# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`section_analytics(days)` — the payload: window, unit times, the cards, the envelope."""

from __future__ import annotations

from . import section_helpers as sh


def section_analytics(days=30, now=None, fresh=False):
    """The whole analytics payload for a `days`-wide window.

    `now` overrides the clock (tests and replays); `fresh` is accepted for call-site
    compatibility and ignored — every stage reads its sources on each call anyway.
    The stages run in board order and each one writes its cards onto the shared
    context: production (volume / times / cost), capacity and income, system, yield,
    mix, subscription and energy, the Approval-Queue backlog, and last the two cards
    that are allowed to fail. See `section_helpers` for each stage.
    """
    ctx = sh.build_context(days, now)
    sh.add_production_cards(ctx)
    sh.add_capacity_income_cards(ctx)
    sh.add_system_cards(ctx)
    ctx.card_backlog = sh.backlog_card(ctx)
    sh.add_optional_cards(ctx)
    return sh.envelope(ctx)
