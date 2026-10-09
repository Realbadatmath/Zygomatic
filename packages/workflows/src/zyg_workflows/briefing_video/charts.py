# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.briefing_video.charts — chart 1 (the opening board) and chart 2 (the price chart).

Moved verbatim out of briefing_video.py (lines 401-682); zero logic changes.
"""

from __future__ import annotations

from zyg_workflows.briefing_video.base import _fig, _fit_px, _header, _save, _uniform_size, theme


# ── chart 1: the opening board (every episode starts here) ──────────────────


def render_board(th_name: str, headline: str, subhead: str, rows: list, path: str, footer: str = '') -> str:
    """The locally-made list chart: every item researched this episode, one row each.

    rows = [{'left','mid','right','tone'}] where tone ∈ {'up','down','neutral'}.
    """
    th = theme(th_name)
    plt, fig = _fig(th)
    _header(fig, th, headline, subhead)

    rows = rows[:12]
    n = max(1, len(rows))
    top, bottom = 0.815, 0.115
    # Keep the row height constant and centre the block instead of stretching a
    # 3-row board across the whole frame — a short list should read as a short
    # list, not as three bars floating in space.
    band = min((top - bottom) / n, 0.098)
    rh = band * 0.76
    block_top = top - ((top - bottom) - band * n) / 2.0
    # one size per COLUMN, sized to the longest row — mixed row sizes read wrong
    lfs = _uniform_size(fig, [r.get('left') for r in rows], 0.345, (27, 23, 20, 17), 'bold')
    mfs = _uniform_size(fig, [r.get('mid') for r in rows], 0.250, (19, 16, 14))
    rfs = _uniform_size(
        fig,
        [('★★★ ' + (r.get('right') or '')) if r.get('stars') else (r.get('right') or '') for r in rows],
        0.250,
        (23, 20, 17, 14),
        'bold',
    )
    for i, r in enumerate(rows):
        y = block_top - (i + 1) * band + (band - rh) / 2.0
        tone = r.get('tone') or 'neutral'
        col = th.get(tone, th['dim']) if tone in ('up', 'down') else th['dim']
        if th['row_style'] == 'pill':
            from matplotlib.patches import FancyBboxPatch

            fig.patches.append(
                FancyBboxPatch(
                    (0.045, y),
                    0.91,
                    rh,
                    boxstyle='round,pad=0,rounding_size=0.02',
                    transform=fig.transFigure,
                    facecolor=th['panel'],
                    edgecolor=col,
                    linewidth=2.5,
                    alpha=0.95,
                )
            )
        elif th['row_style'] == 'slab':
            from matplotlib.patches import Rectangle, Polygon

            fig.patches.append(
                Rectangle((0.045, y), 0.91, rh, transform=fig.transFigure, facecolor=th['panel'], edgecolor='none')
            )
            fig.patches.append(
                Polygon(
                    [[0.045, y], [0.045 + 0.012, y + rh / 2.0], [0.045, y + rh]],
                    transform=fig.transFigure,
                    facecolor=col,
                    edgecolor='none',
                )
            )
        else:
            from matplotlib.patches import Rectangle

            fig.patches.append(
                Rectangle((0.045, y), 0.91, rh, transform=fig.transFigure, facecolor=th['panel'], edgecolor='none')
            )
            fig.patches.append(
                Rectangle((0.045, y), 0.006, rh, transform=fig.transFigure, facecolor=col, edgecolor='none')
            )
        cy = y + rh / 2.0
        # Three fixed columns, each truncated to its MEASURED pixel budget. The
        # right column is right-aligned and bold, so an over-long neighbour does
        # not push it aside — it slides underneath it, which is what happened on
        # the first real board before _fit_px existed.
        fig.text(0.055, cy, f'{i + 1}', color=th['dim'], fontsize=20, fontweight='bold', va='center', ha='left')
        fig.text(
            0.088,
            cy,
            _fit_px(fig, r.get('left'), 0.345, lfs, 'bold'),
            color=th['text'],
            fontsize=lfs,
            fontweight='bold',
            va='center',
            ha='left',
        )
        fig.text(
            0.450, cy, _fit_px(fig, r.get('mid'), 0.250, mfs), color=th['dim'], fontsize=mfs, va='center', ha='left'
        )
        rt = r.get('right') or ''
        if r.get('stars'):
            # the day's one-unit picks wear three golden stars
            rt = f'★★★ {rt}'
            col = '#FFD700'
        fig.text(
            0.945,
            cy,
            _fit_px(fig, rt, 0.250, rfs, 'bold'),
            color=col,
            fontsize=rfs,
            fontweight='bold',
            va='center',
            ha='right',
        )

    if footer:
        fig.text(0.5, 0.055, footer, color=th['dim'], fontsize=17, va='center', ha='center')
    return _save(fig, path)


# ── chart 2: a price chart (stocks + crypto) ────────────────────────────────


def render_price_chart(th_name: str, pick: dict, path: str) -> str:
    """OHLC candles + 20/50/200-day means, with an RSI strip underneath.

    The verdict badge, the horizon and every printed number come straight from
    `pick`; nothing on this chart is recomputed here, so what the presenter says
    and what the viewer sees cannot drift apart.
    """
    th = theme(th_name)
    plt, fig = _fig(th)
    bars = pick.get('bars_tail') or []
    ind = pick.get('indicators') or {}
    up_c, dn_c = th['up'], th['down']

    sym = pick.get('symbol') or ''
    name = pick.get('name') or sym
    dirn = pick.get('direction')
    tone = up_c if dirn == 'up' else dn_c
    horizon = 'SHORT-TERM TRADE' if pick.get('horizon') == 'short' else 'LONG-TERM INVESTMENT'
    verdict = 'EXPECTED TO RISE' if dirn == 'up' else 'EXPECTED TO FALL'

    _header(
        fig,
        th,
        _fit_px(fig, f'{sym} — {name}', 0.66, 42, 'bold'),
        f'{pick.get("index") or ""}{"  ·  " if pick.get("sector") else ""}{pick.get("sector") or ""}',
    )

    # verdict badge
    from matplotlib.patches import Rectangle

    fig.patches.append(
        Rectangle((0.045, 0.775), 0.30, 0.055, transform=fig.transFigure, facecolor=tone, edgecolor='none', alpha=0.16)
    )
    fig.patches.append(
        Rectangle((0.045, 0.775), 0.005, 0.055, transform=fig.transFigure, facecolor=tone, edgecolor='none')
    )
    fig.text(
        0.058,
        0.8025,
        f'{"▲" if dirn == "up" else "▼"}  {verdict}',
        color=tone,
        fontsize=24,
        fontweight='bold',
        va='center',
        ha='left',
    )
    fig.text(0.36, 0.8025, horizon, color=th['accent'], fontsize=21, fontweight='bold', va='center', ha='left')
    conv = float(pick.get('conviction') or 0)
    fig.text(0.955, 0.8025, f'conviction {conv * 100:.0f}%', color=th['dim'], fontsize=20, va='center', ha='right')

    if not bars:
        fig.text(0.5, 0.45, 'price history unavailable', color=th['dim'], fontsize=28, ha='center', va='center')
        return _save(fig, path)

    ax = fig.add_axes([0.06, 0.30, 0.885, 0.44])
    axr = fig.add_axes([0.06, 0.13, 0.885, 0.13], sharex=ax)
    for a in (ax, axr):
        a.set_facecolor(th['panel'])
        a.grid(True, color=th['grid'], linewidth=0.8, alpha=0.7)
        a.tick_params(colors=th['dim'], labelsize=13)
        for sp in a.spines.values():
            sp.set_color(th['grid'])

    xs = list(range(len(bars)))
    closes = [b['c'] for b in bars]
    wick_w, body_w = 0.14, 0.62
    for i, b in enumerate(bars):
        c = up_c if b['c'] >= b['o'] else dn_c
        ax.add_patch(
            plt.Rectangle(
                (i - wick_w / 2, min(b['l'], b['h'])), wick_w, abs(b['h'] - b['l']) or 1e-9, color=c, alpha=0.75
            )
        )
        ax.add_patch(
            plt.Rectangle(
                (i - body_w / 2, min(b['o'], b['c'])),
                body_w,
                abs(b['c'] - b['o']) or (max(closes) * 1e-4),
                color=c,
                alpha=0.95,
            )
        )

    ov = pick.get('overlays') or {}

    def _ma(key, colr, lbl):
        ser = ov.get(key) or []
        pts = [(i, v) for i, v in enumerate(ser[: len(xs)]) if v is not None]
        if len(pts) < 2:
            return
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=colr, linewidth=2.0, label=lbl, alpha=0.9)

    _ma('sma20', th['accent'], '20-day')
    _ma('sma50', th['text'], '50-day')
    _ma('sma200', th['dim'], '200-day')
    lg = ax.legend(
        loc='upper left', fontsize=13, facecolor=th['panel'], edgecolor=th['grid'], labelcolor=th['dim'], framealpha=0.9
    )
    for t in lg.get_texts():
        t.set_color(th['dim'])

    last = ind.get('last')
    if last:
        ax.axhline(last, color=tone, linewidth=1.2, linestyle='--', alpha=0.8)
        ax.annotate(
            f'{last:,.2f}',
            xy=(len(bars) - 1, last),
            xytext=(6, 0),
            textcoords='offset points',
            color=tone,
            fontsize=17,
            fontweight='bold',
            va='center',
        )
    ax.set_xlim(-1, len(bars) + 6)
    ax.set_ylabel('price', color=th['dim'], fontsize=14)
    ax.set_xticks([])

    axr.axhspan(70, 100, color=dn_c, alpha=0.10)
    axr.axhspan(0, 30, color=up_c, alpha=0.10)
    for lvl, colr in ((70, dn_c), (30, up_c), (50, th['grid'])):
        axr.axhline(lvl, color=colr, linewidth=1.0, alpha=0.6)
    rsi_ser = [(i, v) for i, v in enumerate((ov.get('rsi14') or [])[: len(xs)]) if v is not None]
    if len(rsi_ser) >= 2:
        axr.plot([p[0] for p in rsi_ser], [p[1] for p in rsi_ser], color=th['accent'], linewidth=2.2)
    rsi = ind.get('rsi14')
    if rsi is not None:
        axr.annotate(
            f'{rsi:.0f}',
            xy=(len(bars) - 1, rsi),
            xytext=(6, 0),
            textcoords='offset points',
            color=th['accent'],
            fontsize=16,
            fontweight='bold',
            va='center',
        )
    axr.set_ylim(0, 100)
    axr.set_yticks([30, 50, 70])
    axr.set_xticks([])
    axr.set_ylabel('RSI', color=th['dim'], fontsize=13)

    facts = []
    for label, key, fmt in (
        ('1M', 'ret_20d', '{:+.1f}%'),
        ('6M', 'ret_120d', '{:+.1f}%'),
        ('ATR', 'atr_pct', '{:.1f}%'),
        ('52w pos', 'pos_52w', '{:.0f}%'),
    ):
        v = ind.get(key)
        if v is not None:
            facts.append(f'{label} {fmt.format(v)}')
    if facts:
        fig.text(0.5, 0.075, '     ·     '.join(facts), color=th['dim'], fontsize=19, ha='center', va='center')
    fig.text(
        0.5,
        0.035,
        f'data as of {pick.get("as_of", "")} · source {pick.get("provider", "market data")} · not financial advice',
        color=th['dim'],
        fontsize=14,
        ha='center',
        va='center',
        alpha=0.8,
    )
    return _save(fig, path)
