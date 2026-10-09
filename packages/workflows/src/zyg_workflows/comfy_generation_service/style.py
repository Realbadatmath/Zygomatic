# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Model family / checkpoint resolution, restyle profiles and LoRA staging (original lines 1396-1700)."""

from __future__ import annotations

import os
from typing import Any, Callable
from zyg_workflows.comfy_generation_service.constants import (
    _COMFY_ROOT,
    _FLUX_SCHNELL,
    _HF_REVISION,
    _SDXL_ALIGNED_CKPT,
    _SDXL_TRAIN_REPO_ID,
    _log_default,
)


def _resolve_unet(character_package: dict[str, Any] | None) -> str:
    cond = (character_package or {}).get('conditioning', {})
    if cond.get('lora_path') and os.path.isfile(cond['lora_path']):
        return 'flux1-dev.safetensors'
    return 'flux1-schnell.safetensors' if os.path.isdir(_FLUX_SCHNELL) else 'flux1-dev.safetensors'


def _normalize_model_family(model_family: str | None) -> str:
    mf = (model_family or '').strip().lower()
    return mf if mf in ('flux', 'sdxl', 'qwen', 'klein') else 'flux'


def ensure_sdxl_comfy_checkpoint(log_fn: Callable[[str], None] | None = None) -> str:
    """Ensure ``sd_xl_base_1.0.safetensors`` exists in Comfy checkpoints (matches LoRA train base)."""
    _log = log_fn or _log_default
    ckpt_dir = os.path.join(_COMFY_ROOT, 'models', 'checkpoints')
    os.makedirs(ckpt_dir, exist_ok=True)
    dest = os.path.join(ckpt_dir, _SDXL_ALIGNED_CKPT)
    if os.path.isfile(dest) and os.path.getsize(dest) > 500_000_000:
        return _SDXL_ALIGNED_CKPT
    _log(
        f'ComfyGen: downloading aligned SDXL checkpoint {_SDXL_ALIGNED_CKPT} '
        f'from {_SDXL_TRAIN_REPO_ID} (~6.5 GB, one-time)…',
    )
    try:
        from huggingface_hub import hf_hub_download

        hf_hub_download(
            repo_id=_SDXL_TRAIN_REPO_ID,
            filename=_SDXL_ALIGNED_CKPT,
            local_dir=ckpt_dir,
            revision=_HF_REVISION,
        )
    except Exception as exc:
        raise RuntimeError(
            f'Failed to download aligned SDXL checkpoint to {dest}: {exc}',
        ) from exc
    if not os.path.isfile(dest) or os.path.getsize(dest) < 500_000_000:
        raise RuntimeError(f'SDXL checkpoint download incomplete: {dest}')
    _log(f'ComfyGen: aligned SDXL checkpoint ready → {dest}')
    return _SDXL_ALIGNED_CKPT


def _render_style_from_package(character_package: dict[str, Any] | None) -> str:
    if not character_package:
        return ''
    style = character_package.get('style_profile') or {}
    ident = character_package.get('identity') or {}
    return (style.get('render_style') or ident.get('render_style') or '').strip().lower()


def _is_photoreal_render_style(render_style: str) -> bool:
    return render_style in ('photorealistic', 'cinematic', 'realistic', 'photo')


def _restyle_profile_from_package(character_package: dict[str, Any] | None) -> dict | None:
    """Resolve a character's isolated STYLE-restyle profile (e.g. Arcane) if its bible
    carries style_profile.restyle=<name> naming a valid profile in
    character_style_profiles.json. Returns the profile dict (the outer profile, whose
    ['restyle'] holds the recipe) or None.

    This is the SINGLE gate for the 'restyle' render mode — a THIRD effective render
    style distinct from 'photorealistic' and the DynaVision 'animated' path. The lazy,
    guarded import means a missing/broken arcane_restyle module degrades to None (no-op)
    and never raises into a render; public/global characters never carry
    style_profile.restyle, so they always get None → every restyle branch is skipped.
    """
    name = ((character_package or {}).get('style_profile') or {}).get('restyle')
    if not name:
        return None
    try:
        from zyg_workflows import arcane_restyle as _ar_rs

        prof = _ar_rs.load_profile(str(name))
        return prof if (prof and prof.get('restyle')) else None
    except Exception:
        return None


# 2026-07-27: photoreal-forcing POSITIVE phrases + anti-PAINTERLY NEGATIVE phrases that
# other assembly sites (apply_auto_defaults-baked conditioning.quality_suffix /
# conditioning.negative_prompt, identity_prompt_prefix, the dark-skin anti-illustration
# wall, storyteller_quality_suffix) inject BEFORE the 'restyle' sentinel exists. The
# restyle sanitizer drops any comma-clause containing one of these from the FINALIZED
# prompt/negative, so it cleans every source at once for episode AND QC-valve renders.
# NOTE: anti-anime / anti-flat-cartoon negatives (anime, manga, cel shading, flat
# colors, line art) are intentionally KEPT — Arcane is painterly-semi-realistic, NOT
# flat anime, so those negatives help (they guard the tile-23 flat-anime failure mode).
_RESTYLE_POS_STRIP = (
    'raw photograph',
    'raw photo',
    'dslr',
    'unretouched real person',
    'unretouched',
    'visible skin pores',
    'visible pores',
    'natural skin microdetail',
    'natural skin grain',
    'skin microdetail',
    'macro facial texture',
    'subtle skin imperfections',
    'skin imperfections',
    'no beauty filter',
    'fine film grain',
    'film grain',
    'realistic skin texture',
    'realistic skin and fabrics',
    'realistic skin',
    'realistic textures',
    'photorealistic',
    'photoreal',
    '85mm portrait lens',
    '85mm',
    'f/5.6',
    '8k',
)
_RESTYLE_NEG_STRIP = (
    'painterly',
    'digital painting',
    'concept art',
    'illustration',
    'illustrated face',
    'illustrated',
    'oil painting',
    'oil-painting',
    'hand-painted',
    'hand painted',
    'brush strokes',
    'brushstrokes',
    'watercolor',
    'gouache',
    'impasto',
    'overly smooth skin',
    'porcelain skin',
    'poreless',
    'smooth flawless skin',
    # the dark-skin wall's generic 'animated character' opposes the arcane 2D-animation
    # positive (unlike pixar/disney/3d/cel-shaded which we keep as anti-flat guards)
    'animated character',
)


# Clauses that only make sense when the subject is a PERSON. Dropped whenever
# a caller declares human_subject=False (creatures, animals, props).
#
# 2026-08-26, measured on the Zygo AI Pufferball klein LoRA: his real anatomy is
# two short arms with stubby fingers and two THREE-toed feet, and the composed
# negative — bible base + _ANATOMY_NEG + the creature caller's own _NEG — was
# telling a live cfg-4.0 sampler to avoid "hands", "claw hands", "three fingers",
# "3 fingers", "extra arms", "extra limbs", "fused limbs". Those clauses exist to
# protect human hands; on a creature they argue against the body plan. He
# rendered as a fur ball with a face and no limbs at all.
#
# Kept deliberately, and the line is narrow on purpose:
#   * 'human hand', 'human face', 'person' — a creature must still not grow a
#     HUMAN hand; that clause is doing its job.
#   * 'bad anatomy', 'deformed face', 'melted', 'deformed limbs', 'fused limbs'
#     — species-neutral defect guards. A creature wants these too.
#   * 'extra limbs' / 'extra arms' / 'extra legs' — the operator body-plan brief
#     asks for exactly these ("no extra tail, wings, fins or limbs that are not
#     listed"). Banning a SURPLUS limb does not contradict having the listed ones.
# Only the finger-COUNT and hand-QUALITY clauses go, because those are the ones
# a three-toed foot and a stubby four-finger hand actually contradict, plus the
# human-jewelry clauses which are pure noise on an animal.
_NONHUMAN_NEG_STRIP = (
    'fingers',
    'mutated hands',
    'malformed hands',
    'claw hands',
    'asymmetric earrings',
    'mismatched jewelry',
    'duplicate earrings',
)


_ALPHA_CACHE: dict[str, bool] = {}


def lora_has_alpha(path: str) -> bool:
    """True when an exported LoRA carries `.alpha` keys. Reads only the header."""
    if not path or not os.path.isfile(path):
        return False
    key = os.path.realpath(path)
    if key in _ALPHA_CACHE:
        return _ALPHA_CACHE[key]
    ok = False
    try:
        # Both imported locally: this module has no module-level `json`, and the
        # blanket except below turned that NameError into a silent False — the
        # function reported "no alpha" for a file with 40 alpha keys.
        import json as _json
        import struct

        with open(path, 'rb') as fh:
            n = struct.unpack('<Q', fh.read(8))[0]
            if 0 < n < 64 * 1024 * 1024:
                hdr = _json.loads(fh.read(n))
                ok = any(k.endswith('.alpha') for k in hdr if k != '__metadata__')
    except Exception:
        ok = False
    _ALPHA_CACHE[key] = ok
    return ok


def default_lora_scale(staged_name: str | None, fallback: float = 0.85) -> float:
    """The loader strength that reproduces TRAINING strength for this adapter.

    2026-08-26. ComfyUI applies `strength * (alpha / rank)` when the file carries
    alpha keys, and plain `strength` when it does not (comfy/weight_adapter/lora.py
    :249,283). Training applies alpha/rank = 32/64 = 0.5. So:

        alpha exported (qwen, klein)  -> strength 1.0  == trained 0.5   CORRECT
        alpha missing  (flux, sdxl)   -> strength 0.85 == 1.7x OVER     legacy

    Hardcoding 0.85 for every family therefore ran the alpha-carrying adapters at
    0.85 x 0.5 = 0.425, i.e. 15% UNDER training. Editing the workflow JSON does not
    fix it — this function's callers overwrite node 13 on every render, which is
    why a JSON-only change to klein_character_locked had no effect at all.

    An explicit `conditioning.lora_scale` still wins; this only replaces the
    hardcoded default. flux/sdxl keep 0.85 until their exporter emits alpha."""
    if not staged_name:
        return fallback
    p = staged_name if os.path.isabs(staged_name) else os.path.join(_COMFY_ROOT, 'models', 'loras', staged_name)
    return 1.0 if lora_has_alpha(p) else fallback


def _strip_clause_tokens(text: str, tokens: tuple) -> str:
    """Drop each comma-clause of `text` that contains any of `tokens` (case-insensitive)."""
    if not text:
        return text
    out = []
    for seg in str(text).split(','):
        low = seg.strip().lower()
        if low and any(t in low for t in tokens):
            continue
        s = seg.strip()
        if s:
            out.append(s)
    return ', '.join(out)


def _append_render_style_negatives(
    full_negative: str,
    render_st: str,
    *,
    studio_preview: bool = False,
) -> str:
    """Block cross-style bleed for both SDXL and FLUX previews."""
    neg = full_negative
    if render_st == 'animated':
        neg = (
            f'{neg}, photorealistic, photograph, dslr, raw photo, '
            'hyperreal skin, film grain, 8k photo, oil painting, soft brush, '
            'painterly, watercolor, '
            # 2026-07-25: rein in DynaVision's Pixar big-eye prior so eyes stay
            # proportional to the face.
            'oversized eyes, huge eyes, big anime eyes, bug eyes, enlarged eyes, '
            'giant eyeballs, disproportionate eyes, oversized irises'
        ).strip(', ')
    elif render_st == 'restyle':
        # 2026-07-27: painterly restyle (Arcane) — push AWAY from photoreal/3d-toon
        # but ALLOW painterly/illustration (the exact opposite of the photoreal
        # anti-cartoon wall below, which fights the baked-in Arcane look).
        neg = (
            f'{neg}, photograph, photorealistic, dslr, raw photo, film grain, '
            'visible skin pores, hyperreal skin, 3d render, pixar, disney 3d, cgi, '
            'plastic skin, sculpted 3d, wax figure skin, doll skin, '
            'oversized eyes, huge eyes, big anime eyes, bug eyes'
        ).strip(', ')
    elif _is_photoreal_render_style(render_st):
        neg = (
            f'{neg}, anime, cel shading, cartoon, illustration, '
            'line art, flat colors, 2d, manga, chibi, sketch, painting, '
            '3d render, game character, mannequin, plastic doll, '
            'perfect symmetry, airbrushed, retouched skin, poreless skin, '
            'smooth flawless skin, wax figure skin, doll skin, '
            'beauty photography, stock photo, commercial photography, '
            'CGI, octane render, unreal engine render, perfectly styled hair, '
            'too perfect, overly smooth, digital painting, concept art'
        ).strip(', ')
    if studio_preview:
        neg = (
            f'{neg}, office, classroom, desk, chair, window, sunset, '
            'balcony, sea, outdoor, furniture, papers, books, laptop, '
            'paint drips, clothing stains, green streaks on shirt, forehead seam, '
            'asymmetric earrings, mismatched jewelry, rim light artifact, cyan outline, '
            'deformed hands, three fingers, extra fingers, missing fingers, '
            'mutated hands, fused fingers, hands in pockets, gripping clothes, '
            'hands hidden, arms crossed, hands on hips'
        ).strip(', ')
    return neg


def _lora_path_matches_model_family(lora_path: str | None, model_family: str) -> bool:
    """Reject cross-architecture LoRA files (e.g. FLUX weights on SDXL)."""
    if not lora_path or not os.path.isfile(lora_path):
        return False
    norm = lora_path.replace('\\', '/').lower()
    mf = _normalize_model_family(model_family)
    _others = {'flux', 'sdxl', 'qwen', 'klein'} - {mf}
    if any(f'lora-weights-{o}' in norm for o in _others):
        return False
    return True
