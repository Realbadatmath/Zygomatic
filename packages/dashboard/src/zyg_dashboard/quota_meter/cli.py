# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""quota_meter.py — the Claude subscription quota meter and the two costs behind it. 2026-09-17.

Why this exists. Until today every "cost" the GUI showed for Claude Code work was the
CLI's own `total_cost_usd`, labelled "of quota" in the Architecture Studio panel and
"API-equivalent" in the Metrics tab. Measured 2026-09-17 against three real sessions:

  * the number is priced by the CLI that ran the job — /usr/local/bin/claude is 2.1.74
    (March 2026) whose price table stops at Opus 4.6 / Sonnet 4.6. Any newer model is
    "unknown" and priced at the Opus rate: a 49-turn Sonnet 5 job was reported as
    $5.8446; at Sonnet 5 list price it is $2.63 (the CLI's own arithmetic reproduced to
    the cent with its table: input 5, output 25, cache write 6.25, cache read 0.5);
  * it ignores the 1-hour cache-write premium Claude Code actually pays (2x input, not
    1.25x): an Opus 5 job reported as $3.9769 is $4.57 at list;
  * none of it is a quota. The login is a Max subscription: nothing is billed per token,
    and Claude meters usage as PERCENTAGES of a session (5-hour) and a weekly window.

What Claude exposes (GET https://api.anthropic.com/api/oauth/usage with the login's
OAuth token, the same call `/usage` makes in the CLI): `five_hour` and `seven_day`
{utilization %, resets_at}, scoped weekly limits per model family (`limits[]`), the
week's start (`seven_day_breakdown.window_started_at`) and a per-surface split of the
week (Claude Code / Chats / Cowork / Other). The weekly window is a FIXED 7-day window
that resets to 0 % at `resets_at` — the operator's "renewed every week" is right; it
is not a rolling window and it is not a calendar week.

THE TWO COSTS, and the method (every number on the Quota tab comes from these lines):

  1. API-equivalent cost = what the same tokens would have cost on API billing.
     Per model: input, output, cache write (5-minute and 1-hour buckets priced
     separately), cache read and web-search requests at Anthropic list price (table
     PRICING below, checked against the claude-api reference cached 2026-06-24). The
     tokens come from the session transcripts under ~/.claude/projects — every session
     of this login on this machine, interactive and `claude -p` alike, de-duplicated
     by message id (a multi-block message is written once per block, same usage).

  2. Subscription cost = the plan price spread over Claude's own weekly window.
     Weekly price W: the plan bills per calendar month, so W = price x 12 / 52.1775
     (a 28-day "4 weeks = 180 EUR" would count 13 payments a year; `billing_days`
     switches to that basis if the invoices really are every 28 days).
     Consumed this week  = seven_day.utilization % x W        (Claude's number, not ours)
     Cost of one % point = W / 100
     Per model           = consumed x (API-equivalent cost of the model this week
                                       / API-equivalent cost of all models this week)
     The split assumes the meter charges models in proportion to their list price.
     The tab prints the implied "% per API-dollar" so a drift in that assumption is
     visible instead of silent, and the surface split tells how much of the week was
     not Claude Code (chats on claude.ai share the same meter and leave no transcript
     here — that part is attributed to "other surfaces", never to a model).
     Effective rate      = consumed EUR / API-equivalent USD of the week: below the
     EUR/USD rate the subscription is the cheaper way to buy this week's work.

Nothing here refreshes the OAuth token: the CLI does that on any interactive turn. An
expired token is reported as such and the last sample stays on screen.

CLI:  python3 quota_meter.py sample            # one fetch -> data/runtime/quota_samples.jsonl
      python3 quota_meter.py report [--days 7] [--json]
      python3 quota_meter.py scan [--days 7]   # (re)build the transcript cache only
Served by metrics_hub.section('quota') at /api/metrics/hub/quota?days=N.
"""

from __future__ import annotations

from .pricing import DAY, QuotaError, TZ, datetime, json, sys, time
from .calculation import report, sample
from .transcripts import scan_transcripts

# ── CLI ──────────────────────────────────────────────────────────────────────


def _fmt_report(r: dict) -> str:
    w = r['week']
    cfg = r['config']
    cur = cfg['currency']
    lines = [
        f'Claude quota meter — {cfg["plan_label"]} · {cfg["subscription_price"]:g} {cur}/{cfg["billing"]}'
        f' = {w["weekly_price"]:.2f} {cur}/week'
    ]
    if r['sample']:
        s = r['sample']
        lines.append(
            f'week   {w["utilization_pct"]}% used (sample {r["sample_age_s"]} s old) · window '
            f'{_iso(w["window_started_at"])} → resets {_iso(w["resets_at"])}'
            f' · consumed {w["consumed"]:.2f} {cur} · remaining {w["remaining"]:.2f} {cur}'
            f' · projected {w["projected_utilization_pct"]}% at week end'
        )
        lines.append(
            f'session {s["five_hour"].get("pct")}% used · resets {_iso(s["five_hour"].get("resets_at"))}'
            f' · {w["session"]["api_usd"]:.2f} $ API-equivalent in this 5 h window'
        )
        if s.get('scoped'):
            lines.append('scoped ' + ' · '.join(f'{x["name"]} {x["pct"]}%' for x in s['scoped']))
        if s.get('surfaces'):
            lines.append('surfaces ' + ' · '.join(f'{k} {v:g}%' for k, v in s['surfaces'].items()))
    else:
        lines.append('no sample of the meter yet')
    lines.append(
        f'API-equivalent this week: ${w["api_usd"]:.2f} (~{w["api_eur"]:.2f} {cur}) · '
        f'{w["pct_per_api_usd"]} % per API-$ · effective {w["eur_per_api_usd"]} {cur} per API-$ · '
        f'subscription cheaper: {w["subscription_cheaper"]}'
    )
    lines.append(
        f'{"model":<24}{"in":>10}{"out":>10}{"cache w":>11}{"cache r":>12}{"API $":>9}{"share":>7}{"sub " + cur:>9}'
    )
    for m in w['models']:
        u = m['usage']
        lines.append(
            f'{m["model"]:<24}{u["input"]:>10}{u["output"]:>10}{u["cache_5m"] + u["cache_1h"]:>11}{u["cache_read"]:>12}'
            f'{m["api_usd"]:>9.2f}{(m["share"] or 0) * 100:>6.1f}%{(m["subscription_eur"] if m["subscription_eur"] is not None else 0):>9.2f}'
        )
    L = w.get('lanes') or {}
    if L.get('rows'):
        sd, bl = L['sides'], L['by_lane']
        lines.append(
            f'production workflows {sd["production"]["pct"]}% '
            f'({sd["production"]["subscription_eur"]:.2f} {cur}) · '
            f'building infrastructure {sd["infrastructure"]["pct"]}% '
            f'({sd["infrastructure"]["subscription_eur"]:.2f} {cur})'
            if sd['production']['subscription_eur'] is not None
            else f'production workflows {sd["production"]["pct"]}% · '
            f'building infrastructure {sd["infrastructure"]["pct"]}%'
        )
        lines.append('  by lane: ' + ' · '.join(f'{k.replace("_", " ")} {v["pct"]}%' for k, v in bl.items()))
        lines.append(f'  {"side":<15}{"lane":<14}{"what":<46}{"sess":>6}{"API $":>9}{"share":>7}')
        for row in L['rows'][:12]:
            lines.append(
                f'  {row["side"]:<15}{row["lane"].replace("_", " "):<14}{row["label"][:44]:<46}'
                f'{row["sessions"]:>6}{row["api_usd"]:>9.2f}{(row["share"] or 0) * 100:>6.1f}%'
            )
        if len(L['rows']) > 12:
            lines.append(f'  … {len(L["rows"]) - 12} more')
    sc = r['scan']
    lines.append(
        f'transcripts: {sc["files"]} files, {sc["messages"]} messages, {sc["parsed_now"]} parsed now, '
        f'{sc["from_cache"]} from cache' + (f', errors {sc["errors"]}' if sc['errors'] else '')
    )
    for n in r['notes'][:2]:
        lines.append('note: ' + n)
    return '\n'.join(lines)


def _iso(ts):
    return datetime.fromtimestamp(ts, TZ).isoformat(timespec='minutes') if ts else '—'


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else 'report'
    days = int(argv[argv.index('--days') + 1]) if '--days' in argv else 7
    if cmd == 'sample':
        try:
            row = sample()
        except QuotaError as exc:
            print(f'quota sample failed: {exc}', file=sys.stderr)
            return 1
        print(
            f'sampled: week {row["seven_day"]["pct"]}% (resets {_iso(row["seven_day"]["resets_at"])}) · '
            f'session {row["five_hour"]["pct"]}% (resets {_iso(row["five_hour"]["resets_at"])}) · tier {row["tier"]}'
        )
        return 0
    if cmd == 'scan':
        t0 = time.time()
        res = scan_transcripts(time.time() - max(7, days) * DAY)
        print(
            f'scanned {len(res["files"])} transcripts in {time.time() - t0:.1f} s: {res["parsed_now"]} parsed, '
            f'{res["skipped"]} from cache, {res["error_count"]} errors'
        )
        return 0
    if cmd == 'report':
        r = report(days=days, fresh='--fresh' in argv)
        print(json.dumps(r, indent=1, default=str) if '--json' in argv else _fmt_report(r))
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
