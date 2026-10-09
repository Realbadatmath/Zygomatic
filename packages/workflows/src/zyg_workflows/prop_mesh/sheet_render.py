# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sheet_render.py — ANY GLB to the registrable 16-view sheet, in Blender.

    blender -b --factory-startup -P prop_mesh/sheet_render.py -- \
        --glb <file.glb> --out <build_dir> [--samples 48] [--res 1024] ...

WHY THIS EXISTS.
The mesh-to-control path is proven — a Cycles depth pass steers klein and Qwen far
above chance — but exactly ONE asset could ever be fed into it, because the only
renderer that emits a registrable sheet is `pufferball_sheet.py`, which imports the
Pufferball build module and its look patches at the top of the file. `hurlbat_sheet.py`
renders three angles and no passes at all. So the library had one entry and no way to
gain a second without writing another creature-specific script.

This script has NO subject-specific knowledge. It takes a GLB in metres, and emits
exactly what `prop_mesh_library.register` and `mesh_control.build` need:

  beauty/<view>.png                 the shaded render, directly usable as a tile
  passes/<view>_{depth,normal,index}_0001.exr    32-bit, one flat folder
  sheet.json                        views[] with id/azimuth/elevation/framing/
                                    distance_m/cam_r, plus `idx`, `size_m` and the
                                    per-part visible pixel counts

THREE THINGS THAT ARE EASY TO GET WRONG, AND ARE THEREFORE DONE HERE.

1. NORMAL CHANNELS. Blender's Normal socket is a VECTOR, so wired straight to a File
   Output the EXR channels are named X/Y/Z; cv2 resolves one of them and passes_io
   correctly refuses to call one component a normal. 16 unreadable EXRs shipped that
   way once already (2026-08-26). The wiring goes through
   `pass_lib.rgb_named_socket`, which is the one place that knowledge lives.

2. `cam_r`, THE CAMERA'S WORLD ROTATION, PER VIEW. The Normal AOV is world-space.
   Without the rotation matrix a consumer cannot take it to camera space, and a
   world-space normal map is not valid ControlNet input — it swings hue as the object
   turns instead of staying blue. mesh_control reads this key by name and honestly
   labels the map `normal_space: world` when it is missing.

3. AN INDEX VOCABULARY WITH `ground` IN IT. Every conditioning map normalises over
   whatever counts as the subject, and a turntable renders a floor. `mesh_control`'s
   default exclude is the NAME 'ground', looked up in this sheet's own `idx`. A sheet
   that omits it hands the floor 89% of the depth range and warns, but still writes
   maps the whole pipeline will then quietly use.

PARTS AND THE VOCABULARY. A GLB's node names are the only part names that exist, and
they are frequently useless ('Group', 'Group_1', a bare UUID). They are sanitised and
de-duplicated rather than invented: an honest ugly name beats a guessed pretty one.
Above `--max-parts` distinct nodes the vocabulary collapses to a single `subject`
index — the alternative is a 300-entry `idx` that no exclude list can ever use.

VISIBILITY. Every part that is in the scene and renderable must own pixels in at least
one view's IndexOB pass. This is the cheapest check in the pipeline and the one that
would have caught the Pufferball's buried mouth on day one. It is a hard failure here
(exit 3) unless `--allow-hidden-parts`, because a part visible in none of 16 views is a
build problem, and a sheet that ships anyway defers the discovery to whatever renders
from it.

UNITS AND ORIENTATION. glTF is Y-up; Blender's importer converts to Z-up, so the sheet
is in the same frame the build scripts and `geometry_stats` report. The mesh is placed
with its base on z=0 and centred in x/y — the camera solve frames the bounding box, so
a model authored 40 m from its own origin still fills the frame.
"""

import glob
import json
import math
import os
import re
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pass_lib as PL  # noqa: E402
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# ── args ─────────────────────────────────────────────────────────────────────
def _argv():
    return sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []


def _opt(args, name, default, cast=float):
    if name in args:
        return cast(args[args.index(name) + 1])
    return default


ARGS = _argv()
GLB = _opt(ARGS, '--glb', '', str)
OUT = _opt(ARGS, '--out', '', str)
NAME = _opt(ARGS, '--name', '', str) or os.path.splitext(os.path.basename(GLB))[0]
W = int(_opt(ARGS, '--res', 1024))
H = int(_opt(ARGS, '--res-h', W))
SAMPLES = int(_opt(ARGS, '--samples', 48))
SCALE = float(_opt(ARGS, '--scale', 1.0))
MAX_PARTS = int(_opt(ARGS, '--max-parts', 24))
TURNTABLE = int(_opt(ARGS, '--turntable', 0))
ONLY_VIEWS = [v for v in _opt(ARGS, '--views', '', str).split(',') if v]
ALLOW_HIDDEN = '--allow-hidden-parts' in ARGS
WANT_PASSES = '--no-passes' not in ARGS
MANIFEST_ONLY = '--manifest-only' in ARGS
GPU = '--cpu' not in ARGS
NO_GROUND = '--no-ground' in ARGS
# Substrings of node names to drop before anything is measured. The one real use is fur:
# a look layer's lock/tuft/wisp meshes are ~280k vertices reaching 120 mm past the body,
# so a bounding box over them describes the coat and not the animal (0.70 m wide against
# a 0.37 m body), and every camera distance is solved from that box.
DROP = [t for t in _opt(ARGS, '--drop-nodes', '', str).split(',') if t]

if not GLB or not os.path.isfile(GLB):
    raise SystemExit('--glb: no such file: %r' % GLB)
if not OUT:
    raise SystemExit('--out is required')

BEAUTY = os.path.join(OUT, 'beauty')
PASSES = os.path.join(OUT, 'passes')
os.makedirs(BEAUTY, exist_ok=True)
if WANT_PASSES:
    os.makedirs(PASSES, exist_ok=True)


# (id, azimuth°, elevation°, framing) — azimuth 0 = front (camera at -Y),
# positive = orbit to the subject's left. THE SAME 16 ids, angles and framings the
# Pufferball sheet uses and `creature_sheet_service.ANGLES` names, so a consumer that
# asks for 'top_down' gets the same viewpoint on every asset in the library.
VIEWS = [
    ('front_full', 0, 6, 'body'),
    ('q45_left', 45, 6, 'body'),
    ('q45_right', -45, 6, 'body'),
    ('side_left', 90, 6, 'body'),
    ('side_right', -90, 6, 'body'),
    ('back_q_left', 135, 6, 'body'),
    ('back_q_right', -135, 6, 'body'),
    ('back', 180, 6, 'body'),
    ('high_front', 0, 42, 'body'),
    ('low_front', 0, -22, 'body'),
    ('top_down', 0, 82, 'body'),
    ('close_front', 0, 4, 'head'),
    ('close_q_left', 38, 4, 'head'),
    ('close_q_right', -38, 4, 'head'),
    ('wide', 22, 8, 'wide'),
    ('detail', 14, 2, 'detail'),
]

FRAMING = {  # (fill fraction of frame, focal length mm, aim height frac)
    'body': (0.74, 85.0, 0.50),
    'head': (0.95, 105.0, 0.78),
    'wide': (0.34, 60.0, 0.45),
    'detail': (2.10, 135.0, 0.72),
}


# ── scene ────────────────────────────────────────────────────────────────────
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

bpy.ops.import_scene.gltf(filepath=GLB)
subject = [o for o in bpy.context.scene.collection.all_objects if o.type == 'MESH']
if DROP:
    _drop = [o for o in subject if any(t in o.name for t in DROP)]
    for o in _drop:
        bpy.data.objects.remove(o, do_unlink=True)
    subject = [o for o in subject if o not in _drop]
    _zyg_log.info('SR_DROP %d node(s): %s' % (len(_drop), ','.join(sorted(o.name for o in _drop))[:200]))
if not subject:
    raise SystemExit('no mesh objects in %s' % GLB)
# The importer may leave empties parenting the meshes; the meshes are the asset, so
# every transform is baked down and the hierarchy is discarded. Otherwise a later
# `matrix_world` read (bounds, export) has to walk parents that no longer exist once
# the objects are unlinked into the scene collection.
for ob in subject:
    ob.matrix_world = ob.matrix_world.copy()
    if ob.parent is not None:
        mw = ob.matrix_world.copy()
        ob.parent = None
        ob.matrix_world = mw


def bounds(objs):
    lo = Vector((1e18, 1e18, 1e18))
    hi = Vector((-1e18, -1e18, -1e18))
    for ob in objs:
        for corner in ob.bound_box:
            w = ob.matrix_world @ Vector(corner)
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    return lo, hi


if SCALE != 1.0:
    for ob in subject:
        ob.scale = ob.scale * SCALE
    bpy.context.view_layer.update()

# Base on z=0, centred in x/y. A scan authored far from its own origin otherwise
# renders as an empty frame with a correct-looking camera solve.
_lo, _hi = bounds(subject)
_shift = Vector((-(_lo.x + _hi.x) * 0.5, -(_lo.y + _hi.y) * 0.5, -_lo.z))
for ob in subject:
    ob.location = ob.location + _shift
bpy.context.view_layer.update()

lo, hi = bounds(subject)
centre = (lo + hi) * 0.5
size = max((hi - lo).x, (hi - lo).y, (hi - lo).z)
if size <= 0:
    raise SystemExit('degenerate bounding box on %s' % GLB)

# Every subject vertex in WORLD space, gathered once. `place()` projects these onto the
# camera's right/up axes so each view is framed on the SILHOUETTE it actually sees
# rather than on the bounding box's largest dimension: looking down an elongated
# subject's long axis otherwise under-fills the frame, which is how the gorilla
# cranium's top_down control map came out 91% background. 300k vertices is a few MB and
# one projection per unique (azimuth, elevation).
try:
    import numpy as _npv
except Exception:  # noqa: BLE001
    _npv = None
WORLD_VERTS = None
if _npv is not None:
    _chunks = []
    for ob in subject:
        _n = len(ob.data.vertices)
        if _n == 0:
            continue
        _buf = _npv.empty(_n * 3, dtype=_npv.float64)
        ob.data.vertices.foreach_get('co', _buf)
        _m = ob.matrix_world
        _M = _npv.array([[_m[i][j] for j in range(4)] for i in range(3)], dtype=_npv.float64)
        _chunks.append(_buf.reshape(_n, 3) @ _M[:, :3].T + _M[:, 3])
    if _chunks:
        WORLD_VERTS = _npv.concatenate(_chunks, axis=0)
_zyg_log.info('SR_VERTS %s' % ('none' if WORLD_VERTS is None else len(WORLD_VERTS)))


# ── the index vocabulary ─────────────────────────────────────────────────────
def _slug(s):
    s = re.sub(r'[^0-9a-zA-Z]+', '_', str(s)).strip('_').lower()
    return s or 'part'


# `ground` is index 1 on every sheet this script writes and is never taken by a mesh,
# because mesh_control's default exclude looks it up BY NAME and a sheet that renames
# it silently stops excluding the floor.
IDX = {'ground': 1}
names = []
for ob in subject:
    n = _slug(ob.name)
    if n in ('ground', 'floor'):
        n = n + '_mesh'
    names.append(n)
distinct = sorted(set(names))
if len(distinct) > MAX_PARTS:
    # A 300-node scan gets ONE name. An `idx` nobody can write an exclude list against
    # is not a vocabulary, and the visibility check on 300 parts is noise.
    IDX['subject'] = 2
    for ob in subject:
        ob.pass_index = 2
    _zyg_log.info(
        'SR_PARTS collapsed %d nodes -> one `subject` index (over --max-parts %d)' % (len(distinct), MAX_PARTS)
    )
else:
    for i, n in enumerate(distinct):
        IDX[n] = i + 2
    for ob, n in zip(subject, names):
        ob.pass_index = IDX[n]
    _zyg_log.info('SR_PARTS %s' % json.dumps(IDX))

# ── ground, world, lights ────────────────────────────────────────────────────
ground_ob = None
if not NO_GROUND:
    bpy.ops.mesh.primitive_plane_add(size=max(size * 8.0, 0.5), location=(0, 0, 0))
    ground_ob = bpy.context.active_object
    ground_ob.name = 'sr_ground'
    ground_ob.pass_index = IDX['ground']
    gm = bpy.data.materials.new('sr_ground_mat')
    gm.use_nodes = True
    bsdf = gm.node_tree.nodes.get('Principled BSDF')
    if bsdf:
        bsdf.inputs['Base Color'].default_value = (0.09, 0.10, 0.12, 1)
        bsdf.inputs['Roughness'].default_value = 0.86
    ground_ob.data.materials.append(gm)

world = bpy.data.worlds.new('w')
world.use_nodes = True
world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.055, 0.065, 0.085, 1)
world.node_tree.nodes['Background'].inputs['Strength'].default_value = 1.0
scene.world = world


def area(name, loc, energy, sz):
    """One area light aimed at the subject centre. Energy is scaled by area^2 so the
    same rig reads the same on a 3 cm shard and a 2 m cannon — a fixed wattage over a
    50x size range is the difference between a black frame and a white one."""
    ld = bpy.data.lights.new(name, 'AREA')
    ld.energy = energy
    ld.size = sz
    ob = bpy.data.objects.new(name, ld)
    ob.location = Vector(loc)
    d = centre - ob.location
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = d.normalized().to_track_quat('-Z', 'Y')
    scene.collection.objects.link(ob)
    return ob


_e = size * size * 900.0  # W, scales with the lit area
area('key', (centre.x - size * 1.5, centre.y - size * 1.8, centre.z + size * 1.5), _e * 1.0, size * 1.4)
area('fill', (centre.x + size * 2.0, centre.y - size * 1.2, centre.z + size * 0.6), _e * 0.35, size * 2.0)
area('rim', (centre.x + size * 0.4, centre.y + size * 2.2, centre.z + size * 1.9), _e * 0.55, size * 1.2)

# ── camera + render settings ─────────────────────────────────────────────────
cam_d = bpy.data.cameras.new('cam')
cam_d.sensor_width = 36.0
cam = bpy.data.objects.new('cam', cam_d)
scene.collection.objects.link(cam)
scene.camera = cam

scene.render.engine = 'CYCLES'
scene.render.resolution_x, scene.render.resolution_y = W, H
scene.render.resolution_percentage = 100
scene.render.film_transparent = False
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
try:
    scene.view_settings.view_transform = 'Filmic'
except TypeError as _exc:
    _zyg_log.debug('Filmic view transform unavailable, keeping the default: %s', _exc)

if GPU:
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        for kind in ('OPTIX', 'CUDA'):
            try:
                prefs.compute_device_type = kind
                prefs.get_devices()
                if any(d.type == kind for d in prefs.devices):
                    for d in prefs.devices:
                        d.use = d.type == kind
                    scene.cycles.device = 'GPU'
                    _zyg_log.info('SR_DEVICE %s' % kind)
                    break
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.debug('cycles device kind %s unusable, trying the next one: %s', kind, _exc)
                continue
        else:
            scene.cycles.device = 'CPU'
            _zyg_log.info('SR_DEVICE CPU (no OPTIX/CUDA)')
    except Exception as exc:  # noqa: BLE001
        scene.cycles.device = 'CPU'
        _zyg_log.info('SR_DEVICE CPU (%s)' % exc)
else:
    scene.cycles.device = 'CPU'
    _zyg_log.info('SR_DEVICE CPU (forced)')


# Solved silhouette extents keyed by (azimuth°, elevation°). The orbit angles fix the
# camera's ORIENTATION independently of its distance, so the projection is the same for
# every framing at one angle pair — and the turntable path asks for 32-96 views off a
# single elevation, where recomputing a 300k-vertex projection each time is pure waste.
_EXTENT_CACHE = {}


def _axis(r, j):
    """Column j of a 3x3 world rotation as a numpy vector — the camera's world-space
    right (0) and up (1). Columns, not rows: Blender maps a LOCAL vector to world with
    `r @ v`, so the local basis lives in the columns."""
    return _npv.array([r[0][j], r[1][j], r[2][j]], dtype=_npv.float64)


def _project_extent(right, up):
    """(width, height) of the subject's silhouette in the camera plane, in metres."""
    w = WORLD_VERTS @ right
    h = WORLD_VERTS @ up
    return float(w.max() - w.min()), float(h.max() - h.min())


def place(az_deg, el_deg, framing):
    """Orbit the camera to (azimuth, elevation) and frame the subject.

    Distance is solved from the sensor/focal so `fill` means the same thing at every
    angle — otherwise the subject would breathe in and out around the orbit and a sheet
    used for training would teach scale drift along with form.

    The size that `fill` fills is the extent of the silhouette SEEN FROM THIS ANGLE, not
    the bounding box's largest dimension. Framing every view on one number is what left
    the gorilla cranium's top_down cell 91% background: the box's largest dimension is
    the cranium's length, which a camera looking straight down the length cannot see."""
    fill, lens, aim_z = FRAMING[framing]
    cam_d.lens = lens
    az, el = math.radians(az_deg), math.radians(el_deg)
    fov = 2.0 * math.atan(0.5 * cam_d.sensor_width / lens)
    tgt = Vector((centre.x, centre.y, lo.z + (hi.z - lo.z) * aim_z))

    def solve(sz):
        return (sz / max(fill, 1e-3)) * 0.5 / math.tan(fov * 0.5)

    def aim(dist):
        cam.location = tgt + Vector(
            (dist * math.cos(el) * math.sin(az), -dist * math.cos(el) * math.cos(az), dist * math.sin(el))
        )
        cam.rotation_mode = 'QUATERNION'
        cam.rotation_quaternion = (tgt - cam.location).normalized().to_track_quat('-Z', 'Y')
        bpy.context.view_layer.update()

    sv1 = sv2 = None
    if WORLD_VERTS is not None:
        key = (round(az_deg, 6), round(el_deg, 6))
        hit = _EXTENT_CACHE.get(key)
        if hit is None:
            # Pass 1 off the analytic orientation: the camera looks from +d back at the
            # target, and `-d` is the direction it faces.
            d = Vector((math.cos(el) * math.sin(az), -math.cos(el) * math.cos(az), math.sin(el)))
            e1 = _project_extent(*[_axis((-d).to_track_quat('-Z', 'Y').to_matrix(), j) for j in (0, 1)])
            sv1 = max(e1)
            # Pass 2 off the camera's OWN matrix once it is standing at the pass-1
            # distance. Orientation does not depend on distance, so this converges at
            # once; it is run and recorded anyway, so that a later change to how the
            # camera aims shows up as a gap between the two instead of passing silently.
            aim(solve(sv1))
            r2 = cam.matrix_world.to_3x3().normalized()
            e2 = _project_extent(_axis(r2, 0), _axis(r2, 1))
            sv2 = max(e2)
            _EXTENT_CACHE[key] = (sv1, sv2)
        else:
            sv1, sv2 = hit

    sz = sv2 if sv2 and sv2 > 1e-9 else size
    dist = solve(sz)
    aim(dist)
    cam_d.clip_start = max(dist * 1e-4, 1e-5)
    cam_d.clip_end = max(dist * 20.0, 100.0)
    bpy.context.view_layer.update()
    return dist, {
        'size_view_m': round(sz, 5),
        'size_view_pass1_m': None if sv1 is None else round(sv1, 5),
        'size_view_pass2_m': None if sv2 is None else round(sv2, 5),
        'size_box_m': round(size, 5),
        'distance_pass1_m': None if sv1 is None else round(solve(sv1), 4),
    }


def cam_rotation():
    """The camera's 3x3 world rotation, row-major, as plain floats. Recorded per view
    so a consumer can rotate the world-space Normal AOV into CAMERA space; see the
    module docstring."""
    r = cam.matrix_world.to_3x3().normalized()
    return [[float(r[i][j]) for j in range(3)] for i in range(3)]


def enable_passes():
    """Compositor: Render Layers -> one 32-bit EXR File Output slot per pass.

    The slot names carry the VIEW id (set per view in the loop below), which is why
    this cannot call pass_lib.render_set(): that writes one directory per view with
    fixed names, and a 16-angle sheet wants one flat passes/ folder addressed as
    <view>_<kind>_*.exr. It DOES delegate channel naming to rgb_named_socket."""
    for vl in scene.view_layers:
        vl.use_pass_z = True
        vl.use_pass_normal = True
        vl.use_pass_object_index = True
    scene.use_nodes = True
    nt = scene.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    rl = nt.nodes.new('CompositorNodeRLayers')
    out = nt.nodes.new('CompositorNodeOutputFile')
    out.base_path = PASSES
    out.format.file_format = 'OPEN_EXR'
    out.format.color_depth = '32'
    out.format.color_mode = 'RGB'
    out.file_slots.clear()
    for slot, sock in (('depth', 'Depth'), ('normal', 'Normal'), ('index', 'IndexOB')):
        if sock not in rl.outputs:
            raise RuntimeError('render layer has no %r output — check use_pass_* above' % sock)
        out.file_slots.new(slot)
        nt.links.new(PL.rgb_named_socket(nt, rl.outputs[sock]), out.inputs[slot])
    return out


file_out = enable_passes() if WANT_PASSES else None

_ext = {'width': round((hi - lo).x, 5), 'depth': round((hi - lo).y, 5), 'height': round((hi - lo).z, 5)}
manifest = {
    'out': OUT,
    'w': W,
    'h': H,
    'samples': SAMPLES,
    'look': 'generic',
    'size_m': round(size, 4),
    'extent_m': _ext,
    'views': [],
    'idx': IDX,
    'renderer': 'prop_mesh/sheet_render.py',
    'source': {
        'glb': os.path.abspath(GLB),
        'name': NAME,
        'scale': SCALE,
        'parts': len(subject),
        'part_nodes': sorted(set(names))[:64],
    },
    'params': {'max_parts': MAX_PARTS, 'ground': not NO_GROUND, 'turntable': TURNTABLE, 'drop_nodes': DROP},
}

plan = VIEWS if not TURNTABLE else [('turn_%03d' % i, 360.0 * i / TURNTABLE, 6, 'body') for i in range(TURNTABLE)]
if ONLY_VIEWS:
    known = {v[0] for v in plan}
    bad = [v for v in ONLY_VIEWS if v not in known]
    if bad:
        raise SystemExit('--views: unknown view(s) %s; known: %s' % (','.join(bad), ','.join(sorted(known))))
    plan = [v for v in plan if v[0] in ONLY_VIEWS]

for vid, az, el, framing in plan:
    dist, vinfo = place(az, el, framing)
    # A low camera looks THROUGH the floor: at -22° the plane fills the frame and
    # occludes the subject entirely. Hide it rather than move the camera — the
    # worm's-eye view is the point of that cell, and a hidden plane costs nothing.
    if ground_ob is not None:
        ground_ob.hide_render = el < 0
    row = {
        'id': vid,
        'azimuth': az,
        'elevation': el,
        'framing': framing,
        'distance_m': round(dist, 4),
        'cam_r': cam_rotation(),
        'beauty': os.path.join(BEAUTY, vid + '.png'),
    }
    row.update(vinfo)
    if MANIFEST_ONLY:
        manifest['views'].append(row)
        continue
    if file_out:
        file_out.file_slots[0].path = vid + '_depth_'
        file_out.file_slots[1].path = vid + '_normal_'
        file_out.file_slots[2].path = vid + '_index_'
    # ONE render per view. There is no fur here — the reason pufferball_sheet renders
    # the data passes separately is that its passes must be bald — so the beauty PNG
    # and the three EXRs come off the same trace. Half the samples, same pixels.
    scene.render.filepath = os.path.join(BEAUTY, vid)
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    bpy.ops.render.render(write_still=True)
    manifest['views'].append(row)
    _zyg_log.info('SR_VIEW %s az=%s el=%s -> %s.png' % (vid, az, el, vid))

# ── every part must be visible SOMEWHERE ─────────────────────────────────────
# Read the EXRs through BLENDER, not through geom.passes_io: that reader is built on
# cv2 and Blender's bundled Python has no cv2, so routing this check through it makes
# the check skip itself silently on every run. A check that cannot run is worth less
# than no check, because it reports success.
fail = None
if WANT_PASSES and not MANIFEST_ONLY:
    try:
        import numpy as _np

        counts = {}
        for v in manifest['views']:
            hits = sorted(glob.glob(os.path.join(PASSES, v['id'] + '_index_*.exr')))
            if not hits:
                continue
            img = bpy.data.images.load(hits[0], check_existing=False)
            buf = _np.empty(len(img.pixels), dtype=_np.float32)
            img.pixels.foreach_get(buf)
            bpy.data.images.remove(img)
            arr = _np.rint(buf.reshape(-1, 4)[:, 0]).astype(_np.int32)
            u, c = _np.unique(arr, return_counts=True)
            for k, n in zip(u.tolist(), c.tolist()):
                counts[int(k)] = counts.get(int(k), 0) + int(n)
        present = {
            o.pass_index
            for o in scene.collection.all_objects
            if o.type == 'MESH' and o.pass_index > 0 and not o.hide_render
        }
        expect = {k: v for k, v in IDX.items() if v in present}
        seen = {k: counts.get(v, 0) for k, v in expect.items()}
        manifest['visible_expected'] = sorted(expect)
        manifest['visible_px'] = seen
        missing = sorted(k for k, n in seen.items() if n == 0)
        manifest['visible_missing'] = missing
        if missing:
            fail = 'parts visible in NONE of %d views: %s' % (len(manifest['views']), ', '.join(missing))
            _zyg_log.info('SR_VISIBLE_FAIL %s' % fail)
        else:
            _zyg_log.info('SR_VISIBLE_OK ' + ' '.join('%s=%d' % kv for kv in sorted(seen.items())))
    except Exception as exc:  # noqa: BLE001
        manifest['visible_px'] = None
        manifest['visible_skip'] = str(exc)
        _zyg_log.info('SR_VISIBLE_SKIP %s' % exc)

# The GLB is COPIED beside the sheet rather than re-exported: a round trip through
# Blender's glTF exporter would change the vertices the registry then hashes, and the
# asset's geometry must stay the pack's own bytes for its CC0 provenance to mean
# anything. `register()` picks up whatever .glb sits in the build dir.
import shutil  # noqa: E402

_glb_out = os.path.join(OUT, _slug(NAME) + '.glb')
if os.path.abspath(_glb_out) != os.path.abspath(GLB):
    shutil.copy2(GLB, _glb_out)
manifest['glb'] = _glb_out

with open(os.path.join(OUT, 'sheet.json'), 'w') as fh:
    json.dump(manifest, fh, indent=2)

_zyg_log.info('SR_SHEET_OK %s %d views size_m=%.4f' % (OUT, len(plan), size))
if fail and not ALLOW_HIDDEN:
    raise SystemExit(3)
