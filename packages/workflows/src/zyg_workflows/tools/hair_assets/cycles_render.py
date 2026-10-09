# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""cycles_render.py — the photoreal render: clay mesh + baked skin + REAL hair.
blender -b --factory-startup --python cycles_render.py -- <cfg.json>

This is the other end of the split. char_hair_assets.js draws ~7,000 ribbons
1.3 mm wide so the viewport stays interactive; that is a preview and it will
never be photoreal. Here the hair is what the groom actually has — every strand
hair_extract.py pulled out of the production .blend, interpolated up to head
density, rendered as curve primitives 0.05 mm across by the Principled Hair
BSDF (Chiang, melanin-parameterised): transmission through the fibre, multiple
scattering between neighbours, self-shadowing and correct thin-geometry
anti-aliasing, all done by the renderer rather than faked by a shader.

The body is the same CC0 base sculpt the studio stands, wearing the same albedo
atlas char_photoreal.py baked — its UDIM tiles remapped into the packed grid
exactly as char_photoreal.remapUV does for three.js, so the skin here is the
skin there and not a second version of it.

MEASURED, NOT PLACED. The groom arrives in its donor's skull frame; the skull
of the body standing here is measured the same way (a least-squares sphere
through the top DOME_FRAC of the head band) and one is mapped onto the other.
No offset for this body is stored anywhere.

cfg keys:
  glb, out, albedo/manifest (optional), grooms [{npz, colour, part}],
  hdri, hdri_strength, camera {frame, az, el, lens}, size [w, h],
  samples, density, hair_radius_m, device
"""

import json
import math
import os
import sys
import time

import numpy as np

import bpy
from mathutils import Vector
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


DOME_FRAC = 0.45  # must match hair_extract.py and char_hair.js

# Melanin for the studio's hair-colour names. Grey and white are not a melanin
# level, they are its ABSENCE plus scatter, so those switch the node to direct
# colour instead of pretending a melanin value makes white hair.
MELANIN = {
    'black': (1.0, 0.08),
    'dark brown': (0.78, 0.22),
    'brown': (0.55, 0.35),
    'light brown': (0.35, 0.40),
    'dark blond': (0.22, 0.45),
    'dark blonde': (0.22, 0.45),
    'blonde': (0.10, 0.45),
    'blond': (0.10, 0.45),
    'auburn': (0.42, 0.85),
    'red': (0.28, 0.95),
    'ginger': (0.28, 0.95),
}
DIRECT = {
    'grey': (0.35, 0.34, 0.33),
    'gray': (0.35, 0.34, 0.33),
    'white': (0.62, 0.61, 0.60),
    'silver': (0.48, 0.47, 0.46),
}


# ── the body ────────────────────────────────────────────────────────────────


def import_body(glb):
    before = {o.name for o in bpy.context.scene.objects}
    bpy.ops.import_scene.gltf(filepath=glb)
    new = [o for o in bpy.context.scene.objects if o.name not in before]
    meshes = [o for o in new if o.type == 'MESH']
    for o in new:
        if o.parent is None:
            o.rotation_mode = 'XYZ'
    body = max(meshes, key=lambda o: len(o.data.vertices)) if meshes else None
    eyes = [o for o in meshes if o is not body and 'eye' in o.name.lower()]
    return new, body, eyes


def head_frames(meshes):
    """The head frame and the skull sphere of the standing body, Blender space.

    The same measurement char_hair.js makes in the viewport and hair_extract.py
    made on the donor: head band = above yTop - 0.13 * body height, skull = a
    least-squares sphere through the top DOME_FRAC of that band."""
    P = []
    for ob in meshes:
        mw = ob.matrix_world
        P.extend(mw @ v.co for v in ob.data.vertices)
    if not P:
        return None
    A = np.array([[p.x, p.y, p.z] for p in P], dtype=np.float64)
    zTop, zMin = A[:, 2].max(), A[:, 2].min()
    H = zTop - zMin
    headH = 0.13 * H
    band = A[A[:, 2] > zTop - headH]
    dome = A[A[:, 2] > zTop - DOME_FRAC * headH]
    centre, radius = sphere_fit(dome)
    return {
        'zTop': float(zTop),
        'zMin': float(zMin),
        'headOrigin': ((band[:, 0].min() + band[:, 0].max()) * 0.5, (band[:, 1].min() + band[:, 1].max()) * 0.5, zTop),
        'headW': float(band[:, 0].max() - band[:, 0].min()),
        'headH': float(headH),
        'height_m': float(H),
        'skullCentre': centre,
        'skullRadius': radius,
        'dome': int(len(dome)),
    }


def sphere_fit(A):
    if len(A) < 8:
        return None, None
    M = np.concatenate([2.0 * A, np.ones((len(A), 1))], 1)
    rhs = (A * A).sum(1)
    x, *_ = np.linalg.lstsq(M, rhs, rcond=None)
    c = x[:3]
    r2 = x[3] + float(c @ c)
    return (tuple(float(v) for v in c), math.sqrt(r2)) if r2 > 0 else (None, None)


def atlas_uv_layer(body, man):
    """A second UV layer that lands in the packed albedo atlas.

    The body is UDIM (9 x 4 tiles); the bake packs those into a 6 x 4 grid and
    char_photoreal.js remaps per VERTEX because no face on this mesh straddles
    a tile (measured: 0 of 84,680). Same rule here, per loop, off the face
    centroid — so the skin in a render is the skin in the viewport."""
    atlas = man['atlas']
    W, H = atlas['width'], atlas['height']
    lut = {(int(t[0]), int(t[1])): (t[2], t[3], t[4]) for t in atlas['tiles']}
    me = body.data
    src = me.uv_layers.active
    if src is None:
        return 0, 0
    dst = me.uv_layers.new(name='atlas')
    uv = np.zeros((len(me.loops), 2), dtype=np.float64)
    src.data.foreach_get('uv', uv.ravel())
    out = uv.copy()
    miss = 0
    for poly in me.polygons:
        ls = list(poly.loop_indices)
        c = uv[ls].mean(0)
        key = (int(math.floor(c[0])), int(math.floor(c[1])))
        cell = lut.get(key)
        if cell is None:
            miss += len(ls)
            continue
        x0, y0, sz = cell
        loc = uv[ls] - np.array([key[0], key[1]], dtype=np.float64)
        out[ls, 0] = (x0 + loc[:, 0] * sz) / W
        out[ls, 1] = 1.0 - (y0 + (1.0 - loc[:, 1]) * sz) / H
    dst.data.foreach_set('uv', out.ravel())
    me.uv_layers.active = dst
    return len(me.loops), miss


def skin_material(albedo_path, uv_name):
    m = bpy.data.materials.new('skin')
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes['Principled BSDF']
    b.inputs['Roughness'].default_value = 0.46
    b.inputs['Metallic'].default_value = 0.0
    if 'Specular IOR Level' in b.inputs:
        b.inputs['Specular IOR Level'].default_value = 0.5
    # skin scatters: without it a baked albedo reads as painted card
    for nm, val in (('Subsurface Weight', 0.22), ('Subsurface Scale', 0.012)):
        if nm in b.inputs:
            b.inputs[nm].default_value = val
    if 'Subsurface Radius' in b.inputs:
        b.inputs['Subsurface Radius'].default_value = (0.36, 0.14, 0.09)
    uvn = nt.nodes.new('ShaderNodeUVMap')
    uvn.uv_map = uv_name
    uvn.location = (-900, 0)
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.image = bpy.data.images.load(albedo_path)
    tex.location = (-620, 0)
    nt.links.new(uvn.outputs['UV'], tex.inputs['Vector'])
    nt.links.new(tex.outputs['Color'], b.inputs['Base Color'])
    if 'Subsurface Radius' in b.inputs:
        pass
    # micro-relief from the albedo's own high frequencies: pores and stubble
    # are IN the baked texture, and a flat normal throws them away under a
    # grazing key light
    bump = nt.nodes.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = 0.14
    bump.inputs['Distance'].default_value = 0.002
    bump.location = (-300, -260)
    nt.links.new(tex.outputs['Color'], bump.inputs['Height'])
    nt.links.new(bump.outputs['Normal'], b.inputs['Normal'])
    return m


def eye_material(radius_m, centre_obj, lateral, iris=(0.13, 0.075, 0.04)):
    """A plain eye, built in object space off the forward pole.

    Not char_eyes.js's 2048 px fibre iris — that is a viewport shader and
    porting it is its own job. This is enough that a portrait does not stare
    out of two clay balls: sclera, iris, pupil, and a smooth specular."""
    m = bpy.data.materials.new('eye')
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes['Principled BSDF']
    b.inputs['Roughness'].default_value = 0.08
    if 'Coat Weight' in b.inputs:
        b.inputs['Coat Weight'].default_value = 0.8
    if 'IOR' in b.inputs:
        b.inputs['IOR'].default_value = 1.376
    co = nt.nodes.new('ShaderNodeTexCoord')
    co.location = (-1400, 0)
    # Object coordinates are METRES and an eyeball is about 12 mm, so a ramp
    # written in absolute units puts the whole eye inside the first band: the
    # first render had two black holes. Normalise by the eye's own radius and
    # the stops become fractions of it.
    # bpy.ops.object.origin_set is unreliable in background mode — it was
    # caught and swallowed, and the eyes rendered as bare sclera a second time.
    # Subtract the eyeball's centre in the shader instead: no operator, no
    # context, and the number is in the report where it can be checked.
    sub = nt.nodes.new('ShaderNodeVectorMath')
    sub.operation = 'SUBTRACT'
    sub.location = (-1300, 0)
    sub.inputs[1].default_value = tuple(centre_obj)
    nt.links.new(co.outputs['Object'], sub.inputs[0])
    scale = nt.nodes.new('ShaderNodeVectorMath')
    scale.operation = 'SCALE'
    scale.location = (-1220, 0)
    scale.inputs['Scale'].default_value = 1.0 / max(radius_m, 1e-6)
    nt.links.new(sub.outputs['Vector'], scale.inputs[0])
    sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    sep.location = (-1000, 0)
    nt.links.new(scale.outputs['Vector'], sep.inputs['Vector'])
    # distance from the forward (-Y) pole, in the XZ plane
    lenn = nt.nodes.new('ShaderNodeVectorMath')
    lenn.operation = 'LENGTH'
    lenn.location = (-1000, -220)
    comb = nt.nodes.new('ShaderNodeCombineXYZ')
    comb.location = (-1160, -220)
    # The iris is radial about the axis the eye LOOKS along, and that axis is
    # not assumed: object space here is the glTF frame (Y up) while the world
    # is Z up, so 'forward' in object coordinates is whatever the object matrix
    # maps the body's facing direction to. Guessing Y gave two blank sclerae.
    axis = ('X', 'Y', 'Z')
    nt.links.new(sep.outputs[axis[lateral[0]]], comb.inputs['X'])
    nt.links.new(sep.outputs[axis[lateral[1]]], comb.inputs['Y'])
    nt.links.new(comb.outputs['Vector'], lenn.inputs[0])
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.location = (-760, -220)
    ramp.color_ramp.interpolation = 'LINEAR'
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (0.006, 0.005, 0.005, 1)  # pupil
    # stops are fractions of the eyeball radius: a human pupil is about 0.17
    # of it and the iris edge about 0.48
    e1 = ramp.color_ramp.elements.new(0.16)
    e1.color = (0.008, 0.007, 0.006, 1)
    e2 = ramp.color_ramp.elements.new(0.21)
    e2.color = (iris[0], iris[1], iris[2], 1)
    e3 = ramp.color_ramp.elements.new(0.42)
    e3.color = (iris[0] * 1.5, iris[1] * 1.6, iris[2] * 1.7, 1)
    e4 = ramp.color_ramp.elements.new(0.47)
    e4.color = (0.030, 0.024, 0.020, 1)  # limbal ring
    e5 = ramp.color_ramp.elements.new(0.52)
    e5.color = (0.74, 0.72, 0.70, 1)  # sclera
    nt.links.new(lenn.outputs['Value'], ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], b.inputs['Base Color'])
    return m


# ── the hair ────────────────────────────────────────────────────────────────


def resample(pts, counts, starts, n):
    """Every strand to n points by arc length -> (S, n, 3)."""
    S = len(starts)
    out = np.zeros((S, n, 3), dtype=np.float32)
    t = np.linspace(0.0, 1.0, n)
    for i in range(S):
        a, c = starts[i], counts[i]
        P = pts[a : a + c]
        d = np.zeros(c)
        d[1:] = np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))
        if d[-1] <= 1e-9:
            out[i] = P[0]
            continue
        d /= d[-1]
        for k in range(3):
            out[i, :, k] = np.interp(t, d, P[:, k])
    return out


def neighbours(roots, k=3):
    """k nearest source strands per strand, by root. Chunked so a 20k-strand
    groom never allocates a 20k x 20k distance matrix."""
    S = len(roots)
    k = min(k, S)
    idx = np.zeros((S, k), dtype=np.int32)
    step = max(1, int(2e7 // max(1, S)))
    for a in range(0, S, step):
        b = min(S, a + step)
        d = ((roots[a:b, None, :] - roots[None, :, :]) ** 2).sum(-1)
        idx[a:b] = np.argpartition(d, k - 1, axis=1)[:, :k]
    return idx


def densify(strands, mult, rng, jitter=0.035):
    """More strands between the ones the groom has.

    A production groom is ~10k curves; a head is 100k+ hairs. Blending three
    neighbouring strands with random barycentric weights keeps the STYLE — the
    parting, the sweep, the clumps — while filling in the density that makes it
    read as hair instead of as wires. The jitter grows toward the tip because
    roots are pinned to the scalp and ends are not."""
    S, N, _ = strands.shape
    if mult <= 1:
        return strands
    M = int(S * mult)
    nb = neighbours(strands[:, 0, :], 3)
    pick = rng.integers(0, S, M)
    tri = nb[pick]  # (M, 3)
    w = rng.random((M, 3)).astype(np.float32)
    w /= w.sum(1, keepdims=True)
    out = (
        strands[tri[:, 0]] * w[:, 0, None, None]
        + strands[tri[:, 1]] * w[:, 1, None, None]
        + strands[tri[:, 2]] * w[:, 2, None, None]
    )
    span = np.linalg.norm(strands[:, -1] - strands[:, 0], axis=1).mean()
    t = np.linspace(0.0, 1.0, N, dtype=np.float32) ** 1.5
    out += rng.standard_normal(out.shape).astype(np.float32) * (jitter * span) * t[None, :, None]
    return np.concatenate([strands, out], 0)


def build_curves(name, strands, centre, radius, root_r, tip_r):
    """A Curves object in world space, with a per-point radius taper."""
    S, N, _ = strands.shape
    # skull units, glTF axes (+Y up) -> world metres, Blender axes (+Z up)
    P = np.empty_like(strands)
    P[..., 0] = strands[..., 0]
    P[..., 1] = -strands[..., 2]
    P[..., 2] = strands[..., 1]
    P = P * radius + np.asarray(centre, dtype=np.float32)

    cu = bpy.data.hair_curves.new(name)
    cu.add_curves([N] * S)
    cu.attributes['position'].data.foreach_set('vector', P.reshape(-1).tolist())
    rad = cu.attributes.get('radius') or cu.attributes.new('radius', 'FLOAT', 'POINT')
    taper = np.linspace(1.0, tip_r / max(root_r, 1e-9), N, dtype=np.float32) * root_r
    rad.data.foreach_set('value', np.tile(taper, S).tolist())
    ob = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(ob)
    return ob, S, S * N


def hair_material(name, colour):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type == 'BSDF_PRINCIPLED':
            nt.nodes.remove(n)
    out = nt.nodes.get('Material Output')
    h = nt.nodes.new('ShaderNodeBsdfHairPrincipled')
    h.location = (-300, 0)
    if hasattr(h, 'model'):
        h.model = 'CHIANG'
    key = str(colour or 'dark brown').lower()
    if key in DIRECT:
        h.parametrization = 'COLOR'
        h.inputs['Color'].default_value = DIRECT[key] + (1.0,)
    else:
        mel, red = MELANIN.get(key, MELANIN['dark brown'])
        h.parametrization = 'MELANIN'
        h.inputs['Melanin'].default_value = mel
        h.inputs['Melanin Redness'].default_value = red
        if 'Random Color' in h.inputs:
            h.inputs['Random Color'].default_value = 0.12
    if 'Roughness' in h.inputs:
        h.inputs['Roughness'].default_value = 0.28
    if 'Radial Roughness' in h.inputs:
        h.inputs['Radial Roughness'].default_value = 0.22
    nt.links.new(h.outputs[0], out.inputs['Surface'])
    return m


# ── scene ───────────────────────────────────────────────────────────────────


def world_hdri(path, strength):
    w = bpy.data.worlds.new('w')
    bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    bg = nt.nodes['Background']
    bg.inputs['Strength'].default_value = strength
    if path and os.path.isfile(path):
        env = nt.nodes.new('ShaderNodeTexEnvironment')
        env.image = bpy.data.images.load(path)
        env.location = (-400, 0)
        nt.links.new(env.outputs['Color'], bg.inputs['Color'])
    else:
        bg.inputs['Color'].default_value = (0.05, 0.055, 0.065, 1)
    return w


# What each framing should cover vertically, and the lens it wants. Distance is
# then GEOMETRY, not a magic multiplier: for a vertical sensor,
#     d = coverage * lens_mm / sensor_mm
# The first pass used hand-tuned multipliers and 'body' came out framing a
# torso — 0.60 m of coverage on a 1.69 m figure.
SENSOR_MM = 24.0

# Coverage and centre for each framing. 'head' and 'bust' are fractions of the
# measured head; 'body' is the body's OWN bounding box, because a fraction of
# total height put the feet on the bottom edge — the base sculpt does not stand
# exactly on z = 0 and the margin has to come from the geometry, not a guess.
FRAMING = {'head': 85.0, 'bust': 85.0, 'body': 50.0}


def _framing(F, frame):
    if frame == 'body':
        span = F['zTop'] - F['zMin']
        return span * 1.06, (F['zTop'] + F['zMin']) * 0.5
    if frame == 'bust':
        return F['headH'] * 3.20, F['headOrigin'][2] - F['headH'] * 1.30
    return F['headH'] * 1.55, F['headOrigin'][2] - F['headH'] * 0.44


def place_camera(F, frame, az, el, lens=None):
    """Distance is GEOMETRY: for a vertical sensor, d = coverage * lens / sensor.

    The first pass used hand-tuned multipliers and 'body' framed a torso —
    0.60 m of coverage on a 1.69 m figure."""
    lens = float(lens or FRAMING.get(frame, 85.0))
    coverage, ctr_z = _framing(F, frame)
    d = coverage * lens / SENSOR_MM
    cam_d = bpy.data.cameras.new('cam')
    cam_d.lens = lens
    cam_d.sensor_fit = 'VERTICAL'
    cam_d.sensor_height = SENSOR_MM
    cam = bpy.data.objects.new('cam', cam_d)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    hx, hy, _hz = F['headOrigin']
    tgt = Vector((hx, hy, ctr_z))
    a, e = math.radians(az), math.radians(el)
    cam.location = tgt + Vector((d * math.cos(e) * math.sin(a), -d * math.cos(e) * math.cos(a), d * math.sin(e)))
    cam.rotation_euler = (tgt - cam.location).to_track_quat('-Z', 'Y').to_euler()
    return cam, {'lens': lens, 'distance_m': round(d, 3), 'coverage_m': round(coverage, 3), 'centre_z': round(ctr_z, 3)}


def set_device(scene, want):
    prefs = bpy.context.preferences.addons['cycles'].preferences
    used = 'CPU'
    if want != 'CPU':
        for t in ('OPTIX', 'CUDA'):
            try:
                prefs.compute_device_type = t
                prefs.get_devices()
                on = 0
                for d in prefs.devices:
                    d.use = d.type == t
                    on += 1 if d.use else 0
                if on:
                    scene.cycles.device = 'GPU'
                    used = t
                    break
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.debug('compute device type %s unavailable: %s', t, _exc)
                continue
    if used == 'CPU':
        scene.cycles.device = 'CPU'
    return used


def main():
    t_all = time.time()
    cfg = json.load(open(sys.argv[sys.argv.index('--') + 1]))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    rep = {'cfg': {k: v for k, v in cfg.items() if k != 'grooms'}, 'grooms': []}

    # body
    t0 = time.time()
    new, body, eyes = import_body(cfg['glb'])
    meshes = [o for o in new if o.type == 'MESH']
    F = head_frames([body] if body else meshes)
    rep['frames'] = {k: v for k, v in F.items()}
    man_p = cfg.get('manifest')
    if body and cfg.get('albedo') and man_p and os.path.isfile(man_p):
        man = json.load(open(man_p))
        loops, miss = atlas_uv_layer(body, man)
        body.data.materials.clear()
        body.data.materials.append(skin_material(cfg['albedo'], 'atlas'))
        rep['skin'] = {
            'atlas': f'{man["atlas"]["width"]}x{man["atlas"]["height"]}',
            'loops': loops,
            'loops_outside_tiles': miss,
        }
    elif body:
        clay = bpy.data.materials.new('clay')
        clay.use_nodes = True
        clay.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.62, 0.58, 0.53, 1)
        clay.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 0.8
        body.data.materials.clear()
        body.data.materials.append(clay)
        rep['skin'] = {'atlas': None}
    for o in eyes:
        # Object texture coordinates are relative to the object ORIGIN, and the
        # glTF importer leaves every origin at the scene origin: the radial
        # iris was measured from the body's centre line, so the whole eyeball
        # fell past the last ramp stop and rendered as bare sclera. Put the
        # origin on the eyeball first and 'Object' means what it says.
        bb = [Vector(c) for c in o.bound_box]  # already object space
        er = max(max(p[i] for p in bb) - min(p[i] for p in bb) for i in range(3)) * 0.5
        ctr = [(max(p[i] for p in bb) + min(p[i] for p in bb)) * 0.5 for i in range(3)]
        # the body faces -Y in world; carry that into this object's own frame
        fwd = o.matrix_world.to_3x3().inverted() @ Vector((0.0, -1.0, 0.0))
        fa = max(range(3), key=lambda i: abs(fwd[i]))
        lateral = tuple(i for i in range(3) if i != fa)
        em = eye_material(er, ctr, lateral)
        rep.setdefault('eye_forward_axis', 'XYZ'[fa])
        rep.setdefault('eye_radius_m', round(er, 5))
        rep.setdefault('eye_centre_obj', [round(v, 4) for v in ctr])
        o.data.materials.clear()
        o.data.materials.append(em)
    rep['eyes'] = len(eyes)
    rep['t_body'] = round(time.time() - t0, 2)

    # hair
    rng = np.random.default_rng(int(cfg.get('seed', 7)))
    density = float(cfg.get('density', 8.0))
    root_r = float(cfg.get('hair_radius_m', 5e-5))
    samples_n = int(cfg.get('strand_samples', 24))
    t0 = time.time()
    for g in cfg.get('grooms', []):
        if not os.path.isfile(g['npz']):
            rep['grooms'].append({'npz': g['npz'], 'error': 'missing'})
            continue
        z = np.load(g['npz'])
        meta = json.loads(str(z['meta']))
        st = resample(z['pts'], z['counts'], z['starts'], samples_n)
        st = densify(st, density if meta['part'] != 'brows' else min(density, 3.0), rng)
        rr = root_r * (0.8 if meta['part'] == 'brows' else 1.0)
        ob, S, NP = build_curves(f'hair_{meta["part"]}', st, F['skullCentre'], F['skullRadius'], rr, rr * 0.35)
        ob.data.materials.append(hair_material(f'hair_{meta["part"]}', g.get('colour', 'dark brown')))
        rep['grooms'].append(
            {
                'part': meta['part'],
                'character': meta['character'],
                'source_strands': int(meta['strands']),
                'rendered_strands': int(S),
                'points': int(NP),
                'colour': g.get('colour', 'dark brown'),
                'root_radius_mm': round(rr * 1000, 4),
            }
        )
    rep['t_hair'] = round(time.time() - t0, 2)

    # world, camera, render
    world_hdri(cfg.get('hdri'), float(cfg.get('hdri_strength', 1.0)))
    cam_cfg = cfg.get('camera', {})
    _cam, rep['camera'] = place_camera(
        F,
        cam_cfg.get('frame', 'head'),
        float(cam_cfg.get('az', 0.0)),
        float(cam_cfg.get('el', 0.0)),
        cam_cfg.get('lens'),
    )
    rep['camera']['frame'] = cam_cfg.get('frame', 'head')
    sc.render.engine = 'CYCLES'
    rep['device'] = set_device(sc, cfg.get('device', 'OPTIX'))
    w, h = cfg.get('size', [1080, 1350])
    sc.render.resolution_x, sc.render.resolution_y = int(w), int(h)
    sc.render.resolution_percentage = 100
    sc.cycles.samples = int(cfg.get('samples', 256))
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.use_denoising = True
    sc.cycles.max_bounces = 16
    sc.cycles.transmission_bounces = 16
    sc.cycles.transparent_max_bounces = 40  # hair is deep transparent geometry
    for holder, attr, val in (
        (getattr(sc, 'cycles_curves', None), 'shape', 'RIBBONS'),
        (getattr(sc, 'cycles_curves', None), 'subdivisions', 2),
    ):
        if holder is not None and hasattr(holder, attr):
            try:
                setattr(holder, attr, val)
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.warning('cycles setting %s could not be applied, keeping the default: %s', attr, _exc)
    sc.render.film_transparent = bool(cfg.get('transparent', False))
    sc.render.image_settings.file_format = 'PNG'
    sc.render.filepath = cfg['out']
    # The 4090 is SHARED: a measured bench run died on 'Failed to build OptiX
    # acceleration structure' with 2.1 GB free because ComfyUI held 28 GB and
    # Ollama 13.9 GB. A picture that cannot have the GPU should come out slowly,
    # not not at all — and the report says which device drew it.
    t0 = time.time()
    try:
        bpy.ops.render.render(write_still=True)
    except RuntimeError as e:
        if rep['device'] == 'CPU':
            raise
        rep['gpu_error'] = str(e)[:200]
        rep['device_fallback'] = True
        sc.cycles.device = 'CPU'
        rep['device'] = 'CPU'
        t0 = time.time()
        bpy.ops.render.render(write_still=True)
    rep['t_render'] = round(time.time() - t0, 2)
    rep['t_total'] = round(time.time() - t_all, 2)
    rep['out'] = cfg['out']
    rep['samples'] = sc.cycles.samples
    rep['size'] = [int(w), int(h)]
    if cfg.get('report'):
        with open(cfg['report'], 'w') as fh:
            json.dump(rep, fh, indent=1)
    print('ZYGRENDER' + json.dumps(rep))
    print('CYCLES_RENDER_OK')


main()
