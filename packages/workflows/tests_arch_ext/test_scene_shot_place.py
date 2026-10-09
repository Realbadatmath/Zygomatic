# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_scene_shot_place.py — proof for the one-click hop from
the VFX Studio's library into the Architecture Studio's shot.

The question this closes is the operator's, not the code's: *I am browsing a
volume pack — what does it look like in the city?*  Before this there was no
answer that did not involve typing a record by hand into the Shot sheet.  The
path now is: the studio parks the shot you opened in
``data/architecture/shots/current.json``; the VFX Studio's **Place in 3D scene**
act reads that, posts the browsed pack in as a camera-relative effect, and tells
you to press Draft.

So three things have to be true, and each can be true while the others are not:

  · the bridge has a CURRENT shot — set_current writes it, current reads it
    back, and a shot that does not exist is refused rather than parked
  · add_effect takes the record the dock action sends (2 m in front of the
    camera, 3 m across) and STORES the `rel` — it is resolved to a world point
    by the draft, not flattened on the way to disk
  · the act itself exists in the VFX Studio: f_place3d is in the ops payload the
    page draws its bars from, in the File section, video-side, and the page
    wires it to vfPlace3D

Everything is HTTP against the live :8899 server plus one headless page load.
No Blender, no GPU.  The fixture shot is left exactly as it was found.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, browser_eval, server_ext  # noqa: E402
from zyg_workflows.net import safe_urlopen  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = 'fixture_house'
SHOTS_DIR = os.path.join(HERE, 'data', 'architecture', 'shots')
CURRENT_JSON = os.path.join(SHOTS_DIR, 'current.json')
SHOT_JSON = os.path.join(SHOTS_DIR, FIXTURE, 'shot.json')
PAGE = os.path.join(HERE, 'inspection.html')
FX_ID = 'fx_smallcampfirevdb'
PACK = 'SmallCampfireVDB.zip'


def ext(op, payload=None, **kw):
    return server_ext('scene_shot', op, payload or {}, **kw)


def get_json(url):
    with safe_urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))


# what was here before us, so the fixture goes back untouched
was_current = (ext('current') or {}).get('id') or ''
shot_mtime = os.path.getmtime(SHOT_JSON) if os.path.isfile(SHOT_JSON) else None

# ── the current shot ──────────────────────────────────────────────────────
cur0 = ext('current')
check(
    'the bridge answers "which shot is open?" with an id and where it keeps it',
    cur0.get('ok') is True and 'id' in cur0 and cur0.get('path') == CURRENT_JSON,
    cur0,
)

bad_id = ext('set_current', {'id': 'Not A Shot Id'})
check(
    'an id that is not a shot id is refused before anything is written',
    bad_id.get('code') == 400 and 'must match' in (bad_id.get('error') or ''),
    bad_id,
)

missing = ext('set_current', {'id': 'no_such_shot_here'})
check('a well-formed id with no shot behind it is a 404, not a dangling pointer', missing.get('code') == 404, missing)

sc = ext('set_current', {'id': FIXTURE})
check(
    'set_current parks the fixture shot in shots/current.json',
    sc.get('ok')
    and sc.get('id') == FIXTURE
    and os.path.isfile(CURRENT_JSON)
    and json.load(open(CURRENT_JSON, encoding='utf-8')).get('id') == FIXTURE,
    sc,
)

cur = ext('current')
check(
    'current reads that id back — this is what the VFX dock action asks for',
    cur.get('ok') and cur.get('id') == FIXTURE,
    cur,
)

lst = ext('list')
check(
    'current.json sits in the shots directory without being mistaken for a shot',
    lst.get('ok')
    and 'current' not in [r['id'] for r in lst.get('shots') or []]
    and FIXTURE in [r['id'] for r in lst.get('shots') or []],
    [r['id'] for r in lst.get('shots') or []],
)

# ── the record the dock action sends ──────────────────────────────────────
ext('remove_effect', {'id': FIXTURE, 'effect_id': FX_ID})  # a re-run starts clean
before = [e.get('id') for e in (ext('get', {'id': FIXTURE})['shot'].get('effects') or [])]

RECORD = {
    'id': FX_ID,
    'pack': PACK,
    'size_m': 3.0,
    'start_frame': 1,
    'loop': True,
    'rel': {'to': 'camera', 'dx': 0, 'dy': 0, 'dz': 2},
}
add = ext('add_effect', {'id': cur['id'], 'effect': dict(RECORD)})
check('add_effect takes the volume 2 m in front of the camera at a 3 m size', add.get('ok') is True, add)

shot = ext('get', {'id': FIXTURE}).get('shot') or {}
placed = [e for e in shot.get('effects') or [] if e.get('id') == FX_ID]
fx = placed[0] if placed else {}
check(
    'the effect is in the shot on disk, under the id the browsed pack gave it',
    len(placed) == 1
    and fx.get('pack') == PACK
    and fx.get('size_m') == 3.0
    and fx.get('start_frame') == 1
    and fx.get('loop') is True,
    fx,
)
check(
    'the placement is STORED as camera-relative — resolve_positions is the draft\u2019s '
    'job, not a flattening on the way to disk',
    fx.get('rel') == {'to': 'camera', 'dx': 0, 'dy': 0, 'dz': 2} and 'p' not in fx,
    fx,
)
check(
    'nothing that was already in the shot was disturbed',
    [e.get('id') for e in shot.get('effects') or []] == before + [FX_ID],
    [e.get('id') for e in shot.get('effects') or []],
)

again = ext('add_effect', {'id': FIXTURE, 'effect': dict(RECORD)})
check(
    'pressing the icon twice on the same pack is a 409, not a second copy in the same place',
    again.get('code') == 409,
    again,
)

# the draft would resolve it: prove the stored rel is enough to place it
sys.path.insert(0, HERE)
from zyg_workflows import scene_shot as SS  # noqa: E402

res = SS.resolve_positions(shot)
cam1 = SS.camera_at(shot, 1)
rfx = [e for e in res['effects'] if e['id'] == FX_ID][0]
fwd = SS.camera_basis(cam1)[2]
want = [cam1['p'][i] + 2.0 * fwd[i] for i in range(3)]
check(
    'the stored rel resolves to a point 2 m in FRONT of the camera on frame 1, not to the '
    'world origin the operator cannot see',
    'rel' not in rfx
    and max(abs(rfx['p'][i] - want[i]) for i in range(3)) < 1e-9
    and max(abs(rfx['p'][i] - cam1['p'][i]) for i in range(3)) > 0.1,
    {'cam': cam1['p'], 'fx': rfx.get('p'), 'want': want},
)

# ── the act in the VFX Studio ─────────────────────────────────────────────
ops = get_json('http://127.0.0.1:8899/inspect/api/vfx/fx/ops')
rows = [o for s in ops.get('sections') or [] for o in s.get('items') or [] if o.get('id') == 'f_place3d']
row = rows[0] if rows else {}
check(
    'f_place3d is in the ops payload the VFX bars are drawn from, once',
    len(rows) == 1,
    [o.get('id') for s in ops.get('sections') or [] for o in s.get('items') or []][-6:],
)
check(
    'it is a File act on the dock bar, video-side, with a label, a tip and an icon',
    row.get('sec') == 'File'
    and row.get('bar') == 'dock'
    and row.get('act') is True
    and row.get('tog') is False
    and row.get('kinds') == 'v'
    and row.get('lb') == 'Place in 3D scene'
    and 'current.json' in (row.get('tip') or '')
    and len(row.get('svg') or '') > 40,
    row,
)
print('  ops row: ' + json.dumps(row, sort_keys=True))

with open(PAGE, 'r', encoding='utf-8') as fh:
    page = fh.read()
check(
    'the page wires the act to vfPlace3D in vfTool\u2019s acts map',
    'f_place3d:vfPlace3D' in page and page.count('function vfPlace3D(') == 1,
    '',
)

# forget which shot is open, so the studio's own sheet has to say it again
os.remove(CURRENT_JSON)
check(
    'with current.json gone the bridge reports no current shot rather than an error',
    (ext('current') or {}).get('ok') is True and (ext('current') or {}).get('id') == '',
    ext('current'),
)

r = browser_eval(
    """async () => {
  const out = {};
  out.fn = (typeof vfPlace3D === 'function');
  const cur = () => fetch('/inspect/api/architecture/ext/scene_shot/current',
    {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'})
    .then(x => x.json()).then(d => d.id);
  const el = document.getElementById('vf-toast');
  /* no library row is selected on a cold tab: the act must say so, not throw */
  vfPlace3D();
  await new Promise(r => setTimeout(r, 300));
  out.toast = el ? el.innerHTML : '';
  out.warned = !!(el && el.className.indexOf('warn') >= 0);
  out.before = await cur();
  /* opening a shot in the Shot sheet is what makes it the current one */
  await window.SSH_open('%s');
  out.opened = window.SSH.shot && window.SSH.shot.id;
  await new Promise(r => setTimeout(r, 800));
  out.after = await cur();
  return out;
}"""
    % FIXTURE
)
v = r['value'] or {}
check(
    'the page has the function and it refuses politely when no element is picked',
    v.get('fn') is True and v.get('warned') is True and 'element' in (v.get('toast') or ''),
    v,
)
check(
    'opening a shot in the Shot sheet is what parks it as current — the VFX act never '
    'has to be told which shot the operator is editing',
    v.get('before') == '' and v.get('opened') == FIXTURE and v.get('after') == FIXTURE,
    v,
)
check('no page errors while the act and the sheet ran', not r['errors'], r['errors'])

# ── leave the fixture as we found it ──────────────────────────────────────
rm = ext('remove_effect', {'id': FIXTURE, 'effect_id': FX_ID})
after = [e.get('id') for e in ((rm.get('shot') or {}).get('effects') or [])]
if shot_mtime is not None:
    os.utime(SHOT_JSON, (shot_mtime, shot_mtime))  # or the fixture .blend reads as stale
if was_current:
    ext('set_current', {'id': was_current})
check(
    'the fixture shot is back to the effects it had, with its .blend still current',
    rm.get('ok') and after == before and (shot_mtime is None or os.path.getmtime(SHOT_JSON) == shot_mtime),
    after,
)

finish()
