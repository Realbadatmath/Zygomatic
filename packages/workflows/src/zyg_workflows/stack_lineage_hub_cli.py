# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.stack_lineage_hub`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.stack_lineage_hub` still reaches it.
"""

import json
import sys

from zyg_workflows.stack_lineage_hub import (
    load_store,
    section_stack_lineage,
    validate,
)


def main() -> int:
    """The command line that used to live under `if __name__ == '__main__'` in stack_lineage_hub."""
    if len(sys.argv) > 1 and sys.argv[1] == 'check':
        bad = validate()
        for line in bad:
            print('FAIL ' + line)
        store = load_store()
        ents = sum(len(l['entities']) for l in store['lanes'])
        iss = sum(len(e.get('issues') or []) for l in store['lanes'] for e in l['entities'])
        print(f'{len(store["lanes"])} lanes, {ents} entities, {iss} issues, {len(bad)} problems')
        return 1 if bad else 0
    print(json.dumps(section_stack_lineage(fresh=True), indent=1, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
