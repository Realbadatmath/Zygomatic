# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""THE TABLE — the landmark spec and the resolver that walks it."""

from zyg_workflows.geom.anthro.landmarks.constants import (
    CAGE_VERTS,
    _CACHE,
    _anny_waist_ring,
    _axis_probe,
    _coco,
    _support,
    _support_core,
    np,
)
from zyg_workflows.geom.anthro.landmarks.resolvers import _RESOLVERS, _context, _mirror

# ---------------------------------------------------------------------------------
# THE TABLE
# ---------------------------------------------------------------------------------
# ref: the ANSUR key in REFERENCE_FRACTIONS this landmark may be validated against, or
#      None when no public survey measures it.
# sides: () for a midline landmark, ('l','r') to emit <name>_l and <name>_r.
LANDMARK_SPEC = (
    dict(
        name='vertex',
        how='extreme',
        sides=(),
        ref=None,
        anchor='geometry: maximum z',
        anchor_kind='iso',
        confidence='high',
        args=dict(axis='z', sign=+1, region={}),
        note='ISO 7250-1 vertex. Stature is measured to it. The cage is bald, so this '
        'is the skull crown with no hair offset.',
    ),
    dict(
        name='menton',
        how='support_extreme',
        sides=(),
        ref=None,
        anchor='makehuman:chin-prominent-incr, inferior extremum near the midline',
        anchor_kind='derived',
        confidence='medium',
        args=dict(label='chin-prominent-incr', axis='z', sign=-1, region={'xabs': (0.0, 0.025)}),
        note='Resolvable, and here is exactly how: the chin target displaces a patch '
        'whose lowest near-midline vertex carries an outward normal of '
        '(0.01,-0.16,-0.99) — pointing straight down, which is the geometric '
        'signature of menton. The midsagittal anterior profile confirms it: the '
        'surface jumps from y=-155.0mm at 0.850 of stature to -196.9mm at 0.860, '
        'i.e. the chin overhangs the submental region and this is its inferior '
        'limit. WARNING: menton-to-vertex head height is in NO public survey — '
        'ANSUR has head LENGTH and tragion-to-top-of-head but no head height — so '
        'any "heads tall" figure derived from this landmark is a HOUSE constant '
        'and must never be cited to a survey.',
    ),
    dict(
        name='cervicale',
        how='unresolved',
        sides=(),
        ref='cervicale',
        anchor=None,
        anchor_kind='derived',
        confidence='unresolved',
        args={},
        note='UNRESOLVED. This cage has no vertebra prominens: the posterior midline '
        'y(z) profile from 0.76 to 0.92 of stature is monotone with no local '
        'posterior maximum (measured -1.0mm at 0.765 rising smoothly to -51.9mm '
        'at 0.885). Three surface operationalisations were tried and they '
        'disagree by 0.036 of stature (66mm on the 1.85m male): steepest nuchal '
        'slope 0.828, coronal neck-breadth minimum 0.872, breadth-plateau onset '
        'at 1.05x the minimum 0.868. Selecting whichever hits ANSUR 0.8639 would '
        'be fitting the answer to the target. If a cervicale height is needed, '
        'apply CERVICALE_OVER_SUPRASTERNALE (MEASURED from ANSUR: male 0.0448 '
        '+/-0.0065, female 0.0405 +/-0.0071 of stature) to the resolved '
        'suprasternale and label the result HOUSE, not measured. See '
        'neck_breadth_min for the honest geometric feature nearby.',
    ),
    dict(
        name='neck_breadth_min',
        how='coronal_min',
        sides=('l', 'r'),
        ref=None,
        anchor='geometry: minimum of the coronal half-breadth profile over 0.80-0.92',
        anchor_kind='derived',
        confidence='high',
        args=dict(fz=(0.80, 0.92), xabs_max=0.12),
        note='A well-defined geometric extremum (the narrowest coronal section of the '
        'neck), shipped under its own name precisely so nobody calls it '
        'cervicale. Smoothing-window sensitivity measured across five meshes: '
        'the minimum moves by at most 0.006 of stature between a +/-0.008 and a '
        '+/-0.018 window.',
    ),
    dict(
        name='suprasternale',
        how='suprasternale',
        sides=(),
        ref='suprasternale',
        anchor='geometry: least-anterior point of the anterior midsagittal strip',
        anchor_kind='iso',
        confidence='high',
        args=dict(fz=(0.74, 0.855)),
        note='ISO 7250-1 suprasternale (jugular notch), resolved by its own definition '
        'rather than by proxy. The 0.74-0.855 search window is HOUSE: it must '
        'exclude the chin above and the sternal body below.',
    ),
    dict(
        name='acromion',
        how='acromion',
        sides=('l', 'r'),
        ref='acromion',
        anchor='geometry: superior surface in a 0.015-stature coronal slab through the anny COCO glenohumeral centre',
        anchor_kind='derived',
        confidence='medium',
        args=dict(slab=0.015),
        note='Skin over the acromion, not the bony landmark; expect a small positive '
        'bias. Slab width sensitivity measured: 0.010 vs 0.020 of stature moves '
        'the adult results by <0.001 of stature. THE HEIGHT IS USABLE, THE X IS '
        "NOT: doubling this landmark's x gives 279.6mm on the stock anny body, "
        '416.8mm on the male original and 361.1mm on the female against ANSUR '
        'biacromial means of 399 / 438 / 377mm for those statures — 5% narrow on '
        'the issued adults and 30% narrow on the stock body. Biacromial breadth '
        'correlates only r=0.53 with stature and must be gated wide and measured '
        'directly, never read off a height landmark.',
    ),
    dict(
        name='thelion',
        how='support',
        sides=('l', 'r'),
        ref='thelion',
        anchor='makehuman:nipple-size-incr (probed at the FEMALE reference)',
        anchor_kind='makehuman',
        confidence='medium',
        args=dict(label='nipple-size-incr', ref='female', region={}),
        note='nipple-size-incr displaces exactly 0 vertices at gender=0.0 and 32 at '
        'gender=1.0 (measured), so the SUPPORT is probed at the female reference. '
        'The 32 vertices it names are the areolar patch of the cage, which exists '
        'on every body regardless of gender axis, so the landmark resolves on '
        'male-typed meshes too. Compared against ANSUR chestheight, which is the '
        'bustpoint level.',
    ),
    dict(
        name='bust_ring',
        how='support',
        sides=(),
        ref=None,
        anchor='makehuman:measure-bust-circ-incr (the full ring)',
        anchor_kind='makehuman',
        confidence='high',
        args=dict(label='measure-bust-circ-incr'),
        note="MakeHuman's own bust girth ring — a RING, not a point; the reported "
        'point is its displacement-weighted centroid. Girth taken around it must '
        'use a plane slice plus convex hull, not the chord sum anny uses.',
    ),
    dict(
        name='tenth_rib',
        how='unresolved',
        sides=(),
        ref='tenth_rib',
        anchor=None,
        anchor_kind='derived',
        confidence='unresolved',
        args={},
        note='UNRESOLVED. The tenth rib is palpated, not seen: this cage has no costal '
        'margin, and no MakeHuman target names it. The nearest shipped ring, '
        'measure-underbust-circ-incr, sits at 0.700 of stature against ANSUR '
        'tenth rib 0.6380 — 0.062 of stature (115mm on the 1.85m male) too high, '
        'so it is not a substitute. This matters because the WHO natural-waist '
        'site is the rib-iliac midpoint; without tenth rib and iliocristale this '
        'cage cannot produce a WHO waist at all, only the NIH/omphalion site.',
    ),
    dict(
        name='omphalion',
        how='support',
        sides=(),
        ref='omphalion',
        anchor='makehuman:stomach-navel-out',
        anchor_kind='makehuman',
        confidence='high',
        args=dict(label='stomach-navel-out'),
        note='A 19-vertex navel patch — the tightest anchor on the cage. Measured on '
        'the anny neutral at 0.5995 of stature against ANSUR omphalion 0.6014.',
    ),
    dict(
        name='waist_ring_anny',
        how='ring_const',
        sides=(),
        ref='omphalion',
        anchor='anny.anthropometry:BASE_MESH_WAIST_VERTICES (46 vertices)',
        anchor_kind='makehuman',
        confidence='high',
        args={},
        note="The vendor's own waist ring, remapped through base_mesh_vertex_indices. "
        'Measured on the anny neutral at 0.5977-0.6185 of stature, mean 0.6039 — '
        'i.e. anny\'s "waist" is the OMPHALION site, not the WHO rib-iliac site. '
        'anny measures it as a chord sum (an inscribed polyline) which is shorter '
        'than a taut tape; use plane-slice + convex hull instead.',
    ),
    dict(
        name='waist_coronal_min',
        how='coronal_min',
        sides=('l', 'r'),
        ref=None,
        anchor='geometry: minimum of the coronal half-breadth profile over 0.52-0.70',
        anchor_kind='derived',
        confidence='high',
        args=dict(fz=(0.52, 0.70), y=(-0.16, 0.06), xabs_max=0.115),
        note='The narrowest coronal section of the torso. This is NOT a survey waist '
        'site — neither WHO rib-iliac nor NIH iliac-crest nor omphalion define '
        'the waist as the narrowest section, and on many real bodies no such '
        'minimum exists. Shipped as geometry under a geometric name. It is also '
        'the least stable landmark here: measured across five meshes it lands '
        'anywhere from 0.60 to 0.70 of stature, and the smoothing window moves it '
        'by up to 0.016 of stature. Treat it as a shape descriptor, never as a '
        'measurement site.',
    ),
    dict(
        name='iliocristale',
        how='unresolved',
        sides=('l', 'r'),
        ref='iliocristale',
        anchor=None,
        anchor_kind='derived',
        confidence='unresolved',
        args={},
        note='UNRESOLVED. No iliac crest on this cage: the lateral half-breadth profile '
        'of the male original falls monotonically from 181.4mm at 0.50 of stature '
        'to a waist minimum at 0.61 with no intervening crest bulge, so there is '
        'nothing to find. Do not substitute the hip ring — that is trochanteric, '
        '0.09 of stature lower.',
    ),
    dict(
        name='trochanterion',
        how='trochanterion',
        sides=('l', 'r'),
        ref='trochanterion',
        anchor='geometry: lateral-most surface point at the anny COCO femoral-head centre height',
        anchor_kind='derived',
        confidence='medium',
        args=dict(band=0.012),
        note='Height comes from the joint centre, only the lateral projection from the '
        'surface. Pure surface search fails here: the widest lateral point of the '
        'pelvis-and-thigh region sits at 0.43 of stature, 0.08 BELOW ANSUR '
        'trochanterion, because the outer thigh is wider than the hip on this '
        'cage.',
    ),
    dict(
        name='hip_ring',
        how='support_core',
        sides=(),
        ref=None,
        anchor='makehuman:measure-hips-circ-incr, 0.8 core',
        anchor_kind='makehuman',
        confidence='high',
        args=dict(core_label='measure-hips-circ-incr', core=0.8),
        note='The plain support of this target is 13,716 of 13,718 vertices because it '
        'translates everything below the hips; only the 0.8 displacement core '
        '(102 vertices, 0.475-0.536 of stature on the neutral) is a ring.',
    ),
    dict(
        name='buttock',
        how='extreme',
        sides=(),
        ref='buttock',
        anchor='geometry: maximum posterior projection over 0.42-0.60 of stature',
        anchor_kind='iso',
        confidence='medium',
        args=dict(axis='y', sign=+1, region={'fz': (0.42, 0.60)}),
        note='ANSUR buttock height is the height of the maximum posterior protrusion, '
        'which is what this resolves. Sanity check that holds on every mesh '
        'tested: this vertex is also the global maximum y of the whole body.',
    ),
    dict(
        name='crotch',
        how='extreme',
        sides=(),
        ref='crotch',
        anchor='geometry: minimum z of the midsagittal strip over 0.35-0.60 of stature',
        anchor_kind='iso',
        confidence='high',
        args=dict(axis='z', sign=-1, region={'fz': (0.35, 0.60), 'xabs': (0.0, 0.003)}),
        note='The perineal saddle point. Stable to the midline half-width: 0.002 and '
        '0.005 of stature give the same vertex. ANSUR crotch height is taken with '
        'a bar pressed up into the crotch, which compresses tissue and reads '
        'HIGH; a free-surface value slightly below the survey mean is expected.',
    ),
    dict(
        name='stylion',
        how='unresolved',
        sides=('l', 'r'),
        ref='stylion',
        anchor=None,
        anchor_kind='derived',
        confidence='unresolved',
        args={},
        note='UNRESOLVED. The radial styloid has no surface signature on this cage, and '
        'ANSUR wrist height (0.4825 of stature) is a STANDING-POSTURE height that '
        'an A-posed mesh cannot produce in any case — the wrist ring here sits at '
        '0.608 of stature on the neutral. Use wrist_ring for the girth site and '
        'acromion-to-wrist chord for a pose-invariant arm length.',
    ),
    dict(
        name='wrist_ring',
        how='support',
        sides=('l', 'r'),
        ref=None,
        anchor='makehuman:measure-wrist-circ-incr',
        anchor_kind='makehuman',
        confidence='high',
        args=dict(label='measure-wrist-circ-incr', region={}),
        note="MakeHuman's own wrist girth ring. HEIGHT IS A POSE COORDINATE (A-pose) "
        'and is not comparable to ANSUR wrist height.',
    ),
    dict(
        name='dactylion',
        how='dactylion',
        sides=('l', 'r'),
        ref=None,
        anchor='geometry: hand vertex furthest from the wrist ring centroid',
        anchor_kind='derived',
        confidence='high',
        args={},
        note='Fingertip. HEIGHT IS A POSE COORDINATE. The wrist_ring-to-tip chord IS '
        'pose-invariant: measured 216.6mm (0.117 of stature) on the male original '
        'and 191.6mm (0.114) on the female, against ANSUR hand-length means of '
        '0.1101 and 0.1112 of stature. Part of that excess is definitional — the '
        'ring centroid sits proximal to the stylion line where hand length starts '
        '— so read it as "anny hands run long by a few percent", not as a '
        'calibrated hand length.',
    ),
    dict(
        name='patella_mid',
        how='unresolved',
        sides=('l', 'r'),
        ref='patella_mid',
        anchor=None,
        anchor_kind='derived',
        confidence='unresolved',
        args={},
        note='UNRESOLVED. No patellar bulge on this cage: the anterior profile of the '
        'lower limb rises monotonically through the knee, so there is no local '
        'anterior maximum to call mid-patella. knee_ring is the usable knee level '
        'and it sits ABOVE mid-patella by roughly 0.013 of stature (measured '
        '0.2912 on the male against ANSUR 0.2780) — a systematic offset, not a '
        'substitute.',
    ),
    dict(
        name='knee_ring',
        how='support',
        sides=('l', 'r'),
        ref=None,
        anchor='makehuman:measure-knee-circ-incr',
        anchor_kind='makehuman',
        confidence='high',
        args=dict(label='measure-knee-circ-incr', region={}),
        note="MakeHuman's own knee girth ring; the reported point is its displacement-weighted centroid.",
    ),
    dict(
        name='tibiale',
        how='support_extreme',
        sides=('l', 'r'),
        ref='tibiale',
        anchor='makehuman:measure-lowerleg-height-incr, proximal support boundary (thresh 1e-4)',
        anchor_kind='makehuman',
        confidence='medium',
        args=dict(label='measure-lowerleg-height-incr', axis='z', sign=+1, thresh=1e-4, region={}),
        note='A segment-length target does not move the joint it pivots about, so the '
        'proximal edge of its support IS the knee joint line. Measured on the '
        'anny neutral at 0.2666 of stature against ANSUR tibiale 0.2665. '
        'THRESHOLD SENSITIVE, which is why confidence is medium: the boundary '
        'reads 0.2666 at 1e-4, 0.2615 at 3e-4 and 0.2437 at 3e-3 — 0.023 of '
        'stature (42mm) of spread across the cut. 1e-4 is a HOUSE choice, taken '
        'as the lowest cut that is still clear of float noise.',
    ),
    dict(
        name='ankle_ring',
        how='support',
        sides=('l', 'r'),
        ref=None,
        anchor='makehuman:measure-ankle-circ-incr',
        anchor_kind='makehuman',
        confidence='high',
        args=dict(label='measure-ankle-circ-incr', region={}),
        note='The minimum-girth ankle ring. It legitimately sits ABOVE the malleoli '
        '(measured 0.0561 of stature on the male against ANSUR lateral malleolus '
        '0.0415) — that is the definition, not an error.',
    ),
    dict(
        name='malleolus_lat',
        how='unresolved',
        sides=('l', 'r'),
        ref='malleolus_lat',
        anchor=None,
        anchor_kind='derived',
        confidence='unresolved',
        args={},
        note='UNRESOLVED. The ankle tapers smoothly with no malleolar prominence: the '
        'lateral profile of the male original runs 256.3mm at 0.015 of stature '
        'down to 245.9mm at 0.050 with no local maximum anywhere near the ANSUR '
        'malleolus height of 0.0415. Any number produced here would be invented.',
    ),
    dict(
        name='pternion',
        how='support_extreme',
        sides=('l', 'r'),
        ref=None,
        anchor='makehuman:l/r-foot-scale-incr, maximum posterior',
        anchor_kind='derived',
        confidence='high',
        args=dict(label='l-foot-scale-incr', axis='y', sign=+1, region={'fz': (0.0, 0.07)}),
        note='Heel, the most posterior point of the foot. The 0.07-of-stature ceiling '
        'is load-bearing, not decoration: the foot-scale support reaches 0.153 of '
        'stature up the shank, and on the female original the unbounded posterior '
        'maximum landed on the CALF at 0.1665 of stature instead of the heel at '
        '0.019. With acropodion it gives foot length: measured 288.6mm on the '
        '1.85m male, 0.156 of stature against an ANSUR male mean of 0.154.',
    ),
    dict(
        name='acropodion',
        how='support_extreme',
        sides=('l', 'r'),
        ref=None,
        anchor='makehuman:l/r-foot-scale-incr, maximum anterior',
        anchor_kind='derived',
        confidence='high',
        args=dict(label='l-foot-scale-incr', axis='y', sign=-1, region={'fz': (0.0, 0.07)}),
        note='Longest toe tip. Same foot-band ceiling as pternion, for the same reason.',
    ),
)

# Targets that exist per side under an l-/r- name; the spec carries the left one.
_SIDED_LABELS = ('l-foot-scale-incr', 'l-hand-fingers-length-incr')


def _side_args(args, side):
    a = dict(args)
    lab = a.get('label')
    if side == 'r' and lab in _SIDED_LABELS:
        a['label'] = 'r' + lab[1:]
    if side and 'region' in a and 'side' not in a['region']:
        a['region'] = dict(a['region'], side=side)
    return a


def resolve_landmarks(v, faces, phenotype=None, local_changes=None):
    """name -> {vertex_idx, point, height_m, anchor, anchor_kind, confidence, note}.

    height_m is height above the mesh's own standing surface (its minimum z), which is
    the survey convention. frac_stature is that over the z-span. point/height_m are None
    for unresolved landmarks — a None you have to handle is better than a number you
    would have trusted.

    phenotype/local_changes are only needed by the two anchors that read anny's joint
    centres (acromion, trochanterion); without them those fall back to the NEUTRAL
    recipe's joint centres, which is wrong for any other body. Cost of omitting them,
    measured on the issued originals: acromion moves +0.0089 of stature on the male and
    +0.0090 on the female, trochanterion -0.0113 on the female — 16 to 19mm, i.e. more
    than a whole ANSUR standard deviation of acromial height. Pass them.
    """
    ctx = _context(v, faces)
    try:
        ctx['coco'] = _coco(phenotype, local_changes)
    except Exception as e:  # noqa: BLE001
        ctx['coco'] = None
        ctx['coco_error'] = str(e)
    out = {}
    for spec in LANDMARK_SPEC:
        sides = spec['sides'] or (None,)
        for side in sides:
            name = spec['name'] + ('_' + side if side else '')
            fn = _RESOLVERS[spec['how']]
            idx = fn(ctx, side, **_side_args(spec.get('args', {}), side))
            rec = {
                'vertex_idx': [],
                'point': None,
                'height_m': None,
                'frac_stature': None,
                'anchor': spec['anchor'],
                'anchor_kind': spec['anchor_kind'],
                'confidence': spec['confidence'],
                'ansur_key': spec['ref'],
                'note': spec['note'],
            }
            if idx is not None and len(idx):
                idx = np.asarray(idx, np.int64)
                w = _weights(spec, idx)
                p = np.average(ctx['v'][idx], axis=0, weights=w)
                rec['vertex_idx'] = idx.tolist()
                rec['point'] = [float(x) for x in p]
                rec['height_m'] = float(p[2] - ctx['zmin'])
                rec['frac_stature'] = float((p[2] - ctx['zmin']) / ctx['H'])
            elif spec['confidence'] != 'unresolved':
                # A resolver that found nothing where the table promised a landmark is a
                # bug or an out-of-family mesh, and must not be reported as a landmark.
                rec['confidence'] = 'unresolved'
                rec['note'] = (
                    'RESOLVER RETURNED NOTHING on this mesh (table expected %s). ' % spec['confidence']
                ) + spec['note']
            out[name] = rec
    return out


def _weights(spec, idx):
    """Ring landmarks report a displacement-weighted centroid so the reported point sits
    where the target's effect is strongest rather than where the support happens to
    sprawl."""
    a = spec.get('args', {})
    if spec['how'] in ('support', 'support_core') and len(idx) > 1:
        s = (
            _support(a['label'], a.get('thresh', 3e-4), a.get('ref', 'male'))
            if 'label' in a
            else _support_core(a['core_label'], a.get('core', 0.8))
        )
        if s is not None:
            lut = np.zeros(CAGE_VERTS)
            lut[s[0]] = s[1]
            w = lut[idx]
            if w.sum() > 0:
                return w
    return None


def warm_cache():
    """Resolve every topology-fixed anchor once. Supports cost two mesh builds each, so
    this is the whole per-process price of the landmark layer; after it, resolving a mesh
    is pure numpy over 13,718 vertices."""
    for spec in LANDMARK_SPEC:
        for side in spec['sides'] or (None,):
            a = _side_args(spec.get('args', {}), side)
            if 'label' in a:
                _support(a['label'], a.get('thresh', 3e-4), a.get('ref', 'male'))
            if 'core_label' in a:
                _support_core(a['core_label'], a.get('core', 0.8))
    _anny_waist_ring()
    _axis_probe()
    _CACHE['mirror'] = _mirror(None)
    return len(_CACHE)
