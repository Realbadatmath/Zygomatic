# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The "auto" sentinel, bible paths and the smile/expression vocabulary."""

from __future__ import annotations

import os
import re
from typing import Any

from zyg_workflows import paths


_DATASET_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')
_OUTPUT_ROOT = str(paths.ZYG_LORA_OUTPUTS / 'storyteller_chars')
_BIBLE_FILENAME = 'character_bible.json'
_SCHEMA_VERSION = 3

# ── Sentinel value meaning "let the auto-defaults engine pick" ───────────────
AUTO = 'auto'


def _is_auto(v: Any) -> bool:
    """True if a value should be replaced by the auto-defaults engine."""
    if v is None:
        return True
    if isinstance(v, str):
        s = v.strip().lower()
        return s in ('', 'auto', 'none-selected', 'default', '(auto)')
    return False


def text_requests_smile(text: str | None) -> bool:
    return bool(_SMILE_HINT_RE.search(text or ''))


def expression_has_smile(expr: str | None) -> bool:
    low = (expr or '').strip().lower()
    if not low:
        return False
    return any(
        tok in low
        for tok in (
            'smile',
            'smiling',
            'grin',
            'grinning',
            'cheerful',
            'happy',
            'beaming',
            'joyful',
        )
    )


def format_expression_for_prompt(expr: str | None) -> str:
    """Format default_expression for diffusion prompts without doubling 'expression'."""
    e = (expr or '').strip().rstrip('., ')
    if not e:
        return ''
    if e.lower().endswith(' expression'):
        return e
    return f'{e} expression'


def resolve_open_smile_expression(params: dict[str, Any]) -> str:
    """Pick a strong smile phrase from UI / genre context."""
    raw = (params.get('default_expression') or '').strip().lower()
    if raw == 'warm welcoming':
        return SMILE_EXPRESSION_WARM
    if raw == 'playful':
        return SMILE_EXPRESSION_PLAYFUL
    if raw in ('happy smiling', 'smiling', 'happy smile'):
        return SMILE_EXPRESSION_OPEN
    return SMILE_EXPRESSION_OPEN


def apply_smile_intent(params: dict[str, Any]) -> dict[str, Any]:
    """Lock a visible smile when the user asks for one (extra prompt or UI)."""
    out = dict(params)
    expr = (out.get('default_expression') or '').strip()
    extra = (out.get('extra_prompt') or '').strip()

    if not _is_auto(expr) and _SERIOUS_EXPR_RE.search(expr) and not expression_has_smile(expr):
        return out

    wants = bool(out.get('smile_locked') or out.get('smile_requested'))
    if not wants:
        if not _is_auto(expr) and expression_has_smile(expr):
            wants = True
        elif not _is_auto(expr) and expr.lower() in (
            'warm welcoming',
            'playful',
            'happy smiling',
            'smiling',
            'happy smile',
        ):
            wants = True
        elif text_requests_smile(extra) or (_is_auto(expr) and text_requests_smile(extra)):
            wants = True
        elif _is_auto(expr) and text_requests_smile(expr):
            wants = True

    if not wants:
        return out

    if _is_auto(expr) or not expression_has_smile(expr) or 'half-smile' in expr.lower():
        out['default_expression'] = resolve_open_smile_expression(out)
    out['smile_locked'] = True
    out['smile_requested'] = True
    return out


def wants_visible_smile(params: dict[str, Any] | None) -> bool:
    if not params:
        return False
    if params.get('smile_locked') or params.get('smile_requested'):
        return True
    expr = params.get('default_expression') or ''
    return expression_has_smile(expr) or text_requests_smile(params.get('extra_prompt') or '')


def wants_visible_smile_package(package: dict[str, Any] | None) -> bool:
    if not package:
        return False
    cond = package.get('conditioning') or {}
    if cond.get('smile_locked') or cond.get('smile_requested'):
        return True
    style = package.get('style_profile') or {}
    pres = package.get('default_presentation') or {}
    expr = style.get('default_expression') or pres.get('default_expression') or ''
    return expression_has_smile(expr)


def face_detail_wildcard_for_params(params: dict[str, Any] | None) -> str:
    """FaceDetailer wildcard: skin texture + smile tokens when requested."""
    skin = (
        'visible skin pores, natural skin microdetail, fine facial texture, '
        'realistic subsurface skin, sharp eyelashes, detailed iris, natural skin grain, '
        'unretouched, no beauty filter, subtle skin imperfections'
    )
    if not wants_visible_smile(params):
        return skin
    expr = format_expression_for_prompt(
        (params or {}).get('default_expression') or SMILE_EXPRESSION_OPEN,
    )
    return f'{skin}, {expr}, visible teeth, natural smile lines'


def preview_expression_boost(params: dict[str, Any] | None) -> str:
    """Extra preview prompt tokens when a visible smile was requested."""
    if not wants_visible_smile(params):
        return ''
    bits: list[str] = []
    expr = format_expression_for_prompt((params or {}).get('default_expression') or '')
    if expr:
        bits.append(expr)
    extra = ((params or {}).get('extra_prompt') or '').strip()
    if extra and text_requests_smile(extra):
        bits.append(extra[:160])
    if not bits:
        bits.append(format_expression_for_prompt(SMILE_EXPRESSION_OPEN))
    return ', '.join(bits)


def bible_path(char_id: str) -> str:
    return os.path.join(_DATASET_ROOT, char_id, _BIBLE_FILENAME)


# No 'cinematic lighting' / '8k' here: on FLUX those tokens pull toward the
# polished beauty-render cluster (waxy, poreless skin) — 2026-07-09 audit.
PHOTOREAL_STYLE_PHRASE = (
    'photorealistic, film photography, natural skin texture, visible pores, unretouched, fine film grain'
)

# Strong, model-readable smile wording (avoid weak "half-smile" for user requests).
SMILE_EXPRESSION_OPEN = (
    'warm open smile, visible teeth, cheerful happy expression, '
    'eyes slightly squinted with smile lines, smiling at camera'
)
SMILE_EXPRESSION_WARM = 'warm welcoming smile, visible teeth, friendly cheerful expression, smiling at camera'
SMILE_EXPRESSION_PLAYFUL = 'playful bright smile, visible teeth, cheerful expression, smiling at camera'

_SMILE_HINT_RE = re.compile(
    r'\b(smil(?:e|ing|es|ed|y)|grin(?:ning|s|ned)?|happy|cheerful|joyful|beaming)\b',
    re.IGNORECASE,
)
_SERIOUS_EXPR_RE = re.compile(
    r'\b(serious|stern|contemplative|determined|measured|neutral confident|'
    r'neutral mouth|tension at jaw|attentive)\b',
    re.IGNORECASE,
)
