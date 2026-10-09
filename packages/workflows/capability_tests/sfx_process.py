# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — SFX processing & effects rack (sfx_process). 2026-09-30.

Question the sheet asks: can we shape a recorded sound into the one the scene needs?

Nothing on this step is a model. Every row is a deterministic house DSP service driven by a
PARAMETER SET, not a prompt, and every measurement below is an ffmpeg/numpy reading of the
output waveform against the input waveform. That is the whole reason this sheet can be honest
where a generator sheet cannot: "did the 3 dB cut at 200 Hz land" has a number, and the number
does not need a judge.

    fx_rack   sfx_fx.py — 63 effects. Filter effects batch into ONE ffmpeg `-af` pass; render
              effects (convolution, doppler, pitch) each get their own pass. _SR = 48000.
    merger    sfx_merger.py — stem -> mix -> save. Delays are `adelay` in SAMPLES, the sum is
              `amix` with normalize=0, and the result is peak-scaled ONCE if it clipped. The
              merged asset carries the STRICTEST source licence plus its `merge_recipe`.
    ir        sfx_fx.py `_IR_CHARS` = room, hall, plate, chamber, spring, cave. The impulse
              responses are SYNTHESISED (noise x a decay curve), not sampled rooms — which is
              exactly what `reverb` has to find out.

Why the Makes and Prompt bands are `na` here
--------------------------------------------
A rack does not MAKE a footstep; it takes one and puts it in a corridor. The five Makes bands
are therefore `na` with a written reason — EXCEPT the three that are literally rack effects:
make_distance (gain + low-pass + reverb send), make_reverb_space (convolution) and
make_off_screen (pan + distance). Those three keep the bank's own blind operator question, so
a rack row and a generator row stay comparable on the same column.

All four Prompt bands are `na` for the same reason the subtitles step gives: the input is a
parameter dict. The bank already wrote that exemption for `pd_tag_vocab` under
transport_na['service'] and left the rest of the band to the step module; this is the step
module doing it. `pd_recorded` is the exception and is DERIVED — the merger really does store
its `merge_recipe` on the asset, so "were the settings recorded with the output" is answerable.

Honest judging
--------------
Every domain column has a MECHANICAL detector first (the defect-judge bench of 2026-09-27 says
no local model may be asked "is this right": best model 34/40 on a global question, 2/8 on the
hard cases). Where the mechanical number cannot hear smearing or pumping, a BLIND operator
check is added alongside it and BOTH numbers stay on the trial. Where they disagree the
operator decides and the disagreement is written into the note.
"""

from __future__ import annotations

FX = 'capability_tests/fixtures/audio'
PR = FX + '/process'

# The eleven effect families the sheet asks about, in the order of the domain columns. `breadth`
# is a COUNT of this list against what the rack enumerates — a lookup, not a trial.
NEED = [
    'eq',
    'compressor',
    'limiter',
    'reverb',
    'delay',
    'pitch_shift',
    'time_stretch',
    'distortion',
    'denoise',
    'stereo_width',
    'doppler',
]
IR_CHARS = ['room', 'hall', 'plate', 'chamber', 'spring', 'cave']

# ── check kinds this module adds (the runner is a table of these) ──────────────────────
CHECK_KINDS = {
    'null_test_residual_db_max': 'process the fixture with the IDENTITY parameter set, subtract the output from the input sample-for-sample after removing any constant latency, and require the residual peak <= `max` dBFS',
    'artefact_absent': 'the mechanical artefact detectors all clear: no sample-to-sample step > `click_delta`, no run of >= `dropout_ms` of digital silence inside a sounding region, no energy above `alias_hz` that was not in the input',
    'eq_response': 'measured third-octave energy change at each `bands` centre frequency is within `tolerance_db` of the gain that band was asked for, and every band NOT asked for moves < `leak_db`',
    'gain_curve': 'for each (input_db, expected_out_db) pair in `points`, measured output level is within `tolerance_db`; the implied ratio above the knee is within `ratio_tolerance` of the ratio asked for',
    'rt60_range': 'measured RT60 of the decay (Schroeder backward integration, -5 to -35 dB, extrapolated) is inside `min`..`max` seconds for the space named in the trial',
    'delay_time_ms': 'lag of the first correlation peak after the direct sound is within `tolerance_ms` of the delay asked for, and the repeat count matches `repeats_expected`',
    'pitch_shift_accuracy': 'measured f0 ratio (YIN on a steady tone) is within `cents` of the requested semitone shift, and output duration is within `duration_tolerance` of the input',
    'duration_ratio': 'output duration / input duration is within `tolerance` of the requested stretch factor',
    'pitch_preserved': 'measured f0 after the operation is within `cents` of the f0 before it',
    'thd_monotonic': 'total harmonic distortion measured on the 1 kHz tone rises monotonically across the `drive` settings in order and reaches >= `min_top` per cent at the highest',
    'snr_improvement_db_min': 'A-weighted noise floor of the silent region drops by >= `min` dB while the RMS of the sounding region changes by < `signal_tolerance_db`',
    'stereo_width_ratio': 'measured side/mid energy ratio moves monotonically with the `width` settings in order, and the mono sum loses < `mono_loss_db` dB against the width=1.0 mono sum',
    'doppler_shift_hz': 'measured f0 across the pass-by rises then falls, the peak-to-trough spread is >= `min_hz`, and the crossing is within `crossing_tolerance` s of the midpoint',
    'no_clip_in_chain': 'the peak sample of EVERY intermediate stage and of the final output is <= `max_dbfs`, and no sample is at full scale for >= `flat_samples` consecutive samples',
    'param_follows_automation': 'the measured parameter envelope tracks the automation breakpoints within `tolerance` of the asked value at each breakpoint time +/- `time_tolerance` s',
    'source_unchanged': 'the sha256 of every input file is identical before and after the operation, and no file under the input directory has a changed mtime',
    'preset_roundtrip': 'the parameter dict read back after save + load equals the dict saved, key for key, with floats equal to `places` decimal places',
    'effect_list_covers': 'the enumerated effect list the row exposes contains an entry for every name in `need`; the column is the share covered',
}


def _p(pid, title, feeds, checks, inputs, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': dict(inputs),
        'conditions': {
            'seed': None,
            'repeats': 3,
            'sample_rate': 48000,
            'channels': 1,
            'format': 'pcm_s24le',
            'note': 'a DSP pass has no seed. The three repeats exist to catch a rack that is NOT deterministic; on a correct rack they are byte-identical and `deterministic` reads them.',
        },
        'checks': list(checks),
        'grade': 'measured',
    }
    p.update(kw)
    return p


PROBES = [
    # ── The rack (11 probes; `breadth` is a lookup) ────────────────────────────────────
    _p(
        'd_quality',
        'No audible artefacts',
        ['quality'],
        [
            {'check': 'null_test_residual_db_max', 'max': -90.0},
            {'check': 'artefact_absent', 'click_delta': 0.25, 'dropout_ms': 2.0, 'alias_hz': 20000},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Played against the untouched original, does this processed version add any click, crackle, dropout or metallic ring that was not there before? Answer yes if it is CLEAN.',
            },
        ],
        {
            'fixture': PR + '/footsteps_dry.wav',
            'task': (
                'TWO parts. (1) the null test: run the row with its identity parameter set '
                '(fx_rack: gain 0 dB; merger: one stem, offset 0, gain 0 dB; ir: dry/wet = 0) and '
                'subtract the output from the input. (2) the working test: run the row at its '
                'ordinary settings (fx_rack: eq -3 dB @ 200 Hz; merger: three stems; ir: room at '
                '30 % wet) and run the artefact detectors on the result, then play it blind.'
            ),
            'params': {'identity': {'gain_db': 0.0}, 'working': {'eq_200_db': -3.0, 'wet': 0.30}},
        },
        state_note=(
            'a rack whose identity path is not bit-transparent is rewriting audio it was not '
            'asked to touch, which is why the null test comes first and is mechanical. -90 dBFS '
            'is one bit of 16-bit dither; a 24-bit float chain should be far below it. The blind '
            'listen is the second opinion and cannot be skipped because no detector hears pumping.'
        ),
    ),
    _p(
        'd_eq',
        'EQ',
        ['eq'],
        [
            {
                'check': 'eq_response',
                'bands': [{'hz': 100, 'gain_db': 6.0}, {'hz': 1000, 'gain_db': -6.0}, {'hz': 8000, 'gain_db': 3.0}],
                'tolerance_db': 1.0,
                'leak_db': 1.5,
            }
        ],
        {
            'fixture': PR + '/sweep.wav',
            'task': 'Apply the three-band setting below to the log sweep and measure the third-octave transfer function of output against input.',
            'params': {
                'bands': [
                    {'hz': 100, 'q': 1.0, 'gain_db': 6.0},
                    {'hz': 1000, 'q': 1.0, 'gain_db': -6.0},
                    {'hz': 8000, 'q': 1.0, 'gain_db': 3.0},
                ]
            },
        },
        state_note='three bands, each pass/fail on its own tolerance, plus the leak test on the untouched bands; the column is the share of the four that passed. A rack with no parametric EQ at all is a `no`, not an exemption.',
    ),
    _p(
        'd_comp',
        'Compression and limiting',
        ['comp'],
        [
            {
                'check': 'gain_curve',
                'points': [
                    {'input_db': -30.0, 'expected_out_db': -30.0},
                    {'input_db': -12.0, 'expected_out_db': -16.0},
                    {'input_db': -3.0, 'expected_out_db': -11.5},
                ],
                'tolerance_db': 1.5,
                'ratio_tolerance': 0.5,
            },
            {
                'check': 'no_clip_in_chain',
                'max_dbfs': -1.0,
                'flat_samples': 3,
                'note': 'the limiter leg: the same source pushed 12 dB hot must come out under -1 dBFS without a flat top',
            },
        ],
        {
            'fixture': PR + '/tone_steps.wav',
            'task': 'Compress the six-step tone at the setting below, measure the output level of each step, then repeat with the source raised 12 dB to test the limiter.',
            'params': {
                'threshold_db': -20.0,
                'ratio': 4.0,
                'attack_ms': 10.0,
                'release_ms': 100.0,
                'makeup_db': 0.0,
                'limiter_ceiling_db': -1.0,
            },
        },
        state_note='the three points are below, at and above the knee: a compressor that does not move the -30 dB step has a working threshold, and one that moves it does not. Ratio is read from the two upper points, not taken on trust.',
    ),
    _p(
        'd_reverb',
        'Reverb and impulse responses',
        ['reverb'],
        [
            {
                'check': 'rt60_range',
                'spaces': {
                    'room': [0.3, 0.8],
                    'hall': [1.2, 2.5],
                    'plate': [1.0, 2.0],
                    'chamber': [0.8, 1.6],
                    'spring': [1.5, 3.0],
                    'cave': [2.5, 6.0],
                },
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this sound like a real space of the size it claims — a {space} — rather than a wash of noise on top of the sound? yes/no',
            },
        ],
        {
            'fixture': PR + '/impulse.wav',
            'task': 'Convolve the unit impulse with each of the six IR characters, measure RT60 on each, then convolve the dry footstep with each and play those six blind.',
            'params': {'spaces': IR_CHARS, 'wet': 1.0, 'second_fixture': PR + '/footsteps_dry.wav'},
        },
        state_note=(
            'six spaces, each pass/fail on RT60 AND on the blind listen; the column is the share of '
            'the six that passed both. The IRs are SYNTHESISED from noise and a decay curve, so the '
            'RT60 will very likely be right and the listen is where a synthetic plate is caught. '
            'That is the finding this probe exists to produce, not a failure of the measurement.'
        ),
    ),
    _p(
        'd_delay',
        'Delay and echo',
        ['delay'],
        [
            {'check': 'delay_time_ms', 'ms': 250.0, 'tolerance_ms': 2.0, 'repeats_expected': 4},
            {
                'check': 'null_test_residual_db_max',
                'max': -60.0,
                'note': 'feedback 0, mix 100 % wet: the single repeat must be the input again, delayed — a delay line that colours the repeat is not a delay',
            },
        ],
        {
            'fixture': PR + '/impulse.wav',
            'task': 'Set a 250 ms delay with 50 % feedback and 100 % wet, count the repeats above -40 dBFS and measure the lag of the first one; then re-run with feedback 0 for the null test.',
            'params': {'delay_ms': 250.0, 'feedback': 0.5, 'wet': 1.0},
        },
        state_note='2 ms is 96 samples at 48 kHz — a delay implemented in samples (as sfx_merger does for its offsets) should be exact, and a drift larger than this means the time is being computed in a different rate.',
    ),
    _p(
        'd_pitch',
        'Pitch shift without smearing',
        ['pitch'],
        [
            {'check': 'pitch_shift_accuracy', 'semitones': [-5, -2, 2, 5, 12], 'cents': 10, 'duration_tolerance': 0.01},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this the same sound at a different pitch, with no warbling, no metallic edge and no smearing of its attack? yes/no',
            },
        ],
        {
            'fixture': PR + '/footsteps_dry.wav',
            'task': 'Shift the dry footsteps by each of the five intervals with the LENGTH held; measure f0 on the tone fixture at the same settings and play the footsteps blind.',
            'params': {'semitones': [-5, -2, 2, 5, 12], 'preserve_length': True, 'tone_fixture': PR + '/tone_1k.wav'},
        },
        state_note='10 cents is a tenth of a semitone — inaudible, and well inside what a correct phase-vocoder does. The blind listen is what catches the smearing the ratio cannot see; a transient-heavy source (footsteps) is used on purpose.',
    ),
    _p(
        'd_time',
        'Time stretch without smearing',
        ['time'],
        [
            {'check': 'duration_ratio', 'factors': [0.5, 0.75, 1.5, 2.0], 'tolerance': 0.01},
            {'check': 'pitch_preserved', 'cents': 15},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this the same sound at a different length, with its attacks still sharp and no flanging or doubling? yes/no',
            },
        ],
        {
            'fixture': PR + '/footsteps_dry.wav',
            'task': 'Stretch by each of the four factors with the PITCH held; measure the output duration and the f0 of the tone fixture at the same settings, then play the footsteps blind.',
            'params': {'factors': [0.5, 0.75, 1.5, 2.0], 'preserve_pitch': True, 'tone_fixture': PR + '/tone_1k.wav'},
        },
        state_note="the mirror of d_pitch: length changes, pitch must not. A stretch that moves the pitch is a resample wearing a stretch's name, and the two mechanical checks together say which one the rack implements.",
    ),
    _p(
        'd_distort',
        'Distortion and saturation',
        ['distort'],
        [
            {'check': 'thd_monotonic', 'drive': [0.0, 0.25, 0.5, 0.75, 1.0], 'min_top': 5.0},
            {
                'check': 'no_clip_in_chain',
                'max_dbfs': -0.1,
                'flat_samples': 3,
                'note': 'saturation that arrives as hard digital clipping is a different effect; a flat top of 3 samples is the signature',
            },
        ],
        {
            'fixture': PR + '/tone_1k.wav',
            'task': 'Drive the 1 kHz tone at each of the five settings, measure THD on each, and check the peaks.',
            'params': {'drive': [0.0, 0.25, 0.5, 0.75, 1.0], 'output_db': -6.0},
        },
        state_note='drive 0 must measure essentially the clean tone; the column is whether THD rises in order and actually arrives somewhere (>= 5 %) at full drive. A "distortion" whose only mechanism is clipping fails the second check and the note says so.',
    ),
    _p(
        'd_denoise',
        'Noise reduction',
        ['denoise'],
        [
            {'check': 'snr_improvement_db_min', 'min': 10.0, 'signal_tolerance_db': 1.5},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is the hiss gone WITHOUT the sound itself turning watery, hollow or chirpy? yes/no',
            },
        ],
        {
            'fixture': PR + '/noisy_dialogue.wav',
            'task': "Run the row's noise reduction with the noise profile taken from the first 1.0 s (which is noise only), measure the floor in that region and the RMS of the speech, then play it blind.",
            'params': {'profile_start_s': 0.0, 'profile_end_s': 1.0, 'reduction_db': 12.0},
        },
        state_note='10 dB of floor with the signal within 1.5 dB is a real reduction; a gate that simply mutes the quiet part passes the number and fails the listen, which is precisely why both are here.',
    ),
    _p(
        'd_stereo',
        'Stereo field control',
        ['stereo'],
        [{'check': 'stereo_width_ratio', 'width': [0.0, 0.5, 1.0, 1.5, 2.0], 'mono_loss_db': 3.0}],
        {
            'fixture': PR + '/stereo_ambience.wav',
            'task': 'Set each of the five widths, measure the side/mid energy ratio of each output and the level of each mono sum.',
            'params': {'width': [0.0, 0.5, 1.0, 1.5, 2.0]},
            'conditions_override': {'channels': 2},
        },
        cond={
            'seed': None,
            'repeats': 3,
            'sample_rate': 48000,
            'channels': 2,
            'format': 'pcm_s24le',
            'note': 'the only stereo probe on this step; width has no meaning on a mono file',
        },
        state_note='width 0 must collapse to mono (side energy at the noise floor) and width 2 must widen it; the mono_loss check is the phase trap — a width control built on polarity inversion looks wide and disappears the moment anything sums to mono.',
    ),
    _p(
        'd_doppler',
        'Movement and doppler',
        ['doppler'],
        [
            {'check': 'doppler_shift_hz', 'min_hz': 40.0, 'crossing_tolerance': 0.3},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this sound like something moving past you — approaching, passing, going away — rather than a sound whose volume is being turned up and down? yes/no',
            },
        ],
        {
            'fixture': PR + '/tone_1k.wav',
            'task': 'Run the pass-by below on the tone, track f0 over time; then run the same pass-by on the horse hooves and play it blind.',
            'params': {
                'speed_ms': 20.0,
                'distance_m': 5.0,
                'duration_s': 4.0,
                'second_fixture': PR + '/hooves_dry.wav',
            },
        },
        state_note='20 m/s past a 1 kHz tone is about +/- 60 Hz, so a 40 Hz spread is a real shift and not tracker noise. The blind listen is the honest half: a gain ramp with no pitch movement is the common fake and the operator hears it instantly.',
    ),
    # ── Control (4) ───────────────────────────────────────────────────────────────────
    _p(
        'd_chain',
        'Chains without gain staging errors',
        ['chain'],
        [
            {'check': 'no_clip_in_chain', 'max_dbfs': -1.0, 'flat_samples': 3},
            {'check': 'artefact_absent', 'click_delta': 0.25, 'dropout_ms': 2.0, 'alias_hz': 20000},
        ],
        {
            'fixture': PR + '/hot_source.wav',
            'task': (
                'Run the three-effect chain below IN ORDER on a source that already peaks at -1 dBFS, '
                'keeping every intermediate buffer, and measure the peak of each stage and of the '
                'output. For the merger row the chain is instead: eight stems summed, then the '
                'merge, then the save.'
            ),
            'params': {
                'chain': [
                    {'effect': 'eq', 'hz': 100, 'gain_db': 6.0},
                    {'effect': 'compressor', 'threshold_db': -20.0, 'ratio': 4.0, 'makeup_db': 6.0},
                    {'effect': 'reverb', 'space': 'hall', 'wet': 0.3},
                ],
                'merger_stems': PR + '/layers/',
            },
        },
        state_note=(
            'every stage of this chain adds level on purpose — +6 dB of bass, +6 dB of makeup, then a '
            'wet tail — so a rack that does not manage gain WILL clip here. That is the point: the '
            'trial is built to fail an unstaged chain. sfx_merger scales the sum once if it clipped, '
            'so the merger row is expected to pass and the finding would be whether it scales EVERY '
            'time or only when the final sum clips.'
        ),
    ),
    _p(
        'd_automation',
        'Parameters can be automated',
        ['automation'],
        [
            {'check': 'param_follows_automation', 'tolerance': 1.0, 'time_tolerance': 0.05},
            {
                'check': 'artefact_absent',
                'click_delta': 0.15,
                'dropout_ms': 2.0,
                'alias_hz': 20000,
                'note': 'a parameter stepped rather than ramped clicks at every breakpoint; the tighter delta is deliberate',
            },
        ],
        {
            'fixture': PR + '/tone_1k.wav',
            'task': 'Automate the gain along the four breakpoints below over the 4 s tone and measure the output envelope at each breakpoint time.',
            'params': {
                'automate': 'gain_db',
                'breakpoints': [
                    {'t': 0.0, 'v': 0.0},
                    {'t': 1.0, 'v': -12.0},
                    {'t': 2.5, 'v': -12.0},
                    {'t': 4.0, 'v': 0.0},
                ],
            },
        },
        state_note='gain is used because its envelope can be measured directly and the click test is unambiguous. A row that offers NO automation at all is a `no` with "parameter is fixed for the whole pass" in the note — not an exemption, because the sheet is asking whether we can automate it.',
    ),
    _p(
        'd_undo',
        'Non-destructive',
        ['undo'],
        [
            {'check': 'source_unchanged'},
            {
                'check': 'file_exists',
                'path': 'output/capabilities/sfx_process/undo/out.wav',
                'note': 'the result must be written somewhere NEW — a row that writes nothing is not non-destructive, it is broken',
            },
        ],
        {
            'fixture': PR + '/footsteps_dry.wav',
            'task': 'Record the sha256 and mtime of every file under the fixture directory, run the row at its ordinary settings, then record them again.',
            'params': {'settings': 'the `working` set of d_quality'},
        },
        state_note='mechanical and total: one changed digest anywhere under the input directory is a `no`. There is no operator half because there is nothing here to hear.',
    ),
    _p(
        'd_preset',
        'Presets are reusable',
        ['preset'],
        [
            {'check': 'preset_roundtrip', 'places': 6},
            {
                'check': 'identical_runs',
                'note': 'the output produced from the LOADED preset must be byte-identical to the output produced from the parameters directly — equal numbers that give a different sound are not a preset',
            },
        ],
        {
            'fixture': PR + '/footsteps_dry.wav',
            'task': 'Save the three-effect chain of d_chain as a preset, load it back in a FRESH process, compare the parameter dicts key for key, and render from both.',
            'params': {'chain': 'the `chain` of d_chain', 'fresh_process': True},
        },
        state_note='the fresh process matters: a preset that only round-trips inside the process that made it is an in-memory copy. For the merger row the preset under test is the `merge_recipe` the merged asset already carries.',
    ),
    # ── the three Makes columns a rack really does answer ──────────────────────────────
    _p(
        'make_distance',
        'Makes the same sound near and far',
        ['make_distance'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Are these two takes the same sound at two different distances from you? yes/no',
            },
            {
                'check': 'eq_response',
                'bands': [{'hz': 8000, 'gain_db': -8.0}],
                'tolerance_db': 4.0,
                'leak_db': 99.0,
                'note': 'the far take must actually lose top end; the wide tolerance is because the amount is a judgement, the DIRECTION is not',
            },
        ],
        {
            'fixture': PR + '/hooves_dry.wav',
            'task': "Produce a NEAR and a FAR version of the same source with the row's distance setting and present the pair blind.",
            'params': {'near': {'distance_m': 2.0}, 'far': {'distance_m': 40.0}},
        },
        state_note="the bank's question, word for word, on a rack transport. The mechanical half only asserts the direction of the air absorption, because how much is a creative decision and the operator owns it.",
    ),
    _p(
        'make_reverb_space',
        'Makes a believable room around the sound',
        ['make_reverb_space'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this sound in a real room, and is it the room it says it is? yes/no',
            },
            {'check': 'rt60_range', 'spaces': {'room': [0.3, 0.8], 'hall': [1.2, 2.5], 'cave': [2.5, 6.0]}},
        ],
        {
            'fixture': PR + '/footsteps_dry.wav',
            'task': 'Place the dry footsteps in room, hall and cave at 30 % wet and present the three blind, each labelled with the room it claims.',
            'params': {'spaces': ['room', 'hall', 'cave'], 'wet': 0.30},
        },
        state_note='three spaces, each pass/fail on both halves. This is the same evidence as d_reverb read for a different question — d_reverb asks whether the reverb is correct, this asks whether the result is believable — so the trials are shared and both columns name them.',
    ),
    _p(
        'make_off_screen',
        'Makes a sound from off screen',
        ['make_off_screen'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this sound coming from outside the frame — off to one side, or through a wall — rather than in front of you? yes/no',
            },
            {
                'check': 'stereo_width_ratio',
                'width': [1.0],
                'mono_loss_db': 3.0,
                'note': 'whatever the off-screen placement does, it must survive a mono fold-down: a cinema mix is checked in mono',
            },
        ],
        {
            'fixture': PR + '/footsteps_dry.wav',
            'task': "Place the source hard left and behind a wall using the row's pan + distance + damping settings, and present both blind.",
            'params': {
                'side': {'pan': -0.9, 'distance_m': 8.0},
                'through_wall': {'pan': 0.0, 'distance_m': 8.0, 'lowpass_hz': 900},
            },
        },
        cond={
            'seed': None,
            'repeats': 3,
            'sample_rate': 48000,
            'channels': 2,
            'format': 'pcm_s24le',
            'note': 'stereo, because off-screen is a placement and a mono file has no sides',
        },
        state_note='two placements, each pass/fail on the blind question; the mono check is the one mechanical thing that can be asserted about a placement and it catches the polarity trick.',
    ),
    # ── the one universal column this step must own (see notes) ────────────────────────
    _p(
        'd_failsafe',
        'Fails without breaking the caller',
        ['failsafe'],
        [
            {
                'check': 'operator',
                'blind': False,
                'question': 'Did the call return a value or raise a catchable exception, leaving the process alive and no half-written file on disk, within 30 s? yes/no',
            },
            {
                'check': 'file_absent',
                'path': 'output/capabilities/sfx_process/failsafe/partial.wav',
                'note': 'a half-written render left behind is a fail — the next stage would pick it up as finished work',
            },
        ],
        {
            'task': (
                'call the row on a DELIBERATELY broken input three ways and record what came back: (1) the '
                'effect name is a string the rack does not have ("fx_nonesuch"); (2) the input is '
                "capability_tests/fixtures/audio/judge/truncated.wav (the bank's WAV whose header claims "
                '40 s over 0.2 s of data); (3) a parameter is out of range (ratio = -1, wet = 3.0)'
            ),
            'fixture': FX + '/judge/truncated.wav',
        },
        state_note=(
            "the bank's u_failsafe, restated here because its input is declared under a key the "
            'validator does not accept (see notes). All three calls must come back: yes = each '
            'returned or raised something the caller can catch and the process is still up; no = any '
            'hang past 120 s, any crash of the calling process, or a partial file left on disk. '
            'SIGHTED, not blind — it is about the process, not the sound. Expected by code read but '
            'not assumed: sfx_fx.render raises ValueError for a slot type it cannot render.'
        ),
    ),
]

# ── whole bands this step cannot answer ────────────────────────────────────────────────
NA_MAKES = {
    'reason': (
        'a processing rack does not MAKE a sound; it takes a recording and shapes it. Asking '
        'whether sfx_fx.py can produce a dog bark measures the library or the generator that '
        'supplied the bark, not the rack, and would put the same evidence on two sheets. The '
        'three Makes columns that ARE rack effects — make_distance, make_reverb_space, '
        "make_off_screen — are measured above with the bank's own blind questions."
    ),
    'bands': [
        'Makes: Human & movement',
        'Makes: Objects & work',
        'Makes: Nature & weather',
        'Makes: Animals',
        'Makes: Space & ambience',
    ],
}
# The four prompt bands, written out as the permanent column ids they hold. The loader takes ONE
# `na_bands` dict per level and that one is spent on the Makes bands above, so these are listed
# rather than expanded — which is the more honest form anyway: the reason below is asserted of
# each of these 53 columns by name. `pd_recorded` is deliberately absent: it is derived.
PROMPT_COLS = (
    'pd_damage',
    'pd_paraphrase',
    'pd_word_order',
    'pd_synonym',
    'pd_typo',
    'pd_grammar',
    'pd_punctuation',
    'pd_case',
    'pd_filler',
    'pd_repetition',
    'pd_contradiction',
    'pd_negation',
    'pd_unstated',
    'pd_bleed',
    'pd_leak',
    'pd_meta_literal',
    'pd_damage_visible',
    'pd_text_vs_style',
    'pd_spelling_sound',
    'pd_punct_timing',
    'pd_clarity_floor',
    'pd_terse_ok',
    'pd_detail_helps',
    'pd_sweet_spot',
    'pd_prose_ok',
    'pd_structure_needed',
    'pd_example_needed',
    'pd_house_template',
    'pd_jargon_needed',
    'pd_asks_back',
    'pd_tag_vocab',
    'pd_max_hard',
    'pd_max_soft',
    'pd_max_words',
    'pd_truncation_loud',
    'pd_min_len',
    'pd_unique_things',
    'pd_unique_subjects',
    'pd_attrs_per_thing',
    'pd_instructions',
    'pd_constraints',
    'pd_order_wins',
    'pd_negative_len',
    'pd_weight_range',
    'pd_multilingual',
    'pd_small_edit',
    'pd_seed_vs_prompt',
    'pd_fix_lands',
    'pd_fix_breaks',
    'pd_reusable',
    'pd_portable',
    'pd_retries',
    'pd_direction_words',
)
NA_PROMPT = {
    'reason': (
        'none of these rows takes a prompt. The input is a parameter dict — gain in dB, a '
        'frequency in Hz, a list of stems with offsets in samples — so there is no wording to '
        'damage, no clarity floor to find and no length limit to hit. The shared bank already '
        'wrote this exemption for pd_tag_vocab under transport_na["service"] and left the rest '
        'of the band to the step module; this is that. pd_recorded is the exception and is '
        'derived from the merge_recipe the merger stores on the asset.'
    ),
    'bands': ['Prompt: damage', 'Prompt: clarity needed', 'Prompt: limits', 'Prompt: steering'],
}

NA_ACAP = {
    'acap_words': 'nothing here is spoken or sung; a rack processes whatever it is handed, including silence, and a word count is not a property it has',
    'acap_voices': 'the rack does not place voices in a scene — it processes one buffer at a time, and how many voices are in that buffer was decided upstream',
    'acap_instruments': 'no instrument is ever synthesised on this step; separating instruments is a property of the source material, not of the effect applied to it',
    'acap_variations': 'a deterministic DSP pass makes exactly one output for one parameter set, so "variations before they repeat" is unity by construction and measuring it would report the definition back',
}

_RACK = ['eq', 'comp', 'delay', 'pitch', 'time', 'distort', 'denoise', 'stereo', 'doppler']

NA_MERGER = dict(
    {
        c: 'the merger sums stems; it applies no tonal or time processing of its own, so this effect is measured on the fx_rack row where it lives'
        for c in _RACK
    },
    breadth='the merger is one operation, not a rack with an effect list; counting its effects against the eleven asked would report zero and mean nothing',
    reverb='the merger applies no reverb; the house reverb is the ir row',
    automation='the merger takes one static offset and one static gain per stem and runs once — there is no parameter to move over time',
    make_distance='placing a sound at a distance is a rack effect (gain + air absorption + send); the merger only sums what it is given',
    make_reverb_space='the merger applies no reverb, so it cannot put a sound in a room',
    make_off_screen='off-screen placement is pan + distance + damping, none of which the merger does',
)
NA_IR = dict(
    {
        c: 'the IR bank is a convolution space, not an effect rack; this effect is measured on the fx_rack row'
        for c in _RACK
    },
    chain='an impulse response is one convolution — there is no chain of stages inside it to stage the gain of; chains are measured on fx_rack and merger',
    automation='an impulse response is a fixed filter for the length of the pass; moving it mid-render is not something convolution offers',
    preset='the six characters ARE the preset list and there is no save/load surface to round-trip; preset is measured on the fx_rack and merger rows',
    make_distance='distance is gain and air absorption, applied before the send; the IR bank only supplies the room',
    make_off_screen='off-screen placement is a pan, which convolution with a mono IR does not perform',
)
NA_FX_RACK = {}

TEST = {
    'step': 'sfx_process',
    'version': '2026-09-30.1',
    'title': 'Sixteen waveform measurements of the house DSP rack, the merger and the IR bank',
    'purpose': (
        'Measure what the rack DOES to a known signal: the level a compressor returns for a '
        'known input, the RT60 of each synthesised space, the f0 a pitch shift lands on, the '
        'peak a three-effect chain reaches on a source that is already hot. Nothing here needs '
        'a judge, and the two places where a number cannot hear the defect — smearing and '
        'pumping — carry a blind operator check beside the number.'
    ),
    'include_shared': 'audio',
    'house_standard': "48 kHz, 24-bit, mono unless the probe says stereo; sfx_fx._SR = 48000 is the rack's own rate and every fixture is generated at it so nothing resamples on the way in",
    'effects_asked': NEED,
    'ir_chars': IR_CHARS,
    'rows': {
        'fx_rack': {
            'transport': 'service',
            'where': 'sfx_fx.py — 63 effects; filter effects batch into one ffmpeg `-af` pass, render effects (convolution, doppler, pitch) each get their own pass; _SR = 48000',
            'na': NA_FX_RACK,
        },
        'merger': {
            'transport': 'service',
            'where': 'sfx_merger.py — stem -> mix -> save; offsets are `adelay` in SAMPLES, the sum is `amix` with normalize=0, peak-scaled once if it clipped; the merged asset carries the strictest source licence plus its `merge_recipe`',
            'na': NA_MERGER,
            'budget': {
                'calls': 34,
                'minutes': 5,
                'operator_minutes': 6,
                'note': 'five domain probes only (quality, chain, undo, preset, and the shared capacity ladder) at 3 repeats over the eight-stem fixture set, plus the failsafe trio; no sweep, no IR convolution and no f0 tracking are paid on this row',
            },
        },
        'ir': {
            'transport': 'service',
            'where': 'sfx_fx.py `_IR_CHARS` = room, hall, plate, chamber, spring, cave — the impulse responses are SYNTHESISED (noise x a decay curve), not sampled rooms',
            'na': NA_IR,
            'budget': {
                'calls': 48,
                'minutes': 7,
                'operator_minutes': 9,
                'note': 'six spaces x (impulse + footstep) x 3 repeats for d_reverb, three spaces x 3 for make_reverb_space, plus quality, undo and the failsafe trio; convolution of a 4 s file with a 6 s cave tail is the slowest call on the step at ~1.5 s',
            },
        },
    },
    'na_bands': NA_MAKES,
    'probes': PROBES,
    'derive': {
        'deterministic': {
            'from': [
                'probe.d_quality.repeat_1',
                'probe.d_quality.repeat_2',
                'probe.d_quality.repeat_3',
                'probe.d_chain.repeat_1',
                'probe.d_chain.repeat_2',
                'probe.d_chain.repeat_3',
            ],
            'rule': 'yes only if all three repeats of BOTH probes are byte-identical (sha256 of the output file); partial if the samples are identical but a container timestamp differs; no otherwise',
            'grade': 'measured',
            'note': (
                'the sheet already records `yes` for fx_rack with the reason "parameterised ffmpeg/DSP '
                'chains — reproducible by construction". That is a reading of the code, not a '
                'measurement, and it is wrong often enough to be worth checking: an ffmpeg build with '
                'a dithered resampler, or a reverb seeded from time, breaks it. This derive replaces '
                'the assumption with the three repeats every probe already runs.'
            ),
        },
        'pd_recorded': {
            'from': ['probe.d_preset.parameters', 'artifact.merge_recipe'],
            'rule': 'yes if the parameter set that produced the output is stored WITH the output and a fresh process can reproduce the output from it alone; partial if it is stored but incomplete (a field had to be supplied by hand); no if nothing is stored',
            'grade': 'measured',
            'note': (
                'the rack takes no prompt, but the question underneath pd_recorded — "can you tell, '
                'later, what settings made this file" — is exactly answerable here. sfx_merger already '
                'writes `merge_recipe` onto the merged asset, so the merger row is expected to answer '
                'yes and the fx_rack and ir rows are the open question.'
            ),
        },
    },
    'lookup': {
        'breadth': {
            'source': "sfx_fx.py — the module's own effect table, read at the revision recorded in the trial",
            'requires': [
                'the effect table as it stands in the working tree on the day of the run, quoted verbatim into the trial',
                'the git revision or sha256 of sfx_fx.py at that moment',
                "the eleven names in `effects_asked`, matched to the rack's names by the operator once and the mapping stored on the trial",
            ],
            'rule': 'share of the eleven families in `effects_asked` for which the rack enumerates at least one effect: >= 0.8 yes, >= 0.4 partial, else no',
            'grade': 'receipt',
            'note': (
                'a count, not a trial: whether an effect EXISTS is read off the code, whether it WORKS '
                'is the eleven probes above. Graded receipt rather than vendor because the source is '
                "our own file at a pinned revision, not a vendor's claim. The sheet already says yes "
                'here ("a fixed catalogue of effect types across racks"); this pins it to a revision so '
                'the next reader knows which catalogue was counted.'
            ),
        },
    },
    'na': dict(NA_ACAP, **{c: NA_PROMPT['reason'] for c in PROMPT_COLS}),
    'fixtures': [
        {
            'path': PR + '/tone_1k.wav',
            'generated': 'ffmpeg -f lavfi -i "sine=frequency=1000:sample_rate=48000:duration=4" -af "volume=-12dB" -c:a pcm_s24le -ar 48000 -ac 1 tone_1k.wav',
        },
        {
            'path': PR + '/tone_steps.wav',
            'generated': 'six 1 s segments of a 1 kHz sine at -30, -24, -18, -12, -6 and -3 dBFS, concatenated: for each level, ffmpeg -f lavfi -i "sine=frequency=1000:sample_rate=48000:duration=1" -af "volume=<level>dB", then concat -c copy. 48 kHz / 24-bit / mono.',
        },
        {
            'path': PR + '/sweep.wav',
            'generated': 'ffmpeg -f lavfi -i "aevalsrc=0.25*sin(2*PI*20*exp(t/10*log(1000))*10/log(1000)):s=48000:d=10" -c:a pcm_s24le -ac 1 sweep.wav — a 20 Hz to 20 kHz logarithmic sine sweep at -12 dBFS',
        },
        {
            'path': PR + '/impulse.wav',
            'generated': 'a single full-scale sample followed by 6.0 s of digital silence at 48 kHz / 24-bit / mono: python -c "import wave,struct; ..." or ffmpeg -f lavfi -i "aevalsrc=eq(n\\,0):s=48000:d=6" -c:a pcm_s24le -ac 1 impulse.wav',
        },
        {
            'path': PR + '/footsteps_dry.wav',
            'generated': 'a straight copy of the house slate data/asset_libraries/sfx/<the footstep bed the operator names in the trial>, trimmed to its first 4.0 s and converted to 48 kHz / 24-bit / mono with ffmpeg -ar 48000 -ac 1 -c:a pcm_s24le. It is a house CC0 sfx bed, so it may be copied into the fixture set.',
        },
        {
            'path': PR + '/hooves_dry.wav',
            'generated': 'the same recipe as footsteps_dry.wav on the house horse-hooves slate; a long, repeating, transient-heavy source is wanted for the doppler and distance trials',
        },
        {
            'path': PR + '/noisy_dialogue.wav',
            'generated': 'capability_tests/fixtures/audio/judge/clean.wav with 1.0 s of the noise alone prefixed, then pink noise mixed in at -20 dB SNR: ffmpeg -i clean.wav -f lavfi -i "anoisesrc=color=pink:sample_rate=48000:amplitude=0.02" -filter_complex "[1]atrim=0:1[pre];[0][1]amix=inputs=2:normalize=0[mix];[pre][mix]concat=n=2:v=0:a=1" -c:a pcm_s24le -ac 1',
        },
        {
            'path': PR + '/stereo_ambience.wav',
            'generated': 'a straight copy of the house harbour ambience slate, 10 s, kept STEREO at 48 kHz / 24-bit — the one stereo fixture on this step, for d_stereo and make_off_screen',
        },
        {
            'path': PR + '/hot_source.wav',
            'generated': 'footsteps_dry.wav normalised so its peak sits at exactly -1.0 dBFS: ffmpeg -i footsteps_dry.wav -af "volume=<measured>dB" -c:a pcm_s24le. The chain trial needs a source with no headroom left.',
        },
        {
            'path': PR + '/layers/',
            'generated': "eight mono 48 kHz / 24-bit stems of 4 s each, copied from the house sfx library and named 01..08 — a footstep bed, a cloth rustle, a rope creak, a sail flap, a water lap, a gull, a wind bed and a distant bell. They are the merger's input for d_chain and for the shared capacity ladder.",
        },
    ],
    'fixtures_note': (
        'Every fixture is either a generated test signal or a copy of a house CC0 sfx slate. '
        'NONE of them is an answer key, so nothing on this step is blocked pending '
        'verification: what the right answer is, is arithmetic on the waveform, not a '
        'judgement somebody has to make first. The runner generates them on its first run '
        'and records their sha256 on every trial, so a fixture that is later regenerated '
        'differently shows up as a different test rather than a changed result.'
    ),
    'budget': {
        'calls': 96,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'no language model is called anywhere on this step; every row is a local DSP service driven by a parameter dict, so there is no prompt and no completion to count',
        'minutes': 12,
        'gpu_minutes': 0,
        'operator_minutes': 18,
        'note': (
            '16 domain probes + 3 Makes probes + failsafe = 20 trial groups x 3 repeats = 60 calls, '
            'plus the multi-setting probes which are several calls each (d_reverb 6 spaces x 2 '
            'sources, d_pitch 5 intervals, d_time 4 factors, d_distort 5 drives, d_stereo 5 widths) '
            '= ~36 more, so 96. THE SHARED AUDIO BANK is cheap on this step because four of its five '
            'Makes bands and all four prompt bands are na: what is left is the capacity ladders and '
            'the universal probes, ~25 calls, counted inside the 96. A filter pass on a 4 s file is '
            '~0.3 s and the slowest call (cave convolution) is ~1.5 s, so 96 calls is ~3 min; fixture '
            "generation is ~2 min and the capacity ladder's long files ~7 min. gpu_minutes 0: "
            'ffmpeg and numpy on CPU, nothing on this step touches the GPU. OPERATOR: ~36 blind '
            'decisions (quality 3, reverb 6, pitch 5, time 4, denoise 3, doppler 3, and the three '
            'Makes probes at 8) x 30 s = 18 min.'
        ),
    },
    'run_order': [
        'undo',
        'quality',
        'breadth',
        'preset',
        'eq',
        'comp',
        'delay',
        'distort',
        'stereo',
        'chain',
        'automation',
        'pitch',
        'time',
        'denoise',
        'doppler',
        'reverb',
        'make_distance',
        'make_reverb_space',
        'make_off_screen',
        'failsafe',
        'shared bank',
    ],
    'notes': [
        'undo runs FIRST and on its own, before anything else has written to the fixture directory. If '
        'the row turns out to be destructive, every later probe would be reading a source the earlier '
        'probes had already altered, and the whole sheet would be measured against a moving input.',
        'The mechanical checks here are unusual for this project in that they really do decide the '
        'column. That is not a relaxation of the honest-judging rule, it is the rule applied: the rule '
        'forbids trusting a MODEL to say whether an output is right, and none of these checks is a '
        'model. Where the arithmetic provably cannot hear the defect — smearing after a pitch shift, '
        'pumping after compression, a gate pretending to be denoise — a blind operator check sits '
        'beside it and both results are written to the trial.',
        'd_reverb and make_reverb_space deliberately SHARE their trials. The first asks whether the '
        'decay is the length the space claims, the second whether the result sounds like a place. A '
        'synthesised IR can pass the first and fail the second, and that gap is the most likely real '
        'finding on this sheet, so the two columns are kept apart rather than merged.',
        "`failsafe` is owned here, not by the bank. The bank's u_failsafe declares its input under a "
        'key the validator does not count as a fixed input, so merging it produces "probe u_failsafe: '
        'no fixed input". The local d_failsafe is that probe restated with the input under `task` + '
        "`fixture`, and with the rack's own broken inputs substituted for the generator's.",
        'acap_layers, acap_seconds and acap_concurrent are left to the shared bank on purpose. They '
        'read perfectly well for a merger (how many stems before the mix muddies, how long a file '
        'before something degrades, how many passes in parallel pay off) and rewriting them here would '
        'make this sheet incomparable with the other fourteen audio sheets.',
    ],
}
