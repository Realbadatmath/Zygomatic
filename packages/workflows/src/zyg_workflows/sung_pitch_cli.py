# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.sung_pitch`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.sung_pitch` still reaches it.
"""

import json
import sys

import zyg_workflows.sung_pitch as _mod
from zyg_workflows.sung_pitch import (
    measure_stem,
    rank_score,
    shift_semitones,
)


def main(argv):
    if not argv:
        print(_mod.__doc__.strip().splitlines()[-3].strip())
        print('usage: sung_pitch.py FILE [FILE...]  |  sung_pitch.py --shift A B')
        return 2
    if argv[0] == '--shift':
        if len(argv) < 3:
            print('usage: sung_pitch.py --shift A B')
            return 2
        st, corr = shift_semitones(argv[1], argv[2])
        print(json.dumps({'a': argv[1], 'b': argv[2], 'shift_semitones': round(st, 3), 'correlation': round(corr, 4)}))
        return 0
    rows = [measure_stem(p) for p in argv]
    if len(rows) > 1:
        rank_score(rows)
    for r in rows:
        print(json.dumps(r))
    return 0 if all(r['ok'] for r in rows) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
