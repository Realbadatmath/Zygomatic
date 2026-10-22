# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""drift_gate.py — region-wise identity drift across a character's angles (2026-08-04).

RUN:
    python3 -m zyg_workflows.geom.drift_gate <char_id> [--k 3.5]

WHAT THIS REPLACES. The existing identity drift checks compare whole images — embeddings
or judge verdicts over full frames — which is why a character whose left iris silently
turned brown in four cells could still pass: four small brown discs barely move a global
embedding. The region maps make drift ADDRESSABLE: iris is compared to iris, hair to
hair, lips to lips, across all 48 angles, in numbers.

HOW IT MEASURES.
For every cell where a region is present and readable (>= the gate's area floor), the
region's colour is summarised in CIELAB — Lab because Euclidean distance there
approximates perceptual difference, which BGR distance does not. Per region, the corpus
median and MAD (median absolute deviation) are computed across cells, and a cell whose
region sits further than k*MAD from the median on any Lab axis is flagged as a drift
outlier. Median/MAD, not mean/std: a handful of drifted cells must not be allowed to drag
the "normal" toward themselves, which is precisely what they would do to a mean.

WHAT IT DOES NOT CLAIM. Colour statistics catch colour drift (iris colour, hair colour,
skin tone, lip tone) — the drift class that actually bit this production (hair_color
negatives, freckle governance were both colour incidents). They do not catch shape drift;
that is the fitter's reprojection residual's job, later. Lighting variation across angles
inflates L spread, so L gets a wider tolerance than a/b: chroma is identity, luminance is
mostly lighting.

DECLARED CHARACTERISTICS. If the manifest's character entry declares region
characteristics (e.g. iris 'grey-blue'), the measured corpus median hue is checked
against the declared colour family — a coarse, honest check: it will catch grey-blue
irises that measure warm brown, and it will not pretend to distinguish grey-blue from
blue-grey.
"""

import glob
import json
import os

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from . import gate
from . import regions as R
from .char_mesh import OUT_ROOT

# Regions whose colour is identity-bearing. Clothing regions are excluded on purpose —
# wardrobe changes between shots are storytelling, not drift.
DRIFT_REGIONS = ('iris_left', 'iris_right', 'hair_head', 'face_skin', 'lips', 'brow_left', 'brow_right')

# Minimum readable pixels before a region's colour means anything.
MIN_PX = {
    'iris_left': 24,
    'iris_right': 24,
    'brow_left': 40,
    'brow_right': 40,
    'lips': 120,
    'hair_head': 900,
    'face_skin': 1200,
}

# L tolerance multiplier vs a/b — luminance is mostly lighting, chroma is identity.
L_RELAX = 1.8

# Coarse colour families for declared-characteristic checks: Lab box per family name.
# Deliberately broad; the check is "is this even the right family", not colour science.
FAMILIES = {
    'grey-blue': {'a': (-14, 6), 'b': (-30, 4)},
    'blue': {'a': (-16, 6), 'b': (-42, -4)},
    'brown': {'a': (2, 26), 'b': (6, 42)},
    'dark brown': {'a': (0, 22), 'b': (2, 34)},
    'light brown': {'a': (2, 24), 'b': (8, 44)},
    'black': {'a': (-8, 10), 'b': (-10, 12)},
    'green': {'a': (-36, -4), 'b': (-4, 30)},
}


def _region_lab(img_bgr, region_map, rid):
    m = region_map == rid
    if not m.any():
        return None, 0
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    # OpenCV Lab: L in 0..255 (L*255/100), a/b offset by 128
    px = lab[m]
    med = np.median(px, axis=0)
    return [float(med[0]) * 100.0 / 255.0, float(med[1]) - 128.0, float(med[2]) - 128.0], int(m.sum())


def run(char_id, k=3.5):
    root = os.path.join(OUT_ROOT, char_id)
    cells = sorted(d for d in glob.glob(os.path.join(root, 'cell_*')) if os.path.isdir(d))
    if not cells:
        raise SystemExit('no processed cells — run geom.char_mesh first')

    # ── measure ─────────────────────────────────────────────────────────────
    per_region = {r: {} for r in DRIFT_REGIONS}
    for c in cells:
        rm = cv2.imread(os.path.join(c, 'regions.png'), cv2.IMREAD_GRAYSCALE)
        with open(os.path.join(c, 'mesh.json')) as f:
            img_path = json.load(f)['image']
        img = cv2.imread(img_path)
        if rm is None or img is None:
            continue
        name = os.path.basename(c)
        for reg in DRIFT_REGIONS:
            lab, n = _region_lab(img, rm, R.REGION_IDX[reg])
            if lab is not None and n >= MIN_PX.get(reg, 50):
                per_region[reg][name] = {'lab': lab, 'px': n}

    # ── corpus stats + outliers ─────────────────────────────────────────────
    findings, table = [], {}
    for reg, cells_d in per_region.items():
        if len(cells_d) < 5:
            table[reg] = {'cells': len(cells_d), 'note': 'too few readable cells to judge drift'}
            continue
        labs = np.array([v['lab'] for v in cells_d.values()], np.float32)
        med = np.median(labs, axis=0)
        mad = np.median(np.abs(labs - med), axis=0) + 1e-3
        tol = np.array([k * L_RELAX, k, k], np.float32)
        outliers = {}
        for name, v in cells_d.items():
            z = np.abs(np.array(v['lab']) - med) / mad
            worst = float((z / tol).max())
            if worst > 1.0:
                axis = 'Lab'[int((z / tol).argmax())]
                outliers[name] = {
                    'z': [round(float(x), 1) for x in z],
                    'axis': axis,
                    'lab': [round(x, 1) for x in v['lab']],
                }
        table[reg] = {
            'cells': len(cells_d),
            'median_lab': [round(float(x), 1) for x in med],
            'mad': [round(float(x), 2) for x in mad],
            'outliers': outliers,
        }
        findings.append(
            gate.Finding(
                'GD1',
                reg,
                not outliers,
                len(outliers),
                0,
                'cells',
                'colour-drift outliers beyond %.1f*MAD (median Lab %s over %d cells)'
                % (k, [round(float(x), 1) for x in med], len(cells_d)),
            )
        )

    # ── declared characteristics ────────────────────────────────────────────
    try:
        from . import manifest

        man = manifest.Manifest()
        char = next(
            (
                a
                for a in man.list('character')
                if (a.get('notes') or '').lower().find(char_id[:8]) >= 0 or char_id in json.dumps(a.get('refs') or [])
            ),
            None,
        )
        declared = ((char or {}).get('mesh') or {}).get('characteristics') or {}
    except Exception:
        declared = {}
    for reg, props in declared.items():
        colour = (props or {}).get('colour')
        fam = FAMILIES.get(str(colour or '').lower())
        info = table.get(reg) or {}
        med = info.get('median_lab')
        if not colour or not fam or not med:
            continue
        ok = (fam['a'][0] <= med[1] <= fam['a'][1]) and (fam['b'][0] <= med[2] <= fam['b'][1])
        findings.append(
            gate.Finding(
                'GD2',
                reg,
                ok,
                med[2],
                None,
                'b*',
                'declared "%s": corpus median Lab %s %s the %s family box'
                % (colour, med, 'inside' if ok else 'OUTSIDE', colour),
            )
        )

    doc = gate.report(findings, os.path.join(root, 'drift_report.json'), title='region drift gate — %s' % char_id)
    doc['regions'] = table
    with open(os.path.join(root, 'drift_report.json'), 'w') as f:
        json.dump(doc, f, indent=1)
    return doc


def main(*a, **k):
    """Delegate to the CLI, which is where this gate's printing entry point now lives."""
    from zyg_workflows.geom.drift_gate_cli import main as _m

    return _m(*a, **k)


if __name__ == '__main__':  # the CLI lives in drift_gate_cli
    from zyg_workflows.geom.drift_gate_cli import main as _cli_main

    raise SystemExit(_cli_main())
