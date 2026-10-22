# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""body_plates.py — depth / normal / pose plates for a REGISTERED body.

2026-09-02 (S05). Character Studio's 3D preview is a textured plane in an orbit
scene, and its Body tools had nothing behind them. This module renders the three
conditioning plates a character's own registered cage can supply, at the three
angles the studio offers, so `d_plate` has something true to put behind the
preview plane and `d_angles` has real front/side renders to snap to.

WHAT IS RENDERED, AND WHERE IT COMES FROM
=========================================
The subject is the body already in the registry — `data/assets/mesh_skeletons/
derived/<name>/skeleton_<name>.glb` — never a rebuild. Nothing here re-derives a
body or touches the registry; a plate is a picture OF the registered geometry
and its cage hash is recorded beside it so a stale plate is detectable.

Cameras follow geom/mv_render's turntable convention exactly (az 0 = the FRONT,
az increasing toward +X, elevation 0, target at half stature), because a plate
rendered on a different convention is a plate of a different pose.

Channels follow geom/conditioning's conventions, and are produced BY that module
from real Cycles AOVs rather than re-implemented here — the pufferball passes
were re-wired by hand once and came back with X/Y/Z-named channels that nothing
could read:

    depth.png   near = white, normalised over the SUBJECT's range
    normal.png  camera-space, (n*0.5+0.5)*255
    pose.png    an OpenPose-style stick figure

THE POSE PLATE IS NOT AVAILABLE TODAY, AND SAYS SO
==================================================
A four-state ledger, not a silent gap. Measured on the registered bodies
2026-09-02: `skeleton_abel.glb` has 2 nodes ('world', 'geometry_0') and 0 skins,
i.e. the exported cage carries NO ARMATURE. An OpenPose plate needs joint
positions, and there are none in the file. So `pose` is written into the
manifest as state `unavailable` with that reason, and no PNG is produced —
rather than a stick figure inferred from the silhouette, which would be a
drawing of a guess presented as a measurement.

Reaching it needs joints from somewhere that has them: Anny's rig under
/usr/bin/python3.12 (the only interpreter that can import it), or S02's
geom.anny_fit. That is a build, not a flag.

STATES a channel can be in, per view:
    found          the PNG is on disk and its source pass was real
    not_found      the pass rendered but the channel came back empty
    unmeasurable   the render or the read failed (reason recorded)
    unavailable    the input does not exist at all (the pose case)

CLI:
    python -m zyg_workflows.geom.body_plates abel
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile

from zyg_workflows import paths

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MESH_ROOT = os.path.realpath(os.path.join(HERE, 'data', 'assets', 'mesh_skeletons'))
CHARS_ROOT = os.path.realpath(paths.ZYG_STORYTELLER_CHARS)
BLENDER = os.environ.get('ZYG_BLENDER', str(paths.BLENDER_BIN))

MANIFEST = 'plates.json'
KINDS = ('depth', 'normal', 'matte', 'pose')

# az/el in the mv_render frame: az 0 is the FRONT, az grows toward +X.
VIEWS = {
    'front': {'az': 0.0, 'el': 0.0, 'label': 'front'},
    'q45': {'az': 45.0, 'el': 0.0, 'label': 'three-quarter'},
    'side': {'az': 90.0, 'el': 0.0, 'label': 'side'},
}


def _log(fn):
    return fn or (lambda _m: None)


# ── where things live ───────────────────────────────────────────────────────
def registry():
    with open(os.path.join(MESH_ROOT, 'registry.json'), encoding='utf-8') as fh:
        return json.load(fh)


def body_record(name):
    """-> (record, glb_path) for a registered body, or (None, '')."""
    reg = registry()
    for bucket in ('derived', 'originals'):
        rec = (reg.get(bucket) or {}).get(name)
        if rec:
            glb = os.path.join(MESH_ROOT, rec.get('dir', ''), rec.get('glb', ''))
            return rec, (glb if os.path.isfile(glb) else '')
    return None, ''


def plates_dir(name, char_id=None):
    """The plates/ folder for a body — the CHARACTER's dataset when one is
    linked, so a plate travels with the imagery it conditions, and the body's
    own registry folder otherwise.

    The registry keys bodies by a friendly name ('abel'), while a storyteller
    dataset is keyed by a hash id ('c3345deb5bde'), and nothing on disk records
    the link between them. So the link is passed IN by the caller that knows it
    (character_studio.resolve_body reports how it resolved), and a body with no
    linked character keeps its plates beside its own GLB rather than inventing a
    dataset folder named after the registry."""
    if char_id:
        d = os.path.join(CHARS_ROOT, char_id)
        if os.path.isdir(d):
            return os.path.join(d, 'plates')
    d = os.path.join(CHARS_ROOT, name)
    if os.path.isdir(d):
        return os.path.join(d, 'plates')
    # NOT under data/assets/mesh_skeletons/: that tree belongs to the registry
    # and its gate reports, and a render cache does not go in someone else's
    # namespace. output/body_plates/<name>/ is this module's own space.
    return os.path.join(HERE, 'output', 'body_plates', name)


def path_for(name, view, kind, char_id=None):
    return os.path.join(plates_dir(name, char_id), f'{view}_{kind}.png')


def manifest_path(name, char_id=None):
    return os.path.join(plates_dir(name, char_id), MANIFEST)


def load_manifest(name, char_id=None):
    try:
        with open(manifest_path(name, char_id), encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# ── the Blender half ────────────────────────────────────────────────────────
_BL_SCRIPT = r"""
import json, math, os, sys
import bpy, mathutils

CFG = json.load(open(sys.argv[sys.argv.index('--') + 1]))
sys.path.insert(0, CFG['crews'])
sys.path.insert(0, os.path.join(CFG['crews'], 'prop_mesh'))
import pass_lib

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = 'CYCLES'
sc.cycles.device = 'CPU'
sc.render.resolution_x = CFG['size']
sc.render.resolution_y = CFG['size']
sc.render.resolution_percentage = 100
sc.render.film_transparent = True
sc.world = bpy.data.worlds.new('w')
sc.world.use_nodes = True
sc.world.node_tree.nodes['Background'].inputs[0].default_value = (0.05, 0.05, 0.05, 1)

bpy.ops.import_scene.gltf(filepath=CFG['glb'])
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not meshes:
    raise SystemExit('no mesh in %s' % CFG['glb'])
# pass_index 1 = the body. pass_lib.tag() is NOT used: its IDX is prop_mesh's
# own object vocabulary (trunk/axe_head/...) and 'body' is not in it, so tagging
# through it is a hard KeyError by that module's own design. Setting the index
# directly is the same one line without borrowing someone else's vocabulary.
for ob in meshes:
    ob.pass_index = 1

# One flat grey material: the data passes must not be modulated by albedo.
mat = bpy.data.materials.new('plate_grey')
mat.use_nodes = True
bsdf = mat.node_tree.nodes['Principled BSDF']
bsdf.inputs['Base Color'].default_value = (0.5, 0.5, 0.5, 1)
bsdf.inputs['Roughness'].default_value = 0.9
for ob in meshes:
    ob.data.materials.clear()
    ob.data.materials.append(mat)

def _bbox():
    lo = mathutils.Vector((1e9, 1e9, 1e9))
    hi = mathutils.Vector((-1e9, -1e9, -1e9))
    for ob in meshes:
        for c in ob.bound_box:
            w = ob.matrix_world @ mathutils.Vector(c)
            lo = mathutils.Vector((min(lo[k], w[k]) for k in range(3)))
            hi = mathutils.Vector((max(hi[k], w[k]) for k in range(3)))
    return lo, hi

# UP-AXIS CORRECTION. mesh_skeletons exports the cage Z-UP into a glTF, and
# glTF is Y-up by definition, so Blender's importer applies its Y-up -> Z-up
# rotation to a file that never needed one and the body arrives LYING DOWN.
# Measured on skeleton_abel.glb: the registry records stature 1.52 m, the file's
# POSITION accessor spans 1.5200 in Z and 0.3922 in Y, and after import the
# Blender Z extent was 0.3922 — the thickness, not the stature. Every camera
# would then have been aimed along the body's length.
#
# The correction is decided by MEASUREMENT against a number that already exists
# (params.measured.height_m), never by a guess about which axis looks tallest:
# rotate only when the vertical extent misses the recorded stature AND the depth
# extent hits it.
lo, hi = _bbox()
stature = float(CFG.get('stature') or 0.0)
up_fix = 'none'
if stature > 0:
    ez, ey = hi[2] - lo[2], hi[1] - lo[1]
    if abs(ez - stature) > 0.05 * stature and abs(ey - stature) <= 0.05 * stature:
        # UNDO the importer's rotation, don't re-assign it. The glTF importer
        # expresses its Y-up -> Z-up conversion AS rotation_euler=(90,0,0) on the
        # imported object, so `ob.rotation_euler = (90,0,0)` is a no-op — the
        # first attempt did exactly that and the re-measured height came back
        # 0.3922 unchanged, with coverage byte-identical to the unrotated render.
        # Pre-multiplying by Rx(-90) is a DELTA and works whatever the importer
        # chose to do.
        undo = mathutils.Matrix.Rotation(math.radians(-90), 4, 'X')
        for ob in meshes:
            ob.matrix_world = undo @ ob.matrix_world
        bpy.context.view_layer.update()
        lo, hi = _bbox()
        up_fix = 'un-rotated -90 about X: the glTF was authored Z-up'
        # and PROVE it landed, rather than trusting the assignment
        got = hi[2] - lo[2]
        if abs(got - stature) > 0.05 * stature:
            raise SystemExit('up-axis correction did not land: vertical extent %.4f '
                             'against a recorded stature of %.4f' % (got, stature))
target = (lo + hi) * 0.5
height = max(hi[2] - lo[2], 1e-4)

cam_d = bpy.data.cameras.new('cam')
cam_d.lens = 50.0
# sensor_fit AUTO makes the LARGER render dimension use sensor_width (36), so on
# a square frame the vertical FOV is governed by 36 and not by sensor_height
# (24) — the distance below divides by sensor_height, and the mismatch made
# `fill` under-deliver by exactly 24/36: 0.82 asked for, 0.55 measured. VERTICAL
# makes sensor_height genuinely govern the vertical FOV, so the dial means what
# it says.
cam_d.sensor_fit = 'VERTICAL'
cam = bpy.data.objects.new('cam', cam_d)
sc.collection.objects.link(cam)
sc.camera = cam
# The figure fills CFG['fill'] of the frame height at this focal length.
dist = (height / CFG['fill']) * (cam_d.lens / cam_d.sensor_height)

key = bpy.data.objects.new('key', bpy.data.lights.new('key', type='SUN'))
key.data.energy = 3.0
sc.collection.objects.link(key)
key.rotation_euler = (math.radians(55), 0, math.radians(35))

out = {}
for vid, v in CFG['views'].items():
    a, e = math.radians(v['az']), math.radians(v['el'])
    cam.location = target + mathutils.Vector((dist * math.cos(e) * math.sin(a),
                                              -dist * math.cos(e) * math.cos(a),
                                              dist * math.sin(e)))
    cam.rotation_euler = (target - cam.location).to_track_quat('-Z', 'Y').to_euler()
    d = pass_lib.render_set(vid, CFG['passdir'], scene=sc, samples=CFG['samples'])
    # conditioning.normal_map does `n @ r`, i.e. n_cam[i] = n_world . r[:, i],
    # so `r` must have the camera basis in its COLUMNS. Iterating a Blender
    # Matrix yields ROWS, so the matrix is serialised untransposed. Transposing
    # here (the first attempt did) is one transpose too many and produces
    # exactly the world-space signature normal_map's docstring warns about:
    # measured front mean B=31 against the reference sheet's 215.
    out[vid] = {'dir': d,
                'cam_r': [list(r) for r in cam.matrix_world.to_3x3()]}
json.dump({'views': out, 'height_m': height, 'up_fix': up_fix,
           'target': list(target), 'dist': dist}, open(CFG['report'], 'w'), indent=1)
print('BODY_PLATES_OK')
"""


def _run_blender(cfg, log):
    with tempfile.TemporaryDirectory() as td:
        sp = os.path.join(td, 'plate_render.py')
        cp = os.path.join(td, 'cfg.json')
        with open(sp, 'w', encoding='utf-8') as fh:
            fh.write(_BL_SCRIPT)
        with open(cp, 'w', encoding='utf-8') as fh:
            json.dump(cfg, fh)
        cmd = [BLENDER, '-b', '--factory-startup', '-P', sp, '--', cp]
        log('[plates] ' + ' '.join(cmd))
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if 'BODY_PLATES_OK' not in (r.stdout or ''):
            tail = ((r.stdout or '') + (r.stderr or ''))[-2500:]
            raise RuntimeError(f'blender failed (exit {r.returncode}):\n{tail}')
        with open(cfg['report'], encoding='utf-8') as fh:
            return json.load(fh)


# ── build ───────────────────────────────────────────────────────────────────
def build(name, views=None, size=768, samples=24, fill=0.82, force=False, char_id=None, log_fn=None):
    """Render the plates for one registered body. Returns the manifest dict.

    Never re-derives: the input is the registered GLB and its recorded cage hash
    goes into the manifest, so a plate that predates a reissue is detectable
    rather than merely old."""
    log = _log(log_fn)
    rec, glb = body_record(name)
    if rec is None:
        raise ValueError(f'not a registered body: {name!r}')
    if not glb:
        raise ValueError(f'{name}: registered GLB is missing on disk')
    vids = list(views or VIEWS)
    bad = [v for v in vids if v not in VIEWS]
    if bad:
        raise ValueError(f'unknown views {bad} (have {sorted(VIEWS)})')

    d = plates_dir(name, char_id)
    os.makedirs(d, exist_ok=True)
    cage = (rec.get('params') or {}).get('cage_vert_sha256') or ''
    old = load_manifest(name, char_id)
    if (
        old
        and not force
        and old.get('cage_vert_sha256') == cage
        and all(os.path.isfile(path_for(name, v, k, char_id)) for v in vids for k in ('depth', 'normal', 'matte'))
    ):
        log(f'[plates] {name}: up to date ({len(vids)} views) — nothing rendered')
        return old

    import zyg_workflows.geom.conditioning as COND
    import zyg_workflows.geom.passes_io as PIO

    with tempfile.TemporaryDirectory() as td:
        stature = float(((rec.get('params') or {}).get('measured') or {}).get('height_m') or 0.0)
        cfg = {
            'crews': HERE,
            'glb': glb,
            'size': int(size),
            'samples': int(samples),
            'fill': float(fill),
            'passdir': td,
            'stature': stature,
            'report': os.path.join(td, 'report.json'),
            'views': {v: VIEWS[v] for v in vids},
        }
        rep = _run_blender(cfg, log)

        out_views, ledger = {}, {}
        for vid in vids:
            entry, st = {'az': VIEWS[vid]['az'], 'el': VIEWS[vid]['el']}, {}
            pdir = (rep['views'].get(vid) or {}).get('dir') or ''
            try:
                ps = PIO.load_set(pdir)
            except Exception as exc:  # noqa: BLE001
                for k in ('depth', 'normal', 'matte'):
                    st[k] = {'state': 'unmeasurable', 'why': f'{type(exc).__name__}: {exc}'}
                st['pose'] = _pose_state(glb)
                ledger[vid] = st
                out_views[vid] = entry
                continue
            cam_r = (rep['views'].get(vid) or {}).get('cam_r')
            # The mask is the SUBJECT, not the frame: without it depth normalises
            # over a background whose depth is nan/far and the figure comes back
            # as a flat near-white blob. index 1 is the body (set in the render
            # script above); ps.valid drops the transparent film.
            mask = ps.mask(1)
            if not mask.any():
                mask = ps.valid & (ps.index > 0)
            entry['coverage'] = round(float(mask.mean()), 5)
            maps = COND.maps_for(ps, mask=mask, cam=cam_r)
            maps['matte'] = mask.astype('uint8') * 255
            for k in ('depth', 'normal', 'matte'):
                img = maps.get(k)
                dst = path_for(name, vid, k, char_id)
                if img is None:
                    st[k] = {'state': 'not_found', 'why': 'conditioning produced no map for this pass'}
                    continue
                try:
                    from PIL import Image

                    Image.fromarray(img).save(dst)
                    entry[k] = os.path.basename(dst)
                    st[k] = {'state': 'found'}
                except Exception as exc:  # noqa: BLE001
                    st[k] = {'state': 'unmeasurable', 'why': f'{type(exc).__name__}: {exc}'}
            st['pose'] = _pose_state(glb)
            ledger[vid] = st
            out_views[vid] = entry

    man = {
        'name': name,
        'glb': glb,
        'cage_vert_sha256': cage,
        'size': int(size),
        'samples': int(samples),
        'fill': float(fill),
        'height_m': rep.get('height_m'),
        'stature_recorded_m': stature,
        'up_fix': rep.get('up_fix', 'none'),
        'camera': 'geom/mv_render turntable — az 0 = front, az grows toward +X',
        'conventions': {
            'depth': 'near = white, normalised over the subject',
            'normal': 'camera-space, (n*0.5+0.5)*255',
        },
        'views': out_views,
        'ledger': ledger,
    }
    man['char_id'] = char_id or ''
    with open(manifest_path(name, char_id), 'w', encoding='utf-8') as fh:
        json.dump(man, fh, indent=2)
        fh.write('\n')
    log(f'[plates] {name}: {len(out_views)} views -> {d}')
    return man


def _pose_state(glb):
    """The pose channel's honest state, measured off the GLB rather than assumed.

    A glTF with no `skins` array carries no joints; an OpenPose plate from such a
    file could only be inferred from the silhouette, which is a guess drawn to
    look like a measurement."""
    try:
        import struct

        with open(glb, 'rb') as fh:
            fh.read(12)
            clen = struct.unpack('<II', fh.read(8))[0]
            j = json.loads(fh.read(clen).decode('utf-8'))
        n_sk, n_nd = len(j.get('skins') or []), len(j.get('nodes') or [])
        if n_sk:
            return {'state': 'not_found', 'why': f'{n_sk} skin(s) present but no plate writer built yet'}
        return {
            'state': 'unavailable',
            'why': f'the registered GLB carries no armature ({n_nd} nodes, 0 skins), '
            'so there are no joints to project. Joints would have to come '
            "from Anny's rig under /usr/bin/python3.12 or from geom.anny_fit.",
        }
    except Exception as exc:  # noqa: BLE001
        return {'state': 'unmeasurable', 'why': f'{type(exc).__name__}: {exc}'}


def ensure(name, char_id=None, **kw):
    """The existing manifest, or build one."""
    man = load_manifest(name, char_id)
    if man:
        return man
    return build(name, char_id=char_id, **kw)


def is_plate_path(name, path, char_id=None):
    """True only for a path that IS one of this body's rendered plates.

    The validation behind the writable pose-reference field: the point is not
    that the string looks like a path, it is that the file is a render this
    module produced for THIS character."""
    if not path:
        return False
    full = os.path.realpath(path)
    d = os.path.realpath(plates_dir(name, char_id))
    if not full.startswith(d + os.sep) or not os.path.isfile(full):
        return False
    return os.path.basename(full) in {f'{v}_{k}.png' for v in VIEWS for k in KINDS}


def registered_names():
    reg = registry()
    return sorted(set(reg.get('derived') or {}) | set(reg.get('originals') or {}))


if __name__ == '__main__':  # the CLI lives in body_plates_cli
    from zyg_workflows.geom.body_plates_cli import _main as _cli_main

    raise SystemExit(_cli_main())
