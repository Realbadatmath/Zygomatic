# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.mesh_pack_dims`, moved out of the library module so that library
code never prints; `python -m zyg_workflows.mesh_pack_dims` still reaches it.
"""

import json
import sys

from zyg_workflows.mesh_pack_dims import run


def main() -> int:
    """What used to run under `if __name__` in mesh_pack_dims."""
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    print(json.dumps(run(args, '--force' in sys.argv)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
