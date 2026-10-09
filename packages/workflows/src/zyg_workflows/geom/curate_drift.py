# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""curate_drift.py — act on the drift gate: pull flagged cells from the LoRA sets.

RUN:
    python3 -m zyg_workflows.geom.curate_drift <char_id> [--apply]     (default is a dry run)

THE POLICY, AND WHY IT IS THIS AND NOT STRICTER.
The drift gate flags region-colour outliers per cell. Not every flag is a bad training
image: L-axis (luminance) outliers are mostly LIGHTING — a rim-lit profile reads dark
without being a different boy — and a single drifted region can be an accident of pose.
So the quarantine rule is:

    quarantine a cell when >= 2 REGIONS flag on a CHROMA axis (a* or b*)

Chroma is identity (the measured incidents this production has actually had — hair
colour, freckle tint, iris shade — are all chroma); luminance flags and single-region
chroma flags stay as warnings in the report. Measured on Abel this quarantines 6 of 48
cells, including cell_12 (4 regions: the purple-jacket warm-grade cell verified by eye).

MECHANICS. Files MOVE (with their caption .txt) into images/_drift_quarantine_<date>/ —
both known consumers (wan_lora/prep_dataset.py and lora_trainer_service's counter) use
non-recursive os.listdir, so a subfolder is invisible to training, and the move is
reversible by moving files back. CURATION.json records every move with its evidence and
the reversal instruction. NOTHING IS RETRAINED HERE: retraining changes a character's
identity and stays a human decision.
"""

import argparse
import json
import os
import shutil
import sys
import time

from .char_mesh import OUT_ROOT, DATASETS


def plan(char_id):
    rep_path = os.path.join(OUT_ROOT, char_id, 'drift_report.json')
    with open(rep_path) as f:
        rep = json.load(f)
    votes, evidence = {}, {}
    for region, info in (rep.get('regions') or {}).items():
        for cell, d in (info.get('outliers') or {}).items():
            axis = d.get('axis')
            evidence.setdefault(cell, []).append({'region': region, 'axis': axis, 'lab': d.get('lab'), 'z': d.get('z')})
            if axis in ('a', 'b'):
                votes[cell] = votes.get(cell, 0) + 1
    quarantine = sorted(c for c, n in votes.items() if n >= 2)
    warn = sorted(set(evidence) - set(quarantine))
    return quarantine, warn, evidence


def apply(char_id, quarantine, evidence, log=print):
    img_dir = os.path.join(DATASETS, char_id, 'images')
    qdir = os.path.join(img_dir, '_drift_quarantine_%s' % time.strftime('%Y%m%d'))
    os.makedirs(qdir, exist_ok=True)
    moved = []
    for cell in quarantine:
        for ext in ('.png', '.txt'):
            src = os.path.join(img_dir, cell + ext)
            if os.path.exists(src):
                shutil.move(src, os.path.join(qdir, cell + ext))
                moved.append(cell + ext)
    doc = {
        'char_id': char_id,
        'date': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'policy': '>=2 regions flagged on a chroma axis (a*/b*), k=3.5 MAD',
        'quarantined': quarantine,
        'moved_files': moved,
        'evidence': {c: evidence[c] for c in quarantine},
        'reversal': 'move the files back into images/ — both trainer consumers use '
        'non-recursive os.listdir, nothing else references this folder',
        'note': 'NOT retrained. Retraining alters the character and is a human decision.',
    }
    with open(os.path.join(qdir, 'CURATION.json'), 'w') as f:
        json.dump(doc, f, indent=1)
    log('  moved %d files -> %s' % (len(moved), qdir))
    return qdir, doc


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('char_id')
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args(argv)
    quarantine, warn, evidence = plan(a.char_id)
    print('%s: quarantine %d cells %s' % (a.char_id, len(quarantine), quarantine))
    print('  warnings (kept): %d cells %s' % (len(warn), warn[:10]))
    for c in quarantine:
        ev = ', '.join('%s/%s' % (e['region'], e['axis']) for e in evidence[c])
        print('    %-9s %s' % (c, ev))
    if a.apply:
        apply(a.char_id, quarantine, evidence)
    else:
        print('  DRY RUN — pass --apply to move files')
    return 0


if __name__ == '__main__':
    sys.exit(main())
