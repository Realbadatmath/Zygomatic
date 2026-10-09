# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Sheet slicing and tile export.

Moved verbatim out of the old single-file contact_sheet_pipeline.py (lines 3393-3624).
"""

from __future__ import annotations

import os
import shutil
from typing import Callable

from zyg_workflows.contact_sheet_pipeline.constants import (
    CONTACT_SHEET_ANGLE_LABELS,
    DEFAULT_CELL_H,
    DEFAULT_CELL_W,
    DEFAULT_COLS,
    DEFAULT_GUTTER,
    DEFAULT_ROWS,
    EXPORT_CELL_H,
    EXPORT_CELL_W,
    _zyg_log,
)
from zyg_workflows.contact_sheet_pipeline.layout import (
    _angle_label,
    _angles_for_sheet_part,
    load_manifest,
    master_sheet_path,
    master_sheet_path_part,
    tiles_dir,
    write_manifest,
)
from zyg_workflows.contact_sheet_pipeline.stitch import _resize_tile_for_export


def _slice_sheet_image(
    img,
    *,
    rows: int,
    cols: int,
    gutter: int,
    cell_w: int,
    cell_h: int,
    manifest: dict,
    tdir: str,
    sheet_part: str,
    angle_offset: int,
    angle_labels: list[str] | None,
    start_index: int,
) -> tuple[list[dict], int, int, int]:
    """Crop one master sheet; return (tile metas, cell_w, cell_h, next_index)."""

    sw, sh = img.size
    if sw != cols * cell_w + (cols + 1) * gutter:
        cell_w = max(64, (sw - (cols + 1) * gutter) // max(cols, 1))
    if sh != rows * cell_h + (rows + 1) * gutter:
        cell_h = max(64, (sh - (rows + 1) * gutter) // max(rows, 1))

    export_w = int(manifest.get('export_cell_width') or EXPORT_CELL_W)
    export_h = int(manifest.get('export_cell_height') or EXPORT_CELL_H)
    tiles: list[dict] = []
    idx = start_index
    for r in range(rows):
        for c in range(cols):
            x0 = gutter + c * (cell_w + gutter)
            y0 = gutter + r * (cell_h + gutter)
            x1 = min(x0 + cell_w, sw)
            y1 = min(y0 + cell_h, sh)
            crop = img.crop((x0, y0, x1, y1))
            local_i = r * cols + c
            angle = (
                angle_labels[local_i]
                if angle_labels and local_i < len(angle_labels)
                else _angle_label(angle_offset + local_i)
            )
            if export_w > 0 and export_h > 0 and crop.size != (export_w, export_h):
                crop = _resize_tile_for_export(crop, export_w, export_h, angle)
            fname = f'tile_{sheet_part}_{r:02d}_{c:02d}.png'
            fpath = os.path.join(tdir, fname)
            crop.save(fpath, format='PNG')
            tiles.append(
                {
                    'index': idx,
                    'row': r,
                    'col': c,
                    'sheet_part': sheet_part,
                    'path': fpath,
                    'angle': angle,
                    'bbox': [x0, y0, x1, y1],
                }
            )
            idx += 1
    return tiles, cell_w, cell_h, idx


def split_sheet_into_tiles(
    char_id: str,
    *,
    log_fn: Callable[[str], None] | None = None,
) -> list[dict]:
    """Crop master sheet(s) to tiles/; update manifest. Returns tile metadata list."""
    manifest = load_manifest(char_id) or {}
    gutter = int(manifest.get('gutter_px') or DEFAULT_GUTTER)
    rows = int(manifest.get('rows') or DEFAULT_ROWS)
    cols = int(manifest.get('cols') or DEFAULT_COLS)
    cell_w = int(manifest.get('cell_width') or DEFAULT_CELL_W)
    cell_h = int(manifest.get('cell_height') or DEFAULT_CELL_H)
    composite = manifest.get('sheet_path') or master_sheet_path(char_id)

    from PIL import Image

    tdir = tiles_dir(char_id)
    os.makedirs(tdir, exist_ok=True)
    tiles: list[dict] = []
    idx = 0

    if manifest.get('generation_mode') in ('pose_locked_ipa_openpose', 'per_cell_ipa'):
        paths = manifest.get('cell_paths') or []
        labels = manifest.get('cell_angles') or CONTACT_SHEET_ANGLE_LABELS
        part_tag = 'cell' if manifest.get('generation_mode') == 'per_cell_ipa' else 'pose'
        for i, src in enumerate(paths):
            if not src or not os.path.isfile(src):
                continue
            fname = f'tile_{i:03d}.png'
            dest = os.path.join(tdir, fname)
            shutil.copy2(src, dest)
            # 03d migration: a pre-migration tile_NN.png for the same index is
            # stale — remove it or restitch/QC listings would see BOTH.
            _legacy_tile = os.path.join(tdir, f'tile_{i:02d}.png')
            if _legacy_tile != dest and os.path.isfile(_legacy_tile):
                try:
                    os.remove(_legacy_tile)
                except OSError as _exc:
                    _zyg_log.warning(
                        'stale 02d tile %s not removed, listings may see the tile twice: %s', _legacy_tile, _exc
                    )
            angle = labels[i] if i < len(labels) else _angle_label(i)
            tiles.append(
                {
                    'index': i,
                    'path': dest,
                    'angle': angle,
                    'sheet_part': part_tag,
                }
            )
        write_manifest(
            char_id,
            rows=int(manifest.get('rows') or 4),
            cols=int(manifest.get('cols') or 6),
            gutter=gutter,
            cell_w=cell_w,
            cell_h=cell_h,
            sheet_path=composite,
            approved=bool(manifest.get('approved')),
            tiles=tiles,
            extra={
                k: manifest[k]
                for k in manifest
                if k
                not in (
                    'char_id',
                    'pipeline',
                    'rows',
                    'cols',
                    'gutter_px',
                    'cell_width',
                    'cell_height',
                    'sheet_path',
                    'approved',
                    'approved_at',
                    'tiles',
                    'updated_at',
                )
            },
        )
        if log_fn:
            log_fn(
                f'Tile crop ({manifest.get("generation_mode")}) — {len(tiles)} cells copied → {tdir}',
            )
        return tiles

    if manifest.get('dual_sheet') and manifest.get('sheets'):
        for spec in manifest['sheets']:
            part = spec.get('part') or 'a'
            spath = spec.get('master_path') or master_sheet_path_part(char_id, part)
            if not os.path.isfile(spath):
                raise FileNotFoundError(f'Dual sheet {part} not found: {spath}')
            img = Image.open(spath).convert('RGB')
            s_rows = int(spec.get('rows') or rows)
            s_cols = int(spec.get('cols') or cols)
            angle_offset = int(spec.get('angle_offset') or 0)
            labels = spec.get('angles') or _angles_for_sheet_part(part)
            part_tiles, cell_w, cell_h, idx = _slice_sheet_image(
                img,
                rows=s_rows,
                cols=s_cols,
                gutter=gutter,
                cell_w=cell_w,
                cell_h=cell_h,
                manifest=manifest,
                tdir=tdir,
                sheet_part=part,
                angle_offset=angle_offset,
                angle_labels=labels,
                start_index=idx,
            )
            tiles.extend(part_tiles)
            if log_fn:
                log_fn(f'Sheet {part.upper()} — {len(part_tiles)} tiles from {os.path.basename(spath)}')
        sheet_for_manifest = composite
    else:
        sheet = composite
        if not os.path.isfile(sheet):
            raise FileNotFoundError(f'Contact sheet not found: {sheet}')
        img = Image.open(sheet).convert('RGB')
        tiles, cell_w, cell_h, _idx = _slice_sheet_image(
            img,
            rows=rows,
            cols=cols,
            gutter=gutter,
            cell_w=cell_w,
            cell_h=cell_h,
            manifest=manifest,
            tdir=tdir,
            sheet_part='',
            angle_offset=0,
            angle_labels=None,
            start_index=0,
        )
        sheet_for_manifest = sheet

    extra = {
        k: manifest[k]
        for k in manifest
        if k
        not in (
            'char_id',
            'pipeline',
            'rows',
            'cols',
            'gutter_px',
            'cell_width',
            'cell_height',
            'sheet_path',
            'approved',
            'approved_at',
            'tiles',
            'updated_at',
        )
    }
    write_manifest(
        char_id,
        rows=rows,
        cols=cols,
        gutter=gutter,
        cell_w=cell_w,
        cell_h=cell_h,
        sheet_path=sheet_for_manifest,
        approved=bool(manifest.get('approved')),
        tiles=tiles,
        extra=extra,
    )
    if log_fn:
        log_fn(f'Tile crop complete — {len(tiles)} tiles → {tdir}')
    return tiles
