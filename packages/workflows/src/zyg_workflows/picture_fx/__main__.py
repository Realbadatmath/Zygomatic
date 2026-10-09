# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.picture_fx` — the bare sanity read the old
picture_fx.py carried as its `if __name__ == '__main__'` block.
"""

from zyg_workflows.picture_fx.render import ops_payload

if __name__ == '__main__':  # a bare sanity read, not a test suite
    pl = ops_payload()
    print(
        f'{pl["counts"]["total"]} tools in {len(pl["sections"])} sections: '
        f'{pl["counts"]["deterministic"]} deterministic, {pl["counts"]["service"]} service, '
        f'{pl["counts"]["generative"]} generative, '
        f'{pl["counts"]["total"] - pl["counts"]["deterministic"] - pl["counts"]["service"] - pl["counts"]["generative"]} actions'
    )
    for s_ in pl['sections']:
        print(f'  {s_["bar"]:5} {s_["sec"]:<10} {len(s_["items"]):>3}')
