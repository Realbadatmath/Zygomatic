# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Creature/character listing and photo-analysis routes.

Verbatim move of bp_storyteller.py:263-572 (2026-10-06 split).
"""

import json
import logging as _zyg_logging
import os

from flask import jsonify, request

from zyg_dashboard.bp_storyteller import (  # noqa: E402  the package __init__ binds these before it imports this module
    ZYG_LORA_OUTPUTS,
    _char_library_trained_at,
    _char_lora_output_ready,
    _char_preview_png_names,
    _normalize_char_model_family,
    bp,
    limiter,
)
from zyg_dashboard.bp_storyteller.guards import (
    _CHARS_DATASET_ROOT,
    _char_lora_usable,
    _env_on,
    _is_medusa_cid,
)

_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_storyteller')


@bp.route('/api/internal/creature/list')
@limiter.exempt
def api_internal_creature_list():
    """Return trained creature LoRAs for the Creature Library UI."""
    try:
        from zyg_workflows import creature_library_service as _cls

        creatures = _cls.list_creatures()
    except Exception as exc:
        return jsonify({'error': str(exc), 'creatures': [], 'count': 0}), 500
    return jsonify({'creatures': creatures, 'count': len(creatures)})


@bp.route('/api/internal/storyteller/list-chars')
@limiter.exempt
def api_internal_storyteller_list_chars():
    """
    Return a list of previously trained LoRA characters.
    Each entry includes model_family / lora_families for pipeline matching.
    Query: ?model_family=flux|sdxl filters to characters with that LoRA family.
    """
    from zyg_workflows import character_lora_family as _clf_lib

    _lora_root = str(ZYG_LORA_OUTPUTS / 'storyteller_chars')
    _dataset_root = _CHARS_DATASET_ROOT
    _mf_query = (request.args.get('model_family') or '').strip().lower()
    if _mf_query not in ('flux', 'sdxl'):
        _mf_query = ''
    chars = []

    # Collect char IDs from both lora-outputs and lora-datasets (union)
    _all_cids = set()
    if os.path.isdir(_lora_root):
        _all_cids.update(os.listdir(_lora_root))
    if os.path.isdir(_dataset_root):
        _all_cids.update(os.listdir(_dataset_root))

    _mfilter_lc = _env_on('ZYG_LIST_CHARS_MEDUSA_FILTER')
    for _cid in sorted(_all_cids):
        # 2026-07-31: Medusa chars share this dataset root but are isolated to
        # the Medusa app. list-contact-sheets strips them (line ~663); this
        # unauthenticated list did not, and would hand their preview_url —
        # servable by /api/storyteller/char-image/ — to any anonymous visitor.
        if _mfilter_lc and _is_medusa_cid(_cid):
            continue
        _lora_dir = os.path.join(_lora_root, _cid)
        _dataset_dir = os.path.join(_dataset_root, _cid)
        if not os.path.isdir(_dataset_dir):
            continue  # no training data — skip

        # Find the LoRA safetensors file (may be in lora-outputs)
        _lora_families = _clf_lib.char_lora_families_for_dir(_lora_dir)
        _lora_on_disk = bool(_lora_families) or _char_lora_output_ready(_lora_dir)
        # 2026-07-31: adapters exist on disk even when the operator DECLINED the
        # contact-sheet run and identity QC failed — training happens before both
        # gates. c3345deb5bde (front sim 0.194 vs a 0.42 floor, declined) still
        # advertised itself as "LoRA trained — full character consistency".
        _lora_ready = _lora_on_disk
        _lora_block_reason = ''
        if _lora_on_disk:
            _ok_usable, _why_usable = _char_lora_usable(_cid, _mf_query or '')
            if not _ok_usable:
                _lora_ready = False
                _lora_block_reason = _why_usable
        if _mf_query and _lora_families and _mf_query not in _lora_families:
            continue

        # Load manifest — check dataset dir first, then lora-outputs
        _meta = {}
        for _mdir in (_dataset_dir, _lora_dir):
            _manifest_path = os.path.join(_mdir, 'manifest.json')
            if os.path.isfile(_manifest_path):
                try:
                    with open(_manifest_path, encoding='utf-8') as _mf:
                        _meta = json.load(_mf)
                    break
                except (OSError, ValueError) as _exc:
                    _zyg_log.debug('character manifest unreadable in %s, trying the next location: %s', _mdir, _exc)

        # Find best preview image — SDXL canonical, then FLUX/legacy, then Blender renders
        _preview_file = None
        _mf_list = 'flux'
        _pkg_lc = None
        try:
            from zyg_workflows import character_bible_service as _cbs_lc

            _pkg_lc = _cbs_lc.load(_cid)
            _mf_list = _normalize_char_model_family(
                ((_pkg_lc or {}).get('conditioning') or {}).get('model_family'),
                {},
                {'package': _pkg_lc},
            )
        except Exception as _exc:
            _zyg_log.warning('character bible load failed for %s, model family and previews fall back: %s', _cid, _exc)
        _flux_prev = _char_preview_png_names('flux', {}, {'package': _pkg_lc})
        _sdxl_prev = _char_preview_png_names('sdxl', {}, {'package': _pkg_lc})
        from zyg_workflows import contact_sheet_pipeline as _csp_lc

        _cs_meta = _meta
        _cs_preview_urls: dict = {}
        if _csp_lc.is_contact_sheet_char(_cid, _cs_meta):
            if _csp_lc.master_sheet_exists(_cid):
                _preview_file = None
                _cs_preview_urls = _csp_lc.library_preview_urls(_cid, _dataset_dir, _cs_meta)
            else:
                _cs_preview_urls = _csp_lc.library_preview_urls(_cid, _dataset_dir, _cs_meta)
                _preview_file = None
                if _cs_preview_urls.get('preview_url', '').startswith('/api/storyteller/char-image/'):
                    _preview_file = _cs_preview_urls['preview_url'].split('/')[-1].split('?')[0]
        else:
            _cs_preview_urls = {}
        _PREVIEW_CANDIDATES = ((_flux_prev + _sdxl_prev) if _mf_list == 'flux' else (_sdxl_prev + _flux_prev)) + (
            'preview_flux_front.png',
            'preview_flux_face.png',
            'contactsheet_00.png',
            'face_00_000deg.png',
            'full_00_000deg.png',
            'render_front.png',
            'render_000.png',
        )
        if not _cs_preview_urls.get('preview_url'):
            for _pname in _PREVIEW_CANDIDATES:
                if os.path.isfile(os.path.join(_dataset_dir, _pname)):
                    _preview_file = _pname
                    break
        if not _preview_file and not _cs_preview_urls.get('preview_url') and os.path.isdir(_dataset_dir):
            _any_pngs = sorted(f for f in os.listdir(_dataset_dir) if f.endswith('.png'))
            if _any_pngs:
                _preview_file = _any_pngs[0]

        # If metadata still missing from manifests, parse from caption .txt files
        _trigger = _meta.get('trigger_token', '')
        _gender = _meta.get('gender', '')
        _hair = _meta.get('hair_color', '')
        _eye = _meta.get('eye_color', '')
        _style = _meta.get('style', '')
        if not _gender or not _trigger:
            # Read trigger token from training_status.json
            _ts_path = os.path.join(_lora_dir, 'training_status.json')
            if os.path.isfile(_ts_path):
                try:
                    import json as _jlc

                    _ts_data = _jlc.load(open(_ts_path, encoding='utf-8'))
                    if not _trigger:
                        _trigger = _ts_data.get('trigger_token', '')
                except (OSError, ValueError) as _exc:
                    _zyg_log.debug('trigger token lookup failed, leaving it empty: %s', _exc)
            # Parse first caption .txt for gender/hair/eye/style
            _cap_files = sorted(f for f in os.listdir(_dataset_dir) if f.endswith('.txt'))
            if _cap_files:
                try:
                    _cap = open(os.path.join(_dataset_dir, _cap_files[0]), encoding='utf-8').read()
                    import re as _relc

                    if not _trigger:
                        _trigger = _cap.split()[0] if _cap.split() else ''
                    if not _gender:
                        _gm = _relc.search(r'\b(female|male)\b', _cap)
                        if _gm:
                            _gender = _gm.group(1)
                    if not _hair:
                        _hm = _relc.search(r'(\w[\w ]*?)\s+hair', _cap)
                        if _hm:
                            _hair = _hm.group(1).strip().split()[-1]
                    if not _eye:
                        _em = _relc.search(r'(\w+)\s+eyes', _cap)
                        if _em:
                            _eye = _em.group(1)
                    if not _style:
                        _sm = _relc.search(r'\b(animated|photorealistic)\b', _cap)
                        if _sm:
                            _style = _sm.group(1)
                except Exception as _exc:
                    _zyg_log.debug('caption parse failed, leaving the inferred traits empty: %s', _exc)

        # 2026-08-01: skip only characters with NO adapter at all. A character
        # whose adapter exists but whose run was declined / QC-failed used to
        # vanish from this operator-facing list with no explanation — worse than
        # the bug it replaced. Emit the row carrying lora_ready=False and
        # lora_block_reason so the operator can see WHY it is unavailable.
        # The public wizard filters these out separately (zpub_routes_storyteller
        # _zpub_char_lora_usable) and gates selection on lora_ready, so showing
        # the row here cannot make a declined character selectable.
        if not _lora_on_disk:
            continue  # skip characters without a completed LoRA
        if not _lora_ready and not _env_on('ZYG_LIST_CHARS_SHOW_BLOCKED'):
            continue

        # Prefer the character bible (v2) for descriptor data — it's the
        # single source of truth and contains every advanced-identity field
        # the new UI knows about.  Fall back to manifest/caption parsing
        # for very old characters that pre-date the bible.
        _bible_pkg = {}
        try:
            from zyg_workflows import character_bible_service as _cbs_lc

            _bible_pkg = _cbs_lc.load(_cid) or {}
        except Exception:
            _bible_pkg = {}
        _b_ident = _bible_pkg.get('identity', {}) or {}
        _b_style = _bible_pkg.get('style_profile', {}) or {}

        _full_name = _bible_pkg.get('display_name') or _meta.get('name', '')
        try:
            from zyg_workflows import character_bible_service as _cbs_lbl

            _lib_label = _cbs_lbl.format_library_label(_full_name)
        except Exception:
            _lib_label = _full_name or _cid[:8]

        _primary_mf = _mf_list
        if _lora_families:
            if _mf_query and _mf_query in _lora_families:
                _primary_mf = _mf_query
            elif _primary_mf not in _lora_families:
                _primary_mf = _lora_families[0]

        chars.append(
            {
                'char_id': _cid,
                'model_family': _primary_mf,
                'lora_families': _lora_families or ([_primary_mf] if _lora_ready else []),
                'name': _full_name,
                'library_label': _lib_label,
                'trigger_token': _bible_pkg.get('trigger_token') or _trigger or f'ZYG_CHAR_{_cid[:6].upper()}',
                'gender': _b_ident.get('gender') or _gender or 'unknown',
                'age': _b_ident.get('age'),
                'age_range': _b_ident.get('age_range', ''),
                'height': _b_ident.get('height_m', 1.70),
                'skin_tone': _b_ident.get('skin_tone') or _meta.get('skin_tone', 'medium'),
                'hair_color': _b_ident.get('hair_color') or _hair,
                'hair_style': _b_ident.get('hair_style', ''),
                'hair_length': _b_ident.get('hair_length', ''),
                'hair_texture': _b_ident.get('hair_texture', ''),
                'eye_color': _b_ident.get('eye_color') or _eye,
                'eye_shape': _b_ident.get('eye_shape', ''),
                'eyebrow_style': _b_ident.get('eyebrow_style', ''),
                'face_shape': _b_ident.get('face_shape', ''),
                'nose_shape': _b_ident.get('nose_shape', ''),
                'lip_shape': _b_ident.get('lip_shape', ''),
                'facial_hair': _b_ident.get('facial_hair', 'none'),
                'muscle_mass': _b_ident.get('muscle_mass') or _b_ident.get('body_build') or 20,
                'distinctive_marks': _b_ident.get('distinctive_marks', ''),
                'ethnic_heritage': _b_ident.get('ethnic_heritage', ''),
                'style': _b_style.get('render_style') or _style or 'photorealistic',
                'genre': _b_style.get('genre') or _meta.get('genre', 'general'),
                'default_clothing': _b_style.get('default_clothing', ''),
                'accessories': _b_style.get('accessories', ''),
                'default_expression': _b_style.get('default_expression', ''),
                'posture': _b_style.get('posture', ''),
                'lora_ready': _lora_ready,
                'lora_on_disk': _lora_on_disk,
                'lora_block_reason': _lora_block_reason,
                'preview_url': (
                    _cs_preview_urls.get('preview_url')
                    or (f'/api/storyteller/char-image/{_cid}/{_preview_file}' if _preview_file else None)
                ),
                'contact_sheet_url': _cs_preview_urls.get('contact_sheet_url'),
                'source': _meta.get('source')
                or (
                    'contact_sheet'
                    if _csp_lc.is_contact_sheet_char(_cid, _meta)
                    else (
                        'blender'
                        if 'blender' in str(_meta.get('render_mode') or _meta.get('source') or '').lower()
                        else (_meta.get('source') or 'character')
                    )
                ),
                'render_mode': _meta.get('render_mode') or '',
                'creation_pipeline': (
                    'multi_angle_contact_sheet' if _csp_lc.is_contact_sheet_char(_cid, _meta) else 'character_creation'
                ),
                'trained_at': _char_library_trained_at(_cid, _meta, _lora_dir),
            }
        )

    chars.sort(key=lambda c: c.get('trained_at') or '', reverse=True)

    return jsonify({'chars': chars, 'count': len(chars)})


@bp.route('/api/internal/storyteller/analyze-character-photo', methods=['POST'])
@limiter.exempt
def api_internal_storyteller_analyze_character_photo():
    """Vision analysis for Character Generation photo upload → form fields + captions."""
    if not request.content_type or 'multipart/form-data' not in request.content_type:
        return jsonify({'error': 'multipart/form-data required with photo field'}), 400
    photo = request.files.get('photo')
    if not photo or not photo.filename:
        return jsonify({'error': 'photo file required'}), 400
    try:
        from zyg_workflows import character_photo_analysis_service as _cpas

        if not _cpas.analysis_enabled():
            return jsonify({'ok': False, 'error': 'disabled', 'fields': {}}), 503
        raw = photo.read()
        mt = photo.content_type or 'image/jpeg'
        result = _cpas.analyze_image_bytes(raw, mt, log_fn=lambda m: _zyg_log.info(f'[ST-CHAR-PHOTO] {m}'))
        try:
            _cpas.evict_all_ollama_models(
                log_fn=lambda m: _zyg_log.info(f'[ST-CHAR-PHOTO] {m}'),
            )
        except Exception as _exc:
            _zyg_log.debug('ollama model eviction skipped: %s', _exc)
        status = 200 if result.get('ok') else 503
        return jsonify(result), status
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)[:300], 'fields': {}}), 500
