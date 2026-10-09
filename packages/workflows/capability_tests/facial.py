# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Facial performance (facial). 2026-09-30.

Question the sheet asks: "Can we drive a face, and can we measure when it melts?"

The sheet's own note already says the uncomfortable half of the answer: we can MEASURE a
face falling apart better than we can DRIVE it, and only the mouth has a driver at all.
This test is built so that finding is a MEASUREMENT rather than an opinion. Three rows,
two kinds of row:

  * two DRIVERS — `infinitetalk_face` (lipsync_service.lipsync: a still plus a wav, the
    mouth audio-driven through InfiniteTalk at 25 fps) and `prompt_face` (movement_studio
    compose_prompt → wan_vace_service.generate_vace_static_clip: the face directed in
    words). Every "can X be driven" column is a fixed direction given through the row's
    OWN channel, measured against the same row's NEUTRAL take on the same still.
  * one MEASURER — `facemesh` (anatomy_qc.qc_face_clip, MediaPipe 478-point face mesh,
    CPU, zero VRAM). It drives nothing, so every driving column is `na` on that row with
    the reason written out, and the whole Moves subject bank plus the prompt bands are
    `na` too. What it DOES answer is the other half of the sheet: melt, ghost, identity
    drift and jitter as "does it DETECT", scored against the operator's blind labels on
    the very clips the two driver rows produced in this same run.

So melt / ghost / identity / jitter each carry ONE probe with TWO questions in it, split by
`row_checks`: "does it happen" on the drivers (a frame count plus the operator's blind
label) and "does it get detected" on the mesh (agreement with that same label, with a
yes-rate ceiling so a detector that flags everything cannot score well). Same column, same
clips, two questions, and the mesh is never graded against its own opinion.

Honest judging. No local VLM decides whether a face is right — our own defect bench
(2026-09-27) scored the best local model 34/40 on a global "is anything wrong" question
and 2/8 on the hard cases. Every subjective question here is a BLIND operator decision
with the question and the answer list written down, and every mechanical signal that
exists is taken from anatomy_qc's face mesh (mouth_open_ratio, brow distance, iris offset,
yaw_proxy, the three _FACE_BANDS ratios, ECC-compensated jitter) or from ArcFace
(insightface buffalo_l) for identity. Where both exist, both run and `state_note` says
which decides.

BLOCKED. The four speech lines do not exist yet: they are generated from the cast voices
and nobody has verified that the emotional delivery is what the filename claims. Until the
operator signs each line off, `mouth` (the a/v sync span marks) and `joy` / `grief_face` /
`effort` (an operator who cannot name the emotion may be hearing a bad line, not seeing a
bad face) are written `untested — key unverified`.

Included bank: video. The Render band is not asked on this step; the Moves subject bank,
Capacity, Space & relation, the four prompt bands and the universal columns all come from
capability_tests/video_shared.py, and its 132-subject ladder is the bulk of the budget.
"""

from __future__ import annotations

FX = 'capability_tests/fixtures/facial'
STILL = FX + '/stills'
LINE = FX + '/lines'

# ── new check kinds this step needs. The runner implements exactly these; the validator
# unions them into the vocabulary and lists them in the summary. Every one of them is a
# number read off a face mesh or an audio envelope — none of them is a model's opinion.
CHECK_KINDS = {
    'av_sync_lag_ms': (
        "cross-correlate the face mesh's per-frame `mouth_open_ratio` series "
        "(anatomy_qc._face_metrics) against the driving wav's 50 Hz RMS envelope; "
        'the lag of the peak satisfies |lag| <= `max` ms AND the correlation at that '
        'lag is >= `min_r`'
    ),
    'mouth_closed_in_silence': (
        "mean `mouth_open_ratio` over the frames inside the fixture's declared "
        'silent span <= `max`, and over the declared speech spans >= `min_speech` '
        '(both in inter-ocular units)'
    ),
    'landmark_delta_min': (
        'the named face-mesh distance `metric` (inter-ocular units) on the directed take '
        "differs from the SAME row's neutral take on the same still by >= `min`, with "
        'sign `sign` (up|down|any)'
    ),
    'blink_count_min': (
        'lid-aperture (upper-to-lower lid distance / inter-ocular) dips below `closed` for 1 to '
        '4 consecutive sampled frames; the count of such dips over `seconds` of clip >= `min`'
    ),
    'gaze_offset_dir': (
        'mean iris-centre offset from the eye-socket centre (inter-ocular units) points '
        '`direction` (left|right|up|down) with magnitude >= `min` in >= `share` of sampled frames'
    ),
    'yaw_within_deg': (
        'the face mesh yaw (anatomy_qc `yaw_proxy`, converted with the linear fit named in '
        '`calibration`) is within `tolerance_deg` of `target_deg` in >= `share` of sampled frames'
    ),
    'brow_asym_min': (
        '|left brow-raise - right brow-raise| against the neutral take (inter-ocular units) >= `min` '
        'while the quieter side stays below `still_max` — one brow moved, not both'
    ),
    'mesh_topology_valid': (
        'share of sampled frames whose 478-point fit keeps all three anatomy_qc._FACE_BANDS '
        'ratios (interocular_ratio 0.26-0.66, mouth_ratio 0.50-1.55, eye_mouth_ratio 0.70-2.30) '
        'inside band AND raises no degenerate-landmark issue >= `min_share`'
    ),
    'melt_frames_max': (
        'share of sampled frames anatomy_qc.qc_face_clip flags as melt (a run of >= '
        'ZYG_MP_MELT_RUN=3 consecutive lost detections, or a _FACE_BANDS ratio out of band) '
        '<= `max`'
    ),
    'face_count_equals': (
        'the pinned face detector finds exactly `n` faces whose box centre falls inside the '
        'tracked head region, in >= `share` of sampled frames — a second face inside the face '
        'is the ghost'
    ),
    'landmark_jitter_max': (
        'anatomy_qc.qc_face_clip `jitter_median` (ECC-compensated per-landmark displacement '
        'between adjacent samples, inter-ocular units) <= `max`; `p95_max` when set applies '
        'to `jitter_p95`'
    ),
    'detect_rate_min': 'anatomy_qc.qc_face_clip `detect_rate` over the clip >= `min` (the strict pass, not the permissive one)',
    'verdict_matches_operator_label': (
        "the row's own yes/no flag for defect `defect` equals the operator's BLIND "
        "label on the same clip in >= `share` of the clips, and the row's yes-rate "
        'stays <= `max_yes_rate` (a detector that flags everything is not a detector)'
    ),
}

# ── fixed conditions. Same frame count, seeds and sampler as the video bank, so a facial
# cell and a Moves cell on the same row were produced under one configuration.
COND = {
    'repeats': 3,
    'seeds': [11, 12, 13],
    'frames': 81,
    'steps': 30,
    'cfg': 6.0,
    'sampler': 'uni_pc with the simple scheduler',
    'fps': "the row's NATIVE fps, recorded: InfiniteTalk 25 fps (81 frames = 3.24 s), Wan/VACE 16 fps (5.06 s). Never resampled before a check.",
    'resolution': '832x480',
    'sample_every': 2,
    'note': (
        'anatomy_qc is sampled every 2 frames here, not its default 8: a blink is 3-5 frames and a '
        'jitter measurement between samples 8 frames apart measures motion, not jitter. The neutral '
        'baseline take (same still, same seed, no direction) is rendered once per row and is the '
        'reference every landmark_delta_min / brow_asym_min compares against.'
    ),
}

DRV = ['infinitetalk_face', 'prompt_face']
MSH = ['facemesh']
ALL_ROWS = DRV + MSH

CHOICES6 = ['joy', 'grief', 'anger', 'fear', 'surprise', 'physical effort']
EXPR8 = ['neutral', 'smile', 'frown', 'surprise', 'disgust', 'contempt', 'concentration', 'weariness']


def _p(pid, title, feeds, checks, rows, still='neutral_adult_m', audio=None, prompt=None, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {
            'fixture': f'{STILL}/{still}.png',
            'audio': (f'{LINE}/{audio}.wav' if audio else None),
            'prompt': prompt,
            'baseline': "the row's neutral take on the same still, same seed",
        },
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': list(rows),
    }
    p.update(kw)
    return p


def _emotion(cid, label, phrase, audio=None, rows=DRV):
    """A blind operator label test: the runner shows the clip WITHOUT the label and the
    operator names the emotion from the same list of six every time."""
    return _p(
        cid,
        f'{label} is readable off the face',
        [cid],
        [
            {
                'check': 'operator',
                'blind': True,
                'choices': CHOICES6,
                'question': f'Which of these six does this face show — joy, grief, anger, fear, surprise, physical effort? Pass only if the answer is "{label.lower()}".',
            },
            {
                'check': 'landmark_delta_min',
                'metric': 'any_of(brow_eye_distance, mouth_corner_width, lid_aperture)',
                'min': 0.04,
                'sign': 'any',
                'note': 'the face has to have MOVED off neutral at all; a still face that the operator charitably labels is not a performance',
            },
        ],
        rows,
        audio=audio,
        prompt=phrase,
        state_rule={'yes': 1.0, 'partial': 0.6},
        state_note=(
            'yes when the operator names it on all three seeds, partial on two. The operator sees the six '
            'names and nothing else — no row, no seed, no filename. Maybe is no.'
        ),
    )


PROBES = [
    # ── the one channel that really exists: the mouth ────────────────────────────────
    _p(
        'mouth_drive',
        'The mouth follows the audio',
        ['mouth'],
        [
            {'check': 'av_sync_lag_ms', 'max': 80, 'min_r': 0.5},
            {'check': 'mouth_closed_in_silence', 'max': 0.12, 'min_speech': 0.22},
            {
                'check': 'detect_rate_min',
                'min': 0.9,
                'note': 'a mouth measurement on a clip the mesh only finds half the time is not a measurement',
            },
        ],
        DRV,
        audio='l1_neutral_plosive',
        prompt='she speaks the line to camera, lips closing on every p and b, still head',
        state_note=(
            '80 ms is two frames at 25 fps and a little over one at 16; beyond that the audience hears the slip. '
            'The plosive line is the fixture on purpose: a bilabial closure is the one mouth shape a meter can '
            'find without a phoneme aligner. BLOCKED until the operator marks the speech and silence spans in the wav.'
        ),
    ),
    # ── the channels that may not exist. Measured, not assumed. ─────────────────────
    _p(
        'brow_raise',
        'A brow raise can be asked for',
        ['brows'],
        [
            {'check': 'landmark_delta_min', 'metric': 'brow_eye_distance', 'min': 0.08, 'sign': 'up'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Do the eyebrows rise in this clip, clearly and on purpose, rather than drifting? yes/no',
            },
        ],
        DRV,
        prompt='her eyebrows rise high in surprise, eyes widening, mouth closed',
        state_note='0.08 inter-ocular units is about a third of a brow height — smaller than that is noise on a 478-point fit at 832x480.',
    ),
    _p(
        'blink_drive',
        'A blink can be asked for',
        ['blink'],
        [
            {'check': 'blink_count_min', 'closed': 0.06, 'seconds': 8, 'min': 2},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this face blink at least twice, with both lids closing together and reopening? yes/no',
            },
        ],
        DRV,
        prompt='she blinks twice, slowly, otherwise still, looking straight at the camera',
        state_note=(
            '8 s needs two takes per seed at 81 frames (3.24 s at 25 fps, 5.06 s at 16) — the runner concatenates '
            'the two consecutive takes of the same seed and counts over the pair, and records that it did.'
        ),
    ),
    _p(
        'gaze_dir',
        'Gaze can be pointed',
        ['gaze_dir'],
        [
            {'check': 'gaze_offset_dir', 'direction': 'from the grid', 'min': 0.05, 'share': 0.7},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Which way do the eyes look — left, right, or neither? Pass only if it matches the direction on the card.',
            },
        ],
        DRV,
        prompt='she looks sharply to her <DIR>, head facing the camera, eyes only',
        grid={'DIR': ['left', 'right']},
        state_note='the head must NOT turn: a row that answers a gaze direction by turning the whole head fails this and passes head_turn.',
    ),
    _p(
        'head_turn',
        'A head turn can be asked for by angle',
        ['head_turn'],
        [
            {
                'check': 'yaw_within_deg',
                'target_deg': 'from the grid',
                'tolerance_deg': 10,
                'share': 0.6,
                'calibration': 'anatomy_qc yaw_proxy: ~0 frontal, 0.18 turning, ~0.5 profile (90 deg) — the fit pinned in the run receipt',
            },
            {
                'check': 'detect_rate_min',
                'min': 0.6,
                'note': 'MediaPipe loses a face past about 70 deg of yaw; below the floor the cell is untested, not no',
            },
        ],
        DRV,
        prompt='she turns her head <ANG> degrees to her right, shoulders square to camera',
        grid={'ANG': [30, 60]},
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'the honest ceiling of this column is the measurer: past ~70 deg the mesh does not resolve, so 90 deg '
            'is not asked. 30 and 60 are both asked because a row that always lands on profile whatever you ask '
            'for is not directable.'
        ),
    ),
    _p(
        'one_brow',
        'One brow, not both',
        ['asym'],
        [
            {'check': 'brow_asym_min', 'min': 0.06, 'still_max': 0.03},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is exactly ONE eyebrow raised in this clip (the other stays put)? yes/no',
            },
        ],
        DRV,
        prompt='she raises her left eyebrow only, the right one still, mouth neutral',
        state_note='the hardest driving question on the sheet and the one the sheet expects a no on: it needs per-side control, not an expression preset.',
    ),
    _p(
        'expression_named',
        'A named expression is reachable',
        ['expression'],
        [
            {
                'check': 'operator',
                'blind': True,
                'choices': EXPR8,
                'question': 'Which of these eight does this face show — neutral, smile, frown, surprise, disgust, contempt, concentration, weariness? Pass only if it matches the name on the card.',
            },
            {
                'check': 'landmark_delta_min',
                'metric': 'any_of(brow_eye_distance, mouth_corner_width, lid_aperture, nose_wrinkle)',
                'min': 0.04,
                'sign': 'any',
            },
        ],
        DRV,
        prompt='her face shows <EXPR>, held, head still, looking at the camera',
        grid={'EXPR': EXPR8},
        state_rule={'yes': 0.75, 'partial': 0.375},
        state_note=(
            '8 names x 3 seeds = 24 blind labels. yes at 6 of 8 names reachable, partial at 3. The column is '
            '"a named expression is reachable", so the note records WHICH of the eight landed — the four easy '
            'ones (neutral, smile, frown, surprise) and the four that are the real question (disgust, '
            'contempt, concentration, weariness).'
        ),
    ),
    _p(
        'micro_expr',
        'Micro-expressions are present',
        ['micro'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Watch this clip twice. Does anything cross this face BESIDES the one thing it was asked to do — a flicker at the mouth corner, a lid tighten, a swallow? yes/no',
            },
            {
                'check': 'landmark_jitter_max',
                'max': 0.05,
                'note': 'a face whose landmarks are perfectly still between samples has no micro-motion; a face above the jitter ceiling has noise, not micro-expression — this check bounds the answer from above and melt/jitter bound it from below',
            },
        ],
        DRV,
        prompt='she listens, quiet, thinking, looking slightly off camera',
        state_rule={'yes': 1.0, 'partial': 0.6},
        state_note='an observation, not a direction: nothing in either row takes a micro-expression instruction, so the question is whether the model produces them unbidden.',
    ),
    _p(
        'subtle_face',
        'A face, not a mask',
        ['subtle'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this a face or a mask — does the expression sit IN the flesh (skin creases, lids and cheeks move together) rather than being painted on a still surface? Answer "face" or "mask"; pass = face.',
            },
            {'check': 'mesh_topology_valid', 'min_share': 0.9},
        ],
        DRV,
        prompt='a quiet half-smile grows on her face and fades again, skin creasing at the eyes',
        state_rule={'yes': 1.0, 'partial': 0.6},
        state_note=(
            'the waxy-skin diagnosis is exactly this column [[project_waxy_skin]]: a plausible still face that '
            'never creases. The mesh cannot see waxiness — it stays valid on a mask — so the operator decides '
            'and the topology check only rules out a melt being mistaken for a mask.'
        ),
    ),
    # ── the six emotions, each a blind label ────────────────────────────────────────
    _emotion('joy', 'Joy', 'she laughs, delighted, eyes creasing', audio='l2_joy'),
    _emotion('grief_face', 'Grief', 'her face collapses in grief, mouth trembling', audio='l3_grief'),
    _emotion('anger_face', 'Anger', 'she is furious, jaw set, brows down and in', rows=['prompt_face']),
    _emotion('fear_face', 'Fear', 'she is afraid, eyes wide, breath held', rows=['prompt_face']),
    _emotion('surprise', 'Surprise', 'she is startled, brows up, mouth open', rows=['prompt_face']),
    _emotion(
        'effort',
        'Physical effort',
        'she strains, hauling on a rope just out of frame, teeth clenched',
        audio='l4_effort',
    ),
    # ── the other half of the sheet: does it happen / does it get detected ──────────
    _p(
        'melt',
        'Does the face melt, and is the melt detected',
        ['melt'],
        [
            {'check': 'melt_frames_max', 'max': 0.05},
            {'check': 'mesh_topology_valid', 'min_share': 0.95},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does the face lose its structure at any point in this clip — features sliding, a feature doubling, the head briefly not a head? yes = it melts, which fails.',
            },
            {'check': 'verdict_matches_operator_label', 'defect': 'melt', 'share': 0.8, 'max_yes_rate': 0.4},
        ],
        ALL_ROWS,
        prompt='she turns her head slowly from profile to camera, talking',
        row_checks={
            'infinitetalk_face': ['melt_frames_max', 'mesh_topology_valid', 'operator'],
            'prompt_face': ['melt_frames_max', 'mesh_topology_valid', 'operator'],
            'facemesh': ['verdict_matches_operator_label'],
        },
        measurer_input="every clip the two driver rows produced in this run (this probe, head_turn, subtle_face and the Moves ladder), each carrying the operator's blind melt label",
        state_note=(
            'TWO questions, one column. On a DRIVER row: did it happen — the share of frames anatomy_qc flags, '
            "plus the operator's blind label, which is written before any detector number is read. On the "
            'FACEMESH row: was it detected — that same label is the key, and the mesh must agree on 0.8 of the '
            'clips while flagging no more than 40 % of them (a detector that flags everything is not a detector). '
            "The thresholds behind the driver checks are anatomy_qc's own: ZYG_MP_MELT_RUN=3 consecutive lost "
            'samples, ZYG_MP_DETECT_RATE_FLOOR=0.60, _FACE_BANDS from the 2026-07-30 build.'
        ),
    ),
    _p(
        'identity',
        'Does it stay the same person, and is the drift detected',
        ['identity'],
        [
            {
                'check': 'identity_cosine_ref',
                'ref': STILL + '/neutral_adult_m.png',
                'min': 0.35,
                'sample': 'every 2nd frame',
            },
            {
                'check': 'identity_cosine_min',
                'a': 0,
                'b': -1,
                'min': 0.5,
                'note': 'first frame against last: drift within the clip, which the reference check can hide when the whole clip drifts together',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is the person at the END of this clip the same person as at the start? yes/no',
            },
            {'check': 'verdict_matches_operator_label', 'defect': 'identity_drift', 'share': 0.7, 'max_yes_rate': 0.4},
            {'check': 'detect_rate_min', 'min': 0.6},
        ],
        ALL_ROWS,
        prompt='she speaks to camera, head still',
        row_checks={
            'infinitetalk_face': ['identity_cosine_ref', 'identity_cosine_min', 'operator'],
            'prompt_face': ['identity_cosine_ref', 'identity_cosine_min', 'operator'],
            'facemesh': ['verdict_matches_operator_label', 'detect_rate_min'],
        },
        measurer_input='the same driver clips, with the operator\'s blind answer to "same person at the end as at the start"',
        state_note=(
            'The driver rows are scored by ArcFace: 0.35 is the same-identity line on our own insightface '
            "buffalo_l bench (the video bank's detectors table), and the intra-clip bar is higher because both "
            'frames come from one take. The FACEMESH row has no embedding at all — what it has is '
            'interocular_ratio / mouth_ratio / eye_mouth_ratio drift across the clip — so its question is only '
            'whether that geometric proxy agrees with the human often enough to be worth reading. 0.7, not 0.8: '
            'a proxy is expected to be worse than ArcFace and the cell should say so rather than pretend.'
        ),
    ),
    _p(
        'ghost',
        'Is there a second face inside the face, and is it detected',
        ['ghost'],
        [
            {'check': 'face_count_equals', 'n': 1, 'share': 1.0},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is there a second face, or a second set of features, anywhere inside this head at any point in the clip? yes = ghost, which fails.',
            },
            {'check': 'verdict_matches_operator_label', 'defect': 'ghost', 'share': 0.8, 'max_yes_rate': 0.3},
        ],
        ALL_ROWS,
        still='closeup_adult_m',
        prompt='a close-up, she turns towards the camera and speaks',
        row_checks={
            'infinitetalk_face': ['face_count_equals', 'operator'],
            'prompt_face': ['face_count_equals', 'operator'],
            'facemesh': ['verdict_matches_operator_label'],
        },
        measurer_input="these close-up clips from both driver rows plus the close-up Moves clips, each with the operator's blind ghost label",
        state_note=(
            'The close-up still is the fixture because that is where it was seen: the close-up double exposure '
            '[[project_closeup_doubleexposure]] and the ghost-face defect [[project_ghost_face_defect]]. On a '
            'driver row, share 1.0 and not 0.9 — one ghosted frame in a shot is a reshoot. On the facemesh row '
            'the yes-rate ceiling is the tighter 0.3, because counting a hair blob as a second face is exactly '
            "that row's known failure mode."
        ),
    ),
    _p(
        'jitter',
        'Do the landmarks jitter, and is the jitter measured',
        ['jitter'],
        [
            {'check': 'landmark_jitter_max', 'max': 0.06, 'p95_max': 0.12},
            {
                'check': 'flicker_max',
                'max': 6.0,
                'note': 'the clip-level boil ceiling from the video bank, recorded beside the landmark number so a jitter cell can be told apart from a whole-frame flicker',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this face shiver — do the features twitch frame to frame while the head itself is still? yes = jitter, which fails.',
            },
            {'check': 'verdict_matches_operator_label', 'defect': 'jitter', 'share': 0.7, 'max_yes_rate': 0.4},
            {'check': 'detect_rate_min', 'min': 0.6},
        ],
        ALL_ROWS,
        prompt='she stands still, looking at the camera, only breathing',
        row_checks={
            'infinitetalk_face': ['landmark_jitter_max', 'flicker_max', 'operator'],
            'prompt_face': ['landmark_jitter_max', 'flicker_max', 'operator'],
            'facemesh': ['verdict_matches_operator_label', 'detect_rate_min'],
        },
        measurer_input='these clips and the micro_expr clips from both driver rows, each with the operator\'s blind "does this face shiver" label',
        state_note=(
            "0.06 is anatomy_qc's own ZYG_MP_JITTER_FLOOR: below it the module refuses to call jitter at all, so "
            'it is the honest bar, and p95 at twice the median catches the single bad run. The facemesh question '
            'is whether the ECC-compensated number separates the clips the human called shivery. The ECC warp is '
            'load-bearing: on scene20_v7 an uncompensated fit onto a hair blob produced a nonsense jitter p95, '
            'which is why the per-face track exists, and a value above ZYG_MP_JITTER_MAX=2.0 is association '
            'error rather than jitter and is written untested.'
        ),
    ),
    _p(
        'child_face',
        'It works on a child face',
        ['child_face_mv'],
        [
            {'check': 'detect_rate_min', 'min': 0.8},
            {
                'check': 'identity_cosine_ref',
                'ref': STILL + '/child_front.png',
                'min': 0.35,
                'sample': 'every 2nd frame',
            },
            {'check': 'mesh_topology_valid', 'min_share': 0.9},
            {
                'check': 'operator',
                'blind': True,
                'question': "Is this a CHILD's face for the whole clip — child proportions, not a small adult and not sliding towards adult? yes/no",
            },
        ],
        ALL_ROWS,
        still='child_front',
        audio='l1_neutral_plosive',
        prompt='the boy speaks to camera, head still',
        state_note=(
            'Abel is the reason this column exists. The three checks are three different failures: the mesh not '
            'finding a child face (its training skews adult), the driver ageing him, and the fit staying valid '
            'while the proportions go wrong. On the facemesh row only detect_rate_min and mesh_topology_valid '
            'are scored — that row produces no clip to look at.'
        ),
    ),
]

# ── what each row cannot be asked ───────────────────────────────────────────────────
_NO_CHANNEL = (
    'lipsync_service.lipsync takes a still and a wav and nothing else: there is no text, dial or keyframe '
    'by which this could be ASKED for, so nothing was measured and nothing is claimed. Whether it happens '
    'incidentally is a property of the Wan i2v base and is measured on the i2v sheet.'
)
_NO_LINE = (
    'the fixture set holds four verified speech lines (neutral, joy, grief, effort). This emotion has no line, '
    'and this row is driven only by the line it is given — a fifth line is a new fixture and a new test hash.'
)
_MEASURER = (
    'anatomy_qc is a MEASURER, not a driver: it takes a finished clip and returns landmark geometry. It cannot '
    'be asked to move a face, so every driving column on this row is na rather than no.'
)
_MEASURER_NOMAKE = (
    'this row renders nothing — it reads a clip someone else made — so a question about what it can put '
    "in a frame, or how many of them, has no subject on this row. The bank's ladder is measured on the "
    'two driver rows.'
)
_MEASURER_NOPROMPT = (
    'this row takes no prompt and renders nothing: its inputs are a clip path, an expected face count '
    'and a sample stride, so a question about a prompt, or about what it can put in a frame, is about '
    "an input it does not have. The bank's ladder is measured on the two driver rows."
)
_MEASURER_NOSPACE = (
    'this row reports landmark geometry inside one head, not relations between things in a scene; '
    'left/right here means a lid, not a subject. Measured on the two driver rows.'
)

_IT_NA = {c: _NO_CHANNEL for c in ('brows', 'blink', 'gaze_dir', 'head_turn', 'asym', 'expression')}
_IT_NA.update({c: _NO_LINE for c in ('anger_face', 'fear_face', 'surprise')})
_MSH_NA = {
    c: _MEASURER
    for c in (
        'mouth',
        'brows',
        'blink',
        'gaze_dir',
        'head_turn',
        'micro',
        'asym',
        'expression',
        'joy',
        'grief_face',
        'anger_face',
        'fear_face',
        'surprise',
        'effort',
        'subtle',
    )
}
_MSH_NA.update(
    {
        c: _MEASURER_NOMAKE
        for c in (
            'cap_people',
            'cap_named',
            'cap_faces',
            'cap_hands',
            'cap_objects',
            'cap_words',
            'cap_digits',
            'cap_animals',
            'cap_prompt_terms',
            'cap_seconds',
            'cap_shots',
            'cap_moving',
        )
    }
)
_MSH_NA.update(
    {
        c: _MEASURER_NOSPACE
        for c in (
            'sp_left_right',
            'sp_front_behind',
            'sp_on_under',
            'sp_inside',
            'sp_near_far',
            'sp_touching',
            'sp_holding_who',
            'sp_relative_size',
            'sp_occlusion',
            'sp_direction',
        )
    }
)
_MSH_BANDS = {
    'reason': _MEASURER_NOPROMPT,
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
        'Prompt: damage',
        'Prompt: clarity needed',
        'Prompt: limits',
        'Prompt: steering',
    ],
}

TEST = {
    'step': 'facial',
    'version': '2026-09-30.1',
    'title': 'Two drivers and one measurer on six approved faces',
    'purpose': (
        "Give every driving channel a fixed direction through the row's own input and measure what came back "
        "off the 478-point face mesh; give the measurer the drivers' own clips and score it against the "
        "operator's blind labels. Driving and detecting are never graded by the same number."
    ),
    'include_shared': 'video',
    'rows': {
        'infinitetalk_face': {
            'transport': 'service',
            'where': 'lipsync_service.lipsync(still, wav, out_dir) — InfiniteTalk audio cross-attention over Wan2_1-I2V-14B-480P_fp8_e4m3fn, graph _comfy_workflows/infinitetalk_i2v.json, 25 fps, character LoRA attached UNMERGED (the fp8-scaled loader constraint)',
            'na': _IT_NA,
        },
        'prompt_face': {
            'transport': 'service',
            'where': "movement_studio.compose_prompt() -> wan_vace_service.generate_vace_static_clip() via bp_movement._run_job — the face directed in words, at the row's production shift",
        },
        'facemesh': {
            'transport': 'service',
            'where': 'anatomy_qc.qc_face_clip(clip, n_people, sample_every=2) / qc_face_frame — MediaPipe face_landmarker, 478 points, two-pass (permissive ZYG_MP_FACE_CONF 0.20 for recall, strict 0.50 for scoring), CPU, zero VRAM',
            'na': _MSH_NA,
            'na_bands': _MSH_BANDS,
            'budget': {
                'calls': 1400,
                'tokens_in': 0,
                'tokens_out': 0,
                'minutes': 50,
                'gpu_minutes': 0,
                'operator_minutes': 20,
                'note': (
                    'This row renders nothing. It scores every clip the two driver rows produced: 2 rows x ~700 '
                    'clips = 1400 qc_face_clip calls. 81 frames sampled every 2 = 41 frames per clip at ~50 ms '
                    'per MediaPipe pass, two passes = ~4 s per clip, but the passes are shared with the driver '
                    "rows' own measurement, so only ~2 s per clip is charged here = ~47 min CPU. Operator: 20 min "
                    'for the agreement sheet; the blind LABELS themselves are already paid for on the driver rows.'
                ),
            },
        },
    },
    'probes': PROBES,
    'derive': {},
    'lookup': {},
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': LINE,
            'verified': False,
            'generated': (
                'four wav lines from the cast voices through tts_service.py at 48 kHz mono, one take each, no '
                'processing: l1_neutral_plosive "Peter packed the barrels by the pump." then 2.0 s of silence '
                'then "Bring the bill of lading up.", l2_joy, l3_grief, l4_effort — the same 14-word line in '
                'each of the three deliveries so the emotion is the only variable. Written to '
                'capability_tests/fixtures/facial/lines/<id>.wav with a MANIFEST.json holding the text, the '
                'voice id, the sha256 and empty speech_spans / silence_spans / delivery_ok fields.'
            ),
            'blocks': ['mouth', 'joy', 'grief_face', 'effort'],
            'how_to_verify': (
                'open each wav, mark the speech and silence spans in MANIFEST.speech_spans / silence_spans '
                '(mouth needs them; av_sync_lag_ms and mouth_closed_in_silence read them), then listen to '
                'l2/l3/l4 WITHOUT the filename and write the emotion you hear into delivery_ok. If a line '
                'does not read as its own label, the line is the defect, not the face. Set verified = true.'
            ),
        },
        {
            'path': STILL,
            'verified': True,
            'generated': (
                'six approved 832x480 PNGs, each the canon render already signed off in the Character Studio '
                'review lane, exported with no post-processing and its sha256 into the trial: neutral_adult_m '
                '(Cornelis, front, neutral), neutral_adult_f (front, neutral), three_quarter_adult_m, '
                'profile_adult_m, closeup_adult_m (head filling the frame — the still the double-exposure and '
                'ghost-face defects were seen on), child_front (Abel, front, neutral).'
            ),
        },
    ],
    'run_order': [
        'facemesh on the stills first: qc_face_frame on all six approved stills is seconds of CPU and tells us whether the measurer resolves these faces AT ALL (it did not resolve a face whole-frame on scene20_v7 even at confidence 0.01). If it does not, every mechanical check below is untested and the render hours are not spent.',
        'the neutral baseline take per driver row (3 seeds) — every landmark_delta_min and brow_asym_min needs it.',
        'the mechanical driving probes, cheapest signal first: mouth_drive, blink_drive, gaze_dir, head_turn, brow_raise, one_brow, jitter, identity.',
        'the defect probes on the close-up: ghost, melt.',
        'the blind-label probes, which cost operator time: expression_named (24 labels), the six emotions, micro_expr, subtle_face.',
        'child_face.',
        "LAST of the domain probes: the facemesh half of melt / identity / ghost / jitter (its `row_checks`), which needs every driver clip above and the operator's labels on them.",
        "LAST: the video bank's Moves ladder (132 subjects x 3 seeds) and the Capacity ladder. It is ~90 % of the budget and every domain column is already filled without it.",
    ],
    'budget': {
        'calls': 700,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'no language model is called on this step: a diffusion prompt goes through umT5 inside the render and is not metered in tokens',
        'minutes': 2805,
        'gpu_minutes': 2800,
        'operator_minutes': 525,
        'note': (
            'Per DRIVER row. Domain probes: mouth 3 + brows 3 + blink 3x2 concatenated takes = 6 + gaze 2 dirs x 3 = 6 '
            '+ head_turn 2 angles x 3 = 6 + micro 3 + asym 3 + expression 8 names x 3 = 24 + 6 emotions x 3 = 18 + '
            'subtle 3 + melt 3 + identity 3 + ghost 3 + jitter 3 + child 3 + the neutral baseline 3 = 78 renders. '
            'SHARED BANK: 197 video-bank probes feed this step, 622 trials (the 132-subject Moves ladder x 3 seeds is '
            '396 of them) = 622 renders. 78 + 622 = 700 clips. At 81 frames / 832x480 / 30 steps a Wan-family take is '
            '~4 min on the 4090, so 700 x 4 = 2800 GPU minutes = 46.7 h per driver row, plus ~5 min of model load. '
            "OPERATOR: 330 operator checks in the bank's probes for this step x 3 repeats = 990 blind decisions, plus "
            '~60 of my own (24 expression labels, 18 emotion labels, micro, subtle, melt, ghost, child) = ~1050 x 30 s '
            '= 525 min = 8.75 h per driver row. The facemesh row overrides all of this (CPU, no renders). '
            'NO CLAUDE WEEK IS SPENT: all three rows are local services, no claude_cli and no anthropic_api row on '
            'this step. This is a two-night GPU test per driver row; the run_order is written so that stopping after '
            'the domain probes (~5.2 h) still fills every column this sheet is actually about.'
        ),
    },
    'notes': [
        'The sheet said it first: only the mouth has a driver. This test is arranged so that finding lands as measured no cells on brows / blink / gaze_dir / head_turn / asym / expression for prompt_face, and as written na on infinitetalk_face, which has no channel to fail in. Those are different answers and the sheet must not blur them.',
        'melt, identity, ghost and jitter each hold two questions in one probe, split by `row_checks`. On a driver row the question is "did it happen" and the operator\'s blind label is the KEY; on the facemesh row the question is "was it detected" and it is scored against that key with a yes-rate ceiling, so a detector that flags everything cannot score well. The labels are written before any detector output is read. A runner that ignores `row_checks` and applies every check to every row measures the mesh against its own opinion — that is the one way to get this column wrong.',
        'Every threshold that could be taken from anatomy_qc was: ZYG_MP_JITTER_FLOOR 0.06, ZYG_MP_JITTER_MAX 2.0, ZYG_MP_MELT_RUN 3, ZYG_MP_DETECT_RATE_FLOOR 0.60, and _FACE_BANDS (interocular 0.26-0.66, mouth 0.50-1.55, eye_mouth 0.70-2.30) from the 2026-07-30 build. Where the module has no opinion (brow delta, gaze offset, a/v lag) the number is set HERE and the state_note says why.',
        "sample_every is 2, not anatomy_qc's default 8. A blink is 3-5 frames and the ECC jitter between samples 8 frames apart is motion, not jitter. This costs CPU, not GPU.",
        'anatomy_qc on a stylised or small subject returns ok=None, which is UNKNOWN and never clean. A None from the measurer is written untested with the detect_rate, never as a pass — that is the r4 rule the module ships with and this test does not soften it.',
        "The Render band is not asked on this step; the video bank's Moves ladder is, and it is 90 % of the budget. It is deliberately last in run_order.",
    ],
}
