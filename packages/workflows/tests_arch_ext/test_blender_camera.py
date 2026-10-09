# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_blender_camera.py — proof for the blender_render cell camera
and the drawing-skills sheets (2026-09-08).

    /usr/bin/python3 tests_arch_ext/test_blender_camera.py

Assistant-only: one headless Blender build (~10 s) plus three render passes
(~10-30 s each). What it proves:

  · blender_render(from_cell, to_cell) stands a real 35 mm camera on the cell,
    aims it LEVEL at the target and lifts the target into frame with shift_y —
    the reply names the camera's position and target, and a PNG comes back.
  · from_cell on a ROOF stands on the deck (3 storeys x 2.7 + 0.3 = 8.4 m) + eye_height.
  · a target too high for a plumb frame tilts the remainder; shift_y is clamped.
  · every named view is untouched when no cell camera is asked for.
  · explain('entrance' / 'porte-cochere' / 'infinity' / 'blender' / ...) resolve
    to sheets of >= 300 characters, and every core blender_run example compiles.
"""

import base64
import json
import math
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, kinds_of, BLENDER  # noqa: E402

T0 = time.time()


def png_of(res):
    url = res[1] if isinstance(res, tuple) and len(res) == 2 else ''
    if isinstance(url, str) and url.startswith('data:image/png;base64,'):
        return base64.b64decode(url.split(',', 1)[1])
    return b''


def world_line(out):
    for line in reversed(str(out).splitlines()):
        if line.startswith('BP_WORLD '):
            try:
                return json.loads(line[9:])
            except ValueError:
                return {}
    return {}


from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
BP = A.EXT_MODULES['blender_power']
G = A.EXT_MODULES['glossary_examples']

# ── registration ──────────────────────────────────────────────────────────────
print('schema')
check('blender is installed', os.path.exists(BLENDER), BLENDER)
schema = next(t for t in A.TOOL_DEFS if t['name'] == 'blender_render')
props = schema['input_schema']['properties']
check(
    'blender_render takes from_cell, to_cell, eye_height, focal_mm, look_height',
    all(k in props for k in ('from_cell', 'to_cell', 'eye_height', 'focal_mm', 'look_height')),
    sorted(props),
)
check(
    'the description says what from_cell/to_cell are for',
    'from_cell' in schema['description'] and 'to_cell' in schema['description'],
    schema['description'][:200],
)
# 2026-09-10: present() added section/back/left; the six original views must survive
check(
    'VIEWS keeps the six original views', {'iso', 'top', 'front', 'right', 'eye', 'aerial'} <= set(BP.VIEWS), BP.VIEWS
)

# ── the camera solver, no Blender ────────────────────────────────────────────
print('solver')
txt, d = assistant('draw_box', {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 3, 'roof': 'flat'})
check(
    '3-storey box with a flat roof drawn',
    kinds_of(d).get('wall') == 12 and kinds_of(d).get('roof_flat') == 1,
    (txt[:120], kinds_of(d)),
)

with A._Scale(getattr(d, 'cell_m', A.CELL_M)):
    cs = BP._frame_camera(d, 'H30', 'H13')
    cr = BP._frame_camera(d, 'F8', 'H13', eye_height=1.7)
    ct = BP._frame_camera(d, 'H20', 'H8', look_height=54.0)
    cfar = BP._frame_camera(d, 'H30', None)
check(
    'H30 -> H13 stands on the ground at 1.7 m (blender z)',
    abs(cs['loc'][2] - 1.7) < 1e-6 and 'ground' in cs['stand'],
    cs,
)
check(
    'the frame is converted: studio (x, y, z) -> blender (x, -z, y)',
    abs(cs['loc'][0] - A.cell_centre(*A.parse_cell('H30'))[0]) < 1e-6
    and abs(cs['loc'][1] + A.cell_centre(*A.parse_cell('H30'))[1]) < 1e-6,
    cs['loc'],
)
check(
    'it looks north (H13 is 17 m up the plan from H30)',
    cs['compass'] == 'north' and abs(cs['dist'] - 17.0) < 1e-6,
    (cs['compass'], cs['dist']),
)
# H13 lies INSIDE the footprint: the roof deck (8.4 m) is above the eye, so the
# target's surface is the storey-0 slab top (0.22 m, the door threshold), not the roof
check(
    'the target is 1.5 m above the surface under H13 — the slab top at 0.22, NOT the roof deck above the eye',
    abs(cs['target'][2] - 1.72) < 1e-6 and abs(cs['target_surface'] - 0.22) < 1e-6,
    cs,
)
check(
    'a target level with the eye needs almost no shift and no tilt',
    abs(cs['shift_y']) < 0.05 and cs['tilt'] == 0.0,
    (cs['shift_y'], cs['tilt']),
)
check(
    'F8 (on the roof) stands on the deck: 3 x 2.7 + 0.3 = 8.4 m, + 1.7 = 10.1',
    abs(cr['surface'] - 8.4) < 1e-6 and abs(cr['loc'][2] - 10.1) < 1e-6 and 'roof deck' in cr['stand'],
    cr,
)
check(
    'a 54 m target 12 m away clamps shift_y to 0.6 and tilts the rest UP',
    cr is not None and ct['shift_y'] == 0.6 and ct['tilt'] > 0.5,
    (ct['shift_y'], ct['tilt']),
)
phi = math.atan2(ct['target'][2] - ct['loc'][2], ct['dist'])
check(
    '...by exactly phi - atan(0.6 * 36 / 35)',
    abs(ct['tilt'] - (phi - math.atan(0.6 * 36.0 / 35.0))) < 1e-4,
    (ct['tilt'], phi),
)
check(
    'no to_cell: the centre of the drawing (cell H9, inside the box)',
    'centre of the drawing' in cfar['to_name']
    and cfar['to_name'].startswith('H9')
    or cfar['to_name'].startswith('G8')
    or cfar['to_name'].startswith('H8'),
    cfar['to_name'],
)
sent = BP._camera_sentence(cr)
check(
    'the sentence names the cell, the deck, the eye height, the target and the lens',
    all(w in sent for w in ('camera at F8', 'roof deck (8.40 m)', '1.7 m', 'H13', '35 mm')),
    sent,
)
txt, _ = assistant('blender_render', {'from_cell': 'H30', 'to_cell': 'H13', 'focal_mm': 500}, drawing=d)
check(
    'a silly focal length is refused before Blender runs', str(txt).startswith('refused') and '14..135' in str(txt), txt
)
txt, _ = assistant('blender_render', {'to_cell': 'H13'}, drawing=d)
check('to_cell without from_cell is refused', str(txt).startswith('refused') and 'from_cell' in str(txt), txt)
txt, _ = assistant('blender_render', {'from_cell': 'ZZZ999'}, drawing=d)
check('a bad from_cell is refused', str(txt).startswith('refused'), txt)

# ── the render from the approach ─────────────────────────────────────────────
print('render: from the approach')
res, d = assistant(
    'blender_render',
    {'from_cell': 'H30', 'to_cell': 'H13', 'engine': 'workbench', 'width': 480, 'height': 320},
    drawing=d,
)
reply = res[0] if isinstance(res, tuple) else str(res)
print('    reply: ' + reply)
check('the tool returns a (text, data_url) tuple', isinstance(res, tuple) and len(res) == 2, type(res))
raw = png_of(res)
check('a real PNG > 10 KB comes back', raw[:4] == b'\x89PNG' and len(raw) > 10240, (raw[:8], len(raw)))
check(
    'the reply names the camera position and target',
    'camera at H30 on the ground' in reply
    and 'looking north at H13' in reply
    and '35 mm lens' in reply
    and '1.7 m' in reply,
    reply,
)
check('the reply says the verticals are plumb', 'verticals plumb' in reply, reply)
check(
    'the picture reaches the chat with a camera title',
    d.images and d.images[-1]['title'].startswith('camera H30'),
    [i.get('title') for i in d.images],
)

# the BP_WORLD line: what the camera in Blender actually was
blend = d._bp_blend[1]
cam = {k: cs[k] for k in ('loc', 'target', 'focal', 'sensor', 'shift_y', 'tilt')}
rc, out, png = BP._second_pass(blend, render=('iso', 'workbench', 320, 200, None, cam))
W = world_line(out)
print(
    '    world: '
    + json.dumps(
        {k: W.get(k) for k in ('cam', 'cam_loc', 'cam_fwd', 'cam_lens', 'cam_shift_y', 'cam_tilt_deg', 'cam_source')}
    )
)
check(
    'Blender used a PERSP camera with a 35 mm lens at the cell',
    rc == 0
    and W.get('cam') == 'PERSP'
    and W.get('cam_lens') == 35.0
    and W.get('cam_source') == 'cells'
    and all(abs(a - b) < 1e-3 for a, b in zip(W.get('cam_loc') or [0, 0, 0], cs['loc'])),
    W,
)
check(
    'it looks level and north: forward (0, 1, 0) — verticals stay vertical',
    W.get('cam_fwd') and abs(W['cam_fwd'][2]) < 1e-3 and W['cam_fwd'][1] > 0.999,
    W.get('cam_fwd'),
)
check(
    'shift_y went through',
    abs((W.get('cam_shift_y') or 0) - cs['shift_y']) < 1e-3,
    (W.get('cam_shift_y'), cs['shift_y']),
)

# a named view is untouched
rc, out, _ = BP._second_pass(blend, render=('eye', 'workbench', 320, 200, None))
We = world_line(out)
check(
    "'eye' without a cell camera is what it was: FOV camera, source 'view'",
    rc == 0
    and We.get('cam') == 'PERSP'
    and We.get('cam_source') == 'view'
    and We.get('cam_lens') is None
    and We.get('cam_fwd')
    and We['cam_fwd'][1] > 0.9,
    We,
)

# ── from the roof ────────────────────────────────────────────────────────────
print('render: from the roof')
res, d = assistant(
    'blender_render',
    {'from_cell': 'F8', 'to_cell': 'H13', 'eye_height': 1.7, 'engine': 'workbench', 'width': 480, 'height': 320},
    drawing=d,
)
reply2 = res[0] if isinstance(res, tuple) else str(res)
print('    reply: ' + reply2)
check('the roof render returns a PNG', png_of(res)[:4] == b'\x89PNG', reply2[:200])
check(
    'the reply says the camera stands on the deck at 8.4 m + 1.7',
    re.search(r'camera at F8 on the roof deck \(8\.40 m\) \+ 1\.7 m = 10\.10 m', reply2) is not None,
    reply2,
)

# a tilted frame (the target too high for shift alone)
res, d = assistant(
    'blender_render',
    {'from_cell': 'H20', 'to_cell': 'H8', 'look_height': 54, 'engine': 'workbench', 'width': 320, 'height': 200},
    drawing=d,
)
reply3 = res[0] if isinstance(res, tuple) else str(res)
print('    reply: ' + reply3[:220])
check(
    'a target too high for a plumb frame says it tilted up', 'tilted up' in reply3 and 'shift_y +0.60' in reply3, reply3
)

# ── the skills sheets ────────────────────────────────────────────────────────
print('sheets')
for topic in (
    'entrance',
    'porte-cochere',
    'infinity',
    'blender',
    'quality',
    'roof',
    'facade',
    'render',
    'presentation',
):
    t = G.explain(topic)
    check('explain(%r) resolves to a sheet of >= 300 chars (%d)' % (topic, len(t)), len(t) >= 300, t[:80])
check("explain('porte-cochere') is the entrance sheet", G.explain('porte-cochere') == G.EXPLAIN['entrance'])
# 2026-09-12: the infinity pool got its OWN sheet (add_infinity_pool, written from the operator's
# five reference pictures); 'infinity' resolves there now, not to the roof sheet.
check(
    "explain('infinity') is the infinity-pool sheet",
    G.explain('infinity') == G.EXPLAIN['infinity pool'] and G.explain('infinity').startswith('ROOFTOP INFINITY POOL'),
    G.explain('infinity')[:80],
)
check("explain('presentation') is the quality sheet", G.explain('presentation') == G.EXPLAIN['quality'])
check("explain('roof') still names add_roof (the old glossary test)", 'add_roof' in G.explain('roof'))
check(
    'the six sheets fit their caps (900; blender 1400)',
    all(len(G.EXPLAIN[k]) <= 900 for k in ('quality', 'entrance', 'roof', 'facade', 'render'))
    and len(G.EXPLAIN['blender']) <= 1400,
    {k: len(G.EXPLAIN[k]) for k in ('quality', 'entrance', 'roof', 'facade', 'render', 'blender')},
)
check(
    'the entrance sheet gives the canopy rule',
    'add_canopy' in G.EXPLAIN['entrance'] and '3.5-4.5 m' in G.EXPLAIN['entrance'],
)
check('the roof sheet gives the deck arithmetic', '2.7 + 0.3' in G.EXPLAIN['roof'] and 'from_cell' in G.EXPLAIN['roof'])
check(
    'the blender sheet says the frame and that records stay parametric',
    '(x, -z, y)' in G.EXPLAIN['blender'] and 'parametric' in G.EXPLAIN['blender'] and 'shift_y' in G.EXPLAIN['blender'],
)

# ── the core examples ────────────────────────────────────────────────────────
print('core examples')
core = [e for e in BP.EXAMPLES if e.get('core')]
run_core = [
    e for e in core if any(c['tool'] == 'blender_run' for c in e['calls'])
]  # present()/section examples are core too
check('four core blender_run examples', len(run_core) == 4, [e['ask'] for e in core])
for e in core:
    for c in e['calls']:
        sc = (c.get('args') or {}).get('script')
        if not sc:
            continue
        ok = True
        try:
            compile(sc, 'x', 'exec')
        except SyntaxError as ex:
            ok = ex
        check('core script compiles: ' + e['ask'][:48], ok is True, ok)
        check(
            '...and never indexes bpy.data.objects[...] blindly',
            "bpy.data.objects['" not in sc and 'bpy.data.objects["' not in sc,
            sc[:200],
        )
kinds = {'bev': 'BEVEL', 'pool': 'BOOLEAN', 'fins': 'ARRAY', 'cam': 'shift_y'}
scripts = '\n'.join((c.get('args') or {}).get('script') or '' for e in core for c in e['calls'])
check('the four cover BEVEL, BOOLEAN, ARRAY and a shift_y camera', all(v in scripts for v in kinds.values()))

# the camera script really works inside Blender: run it and render through it
print('core camera script in Blender')
cam_script = next(
    (c['args']['script'] for e in core for c in e['calls'] if 'shift_y' in (c['args'].get('script') or '')), ''
)
res, d = assistant('blender_run', {'script': cam_script, 'render': True, 'engine': 'workbench'}, drawing=d)
rtxt = res[0] if isinstance(res, tuple) else str(res)
check('the camera example runs without raising', 'BP_SCRIPT_ERROR' not in rtxt and 'camera at' in rtxt, rtxt[-400:])
check('...and render=true gives a picture through it', png_of(res)[:4] == b'\x89PNG', rtxt[:200])
rc, out, _ = BP._second_pass(d._bp_blend[1], render=('iso', 'workbench', 320, 200, None, 'script'))
Ws = world_line(out)
check(
    "the script's camera was kept for render=true (source 'script', 35 mm)",
    rc == 0 and Ws.get('cam_source') == 'script' and Ws.get('cam_lens') == 35.0,
    Ws,
)
rc, out, _ = BP._second_pass(d._bp_blend[1], render=('iso', 'workbench', 320, 200, None))
Wn = world_line(out)
check(
    '...but a later named view is NOT hijacked by the saved script camera',
    rc == 0 and Wn.get('cam_source') == 'view' and Wn.get('cam') == 'ORTHO',
    Wn,
)

check('the whole test stayed under 6 minutes', time.time() - T0 < 360, round(time.time() - T0, 1))
finish()
