#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 6 Ken Burns stagger verification — 39 Electroculture FLUX stills, 16 threads."""

from __future__ import annotations

import concurrent.futures as cf
import glob
import json
import os
import sys
import time

_CREW_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, _CREW_ROOT)

CLIP_ID = '53851131-2567-45a8-ae81-c785540d60ec'
FLUX_DIR = os.path.join(
    _CREW_ROOT,
    'data',
    'output',
    'clips',
    CLIP_ID,
    'flux_images',
)
OUT_DIR = os.path.join(_CREW_ROOT, 'data', 'runtime', 'kb_stagger_test')
DURATIONS = [
    8,
    18,
    12,
    24,
    16,
    25,
    17,
    21,
    26,
    14,
    21,
    16,
    23,
    13,
    37,
    36,
    35,
    26,
    25,
    9,
    19,
    21,
    13,
    34,
    22,
    29,
    14,
    29,
    27,
    25,
    23,
    16,
    10,
    24,
    21,
    36,
    11,
    29,
    20,
]
_KB_FPS = 30
_KB_STAGGER_S = 0.25


def main() -> int:
    from zyg_dashboard.crewai_web_gui import _render_kb_pil_shared

    imgs = sorted(glob.glob(os.path.join(FLUX_DIR, 'flux_[0-9][0-9][0-9].jpg')))
    if len(imgs) != 39:
        print(f'FAIL: expected 39 images, found {len(imgs)} in {FLUX_DIR}')
        return 1

    os.makedirs(OUT_DIR, exist_ok=True)
    tasks: dict[int, tuple] = {}
    for ki, ip in enumerate(imgs):
        tasks[ki] = (
            ip,
            os.path.join(OUT_DIR, f'kb_{ki:03d}.mp4'),
            float(DURATIONS[ki]),
            _KB_FPS,
            ki,
            'medium',
            'calm',
            'center',
            1920,
            1080,
        )

    n_workers = min(os.cpu_count() or 4, len(tasks), 16)
    print(f'Rendering {len(tasks)} clips on {n_workers} threads (stagger {_KB_STAGGER_S}s × slot)…')

    def worker(args):
        ki, task = args
        time.sleep(_KB_STAGGER_S * ki)
        return ki, _render_kb_pil_shared(*task)

    t0 = time.time()
    results: dict[int, bool] = {}
    with cf.ThreadPoolExecutor(max_workers=n_workers) as pool:
        for ki, ok in pool.map(worker, tasks.items()):
            results[ki] = ok

    ok_count = sum(1 for v in results.values() if v)
    failed = sorted(ki for ki, v in results.items() if not v)
    elapsed = time.time() - t0
    report = {
        'clip_id': CLIP_ID,
        'n_images': len(imgs),
        'n_workers': n_workers,
        'stagger_s_per_slot': _KB_STAGGER_S,
        'pil_ok': ok_count,
        'static_fallback': len(failed),
        'failed_slots': failed,
        'elapsed_s': round(elapsed, 1),
        'pass': ok_count == len(imgs),
    }
    out_json = os.path.join(OUT_DIR, 'kb_stagger_report.json')
    with open(out_json, 'w') as f:
        json.dump(report, f, indent=2)

    print(json.dumps(report, indent=2))
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
