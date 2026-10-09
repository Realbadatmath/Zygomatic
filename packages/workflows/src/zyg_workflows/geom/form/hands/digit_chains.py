# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""t5_digit_chains and t5_phalanx_ratio.

Moved verbatim out of the old single-file hands.py (lines 2444-2956).
"""

import re
import numpy as np

from zyg_workflows.geom.form.hands.rig import (
    PASS,
    FAIL,
    UNMEASURABLE,
    MEASURED,
    CANON,
    FINGERS,
    DIGIT_BONES,
    RING_W_MIN,
    SEGMENT_W_MIN,
    _side,
    rig,
    resolve_hand,
)
from zyg_workflows.geom.form.hands.provenance import (
    _rec,
)
from zyg_workflows.geom.form.hands.unresolved import (
    DIGIT_UNRESOLVED_FOOT_RATIO,
)
from zyg_workflows.geom.form.hands.digits_rig import (
    TOE_BONES,
    TOES,
    LESSER_TOES,
    FOOT_BONE,
    SHANK_BONE,
    SKELETAL_COUNTS,
    BK2010,
    BK2010_SOURCE,
    HD2002,
    HD2002_SOURCE,
    AFS_P178_PARTS,
    AFS_P178_SOURCE,
    _ratio_band,
    _bone_weight,
    skeleton,
    _blen,
)


# ---------------------------------------------------------------------------------
# t5_digit_chains
# ---------------------------------------------------------------------------------
_RE_FINGER = re.compile(r'^finger(\d+)-(\d+)\.([LR])$')
_RE_METACARPAL = re.compile(r'^metacarpal(\d+)\.([LR])$')
_RE_TOE = re.compile(r'^toe(\d+)-(\d+)\.([LR])$')


def digit_roster():
    """The digit census, PARSED FROM THE RIG NAMES rather than read off DIGIT_BONES.

    A hand-typed bone table cannot verify a bone count: if DIGIT_BONES were missing the
    little finger's distal phalanx, a count over DIGIT_BONES would cheerfully report 13
    phalanges and call it correct. So the roster is regexed out of the 163 names anny
    actually ships, and DIGIT_BONES is then checked AGAINST it.
    """
    R = rig()
    names = R['names']
    hand = {}
    meta = {}
    foot = {}
    for nm in names:
        m1 = _RE_FINGER.match(nm)
        if m1:
            hand.setdefault((int(m1.group(1)), m1.group(3)), []).append(int(m1.group(2)))
            continue
        m2 = _RE_METACARPAL.match(nm)
        if m2:
            meta.setdefault(m2.group(2), []).append(int(m2.group(1)))
            continue
        m3 = _RE_TOE.match(nm)
        if m3:
            foot.setdefault((int(m3.group(1)), m3.group(3)), []).append(int(m3.group(2)))
    carpal = [
        n
        for n in names
        if re.match(
            r'^(scaphoid|lunate|triquetrum|pisiform|trapezium|trapezoid|'
            r'capitate|hamate|carpal)',
            n,
            re.I,
        )
    ]
    tarsal = [
        n
        for n in names
        if re.match(
            r'^(talus|calcaneus|navicular|cuboid|cuneiform|metatarsal|'
            r'tarsal)',
            n,
            re.I,
        )
    ]
    return {
        'finger_bones': {('%d' % d, s): sorted(v) for (d, s), v in hand.items()},
        'metacarpal_bones': {s: sorted(v) for s, v in meta.items()},
        'toe_bones': {('%d' % d, s): sorted(v) for (d, s), v in foot.items()},
        'carpal_bones': carpal,
        'tarsal_or_metatarsal_bones': tarsal,
        'shank_to_toe_path': [n for n in names if n in ('%s.L' % SHANK_BONE, '%s.L' % FOOT_BONE)],
        'n_bones': R['n_bones'],
    }


def metapodial_test(sk, side='L'):
    """Is digit 1's first bone a METAPODIAL or a PHALANX? Measured, no free parameter.

    A metacarpal/metatarsal spans from the wrist/tarsus to the MP joint; a proximal
    phalanx STARTS at that joint. So fit the MP joint line through digits 2-5's first
    bone heads — those are unambiguous, because in the hand the metacarpals of digits
    2-5 are named separately and in the foot there are no metatarsal bones at all — and
    ask how far digit 1's first bone head sits off it, in units of that bone's OWN
    length. A metapodial is displaced by about its own length; a phalanx sits on the
    line. Scale-free, so it reads the same on a 12-year-old and on an adult.
    """
    S = _side(side)
    out = {}
    for part, tbl, keys, ref in (('hand', DIGIT_BONES, FINGERS, 'metacarpal1'), ('foot', TOE_BONES, LESSER_TOES, None)):
        first = {}
        for d in keys:
            b = tbl[d][0] if part == 'foot' else tbl[d][1]
            first[d] = sk['head'][sk['index']['%s.%s' % (b, S)]]
        P = np.array([first[d] for d in keys])
        c = P.mean(0)
        _, _, vt = np.linalg.svd(P - c, full_matrices=False)
        u = vt[0]

        def off(q, c=c, u=u):
            x = np.asarray(q, np.float64) - c
            return float(np.linalg.norm(x - float(np.dot(x, u)) * u))

        d1 = 'thumb' if part == 'hand' else 'hallux'
        b1 = tbl[d1][0]  # the digit's FIRST bone, which is what is in question
        j1 = sk['index']['%s.%s' % (b1, S)]
        own = float(np.linalg.norm(sk['tail'][j1] - sk['head'][j1]))
        rec = {
            'bone': b1,
            'off_mp_line_m': off(sk['head'][j1]),
            'own_length_m': own,
            'off_over_own_length': off(sk['head'][j1]) / own if own > 0 else None,
        }
        if ref:
            rec['reference_metapodial'] = ref
            rec['reference_off_mp_line_m'] = off(sk['head'][sk['index']['%s.%s' % (ref, S)]])
            rec['gap_to_reference_metapodial_m'] = float(
                np.linalg.norm(sk['head'][j1] - sk['head'][sk['index']['%s.%s' % (ref, S)]])
            )
        else:
            rec['reference_proximal_carrier'] = FOOT_BONE
            rec['carrier_tail_off_mp_line_m'] = off(sk['tail'][sk['index']['%s.%s' % (FOOT_BONE, S)]])
        # THE VERDICT IS AN ORDERING, NOT A CUT POINT: digit 1's first bone is a
        # metapodial iff its head is closer to the other metapodials' heads than to the
        # MP joint line it would sit on as a phalanx.
        if ref:
            rec['verdict'] = 'metapodial' if rec['gap_to_reference_metapodial_m'] < rec['off_mp_line_m'] else 'phalanx'
        else:
            rec['verdict'] = (
                'metapodial' if rec['off_mp_line_m'] > 0.5 * rec['carrier_tail_off_mp_line_m'] else 'phalanx'
            )
        out[part] = rec
    return out


def chain_continuity(sk, side='L'):
    """Every joint in a digit chain: does one bone's TAIL land on the next bone's HEAD?

    A chain with a gap is not a chain, and a rig can name three phalanges that do not
    articulate. This extends verify_rig()'s base-to-proximal check through the whole
    chain and onto the foot.

    GATED IN REST SPACE, REPORTED IN BOTH. Continuity is a property of the rest
    skeleton — a pose is a rigid transform per bone and cannot open or close a joint —
    and in rest space the gaps are EXACTLY zero, which is what lets verify_rig() use a
    1e-6 mm tolerance honestly. The posed figure is carried beside it and is not gated
    because reconstructing a posed head costs a 4x4 inverse per bone, and that inverse
    contributes about 3e-6 mm of float64 round-off on metre-scale coordinates: gating
    the posed number at 1e-6 mm would fail every character on arithmetic noise, which is
    a defect in the probe and not in the rig.
    """
    S = _side(side)
    rows = []
    for part, tbl in (('hand', DIGIT_BONES), ('foot', TOE_BONES)):
        for d, bones in tbl.items():
            ch = [b for b in bones if b]
            for a, b in zip(ch[:-1], ch[1:]):
                ja, jb = sk['index']['%s.%s' % (a, S)], sk['index']['%s.%s' % (b, S)]
                rows.append(
                    {
                        'part': part,
                        'digit': d,
                        'from': a,
                        'to': b,
                        'gap_mm': float(np.linalg.norm(sk['rest_tail'][ja] - sk['rest_head'][jb])) * 1000.0,
                        'posed_gap_mm': float(np.linalg.norm(sk['tail'][ja] - sk['head'][jb])) * 1000.0,
                    }
                )
    return rows


def surface_support(side='L'):
    """Cage vertices each phalanx bone OWNS outright (rig weight > 0.5).

    A rig can name a bone the SKIN does not represent, and then a phalanx count is a
    statement about a text file rather than about the mesh we ship. The test has no
    tunable: a segment with ZERO majority-owned vertices has no surface of its own, full
    stop. Measured on the neutral, this is not hypothetical — toe5-2 owns 0.
    """
    S = _side(side)
    rows = []
    for part, tbl in (('hand', DIGIT_BONES), ('foot', TOE_BONES)):
        for d, bones in tbl.items():
            ch = [b for b in bones if b]
            phal = ch[1:] if part == 'hand' else ch
            for b in phal:
                w = _bone_weight('%s.%s' % (b, S))
                rows.append(
                    {
                        'part': part,
                        'digit': d,
                        'bone': b,
                        'n_majority': int((w > SEGMENT_W_MIN).sum()),
                        'n_blended': int((w > RING_W_MIN).sum()),
                    }
                )
    return rows


def measure_digit_chains(phenotype, local_changes=None, bone_scales=None, side='L', params=None):
    """Raw census for t5_digit_chains. No thresholds applied."""
    S = _side(side)
    sk = skeleton(phenotype, local_changes, bone_scales, params=params)
    R = digit_roster()
    mp = metapodial_test(sk, S)
    counts = {}

    fingers = {k: v for k, v in R['finger_bones'].items() if k[1] == S}
    toes = {k: v for k, v in R['toe_bones'].items() if k[1] == S}
    counts['digits_per_hand'] = len(fingers)
    counts['digits_per_foot'] = len(toes)
    counts['phalanges_thumb'] = len(fingers.get(('1', S), [])) - (1 if mp['hand']['verdict'] == 'metapodial' else 0)
    per_finger = sorted({len(v) for k, v in fingers.items() if k[0] != '1'})
    counts['phalanges_per_finger'] = per_finger[0] if len(per_finger) == 1 else per_finger
    counts['metacarpals_per_hand'] = len(R['metacarpal_bones'].get(S, [])) + (
        1 if mp['hand']['verdict'] == 'metapodial' else 0
    )
    counts['phalanges_per_hand'] = counts['phalanges_thumb'] + sum(len(v) for k, v in fingers.items() if k[0] != '1')
    counts['phalanges_hallux'] = len(toes.get(('1', S), [])) - (1 if mp['foot']['verdict'] == 'metapodial' else 0)
    per_toe = sorted({len(v) for k, v in toes.items() if k[0] != '1'})
    counts['phalanges_per_lesser_toe'] = per_toe[0] if len(per_toe) == 1 else per_toe
    counts['phalanges_per_foot'] = counts['phalanges_hallux'] + sum(len(v) for k, v in toes.items() if k[0] != '1')
    counts['metatarsals_per_foot'] = None  # no metatarsal bone on this rig
    counts['cuneiforms_per_foot'] = None  # no tarsal bone on this rig
    counts['carpals_per_hand'] = None  # `wrist` is one bone, not eight

    degenerate = []
    for part, tbl in (('hand', DIGIT_BONES), ('foot', TOE_BONES)):
        for d, bones in tbl.items():
            for b in [x for x in bones if x]:
                L = _blen(sk, b, S)
                if L <= 0:
                    degenerate.append({'part': part, 'digit': d, 'bone': b, 'length_m': L})
    return {
        'side': S,
        'counts': counts,
        'roster': R,
        'metapodial_test': mp,
        'chain_gaps_mm': chain_continuity(sk, S),
        'surface_support': surface_support(S),
        'degenerate_bones': degenerate,
        'pose_note': {
            'max_bone_length_change_mm': sk['max_length_change_mm'],
            'pose_is_identity': sk['pose_is_identity'],
        },
    }


def check_digit_chains(phenotype, local_changes=None, bone_scales=None, side='L', params=None):
    m = measure_digit_chains(phenotype, local_changes, bone_scales, side, params)
    c = m['counts']
    fails, notes, unresolved = [], [], []
    for key, want, answerable in SKELETAL_COUNTS:
        got = c.get(key)
        if not answerable or got is None:
            unresolved.append(key)
            continue
        if got != want:
            fails.append({'count': key, 'expected': want, 'measured': got})
    gap = max((r['gap_mm'] for r in m['chain_gaps_mm']), default=0.0)
    posed_gap = max((r['posed_gap_mm'] for r in m['chain_gaps_mm']), default=0.0)
    if gap > 1e-6:
        fails.append(
            {
                'count': 'chain_continuity',
                'expected': 0.0,
                'measured': gap,
                'unit': 'mm (largest rest-space tail-to-head gap)',
            }
        )
    if m['degenerate_bones']:
        fails.append(
            {
                'count': 'nonzero_bone_length',
                'expected': 'every named phalanx has length > 0',
                'measured': m['degenerate_bones'],
            }
        )
    unsupported = [r for r in m['surface_support'] if r['n_majority'] == 0]
    if unsupported:
        fails.append(
            {
                'count': 'surface_resolvable',
                'expected': 'every named phalanx owns >= 1 cage vertex outright',
                'measured': ['%s/%s (%d blended)' % (r['digit'], r['bone'], r['n_blended']) for r in unsupported],
            }
        )
    status = FAIL if fails else PASS
    return _rec(
        'digit_chains',
        'rig',
        status,
        len(fails),
        'count of failed integer assertions',
        'the thumb carries 2 phalanges and the fingers 3, the hallux 2 and the lesser '
        'toes 3, giving 14 phalanges per hand and 14 per foot, on 5 metacarpals and 5 '
        'metatarsals (AFS p.179, p.188). These are integers: there is no tolerance to '
        "set and nothing that could be tuned to make our rig pass. Whether anny's "
        'digit-1 first bone is a metapodial or a phalanx is not assumed from the '
        'numbering — it is measured (metapodial_test), and the answer differs between '
        'the hand and the foot on this rig.',
        band=None,
        threshold=0,
        provenance=CANON,
        severity='block',
        severity_why=(
            'integers. There is no rejection rate to estimate and no width to '
            'widen: a hand either has fourteen phalanges or it does not. CANON '
            'does not cap this one at report: the cap exists so a book cannot '
            'overrule a survey, and NO SURVEY COUNTS PHALANGES — none of these '
            'quantities is in geom.anthro.gates.MEASURED_COVERED_QUANTITIES, '
            'so there is nothing here for the book to overrule. The subject is '
            'also our own bone roster rather than a proportion of a person.'
        ),
        source='integer skeletal counts, AFS p.179 and p.188; verified against the rig '
        "roster parsed from anny's own 163 bone names",
        provenance_note=(
            'RE-TAGGED 2026-08-06, MEASURED -> CANON, to match the gate registry entry '
            'for t5_digit_chains, which was re-tagged first and left this module '
            'contradicting it. The only citation behind these counts is two pages of a '
            'book, and a page is CANON however right it is; MEASURED is reserved for a '
            'named survey of real people with a sample size. NOTHING ABOUT THE CHECK '
            'CHANGED: the assertions, the threshold of 0 and the block severity are '
            'byte-identical, and every anny body still FAILS this predicate. The tag was '
            'the only thing that was wrong, and it was wrong in the flattering '
            'direction — MEASURED outranks CANON, so the file was claiming survey '
            'evidence for a book number.'
        ),
        failed=fails,
        counts=c,
        unresolved_counts=unresolved,
        metapodial_test=m['metapodial_test'],
        max_chain_gap_mm=gap,
        max_posed_chain_gap_mm=posed_gap,
        surface_support=m['surface_support'],
        subchecks={
            'integer_counts': (
                PASS if not [f for f in fails if f['count'] in {k for k, _w, _a in SKELETAL_COUNTS}] else FAIL
            ),
            'chain_continuity': (PASS if gap <= 1e-6 else FAIL),
            'nonzero_bone_length': (PASS if not m['degenerate_bones'] else FAIL),
            'surface_resolvable': (PASS if not unsupported else FAIL),
        },
        pose_note=m['pose_note'],
        notes=notes,
    )


# ---------------------------------------------------------------------------------
# t5_phalanx_ratio
# ---------------------------------------------------------------------------------
def measure_phalanx_ratio(phenotype, local_changes=None, bone_scales=None, side='L', v=None, faces=None, params=None):
    """Segment lengths and ratios for every digit of one hand and one foot.

    Three readings of the same anatomy, kept apart on purpose:
      rig      — |tail - head| through the delivered pose. The gated one, because it is
                 the convention both external surveys measured in.
      fraction — each interphalangeal joint's position as a fraction of the whole
                 MCP-to-fingertip length. Convention-free: it does not matter whether
                 "tip" means bone or pulp as long as the same total is used on both
                 sides, so it is the sharpest form of the comparison.
      mesh     — the same lengths from resolve_hand's ring centroids. Reported, never
                 gated: the ring centroid sits 3.2-8.3 mm from the rig joint, which is
                 a quarter of a 25 mm segment, so this estimator cannot resolve a ratio.
    """
    S = _side(side)
    sk = skeleton(phenotype, local_changes, bone_scales, params=params)
    out = {
        'side': S,
        'hand': {},
        'foot': {},
        'mesh': None,
        'pose_note': {'max_bone_length_change_mm': sk['max_length_change_mm']},
    }
    for d, bones in DIGIT_BONES.items():
        ch = [b for b in bones[1:] if b]
        L = [_blen(sk, b, S) for b in ch]
        tot = float(sum(L))
        rec = {'bones': ch, 'lengths_m': L, 'total_m': tot}
        if len(L) == 3:
            rec['mid_over_prox'] = L[1] / L[0]
            rec['dist_over_mid'] = L[2] / L[1]
            rec['pip_fraction'] = L[0] / tot
            rec['dip_fraction'] = (L[0] + L[1]) / tot
        else:
            rec['dist_over_prox'] = L[1] / L[0]
            rec['ip_fraction'] = L[0] / tot
        out['hand'][d] = rec
    for d, bones in TOE_BONES.items():
        ch = [b for b in bones if b]
        L = [_blen(sk, b, S) for b in ch]
        tot = float(sum(L))
        rec = {'bones': ch, 'lengths_m': L, 'total_m': tot}
        if len(L) == 3:
            rec['mid_over_prox'] = L[1] / L[0]
            rec['dist_over_mid'] = L[2] / L[1]
            rec['pip_fraction'] = L[0] / tot
            rec['dip_fraction'] = (L[0] + L[1]) / tot
        else:
            rec['dist_over_prox'] = L[1] / L[0]
            rec['ip_fraction'] = L[0] / tot
        out['foot'][d] = rec
    if v is not None and faces is not None:
        F = resolve_hand(v, faces, S)
        J, mesh = F['joints'], {}
        for d, bones in DIGIT_BONES.items():
            keys = ['mcp', 'pip', 'dip', 'tip'] if bones[3] else ['mcp', 'pip', 'tip']
            P = [J[(d, k)] for k in keys]
            L = [float(np.linalg.norm(b - a)) for a, b in zip(P[:-1], P[1:])]
            r = {'lengths_m': L}
            if len(L) == 3:
                r['mid_over_prox'] = L[1] / L[0]
                r['dist_over_mid'] = L[2] / L[1]
            else:
                r['dist_over_prox'] = L[1] / L[0]
            mesh[d] = r
        out['mesh'] = mesh
    return out


def check_phalanx_ratio(phenotype, local_changes=None, bone_scales=None, side='L', v=None, faces=None, params=None):
    m = measure_phalanx_ratio(phenotype, local_changes, bone_scales, side, v, faces, params)
    per, fails, z_all = {}, [], []
    for d in FINGERS:
        r = m['hand'][d]
        row = {}
        for kind in ('mid_over_prox', 'dist_over_mid'):
            ref = _ratio_band(d, kind)
            x = r[kind]
            lo, hi = ref['band']
            st = FAIL if (x < lo or x > hi) else PASS
            z = (x - ref['centre']) / ref['sd_propagated']
            row[kind] = {'measured': x, 'status': st, 'z_conservative': z, **ref}
            if kind == 'mid_over_prox':
                z_all.append(z)
            if st == FAIL:
                fails.append('%s.%s' % (d, kind))
        row['ordering_proximal_longer_than_middle'] = bool(r['mid_over_prox'] < 1.0)
        if not row['ordering_proximal_longer_than_middle']:
            fails.append('%s.ordering' % d)
        per[d] = row
    # THE SHARP STATEMENT, and it needs no error model at all: where the two
    # interphalangeal joints sit along the finger, as a fraction of its whole length.
    # The two surveys' disagreement with EACH OTHER is the honest scale of uncertainty;
    # the rig's disagreement with both is measured against it.
    joints = {}
    for d in FINGERS:
        b = BK2010[d]
        bk_tot = b['proximal'][0] + b['middle'][0] + b['distal'][0] + b['tip'][0]
        bk_pip = b['proximal'][0] / bk_tot
        bk_dip = (b['proximal'][0] + b['middle'][0]) / bk_tot
        p, mm, dd = HD2002[d]
        hd_tot = p + mm + dd
        joints[d] = {
            'rig_pip_fraction': m['hand'][d]['pip_fraction'],
            'rig_dip_fraction': m['hand'][d]['dip_fraction'],
            'bk2010_pip_fraction': bk_pip,
            'bk2010_dip_fraction': bk_dip,
            'hd2002_pip_fraction': p / hd_tot,
            'hd2002_dip_fraction': (p + mm) / hd_tot,
            'canon_afs_p178_pip_fraction': AFS_P178_PARTS[0] / sum(AFS_P178_PARTS),
            'canon_afs_p178_dip_fraction': ((AFS_P178_PARTS[0] + AFS_P178_PARTS[1]) / sum(AFS_P178_PARTS)),
            'between_source_spread_pip': abs(bk_pip - p / hd_tot),
            'rig_minus_sources_pip': (m['hand'][d]['pip_fraction'] - 0.5 * (bk_pip + p / hd_tot)),
        }
    sign = 'above' if all(z > 0 for z in z_all) else ('below' if all(z < 0 for z in z_all) else 'mixed')
    status = FAIL if fails else PASS
    worst = max((abs(z) for z in z_all), default=0.0)
    return _rec(
        'phalanx_ratio',
        'rig',
        status,
        worst,
        'largest |z| of mid/prox against the survey mean, in conservative SD',
        'the middle phalanx is about 0.56 of the proximal one and the DIP-to-tip '
        'segment about 0.77-1.0 of the middle one, in two independent radiographic '
        'series that agree with each other to %.3f. The band is 3 conservative SD wide '
        'and comes only from those series. All four fingers here sit %s the survey '
        'mean.' % (max(abs(joints[d]['between_source_spread_pip']) for d in FINGERS), sign),
        band=None,
        threshold=None,
        provenance=MEASURED,
        severity='block',
        severity_why=(
            'the band is MEASURED and external, and the house 1%-rejection '
            'ceiling is a rule about REAL bodies, not about our cage. Our own '
            'morph sample may not be used to widen it: rule 3 of the build '
            'brief says a mesh that fails an external band is a finding, not '
            'a reason to move the band.'
        ),
        source='%s AND %s' % (BK2010_SOURCE, HD2002_SOURCE),
        fingers=per,
        failed=fails,
        sign_agreement=sign,
        joint_fractions=joints,
        thumb={
            'dist_over_prox': m['hand']['thumb']['dist_over_prox'],
            'bk2010_dist_over_prox': (
                (BK2010['thumb']['distal'][0] + BK2010['thumb']['tip'][0]) / BK2010['thumb']['proximal'][0]
            ),
            'note': 'reported, not gated: HD2002 publishes no thumb ratio, so this '
            'quantity has one source rather than two.',
        },
        foot={
            d: {
                'mid_over_prox': m['foot'][d].get('mid_over_prox'),
                'dist_over_mid': m['foot'][d].get('dist_over_mid'),
                'dist_over_prox': m['foot'][d].get('dist_over_prox'),
            }
            for d in TOES
        },
        foot_status=UNMEASURABLE,
        foot_why=DIGIT_UNRESOLVED_FOOT_RATIO,
        canon=AFS_P178_SOURCE,
        canon_severity_cap='report',
        canon_cap_why=(
            'AFS p.178 is CANON and a MEASURED source exists for this exact '
            'quantity, so the book may not block. It is evaluated and '
            'reported beside the survey band.'
        ),
        mesh_cross_read=m['mesh'],
        pose_note=m['pose_note'],
    )
