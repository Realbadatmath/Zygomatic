# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Poses (poses). 2026-09-30.

Question the sheet asks: "Can we hit a specific held body position?"

A pose is not a picture and not a clip: it is a GEOMETRY STATEMENT, and the only honest way
to ask whether a row hit it is to measure the skeleton that came out against the skeleton
that was asked for. So the test is ONE FIXED POSE PACK — twelve poses, each with a verbatim
prompt, a hand-drawn OpenPose control map and a target skeleton the operator has marked by
hand — pushed through each row IN ITS OWN DIRECTION, and scored with the same measurement:
`pose_keypoint_error_max`, the worst per-keypoint distance between achieved and asked,
normalised by the subject's own torso length so a wide shot and a close-up compare.

The four live rows are not four generators. They are the four places a pose is decided:
  openpose_cn     a pose REACHED: a skeleton map drives FLUX ControlNet Union Pro
                  (_comfy_workflows/flux_pose_ipa_cell.json) and the render is measured back
  mediapipe_pose  a pose READ: geom/keypoints.detect, the crop-first 33-point cascade
  pose_fitter     a pose SOLVED: geom/anny_fit, the in-house parametric body fit
  char2d_poses    a pose AUTHORED: char2d_poses.py angles applied to the MPFB rig
Each is measured on the same pack, so "accurate" means the same thing in all four columns.

HONEST JUDGING. No local VLM decides whether a pose is right (defect bench 2026-09-27: best
model 34/40 global, 2/8 on the hard cases). Every domain probe therefore carries a MECHANICAL
keypoint measurement AND a blind operator question, and the `state_note` says which decides.
Where the mechanism is the detector itself (the mediapipe_pose row), the operator is the only
judge that is not marking its own homework, and the note says so.

WHAT IS BLOCKED. The pose pack does not exist yet. capability_tests/fixtures/poses/MANIFEST.json
declares the twelve prompts, the control maps and an EMPTY `verified_skeletons` list; until the
operator marks the target keypoints by hand, every column scored by keypoint error is written
`untested — key unverified`. We do not grade a pose against a skeleton nobody checked.

`clean` is a RIGHTS question, not a quality one, and it is answered PER ROW: the OpenPose CMU
skeleton is non-commercial, MediaPipe is Apache-2.0 including the weights, and the row that
reaches a pose through a CMU-derived preprocessor inherits the preprocessor's licence.
"""

from __future__ import annotations

# Check kinds this step's runner must implement (the base vocabulary has no geometry).
CHECK_KINDS = {
    'pose_keypoint_error_max': 'the worst per-keypoint distance between the skeleton the row ACHIEVED (33-point BlazePose via '
    "geom/keypoints.detect run on the row's output, or the row's own keypoints where it returns them) "
    "and the fixture pose's operator-verified target skeleton, normalised by that target's "
    'shoulder-midpoint-to-hip-midpoint length, is <= `max` over every landmark named in `keypoints` '
    '(default: every landmark the target marks), in >= `share` of the trials',
    'keypoints_visible': 'the pinned detector reports every landmark named in `parts` with visibility >= `min_visibility` '
    '(default 0.5) in >= `share` of the trials — a foot the row did not put in frame is a no, not a pass',
    'skeleton_count': 'the pinned pose detector finds exactly `n` distinct person skeletons, each with at least '
    '`min_landmarks` landmarks above `min_visibility`, in >= `share` of the trials',
    'limb_owner_stable': "with `n` skeletons detected, every wrist and ankle landmark is nearer its OWN skeleton's "
    "torso centroid than any other skeleton's, in >= `share` of the trials — the limb-swap failure",
    'body_proportion_ratio': 'the named `ratio` (head_height_over_total | leg_over_total | arm_span_over_height) measured from '
    'the achieved skeleton is within `tol` of `target` in >= `share` of the trials',
}

FX = 'capability_tests/fixtures/poses'
MANIFEST = FX + '/MANIFEST.json'

# The twelve poses, verbatim. Each id is a key in MANIFEST.poses and carries: `prompt` (for the
# rows that are asked in words), `control` (the hand-drawn OpenPose map, for openpose_cn),
# `reference` (a photo, for the rows that READ a pose) and `target` (the verified skeleton).
POSES = {
    'p01_stand_neutral': 'A man stands facing the camera, arms hanging at his sides, feet shoulder-width apart, whole body in frame, plain grey studio background, even light.',
    'p02_arm_raised': 'A man stands facing the camera, his right arm raised straight above his head, his left arm at his side, his head turned to look up at his raised hand, whole body in frame, plain grey studio background, even light.',
    'p03_seated_chair': 'A man sits on a plain wooden chair, seen from the front, knees bent at a right angle, both feet flat on the floor, hands resting on his knees, whole body in frame, plain grey studio background, even light.',
    'p04_lying_side': 'A man lies on his left side on the floor, knees drawn up, his right arm along his body, seen from above and slightly to the side, whole body in frame, plain grey studio background, even light.',
    'p05_back_view': 'A man stands with his back to the camera, arms hanging at his sides, feet shoulder-width apart, whole body in frame, plain grey studio background, even light.',
    'p06_profile_walk': 'A man walks to the left in exact profile, his left leg forward and bearing his weight, his right arm swung forward, whole body in frame, plain grey studio background, even light.',
    'p07_foreshorten': 'A man reaches his right arm straight towards the camera, fist closed, his body behind it, seen head on so the arm is strongly foreshortened, whole body in frame, plain grey studio background, even light.',
    'p08_occluded_arm': 'A man stands facing the camera behind a waist-high wooden table, his left arm hidden behind his back, his right hand flat on the table, plain grey studio background, even light.',
    'p09_two_figures': "Two men stand facing each other in profile and shake hands, the left man's right hand in the right man's right hand, both whole bodies in frame, plain grey studio background, even light.",
    'p10_child_stand': 'A six-year-old child stands facing the camera, arms hanging at the sides, feet together, whole body in frame, plain grey studio background, even light.',
    'p11_wolf_stand': 'A grey wolf stands side-on to the camera on level ground, all four legs straight and bearing weight, head level, whole animal in frame, plain grey studio background, even light.',
    'p12_bow_forward': 'A man bows forward from the waist to about forty-five degrees, his back rounded, his arms hanging loose towards the floor, his head following the spine, seen in three-quarter view, whole body in frame, plain grey studio background, even light.',
}
# Three finger configurations for `fingers_pose` — the only pose question a body skeleton cannot answer.
FINGERS = {
    'f1_three_up': 'A man holds his right hand up towards the camera, palm forward, three fingers extended — index, middle and ring — the little finger and thumb folded down, close on the hand and forearm, plain grey background.',
    'f2_pinch': 'A man holds his right hand up towards the camera in profile, thumb and index fingertip touching in a pinch, the other three fingers curled, close on the hand and forearm, plain grey background.',
    'f3_splay': 'A man holds his right hand up towards the camera, palm forward, all five fingers spread as wide as they go, close on the hand and forearm, plain grey background.',
}

COND = {
    'repeats': 3,
    'seeds': [11, 12, 13],
    'resolution': '1024x1024',
    'note': 'three seeds per pose; a pose that only lands on one seed is a partial, not a yes. The reading rows (mediapipe_pose, pose_fitter) are deterministic and their three repeats measure the run, not the seed.',
}

ALL = ['openpose_cn', 'mediapipe_pose', 'pose_fitter', 'char2d_poses']
GEN = ['openpose_cn', 'char2d_poses']  # the rows that PRODUCE a body
READ = ['mediapipe_pose', 'pose_fitter']  # the rows that READ one


def _p(pid, title, feeds, pose, checks, rows, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'prompt': POSES.get(pose) or FINGERS.get(pose) or pose, 'fixture': MANIFEST + '#' + pose},
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': list(rows),
    }
    p.update(kw)
    return p


HARD = {'yes': 1.0, 'partial': 0.6}  # one pose x 3 seeds: yes only at 3/3

_OP_POSE = (
    'Here is the pose that was asked for, drawn as a stick figure, and here is what came out. '
    'Is the body in the position the stick figure shows — same limbs, same side, same direction? yes/no'
)

PROBES = [
    _p(
        'pp_accurate',
        'The whole pack: does the body reach the asked position',
        ['accurate'],
        'p01_stand_neutral',
        [
            {
                'check': 'pose_keypoint_error_max',
                'max': 0.08,
                'share': 0.9,
                'note': "0.08 of torso length is about a hand's width on a standing adult — the point at which the pose reads as a different pose",
            },
            {'check': 'operator', 'blind': True, 'question': _OP_POSE},
        ],
        ALL,
        pack=list(POSES),
        state_note=(
            'run over all twelve poses x 3 seeds = 36 trials; the default state rule applies (>= 0.8 yes). '
            'The MECHANICAL keypoint error decides; the blind operator question is recorded beside it and a '
            'disagreement between the two is written into the sheet note rather than resolved silently.'
        ),
    ),
    _p(
        'pp_hands',
        'Hands land where the pose puts them',
        ['hands'],
        'p01_stand_neutral',
        [
            {
                'check': 'pose_keypoint_error_max',
                'max': 0.10,
                'share': 0.8,
                'keypoints': ['left_wrist', 'right_wrist', 'left_index', 'right_index', 'left_thumb', 'right_thumb'],
            },
            {'check': 'hand_landmarks_count', 'hands': 2, 'fingers': 5, 'share': 0.8},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Ignore the rest of the body. Are both hands where the stick figure puts them, and is each one a hand — five digits, no fusing, no extra? yes/no',
            },
        ],
        ALL,
        pack=['p01_stand_neutral', 'p02_arm_raised', 'p03_seated_chair', 'p08_occluded_arm', 'p12_bow_forward'],
        state_note='the operator decides. MediaPipe fits its 21-landmark template onto any hand ([[project_hand_phalanx_correction]]), so hand_landmarks_count is a floor, never a pass.',
    ),
    _p(
        'pp_feet',
        'Feet and ground contact',
        ['feet'],
        'p01_stand_neutral',
        [
            {
                'check': 'keypoints_visible',
                'parts': [
                    'left_ankle',
                    'right_ankle',
                    'left_heel',
                    'right_heel',
                    'left_foot_index',
                    'right_foot_index',
                ],
                'min_visibility': 0.5,
                'share': 0.9,
            },
            {
                'check': 'pose_keypoint_error_max',
                'max': 0.10,
                'share': 0.8,
                'keypoints': ['left_ankle', 'right_ankle', 'left_heel', 'right_heel'],
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Do both feet meet the ground plane — flat where the pose says flat, neither floating above it nor sunk into it? yes/no',
            },
        ],
        ALL,
        pack=['p01_stand_neutral', 'p03_seated_chair', 'p06_profile_walk', 'p10_child_stand'],
    ),
    _p(
        'pp_head',
        'Head and neck angle',
        ['head_pose'],
        'p02_arm_raised',
        [
            {
                'check': 'pose_keypoint_error_max',
                'max': 0.08,
                'share': 0.8,
                'keypoints': ['nose', 'left_ear', 'right_ear', 'left_eye', 'right_eye'],
            }
        ],
        ALL,
        pack=['p02_arm_raised', 'p12_bow_forward'],
        state_rule=dict(HARD),
        state_note='p02 asks for a head turned UP to follow the hand and p12 for a head following a bowed spine; both are angles a body skeleton records, so no operator question is needed here.',
    ),
    _p(
        'pp_spine',
        'Spine curve',
        ['spine'],
        'p12_bow_forward',
        [
            {
                'check': 'pose_keypoint_error_max',
                'max': 0.08,
                'share': 0.8,
                'keypoints': ['left_shoulder', 'right_shoulder', 'left_hip', 'right_hip'],
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is the back ROUNDED as it bends, rather than a straight plank hinged at the hips? yes/no',
            },
        ],
        ALL,
        pack=['p12_bow_forward'],
        state_rule=dict(HARD),
        state_note="a 33-point skeleton has four trunk landmarks and no vertebrae, so curvature is the operator's call and the keypoint check only proves the bend happened.",
    ),
    _p(
        'pp_fingers',
        'Individual fingers are directable',
        ['fingers_pose'],
        'f1_three_up',
        [
            {'check': 'hand_landmarks_count', 'hands': 1, 'fingers': 3, 'share': 0.8, 'variant': 'f1_three_up'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Which fingers are extended on this hand? Write them down, then compare with the brief: do they match exactly, including which finger is folded? yes/no',
            },
        ],
        GEN,
        pack=list(FINGERS),
        state_rule=dict(HARD),
        state_note='three configurations x 3 seeds = 9 trials per row. The operator decides: counting extended fingers from landmarks measures the template, not the picture (hand_qc_service.py, run 6278904c).',
    ),
    _p(
        'pp_foreshorten',
        'Survives foreshortening',
        ['foreshorten'],
        'p07_foreshorten',
        [
            {
                'check': 'pose_keypoint_error_max',
                'max': 0.12,
                'share': 0.8,
                'keypoints': ['right_shoulder', 'right_elbow', 'right_wrist'],
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does the right arm read as pointing at the camera — short on the page but solid — rather than as a stunted or broken arm? yes/no',
            },
        ],
        ALL,
        state_rule=dict(HARD),
        state_note='the tolerance is loosened to 0.12 because a foreshortened limb projects to a few pixels and a 0.08 gate would fail on projection noise alone.',
    ),
    _p(
        'pp_seated',
        'Seated poses',
        ['seated'],
        'p03_seated_chair',
        [
            {'check': 'pose_keypoint_error_max', 'max': 0.08, 'share': 0.8},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is the figure SITTING — weight on the seat, knees bent at about a right angle, both feet on the floor — rather than crouching or hovering? yes/no',
            },
        ],
        ALL,
        state_rule=dict(HARD),
    ),
    _p(
        'pp_lying',
        'Lying and crouching',
        ['lying'],
        'p04_lying_side',
        [
            {'check': 'pose_keypoint_error_max', 'max': 0.10, 'share': 0.8},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is the figure lying on its LEFT side with the knees drawn up, seen from above? yes/no',
            },
        ],
        ALL,
        state_rule=dict(HARD),
        state_note='BlazePose is trained overwhelmingly on upright subjects; a low score here is a detector limit on the reading rows and a generator limit on the making rows, and the note must say which.',
    ),
    _p(
        'pp_back',
        'Back views',
        ['back_view'],
        'p05_back_view',
        [
            {'check': 'pose_keypoint_error_max', 'max': 0.08, 'share': 0.8},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this the BACK of a person — no face, shoulder blades towards us — rather than a front view or a twisted body? yes/no',
            },
        ],
        ALL,
        state_rule=dict(HARD),
        state_note='geom/keypoints.py: a rear view has no face and the cascade reports "no face" rather than inventing one; a confident face mesh on p05 is a detector LIE and scores no.',
    ),
    _p(
        'pp_profile',
        'Profile views',
        ['profile_pose'],
        'p06_profile_walk',
        [
            {'check': 'pose_keypoint_error_max', 'max': 0.08, 'share': 0.8},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is the body in true profile walking LEFT, with the left leg forward and the right arm swung forward? yes/no',
            },
        ],
        ALL,
        state_rule=dict(HARD),
        state_note='geom/anny_fit v2 races stage 1 from four yaw seeds precisely because an orthographic fit cannot discover a profile from near-collinear points (v1 scored 97.5 px on cell_28); this probe is the regression test for that fix.',
    ),
    _p(
        'pp_occluded',
        'Occluded limbs',
        ['occluded_limb'],
        'p08_occluded_arm',
        [
            {
                'check': 'keypoints_visible',
                'parts': ['right_wrist', 'right_elbow'],
                'min_visibility': 0.5,
                'share': 0.9,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'The left arm is meant to be hidden behind the back. Is it ABSENT and accounted for, rather than drawn through the body, duplicated, or grown a second right arm? yes/no',
            },
        ],
        ALL,
        state_rule=dict(HARD),
        state_note='the honest answer for a reading row is "declines to place the hidden limb". anny_fit v2 records a DRAW LIMIT and declines below the evidence; declining is a pass here, inventing a wrist is a no.',
    ),
    _p(
        'pp_two_figure',
        'Two figures without swapping limbs',
        ['two_figure'],
        'p09_two_figures',
        [
            {'check': 'skeleton_count', 'n': 2, 'min_landmarks': 20, 'min_visibility': 0.5, 'share': 0.9},
            {'check': 'limb_owner_stable', 'n': 2, 'share': 0.9},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does each man have exactly two arms and two legs of his own, with no limb running from one body into the other, and are the two shaking hands right-to-right? yes/no',
            },
        ],
        ALL,
        state_rule=dict(HARD),
    ),
    _p(
        'pp_child',
        'Child proportions',
        ['child_prop'],
        'p10_child_stand',
        [
            {
                'check': 'body_proportion_ratio',
                'ratio': 'head_height_over_total',
                'target': 0.165,
                'tol': 0.025,
                'share': 0.8,
                'note': 'a six-year-old is about six heads tall (0.167); an adult is seven and a half (0.133). The gate separates the two and nothing finer.',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this a CHILD of about six — head large for the body, short limbs — rather than a small adult? yes/no',
            },
        ],
        ALL,
        state_rule=dict(HARD),
    ),
    _p(
        'pp_creature',
        'Non-human skeletons',
        ['creature_pose'],
        'p11_wolf_stand',
        [
            {
                'check': 'detector_count',
                'detector': 'yolov8n-coco',
                'label': 'dog',
                'n': 1,
                'share': 0.8,
                'note': 'COCO has no wolf class; a wolf resolves as `dog` and that is the only mechanical hold on this frame',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does the wolf stand on exactly four legs, each one complete and bearing weight, with the spine level? yes/no',
            },
        ],
        ['openpose_cn'],
        state_rule=dict(HARD),
        state_note=(
            'only openpose_cn can be asked: the control map for p11 is a hand-drawn quadruped stick figure declared in the '
            'MANIFEST, because no OpenPose topology exists for a four-legged animal. The three other rows are `na` — their '
            'skeletons ARE the human template.'
        ),
    ),
    _p(
        'pp_extract',
        'Extracts a pose from a reference',
        ['extract_pose'],
        'p06_profile_walk',
        [
            {
                'check': 'pose_keypoint_error_max',
                'max': 0.06,
                'share': 0.9,
                'note': 'tighter than the generation gate: extraction is measured against the same picture, so there is no generation slack to allow for',
            },
            {
                'check': 'keypoints_visible',
                'parts': ['left_shoulder', 'right_shoulder', 'left_hip', 'right_hip'],
                'min_visibility': 0.5,
                'share': 0.9,
            },
        ],
        READ,
        pack=['p01_stand_neutral', 'p04_lying_side', 'p06_profile_walk', 'p09_two_figures'],
        state_note="the four reference photographs in the MANIFEST are read and the returned keypoints compared with the operator's marks on the SAME picture. No operator question: this is a measurement against a verified key, not a judgement.",
    ),
]

LICENCE_ROWS = {
    'openpose_cn': (
        'NON-COMMERCIAL as wired. The skeleton the ControlNet consumes is in the CMU OpenPose format and the '
        'house preprocessor that draws it is the licence-deciding part; the CMU Perceptual Computing Lab '
        'OpenPose licence is academic / non-profit non-commercial. The base model, FLUX.1-dev with Shakker '
        'Labs ControlNet Union Pro, is itself FLUX.1-dev non-commercial. Two independent blocks on one row.',
        'https://github.com/CMU-Perceptual-Computing-Lab/openpose',
    ),
    'mediapipe_pose': (
        'CLEAN. MediaPipe pose_landmarker is Apache-2.0 INCLUDING the weights, verified at file level '
        '2026-08-04 and recorded in data/assets/detectors/PROVENANCE.json (geom/keypoints.py docstring). '
        'No SMPL, no DensePose, no dlib, no insightface anywhere in this row.',
        'https://github.com/google-ai-edge/mediapipe',
    ),
    'pose_fitter': (
        'CLEAN. geom/anny_fit is house code over the Anny parametric body: Apache-2.0 code plus CC0 data, and '
        'the fit itself is an optimisation written here, not a trained regressor — the module exists because '
        'every published image-to-mesh regressor was found non-commercial on 2026-08-04, Multi-HMR included. '
        'Its keypoint input is the MediaPipe cascade above, so the whole chain is clean.',
        'house receipt: geom/anny_fit.py docstring + data/runtime/model_licences.json',
    ),
    'char2d_poses': (
        'CLEAN. char2d_poses.py is stdlib-only house code; the ROM table was measured on the MPFB default rig '
        'and no third-party skeleton, motion capture set or pose dataset is used at any point.',
        'house code: char2d_poses.py (no external skeleton source)',
    ),
    'dwpose': (
        'NOT REVIVED. DWPose code and weights are published Apache-2.0, but the distillation set is COCO-WholeBody '
        'plus UBody and the UBody half is research-only, so the weights are tainted for commercial use whatever the '
        'repository licence file says. If this row is ever revived, verify AT FILE LEVEL before it renders anything.',
        'https://github.com/IDEA-Research/DWPose',
    ),
}

NA_MP = {
    'fingers_pose': 'geom/keypoints.detect reports the 21-point hand mesh but directs nothing; "individual fingers are directable" is a property of a row that makes a hand, and this row only reads one',
    'creature_pose': 'BlazePose is a fixed 33-point HUMAN topology: asked for a wolf it reports nothing or stretches the human template over it, and neither of those is an answer about a quadruped',
    'edit_pose': 'the detector hands keypoints to its caller and has no editing surface of its own; the editor is measured once for the step',
}
NA_FIT = {
    'hands': 'the Anny body fit solves the body chain; the hand is one wrist joint with no palm and no digits, so there is no hand to land',
    'fingers_pose': 'the Anny body model has no finger degrees of freedom at all — there is nothing here that could be directed',
    'creature_pose': 'Anny is a parametric HUMAN body; fitting it to a wolf would return a contorted human and report a number for it, which is worse than declining',
    'edit_pose': 'the fitter returns body parameters for its caller; editing happens in the tool that consumes them, not here',
}
NA_C2D = {
    'extract_pose': 'char2d_poses applies authored Euler angles from a JSON file; it never reads a picture, so there is no reference to extract from',
    'creature_pose': 'the rig is the MPFB human base body (blender_scripts/char2d_build.py); there is no quadruped armature to pose',
    'two_figure': 'one character.blend holds one rig; two figures are two renders composited later, so limb swapping cannot arise and cannot be measured',
}
NA_CN = {
    'extract_pose': "the ControlNet CONSUMES a skeleton map; extracting one from a photograph is the preprocessor's job and is measured on the two reading rows",
}

TEST = {
    'step': 'poses',
    'version': '2026-09-30.1',
    'title': 'Twelve verified poses through the four places a pose is decided',
    'purpose': 'Measure the skeleton that came out against the skeleton that was asked for, identically for a ControlNet render, a detector, a parametric fit and an authored rig.',
    'include_shared': 'video',
    'pose_pack': POSES,
    'finger_pack': FINGERS,
    'rows': {
        'openpose_cn': {
            'transport': 'comfy',
            'model': '_comfy_workflows/flux_pose_ipa_cell.json — FLUX.1-dev + Shakker Labs ControlNet Union Pro in pose mode, OpenPose skeleton map on node "Apply pose ControlNet"',
            'na': NA_CN,
            'state_note': 'the sheet row is named for the OpenPose FORMAT, not for an SDXL checkpoint: the live pose ControlNet on this box is the FLUX Union Pro one, and that is what the test runs.',
        },
        'mediapipe_pose': {
            'transport': 'service',
            'where': 'geom/keypoints.detect — crop-first cascade, 33-point pose + 478-point face + optional 21-point hands, original-image pixels',
            'na': NA_MP,
            'budget': {
                'calls': 84,
                'minutes': 4,
                'gpu_minutes': 0,
                'operator_minutes': 18,
                'note': 'CPU only, ~0.5 s per image plus ~0.5 s graph startup per model; 84 reads = ~2 min, doubled for the tiled escalation pass on the wide poses.',
            },
        },
        'pose_fitter': {
            'transport': 'service',
            'where': 'geom/anny_fit.fit_cell — the in-house parametric body fit v2 (full | upper | declines)',
            'na': NA_FIT,
            'budget': {
                'calls': 84,
                'minutes': 30,
                'gpu_minutes': 8,
                'operator_minutes': 18,
                'note': 'the v2 fit races four yaw seeds through a two-stage optimisation, ~20 s per cell on this box: 84 x 20 s = 28 min, of which the keypoint pass is the only GPU part.',
            },
            'state_note': (
                'carry the three MEASURED v1 defects the v2 docstring records, so a repeat is visible as a regression and not read as news: '
                'FIT MODES — 8 face/shoulder points cannot constrain a body and cell_31 exploded to 276.8 px; YAW SEEDING — a frontal body '
                'fitted beside a profile character, cell_28 at 97.5 px; ARM PRIOR — the T-pose regulariser drew a giant arm across the sky on '
                'cell_00 at 56.9 px. pp_profile, pp_occluded and pp_accurate are the standing regression tests for those three.'
            ),
        },
        'char2d_poses': {
            'transport': 'service',
            'where': 'char2d_poses.py (ROM table + validator) applied through blender_scripts/char2d_build.apply_bones, rendered by char2d_render_pose.py',
            'na': NA_C2D,
            'budget': {
                'calls': 84,
                'minutes': 40,
                'gpu_minutes': 0,
                'operator_minutes': 18,
                'note': 'headless Blender: ~15 s startup amortised over a batch plus ~25 s per posed render on CPU; 84 renders = ~38 min, no GPU (Freestyle + EEVEE on the software path).',
            },
        },
        'dwpose': {
            'transport': 'retired',
            'model': 'DWPose (IDEA-Research) whole-body pose distillation',
            'skip': (
                'NOT USED on this box, 2026-07-30: the hand and pose path was moved to MediaPipe when the AGPL-3.0 ultralytics runtime was '
                'dropped, and DWPose was never wired back in. Kept for its licence receipt — the code and weights are published Apache-2.0 but '
                'the distillation set is COCO-WholeBody plus UBody and the UBody half is research-only, so the weights are tainted whatever the '
                'repository licence says. If this row is ever revived, verify at FILE level before it renders anything.'
            ),
        },
    },
    'probes': PROBES,
    'derive': {
        'speed': {
            'from': 'wall clock per pose, per row, model load excluded from the per-item figure and reported beside it',
            'grade': 'measured',
            'unit': 's',
        },
        'throughput': {
            'from': 'poses per hour sustained over the 84-call pack, single stream',
            'grade': 'measured',
            'unit': 'count',
        },
        'deterministic': {
            'from': 'the three repeats at the SAME seed: identical output hash for the reading and authoring rows (expected yes), identical latents for openpose_cn',
            'grade': 'measured',
        },
        'first_take': {'from': 'share of probes whose FIRST seed passed, before any reroll', 'grade': 'measured'},
        'retries': {
            'from': 'seeds drawn until the first pass, over probes that eventually passed',
            'grade': 'measured',
            'unit': 'count',
        },
        'silent_fail': {
            'from': 'share of failed probes a mechanical check caught before the operator did — a wrong pose that renders cleanly is the silent kind, and pp_occluded is where it lives',
            'grade': 'measured',
        },
        'receipts': {
            'from': 'the run leaves the control map, the achieved keypoints as json, the target skeleton and the settings next to every output',
            'grade': 'receipt',
        },
        'gated': {
            'from': 'whether a pose leaves this step through a gate that reads the keypoint error, or only through a human glance',
            'grade': 'receipt',
        },
    },
    'lookup': {
        'clean': {
            'requires': 'the per-row licence receipts below, re-read at file level before any commercial delivery; the house ledger is data/runtime/model_licences.json and data/assets/detectors/PROVENANCE.json',
            'grade': 'vendor',
            'per_row': {k: {'verdict': v[0], 'source': v[1]} for k, v in LICENCE_ROWS.items()},
            'note': 'this column is a RIGHTS question about the skeleton source, not a quality one, and the four live rows do not share an answer: two are clean, one is doubly blocked, and the retired one is kept for exactly this receipt.',
        },
        'library_pose': {
            'requires': 'a directory count at run time: assets/contact_sheet_poses/*.png (24 OpenPose angle maps, angle_00..angle_23, counted 2026-09-30) and data/char2d/gestures/*.json (11 authored gesture files plus 00_idle)',
            'grade': 'receipt',
            'note': 'two libraries, neither of them a general pose library: 24 camera-ANGLE maps for the contact sheet and 11 authored hand gestures for the char2d rig. The honest cell is the count and what it is a library OF.',
        },
    },
    'wiring': {
        'edit_pose': {
            'from': "read off the code path, not run: char2d_poses.py is the editing surface — a gesture file is plain JSON of local XYZ Euler degrees per bone, and the module ships the ROM table and a validator that refuses an angle outside a joint's measured limits. There is no graphical pose editor; editing a pose means editing the JSON and re-running the render.",
            'grade': 'assumed',
        },
    },
    'na': {},
    'fixtures': [
        {
            'path': MANIFEST,
            'verified': False,
            'blocks': [
                'accurate',
                'hands',
                'feet',
                'head_pose',
                'spine',
                'foreshorten',
                'seated',
                'lying',
                'back_view',
                'profile_pose',
                'occluded_limb',
                'two_figure',
                'child_prop',
                'extract_pose',
            ],
            'generated': (
                'write the twelve prompts and the three finger prompts above into MANIFEST.poses verbatim, one entry each; '
                "render p01..p12 once at 1024x1024 through the row's own production path to get a REFERENCE photograph per pose, "
                'and hand-draw the twelve OpenPose control maps in the CMU 18-point colour convention (a quadruped stick figure '
                'for p11, which has no OpenPose topology)'
            ),
            'how_to_verify': (
                'open each of the twelve reference pictures, mark every visible landmark of the 33-point BlazePose set by hand '
                'into MANIFEST.poses[<id>].target (x, y in original-image pixels, plus `visible` true/false), then set '
                'verified = true. Until then every keypoint-error column is written untested "key unverified" — we do not '
                'grade a pose against a skeleton nobody checked.'
            ),
        },
    ],
    'budget': {
        'calls': 84,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'no language model is called anywhere on this step: a ControlNet takes a skeleton map, a detector takes an image, a fitter takes keypoints and a rig takes Euler angles',
        'minutes': 55,
        'gpu_minutes': 50,
        'operator_minutes': 18,
        'note': (
            'Per row: 12 poses x 3 seeds = 36, plus the extract pack 4 x 3 = 12, plus the finger pack 3 x 3 = 9, plus the '
            'hard-case packs already counted in the twelve, plus 27 repeat slots for the five multi-pose probes that re-use '
            'poses already rendered (cached, counted once) = 84 calls. openpose_cn is the default and the most expensive: a '
            'FLUX ControlNet render at 1024x1024 is ~35 s plus ~4 min model load, so 84 x 35 s + 4 = ~53 min, essentially all '
            'on the GPU. The three other rows override (mediapipe_pose 4 min CPU, pose_fitter 30 min, char2d_poses 40 min '
            'CPU Blender). Operator: 12 blind questions x 3 seeds = 36 decisions at 30 s = 18 min per row, 72 min over the '
            'four live rows, PLUS a one-time ~90 min marking the twelve target skeletons by hand (until that is done the '
            'keypoint columns are BLOCKED). SHARED BANK: include_shared video covers 235 of the 254 columns with 220 probes '
            'at 3 repeats = 660 clips of 81 frames at 832x480 — on this box roughly 5 min a clip, so ~55 GPU-HOURS per row '
            'that is a video generator. NONE of these four rows is: openpose_cn makes a still, the other three make no '
            "pixels at all, so the bank's Moves probes are transport-exempt or `untested — not a video row` and the real "
            'bill for this sheet is the ~55 min above, not the 55 hours. Schedule the bank on the video steps, not here.'
        ),
    },
    'run_order': [
        'pp_extract',
        'pp_accurate',
        'pp_head',
        'pp_spine',
        'pp_feet',
        'pp_hands',
        'pp_fingers',
        'pp_seated',
        'pp_profile',
        'pp_back',
        'pp_foreshorten',
        'pp_occluded',
        'pp_lying',
        'pp_two_figure',
        'pp_child',
        'pp_creature',
    ],
    'notes': [
        'Cheap and mechanical first: pp_extract and pp_accurate run on the CPU rows before a single GPU render is queued, so a '
        'partial run already fills the two columns the rest of the sheet leans on.',
        'The pose pack is the whole test. A row added later is comparable only if it is run on the SAME twelve poses with the SAME '
        'target skeletons; a new pose means a new version and a new hash.',
        'Two rows READ a pose and two MAKE one. `accurate` therefore means "the detected skeleton matches the operator\'s marks" on '
        'the reading rows and "the rendered body matches the asked skeleton" on the making rows. Same measurement, opposite direction '
        '— the sheet note on every cell must say which, or the column is misread.',
        'The wolf (p11) is the one place where only a single row can be asked. That is the finding, not a gap: three of the four '
        'pose surfaces on this box are human-topology by construction and cannot be made to hold a quadruped.',
    ],
}
