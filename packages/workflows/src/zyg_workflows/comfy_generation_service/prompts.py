# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Locked positive and negative prompt composition (original lines 1198-1394)."""

from __future__ import annotations

import os
from typing import Any
from zyg_workflows.comfy_generation_service.constants import _bible
from zyg_workflows.comfy_generation_service.flux_graph import _trim_prompt_at_clause
from zyg_workflows.comfy_generation_service.style import _NONHUMAN_NEG_STRIP, _strip_clause_tokens


def build_locked_prompt(
    scene_prompt: str,
    character_package: dict[str, Any] | None,
    extra_suffix: str = '',
    *,
    studio_preview: bool = False,
) -> str:
    """Identity prefix + scene + environment + quality booster + extra."""
    ident = _bible.identity_prompt_prefix(character_package) if _bible else ''
    pres = ''
    if _bible and studio_preview:
        pres = _bible.presentation_prompt_fragment(
            character_package,
            include_lighting=True,
        )
    if _bible and studio_preview:
        suffix = _bible.preview_studio_suffix(character_package)
    elif _bible:
        suffix = _bible.indoor_style_suffix(character_package)
    else:
        suffix = ''
    quality = _bible.quality_suffix_for_package(character_package) if _bible else ''
    parts = [p for p in (ident, pres, scene_prompt.strip(), suffix, quality, extra_suffix.strip()) if p]
    return _trim_prompt_at_clause(
        ', '.join(parts),
        int(os.environ.get('ZYG_FLUX_PROMPT_MAX_CHARS', '2000')),
    )


def _resize_init_for_latent(ref_path: str, width: int, height: int) -> str:
    """Cover-crop-resize an init image to the requested render size.

    Returns a cached temp copy at exactly width×height (center crop, no
    distortion), or the original path when it already matches or on any
    failure. Needed by graphs whose latent comes from VAEEncode(LoadImage)
    and which therefore have no size node to patch (flux_img2img).
    """
    try:
        from PIL import Image as _PILrz
        import hashlib as _hl_rz
        import tempfile as _tf_rz

        with _PILrz.open(ref_path) as _im:
            if _im.size == (width, height):
                return ref_path
            _im = _im.convert('RGB')
            _sw, _sh = _im.size
            _scale = max(width / _sw, height / _sh)
            _rw = max(width, int(round(_sw * _scale)))
            _rh = max(height, int(round(_sh * _scale)))
            _im = _im.resize((_rw, _rh), _PILrz.LANCZOS)
            _left = max(0, (_rw - width) // 2)
            _top = max(0, (_rh - height) // 2)
            _im = _im.crop((_left, _top, _left + width, _top + height))
            _key = _hl_rz.md5(
                f'{os.path.abspath(ref_path)}|{os.path.getmtime(ref_path)}|{width}x{height}'.encode(),
                usedforsecurity=False,
            ).hexdigest()[:12]
            _out = os.path.join(_tf_rz.gettempdir(), f'zyg_i2i_init_{_key}_{width}x{height}.png')
            if not os.path.isfile(_out):
                # atomic: a crash mid-save must not poison the mtime-keyed cache
                _im.save(_out + '.tmp', format='PNG')
                os.replace(_out + '.tmp', _out)
            return _out
    except Exception:
        return ref_path


def _dedupe_negative_clauses(negative: str) -> str:
    """Split a negative on ', ', strip each clause, keep the FIRST occurrence
    of every clause (case-insensitive), rejoin with ', '.

    P-06: the composed documentary negative was 1,251 chars — the bible base,
    ``_ANATOMY_NEG`` and the caller's ``extra_negative`` (``_FLUX_NEGATIVE`` +
    ``_ERA_NEGATIVE``) were plain-concatenated, so "bad anatomy" appeared x3,
    "extra fingers" x3, "watermark" x2. Order is preserved (the first, usually
    the bible's own, position wins) and empty clauses are dropped.
    """
    seen: set[str] = set()
    out: list[str] = []
    for clause in (negative or '').split(','):
        c = clause.strip()
        if not c:
            continue
        key = c.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return ', '.join(out)


def build_locked_negative_prompt(
    character_package: dict[str, Any] | None,
    *,
    studio_preview: bool = False,
    solo_subject: bool = True,
    human_subject: bool = True,
) -> str:
    """Negative prompt for ComfyUI node 21 — always populated from bible.

    ``solo_subject=False`` omits the bible's ``_SOLO_SUBJECT_NEG`` clause
    ("multiple people, crowd, group shot, character sheet, …"). P-06: with no
    character package the documentary path still inherited that ban on every
    slot; inert on schnell, live on Qwen at cfg 2.5 where it fights prompts
    that ask for crowds. Stage 3.5 should pass ``solo_subject=bool(package)``.
    """
    if _bible:
        try:
            base = _bible.negative_prompt_for_package(
                character_package,
                studio_preview=studio_preview,
                solo_subject=solo_subject,
            )
        except TypeError:  # older bible module without the kwarg(s)
            try:
                base = _bible.negative_prompt_for_package(
                    character_package,
                    studio_preview=studio_preview,
                )
            except TypeError:
                base = _bible.negative_prompt_for_package(character_package)
    else:
        base = 'blurry, low quality, deformed face, bad anatomy, extra fingers, extra limbs, watermark, text'
    # 2026-07-31: this whole hair/eye/age/skin defence used to be gated on
    # studio_preview, and the storyteller calls generate_still with the default
    # studio_preview=False — so episode scenes received NONE of the identity
    # defences that the 07-20/07-21/07-22 audits added. The attribute drift they
    # were written to stop (brown→black hair, age drift, skin lightening) was
    # never actually defended in delivered output. ZYG_IDENTITY_NEG_ALL_RENDERS=0
    # restores the studio-preview-only gate.
    _neg_all_renders = os.environ.get('ZYG_IDENTITY_NEG_ALL_RENDERS', '1') != '0'
    if (studio_preview or _neg_all_renders) and character_package:
        ident = character_package.get('identity') or {}
        hc = (ident.get('hair_color') or '').strip().lower()
        ec = (ident.get('eye_color') or '').strip().lower()
        st = (ident.get('skin_tone') or '').strip().lower()
        # Symmetric hair-colour defence (2026-07-22): every colour negates the
        # contradicting ones so the selected colour holds against the dark-hair
        # prior — not just black defended by negating browns (Maren: brown→black).
        _hair_neg = ''
        if _bible is not None and hasattr(_bible, 'hair_color_negatives'):
            try:
                _hair_neg = _bible.hair_color_negatives(hc, ident.get('ethnic_heritage'))
            except Exception:
                _hair_neg = ''
        if _hair_neg:
            base = f'{base}, {_hair_neg}'
        elif hc == 'black':
            base = f'{base}, brown hair, auburn hair, blonde hair, red hair'
        if ec == 'green':
            base = f'{base}, brown eyes, blue eyes'
        # Age-band defence (2026-07-22): push the wrong (usually too-young) age
        # into the negative so a mature spec is not dragged to FLUX's young default.
        _age_neg = ''
        if _bible is not None and hasattr(_bible, 'age_negatives'):
            try:
                _age_neg = _bible.age_negatives(ident.get('age'))
            except Exception:
                _age_neg = ''
        if _age_neg:
            base = f'{base}, {_age_neg}'
        # Symmetric skin-tone defence (2026-07-21): push the CONTRADICTING-
        # direction tones into the negative so the requested tone holds against
        # both FLUX's light-skin prior AND a heritage token implying a different
        # tone. Replaces the old dark-only defence — a fair request on a
        # dark-associated heritage (light-skinned Caribbean) is now defended
        # exactly as a dark request is defended against lightening.
        _skin_neg = ''
        if _bible is not None and hasattr(_bible, 'skin_tone_negatives'):
            try:
                _skin_neg = _bible.skin_tone_negatives(st, ident.get('ethnic_heritage'))
            except Exception:
                _skin_neg = ''
        if _skin_neg:
            base = f'{base}, {_skin_neg}'
        # FLUX-dev's dark-skin training distribution skews toward illustrated /
        # animated aesthetics (oversized cartoon eyes, painted skin) — keep the
        # anti-stylization push for dark tones specifically.
        _dark = ('olive', 'tan', 'dark', 'deep')
        if _bible is not None:
            _dark = getattr(_bible, '_DARK_SKIN_TONES', _dark)
        if st in _dark:
            base = (
                f'{base}, cartoon eyes, big anime eyes, oversized irises, '
                f'illustrated face, digital painting, concept art, '
                f'pixar style, disney style, animated character, '
                f'3d rendered face, cel-shaded, comic book style'
            )
    if not human_subject:
        # Also applied here, not only in generate_still, so a direct caller of
        # this function gets the same subject-correct string. Idempotent:
        # generate_still re-runs it after appending the caller's extra_negative,
        # which this function never sees.
        base = _strip_clause_tokens(base, _NONHUMAN_NEG_STRIP)
    return base
