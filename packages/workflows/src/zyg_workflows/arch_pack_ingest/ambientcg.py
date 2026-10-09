# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""arch_pack_ingest.ambientcg — ambientCG: the PBR material catalogue and the web-servable
1K sets the Materials rail reads.

Moved verbatim out of arch_pack_ingest.py (lines 406-725) when that 2,019-line
module became this package; no logic was changed.
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from .common import ACG_API, WORKERS, _get_json, _download
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_pack_ingest')


# ── ambientCG ───────────────────────────────────────────────────────────────

# The surfaces a building is actually made of. ambientCG's own category names.
ACG_CATEGORIES = [
    'Bricks',
    'Concrete',
    'Wood',
    'Tiles',
    'Plaster',
    'Metal',
    'Marble',
    'Roofing',
    'Asphalt',
    'Paving Stones',
    'Rock',
    'Ground',
    'Grass',
    'Fabric',
    'Carpet',
    'Terrazzo',
    'Onyx',
    'Porcelain',
    'Facade',
    'Wall',
]


def _acg_downloads(asset: dict) -> list[dict]:
    """Every download entry for one asset, whatever shape the API used.

    ambientCG's `downloadFolders` / `downloadFiletypeCategories` come back as
    a DICT keyed by name for some assets and as a LIST for others — the same
    endpoint, the same include list. Indexing one shape blindly is how the
    gapfill died on Plaster after the first 300 had worked. Walk both."""

    def vals(node):
        if isinstance(node, dict):
            return list(node.values())
        if isinstance(node, list):
            return node
        return []

    out = []
    for folder in vals(asset.get('downloadFolders')):
        for ftc in vals((folder or {}).get('downloadFiletypeCategories')):
            downloads = (ftc or {}).get('downloads')
            if isinstance(downloads, list):
                out.extend(d for d in downloads if isinstance(d, dict))
    return out


def acg_plan(limit: int, res: str = '2K', skip: set | None = None) -> list[dict]:
    """Pick materials ROUND-ROBIN across the categories, not category by category.

    Filling in order is what produced the first haul: the 300-item budget was
    spent before the loop reached Plaster, and an architectural surface library
    that is 38% bricks and 0% plaster is not a library, it is a brick sampler.
    Round-robin spends the budget evenly and degrades gracefully — a category
    with only 6 materials contributes 6 and the rest share what it did not use.
    """
    skip = skip or set()
    buckets, seen = {}, set(skip)
    for cat in ACG_CATEGORIES:
        url = f'{ACG_API}?type=Material&category={urllib.parse.quote(cat)}&limit=200&include=downloadData,displayData'
        try:
            d = _get_json(url)
        except Exception as _exc:
            _zyg_log.warning('ACG category %s listing failed, contributing nothing: %s', cat, _exc)
            continue
        rows = []
        for a in d.get('foundAssets', []):
            aid = a.get('assetId')
            if not aid or aid in seen:
                continue
            dl = _acg_downloads(a)
            pick = next((f for f in dl if f.get('attribute') == f'{res}-JPG'), None)
            if not pick:
                continue
            rows.append(
                {
                    'id': aid,
                    'category': cat,
                    'name': a.get('displayName') or aid,
                    'url': pick['fullDownloadPath'],
                    'size': pick.get('size', 0),
                    'file': pick.get('fileName') or f'{aid}_{res}-JPG.zip',
                }
            )
        if rows:
            buckets[cat] = rows

    out, i = [], 0
    while buckets and len(out) < limit:
        for cat in list(buckets):
            if len(out) >= limit:
                break
            rows = buckets[cat]
            if i >= len(rows):
                del buckets[cat]
                continue
            row = rows[i]
            if row['id'] in seen:
                continue
            seen.add(row['id'])
            out.append(row)
        i += 1
    return out


def acg_fetch(plan: list[dict], root: str) -> dict:
    os.makedirs(root, exist_ok=True)
    registry, failed = {}, []

    def one(a):
        dest = os.path.join(root, a['id'], a['file'])
        ok, sha = _download(a['url'], dest, None)
        return a, (sha if ok else None), dest

    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for n, (a, sha, dest) in enumerate(ex.map(one, plan), 1):
            if not sha:
                failed.append(a['id'])
                continue
            registry[a['id']] = {
                'id': a['id'],
                'name': a['name'],
                'category': a['category'],
                'file': os.path.relpath(dest, root),
                'sha256': sha,
                'bytes': os.path.getsize(dest),
                'licence': 'CC0-1.0',
                'source_url': f'https://ambientcg.com/view?id={a["id"]}',
                'ingested': time.strftime('%Y-%m-%dT%H:%M:%S'),
            }
            if n % 25 == 0:
                _zyg_log.info(f'    {n}/{len(plan)}…')
    if failed:
        _zyg_log.warning(f'  FAILED {len(failed)}: {", ".join(failed[:10])}')
    return registry


# ── ambientCG: prepare the web-servable PBR sets ────────────────────────────

# What a three.js MeshStandardMaterial can actually use, mapped to the suffix
# ambientCG writes. Displacement is deliberately absent: it needs geometry to
# displace, and the studio's walls are two triangles a side.
ACG_MAPS = {
    'Color': 'map',
    'NormalGL': 'normalMap',  # GL, not DX — three.js expects +Y up
    'Roughness': 'roughnessMap',
    'Metalness': 'metalnessMap',
    'AmbientOcclusion': 'aoMap',
}
WEB_RES = 1024  # a viewport texture, not a render texture
WEB_QUALITY = 88
# The rail lists 460 surfaces. At 1K the albedos alone would be ~180 MB of
# image traffic to draw a column of chips, so every material also gets a
# thumbnail and the rail uses that. 320 rather than 128 because the same file
# is ALSO the hover card's picture at 212 CSS px — a 128 px thumb was being
# upscaled there and read as blurry.
THUMB_RES = 320
THUMB_QUALITY = 90


def acg_dimensions(ids: list[str]) -> dict:
    """Physical size per material, in METRES.

    This is the whole reason the materials look right rather than merely
    present: ambientCG publishes dimensionX/dimensionY in CENTIMETRES, so
    Bricks075A is a 2.0 × 1.0 m patch. Without it every surface gets the same
    arbitrary tiling and a brick wall reads as wallpaper."""
    out = {}

    def one(aid):
        try:
            d = _get_json(f'{ACG_API}?id={urllib.parse.quote(aid)}&include=dimensionsData,displayData')
            a = (d.get('foundAssets') or [{}])[0]
            x, y = a.get('dimensionX') or 0, a.get('dimensionY') or 0
            return aid, (round(x / 100.0, 4) or None, round(y / 100.0, 4) or None)
        except Exception:
            return aid, (None, None)

    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for aid, dims in ex.map(one, ids):
            out[aid] = dims
    return out


def acg_prepare(root: str, limit: int | None = None) -> dict:
    """Unpack each material zip into the maps the viewport needs, downsampled.

    The 2K zips STAY as the masters — they are what the registry hashed, and
    Blender wants the full-resolution originals. What is written here is a
    derivative set at 1K, which is what a WebGL viewport can actually use: the
    whole 300-material library comes to a few hundred megabytes instead of the
    seven gigabytes an unpacked copy would cost."""
    import io
    import zipfile
    from PIL import Image

    reg_path = os.path.join(root, 'registry.json')
    reg = json.load(open(reg_path))
    ids = sorted(reg)[:limit] if limit else sorted(reg)
    _zyg_log.info(f'  resolving physical size for {len(ids)} materials…')
    dims = acg_dimensions(ids)

    def one(aid):
        rec = reg[aid]
        src = os.path.join(root, rec['file'])
        web = os.path.join(root, aid, 'web')
        if not os.path.isfile(src):
            return aid, None
        maps = {}
        try:
            with zipfile.ZipFile(src) as zf:
                names = zf.namelist()
                for suffix, slot in ACG_MAPS.items():
                    hit = next(
                        (
                            n
                            for n in names
                            if n.lower().endswith(f'_{suffix.lower()}.jpg')
                            or n.lower().endswith(f'_{suffix.lower()}.png')
                        ),
                        None,
                    )
                    if not hit:
                        continue
                    os.makedirs(web, exist_ok=True)
                    out_name = f'{slot}.jpg'
                    out_path = os.path.join(web, out_name)
                    if not os.path.isfile(out_path):
                        with zf.open(hit) as fh:
                            im = Image.open(io.BytesIO(fh.read()))
                            im = im.convert('RGB')
                            if max(im.size) > WEB_RES:
                                im = im.resize((WEB_RES, WEB_RES), Image.LANCZOS)
                            im.save(out_path, 'JPEG', quality=WEB_QUALITY, optimize=True)
                    maps[slot] = f'{aid}/web/{out_name}'
                    if slot == 'map':
                        th = os.path.join(web, 'thumb.jpg')
                        if not os.path.isfile(th):
                            Image.open(out_path).resize((THUMB_RES, THUMB_RES), Image.LANCZOS).save(
                                th, 'JPEG', quality=THUMB_QUALITY, optimize=True
                            )
                        maps['thumb'] = f'{aid}/web/thumb.jpg'
        except Exception as e:  # noqa: BLE001
            _zyg_log.info(f'  SKIP {aid}: {type(e).__name__}: {e}')
            return aid, None
        return aid, maps

    # Most of ambientCG's older assets publish dimensionX/Y = 0 — no physical
    # size at all. A flat 1 m fallback would tile a brick sheet at four times
    # life size, so the fallback is LEARNED instead: the median measured size
    # of the other materials in the same category. Bricks that do publish a
    # size say 2.0 × 1.0 m, so the ones that do not inherit that rather than a
    # number nobody chose.
    by_cat = {}
    for aid in ids:
        x, y = dims.get(aid, (None, None))
        if x:
            by_cat.setdefault(reg[aid]['category'], []).append((x, y or x))

    def _median(vals):
        vals = sorted(vals)
        return vals[len(vals) // 2] if vals else None

    cat_default = {c: (_median([v[0] for v in vs]), _median([v[1] for v in vs])) for c, vs in by_cat.items()}
    _zyg_log.info(
        '  learned per-category fallback (m): ' + ', '.join(f'{c} {x}×{y}' for c, (x, y) in sorted(cat_default.items()))
    )

    made, failed = {}, []
    with cf.ThreadPoolExecutor(max(4, WORKERS // 2)) as ex:
        for n, (aid, maps) in enumerate(ex.map(one, ids), 1):
            if not maps or 'map' not in maps:
                failed.append(aid)
                continue
            x, y = dims.get(aid, (None, None))
            cat = reg[aid]['category']
            # THREE states, not two. Six categories (Marble, Metal, Onyx,
            # Plaster, Porcelain, Rock) have no measured member at all, so
            # their fallback is not a category median — it is a flat 1 m
            # assumption, and calling it a median would be a lie in a tooltip.
            if x:
                src = 'measured'
            elif cat in cat_default:
                x, y = cat_default[cat]
                src = 'category-median'
            else:
                x, y, src = 1.0, 1.0, 'assumed-1m'
            made[aid] = dict(
                reg[aid],
                maps=maps,
                size_m=[x or 1.0, y or x or 1.0],
                size_source=src,
                size_measured=(src == 'measured'),
            )
            if n % 50 == 0:
                _zyg_log.info(f'    {n}/{len(ids)}…')
    if failed:
        _zyg_log.info(f'  no usable maps for {len(failed)}: {", ".join(failed[:8])}')
    out = os.path.join(root, 'materials.json')
    with open(out, 'w') as f:
        json.dump(made, f, indent=1)
    nb = sum(
        os.path.getsize(os.path.join(root, p))
        for r in made.values()
        for p in r['maps'].values()
        if os.path.isfile(os.path.join(root, p))
    )
    return {
        'prepared': len(made),
        'failed': len(failed),
        'measured': sum(1 for r in made.values() if r['size_measured']),
        'web_bytes': nb,
        'out': out,
    }
