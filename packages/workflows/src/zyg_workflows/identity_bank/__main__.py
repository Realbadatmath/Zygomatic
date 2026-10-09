# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""identity_bank CLI — `python -m zyg_workflows.identity_bank` (nightly drift cron / manual ops)."""

from .clip import check_clip
from .gate import bank_stats, check
from .runs import drift_report, enroll_from_canon, purge, score_run

# ── CLI (nightly drift cron / manual ops) ────────────────────────────────────
if __name__ == '__main__':  # pragma: no cover
    import argparse
    import json as _json

    ap = argparse.ArgumentParser(description='identity bank ops')
    ap.add_argument('cmd', choices=['enroll-canon', 'check', 'check-clip', 'score-run', 'report', 'stats', 'purge'])
    ap.add_argument('char_id', nargs='?', default=None, help='character id (not needed for score-run)')
    ap.add_argument('--style', default='arcane')
    ap.add_argument('--path', help='image, clip, or (score-run) a run directory')
    ap.add_argument('--box', help='fx0,fy0,fx1,fy1 — a per-frame ROI in perframe mode')
    ap.add_argument('--times', default='2,6,9,13,16', help='legacy mode only')
    ap.add_argument(
        '--mode', default=None, choices=[None, 'perframe', 'legacy'], help='check-clip sampling mode (default perframe)'
    )
    ap.add_argument('--stride', type=int, default=None, help='perframe: every Nth frame')
    ap.add_argument('--max-frames', type=int, default=None)
    ap.add_argument('--series', action='store_true', help='check-clip: print the per-frame series too')
    ap.add_argument('--backend')
    ap.add_argument('--episode')
    ap.add_argument('--render-id')
    a = ap.parse_args()
    _box = tuple(float(x) for x in a.box.split(',')) if a.box else None
    _t = [float(x) for x in a.times.split(',') if x.strip()]
    if a.cmd == 'enroll-canon':
        out = enroll_from_canon(a.char_id, a.style, backend=a.backend, log_fn=print)
    elif a.cmd == 'check':
        out = check(
            a.char_id,
            a.style,
            a.path,
            backend=a.backend,
            box_frac=_box,
            episode=a.episode,
            render_id=a.render_id,
            log_fn=print,
        )
    elif a.cmd == 'check-clip':
        out = check_clip(
            a.char_id,
            a.style,
            a.path,
            _box,
            times=_t,
            backend=a.backend,
            episode=a.episode,
            render_id=a.render_id,
            log_fn=print,
            mode=a.mode,
            stride=a.stride,
            max_frames=a.max_frames,
        )
        if not a.series:
            n = len(out.get('series') or [])
            out.pop('series', None)
            if n:
                out['series_len'] = n
    elif a.cmd == 'score-run':
        out = score_run(
            a.path, style_profile=a.style, stride=a.stride, max_frames=a.max_frames, backend=a.backend, log_fn=print
        )
        if not a.series:
            for e in out.get('clips', []):
                for r in e.get('results', {}).values():
                    r.pop('series', None)
    elif a.cmd == 'report':
        out = drift_report(a.char_id, a.style, backend=a.backend)
        out.pop('series', None)
    elif a.cmd == 'stats':
        out = bank_stats(a.char_id, a.style, a.backend)
        out.pop('centroid', None)
    else:
        out = purge(a.char_id, a.style, a.backend)
    print(_json.dumps(out, indent=2, default=str))
