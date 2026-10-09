# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""movement_studio.plates — prop plate building (depth/normal/lineart)."""

import json
import os
import logging as _zyg_logging

from zyg_workflows.movement_studio.options import _OUT_ROOT
from zyg_workflows.movement_studio.params import sanitize

_zyg_log = _zyg_logging.getLogger(__package__)


# ─────────────────────────────────────────────── prop plates (2026-09-02, S05)
# The MISSING block used to say prop_plates wanted "rendered geometry for a
# registered prop mesh in this shot's pose" and that "nothing here knows where
# the prop is in the frame". Both halves are now supplied: mesh_control has
# already written depth/normal/lineart maps for every registered asset view, and
# the PROP PLATES rack asks for the in-frame box (typed, or read off SAM 3).
#
# What reaches what, exactly — prop_control.composite_into_control consumes a
# plate dict of {'plate', 'meta', 'quad', 'strength'} and NOTHING else. There is
# deliberately no per-plate end-percent dial here: the control channel (plates
# included) is released at vace_end_percent, which is already the 'Pin end %'
# lever, and a second copy of it on this rack would be inert.
_PLATE_DIR = os.path.join(_OUT_ROOT, '_plates')
_PLATE_KINDS = ('depth', 'normal', 'lineart')


def _plate_log(fn):
    return fn or (lambda _m: None)


def resolve_view(asset_id: str, view: str, log_fn=None) -> str:
    """The view id to render the plate from — 'auto' resolves to the first view
    the asset's control manifest actually WROTE, not the first view it declares.
    A view that mesh_control skipped (empty subject mask) has no map on disk."""
    log = _plate_log(log_fn)
    try:
        from zyg_workflows import mesh_control as MC

        man = MC.ensure(asset_id)
    except Exception as e:  # noqa: BLE001
        log(f'[plate] mesh_control unavailable ({e})')
        return ''
    built = list((man.get('views') or {}).keys())
    if not built:
        log(f'[plate] {asset_id}: no control views built')
        return ''
    if view and view != 'auto':
        if view in built:
            return view
        log(
            f'[plate] {asset_id}: view {view!r} has no control map (built: '
            f'{", ".join(built[:6])}...) — using {built[0]}'
        )
    return built[0]


def build_plate(asset_id: str, view: str, kind: str = 'depth', log_fn=None):
    """-> (rgba_png_path, meta_dict) or (None, None).

    mesh_control writes FULL-FRAME single-channel maps with no alpha, and
    prop_control multiplies by the plate's alpha. Handing it an opaque
    full-frame map would paint the render's empty background into the control
    as well as the object. So the plate is cropped to the matte's bounding box
    and given the matte as its alpha; the meta then says the plate's own four
    corners are what the destination quad receives.

    Cached under output/movement/_plates keyed by the source map's mtime, so a
    rebuilt control map produces a new plate and a re-render does not."""
    log = _plate_log(log_fn)
    if kind not in _PLATE_KINDS:
        log(f'[plate] unknown channel {kind!r}')
        return None, None
    try:
        from zyg_workflows import mesh_control as MC
        from PIL import Image
    except Exception as e:  # noqa: BLE001
        log(f'[plate] deps unavailable ({e})')
        return None, None
    src_map = MC.path_for(asset_id, view, kind)
    matte = MC.path_for(asset_id, view, 'matte')
    if not (src_map and os.path.isfile(src_map)):
        log(f'[plate] {asset_id}/{view}: no {kind} map on disk')
        return None, None
    if not (matte and os.path.isfile(matte)):
        log(f'[plate] {asset_id}/{view}: no matte — refusing to plate a full frame')
        return None, None
    try:
        stamp = int(max(os.path.getmtime(src_map), os.path.getmtime(matte)))
    except OSError:
        return None, None
    os.makedirs(_PLATE_DIR, exist_ok=True)
    base = os.path.join(_PLATE_DIR, f'{asset_id}_{view}_{kind}_{stamp}')
    png, mjs = base + '.png', base + '.json'
    if os.path.isfile(png) and os.path.isfile(mjs):
        try:
            return png, json.load(open(mjs, encoding='utf-8'))
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('cached matte metrics %s unreadable, recomputing them: %s', mjs, _exc)
    try:
        m = Image.open(matte).convert('L')
        im = Image.open(src_map).convert('RGB')
        if im.size != m.size:
            im = im.resize(m.size)
        bbox = m.point(lambda v: 255 if v > 8 else 0).getbbox()
        if not bbox:
            log(f'[plate] {asset_id}/{view}: matte is empty')
            return None, None
        im, m = im.crop(bbox), m.crop(bbox)
        w, h = im.size
        rgba = im.convert('RGBA')
        rgba.putalpha(m)
        rgba.save(png)
        meta = {
            'aligned': False,
            'size': [w, h],
            'page_quad_render': [[0, 0], [w, 0], [w, h], [0, h]],
            'asset': asset_id,
            'view': view,
            'kind': kind,
            'source_map': src_map,
            'source_matte': matte,
            'crop_in_render': list(bbox),
        }
        with open(mjs, 'w', encoding='utf-8') as fh:
            json.dump(meta, fh, indent=2)
        log(f'[plate] built {os.path.basename(png)} {w}x{h} from {kind}')
        return png, meta
    except Exception as e:  # noqa: BLE001 — a bad plate must leave the control alone
        log(f'[plate] build failed ({e})')
        return None, None


def _typed_box(raw: str):
    """x,y,w,h fractions -> (x,y,w,h), or None. Same refuse-rather-than-guess
    contract as _pin_regions: an unparseable box leaves the plate OFF."""
    raw = str(raw or '').replace(' ', '')
    if not raw:
        return None
    try:
        x, y, w, h = (float(v) for v in raw.split(',')[:4])
    except (TypeError, ValueError):
        return None
    if not (0.0 <= x < 1.0 and 0.0 <= y < 1.0 and 0.0 < w <= 1.0 and 0.0 < h <= 1.0):
        return None
    if x + w > 1.0 or y + h > 1.0:
        return None
    return (x, y, w, h)


def auto_box(still_path: str, phrase: str, log_fn=None):
    """The highest-scoring SAM 3 instance for `phrase`, as (x,y,w,h) fractions.
    None on anything at all — the caller then falls back to the typed box, never
    to a guess."""
    log = _plate_log(log_fn)
    if not (still_path and os.path.isfile(still_path) and str(phrase or '').strip()):
        return None
    try:
        from zyg_workflows import sam3_service as S3
        from PIL import Image

        res = S3.segment(still_path, [phrase], log_fn=log)
        inst = ((res or {}).get(phrase) or {}).get('instances') or []
        if not inst:
            log(f'[plate] SAM3 found no {phrase!r} — keeping the typed box')
            return None
        best = max(inst, key=lambda i: i.get('score', 0.0))
        x0, y0, x1, y1 = best['box_xyxy']
        W, H = Image.open(still_path).size
        box = (x0 / W, y0 / H, (x1 - x0) / W, (y1 - y0) / H)
        log(
            f'[plate] SAM3 box for {phrase!r}: '
            + ','.join(f'{v:.3f}' for v in box)
            + f' (score {best.get("score", 0):.2f})'
        )
        return box
    except Exception as e:  # noqa: BLE001
        log(f'[plate] auto box failed ({e}) — keeping the typed box')
        return None


def prop_plates(p: dict, still_path: str = '', log_fn=None):
    """The prop_plates= argument for generate_vace_static_clip, or None.

    None (not []) when the rack is off, because wan_vace_service tests the value
    for truth and an empty list would still enter the composite branch and log a
    plate pass that painted nothing."""
    log = _plate_log(log_fn)
    p = sanitize(p)
    asset = str(p.get('plate_object') or 'none')
    if asset == 'none':
        return None
    box = None
    if p.get('plate_auto'):
        box = auto_box(still_path, p.get('plate_phrase'), log_fn=log)
    if box is None:
        box = _typed_box(p.get('plate_box'))
    if box is None:
        log(f'[plate] {asset}: no in-frame box (typed or auto) — plate OFF')
        return None
    view = resolve_view(asset, str(p.get('plate_view') or 'auto'), log_fn=log)
    if not view:
        return None
    png, meta = build_plate(asset, view, str(p.get('plate_kind') or 'depth'), log_fn=log)
    if not png:
        return None
    x, y, w, h = box
    quad = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
    return [{'plate': png, 'meta': meta, 'quad': quad, 'strength': float(p.get('plate_strength', 0.6))}]


def plate_chip(p: dict) -> dict:
    """What the GUI shows beside the rack: the exact control map this dial state
    will plate, or the reason there is none. Never a render."""
    p = sanitize(p)
    asset = str(p.get('plate_object') or 'none')
    if asset == 'none':
        return {'on': False, 'why': 'no object chosen'}
    view = resolve_view(asset, str(p.get('plate_view') or 'auto'))
    if not view:
        return {
            'on': False,
            'why': f'{asset} has no built control maps (run: python -m zyg_workflows.mesh_control ' + asset + ')',
        }
    kind = str(p.get('plate_kind') or 'depth')
    try:
        from zyg_workflows import mesh_control as MC

        src = MC.path_for(asset, view, kind)
    except Exception as e:  # noqa: BLE001
        return {'on': False, 'why': f'mesh_control unavailable ({e})'}
    have = bool(src and os.path.isfile(src))
    box = _typed_box(p.get('plate_box'))
    return {
        'on': have and (box is not None or bool(p.get('plate_auto'))),
        'asset': asset,
        'view': view,
        'kind': kind,
        'map': src if have else '',
        'map_exists': have,
        'box': list(box) if box else None,
        'auto': bool(p.get('plate_auto')),
        'strength': float(p.get('plate_strength', 0.6)),
        'why': '' if have else f'no {kind} map for {view}',
    }
