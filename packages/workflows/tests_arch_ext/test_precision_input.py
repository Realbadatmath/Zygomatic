# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_precision_input.py — proves the five Precision icons
(pr_angle, pr_axis, pr_plane, pr_coord, pr_guide) stopped being placeholders and
that each one does what its tooltip promises.

Two headless page loads: icon_state for the placeholder marks, and ONE batched
browser_eval that exercises every mechanism on the live document — the snap hook
(angle snap, axis lock, typed point), the frame hook (rotate snap, axis lock
during a move drag), the work plane, the synthetic click behind "type it", the
digit keys, and hide/show/clear on the guides. Assertions are on records and
numbers only.
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import assistant, browser_eval, check, finish, icon_state  # noqa: E402

IDS = ['pr_angle', 'pr_axis', 'pr_plane', 'pr_coord', 'pr_guide']

st = icon_state(IDS)
check(
    'all five Precision icons exist and are no longer placeholders '
    '(no stub flag, no dashed class, no [placeholder] tip)',
    all(
        st.get(i, {}).get('exists')
        and not st[i].get('stub')
        and not st[i].get('dashed')
        and not st[i].get('tip_placeholder')
        for i in IDS
    ),
    st,
)

JS = r"""() => {
  const R = {};
  const S = () => (AR.doc.ext && AR.doc.ext.precision_input) || {};
  const tick = () => AR_EXT.ticks.forEach(f => f());
  const deg = (ax, az, bx, bz) => (Math.atan2(-(bz - az), bx - ax) * 180 / Math.PI + 360) % 360;
  try {
    AR.doc.ext = {};
    AR.snapOn = false;                      // the grid must not move a typed point

    /* ── pr_angle (a): drafting rounds the direction to the increment ── */
    arToolApply('wall');
    arTool('pr_angle', {deg: 45});
    R.angle_state = [S().angle, !!S().angle_on, !!AR_EXT.tools.pr_angle.on()];
    AR.draft = {tool: 'wall', a: {x: 0, z: 0, y: 0}, chain: 0};
    const p1 = arExtSnap({x: 3, z: -0.5, y: 0}, null, null);
    const p2 = arExtSnap({x: 0.4, z: -3, y: 0}, null, null);
    R.snap_deg = [deg(0, 0, p1.x, p1.z), deg(0, 0, p2.x, p2.z)];
    R.snap_len = [Math.hypot(p1.x, p1.z), Math.hypot(p2.x, p2.z)];
    R.snap_tag = p1.snap;
    arCancelDraft();

    /* ── pr_angle (b): a rotate drag step lands on the increment ── */
    const rot = arNewObj('slab', {w: 2, d: 1, t: 0.2}, 20, 0, 0);
    arSelect([rot.id]); arToolApply('rotate');
    tick();                                  // frame 1: remember ry
    rot.ry = 0.5; arApplyTransform(rot);      // a drag step (28.6 deg)
    tick();                                  // frame 2: re-round to 45 deg
    R.rot_deg = rot.ry * 180 / Math.PI;

    /* ── pr_axis: drafting projects onto the axis line through draft.a ── */
    arToolApply('wall');
    arTool('pr_axis', {axis: 'x'});
    R.axis_state = [S().axis, !!AR_EXT.tools.pr_axis.on()];
    AR.draft = {tool: 'wall', a: {x: 1, z: 2, y: 0}, chain: 0};
    const q = arExtSnap({x: 7, z: 9, y: 0}, null, null);
    R.axis_pt = [q.x, q.z, q.snap];
    arCancelDraft();

    /* ── pr_axis: a move drag keeps the locked coordinate ── */
    const mv = arNewObj('slab', {w: 2, d: 2, t: 0.2}, 0, 0, 0);
    arSelect([mv.id]); arToolApply('move');
    tick();                                  // frame 1: base = (0, 0, 0)
    mv.x = 4; mv.z = 3; arApplyTransform(mv);  // a drag step off the axis
    tick();
    R.move_pt = [mv.x, mv.y, mv.z];

    /* ── pr_axis: the keyboard binding ── */
    AR_EXT.keys['shift+x']({key: 'X', shiftKey: true});   // already x -> off
    R.key_off = S().axis;
    AR_EXT.keys['shift+z']({key: 'Z', shiftKey: true});
    R.key_z = S().axis;
    arTool('pr_axis', {axis: 'off'});
    R.axis_cleared = S().axis;

    /* ── pr_plane: the drawing plane goes onto a slab's top face ── */
    const slab = arNewObj('slab', {w: 4, d: 4, t: 0.22}, 40, 0, 0);
    arTool('pr_plane', {rec: slab.id});
    R.plane = [AR.level, S().plane && S().plane.h, S().plane && S().plane.rec === slab.id,
               !!AR_EXT.tools.pr_plane.on()];
    arTool('pr_plane');                       // a second press returns to the ground
    R.plane_off = [AR.level, S().plane, !!AR_EXT.tools.pr_plane.on()];
    R.plane_pick_mode = !!(AR_EXT.modes && AR_EXT.modes.pr_plane_pick);

    /* ── pr_coord: a typed length + angle completes an open draft ── */
    arSetLevel(0);
    AR.cam.updateMatrixWorld(true);
    arToolApply('wall');
    AR.draft = {tool: 'wall', a: {x: 0, z: 0, y: 0}, chain: 0};
    const nb = AR.objs.length;
    arTool('pr_coord', {len: 5, angle: 90});
    const w = AR.objs[AR.objs.length - 1];
    R.typed_wall = [AR.objs.length - nb, w.kind, w.p.len, w.ry, w.x, w.z];
    arCancelDraft();

    /* ── pr_coord: with no draft it arms the NEXT click, once ── */
    arToolApply('column');
    arTool('pr_coord', {x: 12, z: -7});
    const rc = AR.renderer.domElement.getBoundingClientRect();
    const ev = (fx, fy) => ({clientX: rc.left + rc.width * fx, clientY: rc.top + rc.height * fy,
                             shiftKey: false, button: 0});
    const cb = AR.objs.length;
    arClick(ev(0.5, 0.6));
    const c1 = AR.objs[AR.objs.length - 1];
    R.typed_point = [AR.objs.length - cb, c1.kind, c1.x, c1.z];
    arClick(ev(0.42, 0.66));                  // the one-shot is spent
    const c2 = AR.objs[AR.objs.length - 1];
    R.typed_once = [AR.objs.length - cb, !(c2.x === 12 && c2.z === -7)];

    /* ── pr_coord: digits with a draft open type a length ── */
    arToolApply('line');
    AR.draft = {tool: 'line', a: {x: 50, z: 0, y: 0}, chain: 0};
    const gb = AR.objs.length;
    AR_EXT.keys['3']({key: '3'});             // prompt answers its prefill "3"
    const gl = AR.objs[AR.objs.length - 1];
    R.digit_draft = [AR.objs.length - gb, gl.kind, gl.p && gl.p.len];
    arCancelDraft();

    /* ── pr_coord: digits with NO draft still work the studio's view keys ── */
    arToolApply('select'); AR.draft = null;
    const before = [AR.cam.position.x, AR.cam.position.y, AR.cam.position.z].join(',');
    const nobj = AR.objs.length;
    AR_EXT.keys['1']({key: '1'});             // top view, unchanged behaviour
    R.digit_view = [[AR.cam.position.x, AR.cam.position.y, AR.cam.position.z].join(',') !== before,
                    AR.objs.length === nobj];

    /* ── pr_guide: hide, show, clear ── */
    const g1 = arNewObj('guide_line', {len: 6}, 60, 0, 0);
    const g2 = arNewObj('guide_circle', {r: 3}, 70, 0, 0);
    const isG = o => String(o.kind || '').indexOf('guide_') === 0;
    const nGuides = () => AR.objs.filter(isG).length;
    const gAll = nGuides();
    arTool('pr_guide', {mode: 'hide'});
    R.guide_hidden = [g1.hidden, g2.hidden, g1.node.visible, !!AR_EXT.tools.pr_guide.on()];
    arTool('pr_guide', {mode: 'show'});
    R.guide_shown = [g1.hidden, g2.hidden, g1.node.visible, !!AR_EXT.tools.pr_guide.on()];
    const undoBefore = AR.undo.length;
    arTool('pr_guide', {mode: 'clear'});
    R.guide_cleared = [gAll, nGuides(), AR.undo.length > undoBefore];

    /* ── the settings are JSON-plain and ride in the saved document ── */
    R.ext = JSON.parse(JSON.stringify(AR.doc.ext.precision_input));
    R.doc_ext = !!(arDocOut().ext || {}).precision_input;
    R.toast = document.getElementById('ar-toast').innerHTML;
  } catch (e) { R._err = String((e && e.stack) || e); }
  return R;
}"""

r = browser_eval(JS)
v = r['value']
check(
    'no page errors while pressing the five icons',
    not r['errors'] and not v.get('_err'),
    {'errors': r['errors'], '_err': v.get('_err')},
)

# ── pr_angle ───────────────────────────────────────────────────────────────
check(
    'pr_angle stores the increment in AR.doc.ext and lights because it is not 15',
    v['angle_state'] == [45, True, True],
    v.get('angle_state'),
)
check(
    'pr_angle (a) rounds a wall draft direction to the increment and keeps the drag length: '
    '(3, -0.5) -> 0 deg, (0.4, -3) -> 90 deg',
    abs(v['snap_deg'][0] % 45) < 1e-6
    and abs(v['snap_deg'][1] - 90) < 1e-6
    and abs(v['snap_len'][0] - math.hypot(3, 0.5)) < 1e-6
    and abs(v['snap_len'][1] - math.hypot(0.4, 3)) < 1e-6
    and 'angle' in str(v['snap_tag']),
    {'deg': v.get('snap_deg'), 'len': v.get('snap_len'), 'snap': v.get('snap_tag')},
)
check('pr_angle (b) a rotate drag step of 28.6 deg lands on 45 deg', abs(v['rot_deg'] - 45) < 1e-6, v.get('rot_deg'))

# ── pr_axis ────────────────────────────────────────────────────────────────
check('pr_axis latches the axis and lights', v['axis_state'] == ['x', True], v.get('axis_state'))
check(
    'pr_axis x-lock projects a draft point onto the axis line: (7, 9) -> (7, a.z=2)',
    v['axis_pt'][0] == 7 and v['axis_pt'][1] == 2 and 'X' in str(v['axis_pt'][2]),
    v.get('axis_pt'),
)
check(
    'pr_axis x-lock re-imposes z and y on the selection during a move drag: (4, 3) -> (4, 0)',
    v['move_pt'] == [4, 0, 0],
    v.get('move_pt'),
)
check(
    'shift+X toggles the lock off and shift+Z sets Z',
    v['key_off'] == 'off' and v['key_z'] == 'z' and v['axis_cleared'] == 'off',
    [v.get('key_off'), v.get('key_z'), v.get('axis_cleared')],
)

# ── pr_plane ───────────────────────────────────────────────────────────────
check(
    'pr_plane puts the drawing plane on the top face of a 0.22 m slab (AR.level == 0.22) and lights',
    abs(v['plane'][0] - 0.22) < 1e-6
    and abs(v['plane'][1] - 0.22) < 1e-6
    and v['plane'][2] is True
    and v['plane'][3] is True,
    v.get('plane'),
)
check(
    'a second press returns the plane to the ground and unlights',
    v['plane_off'] == [0, None, False],
    v.get('plane_off'),
)
check('pr_plane also arms a click-to-pick mode', v['plane_pick_mode'] is True, v.get('plane_pick_mode'))

# ── pr_coord ───────────────────────────────────────────────────────────────
tw = v['typed_wall']
check(
    'pr_coord {len:5, angle:90} completes an open wall draft: one wall, len 5, pointing -Z '
    '(ry = pi/2), centred at (0, -2.5)',
    tw[0] == 1
    and tw[1] == 'wall'
    and abs(tw[2] - 5) < 1e-6
    and abs(tw[3] - math.pi / 2) < 1e-9
    and abs(tw[4]) < 1e-6
    and abs(tw[5] + 2.5) < 1e-6,
    tw,
)
check(
    'pr_coord {x, z} with no draft sends the NEXT click to that exact point',
    v['typed_point'] == [1, 'column_rect', 12, -7],
    v.get('typed_point'),
)
check(
    'the typed point is a one-shot: the click after it drops a column where the pointer is',
    v['typed_once'] == [2, True],
    v.get('typed_once'),
)
check(
    'a digit key with a draft open types the length (guide line of 3 m)',
    v['digit_draft'] == [1, 'guide_line', 3],
    v.get('digit_draft'),
)
check(
    'a digit key with no draft still works the studio view shortcut and draws nothing',
    v['digit_view'] == [True, True],
    v.get('digit_view'),
)

# ── pr_guide ───────────────────────────────────────────────────────────────
check(
    'pr_guide hide hides every guide record and its node, and lights',
    v['guide_hidden'] == [True, True, False, True],
    v.get('guide_hidden'),
)
check('pr_guide show restores them and unlights', v['guide_shown'] == [False, False, True, False], v.get('guide_shown'))
check(
    'pr_guide clear removes every guide behind one undo step',
    v['guide_cleared'][0] >= 2 and v['guide_cleared'][1] == 0 and v['guide_cleared'][2] is True,
    v.get('guide_cleared'),
)

# ── document state ─────────────────────────────────────────────────────────
check(
    'the settings are JSON-plain and go out with the saved drawing',
    v['doc_ext'] is True and set(v['ext']) >= {'angle', 'axis', 'plane', 'guides'} and json.dumps(v['ext']),
    v.get('ext'),
)

# ── the assistant may press all five ───────────────────────────────────────
for icon, args in [
    ('pr_angle', {'deg': 45}),
    ('pr_axis', {'axis': 'x'}),
    ('pr_plane', {'rec': 'o1'}),
    ('pr_coord', {'len': 5, 'angle': 90}),
    ('pr_guide', {'mode': 'hide'}),
]:
    txt, d = assistant('press_button', {'id': icon, 'args': args})
    check(
        'the assistant may press %s with args' % icon,
        txt.startswith('pressed') and d.ui and d.ui[-1]['args']['id'] == icon and d.ui[-1]['args'].get('args') == args,
        txt,
    )

finish()
