# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.mesh_studio`, moved out of the library module so
that library code never prints; `python -m zyg_workflows.mesh_studio` still reaches it.
"""

import sys

from zyg_workflows import mesh_studio as M  # the importable copy — see load_parts() there


def main() -> int:
    d = M.ops_payload()
    w = max((len(s_['sec']) for s_ in d['sections']), default=0)
    for s_ in d['sections']:
        ph = sum(1 for it in s_['items'] if it['ph'])
        print(f'  {s_["bar"]:<5} {s_["sec"]:<{w}}  {len(s_["items"]):>3} ops  ({ph} placeholder)')
    c_ = d['counts']
    print(f'\n  {c_["total"]} ops · {c_["sections"]} sections · {c_["placeholder"]} placeholder · {c_["built"]} built')
    print(
        f'  deliberately absent: {len(M.MISSING)} '
        f'({", ".join(m["what"].split(" —")[0].split(" -")[0] for m in M.MISSING)})'
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
