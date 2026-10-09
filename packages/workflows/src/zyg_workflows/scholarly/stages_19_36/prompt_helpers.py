# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The six small nested helpers of Stage 3.5, lifted out of `stage_10_flux_image_generation`.

Each body below is the byte-for-byte range of the single file; the enclosing
`_make_*` wrapper only re-creates the closure the nested `def` used to get
from its stage function, so the inner code is unchanged down to the indent.
"""

from ._common import (
    _LLM_SMALL,
    _SEED_STOPWORDS,
    _bench_replay_get,
    _llm_client,
    _llm_key,
    _log_prompt,
    _record_token_usage,
    _register_prompt,
)


def _make_is_hook_slot(_sch_intensity):
    """Build `_is_hook_slot` over the stage locals it closed over."""

    def _is_hook_slot(idx: int) -> bool:
        return idx == 0 and _sch_intensity['hook_rank'] >= 2

    return _is_hook_slot


def _make_extract_named_entities(_re_flux_sub):
    """Build `_extract_named_entities` over the stage locals it closed over."""

    def _extract_named_entities(text: str) -> str:
        """
        Pull proper nouns (capitalized word sequences) from a text block.
        Returns the most prominent entity as a string for use in FLUX prompts.
        Prefers multi-word names (battles, places, people) over single words.
        Filters out sentence-opening stopwords and incomplete fragments.
        """
        # Words that are capitalized purely because they open a sentence — not real entities
        _STOPWORDS = {
            'The',
            'This',
            'These',
            'That',
            'Those',
            'It',
            'He',
            'She',
            'They',
            'We',
            'One',
            'Thus',
            'However',
            'Moreover',
            'Furthermore',
            'Although',
            'While',
            'When',
            'Where',
            'What',
            'Which',
            'Who',
            'How',
            'If',
            'As',
            'But',
            'So',
            'In',
            'Of',
            'At',
            'On',
            'For',
            'To',
            'By',
            'From',
            'With',
            'And',
            'Or',
            'Professor',
            'Doctor',
            'Chapter',
            'Section',
            'Figure',
            'Table',
            'Nevertheless',
            'Even',
            'Indeed',
            'Also',
            'Yet',
            'Still',
            'Hence',
            'Ibid',
            'Idem',
            'Cf',
            'See',
            'Note',
            'Vol',
            'Press',
            'University',
            'London',
            'Oxford',
            'Cambridge',
            'Berlin',
            'Warsaw',
            'Department',
        }
        # Find capitalized word sequences including "of the / at / de" connectors
        _raw = _re_flux_sub.findall(
            r'\b([A-Z][a-z]{2,}(?:\s+(?:of|the|at|de|von|bin|ibn|van)\s+[A-Z][a-z]{2,})?'
            r'(?:\s+[A-Z][a-z]{2,}){0,2})\b',
            text,
        )
        _counts = {}
        for c in _raw:
            # Skip pure stopwords
            if c.strip() in _STOPWORDS:
                continue
            # Single-word entities only count if they appear 2+ times (avoid sentence-starters)
            if len(c.split()) == 1:
                _counts[c] = _counts.get(c, 0) + 1
            else:
                _counts[c] = _counts.get(c, 0) + 2  # multi-word gets bonus weight
        # Filter single-word entities that only appeared once (likely sentence-starters)
        _filtered = {k: v for k, v in _counts.items() if len(k.split()) > 1 or v >= 2}
        if not _filtered:
            # Last resort: any single-word non-stopword entity. The common-
            # word filter matters here: this branch promoted sentence-
            # openers ("Most", "There", "What", "You") to seed-locked
            # "identities" (P-09).
            _filtered = {k: v for k, v in _counts.items() if k not in _STOPWORDS and k.lower() not in _SEED_STOPWORDS}
        if not _filtered:
            return ''
        # Score: multi-word = higher, repeated = higher
        _scored = sorted(_filtered.items(), key=lambda x: len(x[0].split()) * 3 + x[1], reverse=True)
        return _scored[0][0]

    return _extract_named_entities


def _make_sentence_event_tag():
    """Build `_sentence_event_tag` (it closes over nothing)."""

    def _sentence_event_tag(sentence: str) -> str:
        """
        Detect history-specific event types from a sentence.
        Returns a tag key from _FLUX_PROMPT_TEMPLATES if found, else ''.
        """
        _sl = sentence.lower()
        _event_keywords = {
            'battle': ['battle', 'fought', 'clash', 'skirmish', 'combat', 'engagement', 'warfare'],
            'conquest': ['conquer', 'conquest', 'subjugat', 'defeated', 'overthrew', 'captured', 'seized'],
            'leader': ['general', 'commander', 'led', 'leadership', 'strateg'],
            'emperor': ['emperor', 'imperator', 'caesar', 'augustus', 'basileus'],
            'king': ['king', 'monarch', 'ruler', 'sovereign', 'rex'],
            'death': ['death', 'died', 'assassinat', 'executed', 'perished', 'fell in battle'],
            'fall': ['fell', 'fall of', 'collapse of', 'destruction of', 'sacked', 'burned'],
            'collapse': ['collapse', 'decline', 'disintegrat', 'crumbled', 'end of the'],
            'religion': ['temple', 'priest', 'sacrifice', 'worship', 'deity', 'gods', 'ritual', 'sacred'],
            'ritual': ['ceremony', 'ritual', 'feast', 'coronation', 'burial'],
            'voyage': ['ship', 'fleet', 'sail', 'voyage', 'sea', 'naval', 'expedition'],
            'exploration': ['explor', 'discover', 'journey', 'expedition', 'travell'],
            'trade': ['trade', 'merchant', 'silk road', 'caravan', 'market', 'commerce', 'goods'],
            'map': ['territory', 'borders', 'region', 'province', 'map', 'frontier'],
            'diplomacy': ['treaty', 'negotiat', 'envoy', 'ambassador', 'diplomat', 'peace agreement'],
            'alliance': ['alliance', 'ally', 'coalition', 'pact', 'confederacy'],
            'invasion': ['invad', 'invasion', 'crossing', 'marched into', 'advanced on'],
            'siege': ['siege', 'besieg', 'wall', 'fortif', 'rampart', 'catapult'],
            'plague': ['plague', 'epidemic', 'disease', 'pestilence', 'pandemic'],
            'migration': ['migrat', 'fled', 'displacement', 'exodus', 'moved across'],
        }
        for _etag, _kws in _event_keywords.items():
            if any(_kw in _sl for _kw in _kws):
                return _etag
        return ''

    return _sentence_event_tag


def _make_get_claude_scene_description(_is_modern_topic, pipeline_id, topic):
    """Build `_get_claude_scene_description` over the stage locals it closed over."""

    def _get_claude_scene_description(seg_text: str, fallback: str, recent_descs: list = None) -> str:
        """
        Ask Claude Haiku to write a single specific visual scene description
        for a narration block. This replaces generic keyword-template prompts
        with story-accurate, per-image FLUX anchors so every image is unique.
        Falls back to `fallback` if the API call fails or Claude refuses.
        Uses a topic-adaptive prompt: historical style for history/war topics,
        cinematic documentary style for modern/medical/general topics.
        """
        # Benchmark replay: return a cached refined prompt instead of calling Claude.
        _rep_ref = _bench_replay_get('stage_3_5_refined_prompt')
        if _rep_ref:
            return _rep_ref

        _ak = _llm_key()
        if not _ak or not seg_text.strip():
            return fallback

        # Choose prompt style based on topic type
        if _is_modern_topic:
            _style_instruction = (
                'Write exactly ONE sentence (15–22 words) describing a specific visual scene '
                'for a cinematic documentary. '
                'Describe EXACTLY what could be shown on screen for this passage — '
                'a person, an object, a location, or an abstract visual metaphor. '
                'Be concrete and visual. Use natural, photorealistic settings — '
                'rooms, people, light, nature, close-ups, wide shots. '
                'VARY the visual approach each time — alternate between close-ups, wide shots, '
                'indoor/outdoor, people/objects/landscapes so consecutive images look different. '
                'Never refuse. Never explain. Output only the visual scene description.'
            )
        else:
            _style_instruction = (
                'Write exactly ONE sentence (15–22 words) describing the specific '
                'visual scene for a historical oil painting or cinematic illustration. '
                'Show EXACTLY what is happening in this passage. '
                'Name the specific person or group, their action, and the location. '
                'Be concrete and visual. Use period-accurate details only — stone, wood, '
                'torchlight, horses, robes, armour, parchment, etc. '
                'Never mention modern objects. No art-style words. No abstract concepts.'
            )

        _register_prompt(
            'scene_description',
            'Claude Scene Description',
            'Claude Sonnet 4.6 generates all FLUX prompt anchors in one batched call '
            '(10-part cinematic framework, Murch arc briefs), replacing generic keyword templates',
            _style_instruction + '\n\nPassage: "[narration segment — injected at runtime, up to 600 chars]"',
            pipeline_id=pipeline_id,
            stage='Stage 3.5',
            topic=topic,
        )
        try:
            _c = _llm_client(_ak)
            _haiku_user_msg = (
                _style_instruction
                + (
                    '\n\nRecent scenes already used (create something visually DIFFERENT):\n'
                    + '\n'.join(f'- {d}' for d in (recent_descs or []))
                    if recent_descs
                    else ''
                )
                + f'\n\nPassage: "{seg_text[:600]}"'
            )
            _log_prompt(
                'claude_scene_desc',
                'Stage 3.5',
                pipeline_id,
                _haiku_user_msg,
                meta={'topic': topic, 'pipeline_type': 'scholarly'},
                direction='sent',
                role='user',
                llm=_LLM_SMALL,
                from_who='system',
                to_who=_LLM_SMALL,
                system_prompt=_style_instruction,
            )
            _r = _c.messages.create(
                model=_LLM_SMALL,
                max_tokens=80,
                temperature=0.8,
                messages=[{'role': 'user', 'content': _haiku_user_msg}],
            )
            _desc = _r.content[0].text.strip().strip('"').rstrip('.')
            _log_prompt(
                'claude_scene_desc',
                'Stage 3.5',
                pipeline_id,
                _desc,
                meta={'topic': topic, 'pipeline_type': 'scholarly'},
                direction='received',
                role='assistant',
                llm=_LLM_SMALL,
                from_who=_LLM_SMALL,
                to_who='system',
            )
            _record_token_usage(
                model=_LLM_SMALL,
                prompt_tokens=_r.usage.input_tokens,
                completion_tokens=_r.usage.output_tokens,
                pipeline_id=pipeline_id,
                stage='Stage 3.5',
                pipeline_type='scholarly',
            )
            # Guard: reject Claude refusals — they start with "I cannot" / "I can't" / "I'm unable"
            _dl = _desc.lower()
            if (
                _dl.startswith('i cannot')
                or _dl.startswith("i can't")
                or _dl.startswith("i'm unable")
                or _dl.startswith('i am unable')
                or _dl.startswith("i'm sorry")
                or _dl.startswith('i apologize')
                or 'cannot write' in _dl[:60]
                or "can't write" in _dl[:60]
                or 'cannot create' in _dl[:60]
                or "can't create" in _dl[:60]
            ):
                return fallback
            return _desc if len(_desc.split()) >= 5 else fallback
        except Exception:
            return fallback

    return _get_claude_scene_description


def _make_shot_size_of():
    """Build `_shot_size_of` (it closes over nothing)."""

    def _shot_size_of(shot: str) -> str:
        """Collapse a shot descriptor to its framing size.

        'medium shot, cinematic' and 'medium shot, somber' are the same
        framing wearing different adjectives; the diversity enforcer has to
        compare these, not the raw strings.
        """
        _s = (shot or '').lower()
        if 'extreme close' in _s:
            return 'xcu'
        if 'close-up' in _s or 'close up' in _s:
            return 'cu'
        if 'over-the-shoulder' in _s:
            return 'ots'
        if 'medium wide' in _s:
            return 'mws'
        if 'medium' in _s:
            return 'ms'
        if 'overhead' in _s or 'drone' in _s or "bird's eye" in _s:
            return 'aerial'
        if 'wide' in _s or 'establishing' in _s:
            return 'ws'
        if 'dutch' in _s:
            return 'dutch'
        if 'low-angle' in _s or 'low angle' in _s:
            return 'low'
        return _s[:12] or 'unknown'

    return _shot_size_of


def _make_slot_word_bounds(narration_script, pipeline_state):
    """Build `_slot_word_bounds` over the stage locals it closed over."""

    def _slot_word_bounds(idx: int, n_total: int) -> tuple:
        """Word-index bounds (w0, w1) of slot idx over the narration script."""
        _nw_sb = len(narration_script.split())
        _fwt_sb = pipeline_state.get('final_word_timings') or []
        _tdur_sb = pipeline_state.get('tts_duration') or 0
        # Mostly-interpolated timings are not timings (P-09): on the silent
        # smoke run 1,720 of 1,740 words "landed" in the first 15 s and
        # slots 1-2 got 7 and 13 words. Below a 50 % Whisper match (or with
        # no timings at all) the even word split is the honest approximation.
        _wmr_raw_sb = pipeline_state.get('whisper_match_ratio')
        try:
            _wmr_sb = 1.0 if _wmr_raw_sb is None else float(_wmr_raw_sb)
        except (TypeError, ValueError):
            _wmr_sb = 1.0
        if _fwt_sb and _tdur_sb and _wmr_sb >= 0.5:
            _t0_sb = idx * _tdur_sb / max(n_total, 1)
            _t1_sb = (idx + 1) * _tdur_sb / max(n_total, 1)
            _w0_sb = sum(1 for _p_sb in _fwt_sb if _p_sb[1] < _t0_sb)
            _w1_sb = sum(1 for _p_sb in _fwt_sb if _p_sb[1] < _t1_sb) if idx < n_total - 1 else len(_fwt_sb)
            return min(_w0_sb, _nw_sb), min(max(_w1_sb, _w0_sb + 1), _nw_sb)
        _w0_sb = idx * _nw_sb // max(n_total, 1)
        _w1_sb = (idx + 1) * _nw_sb // max(n_total, 1) if idx < n_total - 1 else _nw_sb
        return _w0_sb, max(_w1_sb, _w0_sb + 1)

    return _slot_word_bounds
