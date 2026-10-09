# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""view_scene_ops — the assistant's viewport tools (no new kinds).

Nothing here draws: every tool appends ONE command to `d.ui`, the channel the
tab replays with arAssistUi() AFTER the drawing has been injected. So these are
what the user SEES (camera, cell labels, grid, sun, section, selection, toasts,
save, and the studio's own dock buttons), never what the drawing IS. No record
is created or edited, so the arch_assistant.MAX_OBJECTS ceiling is never moved
by this family; the id lists handed to the tab are capped instead (the tab's own
select cap is 200).

Tools: set_view, focus, select, show_cells, show_grid, set_storey_plane,
set_sun, section, hide_objects, show_all, save_drawing, press_button, say.
"""

from __future__ import annotations

import json

from zyg_workflows.arch_assistant import Drawing, MAX_OBJECTS, _num

KINDS: dict = {}
OPENINGS: list = []

VIEWS = ('top', 'front', 'right', 'iso', 'back', 'left', 'bottom')
ID_CAP = 200  # arAssistUi's select cap; also used for focus/hide

# The dock/side buttons arAssistUi will press — kept in step with
# `var AR_ASSIST_TOOLS` in inspection.html. Anything else is refused here so
# the model never learns to fire a button the tab silently drops.
BUTTONS = (
    'v_top',
    'v_front',
    'v_right',
    'v_iso',
    'v_back',
    'v_left',
    'v_bottom',
    'v_selfit',
    'v_prev',
    'v_next',
    'v_save',
    'v_go',
    'd_grid',
    'd_axes',
    'd_sky',
    'd_fog',
    'd_hud',
    'd_cells',
    'l_soft',
    'l_amb',
    'l_expo',
    'pr_up',
    'pr_dn',
    'pr_zero',
    'o_isolate',
    'o_lock',
    'o_unlock',
    's_all',
    's_none',
    's_invert',
    's_same_mat',
    's_same_kind',
    'e_cut',
    'e_copy',
    'e_paste',
    'e_pastep',
    'undo',
    'redo',
    'del',
    'dupe',
    'mirror',
    'array',
    'group',
    'ungroup',
    'q_stats',
    'q_area',
    'q_bom',
    'f_obj',
    'f_shot',
    'f_json',
    'f_blend',
    'zoomfit',
    'section',
    't_snap',
    't_ortho',
    't_sun',
    't_wire',
    'p_gpu',
    'hide',
    'showall',
    'select',
    'orbit',
    'pan',
)

PROMPT = (
    'View ops (viewport effects, not drawing edits; run after injection): '
    'set_view(top/front/right/iso/back/left/bottom); focus(which) frames it; select(which) highlights; '
    'show_cells(on); show_grid(on); set_storey_plane(storey); set_sun(hour 0-24); '
    'section(storey) cuts a plan section, section() off; hide_objects(which,hidden); show_all(); '
    'save_drawing(name); say(text) toasts; press_button(id) presses: '
    'views v_top/v_front/v_right/v_iso/v_back/v_left/v_bottom/v_selfit, '
    'display d_grid/d_axes/d_sky/d_fog/d_hud/d_cells, light l_soft/l_amb/l_expo, '
    'precision pr_up/pr_dn/pr_zero, organise o_isolate/o_lock/o_unlock, '
    'select s_all/s_none/s_invert/s_same_mat/s_same_kind, '
    'edit e_cut/e_copy/e_paste/e_pastep/undo/redo/del/dupe/mirror/array/group/ungroup, '
    'reports q_stats/q_area/q_bom, export f_obj/f_shot/f_json/f_blend, '
    'misc zoomfit/section/t_snap/t_ortho/t_sun/t_wire/p_gpu; other ids refused.'
)


def _ids(d: Drawing, which, cap=ID_CAP):
    recs = d.select(which if which not in (None, '') else 'new')
    return [o['id'] for o in recs[:cap]], len(recs)


def t_set_view(d: Drawing, a, view='iso'):
    v = str(view or '').strip().lower()
    if v not in VIEWS:
        return 'refused: view must be one of ' + '/'.join(VIEWS)
    d.ui.append({'cmd': 'view', 'args': {'view': v}})
    return f'viewport set to the {v} view'


def t_focus(d: Drawing, a, which='new'):
    ids, n = _ids(d, which)
    if not ids and str(which or 'new') not in ('all', 'new'):
        return f'refused: nothing matches "{which}" to focus on'
    d.ui.append({'cmd': 'focus', 'args': {'ids': ids}})
    return (
        f'framed {len(ids)} object(s)'
        + (f' of {n}' if n > len(ids) else '')
        + (f' ({ids[0]}..{ids[-1]})' if ids else ' — zoomed to fit')
    )


def t_select(d: Drawing, a, which='new'):
    ids, n = _ids(d, which)
    if not ids:
        return f'refused: nothing matches "{which}" to select'
    d.selected = list(ids)
    d.ui.append({'cmd': 'select', 'args': {'ids': ids}})
    return f'selected {len(ids)} object(s)' + (f' of {n}' if n > len(ids) else '') + f': {ids[0]}..{ids[-1]}'


def t_show_cells(d: Drawing, a, on=True):
    d.ui.append({'cmd': 'cells', 'args': {'on': bool(on)}})
    return 'cell labels ' + ('on — the grid names are painted around the view' if on else 'off')


def t_show_grid(d: Drawing, a, on=True):
    d.ui.append({'cmd': 'grid', 'args': {'on': bool(on)}})
    return 'ground grid ' + ('on' if on else 'off')


def t_set_storey_plane(d: Drawing, a, storey=0):
    n = _num(storey, None)  # sentinel: _num falls back silently, so 'top' must not read as 0
    if n is None:
        return f'refused: storey must be a number, not "{storey}"'
    s = int(n)
    if s < 0 or s > 400:
        return 'refused: storey must be between 0 and 400'
    d.ui.append({'cmd': 'storey', 'args': {'storey': s}})
    return f'working plane moved to storey {s} ({s * d.storey_h:g} m)'


def t_set_sun(d: Drawing, a, hour=12):
    h = _num(hour, -1)
    if h < 0 or h > 24:
        return 'refused: hour must be between 0 and 24'
    h = round(h, 2)
    if h == int(h):  # a whole hour travels as 14, not 14.0
        h = int(h)
    d.ui.append({'cmd': 'sun', 'args': {'hour': h}})
    return f'sun set to {h:g}:00'


def t_section(d: Drawing, a, storey=None):
    if storey is None or storey == '':
        d.ui.append({'cmd': 'section', 'args': {'storey': None}})
        return 'section cut off — the model is whole again'
    n = _num(storey, None)
    if n is None:
        return f'refused: storey must be a number, not "{storey}" — leave it out to switch the section off'
    s = int(n)
    if s < 0 or s > 400:
        return 'refused: storey must be between 0 and 400, or leave it out to switch the section off'
    d.ui.append({'cmd': 'section', 'args': {'storey': s}})
    return f'section cut just under the top of storey {s} — a plan through that floor'


def t_hide_objects(d: Drawing, a, which='new', hidden=True):
    ids, n = _ids(d, which, cap=min(MAX_OBJECTS, 2000))
    if not ids:
        return f'refused: nothing matches "{which}" to hide'
    d.ui.append({'cmd': 'hide', 'args': {'ids': ids, 'hidden': bool(hidden)}})
    return (
        f'{"hid" if hidden else "showed"} {len(ids)} object(s)'
        + (f' of {n}' if n > len(ids) else '')
        + f': {ids[0]}..{ids[-1]}'
    )


def t_show_all(d: Drawing, a):
    ids = [o['id'] for o in d.objs if o.get('hidden')] or [o['id'] for o in d.objs]
    ids = ids[: min(MAX_OBJECTS, 2000)]
    if not ids:
        return 'refused: the drawing is empty — there is nothing to show'
    d.ui.append({'cmd': 'hide', 'args': {'ids': ids, 'hidden': False}})
    return f'showed {len(ids)} object(s) again'


def t_save_drawing(d: Drawing, a, name=''):
    nm = str(name or '').strip()[:80]
    d.ui.append({'cmd': 'save', 'args': {'name': nm}})
    return f'saved the drawing as "{nm}"' if nm else 'saved the drawing under its current name'


def t_press_button(d: Drawing, a, id='', args=None):
    from zyg_workflows import arch_assistant as A

    bid = str(id or '').strip()
    if bid not in BUTTONS and bid not in A.EXT_BUTTONS:
        return f'refused: "{bid}" is not a button the assistant may press'
    cmd = {'cmd': 'tool', 'args': {'id': bid}}
    # 2026-09-07: an extension icon may take arguments in place of the prompt()
    # it shows a person (e.g. {'value': 45} for an angle-snap increment)
    if isinstance(args, dict) and args:
        cmd['args']['args'] = args
    d.ui.append(cmd)
    return f'pressed the studio button {bid}' + (f' with {json.dumps(args)}' if isinstance(args, dict) and args else '')


def t_say(d: Drawing, a, text=''):
    txt = str(text or '').strip()[:300]
    if not txt:
        return 'refused: say needs some text'
    d.ui.append({'cmd': 'toast', 'args': {'text': txt}})
    return f'showed a toast: "{txt[:60]}"'


TOOLS = [
    (
        {
            'name': 'set_view',
            'description': 'Point the viewport camera at a standard view (top for a plan, front/back/left/right for elevations, iso for the 3D view). Use when the user asks to see the plan or a facade.',
            'input_schema': {
                'type': 'object',
                'properties': {'view': {'type': 'string', 'enum': list(VIEWS)}},
                'required': ['view'],
            },
        },
        t_set_view,
    ),
    (
        {
            'name': 'focus',
            'description': 'Zoom the camera to frame objects: "new" (what you just drew), "all", a kind, a group name, or a list of ids. Use after drawing so the user sees the result.',
            'input_schema': {'type': 'object', 'properties': {'which': {'type': 'string'}}, 'required': []},
        },
        t_focus,
    ),
    (
        {
            'name': 'select',
            'description': 'Highlight objects in the viewport and the outliner: "new", "all", a kind, a group name or a list of ids. Use when the user asks "which ones are those?" or before telling them to edit by hand.',
            'input_schema': {'type': 'object', 'properties': {'which': {'type': 'string'}}, 'required': []},
        },
        t_select,
    ),
    (
        {
            'name': 'show_cells',
            'description': 'Turn the grid cell labels (A1, C4, AB12) on or off in the viewport. Use when you want the user to read cell names off the ground.',
            'input_schema': {'type': 'object', 'properties': {'on': {'type': 'boolean'}}, 'required': []},
        },
        t_show_cells,
    ),
    (
        {
            'name': 'show_grid',
            'description': 'Turn the ground grid on or off. Off gives a clean picture for a presentation view.',
            'input_schema': {'type': 'object', 'properties': {'on': {'type': 'boolean'}}, 'required': []},
        },
        t_show_grid,
    ),
    (
        {
            'name': 'set_storey_plane',
            'description': 'Move the studio working plane to a storey, so hand-drawn objects land on that floor. Use after building several storeys.',
            'input_schema': {'type': 'object', 'properties': {'storey': {'type': 'integer'}}, 'required': ['storey']},
        },
        t_set_storey_plane,
    ),
    (
        {
            'name': 'set_sun',
            'description': 'Set the sun to an hour of the day (0-24) for the shadow study. 9 is a low morning sun, 14 a high afternoon one.',
            'input_schema': {'type': 'object', 'properties': {'hour': {'type': 'number'}}, 'required': ['hour']},
        },
        t_set_sun,
    ),
    (
        {
            'name': 'section',
            'description': 'Cut a horizontal section just under the top of a storey, so the user looks into that floor. Call it without a storey to switch the section off.',
            'input_schema': {'type': 'object', 'properties': {'storey': {'type': 'integer'}}, 'required': []},
        },
        t_section,
    ),
    (
        {
            'name': 'hide_objects',
            'description': 'Hide (or unhide) objects in the viewport: "new", "all", a kind, a group name or ids. Use to look past a roof or a facade without deleting it.',
            'input_schema': {
                'type': 'object',
                'properties': {'which': {'type': 'string'}, 'hidden': {'type': 'boolean'}},
                'required': [],
            },
        },
        t_hide_objects,
    ),
    (
        {
            'name': 'show_all',
            'description': 'Unhide everything that is hidden in the viewport.',
            'input_schema': {'type': 'object', 'properties': {}, 'required': []},
        },
        t_show_all,
    ),
    (
        {
            'name': 'save_drawing',
            'description': 'Save the drawing, optionally under a new name. Use when the user says "save this as ...".',
            'input_schema': {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': []},
        },
        t_save_drawing,
    ),
    (
        {
            'name': 'press_button',
            'description': 'Press one of the studio dock buttons by id (views v_*, display d_*, light l_*, precision pr_*, organise o_*, select s_*, edit e_*/undo/redo/del/dupe/mirror/array/group/ungroup, reports q_*, export f_*, misc zoomfit/section/t_snap/t_ortho/t_sun/t_wire/p_gpu) plus every icon an extension family lists as pressable (its CAPABILITIES paragraph names them). Any other id is refused.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'id': {'type': 'string'},
                    'args': {
                        'type': 'object',
                        'description': 'optional arguments an extension icon accepts instead of asking (see help)',
                    },
                },
                'required': ['id'],
            },
        },
        t_press_button,
    ),
    (
        {
            'name': 'say',
            'description': 'Show a short toast message over the viewport. Use for a one-line hint that belongs on screen rather than in the chat.',
            'input_schema': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']},
        },
        t_say,
    ),
]

EXAMPLES = [
    {
        'ask': 'draw the house from C4 to L13, 2 storeys, and show me the plan',
        'calls': [
            {
                'tool': 'draw_box',
                'args': {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 2, 'roof': 'gable', 'name': 'woonhuis'},
            },
            {'tool': 'set_view', 'args': {'view': 'top'}},
            {'tool': 'focus', 'args': {'which': 'new'}},
        ],
    },
    {
        'ask': 'let me look inside the first floor',
        'calls': [{'tool': 'section', 'args': {'storey': 1}}, {'tool': 'set_view', 'args': {'view': 'top'}}],
    },
    {
        'ask': 'section off again and put the sun at nine in the morning',
        'calls': [{'tool': 'section', 'args': {}}, {'tool': 'set_sun', 'args': {'hour': 9}}],
    },
    {
        'ask': 'show the cell names so I can tell you where the garage goes',
        'calls': [
            {'tool': 'show_cells', 'args': {'on': True}},
            {'tool': 'say', 'args': {'text': 'Cell labels on — name me the corner cells.'}},
        ],
    },
    {
        'ask': 'hide the roof and select the walls of woonhuis',
        'calls': [
            {'tool': 'hide_objects', 'args': {'which': 'roof_gable', 'hidden': True}},
            {'tool': 'select', 'args': {'which': 'woonhuis'}},
        ],
    },
    {
        'ask': 'clean picture please, no grid, iso view, and save it as Hoofdstraat 12',
        'calls': [
            {'tool': 'show_grid', 'args': {'on': False}},
            {'tool': 'press_button', 'args': {'id': 'v_iso'}},
            {'tool': 'save_drawing', 'args': {'name': 'Hoofdstraat 12'}},
        ],
    },
]
