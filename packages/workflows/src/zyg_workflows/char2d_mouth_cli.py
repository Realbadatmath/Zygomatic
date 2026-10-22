# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.char2d_mouth`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.char2d_mouth` still reaches it.
"""

import argparse
import json
import sys
from pathlib import Path

from zyg_workflows import char2d_mouth as _mod
from zyg_workflows.char2d_mouth import (
    build_timing,
    draw_all_views,
    render_talking_clip,
)


def main(argv=None) -> int:
    """The command line that used to live in char2d_mouth.main()."""
    ap = argparse.ArgumentParser(description=_mod.__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('sprites', help='draw mouth overlays for every view')
    s.add_argument('views_json')
    s.add_argument('out_dir')

    t = sub.add_parser('timing', help='rhubarb -> quantised 24 fps mouth frames')
    t.add_argument('wav')
    t.add_argument('out_json')
    t.add_argument('--fps', type=int, default=24)
    t.add_argument('--min-hold', type=int, default=6)

    c = sub.add_parser('clip', help='composite a talking clip')
    c.add_argument('view_png')
    c.add_argument('mouth_dir')
    c.add_argument('wav')
    c.add_argument('out_mp4')
    c.add_argument('--fps', type=int, default=24)
    c.add_argument('--timing', help='reuse a timing.json instead of re-running rhubarb')

    a = ap.parse_args(argv)

    if a.cmd == 'sprites':
        for r in draw_all_views(a.views_json, a.out_dir):
            print(f'{r["view"]:10s} {r["kind"]:8s} mouth_w={r["mouth_w"]:.1f} -> {len(r["files"])} overlays')
        return 0

    if a.cmd == 'timing':
        doc = build_timing(a.wav, fps=a.fps, min_hold=a.min_hold)
        Path(a.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out_json).write_text(json.dumps(doc, indent=2))
        print(
            f'cues={len(doc["raw_cues"])} frames={doc["n_frames"]} '
            f'min_run={doc["min_run_frames"]} changes_per_s={doc["changes_per_s"]}'
        )
        return 0

    if a.cmd == 'clip':
        timing = json.loads(Path(a.timing).read_text()) if a.timing else None
        r = render_talking_clip(a.view_png, a.mouth_dir, a.wav, a.out_mp4, fps=a.fps, timing=timing)
        print(f'{r["out"]} frames={r["frames"]} changes_per_s={r["changes_per_s"]}')
        return 0

    return 1


if __name__ == '__main__':
    sys.exit(main())
