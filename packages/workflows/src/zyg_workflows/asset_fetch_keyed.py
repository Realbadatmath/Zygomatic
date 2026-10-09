#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""asset_fetch_keyed.py — bring CC0 / CC-BY models from the two keyed sources
into the mesh-pack catalogue, licence per FILE, real size measured on import.

    python3 asset_fetch_keyed.py sketchfab "palm tree" --license cc0 --max 10
    python3 asset_fetch_keyed.py sketchfab "sun lounger" --license by --max 10
    python3 asset_fetch_keyed.py blenderkit "palm tree" --max 10
    python3 asset_fetch_keyed.py --status

Keys (environment, or the .env of the legacy production tree beside ZYG_CREWS_ROOT):
    SKETCHFAB_TOKEN     an API token from sketchfab.com/settings/password (free account)
    BLENDERKIT_API_KEY  from blenderkit.com/profile (free account)

Nothing runs without the key for that source; --status says which are set.

Sketchfab: /v3/search with downloadable=true and licenses=cc0|by, then
/v3/models/<uid>/download gives a short-lived glTF zip URL. The zip is unpacked
under mesh_packs/sketchfab/<license>/<uid>-<slug>/ with a PROVENANCE.json that
quotes the licence label and, for CC-BY, the author to credit. The catalogue
is fail-closed on licence, so a model whose licence is not CC0 / CC-BY is
never written to disk.

BlenderKit: /api/v1/search with asset_type:model license:cc_zero, then the
download endpoint yields a .blend; headless Blender converts it to GLB
(blend_export_collections.py logic, all objects) and measures it.

After a run: python3 mesh_pack_dims.py sketchfab blenderkit   (sizes)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
PACKS_ROOT = os.path.join(HERE, 'data', 'assets', 'mesh_packs')
ENV_FILES = (os.path.join(os.path.dirname(os.path.dirname(HERE)), '.env'), os.path.join(HERE, '.env'))
UA = 'zygomatic-arch-studio/1.0'
LICENCE_LABEL = {'cc0': 'CC0-1.0', 'by': 'CC-BY-4.0'}


def _env(key: str) -> str:
    v = os.environ.get(key, '')
    if v:
        return v
    for p in ENV_FILES:
        try:
            for line in open(p, encoding='utf-8'):
                if line.strip().startswith(key + '='):
                    return line.strip().split('=', 1)[1].strip().strip('"').strip("'")
        except OSError as _exc:
            _zyg_log.debug('key file unreadable, trying the next one: %s', _exc)
    return ''


def _get(url: str, headers: dict | None = None, timeout: int = 60):
    # Download URLs come back from the asset marketplaces' own JSON, so they are untrusted input;
    # a Request is needed for the API headers, hence the scheme check here rather than net.safe_urlopen.
    if urllib.parse.urlsplit(url).scheme not in ('http', 'https'):
        raise ValueError(f'refusing non-http(s) asset URL: {url[:120]!r}')
    req = urllib.request.Request(url, headers={'User-Agent': UA, **(headers or {})})  # noqa: S310  checked above
    with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310  # noqa: S310  req holds the checked URL
        return r.read()


def _slug(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', str(s).lower()).strip('-')[:48] or 'model'


# ── Sketchfab ────────────────────────────────────────────────────────────────
def sketchfab(query: str, licence: str, maxn: int) -> list:
    tok = _env('SKETCHFAB_TOKEN')
    if not tok:
        raise SystemExit('SKETCHFAB_TOKEN is not set (sketchfab.com/settings/password, free)')
    if licence not in LICENCE_LABEL:
        raise SystemExit('--license must be cc0 or by')
    hdr = {'Authorization': f'Token {tok}'}
    url = (
        'https://api.sketchfab.com/v3/search?type=models&downloadable=true&licenses='
        + licence
        + '&q='
        + urllib.parse.quote(query)
        + '&count=24&sort_by=-likeCount'
    )
    got = []
    while url and len(got) < maxn:
        page = json.loads(_get(url, hdr))
        for m in page.get('results') or []:
            if len(got) >= maxn:
                break
            lic = m.get('license') or {}
            label = str(lic.get('label') or lic.get('slug') or '')
            if licence == 'cc0' and 'CC0' not in label.upper():
                continue  # the filter lied: skip, never write
            if licence == 'by' and not re.search(r'\bCC[ -]?BY\b(?![ -]?(NC|ND|SA))', label, re.I):
                continue
            uid = m['uid']
            dl = json.loads(_get(f'https://api.sketchfab.com/v3/models/{uid}/download', hdr))
            g = (dl.get('gltf') or {}).get('url')
            if not g:
                continue
            pack_dir = os.path.join(PACKS_ROOT, 'sketchfab', licence, f'{uid[:8]}-{_slug(m.get("name"))}')
            os.makedirs(pack_dir, exist_ok=True)
            zpath = os.path.join(pack_dir, 'model.zip')
            with open(zpath, 'wb') as fh:
                fh.write(_get(g, timeout=600))
            with zipfile.ZipFile(zpath) as z:
                z.extractall(pack_dir)
            os.remove(zpath)
            author = (m.get('user') or {}).get('displayName') or (m.get('user') or {}).get('username') or ''
            prov = {
                'source_summary': f'Sketchfab model "{m.get("name")}" by {author}',
                'license': LICENCE_LABEL[licence],
                'license_quote': f'Sketchfab licence label: {label}',
                'license_evidence_url': m.get('viewerUrl') or f'https://sketchfab.com/3d-models/{uid}',
                'attribution': f'"{m.get("name")}" by {author}, {label}, via Sketchfab' if licence == 'by' else '',
                'source_url': m.get('viewerUrl'),
                'uid': uid,
                'faces': m.get('faceCount'),
                'curated': time.strftime('%Y-%m-%d'),
                'tool': 'asset_fetch_keyed.py',
                'scale': 'UNVERIFIED — check DIMENSIONS.json after mesh_pack_dims.py; Sketchfab does not state units',
            }
            json.dump(prov, open(os.path.join(pack_dir, 'PROVENANCE.json'), 'w', encoding='utf-8'), indent=1)
            got.append(pack_dir)
            _zyg_log.info(
                ' '.join(
                    str(a)
                    for a in (
                        '  got',
                        os.path.relpath(pack_dir, PACKS_ROOT),
                        '|',
                        label,
                        '|',
                        m.get('faceCount'),
                        'faces',
                    )
                )
            )
        url = page.get('next')
    _vendor_prov(
        'sketchfab', 'Sketchfab downloadable models, licence per model (CC0 or CC-BY), see each PROVENANCE.json'
    )
    return got


# ── BlenderKit ───────────────────────────────────────────────────────────────
def blenderkit(query: str, maxn: int) -> list:
    key = _env('BLENDERKIT_API_KEY')
    if not key:
        raise SystemExit('BLENDERKIT_API_KEY is not set (blenderkit.com/profile, free)')
    hdr = {'Authorization': f'Bearer {key}'}
    q = urllib.parse.quote(f'asset_type:model license:cc_zero is_free:true {query}')
    page = json.loads(_get(f'https://www.blenderkit.com/api/v1/search/?query={q}&page_size={min(maxn, 50)}', hdr))
    got = []
    blender = os.environ.get('BLENDER_BIN', '/usr/local/bin/blender')
    for r in (page.get('results') or [])[:maxn]:
        if r.get('license') != 'cc_zero':
            continue
        files = r.get('files') or []
        src = next((f for f in files if f.get('fileType') == 'blend'), None)
        if not src:
            continue
        aid = r.get('assetBaseId') or r.get('id')
        pack_dir = os.path.join(PACKS_ROOT, 'blenderkit', f'{str(aid)[:8]}-{_slug(r.get("name"))}')
        os.makedirs(pack_dir, exist_ok=True)
        dl = json.loads(
            _get(
                src['downloadUrl']
                + ('&' if '?' in src['downloadUrl'] else '?')
                + 'scene_uuid=00000000-0000-0000-0000-000000000000',
                hdr,
            )
        )
        blend = os.path.join(pack_dir, 'source.blend')
        with open(blend, 'wb') as fh:
            fh.write(_get(dl['filePath'], timeout=900))
        out = os.path.join(pack_dir, _slug(r.get('name')) + '.glb')
        script = os.path.join(HERE, 'blend_export_collections.py')
        subprocess.run(
            [blender, '-b', blend, '--python', script, '--', '--out', pack_dir, '--match', '.', '--min-meshes', '1'],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        prov = {
            'source_summary': f'BlenderKit model "{r.get("name")}" by {(r.get("author") or {}).get("fullName", "")}',
            'license': 'CC0-1.0',
            'license_quote': 'BlenderKit asset licence field: cc_zero',
            'license_evidence_url': f'https://www.blenderkit.com/asset-gallery-detail/{aid}/',
            'curated': time.strftime('%Y-%m-%d'),
            'tool': 'asset_fetch_keyed.py',
            'scale': 'measured from the .blend at export (DIMENSIONS.json)',
        }
        json.dump(prov, open(os.path.join(pack_dir, 'PROVENANCE.json'), 'w', encoding='utf-8'), indent=1)
        got.append(pack_dir)
        _zyg_log.info(
            ' '.join(
                str(a)
                for a in (
                    '  got',
                    os.path.relpath(pack_dir, PACKS_ROOT),
                    '|',
                    'glb' if os.path.exists(out) else 'export failed',
                )
            )
        )
    _vendor_prov('blenderkit', 'BlenderKit models filtered license:cc_zero, see each PROVENANCE.json')
    return got


def _vendor_prov(vendor: str, summary: str):
    p = os.path.join(PACKS_ROOT, vendor, 'PROVENANCE.json')
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(
            {
                'source_summary': summary,
                'license': 'per pack (see each PROVENANCE.json)',
                'curated': time.strftime('%Y-%m-%d'),
                'tool': 'asset_fetch_keyed.py',
            },
            open(p, 'w', encoding='utf-8'),
            indent=1,
        )


if __name__ == '__main__':
    a = sys.argv[1:]
    if not a or '--status' in a:
        print(
            'SKETCHFAB_TOKEN:',
            'set' if _env('SKETCHFAB_TOKEN') else 'MISSING',
            '| BLENDERKIT_API_KEY:',
            'set' if _env('BLENDERKIT_API_KEY') else 'MISSING',
        )
        sys.exit(0)
    src, query = a[0], a[1] if len(a) > 1 else ''
    lic = a[a.index('--license') + 1] if '--license' in a else 'cc0'
    mx = int(a[a.index('--max') + 1]) if '--max' in a else 10
    got = sketchfab(query, lic, mx) if src == 'sketchfab' else blenderkit(query, mx)
    print(f'{len(got)} pack(s) written; now run: python3 mesh_pack_dims.py {src}')
