# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Picking the reference image for a preview slot, and preview usability.

Moved verbatim out of the old single-file char_state_service.py (lines 1949-2170).
"""

import os
from zyg_workflows.char_state_service._common import (
    _preview_env_on,
    _zyg_log,
)
from zyg_workflows.char_state_service.lora_discovery import (
    _char_photoreal_hybrid_preview,
    _char_preview_png_names,
    _normalize_char_model_family,
)


def _is_generated_preview_name(path_or_name: str) -> bool:
    """True for preview_*.png / style_preview_* artifacts — never identity ground truth.

    2026-07-31: for c3345deb5bde the ONLY PNG in the dataset root was the bogus
    base-model sweep artifact preview_flux_front.png (472 KB, passes every size
    gate), so the last-resort scan below promoted a wrong-identity render to the
    character's reference image — img2img base, InstantID face reference,
    identity-QC anchor and, downstream, delivered scene frames.  A generated
    preview is an OUTPUT of the identity, never evidence of it.
    """
    base = os.path.basename(str(path_or_name or '')).lower()
    return base.startswith('preview_') or base.startswith('style_preview')


def _char_contact_sheet_anchor(char_id: str) -> str | None:
    """Verified contact-sheet identity anchor face, when this char has one.

    Guarded per the 2026-07-31 shared contract — contact_sheet_pipeline is being
    changed in parallel, so every call is getattr/try-wrapped.
    """
    if not char_id:
        return None
    try:
        from zyg_workflows import contact_sheet_pipeline as _csp_ref
    except Exception:
        return None
    for _fn_name in ('identity_anchor_face_path', 'identity_profile_anchor_face_path'):
        try:
            _fn = getattr(_csp_ref, _fn_name, None)
            if not callable(_fn):
                continue
            p = _fn(char_id)
            if p and os.path.isfile(p) and os.path.getsize(p) >= 10_000:
                return p
        except Exception as _exc:
            _zyg_log.debug('reference image probe skipped: %s', _exc)
            continue
    return None


def _char_id_from_info(dataset_dir: str, info: dict | None = None) -> str:
    """char_id from a (possibly stub) info dict, else the dataset folder name."""
    info = info or {}
    for src in (
        info.get('char_id'),
        ((info.get('package') or {}) if isinstance(info.get('package'), dict) else {}).get('char_id'),
        (info.get('manifest') or {}).get('char_id') if isinstance(info.get('manifest'), dict) else None,
    ):
        if src:
            return str(src)
    try:
        return os.path.basename(os.path.normpath(dataset_dir or '')) or ''
    except Exception:
        return ''


def _iter_info_image_paths(info: dict | None) -> list[str]:
    """Tolerate every shape a caller may hand us for info['images'].

    2026-07-31: pipeline_storyteller.py currently passes the stub {'package': bible};
    a parallel agent is changing it to pass the manifest, whose 'images' is a list of
    path strings — but manifests elsewhere use dicts, so accept both.
    """
    out: list[str] = []
    info = info or {}
    _srcs = [info.get('images')]
    _man = info.get('manifest')
    if isinstance(_man, dict):
        _srcs.append(_man.get('images'))
    _pkg = info.get('package')
    if isinstance(_pkg, dict):
        _srcs.append((_pkg.get('manifest') or {}).get('images') if isinstance(_pkg.get('manifest'), dict) else None)
    for src in _srcs:
        if not isinstance(src, (list, tuple)):
            continue
        for item in src:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                for k in ('path', 'file', 'image', 'src', 'filename'):
                    if item.get(k):
                        out.append(str(item[k]))
                        break
    return out


def _pick_char_preview_reference(
    dataset_dir: str,
    info: dict,
    *,
    prefer_face: bool = False,
) -> str | None:
    """Best reference still from the character dataset for SDXL/FLUX preview conditioning."""
    info = info if isinstance(info, dict) else {}
    face_first = (
        'face_00_000deg.png',
        'face_00.png',
        'portrait_00_000deg.png',
        'portrait_00.png',
    )
    general = (
        'portrait_00_000deg.png',
        'portrait_00.png',
        'fullbody_00_000deg.png',
        'photo_000.jpg',
        'photo_000.png',
    )
    ordered_names = face_first + general if prefer_face else general + face_first
    _skip_previews = _preview_env_on('ZYG_PREVIEW_REF_SKIP_PREVIEWS')
    _char_id = _char_id_from_info(dataset_dir, info)

    if prefer_face:
        _pkg = info.get('package') or {}
        _cond = (_pkg.get('conditioning') or {}) if isinstance(_pkg, dict) else {}
        for p in _cond.get('ipadapter_reference_images') or []:
            if p and os.path.isfile(p) and 'face' in os.path.basename(p).lower():
                if _skip_previews and _is_generated_preview_name(p):
                    continue
                return p
        # Contact-sheet characters carry a VERIFIED anchor face — always beat a
        # loose dataset-root scan with it.
        _anchor = _char_contact_sheet_anchor(_char_id)
        if _anchor:
            return _anchor

    for name in ordered_names:
        cand = os.path.join(dataset_dir, name) if dataset_dir else ''
        if cand and os.path.isfile(cand):
            return cand

    for p in _iter_info_image_paths(info):
        if p and os.path.isfile(p):
            if _skip_previews and _is_generated_preview_name(p):
                continue
            if prefer_face and 'face' not in os.path.basename(p).lower():
                continue
            return p

    # Contact-sheet anchor beats the loose dataset-root scan for every slot.
    _anchor = _char_contact_sheet_anchor(_char_id)
    if _anchor:
        return _anchor

    if not dataset_dir or not os.path.isdir(dataset_dir):
        return None
    try:
        files = sorted(os.listdir(dataset_dir))
        if _skip_previews:
            # A generated preview is never ground truth — see _is_generated_preview_name.
            files = [f for f in files if not _is_generated_preview_name(f)]
        if prefer_face:
            for fn in files:
                if fn.lower().startswith('face_') and fn.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    return os.path.join(dataset_dir, fn)
        for fn in files:
            if fn.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                return os.path.join(dataset_dir, fn)
    except Exception as _exc:
        _zyg_log.debug('dataset listing failed, no reference image: %s', _exc)
    return None


def _char_is_blender_dataset(info: dict | None = None, job: dict | None = None) -> bool:
    """True when the character dataset came from Blender (not photo uploads)."""
    job = job or {}
    info = info or {}
    rm = str(job.get('render_mode') or info.get('render_mode') or '').strip().lower()
    if rm == 'blender':
        return True
    if rm == 'uploaded_photos':
        return False
    manifest = info.get('manifest') or {}
    src = str(manifest.get('source') or info.get('source') or '').lower()
    return 'blender' in src


def _pick_char_preview_reference_for_slot(
    dataset_dir: str,
    info: dict,
    slot_name: str,
) -> str | None:
    """Per-slot reference: face slot → face still; front → portrait/full body."""
    sn = (slot_name or '').lower()
    prefer_face = 'face' in sn
    return _pick_char_preview_reference(dataset_dir, info, prefer_face=prefer_face)


def _preview_backend_tier(backend: str) -> str:
    b = (backend or '').lower()
    if 'character_locked' in b:
        return 'locked'
    if 'instantid' in b:
        return 'instantid'
    if 'img2img' in b:
        return 'img2img'
    return 'other'


def _have_usable_char_preview(
    dataset_dir: str,
    model_family: str | None = None,
    params: dict | None = None,
    info: dict | None = None,
) -> bool:
    """True iff both preview PNGs exist for canonical or legacy names (≥10 KB each)."""
    if not dataset_dir or not os.path.isdir(dataset_dir):
        return False

    def _pair_ok(names: tuple[str, str]) -> bool:
        return all(
            os.path.isfile(os.path.join(dataset_dir, n)) and os.path.getsize(os.path.join(dataset_dir, n)) >= 10_000
            for n in names
        )

    if _pair_ok(_char_preview_png_names(model_family, params, info)):
        return True
    mf = _normalize_char_model_family(model_family, params, info)
    if mf == 'flux' and _char_photoreal_hybrid_preview(params, info):
        if _pair_ok(('preview_sdxl_front.png', 'preview_flux_face.png')):
            return True
    return _pair_ok(('preview_flux_front.png', 'preview_flux_face.png'))
