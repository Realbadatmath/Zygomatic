# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""site_context — the server half of the Site context family (2026-09-07).

ROUTES:
  tile   {z, x, y, source}  -> (png bytes, 'image/png')   one slippy map tile
  where  {lat, lon, zoom}   -> {z, x, y, mpp, tile_m}     the slippy arithmetic

WHY A SERVER ROUTE AT ALL. The tab could fetch a tile straight from the tile
server, but then every pan and every reload is another hit on somebody else's
free service from a browser that identifies itself as Chrome. Going through
here gives us the two things the tile policies actually ask for: a real
User-Agent that names this application and a contact address, and an on-disk
cache so the same tile is fetched once and then served from
data/architecture/tiles/<source>/<z>/<x>_<y>.png for ever.

TILE POLICY AND ATTRIBUTION — read before changing anything here.
  · osm  = https://tile.openstreetmap.org/{z}/{x}/{y}.png. The OpenStreetMap
    Foundation's Tile Usage Policy requires: a valid identifying User-Agent
    (below), NO bulk downloading, and caching. Data is ODbL: the attribution
    "(c) OpenStreetMap contributors" MUST be displayed wherever the tiles are
    shown — arch_ext/site_context.js puts it in a corner div that is visible
    for exactly as long as the underlay is on.
  · esri = https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/
    MapServer/tile/{z}/{y}/{x} (note: y BEFORE x). Esri's World Imagery basemap
    may be displayed with the attribution "(c) Esri, Maxar, Earthstar
    Geographics", which the same div shows when the source is esri.
A 3x3 mosaic at one zoom is nine tiles per site: that is the "low volume" the
policy means, and after the first look it is nine files on this disk.

Standard library only (urllib) — no new package, no licence to declare.
"""

from __future__ import annotations

import math
import os
import urllib.error
import urllib.request

from zyg_workflows.contact import contact_email
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(HERE, 'data', 'architecture', 'tiles')

# the identity the OSM tile policy asks for: application name, version, contact
USER_AGENT = f'ZygomaticArchStudio/1.0 ({contact_email()})'

SOURCES = {
    'osm': ('https://tile.openstreetmap.org/{z}/{x}/{y}.png', '(c) OpenStreetMap contributors'),
    'esri': (
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        '(c) Esri, Maxar, Earthstar Geographics',
    ),
}
MAX_ZOOM = 19


def _mime(data: bytes) -> str:
    """Esri's World Imagery answers JPEG behind a .../tile/ URL with no suffix."""
    return 'image/jpeg' if data[:2] == b'\xff\xd8' else 'image/png'


def _int(v, lo, hi, default=0):
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def slippy(lat: float, lon: float, zoom: int):
    """(x, y) of the tile holding lat/lon, and the fractional position in it."""
    z = _int(zoom, 0, MAX_ZOOM, 18)
    n = 2**z
    lat = max(-85.05112878, min(85.05112878, float(lat)))
    lon = ((float(lon) + 180.0) % 360.0) - 180.0
    fx = (lon + 180.0) / 360.0 * n
    fy = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return int(math.floor(fx)), int(math.floor(fy)), fx, fy, z


def metres_per_pixel(lat: float, zoom: int) -> float:
    """Web Mercator ground resolution at the equator scaled by cos(lat)."""
    return 156543.03392804097 * math.cos(math.radians(float(lat))) / (2 ** _int(zoom, 0, MAX_ZOOM, 18))


def where(payload, method):
    """The tile arithmetic, so the tab and the tests share ONE implementation."""
    lat = float(payload.get('lat') or 0.0)
    lon = float(payload.get('lon') or 0.0)
    z = _int(payload.get('zoom'), 0, MAX_ZOOM, 18)
    x, y, fx, fy, z = slippy(lat, lon, z)
    mpp = metres_per_pixel(lat, z)
    return {
        'ok': True,
        'z': z,
        'x': x,
        'y': y,
        'fx': round(fx, 6),
        'fy': round(fy, 6),
        'mpp': mpp,
        'tile_m': mpp * 256.0,
        'attribution': SOURCES.get(str(payload.get('source') or 'osm'), SOURCES['osm'])[1],
    }


def tile(payload, method):
    """One map tile as PNG bytes. Cached on disk; fetched at most once."""
    src = str(payload.get('source') or 'osm').strip().lower()
    if src not in SOURCES:
        return {'error': 'unknown tile source %r (osm, esri)' % src[:20], 'code': 404}
    z = _int(payload.get('z'), 0, MAX_ZOOM, 18)
    n = 2**z
    x = _int(payload.get('x'), 0, n - 1)
    y = _int(payload.get('y'), 0, n - 1)

    path = os.path.join(CACHE, src, str(z), '%d_%d.png' % (x, y))
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        with open(path, 'rb') as fh:
            data = fh.read()
        return (data, _mime(data))

    # `src` is checked against SOURCES above and z/x/y are clamped ints, so the URL is one of the
    # two literal https:// templates in SOURCES: no payload field can reach the scheme.
    url = SOURCES[src][0].format(z=z, x=x, y=y)
    req = urllib.request.Request(  # noqa: S310  literal https:// template from SOURCES
        url, headers={'User-Agent': USER_AGENT, 'Accept': 'image/png,image/*'}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310  req holds that literal URL
            data = r.read()
    except (urllib.error.URLError, OSError, ValueError) as e:  # noqa: BLE001
        return {'error': 'tile fetch failed: %s' % str(e)[:160], 'code': 502}
    if not data or not (data.startswith(b'\x89PNG') or data.startswith(b'\xff\xd8')):
        return {'error': 'tile server did not return an image', 'code': 502}
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.part'
        with open(tmp, 'wb') as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError as _exc:
        _zyg_log.warning('tile cache write failed, the tile is served but not cached: %s', _exc)
    return (data, _mime(data))


ROUTES = {'tile': tile, 'where': where}
