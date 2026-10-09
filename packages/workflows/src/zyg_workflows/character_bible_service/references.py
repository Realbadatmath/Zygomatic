# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Timestamps, reference-image picking, LoRA lookup and the empty package."""

from __future__ import annotations

import json
import os
import re  # noqa: F401
from datetime import datetime, timezone
from typing import Any, Optional
import logging as _zyg_logging


from .smile import (
    _OUTPUT_ROOT,
    _SCHEMA_VERSION,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.character_bible_service')


try:
    from zoneinfo import ZoneInfo

    _AMS_TZ = ZoneInfo('Europe/Amsterdam')
except Exception:
    _AMS_TZ = None


def _utc_now() -> str:
    """ISO timestamp in Europe/Amsterdam (function name is historical).

    The function name was kept for backwards compatibility but the value
    returned is now Amsterdam local time with offset (e.g. ``+02:00`` in
    summer, ``+01:00`` in winter) so the whole server speaks one timezone.
    """
    if _AMS_TZ is not None:
        try:
            return datetime.now(_AMS_TZ).isoformat(timespec='milliseconds')
        except Exception as _exc:
            _zyg_log.debug('Amsterdam timezone unavailable, using UTC: %s', _exc)
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


# 2026-07-31: env-flag helper — behaviour switches in this module default ON
# (new behaviour) and are turned off with 0/false/no for a one-env rollback.
def _env_on(name: str, default: str = '1') -> bool:
    try:
        return os.environ.get(name, default).strip().lower() not in ('0', 'false', 'no', 'off')
    except Exception:
        return default not in ('0', 'false', 'no', 'off')


# ── Identity reference candidates ────────────────────────────────────────────
# Previews are RENDERS, not dataset truth: they are only as trustworthy as the
# job that wrote them. Contact-sheet anchors and curated training tiles are the
# QC'd face of record and outrank them (2026-07-31).
_PREVIEW_REF_NAMES = (
    'preview_sdxl_front.png',
    'preview_sdxl_face.png',
    'preview_flux_front.png',
    'preview_flux_face.png',
)
_CONTACT_SHEET_REF_NAMES = (
    'contact_sheet_anchor_face.png',
    'contact_sheet_profile_anchor_face.png',
)
_ROOT_REF_NAMES = (
    'portrait_00_000deg.png',
    'full_warm_000deg.png',
    'full_neutral_000deg.png',
    'full_00_000deg.png',
)


def _preview_provenance_ok(png_path: str) -> bool:
    """True only when a preview PNG carries provenance proving it was rendered
    with THIS character's LoRA (shared contract D, 2026-07-31).

    ``char_state_service`` writes a sibling ``<slot>.meta.json`` next to every
    preview it renders (``slot``/``model_family``/``lora_used``/``lora_path``/
    ``trigger_token``/``restyle``/``backend``/``rendered_at``). A preview with
    no sidecar has UNVERIFIED provenance — exactly the hole a broken sweep
    endpoint used to drop a generic cel-shaded adult woman into a 12-year-old
    boy's dataset root as ``preview_flux_front.png``.

    Never raises: a missing / unreadable / malformed sidecar simply means the
    preview is not eligible as an identity reference.
    """
    try:
        meta_path = os.path.splitext(png_path)[0] + '.meta.json'
        if not os.path.isfile(meta_path):
            return False
        with open(meta_path, encoding='utf-8') as f:
            meta = json.load(f)
        if not isinstance(meta, dict):
            return False
        used = meta.get('lora_used')
        if isinstance(used, str):
            return used.strip().lower() in ('1', 'true', 'yes', 'on')
        return bool(used)
    except Exception:
        return False


def _pick_reference_images_legacy(dataset_dir: str, limit: int = 6) -> list[str]:
    """Pre-2026-07-31 ordering (previews first). Kept for ZYG_BIBLE_REF_VERIFIED=0."""
    priority = _PREVIEW_REF_NAMES + _ROOT_REF_NAMES
    found: list[str] = []
    for name in priority:
        p = os.path.join(dataset_dir, name)
        if os.path.isfile(p) and os.path.getsize(p) > 10_000:
            found.append(p)
    if len(found) >= limit:
        return found[:limit]
    extras = sorted(
        os.path.join(dataset_dir, f)
        for f in os.listdir(dataset_dir)
        if f.lower().endswith(('.png', '.jpg', '.jpeg')) and not f.startswith('preview_')
    )
    for p in extras:
        if p not in found and os.path.getsize(p) > 10_000:
            found.append(p)
        if len(found) >= limit:
            break
    return found[:limit]


def _pick_reference_images(dataset_dir: str, limit: int = 6) -> list[str]:
    """Prefer VERIFIED portrait / front references for identity conditioning.

    2026-07-31: the old ranking put the four ``preview_*.png`` slots ABOVE every
    real dataset image, and ``build_from_character_generate`` writes the winner
    into ``conditioning.ipadapter_reference_images`` with ``refs[0]`` becoming
    ``master_reference_image`` — so anything that lands in the dataset root
    under a preview name silently becomes the character's face for every future
    IPAdapter / InstantID render. Order is now:

      1. contact-sheet anchor faces  (QC-verified, the face the LoRA was built
         from — the only images the identity QC pass actually scores)
      2. curated ``training/*.png`` tiles (what the LoRA was trained on)
      3. legacy dataset-root portrait / full renders
      4. remaining dataset-root images
      5. ``preview_*`` renders — ONLY with a contract-D sidecar proving
         ``lora_used``; unverified previews are never promoted.

    ``ZYG_BIBLE_REF_VERIFIED=0`` restores the old preview-first ordering.
    """
    if not dataset_dir or not os.path.isdir(dataset_dir):
        return []
    if not _env_on('ZYG_BIBLE_REF_VERIFIED'):
        return _pick_reference_images_legacy(dataset_dir, limit)

    found: list[str] = []

    def _add(path: str) -> bool:
        """Append when it is a real image ≥10 KB. Returns True when full."""
        try:
            if path and path not in found and os.path.isfile(path) and os.path.getsize(path) > 10_000:
                found.append(path)
        except OSError as _exc:
            _zyg_log.debug('reference candidate skipped, stat failed: %s', _exc)
        return len(found) >= limit

    # 1. Contact-sheet anchors — the verified face of record.
    _cs_dir = os.path.join(dataset_dir, 'contact_sheet')
    for _name in _CONTACT_SHEET_REF_NAMES:
        if _add(os.path.join(_cs_dir, _name)):
            return found[:limit]

    # 2. Curated training tiles (identity-locked, human/QC curated).
    _train_dir = os.path.join(dataset_dir, 'training')
    try:
        for _fn in sorted(os.listdir(_train_dir)):
            if not _fn.lower().endswith(('.png', '.jpg', '.jpeg')):
                continue
            if _fn.startswith('preview_'):
                continue
            if _add(os.path.join(_train_dir, _fn)):
                return found[:limit]
    except OSError as _exc:
        _zyg_log.debug('training-image scan stopped, directory unreadable: %s', _exc)

    # 3. Legacy dataset-root portrait / full renders (Blender + FLUX datasets).
    for _name in _ROOT_REF_NAMES:
        if _add(os.path.join(dataset_dir, _name)):
            return found[:limit]

    # 4. Anything else in the dataset root that is not a preview.
    try:
        _extras = sorted(
            os.path.join(dataset_dir, f)
            for f in os.listdir(dataset_dir)
            if f.lower().endswith(('.png', '.jpg', '.jpeg')) and not f.startswith('preview_')
        )
    except OSError:
        _extras = []
    for _p in _extras:
        if _add(_p):
            return found[:limit]

    # 5. Previews LAST, and only with proven LoRA-locked provenance.
    for _name in _PREVIEW_REF_NAMES:
        _p = os.path.join(dataset_dir, _name)
        if not _preview_provenance_ok(_p):
            continue
        if _add(_p):
            return found[:limit]
    return found[:limit]


def _find_lora_path(char_id: str, model_family: str | None = None) -> Optional[str]:
    mf = (model_family or '').strip().lower() or None
    try:
        import importlib.util as _ilu

        spec = _ilu.find_spec('lora_trainer_service')
        if spec:
            from zyg_workflows import lora_trainer_service as _lts

            return _lts.get_trainer().get_lora_path(char_id, model_family=mf)
    except Exception as _exc:
        _zyg_log.debug('trainer lora lookup unavailable, trying the checkpoint scan: %s', _exc)
    try:
        from zyg_workflows import lora_trainer_service as _lts_fb

        return _lts_fb._find_latest_checkpoint(
            os.path.join(_OUTPUT_ROOT, char_id),
            model_family=mf,
        )
    except Exception as _exc:
        _zyg_log.debug('checkpoint scan unavailable, trying the directory roots: %s', _exc)
    roots = []
    if mf:
        roots.append(os.path.join(_OUTPUT_ROOT, char_id, f'lora-weights-{mf}'))
    roots.append(os.path.join(_OUTPUT_ROOT, char_id, 'lora-weights'))
    best: Optional[str] = None
    best_step = -1
    for out in roots:
        if not os.path.isdir(out):
            continue
        for root, _, files in os.walk(out):
            for fn in files:
                if fn.endswith('.safetensors'):
                    full = os.path.join(root, fn)
                    import re

                    m = re.search(r'checkpoint-(\d+)', full)
                    step = int(m.group(1)) if m else 0
                    if step >= best_step:
                        best_step = step
                        best = full
    return best


def default_package(char_id: str, trigger_token: str = '') -> dict[str, Any]:
    tok = trigger_token or f'ZYG_CHAR_{char_id[:6].upper()}'
    return {
        'schema_version': _SCHEMA_VERSION,
        'character_id': char_id,
        'trigger_token': tok,
        'display_name': '',
        'created_at': _utc_now(),
        'updated_at': _utc_now(),
        # ── Identity ─────────────────────────────────────────────────────────
        # All values may be set to '' / 'auto' / None to defer to
        # apply_auto_defaults().  After auto-fill every key has a concrete value.
        'identity': {
            'gender': '',  # required from user
            'age': None,  # int 1–99
            'age_range': '',  # 'child' | 'young' | 'adult' | 'mature' | 'elder'
            'height_m': None,  # float meters
            'skin_tone': '',  # 'fair' | 'light' | 'medium' | 'olive' | 'tan' | 'dark' | 'deep'
            'hair_color': '',
            'hair_style': '',  # e.g. 'long wavy', 'undercut', 'braided'
            'hair_length': '',  # 'shaved' | 'short' | 'medium' | 'shoulder' | 'long' | 'waist-length'
            'hair_texture': '',  # 'straight' | 'wavy' | 'curly' | 'coily' | 'kinky'
            'eye_color': '',
            'eye_shape': '',  # 'almond' | 'round' | 'hooded' | 'monolid' | 'upturned' | 'downturned'
            'eyebrow_style': '',  # 'natural' | 'arched' | 'thick' | 'sparse'
            'face_shape': '',  # 'oval' | 'round' | 'square' | 'heart' | 'long' | 'diamond'
            'nose_shape': '',  # 'balanced' | 'aquiline' | 'button' | 'broad' | 'narrow'
            'lip_shape': '',  # 'natural' | 'full' | 'thin' | 'wide'
            'body_build': '',  # raw 1–100 OR descriptor; auto-mapped to text
            'facial_hair': 'none',  # 'none' | descriptor
            'distinctive_marks': '',  # freckles / scars / dimples / tattoos — free text, 'none' OK
            'ethnic_heritage': '',  # optional cultural hint
        },
        # ── Default presentation (swappable per scene; not permanent identity) ─
        'default_presentation': {
            'default_clothing': '',
            'default_expression': '',
            'accessories': '',
            'posture': '',
        },
        'accessory_decisions': {},
        # ── Style / render profile (genre, lighting, palette — staging metadata) ─
        'style_profile': {
            'render_style': '',  # 'photorealistic' | 'animated' | 'cinematic illustration'
            'genre': '',  # 'general' | 'action' | 'romance' | …
            'indoor_stage': True,
            'lighting_profile': '',
            'color_palette': '',
            'camera_language': '',
            # Legacy flat keys — kept in sync with default_presentation for older callers.
            'default_clothing': '',
            'accessories': '',
            'default_expression': '',
            'posture': '',
        },
        # ── ComfyUI / FLUX conditioning ──────────────────────────────────────
        'conditioning': {
            'lora_path': None,
            'lora_scale': 0.85,
            'ipadapter_reference_images': [],
            'ipadapter_scale': 0.65,
            'master_reference_image': None,
            'controlnet_pose_reference': None,
            'face_detail_pass': True,  # run FaceDetailer second pass if workflow supports it
            # 0.30 max — at 0.45 the detailer re-synthesized ~half the face with
            # FLUX's smooth-skin prior and erased base-pass texture (2026-07-09).
            'face_detail_strength': 0.30,
            # instantid_enabled defaults to True now that the custom nodes are
            # installed; the runtime ``_pick_workflow`` guard still ensures the
            # InstantID workflow is only selected when (a) a reference image
            # exists and (b) ComfyUI actually reports the ApplyInstantID node.
            'instantid_enabled': True,
            'instantid_weight': 0.85,  # ApplyInstantID strength (0..1)
            'quality_suffix': '',  # photographic quality booster (auto-filled)
            'negative_prompt': '',  # always sent to node 21 (auto-filled)
        },
        'voice_profile': {'narrator_hint': '', 'character_voice': ''},
        'motion_profile': {'default_emotion': 'neutral', 'pacing': 'measured'},
        'scene_history': [],
        'generation_stats': {'total_stills': 0, 'drift_retries': 0},
    }
