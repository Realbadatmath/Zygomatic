# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The three functions that are only meaningful against RACKS.

Moved verbatim (lines 3800-3850 of the old single-file spec.py): the _PARAMS
index, defaults(), sanitize() — which clamps whatever a caller sends — and
nondefault().
"""

import json

from .racks import RACKS

_PARAMS = {p['key']: p for r in RACKS for p in r['params']}


def defaults() -> dict:
    return {k: p['def'] for k, p in _PARAMS.items()}


def sanitize(params: dict) -> dict:
    """Clamp/coerce a caller-supplied dict onto the spec — unknown keys dropped,
    missing keys take their default, same contract as voice_studio.sanitize().

    Select membership is compared as strings: an HTML <select> always posts its
    value as text, so a numeric option (duration_s: 7.0) would otherwise never
    match and silently fall back to its default."""
    out = defaults()
    for k, v in (params or {}).items():
        spec = _PARAMS.get(k)
        if not spec:
            continue
        t = spec['type']
        try:
            if t == 'select':
                match = next((o['v'] for o in spec['options'] if str(o['v']) == str(v)), None)
                out[k] = spec['def'] if match is None else match
            elif t == 'toggle':
                out[k] = bool(v) if not isinstance(v, str) else v.strip().lower() not in ('0', 'false', 'no', 'off', '')
            elif t == 'int':
                out[k] = int(max(spec['min'], min(spec['max'], int(float(v)))))
            elif t == 'text':
                out[k] = str(v or '')[:600]
            elif t == 'longtext':
                out[k] = str(v or '')[:6000]
            elif t == 'json':
                s = str(v or '')[:20000]
                try:
                    json.loads(s)
                except (TypeError, ValueError):
                    s = spec['def']
                out[k] = s
            else:
                out[k] = float(max(spec['min'], min(spec['max'], float(v))))
        except (TypeError, ValueError):
            out[k] = spec['def']
    return out


def nondefault(params: dict) -> dict:
    """Only the keys a caller moved off their default — what the GUI marks with
    a dot on the icon, and what a preset is worth storing."""
    d = defaults()
    return {k: v for k, v in (params or {}).items() if k in d and str(v) != str(d[k])}
