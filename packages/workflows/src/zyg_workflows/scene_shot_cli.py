# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.scene_shot`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.scene_shot` still reaches it.
"""

import json
import sys

import zyg_workflows.scene_shot as _mod
from zyg_workflows.scene_shot import (
    new_shot,
    resolve_positions,
    save,
    validate,
)


def _main(argv):
    if len(argv) < 2:
        print(_mod.__doc__.strip().split('CLI')[-1].strip(), file=sys.stderr)
        return 2
    cmd = argv[1]
    if cmd == 'validate' and len(argv) == 3:
        with open(argv[2], 'r', encoding='utf-8') as fh:
            shot = json.load(fh)
        warnings = []
        errs = validate(shot, warnings)
        for wmsg in warnings:
            print('warning: %s' % wmsg)
        if errs:
            for msg in errs:
                print('error: %s' % msg)
            return 1
        print('valid')
        return 0
    if cmd == 'resolve' and len(argv) == 3:
        with open(argv[2], 'r', encoding='utf-8') as fh:
            shot = json.load(fh)
        print(json.dumps(resolve_positions(shot), indent=2))
        return 0
    if cmd == 'new' and len(argv) == 4:
        shot = new_shot(argv[2], argv[3])
        path = save(shot)
        print(path)
        return 0
    print('usage: scene_shot.py validate <shot.json> | resolve <shot.json> | new <id> <drawing.json>', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(_main(sys.argv))
