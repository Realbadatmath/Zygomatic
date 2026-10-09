# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""mvconsist_band.py — THE BAND FOR THE MULTI-VIEW-CONSISTENCY GATE, AND NOTHING ELSE.

`geom/mvconsist.py` measures. It carries no threshold on purpose, and its `verdict()`
refuses to run without a band. This file is that band. It exists as a separate module so
that the numbers below have exactly one home, one derivation, and one date, and so that
changing them is a visible edit to a nine-line dict rather than an invisible edit to an
argument somewhere.

WHERE THE NUMBERS COME FROM
---------------------------
From two control sets and from nothing else:

    data/assets/mvconsist_controls/positive_textured   CEILING  48 Cycles renders of ONE
        rigid mesh (mesh_skeletons/originals/female/skeleton_female.glb) on a turntable,
        surface-locked procedural texture, one resolution. By construction these ARE 48
        projections of one 3D object, so SfM must converge on them.

    data/assets/mvconsist_controls/negative_mixed      FLOOR    48 real generated cells
        taken 8 apiece from SIX DIFFERENT characters. By construction these are NOT
        projections of one object. Whatever SfM extracts from them is what an incoherent
        subject scores.

THE FLOOR IS BUILT OUT OF THE CHARACTERS IT IS LATER USED TO JUDGE, AND THAT IS A REAL
DEPENDENCY — READ THIS BEFORE READING A THRESHOLD
--------------------------------------------------------------------------------------
This file used to say "Not from any character sheet" and to record
`assets_used: "NONE. No character contact sheet influenced any number in BAND."` Both were
false. The floor control is 48 cells drawn 8 apiece from six characters, and FIVE of those
six — c3345deb5bde, f60a454aa472, e58b9137bdc5, dc1669d1afdb, d835e0711f41 — are the
characters this band is then applied to. 40 of the 48 floor cells belong to sheets the band
grades. Both thresholds are the midpoint between the ceiling and that floor, so a character
whose own cells happen to be unusually matchable raises the floor and therefore the bar for
everyone else, and one whose cells are noisy lowers it and makes the gate easier for itself.

It was not constructible any other way: only six characters have a complete 48-cell sheet,
and a floor made of fewer than six identities is a weaker negative. So the dependency stays,
and instead of being denied it is BOUNDED BY MEASUREMENT. See
`DERIVATION['floor_contamination']`: for each character the floor was rebuilt with that
character's 8 cells replaced by the same 8 angle indices from a character the band never
judges, holding n, the angle set and the resolution mix identical, and re-measured. The
result is in that dict, and the size of the effect — not the absence of it — is what
licenses using this band.

Everything else about the ordering guarantee stands: the derivation rule was written down
BEFORE the floor was measured (see `DERIVATION['rule_preregistered_before_floor_was_run']`
and BAND_RULE_PREREGISTERED.md), and no threshold was chosen, checked or adjusted against
any character's SCORE.

THE MEASUREMENTS (2026-08-07, pycolmap 4.1.1 / COLMAP 4.1.1 commit a0d785f, CPU, no CUDA)
-----------------------------------------------------------------------------------------
Three repeats of each set, identical settings throughout — seed=0, quality='high',
camera_grouping='per_resolution', max_image_size=1600, num_threads=-1,
pattern='cell_[0-9][0-9].png'. Repeats matter because the instrument is not deterministic:
its own author could not remove thread-scheduling and mapper-growth-order nondeterminism,
so a band drawn from a single run would be drawn partly from noise.

  field                   positive_textured (n=3)      negative_mixed (n=3)
  registration_rate       1.0      1.0      1.0        0.125    0.125    0.125
  n_registered            48       48       48         6        6        6
  n_models                1        1        1          1        1        1
  mean_track_length       7.5485   7.5439   7.5438     3.4226   3.4315   3.3383
  mean_reproj_error_px    0.7497   0.7471   0.7478     1.1796   1.1817   1.1596
  n_points3D              30737    30761    30763      433      445      467
  n_features_mean         5846.1   5846.1   5846.1     5008.6   5008.6   5008.6

THE BAND
--------
    registration_rate  >= 0.56      midpoint of [1.0 worst-positive .. 0.125 best-negative]
    mean_track_length  >= 5.48      midpoint of [7.5438 worst-positive .. 3.4315 best-neg]

Two fields. That is not laziness; it is what survived the rule. The rejections are the
interesting part and they are recorded below, because a band is defined as much by what it
refused to measure as by what it measures.

WHAT WAS REJECTED, AND WHY
--------------------------
n_models — REJECTED, ENVELOPES OVERLAP. The intuition "a consistent set reconstructs as ONE
    model, an inconsistent set shatters" is wrong at this floor. negative_mixed returned
    n_models=1 in all three runs, identically to the ceiling. It did not shatter; it built
    one small 6-camera model and abandoned the other 42 images. A band on n_models would
    have passed the floor. This is the single most valuable thing the negative control
    bought, and it would have been invisible without one.

mean_reproj_error_px — REJECTED BY CONSTRUCTION, before its numbers were looked at. It is a
    fit-quality statistic conditioned on whichever cameras happened to register, so a set
    that registers a handful of easy views can post a BETTER error than one that registers
    all 48. The control set proves this is not hypothetical: positive_untextured run 1
    registered 3 of 48 cameras — a total failure — and scored 0.7506 px, indistinguishable
    from the ceiling's 0.7471-0.7497 and better than the floor's 1.16-1.18. Banding on it
    would have graded a 3-camera collapse as ceiling-grade. Reported, never banded.

n_points3D — REJECTED. mvconsist.py's author measured it moving 4.9x between identical
    runs on a non-converging set. A band field has to be stable under the instrument's own
    nondeterminism, and this one is not.

n_registered — REJECTED AS REDUNDANT. At n_images=48 it is registration_rate x 48. Banding
    both would double-count one piece of evidence. registration_rate is kept because it is
    the one that survives a set of a different size.

n_features_mean — NOT A BAND FIELD, DELIBERATELY. It does not measure consistency at all;
    it measures whether there was anything to match. It is the disambiguator you read
    ALONGSIDE a fail, never a criterion. See `interpret()`.

THE THIRD CONTROL, WHICH IS NOT IN THE BAND
-------------------------------------------
    data/assets/mvconsist_controls/positive_untextured — the same 48 turntable renders of
    the same rigid mesh with the texture removed. Geometrically it is a positive: it really
    is one object. It carries 127.9 SIFT features per image against the textured set's
    5846.1, and it scores 3, 32, 32 registered cameras over three identical runs.

It was excluded from the derivation before the floor was run, and the reason is worth
stating plainly: including it would have dragged the band down to the floor for a reason
that has nothing to do with 3D consistency. Its job is diagnostic. It establishes that this
gate is a JOINT test of "the images have features" AND "the features belong to one object",
that a featureless set fails it, and therefore that a failure is only attributable to
geometry when n_features_mean is high. It also demonstrates the instrument's worst-case
instability: 3 vs 32 registered cameras from the same input, same seed, same settings.

CALIBRATION SEPARATION
----------------------
    registration_rate  ceiling 8.00x the floor   (1.0    vs 0.125)
    mean_track_length  ceiling 2.20x the floor   (7.5438 vs 3.4315)
Within-set spread across three repeats is 0.0 and 0.0047 (ceiling) and 0.0 and 0.0932
(floor) — between 24x and 96x smaller than the gaps the thresholds sit in. The band is not
resolving noise.

HOW TO USE IT

    from zyg_workflows.geom import mvconsist
    from zyg_workflows.geom.mvconsist_band import BAND, verdict, interpret
    r = mvconsist.measure(cells_dir, pattern='cell_[0-9][0-9].png', quality='high',
                          camera_grouping='per_resolution', seed=0)
    v = verdict(r)                 # {'verdict': 'pass'|'fail'|'unmeasured', ...}
    print(interpret(r, v))         # what a fail is and is not evidence of

THE BAND IS ONLY VALID AT THE SETTINGS IT WAS MEASURED AT. `verdict()` checks this and
returns 'unmeasured' if the result was produced with different settings, rather than
comparing numbers that are not comparable. max_image_size changes the feature count and the
pixel units of the reprojection error; camera_grouping changes registration outright (the
mvconsist author measured 3 / 10-12 / 18 of 48 on one sheet under shared / per-resolution /
per-image); quality changes the SIFT budget.

IT IS ALSO ONLY VALID AT THE IMAGE COUNT IT WAS MEASURED AT, and that is not a formality:
the same ceiling set scores mean_track_length 7.5438 on 48 cells and 6.7095 on 39 of those
same cells. Both verdict functions refuse a result whose n_images is not the one their band
was drawn at. That is why SUBSET39_BAND exists as its own derivation rather than as a
footnote on this one.

A NOTE ON WHAT THIS BAND CANNOT SEE
-----------------------------------
The ceiling control is a rigid, nude, hairless mesh in rest pose on a flat background at one
resolution, and a real 48-cell sheet is none of those things (mv_render.py documents eight
such differences as D1-D8). Every one of them makes the real problem harder for reasons that
are not identity drift: non-rigid hair and cloth, changing expression, A/T/walking poses, a
regenerated backdrop, three resolutions in one folder, and a scale jump between portrait and
full-body cells. This band therefore CANNOT attribute a failure to identity drift on its own.
It bounds the problem: a set at or below the floor is indistinguishable from six different
people, and the confounds have to be excluded separately (the 39 same-resolution cells are
the natural subset for that — see FRAMING_CONFOUNDS).

DO NOT MOVE THESE NUMBERS TO MAKE AN ASSET PASS. If an asset fails, the failure is the
result. The only legitimate reason to change the band is a new or corrected CONTROL
measurement, and any such change must rewrite DERIVATION with new control numbers, a new
date, and the rule re-applied unchanged.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from zyg_workflows.geom import mvconsist as _mvconsist

__all__ = [
    'BAND_N_IMAGES',
    'BAND',
    'SUBSET39_BAND',
    'SUBSET39_CELLS',
    'SUBSET39_DERIVATION',
    'REQUIRED_SETTINGS',
    'DERIVATION',
    'FRAMING_CONFOUNDS',
    'verdict',
    'verdict_subset39',
    'interpret',
]


# ---------------------------------------------------------------------------
# The band. Two entries. Do not add a third without a control that justifies it.
# ---------------------------------------------------------------------------

# The image count BAND was derived at. Not decoration: see the guard in verdict().
BAND_N_IMAGES = 48

BAND: Dict[str, Dict[str, float]] = {
    # midpoint of worst-ceiling 1.0 and best-floor 0.125, rounded DOWN (away from the
    # positives, so rounding can only ever make the gate easier to pass, never harder).
    'registration_rate': {'min': 0.56},
    # midpoint of worst-ceiling 7.5438 and best-floor 3.4315 = 5.48765, rounded DOWN.
    'mean_track_length': {'min': 5.48},
}


# The band is a set of numbers in the units of one particular measurement configuration.
# Applying it to a result produced any other way is comparing two different instruments.
#
# EVERY ONE OF THESE MUST BE PRESENT IN THE RESULT. A missing key used to be treated as
# compatible (`if got is not None and got != want`), so a truncated, older or renamed result
# was graded against the band with nothing to compare — `verdict({'status':'ok',
# 'registration_rate':1.0,'mean_track_length':9.9})` came back 'pass' with no complaint that
# quality, camera_grouping, max_image_size and n_images were all absent. For a module whose
# whole contract is that a result it cannot compare must come back 'unmeasured', fail-open on
# absence is the wrong default. Absence is now a mismatch.
REQUIRED_SETTINGS: Dict[str, Any] = {
    'quality': 'high',
    'camera_grouping': 'shared_per_resolution',  # the value measure() reports for 'per_resolution'
    'max_image_size': 1600,
    # pinned in DERIVATION['settings'] and previously not checked at all, so a measurement
    # taken with a different glob (a different subset of the same directory!) was accepted
    # unless the glob happened to change n_images away from 48.
    'pattern': 'cell_[0-9][0-9].png',
    'seed': 0,
}

# num_threads is deliberately NOT required. It is pinned at -1 in DERIVATION['settings'], but
# -1 means "every core on this machine" and that is a different number on a different
# machine; the module already records thread scheduling as the instrument's chief
# uncontrolled nondeterminism (result['nondeterminism']). Requiring it would refuse valid
# measurements for a setting that is not reproducible in the first place.
NOT_REQUIRED_SETTINGS_AND_WHY: Dict[str, str] = {
    'num_threads': "-1 means 'all cores', which is machine-dependent; recorded as "
    'nondeterminism, not as a comparability condition',
}


DERIVATION: Dict[str, Any] = {
    'date': '2026-08-07',
    'instrument': {
        'module': 'geom/mvconsist.py',
        'pycolmap': '4.1.1',
        'colmap': 'COLMAP 4.1.1, commit a0d785f on 2026-07-17 without CUDA',
        'has_cuda': False,
    },
    'settings': {
        'seed': 0,
        'quality': 'high',
        'camera_grouping': 'per_resolution',
        'max_image_size': 1600,
        'num_threads': -1,
        'pattern': 'cell_[0-9][0-9].png',
        'repeats_per_set': 3,
    },
    'raw_results_on_disk': 'data/assets/anthro_reports/mvconsist/{all48,subset39}/*.json — '
    'every run behind every number in this file, plus '
    'BAND_RULE_PREREGISTERED.md, the rule as written before the floor '
    'was measured.',
    'controls_used': {
        'ceiling': 'data/assets/mvconsist_controls/positive_textured',
        'floor': 'data/assets/mvconsist_controls/negative_mixed',
    },
    'controls_measured_but_excluded': {
        'data/assets/mvconsist_controls/positive_untextured': 'geometrically a positive (one rigid object) but feature-starved (127.9 SIFT '
        "features/image vs the ceiling's 5846.1). Excluded before the floor was run. "
        'Including it would set the band from a feature famine rather than from 3D '
        'inconsistency. Retained as the diagnostic that makes a fail interpretable.'
    },
    'assets_used': 'THE FLOOR CONTROL IS BUILT FROM CHARACTER CONTACT SHEETS, AND FIVE OF ITS SIX '
    'CHARACTERS ARE CHARACTERS THIS BAND JUDGES. data/assets/mvconsist_controls/'
    'negative_mixed is 48 cells, 8 apiece from c3345deb5bde, f60a454aa472, '
    'e58b9137bdc5, dc1669d1afdb, d835e0711f41 and d00967bf3bb6; only the last is never '
    'graded, so 40 of the 48 cells belong to sheets this band is applied to. Both '
    'thresholds are the midpoint between the ceiling and that floor, so those cells '
    "set the bar. This field previously read 'NONE. No character contact sheet "
    "influenced any number in BAND', which was false. What IS true: no character's "
    'SCORE was ever consulted, and the derivation rule was fixed in writing before the '
    'floor was measured. The size of the dependency is measured in '
    "'floor_contamination' below rather than asserted away.",
    'floor_contamination': {
        'why_it_could_not_be_removed': 'an uncontaminated floor needs six complete 48-cell sheets from characters this '
        'band never grades, and only six complete sheets exist in total. A floor built '
        'from fewer identities is a weaker negative, which would be a worse problem.',
        'experiment': 'LEAVE-ONE-CHARACTER-OUT. For each of the six, the floor was rebuilt with that '
        "character's 8 cells replaced by the SAME 8 angle indices from d00967bf3bb6 (the "
        'one character the band never judges; for d00967bf3bb6 itself, from '
        'c3345deb5bde). n stays 48, the angle set and the three-resolution mix are '
        'identical, and the only thing that changes is that the character contributed '
        'nothing. 2 repeats each, identical settings. Runs on disk: '
        'data/assets/anthro_reports/mvconsist/loo_floor/without_<char>.r{0,1}.json; '
        'analysis in FLOOR_CONTAMINATION.json beside it.',
        'measured_2026_08_08': {
            'shipped_floor': {
                'best_registration_rate': 0.125,
                'best_mean_track_length': 3.4315,
                'thresholds': [0.56, 5.48],
            },
            'without_c3345deb5bde': {'floor': [0.125, 3.4579], 'thresholds': [0.56, 5.50]},
            'without_d835e0711f41': {'floor': [0.125, 3.4279], 'thresholds': [0.56, 5.48]},
            'without_dc1669d1afdb': {'floor': [0.125, 3.4605], 'thresholds': [0.56, 5.50]},
            'without_e58b9137bdc5': {'floor': [0.0625, 2.6381], 'thresholds': [0.53, 5.09]},
            'without_f60a454aa472': {'floor': [0.125, 3.4215], 'thresholds': [0.56, 5.48]},
            'without_d00967bf3bb6': {'floor': [0.125, 3.4215], 'thresholds': [0.56, 5.48]},
            'threshold_envelope': {'registration_rate': [0.53, 0.56], 'mean_track_length': [5.09, 5.50]},
        },
        'what_it_shows': 'FIVE of the six characters contribute essentially nothing: dropping any of them '
        "leaves registration_rate's threshold at 0.56 exactly and moves "
        "mean_track_length's by at most +0.02, INSIDE the floor control's own 0.0932 "
        "repeat spread. ONE does not. Dropping e58b9137bdc5 halves the floor's "
        'registration rate (0.125 -> 0.0625) and takes its mean track length from 3.4315 '
        'to 2.6381, moving the thresholds to 0.53 and 5.09. Its 8 cells are carrying the '
        'floor.',
        'consequence_for_each_character': 'Re-graded at EVERY threshold in the envelope above, four of the five judged '
        'characters return the same verdict at every threshold and every repeat — '
        'c3345deb5bde, d835e0711f41, dc1669d1afdb and f60a454aa472 all fail throughout, '
        'and by margins far larger than the envelope. e58b9137bdc5 DOES NOT: it clears '
        'registration_rate at 0.7083 either way, and its mean_track_length of 5.0225 and '
        '5.1607 straddles its OWN leave-one-out threshold of 5.09 while sitting clearly '
        "below the shipped 5.48. So e58b9137bdc5's unambiguous fail is partly produced "
        "by e58b9137bdc5's own cells being in the floor that judges it. Report it as "
        'borderline-and-contaminated, not as a clean fail, and do not rank it against '
        'the other four.',
        'what_would_fix_it': 'a seventh, eighth ... character sheet from identities that are never graded, or '
        'a floor built from a held-out identity pool. Until then this dict is the '
        'correction that must travel with any threshold quoted from this file.',
    },
    'rule_preregistered_before_floor_was_run': [
        'candidates: registration_rate, n_models, mean_track_length, mean_reproj_error_px, n_registered',
        'n_points3D excluded: measured to move 4.9x between identical runs',
        'positive_untextured excluded: feature famine is not 3D inconsistency',
        'a field qualifies only if the ceiling and floor envelopes over the repeats are DISJOINT',
        'threshold = arithmetic midpoint of the two facing envelope edges; for an integer '
        "count field, the ceiling's own worst value",
        'mean_reproj_error_px dropped by construction even if it separates: it is conditioned '
        'on which cameras registered',
        'every threshold rounded AWAY from the positives so rounding cannot manufacture a failure',
        'once written, frozen',
    ],
    'control_measurements': {
        'positive_textured': {
            'n_repeats': 3,
            'registration_rate': [1.0, 1.0, 1.0],
            'n_registered': [48, 48, 48],
            'n_models': [1, 1, 1],
            'model_sizes': [[48], [48], [48]],
            'mean_track_length': [7.5485, 7.5439, 7.5438],
            'mean_reproj_error_px': [0.7497, 0.7471, 0.7478],
            'n_points3D': [30737, 30761, 30763],
            'n_features_mean': [5846.1, 5846.1, 5846.1],
            'n_parallax_pairs_of_1128': [789, 789, 789],
            'elapsed_s': [88.4, 102.0, 89.2],
        },
        'negative_mixed': {
            'n_repeats': 3,
            'registration_rate': [0.125, 0.125, 0.125],
            'n_registered': [6, 6, 6],
            'n_models': [1, 1, 1],
            'model_sizes': [[6], [6], [6]],
            'mean_track_length': [3.4226, 3.4315, 3.3383],
            'mean_reproj_error_px': [1.1796, 1.1817, 1.1596],
            'n_points3D': [433, 445, 467],
            'n_features_mean': [5008.6, 5008.6, 5008.6],
            'n_parallax_pairs_of_1128': [36, 36, 36],
            'elapsed_s': [24.2, 26.9, 25.6],
        },
        'positive_untextured': {
            'n_repeats': 3,
            'registration_rate': [0.666667, 0.0625, 0.666667],
            'n_registered': [32, 3, 32],
            'n_models': [2, 1, 2],
            'model_sizes': [[32, 3], [3], [32, 3]],
            'mean_track_length': [4.301, 2.3182, 4.3804],
            'mean_reproj_error_px': [1.0407, 0.7506, 1.0801],
            'n_points3D': [588, 110, 581],
            'n_features_mean': [127.9, 127.9, 127.9],
            'n_parallax_pairs_of_1128': [132, 136, 136],
            'elapsed_s': [3.4, 2.5, 3.4],
        },
    },
    'fields_rejected': {
        'n_models': 'envelopes overlap: ceiling [1,1] and floor [1,1] are identical. The '
        'floor did not shatter into pieces, it built one 6-camera model and '
        'gave up on 42 images. A band on n_models would pass the floor.',
        'mean_reproj_error_px': 'rejected by construction (pre-registered). Empirically '
        'vindicated: positive_untextured run 1 registered 3 of 48 '
        'cameras and scored 0.7506 px, better than the floor and '
        'level with the ceiling.',
        'n_points3D': "unstable under the instrument's own nondeterminism (4.9x).",
        'n_registered': 'redundant with registration_rate at a fixed n_images.',
        'n_features_mean': 'not a consistency measure; it is the disambiguator read alongside a fail. See interpret().',
    },
    'separation': {
        'registration_rate': {
            'ceiling_worst': 1.0,
            'floor_best': 0.125,
            'midpoint': 0.5625,
            'threshold': 0.56,
            'ceiling_spread': 0.0,
            'floor_spread': 0.0,
        },
        'mean_track_length': {
            'ceiling_worst': 7.5438,
            'floor_best': 3.4315,
            'midpoint': 5.48765,
            'threshold': 5.48,
            'ceiling_spread': 0.0047,
            'floor_spread': 0.0932,
        },
    },
}


# Everything the ceiling control does NOT model. A real sheet that fails is failing for some
# combination of these AND identity drift, and this band cannot separate them by itself.
FRAMING_CONFOUNDS: Dict[str, str] = {
    'D1_mixed_framing': 'the real sheet mixes ~26 head-and-shoulders, 10 medium, 3 close-up '
    'and 9 full-body cells; the ceiling is one framing throughout. The '
    'scale jump is a plausible SfM failure mode on its own.',
    'D2_angular_sampling': 'uniform 7.5 deg at 0 deg elevation (ceiling) vs a hand-written, '
    'non-uniform azimuth/elevation list with duplicates (real).',
    'D3_pose': 'the ceiling is rigid in rest pose for all 48 frames; the real cells include '
    'A-pose, T-pose, a walking pose and varying expression. The real subject is '
    'not rigid even when the generator behaves.',
    'D4_background': 'flat featureless backdrop (ceiling) vs a mottled backdrop regenerated '
    'per cell (real) — features that are neither static nor on the subject.',
    'D5_subject': 'nude, bald, no facial detail (ceiling) vs clothed and haired with eyes and '
    'mouth (real): no hair/cloth non-rigidity in the control, and none of the '
    'strongest real SIFT features either.',
    'D6_lens': 'explicit 85 mm at 1.09 m (ceiling) vs no declared or verified intrinsics at all (real).',
    'D8_resolution': 'the ceiling is 1024x1152 throughout; every real sheet is 39 cells at '
    '1024x1152, 6 at 832x1216 (cells 24-29) and 3 at 1024x1024 (cells '
    '45-47). The floor control reproduces this, the ceiling does not.',
    'recommended_confound_subset': 'cells 0-23 and 30-44 (39 cells, all 1024x1152) removes '
    'D8 entirely and most of D1. Compare against a band '
    'derived from the SAME subset of the controls, never '
    'against this one.',
}


# ---------------------------------------------------------------------------
# The confound-controlled band: the 39 cells every sheet renders at 1024x1152.
# ---------------------------------------------------------------------------
#
# BAND above is measured on all 48 cells, and on a real sheet those 48 cells span three
# resolutions and four framings (FRAMING_CONFOUNDS D8 and D1). A failure there could in
# principle be caused by the framing rather than by the subject. This second band removes
# that possibility by dropping cells 24-29 (the 832x1216 full-body block) and 45-47 (the
# 1024x1024 T-pose block), leaving 39 cells that are all one resolution.
#
# It is derived by applying the SAME pre-registered rule to the SAME two controls reduced
# to the SAME 39 cell indices. No character SCORE entered it — but the floor is the same
# six-character floor as BAND's, so read the contamination note at the top of this file and
# DERIVATION['floor_contamination'] before quoting either threshold.
#
#   field              ceiling (n=3)               floor (n=3)
#   registration_rate  1.0    1.0    1.0           0.128205 0.128205 0.128205
#   n_registered       39     39     39            5        5        5
#   n_models           1      1      1             1        1        1
#   mean_track_length  6.7155 6.7095 6.7115        3.0721   3.0507   3.0721
#   n_features_mean    5796.6 5796.6 5796.6        5855.9   5855.9   5855.9
#
#   registration_rate  midpoint(1.0, 0.128205) = 0.5641  -> 0.56  (rounded down)
#   mean_track_length  midpoint(6.7095, 3.0721) = 4.8908 -> 4.89  (rounded down)
#
# A THIRD REPEAT OF BOTH SUBSET CONTROLS WAS ADDED AFTER THE FIRST DELIVERY (the first
# derivation had two apiece, against three for BAND). It moved neither threshold: the
# ceiling's worst mean_track_length is still 6.7095 and the floor's best is still 3.0721,
# and registration_rate did not move at all on either control. Rule 8 says the band is
# frozen except on a new or corrected CONTROL measurement with the rule re-applied
# unchanged; that is what this is, and the rule re-applied unchanged returns the same two
# numbers.
#
# HONESTY NOTE ON ORDERING. The 48-cell band was written before any character was
# measured. This one was not: by the time the subset controls finished, two character
# subset results were already visible. The rule is mechanical and was fixed in advance, so
# there was no discretion left to exercise — the two thresholds follow from the four
# control numbers above by arithmetic — but the ordering is weaker and it is recorded here
# rather than glossed over. Anyone who wants the stronger guarantee should re-derive from
# fresh control renders before looking at anything else.
#
# n_models is again NOT banded: the floor returned 1 model here too.

SUBSET39_CELLS = tuple(i for i in range(48) if i not in set(range(24, 30)) | {45, 46, 47})

SUBSET39_BAND: Dict[str, Dict[str, float]] = {
    'registration_rate': {'min': 0.56},
    'mean_track_length': {'min': 4.89},
}

SUBSET39_DERIVATION: Dict[str, Any] = {
    'date': '2026-08-07',
    'why': 'removes framing confounds D8 (three resolutions in one folder) and most of D1 '
    '(the portrait/full-body scale jump) by using only the 39 cells that every sheet '
    'renders at 1024x1152.',
    'cells': list(SUBSET39_CELLS),
    'cells_dropped': [24, 25, 26, 27, 28, 29, 45, 46, 47],
    'settings': dict(DERIVATION['settings'], repeats_per_set=3),
    'assets_used': "SEE DERIVATION['assets_used'] AND DERIVATION['floor_contamination']. "
    'The same six-character floor, reduced to the same 39 indices, so the '
    'same dependency applies. No character SCORE entered either threshold.',
    'rule': "identical to DERIVATION['rule_preregistered_before_floor_was_run'], applied unchanged",
    'control_measurements': {
        'positive_textured_39': {
            'n_repeats': 3,
            'registration_rate': [1.0, 1.0, 1.0],
            'n_registered': [39, 39, 39],
            'n_models': [1, 1, 1],
            'mean_track_length': [6.7155, 6.7095, 6.7115],
            'mean_reproj_error_px': [0.7108, 0.7110, 0.7103],
            'n_features_mean': [5796.6, 5796.6, 5796.6],
        },
        'negative_mixed_39': {
            'n_repeats': 3,
            'registration_rate': [0.128205, 0.128205, 0.128205],
            'n_registered': [5, 5, 5],
            'n_models': [1, 1, 1],
            'mean_track_length': [3.0721, 3.0507, 3.0721],
            'mean_reproj_error_px': [1.1866, 1.2086, 1.1866],
            'n_features_mean': [5855.9, 5855.9, 5855.9],
        },
    },
    'third_repeat_added_after_first_delivery': 'the first derivation used 2 repeats per '
    'control. A third was added; it moved neither threshold (ceiling worst track still '
    '6.7095, floor best still 3.0721, registration_rate unmoved on both). Rule 8 permits '
    'exactly this: a new CONTROL measurement with the rule re-applied unchanged.',
    'ordering_caveat': 'two character subset results were already visible when this band was '
    "written; the 48-cell band's were not. The rule is arithmetic and was "
    'fixed in advance, so no discretion was available, but the guarantee '
    'is weaker and is stated rather than hidden.',
    'how_to_report_a_character_against_this_band': "NEVER FROM ONE RUN. On the 39-cell subset the instrument's own spread on a failing "
    'sheet is enormous: f60a454aa472 measured registration_rate 0.0513, 0.1538 and '
    '0.2821 over three identical-config runs — a 5.5x span that straddles the 0.128205 '
    'floor — and c3345deb5bde spanned 0.0769-0.3333. A single run supports no ranking, '
    "no 'below the floor' claim and no delta. The per-character envelopes, and the only "
    'statements that survive across every repeat, are in '
    'data/assets/anthro_reports/mvconsist/RESULTS_WITH_RANGES.json, which is generated '
    'from the runs on disk rather than typed in.',
}


_ABSENT = object()


def _settings_mismatch(result: Dict[str, Any]) -> Optional[str]:
    """Return a description of any setting that makes the band inapplicable, else None.

    ABSENT IS A MISMATCH. See REQUIRED_SETTINGS for why: a result that does not say how it
    was measured cannot be compared with one that does, and treating silence as agreement
    turned this guard into a formality that any incomplete dict walked through."""
    bad = []
    for key, want in REQUIRED_SETTINGS.items():
        if key == 'max_image_size':
            got = (result.get('image_size') or {}).get('max_image_size_requested', _ABSENT)
        else:
            got = result.get(key, _ABSENT)
        if got is _ABSENT or got is None:
            bad.append(
                '%s is ABSENT from the result (band derived at %r); a result that '
                'does not record how it was measured cannot be compared with one '
                'that does' % (key, want)
            )
        elif got != want:
            bad.append('%s=%r (band derived at %r)' % (key, got, want))
    return '; '.join(bad) if bad else None


def verdict(result: Dict[str, Any]) -> Dict[str, Any]:
    """Apply BAND to a mvconsist.measure() result.

    Thin on purpose: all the judging logic — including the rule that no_model and degenerate
    fail by construction rather than returning 'unmeasured' — lives in mvconsist.verdict()
    and is not duplicated here. This function's only additions are the band itself and a
    refusal to apply it to a result measured at different settings.
    """
    # BOTH banded fields depend on how many images were fed in, and the controls prove it
    # rather than assume it: the same ceiling set measured on 48 cells gives track 7.5438 and
    # on 39 of those same cells gives 6.7095. A band drawn at n=48 is not a band at n=39.
    # ABSENT n_images IS ALSO A REFUSAL. The guard used to skip when the key was missing,
    # so a result that never said how many images it measured was graded against a band
    # whose whole validity is conditional on that count.
    n = result.get('n_images')
    if n != BAND_N_IMAGES:
        return {
            'verdict': 'unmeasured',
            'checks': [],
            'reason': 'BAND is derived at n_images=%d and this result has %s. mean_track_length '
            'falls with the image count on the ceiling control itself (7.5438 at 48, '
            '6.7095 at 39), so applying it here would compare two different '
            'measurements. Use SUBSET39_BAND for the 39-cell subset, or derive a '
            'band at your n from the controls.' % (BAND_N_IMAGES, n),
            'band': dict(BAND),
        }
    mismatch = _settings_mismatch(result)
    if mismatch:
        return {
            'verdict': 'unmeasured',
            'checks': [],
            'reason': 'the result was produced at settings the band was not derived at, so '
            'the numbers are not comparable: %s. Re-measure at the settings in '
            "DERIVATION['settings'] or derive a band at yours." % mismatch,
            'band': dict(BAND),
        }
    out = _mvconsist.verdict(result, BAND)
    out['band'] = dict(BAND)
    return out


def verdict_subset39(result: Dict[str, Any]) -> Dict[str, Any]:
    """Apply SUBSET39_BAND. The result MUST come from a measurement of the 39 cells listed in
    SUBSET39_CELLS — this function cannot verify which cells were fed in, so it checks the
    one thing it can (n_images == 39) and refuses otherwise rather than silently comparing a
    48-cell number against a 39-cell band."""
    n = result.get('n_images')
    if n != len(SUBSET39_CELLS):
        return {
            'verdict': 'unmeasured',
            'checks': [],
            'reason': 'SUBSET39_BAND is derived on %d images and this result has %s. '
            'Measure the directory restricted to SUBSET39_CELLS, or use '
            'verdict() with the 48-cell BAND.' % (len(SUBSET39_CELLS), n),
            'band': dict(SUBSET39_BAND),
        }
    mismatch = _settings_mismatch(result)
    if mismatch:
        return {'verdict': 'unmeasured', 'checks': [], 'reason': mismatch, 'band': dict(SUBSET39_BAND)}
    out = _mvconsist.verdict(result, SUBSET39_BAND)
    out['band'] = dict(SUBSET39_BAND)
    return out


def interpret(result: Dict[str, Any], v: Optional[Dict[str, Any]] = None) -> str:
    """Prose stating what this particular verdict is, and is not, evidence of.

    A bare 'fail' is routinely over-read as 'the character is inconsistent'. It is not that
    on its own — see FRAMING_CONFOUNDS — and it can also be caused by having no features to
    match at all, or by the views carrying no baseline between them, which are different
    defects with different fixes. This function reads n_features_mean and n_parallax_pairs to
    say which case is in front of you.

    EVERY BOUNDARY IT USES IS A CONTROL MEASUREMENT. It used to carry `feats < famine * 4`,
    a 4x multiplier that appeared in no derivation, no pre-registration document and no
    control — inside the one module whose stated thesis is that thresholds come from controls
    and nowhere else. The measured anchors are 127.9 (the untextured famine control), 5008.6
    (the negative_mixed floor, which fails for GEOMETRIC reasons at that feature density and
    so proves ~5000 features is not a famine) and 5846.1 (the textured ceiling). Between
    127.9 and 5008.6 nothing was ever measured, and this function now says so instead of
    drawing a line through it.
    """
    if v is None:
        v = verdict(result)
    tag = v.get('verdict')
    feats = result.get('n_features_mean')
    ceiling_feats = DERIVATION['control_measurements']['positive_textured']['n_features_mean'][0]
    famine = DERIVATION['control_measurements']['positive_untextured']['n_features_mean'][0]
    # the floor control's own feature density: a MEASURED point at which failure is
    # geometric, not a famine
    floor_feats = DERIVATION['control_measurements']['negative_mixed']['n_features_mean'][0]
    parallax = result.get('n_parallax_pairs')
    verified = result.get('n_verified_pairs')

    if tag == 'unmeasured':
        return 'UNMEASURED — no verdict. %s' % v.get('reason')

    if tag == 'pass':
        return (
            'PASS — the set reconstructs as one 3D object at or above the midpoint between '
            'a rigid-mesh turntable and six different people. %s. This says the geometry is '
            'mutually consistent; it says nothing about whether the person depicted is the '
            'person that was asked for.' % v.get('reason')
        )

    lines = ['FAIL — %s.' % v.get('reason')]

    # (1) NO BASELINE IS NOT DISAGREEMENT. Read this BEFORE the feature count. A set whose
    #     pairs all verify as planar_or_panoramic has n_parallax_pairs = 0: the views agreed
    #     so completely that no relative pose could be estimated from them, which is the
    #     opposite of "it did not agree" and has a different fix. Fed 48 byte-identical
    #     copies of one control frame, this function used to report "there was plenty to
    #     match and it did not agree. That rules out the one benign explanation" — of a set
    #     that agreed perfectly. The measurement was right; the prose was inverted.
    no_baseline = parallax is not None and parallax == 0
    if parallax is None:
        lines.append(
            'n_parallax_pairs is missing, so it cannot be said whether the views '
            'carry any baseline at all; do not attribute this failure without it.'
        )
    elif no_baseline:
        cfg = result.get('two_view_configs') or {}
        lines.append(
            'n_parallax_pairs=0 of %s verified pair(s)%s: NOT ONE pair of these images '
            'carries a usable baseline. There is nothing here for SfM to triangulate, and '
            'that is a statement about the CAMERAS, not about the subject. This is what '
            'duplicate or near-duplicate views look like, and it is the opposite of '
            'disagreement — the views agreed too completely to be told apart. Fix the '
            'capture (or the set construction) before reading anything else below.'
            % (verified if verified is not None else '?', (' (two_view_configs %r)' % cfg) if cfg else '')
        )

    # (2) THE FEATURE ANCHORS, and only the measured ones.
    if feats is None:
        lines.append(
            'n_features_mean is missing, so the feature-famine case cannot be ruled '
            'out and the failure cannot be attributed.'
        )
    elif feats <= famine:
        lines.append(
            'n_features_mean=%.1f is at or below the FEATURE-FAMINE control (%.1f), where '
            'the instrument failed on 48 projections of one rigid object. This failure is an '
            'image-content failure — there was little to match — and is NOT evidence about '
            '3D consistency.' % (feats, famine)
        )
    elif feats < floor_feats:
        # The uncalibrated gap. 127.9 and 5008.6 are the two nearest measured points and
        # nothing between them was ever measured, so no attribution is available here.
        lines.append(
            'n_features_mean=%.1f falls BETWEEN the two measured anchors — the feature-'
            'famine control at %.1f and the negative_mixed floor at %.1f — and nothing in '
            'that gap has ever been measured. This module therefore CANNOT say whether the '
            'failure is a feature famine or a geometric one. Render a control at this '
            'feature density, or read n_parallax_pairs (%s of %s verified pairs) and decide '
            'on the evidence rather than on a line drawn through an uncalibrated region.'
            % (
                feats,
                famine,
                floor_feats,
                parallax if parallax is not None else '?',
                verified if verified is not None else '?',
            )
        )
    else:
        anchor = (
            "at or above the ceiling control's %.1f" % ceiling_feats
            if feats >= ceiling_feats
            else "at or above the negative_mixed floor control's %.1f, which failed "
            'for geometric reasons at that same feature density' % floor_feats
        )
        detail = (
            ''
            if no_baseline
            else ' There was plenty to match. %s'
            % (
                'It did not agree.'
                if parallax
                else 'Read n_parallax_pairs to see how much of the shortfall is baseline rather than disagreement.'
            )
        )
        lines.append('n_features_mean=%.1f is %s, so a feature famine is ruled out.%s' % (feats, anchor, detail))
        if not no_baseline and feats < ceiling_feats:
            lines.append(
                "It is still %.2fx the textured ceiling's %.1f, so the set is less textured "
                'than the ceiling and some of the shortfall may be matchability rather than '
                'disagreement. n_parallax_pairs=%s of %s verified pairs.'
                % (
                    feats / ceiling_feats,
                    ceiling_feats,
                    parallax if parallax is not None else '?',
                    verified if verified is not None else '?',
                )
            )
        lines.append(
            'It does NOT by itself isolate identity drift. The ceiling control is rigid, '
            'nude, hairless, single-resolution and single-framing; a real sheet is none of '
            'those. Exclude the confounds in FRAMING_CONFOUNDS — starting with the 39 '
            'same-resolution cells — before attributing the failure to the subject changing '
            'between cells.'
        )
    return ' '.join(lines)


if __name__ == '__main__':  # pragma: no cover - convenience only
    import json

    print(json.dumps({'BAND': BAND, 'REQUIRED_SETTINGS': REQUIRED_SETTINGS, 'DERIVATION': DERIVATION}, indent=2))
