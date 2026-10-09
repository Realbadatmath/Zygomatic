# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""blender_power.tools — see the package docstring."""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.blender_power.constants import (
    BLEND_DIR,
    BSTORE,
    Drawing,
    EYE_HEIGHT_M,
    FOCAL_DEFAULT_MM,
    FOCAL_RANGE_MM,
    LOOK_HEIGHT_M,
    SECTION_AXES,
    SENSOR_MM,
    SHIFT_MAX,
    TOOL_ENGINES,
    VIEWS,
    _num,
    _zyg_log,
    cell_centre,
    cell_of,
    deck_tops,
    ground_height,
    math,
    os,
    parse_cell,
    surface_top,
    time,
)
from zyg_workflows.arch_assistant_ext.blender_power.build import (
    _blender_ok,
    _build,
)
from zyg_workflows.arch_assistant_ext.blender_power.second_pass import (
    _data_url,
    _second_pass,
    _sun_hour,
    _tail,
)


# ── tools ────────────────────────────────────────────────────────────────────
def t_blender_run(d: Drawing, a, script, render=False, view='iso', engine='workbench', name=''):
    bad = _blender_ok()
    if bad:
        return bad
    src = str(script or '').strip()
    if not src:
        return 'refused: script is empty — pass the bpy Python you want run'
    if len(src) > 40000:
        return 'refused: the script is over 40000 characters — send a shorter one'
    v = str(view or 'iso').lower()
    if v not in VIEWS:
        return f'refused: view must be one of {", ".join(VIEWS)}'
    e = str(engine or 'workbench').lower()
    if e not in TOOL_ENGINES:
        return 'refused: engine must be workbench or eevee'
    try:
        blend, note = _build(d)
    except ValueError as ex:
        return f'refused: {ex}'
    os.makedirs(BLEND_DIR, exist_ok=True)
    ufile = os.path.join(BLEND_DIR, f'_script-{time.strftime("%Y%m%d-%H%M%S")}-{os.getpid()}.py')
    with open(ufile, 'w', encoding='utf-8') as fh:
        fh.write(src)
    try:
        rc, out, png = _second_pass(
            blend, user_file=ufile, save=True, render=(v, e, 1280, 720, _sun_hour(d), 'script') if render else None
        )
    except ValueError as ex:
        return f'refused: {ex}'
    if 'BP_SAVED' in out:
        BSTORE.mark_dirty(blend)  # edited geometry: never offer it as a clean build again
    url, nbytes = _data_url(png)
    body = _tail(out, 2000)
    err = 'BP_SCRIPT_ERROR' in out
    txt = (
        ('the script raised (traceback below) — ' if err else 'script ran — ')
        + (f'saved {os.path.basename(blend)}' if 'BP_SAVED' in out else 'the .blend was NOT saved')
        + f'\nblend: {blend}\n--- output ---\n{body}'
    )
    if url:
        d.images.append({'title': name or f'blender_run · {v}', 'data_url': url})
        return txt + f'\n(picture: {v} view, {nbytes // 1024} KB)', url
    return txt


def _compass(dx, dz) -> str:
    """'north' for studio -z, 'south-east' for +x +z ... the direction from a camera
    to its target, in the studio's compass (north = -Z)."""
    if abs(dx) < 1e-6 and abs(dz) < 1e-6:
        return 'straight down'
    ang = (math.degrees(math.atan2(-dz, dx)) + 360.0) % 360.0  # 0 = east, 90 = north
    names = ['east', 'north-east', 'north', 'north-west', 'west', 'south-west', 'south', 'south-east']
    return names[int((ang + 22.5) // 45.0) % 8]


def _stand_note(d, x, z) -> tuple:
    """(surface_y, note): the surface a camera on (x, z) stands on and its name —
    'the roof deck (8.40 m)', 'the slab (5.62 m)' or 'the ground (0.00 m)'."""
    top = surface_top(d, x, z)
    g = ground_height(d, x, z)
    for t, o in deck_tops(d, x, z):
        if abs(t - top) < 1e-6 and t > g + 1e-6:
            what = 'the roof deck' if str(o.get('kind', '')).startswith('roof') else 'the slab'
            return top, f'{what} ({top:.2f} m)'
    return top, f'the ground ({top:.2f} m)'


def _frame_camera(d, from_cell, to_cell=None, eye_height=None, focal_mm=None, look_height=None) -> dict:
    """The cell camera, solved on the studio side so the reply can say where it
    stands and the Blender pass only has to apply it. Raises ValueError.

    Frames: studio (x, y_up, z) -> Blender (x, -z, y). The camera is aimed LEVEL at
    the target's plan position; the target is lifted into frame with shift_y (a
    fraction of the 36 mm sensor width, clamped to ±SHIFT_MAX) so verticals stay
    vertical; only when the target sits too high (or low) for that is the
    remainder tilted. The camera stands on surface_top (ground or the deck under
    it); the target's surface is the highest deck under to_cell at or below the
    eye, else the ground (see the note in the body)."""
    c, r = parse_cell(from_cell)
    fx, fz = cell_centre(c, r)
    fsurf, stand = _stand_note(d, fx, fz)
    eh = _num(eye_height, EYE_HEIGHT_M)
    eh = EYE_HEIGHT_M if eh is None else min(max(float(eh), 0.2), 500.0)
    focal = _num(focal_mm, FOCAL_DEFAULT_MM)
    focal = FOCAL_DEFAULT_MM if focal is None else float(focal)
    if not (FOCAL_RANGE_MM[0] <= focal <= FOCAL_RANGE_MM[1]):
        raise ValueError(
            f'focal_mm must be {FOCAL_RANGE_MM[0]:g}..{FOCAL_RANGE_MM[1]:g} (35 is a normal lens, 24 wide, 85 long)'
        )
    lh = _num(look_height, LOOK_HEIGHT_M)
    lh = LOOK_HEIGHT_M if lh is None else min(max(float(lh), -50.0), 500.0)
    if to_cell not in (None, ''):
        tc, tr = parse_cell(to_cell)
        tx, tz = cell_centre(tc, tr)
        tname = f'{str(to_cell).strip().upper()}'
    else:
        xs = [float(o.get('x', 0.0)) for o in d.objs if not o.get('hidden')] or [fx]
        zs = [float(o.get('z', 0.0)) for o in d.objs if not o.get('hidden')] or [fz]
        tx, tz = (min(xs) + max(xs)) / 2.0, (min(zs) + max(zs)) / 2.0
        tname = f'{cell_of(tx, tz)} (the centre of the drawing)'
    cy = fsurf + eh
    # the target's surface: the highest deck under to_cell that is NOT above the
    # camera's eye, else the ground. A door cell lies inside its building's
    # footprint, so 'surface under to_cell' taken literally would be the roof deck
    # (measured 2026-09-08: an approach shot aimed 9.9 m up at the roof edge); a
    # camera standing on a deck still aims along that deck.
    tops = [t for t, _o in deck_tops(d, tx, tz) if t <= cy + 1e-6]
    tsurf = round(max([ground_height(d, tx, tz)] + tops), 4)
    ty = tsurf + lh
    dist = math.hypot(tx - fx, tz - fz)
    want = focal * (ty - cy) / max(dist, 0.05) / SENSOR_MM
    shift = max(-SHIFT_MAX, min(SHIFT_MAX, want))
    tilt = 0.0
    if abs(want) > SHIFT_MAX:
        phi = math.atan2(ty - cy, max(dist, 0.05))
        tilt = phi - math.copysign(math.atan(SHIFT_MAX * SENSOR_MM / focal), want)
    return {
        'loc': (round(fx, 4), round(-fz, 4), round(cy, 4)),
        'target': (round(tx, 4), round(-tz, 4), round(ty, 4)),
        'focal': focal,
        'sensor': SENSOR_MM,
        'shift_y': round(shift, 4),
        'tilt': round(tilt, 5),
        'from_cell': str(from_cell).strip().upper(),
        'to_name': tname,
        'stand': stand,
        'surface': fsurf,
        'eye_height': eh,
        'look_height': lh,
        'target_surface': tsurf,
        'dist': dist,
        'compass': _compass(tx - fx, tz - fz),
    }


def _camera_sentence(cs: dict) -> str:
    hd = f'{cs["eye_height"]:g} m'
    plumb = (
        f'verticals plumb (shift_y {cs["shift_y"]:+.2f})'
        if abs(cs['tilt']) < 1e-6
        else f'shift_y {cs["shift_y"]:+.2f} and tilted {"up" if cs["tilt"] > 0 else "down"} '
        f'{abs(math.degrees(cs["tilt"])):.0f}° — the target sat too {"high" if cs["tilt"] > 0 else "low"} for a plumb frame'
    )
    return (
        f'camera at {cs["from_cell"]} on {cs["stand"]} + {hd} = {cs["surface"] + cs["eye_height"]:.2f} m, '
        f'looking {cs["compass"]} at {cs["to_name"]} ({cs["dist"]:.1f} m away, {cs["look_height"]:g} m above '
        f'its surface at {cs["target_surface"]:.2f} m) with a {cs["focal"]:g} mm lens; {plumb}.'
    )


def _ext(name):
    """A sibling family, or None. present() reads four of them and must still
    work in a drawing where none of them is loaded."""
    from zyg_workflows.arch_assistant import EXT_MODULES

    return EXT_MODULES.get(name)


def _entrance_door(d: Drawing):
    """The ground-floor entrance: the widest door at y < 0.5 above its own base.
    None when the drawing has no door at all."""
    DR = _ext('design_rules')
    kinds = tuple(getattr(DR, 'DOOR_KINDS', None) or ('door', 'double_door', 'door_sliding', 'door_french'))
    doors = [
        o
        for o in d.objs
        if o.get('kind') in kinds
        and not o.get('hidden')
        and float(o.get('y') or 0.0) < 0.5 + (_num((o.get('p') or {}).get('base'), 0.0) or 0.0)
    ]
    if not doors:
        return None
    # 2026-09-16 (creator): the widest ground-floor door is NOT always the entrance.
    # build_entrance gives the lobby a 3.6 m interior door on a PARTITION, and
    # present() then stood 30 m NORTH of the tower looking at the fire escape while
    # the lobby camera faced the wrong wall (tower_recipe_20260916 fixture). An
    # entrance sits in an EXTERIOR wall: keep doors whose host (meta.host, else
    # design_rules._host_wall by geometry) is a wall / curtain wall / wall_arc —
    # never a partition. When no door qualifies the old rule stands.
    wall_kinds = tuple(getattr(DR, 'WALL_KINDS', None) or ('wall', 'curtain_wall', 'wall_arc'))
    by_id = {o['id']: o for o in d.objs}
    hostfn = getattr(DR, '_host_wall', None)

    def _exterior(o):
        h = by_id.get(str((o.get('meta') or {}).get('host') or ''))
        if h is None and callable(hostfn):
            try:
                h = hostfn(d, o)
            except Exception:  # noqa: BLE001
                h = None
        return h is not None and str(h.get('kind') or '') in wall_kinds

    ext = [o for o in doors if _exterior(o)]
    pool = ext or doors
    pool.sort(key=lambda o: (-(_num((o.get('p') or {}).get('w'), 1.0) or 1.0), -float(o.get('z') or 0.0), o['id']))
    return pool[0]


def _door_axis(d: Drawing, door: dict) -> tuple:
    """(x, z, nx, nz): the door's centre and its OUTWARD normal. design_rules
    solves this from the host wall; without that family the door's own rotation
    is used, pointed away from the plan centre."""
    DR = _ext('design_rules')
    fn = getattr(DR, '_door_axis', None) if DR is not None else None
    if callable(fn):
        try:
            got = fn(d, door)
        except Exception:  # noqa: BLE001
            got = None
        if got:
            return tuple(float(c) for c in got)
    ry = float(door.get('ry') or 0.0)
    b = _bounds(d)
    vx = float(door['x']) - (b['x0'] + b['x1']) / 2.0
    vz = float(door['z']) - (b['z0'] + b['z1']) / 2.0
    n = (-math.sin(ry), -math.cos(ry))
    if n[0] * vx + n[1] * vz < 0:
        n = (-n[0], -n[1])
    return float(door['x']), float(door['z']), n[0], n[1]


def _bounds(d: Drawing, group='') -> dict:
    """(x0, x1, y0, y1, z0, z1) of the drawing (or of one group), from the record
    origins and their own heights — the fallback for `envelope_rules`."""
    recs = [o for o in d.objs if not o.get('hidden')]
    if group:
        recs = [o for o in recs if o.get('grp') == group] or recs
    if not recs:
        return {'x0': -5.0, 'x1': 5.0, 'y0': 0.0, 'y1': 5.0, 'z0': -5.0, 'z1': 5.0}
    xs = [float(o.get('x') or 0.0) for o in recs]
    zs = [float(o.get('z') or 0.0) for o in recs]
    ys = [float(o.get('y') or 0.0) for o in recs]
    tops = [float(o.get('y') or 0.0) + abs(_num((o.get('p') or {}).get('h'), 0.0) or 0.0) for o in recs]
    return {'x0': min(xs), 'x1': max(xs), 'y0': min(ys), 'y1': max(ys + tops), 'z0': min(zs), 'z1': max(zs)}


def _envelope(d: Drawing, group='') -> dict:
    """The building envelope: envelope_rules' if that family is loaded, else the
    drawing's own bounding box. Same six keys either way."""
    E = _ext('envelope_rules')
    for fname, args in (('group_envelope', (d, group)), ('envelopes', (d,))):
        fn = getattr(E, fname, None) if E is not None else None
        if not callable(fn):
            continue
        try:
            got = fn(*args)
        except Exception as _exc:  # noqa: BLE001 — a missing family must never break a render
            _zyg_log.debug('envelope family call %s failed: %s', fname, _exc)
            continue
        if isinstance(got, (list, tuple)):
            got = got[0] if got else None
        if isinstance(got, dict) and all(k in got for k in ('x0', 'x1', 'y1', 'z0', 'z1')):
            out = dict(got)
            out.setdefault('y0', 0.0)
            return out
    return _bounds(d, group)


def _section_at(d: Drawing, axis: str, at) -> float:
    """The cut plane's coordinate in metres: a cell name ('F12'), a number, or —
    with nothing given — the door axis when a door exists, else the centre."""
    if at not in (None, ''):
        v = _num(at, None)
        if v is not None:
            return float(v)
        c, r = parse_cell(at)  # raises ValueError -> 'refused: ...'
        x, z = cell_centre(c, r)
        return x if axis == 'x' else z
    door = _entrance_door(d)
    if door is not None:
        return float(door['x'] if axis == 'x' else door['z'])
    b = _bounds(d)
    return (b['x0'] + b['x1']) / 2.0 if axis == 'x' else (b['z0'] + b['z1']) / 2.0


def _section_cam(d: Drawing, axis: str, at: float, group='') -> dict:
    """The cut, in the Blender frame (x = studio x, y = -studio z, z = studio y)."""
    e = _envelope(d, group)
    yc = (e['y0'] + e['y1']) / 2.0
    if axis == 'x':  # plane x = at, looking EAST
        zc = (e['z0'] + e['z1']) / 2.0
        return {
            'kind': 'section',
            'axis': 'x',
            'at': round(at, 3),
            'dir': (1.0, 0.0, 0.0),
            'loc': (round(at, 4), round(-zc, 4), round(yc, 4)),
            'ext_w': max(2.0, e['z1'] - e['z0'] + 4.0),
            'ext_h': max(2.0, e['y1'] - e['y0'] + 2.0),
        }
    xc = (e['x0'] + e['x1']) / 2.0  # plane z = at, looking NORTH
    return {
        'kind': 'section',
        'axis': 'z',
        'at': round(at, 3),
        'dir': (0.0, 1.0, 0.0),
        'loc': (round(xc, 4), round(-at, 4), round(yc, 4)),
        'ext_w': max(2.0, e['x1'] - e['x0'] + 4.0),
        'ext_h': max(2.0, e['y1'] - e['y0'] + 2.0),
    }


def t_blender_render(
    d: Drawing,
    a,
    view='iso',
    engine='workbench',
    width=1280,
    height=720,
    name='',
    from_cell=None,
    to_cell=None,
    eye_height=None,
    focal_mm=None,
    look_height=None,
    axis='z',
    at=None,
):
    bad = _blender_ok()
    if bad:
        return bad
    v = str(view or 'iso').lower()
    if v not in VIEWS:
        return f'refused: view must be one of {", ".join(VIEWS)}'
    ax = str(axis or 'z').lower()
    if v == 'section' and ax not in SECTION_AXES:
        return "refused: axis must be 'z' (cut across the plan, looking north) or 'x' (cut down the plan, looking east)"
    e = str(engine or 'workbench').lower()
    if e not in TOOL_ENGINES:
        return 'refused: engine must be workbench or eevee'
    w = int(_num(width, 1280) or 1280)
    h = int(_num(height, 720) or 720)
    if not (160 <= w <= 3840 and 120 <= h <= 2160):
        return 'refused: width must be 160..3840 and height 120..2160 pixels'
    cs = None
    if from_cell not in (None, ''):
        try:
            cs = _frame_camera(d, from_cell, to_cell, eye_height, focal_mm, look_height)
        except ValueError as ex:
            return f'refused: {ex}'
    elif to_cell not in (None, ''):
        return 'refused: to_cell needs a from_cell — say where the camera stands'
    cam = {k: cs[k] for k in ('loc', 'target', 'focal', 'sensor', 'shift_y', 'tilt')} if cs else None
    sec = None
    if v == 'section' and cam is None:
        if not d.objs:
            return 'refused: the drawing is empty — draw something before sending it to Blender'
        try:
            sec = _section_cam(d, ax, _section_at(d, ax, at))
        except ValueError as ex:
            return f'refused: {ex}'
        cam = sec
    try:
        blend, note = _build(d)
        rc, out, png = _second_pass(blend, render=(v, e, w, h, _sun_hour(d), cam))
    except ValueError as ex:
        return f'refused: {ex}'
    url, nbytes = _data_url(png)
    if not url:
        return f'refused: Blender rendered nothing (exit {rc})\n' + _tail(out, 800)
    if sec:
        title = name or f'section {sec["axis"]} = {sec["at"]:g} m · {e}'
        d.images.append({'title': title, 'data_url': url})
        cut = (
            'the plane x = %.2f m, looking east' % sec['at']
            if sec['axis'] == 'x'
            else 'the plane z = %.2f m, looking north' % sec['at']
        )
        return (
            f'cut the drawing open in Blender on {cut} — everything behind the cut is not drawn. '
            f'{e}, {w}x{h}, {nbytes // 1024} KB ({len(d.objs)} records, {note}).',
            url,
        )
    if cs:
        title = name or f'camera {cs["from_cell"]} → {cs["to_name"].split(" ")[0]} · {e}'
        d.images.append({'title': title, 'data_url': url})
        return (
            f'rendered the drawing in Blender: {_camera_sentence(cs)} {e}, {w}x{h}, {nbytes // 1024} KB '
            f'({len(d.objs)} records, {note}).',
            url,
        )
    title = name or f'{v} view · {e}'
    d.images.append({'title': title, 'data_url': url})
    return (
        f'rendered the drawing in Blender: {v} view, {e}, {w}x{h}, {nbytes // 1024} KB '
        f'({len(d.objs)} records, {note}).',
        url,
    )
