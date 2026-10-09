# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""blender_power.present — see the package docstring."""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.blender_power.constants import (
    APPROACH_FOCAL_MM,
    APPROACH_M,
    BLANK_VIEW_N,
    Drawing,
    EYE_HEIGHT_M,
    FOCAL_DEFAULT_MM,
    HERO_DIST_K,
    HERO_DIST_MAX_K,
    HERO_FOCAL_MM,
    HERO_H,
    HERO_HEADROOM,
    HERO_OFF_AXIS_DEG,
    HERO_SUN_MIN,
    HERO_W,
    LOBBY_AIM_H_M,
    LOBBY_EYE_M,
    LOBBY_FOCAL_MM,
    LOBBY_INSIDE_M,
    LOBBY_LOOK_M,
    LOBBY_MIN_INSIDE_M,
    MODEL_VIEWS,
    PRESENT_CHECKLIST,
    PRESENT_VIEWS,
    SENSOR_MM,
    SHIFT_MAX,
    SUN_AZIM_DEG,
    SUN_ELEV_DEG,
    TOOL_ENGINES,
    _num,
    _zyg_log,
    hashlib,
    json,
    math,
    os,
    time,
)
from zyg_workflows.arch_assistant_ext.blender_power.build import (
    _blender_ok,
    _build,
)
from zyg_workflows.arch_assistant_ext.blender_power.second_pass import (
    Reply,
    _data_url,
    _second_pass,
    _sun_hour,
    _thumb_jpeg,
)
from zyg_workflows.arch_assistant_ext.blender_power.tools import (
    _door_axis,
    _entrance_door,
    _envelope,
    _ext,
    _section_cam,
)


# ── present: the verification that is not the author ─────────────────────────
def present_sig(d: Drawing) -> str:
    """A fingerprint of WHAT WAS DRAWN — id, kind, position to the centimetre and
    parameters, for every record. `done` compares it with the signature stored by
    the last present(): if they differ, the drawing changed after it was shown
    and the pictures the model judged are not of the thing being handed over.

    THE NAME IS A CONTRACT: the done gate calls
    A.EXT_MODULES['blender_power'].present_sig(d)."""
    rows = sorted(
        (
            str(o.get('id') or ''),
            str(o.get('kind') or ''),
            round(float(o.get('x') or 0.0), 2),
            round(float(o.get('y') or 0.0), 2),
            round(float(o.get('z') or 0.0), 2),
            json.dumps(o.get('p') or {}, sort_keys=True),
        )
        for o in d.objs
    )
    return hashlib.sha1(json.dumps(rows).encode('utf-8'), usedforsecurity=False).hexdigest()


def _persp_cam(loc, target, focal) -> dict:
    """A perspective cam_spec (Blender frame) aimed LEVEL at the target's plan
    position, the target lifted into frame by shift_y and only the remainder
    tilted — the same lens maths _frame_camera does for a cell camera."""
    dist = math.hypot(float(target[0]) - float(loc[0]), float(target[1]) - float(loc[1]))
    rise = float(target[2]) - float(loc[2])
    want = float(focal) * rise / max(dist, 0.05) / SENSOR_MM
    shift = max(-SHIFT_MAX, min(SHIFT_MAX, want))
    tilt = 0.0
    if abs(want) > SHIFT_MAX:
        tilt = math.atan2(rise, max(dist, 0.05)) - math.copysign(math.atan(SHIFT_MAX * SENSOR_MM / float(focal)), want)
    return {
        'loc': tuple(round(float(c), 4) for c in loc),
        'target': tuple(round(float(c), 4) for c in target),
        'focal': float(focal),
        'sensor': SENSOR_MM,
        'shift_y': round(shift, 4),
        'tilt': round(tilt, 5),
    }


def _framed(out) -> dict:
    """The BP_FRAMED line: how many records the camera actually saw."""
    for line in reversed(str(out).splitlines()):
        if line.startswith('BP_FRAMED '):
            try:
                return json.loads(line[10:])
            except ValueError:
                return {}
    return {}


def _void_count(d: Drawing):
    """slab_voids' verdict as a number, or None when that family is not loaded."""
    SV = _ext('slab_voids')
    fn = getattr(SV, 'check_voids', None) if SV is not None else None
    if not callable(fn):
        return None
    try:
        got = fn(d)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(got, (list, tuple, set)):
        return len(got)
    if isinstance(got, dict):
        return int(_num(got.get('n', got.get('count')), 0) or 0)
    n = _num(got, None)
    return int(n) if n is not None else None


def _present_shots(d: Drawing, group: str) -> tuple:
    """[(title, view, cam_spec|None, probe|None)] and the entrance door (or None).
    Blender frame: x = studio x, y = -studio z, z = studio y (up)."""
    door = _entrance_door(d)
    env = _envelope(d, group)
    ycent = (env['y0'] + env['y1']) / 2.0
    shots = []
    door_pt = None
    if door is not None:
        x0, z0, nx, nz = _door_axis(d, door)
        floor = float(door.get('y') or 0.0)
        dh = _num((door.get('p') or {}).get('h'), 2.1) or 2.1
        door_pt = (x0, -z0, floor + dh / 2.0)
        out = (x0 + nx * APPROACH_M, z0 + nz * APPROACH_M)
        shots.append(
            (
                'approach',
                'approach',
                _persp_cam((out[0], -out[1], floor + EYE_HEIGHT_M), door_pt, APPROACH_FOCAL_MM),
                door_pt,
            )
        )
        shots.append(('section', 'section', _section_cam(d, 'x', x0, group), door_pt))
        inside = (x0 - nx * LOBBY_INSIDE_M, z0 - nz * LOBBY_INSIDE_M)
        # 2026-09-16: the camera looks INTO the lobby (it used to aim back out
        # at the door from 4 m in, and _bp_unblock then turned it 135 deg into a
        # blank corner — job 5e7eb915e1f9's 4K lobby frame)
        look = (x0 - nx * (LOBBY_INSIDE_M + LOBBY_LOOK_M), z0 - nz * (LOBBY_INSIDE_M + LOBBY_LOOK_M))
        lobby = _persp_cam(
            (inside[0], -inside[1], floor + LOBBY_EYE_M), (look[0], -look[1], floor + LOBBY_AIM_H_M), LOBBY_FOCAL_MM
        )
        # the retreat: OUT along the door normal (Blender frame), as far as the
        # door plane less LOBBY_MIN_INSIDE_M — see _bp_unblock
        lobby['kind'] = 'lobby'
        lobby['retreat'] = (round(nx, 4), round(-nz, 4), 0.0)
        lobby['retreat_max'] = round(max(0.0, LOBBY_INSIDE_M - LOBBY_MIN_INSIDE_M), 3)
    else:
        # no door: the approach becomes the 'eye' walk and the lobby an interior
        # camera at the plan centre looking north — five views either way.
        shots.append(('approach', 'eye', None, None))
        shots.append(('section', 'section', _section_cam(d, 'x', (env['x0'] + env['x1']) / 2.0, group), None))
        xc = (env['x0'] + env['x1']) / 2.0
        lobby = _persp_cam(
            (xc, -(env['z1']), env['y0'] + LOBBY_EYE_M), (xc, -(env['z0']), env['y0'] + LOBBY_AIM_H_M), LOBBY_FOCAL_MM
        )
        lobby['kind'] = 'lobby'
        lobby['retreat'] = (0.0, -1.0, 0.0)  # backwards, out of the plan
        lobby['retreat_max'] = round(max(0.0, LOBBY_INSIDE_M - LOBBY_MIN_INSIDE_M), 3)
    shots.append(('elevation', 'front', None, door_pt))
    shots.append(('aerial', 'aerial', None, door_pt))
    shots.append(('lobby', 'lobby', lobby, door_pt))
    order = {t: i for i, t in enumerate(PRESENT_VIEWS)}
    shots.sort(key=lambda s: order[s[0]])
    return shots, door, env, ycent


# ── the hero camera: the one picture that shows the WHOLE building ───────────
# present()'s five views are working drawings — the approach stands 30 m out on
# the door axis and on a 20-storey tower that is two storeys of entrance. The
# hand-over preview has to be the building itself: a person standing on the
# ground, 35 deg off the door axis so two facades read as volume, far enough
# back that the parapet and the head house are still inside the frame.
def _sun_xz(sun_hour):
    """The horizontal direction FROM the scene TOWARD the sun, in STUDIO (x, z).
    The same arithmetic _bp_sun_dir does inside Blender (x east, y north, z up),
    mapped back to the studio frame by y = -z."""
    if sun_hour is None:
        el, az = math.radians(SUN_ELEV_DEG), math.radians(SUN_AZIM_DEG)
    else:
        h = float(sun_hour) % 24.0
        el = math.radians(max(6.0, 62.0 * math.sin(math.pi * (h - 6.0) / 12.0)))
        az = math.radians((180.0 + (h - 12.0) * 15.0) % 360.0)
    return math.sin(az) * math.cos(el), -(math.cos(az) * math.cos(el))


def _hero_free(d, env, cx, cz, ux, uz):
    """Metres of clear ground on the (ux, uz) side: the distance from the plan
    centre to the nearest solid OUTSIDE the envelope, inside a 90 deg wedge
    around that direction. 1e6 when that side is empty."""
    OS = _ext('object_specs')
    skip = set(getattr(OS, 'SOLID_SKIP', None) or ()) | {'ground', 'terrain', 'zone', 'annotation'}
    best = 1e6
    for o in d.objs:
        if o.get('hidden') or o.get('kind') in skip:
            continue
        x, z = float(o.get('x') or 0.0), float(o.get('z') or 0.0)
        if env['x0'] - 1.0 <= x <= env['x1'] + 1.0 and env['z0'] - 1.0 <= z <= env['z1'] + 1.0:
            continue  # part of the building, not the site
        vx, vz = x - cx, z - cz
        r = math.hypot(vx, vz)
        if r > 1e-6 and (vx * ux + vz * uz) / r > 0.707:
            best = min(best, r)
    return best


def _hero_points(d: Drawing, env) -> list:
    """The corners of every solid record, Blender frame, rounded to the half
    metre and deduplicated — what the frame actually has to hold.

    NOT the envelope's eight corners: the envelope is a BOUNDING BOX, and on the
    live tower the pool deck and the canopy make it 46 m deep where the building
    is 20. Fitting to the box placed a phantom corner 26 m nearer the camera than
    anything real, pushed the standoff from 101 m to 121 m, and the rendered
    tower came out 22 % down the frame where the box said 8 % (measured with PIL
    on test-hero-4k-hero-hero.png, 2026-09-16)."""
    E = _ext('envelope_rules')
    bbox = getattr(E, 'bbox_of', None) if E is not None else None
    OS = _ext('object_specs')
    skip = set(getattr(OS, 'SOLID_SKIP', None) or ()) | {'ground', 'terrain'}
    seen = set()
    for o in d.objs:
        if o.get('hidden') or o.get('kind') in skip or not callable(bbox):
            continue
        try:
            x0, z0, x1, z1 = bbox(o)
        except Exception as _exc:  # noqa: BLE001 — a record with no plan size
            _zyg_log.debug('plan bbox unavailable for kind %s: %s', o.get('kind'), _exc)
            continue
        p = o.get('p') or {}
        y = float(o.get('y') or 0.0)
        t = abs(_num(p.get('h'), 0.0) or 0.0) or abs(_num(p.get('t'), 0.0) or 0.0)
        for x in (x0, x1):
            for z in (z0, z1):
                for yy in (y, y + t):
                    seen.add((round(float(x) * 2) / 2.0, round(float(-z) * 2) / 2.0, round(float(yy) * 2) / 2.0))
    if seen:
        return sorted(seen)
    y0, y1 = float(env.get('y0') or 0.0), float(env['y1'])
    return [(x, -z, y) for x in (env['x0'], env['x1']) for z in (env['z0'], env['z1']) for y in (y0, y1)]


def _hero_ndc(cam, pts, aspect):
    """`pts` (Blender frame) in normalised device coordinates — [-1, 1] across
    the frame both ways — through the exact lens the render will use: sensor_fit
    HORIZONTAL, so shift_y is in SENSOR-WIDTH units and moves the image by
    2 * shift_y * aspect in v, and `tilt` is a pitch about the camera's right
    axis. None when any point is behind the camera."""
    lx, ly, lz = (float(c) for c in cam['loc'])
    tx, ty = float(cam['target'][0]), float(cam['target'][1])
    fx, fy = tx - lx, ty - ly
    n = math.hypot(fx, fy) or 1.0
    fx, fy = fx / n, fy / n
    rx, ry = fy, -fx
    f = float(cam.get('focal') or FOCAL_DEFAULT_MM)
    half = float(cam.get('sensor') or SENSOR_MM) / 2.0
    ct, st = math.cos(float(cam.get('tilt') or 0.0)), math.sin(float(cam.get('tilt') or 0.0))
    sy = 2.0 * float(cam.get('shift_y') or 0.0) * float(aspect)
    out = []
    for px, py, pz in pts:
        dx, dy, dz = px - lx, py - ly, pz - lz
        depth, lat = dx * fx + dy * fy, dx * rx + dy * ry
        d2, z2 = depth * ct + dz * st, -depth * st + dz * ct
        if d2 < 0.05:
            return None
        out.append(((f * lat / d2) / half, (f * z2 / d2) / (half / float(aspect)) - sy))
    return out


def _hero_cam(d: Drawing, env, door, sun_hour=None, aspect=None) -> dict:
    """The hand-over camera, or None when the drawing has no entrance door.

    Three-quarter from the entrance side, eye height 1.7 m (a person on the
    ground, never a drone), 24 mm.

    HERO_DIST_K x max(height, plan diagonal) is the MINIMUM standoff, grown
    until every solid fits with HERO_HEADROOM of air. It HAS to be grown on
    anything tall: the live tower is 57 m over a 20 m square, so 1.35 x 57 =
    77 m puts the near corner ~63 m out, where 57 m of building wants 2.14 of
    the frame's 2.0 — no shift_y can save that. 82.8 m is the first distance
    that fits. Measured there (live_tower_20260911, 3840x2160): shift_y 0.217,
    no tilt, parapet 8.0 % below the top edge, ground line 92.0 % down, the
    tower 84.0 % of the frame height — and PIL reads 8.0 % off the render."""
    if door is None:
        return None
    ar = float(aspect or (HERO_W / float(HERO_H)))
    _dx, _dz, nx, nz = _door_axis(d, door)
    cx, cz = (env['x0'] + env['x1']) / 2.0, (env['z0'] + env['z1']) / 2.0
    y0, y1 = float(env.get('y0') or 0.0), float(env['y1'])
    height = max(1.0, y1 - y0)
    diag = math.hypot(env['x1'] - env['x0'], env['z1'] - env['z0'])
    eye = float(door.get('y') or y0) + EYE_HEIGHT_M
    need = max(2.0, HERO_DIST_K * max(height, diag))

    def _dir(s):
        a = math.radians(HERO_OFF_AXIS_DEG * s)
        return nx * math.cos(a) - nz * math.sin(a), nx * math.sin(a) + nz * math.cos(a)

    # WHICH SIDE. The sun decides: of the two facades a three-quarter shot shows,
    # the entrance one is fixed, so turn toward whichever flank the sun is on and
    # both visible faces are lit. When the sun is square on the door axis it
    # cannot choose, and when its side is built up we take the open one instead.
    sx, sz = _sun_xz(sun_hour)
    turn = nx * sz - nz * sx  # > 0: the +90 deg flank faces the sun
    side, why = (1.0 if turn >= 0 else -1.0), 'sun'
    free = {s: _hero_free(d, env, cx, cz, *_dir(s)) for s in (1.0, -1.0)}
    if abs(turn) < HERO_SUN_MIN or (free[side] < need <= free[-side]):
        side, why = (1.0 if free[1.0] >= free[-1.0] else -1.0), 'ground'
    ux, uz = _dir(side)

    pts = _hero_points(d, env)
    mid = (min(p[2] for p in pts) + max(p[2] for p in pts)) / 2.0
    tgt = (cx, -cz, mid)
    lim = 1.0 - 2.0 * HERO_HEADROOM

    def _spec(dist):
        loc = (cx + ux * dist, -(cz + uz * dist), eye)
        base = _persp_cam(loc, tgt, HERO_FOCAL_MM)
        got = _hero_ndc(base, pts, ar)
        if got is None:
            return base
        off = (max(v for _u, v in got) + min(v for _u, v in got)) / 2.0
        if abs(off) < 1e-4:
            return base
        # AIM, not crop: perspective puts the near parapet further above the
        # centre line than the near footing is below it, so the geometric
        # mid-height leaves the headroom lopsided (11.6 % over 4.0 % on the
        # tower_recipe fixture). Re-target the height that centres what the
        # frame actually holds — the same lens, one more lift of shift_y.
        rise = (float(base['shift_y']) + off / (2.0 * ar)) * dist * SENSOR_MM / HERO_FOCAL_MM
        return _persp_cam(loc, (cx, -cz, eye + rise), HERO_FOCAL_MM)

    def _over(dist):
        """How far outside the frame the worst envelope corner sits (<= 0 fits)."""
        got = _hero_ndc(_spec(dist), pts, ar)
        if got is None:
            return 9.9
        return max(max(abs(u), abs(v)) for u, v in got) - lim

    dist = need
    if _over(need) > 0.0:
        lo, dist = need, max(need, HERO_DIST_MAX_K * max(height, diag))
        for _ in range(40):
            md = (lo + dist) / 2.0
            if _over(md) > 0.0:
                lo = md
            else:
                dist = md
    cam = _spec(dist)
    cam['kind'] = 'hero'
    cam['side'] = why
    cam['lit'] = bool(nx * sx + nz * sz > 0)
    cam['dist'] = round(dist, 2)
    return cam


def _hero_shot(d: Drawing, env, door, sun_hour=None, aspect=None) -> tuple:
    """('hero', view, cam_spec|None, probe|None), the shot hero_render puts
    first. Without an entrance door there is no side to stand off, so it falls
    back to the 'eye' walk — the same fallback present()'s approach uses."""
    cam = _hero_cam(d, env, door, sun_hour, aspect)
    if cam is None:
        return ('hero', 'eye', None, None)
    return ('hero', 'hero', cam, tuple(cam['target']))


def t_present(d: Drawing, a, group='', engine='eevee', width=1280, height=720):
    bad = _blender_ok()
    if bad:
        return bad
    if not d.objs:
        return (
            'refused: the drawing is empty — there is nothing to present. Draw the building first '
            '(draw_box), then call present()'
        )
    e = str(engine or 'eevee').lower()
    if e not in TOOL_ENGINES:
        return 'refused: engine must be workbench or eevee'
    w = int(_num(width, 1280) or 1280)
    h = int(_num(height, 720) or 720)
    if not (160 <= w <= 3840 and 120 <= h <= 2160):
        return 'refused: width must be 160..3840 and height 120..2160 pixels'
    grp = str(group or '').strip()
    if grp and not any(o.get('grp') == grp for o in d.objs):
        return f'refused: no record is in group "{grp}" — pass the group name draw_box returned, or leave it out'
    try:
        shots, door, env, _yc = _present_shots(d, grp)
        blend, note = _build(d)
    except ValueError as ex:
        return f'refused: {ex}'

    voids = _void_count(d)
    lines, titles, files = [], [], []
    pngs: dict = {}
    blank = False
    for title, view, cam, probe in shots:
        try:
            rc, out, png = _second_pass(blend, render=(view, e, w, h, _sun_hour(d), cam, probe))
        except ValueError as ex:
            lines.append(f'{title}: NOT RENDERED — {ex}')
            continue
        url, nbytes = _data_url(png)
        if not url:
            lines.append(f'{title}: NOT RENDERED — Blender exit {rc}')
            continue
        d.images.append({'title': title, 'data_url': url})
        titles.append(title)
        files.append(os.path.basename(png))
        pngs[title] = png
        f = _framed(out)
        nfr = int(f.get('n_frustum') or f.get('n') or 0)
        nvis = int(f.get('n_visible') or 0)
        tall = (
            f'tallest in frame {f.get("tallest")} at {f.get("tallest_h"):.2f} m'
            if f.get('tallest') and f.get('tallest_h') is not None
            else 'nothing in frame'
        )
        row = f'{title}: {nvis} visible of {nfr} in frustum, {tall}'
        if title == 'approach':
            row += f', door in frame: {"yes" if f.get("probe_in") else "no"}'
        if title == 'lobby':
            # the one camera that stands INSIDE: say how much air is in front of it,
            # blank or not, so the operator can see the probe did its work
            ca = _num(f.get('clear_ahead'), None)
            row += f', clear ahead {float(ca):.1f} m' if ca is not None else ', clear ahead not measured'
        if title == 'section':
            row += (
                f'; stairs/shafts crossing slabs without an opening: {voids}'
                if voids is not None
                else '; stairs/shafts crossing slabs without an opening: not measured (slab_voids not loaded)'
            )
        row += f' [{os.path.basename(png)}, {nbytes // 1024} KB]'
        if nvis < BLANK_VIEW_N:
            ca = _num(f.get('clear_ahead'), None)
            blank = True
            row += ' — BLANK VIEW: the camera sees a wall (clear ahead ' + (
                f'{float(ca):.1f} m)' if ca is not None else 'not measured)'
            )
        lines.append(row)

    d.ext['presented'] = {
        'sig': present_sig(d),
        'views': titles,
        'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'engine': e,
        'files': files,
    }
    DR = _ext('design_rules')
    checks = ''
    if DR is not None:
        try:
            checks = DR.format_findings(DR.run_checks(d))
        except Exception as ex:  # noqa: BLE001
            checks = f'design check: could not run ({ex!r})'
    else:
        checks = 'design check: design_rules is not loaded'
    head = (
        f'presented {len(titles)} of {len(shots)} views of {len(d.objs)} records '
        f'({e}, {w}x{h}, {note})'
        + (
            f'; entrance {door["kind"]} {door["id"]}'
            if door is not None
            else '; NO ground-floor door was found, so the approach is the "eye" walk and the lobby the plan centre'
        )
        + f'; envelope {env["x1"] - env["x0"]:.1f} x {env["z1"] - env["z0"]:.1f} m, '
        f'{env["y1"] - env["y0"]:.1f} m tall.'
    )
    if blank:
        lines.append('a blank view is not a presentation: move the room or the camera')
    text = head + '\n' + '\n'.join(lines) + '\n' + checks
    # the pictures the model has to judge: approach, aerial, lobby
    images = [t for t in (_thumb_jpeg(pngs.get(v)) for v in MODEL_VIEWS) if t]
    if not images:
        return text
    return Reply({'text': text + '\n' + PRESENT_CHECKLIST, 'images': images})
