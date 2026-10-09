# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from .placing import A, FLOOR, FP, TD, TW, UNIT, assistant, cells, check, finish, os, tempfile, tool_names

# ── an empty library ─────────────────────────────────────────────────────────
empty = tempfile.mkdtemp(prefix='zyg_plans_empty_')
old = os.environ['ZYG_PLANS_DIR']
os.environ['ZYG_PLANS_DIR'] = empty
try:
    t = A.call_tool(A.Drawing(None), 'search_plans', {'kind': 'unit'})
    check(
        'an empty ZYG_PLANS_DIR refuses with "no plan packs"',
        t.startswith('refused:') and 'no plan packs' in t,
        t[:140],
    )
    t = A.call_tool(A.Drawing(None), 'place_plan', {'plan_id': UNIT['id'], 'cell_from': 'C4', 'cell_to': 'M14'})
    check('and place_plan refuses too instead of drawing nothing', t.startswith('refused:'), t[:120])
finally:
    os.environ['ZYG_PLANS_DIR'] = old
    FP.packs(force=True)
    os.rmdir(empty)

# ── credits: attributions(), the INFO finding, the file beside an export ─────
F2 = A.EXT_MODULES['file_2d']
F3 = A.EXT_MODULES['file_3d']
DR = A.EXT_MODULES['design_rules']
SWISS = FP.attribution_of('swiss_dwellings')

check(
    'attributions is registered as a tool of the family',
    'attributions' in tool_names(),
    [t[0]['name'] for t in FP.TOOLS],
)
check(
    'an EXAMPLE shows attributions being asked for',
    any(c['tool'] == 'attributions' for e in FP.EXAMPLES for c in e['calls']),
    [[c['tool'] for c in e['calls']] for e in FP.EXAMPLES],
)

t = A.call_tool(A.Drawing(None), 'attributions', {})
check(
    'a drawing with no plans in it owes no credits, and is not refused',
    not t.startswith('refused') and 'no credits' in t,
    t[:140],
)

cfc, ctc = cells(UNIT['w'], UNIT['d'], 4, 40)
_t, dcred = assistant(
    'place_plan', {'plan_id': UNIT['id'], 'cell_from': cfc, 'cell_to': ctc, 'storey': 0, 'shell': True}
)
check(
    'placing a unit recorded an attribution on the drawing',
    bool(dcred.ext.get('attributions')),
    dcred.ext.get('attributions'),
)
t = A.call_tool(dcred, 'attributions', {})
check('attributions quotes the Swiss Dwellings line word for word', SWISS in t, t[:220])
check('and names the plan it was used for', UNIT['id'] in t, t[:260])

found = DR.run_checks(dcred)
cred = [f for f in found if f.get('code') == 'credits']
check('design_check reports exactly one credits finding', len(cred) == 1, [(f['sev'], f['code']) for f in found])
check('the credits finding is INFO, so it never blocks done', bool(cred) and cred[0]['sev'] == 'info', cred[:1])
check(
    'the finding says "credits required" and carries the licence line',
    bool(cred)
    and cred[0]['text'].startswith('credits required: ')
    and SWISS in cred[0]['text']
    and 'CC BY 4.0' in cred[0]['text'],
    cred[0]['text'][:200] if cred else None,
)
_t, dplain = assistant(
    'draw_box', {'centre': 'K200', 'width': 6, 'depth': 6, 'storeys': 1, 'roof': 'flat', 'name': 'plain'}
)
check(
    'a drawing with no plan in it gets no credits finding at all',
    not [f for f in DR.run_checks(dplain) if f.get('code') == 'credits'],
    [f.get('code') for f in DR.run_checks(dplain)],
)
check(
    'check_attributions is registered in DESIGN_CHECKS',
    any(getattr(f, '__name__', '') == 'check_attributions' for f in (FP.DESIGN_CHECKS or [])),
    [getattr(f, '__name__', '?') for f in (FP.DESIGN_CHECKS or [])],
)

_edir = tempfile.mkdtemp(prefix='zyg_exports_')


class _FakeSrv:
    """Stands in for arch_server_ext.file_2d/file_3d: the exports directory is a
    temp one, and ifc() writes a real file instead of starting Blender."""

    EXPORT_DIR = _edir

    def ifc(self, payload, method):
        p = os.path.join(_edir, 'model.ifc')
        with open(p, 'w', encoding='utf-8') as f:
            f.write('ISO-10303-21;\nEND-ISO-10303-21;\n')
        return {
            'ok': True,
            'elements': 5,
            'storeys': 1,
            'by_class': {'IfcWall': 5},
            'path': p,
            'rel': 'exports/model.ifc',
            'bytes': os.path.getsize(p),
            'skipped': 0,
        }


_fake = _FakeSrv()
_old2, _old3 = F2._srv, F3._srv
F2._srv = lambda: _fake
F3._srv = lambda: _fake
try:
    cf_path = os.path.join(_edir, 'credits.txt')
    t = A.call_tool(dcred, 'export_drawing', {'format': 'dxf', 'what': 'plan'})
    check('a dxf export of a drawing that owes credits says so in the reply', t.endswith(' + credits.txt'), t[-80:])
    check('and writes the credit lines into the exports directory', os.path.isfile(cf_path), sorted(os.listdir(_edir)))
    check(
        'the credits file holds the attribution line verbatim',
        os.path.isfile(cf_path) and open(cf_path, encoding='utf-8').read().strip() == FP.credits_text(dcred).strip(),
        open(cf_path, encoding='utf-8').read()[:200] if os.path.isfile(cf_path) else None,
    )

    os.remove(cf_path)
    t = A.call_tool(dcred, 'export_drawing', {'format': 'svg', 'what': 'plan'})
    check(
        'an svg export writes the credits file too', t.endswith(' + credits.txt') and os.path.isfile(cf_path), t[-80:]
    )

    os.remove(cf_path)
    t = A.call_tool(dcred, 'export_model', {'format': 'glb'})
    check(
        'a glb export from the 3D family writes the same credits file',
        t.endswith(' + credits.txt') and os.path.isfile(cf_path),
        t[-80:],
    )

    t = A.call_tool(dcred, 'export_ifc', {'schema': 'IFC4'})
    ifc_cred = os.path.join(_edir, 'model.ifc.credits.txt')
    check(
        'an ifc export writes <file>.credits.txt beside the file it wrote',
        os.path.isfile(ifc_cred) and ' + credits.txt' in t,
        (t[:180], sorted(os.listdir(_edir))),
    )
    check(
        'that credits file carries the Swiss line',
        os.path.isfile(ifc_cred) and SWISS in open(ifc_cred, encoding='utf-8').read(),
        open(ifc_cred, encoding='utf-8').read()[:160] if os.path.isfile(ifc_cred) else None,
    )

    for fn in os.listdir(_edir):
        os.remove(os.path.join(_edir, fn))
    t = A.call_tool(dplain, 'export_drawing', {'format': 'dxf', 'what': 'plan'})
    check(
        'a drawing that owes no credits gets NO credits file and no mention',
        'credits' not in t and not os.listdir(_edir),
        (t[-60:], os.listdir(_edir)),
    )
finally:
    F2._srv, F3._srv = _old2, _old3
    for fn in os.listdir(_edir):
        os.remove(os.path.join(_edir, fn))
    os.rmdir(_edir)

# ── repeat_floor over an ALTERNATING facade (job 944061f70863, 2026-09-16) ──
d9 = A.Drawing(None)
A.call_tool(d9, 'draw_box', dict(centre='FH100', width=TW, depth=TD, storeys=4, roof='flat', name='tower'))
A.call_tool(d9, 'add_curtain_wall', dict(walls='tower', storeys=[2]))
p9 = A.call_tool(d9, 'place_plan', {'plan_id': FLOOR['id'], 'group': 'tower', 'storey': 1, 'align': 'centre'})
check('the plan is placed on the concrete storey 1', not str(p9).startswith('refused'), str(p9)[:160])
r9 = A.call_tool(d9, 'repeat_floor', dict(source_storey=1, from_storey=2, to_storey=3))
check('repeat_floor over a glazed storey 2 and a solid storey 3 runs', not str(r9).startswith('refused'), str(r9)[:200])
ops9 = [o for o in d9.objs if A.is_opening(o['kind']) and (o.get('grp') or '').startswith('plan ')]
bad_host = []
for o in ops9:
    h = d9.find(str((o.get('meta') or {}).get('host') or ''))
    if h is None:
        continue
    if h['kind'] == 'curtain_wall':
        bad_host.append((o['id'], 'in a curtain wall'))
    elif h['kind'] == 'wall' and abs(h['y'] - o['y']) > 0.05:
        bad_host.append((o['id'], f'host {h["id"]} one storey away'))
check(
    'no copied facade opening is cut into a curtain wall, and none is hosted by a wall on another storey',
    not bad_host,
    bad_host[:6],
)
check(
    'the reply says how many facade openings the glazed storey did not take',
    'not copied onto glazed storeys' in str(r9),
    str(r9)[:240],
)
st3 = [o for o in d9.objs if (o.get('grp') or '').startswith('plan ') and abs(o['y'] - 3 * d9.storey_h) < 0.4]
check('storey 3 (solid) still got its plan records', len(st3) > 10, len(st3))
ids3 = (d9.ext.get('floor_layouts') or {}).get('3', {}).get('ids') or []
check(
    'the store lists exactly the records copied onto storey 3 (openings skipped on 2 do not shift it)',
    ids3 and all(abs((d9.find(i) or {}).get('y', -9) - 3 * d9.storey_h) < 2.7 for i in ids3),
    (len(ids3), ids3[:3]),
)

# ── place_plan undoes itself when the plan makes the storey unwalkable ──
d10 = A.Drawing(None)
A.call_tool(d10, 'draw_box', dict(centre='FH100', width=TW, depth=TD, storeys=4, roof='flat', name='tower'))
n_before = len(d10.objs)
_real = FP._plan_errors
_calls = [0]


def _fake_errors(dd):
    _calls[0] += 1
    return [] if _calls[0] == 1 else [('walk_storey', 'storey 2: the stair landing cannot be reached (test)')]


FP._plan_errors = _fake_errors
try:
    r10 = A.call_tool(d10, 'place_plan', {'plan_id': FLOOR['id'], 'group': 'tower', 'storey': 2, 'align': 'centre'})
finally:
    FP._plan_errors = _real
check(
    'a plan that adds a walkability error is REFUSED and names layout_floor',
    str(r10).startswith('refused:') and 'unwalkable' in str(r10) and 'layout_floor' in str(r10),
    str(r10)[:200],
)
check(
    '... and nothing of it stays on the drawing',
    len(d10.objs) == n_before and not (d10.ext.get('floor_layouts') or {}).get('2'),
    (len(d10.objs), n_before),
)
check('_plan_errors on a bare box is empty', FP._plan_errors(d10) == [], FP._plan_errors(d10)[:2])

finish()
