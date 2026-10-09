# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401
# F401: the original module-level import block is reproduced verbatim in every
# section module, both so `pkg.os` / `pkg.json` style attribute access keeps
# resolving and so the function-local `import re as _re` imports in the moved
# bodies compile exactly as they did in the single file.

"""Character library: download names, LoRA readiness, disk entries, list-chars.

Moved verbatim out of zpub_routes_storyteller.py (lines 582-1215).
"""

import json
import logging as _zyg_logging
import os
import re
import threading
import time
import uuid
from datetime import datetime

import requests as _requests
from flask import (
    Blueprint,
    jsonify,
    request,
    session,
)

from zyg_workflows import paths
from zyg_workflows.medusa_chars import filter_out_medusa, is_medusa_char
from zyg_zero import paths as _zero_paths
from zyg_zero.zpub_config import AVG_PIPELINE_SECONDS, MAIN_APP_URL, _ams_iso, public_url
from zyg_zero.zpub_gate import _client_ip, _require_api_session, _session_id, _session_invite, limiter
from zyg_zero.zpub_routes_storyteller.dataset_paths import _DATASET_ROOT
from zyg_zero.zpub_main_api import _int_headers, _parse_model_family, _parse_pipeline_options, _token_check, _token_use
from zyg_zero.zpub_store import (
    _LOG_DIR,
    _enqueue,
    _get_running,
    _link_session_job,
    _link_token_job,
    _pending_store,
    _queue_length,
    _save_job,
    _zpub_log,
)

from zyg_zero.zpub_routes_storyteller.base import (
    _ZPUB_HEX_CHARID_ONLY,
    _ZPUB_LIB_IDENTITY,
    _ZPUB_LIST_CHARS_MEDUSA_FILTER,
    _ZPUB_LORA_USABLE_GATE,
    _ZPUB_NAME_INDEX_TTL,
    _zpub_is_listable_char_id,
    _zpub_story_gate,
    bp,
)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_zero.zpub_routes_storyteller')

_CHAR_DATASET_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')


def _slugify_for_filename(text: str, max_len: int = 32) -> str:
    """Lowercase, ASCII-safe slug suitable for embedding in a filename.

    Strips diacritics, replaces whitespace with underscore, drops anything
    outside ``[a-z0-9_-]``. Always returns at least ``''`` if input is empty.
    """
    import re as _re
    import unicodedata as _ud

    if not text:
        return ''
    norm = _ud.normalize('NFKD', str(text)).encode('ascii', 'ignore').decode('ascii').lower()
    norm = _re.sub(r'\s+', '_', norm.strip())
    norm = _re.sub(r'[^a-z0-9_\-]+', '', norm)
    return norm[:max_len].strip('_-') or ''


# 2026-07-31: ?download=1 used to open and json.load EVERY character bible on
# disk (217 directories and growing) on EVERY request, purely to compute a
# cosmetic Content-Disposition filename — at the route's 120/min budget that is
# ~26,000 JSON parses per minute on the same box that runs the GPU pipelines.
# The name index is now memoized with a short TTL and invalidated on the root
# directory's mtime. Only the four fields the disambiguator actually reads are
# retained, so the cache stays small. ZYG_ZPUB_BIBLE_INDEX_TTL=0 disables it.
_NAME_INDEX_DISCRIMINATORS = ('hair_style', 'hair_color', 'body_build', 'gender')
_bible_name_index_lock = threading.Lock()
_bible_name_index: dict = {'built_at': 0.0, 'mtime': None, 'index': {}}


def _build_bible_name_index() -> dict:
    """Map ``display_name.lower() -> [(char_id, {display_name, identity}), …]``."""
    import os as _os
    import json as _json

    index: dict[str, list] = {}
    try:
        entries = _os.listdir(_CHAR_DATASET_ROOT)
    except Exception:
        return index
    for other_id in entries:
        other_bible = _os.path.join(_CHAR_DATASET_ROOT, other_id, 'character_bible.json')
        if not _os.path.isfile(other_bible):
            continue
        try:
            with open(other_bible, encoding='utf-8') as _bf:
                other = _json.load(_bf)
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
        other_name = (other.get('display_name') or '').strip().lower()
        if not other_name:
            continue
        _ident = other.get('identity') or {}
        index.setdefault(other_name, []).append(
            (
                other_id,
                {
                    'display_name': other.get('display_name') or '',
                    'identity': {k: _ident.get(k) for k in _NAME_INDEX_DISCRIMINATORS},
                },
            )
        )
    return index


def _bible_name_lookup(target: str) -> list:
    """TTL/mtime-cached lookup into the display-name index."""
    import os as _os

    if _ZPUB_NAME_INDEX_TTL <= 0:
        return _build_bible_name_index().get(target, [])
    try:
        mtime = _os.path.getmtime(_CHAR_DATASET_ROOT)
    except Exception:
        mtime = None
    now = time.time()
    with _bible_name_index_lock:
        stale = (
            not _bible_name_index['index']
            or _bible_name_index['mtime'] != mtime
            or (now - _bible_name_index['built_at']) > _ZPUB_NAME_INDEX_TTL
        )
        if stale:
            _bible_name_index['index'] = _build_bible_name_index()
            _bible_name_index['mtime'] = mtime
            _bible_name_index['built_at'] = now
        return list(_bible_name_index['index'].get(target, []))


def _list_same_name_bibles(char_id: str, display_name: str) -> list:
    """Return ``(other_char_id, other_bible)`` tuples that share display_name.

    Used both for collision detection and to pick a discriminator that
    actually *differs* from the colliding siblings (e.g. don't append
    ``auburn`` when every Smoke-Test character is also auburn).
    """
    if not display_name:
        return []
    target = display_name.strip().lower()
    try:
        return [row for row in _bible_name_lookup(target) if row[0] != char_id]
    except Exception:
        return []


def _char_display_name_for_download(char_id: str) -> str:
    """Resolve display name from bible, then char-gen state."""
    import os as _os
    import json as _json

    bible_path = _os.path.join(_CHAR_DATASET_ROOT, char_id, 'character_bible.json')
    try:
        if _os.path.isfile(bible_path):
            with open(bible_path, encoding='utf-8') as _bf:
                bible = _json.load(_bf)
            name = (bible.get('display_name') or '').strip()
            if name:
                return name
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    state_path = _os.path.join(_LOG_DIR, f'char_gen_{char_id}.json')
    try:
        if _os.path.isfile(state_path):
            with open(state_path, encoding='utf-8') as _sf:
                st = _json.load(_sf)
            name = ((st.get('params') or {}).get('name') or '').strip()
            if name:
                return name
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return ''


def _compute_char_download_name(char_id: str, base_filename: str) -> str:
    """Build a friendly download filename: ``{character_name}.png``.

    When another character shares the same display name, append a
    distinguishing field (hair style, hair color, …) or a short char_id slice.
    Falls back to the on-disk filename when no display name is known.
    """
    import os as _os
    import json as _json

    display_name = _char_display_name_for_download(char_id)
    if not display_name:
        return base_filename
    name_slug = _slugify_for_filename(display_name)
    if not name_slug:
        return base_filename
    _base, ext = _os.path.splitext(base_filename)
    if not ext:
        ext = '.png'
    parts = [name_slug]
    bible_path = _os.path.join(_CHAR_DATASET_ROOT, char_id, 'character_bible.json')
    bible = {}
    try:
        if _os.path.isfile(bible_path):
            with open(bible_path, encoding='utf-8') as _bf:
                bible = _json.load(_bf)
    except Exception:
        bible = {}
    siblings = _list_same_name_bibles(char_id, display_name)
    if siblings:
        identity = bible.get('identity') or {}
        sibling_identities = [(other_bible.get('identity') or {}) for (_, other_bible) in siblings]

        def _norm(v):
            try:
                v = str(v or '').strip().lower()
            except Exception:
                return ''
            return v if v and v not in {'auto', 'none', 'unknown'} else ''

        chosen_slug = ''
        for field in ('hair_style', 'hair_color', 'body_build', 'gender'):
            mine = _norm(identity.get(field))
            if not mine:
                continue
            theirs = {_norm(sid.get(field)) for sid in sibling_identities}
            if mine not in theirs:
                chosen_slug = _slugify_for_filename(str(identity.get(field) or ''), max_len=24)
                if chosen_slug:
                    break
        parts.append(chosen_slug or char_id[:6])
    return '_'.join(parts) + ext


@bp.route('/api/storyteller/char-image/<char_id>/<filename>')
@limiter.limit('120 per minute')
def api_storyteller_char_image(char_id: str, filename: str):
    """Serve a character dataset image directly from disk.

    Query params:
      ``download=1`` → set ``Content-Disposition: attachment`` with a
                       friendly filename based on the character name
                       (``nolan_sullivan.png`` or
                       ``hazel_long_flowing.png`` on name collision).
    """
    blocked = _zpub_story_gate()  # 2026-07-31: was reachable with no session —
    if blocked:  # the whole private character library was public
        return blocked
    import re as _re

    if not _re.match(r'^[a-f0-9]{12}$', char_id):
        return '', 404
    if not _re.match(r'^[a-zA-Z0-9_]+\.(png|jpg|jpeg)$', filename):
        return '', 404
    import os as _os

    img_path = _os.path.join(_CHAR_DATASET_ROOT, char_id, filename)
    if not _os.path.isfile(img_path):
        return '', 404
    from flask import send_file as _sf

    want_download = (request.args.get('download') or '').strip() in ('1', 'true', 'yes')
    mime = 'image/jpeg' if filename.lower().endswith(('.jpg', '.jpeg')) else 'image/png'
    if want_download:
        dl_name = _compute_char_download_name(char_id, filename)
        return _sf(img_path, mimetype=mime, as_attachment=True, download_name=dl_name)
    return _sf(img_path, mimetype=mime)


_LORA_OUTPUT_ROOT = str(paths.ZYG_LORA_OUTPUTS / 'storyteller_chars')
_CHAR_RUNTIME_DIR = str(_zero_paths.DATA_DIR / 'runtime')


def _zpub_char_lora_ready(lora_dir: str) -> bool:
    """True when LoRA safetensors exist (incl. lora-weights-flux layout)."""
    if not lora_dir or not os.path.isdir(lora_dir):
        return False
    for sub in ('', 'lora-weights', 'lora-weights-flux', 'lora-weights-sdxl'):
        base = lora_dir if not sub else os.path.join(lora_dir, sub)
        if not os.path.isdir(base):
            continue
        try:
            for entry in os.listdir(base):
                path = os.path.join(base, entry)
                if os.path.isfile(path) and entry.endswith('.safetensors'):
                    return True
                if os.path.isdir(path) and entry.startswith('checkpoint-'):
                    if any(f.endswith('.safetensors') for f in os.listdir(path)):
                        return True
        except OSError as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return False


_lora_unusable_logged: set = set()


def _zpub_char_lora_usable(cid: str, lora_dir: str, model_family: str = '') -> tuple[bool, str]:
    """2026-07-31: "LoRA ready?" must respect the OPERATOR, not just the disk.

    ``_zpub_char_lora_ready`` answers purely from ``.safetensors`` existence and
    ignores ``data/runtime/contact_sheet_<cid>.json`` — so a run the operator
    DECLINED (Abel: identity QC 0.194 against a 0.42 floor) still advertised
    itself as a trained, selectable character. Routes through
    ``character_lora_family.char_lora_usable`` (2026-07-31 contract) and falls
    back to the previous safetensors-only check whenever that helper is
    unavailable or raises.
    """
    if _ZPUB_LORA_USABLE_GATE:
        try:
            from zyg_workflows import character_lora_family as _clf_usable

            _fn = getattr(_clf_usable, 'char_lora_usable', None)
            if callable(_fn):
                ok, reason = _fn(cid, model_family or '', _CHAR_RUNTIME_DIR)
                return bool(ok), str(reason or '')
        except (ImportError, AttributeError, TypeError, ValueError) as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return _zpub_char_lora_ready(lora_dir), ''


def _zpub_char_is_medusa(cid: str) -> bool:
    """2026-07-31: Medusa (adults-only) chars are isolated to the Medusa app.

    ``list-contact-sheets`` already strips them on both paths; ``list-chars``
    stripped them on neither, and both libraries read the SAME directory.
    """
    if not _ZPUB_LIST_CHARS_MEDUSA_FILTER:
        return False
    try:
        return bool(is_medusa_char(cid))
    except Exception:
        return False


# Identity descriptors the main app's /api/internal/storyteller/list-chars
# returns (bp_storyteller.py:237-259). The local/fallback builder used to drop
# every one of them, and the wizard then back-filled the gaps with hardcoded
# female / brown / brown / medium / 1.70 / age-null defaults which were shipped
# to the pipeline as authoritative character_params.
def _zpub_identity_fields_from_bible(bible: dict) -> dict:
    """Return the same identity key set the main-app list-chars emits."""
    ident = (bible or {}).get('identity') or {}
    style = (bible or {}).get('style_profile') or {}
    pres = (bible or {}).get('default_presentation') or {}

    def _pres(key: str):
        return pres.get(key) or style.get(key) or ''

    return {
        'age': ident.get('age'),
        'age_range': ident.get('age_range', ''),
        'height': ident.get('height_m', 1.70),
        'skin_tone': ident.get('skin_tone') or 'medium',
        'hair_color': ident.get('hair_color', ''),
        'hair_style': ident.get('hair_style', ''),
        'hair_length': ident.get('hair_length', ''),
        'hair_texture': ident.get('hair_texture', ''),
        'eye_color': ident.get('eye_color', ''),
        'eye_shape': ident.get('eye_shape', ''),
        'eyebrow_style': ident.get('eyebrow_style', ''),
        'face_shape': ident.get('face_shape', ''),
        'nose_shape': ident.get('nose_shape', ''),
        'lip_shape': ident.get('lip_shape', ''),
        'facial_hair': ident.get('facial_hair', 'none'),
        'muscle_mass': ident.get('muscle_mass') or ident.get('body_build') or 20,
        'body_build': ident.get('body_build') or ident.get('muscle_mass') or '',
        'distinctive_marks': ident.get('distinctive_marks', ''),
        'ethnic_heritage': ident.get('ethnic_heritage', ''),
        'default_clothing': _pres('default_clothing'),
        'accessories': _pres('accessories'),
        'default_expression': _pres('default_expression'),
        'posture': _pres('posture'),
    }


def _zpub_char_preview_file(char_id: str, dataset_dir: str) -> str | None:
    # 2026-07-31: this was a third hand-rolled copy of the preview-candidate
    # order — monolithic-sheet-only, and blind to provenance, so it happily
    # returned a sweep-generated preview_flux_front.png as the character's
    # portrait. Delegate to the one implementation that knows about multi-part
    # sheets and the <slot>.meta.json sidecars.
    try:
        from zyg_workflows import contact_sheet_pipeline as _csp

        _fn = getattr(_csp, 'preview_file_for_library', None)
        if _fn is not None:
            return _fn(char_id, dataset_dir, None)
        if _csp.master_sheet_exists(char_id):
            return None
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    for pname in (
        'preview_flux_front.png',
        'preview_flux_face.png',
        'preview_sdxl_front.png',
        'contactsheet_00.png',
        'face_00_000deg.png',
        'full_00_000deg.png',
    ):
        if os.path.isfile(os.path.join(dataset_dir, pname)):
            return pname
    try:
        pngs = sorted(f for f in os.listdir(dataset_dir) if f.endswith('.png'))
        return pngs[0] if pngs else None
    except OSError:
        return None


def _zpub_char_trained_at(char_id: str, lora_dir: str) -> str:
    # 2026-07-31: char_gen_<cid>.json 'ended' is frequently a bp_metrics
    # backfill of the bible's updated_at, not a training timestamp — it was
    # ~27h off for c3345deb5bde and this value is the library sort key.
    # char_state_service resolves the true time (training_status completed_at /
    # completed LoRA stage / adapter mtime); fall back to the old chain.
    try:
        from zyg_workflows import char_state_service as _css_ta

        _fn = getattr(_css_ta, '_char_library_trained_at', None)
        if _fn is not None:
            _v = _fn(char_id)
            if _v:
                return str(_v)
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    state_path = os.path.join(_CHAR_RUNTIME_DIR, f'char_gen_{char_id}.json')
    try:
        if os.path.isfile(state_path):
            with open(state_path, encoding='utf-8') as fh:
                st = json.load(fh)
            return str(st.get('ended') or st.get('started') or '')
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    ts_path = os.path.join(lora_dir, 'training_status.json')
    try:
        if os.path.isfile(ts_path):
            with open(ts_path, encoding='utf-8') as fh:
                ts = json.load(fh)
            return str(ts.get('completed_at') or '')
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return ''


def _zpub_char_entry_from_disk(cid: str, model_family: str = '') -> dict | None:
    """Build one library card from on-disk LoRA + dataset (no main-app hop)."""
    # 2026-07-31: slug directories (e.g. 'abel_van_haren') were listed and
    # swept but BOTH image routes reject non-hex ids, so the row's preview and
    # contact-sheet URLs 404 forever and the card stays on the spinner that
    # re-arms the preview sweep on every load.
    if not _zpub_is_listable_char_id(cid):
        return None
    if _zpub_char_is_medusa(cid):
        return None
    dataset_dir = os.path.join(_DATASET_ROOT, cid)
    lora_dir = os.path.join(_LORA_OUTPUT_ROOT, cid)
    if not os.path.isdir(dataset_dir):
        return None
    _usable, _usable_reason = _zpub_char_lora_usable(cid, lora_dir, model_family)
    if not _usable:
        # Log once per (char, reason) per process — list-chars is polled every
        # 12 s while previews are pending, so an unconditional log would flood.
        _key = (cid, str(_usable_reason)[:80])
        if _usable_reason and _key not in _lora_unusable_logged:
            _lora_unusable_logged.add(_key)
            _zpub_log('char_lora_unusable', char_id=cid, reason=_key[1])
        return None
    try:
        from zyg_workflows import character_lora_family as _clf

        lora_families = _clf.char_lora_families_for_dir(lora_dir)
    except Exception:
        lora_families = []
    mf = (model_family or '').strip().lower()
    if mf in ('flux', 'sdxl'):
        if lora_families and mf not in lora_families:
            return None
        if not lora_families:
            try:
                from zyg_workflows import character_lora_family as _clf2

                if not _clf2.char_lora_ready_for_family(lora_dir, mf):
                    return None
            except Exception:
                return None
    try:
        from zyg_workflows import character_bible_service as _cbs
    except Exception:
        _cbs = None
    bible = (_cbs.load(cid) or {}) if _cbs else {}
    ident = bible.get('identity') or {}
    style = bible.get('style_profile') or {}
    full_name = bible.get('display_name') or ''
    if not full_name:
        state_path = os.path.join(_CHAR_RUNTIME_DIR, f'char_gen_{cid}.json')
        try:
            if os.path.isfile(state_path):
                with open(state_path, encoding='utf-8') as fh:
                    st = json.load(fh)
                full_name = (st.get('params') or {}).get('name') or ''
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    lib_label = _cbs.format_library_label(full_name) if _cbs else (full_name or cid[:8])
    meta = {}
    try:
        with open(os.path.join(dataset_dir, 'manifest.json'), encoding='utf-8') as mf:
            meta = json.load(mf)
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    preview_urls = {'preview_url': None, 'contact_sheet_url': None}
    try:
        from zyg_workflows import contact_sheet_pipeline as _csp

        preview_urls = _csp.library_preview_urls(cid, dataset_dir, meta)
    except Exception:
        preview = _zpub_char_preview_file(cid, dataset_dir)
        if preview:
            preview_urls['preview_url'] = f'/api/storyteller/char-image/{cid}/{preview}'
    if not preview_urls.get('preview_url'):
        preview = _zpub_char_preview_file(cid, dataset_dir)
        if preview:
            preview_urls['preview_url'] = f'/api/storyteller/char-image/{cid}/{preview}'
    primary_mf = mf if mf in ('flux', 'sdxl') else (lora_families[0] if lora_families else 'flux')
    is_cs = meta.get('source') == 'contact_sheet' or meta.get('render_mode') == 'contact_sheet'
    try:
        from zyg_workflows import contact_sheet_pipeline as _csp2

        is_cs = is_cs or _csp2.is_contact_sheet_char(cid, meta)
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    entry = {
        'char_id': cid,
        'name': full_name,
        'library_label': lib_label,
        'trigger_token': bible.get('trigger_token') or f'ZYG_CHAR_{cid[:6].upper()}',
        'gender': ident.get('gender') or 'unknown',
        'lora_ready': True,
        'model_family': primary_mf,
        'lora_families': lora_families or [primary_mf],
        'preview_url': preview_urls.get('preview_url'),
        'contact_sheet_url': preview_urls.get('contact_sheet_url'),
        'source': meta.get('source') or ('contact_sheet' if is_cs else 'character'),
        'render_mode': meta.get('render_mode') or '',
        'creation_pipeline': 'multi_angle_contact_sheet' if is_cs else 'character_creation',
        'trained_at': _zpub_char_trained_at(cid, lora_dir),
        'style': style.get('render_style') or 'photorealistic',
        'genre': style.get('genre') or 'general',
    }
    # 2026-07-31: emit the SAME 22 identity descriptors the main app's
    # list-chars returns. This row used to carry 16 keys and drop every
    # descriptor, so the wizard's Object.assign back-filled the gaps with
    # hardcoded female / brown / brown / medium / 1.70 / age-null constants and
    # submitted them as authoritative character_params — a 12-year-old, 1.52 m,
    # fair-skinned boy became a 1.70 m brown-eyed adult woman in the script.
    if _ZPUB_LIB_IDENTITY:
        try:
            entry.update(_zpub_identity_fields_from_bible(bible))
        except Exception as _ident_exc:
            _zpub_log('char_identity_fields_fail', char_id=cid, error=str(_ident_exc)[:120])
    return entry


def _zpub_list_chars_local(model_family: str = '') -> list:
    """Full character library from disk (used when main app proxy fails)."""
    all_ids: set[str] = set()
    for root in (_LORA_OUTPUT_ROOT, _DATASET_ROOT):
        if os.path.isdir(root):
            try:
                all_ids.update(os.listdir(root))
            except OSError as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    chars: list[dict] = []
    for cid in sorted(all_ids):
        # 2026-07-31: skip non-hex slug dirs before the (costlier) build.
        if not _zpub_is_listable_char_id(cid):
            continue
        entry = _zpub_char_entry_from_disk(cid, model_family)
        if entry:
            chars.append(entry)
    chars.sort(key=lambda c: c.get('trained_at') or '', reverse=True)
    return chars


def _zpub_supplement_list_chars(main_chars: list, model_family: str = '') -> list:
    """Add LoRA-ready chars missing from main-app list (e.g. lora-weights-flux only)."""
    known = {c.get('char_id') for c in main_chars if c.get('char_id')}
    extra: list[dict] = []
    all_ids: set[str] = set()
    for root in (_LORA_OUTPUT_ROOT, _DATASET_ROOT):
        if os.path.isdir(root):
            try:
                all_ids.update(os.listdir(root))
            except OSError as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    for cid in all_ids:
        # 2026-07-31: skip non-hex slug dirs before the (costlier) build.
        if cid in known or not _zpub_is_listable_char_id(cid):
            continue
        entry = _zpub_char_entry_from_disk(cid, model_family)
        if entry:
            extra.append(entry)
    merged = main_chars + extra
    merged.sort(key=lambda c: c.get('trained_at') or '', reverse=True)
    return merged


@bp.route('/api/storyteller/list-chars')
@limiter.limit('30 per minute')
def api_storyteller_list_chars():
    """List trained LoRA characters — main app when available, always merged with local disk."""
    blocked = _zpub_story_gate()  # 2026-07-31: anonymous callers could enumerate
    if blocked:  # the full private roster (names, ids, triggers)
        return blocked
    _mf = (request.args.get('model_family') or '').strip().lower()
    if _mf not in ('flux', 'sdxl'):
        _mf = ''
    _params = {'model_family': _mf} if _mf else {}
    chars: list[dict] = []
    _source = 'local'
    try:
        resp = _requests.get(
            f'{MAIN_APP_URL}/api/internal/storyteller/list-chars',
            headers=_int_headers(),
            params=_params,
            timeout=12,
        )
        _ctype = (resp.headers.get('content-type') or '').lower()
        if resp.ok and 'json' in _ctype:
            payload = resp.json()
            chars = payload.get('chars') or []
            _source = 'main+local'
        else:
            _zpub_log(
                'list_chars_non_json',
                status=resp.status_code,
                ctype=_ctype[:60],
            )
    except Exception as _proxy_exc:
        _zpub_log('list_chars_proxy_fail', error=str(_proxy_exc)[:120])

    chars = _zpub_supplement_list_chars(chars, model_family=_mf)
    if not chars:
        chars = _zpub_list_chars_local(_mf)
        _source = 'local'

    # 2026-07-31: post-merge hygiene on the PROXY rows too (the local builder
    # already applies all three). list-contact-sheets filtered Medusa on both
    # paths; list-chars filtered on neither, and both read the same directory.
    if _ZPUB_LIST_CHARS_MEDUSA_FILTER:
        try:
            chars = filter_out_medusa(chars)  # fail-safe: returns input on error
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    if _ZPUB_HEX_CHARID_ONLY:
        chars = [c for c in chars if _zpub_is_listable_char_id((c or {}).get('char_id') or '')]
    if _ZPUB_LORA_USABLE_GATE:
        # A DECLINED / QC-failed contact-sheet run must not advertise as trained
        # no matter which path produced the row.
        _kept: list[dict] = []
        for c in chars:
            _cid = (c or {}).get('char_id') or ''
            _ok, _why = _zpub_char_lora_usable(
                _cid,
                os.path.join(_LORA_OUTPUT_ROOT, _cid),
                _mf,
            )
            if _ok:
                _kept.append(c)
                continue
            _k = (_cid, str(_why)[:80])
            if _why and _k not in _lora_unusable_logged:
                _lora_unusable_logged.add(_k)
                _zpub_log('char_lora_unusable', char_id=_cid, reason=_k[1], path='list_chars')
        chars = _kept
    return jsonify({'chars': chars, 'count': len(chars), 'source': _source})
