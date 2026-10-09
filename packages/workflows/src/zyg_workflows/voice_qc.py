# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# voice_qc.py — objective voice-identity / voice-age gates for rendered narration
#
# WHY THIS EXISTS
# ---------------
# Every TTS engine in the stack is a zero-shot CLONER, and cloners fail quietly:
# they synthesize confident, well-formed speech in the WRONG voice. The existing
# audio gates (LUFS, true-peak, silence map, WPM, CLAP) all pass on a perfect
# render of the wrong person. Nothing measured whether the delivered voice is the
# voice that was asked for — so a mis-picked seed, a cloner that ages a child
# narrator up into an adult, or timbre drift across a long render all shipped
# undetected.
#
# Two markers, because they fail differently:
#   F0  — median pitch. Obvious, but fakeable: pitch-shift an adult up and you
#         get child pitch on an adult body.
#   VTL — vocal tract length from formant dispersion; the SIZE cue that actually
#         decides whether a listener hears a child. A render that keeps F0 but
#         grows VTL is an adult in falsetto, and a pitch-only check cannot see it.
#
# Measurement runs in an isolated venv (Praat/parselmouth) over subprocess+JSON,
# the same contract as the TTS workers — the GUI process never imports it.
# Calibrated 2026-08-06 against the 16-voice seed pool: adult male 17.30 cm /
# 90 Hz, adult female 14.44 cm / 174 Hz (matches the phonetics literature).
#
# Fail-safe by construction: every gate returns a dict and never raises. Set
# ZYG_VOICE_QC=0 to disable measurement entirely (gates return status 'skipped').

import json
import os
import subprocess
import logging as _zyg_logging
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


_ANALYSIS_DIR = paths.ZYG_VOICE_ANALYSIS_DIR
_ANALYSIS_PY = os.path.join(_ANALYSIS_DIR, '.venv', 'bin', 'python')
_ANALYSIS_SCRIPT = os.path.join(_ANALYSIS_DIR, 'voice_metrics.py')
_CORES = os.environ.get('ZYG_TTS_CORES', '0-19')

# Tolerances. Cloning is not sample-exact, so these are "same person" bands, not
# equality: |dF0| within 18% and |dVTL| within 1.0 cm still reads as one speaker
# (the adult male/female seed groups differ by 2.9 cm, so 1.0 cm stays well
# inside a genuine identity change).
F0_TOL_PCT = float(os.environ.get('ZYG_VOICE_QC_F0_TOL_PCT', '18'))
VTL_TOL_CM = float(os.environ.get('ZYG_VOICE_QC_VTL_TOL_CM', '1.0'))
# Age bands, from the same calibration run.
AGE_BANDS = {
    'child': {'f0_min': 200.0, 'vtl_max': 14.5},
    'adolescent': {'f0_min': 165.0, 'vtl_max': 15.5},
    # 14-15yo boy, mid voice-change: pitch already dropping but the body is not
    # adult yet. CAVEAT: this band genuinely overlaps adult female (174 Hz /
    # 14.44 cm measured here) — the two are not separable on F0+VTL alone. It
    # catches the failures that matter (rendering back up to a child at 280 Hz,
    # or down to an adult male at 90 Hz / 17.3 cm), not sex.
    'teen_male': {'f0_min': 140.0, 'f0_max': 200.0, 'vtl_min': 14.0, 'vtl_max': 16.8},
    'adult_male': {'f0_max': 165.0, 'vtl_min': 15.5},
    'adult_female': {'f0_min': 150.0, 'f0_max': 230.0, 'vtl_max': 15.5},
}


def enabled() -> bool:
    if os.environ.get('ZYG_VOICE_QC', '1').strip().lower() in ('0', 'false', 'no', 'off'):
        return False
    return os.path.isfile(_ANALYSIS_PY) and os.path.isfile(_ANALYSIS_SCRIPT)


def measure(wav_path: str, windows: int = 0, timeout: int = 300) -> list:
    """Measure one wav. Returns a list of metric dicts ([] on any failure).

    windows > 1 splits the file into N equal parts — use it to catch drift
    across a long render.
    """
    if not enabled() or not os.path.isfile(wav_path):
        return []
    cmd = [_ANALYSIS_PY, _ANALYSIS_SCRIPT, wav_path]
    if windows and windows > 1:
        cmd += ['--windows', str(windows)]
    if _CORES:
        cmd = ['taskset', '-c', _CORES] + cmd
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env={**os.environ, 'OMP_NUM_THREADS': '4'}
        )
    except Exception:
        return []
    for line in reversed((r.stdout or '').strip().splitlines()):
        line = line.strip()
        if line.startswith('['):
            try:
                return json.loads(line)
            except json.JSONDecodeError as _exc:
                _zyg_log.debug('analysis output line is not the json result, looking further back: %s', _exc)
                continue
    return []


def _first(wav_path: str) -> dict:
    m = measure(wav_path)
    return m[0] if m and 'error' not in m[0] else {}


def gate_voice_identity(
    wav_path: str, reference_wav: str, f0_tol_pct: float = F0_TOL_PCT, vtl_tol_cm: float = VTL_TOL_CM
) -> dict:
    """Did the render actually come out in the reference voice?

    Catches the silent cloner failure: a clean render of the wrong speaker.
    """
    out = {'gate': 'voice_identity', 'status': 'skipped', 'detail': ''}
    if not enabled():
        out['detail'] = 'voice QC disabled or analysis venv missing'
        return out
    got, ref = _first(wav_path), _first(reference_wav)
    if not got or not ref:
        out['status'] = 'warn'
        out['detail'] = 'could not measure render and/or reference'
        return out
    d_f0_pct = abs(got['f0_median_hz'] - ref['f0_median_hz']) / max(ref['f0_median_hz'], 1e-6) * 100
    d_vtl = abs(got['vtl_cm'] - ref['vtl_cm'])
    out.update(
        {
            'f0_hz': got['f0_median_hz'],
            'ref_f0_hz': ref['f0_median_hz'],
            'vtl_cm': got['vtl_cm'],
            'ref_vtl_cm': ref['vtl_cm'],
            'delta_f0_pct': round(d_f0_pct, 1),
            'delta_vtl_cm': round(d_vtl, 2),
        }
    )
    # VTL is the IDENTITY cue and F0 is a PERFORMANCE cue: an expressive read of
    # dramatic copy legitimately moves pitch (IndexTTS-2 infers emotion from the
    # text, and ran Abel +24.8% on an anxious passage) while the speaker's body
    # stays fixed. So a VTL miss is a different speaker — fail; an F0-only miss
    # is a delivery difference — warn, and say which it is.
    if d_vtl > vtl_tol_cm:
        out['status'] = 'fail'
        out['detail'] = f'different speaker — vocal tract moved {d_vtl:.2f} cm (tol {vtl_tol_cm}); ΔF0 {d_f0_pct:.1f}%'
    elif d_f0_pct > f0_tol_pct:
        out['status'] = 'warn'
        out['detail'] = (
            f'same speaker (ΔVTL {d_vtl:.2f} ≤ {vtl_tol_cm} cm) but pitch '
            f'is {d_f0_pct:.1f}% off the reference (tol {f0_tol_pct}%) — '
            f'delivery/expressiveness, not identity'
        )
    else:
        out['status'] = 'pass'
        out['detail'] = f'matches reference (ΔF0 {d_f0_pct:.1f}% ≤ {f0_tol_pct}%, ΔVTL {d_vtl:.2f} ≤ {vtl_tol_cm} cm)'
    return out


def gate_voice_age(wav_path: str, expect: str) -> dict:
    """Is the delivered voice still the intended age/size class?

    expect: 'child' | 'adolescent' | 'adult_male' | 'adult_female'.
    Specifically catches an adult-trained cloner ageing a child narrator up, and
    the falsetto case (child pitch on an adult body).
    """
    out = {'gate': 'voice_age', 'status': 'skipped', 'expect': expect, 'detail': ''}
    if not enabled():
        out['detail'] = 'voice QC disabled or analysis venv missing'
        return out
    band = AGE_BANDS.get(expect)
    if not band:
        out['status'] = 'warn'
        out['detail'] = f'unknown age class {expect!r}'
        return out
    m = _first(wav_path)
    if not m:
        out['status'] = 'warn'
        out['detail'] = 'could not measure render'
        return out
    f0, vtl = m['f0_median_hz'], m['vtl_cm']
    out.update({'f0_hz': f0, 'vtl_cm': vtl, 'verdict': m.get('verdict', '')})
    fails = []
    if 'f0_min' in band and f0 < band['f0_min']:
        fails.append(f'F0 {f0:.0f} Hz below {band["f0_min"]:.0f}')
    if 'f0_max' in band and f0 > band['f0_max']:
        fails.append(f'F0 {f0:.0f} Hz above {band["f0_max"]:.0f}')
    if 'vtl_max' in band and vtl > band['vtl_max']:
        fails.append(f'vocal tract {vtl:.2f} cm longer than {band["vtl_max"]:.2f} (voice reads adult-sized)')
    if 'vtl_min' in band and vtl < band['vtl_min']:
        fails.append(f'vocal tract {vtl:.2f} cm shorter than {band["vtl_min"]:.2f}')
    out['status'] = 'pass' if not fails else 'fail'
    out['detail'] = (
        f'{expect}: F0 {f0:.0f} Hz, VTL {vtl:.2f} cm' if not fails else f'not {expect} — ' + '; '.join(fails)
    )
    return out


def gate_voice_consistency(
    wav_path: str, windows: int = 4, f0_tol_pct: float = F0_TOL_PCT, vtl_tol_cm: float = VTL_TOL_CM
) -> dict:
    """Does the voice hold steady ACROSS a long render?

    Autoregressive cloners drift: the voice at minute nine is not always the
    voice at minute one. Splits the file into N windows and compares the spread.
    """
    out = {'gate': 'voice_consistency', 'status': 'skipped', 'windows': windows, 'detail': ''}
    if not enabled():
        out['detail'] = 'voice QC disabled or analysis venv missing'
        return out
    ms = [m for m in measure(wav_path, windows=windows) if 'error' not in m]
    if len(ms) < 2:
        out['status'] = 'warn'
        out['detail'] = 'not enough measurable windows'
        return out
    f0s = [m['f0_median_hz'] for m in ms]
    vtls = [m['vtl_cm'] for m in ms]
    spread_f0 = (max(f0s) - min(f0s)) / max(sum(f0s) / len(f0s), 1e-6) * 100
    spread_vtl = max(vtls) - min(vtls)
    out.update(
        {
            'f0_by_window': [round(x, 1) for x in f0s],
            'vtl_by_window': [round(x, 2) for x in vtls],
            'f0_spread_pct': round(spread_f0, 1),
            'vtl_spread_cm': round(spread_vtl, 2),
        }
    )
    if spread_f0 <= f0_tol_pct and spread_vtl <= vtl_tol_cm:
        out['status'] = 'pass'
        out['detail'] = (
            f'voice steady across {len(ms)} windows (F0 spread {spread_f0:.1f}%, VTL spread {spread_vtl:.2f} cm)'
        )
    else:
        out['status'] = 'fail'
        out['detail'] = (
            f'voice drifts across the render — F0 spread {spread_f0:.1f}% '
            f'(tol {f0_tol_pct}%), VTL spread {spread_vtl:.2f} cm '
            f'(tol {vtl_tol_cm})'
        )
    return out


def run_voice_gates(
    wav_path: str, reference_wav: str = '', expect_age: str = '', windows: int = 4, log_fn=None
) -> dict:
    """All applicable voice gates. Advisory by default; set ZYG_VOICE_QC_ENFORCE=1
    to have callers treat a 'fail' as fatal (mirrors audio_qc's enforce flag)."""

    def _l(level, msg):
        if log_fn:
            try:
                log_fn(level, 'Voice QC', msg)
                return
            except Exception as _exc:
                _zyg_log.debug('caller log callback failed, printing instead: %s', _exc)
        _zyg_log.info(f'[VOICE-QC] {msg}')

    gates = []
    if reference_wav:
        gates.append(gate_voice_identity(wav_path, reference_wav))
    if expect_age:
        gates.append(gate_voice_age(wav_path, expect_age))
    gates.append(gate_voice_consistency(wav_path, windows=windows))

    failed = [g for g in gates if g['status'] == 'fail']
    for g in gates:
        _l(
            'ERROR' if g['status'] == 'fail' else 'WARNING' if g['status'] == 'warn' else 'INFO',
            f'{g["gate"]}: {g["status"]} — {g["detail"]}',
        )
    return {
        'gates': gates,
        'ok': not failed,
        'failed': [g['gate'] for g in failed],
        'enforced': os.environ.get('ZYG_VOICE_QC_ENFORCE', '0').strip().lower() in ('1', 'true', 'yes', 'on'),
    }
