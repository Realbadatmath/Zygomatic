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
from datetime import datetime

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


if __name__ == '__main__':  # the CLI lives in preempt_quota_report_cli
    from zyg_dashboard.preempt_quota_report_cli import main as _cli_main

    raise SystemExit(_cli_main())
