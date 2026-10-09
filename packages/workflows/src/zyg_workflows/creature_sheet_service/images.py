# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Image helpers (pure PIL, no GPU): references, letterbox, strips, sheet."""

from __future__ import annotations

import os
from typing import Any

from .base import CELL_SIZE, caption_mode

import logging as _zyg_logging

# Channel kept from the pre-split module. Re-bound by ASSIGNMENT (not ``from .base
# import``) so the moved call sites keep their original method-call bytecode; it is
# the same logger object either way.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.creature_sheet_service')

# ── image helpers (pure PIL, no GPU) ─────────────────────────────────────────


def _prepare_reference(src: str, dst: str, size: int = CELL_SIZE) -> str:
    """Copy a reference at its NATIVE aspect (max side `size`), bars stripped.

    Measured 2026-08-25 on the pufferball smoke: padding the 920×498 reference
    into a square with dark bars made Qwen-Image-Edit reproduce the bars in the
    derived full-body anchor — and every cell edited from it would have carried
    them into the training set. The edit graph accepts any input aspect; the
    OUTPUT size is what node 30 sets, so the source is never padded."""
    from PIL import Image

    im = Image.open(src).convert('RGB')
    im = _crop_letterbox_image(im)[0]
    im.thumbnail((size, size), Image.LANCZOS)
    im.save(dst, format='PNG')
    return dst


def _crop_letterbox_image(im, *, max_frac: float = 0.45, tol: float = 6.0):
    """(image, cropped_px) — strip uniform bars (any colour) from the four edges.

    A bar row/column is one whose pixel std is below `tol` AND whose mean is
    within `tol` of the outermost row/column; bars stop at the first row that
    differs. Never removes more than `max_frac` of a dimension per side."""
    import numpy as np

    arr = np.asarray(im.convert('RGB'), dtype=np.float32)
    h, w = arr.shape[:2]

    def _run(lines, limit):
        ref = lines[0].reshape(-1, 3).mean(axis=0)
        n = 0
        for ln in lines[:limit]:
            px = ln.reshape(-1, 3)
            if px.std(axis=0).max() > tol or np.abs(px.mean(axis=0) - ref).max() > tol:
                break
            n += 1
        return n if n < limit else limit

    top = _run(arr, int(h * max_frac))
    bot = _run(arr[::-1], int(h * max_frac))
    left = _run(arr.transpose(1, 0, 2), int(w * max_frac))
    right = _run(arr.transpose(1, 0, 2)[::-1], int(w * max_frac))
    # a uniform image (blank frame) is not a letterbox — leave it to structural_check
    if top + bot >= h * 0.9 or left + right >= w * 0.9:
        return im, 0
    if max(top, bot, left, right) < 8:
        return im, 0
    return im.crop((left, top, w - right, h - bot)), top + bot + left + right


def strip_letterbox(path: str) -> int:
    """Crop uniform bars off an image IN PLACE. Returns pixels removed (0 = untouched)."""
    try:
        from PIL import Image

        im = Image.open(path).convert('RGB')
        out, n = _crop_letterbox_image(im)
        if n:
            out.save(path, format='PNG')
        return n
    except Exception:
        return 0


def structural_check(
    path: str, anchor_path: str | None = None, *, expect_change: bool = True, siblings: list[str] | None = None
) -> dict:
    """Blank/black frame, unchanged-vs-anchor and duplicate-of-sibling tests.

    Returns {'ok', 'reasons': [...], 'std', 'phash_anchor', 'phash_dup'}."""
    reasons: list[str] = []
    rec: dict[str, Any] = {'ok': True, 'reasons': reasons, 'std': None, 'phash_anchor': None, 'phash_dup': None}
    try:
        from PIL import Image, ImageStat

        im = Image.open(path).convert('L')
        std = float(ImageStat.Stat(im).stddev[0])
        rec['std'] = round(std, 2)
        if std < 4.0:
            reasons.append('blank_frame')
    except Exception as exc:
        reasons.append(f'unreadable:{exc}')
        rec['ok'] = False
        return rec
    try:
        import imagehash
        from PIL import Image

        h = imagehash.phash(Image.open(path).convert('RGB'))
        if anchor_path and os.path.isfile(anchor_path):
            d = int(h - imagehash.phash(Image.open(anchor_path).convert('RGB')))
            rec['phash_anchor'] = d
            if expect_change and d <= 3:
                reasons.append('unchanged_from_anchor')
        best = None
        for s in siblings or []:
            if not s or not os.path.isfile(s) or os.path.abspath(s) == os.path.abspath(path):
                continue
            ds = int(h - imagehash.phash(Image.open(s).convert('RGB')))
            best = ds if best is None else min(best, ds)
        rec['phash_dup'] = best
        if best is not None and best <= 2:
            reasons.append('duplicate_of_sibling')
    except Exception as _exc:
        _zyg_log.warning('phash check failed, this cell was not screened for duplicates: %s', _exc)
    rec['ok'] = not reasons
    return rec


def make_strip(
    ref_path: str,
    cand_path: str,
    out_path: str,
    *,
    ref_label: str = 'REFERENCE',
    cand_label: str = 'CANDIDATE',
    panel: int = 768,
) -> str:
    """Side-by-side judge strip: LEFT = reference, RIGHT = candidate, labelled in-pixel."""
    from PIL import Image, ImageDraw, ImageFont

    gutter, bar = 24, 56
    fills = (18, 18, 22)
    W = 2 * panel + 3 * gutter
    H = panel + bar + 2 * gutter
    canvas = Image.new('RGB', (W, H), fills)
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 34)
    except Exception:
        font = ImageFont.load_default()
    for i, (p, lab) in enumerate(((ref_path, ref_label), (cand_path, cand_label))):
        x0 = gutter + i * (panel + gutter)
        im = Image.open(p).convert('RGB')
        im.thumbnail((panel, panel), Image.LANCZOS)
        canvas.paste(im, (x0 + (panel - im.width) // 2, gutter + bar + (panel - im.height) // 2))
        draw.rectangle([x0, gutter, x0 + panel, gutter + bar - 6], fill=(40, 40, 48))
        draw.text((x0 + 14, gutter + 8), lab, fill=(240, 240, 240), font=font)
    canvas.save(out_path, format='PNG')
    return out_path


def stitch_sheet(
    cells: list[dict], out_path: str, *, cols: int = 4, cell_px: int = 512, title: str = '', judge_note: str = ''
) -> str:
    """Labelled contact sheet: angle label, verdict, DINO score; EXCLUDED = red frame."""
    from PIL import Image, ImageDraw, ImageFont

    gutter, bar = 12, 54
    rows = max(1, (len(cells) + cols - 1) // cols)
    head = 64 if (title or judge_note) else 0
    W = cols * cell_px + (cols + 1) * gutter
    H = head + rows * (cell_px + bar) + (rows + 1) * gutter
    canvas = Image.new('RGB', (W, H), (18, 18, 22))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 20)
        small = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 17)
        big = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 26)
    except Exception:
        font = small = big = ImageFont.load_default()
    if head:
        draw.text((gutter + 4, 16), title[:120], fill=(235, 235, 235), font=big)
        if judge_note:
            tw = draw.textlength(judge_note, font=font)
            draw.text((W - gutter - tw - 4, 20), judge_note, fill=(255, 190, 90), font=font)
    for i, c in enumerate(cells):
        r, col = divmod(i, cols)
        x0 = gutter + col * (cell_px + gutter)
        y0 = head + gutter + r * (cell_px + bar + gutter)
        p = c.get('path')
        if p and os.path.isfile(p):
            im = Image.open(p).convert('RGB')
            im.thumbnail((cell_px, cell_px), Image.LANCZOS)
            canvas.paste(im, (x0 + (cell_px - im.width) // 2, y0 + (cell_px - im.height) // 2))
        else:
            draw.rectangle([x0, y0, x0 + cell_px, y0 + cell_px], fill=(40, 24, 24))
            draw.text((x0 + 16, y0 + 16), 'MISSING', fill=(255, 120, 120), font=font)
        ok = bool(c.get('ok'))
        soft = c.get('soft') or []
        color = (230, 70, 70) if not ok else ((225, 170, 60) if soft else (90, 200, 120))
        draw.rectangle([x0 - 2, y0 - 2, x0 + cell_px + 1, y0 + cell_px + 1], outline=color, width=4)
        draw.rectangle([x0, y0 + cell_px, x0 + cell_px, y0 + cell_px + bar], fill=(30, 30, 36))
        draw.text((x0 + 8, y0 + cell_px + 6), f'{i:02d}  {c.get("label", "")[:40]}', fill=(235, 235, 235), font=font)
        dino = c.get('dino')
        verdict = 'EXCLUDED' if not ok else ('PASS*' if soft else 'PASS')
        why = (
            ','.join(c.get('reasons') or [])[:44]
            if not ok
            else {
                'neutral': 'kept: angle-neutral caption',
                'partial': 'kept: partial-view caption',
                'neutral_partial': 'kept: neutral+partial caption',
            }.get(c.get('caption_mode') or caption_mode(c), '')
        )
        line2 = f'{verdict}' + (f'  dino {dino:.2f}' if isinstance(dino, (int, float)) else '  dino n/a')
        extra = [s[4:] if s.startswith('vlm:') else s for s in soft if s not in ('vlm:angle_match', 'vlm:whole_body')]
        if ok and extra:
            why = (f'{why}  ' if why else '') + 'flag: ' + ','.join(extra)[:28]
        if why:
            line2 += f'  {why}'
        draw.text((x0 + 8, y0 + cell_px + 30), line2, fill=color, font=small)
    canvas.save(out_path, format='PNG')
    return out_path
