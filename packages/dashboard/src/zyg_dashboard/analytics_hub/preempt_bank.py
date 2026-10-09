# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Pre-emptive bank card (2026-09-23)."""

from __future__ import annotations

from .preempt_bank_figures import (
    bank_figures,
    chart_block,
    delta_block,
    facts_block,
    headline_block,
    notes_block,
)


# ── Pre-emptive bank (2026-09-23) ────────────────────────────────────────────
# The bank records every TEXT Claude call of an episode now so the episode can be
# rendered later with the subscription out. This card is the whole ledger of that
# trade: what a banked brain costs to record, how far the bank is from its target,
# and — once an entry has been replayed — what the replay actually saved and what
# it still had to buy live. Nothing is estimated that a file does not say.


def _preempt_targets():
    try:
        from zyg_dashboard import approval_queue_settings as _aqs

        return int(_aqs.get('preempt', 'documentary_target') or 100), int(_aqs.get('preempt', 'songs_target') or 100)
    except Exception:  # noqa: BLE001
        return 100, 100


def preempt_bank_card(now, days, since, keys, weekly, bucket, trend_keys, fkeys, d7, d14, d8, today):
    from zyg_dashboard import preempt_bank as pb

    bank = pb.bank_metrics()
    dt, st_target = _preempt_targets()
    f = bank_figures(bank, dt, st_target, trend_keys, now)
    return {
        'id': 'preempt_bank',
        'lane': 'production',
        'title': 'Pre-emptive generation bank',
        'question': 'How much of the coming production is already paid for, and what did banking it cost?',
        'headline': headline_block(f),
        'delta': delta_block(f, d7, d14, d8),
        'chart': chart_block(f, keys, weekly, bucket, fkeys),
        'facts': facts_block(f),
        'table': {
            'cols': ['Day', 'Brains banked', 'Failed recordings', 'Output tokens', 'Song briefs'],
            'rows': f.per_day_rows,
        },
        'notes': notes_block(f),
    }
