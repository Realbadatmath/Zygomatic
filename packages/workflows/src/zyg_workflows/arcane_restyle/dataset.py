# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.arcane_restyle.dataset — verbatim from arcane_restyle.py lines 748-996.

build_styled_sdxl_dataset — restyling a character's photoreal training
tiles into a styled SDXL dataset
"""

from __future__ import annotations

from typing import Callable
from zyg_workflows import animated_sdxl_dataset as _ads  # reuse identity-preservation helpers
import copy
import os
from zyg_workflows import paths
import shutil
import logging as _zyg_logging
from zyg_workflows.arcane_restyle import profiles as _zyg_profiles

# Bound by ASSIGNMENT, never by `from … import`: CPython 3.12 refuses the
# method-call optimisation for an import-bound global, so `NAME.attr(...)`
# inside the moved code would compile to different bytecode than it did in
# the single-file arcane_restyle.py.
_STYLE_NEG = _zyg_profiles._STYLE_NEG
_styled_caption = _zyg_profiles._styled_caption

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.arcane_restyle')


def build_styled_sdxl_dataset(
    char_id: str,
    photoreal_dir: str,
    *,
    style_cfg: dict,
    out_dir: str | None = None,
    log_fn: Callable[[str], None] | None = None,
    seed: int = 7788,
    force: bool = False,
    limit: int | None = None,
) -> str:
    """img2img every <photoreal_dir>/*.png (with matching .txt) through the
    style_cfg base checkpoint + style LoRA. Returns the styled dataset dir.

    style_cfg keys: base_checkpoint, lora, lora_scale, caption_clause,
                    denoise, cfg, steps.
    `limit` restyles only the first N tiles (for a quick preview).
    """

    def _log(m: str) -> None:
        (log_fn or print)(m)

    from zyg_workflows import _comfy_client as _comfy

    base_ckpt = style_cfg.get('base_checkpoint') or 'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors'
    lora_name = style_cfg.get('lora') or 'style_arcane.safetensors'
    lora_scale = float(style_cfg.get('lora_scale', 0.85))
    style_clause = style_cfg.get('caption_clause') or 'painterly semi-realistic 2D animation illustration'
    denoise = float(style_cfg.get('denoise', 0.5))
    cfg = float(style_cfg.get('cfg', 6.0))
    steps = int(style_cfg.get('steps', 30))
    # 2026-07-26: engine switch. 'qwen_edit' restyles via Qwen-Image-Edit — it EDITS
    # the tile (identity/age/costume/pose held by the reference-image conditioning, no
    # denoise re-synthesis) so it fixes the SDXL-img2img@0.65 drift (aged-up child,
    # doublet→armour, faceless tile→adult), and its LLM encoder takes the full arcane
    # instruction (no CLIP-77 truncation). 'sdxl_img2img' is the legacy fallback.
    engine = (style_cfg.get('engine') or 'sdxl_img2img').strip().lower()
    qwen_instruction = style_cfg.get('qwen_instruction') or ''
    train_clause = style_cfg.get('train_caption_clause') or 'arcane style, painterly 2D animation'
    qwen_steps = int(style_cfg.get('qwen_steps', 36))
    qwen_cfg = float(style_cfg.get('qwen_cfg', 4.0))
    qwen_mp_cap = float(style_cfg.get('qwen_mp_cap', 1.0))
    qwen_angles_scale = float(style_cfg.get('qwen_angles_lora_scale', 0.0))
    qwen_extra_neg = (style_cfg.get('qwen_extra_negatives') or '').strip()

    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(photoreal_dir.rstrip('/')), 'training_sdxl_animated')
    os.makedirs(out_dir, exist_ok=True)

    pngs = sorted(
        f
        for f in os.listdir(photoreal_dir)
        if f.lower().endswith('.png') and os.path.isfile(os.path.join(photoreal_dir, os.path.splitext(f)[0] + '.txt'))
    )
    if not pngs:
        raise RuntimeError(f'no captioned .png training images under {photoreal_dir}')
    if limit:
        pngs = pngs[: int(limit)]

    comfy_root = str(paths.ZYG_COMFY_ROOT)
    ckpt_dir = os.path.join(comfy_root, 'models', 'checkpoints')
    lora_dir = os.path.join(comfy_root, 'models', 'loras')
    qwen_unet = ''
    if engine == 'qwen_edit':
        from zyg_workflows import comfy_generation_service as _cgs_q

        qwen_unet = (style_cfg.get('qwen_unet') or '').strip() or (_cgs_q.qwen_edit_unet() or '')
        if not qwen_unet or not os.path.isfile(os.path.join(comfy_root, 'models', 'diffusion_models', qwen_unet)):
            raise RuntimeError(f'Qwen-Image-Edit UNet not found in models/diffusion_models ({qwen_unet or "none"})')
    else:
        if not os.path.isfile(os.path.join(ckpt_dir, base_ckpt)):
            raise RuntimeError(f'style base checkpoint missing: {os.path.join(ckpt_dir, base_ckpt)}')
        if not os.path.isfile(os.path.join(lora_dir, lora_name)):
            raise RuntimeError(f'style LoRA missing: {os.path.join(lora_dir, lora_name)}')

    base_wf = _comfy.load_workflow('qwen_edit_angle' if engine == 'qwen_edit' else 'sdxl_img2img_lora')
    _ident = _ads._identity_clause(char_id)
    _id_neg = _ads._identity_negatives(char_id)
    _neg = f'{_STYLE_NEG}, {_id_neg}' if _id_neg else _STYLE_NEG
    # Profile-supplied extra negatives (Qwen path): block the embellishments/style-drift
    # Qwen invents on hard angles — gold trim, epaulettes, stand-up collars, anime line-art,
    # photo look, and age-up — none of which the SDXL _STYLE_NEG covers.
    if engine == 'qwen_edit' and qwen_extra_neg:
        _neg = f'{_neg}, {qwen_extra_neg}'
    _clothing = ''
    try:
        from zyg_workflows import character_bible_service as _cbs_id

        _pkg_id = _cbs_id.load(char_id) or {}
        _bi = _pkg_id.get('identity') or {}
        _ident_skin = (
            f'{_bi.get("skin_tone")} brown'
            if _bi.get('skin_tone') in ('medium', 'tan', 'olive')
            else (_bi.get('skin_tone') or '')
        )
        _ident_hair = ' '.join(x for x in (_bi.get('hair_texture'), _bi.get('hair_style')) if x)
        _clothing = (
            (_pkg_id.get('default_presentation') or {}).get('default_clothing')
            or (_pkg_id.get('style_profile') or {}).get('default_clothing')
            or ''
        )
    except Exception:
        _ident_skin, _ident_hair = '', ''

    # Feed Qwen the ACTUAL costume (positive anchor) so the arcane restyle can't
    # invent armour/gold-trim/stand-up collars — but describe ONLY the UPPER-BODY
    # garment (doublet + collar). Naming the lower garments (breeches/stockings/shoes)
    # made Qwen zoom OUT to full-body to show them, losing the head-and-shoulders crop;
    # the reference image still carries the full outfit on genuinely full-body tiles.
    _subject = _ident
    if _clothing:
        import re as _re_cloth

        _lower_kw = _re_cloth.compile(r'breech|trouser|stocking|shoe|boot|\bpant|hose|legging', _re_cloth.I)
        _upper_parts = [p.strip() for p in _re_cloth.split(r'[,;]', _clothing) if p.strip() and not _lower_kw.search(p)]
        _upper_cloth = ', '.join(_upper_parts) if _upper_parts else _clothing
        _subject = (
            f'{_ident}, dressed in this exact unchanged clothing (keep it identical, do not add '
            f'trim or turn it into armour): {_upper_cloth}'
            if _ident
            else f'dressed in: {_upper_cloth}'
        )
    # Age-lock (Qwen path): the restyle repeatedly aged children up (adult jaw, longer
    # face/neck) on 3/4 and profile angles. Derive the apparent age from the identity
    # clause and, for a child, inject a strong keep-them-a-child clause. Character-derived
    # (not hard-coded) so an adult character using this same profile is unaffected.
    _age_lock = ''
    if engine == 'qwen_edit':
        import re as _re_age

        _m_age = _re_age.search(r'(\d{1,2})\s*year', _ident or '')
        if _m_age and int(_m_age.group(1)) < 16:
            _age_lock = (
                ' Keep the subject a young child with a soft, round, childish face and childlike '
                'body proportions — absolutely do not give the child an adult or teenage jaw and '
                'do not lengthen the face or neck.'
            )
    qwen_prompt = (
        f'{qwen_instruction}{_age_lock} The subject is {_subject}.'
        if (_subject and qwen_instruction)
        else f'{qwen_instruction}{_age_lock}'
    )
    if engine == 'qwen_edit':
        _log(
            f'[styled-dataset] {char_id}: Qwen-Edit restyling {len(pngs)} tiles '
            f'({qwen_unet}, steps {qwen_steps}, cfg {qwen_cfg}); identity="{_ident}"'
        )
    else:
        _log(
            f'[styled-dataset] {char_id}: restyling {len(pngs)} tiles → "{style_clause[:40]}…" '
            f'({base_ckpt} + {lora_name}@{lora_scale}, denoise {denoise}); identity="{_ident}"'
        )
    made = 0
    for i, png in enumerate(pngs):
        stem = os.path.splitext(png)[0]
        out_png = os.path.join(out_dir, png)
        out_txt = os.path.join(out_dir, stem + '.txt')
        cap = ''
        try:
            with open(os.path.join(photoreal_dir, stem + '.txt'), encoding='utf-8') as fh:
                cap = fh.read().strip()
        except OSError as _exc:
            _zyg_log.debug('source caption unreadable for %s: %s', stem, _exc)
        styled_cap = _styled_caption(cap, _ident, train_clause if engine == 'qwen_edit' else style_clause)
        with open(out_txt, 'w', encoding='utf-8') as fh:
            fh.write(styled_cap)
        if os.path.isfile(out_png) and not force:
            made += 1
            continue
        g = copy.deepcopy(base_wf)
        src_full = os.path.join(photoreal_dir, png)
        src_name = _comfy.stage_input_image(src_full)
        if engine == 'qwen_edit':
            # Qwen-Image-Edit graph (qwen_edit_angle.json): node 15 = source image
            # (reference conditioning that holds identity/age/costume/pose), node 14 =
            # camera-angle LoRA (zeroed — restyle in place, not rotate), node 20 = the
            # natural-language arcane instruction (LLM encoder, no CLIP-77 limit),
            # node 30 = output size (set here to ~qwen_mp_cap MP, /16-aligned, source
            # aspect — the service's 1MP cap never runs on this direct _comfy path).
            import math

            try:
                from PIL import Image as _PILImage

                with _PILImage.open(src_full) as _im:
                    _ow, _oh = _im.size
            except Exception:
                _ow, _oh = 960, 1072
            _budget = qwen_mp_cap * 1024 * 1024
            if _ow * _oh > _budget:
                _s = math.sqrt(_budget / float(_ow * _oh))
                _ow, _oh = int(_ow * _s), int(_oh * _s)
            g['10']['inputs']['unet_name'] = qwen_unet
            g['14']['inputs']['strength_model'] = qwen_angles_scale
            g['15']['inputs']['image'] = src_name
            g['20']['inputs']['prompt'] = qwen_prompt  # NOTE: key is 'prompt', not 'text'
            g['21']['inputs']['prompt'] = _neg
            g['30']['inputs']['width'] = max(256, (_ow // 16) * 16)
            g['30']['inputs']['height'] = max(256, (_oh // 16) * 16)
            g['31']['inputs'].update({'seed': seed + i, 'steps': qwen_steps, 'cfg': qwen_cfg, 'denoise': 1.0})
        else:
            g['10']['inputs']['ckpt_name'] = base_ckpt
            g['11']['inputs']['lora_name'] = lora_name
            g['11']['inputs']['strength_model'] = lora_scale
            g['11']['inputs']['strength_clip'] = lora_scale
            g['14']['inputs']['image'] = src_name
            g['20']['inputs']['text'] = styled_cap
            g['21']['inputs']['text'] = _neg
            g['31']['inputs'].update({'seed': seed + i, 'denoise': denoise, 'cfg': cfg, 'steps': steps})
        g['50']['inputs']['filename_prefix'] = f'ZygStyled_{char_id[:8]}_{stem}'
        try:
            outs = _comfy.submit(g, timeout_s=(600 if engine == 'qwen_edit' else 300))
        except Exception as exc:
            _log(f'[styled-dataset] tile {png} FAILED: {exc!r}')
            continue
        if outs and os.path.isfile(outs[0]):
            # reuse the per-tile identity screen (retry once lower-denoise, then drop)
            if not _ads._tile_identity_ok(outs[0], _ident_skin, _ident_hair, _log):
                g2 = copy.deepcopy(g)
                g2['31']['inputs']['seed'] = seed + i + 5000
                if engine != 'qwen_edit':
                    g2['31']['inputs']['denoise'] = max(0.38, denoise - 0.12)
                try:
                    outs2 = _comfy.submit(g2, timeout_s=(600 if engine == 'qwen_edit' else 300))
                except Exception:
                    outs2 = None
                if (
                    outs2
                    and os.path.isfile(outs2[0])
                    and _ads._tile_identity_ok(outs2[0], _ident_skin, _ident_hair, _log)
                ):
                    outs = outs2
                else:
                    try:
                        os.remove(out_txt)
                    except OSError as _exc:
                        _zyg_log.debug('dropped tile caption cleanup skipped: %s', _exc)
                    _log(f'[styled-dataset] tile {png} dropped (identity screen)')
                    continue
            shutil.copy2(outs[0], out_png)
            made += 1
            if (i + 1) % 3 == 0 or i + 1 == len(pngs):
                _log(f'[styled-dataset] {made}/{len(pngs)} tiles done')
    if not limit and made < max(4, len(pngs) // 2):
        raise RuntimeError(f'styled dataset too small: {made}/{len(pngs)} tiles produced')
    _log(f'[styled-dataset] {char_id}: {made}/{len(pngs)} styled tiles → {out_dir}')
    return out_dir
