# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""storyteller_scene_service.frame — the first half of the video-helpers section — Ken Burns framing, overlays, grade and camera routes (lines 981-1244).

Moved verbatim out of the old single-file storyteller_scene_service.py.
"""

from __future__ import annotations

from zyg_workflows.storyteller_scene_service.constants import (
    Image,
    _log_noop,
    np,
)

# ── video helpers ────────────────────────────────────────────────────────────


def _zoom_frame(base: Image.Image, W: int, H: int, z: float, focus_xy: tuple = (0.5, 0.5)) -> Image.Image:
    """Crop a window `z`× tighter than the whole frame and deliver it at (W,H).

    focus_xy is the point of the SOURCE (normalised) held at the centre of the
    window, clamped so the window never leaves the image. The clamp is what
    makes a pull-out look filmed: as z falls toward 1 the window can no longer
    stay on the focus point, so the framing drifts back to centre on its own.

    `base` may be an upscaled still (see _base_scale_for): at z == that scale
    the crop is exactly W×H source pixels, i.e. no interpolation at the tight
    end of the move.
    """
    box = _zoom_box(base, z, focus_xy)
    crop = base.crop(box)
    return crop if crop.size == (W, H) else crop.resize((W, H), Image.LANCZOS)


def _zoom_box(base: Image.Image, z: float, focus_xy: tuple = (0.5, 0.5)) -> tuple:
    """The crop rectangle _zoom_frame would take, in BASE pixels.

    Split out so that an overlay authored in base coordinates — a rope drawn on
    a chart, smoke tied to a pipe bowl — can be cut with the SAME rectangle and
    therefore stays registered to the picture through the whole camera move.
    Compositing before the resize also means the overlay is downsampled with the
    plate rather than drawn at delivery size and left crawling against it.
    """
    BW, BH = base.size
    z = max(1.0, float(z))
    cw, ch = BW / z, BH / z
    cx = min(max(float(focus_xy[0]) * BW, cw / 2), BW - cw / 2)
    cy = min(max(float(focus_xy[1]) * BH, ch / 2), BH - ch / 2)
    return (int(round(cx - cw / 2)), int(round(cy - ch / 2)), int(round(cx + cw / 2)), int(round(cy + ch / 2)))


def _compose_overlays(crop: Image.Image, box: tuple, overlays) -> Image.Image:
    """Composite base-space RGBA tiles onto an already-cropped window.

    `overlays` is [((x, y), RGBA tile), ...] positioned in base pixels. Only the
    intersection with the window is touched, which is the point: the rope tile
    covers a fifth of a 5376×3072 plate and the smoke tile a few hundred pixels,
    so a frame costs a small paste instead of a full-plate alpha composite.
    """
    x0, y0, x1, y1 = box
    out = None
    for (ox, oy), ov in overlays or ():
        if ov is None:
            continue
        ow, oh = ov.size
        ix0, iy0 = max(x0, ox), max(y0, oy)
        ix1, iy1 = min(x1, ox + ow), min(y1, oy + oh)
        if ix1 <= ix0 or iy1 <= iy0:
            continue
        if out is None:
            out = crop.convert('RGBA')
        tile = ov.crop((ix0 - ox, iy0 - oy, ix1 - ox, iy1 - oy))
        at = (ix0 - x0, iy0 - y0)
        region = out.crop((at[0], at[1], at[0] + tile.width, at[1] + tile.height))
        out.paste(Image.alpha_composite(region, tile), at)
    return out.convert('RGB') if out is not None else crop


def _kb_zoom_at(t: float, mode: str, amount: float, zoom: tuple | None) -> float:
    """Zoom factor at t in [0,1]. An explicit `zoom` (z0,z1) wins over the named
    mode — that is the hook a continuous move (dialogue framing → pull-out)
    uses to span several shot windows on ONE still without a cut.

    Interpolation is over the WINDOW WIDTH (1/z), not over z. What a viewer
    perceives is how fast new picture arrives, and that tracks width; ramping z
    linearly instead front-loads the tight end and dumps the whole reveal into
    the last second — measured on a 1.88 → 1.00 pull-out, half the hold had
    gone before the framing visibly changed.
    """
    if zoom:
        z0, z1 = float(zoom[0]), float(zoom[1])
        w = (1.0 / z0) + ((1.0 / z1) - (1.0 / z0)) * t
        return 1.0 / max(w, 1e-6)
    if mode == 'hold' or amount <= 0:
        return 1.0
    if mode == 'push_in':
        return 1.0 + amount * t
    if mode == 'pull_out':
        return 1.0 + amount * (1.0 - t)
    return 1.0 + amount  # pans hold a fixed zoom and slide instead


def _kb_keys_at(t: float, keys) -> tuple:
    """A keyframed camera move: (z, focus_xy) at t in [0,1].

    `keys` is [{'at': frac, 'z': float, 'focus': (x, y)}, ...] in order. A
    two-value `kb_zoom` can only say "travel at one rate for the whole window",
    which cannot express the chart move the scene needs — establish the world,
    THEN push into the coast, then ease off while the rope draws. Splitting it
    into windows would need a cut, and a cut on a map is a different map.

    z is interpolated over the WINDOW WIDTH (1/z) for the same reason
    _kb_zoom_at does: that is the quantity a viewer perceives as camera speed.
    """
    ks = sorted(keys, key=lambda k: float(k.get('at', 0.0)))
    t = max(0.0, min(1.0, float(t)))
    if t <= float(ks[0].get('at', 0.0)):
        k = ks[0]
        return float(k['z']), tuple(k.get('focus', (0.5, 0.5)))
    for a, b in zip(ks, ks[1:]):
        ta, tb = float(a.get('at', 0.0)), float(b.get('at', 1.0))
        if t <= tb or b is ks[-1]:
            f = 0.0 if tb <= ta else (t - ta) / (tb - ta)
            f = max(0.0, min(1.0, f))
            wa, wb = 1.0 / max(float(a['z']), 1e-6), 1.0 / max(float(b['z']), 1e-6)
            z = 1.0 / max(wa + (wb - wa) * f, 1e-6)
            fa = tuple(a.get('focus', (0.5, 0.5)))
            fb = tuple(b.get('focus', fa))
            return z, (fa[0] + (fb[0] - fa[0]) * f, fa[1] + (fb[1] - fa[1]) * f)
    k = ks[-1]
    return float(k['z']), tuple(k.get('focus', (0.5, 0.5)))


def _kb_focus_at(t: float, mode: str, amount: float, focus: str, focus_xy: tuple | None) -> tuple:
    """Normalised focus point at t. Named pans sweep it; everything else holds.

    `focus_xy` may also be a LIST of points, in which case the camera travels
    through them at constant rate across the window. That is what lets a move
    follow something — on the chart the framing tightens onto West Africa while
    sliding south with the rope, which a single fixed focus cannot express: a
    fixed focus can only tighten, and the reveal then runs out of frame.
    """
    if focus_xy is not None:
        if isinstance(focus_xy[0], (list, tuple)):
            pts = [(float(a), float(b)) for a, b in focus_xy]
            if len(pts) == 1:
                return pts[0]
            u = max(0.0, min(1.0, t)) * (len(pts) - 1)
            i = min(int(u), len(pts) - 2)
            f = u - i
            return (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f)
        return (float(focus_xy[0]), float(focus_xy[1]))
    if mode in ('pan_lr', 'pan_rl'):
        # sweep the window edge-to-edge; the clamp in _zoom_frame does the rest
        return (t if mode == 'pan_lr' else 1.0 - t, 0.5)
    return ({'left': 0.0, 'right': 1.0}.get(focus, 0.5), 0.5)


def _grade(
    img: Image.Image,
    warm: float = 0.0,
    vignette: float = 0.28,
    grain: float = 6.0,
    rng: np.random.RandomState | None = None,
) -> Image.Image:
    a = np.asarray(img, dtype=np.float32)
    if warm:
        a[..., 0] *= 1.0 + 0.06 * warm
        a[..., 2] *= 1.0 - 0.05 * warm
    if vignette:
        H, W = a.shape[:2]
        yy, xx = np.mgrid[0:H, 0:W]
        r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
        a *= 1.0 - vignette * np.clip(r - 0.45, 0, 1)[..., None] ** 1.6
    if grain and rng is not None:
        a += rng.normal(0.0, grain, a.shape).astype(np.float32)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def _smoothstep(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def _route_context(shot: dict, base_size: tuple, t0: float, t1: float, log_fn=None):
    """Everything the frame loop needs to draw a course progressively.

    The rope is accumulated INCREMENTALLY into one persistent tile: each frame
    draws only the span revealed since the last one, so the whole animation
    costs a single pass along the path instead of a full redraw per frame. The
    tile is bounded to the route plus its labels rather than covering the plate,
    which is what keeps a 5376×3072 chart affordable at 24 fps.
    """
    from zyg_workflows import maritime_map_service as mms

    log = log_fn or _log_noop
    chart = mms.get_chart(log_fn=log)
    legs = shot['route'].get('legs', 'WEST_AFRICA_RUN')
    legs = getattr(mms, legs) if isinstance(legs, str) else legs
    path, marks = mms.route_path(legs, chart)
    verdict = mms.check_route(path, chart, marks=marks, log_fn=log)
    if not verdict['clear']:
        log('[scene] WARN the course sails over land — see the crossings above')

    pad = 520
    x0 = max(0, int(path[:, 0].min()) - pad)
    y0 = max(0, int(path[:, 1].min()) - pad)
    x1 = min(base_size[0], int(path[:, 0].max()) + pad)
    y1 = min(base_size[1], int(path[:, 1].max()) + pad)

    # When does the rope reach each port? The reveal is eased, so arrival is not
    # linear in time and cannot be read off `frac` directly — invert the ease
    # once, here, rather than guessing per frame.
    grid = np.linspace(0.0, 1.0, 4001)
    eased = grid * grid * (3.0 - 2.0 * grid)
    for m in marks:
        k = int(np.searchsorted(eased, m['frac']))
        m['t_arrive'] = t0 + (t1 - t0) * grid[min(k, len(grid) - 1)]

    return {
        'origin': (x0, y0),
        'path': path,
        'path_local': path - np.array([[x0, y0]], dtype=np.float64),
        'marks': marks,
        'rope_ov': Image.new('RGBA', (max(1, x1 - x0), max(1, y1 - y0)), (0, 0, 0, 0)),
        'marks_ov': None,
        'marks_state': None,
        'cursor': 0,
        't0': float(t0),
        't1': float(t1),
        'width': float(shot['route'].get('width', 9.0)),
        'lay_px': float(shot['route'].get('lay_px', 16.0)),
        'port_fade_s': float(shot['route'].get('port_fade_s', 0.7)),
        'label_size': int(shot['route'].get('label_size', 34)),
        'ports': {k: v for k, v in mms.PORTS.items()},
    }


def _route_advance(rc: dict, t_abs: float):
    """Bring the course up to date for this instant."""
    from zyg_workflows import maritime_map_service as mms

    n = len(rc['path'])
    span = max(1e-6, rc['t1'] - rc['t0'])
    u = _smoothstep((t_abs - rc['t0']) / span)
    target = int(round(u * (n - 1)))
    if target > rc['cursor']:
        mms.draw_rope(rc['rope_ov'], rc['path_local'], rc['cursor'], target, width=rc['width'], lay_px=rc['lay_px'])
        rc['cursor'] = target

    # Ports are drawn into their OWN tile, cleared and redrawn only while one of
    # them is still fading up. Accumulating them into the rope tile instead would
    # compound alpha over the leader lines and darken them unevenly — and the
    # Gold Coast leaders overlap each other, so it would show.
    fade = max(1e-6, rc['port_fade_s'])
    alphas = tuple(round(max(0.0, min(1.0, (t_abs - m['t_arrive']) / fade)), 2) for m in rc['marks'])
    if alphas == rc['marks_state']:
        return
    rc['marks_state'] = alphas
    if not any(alphas):
        rc['marks_ov'] = None
        return
    ov = Image.new('RGBA', rc['rope_ov'].size, (0, 0, 0, 0))
    ox, oy = rc['origin']
    for m, a in zip(rc['marks'], alphas):
        if a <= 0.0:
            continue
        mms.draw_port_mark(
            ov,
            (m['xy'][0] - ox, m['xy'][1] - oy),
            m['name'],
            a,
            size=rc['label_size'],
            label=rc['ports'][m['key']].get('label', (80, 0, 'lm')),
        )
    rc['marks_ov'] = ov
