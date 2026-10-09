# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""storyteller_scene_service.bird_sprite — the canary palette and the bird sprite compositor of the video-helpers section (lines 2254-2748).

Moved verbatim out of the old single-file storyteller_scene_service.py.
"""

from __future__ import annotations

from zyg_workflows.storyteller_scene_service.constants import (
    Image,
    ImageDraw,
    ImageFilter,
    ImageOps,
    json,
    math,
    np,
    os,
)
from zyg_workflows.storyteller_scene_service.frame import (
    _smoothstep,
)
from zyg_workflows.storyteller_scene_service.bird_wing import (
    _bird_wing,
)
from zyg_workflows.storyteller_scene_service.bird_flight import (
    _bird_box,
    _bird_pose,
    _bird_wing_polys,
    _closed_spline,
)

# A canary is NOT a yellow blob. Wild-type Serinus canaria is a streaky
# yellow-green finch, and the domestic bird keeps the same MAP even when the
# ground colour is bred to lemon or orange: darker olive mantle, olive-brown
# wing coverts crossed by a pale wing bar, near-black primaries, a bright face,
# a pale belly and a pale rump. Painting all of that one yellow is what made
# the first bird read as a rubber duck.
_CANARY = {
    'belly': (250, 238, 176),  # pale, almost cream underneath
    'breast': (250, 214, 74),  # lemon
    'body': (250, 206, 46),  # flank / ground colour
    'mantle': (198, 176, 58),  # olive-green back
    'crown': (232, 168, 40),  # warm crown
    'head': (250, 166, 44),  # bright orange-yellow face
    'cheek': (206, 128, 34),  # darker ear-coverts
    'covert': (168, 138, 44),  # wing coverts, olive-brown
    'bar': (238, 224, 176),  # the pale wing bar across them
    'primary': (86, 74, 52),  # near-black flight feathers
    'wing_far': (128, 104, 38),
    'tail': (150, 126, 44),
    'rump': (238, 226, 150),
    'beak': (232, 186, 132),  # horn, not carrot
    'eye': (26, 20, 14),
    'leg': (206, 150, 118),
}


_BIRD_SPRITES: dict = {}


def _bird_sprite_set(cfg: dict) -> dict:
    """Load and cache the RGBA phase sprites named by cfg['sprites'].

    `sprites` is a directory holding a sprites.json written by the bird-sheet
    build: one RGBA cut-out per wingbeat phase, each with the width of its own
    body core and the centroid of that core. The body core is the anchor and
    the size reference rather than the bounding box, because the box changes
    by a factor of three through a wingbeat and anchoring on it would make the
    bird pump forward and back along the path as its wings opened.
    """
    return _bird_sprite_set_at(str(cfg['sprites']))


def _bird_sprite_set_at(d: str) -> dict:
    """Same as `_bird_sprite_set`, keyed on an explicit directory rather than
    `cfg['sprites']` — so a second, alternate view (e.g. the side-on ladder
    in `cfg['sprites_side']`) can be loaded the same way without a second
    cfg dict to carry it."""
    got = _BIRD_SPRITES.get(d)
    if got is not None:
        return got
    with open(os.path.join(d, 'sprites.json')) as fh:
        man = json.load(fh)
    out = {}
    for phase, rec in man['phases'].items():
        im = Image.open(os.path.join(d, rec['file'])).convert('RGBA')
        out[phase] = {
            'im': im,
            'body_w': float(rec['body_w']),
            'anchor': tuple(float(v) for v in rec['anchor']),
            'elev': rec.get('elev'),
        }
    _BIRD_SPRITES[d] = out
    return out


def _bird_phase(pose: dict) -> str:
    """Which wingbeat sprite this pose wants.

    A bounding flight is a burst of beats and then a closed-wing fall, so the
    glide sprite is chosen off `tuck` before the stroke is looked at at all —
    the thing that makes a small bird read as a small bird is that the wings
    STOP, and a set of four flapping sprites cycled continuously loses exactly
    that.
    """
    return _bird_phase_at(pose['flap'], pose['tuck'], None)


def _bird_phase_at(elev: float, tuck: float, sprites: dict | None) -> str:
    """The ladder cell nearest this wing elevation.

    A LADDER, not three cases. Four sprites over a beat the frame rate barely
    resolves is why the delivered file spent 31 of 65 wing-phase runs on a
    single frame: there was nothing to show in between. The set is now five
    elevations from one seed, and the cell is chosen by nearest `elev`, so the
    same code works if more are rendered later.

    The glide cell is whichever phase carries `elev: null` in ITS OWN
    manifest — not a hardcoded 'rear_glide' — because a second ladder (e.g.
    the side-on set) names its glide cell 'side_glide'. Hardcoding the rear
    name here silently broke the moment a differently-named `sprites` dict
    was passed in (KeyError inside `_bird_wing_tile`, since it looks the
    returned name up in whichever dict it was given) — caught by actually
    running the side-blend renderer, not by any check that only inspects
    `cfg` in isolation.
    """
    if not sprites:
        if tuck > 0.5:
            return 'rear_glide'
        if elev > 0.34:
            return 'rear_up'
        if elev < -0.34:
            return 'rear_down'
        return 'rear_level'
    glide = next((name for name, rec in sprites.items() if rec.get('elev') is None), None)
    if tuck > 0.5 and glide is not None:
        return glide
    best, bd = next(iter(sprites)), 9.9
    for name, rec in sprites.items():
        e = rec.get('elev')
        if e is None:
            continue
        d = abs(float(e) - elev)
        if d < bd:
            best, bd = name, d
    return best


def _bird_wing_tile(cfg: dict, sprites: dict, pose: dict, body_px: float, roll: float) -> tuple:
    """The bird as one RGBA tile, with the WINGS motion-blurred and the body not.

    This is the single thing the reference clip has that a sprite sequence does
    not, and it is not a stylistic flourish — it is what a camera does. In that
    clip the body stays sharp while the wings smear into semi-transparent fans,
    because within one exposure the wing tips travel most of a wingspan and the
    body travels almost nothing.

    So: sample the WING STATE across the shutter and accumulate, but leave the
    position and the scale at their mid-exposure values. The body lands on the
    same pixels in every sub-sample and stays sharp; the wings land somewhere
    different each time and average into a fan. Body travel over a 1/48 s
    exposure is about four plate pixels at the near end of this flight, which
    is why not blurring it costs nothing and buys a sharp bird.

    Falls back to a single sample when `shutter_frac` is 0, which is what the
    glide phase effectively does anyway — all sub-samples pick the same closed
    -wing sprite, so the blur disappears exactly when the wings stop.
    """
    k = max(1, int(cfg.get('blur_samples', 5)))
    shutter = float(cfg.get('shutter_frac', 0.0)) / max(1.0, float(cfg.get('fps', 24.0)))
    t0 = float(pose.get('t_rel', 0.0))
    ts = [t0] if (k < 2 or shutter <= 1e-6) else [t0 + (j / (k - 1.0) - 0.5) * shutter for j in range(k)]

    tiles = []
    for tj in ts:
        if len(ts) == 1:
            elev, tuck = pose['flap'], pose['tuck']
        else:
            elev, tuck, _ = _bird_wing(cfg, max(0.0, tj))
        sp = sprites[_bird_phase_at(elev, tuck, sprites)]
        s = body_px / max(1e-6, sp['body_w'])
        im = sp['im'].resize(
            (max(2, int(round(sp['im'].width * s))), max(2, int(round(sp['im'].height * s)))), Image.LANCZOS
        )
        ax, ay = sp['anchor'][0] * s, sp['anchor'][1] * s
        if abs(roll) > 0.2:
            before = (im.width, im.height)
            im = im.rotate(roll, resample=Image.BICUBIC, expand=True)
            ax += (im.width - before[0]) * 0.5
            ay += (im.height - before[1]) * 0.5
        tiles.append((im, ax, ay))

    if len(tiles) == 1:
        return tiles[0]

    # one canvas big enough for every sub-sample, all registered on the anchor
    left = max(t[1] for t in tiles)
    top = max(t[2] for t in tiles)
    right = max(t[0].width - t[1] for t in tiles)
    bot = max(t[0].height - t[2] for t in tiles)
    Wc, Hc = int(math.ceil(left + right)), int(math.ceil(top + bot))
    acc = np.zeros((Hc, Wc, 4), dtype=np.float32)
    for im, ax, ay in tiles:
        a = np.asarray(im, dtype=np.float32)
        ox, oy = int(round(left - ax)), int(round(top - ay))
        h, w = a.shape[:2]
        sub = acc[oy : oy + h, ox : ox + w]
        al = a[..., 3:4] / 255.0
        # premultiplied, so a half-transparent wing averages as half a wing
        sub[..., :3] += a[..., :3] * al
        sub[..., 3:4] += al
    acc /= float(len(tiles))
    al = np.clip(acc[..., 3:4], 0.0, 1.0)
    rgb = np.where(al > 1e-4, acc[..., :3] / np.maximum(al, 1e-4), 0.0)
    out = np.dstack([np.clip(rgb, 0, 255), al * 255.0]).astype(np.uint8)
    return Image.fromarray(out, 'RGBA'), left, top


def _bird_view_blend(a_tile: tuple, b_tile: tuple, wb: float) -> tuple:
    """Cross-fade two already-rendered bird tiles — e.g. the rear-view tile
    and the side-view tile for the same instant — by weight `wb` (0 = pure
    a, 1 = pure b), each registered on its own anchor point.

    Same premultiplied-alpha accumulation `_bird_wing_tile` uses to average
    motion-blur sub-samples, applied here to blend VIEWS instead of time-
    samples: two DIFFERENT silhouettes double-expose through the transition
    band rather than morphing, which is the honest result of not having a
    true in-between rendered view — but at the two ends of the blend (wb=0
    or 1, i.e. most of any given flight) it reduces to exactly the single
    sprite that view alone would have drawn.
    """
    (ima, axa, aya), (imb, axb, ayb) = a_tile, b_tile
    wa = 1.0 - wb
    if wa <= 1e-6:
        return imb, axb, ayb
    if wb <= 1e-6:
        return ima, axa, aya
    left = max(axa, axb)
    top = max(aya, ayb)
    right = max(ima.width - axa, imb.width - axb)
    bot = max(ima.height - aya, imb.height - ayb)
    Wc, Hc = int(math.ceil(left + right)), int(math.ceil(top + bot))
    acc = np.zeros((Hc, Wc, 4), dtype=np.float32)
    for im, ax, ay, w in ((ima, axa, aya, wa), (imb, axb, ayb, wb)):
        arr = np.asarray(im, dtype=np.float32)
        ox, oy = int(round(left - ax)), int(round(top - ay))
        h, wdt = arr.shape[:2]
        sub = acc[oy : oy + h, ox : ox + wdt]
        al = arr[..., 3:4] / 255.0
        sub[..., :3] += arr[..., :3] * al * w
        sub[..., 3:4] += al * w
    al = np.clip(acc[..., 3:4], 0.0, 1.0)
    rgb = np.where(al > 1e-4, acc[..., :3] / np.maximum(al, 1e-4), 0.0)
    out = np.dstack([np.clip(rgb, 0, 255), al * 255.0]).astype(np.uint8)
    return Image.fromarray(out, 'RGBA'), left, top


def _draw_bird_sprite(base_size: tuple, cfg: dict, pose: dict):
    """One frame of the bird from the rendered phase sprites.

    The polygon bird this replaces was drawn side-on, and side-on is the one
    view that cannot say "away from you": its silhouette at mid-stroke is a
    body with the wings edge-on, which at 40 px is a fish. These are REAR
    views — two spread wings either side of a body — which is the only
    silhouette that reads as receding, and it is legible down to about ten
    pixels.

    Correct for a bird flying dead away from the lens — wrong for one that
    is TURNING, because a rear view has no way to show YAW, only ROLL: a
    turning bird should show more of one wing and less of the other, and no
    rotation of a fixed back-view produces that (see `_bird_yaw_table`'s
    docstring — measured on the shot this was built for, most of the flight
    sits at 35-80 deg of yaw, well past dead-away). When `cfg['sprites_side']`
    names a second, SIDE-on ladder and the pose carries a yaw, cross-fade
    toward it as |yaw| grows past `yaw_side_lo_deg`, fully there past
    `yaw_side_hi_deg` — with no side set configured this is exactly the old
    rear-only behaviour, bit for bit.
    """
    BW, BH = base_size
    sprites = _bird_sprite_set(cfg)
    body_px = float(cfg.get('body_frac', 0.010)) * BW * pose['scale']

    # Bank. A bird crossing the frame while receding is turning, and a rear
    # view is the one where roll is visible as roll rather than as yaw. When
    # the flight is 3D the bank comes from the TURN, which is what a bank is;
    # on the old 2D path it falls back to the wingbeat term it used to use.
    roll = float(cfg.get('roll_deg', 0.0))
    if pose.get('bank') is not None:
        roll += float(pose['bank'])
    else:
        roll += float(cfg.get('bank_gain', 0.0)) * pose['pitch']

    side_dir = cfg.get('sprites_side')
    yaw = pose.get('yaw')
    wb = 0.0
    if side_dir and yaw is not None:
        lo = float(cfg.get('yaw_side_lo_deg', 25.0))
        hi = float(cfg.get('yaw_side_hi_deg', 65.0))
        wb = _smoothstep((abs(yaw) - lo) / max(1e-6, hi - lo))

    if wb <= 1e-6:
        im, ax, ay = _bird_wing_tile(cfg, sprites, pose, body_px, roll)
    else:
        rear_tile = _bird_wing_tile(cfg, sprites, pose, body_px, roll)
        side_sprites = _bird_sprite_set_at(str(side_dir))
        side_im, side_ax, side_ay = _bird_wing_tile(cfg, side_sprites, pose, body_px, roll)
        # The side set is authored facing screen-left. Which way to face it
        # has to come from the SAME signal that places the bird on screen —
        # `pose['head']`, the screen-space secant tangent `_bird_fly3d`
        # already computes from the projected positions — not from `yaw`, a
        # separately-built world-space heading table (different stencil,
        # different smoothing). The two are usually in step but are not the
        # same computation, and where they disagree the sprite flips against
        # its own visible direction of travel: the bird looks like it flies
        # backwards or sideways for an instant, even though the trajectory
        # underneath never reversed. `cos(head) > 0` means the projected
        # position is presently moving screen-RIGHT, which is the only case
        # the screen-left-authored side sprite needs mirroring for — and it
        # cannot disagree with where the bird is actually going, because
        # it's read off the same projection that puts it there.
        if math.cos(pose['head']) > 0.0:
            side_im = ImageOps.mirror(side_im)
            side_ax = side_im.width - side_ax
        im, ax, ay = _bird_view_blend(rear_tile, (side_im, side_ax, side_ay), wb)
    cx = pose['pos'][0] * BW
    # The scallop is measured in BODIES, not in plate pixels: a bounding flight
    # rises and falls by about its own length per beat, whatever size it is on
    # the plate, so an amplitude in pixels would make the far bird bound as far
    # as the near one and read as a wobble rather than as flight.
    cy = pose['pos'][1] * BH + pose['bob'] * body_px * float(cfg.get('bob_bodies', 3.0))
    x0 = int(math.floor(cx - ax))
    y0 = int(math.floor(cy - ay))
    if x0 + im.width <= 0 or y0 + im.height <= 0 or x0 >= BW or y0 >= BH:
        return None

    fade = 1.0
    fo = float(cfg.get('fade_out_s', 0.0))
    if fo > 0.01:
        dur = float(cfg.get('dur_s', 5.0))
        t = pose.get('t_rel', dur)
        fade = min(1.0, max(0.0, (dur - t) / fo))
    sh_amt = float(cfg.get('shade', 0.0))
    if sh_amt > 0.01 or fade < 0.999:
        a = np.asarray(im, dtype=np.float32)
        if sh_amt > 0.01:
            gy, gx = np.mgrid[0 : im.height, 0 : im.width]
            t = ((gy / max(1, im.height - 1)) + (gx / max(1, im.width - 1)) * 0.35) / 1.35
            a[..., :3] *= ((1.0 + sh_amt * 0.35) - sh_amt * t.astype(np.float32))[..., None]
        a[..., 3] *= fade
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), 'RGBA')

    blur = float(cfg.get('blur_frac', 0.0)) * BW
    if blur > 0.3:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    return (x0, y0), im


def _draw_bird(base_size: tuple, cfg: dict, t_rel: float):
    """One frame of the canary as a base-space RGBA tile, or None.

    BASE space, not delivery space, and for the same reason the smoke is: the
    bird is at a place in the HARBOUR. Drawn on the delivered frame it would
    slide across the picture the moment the camera moved.

    Drawn at `supersample`x and downsampled, because PIL's polygon fill has no
    antialiasing: a 50-px bird built from hard-edged polygons stair-steps
    differently on every frame, and at this size that reads as a glitch rather
    than as a bird.
    """
    pose = _bird_pose(cfg, t_rel)
    if pose is None:
        return None
    if cfg.get('sprites'):
        pose['t_rel'] = t_rel
        return _draw_bird_sprite(base_size, cfg, pose)
    BW, BH = base_size
    x0, y0, x1, y1 = _bird_box(base_size, cfg, pose)
    if x1 <= 0 or y1 <= 0 or x0 >= BW or y0 >= BH:
        return None  # entirely off the plate
    tw, th = max(1, x1 - x0), max(1, y1 - y0)
    ss = max(1, int(cfg.get('supersample', 3)))
    tile = Image.new('RGBA', (tw * ss, th * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)

    L = float(cfg.get('size_frac', 0.030)) * BW * pose['scale']  # half-span
    cx = pose['pos'][0] * BW - x0
    cy = pose['pos'][1] * BH + pose['bob'] * L - y0

    pal = dict(_CANARY)
    pal.update(cfg.get('palette') or {})
    C = {k: tuple(v) + (255,) for k, v in pal.items()}

    tuck = pose['tuck']
    bl = L * 0.60 * (1.0 + 0.14 * tuck)  # body half-length
    bh = L * 0.23 * (1.0 - 0.10 * tuck)  # body half-height
    ang = pose['head'] + pose['pitch']
    ca, sa = math.cos(ang), math.sin(ang)

    def draw(pts, col):
        d.polygon([((cx + x * ca - y * sa) * ss, (cy + x * sa + y * ca) * ss) for x, y in pts], fill=col)

    def ell(c, rx, ry, col, n=18):
        draw(
            [(c[0] + rx * math.cos(a * 2 * math.pi / n), c[1] + ry * math.sin(a * 2 * math.pi / n)) for a in range(n)],
            col,
        )

    up, dn = math.radians(74.0), math.radians(54.0)
    fl = pose['flap']
    base_th = (up if fl >= 0 else dn) * fl
    th_near = base_th * (1.0 - tuck) + math.radians(-8.0) * tuck
    th_far = base_th * 0.86 * (1.0 - tuck) + math.radians(-5.0) * tuck
    span = L * (1.0 - 0.66 * tuck)
    chord = L * 0.30 * (1.0 - 0.40 * tuck)
    sh = (bl * 0.10, -bh * 0.30)

    # ── far wing, behind everything ─────────────────────────────────────────
    fa, fh, _, _ = _bird_wing_polys(sh, span * 0.93, th_far, chord * 0.92)
    draw(fa, C['wing_far'])
    draw(fh, C['primary'])

    # ── tail: NOTCHED, which is what a finch has ────────────────────────────
    tl = bl * 0.95 * (1.0 + 0.18 * tuck)
    tw_ = bh * (0.80 - 0.30 * tuck)
    root = (-bl * 0.86, 0.0)
    draw(
        [
            (root[0], root[1] - tw_ * 0.55),
            (root[0] - tl, root[1] - tw_ * 1.05),
            (root[0] - tl * 0.80, root[1]),  # the notch
            (root[0] - tl, root[1] + tw_ * 0.95),
            (root[0], root[1] + tw_ * 0.55),
        ],
        C['tail'],
    )

    # ── body: a teardrop, not an ellipse ────────────────────────────────────
    body = _closed_spline(
        [
            (bl * 0.98, -bh * 0.20),  # neck, front-top
            (bl * 0.50, -bh * 1.02),  # arched back
            (-bl * 0.20, -bh * 0.92),  # mantle
            (-bl * 0.72, -bh * 0.48),  # rump
            (-bl * 0.88, 0.02),  # tail root
            (-bl * 0.60, bh * 0.55),  # vent
            (bl * 0.10, bh * 1.00),  # belly
            (bl * 0.72, bh * 0.72),  # breast
            (bl * 1.00, bh * 0.22),  # throat
        ],
        108,
    )
    draw(body, C['body'])
    # underside lighter, back darker — the map every finch has
    draw([(x, y) for x, y in body if y > -bh * 0.10], C['belly'])
    draw([(x, y) for x, y in body if y < -bh * 0.55], C['mantle'])
    draw([(x, y) for x, y in body if -bh * 0.62 <= y <= bh * 0.34 and x > -bl * 0.45], C['breast'])
    ell((-bl * 0.66, -bh * 0.22), bl * 0.20, bh * 0.34, C['rump'])

    # ── head ────────────────────────────────────────────────────────────────
    hx, hy = bl * 1.00, -bh * 0.52
    hr = bh * 0.78
    ell((hx, hy), hr * 1.06, hr, C['head'])
    ell((hx - hr * 0.30, hy - hr * 0.55), hr * 0.80, hr * 0.52, C['crown'])
    ell((hx + hr * 0.10, hy + hr * 0.30), hr * 0.52, hr * 0.40, C['cheek'])
    draw(
        [(hx + hr * 0.85, hy - hr * 0.22), (hx + hr * 1.95, hy + hr * 0.06), (hx + hr * 0.82, hy + hr * 0.42)],
        C['beak'],
    )

    # ── near wing: arm + hand + the wing bar ────────────────────────────────
    na, nh, wr, tip = _bird_wing_polys(sh, span, th_near, chord)
    draw(na, C['covert'])
    # the bar sits across the greater coverts, just inboard of the wrist
    bx = (sh[0] * 0.35 + wr[0] * 0.65, sh[1] * 0.35 + wr[1] * 0.65)
    bnx, bny = -(wr[1] - sh[1]), (wr[0] - sh[0])
    bm = math.hypot(bnx, bny) or 1.0
    bnx, bny = bnx / bm, bny / bm
    bw = chord * 0.11
    bl2 = span * 0.13
    ux, uy = (wr[0] - sh[0]) / bm, (wr[1] - sh[1]) / bm
    draw(
        [
            (bx[0] - ux * bl2 + bnx * bw, bx[1] - uy * bl2 + bny * bw),
            (bx[0] + ux * bl2 + bnx * bw * 0.5, bx[1] + uy * bl2 + bny * bw * 0.5),
            (bx[0] + ux * bl2 - bnx * bw * 0.5, bx[1] + uy * bl2 - bny * bw * 0.5),
            (bx[0] - ux * bl2 - bnx * bw, bx[1] - uy * bl2 - bny * bw),
        ],
        C['bar'],
    )
    draw(nh, C['primary'])

    if hr * 0.26 * ss > 1.2:
        ell((hx + hr * 0.22, hy - hr * 0.14), hr * 0.24, hr * 0.24, C['eye'])

    tile = tile.resize((tw, th), Image.LANCZOS)

    # ── make it belong to the picture ───────────────────────────────────────
    # The plate is an illustration: every shape in it carries a dark ink line
    # and a lit/shadowed side. A flat-filled bird with neither is a sticker on
    # a painting. The line is a DILATION of the bird's own alpha rather than an
    # outline drawn per shape, so it wraps the silhouette — wings, tail and all
    # — without needing to know what any of the shapes are.
    if cfg.get('ink') is not False:
        k = int(max(1, round(float(cfg.get('ink_px', 2.0))))) * 2 + 1
        alpha = tile.split()[-1]
        dil = alpha.filter(ImageFilter.MaxFilter(k))
        line = Image.new('RGBA', tile.size, tuple(cfg.get('ink_rgb', (46, 34, 22))) + (255,))
        line.putalpha(dil)
        tile = Image.alpha_composite(line, tile)
    # Shading: the sun is in the upper-left corner of this plate, so the bird's
    # underside is darker than its back.
    sh_amt = float(cfg.get('shade', 0.30))
    if sh_amt > 0.01:
        a = np.asarray(tile, dtype=np.float32)
        gy, gx = np.mgrid[0 : tile.height, 0 : tile.width]
        t = ((gy / max(1, tile.height - 1)) * 1.0 + (gx / max(1, tile.width - 1)) * 0.35) / 1.35
        m = (1.0 + sh_amt * 0.35) - sh_amt * t.astype(np.float32)
        a[..., :3] *= m[..., None]
        tile = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), 'RGBA')

    blur = float(cfg.get('blur_frac', 0.0)) * BW
    if blur > 0.3:
        tile = tile.filter(ImageFilter.GaussianBlur(blur))
    return (x0, y0), tile
