# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_file_manage_setup.py — proves the nine File & Setup icons
(f_tmpl, f_ver, f_auto, f_archive, p_prefs, p_theme, p_perf, p_help, p_about)
are wired: none is a placeholder any more, each DOES what its tooltip says in
the live tab, the disk half keeps templates / versions / archives, and the
assistant's twins press the same icons.

Run:  "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_file_manage_setup.py
"""

import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, browser_eval, icon_state, server_ext  # noqa: E402

from zyg_workflows import architecture_studio as ST  # noqa: E402

IDS = ['f_tmpl', 'f_ver', 'f_auto', 'f_archive', 'p_prefs', 'p_theme', 'p_perf', 'p_help', 'p_about']
PID = 'fms-proof-drawing'
NAME = 'FMS proof drawing'


def _vendored_three() -> str:
    """The revision the vendored bundle declares, read off the bytes. r144 is
    what the docs say; the file itself is the only authority About may quote."""
    import re

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'vendor', 'three', 'three.min.js')
    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        head = fh.read(4000)
    m = re.search(r'"(1\d\d)"', head)
    return m.group(1) if m else '?'


VENDORED_THREE = _vendored_three()


def rec(oid, kind, p, x=0.0, z=0.0, y=0.0):
    return {
        'id': oid,
        'kind': kind,
        'name': kind,
        'p': p,
        'x': x,
        'y': y,
        'z': z,
        'rx': 0.0,
        'ry': 0.0,
        'rz': 0.0,
        's': 1,
        'mat': 'mat_concrete',
        'hidden': False,
        'grp': '',
        'meta': {},
    }


# ── 1. no icon is a placeholder any more ────────────────────────────────────
st = icon_state(IDS)
for i in IDS:
    s = st.get(i) or {}
    check(
        '%s is wired: it exists, is not a stub, is not dashed and its tip is not [placeholder]' % i,
        s.get('exists') and not s.get('stub') and not s.get('dashed') and not s.get('tip_placeholder'),
        s,
    )

# ── 2. templates on disk (f_tmpl) ───────────────────────────────────────────
t = server_ext('file_manage_setup', 'templates', {})
names = [r.get('name') for r in (t.get('templates') or [])]
check(
    'the templates route ships at least two templates so the list is never empty',
    t.get('ok') and len(t.get('templates') or []) >= 2,
    names,
)
check('the two stock templates are there by name', 'Empty A4 site' in names and 'Row house 5.4 m' in names, names)
row = [r for r in t['templates'] if r['name'] == 'Row house 5.4 m'][0]
check('the row house template is a whole little building (>= 8 objects)', row['objects'] >= 8, row)

# ── 3. a saved drawing, then the version shelf (f_ver) ──────────────────────
doc = {
    'name': NAME,
    'units': 'm',
    'schema': 1,
    'objects': [
        rec('o1', 'slab', {'w': 6.0, 'd': 8.0, 't': 0.22}, 0, 0, -0.22),
        rec('o2', 'wall', {'len': 6.0, 'h': 2.7, 't': 0.24}, 0, -4.0),
    ],
}
saved = ST.save_project(doc, pid=PID, name=NAME)
check(
    'a drawing saved through architecture_studio.save_project is on disk',
    saved.get('ok') and saved.get('id') == PID,
    saved,
)

# 2026-09-11: the proof shelf sits at its 50-file cap after a few days of runs, so
# "grew by one" could never hold again — make room first (these are this test's own files)
_shelf = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'architecture', 'versions', PID
)
if os.path.isdir(_shelf):
    for _old in sorted(os.listdir(_shelf))[:-40]:
        os.remove(os.path.join(_shelf, _old))
before = server_ext('file_manage_setup', 'versions', {'pid': PID, 'action': 'list'})
snap = server_ext(
    'file_manage_setup',
    'snapshot',
    {'pid': PID, 'doc': {'name': NAME, 'objects': doc['objects'][:1]}, 'label': 'proof'},
)
check('the snapshot route keeps a copy of the document', snap.get('ok') and snap.get('objects') == 1, snap)
stamp = snap['stamp']

lst = server_ext('file_manage_setup', 'versions', {'pid': PID, 'action': 'list'})
mine = [v for v in (lst.get('versions') or []) if v['stamp'] == stamp]
check(
    'the versions list shows it with its stamp, object count and label',
    mine and mine[0]['objects'] == 1 and mine[0]['label'] == 'proof',
    mine,
)
check(
    'the shelf grew by exactly one and is capped at 50',
    len(lst['versions']) == len(before.get('versions') or []) + 1 and lst.get('keep') == 50,
    (len(lst['versions']), lst.get('keep')),
)

lab = server_ext('file_manage_setup', 'versions', {'pid': PID, 'action': 'label', 'stamp': stamp, 'label': 'kept'})
check('a version can be labelled', lab.get('ok') and lab.get('label') == 'kept', lab)

res = server_ext('file_manage_setup', 'versions', {'pid': PID, 'action': 'restore', 'stamp': stamp})
check(
    'restore hands back the document that was kept (1 object, not the 2 on disk)',
    res.get('ok') and len(((res.get('doc') or {}).get('objects') or [])) == 1,
    res.get('ok'),
)
check(
    'an unknown stamp is refused rather than guessed',
    'error' in server_ext('file_manage_setup', 'versions', {'pid': PID, 'action': 'restore', 'stamp': 'nope'}),
    server_ext('file_manage_setup', 'versions', {'pid': PID, 'action': 'restore', 'stamp': 'nope'}),
)

# diff reads FORWARD: from the kept version to the document it is compared
# with. The shelf holds o1 alone; the drawing on disk has o1 and o2, so o2 is
# an ADDITION since that version — which is what restoring it would cost you.
df = server_ext('file_manage_setup', 'diff', {'pid': PID, 'stamp': stamp})
check(
    'diff counts what the drawing gained since that version (o2 added)',
    df.get('ok')
    and (df.get('counts') or {}).get('added') == 1
    and (df.get('counts') or {}).get('removed') == 0
    and df.get('added') == ['o2'],
    df.get('counts'),
)
# the other direction, against a posted document: o1 is gone, o2 is new here.
df2 = server_ext(
    'file_manage_setup',
    'diff',
    {'pid': PID, 'stamp': stamp, 'doc': {'name': NAME, 'objects': [dict(doc['objects'][1], x=9.0)]}},
)
check(
    'diff counts removals against a posted document (o1 removed, o2 added)',
    df2.get('ok')
    and (df2.get('counts') or {}).get('removed') == 1
    and (df2.get('counts') or {}).get('added') == 1
    and df2.get('removed') == ['o1'],
    df2.get('counts'),
)
# an object that only moved is neither added nor removed — it is CHANGED.
df3 = server_ext(
    'file_manage_setup',
    'diff',
    {'pid': PID, 'stamp': stamp, 'doc': {'name': NAME, 'objects': [dict(doc['objects'][0], x=4.0)]}},
)
check(
    'an object that only moved counts as changed, not as added or removed',
    (df3.get('counts') or {}).get('changed') == 1
    and (df3.get('counts') or {}).get('added') == 0
    and (df3.get('counts') or {}).get('removed') == 0,
    df3.get('counts'),
)

# ── 4. the archive (f_archive) ──────────────────────────────────────────────
z = server_ext('file_manage_setup', 'archive', {'pid': PID})
check(
    'archive answers with a zip download named after the drawing',
    z.get('mime') == 'application/zip' and str(z.get('filename', '')).endswith('.zip'),
    {k: v for k, v in z.items() if k != 'bytes'},
)
zf = zipfile.ZipFile(io.BytesIO(z['bytes']))
members = zf.namelist()
check(
    'the zip opens and holds at least two members (the drawing, its versions, a README)',
    len(members) >= 2 and any(m.endswith('.json') for m in members) and 'README.txt' in members,
    members,
)
check(
    'the README says how many objects the drawing has', b'objects' in zf.read('README.txt'), zf.read('README.txt')[:120]
)

# ── 5. about (p_about) ──────────────────────────────────────────────────────
ab = server_ext('file_manage_setup', 'about', {})
check(
    'about reports the server families, the js families and the assistant tool names',
    ab.get('ok')
    and len(ab.get('families') or {}) >= 1
    and len(ab.get('js_families') or []) >= 1
    and len(ab.get('assistant_tools') or []) >= 20,
    {
        'families': len(ab.get('families') or {}),
        'js': len(ab.get('js_families') or []),
        'tools': len(ab.get('assistant_tools') or []),
    },
)
check('about reads the build time from inspection.html itself', bool(ab.get('built')), ab.get('built'))

# ── 6. the assistant's twins ────────────────────────────────────────────────
txt, d = assistant('list_templates', {})
check('the assistant reads the templates straight from disk', 'Row house 5.4 m' in txt, txt[:120])

txt, d = assistant('new_from_template', {'name': 'Row house 5.4 m'})
check(
    'new_from_template presses f_tmpl with action=new and the name',
    d.ui
    and d.ui[-1]['args']['id'] == 'f_tmpl'
    and d.ui[-1]['args']['args'] == {'action': 'new', 'name': 'Row house 5.4 m'},
    d.ui,
)

txt, d = assistant('save_template', {'name': 'Proof template'})
check('save_template presses f_tmpl with action=save', d.ui and d.ui[-1]['args']['args']['action'] == 'save', d.ui)

txt, d = assistant('list_versions', {'drawing': PID})
check('list_versions answers from the shelf on disk without touching the tab', stamp in txt and not d.ui, txt[:160])

# The shelf holds o1 alone and the drawing on disk holds o1 and o2, so o2 is the
# addition a restore would drop — the model must be able to say that BEFORE it
# replaces every object, and must say it without pressing anything.
txt, d = assistant('version_diff', {'stamp': stamp, 'drawing': PID})
check(
    'version_diff warns, without touching the tab, what restoring would drop',
    not d.ui and 'o2' in txt and 'added' in txt and 'would drop' in txt,
    txt[:200],
)
txt, _ = assistant('version_diff', {'stamp': '20200101-000000-000', 'drawing': PID})
check('version_diff refuses a stamp that is not on the shelf', txt.startswith('refused'), txt[:120])

txt, d = assistant('restore_version', {'stamp': stamp, 'drawing': PID})
check(
    'restore_version presses f_ver with the stamp',
    d.ui and d.ui[-1]['args']['id'] == 'f_ver' and d.ui[-1]['args']['args']['stamp'] == stamp,
    d.ui,
)

txt, d = assistant('set_theme', {'theme': 'blueprint'})
check('set_theme presses p_theme with the theme', d.ui and d.ui[-1]['args']['args'] == {'theme': 'blueprint'}, d.ui)
txt, _ = assistant('set_theme', {'theme': 'tartan'})
check('an invented theme is refused', txt.startswith('refused'), txt)

txt, d = assistant('performance_report', {'reduced': True})
check(
    'performance_report presses p_perf and can ask for the reduced preset',
    d.ui and d.ui[-1]['args']['id'] == 'p_perf' and d.ui[-1]['args']['args'] == {'reduced': True},
    d.ui,
)

for bid in IDS:
    txt, d = assistant('press_button', {'id': bid})
    if not (txt.startswith('pressed') and d.ui[-1]['args']['id'] == bid):
        check('the assistant may press %s' % bid, False, txt)
        break
else:
    check('the assistant may press all nine icons through press_button (EXT_BUTTONS)', True, IDS)

# ══ 7. the live tab — two browser_eval calls ════════════════════════════════
r1 = browser_eval(
    """async () => {
  const out = {errors: []};
  // ── f_tmpl: a template opens as a NEW untitled drawing ──────────────────
  arTool('f_tmpl', {action: 'new', name: 'Row house 5.4 m'});
  await FMS.busy;
  out.tmpl_objs = AR.objs.length;
  out.tmpl_id = AR.doc.id;
  out.tmpl_name = AR.doc.name;
  out.tmpl_kinds = Array.from(new Set(AR.objs.map(o => o.kind))).sort();
  out.tmpl_undoable = (typeof arUndo === 'function');

  // ── f_auto: a dirty, saved drawing snapshots itself every second ────────
  AR.doc.id = %r; AR.doc.name = %r; arDirty(true);
  arTool('f_auto', {on: true, every_s: 1});
  out.auto_on = AR_EXT.tools.f_auto.on();
  out.auto_pref = localStorage.getItem('ar.file_manage_setup.autosave');
  await new Promise(r => setTimeout(r, 2600));
  await FMS.busy;
  out.auto_n = FMS.autoN;
  arTool('f_auto', {on: false});
  out.auto_off = AR_EXT.tools.f_auto.on();

  // ── p_theme: a class on #view-architecture and pale panels ──────────────
  arTool('p_theme', {theme: 'light'});
  const v = document.getElementById('view-architecture');
  const rail = document.querySelector('#view-architecture .ar-rail');
  out.theme_class = v.className;
  out.theme_on = AR_EXT.tools.p_theme.on();
  const bg = getComputedStyle(rail).backgroundColor;
  const m = bg.match(/[\\d.]+/g).map(Number);
  out.theme_bg = bg;
  out.theme_lum = (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / 255;
  arTool('p_theme', {theme: 'dark'});
  out.theme_back = document.getElementById('view-architecture').className;

  // ── p_perf: pixel ratio 0.5 halves the canvas ──────────────────────────
  arTool('p_perf', {pixel_ratio: 1});
  out.perf_w1 = AR.renderer.domElement.width;
  arTool('p_perf', {pixel_ratio: 0.5});
  out.perf_w2 = AR.renderer.domElement.width;
  out.perf_on = AR_EXT.tools.p_perf.on();
  const n = AR_EXT.tools.p_perf.act({});
  out.perf_nums = {fps: typeof n.fps, objects: n.objects, triangles: n.triangles,
                   calls: typeof n.calls, textures: typeof n.textures, geometries: typeof n.geometries};
  out.perf_sheet = document.getElementById('ar-sheet').innerText.slice(0, 400);
  arTool('p_perf', {pixel_ratio: 1, reduced: false});
  arSheetClose();
  return out;
}"""
    % (PID, NAME)
)
v1 = r1['value']
check('no page errors while pressing f_tmpl, f_auto, p_theme and p_perf', not r1['errors'], r1['errors'])

check('f_tmpl opens the row house template as a whole little building', v1['tmpl_objs'] >= 8, v1['tmpl_objs'])
check(
    'f_tmpl opens it as a NEW drawing: the id is cleared so a save cannot overwrite the template',
    v1['tmpl_id'] == '',
    repr(v1['tmpl_id']),
)
check(
    'f_tmpl keeps the template name and its walls, slab, door, windows and roof',
    v1['tmpl_name'] == 'Row house 5.4 m'
    and set(['wall', 'slab', 'door', 'window', 'roof_gable']) <= set(v1['tmpl_kinds']),
    v1['tmpl_kinds'],
)

check(
    'f_auto reports itself on and remembers the setting in localStorage',
    v1['auto_on'] is True and 'every_s' in (v1['auto_pref'] or ''),
    v1['auto_pref'],
)
check('f_auto took at least two snapshots in 2.6 s at every_s=1', v1['auto_n'] >= 2, v1['auto_n'])
check('f_auto switches off again', v1['auto_off'] is False, v1['auto_off'])

after = server_ext('file_manage_setup', 'versions', {'pid': PID, 'action': 'list'})
autos = [x for x in (after.get('versions') or []) if x.get('label') == 'autosave']
check('the autosaves landed on the version shelf labelled "autosave"', len(autos) >= 2, len(autos))
check(
    'autosave never overwrote the named save on disk',
    len((ST.load_project(PID).get('doc') or {}).get('objects') or []) == 2,
    len((ST.load_project(PID).get('doc') or {}).get('objects') or []),
)

check('p_theme puts its class on #view-architecture', 'ar-theme-light' in v1['theme_class'], v1['theme_class'])
check(
    'p_theme actually repaints the rail pale (luminance > 0.5)',
    v1['theme_lum'] > 0.5,
    (v1['theme_bg'], round(v1['theme_lum'], 3)),
)
check('p_theme reads as on when it is not the shipped dark', v1['theme_on'] is True, v1['theme_on'])
check('p_theme goes back to dark by dropping the class', 'ar-theme-' not in v1['theme_back'], v1['theme_back'])

check(
    'p_perf pixel ratio 0.5 halves the canvas width',
    abs(v1['perf_w2'] * 2 - v1['perf_w1']) <= 2 and v1['perf_w2'] > 0,
    (v1['perf_w1'], v1['perf_w2']),
)
check('p_perf reads as on while a reduced setting is applied', v1['perf_on'] is True, v1['perf_on'])
check(
    'p_perf reports live numbers: fps, objects, triangles, draw calls, textures, geometries',
    v1['perf_nums']['fps'] == 'number'
    and v1['perf_nums']['calls'] == 'number'
    and v1['perf_nums']['textures'] == 'number'
    and v1['perf_nums']['geometries'] == 'number'
    and v1['perf_nums']['objects'] >= 8
    and v1['perf_nums']['triangles'] > 0,
    v1['perf_nums'],
)
check(
    'p_perf opens a sheet with the numbers and the knobs',
    'draw calls' in v1['perf_sheet'] and 'pixel ratio' in v1['perf_sheet'],
    v1['perf_sheet'][:160],
)

r2 = browser_eval(
    """async () => {
  const out = {};
  // ── p_help: every icon, the keys, the assistant's tools, searchable ─────
  const h = AR_EXT.tools.p_help.act({});
  await FMS.busy;
  out.help_icons = h.icons;
  out.help_rows = document.querySelectorAll('.fms-help-row').length;
  out.help_all = FMS_helpFilter('');
  out.help_hit = FMS_helpFilter('theme');
  out.help_visible = document.querySelectorAll('.fms-help-row:not(.off)').length;
  out.help_miss = FMS_helpFilter('zzzznotathing');
  FMS_helpFilter('');
  const ht = document.getElementById('ar-sheet').innerText;
  out.help_has_key = ht.indexOf('Ctrl+Z') >= 0;
  out.help_has_tool = ht.indexOf('save_template') >= 0;
  out.help_has_tip = ht.indexOf('Autosave') >= 0;
  arSheetClose();

  // ── p_about ────────────────────────────────────────────────────────────
  const a = await AR_EXT.tools.p_about.act();
  const at = document.getElementById('ar-sheet').innerText;
  out.about_three = a.three;
  out.about_live_rev = 'r' + THREE.REVISION;
  out.about_families = Object.keys(a.families || {}).length;
  out.about_text_rev = at.indexOf('r' + THREE.REVISION) >= 0;
  out.about_text_fam = at.indexOf('file_manage_setup') >= 0;
  // the sheet's headings are text-transform:uppercase, so innerText renders
  // them shouted: count the rows instead of matching a heading's casing.
  out.about_lic_rows = document.querySelectorAll('.fms-lic-row').length;
  out.about_pack_rows = document.querySelectorAll('.fms-pack-row').length;
  out.about_lic_head = at.toLowerCase().indexOf('vendored libraries') >= 0;
  out.about_pack_head = at.toLowerCase().indexOf('asset packs by licence') >= 0;
  out.about_lic_mit = at.toLowerCase().indexOf('mit license') >= 0;
  arSheetClose();

  // ── p_prefs ────────────────────────────────────────────────────────────
  localStorage.setItem('ar.file_manage_setup.probe', 'hello');
  arTool('p_prefs');
  const pt = document.getElementById('ar-sheet').innerText;
  out.prefs_lists = pt.indexOf('ar.file_manage_setup.probe') >= 0;
  out.prefs_defaults = pt.indexOf('wall height') >= 0 && pt.indexOf('grid / snap') >= 0;
  out.prefs_rows = document.querySelectorAll('.fms-pref').length;
  const wasH = AR.defaults.wall_h;
  FMS_defSet('wall_h', 3.3);
  out.prefs_def_now = AR.defaults.wall_h;
  out.prefs_def_stored = localStorage.getItem('ar.file_manage_setup.defaults');
  FMS_defSet('wall_h', wasH);
  FMS_prefReset('ar.file_manage_setup.probe');
  out.prefs_gone = localStorage.getItem('ar.file_manage_setup.probe');
  arSheetClose();

  // ── f_ver in the tab, on the drawing the test saved ─────────────────────
  AR.doc.id = %r; AR.doc.name = %r;
  arTool('f_ver', {action: 'list'});
  await FMS.busy;
  const vt = document.getElementById('ar-sheet').innerText;
  out.ver_sheet = vt.slice(0, 90);
  out.ver_has_autosave = vt.indexOf('autosave') >= 0;
  out.ver_restore_btns = document.querySelectorAll('#ar-sheet .fms-btn').length;
  arSheetClose();

  // ── f_ver restore, as one undo step ────────────────────────────────────
  const nBefore = AR.objs.length;
  arTool('f_ver', {action: 'restore', stamp: %r});
  await FMS.busy;
  out.ver_after = AR.objs.length;
  out.ver_kept_id = AR.doc.id;
  arUndo();
  out.ver_undone = AR.objs.length;
  out.ver_before = nBefore;

  // ── f_archive: the blob comes back to the caller ────────────────────────
  const b = await AR_EXT.tools.f_archive.act();
  out.zip_size = b ? b.size : 0;
  out.zip_type = b ? b.type : '';
  out.toast = document.getElementById('ar-toast').innerHTML;

  // ── the arSave wrap: a successful save leaves a copy on the shelf ───────
  const shelf = () => fetch('/inspect/api/architecture/ext/file_manage_setup/versions',
      {method: 'POST', headers: {'Content-Type': 'application/json'},
       body: JSON.stringify({pid: AR.doc.id, action: 'list'})}).then(r => r.json());
  out.save_pid = AR.doc.id;
  out.save_before = ((await shelf()).versions || []).length;
  arSave(false);                       // doc.id is set, so no name is asked for
  await new Promise(r => setTimeout(r, 3000));   // the wrap snapshots 1.5 s later
  const after = (await shelf()).versions || [];
  out.save_after = after.length;
  out.save_labels = after.slice(0, 4).map(v => v.label);
  return out;
}"""
    % (PID, NAME, stamp)
)
v2 = r2['value']
check('no page errors while pressing p_help, p_about, p_prefs, f_ver and f_archive', not r2['errors'], r2['errors'])

check(
    'p_help lists every icon in the studio (>= 200 rows)',
    v2['help_rows'] >= 200 and v2['help_icons'] >= 200,
    (v2['help_icons'], v2['help_rows']),
)
check(
    'p_help\u2019s filter narrows the list and finds this family\u2019s own icons',
    0 < v2['help_hit'] < v2['help_all'] and v2['help_visible'] == v2['help_hit'],
    (v2['help_all'], v2['help_hit'], v2['help_visible']),
)
check('a search that matches nothing shows nothing', v2['help_miss'] == 0, v2['help_miss'])
check(
    'p_help shows the keyboard map, the tooltips and the assistant\u2019s tools',
    v2['help_has_key'] and v2['help_has_tip'] and v2['help_has_tool'],
    (v2['help_has_key'], v2['help_has_tip'], v2['help_has_tool']),
)

# The brief (and arch_ext/README.md) say the studio runs three.js r144; the
# vendored vendor/three/three.min.js reports REVISION "147". About must state
# what is actually loaded, so this asserts against the live constant and pins
# it to the bytes on disk rather than to either document.
check(
    'p_about names the three.js revision the studio actually runs',
    v2['about_three'] == v2['about_live_rev'] and v2['about_text_rev'],
    (v2['about_three'], v2['about_live_rev']),
)
check(
    'that revision is the one vendored in vendor/three/three.min.js',
    v2['about_live_rev'] == 'r' + VENDORED_THREE,
    (v2['about_live_rev'], VENDORED_THREE),
)
check(
    'p_about lists at least one server family, this one included',
    v2['about_families'] >= 1 and v2['about_text_fam'],
    v2['about_families'],
)
check(
    'p_about shows the vendored libraries with their licences',
    v2['about_lic_head'] and v2['about_lic_rows'] >= 1 and v2['about_lic_mit'],
    (v2['about_lic_head'], v2['about_lic_rows'], v2['about_lic_mit']),
)
check(
    'p_about summarises the asset packs by licence',
    v2['about_pack_head'] and v2['about_pack_rows'] >= 1,
    (v2['about_pack_head'], v2['about_pack_rows']),
)

check(
    'p_prefs lists the stored ar.* keys as editable rows',
    v2['prefs_lists'] and v2['prefs_rows'] >= 1,
    (v2['prefs_lists'], v2['prefs_rows']),
)
check(
    'p_prefs offers the studio defaults as inputs and writing one changes AR.defaults',
    v2['prefs_defaults'] and v2['prefs_def_now'] == 3.3 and 'wall_h' in (v2['prefs_def_stored'] or ''),
    (v2['prefs_defaults'], v2['prefs_def_now'], v2['prefs_def_stored']),
)
check('p_prefs can forget a single preference', v2['prefs_gone'] is None, v2['prefs_gone'])

check(
    'f_ver lists the shelf in the tab with a restore button per version',
    'Versions of' in v2['ver_sheet'] and v2['ver_has_autosave'] and v2['ver_restore_btns'] >= 2,
    (v2['ver_sheet'], v2['ver_restore_btns']),
)
check(
    'f_ver restores that version into the tab (1 object) keeping the drawing id',
    v2['ver_after'] == 1 and v2['ver_kept_id'] == PID,
    (v2['ver_after'], v2['ver_kept_id']),
)
check(
    'the restore is ONE undo step, so nothing is lost',
    v2['ver_undone'] == v2['ver_before'],
    (v2['ver_before'], v2['ver_after'], v2['ver_undone']),
)

check(
    'f_archive hands back a zip blob bigger than 500 bytes and toasts its size',
    v2['zip_size'] > 500 and 'Archive downloaded' in v2['toast'],
    (v2['zip_size'], v2['zip_type']),
)

# arSave is wrapped, so saving from the tab leaves a copy on the shelf without
# anyone pressing f_ver. The wrap waits for arSave's own fetch to settle before
# taking the copy, which is why the browser waited before counting again.
check(
    'every successful save leaves a copy on the version shelf (the arSave wrap)',
    v2['save_pid'] == PID and v2['save_after'] == v2['save_before'] + 1 and 'save' in (v2['save_labels'] or []),
    (v2['save_pid'], v2['save_before'], v2['save_after'], v2['save_labels']),
)

finish()
