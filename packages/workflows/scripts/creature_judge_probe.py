#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
creature_judge_probe.py — run the creature cell judge on one strip and print
every answer with the judge's own reason (and raw reply on a parse failure).

    .venv/bin/python scripts/creature_judge_probe.py STRIP.png [--angle "a top-down view"] [--kind body] [--tier resident] [--no-offload]

Use it when a sheet flags every question at once — that pattern is a protocol
or parsing failure, not a verdict, and this shows which.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CREWS)
os.chdir(_CREWS)

from zyg_workflows import creature_judge as cj  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('strip')
    ap.add_argument('--angle', default='a straight-on front view showing the whole body')
    ap.add_argument('--kind', default='body')
    ap.add_argument('--tier', default='')
    ap.add_argument('--no-offload', action='store_true')
    ap.add_argument('--keep', action='store_true', help='keep worker tempdir (ZYG_VLM_KEEP_FRAMES=1)')
    a = ap.parse_args()
    if a.tier:
        os.environ['ZYG_CREATURE_JUDGE_TIER'] = a.tier
    if a.keep:
        os.environ['ZYG_VLM_KEEP_FRAMES'] = '1'
    base = cj.load_items(cj.CELL_CHECKLIST)
    items = cj.cell_items(a.angle, kind=a.kind, base=base)
    out = cj.judge_batch(
        [{'key': 'probe', 'image': os.path.abspath(a.strip), 'items': items, 'preamble': base.get('preamble', '')}],
        offload=not a.no_offload,
        log_fn=lambda m: print('   ', m[:200]),
    )
    v = out.get('probe') or {}
    print(json.dumps({k: v.get(k) for k in ('judged', 'ok', 'tier', 'model', 'flags', 'reason')}, indent=1))
    for rec in v.get('verdicts') or []:
        print(
            f'{rec["id"]:16s} answer={rec.get("answer")!s:8s} expected={rec.get("expected")} ok={rec.get("ok")}  reason: {(rec.get("reason") or "")[:160]}'
        )
    return 0


if __name__ == '__main__':
    sys.exit(main())
