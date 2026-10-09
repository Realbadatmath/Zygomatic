# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""styles.py — The children's style table and how long a children's song is.

Moved verbatim out of ``kids_music_theory.py`` (original lines 285-689).
"""

from __future__ import annotations


# ── Styles ───────────────────────────────────────────────────────────────────
#
# A STYLE is what the operator actually picks on the Melodies board ("Lullaby",
# "Counting & Alphabet"). It sits ABOVE the mood: it fixes a coherent set of
# defaults — mood, age band, form, metre, length, lyric mode — plus the things
# a mood cannot express, because a mood is a musical adjective and a style is an
# editorial format:
#
#   voices      the SAMPLED instrument library's voice keys (lead/pad/bass).
#               MOODS[...] lead/pad/bass stay as they are — those are General
#               MIDI programs for the SoundFont path, and both paths coexist.
#   ace_tags    replaces MOODS[mood]['tags'] in the ACE-Step prompt, because
#               the caption has to name the same instruments the sampler plays.
#   lyric_hint  one sentence appended to the lyric prompt's Rules; this is what
#               makes "Sing-along" a call-and-response and "Animals" an animal
#               song rather than two songs that differ only in tempo.
#   look        the colour clause of the picture leg (the flat-2D BASE_STYLE is
#               unchanged — a style tints the palette, it does not restyle).
#   clap_pos    the positive captions of the score-render CLAP gate: a lullaby
#               that is measured against "a cheerful children's song" is being
#               graded on the wrong question.
#   burst/fill_motifs   which video motifs the picture leg may draw on.
#
# EVERY EXPLICIT OPERATOR VALUE STILL WINS over the style, exactly as an explicit
# mood already wins over an age band's default: a style is a set of defaults, not
# a lock. A brief without `style` behaves exactly as it did before this table
# existed — see _normalise_brief, which adds no style keys at all in that case.
STYLE_FAMILY = 'children'

# ── How long a children's song is (2026-10-02, operator) ─────────────────────
#
# A minute was the shipped length of every song this workflow has ever made, and
# it is too short for the channel: the form barely states itself before it ends.
# Every children's-music FORMAT now lands in this band, and a format's own
# `seconds` below is its place in it — a nursery rhyme is short by nature, a
# lullaby is long by nature, and neither is a minute any more.
#
# The band is a DEFAULT, not a lock: an explicit operator value still wins and is
# only clamped to what the renderer can do (SONG_SECONDS_HARD), exactly as every
# other style default behaves. The unattended batchers — bp_melody_daily,
# bp_jackmona_daily — draw from the band, so everything the box produces on its
# own is inside it.
#
# WHAT THE CEILING IS MADE OF. ACE-Step takes the length as a node input and the
# cap was an env default of 180 s; 210 is the new one, and the ACE leg is the only
# place that number has to be true. The picture leg follows for free: one picture
# per clip means a 210 s song is ~42 pictures of ~5 s, so a song three times
# longer costs about the same number of pictures a minute did before the cadence
# changed (54).
SONG_SECONDS = (130.0, 210.0)
SONG_SECONDS_DEFAULT = 150.0  # the middle of the measured-clean part; see song_seconds
# What the renderer will accept, wider than the editorial band so an explicit
# short brief (a 25 s test render, a 45 s jingle) still runs.
SONG_SECONDS_HARD = (20.0, 210.0)


# WHAT THE BAND MEASURES LIKE (2026-10-02, four audio-only renders, same theme,
# adult_female, want_video off). The number that matters is whether ACE-Step
# actually SINGS the lyric it was given, because the composer hands it one line
# per half-section and a longer song is more lines:
#
#     asked   lines  sung  missing          severity  repairs  audio leg
#      60 s     12   11-12  0-1                 0-6      0-2     ~120 s
#     130 s     30   30     none                  0        0        74 s
#     170 s     40   38     2 (scattered)        12        5       560 s
#     210 s     50   44     6 — THE LAST FIVE    36        3       640 s
#
# At 210 s the final ~20 s has no vocal at all: the LM runs out of adherence
# before the lyric runs out of lines, and the repair leg spends its whole budget
# repainting. 130 s sang every line with no repair at all and in a twelfth of the
# time. So the ROTATION stays in the measured-clean part of the band while the
# band itself is what the operator asked for — an explicit 210 still renders, and
# the top of the band becomes safe the day the lyric leg repeats its verses
# instead of writing fifty distinct lines (see the note in _section_map).
_SONG_SECONDS_STEPS = (130.0, 150.0, 170.0)


def song_seconds(n=None):
    """A length inside the band. `n` rotates deterministically through it so a
    series does not ship a dozen songs of identical length; None gives the default.

    Three steps rather than a continuous draw: length is a musical decision and
    the composer rounds to whole bars anyway, so three clear formats (short,
    middle, long) are more use than a spread of arbitrary seconds.
    """
    if n is None:
        return SONG_SECONDS_DEFAULT
    return float(_SONG_SECONDS_STEPS[int(n) % len(_SONG_SECONDS_STEPS)])


# Not a table entry with a flag: an EXCLUDED style must not be constructible by
# accident. It is named here so the UI can say why it is absent instead of
# looking like an oversight, and so nothing downstream can select it.
EXCLUDED_STYLES = {
    'dance': 'Action & Dance-along — excluded by operator decision 2026-09-06',
}

# `meter: None` means "keep the mood's own default metre" — the styles that name
# one do so because the metre IS the style (6/8 lilt for a lullaby, 2/4 for a
# nursery rhyme, 3/4 for the bedtime waltz).
# THE BASS IS CHOSEN FOR ITS DUTY CYCLE, NOT ITS TIMBRE. Measured 2026-09-06
# with tools/measure_style_margins.py: the melody-minus-bass RMS margin that
# kids_music_service.mix_balance gates on (>= MIX_MARGIN_MIN_DB) is decided by
# how long each part is SOUNDING, not by how loud it is set. A short plucked or
# struck lead against a sustaining arco bass loses that comparison however it is
# gained — sleeptime's kalimba over an arco cello measured -10.6 dB, and no
# amount of per-voice calibration recovers it, because the cello is simply on
# for most of the bar and the kalimba is not. Hence the plucked basses:
# double_bass_pizz and cello_pizz. Swap one back to 'cello' or 'bass_electric'
# and re-run the tool before believing it still ships.
#
# NOTE: 'glockenspiel' is rendered with voice transpose +12 — its samples start
# at G4 (MIDI 67), so an untransposed melody in the toddler band would fall off
# the bottom of the sample set. The sampler owns that mapping; this table only
# names the voice. No children's style leads on it today (Learning did, and lost
# 10 dB of margin to it), but the mapping stays for anyone who names it.
STYLES = {
    'playtime': {
        'label': 'Playtime',
        'family': STYLE_FAMILY,
        'shelf': 'playtime',
        'mood': 'playful',
        'moods': ['playful', 'happy', 'silly'],
        'age_band': 'preschool',
        'form': 'ABAB',
        'meter': None,
        'seconds': 150,
        'sung': True,
        'lyrics_mode': 'theme',
        'lyric_hint': ('it is a song to play along to: repeat one action word (hop, clap, spin) every second line.'),
        'voices': {'lead': 'xylophone', 'pad': 'guitar_nylon', 'bass': 'double_bass_pizz'},
        'perc': True,
        'ace_tags': 'playful children song, bouncy, xylophone, nylon guitar, hand claps, upbeat',
        'look': 'bright candy colours, bouncy shapes, sunny daylight',
        'burst_motifs': ['count_up', 'shapes', 'colours', 'toys'],
        'fill_motifs': ['journey', 'toys', 'animals', 'weather', 'peekaboo'],
        'clap_pos': ["a cheerful children's song", 'happy simple music for kids', 'nursery rhyme melody'],
    },
    'sleeptime': {
        'label': 'Sleeptime',
        'family': STYLE_FAMILY,
        'shelf': 'sleeptime',
        'mood': 'lullaby',
        'moods': ['lullaby', 'gentle'],
        'age_band': 'toddler',
        'form': 'AABA',
        'meter': '6/8',
        'seconds': 180,
        'sung': True,
        'lyrics_mode': 'theme',
        'lyric_hint': ('slow and soothing: soft sounds, the day winding down, every line ends gently.'),
        # WAS kalimba/harp/cello and measured -10.6 dB — the worst margin in the
        # table. The kalimba's plucked note is over in a fraction of a beat while
        # the arco cello holds the bar, so the tune sat under its own bass and an
        # ACE-less run shipped nothing. The alto recorder sustains with the pad
        # instead of pecking at it, and the pizzicato cello keeps the low end
        # without holding it: +23.0 dB, and softer than what it replaces.
        'voices': {'lead': 'recorder_alto', 'pad': 'harp', 'bass': 'cello_pizz'},
        'perc': False,
        'ace_tags': ('very soft lullaby, alto recorder, harp, pizzicato cello, slow, dreamy, minimal'),
        'look': 'soft dusky pastel colours, calm deep blue evening, tiny friendly stars',
        'burst_motifs': ['count_down', 'colours'],
        'fill_motifs': ['journey', 'grow', 'weather', 'peekaboo'],
        'clap_pos': [
            'a gentle lullaby for children',
            'soft calm music for a sleeping child',
            'slow soothing nursery melody',
        ],
    },
    'storytime': {
        'label': 'Storytime',
        'family': STYLE_FAMILY,
        'shelf': 'storytime',
        'mood': 'curious',
        'moods': ['curious', 'gentle', 'happy'],
        'age_band': 'preschool',
        'form': 'ABAC',
        'meter': None,
        'seconds': 190,
        'sung': True,
        'lyrics_mode': 'theme',
        'lyric_hint': ('tell one tiny story with a beginning, a middle and a happy end, one character throughout.'),
        'voices': {'lead': 'recorder', 'pad': 'guitar_nylon', 'bass': 'double_bass_pizz'},
        'perc': True,
        'ace_tags': ('gentle storytelling children song, recorder, nylon guitar, light percussion, wondering mood'),
        'look': 'warm storybook colours, soft green hills, golden afternoon light',
        'burst_motifs': ['toys', 'animals', 'shapes'],
        'fill_motifs': ['journey', 'animals', 'peekaboo', 'grow'],
        'clap_pos': ["a gentle children's song", 'warm simple music for kids', 'nursery rhyme melody'],
    },
    'learning': {
        'label': 'Learning',
        'family': STYLE_FAMILY,
        'shelf': 'learning',
        'mood': 'happy',
        'moods': ['happy', 'curious', 'playful'],
        'age_band': 'preschool',
        'form': 'AAAA',
        'meter': None,
        'seconds': 150,
        'sung': True,
        'lyrics_mode': 'facts',
        # 'facts' already carries its own prompt shape; a second instruction here
        # would only fight it.
        'lyric_hint': '',
        # WAS glockenspiel/piano/bass_electric and measured +2.7 dB — under the
        # gate. Two sustaining parts (piano pad, electric bass) against a struck
        # glockenspiel that rings and stops. The xylophone is the brighter,
        # drier mallet of the two and reads as "educational" just as well; the
        # nylon guitar comps rather than sustains and the pizzicato double bass
        # marks the beat instead of holding it: +13.4 dB.
        'voices': {'lead': 'xylophone', 'pad': 'guitar_nylon', 'bass': 'double_bass_pizz'},
        'perc': True,
        'ace_tags': (
            'bright educational children song, xylophone, nylon guitar, '
            'pizzicato double bass, simple repeated hook, clear rhythm'
        ),
        'look': 'clean bright primary colours, plain white-blue background, tidy shapes',
        'burst_motifs': ['count_up', 'shapes', 'colours'],
        'fill_motifs': ['colours', 'shapes', 'toys', 'grow'],
        'clap_pos': ["a cheerful children's song", 'happy simple music for kids', 'nursery rhyme melody'],
    },
    'lullaby': {
        'label': 'Lullaby',
        'family': STYLE_FAMILY,
        'shelf': 'lullaby',
        'mood': 'lullaby',
        'moods': ['lullaby'],
        'age_band': 'toddler',
        'form': 'AABA',
        'meter': '6/8',
        'seconds': 200,
        'sung': True,
        'lyrics_mode': 'theme',
        'lyric_hint': ('a lullaby: hush, sleep, stars, moon, soft; no exclamation, no action words.'),
        # Bass only: 'cello' (arco) left this at +4.08 dB — over the gate but
        # inside its noise. The sustained string pad is what makes it a lullaby
        # and is kept; the cello is plucked instead, which takes nothing away
        # from the bed and gives the chimes room: +15.7 dB.
        'voices': {'lead': 'hand_chimes', 'pad': 'strings_sus', 'bass': 'cello_pizz'},
        'perc': False,
        'ace_tags': ('tender lullaby, chimes, soft strings, pizzicato cello, very slow, sleepy, hushed'),
        'look': 'soft lavender and midnight blue, gentle glowing moon, sleepy warm light',
        'burst_motifs': ['count_down'],
        'fill_motifs': ['journey', 'weather', 'grow', 'peekaboo'],
        'clap_pos': [
            'a gentle lullaby for children',
            'soft calm music for a sleeping child',
            'slow soothing nursery melody',
        ],
    },
    'nursery': {
        'label': 'Nursery Rhyme',
        'family': STYLE_FAMILY,
        'shelf': 'nursery',
        'mood': 'happy',
        'moods': ['happy', 'playful', 'marching'],
        # SPECIFIED AS 2/4 AND DELIVERED AS THE MOOD DEFAULT (4/4). Measured
        # 2026-09-06, all 48 seeds identical: 2/4 at this style's defaults gives
        # 2.29 notes/s against the toddler cap of 1.80, so every candidate fails
        # the density gate. It is not the style's fault and no seed or tempo
        # inside the mood's range escapes it (2/4 at 84 bpm is the first passing
        # tempo, below the happy mood's 108 floor): _syllable_targets budgets one
        # lyric line per TWO BARS whatever the metre, and two 2/4 bars are half
        # the seconds of two 4/4 bars, so the same line lands at twice the
        # density. Restore '2/4' here once that budget is metre-aware; the
        # marching pulse is carried by the ace_tags meanwhile.
        'age_band': 'toddler',
        'form': 'AABA',
        'meter': None,
        'seconds': 135,
        'sung': True,
        'lyrics_mode': 'theme',
        'lyric_hint': (
            'a traditional nursery-rhyme shape: strong end rhymes, one refrain line repeated at least three times.'
        ),
        # Bass only: even a pizzicato double bass left this at +4.07 dB, because
        # the ukulele's lead is as short as the bass note is. The cello pizz sits
        # an octave up from the double bass and decays faster still: +10.0 dB,
        # with the ukulele — which IS the style — untouched.
        'voices': {'lead': 'ukulele', 'pad': 'piano', 'bass': 'cello_pizz'},
        'perc': True,
        'ace_tags': ('classic nursery rhyme, ukulele, piano, pizzicato cello, marching pulse, cheerful, simple'),
        'look': 'bright sunny primary colours, clear blue sky, warm daylight',
        'burst_motifs': ['count_up', 'animals', 'toys'],
        'fill_motifs': ['journey', 'toys', 'animals', 'peekaboo'],
        'clap_pos': ["a cheerful children's song", 'happy simple music for kids', 'nursery rhyme melody'],
    },
    'counting': {
        'label': 'Counting & Alphabet',
        'family': STYLE_FAMILY,
        'shelf': 'counting',
        'mood': 'playful',
        'moods': ['playful', 'happy'],
        'age_band': 'toddler',
        'form': 'AAAA',
        'meter': None,
        'seconds': 140,
        'sung': True,
        'lyrics_mode': 'counting',
        'lyric_hint': (
            'COUNT: each line advances by one — one, two, three, '
            'four, five (or A, B, C, D, E if the theme is letters); '
            'spell numbers as words; the last line repeats the whole '
            'count.'
        ),
        'voices': {'lead': 'marimba', 'pad': 'guitar_steel', 'bass': 'bass_electric'},
        'perc': True,
        'ace_tags': ('counting song for children, marimba, acoustic guitar, steady beat, playful, repetitive hook'),
        'look': 'bold flat primary colours, plain pale background, big clear shapes',
        'burst_motifs': ['count_up', 'count_down'],
        'fill_motifs': ['shapes', 'colours', 'toys'],
        'clap_pos': ["a cheerful children's song", 'happy simple music for kids', 'nursery rhyme melody'],
    },
    'singalong': {
        'label': 'Sing-along',
        'family': STYLE_FAMILY,
        'shelf': 'singalong',
        'mood': 'happy',
        'moods': ['happy', 'marching', 'silly'],
        'age_band': 'preschool',
        'form': 'AAB',
        'meter': None,
        'seconds': 150,
        'sung': True,
        'lyrics_mode': 'theme',
        'lyric_hint': ('call-and-response: every second line is the same short shout-back refrain (max 4 words).'),
        'voices': {'lead': 'harmonica', 'pad': 'guitar_steel', 'bass': 'double_bass_pizz'},
        'perc': True,
        'ace_tags': ('sing-along children song, harmonica, acoustic guitar, hand claps, call and response, joyful'),
        'look': 'bright flag colours, red yellow and blue, crisp sunny day',
        'burst_motifs': ['colours', 'toys', 'animals'],
        'fill_motifs': ['journey', 'animals', 'toys', 'weather'],
        'clap_pos': ["a cheerful children's song", 'happy simple music for kids', 'nursery rhyme melody'],
    },
    'animals': {
        'label': 'Animal Songs',
        'family': STYLE_FAMILY,
        'shelf': 'animals',
        'mood': 'silly',
        'moods': ['silly', 'playful', 'happy'],
        'age_band': 'preschool',
        'form': 'ABAB',
        'meter': None,
        'seconds': 160,
        'sung': True,
        'lyrics_mode': 'theme',
        'lyric_hint': ('every line names an animal and the sound it makes (moo, baa, quack, woof) as a word.'),
        'voices': {'lead': 'clarinet', 'pad': 'guitar_nylon', 'bass': 'tuba'},
        'perc': True,
        'ace_tags': 'silly animal song for children, clarinet, nylon guitar, tuba, comedic, bouncy',
        'look': 'fresh green meadow colours, bright farmyard, cheerful daylight',
        'burst_motifs': ['animals'],
        'fill_motifs': ['animals', 'journey', 'weather', 'peekaboo'],
        'clap_pos': ["a cheerful children's song", 'happy simple music for kids', 'nursery rhyme melody'],
    },
    'seasons': {
        'label': 'Seasons & Holidays',
        'family': STYLE_FAMILY,
        'shelf': 'seasons',
        'mood': 'gentle',
        'moods': ['gentle', 'happy', 'curious'],
        'age_band': 'preschool',
        'form': 'AABA',
        'meter': None,
        'seconds': 170,
        'sung': True,
        'lyrics_mode': 'theme',
        'lyric_hint': (
            'about a season or a holiday — weather, clothes, food, decorations; no religious figures, no brand names.'
        ),
        'voices': {'lead': 'flute', 'pad': 'harp', 'bass': 'cello'},
        'perc': True,
        'ace_tags': 'warm seasonal children song, flute, harp, cello, gentle, bright, festive',
        'look': 'seasonal palette matching the theme, soft warm light',
        'burst_motifs': ['colours', 'shapes'],
        'fill_motifs': ['weather', 'grow', 'journey', 'colours'],
        'clap_pos': ["a gentle children's song", 'warm simple music for kids', 'nursery rhyme melody'],
    },
    'bedtime': {
        'label': 'Bath & Bedtime Routine',
        'family': STYLE_FAMILY,
        'shelf': 'bedtime',
        'mood': 'gentle',
        'moods': ['gentle', 'lullaby'],
        'age_band': 'toddler',
        'form': 'ABAC',
        'meter': '3/4',
        'seconds': 185,
        'sung': True,
        'lyrics_mode': 'theme',
        'lyric_hint': ('the bedtime routine in order: bath, pyjamas, teeth, story, cuddle, lights out; calm and warm.'),
        'voices': {'lead': 'vibraphone', 'pad': 'piano', 'bass': 'double_bass_pizz'},
        'perc': False,
        'ace_tags': 'calm bedtime routine song, vibraphone, soft piano, slow waltz, warm, reassuring',
        'look': 'warm amber bathroom and bedroom colours, cosy evening lamplight',
        'burst_motifs': ['count_down', 'toys'],
        'fill_motifs': ['journey', 'peekaboo', 'toys', 'grow'],
        'clap_pos': [
            'a gentle lullaby for children',
            'soft calm music for a sleeping child',
            'slow soothing nursery melody',
        ],
    },
}
