# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""build_hdri_library.py — the CC0 HDRIs as a Blender WORLD asset library.

    blender -b --factory-startup --python build_hdri_library.py

WHY A THIRD LIBRARY. The mesh packs give Blender things to put in a scene and
the material packs give them surfaces; neither lights anything. Until this ran,
every render out of this box started from Blender's flat grey world, which
gives every curved surface the same highlight and is the single clearest
difference between a massing study and a photograph. 992 CC0 environments are
now one drag from the Asset Browser.

A World, not an Image. Blender's Asset Browser can mark a World datablock as an
asset, and dragging one replaces the scene's lighting in a single action — as
opposed to an image asset, which lands as a texture nobody has wired to
anything. The node tree is the minimum that is actually correct:

    Texture Coordinate (Generated) -> Mapping -> Environment Texture -> Background

The Mapping node is there so the rotation is a control rather than a re-wire —
the one thing every user of an HDRI wants to change is which way the sun is.

THREE THINGS THAT WOULD LOOK FINE AND BE WRONG.

  * An .hdr is scene-referred float data and MUST stay Linear Rec.709. Loading
    it and leaving the colour space alone works only because that is already
    Blender's default for a float image; setting it to sRGB "to be safe" would
    double-decode the sky and blow the sun out.

  * Images are NOT packed. 992 environments at 2K come to 5.9 GB; packed, the
    .blend would be a second copy of all of it. They are referenced, and the
    ingest's files stay the only copy.

  * A World with no user is purged on save. asset_mark() is not a user, so
    every world gets use_fake_user — the same trap that returned an empty
    material library the first time.

Previews are LOADED from the ingest's thumbnails (Poly Haven's own tonemap),
because ed.lib_id_generate_preview needs a GPU and quietly does nothing in
background mode.
"""

import json
import os
import uuid

import bpy
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
HDRI = os.path.join(CREWS, 'data', 'assets', 'mesh_packs', 'polyhaven_hdri')
LIB_ROOT = os.path.join(CREWS, 'data', 'assets', 'blender_library')
OUT = os.path.join(LIB_ROOT, 'polyhaven_hdris.blend')

# Poly Haven tags an HDRI with a bag of descriptors. The catalogue drawer is
# derived from it the same way the surfaces' is, most-specific first, so that
# "studio" does not end up filed under "indoor" with the kitchens.
CATEGORY_RULES = [
    ('studio', 'Studio'),
    ('skies', 'Skies'),
    ('night', 'Night'),
    ('sunrise-sunset', 'Sunrise & sunset'),
    ('urban', 'Urban'),
    ('nature', 'Nature'),
    ('indoor', 'Indoor'),
    ('artificial light', 'Indoor'),
    ('outdoor', 'Outdoor'),
]


def group_of(cats) -> str:
    have = {str(c).lower() for c in (cats or [])}
    for tag, group in CATEGORY_RULES:
        if tag in have:
            return group
    return 'Other'


def write_catalogs(cats):
    p = os.path.join(LIB_ROOT, 'blender_assets.cats.txt')
    merged = {}
    if os.path.isfile(p):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith(('VERSION', '#')):
                    continue
                parts = line.split(':')
                if len(parts) >= 2:
                    merged[parts[1]] = parts[0]
    merged.update(cats)
    with open(p, 'w') as f:
        f.write(
            '\n'.join(
                ['VERSION 1', ''] + [f'{c}:{path}:{path.replace("/", "-")}' for path, c in sorted(merged.items())]
            )
            + '\n'
        )


def build_world(aid, rec):
    hdr = rec.get('hdr')
    if not hdr:
        return None
    path = os.path.join(HDRI, aid, hdr)
    if not os.path.isfile(path):
        return None

    w = bpy.data.worlds.new(rec.get('name') or aid)
    w.use_nodes = True
    nt = w.node_tree
    nodes, links = nt.nodes, nt.links
    for n in list(nodes):
        nodes.remove(n)

    out = nodes.new('ShaderNodeOutputWorld')
    out.location = (300, 0)
    bg = nodes.new('ShaderNodeBackground')
    bg.location = (100, 0)
    env = nodes.new('ShaderNodeTexEnvironment')
    env.location = (-200, 0)
    env.image = bpy.data.images.load(path, check_existing=True)
    # Float .hdr data is already Linear Rec.709 by default; assert it rather
    # than trust it, because a wrong colour space here is invisible until the
    # sun is twice as bright as it should be.
    env.image.colorspace_settings.name = 'Linear Rec.709'
    mapping = nodes.new('ShaderNodeMapping')
    mapping.location = (-450, 0)
    coord = nodes.new('ShaderNodeTexCoord')
    coord.location = (-650, 0)

    links.new(coord.outputs['Generated'], mapping.inputs['Vector'])
    links.new(mapping.outputs['Vector'], env.inputs['Vector'])
    links.new(env.outputs['Color'], bg.inputs['Color'])
    links.new(bg.outputs['Background'], out.inputs['Surface'])
    return w


def main():
    with open(os.path.join(HDRI, 'registry.json')) as f:
        recs = json.load(f)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    os.makedirs(LIB_ROOT, exist_ok=True)

    made, previews, cats, skipped = 0, 0, {}, []
    for aid in sorted(recs):
        rec = recs[aid]
        try:
            w = build_world(aid, rec)
        except Exception as e:  # noqa: BLE001
            print(f'  SKIP {aid}: {type(e).__name__}: {e}')
            skipped.append(aid)
            continue
        if w is None:
            skipped.append(aid)
            continue
        group = group_of(rec.get('categories'))
        cid = cats.setdefault(
            f'polyhaven_hdri/{group}', str(uuid.uuid5(uuid.NAMESPACE_URL, f'zygomatic:hdri-cat:polyhaven_hdri/{group}'))
        )
        w.asset_mark()
        ad = w.asset_data
        ad.catalog_id = cid
        ad.description = f'{rec.get("name", aid)} - Poly Haven HDRI, CC0-1.0, {rec.get("resolution", "2k")}'
        ad.tags.new('polyhaven')
        ad.tags.new('CC0-1.0')
        ad.tags.new(group)
        for t in (rec.get('categories') or [])[:6]:
            ad.tags.new(str(t))
        thumb = rec.get('thumb')
        if thumb:
            tp = os.path.join(HDRI, thumb)
            if os.path.isfile(tp):
                try:
                    with bpy.context.temp_override(id=w):
                        bpy.ops.ed.lib_id_load_custom_preview(filepath=tp)
                    previews += 1
                except Exception as _exc:  # noqa: BLE001
                    _zyg_log.warning('custom preview not loaded for this world: %s', _exc)
        made += 1
        if made % 100 == 0:
            print(f'    {made}...', flush=True)

    write_catalogs(cats)
    # asset_mark() is not a user. Without this the library saves empty.
    for w in bpy.data.worlds:
        w.use_fake_user = True
    bpy.ops.wm.save_as_mainfile(filepath=OUT, compress=True)
    packed = sum(1 for i in bpy.data.images if i.packed_file)
    print(
        '@@RESULT@@ '
        + repr(
            {
                'worlds': made,
                'previews': previews,
                'catalogs': len(cats),
                'skipped': len(skipped),
                'packed_images': packed,
                'blend': OUT,
                'bytes': os.path.getsize(OUT),
            }
        )
    )


if __name__ == '__main__':
    main()
