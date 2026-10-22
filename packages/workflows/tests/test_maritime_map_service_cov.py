# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage for the drawn maritime chart.

Everything runs offline on a tiny synthetic world: lon/lat discs written out as
GeoJSON stand in for Natural Earth, and the plate is drawn at 256x144 instead
of 5376x3072, so the whole engraving pipeline runs for real in milliseconds.
Every path the module derives is redirected to tmp_path.
"""

import json
import math
import os

import numpy as np
import pytest
from PIL import Image, ImageDraw

from zyg_workflows import maritime_map_service as mms

# A plate small enough to draw in milliseconds, in the delivery aspect.
_W, _H = 256, 144

# The builder calls `Chart()` with the module's own 5376x3072 defaults, so the
# small plate is installed by replacing the name; keep the real class to hand.
_REAL_CHART = mms.Chart


# ── synthetic world ─────────────────────────────────────────────────────────
def _disc(clon, clat, rlon, rlat, n=60, cw=True):
    """A closed lon/lat ring: cheap stand-in for a coastline."""
    out = []
    for k in range(n + 1):
        a = 2 * math.pi * k / n * (1 if cw else -1)
        out.append([clon + rlon * math.cos(a), clat + rlat * math.sin(a)])
    return out


def _poly(*rings):
    return {'geometry': {'type': 'Polygon', 'coordinates': list(rings)}}


# A ring that walks across +180 into -180 and back: the antimeridian smear the
# projector has to split, into three runs.
_WRAP_LONS = [150, 165, 178, -176, -165, -158, -170, 179, 168, 150]
_WRAP_RING = [[lon, 14 - k] for k, lon in enumerate(_WRAP_LONS)]


def _write_world(tmp_path):
    """Write the two GeoJSON files the module reads, and return their dir."""
    geo = tmp_path / 'geo'
    geo.mkdir()
    land = [
        # one big landmass with a lake-sized hole (an interior ring)
        _poly(_disc(10, 10, 32, 30), _disc(10, 10, 9, 8, 30, cw=False)),
        # two more, handed over as a MultiPolygon
        {'geometry': {'type': 'MultiPolygon', 'coordinates': [[_disc(-100, 25, 22, 18)], [_disc(120, -20, 15, 12)]]}},
        _poly(_WRAP_RING),
        # geometry kinds the reader must ignore rather than crash on
        {'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [1, 1]]}},
        {'geometry': None},
        {},
    ]
    # a lake with an island in it, and a ring too short to fill
    lakes = [_poly(_disc(14, 2, 5, 4, 24), _disc(14, 2, 2, 1, 12)), _poly([[40, 40], [41, 41]])]
    (geo / 'ne_10m_land.geojson').write_text(json.dumps({'features': land}))
    (geo / 'ne_50m_lakes.geojson').write_text(json.dumps({'features': lakes}))
    return geo


@pytest.fixture(autouse=True)
def _no_cache_bleed():
    """The module memoises the chart and the land mask by revision; a test
    that changes the world must not inherit a neighbour's pixels."""
    mms._CACHE.clear()
    mms._MASK_CACHE.clear()
    yield
    mms._CACHE.clear()
    mms._MASK_CACHE.clear()


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Module pointed at a synthetic world and a throwaway output dir."""
    geo = _write_world(tmp_path)
    maps = tmp_path / 'maps'
    monkeypatch.setattr(mms, '_GEO_DIR', str(geo))
    monkeypatch.setattr(mms, '_MAP_DIR', str(maps))
    monkeypatch.setattr(mms, 'BASE_W', _W)
    monkeypatch.setattr(mms, 'BASE_H', _H)
    monkeypatch.setattr(mms, 'Chart', lambda *a, **kw: _REAL_CHART(width=_W, height=_H))
    return {'geo': geo, 'maps': maps}


def _small_chart(width=_W, height=_H):
    return _REAL_CHART(width=width, height=height)


def _ink_pixels(img):
    return int(np.asarray(img.convert('RGBA'))[..., 3].astype(bool).sum())


# ── projection ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize('lat', [0.0, 1.0, -1.0, 23.4368, -45.0, 70.0])
def test_mercator_is_invertible(lat):
    assert mms._inv_y_merc(mms._y_merc(lat)) == pytest.approx(lat, abs=1e-6)


def test_y_merc_is_clamped_at_the_poles():
    assert mms._y_merc(89.9) == mms._y_merc(85.0)
    assert mms._y_merc(-89.9) == mms._y_merc(-85.0)
    assert mms._y_merc(0.0) == pytest.approx(0.0)


def test_chart_geometry_and_as_dict():
    c = _small_chart()
    assert (c.width, c.height) == (_W, _H)
    assert c.y_span == pytest.approx(360.0 * _H / _W)
    assert c.lat_max > 0

    # the prime meridian / equator land dead centre
    x, y = c.lonlat_to_px(0.0, 0.0)
    assert (x, y) == pytest.approx((_W / 2, _H / 2))
    assert c.lonlat_to_px(-180.0, 0.0)[0] == pytest.approx(0.0)

    nx, ny = c.lonlat_to_norm(0.0, 0.0)
    assert (nx, ny) == pytest.approx((0.5, 0.5))

    d = c.as_dict()
    assert d['rev'] == mms.CHART_REV
    assert d['projection'] == 'mercator'
    assert d['png'] is None
    assert d['lat_max'] == pytest.approx(round(c.lat_max, 4))


@pytest.mark.parametrize('lon,lat', [(0.0, 0.0), (4.9, 52.37), (-17.4, 14.67), (120.0, -33.0)])
def test_px_to_lonlat_round_trips(lon, lat):
    c = _small_chart()
    back = c.px_to_lonlat(*c.lonlat_to_px(lon, lat))
    assert back == pytest.approx((lon, lat), abs=1e-6)


def test_zoom_for_span_shrinks_with_the_band():
    c = _small_chart()
    wide = c.zoom_for_span(40.0, -40.0)
    narrow = c.zoom_for_span(6.0, 4.0)
    assert 0 < wide < narrow
    # a zero-height band must not divide by zero
    assert c.zoom_for_span(5.0, 5.0) > 0


# ── GeoJSON reading and projection of rings ─────────────────────────────────
def test_rings_yields_exteriors_first_and_skips_other_geometry(tmp_path):
    geo = _write_world(tmp_path)
    rings = list(mms._rings(str(geo / 'ne_10m_land.geojson')))
    # 2 (polygon + hole) + 2 (multipolygon) + 1 (wrap) = 5
    assert len(rings) == 5
    assert [is_ext for _, is_ext in rings] == [True, False, True, True, True]
    assert all(len(r) >= 2 for r, _ in rings)


def test_project_ring_splits_at_the_antimeridian():
    c = _small_chart()
    runs = mms._project_ring(_WRAP_RING, c)
    assert len(runs) == 3  # east of 180, west of it, then east again
    # no run may span more than half the plate: that is the smear being avoided
    for run in runs:
        xs = [p[0] for p in run]
        assert max(xs) - min(xs) < c.width * 0.5


def test_project_ring_drops_runs_too_short_to_draw():
    c = _small_chart()
    assert mms._project_ring([[0, 0], [1, 1]], c) == []
    assert len(mms._project_ring([[0, 0], [1, 1], [2, 0], [0, 0]], c)) == 1


# ── parchment ───────────────────────────────────────────────────────────────
def test_value_noise_is_normalised_and_deterministic():
    a = mms._value_noise(32, 18, 4, np.random.RandomState(1672))
    b = mms._value_noise(32, 18, 4, np.random.RandomState(1672))
    assert a.shape == (18, 32)
    assert a.min() >= 0.0 and a.max() <= 1.0
    assert np.array_equal(a, b)


def test_parchment_is_a_warm_sheet_with_darker_edges():
    img = mms._parchment(_W, _H, np.random.RandomState(1672))
    assert img.size == (_W, _H)
    a = np.asarray(img, dtype=np.float32)
    # warm: red above blue everywhere on average
    assert a[..., 0].mean() > a[..., 2].mean()
    # the edge burn makes the rim darker than the middle
    mid = a[_H // 3 : 2 * _H // 3, _W // 3 : 2 * _W // 3].mean()
    assert a[:2, :].mean() < mid


def test_parchment_survives_a_sheet_too_small_to_fox():
    # at this size every age spot rounds to a radius of zero and is dropped
    img = mms._parchment(60, 34, np.random.RandomState(1672))
    assert img.size == (60, 34)
    assert np.asarray(img).dtype == np.uint8


# ── lettering ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize('font', [mms._FONT_SERIF, '/nonexistent/NoSuchFont.ttf'])
def test_label_draws_with_a_real_font_or_the_default(font):
    img = Image.new('RGBA', (160, 48), (0, 0, 0, 0))
    mms._label(ImageDraw.Draw(img), 'ELMINA', (4, 4), size=18, font=font)
    assert _ink_pixels(img) > 0


@pytest.mark.parametrize('font', [mms._FONT_SERIF_B, '/nonexistent/NoSuchFont.ttf'])
def test_tracked_text_spaces_capitals_across_the_centre(font):
    img = Image.new('RGBA', (240, 40), (0, 0, 0, 0))
    mms._tracked_text(ImageDraw.Draw(img), 'AFRICA', 120, 20, 16, font, 6, mms._INK + (200,))
    cols = np.flatnonzero(np.asarray(img)[..., 3].astype(bool).any(axis=0))
    assert len(cols) > 0
    # centred on the requested x
    assert abs((cols[0] + cols[-1]) / 2 - 120) < 12


def test_place_names_letters_every_entry_onto_the_plate():
    base = Image.new('RGB', (_W, _H), mms._PARCHMENT)
    out = mms._place_names(base, _small_chart())
    assert out.size == base.size
    assert not np.array_equal(np.asarray(out.convert('RGB')), np.asarray(base))
    assert set(cls for cls, *_ in mms._PLACE_NAMES) <= set(mms._NAME_STYLE)


# ── chart furniture ─────────────────────────────────────────────────────────
def test_graticule_inks_the_named_parallels():
    c = _small_chart()
    img = Image.new('RGB', (_W, _H), mms._PARCHMENT)
    mms._graticule(ImageDraw.Draw(img), c)
    a = np.asarray(img)
    _, y = c.lonlat_to_px(0, 0.0)
    row = a[int(y), :, :]
    # the equator is drawn heavy in full ink, so most of the row is dark
    assert (row.mean(axis=1) < np.asarray(mms._PARCHMENT).mean()).mean() > 0.5


def test_rhumb_network_draws_from_every_node():
    c = _small_chart()
    base = Image.new('RGB', (_W, _H), mms._PARCHMENT)
    out = mms._rhumb_network(base, c, [(-40, 40), (30, -20)], radius_px=_W * 0.2)
    assert out.mode == 'RGBA'
    changed = np.asarray(out.convert('RGB')) != np.asarray(base)
    assert changed.any()
    # a node is marked with a filled ellipse, so its own pixel is inked
    nx, ny = c.lonlat_to_px(-40, 40)
    assert changed[int(ny), int(nx)].any()


def test_compass_rose_is_drawn_around_its_centre():
    base = Image.new('RGB', (_W, _H), mms._PARCHMENT)
    out = mms._compass_rose(base, _W * 0.5, _H * 0.5, _W * 0.12, np.random.RandomState(3))
    changed = (np.asarray(out.convert('RGB')) != np.asarray(base)).any(axis=2)
    assert changed.any()
    # the fleur-de-lis north puts ink above the centre
    assert changed[: _H // 2, :].any()


def test_cartouche_panels_the_title_block():
    base = Image.new('RGB', (_W, _H), mms._SEA)
    box = (20, 20, 20 + int(_W * 0.5), 20 + int(_H * 0.6))
    out = mms._cartouche(base, box, 'MARE ORBIS', 'Pascaerte', ['one', 'two'])
    changed = (np.asarray(out.convert('RGB')) != np.asarray(base)).any(axis=2)
    assert changed[box[1] : box[3], box[0] : box[2]].mean() > 0.5
    # nothing outside the panel on the far side of the plate
    assert not changed[:, box[2] + 8 :].all()


# ── coastal hatching ────────────────────────────────────────────────────────
def _hatch_canvas():
    img = Image.new('RGB', (80, 40), mms._PARCHMENT)
    return img, ImageDraw.Draw(img)


def test_coastal_hatching_strikes_into_the_sea_from_both_windings():
    # left half land, right half sea; the coast runs down the middle
    mask = np.zeros((40, 80), dtype=bool)
    mask[:, :40] = True
    coast = [(40.0, float(y)) for y in range(4, 36)]
    out = {}
    for name, pts in (('down', coast), ('up', list(reversed(coast)))):
        img, d = _hatch_canvas()
        mms._coastal_hatching(d, [pts], mask, step=4, length=8.0, rng=np.random.RandomState(5))
        a = np.asarray(img)
        dark = a.mean(axis=2) < np.asarray(mms._PARCHMENT).mean() - 5
        out[name] = dark
        assert dark.any(), name
        # strokes land on the water side, never inland
        assert dark[:, :34].sum() == 0, name
    # both ring windings hatch the same side of the coast
    assert out['down'][:, 40:].any() and out['up'][:, 40:].any()


def test_coastal_hatching_skips_what_it_cannot_decide():
    mask = np.zeros((40, 80), dtype=bool)
    mask[:, :40] = True
    img, d = _hatch_canvas()
    mms._coastal_hatching(
        d,
        [
            [(5.0, 5.0), (6.0, 6.0)],  # too few points to be a coast
            [(70.0, 5.0)] * 6,  # zero-length segments
            [(70.0, float(y)) for y in range(4, 36)],  # open water: no edge
        ],
        mask,
        step=4,
        length=8.0,
        rng=None,
    )
    assert np.array_equal(np.asarray(img), np.asarray(Image.new('RGB', (80, 40), mms._PARCHMENT)))


# ── the build ───────────────────────────────────────────────────────────────
def test_chart_png_path_carries_the_revision_and_the_size(world):
    p = mms._chart_png_path()
    assert os.path.dirname(p) == str(world['maps'])
    assert os.path.basename(p) == f'series_chart_{mms.CHART_REV}_{_W}x{_H}.png'


def test_build_chart_draws_the_plate_and_writes_its_metadata(world):
    said = []
    chart = mms.build_chart(log_fn=said.append)

    png = world['maps'] / f'series_chart_{mms.CHART_REV}_{_W}x{_H}.png'
    assert chart.path == str(png)
    assert png.is_file()
    with Image.open(png) as img:
        assert img.size == (_W, _H)
        a = np.asarray(img.convert('RGB'), dtype=np.float32)
    # a real engraving: many distinct tones, warm, and not a flat fill
    assert a.std() > 4.0
    assert a[..., 0].mean() > a[..., 2].mean()

    meta = json.loads((world['maps'] / f'series_chart_{mms.CHART_REV}_{_W}x{_H}.json').read_text())
    assert meta['width'] == _W and meta['height'] == _H
    assert meta['projection'] == 'mercator'
    assert meta['png'] == str(png)
    assert 'Natural Earth' in meta['source']

    joined = '\n'.join(said)
    assert 'Mercator plate' in joined
    assert 'land:' in joined and 'rings' in joined
    assert str(png) in joined


def test_build_chart_is_deterministic_and_reuses_the_cached_png(world, capsys):
    first = mms.build_chart(log_fn=lambda m: None)
    pixels = (world['maps'] / os.path.basename(first.path)).read_bytes()
    mtime = os.path.getmtime(first.path)

    # second call, no force: the PNG on disk is taken as it is (and the default
    # log sink is `print`, so nothing is drawn and nothing is said)
    again = mms.build_chart()
    assert again.path == first.path
    assert os.path.getmtime(again.path) == mtime
    assert capsys.readouterr().out == ''

    # forced: redrawn from the same seed, so the same pixels come back
    mms.build_chart(force=True, log_fn=lambda m: None)
    assert (world['maps'] / os.path.basename(first.path)).read_bytes() == pixels


def test_get_chart_builds_once_then_serves_the_cache(world):
    chart = mms.get_chart(log_fn=lambda m: None)
    assert mms._CACHE[mms.CHART_REV] is chart
    assert mms.get_chart() is chart


# ── route geometry ──────────────────────────────────────────────────────────
def test_catmull_rom_passes_through_every_control_point():
    ctrl = np.array([[0.0, 0.0], [10.0, 20.0], [30.0, 5.0], [50.0, 25.0]])
    dense = mms._catmull_rom(ctrl, samples_per_seg=16)
    assert len(dense) > len(ctrl)
    for p in ctrl:
        assert np.linalg.norm(dense - p, axis=1).min() < 1e-9
    assert np.allclose(dense[0], ctrl[0]) and np.allclose(dense[-1], ctrl[-1])


@pytest.mark.parametrize('n', [1, 2])
def test_catmull_rom_leaves_too_few_points_alone(n):
    ctrl = np.array([[float(i), float(i)] for i in range(n)])
    assert np.array_equal(mms._catmull_rom(ctrl), ctrl)


def test_resample_spaces_samples_evenly_by_distance():
    path = np.array([[0.0, 0.0], [100.0, 0.0], [100.0, 50.0]])
    out = mms._resample(path, step_px=5.0)
    seg = np.linalg.norm(np.diff(out, axis=0), axis=1)
    assert len(out) == pytest.approx(150 / 5.0, abs=1)
    # every step is the same length but the one that straddles the corner
    assert np.ptp(seg) < 1.5
    assert seg.mean() == pytest.approx(5.0, abs=0.3)
    assert np.allclose(out[0], path[0]) and np.allclose(out[-1], path[-1])


def test_resample_returns_a_zero_length_path_untouched():
    path = np.zeros((4, 2))
    assert mms._resample(path) is path


def test_route_path_marks_every_port_and_skips_the_sea_waypoints(world):
    chart = _small_chart()
    path, marks = mms.route_path(mms.WEST_AFRICA_RUN, chart, step_px=2.0)
    assert path.shape[1] == 2 and len(path) > len(mms.WEST_AFRICA_RUN)
    assert [m['key'] for m in marks] == [k for kind, k in mms.WEST_AFRICA_RUN if kind == 'port']
    assert [m['name'] for m in marks] == [mms.PORTS[m['key']]['name'] for m in marks]

    # marks arrive in sailing order, each at the port's own pixel
    assert [m['frac'] for m in marks] == sorted(m['frac'] for m in marks)
    for m in marks:
        assert 0.0 <= m['frac'] <= 1.0
        assert m['xy'] == pytest.approx(chart.lonlat_to_px(*mms.PORTS[m['key']]['lonlat']))
        assert np.linalg.norm(path[m['i']] - np.asarray(m['xy'])) < 6.0

    # every offshore control point the course names exists
    assert all(k in mms._OFFSHORE for kind, k in mms.WEST_AFRICA_RUN if kind == 'sea')


def test_route_path_accepts_a_sea_only_course(world):
    chart = _small_chart()
    legs = [('sea', k) for k in ('dogger', 'shetland', 'hebrides', 'ireland_w')]
    path, marks = mms.route_path(legs, chart)
    assert marks == []
    assert len(path) >= 2


# ── check_route ─────────────────────────────────────────────────────────────
def _land_lonlat(chart, mask, want=True):
    """A lon/lat that lands on (or off) the synthetic landmass."""
    ys, xs = np.nonzero(mask if want else ~mask)
    i = len(xs) // 2
    return chart.px_to_lonlat(float(xs[i]), float(ys[i]))


def test_check_route_reports_a_clear_course_over_open_water(world):
    chart = _small_chart()
    mask = mms._land_mask(chart)
    assert mask.any() and not mask.all()
    # straight down a meridian of open water, pole to pole
    open_cols = np.flatnonzero(~mask.any(axis=0))
    col = float(open_cols[len(open_cols) // 2])
    path = np.stack([np.full(60, col), np.linspace(1.0, _H - 2.0, 60)], axis=1)
    assert not mask[path[:, 1].astype(int), path[:, 0].astype(int)].any()

    said = []
    rep = mms.check_route(path, chart, marks=[], log_fn=said.append)
    assert rep == {'total': 60, 'landfalls': [], 'defects': [], 'clear': True}
    assert '✓ clear' in said[-1]


def test_check_route_names_every_overland_crossing(world, capsys):
    chart = _small_chart()
    mask = mms._land_mask(chart)
    ys, xs = np.nonzero(mask)
    # two separate excursions onto land, with open water in between
    a = np.asarray([(xs[0], ys[0]), (xs[1], ys[1])], dtype=np.float64)
    sea = np.asarray(_land_lonlat(chart, mask, want=False))
    sx, sy = chart.lonlat_to_px(*sea)
    far = np.asarray([(xs[-1], ys[-1]), (xs[-2], ys[-2])], dtype=np.float64)
    path = np.vstack([a, [[sx, sy]] * 3, far])

    rep = mms.check_route(path, chart, log_fn=None)
    out = capsys.readouterr().out  # log_fn=None falls back to print
    assert rep['clear'] is False
    assert len(rep['defects']) == 2
    assert rep['landfalls'] == []
    assert rep['total'] == len(path)
    assert out.count('ROUTE CROSSES LAND') == 2
    assert 'FIX THE WAYPOINTS' in out
    # the report is geo-referenced: the crossing is named in lon/lat
    lon, lat = chart.px_to_lonlat(*path[0])
    assert f'({lon:.1f},{lat:.1f})' in out


def test_check_route_forgives_a_crossing_at_a_port(world):
    chart = _small_chart()
    mask = mms._land_mask(chart)
    ys, xs = np.nonzero(mask)
    path = np.asarray([(xs[0], ys[0]), (xs[1], ys[1]), (xs[2], ys[2])], dtype=np.float64)
    marks = [{'key': 'elmina', 'name': 'ELMINA', 'xy': (float(xs[0]), float(ys[0])), 'i': 0, 'frac': 0.0}]

    said = []
    rep = mms.check_route(path, chart, marks=marks, near_px=40.0, log_fn=said.append)
    assert rep['clear'] is True
    assert len(rep['landfalls']) == 1
    assert rep['defects'] == []
    assert '1 landfalls at ports' in said[-1]

    # the same crossing, with no port anywhere near it, is a defect again
    elsewhere = [dict(marks[0], xy=(float(xs[0]) + 90.0, float(ys[0]) + 60.0))]
    far = mms.check_route(path, chart, marks=elsewhere, near_px=40.0, log_fn=said.append)
    assert far['clear'] is False
    assert far['landfalls'] == []


def test_land_mask_is_memoised_per_plate_size(world):
    chart = _small_chart()
    first = mms._land_mask(chart)
    assert mms._land_mask(_small_chart()) is first
    assert mms._MASK_CACHE[(_W, _H, mms.CHART_REV)] is first
    other = mms._land_mask(_small_chart(_W // 2, _H // 2))
    assert other.shape == (_H // 2, _W // 2)
    assert other is not first


# ── the rope ────────────────────────────────────────────────────────────────
def _rope_path(n=90):
    t = np.linspace(0.0, 1.0, n)
    return np.stack([20.0 + 220.0 * t, 70.0 + 30.0 * np.sin(t * 4.0)], axis=1)


def test_draw_rope_lays_three_shaded_strands_with_a_shadow():
    overlay = Image.new('RGBA', (_W, _H), (0, 0, 0, 0))
    path = _rope_path()
    mms.draw_rope(overlay, path, 0, len(path) - 1, width=7.0)
    a = np.asarray(overlay)
    assert _ink_pixels(overlay) > 0
    # the rope reads as rope: the strand shading spans dark to light core
    core = a[..., :3][a[..., 3] == 255]
    assert len(core) > 0
    assert core[:, 0].min() <= mms._ROPE_DARK[0] + 8
    assert core[:, 0].max() >= mms._ROPE_LIGHT[0] - 8
    # and it sits on a softer shadow below and right of itself
    assert ((a[..., 3] > 0) & (a[..., 3] < 255)).any()


def test_draw_rope_is_progressive():
    path = _rope_path()
    early = Image.new('RGBA', (_W, _H), (0, 0, 0, 0))
    mms.draw_rope(early, path, 0, 30)
    whole = Image.new('RGBA', (_W, _H), (0, 0, 0, 0))
    mms.draw_rope(whole, path, 0, len(path) - 1)
    assert 0 < _ink_pixels(early) < _ink_pixels(whole)


@pytest.mark.parametrize('path_n,i0,i1', [(90, 10, 10), (90, 10, 11), (1, 0, 4)])
def test_draw_rope_draws_nothing_without_a_span(path_n, i0, i1):
    overlay = Image.new('RGBA', (_W, _H), (0, 0, 0, 0))
    mms.draw_rope(overlay, _rope_path(path_n), i0, i1)
    assert _ink_pixels(overlay) == 0


# ── port marks ──────────────────────────────────────────────────────────────
def test_draw_port_mark_rings_the_dot_and_sets_the_name():
    overlay = Image.new('RGBA', (240, 120), (0, 0, 0, 0))
    mms.draw_port_mark(overlay, (60.0, 60.0), 'TEXEL', size=16, label=(20, 0, 'lm'))
    a = np.asarray(overlay)
    assert a[60, 60, 3] == 255  # the inked centre dot
    assert a[..., 3][:, 70:].any()  # the name, beside it
    assert not a[..., 3][:, :40].any()  # no leader: the label is close in


def test_draw_port_mark_ladders_a_crowded_coast_out_on_a_leader():
    overlay = Image.new('RGBA', (320, 200), (0, 0, 0, 0))
    mms.draw_port_mark(overlay, (260.0, 40.0), 'ELMINA', size=16, label=(-180, 90, 'rm'))
    alpha = np.asarray(overlay)[..., 3]
    assert alpha[40, 260] == 255
    # the elbow leader runs out horizontally, then down to the label
    assert alpha[130, 150:250].any()
    assert alpha[40:130, 160:175].any()


@pytest.mark.parametrize('alpha', [0.35, 1.0])
def test_draw_port_mark_fades_with_the_reveal(alpha):
    overlay = Image.new('RGBA', (240, 120), (0, 0, 0, 0))
    mms.draw_port_mark(overlay, (60.0, 60.0), 'GOREE', alpha=alpha, size=16)
    assert np.asarray(overlay)[60, 60, 3] == int(alpha * 255)


@pytest.mark.parametrize('alpha', [0.0, 0.005, -1.0])
def test_draw_port_mark_is_invisible_before_the_rope_arrives(alpha):
    overlay = Image.new('RGBA', (240, 120), (0, 0, 0, 0))
    mms.draw_port_mark(overlay, (60.0, 60.0), 'AXIM', alpha=alpha)
    assert _ink_pixels(overlay) == 0


# ── the authored course ─────────────────────────────────────────────────────
def test_every_port_carries_a_name_and_a_label_offset():
    for port in mms.PORTS.values():
        lon, lat = port['lonlat']
        assert -180.0 <= lon <= 180.0 and -85.0 <= lat <= 85.0
        assert port['name'] == port['name'].upper()
        dx, dy, anchor = port['label']
        assert anchor in {'lm', 'rm', 'mm'}
        assert isinstance(dx, int) and isinstance(dy, int)
    assert mms.WEST_AFRICA_RUN[0] == ('port', 'texel')
    assert mms.WEST_AFRICA_RUN[-1] == ('port', 'loango')
