# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""gate_scene.py — run the readable-geometry gate over a built scene (2026-08-04).

RUN:
    python3 -m zyg_workflows.geom.gate_scene output/axe_forest/tree [--styled path.png] [--vlm]

Consumes what prop_mesh/tree_build.py writes:

    hero/         the plate, with everything in it
    trunk_cut/    trunk WITH the wounds        }  G3  — does the relief reach the passes
    trunk_plain/  trunk WITHOUT them           }
    axe_alone/    the weapon with its host hidden  }  G3b — is it in the wood or on it
    tree_meta.json  the strike log

and checks every renderable object against the rules:

    every object has readable geometry   G1  silhouette, at the tier its coverage earns
    the detail is really there           G3  paired depth/normal against a flat proxy
    what should be inside, is            G3b occlusion by its host
    the texture can carry the framing    G2  texel supply vs the shot's demand
    it still reads after styling         G4  local VLM on the crop, hero tier only

G5 IS SPECIFIC TO THIS PRODUCTION AND IS THE ONE THE WEAPON EARNS. Every mark on the trunk
was cut by the hurlbat, whose plate is 6mm and whose bit is 108mm, so no mark may be wider
than the steel plus the chip it splits out, nor longer than the edge that made it. The
strike log is checked against the weapon it claims to come from — which is only possible
because the cutters were derived from the blade instead of chosen.
"""

import argparse
import json
import os
import sys

from . import gate

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# world size of each object, metres — G2 cannot compute texel density without it
WORLD_SPAN = {'trunk': 0.84, 'axe_head': 0.355, 'ground': 12.0}
TEXTURE_PX = {'trunk': 4096, 'ground': 4096}


def _load(root, name):
    p = os.path.join(root, name)
    return gate.load_set(p) if os.path.isdir(p) else None


def check_strikes(meta, findings):
    """G5 — no mark may exceed what this weapon can make."""
    w = (meta or {}).get('weapon') or {}
    strikes = (meta or {}).get('strikes') or []
    if not strikes or not w:
        return
    plate = float(w.get('plate_m') or 0.006)
    # the widest possible mark: full plate plus the chip split out at the deepest strike
    deepest = max(float(s.get('depth_m') or 0) for s in strikes)
    max_width = plate + 2 * deepest * 0.5774  # tan(30 degrees)
    # the longest mark any element can leave, read from the weapon rather than copied
    chords = w.get('element_chord_m') or {}
    max_length = max(chords.values()) if chords else 0.1085

    bad_w = [s for s in strikes if float(s.get('width_m') or 0) > max_width * 1.001]
    bad_l = [s for s in strikes if float(s.get('length_m') or 0) > max_length * 1.001]
    bad_k = [s for s in strikes if float(s.get('kerf_m') or 0) > plate * 1.001]

    findings.append(
        gate.Finding(
            'G5',
            'strikes',
            not bad_w,
            len(bad_w),
            0,
            'marks',
            'marks wider than the weapon can cut (max %.1fmm at %.1fmm deep)' % (max_width * 1000, deepest * 1000),
        )
    )
    findings.append(
        gate.Finding(
            'G5b',
            'strikes',
            not bad_l,
            len(bad_l),
            0,
            'marks',
            'marks longer than the %.0fmm longest edge on the weapon' % (max_length * 1000),
        )
    )
    findings.append(
        gate.Finding(
            'G5c', 'strikes', not bad_k, len(bad_k), 0, 'marks', 'kerfs wider than the %.0fmm plate' % (plate * 1000)
        )
    )


def run(root, styled=None, use_vlm=False):
    hero = _load(root, 'hero')
    if hero is None:
        raise SystemExit('no hero pass set in %s — run prop_mesh/tree_build.py first' % root)
    cut, plain = _load(root, 'trunk_cut'), _load(root, 'trunk_plain')
    alone = _load(root, 'axe_alone')

    meta = {}
    mp = os.path.join(root, 'tree_meta.json')
    if os.path.exists(mp):
        with open(mp) as f:
            meta = json.load(f)
    idx = meta.get('pass_index') or {'trunk': 1, 'axe_head': 2, 'ground': 5}

    findings = []
    tiers = {}
    for name, i in sorted(idx.items()):
        m = hero.mask(i)
        if not m.any():
            continue
        fs = gate.g1_silhouette(hero, i, name)
        findings += fs
        tiers[name] = fs[0]['tier']
        if name in WORLD_SPAN and name in TEXTURE_PX:
            findings += gate.g2_texel(hero, i, name, WORLD_SPAN[name], TEXTURE_PX[name])

    if cut and plain:
        findings += gate.g3_relief(cut, plain, idx.get('trunk', 1), 'wounds')
    if alone:
        findings += gate.g3b_embedment(alone, hero, idx.get('axe_head', 2), 'hurlbat', host='trunk')

    check_strikes(meta, findings)

    if styled and use_vlm:
        for name, i in sorted(idx.items()):
            if tiers.get(name) == gate.HERO or name in gate.ALWAYS_JUDGE:
                findings += gate.g4_recognisable(styled, hero, i, name, root, tier=tiers.get(name, gate.SET))

    doc = gate.report(
        findings, os.path.join(root, 'gate_report.json'), title='readable-geometry gate — %s' % os.path.basename(root)
    )
    gate.print_report(doc)
    if tiers:
        _zyg_log.info('  tiers: ' + ', '.join('%s=%s' % kv for kv in sorted(tiers.items())))
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('root')
    ap.add_argument('--styled', default=None)
    ap.add_argument('--vlm', action='store_true')
    a = ap.parse_args(argv)
    doc = run(a.root, styled=a.styled, use_vlm=a.vlm)
    return 0 if doc['passed'] else 2


if __name__ == '__main__':
    sys.exit(main())
