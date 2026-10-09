# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""arch_pack_ingest.polyhaven — Poly Haven: the model library, the HDRIs and the textures -
selection, planning and fetching.

Moved verbatim out of arch_pack_ingest.py (lines 170-405) when that 2,019-line
module became this package; no logic was changed.
"""

from __future__ import annotations

import concurrent.futures as cf
import os
import time
from .common import PH_API, PH_CATEGORIES, WORKERS, _get_json, _download

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# ── Poly Haven ──────────────────────────────────────────────────────────────


def ph_select() -> dict:
    assets = _get_json(f'{PH_API}/assets?t=models')
    return {k: v for k, v in assets.items() if PH_CATEGORIES & set(v.get('categories') or [])}


def ph_plan(ids: list[str], res: str = '2k') -> dict:
    """Resolve every selected model's glTF file list and total the bytes."""
    plan, missing = {}, []

    def one(aid):
        try:
            files = _get_json(f'{PH_API}/files/{aid}')
        except Exception:
            return aid, None
        node = (files.get('gltf') or {}).get(res, {}).get('gltf')
        if not node:
            return aid, None
        entries = {
            os.path.basename(node['url']): {'url': node['url'], 'md5': node.get('md5'), 'size': node.get('size', 0)}
        }
        for rel, inc in (node.get('include') or {}).items():
            entries[rel] = {'url': inc['url'], 'md5': inc.get('md5'), 'size': inc.get('size', 0)}
        return aid, entries

    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for aid, entries in ex.map(one, ids):
            if entries is None:
                missing.append(aid)
            else:
                plan[aid] = entries
    if missing:
        _zyg_log.warning(
            f'  no glTF@{res} for {len(missing)}: {", ".join(missing[:8])}{"…" if len(missing) > 8 else ""}'
        )
    return plan


def ph_fetch(plan: dict, meta: dict, root: str, res: str = '2k') -> dict:
    os.makedirs(root, exist_ok=True)
    registry, failed = {}, []

    def one(item):
        aid, entries = item
        adir = os.path.join(root, aid)
        files = {}
        for rel, e in entries.items():
            ok, sha = _download(e['url'], os.path.join(adir, rel), e.get('md5'))
            if not ok:
                return aid, None
            files[rel] = {'sha256': sha, 'bytes': e['size'], 'url': e['url']}
        return aid, files

    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for n, (aid, files) in enumerate(ex.map(one, plan.items()), 1):
            if files is None:
                failed.append(aid)
                continue
            m = meta.get(aid, {})
            gltf = next((f for f in files if f.endswith('.gltf')), None)
            registry[aid] = {
                'id': aid,
                'name': m.get('name', aid),
                'categories': m.get('categories', []),
                'tags': m.get('tags', []),
                'authors': list((m.get('authors') or {}).keys()),
                'polycount': m.get('polycount'),
                'dimensions_mm': m.get('dimensions'),
                'resolution': res,
                'gltf': gltf,
                'files': files,
                'licence': 'CC0-1.0',
                'source_url': f'https://polyhaven.com/a/{aid}',
                'ingested': time.strftime('%Y-%m-%dT%H:%M:%S'),
            }
            if n % 25 == 0:
                _zyg_log.info(f'    {n}/{len(plan)}…')
    if failed:
        _zyg_log.warning(f'  FAILED {len(failed)}: {", ".join(failed[:10])}')
    return registry


# ── Poly Haven: the rest of the model library ───────────────────────────────
#
# The first haul filtered on PH_CATEGORIES and deliberately dropped the
# "collection: <scene>" tags on the grounds that a collection is a whole
# environment rather than a placeable object. That reasoning was about the
# TAG, not about the assets: the members of project_lighthouse and the_shed
# are individual rocks, crates, tools and industrial fittings, and each one
# loads and places exactly like any other model. 149 assets sat outside the
# filter for that reason; ph_select_all takes the catalogue entire.


def ph_select_all() -> dict:
    return _get_json(f'{PH_API}/assets?t=models')


# ── Poly Haven: HDRIs ───────────────────────────────────────────────────────
#
# A new asset TYPE rather than more of an existing one. Nothing in the library
# lit a scene before this: the studio and the Blender file both fell back to a
# constant world colour, which gives every curved surface the same highlight
# and is the single biggest thing separating a massing study from a render.


def ph_hdri_plan(ids: list[str], res: str = '2k', fmt: str = 'hdr') -> dict:
    plan, missing = {}, []

    def one(aid):
        try:
            files = _get_json(f'{PH_API}/files/{aid}')
        except Exception:
            return aid, None
        node = ((files.get('hdri') or {}).get(res) or {}).get(fmt)
        if not node:
            return aid, None
        return aid, {
            os.path.basename(node['url']): {'url': node['url'], 'md5': node.get('md5'), 'size': node.get('size', 0)}
        }

    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for aid, entries in ex.map(one, ids):
            (plan.__setitem__(aid, entries) if entries else missing.append(aid))
    if missing:
        _zyg_log.warning(f'  no {fmt}@{res} for {len(missing)}')
    return plan


# ── Poly Haven: textures ────────────────────────────────────────────────────
#
# ambientCG already fills the Materials rail, so this is not redundancy — it is
# the METADATA. ambientCG publishes a physical size for 145 of its 460
# materials and the other 315 run on a learned category median or a flat 1 m
# assumption. Poly Haven publishes `dimensions` in millimetres for 855 of 855.
# Every surface from here tiles at a size somebody measured, which is the one
# thing the size_m machinery cannot compute for itself.

# The map names Poly Haven uses -> the three.js material slot. Same set as
# ACG_MAPS and for the same reasons; nor_gl because three.js wants +Y up, and
# no Displacement because the studio's walls are two triangles a side.
PH_TEX_MAPS = {
    'Diffuse': 'map',
    'nor_gl': 'normalMap',
    'Rough': 'roughnessMap',
    'AO': 'aoMap',
    'metal': 'metalnessMap',
}


def ph_tex_plan(ids: list[str], res: str = '2k') -> dict:
    plan, missing = {}, []

    def one(aid):
        try:
            files = _get_json(f'{PH_API}/files/{aid}')
        except Exception:
            return aid, None
        entries = {}
        for ph_name, slot in PH_TEX_MAPS.items():
            node = ((files.get(ph_name) or {}).get(res) or {}).get('jpg')
            if not node:
                continue
            entries[f'{slot}.jpg'] = {
                'url': node['url'],
                'md5': node.get('md5'),
                'size': node.get('size', 0),
                'slot': slot,
            }
        # A surface with no albedo is not a surface.
        return aid, (entries if 'map.jpg' in entries else None)

    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for aid, entries in ex.map(one, ids):
            (plan.__setitem__(aid, entries) if entries else missing.append(aid))
    if missing:
        _zyg_log.warning(f'  no jpg@{res} albedo for {len(missing)}')
    return plan


def ph_simple_fetch(plan: dict, meta: dict, root: str, kind: str, res: str) -> dict:
    """Download a flat per-asset file set. Shared by HDRIs and textures."""
    os.makedirs(root, exist_ok=True)
    registry, failed = {}, []

    def one(item):
        aid, entries = item
        adir = os.path.join(root, aid)
        files = {}
        for rel, e in entries.items():
            ok, sha = _download(e['url'], os.path.join(adir, rel), e.get('md5'))
            if not ok:
                return aid, None
            files[rel] = {'sha256': sha, 'bytes': e['size'], 'url': e['url']}
        return aid, files

    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for n, (aid, files) in enumerate(ex.map(one, plan.items()), 1):
            if files is None:
                failed.append(aid)
                continue
            m = meta.get(aid, {})
            rec = {
                'id': aid,
                'name': m.get('name', aid),
                'categories': m.get('categories', []),
                'tags': m.get('tags', []),
                'authors': list((m.get('authors') or {}).keys()),
                'resolution': res,
                'files': files,
                'licence': 'CC0-1.0',
                'source_url': f'https://polyhaven.com/a/{aid}',
                'ingested': time.strftime('%Y-%m-%dT%H:%M:%S'),
            }
            if kind == 'hdri':
                rec['hdr'] = next(iter(files))
                rec['coords'] = m.get('coords')
                rec['evs_cap'] = m.get('evs_cap')
                rec['whitebalance'] = m.get('whitebalance')
            else:
                dim = m.get('dimensions') or []
                # Poly Haven states dimensions in MILLIMETRES; size_m is metres.
                rec['size_m'] = [round(d / 1000.0, 4) for d in dim] or [1.0, 1.0]
                rec['size_source'] = 'measured' if dim and all(dim) else 'assumed-1m'
                rec['size_measured'] = bool(dim and all(dim))
                rec['maps'] = {e['slot']: f'{aid}/{rel}' for rel, e in plan[aid].items()}
            registry[aid] = rec
            if n % 50 == 0:
                _zyg_log.info(f'    {n}/{len(plan)}…')
    if failed:
        _zyg_log.warning(f'  FAILED {len(failed)}: {", ".join(failed[:10])}')
    return registry
