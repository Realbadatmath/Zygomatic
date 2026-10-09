# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_scene_shot.py — proof for the scene_shot family: the
Architecture Studio's bridge from a drawing to a Blender clip.

It exercises the whole operator's path in the order a person walks it:

  · the bridge answers (info) and knows the shots on disk (list)
  · a NEW shot is made from the drawing the tab is holding, and the drawing is
    parked beside it as shots/<id>/drawing.json
  · actors and effects go in; an effect may be placed RELATIVE to an actor, and
    an actor holding one cannot quietly walk out of the shot
  · save is a validate-then-write: a round trip keeps the edit, a shot that
    breaks the contract is refused rather than saved
  · the BROWSER half registers behind the two existing icons without taking
    view_camera's behaviour away, opens the Shot sheet, and lays a walk path by
    clicking the ground — the keys land evenly across the shot's frames
  · a DRAFT of the fixture shot runs Blender for real, and the clip and its
    placement boxes come back down the media/placement routes

The draft is the slow part (one headless Blender, a few minutes); everything
else is HTTP against the live :8899 server.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, browser_eval, icon_state, server_ext  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = 'fixture_house'
DRAWING = os.path.join(HERE, 'data', 'architecture', 'projects', 'first-building-attempt.json')
PROBE = 'test_scene_shot_probe'
PROBE_DIR = os.path.join(HERE, 'data', 'architecture', 'shots', PROBE)
DRAFT_BUDGET_S = 600


def ext(op, payload=None, **kw):
    return server_ext('scene_shot', op, payload or {}, **kw)


# ── the bridge itself ─────────────────────────────────────────────────────
info = ext('info')
check(
    'the server half answers and has both Blender scripts and Blender itself',
    info.get('ok')
    and info.get('present')
    and info.get('build_py')
    and info.get('render_py')
    and info.get('schema') == 'zyg.scene_shot/1',
    info,
)

lst = ext('list')
rows = {r['id']: r for r in lst.get('shots') or []}
check(
    'list reports the shots on disk, the fixture among them with its .blend built',
    lst.get('ok') and FIXTURE in rows and rows[FIXTURE]['frames'] == 49 and rows[FIXTURE]['blend'],
    rows.get(FIXTURE) or lst,
)

# ── a new shot from the drawing the tab is holding ────────────────────────
if os.path.isdir(PROBE_DIR):
    shutil.rmtree(PROBE_DIR)
with open(DRAWING, 'r', encoding='utf-8') as fh:
    doc = json.load(fh)

new = ext('new', {'id': PROBE, 'name': 'probe shot', 'doc': doc})
shot = new.get('shot') or {}
check(
    'new makes a shot from the drawing, with the schema defaults (49 frames at 24 fps, 832x480)',
    new.get('ok')
    and shot.get('id') == PROBE
    and shot.get('frames') == 49
    and shot.get('fps') == 24
    and shot.get('resolution') == [832, 480]
    and len((shot.get('camera') or {}).get('keys') or []) == 1,
    new,
)
check(
    'the browser\u2019s drawing is parked beside the shot and pointed at, not copied by value',
    shot.get('drawing') == os.path.join(PROBE_DIR, 'drawing.json')
    and os.path.isfile(shot['drawing'])
    and len(json.load(open(shot['drawing'], encoding='utf-8'))['objects']) == len(doc['objects']),
    shot.get('drawing'),
)
check(
    'a second shot under the same id is a 409, not a silent overwrite',
    ext('new', {'id': PROBE, 'doc': doc}).get('code') == 409,
    '',
)

got = ext('get', {'id': PROBE})
check(
    'get returns the record, its validation verdict and what exists on disk',
    got.get('ok')
    and got.get('errors') == []
    and got['files']
    == {'blend': False, 'draft': False, 'full': False, 'draft_placement': False, 'full_placement': False},
    got,
)

# ── actors and effects ────────────────────────────────────────────────────
a = ext(
    'add_actor',
    {
        'id': PROBE,
        'actor': {'id': 'walker', 'char_id': 'c3345deb5bde', 'proxy': 'abel', 'height_m': 1.7, 'motion': 'cmu/02_01'},
    },
)
check(
    'add_actor puts an actor in with a standing key when no path was laid yet',
    a.get('ok')
    and [x['id'] for x in a['shot']['actors']] == ['walker']
    and a['shot']['actors'][0]['path'] == [{'f': 1, 'p': [0.0, 0.0, 0.0], 'ry': 180.0}],
    a,
)

fx = ext(
    'add_effect',
    {
        'id': PROBE,
        'effect': {
            'pack': 'SmallCampfireVDB.zip',
            'size_m': 1.5,
            'rel': {'to': 'walker', 'dx': 1.0, 'dy': 0.0, 'dz': 2.0},
        },
    },
)
eff = (fx.get('shot') or {}).get('effects') or []
check(
    'add_effect places a volume RELATIVE to an actor and names it for the operator',
    fx.get('ok')
    and len(eff) == 1
    and eff[0]['id'] == 'fx1'
    and eff[0]['rel'] == {'to': 'walker', 'dx': 1.0, 'dy': 0.0, 'dz': 2.0}
    and eff[0]['start_frame'] == 1,
    fx,
)

bad_pack = ext('add_effect', {'id': PROBE, 'effect': {'id': 'nope', 'pack': 'not_a_real_pack.zip', 'p': [0, 0, 0]}})
check(
    'an effect naming a pack that is not in the VDB library is refused before it is saved',
    bad_pack.get('code') == 400
    and 'nope' not in [e['id'] for e in (ext('get', {'id': PROBE})['shot'].get('effects') or [])],
    bad_pack,
)

gone = ext('remove_actor', {'id': PROBE, 'actor_id': 'walker'})
check(
    'an actor an effect is anchored to cannot walk out of the shot behind the operator\u2019s back',
    gone.get('code') == 409 and 'fx1' in gone.get('error', ''),
    gone,
)

# ── save is validate-then-write ───────────────────────────────────────────
edit = json.loads(json.dumps(ext('get', {'id': PROBE})['shot']))
edit['name'] = 'probe shot, renamed'
edit['frames'] = 25
saved = ext('save', {'shot': edit})
back = ext('get', {'id': PROBE})['shot']
check(
    'save round trips the edit through validate onto disk',
    saved.get('ok')
    and back['name'] == 'probe shot, renamed'
    and back['frames'] == 25
    and back['effects'][0]['rel']['to'] == 'walker',
    saved,
)

broken = json.loads(json.dumps(back))
broken['fps'] = 0
broken['actors'][0]['height_m'] = 9.0
refused = ext('save', {'shot': broken})
after = ext('get', {'id': PROBE})['shot']
check(
    'a shot that breaks the contract is refused with every reason, and disk is untouched',
    refused.get('code') == 400
    and len(refused.get('errors') or []) >= 2
    and after['fps'] == 24
    and after['actors'][0]['height_m'] == 1.7,
    refused,
)

cam = ext('set_camera_key', {'id': PROBE, 'key': {'f': 25, 'p': [6, 1.7, 14], 't': [6, 1.5, 4], 'fov': 40}})
keys = ((cam.get('shot') or {}).get('camera') or {}).get('keys') or []
check(
    'set_camera_key adds a second key and keeps the keys in frame order',
    cam.get('ok') and [k['f'] for k in keys] == [1.0, 25.0] and keys[1]['fov'] == 40.0,
    cam,
)

# ── the catalogues the sheet fills its pickers from ───────────────────────
mo = ext('motions')
ac = ext('actors_available')
check(
    'the sheet can offer motions and proxy actors that really have a .blend',
    mo.get('ok')
    and len(mo.get('motions') or []) > 0
    and ac.get('ok')
    and any(r['id'] == 'abel' and os.path.isfile(r['blend']) for r in ac.get('actors') or []),
    {'motions': len(mo.get('motions') or []), 'actors': [r['id'] for r in ac.get('actors') or []]},
)

# ── the browser half ──────────────────────────────────────────────────────
st = icon_state(['r_anim', 'v_walkpath'])
check(
    'both icons are live in the dock and neither is a placeholder any more',
    all(
        st[i].get('exists') and not st[i].get('stub') and not st[i].get('dashed') and not st[i].get('tip_placeholder')
        for i in ('r_anim', 'v_walkpath')
    ),
    st,
)

r = browser_eval(
    """async () => {
  const out = {sel_after: null};
  const anim = AR_EXT.tools.r_anim, walk = AR_EXT.tools.v_walkpath, mode = AR_EXT.modes.v_walkpath;
  out.registered = !!(anim && anim.act && walk && walk.act && mode && mode.click && mode.hint && mode.cancel);
  out.globals = ['SSH_open','SSH_new','SSH_fxAdd','SSH_actorAdd','SSH_camKey','SSH_run','SSH_pathArm']
                  .every(n => typeof window[n] === 'function');
  /* view_camera still owns its own argument shapes on both ids */
  walk.act({mode: 'clear'});
  out.chained = (window.SSH.actor === '') && (AR.tool !== 'v_walkpath') && (typeof walk.on === 'function');
  out.labels_off = (window.SSH.labels === false);

  await anim.act({shot: '%s'});
  out.shot = window.SSH.shot && window.SSH.shot.id;
  out.title = (document.querySelector('.ar-sheet .sh') || {}).textContent || '';
  out.fx_rows = document.querySelectorAll('tr.ssh-fx').length;
  out.actor_rows = document.querySelectorAll('tr.ssh-actor').length;
  out.packs = window.SSH.packs.length;
  out.proxies = window.SSH.proxies.length;
  out.motions = window.SSH.motions.length;
  out.has_buttons = ['Build','Draft','Full'].every(t => document.querySelector('.ar-sheet').innerHTML.indexOf('>' + t + '<') >= 0);

  /* lay a walk path: arm the mode from the actor row, click the ground, Esc */
  out.armed = window.SSH_pathArm('walker');
  out.tool = AR.tool;
  out.hint = mode.hint();
  mode.click({x: 2, y: 0, z: 10});
  mode.click({x: 2, y: 0, z: 4});
  mode.click({x: 8, y: 0, z: 4});
  out.marks = window.SSH.marks ? window.SSH.marks.children.length : 0;
  out.sprites = window.SSH.marks ? window.SSH.marks.children.filter(o => o.isSprite).length : -1;
  mode.cancel();
  await new Promise(r => setTimeout(r, 2500));
  out.path = (((window.SSH.shot || {}).actors || [])[0] || {}).path || null;
  out.after_tool = AR.tool;
  out.sel_after = AR.sel.length;
  return out;
}"""
    % PROBE
)
v = r['value'] or {}
check(
    'the family registers behind both icons and keeps view_camera\u2019s own calls working',
    v.get('registered') and v.get('globals') and v.get('chained'),
    v,
)
check(
    'the Shot sheet opens on the named shot and shows its effects, actors and the three render buttons',
    v.get('shot') == PROBE and v.get('fx_rows') == 1 and v.get('actor_rows') == 1 and v.get('has_buttons'),
    v,
)
check(
    'its pickers are filled from the live catalogues (volume packs, proxy actors, motions)',
    (v.get('packs') or 0) > 0 and (v.get('proxies') or 0) > 0 and (v.get('motions') or 0) > 0,
    v,
)
check(
    'walk path arms the pointer mode on the chosen actor and says so in the hint',
    v.get('armed') == 'walker' and v.get('tool') == 'v_walkpath' and 'walker' in (v.get('hint') or ''),
    v,
)
check(
    'three ground clicks become three keys spaced evenly over the shot\u2019s 25 frames',
    isinstance(v.get('path'), list) and [k['f'] for k in v['path']] == [1, 13, 25] and v['path'][0]['p'] == [2, 0, 10],
    v.get('path'),
)
check(
    'the point markers draw no label sprites while the label switch is off',
    v.get('labels_off') and (v.get('marks') or 0) > 0 and v.get('sprites') == 0,
    v,
)
check('nothing in the drawing was auto-selected by any of it', v.get('sel_after') == 0, v)
check('no page errors while the sheet and the path mode ran', not r['errors'], r['errors'])

server_path = ext('get', {'id': PROBE})['shot']['actors'][0]['path']
check('the path the browser laid is what the server saved', [k['f'] for k in server_path] == [1, 13, 25], server_path)

# ── the slow half: one real draft of the fixture ──────────────────────────
no_media = ext('media', {'id': PROBE, 'kind': 'draft'})
check(
    'asking for a clip that has not been rendered yet is a 404, not an empty file',
    no_media.get('code') == 404,
    no_media,
)

d = ext('draft', {'id': FIXTURE})
check(
    'draft starts one Blender job and says whether it had to rebuild the .blend first',
    d.get('ok') and d['job']['kind'] == 'draft' and d['job']['shot'] == FIXTURE and d.get('rebuilt') is False,
    d,
)
busy = ext('draft', {'id': FIXTURE})
check(
    'a second Blender job while one runs is a 409 — one Blender at a time',
    busy.get('code') == 409 and busy.get('job') == d['job']['id'],
    busy,
)

jid, t0, job = d['job']['id'], time.time(), {}
while time.time() - t0 < DRAFT_BUDGET_S:
    job = (ext('job', {'jid': jid}) or {}).get('job') or {}
    if job.get('state') in ('done', 'failed'):
        break
    time.sleep(5)
check(
    'the draft of the fixture shot finishes inside %d s' % DRAFT_BUDGET_S,
    job.get('state') == 'done' and (job.get('result') or {}).get('ok') and job['result'].get('frames') == 49,
    {
        'state': job.get('state'),
        'seconds': job.get('seconds'),
        'error': job.get('error'),
        'log': (job.get('log') or [])[-6:],
    },
)

m = ext('media', {'id': FIXTURE, 'kind': 'draft'})
data = m.get('bytes') or b''
probe = ''
if data:
    tmp = os.path.join(tempfile.gettempdir(), 'scene_shot_media_probe.mp4')
    with open(tmp, 'wb') as fh:
        fh.write(data)
    probe = subprocess.run(
        [
            'ffprobe',
            '-v',
            'error',
            '-select_streams',
            'v:0',
            '-count_frames',
            '-show_entries',
            'stream=width,height,nb_read_frames',
            '-of',
            'csv=p=0',
            tmp,
        ],
        capture_output=True,
        text=True,
    ).stdout.strip()
    os.remove(tmp)
check(
    'media sends the whole clip down as an mp4 the browser can play inline',
    m.get('mime') == 'video/mp4'
    and m.get('filename') == '%s_draft.mp4' % FIXTURE
    and data[4:8] == b'ftyp'
    and probe == '320,180,49'
    and len(data) > 4000,
    {'mime': m.get('mime'), 'bytes': len(data), 'filename': m.get('filename'), 'ffprobe': probe},
)

pl = (ext('placement', {'id': FIXTURE, 'kind': 'draft'}) or {}).get('placement') or {}
frames = pl.get('frames') or []
f1 = frames[0] if frames else {}
check(
    'placement carries a box for every one of the 49 frames, in pixels the tab can draw over the clip',
    len(frames) == 49
    and pl.get('n_frames') == 49
    and pl.get('width') == 320
    and pl.get('pixel_origin') == 'top-left, y down'
    and len((f1.get('effects') or {}).get('fire1', {}).get('bbox_px') or []) == 4
    and len((f1.get('actors') or {}).get('abel', {}).get('ground_px') or []) == 2,
    {'n': len(frames), 'first': f1},
)

bad_kind = ext('placement', {'id': FIXTURE, 'kind': 'sideways'})
check('a kind that is neither draft nor full is refused', bad_kind.get('code') == 400, bad_kind)

if os.path.isdir(PROBE_DIR):
    shutil.rmtree(PROBE_DIR)
check('the probe shot cleans up after itself', not os.path.isdir(PROBE_DIR), PROBE_DIR)

finish()
