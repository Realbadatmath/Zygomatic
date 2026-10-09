# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Lip sync (lipsync). 2026-09-30.

Question the sheet asks: can we put a mouth on a shot that matches the line?

The sheet's own note says what is missing: "The actual sync QUALITY has never been scored — only
the plumbing around it. That is the gap on this sheet: four mechanical columns measured, the one
that matters untested." Its `next_tests` asks for lip-vertex error against the audio envelope on
twenty lines, or at minimum a blind operator A/B against the silent take. This test is that,
written as a measurement rather than an opinion: the mouth-open signal is a MediaPipe
face_landmarker time series (inner-lip distance normalised by inter-ocular distance), the audio
is an RMS envelope, and `sync` is the cross-correlation lag between them in milliseconds. A
number, per take, that a second model can be measured against next year.

FOUR FIXED LINES, one row. The row is InfiniteTalk (the audio-conditioning module for
Wan2.1-I2V-14B-480P) through lipsync_service.lipsync and _comfy_workflows/infinitetalk_i2v.json.
The lines are a Dutch line in the Cornelis cast voice, an English line with a planted one-second
silence in the child voice, one sung bar and one scream — because a mouth that works on calm
speech and fails on a scream is a mouth we cannot ship, and the scream is the case the house
actually needs (lipsync_service exists so "a shot's dialogue or scream has a face").

WHAT THE CODE ALREADY SETTLES, and is therefore a lookup with a receipt rather than a probe:
  * 25 fps is baked into the wav2vec embedding window, not a preference. The house Wan clips are
    17 fps and the result is resampled with ffmpeg; the receipt records both numbers.
  * the weights do NOT load out of the box. The module on disk is the fp8 *scaled* repack: 120
    audio_cross_attn weights carry a .scale_weight (mean 0.0865) and unscaled they are an order
    of magnitude too large — the take comes back as pure noise, measured, take 1. The wrapper
    applies those scales in one place only, reached when the quantization string contains
    "_scaled" or an UNMERGED LoRA is attached; the first route is rejected at
    nodes_model_loading.py:1222 because the base file is not a scaled one. So the graph attaches
    the character LoRA with merge_loras=false, and that LoRA is load-bearing twice over.
  * IMAGE MODE ONLY. ComfyUI-VideoHelperSuite is not installed, so a video source is handled by
    extracting its first frame: the mouth is audio-driven and the body motion is RE-GENERATED.
    `video_in` is still a PROBE, because the honest cell is a measurement of what came out (the
    source's motion, gone) and not a code read that lets the row off.

HONEST JUDGING. A local VLM is not asked whether a mouth looks right (defect bench 2026-09-27:
34/40 on a global question, 2/8 on the hard cases). Every column here has a landmark detector,
and the two that cannot have one — the six-word phoneme reading and teeth/tongue — are BLIND
operator questions with the wording fixed in this file. The Whisper word alignment that gives
the plosive times is an answer KEY and is unverified until the operator marks it, so
`consonants_lip` and `phoneme` are BLOCKED rather than graded against a machine's guess.
"""

from __future__ import annotations

# ── check kinds this module adds (the runner is a table of these) ──────────────────────
CHECK_KINDS = {
    'av_sync_lag_ms': 'cross-correlation lag between the mouth-open signal (MediaPipe face_landmarker inner-lip vertical distance divided by inter-ocular distance, per frame) and the audio RMS envelope (20 ms hops, resampled to the output fps) is <= `max` ms in absolute value, and the correlation at that lag is >= `min_r`',
    'lip_open_range_min': 'the peak-to-trough range of that same normalised mouth-open signal over the clip >= `min` — the mouth actually moves, so a sync lag measured on it means something',
    'lip_closed_at_times': "at the times in `times` (the plosive onsets in the fixture's verified word alignment) the normalised inner-lip distance is below `max_open`, in >= `share` of them",
    'lip_closed_share_min': 'over the silence windows (audio RMS below `floor_db` for >= `min_window_ms`), the share of frames whose normalised inner-lip distance is below `max_open` >= `min`',
    'mouth_shape_variety_min': 'k-means (k=`k`, on the per-frame triple of normalised lip width, lip height and jaw opening) yields >= `min_clusters` clusters each holding >= `min_share` of the frames — one generic flap collapses to a single cluster',
    'blink_count_min': 'the MediaPipe face_landmarker eyeBlinkLeft/eyeBlinkRight blendshapes both cross `threshold` at least `min` times over the clip',
    'brow_range_min': 'the peak-to-trough range of the browInnerUp blendshape over the clip >= `min`',
    'head_pose_range_min': 'the range of the head yaw (or `axis`) solved from the face_landmarker transformation matrix over the clip >= `min` degrees',
    'duration_matches_audio_frames': "the output duration equals the driving wav's duration within `frames` frames at the output fps (the wav is the truth, not the 81-frame sampling window)",
    'motion_matches_source_min': 'Pearson correlation between the per-frame MediaPipe pose-landmark centroid trajectory of the SOURCE clip and of the output >= `min`, over the frames where both are detected — measures whether an existing performance survived',
    'identity_clip_pass_frac': 'share of sampled output frames whose face embedding clears the per-frame floor in `floor` >= `min`, using the detector in `detector`; the floors and the aggregate rule are identity_bank.CLIP_FLOORS / CLIP_PASS_FRAC and a verdict needs >= CLIP_MIN_FOUND found frames',
}

FX = 'capability_tests/fixtures/lipsync'
MANIFEST = FX + '/MANIFEST.json'

# The four fixed lines. Verbatim — a runner may not re-synthesise them with another voice or
# another wording. The word alignment that `consonants_lip` and `phoneme` read is the operator's.
LINE_NL = FX + '/line_cornelis_nl.wav'
LINE_EN = FX + '/line_abel_en.wav'
SUNG = FX + '/sung_bar.wav'
SCREAM = FX + '/scream.wav'

TEXT_NL = 'Pieter, breng de manden bij de boot en pomp het water uit de bak.'
TEXT_EN = 'Mama, put the big brown box back beside the pump.'
SIX_WORDS = ['Mama', 'put', 'big', 'brown', 'box', 'pump']

# The stills the mouth is put on, and the clip that tests the video path.
R_FRONT = FX + '/ref_cornelis_closeup.png'
R_THREE_QUARTER = FX + '/ref_cornelis_three_quarter.png'
SRC_CLIP = FX + '/source_performance.mp4'

# Fixed conditions. Seeds, steps, cfg and sampler are the video bank's so a lipsync take and an
# i2v take are comparable; fps and resolution are this row's production values, recorded per
# trial (InfiniteTalk generates at 25 fps and the graph always samples there).
COND = {
    'seeds': [11, 12, 13],
    'repeats': 3,
    'fps': 25,
    'resolution': '832x480',
    'steps': 30,
    'cfg': 6.0,
    'sampler': 'uni_pc/simple',
    'lora': 'the character LoRA, merge_loras=false — NOT optional: it is what makes the fp8 scaled audio weights arrive scaled',
    'note': 'frames are whatever the wav needs (InfiniteTalk pads the last sampling window: a 3.00 s line returns 81 frames = 3.24 s) and the take is trimmed back to the wav; every landmark series is compared in SECONDS',
}

ROW = ['infinitetalk']

# 40 ms is one frame at 25 fps: the sync budget the brief fixes. 0.08 of the inter-ocular
# distance is the closed-mouth bar; a relaxed closed mouth measures near 0.02-0.04 and an open
# /a/ well above 0.15, so 0.08 sits between them rather than on either.
LAG_MS = 40
CLOSED = 0.08


def _p(pid, title, feeds, checks, rows, audio=None, image=None, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'audio': audio or LINE_NL, 'image': image or R_FRONT, 'fixture': MANIFEST, 'prompt': None},
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': rows,
    }
    p.update(kw)
    return p


PROBES = [
    _p(
        'sync',
        'Mouth matches the audio',
        ['sync'],
        [
            {'check': 'av_sync_lag_ms', 'max': LAG_MS, 'min_r': 0.45},
            {'check': 'lip_open_range_min', 'min': 0.10},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Watching this clip once with the sound on: does the mouth belong to this voice — no early or late mouth, no mouth moving through a pause? yes/no',
            },
        ],
        ROW,
        audio=[LINE_NL, LINE_EN],
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'the LAG decides and it is the number the sheet has never had: 40 ms is one frame at 25 fps. The correlation floor 0.45 and the range check are there so '
            "a lag measured on a barely-moving mouth cannot pass by accident — a near-still mouth has no lag to speak of. The blind question is the sheet's own "
            'next_tests fallback, kept as the second half rather than the whole thing.'
        ),
    ),
    _p(
        'phoneme',
        'Distinct phoneme shapes',
        ['phoneme'],
        [
            {'check': 'mouth_shape_variety_min', 'k': 6, 'min_clusters': 4, 'min_share': 0.05},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Watching this clip with the sound OFF, six words are spoken. For each, does the mouth shape suit that word rather than a generic open-and-close? Answer yes only if at least five of the six do.',
            },
        ],
        ROW,
        audio=[LINE_EN],
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'the six words are '
            + ', '.join(SIX_WORDS)
            + ' — chosen for the range of shapes (bilabial, rounded, wide, plosive). The k-means half says the mouth '
            'has more than one gesture in it; the sound-off operator half is the only instrument on this box that can say the gestures are the RIGHT ones. BLOCKED '
            'until the word alignment is verified, because the operator must be told where the six words are without being told what the model was.'
        ),
    ),
    _p(
        'consonants_lip',
        'Plosives and labials land',
        ['consonants_lip'],
        [
            {
                'check': 'lip_closed_at_times',
                'times': 'MANIFEST.lines.line_abel_en.plosive_onsets',
                'max_open': CLOSED,
                'share': 0.8,
            },
            {
                'check': 'lip_closed_at_times',
                'times': 'MANIFEST.lines.line_cornelis_nl.plosive_onsets',
                'max_open': CLOSED,
                'share': 0.8,
            },
        ],
        ROW,
        audio=[LINE_NL, LINE_EN],
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'the two lines are written for this column: "'
            + TEXT_EN
            + '" and "'
            + TEXT_NL
            + '" carry eleven p/b/m onsets between them. The times come from a '
            'Whisper word alignment the OPERATOR checks against the waveform (a machine alignment is not a key), so this column is BLOCKED until MANIFEST '
            'verified = true. 80 % rather than all of them: one missed labial in eleven is a soft mouth, not a broken one.'
        ),
    ),
    _p(
        'silence_closed',
        'Mouth closes in silence',
        ['silence_closed'],
        [
            {'check': 'lip_closed_share_min', 'min': 0.8, 'max_open': CLOSED, 'floor_db': -45.0, 'min_window_ms': 300},
            {
                'check': 'lip_open_range_min',
                'min': 0.10,
                'note': 'a mouth that never opens passes the silence check trivially; it must fail here instead',
            },
        ],
        ROW,
        audio=[LINE_EN],
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='the English line has a planted 1.0 s silence in the middle, and the windows are found MECHANICALLY from the RMS envelope, so this column needs no verified key and is the cheapest honest cell on the sheet',
    ),
    _p(
        'lang_lip',
        'Works on Dutch as well as English',
        ['lang_lip'],
        [
            {'check': 'av_sync_lag_ms', 'max': LAG_MS, 'min_r': 0.45, 'per_language': True},
            {
                'check': 'operator',
                'blind': True,
                'question': 'This clip is in Dutch. Watching it with the sound on: does the mouth match the words, or does it look like a mouth speaking some other language? Answer yes if it matches.',
            },
        ],
        ROW,
        audio=[LINE_NL, LINE_EN],
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'the cell is the DIFFERENCE between the two languages, not a pass mark: wav2vec2-chinese-base is the audio encoder, so neither language is its training '
            'language and the interesting number is whether the Dutch lag is worse than the English one on the same seeds. Report both lags beside the cell.'
        ),
    ),
    _p(
        'sung_lip',
        'Works on singing',
        ['sung_lip'],
        [
            {'check': 'av_sync_lag_ms', 'max': 80, 'min_r': 0.35},
            {'check': 'lip_open_range_min', 'min': 0.12},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Watching this clip with the sound on: is this a face singing this bar — sustained vowels held open, the phrase ending when the sound ends? yes/no',
            },
        ],
        ROW,
        audio=[SUNG],
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note="the lag budget is doubled to 80 ms on purpose: a sung vowel has no consonant edge to align to, so a tighter bar would measure the envelope's own vagueness. The range floor is raised because a sung bar with a small mouth range is wrong however well it correlates",
    ),
    _p(
        'scream_lip',
        'Works on a scream or a cry',
        ['scream_lip'],
        [
            {'check': 'lip_open_range_min', 'min': 0.20},
            {'check': 'av_sync_lag_ms', 'max': 80, 'min_r': 0.35},
            {
                'check': 'identity_clip_pass_frac',
                'min': 0.70,
                'floor': 0.42,
                'detector': 'facenet, as identity_bank enrolled it',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Watching this clip with the sound on: is this face screaming — mouth wide, held open through the sound — rather than mouthing a word or pulling apart? yes/no',
            },
        ],
        ROW,
        audio=[SCREAM],
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note="the house case: lipsync_service exists so a shot's dialogue OR SCREAM has a face. A wide mouth is the whole gesture, hence the 0.20 range floor, and identity is checked here because a scream is where a face comes apart first",
    ),
    _p(
        'trim',
        'Take matches the line length',
        ['trim'],
        [
            {'check': 'duration_matches_audio_frames', 'frames': 1},
            {
                'check': 'frames_exact',
                'frames': 'the wav duration x the output fps, rounded',
                'fps': "the trial's recorded output fps",
            },
        ],
        ROW,
        audio=[LINE_NL, LINE_EN, SUNG, SCREAM],
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='InfiniteTalk pads the last sampling window (a 3.00 s line returns 81 frames = 3.24 s), so without the trim the muxed video outruns the speech that drove it. All four lines, because the pad depends on where the line falls in the 81-frame window',
    ),
    _p(
        'video_in',
        'Preserves an existing performance',
        ['video_in'],
        [
            {'check': 'motion_matches_source_min', 'min': 0.6},
            {'check': 'shot_cuts', 'n': 0, 'note': 'whatever comes back must at least be one continuous take'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Comparing this clip with the source clip: does the body do the same thing — same gesture, same turn, same timing — with only the mouth changed? yes/no',
            },
        ],
        ROW,
        audio=[LINE_EN],
        image=SRC_CLIP,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            "measured, not read off the code, although the code says what to expect: the wrapper's V2V InfiniteTalk example is built on VHS_LoadVideo and "
            "ComfyUI-VideoHelperSuite is NOT installed on this box (checked against /object_info), so lipsync_service extracts the source's FIRST FRAME and drives "
            'image mode from it — the mouth is audio-driven and the body motion is re-generated. A correlation near zero is therefore the expected cell, and it is '
            'worth measuring because it is the difference between "we can dub an existing shot" and "we must re-render it".'
        ),
    ),
    _p(
        'identity_lip',
        'The face stays the same person',
        ['identity_lip'],
        [
            {'check': 'identity_cosine_ref', 'ref': R_FRONT, 'sample': 'every 4th frame', 'min': 0.35},
            {
                'check': 'identity_clip_pass_frac',
                'min': 0.70,
                'floor': 0.42,
                'detector': 'facenet, as identity_bank enrolled it',
            },
            {'check': 'identity_cosine_min', 'a': 0, 'b': -1, 'min': 0.35},
        ],
        ROW,
        audio=[LINE_NL, SCREAM],
        state_note=(
            "the clip verdict decides, on identity_bank's CALIBRATED floors (per-frame 0.42, pass_frac 0.70, >= 8 found frames): worst genuine frame 0.3943 against "
            'best impostor 0.3763 is an overlap-free window only 0.018 wide, so no single frame may decide a take. Cornelis has ~0.08 of headroom where Abel has '
            '~0.31, so a Cornelis failure may mean his 3-image bank is a worse centroid rather than that the mouth moved his face. `spread` is dispersion, NEVER '
            'continuity (shuffled frames score 0.7656 against 0.7666) and is not read. The character LoRA is attached on every take anyway, which is why this '
            'column is expected to be the strong one and why a failure here is a loud result.'
        ),
    ),
    _p(
        'head_free',
        'Head can move',
        ['head_free'],
        [
            {'check': 'head_pose_range_min', 'min': 8.0, 'axis': 'yaw'},
            {
                'check': 'av_sync_lag_ms',
                'max': LAG_MS,
                'min_r': 0.45,
                'note': 'the sync must survive the movement, which is the actual question',
            },
        ],
        ROW,
        audio=[LINE_NL],
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='8 degrees of yaw is a head that is alive rather than a photograph with a mouth cut into it. The column is a pair: a head that moves and loses the sync has not passed, and a locked head that syncs perfectly is the failure this column exists to catch',
    ),
    _p(
        'eyes_alive',
        'Eyes and blinks stay alive',
        ['eyes_alive'],
        [
            {'check': 'blink_count_min', 'min': 1, 'threshold': 0.5},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Watching this clip: do the eyes look alive — at least one real blink, gaze not frozen — rather than a staring mask? yes/no',
            },
        ],
        ROW,
        audio=[LINE_NL],
        conditions=dict(
            COND,
            note='the 8-second arm: the Dutch line is looped to 8 s of speech so a blink has time to happen (a 3 s take with no blink is not evidence of a dead face)',
        ),
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note="one blink in eight seconds is the floor a human clears three times over; the blendshape threshold 0.5 is the face_landmarker's own scale. Read with head_free: a take that neither blinks nor turns is a talking photograph",
    ),
    _p(
        'brows_lip',
        'Brows move with the line',
        ['brows_lip'],
        [
            {'check': 'brow_range_min', 'min': 0.15},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Watching this clip with the sound on: do the brows move WITH the line — stress, question, effort — rather than at random or not at all? yes/no',
            },
        ],
        ROW,
        audio=[LINE_NL, SCREAM],
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='the range says the brows moved; only the operator can say they moved with the line, and the two halves must agree before the cell is yes. An audio module driven by a wav2vec embedding has no reason to know where the stress is, so a measured no here is a finding, not a defect',
    ),
    _p(
        'teeth_lip',
        'Teeth and tongue hold up',
        ['teeth_lip'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Freezing on three frames where the mouth is open: are the teeth a row of teeth and the tongue a tongue — not a smear, not a second set of teeth, not a hole? yes/no',
            }
        ],
        ROW,
        audio=[LINE_EN, SCREAM],
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='the ONE column with no detector and it is written that way on purpose: no model on this box counts teeth (defect bench 2026-09-27, 2/8 on the hard cases), and inventing a texture metric here would dress a guess as a measurement',
    ),
    _p(
        'profile_lip',
        'Works off-frontal',
        ['profile_lip'],
        [
            {'check': 'av_sync_lag_ms', 'max': LAG_MS, 'min_r': 0.40},
            {
                'check': 'lip_open_range_min',
                'min': 0.08,
                'note': 'the normalisation is by inter-ocular distance, which foreshortens off-frontal; the floor is lowered for that, not for a softer mouth',
            },
            {
                'check': 'identity_clip_pass_frac',
                'min': 0.70,
                'floor': 0.42,
                'detector': 'facenet, as identity_bank enrolled it',
            },
        ],
        ROW,
        audio=[LINE_NL],
        image=R_THREE_QUARTER,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='a three-quarter still, not a true profile: at a full profile the face_landmarker loses the far-side lip points and the measurement stops meaning anything, so the test asks the hardest angle it can still measure and the sheet says which angle that was',
    ),
]

# ── the columns no trial can answer ────────────────────────────────────────────────────
LOOKUP = {
    'fps': {
        'source': 'lipsync_service.py:13-21 (the FPS paragraph) + _comfy_workflows/infinitetalk_i2v.json',
        'source_url': 'https://huggingface.co/MeiGen-AI/InfiniteTalk (model card) + the ComfyUI-WanVideoWrapper InfiniteTalk nodes',
        'revision': 'lipsync_service.py as of 2026-09-15; graph as of 2026-09-30',
        'requires': ['lipsync_service.py', '_comfy_workflows/infinitetalk_i2v.json'],
        'grade': 'receipt',
        'value': {
            'native_fps': 25,
            'why': 'baked into the wav2vec embedding window, not a preference — the graph always samples at 25',
            'house_fps': 17,
            'adaptation': 'a video source at another fps is resampled with ffmpeg -filter:v fps=, and the receipt records BOTH numbers; an image source has no fps of its own and keeps 25',
        },
        'state_note': (
            'NO at the house frame rate and YES at its own: this is the column that costs a resample on every shot. It matters beyond bookkeeping — a 25 fps take '
            'resampled to 17 drops roughly every third frame, and the mouth is the fastest thing in the frame, so the sync this test measures at 25 is not the '
            'sync the audience sees at 17. A future run should measure `sync` a second time AFTER the resample and report both.'
        ),
    },
    'weights': {
        'source': 'lipsync_service.py:29-44 (the LOADER CONSTRAINT paragraph) + data/runtime/model_licences_pending/LIPSYNC.json',
        'source_url': 'https://huggingface.co/MeiGen-AI/InfiniteTalk + ComfyUI-WanVideoWrapper nodes_model_loading.py',
        'revision': 'measured on this box, take 1, 2026-09-15',
        'requires': [
            'lipsync_service.py',
            '_comfy_workflows/infinitetalk_i2v.json',
            'data/runtime/model_licences_pending/LIPSYNC.json',
        ],
        'grade': 'receipt',
        'value': {
            'loads_out_of_the_box': False,
            'why': 'the module on disk is the fp8 SCALED repack: its 120 audio_cross_attn weights are fp8 and each carries a .scale_weight (mean 0.0865). Unscaled they are an order of magnitude too large and the take comes back as pure noise — measured, take 1.',
            'where_scales_are_applied': 'the wrapper applies them in exactly one place, custom_linear._replace_linear, which nodes_model_loading.loadmodel reaches only when the quantization string contains "_scaled" OR a LoRA is attached unmerged',
            'why_the_first_route_fails': 'the guard at nodes_model_loading.py:1222 inspects the BASE state dict, and Wan2_1-I2V-14B-480P_fp8_e4m3fn is not a scaled file; no scaled Wan2.1-I2V base is on this box',
            'the_fix_in_the_graph': 'the character LoRA is attached with merge_loras=false. It is wanted anyway for identity, and it is what makes the audio cross-attention weights arrive correctly scaled. Drop it only together with an unscaled InfiniteTalk module.',
            'licences': 'base Wan2_1-I2V-14B-480P_fp8_e4m3fn Apache-2.0 (already in model_licences.json); InfiniteTalk single fp8 scaled and wav2vec2-chinese-base fp16 Apache-2.0 / MIT, pending ledger LIPSYNC.json',
        },
        'state_note': (
            'NO — and this is the most useful cell on the sheet for whoever installs the next lipsync model, because the failure is SILENT in the worst way: not '
            'a stack trace but a take of pure noise, which a runner would otherwise score as "sync: no". A run that finds every take noisy must check this '
            'receipt before writing a single column.'
        ),
    },
    'res_lip': {
        'source': "_comfy_workflows/infinitetalk_i2v.json (the graph's width/height) + lipsync_service.py:47-52 (the weights paragraph names the 480P base)",
        'source_url': 'https://huggingface.co/Wan-AI/Wan2.1-I2V-14B-480P',
        'revision': 'graph as of 2026-09-30',
        'requires': ['_comfy_workflows/infinitetalk_i2v.json', 'lipsync_service.py'],
        'grade': 'receipt',
        'value': {
            'base_family': 'Wan2.1-I2V-14B-480P — a 480p model; there is no 720p InfiniteTalk pairing on this box',
            'generation_resolution': "read from the graph and recorded in every trial (832x480 under this test's conditions)",
            'driven_region': 'the cell is the generation resolution PLUS the measured face-box height as a fraction of frame height, reported per trial from the face_landmarker — the mouth only ever gets the pixels the framing gives it, and that fraction is a property of the shot, not of the model',
        },
        'state_note': (
            '480p, and the number that decides whether a take is usable is the second one: the close-up still this test uses is deliberately the kindest framing, '
            'so the sheet must say so. A medium shot at the same resolution gives the mouth a fraction of those pixels, and no probe here claims otherwise. '
            'Measured per trial rather than guessed here.'
        ),
    },
}

TEST = {
    'step': 'lipsync',
    'version': '2026-09-30.1',
    'title': 'Four fixed lines onto two stills, scored as a sync lag in milliseconds',
    'purpose': (
        'Close the gap the sheet names: score the sync QUALITY, not the plumbing around it. The mouth-open landmark series against the audio '
        'envelope gives a lag per take, so InfiniteTalk and whatever replaces it are measured on the same four lines under byte-identical settings.'
    ),
    'include_shared': ['video', 'audio'],
    'detectors_note': (
        'MediaPipe face_landmarker (478 points + blendshapes + the head transformation matrix) is the instrument of this whole test; the identity '
        "detectors are the video bank's insightface-buffalo_l and identity_bank's enrolled facenet banks; the envelope, the silence windows and the "
        'durations are plain signal processing (RMS in 20 ms hops, BS.1770-4 for nothing here, ffprobe for duration). Whisper is used ONLY to propose the '
        'word alignment the operator then verifies — never as the key itself.'
    ),
    'sync_definition': {
        'mouth_signal': 'mean vertical distance between the inner-lip landmark pairs, divided by the inter-ocular distance, per frame',
        'audio_signal': 'RMS envelope in 20 ms hops, resampled to the output fps',
        'statistic': 'the lag of the cross-correlation peak, in milliseconds, with the correlation at that lag reported beside it',
        'budget_ms': LAG_MS,
        'closed_mouth_threshold': CLOSED,
        'note': 'fixed here so two sheets are comparable. 40 ms is one frame at 25 fps; the sung and scream arms are allowed 80 ms because a held vowel has no consonant edge to align to.',
    },
    'rows': {
        'infinitetalk': {
            'transport': 'service',
            'where': 'lipsync_service.lipsync — _comfy_workflows/infinitetalk_i2v.json submitted through _comfy_client, inside ComfyUI-WanVideoWrapper; every submit preceded by lora_attest.attest_submit and licence_provenance.attest_licences',
            'model': 'InfiniteTalk single fp8 scaled (audio module) on Wan2_1-I2V-14B-480P_fp8_e4m3fn + wav2vec2-chinese-base fp16, character LoRA attached UNMERGED (merge_loras=false), 25 fps',
        },
    },
    'probes': PROBES,
    'derive': {},
    'lookup': LOOKUP,
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': LINE_NL,
            'verified': False,
            'blocks': ['consonants_lip', 'lang_lip'],
            'generated': (
                'tts_service on the registered Cornelis cast voice speaking, verbatim: "'
                + TEXT_NL
                + '" — 48 kHz mono, trimmed to the line, no processing. '
                'The eyes_alive arm uses the same wav looped to 8 s of speech with a 0.4 s gap at the loop point.'
            ),
            'how_to_verify': (
                'run Whisper word alignment, then in '
                + MANIFEST
                + ' check every word boundary against the waveform by hand and mark plosive_onsets '
                '(the p/b/m closures: Pieter, breng, manden, bij, boot, pomp, bak); set verified = true. Until then consonants_lip is written untested — key unverified.'
            ),
        },
        {
            'path': LINE_EN,
            'verified': False,
            'blocks': ['consonants_lip', 'phoneme'],
            'generated': (
                'tts_service on the registered Abel (child) cast voice speaking, verbatim: "'
                + TEXT_EN
                + '" — synthesised as TWO utterances, "Mama, put the big '
                'brown box back" and "beside the pump", concatenated with exactly 1.0 s of digital silence between them (the planted silence silence_closed reads). '
                '48 kHz mono, no processing.'
            ),
            'how_to_verify': (
                'as above; mark plosive_onsets (Mama, put, big, brown, box, back, beside, pump), the six-word list for the blind phoneme question '
                '(' + ', '.join(SIX_WORDS) + ') with their times, and the silence window; set verified = true'
            ),
        },
        {
            'path': SUNG,
            'verified': False,
            'blocks': ['sung_lip'],
            'generated': 'one sung bar (~4 s) cut at zero crossings from an existing kidsmusic vocal stem (output/kidsmusic/<id>/stems/vocals.flac), 48 kHz mono — a sustained-vowel phrase, not a rhythmic one',
            'how_to_verify': 'confirm by ear that the bar is one continuous sung phrase with at least one vowel held >= 0.5 s, and note the lyric in the MANIFEST; set verified = true',
        },
        {
            'path': SCREAM,
            'verified': False,
            'blocks': ['scream_lip'],
            'generated': 'the approved scream from the vocal_fx asset library (indexed in data/runtime/asset_library_vocal_fx_meta.json), trimmed to ~2 s at 48 kHz mono, licence row carried into the trial',
            'how_to_verify': 'confirm the library row has a clean licence and no ai_training restriction for this use, and that the clip is one scream rather than a montage; set verified = true',
        },
        {
            'path': R_FRONT,
            'verified': False,
            'blocks': ['identity_lip', 'sync', 'phoneme'],
            'generated': 'the registered canon portrait for Cornelis cropped to a head-and-shoulders CLOSE-UP at 832x480, no post-processing — the same image identity_bank has enrolled, so the reference and the identity metric agree about who he is',
            'how_to_verify': 'confirm the crop is one of the enrolled images, that the mouth is unobstructed and that the face box is >= 0.4 of frame height (the kindest framing, stated as such on the sheet); set verified = true',
        },
        {
            'path': R_THREE_QUARTER,
            'verified': False,
            'blocks': ['profile_lip'],
            'generated': 'the same character at roughly 45 degrees, 832x480, no post-processing — a three-quarter view, NOT a full profile (at a full profile the face_landmarker loses the far-side lip points)',
            'how_to_verify': 'confirm the face_landmarker returns all 478 points on the still itself before it is used as an input; set verified = true',
        },
        {
            'path': SRC_CLIP,
            'verified': False,
            'blocks': ['video_in'],
            'generated': 'an existing house Wan take of the same character (17 fps, 832x480, ~4 s) in which the body clearly does something — turns and lifts a hand — so that "did the performance survive" has something to survive',
            'how_to_verify': "confirm MediaPipe pose landmarks are found in >= 90 % of the SOURCE clip's own frames (a source the detector cannot read cannot measure preservation) and record its fps; set verified = true",
        },
    ],
    'budget': {
        'calls': 22,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'the row is driven by a wav and a still through an audio cross-attention module; no language model is called anywhere on this step and no Claude week is touched',
        'minutes': 66,
        'gpu_minutes': 58,
        'operator_minutes': 15,
        'note': (
            'Six take families x 3 seeds = 18 takes: the Dutch line, the English line, the 8 s looped line (eyes_alive), the sung bar, the scream, the '
            'three-quarter still, and the video source (the last two reuse the English and Dutch lines). At ~180 s for an 81-frame 480p take = ~54 min, '
            '+ ~4 min to load the base, the InfiniteTalk module, wav2vec2 and the LoRA = ~58 min GPU. Measurement on top: face_landmarker over ~1500 frames, '
            'ArcFace every 4th frame, 4 Whisper alignments (~20 s each) = ~8 min. 18 renders + 4 alignments = 22 calls. Operator: 10 blind questions x 3 seeds '
            '= 30 decisions at 30 s = 15 min. '
            'SHARED BANKS for this step: the video bank leaves the 132-subject render/move bank OUT of lipsync (it asks 106 columns, not 405), so the only '
            "bank cost is the AUDIO bank's seven Capacity ladders (acap_*) — roughly 5 rungs x 3 seeds x 7 ladders, but most rungs are the same take measured "
            'differently; budget ~40-60 extra takes, i.e. ~2-3 h GPU, and schedule them after the domain probes. '
            "NOT included and one-time: synthesising the four lines (~10 min) and the operator's word-alignment pass over the two spoken lines (~30 min), "
            'without which consonants_lip and phoneme stay BLOCKED.'
        ),
    },
    'run_order': [
        'trim',
        'sync',
        'silence_closed',
        'identity_lip',
        'head_free',
        'eyes_alive',
        'brows_lip',
        'phoneme',
        'consonants_lip',
        'lang_lip',
        'profile_lip',
        'sung_lip',
        'scream_lip',
        'video_in',
        'teeth_lip',
    ],
    'notes': [
        "trim runs first because it is free and it validates the whole measurement chain: if the take does not match the wav's length, every lag measured against that wav is measured against the wrong clock.",
        'Read `weights` before any column on this sheet. The failure it records is a take of pure noise, which scores as "sync: no" unless the reader knows why.',
        "Read `fps` beside `sync`. The sync measured at the model's 25 fps is not the sync the audience sees after the resample to the house 17 fps; that second measurement is not in this version of the test and is named in the limitations.",
        'video_in is expected to measure a no, and that is the point: it is the difference between dubbing an existing shot and re-rendering it, and it is a missing ComfyUI node rather than a missing model capability.',
        "The seven acap_* Capacity columns come from the shared AUDIO bank. Two of them — acap_instruments and acap_voices — have no real referent for a single-face lipsync module; whatever the bank writes there should be read as the bank's own question, not as a claim about this row. Not changed here: the bank is not this task's file.",
    ],
}
