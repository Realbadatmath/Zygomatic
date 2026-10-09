# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""production_calendar.py — the Approval Queue's calendar and production overview. 2026-09-22.

One payload, `payload(view, anchor, days)`, drives the panel that sits next to the workflow
cards on :5000/approval_queue:

  * **calendar** — a day grid: for every day, what production is PLANNED (the schedule the
    batchers actually follow) and, for a day that has already happened, what was produced.
  * **production** — the same window as numbers: items, production time, token cost, the
    share of the machine the workflow took, expected versus real.

Window: 7 / 14 / 28 days, anchored anywhere from a year back to 28 days ahead. Past days are
measured, the future is projected — the payload never mixes the two silently: every day cell
carries `is_past` / `is_future` and every projected number carries its basis (`n` runs, which
window the median came from).

Sources (all of them already-kept files, nothing new is written):
  * metrics_hub.collect_runs / analytics_hub.enrich_runs — the run ledger with a duration
    basis (recorded / inferred / missing) per run, and the LLM rows attributed per pipeline;
  * data/runtime/system_usage.jsonl (zyg-sysusage minute sampler, 2026-09-18 on) and the
    older telemetry_<pipeline>.csv aggregate — measured machine utilisation;
  * the batchers' own state files (zero_auto_mode.json, storyteller_daily.json +
    storyteller_templates.json, melody_daily.json, preempt bank) and
    approval_queue_settings.py — the schedule the plan is projected from.

Honesty rules (the house rule: measure before you claim):
  * "planned" is the schedule rule applied to a date — for a past date it is the rule applied
    retroactively, and says so (`plan_basis`);
  * "expected" for a past day is the estimate that could have been made BEFORE that day: the
    median unit cost over the 28 days preceding it, never the day's own outcome;
  * "actual" only counts what the ledger recorded; a run whose duration has no basis is
    counted in the item count and excluded from the hours, and `hours_missing` says how many;
  * a future day has no actual, a past day has no forecast band.

`python3 production_calendar.py [--view production] [--days 7] [--anchor 2026-09-01]` prints
the payload.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timedelta

CREWS = os.path.dirname(os.path.abspath(__file__))
if CREWS not in sys.path:
    sys.path.insert(0, CREWS)

from zyg_dashboard import metrics_hub as mh  # noqa: E402

RUNTIME = mh.RUNTIME
TZ = mh.TZ
DAY = mh.DAY

MAX_FUTURE_DAYS = 28
MAX_PAST_DAYS = 365
WINDOWS = (7, 14, 28)
TRAIL_DAYS = 28  # the trailing window a per-item estimate is drawn from
TREND_DAYS = 56  # the window the CURRENT unit medians come from
MIN_SAMPLE = 3  # fewer runs than this and the trailing median widens to all history

# The four Approval Queue workflows and the run kinds each one produces. `scholarly-preempt`
# is the brain-only run the Pre-Emptive bank makes; it never renders, so it is its own card.
WORKFLOWS = (
    {
        'id': 'documentary',
        'name': 'Documentary',
        'accent': '#2e8b57',
        'kinds': ('scholarly', 'crime'),
        'unit': 'episode',
    },
    {'id': 'storyteller', 'name': 'Storyteller', 'accent': '#b5761f', 'kinds': ('storyteller',), 'unit': 'episode'},
    {'id': 'melody', 'name': 'Melody', 'accent': '#1f8ea8', 'kinds': ('kidsmusic',), 'unit': 'song'},
    {'id': 'preempt', 'name': 'Pre-Emptive', 'accent': '#6a4fbf', 'kinds': ('scholarly-preempt',), 'unit': 'brain run'},
)
WF_IDS = tuple(w['id'] for w in WORKFLOWS)
KIND_WF = {k: w['id'] for w in WORKFLOWS for k in w['kinds']}

_MEMO: dict = {}


# ── small helpers ────────────────────────────────────────────────────────────


def _memo(key, ttl, fn, fresh=False):
    hit = _MEMO.get(key)
    now = time.time()
    if hit and not fresh and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _MEMO[key] = (now, val)
    return val


def _read(name):
    try:
        d = mh._read_json(os.path.join(RUNTIME, name))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _aqs_get(wf, key, default):
    """A setting from approval_queue_settings, or its default when the file/field is gone."""
    try:
        from zyg_dashboard import approval_queue_settings as _aqs

        return _aqs.get(wf, key)
    except Exception:  # noqa: BLE001
        return default


def _day_of(ts):
    return datetime.fromtimestamp(ts, TZ).date()


def _daykey(ts):
    return _day_of(ts).isoformat()


def _parse_date(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:  # noqa: BLE001
        return None


def _median(v):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def _pct(v, q):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    i = max(0, min(len(v) - 1, int(round((len(v) - 1) * q))))
    return v[i]


def _r(v, d=2):
    return None if v is None else round(float(v), d)


def _ams_now():
    return datetime.now(TZ)


# ── measured history ─────────────────────────────────────────────────────────


def _runs(now):
    """Every run, with the workflow it belongs to, its duration basis and its LLM cost."""
    from zyg_dashboard import analytics_hub as ah

    runs, meta, llm = ah.enrich_runs(now)
    out = []
    for r in runs:
        wf = KIND_WF.get(r['kind'])
        if not wf or not r.get('started'):
            continue
        out.append(
            {
                'wf': wf,
                'kind': r['kind'],
                'id': r['id'],
                'title': r.get('title') or '',
                'started': r['started'],
                'day': _daykey(r['started']),
                'status': r['status'],
                'duration_s': r.get('duration_s'),
                'duration_basis': r.get('duration_basis'),
                'tokens': r.get('llm_tokens') or 0,
                'cost_usd': r.get('api_cost_usd') or 0.0,
            }
        )
    out.sort(key=lambda r: r['started'])
    return out, meta, llm


def _subscription_by_day(llm):
    """Claude-login (subscription) tokens per day per workflow — they cost no API dollars but
    they are the scarce resource, so the overview counts them separately from the USD."""
    out: dict = {}
    for c in llm['rows']:
        if not c.get('ts'):
            continue
        if c.get('provider') != 'claude_code':
            continue
        out.setdefault(_daykey(c['ts']), 0)
        out[_daykey(c['ts'])] += (c.get('tin') or 0) + (c.get('tout') or 0)
    return out


def _machine_days(now):
    """Measured machine utilisation per day: the minute sampler first, the older telemetry
    CSVs where it did not run yet. `basis` says which one a day came from."""
    from zyg_dashboard import analytics_hub as ah

    days: dict = {}
    try:
        tel, _n_csv = ah.telemetry_days()  # (days, file count)
    except Exception:  # noqa: BLE001
        tel = {}
    for k, d in (tel or {}).items():
        secs = d.get('seconds') or 0
        if not secs:
            continue
        days[k] = {
            'basis': 'telemetry csv (only while a pipeline ran)',
            'busy_h': round((d.get('busy_s') or 0) / 3600.0, 3),
            'measured_h': round(secs / 3600.0, 3),
            'gpu_mean': _r((d.get('gpu_util_sum') or 0) / max(1, d.get('n') or 1), 1),
            'kwh': _r((d.get('power_wh') or 0) / 1000.0, 3),
        }
    try:
        sysd = ah._sysusage_days()
    except Exception:  # noqa: BLE001
        sysd = {}
    for k, d in (sysd or {}).items():
        mins = d.get('minutes') or 0
        if not mins:
            continue
        days[k] = {
            'basis': 'zyg-sysusage minute sampler',
            'busy_h': round((d.get('busy_min') or 0) / 60.0, 3),
            'measured_h': round(mins / 60.0, 3),
            'gpu_mean': _r((d.get('gpu_util_sum') or 0) / max(1, d.get('gpu_n') or 1), 1),
            'cpu_mean': _r((d.get('cpu_sum') or 0) / max(1, d.get('cpu_n') or 1), 1),
            'kwh': _r((d.get('power_wh') or 0) / 1000.0, 3),
        }
    return days


def _busy_hours(rows):
    """Union of run intervals (hours per day) — two runs in parallel do not make 2 h of box."""
    ivs = [[r['started'], r['started'] + r['duration_s']] for r in rows if r.get('started') and r.get('duration_s')]
    ivs.sort()
    merged: list = []
    for s, e in ivs:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    hours: dict = {}
    for s, e in merged:
        cur = s
        while cur < e:
            d = _day_of(cur)
            end_of_day = datetime.combine(d + timedelta(days=1), datetime.min.time(), TZ).timestamp()
            seg = min(e, end_of_day)
            hours[d.isoformat()] = hours.get(d.isoformat(), 0.0) + (seg - cur) / 3600.0
            cur = seg
    return hours


def measured(now, fresh=False):
    """Per-day, per-workflow measured production. Memoised for 45 s (the panel polls)."""

    def build():
        runs, meta, llm = _runs(now)
        sub_day = _subscription_by_day(llm)
        days: dict = {}
        for r in runs:
            d = days.setdefault(r['day'], {})
            w = d.setdefault(
                r['wf'],
                {
                    'started': 0,
                    'completed': 0,
                    'failed': 0,
                    'other': 0,
                    'hours': 0.0,
                    'hours_missing': 0,
                    'tokens': 0,
                    'cost_usd': 0.0,
                    'titles': [],
                },
            )
            w['started'] += 1
            if r['status'] == 'completed':
                w['completed'] += 1
            elif r['status'] == 'failed':
                w['failed'] += 1
            else:
                w['other'] += 1
            if r['duration_s']:
                w['hours'] += r['duration_s'] / 3600.0
            else:
                w['hours_missing'] += 1
            w['tokens'] += r['tokens']
            w['cost_usd'] += r['cost_usd']
            if len(w['titles']) < 6 and r['title']:
                w['titles'].append(r['title'])
        busy = {wf: _busy_hours([r for r in runs if r['wf'] == wf]) for wf in WF_IDS}
        for dk, d in days.items():
            for wf, w in d.items():
                w['busy_h'] = round(busy.get(wf, {}).get(dk, 0.0), 3)
                w['hours'] = round(w['hours'], 3)
                w['cost_usd'] = round(w['cost_usd'], 4)
        return {
            'days': days,
            'runs': runs,
            'meta': meta,
            'subscription_tokens': sub_day,
            'machine': _machine_days(now),
            'llm_rows': len(llm['rows']),
        }

    return _memo(('measured',), 45, build, fresh)


# ── per-item estimates ───────────────────────────────────────────────────────


def _unit_stats(runs, wf, until_ts=None, window_days=TREND_DAYS):
    """Median duration / tokens / cost of ONE item of this workflow, from the runs that
    finished before `until_ts` (so a past day's estimate never sees its own outcome)."""
    end = until_ts if until_ts else time.time()
    start = end - window_days * DAY
    rows = [r for r in runs if r['wf'] == wf and r['started'] < end and r['status'] in ('completed', 'failed')]
    win = [r for r in rows if r['started'] >= start]
    basis = f'median of {len(win)} runs in the {window_days} days before'
    if len(win) < MIN_SAMPLE:
        win = rows[-24:]
        basis = f'median of the last {len(win)} runs (too few in the {window_days}-day window)'
    durs = [r['duration_s'] for r in win if r['duration_s']]
    return {
        'n': len(win),
        'n_timed': len(durs),
        'seconds': _median(durs),
        'p25': _pct(durs, 0.25),
        'p75': _pct(durs, 0.75),
        'tokens': _median([r['tokens'] for r in win]) or 0,
        'cost_usd': _median([r['cost_usd'] for r in win]) or 0.0,
        'success': (sum(1 for r in win if r['status'] == 'completed') / len(win)) if win else None,
        'basis': basis if win else 'no runs of this workflow on record',
    }


def unit_table(runs, now):
    return {w['id']: _unit_stats(runs, w['id'], now) for w in WORKFLOWS}


# ── the plan the batchers actually follow ────────────────────────────────────


def _templates_enabled():
    t = _read('storyteller_templates.json').get('templates') or []
    return sum(1 for x in t if isinstance(x, dict) and x.get('enabled', True))


def schedule_state():
    """Every workflow's live switch position and the rule its plan follows."""
    auto = _read('zero_auto_mode.json')
    std = _read('storyteller_daily.json')
    mel = _read('melody_daily.json')
    pre = _read('preempt_state.json')
    doc_n = int(_aqs_get('documentary', 'topics_per_batch', 6))
    cadence = int(_aqs_get('documentary', 'cadence_days', 2))
    doc_hour = int(_aqs_get('documentary', 'batch_hour', 9))
    std_cap = int(_aqs_get('storyteller', 'max_per_day', 22))
    tpl = _templates_enabled()
    mel_n = int(_aqs_get('melody', 'per_day', 5))
    mel_hour = int(_aqs_get('melody', 'hour', 9))
    return {
        'documentary': {
            'enabled': bool(auto.get('enabled')),
            'paused': bool(auto.get('paused')),
            'per_batch': doc_n,
            'cadence_days': max(1, cadence),
            'hour': doc_hour,
            'next_run': auto.get('next_run_utc'),
            'last_run': auto.get('last_run_at'),
            'rule': f'{doc_n} topics per batch, a new batch {cadence} day(s) after the previous one '
            f'completes, at {doc_hour:02d}:00 AMS',
        },
        'storyteller': {
            'enabled': bool(std.get('enabled')),
            'paused': bool(std.get('paused')),
            'per_day': min(std_cap, tpl),
            'templates_enabled': tpl,
            'cap': std_cap,
            'done_date': std.get('done_date'),
            'hour': None,
            'rule': f'one episode per enabled series template per day ({tpl} enabled, cap {std_cap}); '
            'an unfinished batch carries over instead of being replaced',
        },
        'melody': {
            'enabled': bool(mel.get('enabled')),
            'paused': bool(mel.get('paused')),
            'per_day': mel_n,
            'hour': mel_hour,
            'done_date': mel.get('done_date'),
            'rule': f'{mel_n} songs a day from {mel_hour:02d}:00 AMS, composed one at a time',
        },
        'preempt': {
            'enabled': bool(pre.get('enabled')),
            'paused': bool(pre.get('paused')),
            'rule': 'brain-only runs back to back until the bank target is met; no fixed hour',
        },
    }


def _preempt_remaining():
    """How many brain runs the bank still wants — the Pre-Emptive plan is "until the target"."""
    target = int(_aqs_get('preempt', 'documentary_target', 100))
    built = 0
    try:
        from zyg_dashboard import preempt_bank as _pb

        c = _pb.counts()
        built = int(c.get('ready', 0)) + int(c.get('claimed', 0)) + int(c.get('consumed', 0))
    except Exception:  # noqa: BLE001
        built = 0
    return max(0, target - built), target, built


def _doc_batch_days(state, dates, today, live_items, unit):
    """The days a documentary batch fires inside the window, projected forward from
    next_run_utc (or from the live batch's expected completion) and then every cadence.
    A switched-off workflow keeps its rule — the cadence is projected from today, so the
    calendar can show what the schedule WOULD queue (drawn as a ghost)."""
    s = state['documentary']
    cad = s['cadence_days']
    nxt = _parse_date(s.get('next_run')) if s.get('next_run') else None
    if nxt is None:
        if s['enabled'] and live_items:
            # No armed time: the live batch has to finish first. Estimate that from what is left.
            secs = (unit.get('seconds') or 0) * max(0, live_items)
            nxt = (_ams_now() + timedelta(seconds=secs) + timedelta(days=cad)).date()
        else:
            nxt = today
    out: dict = {}
    first, last = _parse_date(dates[0]), _parse_date(dates[-1])
    d = nxt
    while d < first:  # walk the cadence forward into the window
        d += timedelta(days=cad)
    while d <= last:
        out[d.isoformat()] = s['per_batch']
        d += timedelta(days=cad)
    d = nxt - timedelta(days=cad)  # and backwards, for the past part of the window
    while d >= first:
        out.setdefault(d.isoformat(), s['per_batch'])
        d -= timedelta(days=cad)
    return out


def plan(state, dates, today, measured_days, unit_now):
    """Planned items per day per workflow for every date in the window.

    Every workflow is projected, switched on or off: a row carries `active` (the switch is on
    and not paused) so the board can draw an off workflow's schedule as a ghost — "this is what
    would run" — without it ever being counted as planned work.

    A past day's plan is the same rule applied retroactively (`plan_basis` says so); it is what
    the schedule WOULD have queued, which is what makes "planned vs produced" readable.
    """
    live_doc = 0
    b = _read('zero_kanban_batch.json')
    for e in b.get('topics') or []:
        if (e or {}).get('status') in ('scheduled', 'in_production'):
            live_doc += 1
    doc_days = _doc_batch_days(state, dates, today, live_doc, unit_now.get('documentary', {}))
    pre_left, pre_target, pre_built = _preempt_remaining()
    pre_unit = (unit_now.get('preempt', {}) or {}).get('seconds') or 0
    # The bank builds back to back; 20 h of a day is the most it has ever been given.
    pre_per_day = int(min(pre_left, (20 * 3600 / pre_unit))) if pre_unit else 0
    out: dict = {}
    pre_budget = pre_left
    for dk in dates:
        d = _parse_date(dk)
        row: dict = {}
        doc, s_std, mel, pre = state['documentary'], state['storyteller'], state['melody'], state['preempt']
        n = doc_days.get(dk, 0)
        if n:
            row['documentary'] = {
                'items': n,
                'active': doc['enabled'] and not doc['paused'],
                'why': f'batch day · {doc["hour"]:02d}:00 AMS',
            }
        if s_std['per_day']:
            row['storyteller'] = {
                'items': s_std['per_day'],
                'active': s_std['enabled'] and not s_std['paused'],
                'why': f'{s_std["templates_enabled"]} enabled series, one episode each',
            }
        if mel['per_day']:
            row['melody'] = {
                'items': mel['per_day'],
                'active': mel['enabled'] and not mel['paused'],
                'why': f'daily batch from {mel["hour"]:02d}:00 AMS',
            }
        if pre_per_day and d >= today and pre_budget > 0:
            take = int(min(pre_per_day, pre_budget))
            row['preempt'] = {
                'items': take,
                'active': pre['enabled'] and not pre['paused'],
                'why': f'bank {pre_built}/{pre_target} — {pre_budget} to go',
            }
            pre_budget -= take
        out[dk] = row
    return out, {
        'preempt_target': pre_target,
        'preempt_built': pre_built,
        'preempt_left': pre_left,
        'preempt_per_day': pre_per_day,
        'documentary_batch_days': sorted(doc_days),
        'plan_basis': "the batchers' own rule applied to each date; for a past date the rule "
        'is applied retroactively — no plan was ever stored',
    }


# ── the payload ──────────────────────────────────────────────────────────────


def _window_dates(anchor, days):
    return [(anchor + timedelta(days=i)).isoformat() for i in range(days)]


def _day_cell(dk, today, mes, planned_row, runs, unit_now, machine):
    d = _parse_date(dk)
    is_past, is_today = d < today, d == today
    actual_row = mes['days'].get(dk) or {}
    cell = {
        'date': dk,
        'dow': d.strftime('%a'),
        'dom': d.day,
        'month': d.strftime('%b'),
        'iso_week': d.isocalendar()[1],
        'weekend': d.weekday() >= 5,
        'is_past': is_past,
        'is_today': is_today,
        'is_future': d > today,
        'workflows': {},
        'planned_total': 0,
        'potential_total': 0,
        'produced_total': 0,
        'started_total': 0,
        'failed_total': 0,
        'hours': 0.0,
        'hours_expected': 0.0,
        'hours_expected_started': 0.0,
        'cost_usd': 0.0,
        'cost_expected_usd': 0.0,
        'tokens': 0,
        'tokens_expected': 0,
        'busy_h': 0.0,
        'hours_potential': 0.0,
        'cost_potential_usd': 0.0,
        'tokens_potential': 0,
    }
    # The estimate that could have been made the morning of this day — never its own outcome.
    end_ts = datetime.combine(d, datetime.min.time(), TZ).timestamp()
    for w in WORKFLOWS:
        wf = w['id']
        pl = planned_row.get(wf) or {}
        ac = actual_row.get(wf)
        if not pl and not ac:
            continue
        unit = _unit_stats(runs, wf, end_ts, TRAIL_DAYS) if (is_past or is_today) else unit_now[wf]
        n = int(pl.get('items') or 0)
        active = bool(pl.get('active'))
        exp_h = (unit['seconds'] or 0) * n / 3600.0 if unit['seconds'] else None
        row = {
            'planned': n if active else 0,
            'potential': 0 if active else n,
            'active': active,
            'plan_why': pl.get('why', ''),
            'expected_hours': _r(exp_h, 2),
            'expected_cost_usd': _r((unit['cost_usd'] or 0) * n, 4),
            'expected_tokens': int((unit['tokens'] or 0) * n),
            'unit_min': _r((unit['seconds'] or 0) / 60.0, 1) if unit['seconds'] else None,
            'unit_basis': unit['basis'],
        }
        if not (d > today):
            row.update(
                {
                    'started': (ac or {}).get('started', 0),
                    'completed': (ac or {}).get('completed', 0),
                    'failed': (ac or {}).get('failed', 0),
                    'open': (ac or {}).get('other', 0),
                    'hours': _r((ac or {}).get('hours', 0.0), 2),
                    'busy_hours': _r((ac or {}).get('busy_h', 0.0), 2),
                    'hours_missing': (ac or {}).get('hours_missing', 0),
                    'tokens': (ac or {}).get('tokens', 0),
                    'cost_usd': _r((ac or {}).get('cost_usd', 0.0), 4),
                    'titles': (ac or {}).get('titles', []),
                }
            )
            # Expected here is per ITEM actually attempted, so a day that ran 3 of 6 planned
            # episodes is not reported as 50 % faster than expected.
            exp_started = (unit['seconds'] or 0) * (row['started'] or 0) / 3600.0 if unit['seconds'] else None
            row['expected_hours_for_started'] = _r(exp_started, 2)
            if exp_started and row.get('hours'):
                row['hours_delta_pct'] = _r((row['hours'] - exp_started) / exp_started * 100.0, 0)
            row['items_delta'] = (row.get('started', 0) - n) if active else None
        else:
            # A forecast band from the p25/p75 of the unit duration — not a made-up ±.
            row['band_hours'] = (
                [_r((unit['p25'] or 0) * n / 3600.0, 2), _r((unit['p75'] or 0) * n / 3600.0, 2)]
                if unit['p25']
                else None
            )
            row['success_rate'] = _r(unit['success'], 3)
            row['expected_completed'] = _r((unit['success'] or 0) * n, 1) if unit['success'] is not None else None
        cell['workflows'][wf] = row
        cell['planned_total'] += row['planned']
        cell['potential_total'] += row['potential']
        if active:
            cell['hours_expected'] += exp_h or 0.0
            cell['cost_expected_usd'] += row['expected_cost_usd'] or 0.0
            cell['tokens_expected'] += row['expected_tokens'] or 0
        else:
            # What the same rule WOULD cost if the switch were on — drawn as a ghost, never
            # added to the planned totals.
            cell['hours_potential'] += exp_h or 0.0
            cell['cost_potential_usd'] += row['expected_cost_usd'] or 0.0
            cell['tokens_potential'] += row['expected_tokens'] or 0
        if not (d > today):
            cell['started_total'] += row.get('started', 0)
            cell['produced_total'] += row.get('completed', 0)
            cell['failed_total'] += row.get('failed', 0)
            cell['hours'] += row.get('hours') or 0.0
            cell['busy_h'] += row.get('busy_hours') or 0.0
            cell['cost_usd'] += row.get('cost_usd') or 0.0
            cell['tokens'] += row.get('tokens') or 0
            cell['hours_expected_started'] += row.get('expected_hours_for_started') or 0.0
    cell['machine'] = machine.get(dk) or None
    for k in (
        'hours',
        'hours_expected',
        'hours_expected_started',
        'cost_usd',
        'cost_expected_usd',
        'busy_h',
        'hours_potential',
        'cost_potential_usd',
    ):
        cell[k] = _r(cell[k], 4 if 'cost' in k else 2)
    cell['subscription_tokens'] = mes['subscription_tokens'].get(dk, 0)
    # Share of a 24 h day the box spent on these workflows (union: parallel runs count once).
    cell['system_pct'] = _r((cell['busy_h'] or 0) / 24.0 * 100.0, 1)
    cell['system_pct_expected'] = _r((cell['hours_expected'] or 0) / 24.0 * 100.0, 1)
    cell['system_pct_potential'] = _r((cell['hours_potential'] or 0) / 24.0 * 100.0, 1)
    if cell['hours_expected_started'] and cell['hours']:
        cell['hours_delta_pct'] = _r(
            (cell['hours'] - cell['hours_expected_started']) / cell['hours_expected_started'] * 100.0, 0
        )
    return cell


def payload(view='calendar', anchor=None, days=7, now=None, fresh=False):
    now = now or time.time()
    today = _ams_now().date()
    days = int(days) if int(days) in WINDOWS else 7
    a = _parse_date(anchor) if anchor else today
    if a is None:
        a = today
    lo, hi = today - timedelta(days=MAX_PAST_DAYS), today + timedelta(days=MAX_FUTURE_DAYS)
    if a + timedelta(days=days - 1) > hi:
        a = hi - timedelta(days=days - 1)
    if a < lo:
        a = lo
    dates = _window_dates(a, days)
    mes = measured(now, fresh)
    runs = mes['runs']
    unit_now = unit_table(runs, now)
    state = schedule_state()
    planned, plan_meta = plan(state, dates, today, mes['days'], unit_now)
    cells = [_day_cell(dk, today, mes, planned.get(dk) or {}, runs, unit_now, mes['machine']) for dk in dates]

    # ── window summary, per workflow ──
    summary = []
    for w in WORKFLOWS:
        wf = w['id']
        rows = [c['workflows'].get(wf) for c in cells if c['workflows'].get(wf)]
        past = [(c, c['workflows'][wf]) for c in cells if c['workflows'].get(wf) and not c['is_future']]
        fut = [(c, c['workflows'][wf]) for c in cells if c['workflows'].get(wf) and c['is_future']]
        hours = sum((r.get('hours') or 0) for _, r in past)
        busy = sum((r.get('busy_hours') or 0) for _, r in past)
        exp_h = sum((r.get('expected_hours') or 0) for r in rows if r.get('active'))
        u = unit_now[wf]
        st = state[wf]
        summary.append(
            {
                'id': wf,
                'name': w['name'],
                'accent': w['accent'],
                'unit': w['unit'],
                'enabled': st['enabled'],
                'paused': st.get('paused', False),
                'rule': st['rule'],
                'planned': sum(r.get('planned') or 0 for r in rows),
                'potential': sum(r.get('potential') or 0 for r in rows),
                'planned_past': sum(r.get('planned') or 0 for _, r in past),
                'planned_future': sum(r.get('planned') or 0 for _, r in fut),
                'started': sum(r.get('started') or 0 for _, r in past),
                'completed': sum(r.get('completed') or 0 for _, r in past),
                'failed': sum(r.get('failed') or 0 for _, r in past),
                'hours': _r(hours, 2),
                'busy_hours': _r(busy, 2),
                'expected_hours': _r(exp_h, 2),
                'expected_hours_for_started': _r(sum((r.get('expected_hours_for_started') or 0) for _, r in past), 2),
                'hours_delta_pct': _r((hours - exp_started_sum) / exp_started_sum * 100.0, 0)
                if (exp_started_sum := sum((r.get('expected_hours_for_started') or 0) for _, r in past)) and hours
                else None,
                'hours_missing': sum(r.get('hours_missing') or 0 for _, r in past),
                'cost_usd': _r(sum(r.get('cost_usd') or 0 for _, r in past), 4),
                'expected_cost_usd': _r(sum(r.get('expected_cost_usd') or 0 for r in rows if r.get('active')), 4),
                'tokens': sum(r.get('tokens') or 0 for _, r in past),
                'expected_tokens': sum(r.get('expected_tokens') or 0 for r in rows if r.get('active')),
                'potential_hours': _r(sum(r.get('expected_hours') or 0 for r in rows if not r.get('active')), 2),
                'potential_cost_usd': _r(sum(r.get('expected_cost_usd') or 0 for r in rows if not r.get('active')), 4),
                'potential_tokens': sum(r.get('expected_tokens') or 0 for r in rows if not r.get('active')),
                'unit_min': _r((u['seconds'] or 0) / 60.0, 1) if u['seconds'] else None,
                'unit_tokens': int(u['tokens'] or 0),
                'unit_cost_usd': _r(u['cost_usd'], 4),
                'unit_basis': u['basis'],
                'unit_n': u['n'],
                'success_rate': _r(u['success'], 3),
                'system_pct': _r(busy / (24.0 * max(1, len(past))) * 100.0, 1) if past else None,
                'system_pct_expected': _r(exp_h / (24.0 * max(1, len(rows))) * 100.0, 1) if rows else None,
            }
        )

    past_cells = [c for c in cells if not c['is_future']]
    fut_cells = [c for c in cells if c['is_future']]
    measured_h = sum((c['machine'] or {}).get('measured_h', 0) for c in past_cells)
    machine_busy_h = sum((c['machine'] or {}).get('busy_h', 0) for c in past_cells)
    # A share of the measured busy time only means something on days the sampler actually
    # covered. The old telemetry CSVs ran only WHILE a pipeline ran, so on those days the
    # workflows' own run time can exceed the "measured" busy time — that is not a 700 % share,
    # it is a window that was never measured. Say so instead of printing a number.
    covered = [
        c
        for c in past_cells
        if (c['machine'] or {}).get('basis', '').startswith('zyg-sysusage')
        and (c['machine'] or {}).get('measured_h', 0) >= 20
    ]
    cov_busy = sum((c['machine'] or {}).get('busy_h', 0) for c in covered)
    cov_wf = sum(c['busy_h'] or 0 for c in covered)
    gpu_share = _r(cov_wf / cov_busy * 100.0, 1) if cov_busy else None
    gpu_share_basis = (
        f'{len(covered)} of {len(past_cells)} days have a full-day minute-sampler record'
        if covered
        else 'no full-day utilisation record in this window — the minute sampler runs from '
        '2026-09-18, and before that the box was only logged WHILE a pipeline ran'
    )
    if gpu_share is not None and gpu_share > 100:
        gpu_share_basis += (
            '; over 100 % because a run occupies the box through CPU-only stages too, '
            'while "GPU busy" counts only minutes at 20 % utilisation or more'
        )
    totals = {
        'days': len(cells),
        'past_days': len(past_cells),
        'future_days': len(fut_cells),
        'planned': sum(c['planned_total'] for c in cells),
        'potential': sum(c['potential_total'] for c in cells),
        'started': sum(c['started_total'] for c in past_cells),
        'produced': sum(c['produced_total'] for c in past_cells),
        'failed': sum(c['failed_total'] for c in past_cells),
        'hours': _r(sum(c['hours'] or 0 for c in past_cells), 2),
        'busy_hours': _r(sum(c['busy_h'] or 0 for c in past_cells), 2),
        'expected_hours': _r(sum(c['hours_expected'] or 0 for c in cells), 2),
        'cost_usd': _r(sum(c['cost_usd'] or 0 for c in past_cells), 4),
        'expected_cost_usd': _r(sum(c['cost_expected_usd'] or 0 for c in cells), 4),
        'potential_hours': _r(sum((w.get('potential_hours') or 0) for w in summary), 2),
        'potential_cost_usd': _r(sum((w.get('potential_cost_usd') or 0) for w in summary), 4),
        'potential_tokens': sum((w.get('potential_tokens') or 0) for w in summary),
        'tokens': sum(c['tokens'] or 0 for c in past_cells),
        'expected_tokens': sum(c['tokens_expected'] or 0 for c in cells),
        'subscription_tokens': sum(c['subscription_tokens'] or 0 for c in past_cells),
        'machine_measured_h': _r(measured_h, 2),
        'machine_busy_h': _r(machine_busy_h, 2),
        'system_pct': _r(sum(c['busy_h'] or 0 for c in past_cells) / (24.0 * max(1, len(past_cells))) * 100.0, 1),
        'hours_expected_started': _r(sum(c['hours_expected_started'] or 0 for c in past_cells), 2),
        'machine_days_covered': len(covered),
        'gpu_share_pct': gpu_share,
        'gpu_share_basis': gpu_share_basis,
    }
    notes = [
        "Planned = the batchers' own rule applied to the date (retroactively for a past day); it is "
        'not a stored plan, no plan was ever written down.',
        'Expected for a past day uses the median unit cost of the 28 days BEFORE it, so it is the '
        "estimate that could have been made that morning — never the day's own result.",
        'Actual counts the run ledger only. A run with no duration basis is in the item count and out '
        'of the hours; "no duration" says how many.',
        "System % = the union of this workflow's run intervals over a 24 h day, so two runs in parallel count once.",
        'Token cost = priced API calls attributed to a run (list prices). Claude-login calls are '
        'subscription, counted as tokens, not dollars.',
    ]
    if not mes['machine']:
        notes.append('No measured machine utilisation for this window — system % falls back to the ledger.')
    return {
        'ts': mh._iso(now),
        'view': view if view in ('calendar', 'production') else 'calendar',
        'today': today.isoformat(),
        'range': {
            'start': dates[0],
            'end': dates[-1],
            'days': days,
            'can_back': dates[0] > lo.isoformat(),
            'can_fwd': dates[-1] < hi.isoformat(),
            'min': lo.isoformat(),
            'max': hi.isoformat(),
            'windows': list(WINDOWS),
        },
        'days_list': cells,
        'summary': summary,
        'totals': totals,
        'schedule': state,
        'plan_meta': plan_meta,
        'notes': notes,
        'sources': {
            'runs': len(runs),
            'llm_rows': mes['llm_rows'],
            'machine_days': len(mes['machine']),
            'excluded': mes['meta'],
        },
    }


if __name__ == '__main__':
    args = sys.argv[1:]

    def opt(name, default=None):
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default

    print(
        json.dumps(
            payload(view=opt('--view', 'calendar'), anchor=opt('--anchor'), days=int(opt('--days', 7))),
            indent=1,
            default=str,
        )
    )
