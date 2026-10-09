# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""What each picture shows: the LLM storyboard pass and the Opus brief.

Moved verbatim out of the old single-file kids_video_service.py (lines 1291-1754).
"""

from __future__ import annotations

import os
import random
import re
from zyg_workflows import kids_llm
from zyg_workflows import kids_music_theory as T

from zyg_workflows.kids_video_service.constants import (
    CLIP_S,
    _LLM,
    _log_noop,
)
from zyg_workflows.kids_video_service.motifs import (
    MOTIFS,
    motif_pools,
)


# ── Ideas: what each picture shows ───────────────────────────────────────────


def _hero_phrase(brief, plan, log_fn=None):
    """A short noun phrase for the song's recurring subject, from the theme."""
    theme = str(brief.get('theme') or '').strip()
    t = re.sub(r'^(a|an|the)\s+', '', theme, flags=re.I).strip()
    t = re.sub(r'\s+', ' ', t)[:70]
    return t or 'a cheerful little cartoon character'


IDEA_BATCH = int(os.environ.get('ZYG_KIDSVIDEO_IDEA_BATCH', '10'))


def idea_batch(n):
    """How many picture descriptions to ask for in ONE turn.

    Tens for the local 9B model, for the reason in `llm_ideas` below. The whole
    storyboard in one turn on the subscription model: the batching exists because the
    local model repeats itself and because one bad reply used to cost the storyboard its
    song content, and neither is the failure mode of a model that can hold fourteen
    pictures in one answer — while a model that sees the whole sequence at once is the
    only way the sequence becomes a FILM rather than fourteen independent answers with a
    hero stapled on. `ZYG_KIDSVIDEO_IDEA_BATCH_OPUS` pins a batch size if a song ever
    needs one; the local path is untouched either way.
    """
    env = os.environ.get('ZYG_KIDSVIDEO_IDEA_BATCH_OPUS', '').strip()
    if kids_llm.opus_on():
        if env.isdigit() and int(env) > 0:
            return int(env)
        return max(1, int(n))
    return IDEA_BATCH


def llm_ideas(brief, plan, lyrics, n, log_fn=None):
    """``n`` visual ideas, asked for in BATCHES.

    One request for twenty-four came back with eight usable descriptions on a
    live run (the model repeats itself and the dedup drops the repeats), and one
    bad reply cost the whole storyboard its song content.  Asking in tens costs
    a few seconds more and fails in tens instead: a batch that returns nothing
    loses that batch, and the hero plus the last idea are carried forward so the
    batches still read as one sequence.  Cheap in the new arithmetic — the whole
    picture leg is under two minutes now, so three LLM calls is not the cost it
    was when a single frame took thirteen seconds.
    """
    log_fn = log_fn or _log_noop
    if n <= 0:
        return [], {'model': _LLM, 'asked': 0, 'got': 0, 'reason': '', 'batches': 0}
    out, hero, seen, batches, reasons = [], '', set(), 0, []
    backend, model = '', _LLM
    while len(out) < n:
        want = min(idea_batch(n), n - len(out))
        got, inf = _llm_ideas_once(
            brief, plan, lyrics, want, hero, out[-1] if out else '', log_fn=log_fn, done=len(out), total=n
        )
        batches += 1
        backend = backend or (inf.get('backend') or '')
        model = inf.get('model') or model
        hero = hero or (inf.get('hero') or '')
        if inf.get('reason'):
            reasons.append(inf['reason'])
        fresh = [x for x in got if x.lower() not in seen]
        for x in fresh:
            seen.add(x.lower())
        out.extend(fresh)
        # A batch that yields nothing new means the model has run dry on this
        # topic; asking again for the same thing would only spend time. The
        # motif deck covers the remainder, which is what it is for.
        if not fresh:
            break
    if len(out) < n:
        log_fn(f'ideas: model gave {len(out)} of {n} asked over {batches} batch(es) — the motif deck covers the rest')
    return out[:n], {
        'model': model,
        'asked': n,
        'got': len(out),
        'hero': hero,
        'backend': backend or 'ollama',
        'batches': batches,
        'reason': '; '.join(reasons)[:200],
        'keys_seen': [],
    }


# ── The Opus brief ───────────────────────────────────────────────────────────
#
# The second prompt, for the model on the operator's subscription (kids_llm). The local
# prompt below is left byte-identical because it is the FALLBACK; this one is written for a
# model that can plan the whole film at once, so it carries what the local prompt had to
# leave out: how many pictures there are for how many sung lines, that the style sentence
# is prefixed automatically (so style words in the description only crowd out the subject),
# and that every picture is the FIRST FRAME of a five-second clip with a still camera.

_IDEAS_SYSTEM = (
    "You are the art director of a children's music channel. You plan the pictures for a "
    'song: one picture per shot, in order, each one a scene a four-year-old reads in a '
    'second and wants to look at again. You know that a child follows a film by following '
    'one character, and that a picture of a mood is a picture of nothing. Reply with one '
    'JSON object and nothing else — no preamble, no commentary, no markdown fences.'
)


def _ideas_prompt_opus(brief, plan, lyrics, n, hero, previous, done, total, hint, lyric_txt):
    """The subscription model's brief. Same JSON contract as the local prompt."""
    total = int(total or n)
    done = int(done or 0)
    clip_s = CLIP_S
    where = (
        f'These are pictures {done + 1} to {done + n} of {total} in the film.'
        if total != n
        else f'The film is {n} pictures long and you are planning all of them.'
    )
    lines_n = len(lyrics or [])
    pacing = (
        f'There are {total} pictures for {lines_n} sung lines, in the same order as the '
        f'song: walk through the lyric in order and give each line one or two pictures, '
        f'so the video stays in step with the words.'
        if lines_n
        else 'The song has no words, so the pictures carry it alone: tell one simple story across them.'
    )
    rules = [
        'one COMPLETE little scene per description, at most 14 words — the kind of picture '
        'that could be printed on its own page of a picture book. Never a fragment like '
        '"a blue sky above" or "grass below": something is HAPPENING and the main '
        'character or object is the one doing it;',
        f'the same main character in every picture, recognisably the same — same colours, '
        f'same shape, same size, named the same way in every description ("{hero}" if that '
        f'is who it is). The pictures are drawn one at a time by an image model that sees '
        f'only your sentence, so whatever you leave out changes between pictures;'
        if hero
        else 'one main character or object that appears in every picture, described the same way '
        'every time — the pictures are drawn one at a time by an image model that sees only '
        'your sentence, so whatever you leave out changes between pictures;',
        f'each picture is the FIRST FRAME of a {clip_s:.0f}-second clip with a still camera '
        f'and one small movement in it, so compose something that can hold still and stay '
        f'interesting: a subject doing one thing, room around it, no motion blur, no '
        f'implied camera move;',
        'the style is added automatically (flat 2D cartoon, bold outlines, plain background) '
        '— do NOT spend words on style, lighting, "illustration", "cartoon" or "picture book": '
        'spend all 14 on WHAT IS THERE;',
        'name concrete things a small child recognises; everything happy, sunny and safe;',
        f'vary the framing and the setting across the sequence — close to a face, the whole '
        f'character, a wide view of where it is — so {n} pictures are not one picture '
        f'{n} times;',
        'never describe text, letters, numbers, writing or signs; never a camera, a photo or '
        'a screen; nothing frightening, sad or violent;',
        'no two descriptions alike, and no description that only makes sense if the previous '
        'picture is still on screen.',
    ]
    head = [
        f'Song: "{brief.get("title") or brief.get("theme")}"',
        f'Topic: {brief.get("theme")}',
        f'Audience: {brief.get("age_band")} children',
    ]
    if hint:
        head.append(f'Style: {hint}')
    if plan and plan.get('order'):
        head.append(f'Musical form: {"-".join(plan["order"])} (B is the chorus)')
    return (
        '\n'.join(head)
        + '\n\n'
        + (f'The sung lines, in order:\n{lyric_txt}\n\n' if lyric_txt else '')
        + where
        + ' '
        + pacing
        + '\n'
        + (f'The recurring main character is: {hero}.\n' if hero else '')
        + (f'The previous picture was: {previous}\n' if previous else '')
        + f'\nWrite exactly {n} picture descriptions, in the order they appear.\n\n'
        + 'Rules:\n'
        + '\n'.join(f'- {r}' for r in rules)
        + '\n\n'
        + 'Also give "hero": the recurring main character or object in five words or fewer, '
        'described the way every picture should name it.\n'
        + 'Reply with exactly this JSON and nothing else:\n'
        + '{"hero": "...", "pictures": ['
        + ', '.join(['"..."'] * min(n, 3))
        + (', ...' if n > 3 else '')
        + f']}}  — exactly {n} strings in "pictures".'
    )


def _llm_ideas_once(brief, plan, lyrics, n, hero, previous, log_fn=None, done=0, total=0):
    """Ask for ``n`` visual ideas, one per picture.

    Opus 5 on the operator's subscription first, the local model second, the motif deck
    last — `kids_llm` owns that order. Returns (ideas, info).  The same shape (and the same
    traps) as the lyric writer: qwen3.x needs ``think: false`` or the budget goes to
    reasoning tokens and ``response`` comes back empty, and the keys come back title-cased
    about a third of the time, so they are case-folded before reading.
    """
    log_fn = log_fn or _log_noop
    info = {'model': _LLM, 'asked': n, 'got': 0, 'reason': '', 'keys_seen': []}
    if n <= 0:
        return [], info
    lyric_txt = '\n'.join(f'{i + 1}. {ln}' for i, ln in enumerate(lyrics[:24]))
    _S = T.STYLES.get(brief.get('style')) if isinstance(brief.get('style'), str) else None
    # One owner for the hint (T.lyric_hint_for); the style LABEL is still named
    # here, as it was before, because the picture planner is told the format as
    # well as the rule.
    _hint = T.lyric_hint_for(brief)
    if _S and not str(brief.get('lyric_hint') or '').strip():
        _hint = f'{_S["label"]} — {_hint}'.strip(' —')
    prompt = (
        'You plan the pictures for a cartoon music video for very young '
        'children. Reply with JSON only.\n'
        f'Song topic: {brief.get("theme")}\n'
        # The brief's own hint wins over the style's, for the same reason it does
        # in the lyric writer: a series pins what the pictures are OF.
        + (f'Song style: {_hint}\n' if _hint else '')
        + f'Audience: {brief.get("age_band")} children\n'
        + (f'The sung lines, in order:\n{lyric_txt}\n' if lyric_txt else '')
        + (f'The recurring main character is: {hero}. Keep it recognisably the same.\n' if hero else '')
        + (f'The previous picture in the sequence was: {previous}\n' if previous else '')
        + f'Write exactly {n} picture descriptions, in the order they appear.\n'
        'Rules:\n'
        '- each description is ONE COMPLETE little scene of at most 14 words, '
        'the kind of picture that could be printed on its own page of a picture '
        'book. Never a fragment of a scene like "a blue sky above" or "grass '
        'below" — every picture must have something HAPPENING in it and must '
        'show the main character or object doing it.\n'
        '- name concrete things a small child recognises, and keep the main '
        'character recognisably the same in every picture.\n'
        '- everything is happy, sunny and safe.\n'
        '- never describe text, letters, numbers or writing; never a camera or a '
        'photo; nothing frightening, sad or violent.\n'
        '- do not repeat a description.\n'
        'Also give "hero": the recurring main character or object in five words '
        'or fewer.\n'
        '{"hero": "...", "pictures": ["...", "..."]}'
    )
    # Opus 5 on the subscription, then the local model, then the motif deck. The local
    # payload moved into kids_llm unchanged, the qwen3.x think:false trap with it.
    data, llm_info = kids_llm.ask_json(
        opus_prompt=_ideas_prompt_opus(brief, plan, lyrics, n, hero, previous, done, total, _hint, lyric_txt),
        ollama_prompt=prompt,
        system=_IDEAS_SYSTEM,
        stage='kidsvideo_storyboard',
        max_tokens=4000,
        options={'temperature': 0.9, 'num_predict': 1600, 'num_ctx': 8192},
        ollama_timeout=240,
        label='ideas',
        log_fn=log_fn,
    )
    info['backend'] = llm_info.get('backend') or 'ollama'
    info['model'] = llm_info.get('model') or _LLM
    if data is None:
        info['reason'] = llm_info.get('reason') or 'no answer'
        log_fn(f'ideas: {info["reason"]} — the motif deck fills every slot')
        return [], info

    ideas, hero = [], ''
    if isinstance(data, dict):
        info['keys_seen'] = sorted(str(k) for k in data)
        low = {str(k).strip().lower(): v for k, v in data.items()}
        hero = str(low.get('hero') or '')[:70]
        raw_list = low.get('pictures') or low.get('images') or low.get('scenes') or low.get('shots') or []
        if isinstance(raw_list, str):
            raw_list = [x for x in raw_list.splitlines() if x.strip()]
        seen = set()
        for x in list(raw_list)[:n]:
            s = re.sub(r'\s+', ' ', str(x)).strip(' .,;:"\'')[:140]
            k = s.lower()
            if s and k not in seen:
                seen.add(k)
                ideas.append(s)
        if not ideas:
            info['reason'] = f'model replied with keys {info["keys_seen"]} and no pictures'
            log_fn(f'ideas: {info["reason"]}')
    info['got'] = len(ideas)
    info['hero'] = hero
    return ideas, info


def assign_ideas(slots, brief, plan, *, seed=0, log_fn=None):
    """Give every slot something to show.

    Order of supply, and the reason for it:
      1. the SONG — one idea per picture from the lyric and the theme, via the
         model, because that is what the video is actually about;
      2. the MOTIF DECK — counting runs, parades, toys, animals — for every slot
         the song could not fill, which on a 60 s song is most of them.

    Bursts always take a counting or parade motif: a run of one picture per beat
    is a rhythm, and counting is what that rhythm is for.
    """
    log_fn = log_fn or _log_noop
    rng = random.Random((int(seed) * 7919 + 13) & 0xFFFFFFFF)
    lyrics = list(plan.get('lyrics') or brief.get('lyrics_lines') or [])
    burst_pool, fill_pool = motif_pools(brief)

    # Burst runs are contiguous — find them first so they are not fed lyric ideas.
    runs, i = [], 0
    while i < len(slots):
        if slots[i]['burst']:
            j = i
            while j < len(slots) and slots[j]['burst']:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    burst_idx = {k for a, b in runs for k in range(a, b)}
    free = [s['i'] for s in slots if s['i'] not in burst_idx]

    # HOW MUCH OF THE VIDEO THE SONG SHOULD CARRY.  A 50 s song has about twelve
    # sung lines and about forty-five pictures, and asking the model to stretch
    # twelve lines over forty-five produced exactly what stretching produces:
    # "a bright blue sky above", "green grass grows below" — the scene taken
    # apart into pieces rather than forty-five scenes.  Two pictures per sung
    # line is what the words can actually carry; the rest is what the operator
    # asked for by name — toys, counting, animals, things that make children
    # smile.  A song with no lyric at all still gets a floor of eight, from the
    # theme, so an instrumental is not purely generic.
    story_budget = min(len(free), max(8, 2 * len(lyrics)))

    ideas, info = llm_ideas(brief, plan, lyrics, story_budget, log_fn=log_fn)
    hero = (info.get('hero') or '').strip() or _hero_phrase(brief, plan)

    for s in slots:
        s['idea'] = ''
        s['source'] = ''
        s['motif'] = ''
        s['seed_group'] = ''
        s['draw'] = None

    def _norm(items):
        """A motif yields either a sentence or a (sentence, draw-spec) pair.
        Only the counting motifs carry a spec — everything else is generated."""
        return [(x[0], x[1]) if isinstance(x, tuple) else (x, None) for x in items]

    # 1. Interleave.  Story and motif alternate in blocks of three so a motif
    #    reads as a SEQUENCE (one, two, three blocks) rather than as one orphan
    #    picture between two verses — and so the song's own pictures are spread
    #    across the whole video instead of all landing in the first third.
    want = min(len(ideas), story_budget)
    story_at, k, used_story = set(), 0, 0
    BLOCK = 3
    while k < len(free):
        take = min(BLOCK, len(free) - k)
        ahead = used_story + take
        # Choose whichever assignment keeps the running ratio closest to target.
        as_story = abs((ahead / float(k + take)) - (want / float(len(free))))
        as_motif = abs((used_story / float(k + take)) - (want / float(len(free))))
        if used_story < want and as_story <= as_motif:
            for j in range(k, k + take):
                story_at.add(free[j])
            used_story += take
        k += take

    it = iter(ideas)
    for si in sorted(story_at):
        try:
            slots[si]['idea'] = next(it)
            slots[si]['source'] = 'song'
        except StopIteration:
            break

    # 2. Bursts get a counting or parade motif.  THE FIRST BURST OF EVERY SONG
    #    COUNTS: one block, two blocks, three blocks is the whole point of a run
    #    of one picture per beat, and leaving it to a random draw meant a song
    #    could have a burst and never show it.
    used = []
    for n, (a, b) in enumerate(runs):
        counters = [m for m in ('count_up', 'count_down') if m in burst_pool]
        if n == 0 and counters:
            # Still counting first when the style allows counting at all; a style
            # whose burst pool has no counter (animals) takes its own motif
            # rather than being handed one it did not ask for.
            name = counters[0] if len(counters) == 1 else ('count_up' if (rng.random() < 0.7) else 'count_down')
        else:
            pool = [m for m in burst_pool if m not in used[-2:]] or burst_pool
            name = rng.choice(pool)
        used.append(name)
        gid = f'burst{n}'
        for k, (txt, spec) in enumerate(_norm(MOTIFS[name](b - a, rng, hero))):
            slots[a + k]['idea'] = txt
            slots[a + k]['source'] = 'motif'
            slots[a + k]['motif'] = name
            slots[a + k]['seed_group'] = gid
            slots[a + k]['draw'] = spec

    # 3. Every remaining slot, again in contiguous runs.  A motif not yet seen in
    #    this song always beats one already used: the deck exists to make the
    #    video various, and drawing 'shapes' three times out of nine runs is
    #    what an unweighted choice does.
    i, gi = 0, 0
    while i < len(slots):
        if slots[i]['idea']:
            i += 1
            continue
        j = i
        while j < len(slots) and not slots[j]['idea']:
            j += 1
        fresh = [m for m in fill_pool if m not in used]
        # The very first fill run introduces the HERO — a children's video meets
        # its character before it meets anything else.
        if gi == 0 and 'journey' in fresh:
            name = 'journey'
        else:
            pool = fresh or [m for m in fill_pool if m not in used[-2:]] or fill_pool
            name = rng.choice(pool)
        used.append(name)
        gid = f'fill{gi}'
        gi += 1
        for k, (txt, spec) in enumerate(_norm(MOTIFS[name](j - i, rng, hero))):
            slots[i + k]['idea'] = txt
            slots[i + k]['source'] = 'motif'
            slots[i + k]['motif'] = name
            slots[i + k]['draw'] = spec
            # A counting run only reads as counting if the blocks do not change
            # colour, size and background between pictures. Sharing one seed
            # across the run is what holds the composition still while only the
            # number moves.
            slots[i + k]['seed_group'] = gid if name in ('count_up', 'count_down', 'grow', 'colours') else ''
        i = j

    # NO TWO CONSECUTIVE SLOTS MAY CARRY THE SAME IDEA.  `_m_grow` clamping at
    # its last stage was one way to produce that; any future motif with a short
    # pool is another.  The consequence is not cosmetic — a repeated idea inside
    # a seed-locked run renders BYTE-IDENTICAL, so the cut between them shows
    # nothing at all.  Caught here, at the storyboard, rather than paid for in
    # GPU minutes: the duplicate is given a distinguishing framing and released
    # from the run's shared seed, so it is a different picture of the same thing.
    _ANGLES = [
        'seen from a little closer',
        'seen from a little further away',
        'seen from the side',
        'seen from slightly above',
        'with two more of them beside it',
        'against a warm sunset sky',
    ]
    dupes = 0
    for i in range(1, len(slots)):
        if slots[i]['idea'] and slots[i]['idea'] == slots[i - 1]['idea']:
            slots[i]['idea'] = f'{slots[i]["idea"]}, {_ANGLES[dupes % len(_ANGLES)]}'
            slots[i]['seed_group'] = ''
            dupes += 1
    if dupes:
        log_fn(
            f'ideas: {dupes} consecutive duplicate(s) varied — an identical '
            f'idea inside a seed-locked run renders an identical picture'
        )

    log_fn(
        f'ideas: {sum(1 for s in slots if s["source"] == "song")} from the song '
        f'(budget {story_budget} for {len(lyrics)} sung line(s)), '
        f'{sum(1 for s in slots if s["source"] == "motif")} from the motif deck '
        f'· hero "{hero}"'
    )
    return {
        'hero': hero,
        'llm': info,
        'story_budget': story_budget,
        'lyric_lines': len(lyrics),
        'consecutive_duplicates_varied': dupes,
        'drawn_by_design': sum(1 for s in slots if s.get('draw')),
        'from_song': sum(1 for s in slots if s['source'] == 'song'),
        'from_motifs': sum(1 for s in slots if s['source'] == 'motif'),
        'motifs_used': sorted({s['motif'] for s in slots if s['motif']}),
    }
