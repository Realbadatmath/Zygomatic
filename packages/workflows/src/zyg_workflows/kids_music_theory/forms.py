# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""forms.py — Meters, song forms, chord progressions and their roman numerals.

Moved verbatim out of ``kids_music_theory.py`` (original lines 1295-1364).
"""

from __future__ import annotations


METERS = {
    '4/4': {'label': '4/4 — clapping', 'beats': 4.0, 'strong': (0.0, 2.0), 'grid': 0.5, 'ts': '4'},
    '3/4': {'label': '3/4 — waltz', 'beats': 3.0, 'strong': (0.0,), 'grid': 0.5, 'ts': '3'},
    '2/4': {'label': '2/4 — marching', 'beats': 2.0, 'strong': (0.0,), 'grid': 0.5, 'ts': '2'},
    '6/8': {'label': '6/8 — lilting', 'beats': 3.0, 'strong': (0.0, 1.5), 'grid': 0.5, 'ts': '6'},
}

FORMS = {
    'AABA': {'label': 'AABA (verse · verse · bridge · verse)', 'pattern': ['A', 'A', 'B', 'A']},
    'ABAB': {'label': 'ABAB (verse · chorus)', 'pattern': ['A', 'B', 'A', 'B']},
    'ABAC': {'label': 'ABAC (verse · chorus · verse · tag)', 'pattern': ['A', 'B', 'A', 'C']},
    'AAB': {'label': 'AAB  (call · call · answer)', 'pattern': ['A', 'A', 'B']},
    # Single section letter tiled over every line: no bridge/chorus contrast at
    # all, so every fact rides the SAME melodic phrase (motif_cache in compose()
    # reuses it whenever the syllable count matches). This is what makes a list
    # of facts ("X has Y", "X goes on Z") land as one repeatable hook instead of
    # a verse/chorus song — see [[project-kids-music-workflow]].
    'AAAA': {'label': 'AAAA (facts — one phrase, every line)', 'pattern': ['A']},
}

# One chord per bar.  Diminished triads are deliberately absent from every
# progression: vii° in major and ii° in minor are the two chords whose tones a
# child's ear hears as "wrong note", and nothing in this repertoire needs them.
PROGRESSIONS = {
    'major': [
        [0, 0, 4, 0],  # I  I  V  I     — the nursery default
        [0, 3, 4, 0],  # I  IV V  I
        [0, 4, 5, 3],  # I  V  vi IV
        [0, 5, 3, 4],  # I  vi IV V
        [0, 3, 0, 4],  # I  IV I  V
        [0, 0, 3, 4],  # I  I  IV V
    ],
    'major_b': [  # B-section / bridge colours: start away from home
        [5, 3, 0, 4],  # vi IV I  V
        [3, 4, 0, 0],  # IV V  I  I
        [1, 4, 0, 0],  # ii V  I  I
        [3, 0, 3, 4],  # IV I  IV V
    ],
    'natural_minor': [
        [0, 5, 2, 6],  # i  VI III VII
        [0, 3, 0, 6],  # i  iv i   VII
        [0, 6, 5, 6],  # i  VII VI VII
        [0, 2, 5, 6],  # i  III VI VII
    ],
    'natural_minor_b': [
        [5, 6, 0, 0],  # VI VII i i
        [3, 6, 0, 0],  # iv VII i i
    ],
    'mixolydian': [
        [0, 6, 3, 0],  # I  bVII IV I
        [0, 3, 6, 0],
        [0, 6, 0, 3],
    ],
    'mixolydian_b': [
        [3, 6, 0, 0],
        [6, 3, 0, 0],
    ],
}

# Triad quality per scale degree of the parent scale (index = degree).
QUALITY = {
    'major': ['maj', 'min', 'min', 'maj', 'maj', 'min', 'dim'],
    'natural_minor': ['min', 'dim', 'maj', 'min', 'min', 'maj', 'maj'],
    'mixolydian': ['maj', 'min', 'dim', 'maj', 'min', 'min', 'maj'],
}
ROMAN = {
    'major': ['I', 'ii', 'iii', 'IV', 'V', 'vi', 'vii°'],
    'natural_minor': ['i', 'ii°', 'III', 'iv', 'v', 'VI', 'VII'],
    'mixolydian': ['I', 'ii', 'iii°', 'IV', 'v', 'vi', 'bVII'],
}
