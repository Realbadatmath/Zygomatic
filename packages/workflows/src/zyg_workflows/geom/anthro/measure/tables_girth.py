# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""THE TABLES, part 1: the girth sites and the conventions their columns declare.

Moved verbatim out of the old single-file measure.py (lines 958-1281).
"""

# ---------------------------------------------------------------------------------
# THE TABLES
# ---------------------------------------------------------------------------------
# plane   : 'horizontal' (torso convention) or 'limb_perp' (ISO 18825-2 limb convention)
# anchor  : where the plane sits — a landmark name, a MakeHuman ring, or a COCO joint
# scan    : None for a single plane, else {'mode': 'max'|'min', 'half_fz': ...} which
#           searches along the plane normal for the extreme girth the survey asks for
# scope   : 'torso'  -> select the torso loop, refuse if an arm merged into it
#           'limb'   -> select the loop nearest the anchor
#           'all'    -> hull over EVERY loop in the plane (a tape that goes over the arms)
#           'head'   -> the single loop above the ears
# ansur   : the reference-pack ratio key this value may be compared to, or None when the
#           survey measures something we are not measuring.
GIRTH_SITES = (
    dict(
        name='neck_circumference',
        plane='limb_perp',
        axis='neck',
        anchor=dict(ring='measure-neck-circ-incr'),
        sides=(),
        scope='limb',
        scan=None,
        iso_class='circumference_small',
        ansur='neck_circumference_over_stature',
        landmark="MakeHuman measure-neck-circ-incr ring (vendor's own neck girth site)",
        note='ANSUR takes neck circumference just inferior to the thyroid cartilage. '
        "The MakeHuman ring is the vendor's neck-girth site and is not guaranteed "
        'to be that level, so a systematic offset is expected and is not an error '
        'in the slicer.',
    ),
    dict(
        name='shoulder_circumference',
        plane='horizontal',
        axis=None,
        anchor=dict(fz_band=(0.76, 0.86)),
        sides=(),
        scope='all',
        scan=dict(mode='max'),
        iso_class='circumference_large',
        ansur='shoulder_circumference_over_stature',
        survey_comparable=False,
        survey_reason='same 40-degree A-pose abduction as bideltoid breadth: the tape '
        'goes round two arms held away from the trunk, which is not the '
        'standing dimension. The number is right for this pose.',
        landmark='maximum horizontal girth over the deltoids, 0.76-0.86 of stature',
        note='DELIBERATELY includes the arms: the ANSUR tape passes over both deltoids '
        'and across the chest, so the convex hull is taken over the torso loop AND '
        'both arm loops together. This is the one site where the arm-exclusion '
        'logic must be switched off. POSE SENSITIVE: an A-pose abducts the humerus '
        'and moves the deltoid, so expect a real offset from a standing tape.',
    ),
    dict(
        name='chest_circumference',
        plane='horizontal',
        axis=None,
        anchor=dict(landmark='thelion_r'),
        sides=(),
        scope='torso',
        scan=None,
        iso_class='circumference_large',
        ansur='chest_circumference_over_stature',
        landmark='thelion (bustpoint) level, from the nipple-size-incr support',
        note='ANSUR chest circumference is taken at the bustpoint level, which is what the thelion landmark resolves.',
    ),
    dict(
        name='bust_circumference_makehuman_ring',
        plane='horizontal',
        axis=None,
        anchor=dict(landmark='bust_ring'),
        sides=(),
        scope='torso',
        scan=None,
        iso_class='circumference_large',
        ansur=None,
        landmark='MakeHuman measure-bust-circ-incr ring centroid height',
        note="The vendor's own bust site. Kept because it is the level anny's own bust "
        'morph acts on, which is what a caller editing that morph is changing. No '
        'ANSUR key: ANSUR has chest circumference at bustpoint, not a "bust" site.',
    ),
    dict(
        name='underbust_circumference_makehuman_ring',
        plane='horizontal',
        axis=None,
        anchor=dict(landmark=None, ring='measure-underbust-circ-incr'),
        sides=(),
        scope='torso',
        scan=None,
        iso_class='circumference_large',
        ansur=None,
        landmark='MakeHuman measure-underbust-circ-incr ring centroid height',
        note='Vendor site. NOT a tenth-rib substitute — landmarks.py measured this ring '
        'at 0.700 of stature against an ANSUR tenth rib of 0.6380, 115 mm high on '
        'the 1.85 m male.',
    ),
    dict(
        name='waist_circumference_omphalion',
        plane='horizontal',
        axis=None,
        anchor=dict(landmark='omphalion'),
        sides=(),
        scope='torso',
        scan=None,
        iso_class='circumference_large',
        ansur='waist_circumference_omphalion_over_stature',
        landmark='omphalion (navel), from the 19-vertex stomach-navel-out support',
        note='THE ANSUR II SITE, and the only waist in this module that a US Army band '
        'legitimately applies to. Not the WHO site and not the NIH site.',
    ),
    dict(
        name='waist_circumference_anny_ring',
        plane='horizontal',
        axis=None,
        anchor=dict(landmark='waist_ring_anny'),
        sides=(),
        scope='torso',
        scan=None,
        iso_class='circumference_large',
        ansur=None,
        landmark='mean height of anny.anthropometry.BASE_MESH_WAIST_VERTICES (46 verts)',
        note="The vendor's own waist level, sliced with OUR convention so the number is "
        "comparable to the rest of this table. anny's own figure for the same ring "
        'is a 3D chord sum over its 46 authored vertices and is reported separately '
        'by compare_conventions(); measured, it runs 33.0 mm LONG on the male '
        'original and 3.6 mm long on the female against our hull at the same '
        'level.',
    ),
    dict(
        name='waist_circumference_narrowest',
        plane='horizontal',
        axis=None,
        anchor=dict(landmark_band=('omphalion', -0.025, 0.070)),
        sides=(),
        scope='torso',
        scan=dict(mode='min'),
        iso_class='circumference_large',
        ansur=None,
        landmark='minimum horizontal girth from 0.025 below to 0.070 of stature above the omphalion',
        note='A GEOMETRIC minimum, not a survey site: no authority defines the waist as '
        'the narrowest section, and on many real torsos no interior minimum exists '
        'at all (the scan then returns a band endpoint, which is flagged). The '
        'band is anchored on the navel rather than on a fixed fraction of stature '
        'because a fixed 0.55-0.72 band reaches into the chest: on the male it put '
        'the "abdominal maximum" at 0.708 of stature, which is rib cage.',
    ),
    dict(
        name='abdominal_circumference_maximum',
        plane='horizontal',
        axis=None,
        anchor=dict(landmark_band=('omphalion', -0.025, 0.070)),
        sides=(),
        scope='torso',
        scan=dict(mode='max'),
        iso_class='circumference_large',
        ansur=None,
        landmark='maximum horizontal girth from 0.025 below to 0.070 of stature above the omphalion',
        note='The largest belly section. Geometric, like the narrowest — shipped as the '
        'other end of the same scan so the two bracket every named waist site.',
    ),
    dict(
        name='buttock_circumference',
        plane='horizontal',
        axis=None,
        anchor=dict(landmark='buttock'),
        sides=(),
        scope='torso',
        scan=None,
        iso_class='circumference_large',
        ansur='buttock_circumference_over_stature',
        landmark='horizontal plane at the buttock landmark (maximum posterior protrusion)',
        note='ANSUR buttock circumference is taken at the level of maximum posterior '
        'protrusion, which the buttock landmark resolves. A maximum-girth SCAN was '
        'tried first and is wrong: girth keeps growing downward toward the crotch '
        'because the section picks up both thigh tops, so the scan peaked 1 mm '
        'above the crotch (measured on the male: 1082.6 mm at 0.46 of stature '
        'against 1028.9 mm at the buttock landmark, with a 124 mm hull-to-contour '
        'gap from the perineal notch). Commonly and loosely called "hip '
        'circumference"; hip_circumference_makehuman_ring is a different level.',
    ),
    dict(
        name='hip_circumference_makehuman_ring',
        plane='horizontal',
        axis=None,
        anchor=dict(landmark='hip_ring'),
        sides=(),
        scope='torso',
        scan=None,
        iso_class='circumference_large',
        ansur=None,
        landmark='MakeHuman measure-hips-circ-incr 0.8-core ring centroid height',
        note='The vendor hip site. Reported alongside buttock_circumference precisely '
        'because "hip circumference" is one of the ambiguous names — the two are '
        'different levels and the difference is visible in the output.',
    ),
    dict(
        name='upperarm_circumference_relaxed',
        plane='limb_perp',
        axis='upperarm',
        anchor=dict(ring='measure-upperarm-circ-incr'),
        sides=('l', 'r'),
        scope='limb',
        scan=dict(mode='max', half_fz=0.03),
        iso_class='circumference_small',
        ansur=None,
        landmark='maximum girth of the upper arm around the measure-upperarm-circ ring',
        note='NO ANSUR COMPARISON IS OFFERED. The only ANSUR II upper-arm girth is '
        'bicepscircumferenceflexed, taken with the biceps CONTRACTED; this mesh is '
        'relaxed. The two differ by centimetres and comparing them would be a '
        'definition error, not a tolerance question.',
    ),
    dict(
        name='elbow_circumference',
        plane='limb_perp',
        axis='elbow',
        anchor=dict(coco='%s_elbow'),
        sides=('l', 'r'),
        scope='limb',
        scan=None,
        iso_class='circumference_small',
        ansur=None,
        landmark='anny COCO elbow joint centre, plane normal along shoulder-to-wrist',
        note='Anchored on a JOINT CENTRE because the cage has no olecranon and there is '
        'no measure-elbow-circ target. The plane normal is the shoulder-to-wrist '
        'direction, which bisects the two segment axes — that is how a tape sits at '
        'a flexed joint. ANSUR II has no elbow circumference to compare against.',
    ),
    dict(
        name='wrist_circumference',
        plane='limb_perp',
        axis='forearm',
        anchor=dict(ring='measure-wrist-circ-incr'),
        sides=('l', 'r'),
        scope='limb',
        scan=dict(mode='min', half_fz=0.025),
        iso_class='circumference_small',
        ansur='wrist_circumference_over_stature',
        landmark='minimum girth of the distal forearm around the measure-wrist-circ ring',
        note='ANSUR takes wrist circumference at stylion level. This cage has no radial '
        'styloid (landmarks.py: UNRESOLVED), so the minimum distal-forearm girth is '
        'used instead — a HOUSE operationalisation of the site, not the ISO one.',
    ),
    dict(
        name='thigh_circumference',
        plane='limb_perp',
        axis='thigh',
        anchor=dict(ring='measure-thigh-circ-incr'),
        sides=('l', 'r'),
        scope='limb',
        scan=dict(mode='max', half_fz=0.04),
        iso_class='circumference_large',
        ansur='thigh_circumference_over_stature',
        ansur_uses='horizontal',
        landmark='maximum girth of the upper thigh around the measure-thigh-circ ring',
        note='ANSUR takes thigh circumference at the gluteal furrow with a HORIZONTAL '
        'tape; ISO 18825-2 takes it perpendicular to the femur. Both are computed. '
        'The ANSUR comparison uses the horizontal value, the perpendicular value is '
        'the scan-conformant one.',
    ),
    dict(
        name='knee_circumference',
        plane='limb_perp',
        axis='shank',
        anchor=dict(ring='measure-knee-circ-incr'),
        sides=('l', 'r'),
        scope='limb',
        scan=None,
        iso_class='circumference_small',
        ansur=None,
        landmark='MakeHuman measure-knee-circ-incr ring',
        note='ANSUR II carries knee height, not knee circumference, so no comparison band exists in the pack.',
    ),
    dict(
        name='calf_circumference',
        plane='limb_perp',
        axis='shank',
        anchor=dict(ring='measure-calf-circ-incr'),
        sides=('l', 'r'),
        scope='limb',
        scan=dict(mode='max', half_fz=0.04),
        iso_class='circumference_small',
        ansur='calf_circumference_over_stature',
        ansur_uses='horizontal',
        landmark='maximum girth of the shank around the measure-calf-circ ring',
        note='ANSUR takes the maximum calf girth with a horizontal tape. Both '
        'conventions are computed; the comparison uses the horizontal one.',
    ),
    dict(
        name='ankle_circumference',
        plane='limb_perp',
        axis='shank',
        anchor=dict(ring='measure-ankle-circ-incr'),
        sides=('l', 'r'),
        scope='limb',
        scan=dict(mode='min', half_fz=0.025),
        iso_class='circumference_small',
        ansur=None,
        landmark='minimum girth of the distal shank around the measure-ankle-circ ring',
        note='The minimum-girth ankle site. It legitimately sits above the malleoli — '
        'that is the definition, not a resolver error. ANSUR II has no ankle '
        'circumference in the public release columns this pack carries.',
    ),
    dict(
        name='head_circumference',
        plane='horizontal',
        axis=None,
        anchor=dict(fz_band=(0.90, 0.995), above_ears=True),
        sides=(),
        scope='head',
        scan=dict(mode='max'),
        iso_class='head_with_hair',
        ansur='head_circumference_over_stature',
        survey_comparable=False,
        survey_reason='ANSUR head dimensions are measured OVER HAIR and this cage is '
        'bald; the maximum-girth plane is also only a HOUSE stand-in for '
        'the glabella-occiput plane',
        landmark='maximum horizontal girth of the head above the ear morph support',
        note='The band floor is raised to the top of the ear morph support (measured per '
        'mesh), because the ear is a real lateral bulge on this cage — the '
        'half-breadth profile of the male runs 70.0 mm at 0.89 of stature, 98.3 mm '
        'at 0.93 (the ear) and 84.2 mm at 0.94 (the cranium). A band that starts '
        'below the ear top measures the ears, and the nose (0.912 of stature) as '
        'well.',
    ),
)
