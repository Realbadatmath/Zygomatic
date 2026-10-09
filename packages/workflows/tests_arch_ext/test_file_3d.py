# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_file_3d.py — the proof that File ▸ 3D interchange is real.

Five icons that were placeholders (f_glb, f_stl, f_import, f_pc, f_link), each
checked twice: the live DOM says the placeholder mark is gone, and the thing the
tooltip promises actually happened.

  f_glb     the tab built a .glb, the server kept a copy, and BLENDER opens that
            very file and finds the drawing's objects in it.
  f_stl     the server copy parses as a binary STL (80-byte header + uint32
            triangle count) with triangles > 0.
  f_import  a base64 .glb goes up, comes back by id, and the mesh_file record's
            node gains real meshes where its crate was.
  f_pc      the shipped 5,000-point survey lands as a THREE.Points with colour.
  f_link    a drawing saved from Python here is referenced as ONE record whose
            node holds the linked records' geometry.

Four browser_eval calls (one of them icon_state) and one Blender run.
"""

import base64
import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import (
    BLENDER,
    _BlenderLock,
    assistant,
    browser_eval,  # noqa: E402
    check,
    finish,
    icon_state,
    rail_has,
    server_ext,
    tool_names,
)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMPORTS = os.path.join(HERE, 'data', 'architecture', 'imports')
IDS = ['f_glb', 'f_stl', 'f_import', 'f_pc', 'f_link']

# ── 1. the icons are no longer placeholders ──────────────────────────────────
st = icon_state(IDS)
check(
    'all five icons exist, with no stub flag, no dashed class and no [placeholder] tooltip',
    all(
        st.get(i, {}).get('exists')
        and not st[i].get('stub')
        and not st[i].get('dashed')
        and not st[i].get('tip_placeholder')
        for i in IDS
    ),
    st,
)

# ── 2. a drawing to link, saved the way the studio saves one ─────────────────
from zyg_workflows import architecture_studio as ST  # noqa: E402

LINK_DOC = {
    'name': 'file_3d link target',
    'units': 'm',
    'objects': [
        {
            'id': 'o1',
            'kind': 'slab',
            'name': 'deck',
            'p': {'w': 6, 'd': 4, 't': 0.3},
            'x': 0,
            'y': 0,
            'z': 0,
            'rx': 0,
            'ry': 0,
            'rz': 0,
            's': 1,
            'mat': 'mat_concrete',
            'hidden': False,
            'grp': '',
        },
        {
            'id': 'o2',
            'kind': 'slab',
            'name': 'roof',
            'p': {'w': 6, 'd': 4, 't': 0.2},
            'x': 0,
            'y': 3,
            'z': 0,
            'rx': 0,
            'ry': 0,
            'rz': 0,
            's': 1,
            'mat': 'mat_concrete',
            'hidden': False,
            'grp': '',
        },
        {
            'id': 'o3',
            'kind': 'column_rect',
            'name': 'post',
            'p': {'w': 0.3, 'd': 0.3, 'h': 3},
            'x': 2,
            'y': 0,
            'z': 1,
            'rx': 0,
            'ry': 0,
            'rz': 0,
            's': 1,
            'mat': 'mat_concrete',
            'hidden': False,
            'grp': '',
        },
    ],
}
saved = ST.save_project(LINK_DOC, pid='file-3d-link-target', name='file_3d link target')
PID = saved.get('id') or ''
check(
    'a drawing to link was saved through architecture_studio.save_project', bool(PID) and not saved.get('error'), saved
)

# ── 3. f_glb + f_stl: export the visible drawing, download AND server copy ───
r = browser_eval(
    """async () => {
  const a = arNewObj('slab',        {w:6, d:4, t:0.3},        0,  0, 0);
  const b = arNewObj('wall',        {len:6, h:2.7, t:0.24},   0, -2, 0);
  const c = arNewObj('column_round',{r:0.2, h:3},             2,  2, 0);
  arTool('f_glb', {name: 'f3dproof'});
  const g = await AR_EXT.tools.f_glb._pending;
  arTool('f_stl', {name: 'f3dproof'});
  const s = await AR_EXT.tools.f_stl._pending;
  return {glb: g, stl: s, objs: AR.objs.length,
          toast: document.getElementById('ar-toast').innerHTML};
}""",
    doc={'objects': []},
)
v = r['value'] or {}
glb, stl = (v.get('glb') or {}), (v.get('stl') or {})
GLB_PATH = ((glb.get('save') or {}).get('path')) or ''
STL_PATH = ((stl.get('save') or {}).get('path')) or ''
check(
    'f_glb exported the three visible records and the server kept a .glb copy',
    glb.get('ok')
    and glb.get('objects', 0) >= 3
    and glb.get('tris', 0) > 0
    and GLB_PATH.endswith('.glb')
    and os.path.isfile(GLB_PATH),
    {'glb': glb, 'errors': r['errors']},
)
check(
    'f_stl exported the same drawing and the server kept a .stl copy',
    stl.get('ok') and stl.get('tris', 0) > 0 and STL_PATH.endswith('.stl') and os.path.isfile(STL_PATH),
    {'stl': stl, 'errors': r['errors']},
)
check('the exports toast what they did, with the server path', 'exports/' in (v.get('toast') or ''), v.get('toast'))
check('no page errors while exporting', not r['errors'], r['errors'])

# the STL the browser made, read as bytes: 80-byte header, uint32 triangle count
if STL_PATH and os.path.isfile(STL_PATH):
    with open(STL_PATH, 'rb') as fh:
        head = fh.read(84)
    n_tri = struct.unpack('<I', head[80:84])[0] if len(head) == 84 else 0
    size_ok = os.path.getsize(STL_PATH) == 84 + n_tri * 50
    check(
        'the .stl on the server is a binary STL whose triangle count is > 0 and matches its size',
        n_tri > 0 and size_ok,
        {'triangles': n_tri, 'bytes': os.path.getsize(STL_PATH)},
    )
else:
    check('the .stl on the server is a binary STL whose triangle count is > 0 and matches its size', False, STL_PATH)

# ── 4. Blender opens the glb the browser just made (one run) ─────────────────
if GLB_PATH and os.path.isfile(GLB_PATH):
    expr = (
        'import bpy\n'
        'for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)\n'
        'bpy.ops.import_scene.gltf(filepath=%r)\n'
        "print('GLTFMESH %%d' %% len([o for o in bpy.data.objects if o.type == 'MESH']))\n" % GLB_PATH
    )
    with _BlenderLock():
        p = subprocess.run([BLENDER, '-b', '--python-expr', expr], capture_output=True, text=True, timeout=300)
    line = [ln for ln in (p.stdout or '').splitlines() if ln.startswith('GLTFMESH ')]
    n_mesh = int(line[-1].split()[1]) if line else 0
    check(
        "Blender imports the exported .glb and finds the drawing's objects in it (>= 3 meshes)",
        n_mesh >= 3,
        {'meshes': n_mesh, 'stderr': (p.stderr or '')[-300:], 'tail': (p.stdout or '')[-300:]},
    )
else:
    check("Blender imports the exported .glb and finds the drawing's objects in it (>= 3 meshes)", False, GLB_PATH)

# ── 5. f_import + f_pc: bytes in, real geometry out ─────────────────────────
with open(os.path.join(IMPORTS, 'sample.glb'), 'rb') as fh:
    GLB_B64 = base64.b64encode(fh.read()).decode('ascii')

r2 = browser_eval(
    """async () => {
  arTool('f_import', {data_b64: %s, name: 'sample.glb', cell: 'C4', scale: 2});
  const m = await AR_EXT.tools.f_import._pending;
  let meshes = 0, tris = 0;
  m.node.traverse(o => { if (o.isMesh && o.geometry && o.geometry.attributes.position && !(o.userData||{}).arPlaceholder) {
    meshes++; tris += o.geometry.index ? o.geometry.index.count/3 : o.geometry.attributes.position.count/3; } });
  arTool('f_pc', {id: 'sample_cloud', ext: 'xyz', size: 0.05});
  const c = await AR_EXT.tools.f_pc._pending;
  let pts = null; c.node.traverse(o => { if (o.isPoints) pts = o; });
  return {mesh: {kind: m.kind, id: m.id, p: m.p, meshes: meshes, tris: Math.round(tris), err: m.f3dErr || ''},
          cloud: {kind: c.kind, p: c.p, n: pts ? pts.geometry.attributes.position.count : 0,
                  colour: !!(pts && pts.geometry.attributes.color),
                  size: pts ? pts.material.size : 0, err: c.f3dErr || ''},
          crates: AR.objs.filter(o => (o.kind === 'mesh_file' || o.kind === 'point_cloud')
                                 && o.node.children.some(k => (k.userData||{}).arPlaceholder)).length};
}"""
    % (repr(GLB_B64).lstrip('u'),),
    doc={'objects': []},
)
v2 = r2['value'] or {}
mesh, cloud = (v2.get('mesh') or {}), (v2.get('cloud') or {})
check(
    'f_import uploaded the .glb, made a mesh_file record and swapped real meshes in for the crate',
    mesh.get('kind') == 'mesh_file' and mesh.get('meshes', 0) > 0 and mesh.get('tris', 0) > 0 and not mesh.get('err'),
    {'mesh': mesh, 'errors': r2['errors']},
)
check(
    'the mesh_file record stores PARAMETERS only — a file id, an extension and a scale',
    set((mesh.get('p') or {})) <= {'id', 'ext', 'sx', 'name'}
    and (mesh.get('p') or {}).get('sx') == 2
    and (mesh.get('p') or {}).get('ext') == 'glb'
    and len(str((mesh.get('p') or {}).get('id', ''))) >= 8,
    mesh.get('p'),
)
check(
    'f_pc loaded the 5,000-point survey as a THREE.Points with its vertex colours',
    cloud.get('kind') == 'point_cloud'
    and abs(cloud.get('n', 0) - 5000) <= 5
    and cloud.get('colour')
    and abs(cloud.get('size', 0) - 0.05) < 1e-6
    and not cloud.get('err'),
    {'cloud': cloud, 'errors': r2['errors']},
)
check('both records dropped their placeholder crates once the files landed', v2.get('crates') == 0, v2)
check('no page errors while importing', not r2['errors'], r2['errors'])

# ── 6. f_link: another saved drawing as one reference record ────────────────
r3 = browser_eval(
    """async () => {
  arTool('f_link', {pid: %r});
  const rec = await AR_EXT.tools.f_link._pending;
  let tris = 0, meshes = 0, crate = 0;
  rec.node.traverse(o => { if (o.isMesh && o.geometry && o.geometry.attributes.position) {
    if ((o.userData||{}).arPlaceholder) { crate++; return; }
    meshes++; tris += o.geometry.index ? o.geometry.index.count/3 : o.geometry.attributes.position.count/3; } });
  arTool('f_link');                       /* no args: the sheet of linkable drawings */
  await AR_EXT.tools.f_link._pending;
  const sheet = document.getElementById('ar-sheet');
  const before = tris;
  arTool('f_link', {reload: 1});          /* clear the cache and rebuild */
  await AR_EXT.tools.f_link._pending;     /* the re-fetch, not just the cache clear */
  const after = arFind(rec.id);
  let tris2 = 0;
  after.node.traverse(o => { if (o.isMesh && o.geometry && o.geometry.attributes.position
                                 && !(o.userData||{}).arPlaceholder)
    tris2 += o.geometry.index ? o.geometry.index.count/3 : o.geometry.attributes.position.count/3; });
  return {kind: rec.kind, p: rec.p, name: rec.name, tris: Math.round(before), meshes: meshes, crate: crate,
          reloaded: Math.round(tris2), err: rec.f3dErr || '',
          sheet: sheet ? (sheet.textContent || '').slice(0, 400) : '',
          objs: AR.objs.length};
}"""
    % (PID,),
    doc={'objects': []},
)
v3 = r3['value'] or {}
check(
    "f_link made ONE link record holding the linked drawing's geometry (more than a 12-triangle crate)",
    v3.get('kind') == 'link'
    and v3.get('tris', 0) > 12
    and v3.get('meshes', 0) >= 3
    and v3.get('crate') == 0
    and v3.get('objs') == 1,
    {'link': v3, 'errors': r3['errors']},
)
check(
    'the link record stores only the drawing id and its name — never the linked geometry',
    set((v3.get('p') or {})) == {'pid', 'name'} and (v3.get('p') or {}).get('pid') == PID,
    v3.get('p'),
)
check(
    'pressing f_link with no arguments opens the sheet of linkable drawings',
    'Reload links' in (v3.get('sheet') or '') and 'Reference another saved drawing' in (v3.get('sheet') or ''),
    (v3.get('sheet') or '')[:200],
)
check(
    'Reload links clears the cache and rebuilds the link to the same geometry',
    v3.get('reloaded') == v3.get('tris') and v3.get('reloaded', 0) > 12,
    v3,
)
check('no page errors while linking', not r3['errors'], r3['errors'])

# ── 7. the server extension, on its own ─────────────────────────────────────
up = server_ext('file_3d', 'upload', {'name': 'probe.xyz', 'data_b64': base64.b64encode(b'0 0 0\n1 0 1\n').decode()})
check(
    'the upload route stores a file under a content id and answers where it went',
    up.get('ok') and up.get('ext') == 'xyz' and len(str(up.get('id'))) == 16 and os.path.isfile(up.get('path') or ''),
    up,
)
again = server_ext('file_3d', 'upload', {'name': 'probe.xyz', 'data_b64': base64.b64encode(b'0 0 0\n1 0 1\n').decode()})
check('the same bytes get the same id, so twenty placements are one file', again.get('id') == up.get('id'), again)
back = server_ext('file_3d', 'file', {'id': up.get('id')}, method='GET')
check('the file route serves those bytes back for the tab to parse', back.get('bytes') == b'0 0 0\n1 0 1\n', back)
bad = server_ext('file_3d', 'save', {'name': 'x', 'ext': 'exe', 'data_b64': base64.b64encode(b'MZ').decode()})
check(
    'save fences the extension to glb/stl/obj/ply',
    bad.get('code') == 400 and 'ext must be' in str(bad.get('error')),
    bad,
)
miss = server_ext('file_3d', 'file', {'id': 'no-such-id'}, method='GET')
check('an unknown file id is a 404, not a traversal', miss.get('code') == 404, miss)

# ── 8. the assistant twins ──────────────────────────────────────────────────
check(
    'the three server-side twins are registered as assistant tools',
    all(t in tool_names() for t in ('export_model', 'import_mesh', 'link_drawing')),
    tool_names()[-8:],
)
txt, d = assistant('export_model', {'format': 'stl'})
check(
    'export_model presses f_stl and says the units out loud',
    d.ui and d.ui[-1]['args']['id'] == 'f_stl' and 'METRES' in txt,
    (txt, d.ui),
)
txt2, d2 = assistant('import_mesh', {'id': 'sample', 'cell': 'C4', 'scale': 0.5})
check(
    'import_mesh places a mesh_file record with the id, the extension and the scale',
    d2.objs
    and d2.objs[-1]['kind'] == 'mesh_file'
    and d2.objs[-1]['p'] == {'id': 'sample', 'ext': 'glb', 'sx': 0.5, 'name': 'sample'},
    (txt2, d2.objs),
)
txt3, _ = assistant('import_mesh', {'id': 'not-a-file'})
check(
    'import_mesh refuses an id this machine does not have, and says which it does',
    txt3.startswith('refused') and 'sample' in txt3,
    txt3,
)
txt4, d4 = assistant('link_drawing', {'pid': PID, 'cell': 'D5'})
check(
    'link_drawing places a link record pointing at the saved drawing',
    d4.objs and d4.objs[-1]['kind'] == 'link' and d4.objs[-1]['p']['pid'] == PID,
    (txt4, d4.objs),
)
txt5, _ = assistant('link_drawing', {'pid': 'no-such-drawing'})
check('link_drawing refuses a drawing that is not saved', txt5.startswith('refused'), txt5)
txt6, d6 = assistant('press_button', {'id': 'f_pc', 'args': {'id': 'sample_cloud'}})
check(
    'the assistant may press all five icons with arguments',
    txt6.startswith('pressed') and d6.ui[-1]['args'].get('args') == {'id': 'sample_cloud'},
    (txt6, d6.ui),
)

# ── 9. the rail and the Blender twins ───────────────────────────────────────
check(
    'the library rail lists the three new kinds',
    rail_has(['mesh_file', 'point_cloud', 'link']) == [],
    rail_has(['mesh_file', 'point_cloud', 'link']),
)
import zyg_workflows.arch_blender_ext.file_3d as BL  # noqa: E402

boxes = []
kit = {'add_box_c': lambda bm, w, d, h, z0=0.0: boxes.append((w, d, h)), 'num': lambda p, k, dv: float(p.get(k, dv))}
check(
    'the Blender twin builds link as an approximate bbox crate',
    BL.build_link(None, {}, kit) == ('~', []) and boxes == [(6.0, 6.0, 3.0)],
    boxes,
)
check(
    'the Blender twin registers all three kinds',
    sorted(BL.BUILDERS) == ['link', 'mesh_file', 'point_cloud'],
    sorted(BL.BUILDERS),
)

finish()
