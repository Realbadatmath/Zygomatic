# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kids_series_common.py — sound effects, CC0 instrument one-shots, the music bed and speech (lines 509-803 of the pre-split file, verbatim)."""

from __future__ import annotations

from .constants import os, random, shutil, tempfile, threading, FFMPEG, VOICE_POOL_DIR, SR, _log_noop
from .ffmpeg import _run


# ── sound effects: numpy, no library ─────────────────────────────────────────
#
# There is no CC0 cartoon-effects library on this box (see the module
# docstring), so the pops and dings are SYNTHESISED.  It is also the cheaper
# answer: ten deterministic functions cost nothing per episode and cannot
# introduce a licence question.


def _lp_sweep(x, cut, sr=SR):
    """One-pole lowpass whose cutoff moves per sample."""
    import numpy as np

    a = 1.0 - np.exp(-2.0 * np.pi * np.clip(cut, 20.0, sr * 0.45) / sr)
    y = np.empty_like(x)
    z = 0.0
    for i in range(x.size):
        z += a[i] * (x[i] - z)
        y[i] = z
    return y


def _sfx_wave(kind, seconds, seed, kw):
    import numpy as np

    rng = np.random.default_rng(int(seed) & 0x7FFFFFFF)
    seconds = max(0.01, float(seconds))
    n_out = int(round(seconds * SR))

    def _t(dur):
        return np.arange(int(round(min(dur, seconds) * SR)), dtype=np.float64) / SR

    kind = str(kind).lower()
    if kind == 'pop':
        click = rng.uniform(-1.0, 1.0, int(0.002 * SR))
        t = _t(0.040)
        f = 900.0 + (300.0 - 900.0) * (t / max(t[-1], 1e-6))
        chirp = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 60.0)
        y = np.concatenate([click * np.exp(-np.arange(click.size) / (0.0006 * SR)), chirp])
    elif kind in ('ding', 'bell'):
        f0 = float(kw.get('f0', 1320.0 if kind == 'bell' else 880.0))
        t = _t(max(0.8, min(seconds, 3.0)))
        env = np.exp(-t * (3.6 if kind == 'ding' else 2.4))
        y = (
            np.sin(2 * np.pi * f0 * t)
            + 0.55 * np.sin(2 * np.pi * 2.76 * f0 * t)
            + 0.30 * np.sin(2 * np.pi * 5.40 * f0 * t)
        ) * env
    elif kind == 'whoosh':
        t = _t(max(0.8, min(seconds, 3.0)))
        u = t / max(t[-1], 1e-6)
        cut = 300.0 + 2700.0 * np.sin(np.pi * u)  # 300 -> 3000 -> 300
        y = _lp_sweep(rng.uniform(-1.0, 1.0, t.size), cut)
        y *= np.sin(np.pi * u) ** 0.6
    elif kind in ('engine', 'train'):
        rate = float(kw.get('rate_hz', 24.0 if kind == 'engine' else 9.0))
        t = _t(seconds)
        phase = (t * rate) % 1.0
        pulse = np.where(phase < 0.18, 1.0, -0.15)
        brown = np.cumsum(rng.normal(0.0, 1.0, t.size))
        brown /= max(np.max(np.abs(brown)), 1e-9)
        y = _lp_sweep(pulse + 0.55 * brown, np.full(t.size, 400.0))
        if kind == 'train':
            y *= 0.75 + 0.25 * np.sin(2 * np.pi * 1.1 * t)
    elif kind == 'plane':
        t = _t(seconds)
        noise = np.cumsum(rng.normal(0.0, 1.0, t.size))
        noise -= np.linspace(noise[0], noise[-1], t.size)
        noise /= max(np.max(np.abs(noise)), 1e-9)
        y = noise + 0.45 * np.sin(2 * np.pi * 110.0 * t)
        y *= 0.7 + 0.3 * np.sin(2 * np.pi * 0.3 * t)
    elif kind == 'horn':
        t = _t(max(0.6, min(seconds, 3.0)))
        y = np.zeros(t.size)
        for f0 in (330.0, 415.0):
            for k in range(1, 5):
                y += (1.0 / k) * np.sin(2 * np.pi * f0 * k * t)
        env = np.minimum(1.0, t / 0.03) * np.minimum(1.0, (t[-1] - t + 1e-6) / 0.06)
        y *= env
    elif kind == 'splash':
        t = _t(max(0.7, min(seconds, 3.0)))
        u = t / max(t[-1], 1e-6)
        cut = 4000.0 * (200.0 / 4000.0) ** u
        y = _lp_sweep(rng.uniform(-1.0, 1.0, t.size), cut) * np.exp(-u * 3.2)
    elif kind == 'tick':
        m = int(0.003 * SR)
        y = rng.uniform(-1.0, 1.0, m) * np.exp(-np.arange(m) / (0.0008 * SR))
    else:
        raise ValueError(f'unknown sfx kind: {kind}')

    if y.size >= n_out:
        y = y[:n_out]
    else:
        y = np.concatenate([y, np.zeros(n_out - y.size)])
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak > 1e-9:
        y = y * (10.0 ** (-6.0 / 20.0) / peak)  # -6 dBFS peak
    return y


def synth_sfx(kind, out_wav, *, seconds=1.0, seed=0, **kw):
    """One cartoon effect -> a 48 kHz mono 16-bit wav of exactly `seconds`.

    Kinds: pop ding whoosh engine train plane horn splash bell tick.
    Deterministic in `seed`; peak-normalised to -6 dBFS.
    """
    try:
        import soundfile as sf

        y = _sfx_wave(kind, seconds, seed, kw)
        os.makedirs(os.path.dirname(os.path.abspath(out_wav)) or '.', exist_ok=True)
        sf.write(out_wav, y, SR, subtype='PCM_16')
        return os.path.isfile(out_wav)
    except Exception:  # noqa: BLE001 — never fail a run
        return False


# ── CC0 instrument one-shots ─────────────────────────────────────────────────

_INSTRUMENTS = None
_INSTRUMENTS_LOCK = threading.Lock()


def _instruments():
    """The usable slice of the instruments library, loaded once per process.

    'Usable' is a licence decision, not a taste one: cc0 / public-domain only,
    and never a record whose pack forbids AI training.  66,028 records go in,
    ~43,689 come out.
    """
    global _INSTRUMENTS
    if _INSTRUMENTS is not None:
        return _INSTRUMENTS
    with _INSTRUMENTS_LOCK:
        if _INSTRUMENTS is not None:
            return _INSTRUMENTS
        try:
            from zyg_workflows import asset_library_service as A

            recs = A.load_assets('instruments') or []
            root = A._audio_dir('instruments')
        except Exception:  # noqa: BLE001
            _INSTRUMENTS = []
            return _INSTRUMENTS
        keep = []
        for r in recs:
            if str(r.get('license_id') or '').lower() not in ('cc0', 'public-domain'):
                continue
            if r.get('no_ai_training'):
                continue
            keep.append(
                {
                    'instrument': str(r.get('instrument') or '').lower(),
                    'pitch': str(r.get('pitch') or ''),
                    'path': os.path.join(root, r.get('file') or ''),
                    'license_id': str(r.get('license_id') or '').lower(),
                }
            )
        _INSTRUMENTS = keep
        return _INSTRUMENTS


def instrument_shot(family_substr, pitch=None, *, seed=0):
    """A CC0 one-shot path for a family ('piano' -> Osiris_Piano), or None."""
    fam = str(family_substr or '').lower()
    hits = [r for r in _instruments() if fam in r['instrument']]
    if pitch:
        exact = [r for r in hits if r['pitch'].lower() == str(pitch).lower()]
        if exact:
            hits = exact
    hits = [r for r in hits if os.path.isfile(r['path'])]
    if not hits:
        return None
    hits.sort(key=lambda r: r['path'])
    return random.Random(int(seed)).choice(hits)['path']


# ── music bed ────────────────────────────────────────────────────────────────


def music_bed(out_wav, *, seconds, mood='happy', age_band='toddler', seed=0, log_fn=None):
    """A scored, soundfont-rendered instrumental bed.  CPU only, no GPU.

    compose_best returns the winning PLAN (not a tuple), which then goes to
    MIDI and through the MIT soundfont.  The render lands near the requested
    length but not on it — a bar is a bar — so it is trimmed and padded to the
    second the assembler asked for.
    """
    log_fn = log_fn or _log_noop
    seconds = max(1.0, float(seconds))
    try:
        from zyg_workflows import kids_music_theory as T
        from zyg_workflows import kids_music_service as KM
    except Exception as e:  # noqa: BLE001
        log_fn(f'music: unavailable ({type(e).__name__}: {e})')
        return False
    work = tempfile.mkdtemp(prefix='kseries_music_')
    try:
        brief = {'theme': str(mood), 'age_band': age_band, 'mood': mood, 'seconds': int(round(seconds)), 'sung': False}
        plan = T.compose_best(brief, candidates=16, seed0=int(seed))
        if isinstance(plan, tuple):  # tolerated, not expected
            plan = plan[0]
        if not plan:
            log_fn('music: composer returned no plan')
            return False
        mid = os.path.join(work, 'bed.mid')
        raw = os.path.join(work, 'bed.wav')
        KM.write_midi(plan, mid)
        KM.render_soundfont(mid, raw)
        if not os.path.isfile(raw):
            log_fn('music: soundfont render produced no wav')
            return False
        os.makedirs(os.path.dirname(os.path.abspath(out_wav)) or '.', exist_ok=True)
        ok = _run(
            [
                FFMPEG,
                '-y',
                '-i',
                raw,
                '-af',
                f'atrim=0:{seconds:.3f},asetpts=N/SR/TB,apad=whole_dur={seconds:.3f}',
                '-c:a',
                'pcm_s16le',
                '-ar',
                str(SR),
                out_wav,
            ]
        )
        return bool(ok and os.path.isfile(out_wav))
    except Exception as e:  # noqa: BLE001
        log_fn(f'music: failed ({type(e).__name__}: {e})')
        return False
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ── speech ───────────────────────────────────────────────────────────────────

_VRAM_RELEASED = False


def _release_comfy_vram_once(log_fn):
    """IndexTTS-2 wants ~20 GB.  ComfyUI, if it just rendered, is still holding
    it — the .env keeps weights resident on purpose.  Ask for it back once per
    process, before the first line of speech, and never again."""
    global _VRAM_RELEASED
    if _VRAM_RELEASED:
        return
    _VRAM_RELEASED = True
    try:
        from zyg_workflows import kids_video_service as KV

        KV.release_comfy_vram(log_fn)
    except Exception as e:  # noqa: BLE001
        log_fn(f'vram: release skipped ({type(e).__name__})')


def say(text, out_wav, *, voice='f01_warm_alto', seed=7, log_fn=None):
    """One spoken line.  Returns the engine that produced it, or ''.

    IndexTTS-2 first, Chatterbox second.  voice_studio.synth has no fallback of
    its own by design, so the retry is here and it is VISIBLE in the return
    value — a manifest that says 'chatterbox' is how anyone knows the first
    engine was down that day.
    """
    log_fn = log_fn or _log_noop
    text = (text or '').strip()
    if not text:
        return ''
    ref = os.path.join(VOICE_POOL_DIR, f'{voice}.wav')
    if not os.path.isfile(ref):
        log_fn(f'voice: reference missing for {voice}')
        return ''
    _release_comfy_vram_once(log_fn)
    os.makedirs(os.path.dirname(os.path.abspath(out_wav)) or '.', exist_ok=True)
    try:
        from zyg_workflows import voice_studio as VS
    except Exception as e:  # noqa: BLE001
        log_fn(f'voice: voice_studio unavailable ({type(e).__name__}: {e})')
        return ''
    for engine, extra in (('indextts2', {}), ('chatterbox', {'device': 'auto'})):
        p = dict(VS.defaults())
        p['engine'] = engine
        p['eng_seed'] = int(seed)
        p.update(extra)
        try:
            got = VS.synth(text, ref, out_wav, p, log_fn)
        except Exception as e:  # noqa: BLE001
            log_fn(f'voice: {engine} raised ({type(e).__name__}: {e})')
            got = None
        if got and os.path.isfile(out_wav):
            return engine
        log_fn(f'voice: {engine} produced nothing — trying the next engine')
    return ''
