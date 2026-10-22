# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.continuity_qc.ownership`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.continuity_qc.ownership` still reaches it.
"""

import json
import sys

from zyg_workflows.continuity_qc.clip import analyze_clip
from zyg_workflows.continuity_qc.models import available
from zyg_workflows.continuity_qc.ownership import (
    _V7,
    _V7_ACTORS,
    _V7_OBJECTS,
    action_ownership,
)


def _main(argv):
    """The command line that used to live in continuity_qc.ownership._main()."""
    import argparse

    ap = argparse.ArgumentParser(description='grounded continuity QC')
    ap.add_argument('--clip', default=_V7)
    ap.add_argument('--sample-fps', type=float, default=2.0)
    ap.add_argument('--device', default='auto')
    ap.add_argument('--json-out', default='')
    ap.add_argument('--skip-clip', action='store_true')
    ap.add_argument('--skip-ownership', action='store_true')
    ap.add_argument('--times', default='5.2,12.7')
    a = ap.parse_args(argv)
    log = lambda m: print(m, flush=True)
    res = {'clip': a.clip, 'available': available(log_fn=log)}
    if not a.skip_clip:
        res['analyze_clip'] = analyze_clip(a.clip, _V7_OBJECTS, sample_fps=a.sample_fps, device=a.device, log_fn=log)
    if not a.skip_ownership:
        res['action_ownership'] = action_ownership(
            a.clip,
            _V7_ACTORS,
            'white clay pipe',
            [float(x) for x in a.times.split(',') if x.strip()],
            expected_owner='man',
            device=a.device,
            log_fn=log,
        )
    if a.json_out:
        with open(a.json_out, 'w') as fh:
            json.dump(res, fh, indent=1)
        print(f'wrote {a.json_out}')
    return res


def main() -> int:
    """`python -m zyg_workflows.continuity_qc.ownership` lands here through the module's connector."""
    _main(sys.argv[1:])
    return 0


if __name__ == '__main__':
    sys.exit(main())
