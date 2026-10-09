# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Mix & master (audio_mix). 2026-09-30.

Question the sheet asks: does the delivered mix hit its loudness target without pumping?

The rows are not models. They are a DSP chain (audio_mix.py driven by video_audio.py), a
single ffmpeg filter as the CONTROL, and a meter (audio_qc.py) that measures but mixes
nothing. So the test is one fixed FIXTURE SET — a 1672 narration stem with a scripted 3 s
pause, a music bed, an SFX, a spliced +6 dB transient, six scene masters and the same line
by the WRONG cast voice — pushed through each row exactly as production wires it, and
measured with meters, not ears, wherever a meter exists.

Two things this test refuses to assume:

  * CHAIN ORDER. The house rule is limiter BEFORE loudnorm (audio_mix.level_to, "limiter-
    first", audio_mix.py:545-568), because loudnorm's linear=true is a REQUEST that ffmpeg
    silently downgrades to dynamic AGC (audio_mix.py:14-22). The `order` column is therefore
    measured off a fixture with a +6 dB transient in it: limiter-then-loudnorm leaves no
    overshoot and a flat short-term curve; loudnorm-then-limiter pumps. Nobody reads the
    order off the source code for the sheet.
  * WRONG VOICE. The sheet's own note says the "wrong voice" cell is a measured NO on
    purpose: it records a class of failure the loudness gates structurally cannot see. So
    the probe runs on all three rows and two of them are expected to score no. That is the
    finding, not a gap in the test.

Targets are the house constants, not invented here: -14.0 LUFS integrated / -1.0 dBTP
(audio_mix.master, audio_mix.py:475-481; audio_qc.qc_lufs target=-14.0 tol=1.0 tp_max=-1.0,
audio_qc.py:127; run_master_gates, audio_qc.py:578). WPM is audio_qc's own
_WPM_RANGE_DEFAULT = (125, 165), audio_qc.py:258.

BLOCKED: the narration render and the wrong-voice pair carry answer keys nobody has
verified by ear yet, so wpm, sfx_seat, silence and wrong_voice ship `untested — key
unverified` until the operator signs them off. Nothing in this module generates a file.

Every row is a parameter set, never a prompt: the four Prompt bands are na for the whole
step (`na_bands`), which is the same disposition the subtitles formatter takes.
"""

from __future__ import annotations

FX = 'capability_tests/fixtures/audio/mix'

# Check kinds this step needs and the base vocabulary does not have. The audio bank already
# owns lufs_range, true_peak_max, silence_max, pause_ms, rms_delta_db and transcript_*; these
# are the mixing-specific ones, named for what is measured against what.
CHECK_KINDS = {
    'lra_range': 'EBU R128 loudness range (ffmpeg ebur128 LRA) between `min` and `max` LU',
    'order_signature': (
        'on the +6 dB transient fixture BOTH must hold: (a) no 400 ms window '
        'exceeds `ceiling_dbtp` true peak, and (b) the peak-to-trough spread of '
        'the 3 s short-term loudness around the transient is <= `max_spread_lu`. '
        'limiter-before-loudnorm satisfies both; loudnorm-before-limiter fails '
        '(b). The chain ORDER is read off these two numbers and never off the code'
    ),
    'gain_reduction_depth_max': (
        'peak-to-trough spread of the 400 ms short-term loudness of the '
        'music bed, with the dialogue bars excluded, <= `max` LU'
    ),
    'clip_sample_count_max': 'decoded samples whose absolute value is >= `at` (1.0 = full scale) number at most `max`',
    'dialogue_margin_min': (
        'integrated LUFS of the speech stem minus the integrated LUFS of the '
        'music stem, both measured over the `window` named bars of the mix, >= `min` LU'
    ),
    'duck_onset_ms': (
        'at every speech onset the bed short-term loudness falls by >= `drop_lu` within '
        '`attack_ms`, and is back within `recover_lu` of its pre-duck value within '
        '`release_ms` of speech end; holds for >= `share` of the onsets'
    ),
    'wer_delta_max': (
        'Whisper WER of the speech WITH the layer named in `layer` minus the WER of the '
        'same speech without it <= `max`; same decoder, same model, same seed both times'
    ),
    'lufs_spread_max': 'max minus min integrated LUFS over the `n` scene masters <= `max` LU',
    'silence_map_match': (
        'every scripted pause in `pause_map` is found by ffmpeg silencedetect with '
        '|detected - scripted| <= `tol_ms`, and no unscripted silence longer than '
        '`unscripted_max_ms` exists anywhere in the file'
    ),
    'wpm_range': (
        'Whisper words per minute over the detected speech spans between `min` and `max`, '
        'with transcript-to-script match ratio >= `min_match`'
    ),
    'wrong_voice_caught': (
        'the row reports a FLAG on the planted wrong-cast take and NO flag on its '
        'right-cast twin, on every repeat. The flag is whatever identity figure the '
        'row owns crossing `threshold` (TitaNet-large cosine for a sung stem, '
        'voice_qc F0+VTL bands for speech); a row with no identity figure raises no '
        'flag and scores no — that is the measurement'
    ),
    'mono_correlation_min': (
        'Pearson correlation of L and R >= `min` AND the mono sum loses at most '
        '`max_loss_db` dB RMS against the stereo master (a cancelling layer shows up here)'
    ),
    'returns_none_not_raise': (
        'for every broken input in `inputs` the row returns its documented failure '
        'value (None, or a dict whose ok is False/None) and NO exception crosses the '
        'module boundary: the runner asserts the call returned, the process exit code '
        'is 0 and stderr carries no traceback'
    ),
}

# House delivery standard — every number is a constant of the production modules, cited.
HOUSE = {
    'lufs_target': -14.0,
    'lufs_tol': 1.0,
    'true_peak_max': -1.0,
    'lra_min': 4.0,
    'lra_max': 12.0,
    'dialogue_margin_min': 6.0,
    'pump_max_lu': 3.0,
    'scene_spread_max_lu': 3.0,
    'wpm_min': 125,
    'wpm_max': 165,
    'silence_tol_ms': 100,
    'unscripted_max_ms': 800,
    'source': (
        'lufs_target/true_peak_max: audio_mix.master(i=-14.0, tp=-1.0) audio_mix.py:475-481 and '
        'audio_qc.qc_lufs(target=-14.0, tol=1.0, tp_max=-1.0) audio_qc.py:127; '
        'wpm: audio_qc._WPM_RANGE_DEFAULT = (125, 165) audio_qc.py:258; '
        'unscripted_max_ms: audio_qc.qc_silence_map(unscripted_max_ms=800) audio_qc.py:173. '
        'lra 4-12 LU, pump 3 LU, scene spread 3 LU (+-1.5) and silence_tol_ms 100 are set HERE '
        'as the TEST standard because no production module defines them — the production silence '
        'gate is the looser tol_ms=150 of audio_qc.py:173, which this probe also records.'
    ),
}

# The bank's conditions, so a mix trial and a sound trial are never scored side by side.
COND = {
    'repeats': 3,
    'seeds': None,
    'sample_rate': 48000,
    'channels': 1,
    'note': (
        '48 kHz mono in, 48 kHz stereo master out (dual_mono measurement on a mono source, '
        'audio_mix.py:28-30). Every row here is deterministic DSP, so `seed` is written null '
        'on the trial and the 3 repeats measure the ffmpeg build, not a sampler. The same '
        'fixture bytes for every row: a row that resamples records its native rate.'
    ),
}

ALL = ['chain', 'loudnorm', 'gates']
MIX = ['chain', 'loudnorm']


def _p(pid, title, feeds, checks, rows, fixture, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'fixture': fixture, 'audio': fixture, 'prompt': None},
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': list(rows),
    }
    p.update(kw)
    return p


F_MIX = FX + '/narration.wav + ' + FX + '/bed_music.wav'
F_TRANS = FX + '/transient.wav'
F_SCENES = FX + '/scenes/scene_01..06.wav'
F_VOICE = FX + '/wrong_cast.wav vs ' + FX + '/right_cast.wav (reference ' + FX + '/cast_reference.wav)'

PROBES = [
    _p(
        'no_clip',
        'No clipping',
        ['clip'],
        [{'check': 'clip_sample_count_max', 'at': 1.0, 'max': 0}],
        ALL,
        F_MIX,
        state_note='a single sample at full scale fails the column; the master is read as float32 so a clamped s16 write is visible as a run of exactly-1.0 samples',
    ),
    _p(
        'delivery_target',
        'Hits the LUFS target',
        ['target'],
        [{'check': 'lufs_range', 'min': -15.0, 'max': -13.0}],
        MIX,
        F_MIX,
        state_note='-14.0 +-1.0 LUFS integrated, BS.1770-4, dual_mono on a mono source; the house target, not a preference (audio_mix.py:475-481)',
    ),
    _p(
        'peak_ceiling',
        'True peak under the ceiling',
        ['peak'],
        [{'check': 'true_peak_max', 'max': -1.0}],
        MIX,
        F_MIX,
        state_note='-1.0 dBTP, 4x oversampled. audio_mix.level_to defaults to -1.5 dBTP internally and master() delivers at -1.0; the column measures the DELIVERED file',
    ),
    _p(
        'lra_sane',
        'Loudness range is sane',
        ['lra'],
        [{'check': 'lra_range', 'min': 4.0, 'max': 12.0}],
        MIX,
        F_MIX,
        state_note='below 4 LU the narration has been flattened, above 12 LU loudnorm will have refused linear mode (audio_mix.py:14-22) and the mix will pump',
    ),
    _p(
        'mono_sum',
        'Mono-compatible',
        ['phase_mono'],
        [{'check': 'mono_correlation_min', 'min': 0.9, 'max_loss_db': 3.0}],
        MIX,
        F_MIX,
        state_note='the house master is a dual-mono upmix (pan c0->both), so correlation 1.0 is expected; the probe exists to catch a bed layer or an acrossfade that cancels',
    ),
    _p(
        'chain_order',
        'Chain order is measured, not assumed',
        ['order'],
        [{'check': 'order_signature', 'ceiling_dbtp': -1.0, 'max_spread_lu': 3.0}],
        ALL,
        F_TRANS,
        state_note=(
            'THE column of this sheet. The +6 dB door-slam transient at 15 s is the probe: the house arm '
            '(audio_mix.level_to, limiter-first) must leave no window over -1.0 dBTP and a short-term spread '
            '<= 3 LU around the transient; a loudnorm-first arm pumps and fails (b). Reading "limiter before '
            'loudnorm" off the source code is exactly what this column refuses to accept.'
        ),
    ),
    _p(
        'no_pump',
        'No pumping',
        ['pump'],
        [
            {'check': 'gain_reduction_depth_max', 'max': 3.0, 'exclude': 'dialogue bars'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Listening to the music bed under this 30 s excerpt, does the music breathe in and out with the narration (audible level surging between phrases)? yes/no',
            },
        ],
        MIX,
        F_MIX,
        state_note='the meter is the 400 ms short-term curve over the bed with the dialogue bars cut out; the blind listen is kept because a 2.9 LU pump is still audible and the meter would pass it',
    ),
    _p(
        'dialogue_margin',
        'Dialogue stays intelligible over music',
        ['dialogue'],
        [{'check': 'dialogue_margin_min', 'min': 6.0, 'window': 'dialogue bars 4-12 and 20-28'}],
        MIX,
        F_MIX,
        state_note='speech integrated LUFS minus music integrated LUFS over the dialogue bars >= 6 LU; measured on the stems as mixed, not on the pre-mix gains',
    ),
    _p(
        'ducking',
        'Ducking is musical',
        ['duck'],
        [
            {
                'check': 'duck_onset_ms',
                'drop_lu': 6.0,
                'attack_ms': 200,
                'release_ms': 1000,
                'recover_lu': 1.0,
                'share': 0.9,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'At each point where the narrator starts speaking in this excerpt, does the music duck without an audible click, swoop or late lunge? yes/no',
            },
        ],
        MIX,
        F_MIX,
        state_note='audio_mix.duck_mix is sidechaincompress with an asplit key tap and amix normalize=0 (audio_mix.py:411); the numbers measure attack and release, the blind listen measures whether it is musical',
    ),
    _p(
        'sfx_seat',
        'SFX sit without masking speech',
        ['sfx_seat'],
        [{'check': 'wer_delta_max', 'max': 0.02, 'layer': FX + '/sfx_door.wav under the narration at 6 s'}],
        MIX,
        F_MIX,
        state_note='intelligibility proxy: the same Whisper decode of the same speech with and without the SFX layer; a seating that costs more than 2 points of WER is masking, whatever it sounds like',
    ),
    _p(
        'scene_match',
        'Levels match across scenes',
        ['scene_match'],
        [{'check': 'lufs_spread_max', 'max': 3.0, 'n': 6}],
        MIX,
        F_SCENES,
        state_note='six scene masters, integrated LUFS, max minus min <= 3.0 LU (every scene within +-1.5 of the set mean); the scene that is furthest out is named in the note',
    ),
    _p(
        'silence_map',
        'Silence map is clean',
        ['silence'],
        [
            {
                'check': 'silence_map_match',
                'pause_map': FX + '/pause_map.json',
                'tol_ms': 100,
                'unscripted_max_ms': 800,
            },
            {'check': 'silence_max', 'max': 3.2},
        ],
        ALL,
        F_MIX,
        state_note=(
            'the fixture plants one 3000 ms pause; this probe requires it within +-100 ms (the TEST standard) '
            'and records the verdict of the production gate audio_qc.qc_silence_map at its own looser '
            'tol_ms=150 alongside. Pauses below the 250 ms detection floor are undetectable by construction '
            '(audio_qc.py:52) and the fixture plants none.'
        ),
    ),
    _p(
        'pace',
        'Words per minute in range',
        ['wpm'],
        [{'check': 'wpm_range', 'min': 125, 'max': 165, 'min_match': 0.9}],
        ALL,
        FX + '/narration.wav',
        state_note=(
            "audio_qc._WPM_RANGE_DEFAULT = (125, 165), audio_qc.py:258 — the production window, not the test's "
            'opinion. The fixture is scripted to land near 150 WPM so it sits inside both this window and the '
            'wider 130-170 one the sheet brief quotes. Whisper is pinned to CPU by audio_qc (audio_qc.py:38-40), '
            'so this probe never touches the GPU. articulation_wpm is recorded as a diagnostic and never gated.'
        ),
    ),
    _p(
        'wrong_voice',
        'Catches a correct-sounding but wrong take',
        ['wrong_voice'],
        [
            {
                'check': 'wrong_voice_caught',
                'threshold': 'TitaNet cosine < 0.50 (sung) / voice_qc |dF0| > 18 % or |dVTL| > 1.0 cm (speech)',
                'pairs': 1,
            }
        ],
        ALL,
        F_VOICE,
        state_note=(
            'the wrong-cast take is the same line, same script, same loudness, by a different cast voice of the '
            'same sex and age band — every loudness figure on it is perfect. chain and loudnorm own no identity '
            'figure at all and are expected to score NO: that is the measured receipt the sheet note asks for '
            '("a class of failure the loudness gates structurally cannot see"). gates can answer it through '
            'audio_qc.qc_voice -> voice_qc.gate_voice_identity (audio_qc.py:545), tolerances '
            'F0_TOL_PCT=18 / VTL_TOL_CM=1.0 (voice_qc.py:42-43).'
        ),
    ),
    # `failsafe` is a universal column, but this step has a documented module-boundary contract
    # worth measuring rather than assuming, so the step owns it instead of the shared bank.
    _p(
        'failsafe',
        'Fails without breaking the caller',
        ['failsafe'],
        [
            {
                'check': 'returns_none_not_raise',
                'inputs': [
                    'a zero-byte file named .wav',
                    FX + '/broken_header.wav (header claims 40 s, holds 0.2 s of data)',
                    'a path that does not exist',
                    'a file of digital silence (ebur128 reports -70.0 LUFS)',
                ],
            },
            {
                'check': 'operator',
                'blind': False,
                'question': 'Reading the run log for these four broken inputs, did the row report WHICH input it refused and why, rather than failing quietly? yes/no',
            },
        ],
        ALL,
        FX + '/broken_header.wav',
        state_note=(
            'the house contract is explicit and is what this probe tests: audio_mix returns out_path on '
            'success and None on failure with details to log_fn (audio_mix.py:43-46); audio_qc gates return a '
            'dict with a measured verdict, never raise across the module boundary, and hard gates fail CLOSED '
            'while the soft CLAP gate fails OPEN with ok=None (audio_qc.py:8-13). The silence case is the '
            'interesting one: audio_mix.level_to must report silent=True rather than chase an unreachable '
            'target (audio_mix.py:545-562, _SILENT_LUFS = -69.0).'
        ),
    ),
]

# Cheap mechanical meters first; the Whisper and identity probes last, so a partial run still
# fills the Delivery band.
RUN_ORDER = [
    'failsafe',
    'no_clip',
    'delivery_target',
    'peak_ceiling',
    'lra_sane',
    'mono_sum',
    'chain_order',
    'no_pump',
    'dialogue_margin',
    'ducking',
    'scene_match',
    'silence_map',
    'pace',
    'sfx_seat',
    'wrong_voice',
]

NA_BANDS = {
    'reason': (
        'every row on this step takes a parameter set, never an instruction: the house chain is '
        'ffmpeg filter graphs driven by audio_mix.py, the control row is one loudnorm filter, and the '
        'gates row is a set of meters. There is no prompt to damage, shorten, translate or steer.'
    ),
    'bands': ['Prompt: damage', 'Prompt: clarity needed', 'Prompt: limits', 'Prompt: steering'],
}

# The meter row measures a finished file; it produces no audio, so the mixing columns have
# nothing to measure on it.
NA_GATES = {
    c: 'audio_qc.py measures a delivered file and writes no sample into it; there is no mix on this row to hit a target, shape or balance — the column belongs to the rows that process audio'
    for c in ['target', 'peak', 'lra', 'pump', 'dialogue', 'duck', 'sfx_seat', 'scene_match', 'phase_mono']
}
NA_LOUDNORM = {
    'duck': 'the control row is one loudnorm filter over one finished file: it has no sidechain key input and no separate bed, so there is no ducking behaviour to measure',
    'sfx_seat': 'the control row normalises a finished file and never layers an SFX under speech, so no seating decision exists on it to measure',
    'dialogue': 'one-pass loudnorm sees a single summed file; speech and music are not separate inputs on this row, so a speech-to-music margin cannot be set by it',
}

TEST = {
    'step': 'audio_mix',
    'version': '2026-09-30.1',
    'title': 'One planted fixture set through the house chain, a bare loudnorm control and the meters',
    'purpose': (
        'Measure the delivered mix against the house loudness standard, and measure the CHAIN ORDER off a '
        'planted transient instead of reading it off the code. A bare loudnorm row is carried as the control '
        'so every number has something to be better than.'
    ),
    'include_shared': 'audio',
    'house_standard': HOUSE,
    'run_order': RUN_ORDER,
    'rows': {
        'chain': {
            'transport': 'service',
            'where': 'audio_mix.level_to -> audio_mix.duck_mix -> audio_mix.fade_out -> audio_mix.master, driven by video_audio.py scene assembly (the house order: limiter BEFORE loudnorm)',
            'model': 'audio_mix.py + video_audio.py (ffmpeg-as-a-tool, CPU only)',
        },
        'loudnorm': {
            'transport': 'ffmpeg',
            'where': 'ffmpeg -af loudnorm=I=-14:TP=-1:linear=true, two passes, NOTHING before it — the CONTROL row',
            'model': 'ffmpeg loudnorm alone',
            'na': NA_LOUDNORM,
            'budget': {
                'calls': 24,
                'minutes': 12,
                'operator_minutes': 5,
                'note': 'the control row skips duck, sfx_seat and dialogue (na), so 24 of the 42 calls and 12 of the 20 minutes',
            },
        },
        'gates': {
            'transport': 'service',
            'where': 'audio_qc.run_master_gates / run_stem_gates -> qc_lufs, qc_silence_map, qc_wpm, qc_fade, qc_runtime, qc_voice',
            'model': 'audio_qc.py (a QC, not a mixer)',
            'na': NA_GATES,
            'budget': {
                'calls': 14,
                'minutes': 10,
                'operator_minutes': 2,
                'note': 'nine mixing columns are na on a meter row; what is left is failsafe, clip, order, silence, wpm and wrong_voice — 14 measurement passes, Whisper on CPU dominating the 10 minutes',
            },
        },
    },
    'na_bands': NA_BANDS,
    'probes': PROBES,
    'derive': {},
    'lookup': {
        'platform': {
            'grade': 'vendor',
            'from': (
                'the delivery spec each platform publishes, with the house target beside it: YouTube normalises '
                'DOWN to about -14 LUFS and never boosts (so -14.0 / -1.0 dBTP is the house delivery and a '
                'quieter master permanently loses loudness, audio_mix.py:26-30); EBU R128 broadcast is -23 LUFS '
                '/ -1 dBTP with LRA reported. The cell is written from the pinned revision of each document '
                'TOGETHER WITH the measured integrated LUFS, true peak and LRA of the fixture master, so it says '
                'whether the delivery meets the spec rather than whether the spec was read.'
            ),
            'requires': [
                {
                    'source': 'YouTube loudness normalisation help page',
                    'url': 'https://support.google.com/youtube/answer/6375112',
                    'pin': 'record the retrieval date and the quoted target with the cell',
                },
                {
                    'source': 'EBU R 128 (loudness normalisation and permitted maximum level)',
                    'url': 'https://tech.ebu.ch/publications/r128',
                    'pin': 'record the revision (R 128-2020 or later) with the cell',
                },
                {
                    'source': 'the measured numbers',
                    'url': "the run's own ebur128 output for the fixture master",
                    'pin': 'integrated LUFS, true peak, LRA — the same three figures the spec constrains',
                },
            ],
            'note': 'a lookup without the measured values beside it would only prove somebody read a web page, so this cell carries both',
        },
    },
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': FX + '/narration.wav',
            'verified': False,
            'blocks': ['wpm', 'sfx_seat', 'silence'],
            'generated': (
                'render capability_tests/fixtures/audio/mix/narration_script.txt with the Abel cast voice at '
                'the production settings (abel_voice.py render path, engine chatterbox, CPU), scripted to ~150 '
                'WPM with ONE 3000 ms pause after the third sentence; then: ffmpeg -y -i raw.wav -ar 48000 -ac '
                '1 -c:a pcm_s24le narration.wav. Write the beat list the renderer produced to pause_map.json in '
                'the audio_qc contract shape {"head_ms":0,"tail_ms":0,"silences":[{"beat":"b03","start_s":<s>,"ms":3000}]}.'
            ),
            'how_to_verify': (
                'the operator plays narration.wav once against narration_script.txt and confirms (a) every '
                'word of the script is spoken, (b) the 3 s gap is where the script puts it, (c) the voice is '
                'the Abel cast voice. Only then set verified = true — wpm and sfx_seat are scored against '
                'this script as the transcript key and silence against this pause map.'
            ),
        },
        {
            'path': FX + '/narration_script.txt',
            'verified': True,
            'generated': 'write the script by hand: 1672 Dutch-drama narration, English, ~150 words of plain sentences, one deliberate 3 s dramatic pause marked after the third sentence, no digits (the TTS reads words reliably and digits inconsistently)',
        },
        {
            'path': FX + '/pause_map.json',
            'verified': True,
            'generated': 'written by the narration renderer next to narration.wav; the audio_qc pause_map contract (audio_qc.py:40-46). Entries below the 250 ms detection floor are skipped',
        },
        {
            'path': FX + '/bed_music.wav',
            'verified': True,
            'generated': 'take one soundtracks-shelf bed from the house asset library, trim to 40 s, peak-normalise to -6 dBFS, 48 kHz mono, 24-bit: ffmpeg -y -i <bed> -t 40 -af "volume=-6dB:precision=float" -ar 48000 -ac 1 -c:a pcm_s24le bed_music.wav',
        },
        {
            'path': FX + '/sfx_door.wav',
            'verified': True,
            'generated': 'the highest-rated door-slam slate from the SFX library, trimmed to 1.2 s, peak-normalised to -3 dBFS: ffmpeg -y -i <slate> -t 1.2 -ar 48000 -ac 1 -c:a pcm_s24le sfx_door.wav',
        },
        {
            'path': FX + '/transient.wav',
            'verified': True,
            'generated': (
                'ffmpeg -y -i narration.wav -i sfx_door.wav -filter_complex '
                '"[1]volume=6dB,adelay=15000[t];[0][t]amix=inputs=2:normalize=0:duration=first" '
                "-t 30 -ar 48000 -ac 1 -c:a pcm_s24le transient.wav  — a +6 dB slam at 15 s inside 30 s of narration; this is the order probe's only input"
            ),
        },
        {
            'path': FX + '/scenes',
            'verified': True,
            'generated': (
                'six scene sources of deliberately different density (quiet interior, harbour exterior, crowd, '
                'storm, dialogue duet, near-silence), each 20 s, each built the same way as bed_music.wav, '
                'written as scenes/scene_01.wav .. scenes/scene_06.wav. The row masters each one with ITS OWN '
                'chain and the probe measures the spread of the six delivered masters'
            ),
        },
        {
            'path': FX + '/right_cast.wav',
            'verified': False,
            'blocks': ['wrong_voice'],
            'generated': 'one 8 s line of narration_script.txt rendered with the Abel cast voice at the production settings, then levelled with audio_mix.level_to to -14 LUFS so its loudness figures are perfect',
            'how_to_verify': 'the operator listens to right_cast.wav and cast_reference.wav back to back and confirms they are the same person; this pair is the identity KEY the wrong-voice probe scores against',
        },
        {
            'path': FX + '/wrong_cast.wav',
            'verified': False,
            'blocks': ['wrong_voice'],
            'generated': 'the SAME 8 s line, same text, same settings, rendered with a DIFFERENT cast voice of the same sex and the same age band, then levelled with audio_mix.level_to to -14 LUFS — identical loudness, wrong person',
            'how_to_verify': 'BLIND: the operator hears wrong_cast.wav and right_cast.wav in random order, without filenames, and must name which one is not the cast voice. If the operator cannot hear it either, the fixture is too subtle and is replaced — not relabelled',
        },
        {
            'path': FX + '/broken_header.wav',
            'verified': True,
            'generated': (
                'ffmpeg -y -f lavfi -i "sine=frequency=440:duration=0.2" -ar 48000 -ac 1 -c:a pcm_s16le tmp.wav '
                'then patch the two length fields so the header lies: python3 -c "import struct,sys; b=bytearray('
                "open('tmp.wav','rb').read()); n=48000*2*40; b[4:8]=struct.pack('<I', n+36); "
                "b[40:44]=struct.pack('<I', n); open('broken_header.wav','wb').write(b)\" — a WAV that "
                'claims 40 s and holds 0.2 s. Mechanically checkable, so no ear is needed to verify it'
            ),
            'how_to_verify': 'ffprobe reports a 40 s duration and the decoder yields 0.2 s of samples; that disagreement IS the fixture',
        },
        {
            'path': FX + '/cast_reference.wav',
            'verified': False,
            'blocks': ['wrong_voice'],
            'generated': 'the cast identity reference for the Abel voice, the same file the production gates use (ABEL_IDENTITY_REF in abel_voice.py:258-262), copied here at 48 kHz mono 24-bit so the fixture set is self-contained',
            'how_to_verify': 'confirm the copy is byte-identical in content to the production reference and that it is the voice the script names',
        },
    ],
    'budget': {
        'calls': 42,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'a mixing chain and a set of meters take a parameter set and a wav; no language model is called anywhere on this step, so no tokens are spent',
        'minutes': 20,
        'gpu_minutes': 0,
        'operator_minutes': 5,
        'note': (
            'Per row: 27 renders/measurement passes (base mix x3 repeats = 3; transient fixture x3 = 3; dialogue-bar '
            'mix x3 = 3; SFX on and off x3 = 6; six scene masters x1 = 6; wrong/right cast x3 = 6) at ~12 s of '
            'ffmpeg each = ~5.5 min, plus 9 Whisper decodes (3 for wpm, 6 for the sfx_seat A/B) at ~50 s each on '
            "CPU = ~7.5 min, plus 6 ebur128-only measurement passes = ~2 min, plus the SHARED AUDIO BANK's share "
            'for this step = the seven acap_* capacity ladders (the 53-label sound bank and the four Prompt bands '
            'are NOT asked here: the Hears bands are not on this sheet and the Prompt bands are na_bands), ~28 '
            'CPU mixes at ~10 s = ~5 min. 42 calls, ~20 min wall. GPU_MINUTES IS 0 AND THAT IS A FACT, NOT AN '
            'OPTIMISM: audio_mix.py is pure ffmpeg-as-a-subprocess and forbidden to touch CUDA (audio_mix.py:8-10), '
            'and audio_qc pins the shared Whisper loader to CPU (audio_qc.py:38-40), so this whole sheet can be '
            'scheduled while a GPU render owns the card. Operator: 2 blind questions (pump, duck) x 3 repeats = 6 '
            'decisions, plus the sighted failsafe question x 4 broken inputs = 4 decisions: 10 decisions at ~30 s = 5 min per mixing row; the gates row answers only the failsafe question (2 min). No claude_cli or anthropic_api row '
            'exists on this step, so nothing here spends the shared Claude week. One-time operator cost OUTSIDE '
            'this budget: verifying the narration render and the wrong-voice pair (~20 min), until which wpm, '
            'sfx_seat, silence and wrong_voice are BLOCKED.'
        ),
    },
    'notes': [
        'The `order` column is the reason this test exists in this shape. Everything else on the sheet can be read off a meter; chain order can only be read off a fixture that provokes it.',
        'chain and loudnorm are expected to score NO on wrong_voice. The sheet already says so in its own note; the probe turns that claim into a measured cell instead of an assertion.',
        'The gates row mixes nothing, so nine columns are na on it with the reason. A failing delivery number therefore lands on the row that produced the audio, not on the meter that reported it.',
        "lra, pump, scene spread and the 100 ms silence tolerance are the TEST's standard, not the pipeline's. If the house adopts different values, change them in HOUSE and bump the version — a different threshold is a different test.",
    ],
}
