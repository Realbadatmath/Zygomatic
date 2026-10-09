#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_blender_textures — library materials render with their texture maps
(2026-09-11).

WHAT WENT WRONG. present() on the operator's own 20-storey tower came back
looking like an untextured grey massing model. The drawing was not at fault:
336 records, 283 of them carrying a Materials-rail id (pht_rough_concrete,
acg_Marble006, …) chosen surface by surface. arch_blender_build.mat_rgb /
get_material only knew the sixteen flat mat_* presets, so every library id fell
through to MAT_FALLBACK — one grey for the whole building.

Two independent proofs, because each can be right while the other is wrong:

  · THE SHADER (bpy, on the .blend the render was made from): each library
    material carries an Image Texture linked into the Principled Base Color,
    with its roughness and normal maps, BOX projection on OBJECT coordinates
    and a Mapping scale of 1/size_m, so the tile keeps its published physical
    size on a mesh that has no UV map.
  · THE PICTURE (PIL, on the rendered PNG): a flat-coloured building renders
    as large even fields. Per-pixel luminance std-dev measures that directly.
    Measured on this machine before and after the builder change, same
    fixture, same camera, 640x360 EEVEE:  17.871 flat -> 20.231 textured.

VIEW. The brief asked for view='approach'. blender_render refuses it —
'approach' is a present() shot name, not one of its views ('refused: view must
be one of iso, top, front, back, right, left, section, eye, aerial'). 'front'
is the elevation: it fills the frame with facade, which is exactly the surface
under test, and it is the view both numbers above were measured on.

Run: /usr/bin/python3 tests_arch_ext/test_blender_textures.py
"""

import json
import os
import statistics
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
sys.path.insert(0, CREWS)

from zyg_workflows.arch_ext_harness import BLENDER, check, finish, save_render, _blender  # noqa: E402

FIXTURE = os.path.join(HERE, 'fixtures', 'live_tower_20260911.json')
VIEW = 'front'
WIDTH, HEIGHT = 640, 360
# measured on this machine 2026-09-11 with the builder as it was (every library
# id -> MAT_FALLBACK), same fixture, same camera, same size
STD_FLAT = 17.871
STD_FLOOR = 18.0
# the library ids the tower actually uses most; Marble021 is in the catalogue
# but not in this drawing, so it is only checked when a record carries it
WANT = ['pht_rough_concrete', 'acg_Marble006', 'acg_Marble021']

PROBE = r'''
import bpy, json
want = %s
out = {}
for name in want:
    m = bpy.data.materials.get(name)
    if m is None or not m.use_nodes:
        out[name] = None
        continue
    nt = m.node_tree
    bsdf = nt.nodes.get('Principled BSDF')
    if bsdf is None:
        out[name] = None
        continue

    def feeds(node, sock_name, depth=0):
        """bl_idnames reachable upstream of one input socket. Matched on NAME:
        bpy re-wraps its structs, so `link.to_socket is sock` is never true."""
        seen = []
        for l in nt.links:
            if l.to_node.name == node.name and l.to_socket.name == sock_name:
                seen.append(l.from_node.bl_idname)
                if depth < 4:
                    for i in l.from_node.inputs:
                        seen += feeds(l.from_node, i.name, depth + 1)
        return seen

    imgs = [n for n in nt.nodes if n.bl_idname == 'ShaderNodeTexImage']
    base = feeds(bsdf, 'Base Color')
    out[name] = {
        'base': base, 'rough': feeds(bsdf, 'Roughness'), 'normal': feeds(bsdf, 'Normal'),
        'maps': sorted(n.image.filepath.split('mesh_packs/')[-1] for n in imgs if n.image),
        'projection': sorted({n.projection for n in imgs}),
        'blend': sorted({round(n.projection_blend, 3) for n in imgs}),
        'coord': sorted({l.from_socket.name for l in nt.links
                         if l.to_node.bl_idname == 'ShaderNodeMapping'}),
        'scale': [[round(v, 5) for v in list(n.inputs['Scale'].default_value)[:3]]
                  for n in nt.nodes if n.bl_idname == 'ShaderNodeMapping'],
        'tex_in_base': 'ShaderNodeTexImage' in base,
    }
print('TEXTURED %%d' %% sum(1 for v in out.values() if v and v['tex_in_base']))
print('PROBE ' + json.dumps(out))
'''


def main():
    from zyg_workflows import arch_assistant as A
    from zyg_workflows import architecture_materials as AM

    A.load_extensions()
    with open(FIXTURE, encoding='utf-8') as fh:
        doc = json.load(fh)
    d = A.Drawing(doc)
    check('the live tower fixture loads (336 records)', len(d.objs) == 336, len(d.objs))

    # which library ids the drawing actually uses, and whether their maps are on disk
    defs = (AM.catalogue() or {}).get('defs') or {}
    used = {}
    for o in d.objs:
        mid = o.get('mat')
        if isinstance(mid, str) and mid and not mid.startswith('mat_'):
            used[mid] = used.get(mid, 0) + 1
    missing = [m for m in used if not (defs.get(m) or {}).get('maps', {}).get('map')]
    check(
        'every library id in the drawing is catalogued with an albedo',
        used and not missing,
        f'{len(used)} ids, {sum(used.values())} records, missing={missing}',
    )
    offdisk = []
    for mid in used:
        for slot, rel in ((defs.get(mid) or {}).get('maps') or {}).items():
            if slot in ('map', 'roughnessMap', 'normalMap', 'aoMap') and not os.path.exists(
                os.path.join(AM.PACKS_ROOT, rel)
            ):
                offdisk.append(f'{mid}/{slot}')
    check('their map files are on disk', not offdisk, offdisk[:6])

    # ── the picture ──────────────────────────────────────────────────────────
    png = os.path.join(tempfile.mkdtemp(prefix='arch_tex_'), 'tower_front.png')
    txt = save_render(d, png, view=VIEW, engine='eevee', width=WIDTH, height=HEIGHT)
    check(
        'the render wrote a PNG',
        os.path.exists(png) and os.path.getsize(png) > 5000,
        f'{png} {os.path.getsize(png) if os.path.exists(png) else 0} B :: {str(txt)[:160]}',
    )

    from PIL import Image

    im = Image.open(png).convert('L')
    getter = getattr(im, 'get_flattened_data', None) or im.getdata
    px = list(getter())
    std = statistics.pstdev(px)
    check(
        'the render is not a flat massing model (luminance std-dev)',
        std > STD_FLOOR,
        f'std-dev {std:.3f} <= {STD_FLOOR}',
    )
    print(
        '    std-dev: %.3f flat (before the change) -> %.3f textured (now), floor %.1f; mean %.2f'
        % (STD_FLAT, std, STD_FLOOR, statistics.fmean(px)),
        flush=True,
    )
    check('textured beats the flat measurement it replaced', std > STD_FLAT, f'{std:.3f} vs {STD_FLAT}')

    # ── the shader ───────────────────────────────────────────────────────────
    blend = (getattr(d, '_bp_blend', None) or (None, None))[1]
    if not (blend and os.path.exists(blend)):
        import zyg_workflows.arch_assistant_ext.blender_power as BP

        blend = BP._build(d)[0]
    check('the render kept a .blend to probe', bool(blend) and os.path.exists(blend), blend)

    spath = os.path.join(os.path.dirname(png), 'probe.py')
    with open(spath, 'w', encoding='utf-8') as fh:
        fh.write(PROBE % json.dumps(WANT))
    p = _blender([BLENDER, '-b', blend, '--python', spath], 300)
    lines = (p.stdout or '').splitlines()
    got = {}
    n_tex = -1
    for line in lines:
        if line.startswith('TEXTURED '):
            n_tex = int(line.split()[1])
        elif line.startswith('PROBE '):
            got = json.loads(line[6:])
    expect = [m for m in WANT if m in used]
    check('the bpy probe ran', n_tex >= 0 and bool(got), (p.stderr or p.stdout or '')[-300:])
    check(
        'TEXTURED %d — every library material in the drawing has an image in its Base Color' % len(expect),
        n_tex == len(expect),
        f'TEXTURED {n_tex}, expected {len(expect)} of {expect}',
    )

    for mid in expect:
        g = got.get(mid)
        if not g:
            check(f'{mid}: material exists in the .blend', False, 'absent')
            continue
        check(f'{mid}: Image Texture -> Base Color', g['tex_in_base'], g['base'])
        check(f'{mid}: roughness map -> Roughness', 'ShaderNodeTexImage' in g['rough'], g['rough'])
        check(
            f'{mid}: normal map -> Normal Map node -> Normal',
            g['normal'][:2] == ['ShaderNodeNormalMap', 'ShaderNodeTexImage'],
            g['normal'],
        )
        check(
            f'{mid}: BOX projection, blend 0.25',
            g['projection'] == ['BOX'] and g['blend'] == [0.25],
            f'{g["projection"]} {g["blend"]}',
        )
        check(f'{mid}: tiled on OBJECT coordinates', g['coord'] == ['Object'], g['coord'])
        sx, sy = ((defs[mid].get('size_m') or [1.0, 1.0]) + [1.0, 1.0])[:2]
        want_scale = [
            round(1.0 / float(sx or 1.0), 5),
            round(1.0 / float(sy or sx or 1.0), 5),
            round(1.0 / float(sx or 1.0), 5),
        ]
        check(
            f'{mid}: Mapping scale is 1/size_m ({sx:g}x{sy:g} m per tile)',
            g['scale'] == [want_scale],
            f'{g["scale"]} want {[want_scale]}',
        )
        check(
            f'{mid}: every published map is loaded',
            len(g['maps'])
            == len([s for s in ('map', 'roughnessMap', 'normalMap', 'aoMap') if (defs[mid]['maps'] or {}).get(s)]),
            g['maps'],
        )

    # a preset is still a flat colour — the textured path must not swallow mat_*
    q = _blender(
        [
            BLENDER,
            '-b',
            blend,
            '--python-expr',
            'import bpy, json\n'
            "m = bpy.data.materials.get('mat_glass')\n"
            'nt = m.node_tree if m else None\n'
            "print('PRESET ' + json.dumps({'exists': bool(m), 'images': 0 if not nt else "
            "len([n for n in nt.nodes if n.bl_idname == 'ShaderNodeTexImage'])}))",
        ],
        300,
    )
    pre = {}
    for line in (q.stdout or '').splitlines():
        if line.startswith('PRESET '):
            pre = json.loads(line[7:])
    check('mat_glass is still a flat preset (no image nodes)', pre.get('exists') and pre.get('images') == 0, pre)

    finish()


if __name__ == '__main__':
    main()
