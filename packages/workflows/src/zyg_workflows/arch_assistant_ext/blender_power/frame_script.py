# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""blender_power.frame_script — see the package docstring."""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.blender_power.constants import (
    BLANK_VIEW_N,
    BP_CY_SAMPLES,
    EXPOSURE_EV,
    EYE_FOV_DEG,
    EYE_HEIGHT_M,
    HERE,
    HERO_EV,
    HERO_EV_VIEW,
    HERO_GROUND_M,
    HERO_GROUND_MAT,
    LOBBY_CLEAR_M,
    LOBBY_STEP_M,
    SKY_RGB,
    SUN_ANGLE_DEG,
    SUN_AZIM_DEG,
    SUN_ELEV_DEG,
    SUN_ENERGY,
)

# ── stage 2: a second Blender on that .blend ─────────────────────────────────
_FRAME = (
    (
        'BP_SKY = %r\nBP_SUN_ENERGY = %r\nBP_SUN_ANGLE = %r\nBP_SUN_ELEV = %r\nBP_SUN_AZIM = %r\n'
        'BP_EYE_H = %r\nBP_EYE_FOV = %r\nBP_EV = %r\n'
        'BP_CLEAR_MIN = %r\nBP_CLEAR_STEP = %r\nBP_BLANK_N = %r\nBP_PROBE_INFO = {}\n'
        'BP_HERE = %r\nBP_CY_SAMPLES = %r\nBP_GROUND_M = %r\nBP_GROUND_MAT = %r\nBP_HERO_EV = %r\n'
        'BP_HERO_EV_VIEW = %r\n'
        % (
            SKY_RGB,
            SUN_ENERGY,
            SUN_ANGLE_DEG,
            SUN_ELEV_DEG,
            SUN_AZIM_DEG,
            EYE_HEIGHT_M,
            EYE_FOV_DEG,
            EXPOSURE_EV,
            LOBBY_CLEAR_M,
            LOBBY_STEP_M,
            BLANK_VIEW_N,
            HERE,
            BP_CY_SAMPLES,
            HERO_GROUND_M,
            HERO_GROUND_MAT,
            HERO_EV,
            HERO_EV_VIEW,
        )
    )
    + r'''
def _bp_sun_dir(sun_hour):
    """Unit vector FROM the scene TOWARD the sun, Blender frame (x east, y north,
    z up). Default: BP_SUN_ELEV degrees above the horizon in the south-west.
    With a sun hour the azimuth sweeps 15 deg/h through due south at noon and the
    elevation follows a sine over the day, floored at 6 deg so nothing goes black."""
    import math, mathutils
    if sun_hour is None:
        el, az = math.radians(BP_SUN_ELEV), math.radians(BP_SUN_AZIM)
    else:
        h = float(sun_hour) % 24.0
        el = math.radians(max(6.0, 62.0 * math.sin(math.pi * (h - 6.0) / 12.0)))
        az = math.radians((180.0 + (h - 12.0) * 15.0) % 360.0)
    return mathutils.Vector((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)))


def _bp_world(sc):
    """A sky-coloured world, not the default flat grey: without it grass, sand,
    rock and water all come back as one pastel."""
    import bpy
    if sc.world is None:
        sc.world = bpy.data.worlds.new('bp_world')
    w = sc.world
    w.use_nodes = True
    bg = w.node_tree.nodes.get('Background')
    if bg is None:
        for n in w.node_tree.nodes:
            if n.type == 'BACKGROUND':
                bg = n
                break
    if bg is not None:
        bg.inputs[0].default_value = (BP_SKY[0], BP_SKY[1], BP_SKY[2], 1.0)
        try:
            bg.inputs[1].default_value = 1.0
        except Exception as _exc:
            _zyg_log.debug('world background strength not settable: %s', _exc)
    try:
        w.color = BP_SKY
    except Exception as _exc:
        _zyg_log.debug('world colour not settable: %s', _exc)
    return w


def _bp_sky_world(sc, sv):
    """The HERO world: a physical Nishita sky, so glass reflects a sky instead of
    a flat blue card. `sv` is the unit vector toward the sun (Blender frame), so
    the sky's own sun sits exactly where _bp_sun_dir put the lamp. Falls back to
    the flat BP_SKY background on any build without ShaderNodeTexSky."""
    import bpy, math
    w = _bp_world(sc)
    try:
        nt = w.node_tree
        bg = nt.nodes.get('Background')
        if bg is None:
            for n in nt.nodes:
                if n.type == 'BACKGROUND':
                    bg = n
                    break
        if bg is None:
            return 'flat'
        sky = nt.nodes.new('ShaderNodeTexSky')
    except Exception:
        return 'flat'
    kind = 'flat'
    for st in ('NISHITA', 'HOSEK_WILKIE', 'PREETHAM'):
        try:
            sky.sky_type = st
            kind = st
            break
        except TypeError as _exc:
            _zyg_log.debug('sky type %s not supported: %s', st, _exc)
            continue
    if kind == 'flat':
        nt.nodes.remove(sky)
        return 'flat'
    el = math.asin(max(-1.0, min(1.0, sv.z)))
    az = math.atan2(sv.x, sv.y)                 # 0 = north (+y), clockwise
    for key, val in (('sun_elevation', el), ('sun_rotation', az),
                     ('sun_intensity', 0.6), ('sun_size', math.radians(BP_SUN_ANGLE)),
                     ('altitude', 30.0), ('air_density', 1.0), ('dust_density', 1.6)):
        try:
            setattr(sky, key, val)
        except Exception as _exc:
            _zyg_log.debug('sky attribute %s not settable: %s', key, _exc)
    sky.location = (bg.location.x - 320, bg.location.y)
    nt.links.new(sky.outputs[0], bg.inputs[0])
    try:
        bg.inputs[1].default_value = 1.0
    except Exception as _exc:
        _zyg_log.debug('world background strength not settable: %s', _exc)
    return kind


def _bp_hero_ground(sc, lo, hi):
    """A BP_GROUND_M plane under the building, but ONLY when the drawing brought
    no ground of its own — a 4K photoreal frame of a tower standing on nothing
    is not a photograph. Never saved: this runs in a render pass, not a build."""
    import bpy, sys, mathutils
    for ob in sc.objects:
        if str(ob.get('studio_kind') or '') in ('ground', 'terrain'):
            return ''
        nm = str(ob.name or '').lower()
        if nm.startswith('ground ') or nm.startswith('terrain '):
            return ''
    me = bpy.data.meshes.new('bp_hero_ground')
    r = float(BP_GROUND_M) / 2.0
    me.from_pydata([(-r, -r, 0.0), (r, -r, 0.0), (r, r, 0.0), (-r, r, 0.0)], [], [(0, 1, 2, 3)])
    me.update()
    mat = None
    try:
        if BP_HERE not in sys.path:
            sys.path.insert(0, BP_HERE)
        from zyg_workflows import arch_blender_build as ABB
        mat = ABB.get_material(BP_GROUND_MAT)
    except Exception as e:
        print('BP_HERO_GROUND_MAT_FAIL %s: %s' % (type(e).__name__, e))
    if mat is None:
        mat = bpy.data.materials.new('bp_hero_ground')
        mat.use_nodes = True
        b = mat.node_tree.nodes.get('Principled BSDF')
        if b is not None:
            b.inputs['Base Color'].default_value = (0.17, 0.17, 0.18, 1.0)
            b.inputs['Roughness'].default_value = 0.9
    me.materials.append(mat)
    ob = bpy.data.objects.new('bp_hero_ground', me)
    sc.collection.objects.link(ob)
    ob.location = mathutils.Vector(((lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0, lo[2]))
    return mat.name


def _bp_cycles(sc):
    """CYCLES on the GPU — the same probe render_offline_blender.enable_gpu runs
    (OPTIX, then CUDA, then HIP/ONEAPI), copied here because this script is a
    string compiled inside a second Blender that imports nothing of ours."""
    import bpy
    sc.render.engine = 'CYCLES'
    device, backend = 'CPU', ''
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
    except KeyError:
        try:
            bpy.ops.preferences.addon_enable(module='cycles')
            prefs = bpy.context.preferences.addons['cycles'].preferences
        except Exception:
            prefs = None
    if prefs is not None:
        for be in ('OPTIX', 'CUDA', 'HIP', 'ONEAPI'):
            try:
                prefs.compute_device_type = be
            except TypeError as _exc:
                _zyg_log.debug('cycles compute device %s not supported: %s', be, _exc)
                continue
            try:
                devs = prefs.get_devices_for_type(be)
            except Exception:
                try:
                    prefs.get_devices()
                    devs = [dv for dv in prefs.devices if dv.type == be]
                except Exception:
                    devs = []
            got = False
            for dv in devs:
                dv.use = True
                got = True
            if got:
                sc.cycles.device = 'GPU'
                device, backend = 'GPU', be
                break
    if device == 'CPU':
        sc.cycles.device = 'CPU'
    cy = sc.cycles
    cy.samples = max(1, min(4096, int(BP_CY_SAMPLES)))
    cy.use_adaptive_sampling = True
    cy.use_denoising = True
    denoiser = ''
    for dn in ('OPENIMAGEDENOISE', 'OPTIX'):
        try:
            cy.denoiser = dn
            denoiser = dn
            break
        except TypeError as _exc:
            _zyg_log.debug('denoiser %s not supported: %s', dn, _exc)
            continue
    return device, backend, denoiser


def _bp_look(sc):
    """AgX (Filmic, then Standard, if this build has neither) with a contrast
    look and the stop-down that keeps the landscape's colours out of AgX's
    desaturating shoulder. The look names differ per OCIO config, so the list is
    walked until one is accepted."""
    vs = sc.view_settings
    got = ''
    for t in ('Filmic', 'AgX', 'Standard'):
        try:
            vs.view_transform = t
            got = t
            break
        except TypeError as _exc:
            _zyg_log.debug('view transform %s not supported: %s', t, _exc)
            continue
    look = ''
    for lk in ('Filmic - Medium High Contrast', 'Medium High Contrast', 'AgX - Punchy', 'Punchy',
               'AgX - Medium High Contrast', 'AgX - Base Contrast', 'Medium Contrast', 'None'):
        try:
            vs.look = lk
            look = lk
            break
        except TypeError as _exc:
            _zyg_log.debug('view look %s not supported: %s', lk, _exc)
            continue
    try:
        vs.exposure = BP_EV
    except Exception as _exc:
        _zyg_log.debug('view exposure not settable: %s', _exc)
    return got, look


def _bp_ground_z(sc, x, y, high, floor, step_in=None, max_in=None):
    """The height of the ground under (x, y): a ray straight down from above the
    scene. 2026-09-07 (creator's eye-view check): the scene box can overhang the
    ground (tree crowns past the edge), so a probe just inside the box edge hits
    nothing — walk INWARD (toward +y, north) in steps until something is hit, and
    fall back to the base plane (0), never to the scene's lowest point (that put
    the camera under a valley floor)."""
    import bpy
    try:
        dg = bpy.context.evaluated_depsgraph_get()
        step = step_in or 2.0
        n = int((max_in or 0.0) / step) + 1
        for i in range(max(1, n)):
            hit = sc.ray_cast(dg, (x, y + i * step, high + 50.0), (0.0, 0.0, -1.0))
            if hit[0]:
                # the top hit: ground -> stand on it; a wood or a building -> the camera
                # would be inside it, so stand on its top and a little higher to see over
                name = (hit[4].name if len(hit) > 4 and hit[4] is not None else '') or ''
                kind = name.split(' ')[0]
                ground_kinds = ('ground', 'terrain', 'hill', 'slope', 'plateau', 'berm', 'pad', 'beach', 'dune_field',
                                'island', 'mesa', 'mountain', 'mountain_range', 'valley', 'ridge', 'cliff',
                                'escarpment', 'scree')
                extra = 0.0 if (kind in ground_kinds or kind.startswith('sculpt')) else 1.5
                return hit[1].z + extra
    except Exception as _exc:
        _zyg_log.debug('ground height ray cast failed, assuming z=0: %s', _exc)
    return 0.0


def _bp_forward(cam):
    """The camera's own view direction (unit, Blender frame)."""
    import mathutils
    return (cam.matrix_world.to_quaternion() @ mathutils.Vector((0.0, 0.0, -1.0))).normalized()


def _bp_clear(sc, origin, direction, reach=500.0):
    """Metres of free air from `origin` along `direction` — `reach` when nothing
    is hit. The same scene.ray_cast _bp_ground_z uses, nudged off the origin so
    a camera sitting exactly on a face does not hit it at zero distance."""
    import bpy, mathutils
    try:
        dg = bpy.context.evaluated_depsgraph_get()
        o = mathutils.Vector(origin)
        v = mathutils.Vector(direction).normalized()
        hit = sc.ray_cast(dg, o + v * 0.01, v, distance=reach)
        if hit[0]:
            return max(0.0, (mathutils.Vector(hit[1]) - o).length)
    except Exception as _exc:
        _zyg_log.debug('clearance ray cast failed, assuming full reach: %s', _exc)
    return float(reach)


def _bp_aim(cam, v):
    """Point the camera level along `v` (Blender xy) — the same to_track_quat
    the named views use."""
    import mathutils
    cam.rotation_euler = (-mathutils.Vector(v).normalized()).to_track_quat('Z', 'Y').to_euler()
    bpy.context.view_layer.update()


def _bp_seen_here(sc, dg, cam):
    """How many distinct records THIS camera hits with a grid of rays through its
    own picture — _bp_framed's n_visible, minus the per-object corner rays, which
    are far too slow to run once per candidate camera. Walking every object and
    aiming at its origin was both slower AND wrong: a studio record's origin sits
    ON the floor slab, so the slab was always the first hit."""
    return len(_bp_hit_keys(sc, dg, cam, nx=9, ny=7))


def _bp_unblock(sc, cam, spec):
    """present()'s lobby camera stands INSIDE the building, so it can end up
    against a partition — or, on the operator's own tower (live job 94f5813b,
    2026-09-11), 5 cm INSIDE one: a blank grey frame the old _bp_framed still
    counted 14 records into.

    The camera is left alone when it already has BP_CLEAR_MIN metres of air in
    front of it AND can see BP_BLANK_N records. Otherwise it steps BACK toward
    the door in BP_CLEAR_STEP metres (`retreat` is the unit vector toward the
    door, `retreat_max` how far it may go and still be inside) and at every step
    it also tries 8 horizontal rays at eye height; the (place, direction) that
    SEES the most records wins, clearance breaking the tie. Clearance alone is
    not enough: on that tower the first step back had 2.45 m of air and was
    still one 10 m partition filling the frame — the only real sightline in the
    room ran sideways. Everything measured lands in BP_PROBE_INFO, which
    _bp_framed prints."""
    import math, mathutils
    dg = bpy.context.evaluated_depsgraph_get()
    start = mathutils.Vector(cam.location)
    start_rot = tuple(cam.rotation_euler)
    fwd = _bp_forward(cam)
    flat = mathutils.Vector((fwd.x, fwd.y, 0.0))
    flat = flat.normalized() if flat.length > 1e-6 else mathutils.Vector((0.0, 1.0, 0.0))
    clear0 = _bp_clear(sc, start, fwd)
    seen0 = _bp_seen_here(sc, dg, cam)
    info = {'clear_start': round(min(clear0, 500.0), 3), 'seen_start': seen0,
            'moved_m': 0.0, 'turned_deg': 0.0}
    if clear0 >= BP_CLEAR_MIN and seen0 >= BP_BLANK_N:
        info['clear_ahead'] = round(min(clear0, 500.0), 3)
        BP_PROBE_INFO.clear()
        BP_PROBE_INFO.update(info)
        return info

    rv = spec.get('retreat') or (0.0, 0.0, 0.0)
    back = mathutils.Vector((float(rv[0]), float(rv[1]), 0.0))
    back = back.normalized() if back.length > 1e-6 else None
    rmax = float(spec.get('retreat_max') or 0.0)
    steps = [0.0]
    if back is not None:
        s = BP_CLEAR_STEP
        while s <= rmax + 1e-6:
            steps.append(round(s, 3))
            s += BP_CLEAR_STEP
    dirs = [flat] + [mathutils.Vector((math.sin(math.radians(i * 45.0)), math.cos(math.radians(i * 45.0)), 0.0))
                     for i in range(8)]
    best = None                      # (score, step, dir, clear, seen)
    widest = (clear0, 0.0, flat)     # the fallback when nothing clears BP_CLEAR_MIN
    for s in steps:
        loc = start + (back * s if back is not None else mathutils.Vector((0.0, 0.0, 0.0)))
        cam.location = loc
        for di, v in enumerate(dirs):
            dist = _bp_clear(sc, loc, v)
            if dist > widest[0]:
                widest = (dist, s, v)
            if dist < BP_CLEAR_MIN:
                continue
            _bp_aim(cam, v)
            seen = _bp_seen_here(sc, dg, cam)
            score = (seen, round(min(dist, 500.0), 2), -s, -di)
            if best is None or score > best[0]:
                best = (score, s, v, dist, seen)
    if best is not None:
        step, v, clear, seen = best[1], best[2], best[3], best[4]
    else:
        clear, step, v = widest
        seen = None
    cam.location = start + (back * step if back is not None else mathutils.Vector((0.0, 0.0, 0.0)))
    turn = math.degrees(math.acos(max(-1.0, min(1.0, v.normalized().dot(flat)))))
    if turn < 1.0:
        cam.rotation_euler = start_rot          # unturned: keep the lens's own shift/tilt
        bpy.context.view_layer.update()
    else:
        cam.data.shift_y = 0.0
        _bp_aim(cam, v)
    info['moved_m'] = round(step, 3)
    info['turned_deg'] = round(turn, 1)
    info['seen_probe'] = seen
    info['clear_ahead'] = round(min(clear, 500.0), 3)
    BP_PROBE_INFO.clear()
    BP_PROBE_INFO.update(info)
    return info


def _bp_frame(view, width, height, out_png, engine, sun_hour=None, cam_spec=None):
    """cam_spec (2026-09-08): None keeps every named view exactly as it was. A dict
    {loc, target, focal, shift_y, tilt} (Blender frame, computed by _frame_camera on
    the studio side) stands a perspective camera at loc with a real lens, aimed
    level at the target's plan position, shift_y lifting the target into frame
    and `tilt` (radians, + = up) taking whatever shift alone could not."""
    import bpy, math, mathutils
    sc = bpy.context.scene
    lo = [1e9, 1e9, 1e9]
    hi = [-1e9, -1e9, -1e9]
    has_vcol = False
    for ob in sc.objects:
        if ob.type != 'MESH':
            continue
        try:
            ca = getattr(ob.data, 'color_attributes', None)
            if ca is not None and len(ca):
                has_vcol = True
        except Exception as _exc:
            _zyg_log.debug('vertex colour probe skipped for a mesh: %s', _exc)
        for c in ob.bound_box:
            w = ob.matrix_world @ mathutils.Vector(c)
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    if lo[0] > 1e8:
        lo, hi = [-5.0, -5.0, 0.0], [5.0, 5.0, 5.0]
    ctr = mathutils.Vector([(lo[i] + hi[i]) / 2.0 for i in range(3)])
    span = max(2.0, max(hi[i] - lo[i] for i in range(3)))

    # 2026-09-08: cam_spec is None (the named view, exactly as before), a dict
    # (the cell camera) or 'script' — blender_run(render=true) passes that, and
    # a camera the user's bpy script set as scene.camera is then kept. A saved
    # script camera never hijacks a later named view: only 'script' looks for it.
    user_cam = None
    if cam_spec == 'script':
        if sc.camera is not None and getattr(sc.camera, 'type', '') == 'CAMERA':
            user_cam = sc.camera
        cam_spec = None
    if user_cam is not None:
        cam = user_cam
        cd = cam.data
    else:
        cd = bpy.data.cameras.new('bp_cam')
        cam = bpy.data.objects.new('bp_cam', cd)
        sc.collection.objects.link(cam)
        sc.camera = cam
        cd.clip_start = 0.05
        cd.clip_end = span * 20.0 + 2000.0
        if cam_spec and cam_spec.get('kind') == 'section':
            # THE CUT. An ortho camera standing ON the cut plane looking through
            # the building: everything behind the plane is behind the camera and
            # is simply not rendered, and clip_start 0.01 puts the near plane on
            # the cut itself. This is the view a stair through a slab shows up in.
            cd.type = 'ORTHO'
            cd.clip_start = 0.01
            ext_w = float(cam_spec.get('ext_w') or span)
            ext_h = float(cam_spec.get('ext_h') or span)
            aspect = float(width) / max(1.0, float(height))
            cd.ortho_scale = max(2.0, max(ext_w, ext_h * aspect) * 1.15)
            v = mathutils.Vector(cam_spec['dir']).normalized()
            cam.location = mathutils.Vector(cam_spec['loc'])
            cam.rotation_euler = v.to_track_quat('Z', 'Y').to_euler()
        elif cam_spec:
            cd.type = 'PERSP'
            cd.lens_unit = 'MILLIMETERS'
            cd.sensor_fit = 'HORIZONTAL'
            cd.sensor_width = float(cam_spec.get('sensor') or 36.0)
            cd.lens = float(cam_spec.get('focal') or 35.0)
            cd.shift_y = float(cam_spec.get('shift_y') or 0.0)
            loc = mathutils.Vector(cam_spec['loc'])
            tgt = mathutils.Vector(cam_spec['target'])
            flat = mathutils.Vector((tgt.x - loc.x, tgt.y - loc.y, 0.0))
            if flat.length < 0.05:
                flat = mathutils.Vector((0.0, 1.0, 0.0))
            back = (-flat).normalized()
            q = back.to_track_quat('Z', 'Y')
            tilt = float(cam_spec.get('tilt') or 0.0)
            if abs(tilt) > 1e-6:
                q = q @ mathutils.Quaternion((1.0, 0.0, 0.0), tilt)
            cam.location = loc
            cam.rotation_euler = q.to_euler()
        elif view == 'eye':
            # standing on the ground at the block's SOUTH edge (blender -y), looking north
            cd.type = 'PERSP'
            cd.lens_unit = 'FOV'
            cd.angle = math.radians(BP_EYE_FOV)
            ex = ctr.x
            # the ground height is sampled just INSIDE the edge; the camera stands just
            # OUTSIDE it, so it looks at the block instead of standing inside a hill
            gz = _bp_ground_z(sc, ex, lo[1] + min(3.0, span * 0.03), hi[2], lo[2], step_in=2.0, max_in=span * 0.3)
            ey = lo[1] + min(8.0, span * 0.05)      # a few metres INSIDE the edge: outside it, the cut edge of the ground showed as a void
            cam.location = mathutils.Vector((ex, ey, gz + BP_EYE_H))
            cam.rotation_euler = mathutils.Vector((0.0, -1.0, 0.0)).to_track_quat('Z', 'Y').to_euler()
        elif view == 'aerial':
            # 45 deg above the horizon in the south-west, far enough back for the lot
            cd.type = 'PERSP'
            cd.lens_unit = 'FOV'
            cd.angle = math.radians(45.0)
            v = mathutils.Vector((-1.0, -1.0, math.sqrt(2.0))).normalized()
            cam.location = ctr + v * ((span * 0.62) / math.tan(cd.angle / 2.0) + span * 0.5)
            cam.rotation_euler = v.to_track_quat('Z', 'Y').to_euler()
        else:
            dirs = {'iso': (1.0, -1.0, 0.8), 'top': (0.0, 0.0, 1.0),
                    'front': (0.0, -1.0, 0.02), 'back': (0.0, 1.0, 0.02),
                    'right': (1.0, 0.02, 0.02), 'left': (-1.0, 0.02, 0.02),
                    'section': (0.0, -1.0, 0.02)}
            v = mathutils.Vector(dirs.get(view, dirs['iso'])).normalized()
            cd.type = 'ORTHO'
            cd.ortho_scale = span * 1.75
            cam.location = ctr + v * (span * 3.0 + 20.0)
            cam.rotation_euler = v.to_track_quat('Z', 'Y').to_euler()

    # the sun: one hard key light, so a slope reads as a slope
    sun_d = bpy.data.lights.new('bp_sun', 'SUN')
    sun_d.energy = BP_SUN_ENERGY
    try:
        sun_d.angle = math.radians(BP_SUN_ANGLE)
    except Exception as _exc:
        _zyg_log.debug('sun angle not settable: %s', _exc)
    sun = bpy.data.objects.new('bp_sun', sun_d)
    sc.collection.objects.link(sun)
    sv = _bp_sun_dir(sun_hour)
    sun.location = ctr + sv * (span * 3.0 + 50.0)
    sun.rotation_euler = sv.to_track_quat('Z', 'Y').to_euler()
    hero = {}
    if engine == 'cycles':
        hero['sky'] = _bp_sky_world(sc, sv)
        hero['ground'] = _bp_hero_ground(sc, lo, hi)
    else:
        _bp_world(sc)
    transform, look = _bp_look(sc)

    if engine == 'cycles':
        hero['device'], hero['backend'], hero['denoiser'] = _bp_cycles(sc)
        hero['samples'] = sc.cycles.samples
        if hero.get('sky') != 'flat':
            # a physical sky is ~2 stops hotter than the flat card — and a camera
            # standing INSIDE the building sees that sky only through the glass,
            # so it gets its own stop (BP_HERO_EV_VIEW).
            ev = BP_HERO_EV_VIEW.get(view)
            if ev is None and isinstance(cam_spec, dict):
                ev = BP_HERO_EV_VIEW.get(cam_spec.get('kind'))
            hero['ev_view'] = view if ev is not None else ''
            try:
                sc.view_settings.exposure = BP_HERO_EV if ev is None else float(ev)
            except Exception as _exc:
                _zyg_log.debug('hero exposure not settable: %s', _exc)
        hero['exposure'] = round(sc.view_settings.exposure, 3)
    elif engine == 'eevee':
        for e in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE', 'BLENDER_WORKBENCH'):
            try:
                sc.render.engine = e
                break
            except TypeError as _exc:
                _zyg_log.debug('render engine %s not available: %s', e, _exc)
                continue
        # ambient occlusion and soft shadows: the names moved between EEVEE
        # Legacy and EEVEE Next, so every one of them is set defensively.
        ee = getattr(sc, 'eevee', None)
        if ee is not None:
            for key, val in (('use_gtao', True), ('gtao_distance', 10.0), ('gtao_factor', 1.0),
                             ('use_shadows', True), ('use_soft_shadows', True),
                             ('shadow_ray_count', 2), ('shadow_step_count', 6),
                             ('use_raytracing', True), ('fast_gi_method', 'AMBIENT_OCCLUSION'),
                             ('use_ssr', True), ('use_ssr_refraction', True),
                             ('taa_render_samples', 32)):
                try:
                    setattr(ee, key, val)
                except Exception as _exc:
                    _zyg_log.debug('eevee attribute %s not settable: %s', key, _exc)
        # glass and water (2026-09-16): a thin pane has no thickness for screen
        # -space refraction to bend light through, so EEVEE gets the alpha look
        # instead. Cycles keeps the transmissive material the builder wrote.
        try:
            if BP_HERE not in sys.path:
                sys.path.insert(0, BP_HERE)
            from zyg_workflows import arch_blender_build as ABB
            print('BP_EEVEE_GLASS %d' % ABB.tune_glass_for_eevee(sc))
        except Exception as e:
            print('BP_EEVEE_GLASS_FAIL %s: %s' % (type(e).__name__, e))
    else:
        sc.render.engine = 'BLENDER_WORKBENCH'
        sh = sc.display.shading
        sh.light = 'STUDIO'
        sh.show_shadows = True
        sh.show_cavity = True
        try:
            sh.cavity_type = 'BOTH'
        except Exception as _exc:
            _zyg_log.debug('workbench cavity type not settable: %s', _exc)
        # VERTEX is the only Workbench mode that shows the v3 ground's 'Col'
        # attribute; without it a grass/rock/sand/snow mesh is one flat hex.
        try:
            sh.color_type = 'VERTEX' if has_vcol else 'MATERIAL'
        except TypeError:
            sh.color_type = 'MATERIAL'
        try:
            sh.background_type = 'VIEWPORT'
            sh.background_color = BP_SKY
        except Exception as _exc:
            _zyg_log.debug('workbench background not settable: %s', _exc)
    # matrix_world still holds the identity until the view layer is evaluated, so
    # the camera's direction has to be asked for AFTER this update, not before
    bpy.context.view_layer.update()
    BP_PROBE_INFO.clear()
    if isinstance(cam_spec, dict) and cam_spec.get('kind') == 'lobby' and user_cam is None:
        _bp_unblock(sc, cam, cam_spec)
    fwd = _bp_forward(cam)
    # one JSON line naming everything the world is made of, so a test (or an
    # operator reading the log) can check the sun and the sky without a screenshot
    import json as _json
    print('BP_WORLD ' + _json.dumps(
        {'view': view, 'engine': engine, 'vcol': bool(has_vcol), 'cam': cd.type,
         'transform': transform, 'look': look, 'exposure': round(sc.view_settings.exposure, 3),
         'sun_hour': sun_hour, 'sky': list(BP_SKY), 'sun_energy': sun_d.energy,
         'sun_angle': round(math.degrees(sun_d.angle), 3),
         'sun_dir': [round(c, 4) for c in sv],
         'cam_loc': [round(c, 3) for c in cam.location],
         'cam_fwd': [round(c, 4) for c in fwd],
         'cam_lens': round(float(cd.lens), 2) if cd.type == 'PERSP' and cd.lens_unit == 'MILLIMETERS' else None,
         'cam_shift_y': round(float(cd.shift_y), 4),
         'cam_tilt_deg': round(math.degrees(float((cam_spec or {}).get('tilt') or 0.0)), 2),
         'cam_clip_start': round(float(cd.clip_start), 4),
         'cam_ortho_scale': (round(float(cd.ortho_scale), 3) if cd.type == 'ORTHO' else None),
         'cam_target': ([round(float(c), 3) for c in cam_spec['target']]
                        if (cam_spec and cam_spec.get('target')) else None),
         'cam_source': ((cam_spec.get('kind') or 'cells') if cam_spec
                        else ('script' if user_cam is not None else 'view')),
         'lo': [round(c, 3) for c in lo], 'hi': [round(c, 3) for c in hi],
         'shading': (sc.display.shading.color_type if engine == 'workbench' else ''),
         'hero': hero,
         'engine_set': sc.render.engine}))
    sc.render.resolution_x = int(width)
    sc.render.resolution_y = int(height)
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = 'PNG'
    sc.render.filepath = out_png
    bpy.ops.render.render(write_still=True)
    return out_png
'''
)
