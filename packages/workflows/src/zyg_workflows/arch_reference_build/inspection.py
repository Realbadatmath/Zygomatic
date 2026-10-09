# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_reference_build.inspection — the inspection set: the pictures a finished
asset is judged on, each carrying the measurement its camera made (lines
694-1264 of the original single file, moved verbatim).
"""

import logging as _zyg_logging
import math

import bmesh
import bpy
import mathutils

from .api import asset_meshes, asset_objects
from .base import log
from .scene import _bounds, _ortho_span, _photo_look, _setup, _shoot, _sun, _world

_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_reference_build')

# ── the inspection set: the pictures a finished asset is JUDGED on ───────────
# 2026-09-23, the operator's rule: "when the ai assistant is finished with a
# drawing, have it take 10 screenshots from different angles and from within
# the ship". ONE iso view hides everything that matters: a deck floating two
# metres above the sheer still reads as a deck, a mast stepped in mid-air still
# reads as a mast, and a hull open along its centreline still reads as a hull.
# Ten do not — four standpoints around it, one above, two CUT PLANES and three
# from INSIDE.
#
# Every camera is placed from the asset's own bounds, and the inside ones from
# a RAY CAST onto the surface under them: a camera parked at a guessed height
# is either buried in the deck or floating over it, and both come back as an
# unreadable frame that costs a whole round of the loop to diagnose. The cast
# also MEASURES what it found (the surface height, the headroom over it, the
# clear distance ahead) and those numbers go back in the reply beside the
# picture — "the deck under the camera is at 9.30 m with 3.1 m of headroom" is
# a fact; "it looks about right" is not.
# The order IS the default set: the first ten are what a finished build shows.
# Five standpoints outside, two cut planes, THREE from inside — the operator
# asked for "different angles and from within", and two interiors out of ten is
# not from within.
INSPECT_ALL = (
    'bow_quarter',
    'beam',
    'bow',
    'stern',
    'aerial',
    'section_long',
    'section_mid',
    'inside_fwd',
    'inside_aft',
    'inside_below',
    'stern_quarter',
    'plan',
    'underside',
)
INSPECT_N = 10  # the operator's number
# A ship seen end-on, and a section across it, are TALL subjects: in a 16:9
# frame they fit by their height and leave two thirds of the picture empty.
# Those three views get the frame turned on its side.
PORTRAIT_VIEWS = frozenset({'bow', 'stern', 'section_mid'})
INSPECT_FOCAL = 35.0  # the outside lens, on a 36 mm sensor
INSPECT_FOCAL_IN = 18.0  # inside: wide, or a deck is a wall
INSPECT_SENSOR = 36.0
EYE_M = 1.70  # a person's eye above the surface they stand on
FIG_H = 1.75  # ... and the figure that stands there, for scale
HEAD_M = 1.90  # headroom a standpoint needs to count as a floor
HOLD_M = 1.30  # ... below decks, where a man stoops
CLEAR_M = 2.5  # less air than this ahead of a camera = blocked


def _cast(origin, direction, dist=1.0e4):
    """(hit, location, normal, object) for one ray in the evaluated scene."""
    dg = bpy.context.evaluated_depsgraph_get()
    o = mathutils.Vector(origin)
    d = mathutils.Vector(direction).normalized()
    try:
        hit, loc, nor, _idx, ob, _mw = bpy.context.scene.ray_cast(dg, o, d, distance=dist)
    except Exception:  # noqa: BLE001
        return (False, None, None, None)
    return (bool(hit), loc, nor, ob)


def _floor_like(x, y, z, r, tol=0.45):
    """Is the surface at (x, y, z) a FLOOR, or just the top of something?

    Four probes at radius r, and three of them must land within tol of the same
    height. This is the rule that stops an inside camera being parked on a
    yard-arm 22 m up: a yard is 0.4 m thick, so the two probes along the ship
    miss it entirely, while a deck answers on all four. The radius scales with
    the asset, because 0.7 m of deck is a floor on a launch and a ledge on a
    ship of the line."""
    n = 0
    for dx, dy in ((r, 0.0), (-r, 0.0), (0.0, r), (0.0, -r)):
        hit, loc, nor, _ob = _cast((x + dx, y + dy, z + 0.9), (0, 0, -1), dist=2.6)
        if hit and nor is not None and nor.z > 0.5 and abs(loc.z - z) <= tol:
            n += 1
    return n >= 3


def _floors(x, y, z_from, z_to, head_m=HEAD_M, limit=8, r=0.7):
    """Every surface a person could stand on under (x, y), top down, as
    [(z, headroom)]. A surface counts when its normal points UP, there is
    head_m of air above it, and it is wide enough to stand on — which is what
    separates the deck you walk on from the underside of the one above, from
    the top of a barrel and from a spar."""
    out, z = [], float(z_from)
    for _ in range(limit * 4):
        if z <= z_to or len(out) >= limit:
            break
        hit, loc, nor, _ob = _cast((x, y, z), (0, 0, -1), dist=max(0.05, z - z_to))
        if not hit:
            break
        z = loc.z - 0.04
        if nor is None or nor.z < 0.55:
            continue
        up, uloc, _un, _uo = _cast((loc.x, loc.y, loc.z + 0.06), (0, 0, 1), dist=400.0)
        head = (uloc.z - loc.z) if up else 999.0
        if head >= head_m and _floor_like(loc.x, loc.y, loc.z, r):
            out.append((round(loc.z, 3), round(min(head, 999.0), 2)))
    return out


def _standpoints(lo, hi, n=24, head_m=HEAD_M):
    """Where a person could actually stand, sampled along the length on the
    centreline: [(x, z, headroom, floors_below)].

    Sampled rather than assumed, because the asset's bounding box is not the
    thing you walk on: on this ship it reaches 11 m forward of the stem along
    the bowsprit and 38 m up the topmast, and a camera placed at a fraction of
    THAT is in the air every time."""
    r = min(2.0, max(0.55, 0.06 * max(hi[0] - lo[0], hi[1] - lo[1])))
    out = []
    for i in range(n):
        x = lo[0] + (hi[0] - lo[0]) * (i + 0.5) / float(n)
        fl = _floors(x, 0.0, hi[2] + 1.0, lo[2] - 1.0, head_m=head_m, r=r)
        if fl:
            out.append((round(x, 3), fl[0][0], fl[0][1], fl[1:]))
    return out


def _clear_ahead(loc, target):
    """How far the camera can see before it hits something."""
    d = mathutils.Vector(target) - mathutils.Vector(loc)
    if d.length < 1e-6:
        return 0.0
    hit, hloc, _n, _o = _cast(loc, d, dist=1.0e4)
    return round((mathutils.Vector(hloc) - mathutils.Vector(loc)).length, 2) if hit else 999.0


def _sphere(objs):
    b = _bounds(objs)
    if b is None:
        return None
    lo, hi = b
    ctr = mathutils.Vector([(lo[k] + hi[k]) / 2.0 for k in range(3)])
    rad = 0.5 * mathutils.Vector([hi[k] - lo[k] for k in range(3)]).length
    return lo, hi, ctr, max(rad, 0.5)


def _fit_dist(rad, focal, width, height):
    """Far enough back that a sphere of `rad` is inside the frame on BOTH axes.
    The opening bid for _fit_bbox, and the fallback when there is no box."""
    half = min(INSPECT_SENSOR, INSPECT_SENSOR * float(height) / max(1.0, float(width))) / 2.0
    fov = math.atan(half / max(1.0, float(focal)))
    return rad / max(0.08, math.sin(fov)) * 1.06


_CLOUD = []


def _cloud(cap=6000):
    """A sample of the asset's real vertices, in world space.

    The cameras frame THESE, not the bounding box. A ship's box is 49 x 19 x 38
    m but its corner — abreast of the stern, out at the yard-arms, up at the
    truck — has no geometry anywhere near it, so framing the box leaves the
    subject at 60 % of the frame in every end-on view."""
    if _CLOUD:
        return _CLOUD
    dg = bpy.context.evaluated_depsgraph_get()
    pts, total = [], 0
    for ob in asset_meshes():
        try:
            ev = ob.evaluated_get(dg)
            me = ev.to_mesh()
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('object mesh skipped in the vertex count, not evaluable: %s', _exc)
            continue
        total += len(me.vertices)
        ev.to_mesh_clear()
    step = max(1, total // max(1, cap))
    k = 0
    for ob in asset_meshes():
        try:
            ev = ob.evaluated_get(dg)
            me = ev.to_mesh()
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('object mesh skipped in the point sample, not evaluable: %s', _exc)
            continue
        mw = ev.matrix_world
        for v in me.vertices:
            if k % step == 0:
                pts.append(mw @ v.co)
            k += 1
        ev.to_mesh_clear()
    _CLOUD[:] = pts
    return _CLOUD


def _fit_bbox(lo, hi, ctr, ndir, focal, width, height, margin=0.045):
    """The distance along `ndir` at which the whole BOX is just inside the
    frame. Framing the bounding SPHERE instead — the obvious version — leaves a
    long thin subject like a ship filling a third of the picture, because a
    51 x 19 x 38 m box has a 33 m radius and almost none of it is ship."""
    w, h = float(width), float(height)
    tan_u = (INSPECT_SENSOR / 2.0) / float(focal)
    tan_v = tan_u * (h / w) if w >= h else tan_u
    if w < h:  # portrait: the
        tan_u = tan_v * (w / h)  # sensor fits the
        tan_v = (INSPECT_SENSOR / 2.0) / float(focal)  # taller side
    n = mathutils.Vector(ndir).normalized()
    corners = _cloud() or [
        mathutils.Vector((hi[0] if i & 1 else lo[0], hi[1] if i & 2 else lo[1], hi[2] if i & 4 else lo[2]))
        for i in range(8)
    ]
    rad = 0.5 * mathutils.Vector([hi[k] - lo[k] for k in range(3)]).length

    def over(dist):
        loc = mathutils.Vector(ctr) + n * dist
        q = (mathutils.Vector(loc) - mathutils.Vector(ctr)).to_track_quat('Z', 'Y')
        right = q @ mathutils.Vector((1.0, 0.0, 0.0))
        up = q @ mathutils.Vector((0.0, 1.0, 0.0))
        fwd = q @ mathutils.Vector((0.0, 0.0, -1.0))
        worst = -1.0
        for c in corners:
            v = c - loc
            d = v.dot(fwd)
            if d <= 0.05:
                return 9.9e9
            worst = max(worst, abs(v.dot(right)) / d / tan_u - 1.0, abs(v.dot(up)) / d / tan_v - 1.0)
        return worst

    lo_d, hi_d = rad * 0.6, _fit_dist(rad, focal, width, height) * 1.25
    if over(hi_d) > 0.0:
        hi_d *= 3.0
    for _ in range(46):
        md = (lo_d + hi_d) / 2.0
        if over(md) > 0.0:
            lo_d = md
        else:
            hi_d = md
    return hi_d * (1.0 + margin)


def _cam_persp(loc, target, focal, clip_start=0.05, far=1.0e4):
    cd = bpy.data.cameras.new('inspcam')
    cd.type = 'PERSP'
    cd.lens = float(focal)
    cd.sensor_fit = 'AUTO'
    cd.sensor_width = INSPECT_SENSOR
    cd.clip_start = float(clip_start)
    cd.clip_end = float(far)
    cam = bpy.data.objects.new('inspcam', cd)
    cam['zyg_ref'] = 1
    bpy.context.scene.collection.objects.link(cam)
    cam.location = mathutils.Vector(loc)
    d = mathutils.Vector(loc) - mathutils.Vector(target)
    cam.rotation_euler = d.to_track_quat('Z', 'Y').to_euler()
    bpy.context.scene.camera = cam
    return cam


def _cam_ortho(loc, look, span, clip_start=0.01, far=1.0e4):
    """An ortho camera standing ON a plane and looking through it: with the near
    clip at 1 cm everything on the camera's side of the plane is simply not
    there, which is what makes this a SECTION and not an elevation."""
    cd = bpy.data.cameras.new('inspcam')
    cd.type = 'ORTHO'
    cd.ortho_scale = float(span)
    cd.clip_start = float(clip_start)
    cd.clip_end = float(far)
    cam = bpy.data.objects.new('inspcam', cd)
    cam['zyg_ref'] = 1
    bpy.context.scene.collection.objects.link(cam)
    cam.location = mathutils.Vector(loc)
    d = -mathutils.Vector(look).normalized()
    if abs(d.z) > 0.999:
        cam.rotation_euler = (0.0, 0.0, 0.0) if d.z > 0 else (math.pi, 0.0, 0.0)
    else:
        cam.rotation_euler = d.to_track_quat('Z', 'Y').to_euler()
    bpy.context.scene.camera = cam
    return cam


def _figure(loc, name='scale_figure'):
    """A 1.75 m person, in red, so a picture carries its own scale. Without one
    a bulwark is chest-high or shoulder-high depending on what you already
    believe, and a castle is either one storey or two."""
    mt = bpy.data.materials.get('zyg_scale_figure')
    if mt is None:
        mt = bpy.data.materials.new('zyg_scale_figure')
        mt.use_nodes = True
        try:
            b = mt.node_tree.nodes['Principled BSDF']
            b.inputs['Base Color'].default_value = (0.85, 0.09, 0.09, 1.0)
            b.inputs['Roughness'].default_value = 0.7
        except (KeyError, TypeError) as _exc:
            _zyg_log.debug('debug material colour not settable: %s', _exc)
        mt.diffuse_color = (0.85, 0.09, 0.09, 1.0)
    made = []
    parts = ((0.34, 0.20, 0.88, 0.44), (0.42, 0.26, 0.58, 1.17), (0.21, 0.21, 0.24, 1.58))
    for n, (sx, sy, sz, cz) in enumerate(parts):
        me = bpy.data.meshes.new(f'{name}{n}')
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=mathutils.Vector((sx, sy, sz)), verts=bm.verts)
        bmesh.ops.translate(bm, vec=mathutils.Vector((loc[0], loc[1], loc[2] + cz)), verts=bm.verts)
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new(f'{name}{n}', me)
        ob['zyg_ref'] = 1
        ob.data.materials.append(mt)
        bpy.context.scene.collection.objects.link(ob)
        made.append(ob)
    return made


def cam_and(loc, tgt):
    return _cam_persp(loc, tgt, INSPECT_FOCAL_IN, clip_start=0.04)


def _frame(view, width, height):
    """The frame shape this view wants: portrait for the tall ones."""
    w, h = int(width), int(height)
    if view in PORTRAIT_VIEWS and w > h:
        return (max(320, int(round(h * 0.80))), h)
    return (w, h)


def _body_bounds():
    """The bounds of the asset's BIGGEST single mesh — the hull of a ship, the
    shell of a building. The cut views frame on this rather than on the whole
    asset, because a 9.5 m hull inside a 19 m spread of yards is framed at half
    size by the bounding box and the section is the one view you need to read
    dimensions off."""
    best, bb = None, None
    for ob in asset_meshes():
        b = _bounds([ob])
        if b is None:
            continue
        lo, hi = b
        v = (hi[0] - lo[0]) * (hi[1] - lo[1]) * (hi[2] - lo[2])
        if best is None or v > best:
            best, bb = v, b
    return bb


def _inspect_shots(views, width, height):
    """[(title, make_camera() -> (cam, note), (w, h))], one per named view. The
    cameras are built lazily because the inside ones have to ray cast against a
    scene that is only final once the script has run."""
    sph = _sphere(asset_objects())
    if sph is None:
        return []
    lo, hi, ctr, rad = sph
    L = hi[0] - lo[0]
    W = hi[1] - lo[1]
    H = hi[2] - lo[2]
    cx, cy, cz = ctr[0], ctr[1], ctr[2]
    # the four outside standpoints, in the frame the builder promises: +X is the
    # length (a ship's bow), +Y is one beam, +Z is up.
    EXT = {
        'bow_quarter': ((0.80, 0.62, 0.30), 'three quarters from the bow'),
        'beam': ((0.00, 1.00, 0.10), 'square on the beam'),
        'bow': ((1.00, 0.06, 0.14), 'end on, from the bow'),
        'stern': ((-1.00, 0.06, 0.16), 'end on, from the stern'),
        'stern_quarter': ((-0.80, -0.60, 0.26), 'three quarters from the stern'),
        'aerial': ((0.45, -0.45, 0.95), 'from above, off the quarter'),
    }
    shots = []
    for v in views:
        if v in EXT:
            d, why = EXT[v]

            def mk(d=d, why=why, v=v):
                fw, fh = _frame(v, width, height)
                n = mathutils.Vector(d).normalized()
                dd = _fit_bbox(lo, hi, ctr, n, INSPECT_FOCAL, fw, fh)
                loc = ctr + n * dd
                cam = _cam_persp(loc, ctr, INSPECT_FOCAL, clip_start=max(0.05, dd * 0.002))
                return cam, (
                    f'{why}; {INSPECT_FOCAL:.0f} mm, {dd:.0f} m out, '
                    f'the whole {L:.1f} x {W:.1f} x {H:.1f} m envelope in frame'
                )

            shots.append((v, mk, _frame(v, width, height)))
        elif v == 'plan':

            def mk():
                cam = _cam_ortho((cx, cy, hi[2] + rad * 2.0 + 5.0), (0, 0, -1), _ortho_span(L, W))
                return cam, 'orthographic plan, looking straight down'

            shots.append((v, mk, _frame(v, width, height)))
        elif v == 'underside':

            def mk():
                cam = _cam_ortho((cx, cy, lo[2] - rad * 2.0 - 5.0), (0, 0, 1), _ortho_span(L, W))
                return cam, 'orthographic, looking straight UP at the underside'

            shots.append((v, mk, _frame(v, width, height)))
        elif v == 'section_long':

            def mk():
                b = _body_bounds() or (lo, hi)
                bx = (b[0][0] + b[1][0]) / 2.0
                bz = (b[0][2] + b[1][2]) / 2.0
                cam = _cam_ortho((bx, 0.0, bz), (0, 1, 0), _ortho_span(b[1][0] - b[0][0], b[1][2] - b[0][2], 1.10))
                return cam, (
                    'CUT on the centreline y = 0, looking at the far half: every deck, '
                    'every beam and every mast step shows where it really sits'
                )

            shots.append((v, mk, _frame(v, width, height)))
        elif v == 'section_mid':

            def mk():
                b = _body_bounds() or (lo, hi)
                bx = (b[0][0] + b[1][0]) / 2.0
                bz = (b[0][2] + b[1][2]) / 2.0
                cam = _cam_ortho((bx, 0.0, bz), (1, 0, 0), _ortho_span(b[1][1] - b[0][1], b[1][2] - b[0][2], 1.18))
                return cam, (
                    'CUT athwartships at mid length, looking forward: the section of the '
                    'hull, the deck heights and the headroom between them'
                )

            shots.append((v, mk, _frame(v, width, height)))
        elif v in ('inside_fwd', 'inside_aft', 'inside_below'):

            def mk(v=v):
                back = v == 'inside_aft'
                below = v == 'inside_below'
                pts = _standpoints(lo, hi, head_m=(HOLD_M if below else HEAD_M))
                if not pts:
                    cam = _cam_persp((cx, 0.0, cz), (hi[0], 0.0, cz), INSPECT_FOCAL_IN, clip_start=0.04)
                    return (
                        cam,
                        (
                            'NOTHING TO STAND ON anywhere along the centreline — there is no '
                            'deck, floor or ground in this asset. The camera is at the middle '
                            'of the bounding box, in mid-air.'
                        ),
                        [],
                    )
                # WHERE to stand is chosen by what can be SEEN from there: every
                # standpoint is scored by the clear run along the look direction
                # and the longest wins. Standing at a fixed fraction of the
                # length instead put the camera 3.5 m from a bulkhead, and a
                # picture of a bulkhead says nothing about the ship.
                tx = hi[0] if not back else lo[0]
                # the two weather-deck cameras must stand on the DECK, and the
                # clearest run in the ship is the empty hold: without this the
                # scoring sent all three cameras below. The median top surface
                # is the deck; anything much under it is a hold or a bilge.
                zs = sorted(p[1] for p in pts)
                z_med = zs[len(zs) // 2]
                best = None
                for x0, z0, head, deeper in pts:
                    if not below and z0 < z_med - 1.6:
                        continue
                    if below:
                        # the LOWEST level with standing room, not the next one
                        # down: one deck under the forecastle is still the deck
                        # the other two cameras are already standing on
                        low = [(z, h) for (z, h) in deeper if h >= HOLD_M]
                        if not low:
                            continue
                        z0, head = low[-1]
                    elif (x0 - cx) * (1.0 if not back else -1.0) > 0.12 * L:
                        continue  # stand behind what you look at
                    eye = z0 + (EYE_M if not below else min(EYE_M, max(0.85, head - 0.25)))
                    ca = _clear_ahead((x0, 0.0, eye), (tx, 0.0, z0 + 0.6))
                    if best is None or ca > best[0] + 0.05:
                        best = (ca, x0, z0, head, eye)
                if best is None:
                    return (
                        None,
                        (
                            'there is no second level under the top one anywhere along the '
                            'centreline — the hull has no inside to photograph'
                        ),
                        [],
                    )
                ca, x0, z0, head, eye = best
                loc = (x0, 0.0, eye)
                tgt = (tx, 0.0, z0 + 0.60)
                note = f'standing on the surface at {z0:.2f} m, headroom ' + (
                    'open sky' if head > 900 else f'{head:.2f} m'
                )
                if ca < CLEAR_M:
                    note += f'; only {ca:.1f} m ahead — the BEST standpoint still looks into something'
                # the figure goes where it can be SEEN: down the view, and off
                # the centreline, where a mast cannot stand in front of it
                fd = min(max(ca * 0.55, 3.0), 0.30 * L)
                fx = x0 + (fd if tx > x0 else -fd)
                fy = 1.25 if W > 4.0 else 0.0
                fl = _floors(fx, fy, z0 + 2.2, z0 - 2.2, head_m=0.9, r=min(2.0, max(0.55, 0.06 * max(L, W))))
                fz = fl[0][0] if fl else z0
                fig = _figure((fx, fy, fz))
                where = 'looking forward' if tx > x0 else 'looking aft'
                return (
                    cam_and(loc, tgt),
                    (
                        f'INSIDE at x {x0:.1f} m, eye {eye:.2f} m, {where} over '
                        f'{abs(tx - x0):.1f} m; {note}; clear ahead {ca:.1f} m; '
                        f'the red figure is {FIG_H:.2f} m tall and stands '
                        f'{fd:.1f} m away'
                    ),
                    fig,
                )

            shots.append((v, mk, _frame(v, width, height)))
    return shots


def _inspect(views, base, width, height, engine):
    """Render the inspection set. Returns [{path, title, note, inspect}]."""
    shots = _inspect_shots(views, width, height)
    if not shots:
        log('inspect: nothing to photograph')
        return []
    return _shoot_set(shots, base, 'view', engine, 'inspect')


def _shoot_set(shots, base, tag, engine, flag, photo=False):
    """Render one camera plan. Returns [{path, title, note, <flag>: True}].

    Shared by the ten-picture inspection set and the forty-odd picture
    portfolio: same lighting, same lazy cameras, same rule that a view which
    could not be taken still reports WHY."""
    out = []

    def _look(sc):
        if engine == 'eevee':
            _sun(sc, mathutils.Vector((1.0, -1.0, 0.8)).normalized())
            _world(sc)
            if photo:
                # A PORTFOLIO FRAME IS A PHOTOGRAPH, not a document. _setup
                # pins the view transform to Standard because a PLAN under
                # Filmic renders its white paper mid-grey — but the same
                # setting under a dark sky renders a tarred hull as black, and
                # a material you cannot see is a material you cannot judge. So
                # the portfolio gets a filmic transform and a sky that fills
                # the shadows; the check overlays keep Standard.
                _photo_look(sc)
        else:
            sh = sc.display.shading
            sh.show_xray = False
            sh.light = 'STUDIO'  # lights FROM the camera, so an
            sh.color_type = 'MATERIAL'  # interior is never a black box
            sh.show_cavity = True
            sh.show_object_outline = True

    for n, (title, mk, (fw, fh)) in enumerate(shots):
        _look(_setup(fw, fh, engine))
        cam, note, figs = None, '', []
        try:
            got = mk()
            cam, note = got[0], got[1]
            figs = got[2] if len(got) > 2 else []
            if cam is None:
                # no camera, but the REASON is the finding: "there is no deck
                # below the top one" is worth more than a missing picture
                out.append({'path': '', 'title': title, 'note': note, flag: True})
                log(f'{flag} {title}: NO PICTURE — {note}')
                continue
            png = f'{base}-{tag}-{n:02d}-{title}.png'
            if _shoot(png):
                out.append({'path': png, 'title': title, 'note': note, flag: True})
                log(f'{flag} {title}: {note}')
        except Exception as e:  # noqa: BLE001
            log(f'{flag} {title} FAILED: {type(e).__name__}: {e}')
        finally:
            for ob in ([cam] if cam is not None else []) + list(figs):
                try:
                    bpy.data.objects.remove(ob, do_unlink=True)
                except (ReferenceError, RuntimeError) as _exc:
                    _zyg_log.debug('temporary object removal skipped: %s', _exc)
    return out
