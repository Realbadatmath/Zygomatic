# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""The look and the motif deck — prompts, palettes and the generated motifs.

Moved verbatim out of the old single-file kids_video_service.py (lines 345-708).
"""

from __future__ import annotations

import re
from zyg_workflows import kids_music_theory as T


# ── The look ─────────────────────────────────────────────────────────────────
#
# One style sentence is prefixed to EVERY prompt in a song so the thirty
# pictures read as one film rather than thirty unrelated pictures.  "flat",
# "bold outlines" and "minimal detail" are doing the work the user asked for —
# simple visuals — and the anti-photoreal terms are repeated in the negative
# because a positive alone does not stop a model reaching for photography.

BASE_STYLE = (
    'flat 2D cartoon illustration for young children, children picture-book art, '
    'bold clean dark outlines, simple rounded shapes, large friendly forms, '
    'flat colour fills, minimal detail, plain uncluttered background, '
    'cheerful joyful and wholesome, sweet and gentle, safe for toddlers'
)

# Per-mood palette accent. The mood already chose the music; it chooses the
# colour temperature too, so a lullaby video is not lit like a marching song.
MOOD_LOOK = {
    'happy': 'bright sunny primary colours, clear blue sky, warm daylight',
    'playful': 'bright candy colours, bouncy shapes, sunny daylight',
    'marching': 'bold flag colours, red yellow and blue, crisp sunny day',
    'gentle': 'soft warm pastel colours, gentle golden afternoon light',
    'lullaby': 'soft dusky pastel colours, calm deep blue evening, tiny friendly stars',
    'silly': 'loud clashing happy colours, wobbly playful shapes, cartoon energy',
    'curious': 'fresh green and turquoise colours, bright clear morning light',
}

NEGATIVE = (
    'photorealistic, photograph, photo, realistic, hyperrealistic, 3d render, cgi, '
    'octane render, live action, film still, depth of field, bokeh, camera, '
    'scary, creepy, horror, monster, dark, gloomy, gritty, grim, sad, crying, '
    'violence, weapon, blood, '
    'text, letters, words, numbers, writing, caption, subtitle, logo, watermark, '
    'signature, cluttered, busy background, intricate detail, ornate, '
    'ugly, deformed, distorted, low quality, blurry'
)


def look_for(brief):
    """The colour clause for this song.

    An explicit ``brief['look']`` wins, then the style's own look, then the mood
    palette — which is what every song used before styles existed.  Only the
    accent changes — BASE_STYLE is the flat 2D cartoon contract and is never
    touched, so a styled song is still the same kind of picture.

    THE EXPLICIT CASE IS WHAT MAKES A SERIES POSSIBLE (2026-10-02). A song about
    a recurring child is worthless if the child is a different child in every
    picture, and this function is the single owner of the prompt's leading
    clause — read by every still and by every LTX motion prompt. So a series
    carries its character description on the brief
    (kids_series_people.PEOPLE[*]['look']) and it reaches every frame, ahead of
    the idea text, which is the clause a truncating encoder keeps. Honouring an
    explicit value here is the same rule the style table already states for
    every other default: the operator's value wins.
    """
    look = brief.get('look')
    if isinstance(look, str) and look.strip():
        return look.strip()
    S = T.STYLES.get(brief.get('style')) if isinstance(brief.get('style'), str) else None
    if S and S.get('look'):
        return S['look']
    return MOOD_LOOK.get(brief.get('mood'), MOOD_LOOK['happy'])


def style_for(brief):
    """The style sentence for this song — one owner, used by every prompt."""
    return f'{BASE_STYLE}, {look_for(brief)}'


def build_prompt(style, idea):
    """Style first, subject second.

    Order is deliberate: the leading clause is the one a truncating prompt
    encoder is least likely to drop, and the look is the property this workflow
    must not lose.
    """
    idea = re.sub(r'\s+', ' ', str(idea or '')).strip().strip('.').strip()
    return f'{style}, {idea}'[:1200]


# ── The motif deck ───────────────────────────────────────────────────────────
#
# What fills a video when the song does not have enough words to fill it.  Every
# entry is a function of (run length, rng, hero) returning that many ideas, so a
# motif can stretch to whatever the beat grid gave it.  These are written in code
# rather than asked of the model for two reasons: they are exactly reproducible
# from the song's seed, and they cannot fail when ollama is down — which is
# precisely when the deficit they exist to fill is largest.

_COUNT_WORDS = ['one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']
# (noun, where).  The COLOURS are named cumulatively across a counting run —
# picture two is "red and yellow", picture three is "red, yellow and blue" — so
# the run reads as one growing set rather than as three unrelated pictures of
# different things.  A shared seed alone does not achieve that: klein re-rolls
# the palette when the prompt changes, which is exactly what the first counting
# run produced (a yellow-and-pink balloon, then three quite different ones).
#
# COUNTING FRAMES ARE DRAWN, NOT GENERATED — and that is the point of them.
#
# The operator's example is "boem ba boem → one block, two blocks, three
# blocks", which only works if the numbers are right.  Measured on the first
# illustrated song: klein asked for one, two, three, four balloons and rendered
# one, THREE, three, four.  Nor can the mistake be caught afterwards — CLIP
# asked to count the same four frames answered 2, 3, 4, 3, and connected-
# component analysis (which ought to be easy on a plain sky) answered 4, 2, 3, 2
# because touching balloons merge and a cloud is a blob.  A number a generator
# will not honour and no measurement can check is a number that has to be drawn.
#
# So these frames come out of PIL, where N objects means N objects, in the same
# flat language as the rest: bold dark outline, flat fill, plain ground.  `key`
# is the shape the drawer knows how to draw.
_COUNT_ITEMS = [
    ('block', 'wooden toy building block', 'in a neat row on a nursery rug'),
    ('apple', 'round apple', 'in a row on a plain wooden table'),
    ('balloon', 'balloon', 'floating up side by side against a clear sky'),
    ('star', 'star', 'in a row on a soft blue sky'),
    ('flower', 'smiling flower', 'in a row in short green grass'),
    ('ball', 'spotty toy ball', 'in a row on a clean nursery floor'),
]
# No white: a white balloon is fine but a white apple is not, and the palette is
# shared across every counting item.
_COUNT_COLOURS = ['red', 'yellow', 'blue', 'green', 'orange', 'purple', 'pink']
_COLOUR_RGB = {
    'red': (238, 63, 63),
    'yellow': (255, 208, 45),
    'blue': (74, 160, 240),
    'green': (108, 205, 96),
    'orange': (255, 150, 46),
    'purple': (150, 122, 235),
    'pink': (255, 133, 186),
    'white': (250, 250, 250),
}


def _count_phrase(k, noun, where, colours):
    """One frame of a counting run, as a sentence.

    It is what the storyboard and the inspection tab show, and it is what the
    drawer is told to draw — not a prompt: the colours are named cumulatively so
    picture three is picture two plus one more, which is what makes a run of
    them read as counting rather than as three unrelated pictures.
    """
    cols = colours[:k]
    listed = cols[0] if k == 1 else ', '.join(cols[:-1]) + ' and ' + cols[-1]
    return f'exactly {_COUNT_WORDS[min(k - 1, 9)]} {noun}{"" if k == 1 else "s"}, {listed}, {where}'


_SHAPES = [
    'a big smiling red circle',
    'a big smiling blue square',
    'a big smiling yellow triangle',
    'a big smiling green star',
    'a big smiling orange heart',
    'a big smiling purple oval',
]
_COLOURS = ['bright red', 'sunny yellow', 'sky blue', 'grass green', 'happy orange', 'soft purple', 'bubblegum pink']
_TOYS = [
    'a soft brown teddy bear sitting and waving',
    'a yellow rubber duck with a big smile',
    'a spinning striped toy top',
    'a small toy drum with two drumsticks',
    'a bouncing red and white ball',
    'a wooden rocking horse with a friendly face',
    'a stack of coloured stacking rings',
    'a toy xylophone with rainbow bars',
]
_ANIMALS = [
    'a happy puppy wagging its tail',
    'a fluffy kitten with big eyes',
    'a little yellow duckling waddling',
    'a white bunny hopping',
    'a woolly lamb skipping',
    'a round pink piglet smiling',
    'a friendly brown bear cub waving',
    'a small green frog hopping',
]
_WEATHER = [
    'a big smiling yellow sun in a blue sky',
    'a fat fluffy white cloud with a happy face',
    'a bright rainbow arching over green hills',
    'gentle raindrops and a shiny puddle',
    'soft white snowflakes falling on a green hill',
]
_DANCE = [
    'happy cartoon children clapping their hands',
    'happy cartoon children jumping with their arms up',
    'happy cartoon children waving hello',
    'happy cartoon children spinning and dancing',
    'happy cartoon children holding hands in a circle',
]
# CYCLED, NOT CLAMPED, and long enough that a cycle is rare.  The first version
# was `_GROW[min(i, len - 1)]`, so a run longer than five stages repeated the
# last one — and because 'grow' shares one seed across its run, four identical
# prompts became four byte-identical pictures and three cuts with nothing behind
# them.  `verify_cuts` caught it on the delivered mp4 (51/54 visible), which is
# the whole reason that check measures the file rather than the plan.
_GROW = [
    'a small brown seed in dark soil',
    'a tiny green sprout pushing out of the soil',
    'a young green stem with two leaves',
    'a taller green stem with four leaves',
    'a green stem with a closed flower bud',
    'a flower bud just beginning to open',
    'a big open flower with a smiling face',
    'a big open flower with a friendly bee buzzing beside it',
    'a big open flower with petals waving in the breeze',
    'a tall flower with a small butterfly resting on it',
]
_JOURNEY = [
    'travelling over a rolling green hill',
    'passing a little red farmhouse and a friendly cow',
    'crossing a small wooden bridge over a blue stream',
    'going along the shore beside a calm blue sea with white waves',
    'passing tall green trees full of singing birds',
    'arriving under a big warm setting sun',
]


def _count_run(n, rng, down=False):
    """A counting run as (text, draw-spec) pairs.

    The draw-spec is what makes the number true: it names the shape, the count
    and the exact colours, and it goes to the PIL drawer rather than to a prompt.
    """
    key, noun, where = rng.choice(_COUNT_ITEMS)
    cols = list(_COUNT_COLOURS)
    rng.shuffle(cols)
    out = []
    for i in range(n):
        k = (n - i) if down else (i + 1)
        out.append((_count_phrase(k, noun, where, cols), {'kind': 'count', 'item': key, 'n': k, 'colours': cols[:k]}))
    return out


def _m_count_up(n, rng, hero):
    return _count_run(n, rng, down=False)


def _m_count_down(n, rng, hero):
    # Counting down takes colours AWAY from the same set, so the objects that
    # remain are the same objects — not a fresh set at every number.
    return _count_run(n, rng, down=True)


def _m_shapes(n, rng, hero):
    pool = list(_SHAPES)
    rng.shuffle(pool)
    return [f'{pool[i % len(pool)]}, alone in the middle of the picture' for i in range(n)]


_HERO_COLOUR_RE = re.compile(
    r'\b(red|blue|green|yellow|orange|purple|pink|brown|black|white|grey|gray|'
    r'golden|silver)\b',
    re.I,
)


def _m_colours(n, rng, hero):
    pool = list(_COLOURS)
    rng.shuffle(pool)
    # A COLOUR PARADE CANNOT RUN ON A HERO THAT ALREADY HAS A COLOUR: "a little
    # red steam train, painted bright red" is a wasted frame and "painted happy
    # orange" argues with its own subject at every cfg above 1. The hero's own
    # colour word is dropped for this motif only.
    what = _HERO_COLOUR_RE.sub('', hero or '').strip()
    what = re.sub(r'\s{2,}', ' ', what) or 'a friendly round smiling balloon'
    return [f'{what}, painted {pool[i % len(pool)]}, plain background' for i in range(n)]


def _m_toys(n, rng, hero):
    pool = list(_TOYS)
    rng.shuffle(pool)
    return [f'{pool[i % len(pool)]}, on a clean nursery floor' for i in range(n)]


def _m_animals(n, rng, hero):
    pool = list(_ANIMALS)
    rng.shuffle(pool)
    return [f'{pool[i % len(pool)]} in green grass' for i in range(n)]


def _m_weather(n, rng, hero):
    pool = list(_WEATHER)
    rng.shuffle(pool)
    return [pool[i % len(pool)] for i in range(n)]


def _m_dance(n, rng, hero):
    pool = list(_DANCE)
    rng.shuffle(pool)
    return [pool[i % len(pool)] for i in range(n)]


def _m_grow(n, rng, hero):
    return [_GROW[i % len(_GROW)] for i in range(n)]


def _m_journey(n, rng, hero):
    what = hero or 'a cheerful little cartoon character'
    pool = list(_JOURNEY)
    start = rng.randrange(len(pool))
    return [f'{what} {pool[(start + i) % len(pool)]}' for i in range(n)]


def _m_peekaboo(n, rng, hero):
    what = hero or 'a cheerful little cartoon character'
    # Nothing here assumes the hero has arms: it may be a train, a boat or a
    # teapot, and "both arms up in the air" is how a limbless subject gets given
    # limbs it does not have.
    frames = [
        f'{what} hiding behind a big green bush, only the top peeking out',
        f'{what} popping out from behind the bush with a huge happy smile',
        f'{what} in the open with confetti and streamers all around it',
    ]
    return [frames[i % len(frames)] for i in range(n)]


# Ordered so the deck can be walked without repeating a motif back to back.
MOTIFS = {
    'count_up': _m_count_up,
    'count_down': _m_count_down,
    'shapes': _m_shapes,
    'colours': _m_colours,
    'toys': _m_toys,
    'animals': _m_animals,
    'weather': _m_weather,
    'dance': _m_dance,
    'grow': _m_grow,
    'journey': _m_journey,
    'peekaboo': _m_peekaboo,
}
# A burst is one picture per beat.  Counting is what that rhythm is FOR — the
# number advances with the beat — so bursts draw from this shortlist only.
BURST_MOTIFS = ['count_up', 'count_down', 'shapes', 'colours', 'toys', 'animals']
FILL_MOTIFS = ['journey', 'dance', 'toys', 'animals', 'weather', 'grow', 'peekaboo', 'colours', 'shapes']

# 'dance' is the one motif no STYLE may draw: dance is the excluded style, and a
# styled song that filled its gaps with dance pictures would be showing the very
# thing the operator took off the shelf.  Enforced here rather than trusted to
# eleven hand-written lists in kids_music_theory.
STYLE_MOTIF_EXCLUDED = {'dance'}


def motif_pools(brief):
    """(burst pool, fill pool) for this song.

    A styled song draws from its own two lists — that is how 'counting' counts
    and 'animals' stays on the farm.  Anything the style names that this file
    does not implement is dropped, and an empty result falls back to the whole
    deck rather than leaving a run with nothing to draw.
    """
    S = T.STYLES.get(brief.get('style')) if isinstance(brief.get('style'), str) else None
    if not S:
        return list(BURST_MOTIFS), list(FILL_MOTIFS)

    def _keep(names):
        return [m for m in (names or []) if m in MOTIFS and m not in STYLE_MOTIF_EXCLUDED]

    # The fallback for a styled song is the deck MINUS the excluded motif — a
    # style whose lists all dropped out still may not reach for 'dance'.
    return (_keep(S.get('burst_motifs')) or _keep(BURST_MOTIFS), _keep(S.get('fill_motifs')) or _keep(FILL_MOTIFS))
