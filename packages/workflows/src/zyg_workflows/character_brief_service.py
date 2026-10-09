# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Sonnet character brief — permanent identity vs default presentation."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


logger = logging.getLogger(__name__)

CHAR_BRIEF_MODEL = os.environ.get('ZYG_CHAR_BRIEF_MODEL', 'claude-sonnet-4-6').strip()

# Permanent identity — stable across scenes / outfit changes.
IDENTITY_BRIEF_KEYS = (
    'hair_style',
    'hair_length',
    'hair_texture',
    'face_shape',
    'eye_shape',
    'eyebrow_style',
    'nose_shape',
    'lip_shape',
    'distinctive_marks',
    'ethnic_heritage',
)

# Default presentation — swappable per scene without changing who the person is.
PRESENTATION_BRIEF_KEYS = (
    'default_clothing',
    'default_expression',
    'accessories',
    'posture',
    'lighting_profile',
    'color_palette',
)

ACCESSORY_DECISION_KEYS = (
    'earrings',
    'necklace',
    'pendant',
    'watch',
    'bracelet',
    'glasses',
    'gloves',
    'rings',
    'belt',
    'hat',
)

_SYSTEM = """You are a character brief writer for a visual production pipeline.

You receive locked core fields plus a list of AUTO fields you must invent.
Your output drives image generation (ComfyUI / FLUX) and a persistent character bible.

CRITICAL — two layers (never merge them):

1) PERMANENT IDENTITY (stable forever — face, hair structure, marks)
   - face_shape, eye_shape, eyebrow_style, nose_shape, lip_shape
   - hair_length, hair_texture, hair_style (how hair is worn)
   - distinctive_marks, ethnic_heritage (optional)
   These must stay consistent even if the character later wears different clothes.

2) DEFAULT PRESENTATION (signature look for first preview — can change per scene later)
   - default_clothing, default_expression, accessories, posture
   - lighting_profile, color_palette (character-specific but genre-appropriate)

STUDIO PREVIEW CONTEXT (mandatory):
Images are plain gray studio previews — waist-up portrait, gray seamless backdrop,
solo subject, no props, no furniture, no outdoor scenery, no weapons, no battle poses.
Describe ONLY the person. Do NOT invent environments, combat gear, or dramatic action.

Rules:
- Output a single JSON object only. No markdown fences, no preamble.
- NEVER change locked fields: gender, age, hair_color, eye_color, skin_tone, height,
  muscle_mass, facial_hair, or any field the user explicitly set (not AUTO).
- Only fill identity / presentation keys marked AUTO in the input.
- Use controlled vocabulary for identity enums when possible:
  face_shape: oval|round|square|heart|long|diamond
  eye_shape: almond|round|hooded|monolid|upturned|downturned
  hair_length: shaved|short|medium|shoulder|long|waist-length
  hair_texture: straight|wavy|curly|coily|kinky
  nose_shape: balanced|aquiline|button|broad|narrow
  lip_shape: natural full|natural|thin|wide
  distinctive_marks: specific short phrase, or "none"
  When distinctive_marks is AUTO, prefer subtle natural texture (light freckles, faint
  under-eye texture, beauty mark, faint scar) when age-appropriate — avoid perfectly
  flawless skin unless user locked "none".
- lighting_profile: for photorealistic, use defined studio key with moderate shadows —
  avoid beauty-dish softbox / gauzy fill that hides skin texture.
- Vary within genre — do not copy the same outfit/jewelry for every character.
- accessory_decisions: explicit booleans + type strings per item.
  wear=false means omit from accessories string. wear=true requires a short type phrase.
  Valid items: earrings, necklace, pendant, watch, bracelet, glasses, gloves, rings, belt, hat
- If no jewelry at all, set accessories to "none" and all wear flags false where applicable.
- brief_prose: 2-4 sentences for humans/logs (may mention personality, not scenery).
- If USER CREATIVE NOTES or default_expression (LOCKED) request smiling/happy/cheerful,
  use a VISIBLE open smile with teeth — never downgrade to "soft half-smile" or "neutral confident".
- extra_prompt: REQUIRED for photorealistic — one sentence including visible skin pores,
  natural skin microdetail, unretouched, no beauty filter, fine film grain, minimal makeup.
  No scenery.
- voice_profile: optional narrator_hint + character_voice for downstream TTS (short phrases)."""

_USER_TEMPLATE = """=== LOCKED (do not change) ===
name: {name}
gender: {gender}
age: {age}
genre: {genre}
render_style: {style}
hair_color: {hair_color}
eye_color: {eye_color}
skin_tone: {skin_tone}
height_m: {height}
muscle_mass: {muscle_mass}
facial_hair: {facial_hair}

=== IDENTITY FIELDS ===
{identity_lines}

=== PRESENTATION FIELDS ===
{presentation_lines}

=== USER CREATIVE NOTES (respect smile/happy requests in default_expression) ===
extra_prompt: {extra_prompt}

Return JSON:
{{
  "brief_prose": "...",
  "identity": {{
    "hair_style": "...",
    "hair_length": "...",
    "hair_texture": "...",
    "face_shape": "...",
    "eye_shape": "...",
    "eyebrow_style": "...",
    "nose_shape": "...",
    "lip_shape": "...",
    "distinctive_marks": "...",
    "ethnic_heritage": "..."
  }},
  "presentation": {{
    "default_clothing": "...",
    "default_expression": "...",
    "accessories": "...",
    "posture": "...",
    "lighting_profile": "...",
    "color_palette": "..."
  }},
  "accessory_decisions": {{
    "earrings": {{"wear": true, "type": "small gold hoops"}},
    "necklace": {{"wear": false, "type": ""}},
    "pendant": {{"wear": false, "type": ""}},
    "watch": {{"wear": false, "type": ""}},
    "bracelet": {{"wear": false, "type": ""}},
    "glasses": {{"wear": false, "type": ""}},
    "gloves": {{"wear": false, "type": ""}},
    "rings": {{"wear": false, "type": ""}},
    "belt": {{"wear": false, "type": ""}},
    "hat": {{"wear": false, "type": ""}}
  }},
  "voice_profile": {{
    "narrator_hint": "...",
    "character_voice": "..."
  }},
  "extra_prompt": "..."
}}

Only include identity/presentation keys you are filling (AUTO fields). Omit keys the user locked."""


def _truthy(val: str | None) -> bool:
    return (val or '').strip().lower() in ('1', 'true', 'yes', 'on')


def brief_enabled() -> bool:
    return _truthy(os.environ.get('ZYG_CHAR_BRIEF', '1'))


def _is_auto(v: Any) -> bool:
    try:
        from zyg_workflows import character_bible_service as cbs

        return cbs._is_auto(v)
    except Exception:
        if v is None:
            return True
        if isinstance(v, str):
            s = v.strip().lower()
            return s in ('', 'auto', 'none-selected', 'default', '(auto)')
        return False


def _system_prompt() -> str:
    try:
        from zyg_workflows import pipeline_dsl_adapter as pda

        return pda.wrap_system_planner(_SYSTEM, 'character')
    except Exception:
        try:
            from zyg_workflows.caveman_style import inject_caveman_into_system_prompt

            return inject_caveman_into_system_prompt(_SYSTEM)
        except Exception:
            return _SYSTEM


def _parse_json(text: str) -> dict[str, Any] | None:
    raw = (text or '').strip()
    if raw.startswith('```'):
        raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.I)
        raw = re.sub(r'\s*```\s*$', '', raw)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        m = re.search(r'\{[\s\S]*\}', raw)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def _field_line(key: str, val: Any) -> str:
    if _is_auto(val):
        return f'{key}: AUTO (you decide)'
    s = str(val).strip() if val is not None else ''
    return f'{key}: {s} (LOCKED — do not change)'


def _wear_truthy(spec: Any) -> bool:
    if isinstance(spec, bool):
        return spec
    if isinstance(spec, dict):
        w = spec.get('wear')
        if isinstance(w, bool):
            return w
        if w is not None:
            return str(w).strip().lower() in ('true', 'yes', '1', 'on')
    return False


def flatten_accessory_decisions(decisions: dict[str, Any] | None) -> str:
    """Turn structured accessory_decisions into a prompt-safe accessories string."""
    if not decisions or not isinstance(decisions, dict):
        return ''
    parts: list[str] = []
    for item in ACCESSORY_DECISION_KEYS:
        spec = decisions.get(item)
        if not isinstance(spec, dict) or not _wear_truthy(spec):
            continue
        typ = (spec.get('type') or spec.get('description') or '').strip()
        if typ:
            parts.append(typ)
        else:
            parts.append(item.replace('_', ' '))
    if not parts:
        return 'none'
    return ', '.join(parts)


def _build_user_message(params: dict[str, Any]) -> str:
    identity_lines = '\n'.join(_field_line(k, params.get(k)) for k in IDENTITY_BRIEF_KEYS)
    presentation_lines = '\n'.join(_field_line(k, params.get(k)) for k in PRESENTATION_BRIEF_KEYS)
    return _USER_TEMPLATE.format(
        name=params.get('name', ''),
        gender=params.get('gender', ''),
        age=params.get('age', ''),
        genre=params.get('genre', ''),
        style=params.get('style') or params.get('render_style', ''),
        hair_color=params.get('hair_color', ''),
        eye_color=params.get('eye_color', ''),
        skin_tone=params.get('skin_tone', ''),
        height=params.get('height', ''),
        muscle_mass=params.get('muscle_mass', ''),
        facial_hair=params.get('facial_hair', 'none'),
        identity_lines=identity_lines,
        presentation_lines=presentation_lines,
        extra_prompt=(params.get('extra_prompt') or '').strip() or '(none)',
    )


def generate_character_brief(
    params: dict[str, Any],
    log_fn: Callable[[str], None] | None = None,
    token_record_fn: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any] | None:
    """Call Claude for a structured character brief. Returns parsed JSON or None."""
    log = log_fn or (lambda _m: None)
    if not brief_enabled():
        log('Character brief: disabled (ZYG_CHAR_BRIEF)')
        return None
    try:
        from zyg_workflows import character_bible_service as _cbs_sm

        params = _cbs_sm.apply_smile_intent(dict(params))
    except Exception:
        params = dict(params)
    api_key = (os.environ.get('ANTHROPIC_API_KEY') or '').strip()
    if not api_key:
        log('Character brief: skipped (no ANTHROPIC_API_KEY)')
        return None

    user_msg = _build_user_message(params)

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=CHAR_BRIEF_MODEL,
            max_tokens=1800,
            temperature=0.45,
            system=_system_prompt(),
            messages=[{'role': 'user', 'content': user_msg}],
        )
        text = ''
        if resp.content:
            text = getattr(resp.content[0], 'text', '') or ''
        usage = getattr(resp, 'usage', None)
        if token_record_fn and usage:
            try:
                token_record_fn(
                    CHAR_BRIEF_MODEL,
                    int(getattr(usage, 'input_tokens', 0) or 0),
                    int(getattr(usage, 'output_tokens', 0) or 0),
                )
            except Exception as _exc:
                _zyg_log.warning('token usage recording failed, brief tokens unaccounted: %s', _exc)
        parsed = _parse_json(text)
        if not parsed or not (parsed.get('brief_prose') or '').strip():
            log('Character brief: empty or unparseable response')
            return None
        log(f'Character brief: OK ({CHAR_BRIEF_MODEL}, {len(text)} chars)')
        return parsed
    except Exception as exc:
        logger.warning('character_brief failed: %s', exc)
        log(f'Character brief: failed ({exc})')
        return None


def merge_brief_into_params(
    params: dict[str, Any],
    brief: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge brief into params — only fills fields still on AUTO."""
    if not brief:
        return params
    out = dict(params)

    prose = (brief.get('brief_prose') or '').strip()
    if prose:
        out['character_brief_prose'] = prose

    identity = brief.get('identity') or {}
    if isinstance(identity, dict):
        for key in IDENTITY_BRIEF_KEYS:
            if not _is_auto(out.get(key)):
                continue
            val = (identity.get(key) or '').strip()
            if val:
                out[key] = val

    presentation = brief.get('presentation') or {}
    if not isinstance(presentation, dict):
        presentation = {}

    # Legacy top-level presentation keys (older brief format).
    for key in PRESENTATION_BRIEF_KEYS:
        if key not in presentation:
            legacy = (brief.get(key) or '').strip()
            if legacy:
                presentation[key] = legacy

    accessory_decisions = brief.get('accessory_decisions')
    if isinstance(accessory_decisions, dict) and accessory_decisions:
        out['accessory_decisions'] = accessory_decisions
        if _is_auto(out.get('accessories')):
            flat = flatten_accessory_decisions(accessory_decisions)
            if flat:
                out['accessories'] = flat

    for key in PRESENTATION_BRIEF_KEYS:
        if key == 'default_expression' and out.get('smile_locked'):
            continue
        if not _is_auto(out.get(key)):
            continue
        val = (presentation.get(key) or '').strip()
        if val:
            out[key] = val

    if out.get('smile_locked'):
        try:
            from zyg_workflows import character_bible_service as _cbs_sm

            out = _cbs_sm.apply_smile_intent(out)
        except Exception as _exc:
            _zyg_log.warning('smile intent application failed, keeping the unmodified brief: %s', _exc)

    extra = (brief.get('extra_prompt') or '').strip()
    if extra and _is_auto(out.get('extra_prompt')):
        out['extra_prompt'] = extra

    voice = brief.get('voice_profile') or {}
    if isinstance(voice, dict):
        vp: dict[str, str] = dict(out.get('voice_profile') or {})
        for vk in ('narrator_hint', 'character_voice'):
            vv = (voice.get(vk) or '').strip()
            if vv:
                vp[vk] = vv
        if vp:
            out['voice_profile'] = vp

    out = ensure_photoreal_skin_texture(out)
    return out


def ensure_photoreal_skin_texture(params: dict[str, Any]) -> dict[str, Any]:
    """Append skin-texture tokens to extra_prompt when photorealistic and missing."""
    style = (params.get('style') or params.get('render_style') or '').strip().lower()
    if style != 'photorealistic':
        return params
    try:
        from zyg_workflows import character_bible_service as bible

        skin_extra = bible.PHOTOREAL_SKIN_EXTRA
    except Exception:
        skin_extra = 'visible skin pores, natural skin microdetail, unretouched, fine film grain'
    extra = (params.get('extra_prompt') or '').strip()
    low = extra.lower()
    if not any(
        tok in low for tok in ('pore', 'unretouch', 'microdetail', 'skin grain', 'skin texture', 'no beauty filter')
    ):
        params = dict(params)
        params['extra_prompt'] = f'{extra}, {skin_extra}'.strip(', ') if extra else skin_extra
    return params
