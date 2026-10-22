# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line and self-test of `zyg_workflows.video_finish`, moved out of the library module so
that library code never prints; `python -m zyg_workflows.video_finish` still reaches it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

from zyg_workflows.bin import exe
from zyg_workflows.video_finish import (
    CRF,
    ESRGAN_MODELS,
    _expect,
    _run,
    _zyg_log,
    esrgan_clip,
    probe,
    rife_2x,
)


def _selftest() -> int:
    log = lambda m: print(f'  . {m}')
    tmp = tempfile.mkdtemp(prefix='video_finish_selftest_')
    _zyg_log.info(f'selftest workspace: {tmp}')
    src = os.path.join(tmp, 'src.mp4')
    _run(
        [
            exe('ffmpeg'),
            '-y',
            '-f',
            'lavfi',
            '-i',
            'testsrc2=size=640x360:rate=17',
            '-t',
            '2',
            '-c:v',
            'libx264',
            '-crf',
            str(CRF),
            '-pix_fmt',
            'yuv420p',
            src,
        ],
        120,
        'ffmpeg synthetic source',
    )
    base = probe(src)
    _zyg_log.info(f'source: {base}')
    _expect('source frames', base['frames'], 34)

    _zyg_log.info('\n[1] rife_2x(out_fps=None)')
    r1 = rife_2x(src, os.path.join(tmp, 'rife34.mp4'), out_fps=None, log=log)
    _zyg_log.info(f'receipt: {r1}')
    _expect('rife frames_out', r1['frames_out'], 68)
    _expect('rife fps_out', r1['fps_out'], 34.0)

    _zyg_log.info('\n[2] rife_2x(out_fps=24)')
    r2 = rife_2x(src, os.path.join(tmp, 'rife24.mp4'), out_fps=24, log=log)
    _zyg_log.info(f'receipt: {r2}')
    _expect('rife24 frames_out', r2['frames_out'], 48)
    _expect('rife24 fps_out', r2['fps_out'], 24.0)

    _zyg_log.info('\n[3] esrgan_clip(scale=2)')
    r3 = esrgan_clip(src, os.path.join(tmp, 'esrgan2x.mp4'), scale=2, log=log)
    _zyg_log.info(f'receipt: {r3}')
    _expect('esrgan w_out', r3['w_out'], 1280)
    _expect('esrgan h_out', r3['h_out'], 720)
    _expect('esrgan frames', r3['frames'], 34)

    _zyg_log.info('\nSELFTEST OK')
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Video Studio finishing passes (RIFE / RealESRGAN)')
    ap.add_argument('--rife', nargs=2, metavar=('IN', 'OUT'), help='2x frame interpolation')
    ap.add_argument('--esrgan', nargs=2, metavar=('IN', 'OUT'), help='RealESRGAN clip upscale')
    ap.add_argument('--fps', type=float, default=None, help='conform the RIFE result to this fps')
    ap.add_argument(
        '--scale', type=int, default=2, choices=sorted(ESRGAN_MODELS), help='ESRGAN scale factor (default 2)'
    )
    ap.add_argument('--selftest', action='store_true', help='synthetic end-to-end proof (uses the GPU)')
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    log = lambda m: print(m, flush=True)
    if args.rife:
        print(json.dumps(rife_2x(args.rife[0], args.rife[1], out_fps=args.fps, log=log), indent=2))
        return 0
    if args.esrgan:
        print(json.dumps(esrgan_clip(args.esrgan[0], args.esrgan[1], scale=args.scale, log=log), indent=2))
        return 0
    ap.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
