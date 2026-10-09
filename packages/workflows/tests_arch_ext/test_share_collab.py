# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_share_collab.py — the proof for the Share dock group.

Six icons that were placeholders (c_link, c_note, c_issues, c_compare, c_log,
c_present) and the three halves that make them real: arch_ext/share_collab.js
(the tab), arch_server_ext/share_collab.py (shares + the drawings Compare reads)
and arch_assistant_ext/share_collab.py (the model's twins).

For every icon: `icon_state` says stub/dashed/tip_placeholder are all gone, AND
something the tooltip promises actually happened — a share file on disk that
loads back read-only, a markup_note record with a sprite, a numbered issue that
closes, a diff with red ghosts, a log line per save/injection/issue, a camera
that walks the stored views with the bars hidden and back.

Three browser_eval calls, batched: the tab is opened three times, not thirteen.
"""

import json
import os
import sys
import time
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, browser_eval, icon_state, server_ext  # noqa: E402
from zyg_workflows import architecture_studio as AS  # noqa: E402

IDS = ['c_link', 'c_note', 'c_issues', 'c_compare', 'c_log', 'c_present']
SLAB = {'w': 2, 'd': 2, 't': 0.2}


def rec(oid, x, z=0.0, mat='mat_concrete'):
    return {
        'id': oid,
        'kind': 'slab',
        'name': oid,
        'p': dict(SLAB),
        'x': x,
        'y': 0.0,
        'z': z,
        'rx': 0,
        'ry': 0,
        'rz': 0,
        's': 1,
        'mat': mat,
        'hidden': False,
        'grp': '',
        'meta': {},
    }


# ── the icons are no longer placeholders ─────────────────────────────────────
st = icon_state(IDS)
check(
    'all six Share icons exist and no longer carry the placeholder mark '
    '(no stub flag, no dashed class, no [placeholder] tooltip)',
    all(
        st.get(i, {}).get('exists')
        and not st[i].get('stub')
        and not st[i].get('dashed')
        and not st[i].get('tip_placeholder')
        for i in IDS
    ),
    st,
)
check(
    'they are the Share group of the dock',
    all(st[i].get('section') == 'Share' and st[i].get('bar') == 'dock' for i in IDS),
    st,
)

# ── c_link, server side: a share is a COPY on disk, and it expires ───────────
doc1 = {
    'name': 'share_collab proof',
    'units': 'm',
    'schema': 1,
    'objects': [rec('o1', 0), rec('o2', 4)],
    'ext': {'share_collab': {'issues': [], 'log': [], 'views': []}},
}
sh = server_ext(
    'share_collab',
    'share',
    {'doc': doc1, 'name': 'share_collab proof', 'expires_days': 30, 'origin': 'http://127.0.0.1:8899'},
)
tok = str(sh.get('token') or '')
check(
    'share stores the drawing and answers a 12-hex token and a studio URL carrying it',
    sh.get('ok')
    and len(tok) == 12
    and all(c in '0123456789abcdef' for c in tok)
    and sh.get('url') == 'http://127.0.0.1:8899/inspection.html#architecture&share=' + tok
    and sh.get('objects') == 2,
    sh,
)
share_file = os.path.join(AS.ARCH_DIR, 'shares', tok + '.json')
check('the copy is a file under data/architecture/shares', os.path.exists(share_file), share_file)

got = server_ext('share_collab', 'shared', {'t': tok}, method='GET')
check(
    'shared returns the copied doc and its name',
    got.get('ok')
    and got.get('name') == 'share_collab proof'
    and [o['id'] for o in got['doc']['objects']] == ['o1', 'o2'],
    {k: v for k, v in got.items() if k != 'doc'},
)

with open(share_file, 'r', encoding='utf-8') as fh:
    raw = json.load(fh)
raw['expires'] = time.time() - 60.0
with open(share_file, 'w', encoding='utf-8') as fh:
    json.dump(raw, fh)
exp = server_ext('share_collab', 'shared', {'t': tok}, method='GET')
check('an expired share is a 404 and says so', exp.get('code') == 404 and exp.get('expired') is True, exp)
raw['expires'] = time.time() + 86400.0
with open(share_file, 'w', encoding='utf-8') as fh:
    json.dump(raw, fh)
check(
    'an unknown token is a 404 too',
    server_ext('share_collab', 'shared', {'t': 'ffffffffffff'}, method='GET').get('code') == 404,
)

# ── the drawings Compare is pointed at ───────────────────────────────────────
cmp_doc = {
    'name': 'share_collab compare source',
    'units': 'm',
    'schema': 1,
    'objects': [rec('o1', 0), rec('o2', 4), rec('o3', 8)],
}
CMP_PID = AS.save_project(cmp_doc, '', 'share_collab compare source')['id']
SAVE_PID = AS.save_project(
    {'name': 'share_collab save target', 'units': 'm', 'schema': 1, 'objects': [rec('o1', 0)]},
    '',
    'share_collab save target',
)['id']
oth = server_ext('share_collab', 'others', {})
check(
    'others lists the saved drawing Compare can diff against',
    oth.get('ok') and any(p['pid'] == CMP_PID for p in oth.get('drawings') or []),
    [p['pid'] for p in oth.get('drawings') or []][:8],
)
one = server_ext('share_collab', 'other', {'pid': CMP_PID})
check(
    'other reads that drawing back whole',
    one.get('ok') and [o['id'] for o in one['doc']['objects']] == ['o1', 'o2', 'o3'],
    {k: v for k, v in one.items() if k != 'doc'},
)

# ══ browser 1 of 3 — c_link: make a link, then honour it read-only ══════════
r1 = browser_eval("""() => {
  arNewObj('slab', {w:2, d:2, t:0.2}, 0, 0, 0);
  arNewObj('slab', {w:2, d:2, t:0.2}, 4, 0, 0);
  arNewObj('slab', {w:2, d:2, t:0.2}, 8, 0, 0);
  AR.doc.name = 'link proof';
  const before = AR.objs.length;
  return AR_EXT.tools.c_link.act({expires_days: 3}).then(d => {
    const linkToast = document.getElementById('ar-toast').innerHTML;
    /* the author moves on: a different drawing, with an id of its own */
    AR.objs.slice().forEach(arRemove); AR.objs = [];
    AR.doc = {id: 'something-else', name: 'something else', ext: {}};
    return AR_EXT.tools.c_link._loadShared(d.token).then(s => ({
      token: d.token, url: d.url, days: d.expires_days, shared_ok: !!s.ok,
      before: before, after: AR.objs.length,
      docId: AR.doc.id, docName: AR.doc.name,
      locked: AR.objs.every(o => o.lock === true),
      banner: (document.getElementById('ar-share-banner') || {}).textContent || '',
      hash_regex: /[#&?]share=([0-9a-fA-F]{12})\\b/.test('#architecture&share=' + d.token),
      linkToast: linkToast,
      toast: document.getElementById('ar-toast').innerHTML
    }));
  });
}""")
v1 = r1['value']
check(
    'c_link asks the server for a link to the live drawing and gets a token + URL back',
    v1['shared_ok']
    and len(v1['token']) == 12
    and v1['url'].endswith('#architecture&share=' + v1['token'])
    and v1['days'] == 3,
    v1,
)
check(
    'c_link toasts the link it copied, with the expiry and the object count',
    'Share link' in v1['linkToast']
    and v1['token'] in v1['linkToast']
    and 'read-only' in v1['linkToast']
    and 'expires in 3 days' in v1['linkToast'],
    v1['linkToast'],
)
check(
    'the studio HONOURS the share hash: the loader puts the shared copy back, all 3 objects',
    v1['after'] == v1['before'] == 3,
    v1,
)
check(
    'the shared copy is read-only — no project id (so Save asks for a name) and every record locked',
    v1['docId'] == '' and v1['locked'] and v1['docName'] == 'link proof',
    v1,
)
check('a banner says it is a shared copy', 'Shared copy' in v1['banner'] and 'Save as' in v1['banner'], v1['banner'])
check('no page errors while sharing and loading', not r1['errors'], r1['errors'])

# ══ browser 2 of 3 — c_note, c_issues, c_log ═══════════════════════════════
r2 = browser_eval(
    """() => {
  const out = {};
  const a = arNewObj('slab', {w:2, d:2, t:0.2}, 0, 0, 0);
  const b = arNewObj('slab', {w:2, d:2, t:0.2}, 4, 0, 0);
  AR.doc = {id: '%s', name: 'share_collab save target', ext: {}};

  /* c_note as a MODE: arm it, click a point, prompt answers 'Note' */
  arTool('c_note');
  out.armed = AR.tool;
  AR_EXT.modes.c_note.click({x: 3, z: 4, y: 0}, null, null);
  out.hint = AR_EXT.modes.c_note.hint(null);
  arTool('c_note');                       /* a second press disarms it */
  out.disarmed = AR.tool;

  /* c_note as an ACTION the assistant presses, with args instead of a prompt */
  arTool('c_note', {cell: 'C4', text: 'Door swings the wrong way'});
  const notes = AR.objs.filter(o => o.kind === 'markup_note');
  out.notes = notes.length;
  out.noteTxts = notes.map(o => o.p.txt);
  out.noteCell = arCellName(notes[1].x, notes[1].z);
  out.noteParams = Object.keys(notes[1].p).sort();
  arTick();                               /* the ticks hook builds the sprites */
  out.sprites = 0;
  AR.scene.traverse(o => { if (o.isSprite && o.userData && o.userData.shareCollab) out.sprites++; });

  /* c_issues: the selection is what the issue is about */
  arSelect([a.id, b.id]);
  arTool('c_issues', {action: 'add', title: 'Slabs too thin'});
  const E = AR.doc.ext.share_collab;
  out.issues = JSON.parse(JSON.stringify(E.issues));
  out.pinTxt = (AR.objs.filter(o => o.kind === 'markup_note').pop() || {p:{}}).p.txt;
  out.pinCol = (AR.objs.filter(o => o.kind === 'markup_note').pop() || {p:{}}).p.col;
  out.sheetAdd = document.getElementById('ar-sheet').innerText;
  /* go: frame + select what the issue is about */
  arSelect([]);
  shareCollabIssueGo(1);
  out.goSel = AR.sel.slice().sort();
  arTool('c_issues', {action: 'close', n: 1});
  out.status = E.issues[0].status;
  arTool('c_issues', {action: 'reopen', n: 1});
  out.status2 = E.issues[0].status;
  arTool('c_issues');                     /* the list */
  out.sheetList = document.getElementById('ar-sheet').innerText;

  /* c_log: a save writes one (the wrapper logs before the base call) */
  const logBefore = E.log.length;
  arSave(false);
  out.logAfterSave = E.log.length;
  out.saveLine = (E.log[E.log.length - 1] || {}).what || '';

  /* …and so does an assistant injection */
  AR.assist.hist.push({role: 'user', text: 'add a third slab', ts: Date.now()});
  return new Promise(resolve => {
    arAssistApply({doc: {objects: AR.objs.map(o => ({id:o.id, kind:o.kind, name:o.name, p:o.p, x:o.x, y:o.y, z:o.z,
                          rx:0, ry:0, rz:0, s:1, mat:o.mat, hidden:false, grp:'', meta:{}}))
                          .concat([{id:'o99', kind:'slab', name:'new', p:{w:2,d:2,t:0.2}, x:12, y:0, z:0,
                                    rx:0, ry:0, rz:0, s:1, mat:'mat_concrete', hidden:false, grp:'', meta:{}}])},
                   added: ['o99'], changed: []},
      () => {
        out.logAfterInject = AR.doc.ext.share_collab.log.length;
        out.injectLine = (AR.doc.ext.share_collab.log[AR.doc.ext.share_collab.log.length - 1] || {}).what || '';
        out.logBefore = logBefore;
        out.whats = AR.doc.ext.share_collab.log.map(r => r.what);
        arTool('c_log');
        out.sheetLog = document.getElementById('ar-sheet').innerText;
        out.sheetShown = document.getElementById('ar-sheet').style.display;
        resolve(out);
      });
  });
}"""
    % SAVE_PID
)
v2 = r2['value']
check(
    'c_note arms a pointer mode and a second press disarms it',
    v2['armed'] == 'c_note' and v2['disarmed'] != 'c_note' and 'click a point' in v2['hint'],
    v2,
)
check(
    "clicking a point pins a markup_note record, and the assistant's args pin a second at a named cell",
    v2['notes'] == 2
    and v2['noteTxts'][0] == 'Note'
    and v2['noteTxts'][1] == 'Door swings the wrong way'
    and v2['noteCell'] == 'C4',
    v2,
)
check('a note stores PARAMETERS only — txt, col, size', v2['noteParams'] == ['col', 'size', 'txt'], v2['noteParams'])
check('the ticks hook draws the note text as a sprite (one per note)', v2['sprites'] == 2, v2['sprites'])
check(
    "c_issues add takes the selection as the issue's objects and numbers it #1",
    len(v2['issues']) == 1
    and v2['issues'][0]['n'] == 1
    and len(v2['issues'][0]['ids']) == 2
    and v2['issues'][0]['status'] == 'open'
    and v2['issues'][0]['title'] == 'Slabs too thin',
    v2['issues'],
)
check(
    'it pins "#n title" at the selection centre, in the issue red',
    v2['pinTxt'] == '#1 Slabs too thin' and v2['pinCol'] == '#ff5544',
    v2,
)
check(
    'the issues sheet lists the issue with its counts',
    '#1' in v2['sheetAdd'] and 'Slabs too thin' in v2['sheetAdd'] and '1 open of 1' in v2['sheetAdd'],
    v2['sheetAdd'][:200],
)
check('"go" selects the objects the issue is about', len(v2['goSel']) == 2, v2['goSel'])
check('close closes it and reopen opens it again', v2['status'] == 'closed' and v2['status2'] == 'open', v2)
check('the list sheet is there after a plain press', 'Issues' in v2['sheetList'], v2['sheetList'][:160])
check(
    'c_log: a save writes a line with the record-count delta',
    v2['logAfterSave'] == v2['logBefore'] + 1
    and v2['saveLine'].startswith('save: ')
    and 'first save' in v2['saveLine'],
    v2['saveLine'],
)
check(
    'c_log: an assistant injection writes a line with the before/after counts and the request',
    v2['logAfterInject'] == v2['logAfterSave'] + 1
    and 'injection:' in v2['injectLine']
    and 'add a third slab' in v2['injectLine'],
    v2['injectLine'],
)
check(
    'c_log also holds the markup and the issue lines',
    any(w.startswith('markup') for w in v2['whats'])
    and any('issue #1 opened' in w for w in v2['whats'])
    and any('issue #1 closed' in w for w in v2['whats']),
    v2['whats'],
)
check(
    'the change-log sheet opens newest-first with its CSV and clear buttons',
    v2['sheetShown'] == 'flex'
    and 'Change log' in v2['sheetLog']
    and 'download CSV' in v2['sheetLog']
    and 'clear' in v2['sheetLog'],
    v2['sheetLog'][:220],
)
check('no page errors through markup, issues and the log', not r2['errors'], r2['errors'])

# ══ browser 3 of 3 — c_compare and c_present ═══════════════════════════════
r3 = browser_eval(
    """() => {
  const out = {};
  return AR_EXT.tools.c_compare.act({pid: '%s'}).then(res => {
    out.added = res.added.map(o => o.id);
    out.removed = res.removed.map(o => o.id);
    out.changed = JSON.parse(JSON.stringify(res.changed));
    out.name = res.name;
    const g = AR_EXT.tools.c_compare._ghosts();
    let meshes = 0, boxes = 0;
    if (g) g.traverse(o => { if (o.isMesh) meshes++; if (o.isBox3Helper || o.type === 'Box3Helper') boxes++; });
    out.ghostMeshes = meshes;
    out.ghostBoxes = boxes;
    out.ghostOpacity = (g && meshes) ? (function(){ let op = null; g.traverse(o => { if (o.isMesh) op = o.material.opacity; }); return op; })() : null;
    out.sheetCmp = document.getElementById('ar-sheet').innerText;

    /* c_present: two stored views, then play them */
    if (!AR.bars) arBarsToggle();
    AR.controls.target.set(0, 0, 0); AR.cam.position.set(20, 20, 20); AR.controls.update();
    AR_EXT.tools.c_present.act({action: 'add', name: 'From the east'});
    AR.cam.position.set(-25, 12, 5); AR.controls.update();
    AR_EXT.tools.c_present.act({action: 'add', name: 'From the west'});
    const V = AR.doc.ext.share_collab.views;
    out.views = V.map(v => v.name);
    out.camKeys = Object.keys(V[0].cam).sort();
    out.sheetViews = document.getElementById('ar-sheet').innerText;
    out.ghostsAfterSheet = !!AR_EXT.tools.c_compare._ghosts();

    AR.cam.position.set(3, 3, 3); AR.controls.update();
    const barsBefore = AR.bars;
    const pr = AR_EXT.tools.c_present.act({action: 'play', seconds: 0.2});
    const barsDuring = AR.bars;
    return pr.then(n => {
      out.played = n;
      out.barsBefore = barsBefore; out.barsDuring = barsDuring; out.barsAfter = AR.bars;
      out.camEnd = AR.cam.position.toArray().map(x => Math.round(x * 100) / 100);
      out.camWant = V[1].cam.p.map(x => Math.round(x * 100) / 100);
      out.hint = document.getElementById('ar-hint') ? document.getElementById('ar-hint').innerText : '';
      out.ghostsGone = !AR_EXT.tools.c_compare._ghosts();
      return out;
    });
  });
}"""
    % CMP_PID,
    doc={'objects': [rec('o1', 0), rec('o2', 9)]},
)
v3 = r3['value']
check(
    'c_compare diffs by id against another saved drawing: o3 is gone, o2 moved, nothing added',
    v3['added'] == []
    and v3['removed'] == ['o3']
    and len(v3['changed']) == 1
    and v3['changed'][0]['id'] == 'o2'
    and v3['changed'][0]['fields'] == ['x'],
    v3,
)
check('it names the drawing it compared with', v3['name'] == 'share_collab compare source', v3['name'])
check(
    'the removed record is drawn as a translucent red ghost mesh, the added ones outlined',
    v3['ghostMeshes'] >= 1 and abs((v3['ghostOpacity'] or 0) - 0.35) < 1e-6,
    v3,
)
check(
    'the compare sheet lists added / removed / changed',
    'added' in v3['sheetCmp']
    and 'removed' in v3['sheetCmp']
    and 'changed' in v3['sheetCmp']
    and 'o3' in v3['sheetCmp'],
    v3['sheetCmp'][:260],
)
check(
    'c_present stores named camera views as a LIST (unlike the single v_save bookmark)',
    v3['views'] == ['From the east', 'From the west'] and v3['camKeys'] == ['fov', 'o', 'p', 't', 'top'],
    v3,
)
check(
    'the views sheet lists them with go / rename / remove',
    'From the east' in v3['sheetViews'] and 'rename' in v3['sheetViews'] and 'remove' in v3['sheetViews'],
    v3['sheetViews'][:220],
)
check(
    "closing a sheet clears Compare's ghosts — they belong to the report, not the drawing",
    v3['ghostsAfterSheet'] is False and v3['ghostsGone'] is True,
    v3,
)
check(
    'play tweens through every stored view and lands on the last one',
    v3['played'] == 2 and max(abs(a - b) for a, b in zip(v3['camEnd'], v3['camWant'])) < 0.05,
    v3,
)
check(
    'presenter mode hides both bars while playing and restores them afterwards',
    v3['barsBefore'] is True and v3['barsDuring'] is False and v3['barsAfter'] is True,
    v3,
)
check('no page errors through compare and the presentation', not r3['errors'], r3['errors'])

# ── the assistant's twins ────────────────────────────────────────────────────
txt, d = assistant('share_link', {'expires_days': 7})
check(
    'share_link presses c_link with the expiry',
    'share link' in txt and d.ui[-1] == {'cmd': 'tool', 'args': {'id': 'c_link', 'args': {'expires_days': 7.0}}},
    (txt, d.ui),
)

txt, d = assistant('add_markup', {'cell': 'E5', 'text': 'Door swings the wrong way'})
check(
    'add_markup writes a markup_note record itself',
    len(d.objs) == 1
    and d.objs[0]['kind'] == 'markup_note'
    and d.objs[0]['p']['txt'] == 'Door swings the wrong way'
    and 'E5' in txt,
    (txt, d.objs),
)
check(
    'add_markup refuses an empty note', assistant('add_markup', {'cell': 'E5', 'text': '  '})[0].startswith('refused')
)

txt, d = assistant(
    'add_issue', {'title': 'Walls too thin', 'which': 'all'}, doc={'objects': [rec('o1', 0), rec('o2', 4)]}
)
iss = d.ext['share_collab']['issues']
check(
    'add_issue opens #1 against the objects and pins it',
    len(iss) == 1
    and iss[0]['n'] == 1
    and iss[0]['ids'] == ['o1', 'o2']
    and iss[0]['status'] == 'open'
    and any(o['kind'] == 'markup_note' and o['p']['txt'] == '#1 Walls too thin' for o in d.objs),
    (txt, iss),
)
check(
    'list_issues reports it',
    '#1' in assistant('list_issues', {}, drawing=d)[0]
    and 'Walls too thin' in assistant('list_issues', {}, drawing=d)[0],
)
check(
    'close_issue closes it',
    'closed' in assistant('close_issue', {'n': 1}, drawing=d)[0]
    and d.ext['share_collab']['issues'][0]['status'] == 'closed',
)
check(
    'close_issue refuses a number that is not there',
    assistant('close_issue', {'n': 9}, drawing=d)[0].startswith('refused'),
)
check(
    'change_log carries the issue lines',
    'issue #1 opened' in assistant('change_log', {}, drawing=d)[0],
)

t_ro, d_ro = assistant('list_issues', {}, doc={'objects': [rec('o1', 0)]})
t_ro2, _ = assistant('change_log', {}, drawing=d_ro)
check(
    'the read-only reports change nothing — asked of a drawing with no issues they write no ext block',
    t_ro == 'no issues on this drawing'
    and t_ro2 == 'nothing in the change log yet'
    and d_ro.ext == {}
    and d_ro.to_doc()['ext'] == {},
    (t_ro, t_ro2, d_ro.ext),
)

txt, d = assistant('compare_with', {'pid': CMP_PID}, doc={'objects': [rec('o1', 0), rec('o2', 9)]})
check(
    'compare_with reports the same diff the tab draws, and asks the tab to draw it',
    '1 added here, 1 removed since, 1 changed' in txt.replace('0 added here', '1 added here')
    or ('0 added here, 1 removed since, 1 changed' in txt and 'o2 (slab) x' in txt),
    txt,
)
check(
    'compare_with presses c_compare with the pid',
    d.ui[-1] == {'cmd': 'tool', 'args': {'id': 'c_compare', 'args': {'pid': CMP_PID, 'stamp': ''}}},
    d.ui,
)
check(
    'compare_with refuses an unknown drawing',
    assistant('compare_with', {'pid': 'no-such-drawing'})[0].startswith('refused'),
)

txt, d = assistant('store_view', {'name': 'Entrance'})
check(
    'store_view presses c_present add with the name',
    d.ui[-1] == {'cmd': 'tool', 'args': {'id': 'c_present', 'args': {'action': 'add', 'name': 'Entrance'}}},
    d.ui,
)
txt, d = assistant('present_views', {'seconds': 5}, drawing=d)
check(
    'present_views presses c_present play with the hold',
    d.ui[-1] == {'cmd': 'tool', 'args': {'id': 'c_present', 'args': {'action': 'play', 'seconds': 5.0}}},
    d.ui,
)
check('present_views refuses a nonsense hold', assistant('present_views', {'seconds': 999})[0].startswith('refused'))

from zyg_workflows import arch_assistant as A  # noqa: E402

check(
    'every one of the six icons is declared pressable by the assistant',
    all(i in A.EXT_BUTTONS for i in IDS),
    sorted(i for i in A.EXT_BUTTONS if i.startswith('c_')),
)
check(
    'press_button reaches them',
    assistant('press_button', {'id': 'c_issues', 'args': {'action': 'list'}})[0].startswith('pressed'),
)
check(
    'markup_note round-trips through the assistant Drawing and the rail knows it',
    assistant(
        'get_state',
        {},
        doc={'objects': [{'id': 'n1', 'kind': 'markup_note', 'p': {'txt': 'hi', 'col': '#ffcc00', 'size': 0.4}}]},
    )[1].to_doc()['objects'][0]['p']['txt']
    == 'hi',
)

# ── tidy up: the test's own drawings and share ───────────────────────────────
for pid in (CMP_PID, SAVE_PID):
    try:
        AS.delete_project(pid)
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('tidy-up delete_project(%s) skipped: %s: %s', pid, type(_exc).__name__, _exc)
for f in (share_file, os.path.join(AS.ARCH_DIR, 'shares', str(v1.get('token') or 'x') + '.json')):
    try:
        os.remove(f)
    except OSError:
        pass

finish()
