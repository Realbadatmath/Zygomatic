# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""arch_pack_ingest.kenney — Kenney: the content-hashed zip URLs resolved from the asset
pages, and the fetch that checks each page says CC0.

Moved verbatim out of arch_pack_ingest.py (lines 726-857) when that 2,019-line
module became this package; no logic was changed.
"""

from __future__ import annotations

import concurrent.futures as cf
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from .common import WORKERS, UA, _checked_url, _download
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_pack_ingest')


# ── Kenney ──────────────────────────────────────────────────────────────────
#
# Kenney publishes ~50 CC0 3D kits and the first haul took nine of them. The
# zip URL is CONTENT-HASHED and changes on every republish, so it is resolved
# from the asset page each run rather than stored — a hardcoded URL here would
# 404 silently the next time Kenney touches a pack.

KENNEY_INDEX = 'https://kenney.nl/assets/category:3D?sort=update'
KENNEY_PAGE = 'https://kenney.nl/assets/{slug}'
_K_ZIP = re.compile(r'https://kenney\.nl/media/pages/assets/[^"\']*?\.zip')
_K_CC0 = re.compile(r'CC0', re.I)


def _get_text(url: str, tries: int = 3) -> str:
    url = _checked_url(url)
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)  # noqa: S310  _checked_url rejects other schemes
            with urllib.request.urlopen(req, timeout=60) as r:  # nosec B310  # noqa: S310  req holds the checked URL
                return r.read().decode('utf8', 'replace')
        except Exception:
            if n == tries - 1:
                raise
            time.sleep(1.5 * (n + 1))
    return ''


def kenney_slugs() -> list[str]:
    """Every 3D pack slug, walked across the paginated index."""
    seen, pages = [], [KENNEY_INDEX]
    html = _get_text(KENNEY_INDEX)
    pages += sorted(set(re.findall(r'https://kenney\.nl/assets/category:3D/page:\d+\?sort=update', html)))
    blobs = [html] + [_get_text(u) for u in pages[1:]]
    for b in blobs:
        for m in re.findall(r'https://kenney\.nl/assets/([a-z0-9-]+)', b):
            if m not in ('category', 'series', 'tag') and m not in seen:
                seen.append(m)
    return sorted(seen)


def kenney_plan(slugs: list[str]) -> list[dict]:
    """Resolve each pack's live zip URL, size and licence line."""

    def one(slug):
        try:
            page = _get_text(KENNEY_PAGE.format(slug=slug))
        except Exception:
            return {'id': slug, 'error': 'page'}
        z = _K_ZIP.search(page)
        if not z:
            return {'id': slug, 'error': 'no zip'}
        url = z.group(0)
        size = 0
        try:
            req = urllib.request.Request(  # noqa: S310  _checked_url rejects other schemes
                _checked_url(url), headers=UA, method='HEAD'
            )
            with urllib.request.urlopen(req, timeout=60) as r:  # nosec B310  # noqa: S310  req holds the checked URL
                size = int(r.headers.get('Content-Length') or 0)
        except Exception as _exc:
            _zyg_log.warning('zip size probe failed for %s, reporting 0: %s', slug, _exc)
        return {'id': slug, 'url': url, 'size': size, 'cc0': bool(_K_CC0.search(page)), 'file': os.path.basename(url)}

    out = []
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        out = list(ex.map(one, slugs))
    return out


def kenney_fetch(plan: list[dict], root: str) -> dict:
    """Download + extract. A pack whose page does not SAY CC0 is not taken.

    Extraction matters: the catalogue reads .gltf/.glb off disk and the licence
    file the vendor shipped INSIDE the zip is the evidence it quotes, so the
    zip alone is invisible to it. The zip is kept beside the tree as the master
    the registry hashed."""
    import zipfile

    os.makedirs(root, exist_ok=True)
    registry, failed, refused = {}, [], []

    def one(a):
        if a.get('error') or not a.get('url'):
            return a, None
        if not a.get('cc0'):
            return a, 'refused'
        zpath = os.path.join(root, a['file'])
        ok, sha = _download(a['url'], zpath, None)
        if not ok:
            return a, None
        dest = os.path.join(root, a['id'])
        try:
            with zipfile.ZipFile(zpath) as zf:
                for m in zf.namelist():
                    # A zip entry naming .. or an absolute path would write
                    # outside the pack; refuse rather than sanitise silently.
                    if m.startswith('/') or '..' in m.split('/'):
                        raise ValueError(f'unsafe member {m!r}')
                zf.extractall(dest)
        except Exception as e:  # noqa: BLE001
            _zyg_log.warning(f'  UNZIP {a["id"]}: {type(e).__name__}: {e}')
            return a, None
        return a, (sha, dest)

    with cf.ThreadPoolExecutor(max(4, WORKERS // 2)) as ex:
        for n, (a, res) in enumerate(ex.map(one, plan), 1):
            if res == 'refused':
                refused.append(a['id'])
                continue
            if not res:
                failed.append(a['id'])
                continue
            sha, dest = res
            meshes = sum(1 for dp, _, fns in os.walk(dest) for f in fns if f.lower().endswith(('.glb', '.gltf')))
            registry[a['id']] = {
                'id': a['id'],
                'name': a['id'].replace('-', ' ').title(),
                'zip': a['file'],
                'sha256': sha,
                'bytes': os.path.getsize(os.path.join(root, a['file'])),
                'meshes': meshes,
                'licence': 'CC0-1.0',
                'source_url': KENNEY_PAGE.format(slug=a['id']),
                'ingested': time.strftime('%Y-%m-%dT%H:%M:%S'),
            }
            if n % 10 == 0:
                _zyg_log.info(f'    {n}/{len(plan)}…')
    if refused:
        _zyg_log.warning(f'  REFUSED (page does not say CC0) {len(refused)}: {", ".join(refused)}')
    if failed:
        _zyg_log.warning(f'  FAILED {len(failed)}: {", ".join(failed[:10])}')
    return registry
