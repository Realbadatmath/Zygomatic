# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.video_audio`, moved out of the library module so that library
code never prints; `python -m zyg_workflows.video_audio` still reaches it.
"""

import sys

from zyg_workflows.video_audio import (
    __doc__ as _LIB_DOC,
    _selftest,
    build_track,
    mux,
)


def main(argv=None):  # pragma: no cover
    import argparse
    import json

    ap = argparse.ArgumentParser(description=_LIB_DOC.splitlines()[0])
    ap.add_argument('--spec', help='path to a spec JSON file')
    ap.add_argument('--duration', type=float, help='programme length in seconds')
    ap.add_argument('--out', help='output wav path')
    ap.add_argument('--video', help='video to mux the track onto')
    ap.add_argument('--mux', dest='mux_out', help='muxed mp4 output path')
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    if not (args.spec and args.duration and args.out):
        ap.error('--spec, --duration and --out are required (or --selftest)')
    with open(args.spec, 'r', encoding='utf-8') as fh:
        spec = json.load(fh)
    receipt = build_track(spec, args.duration, args.out, log=print)

    if args.video or args.mux_out:
        if not (args.video and args.mux_out):
            ap.error('--video and --mux must be given together')
        got = mux(args.video, args.out, args.mux_out, log=print)
        if not got:
            print('video_audio: mux failed')
            return 1
        receipt['mux'] = got
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
