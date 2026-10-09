# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_object_specs — the knowledge base: resolution, budget, gaps, and the
three checks it contributes to the done gate."""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, tool_names  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

# load_extensions() builds each family with spec_from_file_location and never
# puts it in sys.modules, so `import arch_assistant_ext.object_specs` would be a
# SECOND, independent copy — patching its GAP_LOG would leave the live one
# writing to the real ledger. Always test the instance the assistant runs.
OS = A.EXT_MODULES['object_specs']
DR = A.EXT_MODULES['design_rules']

check('the tool is registered', 'spec' in tool_names())

# ── the store ────────────────────────────────────────────────────────────────
specs = OS.load_specs(force=True)
check('the seeded store loaded', len(specs) >= 30, f'{len(specs)} sheets')
bad = {k: OS.validate_spec(s) for k, s in specs.items() if OS.validate_spec(s)}
check('every installed sheet validates', not bad, bad)
over = {k: len(OS.prose(s)) for k, s in specs.items() if len(OS.prose(s)) > OS.PROSE_MAX}
check(f'every sheet fits the {OS.PROSE_MAX}-char budget', not over, over)
check(
    'every sheet answers all six questions',
    all(
        all(str(s.get(f) or '').strip() or s.get(f) for f in OS.FIELDS) and isinstance(s.get('space'), dict)
        for s in specs.values()
    ),
)

# ── resolution ───────────────────────────────────────────────────────────────
for term, want in (
    ('elevator', 'elevator'),
    ('lift', 'elevator'),
    ('elevator_car', 'elevator'),
    ('add_corridor', 'corridor'),
    ('pathways', 'corridor'),
    ('hallway', 'corridor'),
    ('dining table', 'dining_table'),
    ('porte cochere', 'canopy'),
    ('roof terrace', 'roof_deck'),
    ('escape stair', 'fire_escape'),
    ('bin store', 'refuse_store'),
):
    got = OS.spec_for(term)
    check(f'"{term}" resolves to {want}', got and got['key'] == want, got and got['key'])

# the substring trap: "stable" must NOT reach the dining_table sheet
for term in ('unicorn stable', 'stable', 'cable tray', 'streetcar'):
    check(f'"{term}" resolves to nothing', OS.spec_for(term) is None, (OS.spec_for(term) or {}).get('key'))

# ── validation refuses what would poison the store ───────────────────────────
for label, s in (
    ('no key', {'title': 'x'}),
    ('missing questions', {'key': 'k', 'title': 'T', 'what': 'a', 'source': 'seeded'}),
    (
        'bad host',
        {
            'key': 'k',
            'title': 'T',
            'what': 'a',
            'looks': 'a',
            'how': 'a',
            'avoid': ['a'],
            'quality': ['a'],
            'space': {'host': 'sky'},
            'source': 'seeded',
        },
    ),
    (
        'researched with no source',
        {
            'key': 'k',
            'title': 'T',
            'what': 'a',
            'looks': 'a',
            'how': 'a',
            'avoid': ['a'],
            'quality': ['a'],
            'space': {},
            'source': 'researched',
        },
    ),
):
    check(f'validate refuses: {label}', bool(OS.validate_spec(s)))

# ── the tool ─────────────────────────────────────────────────────────────────
txt, d = assistant('spec', {'of': 'corridor'})
check('spec() returns the sheet', 'Corridor' in txt and '1.2 m' in txt, txt[:120])
check('spec() carries the SPACE line', 'SPACE:' in txt)
check('spec() marks a seeded sheet as unverified', 'seeded' in txt)
txt, _ = assistant('spec', {'of': ''})
check('spec() refuses an empty term', txt.startswith('refused:'), txt[:80])

# ── gaps: the "log it once" half ─────────────────────────────────────────────
tmp = tempfile.mkdtemp()
old_log, OS.GAP_LOG = OS.GAP_LOG, os.path.join(tmp, 'gaps.jsonl')
try:
    txt, d = assistant('spec', {'of': 'zorbing pit'})
    check('an unknown term is refused helpfully, not invented', 'no spec' in txt and 'queued' in txt, txt[:100])
    rows = [json.loads(x) for x in open(OS.GAP_LOG, encoding='utf-8')]
    check('the miss is logged as a gap', any(r['key'] == 'zorbing_pit' and r['why'] == 'asked' for r in rows), rows)

    from zyg_workflows.arch_assistant import Drawing

    dd = Drawing({'objects': [{'id': 'o1', 'kind': 'ferris_wheel', 'p': {'w': 4, 'd': 4}, 'x': 0, 'y': 0, 'z': 0}]})
    OS.check_gaps(dd)
    rows = [json.loads(x) for x in open(OS.GAP_LOG, encoding='utf-8')]
    check('a kind that was BUILT is logged too', any(r['key'] == 'ferris_wheel' and r['why'] == 'built' for r in rows))
    check('gaps() ranks by count', OS.gaps() and OS.gaps()[0]['n'] >= 1)
finally:
    OS.GAP_LOG = old_log

# ── the checks ───────────────────────────────────────────────────────────────
from zyg_workflows.arch_assistant import Drawing  # noqa: E402

# a table with a wall inside its 1.0 m ring
d = Drawing(
    {
        'objects': [
            {'id': 'o1', 'kind': 'dining_table', 'p': {'w': 1.6, 'd': 0.9}, 'x': 0, 'y': 0, 'z': 0},
            {
                'id': 'o2',
                'kind': 'partition',
                'p': {'len': 4, 'h': 2.5, 't': 0.1, 'w': 4, 'd': 0.1},
                'x': 0,
                'y': 0,
                'z': 1.0,
            },
        ]
    }
)
f = OS.check_clearances(d)
check('a wall inside the table ring is reported', f and f[0]['code'] == 'clearance', f)
d2 = Drawing(
    {
        'objects': [
            {'id': 'o1', 'kind': 'dining_table', 'p': {'w': 1.6, 'd': 0.9}, 'x': 0, 'y': 0, 'z': 0},
            {
                'id': 'o2',
                'kind': 'partition',
                'p': {'len': 4, 'h': 2.5, 't': 0.1, 'w': 4, 'd': 0.1},
                'x': 0,
                'y': 0,
                'z': 2.6,
            },
        ]
    }
)
check('the same wall outside the ring is not', not OS.check_clearances(d2), OS.check_clearances(d2))

# an undersized lift car
d3 = Drawing(
    {'objects': [{'id': 'o1', 'kind': 'elevator_car', 'p': {'w': 0.8, 'd': 0.9, 'h': 2.2}, 'x': 0, 'y': 0, 'z': 0}]}
)
f = OS.check_dims(d3)
check('an undersized lift car is an ERROR', f and f[0]['sev'] == 'error' and f[0]['code'] == 'undersize', f)
d4 = Drawing(
    {'objects': [{'id': 'o1', 'kind': 'elevator_car', 'p': {'w': 1.6, 'd': 1.4, 'h': 2.2}, 'x': 0, 'y': 0, 'z': 0}]}
)
check('a proper lift car passes', not OS.check_dims(d4), OS.check_dims(d4))

# a table floating 5 m over nothing (host = floor, and no deck under it)
d5 = Drawing({'objects': [{'id': 'o1', 'kind': 'dining_table', 'p': {'w': 1.6, 'd': 0.9}, 'x': 0, 'y': 5.0, 'z': 0}]})
check(
    'an unsupported object is reported', any(x['code'] == 'unsupported' for x in OS.check_hosts(d5)), OS.check_hosts(d5)
)
d6 = Drawing(
    {
        'objects': [
            {'id': 'o1', 'kind': 'slab', 'p': {'w': 10, 'd': 10, 't': 0.3}, 'x': 0, 'y': 4.7, 'z': 0},
            {'id': 'o2', 'kind': 'dining_table', 'p': {'w': 1.6, 'd': 0.9}, 'x': 0, 'y': 5.0, 'z': 0},
        ]
    }
)
check(
    'the same table ON a deck is not',
    not [x for x in OS.check_hosts(d6) if x['code'] == 'unsupported'],
    OS.check_hosts(d6),
)
check(
    'a kind with no sheet is not judged',
    not OS.check_hosts(
        Drawing({'objects': [{'id': 'o1', 'kind': 'ferris_wheel', 'p': {'w': 8, 'd': 8}, 'x': 0, 'y': 9.0, 'z': 0}]})
    ),
)

# ── the seam into the done gate ──────────────────────────────────────────────
names = [f.__name__ for f in DR.contributed()]
check(
    'design_rules collects the contributed checks',
    {'check_dims', 'check_clearances', 'check_hosts', 'check_gaps'} <= set(names),
    names,
)
codes = {f['code'] for f in DR.run_checks(d3)}
check('run_checks now reports a spec finding', 'undersize' in codes, codes)

# ── the checks resolve by KIND, exactly (2026-09-08) ─────────────────────────
# `asset` is any library model at all; through the tool name place_asset it once
# resolved to the BED sheet, and every real lamp post in a drawing was reported
# as an undersized bed. The model's spec() stays fuzzy; the checks do not.
check('the fuzzy lookup still reaches a sheet for "asset"', OS.spec_for('asset') is not None)
check(
    'the EXACT lookup refuses a container kind',
    OS.spec_for_kind('asset') is None,
    (OS.spec_for_kind('asset') or {}).get('key'),
)
for k in ('component', 'mesh_file', 'box', 'cylinder'):
    check(f'"{k}" is a container, not a thing', OS.spec_for_kind(k) is None)
check('a real kind still resolves exactly', (OS.spec_for_kind('elevator_car') or {})['key'] == 'elevator')
check(
    'a kind is not reached through a TOOL name',
    OS.spec_for_kind('place_asset') is None,
    (OS.spec_for_kind('place_asset') or {}).get('key'),
)
d_lamp = Drawing(
    {
        'objects': [
            {
                'id': 'o1',
                'kind': 'asset',
                'name': 'lamp post 1',
                'p': {'item': 'street_lamp_01_2k', 'bw': 0.5, 'bd': 0.5, 'bh': 5.0},
                'x': 0,
                'y': 0,
                'z': 0,
            }
        ]
    }
)
check(
    'a real-model lamp is not judged against another sheet',
    not OS.check_dims(d_lamp) and not OS.check_clearances(d_lamp),
    OS.check_dims(d_lamp) + OS.check_clearances(d_lamp),
)


finish()
