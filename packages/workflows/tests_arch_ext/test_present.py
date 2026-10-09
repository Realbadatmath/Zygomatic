# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_present.py — proof for the fourth layer: verification
that is not the author.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_present.py

blender_power gained three things this test pins:

  · view='section' — an ORTHO camera standing ON the cut plane with the near
    clip at 1 cm, so everything behind the cut is not drawn. It is the view a
    stair running through slabs shows up in, and its pixels must therefore NOT
    be the pixels of the 'front' elevation of the same building.
  · present_sig(d) — a fingerprint of what was drawn. The done gate compares it
    with the signature present() stored; the NAME is a contract.
  · present() — one build, five renders (approach / section / elevation /
    aerial / lobby) and a reply made of NUMBERS: records in frame, the tallest
    of them, whether the door is in the approach frame, and the design check.

Assistant + Blender only (the family adds no kinds). Everything renders at
workbench 640x360 so the whole file stays inside two minutes.
"""

import base64
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, kinds_of, tool_names, BLENDER  # noqa: E402

from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
BP = A.EXT_MODULES['blender_power']

T0 = time.time()
W, H = 640, 360
ENGINE = 'workbench'


def png_of(res):
    url = res[1] if isinstance(res, tuple) and len(res) == 2 else ''
    if isinstance(url, str) and url.startswith('data:image/png;base64,'):
        return base64.b64decode(url.split(',', 1)[1])
    return b''


def text_of(res):
    return res[0] if isinstance(res, tuple) else str(res)


# ── registration and the new views ───────────────────────────────────────────
print('registration')
check('present is a registered tool', 'present' in tool_names(), tool_names()[-8:])
check("VIEWS carries 'section' and the two missing elevations", {'section', 'back', 'left'} <= set(BP.VIEWS), BP.VIEWS)
check('blender is installed', os.path.exists(BLENDER), BLENDER)
check(
    "present's tool description states the done rule",
    any(
        t.get('name') == 'present' and 'done requires present() after the last drawing change' in t['description']
        for t, _fn in BP.TOOLS
    ),
    [t.get('name') for t, _fn in BP.TOOLS],
)
check(
    "blender_render's description names the section and the interior view",
    any(
        t.get('name') == 'blender_render' and 'section' in t['description'] and 'from_cell/to_cell' in t['description']
        for t, _fn in BP.TOOLS
    ),
    '',
)

# ── refusals: no Blender launch ──────────────────────────────────────────────
print('refusals')
empty = A.Drawing({'objects': []})
txt = A.call_tool(empty, 'present', {})
check('present on an empty drawing is refused', str(txt).startswith('refused') and 'empty' in txt, txt)
check('the refusal names the call that works', 'draw_box' in str(txt), txt)
txt = A.call_tool(empty, 'blender_render', {'view': 'section', 'axis': 'diagonal'})
check('an unknown section axis is refused', str(txt).startswith('refused') and 'axis must be' in str(txt), txt)

# ── the fixture: a 10 x 8 m box, 2 storeys, with a double door in the south ──
print('fixture')
d = A.Drawing({'objects': []})
made = A.call_tool(d, 'draw_box', {'cell_from': 'A1', 'cell_to': 'J8', 'storeys': 2, 'slabs': True, 'roof': 'flat'})
GROUP = made.split('"')[1] if '"' in made else ''
txt = A.call_tool(d, 'add_opening', {'group': GROUP, 'side': 'south', 'storey': 0, 'kind': 'double_door'})
check(
    'the box is drawn with a south double door',
    kinds_of(d).get('wall') == 8 and kinds_of(d).get('double_door') == 1,
    (made[:80], txt, kinds_of(d)),
)
door = BP._entrance_door(d)
check(
    'the entrance door is found on the ground floor',
    door is not None and door['kind'] == 'double_door' and door['y'] < 0.5,
    door,
)
ax = BP._door_axis(d, door) if door else None
check(
    'the door axis points OUT of the building (south, +z)',
    ax is not None and abs(ax[0] - door['x']) < 1e-6 and ax[3] > 0.5,
    ax,
)

# ── the cut is not the elevation ─────────────────────────────────────────────
print('section')
t = time.time()
res = A.call_tool(d, 'blender_render', {'view': 'section', 'axis': 'x', 'engine': ENGINE, 'width': W, 'height': H})
sec = png_of(res)
print('    section %.1fs — %s' % (time.time() - t, text_of(res)[:160]))
check('section renders a PNG', sec[:4] == b'\x89PNG' and len(sec) > 2048, (sec[:8], len(sec), text_of(res)[:300]))
check(
    'the reply says which plane was cut and which way it looks',
    'x = ' in text_of(res) and 'looking east' in text_of(res),
    text_of(res)[:200],
)

t = time.time()
res = A.call_tool(d, 'blender_render', {'view': 'front', 'engine': ENGINE, 'width': W, 'height': H})
front = png_of(res)
print('    front   %.1fs' % (time.time() - t))
check('front renders a PNG', front[:4] == b'\x89PNG' and len(front) > 2048, (front[:8], len(front)))
check(
    'the section is NOT the front elevation — the bytes differ',
    bool(sec) and bool(front) and sec != front,
    (len(sec), len(front)),
)

# ── present_sig: a fingerprint of what was drawn ─────────────────────────────
print('present_sig')
sig0 = BP.present_sig(d)
check('present_sig is a sha1 hex digest', isinstance(sig0, str) and len(sig0) == 40, sig0)
check('present_sig is stable across calls', BP.present_sig(d) == sig0, (sig0, BP.present_sig(d)))

# ── present(): five views, one build ─────────────────────────────────────────
print('present')
d.images.clear()
t = time.time()
rep = A.call_tool(d, 'present', {'engine': ENGINE, 'width': W, 'height': H})
print('    present %.1fs' % (time.time() - t))
print('    ' + '\n    '.join(str(rep).splitlines()))
check('present is not refused', not str(rep).startswith('refused'), str(rep)[:300])
check('five pictures reach the chat', len(d.images) == 5, [i.get('title') for i in d.images])
check(
    'they are the five named views',
    [i.get('title') for i in d.images] == list(BP.PRESENT_VIEWS),
    [i.get('title') for i in d.images],
)
check(
    'every picture is a real PNG',
    all(base64.b64decode(i['data_url'].split(',', 1)[1])[:4] == b'\x89PNG' for i in d.images),
    [len(i['data_url']) for i in d.images],
)
check("the reply answers 'door in frame'", 'door in frame' in str(rep), str(rep)[:400])
check('the reply carries the design check', 'design check' in str(rep), str(rep)[-400:])
check(
    'the reply counts records in frame for every view',
    all(('%s: ' % v) in str(rep) and 'record' in str(rep) and ' in frame' in str(rep) for v in BP.PRESENT_VIEWS),
    str(rep)[:600],
)
check(
    'the section line reports slabs crossed without an opening',
    'stairs/shafts crossing slabs without an opening' in str(rep),
    [l for l in str(rep).splitlines() if l.startswith('section')],
)
check('the reply names the files it wrote', '.png' in str(rep), str(rep)[:300])
check(
    "the reply judges nothing — the word 'good' does not appear",
    'good' not in str(rep).lower(),
    [l for l in str(rep).splitlines() if 'good' in l.lower()],
)

# ── the receipt the done gate reads ──────────────────────────────────────────
print('the receipt')
pres = d.ext.get('presented') or {}
check(
    "d.ext['presented'] holds the signature of what was shown",
    pres.get('sig') == BP.present_sig(d),
    (pres.get('sig'), BP.present_sig(d)),
)
check(
    "d.ext['presented'] lists the views and a timestamp",
    list(pres.get('views') or []) == list(BP.PRESENT_VIEWS) and len(str(pres.get('ts') or '')) >= 19,
    pres,
)
d.new('column_rect', {'w': 0.4, 'd': 0.4, 'h': 2.7}, -145.0, -146.0, 0.0)
check(
    'one more record changes the signature — the receipt goes stale',
    BP.present_sig(d) != pres.get('sig'),
    (BP.present_sig(d), pres.get('sig')),
)

check('the whole test stayed under 4 minutes', time.time() - T0 < 240, round(time.time() - T0, 1))
finish()
