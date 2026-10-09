# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401
# F401: the original module-level import block is reproduced verbatim in every
# section module, both so `pkg.os` / `pkg.json` style attribute access keeps
# resolving and so the function-local `import re as _re` imports in the moved
# bodies compile exactly as they did in the single file.

"""Identity authority (the bible wins) and voice validation / resolution.

Moved verbatim out of zpub_routes_storyteller.py (lines 1451-1868).
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
from zyg_zero.zpub_config import AVG_PIPELINE_SECONDS, MAIN_APP_URL, _ams_iso, public_url
from zyg_zero.zpub_gate import _client_ip, _require_api_session, _session_id, _session_invite, limiter
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

from zyg_zero.zpub_routes_storyteller.base import _ZPUB_BIBLE_IDENTITY, _ZPUB_VOICE_VALIDATE, _ZpubJobRejected
from zyg_zero.zpub_routes_storyteller.char_library import _DATASET_ROOT

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_zero.zpub_routes_storyteller')

# ══════════════════════════════════════════════════════════════════════════════
# 2026-07-31 — IDENTITY AUTHORITY
# character_params used to be a verbatim, unvalidated echo of the public request
# body, frozen at page-load time, and pipeline_storyteller.py consumed it as the
# authoritative character description AND voice selector. A caller (or a stale
# browser default) could submit char_id=<12-year-old boy> with
# {'gender':'female','hair_color':'brown','age':None} and the screenwriter would
# write a brown-haired adult woman while the LoRA rendered a boy. The bible on
# disk is the record of who the trained character actually is, so it wins.
# ══════════════════════════════════════════════════════════════════════════════
_IDENTITY_AUTHORITY_FIELDS = (
    'gender',
    'age',
    'age_range',
    'height',
    'skin_tone',
    'hair_color',
    'hair_style',
    'hair_length',
    'hair_texture',
    'eye_color',
    'eye_shape',
    'eyebrow_style',
    'face_shape',
    'nose_shape',
    'lip_shape',
    'facial_hair',
    'muscle_mass',
    'body_build',
    'distinctive_marks',
    'ethnic_heritage',
    'default_clothing',
    'accessories',
    'default_expression',
    'posture',
    'style',
    'render_style',
    'genre',
)


def _zpub_bible_identity_params(cid: str) -> dict:
    """Rebuild the identity half of character_params from the on-disk bible.

    Mirrors ``char_state_service._char_params_from_bible`` (which cannot be
    imported here — it pulls in crewai_web_gui). Returns {} when no bible is
    available so the caller can degrade to the previous behaviour.
    """
    try:
        from zyg_workflows import character_bible_service as _cbs_id
    except Exception:
        return {}
    try:
        pkg = _cbs_id.load(cid) or {}
    except Exception:
        return {}
    if not pkg:
        return {}
    ident = pkg.get('identity') or {}
    style = pkg.get('style_profile') or {}
    pres = pkg.get('default_presentation') or {}

    def _pres(key: str):
        return pres.get(key) or style.get(key) or ''

    params = {
        'gender': ident.get('gender'),
        'age': ident.get('age'),
        'age_range': ident.get('age_range'),
        'height': ident.get('height_m'),
        'skin_tone': ident.get('skin_tone'),
        'hair_color': ident.get('hair_color'),
        'hair_style': ident.get('hair_style'),
        'hair_length': ident.get('hair_length'),
        'hair_texture': ident.get('hair_texture'),
        'eye_color': ident.get('eye_color'),
        'eye_shape': ident.get('eye_shape'),
        'eyebrow_style': ident.get('eyebrow_style'),
        'face_shape': ident.get('face_shape'),
        'nose_shape': ident.get('nose_shape'),
        'lip_shape': ident.get('lip_shape'),
        'facial_hair': ident.get('facial_hair'),
        'muscle_mass': ident.get('muscle_mass') or ident.get('body_build'),
        'body_build': ident.get('body_build') or ident.get('muscle_mass'),
        'distinctive_marks': ident.get('distinctive_marks'),
        'ethnic_heritage': ident.get('ethnic_heritage'),
        'default_clothing': _pres('default_clothing'),
        'accessories': _pres('accessories'),
        'default_expression': _pres('default_expression'),
        'posture': _pres('posture'),
        'style': style.get('render_style'),
        'render_style': style.get('render_style'),
        'genre': style.get('genre'),
    }
    # Only keep the fields the bible actually has an opinion on.
    params = {k: v for k, v in params.items() if v not in ('', None)}
    # Complete any older-schema gaps with the SAME auto-default engine the main
    # app uses (seeded per char_id, so explicit values are honoured verbatim and
    # repeated calls always agree).
    try:
        filled = _cbs_id.apply_auto_defaults(dict(params), seed_key=cid) or {}
        for key in _IDENTITY_AUTHORITY_FIELDS:
            if key not in params and filled.get(key) not in ('', None):
                params[key] = filled[key]
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return params


def _zpub_char_render_mode(cid: str) -> str:
    """render_mode from the character's on-disk manifest (never the client).

    A client-supplied ``character_params.render_mode='blender'`` made
    ``_char_is_blender_dataset`` true at pipeline_storyteller.py:317, which
    NULLS char_reference_image and drops IPAdapter conditioning for a character
    that needs it.
    """
    try:
        with open(os.path.join(_DATASET_ROOT, cid, 'manifest.json'), encoding='utf-8') as _mfh:
            meta = json.load(_mfh)
        return str(meta.get('render_mode') or '').strip()
    except Exception:
        return ''


def _zpub_apply_identity_authority(char_id: str, client_params: dict) -> tuple[dict, dict]:
    """Return (character_params, identity) with the bible winning every
    contested identity field. ``identity`` is the SERVER-side {gender, age}
    used for voice validation."""
    params = dict(client_params or {})
    identity = {
        'gender': str(params.get('gender') or '').strip().lower(),
        'age': params.get('age'),
    }
    if not _ZPUB_BIBLE_IDENTITY or not char_id:
        return params, identity

    bible_params = _zpub_bible_identity_params(char_id)
    if not bible_params:
        _zpub_log('storyteller_identity_bible_missing', char_id=char_id[:12], ip=_client_ip())
        # Still refuse to trust a client render_mode.
        rm = _zpub_char_render_mode(char_id)
        if rm or 'render_mode' in params:
            params['render_mode'] = rm
        return params, identity

    disagreements: list[dict] = []
    for key in _IDENTITY_AUTHORITY_FIELDS:
        if key not in bible_params:
            continue  # bible has no opinion → keep whatever the client sent
        was = params.get(key)
        now = bible_params[key]
        if key in params and str(was).strip().lower() != str(now).strip().lower():
            disagreements.append(
                {
                    'field': key,
                    'client': str(was)[:40],
                    'bible': str(now)[:40],
                }
            )
        params[key] = now

    # render_mode is read from disk, never from the request body.
    rm = _zpub_char_render_mode(char_id)
    if str(params.get('render_mode') or '').strip() != rm:
        disagreements.append(
            {
                'field': 'render_mode',
                'client': str(params.get('render_mode') or '')[:40],
                'bible': rm[:40],
            }
        )
    params['render_mode'] = rm

    identity = {
        'gender': str(params.get('gender') or '').strip().lower(),
        'age': params.get('age'),
    }
    if disagreements:
        _zpub_log(
            'storyteller_identity_overridden',
            ip=_client_ip(),
            char_id=char_id[:12],
            count=len(disagreements),
            fields=disagreements[:30],
        )
    return params, identity


# ══════════════════════════════════════════════════════════════════════════════
# 2026-07-31 — VOICE VALIDATION
# narrator_voice / character_voice were free-form strings forwarded unchecked to
# TTS: an arbitrary id silently degraded to a random-gender seed pick and then
# a hard Azure failure at the END of a full render, and nothing could flag
# en-US-BrianNeural (adult narrator) being assigned to a 12-year-old boy because
# the catalog's age_min/age_max fields were consulted by nothing.
# ══════════════════════════════════════════════════════════════════════════════
_MINOR_AGE = 18


def _zpub_as_int(value, default=None):
    try:
        if value is None or value == '':
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _zpub_voice_index() -> dict:
    """``{voice_id: {gender, age_min, age_max, narrator}}`` — {} when unavailable."""
    try:
        from zyg_workflows import storyteller_voice_catalog as _svc
    except Exception:
        return {}
    index: dict[str, dict] = {}
    try:
        rows = _svc.list_storyteller_voices(kind='character') or []
    except Exception:
        rows = []
    for row in rows:
        vid = (row or {}).get('id')
        if not vid:
            continue
        index[vid] = {
            'gender': str(row.get('gender') or '').strip().lower(),
            'age_min': _zpub_as_int(row.get('age_min'), 0),
            'age_max': _zpub_as_int(row.get('age_max'), 120),
            'narrator': False,
        }
    if not index:
        # Membership-only fallback: still rejects invented voice ids.
        try:
            for vid in _svc.all_voice_ids() or set():
                index[vid] = {'gender': '', 'age_min': 0, 'age_max': 120, 'narrator': True}
        except Exception:
            return {}
    try:
        for row in _svc.list_storyteller_voices(kind='narrator') or []:
            vid = (row or {}).get('id')
            if vid in index:
                index[vid]['narrator'] = True
    except Exception:
        for meta in index.values():
            meta['narrator'] = True

    # Contract (2026-07-31, parallel change): prefer the catalog's own clean
    # id→gender map / age-band accessor when it exports them.
    for _gname in ('voice_gender_map', 'all_voice_genders', 'voice_genders'):
        _gfn = getattr(_svc, _gname, None)
        if callable(_gfn):
            try:
                for vid, gender in (_gfn() or {}).items():
                    if vid in index and gender:
                        index[vid]['gender'] = str(gender).strip().lower()
                break
            except Exception as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    _bfn = getattr(_svc, 'voice_age_band', None)
    if callable(_bfn):
        for vid, meta in index.items():
            try:
                band = _bfn(vid)
            except Exception as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
                continue
            if band and len(band) == 2:
                meta['age_min'] = _zpub_as_int(band[0], meta['age_min'])
                meta['age_max'] = _zpub_as_int(band[1], meta['age_max'])
    return index


def _zpub_voice_fits(meta: dict, gender: str, age, *, strict_minor: bool) -> bool:
    """True when a catalog row is compatible with the server-side identity."""
    if gender in ('male', 'female'):
        vg = meta.get('gender') or ''
        if vg in ('male', 'female') and vg != gender:
            return False
    if age is not None:
        if not (meta['age_min'] <= age <= meta['age_max']):
            return False
        # A catch-all 0-120 band (the narrator escape hatch) is NOT an
        # age-appropriate CHARACTER voice for a minor — that is exactly how
        # en-US-BrianNeural ended up voicing a 12-year-old boy.
        if strict_minor and age < _MINOR_AGE and meta['age_max'] >= _MINOR_AGE:
            return False
    return True


def _zpub_pick_voice(index: dict, gender: str, age, *, narrator_only: bool, strict_minor: bool) -> str:
    """Deterministic best-fit voice: narrowest (most specific) age band wins."""
    candidates = []
    for vid, meta in index.items():
        if narrator_only and not meta.get('narrator'):
            continue
        if not _zpub_voice_fits(meta, gender, age, strict_minor=strict_minor):
            continue
        candidates.append((meta['age_max'] - meta['age_min'], vid))
    if not candidates:
        return ''
    candidates.sort()
    return candidates[0][1]


def _zpub_resolve_voices(narrator_voice: str, character_voice: str, identity: dict, char_id: str) -> tuple[str, str]:
    """Validate/repair the submitted TTS voices against the catalog + bible.

    Unknown ids are rejected (``_ZpubJobRejected`` → 400). A voice whose catalog
    gender contradicts the bible gender, or whose [age_min, age_max] band
    excludes the bible age, is auto-corrected and logged.
    """
    if not _ZPUB_VOICE_VALIDATE:
        return narrator_voice, character_voice
    index = _zpub_voice_index()
    if not index:
        _zpub_log('voice_catalog_unavailable', ip=_client_ip(), char_id=(char_id or '')[:12])
        return narrator_voice, character_voice  # degrade to previous behaviour

    for label, vid in (('narrator_voice', narrator_voice), ('character_voice', character_voice)):
        if vid and vid not in index:
            _zpub_log(
                'voice_rejected_unknown',
                ip=_client_ip(),
                char_id=(char_id or '')[:12],
                field=label,
                voice=str(vid)[:60],
            )
            raise _ZpubJobRejected(
                f'Unknown {label.replace("_", " ")} "{str(vid)[:60]}" — pick a voice from the catalog.'
            )

    gender = str((identity or {}).get('gender') or '').strip().lower()
    age = _zpub_as_int((identity or {}).get('age'), None)

    def _substitute(field: str, current: str, replacement: str, reason: str) -> str:
        if not replacement or replacement == current:
            _zpub_log(
                'voice_mismatch_unresolved',
                ip=_client_ip(),
                char_id=(char_id or '')[:12],
                field=field,
                voice=current,
                reason=reason,
                identity_gender=gender,
                identity_age=age,
            )
            return current
        _zpub_log(
            'voice_substituted',
            ip=_client_ip(),
            char_id=(char_id or '')[:12],
            field=field,
            was=current,
            now=replacement,
            reason=reason,
            identity_gender=gender,
            identity_age=age,
        )
        return replacement

    # ── Narrator: the STORYTELLER, not the character. Must exist in the
    #    catalog and be narrator-eligible (adult / explicitly narrator-tagged).
    #    Deliberately NOT gender/age-matched to the character — a female
    #    narrator for a male character is a legitimate creative choice.
    if narrator_voice and not index[narrator_voice].get('narrator'):
        narrator_voice = _substitute(
            'narrator_voice',
            narrator_voice,
            _zpub_pick_voice(
                index, index[narrator_voice].get('gender') or '', None, narrator_only=True, strict_minor=False
            )
            or _zpub_pick_voice(index, '', None, narrator_only=True, strict_minor=False),
            'not_narrator_eligible',
        )

    # ── Character voice: this one speaks AS the character, so it must match the
    #    bible's gender and age band (and a minor needs a real child voice).
    if character_voice:
        meta = index[character_voice]
        if not _zpub_voice_fits(meta, gender, age, strict_minor=True):
            reason = []
            if gender in ('male', 'female') and meta.get('gender') in ('male', 'female') and meta['gender'] != gender:
                reason.append(f'gender_{meta["gender"]}_vs_{gender}')
            if age is not None and not (meta['age_min'] <= age <= meta['age_max']):
                reason.append(f'age_{age}_outside_{meta["age_min"]}_{meta["age_max"]}')
            elif age is not None and age < _MINOR_AGE and meta['age_max'] >= _MINOR_AGE:
                reason.append(f'adult_band_for_minor_age_{age}')
            character_voice = _substitute(
                'character_voice',
                character_voice,
                _zpub_pick_voice(index, gender, age, narrator_only=False, strict_minor=True)
                or _zpub_pick_voice(index, gender, age, narrator_only=False, strict_minor=False),
                ','.join(reason) or 'identity_mismatch',
            )
    return narrator_voice, character_voice


def _zpub_precheck_voice_ids(data: dict):
    """Reject unknown voice ids BEFORE the invite quota is consumed.

    ``_zpub_resolve_voices`` is the authority (it runs inside the shared job
    builder, so the parked-approval path is covered too), but membership is the
    only condition that can hard-reject — checking it up front means a typo'd
    voice costs a 400 rather than one of the invite's requests.
    """
    if not _ZPUB_VOICE_VALIDATE:
        return None
    index = _zpub_voice_index()
    if not index:
        return None
    for label in ('narrator_voice', 'character_voice'):
        vid = (data.get(label) or '').strip()
        if vid and vid not in index:
            _zpub_log('voice_rejected_unknown', ip=_client_ip(), field=label, voice=str(vid)[:60], phase='precheck')
            return jsonify(
                {'error': f'Unknown {label.replace("_", " ")} "{str(vid)[:60]}" — pick a voice from the catalog.'}
            ), 400
    return None
