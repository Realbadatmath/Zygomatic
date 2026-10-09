# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_quantities.py — the proof for the Quantities family.

Seven icons (q_volume, q_cost, q_doors, q_rooms, q_csv, q_units, q_prec) stop
being placeholders and each one does the thing its tooltip promises. The
document under test is a 4 x 4 m room of four concrete walls (the south wall
carries a door and a window), a slab and a column — enough for a volume with a
hole in it, an opening schedule, a closed room loop and a priced estimate.

Three browser_eval calls: icon_state, the four reports + CSV, and the display
units. Everything is asserted on numbers and on the document.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, browser_eval, icon_state  # noqa: E402

IDS = ['q_volume', 'q_cost', 'q_doors', 'q_rooms', 'q_csv', 'q_units', 'q_prec']
RY90 = 1.5707963267948966

DOC = {
    'objects': [
        {
            'id': 'o1',
            'kind': 'wall',
            'name': 'South wall',
            'p': {'len': 4, 'h': 2.7, 't': 0.24},
            'x': 0,
            'y': 0,
            'z': -2,
            'ry': 0,
            'mat': 'mat_concrete',
        },
        {
            'id': 'o2',
            'kind': 'wall',
            'name': 'North wall',
            'p': {'len': 4, 'h': 2.7, 't': 0.24},
            'x': 0,
            'y': 0,
            'z': 2,
            'ry': 0,
            'mat': 'mat_concrete',
        },
        {
            'id': 'o3',
            'kind': 'wall',
            'name': 'West wall',
            'p': {'len': 4, 'h': 2.7, 't': 0.24},
            'x': -2,
            'y': 0,
            'z': 0,
            'ry': RY90,
            'mat': 'mat_concrete',
        },
        {
            'id': 'o4',
            'kind': 'wall',
            'name': 'East wall',
            'p': {'len': 4, 'h': 2.7, 't': 0.24},
            'x': 2,
            'y': 0,
            'z': 0,
            'ry': RY90,
            'mat': 'mat_concrete',
        },
        {
            'id': 'o5',
            'kind': 'door',
            'name': 'Front door',
            'p': {'w': 0.9, 'h': 2.1},
            'x': 0,
            'y': 0,
            'z': -2,
            'ry': 0,
            'mat': 'mat_timber',
        },
        {
            'id': 'o6',
            'kind': 'window',
            'name': 'South window',
            'p': {'w': 1.2, 'h': 1.4, 'sill': 0.9},
            'x': 1.2,
            'y': 0,
            'z': -2,
            'ry': 0,
            'mat': 'mat_glass',
        },
        {
            'id': 'o7',
            'kind': 'slab',
            'name': 'Floor',
            'p': {'w': 4, 'd': 4, 't': 0.22},
            'x': 0,
            'y': 0,
            'z': 0,
            'ry': 0,
            'mat': 'mat_concrete',
        },
        {
            'id': 'o8',
            'kind': 'column_rect',
            'name': 'Post',
            'p': {'w': 0.3, 'd': 0.3, 'h': 2.7},
            'x': 1.5,
            'y': 0,
            'z': 1.5,
            'ry': 0,
            'mat': 'mat_concrete',
        },
    ]
}

# ── 1. the icons are wired ───────────────────────────────────────────────────
st = icon_state(IDS)
bad = {
    i: v for i, v in st.items() if not v.get('exists') or v.get('stub') or v.get('dashed') or v.get('tip_placeholder')
}
check(
    'all seven Quantities icons exist and are no longer placeholders '
    '(no stub flag, no dashed class, no [placeholder] tooltip)',
    not bad,
    bad or st,
)
check(
    'q_units and q_prec render as switches in the Quantities section',
    st['q_units']['section'] == 'Quantities' and st['q_prec']['section'] == 'Quantities',
    st,
)

# ── 2. the four reports and the CSV ──────────────────────────────────────────
R = browser_eval(
    """() => {
  const R = {};
  /* q_volume */
  arTool('q_volume');
  const v = quantities.last;
  R.volTitle = v.title; R.volHeaders = v.headers; R.volRows = v.rows; R.volFoot = v.foot;
  const t = quantities.takeoff();
  R.concreteJs = t.byMat['mat_concrete'] ? t.byMat['mat_concrete'].vol : 0;
  R.massJs = t.byMat['mat_concrete'] ? t.byMat['mat_concrete'].mass : 0;
  R.netJs = t.totals.net;
  let exp = 0, expNet = 0;
  AR.objs.forEach(o => {
    if (o.kind === 'wall') { (o.p.holes||[]).forEach(h => { expNet -= h.w*h.h; }); expNet += o.p.len*o.p.h; }
    if (o.mat !== 'mat_concrete') return;
    if (o.kind === 'wall') { let x = o.p.len*o.p.h*o.p.t; (o.p.holes||[]).forEach(h => { x -= h.w*h.h*o.p.t; }); exp += x; }
    else if (o.kind === 'slab') exp += o.p.w*o.p.d*o.p.t;
    else if (o.kind === 'column_rect') exp += o.p.w*o.p.d*o.p.h;
  });
  R.concreteExp = exp; R.netExp = expNet;
  R.holes = (arFind('o1').p.holes || []).length;
  R.sheetRows = document.querySelectorAll('#ar-sheet .ar-tbl tr').length;
  R.sheetTitle = document.querySelector('#ar-sheet .hd span').textContent;
  /* q_cost */
  arTool('q_cost');
  R.cost0 = quantities.last.total; R.costRows0 = quantities.last.rows.length;
  R.costInputs = document.querySelectorAll('#ar-sheet [data-qrate]').length;
  R.costHasSave = /saveRates/.test(document.getElementById('ar-sheet').innerHTML);
  arTool('q_cost', {rates: {per_m3: {concrete: 360}}});
  R.cost1 = quantities.last.total;
  R.rateStored = AR.doc.ext.quantities.rates.per_m3.concrete;
  /* q_doors */
  arTool('q_doors');
  R.doorTitle = quantities.last.title; R.doorRows = quantities.last.rows;
  R.hostId = arFind('o5').p.host;
  /* q_rooms */
  arTool('q_rooms');
  R.roomRows = quantities.last.rows; R.rooms = quantities.last.roomsList;
  R.roomMethod = quantities.rooms().method;
  /* q_csv */
  arTool('q_csv', {report: 'doors'});
  R.csv = quantities.lastCsv;
  R.toast = document.getElementById('ar-toast').innerHTML;
  R.doc = arDocOut();
  /* the rest of what the CSV button promises: the built-in Bill of materials
     re-derived from the records, "last" meaning the report last opened (the
     room schedule, from the q_rooms press above), and the ';' a Dutch or German
     spreadsheet needs because it reads ',' as the decimal point. */
  arTool('q_csv', {report: 'bom'});
  R.csvBom = quantities.lastCsv;
  arTool('q_csv', {report: 'last'});
  R.csvLast = quantities.lastCsv;
  R.lang = navigator.language;
  Object.defineProperty(navigator, 'language', {value: 'de-DE', configurable: true});
  arTool('q_csv', {report: 'doors'});
  R.csvDe = quantities.lastCsv;
  arTool('q_csv', {report: 'no_such_report'});
  R.csvBadToast = document.getElementById('ar-toast').innerHTML;
  R.csvAfterBad = quantities.lastCsv;           /* unchanged: nothing was written */
  Object.defineProperty(navigator, 'language', {value: R.lang, configurable: true});
  /* q_rooms again, this time with ZONES. The organise_model family's 'zone'
     kind does exist, so the brief's "zone records if the zone kind exists"
     branch is the one a real drawing takes; the wall-loop walk above is the
     fallback. A zone is also a closed 5 cm mesh, so this is where we prove it
     is counted as a diagram and never priced as 0.8 m3 of flooring. */
  R.volNoZones = quantities.takeoff().totals.vol;
  const z1 = arNewObj('zone', {pts: [[-2,-2],[2,-2],[2,2],[-2,2]], name: 'Hall', use: 'circulation', h: 0.05}, 0, 0, 0);
  z1.name = 'Hall';
  const z2 = arNewObj('zone', {pts: [[-1.5,-1],[1.5,-1],[1.5,1],[-1.5,1]], name: 'Store', use: 'storage', h: 0.05}, 8, 0, 0);
  z2.name = 'Store';
  arTool('q_rooms');
  R.zoneMethod = quantities.rooms().method;
  R.zoneRooms = quantities.last.roomsList;
  R.zoneFirstRow = quantities.last.rows[0];
  const tz = quantities.takeoff();
  R.volWithZones = tz.totals.vol; R.diagrams = tz.totals.diagram;
  R.zoneGeomVol = (function(){ let s = 0; arGeom('zone', arFind(z1.id).p).forEach(pt => {
    if (pt.line) return; pt.g.computeBoundingBox();
    const b = pt.g.boundingBox; s += (b.max.x-b.min.x)*(b.max.y-b.min.y)*(b.max.z-b.min.z); }); return s; })();
  arTool('q_cost');
  R.costWithZones = quantities.last.total;
  R.docZ = arDocOut();
  return R;
}""",
    doc=DOC,
)
check('no page errors while the seven reports ran', not R['errors'], R['errors'])
v = R['value']

check(
    'q_volume opens a "Volume and mass by material" sheet with material/count/volume/mass columns',
    v['sheetTitle'] == 'Volume and mass by material'
    and v['volHeaders'] == ['material', 'count', 'volume m\u00b3', 'mass t']
    and v['sheetRows'] >= 3,
    {'title': v['sheetTitle'], 'hdr': v['volHeaders'], 'rows': v['sheetRows']},
)
check('the openings really are cut out of the south wall (2 holes in o1)', v['holes'] == 2, v['holes'])
check(
    'concrete volume from the built mesh is within 2%% of the parametric value '
    '(%.4f vs %.4f m3; 4 x 2.7 x 0.24 = 2.592 per wall, minus its holes)' % (v['concreteJs'], v['concreteExp']),
    v['concreteExp'] > 12 and abs(v['concreteJs'] - v['concreteExp']) <= 0.02 * v['concreteExp'],
    {'js': v['concreteJs'], 'parametric': v['concreteExp']},
)
check(
    'mass = volume x 2400 kg/m3 for concrete (%.1f kg)' % v['massJs'],
    abs(v['massJs'] - v['concreteJs'] * 2400) < 1.0,
    v['massJs'],
)
check(
    'walls report a net face area of len*h minus the holes (%.3f vs %.3f m2)' % (v['netJs'], v['netExp']),
    abs(v['netJs'] - v['netExp']) < 0.01,
    {'net': v['netJs'], 'expected': v['netExp']},
)
check(
    'the volume sheet has a concrete row',
    any(r[0] == 'Concrete' or 'oncrete' in str(r[0]) for r in v['volRows']),
    v['volRows'],
)

check(
    'q_cost prices the take-off: a positive itemised total (%.2f EUR over %d lines)' % (v['cost0'], v['costRows0']),
    v['cost0'] > 0 and v['costRows0'] >= 3,
    {'total': v['cost0'], 'rows': v['costRows0']},
)
check(
    'the cost sheet carries editable rate inputs and a save button',
    v['costInputs'] >= 8 and v['costHasSave'],
    {'inputs': v['costInputs'], 'save': v['costHasSave']},
)
check(
    'passing rates to q_cost changes the estimate and is stored in doc.ext '
    '(%.2f -> %.2f, concrete 180 -> %s)' % (v['cost0'], v['cost1'], v['rateStored']),
    v['cost1'] > v['cost0'] and v['rateStored'] == 360,
    {'a': v['cost0'], 'b': v['cost1']},
)

check(
    'q_doors schedules both openings with their host wall, size and storey',
    v['doorTitle'] == 'Door and window schedule'
    and len(v['doorRows']) == 2
    and all(r[5] == v['hostId'] for r in v['doorRows'])
    and v['hostId'] == 'o1'
    and any('0.9' in str(r[3]) for r in v['doorRows']),
    v['doorRows'],
)

check(
    'q_rooms finds the 4 x 4 room by closed wall loops, 16 m2 +/- 0.5',
    v['roomMethod'] == 'closed wall loops'
    and len(v['rooms']) >= 1
    and abs(v['rooms'][0]['area'] - 16.0) < 0.5
    and abs(v['rooms'][0]['perim'] - 16.0) < 0.5,
    v['rooms'],
)
check(
    'the room sheet says which method produced the rooms in its first row',
    v['roomRows'][0][0] == 'method' and 'closed wall loops' in v['roomRows'][0][1],
    v['roomRows'][0],
)

csv = v['csv']
lines = [ln for ln in csv['text'].replace('\ufeff', '').split('\r\n') if ln.strip()]
check(
    'q_csv {report:"doors"} writes a 3-line CSV (header + 2 openings) with a UTF-8 BOM',
    csv['text'][0] == '\ufeff' and len(lines) == 3 and lines[0].startswith('id'),
    lines,
)
check(
    'the CSV separator matches the locale ("%s") and the download was named' % csv['sep'],
    csv['sep'] in (',', ';') and csv['filename'] == 'quantities-doors.csv',
    csv,
)
check(
    'the CSV rows are the schedule rows, not scraped HTML',
    all('<' not in ln for ln in lines) and lines[1].split(csv['sep'])[0] in ('o5', 'o6'),
    lines,
)
check('q_csv says what it wrote', 'quantities-doors.csv' in v['toast'], v['toast'])
bom = v['csvBom']
bomlines = [ln for ln in bom['text'].replace('\ufeff', '').split('\r\n') if ln.strip()]
check(
    'q_csv {report:"bom"} writes the bill of materials re-derived from the records '
    '(%d lines, headed "%s")' % (len(bomlines), bomlines[0]),
    bom['filename'] == 'quantities-bom.csv'
    and bomlines[0].split(bom['sep'])[0] == 'kind'
    and len(bomlines) >= 4
    and any('Wall' in ln for ln in bomlines[1:]),
    bomlines,
)
check(
    'q_csv {report:"last"} writes the report last opened, the room schedule (%s)' % v['csvLast']['filename'],
    v['csvLast']['name'] == 'rooms' and v['csvLast']['filename'] == 'quantities-rooms.csv',
    v['csvLast'],
)
check(
    'a Dutch or German locale gets ";" separated CSV (this browser\'s "%s" locale gets "%s")' % (v['lang'], csv['sep']),
    v['csvDe']['sep'] == ';' and ';' in v['csvDe']['text'] and csv['sep'] == ',',
    {'de-DE': v['csvDe']['sep'], v['lang']: csv['sep']},
)
check(
    'q_csv refuses a report that does not exist instead of writing an empty file',
    'no_such_report' in v['csvBadToast'] and v['csvAfterBad']['name'] == 'doors' and v['csvAfterBad']['sep'] == ';',
    {'toast': v['csvBadToast'], 'still': v['csvAfterBad']},
)

# ── 2b. the zone branch of the room schedule, and zones as diagrams ──────────
check(
    'with zones in the drawing q_rooms switches to the zone records branch and schedules both '
    '(Hall %.2f m2, Store %.2f m2)'
    % (
        v['zoneRooms'][0]['area'] if v['zoneRooms'] else -1,
        v['zoneRooms'][1]['area'] if len(v['zoneRooms']) > 1 else -1,
    ),
    v['zoneMethod'] == 'zone records'
    and len(v['zoneRooms']) == 2
    and abs(v['zoneRooms'][0]['area'] - 16.0) < 0.01
    and abs(v['zoneRooms'][0]['perim'] - 16.0) < 0.01
    and abs(v['zoneRooms'][1]['area'] - 6.0) < 0.01
    and v['zoneRooms'][0]['use'] == 'circulation'
    and v['zoneRooms'][1]['use'] == 'storage',
    v['zoneRooms'],
)
check(
    'the zone rows carry the zone names and the sheet says the method changed',
    v['zoneFirstRow'][0] == 'method'
    and v['zoneFirstRow'][1] == 'zone records'
    and {r['name'] for r in v['zoneRooms']} == {'Hall', 'Store'},
    v['zoneFirstRow'],
)
check(
    'a zone builds a real closed mesh (%.3f m3 of box) but is NOT added to the take-off — '
    'the volume is unchanged by adding two zones (%.4f m3 both times) and 2 are counted as diagrams'
    % (v['zoneGeomVol'], v['volWithZones']),
    v['zoneGeomVol'] > 0.5 and abs(v['volWithZones'] - v['volNoZones']) < 1e-9 and v['diagrams'] == 2,
    {'geom m3': v['zoneGeomVol'], 'before': v['volNoZones'], 'after': v['volWithZones'], 'diagrams': v['diagrams']},
)
check(
    'and the cost estimate does not charge for them (%.2f, the same total as before the zones)' % v['costWithZones'],
    abs(v['costWithZones'] - v['cost1']) < 1e-6,
    {'before': v['cost1'], 'after': v['costWithZones']},
)

# ── 3. units and precision ───────────────────────────────────────────────────
U = browser_eval("""() => {
  const O = {};
  const rec = arNewObj('wall', {len: 4, h: 2.7, t: 0.24}, 2.5, 0, 0);
  arSelect([rec.id]);
  O.base = arFmt(2.456);
  arTool('q_prec', {decimals: 1});
  O.prec1 = arFmt(2.456); O.dec = quantities.decimals;
  arTool('q_units', {units: 'mm'});
  O.mm = arFmt(2.5); O.units = quantities.units;
  O.hud = document.getElementById('ar-hud').textContent;
  arPanel();
  O.panel = [].slice.call(document.querySelectorAll('#ar-panel-bd input[type=number]')).map(i => i.value);
  O.panelNote = document.getElementById('ar-panel-bd').textContent.slice(0, 160);
  O.ext = JSON.parse(JSON.stringify(AR.doc.ext.quantities));
  O.ls = [localStorage.getItem('ar.quantities.units'), localStorage.getItem('ar.quantities.decimals')];
  arTool('q_units', {units: 'ft'});
  O.ft = arFmt(3.2); O.ftHud = document.getElementById('ar-hud').textContent;
  arTool('q_units');                       /* cycle: ft -> m */
  O.cycled = quantities.units; O.mAfter = arFmt(2.456);
  arTool('q_prec');                        /* cycle: 1 -> 2 */
  O.dec2 = quantities.decimals; O.prec2 = arFmt(2.456);
  O.ext2 = JSON.parse(JSON.stringify(AR.doc.ext.quantities));
  O.ls2 = [localStorage.getItem('ar.quantities.units'), localStorage.getItem('ar.quantities.decimals')];
  O.toast = document.getElementById('ar-toast').innerHTML;
  return O;
}""")
check('no page errors while the units and precision switches ran', not U['errors'], U['errors'])
u = U['value']
check('q_prec {decimals:1} makes arFmt(2.456) read "2.5" in metres', u['prec1'] == '2.5' and u['dec'] == 1, u)
check('q_units {units:"mm"} makes arFmt(2.5) read "2500"', u['mm'] == '2500' and u['units'] == 'mm', u)
check('the HUD shows the unit it is displaying', 'mm' in u['hud'], u['hud'])
check(
    'the properties panel still reads and writes METRES while the page shows mm (x = 2.50, not 2500)',
    '2.50' in u['panel'] and '2500' not in u['panel'],
    u['panel'],
)
check('the panel says so out loud', 'metres' in u['panelNote'] and 'mm' in u['panelNote'], u['panelNote'])
check('q_units ft prints feet and inches (3.2 m = %s)' % u['ft'], u['ft'] == '10\' 6"', u['ft'])
check('pressing q_units with no args cycles back to metres', u['cycled'] == 'm' and u['mAfter'] == '2.5', u)
check(
    'pressing q_prec with no args cycles the decimals (1 -> %s, 2.456 -> %s)' % (u['dec2'], u['prec2']),
    u['dec2'] == 2 and u['prec2'] == '2.46',
    u,
)
check(
    'every change is persisted in the drawing (doc.ext.quantities) and in localStorage, '
    'so the next visit opens in the same units',
    u['ext'].get('units') == 'mm'
    and u['ext'].get('decimals') == 1
    and u['ls'] == ['mm', '1']
    and u['ext2'].get('units') == 'm'
    and u['ext2'].get('decimals') == 2
    and u['ls2'] == ['m', '2'],
    {'at mm/1': {'ext': u['ext'], 'ls': u['ls']}, 'after cycling': {'ext': u['ext2'], 'ls': u['ls2']}},
)
check('the toast says the model is unchanged', 'unchanged' in u['toast'] or 'metres' in u['toast'], u['toast'])

# ── 4. the server-side twins ────────────────────────────────────────────────
doc = v['doc']
txt, d = assistant('quantities', {'report': 'volume'}, doc=doc)
m = re.search(r'^\s*concrete\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s*$', txt, re.M)
check('assistant quantities("volume") returns a material table with a concrete line', bool(m), txt)
if m:
    py = float(m.group(2))
    check(
        'the Python twin agrees with the tab within 2%% on the walls (%.3f vs %.3f m3)' % (py, v['concreteJs']),
        abs(py - v['concreteJs']) <= 0.02 * v['concreteJs'],
        {'python': py, 'browser': v['concreteJs']},
    )

txt2, _ = assistant('quantities', {'report': 'doors'}, doc=doc)
check(
    'assistant quantities("doors") lists both openings with their host',
    txt2.count('\n  ') == 2 and 'o1' in txt2 and 'door' in txt2 and 'window' in txt2,
    txt2,
)
txt3, _ = assistant('quantities', {'report': 'rooms'}, doc=doc)
check('assistant quantities("rooms") finds the same 16 m2 room', '16.00 m2' in txt3, txt3)
txt4, d4 = assistant('quantities', {'report': 'cost'}, doc=doc)
check(
    'assistant quantities("cost") prices it with the rate card the tab saved (concrete 360)',
    'TOTAL' in txt4 and '360.00' in txt4,
    txt4,
)
txt5, _ = assistant('quantities', {'report': 'nonsense'}, doc=doc)
check('an unknown report is refused, not guessed', txt5.startswith('refused'), txt5)

# the same drawing WITH the two zones: the twin must take the zone branch too,
# and must leave the zones out of the material exactly as the tab does
docZ = v['docZ']
txtZ, _ = assistant('quantities', {'report': 'rooms'}, doc=docZ)
check(
    'the Python twin also switches to zone records and finds the same two rooms',
    'by zone records' in txtZ
    and '16.00 m2' in txtZ
    and '6.00 m2' in txtZ
    and 'circulation' in txtZ
    and 'storage' in txtZ,
    txtZ,
)
txtZv, _ = assistant('quantities', {'report': 'volume'}, doc=docZ)
mZ = re.search(r'^\s*concrete\s+(\d+)\s+([\d.]+)\s+', txtZv, re.M)
check(
    'the twin leaves the zones out of the volume too (concrete %s m3, unchanged) and says it did'
    % (mZ.group(2) if mZ else '?'),
    bool(mZ) and abs(float(mZ.group(2)) - v['concreteJs']) <= 0.02 * v['concreteJs'] and '2 diagram objects' in txtZv,
    txtZv,
)

txt6, d6 = assistant('set_units', {'units': 'mm', 'decimals': 1})
check(
    'assistant set_units writes doc.ext.quantities for the tab to pick up',
    d6.ext['quantities'] == {'units': 'mm', 'decimals': 1} and d6.to_doc()['ext']['quantities']['units'] == 'mm',
    d6.ext,
)
txt7, _ = assistant('set_units', {'units': 'furlongs'})
check('a unit system that does not exist is refused', txt7.startswith('refused'), txt7)
txt8, d8 = assistant('set_rates', {'rates': {'per_m3': {'concrete': 200}, 'per_item': {'door': 500}}})
check(
    'assistant set_rates writes the rate card into the drawing',
    d8.ext['quantities']['rates']['per_m3']['concrete'] == 200
    and d8.ext['quantities']['rates']['per_item']['door'] == 500,
    d8.ext,
)
txt9, _ = assistant('set_rates', {'rates': 'cheap'})
check('a rate card that is not a card is refused', txt9.startswith('refused'), txt9)

for i in IDS:
    t, _ = assistant('press_button', {'id': i})
    if not check('the assistant may press %s' % i, t.startswith('pressed'), t):
        break

finish()
