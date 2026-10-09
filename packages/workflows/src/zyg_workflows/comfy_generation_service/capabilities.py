# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ComfyUI asset/capability probes - IPAdapter, PuLID, Qwen, Klein, pose ControlNet (original lines 300-541, 207-216)."""

from __future__ import annotations

import os
from zyg_workflows.comfy_generation_service.constants import _COMFY_LORA_DIR, _COMFY_ROOT, _comfy


def has_flux_ipadapter() -> bool:
    return _comfy is not None and _comfy.has_node('LoadFluxIPAdapter')


def has_pulid_flux() -> bool:
    """PuLID-FLUX identity lock available (lldacing node + weights on disk)."""
    return (
        _comfy is not None
        and _comfy.has_node('ApplyPulidFlux')
        and os.path.isfile(os.path.join(_COMFY_ROOT, 'models', 'pulid', 'pulid_flux_v0.9.1.safetensors'))
    )


def qwen_edit_unet() -> str | None:
    """Preferred Qwen-Image-Edit checkpoint: env override → bf16 → fp8.

    fp8 quantization measurably eats high-frequency facial detail (skin
    texture first); bf16 (41 GB) fits the 48 GB card since models load
    sequentially, so prefer it whenever the file exists.
    """
    override = os.environ.get('ZYG_QWEN_EDIT_UNET', '').strip()
    candidates = (
        [override]
        if override
        else [
            'qwen_image_edit_2509_bf16.safetensors',
            'qwen_image_edit_2509_fp8_e4m3fn.safetensors',
        ]
    )
    for name in candidates:
        if name and os.path.isfile(os.path.join(_COMFY_ROOT, 'models', 'diffusion_models', name)):
            return name
    return None


def qwen_t2i_unet() -> str | None:
    """Qwen-Image-2512 generator checkpoint (Apache-2.0 — the FLUX.1-dev exit
    base, 2026-08-09). Env override ZYG_QWEN_T2I_UNET."""
    override = os.environ.get('ZYG_QWEN_T2I_UNET', '').strip()
    candidates = (
        [override]
        if override
        else [
            'qwen_image_2512_fp8_e4m3fn.safetensors',
        ]
    )
    for name in candidates:
        if name and os.path.isfile(os.path.join(_COMFY_ROOT, 'models', 'diffusion_models', name)):
            return name
    return None


def has_qwen_t2i() -> bool:
    """Qwen-Image-2512 text-to-image path available."""
    return _comfy is not None and qwen_t2i_unet() is not None


def klein_t2i_unet() -> str | None:
    """FLUX.2 [klein] 4B generator checkpoint (Apache-2.0, 2026-08-23).

    Two variants ship: ``base`` is UNDISTILLED — it is what LoRA training needs
    and what a fair quality comparison against Qwen-2512 must use — and the
    plain ``flux-2-klein-4b`` is step-distilled for 4-step throughput. Default
    is base; ZYG_KLEIN_DISTILLED=1 selects the fast one.

    Only the 4B is Apache-2.0. FLUX.2-klein-base-9B and FLUX.2 [dev] are
    non-commercial, and both are registered as explicit DENY rules in
    data/runtime/model_licences.json so a 9B download cannot be mistaken for
    its permissive sibling."""
    override = os.environ.get('ZYG_KLEIN_T2I_UNET', '').strip()
    if override:
        candidates = [override]
    elif os.environ.get('ZYG_KLEIN_DISTILLED', '0').strip().lower() in ('1', 'true', 'yes', 'on'):
        candidates = ['flux-2-klein-4b.safetensors', 'flux-2-klein-base-4b.safetensors']
    else:
        candidates = ['flux-2-klein-base-4b.safetensors', 'flux-2-klein-4b.safetensors']
    for name in candidates:
        if name and os.path.isfile(os.path.join(_COMFY_ROOT, 'models', 'diffusion_models', name)):
            return name
    return None


def klein_is_distilled(unet: str | None = None) -> bool:
    """True when the resolved klein checkpoint is the step-distilled variant.

    The distilled model wants cfg 1.0 and ~4 steps; the base wants cfg ~5 and
    ~20. Running one at the other's settings is the FLUX-schnell mistake again,
    so the sampler patch reads this rather than trusting the caller."""
    name = (unet if unet is not None else (klein_t2i_unet() or '')).lower()
    return bool(name) and 'base' not in name


def klein_text_encoder() -> str | None:
    """Qwen3-4B text encoder bundled with klein (models/text_encoders)."""
    name = os.environ.get('ZYG_KLEIN_CLIP', '').strip() or 'qwen_3_4b.safetensors'
    p = os.path.join(_COMFY_ROOT, 'models', 'text_encoders', name)
    return name if os.path.isfile(p) else None


def klein_vae() -> str | None:
    """FLUX.2 VAE. Fetched from the apache-2.0 Comfy-Org/flux2-klein repo, not
    from Comfy-Org/flux2-dev (license=other) which carries an identical file."""
    name = os.environ.get('ZYG_KLEIN_VAE', '').strip() or 'flux2-vae.safetensors'
    p = os.path.join(_COMFY_ROOT, 'models', 'vae', name)
    return name if os.path.isfile(p) else None


# FLUX.2 has no ControlNet — the geometric-control route for this family is a CONTROL
# LoRA. RefControl (thedeoxen, Apache-2.0, trained on FLUX.2-klein-base-4B, the exact
# base this repo trains on) fuses a depth map with a reference image: depth as reference
# image 1, appearance as reference image 2, trigger word `refcontrol`. Both halves of the
# licence are clean, which is the whole reason this one and not the klein-9B or dev
# variants — those are flux-non-commercial and must never reach a monetised render.
_KLEIN_CONTROL_LORA = 'flux2_klein_4b_refcontrol_depth.safetensors'


def klein_control_lora_name() -> str | None:
    """The staged RefControl depth adapter, or None when it is not installed."""
    name = os.environ.get('ZYG_KLEIN_CONTROL_LORA', '').strip() or _KLEIN_CONTROL_LORA
    return name if os.path.isfile(os.path.join(_COMFY_LORA_DIR, name)) else None


def klein_control_lora_scale(name: str | None = None) -> float:
    """Strength for the control adapter — 1.0, and DELIBERATELY NOT default_lora_scale().

    default_lora_scale() answers a different question: it reads the safetensors header and
    returns 1.0 for an adapter carrying `.alpha` keys (our own qwen/klein exports, where
    ComfyUI would otherwise apply strength * alpha/rank) and the legacy 0.85 for one that
    does not. RefControl is a third-party ai-toolkit export with NO alpha keys, so that
    heuristic would hand it 0.85 — a number calibrated for OUR alpha-less flux/sdxl
    exports and meaningless for this file. Its model card states 0.8-1.0; 1.0 is the
    value its own reference workflow ships.
    """
    del name
    try:
        return max(0.0, min(2.0, float(os.environ.get('ZYG_KLEIN_CONTROL_LORA_SCALE', '1.0'))))
    except ValueError:
        return 1.0


def has_klein_refcontrol() -> bool:
    """klein is renderable AND the control adapter is on disk."""
    return has_klein_t2i() and klein_control_lora_name() is not None


def has_klein_t2i() -> bool:
    """All three klein components present and Comfy reachable."""
    return (
        _comfy is not None
        and klein_t2i_unet() is not None
        and klein_text_encoder() is not None
        and klein_vae() is not None
    )


def _graph_is_klein(workflow: dict) -> bool:
    """True when *workflow* is one of the FLUX.2 klein graphs.

    The per-cell contact sheet renders every non-anchor cell through the
    QWEN EDIT graph while model_family stays the anchor family — the FLUX
    pathway has always worked that way. So `mf == 'klein'` does NOT mean "this
    graph is a klein graph": on an edit cell it is qwen_edit_angle, whose
    nodes 11/12 are the Qwen CLIP and VAE. Patching them to the klein encoder
    and flux2 VAE there would break every rotation cell of a klein sheet.
    The family block therefore keys on the GRAPH, not the family.
    """
    n11 = (workflow.get('11') or {}).get('inputs') or {}
    return n11.get('type') == 'flux2' or (workflow.get('31') or {}).get('class_type') == 'SamplerCustomAdvanced'


def klein_missing_parts() -> list[str]:
    """Which klein components are absent — for a log line that says WHICH."""
    out = []
    if klein_t2i_unet() is None:
        out.append('diffusion_models/flux-2-klein-base-4b.safetensors')
    if klein_text_encoder() is None:
        out.append('text_encoders/qwen_3_4b.safetensors')
    if klein_vae() is None:
        out.append('vae/flux2-vae.safetensors')
    return out


def has_qwen_hand_inpaint() -> bool:
    """InstantX Qwen inpaint CN + 2512 base available for HandFixer."""
    return (
        _comfy is not None
        and qwen_t2i_unet() is not None
        and os.path.isfile(
            os.path.join(_COMFY_ROOT, 'models', 'controlnet', 'Qwen-Image-InstantX-ControlNet-Inpainting.safetensors')
        )
    )


def qwen_edit_angles_lora_name() -> str:
    """Multi-angle LoRA filename under models/loras, subdir-relative allowed
    (e.g. 'qwen_edit_2511/qwen-image-edit-2511-multiple-angles-lora.safetensors').
    Env override ZYG_QWEN_EDIT_ANGLES_LORA switches to the Edit-2511 retrain;
    unset keeps the flat dx8152 2509 file."""
    return os.environ.get('ZYG_QWEN_EDIT_ANGLES_LORA', '').strip() or 'qwen_edit_2509_multiple_angles.safetensors'


def has_qwen_edit_angles() -> bool:
    """Qwen-Image-Edit-2509 + dx8152 multi-angle LoRA available for camera-rotation edits."""
    return (
        _comfy is not None
        and _comfy.has_node('TextEncodeQwenImageEditPlus')
        and qwen_edit_unet() is not None
        and os.path.isfile(os.path.join(_COMFY_ROOT, 'models', 'loras', qwen_edit_angles_lora_name()))
    )


_UNION_CN_FILE = os.environ.get(
    'ZYG_FLUX_UNION_CONTROLNET',
    'FLUX.1-dev-ControlNet-Union-Pro.safetensors',
).strip()
_POSE_DIR = os.environ.get(
    'ZYG_CONTACT_SHEET_POSE_DIR',
    # Split deviation: this module sits one directory deeper than the old
    # comfy_generation_service.py, so one extra dirname() keeps _POSE_DIR on
    # zyg_workflows/assets/contact_sheet_poses exactly as before.
    os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets', 'contact_sheet_poses'),
)


def has_flux_union_pose_controlnet() -> bool:
    if _comfy is None or not _comfy.has_node('ControlNetLoader'):
        return False
    cn_path = os.path.join(_COMFY_ROOT, 'models', 'controlnet', _UNION_CN_FILE)
    return os.path.isfile(cn_path)


def pose_locked_stack_ready() -> bool:
    """IP-Adapter + Shakker Union pose + static pose library."""
    if not has_flux_ipadapter() or not has_flux_union_pose_controlnet():
        return False
    if not _comfy.has_node('SetShakkerLabsUnionControlNetType'):
        return False
    if not _comfy.has_node('XlabsSampler'):
        return False
    pose0 = os.path.join(_POSE_DIR, 'angle_00.png')
    return os.path.isfile(pose0)


def pose_map_path(index: int) -> str:
    return os.path.join(_POSE_DIR, f'angle_{int(index):02d}.png')


def pick_scholarly_anatomy_workflow(
    reference_image: str | None,
    pose_image: str | None,
) -> tuple[str, str]:
    """Workflow for scholarly anatomy stills — pose+IP+CN when stack is ready."""
    if pose_image and os.path.isfile(pose_image) and pose_locked_stack_ready():
        return 'flux_pose_ipa_cell', 'pose_ipa_cn'
    if reference_image and os.path.isfile(reference_image) and has_flux_ipadapter():
        return 'flux_character_ipadapter', 'ipadapter_ref'
    return 'flux_txt2img', 'txt2img_fallback'
