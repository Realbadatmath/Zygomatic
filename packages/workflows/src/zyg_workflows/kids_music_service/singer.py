# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The singer gate: separate the vocal, then refuse a child voice.

Moved verbatim out of the old single-file kids_music_service.py (lines 2322-2557).
"""

from __future__ import annotations

import json
import os
import subprocess
from zyg_workflows import kids_music_theory as T

from zyg_workflows.kids_music_service.base import (
    HERE,
    _log_noop,
    _zyg_log,
)

# ── Singer gate ──────────────────────────────────────────────────────────────

_AGENTS_PY = os.path.join(os.path.dirname(HERE), '.venv', 'bin', 'python')
_DEMUCS_TOOL = os.path.join(HERE, 'tools', 'demucs_split.py')
# Below this the "vocal" stem is not a vocal. A separation failure or a silent
# vocal must FAIL CLOSED rather than be measured: voice_qc returned a confident
# CHILD verdict (436 Hz / 10.02 cm) from a stem 43 dB below its backing, because
# Praat measures noise perfectly happily.
VOCAL_PRESENT_DB = float(os.environ.get('ZYG_KIDSMUSIC_VOCAL_DB', '-25'))
# Above this F0, formant estimation — and therefore VTL — is not reliable: the
# harmonics are spaced too far apart to sample the spectral envelope. RETAINED
# ONLY AS A CONSTANT: the gate stopped recording VTL on 2026-09-06, because every
# sung female take measures 300-500 Hz and a dispersion figure that is never
# trustworthy in its own operating range is not an observation, it is noise.
VTL_TRUSTWORTHY_MAX_F0 = 300.0
# Median above this and the singer is over every female primo passaggio (mezzo
# E4, contralto G#4-A4 — Miller). Not a failure: an advisory, because a belted
# take is a legitimate render, just not a warm one.
FEMALE_HIGH_REGISTER_F0 = 415.0


def separate_vocal(path, out_dir, *, log_fn=None, timeout_s=600):
    """demucs htdemucs two-stem split, in the agents venv. Returns its dict.

    NEVER use a librosa soft-mask for this. Measured: it retains 41-61% of the
    spectral energy in the "vocal" stem and the leftover accompaniment tracks at
    261-403 Hz — squarely inside the band the gate is trying to read, so the gate
    would be measuring the backing and calling it the singer.
    """
    log_fn = log_fn or _log_noop
    out = {'ok': False, 'error': 'not run'}
    if not (os.path.isfile(_AGENTS_PY) and os.path.isfile(_DEMUCS_TOOL)):
        out['error'] = 'demucs helper or agents venv missing'
        return out
    cmd = [_AGENTS_PY, _DEMUCS_TOOL, path, out_dir]
    cores = os.environ.get('ZYG_TTS_CORES', '0-19')
    if cores:
        cmd = ['taskset', '-c', cores] + cmd
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except (subprocess.SubprocessError, OSError) as e:
        out['error'] = f'{type(e).__name__}: {e}'[:200]
        return out
    for line in reversed((r.stdout or '').strip().splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                return json.loads(line)
            except ValueError as _exc:
                _zyg_log.debug('non-JSON line on the gate stdout, ignored: %s', _exc)
                continue
    out['error'] = (r.stderr or 'no JSON on stdout')[-200:]
    return out


def gate_singer_age(path, plan, *, work_dir=None, log_fn=None):
    """The singer gate (see _gate_singer_age). With no work_dir the demucs split
    goes to a private temp dir that is REMOVED afterwards — it used not to be,
    and 288 kmsinger_* dirs (4.2 GB of stems) had piled up in /tmp by
    2026-09-15. Pass work_dir to keep the stems (the voice review reads them)."""
    if work_dir:
        return _gate_singer_age(path, plan, work_dir=work_dir, log_fn=log_fn)
    import tempfile

    tmp = tempfile.mkdtemp(prefix='kmsinger_')
    try:
        return _gate_singer_age(path, plan, work_dir=tmp, log_fn=log_fn)
    finally:
        import shutil as _sh

        _sh.rmtree(tmp, ignore_errors=True)


def _gate_singer_age(path, plan, *, work_dir=None, log_fn=None):
    """Is the voice on this track the singer we cast?

    Three ordered steps, because both obvious shortcuts were tested and both are
    invalid:

      1. SEPARATE and check a vocal is actually there. CLAP cannot do this job —
         it scores a pure instrumental at 0.493 on "a children's choir singing".
         The vocals-vs-rest RMS must clear VOCAL_PRESENT_DB or the gate fails
         closed: a silent vocal and a failed separation are both un-measurable,
         and measuring them anyway is how you get a confident wrong answer.

      2. MEASURE the stem with sung_pitch (RMVPE) and hold the CONFIDENCE-
         WEIGHTED MEDIAN F0 to the cast SUNG band.

      3. RECORD everything — the median with p10/p90, the brightness axis, the
         cross-tracker agreement, stem ratio, expected band.

    THE CRITERION IS THE RMVPE MEDIAN (changed 2026-09-06). It used to be the
    Praat median from voice_qc, and that meter is wrong for this material: it
    runs at pitch_ceiling 550 Hz, and a sung take reaches well past it (the
    picked Farmyard soprano measures p95 736 Hz with a 1162 Hz peak). Every
    frame above the ceiling is dropped, so the reported median is a censored
    statistic — it moved NON-MONOTONICALLY as pitch-shifted copies of one take
    pulled different frames in and out of the window, which is how a -3 st copy
    once read higher than the -2 st one. sung_pitch uses RMVPE (trained on
    polyphonic mixes) up to 1400 Hz with SwiftF0 as an independent cross-check,
    and reports the disagreement in cents rather than a single number to trust.

    WHY NO voice_qc VERDICT ANY MORE. voice_qc.AGE_BANDS is calibrated on
    SPEECH — adult female 174 Hz / 14.44 cm — and this is SINGING. Measured
    2026-08-29 on the five shipped sung songs, every one came back
    "CHILD/ADOLESCENT (pitch and size agree)" at 329-387 Hz. That is the
    instrument being used outside its calibration, not a finding, and it cost a
    subprocess in another venv to obtain. Retired; see 'praat_note'.

    NO VTL EITHER. Formant dispersion needs harmonics closely enough spaced to
    sample the spectral envelope, and above ~400 Hz they are not. Since every
    female sung take lives above that, the figure was never usable in the range
    this gate operates in.

    WHAT THIS GATE CAN AND CANNOT SEE. It separates MALE from FEMALE — those
    captions are non-overlapping 3 of 3 (164-261 vs 295-391 Hz on the old
    meter). It CANNOT separate an adult woman from a child choir: those captions
    interleave completely, which is exactly why no child or teen singer is
    offered. Do not extend it to that job without new evidence. It also does not
    judge SHRILLNESS — register and brightness are separate axes, so the
    sharpness/HF numbers are recorded and the high-register flag is advisory.
    """
    log_fn = log_fn or _log_noop
    b = plan['brief']
    key = b.get('singer') or T.DEFAULT_SINGER
    spec = T.SINGERS.get(key, T.SINGERS[T.DEFAULT_SINGER])
    lo, hi = spec['band']
    g = {
        'gate': 'singer',
        'expected': key,
        'expected_band_hz': [lo, hi],
        'status': 'skipped',
        'ok': True,
        'detail': '',
        'checks': {},
    }

    if not b.get('sung'):
        g['detail'] = 'instrumental brief — no singer to verify'
        return g
    if not path or not os.path.isfile(path):
        g.update(status='fail', ok=False, detail='no audio to measure')
        return g

    import tempfile

    tmp = work_dir or tempfile.mkdtemp(prefix='kmsinger_')
    sep = separate_vocal(path, os.path.join(tmp, 'stems'), log_fn=log_fn)
    g['checks']['separation'] = {
        k: sep.get(k) for k in ('ok', 'vocal_rms_db', 'rest_rms_db', 'ratio_db', 'device', 'error') if k in sep
    }
    if not sep.get('ok'):
        g.update(status='fail', ok=False, detail=f'separation failed — {sep.get("error") or "unknown"}')
        log_fn(f'singer: {g["detail"]}')
        return g

    ratio = float(sep.get('ratio_db', -99))
    if ratio < VOCAL_PRESENT_DB:
        g.update(
            status='fail',
            ok=False,
            detail=(
                f'no vocal present: stem is {ratio:.1f} dB against the '
                f'backing (floor {VOCAL_PRESENT_DB:.0f} dB) — a sung '
                f'brief with no singing, or a failed separation'
            ),
        )
        log_fn(f'singer: {g["detail"]}')
        return g

    try:
        from zyg_workflows import sung_pitch

        m = sung_pitch.measure_stem(sep['vocals'])
    except Exception as e:  # noqa: BLE001
        m = {}
        g['checks']['measure_error'] = f'{type(e).__name__}: {e}'[:160]
    if not m.get('ok'):
        g['checks']['measure_error'] = (m.get('error') or '')[:160] or g['checks'].get('measure_error', '')
        g.update(status='fail', ok=False, detail='vocal stem present but could not be measured')
        log_fn(f'singer: {g["detail"]}')
        return g

    f0 = float(m.get('f0_median_hz') or 0.0)
    g['checks'].update(
        {
            'f0_median_hz': round(f0, 1),
            'f0_p10_hz': m.get('f0_p10_hz'),
            'f0_p90_hz': m.get('f0_p90_hz'),
            'pct_time_above_500hz': m.get('pct_time_above_500hz'),
            'sharpness_acum': m.get('sharpness_acum'),
            'hf_ratio_2k8k': m.get('hf_ratio_2k8k'),
            'tracker': m.get('tracker'),
            'agreement_cents': m.get('agreement_cents'),
            'praat_note': ('retired 2026-09-06, ceiling 550 Hz censored sung medians'),
        }
    )

    # REGISTER is an advisory, never a verdict. A median above G#4 is over every
    # female primo passaggio, so the take will read bright or belted — which is
    # a legitimate render and a bad fit for a lullaby, and only a human can tell
    # those apart.
    if key == 'adult_female' and f0 > FEMALE_HIGH_REGISTER_F0:
        g['register'] = 'high'
        g['register_note'] = 'median above G#4: above every female primo passaggio; expect bright/belted'

    # ENFORCE is the default, but the audit's advice — ship it as a warning until
    # >= 20 renders per band have set the windows — is honoured as a switch, and
    # the male arm is the one that still wants it (n=6 against female's n=14).
    # ZYG_KIDSMUSIC_SINGER_ENFORCE=0 downgrades a miss to a warning that still
    # records every number.
    enforce = os.environ.get('ZYG_KIDSMUSIC_SINGER_ENFORCE', '1').strip().lower() not in ('0', 'false', 'no', 'off')
    g['enforced'] = enforce
    g['calibration_n'] = spec.get('n')
    if lo <= f0 <= hi:
        g.update(
            status='pass',
            ok=True,
            detail=(
                f'{spec["label"]}: {f0:.0f} Hz inside the cast band '
                f'{lo:.0f}-{hi:.0f} Hz (vocal {ratio:.1f} dB over the mix)'
            ),
        )
    else:
        g.update(
            status='fail' if enforce else 'warn',
            ok=not enforce,
            detail=(
                f'not {spec["label"]}: {f0:.0f} Hz is outside the cast '
                f'band {lo:.0f}-{hi:.0f} Hz' + ('' if enforce else ' (advisory: gate not enforcing)')
            ),
        )
    log_fn(f'singer: {g["status"]} — {g["detail"]}')
    return g
