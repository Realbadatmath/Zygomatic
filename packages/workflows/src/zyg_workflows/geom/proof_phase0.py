# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""proof_phase0.py — falsify the gate before building anything on top of it (2026-08-04).

RUN (after prop_mesh/gate_proof.py has written the pass sets):
    python3 -m zyg_workflows.geom.proof_phase0 [output/axe_forest/gate_proof]

THE CLAIM UNDER TEST.
g3b_embedment separates a hatchet driven into a trunk from the same hatchet lying flat
against it. `flat` is the real defect from 2026-08-03 — "not one axe is actually stuck in
the tree, all axes are just flat against it" — reproduced here as a 50mm translation
toward the camera and nothing else. Same mesh, same light, same camera, same seed.

The proof PASSES only if the gate says PASS on embedded and FAIL on flat. A gate that
agrees with itself on both configurations is measuring something other than seating, and
every phase downstream would inherit that blind spot.

The scars are checked the same way: trunk with the boolean cuts on vs off, which is the
paired input g3_relief needs.
"""

import json
import os
import sys

from . import gate

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

IDX = {'trunk': 1, 'axe_head': 2, 'axe_haft': 3}


def run(root='output/axe_forest/gate_proof'):
    sets = {}
    for n in (
        'trunk_cut',
        'trunk_plain',
        'axe_embedded_scene',
        'axe_embedded_alone',
        'axe_flat_scene',
        'axe_flat_alone',
    ):
        p = os.path.join(root, n)
        if not os.path.isdir(p):
            raise SystemExit('missing pass set %s — run prop_mesh/gate_proof.py first' % p)
        sets[n] = gate.load_set(p)

    findings, verdicts = [], {}

    # ── G1: is anything here resolvable at all ──────────────────────────────
    for obj, idx in IDX.items():
        src = 'trunk_cut' if obj == 'trunk' else 'axe_embedded_scene'
        findings += gate.g1_silhouette(sets[src], idx, obj)

    # ── G3: do the boolean cuts survive into depth and normals ──────────────
    findings += gate.g3_relief(sets['trunk_cut'], sets['trunk_plain'], IDX['trunk'], 'scars')

    # ── G3b: the discrimination test ────────────────────────────────────────
    # ONLY THE HEAD. The haft is supposed to jut OUT of the trunk toward the camera, so
    # the wood can never occlude it and its embedment is 0.000 in both configurations —
    # correctly. Running the check on it would report a permanent failure that no seating
    # could ever clear. Embedment applies to the part declared to be inside something,
    # which is why the manifest carries `embedded_in` per part rather than per object.
    for cfg in ('embedded', 'flat'):
        f = gate.g3b_embedment(
            sets['axe_%s_alone' % cfg], sets['axe_%s_scene' % cfg], IDX['axe_head'], 'axe_head[%s]' % cfg, host='trunk'
        )
        findings += f
        verdicts['%s.axe_head' % cfg] = f[0]

    doc = gate.report(
        findings, os.path.join(root, 'gate_report.json'), title='Phase 0 — gate falsification on the axe scene'
    )
    gate.print_report(doc)

    # ── the actual claim ────────────────────────────────────────────────────
    emb = verdicts['embedded.axe_head']
    flat = verdicts['flat.axe_head']
    ok = bool(emb['passed']) and not bool(flat['passed'])
    _zyg_log.info('')
    _zyg_log.info('DISCRIMINATION TEST — g3b_embedment on the hatchet head')
    _zyg_log.info('  embedded : %.4f  -> %s' % (emb['value'], 'PASS' if emb['passed'] else 'FAIL'))
    _zyg_log.info('  flat     : %.4f  -> %s' % (flat['value'] or 0.0, 'PASS' if flat['passed'] else 'FAIL'))
    _zyg_log.info(
        '  separation: %.4f (threshold %.2f)' % ((emb['value'] or 0) - (flat['value'] or 0), gate.TH['embedment_frac'])
    )
    _zyg_log.info(
        '  PROOF %s'
        % (
            'HOLDS — the gate catches the defect it was built for'
            if ok
            else 'FAILED — the metric does not separate the two; do not build on it'
        )
    )
    with open(os.path.join(root, 'proof_verdict.json'), 'w') as fh:
        json.dump({'proof_holds': ok, 'embedded': dict(emb), 'flat': dict(flat)}, fh, indent=1)
    return ok


if __name__ == '__main__':
    root = sys.argv[1] if len(sys.argv) > 1 else 'output/axe_forest/gate_proof'
    raise SystemExit(0 if run(root) else 2)
