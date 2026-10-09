# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.music_studio` — print the roster counts."""

from . import SECTIONS, spec

if __name__ == '__main__':
    import json as _json

    print(_json.dumps(spec()['counts'], indent=2))
    for _s in SECTIONS:
        print(f'  {_s["place"]:5s} {_s["title"]:20s} {len(_s["tools"]):3d}')
