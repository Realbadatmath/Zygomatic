# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""rig_export_glb.py — one actor .blend out as a skinned, animated GLB for the browser.

    flock /tmp/claude-1000/arch_ext_blender.lock /usr/local/bin/blender -b \
        --python blender_scripts/rig_export_glb.py -- --actor abel_capture [--out DIR]

WHY. The actor .blend is the shot runner's format: Blender opens it, appends the
collection 'actor' and renders. Movement Studio is a BROWSER, and a browser reads
glTF. This is the one-way door between the two — it does not change the .blend
contract (collection 'actor': actor_root empty -> armature (custom props
actor_name, actor_height_m, motion_id, mapping, root_offset_z) -> mesh; action
'motion'; sidecar <name>.json), it only re-publishes it.

THREE THINGS THAT ARE EASY TO GET WRONG.

  * THE REST FRAME IS NOT PLAYABLE. A retargeted actor keeps its rest pose on
    frame <rest_frame> (frame 1 for a capture clip) so the retarget has a
    reference; the motion starts on the frame AFTER it. Exporting from frame 1
    puts a one-frame snap at the head of every loop in the browser, so the
    export range is [rest_frame + 1, frames] — scene.frame_start/frame_end are
    set from the sidecar, not trusted from the .blend.

  * TIME IN A GLB IS SECONDS, and the exporter converts frames with
    scene.render.fps. The clips run at 24 fps (capture) and 120 fps (CMU), so
    the scene fps is re-asserted from the sidecar before the export or a
    2.9 s clip ships as a 14 s one.

  * use_selection SEES THE VIEW LAYER. An object that is not linked into the
    scene, or is hidden, cannot be selected and is silently dropped — a GLB
    with an armature and no mesh still parses. The 'actor' collection is
    linked and un-hidden first, and the sidecar re-parses the written GLB
    (stdlib, no bpy) so the proof does not come from the writer.

Materials are NOT exported: the clay look is applied in the browser, and a
placeholder material only adds bytes the viewer overrides.

Output, next to the .blend (or under --out):
    <name>.glb          skinned, animated, +Y up, Draco off
    <name>.glb.json     {name, bytes, skins, joints, animations[{name,duration_s}],
                         meshes, height_y, frames, fps, first_frame,
                         expected_duration_s}
"""

import argparse
import json
import os
import struct
import sys

import bpy
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACTORS_DIR = os.path.join(HERE, 'data', 'architecture', 'actors')


def argv_after_dashes():
    return sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []


# --------------------------------------------------------------------------
# GLB re-parse — stdlib only, so the sidecar is evidence and not a restatement
# --------------------------------------------------------------------------


def glb_json(path):
    """The JSON chunk of a GLB: length at bytes 12-16, payload from byte 20."""
    with open(path, 'rb') as fh:
        head = fh.read(20)
        if head[:4] != b'glTF':
            raise RuntimeError('%s is not a GLB (magic %r)' % (path, head[:4]))
        jl = struct.unpack('<I', head[12:16])[0]
        return json.loads(fh.read(jl))


def animation_seconds(g, anim):
    """Longest sampler input (= keyframe time) accessor max, in seconds."""
    best = 0.0
    for s in anim.get('samplers', []):
        acc = g['accessors'][s['input']]
        mx = acc.get('max')
        if mx:
            best = max(best, float(mx[0]))
    return best


def body_bbox_y(g, name):
    """Y extent of the BODY mesh's POSITION accessor.

    'Biggest mesh' stopped meaning 'the body' the moment the anatomical skeleton
    joined the actor — it carries more vertices than the base body does. The body
    is the mesh named after the actor; the size test is only the fallback, and it
    never looks at a mesh named 'skeleton'."""
    named = [m for m in g.get('meshes', []) if m.get('name') == name]
    best_count, best_y = -1, 0.0
    for mesh in named or [m for m in g.get('meshes', []) if m.get('name') != 'skeleton']:
        for prim in mesh.get('primitives', []):
            pos = prim.get('attributes', {}).get('POSITION')
            if pos is None:
                continue
            acc = g['accessors'][pos]
            mn, mx = acc.get('min'), acc.get('max')
            if not mn or not mx:
                continue
            if acc['count'] > best_count:
                best_count = acc['count']
                best_y = float(mx[1]) - float(mn[1])
    return best_y


def sidecar(path, name, frames, fps, first_frame):
    g = glb_json(path)
    skins = g.get('skins', [])
    anims = [
        {'name': a.get('name') or 'anim%d' % i, 'duration_s': round(animation_seconds(g, a), 6)}
        for i, a in enumerate(g.get('animations', []))
    ]
    return {
        'name': name,
        'bytes': os.path.getsize(path),
        'skins': len(skins),
        'joints': len(skins[0]['joints']) if skins else 0,
        'animations': anims,
        'meshes': len(g.get('meshes', [])),
        'mesh_names': sorted(m.get('name') or '' for m in g.get('meshes', [])),
        'height_y': round(body_bbox_y(g, name), 6),
        'frames': frames,
        'fps': fps,
        'first_frame': first_frame,
        'expected_duration_s': round((frames - first_frame + 1) / float(fps), 6),
    }


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------


def select_actor(scene):
    coll = bpy.data.collections.get('actor')
    if coll is None:
        raise RuntimeError(
            'no collection named "actor" (has: %s)' % (', '.join(c.name for c in bpy.data.collections) or 'none')
        )
    if coll.name not in scene.collection.children:
        try:
            scene.collection.children.link(coll)
        except RuntimeError as _exc:
            _zyg_log.debug('collection already linked to the scene: %s', _exc)
    layer = bpy.context.view_layer
    bpy.ops.object.select_all(action='DESELECT')
    picked = []
    # list() first: setting hide_viewport rebuilds the collection's temporary
    # all_objects listbase and iterating it while it is freed crashes Blender.
    for ob in list(coll.all_objects):
        ob.hide_viewport = False
        ob.hide_set(False)
        ob.hide_select = False
        ob.select_set(True)
        picked.append(ob)
    if not picked:
        raise RuntimeError('collection "actor" is empty')
    layer.objects.active = picked[-1]
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--actor', required=True)
    ap.add_argument('--actors-dir', default=ACTORS_DIR)
    ap.add_argument('--out', default='', help='directory for the .glb (default: the actor dir)')
    a = ap.parse_args(argv_after_dashes())

    src_dir = os.path.join(a.actors_dir, a.actor)
    blend = os.path.join(src_dir, '%s.blend' % a.actor)
    meta_path = os.path.join(src_dir, '%s.json' % a.actor)
    for p in (blend, meta_path):
        if not os.path.isfile(p):
            raise SystemExit('missing %s' % p)
    with open(meta_path) as fh:
        meta = json.load(fh)

    frames = int(meta['frames'])
    fps = int(round(float(meta['fps'])))
    rest = meta.get('rest_frame')
    first_frame = int(rest) + 1 if rest else 1  # the rest pose is not playable

    out_dir = a.out or src_dir
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, '%s.glb' % a.actor)

    bpy.ops.wm.open_mainfile(filepath=blend)
    scene = bpy.context.scene
    scene.render.fps, scene.render.fps_base = fps, 1.0
    scene.frame_start, scene.frame_end = first_frame, frames
    scene.frame_set(first_frame)
    picked = select_actor(scene)

    bpy.ops.export_scene.gltf(
        filepath=out,
        export_format='GLB',
        use_selection=True,
        export_animations=True,
        export_skins=True,
        export_yup=True,
        export_apply=False,
        export_frame_range=True,
        export_force_sampling=True,
        export_materials='NONE',
        export_texcoords=True,
        export_normals=True,
        export_draco_mesh_compression_enable=False,
    )

    card = sidecar(out, a.actor, frames, fps, first_frame)
    with open(out + '.json', 'w') as fh:
        json.dump(card, fh, indent=1)

    print(
        '[rig_export] %s: %d objects, frames %d-%d @ %d fps -> %s'
        % (a.actor, len(picked), first_frame, frames, fps, out),
        flush=True,
    )
    print('@@RESULT@@ ' + json.dumps(card), flush=True)


if __name__ == '__main__':
    main()
