# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The preview slot plan: _build_char_preview_slots.

Moved verbatim out of the old single-file char_state_service.py (lines 1667-1947).
"""

import os
from zyg_workflows.char_state_service._common import (
    _zyg_log,
)
from zyg_workflows.char_state_service.lora_discovery import (
    _char_effective_hybrid_preview,
    _char_preview_slot_names,
    _char_restyle_profile,
    _normalize_char_model_family,
)


def _build_char_preview_slots(
    params: dict,
    info: dict,
    model_family: str | None = None,
) -> list[tuple[str, str, int, int, str]]:
    """Return [(filename_stem, prompt, width, height, slot_model_family), …]."""
    _mf_slots = _normalize_char_model_family(model_family, params, info)
    _hybrid = _mf_slots == 'flux' and _char_effective_hybrid_preview(
        params,
        info,
        char_id=(info or {}).get('char_id') or (params or {}).get('char_id') or '',
        dataset_dir=(info or {}).get('dataset_dir') or '',
    )
    try:
        from zyg_workflows import character_bible_service as _cbs_ad

        params = _cbs_ad.apply_auto_defaults(
            params,
            seed_key=(info or {}).get('char_id') or (params or {}).get('char_id') or '',
        )
    except Exception as _exc:
        _zyg_log.debug('auto-defaults not applied to the params: %s', _exc)
    if not info.get('package'):
        try:
            from zyg_workflows import character_bible_service as _cbs_hp

            _cid_pkg = (info.get('char_id') or '').strip()
            _pkg_hp = _cbs_hp.load(_cid_pkg) if _cid_pkg else None
            if _pkg_hp:
                info['package'] = _pkg_hp
        except Exception as _exc:
            _zyg_log.debug('bible package not loaded for the prompt: %s', _exc)

    trigger = info.get('trigger_token') or ''
    _tp = f'{trigger} ' if trigger else ''
    _ident = (params.get('identity') if isinstance(params.get('identity'), dict) else {}) or params
    _style = (params.get('style_profile') if isinstance(params.get('style_profile'), dict) else {}) or params

    _gpr = _ident.get('gender', 'female')
    _age_pr = _ident.get('age') or params.get('age')
    _skp = _ident.get('skin_tone', 'medium')
    _hrp = _ident.get('hair_color', 'brown')
    _hair_style_pr = _ident.get('hair_style', '') or params.get('hair_style', '')
    _hair_len_pr = _ident.get('hair_length', '') or params.get('hair_length', '')
    _hair_tex_pr = _ident.get('hair_texture', '') or params.get('hair_texture', '')
    _eyp = _ident.get('eye_color', 'brown')
    _eye_shape_pr = _ident.get('eye_shape', '') or params.get('eye_shape', '')
    _face_shape_pr = _ident.get('face_shape', '') or params.get('face_shape', '')
    _nose_pr = _ident.get('nose_shape', '') or params.get('nose_shape', '')
    _lip_pr = _ident.get('lip_shape', '') or params.get('lip_shape', '')
    _brow_pr = _ident.get('eyebrow_style', '') or params.get('eyebrow_style', '')
    _marks_pr = _ident.get('distinctive_marks', '') or params.get('distinctive_marks', '')
    _heritage_pr = _ident.get('ethnic_heritage', '') or params.get('ethnic_heritage', '')
    _genre_pr = (_style.get('genre') or params.get('genre') or 'general').lower()
    _fhp = (_ident.get('facial_hair') or params.get('facial_hair') or 'none').lower()
    _mmp = max(1, min(100, int(_ident.get('muscle_mass') or params.get('muscle_mass') or 20)))
    _render_pr = _style.get('render_style') or params.get('style') or 'photorealistic'
    _clothes_pr = _style.get('default_clothing', '') or params.get('default_clothing', '')
    _accs_pr = _style.get('accessories', '') or params.get('accessories', '')
    _expr_pr = _style.get('default_expression', '') or params.get('default_expression', '')
    _posture_pr = _style.get('posture', '') or params.get('posture', '')

    try:
        from zyg_workflows import character_bible_service as _cbs_expr

        _expr_pt = _cbs_expr.format_expression_for_prompt(_expr_pr)
        if _expr_pt:
            _expr_pt = f', {_expr_pt}'
        _smile_boost = _cbs_expr.preview_expression_boost(params)
        _smile_pt = f', {_smile_boost}' if _smile_boost else ''
    except Exception:
        _expr_pt = f', {_expr_pr} expression' if _expr_pr else ''
        _smile_pt = ''

    _hair_bits: list[str] = []
    for _hb in (_hair_len_pr, _hair_tex_pr, _hrp, _hair_style_pr):
        if _hb and _hb not in _hair_bits:
            _hair_bits.append(_hb)
    _hair_desc = ' '.join(_hair_bits) + ' hair' if _hair_bits else f'{_hrp} hair'

    _face_bits: list[str] = []
    if _face_shape_pr:
        _face_bits.append(f'{_face_shape_pr} face')
    if _nose_pr:
        _face_bits.append(f'{_nose_pr} nose')
    if _lip_pr:
        _face_bits.append(f'{_lip_pr} lips')
    if _eye_shape_pr:
        _face_bits.append(f'{_eye_shape_pr} {_eyp} eyes')
    else:
        _face_bits.append(f'{_eyp} eyes')
    if _brow_pr:
        _face_bits.append(f'{_brow_pr} eyebrows')
    _face_desc = ', '.join(_face_bits)

    # Presentation comes from default_clothing / expression / posture (brief or Auto).
    # Skip genre cliché suffixes in studio preview — they add scenery, combat gear, etc.
    _genre_part = ''

    def _muscle_desc(v):
        if v <= 20:
            return 'slender build'
        if v <= 40:
            return 'average build'
        if v <= 60:
            return 'athletic build'
        if v <= 80:
            return 'muscular build'
        return 'very muscular bodybuilder build'

    _muscle_part = f', {_muscle_desc(_mmp)}'
    _fh_part = f', {_fhp} facial hair' if _fhp not in ('none', '') else ''
    _heritage_pt = f'{_heritage_pr} heritage, ' if _heritage_pr else ''
    _age_pt = f'{int(_age_pr)}-year-old ' if (_age_pr and str(_age_pr).isdigit()) else ''
    _clothes_pt = f', wearing {_clothes_pr}' if _clothes_pr else ''
    _accs_pt = f', {_accs_pr}' if (_accs_pr and _accs_pr.lower() not in ('', 'none')) else ''
    _posture_pt = f', {_posture_pr}' if _posture_pr else ''
    _marks_pt = f', {_marks_pr}' if (_marks_pr and _marks_pr.lower() not in ('', 'none')) else ''

    _qs_pr = (
        ((info.get('package') or {}).get('conditioning', {}).get('quality_suffix'))
        or params.get('quality_suffix')
        or 'highly detailed, sharp focus, cinematic lighting'
    )

    _render_lc = (_render_pr or '').strip().lower()
    # SDXL-only: a restyle char's photoreal FLUX twin preview must stay photoreal.
    _restyle_prof_bs = _char_restyle_profile(params, info) if _mf_slots == 'sdxl' else None
    if _restyle_prof_bs:
        # 2026-07-27: restyle (Arcane) — drive _render_lc to the 'restyle' sentinel so
        # EVERY photoreal injection below (the RAW-photograph lead, the visible-pores
        # qs_face, the PHOTOREAL_SKIN_EXTRA block) skips its `== 'photorealistic'` gate,
        # and inject the profile's painterly caption clause as the positive style phrase.
        _render_lc = 'restyle'
        _style_phrase = ((_restyle_prof_bs.get('restyle') or {}).get('caption_clause')) or (
            'arcane style, painterly semi-realistic 2D animation, hand-painted illustration, '
            'visible brush strokes, stylized painterly shading, realistic proportions, '
            'cinematic painterly lighting'
        )
    elif _render_lc == 'photorealistic':
        try:
            from zyg_workflows import character_bible_service as _cbs_sty

            _style_phrase = _cbs_sty.PHOTOREAL_STYLE_PHRASE
        except Exception:
            _style_phrase = (
                'photorealistic, film photography, natural skin texture, visible pores, '
                'unretouched, fine film grain, cinematic lighting, 8k'
            )
    elif _render_lc == 'animated':
        if _mf_slots == 'sdxl':
            _style_phrase = (
                'flat cel-shaded anime illustration, hard clean outlines, flat vibrant colors, '
                'crisp line art, animation still frame, not a photograph, not oil painting'
            )
        else:
            _style_phrase = 'toon animated 3D illustration, cel shaded'
    else:
        _style_phrase = f'{_render_pr} render'

    _slot_front, _slot_face = _char_preview_slot_names(_mf_slots, params, info)
    _gender_solo = 'one woman only' if _gpr == 'female' else ('one man only' if _gpr == 'male' else 'one person only')
    _solo_pos = (
        'solo, single character, one person only, centered in frame, only one subject, '
        f'{_gender_solo}, looking at viewer'
    )
    _identity_lead = ', '.join(
        p
        for p in (
            f'{_hrp} hair' if _hrp else '',
            f'{_eyp} eyes' if _eyp else '',
            f'{_skp} skin tone' if _skp else '',
        )
        if p
    )
    _id_block = f'{_identity_lead}, ' if _identity_lead else ''
    _hide_hands = os.environ.get('ZYG_PREVIEW_HIDE_HANDS', '').strip().lower() in (
        '1',
        'true',
        'yes',
    )
    if _hybrid:
        if _hide_hands:
            _pose_front = (
                'standing straight, simple neutral pose, arms relaxed at sides, '
                'waist-up medium shot, facing camera, hands below frame edge, '
                'cropped at hips, no visible hands, centered composition'
            )
        else:
            _pose_front = (
                'standing neutral, arms hanging straight down at sides, not bent, '
                'waist-up portrait, facing camera, both full hands visible at lower frame, '
                'open relaxed hands with five spread fingers each, hands not in pockets, '
                'not gripping clothing, not touching vest or lapels, hands not on hips, '
                'simple composition, centered subject'
            )
        _pw, _ph = 640, 960
        _face_w, _face_h = 512, 512
    elif _mf_slots == 'flux':
        _pose_front = (
            'full body, facing camera, neutral confident pose, arms relaxed at sides, centered portrait composition'
        )
        _pw, _ph = 512, 768
        _face_w, _face_h = 512, 512
    elif _hide_hands:
        _pose_front = (
            'standing straight, simple neutral pose, arms relaxed at sides, '
            'waist-up medium shot, facing camera, hands below frame edge, '
            'cropped at hips, no visible hands'
        )
        _pw, _ph = 640, 960
        _face_w, _face_h = 768, 768
    else:
        _pose_front = (
            'standing neutral, arms hanging straight down at sides, not bent, '
            'waist-up portrait, facing camera, both full hands visible at lower frame, '
            'open relaxed hands with five spread fingers each, hands not in pockets, '
            'not gripping clothing, not touching vest or lapels, hands not on hips'
        )
        _pw, _ph = 640, 960
        _face_w, _face_h = 768, 768
    _accs_enhanced = _accs_pt
    if _accs_pr and _accs_pr.strip().lower() not in ('', 'none'):
        try:
            from zyg_workflows import character_bible_service as _cbs_ac

            _enh = _cbs_ac.enhance_accessories_for_prompt(_accs_pr)
            if _enh:
                _accs_enhanced = f', {_enh}'
        except Exception:
            if 'earring' in _accs_pr.lower():
                _accs_enhanced = f'{_accs_pr}, matching identical stud earrings on both ears, symmetrical jewelry'
    _qs_face = _qs_pr
    if _render_lc == 'photorealistic':
        _qs_face = (
            'visible skin pores, natural skin microdetail, unretouched, fine film grain, '
            'macro facial texture, sharp eye and lash detail, soft even studio lighting, '
            '85mm portrait lens, f/5.6, sharp focus on face, 8k, natural skin grain'
        )
    _skin_texture_pt = ''
    if _render_lc == 'photorealistic':
        try:
            from zyg_workflows import character_bible_service as _cbs_sk

            _skin_texture_pt = f', {_cbs_sk.PHOTOREAL_SKIN_EXTRA}'
        except Exception:
            _skin_texture_pt = ', visible skin pores, natural skin microdetail, unretouched, fine film grain'
    _front_mf = 'sdxl' if _hybrid else _mf_slots
    _face_mf = 'flux' if _hybrid else _mf_slots
    _photoreal_lead = (
        'RAW photograph, DSLR portrait, unretouched real person, ' if _render_lc == 'photorealistic' else ''
    )
    _studio_ctx = (
        'plain neutral gray studio backdrop, seamless empty stage, waist-up portrait, '
        'no props, no furniture, no outdoor scenery, no weapons'
    )
    return [
        (
            _slot_front,
            f'{_photoreal_lead}{_tp}{_id_block}{_heritage_pt}{_age_pt}{_gpr} character, {_solo_pos}, '
            f'{_pose_front}, '
            f'{_face_desc}, {_hair_desc}{_fh_part}{_muscle_part}'
            f'{_clothes_pt}{_accs_enhanced}{_expr_pt}{_smile_pt}{_posture_pt}{_marks_pt}{_skin_texture_pt}, '
            f'{_studio_ctx}, {_style_phrase}, {_qs_pr}{_genre_part}',
            _pw,
            _ph,
            _front_mf,
        ),
        (
            _slot_face,
            f'{_photoreal_lead}{_tp}{_id_block}{_heritage_pt}{_age_pt}{_gpr} character, {_solo_pos}, '
            f'close-up portrait, head and shoulders only, facing camera, '
            f'{_face_desc}, {_hair_desc}{_fh_part}'
            f'{_accs_enhanced}{_expr_pt}{_smile_pt}{_marks_pt}{_skin_texture_pt}, '
            f'{_studio_ctx}, {_style_phrase}, {_qs_face}{_genre_part}',
            _face_w,
            _face_h,
            _face_mf,
        ),
    ]
