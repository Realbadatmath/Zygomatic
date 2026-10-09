# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line and self-test of `zyg_workflows.build_cast_voices`, moved out of the library module.

The library file sits above the brand line (800 lines); its logic stays there and
only connects to this entry point, which `python -m zyg_workflows.build_cast_voices` still reaches.
"""

import sys

from zyg_workflows.build_cast_voices import (
    BENCHES,
    bake,
    build,
)


def main() -> int:
    """The command line that used to live under `if __name__ == '__main__'` in build_cast_voices."""
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    do_render = '--no-render' not in sys.argv
    only_bake = '--bake-only' in sys.argv
    for b in args or list(BENCHES):
        print(f'\n═══ bench: {b} ═══', flush=True)
        if not only_bake:
            build(b, render=do_render)
        # Playability is part of delivering a bench: a candidate an operator has
        # to wait 11 s to hear is not auditionable.
        if '--no-bake' not in sys.argv:
            print('── filling the Voices tab take cache ──', flush=True)
            bake(b)
    return 0


if __name__ == '__main__':
    sys.exit(main())
