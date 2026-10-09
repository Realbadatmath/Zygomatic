# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Day keys, bucketing, medians, the OLS forecast and the delta helper."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from zyg_dashboard import metrics_hub as mh

from .constants import HORIZON_DAYS, TZ


# ── small helpers ────────────────────────────────────────────────────────────


def _day(ts):
    return datetime.fromtimestamp(ts, TZ).date()


def _daykey(ts):
    return _day(ts).isoformat()


def _r(v, d=2):
    return None if v is None else round(v, d)


def _median(v):
    return mh._pct(v, 0.5)


def _week_start(d):
    return d - timedelta(days=d.weekday())


def _daily_keys(now, n):
    end = _day(now)
    return [(end - timedelta(days=n - 1 - i)).isoformat() for i in range(n)]


def _bucket_series(daily: dict, keys, weekly, agg='sum'):
    """daily: {daykey: number} -> list aligned with the hub's bucket keys."""
    out = [0.0] * len(keys)
    cnt = [0] * len(keys)
    idx = {k: i for i, k in enumerate(keys)}
    for dk, v in daily.items():
        if v is None:
            continue
        d = datetime.fromisoformat(dk).date()
        bk = (_week_start(d) if weekly else d).isoformat()
        i = idx.get(bk)
        if i is None:
            continue
        out[i] += v
        cnt[i] += 1
    if agg == 'mean':
        return [round(out[i] / cnt[i], 3) if cnt[i] else None for i in range(len(keys))]
    return [round(v, 4) for v in out]


def _forecast(values, horizon=HORIZON_DAYS, floor=0.0, cap=None):
    """OLS trend over a daily series (index = day) with an 80 % residual band.
    Returns None with fewer than 7 usable points. Everything the reader needs to judge it
    (slope, r², n, method) ships with the numbers."""
    pts = [(i, float(v)) for i, v in enumerate(values) if v is not None]
    if len(pts) < 7:
        return None
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
    slope = sxy / sxx if sxx else 0.0
    icpt = my - slope * mx
    resid = [p[1] - (icpt + slope * p[0]) for p in pts]
    ss_res = sum(r * r for r in resid)
    ss_tot = sum((p[1] - my) ** 2 for p in pts)
    r2 = 1 - ss_res / ss_tot if ss_tot else None
    sd = math.sqrt(ss_res / max(1, n - 2))
    band = 1.2816 * sd
    start = len(values)
    vals, lo, hi = [], [], []
    for i in range(horizon):
        x = start + i
        y = icpt + slope * x
        y = max(floor, y) if floor is not None else y
        if cap is not None:
            y = min(cap, y)
        vals.append(round(y, 4))
        lo.append(round(max(floor if floor is not None else -1e18, y - band), 4))
        hi.append(round(min(cap, y + band) if cap is not None else y + band, 4))
    level = sum(p[1] for p in pts[-14:]) / len(pts[-14:])
    return {
        'values': vals,
        'lo': lo,
        'hi': hi,
        'slope_per_day': round(slope, 5),
        'r2': _r(r2, 3),
        'n': n,
        'level_14d': round(level, 4),
        'band_pct': 80,
        'method': f'OLS trend over the last {len(values)} days, 80 % residual band',
    }


def _forecast_keys(now, horizon=HORIZON_DAYS):
    d0 = _day(now)
    return [(d0 + timedelta(days=i + 1)).isoformat() for i in range(horizon)]


def _fc_bucketed(fc, fkeys, weekly, agg='sum'):
    """Re-bucket a daily forecast to the history's bucket (weekly → per-week sums or means)."""
    if not fc:
        return None
    if not weekly:
        return {'keys': fkeys, 'values': fc['values'], 'lo': fc['lo'], 'hi': fc['hi']}
    groups: dict = {}
    for k, v, lo, hi in zip(fkeys, fc['values'], fc['lo'], fc['hi']):
        wk = _week_start(datetime.fromisoformat(k).date()).isoformat()
        g = groups.setdefault(wk, [[], [], []])
        g[0].append(v)
        g[1].append(lo)
        g[2].append(hi)
    f = (lambda a: sum(a)) if agg == 'sum' else (lambda a: sum(a) / len(a))
    keys = sorted(groups)
    return {
        'keys': keys,
        'values': [round(f(groups[k][0]), 4) for k in keys],
        'lo': [round(f(groups[k][1]), 4) for k in keys],
        'hi': [round(f(groups[k][2]), 4) for k in keys],
    }


def _delta(cur, prev):
    if cur is None or prev is None:
        return None
    if prev == 0:
        return None if cur == 0 else 100.0
    return round((cur - prev) / abs(prev) * 100, 1)
