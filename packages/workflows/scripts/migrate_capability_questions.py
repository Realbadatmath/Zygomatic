#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""migrate_questions.py — widen every capabilities sheet to the current questionnaire.

Column order per matrix:  DOMAIN → BANKS → preserved old → EXTRA → UNIVERSAL.
A recorded cell must always land in a column. If any would be orphaned the script
REFUSES to write anything and prints what would have been lost.

  (default)  compare only, write nothing
  --write    rewrite the sheets, keeping one .bak-<tag> per file
"""

import argparse
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from zyg_workflows import capabilities_questions as Q  # noqa: E402

STORE = os.path.join(ROOT, 'data', 'runtime', 'capabilities')


def matrices_of(sheet):
    return sheet['matrices'] if sheet.get('matrices') else [sheet]


def plan(step, old_cols):
    domain = Q.DOMAIN.get(step, [])
    banks = Q.BANKS.get(step, [])
    extra = Q.EXTRA.get(step, [])
    known = {c['id'] for c in domain + banks + extra + Q.UNIVERSAL}
    aliases = Q.ALIASES.get(step, {})
    preserved = [c for c in old_cols if c['id'] not in known and c['id'] not in aliases]
    out, seen = [], set()
    for c in domain + banks + preserved + extra + Q.UNIVERSAL:
        if c['id'] not in seen:
            seen.add(c['id'])
            out.append(copy.deepcopy(c))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--tag', default='promptdamage')
    args = ap.parse_args()

    orphans, changed, staged = [], [], []
    cols = grid = recorded = 0
    for name in sorted(os.listdir(STORE)):
        if not name.endswith('.json'):
            continue
        path = os.path.join(STORE, name)
        with open(path) as fh:
            sheet = json.load(fh)
        step = sheet['step']
        aliases = Q.ALIASES.get(step, {})
        before = after = 0
        for m in matrices_of(sheet):
            old = m.get('columns') or []
            new = plan(step, old)
            ids = {c['id'] for c in new}
            for r in m.get('rows') or []:
                cells = r.get('cells') or {}
                for old_id, new_id in aliases.items():
                    if old_id in cells and new_id in ids:
                        cells[new_id] = cells.pop(old_id)
                for cid in cells:
                    if cid not in ids:
                        orphans.append(f'{step}/{r["id"]}/{cid}')
                recorded += len(cells)
                grid += len(new)
            m['columns'] = new
            before += len(old)
            after += len(new)
        cols += after
        if after != before:
            changed.append((step, before, after))
        staged.append((path, sheet))

    print(f'50 sheets: {cols} columns, {grid} grid cells, {recorded} recorded cells')
    for step, b, a in changed:
        print(f'  {step}: {b} -> {a}')
    if not changed:
        print('  (no column changes — sheets already match the questionnaire)')
    if orphans:
        print(f'REFUSED — {len(orphans)} recorded cells would have no column:')
        for o in orphans[:40]:
            print('   ', o)
        return 1
    if args.write:
        for path, sheet in staged:
            bak = f'{path}.bak-{args.tag}'
            if not os.path.exists(bak):
                os.replace(path, bak)
            with open(path, 'w') as fh:
                json.dump(sheet, fh, indent=1, ensure_ascii=False)
        print(f'written ({len(staged)} sheets, backups *.bak-{args.tag})')
    else:
        print('check only — pass --write to apply')
    return 0


sys.exit(main())
