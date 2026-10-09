# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Mock sheets, cell stitching, re-stitching and composite previews.

Moved verbatim out of the old single-file contact_sheet_pipeline.py (lines 1464-1692).
"""

from __future__ import annotations

import os
from typing import Callable

from zyg_workflows.contact_sheet_pipeline.constants import (
    DEFAULT_CELL_H,
    DEFAULT_CELL_W,
    DEFAULT_COLS,
    DEFAULT_GUTTER,
    DEFAULT_ROWS,
    _zyg_log,
)
from zyg_workflows.contact_sheet_pipeline.layout import (
    _ams_iso,
    _angle_label,
    contact_sheet_dir,
    load_manifest,
    master_sheet_path,
    trigger_token_for,
)
from zyg_workflows.contact_sheet_pipeline.angle_edit import (
    _cell_size_for_angle,
    _is_full_body_angle,
)


def _generate_sheet_mock(
    char_id: str,
    params: dict,
    out_path: str,
    rows: int,
    cols: int,
    cell_w: int,
    cell_h: int,
    gutter: int,
    log_fn: Callable[[str], None] | None,
) -> str:
    from PIL import Image, ImageDraw, ImageFont

    sheet_w = cols * cell_w + (cols + 1) * gutter
    sheet_h = rows * cell_h + (rows + 1) * gutter
    img = Image.new('RGB', (sheet_w, sheet_h), (32, 32, 38))
    draw = ImageDraw.Draw(img)
    name = (params or {}).get('name') or char_id[:8]
    trigger = trigger_token_for(char_id)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    idx = 0
    for r in range(rows):
        for c in range(cols):
            x0 = gutter + c * (cell_w + gutter)
            y0 = gutter + r * (cell_h + gutter)
            # Slight hue variation per cell so tiles are distinguishable in QA.
            hue = (40 + (idx * 17) % 80, 90 + (idx * 11) % 60, 120 + (idx * 7) % 50)
            draw.rectangle([x0, y0, x0 + cell_w, y0 + cell_h], fill=hue, outline=(200, 200, 210))
            label = _angle_label(idx)[:48]
            draw.text((x0 + 8, y0 + 8), f'{trigger}', fill=(255, 255, 255), font=font)
            draw.text((x0 + 8, y0 + 28), label[:40], fill=(230, 230, 240), font=font)
            draw.text((x0 + 8, y0 + cell_h - 24), name[:24], fill=(255, 255, 255), font=font)
            idx += 1

    img.save(out_path, format='PNG')
    if log_fn:
        log_fn(f'Mock contact sheet saved ({rows}×{cols}, {sheet_w}×{sheet_h}) → {out_path}')
    return out_path


def _stitch_cell_images(
    cell_paths: list[str],
    out_path: str,
    rows: int,
    cols: int,
    cell_w: int,
    cell_h: int,
    gutter: int,
    log_fn: Callable[[str], None] | None,
) -> str:
    from PIL import Image

    sheet_w = cols * cell_w + (cols + 1) * gutter
    sheet_h = rows * cell_h + (rows + 1) * gutter
    sheet = Image.new('RGB', (sheet_w, sheet_h), (24, 24, 28))
    for idx, cpath in enumerate(cell_paths):
        if not cpath or not os.path.isfile(cpath):
            continue
        r, c = divmod(idx, cols)
        x0 = gutter + c * (cell_w + gutter)
        y0 = gutter + r * (cell_h + gutter)
        cell = Image.open(cpath).convert('RGB')
        if cell.size != (cell_w, cell_h):
            # Letterbox-fit: mixed-aspect cells (full-body 2:3) must not be
            # stretched in the approval preview.
            scale = min(cell_w / cell.size[0], cell_h / cell.size[1])
            fitted = cell.resize(
                (max(1, int(cell.size[0] * scale)), max(1, int(cell.size[1] * scale))),
                Image.Resampling.LANCZOS,
            )
            cell = Image.new('RGB', (cell_w, cell_h), (24, 24, 28))
            cell.paste(fitted, ((cell_w - fitted.size[0]) // 2, (cell_h - fitted.size[1]) // 2))
        sheet.paste(cell, (x0, y0))
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    sheet.save(out_path, format='PNG')
    if log_fn:
        log_fn(f'Stitched contact sheet ({rows}×{cols}, {sheet_w}×{sheet_h}) → {out_path}')
    return out_path


def restitch_master_sheets(char_id: str, log_fn: Callable[[str], None] | None = None) -> bool:
    """Rebuild the master preview pages + composite from the CURRENT tiles.

    The sheet pages are stitched right after generation, BEFORE identity QC
    installs repairs into tiles/ — so the library preview showed pre-repair
    cells (2026-07-16, Kira Patel: 8 repaired tiles invisible in the library).
    Called after QC whenever repairs happened; safe to call any time.
    """
    import glob as _glob
    import json as _json

    cs_dir = contact_sheet_dir(char_id)
    m = load_manifest(char_id) or {}
    rows = int(m.get('rows') or DEFAULT_ROWS)
    cols = int(m.get('cols') or DEFAULT_COLS)
    cw = int(m.get('cell_width') or DEFAULT_CELL_W)
    ch = int(m.get('cell_height') or DEFAULT_CELL_H)
    gutter = int(m.get('gutter_px') or DEFAULT_GUTTER)
    # Per-cell tile_NN(N).png sorts by numeric index (lexical breaks at the
    # 02d→03d boundary); grid-sliced tile_<part>_<r>_<c>.png keeps lexical
    # part-major order.
    import re as _re_rs

    def _tile_sort_key(p: str):
        m = _re_rs.fullmatch(r'tile_(\d+)\.png', os.path.basename(p))
        return (0, int(m.group(1)), '') if m else (1, 0, os.path.basename(p))

    tiles = sorted(
        _glob.glob(os.path.join(cs_dir, 'tiles', 'tile_*.png')),
        key=_tile_sort_key,
    )
    if not tiles:
        if log_fn:
            log_fn('Sheet re-stitch skipped — no tiles found')
        return False
    per_sheet = max(1, rows * cols)
    sheet_paths: list[str] = []
    for si in range((len(tiles) + per_sheet - 1) // per_sheet):
        group = tiles[si * per_sheet : (si + 1) * per_sheet]
        out = os.path.join(cs_dir, f'contact_sheet_master_{chr(ord("a") + si)}.png')
        _stitch_cell_images(group, out, rows, cols, cw, ch, gutter, log_fn)
        sheet_paths.append(out)
    _composite_sheet_stack(sheet_paths, master_sheet_path(char_id), gap=24, log_fn=log_fn)
    try:
        m['updated_at'] = _ams_iso()
        m['sheet_restitched_after_qc'] = m['updated_at']
        _mpath = os.path.join(cs_dir, 'manifest.json')
        _tmp = _mpath + '.tmp'
        with open(_tmp, 'w', encoding='utf-8') as fh:
            _json.dump(m, fh, indent=2)
        os.replace(_tmp, _mpath)
    except Exception as _exc:
        _zyg_log.warning('manifest write after the sheet re-stitch failed, manifest left stale: %s', _exc)
    if log_fn:
        log_fn(f'Library preview re-stitched from repaired tiles ({len(tiles)} tiles, {len(sheet_paths)} pages)')
    return True


def _composite_dual_preview(
    path_a: str,
    path_b: str,
    out_path: str,
    *,
    gap: int = 12,
    log_fn: Callable[[str], None] | None = None,
) -> str:
    """Stack sheets for approval preview (legacy 2-arg wrapper)."""
    return _composite_sheet_stack([path_a, path_b], out_path, gap=gap, log_fn=log_fn)


def _composite_sheet_stack(
    sheet_paths: list[str],
    out_path: str,
    *,
    gap: int = 12,
    log_fn: Callable[[str], None] | None = None,
) -> str:
    """Stack sheet PNGs vertically for approval preview."""
    from PIL import Image

    images: list[Image.Image] = []
    for p in sheet_paths:
        if p and os.path.isfile(p):
            images.append(Image.open(p).convert('RGB'))
    if not images:
        raise FileNotFoundError('No sheet images to composite')
    w = max(im.size[0] for im in images)
    resized: list[Image.Image] = []
    for im in images:
        if im.size[0] != w:
            nh = int(im.size[1] * w / im.size[0])
            resized.append(im.resize((w, nh), Image.Resampling.LANCZOS))
        else:
            resized.append(im)
    h = sum(im.size[1] for im in resized) + gap * max(0, len(resized) - 1)
    comp = Image.new('RGB', (w, h), (28, 28, 32))
    y = 0
    for i, im in enumerate(resized):
        comp.paste(im, (0, y))
        y += im.size[1] + (gap if i < len(resized) - 1 else 0)
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    comp.save(out_path, format='PNG')
    if log_fn:
        log_fn(f'Multi-sheet composite preview {w}×{h} ({len(resized)} sheets) → {out_path}')
    return out_path


def _resize_tile_for_export(crop, export_w: int, export_h: int, angle: str = ''):
    """Cover-crop to export aspect so faces are not squashed.

    Full-body panels bypass the head-and-shoulders crop entirely — the upper-90%
    assumption amputates legs/feet on A-pose and T-pose cells; they letterbox-fit
    instead (aspect-bucket training handles the mixed geometry).
    """
    from PIL import Image

    if export_w <= 0 or export_h <= 0:
        return crop
    cw, ch = crop.size
    if cw < 8 or ch < 8:
        return crop.resize((export_w, export_h), Image.Resampling.LANCZOS)
    if _is_full_body_angle(angle):
        target_w, target_h = _cell_size_for_angle(angle)
        scale = min(target_w / cw, target_h / ch)
        return crop.resize(
            (max(8, int(cw * scale)), max(8, int(ch * scale))),
            Image.Resampling.LANCZOS,
        )
    # Head-and-shoulders: keep upper ~90% of cell (drop empty gutter below chin).
    head_h = max(8, int(ch * 0.9))
    work = crop.crop((0, 0, cw, head_h))
    tw, th = work.size
    target_ar = export_w / export_h
    src_ar = tw / th
    if src_ar > target_ar:
        new_w = int(th * target_ar)
        x0 = (tw - new_w) // 2
        work = work.crop((x0, 0, x0 + new_w, th))
    else:
        new_h = int(tw / target_ar)
        y0 = max(0, (th - new_h) // 4)
        work = work.crop((0, y0, tw, min(th, y0 + new_h)))
    return work.resize((export_w, export_h), Image.Resampling.LANCZOS)
