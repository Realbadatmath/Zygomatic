# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""blender_power.hero_render — see the package docstring."""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.blender_power.constants import (
    BLEND_DIR,
    Drawing,
    ENGINES,
    FORMATS,
    HERO_H,
    HERO_JPEG_Q,
    HERO_JPEG_W,
    HERO_TIMEOUT,
    HERO_VIEWS,
    HERO_W,
    RENDER_DIR,
    SECTION_AXES,
    VIEWS,
    _num,
    json,
    os,
    re,
    time,
)
from zyg_workflows.arch_assistant_ext.blender_power.build import (
    _blender_ok,
    _build,
    _slug,
)
from zyg_workflows.arch_assistant_ext.blender_power.second_pass import (
    _between,
    _second_pass,
    _sun_hour,
    _tail,
)
from zyg_workflows.arch_assistant_ext.blender_power.tools import (
    t_blender_render,
    t_blender_run,
)
from zyg_workflows.arch_assistant_ext.blender_power.present import (
    _hero_shot,
    _present_shots,
    t_present,
)
from zyg_workflows.arch_assistant_ext.blender_power.portfolio import (
    t_portfolio,
)

# ── the hero: one photoreal 4K Cycles frame, as a FILE ───────────────────────
# A 4K PNG is 10-20 MB; a data URL that size never survives the panel's
# localStorage, so the hero travels as a path the tab fetches from
# PICTURE_URL + <basename> and the model never sees it at all.
PICTURE_URL = '/inspect/api/architecture/assistant/picture?f='


def _hero_jpeg(png, dest):
    """The panel copy of a hero frame: HERO_JPEG_W wide, quality HERO_JPEG_Q.
    Returns dest, or '' when PIL is missing or the PNG will not open."""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001
        return ''
    try:
        with Image.open(png) as im:
            im = im.convert('RGB')
            if im.width > HERO_JPEG_W:
                im = im.resize((HERO_JPEG_W, max(1, round(im.height * HERO_JPEG_W / im.width))), Image.LANCZOS)
            im.save(dest, 'JPEG', quality=HERO_JPEG_Q, optimize=True)
    except Exception:  # noqa: BLE001
        return ''
    return dest if os.path.exists(dest) else ''


def hero_render(d: Drawing, job_id, views=HERO_VIEWS, width=HERO_W, height=HERO_H):
    """The photoreal hand-over picture: `views` rendered with CYCLES on the GPU,
    written to RENDER_DIR as <job>-hero-<view>.png with a light JPEG beside each.

    Returns [{'title', 'view', 'png', 'jpeg', 'seconds', 'device', 'samples',
    'exposure'}] — the lobby frame is the one that comes back at HERO_EV_VIEW's
    interior stop, with the room's own lamps in it.
    Raises ValueError (Blender missing, empty drawing, build failure) — the
    caller logs it and hands over the EEVEE pictures instead."""
    bad = _blender_ok()
    if bad:
        raise ValueError(bad[len('refused: ') :] if bad.startswith('refused: ') else bad)
    want = [str(v).lower() for v in (views or HERO_VIEWS)]
    w, h = int(_num(width, HERO_W) or HERO_W), int(_num(height, HERO_H) or HERO_H)
    shots, door, env, _yc = _present_shots(d, '')
    # the whole-building shot is not one of present()'s working views: it is
    # prepended here, and the frames come back in the order `views` asked for —
    # the first one is the panel's preview picture.
    shots = [_hero_shot(d, env, door, _sun_hour(d), w / float(h))] + list(shots)
    rank: dict = {}
    for i, v in enumerate(want):
        rank.setdefault(v, i)
    picked = sorted((s for s in shots if s[0] in rank), key=lambda s: rank[s[0]])
    if not picked:
        raise ValueError(f'no hero view among {", ".join(want)}')
    blend, _note = _build(d)
    os.makedirs(RENDER_DIR, exist_ok=True)
    jid = re.sub(r'[^A-Za-z0-9_-]+', '', str(job_id or 'job'))[:32] or 'job'
    out = []
    for title, view, cam, probe in picked:
        png = os.path.join(RENDER_DIR, f'{jid}-hero-{title}.png')
        t0 = time.time()
        rc, txt, got = _second_pass(
            blend, render=(view, 'cycles', w, h, _sun_hour(d), cam, probe, png), timeout=HERO_TIMEOUT
        )
        secs = round(time.time() - t0, 1)
        if not os.path.exists(png):
            raise ValueError(f'the {title} hero frame did not render (Blender exit {rc}): {_tail(txt, 400)}')
        world = {}
        for line in reversed(str(txt).splitlines()):
            if line.startswith('BP_WORLD '):
                try:
                    world = json.loads(line[9:])
                except ValueError:
                    world = {}
                break
        hero = world.get('hero') or {}
        out.append(
            {
                'title': title,
                'view': view,
                'png': png,
                'jpeg': _hero_jpeg(png, os.path.splitext(png)[0] + '.jpg'),
                'seconds': secs,
                'bytes': os.path.getsize(png),
                'engine': world.get('engine_set') or '',
                'device': hero.get('device') or '',
                'backend': hero.get('backend') or '',
                'samples': hero.get('samples'),
                'sky': hero.get('sky') or '',
                'ground': hero.get('ground') or '',
                'exposure': hero.get('exposure'),
                'ev_view': hero.get('ev_view') or '',
                'out': txt,
            }
        )
    return out


def hero_images(hero_list):
    """The hero frames as the chat panel's image records: the JPEG is what the
    <img> loads, `full` is the 4K PNG behind it. Both are URLs, never bytes."""
    out = []
    for hr in hero_list or []:
        png = str((hr or {}).get('png') or '')
        jpeg = str((hr or {}).get('jpeg') or '')
        if not png:
            continue
        shown = jpeg or png
        out.append(
            {
                'title': 'photoreal 4K · ' + str(hr.get('title') or 'view'),
                'data_url': PICTURE_URL + os.path.basename(shown),
                'full': PICTURE_URL + os.path.basename(png),
            }
        )
    return out


def t_blender_export(d: Drawing, a, format='glb', name=''):
    bad = _blender_ok()
    if bad:
        return bad
    fmt = str(format or 'glb').lower().lstrip('.')
    if fmt == 'gltf':
        fmt = 'glb'
    if fmt not in FORMATS:
        return f'refused: format must be one of {", ".join(sorted(FORMATS))}'
    try:
        blend, note = _build(d)
    except ValueError as ex:
        return f'refused: {ex}'
    path = os.path.splitext(blend)[0] + FORMATS[fmt]
    if name:
        path = os.path.join(BLEND_DIR, _slug(name) + FORMATS[fmt])
    try:
        rc, out, _ = _second_pass(blend, export=(fmt, path))
    except ValueError as ex:
        return f'refused: {ex}'
    if not os.path.exists(path):
        return f'refused: the {fmt.upper()} export failed — ' + (
            _between(out, 'BP_EXPORT_FAIL ', '\n') or _tail(out, 400)
        )
    kb = os.path.getsize(path) / 1024.0
    return f'exported {len(d.objs)} objects as {fmt.upper()}: {path} ({kb:.1f} KB)'


def t_blender_measure(d: Drawing, a):
    bad = _blender_ok()
    if bad:
        return bad
    try:
        blend, note = _build(d)
        rc, out, _ = _second_pass(blend, measure=True)
    except ValueError as ex:
        return f'refused: {ex}'
    table = _between(out, 'BP_MEASURE_BEGIN', 'BP_MEASURE_END')
    if not table:
        return f'refused: the measurement pass produced nothing (exit {rc})\n' + _tail(out, 400)
    return f'measured {os.path.basename(blend)} ({note}):\n' + table[:3500]


TOOLS = [
    (
        {
            'name': 'blender_run',
            'description': (
                'Run your own bpy Python inside a headless Blender holding the drawing. Use for geometry the '
                'studio kinds cannot express: booleans, bevels, arrays, subdivision, custom meshes, material '
                'edits. Edits are saved into the .blend and persist for the rest of this request, but they do '
                'NOT change the parametric drawing. render=true gives a picture back — through a camera your '
                'script made and set as bpy.context.scene.camera, else the named view.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'script': {
                        'type': 'string',
                        'description': 'Python for Blender; bpy, bmesh, math and mathutils are imported. Everything you print comes back.',
                    },
                    'render': {'type': 'boolean'},
                    'view': {'type': 'string', 'enum': list(VIEWS)},
                    'engine': {'type': 'string', 'enum': list(ENGINES)},
                    'name': {'type': 'string'},
                },
                'required': ['script'],
            },
        },
        t_blender_run,
    ),
    (
        {
            'name': 'blender_render',
            'description': (
                'A rendered picture of the whole drawing rebuilt in Blender under a real sky and sun. '
                'iso/top and the four elevations front/back/right/left are orthographic; "section" CUTS THE '
                'BUILDING OPEN on a plane (axis="z" cuts across the plan at z=at and looks north, axis="x" cuts '
                'down the plan at x=at and looks east; `at` is a cell name or metres, default the entrance door '
                'axis) — everything behind the cut is not drawn, so a stair through slabs, a shaft without a '
                'floor opening or a missing landing is visible; "eye" stands on the ground at the south edge at '
                '1.7 m looking north; "aerial" looks down from 45 degrees in the south-west. INTERIOR views are '
                'from_cell/to_cell + eye_height: they stand the camera on a cell and look at another — the way '
                'to check an entrance from its approach, a room from its door or a roof from its deck (a real '
                'lens, verticals kept plumb; the camera stands on whatever surface is under from_cell: the '
                'ground, a slab or a roof deck). Use to check a result you cannot judge from numbers. Workbench '
                'is fast and flat; eevee is lit and slower.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'view': {'type': 'string', 'enum': list(VIEWS)},
                    'engine': {'type': 'string', 'enum': list(ENGINES)},
                    'width': {'type': 'integer'},
                    'height': {'type': 'integer'},
                    'name': {'type': 'string'},
                    'axis': {
                        'type': 'string',
                        'enum': list(SECTION_AXES),
                        'description': 'view="section" only: "z" cuts across the plan and looks north, "x" cuts down the plan and looks east',
                    },
                    'at': {
                        'type': 'string',
                        'description': 'view="section" only: the cut plane, a cell name (F12) or metres; default the entrance door axis, else the centre',
                    },
                    'from_cell': {
                        'type': 'string',
                        'description': 'the cell the camera stands on (its surface: ground or a roof deck); given, it replaces `view`',
                    },
                    'to_cell': {
                        'type': 'string',
                        'description': 'the cell the camera looks at (default: the centre of the drawing)',
                    },
                    'eye_height': {
                        'type': 'number',
                        'description': 'metres above the surface under from_cell, default 1.7',
                    },
                    'focal_mm': {
                        'type': 'number',
                        'description': 'lens, 14..135 mm on a 36 mm sensor; default 35 (24 wide, 85 long)',
                    },
                    'look_height': {
                        'type': 'number',
                        'description': 'metres above the surface under to_cell the camera aims at (the ground, or a deck no higher than the camera), default 1.5',
                    },
                },
                'required': [],
            },
        },
        t_blender_render,
    ),
    (
        {
            'name': 'present',
            'description': (
                'Show the building the way it will be judged: five renders from one build — approach (1.7 m on '
                'the entrance axis 30 m out, 28 mm), section (cut through the entrance axis, so stairs and '
                'shafts are seen crossing the slabs), elevation, aerial and lobby (4 m inside the door at 1.6 m '
                'looking out). The reply is NUMBERS, not adjectives: records the camera can really SEE of the '
                'records in frustum, the tallest visible one, '
                'whether the door is in the approach frame, slabs crossed without an opening, and the full '
                'design-check findings. done requires present() after the last drawing change.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group': {
                        'type': 'string',
                        'description': 'the building group to frame; default the whole drawing',
                    },
                    'engine': {'type': 'string', 'enum': list(ENGINES)},
                    'width': {'type': 'integer'},
                    'height': {'type': 'integer'},
                },
                'required': [],
            },
        },
        t_present,
    ),
    (
        {
            'name': 'portfolio',
            'description': (
                'THE PORTFOLIO — the hand-over the operator asked for: about fifty renders of the whole '
                'drawing in ONE Blender pass, written to a FOLDER they open. Twelve standpoints right '
                'round it and four from above, the six orthographic views, a cut on the centreline and '
                'six across it, a plan cut over every level and two views from INSIDE every level with a '
                '1.75 m figure for scale, two raking shots that show whether the curves run fair, and '
                'close lenses on the ends, the entrance and the decks. Each picture carries the '
                'measurement its camera made, and a SURFACE AUDIT comes with it: meshes with no '
                'material, untouched default materials, big flat-shaded curves, open edges. done() is '
                'refused until the current drawing has one. Contact sheets come back as pictures here; '
                'the full-size frames are in the folder.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {'width': {'type': 'integer'}, 'height': {'type': 'integer'}},
                'required': [],
            },
        },
        t_portfolio,
    ),
    (
        {
            'name': 'blender_export',
            'description': (
                'Export the drawing from Blender to a file the user can take away: obj, fbx, stl, glb, usd or '
                'ply. Returns the path on the server and its size.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {'format': {'type': 'string', 'enum': sorted(FORMATS)}, 'name': {'type': 'string'}},
                'required': [],
            },
        },
        t_blender_export,
    ),
    (
        {
            'name': 'blender_measure',
            'description': (
                'A table of every Blender object: bounding box in metres, mesh volume, face count and the '
                'studio id. Use to verify sizes and to find records that built empty.'
            ),
            'input_schema': {'type': 'object', 'properties': {}, 'required': []},
        },
        t_blender_measure,
    ),
]

_EX_BEVEL = (
    'import bpy\n'
    'n = 0\n'
    'for ob in bpy.data.objects:\n'
    "    if ob.type != 'MESH' or ob.get('studio_kind') not in ('wall', 'partition', 'column_rect', 'column_round', 'slab', 'roof_flat'):\n"
    '        continue\n'
    "    if ob.modifiers.get('bev') is None:\n"
    "        m = ob.modifiers.new('bev', 'BEVEL')\n"
    '        m.width = 0.03\n'
    '        m.segments = 2\n'
    "        m.limit_method = 'ANGLE'\n"
    '        n += 1\n'
    "print('bevelled', n, 'objects')\n"
)

_EX_POOL = (
    'import bpy\n'
    "roof = bpy.data.objects.get('roof_flat o101')\n"
    'if roof is None:\n'
    "    print('no roof_flat o101 —', [o.name for o in bpy.data.objects if o.name.startswith('roof')])\n"
    'else:\n'
    "    # blender frame: x = studio x, y = -studio z, z = studio y (up); the roof's top is its bbox max z\n"
    '    top = max((roof.matrix_world @ v.co).z for v in roof.data.vertices)\n'
    '    cx, cy = roof.matrix_world.translation.x, roof.matrix_world.translation.y\n'
    '    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(cx, cy, top - 0.75 + 0.01))\n'
    '    cut = bpy.context.active_object\n'
    "    cut.name = 'pool cutter'\n"
    '    cut.scale = (6.0, 3.0, 1.5)\n'
    '    cut.hide_render = True\n'
    "    cut.display_type = 'WIRE'\n"
    "    m = roof.modifiers.new('pool', 'BOOLEAN')\n"
    "    m.operation = 'DIFFERENCE'\n"
    "    m.solver = 'EXACT'\n"
    '    m.object = cut\n'
    '    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(cx, cy, top - 0.15))\n'
    '    water = bpy.context.active_object\n'
    "    water.name = 'pool water'\n"
    '    water.scale = (5.9, 2.9, 0.3)\n'
    "    mat = bpy.data.materials.new('pool water')\n"
    '    mat.use_nodes = True\n'
    "    b = mat.node_tree.nodes['Principled BSDF']\n"
    "    b.inputs['Base Color'].default_value = (0.6, 0.85, 0.9, 1.0)\n"
    "    b.inputs['Roughness'].default_value = 0.05\n"
    "    b.inputs['IOR'].default_value = 1.33\n"
    "    b.inputs['Transmission Weight'].default_value = 1.0\n"
    '    water.data.materials.append(mat)\n'
    "    print('pool cut 6 x 3 x 1.5 m into', roof.name, 'deck at', round(top, 2))\n"
)

_EX_FINS = (
    'import bpy, mathutils\n'
    "# south face = the largest y-min over the building's walls (blender y = -studio z, so south is -y)\n"
    "walls = [o for o in bpy.data.objects if o.type == 'MESH' and o.get('studio_kind') == 'wall']\n"
    'if not walls:\n'
    "    print('no walls')\n"
    'else:\n'
    '    pts = [o.matrix_world @ mathutils.Vector(c) for o in walls for c in o.bound_box]\n'
    '    x0, x1 = min(p.x for p in pts), max(p.x for p in pts)\n'
    '    y0 = min(p.y for p in pts)\n'
    '    z0, z1 = min(p.z for p in pts), max(p.z for p in pts)\n'
    '    h = z1 - z0\n'
    '    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x0 + 0.3, y0 - 0.25, z0 + h / 2.0))\n'
    '    fin = bpy.context.active_object\n'
    "    fin.name = 'fin'\n"
    '    fin.scale = (0.08, 0.5, h)\n'
    "    arr = fin.modifiers.new('arr', 'ARRAY')\n"
    '    arr.count = 20\n'
    '    arr.use_relative_offset = False\n'
    '    arr.use_constant_offset = True\n'
    '    arr.constant_offset_displace = (0.6, 0.0, 0.0)\n'
    "    mat = bpy.data.materials.get('mat_steel') or bpy.data.materials.new('mat_steel')\n"
    '    fin.data.materials.append(mat)\n'
    "    print('20 fins 0.6 m apart along the south face from x', round(x0, 2), 'height', round(h, 2))\n"
)

_EX_CAMERA = (
    'import bpy, math, mathutils\n'
    '# stand at studio (x=12, z=30) on the ground, 1.7 m up; look at the door at studio (12, 13), 1.5 m up\n'
    'loc = mathutils.Vector((12.0, -30.0, 1.7))        # blender frame: (x, -z, y)\n'
    'tgt = mathutils.Vector((12.0, -13.0, 1.5))\n'
    "cd = bpy.data.cameras.new('cam')\n"
    "cd.lens_unit = 'MILLIMETERS'\n"
    "cd.sensor_fit = 'HORIZONTAL'\n"
    'cd.sensor_width = 36.0\n'
    'cd.lens = 35.0\n'
    "cam = bpy.data.objects.new('cam', cd)\n"
    'bpy.context.scene.collection.objects.link(cam)\n'
    'cam.location = loc\n'
    "# aim LEVEL at the target's plan position, so verticals stay vertical...\n"
    'flat = mathutils.Vector((tgt.x - loc.x, tgt.y - loc.y, 0.0))\n'
    "cam.rotation_euler = (-flat).normalized().to_track_quat('Z', 'Y').to_euler()\n"
    '# ...and lift the target into frame with the sensor shift (a fraction of the 36 mm width, clamped to +-0.6)\n'
    'cd.shift_y = max(-0.6, min(0.6, cd.lens * (tgt.z - loc.z) / flat.length / cd.sensor_width))\n'
    'bpy.context.scene.camera = cam        # render=true uses the camera the script set\n'
    "print('camera at', tuple(round(c, 2) for c in loc), 'lens 35 mm, shift_y', round(cd.shift_y, 3))\n"
)

EXAMPLES = [
    # core (2026-09-08): the pro sheet's four worked bpy scripts, listed first in the prompt
    {
        'core': True,
        'ask': 'make it read as built, not drawn — bevel every concrete edge and show me from the corner',
        'calls': [
            {'tool': 'blender_run', 'args': {'script': _EX_BEVEL, 'render': True, 'view': 'eye', 'engine': 'eevee'}}
        ],
    },
    {
        'core': True,
        'ask': 'cut a 6 by 3 m pool, 1.5 deep, into the roof o101 and fill it with water',
        'calls': [
            {'tool': 'blender_run', 'args': {'script': _EX_POOL, 'render': True, 'view': 'aerial', 'engine': 'eevee'}}
        ],
    },
    {
        'core': True,
        'ask': 'twenty vertical fins 60 cm apart along the south facade',
        'calls': [
            {'tool': 'blender_run', 'args': {'script': _EX_FINS, 'render': True, 'view': 'front', 'engine': 'eevee'}}
        ],
    },
    {
        'core': True,
        'ask': "a photographer's shot in bpy: stand 17 m south of the door, 35 mm, verticals straight",
        'calls': [{'tool': 'blender_run', 'args': {'script': _EX_CAMERA, 'render': True, 'engine': 'eevee'}}],
    },
    {
        'core': True,
        'ask': 'that looks finished — show me before you hand it over',
        'calls': [{'tool': 'present', 'args': {'engine': 'eevee'}}, {'tool': 'portfolio', 'args': {}}],
    },
    {
        'core': True,
        'ask': 'does the stair actually go through the floors? cut it open',
        'calls': [
            {
                'tool': 'blender_render',
                'args': {'view': 'section', 'axis': 'x', 'at': 'F12', 'engine': 'eevee', 'width': 1600, 'height': 900},
            }
        ],
    },
    {
        'ask': 'show me the north elevation',
        'calls': [{'tool': 'blender_render', 'args': {'view': 'back', 'engine': 'eevee'}}],
    },
    {
        'ask': 'what does the lobby feel like from inside?',
        'calls': [
            {
                'tool': 'blender_render',
                'args': {
                    'from_cell': 'M14',
                    'to_cell': 'M20',
                    'eye_height': 1.6,
                    'focal_mm': 24,
                    'look_height': 1.6,
                    'engine': 'eevee',
                },
            }
        ],
    },
    {
        'ask': 'check the entrance from the drive, the way a visitor arrives',
        'calls': [
            {
                'tool': 'blender_render',
                'args': {
                    'from_cell': 'M31',
                    'to_cell': 'M14',
                    'eye_height': 1.7,
                    'focal_mm': 35,
                    'look_height': 1.5,
                    'engine': 'eevee',
                },
            }
        ],
    },
    {
        'ask': 'check the pool from the roof deck',
        'calls': [
            {
                'tool': 'blender_render',
                'args': {
                    'from_cell': 'D5',
                    'to_cell': 'H8',
                    'eye_height': 1.7,
                    'focal_mm': 28,
                    'look_height': 0.0,
                    'engine': 'eevee',
                },
            }
        ],
    },
    {
        'ask': 'show me what this looks like',
        'calls': [{'tool': 'blender_render', 'args': {'view': 'iso', 'engine': 'workbench'}}],
    },
    {
        'ask': 'render the house from the front, nicely lit',
        'calls': [
            {'tool': 'blender_render', 'args': {'view': 'front', 'engine': 'eevee', 'width': 1600, 'height': 900}}
        ],
    },
    {
        'ask': 'what does the valley look like from down there?',
        'calls': [{'tool': 'blender_render', 'args': {'view': 'eye', 'engine': 'eevee', 'width': 1600, 'height': 900}}],
    },
    {
        'ask': 'show me the whole site from the air',
        'calls': [
            {'tool': 'blender_render', 'args': {'view': 'aerial', 'engine': 'eevee', 'width': 1600, 'height': 900}}
        ],
    },
    {'ask': 'how big is it really, and how many faces?', 'calls': [{'tool': 'blender_measure', 'args': {}}]},
    {
        'ask': 'give me a glb of the terraced houses',
        'calls': [{'tool': 'blender_export', 'args': {'format': 'glb', 'name': 'row houses'}}],
    },
    {
        'ask': 'bevel all the wall edges by 3 cm and show me',
        'calls': [
            {
                'tool': 'blender_run',
                'args': {
                    'script': (
                        'import bpy\nn = 0\nfor ob in bpy.data.objects:\n'
                        "    if ob.get('studio_kind') in ('wall', 'partition'):\n"
                        "        m = ob.modifiers.new('bev', 'BEVEL'); m.width = 0.03; m.segments = 2\n"
                        "        n += 1\nprint('bevelled', n, 'walls')"
                    ),
                    'render': True,
                    'view': 'iso',
                },
            }
        ],
    },
    {
        'ask': 'cut a 1.2 m round hole through the north wall o5',
        'calls': [
            {
                'tool': 'blender_run',
                'args': {
                    'script': (
                        'import bpy\nbpy.ops.mesh.primitive_cylinder_add(radius=0.6, depth=2, '
                        'rotation=(1.5708, 0, 0), location=(0, 0, 1.5))\ncut = bpy.context.active_object\n'
                        "w = bpy.data.objects['wall o5']\nm = w.modifiers.new('hole', 'BOOLEAN')\n"
                        "m.operation = 'DIFFERENCE'; m.object = cut\nprint('boolean added to', w.name)"
                    ),
                    'render': True,
                    'view': 'front',
                },
            }
        ],
    },
]
