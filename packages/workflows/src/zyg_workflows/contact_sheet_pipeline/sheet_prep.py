# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Sheet pre-flight: identity anchor extraction, grid math, prompts, packages.

Moved verbatim out of the old single-file contact_sheet_pipeline.py (lines 1019-1276).
"""

from __future__ import annotations

import os
from typing import Callable

from zyg_workflows import paths

from zyg_workflows.contact_sheet_pipeline.constants import _DATASET_ROOT
from zyg_workflows.contact_sheet_pipeline.layout import trigger_token_for


def _extract_sheet_identity_anchor(
    native_sheet_path: str,
    dest_path: str,
    *,
    rows: int,
    cols: int,
    gutter: int,
    log_fn: Callable[[str], None] | None = None,
) -> str | None:
    """Extract the identity anchor from sheet A — face detection first.

    Geometric cell-[0,0] cropping assumed FLUX painted the grid where the
    arithmetic says; it doesn't (Rhea's anchor straddled two panels). Detect
    the largest face and crop around it; fall back to the geometric crop only
    when detection is unavailable.
    """
    if not os.path.isfile(native_sheet_path):
        return None
    try:
        from zyg_workflows import identity_qc_service as _idqc

        detected = _idqc.extract_anchor_face(
            native_sheet_path,
            dest_path,
            log_fn=log_fn,
        )
        if detected:
            return detected
    except Exception as _det_exc:
        if log_fn:
            log_fn(f'Anchor face detection unavailable ({_det_exc}) — geometric fallback')
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        img = Image.open(native_sheet_path).convert('RGB')
        sw, sh = img.size
        cw, ch = _grid_cell_size(sw, sh, rows, cols, gutter)
        x0 = gutter
        y0 = gutter
        x1 = min(x0 + cw, sw)
        y1 = min(y0 + ch, sh)
        crop = img.crop((x0, y0, x1, y1))
        os.makedirs(os.path.dirname(dest_path) or '.', exist_ok=True)
        crop.save(dest_path, format='PNG')
        if log_fn:
            log_fn(
                f'Identity anchor — sheet A front panel {crop.size[0]}×{crop.size[1]} → {os.path.basename(dest_path)}',
            )
        return dest_path
    except Exception as exc:
        if log_fn:
            log_fn(f'Identity anchor crop failed ({exc})')
        return None


def _grid_cell_size(sw: int, sh: int, rows: int, cols: int, gutter: int) -> tuple[int, int]:
    cw = max(64, (sw - (cols + 1) * gutter) // max(cols, 1))
    ch = max(64, (sh - (rows + 1) * gutter) // max(rows, 1))
    return cw, ch


def _build_grid_forcing_prompt(
    params: dict,
    pkg: dict,
    *,
    rows: int,
    cols: int,
    trigger: str,
    sheet_angles: list[str] | None = None,
    sheet_part: str = '',
) -> str:
    """One-shot contact-sheet prompt for single-canvas FLUX generation."""
    from zyg_workflows import comfy_generation_service as _cgs

    ident_block = _cgs.build_locked_prompt(
        'studio portrait',
        pkg,
        studio_preview=True,
    )
    style = caption_style_description((params or {}).get('style', 'photorealistic'))
    n_cells = rows * cols
    if sheet_angles:
        ordered = sheet_angles[:n_cells]
        while len(ordered) < n_cells:
            ordered.append(f'angle panel {len(ordered) + 1}')
        panel_list = '; '.join(f'panel {i + 1}: {a}' for i, a in enumerate(ordered))
        angle_summary = (
            f'each panel must show a DIFFERENT camera angle and head rotation — not duplicate front '
            f'poses — in this exact left-to-right top-to-bottom order: {panel_list}'
        )
        part_note = f' (contact sheet part {sheet_part.upper()})' if sheet_part else ''
        if sheet_part and sheet_part.lower() != 'a':
            angle_summary = (
                f'exact same person as part A, identical face identity, only change camera angle and '
                f'lighting per panel — {angle_summary}'
            )
    else:
        part_note = ''
        angle_summary = (
            'front view, three-quarter left and right, left and right profile, '
            'back of head showing hair, slight up and down angles, warm and cool studio lighting, '
            'medium shots and close-ups, natural smile on one panel'
        )
    grid_block = (
        f'A professional photography contact sheet{part_note} with exactly {rows} rows and {cols} columns '
        f'of clean studio portrait panels in a uniform grid with visible thin gutters between cells, '
        f'the exact same person in every panel, consistent face identity hair and outfit, '
        f'{angle_summary}, {style}, '
        f'no text labels, no watermarks, no merged overlapping panels, '
        f'no duplicate identical poses in every cell, '
        f'{trigger}'
    )
    # Identity prefix from bible + grid instructions (cap for CLIP/T5).
    if ident_block and ident_block not in grid_block:
        return f'{ident_block}, {grid_block}'[:1500]
    return grid_block[:1500]


def _upscale_sheet_comfy(
    src_path: str,
    dst_path: str,
    *,
    scale: int = 2,
    log_fn: Callable[[str], None] | None = None,
) -> str:
    """ESRGAN upscale via ComfyUI (RealESRGAN_x2 or x4)."""
    from zyg_workflows import _comfy_client as _cc

    scale = max(2, min(4, int(scale)))
    model = 'RealESRGAN_x2.pth' if scale <= 2 else 'RealESRGAN_x4plus.pth'
    staged = _cc.stage_input_image(src_path)
    wf = _cc.load_workflow('image_esrgan_upscale')
    overrides = {
        '10': {'image': staged},
        '11': {'model_name': model},
    }
    if log_fn:
        log_fn(f'Comfy ESRGAN {scale}x ({model}) → {os.path.basename(dst_path)}')
    outputs = _cc.submit(wf, overrides=overrides, timeout_s=600)
    if not outputs:
        raise RuntimeError('ESRGAN upscale produced no output')
    os.makedirs(os.path.dirname(dst_path) or '.', exist_ok=True)
    import shutil

    shutil.copy2(outputs[0], dst_path)
    return dst_path


def _upscale_sheet_pil(
    src_path: str,
    dst_path: str,
    *,
    scale: int = 2,
    log_fn: Callable[[str], None] | None = None,
) -> str:
    """Fallback LANCZOS upscale when Comfy ESRGAN is unavailable."""
    from PIL import Image

    scale = max(2, min(4, int(scale)))
    img = Image.open(src_path).convert('RGB')
    nw, nh = img.size[0] * scale, img.size[1] * scale
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    os.makedirs(os.path.dirname(dst_path) or '.', exist_ok=True)
    img.save(dst_path, format='PNG')
    if log_fn:
        log_fn(f'PIL fallback upscale {scale}x ({img.size[0]}×{img.size[1]}) → {dst_path}')
    return dst_path


def _comfy_availability() -> tuple[bool, str]:
    try:
        from zyg_workflows import comfy_generation_service as _cgs
    except ImportError:
        return False, 'comfy_generation_service not installed'
    if _cgs.is_available():
        return True, 'ok'
    if not _cgs.is_primary_backend():
        return False, 'set ZYG_COMFY_PRIMARY=1 (or ZYG_USE_COMFYUI=1) in .env'
    host = os.environ.get('ZYG_COMFY_HOST', paths.BIND_HOST)
    port = os.environ.get('ZYG_COMFY_PORT', '8188')
    return False, f'ComfyUI not reachable at {host}:{port}'


def _build_sheet_character_package(
    char_id: str,
    params: dict,
    model_family: str,
    log_fn: Callable[[str], None] | None = None,
) -> dict:
    """Bible package for locked Comfy prompts (no LoRA required)."""
    mf = (model_family or 'flux').strip().lower()
    if mf not in ('flux', 'sdxl', 'qwen', 'klein'):
        mf = 'flux'
    try:
        from zyg_workflows import character_bible_service as _cbs

        p = dict(params or {})
        p['model_family'] = mf
        p = _cbs.apply_auto_defaults(p, seed_key=char_id)
        p['name'] = _cbs.resolve_character_display_name(
            p.get('name'),
            p.get('gender', 'female'),
            p.get('eye_color'),
            seed_key=char_id,
        )
        info = {
            'char_id': char_id,
            'trigger_token': trigger_token_for(char_id),
            'dataset_dir': os.path.join(_DATASET_ROOT, char_id),
            'model_family': mf,
        }
        return _cbs.build_from_character_generate(char_id, p, info, log_fn=log_fn)
    except Exception as exc:
        if log_fn:
            log_fn(f'Contact sheet: bible build fallback ({exc})')
        p = params or {}
        return {
            'character_id': char_id,
            'trigger_token': trigger_token_for(char_id),
            'display_name': p.get('name') or char_id[:8],
            'identity': {
                'gender': p.get('gender', 'female'),
                'hair_color': p.get('hair_color', 'brown'),
                'eye_color': p.get('eye_color', 'brown'),
                'skin_tone': p.get('skin_tone', 'medium'),
            },
            'style_profile': {'render_style': p.get('style', 'photorealistic')},
            'conditioning': {},
        }


def caption_style_description(style: str) -> str:
    st = (style or 'photorealistic').strip().lower()
    if st in ('photorealistic', 'cinematic', 'realistic', 'photo'):
        # No 'cinematic lighting' / '8k portrait style' here: those tokens pull
        # FLUX toward its polished beauty-render cluster (waxy skin), and this
        # string is baked into every LoRA training caption.
        return 'photorealistic, film photography, natural skin texture, visible pores, unretouched, fine film grain'
    return 'high quality character illustration, clean linework, vibrant colors'


def _sdxl_per_cell_enabled() -> bool:
    """2026-07-26: SDXL characters get the FULL 48-angle per-cell contact sheet —
    photoreal FLUX+Qwen source tiles, which the SDXL/Arcane LoRA later restyles —
    instead of the legacy single 6-cell SDXL img2img sheet. The sheet is only a
    photoreal SOURCE (identity + angle coverage); the model_family stays 'sdxl'
    for QC and LoRA training, so forcing the FLUX source path is scoped to sheet
    generation only. Kill-switch: ZYG_CONTACT_SHEET_SDXL_PER_CELL=0 reverts every
    SDXL char to the fast 6-cell path (also used automatically as a fallback when
    the FLUX IP-Adapter / Qwen-edit capabilities are absent — see the dispatch)."""
    return os.environ.get(
        'ZYG_CONTACT_SHEET_SDXL_PER_CELL',
        '1',
    ).strip().lower() not in ('0', 'false', 'no', 'off')
