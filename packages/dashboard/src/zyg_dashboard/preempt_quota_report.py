#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""preempt_quota_report.py — what the bank is costing, per brain, as it builds.

Two independent readings, because neither alone is trustworthy:

  * PER BRAIN, from the entry's own turn ledger — tokens by model, priced at list.
    This attributes cleanly: only that recording's turns are in it.
  * THE METER, from quota_samples.jsonl — the 7-day and 5-hour windows across the
    build. This is the thing that actually runs out, but it is contaminated: every
    other Claude session on this login (including the agent doing the work) lands
    on the same meter, so it is an UPPER bound on what the bank costs.

Run it any time: python3 preempt_quota_report.py [--since HH:MM]
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

from zyg_dashboard import preempt_bank as pb
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


PRICE = {  # $/M tokens: in, out, cache-write (1.25x in), cache-read (0.1x in)
    'claude-opus-5': (15.0, 75.0, 18.75, 1.50),
    'claude-sonnet-5': (3.0, 15.0, 3.75, 0.30),
    'claude-sonnet-4-6': (3.0, 15.0, 3.75, 0.30),
    'claude-haiku-4-5-20251001': (1.0, 5.0, 1.25, 0.10),
}
BASELINE = {
    'turns': 11,
    'out': 77580,
    'wall': 1598,
    'value': 8.00,
    'label': '09-20 baseline (all Opus, thinking on, TTS in the run)',
}


def _ts(iso):
    try:
        return datetime.fromisoformat(str(iso)).timestamp()
    except (TypeError, ValueError):
        return None


def _value(turns_path):
    """($ at list, {model: out_tokens}) for one entry's ledger."""
    val, by_model = 0.0, {}
    try:
        with open(turns_path, encoding='utf-8') as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except ValueError as _exc:
                    _zyg_log.debug('malformed turn record skipped in %s: %s', turns_path, _exc)
                    continue
                u = r.get('usage') or {}
                m = str(r.get('model') or '')
                p = PRICE.get(m) or PRICE['claude-opus-5']
                val += (
                    int(u.get('input_tokens') or 0) * p[0]
                    + int(u.get('output_tokens') or 0) * p[1]
                    + int(u.get('cache_creation_input_tokens') or 0) * p[2]
                    + int(u.get('cache_read_input_tokens') or 0) * p[3]
                ) / 1e6
                by_model[m] = by_model.get(m, 0) + int(u.get('output_tokens') or 0)
    except OSError as _exc:
        _zyg_log.warning('ledger %s unreadable, its value counts as zero: %s', turns_path, _exc)
    return val, by_model


def main():
    since = None
    if '--since' in sys.argv:
        hhmm = sys.argv[sys.argv.index('--since') + 1]
        since = datetime.now().replace(hour=int(hhmm[:2]), minute=int(hhmm[3:]), second=0).timestamp()
    bank = pb.bank_metrics()
    rows = []
    for e in bank['entries']:
        t = _ts(e.get('created_at'))
        if since and (not t or t < since):
            continue
        val, by_model = _value(os.path.join(pb.DOC_DIR, e['id'], 'turns.jsonl'))
        rows.append(dict(e, value=val, by_model=by_model, t=t))
    rows.sort(key=lambda r: r['t'] or 0)
    done = [r for r in rows if r['status'] in ('ready', 'claimed', 'consumed')]

    print(f'── {len(rows)} entries ({len(done)} banked) ' + '─' * 44)
    print('%-32s %5s %8s %8s %8s  %s' % ('topic', 'turns', 'out_tok', 'wall_s', '$ list', 'output tokens by model'))
    for r in rows:
        mix = ' '.join(
            f'{m.split("-")[1][:3]}:{v // 1000}k' if v >= 1000 else f'{m.split("-")[1][:3]}:{v}'
            for m, v in sorted(r['by_model'].items(), key=lambda kv: -kv[1])
        )
        print(
            '%-32s %5d %8d %8s %8.2f  %s'
            % (
                (r['topic'] or '')[:32],
                r['turns'],
                r['output_tokens'],
                r['build_s'] if r['build_s'] is not None else '—',
                r['value'],
                mix,
            )
        )
    if not done:
        print('\nnothing banked yet in this window')
        return

    def med(key):
        v = sorted(r[key] for r in done if r.get(key))
        return v[len(v) // 2] if v else 0

    mv, mt, mw = med('value'), med('output_tokens'), med('build_s')
    print(
        '\nMEDIAN PER BANKED BRAIN: %d turns · %s output tokens · %.0f s wall · $%.2f at list'
        % (med('turns'), f'{mt:,}', mw, mv)
    )
    print(
        '%-38s %d turns · %s output tokens · %.0f s wall · $%.2f'
        % (BASELINE['label'], BASELINE['turns'], f'{BASELINE["out"]:,}', BASELINE['wall'], BASELINE['value'])
    )
    print('  → %.1fx cheaper, %.1fx faster' % (BASELINE['value'] / mv if mv else 0, BASELINE['wall'] / mw if mw else 0))

    # ── the meter, with its contamination stated ────────────────────────────
    samples = []
    try:
        with open(os.path.join(pb.RUNTIME, 'quota_samples.jsonl'), encoding='utf-8') as fh:
            for line in fh:
                if line.strip():
                    try:
                        samples.append(json.loads(line))
                    except ValueError as _exc:
                        _zyg_log.debug('malformed quota sample skipped: %s', _exc)
    except OSError as _exc:
        _zyg_log.warning('quota_samples.jsonl unreadable, reporting the meter as empty: %s', _exc)
    samples.sort(key=lambda s: s.get('ts') or 0)
    t0 = min((r['t'] for r in rows if r['t']), default=None)
    win = [s for s in samples if t0 and (s.get('ts') or 0) >= t0 - 900]
    if win and len(win) >= 2:
        print('\n── the meter across the build (ALL sessions on this login, not the bank alone) ──')
        print('%-16s %8s %8s' % ('sample', '7-day %', '5-hour %'))
        for s in win[-8:]:
            print(
                '%-16s %8s %8s'
                % (
                    datetime.fromtimestamp(s['ts']).strftime('%m-%d %H:%M'),
                    (s.get('seven_day') or {}).get('pct'),
                    (s.get('five_hour') or {}).get('pct'),
                )
            )
        d7 = [(s.get('seven_day') or {}).get('pct') for s in win if (s.get('seven_day') or {}).get('pct') is not None]
        d5 = [(s.get('five_hour') or {}).get('pct') for s in win if (s.get('five_hour') or {}).get('pct') is not None]
        # The meter is the WHOLE login. Charge the bank only its measured share of what
        # was billed in the same window (2026-09-23: nine sessions were running).
        share_out = share_list = None
        try:
            from zyg_dashboard import preempt_meter_share as pms

            sh = pms.bank_share(win[0]['ts'])
            share_out, share_list = sh['share_out'], sh['share_list']
            print(
                '\n%d sessions billed to this login in the window; the bank is %.1f %% of it by output '
                'value, %.1f %% with cached tokens counted.'
                % (sh['sessions'], 100 * (share_out or 0), 100 * (share_list or 0))
            )
        except Exception as exc:  # noqa: BLE001
            print(f'(session attribution unavailable: {exc})')
        for label, series in (('7-day', d7), ('5-hour', d5)):
            if len(series) >= 2 and series[-1] >= series[0]:
                moved = series[-1] - series[0]
                n = max(len(done), 1)
                print('%s window moved %+0.0f points while %d brains were banked' % (label, moved, len(done)))
                if share_out is not None and share_list is not None:
                    lo, hi = sorted((moved * share_list / n, moved * share_out / n))
                    print("   the bank's share: %.3f-%.3f points per brain" % (lo, hi))
                    if label == '7-day':
                        print('   → 100 brains ≈ %.1f-%.1f %% of a Claude week' % (lo * 100, hi * 100))
                else:
                    print('   ≤ %.2f points each if the bank were the only thing running' % (moved / n))
    print('\nlist $ is what the same tokens would cost on the API — the subscription bills none of it;')
    print('it is here because it attributes per brain, which the shared meter cannot.')


if __name__ == '__main__':
    main()
