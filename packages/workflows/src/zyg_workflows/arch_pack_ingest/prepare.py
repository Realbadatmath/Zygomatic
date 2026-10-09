# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""arch_pack_ingest.prepare — the Poly Haven texture/HDRI web sets and the ambientCG decal
and atlas packs (the OPACITY-map surfaces).

Moved verbatim out of arch_pack_ingest.py (lines 858-1143) when that 2,019-line
module became this package; no logic was changed.
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from .common import PH_API, ACG_API, WORKERS, _get_json, _download
from .ambientcg import _acg_downloads, ACG_MAPS, WEB_RES, WEB_QUALITY, THUMB_RES, THUMB_QUALITY, acg_dimensions

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def ph_tex_prepare(root: str) -> dict:
    """Downsample the 2K masters into the 1K web set + a 320 px rail chip.

    Same derivative shape ambientCG's materials get, for the same reason: a
    WebGL viewport cannot use a 2K albedo per surface and the rail draws a
    column of chips. The 2K files STAY as the masters — they are what the
    registry hashed and what Blender loads."""
    from PIL import Image

    reg = json.load(open(os.path.join(root, 'registry.json')))
    made, failed = {}, []

    def one(aid):
        rec = reg[aid]
        web = os.path.join(root, aid, 'web')
        maps = {}
        try:
            for rel, _f in (rec.get('files') or {}).items():
                slot = rel[:-4]  # 'map.jpg' -> 'map'
                src = os.path.join(root, aid, rel)
                if not os.path.isfile(src):
                    continue
                os.makedirs(web, exist_ok=True)
                out_path = os.path.join(web, rel)
                if not os.path.isfile(out_path):
                    im = Image.open(src).convert('RGB')
                    if max(im.size) > WEB_RES:
                        im = im.resize((WEB_RES, WEB_RES), Image.LANCZOS)
                    im.save(out_path, 'JPEG', quality=WEB_QUALITY, optimize=True)
                maps[slot] = f'{aid}/web/{rel}'
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

    with cf.ThreadPoolExecutor(max(4, WORKERS // 2)) as ex:
        for n, (aid, maps) in enumerate(ex.map(one, sorted(reg)), 1):
            if not maps or 'map' not in maps:
                failed.append(aid)
                continue
            made[aid] = dict(reg[aid], maps=maps)
            if n % 100 == 0:
                _zyg_log.info(f'    {n}/{len(reg)}…')
    if failed:
        _zyg_log.info(f'  no usable maps for {len(failed)}: {", ".join(failed[:8])}')
    with open(os.path.join(root, 'materials.json'), 'w') as f:
        json.dump(made, f, indent=1)
    nb = sum(
        os.path.getsize(os.path.join(root, p_))
        for r in made.values()
        for p_ in r['maps'].values()
        if os.path.isfile(os.path.join(root, p_))
    )
    return {
        'prepared': len(made),
        'failed': len(failed),
        'measured': sum(1 for r in made.values() if r.get('size_measured')),
        'web_bytes': nb,
    }


def ph_hdri_prepare(root: str) -> dict:
    """A picture per HDRI, from Poly Haven's own tonemapped thumbnail.

    Not rendered here on purpose. A .hdr is scene-referred float data with no
    single correct exposure, so any thumbnail this box made would be one
    arbitrary tonemap of it; the site's own thumbnail is the image the
    photographer signed off, is the picture a person will have seen if they
    have seen the HDRI at all, and is CC0 like everything else in the set."""
    from PIL import Image

    reg_path = os.path.join(root, 'registry.json')
    reg = json.load(open(reg_path))
    meta = _get_json(f'{PH_API}/assets?t=hdris')
    made, failed = 0, []

    def one(aid):
        url = (meta.get(aid) or {}).get('thumbnail_url')
        if not url:
            return aid, None
        dest = os.path.join(root, aid, 'thumb.jpg')
        if os.path.isfile(dest):
            return aid, 'thumb.jpg'
        ok, _ = _download(url, dest, None)
        if not ok:
            return aid, None
        try:
            im = Image.open(dest).convert('RGB')
            if max(im.size) > 512:
                im.thumbnail((512, 512), Image.LANCZOS)
                im.save(dest, 'JPEG', quality=THUMB_QUALITY, optimize=True)
        except Exception:  # noqa: BLE001
            return aid, None
        return aid, 'thumb.jpg'

    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for aid, rel in ex.map(one, sorted(reg)):
            if rel:
                reg[aid]['thumb'] = f'{aid}/{rel}'
                made += 1
            else:
                failed.append(aid)
    with open(reg_path, 'w') as f:
        json.dump(reg, f, indent=1)
    return {'thumbs': made, 'failed': len(failed)}


# -- ambientCG decals and atlases --------------------------------------------
#
# A different KIND of surface, not more of the same one. A material answers
# "what is this wall made of" and tiles; a decal is a manhole cover, a stain,
# a crack, a road marking, placed ONCE at a known size; an atlas is a sheet of
# cut-out foliage to be mapped onto cards. What they have that no ambientCG
# material has is an OPACITY map, and that is what makes them worth a separate
# path rather than 187 more rows in the Materials rail.
#
# PNG, NOT JPG, AND IT COSTS 3.5 GB TO SAY SO. The alpha cutout IS the asset
# here; a JPEG mask fringes along every leaf edge and the fringe is exactly
# what a viewer looks at. 2K-PNG for both classes is 4.9 GB against 1.9 GB for
# JPG - measured, not assumed - and one decal (of 127) publishes no 2K-PNG at
# all, so JPG is the documented fallback for that one rather than a silent
# downgrade.

ACG_ALPHA_KINDS = {
    # api type -> (pack dir, rail group, human name)
    'Decal': ('ambientcg_decals', 'Decals', 'ambientCG decals'),
    'Atlas': ('ambientcg_atlas', 'Atlas', 'ambientCG atlases'),
}


def acg_alpha_plan(kind: str, res_pref=('2K-PNG', '2K-JPG')) -> list[dict]:
    url = f'{ACG_API}?type={urllib.parse.quote(kind)}&limit=500&include=downloadData,displayData'
    d = _get_json(url)
    out, fallback = [], []
    for a in d.get('foundAssets', []):
        aid = a.get('assetId')
        if not aid:
            continue
        dl = _acg_downloads(a)
        pick = attr = None
        for want in res_pref:
            pick = next((f for f in dl if f.get('attribute') == want), None)
            if pick:
                attr = want
                break
        if not pick:
            continue
        if attr != res_pref[0]:
            fallback.append(aid)
        out.append(
            {
                'id': aid,
                'category': ACG_ALPHA_KINDS[kind][1],
                'name': a.get('displayName') or aid,
                'url': pick['fullDownloadPath'],
                'size': pick.get('size', 0),
                'attribute': attr,
                'file': pick.get('fileName') or f'{aid}_{attr}.zip',
            }
        )
    if fallback:
        _zyg_log.info(f'  no {res_pref[0]} for {len(fallback)}, took {res_pref[1]}: {", ".join(fallback)}')
    return out


# Opacity is the whole point of these two classes, so it gets a slot the
# material path has no use for. three.js reads alphaMap from the GREEN channel,
# which a greyscale PNG satisfies.
ACG_ALPHA_MAPS = dict(ACG_MAPS, Opacity='alphaMap')


def acg_alpha_prepare(root: str, group: str) -> dict:
    """Unpack to the 1K web set. The alpha stays PNG; everything else is JPEG.

    Writing the mask as JPEG would undo the reason the PNG masters were taken
    in the first place - and it is one greyscale image per asset, so the cost
    of keeping it lossless is a few megabytes across the whole set."""
    import io
    import zipfile
    from PIL import Image

    reg = json.load(open(os.path.join(root, 'registry.json')))
    ids = sorted(reg)
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
                for suffix, slot in ACG_ALPHA_MAPS.items():
                    hit = next(
                        (
                            n
                            for n in names
                            if n.lower().endswith(f'_{suffix.lower()}.png')
                            or n.lower().endswith(f'_{suffix.lower()}.jpg')
                        ),
                        None,
                    )
                    if not hit:
                        continue
                    os.makedirs(web, exist_ok=True)
                    is_alpha = slot == 'alphaMap'
                    out_name = f'{slot}.png' if is_alpha else f'{slot}.jpg'
                    out_path = os.path.join(web, out_name)
                    if not os.path.isfile(out_path):
                        with zf.open(hit) as fh:
                            im = Image.open(io.BytesIO(fh.read()))
                            im = im.convert('L' if is_alpha else 'RGB')
                            if max(im.size) > WEB_RES:
                                im = im.resize((WEB_RES, WEB_RES), Image.LANCZOS)
                            if is_alpha:
                                im.save(out_path, 'PNG', optimize=True)
                            else:
                                im.save(out_path, 'JPEG', quality=WEB_QUALITY, optimize=True)
                    maps[slot] = f'{aid}/web/{out_name}'
                if 'map' in maps:
                    th = os.path.join(web, 'thumb.png')
                    if not os.path.isfile(th):
                        col = Image.open(os.path.join(web, 'map.jpg')).convert('RGBA')
                        # The chip has to show the CUTOUT, not the sheet. A
                        # foliage atlas composited on white reads as a green
                        # square and every one of the 60 looks the same.
                        if 'alphaMap' in maps:
                            al = Image.open(os.path.join(web, 'alphaMap.png')).convert('L')
                            col.putalpha(al.resize(col.size, Image.LANCZOS))
                        col.thumbnail((THUMB_RES, THUMB_RES), Image.LANCZOS)
                        col.save(th, 'PNG', optimize=True)
                    maps['thumb'] = f'{aid}/web/thumb.png'
        except Exception as e:  # noqa: BLE001
            _zyg_log.info(f'  SKIP {aid}: {type(e).__name__}: {e}')
            return aid, None
        return aid, maps

    made, failed, no_alpha = {}, [], []
    with cf.ThreadPoolExecutor(max(4, WORKERS // 2)) as ex:
        for n, (aid, maps) in enumerate(ex.map(one, ids), 1):
            if not maps or 'map' not in maps:
                failed.append(aid)
                continue
            if 'alphaMap' not in maps:
                no_alpha.append(aid)
            x, y = dims.get(aid, (None, None))
            made[aid] = dict(
                reg[aid],
                maps=maps,
                size_m=[x or 1.0, y or x or 1.0],
                size_source='measured' if x else 'assumed-1m',
                size_measured=bool(x),
                # A decal is placed once and an atlas is mapped
                # onto cards. Neither tiles, and repeating one
                # across a wall is never what was wanted.
                tile=False,
                group=group,
            )
            if n % 25 == 0:
                _zyg_log.info(f'    {n}/{len(ids)}...')
    if failed:
        _zyg_log.info(f'  no usable maps for {len(failed)}: {", ".join(failed[:8])}')
    if no_alpha:
        _zyg_log.info(f'  NO OPACITY MAP for {len(no_alpha)}: {", ".join(no_alpha[:8])}')
    with open(os.path.join(root, 'materials.json'), 'w') as f:
        json.dump(made, f, indent=1)
    return {
        'prepared': len(made),
        'failed': len(failed),
        'with_alpha': len(made) - len(no_alpha),
        'measured': sum(1 for r in made.values() if r['size_measured']),
    }
