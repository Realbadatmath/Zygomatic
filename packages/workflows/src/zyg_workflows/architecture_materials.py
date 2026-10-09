# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""architecture_materials.py — the PBR surface catalogue for the Architecture
Studio's Materials rail (2026-09-01).

The studio shipped with sixteen flat-colour presets: a hex value, a roughness
and a metalness. They are still there and still the default, because a massing
study wants a grey box and not a photograph of concrete. This module adds the
other kind — real measured surfaces from the CC0 ambientCG library — and the
one number that decides whether they look like architecture or like wallpaper:

    SIZE_M — how many METRES of wall one tile of the texture covers.

WHY THAT NUMBER IS THE WHOLE JOB. A brick sheet is a photograph of about
1.5 × 1.45 m of wall. Map it 0..1 across a 4 m wall and the bricks come out
nearly three times life size; map the same sheet across a 0.9 m door and they
come out a third of it, and the two surfaces do not agree at the joint. The
studio already models in metres, so the fix is to hand the client a physical
size per material and let it tile in world space. ambientCG publishes
dimensionX/dimensionY for only 145 of the 460 materials here and zero for the
rest, so the size a surface carries has THREE possible provenances and the rail
says which: `measured` from the vendor, `category-median` learned from the
materials in the same category that were measured, or `assumed-1m` for the six
categories (Marble, Metal, Onyx, Plaster, Porcelain, Rock) where nothing was
measured and there is no median to learn from. An assumed metre must never
read like a measurement.

SECOND VENDOR, ADDED FOR THE METADATA (2026-09-01). Poly Haven's 855 CC0
textures are not more of the same: Poly Haven publishes `dimensions` for 855
of 855, in millimetres. Where ambientCG leaves two thirds of its library on a
learned median or a flat metre, every Poly Haven surface tiles at a size
somebody actually measured. The two vendors share the rail and the same
category groups, so a wall material is found by what it IS rather than by who
published it; `vendor` rides along on every def so the tooltip can say.

Public API:
    catalogue()               -> {'ok', 'groups':[...], 'count', 'defs':{...}}
    resolve_url(relpath)      -> delegated to architecture_assets (same root)

The textures themselves are served by the existing /inspect/arch-asset/ route:
they live under the same mesh_packs root and need the same containment fence,
so giving them a second one would mean two places to get it wrong.
"""

from __future__ import annotations

import json
import os
import time
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
PACKS_ROOT = os.path.realpath(os.path.join(HERE, 'data', 'assets', 'mesh_packs'))
ACG_DIR = os.path.join(PACKS_ROOT, 'ambientcg')
PHT_DIR = os.path.join(PACKS_ROOT, 'polyhaven_tex')
MATERIALS_JSON = os.path.join(ACG_DIR, 'materials.json')
PH_MATERIALS_JSON = os.path.join(PHT_DIR, 'materials.json')
# Every materials.json the rail reads. The cache signature is the max mtime
# across all of them, so a second vendor appearing does not sit invisible
# behind a cache keyed on the first one's timestamp.
ACGD_DIR = os.path.join(PACKS_ROOT, 'ambientcg_decals')
ACGA_DIR = os.path.join(PACKS_ROOT, 'ambientcg_atlas')
SOURCES = (
    ('ambientcg', MATERIALS_JSON),
    ('polyhaven_tex', PH_MATERIALS_JSON),
    ('ambientcg_decals', os.path.join(ACGD_DIR, 'materials.json')),
    ('ambientcg_atlas', os.path.join(ACGA_DIR, 'materials.json')),
)

# The prepared web set writes one file per three.js slot. Anything not in this
# map is not something MeshStandardMaterial can consume.
SLOTS = ('map', 'normalMap', 'roughnessMap', 'metalnessMap', 'aoMap', 'alphaMap')
# Not a three.js slot — the rail's chip. Carried alongside so the client does
# not have to guess a filename.
THUMB = 'thumb'

# A rail grouped by ambientCG's own category names, in the order a building is
# actually made rather than alphabetically.
CATEGORY_ORDER = [
    'Bricks',
    'Concrete',
    'Plaster',
    'Wall',
    'Facade',
    'Wood',
    'Bark',
    'Tiles',
    'Marble',
    'Onyx',
    'Porcelain',
    'Terrazzo',
    'Metal',
    'Roofing',
    'Paving Stones',
    'Asphalt',
    'Rock',
    'Gravel',
    'Sand',
    'Snow',
    'Ground',
    'Grass',
    'Carpet',
    'Fabric',
    'Leather',
    'Decals',
    'Atlas',
]

# Decals and atlases are a different KIND of surface and the rail says so by
# putting them last: a material answers "what is this made of" and tiles, a
# decal is placed once and an atlas is a cut-out sheet for cards. Two things
# follow from that and both ride on the def:
#   tile=False   - repeating a manhole cover across a wall is never wanted
#   alpha_mode   - 'mask' for the hard foliage cutouts (alphaTest, so nothing
#                  has to be depth-sorted) and 'blend' for decals, whose edges
#                  are soft grime and would look chewed by a threshold.
ALPHA_VENDORS = {'ambientcg_decals': 'blend', 'ambientcg_atlas': 'mask'}

# Poly Haven tags an asset with a bag of descriptors ("outdoor", "man made",
# "wall", "brick") rather than one category, so the rail group is DERIVED:
# first match wins and the list is ordered most-specific first. "wall" and
# "floor" sit at the bottom on purpose - they say where a surface goes, not
# what it is, and a brick wall belongs under Bricks with the other bricks.
PH_CATEGORY_RULES = [
    ('brick', 'Bricks'),
    ('cobblestone', 'Paving Stones'),
    ('roofing', 'Roofing'),
    ('asphalt', 'Asphalt'),
    ('road', 'Asphalt'),
    ('tiles', 'Tiles'),
    ('concrete', 'Concrete'),
    ('plaster', 'Plaster'),
    ('plaster-concrete', 'Concrete'),
    ('metal', 'Metal'),
    ('bark', 'Bark'),
    ('raw wood', 'Wood'),
    ('wood', 'Wood'),
    ('sandstone', 'Rock'),
    ('rock', 'Rock'),
    ('gravel', 'Gravel'),
    ('sand', 'Sand'),
    ('snow', 'Snow'),
    ('carpet', 'Carpet'),
    ('leather', 'Leather'),
    ('cotton', 'Fabric'),
    ('wool', 'Fabric'),
    ('fleece', 'Fabric'),
    ('knitted', 'Fabric'),
    ('denim', 'Fabric'),
    ('hessian', 'Fabric'),
    ('crepe', 'Fabric'),
    ('jacquard', 'Fabric'),
    ('satin', 'Fabric'),
    ('corduroy', 'Fabric'),
    ('suede', 'Fabric'),
    ('woven', 'Fabric'),
    ('velvet', 'Fabric'),
    ('fur', 'Fabric'),
    ('stretchy', 'Fabric'),
    ('fabric', 'Fabric'),
    ('terrain', 'Ground'),
    ('wall', 'Wall'),
    ('floor', 'Ground'),
]


def _ph_group(cats) -> str:
    have = {str(c).lower() for c in (cats or [])}
    for tag, group in PH_CATEGORY_RULES:
        if tag in have:
            return group
    return 'Other'


# Where a material's physical size came from, said plainly in the tooltip. An
# assumed metre is a guess and must not read like a measurement.
_SIZE_NOTE = {'measured': '', 'category-median': ' (category median)', 'assumed-1m': ' (size unpublished — assumed)'}

_CACHE = {'ts': 0.0, 'mtime': 0.0, 'data': None}
_CACHE_TTL = 30.0


def _pretty(name: str, aid: str) -> str:
    return name or aid


def _load(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _sig() -> float:
    """Newest mtime across every vendor's materials.json.

    A max rather than one file's mtime, because the rail now has two sources
    and keying the cache on the first one means the second can be rebuilt and
    stay invisible for the life of the process."""
    m = 0.0
    for _, path in SOURCES:
        try:
            m = max(m, os.path.getmtime(path))
        except OSError as _exc:
            _zyg_log.debug('mtime scan skipped a file: %s', _exc)
    return m


# ── tone ────────────────────────────────────────────────────────────────────
# A surface's NAME does not say how light it is: ambientCG's Marble006 is a
# black marble and Marble021 a white one, so a search for "white marble" that
# reads only words hands the assistant the black one. The one honest source is
# the albedo map itself, so every entry carries the mean luminance of its own
# map and the bucket that luminance falls in. Measuring 1,500 JPEGs costs about
# five seconds, so the answer is cached per id against the map file's mtime and
# a rescan of an unchanged library costs nothing.
TONE_DIR = os.path.join(HERE, 'data', 'architecture')
TONE_CACHE = os.path.join(TONE_DIR, 'materials_tone.json')
TONE_BUCKETS = ((40.0, 'black'), (90.0, 'dark'), (150.0, 'mid'), (200.0, 'light'))
TONE_WORDS = ('black', 'dark', 'mid', 'light', 'white')


def tone_of(lum: float) -> str:
    """The bucket a mean luminance (0..255) falls in."""
    for edge, name in TONE_BUCKETS:
        if lum < edge:
            return name
    return 'white'


def _map_path(d: dict) -> str:
    rel = (d.get('maps') or {}).get('map')
    return os.path.join(PACKS_ROOT, rel) if rel else ''


def _measure_lum(path: str) -> float | None:
    try:
        from PIL import Image, ImageStat

        with Image.open(path) as im:
            im.draft('L', (64, 64))  # JPEG decoder shortcut, same mean
            g = im.convert('L')
            g.thumbnail((64, 64))
            return round(float(ImageStat.Stat(g).mean[0]), 1)
    except Exception:  # noqa: BLE001 — a surface we cannot read has no tone
        return None


def _apply_tone(defs: dict) -> None:
    """Stamp 'lum' and 'tone' on every def, measuring only what changed."""
    cached = _load(TONE_CACHE).get('entries') or {}
    out, dirty = {}, False
    for kind, d in defs.items():
        path = _map_path(d)
        try:
            mt = round(os.path.getmtime(path), 3) if path else 0.0
        except OSError:
            mt = 0.0
        old = cached.get(kind)
        if isinstance(old, dict) and old.get('mtime') == mt:
            row = old
        else:
            lum = _measure_lum(path) if path else None
            row = {'lum': lum, 'tone': tone_of(lum) if lum is not None else '', 'mtime': mt}
            dirty = True
        out[kind] = row
        d['lum'] = row.get('lum')
        d['tone'] = row.get('tone') or ''
    if dirty or len(out) != len(cached):
        try:
            os.makedirs(TONE_DIR, exist_ok=True)
            tmp = TONE_CACHE + '.tmp'
            with open(tmp, 'w') as f:
                json.dump({'buckets': {n: e for e, n in TONE_BUCKETS}, 'entries': out}, f)
            os.replace(tmp, TONE_CACHE)
        except OSError as _exc:
            _zyg_log.warning('tone cache write failed, tones will be recomputed next time: %s', _exc)


def _def_from(aid: str, r: dict, vendor: str, prefix: str) -> tuple[str, dict, str] | None:
    """One rail entry, whichever vendor published it. Returns (kind, def, group)."""
    allmaps = r.get('maps') or {}
    maps = {k: v for k, v in allmaps.items() if k in SLOTS}
    thumb = allmaps.get(THUMB)
    if 'map' not in maps:
        return None  # a surface with no albedo is not one
    # Licence is fail-closed here for the same reason it is on the model
    # catalogue: an un-evidenced surface must not become listable by being
    # dropped in a directory.
    if str(r.get('licence', '')).upper() not in ('CC0-1.0', 'CC0', 'PUBLIC-DOMAIN'):
        return None
    sx, sy = (r.get('size_m') or [1.0, 1.0])[:2]
    kind = prefix + aid
    if vendor == 'ambientcg':
        group = r.get('category') or 'Other'
    elif vendor in ALPHA_VENDORS:
        group = r.get('group') or 'Other'
    else:
        group = _ph_group(r.get('categories'))
    d = {
        'n': _pretty(r.get('name'), aid),
        'vendor': vendor,
        'maps': {k: f'{vendor}/{v}' for k, v in maps.items()},
        'thumb': f'{vendor}/{thumb}' if thumb else None,
        'size_m': [float(sx or 1.0), float(sy or sx or 1.0)],
        'measured': bool(r.get('size_measured')),
        'size_source': r.get('size_source') or ('measured' if r.get('size_measured') else 'assumed-1m'),
        'licence': 'CC0-1.0',
        'src': r.get('source_url', ''),
        # The flat presets carry col/rough/metal and the client falls back
        # to them until the textures arrive, so a textured material still
        # needs a plausible base colour and a roughness.
        'col': '#9a9a94',
        'rough': 1.0 if 'roughnessMap' in maps else 0.85,
        'metal': 0.0 if 'metalnessMap' not in maps else 1.0,
    }
    if vendor in ALPHA_VENDORS:
        d['tile'] = bool(r.get('tile', False))
        d['alpha_mode'] = ALPHA_VENDORS[vendor] if 'alphaMap' in maps else None
    return kind, d, group


# Which prefix each vendor's kind carries. The ambientCG one is `acg_` and
# CANNOT change: it is written into every drawing that has ever placed a
# material, and a drawing stores the kind, not the file.
VENDOR_PREFIX = {'ambientcg': 'acg_', 'polyhaven_tex': 'pht_', 'ambientcg_decals': 'acgd_', 'ambientcg_atlas': 'acga_'}


def _build() -> dict:
    by_cat, defs, per_vendor = {}, {}, {}
    for vendor, path in SOURCES:
        recs = _load(path)
        prefix = VENDOR_PREFIX[vendor]
        n = 0
        for aid, r in recs.items():
            made = _def_from(aid, r, vendor, prefix)
            if not made:
                continue
            kind, d, group = made
            defs[kind] = d
            by_cat.setdefault(group, []).append((kind, d))
            n += 1
        per_vendor[vendor] = n

    _apply_tone(defs)
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    groups = []
    for cat in sorted(by_cat, key=lambda c: (order.get(c, 999), c)):
        items = sorted(by_cat[cat], key=lambda kv: kv[1]['n'])
        groups.append(
            {
                'g': cat,
                'items': [
                    {
                        'id': f'acgmat:{k}',
                        'kind': k,
                        'n': d['n'],
                        'p': {
                            'col': d['col'],
                            'rough': d['rough'],
                            'metal': d['metal'],
                            'maps': d['maps'],
                            'thumb': d['thumb'],
                            'size_m': d['size_m'],
                            'tile': d.get('tile', True),
                            'alpha': d.get('alpha_mode'),
                            'tone': d.get('tone', ''),
                            'lum': d.get('lum'),
                        },
                        'note': (
                            f'{d["size_m"][0]:g}x{d["size_m"][1]:g} m'
                            + _SIZE_NOTE.get(d['size_source'], '')
                            + ('' if d.get('tile', True) else ', placed once')
                        ),
                    }
                    for k, d in items
                ],
            }
        )
    return {
        'ok': True,
        'groups': groups,
        'defs': defs,
        'mtime': _sig(),
        'vendors': per_vendor,
        'count': sum(len(g['items']) for g in groups),
        'alpha': sum(1 for d in defs.values() if d.get('alpha_mode')),
        'measured': sum(1 for d in defs.values() if d['measured']),
    }


def catalogue() -> dict:
    now = time.time()
    if _CACHE['data'] is not None and now - _CACHE['ts'] < _CACHE_TTL:
        return _CACHE['data']
    mtime = _sig()
    if _CACHE['data'] is not None and mtime == _CACHE['mtime']:
        _CACHE['ts'] = now
        return _CACHE['data']
    data = _build()
    _CACHE.update({'ts': now, 'mtime': data.get('mtime', 0.0), 'data': data})
    return data
