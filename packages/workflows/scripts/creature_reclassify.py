#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""creature_reclassify.py — re-apply the pass/soft/exclude policy to a finished sheet
without re-rendering (re-judges only cells whose hard flag is a vlm identity check),
and record OPERATOR decisions taken at the review gate.

    .venv/bin/python scripts/creature_reclassify.py <creature_id> [--no-rejudge]
    .venv/bin/python scripts/creature_reclassify.py <creature_id> --exclude 08,10 --reason "tail reads as a horn"
    .venv/bin/python scripts/creature_reclassify.py <creature_id> --include 08

An operator exclusion is stored on the cell as a hard reason ``operator:<reason>``
(never a vlm: flag, so later reclassify runs keep it); --include removes it.
Rewrites sheet.png / sheet.json / cell checkpoints, the job state and the manifest.
"""

import argparse
import json
import os
import sys

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CREWS)
os.chdir(_CREWS)
os.environ.setdefault('ZYG_COMFY_PRIMARY', '1')
os.environ.setdefault('ZYG_USE_COMFYUI', '1')
from zyg_workflows import creature_sheet_service as css  # noqa: E402
from zyg_workflows import creature_training_service as cts  # noqa: E402


def _idxs(s: str) -> set[int]:
    return {int(x) for x in s.replace(' ', '').split(',') if x != ''}


ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('cid')
ap.add_argument('--no-rejudge', action='store_true')
ap.add_argument('--exclude', default='', help='cell indexes to exclude from training, e.g. "08,10"')
ap.add_argument('--include', default='', help='cell indexes whose operator exclusion is lifted')
ap.add_argument('--reason', default='operator review', help='why (stored with --exclude)')
a = ap.parse_args()

cid = a.cid
ds = os.path.join(cts.DATASET_ROOT, cid)
rejudge = not a.no_rejudge
if a.exclude or a.include:
    rp = css.report_path(ds)
    rep0 = json.load(open(rp, encoding='utf-8'))
    ex, inc = _idxs(a.exclude), _idxs(a.include)
    reason = a.reason.strip().replace(',', ';')[:80] or 'operator review'
    for c in rep0.get('cells') or []:
        i = int(c.get('idx', -1))
        if i in ex:
            c['reasons'] = [r for r in (c.get('reasons') or []) if not r.startswith('operator:')] + [
                f'operator:{reason}'
            ]
            c['operator'] = {'exclude': True, 'reason': reason}
            print(f'   cell {i:02d} excluded by operator: {reason}')
        elif i in inc:
            c['reasons'] = [r for r in (c.get('reasons') or []) if not r.startswith('operator:')]
            c.pop('operator', None)
            print(f'   cell {i:02d} operator exclusion lifted')
    json.dump(rep0, open(rp, 'w', encoding='utf-8'), indent=2, default=str)
    rejudge = False  # an operator decision never needs the judge back on the GPU
rep = css.reclassify(ds, rejudge_hard=rejudge, log_fn=lambda m: print('   ', m[:200], flush=True))
summary = cts.sheet_summary(rep)
sp = os.path.join(_CREWS, 'data', 'runtime', f'creature_gen_{cid}.json')
try:
    st = json.load(open(sp, encoding='utf-8'))
    st['sheet_report'] = summary
    st['image_count'] = int(rep.get('pass_count') or 0) + len(rep.get('refs') or [])
    json.dump(st, open(sp, 'w', encoding='utf-8'), default=str)
except Exception as exc:
    print('state not updated:', exc)
mp = os.path.join(ds, 'manifest.json')
try:
    m = json.load(open(mp, encoding='utf-8'))
    m['sheet_report'] = summary
    m['images'] = [c.get('path') for c in rep.get('cells') or [] if c.get('ok')]
    m['total'] = int(rep.get('pass_count') or 0)
    json.dump(m, open(mp, 'w', encoding='utf-8'), indent=2, default=str)
except Exception as exc:
    print('manifest not updated:', exc)
print(json.dumps(summary, indent=1))
