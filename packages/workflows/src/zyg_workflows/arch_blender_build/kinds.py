# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bmesh helpers, the kind vocabulary and the arch_blender_ext builders.

Moved verbatim out of the old single-file arch_blender_build.py (lines 489-865).
"""

import math
import os

import bmesh
from mathutils import Matrix

from zyg_workflows import paths

# Bound by assignment rather than `from … import` on purpose: CPython emits the
# LOAD_METHOD form for `X.method()` only when X was not bound by an import
# statement, and the moved lines below were compiled against a plain global.
from zyg_workflows.arch_blender_build import materials as _materials

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

MAT_COLOURS = _materials.MAT_COLOURS
MAT_FALLBACK = _materials.MAT_FALLBACK


# ── bmesh helpers (all LOCAL: X = along, Y = across, Z = up) ────────────────
def num(p, k, d):
    v = p.get(k, d)
    try:
        v = float(v)
    except (TypeError, ValueError):
        return float(d)
    return v if math.isfinite(v) else float(d)


def add_box(bm, x0, x1, y0, y1, z0, z1, mi=0):
    vs = [
        bm.verts.new(v)
        for v in (
            (x0, y0, z0),
            (x1, y0, z0),
            (x1, y1, z0),
            (x0, y1, z0),
            (x0, y0, z1),
            (x1, y0, z1),
            (x1, y1, z1),
            (x0, y1, z1),
        )
    ]
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        f = bm.faces.new([vs[i] for i in idx])
        f.material_index = mi


def add_box_c(bm, sx, sy, sz, cx=0.0, cy=0.0, z0=0.0, mi=0):
    """box of size sx*sy*sz centred at (cx, cy) in plan, bottom at z0."""
    add_box(bm, cx - sx / 2, cx + sx / 2, cy - sy / 2, cy + sy / 2, z0, z0 + sz, mi)


def _tag(bm, geom, mi):
    for g in geom:
        if isinstance(g, bmesh.types.BMFace):
            g.material_index = mi


def add_cylinder(bm, r, h, z0=0.0, seg=32, cx=0.0, cy=0.0, r_top=None, mi=0):
    seg = max(3, int(seg))
    r_top = r if r_top is None else r_top
    res = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg, radius1=r, radius2=r_top, depth=h)
    vs = res['verts']
    bmesh.ops.translate(bm, verts=vs, vec=(cx, cy, z0 + h / 2))
    _tag(bm, {f for v in vs for f in v.link_faces}, mi)
    return vs


def add_sphere(bm, r, cz, cx=0.0, cy=0.0, useg=24, vseg=12, sz=1.0, mi=0):
    res = bmesh.ops.create_uvsphere(bm, u_segments=useg, v_segments=vseg, radius=r)
    vs = res['verts']
    if sz != 1.0:
        bmesh.ops.scale(bm, verts=vs, vec=(1.0, 1.0, sz))
    bmesh.ops.translate(bm, verts=vs, vec=(cx, cy, cz))
    _tag(bm, {f for v in vs for f in v.link_faces}, mi)
    return vs


def add_prism(bm, profile, axis, a0, a1, mi=0):
    """Extrude a closed 2-D profile along `axis`.
    axis 'x': profile (u, v) = (Y, Z), swept from X=a0 to X=a1.
    axis 'y': profile (u, v) = (X, Z), swept from Y=a0 to Y=a1."""

    def pt(u, v, a):
        return (a, u, v) if axis == 'x' else (u, a, v)

    v0 = [bm.verts.new(pt(u, v, a0)) for u, v in profile]
    v1 = [bm.verts.new(pt(u, v, a1)) for u, v in profile]
    faces = [bm.faces.new(v0), bm.faces.new(list(reversed(v1)))]
    n = len(profile)
    for i in range(n):
        j = (i + 1) % n
        faces.append(bm.faces.new((v0[i], v0[j], v1[j], v1[i])))
    for f in faces:
        f.material_index = mi


def add_dome(bm, r, h, seg=32, rings=16, mi=0):
    """half sphere of radius r, squashed to height h, sitting on z=0."""
    faces = []
    rows = []
    for k in range(rings + 1):
        phi = (math.pi / 2) * k / rings  # 0 = rim, pi/2 = apex
        z = math.sin(phi) * h
        rr = math.cos(phi) * r
        if k == rings:
            rows.append([bm.verts.new((0.0, 0.0, z))])
            break
        rows.append(
            [
                bm.verts.new((math.cos(2 * math.pi * i / seg) * rr, math.sin(2 * math.pi * i / seg) * rr, z))
                for i in range(seg)
            ]
        )
    for k in range(rings):
        a, b = rows[k], rows[k + 1]
        for i in range(seg):
            j = (i + 1) % seg
            if len(b) == 1:
                faces.append(bm.faces.new((a[i], a[j], b[0])))
            else:
                faces.append(bm.faces.new((a[i], a[j], b[j], b[i])))
    faces.append(bm.faces.new(list(reversed(rows[0]))))  # floor cap
    for f in faces:
        f.material_index = mi


def add_hip(bm, W, D, h, mi=0):
    """hip roof: rectangular eave W (along X) x D (along Y), ridge along X."""
    rx = max(0.001, (W - D) / 2)
    v = [
        bm.verts.new(p)
        for p in (
            (-W / 2, -D / 2, 0),
            (W / 2, -D / 2, 0),
            (W / 2, D / 2, 0),
            (-W / 2, D / 2, 0),
            (-rx, 0, h),
            (rx, 0, h),
        )
    ]
    for idx in ((0, 1, 5, 4), (2, 3, 4, 5), (1, 2, 5), (3, 0, 4), (0, 3, 2, 1)):
        f = bm.faces.new([v[i] for i in idx])
        f.material_index = mi


# ── kinds ──────────────────────────────────────────────────────────────────
PLACEHOLDER_KINDS = {'ramp', 'railing', 'ladder', 'truss', 'stair_l', 'stair_spiral', 'asset'}


# ── extensions (2026-09-06) ────────────────────────────────────────────────
# arch_blender_ext/*.py — one file per capability family, mirroring
# arch_ext/*.js. Each defines BUILDERS = {kind: fn(bm, p, kit)} where fn fills
# bm with LOCAL geometry (same frame as build_kind: X along, Y depth, Z up,
# bottom at z=0) and returns None or (prefix, extra_material_ids). `kit` is a
# dict of the helpers in this file: add_box, add_box_c, add_cylinder,
# add_sphere, add_prism, add_dome, add_hip, num, bmesh, math.
_EXT_BUILDERS = None


def ext_builders():
    global _EXT_BUILDERS
    if _EXT_BUILDERS is not None:
        return _EXT_BUILDERS
    _EXT_BUILDERS = {}
    import glob
    import importlib.util

    # the extensions live beside the package, under zyg_workflows/arch_blender_ext/
    for f in sorted(glob.glob(os.path.join(str(paths.PKG_DIR), 'arch_blender_ext', '*.py'))):
        name = os.path.splitext(os.path.basename(f))[0]
        if name.startswith('_'):
            continue
        try:
            spec = importlib.util.spec_from_file_location('arch_blender_ext.' + name, f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for k, fn in (getattr(mod, 'BUILDERS', {}) or {}).items():
                _EXT_BUILDERS[k] = fn
        except Exception as e:  # noqa: BLE001
            _zyg_log.info(f'[arch_blender_build] extension {name} skipped: {e!r}')
    return _EXT_BUILDERS


def mat_rgb(mat_id):
    """(r, g, b) 0..1 for a material preset — the studio's own hex. The v3 ground
    colours its own vertices from these, so its grass is the grass preset."""
    key = mat_id or 'mat_concrete'
    key = key[4:] if key.startswith('mat_') else key
    c = MAT_COLOURS.get(key, MAT_FALLBACK)
    return (c[0], c[1], c[2])


def ext_kit(records=None):
    """The helpers an extension builder gets. `records` is the drawing's whole
    object list (2026-09-07): the v3 ground is a function of every sculpt_*
    record in the drawing, so a builder that has only its own `p` cannot build
    it. Read-only by convention."""
    return {
        'add_box': add_box,
        'add_box_c': add_box_c,
        'add_cylinder': add_cylinder,
        'add_sphere': add_sphere,
        'add_prism': add_prism,
        'add_dome': add_dome,
        'add_hip': add_hip,
        'num': num,
        'bmesh': bmesh,
        'math': math,
        'records': list(records or []),
        'mat_rgb': mat_rgb,
    }


def build_kind(bm, kind, p, records=None):
    """Fill bm with the LOCAL geometry for one record.  Returns
    (name_prefix, extra_material_ids) where extra_material_ids are the
    material slots beyond slot 0 (None = keep the record's material).
    An extension builder may return a THIRD element, `vcolors`: one (r, g, b)
    per vertex in bm.verts order, which the record loop turns into a 'Col'
    colour attribute and a material that reads it."""
    N = lambda k, d: num(p, k, d)
    extra = []
    prefix = ''
    ext = ext_builders().get(kind)
    if ext is not None:
        r = ext(bm, p, ext_kit(records))
        if isinstance(r, tuple) and len(r) == 3:
            return str(r[0] or ''), list(r[1] or []), list(r[2] or [])
        if isinstance(r, tuple) and len(r) == 2:
            return str(r[0] or ''), list(r[1] or [])
        return '', []

    if kind in ('wall', 'partition'):
        L, h, t = N('len', 4), N('h', 2.7), N('t', 0.10 if kind == 'partition' else 0.24)
        add_box_c(bm, L, t, h)
    elif kind in ('door', 'double_door'):
        # Jambs + head + leaf/leaves, the same frame the tab draws
        # (inspection.html arGeom 'door'/'double_door') and the same one every
        # arch_blender_ext opening uses (_frame, FT=0.06, WT=0.16): the bare
        # 0.04 m leaf this used to build read 2.40 x 2.70 x 0.04 against the
        # tab's 2.52 x 2.76 x 0.16 on the live tower's entrance.
        w, h = N('w', 1.6 if kind == 'double_door' else 0.9), N('h', 2.1)
        dt = N('t', 0.06) + 0.10
        add_box_c(bm, 0.06, dt, h, cx=-(w / 2 + 0.03))
        add_box_c(bm, 0.06, dt, h, cx=(w / 2 + 0.03))
        add_box_c(bm, w + 0.12, dt, 0.06, z0=h)
        if kind == 'double_door':
            add_box_c(bm, w / 2 - 0.02, 0.045, h - 0.04, cx=-w / 4)
            add_box_c(bm, w / 2 - 0.02, 0.045, h - 0.04, cx=w / 4)
        else:
            add_box_c(bm, w - 0.03, 0.045, h - 0.04)
    elif kind == 'window':
        w, h, sill = N('w', 1.2), N('h', 1.4), N('sill', 0.9)
        add_box_c(bm, w, 0.04, h, z0=sill)
    elif kind == 'column_rect':
        add_box_c(bm, N('w', 0.3), N('d', 0.3), N('h', 3))
    elif kind == 'column_round':
        add_cylinder(bm, N('r', 0.18), N('h', 3), seg=24)
    elif kind == 'beam':
        add_box_c(bm, N('len', 5), N('w', 0.2), N('h', 0.4))
    elif kind == 'slab':
        add_box_c(bm, N('w', 6), N('d', 4), N('t', 0.22))
    elif kind == 'footing':
        add_box_c(bm, N('w', 1), N('d', 1), N('t', 0.35))
    elif kind == 'pad':
        t = N('t', 0.2)
        add_box_c(bm, N('w', 20), N('d', 20), t, z0=-t)  # studio: pad TOP is the ground plane
    elif kind == 'road':
        add_box_c(bm, N('len', 20), N('w', 6), N('t', 0.08))
    elif kind == 'path':
        add_box_c(bm, N('len', 10), N('w', 1.2), N('t', 0.05))
    elif kind == 'roof_flat':
        add_box_c(bm, N('w', 8), N('d', 6), N('t', 0.3))
    elif kind == 'roof_gable':
        w, d, h, o = N('w', 8), N('d', 6), N('h', 2.4), N('over', 0.4)
        D = d / 2 + o
        add_prism(bm, [(-D, 0), (D, 0), (0, h)], 'x', -(w / 2 + o), w / 2 + o)
    elif kind == 'roof_hip':
        w, d, h, o = N('w', 8), N('d', 6), N('h', 2.4), N('over', 0.4)
        add_hip(bm, w + 2 * o, d + 2 * o, h)
    elif kind == 'roof_shed':
        w, d, h, o = N('w', 6), N('d', 4), N('h', 1.6), N('over', 0.3)
        D = d / 2 + o
        add_prism(bm, [(-D, 0), (D, 0), (D, h), (-D, 0.05)], 'x', -(w / 2 + o), w / 2 + o)
    elif kind == 'roof_vault':
        w, d, h = N('w', 4), N('d', 8), N('h', 2)
        arc = [(math.cos(math.pi * (1 - i / 28)) * w / 2, math.sin(math.pi * (1 - i / 28)) * h) for i in range(29)]
        add_prism(bm, arc, 'x', -d / 2, d / 2)
    elif kind == 'roof_dome':
        r = N('r', 3)
        add_dome(bm, r, N('h', r * 0.8))
    elif kind == 'box':
        add_box_c(bm, N('w', 1), N('d', 1), N('h', 1))
    elif kind == 'cylinder':
        add_cylinder(bm, N('r', 0.5), N('h', 1), seg=N('seg', 32))
    elif kind == 'sphere':
        r = N('r', 0.5)
        add_sphere(bm, r, r, useg=max(4, int(N('seg', 32))), vseg=max(3, int(N('seg', 32) / 2)))
    elif kind == 'cone':
        add_cylinder(bm, N('r', 0.5), N('h', 1), seg=N('seg', 32), r_top=0.0)
    elif kind == 'pyramid':
        vs = add_cylinder(bm, N('r', 0.7), N('h', 1), seg=N('sides', 4), r_top=0.0)
        bmesh.ops.rotate(bm, verts=vs, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 4, 3, 'Z'))
    elif kind == 'torus':
        r, rt = N('r', 0.5), N('rt', 0.15)
        seg = max(6, int(N('seg', 32)))
        rows = [
            [
                bm.verts.new(
                    (
                        (r + rt * math.cos(2 * math.pi * j / 14)) * math.cos(2 * math.pi * i / seg),
                        (r + rt * math.cos(2 * math.pi * j / 14)) * math.sin(2 * math.pi * i / seg),
                        rt + rt * math.sin(2 * math.pi * j / 14),
                    )
                )
                for j in range(14)
            ]
            for i in range(seg)
        ]
        for i in range(seg):
            a, b = rows[i], rows[(i + 1) % seg]
            for j in range(14):
                k = (j + 1) % 14
                bm.faces.new((a[j], b[j], b[k], a[k]))
    elif kind == 'wedge':
        w, d, h = N('w', 1), N('d', 1), N('h', 1)
        add_prism(bm, [(-d / 2, 0), (d / 2, 0), (d / 2, h)], 'x', -w / 2, w / 2)
    elif kind == 'capsule':
        r, h = N('r', 0.3), N('h', 1)
        add_cylinder(bm, r, h, z0=r, seg=N('seg', 24))
        add_sphere(bm, r, r)
        add_sphere(bm, r, r + h)
    elif kind == 'plane':
        w, d = N('w', 2), N('d', 2)
        bm.faces.new(
            [bm.verts.new(v) for v in ((-w / 2, -d / 2, 0), (w / 2, -d / 2, 0), (w / 2, d / 2, 0), (-w / 2, d / 2, 0))]
        )
    elif kind == 'disc':
        bmesh.ops.create_circle(bm, cap_ends=True, radius=N('r', 1), segments=max(6, int(N('seg', 48))))
    elif kind == 'tree':
        h, rc, rt = N('h', 6), N('r_can', 2), N('r_trunk', 0.18)
        add_cylinder(bm, rt, h * 0.45, seg=10, r_top=rt * 0.8, mi=0)
        add_sphere(bm, rc, h * 0.45 + rc * 0.9, useg=16, vseg=12, sz=1.25, mi=1)
        extra = ['mat_grass']
    elif kind == 'bollard':
        add_cylinder(bm, N('r', 0.09), N('h', 0.9), seg=14)
    elif kind == 'person':
        h = N('h', 1.75)
        head, body = h * 0.13, h * 0.52
        legs = h - body - head
        lr, tr = h * 0.055, h * 0.11
        add_cylinder(bm, lr, legs, cx=-h * 0.05, seg=10)
        add_cylinder(bm, lr, legs, cx=h * 0.05, seg=10)
        add_cylinder(bm, tr, body, z0=legs, seg=12)
        add_sphere(bm, head * 0.62, h - head * 0.62, useg=14, vseg=10)
    elif kind == 'stair_straight':
        ns = max(1, int(round(N('steps', 16))))
        rise, run, w = N('rise', 0.175), N('run', 0.28), N('w', 1.0)
        x0 = -(ns * run) / 2
        for i in range(ns):
            add_box(bm, x0 + run * i, x0 + run * (i + 1), -w / 2, w / 2, rise * i, rise * (i + 1))
    # ── placeholders ("~" prefix) ──
    elif kind == 'ramp':
        L, w, rise, t = N('len', 6), N('w', 1.5), N('rise', 0.5), N('t', 0.15)
        add_prism(bm, [(-L / 2, 0), (L / 2, 0), (L / 2, rise + t), (-L / 2, t)], 'y', -w / 2, w / 2)
        prefix = '~'
    elif kind == 'railing':
        add_box_c(bm, N('len', 3), 0.04, N('h', 1.0))
        prefix = '~'
    elif kind == 'ladder':
        add_box_c(bm, N('w', 0.5), 0.08, N('h', 3))
        prefix = '~'
    elif kind == 'truss':
        add_box_c(bm, N('span', 8), N('w', 0.12), N('h', 1.2))
        prefix = '~'
    elif kind == 'stair_l':
        na, nb = max(1, int(round(N('steps_a', 8)))), max(1, int(round(N('steps_b', 8))))
        rise, run, w = N('rise', 0.175), N('run', 0.28), N('w', 1.0)
        add_box(bm, 0, run * na + w, -w / 2, w / 2 + run * nb, 0, rise * (na + nb + 1))
        prefix = '~'
    elif kind == 'stair_spiral':
        sn, sr = max(3, int(round(N('steps', 18)))), N('rise', 0.19)
        add_cylinder(bm, N('r_out', 1.1), sr * sn + 0.2, seg=24)
        prefix = '~'
    elif kind == 'asset':
        add_box_c(bm, N('bw', 0.8), N('bd', 0.8), N('bh', 0.8))
        prefix = '~'
    elif kind.startswith('guide_'):
        add_box_c(bm, 1, 1, 1)
        prefix = '~'
    else:
        add_box_c(bm, 0.5, 0.5, 0.5)
        prefix = '?'
    return prefix, extra
