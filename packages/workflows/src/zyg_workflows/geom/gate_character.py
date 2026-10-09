# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""gate_character.py — the readable-geometry gate, applied to characters (2026-08-04).

RUN:
    python3 -m zyg_workflows.geom.gate_character <char_id> [--vlm] [--limit N]

The rule is the same one the tree passed: everything must have readable geometry AT THE
SCALE IT OCCUPIES, and what the detector says exists must actually be addressable. Checks,
per cell:

  GC1 conditional coverage   IF a face was detected, all nine face regions must exist and
                             clear their Nyquist floors. IF a body was detected, the core
                             body regions must exist. A rear view owes hair and torso, not
                             lips — expectations follow the detection, because demanding
                             lips of the back of a head would train everyone to ignore
                             the gate.
  GC2 region readability     each present region re-uses gate.g1_silhouette: pixel area
                             above floor and thinnest feature above 2px. An iris of 3
                             pixels is decoration, not a region you can inpaint.
  GC3 assignment coverage    the fraction of person-mask pixels carrying NO region id.
                             Unassigned person pixels are pixels nothing downstream can
                             address — the exact blindness this system exists to remove.
  GC4 recognisable (--vlm)   region crops to the local judge, ALWAYS_JUDGE semantics:
                             "is this an eye", "is this a mouth". Reject-only, never
                             breaks the run — same contract as every VLM gate here.

Region area floors are in PIXELS OF THE REGION'S OWN KIND, not fractions of frame: an
iris is tiny in every portrait ever framed, so its floor is 20px where torso's is 900.
"""

import argparse
import glob
import json
import os
import sys

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from . import gate
from . import regions as R
from .char_mesh import OUT_ROOT

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# Minimum readable area per region, px. Scaled to what each region IS, not to the frame.
AREA_FLOOR = {
    'iris_left': 20,
    'iris_right': 20,
    'eye_left': 60,
    'eye_right': 60,
    'brow_left': 40,
    'brow_right': 40,
    'lips': 150,
    'nose': 200,
    'face_skin': 1500,
    'ear_left': 80,
    'ear_right': 80,
    'hair_head': 800,
    # neck floor 60, not 100: the Second Ledger cast wears ruff collars, which occlude
    # most of the anatomical neck by COSTUME — a 70px visible neck on a portrait is the
    # wardrobe working, not the mesh failing.
    'neck': 60,
    'torso': 900,
    'upper_arm_left': 150,
    'upper_arm_right': 150,
    'forearm_left': 100,
    'forearm_right': 100,
    'hand_left': 60,
    'hand_right': 60,
    'thigh_left': 200,
    'thigh_right': 200,
    'shin_left': 120,
    'shin_right': 120,
    'foot_left': 50,
    'foot_right': 50,
}

# What a detection owes. Ears stay out of the face set: they are visibility-gated on
# purpose (an ear under hair is legitimately absent) and gating on them would punish
# every haircut in the cast.
EXPECT_FACE = (
    'face_skin',
    'brow_left',
    'brow_right',
    'eye_left',
    'eye_right',
    'iris_left',
    'iris_right',
    'nose',
    'lips',
)
EXPECT_BODY = ('torso', 'neck')

# Unassigned-person ceiling. Measured headroom: portraits assign >97% of person pixels;
# 10% tolerates ragged mask borders without letting a whole limb go missing.
MAX_UNASSIGNED = 0.10


def gate_cell(cell_dir, use_vlm=False, log_fn=None):
    """Gate one processed cell. Returns a list of gate.Finding."""
    with open(os.path.join(cell_dir, 'mesh.json')) as f:
        mesh = json.load(f)
    rm = cv2.imread(os.path.join(cell_dir, 'regions.png'), cv2.IMREAD_GRAYSCALE)
    name = os.path.basename(cell_dir)
    findings = []

    class _PS:
        """regions.png quacking like a PassSet: mask() over region ids."""

        def __init__(self, arr):
            self.index = arr.astype(np.int32)
            self.valid = np.ones_like(arr, bool)
            self.h, self.w = arr.shape

        def mask(self, idx):
            return self.index == int(idx)

    ps = _PS(rm)

    expected = []
    if mesh.get('face'):
        expected += list(EXPECT_FACE)
    if mesh.get('body'):
        expected += list(EXPECT_BODY)
    if not expected:
        findings.append(gate.Finding('GC1', name, False, 0, 1, '', 'nothing detected at all — cell is ungated pixels'))
        return findings

    for reg in expected:
        rid = R.REGION_IDX[reg]
        area = int(ps.mask(rid).sum())
        floor = AREA_FLOOR.get(reg, 50)
        if area == 0:
            findings.append(
                gate.Finding('GC1', '%s.%s' % (name, reg), False, 0.0, floor, 'px', 'expected region is ABSENT')
            )
            continue
        findings.append(
            gate.Finding('GC1', '%s.%s' % (name, reg), area >= floor, area, floor, 'px', 'region area vs floor')
        )
        if area >= floor:
            g1 = gate.g1_silhouette(ps, rid, '%s.%s' % (name, reg))
            findings.append(g1[0])  # thinnest-feature Nyquist check

    person = mesh.get('person_px') or 0
    if person:
        assigned = int((rm > 0).sum())
        unass = max(0.0, 1.0 - assigned / float(person))
        findings.append(
            gate.Finding(
                'GC3',
                name,
                unass <= MAX_UNASSIGNED,
                unass,
                MAX_UNASSIGNED,
                'frac',
                '%d of %d person px carry no region id' % (max(0, person - assigned), person),
            )
        )

    if use_vlm and mesh.get('face'):
        img = mesh.get('image')
        for reg in ('eye_left', 'lips'):
            rid = R.REGION_IDX[reg]
            findings += gate.g4_recognisable(
                img, ps, rid, '%s.%s' % (name, reg), cell_dir, tier=gate.SET, log_fn=log_fn
            )
    return findings


def run(char_id, use_vlm=False, limit=0):
    root = os.path.join(OUT_ROOT, char_id)
    cells = sorted(d for d in glob.glob(os.path.join(root, 'cell_*')) if os.path.isdir(d))
    if limit:
        cells = cells[:limit]
    if not cells:
        raise SystemExit('no processed cells under %s — run geom.char_mesh first' % root)

    findings = []
    for c in cells:
        findings += gate_cell(c, use_vlm=use_vlm)
    doc = gate.report(findings, os.path.join(root, 'gate_report.json'), title='character mesh gate — %s' % char_id)
    fails = [f for f in doc['findings'] if not f['passed']]
    _zyg_log.info('%s: %d cells, %d checks, %d failed' % (char_id, len(cells), doc['n_checks'], doc['n_failed']))
    for f in fails[:20]:
        _zyg_log.info(
            '  FAIL %-4s %-28s %.1f vs %.1f %s — %s'
            % (f['check'], f['obj'], f['value'] or 0, f['threshold'] or 0, f['units'], f['detail'][:60])
        )
    if len(fails) > 20:
        _zyg_log.info('  ... and %d more (see gate_report.json)' % (len(fails) - 20))
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('char_id')
    ap.add_argument('--vlm', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args(argv)
    doc = run(a.char_id, use_vlm=a.vlm, limit=a.limit)
    return 0 if doc['passed'] else 2


if __name__ == '__main__':
    sys.exit(main())
