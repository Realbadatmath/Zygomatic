# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""drawings_sheet — the assistant half of the sheet layer (2026-09-08).

No new kinds: the family lays the drawings that drawings_2d makes onto an ISO
page with a border, a title block and a revision table. The composition itself
can only happen in the tab (it needs the model on screen), so `compose_sheet`
and `export_pdf` are presses of the tab's own icons, while `set_title_block`
and `add_revision` write AR.doc.ext.drawings_sheet directly — that is document
state, it round-trips through the Drawing, and the tab reads it on the next
composition.

Stdlib only.
"""

import datetime
import json

KINDS: dict = {}
OPENINGS: list = []

BUTTONS = ['dc_sheet', 'dc_title', 'dc_rev', 'dc_pdf', 'dc_print']

PROMPT = (
    'Drawing sheets: compose_sheet(size="A3", orient="landscape", views=[{"kind":"plan","storey":0}, '
    '{"kind":"elevation","elev":"front"}, {"kind":"section","dir":"x","x":3}]) lays those drawings out on one '
    'ISO page (A4/A3/A2/A1) with a 10 mm border, the title block bottom-right and the revision table above it, '
    'and shows it to the person with a download button — you cannot see the picture yourself, so say what you '
    'laid out. set_title_block(project=, client=, drawn=, checked=, date=, number=, notes=) fills the title '
    'block; add_revision(note=, by=) appends the next revision letter (A, B, C ...) to the revision table; '
    'export_pdf() sends the composed sheet to the server and downloads a true-size vector PDF. '
    'The five icons can also be pressed directly: press_button("dc_sheet", {"size":"A3","orient":"landscape",'
    '"views":[{"kind":"plan","storey":0}]}), press_button("dc_title", {"project":"Ravenscourt"}), '
    'press_button("dc_rev", {"add":{"note":"window revised","by":"AB"}}), '
    'press_button("dc_pdf", {"size":"A2"}), press_button("dc_print").'
)

SIZES = ('A4', 'A3', 'A2', 'A1')
ORIENTS = ('landscape', 'portrait')
TITLE_KEYS = ('project', 'client', 'drawn', 'checked', 'date', 'number', 'notes')

DEF = {
    'size': 'A3',
    'orient': 'landscape',
    'layout': 'auto',
    'views': [{'kind': 'plan', 'storey': 0}],
    'title': {k: '' for k in TITLE_KEYS},
    'revisions': [],
}


def _today() -> str:
    return datetime.date.today().isoformat()


def _rev_letter(i: int) -> str:
    out = ''
    i = max(0, int(i))
    while True:
        out = chr(65 + i % 26) + out
        i = i // 26 - 1
        if i < 0:
            return out


def _settings(d) -> dict:
    s = d.ext.get('drawings_sheet')
    if not isinstance(s, dict):
        s = json.loads(json.dumps(DEF))
        d.ext['drawings_sheet'] = s
    if s.get('size') not in SIZES:
        s['size'] = DEF['size']
    if s.get('orient') not in ORIENTS:
        s['orient'] = DEF['orient']
    if s.get('layout') not in ('auto', 'grid'):
        s['layout'] = 'auto'
    if not isinstance(s.get('views'), list) or not s['views']:
        s['views'] = json.loads(json.dumps(DEF['views']))
    if not isinstance(s.get('title'), dict):
        s['title'] = {k: '' for k in TITLE_KEYS}
    for k in TITLE_KEYS:
        if not isinstance(s['title'].get(k), str):
            s['title'][k] = ''
    if not s['title']['date']:
        s['title']['date'] = _today()
    if not isinstance(s.get('revisions'), list):
        s['revisions'] = []
    return s


def _clean_view(v) -> dict | str:
    """A view spec the tab understands, or a 'refused: ...' string."""
    if not isinstance(v, dict):
        return 'refused: every view is an object like {"kind": "plan", "storey": 0}'
    k = str(v.get('kind') or 'plan').strip().lower()
    if k in ('plan',):
        try:
            return {'kind': 'plan', 'storey': int(v.get('storey') or 0)}
        except (TypeError, ValueError):
            return 'refused: a plan storey is a whole number (0 = ground)'
    if k in ('elevation', 'elev'):
        e = str(v.get('elev') or 'front').strip().lower()
        if e not in ('front', 'back', 'left', 'right'):
            return 'refused: an elevation is from front, back, left or right'
        return {'kind': 'elevation', 'elev': e}
    if k in ('section', 'sect'):
        ax = str(v.get('dir') or v.get('axis') or ('z' if v.get('z') is not None else 'x')).strip().lower()
        if ax not in ('x', 'z'):
            return 'refused: a section axis is "x" or "z"'
        out = {'kind': 'section', 'dir': ax}
        at = v.get(ax)
        if at is not None:
            try:
                out[ax] = float(at)
            except (TypeError, ValueError):
                return 'refused: a section plane coordinate is a number of metres'
        return out
    return 'refused: a view kind is "plan", "elevation" or "section"'


def t_compose_sheet(d, a, size=None, orient=None, views=None, layout=None):
    s = _settings(d)
    args: dict = {}
    if size is not None:
        sz = str(size).strip().upper()
        if sz not in SIZES:
            return 'refused: a paper size is A4, A3, A2 or A1'
        s['size'] = sz
        args['size'] = sz
    if orient is not None:
        o = str(orient).strip().lower()
        if o not in ORIENTS:
            return 'refused: orientation is "landscape" or "portrait"'
        s['orient'] = o
        args['orient'] = o
    if layout is not None:
        lay = str(layout).strip().lower()
        if lay not in ('auto', 'grid'):
            return 'refused: layout is "auto" or "grid"'
        s['layout'] = lay
        args['layout'] = lay
    if views is not None:
        if not isinstance(views, list) or not views:
            return 'refused: views is a non-empty list of view objects'
        if len(views) > 8:
            return 'refused: at most eight drawings fit on one sheet'
        clean = []
        for v in views:
            c = _clean_view(v)
            if isinstance(c, str):
                return c
            clean.append(c)
        s['views'] = clean
        args['views'] = clean
    d.ui.append({'cmd': 'tool', 'args': {'id': 'dc_sheet', 'args': args or {'size': s['size']}}})
    names = ', '.join(
        v.get('kind', '?') + ('' if v.get('kind') != 'plan' else ' storey %s' % v.get('storey', 0)) for v in s['views']
    )
    return (
        'requested: the studio is composing a %s %s sheet with %d drawing(s) (%s) and showing it with a '
        'download button' % (s['size'], s['orient'], len(s['views']), names)
    )


def t_set_title_block(d, a, project=None, client=None, drawn=None, checked=None, date=None, number=None, notes=None):
    s = _settings(d)
    given = {
        'project': project,
        'client': client,
        'drawn': drawn,
        'checked': checked,
        'date': date,
        'number': number,
        'notes': notes,
    }
    changed = []
    for k, v in given.items():
        if v is None:
            continue
        s['title'][k] = str(v)[:120]
        changed.append('%s "%s"' % (k, s['title'][k]))
    if not changed:
        return 'title block: ' + ', '.join('%s "%s"' % (k, s['title'][k]) for k in TITLE_KEYS if s['title'][k])
    d.ui.append({'cmd': 'toast', 'args': {'text': 'Title block updated.'}})
    return 'title block updated: ' + ', '.join(changed)


def t_add_revision(d, a, note='', by=''):
    s = _settings(d)
    if len(s['revisions']) >= 26 * 27:
        return 'refused: this drawing already has every revision letter'
    rev = {
        'rev': _rev_letter(len(s['revisions'])),
        'date': _today(),
        'note': str(note or '')[:160],
        'by': str(by or '')[:24],
    }
    s['revisions'].append(rev)
    d.ui.append({'cmd': 'toast', 'args': {'text': 'Revision %s added.' % rev['rev']}})
    return (
        'revision %s added (%s, %s%s) — it will appear in the revision table above the title block on the '
        'next sheet'
        % (rev['rev'], rev['date'], rev['note'] or 'no description', ' by ' + rev['by'] if rev['by'] else '')
    )


def t_export_pdf(d, a, name=None, size=None, orient=None):
    s = _settings(d)
    args: dict = {}
    if size is not None:
        sz = str(size).strip().upper()
        if sz not in SIZES:
            return 'refused: a paper size is A4, A3, A2 or A1'
        s['size'] = sz
        args['size'] = sz
    if orient is not None:
        o = str(orient).strip().lower()
        if o not in ORIENTS:
            return 'refused: orientation is "landscape" or "portrait"'
        s['orient'] = o
        args['orient'] = o
    if name is not None:
        s['title']['number'] = str(name)[:120]
    d.ui.append({'cmd': 'tool', 'args': {'id': 'dc_pdf', 'args': args}})
    return 'requested: the studio is exporting the composed %s %s sheet as a vector PDF and downloading it' % (
        s['size'],
        s['orient'],
    )


TOOLS = [
    (
        {
            'name': 'compose_sheet',
            'description': (
                'Lay several drawings (plans, elevations, sections) out on ONE ISO sheet with a border, '
                'a title block and the revision table, and show it to the person with a download button. '
                'You cannot see the picture yourself.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'size': {'type': 'string', 'enum': list(SIZES), 'description': 'paper size'},
                    'orient': {'type': 'string', 'enum': list(ORIENTS), 'description': 'page orientation'},
                    'layout': {
                        'type': 'string',
                        'enum': ['auto', 'grid'],
                        'description': 'how the viewports are flowed',
                    },
                    'views': {
                        'type': 'array',
                        'description': 'the drawings, e.g. [{"kind":"plan","storey":0}]',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'kind': {'type': 'string', 'enum': ['plan', 'elevation', 'section']},
                                'storey': {'type': 'integer'},
                                'elev': {'type': 'string', 'enum': ['front', 'back', 'left', 'right']},
                                'dir': {'type': 'string', 'enum': ['x', 'z']},
                                'x': {'type': 'number'},
                                'z': {'type': 'number'},
                            },
                        },
                    },
                },
                'required': [],
            },
        },
        t_compose_sheet,
    ),
    (
        {
            'name': 'set_title_block',
            'description': (
                'Fill the sheet title block kept with the document (project, client, drawn, checked, '
                'date, drawing number, notes). Call with no arguments to read it back.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project': {'type': 'string'},
                    'client': {'type': 'string'},
                    'drawn': {'type': 'string', 'description': 'initials of who drew it'},
                    'checked': {'type': 'string', 'description': 'initials of who checked it'},
                    'date': {'type': 'string', 'description': 'ISO date on the sheet'},
                    'number': {'type': 'string', 'description': 'drawing number'},
                    'notes': {'type': 'string'},
                },
                'required': [],
            },
        },
        t_set_title_block,
    ),
    (
        {
            'name': 'add_revision',
            'description': (
                'Add the next revision (A, B, C ...) to the sheet revision table with a description and who made it.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'note': {'type': 'string', 'description': 'what changed since the last issue'},
                    'by': {'type': 'string', 'description': 'initials of who revised it'},
                },
                'required': ['note'],
            },
        },
        t_add_revision,
    ),
    (
        {
            'name': 'export_pdf',
            'description': 'Export the composed sheet as a true-size vector PDF and download it.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'the drawing number to file it under'},
                    'size': {'type': 'string', 'enum': list(SIZES)},
                    'orient': {'type': 'string', 'enum': list(ORIENTS)},
                },
                'required': [],
            },
        },
        t_export_pdf,
    ),
]

EXAMPLES = [
    {
        'ask': 'put the ground floor plan and the front elevation on an A3 sheet',
        'calls': [
            {
                'tool': 'compose_sheet',
                'args': {
                    'size': 'A3',
                    'views': [{'kind': 'plan', 'storey': 0}, {'kind': 'elevation', 'elev': 'front'}],
                },
            }
        ],
    },
    {
        'ask': 'the project is Ravenscourt, drawing 1001, drawn by AB',
        'calls': [{'tool': 'set_title_block', 'args': {'project': 'Ravenscourt', 'number': '1001', 'drawn': 'AB'}}],
    },
    {
        'ask': 'note that the kitchen window changed and issue it as a PDF',
        'calls': [
            {'tool': 'add_revision', 'args': {'note': 'kitchen window revised', 'by': 'AB'}},
            {'tool': 'compose_sheet', 'args': {}},
            {'tool': 'export_pdf', 'args': {}},
        ],
    },
    {'ask': 'print the sheet at true scale', 'calls': [{'tool': 'press_button', 'args': {'id': 'dc_print'}}]},
]
