# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Video to video, performance transfer (v2v). 2026-09-30.

Question the sheet asks: can a reference performance drive our character?

The step has two rows and they are not two models of one kind — they are the two SHAPES the
house has tried. wan22_animate takes a reference still plus a PER-FRAME 2D skeleton and
per-frame face crops off a driver clip (wan_animate_service.py, _comfy_workflows/wan22_animate.json).
vace_static takes the same still, detects ONE skeleton and ONE face mesh on it, and paints that
single statement into every control frame (geom/char_vace.py, behind ZYG_CHAR_GEOM_CTRL). There
is no driver clip on that path at all. Its own docstring states the consequence: "a static
geometry statement is wrong guidance the moment the character moves". So the test is built to
MEASURE that sentence rather than quote it — `per_frame` hashes the control frames the row hands
the engine, and every driver-fed column is `na` on vace_static with the reason, not a bad score.

The drivers are OURS. Five short operator recordings (walk, face, hands, occlusion, two people)
declared in capability_tests/fixtures/video/drivers/MANIFEST.json with their footfall times and
occlusion window to be marked by hand. This is the licence spine of the step, not paperwork:
the ComfyUI tutorial path preprocesses the driver with DWPose (non-commercial dataset) and
retargets with FLUX.1-Kontext-dev (non-commercial, and deleted from this box); both were removed
and replaced with MediaPipe through geom/keypoints.detect in the same OpenPose colour convention
char_vace already paints, so the two engines cannot drift apart. `clean_inputs` and
`driver_source` are therefore lookups into that receipt, and the standing rule stands: the
pirated-source scope allows a QA sample, never an archive, and a driver we ship against must be
a recording we made.

HONEST JUDGING. No local VLM is asked whether a transfer looks right — the 2026-09-27 defect
bench settles that (best model 34/40 on a global question, 2/8 on fused fingers). Every
transfer column is a mechanical detector PLUS a blind operator question, and the state_note says
which decides: MediaPipe pose/face/hand landmarks for what moved, ArcFace (insightface
buffalo_l, cosine >= 0.35 on our own bench) for who it is, Farneback flow and SAM2 masks for
where, PySceneDetect and the seam arithmetic for the joins.

WHAT IS BLOCKED. Nothing here exists on disk yet: the five drivers are unrecorded and the three
reference stills uncopied. Every fixture is declared with the exact recipe that makes it and
`verified: False`, so the columns it feeds are written `untested — key unverified` until the
operator records, marks and flips the flag. No binary is created by this test module.
"""

from __future__ import annotations

# ── check kinds this module adds (the runner is a table of these) ──────────────────────
CHECK_KINDS = {
    'pose_track_error_max': "median over frames of the mean L2 distance between the MediaPipe 33-joint pose landmarks of the OUTPUT frame and of the DRIVER frame at the same time, both normalised by the subject's own shoulder-to-hip distance, <= `max` (unit: torso lengths)",
    'pose_track_late_ratio_max': 'pose_track_error over the LAST quarter of the clip divided by the error over the first quarter <= `max` — a guidance statement that does not update degrades as the performance leaves it',
    'pose_track_missing_share_max': 'share of frames in which either the driver or the output yields no 33-joint detection <= `max`; these frames are excluded from pose_track_error_max and the count is reported beside the cell',
    'event_time_error_max': 'for the events marked in the driver fixture record (footfalls, the hand clap), median |time(output event) - time(driver event)| <= `max` ms, matched nearest-neighbour within 250 ms; output events are located by the same foot-landmark minimum detector on the output clip',
    'face_blendshape_corr_min': 'median over the blendshapes in `shapes` of the Pearson correlation between the MediaPipe face_landmarker blendshape time series of the driver and of the output >= `min`',
    'hand_pose_corr_min': "median over the 21 MediaPipe hand landmarks of the Pearson correlation between the driver's and the output's per-frame landmark position (x and y, normalised by hand bounding box) >= `min`, over the frames where both hands are found",
    'limb_ratio_matches_ref': "the output's median leg/torso, arm/torso and head/torso length ratios (MediaPipe pose landmarks) are each within `tolerance` of the REFERENCE STILL's ratios and NOT within `tolerance` of the driver's, where the two differ by more than `separation`",
    'background_delta_range': 'mean absolute frame-to-frame luma delta OUTSIDE the SAM2 subject mask is between `min` and `max` (0-255 scale) — `max` alone is the "background held" arm, `min` alone the "background replaced on purpose" arm',
    'landmark_recovery_frames_max': 'after the occlusion window marked in the driver record ends, the number of frames until the full 33-joint pose is detected again in the output <= `max`',
    'control_frames_identical': "the per-frame control images the row hands the engine are byte-identical across the clip (md5 per control frame, read from the row's own control dump) — `expect: True` means the guidance does NOT update per frame",
    'identity_clip_pass_frac': 'share of sampled output frames whose face embedding clears the per-frame floor in `floor` >= `min`, using the detector in `detector`; the floors and the aggregate rule are identity_bank.CLIP_FLOORS / CLIP_PASS_FRAC and a verdict needs >= CLIP_MIN_FOUND found frames',
}

FX = 'capability_tests/fixtures/video'
DRV = FX + '/drivers'
MANIFEST = DRV + '/MANIFEST.json'

# The five driver recordings. One MANIFEST holds the marked footfall times, the occlusion
# window and the frames where the face is fully visible — the answer key the operator verifies.
D_WALK = FX + '/driver_walk.mp4'
D_FACE = DRV + '/driver_face.mp4'
D_HANDS = DRV + '/driver_hands.mp4'
D_OCCL = DRV + '/driver_occlusion.mp4'
D_TWO = DRV + '/driver_two.mp4'

# The reference stills: who is being driven. Cornelis is the adult, Abel the child (the
# proportion case — an adult driver onto a child body), the wolf the non-humanoid case.
R_CORNELIS = DRV + '/ref_cornelis.png'
R_ABEL = DRV + '/ref_abel.png'
R_WOLF = DRV + '/ref_wolf.png'

# Fixed conditions. Frames, seeds, steps, cfg and sampler are the video bank's, so a v2v clip
# and an i2v clip of the same subject are comparable. fps/resolution/shift stay each row's
# production default and are recorded per trial (the bank's conditions_note: on Wan a shift
# change is a different test).
COND = {
    'seeds': [11, 12, 13],
    'repeats': 3,
    'frames': 81,
    'resolution': '832x480',
    'steps': 30,
    'cfg': 6.0,
    'sampler': 'uni_pc/simple',
    'shift': "the row's production default, recorded into every trial",
    'note': "the driver is played at its own 25 fps and the output is sampled at the row's native fps; landmark series are compared in SECONDS, never in frame indices, so a 16 fps row is not punished for being 16 fps",
}

NEG = (
    'blurry, low quality, jpeg artifacts, watermark, text overlay, subtitles, extra limbs, extra fingers, '
    'missing fingers, deformed hands, melting, morphing, duplicated subject, flicker, colour banding, static image'
)

BOTH = ['wan22_animate', 'vace_static']
DRIVEN = ['wan22_animate']

FACE_SHAPES = [
    'jawOpen',
    'mouthSmileLeft',
    'mouthSmileRight',
    'browInnerUp',
    'browDownLeft',
    'browDownRight',
    'eyeBlinkLeft',
    'eyeBlinkRight',
    'mouthPucker',
]


def _p(pid, title, feeds, checks, rows, video=None, image=None, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {
            'video': video or D_WALK,
            'image': image or R_CORNELIS,
            'prompt': 'Cornelis walks along the stone quay in his brown wool coat, 1671, daylight.',
            'negative': NEG,
            'fixture': MANIFEST,
        },
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': rows,
    }
    p.update(kw)
    return p


PROBES = [
    _p(
        'per_frame',
        'Does the guidance update per frame',
        ['per_frame'],
        [
            {
                'check': 'control_frames_identical',
                'expect': False,
                'note': 'wan22_animate must hand the engine 81 DIFFERENT pose frames and 81 face crops; vace_static hands it one statement 81 times',
            },
            {'check': 'pose_track_late_ratio_max', 'max': 1.5},
            {'check': 'pose_track_error_max', 'max': 0.25},
        ],
        BOTH,
        state_rule={'yes': 1.0, 'partial': 0.34},
        state_note=(
            "the column is decided MECHANICALLY and in the row's own control dump, not by eye: identical control frames = no per-frame guidance, whatever the "
            "output looks like. The late/early ratio is the measurement of char_vace.py's own stated limitation (a static skeleton mid-motion is wrong guidance "
            'late in the clip); 1.5 says the error may grow by half, not double. All three checks must pass.'
        ),
    ),
    _p(
        'driver_fidelity',
        'Follows the driver performance',
        ['driver_fidelity'],
        [
            {'check': 'pose_track_error_max', 'max': 0.20},
            {'check': 'pose_track_missing_share_max', 'max': 0.10},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Watching this clip beside the driver recording: does the character perform the SAME action, in the same order, with the same number of steps? yes/no',
            },
        ],
        DRIVEN,
        state_note="the landmark error decides; the operator question catches the failure the metric cannot see — a plausible walk that is not THIS walk. 0.20 torso lengths is roughly a hand's width of slack at the wrists",
    ),
    _p(
        'timing_keep',
        "Keeps the driver's timing",
        ['timing_keep'],
        [
            {
                'check': 'event_time_error_max',
                'max': 80,
                'events': "MANIFEST.drivers.driver_walk.footfalls (the operator's marks)",
            },
            {
                'check': 'duration_s',
                'min': 3.1,
                'max': 3.4,
                'note': '81 frames at 25 fps = 3.24 s; a row at another native fps is checked against its own 81-frame duration recorded in the trial',
            },
        ],
        DRIVEN,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='80 ms is two frames at 25 fps: a footfall that lands two frames late is still on the beat, three is visibly dragging. BLOCKED until the footfall marks are verified',
    ),
    _p(
        'identity',
        'Character survives',
        ['identity'],
        [
            {'check': 'identity_cosine_ref', 'ref': R_CORNELIS, 'sample': 'every 4th frame', 'min': 0.35},
            {
                'check': 'identity_clip_pass_frac',
                'min': 0.70,
                'floor': 0.42,
                'detector': 'facenet, as identity_bank enrolled it',
            },
            {'check': 'identity_cosine_min', 'a': 0, 'b': -1, 'min': 0.35},
        ],
        BOTH,
        state_note=(
            "two instruments on purpose. ArcFace/buffalo_l at 0.35 is the video bank's own bar; the clip verdict is identity_bank's CALIBRATED one (per-frame floor "
            '0.42, pass_frac 0.70, >= 8 found frames) and it is the one that decides, because it was benched on our characters: worst genuine frame 0.3943 against best '
            'impostor 0.3763, an overlap-free window only 0.018 wide — no single frame may decide a clip. Cornelis sits at 0.50-0.57 with ~0.08 of headroom and Abel at '
            '0.73-0.82, so a Cornelis failure may mean his 3-image bank is a worse centroid, not that his identity moved. `spread` is dispersion, NEVER continuity '
            '(the shuffled frame set scores 0.7656 against 0.7666) and is not read here at all.'
        ),
    ),
    _p(
        'face_transfer',
        'Transfers facial performance',
        ['face_transfer'],
        [
            {'check': 'face_blendshape_corr_min', 'min': 0.5, 'shapes': FACE_SHAPES},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Watching this clip beside the driver recording: do the brows and the mouth do the same things at the same moments? yes/no',
            },
        ],
        DRIVEN,
        video=D_FACE,
        state_note='the driver_face recording is front-on and seated so the face is measurable in every frame; 0.5 median correlation over nine blendshapes is "the performance is there", not "the performance is exact"',
    ),
    _p(
        'hand_transfer',
        'Transfers hand performance',
        ['hand_transfer'],
        [
            {'check': 'hand_pose_corr_min', 'min': 0.5},
            {'check': 'hand_landmarks_count', 'hands': 2, 'fingers': 5, 'share': 0.8, 'sample': 'every 4th frame'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Freezing on any three frames of this clip: does each hand have five fingers, none fused, none extra? yes/no',
            },
        ],
        DRIVEN,
        video=D_HANDS,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note="both halves are needed and they measure different failures: the correlation says the hands did the driver's knot, the landmark count and the blind question say they are still hands. The 2026-09-27 bench is why the second one is a human (2/8 on fused fingers)",
    ),
    _p(
        'proportion',
        'Retargets different proportions',
        ['proportion'],
        [
            {'check': 'limb_ratio_matches_ref', 'tolerance': 0.10, 'separation': 0.20},
            {
                'check': 'identity_clip_pass_frac',
                'min': 0.70,
                'floor': 0.42,
                'detector': 'facenet, as identity_bank enrolled it',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this clip show a child of about eight, or an adult scaled down (long legs, adult head-to-body ratio)? Answer yes if it is a child.',
            },
        ],
        DRIVEN,
        image=R_ABEL,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'Abel (child) driven by the adult walk. The mechanical half needs the two bodies to differ by >= 0.20 in the ratios before it claims anything, and the '
            'driver\'s own ratios are measured from the same recording, so "it kept the reference body" and "it copied the driver body" are separable. The official '
            'retarget uses FLUX.1-Kontext-dev, which is non-commercial and not on this box; this column measures what the house has instead, which is nothing but '
            'the reference render (S05 geom/body_plates.py)'
        ),
    ),
    _p(
        'costume_v2v',
        'Costume survives the transfer',
        ['costume_v2v'],
        [
            {
                'check': 'named_colour_region',
                'region': 'coat',
                'colour': 'brown',
                'tolerance_deg': 20,
                'sample': 'frames 0, 20, 40, 60, 80',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Comparing the first and last frame of this clip: is it the same garment — same colour, same length, same fastenings — rather than a similar one? yes/no',
            },
        ],
        BOTH,
        state_note='the hue check catches the drift a viewer forgives frame to frame and notices across a cut; the operator catches the garment QUIETLY becoming another brown coat, which no colour metric sees',
    ),
    _p(
        'background_v2v',
        'Background is preserved or replaced on purpose',
        ['background_v2v'],
        [
            {'check': 'background_delta_range', 'max': 3.0, 'arm': 'hold'},
            {'check': 'background_delta_range', 'min': 6.0, 'arm': 'replace'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'In the HOLD arm: does the quay behind the character stay the same quay, without stones or ropes changing shape? yes/no',
            },
        ],
        BOTH,
        grid={
            'background': [
                "hold (no background_dir, the still's own background)",
                'replace (background_dir = the harbour plate, mask_dir = the character matte)',
            ]
        },
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'two arms, because the column is "or replaced ON PURPOSE": a row that cannot hold the background fails the first arm, and a row with no background input at '
            'all is measured on the hold arm and reported as untested on the replace arm. wan22_animate has the inputs (nodes 15/16, inserted only when background_dir '
            'and mask_dir are passed); the VACE path holds by construction because the control is neutralised only under the character mask'
        ),
    ),
    _p(
        'occlusion',
        'Handles occlusion',
        ['occlusion'],
        [
            {'check': 'landmark_recovery_frames_max', 'max': 4},
            {
                'check': 'identity_cosine_ref',
                'ref': R_CORNELIS,
                'sample': 'the 12 frames after the occlusion window',
                'min': 0.35,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'When the character comes back out from behind the post: is it the same person in the same coat, facing the way the driver faces? yes/no',
            },
        ],
        DRIVEN,
        video=D_OCCL,
        state_note='four frames is the recovery the eye forgives at 25 fps. The identity check after the window is the one that catches the real failure mode — the model re-inventing whoever the post hid. BLOCKED until the occlusion window is marked',
    ),
    _p(
        'two_people_v2v',
        'Handles two people',
        ['two_people_v2v'],
        [
            {
                'check': 'detector_count',
                'detector': 'yolov8n-coco',
                'label': 'person',
                'n': 2,
                'share': 0.9,
                'sample': 'every 4th frame',
            },
            {'check': 'mask_iou_max', 'n': 2, 'max': 0.15, 'sample': 'every 4th frame'},
            {
                'check': 'pose_track_error_max',
                'max': 0.30,
                'note': 'per person, matched left-to-right by bounding box centre',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Do the two figures stay two separate people throughout — never merging, never swapping clothes or faces? yes/no',
            },
        ],
        DRIVEN,
        video=D_TWO,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='the count and the mask overlap are the merge detector; the looser 0.30 pose error is because two skeletons in one frame are harder to match than one, and a matching error is not a transfer error',
    ),
    _p(
        'non_humanoid',
        'Works on non-human bodies',
        ['non_humanoid'],
        [
            {
                'check': 'event_time_error_max',
                'max': 120,
                'events': 'MANIFEST.drivers.driver_walk.footfalls',
                'note': "the wolf's footfalls, located by the flow minimum under the paws — MediaPipe has no wolf skeleton and is not asked for one",
            },
            {
                'check': 'flow_region',
                'region': 'wolf',
                'min': 1.0,
                'max': 12.0,
                'note': 'the animal actually moves, and does not boil',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': "Does this clip show a wolf walking on four legs with the driver's rhythm, rather than a wolf standing on two legs or a human in fur? yes/no",
            },
        ],
        BOTH,
        image=R_WOLF,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'the column exists because Wan2.2-Animate\'s authors chose a 2D skeleton over a body model "for better generality, particularly for non-humanoid '
            'characters" — and because the SMPL family is banned in this house, so there is no fallback. The operator decides: no detector on this box counts a '
            "wolf's legs. On the VACE path MediaPipe finds no human in the wolf still, char_vace returns None and the control stays neutral grey — a measured no "
            'with a known cause, which is what fail-safe means'
        ),
    ),
    _p(
        'length',
        'Usable seconds',
        ['length'],
        [
            {'check': 'seam_continuity', 'at': 81, 'max_ratio': 2.0},
            {'check': 'seam_continuity', 'at': 157, 'max_ratio': 2.0},
            {
                'check': 'identity_clip_pass_frac',
                'min': 0.70,
                'floor': 0.42,
                'detector': 'facenet, as identity_bank enrolled it',
            },
            {'check': 'pose_track_late_ratio_max', 'max': 1.5},
            {'check': 'flicker_max', 'max': 12.0},
        ],
        BOTH,
        grid={'frames': [81, 157, 233]},
        conditions=dict(
            COND,
            frames='the ladder rung',
            repeats=3,
            note='three rungs, three seeds each. The rungs are the REAL chunk arithmetic, not round numbers: WanAnimateToVideo slices at video_frame_offset and with continue_motion first does offset -= len(continue_motion), so with continue_motion_max_frames=5 chunk 0 yields 81 new frames and every later chunk 76. Seams land at 81 and 157, NOT at 81/162',
        ),
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            "the cell is the longest rung that passed every check, in seconds at the row's native fps (81 frames = 3.24 s at 25 fps, 5.06 s at 16). "
            'generate_animate_clips() returns the real seam indices, so the seam check reads them from the run receipt rather than recomputing them. The VACE row '
            'has no chunking of this shape and its seam checks are reported untested with that reason, while the drift and flicker rungs still measure'
        ),
    ),
]

# ── the columns no trial can answer ────────────────────────────────────────────────────
LOOKUP = {
    'clean_inputs': {
        'source': 'wan_animate_service.py:16-27 (the two removals, at source) + data/runtime/model_licences_pending/S06.json + '
        + MANIFEST,
        'source_url': 'https://huggingface.co/Wan-AI/Wan2.2-Animate-14B (model card, Apache-2.0, verified 2026-09-02); https://docs.comfy.org/tutorials/video/wan/wan2-2-animate (the tutorial path whose preprocessors were REJECTED)',
        'revision': 'Wan2.2-Animate-14B card + Wan2.2 README as verified 2026-09-02; recipe as of 2026-09-30',
        'requires': [
            'wan_animate_service.py',
            'geom/keypoints.py',
            'geom/char_vace.py',
            'data/runtime/model_licences_pending/S06.json',
            MANIFEST,
        ],
        'grade': 'receipt',
        'value': {
            'weights': 'Wan2.2-Animate-14B Apache-2.0; Wan2.1-VACE-14B Apache-2.0; both pinned in the licence ledger',
            'removed': [
                "DWPose — the tutorial's driver preprocessor; its training dataset is non-commercial",
                'FLUX.1-Kontext-dev — the official proportion retarget; non-commercial, and the FLUX.1-dev family is deleted from this box',
            ],
            'substituted': 'MediaPipe through geom/keypoints.detect, drawn in the same OpenPose colour convention geom/char_vace already paints (_POSE_COLOURS / _BONES imported from there, so the two engines cannot drift apart)',
            'driver': 'our own recording. The standing rule: the pirated-source scope allows a QA SAMPLE, never an archive — so a benchmark clip may be looked at once and may never become a fixture, and every driver in '
            + MANIFEST
            + ' is operator-recorded with the release marked.',
        },
        'state_note': (
            'YES, and the receipt is the interesting part: this is the one column on the sheet where the house did work rather than accepted a default. The '
            'answer is only as good as the driver, which is why `driver_source` sits beside it and why the MANIFEST carries a per-file release flag the '
            'operator sets. A run whose driver record has no release flag must write this cell untested, not yes.'
        ),
    },
    'driver_source': {
        'source': MANIFEST + ' (the recipes) + wan_animate_service.py:16-27 (why nothing is fetched)',
        'source_url': 'https://docs.comfy.org/tutorials/video/wan/wan2-2-animate',
        'revision': 'as of 2026-09-30',
        'requires': [MANIFEST],
        'grade': 'receipt',
        'value': {
            'how': 'a phone recording, 25 fps, 8 s, tripod or steady hold, one subject, plain background, daylight — five of them, listed in the fixtures below',
            'cost': 'an afternoon per batch and no licence exposure; the only real cost is the marking pass (footfalls, occlusion window) the test needs as its key',
            'not_allowed': 'stock footage without a commercial release; anything scraped; anything from the pirated-source scope beyond a single QA look',
            'stand_in': "for a motion the operator cannot perform, the driver is RENDERED from the character's registered body (S05 geom/body_plates.py) rather than fetched — which is also the house answer to the banned Kontext retarget",
        },
        'state_note': 'YES for anything a person can act out in front of a phone, which is what this step is for. NO for a crowd, a horse or a fall — those need either a stand-in render or a licensed clip, and the sheet should say so rather than implying a driver is always available.',
    },
}

# vace_static takes no driver clip at all: the skeleton and the face mesh are detected on the
# STILL. Every driver-fed column therefore has no referent on that row — written na with the
# reason, never scored as a failure of a path that was never asked the question.
NO_DRIVER = (
    'this row has no driver clip: geom/char_vace detects one 33-joint skeleton and one 478-point face mesh on the STILL and paints that single '
    'statement into the control channel (wan_vace_service.generate_vace_static_clip behind ZYG_CHAR_GEOM_CTRL). A column about following, timing or '
    'transferring a reference performance has nothing to measure here. per_frame IS measured on this row, and it is the column that says so.'
)
VACE_NA = {
    c: NO_DRIVER
    for c in (
        'driver_fidelity',
        'timing_keep',
        'face_transfer',
        'hand_transfer',
        'occlusion',
        'two_people_v2v',
        'driver_source',
    )
}
VACE_NA['proportion'] = (
    'retargeting is a question about a driver body reaching a different reference body, and this row has no driver body. The reference still '
    'is the only body in the run, so the ratios are its own by construction and measuring them would measure the still.'
)

TEST = {
    'step': 'v2v',
    'version': '2026-09-30.1',
    'title': 'Five operator-recorded drivers onto three registered characters, measured against the driver',
    'purpose': (
        'Measure performance transfer against the DRIVER rather than against taste: landmark error per frame, event times in milliseconds, '
        'identity on the calibrated clip rule, and the one mechanical question that separates the two rows — do the control frames update at all.'
    ),
    'include_shared': 'video',
    'detectors_note': (
        "all detectors are the video bank's (yolov8n-coco, insightface-buffalo_l, mediapipe-hands, sam2-hiera-small, farneback, pyscenedetect) "
        'plus MediaPipe pose_landmarker and face_landmarker, which this step adds because the whole step is a landmark comparison. The pose source '
        'is geom/keypoints.detect — the same detector the production path draws its control with, so the measurement and the guidance cannot disagree '
        'about what a joint is.'
    ),
    'identity_calibration': {
        'source': 'identity_bank.py:70-105 (the bench) + docs/mesh_identity_plan_2026-09-02_sessions/receipts/S03.md',
        'per_frame_floor_facenet': 0.42,
        'clip_pass_frac': 0.70,
        'min_found_frames': 8,
        'arcface_same_identity': 0.35,
        'spread_alarm': 0.35,
        'note': (
            'worst genuine frame 0.3943 against best impostor frame 0.3763 — a 0.018-wide window, so the verdict is a FRACTION of frames. Cornelis 0.50-0.57, '
            'Abel 0.73-0.82. The ceiling 0.93-0.95 is IN-BANK (the canon portrait is one of the three enrolled images) and is not a genuine sample. spread is '
            'dispersion, never continuity. The dinov2 floor (0.50) is UNBENCHED and every result carries floor_benched.'
        ),
    },
    'rows': {
        'wan22_animate': {
            'transport': 'comfy',
            'where': '_comfy_workflows/wan22_animate.json, built and submitted by wan_animate_service.generate_animate_clips (pose frames and face crops from geom/keypoints.detect, never DWPose)',
            'model': 'Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2.safetensors + umt5_xxl_fp8_e4m3fn_scaled (wan) + wan_2.1_vae + clip_vision_h; WanAnimateToVideo with continue_motion_max_frames 5',
        },
        'vace_static': {
            'transport': 'service',
            'where': 'geom/char_vace.CharGeometryPainter into wan_vace_service.generate_vace_static_clip, behind ZYG_CHAR_GEOM_CTRL — one detection on the still, painted into every control frame',
            'model': "Wan2.1-VACE-14B with the character's own detected geometry in the control channel (OpenPose colours + face tesselation), neutral grey 127 as the base",
            'na': VACE_NA,
            'budget': {
                'calls': 21,
                'minutes': 58,
                'gpu_minutes': 54,
                'operator_minutes': 6,
                'note': (
                    'the incumbent path runs only the seven columns that have a referent without a driver: per_frame (the control dump is free — the render is '
                    'not), identity, costume_v2v, background_v2v (2 arms), non_humanoid, length (3 rungs). 6 clip families x 3 seeds = 18 clips plus the 3 long '
                    'rungs, at ~120 s for 81 frames on the VACE path = ~48 min, + ~4 min model load, + ~6 min of MediaPipe/ArcFace measurement. Operator: 12 '
                    'blind decisions at 30 s.'
                ),
            },
        },
    },
    'probes': PROBES,
    'derive': {},
    'lookup': LOOKUP,
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': D_WALK,
            'verified': False,
            'blocks': ['timing_keep', 'driver_fidelity', 'per_frame', 'non_humanoid', 'length'],
            'generated': 'operator-recorded 8 s walk, phone, 25 fps — one person walking four steps across frame and stopping, side on, plain wall, daylight, tripod',
            'how_to_verify': (
                'in '
                + MANIFEST
                + ': mark the footfall times to the frame from the waveform and the foot landmarks, tick the release flag (this is our '
                'recording of a consenting adult), and set verified = true. Until then every column driven by this clip is written untested — key unverified.'
            ),
        },
        {
            'path': D_FACE,
            'verified': False,
            'blocks': ['face_transfer'],
            'generated': 'operator-recorded 6 s, phone, 25 fps — seated, front on, head still: says one sentence, raises the brows once, smiles once, closes the eyes once',
            'how_to_verify': 'mark in the MANIFEST the frames where the whole face is visible and the four beats (sentence, brows, smile, blink); tick the release flag; set verified = true',
        },
        {
            'path': D_HANDS,
            'verified': False,
            'blocks': ['hand_transfer'],
            'generated': 'operator-recorded 6 s, phone, 25 fps — both hands in frame at chest height tying a knot in a rope, palms toward camera',
            'how_to_verify': "confirm MediaPipe hand_landmarker finds two hands in >= 90 % of the driver's own frames before the clip is used as a key (a driver the detector cannot read cannot measure a transfer); set verified = true",
        },
        {
            'path': D_OCCL,
            'verified': False,
            'blocks': ['occlusion'],
            'generated': 'operator-recorded 8 s, phone, 25 fps — the same walk, but passing behind a post that hides the subject completely for about one second',
            'how_to_verify': 'mark the occlusion window (first and last hidden frame) in the MANIFEST; tick the release flag; set verified = true',
        },
        {
            'path': D_TWO,
            'verified': False,
            'blocks': ['two_people_v2v'],
            'generated': 'operator-recorded 8 s, phone, 25 fps — two people walk toward each other, shake hands and part; both fully in frame throughout',
            'how_to_verify': 'mark the handshake frame and tick a release flag for BOTH people; set verified = true',
        },
        {
            'path': R_CORNELIS,
            'verified': False,
            'blocks': ['identity', 'costume_v2v', 'background_v2v'],
            'generated': 'the registered canon portrait for Cornelis, exported at 832x480 with no post-processing — the same image identity_bank has enrolled for him, so the reference and the metric agree about who he is',
            'how_to_verify': "confirm the exported still is one of the three images in the character's identity_bank enrolment and that the coat is the brown wool one the costume probe names; set verified = true",
        },
        {
            'path': R_ABEL,
            'verified': False,
            'blocks': ['proportion'],
            'generated': 'the registered canon portrait for Abel (the child) at 832x480, no post-processing — the enrolled image, for the same reason',
            'how_to_verify': "as above, and record Abel's leg/torso, arm/torso and head/torso ratios from the still into the MANIFEST: they are the key limb_ratio_matches_ref compares against",
        },
        {
            'path': R_WOLF,
            'verified': False,
            'blocks': ['non_humanoid'],
            'generated': 'the approved wolf still from the creature library at 832x480, no post-processing — a full-body side view, four legs visible',
            'how_to_verify': 'confirm the still is a full-body side view (a head-and-shoulders wolf cannot answer a four-legged walk) and that it is a house render, not a fetched photograph; set verified = true',
        },
    ],
    'budget': {
        'calls': 32,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'both rows are driven by a still, a clip and a short fixed caption through CLIPTextEncode; no language model is called and no Claude week is touched anywhere on this step',
        'minutes': 105,
        'gpu_minutes': 100,
        'operator_minutes': 12,
        'note': (
            'Per row, defaulting to wan22_animate. 7 clip families (walk, face, hands, occlusion, two-people, wolf, Abel) x 3 seeds = 21 clips at ~150 s for 81 '
            "frames at 832x480 = ~53 min, plus the length ladder's two longer rungs (157 frames ~300 s, 233 frames ~450 s) x 3 seeds = ~38 min, plus ~3 min model "
            'load = ~94 min GPU. Measurement on top: MediaPipe pose/face/hands over 27 clips and their drivers, ArcFace on every 4th frame, Farneback and SAM2 for '
            'the flow and mask checks = ~9 min. 27 renders + 5 driver preprocessing passes = 32 calls. Operator: 8 blind questions x 3 seeds = 24 decisions at 30 s '
            '= 12 min. '
            'SHARED VIDEO BANK for this step, and it dwarfs the above: 132 subjects x 3 seeds = 396 v2v renders (the driver moves, the subject still is restyled) at '
            "~150 s = ~990 min = 16.5 h of GPU per row, plus the bank's prompt and capacity probes. Two rows = ~33 h. Schedule the domain probes first: they are "
            '~1.7 h and they answer the 15 columns nobody else can. '
            'NOT included and one-time: recording the five drivers (~1 afternoon) and marking their footfalls and occlusion window (~45 min), without which '
            'timing_keep, occlusion, face_transfer and hand_transfer stay BLOCKED.'
        ),
    },
    'run_order': [
        'per_frame',
        'identity',
        'driver_fidelity',
        'timing_keep',
        'costume_v2v',
        'background_v2v',
        'proportion',
        'face_transfer',
        'hand_transfer',
        'occlusion',
        'two_people_v2v',
        'non_humanoid',
        'length',
    ],
    'notes': [
        'per_frame runs first and costs almost nothing beyond one render per row: it is the column that tells the reader which SHAPE each row is, and every other column on the vace_static row should be read after it.',
        'Every transfer column is measured against the driver, in seconds, never against an ideal performance. A clip that is better than the driver has still failed the column.',
        "The length ladder's rungs are the real chunk arithmetic (81 / 157 / 233, seams at 81 and 157). Naive 81/162 rungs would put the seam checks in the wrong place and measure nothing.",
        'The shared video bank is 396 renders per row here. run_order exists so a run stopped after two hours has all 15 domain columns and none of the subject bank, rather than the other way round.',
        'The two rows share no fixture beyond the reference stills, because the vace_static path has no driver. That asymmetry is the finding of the sheet, not a gap in the test.',
    ],
}
