# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.arcane_restyle.qwen — verbatim from arcane_restyle.py lines 618-747.

qwen_restyle_image — single-image arcane restyle via Qwen-Image-Edit
"""

from __future__ import annotations

from zyg_workflows import animated_sdxl_dataset as _ads  # reuse identity-preservation helpers
from zyg_workflows import paths
import logging as _zyg_logging
from zyg_workflows.arcane_restyle import profiles as _zyg_profiles

# Bound by ASSIGNMENT, never by `from … import`: CPython 3.12 refuses the
# method-call optimisation for an import-bound global, so `NAME.attr(...)`
# inside the moved code would compile to different bytecode than it did in
# the single-file arcane_restyle.py.
_STYLE_NEG = _zyg_profiles._STYLE_NEG

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.arcane_restyle')


def qwen_restyle_image(char_id, style_cfg, src_path, dst_path=None, seed=42, log_fn=None):
    """Render-time Arcane restyle of a SINGLE already-rendered image via Qwen-Image-Edit.

    The Arcane style CANNOT be baked into an SDXL character LoRA (it renders photoreal at
    any scale; a style LoRA imposes the look but ages the subject up). So the render path
    renders photoreal (good identity) and calls this to restyle the saved frame to Arcane:
    Qwen-Edit samples an EMPTY latent at denoise 1.0 with the source as CONDITIONING, so
    identity/age/pose/costume are PRESERVED while only the render style changes (the exact
    technique that produced the 25 training tiles). Overwrites src_path when dst_path is
    None; the output is resized back to the ORIGINAL render dimensions so episode frames
    keep their exact size. Returns True on success, False (no-op) on any problem.
    """
    import os as _os

    _log = log_fn or (lambda m: None)
    dst_path = dst_path or src_path
    if (style_cfg.get('engine') or '').strip().lower() != 'qwen_edit':
        return False
    instr = style_cfg.get('qwen_instruction') or ''
    extra_neg = (style_cfg.get('qwen_extra_negatives') or '').strip()
    steps = int(style_cfg.get('qwen_steps', 36))
    cfg = float(style_cfg.get('qwen_cfg', 3.0))
    mp_cap = float(style_cfg.get('qwen_mp_cap', 1.0))
    angles_scale = float(style_cfg.get('qwen_angles_lora_scale', 0.0))
    comfy_root = str(paths.ZYG_COMFY_ROOT)
    try:
        from zyg_workflows import comfy_generation_service as _cgs_q

        qwen_unet = (style_cfg.get('qwen_unet') or '').strip() or (_cgs_q.qwen_edit_unet() or '')
    except Exception:
        qwen_unet = (style_cfg.get('qwen_unet') or '').strip()
    if not qwen_unet or not _os.path.isfile(_os.path.join(comfy_root, 'models', 'diffusion_models', qwen_unet)):
        _log(f'[render-restyle] qwen unet not found ({qwen_unet or "none"}) — skip')
        return False
    # identity / clothing / negatives / age-lock — identical to build_styled_sdxl_dataset
    _ident = _ads._identity_clause(char_id)
    _id_neg = _ads._identity_negatives(char_id)
    _neg = f'{_STYLE_NEG}, {_id_neg}' if _id_neg else _STYLE_NEG
    if extra_neg:
        _neg = f'{_neg}, {extra_neg}'
    _clothing = ''
    try:
        from zyg_workflows import character_bible_service as _cbs_id

        _pkg = _cbs_id.load(char_id) or {}
        _clothing = (
            (_pkg.get('default_presentation') or {}).get('default_clothing')
            or (_pkg.get('style_profile') or {}).get('default_clothing')
            or ''
        )
    except Exception as _exc:
        _zyg_log.warning('default clothing lookup failed, continuing without it: %s', _exc)
    _subject = _ident
    if _clothing:
        import re as _re_c

        _lk = _re_c.compile(r'breech|trouser|stocking|shoe|boot|\bpant|hose|legging', _re_c.I)
        _up = [p.strip() for p in _re_c.split(r'[,;]', _clothing) if p.strip() and not _lk.search(p)]
        _upper = ', '.join(_up) if _up else _clothing
        _subject = (
            f'{_ident}, dressed in this exact unchanged clothing (keep it identical, do not add '
            f'trim or turn it into armour): {_upper}'
            if _ident
            else f'dressed in: {_upper}'
        )
    _age_lock = ''
    import re as _re_a

    _ma = _re_a.search(r'(\d{1,2})\s*year', _ident or '')
    if _ma and int(_ma.group(1)) < 16:
        _age_lock = (
            ' Keep the subject a young child with a soft, round, childish face and childlike '
            'body proportions — absolutely do not give the child an adult or teenage jaw and '
            'do not lengthen the face or neck.'
        )
    qwen_prompt = f'{instr}{_age_lock} The subject is {_subject}.' if (_subject and instr) else f'{instr}{_age_lock}'
    try:
        from PIL import Image as _PImg

        with _PImg.open(src_path) as _im:
            _ow0, _oh0 = _im.size
    except Exception as _oe:
        _log(f'[render-restyle] cannot read {src_path} ({_oe}) — skip')
        return False
    import copy as _copy
    import math as _math
    from zyg_workflows import _comfy_client as _comfy

    _ow, _oh = _ow0, _oh0
    _budget = mp_cap * 1024 * 1024
    if _ow * _oh > _budget:
        _s = _math.sqrt(_budget / float(_ow * _oh))
        _ow, _oh = int(_ow * _s), int(_oh * _s)
    try:
        g = _copy.deepcopy(_comfy.load_workflow('qwen_edit_angle'))
        src_name = _comfy.stage_input_image(src_path)
    except Exception as _se:
        _log(f'[render-restyle] stage/load failed ({_se}) — skip')
        return False
    g['10']['inputs']['unet_name'] = qwen_unet
    g['14']['inputs']['strength_model'] = angles_scale
    g['15']['inputs']['image'] = src_name
    g['20']['inputs']['prompt'] = qwen_prompt
    g['21']['inputs']['prompt'] = _neg
    g['30']['inputs']['width'] = max(256, (_ow // 16) * 16)
    g['30']['inputs']['height'] = max(256, (_oh // 16) * 16)
    g['31']['inputs'].update({'seed': int(seed), 'steps': steps, 'cfg': cfg, 'denoise': 1.0})
    g['50']['inputs']['filename_prefix'] = f'ZygRestyle_{char_id[:8]}'
    try:
        outs = _comfy.submit(g, timeout_s=600)
    except Exception as _sub_e:
        _log(f'[render-restyle] submit failed ({_sub_e})')
        return False
    if not (outs and _os.path.isfile(outs[0])):
        _log('[render-restyle] no output — skip')
        return False
    try:
        from PIL import Image as _PImg2

        _res = _PImg2.open(outs[0]).convert('RGB')
        if _res.size != (_ow0, _oh0):  # restore exact render dimensions
            _res = _res.resize((_ow0, _oh0), _PImg2.LANCZOS)
        _res.save(dst_path)
    except Exception as _we:
        _log(f'[render-restyle] save failed ({_we}) — skip')
        return False
    _log(f'[render-restyle] {char_id}: Arcane-restyled {_os.path.basename(dst_path)}')
    return True
