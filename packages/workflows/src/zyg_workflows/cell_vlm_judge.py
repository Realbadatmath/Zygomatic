# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tiered VLM defect judge for contact-sheet cells (2026-07-16).

The only gate that can see translucent ghost-face remnants: ArcFace embeddings
are pose/texture-invariant by construction, face detectors do not fire on
low-alpha ghosts even at det-thresh 0.22, and Laplacian cheek variance does not
separate ghost cells from clean ones (all three measured on the Kira Dunn run).

Tier 1 — local Ollama vision model (free): catches gross defects (melted faces,
strong ghost figures). Validated 2026-07-16: flagged cells 17/23, zero false
positives on clean cells, but missed the subtle ghosts (cells 04/44).
Tier 2 — Anthropic Claude vision (cents/sheet): pairwise anchor+cell prompt,
catches the subtle ghosts tier 1 misses (validated in the 2026-07-16 audit).

Flag-only semantics (SalArt-VQA: VLMs hit ~99% defect-presence recall but only
~53% precise grounding): a flag routes the cell to the regen ladder and, if
unrepaired, to fail-closed dataset exclusion. A clean verdict never overrides
the identity/pose gates. Infrastructure errors fail OPEN per tier (logged) so a
down Ollama or missing API key degrades coverage instead of blocking the run.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
from typing import Any, Callable
import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


logger = logging.getLogger(__name__)

_OLLAMA_HOST = os.environ.get('OLLAMA_HOST', paths.ZYG_OLLAMA_URL).rstrip('/')


def enabled() -> bool:
    return os.environ.get('ZYG_CELL_VLM_JUDGE', '1').strip().lower() not in (
        '0',
        'false',
        'no',
        'off',
    )


def local_enabled() -> bool:
    return os.environ.get('ZYG_CELL_VLM_LOCAL', '1').strip().lower() not in (
        '0',
        'false',
        'no',
        'off',
    )


def cloud_enabled() -> bool:
    if os.environ.get('ZYG_CELL_VLM_CLOUD', '1').strip().lower() in ('0', 'false', 'no', 'off'):
        return False
    return bool((os.environ.get('ANTHROPIC_API_KEY') or '').strip())


LOCAL_MODEL = os.environ.get('ZYG_CELL_VLM_LOCAL_MODEL', 'qwen3.5:9b').strip()


def _ollama_vision_payload(payload: dict) -> dict:
    """qwen3.x are thinking models: without think=False their reasoning eats the
    small num_predict budgets and 'response' comes back empty. Non-thinking
    models (qwen2.5vl) 500 on the think key, so add it conditionally."""
    if payload.get('model', '').startswith('qwen3'):
        payload['think'] = False
    return payload


CLOUD_MODEL = os.environ.get('ZYG_CELL_VLM_CLOUD_MODEL', 'claude-sonnet-4-6').strip()
TIMEOUT_S = int(os.environ.get('ZYG_CELL_VLM_TIMEOUT', '300'))
# Keep the Ollama model resident across a 48-cell batch; release() unloads it.
KEEP_ALIVE = os.environ.get('ZYG_CELL_VLM_KEEP_ALIVE', '2m').strip() or '2m'
# Only medium/high-confidence detections flag — low-confidence VLM positives
# are noise (measured: clean cells return defect_found=false at low conf).
_FLAG_CONFIDENCES = ('high', 'medium')
_KNOWN_CONFIDENCES = ('high', 'medium', 'low')

# Per-run circuit breaker: after this many consecutive errors a tier is marked
# dead for the process lifetime of the batch — a wedged Ollama or rate-limited
# API account must not turn 47 fail-open calls into a multi-hour stall.
_TIER_MAX_CONSECUTIVE_ERRORS = int(os.environ.get('ZYG_CELL_VLM_MAX_ERRORS', '3'))
_tier_errors = {'local': 0, 'cloud': 0}


def _tier_dead(tier: str) -> bool:
    return _tier_errors.get(tier, 0) >= _TIER_MAX_CONSECUTIVE_ERRORS


def _tier_record(tier: str, ok: bool) -> None:
    _tier_errors[tier] = 0 if ok else _tier_errors.get(tier, 0) + 1


def reset_tier_errors() -> None:
    _tier_errors['local'] = 0
    _tier_errors['cloud'] = 0


def _norm_confidence(raw_flagged: bool, conf: str) -> str:
    """Unknown/missing confidence on a positive verdict counts as medium —
    'very high'/'certain' must not silently convert a defect into a pass."""
    conf = (conf or '').strip().lower()
    if conf in _KNOWN_CONFIDENCES:
        return conf
    return 'medium' if raw_flagged else ''


_DEFECT_CRITERIA = (
    '(1) GHOST FACE: a translucent second face or facial features (eye sockets, '
    'nose highlight, lips, eyebrows) blended into the skin, forehead, cheeks, or '
    'hair INCLUDING the back of the head, like a double exposure; '
    '(2) melted, missing, or duplicated facial features; '
    '(3) mottled, blotchy, or uneven skin discoloration: hard-edged '
    'hyperpigmentation patches, scar-like smears, streaks, or irregular '
    'darker/lighter blotches on the cheeks, forehead, chin or around the mouth '
    'that are NOT uniform freckles and NOT explained by lighting (run dc1669d1 '
    'and 0cc9541b trained tiles with smeared cheek/forehead mottling); '
    '(4) a second person or duplicated/extra body parts; '
    '(5) sideways or upside-down framing; '
    '(6) gray smudges, ghost-marks, stain-like blotches, or faded ghost text '
    'ON THE CLOTHING (run d835e071 shipped sweater tiles with smeared '
    'gray marks that trained into the dataset). '
    'Natural skin pores, freckles, film grain, stray hair strands, and normal '
    'fabric knit texture, seams or folds are NOT defects.'
)

_LOCAL_PROMPT = (
    'You are a strict photo QC inspector for AI-generated character reference '
    f'photos. Inspect this image closely for these specific defects: {_DEFECT_CRITERIA} '
    'Look carefully at cheeks, forehead, and hair including the back of the head. '
    'Answer ONLY compact JSON: '
    '{"defect_found": true/false, "defect_type": "...", "location": "...", '
    '"confidence": "high/medium/low"}'
)


def _cloud_prompt(angle: str, has_anchor: bool) -> str:
    target = f' (target camera angle: {angle})' if angle else ''
    if has_anchor:
        intro = (
            'Image 1 is the APPROVED reference photo of a character. Image 2 is an '
            f'AI-generated edit of the same character from a different camera angle{target}. '
            'Inspect IMAGE 2 ONLY for generation defects: '
        )
        expected = 'Differences in pose, framing, or camera angle versus image 1 are EXPECTED and are not defects. '
    else:
        intro = f'This is an AI-generated character reference photo{target}. Inspect it for generation defects: '
        expected = ''
    return (
        f'{intro}{_DEFECT_CRITERIA} {expected}'
        'Respond ONLY with compact JSON: '
        '{"flagged": true/false, "defect": "<short description or empty>", '
        '"confidence": "high/medium/low"}'
    )


def _encode_image(path: str, max_side: int = 1024) -> tuple[str, str] | None:
    """Downscale + JPEG-encode to keep payloads/token costs bounded."""
    try:
        from PIL import Image

        img = Image.open(path).convert('RGB')
        w, h = img.size
        scale = max_side / float(max(w, h))
        if scale < 1.0:
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=88)
        return base64.b64encode(buf.getvalue()).decode(), 'image/jpeg'
    except Exception as exc:
        logger.warning('cell_vlm_judge: could not encode %s (%s)', path, exc)
        return None


def _parse_json(text: str) -> dict | None:
    m = re.search(r'\{.*\}', text or '', re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _judge_local(cell_b64: str) -> dict[str, Any]:
    from zyg_workflows import llm_audit as _la_cv

    _resp_cv = _la_cv.ollama_post(
        f'{_OLLAMA_HOST}/api/generate',
        _ollama_vision_payload(
            {
                'model': LOCAL_MODEL,
                'prompt': _LOCAL_PROMPT,
                'images': [cell_b64],
                'stream': False,
                'keep_alive': KEEP_ALIVE,
                'options': {'num_ctx': 8192, 'num_predict': 300, 'temperature': 0.1},
            }
        ),
        timeout=TIMEOUT_S,
        stage='cell_vlm/defect',
    )
    parsed = _parse_json(_resp_cv.get('response') or '') or {}
    conf = _norm_confidence(bool(parsed.get('defect_found')), str(parsed.get('confidence') or ''))
    flagged = bool(parsed.get('defect_found')) and conf in _FLAG_CONFIDENCES
    defect = ''
    if flagged:
        defect = f'{parsed.get("defect_type") or "defect"} @ {parsed.get("location") or "?"}'
    return {'flagged': flagged, 'defect': defect, 'confidence': conf}


def _judge_cloud(cell_b64: str, mt: str, anchor: tuple[str, str] | None, angle: str) -> dict[str, Any]:
    import anthropic

    client = anthropic.Anthropic(api_key=(os.environ.get('ANTHROPIC_API_KEY') or '').strip())
    content: list[dict] = []
    if anchor:
        content.append({'type': 'image', 'source': {'type': 'base64', 'media_type': anchor[1], 'data': anchor[0]}})
    content.append({'type': 'image', 'source': {'type': 'base64', 'media_type': mt, 'data': cell_b64}})
    content.append({'type': 'text', 'text': _cloud_prompt(angle, anchor is not None)})
    # No temperature param: current-generation Anthropic models reject
    # non-default temperature (400) — the narrow JSON rubric is stable without it.
    resp = client.messages.create(
        model=CLOUD_MODEL,
        max_tokens=300,
        messages=[{'role': 'user', 'content': content}],
    )
    text = getattr(resp.content[0], 'text', '') if resp.content else ''
    parsed = _parse_json(text) or {}
    conf = _norm_confidence(bool(parsed.get('flagged')), str(parsed.get('confidence') or ''))
    flagged = bool(parsed.get('flagged')) and conf in _FLAG_CONFIDENCES
    return {
        'flagged': flagged,
        'defect': str(parsed.get('defect') or '') if flagged else '',
        'confidence': conf,
    }


def judge_cell(
    cell_path: str,
    *,
    anchor_path: str | None = None,
    angle: str = '',
    log_fn: Callable[[str], None] | None = None,
    allow_cloud: bool = True,
) -> dict[str, Any]:
    """Judge one cell. Returns {flagged, tier, defect, confidence, errors}.

    Tier 1 (local) flags short-circuit; clean tier-1 results escalate to tier 2
    (cloud) because the local model is measured-blind to subtle ghosts. Errors
    fail open per tier.

    ``allow_cloud=False`` (2026-07-18): the caller judged this tile
    low-suspicion (strong ArcFace pass) — run the local screen only and skip
    the paid cloud confirmation. See ZYG_CELL_VLM_CLOUD_MODE in the caller.
    """
    out: dict[str, Any] = {'flagged': False, 'tier': '', 'defect': '', 'confidence': '', 'errors': []}
    if not enabled() or not os.path.isfile(cell_path):
        return out
    enc = _encode_image(cell_path)
    if not enc:
        out['errors'].append('encode_failed')
        return out
    cell_b64, mt = enc

    if local_enabled() and not _tier_dead('local'):
        try:
            r = _judge_local(cell_b64)
            _tier_record('local', True)
            if r['flagged']:
                r['tier'] = 'local'
                out.update(r)
                return out
        except Exception as exc:
            _tier_record('local', False)
            out['errors'].append(f'local:{exc}')
            if log_fn:
                dead = ' — tier disabled for this run' if _tier_dead('local') else ''
                log_fn(f'VLM judge: local tier error ({str(exc)[:80]}){dead}')

    if not allow_cloud:
        out['tier'] = 'local_only'
        return out

    if cloud_enabled() and not _tier_dead('cloud'):
        try:
            anchor_enc = _encode_image(anchor_path) if anchor_path else None
            r = _judge_cloud(cell_b64, mt, anchor_enc, angle)
            _tier_record('cloud', True)
            if r['flagged']:
                r['tier'] = 'cloud'
            out.update(r)
            return out
        except Exception as exc:
            _tier_record('cloud', False)
            out['errors'].append(f'cloud:{exc}')
            if log_fn:
                dead = ' — tier disabled for this run' if _tier_dead('cloud') else ''
                log_fn(f'VLM judge: cloud tier error ({str(exc)[:80]}){dead}')
    return out


_IDMATCH_PROMPT = (
    'Image 1 is the APPROVED reference photo of a character. Image 2 is another '
    'photo that is supposed to be the SAME person from a possibly different '
    'camera angle. Judge ONLY whether image 2 depicts the same individual — '
    'compare the immutable bone structure and features: face shape and jawline, '
    'eye shape and spacing, nose bridge and tip, lip shape and fullness, brow '
    'shape, chin, apparent age. IGNORE differences in pose, camera angle, '
    'framing, expression, lighting, hair styling, and makeup — those are not '
    'identity. ArcFace already accepted this pair, so only report a mismatch you '
    'are confident a casting director would call a different person or a clearly '
    'wrong face. Respond ONLY with compact JSON: '
    '{"same_person": true/false, "confidence": "high/medium/low", '
    '"drifted_features": "<short list of the features that differ, or empty>"}'
)


def judge_identity_match(
    cell_path: str,
    anchor_path: str,
    *,
    angle: str = '',
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Cloud VLM same-person check for ArcFace-passing tiles (2026-07-20).

    ArcFace is nearly blind to brow shape, lip fullness, hair length and fine
    face-shape drift, so a tile can pass the embedding gate yet read as a
    different (or subtly wrong) person — the Ivy Rossi audit's tile 16. This
    compares immutable structure against the anchor and returns a mismatch only
    on a confident different-person verdict. Cloud-only (needs the two-image
    comparison); returns {'checked', 'same_person', 'confidence',
    'drifted_features'}. Fails OPEN (same_person True) on any error so it can
    only ever remove a tile on a positive, confident signal.
    """
    out: dict[str, Any] = {
        'checked': False,
        'same_person': True,
        'confidence': '',
        'drifted_features': '',
    }
    if not enabled() or not cloud_enabled() or _tier_dead('cloud'):
        return out
    if not (cell_path and anchor_path and os.path.isfile(cell_path) and os.path.isfile(anchor_path)):
        return out
    enc_c = _encode_image(cell_path)
    enc_a = _encode_image(anchor_path)
    if not enc_c or not enc_a:
        return out
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=(os.environ.get('ANTHROPIC_API_KEY') or '').strip())
        content = [
            {'type': 'image', 'source': {'type': 'base64', 'media_type': enc_a[1], 'data': enc_a[0]}},
            {'type': 'image', 'source': {'type': 'base64', 'media_type': enc_c[1], 'data': enc_c[0]}},
            {'type': 'text', 'text': _IDMATCH_PROMPT},
        ]
        resp = client.messages.create(
            model=CLOUD_MODEL,
            max_tokens=200,
            messages=[{'role': 'user', 'content': content}],
        )
        _tier_record('cloud', True)
        text = getattr(resp.content[0], 'text', '') if resp.content else ''
        parsed = _parse_json(text) or {}
        out['checked'] = True
        # Default missing/garbled 'same_person' to True (fail-open).
        out['same_person'] = parsed.get('same_person', True) is not False
        out['confidence'] = _norm_confidence(True, str(parsed.get('confidence') or ''))
        out['drifted_features'] = str(parsed.get('drifted_features') or '')
    except Exception as exc:
        _tier_record('cloud', False)
        if log_fn:
            log_fn(f'Identity-match judge: cloud error ({str(exc)[:80]})')
    return out


_SKIN_SCALE = ('fair', 'light', 'medium-light', 'medium', 'olive', 'tan', 'dark', 'deep')
EYE_VOCAB = ('brown', 'green', 'blue', 'hazel', 'gray', 'amber', 'black')
HAIR_VOCAB = ('black', 'brown', 'blonde', 'red', 'auburn', 'gray', 'white')
# Spelling/synonym normalization applied to BOTH spec and observation — 'grey'
# vs 'gray' failed both substring tests and even poisoned the negative builder
# (the spec's own colour got negated).
_COLOR_SYNONYMS = {'grey': 'gray', 'blond': 'blonde', 'ginger': 'red'}

_ATTR_PROMPT = (
    'Look at this AI-generated character reference photo and report the visible '
    'physical attributes. Be literal about what the pixels show — do not infer '
    'from context. Respond ONLY with compact JSON: '
    '{"eye_color": "<brown|green|blue|hazel|gray|amber|black|unclear>", '
    '"hair_color": "<black|brown|blonde|red|auburn|gray|white|other|unclear>", '
    '"skin_tone": "<fair|light|medium-light|medium|olive|tan|dark|deep|unclear>"}'
)


def normalize_color(value: str) -> str:
    words = (value or '').strip().lower().split()
    return ' '.join(_COLOR_SYNONYMS.get(w, w) for w in words)


def spec_verifiable(attr: str, value: str) -> bool:
    """Can the judge's fixed answer vocabulary ever confirm this spec value?
    Unverifiable specs (hair 'violet', eyes 'heterochromia') must be SKIPPED,
    not retried to exhaustion — the VLM can only ever answer 'other'."""
    v = normalize_color(value)
    if not v:
        return False
    if attr == 'skin_tone':
        return v in _SKIN_SCALE
    vocab = EYE_VOCAB if attr == 'eye_color' else HAIR_VOCAB
    return any(w in v or v in w for w in vocab)


def _attr_matches(attr: str, spec: str, observed: str) -> bool:
    """Tolerant compare: substring match for colors, ±1 step on the skin scale.
    'unclear'/'other' observations never count as a mismatch (fail-open)."""
    spec = normalize_color(spec)
    observed = normalize_color(observed)
    if not spec or not observed or observed in ('unclear', 'other'):
        return True
    if attr == 'skin_tone':
        # light↔medium stays acceptable even though medium-light now sits
        # between them (pre-existing tolerance boundary, kept on purpose).
        if {spec, observed} == {'light', 'medium'}:
            return True
        try:
            si = _SKIN_SCALE.index(spec)
            oi = _SKIN_SCALE.index(observed)
        except ValueError:
            return spec in observed or observed in spec
        return abs(si - oi) <= 1
    if attr == 'hair_color':
        # Dark-brown vs black is a call the VLM cannot make reliably — a
        # dark-brown-with-highlights render was over-called 'black' and synced
        # the bible away from the selected 'brown' (Maren, 2026-07-22). Treat
        # adjacent hair colours as a match so an ambiguous dark call neither
        # regens forever nor clobbers the selection; the symmetric hair negative
        # already biases the render toward the requested colour.
        if {spec, observed} in _HAIR_ADJACENT:
            return True
    return spec in observed or observed in spec


# Hair colours close enough that the VLM cannot separate them (2026-07-22).
_HAIR_ADJACENT = [
    {'brown', 'black'},
    {'brown', 'auburn'},
    {'brown', 'dark brown'},
    {'auburn', 'red'},
    {'auburn', 'black'},
    {'blonde', 'light brown'},
    {'gray', 'white'},
    {'gray', 'silver'},
    {'white', 'silver'},
]


def judge_attributes(
    image_path: str,
    spec: dict,
    *,
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Compare the delivered image's attributes against the character spec.

    2026-07-16: FLUX ignored 'green eyes' on two consecutive runs and the
    error cloned into every edit cell and the LoRA — no gate ever compared
    delivered attributes to requested ones. Returns
    {'checked': bool, 'observed': {...}, 'mismatches': {attr: observed}}.
    Fail-open: checked=False (and no mismatches) when no tier answers.
    Prefers the cloud tier — small local VLMs are unreliable on iris color.
    """
    out: dict[str, Any] = {'checked': False, 'observed': {}, 'mismatches': {}, 'unverifiable': []}
    spec = {k: normalize_color(v) for k, v in (spec or {}).items() if (v or '').strip()}
    for k in list(spec):
        if not spec_verifiable(k, spec[k]):
            out['unverifiable'].append(k)
            del spec[k]
    if not enabled() or not spec or not os.path.isfile(image_path):
        return out
    enc = _encode_image(image_path)
    if not enc:
        return out
    b64, mt = enc
    parsed: dict | None = None
    if cloud_enabled() and not _tier_dead('cloud'):
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=(os.environ.get('ANTHROPIC_API_KEY') or '').strip())
            resp = client.messages.create(
                model=CLOUD_MODEL,
                max_tokens=200,
                messages=[
                    {
                        'role': 'user',
                        'content': [
                            {'type': 'image', 'source': {'type': 'base64', 'media_type': mt, 'data': b64}},
                            {'type': 'text', 'text': _ATTR_PROMPT},
                        ],
                    }
                ],
            )
            text = getattr(resp.content[0], 'text', '') if resp.content else ''
            parsed = _parse_json(text)
            _tier_record('cloud', True)
        except Exception as exc:
            _tier_record('cloud', False)
            if log_fn:
                log_fn(f'Attribute judge: cloud tier error ({str(exc)[:80]})')
    if parsed is None and local_enabled() and not _tier_dead('local'):
        try:
            from zyg_workflows import llm_audit as _la_cv2

            _resp_cv2 = _la_cv2.ollama_post(
                f'{_OLLAMA_HOST}/api/generate',
                _ollama_vision_payload(
                    {
                        'model': LOCAL_MODEL,
                        'prompt': _ATTR_PROMPT,
                        'images': [b64],
                        'stream': False,
                        'keep_alive': KEEP_ALIVE,
                        'options': {'num_ctx': 8192, 'num_predict': 200, 'temperature': 0.1},
                    }
                ),
                timeout=TIMEOUT_S,
                stage='cell_vlm/attribute',
            )
            parsed = _parse_json(_resp_cv2.get('response') or '')
            _tier_record('local', True)
        except Exception as exc:
            _tier_record('local', False)
            if log_fn:
                log_fn(f'Attribute judge: local tier error ({str(exc)[:80]})')
    if not parsed:
        return out
    out['checked'] = True
    out['observed'] = {k: str(parsed.get(k) or '').strip().lower() for k in ('eye_color', 'hair_color', 'skin_tone')}
    for attr, want in spec.items():
        got = out['observed'].get(attr, '')
        if not _attr_matches(attr, want, got):
            out['mismatches'][attr] = got
    return out


_STRUCT_PROMPT = (
    'Look at this AI-generated character reference photo and report the visible '
    'facial structure. Be literal about what the pixels show. Respond ONLY with '
    'compact JSON: '
    '{"face_shape": "<oval|round|square|heart|long|diamond|unclear>", '
    '"eye_shape": "<almond|round|hooded|monolid|upturned|downturned|unclear>", '
    '"age_band": "<young_adult|adult|mature|elder|unclear>", '
    '"freckle_density": "<none|light|heavy|unclear>"} '
    'where young_adult is roughly 18-32, adult 33-50, mature 51-64, elder 65+; '
    'freckle_density: none = clear skin, light = a few scattered freckles, '
    'heavy = a dense freckle/spot field across cheeks, nose or forehead.'
)

# Adjacent shapes a VLM routinely confuses — do not report these as mismatches.
_FACE_SHAPE_CLOSE = {
    'oval': ('round', 'heart', 'long'),
    'round': ('oval', 'heart'),
    'square': ('round', 'diamond'),
    'heart': ('oval', 'round', 'diamond'),
    'long': ('oval', 'diamond'),
    'diamond': ('heart', 'long', 'square'),
}
_EYE_SHAPE_CLOSE = {
    'almond': ('upturned', 'downturned', 'round'),
    'round': ('almond',),
    'hooded': ('monolid', 'downturned'),
    'monolid': ('hooded',),
    'upturned': ('almond',),
    'downturned': ('almond', 'hooded'),
}


def _age_band(age) -> str:
    try:
        a = int(age)
    except (TypeError, ValueError):
        return ''
    if a < 33:
        return 'young_adult'
    if a < 51:
        return 'adult'
    if a < 65:
        return 'mature'
    return 'elder'


def judge_structure(
    image_path: str,
    spec: dict,
    *,
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Compare delivered face STRUCTURE against the character spec (2026-07-18).

    The attribute judge above covers colours only; FLUX silently ignored
    'monolid'/'long face' on run 59f1f012 and nothing recorded it. Log-only
    caller contract — structure tokens are weak FLUX levers, so mismatches
    inform the operator and the quality metrics rather than triggering regens.
    Returns {'checked': bool, 'observed': {...}, 'mismatches': {attr: observed}}.
    """
    out: dict[str, Any] = {'checked': False, 'observed': {}, 'mismatches': {}}
    spec = dict(spec or {})
    want_face = (spec.get('face_shape') or '').strip().lower()
    want_eye = (spec.get('eye_shape') or '').strip().lower()
    want_band = _age_band(spec.get('age'))
    # Freckle governance: checked whenever the caller supplies the marks field
    # (even as 'none' — that IS the spec being enforced).
    marks_txt = str(spec.get('distinctive_marks') or '').strip().lower()
    check_freckles = 'distinctive_marks' in spec
    if not enabled() or not os.path.isfile(image_path) or not (want_face or want_eye or want_band or check_freckles):
        return out
    enc = _encode_image(image_path)
    if not enc:
        return out
    b64, mt = enc
    parsed: dict | None = None
    if cloud_enabled() and not _tier_dead('cloud'):
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=(os.environ.get('ANTHROPIC_API_KEY') or '').strip())
            resp = client.messages.create(
                model=CLOUD_MODEL,
                max_tokens=200,
                messages=[
                    {
                        'role': 'user',
                        'content': [
                            {'type': 'image', 'source': {'type': 'base64', 'media_type': mt, 'data': b64}},
                            {'type': 'text', 'text': _STRUCT_PROMPT},
                        ],
                    }
                ],
            )
            text = getattr(resp.content[0], 'text', '') if resp.content else ''
            parsed = _parse_json(text)
            _tier_record('cloud', True)
        except Exception as exc:
            _tier_record('cloud', False)
            if log_fn:
                log_fn(f'Structure judge: cloud tier error ({str(exc)[:80]})')
    if parsed is None and local_enabled() and not _tier_dead('local'):
        try:
            from zyg_workflows import llm_audit as _la_cv2

            _resp_cv2 = _la_cv2.ollama_post(
                f'{_OLLAMA_HOST}/api/generate',
                _ollama_vision_payload(
                    {
                        'model': LOCAL_MODEL,
                        'prompt': _STRUCT_PROMPT,
                        'images': [b64],
                        'stream': False,
                        'keep_alive': KEEP_ALIVE,
                        'options': {'num_ctx': 8192, 'num_predict': 200, 'temperature': 0.1},
                    }
                ),
                timeout=TIMEOUT_S,
                stage='cell_vlm/structure',
            )
            parsed = _parse_json(_resp_cv2.get('response') or '')
            _tier_record('local', True)
        except Exception as exc:
            _tier_record('local', False)
            if log_fn:
                log_fn(f'Structure judge: local tier error ({str(exc)[:80]})')
    if not parsed:
        return out
    out['checked'] = True
    got_face = str(parsed.get('face_shape') or '').strip().lower()
    got_eye = str(parsed.get('eye_shape') or '').strip().lower()
    got_band = str(parsed.get('age_band') or '').strip().lower()
    out['observed'] = {'face_shape': got_face, 'eye_shape': got_eye, 'age_band': got_band}
    if (
        want_face
        and got_face not in ('', 'unclear')
        and got_face != want_face
        and got_face not in _FACE_SHAPE_CLOSE.get(want_face, ())
    ):
        out['mismatches']['face_shape'] = got_face
    if (
        want_eye
        and got_eye not in ('', 'unclear')
        and got_eye != want_eye
        and got_eye not in _EYE_SHAPE_CLOSE.get(want_eye, ())
    ):
        out['mismatches']['eye_shape'] = got_eye
    if want_band and got_band not in ('', 'unclear') and got_band != want_band:
        out['mismatches']['age_band'] = got_band
    got_density = str(parsed.get('freckle_density') or '').strip().lower()
    out['observed']['freckle_density'] = got_density
    if check_freckles:
        if 'freckle' not in marks_txt and got_density == 'heavy':
            # Unrequested dense field (Iris Weber failure mode) — the one
            # structure mismatch the pipeline acts on, since the freckle
            # negative gives it a real lever ('light' is tolerated).
            out['mismatches']['freckle_density'] = got_density
        elif 'freckle' in marks_txt and got_density == 'none':
            out['mismatches']['freckle_density'] = got_density
    return out


def release() -> None:
    """Unload the local vision model so it never competes with ComfyUI VRAM."""
    try:
        import requests

        requests.post(
            f'{_OLLAMA_HOST}/api/generate',
            json=_ollama_vision_payload(
                {
                    'model': LOCAL_MODEL,
                    'prompt': '',
                    'keep_alive': 0,
                    'stream': False,
                }
            ),
            timeout=20,
        )
    except Exception as _exc:
        _zyg_log.debug('ollama model unload request failed: %s', _exc)
