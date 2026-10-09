# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""vocabulary.py — Option vocabulary: pitch names, modes, age bands and moods.

Moved verbatim out of ``kids_music_theory.py`` (original lines 51-283).
"""

from __future__ import annotations


# ── Vocabulary ───────────────────────────────────────────────────────────────

PITCH_NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']
NAME_TO_PC = {
    'C': 0,
    'C#': 1,
    'Db': 1,
    'D': 2,
    'D#': 3,
    'Eb': 3,
    'E': 4,
    'F': 5,
    'F#': 6,
    'Gb': 6,
    'G': 7,
    'G#': 8,
    'Ab': 8,
    'A': 9,
    'A#': 10,
    'Bb': 10,
    'B': 11,
}

# Scale tables.  A pentatonic mode has FIVE indices per octave, so "+1 index" is
# still one step of that scale — which is exactly why pentatonic tunes are so
# forgiving: every step is a whole tone or a minor third and nothing clashes.
MODES = {
    'major': {'label': 'Major', 'steps': [0, 2, 4, 5, 7, 9, 11], 'diatonic': True},
    'major_pentatonic': {'label': 'Major pentatonic', 'steps': [0, 2, 4, 7, 9], 'diatonic': False},
    'natural_minor': {'label': 'Natural minor', 'steps': [0, 2, 3, 5, 7, 8, 10], 'diatonic': True},
    'minor_pentatonic': {'label': 'Minor pentatonic', 'steps': [0, 3, 5, 7, 10], 'diatonic': False},
    'mixolydian': {'label': 'Mixolydian', 'steps': [0, 2, 4, 5, 7, 9, 10], 'diatonic': True},
}

# The parent 7-note scale a mode's harmony is drawn from.  Pentatonic melodies
# still sit over ordinary triads; the melody simply cannot reach some of the
# chord tones, which the strong-beat rule handles by intersecting the two sets.
PARENT_OF = {
    'major': 'major',
    'major_pentatonic': 'major',
    'mixolydian': 'mixolydian',
    'natural_minor': 'natural_minor',
    'minor_pentatonic': 'natural_minor',
}

# Age bands.  Ranges are the SINGABLE range for that age, not the range of an
# instrument: a toddler group can hold roughly C4–C5, and every extra semitone
# above that is a note the room stops singing.
# `max_density` is notes per second of the SUNG BODY (intro and outro excluded).
# Set 2026-08-29 at ~1.2x the measured maximum over 168 candidates per band
# across the whole mood x duration grid (toddler 1.50, preschool 1.79, early
# 2.28 n/s). The previous ceilings (2.8/3.6/4.4) were ~2x above anything the
# composer could produce AND were divided by a duration that included the
# intro and outro, so the metric understated by ~20% and then compared the
# understatement against an unreachable cap: it scored 1.000 on all 2,016
# candidates ever generated. A metric that cannot fail is not a measurement.
AGE_BANDS = {
    'toddler': {
        'label': 'Toddler (2–4)',
        'lo': 60,
        'hi': 72,  # C4–C5
        'max_leap': 7,
        'max_span': 9,
        'stepwise_min': 0.60,
        'max_density': 1.80,
        'allow_eighths': True,
        'allow_dotted': False,
        'allow_syncopation': False,
        'max_distinct_durations': 3,
        'syllables': (4, 7),
        'bpm': (84, 112),
    },
    'preschool': {
        'label': 'Preschool (4–6)',
        'lo': 60,
        'hi': 74,  # C4–D5
        'max_leap': 8,
        'max_span': 12,
        'stepwise_min': 0.52,
        'max_density': 2.15,
        'allow_eighths': True,
        'allow_dotted': True,
        'allow_syncopation': False,
        'max_distinct_durations': 4,
        'syllables': (5, 9),
        'bpm': (92, 126),
    },
    'early': {
        'label': 'Early school (6–8)',
        'lo': 59,
        'hi': 77,  # B3–F5
        'max_leap': 12,
        'max_span': 14,
        'stepwise_min': 0.45,
        'max_density': 2.75,
        'allow_eighths': True,
        'allow_dotted': True,
        'allow_syncopation': True,
        'max_distinct_durations': 5,
        'syllables': (6, 11),
        'bpm': (96, 138),
    },
    # NOT an age at all — an INSTRUMENT'S range. Cinematic cues are PLAYED, not
    # sung, so every number a child's larynx imposes is the wrong number: the
    # window is G3–C6 (the comfortable overlap of flute, oboe, horn, violin and
    # cello rather than one voice), an octave leap is ordinary writing rather
    # than a hazard, and a phrase runs eight bars because nobody has to breathe.
    # It lives in AGE_BANDS because every gate in score_plan is keyed on this
    # dict — a parallel table would be a second place to forget. `instrumental`
    # says so out loud to the UI; `long_phrases` is what compose() reads.
    'cinematic': {
        'label': 'Instrumental (cinematic)',
        'lo': 55,
        'hi': 84,  # G3–C6
        'max_leap': 12,
        'max_span': 19,
        'stepwise_min': 0.40,
        'max_density': 3.6,
        'allow_eighths': True,
        'allow_dotted': True,
        'allow_syncopation': True,
        'max_distinct_durations': 6,
        'syllables': (6, 12),
        'bpm': (50, 176),
        'instrumental': True,
        'long_phrases': True,
    },
}

# Hard ceiling on lyric lines carried through a brief. A 180 s song at the
# fastest band asks for 42 lines, so the old cap of 32 truncated real
# requests; 64 is above anything _plan_sections can generate.
LYRIC_LINE_CAP = 64

# Moods carry the musical consequences of a word, so the brief can stay in plain
# language.  `lead`/`pad`/`bass`/`perc` are General-MIDI program numbers resolved
# against the MIT SoundFont; `tags` seed the ACE-Step prompt.
MOODS = {
    'happy': {
        'label': 'Happy',
        'modes': ['major', 'major_pentatonic'],
        'meters': ['4/4', '2/4'],
        'bpm': (108, 128),
        'lead': 12,
        'pad': 0,
        'bass': 33,
        'perc': True,
        'tags': 'cheerful children song, bright major key, simple singable melody, ukulele, glockenspiel, hand claps, warm acoustic',
    },
    'playful': {
        'label': 'Playful',
        'modes': ['major_pentatonic', 'major'],
        'meters': ['4/4', '2/4'],
        'bpm': (116, 138),
        'lead': 13,
        'pad': 24,
        'bass': 33,
        'perc': True,
        'tags': 'playful nursery rhyme, bouncy rhythm, xylophone, marimba, light percussion, upbeat',
    },
    'marching': {
        'label': 'Marching',
        'modes': ['major'],
        'meters': ['4/4', '2/4'],
        'bpm': (104, 120),
        'lead': 56,
        'pad': 61,
        'bass': 58,
        'perc': True,
        'tags': 'happy marching song for children, steady snare, brass band, strong downbeat, parade feel',
    },
    'gentle': {
        'label': 'Gentle',
        'modes': ['major', 'major_pentatonic'],
        'meters': ['3/4', '6/8', '4/4'],
        'bpm': (76, 96),
        'lead': 10,
        'pad': 89,
        'bass': 32,
        'perc': False,
        'tags': 'gentle childrens song, soft acoustic guitar, warm music box, calm and reassuring, slow tempo',
    },
    'lullaby': {
        'label': 'Lullaby',
        'modes': ['major', 'major_pentatonic'],
        'meters': ['6/8', '3/4'],
        'bpm': (58, 76),
        'lead': 10,
        'pad': 52,
        'bass': 32,
        'perc': False,
        'tags': 'tender lullaby, music box, very slow, dreamy, sleepy, minimal instrumentation',
    },
    'silly': {
        'label': 'Silly',
        'modes': ['major_pentatonic', 'mixolydian'],
        'meters': ['4/4', '2/4'],
        'bpm': (120, 142),
        'lead': 79,
        'pad': 21,
        'bass': 33,
        'perc': True,
        'tags': 'silly funny childrens song, comedic, honky tonk piano, kazoo, wood block, cartoon energy',
    },
    'curious': {
        'label': 'Curious',
        'modes': ['major', 'major_pentatonic'],
        'meters': ['4/4', '3/4'],
        'bpm': (96, 116),
        'lead': 11,
        'pad': 4,
        'bass': 33,
        'perc': True,
        'tags': 'curious exploring childrens song, vibraphone, gentle pizzicato strings, wondering mood, light',
    },
    # The cinematic family's single mood. It is deliberately WIDE — every mode,
    # meter and tempo the thirteen cues between them ask for — because in this
    # family the STYLE is the colour and the mood is only the fallback the
    # SoundFont path needs. GM 48/48/43 (string ensemble over contrabass) is the
    # one patch trio that is not embarrassing behind any of the thirteen; the
    # sampled library named in each style's `voices` is the real instrumentation.
    'cinematic': {
        'label': 'Cinematic',
        'modes': ['major', 'natural_minor', 'mixolydian', 'minor_pentatonic'],
        'meters': ['4/4', '3/4', '6/8', '2/4'],
        'bpm': (50, 176),
        'lead': 48,
        'pad': 48,
        'bass': 43,
        'perc': False,
        'tags': 'cinematic instrumental score',
    },
}
