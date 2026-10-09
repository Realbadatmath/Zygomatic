# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""character_hair_assets.py — the hair-groom catalogue behind Character Studio's
Hair asset tool (2026-09-23).

char_hair.js GROWS hair: thousands of ribbon strands raised off the clay body's
own scalp field. That path stays, and it is still what an unposed default head
wears. This module owns the other half — grooms that were MODELLED by somebody
else and that no procedural rule will reproduce: MakeHuman's hair-card styles
and Blender Studio's production strand grooms.

WHY NOT architecture_assets. The mesh-pack catalogue next door already gates
licences exactly the way this one needs to, and its gate is imported here
rather than copied, so there is one policy and not two. What it cannot carry is
the FIT: a groom is meaningless without the head it was modelled on, and an
architecture item has no place to put one. Hair therefore gets its own root and
its own manifest, and the Architecture Studio's Assets rail stays free of
twenty hairstyles it will never place.

THE FIT. Every groom is stored in its DONOR'S OWN HEAD FRAME, measured at
conversion time (tools/hair_assets/): a MakeHuman groom in head widths off the
hm08 base body's head centre, a Blender Studio groom in skull radii off a
least-squares sphere fitted to the scalp it grew on. The client measures the
same frame on the clay body it is standing and maps one onto the other. Nothing
here assumes a proportion; `fit` carries the numbers and the client can show
them.

FAIL-CLOSED, per FILE. A pack is listed only if it can show a licence this
project may embed in published output, and the evidence is read from what the
vendor shipped beside the bytes before any note we wrote. The MakeHuman hair02
pack is the case in point: its own manifest calls all 21 styles CC-BY, and one
of them declares AGPL3 in its own .mhclo header. That one is not in the pack.

Public API:
    catalogue()            -> {'ok', 'packs', 'items', 'refused', 'count'}
    resolve_url(relpath)   -> absolute path for the browser asset route, or None
    mime_for(path)         -> content type
"""

from __future__ import annotations

import json
import os
import time

from zyg_workflows import architecture_assets as aa
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
# Inside the mesh-pack root, under an underscore: architecture_assets skips
# underscore-prefixed trees when it builds its catalogue, so these packs are
# SERVED by the existing /inspect/arch-asset/ route — byte ranges, one-day
# cache, one traversal fence already written and tested — without appearing in
# the Architecture Studio's Assets rail, where a hairstyle is noise.
PACKS_ROOT = os.path.realpath(os.path.join(HERE, 'data', 'assets', 'mesh_packs'))
HAIR_DIR = '_hair'
HAIR_ROOT = os.path.join(PACKS_ROOT, HAIR_DIR)

# what the browser fetches: /inspect/arch-asset/<URL_PREFIX><pack>/glb/<file>
URL_PREFIX = HAIR_DIR + '/'

# One policy, imported and not restated: CC0 and public domain are free to
# embed, CC-BY is admitted and carries attrib all the way to the rail.
LICENCE_OK = aa.LICENCE_OK
SERVE_EXT = aa.SERVE_EXT

_CACHE = {'ts': 0.0, 'sig': None, 'data': None}
_CACHE_TTL = 30.0


def _signature() -> tuple:
    """Cheap change detector: the manifests and their mtimes."""
    out = []
    try:
        for pack in sorted(os.listdir(HAIR_ROOT)):
            pd = os.path.join(HAIR_ROOT, pack)
            if not os.path.isdir(pd) or pack.startswith(('_', '.')):
                continue
            for fn in ('HAIR.json', 'PROVENANCE.json'):
                fp = os.path.join(pd, fn)
                try:
                    out.append((pack, fn, os.path.getmtime(fp)))
                except OSError:
                    out.append((pack, fn, 0.0))
            try:
                out.append((pack, 'glb', len(os.listdir(os.path.join(pd, 'glb')))))
            except OSError as _exc:
                _zyg_log.debug('hair pack glb count skipped: %s', _exc)
    except OSError as _exc:
        _zyg_log.debug('hair root listing skipped: %s', _exc)
    return tuple(out)


def _read_json(fp: str):
    try:
        with open(fp, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _build() -> dict:
    packs, items, refused = [], [], []
    try:
        names = sorted(
            d
            for d in os.listdir(HAIR_ROOT)
            if os.path.isdir(os.path.join(HAIR_ROOT, d)) and not d.startswith(('_', '.'))
        )
    except OSError:
        names = []

    for pack in names:
        pd = os.path.join(HAIR_ROOT, pack)
        prov = _read_json(os.path.join(pd, 'PROVENANCE.json'))
        lic, quote = aa._pack_licence(None, prov, pack, pd)
        if lic not in LICENCE_OK:
            refused.append(
                {'pack': pack, 'why': ('no PROVENANCE.json' if not lic else f'licence {lic} may not be embedded')}
            )
            continue
        man = _read_json(os.path.join(pd, 'HAIR.json'))
        if not man or not man.get('items'):
            refused.append({'pack': pack, 'why': 'no HAIR.json manifest'})
            continue
        attrib = LICENCE_OK[lic]
        n = 0
        for it in man['items']:
            rel = f'glb/{it["file"]}'
            if not os.path.isfile(os.path.join(pd, rel)):
                continue
            pv = None
            for ext in ('.png', '.jpg', '.webp'):
                cand = os.path.join(pd, '_previews', os.path.splitext(it['file'])[0] + ext)
                if os.path.isfile(cand):
                    pv = f'{URL_PREFIX}{pack}/_previews/{os.path.basename(cand)}'
                    break
            items.append(
                {
                    'id': f'{pack}|{it["id"]}',
                    'pack': pack,
                    'item': it['id'],
                    'label': it.get('label') or it['id'],
                    'kind': it.get('kind', 'cards'),
                    'part': it.get('part', 'hair'),
                    'u': f'{URL_PREFIX}{pack}/{rel}',
                    'pv': pv,
                    'licence': lic,
                    'attrib': attrib,
                    'credit': it.get('credit') or man.get('credit') or '',
                    'author': it.get('author', ''),
                    'tags': it.get('tags', []),
                    'verts': it.get('verts'),
                    'tris': it.get('tris'),
                    'strands': it.get('strands_kept'),
                    'fit': it.get('fit') or man.get('fit') or {},
                    'note': it.get('note', ''),
                }
            )
            n += 1
        if not n:
            refused.append({'pack': pack, 'why': 'manifest lists no file on disk'})
            continue
        packs.append(
            {
                'id': pack,
                'n': man.get('label') or aa._pretty(pack),
                'licence': lic,
                'attrib': attrib,
                'quote': quote,
                'credit': man.get('credit', ''),
                'source_url': man.get('source_url', ''),
                'count': n,
                'refused_items': man.get('refused', []),
            }
        )

    items.sort(key=lambda i: (i['pack'], i['part'] != 'hair', i['label'].lower()))
    return {
        'ok': True,
        'packs': packs,
        'items': items,
        'refused': refused,
        'count': len(items),
        'index': {i['id']: i['u'] for i in items},
    }


def catalogue() -> dict:
    now = time.time()
    if _CACHE['data'] is not None and now - _CACHE['ts'] < _CACHE_TTL:
        return _CACHE['data']
    sig = _signature()
    if _CACHE['data'] is not None and sig == _CACHE['sig']:
        _CACHE['ts'] = now
        return _CACHE['data']
    data = _build()
    _CACHE.update({'ts': now, 'sig': sig, 'data': data})
    return data


def resolve_url(relpath: str) -> str | None:
    """Absolute path for one file under the hair asset route, or None.

    The same three gates the mesh-pack route uses: no traversal in the request,
    an extension allowlist, and a realpath that must still sit inside the hair
    root once every symlink is resolved."""
    s = str(relpath or '').strip().lstrip('/')
    if not s or '\\' in s or '..' in s.split('/') or s.startswith('.'):
        return None
    if not s.lower().endswith(SERVE_EXT):
        return None
    full = os.path.realpath(os.path.join(HAIR_ROOT, s))
    if not full.startswith(HAIR_ROOT + os.sep):
        return None
    return full if os.path.isfile(full) else None


def mime_for(path: str) -> str:
    return aa.mime_for(path)
