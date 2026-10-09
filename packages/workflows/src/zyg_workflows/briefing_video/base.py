# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.briefing_video.base — top imports, themes, ffmpeg helpers, matplotlib scaffolding.

Moved verbatim out of briefing_video.py (lines 36-398); zero logic changes.
"""

# ruff: noqa: F401  # the original module-level import block lands here
# verbatim; several of its names are consumed by the sibling modules rather
# than by this one, and deleting them would also change how CPython compiles
# the moved calls (import-originated globals use a different LOAD_ATTR form).
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import textwrap
import time
import logging as _zyg_logging

from zyg_workflows import paths
from zyg_workflows import provenance_seal as _seal
from zyg_workflows.bin import exe

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.briefing_video')


# briefing_video.py's own directory: the package root.
_CREWS = str(paths.PKG_DIR)
_FONT_BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

W, H = 1920, 1080
FPS = 30

# ── themes ──────────────────────────────────────────────────────────────────
# Every channel gets a visually distinct board. Operator spec calls this out
# explicitly for TokiToki vs Arena ("use a different looking chart"), so the
# two betting themes differ in palette, corner geometry AND row styling, not just
# in accent colour.
THEMES = {
    'stocks': {
        'name': 'Stockmarket',
        'bg': '#0B0F14',
        'panel': '#111823',
        'grid': '#1E2933',
        'text': '#E6EDF3',
        'dim': '#8B98A5',
        'accent': '#E8B923',
        'up': '#16C784',
        'down': '#EA3943',
        'rule': 'square',
        'row_style': 'bar',
        'title_case': 'upper',
    },
    'crypto': {
        'name': 'Cryptodaily',
        'bg': '#08060F',
        'panel': '#120E22',
        'grid': '#241C3D',
        'text': '#EDE9FE',
        'dim': '#9C93C4',
        'accent': '#22D3EE',
        'up': '#34D399',
        'down': '#FB7185',
        'rule': 'square',
        'row_style': 'bar',
        'title_case': 'upper',
    },
    'tokitoki': {
        'name': 'TokiToki',
        'bg': '#141034',
        'panel': '#1E1750',
        'grid': '#332a70',
        'text': '#FFFFFF',
        'dim': '#B6ADE8',
        'accent': '#FF4FA3',
        'up': '#4ADE80',
        'down': '#FF6B6B',
        'rule': 'round',
        'row_style': 'pill',
        'title_case': 'title',
    },
    'arena': {
        'name': 'Arena',
        'bg': '#0C0908',
        'panel': '#1A1210',
        'grid': '#2E2018',
        'text': '#F2E8DC',
        'dim': '#A08B78',
        'accent': '#C0392B',
        'up': '#8FBF6A',
        'down': '#D9534F',
        'rule': 'sharp',
        'row_style': 'slab',
        'title_case': 'upper',
    },
}


def theme(name) -> dict:
    # a dict passes through: pipelines brand the corner tag per sub-channel
    # ("TokiToki Tennis") by handing in a copied theme with 'name' overridden
    if isinstance(name, dict):
        return name
    return THEMES.get(name) or THEMES['stocks']


# ── ffmpeg helpers ──────────────────────────────────────────────────────────


def _run(cmd, timeout=900):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _dur(path) -> float:
    try:
        r = _run(
            [
                'ffprobe',
                '-v',
                'error',
                '-show_entries',
                'format=duration',
                '-of',
                'default=noprint_wrappers=1:nokey=1',
                path,
            ],
            timeout=60,
        )
        return float((r.stdout or '0').strip())
    except Exception:
        return 0.0


_NVENC_PROBE: dict = {'ts': 0.0, 'ok': False}


def _nvenc_available() -> bool:
    """A REAL test encode, not a listing check. 2026-08-07: an apt driver update
    (userspace 580.173 vs loaded kernel module 580.159) left h264_nvenc listed by
    ffmpeg but unable to emit a single packet — the old check said yes, every
    panel then failed to encode and the episode died. Cached for 10 min."""
    if time.time() - _NVENC_PROBE['ts'] < 600:
        return _NVENC_PROBE['ok']
    ok = False
    try:
        r = _run(
            [
                exe('ffmpeg'),
                '-hide_banner',
                '-f',
                'lavfi',
                '-i',
                'color=black:size=256x144:rate=30:duration=0.2',
                '-c:v',
                'h264_nvenc',
                '-f',
                'null',
                '-',
            ],
            timeout=30,
        )
        ok = r.returncode == 0
    except Exception:
        ok = False
    _NVENC_PROBE.update(ts=time.time(), ok=ok)
    return ok


def _vcodec(use_nvenc: bool) -> list:
    if use_nvenc:
        return ['-c:v', 'h264_nvenc', '-preset', 'p5', '-rc', 'vbr', '-cq', '21', '-b:v', '0', '-pix_fmt', 'yuv420p']
    return ['-c:v', 'libx264', '-preset', 'medium', '-crf', '21', '-pix_fmt', 'yuv420p']


_AUDIO_ARGS = ['-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2']


# ── matplotlib scaffolding ──────────────────────────────────────────────────


def _plt():
    import matplotlib

    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    try:
        font_manager.fontManager.addfont(_FONT_BOLD)
    except Exception as _exc:
        _zyg_log.debug('bold font not registered with matplotlib: %s', _exc)
    plt.rcParams['font.family'] = 'DejaVu Sans'
    return plt


def _fig(th):
    plt = _plt()
    fig = plt.figure(figsize=(W / 100.0, H / 100.0), dpi=100)
    fig.patch.set_facecolor(th['bg'])
    return plt, fig


def _save(fig, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.savefig(path, facecolor=fig.get_facecolor(), dpi=100)
    try:
        fig.clf()
        import matplotlib.pyplot as plt

        plt.close(fig)
    except Exception as _exc:
        _zyg_log.debug('figure close skipped: %s', _exc)
    return path


def _panel(fig, th, x, y, w, h, alpha=1.0, edge=True):
    """A theme-shaped background card in figure coordinates."""
    from matplotlib.patches import FancyBboxPatch, Rectangle

    style = {'round': 'round,pad=0,rounding_size=0.018', 'sharp': 'square,pad=0'}.get(th['rule'], 'square,pad=0')
    if th['rule'] == 'round':
        p = FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=style,
            transform=fig.transFigure,
            facecolor=th['panel'],
            alpha=alpha,
            edgecolor=th['grid'] if edge else 'none',
            linewidth=2,
        )
    else:
        p = Rectangle(
            (x, y),
            w,
            h,
            transform=fig.transFigure,
            facecolor=th['panel'],
            alpha=alpha,
            edgecolor=th['grid'] if edge else 'none',
            linewidth=2,
        )
    fig.patches.append(p)
    return p


def _header(fig, th, title, subtitle=''):
    t = title.upper() if th['title_case'] == 'upper' else title
    t, fs = _fit_px_auto(fig, t, 0.66, (42, 36, 31, 27), 'bold')
    fig.text(0.045, 0.925, t, color=th['accent'], fontsize=fs, fontweight='bold', va='center', ha='left')
    if subtitle:
        fig.text(0.045, 0.877, subtitle, color=th['dim'], fontsize=20, va='center', ha='left')
    fig.patches.append(_rule(fig, th, 0.045, 0.858, 0.91, 0.004))
    fig.text(0.955, 0.925, th['name'], color=th['dim'], fontsize=22, fontweight='bold', va='center', ha='right')


def _rule(fig, th, x, y, w, h):
    from matplotlib.patches import Rectangle

    return Rectangle((x, y), w, h, transform=fig.transFigure, facecolor=th['accent'], edgecolor='none', alpha=0.85)


def _paste(fig, img_path, cx, cy, max_w, max_h, avatar_if_opaque=False):
    """Draw an image centred at (cx, cy) in figure coords, aspect PRESERVED.

    Aspect is never distorted and the image is never cropped: TheSportsDB's terms
    require trademarked badges to be used unmodified, and a squashed club crest is
    exactly the modification they mean.

    `avatar_if_opaque` (player PHOTOS only, never badges): a square studio
    headshot with a flat background pastes as a jarring white box on the dark
    theme — those are shown as a circular avatar instead.
    """
    try:
        from PIL import Image

        im = Image.open(img_path).convert('RGBA')
    except Exception:
        return False
    if avatar_if_opaque:
        try:
            alpha = im.getchannel('A')
            if alpha.getextrema()[0] == 255:  # fully opaque → avatar crop
                from PIL import ImageDraw

                side = min(im.size)
                left = (im.width - side) // 2
                im = im.crop((left, 0, left + side, side))
                mask = Image.new('L', im.size, 0)
                ImageDraw.Draw(mask).ellipse((0, 0, im.width, im.height), fill=255)
                im.putalpha(mask)
        except Exception as _exc:
            _zyg_log.debug('avatar crop skipped, alpha channel unusable: %s', _exc)
    iw, ih = im.size
    if not iw or not ih:
        return False
    scale = min((max_w * W) / iw, (max_h * H) / ih)
    tw, th_ = max(1, int(iw * scale)), max(1, int(ih * scale))
    ax = fig.add_axes([cx - (tw / W) / 2.0, cy - (th_ / H) / 2.0, tw / W, th_ / H])
    ax.imshow(im)
    ax.axis('off')
    ax.set_facecolor('none')
    return True


def _wrap(s, n):
    return '\n'.join(textwrap.wrap(str(s or ''), n)) or ''


def _fit(s, n):
    s = str(s or '')
    return s if len(s) <= n else s[: n - 1].rstrip() + '…'


def _fit_px(fig, s, max_frac, fontsize, weight='normal'):
    """Truncate `s` so it actually RENDERS inside `max_frac` of the frame width.

    Character counts are not a width budget. "Borussia Mönchengladbach vs Bay…"
    is 32 characters and so is "Columbus Crew vs Pachuca ......." — at 27pt bold
    the first is 700px and the second 520px, and the first one printed straight
    through the column to its right on the first real board. This measures the
    string with the live renderer and binary-searches the cut, so a column can
    never overrun its neighbour whatever the language or the weight.
    """
    s = str(s or '')
    if not s:
        return ''
    budget = max_frac * W
    try:
        rend = fig.canvas.get_renderer()
    except Exception:  # no renderer yet — fall back to an estimate
        return _fit(s, max(4, int(budget / (fontsize * 0.62))))

    def _w(t):
        obj = fig.text(0, 0, t, fontsize=fontsize, fontweight=weight)
        try:
            return obj.get_window_extent(renderer=rend).width
        finally:
            obj.remove()

    if _w(s) <= budget:
        return s
    lo, hi = 1, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _w(s[:mid] + '…') <= budget:
            lo = mid
        else:
            hi = mid - 1
    return s[:lo].rstrip() + '…'


def _fit_px_auto(fig, s, max_frac, sizes, weight='normal'):
    """(text, fontsize): step the font DOWN until the whole string fits, only
    ellipsising at the smallest size. Operator 2026-08-08: full matchup names
    beat big truncated ones — "Aryna Sabalenka vs Ekaterina Alex…" reads worse
    than the same line a couple of points smaller."""
    s = str(s or '')
    for fs in sizes:
        fitted = _fit_px(fig, s, max_frac, fs, weight)
        if fitted == s:
            return fitted, fs
    return _fit_px(fig, s, max_frac, sizes[-1], weight), sizes[-1]


def _uniform_size(fig, texts, max_frac, sizes, weight='normal'):
    """ONE font size for a whole column: the largest at which EVERY row fits.

    Per-row auto-shrink made row 5 huge and row 7 small on the same board
    (operator screenshot 2026-08-08) — a column must read as one column."""
    for fs in sizes:
        if all(_fit_px(fig, str(t or ''), max_frac, fs, weight) == str(t or '') for t in texts):
            return fs
    return sizes[-1]
