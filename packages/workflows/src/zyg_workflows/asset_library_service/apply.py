# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.asset_library_service.apply — verbatim from asset_library_service.py lines 835-1025.

applying a library asset to a character render: the base-image lookup,
the per-anchor edit instruction, the presence-QC gate and apply_asset
"""

import copy
import json
import math
import os
from zyg_workflows import paths
import logging as _zyg_logging
from zyg_workflows.asset_library_service import catalog as _zyg_catalog
from zyg_workflows.asset_library_service import assets as _zyg_assets

# Bound by ASSIGNMENT, never by `from … import`: CPython 3.12 refuses the
# method-call optimisation for an import-bound global, so `NAME.attr(...)`
# inside the moved code would compile to different bytecode than it did in
# the single-file asset_library_service.py.
_CATEGORIES = _zyg_catalog._CATEGORIES
_CHARS_ROOT = _zyg_catalog._CHARS_ROOT
_log_noop = _zyg_catalog._log_noop
get_asset = _zyg_assets.get_asset

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.asset_library_service')


def _char_base_image(char_id):
    d = os.path.join(_CHARS_ROOT, char_id)
    for cand in (
        os.path.join(d, 'arcane_instantid', 'cell_00.png'),
        os.path.join(d, 'contact_sheet', 'cells', 'cell_00.png'),
    ):
        if os.path.isfile(cand):
            return cand
    return None


# Apply instructions per anchor. Grip wording follows the prop research: name the hand,
# demand wrapped fingers, and forbid extra hands — never leave the grip implicit.
def _apply_instruction(rec, target_desc=None):
    """target_desc disambiguates WHO gets the asset in multi-person images (2026-07-29
    ownership bug: 'the person's right hand' put the father's pipe in the son's hand).
    E.g. 'the older bearded man on the left'."""
    clause = rec.get('prompt_clause') or rec.get('name') or ''
    anchor = rec.get('anchor') or 'held-in-hand'
    who = target_desc or 'the person'
    if anchor == 'on-table':
        return (
            f'Add {clause} on the table or surface in front of {who}. '
            f'Keep the person — face, hairstyle, body, pose, clothing — and the background and '
            f'art style completely unchanged. Only add the object to the scene.'
        )
    if anchor == 'in-scene':
        return (
            f'Add {clause} to the room beside the person, standing naturally on the floor at a '
            f'realistic scale and perspective. Keep the person — face, hairstyle, body, pose, '
            f'clothing — and the rest of the background and the art style completely unchanged. '
            f'Only add the piece of furniture to the scene.'
        )
    if anchor == 'scene':
        return (
            f'Change the background and setting of the image to {clause}. '
            f'Keep the person — face, hairstyle, body, pose, clothing and art style — completely '
            f'unchanged and identical; replace ONLY the background and environment.'
        )
    return (
        f'Place {clause}, at a realistic small scale, in the right hand of {who}, held '
        f'naturally with the fingers wrapped around it in a realistic grip. Keep every '
        f"person's face, hairstyle, body, pose and clothing, the background and the art "
        f'style completely unchanged; every other person keeps exactly what they were '
        f'holding and doing. Each person must still have exactly two hands with five '
        f'fingers each. Only add the object and adjust that one hand of {who}.'
    )


def _presence_qc(base_path, out_path, anchor):
    """Objective gate for the 'asset silently missing' regression. A qwen denoise-1.0
    re-synthesis NEVER returns a byte-near copy — the whole-frame MAD noise floor is ~9-11
    (measured 2026-07-29 on wardrobe outputs from the same graph) — so absolute full-frame
    thresholds can't work. Instead compare the SHAPE of the change on a 16x16 cell grid:
      - held/on-table: a real added object is a LOCALIZED outlier → max-cell must exceed the
        median cell (the uniform re-synthesis noise) by a wide margin.
      - scene: a real background swap lifts almost every cell → the median itself must sit
        far above the noise floor."""
    try:
        from PIL import Image
        import numpy as np

        a = np.asarray(Image.open(base_path).convert('RGB').resize((256, 256)), dtype=float)
        b = np.asarray(Image.open(out_path).convert('RGB').resize((256, 256)), dtype=float)
        d = np.abs(a - b).mean(axis=2)  # 256x256 per-pixel MAD
        cells = d.reshape(16, 16, 16, 16).mean(axis=(1, 3))  # 16x16 per-cell MAD
        med = float(np.median(cells))
        mx = float(cells.max())
        margin = mx - med
        if anchor == 'scene':
            present = med >= 18.0
            note = (
                ''
                if present
                else (
                    f'whole-frame change (median {med:.1f}) is at the '
                    f're-synthesis noise floor — background swap likely missing'
                )
            )
            return {
                'delta': round(med, 2),
                'margin': round(margin, 2),
                'threshold': 18.0,
                'present': present,
                'note': note,
            }
        present = margin >= 10.0
        note = (
            ''
            if present
            else (f'no localized change (max-cell {mx:.1f} vs median {med:.1f}) — asset likely missing from the render')
        )
        return {'delta': round(med, 2), 'margin': round(margin, 2), 'threshold': 10.0, 'present': present, 'note': note}
    except Exception as e:
        return {'delta': None, 'margin': None, 'present': None, 'note': f'qc failed: {e}'}


def apply_asset(cat, asset_id, char_id, out_path, base_image=None, seed=42, target_desc=None, log_fn=None):
    """Apply a library asset to a character's render via Qwen-Image-Edit. Returns
    (out_path|None, qc_dict). The qc dict carries the presence-gate verdict."""
    log = log_fn or _log_noop
    info = _CATEGORIES.get(cat)
    if not info or info['kind'] != 'visual':
        log(f'[assetlib] category "{cat}" is not applyable')
        return None, {}
    rec = get_asset(cat, asset_id)
    if not rec:
        log(f'[assetlib] unknown asset {cat}/{asset_id}')
        return None, {}
    base = base_image or _char_base_image(char_id)
    if not (base and os.path.isfile(base)):
        log(f'[assetlib] no base image for {char_id}')
        return None, {}
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    comfy_root = str(paths.ZYG_COMFY_ROOT)
    try:
        from zyg_workflows import comfy_generation_service as _cgs

        qwen_unet = _cgs.qwen_edit_unet() or ''
    except Exception:
        qwen_unet = ''
    if not qwen_unet or not os.path.isfile(os.path.join(comfy_root, 'models', 'diffusion_models', qwen_unet)):
        log('[assetlib] qwen unet not found — cannot apply asset')
        return None, {}

    instr = _apply_instruction(rec, target_desc=target_desc)
    neg = 'deformed, extra limbs, extra hand, third hand, extra fingers, changed face, different person, blurry, watermark, text'
    if rec.get('negative'):
        neg = f'{rec["negative"]}, {neg}'

    try:
        from PIL import Image

        with Image.open(base) as im:
            ow, oh = im.size
    except Exception as e:
        log(f'[assetlib] cannot read base ({e})')
        return None, {}
    w, h = ow, oh
    budget = 1.0 * 1024 * 1024
    if w * h > budget:
        s = math.sqrt(budget / float(w * h))
        w, h = int(w * s), int(h * s)
    try:
        from zyg_workflows import _comfy_client as _comfy

        g = copy.deepcopy(_comfy.load_workflow('qwen_edit_angle'))
        src_name = _comfy.stage_input_image(base)
    except Exception as e:
        log(f'[assetlib] stage/load failed ({e})')
        return None, {}
    g['10']['inputs']['unet_name'] = qwen_unet
    g['14']['inputs']['strength_model'] = 0.0
    g['15']['inputs']['image'] = src_name
    g['20']['inputs']['prompt'] = instr
    g['21']['inputs']['prompt'] = neg
    g['30']['inputs']['width'] = max(256, (w // 16) * 16)
    g['30']['inputs']['height'] = max(256, (h // 16) * 16)
    g['31']['inputs'].update({'seed': int(seed), 'steps': 32, 'cfg': 3.0, 'denoise': 1.0})
    g['50']['inputs']['filename_prefix'] = f'ZygAssetApply_{cat}'
    try:
        outs = _comfy.submit(g, timeout_s=600)
    except Exception as e:
        log(f'[assetlib] qwen submit failed ({e})')
        return None, {}
    if not (outs and os.path.isfile(outs[0])):
        log('[assetlib] qwen produced no output')
        return None, {}
    try:
        from PIL import Image as _I

        res = _I.open(outs[0]).convert('RGB')
        if res.size != (ow, oh):
            res = res.resize((ow, oh), _I.LANCZOS)
        res.save(out_path)
    except Exception as e:
        log(f'[assetlib] save failed ({e})')
        return None, {}
    qc = _presence_qc(base, out_path, rec.get('anchor') or 'held-in-hand')
    try:
        with open(os.path.splitext(out_path)[0] + '.qc.json', 'w', encoding='utf-8') as f:
            json.dump({'category': cat, 'asset_id': asset_id, 'char_id': char_id, 'qc': qc}, f, indent=2)
    except OSError as _exc:
        _zyg_log.warning('QC sidecar write failed, the applied asset has no qc.json: %s', _exc)
    log(
        f'[assetlib] {cat}/{asset_id} applied → {os.path.basename(out_path)} '
        f'(qc delta={qc.get("delta")} present={qc.get("present")})'
    )
    return out_path, qc
