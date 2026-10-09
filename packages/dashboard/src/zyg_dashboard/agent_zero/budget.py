# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Usage caps for Agent Zero v2: the configured ceilings, the running counters, and the
verdict for the next turn (CONTRACT E).

Agent Zero is meant to run on as little usage as possible -- but a saved token is never
allowed to cost reliability, so this module does exactly three things:

1. it publishes the ceilings that keep an assembled turn small by construction
   (``per_turn.max_context_tokens``, ``per_turn.max_tool_calls``, the compaction
   thresholds ``memory.py`` reads);
2. it enforces hard ceilings per turn, per day and per Claude week and returns a
   ``blocked`` verdict with a sentence the UI can show verbatim;
3. it never repairs a blocked turn behind the operator's back. There is no silent model
   downgrade, no dropped tool index and no truncated user message in here -- a turn that
   does not fit is refused, and the only way past a ceiling is an explicit
   :func:`grant_override`. A local Ollama model stays available when a Claude ceiling
   blocks (it costs no quota) but only because the user picks it; nothing auto-switches.

Two files under ``data/runtime`` hold the state, both written atomically and guarded by
one process-wide lock: ``zero_budget.json`` (the operator's config, created with
:data:`DEFAULTS` on first read) and ``zero_budget_state.json`` (the counters, rolled over
when the Amsterdam day or Claude's weekly window changes).

Reading Claude's own meter is best-effort by design: any failure to read it counts as
*unknown* and allows the turn. Blocking Agent Zero because a sampler file was missing
would be a reliability regression, which is precisely what this module must not cause.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import tempfile
import threading
import time
from zoneinfo import ZoneInfo

from . import _host
from .contracts import estimate_tokens

_log = logging.getLogger(__name__)

#: The operator's timezone -- the "day" of the daily caps is an Amsterdam day.
TZ = ZoneInfo('Europe/Amsterdam')

CONFIG_NAME = 'zero_budget.json'
STATE_NAME = 'zero_budget_state.json'

#: How long the whole-login weekly API-equivalent total is reused (``report()`` scans
#: every Claude transcript on the machine and takes seconds -- it may not run per turn).
SHARE_CACHE_S = 600

#: How long a meter snapshot is reused. The sampler writes every 10 min, so a minute of
#: staleness costs nothing and keeps ``check_turn`` off the 1.4 MB sample ledger.
METER_CACHE_S = 60

DEFAULTS = {
    'per_turn': {
        'max_context_tokens': 14000,
        'max_tool_calls': 12,
        'max_output_tokens': 4096,
        'thinking_tokens': 0,
        'tool_result_max_chars': 6000,
        'timeout_s': 600,
    },
    'per_session': {
        'max_turns': 300,
        'compact_after_tokens': 24000,
        'keep_recent_turns': 8,
    },
    'per_day': {
        'soft_tokens': 150000,
        'hard_tokens': 400000,
        'max_turns': 400,
    },
    'per_week': {
        'zero_share_cap_pct': 20,
        'meter_reserve_pct': 90,
        'fable_cap_pct': 50,
    },
    'policy': {
        'allow_local_when_blocked': True,
        'override_turns_granted': 10,
    },
}

#: One line per setting, shipped to the settings UI so the operator never has to read
#: this file to know what a number does.
CONFIG_DOC = {
    'per_turn.max_context_tokens': 'Ceiling on the estimated input of one turn (system + tool index + state snapshot + summary + recent turns + message). A turn over it is refused, never trimmed.',
    'per_turn.max_tool_calls': 'How many tools one turn may run before the backend must stop and answer with what it has.',
    'per_turn.max_output_tokens': 'Reply ceiling for the API backends. The subscription CLI has a 16000-token floor it enforces itself.',
    'per_turn.thinking_tokens': 'MAX_THINKING_TOKENS for the Claude Code backend. 0 is the measured best setting for this stack; the operator may raise it.',
    'per_turn.tool_result_max_chars': 'A tool result longer than this is clipped before it enters the conversation.',
    'per_turn.timeout_s': 'Wall-clock ceiling for one turn, backend included.',
    'per_session.max_turns': 'Turns one chat session may hold before a new chat is required.',
    'per_session.compact_after_tokens': 'Estimated history size that triggers rolling-summary compaction.',
    'per_session.keep_recent_turns': 'User/assistant pairs kept verbatim; everything older is folded into the summary.',
    'per_day.soft_tokens': 'Daily token total that raises a warning (the turn still runs).',
    'per_day.hard_tokens': 'Daily token total that blocks further turns until midnight Amsterdam.',
    'per_day.max_turns': 'Turns Agent Zero may run in one Amsterdam day.',
    'per_week.zero_share_cap_pct': "Most of the Claude weekly meter Agent Zero may consume, measured as Zero's API-equivalent share of this login's week.",
    'per_week.meter_reserve_pct': "Stop on subscription models once Claude's own weekly meter is above this, so the operator keeps a reserve.",
    'per_week.fable_cap_pct': 'Same reserve for the scoped Fable weekly limit, applied when the selected model is a Fable model.',
    'policy.allow_local_when_blocked': 'When a Claude ceiling blocks, still allow a local Ollama model (it costs no quota). Never an automatic switch -- the user must pick it.',
    'policy.override_turns_granted': 'Turns one operator override is worth.',
}

#: ``section.key -> (type, minimum, maximum)``. ``float`` also accepts an ``int``;
#: ``bool`` is never accepted for an ``int`` field even though Python says it is one.
_SPEC: dict[str, tuple[type, float | None, float | None]] = {
    'per_turn.max_context_tokens': (int, 1000, 1_000_000),
    'per_turn.max_tool_calls': (int, 1, 200),
    'per_turn.max_output_tokens': (int, 256, 200_000),
    'per_turn.thinking_tokens': (int, 0, 200_000),
    'per_turn.tool_result_max_chars': (int, 200, 1_000_000),
    'per_turn.timeout_s': (int, 10, 7200),
    'per_session.max_turns': (int, 1, 100_000),
    'per_session.compact_after_tokens': (int, 1000, 1_000_000),
    'per_session.keep_recent_turns': (int, 1, 200),
    'per_day.soft_tokens': (int, 0, 100_000_000),
    'per_day.hard_tokens': (int, 1000, 100_000_000),
    'per_day.max_turns': (int, 1, 1_000_000),
    'per_week.zero_share_cap_pct': (float, 0, 100),
    'per_week.meter_reserve_pct': (float, 0, 100),
    'per_week.fable_cap_pct': (float, 0, 100),
    'policy.allow_local_when_blocked': (bool, None, None),
    'policy.override_turns_granted': (int, 0, 1000),
}

_STATE_DEFAULTS = {
    'day': '',
    'day_tokens': 0,
    'day_turns': 0,
    'day_api_usd': 0.0,
    'week_key': '',
    'week_tokens': 0,
    'week_api_usd': 0.0,
    'week_sub_turns': 0,
    'override_turns_left': 0,
    'last_block': None,
    'totals': {'turns': 0, 'tokens': 0, 'api_usd': 0.0},
}

#: Providers that spend no Claude quota at all: only the per-turn and daily turn rules
#: apply to them.
LOCAL_PROVIDERS = ('ollama',)

_LOCK = threading.Lock()
_share_cache: dict = {'ts': 0.0, 'login_week_usd': None, 'meter_pct': None}
_meter_cache: dict = {'ts': 0.0, 'snapshot': None}


# ── paths and atomic writes ──────────────────────────────────────────────────


def config_path() -> str:
    """Path of the operator's budget config."""
    return os.path.join(_host.runtime_dir(), CONFIG_NAME)


def state_path() -> str:
    """Path of the running counters."""
    return os.path.join(_host.runtime_dir(), STATE_NAME)


def _write_json(path: str, data) -> None:
    """Write ``data`` as JSON through a temp file in the same directory + os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.zero_budget.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write('\n')
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001 - a corrupt file falls back to defaults
        _log.warning('agent_zero.budget: cannot read %s (%s)', path, exc)
        return {}
    return data if isinstance(data, dict) else {}


# ── config ──────────────────────────────────────────────────────────────────


def _merge_defaults(stored: dict) -> tuple[dict, bool]:
    """Overlay ``stored`` on :data:`DEFAULTS`; the flag says whether a key was missing."""
    merged: dict = {}
    added = False
    for section, keys in DEFAULTS.items():
        sec = stored.get(section)
        have = sec if isinstance(sec, dict) else {}
        out = {}
        for key, default in keys.items():
            if key in have:
                out[key] = have[key]
            else:
                out[key] = default
                added = True
        merged[section] = out
    return merged, added


def load_config() -> dict:
    """The budget config, created with :data:`DEFAULTS` on first read.

    Missing keys are filled from the defaults and written back, so a release that adds a
    setting does not need a migration.
    """
    path = config_path()
    stored = _read_json(path)
    merged, added = _merge_defaults(stored)
    if added or not stored:
        try:
            _write_json(path, merged)
        except OSError as exc:
            _log.warning('agent_zero.budget: cannot write %s (%s)', path, exc)
    return merged


def _validate(section: str, key: str, value):
    """Coerce and range-check one setting.

    Raises ``TypeError`` when the value is of the wrong kind and ``ValueError`` when it is
    of the right kind but out of range; the settings route reports both as a 400.
    """
    spec = _SPEC.get(f'{section}.{key}')
    if spec is None:
        raise ValueError(f'unknown budget setting {section}.{key}')
    kind, low, high = spec
    if kind is bool:
        if not isinstance(value, bool):
            raise TypeError(f'{section}.{key} must be true or false, got {value!r}')
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f'{section}.{key} must be a number, got {value!r}')
    value = int(value) if kind is int else float(value)
    if low is not None and value < low:
        raise ValueError(f'{section}.{key} must be >= {low:g}, got {value:g}')
    if high is not None and value > high:
        raise ValueError(f'{section}.{key} must be <= {high:g}, got {value:g}')
    return value


def save_config(patch: dict) -> dict:
    """Validate ``patch`` ({section: {key: value}}), merge it into the config, write it.

    Raises ``TypeError`` on a wrong type and ``ValueError`` on an unknown key or an
    out-of-range number, and writes nothing in either case -- a half-applied config is
    worse than a rejected one.
    """
    if not isinstance(patch, dict):
        raise TypeError('budget config patch must be an object')
    clean: dict[str, dict] = {}
    for section, keys in patch.items():
        if section not in DEFAULTS:
            raise ValueError(f'unknown budget section {section!r}')
        if not isinstance(keys, dict):
            raise TypeError(f'budget section {section!r} must be an object')
        clean[section] = {k: _validate(section, k, v) for k, v in keys.items()}
    cfg = load_config()
    for section, keys in clean.items():
        cfg[section].update(keys)
    if cfg['per_day']['soft_tokens'] > cfg['per_day']['hard_tokens']:
        raise ValueError('per_day.soft_tokens must not exceed per_day.hard_tokens')
    _write_json(config_path(), cfg)
    return cfg


# ── Claude's meter (best effort, never a reason to block) ────────────────────


def _today() -> str:
    """Today's date in the operator's timezone. Monkeypatched in the tests."""
    return _dt.datetime.now(TZ).strftime('%Y-%m-%d')


def _iso_monday() -> str:
    """Fallback week key: the ISO date of this Amsterdam week's Monday."""
    now = _dt.datetime.now(TZ).date()
    return (now - _dt.timedelta(days=now.weekday())).isoformat()


def _newest_sample() -> dict:
    """The newest line of ``quota_samples.jsonl``, read from the tail of the file.

    The ledger is megabytes and grows; only its last line matters here.
    """
    path = os.path.join(_host.runtime_dir(), 'quota_samples.jsonl')
    try:
        with open(path, 'rb') as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 65536))
            tail = fh.read().decode('utf-8', 'replace')
    except OSError:
        return {}
    for line in reversed(tail.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            return row
    return {}


def meter_snapshot(max_age_s: float = METER_CACHE_S) -> dict:
    """What Agent Zero knows about Claude's own meter.

    ``{'ok': bool, 'seven_day_pct': float|None, 'five_hour_pct': float|None,
    'window_key': str|None, 'scoped': {name_lower: pct}}``. ``ok`` is False when nothing
    could be read, and every caller treats that as *unknown and allowed*.
    """
    now = time.time()
    if _meter_cache['snapshot'] is not None and now - _meter_cache['ts'] < max_age_s:
        return _meter_cache['snapshot']
    snap = {'ok': False, 'seven_day_pct': None, 'five_hour_pct': None, 'window_key': None, 'scoped': {}}
    meter = _host.quota_meter()
    if meter is not None:
        try:
            status = meter.read_status() or {}
            if status.get('seven_day_pct') is not None:
                snap['seven_day_pct'] = float(status['seven_day_pct'])
                snap['ok'] = True
            if status.get('five_hour_pct') is not None:
                snap['five_hour_pct'] = float(status['five_hour_pct'])
                snap['ok'] = True
        except Exception as exc:  # noqa: BLE001 - unknown is allowed, never fatal
            _log.warning('agent_zero.budget: quota_meter.read_status failed (%s)', exc)
    row = _newest_sample()
    sd = row.get('seven_day')
    seven = sd if isinstance(sd, dict) else {}
    if snap['seven_day_pct'] is None and seven.get('pct') is not None:
        snap['seven_day_pct'] = float(seven['pct'])
        snap['ok'] = True
    started = seven.get('window_started_at')
    if started:
        try:
            snap['window_key'] = _dt.datetime.fromtimestamp(float(started), _dt.timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            snap['window_key'] = None
    for item in row.get('scoped') or []:
        if isinstance(item, dict) and item.get('name') is not None and item.get('pct') is not None:
            snap['scoped'][str(item['name']).lower()] = float(item['pct'])
    _meter_cache.update(ts=now, snapshot=snap)
    return snap


def _week_key() -> str:
    """Key identifying Claude's current weekly window, for the state rollover."""
    return meter_snapshot().get('window_key') or _iso_monday()


def _login_week(now: float) -> tuple[float | None, float | None]:
    """``(whole-login week API-equivalent $, seven-day meter pct)``, cached 10 minutes."""
    if now - _share_cache['ts'] < SHARE_CACHE_S:
        return _share_cache['login_week_usd'], _share_cache['meter_pct']
    usd = pct = None
    meter = _host.quota_meter()
    if meter is not None:
        try:
            week = (meter.report(days=7) or {}).get('week') or {}
            usd = week.get('api_usd')
            pct = week.get('utilization_pct')
            usd = float(usd) if usd is not None else None
            pct = float(pct) if pct is not None else None
        except Exception as exc:  # noqa: BLE001 - unknown is allowed, never fatal
            _log.warning('agent_zero.budget: quota_meter.report failed (%s)', exc)
    _share_cache.update(ts=now, login_week_usd=usd, meter_pct=pct)
    return usd, pct


def zero_share_pct(cached_only: bool = False) -> float | None:
    """How many points of Claude's weekly meter Agent Zero is responsible for.

    Zero's API-equivalent spend this week divided by the whole login's, times the meter
    Claude reports -- i.e. Zero's slice of the weekly allowance in meter points.
    ``None`` when the meter or the transcript scan is unavailable.

    With ``cached_only`` the transcript scan is never triggered (the prompt's
    :func:`summary_line` uses that, so assembling a turn stays cheap).
    """
    now = time.time()
    if cached_only and now - _share_cache['ts'] >= SHARE_CACHE_S:
        return None
    login_usd, pct = _login_week(now)
    if not login_usd or pct is None:
        return None
    mine = float(load_state().get('week_api_usd') or 0.0)
    return round(mine / login_usd * pct, 4)


# ── state ───────────────────────────────────────────────────────────────────


def _roll(st: dict) -> tuple[dict, bool]:
    """Reset the day and week counters when their key changed."""
    changed = False
    today = _today()
    if st.get('day') != today:
        st.update(day=today, day_tokens=0, day_turns=0, day_api_usd=0.0)
        changed = True
    week = _week_key()
    if st.get('week_key') != week:
        st.update(week_key=week, week_tokens=0, week_api_usd=0.0, week_sub_turns=0)
        changed = True
    return st, changed


def _load_state_locked() -> dict:
    stored = _read_json(state_path())
    st = {}
    for key, default in _STATE_DEFAULTS.items():
        value = stored.get(key, default)
        st[key] = dict(default) if isinstance(default, dict) and not isinstance(value, dict) else value
    totals = st['totals'] if isinstance(st['totals'], dict) else {}
    st['totals'] = {k: totals.get(k, v) for k, v in _STATE_DEFAULTS['totals'].items()}
    st, changed = _roll(st)
    if changed or not stored:
        try:
            _write_json(state_path(), st)
        except OSError as exc:
            _log.warning('agent_zero.budget: cannot write %s (%s)', state_path(), exc)
    return st


def load_state() -> dict:
    """The running counters, with the day/week rollover already applied."""
    with _LOCK:
        return _load_state_locked()


def _mutate(fn):
    """Run ``fn(state)`` under the lock and persist whatever it returns."""
    with _LOCK:
        st = _load_state_locked()
        fn(st)
        _write_json(state_path(), st)
        return st


# ── verdicts ────────────────────────────────────────────────────────────────


def _blocked(reason: str, st: dict, cfg: dict) -> dict:
    return {'allowed': False, 'level': 'blocked', 'reason': reason, 'state': st, 'limits': cfg}


def check_turn(provider: str, model: str, est_input_tokens: int) -> dict:
    """Decide whether the next turn may run.

    Returns ``{'allowed', 'level': 'ok'|'warn'|'blocked', 'reason', 'state', 'limits'}``.
    A blocked verdict's ``reason`` is a full sentence meant to be shown to the user as-is,
    naming the ceiling that was hit and what to do about it.

    An outstanding override (see :func:`grant_override`) turns a blocked verdict into an
    allowed one and spends one of its turns. Nothing else ever bypasses a ceiling: the
    caller must not retry with a smaller model, fewer tools or a shortened message unless
    the user asked for that.
    """
    cfg = load_config()
    st = load_state()
    turn, day, week, policy = cfg['per_turn'], cfg['per_day'], cfg['per_week'], cfg['policy']
    est = int(est_input_tokens or 0)
    local = provider in LOCAL_PROVIDERS
    verdict = None

    if est > turn['max_context_tokens']:
        verdict = _blocked(
            f'this turn would need {est} tokens, the per-turn ceiling is '
            f'{turn["max_context_tokens"]} — start a new chat or shorten the message',
            st,
            cfg,
        )
    elif st['day_turns'] >= day['max_turns']:
        verdict = _blocked(
            f'Agent Zero has run {st["day_turns"]} turns today, the daily ceiling is '
            f'{day["max_turns"]} — it resumes after midnight (Amsterdam) or with an override',
            st,
            cfg,
        )
    elif not local and st['day_tokens'] >= day['hard_tokens']:
        verdict = _blocked(
            f'Agent Zero has used {st["day_tokens"]} tokens today, the daily hard ceiling is '
            f'{day["hard_tokens"]} — it resumes after midnight (Amsterdam) or with an override',
            st,
            cfg,
        )
    elif provider == 'subscription':
        verdict = _check_subscription(model, st, cfg, week)

    if verdict is not None:
        return _apply_override(verdict, local, policy)

    meter = meter_snapshot()
    seven = meter.get('seven_day_pct')
    warn = None
    if not local and st['day_tokens'] >= day['soft_tokens']:
        warn = (
            f'{st["day_tokens"]} tokens used today, the daily soft limit is '
            f'{day["soft_tokens"]} (hard stop at {day["hard_tokens"]})'
        )
    elif provider == 'subscription' and seven is not None and seven >= week['meter_reserve_pct'] - 10:
        warn = f"Claude's weekly meter is at {seven:g}%, Agent Zero stops at {week['meter_reserve_pct']:g}%"
    return {
        'allowed': True,
        'level': 'warn' if warn else 'ok',
        'reason': warn or '',
        'state': st,
        'limits': cfg,
    }


def _check_subscription(model: str, st: dict, cfg: dict, week: dict) -> dict | None:
    """The three weekly ceilings that only apply to the Claude Code login."""
    meter = meter_snapshot()
    seven = meter.get('seven_day_pct')
    if seven is not None and seven >= week['meter_reserve_pct']:
        return _blocked(
            f"Claude's weekly meter is at {seven:g}% and Agent Zero keeps a reserve above "
            f'{week["meter_reserve_pct"]:g}% — pick a local Ollama model or grant an override',
            st,
            cfg,
        )
    if 'fable' in (model or '').lower():
        fable = meter['scoped'].get('fable')
        if fable is not None and fable >= week['fable_cap_pct']:
            return _blocked(
                f'the Fable weekly limit is at {fable:g}% and Agent Zero stops at '
                f'{week["fable_cap_pct"]:g}% — pick another model or grant an override',
                st,
                cfg,
            )
    share = zero_share_pct(cached_only=True)
    if share is not None and share >= week['zero_share_cap_pct']:
        return _blocked(
            f'Agent Zero has taken {share:g}% of this Claude week and its share cap is '
            f'{week["zero_share_cap_pct"]:g}% — pick a local Ollama model or grant an override',
            st,
            cfg,
        )
    return None


def _apply_override(verdict: dict, local: bool, policy: dict) -> dict:
    """Spend one override turn on a blocked verdict, or record the block."""
    st = verdict['state']
    if st.get('override_turns_left', 0) > 0:
        st = _mutate(lambda s: s.update(override_turns_left=max(0, s['override_turns_left'] - 1)))
        return {
            'allowed': True,
            'level': 'warn',
            'reason': f'operator override ({st["override_turns_left"]} turns left): {verdict["reason"]}',
            'state': st,
            'limits': verdict['limits'],
        }
    reason = verdict['reason']
    if not local and policy.get('allow_local_when_blocked'):
        reason = f'{reason}. A local Ollama model is still available — it costs no Claude quota'
    st = _mutate(lambda s: s.update(last_block={'ts': time.time(), 'reason': reason}))
    return {'allowed': False, 'level': 'blocked', 'reason': reason, 'state': st, 'limits': verdict['limits']}


def check_tool(n_calls: int) -> bool:
    """True while another tool call fits inside ``per_turn.max_tool_calls``."""
    return int(n_calls or 0) < load_config()['per_turn']['max_tool_calls']


def record(provider: str, model: str, usage: dict) -> dict:
    """Book one finished turn's usage event (CONTRACT C ``usage``) into the counters.

    ``cost_usd`` from the backend is trusted when present; otherwise a Claude turn is
    priced with the host's price table and anything else counts as 0 $ (a local model
    costs no money and no quota).
    """
    usage = usage or {}
    tin = int(usage.get('input_tokens') or 0)
    tout = int(usage.get('output_tokens') or 0)
    tokens = tin + tout
    usd = _api_usd(provider, model, usage, tin, tout)

    def apply(st: dict) -> None:
        st['day_tokens'] += tokens
        st['day_turns'] += 1
        st['day_api_usd'] = round(st['day_api_usd'] + usd, 6)
        st['week_tokens'] += tokens
        st['week_api_usd'] = round(st['week_api_usd'] + usd, 6)
        if provider == 'subscription':
            st['week_sub_turns'] += 1
        st['totals']['turns'] += 1
        st['totals']['tokens'] += tokens
        st['totals']['api_usd'] = round(st['totals']['api_usd'] + usd, 6)

    return _mutate(apply)


def _api_usd(provider: str, model: str, usage: dict, tin: int, tout: int) -> float:
    if usage.get('cost_usd') is not None:
        try:
            return float(usage['cost_usd'])
        except (TypeError, ValueError):
            pass
    if provider not in ('subscription', 'anthropic'):
        return 0.0
    meter = _host.quota_meter()
    if meter is None:
        return 0.0
    try:
        priced = meter.price_tokens(
            model,
            tin,
            tout,
            int(usage.get('cache_write') or 0),
            int(usage.get('cache_read') or 0),
        )
    except Exception as exc:  # noqa: BLE001 - pricing is bookkeeping, never fatal
        _log.warning('agent_zero.budget: price_tokens failed (%s)', exc)
        return 0.0
    return float(priced or 0.0)


def grant_override(turns: int | None = None) -> dict:
    """Let the next ``turns`` blocked turns through (default ``policy.override_turns_granted``)."""
    granted = int(turns) if turns is not None else int(load_config()['policy']['override_turns_granted'])
    granted = max(0, min(granted, 1000))
    return _mutate(lambda s: s.update(override_turns_left=granted))


def state() -> dict:
    """Everything the budget panel shows: counters, config, share and the meter."""
    st = dict(load_state())
    meter = meter_snapshot()
    st['config'] = load_config()
    st['config_doc'] = CONFIG_DOC
    st['zero_share_pct'] = zero_share_pct(cached_only=True)
    st['meter'] = {
        'ok': meter['ok'],
        'seven_day_pct': meter['seven_day_pct'],
        'five_hour_pct': meter['five_hour_pct'],
        'scoped': meter['scoped'],
    }
    st['summary_line'] = summary_line()
    return st


def _k(n: float) -> str:
    n = float(n or 0)
    return f'{n / 1000:.0f}k' if n >= 1000 else f'{n:.0f}'


def summary_line() -> str:
    """One line (<=160 chars) for the system prompt, telling the model what it may spend.

    Uses only cached meter data -- assembling a turn must never pay for a transcript scan.
    """
    cfg = load_config()
    st = load_state()
    meter = meter_snapshot()
    seven = meter.get('seven_day_pct')
    share = zero_share_pct(cached_only=True)
    parts = [f'day {_k(st["day_tokens"])}/{_k(cfg["per_day"]["hard_tokens"])} tokens']
    parts.append(f'week meter {seven:g}%' if seven is not None else 'week meter n/a')
    cap = cfg['per_week']['zero_share_cap_pct']
    parts.append(f'Zero share {share:g}%/{cap:g}%' if share is not None else f'Zero share n/a/{cap:g}%')
    parts.append(f'tools <={cfg["per_turn"]["max_tool_calls"]}/turn')
    if st['override_turns_left']:
        parts.append(f'override {st["override_turns_left"]}')
    line = 'Budget: ' + ', '.join(parts)
    return line if len(line) <= 160 else line[:157] + '...'


def estimate_turn_tokens(system: str, messages: list, tools: list, extra: str = '') -> int:
    """Estimated input of an assembled turn, with the one estimator from CONTRACT C."""
    total = estimate_tokens(system or '') + estimate_tokens(extra or '')
    for msg in messages or []:
        content = msg.get('content')
        total += estimate_tokens(content if isinstance(content, str) else json.dumps(content, default=str))
    for tool in tools or []:
        total += estimate_tokens(json.dumps(tool, default=str))
    return total
