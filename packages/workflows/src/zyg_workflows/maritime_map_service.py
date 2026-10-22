# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The series' canonical maritime chart — one map, every episode, geo-referenced.

WHY THIS IS DRAWN AND NOT GENERATED
-----------------------------------
The brief was two things at once: a beautiful world map, and *the exact same*
world map pulled continuously throughout the series. A diffusion render can do
the first and structurally cannot do the second — it invents coastlines, garbles
place names, and exists only as whatever PNG happened to come out of the sampler.
It also cannot carry a route: "curving into every port along the African west
coast" needs to know where those ports ARE, in pixels.

So the chart is DRAWN, from public-domain Natural Earth coastlines, in a real
Mercator projection, from a seeded deterministic recipe. That buys three things
the generated route could never have:

  * **Reproducibility** — same `CHART_REV`, same pixels, forever. The cached PNG
    is a convenience, not the asset; the asset is this file.
  * **Geo-reference** — `lonlat_to_px()` is exact, so a camera move can be
    authored to a latitude/longitude and a rope can land on the true Elmina.
  * **Mercator honesty** — a rhumb line is straight on a Mercator chart. That is
    the whole reason Mercator drew it that way in 1569, and it is why the rhumb
    network decorating this chart is geometrically real rather than ornamental.

The look is an engraved 17th-century Dutch sea chart: laid parchment, sepia ink
coastlines with the hatched coastal shading band that is the signature of the
form, a rhumb-line network on compass nodes, a graticule, an ornate rose and a
cartouche.

USAGE
    from zyg_workflows import maritime_map_service as mms
    chart = mms.get_chart()                    # builds once, then cached
    x, y  = chart.lonlat_to_px(4.90, 52.37)    # Amsterdam, in base pixels
    path  = mms.route_path(mms.WEST_AFRICA_RUN, chart)
    mms.draw_rope(overlay, path, reveal=0.4)   # progressive, in base space
"""

import json
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

_CREWS = os.path.dirname(os.path.abspath(__file__))
_GEO_DIR = os.path.join(_CREWS, 'data', 'asset_libraries', 'geo')
_MAP_DIR = os.path.join(_CREWS, 'data', 'asset_libraries', 'maps')
_FONT_SERIF = '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf'
_FONT_SERIF_B = '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf'
_FONT_ITALIC = '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf'

# Bump to force a rebuild. The cached PNG is keyed on it, so an old episode can
# always be re-rendered against the chart it actually shipped with.
CHART_REV = 'v1'

# Base size. 4× the 1344×768 delivery frame, so a push to z=4 is still native
# pixels — the chart is the one plate in the series that is zoomed hard.
BASE_W, BASE_H = 5376, 3072

# ── palette (sepia ink on laid parchment) ───────────────────────────────────
_PARCHMENT = (223, 205, 168)
_SEA = (205, 190, 158)  # sea is the parchment, a shade cooler/deeper
_LAND = (216, 197, 156)
_INK = (74, 52, 32)  # coastline / lettering
_INK_SOFT = (120, 96, 66)  # graticule, hatching
_RHUMB_A = (128, 104, 74)  # the plain rhumbs
_RHUMB_B = (150, 66, 46)  # the eight "wind" rhumbs, in red, as on portolans
_ROPE_DARK = (86, 58, 34)
_ROPE_LIGHT = (168, 132, 82)


# ── projection ──────────────────────────────────────────────────────────────
def _y_merc(lat_deg: float) -> float:
    """Mercator northing in DEGREE units (so it is commensurate with longitude)."""
    lat = max(-85.0, min(85.0, float(lat_deg)))
    return math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def _inv_y_merc(y_deg: float) -> float:
    return math.degrees(2 * math.atan(math.exp(math.radians(y_deg))) - math.pi / 2)


class Chart:
    """A geo-referenced chart plate: pixels plus the projection that made them."""

    def __init__(self, width: int = BASE_W, height: int = BASE_H, lon0: float = -180.0, lon1: float = 180.0):
        self.width, self.height = int(width), int(height)
        self.lon0, self.lon1 = float(lon0), float(lon1)
        # The chart is cut to the DELIVERY aspect on purpose: _zoom_frame crops a
        # window of the base's own aspect and resizes it to the frame, so a base
        # of any other shape would be stretched by every camera move.
        span_lon = self.lon1 - self.lon0
        self.y_span = span_lon * self.height / self.width
        self.y_max = self.y_span / 2.0
        self.lat_max = _inv_y_merc(self.y_max)
        self.path = None

    # -- exact, and the reason this module exists --
    def lonlat_to_px(self, lon: float, lat: float) -> tuple[float, float]:
        x = (float(lon) - self.lon0) / (self.lon1 - self.lon0) * self.width
        y = (self.y_max - _y_merc(lat)) / self.y_span * self.height
        return (x, y)

    def lonlat_to_norm(self, lon: float, lat: float) -> tuple[float, float]:
        """Normalised 0..1 — the form `focus_xy` wants."""
        x, y = self.lonlat_to_px(lon, lat)
        return (x / self.width, y / self.height)

    def px_to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        lon = self.lon0 + (float(x) / self.width) * (self.lon1 - self.lon0)
        lat = _inv_y_merc(self.y_max - (float(y) / self.height) * self.y_span)
        return (lon, lat)

    def zoom_for_span(self, lat_n: float, lat_s: float) -> float:
        """The z that just fits a latitude band — z is a fraction of the WHOLE
        chart, which is what _zoom_frame means by it."""
        dy = abs(_y_merc(lat_n) - _y_merc(lat_s))
        return self.y_span / max(dy, 1e-6)

    def as_dict(self) -> dict:
        return {
            'rev': CHART_REV,
            'width': self.width,
            'height': self.height,
            'lon0': self.lon0,
            'lon1': self.lon1,
            'lat_max': round(self.lat_max, 4),
            'projection': 'mercator',
            'png': self.path,
        }


# ── Natural Earth geometry ──────────────────────────────────────────────────
def _rings(geojson_path: str):
    """Yield every ring as a list of (lon, lat), exterior rings first per feature."""
    with open(geojson_path) as fh:
        gj = json.load(fh)
    for feat in gj.get('features', []):
        geom = feat.get('geometry') or {}
        gtype = geom.get('type')
        polys = (
            [geom['coordinates']]
            if gtype == 'Polygon'
            else geom.get('coordinates', [])
            if gtype == 'MultiPolygon'
            else []
        )
        for poly in polys:
            for i, ring in enumerate(poly):
                yield ring, (i == 0)  # (points, is_exterior)


def _project_ring(ring, chart: Chart):
    """Project a lon/lat ring to pixels, splitting where it wraps the antimeridian.

    A ring that straddles ±180 would otherwise be drawn as a band right across
    the chart — the classic world-map smear. Splitting on a jump greater than a
    half-turn keeps Chukotka and Fiji where they belong.
    """
    runs, cur, prev_lon = [], [], None
    for lon, lat in ring:
        if prev_lon is not None and abs(lon - prev_lon) > 180.0:
            if len(cur) > 2:
                runs.append(cur)
            cur = []
        cur.append(chart.lonlat_to_px(lon, lat))
        prev_lon = lon
    if len(cur) > 2:
        runs.append(cur)
    return runs


# ── parchment ───────────────────────────────────────────────────────────────
def _value_noise(w: int, h: int, cells: int, rng, octaves: int = 4) -> np.ndarray:
    """Deterministic fractal value noise in [0,1] — the parchment's fibre."""
    acc = np.zeros((h, w), dtype=np.float32)
    amp, tot, c = 1.0, 0.0, cells
    for _ in range(octaves):
        g = rng.rand(max(2, int(c * h / w) + 1), max(2, c)).astype(np.float32)
        layer = (
            np.asarray(Image.fromarray((g * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC), dtype=np.float32)
            / 255.0
        )
        acc += layer * amp
        tot += amp
        amp *= 0.5
        c *= 2
    return acc / max(tot, 1e-6)


def _parchment(w: int, h: int, rng) -> Image.Image:
    base = np.zeros((h, w, 3), dtype=np.float32)
    base[..., :] = np.array(_PARCHMENT, dtype=np.float32)

    # Broad tonal drift — no sheet of 350-year-old paper is one colour.
    drift = _value_noise(w, h, 5, rng, octaves=3)
    base *= (0.90 + 0.16 * drift)[..., None]

    # Laid lines: the horizontal wire marks of hand-made paper, very faint.
    yy = np.arange(h, dtype=np.float32)
    laid = 1.0 + 0.010 * np.sin(yy * (2 * math.pi / (h / 260.0)))
    base *= laid[:, None, None]

    # Fibre grain.
    fib = _value_noise(w, h, 120, rng, octaves=2)
    base *= (0.96 + 0.08 * fib)[..., None]

    # Foxing — the rust-brown age spots. Sparse, soft, warmer than the ground.
    spots = np.zeros((h, w), dtype=np.float32)
    for _ in range(rng.randint(90, 130)):
        cx, cy = rng.randint(0, w), rng.randint(0, h)
        r = rng.randint(int(w * 0.004), int(w * 0.022))
        y0, y1 = max(0, cy - r), min(h, cy + r)
        x0, x1 = max(0, cx - r), min(w, cx + r)
        if y1 <= y0 or x1 <= x0:
            continue
        gy, gx = np.mgrid[y0:y1, x0:x1]
        d = np.sqrt(((gx - cx) / r) ** 2 + ((gy - cy) / r) ** 2)
        spots[y0:y1, x0:x1] += np.clip(1.0 - d, 0, 1) ** 2 * rng.uniform(0.25, 0.75)
    spots = np.clip(spots, 0, 1)
    stain = np.array([-26.0, -34.0, -40.0], dtype=np.float32)
    base += spots[..., None] * stain

    # Edge burn — the sheet is darker and browner where it was handled.
    gy, gx = np.mgrid[0:h, 0:w]
    ex = np.minimum(gx / w, 1 - gx / w) / 0.5
    ey = np.minimum(gy / h, 1 - gy / h) / 0.5
    edge = np.clip(1.0 - np.minimum(ex, ey) / 0.34, 0, 1) ** 1.7
    base += edge[..., None] * np.array([-40.0, -46.0, -50.0], dtype=np.float32)

    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))


# ── chart furniture ─────────────────────────────────────────────────────────
def _graticule(d: ImageDraw.ImageDraw, chart: Chart):
    """Meridians and parallels every 15°, with the three named parallels heavier."""
    named = {0.0: 'ÆQVATOR', 23.4368: 'TROPICVS CANCRI', -23.4368: 'TROPICVS CAPRICORNI'}
    for lon in range(-180, 181, 15):
        x, _ = chart.lonlat_to_px(lon, 0)
        d.line([(x, 0), (x, chart.height)], fill=_INK_SOFT + (0,), width=2)
    for lat in range(-60, 61, 15):
        _, y = chart.lonlat_to_px(0, lat)
        d.line([(0, y), (chart.width, y)], fill=_INK_SOFT, width=2)
    for lat, label in named.items():
        _, y = chart.lonlat_to_px(0, lat)
        d.line([(0, y), (chart.width, y)], fill=_INK, width=4)
        _label(d, label, (chart.width * 0.055, y - 34), size=30, fill=_INK, font=_FONT_ITALIC)


def _label(d, text, xy, size=28, fill=_INK, font=_FONT_SERIF, anchor=None):
    from PIL import ImageFont

    try:
        f = ImageFont.truetype(font, size)
    except Exception:
        f = ImageFont.load_default()
    d.text(xy, text, font=f, fill=fill, anchor=anchor)


def _rhumb_network(img: Image.Image, chart: Chart, nodes, radius_px: float):
    """32-point rhumb lines from each compass node.

    On a Mercator plate a constant-bearing course IS a straight line, so these
    are not decoration pretending to be geometry — they are the geometry.
    """
    lay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    for lon, lat in nodes:
        cx, cy = chart.lonlat_to_px(lon, lat)
        for k in range(32):
            a = k * (2 * math.pi / 32)
            # the eight principal winds are drawn in red and run further
            principal = k % 4 == 0
            r = radius_px * (1.55 if principal else 1.0)
            # Kept deliberately faint. A real portolan IS this busy, but the
            # rope has to read as the brightest thing on the plate when it
            # draws — at the first pass's opacity the network competed with it.
            col = (_RHUMB_B + (46,)) if principal else (_RHUMB_A + (30,))
            d.line([(cx, cy), (cx + r * math.cos(a), cy + r * math.sin(a))], fill=col, width=2)
        d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=_INK + (110,))
    return Image.alpha_composite(img.convert('RGBA'), lay)


def _compass_rose(img: Image.Image, cx: float, cy: float, r: float, rng):
    """An ornate 8-point rose with a fleur-de-lis north."""
    lay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    for ring in (1.00, 0.72, 0.30):
        d.ellipse([cx - r * ring, cy - r * ring, cx + r * ring, cy + r * ring], outline=_INK + (170,), width=3)
    # 16 minor points, then 8 major over the top
    for n, (frac, fill_a, fill_b) in ((16, (0.62, _INK_SOFT, _PARCHMENT)), (8, (1.00, _INK, _PARCHMENT))):
        for k in range(n):
            a = k * (2 * math.pi / n) - math.pi / 2
            tip = (cx + r * frac * math.cos(a), cy + r * frac * math.sin(a))
            w = (2 * math.pi / n) * 0.34
            l = (cx + r * 0.20 * math.cos(a - w), cy + r * 0.20 * math.sin(a - w))
            rt = (cx + r * 0.20 * math.cos(a + w), cy + r * 0.20 * math.sin(a + w))
            # each point is split light/dark down its axis, as engraved roses are
            d.polygon([tip, l, (cx, cy)], fill=fill_a + (225,))
            d.polygon([tip, rt, (cx, cy)], fill=fill_b + (205,))
            d.polygon([tip, l, (cx, cy), rt], outline=_INK + (190,), width=2)
    # fleur-de-lis north
    top = (cx, cy - r * 1.20)
    d.polygon([top, (cx - r * 0.11, cy - r * 0.86), (cx + r * 0.11, cy - r * 0.86)], fill=_INK + (235,))
    d.ellipse([cx - r * 0.07, cy - r * 1.29, cx + r * 0.07, cy - r * 1.15], fill=_INK + (235,))
    _label(d, 'S', (cx, cy + r * 1.14), size=int(r * 0.30), fill=_INK + (220,), font=_FONT_SERIF_B, anchor='mm')
    _label(d, 'O', (cx + r * 1.16, cy), size=int(r * 0.30), fill=_INK + (220,), font=_FONT_SERIF_B, anchor='mm')
    _label(d, 'W', (cx - r * 1.16, cy), size=int(r * 0.30), fill=_INK + (220,), font=_FONT_SERIF_B, anchor='mm')
    return Image.alpha_composite(img.convert('RGBA'), lay)


def _cartouche(img: Image.Image, box, title, subtitle, lines):
    """The title panel. Sits in empty ocean — the South Pacific, as it usually did."""
    lay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=26, fill=_PARCHMENT + (196,), outline=_INK + (200,), width=5)
    d.rounded_rectangle((x0 + 16, y0 + 16, x1 - 16, y1 - 16), radius=18, outline=_INK_SOFT + (170,), width=2)
    # corner flourishes
    for sx, sy in ((x0 + 16, y0 + 16), (x1 - 16, y0 + 16), (x0 + 16, y1 - 16), (x1 - 16, y1 - 16)):
        d.ellipse([sx - 9, sy - 9, sx + 9, sy + 9], fill=_INK + (180,))
    cx = (x0 + x1) / 2
    _label(d, title, (cx, y0 + 78), size=64, fill=_INK + (240,), font=_FONT_SERIF_B, anchor='mm')
    d.line([(x0 + 70, y0 + 128), (x1 - 70, y0 + 128)], fill=_INK + (170,), width=3)
    _label(d, subtitle, (cx, y0 + 172), size=34, fill=_INK + (215,), font=_FONT_ITALIC, anchor='mm')
    for i, ln in enumerate(lines):
        _label(d, ln, (cx, y0 + 232 + i * 44), size=28, fill=_INK_SOFT + (215,), font=_FONT_SERIF, anchor='mm')
    return Image.alpha_composite(img.convert('RGBA'), lay)


# Period names, in the Latin a Dutch plate of 1672 would have carried. These do
# most of the work at the zoomed framing: without lettering the West African
# coast is just an inked outline, and lettering is what makes a chart look read
# rather than drawn. Placed in open land/sea away from the Day 1 course.
#   (lon, lat, text, class)   class → size/font/tracking/colour
_PLACE_NAMES = [
    ('continent', -101.0, 47.0, 'AMERICA SEPTENTRIONALIS'),
    ('continent', -58.0, -11.0, 'AMERICA MERIDIONALIS'),
    # East of the Zuiderzee: TEXEL's leader is the first thing the rope
    # draws, and at 15°E this label ran straight under it.
    ('continent', 22.0, 45.5, 'EVROPA'),
    ('continent', 30.0, 3.5, 'AFRICA'),
    ('continent', 90.0, 46.0, 'ASIA'),
    ('continent', 133.0, -25.0, 'NOVA HOLLANDIA'),
    # The Day 1 coast, north to south. All pushed INLAND (east): the course runs
    # down the seaward side and the port marks ladder out into the Gulf, so the
    # only clear ground for a territory name is the interior.
    ('region', 6.0, 28.5, 'BARBARIA'),
    ('region', -4.0, 22.0, 'MAVRITANIA'),
    ('region', -3.0, 15.0, 'NIGRITIA'),
    ('region', -1.0, 10.2, 'GVINEA'),
    ('region', 22.5, -10.0, 'CONGO'),
    ('region', 22.5, -16.0, 'ANGOLA'),
    ('region', 38.0, 7.0, 'ÆTHIOPIA'),
    ('sea', -38.0, 31.0, 'MARE ATLANTICVM'),
    ('sea', -20.0, -24.0, 'OCEANVS ÆTHIOPICVS'),
    ('sea', 17.0, 35.4, 'MARE MEDITERRANEVM'),
    ('sea', -140.0, 6.0, 'MARE PACIFICVM'),
    ('sea', 76.0, -20.0, 'OCEANVS INDICVS'),
    ('sea', -44.0, 62.0, 'MARE GLACIALE'),
    ('sea', -62.0, 26.0, 'MARE DEL NORT'),
]

_NAME_STYLE = {
    # size, font, tracking (px between glyphs), colour, alpha
    'continent': (48, _FONT_SERIF_B, 12, _INK, 170),
    'region': (40, _FONT_SERIF, 10, _INK, 165),
    'sea': (38, _FONT_ITALIC, 8, _INK_SOFT, 185),
}


def _tracked_text(d, text, cx, cy, size, font_path, tracking, fill):
    """Letter-spaced, centred. Engravers spaced their capitals wide across a
    territory; PIL has no tracking, so the glyphs are set one at a time."""
    from PIL import ImageFont

    try:
        f = ImageFont.truetype(font_path, size)
    except Exception:
        f = ImageFont.load_default()
    widths = [d.textlength(ch, font=f) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = cx - total / 2
    for ch, w in zip(text, widths):
        d.text((x, cy), ch, font=f, fill=fill, anchor='lm')
        x += w + tracking


def _place_names(img: Image.Image, chart: Chart):
    lay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    for cls, lon, lat, text in _PLACE_NAMES:
        size, font, track, col, alpha = _NAME_STYLE[cls]
        x, y = chart.lonlat_to_px(lon, lat)
        _tracked_text(d, text, x, y, size, font, track, col + (alpha,))
    # the ink has soaked a little, as every other line on this plate has
    lay = lay.filter(ImageFilter.GaussianBlur(0.7))
    return Image.alpha_composite(img.convert('RGBA'), lay)


def _coastal_hatching(
    d: ImageDraw.ImageDraw, runs, land_mask: np.ndarray, step: int = 22, length: float = 13.0, rng=None
):
    """The engraved shading band: short strokes struck into the SEA side.

    Which side is the sea is decided by SAMPLING the land mask rather than by
    trusting ring winding order — Natural Earth does not guarantee RFC-7946
    orientation, and a wrong guess hatches inland, which reads as a mistake
    rather than as a chart.
    """
    h, w = land_mask.shape
    for pts in runs:
        if len(pts) < 4:
            continue
        for i in range(0, len(pts) - 1, step):
            x0, y0 = pts[i]
            x1, y1 = pts[min(i + 1, len(pts) - 1)]
            dx, dy = x1 - x0, y1 - y0
            n = math.hypot(dx, dy)
            if n < 1e-3:
                continue
            nx, ny = -dy / n, dx / n
            probe = 5.0
            px, py = int(x0 + nx * probe), int(y0 + ny * probe)
            qx, qy = int(x0 - nx * probe), int(y0 - ny * probe)
            p_land = land_mask[min(max(py, 0), h - 1), min(max(px, 0), w - 1)]
            q_land = land_mask[min(max(qy, 0), h - 1), min(max(qx, 0), w - 1)]
            if p_land == q_land:
                continue  # a spit or an inlet — skip it
            if p_land:
                nx, ny = -nx, -ny  # point the stroke at the water
            ln = length * (0.7 + 0.6 * (rng.rand() if rng is not None else 0.5))
            d.line([(x0, y0), (x0 + nx * ln, y0 + ny * ln)], fill=_INK_SOFT, width=2)


# ── the build ───────────────────────────────────────────────────────────────
def _chart_png_path() -> str:
    return os.path.join(_MAP_DIR, f'series_chart_{CHART_REV}_{BASE_W}x{BASE_H}.png')


def build_chart(force: bool = False, log_fn=None) -> Chart:
    """Draw the chart. Deterministic: same CHART_REV → same pixels."""
    log = log_fn or print
    chart = Chart()
    png = _chart_png_path()
    meta = png.replace('.png', '.json')
    if os.path.isfile(png) and not force:
        chart.path = png
        return chart
    os.makedirs(_MAP_DIR, exist_ok=True)
    rng = np.random.RandomState(1672)
    W, H = chart.width, chart.height
    log(f'[chart] drawing {W}×{H} Mercator plate (±{chart.lat_max:.1f}° lat) rev {CHART_REV}')

    img = _parchment(W, H, rng)

    # -- sea tint, so the water reads as water and not as blank paper ---------
    sea = Image.new('RGBA', (W, H), _SEA + (74,))
    img = Image.alpha_composite(img.convert('RGBA'), sea).convert('RGB')

    # -- land ----------------------------------------------------------------
    land_layer = Image.new('L', (W, H), 0)
    dl = ImageDraw.Draw(land_layer)
    all_runs = []
    for ring, is_ext in _rings(os.path.join(_GEO_DIR, 'ne_10m_land.geojson')):
        for pts in _project_ring(ring, chart):
            dl.polygon(pts, fill=255 if is_ext else 0)
            all_runs.append(pts)
    land_mask = np.asarray(land_layer) > 127
    log(f'[chart] land: {len(all_runs)} rings, {100.0 * land_mask.mean():.1f}% of the plate')

    a = np.asarray(img, dtype=np.float32)
    lm = land_mask[..., None].astype(np.float32)
    a = a * (1 - lm) + (a * 0.34 + np.array(_LAND, dtype=np.float32) * 0.66) * lm
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))

    # -- graticule under the ink ---------------------------------------------
    d = ImageDraw.Draw(img)
    _graticule(d, chart)

    # -- lakes ---------------------------------------------------------------
    for ring, is_ext in _rings(os.path.join(_GEO_DIR, 'ne_50m_lakes.geojson')):
        for pts in _project_ring(ring, chart):
            if is_ext and len(pts) > 2:
                d.polygon(pts, fill=_SEA, outline=_INK_SOFT)

    # -- coastal shading band, then the coastline itself ---------------------
    _coastal_hatching(d, all_runs, land_mask, rng=rng)
    for pts in all_runs:
        if len(pts) > 1:
            d.line(pts, fill=_INK, width=3, joint='curve')

    # -- rhumb network on nine compass nodes ---------------------------------
    img = _rhumb_network(
        img,
        chart,
        [
            (-40, 40),
            (-40, 0),
            (-40, -35),
            (-150, 20),
            (-150, -25),
            (30, 30),
            (30, -20),
            (95, 5),
            (150, -30),
        ],
        radius_px=W * 0.20,
    )

    # -- lettering, under the rose and the cartouche -------------------------
    img = _place_names(img, chart)

    # -- the rose, in the Indian Ocean ---------------------------------------
    # NOT the North Atlantic, where it was first placed: that is the Day 1
    # corridor, and the rope would have had to draw straight across it.
    rx, ry = chart.lonlat_to_px(78.0, 8.0)
    img = _compass_rose(img, rx, ry, W * 0.048, rng)

    # -- cartouche well out in the South Pacific -----------------------------
    cx0, cy0 = chart.lonlat_to_px(-166.0, -18.0)
    img = _cartouche(
        img,
        (cx0, cy0, cx0 + W * 0.235, cy0 + H * 0.235),
        'MARE ORBIS',
        'Pascaerte van de geheele Werelt',
        ['Naar de wassende graden', 'van Gerard Mercator', 'Amsterdam · Anno 1672'],
    )

    # -- ageing: the ink sinks into the paper, the paper is not flat ---------
    img = img.convert('RGB').filter(ImageFilter.GaussianBlur(0.6))
    a = np.asarray(img, dtype=np.float32)
    a += rng.normal(0.0, 3.4, a.shape).astype(np.float32)
    # two vertical folds, as the sheet was stored folded
    gx = np.arange(W, dtype=np.float32)
    for fx in (W * 0.333, W * 0.667):
        a *= (1.0 - 0.055 * np.exp(-((gx - fx) ** 2) / (2 * (W * 0.0016) ** 2)))[None, :, None]
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))

    img.save(png)
    chart.path = png
    with open(meta, 'w') as fh:
        json.dump(
            {
                **chart.as_dict(),
                'source': 'Natural Earth 10m land / 50m lakes — public domain',
                'note': 'deterministic: same CHART_REV reproduces these pixels',
            },
            fh,
            indent=1,
        )
    log(f'[chart] wrote {png}')
    return chart


_CACHE: dict = {}


def get_chart(log_fn=None) -> Chart:
    if CHART_REV not in _CACHE:
        _CACHE[CHART_REV] = build_chart(log_fn=log_fn)
    return _CACHE[CHART_REV]


# ── ports ───────────────────────────────────────────────────────────────────
# Real coordinates of the posts a Dutch merchantman actually worked in 1672.
# `sea` waypoints carry no mark — they only bow the course out around a cape so
# the rope stays on water, which is checked against the land mask, not by eye.
# `label` is (dx, dy, anchor) in base pixels from the mark. The four Gold Coast
# forts sit inside 70 px of each other, so their names cannot simply sit beside
# the dots — they ladder down into the Gulf of Guinea on leader lines, which is
# how a chart has always handled a crowded coast.
PORTS = {
    'texel': {'lonlat': (4.80, 53.06), 'name': 'TEXEL', 'label': (76, -34, 'lm')},
    'canaria': {'lonlat': (-15.43, 28.13), 'name': 'CANARIA', 'label': (-76, 34, 'rm')},
    'arguin': {'lonlat': (-16.45, 20.60), 'name': 'ARGVIN', 'label': (86, 8, 'lm')},
    'goree': {'lonlat': (-17.40, 14.67), 'name': 'GOREE', 'label': (-86, 14, 'rm')},
    'axim': {'lonlat': (-2.24, 4.87), 'name': 'AXIM', 'label': (-300, 112, 'rm')},
    'elmina': {'lonlat': (-1.35, 5.08), 'name': 'ELMINA', 'label': (-238, 192, 'rm')},
    'accra': {'lonlat': (-0.19, 5.55), 'name': 'ACCRA', 'label': (-176, 272, 'rm')},
    'offra': {'lonlat': (2.45, 6.37), 'name': 'OFFRA', 'label': (-114, 352, 'rm')},
    'loango': {'lonlat': (11.83, -4.65), 'name': 'LOANGO', 'label': (84, 26, 'lm')},
}

# Offshore control points. They carry no mark — they exist so the course rounds
# a cape instead of sailing over it, and so that between two neighbouring Gold
# Coast forts the rope bows out to sea and curves back IN, which is the shape
# the brief asked for. Every one of them was placed by running `check_route`
# against the same land mask the chart was drawn from, not by eye.
_OFFSHORE = {
    # north-about: in 1672 the Dutch were at war with England and the Channel
    # was shut to their merchantmen, so a ship out of Texel went round the top
    # of Scotland. Historically right, and it also spares the rope a 5-pixel
    # thread through the Strait of Dover.
    'dogger': (4.40, 56.60),
    'shetland': (-1.20, 61.50),
    'hebrides': (-9.00, 58.60),
    'ireland_w': (-13.00, 52.00),
    'biscay_w': (-15.00, 43.00),
    'iberia_w': (-16.20, 34.00),
    'canary_s': (-17.60, 24.60),
    'arguin_w': (-18.30, 21.40),
    'verde_w': (-19.40, 16.40),
    'goree_s': (-18.40, 13.40),
    'bulge_w': (-18.20, 9.60),
    'bulge_s': (-12.00, 4.20),
    'liberia_s': (-6.50, 2.90),
    'axim_w': (-3.40, 3.90),
    'axim_e': (-1.90, 4.10),
    'elmina_e': (-0.85, 4.45),
    'accra_e': (1.00, 4.85),
    'bight': (5.40, 2.90),
    'gabon_w': (8.00, -1.80),
    'loango_w': (10.40, -4.10),
}

# The Day 1 course: out of Texel, north about Scotland, down the Atlantic past
# the Canaries, and into every Dutch post on the African west coast in the order
# a southbound ship would take them.
WEST_AFRICA_RUN = [
    ('port', 'texel'),
    ('sea', 'dogger'),
    ('sea', 'shetland'),
    ('sea', 'hebrides'),
    ('sea', 'ireland_w'),
    ('sea', 'biscay_w'),
    ('sea', 'iberia_w'),
    ('port', 'canaria'),
    ('sea', 'canary_s'),
    ('sea', 'arguin_w'),
    ('port', 'arguin'),
    ('sea', 'verde_w'),
    ('port', 'goree'),
    ('sea', 'goree_s'),
    ('sea', 'bulge_w'),
    ('sea', 'bulge_s'),
    ('sea', 'liberia_s'),
    ('sea', 'axim_w'),
    ('port', 'axim'),
    ('sea', 'axim_e'),
    ('port', 'elmina'),
    ('sea', 'elmina_e'),
    ('port', 'accra'),
    ('sea', 'accra_e'),
    ('port', 'offra'),
    ('sea', 'bight'),
    ('sea', 'gabon_w'),
    ('sea', 'loango_w'),
    ('port', 'loango'),
]


# ── route geometry ──────────────────────────────────────────────────────────
def _catmull_rom(pts: np.ndarray, samples_per_seg: int = 48) -> np.ndarray:
    """Smooth the waypoints into a course. Catmull-Rom passes THROUGH every
    control point, which is the whole requirement: the rope must curve into each
    port, not merely near it."""
    p = np.asarray(pts, dtype=np.float64)
    if len(p) < 3:
        return p
    ext = np.vstack([p[0] + (p[0] - p[1]), p, p[-1] + (p[-1] - p[-2])])
    out = []
    for i in range(len(ext) - 3):
        p0, p1, p2, p3 = ext[i : i + 4]
        t = np.linspace(0, 1, samples_per_seg, endpoint=False)[:, None]
        out.append(
            0.5
            * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t**2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t**3)
        )
    out.append(p[-1][None, :])
    return np.vstack(out)


def _resample(path: np.ndarray, step_px: float = 3.0) -> np.ndarray:
    """Arc-length resample, so `reveal` is a fraction of DISTANCE SAILED rather
    than of control-point index — otherwise the rope races across the long ocean
    legs and crawls through the clustered Gold Coast ports."""
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    if s[-1] <= 0:
        return path
    n = max(2, int(s[-1] / step_px))
    si = np.linspace(0, s[-1], n)
    return np.stack([np.interp(si, s, path[:, 0]), np.interp(si, s, path[:, 1])], axis=1)


def route_path(legs, chart: Chart, step_px: float = 3.0):
    """Waypoints → a dense arc-length-parameterised pixel course.

    Returns (path Nx2, marks) where marks are the port pixels + names with the
    path index at which each is reached, so a caller can pop a port's name onto
    the chart exactly as the rope arrives."""
    ctrl, port_idx = [], []
    for kind, key in legs:
        lonlat = PORTS[key]['lonlat'] if kind == 'port' else _OFFSHORE[key]
        ctrl.append(chart.lonlat_to_px(*lonlat))
        if kind == 'port':
            port_idx.append((len(ctrl) - 1, key))
    ctrl = np.asarray(ctrl, dtype=np.float64)
    dense = _catmull_rom(ctrl)
    path = _resample(dense, step_px)
    marks = []
    for ci, key in port_idx:
        px = ctrl[ci]
        i = int(np.argmin(np.linalg.norm(path - px[None, :], axis=1)))
        marks.append(
            {
                'key': key,
                'name': PORTS[key]['name'],
                'xy': (float(px[0]), float(px[1])),
                'i': i,
                'frac': i / max(1, len(path) - 1),
            }
        )
    return path, marks


def check_route(path: np.ndarray, chart: Chart, marks=None, near_px: float = 26.0, log_fn=None) -> dict:
    """Does the course sail over land? Answered against the same mask the chart
    was drawn from, so this is a measurement and not an opinion.

    A crossing within `near_px` of a port mark is a LANDFALL, not a defect — a
    port is on the coast, and the rope is supposed to touch it. Without that
    distinction every correct route reports nine failures and the check becomes
    something you learn to ignore.
    """
    log = log_fn or print
    mask = _land_mask(chart)
    h, w = mask.shape
    xi = np.clip(path[:, 0].astype(int), 0, w - 1)
    yi = np.clip(path[:, 1].astype(int), 0, h - 1)
    hits = mask[yi, xi]
    runs = []
    if hits.any():
        idx = np.flatnonzero(hits)
        start = idx[0]
        for a, b in zip(idx, idx[1:]):
            if b != a + 1:
                runs.append((int(start), int(a)))
                start = b
        runs.append((int(start), int(idx[-1])))

    port_px = np.asarray([m['xy'] for m in (marks or [])], dtype=np.float64)
    landfalls, defects = [], []
    for a, b in runs:
        seg = path[a : b + 1]
        near = False
        if len(port_px):
            dmin = np.linalg.norm(seg[:, None, :] - port_px[None, :, :], axis=2).min()
            near = bool(dmin <= near_px)
        (landfalls if near else defects).append((a, b))

    for a, b in defects:
        lon0, lat0 = chart.px_to_lonlat(*path[a])
        lon1, lat1 = chart.px_to_lonlat(*path[b])
        log(
            f'[chart] ROUTE CROSSES LAND: idx {a}-{b} '
            f'({lon0:.1f},{lat0:.1f}) → ({lon1:.1f},{lat1:.1f}) '
            f'— {b - a + 1} samples'
        )
    log(
        f'[chart] route: {len(path)} samples, {len(landfalls)} landfalls at ports, '
        f'{len(defects)} overland crossing(s)' + ('  ✓ clear' if not defects else '  ✗ FIX THE WAYPOINTS')
    )
    return {'total': len(path), 'landfalls': landfalls, 'defects': defects, 'clear': not defects}


_MASK_CACHE: dict = {}


def _land_mask(chart: Chart) -> np.ndarray:
    """Rebuild the land mask (cheap relative to the full plate, and it keeps
    `check_route` honest even when the PNG came from cache)."""
    key = (chart.width, chart.height, CHART_REV)
    if key in _MASK_CACHE:
        return _MASK_CACHE[key]
    lay = Image.new('L', (chart.width, chart.height), 0)
    d = ImageDraw.Draw(lay)
    for ring, is_ext in _rings(os.path.join(_GEO_DIR, 'ne_10m_land.geojson')):
        for pts in _project_ring(ring, chart):
            d.polygon(pts, fill=255 if is_ext else 0)
    m = np.asarray(lay) > 127
    _MASK_CACHE[key] = m
    return m


# ── the rope ────────────────────────────────────────────────────────────────
def draw_rope(
    overlay: Image.Image, path: np.ndarray, i0: int, i1: int, width: float = 7.0, lay_px: float = 15.0, seed: int = 7
):
    """Draw the course as LAID ROPE between two path indices.

    Not a line with a texture: three strands, each a sine offset a third of a
    turn out of phase with its neighbours, so the twist actually crosses over
    itself the way a rope's lay does. Drawn incrementally — the caller passes
    only the newly-revealed span each frame, so the whole animation costs one
    pass over the path in total rather than one per frame.
    """
    if i1 <= i0 + 1:
        return
    d = ImageDraw.Draw(overlay)
    seg = path[max(0, i0 - 1) : i1 + 1]
    if len(seg) < 2:
        return
    tang = np.gradient(seg, axis=0)
    nrm = np.stack([-tang[:, 1], tang[:, 0]], axis=1)
    ln = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = nrm / np.maximum(ln, 1e-6)
    s = np.arange(max(0, i0 - 1), max(0, i0 - 1) + len(seg), dtype=np.float64)

    # a soft dark under-shadow so the rope sits ON the chart rather than in it
    shadow = [(float(x + 2.0), float(y + 2.6)) for x, y in seg]
    d.line(shadow, fill=(60, 44, 28, 60), width=int(width * 1.7), joint='curve')

    for k in range(3):
        phase = k * (2 * math.pi / 3)
        off = np.sin(s * (2 * math.pi / lay_px) + phase)[:, None] * (width * 0.30)
        pts = seg + nrm * off
        # a strand facing away from the light is darker — that shading is what
        # makes it read as rope rather than as three parallel wires
        depth = np.cos(s * (2 * math.pi / lay_px) + phase)
        for j in range(len(pts) - 1):
            t = (depth[j] + 1.0) / 2.0
            col = tuple(int(_ROPE_DARK[c] + (_ROPE_LIGHT[c] - _ROPE_DARK[c]) * t) for c in range(3))
            d.line([tuple(pts[j]), tuple(pts[j + 1])], fill=col + (255,), width=max(1, int(round(width * 0.42))))


def draw_port_mark(overlay: Image.Image, xy, name: str, alpha: float = 1.0, size: int = 34, label=(80, 0, 'lm')):
    """A port as the rope reaches it: an inked ring, a leader, and the name.

    The leader is what makes a crowded coast legible — four Dutch forts inside
    70 px cannot each have a name beside them, so the names ladder out into open
    water and a hairline says which dot each belongs to.
    """
    if alpha <= 0.01:
        return
    a = int(max(0.0, min(1.0, alpha)) * 255)
    d = ImageDraw.Draw(overlay)
    x, y = float(xy[0]), float(xy[1])
    dx, dy, anchor = label
    r = 10.0
    if abs(dx) > 40 or abs(dy) > 40:
        # elbow leader: out horizontally, then to the label — a straight diagonal
        # reads as another route line, which is the one thing it must not do
        ex = x + dx * 0.55
        d.line([(x, y), (ex, y + dy), (x + dx * 0.93, y + dy)], fill=_INK + (int(a * 0.75),), width=3)
    d.ellipse([x - r, y - r, x + r, y + r], outline=_INK + (a,), width=5)
    d.ellipse([x - r * 0.30, y - r * 0.30, x + r * 0.30, y + r * 0.30], fill=_INK + (a,))
    _label(d, name, (x + dx, y + dy), size=size, fill=_INK + (a,), font=_FONT_SERIF_B, anchor=anchor)


if __name__ == '__main__':  # the CLI lives in maritime_map_service_cli
    from zyg_workflows.maritime_map_service_cli import main as _cli_main

    raise SystemExit(_cli_main())
