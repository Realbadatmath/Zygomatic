#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
creature_lock.py — set / show a creature's body-plan lock (brief.json).

    python3 scripts/creature_lock.py CID --show
    python3 scripts/creature_lock.py CID --body-plan "a ball-shaped body, almost as wide as it is tall; one segmented glossy turquoise tail curling up behind the body; two short turquoise arms; two turquoise three-toed feet"
    python3 scripts/creature_lock.py CID --side  /path/to/right_side_profile.png   # tail source
    python3 scripts/creature_lock.py CID --full  /path/to/front_full_body.png      # replaces the derived anchor
    python3 scripts/creature_lock.py CID --negative "wings, fins, flippers, second tail"
    python3 scripts/creature_lock.py CID --clear-locks | --clear-body-plan

Lock images are COPIED into <dataset>/locks/ so the lock never points at a
scratch file. Then re-render the sheet:

    scripts/creature_worker.py --resume CID --phase sheet

Cells rendered from a changed anchor (or with a changed body plan) re-render;
everything else comes back from its checkpoint. What the lock does is
documented at the top of creature_sheet_service.py ("Body-plan lock").
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys

from zyg_workflows import paths

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CREWS)

DATASET_ROOT = os.environ.get('ZYG_CREATURE_DATASET_ROOT', str(paths.ZYG_LORA_DATASETS / 'creatures'))


def _dataset_dir(cid: str) -> str:
    if not re.match(r'^[a-f0-9]{12}$', cid or ''):
        sys.exit(f'bad creature id: {cid!r}')
    d = os.path.join(DATASET_ROOT, cid)
    if not os.path.isdir(d):
        sys.exit(f'no dataset for creature {cid}: {d}')
    return d


def _load(path: str) -> dict:
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return {}


def _copy_lock(dataset_dir: str, kind: str, src: str) -> str:
    src = os.path.abspath(src)
    if not os.path.isfile(src):
        sys.exit(f'{kind} lock image not found: {src}')
    ldir = os.path.join(dataset_dir, 'locks')
    os.makedirs(ldir, exist_ok=True)
    dst = os.path.join(ldir, f'{kind}_{os.path.basename(src)}')
    if os.path.abspath(dst) != src:
        shutil.copy2(src, dst)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cid')
    ap.add_argument('--body-plan', default=None, help='one anatomy sentence (semicolon-separated parts)')
    ap.add_argument('--side', default=None, help='RIGHT-side full-body profile that shows the tail')
    ap.add_argument('--full', default=None, help='front full-body image that replaces the derived anchor')
    ap.add_argument('--negative', default=None, help='extra negative terms for every edit')
    ap.add_argument('--clear-locks', action='store_true')
    ap.add_argument('--clear-body-plan', action='store_true')
    ap.add_argument('--show', action='store_true')
    a = ap.parse_args()

    ds = _dataset_dir(a.cid)
    bpath = os.path.join(ds, 'brief.json')
    brief = _load(bpath)
    if not brief:
        sys.exit(f'no brief.json in {ds} — run the sheet once first')
    changed = False
    if a.clear_locks:
        brief.pop('anchor_locks', None)
        changed = True
    if a.clear_body_plan:
        brief.pop('body_plan', None)
        changed = True
    if a.body_plan is not None:
        brief['body_plan'] = a.body_plan.strip()
        changed = True
    if a.negative is not None:
        brief['negative'] = a.negative.strip()
        changed = True
    locks = dict(brief.get('anchor_locks') or {})
    if a.side:
        locks['side'] = _copy_lock(ds, 'side', a.side)
        changed = True
    if a.full:
        locks['full_body'] = _copy_lock(ds, 'full_body', a.full)
        changed = True
    if a.side or a.full:
        brief['anchor_locks'] = locks
    if changed:
        with open(bpath, 'w', encoding='utf-8') as fh:
            json.dump(brief, fh, indent=2, ensure_ascii=False)
        # mirror into the job state so the board / review page show the lock
        # (best effort; the worker re-reads brief.json itself on resume)
        spath = os.path.join(_CREWS, 'data', 'runtime', f'creature_gen_{a.cid}.json')
        job = _load(spath)
        if job:
            jb = dict(job.get('brief') or {})
            for k in ('body_plan', 'anchor_locks', 'negative'):
                if k in brief:
                    jb[k] = brief[k]
                else:
                    jb.pop(k, None)
            job['brief'] = jb
            tmp = spath + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(job, fh, default=str)
            os.replace(tmp, spath)
        print(f'brief.json updated: {bpath}')
    print(
        json.dumps(
            {k: brief.get(k) for k in ('name', 'body_plan', 'anchor_locks', 'negative')}, indent=1, ensure_ascii=False
        )
    )
    if changed:
        print(f'\nre-render: scripts/creature_worker.py --resume {a.cid} --phase sheet')
    return 0


if __name__ == '__main__':
    sys.exit(main())
