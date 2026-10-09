#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Write placeholder frame files. Usage: render.py --out <dir> [--frames N]"""

import argparse
import os
import sys


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('--out')
    ap.add_argument('--frames', type=int, default=1)
    a, _ = ap.parse_known_args()
    if not a.out:
        sys.exit('render: missing --out <dir>')
    os.makedirs(a.out, exist_ok=True)
    for i in range(1, a.frames + 1):
        with open(os.path.join(a.out, f'frame_{i:04d}.txt'), 'w') as f:
            f.write(f'FRAME {i:04d} quay dawn\nlantern lit\n')
    print(f'wrote {a.frames} frame(s) to {a.out}')


if __name__ == '__main__':
    main()
