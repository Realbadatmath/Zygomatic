# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pufferball_sheet.py — orbit the Pufferball mesh and render a consistent sheet.

RUN:
    blender -b -P prop_mesh/pufferball_sheet.py -- --out output/pufferball_mesh
    blender -b -P prop_mesh/pufferball_sheet.py -- --out DIR --angles 16 --passes

WHY THIS EXISTS.
The 2D sheet is built by rotating one reference image, so every view past the two
operator-locked anchors is a GUESS at surfaces the source never showed. This script
answers the same question with geometry: the camera orbits a mesh, so all N views
are the same creature by construction and the top-down view costs no more certainty
than the front.

WHAT IT EMITS, and why both.
  beauty/   the shaded render. Directly usable as a LoRA training tile.
  passes/   depth (Z), normal and IndexOB EXRs, when --passes is given.

The passes matter more than the beauty render for production. A LoRA supplies
APPEARANCE and has no idea where surfaces are; a depth/normal pair is exactly the
control signal a ControlNet consumes. Together they are the whole answer to
"rotatable in a 3D environment": the mesh fixes the pose, the passes carry it into
the diffusion stack, and the LoRA paints the creature onto it. Neither half can do
it alone — this pipeline's own maxim is that prompts steer and only pixels
guarantee, and a depth pass IS the pixels.

ANGLE PLAN. Mirrors creature_sheet_service.ANGLES so a mesh-rendered sheet is a
drop-in comparison for the Qwen-rotated one: the same 11 body viewpoints in the
same order, then the head/wide/detail framings. Names match the 2D cells' ids.
"""

import json
import math
import os
import sys
import tempfile

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pass_lib as PL  # noqa: E402
import pufferball as PB  # noqa: E402
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def _argv():
    a = sys.argv
    return a[a.index('--') + 1 :] if '--' in a else []


def _opt(args, name, default, cast=float):
    if name in args:
        try:
            return cast(args[args.index(name) + 1])
        except Exception:
            return default
    return default


ARGS = _argv()
OUT = _opt(ARGS, '--out', os.path.join(tempfile.gettempdir(), 'pufferball_mesh'), str)
W = int(_opt(ARGS, '--w', 1024))
H = int(_opt(ARGS, '--h', 1024))
SAMPLES = int(_opt(ARGS, '--samples', 64))
WANT_PASSES = '--passes' in ARGS
# --look canon applies prop_mesh/pufferball_look.py: the fitted plush groom, eye/skin
# shaders, re-shaped parts and the anchor-matched lighting/backdrop/floor/lens. The
# default 'studio' look is the neutral rig below. Data passes are unaffected by the
# rig either way (and render bald), but the look's geometry changes ARE the creature.
LOOK = _opt(ARGS, '--look', 'studio', str)
# --manifest-only rebuilds the scene and walks every view WITHOUT rendering: it
# records cam_r, runs the visibility check on the EXRs already on disk and writes
# sheet.json. For when a post-render check failed and left a finished render with
# no manifest — a 35-minute render should never have to be repeated for that.
MANIFEST_ONLY = '--manifest-only' in ARGS
# --views front_full,side_left renders a SUBSET. The fit loop (prop_mesh/pbopt.py)
# evaluates two views per candidate; making it render all sixteen would multiply an
# already dominant cost by eight for nothing.
ONLY_VIEWS = [v for v in _opt(ARGS, '--views', '', str).split(',') if v]
# --patch FILE.json overrides build parameters WITHOUT editing a source file:
#     {"P": {"hair_len": 0.06}, "LOOK": {"WIND": {"strength": 0.12}}, "fill": 0.73}
# "P" merges into the parameter dict last (so it beats the look's own PARAMS), "LOOK"
# deep-updates module-level constants in pufferball_look, and "fill" overrides the canon
# body framing. This is what lets an optimiser search the parameter space: three
# convergence runs guessed values through an LLM at ~30 min per sample and evaluated
# perhaps fifteen points in a ~50-dimensional space.
PATCH = {}
_patch_path = _opt(ARGS, '--patch', '', str)
if _patch_path:
    with open(_patch_path) as _f:
        PATCH = json.load(_f)
if LOOK not in ('studio', 'canon'):
    raise SystemExit('--look must be studio or canon, not %r' % LOOK)
# The data passes describe FORM. Hair strands and the surface crinkle are not form
# — they are the appearance a diffusion model will invent for itself — and they
# wrecked every channel they touched: the lineart map came back 4.5% white and
# structurally a fuzzy annulus of hair silhouette over a black interior, with the
# face, arms, legs and tail contributing almost no lines at all. Depth, normal and
# matte carried the same fuzz on every edge. So the pass set renders BALD, on its
# own pass, and beauty keeps the fur. `--furry-passes` restores the old behaviour.
FUR_IN_PASSES = '--furry-passes' in ARGS
TURNTABLE = int(_opt(ARGS, '--turntable', 0))
GPU = '--cpu' not in ARGS

BEAUTY = os.path.join(OUT, 'beauty')
PASSES = os.path.join(OUT, 'passes')
os.makedirs(BEAUTY, exist_ok=True)
if WANT_PASSES:
    os.makedirs(PASSES, exist_ok=True)

# (id, azimuth°, elevation°, framing) — azimuth 0 = front (camera at -Y),
# positive = orbit to the creature's left. Matches creature_sheet_service.ANGLES.
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

LK = None


def _deep_update(dst, src):
    """Merge `src` into `dst` in place, recursing into dicts.

    A patch that names one key of WIND must not wipe the other six, so a nested dict is
    merged rather than replaced. Lists are replaced whole — a Bezier control point is
    meaningless half-updated."""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_update(dst[k], v)
        else:
            dst[k] = v
    return dst


def _apply_look_patch(mod, patch):
    """Deep-update module-level constants of the look from a patch dict.

    Only names that ALREADY EXIST are touched, and a dict constant may only be patched
    with a dict. A typo in a patch key is a silent no-op otherwise, and a silent no-op in
    a parameter search reads as "this parameter does nothing" — which would be recorded as
    a measurement and believed."""
    for k, v in patch.items():
        if not hasattr(mod, k):
            raise SystemExit('--patch LOOK.%s does not exist in pufferball_look' % k)
        cur = getattr(mod, k)
        if isinstance(cur, dict):
            if not isinstance(v, dict):
                raise SystemExit('--patch LOOK.%s must be an object (it is a dict)' % k)
            _deep_update(cur, v)
        else:
            setattr(mod, k, v)


P_USED = dict(PB.P)
if LOOK == 'canon':
    import pufferball_look as LK

    _apply_look_patch(LK, PATCH.get('LOOK', {}))
    P_USED.update(getattr(LK, 'PARAMS', {}))
    if hasattr(LK, 'pre_build'):
        LK.pre_build(PB)  # must precede materials(): the look may patch them
# LAST, so a patch beats both PB.P and the look's PARAMS. PB.P is patched too because
# build_* functions default to `p=P` and some look code reads PB.P directly.
if PATCH.get('P'):
    for _k in PATCH['P']:
        if _k not in P_USED:
            raise SystemExit('--patch P.%s is not a known build parameter' % _k)
    P_USED.update(PATCH['P'])
    PB.P.update(PATCH['P'])
mats = PB.materials()
# check=False here: the look layer adds meshes that pufferball's own invariants do
# not know about; _finish_look brings them into line and the assertion runs after.
built = PB.build(scene, mats, p=P_USED, ground=True, check=(LK is None))
parts = built['parts']


def _finish_look(scene, built, PB, p):
    """Bring the look layer's additions in line with pufferball's invariants.

    The look adds meshes (lock geometry, rebuilt pupils/glints) without UVs and
    moves the feet, so assert_geometry fails on 'no UV layer' and 'sinks 2.5 mm
    through the ground'. Both are mechanical: give every creature mesh the same
    analytic UVs the primitives get, then seat the whole creature on z=0."""
    from mathutils import Vector as _V

    creature = [
        o
        for o in scene.collection.objects
        if o.type == 'MESH'
        and o.name.startswith('pb_')
        and o.name != 'pb_ground'
        and o.pass_index > 0
        and not o.hide_render
    ]
    solid = [o for o in creature if not PB.is_fur_geometry(o)]
    for o in creature:
        if not o.data.uv_layers and len(o.data.polygons):
            try:
                PB._cylindrical_uv(o.data)
            except Exception as exc:  # noqa: BLE001
                _zyg_log.info('PB_LOOK uv skipped for %s: %s' % (o.name, exc))
    bpy.context.view_layer.update()
    zmin = min((o.matrix_world @ _V(v.co)).z for o in solid for v in o.data.vertices)
    if abs(zmin) > 1e-4:
        for o in creature:
            o.location.z -= zmin
        bpy.context.view_layer.update()
        _zyg_log.info('PB_LOOK seated on ground: shifted %+.4f m' % -zmin)
    PB.assert_geometry(creature + [o for o in scene.collection.objects if o.name == 'pb_ground'], p)
    return creature


if LK is not None and hasattr(LK, 'post_build'):
    LK.post_build(scene, built, PB)
    _finish_look(scene, built, PB, P_USED)

lo, hi = PB.bounds(parts)
centre = (lo + hi) * 0.5
size = max((hi - lo).x, (hi - lo).y, (hi - lo).z)
# The canon look frames on the BODY (tail excluded) and on the FACE for close-ups,
# as the fit harness did: the anchors are body-dominant with the tail in frame, and a
# rising tail was shrinking the creature in frame. Studio keeps the whole-bbox framing.
if LOOK == 'canon':
    _body = [o for o in parts if not o.name.startswith('pb_tail_') and o.name != 'pb_ground']
    _blo, _bhi = PB.bounds(_body)
    centre = (_blo + _bhi) * 0.5
    size = max((_bhi - _blo).x, (_bhi - _blo).y, (_bhi - _blo).z)
    _face = next((o for o in parts if o.name == 'pb_face'), None)
    if _face is not None:
        _flo, _fhi = PB.bounds([_face])
        face_c = (_flo + _fhi) * 0.5
        face_size = max((_fhi - _flo).x, (_fhi - _flo).y, (_fhi - _flo).z) * 1.9
    else:
        face_c, face_size = centre, size * 0.6
    lo, hi = _blo, _bhi

world = bpy.data.worlds.new('w')
world.use_nodes = True
world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.055, 0.065, 0.085, 1)
world.node_tree.nodes['Background'].inputs['Strength'].default_value = 1.0
scene.world = world
if LK is not None and hasattr(LK, 'world'):
    LK.world(scene)


def area(name, loc, energy, sz, target):
    ld = bpy.data.lights.new(name, 'AREA')
    ld.energy = energy
    ld.size = sz
    o = bpy.data.objects.new(name, ld)
    o.location = loc
    d = (Vector(target) - Vector(loc)).normalized()
    o.rotation_mode = 'QUATERNION'
    o.rotation_quaternion = d.to_track_quat('-Z', 'Y')
    scene.collection.objects.link(o)
    return o


# Lit like the reference cells: cool key from front-left, warm bounce from below
# (his belly glow), and a strong rim behind so the fur silhouette separates from
# the dark backdrop. The rim is what makes a fur outline read at all.
aim = tuple(centre)
if LK is not None and hasattr(LK, 'lighting'):
    LK.lighting(scene, centre, size, aim)
else:
    area('key', (-0.55, -0.62, 0.62), 14, 0.9, aim)
    area('warm', (0.10, -0.34, 0.03), 6, 0.5, aim)
    area('rim', (0.42, 0.72, 0.55), 20, 0.7, aim)

cam_d = bpy.data.cameras.new('cam')
cam = bpy.data.objects.new('cam', cam_d)
scene.collection.objects.link(cam)
scene.camera = cam

scene.render.engine = 'CYCLES'
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
scene.render.resolution_x = W
scene.render.resolution_y = H
scene.render.film_transparent = False

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
                    _zyg_log.info('PB_DEVICE %s' % kind)
                    break
            except Exception as _exc:
                _zyg_log.debug('cycles device kind %s unusable, trying the next one: %s', kind, _exc)
                continue
        else:
            scene.cycles.device = 'CPU'
            _zyg_log.info('PB_DEVICE CPU (no OPTIX/CUDA)')
    except Exception as exc:
        scene.cycles.device = 'CPU'
        _zyg_log.info('PB_DEVICE CPU (%s)' % exc)
else:
    scene.cycles.device = 'CPU'
    _zyg_log.info('PB_DEVICE CPU (forced)')


def place(az_deg, el_deg, framing):
    """Orbit the camera to (azimuth, elevation) and frame the subject.

    Distance is solved from the sensor/focal so `fill` means the same thing at
    every angle — otherwise the creature would breathe in and out around the orbit
    and the sheet would teach scale drift along with identity."""
    fill, lens, aim_z = FRAMING[framing]
    if LOOK == 'canon' and framing in ('body', 'head'):
        fill, aim_z = {'body': (0.66, 0.50), 'head': (0.95, 0.50)}[framing]
        # Measured 2026-08-28: at fill 0.66 the front render covers 32.5% of the frame
        # against the anchor's 48.9%, and its bbox is 0.798 of frame width against 0.880.
        # Nothing in three look-dev runs measured framing, so this was never a candidate
        # for the difference. `--patch {"fill": ...}` makes it one.
        if framing == 'body' and 'fill' in PATCH:
            fill = float(PATCH['fill'])
        if framing == 'head' and 'fill_head' in PATCH:
            fill = float(PATCH['fill_head'])
    cam_d.lens = lens
    az, el = math.radians(az_deg), math.radians(el_deg)
    fov = 2.0 * math.atan(0.5 * cam_d.sensor_width / lens)
    if LOOK == 'canon' and framing == 'head':
        dist = (face_size / max(fill, 1e-3)) * 0.5 / math.tan(fov * 0.5)
        tgt = Vector((face_c.x, centre.y, face_c.z))
    else:
        dist = (size / max(fill, 1e-3)) * 0.5 / math.tan(fov * 0.5)
        tgt = Vector((centre.x, centre.y, lo.z + (hi.z - lo.z) * aim_z))
    cam.location = tgt + Vector(
        (dist * math.cos(el) * math.sin(az), -dist * math.cos(el) * math.cos(az), dist * math.sin(el))
    )
    cam.rotation_mode = 'QUATERNION'
    cam.rotation_quaternion = (tgt - cam.location).normalized().to_track_quat('-Z', 'Y')
    bpy.context.view_layer.update()
    return dist


def cam_rotation():
    """The camera's 3x3 world rotation, row-major, as plain floats.

    Recorded per view so a consumer can rotate the world-space Normal AOV into
    CAMERA space. Without it the normal maps are unusable as ControlNet input —
    they encode which way a surface faces IN THE WORLD, so the camera-facing
    channel swings from one extreme to the other as the creature turns instead of
    staying blue. Stored rather than re-derived from azimuth/elevation, because
    re-deriving a convention in a second place is how two surfaces end up
    disagreeing about which way round it goes."""
    r = cam.matrix_world.to_3x3().normalized()
    return [[float(r[i][j]) for j in range(3)] for i in range(3)]


def set_fur(on):
    """Toggle every hair system and every fur DISPLACE modifier for rendering —
    and the look layer's fur GEOMETRY (lock/tuft/wisp meshes), which is fur too."""
    for ob in scene.collection.objects:
        if ob.type != 'MESH':
            continue
        for md in ob.modifiers:
            if md.type == 'PARTICLE_SYSTEM' or md.name == 'fur':
                md.show_render = on
        if PB.is_fur_geometry(ob):
            ob.hide_render = not on


def enable_passes():
    """Compositor: Render Layers -> one 32-bit EXR File Output slot per pass.

    The slot names carry the VIEW id (set per view in the render loop below), which is
    why this cannot just call pass_lib.render_set() — that writes one directory per view
    with fixed names, and a 16-angle sheet wants one flat passes/ folder.

    It DOES delegate the channel naming to pass_lib.rgb_named_socket(), and must: this
    function previously wired the Normal socket straight through, so Blender wrote its
    EXR channels as X/Y/Z, cv2 could resolve only one of them, and passes_io correctly
    reported every normal pass as unusable. 16 normal EXRs shipped that way (2026-08-26).
    A missing socket is now a hard error rather than a silently skipped slot — a pass
    that never gets written is not something to discover downstream."""
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

if '--export' in ARGS and not MANIFEST_ONLY:
    # .blend keeps EVERYTHING (hair, modifiers, materials) and is the editable
    # master. .glb is the portable asset — but note glTF has no concept of a
    # Blender particle system, so the fur does NOT travel with it. That is the
    # correct trade: an engine grows its own fur from the same surface, and what
    # has to be shared is the geometry and the UV/material intent.
    blend = os.path.join(OUT, 'pufferball.blend')
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    _zyg_log.info('PB_EXPORT blend -> %s' % blend)
    glb = os.path.join(OUT, 'pufferball.glb')
    try:
        # The asset is the CREATURE: pb_* meshes that carry a pass_index and render.
        # "Everything but the floor" also shipped the look's bokeh spheres and light
        # blockers (pass_index 0) inside the GLB, which put scenery in the bbox.
        for ob in scene.collection.objects:
            ob.select_set(
                ob.type == 'MESH'
                and ob.name.startswith('pb_')
                and ob.name != 'pb_ground'
                and ob.pass_index > 0
                and not ob.hide_render
            )
        bpy.ops.export_scene.gltf(filepath=glb, export_format='GLB', use_selection=True, export_apply=True)
        _zyg_log.info('PB_EXPORT glb -> %s (geometry only; hair is not a glTF concept)' % glb)
    except Exception as exc:
        _zyg_log.info('PB_EXPORT glb FAILED: %s' % exc)

manifest = {
    'out': OUT,
    'w': W,
    'h': H,
    'samples': SAMPLES,
    'look': LOOK,
    'size_m': round(size, 4),
    'views': [],
    'idx': PB.IDX,
    'params': {k: v for k, v in P_USED.items() if not callable(v)},
}

plan = VIEWS if not TURNTABLE else [('turn_%03d' % i, 360.0 * i / TURNTABLE, 6, 'body') for i in range(TURNTABLE)]
if ONLY_VIEWS:
    _known = {v[0] for v in plan}
    _bad = [v for v in ONLY_VIEWS if v not in _known]
    if _bad:
        raise SystemExit('--views: unknown view(s) %s; known: %s' % (','.join(_bad), ','.join(sorted(_known))))
    plan = [v for v in plan if v[0] in ONLY_VIEWS]

ground_ob = next((o for o in scene.collection.objects if o.name == 'pb_ground'), None)
SCRATCH = os.path.join(OUT, '_pass_beauty')
if WANT_PASSES:
    os.makedirs(SCRATCH, exist_ok=True)

for vid, az, el, framing in plan:
    dist = place(az, el, framing)
    if LK is not None and hasattr(LK, 'camera'):
        LK.camera(cam, cam_d, vid)
    # A low camera looks THROUGH the floor: at -22 deg the ground plane fills the
    # frame and occludes the creature entirely (cell 09 came back as bare floor).
    # Hide it rather than move the camera — the worm's-eye view is the point of
    # that cell, and a hidden plane still costs nothing.
    if ground_ob is not None:
        ground_ob.hide_render = el < 0
    # Scenery that lives ON the floor (the look's bokeh lights, blockers: meshes with
    # pass_index 0) goes with it, or a worm's-eye view shows lights floating in air.
    for _o in scene.collection.objects:
        if _o.type == 'MESH' and _o.pass_index == 0 and _o.name != 'pb_ground' and not PB.is_fur_geometry(_o):
            _o.hide_render = el < 0
    if MANIFEST_ONLY:
        manifest['views'].append(
            {
                'id': vid,
                'azimuth': az,
                'elevation': el,
                'framing': framing,
                'distance_m': round(dist, 4),
                'cam_r': cam_rotation(),
                'passes_furred': bool(FUR_IN_PASSES),
                'beauty': os.path.join(BEAUTY, vid + '.png'),
            }
        )
        continue
    # ── data passes: bald, and they do not need beauty's sample count ────────
    if file_out:
        file_out.file_slots[0].path = vid + '_depth_'
        file_out.file_slots[1].path = vid + '_normal_'
        file_out.file_slots[2].path = vid + '_index_'
        if not FUR_IN_PASSES:
            set_fur(False)
        scene.cycles.samples = SAMPLES if FUR_IN_PASSES else max(8, SAMPLES // 8)
        scene.render.filepath = os.path.join(SCRATCH, vid)
        bpy.ops.render.render(write_still=True)
        file_out.mute = True
        scene.cycles.samples = SAMPLES
        set_fur(True)

    # ── beauty: furred, full samples, and no EXRs from this one ──────────────
    scene.render.filepath = os.path.join(BEAUTY, vid)
    bpy.ops.render.render(write_still=True)
    if file_out:
        file_out.mute = False
    manifest['views'].append(
        {
            'id': vid,
            'azimuth': az,
            'elevation': el,
            'framing': framing,
            'distance_m': round(dist, 4),
            'cam_r': cam_rotation(),
            'passes_furred': bool(FUR_IN_PASSES),
            'beauty': os.path.join(BEAUTY, vid + '.png'),
        }
    )
    _zyg_log.info('PB_VIEW %s az=%s el=%s -> %s.png' % (vid, az, el, vid))

# ── every part must be visible SOMEWHERE ─────────────────────────────────────
# The cheapest check in the pipeline and the one that would have caught the buried
# mouth on day one: pb_mouth sat 42 mm inside the head with IDX['mouth'] reserved
# for it, rendered in none of the 16 views, and shipped that way because nothing
# ever counted its pixels. Runs on the finished sheet, so it also covers a part
# that is merely occluded by another in every framing.
if WANT_PASSES:
    # Read the EXRs through BLENDER, not through geom.passes_io: that reader is
    # built on cv2 and Blender's bundled Python has no cv2, so routing this check
    # through it made the check skip itself silently on every run. A check that
    # cannot run is worth less than no check, because it reports success.
    try:
        import glob as _glob
        import numpy as _np

        arrs = []
        for v in manifest['views']:
            hits = sorted(_glob.glob(os.path.join(PASSES, v['id'] + '_index_*.exr')))
            if not hits:
                continue
            img = bpy.data.images.load(hits[0], check_existing=False)
            buf = _np.empty(len(img.pixels), dtype=_np.float32)
            img.pixels.foreach_get(buf)
            arrs.append(_np.rint(buf.reshape(-1, 4)[:, 0]).astype(_np.int32))
            bpy.data.images.remove(img)
        # Expect only the parts that are actually IN the scene and renderable: a
        # look layer may hide a base part (the glint spheres, the base mouth) and
        # carry its role elsewhere. A hidden part is not invisible-by-accident.
        present = {
            o.pass_index
            for o in scene.collection.objects
            if o.type == 'MESH' and o.pass_index > 0 and not o.hide_render
        }
        expect = {k: v for k, v in PB.IDX.items() if v in present}
        exempt = dict(getattr(LK, 'VISIBLE_EXEMPT', {}) or {}) if LK is not None else {}
        for k in exempt:
            expect.pop(k, None)
        manifest['visible_expected'] = sorted(expect)
        manifest['visible_exempt'] = exempt
        with open(os.path.join(OUT, 'sheet.json'), 'w') as fh:
            json.dump(manifest, fh, indent=2)  # renders are never stranded
        if arrs:
            seen = PB.assert_parts_visible(arrs, expect)
            manifest['visible_px'] = {k: int(v) for k, v in seen.items()}
            _zyg_log.info('PB_VISIBLE_OK ' + ' '.join('%s=%d' % kv for kv in sorted(seen.items())))
        else:
            _zyg_log.info('PB_VISIBLE_SKIP no index EXRs found')
    except AssertionError as exc:
        _zyg_log.info('PB_VISIBLE_FAIL %s' % exc)
        raise
    except Exception as exc:
        _zyg_log.info('PB_VISIBLE_SKIP %s' % exc)

with open(os.path.join(OUT, 'sheet.json'), 'w') as fh:
    json.dump(manifest, fh, indent=2)

_zyg_log.info('PB_SHEET_OK %s %d views' % (OUT, len(plan)))
