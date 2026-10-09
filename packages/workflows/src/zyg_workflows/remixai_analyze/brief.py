# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.remixai_analyze.brief — verbatim from remixai_analyze.py lines 335-761.

section 2 — transcript to STRUCTURAL brief (word ceilings, sanitising,
prose rendering, analyze_transcript) and the script rewriter
"""

from __future__ import annotations

import json
import os
import re
from zyg_workflows.remixai_analyze import llm as _zyg_llm

# Bound by ASSIGNMENT, never by `from … import`: CPython 3.12 refuses the
# method-call optimisation for an import-bound global, so `NAME.attr(...)`
# inside the moved code would compile to different bytecode than it did in
# the single-file remixai_analyze.py.
_llm = _zyg_llm._llm


# ── 2. transcript → STRUCTURAL brief ────────────────────────────────────────

_BEATS_PROMPT = """You are analysing a video transcript to build a BRIEF that lets a
different writer cover the same subject accurately, in their own words.

Two rules govern everything below.

1. RECORD THE SUBSTANCE. Claims, figures, named things, the shape of the
   argument, what each beat is FOR. A writer working from this brief must be
   able to be as accurate and as specific as the original was.
2. RECORD NO SENTENCES. Never quote, paraphrase or lightly edit the
   transcript's own wording. Restate every claim as a short proposition in
   neutral words. If a field would run long, you are writing prose — compress it
   to the bare proposition instead.

Every free-text field has a word ceiling. Respect it; overlong fields are
discarded, which loses the substance you were asked to capture.

Return JSON exactly:
{"topic": "the subject, <=12 words",
 "angle": "the specific take or claim, <=18 words",
 "audience": "who this is for, <=10 words",
 "register": "tone, 2-4 words",
 "hook_type": "one of: question / bold claim / countdown / story open / statistic / contrast",
 "beat_count": <integer>,
 "beats": [{"label": "what this beat covers, <=10 words",
            "purpose": "one of: hook / setup / evidence / turn / payoff / objection / rebuttal / cta",
            "covers": ["the specific points made here, each <=8 words, max 4"],
            "seconds": <number>}],
 "claims": [{"claim": "a standalone proposition, <=16 words",
             "kind": "fact / opinion / prediction / recommendation",
             "support": "what backs it, <=12 words"}],
 "figures": [{"value": "the number or quantity as stated",
              "measures": "what it quantifies, <=10 words"}],
 "entities": [{"name": "the named tool, product, person or technique",
               "kind": "tool / product / person / org / technique",
               "role": "why it matters here, <=8 words"}],
 "argument": {"premise": "<=15 words", "support": "<=15 words",
              "conclusion": "<=15 words", "objection": "<=15 words",
              "rebuttal": "<=15 words"},
 "pacing": {"words_per_minute": <int>, "avg_beat_seconds": <number>},
 "cta": "what the ending asks of the viewer, <=15 words, or empty string",
 "key_facts": ["standalone factual claims the topic requires, each <=16 words, max 8"]}"""


# Word ceilings per field. These are the structural guarantee that an ENRICHED
# brief stays a brief: a genuine abstraction fits comfortably inside them, and a
# lifted sentence does not. Values that overrun are dropped (list items) or
# trimmed (fields the brief cannot do without), and the count is logged.
# TIGHTENED 2026-08-29 after a test drove a 24-word lifted sentence straight
# through the original 25-word `argument` ceiling untouched. A cap is a cheap
# structural filter, not a guarantee — no ceiling stops a lift SHORTER than
# itself — so these sit at the smallest size a genuine datum needs, and the
# brief's own divergence check (analyze_transcript) is what actually catches
# what fits underneath them.
_BRIEF_CAPS = {
    'topic': 12,
    'angle': 18,
    'audience': 10,
    'register': 6,
    'cta': 15,
    'beat.label': 10,
    'beat.purpose': 12,
    'beat.covers': 8,
    'claim.claim': 16,
    'claim.support': 12,
    'figure.value': 8,
    'figure.measures': 10,
    'entity.name': 6,
    'entity.role': 8,
    'argument': 15,
    'key_fact': 16,
}
_BRIEF_REQUIRED = ('topic', 'angle', 'audience', 'register', 'cta')


def _cap(val, limit):
    """(kept_or_trimmed_value, overran?) — None when it should be dropped."""
    t = re.sub(r'\s+', ' ', str(val or '')).strip()
    if not t:
        return '', False
    return (t, False) if len(t.split()) <= limit else (t, True)


def _sanitize_brief(brief: dict, log=None) -> dict:
    """Enforce the word ceilings. A field that overruns is prose, not a datum.

    Required scalars are TRIMMED (the brief is unusable without a topic), and
    everything optional is DROPPED, because a partial enrichment is safe while a
    smuggled sentence is not. The count is logged rather than swallowed: a brief
    that keeps losing items means the extraction prompt is drifting toward prose
    and wants looking at, not silently tolerating."""
    dropped = trimmed = 0

    def take(val, limit, required=False):
        nonlocal dropped, trimmed
        t, over = _cap(val, limit)
        if not over:
            return t
        if required:
            trimmed += 1
            return ' '.join(t.split()[:limit])
        dropped += 1
        return None

    out = dict(brief or {})
    for k in _BRIEF_REQUIRED:
        out[k] = take(out.get(k), _BRIEF_CAPS[k], required=True) or ''

    beats = []
    for b in (out.get('beats') or [])[:24]:
        if not isinstance(b, dict):
            continue
        lab = take(b.get('label'), _BRIEF_CAPS['beat.label'])
        if lab is None:
            continue
        covers = [c for c in (take(x, _BRIEF_CAPS['beat.covers']) for x in (b.get('covers') or [])[:4]) if c]
        beats.append(
            {
                'label': lab,
                'purpose': take(b.get('purpose'), _BRIEF_CAPS['beat.purpose']) or '',
                'covers': covers,
                'seconds': b.get('seconds'),
            }
        )
    out['beats'] = beats

    claims = []
    for c in (out.get('claims') or [])[:12]:
        if not isinstance(c, dict):
            continue
        cl = take(c.get('claim'), _BRIEF_CAPS['claim.claim'])
        if cl is None:
            continue
        claims.append(
            {
                'claim': cl,
                'kind': (c.get('kind') or '')[:20],
                'support': take(c.get('support'), _BRIEF_CAPS['claim.support']) or '',
            }
        )
    out['claims'] = claims

    figs = []
    for f in (out.get('figures') or [])[:12]:
        if not isinstance(f, dict):
            continue
        v = take(f.get('value'), _BRIEF_CAPS['figure.value'])
        m = take(f.get('measures'), _BRIEF_CAPS['figure.measures'])
        if v is None or m is None:
            continue
        figs.append({'value': v, 'measures': m})
    out['figures'] = figs

    ents = []
    for e in (out.get('entities') or [])[:12]:
        if not isinstance(e, dict):
            continue
        n = take(e.get('name'), _BRIEF_CAPS['entity.name'])
        if n is None:
            continue
        ents.append(
            {
                'name': n,
                'kind': (e.get('kind') or '')[:20],
                'role': take(e.get('role'), _BRIEF_CAPS['entity.role']) or '',
            }
        )
    out['entities'] = ents

    arg = out.get('argument') if isinstance(out.get('argument'), dict) else {}
    out['argument'] = {
        k: (take(arg.get(k), _BRIEF_CAPS['argument']) or '')
        for k in ('premise', 'support', 'conclusion', 'objection', 'rebuttal')
    }

    out['key_facts'] = [k for k in (take(x, _BRIEF_CAPS['key_fact']) for x in (out.get('key_facts') or [])[:8]) if k]

    out['_sanitizer'] = {'dropped': dropped, 'trimmed': trimmed}
    if log and (dropped or trimmed):
        log(f'brief sanitiser: {dropped} field(s) dropped as over-long, {trimmed} required field(s) trimmed')
    return out


def brief_prose(brief: dict) -> str:
    """Every free-text value in the brief, concatenated. This is what the brief's
    own divergence check measures — the enrichment must not become a route by
    which the source's wording reaches the writer."""
    bits = [str(brief.get(k) or '') for k in _BRIEF_REQUIRED]
    for b in brief.get('beats') or []:
        bits += [b.get('label') or '', b.get('purpose') or ''] + list(b.get('covers') or [])
    for c in brief.get('claims') or []:
        bits += [c.get('claim') or '', c.get('support') or '']
    for f in brief.get('figures') or []:
        bits += [f.get('value') or '', f.get('measures') or '']
    for e in brief.get('entities') or []:
        bits += [e.get('name') or '', e.get('role') or '']
    bits += list((brief.get('argument') or {}).values())
    bits += list(brief.get('key_facts') or [])
    return ' '.join(x for x in bits if x)


def analyze_transcript(segments: list, duration_s: float, log=None, source_text: str = '') -> dict:
    """Transcript → an ENRICHED structural brief.

    The brief now carries the source's SUBSTANCE — claims, figures, named
    entities, the argument's shape, what each beat is for — because a writer
    given only beat labels produces something accurate about the topic but thin
    about the subject. What it still carries NO amount of is the source's
    WORDING: every field is a short structured datum under an enforced word
    ceiling (see _sanitize_brief), and this function then measures the assembled
    brief against the transcript itself. Enriching the brief is exactly the
    change that could turn it into a prose channel, so it is the change that
    gets its own gate.

    `regenerate_script()` still takes this brief and nothing else."""
    if not segments:
        return {}
    text = source_text or ' '.join((s.get('text') or '').strip() for s in segments)
    words = len(text.split())
    wpm = int(words / max(0.5, duration_s / 60.0)) if duration_s else 0

    res, src = _llm(_BEATS_PROMPT + f'\n\nTRANSCRIPT:\n{text[:9000]}', num_predict=2600, stage='remixai-beats')
    if not res:
        return {}
    res = _sanitize_brief(res, log=log)
    res.setdefault('pacing', {})
    if not isinstance(res['pacing'], dict):
        res['pacing'] = {}
    res['pacing']['words_per_minute'] = res['pacing'].get('words_per_minute') or wpm
    res['source_word_count'] = words
    res['source_duration_s'] = round(duration_s, 2)
    res['llm'] = src

    # THE BRIEF'S OWN DIVERGENCE CHECK. Named entities and figures legitimately
    # match the source (that is the point of recording them), so the ceilings are
    # a little looser than the script's — but a brief that shares five-word runs
    # with the transcript is quoting it, and no amount of downstream care fixes
    # a contaminated brief.
    try:
        from zyg_workflows import remixai_divergence as RD

        rep = RD.check(brief_prose(res), text, thresholds={'containment_5gram': 0.030, 'longest_shared_run': 10})
        res['brief_divergence'] = {
            'verdict': rep['verdict'],
            'failed': rep['failed'],
            'metrics': {
                k: rep['metrics'].get(k) for k in ('containment_5gram', 'longest_shared_run', 'max_sentence_cosine')
            },
        }
        if log:
            m = rep['metrics']
            log(
                f'brief divergence {rep["verdict"].upper()}: containment '
                f'{m["containment_5gram"]:.4f}, longest run {m["longest_shared_run"]}w'
                + (f' — BREACHED {", ".join(rep["failed"])}' if rep['failed'] else '')
            )
    except Exception as e:
        res['brief_divergence'] = {'verdict': 'unavailable', 'error': str(e)[:120]}
        if log:
            log(f'brief divergence check unavailable: {e}')

    if log:
        log(
            f'brief ({src}): "{res.get("topic", "")}" · {len(res.get("beats") or [])} beat(s) '
            f'· {len(res.get("claims") or [])} claim(s) · {len(res.get("figures") or [])} figure(s) '
            f'· {len(res.get("entities") or [])} entity(ies) · {res.get("hook_type", "?")} hook '
            f'· {wpm} wpm'
        )
    return res


_SCRIPT_PROMPT = """Write an ORIGINAL short-form video script.

You are given a BRIEF: a subject, a proven structure, and the substance the
subject requires — the claims to make, the figures to cite, the things to name,
and the shape of the argument. You have never seen the video this brief was
built from and must not try to reconstruct it. Write fresh copy in your own
words.

Be SPECIFIC. The brief lists claims, figures and named tools precisely so the
script can be as concrete as the subject deserves — a script that covers the
topic in generalities while the brief hands you exact numbers has wasted them.
Use the figures as given; do not invent new ones, and do not round them away.

Requirements:
- Cover the beats in a sensible order, each serving the PURPOSE the brief gives it.
- Open with a {hook_type} hook.
- Register: {register}
- Target {target_words} words total (about {target_seconds} seconds spoken).
- {beat_n} beats. Each beat is 1-3 spoken sentences.
- Plain spoken English. No stage directions, no emoji, no markdown, no speaker labels.

Return JSON exactly:
{{"beats": [{{"label": "...", "text": "the spoken line(s) for this beat",
   "visual": "a 15-30 word description of what should be on screen here"}}],
 "cta": "closing line, or empty string"}}"""


# Measured delivery rate of the narration stack, words per minute. IndexTTS-2
# measured 141 wpm over 493 words / 210.4 s on the first real job (2026-08-29).
# One sample, so it is env-overridable and every run logs what it actually got —
# re-derive from `tts_wpm_measured` in the manifests as they accumulate.
_TTS_WPM_DEFAULT = 141


def _tts_wpm() -> int:
    try:
        return max(90, min(220, int(os.environ.get('ZYG_REMIXAI_TTS_WPM', '') or _TTS_WPM_DEFAULT)))
    except ValueError:
        return _TTS_WPM_DEFAULT


# How much of the brief reaches the writer. MEASURED, not a taste setting:
#
#   minimal  beat labels + key_facts. The pre-enrichment payload. On the test
#            source its scripts gated clean at containment 0.0000 / 4-word run.
#   lean     adds beat PURPOSE + COVERS, FIGURES and ENTITIES — short factual
#            data (a name, a number, what it measures). This is the substance a
#            writer actually needs to be specific, in the form least able to
#            carry someone else's phrasing. DEFAULT.
#   full     adds CLAIMS (16-word propositions) and the ARGUMENT block (five
#            15-word fields). On the test source this measurably pushed the
#            script into reproducing source wording: the lexical gate breached
#            containment_5gram AND longest_shared_run on three consecutive
#            attempts, where the same source at `minimal` had passed at 0.0000.
#            The brief itself was clean (0.0048 / 5w) — it is handing the writer
#            restated PROSE, however short, that does the damage. Available
#            because it is the most faithful to the source's substance, but it
#            is the setting most likely to be refused at the gate.
#
# The gate is never the thing to relax to make a level work. If `full` will not
# pass, that is the answer, not the obstacle.
_BRIEF_LEVELS = ('minimal', 'lean', 'full')


def _brief_level() -> str:
    lv = (os.environ.get('ZYG_REMIXAI_BRIEF_LEVEL', 'lean') or 'lean').strip().lower()
    return lv if lv in _BRIEF_LEVELS else 'lean'


def _brief_for_writer(brief: dict, beat_n: int, level: str = None) -> dict:
    """The exact payload handed to the writer.

    Assembled explicitly, field by field, rather than by passing the brief
    through: the writer's input is a closed list that can be read off in one
    place, and a future field added to the brief cannot reach the prompt without
    someone deciding it should. Note what is NEVER here at any level — no
    transcript, no segment text, no source title."""
    level = level or _brief_level()
    out = {
        'topic': brief.get('topic', ''),
        'angle': brief.get('angle', ''),
        'audience': brief.get('audience', ''),
        'key_facts': (brief.get('key_facts') or [])[:8],
        'cta': brief.get('cta', ''),
    }
    beats = (brief.get('beats') or [])[:beat_n]
    if level == 'minimal':
        out['beats'] = [{'label': b.get('label', '')} for b in beats]
        return out

    out['beats'] = [
        {'label': b.get('label', ''), 'purpose': b.get('purpose', ''), 'covers': b.get('covers') or []} for b in beats
    ]
    out['figures'] = brief.get('figures') or []
    out['entities'] = brief.get('entities') or []
    if level == 'full':
        out['claims'] = brief.get('claims') or []
        out['argument'] = brief.get('argument') or {}
    return out


def regenerate_script(brief: dict, target_seconds: float, log=None, extra_instruction: str = '') -> dict:
    """Brief → NEW script. Takes the structural brief ONLY; there is no parameter
    through which source wording could reach this call.

    `extra_instruction` carries a DIVERGENCE RETRY note from remixai_divergence
    when a previous draft scored too close to the material the brief was
    abstracted from. It describes what to avoid — it never carries the source
    text itself, so the retry path cannot become a back door for the wording the
    signature above is designed to keep out. (The one exception is a short
    offending phrase quoted back as a ban, capped at 10 words; that is our OWN
    previous draft's wording, which is what has to change.)"""
    if not brief:
        return {}
    # Budget words at OUR NARRATOR'S rate, not the source presenter's. The first
    # real run budgeted from the source's 158 wpm and overshot its 180 s target
    # by 21% (217.7 s): the script hit its word count exactly, but IndexTTS-2
    # delivered 493 words in 210.4 s — 141 wpm. How fast the person in the source
    # video talks says nothing about how fast our voice talks. The source rate
    # stays in the brief (it signals how DENSE the format is, which informs beat
    # count) but the duration budget uses the measured TTS rate.
    wpm = _tts_wpm()
    target_words = max(30, int(target_seconds * wpm / 60.0))
    beat_n = max(3, min(int(brief.get('beat_count') or len(brief.get('beats') or []) or 5), 14))
    _lvl = _brief_level()
    prompt = (
        _SCRIPT_PROMPT.format(
            hook_type=brief.get('hook_type', 'bold claim'),
            register=brief.get('register', 'clear, conversational'),
            target_words=target_words,
            target_seconds=int(target_seconds),
            beat_n=beat_n,
        )
        + '\n\nBRIEF:\n'
        + json.dumps(_brief_for_writer(brief, beat_n, _lvl), ensure_ascii=False)
    )
    if extra_instruction:
        prompt += '\n\nIMPORTANT — REVISION NOTE:\n' + extra_instruction
    res, src = _llm(prompt, num_predict=2400, stage='remixai-script')
    if not res or not res.get('beats'):
        return {}
    for b in res['beats']:
        b['text'] = re.sub(r'\s+', ' ', str(b.get('text') or '')).strip()
    res['beats'] = [b for b in res['beats'] if b['text']]
    res['word_count'] = sum(len(b['text'].split()) for b in res['beats'])
    res['source'] = src
    res['brief_level'] = _lvl
    if log:
        log(
            f'script ({src}, brief={_lvl}): {len(res["beats"])} beat(s), '
            f'{res["word_count"]} words (target {target_words} @ {wpm} wpm)'
        )
    return res
