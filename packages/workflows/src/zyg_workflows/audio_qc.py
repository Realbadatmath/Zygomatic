# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""audio_qc.py — automated QC gates for the narration + ambience audio stack.

2026-07-30: Built for the 1672 Dutch-drama narration pipeline. The audio stack
renders narration stems (TTS + scripted pauses from a pause_map.json), ambience
beds, and a loudness-normalized master. Nothing was MEASURING those outputs:
a stem with a dropped beat, runaway pause, hot master, or clicky tail sailed
straight into publish. This module is the audio twin of pipeline_debug.py's
visual QC: every gate returns a dict with a measured verdict, never raises
across the module boundary, and hard gates fail CLOSED (tool breakage = not ok)
while the semantic CLAP gate fails OPEN ('ok': None -> operator escalation),
because its weights may still be downloading in a parallel task.

Gates:
  measure_loudness / qc_lufs  — ffmpeg ebur128 (integrated LUFS, true peak, LRA)
  qc_silence_map              — ffmpeg silencedetect vs the scripted pause map
  qc_wpm                      — faster-whisper (shared zyg_whisper loader, forced
                                CPU: a GPU render owns the card) speech-span
                                words-per-minute + script match ratio
                                (voiced-only pace kept as 'articulation_wpm'
                                diagnostic, never gated)
  qc_runtime                  — ffprobe duration cap
  qc_fade                     — tail-window RMS must be near-digital-silence
  qc_clap                     — SOFT: laion/clap-htsat-fused zero-shot audio tags
  run_stem_gates / run_master_gates — aggregates (soft-None gates don't veto)

License posture (commercial publication): these gates are analysis-only — they
never write a sample into published audio. ffmpeg/ffprobe are invoked as
external tools; faster-whisper (MIT), soundfile (BSD), numpy (BSD),
transformers (Apache-2.0) and the CLAP checkpoint are measurement components.

pause_map.json contract (written by the narration renderer):
  { "head_ms": 0, "tail_ms": 0,
    "silences": [ {"beat": "b01", "start_s": 2.0, "ms": 1200}, ... ] }
head/tail entries below the 250 ms detection floor are skipped (undetectable).

CPU-only by design: qc_wpm pins the shared whisper loader to CPU via env
(CUDA_VISIBLE_DEVICES="" so an uninitialized torch never creates a CUDA
context, plus a sky-high ZYG_WHISPER_FW_MIN_VRAM_MB floor so an already-
initialized context still routes to CPU); qc_clap loads on CPU and never
calls .cuda()/.to('cuda').

Self-test: python3 audio_qc.py --selftest <out_dir>
           python3 audio_qc.py --clap-check <wav> (soft-gate wiring check)
"""

import os
import sys
import json
import re
import threading

from zyg_workflows.bin import exe

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

_SILENCE_NOISE_DB = -35.0
_SILENCE_MIN_S = 0.25

_CLAP_CACHE = {}
_CLAP_LOCK = threading.Lock()
#: The hub ref the CLAP loads resolve. The commit this box cached is not recorded anywhere, so
#: 'main' is the honest pin until someone writes the sha down; ``ZYG_AUDIO_QC_CLAP_REVISION``
#: overrides it. Without a ref at all a moved branch would be followed silently.
_CLAP_REVISION = os.environ.get('ZYG_AUDIO_QC_CLAP_REVISION', '').strip() or 'main'


def _log_noop(_m):
    pass


# ── subprocess helpers ───────────────────────────────────────────────────────


def _run_cmd(args, timeout=600):
    """Run a command, return (rc, stdout, stderr) — never raises."""
    import subprocess

    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout)
        return (p.returncode, p.stdout.decode('utf-8', 'replace'), p.stderr.decode('utf-8', 'replace'))
    except Exception as e:
        return (-1, '', f'{type(e).__name__}: {e}')


def _ffprobe_duration(path):
    """Duration in seconds via ffprobe, or None."""
    rc, out, _err = _run_cmd(
        [
            'ffprobe',
            '-v',
            'error',
            '-show_entries',
            'format=duration',
            '-of',
            'default=noprint_wrappers=1:nokey=1',
            path,
        ],
        timeout=60,
    )
    if rc != 0:
        return None
    try:
        return float(out.strip())
    except ValueError:
        return None


# ── loudness ─────────────────────────────────────────────────────────────────


def measure_loudness(path, log_fn=None):
    """EBU R128 summary via ffmpeg ebur128=peak=true.

    Returns {'ok': True, 'lufs': I, 'tp': true_peak_dBFS, 'lra': LU} or
    {'ok': False, 'reason': ...}.
    """
    log = log_fn or _log_noop
    if not path or not os.path.isfile(path):
        return {'ok': False, 'reason': f'file not found: {path}'}
    rc, _out, err = _run_cmd(
        [
            exe('ffmpeg'),
            '-nostdin',
            '-hide_banner',
            '-nostats',
            '-i',
            path,
            '-af',
            'ebur128=peak=true',
            '-f',
            'null',
            '-',
        ]
    )
    if rc != 0:
        return {'ok': False, 'reason': f'ffmpeg rc={rc}: {err[-300:]}'}
    # Summary block (stderr):
    #   Integrated loudness:\n    I:   -14.0 LUFS ...
    #   Loudness range:\n    LRA:   2.1 LU ...  (avoid the "LRA low/high" lines)
    #   True peak:\n    Peak:  -1.2 dBFS
    m_i = re.search(r'Integrated loudness:\s*\n\s*I:\s*(-?[\d.]+|nan)\s*LUFS', err)
    m_lra = re.search(r'^\s*LRA:\s*(-?[\d.]+|nan)\s*LU\b', err, re.M)
    m_tp = re.search(r'True peak:\s*\n\s*Peak:\s*(-?[\d.]+|nan|-inf|inf)\s*dBFS', err)
    if not (m_i and m_tp):
        return {'ok': False, 'reason': 'ebur128 summary not found in ffmpeg output'}
    try:
        lufs = float(m_i.group(1))
        tp = float(m_tp.group(1))
        lra = float(m_lra.group(1)) if m_lra else None
    except ValueError:
        return {'ok': False, 'reason': f'unparseable ebur128 values (I={m_i.group(1)}, Peak={m_tp.group(1)})'}
    res = {'ok': True, 'lufs': round(lufs, 2), 'tp': round(tp, 2), 'lra': round(lra, 2) if lra is not None else None}
    log(f'[audio_qc] loudness {os.path.basename(path)}: {res}')
    return res


def qc_lufs(path, target=-14.0, tol=1.0, tp_max=-1.0, log_fn=None):
    """Gate: |integrated LUFS - target| <= tol AND true peak <= tp_max."""
    m = measure_loudness(path, log_fn=log_fn)
    if not m.get('ok'):
        return {
            'ok': False,
            'reason': m.get('reason', 'loudness measurement failed'),
            'target': target,
            'tol': tol,
            'tp_max': tp_max,
        }
    lufs_ok = abs(m['lufs'] - target) <= tol
    tp_ok = m['tp'] <= tp_max
    return {
        'ok': bool(lufs_ok and tp_ok),
        'lufs': m['lufs'],
        'tp': m['tp'],
        'lra': m['lra'],
        'target': target,
        'tol': tol,
        'tp_max': tp_max,
        'lufs_ok': bool(lufs_ok),
        'tp_ok': bool(tp_ok),
    }


# ── silence map ──────────────────────────────────────────────────────────────


def _detect_silences(path, noise_db=_SILENCE_NOISE_DB, min_s=_SILENCE_MIN_S):
    """Detected silences via ffmpeg silencedetect.

    Returns (list_of_{start_s,end_s,ms}, duration_s) or (None, reason_str).
    A silence still open at EOF (no silence_end line) is closed at file end.
    """
    dur = _ffprobe_duration(path)
    if dur is None:
        return None, f'ffprobe could not read duration of {path}'
    rc, _out, err = _run_cmd(
        [
            'ffmpeg',
            '-nostdin',
            '-hide_banner',
            '-nostats',
            '-i',
            path,
            '-af',
            f'silencedetect=noise={noise_db}dB:d={min_s}',
            '-f',
            'null',
            '-',
        ]
    )
    if rc != 0:
        return None, f'ffmpeg rc={rc}: {err[-300:]}'
    silences, open_start = [], None
    for line in err.splitlines():
        ms_ = re.search(r'silence_start:\s*(-?[\d.]+)', line)
        me_ = re.search(r'silence_end:\s*(-?[\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)', line)
        if ms_:
            open_start = max(0.0, float(ms_.group(1)))
        elif me_ and open_start is not None:
            end = float(me_.group(1))
            silences.append(
                {'start_s': round(open_start, 3), 'end_s': round(end, 3), 'ms': round((end - open_start) * 1000.0)}
            )
            open_start = None
    if open_start is not None:  # file ended mid-silence
        silences.append(
            {'start_s': round(open_start, 3), 'end_s': round(dur, 3), 'ms': round((dur - open_start) * 1000.0)}
        )
    return silences, dur


def qc_silence_map(stem_wav, pause_map_json, tol_ms=150, unscripted_max_ms=800, log_fn=None):
    """Gate: every scripted pause exists where scripted; no long rogue silences.

    pause_map_json: path to the renderer's pause_map.json (or an already-loaded
    dict). Each entry in its 'silences' list ({'start_s','ms'[,'beat']}) — plus
    'head_ms'/'tail_ms' when >= the 250 ms detection floor — must match a
    detected silence within tol_ms in BOTH position and duration. Any detected
    silence longer than unscripted_max_ms that matches no scripted entry fails
    the gate (a TTS stall / dropped beat).
    """
    log = log_fn or _log_noop
    try:
        if isinstance(pause_map_json, dict):
            pmap = pause_map_json
        else:
            with open(pause_map_json, 'r', encoding='utf-8') as fh:
                pmap = json.load(fh)
    except Exception as e:
        return {'ok': False, 'reason': f'pause map unreadable: {type(e).__name__}: {e}'}

    detected, dur_or_reason = _detect_silences(stem_wav)
    if detected is None:
        return {'ok': False, 'reason': dur_or_reason}
    duration_s = dur_or_reason

    floor_ms = _SILENCE_MIN_S * 1000.0
    expected = []
    head_ms = float(pmap.get('head_ms') or 0)
    tail_ms = float(pmap.get('tail_ms') or 0)
    if head_ms >= floor_ms:
        expected.append({'beat': '__head__', 'start_s': 0.0, 'ms': head_ms})
    for i, s in enumerate(pmap.get('silences') or []):
        try:
            expected.append(
                {'beat': str(s.get('beat', f'silence[{i}]')), 'start_s': float(s['start_s']), 'ms': float(s['ms'])}
            )
        except (KeyError, TypeError, ValueError):
            return {'ok': False, 'reason': f'malformed pause map entry #{i}: {s!r}'}
    if tail_ms >= floor_ms:
        expected.append({'beat': '__tail__', 'start_s': duration_s - tail_ms / 1000.0, 'ms': tail_ms})

    used, beats = set(), []
    for exp in expected:
        best_i, best_err = None, None
        for i, d in enumerate(detected):
            if i in used:
                continue
            err = abs(d['start_s'] - exp['start_s'])
            if best_i is None or err < best_err:
                best_i, best_err = i, err
        row = {
            'beat': exp['beat'],
            'expected_start_s': round(exp['start_s'], 3),
            'expected_ms': round(exp['ms']),
            'matched': False,
        }
        if best_i is not None:
            d = detected[best_i]
            start_err_ms = abs(d['start_s'] - exp['start_s']) * 1000.0
            dur_err_ms = abs(d['ms'] - exp['ms'])
            row.update(
                {
                    'detected_start_s': d['start_s'],
                    'detected_ms': d['ms'],
                    'start_err_ms': round(start_err_ms),
                    'dur_err_ms': round(dur_err_ms),
                }
            )
            if start_err_ms <= tol_ms and dur_err_ms <= tol_ms:
                row['matched'] = True
                used.add(best_i)
        beats.append(row)

    unscripted = [d for i, d in enumerate(detected) if i not in used and d['ms'] > unscripted_max_ms]
    ok = all(b['matched'] for b in beats) and not unscripted
    res = {
        'ok': bool(ok),
        'beats': beats,
        'unscripted': unscripted,
        'detected': detected,
        'n_expected': len(expected),
        'n_detected': len(detected),
        'tol_ms': tol_ms,
        'unscripted_max_ms': unscripted_max_ms,
        'duration_s': round(duration_s, 3),
    }
    log(
        f'[audio_qc] silence_map {os.path.basename(str(stem_wav))}: ok={ok} '
        f'({sum(b["matched"] for b in beats)}/{len(expected)} beats, '
        f'{len(unscripted)} unscripted)'
    )
    return res


# ── words per minute / script match ──────────────────────────────────────────


def _normalize_text(t):
    return re.sub(r'\s+', ' ', re.sub(r'[^0-9a-zà-ÿ]+', ' ', (t or '').lower())).strip()


_WPM_RANGE_DEFAULT = (125, 165)


def qc_wpm(stem_wav, script_text, wpm_range=_WPM_RANGE_DEFAULT, min_match=0.9, log_fn=None):
    """Gate: narration pace (SPEECH-SPAN words per minute) + script fidelity.

    Reuses the shared zyg_whisper loader, pinned to CPU (see module docstring —
    a GPU render owns the card, so the env pins below make _pick_device_compute
    land on cpu/int8 without ever creating a CUDA context).

    wpm is measured over the speech span (last word end - first word start):
    whisper VAD already excludes head/tail silence, while scripted mid-beats
    count — matching how the audiobook pacing convention the default band
    (125, 165) encodes is actually quoted on pause-INCLUSIVE audio. The
    reference-good narration stem measures 135.9 span-wpm.
    The old voiced-only figure (sum of word durations, pauses excluded) runs
    30-60 wpm hotter and is kept as the 'articulation_wpm' DIAGNOSTIC: it is
    pause-independent and catches engine speed regressions (speed 0.87 ->
    ~181, 1.0 -> ~208), logged outside its ~150-210 sanity band but NEVER
    gated. wpm_range=None selects the module default. Transcript is
    fuzzy-matched against the script with difflib.
    """
    log = log_fn or _log_noop
    if wpm_range is None:
        wpm_range = _WPM_RANGE_DEFAULT
    if not stem_wav or not os.path.isfile(stem_wav):
        return {'ok': False, 'reason': f'file not found: {stem_wav}'}
    saved = {k: os.environ.get(k) for k in ('CUDA_VISIBLE_DEVICES', 'ZYG_WHISPER_FW_MIN_VRAM_MB')}
    try:
        os.environ['CUDA_VISIBLE_DEVICES'] = ''
        os.environ['ZYG_WHISPER_FW_MIN_VRAM_MB'] = '999999999'
        try:
            import zyg_whisper
        except ImportError:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import zyg_whisper
        lang = os.environ.get('ZYG_AUDIO_QC_LANG', 'en')
        segs, _info = zyg_whisper.transcribe_segments(stem_wav, language=lang, want_words=True, vad=True)
    except Exception as e:
        return {'ok': False, 'reason': f'transcription failed: {type(e).__name__}: {e}'[:300]}
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    words = [w for s in segs for w in s.get('words') or []]
    n_words = len(words)
    voiced_s = sum(max(0.0, w['end'] - w['start']) for w in words)
    span_s = (float(words[-1]['end']) - float(words[0]['start'])) if words else 0.0
    if n_words < 5 or span_s <= 0:
        return {
            'ok': False,
            'reason': 'too few words for pace measurement',
            'n_words': n_words,
            'wpm': None,
            'match_ratio': None,
        }
    wpm = n_words / span_s * 60.0
    articulation_wpm = (n_words / voiced_s * 60.0) if voiced_s > 0 else None

    import difflib

    transcript = ' '.join(s.get('text', '') for s in segs)
    # 2026-08-06: compare WORD sequences with autojunk OFF. Character-level with
    # difflib's default autojunk silently collapses on any script over ~200
    # chars — it treats characters occurring in >1% of the sequence (i.e. every
    # common letter and the space) as junk. A verified-good 284-of-285-word
    # render scored 0.113 against this 0.9 gate, so the match check was failing
    # every full-length narration; it only ever passed because the 2026-07-30
    # reference render was ~40 words, below the autojunk threshold.
    ratio = difflib.SequenceMatcher(
        None, _normalize_text(script_text).split(), _normalize_text(transcript).split(), autojunk=False
    ).ratio()
    ok = (wpm_range[0] <= wpm <= wpm_range[1]) and ratio >= min_match
    res = {
        'ok': bool(ok),
        'wpm': round(wpm, 1),
        'match_ratio': round(ratio, 3),
        'n_words': n_words,
        'span_s': round(span_s, 2),
        'voiced_s': round(voiced_s, 2),
        'articulation_wpm': (None if articulation_wpm is None else round(articulation_wpm, 1)),
        'wpm_range': list(wpm_range),
        'min_match': min_match,
        'transcript_head': transcript[:300],
    }
    log(
        f'[audio_qc] wpm {os.path.basename(stem_wav)}: {wpm:.1f} span-wpm '
        f'(articulation {res["articulation_wpm"]}), match {ratio:.3f}, ok={ok}'
    )
    if articulation_wpm is not None and not (150.0 <= articulation_wpm <= 210.0):
        log(
            f'[audio_qc] wpm {os.path.basename(stem_wav)}: articulation '
            f'{articulation_wpm:.1f} wpm outside sanity band 150-210 '
            f'(engine speed regression?) — diagnostic only, not gated'
        )
    return res


# ── runtime / fade tail ──────────────────────────────────────────────────────


def qc_runtime(wav_path, max_s, log_fn=None):
    """Gate: 0 < duration <= max_s (ffprobe)."""
    dur = _ffprobe_duration(wav_path)
    if dur is None:
        return {'ok': False, 'reason': f'ffprobe failed on {wav_path}', 'duration_s': None, 'max_s': max_s}
    ok = 0.0 < dur <= float(max_s)
    (log_fn or _log_noop)(f'[audio_qc] runtime {os.path.basename(str(wav_path))}: {dur:.2f}s (max {max_s}s) ok={ok}')
    return {'ok': bool(ok), 'duration_s': round(dur, 3), 'max_s': float(max_s)}


def qc_fade(path, window_ms=200, max_dbfs=-60.0, log_fn=None):
    """Gate: the final window must be faded out (tail RMS <= max_dbfs).

    Catches un-faded hard cuts / clicks at the end of a stem or master.
    tail_dbfs is None for a digitally-silent tail (-inf is not JSON-safe).
    """
    try:
        import numpy as np
        import soundfile as sf

        data, sr = sf.read(path, dtype='float64', always_2d=True)
    except Exception as e:
        return {'ok': False, 'reason': f'{type(e).__name__}: {e}'[:300]}
    if data.shape[0] == 0:
        return {'ok': False, 'reason': 'empty audio file'}
    n = max(1, min(data.shape[0], int(sr * window_ms / 1000.0)))
    tail = data[-n:].mean(axis=1)  # mono mix of the last window
    rms = float(np.sqrt(np.mean(tail**2)))
    dbfs = 20.0 * np.log10(rms) if rms > 0 else None
    ok = dbfs is None or dbfs <= max_dbfs
    (log_fn or _log_noop)(
        f'[audio_qc] fade {os.path.basename(str(path))}: '
        f'tail {dbfs if dbfs is None else round(dbfs, 1)} dBFS '
        f'(max {max_dbfs}) ok={ok}'
    )
    return {
        'ok': bool(ok),
        'tail_dbfs': None if dbfs is None else round(dbfs, 1),
        'window_ms': window_ms,
        'max_dbfs': max_dbfs,
    }


# ── CLAP semantic tag (SOFT gate) ────────────────────────────────────────────


def _load_clap():
    """Load (and cache) CLAP on CPU, local files only — NEVER downloads.

    Weights may still be fetching in a parallel task, so any miss must surface
    as soft-unavailable upstream, not a download attempt mid-render.
    """
    name = os.environ.get('ZYG_AUDIO_QC_CLAP_MODEL', 'laion/clap-htsat-fused')
    with _CLAP_LOCK:
        if name in _CLAP_CACHE:
            return _CLAP_CACHE[name]
        from transformers import ClapModel, ClapProcessor

        try:
            model = ClapModel.from_pretrained(name, revision=_CLAP_REVISION, local_files_only=True)
            proc = ClapProcessor.from_pretrained(name, revision=_CLAP_REVISION, local_files_only=True)
        except Exception:
            # Belt and braces: retry under the hub's offline switches (still
            # allow-download=False semantics), then give up to the soft path.
            saved = {k: os.environ.get(k) for k in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE')}
            try:
                os.environ['HF_HUB_OFFLINE'] = '1'
                os.environ['TRANSFORMERS_OFFLINE'] = '1'
                model = ClapModel.from_pretrained(name, revision=_CLAP_REVISION)
                proc = ClapProcessor.from_pretrained(name, revision=_CLAP_REVISION)
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
        model.eval()  # CPU by default; this module never moves it to CUDA
        _CLAP_CACHE[name] = (model, proc)
        return _CLAP_CACHE[name]


def qc_clap(path, positives, negatives, threshold=0.6, log_fn=None):
    """SOFT gate: zero-shot 'does this sound like what we asked for?' check.

    Scores the FULL file in non-overlapping 30 s windows (each resampled to
    48 kHz mono; a trailing partial window under ~5 s is dropped when other
    windows exist) against positive and negative text prompts with
    laion/clap-htsat-fused on CPU; softmax over all prompts per window.

    The gate figure ('positive_prob') is the MINIMUM window positive-prompt
    probability — a loop seam at t=45 s must not hide behind a good opening —
    and the effective threshold is max(threshold, baseline + 0.15), where
    baseline = n_pos/(n_pos+n_neg) is the softmax sum's CHANCE level: it
    depends on the prompt-list split, so a fixed 0.6 alone would mean
    different things per call site (5 pos / 2 neg has chance 0.714 > 0.6).
    'scores' holds the per-prompt breakdown of the worst window; 'coverage_s'
    reports how much audio was actually scored. ANY failure (import, weights
    missing/downloading, OOM) returns {'ok': None, 'reason'} — fail-open,
    operator escalation, never blocks the pipeline on tooling.
    """
    log = log_fn or _log_noop
    try:
        positives = [str(p) for p in (positives or []) if str(p).strip()]
        negatives = [str(n) for n in (negatives or []) if str(n).strip()]
        if not positives:
            return {'ok': None, 'reason': 'no positive prompts given'}
        if not os.path.isfile(path):
            return {'ok': None, 'reason': f'file not found: {path}'}

        import numpy as np
        import soundfile as sf

        data, sr = sf.read(path, dtype='float64', always_2d=True)
        if data.shape[0] == 0:
            return {'ok': None, 'reason': 'empty audio file'}
        data = data.mean(axis=1)  # mono, native sr

        win_n = int(sr * 30)
        starts = list(range(0, len(data), win_n))
        if len(starts) > 1 and len(data) - starts[-1] < int(sr * 5):
            starts = starts[:-1]  # trailing sliver: too short to score

        import torch

        model, proc = _load_clap()
        texts = positives + negatives
        baseline = len(positives) / float(len(texts))
        eff_threshold = max(float(threshold), baseline + 0.15)

        windows, worst = [], None  # worst = (pos_prob, probs, start_s)
        coverage = 0.0
        for st in starts:
            chunk = data[st : st + win_n]
            if sr != 48000:  # linear resample:
                n_out = int(round(len(chunk) * 48000.0 / sr))  # fine for a
                chunk = np.interp(
                    np.linspace(0.0, len(chunk) - 1, n_out), np.arange(len(chunk)), chunk
                )  # coarse tagger
            audio = chunk.astype(np.float32)
            try:
                inputs = proc(text=texts, audio=[audio], sampling_rate=48000, return_tensors='pt', padding=True)
            except TypeError:  # older transformers use the `audios=` kwarg
                inputs = proc(text=texts, audios=[audio], sampling_rate=48000, return_tensors='pt', padding=True)
            with torch.no_grad():
                out = model(**inputs)
            probs = out.logits_per_audio.softmax(dim=-1)[0].tolist()
            pos_prob = float(sum(probs[: len(positives)]))
            start_s = st / float(sr)
            end_s = min(st + win_n, len(data)) / float(sr)
            coverage += end_s - start_s
            windows.append({'start_s': round(start_s, 2), 'end_s': round(end_s, 2), 'pos_prob': round(pos_prob, 4)})
            if worst is None or pos_prob < worst[0]:
                worst = (pos_prob, probs, start_s)

        min_pos = worst[0]
        res = {
            'ok': bool(min_pos >= eff_threshold),
            'positive_prob': round(min_pos, 4),  # min over windows (gated)
            'threshold': threshold,
            'baseline': round(baseline, 4),
            'effective_threshold': round(eff_threshold, 4),
            'coverage_s': round(coverage, 2),
            'windows': windows,
            'scores': {
                t: round(p, 4)  # worst window's breakdown
                for t, p in zip(texts, worst[1])
            },
        }
        log(
            f'[audio_qc] clap {os.path.basename(str(path))}: '
            f'min pos={min_pos:.3f} over {len(windows)} window(s) '
            f'({coverage:.0f}s scored, gate {eff_threshold:.2f}, '
            f'chance {baseline:.2f}) ok={res["ok"]}'
        )
        return res
    except Exception as e:
        reason = f'{type(e).__name__}: {e}'[:300]
        log(f'[audio_qc] clap soft-unavailable: {reason}')
        return {'ok': None, 'reason': reason}


# ── aggregates ───────────────────────────────────────────────────────────────


def _aggregate(gates):
    """Overall ok: no gate measured False. Soft-None gates never veto."""
    return {'ok': all(g.get('ok') is not False for g in gates.values()), 'gates': gates}


def qc_voice(stem_wav, reference_wav='', expect_age='', windows=4, log_fn=None):
    """Voice identity / age / consistency, via voice_qc (Praat in its own venv).

    Every engine in the stack is a zero-shot CLONER, and cloners fail quietly —
    they render clean, well-paced speech in the WRONG voice, which every other
    gate here happily passes. Soft-None when voice QC is unavailable or nothing
    was asked for, so it never vetoes a render it could not actually check.
    """
    out = {'ok': None, 'detail': 'voice QC not requested'}
    if not (reference_wav or expect_age):
        return out
    try:
        from zyg_workflows import voice_qc as _vqc
    except Exception as _e:
        out['detail'] = f'voice_qc unavailable: {_e!r}'
        return out
    if not _vqc.enabled():
        out['detail'] = 'voice QC disabled or analysis venv missing'
        return out
    res = _vqc.run_voice_gates(
        stem_wav,
        reference_wav=reference_wav,
        expect_age=expect_age,
        windows=windows,
        log_fn=(lambda lvl, stage, msg: log_fn(msg)) if log_fn else None,
    )
    measured = [g for g in res['gates'] if g['status'] in ('pass', 'fail')]
    if not measured:
        out['detail'] = '; '.join(g['detail'] for g in res['gates']) or 'nothing measurable'
        return out
    out['ok'] = res['ok']
    out['detail'] = '; '.join(f'{g["gate"]}={g["status"]}' for g in measured)
    out['gates'] = res['gates']
    return out


def run_stem_gates(
    stem_wav, pause_map_json, script_text, max_s, wpm_range=None, log_fn=None, reference_wav='', expect_age=''
):
    """All hard gates for a narration stem (silence map, pace, runtime, tail, voice).

    wpm_range=None uses qc_wpm's default speech-span band; pass a per-voice
    calibration tuple to override. reference_wav / expect_age enable the voice
    gates — pass the seed wav the render was cloned from, and the age class the
    character is meant to be ('child' for a boy narrator, 'adult_male', ...).
    """
    gates = {
        'silence_map': qc_silence_map(stem_wav, pause_map_json, log_fn=log_fn),
        'wpm': qc_wpm(stem_wav, script_text, wpm_range=wpm_range, log_fn=log_fn),
        'runtime': qc_runtime(stem_wav, max_s, log_fn=log_fn),
        'fade': qc_fade(stem_wav, log_fn=log_fn),
        'voice': qc_voice(stem_wav, reference_wav=reference_wav, expect_age=expect_age, log_fn=log_fn),
    }
    return _aggregate(gates)


def run_master_gates(path, target_lufs=-14.0, tp_max=-1.0, log_fn=None):
    """Delivery gates for the final mixed master (loudness spec + clean tail)."""
    gates = {
        'lufs': qc_lufs(path, target=target_lufs, tp_max=tp_max, log_fn=log_fn),
        'fade': qc_fade(path, log_fn=log_fn),
    }
    return _aggregate(gates)


# ── self-test ────────────────────────────────────────────────────────────────


def _selftest(out_dir):
    """Synthesize a tone/silence pattern, then prove the gates in both directions."""
    os.makedirs(out_dir, exist_ok=True)
    wav = os.path.join(out_dir, 'selftest_tone.wav')
    # 2s 300Hz | 1.2s silence | 2s tone | 2.2s silence | 1s tone, faded tail,
    # 0.4s digital-silence pad → 8.8s total.
    rc, _o, err = _run_cmd(
        [
            'ffmpeg',
            '-nostdin',
            '-hide_banner',
            '-y',
            '-f',
            'lavfi',
            '-i',
            'sine=frequency=300:duration=2:sample_rate=48000',
            '-f',
            'lavfi',
            '-i',
            'anullsrc=r=48000:cl=mono:d=1.2',
            '-f',
            'lavfi',
            '-i',
            'sine=frequency=300:duration=2:sample_rate=48000',
            '-f',
            'lavfi',
            '-i',
            'anullsrc=r=48000:cl=mono:d=2.2',
            '-f',
            'lavfi',
            '-i',
            'sine=frequency=300:duration=1:sample_rate=48000',
            '-filter_complex',
            '[0][1][2][3][4]concat=n=5:v=0:a=1,afade=t=out:st=8.0:d=0.2,apad=pad_dur=0.4[a]',
            '-map',
            '[a]',
            '-ac',
            '1',
            '-ar',
            '48000',
            wav,
        ]
    )
    if rc != 0 or not os.path.isfile(wav):
        _zyg_log.info(json.dumps({'selftest': 'FAIL', 'reason': f'wav synth failed: {err[-300:]}'}))
        return 1

    pause_map = {
        'head_ms': 0,
        'tail_ms': 0,
        'silences': [
            {'beat': 'b01', 'start_s': 2.0, 'ms': 1200},
            {'beat': 'b02', 'start_s': 5.2, 'ms': 2200},
        ],
    }
    pmap_path = os.path.join(out_dir, 'pause_map.json')
    with open(pmap_path, 'w', encoding='utf-8') as fh:
        json.dump(pause_map, fh, indent=2)

    shifted = json.loads(json.dumps(pause_map))
    shifted['silences'][1]['start_s'] = 5.6  # +400ms > tol_ms=150

    def _p(x):
        _zyg_log.info(x)

    results = {
        'loudness': measure_loudness(wav, log_fn=_p),
        'silence_map_match': qc_silence_map(wav, pmap_path, log_fn=_p),
        'silence_map_shifted_400ms': qc_silence_map(wav, shifted, log_fn=_p),
        'runtime': qc_runtime(wav, max_s=10, log_fn=_p),
        'fade': qc_fade(wav, log_fn=_p),
    }
    verdict = (
        results['loudness']['ok'] is True
        and results['silence_map_match']['ok'] is True
        and results['silence_map_shifted_400ms']['ok'] is False
        and results['runtime']['ok'] is True
        and results['fade']['ok'] is True
    )
    results['selftest'] = 'PASS' if verdict else 'FAIL'
    _zyg_log.info(json.dumps(results, indent=2))
    return 0 if verdict else 1


def main(argv):
    if len(argv) >= 3 and argv[1] == '--selftest':
        return _selftest(argv[2])
    if len(argv) >= 3 and argv[1] == '--clap-check':
        res = qc_clap(
            argv[2],
            positives=['calm spoken narration', 'ambient background sound'],
            negatives=['loud music', 'silence', 'noise and distortion'],
            log_fn=print,
        )
        print(json.dumps(res, indent=2))
        return 0
    print('usage: audio_qc.py --selftest <out_dir> | --clap-check <wav>')
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
