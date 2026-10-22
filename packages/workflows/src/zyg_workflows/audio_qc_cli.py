# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.audio_qc`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.audio_qc` still reaches it.
"""

import sys
import json

from zyg_workflows.audio_qc import (
    _selftest,
    qc_clap,
)


def main(argv):
    if len(argv) >= 3 and argv[1] == '--selftest':
        return _selftest(argv[2])
    if len(argv) >= 3 and argv[1] == '--clap-check':
        res = qc_clap(
            argv[2],
            positives=['calm spoken narration', 'ambient background sound'],
            negatives=['loud music', 'silence', 'noise and distortion'],
            log_fn=print,
        )
        print(json.dumps(res, indent=2))
        return 0
    print('usage: audio_qc.py --selftest <out_dir> | --clap-check <wav>')
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
