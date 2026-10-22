# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_pack_ingest.py — pull the CC0 architecture asset packs into mesh_packs.

Built 2026-09-01 for the Architecture Studio. The audio side of the house has
pack_ingest.py; this is the same discipline for GEOMETRY and SURFACES:

    masters land under data/assets/mesh_packs/<vendor>/<pack>/
    every file is hashed, every pack carries a PROVENANCE.json with the
    licence QUOTE and the URL it was read from, and nothing is installed
    that cannot show CC0 at FILE level.

Two sources are scripted here because both publish a real API:

    polyhaven_arch   glTF @ 2k for the architecture-relevant categories.
                     glTF and not .blend on purpose — ONE download serves
                     both consumers: Blender imports it for the asset
                     library, and the Architecture Studio's three.js
                     viewport loads the same bytes.
    ambientcg        PBR materials @ 2k, the surfaces the studio's
                     Materials section is currently faking with flat colour.

Kenney and Quaternius are NOT here: Kenney ships one zip per pack behind a
content-hashed URL that changes on every republish (resolve it from the asset
page, which `--kenney-urls` does), and Quaternius delivers through a Google
Drive folder that rate-limits scripted pulls after ~40 files. Both are
recorded in PROVENANCE by hand.

    python3 arch_pack_ingest.py --plan                 # sizes only, no writes
    python3 arch_pack_ingest.py --fetch polyhaven
    python3 arch_pack_ingest.py --fetch ambientcg --limit 300
    python3 arch_pack_ingest.py --report
"""

# This module inherits the original module's top import block; the names its
# siblings use are imported here and re-exported from here. The four nothing
# reads through this module — argparse, concurrent.futures, re, sys; every
# sibling that needs them imports its own — went with the F401 suppression.

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import logging as _zyg_logging

from zyg_workflows import paths

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_pack_ingest')


HERE = str(paths.PKG_DIR)
PACKS = str(paths.DATA_DIR / 'assets' / 'mesh_packs')

PH_API = 'https://api.polyhaven.com'
ACG_API = 'https://ambientcg.com/api/v2/full_json'

# Categories that can appear in an architectural scene. Deliberately excludes
# the site's "collection: <scene>" tags, which are whole environments rather
# than placeable objects.
PH_CATEGORIES = {
    'furniture',
    'seating',
    'table',
    'shelves',
    'lighting',
    'decorative',
    'office',
    'appliances',
    'wall decoration',
    'vases',
    'bed',
    'books',
    'dishes',
    'potted plants',
    'structures',
    'buildings',
    'containers',
    'plants',
    'trees',
    'flowers',
    'grass',
    'ground cover',
    'electronics',
    'food',
}

# Network-bound, so the worker count is about sockets rather than cores; the
# 20-core ceiling this box runs under is inherited and not re-applied here.
WORKERS = 12
UA = {'User-Agent': 'zygomatic-arch-ingest/1.0'}


# ── plumbing ────────────────────────────────────────────────────────────────


def _checked_url(url: str) -> str:
    """Return *url* unchanged once its scheme is http or https.

    Pack URLs arrive from remote registries and from scraped HTML, so they are untrusted input:
    ``urlopen`` would follow a ``file://`` or custom scheme straight out of it. Every Request in
    this module is built from a URL that has been through here, which is what S310 asks for.
    """
    if urllib.parse.urlsplit(url).scheme not in ('http', 'https'):
        raise ValueError(f'refusing non-http(s) pack URL: {url[:120]!r}')
    return url


def _get_json(url: str, tries: int = 3):
    url = _checked_url(url)
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)  # noqa: S310  _checked_url rejects other schemes
            with urllib.request.urlopen(req, timeout=60) as r:  # nosec B310  # noqa: S310  req holds the checked URL
                return json.loads(r.read().decode('utf8'))
        except Exception:
            if n == tries - 1:
                raise
            time.sleep(1.5 * (n + 1))


def _download(url: str, dest: str, md5: str | None = None, tries: int = 3) -> tuple[bool, str]:
    """Returns (ok, sha256). A file already on disk with the right md5 is kept."""
    if os.path.isfile(dest) and md5 and _md5(dest) == md5:
        return True, _sha256(dest)
    url = _checked_url(url)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + '.part'
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)  # noqa: S310  _checked_url rejects other schemes
            with urllib.request.urlopen(req, timeout=300) as r, open(tmp, 'wb') as f:  # nosec B310  # noqa: S310  checked URL
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
            if md5 and _md5(tmp) != md5:
                raise ValueError('md5 mismatch')
            os.replace(tmp, dest)
            return True, _sha256(dest)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            if n == tries - 1:
                return False, ''
            time.sleep(2 * (n + 1))
    return False, ''


def _digest(path: str, algo):
    h = algo()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _md5(p):
    return _digest(p, hashlib.md5)


def _sha256(p):
    return _digest(p, hashlib.sha256)
