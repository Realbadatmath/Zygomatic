# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.arcane_restyle.depth — verbatim from arcane_restyle.py lines 146-396.

depth_controlnet_arcane_restyle — the universal arcane engine
(style LoRA + character LoRA + depth ControlNet, img2img)
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
_DEPTH_CKPT = _zyg_profiles._DEPTH_CKPT
_STYLE_NEG = _zyg_profiles._STYLE_NEG
_stage_char_lora = _zyg_profiles._stage_char_lora

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.arcane_restyle')


def depth_controlnet_arcane_restyle(char_id, style_cfg, src_path, dst_path=None, seed=42, log_fn=None):
    """Render-time Arcane restyle via **style_arcane LoRA + the character's identity LoRA +
    a DEPTH ControlNet**, img2img on the source. This is the UNIVERSAL arcane engine — it works
    for adults AND children:

      * style_arcane (trained weights) → the AUTHENTIC Arcane look (which a Qwen text instruction
        cannot reproduce).
      * the char's SDXL identity LoRA → the specific face/likeness (freckles etc.).
      * a DEPTH ControlNet from the source → locks head/face PROPORTIONS and pose. Depth is
        AGE-AGNOSTIC geometry, so — unlike InstantID's adult-trained ArcFace, which DISFIGURES a
        child — it preserves a child's proportions and never collapses the face. No face is
        required (works on full-body / back-of-head frames too, so no fallback needed).
      * img2img (denoise ~0.8) from the source → preserves the exact costume/composition.

    Deterministic and consistent across angles (unlike Qwen's unstable re-synthesis). Output is
    resized to the ORIGINAL source dims. Returns True on success, False (no-op) on any problem.
    """
    import os as _os

    _log = log_fn or (lambda m: None)
    dst_path = dst_path or src_path
    # PER-CHARACTER recipe overrides: the profile carries the default (e.g. the punchy adult
    # arcane recipe Cornelis is perfect on); a specific character's bible may override numerics
    # and/or opt into naturalistic softeners (e.g. Abel's calibrated soft-oil recipe). This keeps
    # one character's tuning from changing everyone else on the same style profile.
    try:
        from zyg_workflows import character_bible_service as _cbs_ov

        _ov = (((_cbs_ov.load(char_id) or {}).get('style_profile') or {}).get('restyle_overrides')) or {}
        if isinstance(_ov, dict) and _ov:
            style_cfg = {**style_cfg, **_ov}
            _log(f'[depth-arcane] per-char restyle_overrides for {char_id[:8]}: {sorted(_ov)}')
    except Exception as _exc:
        _zyg_log.warning('per-character restyle_overrides load failed, using the style profile defaults: %s', _exc)
    # per-character calibrated style-prompt modifiers (accepts the new `bold_arcane_mods` key and
    # the legacy `naturalistic_softeners` alias for back-compat).
    _soft = bool(style_cfg.get('bold_arcane_mods') or style_cfg.get('naturalistic_softeners'))
    base_ckpt = style_cfg.get('render_base_checkpoint') or 'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors'
    style_lora = style_cfg.get('render_style_lora') or 'style_arcane.safetensors'
    style_s = float(style_cfg.get('render_style_lora_scale', 1.15))
    char_s = float(style_cfg.get('render_char_lora_scale', 0.7))
    cn_name = style_cfg.get('render_depth_controlnet') or 'controlnet-depth-sdxl.safetensors'
    # LICENCE: Depth-Anything-V2 Small (vits) is Apache-2.0; Base/Large/Giant are
    # CC-BY-NC-4.0 and may not be used to produce commercially published assets. See the
    # _DEPTH_CKPT note in arcane_multichar.py. A style_cfg that names a vitb/vitl/vitg
    # checkpoint is REJECTED rather than silently honoured — a per-character bible override
    # is exactly how a banned model would creep back in unnoticed.
    depth_preproc = style_cfg.get('render_depth_preproc') or _DEPTH_CKPT
    if any(b in str(depth_preproc) for b in ('vitb', 'vitl', 'vitg')):
        if log_fn:
            log_fn(
                f'[restyle] LICENCE: refusing non-commercial depth checkpoint {depth_preproc!r} -> using {_DEPTH_CKPT}'
            )
        depth_preproc = _DEPTH_CKPT
    depth_s = float(style_cfg.get('render_depth_strength', 0.5))
    depth_end = float(style_cfg.get('render_depth_end', 0.85))
    denoise = float(style_cfg.get('render_denoise', 0.8))
    cfg = float(style_cfg.get('render_cfg', 6.5))
    steps = int(style_cfg.get('render_steps', 32))
    comfy_root = str(paths.ZYG_COMFY_ROOT)
    if not _os.path.isfile(_os.path.join(comfy_root, 'models', 'controlnet', cn_name)):
        _log(f'[depth-arcane] depth ControlNet missing ({cn_name}) — skip')
        return False
    try:
        from PIL import Image as _PImg

        with _PImg.open(src_path) as _im:
            _ow, _oh = _im.size
    except Exception as _oe:
        _log(f'[depth-arcane] cannot read {src_path} ({_oe}) — skip')
        return False

    # prompt: arcane style + identity + upper clothing; a child gets a youth-lock phrase so the
    # style prior (adult-leaning) does not age proportions up beyond the depth lock.
    _ident = _ads._identity_clause(char_id) or ''
    import re as _re_a

    _m = _re_a.search(r'(\d{1,2})\s*year', _ident)
    _age = int(_m.group(1)) if _m else 99
    _child = _age < 16
    # age-graduated youth lock: a small child needs the round-face lock; a young teen
    # (13-15) should read youthful/boyish but NOT a little kid (the style ages ~+2-3y).
    if _age <= 12:
        _youth_phrase = 'a young child, youthful soft round childlike face, '
        _aged_neg = ', adult, grown man, aged up, elongated face, moustache, beard, stubble'
    elif _age <= 16:
        _youth_phrase = f'a youthful teenage boy about {_age} years old, young and boyish (not a little child), '
        _aged_neg = ', grown adult man, middle-aged, full beard, thick moustache, wrinkles, jowls'
    else:
        _youth_phrase = ''
        _aged_neg = ''
    cap = (
        style_cfg.get('caption_clause')
        or 'League of Legends Arcane art style, painterly semi-realistic 2D animation, thick visible oil brush strokes, dramatic cinematic lighting'
    )
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
        _lk = _re_a.compile(r'breech|trouser|stocking|shoe|boot|\bpant|hose|legging', _re_a.I)
        _up = [p.strip() for p in _re_a.split(r'[,;]', _cloth) if p.strip() and not _lk.search(p)]
        _cloth = ', '.join(_up) if _up else _cloth
    _tok = f'ZYG_CHAR_{char_id[:6].upper()}'
    prompt = f'{_tok}, {cap}, {_youth_phrase}{_ident}'
    if _cloth:
        prompt += f', wearing {_cloth}'
    # per-character calibrated style modifiers (2026-07-27 sweeps + 4-judge panels). For Abel the
    # unanimous winner is "r4" = BOLD Arcane splash-art oil: confident decisive brushwork, crisp
    # defined features, dramatic rim light, striking (non-neon) eyes — matching the sweep bottom-middle
    # target and the father's boldness (earlier "soft/gentle" and even "impasto" phrasings came out
    # muted/subdued). OPT-IN per character (bold_arcane_mods) so it never touches characters tuned on
    # the punchy default recipe (e.g. Cornelis, already perfect there).
    if _soft:
        prompt += (
            ', League of Legends Arcane splash art, bold confident oil brushwork, '
            'crisp defined painterly features, dramatic rim lighting, warm natural light, '
            'striking bold eyes'
        )
    _id_neg = _ads._identity_negatives(char_id)
    neg = f'{_STYLE_NEG}, {_id_neg}' if _id_neg else _STYLE_NEG
    neg += ', photograph, photorealistic, dslr, 3d render, flat anime, cel shaded, deformed, extra face'
    neg += _aged_neg
    if _soft:
        # MILD guard: block ONLY the neon/hextech glow + glowing-metal-button hallucination (keep the
        # bold striking blue eyes the target has), plus smooth/airbrushed and aging-up that fight the
        # bold youthful Arcane oil. (An earlier heavy "bright electric blue eyes" negative wrongly
        # muted the eyes and dulled the whole render.)
        neg += (
            ', glowing neon eyes, laser eyes, hextech glowing eyes, glowing buttons, '
            'bright glowing blue buttons, sapphire gemstone buttons, gold trim, brass buttons, '
            'smooth airbrushed, glossy plastic skin, old man, stubble'
        )
        # guard hair against the style's blond drift — but only when the character is not actually blond.
        if not _re_a.search(r'blond|blonde|golden.?hair|platinum|flaxen', _ident, _re_a.I):
            neg += ', blonde hair, platinum blonde, bleached hair, golden yellow hair'

    char_lora = _stage_char_lora(char_id, _log)
    from zyg_workflows import _comfy_client as _comfy

    try:
        st = _comfy.stage_input_image(src_path)
    except Exception as _se:
        _log(f'[depth-arcane] stage failed ({_se}) — skip')
        return False
    # base model chain: checkpoint -> style_arcane -> (char lora) ; clip from the last loader
    g = {
        '10': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': base_ckpt}},
        '11': {
            'class_type': 'LoraLoader',
            'inputs': {
                'model': ['10', 0],
                'clip': ['10', 1],
                'lora_name': style_lora,
                'strength_model': style_s,
                'strength_clip': style_s,
            },
        },
        '14': {'class_type': 'LoadImage', 'inputs': {'image': st}},
        '15': {
            'class_type': 'DepthAnythingV2Preprocessor',
            'inputs': {'image': ['14', 0], 'ckpt_name': depth_preproc, 'resolution': 1024},
        },
        '16': {'class_type': 'VAEEncode', 'inputs': {'pixels': ['14', 0], 'vae': ['10', 2]}},
        '18': {'class_type': 'ControlNetLoader', 'inputs': {'control_net_name': cn_name}},
        '30': {'class_type': 'CLIPTextEncode', 'inputs': {'text': prompt}},
        '31': {'class_type': 'CLIPTextEncode', 'inputs': {'text': neg}},
        '19': {
            'class_type': 'ControlNetApplyAdvanced',
            'inputs': {
                'positive': ['30', 0],
                'negative': ['31', 0],
                'control_net': ['18', 0],
                'image': ['15', 0],
                'strength': depth_s,
                'start_percent': 0.0,
                'end_percent': depth_end,
            },
        },
        '40': {
            'class_type': 'KSampler',
            'inputs': {
                'model': None,
                'positive': ['19', 0],
                'negative': ['19', 1],
                'latent_image': ['16', 0],
                'seed': int(seed),
                'steps': steps,
                'cfg': cfg,
                'denoise': denoise,
                'sampler_name': 'dpmpp_2m',
                'scheduler': 'karras',
            },
        },
        '41': {'class_type': 'VAEDecode', 'inputs': {'samples': ['40', 0], 'vae': ['10', 2]}},
        '50': {
            'class_type': 'SaveImage',
            'inputs': {'images': ['41', 0], 'filename_prefix': f'ZygDepthArc_{char_id[:8]}'},
        },
    }
    _model_out = ['11', 0]
    _clip_out = ['11', 1]
    if char_lora:
        g['12'] = {
            'class_type': 'LoraLoader',
            'inputs': {
                'model': ['11', 0],
                'clip': ['11', 1],
                'lora_name': char_lora,
                'strength_model': char_s,
                'strength_clip': char_s,
            },
        }
        _model_out = ['12', 0]
        _clip_out = ['12', 1]
    g['30']['inputs']['clip'] = _clip_out
    g['31']['inputs']['clip'] = _clip_out
    g['40']['inputs']['model'] = _model_out
    try:
        outs = _comfy.submit(g, timeout_s=600)
    except Exception as _sub_e:
        _log(f'[depth-arcane] submit failed ({_sub_e})')
        return False
    if not (outs and _os.path.isfile(outs[0])):
        _log('[depth-arcane] no output — skip')
        return False
    try:
        from PIL import Image as _PImg2

        _res = _PImg2.open(outs[0]).convert('RGB')
        if _res.size != (_ow, _oh):
            _res = _res.resize((_ow, _oh), _PImg2.LANCZOS)
        _res.save(dst_path)
    except Exception as _we:
        _log(f'[depth-arcane] save failed ({_we}) — skip')
        return False
    _log(
        f'[depth-arcane] {char_id}: Arcane(style_arcane+charLoRA+depth{"+child" if _child else ""}) '
        f'→ {_os.path.basename(dst_path)}'
    )
    return True
