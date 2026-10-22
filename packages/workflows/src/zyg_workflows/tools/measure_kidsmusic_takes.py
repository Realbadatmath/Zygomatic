# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""measure_kidsmusic_takes.py — separate + measure a batch of kidsmusic takes.

One row per audio file: demucs two-stem separation (the same
`kids_music_service.separate_vocal` the singer gate uses) followed by
`sung_pitch.measure_stem` on the vocal stem.

WHY A SEPARATE HELPER. The SINGERS bands in kids_music_theory were calibrated on
the Praat meter in models/voice_analysis (pitch_ceiling 550 Hz), which censors a
large slice of every frame set of a sung take and therefore reports a median that
is both low and non-monotonic. Recalibrating them needs the whole take set
measured with the RMVPE meter in one pass, and more than one task needs that
pass, so it lives here rather than inside a one-off.

Runs in the agents venv (it needs demucs, librosa and rmvpe-onnx):

    "../.venv/bin/python" tools/measure_kidsmusic_takes.py FILE [FILE...] \
        [--out rows.json] [--old-f0 map.json] [--device cuda|cpu]

`--old-f0` takes a JSON object mapping a file BASENAME to the F0 the old Praat
meter reported for it (the sweep index.json `gate.f0_hz` or pitch_fix
`base_f0_hz`), so the two meters can be compared row by row.

stdout carries one JSON document: {'rows': [...], 'aggregate': {...}}.
"""

from __future__ import annotations

import os
import statistics
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

ROW_KEYS = (
    'f0_median_hz',
    'f0_p10_hz',
    'f0_p90_hz',
    'pct_time_above_500hz',
    'sharpness_acum',
    'hf_ratio_2k8k',
    'agreement_cents',
)


def measure_files(paths, *, old_f0=None, work_root=None, log=None):
    """Separate and measure every path. Returns the row list, in input order."""
    from zyg_workflows import kids_music_service as K
    from zyg_workflows import sung_pitch

    log = log or (lambda m: None)
    old_f0 = old_f0 or {}
    work_root = work_root or tempfile.mkdtemp(prefix='kmtakes_')
    os.makedirs(work_root, exist_ok=True)
    rows = []
    for i, path in enumerate(paths):
        name = os.path.basename(path)
        row = {'file': os.path.relpath(path, HERE), 'ok': False, 'error': ''}
        row.update({k: None for k in ROW_KEYS})
        row['old_praat_f0'] = old_f0.get(name)
        if not os.path.isfile(path):
            row['error'] = 'missing'
            rows.append(row)
            continue
        sep = K.separate_vocal(path, os.path.join(work_root, f'{i:03d}'))
        row['ratio_db'] = sep.get('ratio_db')
        if not sep.get('ok'):
            row['error'] = f'separation failed: {sep.get("error") or "unknown"}'
            log(f'{name}: {row["error"]}')
            rows.append(row)
            continue
        m = sung_pitch.measure_stem(sep['vocals'])
        for k in ROW_KEYS:
            row[k] = m.get(k)
        row['voiced_frac'] = m.get('voiced_frac')
        row['tracker'] = m.get('tracker')
        row['ok'] = bool(m.get('ok'))
        row['error'] = m.get('error') or ''
        log(f'{name}: f0 {row["f0_median_hz"]} Hz  (old praat {row["old_praat_f0"]})')
        rows.append(row)
    return rows


def aggregate(rows):
    """min / median / max of the measured medians over the rows that measured."""
    vals = sorted(r['f0_median_hz'] for r in rows if r.get('ok') and r.get('f0_median_hz'))
    if not vals:
        return {'n': 0, 'min_f0_median_hz': None, 'median_f0_median_hz': None, 'max_f0_median_hz': None}
    return {
        'n': len(vals),
        'min_f0_median_hz': round(vals[0], 1),
        'median_f0_median_hz': round(statistics.median(vals), 1),
        'max_f0_median_hz': round(vals[-1], 1),
    }


if __name__ == '__main__':  # the CLI lives in measure_kidsmusic_takes_cli
    from zyg_workflows.tools.measure_kidsmusic_takes_cli import main as _cli_main

    raise SystemExit(_cli_main())
