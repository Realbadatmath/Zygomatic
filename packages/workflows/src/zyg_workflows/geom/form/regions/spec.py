# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""regions — REGION_SPEC — the authored region table — and REGION_NAMES.

Moved verbatim out of regions.py; see the package __init__ for the full rationale.
"""

# ---------------------------------------------------------------------------------
# THE TABLE
# ---------------------------------------------------------------------------------
# claim:  'landmark'       — the patch is on the named structure
#         'surface_aspect' — the patch is in the right PLACE but the named bone has no
#                            measured signature there; do not read the bone off it
#         None             — unresolved
REGION_SPEC = (
    dict(
        name='acromion',
        how='landmark_ball',
        args=dict(landmark='acromion_l', radius_frac=0.018),
        claim='surface_aspect',
        confidence='medium',
        anchor='geom.anthro.landmarks acromion_l vertex, grown by a 0.018-stature graph geodesic ball',
        anchor_kind='landmark_construction',
        note='landmarks.py resolves acromion as SKIN OVER the acromion from a coronal '
        "slab through anny's COCO glenohumeral centre, at medium confidence, and "
        'warns that its x is not a biacromial semi-breadth. This patch inherits '
        'both caveats. Read it as "the top of the shoulder", which is what A4S and '
        "Gray's call the acromial region, not as the bony acromion.",
    ),
    dict(
        name='deltopectoral_triangle',
        how='support_gap',
        args=dict(label_a='l-upperarm-shoulder-muscle-incr', label_b='torso-muscle-pectoral-incr', radius_frac=0.025),
        claim='surface_aspect',
        confidence='low',
        anchor="the surface between MakeHuman's deltoid (l-upperarm-shoulder-muscle-incr, "
        '158 verts) and pectoral (torso-muscle-pectoral-incr, 211 left verts) '
        'supports, within 0.025 of stature of both',
        anchor_kind='morph_support_gap',
        note='A4S names the deltopectoral triangle one of two clavicular regions that '
        'stay visible whatever the build. The ANCHOR here is definitional — the '
        'triangle IS the gap between deltoid and pectoralis, and MakeHuman names '
        'both muscles — but the cage gives that gap only a handful of vertices and '
        'the reference surface fitted around them has a 4.1-4.4 mm residual '
        '(measured), which is larger than the relief being measured. The place is '
        'right; the measurement through it is not trustworthy, and confidence says '
        'so.',
    ),
    dict(
        name='clavicle_shaft',
        how='feature_search',
        args=dict(
            window=dict(fz=(0.79, 0.865), x=(0.008, 0.115), y=(-0.12, 0.01), normal_y_max=0.2), polarity='protrusion'
        ),
        claim=None,
        confidence='unresolved',
        anchor=None,
        anchor_kind='feature_search',
        note='UNRESOLVED. A4S: "when a person is muscular, shoulder bony landmarks look '
        'like depressions between the muscles, and if the person is lean, they '
        'protrude"; Gray\'s 1918 surface-anatomy chapter calls the clavicle '
        'subcutaneous along its whole length. Neither is testable here: a sweep of '
        "the antero-superior shoulder finds no ridge clearing this cage's own "
        'relief p99. The strongest raised vertices in the window do not form a '
        'sterno-acromial line at all — they form a VERTICAL ridge at x = 0.09 m over '
        'fz 0.79-0.83, which is the trapezius margin. Building a clavicle group out '
        'of them would put a clavicle predicate on the trapezius.',
    ),
    dict(
        name='sternal_end',
        how='feature_search',
        args=dict(
            window=dict(fz=(0.795, 0.85), x=(0.004, 0.040), y=(-0.13, -0.02), normal_y_max=0.0), polarity='protrusion'
        ),
        claim=None,
        confidence='unresolved',
        anchor=None,
        anchor_kind='feature_search',
        note='UNRESOLVED. The sternoclavicular joint flanks the jugular notch and is one '
        'of the most reliably visible bony landmarks on a living neck. On this cage '
        'the notch itself resolves (landmarks.suprasternale, ISO, high confidence) '
        'but the paired sternal ends beside it do not clear the relief p99.',
    ),
    dict(
        name='l_triangle',
        how='feature_search',
        args=dict(
            window=dict(fz=(0.835, 0.885), x=(0.012, 0.075), y=(-0.11, 0.0), normal_y_max=0.3), polarity='depression'
        ),
        claim=None,
        confidence='unresolved',
        anchor=None,
        anchor_kind='feature_search',
        note='UNRESOLVED. The supraclavicular fossa — A4S\'s "L-triangle" — is the second '
        'of the two clavicular regions they say stay visible at any build, and it is '
        'a DEPRESSION, so it is searched as one. It cannot exist without the '
        'clavicle that bounds it below, and the clavicle is not here.',
    ),
    dict(
        name='coracoid',
        how='feature_search',
        args=dict(
            window=dict(fz=(0.775, 0.835), x=(0.045, 0.115), y=(-0.115, -0.02), normal_y_max=-0.1),
            polarity='protrusion',
        ),
        claim=None,
        confidence='unresolved',
        anchor=None,
        anchor_kind='feature_search',
        note='UNRESOLVED, AND EXPECTED TO BE. A4S state the coracoid process cannot be '
        "seen on the surface and can only be palpated; Gray's 1918 agrees. A "
        'landmark that is invisible on a LIVING body cannot honestly be resolved on '
        'a mesh of one, so a null result here is the correct answer rather than a '
        'shortfall of the cage. The search is run and reported anyway, because '
        '"we expected nothing" is not evidence and a measurement is.',
    ),
    dict(
        name='scapular_spine',
        how='feature_search',
        args=dict(
            window=dict(fz=(0.735, 0.825), x=(0.008, 0.110), y=(-0.03, 0.06), normal_y_min=0.15), polarity='protrusion'
        ),
        claim=None,
        confidence='unresolved',
        anchor=None,
        anchor_kind='feature_search',
        note='UNRESOLVED. 139 vertices swept over the posterior shoulder. The strongest '
        'feature is +4.2 mm at contrast 2.7 and it runs VERTICALLY at x = 0.09 m '
        '(the trapezius margin again), not laterally along the line a scapular spine '
        'would take from the medial border to the acromion.',
    ),
    dict(
        name='scapula_medial_border',
        how='feature_search',
        args=dict(
            window=dict(fz=(0.695, 0.800), x=(0.008, 0.070), y=(-0.02, 0.06), normal_y_min=0.25), polarity='protrusion'
        ),
        claim=None,
        confidence='unresolved',
        anchor=None,
        anchor_kind='feature_search',
        note='UNRESOLVED. Same sweep, medial half.',
    ),
    dict(
        name='scapula_inferior_angle',
        how='feature_search',
        args=dict(
            window=dict(fz=(0.670, 0.740), x=(0.012, 0.090), y=(-0.02, 0.06), normal_y_min=0.25), polarity='protrusion'
        ),
        claim=None,
        confidence='unresolved',
        anchor=None,
        anchor_kind='feature_search',
        note='UNRESOLVED, and A4S would predict it: they say the inferior angle "can '
        'rarely be seen on the surface" except on the exceptionally lean. The neutral '
        'is muscle 0.5 / weight 0.5, so absence here is consistent with the anatomy '
        'and is NOT by itself proof the cage lacks a scapula — but nothing in the '
        'morph vocabulary produces one at any setting either, and that is.',
    ),
    dict(
        name='asis',
        how='feature_search',
        args=dict(window=dict(fz=(0.505, 0.640), x=(0.018, 0.100), y=(-0.13, -0.01)), polarity='protrusion'),
        claim=None,
        confidence='unresolved',
        anchor=None,
        anchor_kind='feature_search',
        note='UNRESOLVED. A4S make ASIS, PSIS and greater trochanter the three pelvic '
        'landmarks. None of the three has a surface signature here: landmarks.py '
        'already reports iliocristale unresolved because the lateral half-breadth '
        'profile falls monotonically from 0.50 of stature to the waist minimum with '
        'no crest bulge, and the anterior sweep finds no ASIS above the relief p99 '
        'either. WITHOUT ASIS THERE IS NO PELVIC TILT MEASUREMENT AND NO Q ANGLE on '
        'this cage; a predicate that needs either must be refused, not approximated.',
    ),
    dict(
        name='psis',
        how='feature_search',
        args=dict(
            window=dict(fz=(0.520, 0.615), x=(0.006, 0.060), y=(0.0, 0.06), normal_y_min=0.25), polarity='depression'
        ),
        claim=None,
        confidence='unresolved',
        anchor=None,
        anchor_kind='feature_search',
        note='UNRESOLVED, AND NOT MEASURABLE IN PRINCIPLE HERE. The dimples above the '
        'buttocks are a paired DEPRESSION about 30 mm either side of the midline. The '
        'entire sacral window of this cage holds 23 VERTICES, i.e. roughly one vertex '
        'per 30 mm, so a dimple would be a single vertex. The only depression the '
        'sweep finds sits at x = 3 mm — the midline natal cleft, not a paired dimple. '
        'This is a TESSELLATION limit, not a shape one: no threshold change can '
        'recover a feature the cage has no vertices to carry.',
    ),
    dict(
        name='trochanter',
        how='landmark_ball',
        args=dict(landmark='trochanterion_l', radius_frac=0.018),
        claim='surface_aspect',
        confidence='medium',
        anchor='geom.anthro.landmarks trochanterion_l vertex, grown by a 0.018-stature graph geodesic ball',
        anchor_kind='landmark_construction',
        note='THE PLACE IS RIGHT AND THE BONE IS NOT THERE. landmarks.py takes this '
        'height from anny\'s COCO femoral-head centre precisely because "the greater '
        'trochanter has no surface signature on this cage — the lateral profile '
        'through the pelvis is monotone". So this patch is the lateral hip at '
        'trochanteric level and nothing more. It is still worth having: A4S\'s "the '
        'hips are wider than the butt" is a comparison of two WIDTHS, and a width '
        'needs a patch to be measured over, not a prominence.',
    ),
    dict(
        name='olecranon',
        how='ring_sector',
        args=dict(
            ring_label='measure-lowerarm-length-incr',
            ring_side_label=None,
            axis_to_label='measure-wrist-circ-incr',
            direction='posterior',
            half_deg=45.0,
            band_frac=0.022,
            reach_frac=0.06,
        ),
        claim='surface_aspect',
        confidence='medium',
        anchor='posterior 90-degree sector of the ELBOW JOINT LINE (boundary of the '
        'measure-lowerarm-length-incr support, 20 verts/side at 0.665 of stature), '
        "in the forearm's own frame",
        anchor_kind='joint_line_sector',
        note='The joint line itself is solid — a segment-length morph cannot move the '
        'joint it pivots about, so its support boundary is that joint. What is not '
        'there is the olecranon: measured on the neutral this sector reads -2.07 mm, '
        'a shallow DEPRESSION, where a real elbow carries the most prominent bony '
        'point of the arm. Any predicate about a visible olecranon must be refused '
        'on this cage.',
    ),
    dict(
        name='epicondyle_lat',
        how='ring_sector',
        args=dict(
            ring_label='measure-lowerarm-length-incr',
            ring_side_label=None,
            axis_to_label='measure-wrist-circ-incr',
            direction='lateral',
            half_deg=45.0,
            band_frac=0.022,
            reach_frac=0.06,
        ),
        claim='surface_aspect',
        confidence='medium',
        anchor="lateral 90-degree sector of the elbow joint line, in the forearm's frame",
        anchor_kind='joint_line_sector',
        note='This one DOES read as a protrusion — measured +6.84 mm at contrast 11.5 on '
        "the neutral, far above the cage's relief p99, against +1.11 mm for the "
        'anterior control sector. But what that measures is the elbow FLARING wider '
        'than the arm above and below it, which is where the epicondyles are; it is '
        'not evidence of a modelled epicondyle. claim stays surface_aspect.',
    ),
    dict(
        name='epicondyle_med',
        how='ring_sector',
        args=dict(
            ring_label='measure-lowerarm-length-incr',
            ring_side_label=None,
            axis_to_label='measure-wrist-circ-incr',
            direction='medial',
            half_deg=45.0,
            band_frac=0.022,
            reach_frac=0.06,
        ),
        claim='surface_aspect',
        confidence='medium',
        anchor="medial 90-degree sector of the elbow joint line, in the forearm's frame",
        anchor_kind='joint_line_sector',
        note='Measured +4.53 mm at contrast 2.69, i.e. the medial flare is real but about '
        'a third weaker than the lateral one. THE GEODESIC LEASH IS WHAT MAKES THIS '
        'MEANINGFUL: without it the medial sector reaches across the A-pose gap onto '
        'the ribs and returns 312 vertices and -75.7 mm.',
    ),
    dict(
        name='ulnar_head',
        how='ring_sector',
        args=dict(
            ring_label='measure-wrist-circ-incr',
            ring_side_label=None,
            axis_to_label='l-hand-fingers-length-incr',
            direction='posterior',
            half_deg=40.0,
            band_frac=0.014,
            reach_frac=0.045,
        ),
        claim='surface_aspect',
        confidence='low',
        anchor="postero-ulnar sector of MakeHuman's wrist girth ring (measure-wrist-circ-incr), in the forearm's frame",
        anchor_kind='ring_sector',
        note='The head of the ulna is the bump on the little-finger side of the back of '
        'the wrist and is one of the easiest landmarks to see on a living arm. '
        'Measured here: +2.12 mm at contrast 0.60 against a collar residual of '
        '3.5 mm — i.e. nothing. Consistent with landmarks.py reporting stylion '
        'UNRESOLVED for the radial side. THE SECTOR IS ALSO ONLY APPROXIMATELY '
        "ULNAR: the cage's forearm carries no pronation state we can read, so "
        '"postero-ulnar" here means the posterior sector of the wrist ring in the '
        'limb frame, which is why confidence is low.',
    ),
    # band_frac 0.030 -> 0.024, 2026-08-08. THE BAND WAS CHOSEN BY RELIEF CONTRAST AND BY
    # NOTHING ELSE, which matters because the patch also feeds a gate this package would
    # dearly like to pass, and tightening a patch until a gate passes is the move this
    # pipeline forbids. Swept on the neutral, contrast against the collar beside it:
    #     band_frac  0.030   0.024   0.020   0.016   0.012   0.010
    #     contrast   3.062   6.095   1.001   1.483  -0.771   0.095
    #     verdict    prot.   prot.   flat    flat    flat     flat
    # 0.024 is a SHARP INTERIOR MAXIMUM — better than both neighbours, and everything
    # below it collapses to flat — so it is an argmax and not a trend someone stopped
    # walking down at a convenient point. It doubles the contrast (3.062 -> 6.095) while
    # keeping essentially all the relief (8.902 -> 8.760 mm) and dropping the patch from
    # 81.30 mm to 58.18 mm tall, i.e. from 0.048 to 0.035 of stature. reach_frac is INERT
    # for this patch (identical vertex sets at 0.080 / 0.050 / 0.035 / 0.025) and is left
    # where it was rather than tidied, so this edit changes exactly one number.
    #
    # WHY IT NEEDED TIGHTENING, from geom/patella_skin.py's own cost block: the 0.030
    # patch is about twice the height of a patella and roughly its upper half is
    # suprapatellar THIGH, which has the longest lever arm about the knee. Skinning that
    # patch to the shank — which the extensor-mechanism correction must do, and which the
    # LBS algebra in that module shows is forced — therefore drags thigh skin with the
    # kneecap. That module names this exact edit as "the fix that has no cost".
    dict(
        name='patella',
        how='ring_sector',
        args=dict(
            ring_label='measure-knee-circ-incr',
            ring_side_label=None,
            axis_to_label='measure-ankle-circ-incr',
            direction='anterior',
            half_deg=45.0,
            band_frac=0.024,
            reach_frac=0.08,
        ),
        claim='surface_aspect',
        confidence='medium',
        anchor="anterior 90-degree sector of MakeHuman's knee girth ring "
        "(measure-knee-circ-incr), in the shank's frame",
        anchor_kind='ring_sector',
        note='MEASURED +8.90 mm at contrast 3.06 — the front of the knee does stand proud '
        'of the surface around it, and the posterior control sector reads +0.62 mm. '
        'That does NOT contradict landmarks.py reporting patella_mid unresolved, and '
        'the difference is worth stating because it is exactly the metric-vs-form '
        'distinction this package exists for: landmarks.py looked for a local maximum '
        'in the SAGITTAL HEIGHT PROFILE and found the anterior profile monotone, '
        'which is a statement about where the knee is; this measures the patch '
        'against the surface beside it, which is a statement about how the knee '
        'READS. A knee that is flatter front-to-side than this is a form defect even '
        'though no landmark moved. claim is surface_aspect because a raised anterior '
        'knee is not by itself a patella.',
    ),
    dict(
        name='tibial_tuberosity',
        how='ring_sector',
        args=dict(
            ring_label='measure-lowerleg-height-incr',
            ring_side_label=None,
            axis_to_label='measure-ankle-circ-incr',
            direction='anterior',
            half_deg=35.0,
            band_frac=0.014,
            reach_frac=0.07,
            offset_frac=0.022,
        ),
        claim='surface_aspect',
        confidence='low',
        anchor='anterior sector of the shank 0.022 of stature distal to the KNEE JOINT '
        'LINE (boundary of the measure-lowerleg-height-incr support, which '
        'landmarks.py resolves as tibiale)',
        anchor_kind='joint_line_sector',
        note='The 0.022-of-stature offset is a HOUSE constant, chosen as roughly the '
        "tuberosity's distance below the joint line on an adult, and it is the "
        'weakest link in this table: nothing on the cage confirms it. Measured, the '
        'patch is 7 vertices reading +1.49 mm at contrast 0.58 — below the null p95 '
        '— so there is no tuberosity here to calibrate the offset against either.',
    ),
    dict(
        name='malleolus_lat',
        how='ring_sector',
        args=dict(
            ring_label='measure-ankle-circ-incr',
            ring_side_label=None,
            axis_to_label='measure-ankle-circ-incr',
            direction='lateral',
            half_deg=45.0,
            band_frac=0.016,
            reach_frac=0.05,
        ),
        claim='surface_aspect',
        confidence='medium',
        anchor="lateral 90-degree sector of MakeHuman's ankle girth ring, in the shank's frame",
        anchor_kind='ring_sector',
        note='Measured -0.18 mm at contrast -0.06: FLAT. This independently confirms '
        'landmarks.py, which reports malleolus_lat UNRESOLVED because the lateral '
        'height profile runs 256.3 mm down to 245.9 mm with no local maximum. Two '
        'different measurements, one profile-based and one relief-based, agree that '
        'the ankle of this cage tapers smoothly and has no malleolus.',
    ),
    dict(
        name='malleolus_med',
        how='ring_sector',
        args=dict(
            ring_label='measure-ankle-circ-incr',
            ring_side_label=None,
            axis_to_label='measure-ankle-circ-incr',
            direction='medial',
            half_deg=45.0,
            band_frac=0.016,
            reach_frac=0.05,
        ),
        claim='surface_aspect',
        confidence='medium',
        anchor="medial 90-degree sector of MakeHuman's ankle girth ring, in the shank's frame",
        anchor_kind='ring_sector',
        note='Measured +0.71 mm at contrast 0.29: FLAT, same as the lateral side. On a '
        'real ankle the medial malleolus sits higher and further forward than the '
        'lateral one and the asymmetry is one of the most-taught landmarks in '
        'figure drawing; here the two sides differ by 0.9 mm, which is inside the '
        "cage's own noise.",
    ),
)

REGION_NAMES = tuple(s['name'] + '_' + side for s in REGION_SPEC for side in ('l', 'r'))
