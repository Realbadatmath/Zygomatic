# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""arch_pack_ingest.smithsonian — Smithsonian Open Access: the 3D record catalogue, the GLB
fetch and the streaming PLY -> decimate -> GLB pipeline.

Moved verbatim out of arch_pack_ingest.py (lines 1144-1582) when that 2,019-line
module became this package; no logic was changed.
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from zyg_workflows import paths
from .common import PACKS, WORKERS, _get_json, _download, _sha256
from .provenance import PROV
import logging as _zyg_logging

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_pack_ingest')


# -- Smithsonian Open Access -------------------------------------------------
#
# The one source here that is not game art or a studio scan: 1,937 CC0 records
# of REAL objects, scanned by the institution that holds them. Invertebrates,
# mammal skulls, fossils, aircraft parts, furniture, portrait busts. Nothing
# else in the library has a horseshoe crab or a Wright brothers propeller in
# it, and no generator is going to invent one that is right.
#
# Two things make it cheap. The search response already carries every download
# URL in its `resources` array, so the whole catalogue costs TWO API calls; and
# 3d-api.si.edu itself needs no key, so the downloads are unmetered.
#
# THE KEY. api.si.edu is api.data.gov, whose shared DEMO_KEY allows 30 requests
# an hour. Two calls at rows=1000 fetch all 1,937 records, so DEMO_KEY is
# sufficient here and no account is needed. Set SI_API_KEY to use your own.

SI_API = 'https://api.si.edu/openaccess/api/v1.0/search'
SI_QUERY = 'online_media_type:"3D Models"'
SI_PAGE = 1000


# The record set is cached because DEMO_KEY allows 30 requests an HOUR, shared
# across every user of api.data.gov. Two calls fetch all 1,937 records, so a
# handful of re-runs while iterating is enough to earn a 429 - and the rows are
# the only thing those calls produce. Cached under the pack so it travels with
# the data it describes.
SI_CACHE = 'records.json'
SI_CACHE_TTL = 7 * 24 * 3600


def si_records(cache_dir: str | None = None, max_age: float = SI_CACHE_TTL) -> list[dict]:
    """Every 3D record, with its resource list, in ceil(n/1000) calls.

    Served from cache when it is fresh, and FALLS BACK to a stale cache if the
    API refuses - a 429 an hour into an ingest should not throw away a haul
    when the answer is already on disk."""
    cache = os.path.join(cache_dir or os.path.join(PACKS, 'smithsonian'), SI_CACHE)
    if os.path.isfile(cache) and time.time() - os.path.getmtime(cache) < max_age:
        try:
            with open(cache) as f:
                return json.load(f)
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('fresh Smithsonian cache unreadable, refetching live: %s', _exc)
    try:
        rows = _si_records_live()
    except Exception as e:  # noqa: BLE001
        if os.path.isfile(cache):
            _zyg_log.warning(
                f'  {type(e).__name__} from the API; using the cached record '
                f'set from {time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(cache)))}'
            )
            with open(cache) as f:
                return json.load(f)
        raise
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, 'w') as f:
        json.dump(rows, f)
    return rows


def _si_records_live() -> list[dict]:
    key = os.environ.get('SI_API_KEY', 'DEMO_KEY')
    q = urllib.parse.quote(SI_QUERY)
    rows, start, total = [], 0, None
    while total is None or start < total:
        d = _get_json(f'{SI_API}?q={q}&rows={SI_PAGE}&start={start}&api_key={key}')
        resp = d.get('response') or {}
        total = resp.get('rowCount', 0)
        got = resp.get('rows') or []
        if not got:
            break
        rows.extend(got)
        start += len(got)
    return rows


def _si_media(rec: dict) -> dict | None:
    onl = ((rec.get('content') or {}).get('descriptiveNonRepeating') or {}).get('online_media') or {}
    for m in onl.get('media') or []:
        if m.get('type') == '3d_voyager':
            return m
    return None


def si_plan(rows: list[dict]) -> tuple[list[dict], dict]:
    """Pick ONE mesh per record: a plain .glb, never the draco one.

    Both consumers matter and they disagree. Blender's glTF importer decodes
    draco; the studio's three.js is r144 with no DRACOLoader registered, and a
    draco .glb there fails at parse with an error about a missing extension
    rather than anything that names the cause. So a record without a plain
    .glb is SKIPPED and counted, not silently taken in a format half the
    library cannot open. usdz and the full-resolution obj.zip are ignored for
    the same reason.

    Low resolution before full: these are 100k-triangle photogrammetry scans
    and the full-resolution variants run to hundreds of megabytes each."""
    plan, why = [], {'no-3d': 0, 'draco-only': 0, 'not-cc0': 0}
    for rec in rows:
        m = _si_media(rec)
        if not m:
            why['no-3d'] += 1
            continue
        if str(((m.get('usage') or {}).get('access') or '')).upper() != 'CC0':
            why['not-cc0'] += 1
            continue
        glbs = [
            r
            for r in (m.get('resources') or [])
            if (r.get('filename') or '').lower().endswith('.glb') and 'draco' not in (r.get('filename') or '').lower()
        ]
        if not glbs:
            why['draco-only'] += 1
            continue
        glbs.sort(key=lambda r: 0 if 'low' in str(r.get('category') or '').lower() else 1)
        pick = glbs[0]
        aid = m['id'].split(':')[-1]
        plan.append(
            {
                'id': aid,
                'name': rec.get('title') or aid,
                'unit': rec.get('unitCode') or '',
                'url': pick['url'],
                'file': pick.get('filename') or f'{aid}.glb',
                'size': int(pick.get('size') or 0),
                'record': rec.get('id') or '',
                'viewer': m.get('content') or '',
            }
        )
    return plan, why


# The unit codes, spelled out. A rail group called "NMNHINV" tells a person
# nothing; "Invertebrate Zoology" tells them there are crabs in it.
SI_UNITS = {
    'NMNHINV': 'Invertebrate Zoology',
    'NMNHMAMMALS': 'Mammals',
    'NMNHPALEO': 'Paleobiology',
    'NMNHBOTANY': 'Botany',
    'NMNHFISHES': 'Fishes',
    'NMNHENTO': 'Entomology',
    'NMNHHERPS': 'Reptiles & Amphibians',
    'NMNHEDUCATION': 'Education',
    'NMNHANTHRO': 'Anthropology',
    'NMAH': 'American History',
    'NMAAHC': 'African American History',
    'NMAI': 'American Indian',
    'NMAA': 'Asian Art',
    'NMAfA': 'African Art',
    'NPG': 'Portrait Gallery',
    'SAAM': 'American Art',
    'CHNDM': 'Cooper Hewitt Design',
    'NASM': 'Air and Space',
    'HMSG': 'Hirshhorn',
    'FSG': 'Freer Sackler',
    'OCIO_DPO3D': 'Digitization Program',
    'OFEO-SG': 'Smithsonian Gardens',
    'NPM': 'Postal Museum',
    'SIA': 'Institution Archives',
}


def si_slug(name: str, aid: str, taken: set) -> str:
    """A filename a person can read in an Asset Browser.

    The record id is a UUID and naming the file after it produces an asset
    called `03cb230f-8ad6-4d7f-bc41-aee9a05644fb`, which is what the first
    haul did. The stem is the item id in the catalogue AND the object name in
    Blender, so it is the only string either consumer ever shows — it has to
    be the title. Collisions get a numeric suffix rather than the UUID,
    because "Trilobite 2" reads and "Trilobite 03cb230f" does not."""
    base = re.sub(r'[^A-Za-z0-9]+', '_', str(name or aid)).strip('_')[:70]
    base = base or aid
    cand, n = base, 2
    while cand.lower() in taken:
        cand = f'{base}_{n}'
        n += 1
    taken.add(cand.lower())
    return cand


def si_fetch(plan: list[dict], root: str) -> dict:
    """One .glb per record, filed under its museum unit.

    Filed by UNIT rather than flat because the catalogue's group IS the
    directory: 906 invertebrates and 728 mammals in one bucket is a rail nobody
    can use, and the unit code is the only taxonomy the records all carry."""
    os.makedirs(root, exist_ok=True)
    registry, failed = {}, []

    # Names are assigned BEFORE the pool starts: the collision suffix has to
    # be deterministic, and racing threads over a shared set is not.
    taken_by_unit: dict[str, set] = {}
    for a in plan:
        unit = SI_UNITS.get(a['unit'], a['unit'] or 'Other')
        a['_sub'] = re.sub(r'[^A-Za-z0-9]+', '_', unit).strip('_')
        a['_stem'] = si_slug(a['name'], a['id'], taken_by_unit.setdefault(a['_sub'], set()))

    def one(a):
        dest = os.path.join(root, a['_sub'], f'{a["_stem"]}.glb')
        ok, sha = _download(a['url'], dest, None)
        return a, (sha if ok else None), dest, a['_sub']

    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for n, (a, sha, dest, _sub) in enumerate(ex.map(one, plan), 1):
            if not sha:
                failed.append(a['id'])
                continue
            registry[a['id']] = {
                'id': a['id'],
                'name': a['name'],
                'unit': a['unit'],
                'unit_name': SI_UNITS.get(a['unit'], a['unit']),
                'file': os.path.relpath(dest, root),
                'sha256': sha,
                'bytes': os.path.getsize(dest),
                'licence': 'CC0-1.0',
                'source_url': a['viewer'],
                'record': a['record'],
                'ingested': time.strftime('%Y-%m-%dT%H:%M:%S'),
            }
            if n % 50 == 0:
                _zyg_log.info(f'    {n}/{len(plan)}...')
    if failed:
        _zyg_log.warning(f'  FAILED {len(failed)}: {", ".join(failed[:10])}')
    return registry


def si_unit_provenance(root: str, registry: dict) -> int:
    """One PROVENANCE.json per museum unit, which is what makes them PACKS.

    architecture_assets decides "is this directory a pack or a bag of items"
    by evidence: a subdirectory carrying its own licence file or PROVENANCE is
    a pack in its own right. Without this the whole Smithsonian haul is a
    single drawer of 1,152 things — 728 mammal skulls and a Wright propeller in
    the same list, which is a directory listing rather than a library. Each
    unit is a real collection with its own curators, so making it a pack is
    also the truthful shape."""
    by_unit = {}
    for r in registry.values():
        by_unit.setdefault(os.path.dirname(r['file']) or 'Other', []).append(r)
    for sub, recs in by_unit.items():
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        p_ = dict(PROV['smithsonian'])
        p_.update(
            {
                'curated': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'tool': 'arch_pack_ingest.py',
                'unit': recs[0].get('unit'),
                'unit_name': recs[0].get('unit_name'),
                'source_summary': (
                    f'Smithsonian Open Access 3D — '
                    f'{recs[0].get("unit_name")} '
                    f'({recs[0].get("unit")}), low-resolution GLB'
                ),
                'item_count': len(recs),
                'byte_count': sum(r.get('bytes', 0) for r in recs),
            }
        )
        with open(os.path.join(d, 'PROVENANCE.json'), 'w') as f:
            json.dump(p_, f, indent=1)
    return len(by_unit)


# -- Smithsonian: the PLY-only mammal scans ----------------------------------
#
# 718 records, every one NMNHMAMMALS, publish a FULL-RESOLUTION ASCII PLY and
# nothing else - no GLB, no usdz. ~150 MB and 750k faces apiece: 79 GB of
# transfer that neither consumer could open as delivered. So the master is
# never kept. Each scan is downloaded, decimated to 100k faces (the same
# budget the Smithsonian's own "low resolution" GLBs use), scaled out of
# millimetres into metres and written as a GLB - then the PLY is deleted.
#
# Peak disk is bounded by the worker count, not by the haul: at 12 workers no
# more than ~1.8 GB of PLY is on disk at once, and the 6 GB of GLB output is
# what remains. That is the whole reason this is a streaming pipeline rather
# than a fetch followed by a convert.

SI_PLY_TARGET_TRIS = 100000
SI_PLY_UNITS = 'mm'  # measured: a gibbon cranium imports at 103 units
# The conversions are CPU-bound and the downloads are not, so they get
# different limits; the semaphore is what stops 12 Blenders competing for the
# 20 cores this box is capped at.
SI_PLY_CONVERT_JOBS = 5


# USNM143596_ulna_left_-500.ply -> "ulna left". The record TITLE is only the
# species, and 718 records cover a couple of hundred species, so titles alone
# would produce Pongo_abelii_2 .. Pongo_abelii_15 and nobody could tell a
# cranium from an ulna without opening it. The element is in the vendor's
# filename and nowhere else in the record.
_SI_ELEMENT = re.compile(r'^[A-Za-z]*\d+[a-z]?_(.+?)_-?\d+(?:_dec)?$', re.I)


def _si_specimen_name(title: str, filename: str) -> str:
    stem = os.path.splitext(os.path.basename(filename or ''))[0]
    m = _SI_ELEMENT.match(stem)
    if not m:
        return title
    element = m.group(1).replace('_', ' ').strip()
    if not element or element.lower() in title.lower():
        return title
    return f'{title} {element}'


def si_ply_plan(rows: list[dict]) -> list[dict]:
    out = []
    for rec in rows:
        m = _si_media(rec)
        if not m:
            continue
        if str(((m.get('usage') or {}).get('access') or '')).upper() != 'CC0':
            continue
        res = m.get('resources') or []
        if any((r.get('filename') or '').lower().endswith('.glb') for r in res):
            continue  # the GLB path already took this one
        ply = [r for r in res if (r.get('filename') or '').lower().endswith('.ply')]
        if not ply:
            continue
        fn = ply[0].get('filename') or 'scan.ply'
        out.append(
            {
                'id': m['id'].split(':')[-1],
                'name': _si_specimen_name(rec.get('title') or m['id'], fn),
                'unit': rec.get('unitCode') or 'NMNHMAMMALS',
                'url': ply[0]['url'],
                'file': fn,
                'record': rec.get('id') or '',
                'viewer': m.get('content') or '',
            }
        )
    return out


def si_ply_fetch(plan: list[dict], root: str, staging: str) -> dict:
    """Download -> decimate -> export -> DELETE the master, one at a time."""
    import subprocess
    import threading

    blender = os.environ.get('BLENDER', 'blender')
    converter = str(paths.PKG_DIR / 'blender_scripts' / 'ply_to_glb.py')
    os.makedirs(staging, exist_ok=True)
    gate = threading.BoundedSemaphore(SI_PLY_CONVERT_JOBS)
    registry, failed = {}, []
    lock = threading.Lock()

    def one(a):
        tmp = os.path.join(staging, f'{a["id"]}.ply')
        try:
            ok, _sha = _download(a['url'], tmp, None)
            if not ok:
                return a, None, 'download'
            with gate:
                r = subprocess.run(
                    [
                        blender,
                        '-b',
                        '--factory-startup',
                        '--python',
                        converter,
                        '--',
                        '--in',
                        tmp,
                        '--out',
                        a['dest'],
                        '--target-tris',
                        str(SI_PLY_TARGET_TRIS),
                        '--units',
                        SI_PLY_UNITS,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=900,
                )
            line = next((l for l in r.stdout.splitlines() if l.startswith('@@RESULT@@')), None)
            if not line:
                return a, None, 'convert'
            import ast as _ast

            info = _ast.literal_eval(line[len('@@RESULT@@ ') :])
            if info.get('error') or not os.path.isfile(a['dest']):
                return a, None, info.get('error') or 'no output'
            return a, info, None
        except subprocess.TimeoutExpired:
            return a, None, 'convert timeout'
        except Exception as e:  # noqa: BLE001
            return a, None, f'{type(e).__name__}: {e}'
        finally:
            # The master goes whether or not the conversion worked. Keeping
            # failures would grow an unbounded pile of 150 MB files nobody
            # reads, and the URL is in the plan if one needs retrying.
            if os.path.isfile(tmp):
                try:
                    os.unlink(tmp)
                except OSError as _exc:
                    _zyg_log.debug('master scan cleanup skipped: %s', _exc)

    done = 0
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for a, info, why in ex.map(one, plan):
            if info is None:
                failed.append((a['id'], why))
                continue
            with lock:
                registry[a['id']] = {
                    'id': a['id'],
                    'name': a['name'],
                    'unit': a['unit'],
                    'unit_name': SI_UNITS.get(a['unit'], a['unit']),
                    'file': os.path.relpath(a['dest'], root),
                    'stem': a['stem'],
                    'sha256': _sha256(a['dest']),
                    'bytes': os.path.getsize(a['dest']),
                    'faces': info.get('faces_out'),
                    'faces_source': info.get('faces_in'),
                    'size_m': list(info.get('size_m') or []),
                    'derived': (
                        f'decimated from the source PLY to '
                        f'{SI_PLY_TARGET_TRIS} faces and scaled from '
                        f'{SI_PLY_UNITS} to metres; master not kept'
                    ),
                    'source_file': a['file'],
                    'licence': 'CC0-1.0',
                    'source_url': a['viewer'],
                    'record': a['record'],
                    'ingested': time.strftime('%Y-%m-%dT%H:%M:%S'),
                }
                done += 1
                if done % 25 == 0:
                    _zyg_log.info(f'    {done}/{len(plan)} converted...')
    if failed:
        _zyg_log.warning(f'  FAILED {len(failed)}: {", ".join(f"{i} ({w})" for i, w in failed[:8])}')
    return registry
