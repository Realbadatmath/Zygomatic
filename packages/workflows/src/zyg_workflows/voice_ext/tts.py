# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Voice-bridge reply voice — the assistant's mouth.

The voice bridge needs ONE thing from the TTS stack that Voice Studio does not
already give it: a cheap, repeatable `say(text)` that answers in a voice the
operator picked, and answers a second time in milliseconds. Everything else —
the voice registry, the knob spec, the preset store, the two engine venvs — is
voice_studio's, and is used from here rather than re-implemented.

Standing policy (unchanged here, only obeyed): IndexTTS-2 is primary,
Chatterbox is the ONLY fallback, Kokoro is gone from the codebase.

Three things this module adds on top of voice_studio.synth:

1. A CACHE keyed by everything that can change the audio (voice, resolved
   engine, the full sanitised knob set, the text). The assistant says the same
   forty sentences all day — "Opening Video Studio", "Done", "I did not catch
   that" — and each of them costs eleven seconds exactly once.
2. A LEVEL CONTRACT. A reply is played through the browser between the
   operator's own speech, so it has to be one predictable loudness: -16 LUFS,
   mono, 24 kHz, with the engines' leading/trailing silence cut off. Untrimmed
   takes put a half-second hole in front of every answer.
3. A resolved ENGINE choice. voice_studio.synth deliberately has no fallback
   inside it (a silent engine swap would make an operator judge a knob move on
   the wrong engine). The bridge is the opposite case: it must always speak, so
   the choice is made HERE, before synth, off free VRAM — the same
   ZYG_INDEXTTS_MIN_VRAM_MB / 21000 MB line the IndexTTS-2 worker itself gates
   on, so 'auto' never picks an engine the worker will then refuse.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time

from zyg_workflows import voice_studio as VS
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_HERE = os.path.dirname(os.path.abspath(__file__))
_CREWS = os.path.dirname(_HERE)

RUNTIME_DIR = os.path.join(_CREWS, 'data', 'runtime', 'voice_bridge')
SAY_DIR = os.path.join(RUNTIME_DIR, 'say')
CONFIG_PATH = os.path.join(RUNTIME_DIR, 'config.json')
_GAP_WAV = os.path.join(RUNTIME_DIR, '_gap250.wav')

ENGINES = ('auto', 'indextts2', 'chatterbox')

# The line the IndexTTS-2 worker itself gates on (indextts2_worker.py --min-vram-mib,
# default 21000). Mirrored rather than guessed: picking indextts2 below it would
# only earn exit code 3 and a wasted model load.
MIN_VRAM_MB = int(os.environ.get('ZYG_INDEXTTS_MIN_VRAM_MB', '21000') or 21000)

# One GPU job at a time. Both engines want the whole card, and two concurrent
# loads starve each other past the worker timeout (voice_studio's own _JOBS
# comment, measured there).
_SYNTH_LOCK = threading.Lock()

# Past this, a single worker call is a long wait for a first word that could
# already be playing. Split on sentence ends and cache each part on its own key.
SPLIT_CHARS = 240
GAP_MS = 250

LUFS = -16.0
SR = 24000


def _ensure_dirs():
    os.makedirs(SAY_DIR, exist_ok=True)


# ────────────────────────────────────────────────────────────── voice registry
def ref_wav_for(vid: str) -> str:
    """The reference wav to clone, for ANY voice in the registry.

    All five registry sources — Abel's hand-written entry, the Maya1 pool, the
    teen bench, the character benches and the Kyutai harvest — write their
    frozen wav to the same key, `seed` (checked in _load_pool_voices,
    _load_teen_voices, _load_bench_voices and _load_kyutai_voices). So this is
    one lookup and not a per-source table. `identity_ref` is deliberately NOT
    used: it is a known-good RENDER kept for drift gating, and cloning a render
    of a clone is a second generation of loss.
    """
    v = VS.voice(vid)
    seed = str((v or {}).get('seed') or '')
    return seed if seed and os.path.isfile(seed) else ''


def _has_active_preset(vid: str) -> bool:
    """Whether a voice has a preset marked active — one stat, not a directory read.

    VS.list_presets() opens and sanitises every preset json for the voice; over
    ~326 voices that is thousands of reads for a picker list that only needs a
    boolean. The marker file is the same source list_presets reads its `active`
    from.
    """
    try:
        return os.path.isfile(os.path.join(VS._voice_preset_dir(vid), '_active.json'))
    except Exception:  # noqa: BLE001 — a picker must render
        return False


def default_voice() -> str:
    """The voice an empty config speaks with: the shipping narrator if he is
    registered, else whatever the registry lists first."""
    if 'abel' in VS.VOICES:
        return 'abel'
    for vid in VS.VOICES:
        return vid
    return ''


# ────────────────────────────────────────────────────────────────────── config
def load_config() -> dict:
    """{voice_id, engine} with the blanks filled in. Never raises."""
    raw = {}
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            raw = json.load(f) or {}
    except (OSError, ValueError):
        raw = {}
    vid = str(raw.get('voice_id') or '').strip().lower()
    if vid not in VS.VOICES:
        vid = default_voice()
    eng = str(raw.get('engine') or 'auto').strip().lower()
    if eng not in ENGINES:
        eng = 'auto'
    out = dict(raw)
    out['voice_id'] = vid
    out['engine'] = eng
    return out


def save_config(patch: dict) -> dict:
    """MERGE, not replace: a POST that names only the engine must not drop the
    operator's voice pick (and vice versa)."""
    _ensure_dirs()
    cur = {}
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            cur = json.load(f) or {}
    except (OSError, ValueError):
        cur = {}
    if isinstance(patch, dict):
        if 'voice_id' in patch:
            vid = str(patch.get('voice_id') or '').strip().lower()
            if vid in VS.VOICES:
                cur['voice_id'] = vid
        if 'engine' in patch:
            eng = str(patch.get('engine') or '').strip().lower()
            if eng in ENGINES:
                cur['engine'] = eng
    cur['updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
    tmp = CONFIG_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cur, f, indent=2)
    os.replace(tmp, CONFIG_PATH)
    return load_config()


# ─────────────────────────────────────────────────────────────── engine choice
def free_vram_mb() -> float:
    """Free VRAM in MB, or -1.0 when nvidia-smi cannot say.

    -1 means "unknown", and unknown must NOT read as "plenty": an unknown GPU
    picks the 4 GB engine, which is the choice that still produces audio on a
    box whose card is busy or absent.
    """
    try:
        r = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=8,
        )
        return float(r.stdout.strip().splitlines()[0].strip())
    except Exception:  # noqa: BLE001 — see docstring
        return -1.0


def choose_engine(engine: str = 'auto') -> str:
    """'auto' -> indextts2 when the worker's own VRAM gate would pass, else
    chatterbox. An explicit engine is honoured as asked."""
    eng = (engine or 'auto').strip().lower()
    if eng in ('indextts2', 'chatterbox'):
        return eng
    return 'indextts2' if free_vram_mb() >= MIN_VRAM_MB else 'chatterbox'


def params_for(vid: str, engine: str) -> dict:
    """The knob set to render with, forced onto the resolved engine."""
    p = VS.sanitize(VS.active_params(vid) or VS.defaults())
    p['engine'] = engine
    return p


# ────────────────────────────────────────────────────────────────── cache keys
def say_key(voice_id: str, engine: str, params: dict, text: str) -> str:
    """Everything that can change the audio, and nothing that cannot.

    The knob set goes in whole and sorted, so adopting a new active preset
    invalidates the cache instead of serving the old voice from it.
    """
    blob = '|'.join(
        [
            str(voice_id or ''),
            str(engine or ''),
            json.dumps(params or {}, sort_keys=True, default=str),
            (text or '').strip(),
        ]
    )
    return hashlib.sha1(blob.encode('utf-8'), usedforsecurity=False).hexdigest()


def cache_path(key: str) -> str:
    return os.path.join(SAY_DIR, key + '.wav')


def split_text(text: str, limit: int = SPLIT_CHARS) -> list:
    """Sentence-sized chunks, each <= `limit` where the sentences allow it.

    Short text is ONE chunk — the common case must not pay for the machinery.
    A single sentence longer than the limit is left whole rather than cut
    mid-clause; the engines handle it, and a chopped clause reads as a stammer.
    """
    t = (text or '').strip()
    if len(t) <= limit:
        return [t] if t else []
    parts, cur = [], ''
    for s in re.split(r'(?<=[.!?\u2026])\s+', t):
        s = s.strip()
        if not s:
            continue
        if cur and len(cur) + 1 + len(s) > limit:
            parts.append(cur)
            cur = s
        else:
            cur = (cur + ' ' + s).strip() if cur else s
    if cur:
        parts.append(cur)
    return parts or [t]


# ──────────────────────────────────────────────────────────── ffmpeg finishing
def _ffmpeg(args: list, timeout: float = 120) -> bool:
    try:
        r = subprocess.run(
            ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y'] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


_TRIM = (
    'silenceremove=start_periods=1:start_silence=0.05:start_threshold=-50dB,'
    'areverse,'
    'silenceremove=start_periods=1:start_silence=0.05:start_threshold=-50dB,'
    'areverse'
)


def post_process(src: str, dst: str) -> bool:
    """One loudness for every reply: trim the engine's silence, then loudnorm to
    -16 LUFS, mono, 24 kHz, 16-bit.

    Trim BEFORE loudnorm: loudnorm measures the whole file, and half a second of
    leading digital silence drags the measured integrated loudness down and
    pushes the speech up over the target.
    """
    ok = _ffmpeg(
        [
            '-i',
            src,
            '-af',
            f'{_TRIM},loudnorm=I={LUFS:g}:TP=-1.5:LRA=11',
            '-ar',
            str(SR),
            '-ac',
            '1',
            '-c:a',
            'pcm_s16le',
            dst,
        ]
    )
    return ok and os.path.isfile(dst) and os.path.getsize(dst) > 44


def _gap_wav() -> str:
    """A 250 ms silence at the reply format, made once, so the parts of a long
    answer can be joined with the concat demuxer and no re-encode."""
    if os.path.isfile(_GAP_WAV) and os.path.getsize(_GAP_WAV) > 44:
        return _GAP_WAV
    _ensure_dirs()
    _ffmpeg(
        ['-f', 'lavfi', '-i', f'anullsrc=r={SR}:cl=mono', '-t', f'{GAP_MS / 1000.0:g}', '-c:a', 'pcm_s16le', _GAP_WAV]
    )
    return _GAP_WAV


def concat_with_gaps(parts: list, dst: str) -> bool:
    """Join finished parts with 250 ms between them. Stream copy — every part is
    already the same pcm_s16le/24k/mono, so there is nothing to re-encode."""
    if not parts:
        return False
    if len(parts) == 1:
        try:
            shutil.copyfile(parts[0], dst)
            return True
        except OSError:
            return False
    gap = _gap_wav()
    lines = []
    for i, p in enumerate(parts):
        if i:
            lines.append(f"file '{gap}'")
        lines.append(f"file '{p}'")
    listing = dst + '.concat.txt'
    with open(listing, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    ok = _ffmpeg(['-f', 'concat', '-safe', '0', '-i', listing, '-c', 'copy', dst])
    try:
        os.remove(listing)
    except OSError as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return ok and os.path.isfile(dst) and os.path.getsize(dst) > 44


# ───────────────────────────────────────────────────────────────── the synthesis
def _synth_part(text: str, vid: str, engine: str, p: dict, log) -> str:
    """One cached part. Returns its cache path, or '' when the engine failed."""
    key = say_key(vid, engine, p, text)
    out = cache_path(key)
    if os.path.isfile(out) and os.path.getsize(out) > 44:
        return out
    ref = ref_wav_for(vid)
    if not ref:
        log(f'no reference wav for voice {vid!r}')
        return ''
    raw = out + '.raw.wav'
    with _SYNTH_LOCK:
        got = VS.synth(text, ref, raw, p, log)
    if not got:
        return ''
    ok = post_process(raw, out)
    try:
        os.remove(raw)
    except OSError as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return out if ok else ''


def say(text: str, voice_id: str = '', engine: str = '') -> dict:
    """The reply voice. Returns {ok, wav_path, cached, ms, engine, voice_id, parts}.

    A cache hit costs one stat. A miss costs the engine once and never again for
    that exact (voice, engine, knobs, text).
    """
    t0 = time.time()
    _ensure_dirs()
    cfg = load_config()
    vid = (voice_id or cfg['voice_id'] or '').strip().lower()
    if vid not in VS.VOICES:
        return {'ok': False, 'error': f'unknown voice {vid!r}', 'ms': 0}
    txt = (text or '').strip()
    if not txt:
        return {'ok': False, 'error': 'empty text', 'ms': 0}

    eng = choose_engine(engine or cfg['engine'])
    p = params_for(vid, eng)
    key = say_key(vid, eng, p, txt)
    out = cache_path(key)
    if os.path.isfile(out) and os.path.getsize(out) > 44:
        return {
            'ok': True,
            'wav_path': out,
            'key': key,
            'cached': True,
            'ms': int((time.time() - t0) * 1000),
            'engine': eng,
            'voice_id': vid,
            'parts': 1,
            'log': [],
        }

    lines = []

    def log(m):
        lines.append(str(m))

    chunks = split_text(txt)
    made = []
    for c in chunks:
        got = _synth_part(c, vid, eng, p, log)
        if not got:
            return {
                'ok': False,
                'error': 'synthesis failed',
                'ms': int((time.time() - t0) * 1000),
                'engine': eng,
                'voice_id': vid,
                'log': lines,
            }
        made.append(got)

    # One part: its own cache entry IS the answer, under its own key, which for a
    # single chunk is the same key as the whole. Nothing to join.
    if len(made) == 1 and made[0] == out:
        pass
    elif not concat_with_gaps(made, out):
        return {
            'ok': False,
            'error': 'concat failed',
            'ms': int((time.time() - t0) * 1000),
            'engine': eng,
            'voice_id': vid,
            'log': lines,
        }
    return {
        'ok': True,
        'wav_path': out,
        'key': key,
        'cached': False,
        'ms': int((time.time() - t0) * 1000),
        'engine': eng,
        'voice_id': vid,
        'parts': len(made),
        'log': lines,
    }


def cache_stats() -> dict:
    _ensure_dirs()
    n, b = 0, 0
    try:
        for fn in os.listdir(SAY_DIR):
            if not fn.endswith('.wav'):
                continue
            n += 1
            try:
                b += os.path.getsize(os.path.join(SAY_DIR, fn))
            except OSError as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    except OSError as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return {'ok': True, 'count': n, 'bytes': b, 'dir': SAY_DIR}


# ──────────────────────────────────────────────────────────────────── ROUTES
def _r_voices(payload: dict, method: str):
    """The picker list. Every registered voice, in registry order (Abel first —
    voice_studio keeps him there on purpose)."""
    rows = [
        {
            'id': v.get('id') or vid,
            'name': v.get('name') or vid,
            'role': v.get('role') or '',
            'has_active_preset': _has_active_preset(vid),
        }
        for vid, v in VS.VOICES.items()
    ]
    cfg = load_config()
    return {'ok': True, 'voices': rows, 'count': len(rows), 'voice_id': cfg['voice_id'], 'engine': cfg['engine']}


def _r_config(payload: dict, method: str):
    if (method or 'GET').upper() == 'POST':
        cfg = save_config(payload or {})
    else:
        cfg = load_config()
    cfg['ok'] = True
    cfg['engines'] = list(ENGINES)
    cfg['resolved_engine'] = choose_engine(cfg['engine'])
    return cfg


def _r_say(payload: dict, method: str):
    """GET -> the wav itself (so an <audio src> can point straight at it).
    POST -> the metadata, for a caller that wants the path and the timing."""
    payload = payload or {}
    res = say(str(payload.get('text') or ''), str(payload.get('voice_id') or ''), str(payload.get('engine') or ''))
    if (method or 'GET').upper() == 'POST':
        return {k: v for k, v in res.items() if k != 'log'} if res.get('ok') else res
    if not res.get('ok'):
        return {'error': res.get('error') or 'say failed', 'code': 500}
    try:
        with open(res['wav_path'], 'rb') as f:
            data = f.read()
    except OSError as e:
        return {'error': f'cache read failed: {e}', 'code': 500}
    return (data, 'audio/wav', 'say.wav')


def _r_prerender(payload: dict, method: str):
    """Warm the cache with the sentences the assistant is about to need. The
    first spoken reply of a session should not be the one that pays for the
    model load."""
    phrases = (payload or {}).get('phrases') or []
    if isinstance(phrases, str):
        phrases = [phrases]
    rendered = cached = failed = 0
    errors = []
    for ph in phrases:
        res = say(str(ph or ''))
        if not res.get('ok'):
            failed += 1
            if len(errors) < 5:
                errors.append({'text': str(ph or '')[:80], 'error': res.get('error') or 'failed'})
        elif res.get('cached'):
            cached += 1
        else:
            rendered += 1
    return {
        'ok': failed == 0,
        'count': len(phrases),
        'rendered': rendered,
        'cached': cached,
        'failed': failed,
        'errors': errors,
    }


def _r_cache(payload: dict, method: str):
    return cache_stats()


ROUTES = {
    'voices': _r_voices,
    'config': _r_config,
    'say': _r_say,
    'prerender': _r_prerender,
    'cache': _r_cache,
}
