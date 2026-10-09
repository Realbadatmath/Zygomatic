# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The piano roll SVG — the composed tune, drawn.

Moved verbatim out of the old single-file kids_music_service.py (lines 2558-2639).
"""

from __future__ import annotations

from zyg_workflows import kids_music_theory as T


# ── Piano roll ───────────────────────────────────────────────────────────────


def write_roll_svg(plan, path):
    """A piano-roll of the melody, so the tab can SHOW the tune next to the
    player.  Hand-written SVG: no plotting dependency and scales to any width.

    Every colour is EXPLICIT. The first version drew its bar lines, tonic guides
    and chord symbols in `currentColor`, which inherits from the host document —
    and the tab loads this through an <img>, whose SVG is an isolated document
    where currentColor resolves to black. On a dark card that rendered the notes
    and nothing else: no bars, no key reference, no chords. A mid grey is used
    instead so the file is self-contained and reads on a light or dark ground.
    """
    mel = plan['melody']
    if not mel:
        return None
    bar_beats = plan['bar_beats']
    total = plan['total_beats']
    lo = min(n['p'] for n in mel) - 2
    hi = max(n['p'] for n in mel) + 2
    W, H = 1200, 260
    pad_l, pad_b = 42, 22
    pw, ph = W - pad_l - 8, H - pad_b - 10
    x = lambda b: pad_l + pw * (b / max(1e-6, total))  # noqa: E731
    y = lambda p: 10 + ph * (1 - (p - lo) / max(1, hi - lo))  # noqa: E731
    nh = max(4.0, ph / max(1, hi - lo))

    hue = ['#4f9bff', '#f0883e', '#57c98a', '#c678dd', '#e5c07b']
    ink = '#8892a4'  # reads on both grounds; never `currentColor` here
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="100%" preserveAspectRatio="none" role="img" '
        f'aria-label="piano roll of the composed melody">'
    ]
    out.append(f'<rect width="{W}" height="{H}" fill="none"/>')
    # Bar lines, heavier at the start of each 4-bar section.
    n_bars = int(round(total / bar_beats))
    for b in range(n_bars + 1):
        bx = x(b * bar_beats)
        strong = (b - plan['intro_bars']) % 4 == 0
        out.append(
            f'<line x1="{bx:.1f}" y1="8" x2="{bx:.1f}" y2="{H - pad_b}" '
            f'stroke="{ink}" stroke-opacity="{0.55 if strong else 0.22}" '
            f'stroke-width="{1.4 if strong else 1}"/>'
        )
    # Tonic guide lines — the ear's reference, and the eye's.
    tonic_pc = plan['key']['tonic_pc']
    for p in range(lo, hi + 1):
        if p % 12 == tonic_pc:
            yy = y(p) + nh / 2
            out.append(
                f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{W - 8}" y2="{yy:.1f}" '
                f'stroke="{ink}" stroke-opacity="0.40" '
                f'stroke-dasharray="3 4"/>'
            )
            out.append(
                f'<text x="4" y="{yy + 4:.1f}" font-size="11" '
                f'font-family="ui-monospace,monospace" fill="{ink}">'
                f'{T._note_name(p)}</text>'
            )
    for n in mel:
        c = hue[n['section'] % len(hue)]
        w = max(3.0, x(n['t'] + n['d']) - x(n['t']) - 1.5)
        out.append(
            f'<rect x="{x(n["t"]):.1f}" y="{y(n["p"]):.1f}" width="{w:.1f}" '
            f'height="{nh - 1.5:.1f}" rx="2" fill="{c}" '
            f'fill-opacity="{0.95 if n["strong"] else 0.68}"/>'
        )
    # Chord symbols along the bottom.
    for c in plan['chords']:
        out.append(
            f'<text x="{x(c["t"]) + 3:.1f}" y="{H - 6}" font-size="11" '
            f'font-family="ui-monospace,monospace" fill="{ink}">'
            f'{c["symbol"]}</text>'
        )
    out.append('</svg>')
    with open(path, 'w') as fh:
        fh.write('\n'.join(out))
    return path
