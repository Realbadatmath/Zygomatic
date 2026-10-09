# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_organise_layers.py — proves the four Organise icons
(o_outliner, o_layers, o_tags, o_sets) are wired for real:

  * none of them is a placeholder any more (no stub flag, no dashed class, no
    "[placeholder]" tooltip) — icon_state, straight from the live tab;
  * the tree outliner really renders storey headers, group nodes and rows that
    select when clicked, and a heading collapses;
  * the layer manager creates, assigns, hides, shows and locks for real, on the
    records, and opens a sheet with a row per layer;
  * tags land in rec.meta.tags and select-by-tag sets AR.sel to exactly the
    tagged ids;
  * a selection set round-trips through AR.doc.ext and survives arDocOut();
  * the assistant twins do the same job on a Drawing and to_doc() carries
    meta and ext back to the tab.

Three browser passes in total (icon_state + two browser_eval).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, browser_eval, icon_state  # noqa: E402

IDS = ['o_outliner', 'o_layers', 'o_tags', 'o_sets']

# ── 1. the placeholder mark is gone ──────────────────────────────────────────
st = icon_state(IDS)
for i in IDS:
    check(
        '%s is real (exists, stub false, dashed false, tip_placeholder false)' % i,
        st.get(i, {}).get('exists')
        and not st[i].get('stub')
        and not st[i].get('dashed')
        and not st[i].get('tip_placeholder'),
        st.get(i),
    )

# ── 2. the tree outliner + the layer manager ─────────────────────────────────
r1 = browser_eval("""() => {
  const mk = (n, x, y, g) => { const r = arNewObj('slab', {w:2, d:2, t:0.2}, x, 0, y);
                               r.name = n; r.grp = g; arApplyTransform(r); return r; };
  const a = mk('A1', 0, 0, 'Shell'),   b = mk('A2', 3, 0, 'Shell'),   c = mk('A3', 6, 0, 'Fitout');
  const d = mk('B1', 0, 2.7, 'Shell'), e = mk('B2', 3, 2.7, 'Fitout'), f = mk('B3', 6, 2.7, 'Fitout');
  arPanel();
  const flat = document.getElementById('ar-outl').querySelectorAll('.ol-storey').length;

  arTool('o_outliner', {on: true});
  const host = () => document.getElementById('ar-outl');
  const storeys = host().querySelectorAll('.ol-storey').length;
  const groups  = host().querySelectorAll('.ol-group').length;
  const rows0   = host().querySelectorAll('.ol-rec').length;
  const switchOn = !!AR_EXT.tools.o_outliner.on();

  /* clicking a row selects that record */
  const row = host().querySelector('.ol-rec');
  const rowId = row.getAttribute('data-id');
  row.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  const selByClick = AR.sel.slice();

  /* clicking a storey heading collapses it */
  host().querySelector('.ol-storey').dispatchEvent(new MouseEvent('click', {bubbles: true}));
  const rowsCollapsed = host().querySelectorAll('.ol-rec').length;

  /* the switch gives the flat list back */
  arTool('o_outliner', {on: false});
  const flatAgain = host().querySelectorAll('.ol-storey').length;
  const flatRows  = host().querySelectorAll('.ar-orow').length;

  /* ── layers ── */
  arSelect([a.id, b.id, d.id]);
  arTool('o_layers', {layer: 'Structure', action: 'new'});
  const names1 = AR.doc.ext.organise_layers.layers.map(L => L.name);
  arTool('o_layers', {layer: 'Structure', action: 'assign'});
  const assigned = [a, b, d].map(r => r.meta.layer);
  const others   = [c, e, f].map(r => (r.meta || {}).layer || null);

  arTool('o_layers', {layer: 'Structure', action: 'hide'});
  const hid = {mine: [a, b, d].map(r => !!r.hidden), rest: [c, e, f].map(r => !!r.hidden)};
  arTool('o_layers', {layer: 'Structure', action: 'show'});
  const shown = [a, b, d].map(r => !!r.hidden);
  arTool('o_layers', {layer: 'Structure', action: 'lock'});
  const locked = [a, b, d].map(r => !!r.lock);
  const pickable = AR.objs.filter(o => o.node && !o.hidden && !o.lock).map(o => o.id);
  arTool('o_layers', {layer: 'Structure', action: 'unlock'});
  const unlocked = [a, b, d].map(r => !!r.lock);

  const sheet = document.getElementById('ar-sheet');
  const sheetRows = sheet ? sheet.querySelectorAll('tr.ol-layer').length : 0;
  const sheetOpen = !!(sheet && sheet.style.display !== 'none');

  arTool('o_layers', {layer: 'Structure', action: 'delete'});
  const afterDelete = {names: AR.doc.ext.organise_layers.layers.map(L => L.name),
                       layers: [a, b, d].map(r => r.meta.layer)};

  return {ids: [a.id, b.id, c.id, d.id, e.id, f.id], flat, storeys, groups, rows0, switchOn,
          rowId, selByClick, rowsCollapsed, flatAgain, flatRows, names1, assigned, others,
          hid, shown, locked, pickable, unlocked, sheetRows, sheetOpen, afterDelete};
}""")
v = r1['value']
check('no page errors in the outliner/layers pass', not r1['errors'], r1['errors'])
check('the flat outliner has no tree nodes before the switch', v['flat'] == 0, v['flat'])
check('the tree switch latches on', v['switchOn'] is True, v['switchOn'])
check('the tree shows one header per storey (2 storeys)', v['storeys'] == 2, v)
check('the tree shows a node per group per storey (Shell/Fitout x 2 = 4)', v['groups'] == 4, v)
check('every record has a row under its group (6)', v['rows0'] == 6, v)
check('clicking a tree row selects that record', v['selByClick'] == [v['rowId']], v)
check('clicking a storey heading collapses its rows', v['rowsCollapsed'] < v['rows0'], v)
check('switching the tree off restores the flat list (no nodes, 6 rows)', v['flatAgain'] == 0 and v['flatRows'] == 6, v)
check(
    'o_layers new creates the layer in AR.doc.ext.organise_layers', v['names1'] == ['Default', 'Structure'], v['names1']
)
check(
    'o_layers assign writes rec.meta.layer on the selection only',
    v['assigned'] == ['Structure'] * 3 and all(x in (None, 'Default') for x in v['others']),
    v,
)
check(
    'o_layers hide hides the members and nothing else',
    v['hid']['mine'] == [True] * 3 and v['hid']['rest'] == [False] * 3,
    v['hid'],
)
check('o_layers show brings them back', v['shown'] == [False] * 3, v['shown'])
check(
    'o_layers lock sets rec.lock so arPick cannot reach them',
    v['locked'] == [True] * 3 and all(i not in v['pickable'] for i in v['ids'][:2]),
    v,
)
check('o_layers unlock clears rec.lock', v['unlocked'] == [False] * 3, v['unlocked'])
check('the layer manager sheet is open with a row per layer', v['sheetOpen'] and v['sheetRows'] >= 2, v)
check(
    'deleting a layer returns its members to Default',
    v['afterDelete']['names'] == ['Default'] and v['afterDelete']['layers'] == ['Default'] * 3,
    v['afterDelete'],
)

# ── 3. tags + selection sets + persistence ───────────────────────────────────
r2 = browser_eval("""() => {
  const mk = (n, x, y, g) => { const r = arNewObj('slab', {w:2, d:2, t:0.2}, x, 0, y);
                               r.name = n; r.grp = g; arApplyTransform(r); return r; };
  const a = mk('A1', 0, 0, 'Shell'),   b = mk('A2', 3, 0, 'Shell'),   c = mk('A3', 6, 0, 'Fitout');
  const d = mk('B1', 0, 2.7, 'Shell'), e = mk('B2', 3, 2.7, 'Fitout'), f = mk('B3', 6, 2.7, 'Fitout');

  /* ── tags ── */
  arSelect([a.id, c.id]);
  arTool('o_tags', {tags: ['Fire-Rated', ' phase-2 '], mode: 'add'});
  const tagged = {a: a.meta.tags, c: c.meta.tags, b: (b.meta || {}).tags || null};
  arSelect([c.id]);
  arTool('o_tags', {tags: ['phase-2'], mode: 'remove'});
  const afterRemove = c.meta.tags;
  arSelect([]);
  arTool('o_tags', {tags: ['fire-rated'], mode: 'select'});
  const selByTag = AR.sel.slice();
  arSelect([]);
  arTool('o_tags', {mode: 'select'});                       /* no tags -> the tag sheet */
  const tagSheetRows = document.querySelectorAll('#ar-sheet tr.ol-tag').length;

  /* ── selection sets ── */
  arSelect([b.id, d.id, f.id]);
  arTool('o_sets', {name: 'north wing', action: 'save'});
  const saved = JSON.parse(JSON.stringify(AR.doc.ext.organise_layers.sets));
  arSelect([a.id]);
  arRemove(f);                                              /* one member goes away */
  arTool('o_sets', {name: 'north wing', action: 'recall'});
  const recalled = AR.sel.slice();
  const toast = document.getElementById('ar-toast').innerHTML;
  arTool('o_sets', {action: 'list'});
  const setSheetRows = document.querySelectorAll('#ar-sheet tr.ol-set').length;

  /* ── persistence ── */
  arTool('o_layers', {layer: 'Envelope', action: 'new'});
  arSelect([a.id]); arTool('o_layers', {layer: 'Envelope', action: 'assign'});
  const out = arDocOut();
  const outRec = out.objects.filter(o => o.id === a.id)[0];
  const helper = {api: Object.keys(window.organise_layers || {}).sort(),
                  layerOf: window.organise_layers.layerOf(a),
                  tagsOf: window.organise_layers.tagsOf(a),
                  visible: window.organise_layers.visibleLayers()};
  arTool('o_layers', {layer: 'Envelope', action: 'hide'});
  const visibleAfterHide = window.organise_layers.visibleLayers();

  return {ids: {a: a.id, b: b.id, c: c.id, d: d.id, e: e.id, f: f.id},
          tagged, afterRemove, selByTag, tagSheetRows, saved, recalled, toast, setSheetRows,
          outExt: out.ext.organise_layers, outMeta: outRec.meta, helper, visibleAfterHide};
}""")
w = r2['value']
check('no page errors in the tags/sets pass', not r2['errors'], r2['errors'])
check(
    'o_tags add writes normalised tags on the selection only',
    w['tagged']['a'] == ['fire-rated', 'phase-2']
    and w['tagged']['c'] == ['fire-rated', 'phase-2']
    and w['tagged']['b'] is None,
    w['tagged'],
)
check('o_tags remove takes one tag off and leaves the rest', w['afterRemove'] == ['fire-rated'], w['afterRemove'])
check(
    'o_tags select sets AR.sel to exactly the tagged ids',
    sorted(w['selByTag']) == sorted([w['ids']['a'], w['ids']['c']]),
    w['selByTag'],
)
check('o_tags with no tags opens a sheet listing every tag', w['tagSheetRows'] == 2, w['tagSheetRows'])
check(
    'o_sets save keeps the ids in AR.doc.ext.organise_layers.sets',
    w['saved']['north wing'] == [w['ids']['b'], w['ids']['d'], w['ids']['f']],
    w['saved'],
)
check(
    'o_sets recall selects the members that still exist', w['recalled'] == [w['ids']['b'], w['ids']['d']], w['recalled']
)
check('o_sets recall says how many members are gone', 'no longer in the drawing' in w['toast'], w['toast'])
check('o_sets list opens a sheet with a row per set', w['setSheetRows'] == 1, w['setSheetRows'])
check(
    'doc.ext.organise_layers survives arDocOut (layers + sets)',
    [L['name'] for L in w['outExt']['layers']] == ['Default', 'Envelope'] and 'north wing' in w['outExt']['sets'],
    w['outExt'],
)
check(
    'rec.meta (layer + tags) survives arDocOut',
    w['outMeta']['layer'] == 'Envelope' and w['outMeta']['tags'] == ['fire-rated', 'phase-2'],
    w['outMeta'],
)
check(
    'window.organise_layers exposes layerOf/tagsOf/visibleLayers',
    w['helper']['api'] == ['layerOf', 'tagsOf', 'visibleLayers']
    and w['helper']['layerOf'] == 'Envelope'
    and w['helper']['tagsOf'] == ['fire-rated', 'phase-2']
    and w['helper']['visible'] == ['Default', 'Envelope'],
    w['helper'],
)
check('visibleLayers drops a hidden layer', w['visibleAfterHide'] == ['Default'], w['visibleAfterHide'])

# ── 4. the assistant twins ───────────────────────────────────────────────────
DOC = {
    'objects': [
        {'id': 'o1', 'kind': 'wall', 'p': {'len': 4, 'h': 2.7, 't': 0.24}, 'x': 0, 'z': 0},
        {'id': 'o2', 'kind': 'wall', 'p': {'len': 4, 'h': 2.7, 't': 0.24}, 'x': 4, 'z': 0},
        {'id': 'o3', 'kind': 'slab', 'p': {'w': 4, 'd': 4, 't': 0.2}, 'x': 2, 'z': 2},
    ]
}

txt, d = assistant('set_layer', {'which': 'walls', 'layer': 'Structure'}, doc=DOC)
check(
    'set_layer puts the walls on the layer',
    'layer "Structure"' in txt and [o['meta'].get('layer') for o in d.objs] == ['Structure', 'Structure', None],
    txt,
)
check(
    'set_layer registers the layer in d.ext',
    [L['name'] for L in d.ext['organise_layers']['layers']] == ['Default', 'Structure'],
    d.ext,
)

txt, _ = assistant('layer_visibility', {'layer': 'Structure', 'hidden': True, 'locked': True}, drawing=d)
check(
    'layer_visibility hides and locks every member and tells the tab',
    [o['hidden'] for o in d.objs] == [True, True, False]
    and [o.get('lock') for o in d.objs[:2]] == [True, True]
    and d.ui[-1]['cmd'] == 'hide'
    and d.ui[-1]['args']['hidden'] is True,
    (txt, d.ui[-1]),
)
txt, _ = assistant('layer_visibility', {'layer': 'Nope', 'hidden': True}, drawing=d)
check('layer_visibility refuses an unknown layer', txt.startswith('refused'), txt)

txt, _ = assistant('tag_objects', {'which': 'walls', 'tags': ['Fire-Rated', 'PHASE-2'], 'mode': 'add'}, drawing=d)
check(
    'tag_objects normalises and stores the tags',
    d.objs[0]['meta']['tags'] == ['fire-rated', 'phase-2'] and 'tags' not in d.objs[2]['meta'],
    txt,
)
txt, _ = assistant('tag_objects', {'which': ['o2'], 'tags': ['phase-2'], 'mode': 'remove'}, drawing=d)
check('tag_objects remove takes exactly one tag off', d.objs[1]['meta']['tags'] == ['fire-rated'], txt)

txt, _ = assistant('select_by_tag', {'tag': 'phase-2'}, drawing=d)
check(
    'select_by_tag selects through d.ui',
    d.ui[-1]['cmd'] == 'select' and d.ui[-1]['args']['ids'] == ['o1'],
    (txt, d.ui[-1]),
)
txt, _ = assistant('select_by_tag', {}, drawing=d)
check('select_by_tag with no tag lists the tags with counts', 'fire-rated (2)' in txt, txt)

txt, _ = assistant('save_selection_set', {'name': 'north wing', 'which': ['o1', 'o3']}, drawing=d)
check(
    'save_selection_set stores the ids in d.ext',
    d.ext['organise_layers']['sets']['north wing'] == ['o1', 'o3'],
    (txt, d.ext),
)
d.remove([d.find('o3')])
txt, _ = assistant('recall_selection_set', {'name': 'north wing'}, drawing=d)
check(
    'recall_selection_set selects what survives and counts what is gone',
    d.ui[-1]['args']['ids'] == ['o1'] and '1 no longer in the drawing' in txt,
    (txt, d.ui[-1]),
)
txt, _ = assistant('recall_selection_set', {'name': 'ghost'}, drawing=d)
check('recall_selection_set refuses an unknown set', txt.startswith('refused'), txt)

doc = d.to_doc()
check(
    'to_doc carries meta and ext back to the tab',
    doc['objects'][0]['meta']['layer'] == 'Structure'
    and doc['objects'][0]['meta']['tags'] == ['fire-rated', 'phase-2']
    and [L['name'] for L in doc['ext']['organise_layers']['layers']] == ['Default', 'Structure']
    and doc['ext']['organise_layers']['sets'] == {'north wing': ['o1', 'o3']},
    doc['ext'],
)

for i in IDS:
    txt, du = assistant('press_button', {'id': i, 'args': {'action': 'list'}})
    check('the assistant may press %s' % i, txt.startswith('pressed') and du.ui[-1]['args']['id'] == i, txt)

finish()
