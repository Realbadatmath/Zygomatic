# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.rubberband_r3`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.tools.rubberband_r3` still reaches it.
"""

import argparse
import json
import sys

from zyg_workflows.tools import rubberband_r3 as _mod
from zyg_workflows.tools.rubberband_r3 import (
    _decode,
    _encode,
    shift,
)


def main(argv=None):
    ap = argparse.ArgumentParser(description=_mod.__doc__.split('\n')[0])
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--semitones', type=float, default=0.0)
    ap.add_argument('--formant-follow', action='store_true', help='envelope moves with the pitch (default: preserved)')
    ap.add_argument(
        '--formant-semitones', type=float, default=None, help='explicit envelope shift, independent of pitch'
    )
    ap.add_argument('--engine', choices=('finer', 'faster'), default='finer')
    a = ap.parse_args(argv)
    x, sr = _decode(a.src)
    y, ver = shift(
        x,
        sr,
        semitones=a.semitones,
        formant='follow' if a.formant_follow else 'preserved',
        formant_semitones=a.formant_semitones,
        engine=a.engine,
    )
    _encode(y, sr, a.dst)
    rec = {
        'ok': True,
        'src': a.src,
        'dst': a.dst,
        'semitones': a.semitones,
        'formant': ('explicit %+.2f st' % a.formant_semitones)
        if a.formant_semitones is not None
        else ('follow' if a.formant_follow else 'preserved'),
        'engine': a.engine,
        'engine_version': ver,
        'sr': sr,
        'in_samples': int(x.shape[1]),
        'out_samples': int(y.shape[1]),
    }
    print(json.dumps(rec))
    return 0


if __name__ == '__main__':
    sys.exit(main())
