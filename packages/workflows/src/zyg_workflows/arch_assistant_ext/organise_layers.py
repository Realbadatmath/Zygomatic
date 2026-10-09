# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""organise_layers — the assistant's half of Organise ▸ Outliner / Layers / Tags / Sets.

No kinds and no geometry: this family organises what is already drawn. It gives
the model

  * BUTTONS — the four dock icons arch_ext/organise_layers.js wired (o_outliner,
    o_layers, o_tags, o_sets), pressed through view_scene_ops.press_button(id, args);
  * TOOLS — server-side twins that do the same job on the Drawing so the model
    gets a text answer and the document comes back already organised:
    set_layer, layer_visibility, tag_objects, select_by_tag,
    save_selection_set, recall_selection_set.

One arithmetic, kept in step with the JS:
  a record's layer  = o['meta']['layer']          (unset ⇒ 'Default')
  a record's tags   = o['meta']['tags']           (unique, lower-case, trimmed, sorted)
  the drawing's own = d.ext['organise_layers'] = {'layers': [{name, hidden, locked, color}],
                                                  'sets': {name: [ids]}}
Both survive the round trip: Drawing keeps `meta` per record and `ext` per
document, and to_doc() writes them back for the tab.

Standard library only.
"""

from __future__ import annotations

from zyg_workflows.arch_assistant import Drawing

KINDS: dict = {}
OPENINGS: list = []

FAM = 'organise_layers'
DEFAULT_LAYER = 'Default'
MAX_NAME = 40
MAX_TAGS = 24

BUTTONS = ['o_outliner', 'o_layers', 'o_tags', 'o_sets']

PROMPT = (
    'Organise (layers, tags, selection sets — no geometry): set_layer(which, layer) puts objects on a '
    'named layer (created if new); layer_visibility(layer, hidden, locked) hides/shows and locks/unlocks '
    'a whole layer; tag_objects(which, tags, mode=add|remove) writes free labels; select_by_tag(tag) '
    'highlights everything carrying it; save_selection_set(name, which) and recall_selection_set(name) '
    'name a selection and get it back. Layers live in the drawing, so they are saved with it. '
    'Buttons: press_button("o_outliner", {"on": true}) turns the outliner into a storey/group tree; '
    'press_button("o_layers", {"layer": "Structure", "action": "new"|"assign"|"hide"|"show"|"lock"|"unlock"|"rename"|"delete"}) '
    'opens the layer manager and acts; press_button("o_tags", {"tags": ["fire-rated"], "mode": "add"|"remove"|"select"}); '
    'press_button("o_sets", {"name": "north wing", "action": "save"|"recall"|"delete"|"list"}).'
)


# ── helpers (the same arithmetic as arch_ext/organise_layers.js) ──────────────
def _ext(d: Drawing) -> dict:
    e = d.ext.get(FAM)
    if not isinstance(e, dict):
        e = d.ext[FAM] = {}
    layers = e.get('layers')
    if not isinstance(layers, list) or not layers:
        e['layers'] = [{'name': DEFAULT_LAYER, 'hidden': False, 'locked': False, 'color': '#8fa3b8'}]
    if not isinstance(e.get('sets'), dict):
        e['sets'] = {}
    return e


def _meta(o: dict) -> dict:
    m = o.get('meta')
    if not isinstance(m, dict):
        m = o['meta'] = {}
    return m


def layer_of(o: dict) -> str:
    return str(_meta(o).get('layer') or DEFAULT_LAYER)


def tags_of(o: dict) -> list[str]:
    t = _meta(o).get('tags')
    return [str(x) for x in t] if isinstance(t, list) else []


def _find_layer(e: dict, name: str) -> dict | None:
    for lay in e['layers']:
        if lay.get('name') == name:
            return lay
    return None


def _ensure_layer(e: dict, name: str) -> dict:
    lay = _find_layer(e, name)
    if lay is None:
        lay = {'name': name, 'hidden': False, 'locked': False, 'color': '#8fa3b8'}
        e['layers'].append(lay)
    return lay


def _norm_tags(v) -> list[str]:
    raw = v if isinstance(v, list) else str(v or '').split(',')
    out: list[str] = []
    for t in raw:
        t = str(t or '').strip().lower()[:MAX_NAME]
        if t and t not in out:
            out.append(t)
    return out[:MAX_TAGS]


def _n(n: int, word: str) -> str:
    return f'{n} {word}' + ('' if n == 1 else 's')


# ── tools ────────────────────────────────────────────────────────────────────
def t_set_layer(d: Drawing, a: dict, which='new', layer=DEFAULT_LAYER):
    name = str(layer or '').strip()[:MAX_NAME]
    if not name:
        return 'refused: a layer needs a name.'
    recs = d.select(which)
    if not recs:
        return f'refused: {which!r} matched nothing to put on a layer.'
    e = _ext(d)
    lay = _ensure_layer(e, name)
    for o in recs:
        _meta(o)['layer'] = name
        o['hidden'] = bool(lay.get('hidden'))
        if lay.get('locked'):
            o['lock'] = True
    d.selected = [o['id'] for o in recs][:200]
    return f'{_n(len(recs), "object")} on layer "{name}" ({", ".join(o["id"] for o in recs[:12])}).'


def t_layer_visibility(d: Drawing, a: dict, layer=DEFAULT_LAYER, hidden=None, locked=None):
    name = str(layer or '').strip()[:MAX_NAME]
    e = _ext(d)
    lay = _find_layer(e, name)
    if lay is None:
        have = ', '.join(str(x.get('name')) for x in e['layers'])
        return f'refused: no layer named "{name}". The drawing has: {have}.'
    if hidden is None and locked is None:
        return 'refused: say hidden=true/false or locked=true/false.'
    if hidden is not None:
        lay['hidden'] = bool(hidden)
    if locked is not None:
        lay['locked'] = bool(locked)
    members = [o for o in d.objs if layer_of(o) == name]
    ids = []
    for o in members:
        o['hidden'] = bool(lay.get('hidden'))
        o['lock'] = bool(lay.get('locked'))
        ids.append(o['id'])
    if ids:
        d.ui.append({'cmd': 'hide', 'args': {'ids': ids[:200], 'hidden': bool(lay.get('hidden'))}})
    state = ('hidden' if lay.get('hidden') else 'visible') + ', ' + ('locked' if lay.get('locked') else 'unlocked')
    return f'Layer "{name}" is now {state} ({_n(len(members), "object")}).'


def t_tag_objects(d: Drawing, a: dict, which='new', tags=None, mode='add'):
    tg = _norm_tags(tags)
    if not tg:
        return 'refused: no tags given.'
    mode = str(mode or 'add').lower()
    if mode not in ('add', 'remove'):
        return 'refused: mode is "add" or "remove" (use select_by_tag to select).'
    recs = d.select(which)
    if not recs:
        return f'refused: {which!r} matched nothing to tag.'
    changed = 0
    for o in recs:
        have = tags_of(o)
        before = list(have)
        for t in tg:
            if mode == 'remove':
                if t in have:
                    have.remove(t)
            elif t not in have:
                have.append(t)
        have.sort()
        _meta(o)['tags'] = have
        if have != before:
            changed += 1
    verb = 'Removed' if mode == 'remove' else 'Added'
    return f'{verb} {", ".join(tg)} on {_n(len(recs), "object")} ({changed} changed).'


def t_select_by_tag(d: Drawing, a: dict, tag=''):
    tg = _norm_tags(tag)
    if not tg:
        counts: dict[str, int] = {}
        for o in d.objs:
            for t in tags_of(o):
                counts[t] = counts.get(t, 0) + 1
        if not counts:
            return 'Nothing in this drawing is tagged yet.'
        return 'Tags in this drawing: ' + ', '.join(f'{k} ({v})' for k, v in sorted(counts.items()))
    ids = [o['id'] for o in d.objs if set(tags_of(o)) & set(tg)]
    if not ids:
        return f'Nothing is tagged {", ".join(tg)}.'
    d.ui.append({'cmd': 'select', 'args': {'ids': ids[:200]}})
    d.selected = ids[:200]
    return f'{_n(len(ids), "object")} tagged {", ".join(tg)} selected.'


def t_save_selection_set(d: Drawing, a: dict, name='', which='new'):
    nm = str(name or '').strip()[:MAX_NAME]
    if not nm:
        return 'refused: a selection set needs a name.'
    recs = d.select(which)
    if not recs:
        return f'refused: {which!r} matched nothing to save.'
    e = _ext(d)
    e['sets'][nm] = [o['id'] for o in recs]
    return f'Selection set "{nm}" saved with {_n(len(recs), "object")}.'


def t_recall_selection_set(d: Drawing, a: dict, name=''):
    e = _ext(d)
    nm = str(name or '').strip()[:MAX_NAME]
    if not nm:
        if not e['sets']:
            return 'No selection sets are saved in this drawing.'
        return 'Selection sets: ' + ', '.join(f'{k} ({len(v)})' for k, v in sorted(e['sets'].items()))
    ids = e['sets'].get(nm)
    if ids is None:
        have = ', '.join(sorted(e['sets'])) or 'none'
        return f'refused: no selection set named "{nm}". Saved sets: {have}.'
    live = [i for i in ids if d.find(i)]
    gone = len(ids) - len(live)
    d.ui.append({'cmd': 'select', 'args': {'ids': live[:200]}})
    d.selected = live[:200]
    tail = f', {gone} no longer in the drawing' if gone else ''
    return f'Selection set "{nm}": {_n(len(live), "object")} selected{tail}.'


_WHICH = {'type': 'string', 'description': '"new", "all", a kind, a group name, or a list of ids'}

TOOLS = [
    (
        {
            'name': 'set_layer',
            'description': 'Put objects on a named layer (created if it does not exist). Layers are saved with the drawing.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'which': _WHICH,
                    'layer': {'type': 'string', 'description': 'layer name, e.g. "Structure"'},
                },
                'required': ['layer'],
            },
        },
        t_set_layer,
    ),
    (
        {
            'name': 'layer_visibility',
            'description': 'Hide/show and lock/unlock a whole layer at once; every object on it follows.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'layer': {'type': 'string'},
                    'hidden': {'type': 'boolean'},
                    'locked': {'type': 'boolean'},
                },
                'required': ['layer'],
            },
        },
        t_layer_visibility,
    ),
    (
        {
            'name': 'tag_objects',
            'description': 'Add or remove free-text tags on objects. Tags are lower-cased and de-duplicated.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'which': _WHICH,
                    'tags': {'type': 'array', 'items': {'type': 'string'}},
                    'mode': {'type': 'string', 'enum': ['add', 'remove']},
                },
                'required': ['tags'],
            },
        },
        t_tag_objects,
    ),
    (
        {
            'name': 'select_by_tag',
            'description': 'Select everything carrying a tag. With no tag, lists the tags in the drawing with counts.',
            'input_schema': {'type': 'object', 'properties': {'tag': {'type': 'string'}}},
        },
        t_select_by_tag,
    ),
    (
        {
            'name': 'save_selection_set',
            'description': 'Name a set of objects so it can be recalled later; saved with the drawing.',
            'input_schema': {
                'type': 'object',
                'properties': {'name': {'type': 'string'}, 'which': _WHICH},
                'required': ['name'],
            },
        },
        t_save_selection_set,
    ),
    (
        {
            'name': 'recall_selection_set',
            'description': 'Select a saved selection set again. With no name, lists the sets with their sizes.',
            'input_schema': {'type': 'object', 'properties': {'name': {'type': 'string'}}},
        },
        t_recall_selection_set,
    ),
]

EXAMPLES = [
    {
        'ask': 'put the walls on a Structure layer and hide it',
        'calls': [
            {'tool': 'set_layer', 'args': {'which': 'walls', 'layer': 'Structure'}},
            {'tool': 'layer_visibility', 'args': {'layer': 'Structure', 'hidden': True}},
        ],
    },
    {
        'ask': 'tag the new objects fire-rated and select everything fire-rated',
        'calls': [
            {'tool': 'tag_objects', 'args': {'which': 'new', 'tags': ['fire-rated']}},
            {'tool': 'select_by_tag', 'args': {'tag': 'fire-rated'}},
        ],
    },
    {
        'ask': 'remember this selection as north wing',
        'calls': [{'tool': 'save_selection_set', 'args': {'name': 'north wing', 'which': 'new'}}],
    },
    {
        'ask': 'show the outliner as a tree',
        'calls': [{'tool': 'press_button', 'args': {'id': 'o_outliner', 'args': {'on': True}}}],
    },
]
