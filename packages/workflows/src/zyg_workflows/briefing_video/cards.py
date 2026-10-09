# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.briefing_video.cards — chart 3: the matchup card, the entity focus cards, the parlay sheet, the generic card.

Moved verbatim out of briefing_video.py (lines 685-1017); zero logic changes.
"""

from __future__ import annotations

from zyg_workflows.briefing_video.base import (
    H,
    W,
    _fig,
    _fit,
    _fit_px,
    _header,
    _panel,
    _paste,
    _rule,
    _save,
    _uniform_size,
    _wrap,
    os,
    theme,
)


# ── chart 3: the matchup card + entity focus cards (sports) ─────────────────


def _initials_disc(fig, th, cx, cy, r_h, col, text, fontsize):
    """A round disc in figure coordinates. Figure coords are not square (16:9), so
    a matplotlib Circle drawn in them renders as a flattened ellipse — the width
    has to be scaled by the aspect ratio by hand."""
    from matplotlib.patches import Ellipse

    fig.patches.append(
        Ellipse(
            (cx, cy),
            r_h * 2 * (H / float(W)),
            r_h * 2,
            transform=fig.transFigure,
            facecolor=th['panel'],
            edgecolor=col,
            linewidth=3,
        )
    )
    fig.text(cx, cy, text, color=col, fontsize=fontsize, fontweight='bold', ha='center', va='center')


def _entity_block(fig, th, ent, art_path, cx, cy, label, is_pick, players=None):
    col = th['accent'] if is_pick else th['dim']
    if art_path and os.path.isfile(art_path):
        _paste(fig, art_path, cx, cy + 0.055, 0.20, 0.30)
    else:
        initials = ''.join(w[0] for w in str(ent.get('display') or '?').split()[:2])
        _initials_disc(fig, th, cx, cy + 0.055, 0.135, col, initials.upper(), 60)
    # key players flank their club's badge (operator spec 2026-08-07)
    players = [p for p in (players or []) if p.get('img') and os.path.isfile(p['img'])][:2]
    for dx, p in zip((-0.155, 0.155), players):
        _paste(fig, p['img'], cx + dx, cy + 0.045, 0.095, 0.175, avatar_if_opaque=True)
    fig.text(
        cx,
        cy - 0.115,
        _wrap(_fit(ent.get('display') or '', 34), 20),
        color=th['text'],
        fontsize=27,
        fontweight='bold',
        ha='center',
        va='top',
    )
    fig.text(cx, cy - 0.205, label, color=col, fontsize=20, ha='center', va='top')


def render_matchup(
    th_name: str,
    bet: dict,
    path: str,
    home_art: str = '',
    away_art: str = '',
    home_players: list = None,
    away_players: list = None,
) -> str:
    """Both sides, both faces/badges, the price, the model's fair price and the edge."""
    th = theme(th_name)
    plt, fig = _fig(th)
    when = bet.get('kickoff_local') or ''
    _header(
        fig,
        th,
        _fit_px(fig, f'{bet.get("home")}  vs  {bet.get("away")}', 0.66, 42, 'bold'),
        f'{bet.get("league") or ""}{("  ·  " + when) if when else ""}',
    )

    home_pick = bet.get('selection') == bet.get('home')
    away_pick = bet.get('selection') == bet.get('away')
    _entity_block(
        fig,
        th,
        bet.get('home_entity') or {'display': bet.get('home')},
        home_art,
        0.245,
        0.60,
        'HOME' + ('  ·  OUR PICK' if home_pick else ''),
        home_pick,
        players=home_players,
    )
    _entity_block(
        fig,
        th,
        bet.get('away_entity') or {'display': bet.get('away')},
        away_art,
        0.755,
        0.60,
        'AWAY' + ('  ·  OUR PICK' if away_pick else ''),
        away_pick,
        players=away_players,
    )
    fig.text(0.5, 0.645, 'VS', color=th['accent'], fontsize=54, fontweight='bold', ha='center', va='center')

    _panel(fig, th, 0.045, 0.085, 0.91, 0.24)
    tone = th['up'] if (bet.get('edge_pct') or 0) > 0 else th['accent']
    badge = 'VALUE BET' if bet.get('bet_type') == 'value' else 'CONFIDENCE PICK'
    if bet.get('starred'):
        badge = '★★★ ONE-UNIT BET  ·  ' + badge
        tone = '#FFD700'
    fig.text(0.075, 0.283, badge, color=tone, fontsize=22, fontweight='bold', va='center', ha='left')
    fig.text(
        0.075,
        0.215,
        f'PICK:  {_fit(bet.get("selection"), 40)}',
        color=th['text'],
        fontsize=36,
        fontweight='bold',
        va='center',
        ha='left',
    )
    fig.text(
        0.075,
        0.145,
        f'@ {bet.get("price")}  ({bet.get("book") or "best price"})',
        color=th['accent'],
        fontsize=28,
        fontweight='bold',
        va='center',
        ha='left',
    )

    # no stake cell: staking is fixed policy (1 unit on the two starred picks),
    # not a per-match percentage — operator 2026-08-08
    cells = [
        ('fair price', f'{bet.get("fair_price")}'),
        ('true chance', f'{float(bet.get("fair_prob") or 0) * 100:.0f}%'),
        ('edge', f'{bet.get("edge_pct"):+.1f}%'),
        ('books', f'{bet.get("n_books")}'),
    ]
    x0, step = 0.575, 0.100
    for i, (k, v) in enumerate(cells):
        x = x0 + i * step
        fig.text(x, 0.250, v, color=th['text'], fontsize=24, fontweight='bold', ha='center', va='center')
        fig.text(x, 0.198, k, color=th['dim'], fontsize=14, ha='center', va='top')
    fig.text(
        0.5,
        0.045,
        '18+  ·  gamble responsibly  ·  odds move, always check your bookmaker before placing',
        color=th['dim'],
        fontsize=15,
        ha='center',
        va='center',
        alpha=0.85,
    )
    return _save(fig, path)


def render_entity_focus(
    th_name: str, ent: dict, art_path: str, headline: str, caption: str, path: str, players: list = None
) -> str:
    """One team/fighter filling the frame — used while the narration talks about them.

    `players` (2026-08-07 operator enhancement): up to three {name, img} dicts of
    the team's notable players, drawn as a cutout strip under the badge. Cutouts
    are pasted aspect-preserved and unmodified (TheSportsDB terms), and everything
    sits above the 6%-of-edge line so the Ken Burns crop cannot clip it.
    """
    th = theme(th_name)
    plt, fig = _fig(th)
    _header(fig, th, _fit_px(fig, headline, 0.66, 42, 'bold'), '')
    players = [p for p in (players or []) if p.get('img') and os.path.isfile(p['img'])][:3]
    badge_cx, badge_cy = (0.27, 0.56) if players else (0.30, 0.46)
    if art_path and os.path.isfile(art_path):
        _paste(fig, art_path, badge_cx, badge_cy, 0.26 if players else 0.34, 0.40 if players else 0.52)
    else:
        initials = ''.join(w[0] for w in str(ent.get('display') or '?').split()[:2])
        _initials_disc(
            fig,
            th,
            badge_cx,
            badge_cy,
            0.17 if players else 0.23,
            th['accent'],
            initials.upper(),
            96 if players else 110,
        )
    if players:
        # SURROUND the badge (operator spec: "like an artwork"): flanks left and
        # right of the crest, third player centred beneath it. Everything stays
        # outside the 6% Ken Burns crop band.
        spots = {
            1: [(badge_cx, 0.235)],
            2: [(0.10, 0.44), (0.44, 0.44)],
            3: [(0.10, 0.44), (0.44, 0.44), (badge_cx, 0.235)],
        }[len(players)]
        for (px_, py_), p in zip(spots, players):
            _paste(fig, p['img'], px_, py_, 0.135, 0.235, avatar_if_opaque=True)
            fig.text(
                px_, py_ - 0.145, _fit(p.get('name') or '', 20), color=th['dim'], fontsize=15, ha='center', va='center'
            )
    fig.text(
        0.56,
        0.60,
        _wrap(_fit(ent.get('display') or '', 40), 22),
        color=th['text'],
        fontsize=48,
        fontweight='bold',
        ha='left',
        va='center',
    )
    # Only a TRUSTED lookup may decorate the card: a low-confidence or
    # conflicted match printed "_No League Basketball · Belgium" next to an
    # Eredivisie side. No metadata beats a stranger's metadata.
    trusted = ent.get('confidence') == 'high' and not ent.get('country_conflict') and not ent.get('variant_mismatch')
    meta = ' · '.join([x for x in (ent.get('team'), ent.get('league'), ent.get('country')) if x]) if trusted else ''
    if meta:
        fig.text(0.56, 0.505, _fit(meta, 46), color=th['dim'], fontsize=22, ha='left', va='center')
    if caption:
        fig.text(0.56, 0.40, _wrap(caption, 40), color=th['accent'], fontsize=26, ha='left', va='top')
    if (ent.get('source') or '') == 'TheSportsDB':
        # 0.085, not 0.045: this card is the one that gets the Ken Burns crop, and
        # the credit has to stay on screen — it is the attribution TheSportsDB's
        # terms ask for (description.txt carries it too).
        fig.text(0.94, 0.085, 'artwork: TheSportsDB', color=th['dim'], fontsize=15, ha='right', va='center', alpha=0.85)
    return _save(fig, path)


def render_parlay_sheet(th_name: str, headline: str, subhead: str, rows: list, path: str, footer: str = '') -> str:
    """The parlay sheet: one tall row per combination, legs on their own line.

    rows = [{'label', 'legs', 'stats', 'pays'}]. The generic board's three
    columns truncated 'The Double — Chapecoense + FC Zwolle' to an ellipsis at
    27pt; parlays carry more text per row than a fixture line, so they get a
    two-line row with measured budgets instead."""
    th = theme(th_name)
    plt, fig = _fig(th)
    _header(fig, th, headline, subhead)
    rows = rows[:5]
    n = max(1, len(rows))
    top, bottom = 0.815, 0.115
    band = min((top - bottom) / n, 0.17)
    rh = band * 0.86
    block_top = top - ((top - bottom) - band * n) / 2.0
    labfs = _uniform_size(fig, [r.get('label') for r in rows], 0.21, (26, 22, 19), 'bold')
    legfs = _uniform_size(fig, [r.get('legs') for r in rows], 0.50, (23, 20, 17, 15), 'bold')
    stafs = _uniform_size(fig, [r.get('stats') for r in rows], 0.62, (19, 17, 15))
    from matplotlib.patches import FancyBboxPatch, Rectangle

    for i, r in enumerate(rows):
        y = block_top - (i + 1) * band + (band - rh) / 2.0
        if th['rule'] == 'round':
            fig.patches.append(
                FancyBboxPatch(
                    (0.045, y),
                    0.91,
                    rh,
                    boxstyle='round,pad=0,rounding_size=0.02',
                    transform=fig.transFigure,
                    facecolor=th['panel'],
                    edgecolor=th['up'],
                    linewidth=2.5,
                    alpha=0.95,
                )
            )
        else:
            fig.patches.append(
                Rectangle(
                    (0.045, y),
                    0.91,
                    rh,
                    transform=fig.transFigure,
                    facecolor=th['panel'],
                    edgecolor=th['up'],
                    linewidth=2,
                )
            )
        y_hi = y + rh * 0.66
        y_lo = y + rh * 0.24
        lab_col = '#FFD700' if '★' in (r.get('label') or '') else th['accent']
        fig.text(
            0.065,
            y_hi,
            _fit_px(fig, r.get('label'), 0.21, labfs, 'bold'),
            color=lab_col,
            fontsize=labfs,
            fontweight='bold',
            va='center',
            ha='left',
        )
        fig.text(
            0.29,
            y_hi,
            _fit_px(fig, r.get('legs'), 0.50, legfs, 'bold'),
            color=th['text'],
            fontsize=legfs,
            fontweight='bold',
            va='center',
            ha='left',
        )
        fig.text(
            0.065,
            y_lo,
            _fit_px(fig, r.get('stats'), 0.62, stafs),
            color=th['dim'],
            fontsize=stafs,
            va='center',
            ha='left',
        )
        fig.text(
            0.935,
            y + rh / 2.0,
            _fit_px(fig, r.get('pays'), 0.15, 27, 'bold'),
            color=th['up'],
            fontsize=27,
            fontweight='bold',
            va='center',
            ha='right',
        )
    if footer:
        fig.text(0.5, 0.055, footer, color=th['dim'], fontsize=17, va='center', ha='center')
    return _save(fig, path)


def render_card(th_name: str, headline: str, lines: list, path: str, footer: str = '') -> str:
    """A plain title/outro card."""
    th = theme(th_name)
    plt, fig = _fig(th)
    fig.text(
        0.5,
        0.68,
        headline.upper() if th['title_case'] == 'upper' else headline,
        color=th['accent'],
        fontsize=64,
        fontweight='bold',
        ha='center',
        va='center',
    )
    fig.patches.append(_rule(fig, th, 0.30, 0.615, 0.40, 0.005))
    for i, ln in enumerate(lines[:6]):
        fig.text(0.5, 0.53 - i * 0.075, _fit(ln, 70), color=th['text'], fontsize=30, ha='center', va='center')
    if footer:
        fig.text(0.5, 0.075, footer, color=th['dim'], fontsize=17, ha='center', va='center')
    return _save(fig, path)
