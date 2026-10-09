# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""cinematic.py — The cinematic family: its style table, family registry and CLAP captions.

Moved verbatim out of ``kids_music_theory.py`` (original lines 691-1096).
"""

from __future__ import annotations


from zyg_workflows.kids_music_theory.styles import STYLES


# ── The cinematic family ─────────────────────────────────────────────────────
#
# THIRTEEN CUES THAT ARE PLAYED, NOT SUNG. Everything the children's table
# carries for a singer is absent here and everything an arranger needs is
# present instead:
#
#   sung=False        there is no lyric, no singer and no vocal gate. It is a
#                     field rather than an omission because _normalise_brief
#                     FORCES it off — a cinematic brief that asks to be sung is
#                     a caller error, recorded as `sung_forced_off` rather than
#                     quietly honoured into an unrenderable plan.
#   age_band          always the 'cinematic' band: an instrument's range, not a
#                     child's. Named in _normalise_brief, not per style, because
#                     a style that could pick its own band could pick a wrong one.
#   voices            lead/pad/bass, as in the children's table, from the SAME
#                     sampled vocabulary (melody_sampler.VOICES) — the test
#                     asserts every name here resolves there.
#   extra             the FOURTH part, which the children's family has no use
#                     for. 'voice' names the instrument, 'role' says what it
#                     plays against the melody:
#                       double    the melody an octave away (thickens the tune)
#                       counter   a slow second line, chord tones on 1 and 3
#                       ostinato  a repeating 8th-note arpeggio of the bar
#                       arpeggio  a broken chord in the metre's own lilt
#                     The arranger (melody_sampler) owns the realisation; this
#                     table only commissions it.
#   bpm               a per-style WINDOW, not a mood's. Thirteen cues that span
#                     58 bpm (Sad) to 168 (Chase) cannot share one tempo range,
#                     which is why the single 'cinematic' mood is deliberately
#                     wide and the style narrows it.
#
# No `look`, `burst_motifs` or `fill_motifs`: THE CINEMATIC FAMILY HAS NO
# PICTURE LEG. A cue is audio. Adding empty motif lists here would advertise a
# video path that does not exist.
CINEMATIC_FAMILY = 'cinematic'

CINEMATIC_STYLES = {
    'cheerful': {
        'label': 'Cheerful',
        'family': CINEMATIC_FAMILY,
        'shelf': 'cheerful',
        'mood': 'cinematic',
        'mode': 'major',
        'meter': '4/4',
        'bpm': (112, 132),
        'form': 'ABAB',
        'seconds': 60,
        'sung': False,
        'perc': False,
        'voices': {'lead': 'flute', 'pad': 'strings_pizz', 'bass': 'double_bass_pizz'},
        'extra': {'voice': 'glockenspiel', 'role': 'double'},
        'ace_tags': ('cheerful orchestral piece, flute, pizzicato strings, glockenspiel, bright, light, playful score'),
        'clap_pos': ['a cheerful orchestral piece', 'light playful film music', 'bright instrumental score'],
    },
    'sad': {
        'label': 'Sad',
        'family': CINEMATIC_FAMILY,
        'shelf': 'sad',
        'mood': 'cinematic',
        'mode': 'natural_minor',
        'meter': '4/4',
        'bpm': (58, 72),
        'form': 'AABA',
        'seconds': 75,
        'sung': False,
        'perc': False,
        'voices': {'lead': 'cello', 'pad': 'strings_sus', 'bass': 'double_bass'},
        'extra': {'voice': 'piano', 'role': 'counter'},
        'ace_tags': ('sad emotional film score, solo cello, soft strings, piano, slow, mournful, cinematic'),
        'clap_pos': ['a sad orchestral piece', 'slow mournful film music', 'emotional instrumental score'],
    },
    'heroic': {
        'label': 'Heroic',
        'family': CINEMATIC_FAMILY,
        'shelf': 'heroic',
        'mood': 'cinematic',
        'mode': 'major',
        'meter': '4/4',
        'bpm': (96, 116),
        'form': 'AABA',
        'seconds': 70,
        'sung': False,
        'perc': False,
        'voices': {'lead': 'french_horn', 'pad': 'strings_sus', 'bass': 'double_bass'},
        'extra': {'voice': 'trumpet', 'role': 'double'},
        'ace_tags': ('heroic orchestral theme, french horns, trumpets, soaring strings, bold, triumphant, cinematic'),
        'clap_pos': ['a heroic orchestral theme', 'triumphant brass film music', 'grand instrumental score'],
    },
    'tavern': {
        'label': 'Tavern',
        'family': CINEMATIC_FAMILY,
        'shelf': 'tavern',
        'mood': 'cinematic',
        'mode': 'mixolydian',
        'meter': '6/8',
        'bpm': (108, 132),
        'form': 'AABA',
        'seconds': 60,
        'sung': False,
        'perc': False,
        'voices': {'lead': 'recorder_alto', 'pad': 'lute', 'bass': 'cello_pizz'},
        'extra': {'voice': 'harpsichord', 'role': 'counter'},
        'ace_tags': ('medieval tavern music, recorder, lute, harpsichord, lively jig, folk, acoustic'),
        'clap_pos': [
            'medieval folk dance music',
            'lively tavern music with lute and recorder',
            'renaissance instrumental',
        ],
    },
    'storytime': {
        'label': 'Storytime',
        'family': CINEMATIC_FAMILY,
        'shelf': 'storytime',
        'mood': 'cinematic',
        'mode': 'major',
        'meter': '3/4',
        'bpm': (80, 96),
        'form': 'ABAC',
        'seconds': 70,
        'sung': False,
        'perc': False,
        'voices': {'lead': 'oboe', 'pad': 'harp', 'bass': 'cello'},
        'extra': {'voice': 'piano', 'role': 'counter'},
        'ace_tags': ('gentle storytelling score, oboe, harp, cello, warm, wondering, cinematic'),
        'clap_pos': ['a gentle orchestral piece', 'warm magical film music', 'tender instrumental score'],
    },
    'sonata': {
        'label': 'Sonata',
        'family': CINEMATIC_FAMILY,
        'shelf': 'sonata',
        'mood': 'cinematic',
        'mode': 'major',
        'meter': '4/4',
        'bpm': (88, 108),
        'form': 'AABA',
        'seconds': 80,
        'sung': False,
        'perc': False,
        'voices': {'lead': 'grand_piano', 'pad': 'grand_piano', 'bass': 'grand_piano'},
        'extra': {'voice': 'violin', 'role': 'counter'},
        'ace_tags': ('classical sonata, solo piano, violin, elegant, expressive, chamber music'),
        'clap_pos': [
            'a classical piano sonata',
            'chamber music with piano and violin',
            'elegant classical instrumental',
        ],
    },
    'suspense': {
        'label': 'Suspense',
        'family': CINEMATIC_FAMILY,
        'shelf': 'suspense',
        'mood': 'cinematic',
        'mode': 'natural_minor',
        'meter': '4/4',
        'bpm': (66, 84),
        'form': 'ABAB',
        'seconds': 70,
        'sung': False,
        'perc': False,
        # ARRANGEMENT, not captions, is what moved this cue through the gate.
        # The old scoring (clarinet lead / strings_trem pad / double_bass /
        # harp:ostinato) rendered a -20 dBFS sparse tremolo texture that CLAP
        # filed under 'pop song with vocals': 0.3795 mean over 5 repeats,
        # 0/5 passes, and no caption triple could reach 0.525 because the best
        # single caption carried only 0.22 of the softmax mass. Three
        # arrangements were measured against the SAME captions
        # (tools/measure_cinematic_clap.py --phase cands --repeats 5, two
        # tonics): bassoon/strings_sus/double_bass/harp 0.3795 & 0.4713 (1/10
        # passes), french_horn/strings_sus_low/contrabass_pizz/clarinet 0.4626
        # & 0.4018 (3/10), and the one below 0.5818 & 0.6229 — 10/10 passes.
        # A sustained low-string bed with an arco cello line and a pizzicato
        # contrabass reads as 'orchestral' where the tremolo did not.
        'voices': {'lead': 'cello', 'pad': 'strings_sus_low', 'bass': 'contrabass_pizz'},
        'extra': {'voice': 'vibraphone', 'role': 'counter'},
        'ace_tags': (
            'suspenseful film score, solo cello, low sustained strings, '
            'pizzicato contrabass, vibraphone, tense, dark, cinematic'
        ),
        # MEASURED, not written to taste: probing 37 captions one at a time
        # (--phase probe) 'a quiet orchestral piece' ranked first on this cue,
        # and this triple is the most selective set on disk — it scores 0.04 on
        # the chase render and 0.26 on cheerful. Unchanged across the
        # arrangement change on purpose, so the numbers above compare like
        # with like.
        'clap_pos': ['a quiet orchestral piece', 'a slow quiet string piece', 'suspense music from a thriller film'],
    },
    'romance': {
        'label': 'Romance',
        'family': CINEMATIC_FAMILY,
        'shelf': 'romance',
        'mood': 'cinematic',
        'mode': 'major',
        'meter': '3/4',
        'bpm': (72, 88),
        'form': 'AABA',
        'seconds': 75,
        'sung': False,
        'perc': False,
        'voices': {'lead': 'violin', 'pad': 'strings_sus', 'bass': 'cello'},
        'extra': {'voice': 'piano', 'role': 'arpeggio'},
        'ace_tags': ('romantic film score, solo violin, warm strings, piano arpeggios, tender, sweeping, cinematic'),
        'clap_pos': ['a gentle orchestral piece', 'warm magical film music', 'tender instrumental score'],
    },
    'wonder': {
        'label': 'Wonder & Discovery',
        'family': CINEMATIC_FAMILY,
        'shelf': 'wonder',
        'mood': 'cinematic',
        'mode': 'major',
        'meter': '4/4',
        'bpm': (84, 100),
        'form': 'ABAC',
        'seconds': 75,
        'sung': False,
        'perc': False,
        'voices': {'lead': 'glockenspiel', 'pad': 'harp', 'bass': 'strings_sus_low'},
        'extra': {'voice': 'flute', 'role': 'double'},
        'ace_tags': ('wonder and discovery score, glockenspiel, harp, flute, strings, magical, bright, cinematic'),
        'clap_pos': ['a gentle orchestral piece', 'warm magical film music', 'tender instrumental score'],
    },
    'mystery': {
        'label': 'Mystery',
        'family': CINEMATIC_FAMILY,
        'shelf': 'mystery',
        'mood': 'cinematic',
        'mode': 'minor_pentatonic',
        'meter': '4/4',
        'bpm': (70, 86),
        'form': 'ABAB',
        'seconds': 70,
        'sung': False,
        'perc': False,
        'voices': {'lead': 'oboe', 'pad': 'harpsichord', 'bass': 'contrabass_pizz'},
        'extra': {'voice': 'vibraphone', 'role': 'counter'},
        'ace_tags': (
            'mysterious film score, oboe, harpsichord, vibraphone, pizzicato bass, sparse, curious, cinematic'
        ),
        # This style used to share Suspense's triple and failed the render gate
        # with it (0.041-0.152 over three calls, beaten by 'pop song with
        # vocals' at 0.86). The captions below name the INSTRUMENTS and score
        # 0.9658 minimum on the same renders — the audio was never the problem
        # here, 'a suspenseful film score' simply is not what an oboe over a
        # harpsichord sounds like. Measured with
        # tools/measure_cinematic_clap.py --phase cands (set M1).
        'clap_pos': [
            'mysterious orchestral film score',
            'slow eerie instrumental music with oboe and harpsichord',
            'sparse curious cinematic underscore',
        ],
    },
    'chase': {
        'label': 'Chase',
        'family': CINEMATIC_FAMILY,
        'shelf': 'chase',
        'mood': 'cinematic',
        'mode': 'natural_minor',
        'meter': '4/4',
        'bpm': (140, 168),
        'form': 'ABAB',
        'seconds': 60,
        'sung': False,
        'perc': False,
        'voices': {'lead': 'trumpet', 'pad': 'strings_spic', 'bass': 'contrabass_pizz'},
        'extra': {'voice': 'marimba', 'role': 'ostinato'},
        'ace_tags': ('fast chase scene score, spiccato strings, trumpet, marimba ostinato, driving, urgent, cinematic'),
        'clap_pos': [
            'a fast action film score',
            'driving urgent orchestral music',
            'exciting instrumental chase music',
        ],
    },
    'melancholy': {
        'label': 'Melancholy',
        'family': CINEMATIC_FAMILY,
        'shelf': 'melancholy',
        'mood': 'cinematic',
        'mode': 'natural_minor',
        'meter': '3/4',
        'bpm': (60, 76),
        'form': 'AABA',
        'seconds': 75,
        'sung': False,
        'perc': False,
        'voices': {'lead': 'piano', 'pad': 'strings_sus', 'bass': 'cello'},
        'extra': {'voice': 'oboe', 'role': 'counter'},
        'ace_tags': ('melancholic piano score, soft strings, oboe, slow waltz, wistful, cinematic'),
        'clap_pos': ['a sad orchestral piece', 'slow mournful film music', 'emotional instrumental score'],
    },
    'triumph': {
        'label': 'Triumphant Finale',
        'family': CINEMATIC_FAMILY,
        'shelf': 'triumph',
        'mood': 'cinematic',
        'mode': 'major',
        'meter': '4/4',
        'bpm': (100, 120),
        'form': 'AAB',
        'seconds': 60,
        'sung': False,
        'perc': False,
        'voices': {'lead': 'trumpet', 'pad': 'organ_full', 'bass': 'tuba'},
        'extra': {'voice': 'strings_sus', 'role': 'double'},
        'ace_tags': ('triumphant finale, brass fanfare, organ, full strings, grand, victorious, cinematic'),
        # KEPT after measurement, against two challengers. This triple scored
        # 0.7642 minimum over four calls on the render that once reported
        # 0.4697; a fanfare-and-organ set ('triumphant orchestral fanfare with
        # brass and organ', …) collapsed to 0.1833 and an instrument-naming one
        # to 0.3854. The 0.4697 in the manifest was a DRAW, not a property:
        # laion/clap-htsat-fused fuses randomly truncated chunks, so the same
        # file against the same captions scores 0.47-0.94 call to call.
        'clap_pos': ['a heroic orchestral theme', 'triumphant brass film music', 'grand instrumental score'],
    },
}

# The four things `extra.role` may say. Named so a typo is a KeyError here
# rather than a silently missing fourth part in the arrangement.
EXTRA_ROLES = ('double', 'counter', 'ostinato', 'arpeggio')

STYLE_FAMILIES = {
    'children': {'label': "Children's Music", 'styles': STYLES},
    'cinematic': {'label': 'Cinematic', 'styles': CINEMATIC_STYLES},
}


def style_lookup(key, family=None):
    """``(family, entry)`` for a style key, or ``(None, None)``.

    The two families are kept as SEPARATE dicts — not merged into one namespaced
    table — because everything downstream already reads `brief['style']` as a
    bare key and a merged 'cinematic/chase' would break every one of those
    readers. The keys happen to be unique across the two families with ONE
    exception, 'storytime', which exists in both and means different things:
    a sung preschool song and a 3/4 oboe-and-harp cue. That collision is why
    `family` exists on the brief. Without one the children's table wins, which
    is the pre-existing behaviour every current caller depends on.
    """
    if not isinstance(key, str) or not key:
        return (None, None)
    if family in STYLE_FAMILIES:
        entry = STYLE_FAMILIES[family]['styles'].get(key)
        return (family, entry) if entry else (None, None)
    for fam, spec in STYLE_FAMILIES.items():  # children first, by order
        entry = spec['styles'].get(key)
        if entry:
            return (fam, entry)
    return (None, None)


# The placeholder `_normalise_brief` fills an empty theme with. Named because
# downstream code needs to tell "the operator asked for a song about this" from
# "nobody said" — the cinematic ACE caption only carries a subject when one was
# actually given.
DEFAULT_THEME = 'a happy little song'

# What the CLAP gate compares a score render against when no style is set.
DEFAULT_CLAP_POS = ["a cheerful children's song", 'happy simple music for kids', 'nursery rhyme melody']

# And what it must NOT hear. Family-aware for the same reason the positives are:
# 'horror drone' is a real failure in a nursery rhyme and an ordinary colour in a
# Suspense cue, so scoring a cinematic render against the children's negatives
# would fail the cue for being what it was commissioned to be. What stays common
# to both is the pair that means "this is not music at all" (silence, spoken
# word) plus the two the workflow never wants (heavy metal, angry shouting); what
# the cinematic list adds is 'pop song with vocals', because an instrumental cue
# that grew a voice is the one content failure this family can have.
CLAP_NEGATIVES = {
    'children': ['heavy metal', 'horror drone', 'angry shouting', 'spoken word with no music', 'silence'],
    'cinematic': ['heavy metal', 'spoken word with no music', 'silence', 'angry shouting', 'pop song with vocals'],
}

# The lyric shapes a brief may ask for. 'counting' arrived with the style layer
# and behaves like 'facts' musically (one phrase, tiled — form AAAA) while the
# prompt rule is different, which is why it is a third mode and not a flag.
LYRICS_MODES = {
    'theme': 'Theme (a song about the topic)',
    'facts': 'Facts (subject + a list of things it has/does)',
    'counting': 'Counting (one, two, three … each line advances)',
}


def style_for_plan(plan):
    """The style entry a composed plan was built under, or None.

    Family-aware: the plan carries the family it was composed under, so a
    cinematic 'storytime' resolves to the cue and not to the preschool song.
    """
    plan = plan or {}
    fam = plan.get('family') or (plan.get('brief') or {}).get('family')
    return style_lookup(plan.get('style'), fam)[1]


def clap_captions(style_key, family='children'):
    """Positive CLAP captions for a style key (the default list without one).

    `family` defaults to 'children' rather than to None so that a caller who
    does not know about families cannot be handed the cinematic captions by
    accident through the 'storytime' collision. Every caller that HAS a family
    passes it.
    """
    s = style_lookup(style_key, family)[1]
    return list(s['clap_pos']) if s else list(DEFAULT_CLAP_POS)


def clap_negatives(family='children'):
    """Negative CLAP captions for a family (the children's list by default)."""
    return list(CLAP_NEGATIVES.get(family) or CLAP_NEGATIVES['children'])
