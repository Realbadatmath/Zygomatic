# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""THE TABLES, part 2: breadths, depths, heights, lengths and the unmeasurable sites.

Moved verbatim out of the old single-file measure.py (lines 1282-1717).
"""

BREADTH_SPEC = (
    dict(
        name='biacromial_breadth',
        measurable=False,
        iso_class='breadth',
        ansur='biacromial_breadth_over_stature',
        landmark='acromion to acromion',
        reason='UNMEASURABLE ON THIS CAGE. The acromion landmark resolves a HEIGHT but '
        'not a lateral position: landmarks.py resolves it as the top of the '
        'shoulder surface inside a coronal slab whose x is the SLAB CENTRE, and '
        'doubling that x gives 279.6 mm on the stock anny body against an ANSUR '
        'biacromial mean of 399 mm for that stature — 30% narrow. A silhouette '
        'search lands on the deltoid instead (bideltoid, a different dimension). '
        'Biacromial breadth also correlates only r=0.53 with stature, so it '
        'cannot be recovered from a stature-anchored point either.',
    ),
    dict(
        name='bicristal_breadth',
        measurable=False,
        iso_class='breadth',
        ansur='bicristal_breadth_over_stature',
        landmark='iliocristale to iliocristale',
        reason='UNMEASURABLE ON THIS CAGE. There is no iliac crest: landmarks.py '
        'measured the lateral half-breadth profile of the male original falling '
        'monotonically from 181.4 mm at 0.50 of stature to the waist minimum at '
        '0.61 with no intervening crest bulge. Any bicristal number would be a '
        'hip or waist breadth wearing the wrong name.',
    ),
    dict(
        name='bideltoid_breadth',
        measurable=True,
        plane='horizontal',
        anchor=dict(fz_band=(0.74, 0.86)),
        scope='all',
        scan=dict(mode='max_extent'),
        axis_label='x',
        iso_class='breadth',
        ansur='bideltoid_breadth_over_stature',
        survey_comparable=False,
        survey_reason='the A-pose abducts the humerus about 40 degrees (measured from '
        'the COCO shoulder and elbow centres on the male original), which '
        'carries the deltoid laterally. The number is a correct '
        'measurement of THIS POSE and is not the standing survey '
        'dimension. Reported against the band anyway so the size of the '
        'pose effect is visible, not hidden.',
        landmark='maximum lateral extent over 0.74-0.86 of stature, arms INCLUDED',
        note='Bideltoid breadth is a soft-tissue dimension that legitimately includes '
        'the deltoids, so this is the one breadth where the arms belong.',
    ),
    dict(
        name='chest_breadth',
        measurable=True,
        plane='horizontal',
        anchor=dict(landmark='thelion_r'),
        scope='torso',
        scan=None,
        axis_label='x',
        iso_class='breadth',
        ansur='chest_breadth_over_stature',
        landmark='lateral extent of the TORSO cross-section at thelion level',
        note='Read off the selected torso contour loop, so the arms are excluded by '
        'topology rather than by an x window.',
    ),
    dict(
        name='waist_breadth_omphalion',
        measurable=True,
        plane='horizontal',
        anchor=dict(landmark='omphalion'),
        scope='torso',
        scan=None,
        axis_label='x',
        iso_class='breadth',
        ansur='waist_breadth_over_stature',
        landmark='lateral extent of the TORSO cross-section at omphalion level',
        note='ANSUR waist breadth is taken at omphalion, which is the site used here.',
    ),
    dict(
        name='hip_breadth',
        measurable=True,
        plane='horizontal',
        anchor=dict(fz_band=(0.44, 0.58), above_crotch=True, above_trochanterion=True),
        scope='torso',
        scan=dict(mode='max_extent'),
        axis_label='x',
        iso_class='breadth',
        ansur='hip_breadth_over_stature',
        landmark='maximum lateral extent of the torso cross-section from the resolved '
        'trochanterion up to 0.58 of stature',
        note='ANSUR hip breadth is the maximum lateral hip contour STANDING. THE BAND '
        "FLOOR IS THE TROCHANTERION (HOUSE, resolved per mesh from anny's own "
        'femoral-head centre), NOT the crotch. The crotch floor this site shipped '
        'with until 2026-08-05 was justified by "below the crotch the torso section '
        'is the two thighs fused to the pelvis" and that reasoning is exactly '
        'inverted. MEASURED on all five bodies (anny-neutral, male, female, abel, '
        'cornelis): BELOW the crotch the torso scope selects ONE LEG (male 197.55 mm '
        'at 0.4533 of stature), and it is AT AND ABOVE the crotch that the section '
        'first becomes pelvis-plus-both-thighs (male 199.31 mm at the 3-loop crotch '
        'plane, then 417.90 mm one step above it). From there the x-extent falls '
        'MONOTONICALLY to the 0.58 ceiling, so a maximum search floored at the '
        'crotch returned the first single-loop plane above the crotch on every body '
        'without exception — found_at minus crotch was exactly +0.0020 on all five — '
        'and the number reported as "hip breadth" was the width of the perineum: '
        'male 417.90 mm at 0.4573, whose extreme point sits 52.9 mm BELOW the '
        'trochanterion, against 385.8 mm at the trochanterion itself. landmarks.py '
        'records the same cage property independently ("the widest lateral point of '
        'the pelvis-and-thigh region sits at 0.43 of stature, 0.08 BELOW ANSUR '
        'trochanterion, because the outer thigh is wider than the hip on this '
        'cage"), which is why NO maximum search over a band that reaches into the '
        'thigh can return a hip breadth here. The greater trochanter is the accepted '
        'inferior limit of the hip, so it is the floor, and an unresolved '
        'trochanterion REFUSES the measurement rather than falling back. The search '
        'is kept, not replaced by a fixed plane, so a body with a genuine '
        'trochanteric or iliac bulge still finds it — but on all four issued '
        'characters the winner is the first usable plane, so every one of them now '
        'carries at_window_endpoint=True and a BAND-EDGE flag saying this is the '
        'extent AT the trochanterion, not an interior maximum. The 0.58 ceiling is '
        'unchanged HOUSE and, the profile being monotone, does not touch the '
        'value.',
    ),
    dict(
        name='head_breadth',
        measurable=True,
        plane='horizontal',
        anchor=dict(fz_band=(0.90, 0.995), above_ears=True),
        scope='head',
        scan=dict(mode='max_extent'),
        axis_label='x',
        iso_class='head_with_hair',
        ansur='head_breadth_over_stature',
        survey_comparable=False,
        survey_reason='ANSUR head breadth is measured over hair; this cage is bald',
        landmark='maximum lateral extent of the head above the ear morph support',
        note='"Maximum lateral cranial breadth ABOVE THE EARS" is the definition, and '
        'the ear is a 14 mm-per-side bulge on this cage, so the band floor is taken '
        'from the ear morph support rather than from a fixed fraction. Measured on '
        'the male: half-breadth 98.3 mm at 0.93 of stature (ear) against 84.2 mm at '
        '0.94 (cranium) — a band starting at 0.92 measures the ears and overstates '
        'head breadth by about 28 mm.',
    ),
)

DEPTH_SPEC = (
    dict(
        name='chest_depth',
        plane='horizontal',
        anchor=dict(landmark='thelion_r'),
        scope='torso',
        scan=None,
        iso_class='depth',
        ansur='chest_depth_over_stature',
        landmark='anterior-posterior extent of the torso cross-section at thelion level',
        note='ANSUR chest depth is taken at the level of the chest circumference, which '
        'is the thelion level used here.',
    ),
    dict(
        name='waist_depth_omphalion',
        plane='horizontal',
        anchor=dict(landmark='omphalion'),
        scope='torso',
        scan=None,
        iso_class='depth',
        ansur=None,
        landmark='anterior-posterior extent of the torso cross-section at omphalion',
        note='No ANSUR standing abdominal depth at omphalion is in the pack — the pack '
        'carries abdominalextensiondepthsitting, which is a SEATED measurement and '
        'is not comparable to a standing mesh.',
    ),
    dict(
        name='buttock_depth',
        plane='horizontal',
        anchor=dict(landmark='buttock'),
        scope='torso',
        scan=None,
        iso_class='depth',
        ansur='buttock_depth_over_stature',
        landmark='anterior-posterior extent of the torso at the buttock landmark',
        note='ANSUR buttock depth is the horizontal depth at the maximum posterior '
        'buttock protrusion, which is the buttock landmark itself.',
    ),
    dict(
        name='head_length',
        plane='horizontal',
        anchor=dict(fz_band=(0.90, 0.995), above_ears=True),
        scope='head',
        scan=dict(mode='max_extent_y'),
        iso_class='head_with_hair',
        ansur='head_length_over_stature',
        survey_comparable=False,
        survey_reason='ANSUR head length is measured over hair; this cage is bald, and '
        'the maximum AP extent over the cranial band is only a HOUSE '
        'stand-in for the glabella-occiput line',
        landmark='maximum anterior-posterior extent of the head above the ear support',
        note='The band floor matters here for a second reason: the NOSE sits at 0.912 of '
        'stature and would otherwise be included, and ANSUR head length explicitly '
        'starts at glabella, behind it.',
    ),
)

# Heights taken straight from resolved landmarks. Each is stature-relative, and stature
# predicts heights almost deterministically (cervicale r=0.98), which is why these may be
# gated tight while every breadth above must be gated wide.
HEIGHT_SPEC = (
    dict(
        name='stature',
        landmark='vertex',
        iso_class='height',
        ansur=None,
        note='Mesh z-extent, vertex to the standing surface. The cage is bald so there is no hair offset to subtract.',
    ),
    dict(
        name='acromial_height',
        landmark='acromion_r',
        iso_class='height',
        ansur='acromial_height_over_stature',
        note='Skin over the acromion; a small positive bias against the bony landmark is expected.',
    ),
    dict(
        name='suprasternale_height',
        landmark='suprasternale',
        iso_class='height',
        ansur='suprasternale_height_over_stature',
        note='',
    ),
    dict(
        name='thelion_height',
        landmark='thelion_r',
        iso_class='height',
        ansur='chest_height_over_stature_NOT_IN_PACK',
        note='',
    ),
    dict(
        name='waist_height_omphalion',
        landmark='omphalion',
        iso_class='height',
        ansur='waist_height_omphalion_over_stature',
        note='',
    ),
    dict(
        name='trochanterion_height',
        landmark='trochanterion_r',
        iso_class='height',
        ansur='trochanterion_height_over_stature',
        note="Height from anny's own femoral-head joint centre, not from a surface "
        'feature — the greater trochanter has no signature on this cage.',
    ),
    dict(
        name='buttock_height',
        landmark='buttock',
        iso_class='height',
        ansur='buttock_height_over_stature',
        note='DEFINITION MISMATCH TO WATCH: landmarks.py resolves this as the height of '
        'maximum posterior protrusion, while the reference pack describes the ANSUR '
        'column as the gluteal furrow. The two agents disagree about the ANSUR '
        'definition and this file does not adjudicate it — treat the comparison as '
        'definitionally uncertain rather than as a measurement error.',
    ),
    dict(
        name='crotch_height',
        landmark='crotch',
        iso_class='height',
        ansur='crotch_height_over_stature',
        note='ANSUR crotch height is taken with a bar pressed up into the crotch, which '
        'compresses tissue and reads HIGH, so a free-surface value slightly below '
        'the survey mean is expected. This is also the ratio with the largest '
        'ancestry effect in the whole reference pack (0.024 of stature between male '
        'groups, 44 mm of leg on a 1.85 m man), so it must never be gated against a '
        'single population.',
    ),
    dict(
        name='tibiale_height',
        landmark='tibiale_r',
        iso_class='height',
        ansur='tibiale_height_over_stature',
        note='Proximal boundary of the lowerleg-height morph support. Threshold '
        'sensitive: landmarks.py measured 0.2666 at a 1e-4 cut and 0.2437 at 3e-3.',
    ),
)

# Landmark-pair lengths that survive the A-pose because they are chords, not heights.
LENGTH_SPEC = (
    dict(
        name='hand_length',
        a='wrist_ring_r',
        b='dactylion_r',
        iso_class='hand',
        ansur='hand_length_over_stature',
        mode='3d',
        survey_comparable=False,
        survey_reason='the proximal end is a girth-ring centroid, not the stylion line '
        'where ANSUR hand length starts, so part of the excess is '
        'definitional and cannot be separated from a genuinely long hand',
        note='Wrist-ring centroid to fingertip. Runs LONG against ANSUR partly by '
        'definition — the ring centroid sits proximal to the stylion line where '
        'hand length starts. Read it as "anny hands run a few percent long", not as '
        'a calibrated hand length.',
    ),
    dict(
        name='foot_length',
        a='pternion_r',
        b='acropodion_r',
        iso_class='foot',
        ansur='foot_length_over_stature',
        mode='horizontal',
        note='Heel to longest toe, horizontal component, which is how foot length is '
        'defined (maximum length with the subject standing).',
    ),
    dict(
        name='head_height_vertex_menton',
        a='vertex',
        b='menton',
        iso_class=None,
        ansur=None,
        mode='vertical',
        note='HOUSE CONSTANT WITH NO SURVEY SOURCE. ANSUR II has head length and '
        'tragion-to-top-of-head but no menton-to-vertex head height, so any "heads '
        'tall" figure derived from this must never be cited to a survey.',
    ),
)

# Sites and dimensions this cage cannot produce, kept in the output so a consumer sees the
# hole rather than an absence.
UNMEASURABLE = (
    dict(
        name='waist_circumference_who_rib_iliac',
        kind='girth',
        iso_class='circumference_large',
        landmark='midpoint between the lowest rib and the iliac crest',
        reason='UNMEASURABLE ON THIS CAGE. The WHO/IDF site is defined by two landmarks '
        'this cage does not carry: landmarks.py reports tenth_rib UNRESOLVED (no '
        'costal margin; the nearest shipped ring sits 115 mm too high on the '
        '1.85 m male) and iliocristale UNRESOLVED (no crest bulge in the lateral '
        'profile). Substituting the omphalion waist here would import an error of '
        'up to 10.1 cm in women.',
    ),
    dict(
        name='waist_circumference_nih_iliac_crest',
        kind='girth',
        iso_class='circumference_large',
        landmark='iliac crest (NHANES / NIH protocol)',
        reason='UNMEASURABLE ON THIS CAGE. Same missing landmark: no iliac crest. The '
        'NIH and WHO waist sites differ from each other by up to 10.1 cm in '
        'women, so neither may stand in for the other, let alone for omphalion.',
    ),
    dict(
        name='cervicale_height',
        kind='height',
        iso_class='height',
        landmark='cervicale (spinous process of C7)',
        reason='UNMEASURABLE DIRECTLY. The posterior midline profile is monotone from '
        '0.76 to 0.92 of stature with no vertebra prominens, and three surface '
        'operationalisations disagree by 66 mm on the male. A HOUSE substitute is '
        'emitted separately as cervicale_height_house (suprasternale plus the '
        'ANSUR-measured cervicale-minus-suprasternale offset) and is labelled '
        'HOUSE, not MEASURED.',
    ),
    dict(
        name='iliocristale_height',
        kind='height',
        iso_class='height',
        landmark='iliocristale',
        reason='UNMEASURABLE: no iliac crest on this cage.',
    ),
    dict(
        name='tenthrib_height',
        kind='height',
        iso_class='height',
        landmark='tenth rib midspine',
        reason='UNMEASURABLE: the tenth rib is palpated, not seen, and this cage has no costal margin.',
    ),
    dict(
        name='knee_height_midpatella',
        kind='height',
        iso_class='height',
        landmark='mid-patella',
        reason='UNMEASURABLE: no patellar bulge — the anterior profile of the lower limb '
        'rises monotonically through the knee.',
    ),
    dict(
        name='lateral_malleolus_height',
        kind='height',
        iso_class='height',
        landmark='lateral malleolus',
        reason='UNMEASURABLE: the ankle tapers smoothly with no malleolar prominence.',
    ),
    dict(
        name='wrist_height',
        kind='height',
        iso_class='height',
        landmark='stylion',
        reason='NOT MEASURABLE IN THIS POSE. ANSUR wrist height is a standing-posture '
        'height with the arm hanging (0.4825 of stature); the A-posed wrist ring '
        'sits at 0.608 of stature on the neutral. The number exists but it is a '
        'pose coordinate, not the survey dimension.',
    ),
    dict(
        name='span',
        kind='segment_length',
        iso_class='segment_length',
        landmark='dactylion to dactylion',
        reason='NOT MEASURABLE IN THIS POSE. Span is taken with the arms horizontal; the '
        'A-pose half-span is 0.31-0.37 of stature against an ANSUR span of about '
        '1.0 of stature.',
    ),
    dict(
        name='sitting_height',
        kind='height',
        iso_class='height',
        landmark='vertex, seated',
        reason='NOT MEASURABLE FROM A STANDING MESH. Sitting height requires the seated '
        'posture; it cannot be inferred from standing landmarks without assuming '
        'the cormic index, which is the quantity it would be used to test. This '
        'is the component that would most improve the joint plausibility check '
        '(it is 1 of the 10 Mahalanobis vector components), and its absence is a '
        'real limitation of a standing-only pipeline, not an oversight.',
    ),
    dict(
        name='acromion_radiale_length',
        kind='segment_length',
        iso_class='segment_length',
        landmark='acromion to radiale',
        reason='NOT MEASURABLE AS THE SURVEY DEFINES IT. The cage has no radiale (head '
        'of radius). An acromion-to-elbow-joint-centre chord is available and is '
        'pose-invariant, but it is a joint-centre proxy and is NOT the ANSUR '
        'dimension, so it is not emitted under this name and is not fed to the '
        'joint plausibility check.',
    ),
    dict(
        name='radiale_stylion_length',
        kind='segment_length',
        iso_class='segment_length',
        landmark='radiale to stylion',
        reason='NOT MEASURABLE AS THE SURVEY DEFINES IT. Neither radiale nor stylion exists on this cage.',
    ),
)
