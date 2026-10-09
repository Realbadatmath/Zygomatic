#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Blender-side half of vfx_volume_preview — run as `blender -b -P this -- <json>`.

Renders one zero-padded .vdb sequence to PNG frames. Everything about the look
is chosen so a browse-and-pick preview reads correctly, not so it looks good:

**The grid set is not fixed, so the material cannot be.** The six packs that
need rendering carry three different grid sets — `{flames, temperature}`,
`{density}`, `{density, flames, temperature}`. Wiring Principled Volume to a
hardcoded `density` renders a black frame for the fire packs, which is exactly
the kind of "it ran, here is your empty video" result this library has been
bitten by before. So the grids are READ off the first frame and the density
attribute is picked from what is actually there.

**The camera is framed on the simulation's own bounds, sampled across the
sequence.** An explosion's bounding box at frame 0 is a fist and at frame 90 is
the whole domain; framing on either alone throws away most of the shot.

**A smoke-only pack has no light of its own.** Fire packs emit via blackbody
from `temperature`; a `density`-only pack is grey dust and renders black
without lights, so a key/fill/rim rig is always built. It costs nothing on a
fire pack and it is the whole picture on a dust one.
"""

import json
import math
import os
import sys

import bpy
from mathutils import Vector
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def cfg_from_argv():
    return json.loads(sys.argv[sys.argv.index('--') + 1])


def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.volumes, bpy.data.materials, bpy.data.meshes):
        for b in list(block):
            block.remove(b)


def import_sequence(seqdir, n):
    first = os.path.join(seqdir, 'f_0000.vdb')
    bpy.ops.object.volume_import(
        filepath=first,
        directory=seqdir + os.sep,
        files=[{'name': 'f_%04d.vdb' % i} for i in range(n)],
        use_sequence_detection=True,
    )
    obs = [o for o in bpy.context.scene.objects if o.type == 'VOLUME']
    if not obs:
        raise RuntimeError('volume_import created no volume object')
    ob = obs[0]
    vol = ob.data
    # Force the sequence on regardless of what detection concluded: the files
    # were padded on extraction precisely so this is unambiguous.
    vol.is_sequence = True
    vol.frame_start = 1
    vol.frame_duration = n
    vol.sequence_mode = 'CLIP'
    return ob


def grid_names(ob):
    vol = ob.data
    try:
        vol.grids.load()
        return [g.name for g in vol.grids]
    except Exception:  # noqa: BLE001
        return []


def build_material(ob, grids):
    """Principled Volume wired to whichever grids this pack actually has."""
    low = {g.lower(): g for g in grids}
    dens = low.get('density') or low.get('smoke') or low.get('flames') or (grids[0] if grids else 'density')
    temp = low.get('temperature') or low.get('heat') or ''
    flame = low.get('flames') or low.get('fuel') or ''
    smoke_only = 'density' in low and not temp

    mat = bpy.data.materials.new('vfx_preview_volume')
    mat.use_nodes = True
    nt = mat.node_tree
    for nd in list(nt.nodes):
        nt.nodes.remove(nd)
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    pv = nt.nodes.new('ShaderNodeVolumePrincipled')
    pv.location = (-300, 0)
    nt.links.new(pv.outputs['Volume'], out.inputs['Volume'])

    pv.inputs['Density Attribute'].default_value = dens
    pv.inputs['Anisotropy'].default_value = 0.25

    if temp:
        # A fire is an EMITTER, so its scattering albedo has to stay dark or the
        # key light bounces off the plume and the whole element reads as pale
        # pink smoke with a white core — which is what the first two Fire_01
        # test renders were. Dark albedo + blackbody = flame you can see.
        pv.inputs['Color'].default_value = (0.20, 0.19, 0.19, 1.0)
        pv.inputs['Density'].default_value = 4.0 if dens == flame else 3.0
        pv.inputs['Temperature Attribute'].default_value = temp
        # EmberGen writes NORMALISED 0..1 temperature and Blender multiplies the
        # attribute by this socket to get Kelvin, so this is the whole mapping.
        pv.inputs['Temperature'].default_value = 1700.0
        pv.inputs['Blackbody Intensity'].default_value = 1.0
    else:
        pv.inputs['Color'].default_value = (0.62, 0.62, 0.64, 1.0)
        pv.inputs['Density'].default_value = 3.0
        pv.inputs['Blackbody Intensity'].default_value = 0.0

    ob.data.materials.clear()
    ob.data.materials.append(mat)
    return {'density': dens, 'temperature': temp, 'smoke_only': smoke_only}


def sequence_bounds(ob, n, samples=9):
    """World-space bounds of the volume across the sequence. Sampled, because
    loading every frame's grid to measure it costs as much as rendering it."""
    dg = bpy.context.evaluated_depsgraph_get()
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    seen = 0
    step = max(1, n // samples)
    for f in range(1, n + 1, step):
        bpy.context.scene.frame_set(f)
        dg.update()
        ev = ob.evaluated_get(dg)
        bb = [ev.matrix_world @ Vector(c) for c in ev.bound_box]
        if max((b - bb[0]).length for b in bb) < 1e-6:
            continue  # empty frame — an unstarted sim
        for b in bb:
            lo = Vector((min(lo.x, b.x), min(lo.y, b.y), min(lo.z, b.z)))
            hi = Vector((max(hi.x, b.x), max(hi.y, b.y), max(hi.z, b.z)))
        seen += 1
    if not seen:
        lo, hi = Vector((-1, -1, -1)), Vector((1, 1, 1))
    return lo, hi


def setup_camera(lo, hi, res_x, res_y, cfg_dir=None):
    centre = (lo + hi) * 0.5
    radius = max((hi - lo).length * 0.5, 1e-3)
    cam_d = bpy.data.cameras.new('cam')
    cam_d.lens = 50.0
    cam = bpy.data.objects.new('cam', cam_d)
    bpy.context.scene.collection.objects.link(cam)
    # Half-angle of the NARROWER axis is what actually clips the subject.
    sensor = cam_d.sensor_width
    fov = 2.0 * math.atan(0.5 * sensor / cam_d.lens)
    if res_y > res_x:
        fov = 2.0 * math.atan(math.tan(fov * 0.5) * res_y / res_x)
    else:
        fov = 2.0 * math.atan(math.tan(fov * 0.5) * min(1.0, res_y / res_x))
    dist = radius / max(math.sin(fov * 0.5), 1e-3) * 1.25
    # THE CLIP RANGE IS NOT OPTIONAL. `bpy.data.cameras.new()` hands back
    # clip_end = 1000, and these domains are hundreds of units across, so the
    # framing distance for a big sim lands beyond it and Cycles renders the
    # volume away entirely — a full black clip with no error anywhere. Fire_01
    # (dist 737) survived it and Dust Devil (dist 1675) did not, which is
    # exactly the kind of works-on-one-pack bug that ships.
    cam_d.clip_start = max(1e-3, (dist - radius * 4.0) * 0.5)
    cam_d.clip_end = (dist + radius * 4.0) * 2.0
    direction = Vector(cfg_dir or (0.72, -1.0, 0.28)).normalized()
    cam.location = centre + direction * dist
    _zyg_log.info(f'[render] camera dist={dist:.0f} clip=[{cam_d.clip_start:.2f}, {cam_d.clip_end:.0f}]')
    trk = cam.constraints.new('TRACK_TO')
    empty = bpy.data.objects.new('aim', None)
    empty.location = centre
    bpy.context.scene.collection.objects.link(empty)
    trk.target = empty
    trk.track_axis = 'TRACK_NEGATIVE_Z'
    trk.up_axis = 'UP_Y'
    bpy.context.scene.camera = cam
    return centre, radius


def refit_camera_to_element(ob, cam, n, samples=13, margin=1.04):
    """Tighten framing from the circumscribing SPHERE to the element's own
    PROJECTED box, and match the output aspect to it.

    `setup_camera` fits a sphere of radius = half the bounding-box DIAGONAL.
    That can never clip the subject, which is what a browse preview needs, but
    it is badly wrong for a compositing element: Dust Shockwave's bounds are
    1127 x 1103 x 143 — a pancake — so the sphere fit is driven by the wide
    axis while the element only covers 353 of 2160 rows. Rendered that way, a
    "4K" pass delivers an element 1233 px across: no better than the vendor's
    1080p turntable, which is the whole reason for rendering at all.

    So the 8 bbox corners are projected through the camera across the sequence,
    the union of that is what gets framed, and the render height is set to the
    element's own aspect instead of a forced 16:9. Zoom is applied as focal
    length and recentring as sensor shift — the camera does not move, so the
    perspective the sphere fit chose is preserved exactly.

    Iterated rather than solved in closed form: `world_to_camera_view` already
    accounts for lens and shift, so re-projecting after each nudge converges
    and needs no algebra that could silently disagree with Blender's own
    projection. The UNION across frames (not per-frame) is deliberate — a
    per-frame crop would make a fixed element jitter."""
    from bpy_extras.object_utils import world_to_camera_view

    sc = bpy.context.scene
    dg = bpy.context.evaluated_depsgraph_get()
    step = max(1, n // samples)

    def project_union():
        u0 = v0 = 1e9
        u1 = v1 = -1e9
        seen = 0
        for f in range(1, n + 1, step):
            sc.frame_set(f)
            dg.update()
            ev = ob.evaluated_get(dg)
            bb = [ev.matrix_world @ Vector(c) for c in ev.bound_box]
            if max((b - bb[0]).length for b in bb) < 1e-6:
                continue  # empty frame — an unstarted sim
            for b in bb:
                co = world_to_camera_view(sc, cam, b)
                if co.z <= 0.0:
                    continue  # behind the camera
                u0, u1 = min(u0, co.x), max(u1, co.x)
                v0, v1 = min(v0, co.y), max(v1, co.y)
            seen += 1
        if not seen or u1 <= u0 or v1 <= v0:
            return None
        return u0, v0, u1, v1

    box = project_union()
    if not box:
        _zyg_log.info('[render] refit: no projectable bounds — keeping sphere fit')
        return
    u0, v0, u1, v1 = box
    rx, ry = sc.render.resolution_x, sc.render.resolution_y
    # Element aspect in SQUARE PIXELS, which is what the output must match.
    asp = ((v1 - v0) * ry) / max((u1 - u0) * rx, 1e-9)
    # "4K" is the LONG EDGE, not the width. A tornado is a vertical column:
    # sizing its width to 3840 would derive a height of 3840*asp and hand back
    # a 3840x6000 render nobody asked for. Whichever way the element runs, its
    # long side gets the budget.
    long_edge = max(rx, ry)
    if asp <= 1.0:
        new_rx, new_ry = long_edge, int(round(long_edge * asp / margin))
    else:
        new_rx, new_ry = int(round(long_edge / asp * margin)), long_edge
    new_rx = max(64, min(new_rx + (new_rx & 1), 8192))  # even, sane bounds
    new_ry = max(64, min(new_ry + (new_ry & 1), 8192))
    sc.render.resolution_x, sc.render.resolution_y = new_rx, new_ry
    rx, ry = new_rx, new_ry
    _zyg_log.info(f'[render] refit: element aspect {asp:.3f} → {new_rx}x{new_ry}')

    for it in range(6):
        box = project_union()
        if not box:
            break
        u0, v0, u1, v1 = box
        du, dv = u1 - u0, v1 - v0
        cu, cv = (u0 + u1) * 0.5, (v0 + v1) * 0.5
        z = 1.0 / max(margin * max(du, dv), 1e-6)
        cam.data.lens *= z
        # shift_x/shift_y are in fractions of the sensor's LARGER dimension —
        # and they shift the FRUSTUM, so the subject moves the other way. The
        # response was measured on this rig, not assumed: d(u)/d(shift_x) = -1
        # and d(v)/d(shift_y) = -1/aspect. Getting that sign wrong does not
        # merely fail to converge, it DIVERGES — the first cut doubled the
        # centring error every pass (v: 0.466, 0.357, 0.214, -0.072) and walked
        # the element clean off the frame, which renders as a fully transparent
        # 3840x1168 png and looks exactly like a successful run.
        ar = sc.render.resolution_y / sc.render.resolution_x
        cam.data.shift_x += (cu - 0.5) * z
        cam.data.shift_y += (cv - 0.5) * z * ar
        _zyg_log.info(
            f'[render]   pass {it}: cover {du * 100:.1f}%x{dv * 100:.1f}% '
            f'centre ({cu:.3f},{cv:.3f}) zoom {z:.3f} lens {cam.data.lens:.1f} '
            f'shift ({cam.data.shift_x:.3f},{cam.data.shift_y:.3f})'
        )
        if abs(z - 1.0) < 0.01 and abs(cu - 0.5) < 0.005 and abs(cv - 0.5) < 0.005:
            break


def setup_lights(centre, radius, emissive=False):
    """Key / fill / rim. A density-only pack is lit by nothing else.

    `emissive` (the pack has a temperature grid) drops the rig to a quarter:
    a fire lights itself through blackbody, and a full key on top of that is
    what turned the first Fire_01 test into a white blob."""
    scale = 0.10 if emissive else 1.0
    rig = [
        ('key', (1.1, -1.4, 1.0), 1.00, (1.0, 0.95, 0.88)),
        ('fill', (-1.3, -0.7, 0.35), 0.35, (0.62, 0.72, 1.0)),
        ('rim', (-0.4, 1.5, 0.9), 0.75, (0.80, 0.88, 1.0)),
    ]
    for name, d, power, col in rig:
        ld = bpy.data.lights.new(name, type='AREA')
        ld.energy = power * scale * (radius**2) * 900.0
        ld.size = radius * 1.5
        ld.color = col
        ob = bpy.data.objects.new(name, ld)
        bpy.context.scene.collection.objects.link(ob)
        v = Vector(d).normalized() * radius * 3.2
        ob.location = centre + v
        trk = ob.constraints.new('TRACK_TO')
        aim = bpy.data.objects.new(name + '_aim', None)
        aim.location = centre
        bpy.context.scene.collection.objects.link(aim)
        trk.target = aim
        trk.track_axis = 'TRACK_NEGATIVE_Z'
        trk.up_axis = 'UP_Y'


def setup_world():
    w = bpy.data.worlds.new('vfx_preview_world')
    bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    for nd in list(nt.nodes):
        nt.nodes.remove(nd)
    out = nt.nodes.new('ShaderNodeOutputWorld')
    bg = nt.nodes.new('ShaderNodeBackground')
    # Near-black, but not black: a dark ground keeps a dust element readable
    # against the pane's own dark panel instead of dissolving into it.
    bg.inputs['Color'].default_value = (0.035, 0.038, 0.045, 1.0)
    bg.inputs['Strength'].default_value = 1.0
    nt.links.new(bg.outputs['Background'], out.inputs['Surface'])


def setup_render(cfg):
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.render.resolution_x = cfg['w']
    sc.render.resolution_y = cfg['h']
    sc.render.resolution_percentage = 100
    # ALPHA is cfg-driven and defaults OFF, so the browse-preview path keeps
    # its exact previous output. A compositing element wants the opposite: the
    # volume carries partial coverage per pixel, and `film_transparent` is what
    # writes that into the alpha channel instead of matting it onto the world.
    alpha = bool(cfg.get('alpha'))
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGBA' if alpha else 'RGB'
    sc.render.image_settings.color_depth = str(cfg.get('depth', 8))
    sc.render.filepath = cfg['out'] + 'f_'
    sc.render.film_transparent = alpha
    sc.cycles.samples = cfg.get('samples', 48)
    sc.cycles.use_denoising = True
    sc.cycles.volume_max_steps = 256
    sc.cycles.volume_step_rate = 1.0
    sc.cycles.max_bounces = 4
    sc.cycles.volume_bounces = 2
    sc.cycles.transparent_max_bounces = 8
    _set_view_transform(sc, cfg.get('view'))
    # EXPOSURE, in stops, applied before the view transform. The light rig in
    # `setup_lights` was built against AgX, which rolls highlights off; an
    # element rendered under 'Standard' with that same rig clips hard — the
    # first Dust Shockwave element pass came out with 59.3% of its pixels at
    # pure white, which is unrecoverable in a grade and makes the element
    # useless for the one job it exists to do.
    sc.view_settings.exposure = float(cfg.get('exposure', 0.0))
    _enable_gpu(sc)


def _set_view_transform(sc, prefer=None):
    """AgX, or Filmic on an older config.

    Not optional and not cosmetic: fire is an HDR emitter, and under 'Standard'
    every flame clips to flat white — the first test render of Fire_01 came out
    as a white blob with no fire in it. The enum cannot be introspected (it is
    populated from the OCIO config at runtime and `bl_rna` reports only 'NONE'),
    so this asks forgiveness rather than permission."""
    order = ([prefer] if prefer else []) + ['AgX', 'Filmic', 'Standard']
    for name in order:
        try:
            sc.view_settings.view_transform = name
            _zyg_log.info(f'[render] view transform: {name}')
            return
        except TypeError as _exc:
            _zyg_log.debug('view transform %s unavailable: %s', name, _exc)
            continue


def _enable_gpu(sc):
    """OPTIX if the box has it, CUDA next, CPU only as a last resort. A silent
    CPU fallback turns a 3-minute pack into an hour, so it is printed."""
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
    except KeyError:
        _zyg_log.info('[render] cycles prefs unavailable — CPU')
        return
    for kind in ('OPTIX', 'CUDA', 'HIP', 'ONEAPI'):
        try:
            prefs.compute_device_type = kind
        except TypeError as _exc:
            _zyg_log.debug('compute device type %s unavailable: %s', kind, _exc)
            continue
        prefs.get_devices()
        gpus = [d for d in prefs.devices if d.type == kind]
        if gpus:
            for d in prefs.devices:
                d.use = d.type == kind
            sc.cycles.device = 'GPU'
            _zyg_log.info(f'[render] GPU {kind}: ' + ', '.join(d.name for d in gpus))
            return
    sc.cycles.device = 'CPU'
    _zyg_log.info('[render] no GPU device — rendering on CPU')


def main():
    cfg = cfg_from_argv()
    n = int(cfg['n'])
    clear_scene()
    ob = import_sequence(cfg['seq'], n)
    grids = grid_names(ob)
    print('[render] grids: ' + (', '.join(grids) or '(none)'))
    wiring = build_material(ob, grids)
    print(f'[render] density={wiring["density"]!r} temperature={wiring["temperature"]!r}')
    setup_render(cfg)
    lo, hi = sequence_bounds(ob, n)
    centre, radius = setup_camera(lo, hi, cfg['w'], cfg['h'], cfg.get('cam_dir'))
    print(f'[render] bounds {tuple(round(v, 1) for v in lo)} → {tuple(round(v, 1) for v in hi)}  r={radius:.1f}')
    if cfg.get('fit') == 'element':
        refit_camera_to_element(ob, bpy.context.scene.camera, n, margin=float(cfg.get('margin', 1.04)))
    setup_lights(centre, radius, emissive=bool(wiring['temperature']))
    setup_world()
    sc = bpy.context.scene
    # Optional sub-range. The camera is still framed on the WHOLE sequence's
    # bounds above, so a partial run lines up exactly with a full one — which
    # is what makes a 4K element render resumable instead of all-or-nothing.
    sc.frame_start = max(1, int(cfg.get('f_start', 1)))
    sc.frame_end = min(n, int(cfg.get('f_end', n)))
    todo = sc.frame_end - sc.frame_start + 1
    print(f'[render] frames {sc.frame_start}..{sc.frame_end} of {n}')
    bpy.ops.render.render(animation=True)
    print(f'[render] done: {todo} frame(s)')


if __name__ == '__main__':
    main()
