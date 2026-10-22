# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.recipe_probe`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.tools.recipe_probe` still reaches it.
"""

import argparse
import json
import os

from zyg_workflows.tools.recipe_probe import probe_animate, probe_vace


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('shot_dir')
    ap.add_argument('--engine', choices=('vace', 'animate'), required=True)
    ap.add_argument('--plates', default='plates')
    ap.add_argument('--frames', type=int, default=25)
    ap.add_argument('--still')
    ap.add_argument('--ref', action='append', default=[])
    ap.add_argument('--neg', default='')
    ap.add_argument('--set-plate', default='')
    ap.add_argument('--set-strength', type=float, default=1.0)
    ap.add_argument('--set-end', type=float, default=0.88)
    ap.add_argument('--geom', default='')
    ap.add_argument('--use-binding', action='store_true')
    ap.add_argument('--lora')
    ap.add_argument('--lora-strength', type=float, default=1.0)
    ap.add_argument('--vace-strength', type=float, default=0.7)
    ap.add_argument('--vace-end', type=float, default=0.35)
    ap.add_argument('--blend', default='')
    ap.add_argument('--steps', type=int, default=20)
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--prompt', default='')
    ap.add_argument('--tag', default='t')
    ap.add_argument('--res', default='')
    a = ap.parse_args()
    shot_dir = os.path.abspath(a.shot_dir)
    shot = json.load(open(os.path.join(shot_dir, 'shot.json')))
    lines = []

    def log(m):
        print(m, flush=True)
        lines.append(str(m))

    take, rec = (probe_vace if a.engine == 'vace' else probe_animate)(a, shot, shot_dir, log)
    if take:
        os.makedirs(take, exist_ok=True)
        with open(os.path.join(take, 'probe.json'), 'w') as fh:
            json.dump(rec, fh, indent=1, default=str)
        with open(os.path.join(take, 'probe.log'), 'w') as fh:
            fh.write('\n'.join(lines))
    print('PROBE DONE', json.dumps({k: rec.get(k) for k in ('engine', 'tag', 'clip', 'wall_s')}))


if __name__ == '__main__':
    main()
