# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .pricing import (
    CRED_PATH,
    DAY,
    LEGACY_CLI_UNKNOWN_MODEL,
    OAUTH_BETA,
    PRICING,
    PROJECTS_DIR,
    QuotaError,
    SAMPLES_PATH,
    SCAN_CAP_DAYS,
    STATUS_PATH,
    TZ,
    USAGE_URL,
    WEEK,
    _zyg_log,
    datetime,
    fcntl,
    json,
    load_config,
    os,
    price_usage,
    price_usage_total,
    time,
    urllib,
    urlsplit,
    weekly_price,
)
from .transcripts import _ts_iso, _write_json_atomic, aggregate, aggregate_lanes, daily_series, scan_transcripts

# ── Claude's own meter ───────────────────────────────────────────────────────


def _credentials() -> dict:
    try:
        with open(CRED_PATH, encoding='utf-8') as fh:
            cred = (json.load(fh) or {}).get('claudeAiOauth') or {}
    except (OSError, ValueError) as exc:
        raise QuotaError(f'no Claude login credentials at {CRED_PATH}: {type(exc).__name__}') from exc
    if not cred.get('accessToken'):
        raise QuotaError('the Claude login has no OAuth access token (not logged in with a subscription?)')
    exp = cred.get('expiresAt')
    if exp and float(exp) / 1000.0 < time.time():
        when = datetime.fromtimestamp(float(exp) / 1000.0, TZ).isoformat(timespec='minutes')
        raise QuotaError(f'the OAuth token expired at {when}; any interactive claude turn refreshes it')
    return cred


def fetch_usage(timeout: float = 10.0) -> dict:
    """The raw payload of /api/oauth/usage for this login."""
    cred = _credentials()
    # USAGE_URL is overridable from the environment, so the scheme is checked before the
    # OAuth bearer token is attached to it: file:// or a custom handler would otherwise
    # see the token. safe_urlopen cannot be used here — it takes a URL, not a Request.
    scheme = urlsplit(USAGE_URL).scheme.lower()
    if scheme not in ('http', 'https'):
        raise QuotaError(f'refusing to send the OAuth token to a {scheme or "scheme-less"} URL: {USAGE_URL}')
    req = urllib.request.Request(  # nosec B310  # noqa: S310  scheme checked on the line above
        USAGE_URL,
        headers={
            'Authorization': f'Bearer {cred["accessToken"]}',
            'anthropic-beta': OAUTH_BETA,
            'Content-Type': 'application/json',
            'User-Agent': 'zygomatic-quota-meter/1',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310  # noqa: S310  scheme checked above
            return json.loads(resp.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as exc:
        body = ''
        try:
            body = exc.read().decode('utf-8', 'replace')[:200]
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('HTTP error body not readable, reporting the reason only: %s', _exc)
        raise QuotaError(f'usage endpoint answered HTTP {exc.code}: {body or exc.reason}') from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise QuotaError(f'usage endpoint unreachable: {type(exc).__name__}: {exc}'[:200]) from exc


def _limit(obj) -> dict:
    obj = obj or {}
    util = obj.get('utilization')
    return {
        'pct': float(util) if isinstance(util, (int, float)) else None,
        'resets_at': _ts_iso(obj.get('resets_at')) if obj.get('resets_at') else None,
    }


def parse_usage_payload(payload: dict, now: float = None, tier: str = None) -> dict:
    """Raw payload -> one sample row. Only what the method needs; the raw key list is
    kept so a renamed field shows up in the record instead of vanishing."""
    now = now or time.time()
    five = _limit(payload.get('five_hour'))
    seven = _limit(payload.get('seven_day'))
    breakdown = payload.get('seven_day_breakdown') or {}
    ws = _ts_iso(breakdown.get('window_started_at')) if breakdown.get('window_started_at') else None
    if ws is None and seven['resets_at']:
        ws = seven['resets_at'] - WEEK
    seven['window_started_at'] = ws
    scoped = []
    for lim in payload.get('limits') or []:
        if not isinstance(lim, dict) or lim.get('kind') in ('session', 'weekly_all'):
            continue
        scope = lim.get('scope') or {}
        model = (scope.get('model') or {}) if isinstance(scope, dict) else {}
        scoped.append(
            {
                'kind': lim.get('kind'),
                'name': model.get('display_name')
                or model.get('id')
                or (scope.get('surface') if isinstance(scope, dict) else None)
                or lim.get('kind'),
                'pct': float(lim['percent']) if isinstance(lim.get('percent'), (int, float)) else None,
                'resets_at': _ts_iso(lim.get('resets_at')) if lim.get('resets_at') else None,
                'severity': lim.get('severity'),
            }
        )
    surfaces = {}
    for row in breakdown.get('rows') or []:
        if isinstance(row, dict) and row.get('key'):
            surfaces[row['key']] = float(row.get('percent') or 0)
    extra = payload.get('extra_usage') or {}
    return {
        'ts': now,
        'five_hour': five,
        'seven_day': seven,
        'scoped': scoped,
        'surfaces': surfaces,
        'extra_usage_enabled': bool(extra.get('is_enabled')),
        'tier': tier,
        'raw_keys': sorted(k for k, v in payload.items() if v is not None),
    }


def _append_sample(sample: dict) -> None:
    os.makedirs(os.path.dirname(SAMPLES_PATH), exist_ok=True)
    with open(SAMPLES_PATH, 'a', encoding='utf-8') as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(json.dumps(sample, separators=(',', ':')) + '\n')
        fh.flush()
        fcntl.flock(fh, fcntl.LOCK_UN)


def _write_status(**fields) -> None:
    st = {}
    try:
        with open(STATUS_PATH, encoding='utf-8') as fh:
            st = json.load(fh) or {}
    except (OSError, ValueError) as _exc:
        _zyg_log.debug('no previous status at %s, starting from an empty one: %s', STATUS_PATH, _exc)
    st.update(fields)
    try:
        _write_json_atomic(STATUS_PATH, st)
    except OSError as _exc:
        _zyg_log.warning('status %s not written, the meter keeps the old values: %s', STATUS_PATH, _exc)


def read_status() -> dict:
    try:
        with open(STATUS_PATH, encoding='utf-8') as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        return {}


def sample(now: float = None) -> dict:
    """Fetch Claude's meter once and append it to the sample ledger."""
    now = now or time.time()
    try:
        cred = _credentials()
        payload = fetch_usage()
    except QuotaError as exc:
        _write_status(last_error=str(exc), last_error_ts=now)
        raise
    row = parse_usage_payload(payload, now, tier=cred.get('rateLimitTier') or cred.get('subscriptionType'))
    _append_sample(row)
    _write_status(
        last_ok_ts=now,
        last_error=None,
        last_error_ts=None,
        tier=row['tier'],
        seven_day_pct=row['seven_day']['pct'],
        five_hour_pct=row['five_hour']['pct'],
    )
    return row


def read_samples(since: float = None, limit: int = 5000) -> list:
    rows = []
    try:
        with open(SAMPLES_PATH, encoding='utf-8') as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError as _exc:
                    _zyg_log.debug('malformed quota sample skipped: %s', _exc)
                    continue
                if isinstance(r, dict) and (since is None or (r.get('ts') or 0) >= since):
                    rows.append(r)
    except OSError:
        return []
    return rows[-limit:]


# ── the calculation ──────────────────────────────────────────────────────────


def _lane_split(lane_usage: dict, api_total: float, consumed_here, eur_per_usd: float) -> dict:
    """The lane rows and their two roll-ups, priced the same way the per-model rows are:
    each lane's share of the week's API-equivalent cost, applied to the subscription value
    the meter says Claude Code consumed. `production_pct` is the headline — the share of
    the work on THIS machine that went into producing content rather than building the
    stack."""
    rows = []
    for (lane, side, label), row in (lane_usage or {}).items():
        usd = price_usage_total(row['models'])
        rows.append(
            {
                'lane': lane,
                'side': side,
                'label': label,
                'tree': row.get('tree'),
                'sessions': row['sessions'],
                'usage': row['usage'],
                'api_usd': usd,
            }
        )
    total = sum(r['api_usd'] for r in rows)
    basis = api_total if api_total else total
    sides = {'production': 0.0, 'infrastructure': 0.0}
    by_lane = {'production': 0.0, 'session_tree': 0.0, 'interactive': 0.0}
    for r in rows:
        r['share'] = (r['api_usd'] / basis) if basis else None
        r['api_eur'] = round(r['api_usd'] * eur_per_usd, 4)
        r['subscription_eur'] = (
            round(consumed_here * r['share'], 4) if consumed_here is not None and r['share'] is not None else None
        )
        r['api_usd'] = round(r['api_usd'], 4)
        if r['share'] is not None:
            r['share'] = round(r['share'], 4)
        sides[r['side']] = sides.get(r['side'], 0.0) + r['api_usd']
        by_lane[r['lane']] = by_lane.get(r['lane'], 0.0) + r['api_usd']
    rows.sort(key=lambda r: (r['side'] != 'production', -r['api_usd']))

    def roll(usd):
        share = (usd / basis) if basis else None
        return {
            'api_usd': round(usd, 4),
            'api_eur': round(usd * eur_per_usd, 4),
            'share': round(share, 4) if share is not None else None,
            'pct': round(share * 100, 1) if share is not None else None,
            'subscription_eur': (
                round(consumed_here * share, 4) if consumed_here is not None and share is not None else None
            ),
        }

    return {
        'rows': rows,
        'sides': {k: roll(v) for k, v in sides.items()},
        'by_lane': {k: roll(v) for k, v in by_lane.items()},
        'production_pct': roll(sides.get('production', 0.0))['pct'],
        'api_usd': round(total, 4),
        'unclassified_api_usd': round(max(0.0, api_total - total), 4) if api_total else 0.0,
    }


def compute(
    cfg: dict, sample_row: dict, week_usage: dict, session_usage: dict, now: float, lane_usage: dict = None
) -> dict:
    """Pure arithmetic of the method in the docstring. `week_usage` and `session_usage`
    are {model: usage vector} for Claude's current weekly and 5-hour windows; `lane_usage`
    is `aggregate_lanes` over the same weekly window."""
    W = weekly_price(cfg)
    eur_per_usd = float(cfg.get('eur_per_usd') or 0)
    seven = (sample_row or {}).get('seven_day') or {}
    five = (sample_row or {}).get('five_hour') or {}
    util = seven.get('pct')
    ws, we = seven.get('window_started_at'), seven.get('resets_at')
    consumed = (util or 0) / 100.0 * W if util is not None else None
    surfaces = (sample_row or {}).get('surfaces') or {}
    cc_share = surfaces.get('claude_code')
    cc_share = (cc_share / 100.0) if isinstance(cc_share, (int, float)) and surfaces else 1.0
    consumed_here = consumed * cc_share if consumed is not None else None

    rows = []
    api_total = 0.0
    unpriced = []
    for model, u in week_usage.items():
        usd = price_usage(model, u)
        if usd is None:
            unpriced.append(model)
            continue
        api_total += usd
        rows.append({'model': model, 'usage': u, 'api_usd': usd})
    for r in rows:
        r['share'] = (r['api_usd'] / api_total) if api_total else None
        r['api_eur'] = r['api_usd'] * eur_per_usd
        r['subscription_eur'] = (
            (consumed_here * r['share']) if consumed_here is not None and r['share'] is not None else None
        )
        r['api_usd'] = round(r['api_usd'], 4)
        r['api_eur'] = round(r['api_eur'], 4)
        if r['subscription_eur'] is not None:
            r['subscription_eur'] = round(r['subscription_eur'], 4)
        if r['share'] is not None:
            r['share'] = round(r['share'], 4)
    rows.sort(key=lambda r: -r['api_usd'])

    elapsed = (now - ws) if ws else None
    frac = max(1e-6, min(1.0, elapsed / WEEK)) if elapsed is not None else None
    session_rows = []
    session_total = 0.0
    for model, u in session_usage.items():
        usd = price_usage(model, u)
        if usd is None:
            continue
        session_total += usd
        session_rows.append({'model': model, 'usage': u, 'api_usd': round(usd, 4)})
    session_rows.sort(key=lambda r: -r['api_usd'])

    eur_per_api_usd = (consumed_here / api_total) if consumed_here is not None and api_total > 0 else None
    return {
        'weekly_price': round(W, 4),
        'price_per_pct': round(W / 100.0, 4),
        'utilization_pct': util,
        'window_started_at': ws,
        'resets_at': we,
        'elapsed_fraction': round(frac, 4) if frac is not None else None,
        'consumed': round(consumed, 4) if consumed is not None else None,
        'consumed_claude_code': round(consumed_here, 4) if consumed_here is not None else None,
        'consumed_other_surfaces': round(consumed - consumed_here, 4) if consumed is not None else None,
        'remaining': round(W - consumed, 4) if consumed is not None else None,
        'projected_utilization_pct': round(util / frac, 1) if util is not None and frac else None,
        'projected_api_usd': round(api_total / frac, 2) if frac else None,
        'api_usd': round(api_total, 4),
        'api_eur': round(api_total * eur_per_usd, 4),
        'pct_per_api_usd': round(util / api_total, 4) if util is not None and api_total > 0 else None,
        'eur_per_api_usd': round(eur_per_api_usd, 4) if eur_per_api_usd is not None else None,
        'subscription_cheaper': (eur_per_api_usd < eur_per_usd) if eur_per_api_usd is not None else None,
        'models': rows,
        'unpriced_models': unpriced,
        'lanes': _lane_split(lane_usage or {}, api_total, consumed_here, eur_per_usd),
        'session': {
            'utilization_pct': five.get('pct'),
            'resets_at': five.get('resets_at'),
            'api_usd': round(session_total, 4),
            'models': session_rows,
        },
        'claude_code_share': round(cc_share, 4),
    }


def _history(samples: list) -> dict:
    keys = [datetime.fromtimestamp(s['ts'], TZ).isoformat(timespec='minutes') for s in samples]
    return {
        'ts': [s['ts'] for s in samples],
        'labels': keys,
        'seven_day_pct': [(s.get('seven_day') or {}).get('pct') for s in samples],
        'five_hour_pct': [(s.get('five_hour') or {}).get('pct') for s in samples],
    }


def _implied_rates(samples: list, files: dict) -> list:
    """Between consecutive samples inside one weekly window: Δ utilization vs the
    API-equivalent cost of the transcripts in that interval. A stable % per dollar
    says the proportional split holds; a drift says a model is weighted differently."""
    out = []
    prev = None
    for s in samples:
        seven = s.get('seven_day') or {}
        if seven.get('pct') is None or not seven.get('window_started_at'):
            prev = None
            continue
        if prev and (prev.get('seven_day') or {}).get('window_started_at') == seven['window_started_at']:
            d_pct = seven['pct'] - prev['seven_day']['pct']
            usage = aggregate(files, prev['ts'], s['ts'])
            usd = sum((price_usage(m, u) or 0.0) for m, u in usage.items())
            if d_pct > 0 and usd > 0.05:
                out.append(
                    {
                        'from': prev['ts'],
                        'to': s['ts'],
                        'delta_pct': round(d_pct, 2),
                        'api_usd': round(usd, 3),
                        'pct_per_usd': round(d_pct / usd, 3),
                    }
                )
        prev = s
    return out[-40:]


def report(days: int = 7, now: float = None, fresh: bool = False, projects_dir: str = None) -> dict:
    now = now or time.time()
    cfg = load_config()
    days_eff = days if days else SCAN_CAP_DAYS
    days_eff = max(7, min(days_eff, SCAN_CAP_DAYS))
    status = read_status()
    samples = read_samples()
    latest = samples[-1] if samples else None
    fetch_note = None
    if fresh or latest is None or now - (latest.get('ts') or 0) > float(cfg.get('sample_max_age_s') or 900):
        try:
            latest = sample(now)
            samples.append(latest)
            status = read_status()
        except QuotaError as exc:
            fetch_note = str(exc)
    seven = (latest or {}).get('seven_day') or {}
    ws = seven.get('window_started_at') or (now - WEEK)
    since = min(ws, now - days_eff * DAY) - DAY
    scan = scan_transcripts(since, projects_dir=projects_dir)
    files = scan['files']
    week_usage = aggregate(files, ws, now)
    five = (latest or {}).get('five_hour') or {}
    ss = (five.get('resets_at') - 5 * 3600) if five.get('resets_at') else now - 5 * 3600
    session_usage = aggregate(files, ss, now)
    lane_usage = aggregate_lanes(files, ws, now, cfg.get('lanes'))
    calc = compute(cfg, latest or {}, week_usage, session_usage, now, lane_usage)
    range_usage = aggregate(files, now - days_eff * DAY, now)
    range_rows = []
    for model, u in range_usage.items():
        usd = price_usage(model, u)
        range_rows.append(
            {
                'model': model,
                'usage': u,
                'api_usd': round(usd, 4) if usd is not None else None,
                'api_eur': round(usd * float(cfg['eur_per_usd']), 4) if usd is not None else None,
            }
        )
    range_rows.sort(key=lambda r: -(r['api_usd'] or 0))
    win_samples = [s for s in samples if (s.get('ts') or 0) >= now - days_eff * DAY]
    notes = [
        "Utilization percentages are Claude's own meter for this login (the /usage endpoint), sampled "
        'every 10 minutes by zyg-quota-meter.timer; the weekly window is fixed, starts at '
        '"window start" and resets to 0 % at "resets".',
        'Tokens per model come from every session transcript of this login on this machine '
        '(~/.claude/projects, interactive and claude -p alike), de-duplicated by message id.',
        'API-equivalent = Anthropic list price with cache writes at 2x input (1-hour TTL, which Claude '
        'Code uses) and cache reads at 10 % (Claude Fable 5.1: $0.25/MTok). This is what the same work '
        'would cost on API billing; nothing here is billed per token.',
        f'Subscription: {cfg["plan_label"]} at {cfg["subscription_price"]:g} {cfg["currency"]} per '
        + ('calendar month = ' if cfg.get('billing') != 'days' else f'{cfg.get("billing_days")} days = ')
        + f'{calc["weekly_price"]:.2f} {cfg["currency"]} per Claude week; one utilization point = '
        f'{calc["price_per_pct"]:.3f} {cfg["currency"]}.',
        "Per-model subscription cost splits the consumed weekly value in proportion to each model's "
        'API-equivalent cost this week (the meter weights models by price; "% per API-$" shows whether that '
        'proportion holds between samples). Usage on other surfaces (claude.ai chats, Cowork) shares the '
        'meter but leaves no transcript here and is shown separately.',
        f'EUR/USD {cfg["eur_per_usd"]:g} is a configured value (data/runtime/quota_config.json), not a live rate.',
        "Production workflows vs infrastructure is this stack's own split, not one Claude reports: a "
        "workflow is an unattended `claude -p` in a pipeline's own CLI directory (documentary, "
        'architecture assistant, Vicky, the app assistants); a session-tree executor names its tree in '
        'its first line and counts as production or infrastructure by what that tree was building; '
        'every other session is an operator at an editor, which is always infrastructure. The keyword '
        'lists behind the tree call are `lanes` in quota_config.json, and each lane costs the same way '
        "a model does — its share of the week's API-equivalent, applied to what Claude Code consumed.",
    ]
    if fetch_note:
        notes.insert(0, f'Live fetch failed: {fetch_note}. Showing the last sample.')
    if not latest:
        notes.insert(
            0,
            "No sample of Claude's meter yet: utilization and subscription columns are empty until "
            'the first successful fetch.',
        )
    return {
        'config': {
            k: cfg[k]
            for k in ('subscription_price', 'currency', 'billing', 'billing_days', 'eur_per_usd', 'plan_label')
        },
        'sample': latest,
        'sample_age_s': round(now - latest['ts']) if latest else None,
        'status': {
            'last_ok': status.get('last_ok_ts'),
            'last_error': status.get('last_error'),
            'last_error_ts': status.get('last_error_ts'),
            'samples': len(samples),
            'tier': status.get('tier'),
        },
        'week': calc,
        'range': {
            'days': days_eff,
            'requested_days': days,
            'models': range_rows,
            'api_usd': round(sum(r['api_usd'] or 0 for r in range_rows), 4),
            'daily': daily_series(files, now - days_eff * DAY, now),
        },
        'history': _history(win_samples),
        'implied_rates': _implied_rates(win_samples, files),
        'scan': {
            'files': len(files),
            'parsed_now': scan['parsed_now'],
            'from_cache': scan['skipped'],
            'errors': scan['errors'],
            'messages': sum(d.get('messages', 0) for d in files.values()),
            'projects_dir': projects_dir or PROJECTS_DIR,
        },
        'pricing': [
            {
                'model_prefix': p[0],
                'input': p[1],
                'output': p[2],
                'cache_write_5m': p[3],
                'cache_write_1h': p[4],
                'cache_read': p[5],
            }
            for p in PRICING
        ],
        'legacy_cli': {
            'version': '2.1.74',
            'unknown_model_rates': LEGACY_CLI_UNKNOWN_MODEL,
            'note': 'What the installed CLI charges any model newer than Sonnet/Opus 4.6 in its '
            'total_cost_usd: Opus rates with a flat 1.25x cache write. Sonnet 5 reads 2.2x too high, '
            'Opus 5 0.87x (missing 1-hour cache premium), Haiku 4.5 about right.',
        },
        'notes': notes,
    }
