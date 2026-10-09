# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Sound effects, generated (sfx_gen). 2026-09-30.

Question the sheet asks: can we synthesise a sound effect that does not exist in any library?

The sheet's own note says this is the thinnest part of the stack: AudioGen was retired for its
licence on 2026-08-09 and nothing replaced it, so the two live rows are a MUSIC generator used
as a sound generator (ACE-Step 1.5 turbo through ace_step_service.generate) and the SFX Studio
effects rack (sfx_fx.py) used as a synthesiser. Both are honest answers to the question and
both are expected to be weak at it — which is exactly what a default test is for.

Shape of the test
-----------------
The 53-subject Makes bank, the Capacity ladders, the four Prompt bands and the universal
columns come from `audio_shared` and are run byte-identically here (48 kHz mono, 4 s per sound
and 12 s per ambience, seeds [11, 12, 13], repeats 3). This module answers only the 15 DOMAIN
columns the bank leaves to the step, and it answers them with a MECHANICAL detector wherever
one exists plus a BLIND operator where none does:

    realism      the 12-sound blind set against 12 verified REAL recordings (operator decides)
    prompt       one three-fact prompt with a countable key: two onsets, the slam 10 dB louder
    length       2 / 4 / 8 / 16 s asked, duration measured within ±5 %
    transient    a glass break's attack under 5 ms
    tail         a church bell's decay over 3 s to -40 dB
    loopable     the seam of a butt-joined 4 s loop, high-passed, 40 dB under the peak
    layerable    two renders summed: no over, loudness still in band
    period_sound three 1671 scenes: no mains hum in the spectrum, no modern element to the ear
    perspective  the bank's near/far bell pair: HF share and RMS must both move the right way
    variation    five seeds of one sound: pairwise waveform correlation under 0.9, label rank 1
    mono_stereo  the channel count as asked, and a "stereo" file whose channels actually differ
    sr_out       derived from the delivered file (not asked of the model)
    noise_floor  the quietest 200 ms of a room-tone render under -60 dBFS
    creature     a wolf growl and an invented creature call: CLAP rank plus the operator
    human        a laugh and a cough: CLAP rank plus the operator

What is blocked and why
-----------------------
`realism` is BLOCKED until the operator has confirmed the 12 REAL anchor recordings in
fixtures/sfx_gen/MANIFEST.json are genuine field recordings and not themselves generated. A
real/synthetic listening test whose "real" half is unverified measures nothing; and the anchors
are also the control — a run in which the operator calls fewer than 10 of the 12 real anchors
real is written `untested`, because the listening test did not work that day.

The dsp row is not a generator: sfx_fx's whole public contract is src → dst (`filters()` and
`render()` both take a source), and the only noise source in the file is the seeded
`anoisesrc=…:s=7` that builds the convolution IR. So the rack "synthesises" by shaping a fixed
primitive — one pink-noise bed and one one-sample impulse, both declared as fixtures with the
exact ffmpeg command that makes them — and DSP_CHAINS says which of the 53 subjects that
reaches. The other 44 are `na` on that row with the reason written out: the rack has no
oscillator, no physical model and no sample source, so it can shape a sound but not originate a
pitched, formant or event-sequence one.
"""

from __future__ import annotations

from capability_tests.audio_shared import DISTANCE_PAIR, SOUNDS

FX = 'capability_tests/fixtures/sfx_gen'
MANIFEST = FX + '/MANIFEST.json'
NOISE_BED = FX + '/noise_bed.wav'
IMPULSE = FX + '/impulse.wav'

# ── check kinds this module adds (the runner is a table of these) ──────────────────────
# Named for WHAT is measured, AGAINST WHAT, with the threshold field names. The bank's
# existing kinds are reused wherever they already say the same thing: `onset_count`,
# `duration_s`, `lufs_range`, `true_peak_max`, `noise_floor_max`, `clap_rank_max`,
# `clap_label_min`, `clap_absent_max`, `hf_ratio_delta_min`, `rms_delta_db`, `operator`.
CHECK_KINDS = {
    'peak_order': (
        'the render is cut at its librosa onsets into as many segments as `events` (matched to '
        '`events` in time order); the segment named `louder` has a sample peak at least `min_db` dB '
        'above every other named segment'
    ),
    'duration_range': (
        'decoded duration, after trimming leading and trailing silence below -60 dBFS, is within '
        '`tolerance_pct` per cent of the `asked` seconds of the grid rung being rendered'
    ),
    'attack_ms_max': (
        'time from -40 dBFS to the sample peak of the loudest onset is <= `max` ms, on an envelope '
        'taken with a 1 ms RMS window at the native rate'
    ),
    'decay_s_min': (
        'time from the peak of the last onset until the 1 ms-RMS envelope has fallen `to_db` dB below '
        'that peak is >= `min` seconds; a render that ends before the fall is a fail, not a pass'
    ),
    'loop_seam_residual_db_max': (
        'the render is butt-joined end-to-start; the peak of the >2 kHz high-passed signal '
        "in a `window_ms` window centred on the seam, relative to the render's own true "
        'peak, is <= `max` dB'
    ),
    'layer_sum_headroom': (
        'the renders named in `of` (trial ids) are summed at unity gain from a common start; the '
        'sum has true peak <= `peak_max` dBTP and integrated loudness (BS.1770-4) between '
        '`lufs_min` and `lufs_max` LUFS'
    ),
    'spectral_band_absent': (
        'in a Welch PSD at 1 Hz resolution, no narrow peak inside any band in `bands` (Hz pairs) '
        'rises more than `max_db` dB above the local spectral floor (the median PSD of the '
        'decade either side of that band)'
    ),
    'pairwise_waveform_corr_max': (
        "every pair of renders in the probe's set has |Pearson r| <= `max` after loudness "
        'normalisation and best-lag alignment within ±50 ms'
    ),
    'channels_equals': (
        'the DELIVERED file has exactly `n` channels; when `n` is 2 the two channels must also differ '
        '(|Pearson r| <= `max_corr`), because a dual-mono file is not a stereo render'
    ),
}

# ── conditions: the bank's, repeated here so a probe carries them verbatim ─────────────
SEEDS = [11, 12, 13]
COND = {'seeds': SEEDS, 'repeats': 3, 'seconds': 4, 'sample_rate_out': 48000, 'channels': 1}
COND_AMB = {'seeds': SEEDS, 'repeats': 3, 'seconds': 12, 'sample_rate_out': 48000, 'channels': 1}
COND_5 = {'seeds': [11, 12, 13, 14, 15], 'repeats': 5, 'seconds': 4, 'sample_rate_out': 48000, 'channels': 1}

# ── the fixed prompts this module adds; everything else is quoted from the bank ────────
PROMPTS = {
    'door_3fact': 'a heavy wooden door, creaks slowly, then slams',
    'loop_fire': 'a small wood fire burning steadily in a hearth, even crackle from beginning to end, no build, no music, no voices',
    'period_street': 'a quiet street in a Dutch town in 1671: footsteps on cobbles, a distant voice, a handcart, no engines, no music',
    'period_house': 'the inside of a 1671 merchant house at night: a fire in the hearth, a clock, wind at the shutters, no engines, no music',
    'period_harbour': 'a 1671 harbour at first light: water against the quay, hemp rigging, a handcart on the quay stones, no engines, no music',
    'creature_wolf': 'a large wolf growling low and close, then one short snarl, exterior at night, no music, no voices',
    'creature_call': 'an unseen creature calling twice across a marsh, deep and hollow, not any living animal, no music, no voices',
}
# Quoted from the bank so the two sheets cannot drift apart:
P_RAIN = SOUNDS['rain_roof'][1]
P_GLASS = SOUNDS['glass_break'][1]
P_BELL = SOUNDS['bell_church'][1]
P_WIND = SOUNDS['wind'][1]
P_STEP = SOUNDS['footstep_wood'][1]
P_HARBOUR = SOUNDS['harbour_ambience'][1]
P_TONE = SOUNDS['room_tone_interior'][1]
P_LAUGH = SOUNDS['laugh'][1]
P_COUGH = SOUNDS['cough'][1]

# The 12 subjects of the blind real/synthetic set, spread over all five subject groups; four of
# them (water_lap, rain_roof, fire_crackle, room_tone_church) are inside the dsp row's reach, so
# that row answers `realism` on a four-item subset and the state_note says so.
REALISM_SET = [
    'footstep_wood',
    'cloth_rustle',
    'door_creak',
    'glass_break',
    'coins',
    'pour_liquid',
    'bell_church',
    'water_lap',
    'rain_roof',
    'fire_crackle',
    'dog_bark',
    'room_tone_church',
]

MAINS_BANDS = [[49, 51], [59, 61], [99, 101], [119, 121]]


def _p(pid, title, feeds, checks, inputs, cond=None, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': dict(inputs),
        'conditions': dict(cond or COND),
        'checks': list(checks),
        'grade': 'measured',
    }
    p.update(kw)
    return p


PROBES = [
    # ── mechanical, cheapest first ────────────────────────────────────────────────────
    _p(
        'd_length',
        'Reaches the length asked',
        ['length'],
        [{'check': 'duration_range', 'tolerance_pct': 5, 'asked': 'the rung'}],
        {'prompt': P_RAIN},
        grid={'seconds': [2, 4, 8, 16]},
        state_note=(
            'one prompt, four asked lengths, three seeds each: 12 renders, each scored against its own rung. '
            'ace_step_service.generate clamps with max(5.0, min(duration_s, MAX_SECONDS)) — the 2 s rung '
            'therefore CANNOT pass for that row and the note must say the floor is in the caller, not in the '
            'model. The column is the pass rate over all 12.'
        ),
    ),
    _p(
        'd_channels',
        'Mono and stereo as asked',
        ['mono_stereo'],
        [{'check': 'channels_equals', 'n': 'the rung', 'max_corr': 0.98}],
        {'prompt': P_HARBOUR},
        cond=COND_AMB,
        grid={'channels': [1, 2]},
        state_note=(
            'asked mono, then asked stereo, three seeds each. A row with no channel argument (ACE-Step is '
            'driven through ace_step_service.generate, which exposes prompt, out_path, duration_s and seed '
            'and nothing else) fails the rung it cannot ask for — that is the measurement, not an exemption. '
            'A "stereo" file whose channels correlate above 0.98 is dual mono and is a no.'
        ),
    ),
    _p(
        'd_transient',
        'Transients are sharp',
        ['transient'],
        [
            {'check': 'attack_ms_max', 'max': 5.0},
            {'check': 'clap_label_min', 'label': SOUNDS['glass_break'][0], 'min': 0.26, 'margin': 0.02},
        ],
        {'prompt': P_GLASS},
        state_note=(
            'the same glass-break prompt the bank renders for make_glass_break, so the trial is REUSED and '
            'costs no extra render. The CLAP screen is there only to reject a render that is not an impact at '
            'all: a 3 ms attack on the wrong sound is not a pass.'
        ),
    ),
    _p(
        'd_tail',
        'Tail and decay are right',
        ['tail'],
        [
            {'check': 'decay_s_min', 'min': 3.0, 'to_db': -40},
            {'check': 'clap_label_min', 'label': SOUNDS['bell_church'][0], 'min': 0.26, 'margin': 0.02},
        ],
        {'prompt': P_BELL},
        state_note=(
            "reuses the bank's make_bell_church renders. The 4 s clip is long enough to hold a 3 s decay; a "
            'render that is still ringing when the file ends fails, because the tail was truncated rather '
            'than shaped.'
        ),
    ),
    _p(
        'd_noise_floor',
        'Clean noise floor',
        ['noise_floor'],
        [
            {'check': 'noise_floor_max', 'max': -60, 'window': 'the quietest 200 ms of the render'},
            {'check': 'spectral_band_absent', 'bands': MAINS_BANDS, 'max_db': 6},
        ],
        {'prompt': P_TONE},
        cond=COND_AMB,
        state_note=(
            "reuses the bank's make_room_tone_interior renders — room tone is the hardest case for a floor, "
            'because the wanted signal is itself near the floor. The mains-hum bands are checked here too: a '
            'generated "quiet room" that hums at 50 Hz is not a clean floor, it is a modelled artefact.'
        ),
    ),
    _p(
        'd_loopable',
        'Loops seamlessly',
        ['loopable'],
        [
            {'check': 'loop_seam_residual_db_max', 'max': -40, 'window_ms': 20},
            {
                'check': 'lufs_range',
                'min': -30,
                'max': -14,
                'note': 'the loop must not ramp: measured on the first and last second separately',
            },
        ],
        {'prompt': PROMPTS['loop_fire']},
        state_note=(
            "a 4 s render is butt-joined to itself and the seam is measured; -40 dB under the render's own "
            'true peak is the house threshold for an inaudible join. The loudness check catches the other way '
            'a loop fails — a render that fades in or out loops smoothly and still pumps.'
        ),
    ),
    _p(
        'd_layerable',
        'Layers with other sounds',
        ['layerable'],
        [
            {
                'check': 'layer_sum_headroom',
                'of': ['d_layerable#wind', 'd_layerable#rain'],
                'peak_max': -1.0,
                'lufs_min': -24,
                'lufs_max': -14,
            }
        ],
        {'prompt': [P_WIND, P_RAIN]},
        state_note=(
            'the bank already renders wind and rain on a roof; this probe only SUMS them at unity gain, so it '
            'costs no render at all. It fails when either render is delivered so hot that two of them clip, '
            'which is the practical meaning of "layers": the sheet\'s acap_layers ladder asks how MANY.'
        ),
    ),
    _p(
        'd_perspective',
        'Near and far versions',
        ['perspective'],
        [
            {'check': 'hf_ratio_delta_min', 'near': 'near', 'far': 'far', 'min': 3.0},
            {'check': 'rms_delta_db', 'louder': 'near', 'quieter': 'far', 'min': 6.0},
            {
                'check': 'operator',
                'blind': True,
                'question': 'You hear two takes of the same event, A then B. Is B further away than A? yes/no',
            },
        ],
        {'prompt': 'PAIR', 'pair': dict(DISTANCE_PAIR)},
        state_note=(
            "the bank's own near/far church-bell pair, so make_distance and this column are measured on the "
            'same two renders. BOTH mechanical checks must move the right way: a row that only turns the '
            'volume down has changed the level, not the distance, and the HF check is what tells them apart. '
            'The operator question is the third leg and decides a disagreement.'
        ),
    ),
    _p(
        'd_prompt',
        'Obeys the prompt',
        ['prompt'],
        [
            {'check': 'onset_count', 'n': 2, 'tolerance': 0},
            {'check': 'peak_order', 'events': ['creak', 'slam'], 'louder': 'slam', 'min_db': 10},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this sound contain a slow creak FOLLOWED BY a slam, in that order, and nothing else? yes/no',
            },
        ],
        {'prompt': PROMPTS['door_3fact']},
        state_note=(
            'three facts in eleven words — the object (heavy wooden door), the first event (creaks slowly) and '
            'the second event (then slams) — and all three are countable: two onsets, the second at least '
            '10 dB above the first, in that order. This is the whole obedience question for a sound generator: '
            "the bank's Prompt bands measure how the prompt may be WRITTEN, this measures whether what it "
            'says arrives.'
        ),
    ),
    _p(
        'd_variation',
        'Many variations of one sound',
        ['variation'],
        [
            {'check': 'pairwise_waveform_corr_max', 'max': 0.9},
            {'check': 'clap_rank_max', 'label': SOUNDS['footstep_wood'][0], 'among': 'SOUND_LABELS', 'max': 1},
        ],
        {'prompt': P_STEP},
        cond=COND_5,
        state_note=(
            'five seeds of one prompt, 11 to 15. Footsteps are the case that matters: a step library that '
            'repeats is heard as a repeat within three paces. Both halves must hold — five renders that all '
            'differ but no longer rank as footsteps are variation bought by losing the subject.'
        ),
    ),
    # ── operator-decided ──────────────────────────────────────────────────────────────
    _p(
        'd_period',
        'Period-correct',
        ['period_sound'],
        [
            {'check': 'spectral_band_absent', 'bands': MAINS_BANDS, 'max_db': 6},
            {
                'check': 'clap_absent_max',
                'labels': [
                    'a car engine',
                    'a siren',
                    'an electric hum',
                    'an aeroplane',
                    'a diesel engine',
                    'a telephone ringing',
                ],
                'max': 0.22,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is there anything in this recording that did not exist in 1671 — an engine, a siren, an electric hum, a radio, a car horn? yes/no',
            },
        ],
        {'prompt': [PROMPTS['period_street'], PROMPTS['period_house'], PROMPTS['period_harbour']]},
        cond=COND_AMB,
        state_note=(
            'three 1671 scenes, three seeds each: 9 renders of 12 s. The operator question is INVERTED (yes '
            "means a modern element IS present) and the runner flips it before scoring, per the bank's "
            'operator protocol. The mains-hum bands are the mechanical half: 50/60 Hz and their second '
            "harmonics are the anachronism a machine can actually find, and CLAP's absent-screen catches the "
            'loud ones. Nothing mechanical finds a distant car, which is why the operator listens.'
        ),
    ),
    _p(
        'd_creature',
        'Creature and non-real sounds',
        ['creature'],
        [
            {'check': 'clap_rank_max', 'label': 'a wolf growling', 'among': 'SOUND_LABELS', 'max': 3},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this one animal or creature making one sound, believable as a living thing, with no human voice in it? yes/no',
            },
        ],
        {'prompt': [PROMPTS['creature_wolf'], PROMPTS['creature_call']]},
        state_note=(
            'two prompts x three seeds. The wolf is the measurable half: "a wolf growling" is not one of the '
            '53 bank labels, so ranking it in the top 3 against them is a weak but real screen (a growl that '
            'ranks below "a cow lowing" is not a growl). The invented marsh call has no label at all and is '
            "the operator's alone — which is the honest state of the art: no local judge decides whether an "
            'imagined creature sounds right.'
        ),
    ),
    _p(
        'd_human',
        'Human non-speech',
        ['human'],
        [
            {
                'check': 'clap_rank_max',
                'label': 'HERE: the label of the subject rendered',
                'among': 'SOUND_LABELS',
                'max': 1,
            },
            {
                'check': 'transcript_absent_terms',
                'terms': ['the', 'and', 'a', 'I', 'you', 'is'],
                'note': 'faster-whisper on the render must NOT return words: a laugh that is transcribed is speech',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this a real human making this sound without speaking, and does it sound like one person? yes/no',
            },
        ],
        {'prompt': [P_LAUGH, P_COUGH]},
        state_note=(
            'the bank already renders laugh and cough, so this probe reuses those six trials. The extra thing '
            'it asks is the failure mode a music generator has here: a "laugh" that is actually a sung '
            'syllable transcribes as a word. The screen label is the bank label of the subject being scored '
            '(a person laughing / a person coughing).'
        ),
    ),
    # ── the one universal column this step must own (see notes) ───────────────────────
    _p(
        'd_failsafe',
        'Fails without breaking the caller',
        ['failsafe'],
        [
            {
                'check': 'operator',
                'blind': False,
                'question': 'Did the call return a value or raise a catchable exception, leaving the process alive and the VRAM released within 30 s? yes/no',
            },
            {
                'check': 'file_absent',
                'path': 'output/capabilities/failsafe/partial.wav',
                'note': 'a half-written file left behind is a fail',
            },
        ],
        {
            'task': (
                'call the row on a DELIBERATELY broken input three ways and record what came back: (1) prompt = the '
                "empty string; (2) audio / source = capability_tests/fixtures/audio/judge/truncated.wav (the bank's "
                'WAV whose header claims 40 s over 0.2 s of data); (3) seconds = 0'
            ),
            'fixture': 'capability_tests/fixtures/audio/judge/truncated.wav',
        },
        cond={'seed': 11, 'repeats': 3, 'sample_rate_out': 48000, 'channels': 1},
        state_note=(
            "the bank's u_failsafe, restated here because its input is declared under a key the validator "
            'does not accept (see notes). Three broken calls, all three must come back: yes = every call '
            'returned or raised something the caller can catch, the process is still up and nvidia-smi shows '
            'the VRAM released within 30 s; no = any hang past 120 s, any crash of the calling process, or a '
            'partial file left on disk. This check is SIGHTED — it is about the process, not the sound. '
            'Expected by code read but not assumed: ace_step_service.generate wraps its whole body in '
            '`except Exception` and returns False, and sfx_fx.render raises ValueError for a slot type it '
            'cannot render; the probe is what turns that reading into a measurement.'
        ),
    ),
    _p(
        'd_realism',
        'Sounds like the thing',
        ['realism'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this a real recording of a real event, or was it made by a machine? Answer yes for a real recording.',
            }
        ],
        {'prompt': 'BANK_SUBSET: the 12 subjects in REALISM_SET, rendered by the bank', 'fixture': MANIFEST},
        state_note=(
            "the row's 12 renders (3 seeds each = 36 trials) are shuffled BLIND together with the 12 verified "
            'real recordings named in MANIFEST.real_anchors. A render the operator calls real is a pass. The '
            'anchors are the CONTROL: if the operator marks fewer than 10 of the 12 real ones real, the whole '
            'probe is written `untested` with that count, because the listening test did not work — it is a '
            'statement about the session, not about the model. A row that can render only part of the set (the '
            'dsp row reaches water_lap, rain_roof, fire_crackle and room_tone_church) is scored over its own '
            'subset and the trial count is recorded on the cell.'
        ),
    ),
]

RUN_ORDER = [
    'd_failsafe',
    'd_length',
    'd_channels',
    'd_transient',
    'd_tail',
    'd_noise_floor',
    'd_loopable',
    'd_layerable',
    'd_perspective',
    'd_prompt',
    'd_variation',
    'd_period',
    'd_creature',
    'd_human',
    'd_realism',
    'SHARED: the 53-subject Makes bank last (159 renders per row)',
]

# ── the dsp row: what a processing rack can originate, and with what chain ─────────────
# sfx_fx.py has no source generator — `filters(typ, p, ctx)` and `render(typ, p, src, dst)` both
# take a source. So the "synthesis" is a fixed primitive (a pink-noise bed or a one-sample
# impulse, both fixtures below) shaped by a fixed chain of the rack's own blocks, named by their
# real ids. This table IS the dsp row's prompt: the runner applies the chain and nothing else.
DSP_CHAINS = {
    'wind': [
        ['fx_band', 'band pass 120-1800 Hz'],
        ['fx_tremolo', 'rate 0.2 Hz, depth 40 %'],
        ['fx_tilt', 'dark 3 dB'],
        ['fx_loudness', '-24 LUFS, linear'],
    ],
    'rain_roof': [
        ['fx_eq18', 'tilt bright above 2 kHz'],
        ['fx_spectral', 'spectral gate for droplet texture'],
        ['fx_reverb', 'small wooden room'],
        ['fx_loudness', '-24 LUFS, linear'],
    ],
    'waves': [
        ['fx_band', 'band pass 60-900 Hz'],
        ['fx_tremolo', 'rate 0.12 Hz, depth 70 %'],
        ['fx_subboost', 'gentle'],
        ['fx_loudness', '-22 LUFS, linear'],
    ],
    'water_lap': [
        ['fx_band', 'band pass 200-4000 Hz'],
        ['fx_tremolo', 'rate 0.8 Hz, depth 80 %'],
        ['fx_punch', 'transient shaper, attack up'],
        ['fx_loudness', '-26 LUFS, linear'],
    ],
    'fire_crackle': [
        ['fx_spectral', 'spectral gate, fast'],
        ['fx_punch', 'attack up, sustain down'],
        ['fx_band', 'band pass 300-9000 Hz'],
        ['fx_loudness', '-24 LUFS, linear'],
    ],
    'thunder': [
        ['fx_band', 'band pass 20-400 Hz'],
        ['fx_convolve', 'synthesised IR, 4 s decay'],
        ['fx_fadepro', 'exponential out'],
        ['fx_subboost', 'strong'],
        ['fx_loudness', '-20 LUFS, linear'],
    ],
    'room_tone_interior': [
        ['fx_band', 'band pass 40-6000 Hz'],
        ['fx_reverb', 'small wooden room'],
        ['fx_gainstage', '-55 dB'],
    ],
    'room_tone_church': [
        ['fx_band', 'band pass 60-5000 Hz'],
        ['fx_convolve', 'synthesised IR, 4 s decay'],
        ['fx_gainstage', '-52 dB'],
    ],
    'reverb_space': [['fx_convolve', 'synthesised IR, 4 s decay — the source is the one-sample impulse, not the bed']],
}
DSP_SOURCE = {sid: (IMPULSE if sid == 'reverb_space' else NOISE_BED) for sid in DSP_CHAINS}

DSP_MAKE_NA = (
    'the SFX Studio rack is a PROCESSOR, not a generator: sfx_fx.filters() and sfx_fx.render() both take a source '
    'file, and the only noise source in the module is the seeded anoisesrc that builds the convolution IR. It has no '
    'oscillator, no physical model and no sample bank, so it can shape this sound but cannot originate it — DSP_CHAINS '
    'lists the nine subjects a noise bed or a one-sample impulse does reach.'
)
DSP_NA = {f'make_{sid}': DSP_MAKE_NA for sid in SOUNDS if sid not in DSP_CHAINS}
DSP_NA.update(
    {
        'prompt': 'the rack takes a parameter set, not a prompt: a slot is an effect id plus its knob values, so there is '
        'no instruction whose facts could arrive or fail to arrive (DSP_CHAINS is the fixed input instead).',
        'transient': 'the rack can sharpen an existing attack (fx_punch) but cannot originate an impact: the only sources '
        'it has are a noise bed and a one-sample impulse, and neither is a glass break. Measured on the '
        'acestep row; on this row the honest answer is that the question is about a source it does not have.',
        'period_sound': 'a filtered noise bed contains nothing at all, so "no modern element" is true by construction and '
        'says nothing about the row. The rack cannot build a 1671 street (voices, carts, gulls) to ask '
        'the question of, so the column is not applicable rather than a free yes.',
        'variation': 'the rack is deterministic and has no seed — the same chain on the same source is bit-identical, and '
        "even its convolution IR is seeded s=7 in the code. Variation here is a property of the operator's "
        'knob moves, not of the row, so the column would measure the test author, not the rack.',
        'creature': 'a growl or a call needs pitched, formant-bearing content; the rack has no oscillator and no voice '
        'model, and shaping noise cannot produce one. Measured on the acestep row.',
        'human': 'the rack has no voice model and no sample bank, so it cannot originate a laugh, a cough or a scream. '
        'Human non-speech on this step is measured on the acestep row; the library step owns the recorded case.',
    }
)
DSP_NA_BANDS = {
    'reason': 'the SFX Studio rack has no prompt at all: a slot is an effect id plus numeric knob values '
    '(sfx_fx._k/_t/_s), so every question about how a prompt may be written, damaged, lengthened or '
    'steered has no input to ask it of. The parameter set is the fixed input and it is in DSP_CHAINS.',
    'bands': ['Prompt: damage', 'Prompt: clarity needed', 'Prompt: limits', 'Prompt: steering'],
}

TEST = {
    'step': 'sfx_gen',
    'version': '2026-09-30.1',
    'title': 'Fifteen domain probes over the shared 53-sound bank: a music model and an effects rack asked to make a sound effect',
    'purpose': (
        'Measure whether either live row can synthesise a sound effect that no library holds — obedience to a '
        'three-fact prompt, length, transient, tail, loop, layer, period, perspective, variation, channels, '
        'floor, creature and human non-speech — with a mechanical detector wherever one exists and a blind '
        'operator where none does.'
    ),
    'include_shared': 'audio',
    'rows': {
        'acestep_sfx': {
            'transport': 'service',
            'model': 'ACE-Step 1.5 turbo AIO (ace_step_1.5_turbo_aio.safetensors, Comfy-Org rev 54b2ef4d8af5; engine MIT, ACE-Step/Ace-Step1.5 rev 19671f406d60)',
            'where': 'ace_step_service.generate(prompt, out_path, duration_s, seed=) → the _comfy_workflows/ace_step_bgm.json workflow on the resident ComfyUI server',
            'row_note': (
                "A MUSIC generator asked for sound effects — that is the sheet's question, not a mistake. "
                'Three facts the runner must respect: (1) generate() RETURNS THE CACHED FILE when out_path '
                'already exists and is over 10 kB, so every trial needs a fresh path or the test measures '
                'the first render 462 times; (2) duration is clamped by max(5.0, min(duration_s, '
                "ZYG_ACE_MAX_SECONDS)), so the 2 s rung of d_length cannot pass and the cell's note must "
                'say the floor is in the caller; (3) the only arguments are prompt, out_path, duration_s '
                'and seed — there is no channel, sample-rate or format argument, and delivery is an MP3 '
                "copied out of the Comfy output folder at ACE-Step's native 44.1 kHz."
            ),
        },
        'audiogen': {
            'transport': 'retired',
            'model': 'facebook/audiogen-medium',
            'where': 'removed from the stack; no module calls it',
            'skip': (
                'AudioGen was retired on 2026-08-09 in the licence sweep that also replaced musicgen_service '
                '(CC-BY-NC weights); nothing in production has called it since and the weights are not pinned '
                'in the vault. The row is kept so the sheet keeps the receipt of why generative SFX is thin.'
            ),
            'budget': {
                'calls': 0,
                'tokens_in': 0,
                'tokens_out': 0,
                'minutes': 0,
                'gpu_minutes': 0,
                'operator_minutes': 0,
                'tokens_note': 'a retired row is never run, so it spends nothing on any meter',
                'note': 'Retired 2026-08-09: the runner writes untested "retired" on all 156 columns and issues no call, so every budget field is zero.',
            },
        },
        'dsp': {
            'transport': 'service',
            'model': 'the SFX Studio effect rack — 60 DSP blocks over ffmpeg, IRs synthesised in-module',
            'where': 'sfx_fx.filters(typ, p, ctx) for the batchable blocks and sfx_fx.render(typ, p, src, dst) for the two-pass ones, staged by sfx_merger.render_mix',
            'na': DSP_NA,
            'na_bands': DSP_NA_BANDS,
            'row_note': (
                'Licence-clean by construction: ffmpeg is an external tool and the convolution IRs are '
                "synthesised from seeded noise, so no IR pack's terms reach the render (sfx_fx docstring). "
                'The rack runs at _SR = 48000 and is CPU-only.'
            ),
            'budget': {
                'calls': 90,
                'minutes': 25,
                'gpu_minutes': 0,
                'operator_minutes': 20,
                'note': (
                    '9 DSP_CHAINS subjects x 3 repeats = 27 chain renders (the repeats are '
                    'bit-identical and are run anyway, because that is what proves `deterministic`), '
                    'plus 8 domain probes x 3 = 24, plus the Capacity ladders the rack does answer '
                    '(layers, seconds, concurrent) at ~40 ffmpeg passes. ~150 ffmpeg passes at ~8 s = '
                    '~20 min of CPU, no GPU at all. Operator: 27 Makes decisions + ~12 domain '
                    'decisions = ~39 x 30 s = ~20 min.'
                ),
            },
        },
    },
    'probes': PROBES,
    'derive': {
        'sr_out': {
            'from': (
                'the sample rate and channel count of the DELIVERED file, read with ffprobe on the trial '
                "artefact, against the bank's 48 kHz mono delivery contract. acestep_sfx delivers a "
                '44.1 kHz MP3 (ACE-Step native, copied out of the Comfy output folder by '
                'ace_step_service.generate) and the cell records both the native rate and whether the '
                'runner had to resample with soxr VHQ; the dsp row runs at sfx_fx._SR = 48000.'
            ),
            'grade': 'measured',
            'unit': 'count',
        },
    },
    'lookup': {},
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': MANIFEST,
            'verified': False,
            'blocks': ['realism'],
            'generated': (
                'author it by hand: for each of the 12 REALISM_SET subjects pick one item from the house SFX '
                'library whose slate says field recording (not generated, not a library-of-libraries '
                'resample), copy the 12 items into fixtures/sfx_gen/real/ at 48 kHz mono 4 s (12 s for '
                'room_tone_church), and write {"real_anchors": [{"subject", "path", "source_slate", '
                '"licence"}], "verified": false} — then listen to all 12 once and set verified true'
            ),
            'how_to_verify': (
                'listen to each of the 12 anchors and confirm two things: it is a recording of the real '
                'event (not a synthesised or resampled library item) and it is the subject its name says. '
                'Read the slate for each one and copy the licence into the manifest. Then set verified = '
                'true. Until then `realism` is written untested "key unverified": a real/synthetic test '
                'whose real half is unverified measures nothing.'
            ),
        },
        {
            'path': NOISE_BED,
            'verified': True,
            'generated': (
                'ffmpeg -y -f lavfi -i "anoisesrc=d=12:c=pink:r=48000:a=0.7:s=1671" -ac 1 -c:a pcm_s24le '
                'capability_tests/fixtures/sfx_gen/noise_bed.wav'
            ),
        },
        {
            'path': IMPULSE,
            'verified': True,
            'generated': (
                'ffmpeg -y -f lavfi -i "aevalsrc=if(eq(n\\,0)\\,0.98\\,0):d=4:s=48000" -ac 1 -c:a pcm_s24le '
                'capability_tests/fixtures/sfx_gen/impulse.wav'
            ),
        },
    ],
    'dsp_chains': {
        'chains': DSP_CHAINS,
        'source': DSP_SOURCE,
        'note': (
            'the dsp row has no prompt; this table is its fixed input. The runner builds the chain '
            'with sfx_fx.filters/render in the order given, on the source named, and records the '
            'full parameter dict of every slot on the trial. Knob values not named here are the '
            "rack's own defaults (sfx_fx.FX), recorded verbatim, and are never varied inside a run."
        ),
    },
    'run_order': RUN_ORDER,
    'budget': {
        'calls': 462,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'a sound generator takes a tag string through a ComfyUI workflow and a DSP rack takes knob values; no language model is called on this step, so no token meter moves',
        'minutes': 110,
        'gpu_minutes': 105,
        'operator_minutes': 130,
        'note': (
            'Per row, dominated by the SHARED BANK: 53 subjects x 3 seeds = 159 renders (47 at 4 s, 6 ambience '
            "at 12 s) at ~10 s each = ~27 min. Then the bank's Capacity ladders ~105 renders = ~18 min, "
            'Prompt: damage 20 variants x 3 = 60 = ~10 min, clarity ~18 = ~3 min, limits ladders ~40 = ~7 min, '
            'steering ~20 = ~4 min, the three measured universals ~10 = ~2 min. This module adds only ~50 new '
            'renders (~9 min): d_length 12, d_channels 6, d_loopable 3, d_prompt 3, d_period 9, d_perspective '
            '6, d_variation 5, d_creature 6 — d_transient, d_tail, d_noise_floor, d_layerable, d_human and '
            'd_realism REUSE bank trials and cost nothing. 462 calls x ~12 s + 1 min checkpoint load = ~95 min, '
            'rounded to 110 with queue overhead; effectively all of it is GPU. Set ZYG_COMFY_KEEP_LOADED before '
            'the run: ComfyUI evicts the ACE checkpoint after every job otherwise and 462 reloads at ~25 s add '
            '~3.2 h. No Claude week is spent — neither row is claude_cli or anthropic_api. Operator: 159 blind '
            'Makes decisions + ~40 domain decisions (36 realism renders + 12 real anchors, 9 period, 6 '
            'perspective, 6 creature, 6 human, 3 prompt — capped at the ~40 the brief budgets by scoring '
            "realism on one seed per subject in a first pass) = ~199 x 30 s = ~100 min, plus the bank's own "
            'prompt-band operator decisions (~60) = ~130 min. The dsp row overrides all of this: no GPU, '
            '~150 ffmpeg passes, ~20 min. The audiogen row is retired and costs zero.'
        ),
    },
    'notes': [
        "The step's verdict on the sheet is that generative SFX is the thinnest part of the stack. This test does "
        'not assume that: it renders the same 53 subjects a library step is asked for and lets the operator decide, '
        'so "the library carries the work" becomes a measured comparison against the sfx_library sheet rather than a '
        'standing opinion.',
        "CLAP is only ever a SCREEN here, never the judge — the bank's receipt (2026-09-27: a correct render 0.827, "
        'a chroma-only match 0.279, null 0.252) and the defect-judge bench (34/40 global, 2/8 local) are why every '
        "subjective column carries a blind operator check and the operator's answer wins a disagreement.",
        'Nine of the fifteen domain columns are decided by a detector alone (length, channels, transient, tail, '
        'noise floor, loop seam, layer sum, perspective features, variation correlation). That is the point of '
        'choosing these fifteen: a sound generator can be held to a number far more often than an image generator '
        "can, so the operator's 30-second decisions are spent only where no meter exists.",
        "This module reuses the bank's own prompt text by importing SOUNDS and DISTANCE_PAIR rather than copying "
        "it, so a change to a subject prompt cannot silently make this step's transient, tail, floor, layer, human "
        'and perspective probes disagree with make_glass_break and friends.',
        "Sixteen columns, not fifteen: this step also owns `failsafe`. The bank's u_failsafe declares its input "
        'under the key `command`, and the validator accepts a fixed input only under prompt / task / fixture / '
        'audio, so that probe errors on the first audio step to include the bank. d_failsafe restates it verbatim '
        "under `task` (which drops the bank's copy, because a step's own disposition wins). When the bank renames "
        "that key to `task`, delete d_failsafe from this module and the bank's probe takes the column back.",
        "Known imprecision inherited from the bank: transport_na['service']['pd_tag_vocab'] exempts every "
        'service row, while its own reason says only the DSP rack rows should take it. The acestep_sfx row DOES '
        'answer that column (an ACE-Step tag string is exactly the question), and the bank owns the column, so the '
        'per-row view will under-report it until the bank keys that exemption by row instead of by transport.',
        'The 2 s rung of d_length and both rungs of d_channels are expected to fail on acestep_sfx for a reason that '
        'is in ace_step_service.py rather than in the model. They are still measured, because "the house cannot ask '
        'for it" is the capability the sheet is about; the row_note carries the code fact so the cell is not read as '
        'a verdict on ACE-Step itself.',
    ],
}
