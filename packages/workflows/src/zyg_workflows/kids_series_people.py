# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kids_series_people.py — the two children's-song SERIES: Life of Jack, Life of Mona.

2026-10-02, operator: two children's songs a day, one about a little boy's day and
one about a little girl's, every episode about that child and nothing else.

WHY A MODULE AND NOT JUST A BATCHER. The daily batcher (bp_jackmona_daily) has to do
a ``crewai_web_gui`` import, which means it cannot be unit
tested and cannot be read without the GUI in the room. Everything that decides
WHAT a song is — who the children are, what they look like, which moment of the
day this episode is, how long it runs — lives here instead, with no Flask and no
GUI import, so it is testable on its own and there is one place to edit a child.

THE THREE THINGS THAT MAKE A SERIES A SERIES
--------------------------------------------
1. **One face.** A song about Jack is worthless if Jack is a different boy in
   every picture. The appearance lives in ``look``, which rides on the brief and
   is read by ``kids_video_service.look_for`` — the single owner of the picture
   prompt's leading clause, used by every still AND by every LTX motion prompt.
   So the description reaches every frame of every episode, and it reaches them
   BEFORE the idea text, which is the clause a truncating encoder keeps.
   It is deliberately NOT in the theme: the theme is what the lyric writer sees,
   and a lyric that sings about chestnut hair and yellow trainers is a costume
   list, not a song.

2. **One voice.** ``singer`` is fixed per child — Jack is the adult male Warm
   Control, Mona the female twin of that same caption and seed. The songs are
   ABOUT a child, sung by an adult: there is no child singer in this stack, and
   the reason is measured (the children's-choir caption does not separate from
   adult female; see kids_music_theory.SINGERS).

3. **No repeats, and no crossovers.** Every episode is one ordinary moment of
   that child's own day, recorded in the ledger so tomorrow does not sing it
   again. Jack's songs are only ever about Jack and Mona's only ever about Mona —
   the operator asked for that twice, so it is a rule here and not a tendency:
   neither child's prompt, pool or look mentions the other.

WHAT AN EPISODE COSTS. One song is ~170 s of music (the band in
kids_music_theory.SONG_SECONDS), which the picture leg turns into ~40 pictures of
~5 s each — one LTX clip per picture. Measured on 60 s songs: ~10 min of picture
leg, so ~30 min for a 170 s one, and the pair is roughly an hour of GPU a night.
"""

from __future__ import annotations

import json
import os
import random
import re
import threading

from zyg_workflows import kids_llm
from zyg_workflows import paths
from zyg_workflows import kids_music_theory as T

_RUNTIME = paths.ZYG_METRICS_RUNTIME_DIR
LEDGER_PATH = os.path.join(_RUNTIME, 'kids_series_episodes.json')
_LOCK = threading.RLock()

_OLLAMA = paths.ZYG_OLLAMA_URL.rstrip('/')
_MODEL = os.environ.get('ZYG_KIDSMUSIC_LLM', 'qwen3.5:9b')

# ── The children ─────────────────────────────────────────────────────────────
#
# `look` is the picture clause. Every noun in it is there to be drawn the same
# way twice: hair shape AND colour, eye colour, one named garment per layer, one
# shoe colour. Vague words ("cute", "nice clothes") are what make a character
# drift between renders, so there are none. It opens by naming the child and
# saying the words "the same ... in every picture", because the clause is also
# read by the LTX motion prompt, where holding the first frame is the job.
#
# `lyric_hint` is appended to the lyric prompt's Rules (kids_music_service.
# write_lyrics). It names the child and pins the point of view, which is what
# stops a song about Jack becoming a song about ducks that Jack happens to see.
PEOPLE = {
    'jack': {
        'slug': 'jack',
        'name': 'Jack',
        'label': 'Life of Jack',
        'blurb': "A song a day about one small boy's ordinary day.",
        # Warm Control, the operator's default male voice (caption + seed ARE the
        # voice; see kids_music_theory.SINGERS['adult_male']).
        'singer': 'adult_male',
        'age_band': 'preschool',
        # Its musical identity: warm storybook, AABA, theme lyrics. A format, not
        # a palette — the palette is the look below.
        'style': 'storytime',
        'moods': ['happy', 'playful', 'curious', 'gentle'],
        'look': (
            'Jack is the same little boy in every picture: a cheerful four-year-old '
            'with short wavy chestnut-brown hair, round brown eyes and a few freckles, '
            'wearing a red and white striped t-shirt, blue dungarees and yellow shoes; '
            'warm storybook colours, soft green garden, golden afternoon light'
        ),
        'lyric_hint': (
            'This is one episode of a series about a little boy called Jack: every '
            'line is about Jack himself and what he does in this one everyday moment, '
            'name him "Jack" in at least half the lines, and keep him the only '
            'person the song is about.'
        ),
        'world': (
            'Jack is four. He lives in a small house with a green garden, a cat '
            'called Pim, his mum, his dad and a baby sister. He has a red scooter, '
            'wellington boots and a toy digger.'
        ),
        # 36 ordinary moments of a small boy's day. Hand-written, so the series
        # ships whether or not a model answers, and ordered roughly as a day runs
        # so a week of episodes reads as a week.
        'pool': [
            'Jack wakes up and opens the curtains',
            'Jack brushes his teeth and makes a bubble beard',
            'Jack puts on his own socks at last',
            'Jack eats toast with too much jam',
            'Jack packs his little backpack for the day',
            'Jack puts on his wellington boots the wrong way round',
            'Jack rides his red scooter down the path',
            'Jack splashes in a puddle on purpose',
            'Jack feeds the ducks at the pond',
            'Jack helps hang the washing on the line',
            'Jack digs a hole in the garden with his toy digger',
            'Jack waters the tomato plants with a watering can',
            'Jack finds a snail on the garden wall',
            'Jack builds a tall tower of blocks and knocks it down',
            'Jack draws a picture of his cat Pim',
            'Jack hides under the table and counts to ten',
            'Jack shares his biscuits with his baby sister',
            'Jack washes his hands before lunch',
            'Jack eats soup and dips his bread in it',
            'Jack puts his toys back in the box',
            'Jack goes to the shop with dad and carries the bag',
            'Jack picks apples and puts them in a basket',
            'Jack jumps in a big pile of leaves',
            'Jack builds a den out of cushions and a blanket',
            'Jack rolls a ball to Pim the cat',
            'Jack paints with his fingers and gets paint on his nose',
            'Jack helps stir the cake mixture',
            'Jack puts a plaster on his knee and feels brave',
            'Jack learns to hop on one foot',
            'Jack blows dandelion seeds across the garden',
            'Jack looks for his missing shoe everywhere',
            'Jack has a bath and sails a plastic boat',
            'Jack puts on his pyjamas all by himself',
            'Jack brushes his hair and looks in the mirror',
            'Jack reads one more bedtime story with mum',
            'Jack says goodnight to the moon from his window',
        ],
    },
    'mona': {
        'slug': 'mona',
        'name': 'Mona',
        'label': 'Life of Mona',
        'blurb': "A song a day about one small girl's ordinary day.",
        # The female twin of Warm Control: the same caption at the same seed, which
        # is the shipped Red Train master's voice.
        'singer': 'adult_female',
        'age_band': 'preschool',
        'style': 'storytime',
        'moods': ['happy', 'playful', 'curious', 'gentle'],
        'look': (
            'Mona is the same little girl in every picture: a bright five-year-old '
            'with dark brown hair in two bunches tied with turquoise ribbons, warm '
            'brown skin and big hazel eyes, wearing a sunflower-yellow pinafore over '
            'a white t-shirt, green leggings and red shoes; warm storybook colours, '
            'soft green garden, golden afternoon light'
        ),
        'lyric_hint': (
            'This is one episode of a series about a little girl called Mona: every '
            'line is about Mona herself and what she does in this one everyday '
            'moment, name her "Mona" in at least half the lines, and keep her the '
            'only person the song is about.'
        ),
        'world': (
            'Mona is five. She lives in a flat with a balcony full of plants, a '
            'budgie called Pip, her mum and her grandad. She has a blue bicycle '
            'with a bell, a skipping rope and a toy rabbit called Bun.'
        ),
        'pool': [
            'Mona wakes up and stretches like a cat',
            'Mona ties her own shoelaces slowly',
            'Mona brushes her hair into two bunches',
            'Mona pours milk on her cereal all by herself',
            'Mona waters the plants on the balcony',
            'Mona says good morning to Pip the budgie',
            'Mona rides her blue bicycle and rings the bell',
            'Mona skips with her skipping rope and counts the jumps',
            'Mona draws a rainbow with every colour she has',
            'Mona plants a bean in a little pot',
            'Mona finds a ladybird on a leaf',
            'Mona helps grandad carry the shopping upstairs',
            'Mona sorts her buttons into colours',
            'Mona has a tea party with her toy rabbit Bun',
            'Mona builds a tall tower out of books',
            'Mona dances in the kitchen to the radio',
            'Mona washes her hands and sings while she does it',
            'Mona cuts out paper stars with safety scissors',
            'Mona shares her orange with grandad, half each',
            'Mona looks after Bun when his ear comes loose',
            'Mona feeds the birds crumbs from the balcony',
            'Mona splashes in the bath and makes a bubble hat',
            'Mona helps fold the warm washing',
            'Mona learns to whistle and nearly manages it',
            'Mona makes a card for her mum with glue and glitter',
            'Mona goes to the market and picks the reddest apple',
            'Mona tidies her toys into the big basket',
            'Mona hops across the paving stones without touching the lines',
            'Mona finds a feather and keeps it safe',
            'Mona bakes little biscuits with grandad',
            'Mona looks at the rain on the window and draws in the steam',
            'Mona puts on her yellow raincoat and goes out anyway',
            'Mona counts the stairs all the way up to the flat',
            'Mona reads a picture book to Bun at bedtime',
            'Mona puts on her pyjamas and brushes her teeth',
            'Mona says goodnight to Pip and turns off the lamp',
        ],
    },
}

SLUGS = ('jack', 'mona')  # the order a day's pair runs in

# Nothing frightening, nothing medical, nothing about money, and no moment that
# needs a second child in it — the series are single-character by instruction.
_BANNED = re.compile(
    r'\b(die|died|death|dead|kill|blood|hospital|doctor|injection|ill|illness|'
    r'sick|fever|money|buy|price|euro|dollar|gun|war|fight|scary|monster|ghost|'
    r'nightmare|lost forever|police|fire brigade|ambulance)\b',
    re.I,
)


def person(slug):
    """One child's entry, or None."""
    return PEOPLE.get(str(slug or '').strip().lower())


def _norm(moment):
    return re.sub(r'[^a-z0-9 ]+', '', str(moment or '').lower()).strip()


# ── the ledger: what each child has already sung about ───────────────────────


def load_ledger():
    with _LOCK:
        try:
            with open(LEDGER_PATH, encoding='utf-8') as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            return {s: [] for s in SLUGS}
        if not isinstance(d, dict):
            return {s: [] for s in SLUGS}
        return {s: list(d.get(s) or []) for s in SLUGS}


def _save_ledger(d):
    with _LOCK:
        os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
        tmp = LEDGER_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(d, fh, indent=1)
        os.replace(tmp, LEDGER_PATH)


def episodes(slug):
    return load_ledger().get(str(slug).lower()) or []


def next_number(slug):
    """Episode numbers are 1-based and never reused, so a title can carry one."""
    eps = episodes(slug)
    return 1 + max([int(e.get('n') or 0) for e in eps] or [0])


def used_moments(slug):
    return {_norm(e.get('moment')) for e in episodes(slug) if e.get('moment')}


def record_episode(slug, moment, *, n=None, job_id=None, title=None, seconds=None, date=None, extra=None):
    """Append one episode. Called when the song STARTS, so a crash mid-render
    cannot hand tomorrow the same moment — a repeated moment is a worse failure
    than a missing episode, because it looks like the series has no memory."""
    slug = str(slug).lower()
    with _LOCK:
        d = load_ledger()
        rows = d.setdefault(slug, [])
        rows.append(
            {
                'n': int(n or next_number(slug)),
                'date': date or '',
                'moment': str(moment or '')[:200],
                'job_id': job_id or None,
                'title': title or None,
                'seconds': seconds,
                **(dict(extra or {})),
            }
        )
        _save_ledger(d)
        return rows[-1]


def attach_job(slug, n, job_id, *, status='in_production'):
    """Put the pipeline id on the row `record_episode` created for episode `n`.

    The row exists before the song starts (see record_episode) so the moment is
    spent the moment it is chosen; this is what later joins it to the run that
    actually rendered it.
    """
    slug = str(slug).lower()
    with _LOCK:
        d = load_ledger()
        for e in d.get(slug) or []:
            if int(e.get('n') or 0) == int(n) and not e.get('job_id'):
                e['job_id'] = job_id
                e['status'] = status
                _save_ledger(d)
                return e
    return None


def settle_episode(slug, job_id, *, title=None, status=None):
    """Fill in what only the finished run knows (its title, its verdict)."""
    slug = str(slug).lower()
    with _LOCK:
        d = load_ledger()
        for e in d.get(slug) or []:
            if e.get('job_id') == job_id:
                if title:
                    e['title'] = str(title)[:120]
                if status:
                    e['status'] = str(status)[:40]
                _save_ledger(d)
                return e
    return None


# ── what this episode is about ───────────────────────────────────────────────


def moment_ok(slug, moment, avoid):
    p = person(slug)
    name = (p or {}).get('name', '')
    m = re.sub(r'\s+', ' ', str(moment or '')).strip()
    if not (12 <= len(m) <= 110):
        return False
    if _BANNED.search(m):
        return False
    if _norm(m) in avoid:
        return False
    # It has to be about THIS child by name, and must not drag the other one in.
    if name and name.lower() not in m.lower():
        return False
    other = [q['name'] for s, q in PEOPLE.items() if s != slug]
    return not any(o.lower() in m.lower() for o in other)


def propose_moment(slug, avoid=None, *, log_fn=None):
    """Ask the local model for one fresh moment of this child's day. '' on any
    failure — the pool below covers it, so a model outage never stops the series."""
    log = log_fn or (lambda _m: None)
    p = person(slug)
    if not p:
        return ''
    avoid = set(avoid or used_moments(slug))
    recent = [e.get('moment') for e in episodes(slug)[-20:] if e.get('moment')]
    prompt = (
        f'You write episode ideas for a song series about one small child called '
        f'{p["name"]}. Reply with JSON only.\n'
        f'About {p["name"]}: {p["world"]}\n'
        f"Invent ONE new everyday moment from {p['name']}'s own day — something "
        f'ordinary and cheerful a small child does, in 5 to 14 words, written as a '
        f'sentence that starts with "{p["name"]}".\n'
        'Rules: one simple action a four or five year old really does; everyday '
        'things only; nothing frightening; nothing about illness, death, violence '
        'or money; no brand names; no other children or named people; it must be '
        f'about {p["name"]} alone.\n'
        + (f'Do NOT repeat or rephrase any of these: {"; ".join(recent)}\n' if recent else '')
        + '{"moment": "..."}'
    )
    # Opus 5 on the subscription, then the local model, then the hand-written pool. This is
    # the step that decides what a daily episode IS — the lyric and all fourteen pictures
    # are written downstream of this one sentence — so it runs on the same model as the
    # lyric. The local prompt above is unchanged and is the fallback; the Opus prompt gets
    # the ledger of what has already been sung, which is what keeps a daily series from
    # circling. (kids_llm keeps the qwen3.x think:false trap; gpt-oss + format:json returns
    # nothing at all, so do not swap the local model here either.)
    opus_prompt = (
        f'You invent episodes of a daily song series about one small child, {p["name"]}.\n'
        f'About {p["name"]}: {p["world"]}\n\n'
        f"Invent ONE new everyday moment from {p['name']}'s own day: something ordinary, "
        f'specific and cheerful that a four or five year old really does. Five to fourteen '
        f'words, written as a sentence that starts with "{p["name"]}".\n\n'
        'Rules:\n'
        '- ONE action, happening once, that could be drawn: a child, a place, a thing they '
        'are doing with it. A whole song (about fourteen pictures) is written from this '
        'sentence, so it must have something to look at — "has a lovely day" is nothing to '
        'draw, "puts his boots on the wrong feet" is a film;\n'
        "- the ordinary small end of a child's day — a sock, a puddle, a spoon, a cat, a "
        'step too high — not an outing, an adventure or a birthday;\n'
        '- nothing frightening; nothing about illness, death, violence or money; no brand '
        f'names; no other children or named people; it is about {p["name"]} alone;\n'
        '- present tense, plain words a small child uses, no jokes aimed over their head.\n'
        + (
            '\nAlready sung — do not repeat or rephrase any of these:\n' + '\n'.join(f'- {m}' for m in recent) + '\n'
            if recent
            else ''
        )
        + '\nReply with exactly this JSON and nothing else:\n{"moment": "..."}'
    )
    data, _info = kids_llm.ask_json(
        opus_prompt=opus_prompt,
        ollama_prompt=prompt,
        system=(
            "You invent episodes for a children's song series. One idea, concrete and "
            'small enough to draw. Reply with one JSON object and nothing else.'
        ),
        stage=f'kids_series_{slug}',
        max_tokens=400,
        options={'temperature': 0.95, 'num_predict': 200, 'num_ctx': 4096},
        ollama_timeout=90,
        label=f'series: {slug} idea',
        log_fn=log,
    )
    if not isinstance(data, dict):
        log(f'series: {slug} no usable idea — using the pool')
        return ''
    # qwen returns {"Moment": ...} a good fraction of the time; reading one
    # spelling threw those answers away in two other callers before this fix.
    low = {str(k).strip().lower(): v for k, v in data.items()}
    m = low.get('moment') or low.get('idea') or low.get('episode') or ''
    if isinstance(m, list):
        m = m[0] if m else ''
    m = re.sub(r'\s+', ' ', str(m)).strip(' .,;:"\'')
    if not moment_ok(slug, m, avoid):
        log(f'series: {slug} proposed moment rejected ({m[:60]!r}) — using the pool')
        return ''
    return m


def pool_moment(slug, avoid=None):
    """The next unused moment from the hand-written pool.

    Past exhaustion every moment is a repeat, so it takes the LEAST RECENTLY sung
    one: the pool is consumed in order, so that is the one `len(episodes)` lands
    on. A month and a bit later, singing the first morning again is the best
    available choice — and it is a rotation rather than a reset, so the day after
    that is the second moment and not the first one again.
    """
    p = person(slug)
    if not p:
        return ''
    avoid = set(avoid if avoid is not None else used_moments(slug))
    pool = p['pool']
    for m in pool:
        if _norm(m) not in avoid:
            return m
    off = len(episodes(slug))
    return pool[off % len(pool)]


def pick_moment(slug, *, log_fn=None):
    """This episode's moment: the model first, the pool as the floor."""
    avoid = used_moments(slug)
    return propose_moment(slug, avoid, log_fn=log_fn) or pool_moment(slug, avoid)


# ── the song brief ───────────────────────────────────────────────────────────


def episode_brief(slug, *, moment=None, n=None, log_fn=None):
    """The complete brief for one episode, ready for pipeline_kidsmusic.

    Everything a series needs is carried on the brief itself rather than written
    into a style table: `look` locks the face (kids_video_service.look_for),
    `lyric_hint` locks the point of view (kids_music_service.write_lyrics),
    `singer` locks the voice, and `style` supplies the musical format. The brief
    is therefore the whole contract and can be read in one place.
    """
    p = person(slug)
    if not p:
        raise KeyError(f'unknown series {slug!r}')
    n = int(n or next_number(slug))
    moment = moment or pick_moment(slug, log_fn=log_fn)
    rng = random.Random(f'{slug}-{n}')
    mood = p['moods'][(n - 1) % len(p['moods'])]
    return {
        # The theme is what the lyric writer is given as its Topic and what the
        # picture leg derives its hero from — the moment, named, and nothing else.
        'theme': moment,
        'subject': p['name'],
        'series': p['slug'],
        'episode': n,
        'age_band': p['age_band'],
        'mood': mood,
        'style': p['style'],
        'family': 'children',
        'sung': True,
        'singer': p['singer'],
        'want_ace': True,
        'want_video': True,
        # The children's band, rotated so consecutive episodes are not all one
        # length (kids_music_theory.SONG_SECONDS, 130-210 s).
        'seconds': T.song_seconds(n),
        'look': p['look'],
        'lyric_hint': p['lyric_hint'],
        # A stable per-episode seed: the same episode re-rendered is the same
        # song, and two different episodes never collide.
        'seed': rng.randrange(1, 2**31 - 1),
    }


def series_rows():
    """Both series with their state, for a board or a status endpoint."""
    out = []
    for s in SLUGS:
        p = PEOPLE[s]
        eps = episodes(s)
        out.append(
            {
                'slug': s,
                'name': p['name'],
                'label': p['label'],
                'blurb': p['blurb'],
                'singer': p['singer'],
                'style': p['style'],
                'episodes': len(eps),
                'next_episode': next_number(s),
                'pool_size': len(p['pool']),
                'pool_left': sum(1 for m in p['pool'] if _norm(m) not in used_moments(s)),
                'last': (eps[-1] if eps else None),
            }
        )
    return out
