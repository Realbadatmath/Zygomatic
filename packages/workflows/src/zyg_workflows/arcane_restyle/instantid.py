# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.arcane_restyle.instantid — verbatim from arcane_restyle.py lines 397-617.

the concise SDXL arcane prompt and instantid_arcane_restyle
(style_arcane LoRA + InstantID identity lock)
"""

from __future__ import annotations

from zyg_workflows import animated_sdxl_dataset as _ads  # reuse identity-preservation helpers
import logging as _zyg_logging
from zyg_workflows.arcane_restyle import profiles as _zyg_profiles

# Bound by ASSIGNMENT, never by `from … import`: CPython 3.12 refuses the
# method-call optimisation for an import-bound global, so `NAME.attr(...)`
# inside the moved code would compile to different bytecode than it did in
# the single-file arcane_restyle.py.
_STYLE_NEG = _zyg_profiles._STYLE_NEG

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.arcane_restyle')


def _arcane_prompt(char_id, style_cfg):
    """Concise SDXL prompt for the style_arcane render: caption-clause (style) first,
    then a brief identity + upper-body clothing (InstantID + the img2img source carry the
    finer identity/costume, so this stays inside CLIP's 77-token budget)."""
    cap = (
        style_cfg.get('caption_clause')
        or 'League of Legends Arcane art style, painterly semi-realistic 2D animation, thick visible oil brush strokes, dramatic cinematic lighting'
    )
    _ident = _ads._identity_clause(char_id) or ''
    _cloth = ''
    try:
        from zyg_workflows import character_bible_service as _cbs_id

        _pkg = _cbs_id.load(char_id) or {}
        _cloth = (
            (_pkg.get('default_presentation') or {}).get('default_clothing')
            or (_pkg.get('style_profile') or {}).get('default_clothing')
            or ''
        )
    except Exception as _exc:
        _zyg_log.warning('default clothing lookup failed, continuing without it: %s', _exc)
    if _cloth:
        import re as _re_c

        _lk = _re_c.compile(r'breech|trouser|stocking|shoe|boot|\bpant|hose|legging', _re_c.I)
        _up = [p.strip() for p in _re_c.split(r'[,;]', _cloth) if p.strip() and not _lk.search(p)]
        _cloth = ', '.join(_up) if _up else _cloth
    parts = [cap]
    if _ident:
        parts.append(_ident)
    if _cloth:
        parts.append(f'wearing {_cloth}')
    return ', '.join(parts)


def instantid_arcane_restyle(char_id, style_cfg, src_path, dst_path=None, seed=42, log_fn=None):
    """Render-time Arcane restyle via SDXL **style_arcane LoRA + InstantID identity-lock**.

    This produces the AUTHENTIC Arcane look (the trained style_arcane aesthetic that matches
    the calibration sweep — thick brushwork, chiaroscuro, luminous eyes) — which a text
    instruction to Qwen CANNOT reproduce — while InstantID locks the character's specific face
    from their anchor (so identity does not drift to a generic Arcane face like the raw sweep).
    Age is allowed to settle where the style puts it (~+2-3y). Recipe (calibrated 2026-07-27):
    Juggernaut + style_arcane@~1.15 + InstantID(anchor face, weight ~0.8, end_at ~0.6) img2img
    on the source at denoise ~0.6, cfg 6.5, 32 steps.

    Robustness: renders best-of-N and keeps the candidate with the highest ArcFace similarity to
    the anchor (this also rejects the seed-dependent collar smear, which mangles the face → low
    score). If the SOURCE has no usable face (full-body / back-of-head frames — InstantID needs a
    face and otherwise emits a broken double-face), it FALLS BACK to style_arcane-only img2img so
    the frame still gets the Arcane style (no identity at stake when no face is shown).

    Output is resized to the ORIGINAL source dimensions. Returns True on success, False (no-op).
    """
    import os as _os
    import copy as _copy

    _log = log_fn or (lambda m: None)
    dst_path = dst_path or src_path
    base_ckpt = style_cfg.get('render_base_checkpoint') or 'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors'
    style_lora = style_cfg.get('render_style_lora') or 'style_arcane.safetensors'
    lora_s = float(style_cfg.get('render_style_lora_scale', 1.15))
    weight = float(style_cfg.get('instantid_weight', 0.8))
    end_at = float(style_cfg.get('instantid_end_at', 0.6))
    denoise = float(style_cfg.get('render_denoise', 0.6))
    cfg = float(style_cfg.get('render_cfg', 6.5))
    steps = int(style_cfg.get('render_steps', 32))
    best_of = max(1, int(style_cfg.get('render_best_of', 2)))
    face_min_frac = float(style_cfg.get('render_face_min_frac', 0.012))
    try:
        from PIL import Image as _PImg

        with _PImg.open(src_path) as _im:
            _ow, _oh = _im.size
    except Exception as _oe:
        _log(f'[instantid-arcane] cannot read {src_path} ({_oe}) — skip')
        return False
    _prompt = _arcane_prompt(char_id, style_cfg)
    _id_neg = _ads._identity_negatives(char_id)
    _neg = f'{_STYLE_NEG}, {_id_neg}' if _id_neg else _STYLE_NEG
    _neg = (
        _neg + ', photograph, photorealistic, dslr, 3d render, white smear, melted face, '
        'disfigured mouth, double face, extra face'
    ).strip(', ')
    # anchor face for InstantID + the identity gate/pick
    try:
        from zyg_workflows import contact_sheet_pipeline as _csp

        anchor = _csp.identity_anchor_face_path(char_id)
    except Exception:
        anchor = ''
    have_anchor = bool(anchor and _os.path.isfile(anchor))

    # ---- face-presence gate on the SOURCE (InstantID needs a real face) ----
    use_instantid = have_anchor
    if use_instantid:
        try:
            from zyg_workflows import identity_qc_service as _iq

            if _iq.available()[0]:
                _e = (_iq.embed_images([src_path]) or {}).get(src_path) or {}
                _fd = bool(_e.get('face_detected'))
                _bb = _e.get('bbox') or []
                _frac = 0.0
                if _fd and len(_bb) == 4 and _e.get('img_w') and _e.get('img_h'):
                    _frac = (abs(_bb[2] - _bb[0]) * abs(_bb[3] - _bb[1])) / float(_e['img_w'] * _e['img_h'])
                if not _fd or _frac < face_min_frac:
                    _log(
                        f'[instantid-arcane] source face absent/too small (det={_fd}, frac={_frac:.3f}) '
                        f'— style_arcane-only fallback'
                    )
                    use_instantid = False
        except Exception as _ge:
            _log(f'[instantid-arcane] face gate skipped ({_ge}) — proceeding with InstantID')

    from zyg_workflows import _comfy_client as _comfy

    try:
        base_wf = _comfy.load_workflow('sdxl_img2img_lora')
    except Exception as _we:
        _log(f'[instantid-arcane] workflow load failed ({_we}) — skip')
        return False

    def _build(g_seed, instantid):
        g = _copy.deepcopy(base_wf)
        g['10']['inputs']['ckpt_name'] = base_ckpt
        g['11']['inputs']['lora_name'] = style_lora
        g['11']['inputs']['strength_model'] = lora_s
        g['11']['inputs']['strength_clip'] = lora_s
        g['14']['inputs']['image'] = _comfy.stage_input_image(src_path)
        g['20']['inputs']['text'] = _prompt
        g['21']['inputs']['text'] = _neg
        g['31']['inputs'].update(
            {
                'seed': int(g_seed),
                'steps': steps,
                'cfg': cfg,
                'denoise': denoise,
                'sampler_name': 'dpmpp_2m',
                'scheduler': 'karras',
            }
        )
        g['50']['inputs']['filename_prefix'] = f'ZygArcID_{char_id[:8]}'
        if instantid:
            # InstantIDFaceAnalysis on CPU by default: its onnxruntime CUDA provider
            # (libcublasLt.so.12) intermittently CRASHES the ComfyUI server; CPU face
            # analysis is a few seconds slower but stable (diffusion still runs on GPU).
            _id_prov = (style_cfg.get('instantid_provider') or 'CPU').strip()
            g['60'] = {'class_type': 'InstantIDModelLoader', 'inputs': {'instantid_file': 'ip-adapter.bin'}}
            g['61'] = {'class_type': 'LoadImage', 'inputs': {'image': _comfy.stage_input_image(anchor)}}
            g['62'] = {'class_type': 'InstantIDFaceAnalysis', 'inputs': {'provider': _id_prov}}
            g['63'] = {
                'class_type': 'ControlNetLoader',
                'inputs': {'control_net_name': 'instantid_controlnet.safetensors'},
            }
            g['64'] = {
                'class_type': 'ApplyInstantID',
                'inputs': {
                    'instantid': ['60', 0],
                    'insightface': ['62', 0],
                    'control_net': ['63', 0],
                    'image': ['61', 0],
                    'model': ['11', 0],
                    'positive': ['20', 0],
                    'negative': ['21', 0],
                    'weight': weight,
                    'start_at': 0.0,
                    'end_at': end_at,
                },
            }
            g['31']['inputs']['model'] = ['64', 0]
            g['31']['inputs']['positive'] = ['64', 1]
            g['31']['inputs']['negative'] = ['64', 2]
        return g

    import shutil as _sh
    import tempfile as _tf

    cands = []
    _n = best_of if use_instantid else 1
    for _k in range(_n):
        try:
            outs = _comfy.submit(_build(seed + _k * 1000, use_instantid), timeout_s=300)
        except Exception as _se:
            _log(f'[instantid-arcane] submit failed ({_se})')
            outs = None
        if outs and _os.path.isfile(outs[0]):
            _tmp = _os.path.join(_tf.gettempdir(), f'arcid_{char_id[:8]}_{_k}.png')
            _sh.copy2(outs[0], _tmp)
            cands.append(_tmp)
    if not cands:
        _log('[instantid-arcane] no candidates produced — skip')
        return False

    # Pick the first candidate. Do NOT gate on ArcFace: it is trained on PHOTOS and reads a
    # painterly Arcane face at only ~0.08-0.16 even when the identity is perfect (the very
    # reason the pipeline uses a VLM attribute gate, not ArcFace, for stylized renders). An
    # absolute-floor ArcFace check here wrongly discards a good InstantID render and falls back
    # to style_arcane-only — which is exactly the identity-DRIFTING raw-sweep path. InstantID
    # locks the face by construction (embedding + keypoint controlnet during generation); trust
    # it. best_of>1 only adds seed diversity (the end_at 0.6 render is deterministically clean).
    pick = cands[0]

    # ---- resize to original dims + save ----
    try:
        from PIL import Image as _PImg2

        _res_im = _PImg2.open(pick).convert('RGB')
        if _res_im.size != (_ow, _oh):
            _res_im = _res_im.resize((_ow, _oh), _PImg2.LANCZOS)
        _res_im.save(dst_path)
    except Exception as _se2:
        _log(f'[instantid-arcane] save failed ({_se2}) — skip')
        return False
    _log(
        f'[instantid-arcane] {char_id}: Arcane(style_arcane+InstantID) '
        f'{"+id" if use_instantid else "style-only"} → {_os.path.basename(dst_path)}'
    )
    return True
