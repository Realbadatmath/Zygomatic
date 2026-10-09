# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""light_sun — the one thing the browser cannot do for the sun: turn a PLACE
NAME into a coordinate.

`geocode` asks OpenStreetMap's Nominatim. The data is (c) OpenStreetMap
contributors and licensed ODbL 1.0 (opendatacommons.org/licenses/odbl/) — the
icon says so in its toast, and so does this answer. Nominatim's usage policy
asks for an identifying User-Agent and at most one request a second, so the
request carries one and the answers are cached in-process for the life of the
server: a place looked up twice costs one call.

stdlib only (urllib), no key, no package.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request

from zyg_workflows.contact import contact_email

URL = 'https://nominatim.openstreetmap.org/search'
UA = f'ZygomaticArchStudio/1.0 ({contact_email()})'
ATTRIBUTION = 'Data \u00a9 OpenStreetMap contributors, ODbL 1.0'

_CACHE: dict = {}
_LOCK = threading.Lock()


def geocode(payload, method):
    place = str((payload or {}).get('place') or '').strip()
    if not place:
        return {'ok': False, 'error': 'no place given', 'attribution': ATTRIBUTION}
    key = place.lower()
    with _LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        return dict(hit, cached=True)

    # URL is the literal https:// constant above and `place` is urlencoded into the query, so the
    # scheme is fixed at https; no caller input can reach the scheme of this open.
    url = URL + '?' + urllib.parse.urlencode({'format': 'json', 'q': place, 'limit': 1})
    req = urllib.request.Request(  # noqa: S310  literal https:// constant, scheme cannot vary
        url, headers={'User-Agent': UA, 'Accept': 'application/json'}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:  # nosec B310  # noqa: S310  req holds that literal URL
            rows = json.loads(r.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as e:  # noqa: PERF203
        return {'ok': False, 'error': 'Nominatim HTTP %s' % e.code, 'attribution': ATTRIBUTION}
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'error': 'Nominatim unreachable: %s' % e, 'attribution': ATTRIBUTION}
    if not rows:
        return {'ok': False, 'error': 'no place called %r' % place, 'attribution': ATTRIBUTION}

    row = rows[0]
    try:
        lat, lon = float(row['lat']), float(row['lon'])
    except (KeyError, TypeError, ValueError):
        return {'ok': False, 'error': 'Nominatim answered without a coordinate', 'attribution': ATTRIBUTION}
    out = {
        'ok': True,
        'lat': lat,
        'lon': lon,
        'name': str(row.get('display_name') or place)[:200],
        'kind': str(row.get('type') or ''),
        'licence': str(row.get('licence') or ''),
        'attribution': ATTRIBUTION,
    }
    with _LOCK:
        _CACHE[key] = out
    return dict(out)


ROUTES = {'geocode': geocode}
