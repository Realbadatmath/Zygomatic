# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""mh_to_glb.py — MakeHuman hair assets -> GLB in the HEAD FRAME.
Run under Blender:  blender -b --python mh_to_glb.py -- <src_hair_dir> <out_dir> <base_obj>

A MakeHuman groom is a hair-card mesh modelled around the hm08 base mesh, in
MakeHuman's own space (Y up, +Z forward, 1 unit = 1 dm, origin at the body's
middle). Character Studio's clay body is a different mesh at a different scale,
so a groom is NOT stored where it was authored. It is stored in the DONOR'S
HEAD FRAME: origin at the head's own centre (cx, yTop, zc), one unit = one head
width. Fitting it to any other body is then a translate and a uniform scale off
that body's OWN measured head — the same measurement char_hair.js already
makes (headMetrics) — and never a guess about proportions.

The exporter's axis round trip is VERIFIED, not assumed: the mesh's bounding box
in head units is measured after import and written to the manifest, and
verify_glb.py re-measures it from the exported GLB. A silent axis flip shows up
as a mismatch instead of as a groom facing backwards three weeks later."""

import json
import logging as _zyg_logging
import os
import sys

import bpy
from mathutils import Matrix, Vector

_zyg_log = _zyg_logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from headframe import head_frame, read_obj_verts  # noqa: E402  needs the sys.path above under --factory-startup
import mhclo_fit  # noqa: E402  needs the sys.path above under --factory-startup


def _bbox(meshes):
    """Bounding box and vertex count of some meshes, in Blender world space."""
    lo = [1e9] * 3
    hi = [-1e9] * 3
    n = 0
    for ob in meshes:
        for v in ob.data.vertices:
            w = ob.matrix_world @ v.co
            n += 1
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    return lo, hi, n


def wipe():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def mhmat(path):
    """The fields of a .mhmat this converter uses, plus its licence comment."""
    out = {'diffuse': None, 'normal': None, 'transparent': False, 'licence_comment': '', 'name': ''}
    if not path or not os.path.isfile(path):
        return out
    for ln in open(path, errors='replace'):
        s = ln.strip()
        if s.startswith('#'):
            if 'CC0' in s or 'licen' in s.lower() or 'Copyright' in s:
                out['licence_comment'] += s.lstrip('# ').rstrip() + '\n'
            continue
        p = s.split()
        if len(p) < 2:
            continue
        k = p[0].lower()
        if k == 'diffusetexture':
            out['diffuse'] = ' '.join(p[1:])
        elif k in ('normalmaptexture', 'normaltexture'):
            out['normal'] = ' '.join(p[1:])
        elif k == 'transparent':
            out['transparent'] = p[1].lower() == 'true'
        elif k == 'name':
            out['name'] = ' '.join(p[1:])
    return out


def mhclo(path):
    out = {'author': '', 'licence': '', 'name': '', 'material': '', 'obj': '', 'tags': []}
    if not os.path.isfile(path):
        return out
    for ln in open(path, errors='replace'):
        s = ln.strip()
        if s.startswith('#'):
            p = s.lstrip('# ').split(None, 1)
            if len(p) == 2 and p[0].lower() in ('author', 'license', 'licence'):
                out['author' if p[0].lower() == 'author' else 'licence'] = p[1].strip()
            continue
        p = s.split(None, 1)
        if len(p) != 2:
            continue
        k = p[0].lower()
        if k in ('name', 'material', 'obj_file'):
            out['obj' if k == 'obj_file' else k] = p[1].strip()
        elif k == 'tag':
            out['tags'].append(p[1].strip())
    return out


def build_material(name, mat, texdir):
    """A hair-card material: the diffuse texture drives base colour AND alpha.

    MakeHuman hair cards are transparent PNGs; without the alpha wired the card
    renders as an opaque grey rectangle, which is what a 'hair helmet' actually
    is. Blend mode is BLEND and backface culling is off, because a card is a
    single-sided quad seen from both sides."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get('Principled BSDF')
    bsdf.inputs['Roughness'].default_value = 0.42
    bsdf.inputs['Metallic'].default_value = 0.0
    if 'Specular IOR Level' in bsdf.inputs:
        bsdf.inputs['Specular IOR Level'].default_value = 0.35
    img = None
    if mat.get('diffuse'):
        fp = os.path.join(texdir, mat['diffuse'])
        if os.path.isfile(fp):
            img = bpy.data.images.load(fp)
            tex = nt.nodes.new('ShaderNodeTexImage')
            tex.image = img
            tex.location = (-520, 240)
            nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
            nt.links.new(tex.outputs['Alpha'], bsdf.inputs['Alpha'])
    if mat.get('normal'):
        fp = os.path.join(texdir, mat['normal'])
        if os.path.isfile(fp):
            nimg = bpy.data.images.load(fp)
            nimg.colorspace_settings.name = 'Non-Color'
            ntex = nt.nodes.new('ShaderNodeTexImage')
            ntex.image = nimg
            ntex.location = (-520, -140)
            nmap = nt.nodes.new('ShaderNodeNormalMap')
            nmap.location = (-240, -140)
            nt.links.new(ntex.outputs['Color'], nmap.inputs['Color'])
            nt.links.new(nmap.outputs['Normal'], bsdf.inputs['Normal'])
    # ALPHA CLIP, not blend. A head of hair cards is hundreds of overlapping
    # quads; with BLEND the viewport has to sort them per frame and gets it
    # wrong at every crossing, and glTF carries the choice to three.js as
    # alphaMode. MASK costs a hard edge at the cutoff and sorts correctly.
    m.blend_method = 'CLIP'
    m.alpha_threshold = 0.5
    if hasattr(m, 'surface_render_method'):
        m.surface_render_method = 'DITHERED'  # EEVEE Next ignores blend_method
    m.use_backface_culling = False
    return m, (img.name if img else None)


def convert(style_dir, out_dir, frame, base, tmp_dir):
    """One hair style -> one GLB in head units. Returns its manifest record."""
    objs = [f for f in os.listdir(style_dir) if f.lower().endswith('.obj')]
    clos = [f for f in os.listdir(style_dir) if f.lower().endswith('.mhclo')]
    if not objs:
        return None
    sid = os.path.basename(style_dir.rstrip('/'))
    clo = mhclo(os.path.join(style_dir, clos[0])) if clos else {}
    objf = clo.get('obj') if clo.get('obj') in objs else objs[0]
    matf = clo.get('material') or (os.path.splitext(objf)[0] + '.mhmat')
    mat = mhmat(os.path.join(style_dir, matf))

    # PLACE IT FIRST. The .obj is raw modelling data; the .mhclo says where each
    # vertex belongs on the base mesh. Read literally the styles disagree with
    # each other by up to 10 cm of head height — see mhclo_fit.py.
    src_obj = os.path.join(style_dir, objf)
    fit_note, fitted_scales = '', None
    if clos:
        clo = mhclo_fit.parse_mhclo(os.path.join(style_dir, clos[0]))
        if clo['verts']:
            pts, fitted_scales = mhclo_fit.fit(clo, base)
            dst = os.path.join(tmp_dir, sid + '.obj')
            got, err = mhclo_fit.write_fitted_obj(src_obj, pts, dst)
            if got:
                src_obj = got
                fit_note = 'mhclo'
            else:
                fit_note = f'UNFITTED ({err})'
        else:
            fit_note = 'UNFITTED (no verts block)'
    else:
        fit_note = 'UNFITTED (no .mhclo)'

    wipe()
    bpy.ops.wm.obj_import(filepath=src_obj, forward_axis='NEGATIVE_Z', up_axis='Y')
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if not meshes:
        return None

    # The importer leaves its axis conversion in the OBJECT matrix, not in the
    # mesh data: a transform applied to the data alone would run in MakeHuman's
    # axes and then be rotated by that matrix afterwards, which is how the first
    # run put every groom a head-height above the head and a head-depth behind
    # it. Bake the matrix in first, then there is exactly one space to think in.
    for ob in meshes:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    pre = _bbox(meshes)
    # The head origin in MakeHuman space, carried through the same axis map the
    # importer just baked in (mh.x -> bl.x, mh.y -> bl.z, mh.z -> -bl.y).
    origin = Vector((frame['cx'], -frame['zc'], frame['yTop']))
    s = 1.0 / frame['headW']
    M = Matrix.Diagonal((s, s, s, 1.0)) @ Matrix.Translation(-origin)

    tris = 0
    for ob in meshes:
        ob.data.transform(M)
        ob.data.update()
        ob.data.materials.clear()
        m, _img = build_material(sid, mat, style_dir)
        ob.data.materials.append(m)
        ob.data.calc_loop_triangles()
        tris += len(ob.data.loop_triangles)

    # measured, in head units — this is what verify_glb.py checks against
    lo, hi, nv = _bbox(meshes)

    os.makedirs(out_dir, exist_ok=True)
    glb = os.path.join(out_dir, sid + '.glb')
    bpy.ops.export_scene.gltf(
        filepath=glb,
        export_format='GLB',
        export_yup=True,
        export_apply=True,
        export_materials='EXPORT',
        export_image_format='AUTO',
    )
    # Blender (x, y, z) with +Z up  ->  glTF (x, z, -y) with +Y up
    bbox = {'x': [lo[0], hi[0]], 'y': [lo[2], hi[2]], 'z': [-hi[1], -lo[1]]}
    return {
        'id': sid,
        'file': os.path.basename(glb),
        'kind': 'cards',
        'bbox_import': {'lo': list(pre[0]), 'hi': list(pre[1])},
        'placement': fit_note,
        'mhclo_scales': list(fitted_scales) if fitted_scales else None,
        'label': (clo.get('name') or mat.get('name') or sid),
        'author': clo.get('author', ''),
        'licence_mhclo': clo.get('licence', ''),
        'tags': clo.get('tags', []),
        'verts': nv,
        'tris': tris,
        'texture': mat.get('diffuse'),
        'normal_map': mat.get('normal'),
        'mhmat_licence_comment': mat.get('licence_comment', '').strip(),
        'bbox_head_units': bbox,
        'bytes': os.path.getsize(glb),
    }


def main():
    argv = sys.argv[sys.argv.index('--') + 1 :]
    src, out, base = argv[0], argv[1], argv[2]
    # 'body' only: the helper cage round hm08 measures 18 % wider than the head
    frame = head_frame(read_obj_verts(base, ('body',)))
    # the FULL base mesh, helpers included: hair binds to the helper-hair group
    base_v, _ = mhclo_fit.read_obj(base)
    tmp_dir = os.path.join(out, '_fitted_obj')
    recs, problems = [], []
    for d in sorted(os.listdir(src)):
        sd = os.path.join(src, d)
        if not os.path.isdir(sd):
            continue
        try:
            r = convert(sd, out, frame, base_v, tmp_dir)
            if r:
                recs.append(r)
            else:
                problems.append(f'{d}: no .obj')
        except Exception as e:  # noqa: BLE001
            problems.append(f'{d}: {e!r}')
    try:
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('temporary export dir cleanup skipped: %s', _exc)
    print('ZYGRESULT' + json.dumps({'donor_head_frame': frame, 'items': recs, 'problems': problems}))


main()
