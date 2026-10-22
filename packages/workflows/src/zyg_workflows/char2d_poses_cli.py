# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.char2d_poses`, moved out of the library module so
that library code never prints; `python -m zyg_workflows.char2d_poses` still reaches it."""

import json
import sys

from zyg_workflows.char2d_poses import FPS, idle_bones, validate
from zyg_workflows.char2d_poses import __doc__ as _LIB_DOC


def _cmd_validate(paths):
    if not paths:
        print('validate: no gesture files given', file=sys.stderr)
        return 1
    bad = 0
    for path in paths:
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                gesture = json.load(fh)
        except (OSError, ValueError) as exc:
            print('FAIL %s: %s' % (path, exc))
            bad += 1
            continue
        errors = validate(gesture)
        if errors:
            bad += 1
            print('FAIL %s (%d error%s)' % (path, len(errors), '' if len(errors) == 1 else 's'))
            for message in errors:
                print('     %s' % message)
        else:
            keys = gesture.get('keys') or []
            frames = sum(int(k.get('hold_frames', 0)) for k in keys)
            print(
                'OK   %s  %-22s hands=%-4s keys=%d frames=%d (%.2fs)'
                % (path, gesture.get('name', '?'), gesture.get('hands', '?'), len(keys), frames, frames / float(FPS))
            )
    return 1 if bad else 0


def main(argv):
    if len(argv) < 2 or argv[1] in ('-h', '--help'):
        print(_LIB_DOC.strip())
        print('\nusage: char2d_poses.py validate GESTURE.json ...\n       char2d_poses.py idle')
        return 0 if len(argv) > 1 else 1
    command = argv[1]
    if command == 'validate':
        return _cmd_validate(argv[2:])
    if command == 'idle':
        print(json.dumps(idle_bones(), indent=2))
        return 0
    print('unknown command %r (validate | idle)' % command, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
