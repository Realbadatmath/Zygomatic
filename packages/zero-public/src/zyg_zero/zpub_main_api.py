# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 by the GUI modularization (split out of zero_public_server.py).
# Source line refs: crews_modularization_backups_20260717/originals/zero_public_server.py

import json
import requests as _requests
from zyg_zero.zpub_config import INTERNAL_TOKEN, MAIN_APP_URL
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# ── Helpers: call main app internal API ───────────────────────────────────────


def _int_headers() -> dict:
    return {
        'X-Zero-Public-Token': INTERNAL_TOKEN,
        'Content-Type': 'application/json',
    }


def _token_check(token: str) -> dict:
    """
    Check a token without consuming it.
    Returns {'valid': bool, 'reason': str, 'entry': dict|None}
    """
    try:
        resp = _requests.get(
            f'{MAIN_APP_URL}/api/zero_public/token_check/{token}',
            headers=_int_headers(),
            timeout=8,
        )
        return resp.json()
    except Exception:
        return {'valid': False, 'reason': 'main_app_unreachable', 'entry': None}


def _token_use(token: str) -> dict:
    """
    Atomically increment a token's used_requests counter.
    Returns {'ok': bool, 'reason': str, 'entry': dict|None}
    """
    try:
        resp = _requests.post(
            f'{MAIN_APP_URL}/api/zero_public/token_use/{token}',
            headers=_int_headers(),
            timeout=8,
        )
        return resp.json()
    except Exception:
        return {'ok': False, 'reason': 'main_app_unreachable', 'entry': None}


def _classify_prompt(prompt: str) -> str:
    """Ask the main app to classify the pipeline type, or fall back locally."""
    if INTERNAL_TOKEN:
        try:
            resp = _requests.post(
                f'{MAIN_APP_URL}/api/internal/zero/classify',
                json={'prompt': prompt},
                headers=_int_headers(),
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get('pipeline_type', 'scholarly')
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    # Local fallback
    crime_kw = [
        'crime',
        'murder',
        'killer',
        'criminal',
        'court',
        'trial',
        'conviction',
        'serial killer',
        'true crime',
        'robbery',
        'assault',
        'fraud',
        'detective',
        'homicide',
        'victim',
        'suspect',
    ]
    return 'crime' if any(k in prompt.lower() for k in crime_kw) else 'scholarly'


def _parse_model_family(raw) -> str:
    mf = (raw or '').strip().lower()
    return mf if mf in ('flux', 'sdxl') else 'flux'


def _parse_creature_options(raw) -> dict:
    """Creature workflow options (2026-08-25): source reference|scratch,
    angles standard|compact, review_gate bool. Accepts a dict or a JSON string."""
    if isinstance(raw, dict):
        po = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            po = json.loads(raw)
        except Exception:
            po = {}
    else:
        po = {}
    if not isinstance(po, dict):
        po = {}
    src = str(po.get('source') or '').strip().lower()
    src = (
        'scratch'
        if src in ('scratch', 'text', 'from_scratch')
        else ('reference' if src in ('reference', 'ref', 'image', 'images') else '')
    )
    ang = str(po.get('angles') or 'standard').strip().lower()
    rg = po.get('review_gate', True)
    return {
        'source': src,
        'angles': ang if ang in ('standard', 'compact') else 'standard',
        'review_gate': rg if isinstance(rg, bool) else str(rg).strip().lower() not in ('0', 'false', 'no', 'off'),
    }


def _parse_pipeline_options(raw) -> dict:
    if isinstance(raw, dict):
        po = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            po = json.loads(raw)
        except Exception:
            po = {}
    else:
        po = {}
    if not isinstance(po, dict):
        po = {}

    def _as_bool(v, default: bool) -> bool:
        if isinstance(v, bool):
            return v
        if v is None:
            return default
        return str(v).strip().lower() not in ('false', '0', 'no', 'off')

    out = {
        'enable_bgm': _as_bool(po.get('enable_bgm'), True),
        'burn_subtitles': _as_bool(po.get('burn_subtitles'), True),
        'enable_watermark': _as_bool(po.get('enable_watermark'), False),
    }
    try:
        sc = int(po.get('scene_count') or 0)
        if sc > 0:
            out['scene_count'] = max(1, min(12, sc))
    except (TypeError, ValueError) as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    try:
        td = float(po.get('total_duration_sec') or 0)
        if td > 0:
            out['total_duration_sec'] = max(3.5, min(1800.0, td))
    except (TypeError, ValueError) as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    try:
        sds = float(po.get('scene_duration_sec') or 0)
        if sds > 0:
            out['scene_duration_sec'] = max(3.5, min(20.0, sds))
    except (TypeError, ValueError) as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    try:
        mpf = int(po.get('manga_panel_fps') or 0)
        if mpf > 0:
            out['manga_panel_fps'] = max(1, min(30, mpf))
    except (TypeError, ValueError) as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return out


def _start_pipeline(
    pipeline_type: str,
    directive: str,
    image_paths: list | None = None,
    video_duration_minutes: int = 1,
    narration_enabled: bool = True,
    visual_style: str = 'cinematic',
    scene_mode: str = 'independent',
    ending_text: str = '',
    storyteller_params: dict | None = None,
    model_family: str = 'flux',
    pipeline_options: dict | None = None,
    char_id: str = '',
    creature_options: dict | None = None,
) -> str | None:
    """Ask the main app to start a pipeline. Returns pipeline_id or None."""
    try:
        payload = {'pipeline_type': pipeline_type, 'directive': directive, 'narration_enabled': narration_enabled}
        payload['model_family'] = _parse_model_family(model_family)
        payload['pipeline_options'] = _parse_pipeline_options(pipeline_options)
        _cid = (char_id or '').strip()
        if _cid:
            payload['char_id'] = _cid
        if image_paths:
            payload['image_paths'] = image_paths
        if pipeline_type in ('video', 'intro', 'manga'):
            payload['video_duration_minutes'] = video_duration_minutes
            payload['visual_style'] = visual_style
            payload['scene_mode'] = scene_mode
            if ending_text:
                payload['ending_text'] = ending_text
        if pipeline_type == 'creature':
            payload['visual_style'] = visual_style
            payload['creature_options'] = _parse_creature_options(creature_options)
        if pipeline_type == 'manga':
            payload['visual_style'] = 'manga'
        if pipeline_type == 'storyteller':
            payload['visual_style'] = visual_style
            if storyteller_params:
                payload['storyteller_params'] = storyteller_params
        resp = _requests.post(
            f'{MAIN_APP_URL}/api/internal/pipeline/start',
            json=payload,
            headers=_int_headers(),
            timeout=20,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get('job_id') or data.get('pipeline_id')
        if resp.status_code == 400:
            try:
                data = resp.json()
                err = (data.get('error') or 'Pipeline rejected').strip()
            except Exception:
                err = 'Pipeline rejected'
            _zyg_log.info(f'[ZeroPub] Pipeline start rejected: {err[:200]}')
            return f'__rejected__:{err}'
        if resp.status_code == 409:
            # Main app reports a pipeline is already running — retry in 30 s
            _zyg_log.info('[ZeroPub] Main app busy (409); will retry')
            return None
    except Exception as e:
        _zyg_log.info(f'[ZeroPub] _start_pipeline error: {e}')
    return None


def _get_pipeline_status(pipeline_id: str) -> dict:
    try:
        resp = _requests.get(
            f'{MAIN_APP_URL}/api/internal/pipeline/status/{pipeline_id}',
            headers=_int_headers(),
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return {}
