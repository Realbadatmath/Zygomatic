# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Image to video (i2v). 2026-09-30.

Question the sheet asks: can we move an approved still without losing the character in it?
Its recorded verdict is the reason this test exists at all — identity survives a clip only
when it comes from the PIXELS (a reference still in the control channel), not from a prompt
describing the person — and its recorded limitation is the hole this test fills: clip length
before identity drift has never been measured as a NUMBER, only known by eye, per shot.

Shape of the test. The shared video bank (`include_shared: 'video'`) already answers 385 of
the 405 columns identically for every video step: the 132 render_/move_ subject pairs, the
capacity and prompt ladders, the counting, spatial and attribute scenes, and the 27 universal
columns. The twenty columns left are this step's own subject — identity, the motion levers,
temporal coherence and the practical envelope — and they are all measured from SIX approved
stills, so every row starts from byte-identical pixels and the only variable is the engine.

What is measured mechanically, and what only the operator can say. Identity is ArcFace
cosine (insightface buffalo_l, 0.35 = same person on our own bench) against the input still,
which is a real detector and decides `identity`, `identity_len` and `face_hold`. Motion
magnitude is mean Farneback flow, which is what makes `shift` a measurable LEVER instead of
an opinion: on Wan, shift IS the motion lever ([[project_wan_motion_debug]]), so the ladder
3/5/8/12 must produce a moving curve or the column is `no`. Camera motion is separated from
subject motion by taking flow OUTSIDE the SAM2 subject mask, which is what lets
`camera_move`, `camera_still` and `background_hold` be decided at all. Hands are MediaPipe
hand_landmarker. `loop` is SSIM between frame 0 and the last frame. Everything that is
"does this clip look wrong" — melting, morphing, a second limb appearing, a costume changing
weave — is a BLIND operator yes/no, because our own defect-judge bench (2026-09-27) scored
34/40 on one global question and 2/8 on fused fingers, extra digits and a second feather.

What is blocked. The six stills do not exist yet; they are declared with the recipe that
makes them (the image bank's approved subject render at seed 11) and `verified: False`. Until
the operator approves them, the columns that judge the CONTENT carried over from the still —
identity, identity_len, face_hold, costume_hold, hands_video, background_hold, props_hold —
are BLOCKED and written `untested — key unverified`. The purely temporal columns (motion,
shift, prompt_motion, camera_*, physics, morph, flicker, length, window_seam, loop) are not
blocked: a defect already in the still cannot flatter a flicker or flow measurement.

What this test does NOT force. fps, resolution and shift stay each row's PRODUCTION default
and are recorded into every trial (the bank's rule). One row cannot obey the bank's 30 steps
at all: `wan_lightning` is a 4-step distill that overrides steps/cfg/shift to 4/1.0/5.0 in
code (wan_video_service.py:855-858), so its conditions differ by design and its trials say so.
"""

from __future__ import annotations

# ── check kinds this module adds (the runner is a table of these) ──────────────────────
CHECK_KINDS = {
    'flow_mean_range': (
        'mean Farneback (DETECTORS["farneback"]) flow magnitude over the WHOLE frame, averaged over '
        'every consecutive frame pair of the clip, is between `min` and `max` px/frame — the global '
        'motion magnitude, subject plus camera together'
    ),
    'ladder_monotone': (
        "across the probe's rungs, the measured `metric` RISES with the rung: the highest rung's "
        "value exceeds the lowest rung's by at least `min_delta` in the metric's unit, and no rung "
        'falls more than `tol` below its predecessor. A lever that does not move the number is a no, '
        'however good the clips look'
    ),
    'camera_flow_max': (
        'the median Farneback flow magnitude OUTSIDE the SAM2 subject mask (the background — which is '
        "the camera's own motion) over the whole clip is <= `max` px/frame"
    ),
    'camera_flow_min': (
        'the same background flow is >= `min` px/frame AND its dominant direction over the clip is '
        '`direction` (left|right|up|down|in|out) — the camera moved, and moved the way it was asked to'
    ),
    'bbox_stable': (
        'the subject bounding box width and height (located by `detector`, or by the SAM2 mask for '
        '`region`) each vary by less than `tol` (a fraction of their own median) across the frames in '
        '`sample` — the size-and-shape half of a morph'
    ),
    'ssim_min': (
        'SSIM (skimage.metrics.structural_similarity, gaussian_weights, data_range 255, luma plane) between '
        'the frames named by `a` and `b` is >= `min`. A bare integer is a frame index of this clip (-1 is the '
        'last); "<rung>:<index>" names a frame of another clip of the same probe'
    ),
}

# ── the six approved input stills: every probe below starts from one of them ───────────
FX = 'capability_tests/fixtures/video/i2v_stills'
MANIFEST = FX + '/MANIFEST.json'

STILLS = {
    'maarten_cu': (
        'close-up, head and shoulders, front on: Maarten, a Dutch dockworker of about forty, dark cropped '
        'hair, short brown beard, a brown wool coat with a plain collar, plain quay wall behind, overcast '
        'daylight, 1671.'
    ),
    'maarten_mid': (
        'mid shot, waist up, front on: Maarten, a Dutch dockworker of about forty, dark cropped hair, '
        'short brown beard, a brown wool coat with a plain collar, standing on a stone quay, overcast '
        'daylight, 1671.'
    ),
    'maarten_wide': (
        'wide shot, full body and small in frame at the left: Maarten, a Dutch dockworker of about forty '
        'in a brown wool coat, standing on a long stone quay with a moored ship behind him, overcast '
        'daylight, 1671.'
    ),
    'griet_red': (
        'mid shot, waist up, front on: Griet, a Dutch woman of about thirty, hair under a white linen cap, '
        'in a red wool cloak over a grey bodice, standing on a stone quay, overcast daylight, 1671.'
    ),
    'hands_rope': (
        'close-up of two bare human hands gripping a thick tarred rope, five fingers visible on each hand, '
        'plain grey quay stone behind, soft daylight.'
    ),
    'quay_props': (
        'three oak barrels stacked in a row with one iron lantern hanging beside them on a stone quay, a '
        'Dutch dockworker standing to the right of the barrels, brick warehouse wall behind, overcast '
        'daylight, 1671.'
    ),
}

NEGATIVE = (
    'blurry, low quality, jpeg artifacts, watermark, text overlay, subtitles, extra limbs, '
    'extra fingers, missing fingers, deformed hands, melting, morphing, duplicated subject, '
    'flicker, colour banding, static image'
)

# The bank's conditions, restated here so a reader of this module sees what a trial is: 81
# frames, seeds 11/12/13, 30 steps, cfg 6.0, uni_pc/simple, the row's own fps / resolution /
# shift RECORDED rather than forced.
COND = {
    'seeds': [11, 12, 13],
    'repeats': 3,
    'frames': 81,
    'steps': 30,
    'cfg': 6.0,
    'sampler': 'uni_pc/simple',
    'shift': 'row production default (recorded)',
    'resolution': 'row production default (recorded): 832x480, or 1280x720 for the 720P row',
    'negative': 'NEGATIVE',
}
COND_ONE = dict(COND, seeds=[11], repeats=1)

SAMPLE5 = [0, 20, 40, 60, 80]
S3 = {'yes': 1.0, 'partial': 0.6}  # yes at 3/3 seeds, partial at 2/3
LADDER = {'yes': 1.0, 'partial': 0.6}  # a rung passes at every seed or it is not the answer

ARC = 'insightface-buffalo_l'
LADDER_NOTE = (
    'The answer is a NUMBER: the highest rung that passed at all three seeds. Rungs above it are '
    'rendered too and their failures go in the trial, so the reader sees where it broke and how. '
    'Rung 1 failing means the column is 0, which is a real answer.'
)


def _p(pid, title, feeds, prompt, checks, image=None, cond=None, **kw):
    """One probe. `prompt` is the verbatim motion phrase (or the ladder marker); `image` names
    the approved still it starts from. A check's `for` says which fed column it scores."""
    ins = {'prompt': prompt, 'negative': NEGATIVE}
    if image:
        ins['image'] = f'{FX}/{image}.png'
        ins['still_prompt'] = STILLS[image]
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': ins,
        'conditions': dict(cond or COND),
        'checks': list(checks),
        'grade': 'measured',
        'state_rule': S3,
    }
    p.update(kw)
    return p


def _op(q, for_=None):
    c = {'check': 'operator', 'blind': True, 'question': q}
    if for_:
        c['for'] = for_
    return c


PROBES = [
    # ── Identity: the question the sheet is actually about ──
    _p(
        'id_hold',
        'Identity survives the clip',
        ['identity'],
        'he turns his head slowly to his left, then back to camera',
        [
            {'check': 'frames_exact', 'frames': 81},
            {'check': 'identity_cosine_min', 'a': 0, 'b': -1, 'min': 0.35, 'detector': ARC},
            {'check': 'identity_cosine_ref', 'ref': 'the input still', 'sample': SAMPLE5, 'min': 0.35, 'detector': ARC},
            _op(
                'Is the person at the END of this clip the same person as in the still shown beside it — same face, '
                'same age, same hair, same beard? yes/no'
            ),
        ],
        image='maarten_mid',
        state_note=(
            'BOTH must hold: cosine to the input still stays >= 0.35 at frames 0/20/40/60/80 AND frame 0 vs '
            'the last frame stays >= 0.35. The mechanical check decides; the operator answer is recorded '
            'beside it and a disagreement is reported rather than averaged. Griet (griet_red) is run through '
            "the same probe as the second subject so the answer is not one face's luck."
        ),
        second_subject='griet_red, same motion phrase with "she" for "he" — the only word that changes',
    ),
    _p(
        'id_len',
        'Seconds before identity drifts',
        ['identity_len'],
        'per rung, verbatim in `ladder`: he turns his head slowly to his left, then back to camera',
        [
            {
                'check': 'operator',
                'blind': True,
                'question': "see each rung's own checks in `inputs.ladder`",
                'note': 'the runner scores rung by rung; this entry exists so the check list is never empty',
            }
        ],
        image='maarten_mid',
        unit='s',
        state_rule=LADDER,
        ladder=[{'s': 2, 'frames': 33}, {'s': 4, 'frames': 65}, {'s': 6, 'frames': 97}, {'s': 8, 'frames': 129}],
        rung_checks=[
            {
                'check': 'identity_cosine_ref',
                'ref': 'the input still',
                'sample': 'every 8th frame',
                'min': 0.35,
                'detector': ARC,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is the person still the same person in the LAST frame of this clip as in the still '
                'shown beside it? yes/no',
            },
        ],
        state_note=(
            LADDER_NOTE + ' The column is the last rung whose cosine never fell below 0.35 — the NUMBER the '
            "sheet's own limitation says has never been measured. Past 81 frames a comfy row must chain "
            'sub-clips (wan_video_service n_chained) and the vace row slides its context window; that is not '
            'a confound, it is what "seconds before identity drifts" means on this box.'
        ),
    ),
    _p(
        'face_dist',
        'The face holds at distance',
        ['face_hold'],
        'he walks two steps towards the camera and stops',
        [
            {'check': 'identity_cosine_ref', 'ref': 'the input still', 'sample': SAMPLE5, 'min': 0.35, 'detector': ARC},
            {
                'check': 'bbox_frac',
                'min': 0.05,
                'max': 1.0,
                'sample': SAMPLE5,
                'detector': 'yolov8n-coco',
                'note': 'proves the clip really is at the distance the still set, so the three rungs are three distances',
            },
            _op('Is this the same face as in the still shown beside it, at this size in frame? yes/no'),
        ],
        image='maarten_cu',
        unit='count',
        state_rule=LADDER,
        ladder=[
            {'distance': 'close-up', 'image': f'{FX}/maarten_cu.png', 'bbox_frac': [0.45, 1.0]},
            {'distance': 'mid', 'image': f'{FX}/maarten_mid.png', 'bbox_frac': [0.20, 0.55]},
            {'distance': 'wide', 'image': f'{FX}/maarten_wide.png', 'bbox_frac': [0.05, 0.25]},
        ],
        state_note=(
            'Three distances, one motion phrase, three seeds each. The column is the FURTHEST distance at '
            "which cosine to that distance's own still stayed >= 0.35 at all three seeds. A wide shot whose "
            'face is 40 px tall may give ArcFace no face at all — that is recorded as "no face detected", '
            'which is a no on the rung and NOT an untested.'
        ),
    ),
    _p(
        'costume',
        'Costume holds',
        ['costume_hold'],
        'she turns once to her right so the cloak swings, and faces the camera again',
        [
            {
                'check': 'named_colour_region',
                'region': 'the cloak',
                'colour': 'red',
                'tolerance_deg': 20,
                'sample': SAMPLE5,
                'detector': 'sam2-hiera-small',
            },
            {
                'check': 'bbox_stable',
                'region': 'the cloak',
                'tol': 0.25,
                'sample': SAMPLE5,
                'detector': 'sam2-hiera-small',
            },
            _op(
                'Comparing the last frame with the still shown beside it: is it the SAME garment — same colour, same '
                'cut, same closure, same cap — and not merely a garment of the same kind? yes/no'
            ),
        ],
        image='griet_red',
        state_note=(
            'The masked hue is the mechanical half and it is deliberately narrow: it catches the common '
            'failure (a red cloak drifting to brown or maroon over 81 frames) and nothing else. Cut, weave, '
            "buttons and the linen cap are the operator's, because no detector we have reads them."
        ),
    ),
    # ── Motion and the levers ──
    _p(
        'verbs',
        'The motion in the prompt is performed',
        ['motion', 'prompt_motion'],
        'per variant, verbatim in `variants`',
        [
            {
                'check': 'motion_min',
                'min': 0.6,
                'for': 'motion',
                'note': 'a clip that did not move is a no on motion, whatever it looks like',
            },
            {'check': 'flicker_max', 'max': 12.0, 'for': 'motion'},
            _op(
                'Does the figure perform THIS action, once and completely, within the clip: "{verb}"? yes/no', 'motion'
            ),
            {
                'check': 'flow_direction',
                'direction': '{direction}',
                'min': 0.8,
                'detector': 'farneback',
                'for': 'prompt_motion',
                'note': 'only the four variants whose verb has a screen direction are scored here; the other two are '
                'scored by the operator question alone and the trial says so',
            },
        ],
        image='maarten_mid',
        variants=[
            {'verb': 'he raises his right arm above his head and lowers it again', 'direction': 'up'},
            {'verb': 'he walks out of frame to the left', 'direction': 'left'},
            {'verb': 'he walks out of frame to the right', 'direction': 'right'},
            {'verb': 'he crouches down out of the bottom of frame', 'direction': 'down'},
            {'verb': 'he shakes his head twice', 'direction': None},
            {'verb': 'he takes off his coat', 'direction': None},
        ],
        state_note=(
            'Six verb phrases, three seeds each, one still. `motion` is "did anything coherent happen" — the '
            'operator question plus the two-sided flow floor. `prompt_motion` is "did the thing ASKED FOR '
            'happen" — the flow direction the verb implies, where it implies one. A clip that moves '
            'beautifully in the wrong direction is yes on motion and no on prompt_motion, which is exactly '
            'the distinction the two columns are for.'
        ),
    ),
    _p(
        'shift_lever',
        'The motion lever is calibrated',
        ['shift'],
        'per rung, verbatim in `ladder`: he walks four steps along the quay and stops',
        [
            {'check': 'ladder_monotone', 'metric': 'flow_mean_range', 'min_delta': 1.0, 'tol': 0.2, 'unit': 'px/frame'},
            _op(
                'Ordering these four clips by how much movement they contain, do they come out in the order of their '
                'hidden setting — that is, is each one more animated than the one before? yes/no'
            ),
        ],
        image='maarten_mid',
        cond=COND_ONE,
        unit='px/frame',
        state_rule={'yes': 1.0, 'partial': 0.5},
        ladder=[{'shift': 3.0}, {'shift': 5.0}, {'shift': 8.0}, {'shift': 12.0}],
        rung_checks=[
            {
                'check': 'flow_mean_range',
                'min': 0.3,
                'max': 30.0,
                'detector': 'farneback',
                'note': "the rung's own measured value; the column is the CURVE, not any single rung",
            }
        ],
        state_note=(
            'ONE seed (11) and four shift values — the only probe in this test that changes a generation '
            'setting, because shift IS the motion lever on Wan [[project_wan_motion_debug]] and the question '
            'is whether the lever works. yes = the mean-flow curve rises by at least 1.0 px/frame from '
            'shift 3 to shift 12 with no rung more than 20 % below its predecessor. partial = it rises but '
            'not monotonically. no = the number does not move, which means this row has no motion lever and '
            'every other motion column on it was measured at whatever shift it happened to ship with. '
            'On the vace row vace_strength is laddered in the same clip set at fixed shift 5.0, because the '
            'house finding there is the other way round — the modality carries identity and the strength '
            'carries motion [[project_vace_plate_levers]]; both curves go in the trial.'
        ),
    ),
    _p(
        'camera',
        'Camera moves when asked, and holds still when asked',
        ['camera_move', 'camera_still'],
        'per variant, verbatim in `variants`',
        [
            {
                'check': 'camera_flow_min',
                'min': 1.2,
                'direction': '{direction}',
                'detector': 'sam2-hiera-small',
                'for': 'camera_move',
                'note': "background flow only — the subject's own motion is masked out first",
            },
            _op(
                'Did the CAMERA move this way — "{instruction}" — rather than the figure moving inside a still '
                'frame? yes/no',
                'camera_move',
            ),
            {'check': 'camera_flow_max', 'max': 0.5, 'detector': 'sam2-hiera-small', 'for': 'camera_still'},
            _op(
                'Is the camera locked off for the whole clip — no drift, no creep, no breathing of the frame edges? '
                'yes/no',
                'camera_still',
            ),
        ],
        image='maarten_wide',
        variants=[
            {'instruction': 'the camera pans left across the quay', 'direction': 'left', 'for': 'camera_move'},
            {'instruction': 'the camera pushes in towards the man', 'direction': 'in', 'for': 'camera_move'},
            {'instruction': "the camera tilts up the ship's mast", 'direction': 'up', 'for': 'camera_move'},
            {
                'instruction': 'the camera does not move; the man walks two steps along the quay',
                'direction': 'none',
                'for': 'camera_still',
            },
        ],
        state_note=(
            'Four instructions, three seeds. The separation of camera from subject is the whole trick: flow '
            'is taken OUTSIDE the SAM2 subject mask, so "the man walked and the frame did not" and "the '
            'camera panned and the man stood still" are different measurements instead of one number. '
            'camera_move = 3 of 3 move instructions passed (partial at 2 of 3); camera_still = the locked-off '
            'variant passed at all three seeds. Endpoint ORB affine is deliberately NOT used: on our own '
            'measurements it gives the wrong SIGN on a push-in or a dive once the end frames stop '
            'overlapping.'
        ),
    ),
    _p(
        'physics',
        'Physics are plausible',
        ['physics'],
        'per variant, verbatim in `variants`',
        [
            {'check': 'motion_min', 'min': 0.6},
            _op('Watching only this clip: does the {what} behave the way {what} does — {tell}? yes/no'),
        ],
        image='quay_props',
        variants=[
            {
                'what': 'cloth',
                'motion': 'the wind lifts the tarpaulin over the barrels and drops it again',
                'tell': 'it stays one continuous sheet, it hangs from where it is held, and it settles',
            },
            {
                'what': 'water',
                'motion': 'a bucket of water is poured over the edge of the quay',
                'tell': 'it falls as a connected stream, it does not hang in the air, and it does not flow upwards',
            },
            {
                'what': 'weight',
                'motion': 'the man lifts one barrel from the stack and sets it down',
                'tell': 'the barrel is heavy — he braces before it moves, it does not float, and it lands',
            },
        ],
        state_note=(
            'Operator only, and named as such. Cloth, water and weight are the three failures that cost us '
            'shots, and no detector we have can tell a plausible fall from an implausible one; a flow number '
            'would only say that something moved. Three variants x three seeds = 9 blind decisions per row.'
        ),
    ),
    # ── Coherence ──
    _p(
        'hands',
        'Hands survive motion',
        ['hands_video'],
        'the hands pull the rope towards the camera and keep their grip',
        [
            {
                'check': 'hand_landmarks_count',
                'hands': 2,
                'sample': SAMPLE5,
                'share': 0.8,
                'detector': 'mediapipe-hands',
            },
            {
                'check': 'hand_landmarks_count',
                'hands': 2,
                'fingers': 5,
                'sample': SAMPLE5,
                'share': 0.6,
                'detector': 'mediapipe-hands',
                'note': 'the stricter reading: five extended fingers on each hand. A gripping hand legitimately hides '
                'fingers, which is why the share is 0.6 here and 0.8 above',
            },
            _op(
                'In this clip, does each hand keep exactly five fingers throughout — no sixth finger, no finger fusing '
                'into another, no finger vanishing into the rope and coming back somewhere else? yes/no'
            ),
        ],
        image='hands_rope',
        state_note=(
            'MediaPipe hand_landmarker is the one real detector we have here (anatomy_qc.py), so it decides '
            'the count; the operator decides fusion, which the bench of 2026-09-27 showed no VLM can see '
            '(2/8). A frame where the landmarker finds no hand at all counts against the share — it is what '
            'the row produced.'
        ),
    ),
    _p(
        'coherence',
        'No melting, no morphing, no flicker',
        ['morph', 'flicker'],
        'per variant, verbatim in `variants`',
        [
            {'check': 'flicker_max', 'max': 12.0, 'for': 'flicker'},
            _op(
                'Does this clip boil — do surfaces, textures or edges churn between frames in a way that does not '
                'belong to the movement? yes/no',
                'flicker',
            ),
            {'check': 'bbox_stable', 'tol': 0.25, 'sample': SAMPLE5, 'detector': 'yolov8n-coco', 'for': 'morph'},
            _op(
                'Does anything in this clip melt, morph into something else, grow or lose a limb, duplicate itself, or '
                'change into a different object? yes/no',
                'morph',
            ),
        ],
        image='maarten_wide',
        variants=[
            {'motion': 'he walks four steps along the quay and stops'},
            {'motion': 'he turns his whole body away from the camera and back again'},
        ],
        state_note=(
            'Two motions x three seeds x two stills (maarten_wide and quay_props) — the fast one and the '
            'one with a hard turn, which is where morphing shows. flicker is the mean frame-to-frame luma '
            "delta ceiling of 12.0 on the 0-255 scale, the bank's figure for a normal-motion subject; "
            'morph is the bounding-box stability plus the operator, because a figure that melts into the '
            'quay keeps a perfectly steady flicker number.'
        ),
    ),
    _p(
        'hold_bg',
        'Background and props stay put',
        ['background_hold', 'props_hold'],
        'the man walks from beside the barrels to the left edge of frame; the camera does not move',
        [
            {
                'check': 'camera_flow_max',
                'max': 0.5,
                'detector': 'sam2-hiera-small',
                'for': 'background_hold',
                'note': "flow outside the man's own mask: the quay, the wall and the barrels must sit still while he moves",
            },
            _op(
                'Does the background stay in the same place for the whole clip — the same wall, the same stones, '
                'nothing sliding, appearing or being repainted behind him? yes/no',
                'background_hold',
            ),
            {
                'check': 'bbox_stable',
                'region': 'the stack of three barrels',
                'tol': 0.15,
                'sample': SAMPLE5,
                'detector': 'sam2-hiera-small',
                'for': 'props_hold',
            },
            _op(
                'Do the three barrels and the lantern keep the same size, the same shape and the same number for the '
                'whole clip? yes/no',
                'props_hold',
            ),
        ],
        image='quay_props',
        state_note=(
            'One clip answers both, read in two places: outside the subject mask for the background, inside '
            "the barrel mask for the props. The barrel count is the operator's because barrels are not a "
            "COCO class and the bank's own rule is that a thing outside those ten classes is counted by a "
            'human, never by a stand-in class.'
        ),
    ),
    # ── Practicalities ──
    _p(
        'len_ladder',
        'Usable seconds per clip',
        ['length'],
        'per rung, verbatim in `ladder`: he walks along the quay, stops, and looks out over the water',
        [
            {
                'check': 'operator',
                'blind': True,
                'question': "see each rung's own checks in `inputs.ladder`",
                'note': 'the runner scores rung by rung; this entry exists so the check list is never empty',
            }
        ],
        image='maarten_mid',
        unit='frames',
        state_rule=LADDER,
        ladder=[
            {'frames': 81, 's_at_16fps': 5.06},
            {'frames': 121, 's_at_16fps': 7.56},
            {'frames': 161, 's_at_16fps': 10.06},
        ],
        rung_checks=[
            {'check': 'frames_exact', 'frames': '{frames}'},
            {'check': 'flicker_max', 'max': 12.0},
            {
                'check': 'identity_cosine_ref',
                'ref': 'the input still',
                'sample': 'every 8th frame',
                'min': 0.35,
                'detector': ARC,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this whole clip usable end to end — would you cut it into an episode as it is? yes/no',
            },
        ],
        state_note=(
            LADDER_NOTE + ' "Usable" is defined here, not left to the runner: the clip decodes to exactly '
            "the rung's frame count, it does not boil, identity holds, and the operator would cut it. The "
            'unit is FRAMES and the seconds are written beside them per rung, because the rows disagree '
            'about fps and a seconds-only answer would hide that.'
        ),
    ),
    _p(
        'seam',
        'Context-window seams are invisible',
        ['window_seam'],
        'reads the 161-frame rung of len_ladder — no new render: he walks along the quay, stops, and looks out '
        'over the water',
        [
            {'check': 'seam_continuity', 'at': 81, 'max_ratio': 2.0},
            {
                'check': 'ssim_min',
                'a': 80,
                'b': 81,
                'min': 0.85,
                'note': "the two frames either side of the join, against the clip's own median neighbour SSIM in the trial",
            },
            _op(
                'Somewhere in this clip two renders are joined. Can you see where — a jump in brightness, a change of '
                'texture, a hitch in the movement? Answer yes if you CAN see it.'
            ),
        ],
        image='maarten_mid',
        state_note=(
            'No extra render: the 161-frame rung of len_ladder is already two windows for every row here — a '
            'comfy row chains sub-clips (wan_video_service n_chained) and the vace row slides its context '
            'window (wan_vace_service context.py shift_window_to_end). The mechanical check is the luma '
            "delta at frame 81 against the clip's own median frame delta; the operator question is INVERTED "
            'on purpose — a yes there is a fail, and the runner flips it before scoring, which the trial '
            'records so nobody flips it twice.'
        ),
    ),
    _p(
        'loop',
        'First and last frame can match',
        ['loop'],
        'he lifts his right hand to his cap and lowers it again, ending in exactly the pose he started in',
        [
            {'check': 'ssim_min', 'a': 0, 'b': -1, 'min': 0.90},
            {'check': 'identity_cosine_min', 'a': 0, 'b': -1, 'min': 0.35, 'detector': ARC},
            _op('Played on a loop, does this clip join to itself without a visible jump at the wrap? yes/no'),
        ],
        image='maarten_mid',
        state_note=(
            'SSIM 0.90 between frame 0 and the last frame is the mechanical bar and it is strict on purpose: '
            'a clip that merely returns to a SIMILAR pose does not loop. The prompt asks for the return '
            'explicitly, so a row that cannot obey it fails on the instruction, which is the honest reading '
            'of "CAN the first and last frame match".'
        ),
    ),
]

TEST = {
    'step': 'i2v',
    'version': '2026-09-30.1',
    'title': 'Six approved stills, one motion vocabulary, identity measured as a number',
    'purpose': (
        'Measure the twenty columns the shared video bank leaves to this step — identity and how long it '
        'lasts, the motion and camera levers, temporal coherence and the practical envelope — from six '
        'byte-identical input stills, so the only variable between two rows is the engine.'
    ),
    'include_shared': 'video',
    'rows': {
        'wan21_i2v_480': {
            'transport': 'comfy',
            'where': '_comfy_workflows/wan_i2v.json at 832x480 (ZYG_WAN_WIDTH/ZYG_WAN_HEIGHT defaults, ZYG_WAN_ATTENTION=sdpa)',
            'model': 'Wan2_1-I2V-14B-480P_fp8_e4m3fn.safetensors (ComfyUI diffusion_models)',
            'note': 'the house default I2V path: wan_video_service._WAN_COMFY_MODEL, native 16 fps per the model card',
        },
        'wan21_i2v_720': {
            'transport': 'comfy',
            'where': '_comfy_workflows/wan_i2v.json at 1280x720 (ZYG_WAN_MODEL + ZYG_WAN_WIDTH=1280, ZYG_WAN_HEIGHT=720)',
            'model': 'Wan2_1-I2V-14B-720P_fp8_e4m3fn.safetensors',
            'budget': {
                'minutes': 47500,
                'gpu_minutes': 47475,
                'note': '~45 min per 81-frame clip at 30 steps, from the measured 22 s/frame at 1280x720 and '
                '20 steps; 1055 clips x 45 min = 47,475 GPU minutes. ZYG_WAN_TIMEOUT_S must be raised '
                'above its 900 s default before any of these run or every clip is interrupted '
                'mid-sampler and the work is lost.',
            },
            'note': 'a 720p render is a DIFFERENT clip, not an upscale: re-rendering the same seed at 720p '
            "re-samples from scratch, so this row's numbers may not track the 480P row in either direction",
        },
        'wan22_i2v': {
            'transport': 'comfy',
            'where': '_comfy_workflows/wan22_i2v.json, HIGH expert for the first 50 % of steps then LOW '
            '(wan_video_service._WAN22_BOUNDARY_FRACTION = 0.5)',
            'model': 'Wan2_2-I2V-A14B-HIGH_fp8_e4m3fn_scaled_KJ.safetensors + Wan2_2-I2V-A14B-LOW_fp8_e4m3fn_scaled_KJ.safetensors',
            'note': 'A14B mixture of experts; Wan 2.1 character LoRAs only fit the LOW expert, which is why identity '
            'on this row is measured from the still and never from a LoRA',
        },
        'wan_lightning': {
            'transport': 'comfy',
            'where': '_comfy_workflows/wan22_i2v.json + wan_lightning/Wan2.2-Lightning_I2V-A14B-4steps-lora_HIGH_fp16.safetensors '
            'and _LOW_fp16.safetensors chained through WanVideoLoraSelect (ZYG_WAN_LIGHTNING=1)',
            'model': 'Wan2.2 I2V A14B + the 4-step Lightning LoRA pair, both at strength 1.0',
            'conditions': {
                'steps': 4,
                'cfg': 1.0,
                'shift': 5.0,
                'why': "the distill OVERRIDES the caller's steps/cfg/shift in code "
                "(wan_video_service.py:855-858), so this row cannot be run at the bank's 30 steps "
                'and cfg 6.0. Its trials are therefore comparable to the other rows in inputs and '
                'NOT in sampler settings, and every trial says so.',
            },
            'na': {
                'shift': 'Lightning forces shift to 5.0 together with 4 steps and cfg 1.0 '
                '(wan_video_service.py:855-858). There is no shift lever to calibrate on this row: a '
                'ladder of 3/5/8/12 would render four identical clips at 5.0 and report a flat curve as '
                'a model failure, which would be a lie about the code.'
            },
            'budget': {
                'minutes': 2200,
                'gpu_minutes': 2110,
                'note': '4 steps instead of 30: ~2 min per 81-frame clip at 832x480 (119 s by the measured '
                '0.368 s per frame per step), 1055 clips x 2 min = 2,110 GPU minutes. This is the '
                'cheapest row on the sheet by a factor of seven and should be run FIRST as the '
                'shake-down of the whole test.',
            },
            'note': 'known failure mode, recorded before the test runs: extreme motion. Expect the motion and '
            'physics columns to be where this row loses, and the speed columns to be where it wins.',
        },
        'vace': {
            'transport': 'service',
            'where': 'wan_vace_service.generate_vace_static_clip with ZYG_CHAR_GEOM_CTRL on, so '
            'geom/char_vace.CharGeometryPainter paints a 33-joint skeleton and a 478-point face mesh into '
            'every control frame (defaults width=832 height=480 steps=25 cfg=6.0 shift=5.0 '
            "vace_strength=0.9 vace_end_percent=1.0; steps raised to the bank's 30 and recorded)",
            'model': 'Wan2_1-VACE_module_14B_fp8_e4m3fn.safetensors over Wan2.1 I2V 480P',
            'budget': {
                'minutes': 17100,
                'gpu_minutes': 16880,
                'note': '~16 min per clip: the 15 min of a 480p 30-step render plus MediaPipe detection once '
                'and the per-frame control painting (CharGeometryPainter detects once and paints '
                'many, so the cost is drawing, not detection). 1055 clips x 16 min = 16,880.',
            },
            'note': "this is the row the sheet's verdict is about — identity from the PIXELS through the control "
            'channel. Its stated limitation is in its own docstring: ONE static geometry statement for the '
            'whole clip, which is wrong guidance the moment the character moves, so id_len and the long '
            'rungs of len_ladder are where it is expected to break. Fail-safe contract: any detector '
            'failure returns None and the caller keeps the neutral-grey control — a clip produced that way '
            'is a DIFFERENT configuration and the trial must record which path ran.',
        },
    },
    'probes': PROBES,
    'derive': {},
    'lookup': {
        'fps_native': {
            'grade': 'receipt',
            'requires': (
                'three things, all recorded in the cell: (1) the frame rate the model card states at a '
                'pinned revision (Wan 2.1 and 2.2: 16 fps); (2) the fps the house writes into the '
                'container, which is wan_video_service._CLIP_FPS = 17 at line 39, labelled there as "WAN '
                'native generation framerate"; (3) what ffprobe reads off the clip this test produced.'
            ),
            'note': (
                '(1) and (2) DISAGREE — the card says 16 and the house writes 17 — so this cell is a receipt, '
                'not a vendor fact, and it records both with the file and line for each. A cell that printed '
                'one number would hide a one-frame-per-second stretch in every clip we have shipped.'
            ),
        },
        'res_video': {
            'grade': 'receipt',
            'requires': (
                'the resolution the checkpoint was trained at, from the model card at a pinned revision '
                '(480P and 720P are in the checkpoint FILENAMES here), plus ffprobe width x height on the '
                'clip this test produced, plus the ZYG_WAN_WIDTH / ZYG_WAN_HEIGHT the row ran with.'
            ),
            'note': 'the 480P and 720P rows are the SAME workflow at two resolutions, so this column is what tells '
            'the reader that they are two rows and not one measured twice.',
        },
    },
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': MANIFEST,
            'verified': False,
            'blocks': [
                'identity',
                'identity_len',
                'face_hold',
                'costume_hold',
                'hands_video',
                'background_hold',
                'props_hold',
            ],
            'generated': (
                'the manifest lists the six stills and the exact prompt for each (STILLS in this module). '
                "Each one is rendered by the image bank's own path — capability_tests/image_shared.py, the "
                'production t2i row, seed 11, 832x480 for the wide and mid shots and 832x832 for the two '
                'close-ups, exported PNG with no post-processing — and its sha256 goes in the manifest and '
                'in every trial that used it. Nothing is drawn by hand and nothing is fetched.'
            ),
            'how_to_verify': (
                'the operator opens the six stills as a contact sheet and answers, per still: "is this '
                'the subject the prompt names, and is it free of any defect this test would then blame '
                'on the video row — five fingers on each visible hand, one face, the named colour on the '
                'named garment, three barrels?" A still that fails is re-rendered at the next seed, not '
                'accepted. Set verified = true only when all six have passed, and write the date and the '
                "operator's name into the manifest."
            ),
            'blocks_note': (
                'only the columns that judge CONTENT carried over from the still are blocked. motion, '
                'shift, prompt_motion, camera_move, camera_still, physics, morph, flicker, length, '
                'window_seam and loop are not: a defect already present in the still cannot flatter a flow, '
                'flicker, SSIM or seam measurement, and holding those columns hostage to the contact sheet '
                'would stop the cheap half of the test from ever running.'
            ),
        },
    ],
    'budget': {
        'calls': 1055,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': (
            'every row here is a diffusion renderer driven by a fixed prompt string; no language model '
            'is called at any point, so no tokens are spent and no Claude week is touched'
        ),
        'minutes': 15900,
        'gpu_minutes': 15825,
        'operator_minutes': 701,
        'note': (
            'CLIPS PER ROW = 1055. The SHARED VIDEO BANK is 958 of them: 396 subject clips (132 subjects x 3 seeds '
            '— one clip answers BOTH render_<id> and move_<id>, read at frame 0 and the last frame for render and '
            'across the clip for move, so it is 396 and not 792), 288 ladder rungs, 27 prompt-grid cells, 223 '
            'scene and prompt-variant clips, plus ~24 second clips for the eight paired probes. THIS MODULE adds '
            '97: id_hold 6, id_len 12 (4 rungs x 3), face_dist 9 (3 distances x 3), costume 3, verbs 18 (6 x 3), '
            'shift_lever 4 (4 rungs, one seed), camera 12 (4 x 3), physics 9 (3 x 3), hands 3, coherence 6, '
            "hold_bg 3, len_ladder 9 (3 rungs x 3), loop 3, seam 0 (it re-reads len_ladder's 161-frame rung). "
            'TIME PER CLIP at 832x480, 81 frames, 30 steps: ~15 min. That is arithmetic from a house measurement, '
            'not a guess — 53 frames at 832x480 and 20 steps took 390 s and 45 frames took 330 s (2026-09-15), i.e. '
            "0.368 s per frame per step, so 81 x 30 x 0.368 = 894 s, and Wan's attention is quadratic in frames so "
            '894 s is a floor. 1055 x 15 min = 15,825 GPU minutes = 264 GPU HOURS for this row, and ~75 min more of '
            'wall clock for model loads and queue. Setting ZYG_WAN_ATTENTION=sageattn would cut it by ~35-40 % to '
            '~165 h, but sdpa is the production default and this test measures what ships. The other rows override: '
            '720P ~47,475 (45 min/clip), Lightning ~2,110 (4 steps), vace ~16,880. TOTAL over the five rows is '
            'therefore about 1,380 GPU hours, which is 57 days of one 24 GB card and is the number the operator has '
            'to see BEFORE scheduling; `run_order` exists so a part of it is still worth running. OPERATOR: 1,291 '
            'blind decisions per row from the bank (2 per subject clip = 792, one per ladder rung = 288, the rest '
            'from the scenes and prompt variants) plus ~110 from this module = ~1,400 at 30 s = 701 min = ~11.7 h '
            'per row, 58 h over the sheet. ONE-OFF, not per row: approving the six stills as a contact sheet, ~10 '
            'min, and until it is done seven columns are BLOCKED. No language-model tokens and no Claude week on '
            'any row.'
        ),
    },
    'run_order': [
        'shift_lever',
        'loop',
        'coherence',
        'hold_bg',
        'hands',
        'id_hold',
        'costume',
        'face_dist',
        'camera',
        'verbs',
        'physics',
        'len_ladder',
        'seam',
        'id_len',
        'shared:counting',
        'shared:spatial',
        'shared:attributes',
        'shared:prompt',
        'shared:capacity',
        'shared:subjects',
        'ORDER RULE: the cheap mechanical probes first (shift_lever is 4 clips at one seed and tells you whether '
        'the motion lever works at all; loop, coherence, hold_bg and hands are 3-6 clips each and are fully '
        'mechanical apart from one question), then the identity probes the sheet is actually about, then the long '
        "ladders (id_len's 8-second rung and len_ladder's 161 frames are the most expensive clips in the test), "
        'and the 396-clip subject bank LAST. A run stopped anywhere down this list has filled whole columns rather '
        'than a scatter of cells. The Lightning row should be run first of the five rows for the same reason: at 4 '
        'steps it is a seventh of the cost and will find every wiring fault in the runner.',
    ],
    'notes': [
        'The sheet\'s own limitation — "clip length before identity drift has never been measured as a number" — is '
        'what id_len exists to close. Its answer is a count of seconds, not a yes/no, and the rungs above the '
        'answer are rendered and kept so the reader sees the shape of the drift and not just where it crossed.',
        'Shift is the one generation setting this test deliberately varies, on one seed, because on Wan it is the '
        'motion lever and a sheet that reports motion without reporting the shift it was measured at is not '
        "comparable to anything. Every other trial records the row's production shift rather than forcing one.",
        'wan_lightning is na on `shift` with the code reason: the distill overwrites steps, cfg AND shift, so there '
        'is no lever to ladder. That is a property of the row, not a failure of the row, and na is how the sheet '
        'says so.',
        'Endpoint ORB affine is not used anywhere in this test. On our own measurements it reports the wrong sign '
        'on a push-in or a dive as soon as frame 0 and the last frame stop overlapping (a 23 % push-in measured '
        '1.0352 endpoint against 1.2267 accumulated; a dive measured +0.744 endpoint against -0.6801 accumulated). '
        'Camera questions here use background flow, which stays inside each consecutive pair.',
        'The GPU cost in the budget is roughly seven times the estimate this test was commissioned against '
        '(~90-180 s per clip). The difference is not the bank and not this module: it is 30 sampler steps at 81 '
        'frames on a 14B fp8 model on one card, measured. If the house wants this test to fit a week, the honest '
        "lever is the bank's seed count or its subject count — both of which change the test and therefore its "
        'hash — and not a quietly lower step count.',
    ],
}
