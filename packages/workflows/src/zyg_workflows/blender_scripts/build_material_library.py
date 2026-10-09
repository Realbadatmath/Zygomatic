# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""build_material_library.py — the CC0 surfaces as a Blender material library.

    blender -b --factory-startup --python build_material_library.py -- --vendor ambientcg
    blender -b --factory-startup --python build_material_library.py -- --vendor polyhaven_tex

The Architecture Studio loads these surfaces over HTTP as 1K JPEGs. Blender
gets the SAME materials wired as real Principled BSDF node trees, marked as
assets and filed in a catalogue, so the two halves of the pipeline shade a wall
the same way.

FOUR THINGS THAT MAKE IT CORRECT RATHER THAN MERELY PRESENT.

  * Real-world scale, from the same number. Every material is driven by
    Texture Coordinate → **Object** through a Mapping node scaled to
    1/size_m, so one tile covers the physical size ambientCG published (or the
    category median the ingest learned). This is the Blender-side twin of the
    studio's metre-space UVs.

  * **Box projection**, blend 0.2. The studio does planar projection per
    vertex and seams on curved surfaces; Blender's image node can box-project
    and blend across the axis change, so domes and columns come out clean.
    Same intent, better tool.

  * **Non-colour data.** The normal, roughness and metalness maps are set to
    Non-Color. Left on sRGB they are silently gamma-decoded and the surface
    reads flat and too smooth — the exact bug that is invisible until you
    compare against a reference.

  * Previews are LOADED from the ingest's thumbnails, because
    `ed.lib_id_generate_preview` needs a GPU and quietly does nothing in
    background mode.

TWO VENDORS, AND THEY ARE FED DIFFERENT FILES ON PURPOSE. ambientCG's masters
live inside the 2K zips the ingest hashed, so Blender is wired to the unpacked
1K web set - the only copy on disk. Poly Haven's 2K masters ARE on disk, flat,
one JPEG per slot, so Blender gets those and the 1K web set stays what it was
built for: the browser. Same node tree either way; the resolution differs
because what is available differs, not because anybody preferred it.

Textures are referenced, never packed — the 2K masters and the 1K web set both
stay where the ingest hashed them.
"""

import json
import os
import sys
import uuid

import bpy
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
PACKS = os.path.join(CREWS, 'data', 'assets', 'mesh_packs')
ACG = os.path.join(PACKS, 'ambientcg')
LIB_ROOT = os.path.join(CREWS, 'data', 'assets', 'blender_library')

# vendor -> (pack dir, output .blend, which map set to wire)
#   'web'    the prepared 1K derivatives (ambientCG: the masters are zipped)
#   'master' the 2K files themselves     (Poly Haven: they are already flat)
VENDORS = {
    'ambientcg': (ACG, 'ambientcg_materials.blend', 'web'),
    'polyhaven_tex': (os.path.join(PACKS, 'polyhaven_tex'), 'polyhaven_materials.blend', 'master'),
    'ambientcg_decals': (os.path.join(PACKS, 'ambientcg_decals'), 'ambientcg_decals.blend', 'web'),
    'ambientcg_atlas': (os.path.join(PACKS, 'ambientcg_atlas'), 'ambientcg_atlas.blend', 'web'),
}

# Decals and atlases are not tiling surfaces, so they are coordinated and
# blended differently. 'CLIP' for the cut-out sheets (a leaf edge is binary and
# a threshold needs no sorting); 'BLEND' for decals, whose edges are soft.
ALPHA_VENDORS = {'ambientcg_decals': 'BLEND', 'ambientcg_atlas': 'CLIP'}

# three.js slot -> (Principled input, is colour data)
WIRING = [
    ('map', 'Base Color', True),
    ('roughnessMap', 'Roughness', False),
    ('metalnessMap', 'Metallic', False),
]


def load_image(path):
    img = bpy.data.images.get(os.path.basename(path))
    if img is None or bpy.path.abspath(img.filepath) != path:
        img = bpy.data.images.load(path, check_existing=True)
    return img


def set_blend(mat, mode):
    """Blender 4.2 replaced material.blend_method with surface_render_method
    and the two spell the same intent differently. Set whichever exists rather
    than assuming a version - a wrong guess here shows every cut-out as an
    opaque square and nothing reports it."""
    if hasattr(mat, 'surface_render_method'):
        mat.surface_render_method = 'DITHERED' if mode == 'CLIP' else 'BLENDED'
    if hasattr(mat, 'blend_method'):
        mat.blend_method = mode
    if mode == 'CLIP' and hasattr(mat, 'alpha_threshold'):
        mat.alpha_threshold = 0.5


def build_material(aid, rec, root, mapset, tiles=True):
    maps = rec.get('maps') or {}
    if mapset == 'master':
        # 'aid/web/map.jpg' -> 'aid/map.jpg'. The web set is a derivative of
        # exactly these files, so the master path is the same name one
        # directory up; fall back to the derivative if a master is missing.
        maps = {
            k: (v.replace('/web/', '/') if os.path.isfile(os.path.join(root, v.replace('/web/', '/'))) else v)
            for k, v in maps.items()
        }
    if 'map' not in maps:
        return None
    sx, sy = (rec.get('size_m') or [1.0, 1.0])[:2]
    sx, sy = float(sx or 1.0), float(sy or sx or 1.0)

    mat = bpy.data.materials.new(rec.get('name') or aid)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    bsdf = next(n for n in nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.location = (300, 0)

    coord = nodes.new('ShaderNodeTexCoord')
    coord.location = (-900, 0)
    mapping = nodes.new('ShaderNodeMapping')
    mapping.location = (-700, 0)
    if tiles:
        # One tile per physical size. Object coordinates are the object's own
        # metres, so this is the same arithmetic the studio does in UV space.
        mapping.inputs['Scale'].default_value = (1.0 / sx, 1.0 / sy, 1.0 / sx)
        links.new(coord.outputs['Object'], mapping.inputs['Vector'])
    else:
        # A decal is placed once on a face, so it follows the mesh's own UV
        # layout at 1:1. Driving it from object metres like a tiling surface
        # would repeat a manhole cover across the wall it is on.
        links.new(coord.outputs['UV'], mapping.inputs['Vector'])

    y = 300
    for slot, socket, is_colour in WIRING:
        rel = maps.get(slot)
        if not rel:
            continue
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            continue
        tex = nodes.new('ShaderNodeTexImage')
        tex.image = load_image(path)
        if tiles:
            tex.projection = 'BOX'
            tex.projection_blend = 0.2
        else:
            tex.extension = 'CLIP'
        tex.location = (-450, y)
        if not is_colour:
            tex.image.colorspace_settings.name = 'Non-Color'
        links.new(mapping.outputs['Vector'], tex.inputs['Vector'])
        links.new(tex.outputs['Color'], bsdf.inputs[socket])
        y -= 300

    if maps.get('alphaMap'):
        path = os.path.join(root, maps['alphaMap'])
        if os.path.isfile(path):
            tex = nodes.new('ShaderNodeTexImage')
            tex.image = load_image(path)
            tex.image.colorspace_settings.name = 'Non-Color'
            if not tiles:
                tex.extension = 'CLIP'
            else:
                tex.projection = 'BOX'
                tex.projection_blend = 0.2
            tex.location = (-450, y)
            links.new(mapping.outputs['Vector'], tex.inputs['Vector'])
            links.new(tex.outputs['Color'], bsdf.inputs['Alpha'])
            y -= 300

    if maps.get('normalMap'):
        path = os.path.join(root, maps['normalMap'])
        if os.path.isfile(path):
            tex = nodes.new('ShaderNodeTexImage')
            tex.image = load_image(path)
            tex.image.colorspace_settings.name = 'Non-Color'
            if tiles:
                tex.projection = 'BOX'
                tex.projection_blend = 0.2
            else:
                tex.extension = 'CLIP'
            tex.location = (-450, y)
            nm = nodes.new('ShaderNodeNormalMap')
            nm.location = (-150, y)
            links.new(mapping.outputs['Vector'], tex.inputs['Vector'])
            links.new(tex.outputs['Color'], nm.inputs['Color'])
            links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])
    return mat


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


def main():
    import argparse

    argv = sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument('--vendor', default='ambientcg', choices=sorted(VENDORS))
    a = ap.parse_args(argv)
    root, out_name, mapset = VENDORS[a.vendor]
    out = os.path.join(LIB_ROOT, out_name)

    with open(os.path.join(root, 'materials.json')) as f:
        recs = json.load(f)

    # The rail group for a Poly Haven surface is DERIVED from its tag bag, and
    # the derivation lives in architecture_materials. Importing it rather than
    # copying the rules is the point: Blender's catalogue and the studio's rail
    # must not be able to disagree about which drawer a brick lives in.
    sys.path.insert(0, CREWS)
    from zyg_workflows import architecture_materials as am

    tiles = a.vendor not in ALPHA_VENDORS

    def group_of(rec):
        if a.vendor == 'ambientcg':
            return rec.get('category') or 'Other'
        if a.vendor in ALPHA_VENDORS:
            return rec.get('group') or 'Other'
        return am._ph_group(rec.get('categories'))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    os.makedirs(LIB_ROOT, exist_ok=True)

    made, previews, cats = 0, 0, {}
    for aid in sorted(recs):
        rec = recs[aid]
        cat_name = group_of(rec)
        try:
            mat = build_material(aid, rec, root, mapset, tiles)
        except Exception as e:  # noqa: BLE001
            print(f'  SKIP {aid}: {type(e).__name__}: {e}')
            continue
        if mat is None:
            continue
        if not tiles and (rec.get('maps') or {}).get('alphaMap'):
            set_blend(mat, ALPHA_VENDORS[a.vendor])
        cid = cats.setdefault(
            f'{a.vendor}/{cat_name}', str(uuid.uuid5(uuid.NAMESPACE_URL, f'zygomatic:mat-cat:{a.vendor}/{cat_name}'))
        )
        mat.asset_mark()
        ad = mat.asset_data
        ad.catalog_id = cid
        src = rec.get('size_source', 'assumed-1m')
        ad.description = (
            f'{rec.get("name", aid)} - {a.vendor}, CC0-1.0, {rec["size_m"][0]:g}x{rec["size_m"][1]:g} m ({src})'
        )
        ad.tags.new(a.vendor)
        ad.tags.new('CC0-1.0')
        ad.tags.new(cat_name)
        thumb = (rec.get('maps') or {}).get('thumb')
        if thumb:
            tp = os.path.join(root, thumb)
            if os.path.isfile(tp):
                try:
                    with bpy.context.temp_override(id=mat):
                        bpy.ops.ed.lib_id_load_custom_preview(filepath=tp)
                    previews += 1
                except Exception as _exc:  # noqa: BLE001
                    _zyg_log.warning('custom preview not loaded for this material: %s', _exc)
        made += 1
        if made % 100 == 0:
            print(f'    {made}...', flush=True)

    write_catalogs(cats)
    # Materials with no user are purged on save unless they are given a fake
    # one - an asset-marked datablock is not a user, and the whole library
    # would come back empty.
    for m in bpy.data.materials:
        m.use_fake_user = True
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
    print(
        '@@RESULT@@ '
        + repr(
            {
                'vendor': a.vendor,
                'materials': made,
                'tiling': tiles,
                'alpha': sum(1 for r in recs.values() if (r.get('maps') or {}).get('alphaMap')),
                'previews': previews,
                'catalogs': len(cats),
                'blend': out,
                'bytes': os.path.getsize(out),
            }
        )
    )


if __name__ == '__main__':
    main()
