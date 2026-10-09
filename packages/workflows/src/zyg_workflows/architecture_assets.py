# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""architecture_assets.py — the mesh-pack catalogue behind the Architecture
Studio's Assets rail (2026-09-01).

architecture_studio.py owns the PARAMETRIC catalogue: a `kind` plus numbers
that the client's geometry factory rebuilds from scratch on every load. This
module owns the other half — the CC0 model packs on disk that no amount of
arithmetic will produce, and that the studio therefore has to load as files.

The contract with the drawing is unchanged and deliberately so. A placed asset
is still stored as PARAMETERS:

    {kind: 'asset', p: {pack: 'kenney/building-kit', item: 'wall-half'}}

— never as geometry, never as an absolute path. A drawing that names a pack it
cannot find degrades to a placeholder box; it does not fail to open. That is
the same rule `arGeom()` already lives under, applied to files.

WHY A PACK CAN BE REFUSED. The catalogue is FAIL-CLOSED on licence. A pack is
listed only if it can SHOW a licence this project may embed in published
output — CC0 / public domain, or CC-BY, which is admitted but carries an
`attrib` flag the whole way to the rail. The evidence is read from the licence
file the vendor shipped inside the pack BEFORE any PROVENANCE.json we wrote
about it, because the root-licence-lies lesson says the file next to the bytes
is the only one worth quoting. A pack that can show nothing is not "probably
fine", it is INVISIBLE — the one audit an operator will never perform by hand
is of a directory that already appears in a picker. Refusals come back through
`catalogue()['refused']`, so a missing pack is legible rather than mysterious.

Public API:
    catalogue()              -> {'ok', 'packs':[...], 'sections':[...], 'refused':[...]}
    resolve(pack, rel)       -> absolute path inside that pack, or None
    packs()                  -> the pack records alone (no items)
"""

from __future__ import annotations

import json
import os
import re
import time
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
PACKS_ROOT = os.path.realpath(os.path.join(HERE, 'data', 'assets', 'mesh_packs'))

MESH_EXT = ('.glb', '.gltf')

# Licences whose assets may appear in published output. CC-BY is admitted but
# carries `attrib=True` all the way to the client, so a rail can mark it.
LICENCE_OK = {
    'CC0-1.0': False,
    'CC0': False,
    'CC0 1.0': False,
    'PUBLIC-DOMAIN': False,
    'PUBLIC DOMAIN': False,
    'CC-PD': False,
    'CC-BY-4.0': True,
    'CC-BY': True,
    'CC-BY-3.0': True,
    # 2026-09-23: built HERE, by Architecture Studio, from the operator's own
    # reference pictures (mesh_packs/zyg_reference/*). Nothing third-party is
    # embedded, so there is nothing to attribute — but it still needs a class,
    # because a pack whose licence is unrecognised is refused outright.
    'OWN-WORK': False,
}

# Directories inside a pack that hold source/interchange copies of the same
# models. Listing them would show every wall three times.
SKIP_DIRS = re.compile(
    r'(^|/)(OBJ|FBX|OBJ format|FBX format|Sources?|'
    r'Unity|Unreal|Godot|Blend|Blender|__MACOSX|_previews|'
    r'Previews|Isometric|textures)(/|$)',
    re.I,
)

_CACHE = {'ts': 0.0, 'sig': None, 'data': None}
_CACHE_TTL = 30.0

# ── triangle budget (2026-09-11) ────────────────────────────────────────────
# A live 20-storey job came out at 15.66 M triangles, 15.5 M of which were four
# copies of one photoscanned jacaranda (3,863,832 tris each). The scan counts
# triangles into DIMENSIONS.json 'tris'; this is the per-PLACEMENT ceiling the
# catalogue's consumers hold anything placed to.
TRI_BUDGET = 400_000

# Polyhaven ships its models at a texture resolution: `jacaranda_tree_2k`. A
# decimated stand-in is of the MODEL, not of that resolution, so the suffix
# comes off: jacaranda_tree_2k -> jacaranda_tree_lod1.
_RES_SUFFIX = re.compile(r'_(?:\d+k)$', re.I)


def lod_stem(item: str) -> str:
    """The item id a decimated stand-in for `item` is filed under."""
    return _RES_SUFFIX.sub('', str(item or '')) + '_lod1'


# ── licence ─────────────────────────────────────────────────────────────────


def _norm_licence(raw: str) -> str:
    s = str(raw or '').strip().upper()
    if not s:
        return ''
    # "CC0 1.0 Universal (CC0 1.0) Public Domain Dedication" and friends.
    if 'CC0' in s:
        return 'CC0-1.0'
    if 'PUBLIC DOMAIN' in s or s.startswith('PD'):
        return 'PUBLIC-DOMAIN'
    m = re.search(r'CC[- ]BY(?![- ]?(NC|ND|SA))[- ]?([0-9.]+)?', s)
    if m:
        return 'CC-BY'
    return s[:40]


def _read_provenance(pack_dir: str) -> dict | None:
    p = os.path.join(pack_dir, 'PROVENANCE.json')
    if not os.path.isfile(p):
        return None
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


LICENCE_FILE = re.compile(r'^(licen[cs]e|license_evidence|copying)[^/]*\.(txt|md)$', re.I)

# The statements a vendor's own bundled licence file actually contains.
_CC0_TEXT = re.compile(
    r'creative commons zero|CC0[ ._-]?1\.0|publicdomain/zero|'
    r'public[- ]domain|no copyright restrictions',
    re.I,
)
_CCBY_TEXT = re.compile(
    r'creative commons attribution(?![ -]non)|CC[ -]BY[ -]?[0-9.]*'
    r'(?![ -]?(NC|ND|SA))',
    re.I,
)
_BAD_TEXT = re.compile(
    r'non[- ]commercial|CC[ -]BY[ -]?(NC|ND)|personal use only|'
    r'may not be used commercially',
    re.I,
)


def _licence_file(d: str) -> str | None:
    try:
        for fn in sorted(os.listdir(d)):
            if LICENCE_FILE.match(fn) and os.path.isfile(os.path.join(d, fn)):
                return os.path.join(d, fn)
    except OSError as _exc:
        _zyg_log.debug('licence file scan skipped, directory unreadable: %s', _exc)
    return None


def _licence_from_file(d: str) -> tuple[str, str]:
    """Read the pack's OWN bundled licence file.

    This is the primary evidence on purpose. A vendor-level PROVENANCE.json is
    a note WE wrote about a tree; the License.txt inside the pack is what the
    vendor shipped with these exact files — and the root-vs-file lesson from
    the TripoSG finding is that only the second one is worth anything."""
    p = _licence_file(d)
    if not p:
        return '', ''
    try:
        with open(p, encoding='utf8', errors='ignore') as f:
            txt = f.read(8192)
    except OSError:
        return '', ''
    if _BAD_TEXT.search(txt):
        # An explicit restriction beats any permissive phrase in the same file.
        return 'RESTRICTED', txt.strip()[:300]
    if _CC0_TEXT.search(txt):
        return 'CC0-1.0', _quote(txt, _CC0_TEXT)
    if _CCBY_TEXT.search(txt):
        return 'CC-BY', _quote(txt, _CCBY_TEXT)
    return '', ''


def _quote(txt: str, pat: re.Pattern) -> str:
    m = pat.search(txt)
    if not m:
        return txt.strip()[:200]
    a = max(0, m.start() - 90)
    return ' '.join(txt[a : m.end() + 150].split())[:300]


def _pack_licence(vendor_prov: dict | None, pack_prov: dict | None, pack_name: str, pack_dir: str) -> tuple[str, str]:
    """(normalised licence, evidence quote) for one pack.

    Order of evidence, strongest first:
      1. the licence file the vendor shipped INSIDE the pack
      2. a pack-level PROVENANCE.json
      3. the matching entry in a vendor-level PROVENANCE.json `packs` list
      4. a vendor-level licence covering the whole tree
    """
    lic, quote = _licence_from_file(pack_dir)
    if lic:
        return lic, quote

    def _key(s):
        return re.sub(r'[^a-z0-9]+', ' ', str(s).lower()).strip()

    want = _key(pack_name)
    for prov in (pack_prov, vendor_prov):
        if not prov:
            continue
        for rec in prov.get('packs') or []:
            if want and want in _key(rec.get('name', '')):
                return _norm_licence(rec.get('license') or rec.get('licence')), str(rec.get('license_quote') or '')[
                    :300
                ]
        lic = prov.get('license') or prov.get('licence')
        if lic:
            return _norm_licence(lic), str(prov.get('license_quote') or '')[:300]
        # A vendor tree we ingested ourselves states its licence once per pack
        # rather than once for the tree. Inherit it only when every entry
        # AGREES — a mixed tree must be split, not averaged.
        seen = {_norm_licence(r.get('license') or r.get('licence')) for r in (prov.get('packs') or [])}
        seen.discard('')
        if len(seen) == 1:
            one = seen.pop()
            q = next((str(r.get('license_quote') or '') for r in prov['packs'] if r.get('license_quote')), '')
            return one, q[:300]
    return '', ''


# ── scanning ────────────────────────────────────────────────────────────────


def _pretty(stem: str) -> str:
    s = re.sub(r'[_\-]+', ' ', stem).strip()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'\b(\d+k)\b', '', s, flags=re.I).strip()
    return (s[:1].upper() + s[1:]) if s else stem


# Where a vendor hides its rendered previews. Kenney ships `Previews/`, its
# nature kit ships `Isometric/` and `Side/`, Blender Studio ships `thumbnails/`.
PREVIEW_DIRS = ('Previews', 'Preview', 'Isometric', 'Side', 'thumbnails', '_previews')
PREVIEW_EXT = ('.png', '.jpg', '.jpeg', '.webp')

# Previews we rendered ourselves for the packs that ship none, kept OUT of the
# pack directories so a re-download never has to reason about what is ours.
GEN_PREVIEWS = os.path.join(PACKS_ROOT, '_generated_previews')


def _preview_index(pack_dir: str, pack_id: str) -> dict:
    """stem (lowercased) -> preview path relative to PACKS_ROOT.

    Built once per pack during the scan rather than probed per item: a hover
    that stats the filesystem is a hover that stutters, and the rail asks for
    up to 1,500 of them."""
    idx = {}
    # Generated previews win: they are rendered from the exact file the
    # catalogue lists, whereas a vendor's shipped art may be of a variant.
    for base in (pack_dir, os.path.join(GEN_PREVIEWS, pack_id)):
        roots = [os.path.join(base, d) for d in PREVIEW_DIRS] + [base] if base == pack_dir else [base]
        for pd in roots:
            if not os.path.isdir(pd):
                continue
            for root, _dirs, files in os.walk(pd):
                for fn in files:
                    stem, ext = os.path.splitext(fn)
                    if ext.lower() not in PREVIEW_EXT:
                        continue
                    key = stem.lower()
                    full = os.path.join(root, fn)
                    if key not in idx or base != pack_dir:
                        idx[key] = os.path.relpath(full, PACKS_ROOT).replace(os.sep, '/')
    return idx


def _scan_pack(vendor: str, pack: str, pack_dir: str) -> list[dict]:
    """Every mesh file in one pack, de-duplicated by stem.

    A kit ships the same wall as GLB, OBJ and FBX; SKIP_DIRS drops the
    interchange copies, and a stem seen twice keeps the first (glTF sorts
    before OBJ anyway once the directories are gone)."""
    items, seen = [], set()
    # 2026-09-07: measured sizes and search notes ride along from two sidecar
    # files a pack may carry — DIMENSIONS.json (mesh_pack_dims.py, metres,
    # glTF axes) and NOTES.json (vendor categories/tags). Without a measured
    # size every item reported 1 x 1 x 1 m, and a 1 m palm is a toy.
    dims, notes, tris = {}, {}, {}
    try:
        sidecar = json.load(open(os.path.join(pack_dir, 'DIMENSIONS.json'), encoding='utf-8')) or {}
        dims = sidecar.get('dims') or {}
        tris = sidecar.get('tris') or {}
    except (OSError, ValueError) as _exc:
        _zyg_log.warning('DIMENSIONS.json unreadable, pack listed without dimensions: %s', _exc)
    try:
        notes = (json.load(open(os.path.join(pack_dir, 'NOTES.json'), encoding='utf-8')) or {}).get('notes') or {}
    except (OSError, ValueError) as _exc:
        _zyg_log.warning('NOTES.json unreadable, pack listed without notes: %s', _exc)
    for root, dirs, files in os.walk(pack_dir):
        rel_dir = os.path.relpath(root, pack_dir).replace(os.sep, '/')
        if rel_dir == '.':
            rel_dir = ''
        dirs[:] = [d for d in dirs if not SKIP_DIRS.search(f'{rel_dir}/{d}'.strip('/'))]
        if rel_dir and SKIP_DIRS.search(rel_dir):
            continue
        for fn in sorted(files):
            if not fn.lower().endswith(MESH_EXT):
                continue
            stem = os.path.splitext(fn)[0]
            key = stem.lower()
            if key in seen:
                continue
            seen.add(key)
            rel = f'{rel_dir}/{fn}' if rel_dir else fn
            try:
                st = os.stat(os.path.join(root, fn))
                size, ver = st.st_size, int(st.st_mtime)
            except OSError as _exc:
                _zyg_log.debug('asset file skipped, stat failed: %s', _exc)
                continue
            d = dims.get(rel)
            top = rel.split('/')[0] if '/' in rel else stem
            items.append(
                {
                    'id': f'{vendor}/{pack}|{stem}',
                    'pack': f'{vendor}/{pack}',
                    'rel': rel,
                    'n': _pretty(stem),
                    'bytes': size,
                    # the FILE's mtime, carried through to the url as ?v= so a
                    # rebuilt asset at the same path is a new url to the browser
                    'ver': ver,
                    'dims': [float(x) for x in d] if isinstance(d, list) and len(d) == 3 else None,
                    # None (not 0) when the pack has never been counted: unknown is
                    # not the same as free, and a budget must not refuse on a guess.
                    'tris': int(tris[rel]) if isinstance(tris.get(rel), (int, float)) else None,
                    'note': str(notes.get(stem) or notes.get(top) or ''),
                }
            )
    return items


# the vendors whose files this machine REWRITES in place (a reference-model
# build overwrites <item>.glb every time), so their mesh mtimes join the
# signature; a vendor pack that only ever arrives whole does not need it.
VER_VENDORS = ('zyg_reference',)


def _signature() -> tuple:
    """Cheap change-detector: the mtime of every pack directory, PLUS the mtime
    of every mesh file in the packs a build writes into. Rescanning ~4,000 files
    on each rail open would cost more than the rail is worth.

    2026-09-23: directory mtime alone is not enough. Rebuilding an asset
    overwrites its .glb IN PLACE, which leaves the pack directory's mtime
    untouched, so the cached catalogue kept serving the pre-rebuild size, tris
    and version for the life of the process. Only the vendors a build writes
    into are walked (VER_VENDORS), so the common case stays one stat per pack."""
    sig = []
    try:
        vendors = sorted(os.listdir(PACKS_ROOT))
    except OSError:
        return ()
    # Generated previews live outside every pack, so nothing about a pack's
    # mtime changes when they appear. Without this the rail would cache a
    # preview-less catalogue for as long as the process lived.
    try:
        sig.append(('_gen', os.path.getmtime(GEN_PREVIEWS)))
        for d in sorted(os.listdir(GEN_PREVIEWS)):
            p = os.path.join(GEN_PREVIEWS, d)
            if os.path.isdir(p):
                sig.append((f'_gen/{d}', os.path.getmtime(p)))
    except OSError as _exc:
        _zyg_log.debug('generated-preview signature skipped, directory unreadable: %s', _exc)
    for v in vendors:
        vd = os.path.join(PACKS_ROOT, v)
        if not os.path.isdir(vd):
            continue
        try:
            sig.append((v, os.path.getmtime(vd)))
            for p in sorted(os.listdir(vd)):
                pd = os.path.join(vd, p)
                if not os.path.isdir(pd):
                    continue
                sig.append((f'{v}/{p}', os.path.getmtime(pd)))
                if v in VER_VENDORS:
                    for fn in sorted(os.listdir(pd)):
                        if fn.lower().endswith(MESH_EXT):
                            sig.append((f'{v}/{p}/{fn}', os.path.getmtime(os.path.join(pd, fn))))
        except OSError as _exc:
            _zyg_log.debug('vendor signature skipped, directory unreadable: %s', _exc)
            continue
    return tuple(sig)


def _build() -> dict:
    packs, refused, all_items = [], [], []
    try:
        # Underscore-prefixed trees are OURS (_generated_previews), not a
        # vendor. Scanned as one it would show up in `refused` for having no
        # licence — true, meaningless, and it would bury the real refusals.
        vendors = sorted(
            d
            for d in os.listdir(PACKS_ROOT)
            if os.path.isdir(os.path.join(PACKS_ROOT, d)) and not d.startswith(('_', '.'))
        )
    except OSError:
        vendors = []

    for vendor in vendors:
        vdir = os.path.join(PACKS_ROOT, vendor)
        vprov = _read_provenance(vdir)
        # A vendor tree is either a set of pack dirs, or one flat pack.
        subs = sorted(
            d for d in os.listdir(vdir) if os.path.isdir(os.path.join(vdir, d)) and not d.startswith(('_', '.'))
        )
        # Is a vendor directory a set of PACKS, or one pack whose subdirectories
        # are ITEMS? Decided by evidence, not by name: a kit that ships its own
        # licence file is a pack in its own right (Kenney, Quaternius), while a
        # tree we ingested ourselves carries one licence at the vendor root and
        # one directory per model (polyhaven_arch, ambientcg, polyhaven_props).
        packlike = [
            s
            for s in subs
            if _licence_file(os.path.join(vdir, s)) or os.path.isfile(os.path.join(vdir, s, 'PROVENANCE.json'))
        ]
        pairs = [(vendor, s, os.path.join(vdir, s)) for s in packlike] if packlike else [(vendor, '', vdir)]

        for vend, pack, pdir in pairs:
            pname = pack or vend
            pprov = _read_provenance(pdir) if pack else vprov
            lic, quote = _pack_licence(vprov, pprov, pname, pdir)
            pack_id = f'{vend}/{pack}' if pack else vend
            if lic not in LICENCE_OK:
                refused.append(
                    {
                        'pack': pack_id,
                        'why': ('no PROVENANCE.json' if not lic else f'licence {lic} may not be embedded'),
                    }
                )
                continue
            items = _scan_pack(vend, pack, pdir) if pack else _scan_pack(vend, '', pdir)
            if not items:
                continue
            pv = _preview_index(pdir, pack_id)
            for it in items:
                it['pack'] = pack_id
                it['id'] = f'{pack_id}|{os.path.splitext(os.path.basename(it["rel"]))[0]}'
                it['attrib'] = LICENCE_OK[lic]
                it['pv'] = pv.get(os.path.splitext(os.path.basename(it['rel']))[0].lower())
            packs.append(
                {
                    'id': pack_id,
                    'vendor': vend,
                    'n': _pretty(pack or vend),
                    'licence': lic,
                    'attrib': LICENCE_OK[lic],
                    'quote': quote,
                    'count': len(items),
                }
            )
            all_items.extend(items)

    packs.sort(key=lambda p: (p['vendor'], p['n']))
    for p in packs:
        p['previews'] = sum(1 for i in all_items if i['pack'] == p['id'] and i.get('pv'))
    sections = [
        {
            'g': p['n'],
            'pack': p['id'],
            'licence': p['licence'],
            'attrib': p['attrib'],
            'items': [
                {
                    'id': i['id'],
                    'kind': 'asset',
                    'n': i['n'],
                    'p': dict(
                        {'pack': i['pack'], 'item': os.path.splitext(os.path.basename(i['rel']))[0]},
                        **({'bw': i['dims'][0], 'bh': i['dims'][1], 'bd': i['dims'][2]} if i.get('dims') else {}),
                        **({'tris': i['tris']} if i.get('tris') else {}),
                    ),
                    'u': f'{i["pack"]}/{i["rel"]}',
                    'pv': i.get('pv'),
                    # 'u' stays a pure path: blender_scripts/build_asset_library.py
                    # and render_asset_previews.py join it onto PACKS_ROOT. The
                    # browser gets 'uv', which carries the file's mtime, because
                    # /inspect/arch-asset/ is served max-age=86400 with no ETag —
                    # a rebuilt asset at the same path would otherwise sit behind
                    # the cache for a day (2026-09-23: it did, for the pinas).
                    'uv': f'{i["pack"]}/{i["rel"]}?v={i.get("ver") or 0}',
                    'note': (f'{i["dims"][0]:.2g}x{i["dims"][1]:.2g}x{i["dims"][2]:.2g} m ' if i.get('dims') else '')
                    + (i.get('note') or ''),
                }
                for i in all_items
                if i['pack'] == p['id']
            ],
        }
        for p in packs
    ]
    return {
        'ok': True,
        'packs': packs,
        'groups': sections,
        'refused': refused,
        'count': len(all_items),
        'index': {i['id']: i['rel'] for i in all_items},
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


def packs() -> list[dict]:
    return catalogue()['packs']


# ── file resolution ─────────────────────────────────────────────────────────


def resolve(pack: str, item: str) -> str | None:
    """Absolute path of one catalogued item, or None.

    Resolution goes through the CATALOGUE, never through the request string:
    the client names a pack and an item id, and the only paths reachable are
    ones the scan already found. The realpath check below is therefore a second
    fence, not the first."""
    cat = catalogue()
    rel = cat['index'].get(f'{pack}|{item}')
    if not rel:
        return None
    base = os.path.realpath(os.path.join(PACKS_ROOT, pack))
    full = os.path.realpath(os.path.join(base, rel))
    if not (full == base or full.startswith(base + os.sep)):
        return None
    return full if os.path.isfile(full) else None


def url_for(pack: str, item: str) -> str | None:
    """The path the browser should fetch for one catalogued item.

    Path-based and NOT a query string, because a .gltf names its .bin and its
    textures by RELATIVE uri: the loader resolves them against the document's
    own URL, so `?pack=x&item=y` would send it looking for `?pack=x&scene.bin`.
    A path lets the browser do the resolving correctly and for free."""
    rel = catalogue()['index'].get(f'{pack}|{item}')
    return f'{pack}/{rel}' if rel else None


# A .gltf pulls in its buffer and its textures; nothing else is ever served.
SERVE_EXT = ('.glb', '.gltf', '.bin', '.png', '.jpg', '.jpeg', '.webp', '.ktx2')


def resolve_url(relpath: str) -> str | None:
    """Absolute path for a browser request under the asset route, or None.

    This is the fence for EVERY file the loader pulls, not just the ones the
    catalogue listed — a glTF's own sidecars were never scanned. Three gates:
    no traversal in the request, an extension allowlist, and a realpath that
    must still sit inside the packs root after every symlink is resolved."""
    s = str(relpath or '').strip().lstrip('/')
    if not s or '\\' in s or '..' in s.split('/') or s.startswith('.'):
        return None
    if not s.lower().endswith(SERVE_EXT):
        return None
    full = os.path.realpath(os.path.join(PACKS_ROOT, s))
    if not full.startswith(PACKS_ROOT + os.sep):
        return None
    return full if os.path.isfile(full) else None


MIME = {
    '.glb': 'model/gltf-binary',
    '.gltf': 'model/gltf+json',
    '.bin': 'application/octet-stream',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
    '.ktx2': 'image/ktx2',
}


def mime_for(path: str) -> str:
    return MIME.get(os.path.splitext(path)[1].lower(), 'application/octet-stream')
