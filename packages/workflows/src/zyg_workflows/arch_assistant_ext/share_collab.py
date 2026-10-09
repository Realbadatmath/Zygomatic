# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""share_collab — the assistant's half of the Share dock group.

The six icons split cleanly in two, and the split is the whole design:

  · what is a fact about the DRAWING the model writes itself — a markup pin is
    a record (d.new), an issue, a log line and a stored view live in
    `d.ext['share_collab']`, so they are saved with the drawing, round-trip
    through the tab, and are readable again by list_issues()/change_log()
    without asking the browser anything.
  · what only the TAB knows the model asks the tab for, through
    press_button(id, args): the clipboard (share_link), the camera the operator
    is looking through right now (store_view), the tween and the hidden bars
    (present_views), the red ghosts of Compare. Those are effects on a screen,
    not statements about the building.

compare_with() does both: it reads the other saved drawing here and reports the
real numbers, then presses c_compare so the operator SEES the same diff.
"""

from __future__ import annotations

import datetime
import json

from zyg_workflows.arch_assistant import Drawing, _num, cell_centre, cell_of, parse_cell

KINDS = {'markup_note': {'txt': 'Note', 'col': '#ffcc00', 'size': 0.4}}
OPENINGS: list = []
# A pin is a comment about the building, not part of it: Blender builds nothing
# (arch_blender_ext/share_collab.py).
VOID_KINDS = ['markup_note']
BUTTONS = ['c_link', 'c_note', 'c_issues', 'c_compare', 'c_log', 'c_present']

NOTE_COL = '#ffcc00'
ISSUE_COL = '#ff5544'
NOTE_SIZE = 0.4
LOG_CAP = 500

PROMPT = (
    'Share and review: share_link(expires_days) makes a read-only LAN copy. add_markup(cell, text) pins a '
    'markup_note — a drawing mark, never building fabric. add_issue(title, which) opens a numbered issue, '
    'list_issues() reports them and close_issue(n) — not a status argument — closes one. compare_with(pid) diffs '
    'this drawing against another SAVED one; change_log() says what has happened to it. store_view(name) and '
    'present_views(seconds). explain("sharing") has the detail.'
)


# ── document-level state ──────────────────────────────────────────────────────
def _ext(d: Drawing) -> dict:
    """`d.ext['share_collab']`, with its three lists — the same shape the tab
    writes (arch_ext/share_collab.js extWrite). This one CREATES the state, so
    only a tool that is about to write anything calls it."""
    e = d.ext.get('share_collab')
    if not isinstance(e, dict):
        e = d.ext['share_collab'] = {}
    for k in ('issues', 'log', 'views'):
        if not isinstance(e.get(k), list):
            e[k] = []
    return e


def _ext_ro(d: Drawing) -> dict:
    """The same three lists for a tool that only READS. "What is still
    outstanding?" asked of a drawing that has never had an issue must not write
    an empty share_collab block into it and hand that back as a change — a
    read-only report changes nothing, here as in the tab."""
    e = d.ext.get('share_collab')
    e = e if isinstance(e, dict) else {}
    return {k: (e[k] if isinstance(e.get(k), list) else []) for k in ('issues', 'log', 'views')}


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec='seconds')


def _log(d: Drawing, what: str) -> None:
    e = _ext(d)
    e['log'].append({'t': _now(), 'who': 'assistant', 'what': str(what)[:300]})
    if len(e['log']) > LOG_CAP:
        del e['log'][: len(e['log']) - LOG_CAP]


def _pin(d: Drawing, x: float, z: float, y: float, txt: str, col: str) -> dict:
    return d.new(
        'markup_note',
        {'txt': str(txt)[:300], 'col': col, 'size': NOTE_SIZE},
        x,
        z,
        y,
        mat='mat_plaster',
        name='Note: ' + str(txt)[:40],
    )


def _centre(recs: list) -> tuple:
    """Where a pin about these records belongs: over the middle of them, at the
    top of the tallest. No geometry here — the record's own point is enough."""
    n = len(recs)
    x = sum(o['x'] for o in recs) / n
    z = sum(o['z'] for o in recs) / n
    y = max(o['y'] for o in recs)
    return x, z, y


# ── tools ─────────────────────────────────────────────────────────────────────
def t_share_link(d: Drawing, a, expires_days=30):
    days = _num(expires_days, 30)
    if days < 0 or days > 3650:
        return 'refused: expires_days must be between 0 (never expires) and 3650'
    d.ui.append({'cmd': 'tool', 'args': {'id': 'c_link', 'args': {'expires_days': days}}})
    _log(d, 'share link requested (%s)' % ('no expiry' if not days else '%g days' % days))
    return (
        'asked the studio for a read-only share link to this drawing'
        + (' with no expiry' if not days else ' expiring in %g day(s)' % days)
        + ' — it is copied to the clipboard and shown in a toast'
    )


def t_add_markup(d: Drawing, a, cell, text, storey=0):
    txt = str(text or '').strip()
    if not txt:
        return 'refused: a markup is a comment — it needs some text'
    if len(txt) > 300:
        return 'refused: a markup is a note, not a report — keep it under 300 characters'
    x, z = cell_centre(*parse_cell(cell))
    o = _pin(d, x, z, int(_num(storey, 0)) * d.storey_h, txt, NOTE_COL)
    _log(d, 'markup "%s" at %s' % (txt[:80], cell_of(x, z)))
    return 'markup %s pinned at %s: "%s"' % (o['id'], cell_of(x, z), txt)


def t_add_issue(d: Drawing, a, title, which='new'):
    t = str(title or '').strip()[:200]
    if not t:
        return 'refused: an issue needs a title saying what is wrong'
    recs = d.select(which if which not in (None, '') else 'new')
    recs = [o for o in recs if o['kind'] != 'markup_note']
    if not recs:
        return f'refused: nothing matches "{which}" — an issue is raised against objects, name them'
    e = _ext(d)
    n = max([int(_num(i.get('n'), 0)) for i in e['issues']] + [0]) + 1
    x, z, y = _centre(recs)
    pin = _pin(d, x, z, y, '#%d %s' % (n, t), ISSUE_COL)
    e['issues'].append(
        {
            'n': n,
            'title': t,
            'ids': [o['id'] for o in recs],
            'status': 'open',
            'created': _now(),
            'by': 'assistant',
            'pin': pin['id'],
        }
    )
    _log(d, 'issue #%d opened: %s' % (n, t))
    op = len([i for i in e['issues'] if i.get('status') != 'closed'])
    return 'issue #%d "%s" opened against %d object(s) at %s, pinned as %s — %d open of %d' % (
        n,
        t,
        len(recs),
        cell_of(x, z),
        pin['id'],
        op,
        len(e['issues']),
    )


def t_close_issue(d: Drawing, a, n, status='closed'):
    e = _ext(d)
    num = int(_num(n, 0))
    want = 'closed' if str(status or 'closed').lower() != 'open' else 'open'
    for i in e['issues']:
        if int(_num(i.get('n'), 0)) == num:
            if i.get('status') == want:
                return f'issue #{num} is already {want}'
            i['status'] = want
            _log(d, 'issue #%d %s: %s' % (num, 'closed' if want == 'closed' else 'reopened', i.get('title', '')))
            op = len([x for x in e['issues'] if x.get('status') != 'closed'])
            return 'issue #%d "%s" %s — %d still open of %d' % (num, i.get('title', ''), want, op, len(e['issues']))
    return f'refused: there is no issue #{num} on this drawing'


def t_list_issues(d: Drawing, a):
    e = _ext_ro(d)
    if not e['issues']:
        return 'no issues on this drawing'
    op = len([i for i in e['issues'] if i.get('status') != 'closed'])
    out = ['%d issue(s), %d open:' % (len(e['issues']), op)]
    for i in e['issues']:
        ids = i.get('ids') or []
        alive = [x for x in ids if d.find(x)]
        out.append(
            '  #%s [%s] %s — %d object(s)%s'
            % (
                i.get('n'),
                i.get('status', 'open'),
                i.get('title', ''),
                len(ids),
                '' if len(alive) == len(ids) else ', %d since deleted' % (len(ids) - len(alive)),
            )
        )
    return '\n'.join(out)


def t_compare_with(d: Drawing, a, pid, stamp=''):
    """The diff read here (so the answer carries real numbers) and shown there
    (so the operator sees the red ghosts)."""
    from zyg_workflows import architecture_studio as AS

    r = AS.ext_dispatch('POST', 'share_collab/other', {'pid': str(pid or ''), 'stamp': str(stamp or '')})
    if not r.get('ok'):
        return 'refused: ' + str(r.get('error') or 'no such drawing')
    them = {o.get('id'): o for o in ((r.get('doc') or {}).get('objects') or []) if isinstance(o, dict)}
    mine = {o['id']: o for o in d.objs}
    added = [i for i in mine if i not in them]
    removed = [i for i in them if i not in mine]
    changed = []
    for i in mine:
        b = them.get(i)
        if b is None:
            continue
        f = []
        if json.dumps(mine[i]['p'], sort_keys=True) != json.dumps(b.get('p') or {}, sort_keys=True):
            f.append('p')
        for k in ('x', 'y', 'z', 'ry'):
            if abs(mine[i][k] - _num(b.get(k), 0)) > 1e-6:
                f.append(k)
        if str(mine[i]['mat']) != str(b.get('mat') or ''):
            f.append('mat')
        if f:
            changed.append('%s (%s) %s' % (i, mine[i]['kind'], '/'.join(f)))
    d.ui.append({'cmd': 'tool', 'args': {'id': 'c_compare', 'args': {'pid': str(pid), 'stamp': str(stamp or '')}}})
    lines = [
        'compared with "%s": %d added here, %d removed since, %d changed'
        % (r.get('name') or pid, len(added), len(removed), len(changed))
    ]
    if changed:
        lines.append('  changed: ' + ', '.join(changed[:20]) + (' …' if len(changed) > 20 else ''))
    if removed:
        lines.append('  removed: ' + ', '.join(removed[:20]) + (' …' if len(removed) > 20 else ''))
    lines.append('  the studio is showing the removed records as red ghosts and the added ones outlined green')
    return '\n'.join(lines)


def t_change_log(d: Drawing, a, limit=40):
    e = _ext_ro(d)
    if not e['log']:
        return 'nothing in the change log yet'
    n = max(1, min(200, int(_num(limit, 40))))
    rows = e['log'][-n:]
    out = [
        '%d log entr%s (newest last%s):'
        % (
            len(e['log']),
            'y' if len(e['log']) == 1 else 'ies',
            '' if len(rows) == len(e['log']) else ', showing the last %d' % n,
        )
    ]
    for r in rows:
        out.append('  %s  %-9s %s' % (str(r.get('t', ''))[:19], r.get('who', '?'), r.get('what', '')))
    return '\n'.join(out)


def t_store_view(d: Drawing, a, name=''):
    nm = str(name or '').strip()[:80]
    if not nm:
        return 'refused: a stored view needs a name — that is what the presentation lists'
    d.ui.append({'cmd': 'tool', 'args': {'id': 'c_present', 'args': {'action': 'add', 'name': nm}}})
    _log(d, 'view "%s" stored' % nm)
    return (
        'stored the camera the operator is looking through as the view "%s" — '
        'present_views() plays every stored view in turn' % nm
    )


def t_present_views(d: Drawing, a, seconds=4):
    s = _num(seconds, 4)
    if s < 0.1 or s > 120:
        return 'refused: seconds (how long each view is held) must be between 0.1 and 120'
    d.ui.append({'cmd': 'tool', 'args': {'id': 'c_present', 'args': {'action': 'play', 'seconds': s}}})
    return (
        'presenting the stored views, %g second(s) each, with the panels hidden — '
        'Esc stops it and the panels come back' % s
    )


TOOLS = [
    (
        {
            'name': 'share_link',
            'description': 'A read-only link to this drawing for someone else on this network. The studio stores a '
            'COPY, so the link keeps working after the drawing moves on, and copies the URL to the '
            'clipboard. expires_days 0 means it never expires (default 30).',
            'input_schema': {'type': 'object', 'properties': {'expires_days': {'type': 'number'}}},
        },
        t_share_link,
    ),
    (
        {
            'name': 'add_markup',
            'description': 'Pin a comment to a cell of the drawing — a question, a correction, "this wall is wrong". '
            'The note stays with the drawing and is not built in Blender.',
            'input_schema': {
                'type': 'object',
                'properties': {'cell': {'type': 'string'}, 'text': {'type': 'string'}, 'storey': {'type': 'integer'}},
                'required': ['cell', 'text'],
            },
        },
        t_add_markup,
    ),
    (
        {
            'name': 'add_issue',
            'description': 'Open a numbered issue against some objects: which = "new" (the ones just made), "all", a '
            'kind, a group name or a list of ids. A pin "#n title" is placed at their centre and the '
            'issue is saved with the drawing.',
            'input_schema': {
                'type': 'object',
                'properties': {'title': {'type': 'string'}, 'which': {'type': 'string'}},
                'required': ['title'],
            },
        },
        t_add_issue,
    ),
    (
        {
            'name': 'close_issue',
            'description': 'Close issue number n (or reopen it with status="open").',
            'input_schema': {
                'type': 'object',
                'properties': {'n': {'type': 'integer'}, 'status': {'type': 'string', 'enum': ['closed', 'open']}},
                'required': ['n'],
            },
        },
        t_close_issue,
    ),
    (
        {
            'name': 'list_issues',
            'description': 'Every issue on this drawing with its number, status, title and how many objects it is '
            'about. Read-only — read it before answering "what is still outstanding?".',
            'input_schema': {'type': 'object', 'properties': {}},
        },
        t_list_issues,
    ),
    (
        {
            'name': 'compare_with',
            'description': "Diff this drawing against another SAVED drawing (its project id, from the studio's Open "
            'list) or one of its versions. Reports what was added, removed and changed, and makes the '
            'studio show the removed records as translucent red ghosts.',
            'input_schema': {
                'type': 'object',
                'properties': {'pid': {'type': 'string'}, 'stamp': {'type': 'string'}},
                'required': ['pid'],
            },
        },
        t_compare_with,
    ),
    (
        {
            'name': 'change_log',
            'description': 'What has happened to this drawing and when — saves with their object-count deltas, '
            'assistant injections with what was asked for, issues opened and closed. Read-only.',
            'input_schema': {'type': 'object', 'properties': {'limit': {'type': 'integer'}}},
        },
        t_change_log,
    ),
    (
        {
            'name': 'store_view',
            'description': 'Store the camera the operator is looking through as a named view, for the presentation. '
            "Unlike the studio's single camera bookmark this is a list.",
            'input_schema': {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']},
        },
        t_store_view,
    ),
    (
        {
            'name': 'present_views',
            'description': 'Play the stored views as a slideshow: the panels go away, the camera tweens from one to '
            'the next and holds each for `seconds`. Esc stops it.',
            'input_schema': {'type': 'object', 'properties': {'seconds': {'type': 'number'}}},
        },
        t_present_views,
    ),
]

EXAMPLES = [
    {'ask': 'send this to Ruth on the office network', 'calls': [{'tool': 'share_link', 'args': {'expires_days': 7}}]},
    {
        'ask': 'put a note on E5 saying the door swings the wrong way',
        'calls': [{'tool': 'add_markup', 'args': {'cell': 'E5', 'text': 'Door swings the wrong way'}}],
    },
    {
        'ask': 'raise an issue on the walls I just drew: they are too thin',
        'calls': [{'tool': 'add_issue', 'args': {'title': 'Walls too thin', 'which': 'new'}}],
    },
    {'ask': 'what is still outstanding?', 'calls': [{'tool': 'list_issues', 'args': {}}]},
    {'ask': 'issue 1 is sorted', 'calls': [{'tool': 'close_issue', 'args': {'n': 1}}]},
    {
        'ask': 'what changed since the scheme called north-house?',
        'calls': [{'tool': 'compare_with', 'args': {'pid': 'north-house'}}],
    },
    {'ask': 'what has been done to this drawing today?', 'calls': [{'tool': 'change_log', 'args': {}}]},
    {
        'ask': 'remember this angle as the entrance shot, then walk me through the views',
        'calls': [
            {'tool': 'store_view', 'args': {'name': 'Entrance'}},
            {'tool': 'present_views', 'args': {'seconds': 5}},
        ],
    },
]
