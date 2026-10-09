# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Lyrics: the local fallback, the Opus brief and the writer that picks between them.

Moved verbatim out of the old single-file kids_music_service.py (lines 1398-1859).
"""

from __future__ import annotations

import os
import re
from zyg_workflows import kids_llm
from zyg_workflows import paths
from zyg_workflows import kids_music_theory as T

from zyg_workflows.kids_music_service.base import _log_noop

# ── Lyrics ───────────────────────────────────────────────────────────────────

_OLLAMA = paths.ZYG_OLLAMA_URL.rstrip('/')
_LYRIC_MODEL = os.environ.get('ZYG_KIDSMUSIC_LLM', 'qwen3.5:9b')

_BANNED = re.compile(
    r'\b(kill|die|dead|death|blood|gun|hate|stupid|dumb|ugly|fat|drunk|drug|'
    r'sex|damn|hell)\b',
    re.IGNORECASE,
)


def _fallback_lyrics(brief, n_lines):
    """A template lyric, used when the LLM is down or its answer is unusable.

    Deliberately plain. It exists so a song is never blocked on a language model
    — an instrumental with a placeholder lyric is a deliverable, a failed run is
    not — and the manifest records that the fallback was used.
    """
    theme = (brief.get('theme') or 'a happy little day').strip().rstrip('.')
    short = _theme_phrase(theme, brief)
    base = [
        f'Here we go with {short}',
        'Everybody sing along',
        f'{short.capitalize()} every day',
        'Clap your hands and join the song',
    ]
    return [base[i % len(base)] for i in range(n_lines)]


def _fallback_facts_lyrics(brief, n_lines):
    """Template facts lines, same escape hatch as `_fallback_lyrics` but for
    'facts' mode: the subject repeated with a generic property so a facts song
    still ships instrumental-shaped rather than blocking on the LLM."""
    subject = (brief.get('subject') or brief.get('theme') or 'this').strip().rstrip('.')
    subject = subject[0].upper() + subject[1:] if subject else 'It'
    base = [
        f'{subject} goes choochoo',
        f'{subject} has a part',
        f'{subject} has a shape',
        f'{subject} goes round and round',
    ]
    return [base[i % len(base)] for i in range(n_lines)]


# Articles and prepositions that must not be left dangling at the end of a
# trimmed phrase — "a dinosaur who lost" is a sentence fragment, and a fragment
# is what a listener hears.
_DANGLING = {
    'a',
    'an',
    'the',
    'and',
    'or',
    'but',
    'with',
    'to',
    'of',
    'in',
    'on',
    'at',
    'for',
    'his',
    'her',
    'its',
    'their',
    'my',
    'your',
    'our',
    'who',
    'that',
    'which',
    'is',
    'was',
    'lost',
    'got',
    'has',
}
_STOPWORDS = {
    'a',
    'an',
    'the',
    'and',
    'or',
    'but',
    'with',
    'to',
    'of',
    'in',
    'on',
    'at',
    'for',
    'who',
    'that',
    'which',
    'is',
    'was',
    'his',
    'her',
    'its',
    'their',
    'my',
    'your',
    'our',
}


def _theme_phrase(theme, brief):
    """The theme as a singable phrase, trimmed on a WORD boundary to the age
    band's syllable ceiling.

    The old rule was `' '.join(theme.split()[:4])` — a fixed four-word cut with
    no regard for syllables or for where the sense ends. It shipped: "a dinosaur
    who lost his socks" became "a dinosaur who lost", and the resulting twelve
    lines never once mention the socks. whisper-medium at 0.917 recall confirms
    that is what is sung.

    Three rules, in order:
      * drop a leading article — it costs a syllable and carries no meaning;
      * take as many whole words as the band's syllable ceiling allows;
      * never end on a dangling function word, and if trimming leaves nothing
        usable, fall back to the last two CONTENT words, which is where the
        subject of a phrase like this actually lives.
    """
    words = [w for w in str(theme or '').split() if w]
    if not words:
        return 'a happy little day'
    if words[0].lower() in ('a', 'an', 'the') and len(words) > 1:
        words = words[1:]

    band = T.AGE_BANDS.get((brief or {}).get('age_band') or 'preschool', T.AGE_BANDS['preschool'])
    # Leave room for the carrier ("Here we go with ..." is 5 syllables).
    budget = max(3, band['syllables'][1] - 3)

    kept, used = [], 0
    for w in words:
        c = max(1, T.count_syllables(w))
        if kept and used + c > budget:
            break
        kept.append(w)
        used += c
    while kept and kept[-1].lower().strip('.,!?') in _DANGLING:
        kept.pop()

    # If the budget cut off the tail, try to buy the phrase's LAST content word
    # back. That word is usually the thing the song is about — "socks" in "a
    # dinosaur who lost his socks" — and a theme phrase that names the subject
    # but not the object is the exact failure that shipped.
    content = [w for w in words if w.lower().strip('.,!?') not in _STOPWORDS]
    if kept and content and content[-1] not in kept:
        tail = content[-1]
        c = max(1, T.count_syllables(tail))
        used_now = sum(max(1, T.count_syllables(w)) for w in kept)
        while kept and used_now + c > budget and len(kept) > 1:
            used_now -= max(1, T.count_syllables(kept.pop()))
        # Popping can leave a function word stranded before the tail
        # ("...with lots" + "bubbles"), so strip again before joining.
        while len(kept) > 1 and kept[-1].lower().strip('.,!?') in _DANGLING | {'lots', 'that'}:
            used_now -= max(1, T.count_syllables(kept.pop()))
        if used_now + c <= budget:
            kept.append(tail)

    if not kept:
        kept = content[-2:] or words[-2:]
    return ' '.join(kept)


# ── The Opus brief ───────────────────────────────────────────────────────────
#
# A second prompt, for the model on the operator's subscription (kids_llm). The
# local 9B prompt below is left byte-identical because it is the FALLBACK and a
# fallback that drifts is a second bug to find; this one is written for a model
# that can hold the whole form in its head, so it carries what the 9B prompt had
# to leave out: the section map with the chorus marked, each line's own syllable
# target, the filter that silently drops a line, and the fact — true since the
# 2026-10-02 cadence change — that EVERY line becomes a picture and then a clip.

_LYRIC_SYSTEM = (
    "You are the lyricist of a children's music channel. You write the words that a "
    'three-to-six-year-old will sing back after hearing them twice: concrete, warm, '
    'singable, nothing clever for the grown-ups. You know that the returning hook is '
    'what a child learns first and that a line naming something they can picture beats '
    'a line naming something they must understand. Reply with one JSON object and '
    'nothing else — no preamble, no commentary, no markdown fences.'
)

_LYRIC_BANNED_WORDS = 'kill, die, dead, death, blood, gun, hate, stupid, dumb, ugly, fat, drunk, drug, sex, damn, hell'


def _section_map(order, syllables, n_lines):
    """The shape of the song as the lyricist must see it: which lines belong to which
    section, which of them are the chorus, and what each line's syllable budget is.

    Two lines per section, which is what the caller's `n_lines = len(order) * 2` and
    `lyrics_block` both assume. 'B' is the chorus — `lyrics_block` tags B as [chorus] and
    everything else as [verse] — and every B in the order gets the SAME two lines, because
    positional lines meant a four-section song had two different "choruses" and therefore
    no chorus at all.
    """
    order = list(order or [])
    rows, chorus_at = [], []
    for i, name in enumerate(order):
        a, b = i * 2 + 1, i * 2 + 2
        if a > n_lines:
            break
        kind = 'CHORUS' if name == 'B' else 'verse '
        syl = [syllables[j - 1] for j in (a, b) if 0 < j <= len(syllables)]
        budget = ' and '.join(str(int(s)) for s in syl) or 'as above'
        rows.append(f'  lines {a}-{b}   {kind} (section {name})   about {budget} syllables')
        if name == 'B':
            chorus_at.append((a, b))
    out = '\n'.join(rows)
    if len(chorus_at) > 1:
        pairs = ' and '.join(f'{a}-{b}' for a, b in chorus_at)
        out += (
            f'\nLines {pairs} are the SAME chorus: write those two lines once and '
            f'repeat them word for word at every return. That repeat is the hook — '
            f'it is the part a child sings in the car.'
        )
    elif len(chorus_at) == 1:
        a, b = chorus_at[0]
        out += (
            f'\nLines {a}-{b} are the chorus: they must be the catchiest, simplest '
            f'lines in the song and they must name the subject.'
        )
    return out


def _lyric_prompt_opus(brief, n_lines, syllables, order, target, lo, hi, facts_mode, hint):
    """The subscription model's brief. Same JSON contract as the local prompt."""
    band = T.AGE_BANDS[brief['age_band']]
    style = T.STYLES.get(brief.get('style')) if isinstance(brief.get('style'), str) else None
    subject = (brief.get('subject') or brief.get('theme') or '').strip() or 'it'
    head = [
        (
            "An EDUCATIONAL children's song that teaches facts about one subject."
            if facts_mode
            else "A children's song."
        ),
        f'Subject: {subject}' if facts_mode else f'Topic: {brief["theme"]}',
        f'Audience: {band["label"]}',
        f'Mood: {T.MOODS[brief["mood"]]["label"]}',
        f'Length: about {int(brief.get("seconds") or 60)} seconds, sung.',
    ]
    if style:
        head.append(f'Style: {style["label"]}')
    smap = _section_map(order, syllables, n_lines)
    rules = [
        f'every line is between {lo} and {hi} syllables, as close to its own target above '
        f'as you can get it (the melody is written to that budget before the words are '
        f'sung, so a long line is squeezed and a short one leaves the bar empty);',
        f'words a {band["label"].lower()} child already uses; present tense; no made-up words;',
        'something CONCRETE happens in every line — a thing, an action, a sound you could '
        'point at. The pipeline draws ONE PICTURE for every line and then animates it, so a '
        'line that names nothing visible becomes a picture of nothing;',
        'repeat a key phrase across the song so it is easy to learn;',
        'end rhymes in pairs (1-2, 3-4, and so on) — true rhymes, not near ones;',
        'nothing frightening, nothing about death, illness, violence or money; no brand '
        "names; no irony and no jokes aimed over the child's head;",
        f'never use these words — the pipeline deletes any line containing one and replaces '
        f'it with a template line: {_LYRIC_BANNED_WORDS};',
        'no line over 90 characters; no section labels, stage directions or parentheses inside a line.',
    ]
    if facts_mode:
        rules.insert(
            1,
            f'EVERY line names the subject ("{subject}") and states exactly one '
            f'simple, true, concrete fact about it — a part it has, a sound it '
            f'makes, something it does — in the SAME short sentence pattern '
            f'("{subject} has ...", "{subject} goes ...") every line, and no two '
            f'lines repeat a fact;',
        )
    if hint:
        rules.append(hint.rstrip() if hint.rstrip().endswith((';', '.')) else hint.rstrip() + '.')
    return (
        '\n'.join(head)
        + '\n\n'
        + f'Write exactly {n_lines} sung lines (average {target} syllables).\n\n'
        # No `order` (an external caller, or a form with no sections) ⇒ no map rather than an
        # empty heading: a heading with nothing under it reads as a dropped instruction.
        + ("The song's shape — two lines per section, in this order:\n" + smap + '\n\n' if smap else '')
        + 'Rules:\n'
        + '\n'.join(f'- {r}' for r in rules)
        + '\n\n'
        + 'Also invent a title of at most 6 words, cheerful and plain.\n'
        + 'Reply with exactly this JSON and nothing else:\n'
        + '{"title": "...", "lines": ['
        + ', '.join(['"..."'] * min(n_lines, 4))
        + (', ...' if n_lines > 4 else '')
        + f']}}  — exactly {n_lines} strings in "lines".'
    )


def write_lyrics(brief, n_lines, syllables, *, order=None, log_fn=None):
    """Ask for a children's lyric on a syllable budget.

    Opus 5 on the operator's subscription first, the local model second, the template
    last — `kids_llm` owns that order and the reason for it. `order` is the composer's
    section pattern; it reaches the subscription prompt as the section map (which lines
    are the chorus) and is ignored by the local prompt, which has not changed.

    Returns (lines, title, source, info) where source is 'llm', 'llm (padded)'
    or 'fallback', and `info` carries why a fallback happened and which JSON keys
    the model actually used — the fallback branch used to log nothing at all, so
    a third of runs silently shipped a template lyric with no trace.
    """
    log_fn = log_fn or _log_noop
    lo, hi = T.AGE_BANDS[brief['age_band']]['syllables']
    target = int(round(sum(syllables) / max(1, len(syllables)))) if syllables else (lo + hi) // 2
    facts_mode = brief.get('lyrics_mode') == 'facts'
    # The style's lyric hint rides on the END of the Rules sentence of whichever
    # prompt runs, so it is read as one more rule rather than as a competing
    # instruction. Note that lyrics_mode 'counting' is NOT facts_mode: it takes
    # the theme prompt, and the counting rule reaches the model only through
    # this hint. Empty hint (or no style) ⇒ the prompts are byte-identical to
    # what they were before the style layer.
    _hint = T.lyric_hint_for(brief)
    _rules_tail = f' {_hint}\n' if _hint else '\n'
    if facts_mode:
        # One repeated grammar, one new fact per line — "Train has a
        # conductor / Train has wheels / Train goes on rails" — rather than a
        # narrative. Paired with FORMS['AAAA'] (one melodic phrase reused for
        # every line) this is what makes the song teach a fact per repeat
        # instead of advancing a story. See [[project-kids-music-workflow]].
        subject = (brief.get('subject') or brief.get('theme') or '').strip() or 'it'
        prompt = (
            'You write an EDUCATIONAL song for young children that lists facts '
            'about one subject. Reply with JSON only.\n'
            f'Subject: {subject}\n'
            f'Audience: {T.AGE_BANDS[brief["age_band"]]["label"]}\n'
            f'Mood: {T.MOODS[brief["mood"]]["label"]}\n'
            f'Write exactly {n_lines} short lines. Each line must be about {target} '
            f'syllables (between {lo} and {hi}).\n'
            f'Rules: EVERY line names the subject ("{subject}") and states exactly '
            'one simple, true, concrete fact about it — a part it has, a sound it '
            'makes, or something it does (e.g. "Train has a conductor", "Train has '
            'wheels", "Train goes on rails"); use the SAME short sentence pattern '
            f'("{subject} has/goes ...") every line so it is easy to learn; no two '
            'lines repeat the same fact; everyday words a small child knows; '
            'present tense; nothing frightening, nothing about death, illness, '
            'violence or money; no brand names.' + _rules_tail + 'Also invent a short cheerful title (max 6 words).\n'
            '{"title": "...", "lines": ["...", "..."]}'
        )
    else:
        prompt = (
            'You write lyrics for young children. Reply with JSON only.\n'
            f'Topic: {brief["theme"]}\n'
            f'Audience: {T.AGE_BANDS[brief["age_band"]]["label"]}\n'
            f'Mood: {T.MOODS[brief["mood"]]["label"]}\n'
            f'Write exactly {n_lines} short lines. Each line must be about {target} '
            f'syllables (between {lo} and {hi}).\n'
            'Rules: everyday words a small child knows; present tense; concrete '
            'actions and objects; repeat a key phrase across lines so it is easy to '
            'learn; lines 1-2 and 5-6 should rhyme in pairs; nothing frightening, '
            'nothing about death, illness, violence or money; no brand names.'
            + _rules_tail
            + 'Also invent a short cheerful title (max 6 words).\n'
            '{"title": "...", "lines": ["...", "..."]}'
        )
    # Opus 5 on the subscription, then the local model, then the template. The local
    # payload (temperature, num_predict, num_ctx, the qwen3.x think:false trap, the
    # /api/version probe) moved into kids_llm UNCHANGED — the comment that used to sit on
    # it is there now. Do not swap the local model for gpt-oss: with format:json it
    # returns nothing at all.
    data, llm_info = kids_llm.ask_json(
        opus_prompt=_lyric_prompt_opus(brief, n_lines, syllables, order, target, lo, hi, facts_mode, _hint),
        ollama_prompt=prompt,
        system=_LYRIC_SYSTEM,
        stage='kidsmusic_lyrics',
        max_tokens=2000,
        options={'temperature': 0.85, 'num_predict': 700, 'num_ctx': 4096},
        ollama_timeout=180,
        label='lyrics',
        log_fn=log_fn,
    )
    reason = llm_info.get('reason') or ''

    lines, title, keys_seen = [], '', []
    if isinstance(data, dict):
        # CASE-FOLD THE KEYS. qwen returns {"Lines": [...], "Title": ...} about
        # a third of the time — 5 of 16 live POSTs with this module's exact
        # payload — and the old code read data['lines'], got nothing, and fell
        # silently through to the template. One probe threw away 42 perfectly
        # good lines that way. `verses` is accepted as an alias for the same
        # reason: it is what the model reaches for when "lines" is taken.
        keys_seen = sorted(str(k) for k in data)
        low = {str(k).strip().lower(): v for k, v in data.items()}
        title = str(low.get('title') or low.get('name') or '')[:80]
        raw_lines = low.get('lines') or low.get('lyrics') or low.get('verses') or []
        if isinstance(raw_lines, str):
            raw_lines = [x for x in raw_lines.splitlines() if x.strip()]
        for x in list(raw_lines)[:n_lines]:
            ln = re.sub(r'\s+', ' ', str(x)).strip(' .,;:"\'')[:90]
            if ln and not _BANNED.search(ln):
                lines.append(ln)
        if not lines:
            reason = f'model replied with keys {keys_seen} and no usable lines'
            log_fn(f'lyrics: {reason}')

    if len(lines) < n_lines:
        if lines:
            # Pad from the model's OWN lines, not the generic template: a
            # half-filled lyric padded with "Everybody sing along" reads as a
            # song about nothing, while repeating the real lines reads as a
            # chorus — which is what a children's song does anyway.
            log_fn(f'lyrics: model returned {len(lines)}/{n_lines} usable lines — repeating its own lines to fill')
            src = 'llm (padded)'
            # `lines[len(lines) % max(1, len(lines))]` was n % n — ALWAYS 0 — so
            # padding three lines to eight produced five consecutive copies of
            # line 0 rather than cycling A,B,C,A,B. The cycle length must be
            # captured BEFORE the list starts growing.
            n_orig = len(lines)
            while len(lines) < n_lines:
                lines.append(lines[len(lines) % n_orig])
            reason = reason or f'model returned {n_orig}/{n_lines} lines'
        else:
            lines += (_fallback_facts_lyrics if facts_mode else _fallback_lyrics)(brief, n_lines - len(lines))
            src = 'fallback'
            reason = reason or 'model returned no usable lines'
    else:
        src = 'llm'
    # `model` is the model that ACTUALLY answered, not the one configured: a song written by
    # the local fallback after a weekly-limit refusal must not read back as an Opus song.
    return (
        lines[:n_lines],
        title,
        src,
        {
            'reason': reason,
            'keys_seen': keys_seen,
            'model': llm_info.get('model') or _LYRIC_MODEL,
            'backend': llm_info.get('backend') or 'ollama',
            'fallback_backend': bool(llm_info.get('fallback')),
            'seconds': llm_info.get('seconds'),
            'input_tokens': llm_info.get('input_tokens'),
            'output_tokens': llm_info.get('output_tokens'),
            'asked': n_lines,
            'got': len(lines),
        },
    )


def lyrics_block(lines, order):
    """ACE-Step lyric field: sections tagged so the model knows where the chorus
    is.  Two lines per 4-bar section, matching the composer's line budget.

    A section with no words is SKIPPED rather than emitted as a bare tag. The old
    version wrote the tag first and only then looked for lines, so a lyric that
    ran short — which the 32-line cap guaranteed on any song over ~110 s —
    produced a run of naked [verse] markers with nothing under them, and that is
    what went to ACE-Step. Ten of twenty-one sections were wordless at 180 s.
    """
    out = []
    for i, name in enumerate(order):
        words = [lines[i * 2 + j] for j in range(2) if i * 2 + j < len(lines) and str(lines[i * 2 + j]).strip()]
        if not words:
            continue
        out.append('[chorus]' if name in ('B',) else '[verse]')
        out.extend(words)
    return '\n'.join(out)
