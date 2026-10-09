# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Workflow template selection, LoRA staging and post-save drift QA (original lines 1702-1963)."""

from __future__ import annotations

import os
import re
import shutil
from typing import Any, Callable
from zyg_workflows.comfy_generation_service.constants import (
    _CHAR_DRIFT_ANIMATED,
    _CHAR_DRIFT_MIN,
    _COMFY_LORA_DIR,
    _COMFY_ROOT,
    _SDXL_ALIGNED_CKPT,
    _SDXL_ANIMATED_CKPT,
    _SDXL_FALLBACK_CKPT,
    _comfy,
)
from zyg_workflows.comfy_generation_service.capabilities import has_flux_ipadapter, klein_control_lora_name
from zyg_workflows.comfy_generation_service.flux_graph import has_instantid
from zyg_workflows.comfy_generation_service.style import (
    _is_photoreal_render_style,
    _lora_path_matches_model_family,
    _normalize_model_family,
    _render_style_from_package,
    _restyle_profile_from_package,
)


def _resolve_checkpoint_sdxl(character_package: dict[str, Any] | None) -> str:
    """Checkpoint for Comfy SDXL — photoreal previews prefer Juggernaut when present.

    Exception (2026-07-18): when the package carries a character SDXL LoRA,
    render on the ALIGNED base — the LoRA was trained on SDXL base 1.0, and
    applying it on Juggernaut (a different fine-tune) weakens the identity it
    was trained to lock. Juggernaut remains the photoreal pick only for
    LoRA-less renders.
    """
    cond = (character_package or {}).get('conditioning') or {}
    ckpt = str(cond.get('sdxl_checkpoint') or cond.get('comfy_sdxl_checkpoint') or '').strip()
    ckpt_dir = os.path.join(_COMFY_ROOT, 'models', 'checkpoints')
    render_st = _render_style_from_package(character_package)
    _sdxl_lora = str(cond.get('sdxl_lora_path') or '').strip()
    _has_char_sdxl_lora = bool(_sdxl_lora and os.path.isfile(_sdxl_lora))
    # 2026-07-27: a restyle char (Arcane) renders on the profile's render_checkpoint —
    # the base its LoRA was BAKED on (Juggernaut) — never the DynaVision animated
    # default or the aligned SDXL base. Profile-driven (checks the restyle profile
    # directly, not the render_style string) so it holds whether called from the
    # episode render (render_style mutated to 'restyle') or the QC valve (render_style
    # still 'photorealistic'), and even for a future restyle char with no ckpt pin.
    _rprof_ck = _restyle_profile_from_package(character_package)
    if _rprof_ck:
        _rck = str(_rprof_ck.get('render_checkpoint') or '').strip()
        if _rck and os.path.isfile(os.path.join(ckpt_dir, _rck)):
            return _rck
    # 2026-07-25: animated SDXL renders on the 3D-toon checkpoint. An explicit
    # on-disk sdxl_checkpoint in the bible still wins (per-char override); only
    # fall back to the animated default when none is pinned.
    if render_st == 'animated' and not ckpt and os.path.isfile(os.path.join(ckpt_dir, _SDXL_ANIMATED_CKPT)):
        return _SDXL_ANIMATED_CKPT
    if not ckpt:
        if _has_char_sdxl_lora and os.path.isfile(
            os.path.join(ckpt_dir, _SDXL_ALIGNED_CKPT),
        ):
            ckpt = _SDXL_ALIGNED_CKPT
        elif _is_photoreal_render_style(render_st) and os.path.isfile(
            os.path.join(ckpt_dir, _SDXL_FALLBACK_CKPT),
        ):
            ckpt = _SDXL_FALLBACK_CKPT
        else:
            ckpt = _SDXL_ALIGNED_CKPT
    if os.path.isfile(os.path.join(ckpt_dir, ckpt)):
        return ckpt
    if _is_photoreal_render_style(render_st) and os.path.isfile(
        os.path.join(ckpt_dir, _SDXL_FALLBACK_CKPT),
    ):
        return _SDXL_FALLBACK_CKPT
    if os.path.isfile(os.path.join(ckpt_dir, _SDXL_ALIGNED_CKPT)):
        return _SDXL_ALIGNED_CKPT
    if os.path.isfile(os.path.join(ckpt_dir, _SDXL_FALLBACK_CKPT)):
        return _SDXL_FALLBACK_CKPT
    return ckpt


def _workflow_template_exists(name: str) -> bool:
    """True when <name>.json is on disk, without loading or raising.

    _comfy.load_workflow raises ComfyUIError on a missing template, and the one
    caller that needs this is choosing whether to switch graphs at all — a
    try/except around a full JSON parse would be a parse per render.
    """
    try:
        return (_comfy._WORKFLOW_DIR / f'{name}.json').is_file()
    except Exception:
        return False


def _stage_style_lora(
    lora_path: str | None,
    log_fn: Callable[[str], None],
) -> str | None:
    """Copy a style LoRA into Comfy for flux_txt2img_style workflow."""
    if not lora_path or not os.path.isfile(lora_path):
        return None
    os.makedirs(_COMFY_LORA_DIR, exist_ok=True)
    dst = os.path.join(_COMFY_LORA_DIR, 'style_lora.safetensors')
    lora_name = 'style_lora.safetensors'
    try:
        if not os.path.isfile(dst) or os.path.getmtime(lora_path) > os.path.getmtime(dst):
            shutil.copy2(lora_path, dst)
            log_fn(f'ComfyGen: staged style LoRA → {dst}')
        return lora_name
    except Exception as exc:
        log_fn(f'ComfyGen: could not stage style LoRA ({exc}) — continuing without')
        return None


def _char_id_from_lora_path(lora_path: str | None) -> str:
    """Recover the 12-hex char_id from …/storyteller_chars/<char_id>/lora-weights-*/…"""
    if not lora_path:
        return ''
    m = re.search(r'/([a-f0-9]{12})/lora-weights', lora_path.replace('\\', '/'))
    return m.group(1) if m else ''


def _stage_character_lora(
    lora_path: str | None,
    log_fn: Callable[[str], None],
    *,
    model_family: str = 'flux',
    char_id: str = '',
) -> str | None:
    """Copy trained character LoRA into Comfy under a PER-CHARACTER filename.

    2026-07-31: this used to copy every character's adapter onto ONE shared name
    ('character_lora.safetensors' / 'character_sdxl_lora.safetensors') and skip the
    copy when getmtime(src) <= getmtime(dst). shutil.copy2 preserves mtimes, so that
    guard compared two *characters'* training timestamps: any character trained
    earlier than whoever was staged last silently rendered with the OTHER
    character's weights, under its own trigger token, with no log line. Measured at
    the time of the fix: 28/28 SDXL and 37/39 FLUX adapters were in that state, and
    Abel (c3345deb5bde) was rendering with his father's LoRA (0015c8a3f2e3).
    Per-character naming matches arcane_restyle._stage_char_lora, which got it right.
    """
    mf = _normalize_model_family(model_family)
    if not _lora_path_matches_model_family(lora_path, mf):
        if lora_path:
            log_fn(
                f'ComfyGen: skip staging LoRA — path is not for {mf.upper()} ({os.path.basename(lora_path)})',
            )
        return None
    os.makedirs(_COMFY_LORA_DIR, exist_ok=True)
    label = mf.upper()  # mf is already normalized to flux/sdxl/qwen
    cid = (char_id or '').strip().lower() or _char_id_from_lora_path(lora_path)
    if not re.fullmatch(r'[a-f0-9]{12}', cid or ''):
        # No identity to key on. The legacy shared name is the ONLY thing we could
        # fall back to, and that is exactly the collision this function now exists
        # to prevent — refuse rather than risk rendering the wrong character.
        log_fn(
            f'ComfyGen: cannot stage {label} character LoRA — no char_id resolvable '
            f'from {os.path.basename(lora_path or "")!r}; refusing shared-name fallback',
        )
        return None
    lora_name = f'zygchar_{cid}_{mf}.safetensors'
    dst = os.path.join(_COMFY_LORA_DIR, lora_name)
    try:
        src_st = os.stat(lora_path)
        need_copy = True
        if os.path.isfile(dst):
            dst_st = os.stat(dst)
            # Size + mtime_ns identity, not "is the source newer" — a same-size,
            # same-timestamp file is the same export; anything else is re-copied.
            need_copy = not (src_st.st_size == dst_st.st_size and src_st.st_mtime_ns == dst_st.st_mtime_ns)
        if need_copy:
            _tmp = dst + '.part'
            shutil.copy2(lora_path, _tmp)
            os.replace(_tmp, dst)
            log_fn(f'ComfyGen: staged {label} character LoRA for {cid} → {lora_name}')
        if os.path.getsize(dst) != src_st.st_size:
            log_fn(
                f'ComfyGen: staged {label} LoRA size mismatch for {cid} '
                f'({os.path.getsize(dst)} != {src_st.st_size}) — refusing',
            )
            return None
        return lora_name
    except Exception as exc:
        log_fn(f'ComfyGen: could not stage LoRA ({exc}) — continuing without')
        return None


def _pick_workflow(
    character_package: dict[str, Any] | None,
    init_image: str | None,
    reference_image: str | None,
    lora_name: str | None,
    model_family: str | None = None,
    *,
    blender_dataset: bool = False,
    force_workflow: str | None = None,
    pose_image: str | None = None,
) -> str:
    if force_workflow:
        return force_workflow
    mf = _normalize_model_family(model_family)
    if mf == 'klein':
        # FLUX.2 [klein] 4B (Apache-2.0). An init image routes to the edit graph
        # — ReferenceLatent conditioning, the same role qwen_edit_angle plays for
        # the per-cell sheet. A staged klein character LoRA routes to the
        # LoRA-locked txt2img graph (2026-08-25), exactly as qwen does.
        #
        # 2026-08-26: klein_edit_angle now carries LoraLoader node 13, so an init
        # image and a character LoRA COMBINE instead of the init silently winning.
        # That is what lets a Blender render of the creature's mesh supply the
        # POSE while the trained adapter supplies the APPEARANCE — the only
        # geometric-control route open to this family, since there is no FLUX.2
        # depth ControlNet installed and the FLUX.1-dev Union stack is both a
        # different base model and licence-paused. `_flux_rewire_without_lora`
        # is generic over node ids and already bypasses 13 when nothing is staged.
        # 2026-08-26 (later that day): a DEPTH map routes to klein_refcontrol, which is
        # the same ReferenceLatent mechanism but with two chained references and the
        # RefControl adapter stacked on the identity LoRA. Preferred over
        # klein_edit_angle whenever a control image is supplied, because it is the only
        # klein path where the geometry is CONDITIONED rather than suggested: measured on
        # this creature, klein_edit_angle handed a true top-down mesh render came back as
        # a three-quarter front view, and klein_pose_i2i holds the pose at denoise 0.62
        # but stops carrying the trained appearance.
        # BOTH images or nothing. klein_refcontrol needs a second reference by
        # construction, so routing to it on a control image alone would turn a render
        # that used to succeed (klein ignored pose_image entirely before today) into a
        # hard failure. Requiring the pair here keeps every existing caller on its old
        # path and lets the branch's own guards stay defensive rather than load-bearing.
        _ref_for_ctrl = reference_image or init_image
        if pose_image and os.path.isfile(pose_image) and _ref_for_ctrl and os.path.isfile(_ref_for_ctrl):
            if klein_control_lora_name():
                return 'klein_refcontrol'
            # Falling through silently would render a depth map as if it were a photo
            # of the creature; the caller logs that, where `log` is in scope.
        if init_image and os.path.isfile(init_image):
            return 'klein_edit_angle'
        return 'klein_character_locked' if lora_name else 'klein_txt2img'
    if mf == 'qwen':
        # 2512 generator path (2026-08-09). The cast retrain is landing: a staged
        # qwen character LoRA routes to the LoRA-locked graph; LoRA-less renders
        # stay on plain txt2img.
        return 'qwen_character_locked' if lora_name else 'qwen_txt2img'
    if init_image and os.path.isfile(init_image):
        # 2026-07-31: sdxl_img2img.json has NO LoraLoader node, so an SDXL
        # img2img render silently threw away a staged character LoRA — the
        # identity lock vanished with no log line. flux_img2img does carry
        # node 13, so only the SDXL leg is affected. Prefer the LoRA-locked
        # graph when we actually have an adapter; ZYG_SDXL_I2I_KEEP_LORA=0
        # restores the old (identity-free) routing.
        if mf == 'sdxl' and lora_name and os.environ.get('ZYG_SDXL_I2I_KEEP_LORA', '1') != '0':
            return 'sdxl_character_locked'
        return 'flux_img2img' if mf == 'flux' else 'sdxl_img2img'
    # Trained character LoRA + txt2img is the primary SDXL preview path.
    if lora_name and mf == 'sdxl':
        return 'sdxl_character_locked'
    if lora_name and mf == 'flux':
        return 'flux_character_locked'
    cond = (character_package or {}).get('conditioning', {}) or {}
    instantid_opt_in = bool(cond.get('instantid_enabled', False))
    if (
        not blender_dataset
        and instantid_opt_in
        and reference_image
        and os.path.isfile(reference_image)
        and has_instantid()
    ):
        return 'flux_character_instantid' if mf == 'flux' else 'sdxl_character_instantid'
    if reference_image and os.path.isfile(reference_image):
        if mf == 'flux' and has_flux_ipadapter():
            return 'flux_character_ipadapter'
        if mf == 'sdxl':
            return 'sdxl_img2img'
    return 'flux_txt2img' if mf == 'flux' else 'sdxl_txt2img'


def _drift_threshold_for_package(character_package: dict[str, Any] | None) -> float:
    style = (character_package or {}).get('style_profile') or {}
    render = (style.get('render_style') or '').strip().lower()
    # A painterly Arcane render legitimately diverges more from the photoreal bible
    # reference embedding; use the relaxed animated floor (still parks true drift).
    # Keyed on the 'restyle' SENTINEL only (NOT the profile) so it is mf-safe: the SDXL
    # episode render mutates render_style→'restyle' (caught here), the SDXL QC valve
    # mutates pkg_locked→'restyle' before its _post_save, and the photoreal FLUX twin
    # leg of a restyle char keeps render_style='photorealistic' → strict 0.60 floor.
    if render in ('animated', 'restyle'):
        return _CHAR_DRIFT_ANIMATED
    return _CHAR_DRIFT_MIN
