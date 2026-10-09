# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""era_gate.checks — offline (deterministic) check derivation, the one-call LLM
check extraction and item assembly (verbatim from era_gate.py lines 310-580).
"""

from __future__ import annotations

import json
import re
from typing import Callable
import logging as _zyg_logging

from zyg_workflows.era_gate.constants import (
    GORE_ITEM,
    PERIOD_VOCAB,
    QUESTION_TEMPLATES,
    UNIVERSAL_ITEMS,
    _after_phrase,
    _KIND_TO_VOCAB,
    period_bucket,
)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.era_gate')

# ── offline (deterministic) check derivation ─────────────────────────────────
# Keyword -> (id, question, vocab key). The fallback when the API is down, and
# the floor the LLM extraction is compared against.
_OFFLINE_RULES = [
    (r'\b(boats?|ships?|vessels?|galleys?|cogs?|barges?|fishing|sailors?|harbou?r|quay|docks?)\b', 'boat'),
    (
        r'\b(tunics?|robes?|gowns?|cloaks?|dress(?:es)?|shirts?|hoods?|coats?|jerkins?|kirtles?|chemises?|garments?|clothing|clothes|wearing|dressed)\b',
        'clothing',
    ),
    (r'\b(shoes?|boots?|sandals?|feet|foot|barefoot|footwear)\b', 'footwear'),
    (r'\b(windows?|shutters?|panes?)\b', 'window'),
    (r'\b(maps?|charts?)\b', 'map'),
    (r'\b(carts?|wagons?|carriages?|wheels?)\b', 'cart'),
    (r'\b(streets?|roads?|lanes?|alleys?|pavement)\b', 'street'),
    (r'\b(lanterns?|lamps?|torch(?:es)?|candles?|lit|light|glow)\b', 'lighting'),
    (r'\b(jars?|bottles?|flasks?|vials?)\b', 'container'),
    (r'\b(fleas?|rats?|mice|insects?|animals?)\b', 'animal'),
]
_STAINED_RE = re.compile(r'\bstained[- ]glass\b', re.I)


def check_for_kind(kind: str, era: dict | None, fix: str = '', name: str = '') -> dict | None:
    """One check (id, question, fix) for an object KIND, from the fixed templates."""
    kind = re.sub(r'[^a-z]', '', str(kind or '').lower())
    q = QUESTION_TEMPLATES.get(kind)
    if not q:
        return None
    q = q.replace('{after}', _after_phrase(era))
    vocab = PERIOD_VOCAB[period_bucket(era)]
    fx = (fix or '').strip() or vocab.get(_KIND_TO_VOCAB.get(kind, ''), '')
    return {'id': f'obj_{kind}', 'question': q, 'fix': fx, 'kind': kind, 'name': name}


def derive_checks_offline(prompt: str, era: dict | None) -> list[dict]:
    """Prompt -> checkable objects, no API. Deterministic, order-stable."""
    out, seen = [], set()
    for pat, kind in _OFFLINE_RULES:
        if kind in seen:
            continue
        if not re.search(pat, prompt or '', re.I):
            continue
        if kind == 'window' and _STAINED_RE.search(prompt or ''):
            continue  # a cathedral's stained glass is period-correct
        if kind == 'lighting':
            continue  # covered by the universal era_electric tell
        c = check_for_kind(kind, era)
        if not c:
            continue
        seen.add(kind)
        c['source'] = 'offline'
        out.append(c)
        if len(out) >= 5:
            break
    return out


def subject_phrase_offline(prompt: str) -> str:
    """First clause of the prompt, stripped of the style lead — what the shot is of."""
    t = re.sub(r'^\s*(?:cinematic photograph|photograph)\s*', '', prompt or '', flags=re.I)
    t = re.split(r'[,;.]', t, maxsplit=1)[0]
    words = t.split()
    return ' '.join(words[:14]).strip() or 'the prompted scene'


# ── LLM check extraction (one call per batch) ────────────────────────────────


def extract_checks(
    prompts: list[str],
    era: dict | None,
    api_key: str = '',
    model: str = 'claude-haiku-4-5-20251001',
    log: Callable | None = None,
    chunk: int = 20,
    record_usage: Callable | None = None,
) -> list[dict]:
    """For each S prompt: {'subject': str, 'checks': [{'id','question','fix'}], 'source'}.

    One Haiku call per `chunk` prompts. Every slot always gets an entry: on any
    failure the offline derivation fills in, so the caller never sees a hole.
    """

    def _l(m):
        if log:
            try:
                log(m)
            except Exception as _exc:
                _zyg_log.debug('log callback failed: %s', _exc)

    era = era or {}
    n = len(prompts)
    out = [
        {'subject': subject_phrase_offline(p), 'checks': derive_checks_offline(p, era), 'source': 'offline'}
        for p in prompts
    ]
    if not api_key or not n:
        return out
    b = period_bucket(era)
    anchors = ''.join(f'  - {a}\n' for a in (era.get('anchors') or []))
    try:
        from zyg_workflows.subscription_llm import anthropic_client as _sub_client

        client = _sub_client(api_key)
    except Exception as e:
        _l(f'era_gate: anthropic unavailable ({e!r}) — offline checks')
        return out
    for lo in range(0, n, chunk):
        hi = min(n, lo + chunk)
        lines = '\n'.join(f'  Slot {i + 1}: "{(prompts[i] or "")[:700]}"' for i in range(lo, hi))
        kinds = ', '.join(sorted(QUESTION_TEMPLATES))
        msg = (
            f'You are the period-accuracy supervisor for a historical documentary set in '
            f'{era.get("period_label") or "the stated period"} ({b.replace("_", " ")}).\n'
            + (f'Period anchors for this exact time and place:\n{anchors}\n' if anchors else '')
            + 'A diffusion model renders these image prompts. It renders any object it is not '
            'told about with a MODERN default: "vessel" becomes a motor boat, "lantern" a gas '
            'lamp, "shoe" a sneaker, "bracelet" a wristwatch, any head without a described '
            'hairstyle a 2020s haircut, "plague sites marked on a map" virus icons.\n\n'
            'For EACH prompt below, list the KINDS of object it names that carry that risk, '
            f'choosing ONLY from this list: {kinds}. For each give "kind", "name" (the noun '
            'as the prompt wrote it) and "fix": a positive 8-16 word phrase describing the '
            'period-correct version of that object for this era, using the anchors, never '
            '"no X". Do not write questions — they are fixed per kind.\n'
            'Also give "subject": the main subject as a BARE noun phrase of at most 6 words '
            '— a person, object, animal or place as it would be named by someone who sees the '
            'picture (e.g. "a sick sailor on a quay", "a physician in a beaked mask"). NO '
            'actions, symptoms, states, emotions or details that might not be visible.\n\n'
            'Return ONLY JSON, no prose:\n'
            '{"slots":[{"slot":<n>,"subject":"...","objects":[{"kind":"boat","name":"fishing '
            'vessel","fix":"..."}]}]}\n'
            'Between 1 and 5 objects per slot; do not invent objects the prompt does not name.\n\n' + lines
        )
        try:
            r = client.messages.create(
                model=model, max_tokens=8000, temperature=0.0, messages=[{'role': 'user', 'content': msg}]
            )
            raw = re.sub(r'```(?:json)?|```', '', r.content[0].text).strip()
            if record_usage:
                try:
                    record_usage(model, r.usage.input_tokens, r.usage.output_tokens)
                except Exception as _exc:
                    _zyg_log.warning('token usage recording failed, this era-gate call is unaccounted: %s', _exc)
            m = re.search(r'\{.*\}', raw, re.S)
            d = json.loads(m.group(0) if m else raw)
            got = 0
            for s in d.get('slots') or []:
                try:
                    i = int(s.get('slot')) - 1
                except (AttributeError, TypeError, ValueError) as _exc:
                    _zyg_log.debug('slot index unparseable, skipping the slot: %s', _exc)
                    continue
                if not (lo <= i < hi):
                    continue
                checks, kinds_seen = [], set()
                for c in (s.get('objects') or s.get('checks') or [])[:6]:
                    ck = check_for_kind(
                        str(c.get('kind') or ''), era, fix=str(c.get('fix') or ''), name=str(c.get('name') or '')
                    )
                    if not ck or ck['kind'] in kinds_seen:
                        continue
                    kinds_seen.add(ck['kind'])
                    ck['source'] = 'llm'
                    checks.append(ck)
                    if len(checks) >= 5:
                        break
                subj = ' '.join(str(s.get('subject') or '').strip().split()[:8])
                if checks or subj:
                    out[i] = {
                        'subject': subj or out[i]['subject'],
                        'checks': checks or out[i]['checks'],
                        'source': 'llm' if checks else 'offline',
                    }
                    got += 1
            _l(f'era_gate: checks extracted for {got}/{hi - lo} slots ({lo + 1}-{hi})')
        except Exception as e:
            _l(f'era_gate: extraction failed for slots {lo + 1}-{hi} ({e!r}) — offline checks')
    return out


# ── item assembly ────────────────────────────────────────────────────────────


def _resolve_fix(fix: str, era: dict | None) -> str:
    if fix.startswith('@'):
        return PERIOD_VOCAB[period_bucket(era)].get(fix[1:], '')
    return fix


def build_items(
    slot_checks: dict | None,
    era: dict | None,
    *,
    include_gore: bool = True,
    include_subject: bool = True,
    include_universal: bool = True,
) -> list[dict]:
    """Assemble the vlm_inspector item list for one slot.

    'scope' decides which images each question sees: 'tiles' -> the six crops,
    'frame' -> the full frame. Every item is expected 'no' except the subject
    check, which is expected 'yes'.
    """
    items: list[dict] = []
    sc = slot_checks or {}
    for c in sc.get('checks') or []:
        items.append(
            {
                'id': c['id'],
                'question': c['question'],
                'expected': 'no',
                'severity': 'critical',
                'grounding': True,
                'scope': 'tiles',
                'fix': _resolve_fix(c.get('fix') or '', era),
                'small': False,
                'source': c.get('source', 'offline'),
            }
        )
    if include_universal:
        _aft = _after_phrase(era)
        _aft_neg = ('before ' + _aft.replace('after ', '')) if _aft.startswith('after') else 'in the period'
        for u in UNIVERSAL_ITEMS:
            items.append(
                {
                    'id': u['id'],
                    'question': u['question'].replace('{after}', _aft).replace('{after_neg}', _aft_neg),
                    'expected': 'no',
                    'severity': u.get('severity', 'critical'),
                    'grounding': True,
                    'scope': 'tiles',
                    'fix': _resolve_fix(u['fix'], era),
                    'small': u['small'],
                    'source': 'universal',
                }
            )
    if include_gore:
        items.append(
            {
                'id': GORE_ITEM['id'],
                'question': GORE_ITEM['question'],
                'expected': 'no',
                'severity': 'critical',
                'grounding': True,
                'scope': 'tiles',
                'fix': GORE_ITEM['fix'],
                'small': False,
                'source': 'universal',
            }
        )
    if include_subject:
        subj = str(sc.get('subject') or '').strip()
        if subj:
            items.append(
                {
                    'id': 'subject_present',
                    'question': (
                        f'Is there {subj} visible somewhere in this image? Answer '
                        f'yes if the thing itself is present, even if small or '
                        f'partly hidden; answer no only if it is absent or replaced '
                        f'by something else.'
                    ),
                    'expected': 'yes',
                    'severity': 'major',
                    'grounding': False,
                    'scope': 'frame',
                    'fix': f'{subj} clearly visible and central in frame',
                    'small': False,
                    'source': 'subject',
                }
            )
    return items
