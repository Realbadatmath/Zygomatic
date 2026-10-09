# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Vision-based character photo analysis — form auto-fill + LoRA training captions."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from difflib import get_close_matches
from typing import Any, Callable

from zyg_workflows import paths

logger = logging.getLogger(__name__)


# ── Feature flag ───────────────────────────────────────────────────────────────
def analysis_enabled() -> bool:
    return os.environ.get('ZYG_CHAR_PHOTO_ANALYSIS', '1').strip().lower() not in (
        '0',
        'false',
        'no',
        'off',
    )


CHAR_PHOTO_MODEL = os.environ.get(
    'ZYG_CHAR_PHOTO_MODEL',
    os.environ.get('ZYG_CHAR_BRIEF_MODEL', 'claude-sonnet-4-6'),
).strip()


def prefer_ollama() -> bool:
    """When true (default), use local Qwen before Claude to keep photo analysis at $0."""
    return os.environ.get('ZYG_CHAR_PHOTO_PREFER_OLLAMA', '1').strip().lower() not in (
        '0',
        'false',
        'no',
        'off',
    )


def consensus_enabled() -> bool:
    """When true (default), cross-check CORE identity fields across two independent
    local vision models instead of trusting whichever one answers first.

    Nothing here validated that the first model to return parseable JSON was
    RIGHT — a confident wrong read (e.g. gender or hair_color) merges straight
    into params.json and seeds LoRA training identity. Two independent models
    disagreeing is the cheapest available null-model-style check (both are
    local Ollama calls, no added $ cost); agreement isn't proof, but silent
    disagreement is proof of NO evidence, which the single-model path could
    never see."""
    return os.environ.get('ZYG_CHAR_PHOTO_CONSENSUS', '1').strip().lower() not in (
        '0',
        'false',
        'no',
        'off',
    )


CONSENSUS_N = max(2, int(os.environ.get('ZYG_CHAR_PHOTO_CONSENSUS_N', '2') or '2'))


OLLAMA_VISION_NUM_CTX = int(os.environ.get('ZYG_CHAR_PHOTO_NUM_CTX', '8192') or '8192')
OLLAMA_VISION_NUM_PREDICT = int(os.environ.get('ZYG_CHAR_PHOTO_NUM_PREDICT', '1200') or '1200')
# Unload vision models immediately after each request (Ollama default is ~5 min).
OLLAMA_KEEP_ALIVE = os.environ.get('ZYG_CHAR_PHOTO_OLLAMA_KEEP_ALIVE', '0').strip() or '0'

OLLAMA_VISION_MODELS = [
    m.strip()
    for m in os.environ.get(
        'ZYG_CHAR_PHOTO_VISION_MODELS',
        # llama3.2-vision REMOVED 2026-08-09: Llama 3.2 grants no multimodal
        # rights to EU-domiciled operators — no licence exists for this box.
        'qwen3.5:9b,moondream:latest',  # qwen2.5vl removed 2026-09-04
    ).split(',')
    if m.strip()
]

# ── Allowed enum values (must match zero_public.html) ───────────────────────────
GENDER_VALUES = ('female', 'male')
HAIR_COLOR_VALUES = (
    'blonde',
    'brown',
    'auburn',
    'red',
    'black',
    'dark brown',
    'grey',
    'white',
)
EYE_COLOR_VALUES = ('brown', 'blue', 'green', 'hazel', 'grey', 'amber')
SKIN_TONE_VALUES = ('fair', 'light', 'medium', 'olive', 'tan', 'dark', 'deep')
FACIAL_HAIR_VALUES = (
    'none',
    'stubble',
    'goatee',
    'mustache',
    'handlebar mustache',
    'short beard',
    'full beard',
    'long beard',
    'van dyke',
    'circle beard',
    'anchor beard',
    'extended goatee',
    'chinstrap',
    'mutton chops',
)
FACE_SHAPE_VALUES = ('oval', 'round', 'square', 'heart', 'long', 'diamond')
EYE_SHAPE_VALUES = (
    'almond',
    'round',
    'hooded',
    'monolid',
    'upturned',
    'downturned',
)
EYEBROW_STYLE_VALUES = (
    'natural',
    'natural arched',
    'thick',
    'sparse',
    'bold straight',
)
NOSE_SHAPE_VALUES = ('balanced', 'aquiline', 'button', 'broad', 'narrow')
LIP_SHAPE_VALUES = ('natural', 'natural full', 'full', 'thin', 'wide')
HAIR_LENGTH_VALUES = (
    'shaved',
    'short',
    'medium',
    'shoulder',
    'long',
    'waist-length',
)
HAIR_TEXTURE_VALUES = ('straight', 'wavy', 'curly', 'coily', 'kinky')
EXPRESSION_VALUES = (
    'auto',
    'happy smiling',
    'neutral confident',
    'warm welcoming',
    'stern serious',
    'playful',
    'thoughtful',
    'surprised',
)
HEIGHT_VALUES = (
    '1.10',
    '1.20',
    '1.30',
    '1.40',
    '1.45',
    '1.50',
    '1.55',
    '1.60',
    '1.65',
    '1.70',
    '1.75',
    '1.80',
    '1.85',
    '1.90',
    '1.95',
    '2.00',
    '2.05',
    '2.10',
)

HAIR_STYLE_VALUES = (
    'auto',
    'pixie cut',
    'textured pixie',
    'boy cut',
    'buzz cut',
    'shaved head',
    'long straight',
    'long wavy',
    'long curly',
    'short bob',
    'lob',
    'wavy bob',
    'curly bob',
    'high ponytail',
    'low ponytail',
    'high bun',
    'low bun',
    'braids',
    'afro',
    'crew cut',
    'fade',
    'undercut',
    'slick back',
    'messy',
    'side part',
    'man bun',
    'bald',
    'curtain bangs',
    'layered medium',
    'beach waves',
)

CORE_FIELD_KEYS = (
    'gender',
    'age',
    'hair_color',
    'eye_color',
    'skin_tone',
    'height',
    'facial_hair',
    'muscle_mass',
)
IDENTITY_FIELD_KEYS = (
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
PRESENTATION_FIELD_KEYS = (
    'default_clothing',
    'default_expression',
    'accessories',
    'posture',
)

_ALL_MERGE_KEYS = CORE_FIELD_KEYS + IDENTITY_FIELD_KEYS + PRESENTATION_FIELD_KEYS

_SYSTEM_PROMPT = (
    """You analyze portrait / character reference photos for a LoRA training pipeline.
Return ONE JSON object only — no markdown fences, no preamble.

Rules:
- Infer visible traits only; use null when uncertain or not visible.
- Map values to the allowed enums below whenever possible.
- age: integer 1-99 best estimate from face.
- muscle_mass: integer 1-100 (1=very slim, 20=average, 60=athletic, 85=muscular).
- height: meters as string snapped to nearest: """
    + ', '.join(HEIGHT_VALUES)
    + """
- gender: female|male (presentation in photo).
- hair_color: """
    + '|'.join(HAIR_COLOR_VALUES)
    + """
- eye_color: """
    + '|'.join(EYE_COLOR_VALUES)
    + """
- skin_tone: """
    + '|'.join(SKIN_TONE_VALUES)
    + """
- facial_hair: """
    + '|'.join(FACIAL_HAIR_VALUES)
    + """ (none if not visible / female)
- hair_length: """
    + '|'.join(HAIR_LENGTH_VALUES)
    + """
- hair_texture: """
    + '|'.join(HAIR_TEXTURE_VALUES)
    + """
- face_shape: """
    + '|'.join(FACE_SHAPE_VALUES)
    + """
- eye_shape: """
    + '|'.join(EYE_SHAPE_VALUES)
    + """
- eyebrow_style, nose_shape, lip_shape: use allowed enums.
- hair_style: short phrase describing visible hairstyle (e.g. "long wavy", "short bob", "crew cut").
- distinctive_marks: short phrase or "none".
- ethnic_heritage: optional short hint or empty string.
- default_clothing: visible clothing in photo (short phrase).
- default_expression: """
    + '|'.join(e for e in EXPRESSION_VALUES if e != 'auto')
    + """
- accessories: visible jewelry/glasses/hat or "none".
- posture: visible posture hint or null.
- per_image_caption: ONE rich LoRA training caption for THIS image (include trigger placeholder TRIGGER_TOKEN).
  Include gender, hair, eyes, skin, clothing, pose angle, lighting, photorealistic descriptors.
  No scenery beyond plain background if visible."""
)

_USER_PROMPT = (
    'Analyze this character reference photo. Replace TRIGGER_TOKEN in per_image_caption '
    'with the literal text TRIGGER_TOKEN (we substitute later).\n\n'
    'Return JSON:\n'
    '{\n'
    '  "gender": "...", "age": 25, "hair_color": "...", "eye_color": "...",\n'
    '  "skin_tone": "...", "height": "1.70", "facial_hair": "none", "muscle_mass": 20,\n'
    '  "hair_style": "...", "hair_length": "...", "hair_texture": "...",\n'
    '  "face_shape": "...", "eye_shape": "...", "eyebrow_style": "...",\n'
    '  "nose_shape": "...", "lip_shape": "...", "distinctive_marks": "...",\n'
    '  "ethnic_heritage": "...", "default_clothing": "...", "default_expression": "...",\n'
    '  "accessories": "...", "posture": "...",\n'
    '  "per_image_caption": "TRIGGER_TOKEN woman, blonde hair, ..."\n'
    '}'
)


def _parse_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    text = text.strip()
    m = re.search(r'\{[\s\S]*\}', text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _norm(s: Any) -> str:
    return re.sub(r'\s+', ' ', str(s or '').strip().lower())


def _pick_enum(value: Any, allowed: tuple[str, ...], default: str | None = None) -> str | None:
    if value is None:
        return default
    raw = _norm(value)
    if not raw:
        return default
    if raw in allowed:
        return raw
    for a in allowed:
        if a in raw or raw in a:
            return a
    close = get_close_matches(raw, list(allowed), n=1, cutoff=0.55)
    if close:
        return close[0]
    aliases = {
        'gray': 'grey',
        'platinum': 'white',
        'silver': 'grey',
        'brunette': 'brown',
        'dark': 'dark brown',
        'tan skin': 'tan',
        'dark skin': 'dark',
        'deep skin': 'deep',
        'woman': 'female',
        'man': 'male',
        'beard': 'full beard',
        'clean shaven': 'none',
        'no beard': 'none',
    }
    if raw in aliases and aliases[raw] in allowed:
        return aliases[raw]
    return default


def _snap_height(value: Any) -> str | None:
    if value is None:
        return None
    try:
        h = float(value)
    except (TypeError, ValueError):
        return _pick_enum(value, HEIGHT_VALUES)
    best = min(HEIGHT_VALUES, key=lambda x: abs(float(x) - h))
    return best


def _snap_muscle(value: Any) -> int | None:
    try:
        v = int(float(value))
        return max(1, min(100, v))
    except (TypeError, ValueError):
        return None


def _snap_age(value: Any) -> int | None:
    try:
        v = int(float(value))
        return max(1, min(99, v))
    except (TypeError, ValueError):
        return None


def _match_hair_style(value: Any) -> str | None:
    if not value:
        return None
    raw = _norm(value)
    if raw == 'auto':
        return 'auto'
    if raw in HAIR_STYLE_VALUES:
        return raw
    close = get_close_matches(raw, list(HAIR_STYLE_VALUES), n=1, cutoff=0.45)
    if close:
        return close[0]
    for hs in HAIR_STYLE_VALUES:
        if hs in raw or raw in hs:
            return hs
    return raw[:80] if raw else None


def normalize_analysis(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Map vision model output to pipeline-safe enums."""
    if not raw:
        return {}
    out: dict[str, Any] = {}
    out['gender'] = _pick_enum(raw.get('gender'), GENDER_VALUES)
    out['age'] = _snap_age(raw.get('age'))
    out['hair_color'] = _pick_enum(raw.get('hair_color'), HAIR_COLOR_VALUES)
    out['eye_color'] = _pick_enum(raw.get('eye_color'), EYE_COLOR_VALUES)
    out['skin_tone'] = _pick_enum(raw.get('skin_tone'), SKIN_TONE_VALUES)
    out['height'] = _snap_height(raw.get('height') or raw.get('height_m'))
    out['facial_hair'] = _pick_enum(raw.get('facial_hair'), FACIAL_HAIR_VALUES, 'none')
    out['muscle_mass'] = _snap_muscle(raw.get('muscle_mass'))
    out['hair_style'] = _match_hair_style(raw.get('hair_style'))
    out['hair_length'] = _pick_enum(raw.get('hair_length'), HAIR_LENGTH_VALUES)
    out['hair_texture'] = _pick_enum(raw.get('hair_texture'), HAIR_TEXTURE_VALUES)
    out['face_shape'] = _pick_enum(raw.get('face_shape'), FACE_SHAPE_VALUES)
    out['eye_shape'] = _pick_enum(raw.get('eye_shape'), EYE_SHAPE_VALUES)
    out['eyebrow_style'] = _pick_enum(raw.get('eyebrow_style'), EYEBROW_STYLE_VALUES)
    out['nose_shape'] = _pick_enum(raw.get('nose_shape'), NOSE_SHAPE_VALUES)
    out['lip_shape'] = _pick_enum(raw.get('lip_shape'), LIP_SHAPE_VALUES)
    out['distinctive_marks'] = (raw.get('distinctive_marks') or '').strip() or None
    if out.get('distinctive_marks') and _norm(out['distinctive_marks']) in ('none', 'n/a', 'null'):
        out['distinctive_marks'] = 'none'
    out['ethnic_heritage'] = (raw.get('ethnic_heritage') or '').strip() or None
    out['default_clothing'] = (raw.get('default_clothing') or '').strip() or None
    out['default_expression'] = _pick_enum(raw.get('default_expression'), EXPRESSION_VALUES)
    out['accessories'] = (raw.get('accessories') or '').strip() or None
    if out.get('accessories') and _norm(out['accessories']) in ('none', 'n/a'):
        out['accessories'] = 'none'
    out['posture'] = (raw.get('posture') or '').strip() or None
    cap = (raw.get('per_image_caption') or raw.get('caption') or '').strip()
    if cap:
        out['per_image_caption'] = cap
    return {k: v for k, v in out.items() if v is not None and v != ''}


def _is_auto(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        s = v.strip().lower()
        return s in ('', 'auto', 'none-selected', 'default', '(auto)')
    return False


def merge_analysis_into_params(
    params: dict[str, Any],
    analysis: dict[str, Any] | None,
    *,
    locked_fields: set[str] | None = None,
    only_auto: bool = True,
) -> dict[str, Any]:
    """Merge normalized analysis into params; respect locked / non-auto fields."""
    if not analysis:
        return params
    out = dict(params)
    locked = {(_norm(k)) for k in (locked_fields or set())}
    fields = analysis.get('fields') if isinstance(analysis.get('fields'), dict) else analysis
    normalized = normalize_analysis(fields if isinstance(fields, dict) else analysis)

    for key in _ALL_MERGE_KEYS:
        if key in locked:
            continue
        val = normalized.get(key)
        if val is None:
            continue
        if key in IDENTITY_FIELD_KEYS + PRESENTATION_FIELD_KEYS:
            if only_auto and not _is_auto(out.get(key)):
                continue
            if key in ('ethnic_heritage', 'default_clothing', 'accessories', 'posture'):
                if (out.get(key) or '').strip() and not _is_auto(out.get(key)):
                    continue
            out[key] = val
        else:
            out[key] = val
    return out


def _ollama_host() -> str:
    return os.environ.get('OLLAMA_HOST', paths.ZYG_OLLAMA_URL).rstrip('/')


def _ollama_list_loaded() -> list[str]:
    import requests

    try:
        r = requests.get(f'{_ollama_host()}/api/ps', timeout=5)
        if r.status_code != 200:
            return []
        return [str(m.get('name', '')).strip() for m in (r.json().get('models') or []) if (m.get('name') or '').strip()]
    except Exception:
        return []


def _wait_ollama_unload(model_name: str, timeout: int = 30) -> None:
    import time

    prefix = (model_name or '').split(':')[0]
    deadline = time.time() + max(1, timeout)
    while time.time() < deadline:
        names = _ollama_list_loaded()
        if not any(prefix in n for n in names):
            return
        time.sleep(1)


def evict_ollama_model(
    model_name: str,
    log_fn: Callable[[str], None] | None = None,
    wait: bool = True,
) -> None:
    """Force-unload one Ollama model from VRAM (keep_alive=0 + poll /api/ps)."""
    import requests

    log = log_fn or (lambda _m: None)
    if not model_name:
        return
    try:
        requests.post(
            f'{_ollama_host()}/api/generate',
            json={'model': model_name, 'prompt': ' ', 'stream': False, 'keep_alive': 0},
            timeout=15,
        )
        log(f'Ollama evict requested: {model_name}')
    except Exception as exc:
        log(f'Ollama evict failed ({model_name}): {exc}')
    if wait:
        _wait_ollama_unload(model_name, timeout=30)


def evict_all_ollama_models(
    log_fn: Callable[[str], None] | None = None,
    wait: bool = True,
) -> list[str]:
    """Unload every model Ollama currently holds in VRAM."""
    log = log_fn or (lambda _m: None)
    names = _ollama_list_loaded()
    for name in names:
        evict_ollama_model(name, log_fn=log, wait=wait)
    if names:
        log(f'Ollama evicted {len(names)} model(s): {", ".join(names)}')
    return names


def _image_to_b64(image_bytes: bytes) -> str:
    return base64.standard_b64encode(image_bytes).decode('ascii')


def _call_anthropic_vision(
    image_bytes: bytes,
    media_type: str,
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, Any] | None:
    log = log_fn or (lambda _m: None)
    api_key = (os.environ.get('ANTHROPIC_API_KEY') or '').strip()
    if not api_key:
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        b64 = _image_to_b64(image_bytes)
        mt = media_type if media_type.startswith('image/') else 'image/jpeg'
        resp = client.messages.create(
            model=CHAR_PHOTO_MODEL,
            max_tokens=1200,
            temperature=0.2,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'image',
                            'source': {
                                'type': 'base64',
                                'media_type': mt,
                                'data': b64,
                            },
                        },
                        {'type': 'text', 'text': _USER_PROMPT},
                    ],
                }
            ],
        )
        text = ''
        if resp.content:
            text = getattr(resp.content[0], 'text', '') or ''
        parsed = _parse_json(text)
        if parsed:
            log(f'Photo analysis: Claude OK ({CHAR_PHOTO_MODEL})')
            return parsed
    except Exception as exc:
        log(f'Photo analysis: Claude failed ({exc})')
        logger.warning('anthropic photo analysis failed: %s', exc)
    return None


def _call_ollama_vision_collect(
    image_bytes: bytes,
    max_results: int,
    log_fn: Callable[[str], None] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Query Ollama vision models in order, collecting up to `max_results` parsed
    responses from DISTINCT models (not just the first one that answers)."""
    import requests

    log = log_fn or (lambda _m: None)
    host = _ollama_host()
    b64 = _image_to_b64(image_bytes)
    prompt = _SYSTEM_PROMPT + '\n\n' + _USER_PROMPT
    used_models: list[str] = []
    results: list[tuple[str, dict[str, Any]]] = []
    try:
        for model in OLLAMA_VISION_MODELS:
            if len(results) >= max_results:
                break
            try:
                r = requests.post(
                    f'{host}/api/chat',
                    json={
                        'model': model,
                        # qwen3.x think tokens would eat num_predict; non-thinking
                        # models 500 on the key, so add it conditionally
                        **({'think': False} if model.startswith('qwen3') else {}),
                        'messages': [
                            {
                                'role': 'user',
                                'content': prompt,
                                'images': [b64],
                            }
                        ],
                        'stream': False,
                        'format': 'json',
                        'keep_alive': OLLAMA_KEEP_ALIVE,
                        'options': {
                            'num_ctx': OLLAMA_VISION_NUM_CTX,
                            'num_predict': OLLAMA_VISION_NUM_PREDICT,
                            'temperature': 0.2,
                        },
                    },
                    timeout=120,
                )
                if r.status_code != 200:
                    continue
                used_models.append(model)
                out_data = r.json()
                msg_obj = out_data.get('message', {})
                text = msg_obj.get('content', '') if isinstance(msg_obj, dict) else str(msg_obj)
                parsed = _parse_json(text)
                if parsed:
                    log(f'Photo analysis: Ollama OK ({model})')
                    results.append((model, parsed))
            except Exception as exc:
                log(f'Photo analysis: Ollama {model} failed ({exc})')
                continue
        return results
    finally:
        if str(OLLAMA_KEEP_ALIVE).strip() in ('0', '0s', '0m'):
            for m in used_models:
                evict_ollama_model(m, log_fn=log)


def _call_ollama_vision(
    image_bytes: bytes,
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, Any] | None:
    results = _call_ollama_vision_collect(image_bytes, max_results=1, log_fn=log_fn)
    return results[0][1] if results else None


def _reconcile_backends(
    results: list[tuple[str, dict[str, Any]]],
) -> tuple[dict[str, Any], list[str], str]:
    """Merge normalized analyses from independent backends.

    Any CORE_FIELD_KEYS value (identity fields that overwrite params.json
    unconditionally in merge_analysis_into_params) that two-or-more backends
    disagree on is nulled out rather than guessed — a disputed field is treated
    the same as 'not visible', not as a coin flip. Non-core fields (free-text
    style descriptions) use the first backend's read: comparing paraphrases
    like 'long wavy' vs 'wavy, long' would manufacture disagreement that isn't
    there. Returns (merged_fields, ambiguous_core_fields, confidence) where
    confidence is 'single_backend' (nothing to cross-check against),
    'agreed' (every core field either had one source or all sources matched),
    or 'disputed' (>=1 core field's backends disagreed and was nulled)."""
    if not results:
        return {}, [], 'single_backend'
    normalized = [normalize_analysis(raw) for _model, raw in results]
    merged = dict(normalized[0])
    if len(normalized) < 2:
        return merged, [], 'single_backend'
    ambiguous: list[str] = []
    for key in CORE_FIELD_KEYS:
        values = {n[key] for n in normalized if n.get(key) is not None}
        if len(values) > 1:
            merged.pop(key, None)
            ambiguous.append(key)
        elif values:
            merged[key] = next(iter(values))
    return merged, ambiguous, ('disputed' if ambiguous else 'agreed')


def analyze_image_bytes(
    image_bytes: bytes,
    media_type: str = 'image/jpeg',
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Analyze one image; returns {fields, per_image_caption, backend, ok, error,
    confidence, ambiguous_fields}.

    confidence is 'agreed' (>=2 backends cross-checked and matched on every
    CORE identity field they both answered), 'disputed' (>=2 backends
    disagreed on at least one core field — see ambiguous_fields, those keys
    are left out of `fields` rather than guessed), or 'single_backend' (only
    one vision call succeeded, so nothing could be cross-checked — treat
    with the same caution as an unmeasurable reading, not as verified)."""
    log = log_fn or (lambda _m: None)
    if not analysis_enabled():
        return {'ok': False, 'error': 'disabled', 'fields': {}}
    if not image_bytes:
        return {'ok': False, 'error': 'empty_image', 'fields': {}}

    ollama_results: list[tuple[str, dict[str, Any]]] = []
    raw = None
    backend = None
    if prefer_ollama():
        if consensus_enabled() and len(OLLAMA_VISION_MODELS) >= 2:
            ollama_results = _call_ollama_vision_collect(image_bytes, max_results=CONSENSUS_N, log_fn=log)
        else:
            single = _call_ollama_vision(image_bytes, log_fn=log)
            ollama_results = [('ollama', single)] if single else []
        if ollama_results:
            backend = '+'.join(m for m, _r in ollama_results)
    if not ollama_results:
        raw = _call_anthropic_vision(image_bytes, media_type, log_fn=log)
        backend = 'claude'
    if not raw and not ollama_results and not prefer_ollama():
        single = _call_ollama_vision(image_bytes, log_fn=log)
        if single:
            ollama_results = [('ollama', single)]
            backend = 'ollama'
    if not raw and not ollama_results:
        return {'ok': False, 'error': 'vision_unavailable', 'fields': {}, 'backend': None}

    if ollama_results:
        fields, ambiguous, confidence = _reconcile_backends(ollama_results)
        caption = (fields.pop('per_image_caption', None) or '').strip()
        if ambiguous:
            log(
                f'Photo analysis: DISPUTED core field(s) across '
                f'{len(ollama_results)} backends: {", ".join(ambiguous)} — '
                f'left unset rather than guessed'
            )
    else:
        fields = normalize_analysis(raw)
        caption = (
            raw.get('per_image_caption') or raw.get('caption') or fields.pop('per_image_caption', None) or ''
        ).strip()
        ambiguous, confidence = [], 'single_backend'
    return {
        'ok': True,
        'backend': backend,
        'fields': fields,
        'per_image_caption': caption,
        'error': None,
        'confidence': confidence,
        'ambiguous_fields': ambiguous,
    }


def analyze_photo_paths(
    paths: list[str],
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Analyze multiple photos; aggregate fields from first/best + per-path captions."""
    log = log_fn or (lambda _m: None)
    if not paths:
        return {'ok': False, 'error': 'no_paths', 'fields': {}, 'image_captions': []}

    image_captions: list[dict[str, Any]] = []
    aggregate: dict[str, Any] = {}
    backend = None
    all_ambiguous: set[str] = set()
    worst_confidence = 'agreed'  # agreed < single_backend < disputed
    _CONF_RANK = {'agreed': 0, 'single_backend': 1, 'disputed': 2}

    for idx, path in enumerate(paths):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, 'rb') as fh:
                data = fh.read()
        except OSError as exc:
            log(f'Photo analysis: cannot read {path}: {exc}')
            continue
        ext = os.path.splitext(path)[1].lower()
        mt = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.webp': 'image/webp',
        }.get(ext, 'image/jpeg')
        result = analyze_image_bytes(data, mt, log_fn=log)
        if not result.get('ok'):
            continue
        backend = result.get('backend') or backend
        if not aggregate:
            aggregate = dict(result.get('fields') or {})
        all_ambiguous.update(result.get('ambiguous_fields') or ())
        conf = result.get('confidence') or 'single_backend'
        if _CONF_RANK.get(conf, 1) > _CONF_RANK.get(worst_confidence, 0):
            worst_confidence = conf
        cap = (result.get('per_image_caption') or '').strip()
        image_captions.append(
            {
                'index': idx,
                'path': path,
                'caption': cap,
                'fields': result.get('fields') or {},
            }
        )

    if not aggregate and not image_captions:
        return {'ok': False, 'error': 'analysis_failed', 'fields': {}, 'image_captions': []}

    if backend and backend != 'claude':
        evict_all_ollama_models(log_fn=log)

    return {
        'ok': True,
        'backend': backend,
        'fields': aggregate,
        'image_captions': image_captions,
        'error': None,
        'confidence': worst_confidence,
        'ambiguous_fields': sorted(all_ambiguous),
    }


def _fallback_caption(
    trigger: str,
    params: dict[str, Any],
    pose_suffix: str,
    style_desc: str,
) -> str:
    gender = params.get('gender', 'person')
    hair = params.get('hair_color', 'brown')
    eyes = params.get('eye_color', 'brown')
    skin = params.get('skin_tone', 'medium')
    clothing = (params.get('default_clothing') or '').strip()
    expr = (params.get('default_expression') or 'neutral confident').strip()
    parts = [
        trigger,
        gender,
        f'{hair} hair',
        f'{eyes} eyes',
        f'{skin} skin tone',
        style_desc,
        expr,
    ]
    if clothing and clothing.lower() not in ('auto', 'none', ''):
        parts.append(f'wearing {clothing}')
    parts.append(pose_suffix)
    return ', '.join(p for p in parts if p)


def write_training_captions(
    image_paths: list[str],
    params: dict[str, Any],
    trigger_token: str,
    analysis: dict[str, Any] | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> int:
    """Write .txt caption beside each training image. Returns count written."""
    log = log_fn or (lambda _m: None)
    try:
        from zyg_workflows import blender_character_service as _bcs

        style_desc = _bcs.caption_style_description(params.get('style', 'photorealistic'))
    except Exception:
        style_desc = 'photorealistic, film photography, natural skin texture'

    pose_suffixes = [
        'full body, front view',
        'portrait, facing camera',
        'three-quarter angle, natural light',
        'profile view, side angle',
        'upper body, candid',
        'close-up face',
        'full body, dynamic pose',
    ]

    captions_by_index: dict[int, str] = {}
    if analysis:
        for item in analysis.get('image_captions') or []:
            if not isinstance(item, dict):
                continue
            idx = int(item.get('index', -1))
            cap = (item.get('caption') or '').strip()
            if idx >= 0 and cap:
                captions_by_index[idx] = cap.replace('TRIGGER_TOKEN', trigger_token)

    written = 0
    for idx, img_path in enumerate(image_paths):
        cap_path = os.path.splitext(img_path)[0] + '.txt'
        cap = captions_by_index.get(idx, '').strip()
        if not cap:
            cap = _fallback_caption(
                trigger_token,
                params,
                pose_suffixes[idx % len(pose_suffixes)],
                style_desc,
            )
        else:
            if trigger_token not in cap:
                cap = f'{trigger_token} {cap}'
        try:
            with open(cap_path, 'w', encoding='utf-8') as fh:
                fh.write(cap)
            written += 1
        except OSError as exc:
            log(f'Caption write failed for {img_path}: {exc}')
    log(f'Wrote {written} vision/training caption(s) for {len(image_paths)} photo(s)')
    return written
