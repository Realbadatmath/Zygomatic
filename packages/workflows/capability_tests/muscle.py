# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Muscle, weight & deformation (muscle). 2026-09-30.

Question the sheet asks: "Does the body behave like flesh over bone?" On 2026-09-30 this is the
emptiest sheet on the tab: every column here has been described in words and hoped for, never
measured. The `measured` column exists to say so out loud, and this test is written so that the
first run replaces that sentence with numbers.

The shape of the test
---------------------
Three rows, two of which are not pixel generators:
  * `prompt_muscle` asks for muscle in WORDS — the movement_studio racks carry weight, breathing,
    intensity and posture, and nothing else in this house can ask Wan for effort. The prompt is
    built by movement_studio.compose_prompt() from the dial state below and submitted verbatim.
  * `anatomy_layers` is the Movement Studio anatomy solver: 262 joints and 192 links solved over
    the cmu_mb rig's 31 channels, with the BONES layer a real SkinnedMesh of 135 CC0 anatomical
    pieces and the MUSCLES layer the écorché body inset 1.5 mm
    ([[project_movement_anatomy_layers]]).
  * `blender_rig` is armature deformation in the mesh studio, the only row whose mesh can be
    measured directly rather than through pixels.
The two rig rows cannot render the shared bank's 132 subjects, its capacity ladders or its space
scenes, so those bands are `na` per row with the reason written out. They are NOT excused from
the deformation columns: a SkinnedMesh weighted to 31 joints has no muscle bulge at all, and the
honest cell for that is a measured `no`, not an `na`.

What is measured mechanically and what the operator decides
----------------------------------------------------------
No local VLM judges a render defect (defect judge bench 2026-09-27: 34/40 on a global question,
2/8 on the hard cases), so every "does this look right" is a BLIND operator yes/no, and every
column that has a real measurement gets it too:
  * `flex` is a width ratio inside the SAM2 mask of the upper arm, relaxed frame against peak —
    a bicep that does not widen has not flexed, whatever it looks like;
  * `breath_body` and `soft_tissue` are the same measurement at two frequencies: chest
    circumference 0.2-0.4 Hz for breathing, soft-tissue landmarks 1-6 Hz for jiggle;
  * `joint_bulge` is the cross-section growing on the inside of a closing elbow;
  * `volume` is the real thing, on the one row that has a mesh: |ΔV| <= 3 % over the clip;
  * `consistent` is the shoulder-to-ribcage ratio holding across the clip — the same number that
    caught the clavicle defect on the movement sheet ([[project_movement_stance_chest_fix]]).

What is blocked and why
-----------------------
The fitted Abel rig is `verified: False` and blocks `child_muscle` and `body_types`: the fit is
`clamped`, not exact — the leg wants x0.753 and is pinned at the 0.800 clamp, worst 5.50 %
(2026-09-24) — so a "child" rig today has adult legs and grading a child's flesh against it grades
the base body's proportions instead.
"""

from __future__ import annotations

# ── check kinds this module adds ─────────────────────────────────────────────────────────────
CHECK_KINDS = {
    'masked_width_ratio_min': 'inside the SAM2 mask for `region` (box-prompted with the region words), the mask width measured perpendicular to the limb axis at `at_frac` of its length grows from the `relaxed` frame to the `peak` frame by a factor >= `min_ratio`',
    'oscillation_hz_range': 'the dominant frequency of the `signal` (a named track distance or landmark displacement), from the FFT of its de-trended series over the clip, lies between `min_hz` and `max_hz` with the peak carrying >= `min_share` of the band power; a flat signal has no peak and fails',
    'skin_tangential_slide_min': 'the surface point nearest a named bone landmark moves TANGENTIALLY to the underlying bone axis by >= `min_frac` of the limb length between `a` and `b` — measured on the mesh for a rig row, on the `region` mask contour for a pixel row; pure rigid rotation gives zero slide',
    'cross_section_growth_min': 'the mesh (or masked) cross-section area on the `side` side of joint `joint` grows by >= `min_ratio` between the joint angle `open_deg` and `closed_deg`, and does not SHRINK on the opposite side by more than `max_loss`',
    'mesh_volume_drift_max': 'the closed-mesh signed volume of `mesh` stays within `max_frac` of its rest-pose value in every frame of `sample` (trimesh on the per-frame evaluated mesh); a rig that loses volume as it bends fails',
    'metric_declines_over_clip': "the named `metric` measured over the LAST `window_frac` of the clip is lower than over the first `window_frac` by >= `min_drop` (a fraction of the first window's value); measures that the movement changes as the clip runs, not that it is slow",
    'keypoint_ratio_stable': 'the ratio of the track distances `a` and `b` (named keypoint pairs or vertex bands) stays within `max_drift` of its own median across the frames in `sample`',
    'track_ratio_within': 'the body proportion `metric` (head_frac|leg_frac|shoulder_frac|shoulder_hip_frac) measured off the track is within `tol` of `target` in >= `share` of the frames in `sample`',
}

# ── the fixed inputs ─────────────────────────────────────────────────────────────────────────
SUBJ = 'capability_tests/fixtures/video/subjects/%s.png'  # the video bank's approved stills
STILL = SUBJ % 'muscle_flex'
RIG = 'capability_tests/fixtures/movement/abel_fitted.glb'  # ONE fixture, shared with movement

# Everything not named in a probe's `dials` is the rack DEFAULT, so a trial differs from the
# baseline in exactly the tokens under test (movement_studio._PARAMS, 2026-09-30).
BASE_DIALS = {
    'action': 'idle',
    'speed': 'natural',
    'intensity': 'natural',
    'amplitude': 'natural',
    'easing': 'none',
    'repeat': 'once',
    'direction': 'in place',
    'ground': 'natural',
    'posture': 'natural',
    'breathing': 'natural',
    'weight': 'natural',
}

FIXED = {
    'frames': 81,
    'resolution': '832x480',
    'steps': 30,
    'cfg': 6.0,
    'sampler': 'uni_pc/simple',
    'seeds': [11, 12, 13],
    'shift': "the row's PRODUCTION default, recorded into every trial; on Wan shift IS the motion lever, so a shift change is a different test [[project_wan_motion_debug]]",
    'prompt_rule': (
        "prompt_muscle only: the runner builds the dial state from BASE_DIALS updated with the probe's `dials`, "
        'calls movement_studio.compose_prompt() and submits EXACTLY the sentence it returns; the sentence, the dial '
        'state and the resolved render_kwargs all go into the trial'
    ),
    'rig_rule': (
        'anatomy_layers and blender_rig: the same clip is produced by posing the fitted rig through the ANGLES table '
        'below over 81 frames at 17 fps, layers on, and capturing the viewport (anatomy_layers, the Playwright capture '
        'path) or rendering it (blender_rig). The pose is the fixed input — no prompt exists on either row.'
    ),
    'angles': {
        'arm_curl': 'right elbow 170 deg -> 35 deg -> 170 deg over 81 frames, shoulder held',
        'squat': 'both knees 178 deg -> 95 deg -> 178 deg, hips tracking, feet planted',
        'breath': "no joint moves; only the row's own breathing channel, if it has one",
    },
    'measure': (
        'a pixel row is measured through SAM2 masks (box-prompted with the region words) and geom.pose_track landmarks; '
        'a rig row is measured on the evaluated MESH (trimesh) for volume and cross-section and on the same masks for '
        'anything the pixel row is also asked. Distances are normalised to a shoulder width of 100 px so the rows compare.'
    ),
    'negative': 'the rack default negative_prompt on prompt_muscle, recorded per trial; never edited per probe',
}

COND = {
    'repeats': 3,
    'seeds': [11, 12, 13],
    'frames': 81,
    'resolution': '832x480',
    'steps': 30,
    'cfg': 6.0,
    'sampler': 'uni_pc/simple',
    'shift': 'row production default (recorded)',
    'note': 'three seeds on a pixel row; a rig row is deterministic, so its three repeats are three IDENTICAL runs and disagreement between them is itself a finding',
}
COND_LADDER = dict(
    COND, note='three seeds at EVERY rung; scored on the rung medians so one bad seed cannot invert the ladder'
)

STATE_3OF3 = {'yes': 1.0, 'partial': 0.6}  # yes at 3/3 seeds, partial at 2/3
STATE_LADDER = {'yes': 1.0, 'partial': 0.5}

ALL3 = ['prompt_muscle', 'anatomy_layers', 'blender_rig']
PIX = ['prompt_muscle']
RIGROWS = ['anatomy_layers', 'blender_rig']

# The bands neither rig row can produce: the shared bank renders 132 photographic subjects, a
# capacity ladder and staged spatial scenes, none of which a posed armature can be asked for —
# and neither row takes a prompt at all, so the four prompt bands have nothing to steer. (The
# bank's transport_na already excuses the prompt bands on a blender row; naming them here makes
# the anatomy_layers row, which is transport `service`, say the same thing for the same reason.)
RIG_NA_BANDS = {
    'bands': [
        'Moves: People',
        'Moves: The body',
        'Moves: Food',
        'Moves: Damage & wear',
        'Moves: Text & number',
        'Moves: Objects',
        'Moves: Animals',
        'Moves: Nature & weather',
        'Moves: Built environment',
        'Moves: Clothing',
        'Capacity',
        'Space & relation',
        'Prompt: damage',
        'Prompt: clarity needed',
        'Prompt: limits',
        'Prompt: steering',
    ],
    'reason': "this row deforms one fitted rig and takes no prompt: the fixed input is a joint-angle table, so there is no subject to swap, no scene to stage, no clip length to push and no prompt word to steer — the shared video bank's subject, capacity, spatial and prompt bands cannot be asked of it at all",
}


def _p(pid, title, feeds, checks, rows, dials=None, still=STILL, pose=None, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {
            'fixture': still,
            'prompt': 'movement_studio.compose_prompt(BASE_DIALS + dials)  [prompt_muscle only]',
            'dials': dict(BASE_DIALS, **(dials or {})),
            'pose': pose or 'arm_curl',
            'rig': RIG,
        },
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': list(rows),
        'state_rule': dict(STATE_3OF3),
    }
    p.update(kw)
    return p


PROBES = [
    # ── Under load ───────────────────────────────────────────────────────────────────────────
    _p(
        'm_flex',
        'Visible flex under load',
        ['flex'],
        [
            {
                'check': 'masked_width_ratio_min',
                'region': 'upper arm',
                'at_frac': 0.5,
                'relaxed': 0,
                'peak': 40,
                'min_ratio': 1.08,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'As the arm bends, does the upper arm VISIBLY thicken — a muscle filling out — rather than the limb keeping one width like a tube? yes/no',
            },
        ],
        ALL3,
        dials={'action': 'work', 'intensity': 'extreme', 'weight': 'heavy and grounded'},
        state_note='the width of the upper-arm mask at its midpoint must grow by at least 8 % from the straight frame to the fully-bent frame. 8 % is a deliberately low bar — it is the floor below which nothing happened. On a SkinnedMesh weighted to 31 joints the expected reading is 1.00 and the honest cell is `no`.',
    ),
    _p(
        'm_weight',
        'Weight reads correctly',
        ['weight'],
        [
            {'check': 'motion_min', 'min': 1.2},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this body look like it is moving something HEAVY — braced, slower through the lift, the load visibly resisting — rather than miming the same action with nothing in its hands? yes/no',
            },
        ],
        ALL3,
        dials={'action': 'work', 'weight': 'heavy and grounded', 'speed': 'very slow'},
        state_note='weight is an impression with no detector in this house, so it is a blind operator question with a mechanical FLOOR only: `motion_min` rejects the near-still clip Wan returns when it ignores the verb, so no human is asked about a static frame. Two clips of the same action, "heavy and grounded" against the rack default, are shown anonymised and shuffled.',
    ),
    _p(
        'm_strain',
        'Strain shows in the body',
        ['strain'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does the effort show anywhere OTHER than the moving limb — the torso bracing, the neck or jaw tightening, the supporting leg loading? yes/no',
            }
        ],
        ALL3,
        dials={'action': 'work', 'intensity': 'extreme', 'weight': 'heavy and grounded'},
        state_note='strain is whole-body effort and nothing measures it. The question is deliberately written to exclude the limb that is obviously working, because a model that only animates the acting limb passes a looser question.',
    ),
    _p(
        'm_breath',
        'Breathing moves the chest',
        ['breath_body'],
        [
            {
                'check': 'oscillation_hz_range',
                'signal': 'chest_width_at_sternal_angle',
                'min_hz': 0.2,
                'max_hz': 0.4,
                'min_share': 0.5,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this chest BREATHE — a slow steady rise and fall, about ten to twenty times a minute — rather than sitting still or trembling? yes/no',
            },
        ],
        ALL3,
        dials={'action': 'idle', 'breathing': 'slow and deep'},
        pose='breath',
        state_note='0.2-0.4 Hz is 12-24 breaths a minute, resting adult. 81 frames at 17 fps is 4.8 s, so a 0.2 Hz signal gets one full cycle — enough for an FFT peak, not enough for a rate estimate, and the cell records the peak frequency alongside the verdict. Neither rig row has a breathing channel (no clip in this house carries one), so their expected reading is "no peak" = `no`.',
    ),
    {
        'id': 'm_fatigue',
        'title': 'Fatigue changes the movement',
        'feeds': ['fatigue'],
        'inputs': {
            'fixture': STILL,
            'prompt': 'movement_studio.compose_prompt(BASE_DIALS + {action: work, repeat: three, intensity})',
            'dials': dict(BASE_DIALS, action='work', repeat='three'),
            'pose': 'squat',
            'rig': RIG,
        },
        'grid': {'intensity': ['subtle', 'natural', 'extreme']},
        'conditions': dict(COND_LADDER),
        'grade': 'measured',
        'rows': list(PIX),
        'state_rule': dict(STATE_LADDER),
        'checks': [
            {
                'check': 'metric_declines_over_clip',
                'metric': 'mean_joint_speed_px_per_frame',
                'window_frac': 0.25,
                'min_drop': 0.1,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'By the end of the clip, is this body TIRING — the same action getting smaller, slower or heavier than it was at the start? yes/no',
            },
        ],
        'state_note': "three repetitions of the same effort in one clip: the last quarter must be at least 10 % slower than the first. Only the prompt row is asked — a rig row plays the angle table we wrote, so any decline would be OUR fatigue, not the row's. The rack has no fatigue token, so intensity is the nearest lever and a flat ladder is the expected finding.",
    },
    # ── Deformation ──────────────────────────────────────────────────────────────────────────
    _p(
        'm_skin_slide',
        'Skin slides over bone',
        ['skin_slide'],
        [
            {'check': 'skin_tangential_slide_min', 'region': 'elbow', 'a': 'elbow', 'b': 'wrist', 'min_frac': 0.02},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Around the elbow, does the SURFACE shift and stretch over the bone as the arm bends — or does the whole forearm rotate as one solid piece? yes/no',
            },
        ],
        ALL3,
        dials={'action': 'reach', 'amplitude': 'wide and open'},
        state_note='rigid rotation gives exactly zero tangential slide; 2 % of forearm length is the smallest slide a viewer can see. This is the column where a bone-weighted SkinnedMesh must read `no` and the écorché layer, which is the body surface re-bound to the same skeleton, will read `no` with it — the receipt that the layers are anatomy for LOOKING at, not a deformer.',
    ),
    _p(
        'm_joint_bulge',
        'Joints bulge and crease correctly',
        ['joint_bulge'],
        [
            {
                'check': 'cross_section_growth_min',
                'joint': 'elbow',
                'side': 'flexor',
                'open_deg': 170,
                'closed_deg': 35,
                'min_ratio': 1.06,
                'max_loss': 0.25,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'At the fully bent elbow, is there a crease on the INSIDE and a fuller shape on the outside — the way a real arm folds — with no collapsed or pinched geometry? yes/no',
            },
        ],
        ALL3,
        dials={'action': 'reach', 'repeat': 'twice'},
        state_note='the flexor side must gain at least 6 % cross-section as the elbow closes while the extensor side loses no more than 25 % — the second half is the candy-wrapper failure, where a rig pinches instead of folding. Both readings go in the cell even when the verdict is a no.',
    ),
    _p(
        'm_soft_tissue',
        'Soft tissue jiggles',
        ['soft_tissue'],
        [
            {
                'check': 'oscillation_hz_range',
                'signal': 'soft_tissue_landmark_displacement',
                'min_hz': 1.0,
                'max_hz': 6.0,
                'min_share': 0.4,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'When the body lands or stops, does any soft part keep moving for a moment — a settle or a wobble — instead of everything freezing at once? yes/no',
            },
        ],
        ALL3,
        dials={'action': 'jump', 'weight': 'heavy and grounded'},
        pose='squat',
        state_note='1-6 Hz is the band real soft tissue settles in. The signal is the residual displacement of the soft-tissue landmarks after the rigid body motion is subtracted, so a whole-body bounce does not count as jiggle. Neither rig row has a jiggle deformer and both are expected to read `no`.',
    ),
    _p(
        'm_cloth',
        'Cloth responds to the body',
        ['cloth'],
        [
            {'check': 'flow_region', 'region': 'the loose cloth', 'min': 0.8},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does the clothing move BECAUSE of the body — following the limb, swinging late, settling after it stops — rather than being painted on or flapping on its own? yes/no',
            },
        ],
        ['prompt_muscle', 'blender_rig'],
        dials={'action': 'turn_r', 'amplitude': 'wide and open'},
        still=SUBJ % 'cloth_folds',
        state_note='optical flow inside the cloth mask must exceed the still-image floor (the garment must move at all) before the operator is asked whether it moves because of the body. The anatomy_layers row is na: the layers are skeleton and écorché, with no garment in the scene.',
    ),
    _p(
        'm_volume',
        'Volume is preserved',
        ['volume'],
        [{'check': 'mesh_volume_drift_max', 'mesh': 'body', 'max_frac': 0.03, 'sample': [0, 20, 40, 60, 80]}],
        ['blender_rig'],
        dials={'action': 'reach'},
        state_note='the one column on this sheet that can be measured exactly, on the one row that has a mesh: trimesh signed volume of the evaluated body mesh, per frame, within 3 % of the rest pose. No operator question — there is nothing for an eye to add to a volume. The two other rows are na for lack of a mesh.',
    ),
    # ── Evidence ─────────────────────────────────────────────────────────────────────────────
    _p(
        'm_consistent',
        'Consistent across a clip',
        ['consistent'],
        [
            {
                'check': 'keypoint_ratio_stable',
                'a': 'acromion_L..acromion_R',
                'b': 'ribcage_width_at_sternal_angle',
                'max_drift': 0.06,
                'sample': [0, 20, 40, 60, 80],
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Across the whole clip, does this stay ONE body — the same build, the same thickness of limb, nothing swelling or shrinking between the start and the end? yes/no',
            },
        ],
        ALL3,
        dials={'action': 'work', 'repeat': 'twice'},
        state_note='the same ratio that caught the clavicle defect on the movement sheet ([[project_movement_stance_chest_fix]]): shoulder width over ribcage width at the sternal angle may drift 6 % of its own median. A rig row holds this by construction and the cell records that as the control the pixel row is read against.',
    ),
    _p(
        'm_body_types',
        'Works across body types',
        ['body_types'],
        [
            {
                'check': 'track_ratio_within',
                'metric': 'shoulder_hip_frac',
                'target': "the value measured on that subject's own still at frame 0",
                'tol': 0.08,
                'share': 0.9,
                'sample': [0, 20, 40, 60, 80],
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this body keep the BUILD it started with — a heavy body staying heavy, a lean one staying lean, an old one not turning young — while it moves? yes/no',
            },
        ],
        ALL3,
        grid={'subject': ['person_one', 'muscle_flex', 'elderly']},
        dials={'action': 'work', 'weight': 'heavy and grounded'},
        state_note="three builds off the bank's approved stills — an ordinary adult, a muscular body and an aged body — because no rack token asks for a build and the still is the only way to set one. Shoulder-over-hip width from the subject's OWN frame 0 is the reference, so the check measures drift from the given body rather than against an average. On the rig rows the three builds are the base bodies reached with proxy_actor --fit, which is why this column is BLOCKED with the rig fixture.",
    ),
    _p(
        'm_child_muscle',
        'Works on a child body',
        ['child_muscle'],
        [
            {
                'check': 'masked_width_ratio_min',
                'region': 'upper arm',
                'at_frac': 0.5,
                'relaxed': 0,
                'peak': 40,
                'min_ratio': 1.04,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': "Does this read as a CHILD's body under effort — a child's softer, less defined muscle — rather than a small adult with adult definition? yes/no",
            },
        ],
        ALL3,
        dials={'action': 'work', 'intensity': 'extreme'},
        still=SUBJ % 'child',
        state_note='the flex bar drops from 1.08 to 1.04 because a child of twelve genuinely has less to show, and a test that demanded adult definition would reward the wrong answer. BLOCKED: the fitted Abel rig is `clamped`, not exact — the leg wants x0.753 and is pinned at the 0.800 clamp, worst 5.50 % (2026-09-24) — so today the reference child has adult legs.',
    ),
]

TEST = {
    'step': 'muscle',
    'version': '2026-09-30.1',
    'title': 'Flex, breath and volume as numbers, on the sheet that has never been measured',
    'purpose': (
        'Turn the fifteen columns of the emptiest sheet on the tab into readings: a masked width ratio for flex, an '
        'FFT band for breathing and for jiggle, a cross-section for the elbow fold, trimesh volume on the one row with '
        'a mesh, and a blind operator question beside every one of them. The `measured` column records, as a lookup, '
        'that before this test nothing here had been measured at all.'
    ),
    'include_shared': 'video',
    'fixed': FIXED,
    'rows': {
        'prompt_muscle': {
            'transport': 'service',
            'model': 'movement_studio.py (RACKS/_PARAMS weight, breathing, intensity, posture -> compose_prompt -> render_kwargs) -> wan_vace_service.generate_vace_static_clip',
            'note': 'the only row that can be ASKED for effort, and it can only be asked in words — there is no muscle parameter anywhere in the racks, only weight/breathing/intensity/posture.',
        },
        'anatomy_layers': {
            'transport': 'service',
            'model': "Movement Studio anatomy layers — studio_ext/movement_rig_anatomy.js solved over studio_ext_server/movement_rig.py ops: 262 joints and 192 links over the cmu_mb rig's 31 channels, BONES = 135 CC0 anatomical pieces as a SkinnedMesh in the GLB (skelAdopt), MUSCLES = the écorché body inset 1.5 mm wearing the male_ecorche atlas [[project_movement_anatomy_layers]]",
            'na_bands': dict(RIG_NA_BANDS),
            'budget': {
                'calls': 27,
                'minutes': 48,
                'gpu_minutes': 6,
                'operator_minutes': 22,
                'note': 'no bank renders (those bands are na): 9 domain probes x 3 repeats = 27 viewport captures of 81 frames each, ~90 s a capture including the layer solve, plus SAM2 and the FFT off-GPU. The 3 repeats are identical by construction and are kept as the determinism control.',
            },
        },
        'blender_rig': {
            'transport': 'blender',
            'where': 'blender_scripts/proxy_actor.py + blender_scripts/skeleton_bind.py in the mesh studio — armature deformation on the fitted rig, evaluated mesh per frame, rendered headless with `blender -b --python` under the studio lock',
            'na_bands': dict(RIG_NA_BANDS),
            'budget': {
                'calls': 30,
                'minutes': 96,
                'gpu_minutes': 30,
                'operator_minutes': 22,
                'note': '10 domain probes (volume included) x 3 repeats = 30 headless runs of 81 frames, ~3 min each including the per-frame mesh evaluation trimesh needs; the render itself is the cheap half.',
            },
        },
    },
    'probes': PROBES,
    'derive': {},
    'lookup': {
        'layers': {
            'question': 'Anatomy layers exist',
            'requires': [
                "studio_ext/movement_rig_anatomy.js (2026-09-23/24): the JOINTS layer, 262 joints and 192 links solved in code from the cmu_mb rig's 31 channels",
                'the BONES layer: 135 CC0 anatomical pieces bound as a real SkinnedMesh to those same 31 joints and shipped inside the GLB, adopted by skelAdopt() — see memory/skeleton_bind.md for the fit receipts',
                'the MUSCLES layer: the écorché, the body geometry re-bound to the body skeleton and inset 1.5 mm, wearing the male_ecorche atlas built by char_photoreal.py (look: ecorche)',
                'the absence receipt: no clip in this house carries finger or toe channels, so the hand and foot pieces of the BONES layer are carried, never driven',
            ],
            'grade': 'receipt',
            'note': (
                'a lookup, not a probe: whether the layers EXIST is a fact about the repo, answered by naming the three '
                'layers, their joint counts and where each is built. Whether they DEFORM like flesh is the skin_slide, '
                'joint_bulge and volume columns, and those are probes on the same rows. The cell must not be read as '
                '"anatomy works" — it says the layers are there, solved and visible, and nothing more.'
            ),
        },
        'measured': {
            'question': 'Anyone has measured it',
            'requires': [
                'this sheet, 2026-09-30: no cell on the muscle sheet carries a measured value — the columns were described and hoped for, never run',
                "the movement receipts that DO exist and are the nearest thing: A-pose toe-out leaked through the delta retarget and the clavicles drove the chest wall ([[project_movement_stance_chest_fix]], 2026-09-24) — both found by eye, then written down, neither ever thresholded until the movement sheet's test",
                'the fit receipts in memory/skeleton_bind.md and memory/base_body_rig.md: trunk-depth least squares, the female rig\'s broken hip joint, "green checks are not proof" — measurements of FIT, not of flesh under load',
                'the honest consequence: until this TEST is run, `measured` is `no` on every row, and the note is this list',
            ],
            'grade': 'receipt',
            'note': (
                'the one column that must answer about US rather than about a model, so it is a lookup and its honest '
                'value today is a no with the receipts attached. The first run of this test is what changes it, and the '
                "note must then be rewritten to cite that run's hash rather than this list."
            ),
        },
    },
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': RIG,
            'verified': False,
            'blocks': ['child_muscle', 'body_types'],
            'generated': (
                'flock /tmp/claude-1000/arch_ext_blender.lock blender -b --python blender_scripts/proxy_actor.py -- '
                '--body base --char c3345deb5bde --motion cmu/02_01 --fit  &&  blender -b --python '
                'blender_scripts/rig_export_glb.py -- --actor c3345deb5bde__cmu_02_01  &&  cp '
                'data/architecture/actors/c3345deb5bde__cmu_02_01/*.glb '
                + RIG
                + '   (the SAME file the movement sheet declares — one fixture, two sheets, never two copies)'
            ),
            'how_to_verify': (
                'read the actor sidecar and require fit.status == "exact" with fit.ok true. On 2026-09-24 it is '
                '"clamped", ok false, worst 5.50 %: the LEG wants x0.753 and is pinned at the 0.800 clamp, so the '
                "damped solve diverges and keeps pass 1. Until a child base body exists, a child's flesh must not be "
                'graded against a rig with adult legs, and neither must the three builds of body_types.'
            ),
        },
    ],
    'run_order': [
        'm_volume',
        'm_consistent',
        'm_joint_bulge',
        'm_skin_slide',
        'm_breath',
        'm_soft_tissue',
        'm_flex',
        'm_fatigue',
        'm_cloth',
        'm_weight',
        'm_strain',
        'm_child_muscle',
        'm_body_types',
    ],
    'budget': {
        'calls': 583,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'no language model is called anywhere on this sheet: the prompt row assembles its sentence from rack option strings through movement_studio.compose_prompt, and the two rig rows take a joint-angle table instead of a prompt',
        'minutes': 1830,
        'gpu_minutes': 1800,
        'operator_minutes': 418,
        'note': (
            'DOMAIN, prompt_muscle: 11 single-cell probes x 3 seeds = 33 renders, plus fatigue 3 rungs x 3 = 9 and '
            'body_types 3 subjects x 3 = 9, and volume is na on this row: 51 renders. At 832x480, 81 frames, 30 steps a Wan '
            'clip is ~3 min on the 24 GB card = 153 min, plus SAM2 masks and the FFT/trimesh reads (~30 s a clip) = 26 min. '
            'SHARED BANK, prompt_muscle only: the 132 subjects x 3 seeds = 396 renders plus ~136 capacity, spatial and '
            'prompt-variant renders = 532 x 3 min = 1596 min. So the prompt row is ~583 calls and ~1775 min; the two rig rows '
            "override with 27 and 30 calls because the bank's bands are na on them, which is why the sheet total is far "
            'below three times this row. OPERATOR: domain 12 probes x 3 seeds = 36 blind decisions plus fatigue 9 and '
            "body_types 9 = 54, ~27 min; the bank's 132 subjects x 2 questions x 3 seeds = 792 decisions ~396 min; ~418 min "
            'on the prompt row and ~22 min on each rig row. Whole sheet: ~1975 min GPU (~33 h) and ~7.7 h of blind operator '
            'time. No claude_cli or anthropic_api row, so the shared Claude week is untouched by this sheet.'
        ),
    },
    'notes': [
        'Nine of the fifteen domain columns are expected to read `no` on the two rig rows, and that is the point: a SkinnedMesh weighted to 31 joints cannot slide skin, bulge a joint or jiggle, so the cells should say so with a number beside them rather than be excused as na. An na here would hide exactly what the sheet is for.',
        'The rack has no muscle parameter. `weight`, `breathing`, `intensity` and `posture` are the whole vocabulary this house has for effort, so every prompt-row trial is really a test of those four tokens — if a column fails on prompt_muscle the first question is whether any token was capable of asking for it.',
        "Shift is never varied on the prompt row (on Wan shift is how much the model moves at all [[project_wan_motion_debug]]); the row's production shift is recorded into every trial instead.",
        '81 frames at 17 fps is 4.8 s, which is one full breath cycle at 0.2 Hz and no more. `breath_body` therefore reports a peak frequency from a single cycle and the cell must carry that caveat; a longer clip is the first thing to change if the column matters.',
        "The Abel rig fixture is SHARED with the movement sheet by path. If a runner regenerates it, both sheets' blocked columns unblock together and both must record the same fit.status — a rig that is `exact` for one sheet and `clamped` for the other means someone copied a second file over it.",
    ],
}
