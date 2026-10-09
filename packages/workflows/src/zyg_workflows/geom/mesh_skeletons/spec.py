# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The storage roots and the ORIGINALS spec: issue recipes, anatomy,
abs patterns, subdivision levels and the hashed-aux tuples.

Moved verbatim out of the old single-file mesh_skeletons.py (lines 104-424).
"""

import os


ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'data',
    'assets',
    'mesh_skeletons',
)
REGISTRY = os.path.join(ROOT, 'registry.json')

# The originals: neutral adults, one per sex. Everything else is 0.5 = the model's
# anatomical midpoint, which is the correct template value — a template should carry no
# opinions a derivation would have to undo.
#
# GENDER CONVENTION, MEASURED NOT ASSUMED (2026-08-05): in Anny, gender=0.0 is MALE and
# 1.0 is FEMALE — the reverse of the common slider convention. Established two ways:
# anthropometry (gender=0.0 measures 1.686m with 0.317m shoulders and shoulder/hip 1.77 —
# male-typical — vs 1.568m/0.291m/1.71 at 1.0) and decisively by the cupsize axis, which
# displaces the gender=1.0 body by 74mm and the gender=0.0 body by exactly 0.0mm. The
# first issue of the originals had the labels swapped because of this; they were
# re-issued the same day.
ORIGINAL_SPEC = {
    'male': {'gender': 0.0, 'age': 0.5, 'muscle': 0.5, 'weight': 0.5, 'height': 0.5, 'proportions': 0.5},
    'female': {'gender': 1.0, 'age': 0.5, 'muscle': 0.5, 'weight': 0.5, 'height': 0.5, 'proportions': 0.5},
}

# Issue heights for the originals (operator-specified 2026-08-05). The height AXIS value
# that lands each body on its target is found by binary search at build time against the
# measured vertex span — the number shown on the card is the number asked for.
TARGET_HEIGHT_M = {'male': 1.85, 'female': 1.68}

# Issue bodies, THIRD ISSUE 2026-08-05: recipes are now the output of geom/
# fit_reference.py — a trimmed, index-refreshed chamfer fit of anny's differentiable
# morph stack against point clouds sampled on the Blender Studio realistic bodies
# (CC0, data/assets/mesh_packs/blender_human_base). The two hand-calibration rounds
# before it both failed the operator's eye because scalar slice-width targets conflate
# arm pose with shoulder breadth (arms are connected to the torso at shoulder level —
# there is no x-gap to split on) and let the solver dump error into unmeasured
# dimensions. Mean surface distance after fit ≈ 8.1mm male / 9.2mm female at
# delivered height (the fit logs printed 8.9/10.4 — those were scaled by anny's
# fit-time native span ~2.05m, ~11% high; fixed in fit_reference.py). Arms/feet
# masked — anny's rest pose differs there. Both approved BY EYE, front AND side,
# against the references (scratchpad eyepass_*.png).
#
# Male muscle/weight were bounded apart (0.65-0.95 / 0.30-0.55) before fitting:
# chamfer cannot tell fat from muscle when both land the surface in the same place —
# unconstrained, the male fitted weight 0.75/muscle 0.35 and read soft.
#
# FOURTH ISSUE 2026-08-06, geom/fit_proportions.py: the leg/torso length subspace was
# re-fitted under an ANSUR-II constraint. The third issue's legs were too short for the
# survey — crotch_height_over_stature male 0.4553 (z -1.86, p2.7) and female 0.4485
# (z -2.10, p1.5), both outside p5-p95 of a MEASURED quantity. The chamfer objective
# never saw it, and the reference clouds are why: the CC0 Blender Studio bodies the third
# issue was fitted to measure 0.4320 (male, z -3.51, p0.02) and 0.4637 (female, z -1.09)
# on that same ratio by their own geometry, so on the male the surface objective was
# actively pulling AWAY from the survey. Six parameters were re-solved — the proportions
# macro plus measure-upperleg-height / measure-lowerleg-height / measure-napetowaist-dist
# / measure-waisttohip-dist / torso-scale-vert / measure-neck-height — with everything
# else, girths and breadths and the two hand nudges included, held exactly where the eye
# pass left it. THE HEAD MORPHS WERE HELD OUT ON PURPOSE: head count is CANON, has no
# survey source, and a fit allowed to shrink the head would have reached a MEASURED
# target through a CANON lever. Result: crotch z -0.022 (male) / -0.029 (female), i.e. on
# the population median. PRICE, measured on the same chamfer at the same registration:
# male forward 8.79 -> 9.82 mm and reverse 17.73 -> 18.73 mm, so the male has moved ~1 mm
# of mean surface distance away from a reference body that is itself at p0.02; the female
# IMPROVED on the forward term, 11.37 -> 11.15 mm (reverse 19.35 -> 19.54). The male
# torso is visibly shorter than the eye-approved third issue and NEEDS A NEW EYE PASS.
#
# FIFTH ISSUE 2026-08-07, geom/fit_proportions.py: the leg fix is KEPT, bony_relief is
# dropped from both bodies (see ORIGINAL_ANATOMY below), and the chamfer is no longer
# allowed to vote on leg length. Four things were measured on the way and the second one
# changed the diagnosis this pass was handed.
#
#   1. THE CHAMFER'S LEG AXIS IS NEUTRALISED. Every vertex below the body's own crotch and
#      every reference point below the REFERENCE's own crotch now leave both chamfer
#      terms. (The reference's leg proportion, measured with the landmark table's own
#      crotch rule on the sampled cloud: male 0.4372 z -3.14, female 0.4638 z -1.09 — we
#      were surface-fitting to a body 3 sd wrong on the very axis we were constraining.)
#      The upper body is still seen at true unit-height scale, so torso length and head
#      size stay fully constrained; only "how long are the legs" is gone, and the ANSUR
#      constraint answers that alone. THE PRICE OF THE LEG FIX WENT DOWN, NOT UP: the
#      male's full-body chamfer, on the same metric and registration the fourth issue
#      reported, 9.82 -> 9.46 mm forward and 18.74 -> 18.43 mm reverse, with crotch still
#      on the population median (z +0.009). The fourth issue had needed an 8x constraint
#      weight to beat a surface objective pulling the legs the wrong way; with that fight
#      removed the optimiser found a BETTER surface fit at the same survey leg length.
#
#   2. THE TORSO COMPRESSION WAS NOT WHAT CRASHED THE MALE'S TORSO HEIGHTS — bony_relief
#      was, by about 5:1. Dropping the layer and changing nothing else moves
#      suprasternale_height_over_stature p6.4 -> p32.5 (+1.09 sd, 14.2 mm of landmark).
#      The neck/torso morph cuts account for the remaining ~0.22 sd.
#
#   3. SO NO HEAD MORPH MOVED ON THE MALE. head-scale-vert/-horiz/-depth are exactly where
#      the third issue's eye pass left them. A lever is released only when a
#      survey-comparable MEASURED ratio is outside its band by more than the build's own
#      2 mm stature resolution AND by more than the A-pose bias the measurement itself
#      reports; after the relief drop the male has no such ratio. His whole change is the
#      leg/torso set relaxing back toward the third issue (napetowaist -0.269 -> -0.188,
#      waisttohip -0.176 -> -0.143, torso-scale-vert -0.316 -> -0.242, neck-height
#      0.404 -> 0.511, upperleg -0.681 -> -0.550, lowerleg -0.603 -> -0.448, proportions
#      0.0233 -> 0.0128). chest_circumference_over_stature came back INSIDE the band
#      (p95.6 -> p93) as a consequence, with no girth morph touched. head count is CANON,
#      never a target, and moved 6.971 -> 7.040 on its own.
#
#   4. THE FEMALE'S LEG/TORSO SET DID NOT MOVE AT ALL. Her unrestricted re-fit improved
#      the surface fit and put chest_breadth on the mean, but it also relaxed her leg
#      morphs by 0.17-0.22, which dropped the height axis, which shrank her FEET, and
#      foot_length_over_stature crossed from p9.1 to p1.8 — outside the band. Feet and
#      hands are in NO objective (fit_reference masks them out of the chamfer by skinning
#      weight and no ratio steers them) and may not be made free parameters, so
#      fit_proportions' do-no-harm guard DECLINED the improvement and re-solved with her
#      whole leg/torso free set frozen. Her only change is the chest:
#      torso-vshape-incr 0.5371 -> -0.7519 and torso-scale-depth-incr 0.023 -> 0.3810, a
#      breadth->depth rotation at near-constant girth that takes
#      chest_breadth_over_stature 0.1952 (p99.2, her only survey-comparable ratio outside
#      the band) to 0.1662 (z +0.06) while chest_depth goes p29 -> p56 and
#      chest_circumference stays inside at p44. PRICE: her full-body chamfer 11.16 ->
#      11.49 mm forward, 19.55 -> 19.82 mm reverse. That 0.33 mm is what correcting a
#      p99.2 breadth costs against a reference body she no longer matches there.
#
# WHAT THIS ISSUE DOES NOT FIX, stated so it is not mistaken for a clean bill:
#   * wrist_circumference_over_stature is outside the band on BOTH bodies and gets 0.71 sd
#     WORSE when bony_relief comes off (male p0.8 -> p0.4, female p0.5 -> p0.0). anny has
#     no wrist girth target, so there is no lever at all.
#   * female waist_hip_circumference p1.4 -> p2.6 and waist_over_stature p5.3 -> p6.9:
#     improved, still outside, and both PRE-EXISTING. Fixing them needs her eye-approved
#     waist/hip girths, which a repair pass does not re-open.
#   * male chest_breadth reads 500.6 mm at thelion level while his chest_circumference
#     reads 1274.5 mm; an ellipse 500.6 x 281.4 mm has a ~1521 mm perimeter, so on him the
#     breadth and the girth are not describing the same section (the female's ARE
#     consistent: 327.9 x 240.1 -> ~897 mm against 975 mm measured). His chest_breadth is
#     therefore not treated as a steerable body dimension by this pass. That belongs to
#     whoever owns geom/anthro/measure.py.
#   * head_length, head_breadth, head_circumference, cephalic_index and hand_length are
#     all survey_comparable=FALSE by the measurement layer's own declaration (head
#     dimensions are ANSUR-measured over hair and this cage is bald; the head extents are
#     additionally at_window_endpoint, i.e. properties of the search window; hand length
#     starts at a girth-ring centroid, not the stylion line). None of them may drive a
#     change, and none of them did.
# BOTH BODIES NEED A NEW EYE PASS.
ORIGINAL_PHEN = {
    'male': {
        'age': 0.4643,
        'muscle': 0.9385,
        'proportions': 0.0128,
        'weight': 0.5486,
    },
    'female': {
        'age': 0.646,
        'muscle': 0.9423,
        'proportions': 0.1621,
        'weight': 0.6859,
    },
}
# Local morphs: fitted values, hard-capped at ±0.8 inside the fitter (the swayback
# lesson — beyond the designed range MakeHuman targets bend anatomy, not scale it).
# Two post-fit nudges on the male, both re-approved by eye front+side: shoulder-dist
# 0.5957 -> 0.72 (deltoid verts are arm-masked, the fitter cannot see shoulder caps)
# and pectoral 0.1354 -> 0.28 (reference pec line is stronger; 0.35 was the
# operator-approved ceiling from the bust-profile A/B).
ORIGINAL_LOCALS = {
    'male': {
        'buttocks-volume-incr': -0.477,
        'head-scale-depth-incr': 0.4779,
        'head-scale-horiz-incr': 0.1644,
        'head-scale-vert-incr': 0.2941,
        'hip-scale-depth-incr': 0.2888,
        'hip-scale-horiz-incr': 0.1902,
        'l-upperleg-scale-depth-incr': 0.0964,
        'l-upperleg-scale-horiz-incr': 0.2268,
        'measure-calf-circ-incr': 0.4263,
        'measure-hips-circ-incr': 0.2995,
        'measure-knee-circ-incr': -0.172,
        'measure-lowerleg-height-incr': -0.4483,
        'measure-napetowaist-dist-incr': -0.1878,
        'measure-neck-circ-incr': 0.2791,
        'measure-neck-height-incr': 0.5111,
        'measure-shoulder-dist-incr': 0.72,
        'measure-thigh-circ-incr': 0.3193,
        'measure-upperleg-height-incr': -0.5496,
        'measure-waist-circ-incr': 0.1703,
        'measure-waisttohip-dist-incr': -0.1431,
        'neck-scale-depth-incr': 0.0428,
        'pelvis-tone-incr': -0.2208,
        'r-upperleg-scale-depth-incr': 0.0964,
        'r-upperleg-scale-horiz-incr': 0.2268,
        'stomach-tone-incr': -0.0365,
        'torso-muscle-dorsi-incr': 0.573,
        'torso-muscle-pectoral-incr': 0.28,
        'torso-scale-depth-incr': 0.4839,
        'torso-scale-horiz-incr': 0.6839,
        'torso-scale-vert-incr': -0.2424,
        'torso-vshape-incr': 0.5892,
    },
    'female': {
        'breast-dist-incr': 0.1384,
        'breast-point-incr': 0.3721,
        'breast-trans-up': -0.2647,
        'breast-volume-vert-up': -0.3058,
        'buttocks-volume-incr': 0.4125,
        'head-scale-depth-incr': 0.7306,
        'head-scale-horiz-incr': 0.4224,
        'head-scale-vert-incr': 0.3899,
        'hip-scale-depth-incr': 0.2589,
        'hip-scale-horiz-incr': 0.2353,
        'l-upperleg-scale-depth-incr': 0.4721,
        'l-upperleg-scale-horiz-incr': -0.3773,
        'measure-calf-circ-incr': 0.5487,
        'measure-frontchest-dist-incr': -0.2841,
        'measure-hips-circ-incr': -0.1193,
        'measure-knee-circ-incr': -0.5606,
        'measure-lowerleg-height-incr': -0.2163,
        'measure-napetowaist-dist-incr': -0.4208,
        'measure-neck-circ-incr': 0.2571,
        'measure-neck-height-incr': 0.4556,
        'measure-shoulder-dist-incr': 0.5701,
        'measure-thigh-circ-incr': -0.1502,
        'measure-underbust-circ-incr': -0.2561,
        'measure-upperleg-height-incr': -0.1173,
        'measure-waist-circ-incr': 0.1251,
        'measure-waisttohip-dist-incr': -0.3817,
        'neck-scale-depth-incr': 0.0251,
        'pelvis-tone-incr': -0.4261,
        'r-upperleg-scale-depth-incr': 0.4721,
        'r-upperleg-scale-horiz-incr': -0.3773,
        'stomach-tone-incr': -0.2119,
        'torso-muscle-dorsi-incr': -0.3469,
        'torso-scale-depth-incr': 0.381,
        'torso-scale-horiz-incr': 0.0269,
        'torso-scale-vert-incr': -0.4269,
        'torso-vshape-incr': -0.7519,
    },
}
# The two AFS p.30 rectus patterns, named here rather than beside _abs_pattern() because
# ORIGINAL_ANATOMY below has to be able to name one.
ABS_PATTERN_V1 = 'v1-preserved'
ABS_PATTERN_V2 = 'v2-afs-p30'
ABS_PATTERN_KEY = 'abs_pattern'
ABS_PATTERNS = (ABS_PATTERN_V1, ABS_PATTERN_V2)

# The sculpted definition layer — OUR delta, not MakeHuman's (their vocabulary has no
# rectus separation at all). Applied to the cage, so it is real hashed geometry that
# subdivision smooths into organic forms.
#
# EVERY KEY HERE IS PER-CHARACTER AND TRAVELS IN params.json, which is the whole point:
# a body that is not being re-issued carries no key, gets no layer, and keeps its hash
# and its gate. That is how originals/male can take the corrected abs pattern this wave
# while derived/cornelis — same abs_definition, out of scope — keeps v1 and keeps gating.
#   abs_definition  float   rectus relief amplitude. The male's 1.7 was tuned by eye
#                           against tight-crop renders. (Kept here rather than as an
#                           inline comment on the value: fit_proportions.py --bake
#                           REGENERATES this dict's literal from the fit JSON, so an
#                           inline note beside a number does not survive a re-issue.)
#   abs_pattern     str     which AFS p.30 diagram; absent = ABS_PATTERN_V1
#   bony_relief     float   geom/relief.py subcutaneous bone landmarks; absent = off
#   toe_declash     float   toe contraction that stops the shell crossing itself
# bony_relief 1.0 WAS geom/relief.py's own designed amplitude, not a fitted number.
# NEITHER ORIGINAL CARRIES IT ANY MORE — dropped in the FIFTH ISSUE 2026-08-07. The module
# is NOT deleted and NOT disabled: geom/relief.py is on disk, imported and working,
# _apply_bony_relief() still honours the key, ZYG_BONY_RELIEF still works, and any
# character that asks for the layer still gets it. These two bodies simply stopped asking,
# which is exactly the per-character contract this dict exists for — derived/abel and
# derived/cornelis never carried the key, so they keep their hashes and their gates.
#
# WHY, on three independent measurements:
#   1. LANDMARK RESOLUTION, re-measured on the FOURTH-issue recipes with relief.measure()'s
#      own resolvers, one null, same cut on both columns (the module's headline of
#      male 1/20 -> 3/20 was measured on the THIRD issue and the base body had since
#      changed):
#          male    4/20 -> 2/20   LOSES deltopectoral_triangle and epicondyle_med
#          female  3/20 -> 3/20   gains none, loses none
#      Both male losses are sign flips — epicondyle_med ridge/2 +8.04 mm c4.3 ->
#      point_only/1 -12.85 mm c-5.0, deltopectoral_triangle furrow/2 -9.76 ->
#      point_only/1 -21.75 — i.e. the probe latches onto a deeper adjacent furrow, which
#      is consistent with the layer's own 10.36 mm maximum displacement.
#   2. THE NULL IS SEED-DEPENDENT. Across 7 RNG seeds the shipped seed is the unique
#      minimum on both axes — 1 draw in 7 — and at the modal threshold the entire gain is
#      zero on both bodies.
#   3. ANTHROPOMETRY, which nobody had measured before and which is the biggest of the
#      three. On the male the layer was depressing the suprasternale landmark by 14.2 mm.
#      Changing NOTHING but dropping the key, on the fourth-issue recipe:
#          suprasternale_height_over_stature 0.8082 (z -1.54, p6.4) -> 0.8159 (z -0.45, p32.5)
#          cervicale_height_over_stature (the HOUSE restatement)      p5.0  -> p32.2
#      So most of the "torso compression" the fourth issue was blamed for was this layer,
#      not the neck and torso morph cuts. On the female it moves neither.
#      THE COST, stated because it is real and this pass does not fix it:
#          wrist_circumference_over_stature   male p0.8 -> p0.4,  female p0.5 -> p0.0
#      -0.71 sd on both. That ratio is survey_comparable and was ALREADY outside p5-p95
#      before this pass (anny's wrists are thin), and anny's morph vocabulary has no wrist
#      girth target at all, so there is no lever for it. Reported, not tuned around.
#
# toe_declash 0.0454 is MEASURED, not chosen: the delivered intra-component
# self-intersection count on originals/female goes 20 -> 0 between 0.0206 and 0.0209 on
# the template itself, and between 0.0360 and 0.0363 over an 11-recipe derivation
# envelope (macros +/-0.2-0.3 and stature 1.52-1.80 m, since a derived character inherits
# this layer). The shipped value is that envelope boundary with 25% headroom — a HOUSE
# margin, stated so it can be argued with. It moves at most 0.798 mm of cage.
ORIGINAL_ANATOMY = {
    'male': {
        'abs_definition': 1.7,
        'abs_pattern': ABS_PATTERN_V2,
    },
    'female': {
        'toe_declash': 0.0454,
    },
}

# The pinned GLB stays the 13,718-vert CAGE (the rig every fitter/animator works on).
# What the operator SEES is the Catmull-Clark subdivided limit surface with the cage's
# quad grid overlaid: smooth organic surface, readable geometry, no display faceting.
# Stills render at level 2 (facets are already sub-pixel at 1600px); the interactive
# 3D viewer gets level 3 (~877k quads / 1.75M tris) via the binary mesh3d format.
DISPLAY_SUBDIV = 2
MESH3D_SUBDIV = 3

# The anthropometric gate report ships INSIDE the character directory, so a character is
# a self-contained artefact: mesh, previews, recipe, and the verdict of the measurement
# that was run on it. Named here because _aux_hashes() hashes it.
ANTHRO_REPORT_FILE = 'anthro_report.json'

# Hashed aux files that refresh_previews() does NOT regenerate. A command may only
# re-record a hash for a file it actually rewrote; for everything else the recorded hash
# has to be VERIFIED first (see _aux_assert_unrewritten_intact). This tuple is the list
# refresh-previews must check rather than adopt.
AUX_NOT_REGENERATED_BY_REFRESH = (ANTHRO_REPORT_FILE,)
# ...and the mirror for `gate`, which regenerates params.json and the report but never
# re-renders a preview or mesh3d.bin.
AUX_REGENERATED_BY_GATE = ('params.json', ANTHRO_REPORT_FILE)
