# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""file_manage_setup — the assistant half of the File & Setup icons.

No kinds and no drawing tools: this family is about the DOCUMENT (templates,
versions, autosave, archive) and the STUDIO (preferences, theme, performance,
help, about). Every tool here is one of two shapes:

  * a tab press — it appends {'cmd': 'tool'} for arch_ext/file_manage_setup.js
    to carry out in the browser, because only the tab holds the live drawing;
  * a disk read — list_versions() answers straight from
    arch_server_ext.file_manage_setup, which owns data/architecture/versions,
    so the model can report what exists without a round trip through the tab.

BUTTONS names the nine icons the model may press directly; the tab only accepts
them because the JS registrations carry `assist: 1`.
"""

from __future__ import annotations

KINDS: dict = {}
OPENINGS: list = []

BUTTONS = ['f_tmpl', 'f_ver', 'f_auto', 'f_archive', 'p_prefs', 'p_theme', 'p_perf', 'p_help', 'p_about']

THEMES = ('dark', 'light', 'blueprint')

PROMPT = (
    'File and setup: save_template(name), new_from_template(name) (a NEW untitled drawing, the original '
    'untouched), list_templates(); list_versions() reads the history from disk, version_diff(stamp) says what a '
    'version holds against the saved drawing — ask before restore_version(stamp), which replaces every object. '
    'set_theme("dark"|"light"|"blueprint"); performance_report(). Icons f_tmpl, f_ver, f_auto, f_archive, '
    'p_prefs, p_theme, p_perf, p_help, p_about. explain("templates") has the detail.'
)


def _srv():
    """The server half, loaded the same way the route dispatcher loads it."""
    import importlib
    import os
    import sys

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if here not in sys.path:
        sys.path.insert(0, here)
    return importlib.import_module('zyg_workflows.arch_server_ext.file_manage_setup')


def _press(d, bid, args=None):
    cmd = {'cmd': 'tool', 'args': {'id': bid}}
    if isinstance(args, dict) and args:
        cmd['args']['args'] = args
    d.ui.append(cmd)


def t_save_template(d, a, name=''):
    nm = str(name or '').strip()[:60]
    if not nm:
        return 'refused: save_template needs a name for the template'
    _press(d, 'f_tmpl', {'action': 'save', 'name': nm})
    return (
        f'saving the drawing on screen as the template "{nm}" — it will appear in '
        f'new_from_template and in the f_tmpl list'
    )


def t_new_from_template(d, a, name=''):
    nm = str(name or '').strip()[:60]
    if not nm:
        return 'refused: new_from_template needs the template name (call list_templates first if unsure)'
    _press(d, 'f_tmpl', {'action': 'new', 'name': nm})
    return (
        f'opening the template "{nm}" as a NEW untitled drawing — the template itself is not '
        f'changed, and the first save will ask for a name'
    )


def t_list_templates(d, a):
    try:
        rows = (_srv().templates({}, 'GET') or {}).get('templates') or []
    except Exception as e:  # noqa: BLE001 — report, never raise at the model
        return f'could not read the templates: {e}'
    if not rows:
        return 'no templates yet — save_template(name) makes the first one'
    return f'{len(rows)} templates: ' + '; '.join(f'{r.get("name")} ({r.get("objects")} objects)' for r in rows[:30])


def _resolve_pid(d, drawing):
    """(srv, pid, complaint). The Drawing carries no project id, so an unnamed
    call reads the history of the drawing SAVED UNDER THIS NAME — which is the id
    architecture_studio gives it (save_project slugs the name)."""
    try:
        srv = _srv()
        pid = str(drawing or '').strip() or srv._studio()._slug(d.name)
    except Exception as e:  # noqa: BLE001
        return None, '', f'could not reach the version shelf: {e}'
    if not pid:
        return (
            srv,
            '',
            (
                'the drawing on screen has never been saved, so it has no versions yet — '
                'save it once (press_button "v_save") and every later save keeps a copy'
            ),
        )
    return srv, pid, ''


def t_list_versions(d, a, drawing=''):
    srv, pid, complaint = _resolve_pid(d, drawing)
    if complaint:
        return complaint
    try:
        r = srv.versions({'pid': pid, 'action': 'list'}, 'GET')
    except Exception as e:  # noqa: BLE001
        return f'could not read the versions: {e}'
    if r.get('error'):
        return f'refused: {r["error"]}'
    rows = r.get('versions') or []
    if not rows:
        return f'"{pid}" has no versions yet — the next save will keep one (up to {r.get("keep", 50)})'
    out = '; '.join(
        f'{v["stamp"]} {v["objects"]} objects' + (f' "{v["label"]}"' if v.get('label') else '') for v in rows[:25]
    )
    return f'{len(rows)} versions of "{pid}" (newest first, kept up to {r.get("keep", 50)}): {out}' + (
        f' ... and {len(rows) - 25} older' if len(rows) > 25 else ''
    )


def t_version_diff(d, a, stamp='', drawing=''):
    # Read only, and deliberately so: this is the question to ask BEFORE
    # restore_version, which replaces every object. The count reads forward, from
    # the kept version to the drawing on disk, so "added" is what a restore drops.
    st = str(stamp or '').strip()
    if not st:
        return 'refused: version_diff needs the stamp of the version (list_versions shows them)'
    srv, pid, complaint = _resolve_pid(d, drawing)
    if complaint:
        return complaint
    try:
        r = srv.diff({'pid': pid, 'stamp': st}, 'GET')
    except Exception as e:  # noqa: BLE001
        return f'could not compare that version: {e}'
    if r.get('error'):
        return f'refused: {r["error"]}'
    c = r.get('counts') or {}
    if not (c.get('added') or c.get('removed') or c.get('changed')):
        return f'version {st} of "{pid}" is identical to the saved drawing — restoring it would change nothing'

    def _some(ids):
        ids = ids or []
        return ', '.join(ids[:6]) + (f' and {len(ids) - 6} more' if len(ids) > 6 else '')

    parts = []
    if c.get('added'):
        parts.append(f'{c["added"]} objects added since then ({_some(r.get("added"))}) — a restore would drop them')
    if c.get('removed'):
        parts.append(
            f'{c["removed"]} objects deleted since then ({_some(r.get("removed"))}) — a restore would bring them back'
        )
    if c.get('changed'):
        parts.append(f'{c["changed"]} objects moved or altered ({_some(r.get("changed"))})')
    return f'version {st} of "{pid}" has {c.get("old", 0)} objects against the saved {c.get("new", 0)}: ' + '; '.join(
        parts
    )


def t_restore_version(d, a, stamp='', drawing=''):
    st = str(stamp or '').strip()
    if not st:
        return 'refused: restore_version needs the stamp of the version (list_versions shows them)'
    args = {'action': 'restore', 'stamp': st}
    if drawing:
        args['pid'] = str(drawing).strip()
    _press(d, 'f_ver', args)
    return (
        f'restoring version {st} into the drawing on screen — it replaces every object but is '
        f'one undo step, so the current state is not lost'
    )


def t_set_theme(d, a, theme='dark'):
    th = str(theme or '').strip().lower()
    if th not in THEMES:
        return 'refused: theme must be one of ' + '/'.join(THEMES)
    _press(d, 'p_theme', {'theme': th})
    return f'studio theme set to {th}' + (' (the sky is only repainted when it is studio grey)' if th != 'dark' else '')


def t_performance_report(d, a, reduced=None):
    args = {}
    if reduced is not None:
        args['reduced'] = bool(reduced)
    _press(d, 'p_perf', args)
    return (
        'opening the performance sheet — live fps, objects, triangles, draw calls and textures, '
        'with pixel ratio, shadows, texture quality and freeze-far-objects switches'
        + (' ; applying the reduced preset' if args.get('reduced') else '')
    )


TOOLS = [
    (
        {
            'name': 'save_template',
            'description': 'Save the drawing currently on screen as a reusable template under a name. Use it when the user says "keep this as a starting point/template".',
            'input_schema': {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']},
        },
        t_save_template,
    ),
    (
        {
            'name': 'new_from_template',
            'description': 'Open a saved template as a NEW untitled drawing. Use it to start from a standard layout instead of drawing it again. Call list_templates first if the name is not known.',
            'input_schema': {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']},
        },
        t_new_from_template,
    ),
    (
        {
            'name': 'list_templates',
            'description': 'The templates on disk, with their object counts. Read only.',
            'input_schema': {'type': 'object', 'properties': {}, 'required': []},
        },
        t_list_templates,
    ),
    (
        {
            'name': 'list_versions',
            'description': 'The saved version history of a drawing (newest first, with stamp, object count and label). Read straight from disk. Use it before restoring anything.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'drawing': {'type': 'string', 'description': 'drawing id; defaults to the one on screen'}
                },
                'required': [],
            },
        },
        t_list_versions,
    ),
    (
        {
            'name': 'version_diff',
            'description': 'What a saved version holds against the saved drawing: objects added, deleted and moved since then. Read only. Ask this before restore_version, which replaces everything.',
            'input_schema': {
                'type': 'object',
                'properties': {'stamp': {'type': 'string'}, 'drawing': {'type': 'string'}},
                'required': ['stamp'],
            },
        },
        t_version_diff,
    ),
    (
        {
            'name': 'restore_version',
            'description': 'Put a saved version back into the drawing on screen. It replaces every object but is a single undo step. Get the stamp from list_versions.',
            'input_schema': {
                'type': 'object',
                'properties': {'stamp': {'type': 'string'}, 'drawing': {'type': 'string'}},
                'required': ['stamp'],
            },
        },
        t_restore_version,
    ),
    (
        {
            'name': 'set_theme',
            'description': 'Repaint the studio panels dark, light or blueprint. Use it when the user asks for a lighter/darker interface or a blueprint look.',
            'input_schema': {
                'type': 'object',
                'properties': {'theme': {'type': 'string', 'enum': list(THEMES)}},
                'required': ['theme'],
            },
        },
        t_set_theme,
    ),
    (
        {
            'name': 'performance_report',
            'description': 'Open the live performance sheet (fps, objects, triangles, draw calls, textures) with its reduction switches. Use it when the user says the studio is slow.',
            'input_schema': {
                'type': 'object',
                'properties': {'reduced': {'type': 'boolean', 'description': 'also apply the reduced preset'}},
                'required': [],
            },
        },
        t_performance_report,
    ),
]

EXAMPLES = [
    {
        'ask': 'start me a new row house from the standard template',
        'calls': [
            {'tool': 'list_templates', 'args': {}},
            {'tool': 'new_from_template', 'args': {'name': 'Row house 5.4 m'}},
        ],
    },
    {
        'ask': 'keep this layout so I can reuse it',
        'calls': [{'tool': 'save_template', 'args': {'name': 'Site layout'}}],
    },
    {
        'ask': 'what versions of this drawing do I have, and go back to the one before lunch',
        'calls': [
            {'tool': 'list_versions', 'args': {}},
            {'tool': 'version_diff', 'args': {'stamp': '20260908-115500-120'}},
            {'tool': 'restore_version', 'args': {'stamp': '20260908-115500-120'}},
        ],
    },
    {
        'ask': 'turn on autosave every minute',
        'calls': [{'tool': 'press_button', 'args': {'id': 'f_auto', 'args': {'on': True, 'every_s': 60}}}],
    },
    {'ask': 'zip this drawing up with its history', 'calls': [{'tool': 'press_button', 'args': {'id': 'f_archive'}}]},
    {
        'ask': 'the interface is too dark, and the viewport feels slow',
        'calls': [
            {'tool': 'set_theme', 'args': {'theme': 'light'}},
            {'tool': 'performance_report', 'args': {'reduced': True}},
        ],
    },
    {
        'ask': 'what does the studio actually do — show me the icons and keys',
        'calls': [{'tool': 'press_button', 'args': {'id': 'p_help'}}],
    },
]
