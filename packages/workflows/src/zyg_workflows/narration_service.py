# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# narration_service.py — deterministic pause-map narration assembler (2026-07-30)
#
# WHY THIS EXISTS
# ---------------
# TTS engines are unreliable about pauses: they pad sentences with variable
# dead air, and prosody-driven "pauses" drift run-to-run. For the 1672 Dutch
# drama narration the pacing IS the direction — a scene break must be exactly
# 2200 ms, every render. So pauses are never trusted to the engine: each
# segment is synthesized on its own, its edge silence is stripped
# aggressively (~-45 dBFS, <=30 ms pad), and every pause is ASSEMBLED as
# explicit digital silence between segments. A pause_map.json records exactly
# where speech and silence sit, so downstream stages (ambience ducking,
# subtitles, music cues) can align sample-accurately.
#
# Synthesis is REUSED from tts_service.py (voice-seed pick, engine chain, edge
# trim) — no second model loader. tts_service was written to be imported
# from inside the running GUI (`from crewai_web_gui import ...` at its top),
# so when this module runs standalone we pre-seed sys.modules with a minimal
# 'crewai_web_gui' stub carrying only the constants tts_service/subproc_registry
# import — the 4667-line GUI module is never executed here. Inside the GUI the
# real module is already in sys.modules and the stub is skipped.
#
# LICENSE NOTE (commercial publication): IndexTTS-2 ships under bilibili's
# Model Use License Agreement — royalty-free commercial use below 100M MAU /
# RMB 1B revenue, so a solo channel is covered; archive the license text.
# numpy/soundfile are BSD (royalty-free). pydub is importable in
# the venv but numpy+soundfile is used instead for sample-exact, deterministic
# trim/concat. ffmpeg (with GPL librubberband) is invoked strictly as an
# external TOOL — its license governs distribution of the software, not the
# audio it outputs; no GPL code ships with or links into published audio.
# Chatterbox (engine='chatterbox' via abel_voice) is MIT, but its output audio
# ALWAYS carries the Resemble Perth implicit watermark (chatterbox/tts.py
# applies it unconditionally in generate()). Every pause_map records the
# engine's license string ('engine_license', from ENGINE_LICENSES below) so a
# published narration can answer a license audit on its own.
#
# GPU: synthesis now runs on the GPU — IndexTTS-2 needs ~19.7 GB and is driven
# by tts_service in its own venv. tts_service gates on free VRAM before loading
# it (ZYG_INDEXTTS_MIN_VRAM_MB, default 21000) and falls back to the ~4.1 GB
# Chatterbox worker when the card is busy, so a render in flight degrades the
# voice rather than failing the narration.

import json
import os
import subprocess
import sys
import tempfile
import logging as _zyg_logging
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROFILE_PATH = os.path.join(_MODULE_DIR, 'config', 'pause_profiles.json')

# Embedded fallback — load_pause_profiles() must never fail across a module
# boundary, and the assembler must stay deterministic even if the json is
# deleted or corrupted.
_DEFAULT_PROFILES = {
    'calm_period_drama': {
        'sentence': 700,
        'paragraph': 1200,
        'dramatic_beat': 1500,
        'scene_break': 2200,
        'head': 500,
        'tail': 1500,
    },
}

_TARGET_SR = 48000  # everything is assembled at 48 kHz mono
_TRIM_DB = -45.0  # absolute dBFS edge-trim threshold
_TRIM_KEEP_MS = 30  # max natural pad kept on each side
_SILENCE_FLOOR = 0.60  # runtime shrink never goes below 60% of nominal

# Engine license provenance, written into every pause_map as
# engine_params['engine_license']. Unknown engines record 'UNKNOWN' so a
# license audit fails visibly instead of silently. See LICENSE NOTE above.
ENGINE_LICENSES = {
    'indextts2': (
        'bilibili Model Use License Agreement (IndexTTS-2; royalty-free commercial below 100M MAU / RMB 1B revenue)'
    ),
    'chatterbox': 'MIT (ResembleAI Chatterbox; output carries Perth implicit watermark)',
}


def _log_noop(level, msg):
    pass


def _mk_log(log_fn):
    if not log_fn:
        return _log_noop

    def _l(level, msg):
        try:
            try:
                log_fn(level, msg)
            except TypeError:
                # single-arg logger (abel_voice/audio_qc/ambience_ingest house
                # style is log(msg)) — adapt instead of silently dropping every
                # diagnostic behind the exception guard below.
                log_fn(f'[{level}] {msg}')
        except Exception as _exc:
            _zyg_log.debug('log callback raised, message dropped: %s', _exc)

    return _l


# ---------------------------------------------------------------------------
# tts_service bootstrap (standalone-safe)
# ---------------------------------------------------------------------------


def _install_gui_stub():
    """Pre-seed sys.modules['zyg_dashboard.crewai_web_gui'] with the constants tts_service
    and subproc_registry from-import at their module top. These exist only so
    the imports bind — none of them affect this module's code path (the TTS
    engines run in their own venvs behind tts_service's worker subprocesses).
    Never installed when the real GUI module is already loaded."""
    if 'crewai_web_gui' in sys.modules:
        return
    import threading
    import types
    from datetime import datetime, timezone

    stub = types.ModuleType('crewai_web_gui')
    stub.__doc__ = 'narration_service standalone stub — NOT the real GUI module'
    stub._DEMONET_TIER1 = set()
    stub._DEMONET_TIER2 = set()
    stub._DEMONET_TIER3_TITLE = set()
    stub._TITLE_SYNONYMS = {}
    stub._SUBPROC_REGISTRY = {}
    stub._SUBPROC_LOCK = threading.Lock()
    stub._SUBPROC_SYNTHETIC_COUNTER = [10_000_000]

    def _agent_log(*_a, **_k):
        pass

    def _ams_iso(timespec='milliseconds'):
        return datetime.now(timezone.utc).isoformat(timespec=timespec)

    stub._agent_log = _agent_log
    stub._ams_iso = _ams_iso
    sys.modules['zyg_dashboard.crewai_web_gui'] = stub


def _get_tts_service(log_fn=None):
    """Import tts_service (stub-guarded). Returns module or None — never raises."""
    _l = _mk_log(log_fn)
    if 'tts_service' in sys.modules:
        return sys.modules['zyg_workflows.tts_service']
    try:
        _install_gui_stub()
        if _MODULE_DIR not in sys.path:
            sys.path.insert(0, _MODULE_DIR)
        from zyg_workflows import tts_service as _ts

        return _ts
    except Exception as e:
        _l('ERROR', f'narration: cannot import tts_service — {e!r}')
        return None


# ---------------------------------------------------------------------------
# profiles
# ---------------------------------------------------------------------------


def load_pause_profiles() -> dict:
    """Read config/pause_profiles.json; fail-safe to the embedded default."""
    try:
        with open(_PROFILE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and data:
            return data
    except Exception as _exc:
        _zyg_log.warning(
            'narration profiles at %s unreadable, falling back to the built-in defaults: %s', _PROFILE_PATH, _exc
        )
    return json.loads(json.dumps(_DEFAULT_PROFILES))  # deep copy


# ---------------------------------------------------------------------------
# audio helpers (numpy + soundfile — sample-exact, deterministic)
# ---------------------------------------------------------------------------


def _trim_edges_db(audio, sr, thr_db=_TRIM_DB, keep_ms=_TRIM_KEEP_MS):
    """Absolute-dBFS edge trim (full scale = 1.0). Deterministic pause lengths
    depend on this strip: any engine-supplied edge padding surviving here would
    silently lengthen every assembled pause."""
    import numpy as np

    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    amp = np.abs(audio)
    if amp.size == 0:
        return audio
    thr = 10.0 ** (thr_db / 20.0)
    nz = np.nonzero(amp > thr)[0]
    if nz.size == 0:
        return audio  # all below threshold — leave untouched (fail-safe)
    keep = int(sr * keep_ms / 1000)
    s = max(0, int(nz[0]) - keep)
    e = min(len(audio), int(nz[-1]) + keep)
    return audio[s:e]


def _resample_wav_48k_mono(in_wav, out_wav, log_fn=None):
    """ffmpeg resample to 48 kHz mono pcm_s16le. Returns out_wav or None."""
    _l = _mk_log(log_fn)
    try:
        r = subprocess.run(
            [exe('ffmpeg'), '-y', '-i', in_wav, '-ac', '1', '-ar', str(_TARGET_SR), '-c:a', 'pcm_s16le', out_wav],
            capture_output=True,
            timeout=300,
        )
        if r.returncode == 0 and os.path.isfile(out_wav) and os.path.getsize(out_wav) > 44:
            return out_wav
        _l('WARNING', f'narration: resample failed rc={r.returncode} ({(r.stderr or b"")[-200:]})')
    except Exception as e:
        _l('WARNING', f'narration: resample exception — {e!r}')
    return None


def _read_wav_mono(path):
    """soundfile read -> (float32 mono array, sr) or (None, 0)."""
    try:
        import numpy as np
        import soundfile as sf

        audio, sr = sf.read(path, dtype='float32', always_2d=False)
        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        return audio, int(sr)
    except Exception:
        return None, 0


# ---------------------------------------------------------------------------
# segment synthesis
# ---------------------------------------------------------------------------


def synth_segment(text, out_wav, voice_id='', seed_wav='', log_fn=None):
    """Synthesize ONE narration segment via tts_service (IndexTTS-2 → Chatterbox).

    Delivered UN-normalized: this module ducks and masters the whole programme
    at -14 LUFS, and per-segment loudnorm would flatten the dynamics between
    segments. Edge silence is trimmed aggressively (~-45 dBFS absolute, <=30 ms
    pad) so assembled pause lengths are exact. Returns out_wav or None.
    """
    _l = _mk_log(log_fn)
    ts = _get_tts_service(log_fn)
    if ts is None:
        return None
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as e:
        _l('ERROR', f'narration: missing dependency — {e}')
        return None

    try:
        clean = ts._tts_clean_text(text or '')
        if not clean:
            _l('WARNING', 'narration: empty segment text after clean')
            return None
        out_abs = os.path.abspath(out_wav)
        os.makedirs(os.path.dirname(out_abs) or '.', exist_ok=True)
        ok, _ = ts._tts_shared(
            clean, out_abs, 'narration segment', log_fn=None, voice_id=voice_id, seed_wav=seed_wav, loudnorm=False
        )
        if not (ok and os.path.isfile(out_abs)):
            _l('WARNING', f'narration: no audio for segment ({clean[:60]!r})')
            return None
        # tts_service trims at 1% of peak; the absolute -45 dBFS pass then
        # removes any low-level room tone it kept, so pauses stay exact.
        audio, sr = sf.read(out_abs, dtype='float32', always_2d=False)
        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        audio = _trim_edges_db(audio, sr)
        if audio.size == 0:
            _l('WARNING', 'narration: segment fully trimmed away')
            return None
        sf.write(out_abs, audio, sr, subtype='PCM_16')
        _l('INFO', f'narration: segment OK {audio.size / sr:.2f}s (voice={voice_id or "(default)"})')
        return out_abs
    except Exception as e:
        _l('ERROR', f'narration: synth failed — {e!r}')
        return None


def pitch_lift(in_wav, out_wav, semitones=2.0):
    """Formant-preserving pitch shift via ffmpeg librubberband (tool-use only;
    see module license note). Returns out_wav or None."""
    try:
        factor = 2.0 ** (float(semitones) / 12.0)
        out_abs = os.path.abspath(out_wav)
        r = subprocess.run(
            [
                exe('ffmpeg'),
                '-y',
                '-i',
                in_wav,
                '-af',
                f'rubberband=pitch={factor:.8f}:formant=preserved',
                '-c:a',
                'pcm_s16le',
                out_abs,
            ],
            capture_output=True,
            timeout=300,
        )
        if r.returncode == 0 and os.path.isfile(out_abs) and os.path.getsize(out_abs) > 44:
            return out_abs
    except Exception as _exc:
        _zyg_log.warning('rubberband pitch shift failed, the segment stays unshifted: %s', _exc)
    return None


def _synth_segment(engine, text, out_wav, engine_kwargs, log_fn=None):
    """Engine adapter. 'indextts2' is built-in (and falls back to Chatterbox
    inside tts_service); 'chatterbox' calls abel_voice.chatterbox_synth_segment
    (text, out_wav, **engine_kwargs) for the Abel frozen-seed clone path
    (lazy import — the Abel voice-clone module ships separately)."""
    _l = _mk_log(log_fn)
    kwargs = dict(engine_kwargs or {})
    if engine == 'indextts2':
        allowed = {'voice_id', 'seed_wav'}
        kw = {k: v for k, v in kwargs.items() if k in allowed}
        return synth_segment(text, out_wav, log_fn=log_fn, **kw)
    if engine == 'chatterbox':
        try:
            from zyg_workflows import abel_voice

            fn = getattr(abel_voice, 'chatterbox_synth_segment', None)
        except ImportError:
            fn = None
        if fn is None:
            _l(
                'ERROR',
                "narration: engine='chatterbox' requested but "
                'abel_voice.chatterbox_synth_segment is not available '
                '— install/deploy the abel_voice module or use '
                "engine='indextts2'",
            )
            return None
        try:
            # Thread the logger through (level-stripped to the single-arg
            # contract) so the chatterbox worker's stderr/timeout detail is not
            # discarded — without this the only surviving diagnostic is the
            # generic 'segment i synth failed'.
            kwargs.setdefault('log_fn', lambda m: _l('INFO', m))
            return fn(text, out_wav, **kwargs)
        except Exception as e:
            _l('ERROR', f'narration: chatterbox synth failed — {e!r}')
            return None
    _l('ERROR', f'narration: unknown engine {engine!r} (indextts2|chatterbox)')
    return None


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------


def _resolve_pause_ms(spec, prof, default_key, log_fn=None):
    """pause_after value -> ms. Named key looks up the profile; int/float is
    literal ms; None/unknown falls back to prof[default_key]."""
    _l = _mk_log(log_fn)
    if isinstance(spec, bool):
        spec = None
    if isinstance(spec, (int, float)):
        return max(0, int(spec))
    if isinstance(spec, str):
        key = spec.strip()
        if key in prof:
            return max(0, int(prof[key]))
        _l('WARNING', f'narration: unknown pause key {key!r} — using {default_key!r}')
    return max(0, int(prof.get(default_key, 700)))


def assemble_narration(
    segments,
    out_wav,
    profile='calm_period_drama',
    engine='indextts2',
    engine_kwargs=None,
    pitch_semitones=0.0,
    target_runtime_s=None,
    log_fn=None,
):
    """Assemble narration with EXACT, deterministic pauses.

    segments: [{'text': str, 'pause_after': 'scene_break'|int_ms|None}]
      - named pause_after keys resolve through the profile
      - int/float pause_after is literal ms
      - None between segments -> profile 'sentence'
      - pause_after of the LAST segment is the tail; None -> profile 'tail'
    Layout: head silence + seg1 + pause1 + ... + segN + tail silence.
    If target_runtime_s is exceeded, all inserted silences shrink
    proportionally (floor 60% of nominal); 'over_runtime': True if still over.
    Writes <stem>.pause_map.json NEXT TO the wav (named after the stem so two
    builds sharing an out_dir never clobber each other's map; written
    atomically via tmp + os.replace). Returns
    {'wav','pause_map','duration_s','over_runtime'} or None.
    """
    _l = _mk_log(log_fn)
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as e:
        _l('ERROR', f'narration: missing dependency — {e}')
        return None

    if not segments:
        _l('ERROR', 'narration: no segments given')
        return None
    profiles = load_pause_profiles()
    prof = profiles.get(profile)
    if not isinstance(prof, dict):
        _l('ERROR', f'narration: unknown pause profile {profile!r} (have: {sorted(profiles)})')
        return None

    out_abs = os.path.abspath(out_wav)
    out_dir = os.path.dirname(out_abs) or '.'
    os.makedirs(out_dir, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix='narration_asm_')

    try:
        # -- 1. per-segment synth -> pitch -> 48k mono -> re-trim ------------
        seg_audio = []  # list of float32 arrays @ 48k
        for i, seg in enumerate(segments):
            text = (seg or {}).get('text', '')
            raw = os.path.join(tmp_dir, f'seg_{i:03d}_raw.wav')
            if _synth_segment(engine, text, raw, engine_kwargs, log_fn) is None:
                _l('ERROR', f'narration: segment {i} synth failed — aborting')
                return None
            cur = raw
            if pitch_semitones:
                lifted = os.path.join(tmp_dir, f'seg_{i:03d}_pitch.wav')
                if pitch_lift(cur, lifted, pitch_semitones) is None:
                    _l('ERROR', f'narration: segment {i} pitch_lift failed — aborting')
                    return None
                cur = lifted
            rs = os.path.join(tmp_dir, f'seg_{i:03d}_48k.wav')
            if _resample_wav_48k_mono(cur, rs, log_fn) is None:
                _l('ERROR', f'narration: segment {i} resample failed — aborting')
                return None
            audio, sr = _read_wav_mono(rs)
            if audio is None or sr != _TARGET_SR:
                _l('ERROR', f'narration: segment {i} readback failed')
                return None
            # Re-trim after pitch/resample: rubberband + resampling can add a
            # few ms of edge padding, which would corrupt the pause map.
            audio = _trim_edges_db(audio, _TARGET_SR)
            if audio.size == 0:
                _l('ERROR', f'narration: segment {i} empty after trim')
                return None
            seg_audio.append(audio)

        # -- 2. nominal silence plan ----------------------------------------
        head_ms = max(0, int(prof.get('head', 0)))
        inter_ms = [
            _resolve_pause_ms(segments[i].get('pause_after'), prof, 'sentence', log_fn)
            for i in range(len(segments) - 1)
        ]
        last_spec = segments[-1].get('pause_after')
        tail_ms = (
            _resolve_pause_ms(last_spec, prof, 'tail', log_fn)
            if last_spec is not None
            else max(0, int(prof.get('tail', 0)))
        )

        speech_s = sum(len(a) for a in seg_audio) / _TARGET_SR
        sil_nom_ms = head_ms + sum(inter_ms) + tail_ms
        total_nom_s = speech_s + sil_nom_ms / 1000.0

        # -- 3. runtime budget: shrink silences, floor 60% ------------------
        scale = 1.0
        over_runtime = False
        if target_runtime_s is not None and total_nom_s > float(target_runtime_s):
            avail_ms = max(0.0, (float(target_runtime_s) - speech_s) * 1000.0)
            scale = (avail_ms / sil_nom_ms) if sil_nom_ms > 0 else 1.0
            scale = max(_SILENCE_FLOOR, min(1.0, scale))
            _l(
                'INFO',
                f'narration: total {total_nom_s:.2f}s > target '
                f'{float(target_runtime_s):.2f}s — shrinking silences '
                f'to {scale * 100:.0f}% of nominal',
            )
        head_act = int(round(head_ms * scale))
        inter_act = [int(round(m * scale)) for m in inter_ms]
        tail_act = int(round(tail_ms * scale))

        # -- 4. sample-exact concatenation ----------------------------------
        def _sil(ms):
            return np.zeros(int(round(ms * _TARGET_SR / 1000.0)), dtype=np.float32)

        pieces = [_sil(head_act)]
        seg_times = []
        silences = []
        cursor = len(pieces[0])
        for i, audio in enumerate(seg_audio):
            start_s = cursor / _TARGET_SR
            pieces.append(audio)
            cursor += len(audio)
            seg_times.append(
                {
                    'i': i,
                    'text': segments[i].get('text', ''),
                    'start_s': round(start_s, 4),
                    'end_s': round(cursor / _TARGET_SR, 4),
                }
            )
            if i < len(seg_audio) - 1:
                silences.append({'after': i, 'ms': inter_act[i], 'start_s': round(cursor / _TARGET_SR, 4)})
                gap = _sil(inter_act[i])
                pieces.append(gap)
                cursor += len(gap)
        pieces.append(_sil(tail_act))
        cursor += len(pieces[-1])

        full = np.concatenate(pieces)
        total_s = len(full) / _TARGET_SR
        if target_runtime_s is not None and total_s > float(target_runtime_s) + 0.05:
            over_runtime = True
            _l(
                'WARNING',
                f'narration: still over target after floor — {total_s:.2f}s vs {float(target_runtime_s):.2f}s',
            )
        sf.write(out_abs, full, _TARGET_SR, subtype='PCM_16')

        # -- 5. pause map ----------------------------------------------------
        pause_map = {
            'profile': profile,
            'engine': engine,
            'engine_params': {
                'engine_kwargs': dict(engine_kwargs or {}),
                'engine_license': ENGINE_LICENSES.get(engine, 'UNKNOWN'),
                'pitch_semitones': float(pitch_semitones),
                'silence_scale': round(scale, 4),
                'profile_values': prof,
                'sample_rate': _TARGET_SR,
            },
            'segments': seg_times,
            'silences': silences,
            'head_ms': head_act,
            'tail_ms': tail_act,
            'total_s': round(total_s, 4),
        }
        # Named after the stem (not a fixed name) so parallel builds in one
        # out_dir cannot clobber each other's map; atomic so a kill mid-write
        # never leaves a truncated map beside a good stem.
        pm_path = os.path.splitext(out_abs)[0] + '.pause_map.json'
        pm_tmp = pm_path + '.tmp'
        with open(pm_tmp, 'w', encoding='utf-8') as f:
            json.dump(pause_map, f, indent=2, ensure_ascii=False)
        os.replace(pm_tmp, pm_path)

        _l(
            'INFO',
            f'narration: assembled {len(seg_audio)} segments -> {total_s:.2f}s ({os.path.getsize(out_abs) // 1024} KB)',
        )
        return {'wav': out_abs, 'pause_map': pm_path, 'duration_s': round(total_s, 4), 'over_runtime': over_runtime}
    except Exception as e:
        _l('ERROR', f'narration: assemble failed — {e!r}')
        return None
    finally:
        try:
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception as _exc:
            _zyg_log.debug('temp dir %s cleanup skipped: %s', tmp_dir, _exc)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------


def _demo(out_dir):
    """Abel opening lines — the reference render for pacing QA."""

    def _print_log(level, msg):
        _zyg_log.info(f'[{level}] {msg}')

    segs = [
        {'text': 'What we speak is not to be written.', 'pause_after': 'paragraph'},
        {
            'text': 'What we write is not to be spoken; therefore, I will tread '
            'carefully in the telling of our journey.',
            'pause_after': 'scene_break',
        },
        {'text': 'In the year of 1672...', 'pause_after': None},
    ]
    os.makedirs(out_dir, exist_ok=True)
    result = assemble_narration(
        segs,
        os.path.join(out_dir, 'abel_demo.wav'),
        profile='calm_period_drama',
        engine='indextts2',
        engine_kwargs={'voice': 'am_michael', 'speed': 0.87, 'lang_code': 'a', 'force_device': 'cpu'},
        pitch_semitones=2.0,
        target_runtime_s=18.5,
        log_fn=_print_log,
    )
    _zyg_log.info(result)
    return result


if __name__ == '__main__':
    import argparse

    ap = argparse.ArgumentParser(description='Deterministic pause-map narration assembler')
    ap.add_argument('--demo', metavar='OUT_DIR', help='render the Abel demo script into OUT_DIR')
    args = ap.parse_args()
    if args.demo:
        sys.exit(0 if _demo(args.demo) else 1)
    ap.print_help()
