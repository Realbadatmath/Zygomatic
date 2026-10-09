# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Movement & action (movement). 2026-09-30.

Question the sheet asks: "Can we ask for a specific action and get that action?" The sheet's own
note says the central column, `obeyed`, "has never been scored — it is judged by eye, shot by
shot", and its `next_tests` line asks for exactly one thing: pick actions from the library,
render three seeds each, and have the operator name the action BLIND. That is what this test is,
with the six rack ladders and the body defects added as mechanical measurements beside it.

The shape of the test
---------------------
One fixed still (the video bank's approved `person_one` subject) and one fixed dial state per
trial, taken VERBATIM from movement_studio.RACKS: the action prompt string out of ACTIONS_LIB,
the rack option strings out of `_PARAMS[key]['options']`. The runner calls
movement_studio.compose_prompt() on that dial state and submits whatever sentence it returns —
never a second, prettier copy — then runs geom.pose_track over the finished clip at the render
fps and reads the body numbers off the track, not off a model's opinion of the clip.

What is measured mechanically and what the operator decides
----------------------------------------------------------
No local VLM judges a clip (defect judge bench 2026-09-27: 34/40 on a global question, 2/8 on
the hard cases), so "does this clip perform the named action" is a BLIND operator yes/no. Every
column that has a real detector gets it too, and the `state_note` says which decides:
  * the six control ladders are pure geometry — a metric read off the pose track must MOVE with
    the rung (`track_metric_monotonic`); a flat ladder means the rack token is inert;
  * `stance` is the 2026-09-24 defect written as a number: A-pose toe-out leaked through the
    delta retarget, so the foot axis must sit within ±8° of neutral
    ([[project_movement_stance_chest_fix]]);
  * `chest` is the other half of that defect: the clavicles drove the chest wall, so the
    shoulder-to-ribcage width ratio must hold across the clip;
  * `ground` is `foot_slide_max` — the skating failure, measured on the ankle during stance;
  * `limb_cross` is MediaPipe keypoint confidence staying up while the arms cross (the merge
    failure), NOT a model's opinion that the arms look separate;
  * `two_actors` is `track_identity_swap == 0` on the IoU-continuity track.

What is blocked and why
-----------------------
Two fixtures do not exist. The Movement Studio FITTED Abel rig is `verified: False` and blocks
`child_body`: the fit is `clamped`, not exact — the leg wants x0.753 and is pinned at the 0.800
clamp, worst 5.50 % (2026-09-24), so today the "child" rig has adult legs and grading a child
body against it would be grading the base body's proportions. The six operator reference clips
(the driver for the wan_animate_drv row) block `two_actors`, the one column no rack token can
produce on either row.

`smpl_family` is a retired row: SMPL and AMASS are non-commercial and AMASS taints anything
fitted through it ([[project_movement_base_models_research]]). It keeps its place on the sheet
so the sheet keeps the receipt for why it is not used.
"""

from __future__ import annotations

# ── check kinds this module adds (each names what is measured, against what, and the field
#    that carries the threshold; the runner is a table of these) ─────────────────────────────
CHECK_KINDS = {
    'rack_has': 'every id in `actions` resolves to an entry of movement_studio.ACTIONS_LIB and every value in `values` to an option of movement_studio._PARAMS[`key`]["options"] — read off the module, nothing rendered',
    'track_metric_monotonic': "the named `metric` read off geom.pose_track track.json moves with the rungs in `rungs` order, every consecutive step changing by >= `min_step` (a fraction of the first rung's value); a flat or inverted ladder fails",
    'toe_out_angle_max': "the angle between each foot's heel-to-toe axis and the pelvis forward axis, from the track's foot keypoints, is within `max_deg` of `neutral_deg` in >= `share` of the frames in `sample`",
    'foot_slide_max': "during stance frames (an ankle whose height is within `stance_tol_frac` of its own minimum) that ankle's horizontal travel is <= `max_px_per_frame`, normalised to a shoulder width of 100 px",
    'keypoint_ratio_stable': 'the ratio of the track distances `a` and `b` (named keypoint pairs or vertex bands) stays within `max_drift` of its own median across the frames in `sample`',
    'keypoint_excursion_frac': 'the peak-to-peak displacement of `keypoint` along `axis` (x|y) is between `min_frac` and `max_frac` of the figure bounding-box height, over the frames in `sample`',
    'support_offset_max': 'the horizontal distance from the hip centroid to the midpoint of the two ankle keypoints stays <= `max_frac` of the figure bbox height, outside frames the track flags airborne',
    'landmark_confidence_min': 'MediaPipe pose landmark visibility for every joint in `joints` stays >= `min` in >= `share` of the frames in `sample` (a merged limb collapses this, a correct crossing does not)',
    'track_identity_swap': "the number of frames in which the two subject tracks exchange identity (an IoU-continuity break in geom.pose_track's box chain) is <= `max`",
    'track_distance_max': 'mean per-joint 2D distance between the pose tracks of two runs at the SAME settings and seed is <= `max_px`, normalised to a shoulder width of 100 px',
    'track_yaw_delta': 'the pelvis yaw estimated from the track changes by between `min_deg` and `max_deg` between the first and last frame while the hip centroid travels < `max_travel_frac` of the bbox height',
    'object_follows_hand': 'the Pearson correlation between the per-frame displacement of the `object` mask centroid (SAM2, box-prompted with the object word) and of the `keypoint` is >= `min_corr`, and the gap between them stays within `max_gap_frac` of the bbox height',
    'keypoint_y_travel': 'the `keypoint` travels >= `min_frac` of the figure bbox height in `direction` (down|up) and, when `returns` is set, comes back within `return_tol_frac`',
    'keypoint_still': 'the per-frame displacement of `keypoint` stays <= `max_px_per_frame` (shoulder width normalised to 100 px) over the frames in `sample`',
    'track_ratio_within': 'the body proportion `metric` (head_frac|leg_frac|shoulder_frac) measured off the track is within `tol` of `target` in >= `share` of the frames in `sample`',
}

# ── the fixed inputs ─────────────────────────────────────────────────────────────────────
SUBJ = 'capability_tests/fixtures/video/subjects/%s.png'  # the video bank's approved stills
STILL = SUBJ % 'person_one'
FX = 'capability_tests/fixtures/movement'
RIG = FX + '/abel_fitted.glb'
CLIPS = FX + '/CLIPS.json'

# Everything not named in a probe's `dials` is the rack DEFAULT (movement_studio._PARAMS[k]['def']),
# so a trial differs from the baseline in exactly the tokens under test.
BASE_DIALS = {
    'action': 'walk',
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
    'shift': "the row's PRODUCTION default, recorded into every trial — on Wan shift IS the motion lever, so a shift change is a different test [[project_wan_motion_debug]]",
    'prompt_rule': (
        "the runner builds the dial state from BASE_DIALS updated with the probe's `dials`, calls "
        'movement_studio.compose_prompt() and submits EXACTLY the sentence it returns; that sentence, the '
        'dial state and the resolved render_kwargs all go into the trial'
    ),
    'track': (
        'geom.pose_track on the finished clip at the render fps (17 unless the row renders at another), '
        '--smooth savgol; every body number below is read off track.json / track_arrays.npz. Distances are '
        'normalised to a shoulder width of 100 px so a 480p and a 720p row are comparable.'
    ),
    'negative': 'the rack default negative_prompt, recorded per trial; never edited per probe',
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
    'track': 'geom.pose_track, savgol',
    'note': 'three seeds, one dial state; the FIRST seed is what first_take reads',
}
COND_LADDER = dict(
    COND,
    note='three seeds at EVERY rung; the ladder is scored on the rung medians, so a single bad seed cannot invert it',
)
COND_TWICE = dict(
    COND,
    repeats=6,
    note='the same dial state and the same three seeds submitted TWICE (six runs) — repeat compares run A to run B seed for seed',
)

STATE_3OF3 = {'yes': 1.0, 'partial': 0.6}  # yes at 3/3 seeds, partial at 2/3
STATE_LADDER = {'yes': 1.0, 'partial': 0.5}  # a ladder is right or it is not; half = one rung inert

W = ['wan_prompt', 'wan_animate_drv']
WP = ['wan_prompt']

# The eight named actions `obeyed` is scored on, each with the operator's written question. The
# prompt string is the ACTIONS_LIB entry VERBATIM (movement_studio.ACTIONS_LIB, 2026-09-30).
ACTIONS8 = [
    (
        'walk',
        'walks forward with a full walking cycle',
        'Does the figure WALK — both feet leaving and meeting the ground in turn, legs alternating? yes/no',
    ),
    ('run', 'runs', 'Does the figure RUN, with a flight phase where neither foot is down? yes/no'),
    (
        'wave',
        'raises one arm and waves',
        'Does the figure WAVE — one arm raised and the hand moving side to side? yes/no',
    ),
    ('sit', 'sits down', 'Does the figure SIT DOWN, ending lower than it started and supported? yes/no'),
    ('standup', 'stands up', 'Does the figure STAND UP from a lower position to standing? yes/no'),
    ('crouch', 'crouches', 'Does the figure CROUCH — hips dropping with the feet staying put? yes/no'),
    ('throw', 'throws', 'Does the figure THROW — a wind-up and a release with one arm? yes/no'),
    ('clap', 'claps', 'Does the figure CLAP — both hands meeting in front of the body, more than once? yes/no'),
]


def _p(pid, title, feeds, checks, rows, dials=None, still=STILL, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {
            'fixture': still,
            'prompt': 'movement_studio.compose_prompt(BASE_DIALS + dials)',
            'dials': dict(BASE_DIALS, **(dials or {})),
        },
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': list(rows),
        'state_rule': dict(STATE_3OF3),
    }
    p.update(kw)
    return p


def _ladder(pid, col, key, rungs, metric, min_step, action, note):
    """One rack parameter, three rungs, one track metric that must move with them."""
    return {
        'id': pid,
        'title': 'The %s rack is obeyed' % key,
        'feeds': [col],
        'inputs': {
            'fixture': STILL,
            'prompt': 'movement_studio.compose_prompt(BASE_DIALS + {action, %s})' % key,
            'dials': dict(BASE_DIALS, action=action),
        },
        'grid': {key: list(rungs)},
        'conditions': dict(COND_LADDER),
        'grade': 'measured',
        'rows': list(WP),
        'state_rule': dict(STATE_LADDER),
        'checks': [
            {'check': 'rack_has', 'key': key, 'values': list(rungs), 'actions': [action]},
            {'check': 'track_metric_monotonic', 'metric': metric, 'rungs': list(rungs), 'min_step': min_step},
        ],
        'state_note': note,
    }


PROBES = [
    # ── the six rack ladders: pure geometry, no operator, cheapest — run these first ──
    _ladder(
        'lad_speed',
        'speed_ctl',
        'speed',
        ['very slow', 'natural', 'fast'],
        'mean_joint_speed_px_per_frame',
        0.25,
        'wave',
        'mean joint speed must rise across the three rung medians by >= 25 % of the "very slow" value each step. '
        'The rack hint says the frame count is unchanged, so a faster action simply completes earlier — the metric is speed, not duration.',
    ),
    _ladder(
        'lad_intensity',
        'intensity_ctl',
        'intensity',
        ['subtle', 'natural', 'extreme'],
        'joint_displacement_p95_px',
        0.25,
        'wave',
        "the 95th percentile of per-frame joint displacement. Shift is NOT changed between rungs — it is the row's production default — because shift is how much the model will move at all and intensity is what was asked for.",
    ),
    _ladder(
        'lad_amplitude',
        'amplitude_ctl',
        'amplitude',
        ['tight and contained', 'natural', 'wide and open'],
        'wrist_range_of_motion_px',
        0.25,
        'wave',
        "peak-to-peak wrist excursion, which is amplitude independent of speed — the rack hint's own definition.",
    ),
    _ladder(
        'lad_easing',
        'easing_ctl',
        'easing',
        ['out', 'none', 'in'],
        'speed_profile_slope',
        0.25,
        'wave',
        'the rungs are ordered by the SIGN of the speed curve: "ease out" decelerates (negative slope of the per-frame '
        'speed fit), "none" is flat, "ease in" builds (positive). A model that ignores easing gives three flat slopes and fails.',
    ),
    _ladder(
        'lad_repeat',
        'repeat_ctl',
        'repeat',
        ['once', 'twice', 'three'],
        'cycle_count',
        0.5,
        'wave',
        'wrist cycles counted from the zero crossings of the smoothed lateral velocity; the medians must read about 1, 2 and 3.',
    ),
    {
        'id': 'lad_direction',
        'title': 'The direction rack is obeyed',
        'feeds': ['direction_ctl'],
        'inputs': {
            'fixture': STILL,
            'prompt': 'movement_studio.compose_prompt(BASE_DIALS + {action: walk, direction})',
            'dials': dict(BASE_DIALS, action='walk'),
        },
        'grid': {'direction': ['to the left', 'to the right', 'toward the camera']},
        'conditions': dict(COND_LADDER),
        'grade': 'measured',
        'rows': list(WP),
        'state_rule': dict(STATE_LADDER),
        'checks': [
            {
                'check': 'rack_has',
                'key': 'direction',
                'values': ['to the left', 'to the right', 'toward the camera'],
                'actions': ['walk'],
            },
            {'check': 'flow_direction', 'direction': 'left', 'min': 0.6, 'rung': 'to the left'},
            {'check': 'flow_direction', 'direction': 'right', 'min': 0.6, 'rung': 'to the right'},
            {'check': 'flow_direction', 'direction': 'in', 'min': 0.6, 'rung': 'toward the camera'},
        ],
        'state_note': 'direction is not an ordinal ladder, so it is three named flow directions rather than a monotonic metric. Travel is only asked of the walk action — "in place" is the rack default and must give none of the three.',
    },
    # ── the body defects: mechanical, no operator needed for ground ──
    _p(
        'p_ground',
        'Feet stay on the ground',
        ['ground'],
        [
            {'check': 'foot_slide_max', 'max_px_per_frame': 1.5, 'stance_tol_frac': 0.02, 'sample': 'all'},
            {
                'check': 'rack_has',
                'key': 'ground',
                'values': ['natural', 'feet planted', 'full walking cycle'],
                'actions': ['walk'],
            },
        ],
        W,
        dials={'action': 'walk', 'ground': 'full walking cycle'},
        state_note='the skating failure as a number: an ankle in stance may travel at most 1.5 px/frame at a 100 px shoulder width. The rack offers "feet planted" as the fix for a sliding subject; this probe asks for the honest case ("full walking cycle") and records whether "feet planted" rescues it in the note.',
    ),
    _p(
        'p_stance',
        'Stance and posture are correct',
        ['stance'],
        [
            {'check': 'toe_out_angle_max', 'max_deg': 8, 'neutral_deg': 0, 'share': 0.9, 'sample': 'all'},
            {
                'check': 'operator',
                'blind': True,
                'question': "Ignoring everything else, do this figure's FEET point where a standing person's feet point — not splayed outward like a ballet first position? yes/no",
            },
        ],
        W,
        dials={'action': 'idle', 'posture': 'upright'},
        state_note='THE 2026-09-24 DEFECT, written as a threshold: A-pose toe-out leaked through the delta retarget ([[project_movement_stance_chest_fix]]) and nothing measured it. The angle decides; the operator question is the cross-check, because a retarget can also splay the knees without splaying the feet.',
    ),
    _p(
        'p_chest',
        'Chest and shoulders behave',
        ['chest'],
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
                'question': "Does this figure's CHEST keep one shape while the arms move — no rib cage swelling, collapsing or shearing with the shoulders? yes/no",
            },
        ],
        W,
        dials={'action': 'wave', 'amplitude': 'wide and open'},
        state_note="the other half of the 09-24 defect: the clavicles drove the chest wall. Shoulder width over ribcage width at the sternal angle, both from the track's per-frame vertices, may drift 6 % of its own median. A wide wave is the case that exposed it.",
    ),
    _p(
        'p_weight_shift',
        'Weight shifts believably',
        ['weight_shift'],
        [
            {
                'check': 'keypoint_excursion_frac',
                'keypoint': 'hip_centroid',
                'axis': 'x',
                'min_frac': 0.02,
                'max_frac': 0.12,
                'sample': 'all',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does the weight visibly move from one leg to the other — hips shifting over the supporting foot — rather than the whole body drifting sideways? yes/no',
            },
        ],
        W,
        dials={'action': 'walk', 'weight': 'heavy and grounded'},
        state_note='a hip centroid that never moves laterally is a puppet; one that moves more than 12 % of body height is falling over. The band is the mechanical floor; the operator decides believability.',
    ),
    _p(
        'p_balance',
        'Keeps balance',
        ['balance'],
        [
            {'check': 'support_offset_max', 'max_frac': 0.09, 'sample': 'all'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this figure stay balanced throughout — never leaning past the point a real person would fall, and never saved by a limb that teleports? yes/no',
            },
        ],
        W,
        dials={'action': 'lean', 'intensity': 'strong'},
        state_note='the hip centroid must stay within 9 % of body height of the ankle midpoint except in frames the track flags airborne. "lean, strong" is chosen because it asks for the pose that legitimately approaches the limit.',
    ),
    _p(
        'p_limb_cross',
        'Limbs cross without merging',
        ['limb_cross'],
        [
            {
                'check': 'landmark_confidence_min',
                'joints': ['left_wrist', 'right_wrist', 'left_elbow', 'right_elbow'],
                'min': 0.5,
                'share': 0.95,
                'sample': 'all',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'While the arms cross, do they stay TWO arms — no fusing into one limb, no arm passing through the body? yes/no',
            },
        ],
        W,
        dials={'action': 'brace', 'amplitude': 'wide and open'},
        state_note='MediaPipe pose visibility on the four arm joints is the merge detector: a fused limb collapses the confidence of one side, a correct crossing does not. Deliberately NOT a VLM question — the 09-27 bench scored 2/8 on exactly this class of defect.',
    ),
    _p(
        'p_turn',
        'Can turn on the spot',
        ['turn'],
        [
            {'check': 'track_yaw_delta', 'min_deg': 60, 'max_deg': 200, 'max_travel_frac': 0.08},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does the figure TURN — the body rotating about its own axis — rather than sliding or being replaced by a differently-facing figure? yes/no',
            },
        ],
        W,
        dials={'action': 'turn_r', 'direction': 'in place'},
        state_note='pelvis yaw must change by 60-200 degrees while the hip centroid travels less than 8 % of body height. The upper bound catches the spin the model sometimes substitutes for a quarter turn.',
    ),
    # ── interaction ──
    _p(
        'p_carry',
        'Carries an object convincingly',
        ['carry'],
        [
            {
                'check': 'object_follows_hand',
                'object': 'wooden crate',
                'keypoint': 'wrist_mid',
                'min_corr': 0.6,
                'max_gap_frac': 0.12,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is the object CARRIED — held by the hands and moving with the body, never floating, swapping hands or passing through the torso? yes/no',
            },
        ],
        W,
        dials={'action': 'work', 'weight': 'heavy and grounded'},
        still=SUBJ % 'container_barrel',
        state_note='the crate mask centroid and the wrist midpoint must move together (r >= 0.6) and stay within 12 % of body height of each other. A carried object that floats breaks the correlation, not the eye.',
    ),
    _p(
        'p_tool_use',
        'Uses a tool convincingly',
        ['tool_use'],
        [
            {
                'check': 'object_follows_hand',
                'object': 'wooden mallet',
                'keypoint': 'right_wrist',
                'min_corr': 0.6,
                'max_gap_frac': 0.08,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is the tool USED — gripped at the handle and swung or applied to something, rather than held still or morphing? yes/no',
            },
        ],
        W,
        dials={'action': 'work', 'repeat': 'twice'},
        still=SUBJ % 'hand_holding',
        state_note="the bank's hand_holding still (one hand, a wooden mallet) is the input, so the grip is correct at frame 0 and only the motion is under test.",
    ),
    _p(
        'p_sit_stand',
        'Sits and stands',
        ['sit_stand'],
        [
            {
                'check': 'keypoint_y_travel',
                'keypoint': 'hip_centroid',
                'direction': 'down',
                'min_frac': 0.15,
                'returns': True,
                'return_tol_frac': 0.05,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does the figure sit down and then stand up again, with the legs doing the work? yes/no',
            },
        ],
        W,
        dials={'action': 'sit', 'repeat': 'twice', 'easing': 'both'},
        state_note='"sit" twice with easing both is the nearest the rack comes to a sit-and-rise: the hips must drop at least 15 % of body height and return within 5 %. If the row cannot chain the two beats the travel check fails and the note records it as a sequencing limit, not a body limit.',
    ),
    _p(
        'p_stairs',
        'Handles stairs and slopes',
        ['stairs'],
        [
            {
                'check': 'keypoint_y_travel',
                'keypoint': 'hip_centroid',
                'direction': 'up',
                'min_frac': 0.12,
                'returns': False,
            },
            {'check': 'foot_slide_max', 'max_px_per_frame': 2.0, 'stance_tol_frac': 0.03, 'sample': 'all'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does the figure climb the steps — each foot landing on a tread and the body rising step by step — rather than gliding up the staircase? yes/no',
            },
        ],
        W,
        dials={'action': 'climb', 'direction': 'away from the camera'},
        still=SUBJ % 'stairs',
        state_note="the bank's staircase still gives the geometry; the hips must actually rise and the feet must not slide while they carry weight. Gliding up a stair is the classic pass-by-eye failure.",
    ),
    _p(
        'p_two_actors',
        'Two people interacting',
        ['two_actors'],
        [
            {'check': 'track_identity_swap', 'max': 0},
            {
                'check': 'detector_count',
                'detector': 'yolov8n-coco',
                'label': 'person',
                'n': 2,
                'sample': [0, 20, 40, 60, 80],
                'share': 1.0,
            },
            {'check': 'mask_iou_max', 'n': 2, 'max': 0.15, 'sample': [0, 20, 40, 60, 80]},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Are there two separate people throughout — never merging, never exchanging bodies or clothes? yes/no',
            },
        ],
        W,
        dials={'action': 'custom', 'direction': 'in place'},
        still=SUBJ % 'person_two',
        state_note='no ACTIONS_LIB entry produces a two-person interaction, so this probe uses action "custom" with the driver clip named in CLIPS.json ("two men shake hands once and step apart") as the reference for both rows. BLOCKED until those clips exist and are labelled.',
    ),
    _p(
        'p_contact',
        'Contact with a surface reads',
        ['contact'],
        [
            {'check': 'keypoint_still', 'keypoint': 'left_wrist', 'max_px_per_frame': 1.0, 'sample': 'all'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does the hand rest ON the surface — neither sinking into it nor hovering above it — for the whole clip? yes/no',
            },
        ],
        W,
        dials={'action': 'lean', 'ground': 'feet planted'},
        still=SUBJ % 'furniture',
        state_note='a supporting hand is a contact constraint: the wrist may drift at most 1 px/frame while the rest of the body leans. Penetration and hovering are what the operator sees and the number cannot.',
    ),
    # ── the central question, and the three "does it generalise" columns ──
    _p(
        'p_obeyed',
        'The clip performs the named action',
        ['obeyed'],
        [
            {'check': 'motion_min', 'min': 1.2},
            {
                'check': 'operator',
                'blind': True,
                'question': "Per action, the question listed in ACTIONS8 for that action id — asked one clip at a time, the clip's own action never shown beside it. yes/no",
            },
        ],
        W,
        grid={'action': [a[0] for a in ACTIONS8]},
        state_note=(
            "the sheet's own next_tests, executed: eight ACTIONS_LIB actions x three seeds, the operator answering the "
            'written yes/no for that action with the clips anonymised and shuffled. `motion_min` is the floor that '
            'catches the near-still clip Wan produces when it ignores the verb entirely — an almost-static clip is a no '
            'before a human is asked. The operator decides everything above that floor; ACTIONS8 holds the eight questions verbatim.'
        ),
    ),
    _p(
        'p_repeat',
        'Same settings, same movement',
        ['repeat'],
        [{'check': 'track_distance_max', 'max_px': 6.0}, {'check': 'identical_clips'}],
        W,
        dials={'action': 'wave'},
        conditions=dict(COND_TWICE),
        state_note='two submissions of the same dial state and the same seed. `identical_clips` is the strict question (does the pipeline reproduce at all); `track_distance_max` is the useful one — 6 px of mean per-joint difference at a 100 px shoulder width is the same movement even if the pixels differ.',
    ),
    _p(
        'p_child_body',
        'Works on a child body',
        ['child_body'],
        [
            {
                'check': 'track_ratio_within',
                'metric': 'head_frac',
                'target': 0.154,
                'tol': 0.02,
                'share': 0.9,
                'sample': [0, 20, 40, 60, 80],
            },
            {
                'check': 'operator',
                'blind': True,
                'question': "Does this read as a CHILD moving — child proportions kept and a child's gait, not a small adult? yes/no",
            },
        ],
        W,
        dials={'action': 'walk'},
        still=SUBJ % 'child',
        state_note=(
            'head height over stature must stay near 1/6.5 (0.154), the figure a child of eight reads at, rather than the '
            'adult 1/7.5. BLOCKED: the fitted Abel rig this would be compared against is `clamped`, not exact — the leg '
            'wants x0.753 and is pinned at the 0.800 clamp, worst 5.50 % (2026-09-24) — so the reference itself has adult legs.'
        ),
    ),
    _p(
        'p_creature_body',
        'Works on a non-human body',
        ['creature_body'],
        [
            {
                'check': 'detector_count',
                'detector': 'yolov8n-coco',
                'label': 'person',
                'n': 0,
                'sample': [0, 20, 40, 60, 80],
                'share': 1.0,
            },
            {'check': 'motion_min', 'min': 1.2},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does the four-legged creature move like an animal — four legs in a real gait, spine and neck following — without any part of it becoming human? yes/no',
            },
        ],
        W,
        dials={'action': 'walk', 'direction': 'to the left'},
        still=SUBJ % 'creature_invented',
        state_note=(
            "the bank's four-legged horned creature is the non-human body (the wolf case: a canid quadruped with a long "
            'neck). The person detector must find NOBODY — a creature that grows a human torso is the failure this column '
            "exists for, and it is mechanically detectable. Wan2.2-Animate's own card claims a 2D skeleton generalises to "
            'non-humanoids; this is where that claim is measured.'
        ),
    ),
]

# ── what the racks cannot do on a driven row ─────────────────────────────────────────────
DRV_NA = {
    c: "the motion of this row comes from the driver clip's per-frame skeleton, not from a rack token — the timing, the range and the travel are the driver's, so changing a prompt word cannot move this ladder and a measured result would be a property of the clip we recorded"
    for c in ['speed_ctl', 'intensity_ctl', 'amplitude_ctl', 'easing_ctl', 'repeat_ctl', 'direction_ctl']
}
DRV_NA['library'] = (
    'there is no named-action library on this row: the driver clip IS the action, and ACTIONS_LIB is never consulted by wan_animate_service'
)

TEST = {
    'step': 'movement',
    'version': '2026-09-30.1',
    'title': 'Eight named actions blind, six rack ladders measured off the pose track',
    'purpose': (
        'Score the column the sheet says has never been scored — does the clip perform the action we named — by '
        'rendering eight ACTIONS_LIB actions at three seeds and asking the operator blind, and measure the six rack '
        'ladders and the seven body defects as numbers read off geom.pose_track rather than by eye.'
    ),
    'include_shared': 'video',
    'fixed': FIXED,
    'actions_8': [{'action': a, 'summary': s, 'question': q} for a, s, q in ACTIONS8],
    'rows': {
        'wan_prompt': {
            'transport': 'service',
            'model': 'movement_studio.py (RACKS/_PARAMS -> compose_prompt -> render_kwargs) -> wan_vace_service.generate_vace_static_clip, driven by bp_movement._run_job under its one-job lock',
        },
        'wan_animate_drv': {
            'transport': 'service',
            'model': 'wan_animate_service.py — Wan2.2-Animate-14B fp8_scaled (_comfy_workflows/wan22_animate.json), reference still + per-frame MediaPipe skeleton and face crops from a driver clip',
            'na': dict(DRV_NA),
            'budget': {
                'calls': 636,
                'minutes': 2450,
                'gpu_minutes': 2400,
                'operator_minutes': 410,
                'note': 'the six ladders are na on this row (-54 renders), but every clip needs its driver preprocessed first: MediaPipe per frame over 81 frames plus the face crops, ~40 s a clip on top of the render.',
            },
        },
        'smpl_family': {
            'transport': 'retired',
            'model': 'SMPL / SMPL-X / AMASS motion models — never installed on this box',
            'skip': 'RETIRED 2026-09-30: SMPL and AMASS are non-commercial research licences and AMASS taints anything fitted through it, so no output of this family may ship — the row is kept for that receipt ([[project_movement_base_models_research]]). Wan2.2-Animate was chosen partly because a 2D skeleton avoids a body model altogether.',
            'budget': {
                'calls': 0,
                'tokens_in': 0,
                'tokens_out': 0,
                'minutes': 0,
                'gpu_minutes': 0,
                'operator_minutes': 0,
                'note': 'a retired row is never run: nothing is rendered, nothing is judged, no GPU and no operator time. It costs the reading of one licence page.',
            },
        },
    },
    'probes': PROBES,
    'derive': {},
    'lookup': {
        'library': {
            'question': 'A named action is reachable',
            'requires': [
                'movement_studio.ACTIONS_LIB — 56 entries on 2026-09-30, each with an id, a group and a real prompt string: '
                'idle, stand_alert, brace, sway, shiver, walk, run, sneak, approach, retreat, pace, stagger, climb, swim, fly, '
                'turn_l, turn_r, spin, lookover, lookup, lookdown, wave, point, beckon, reach, grab, nod, shake_head, shrug, clap, '
                'bow, sit, standup, crouch, kneel, lean, recoil, react, laugh, cry, sigh, think, talk, yawn, jump, strike, dodge, '
                'fall, throw, dance, work, obj_rotate, obj_bounce, obj_float, obj_topple, custom',
                'movement_studio.RACKS — 12 racks; the motion rack carries speed/intensity/amplitude/style/easing/repeat and the space rack direction/distance/facing/scale_change/ground/environment',
                'the check kind `rack_has`: the runner resolves every action id and every rung value against the live module, so the cell fails the day an id is renamed',
            ],
            'grade': 'receipt',
            'note': (
                'a lookup, not a probe: "is the action in the library" is a fact about the module, answered by reading it, and '
                'whether the library ENTRY works is the `obeyed` column. The cell records the count and the resolved ids. '
                'The wan_animate_drv row has no library at all and is na.'
            ),
        },
    },
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': RIG,
            'verified': False,
            'blocks': ['child_body'],
            'generated': (
                'flock /tmp/claude-1000/arch_ext_blender.lock blender -b --python blender_scripts/proxy_actor.py -- '
                '--body base --char c3345deb5bde --motion cmu/02_01 --fit  &&  blender -b --python '
                'blender_scripts/rig_export_glb.py -- --actor c3345deb5bde__cmu_02_01  &&  cp '
                'data/architecture/actors/c3345deb5bde__cmu_02_01/*.glb ' + RIG
            ),
            'how_to_verify': (
                'read the actor sidecar and require fit.status == "exact" with fit.ok true. On 2026-09-24 it is '
                '"clamped", ok false, worst 5.50 %: the LEG wants x0.753 and is pinned at the 0.800 clamp, so the '
                "damped solve diverges and keeps pass 1. Adult legs on a child's metrics is a base-body limit, not a "
                'solver bug — until a child base body exists, child_body must not be graded against this rig.'
            ),
        },
        {
            'path': CLIPS,
            'verified': False,
            'blocks': ['two_actors'],
            'generated': (
                'the operator records six reference clips at 832x480, >= 81 frames, static camera, and writes '
                'CLIPS.json = {"clips": [{"file": "ref_<n>.mp4", "action": "<one of the ACTIONS8 ids or \'two_handshake\'", '
                '"actors": 1|2, "fps": <native>}], "verified": false}. The six: walk, sit-and-rise, climb three steps, '
                'carry a crate, a hand resting on a table, and two men shaking hands once and stepping apart. They are the '
                'DRIVER for wan_animate_drv and the only source for the two-actor case on either row.'
            ),
            'how_to_verify': (
                'run geom.pose_track over each clip, confirm the track holds one box chain per actor with no '
                'identity swap, check that the written action label is what the clip shows, then set verified true. '
                'Until then the wan_animate_drv row cannot be run at all — it has no driver.'
            ),
        },
    ],
    'run_order': [
        'lad_speed',
        'lad_intensity',
        'lad_amplitude',
        'lad_easing',
        'lad_repeat',
        'lad_direction',
        'p_ground',
        'p_stance',
        'p_chest',
        'p_repeat',
        'p_limb_cross',
        'p_turn',
        'p_weight_shift',
        'p_balance',
        'p_obeyed',
        'p_creature_body',
        'p_child_body',
        'p_sit_stand',
        'p_stairs',
        'p_contact',
        'p_carry',
        'p_tool_use',
        'p_two_actors',
    ],
    'budget': {
        'calls': 679,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'no language model is called: the prompt is assembled from rack option strings by movement_studio.compose_prompt, so there are no prompt or completion tokens to spend',
        'minutes': 2127,
        'gpu_minutes': 2100,
        'operator_minutes': 430,
        'note': (
            'DOMAIN, per row: 6 ladders x 3 rungs x 3 seeds = 54 renders; obeyed 8 actions x 3 seeds = 24; repeat 2 runs x 3 '
            'seeds = 6; the 13 remaining body/interaction probes x 3 seeds = 39; child_body 3 + creature_body 3 = 129 renders. '
            'At 832x480, 81 frames, 30 steps a Wan clip is ~3 min on the 24 GB card = 387 min, plus geom.pose_track over each '
            'clip (~40 s) = 86 min. SHARED BANK, per row: the 132 subjects x 3 seeds = 396 renders plus ~154 ladder, scene and '
            'prompt-variant renders = 550 renders x 3 min = 1650 min. Total ~679 calls and ~2127 min (~35 h) of which ~2100 min '
            "hold the GPU, PER ROW. OPERATOR: domain 24 (obeyed) + 14 probes x 3 seeds = 66 blind decisions ~33 min; the bank's "
            '132 subjects x 2 questions x 3 seeds = 792 decisions ~396 min; ~430 min per row. Three rows, one of them retired, so '
            'the sheet costs ~2 x 35 h of GPU and ~14 h of blind operator time — schedule it as two nights, not an afternoon. No '
            'claude_cli or anthropic_api row here, so the shared Claude week is untouched.'
        ),
    },
    'notes': [
        'The sheet\'s next_tests asked for exactly one thing — twelve actions, three seeds, the operator naming them blind. This test does eight actions (three seeds) with the question written per action, because a written yes/no is scoreable and "name it" is not, and spends the difference on the six rack ladders, which are cheaper and entirely mechanical.',
        'A rack token that does not move its metric is an INERT LEVER, which is the thing movement_studio.py\'s own docstring forbids ("no inert levers"). The ladders are therefore a test of this house\'s code as much as of the model, and a flat ladder must be reported against the studio, not against Wan.',
        "Shift is never varied. On Wan, shift is how much the model will move at all, so a shift change is a different test [[project_wan_motion_debug]]; the row's production shift is recorded into every trial instead.",
        "SOMA's zero pose is not a T-pose ([[project_movement_capture_path]]). Nothing here compares a rendered clip to a capture rest pose, so that trap cannot reach these numbers — but a runner that ever imports a capture rig as the neutral for toe_out_angle_max would reintroduce it. The neutral for stance is the pelvis forward axis of the same frame, nothing external.",
        'wan_animate_drv cannot be run until CLIPS.json and the six reference clips exist: it has no driver without them. That is a fixture gap, not an na — the row keeps every column it can answer.',
    ],
}
