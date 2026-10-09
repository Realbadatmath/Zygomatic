# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""data/runtime/analytics_config.json — the stated assumptions, loaded and merged."""

from __future__ import annotations

import json
import os
from zyg_dashboard import metrics_hub as mh

from .constants import CONFIG_PATH, DEFAULT_CONFIG, RUNTIME, _zyg_log


# ── config ───────────────────────────────────────────────────────────────────


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        saved = mh._read_json(CONFIG_PATH)
        if isinstance(saved, dict):
            cfg.update({k: v for k, v in saved.items() if k in DEFAULT_CONFIG})
    except Exception as _exc:
        _zyg_log.warning('analytics config load failed, using built-in defaults: %s', _exc)
    if not cfg.get('eur_per_usd'):
        try:
            q = mh._read_json(os.path.join(RUNTIME, 'quota_config.json'))
            cfg['eur_per_usd'] = float(q.get('eur_per_usd') or 0.92)
        except Exception:
            cfg['eur_per_usd'] = 0.92
    cfg['views_per_content'] = max(0, int(cfg['views_per_content'] or 0))
    cfg['rpm_usd'] = max(0.0, float(cfg['rpm_usd'] or 0))
    cfg['kwh_price_eur'] = max(0.0, float(cfg['kwh_price_eur'] or 0))
    cfg['active_hours_per_day'] = max(1.0, min(24.0, float(cfg['active_hours_per_day'] or 24)))
    cfg['rpm_scenarios'] = sorted(
        {round(float(x), 2) for x in (cfg.get('rpm_scenarios') or []) if float(x) >= 0} | {cfg['rpm_usd']}
    )[:8]
    return cfg


def save_config(updates: dict):
    """Persist operator assumptions. Only known keys, numeric, bounded. Returns the merged config."""
    cur = {}
    try:
        cur = mh._read_json(CONFIG_PATH) or {}
    except Exception as _exc:
        _zyg_log.warning('stored analytics config unreadable, merging updates into an empty one: %s', _exc)
    for k, v in (updates or {}).items():
        if k not in DEFAULT_CONFIG:
            continue
        if k == 'rpm_scenarios':
            if isinstance(v, list):
                cur[k] = [float(x) for x in v if isinstance(x, (int, float)) and 0 <= float(x) <= 1000][:8]
            continue
        try:
            cur[k] = float(v)
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('ignoring non-numeric config update for %s: %s', k, _exc)
            continue
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp = CONFIG_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(cur, fh, indent=1)
    os.replace(tmp, CONFIG_PATH)
    return load_config()
