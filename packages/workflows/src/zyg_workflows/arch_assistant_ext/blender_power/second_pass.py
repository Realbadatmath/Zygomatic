# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""blender_power.second_pass — see the package docstring."""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.blender_power.constants import (
    BLENDER,
    BLEND_DIR,
    BP_CY_SAMPLES,
    HERE,
    PASS_TIMEOUT,
    THUMB_MAX_BYTES,
    THUMB_Q,
    THUMB_W,
    _env_int,
    _num,
    base64,
    os,
    subprocess,
    time,
)
from zyg_workflows.arch_assistant_ext.blender_power.frame_script import (
    _FRAME,
)

_FRAMED = r'''
def _bp_root(ob):
    """The top of an object's parent chain — a pack asset is one empty with a
    pile of imported meshes under it, and any of them is 'that object'."""
    top = ob
    for _ in range(8):
        if top.parent is None:
            break
        top = top.parent
    return top


def _bp_same(hit_ob, ob):
    """Is the ray's first hit THIS record (or one of its parts)? Records are
    built as f'{prefix}{kind} {id}' carrying obj['studio_id'], and a wall's
    boolean cutters and an asset's imported children share its root."""
    if hit_ob is None:
        return False
    if hit_ob == ob:
        return True
    a, b = ob.get('studio_id'), hit_ob.get('studio_id')
    if a and b and a == b:
        return True
    return _bp_root(hit_ob) == _bp_root(ob)


def _bp_key(ob):
    """One record, one key — a wall's boolean cutters and a pack asset's
    imported children all answer with the record they belong to."""
    if ob is None:
        return None
    rid = ob.get('studio_id')
    if rid:
        return str(rid)
    top = _bp_root(ob)
    rid = top.get('studio_id')
    return str(rid) if rid else top.name


def _bp_hit_keys(sc, dg, cam, nx=13, ny=9, reach=400.0):
    """The records the camera LITERALLY sees: a grid of rays fired through the
    picture, one per cell, keyed by whatever each ray hits first. This is the
    honest answer to 'what is in this frame'; the per-object test below can only
    aim at an origin and 4 bound-box corners, and a corner ray grazes past a
    partition the camera is staring straight at (measured on live job 94f5813b:
    a lobby full of walls scored 2)."""
    keys = set()
    if cam is None or cam.data is None:
        return keys
    try:
        corners = [cam.matrix_world @ c for c in cam.data.view_frame(scene=sc)]
    except Exception:
        return keys
    if len(corners) != 4:
        return keys
    tr, br, bl, tl = corners
    o = cam.matrix_world.translation.copy()
    for iy in range(ny):
        fy = (iy + 0.5) / float(ny)
        left, right = tl.lerp(bl, fy), tr.lerp(br, fy)
        for ix in range(nx):
            p = left.lerp(right, (ix + 0.5) / float(nx))
            v = (p - o)
            if v.length < 1e-6:
                continue
            v = v.normalized()
            try:
                hit = sc.ray_cast(dg, o + v * 0.01, v, distance=reach)
            except Exception as _exc:
                _zyg_log.debug('visibility ray cast skipped: %s', _exc)
                continue
            if hit[0] and len(hit) > 4 and hit[4] is not None and not hit[4].name.startswith('bp_'):
                keys.add(_bp_key(hit[4]))
    keys.discard(None)
    return keys


def _bp_in_frame(sc, cam, ob):
    """Does any part of `ob` land in the picture? The object's 8 bound-box
    corners are projected and their rectangle tested against the frame.
    Projecting the ORIGIN alone (what this did until 2026-09-11) is wrong
    indoors: every studio record's origin sits on the FLOOR, so a lobby camera
    at 1.6 m reported 1 record in frustum for a room full of partitions."""
    import mathutils
    from bpy_extras.object_utils import world_to_camera_view
    xs, ys = [], []
    for c in ob.bound_box:
        try:
            p = world_to_camera_view(sc, cam, ob.matrix_world @ mathutils.Vector(c))
        except Exception:
            return False
        if p.z > 0.0:
            xs.append(p.x)
            ys.append(p.y)
    if not xs:
        return False
    return max(xs) >= 0.0 and min(xs) <= 1.0 and max(ys) >= 0.0 and min(ys) <= 1.0


def _bp_sees(sc, dg, cam_loc, ob):
    """True when the camera can actually SEE `ob`: a ray to its origin or to one
    of 4 bound-box corners either reaches that point with nothing in the way, or
    hits the object itself first. Origin-in-frustum alone counted 14 records in
    a frame that was one grey partition (live job 94f5813b)."""
    import mathutils
    pts = [ob.matrix_world.translation]
    bb = ob.bound_box
    for i in (0, 2, 5, 7):
        pts.append(ob.matrix_world @ mathutils.Vector(bb[i]))
    for tgt in pts:
        d = mathutils.Vector(tgt) - cam_loc
        dist = d.length
        if dist < 0.05:
            return True
        v = d / dist
        try:
            hit = sc.ray_cast(dg, cam_loc + v * 0.02, v, distance=dist + 0.05)
        except Exception:
            return True
        if not hit[0] or _bp_same(hit[4] if len(hit) > 4 else None, ob):
            return True
    return False


def _bp_framed(probe=None):
    """What is ACTUALLY in the picture, in numbers — the answer to "the model
    judged its own render". Meshes whose origin projects inside the frustum are
    counted (n_frustum); those the camera can really see, by ray cast — a grid
    of rays through the picture plus a ray to the object's own origin and bound
    box — are counted again (n_visible) and only they can be the tallest.
    `probe` (a point
    in the Blender frame, e.g. the entrance door's centre) is tested for the
    frustum the same way, and `clear_ahead` is the free air in front of the
    camera — BP_PROBE_INFO's when present()'s lobby probe already measured it."""
    import bpy, mathutils, json as _json
    from bpy_extras.object_utils import world_to_camera_view
    sc = bpy.context.scene
    cam = sc.camera
    n = nvis = 0
    tall_name, tall_h = '', None
    if cam is not None:
        dg = bpy.context.evaluated_depsgraph_get()
        cam_loc = cam.matrix_world.translation.copy()
        seen_keys = _bp_hit_keys(sc, dg, cam)
        for ob in sc.objects:
            if ob.type != 'MESH' or ob.name.startswith('bp_'):
                continue
            if not _bp_in_frame(sc, cam, ob):
                continue
            n += 1
            if _bp_key(ob) not in seen_keys and not _bp_sees(sc, dg, cam_loc, ob):
                continue
            nvis += 1
            top = max((ob.matrix_world @ mathutils.Vector(c)).z for c in ob.bound_box)
            if tall_h is None or top > tall_h:
                tall_h, tall_name = top, ob.name
    pin = None
    if probe is not None and cam is not None:
        try:
            p = world_to_camera_view(sc, cam, mathutils.Vector(probe))
            pin = bool(0.0 <= p.x <= 1.0 and 0.0 <= p.y <= 1.0 and p.z > 0.0)
        except Exception:
            pin = None
    info = dict(BP_PROBE_INFO)
    if cam is not None and 'clear_ahead' not in info:
        info['clear_ahead'] = round(_bp_clear(sc, cam.matrix_world.translation, _bp_forward(cam)), 3)
    row = {'n': n, 'n_frustum': n, 'n_visible': nvis, 'tallest': tall_name,
           'tallest_h': (round(tall_h, 2) if tall_h is not None else None),
           'probe_in': pin,
           'cam_loc': ([round(c, 3) for c in cam.matrix_world.translation] if cam is not None else None)}
    row.update(info)
    print('BP_FRAMED ' + _json.dumps(row))
'''

_MEASURE = r"""
def _bp_measure():
    import bpy, bmesh
    rows = []
    total = 0.0
    faces = 0
    for ob in sorted(bpy.context.scene.objects, key=lambda o: o.name):
        if ob.type != 'MESH':
            continue
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        bm.transform(ob.matrix_world)
        try:
            vol = abs(bm.calc_volume(signed=True))
        except Exception:
            vol = 0.0
        nf = len(bm.faces)
        bm.free()
        dep = bpy.context.evaluated_depsgraph_get()
        ev = ob.evaluated_get(dep)
        xs = [(ob.matrix_world @ v.co) for v in ev.data.vertices] if ev.data.vertices else []
        if xs:
            w = max(p.x for p in xs) - min(p.x for p in xs)
            dd = max(p.y for p in xs) - min(p.y for p in xs)
            h = max(p.z for p in xs) - min(p.z for p in xs)
        else:
            w = dd = h = 0.0
        total += vol
        faces += nf
        rows.append('%-26s %6.2f x %6.2f x %6.2f m  vol %8.3f m3  %5d faces  %s'
                    % (ob.name[:26], w, dd, h, vol, nf, ob.get('studio_id') or '-'))
    print('BP_MEASURE_BEGIN')
    print('object                       w      d      h        volume        faces  studio_id')
    for r in rows[:120]:
        print(r)
    if len(rows) > 120:
        print('... and %d more objects' % (len(rows) - 120))
    print('TOTAL %d meshes, %.3f m3, %d faces' % (len(rows), total, faces))
    print('BP_MEASURE_END')
"""

_EXPORT = r"""
def _bp_export(fmt, path):
    import bpy
    ops = {
        'obj': [lambda: bpy.ops.wm.obj_export(filepath=path)],
        'fbx': [lambda: bpy.ops.export_scene.fbx(filepath=path)],
        'stl': [lambda: bpy.ops.wm.stl_export(filepath=path),
                lambda: bpy.ops.export_mesh.stl(filepath=path)],
        'glb': [lambda: bpy.ops.export_scene.gltf(filepath=path, export_format='GLB', export_apply=True)],
        'usd': [lambda: bpy.ops.wm.usd_export(filepath=path)],
        'ply': [lambda: bpy.ops.wm.ply_export(filepath=path),
                lambda: bpy.ops.export_mesh.ply(filepath=path)],
    }[fmt]
    last = ''
    for fn in ops:
        try:
            fn()
            print('BP_EXPORT_OK ' + path)
            return
        except Exception as e:
            last = '%s: %s' % (type(e).__name__, e)
    print('BP_EXPORT_FAIL ' + last)
"""


def _sun_hour(d):
    """The studio's sun hour for this drawing, or None. No kind carries one
    today, so this is the hook a doc-level `sun_hour` lands on; without it the
    render uses the default 35 deg south-west sun."""
    h = _num(getattr(d, 'sun_hour', None), None)
    return h if h is not None and 0.0 <= float(h) <= 24.0 else None


def hero_samples():
    """The Cycles sample count, read from the environment at RENDER time — the
    module const is only the default the frame script is compiled with."""
    return _env_int('ZYG_ARCH_HERO_SAMPLES', BP_CY_SAMPLES, 1, 4096)


def _second_pass(blend, *, user_file='', save=False, render=None, measure=False, export=None, timeout=None):
    """Compose and run one headless Blender pass over `blend`. Returns (rc, stdout)."""
    png = ''
    parts = [
        'import bpy, bmesh, math, mathutils, os, sys, traceback',
        _FRAME,
        _FRAMED,
        _MEASURE,
        _EXPORT,
        'BLEND = ' + repr(blend),
    ]
    if user_file:
        parts.append(
            'USER = ' + repr(user_file) + '\n'
            "g = {'__name__': '__main__', 'bpy': bpy, 'bmesh': bmesh, 'math': math, 'mathutils': mathutils}\n"
            'try:\n'
            "    exec(compile(open(USER, 'r', encoding='utf-8').read(), USER, 'exec'), g)\n"
            "    print('BP_SCRIPT_OK')\n"
            'except Exception:\n'
            '    traceback.print_exc()\n'
            "    print('BP_SCRIPT_ERROR')"
        )
    if save:
        parts.append(
            'try:\n'
            '    bpy.ops.wm.save_as_mainfile(filepath=BLEND)\n'
            "    print('BP_SAVED ' + BLEND)\n"
            'except Exception as e:\n'
            "    print('BP_SAVE_ERROR %s: %s' % (type(e).__name__, e))"
        )
    if measure:
        parts.append('_bp_measure()')
    if export:
        parts.append(f'_bp_export({export[0]!r}, {export[1]!r})')
    if render:
        view, engine, w, h = render[:4]
        sun_hour = render[4] if len(render) > 4 else None
        cam = render[5] if len(render) > 5 else None  # 2026-09-08: the cell camera, or None
        probe = render[6] if len(render) > 6 else None  # 2026-09-10: a point present() asks about
        png = (
            render[7]
            if len(render) > 7 and render[7]
            else os.path.join(BLEND_DIR, f'view-{view}-{time.strftime("%Y%m%d-%H%M%S")}-{os.getpid()}.png')
        )
        if engine == 'cycles':
            parts.append(f'BP_CY_SAMPLES = {hero_samples()!r}')
        parts.append(
            f'_bp_frame({view!r}, {int(w)}, {int(h)}, {png!r}, {engine!r}, {sun_hour!r}, {cam!r})\n'
            f'_bp_framed({probe!r})\n'
            f"print('BP_PNG ' + {png!r})"
        )
    os.makedirs(BLEND_DIR, exist_ok=True)
    spath = os.path.join(BLEND_DIR, f'_pass-{time.strftime("%H%M%S")}-{os.getpid()}-{len(parts)}.py')
    with open(spath, 'w', encoding='utf-8') as fh:
        fh.write('\n\n'.join(parts) + '\n')
    tmo = int(timeout or PASS_TIMEOUT)
    try:
        p = subprocess.run(
            [BLENDER, '-b', blend, '--python', spath], capture_output=True, text=True, timeout=tmo, cwd=HERE
        )
    except subprocess.TimeoutExpired as _exc:
        raise ValueError(f'the Blender pass did not finish inside {tmo}s') from _exc
    out = (p.stdout or '') + (('\n[stderr] ' + p.stderr[-800:]) if p.returncode != 0 and p.stderr else '')
    return p.returncode, out, png


def _data_url(png):
    if not png or not os.path.exists(png):
        return '', 0
    raw = open(png, 'rb').read()
    return 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii'), len(raw)


class Reply(dict):
    """A tool reply that carries pictures for the model as well as text.

    It is a dict — shim_tool unwraps {'text', 'images'} and the MCP shim turns
    each picture into an image block — but it str()s to the text alone, so
    call_tool's callers (the in-process loop, the harness, every test) keep the
    string they have always had."""

    def __str__(self):
        return str(self.get('text') or '')


def _thumb_jpeg(png):
    """One render as a small JPEG [mime, b64], or None. <= THUMB_W px wide, and
    quality is stepped down until the bytes fit THUMB_MAX_BYTES."""
    if not png or not os.path.exists(png):
        return None
    try:
        import io

        from PIL import Image
    except Exception:  # noqa: BLE001
        return None
    try:
        with Image.open(png) as im:
            im = im.convert('RGB')
            if im.width > THUMB_W:
                im = im.resize((THUMB_W, max(1, round(im.height * THUMB_W / im.width))), Image.LANCZOS)
            for q in (THUMB_Q, 55, 40, 30):
                buf = io.BytesIO()
                im.save(buf, 'JPEG', quality=q, optimize=True)
                if buf.tell() <= THUMB_MAX_BYTES or q == 30:
                    return ['image/jpeg', base64.b64encode(buf.getvalue()).decode('ascii')]
    except Exception:  # noqa: BLE001
        return None
    return None


def _between(out, a, b):
    i, j = out.find(a), out.find(b)
    return out[i + len(a) : j].strip() if 0 <= i < j else ''


def _tail(out, n=2000):
    lines = [l for l in out.splitlines() if l.strip() and not l.startswith('Blender quit') and not l.startswith('Fra:')]
    return '\n'.join(lines)[-n:]
