# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""audio_shared: check kinds, fixed settings and the 53 subjects."""

from __future__ import annotations

# ── check kinds this bank adds (the runner is a table of these) ────────────────────────
CHECK_KINDS = {
    # CLAP (laion CLAP-HTSAT-fused, pinned in the run receipt) — the SCREEN, never the judge
    'clap_label_min': 'CLAP cosine(render, `label`) >= `min` AND >= the null baseline for that label (its mean cosine against the other 52 renders of the row) + `margin`',
    'clap_labels_all_min': 'every label in `labels` scores cosine >= `min` against the render',
    'clap_absent_max': 'every label in `labels` scores cosine <= `max` against the render (the thing asked NOT to be there)',
    'clap_rank_max': 'among the 53 SOUND_LABELS, the true `label` ranks at position <= `max` by cosine',
    'clap_window_label': "in the render's 1 s CLAP windows, the window at `window` ranks `label` above `over`",
    'clap_sequence': "the render's 1 s CLAP windows put the labels in `order` in that order, each first-ranked in at least one window",
    # events and timing (librosa onset_detect, default backtrack, hop 512 at the native rate)
    'onset_count': 'librosa onset count == `n` within +/- `tolerance`',
    'pause_ms': 'the silent gap at the position named by `after` (comma|full_stop|event) is between `min` and `max` ms',
    'pause_longer': 'the pause after `longer` exceeds the pause after `shorter` by >= `min_ms`',
    # level, length, space
    'duration_s': 'decoded duration between `min` and `max` seconds',
    'lufs_range': 'integrated loudness (BS.1770-4) between `min` and `max` LUFS',
    'true_peak_max': 'true peak <= `max` dBTP (4x oversampled)',
    'silence_max': 'longest stretch below -60 dBFS <= `max` seconds',
    'noise_floor_max': 'RMS of the quietest 200 ms window <= `max` dBFS',
    'rms_delta_db': 'RMS of the `louder` leg exceeds the `quieter` leg by >= `min` dB',
    'hf_ratio_max': 'energy above 4 kHz is at most `max` of the total energy',
    'hf_ratio_delta_min': 'the share of energy above 4 kHz falls from the `near` leg to the `far` leg by >= `min` dB',
    'rt60_range': 'Schroeder RT60 estimate between `min` and `max` seconds',
    'rtf_max': 'real-time factor (render seconds per output second) <= `max`, or <= `times` x the 1-stream RTF',
    # across renders
    'audio_identical': 'all repeats decode to a bit-identical float32 buffer (md5 of the samples)',
    'audio_similarity_min': 'mean cosine of the log-mel spectrogram against the render `to` >= `min`',
    'pairwise_audio_distinct': 'every pair of renders in the set has log-mel cosine distance >= `min`',
    # speech read back off the render (faster-whisper large-v3, pinned in the run receipt)
    'transcript_contains_terms': 'the Whisper transcript contains every term in `terms` (case-insensitive)',
    'transcript_absent_terms': 'the Whisper transcript contains no term in `terms`',
    'transcript_words_max': 'Whisper returns at most `max` words at confidence >= 0.5',
    'speaker_count': 'pyannote speaker-diarization-3.1 counts exactly `n` speakers',
    'prosody_delta_min': "median F0 or speaking rate differs from the pair's other leg by >= `min` (semitones for F0, per cent for rate)",
}

# ── fixed settings: the same for every row, recorded into every trial ──────────────────
SETTINGS = {
    'sample_rate_out': 48000,
    'channels': 1,
    'seconds': 4,
    'seconds_ambience': 12,
    'seeds': [11, 12, 13],
    'note': (
        'Delivery is 48 kHz mono for every sound row. A row whose engine has a different '
        'native rate (ACE-Step 44.1 kHz, IndexTTS 24 kHz, MusicGen 32 kHz) renders at its '
        'native rate and the runner records `native_rate` on the trial, then resamples to '
        '48 kHz with soxr VHQ for the CLAP screen and for the operator listen — the SAME '
        'resampler for every row. Every other generation setting (steps, cfg, sampler, '
        'guidance, temperature) is the engine default for that row, recorded verbatim on '
        'the trial and never varied inside one run.'
    ),
}

COND_SOUND = {'seeds': SETTINGS['seeds'], 'repeats': 3, 'seconds': 4, 'sample_rate_out': 48000, 'channels': 1}
COND_AMB = {'seeds': SETTINGS['seeds'], 'repeats': 3, 'seconds': 12, 'sample_rate_out': 48000, 'channels': 1}
COND_ONE = {'seed': 11, 'repeats': 1, 'sample_rate_out': 48000, 'channels': 1}
COND_JUDGE = {'repeats': 3, 'temperature': 0.0, 'seed': 11}

COND_NOTE = (
    'Every sound probe runs at seeds [11, 12, 13], one render per seed, repeats = 3 — so a '
    'pass rate of 3/3 is "yes" under the default state_rule and 2/3 is "partial". A row whose '
    'transport exposes no seed (the `library` lookup; edge-tts) runs three times anyway and '
    '`pd_seed_vs_prompt` plus `deterministic` are read from TRANSPORT_NA instead. Judge probes '
    '(`hear_*`, the Counting band, the judge extras) are scored on a fixture, so the render '
    'seeds do not apply; they run at temperature 0 with repeats = 3 where the judge is a model '
    'and repeats = 1 where it is an embedding (CLAP) or a meter (audio_qc), because a second '
    'call of a deterministic measurement buys nothing.'
)

CHECKS_NOTE = (
    'A check may carry `applies_to`: "speech" (rows that produce or read words — tts, '
    'voice_clone, voice_direction, voice_conversion, stt, melody, lipsync), "sound" (sfx_gen, '
    'sfx_library, sfx_process, music_gen, audio_mix, stem_split) or "judge" (diarization, '
    'audio_judges). A check without `applies_to` is applied to every row. A probe whose checks '
    'all carry an `applies_to` that no row of the sheet matches is not run on that sheet and '
    'writes `untested` with the reason — it is never scored as a no.'
)

# ── the 53 subjects: id -> (CLAP label, the verbatim render prompt) ────────────────────
# Every prompt is under 25 words. Prompt length is deliberate: a text-conditioned audio
# model's encoder truncates long prompts as silently as SDXL truncates at 77 CLIP tokens, so
# the subject prompts stay short and the LENGTH question is asked once, by pd_length_ladder.
SOUNDS = {
    # Human & movement (13)
    'footstep_wood': (
        'footsteps on wooden boards',
        'a single person walking slowly on bare wooden boards, interior, close, dry, no music, no voices',
    ),
    'footstep_stone': (
        'footsteps on stone',
        'a single person walking slowly on wet stone flags, exterior courtyard, close, no music, no voices',
    ),
    'footstep_mud': (
        'footsteps in mud',
        'a single person walking slowly through thick mud, exterior, close, wet suction, no music, no voices',
    ),
    'cloth_rustle': (
        'cloth rustling',
        'heavy wool cloth rustling as someone turns, interior, very close, dry, no music, no voices',
    ),
    'breath': (
        'a person breathing',
        'one person breathing quietly through the nose at rest, very close, dry, no words, no music',
    ),
    'effort': (
        'a person straining with effort',
        'one man straining to lift a heavy crate, grunting with effort, close, no words, no music',
    ),
    'laugh': ('a person laughing', 'one woman laughing warmly, close, interior, no words, no music, no other voices'),
    'cry': ('a person crying', 'one woman weeping quietly, close, interior, no words, no music, no other voices'),
    'scream': (
        'a person screaming',
        'one woman screaming in terror once, close, exterior, no words, no music, no echo',
    ),
    'cough': ('a person coughing', 'one man coughing twice, dry chest cough, close, interior, no words, no music'),
    'baby_cry': ('a baby crying', 'a newborn baby crying, close, interior, no adult voices, no music, no room reverb'),
    'crowd_murmur': (
        'a crowd murmuring',
        'a crowd of about thirty people murmuring indistinctly, medium distance, interior hall, no music, no single voice',
    ),
    'chewing': (
        'a person chewing food',
        'one person chewing and swallowing bread, very close, interior, no words, no music',
    ),
    # Objects & work (16)
    'door_creak': (
        'a creaking wooden door',
        'a heavy wooden door creaks open slowly on iron hinges, interior, close, no music, no voices',
    ),
    'hammer_wood': (
        'hammering wood',
        'a carpenter striking a wooden peg with a mallet, four blows, close, interior, no music, no voices',
    ),
    'saw_wood': (
        'sawing wood',
        'a hand saw cutting through a pine plank, steady strokes, close, workshop, no music, no voices',
    ),
    'wood_break': ('wood breaking', 'a thick wooden plank snapping and splintering once, close, no music, no voices'),
    'glass_break': (
        'glass breaking',
        'a glass bottle dropped on stone and shattering once, close, no music, no voices',
    ),
    'pottery_smash': (
        'pottery smashing',
        'an earthenware jug smashing on a stone floor once, close, interior, no music, no voices',
    ),
    'rope_creak': (
        'rope and rigging creaking',
        'hemp rope and rigging creaking under load on a moored ship, close, no music, no voices',
    ),
    'sail_flap': (
        'a sail flapping in wind',
        'canvas sail flapping and snapping in a gusting wind, medium distance, no music, no voices',
    ),
    'cart_wheels': (
        'cart wheels on cobbles',
        'a wooden handcart with iron-rimmed wheels rolling over cobbles, medium distance, no music, no voices',
    ),
    'coins': (
        'coins clinking',
        'a handful of silver coins poured onto a wooden table, close, interior, no music, no voices',
    ),
    'paper_rustle': (
        'paper rustling',
        'sheets of thick paper being turned and set down, very close, interior, no music, no voices',
    ),
    'quill_write': (
        'a quill pen writing',
        'a quill pen scratching words on paper, very close, quiet interior, no music, no voices',
    ),
    'pour_liquid': (
        'liquid pouring',
        'beer poured from an earthenware jug into a pewter cup, close, interior, no music, no voices',
    ),
    'sword_clash': (
        'metal blades clashing',
        'two steel blades striking each other three times, close, exterior, no music, no voices',
    ),
    'clock_tick': (
        'a clock ticking',
        'a wall clock ticking once a second in a quiet room, close, no chime, no music, no voices',
    ),
    'bell_church': (
        'a church bell ringing',
        'a single large church bell struck three times, exterior, medium distance, no music, no voices',
    ),
    # Nature & weather (9)
    'water_lap': (
        'water lapping',
        'harbour water lapping against a wooden quay, close, calm, no music, no voices, no gulls',
    ),
    'waves': (
        'sea waves breaking',
        'open sea waves breaking against a hull, medium distance, no music, no voices, no gulls',
    ),
    'rain_roof': (
        'rain on a roof',
        'steady rain falling on a tiled roof, interior perspective, no thunder, no music, no voices',
    ),
    'thunder': ('thunder', 'one distant thunderclap rolling and fading, exterior, no rain, no music, no voices'),
    'wind': ('wind blowing', 'wind through bare rigging and around a corner, exterior, steady, no music, no voices'),
    'fire_crackle': (
        'a crackling fire',
        'a small wood fire crackling and popping in a hearth, close, no music, no voices',
    ),
    'birdsong': (
        'birds singing',
        'small songbirds calling in a garden at dawn, exterior, medium distance, no music, no voices',
    ),
    'seagull': (
        'seagulls calling',
        'herring gulls calling over a harbour, exterior, medium distance, no music, no voices',
    ),
    'insects': (
        'insects chirping',
        'crickets and flies in a warm meadow at dusk, exterior, no music, no voices, no birds',
    ),
    # Animals (7)
    'dog_bark': ('a dog barking', 'one medium dog barking three times, exterior, medium distance, no music, no voices'),
    'cat': ('a cat meowing', 'one cat meowing twice, interior, close, no music, no voices, no purring'),
    'horse_hooves': (
        'horse hooves',
        'one horse walking on cobbles, shod hooves, medium distance, no cart, no music, no voices',
    ),
    'horse_whinny': (
        'a horse whinnying',
        'one horse whinnying once, exterior, medium distance, no hooves, no music, no voices',
    ),
    'cow': ('a cow lowing', 'one cow lowing twice in a byre, close, no music, no voices, no other animals'),
    'sheep': ('sheep bleating', 'a small flock of sheep bleating in a pen, medium distance, no music, no voices'),
    'chicken': ('hens clucking', 'hens clucking and scratching in a yard, close, no rooster, no music, no voices'),
    # Space & ambience (8)
    'room_tone_interior': (
        'the room tone of a small wooden room',
        'the room tone of a small wood-panelled house, no events, no music, no voices, no traffic',
    ),
    'room_tone_church': (
        'the room tone of a large stone church',
        'the room tone of a large empty stone church, long decay, no events, no music, no voices',
    ),
    'street_ambience': (
        'a quiet street ambience',
        'a quiet seventeenth-century street, distant footsteps and voices, no traffic, no music',
    ),
    'harbour_ambience': (
        'a harbour ambience',
        'a working harbour: water, rigging, distant gulls and cart wheels, no music, no engines',
    ),
    'market_ambience': (
        'a busy market ambience',
        'a busy open market: many indistinct voices, cart wheels, poultry, no music, no engines',
    ),
    'distance': ('a church bell heard from far away', 'PAIR'),
    'reverb_space': (
        'a hand clap in a large stone hall',
        'a single hand clap in a large stone hall with a long natural tail, no music, no voices',
    ),
    'off_screen': (
        'a door slamming in the next room',
        'a door slamming in another room behind a wall, heard from the next room, no music, no voices',
    ),
}
SOUND_LABELS = [lbl for lbl, _ in SOUNDS.values()]

AMBIENCE = (
    'room_tone_interior',
    'room_tone_church',
    'street_ambience',
    'harbour_ambience',
    'market_ambience',
    'reverb_space',
)

# The near/far pair for `distance` — the only subject that needs two renders to be a subject.
DISTANCE_PAIR = {
    'near': 'a single large church bell struck once, exterior, one metre away, dry, no music, no voices',
    'far': 'a single large church bell struck once, exterior, three hundred metres away, no music, no voices',
}

# Mechanical checks a particular subject allows on top of the CLAP screen and the operator.
SOUND_EXTRA = {
    'hammer_wood': [{'check': 'onset_count', 'n': 4, 'tolerance': 1}],
    'sword_clash': [{'check': 'onset_count', 'n': 3, 'tolerance': 0}],
    'bell_church': [{'check': 'onset_count', 'n': 3, 'tolerance': 0}],
    'dog_bark': [{'check': 'onset_count', 'n': 3, 'tolerance': 0}],
    'cough': [{'check': 'onset_count', 'n': 2, 'tolerance': 0}],
    'cat': [{'check': 'onset_count', 'n': 2, 'tolerance': 0}],
    'cow': [{'check': 'onset_count', 'n': 2, 'tolerance': 0}],
    'clock_tick': [{'check': 'onset_count', 'n': 4, 'tolerance': 1}],
    'crowd_murmur': [{'check': 'transcript_words_max', 'max': 2}],
    'room_tone_interior': [
        {'check': 'onset_count', 'n': 0, 'tolerance': 1},
        {'check': 'lufs_range', 'min': -60, 'max': -30},
    ],
    'room_tone_church': [{'check': 'rt60_range', 'min': 1.5, 'max': 6.0}],
    'reverb_space': [{'check': 'rt60_range', 'min': 0.8, 'max': 4.0}],
    'off_screen': [{'check': 'hf_ratio_max', 'max': 0.12}],
    'distance': [
        {'check': 'rms_delta_db', 'louder': 'near', 'quieter': 'far', 'min': 8},
        {'check': 'hf_ratio_delta_min', 'near': 'near', 'far': 'far', 'min': 4},
    ],
    'breath': [{'check': 'transcript_words_max', 'max': 0}],
    'effort': [{'check': 'transcript_words_max', 'max': 0}],
    'laugh': [{'check': 'transcript_words_max', 'max': 0}],
    'scream': [{'check': 'transcript_words_max', 'max': 0}],
}

CLAP_MIN = 0.28  # measured 2026-09-27: a correct render 0.827, a chroma-only match 0.279
CLAP_NULL_MARGIN = 0.02  # against a 0.252 null baseline on the same library
CLAP_ABSENT_MAX = 0.22  # below the chroma-only floor: the thing is really not there
