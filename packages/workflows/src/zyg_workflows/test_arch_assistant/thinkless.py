# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The thinkless pass and the one live request."""

from zyg_workflows import arch_assistant as A
from zyg_workflows import paths
import time
from zyg_workflows.test_arch_assistant.drawer import check

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def test_thinkless():
    """2026-09-10: the seven changes that take the arithmetic, the missing
    recipe and the known traps out of the model's first thought."""
    _zyg_log.info('thinkless')
    check(
        'cells: block_around centres an even block one rule (FH100, 20 x 20 -> EX90..FQ109)',
        A.block_around('FH100', 20, 20) == ('EX90', 'FQ109') and A.block_around('C4', 3, 3) == ('B3', 'D5'),
    )
    check(
        'cells: cell_offset walks columns and rows',
        A.cell_offset('FH112', -6, 0) == 'FB112' and A.cell_offset('A1', 2, 3) == 'C4',
    )
    d = A.Drawing({'objects': []})
    r = A.call_tool(
        d, 'plan_building', {'use': 'residential', 'storeys': 20, 'centre': 'FH100', 'width': 20, 'depth': 20}
    )
    # 2026-09-16: the entrance how-line names build_entrance(group, side="south") when
    # entrance_kit is loaded and falls back to add_opening when it is not. The check is
    # that the line is LITERAL and names a real tool, not which of the two it names.
    check(
        'plan_building takes centre + width + depth',
        'EX90..FQ109' in r and ('build_entrance(group, side="south"' in r or 'add_opening(group, side="south"' in r),
        r[:200],
    )
    r = A.call_tool(
        d, 'draw_box', {'centre': 'FH100', 'width': 20, 'depth': 20, 'storeys': 20, 'roof': 'flat', 'name': 'tower'}
    )
    check(
        'draw_box takes centre + width + depth and names the deck',
        'EX90..FQ109' in r and 'Roof deck at 54.3 m (storey 20)' in r,
        r[:300],
    )
    check('draw_box lists ids readably', 'south: o2, o7, o12 … o97' in r, r[-260:])
    r = A.call_tool(d, 'draw_box', {'storeys': 2})
    check(
        'draw_box without corners or centre refuses with the rule', r.startswith('refused') and 'centre + width' in r, r
    )
    r = A.call_tool(d, 'add_opening', {'group': 'tower', 'side': 'south', 'storey': 0, 'kind': 'double_door'})
    door = [o for o in d.objs if o['kind'] == 'double_door']
    south0 = [o for o in d.objs if o.get('name') == 'south wall st0'][0]
    check(
        'add_opening by group + side + storey lands the door in the south ground wall',
        len(door) == 1 and 'south side of "tower", storey 0' in r and abs(door[0]['z'] - south0['z']) < 0.3,
        r,
    )
    r = A.call_tool(
        d,
        'add_canopy',
        {'group': 'tower', 'side': 'south', 'storey': 0, 'width': 12, 'depth': 5, 'height': 4.2, 'columns': 4},
    )
    check(
        'add_canopy by group + side + storey',
        r.startswith('canopy') and 'south side of "tower"' in r and '4 round columns' in r,
        r,
    )
    r = A.call_tool(d, 'add_opening', {'group': 'tower', 'side': 'up', 'storey': 0})
    check('a bad side is refused, not guessed', r.startswith('refused: side must be'), r)
    r = A.call_tool(d, 'add_opening', {'group': 'tower', 'side': 'south', 'storey': 40})
    check('a storey the group lacks is refused with the range', 'has no wall on storey 40' in r and '0..19' in r, r)
    r = A.call_tool(d, 'add_curtain_wall', {'walls': 'tower', 'storeys': [0, 2, 4, 6, 8, 10, 12, 14, 16, 18]})
    kept = [o for o in d.objs if o['id'] == south0['id']]
    check(
        'add_curtain_wall keeps the wall that holds the door, as glass',
        'replaced 39 wall' in r
        and 'kept 1 wall' in r
        and kept
        and kept[0]['kind'] == 'wall'
        and kept[0]['mat'] == 'mat_glass'
        and len([o for o in d.objs if o['kind'] == 'double_door']) == 1,
        r,
    )
    cw = [o for o in d.objs if o['kind'] == 'curtain_wall']
    check(
        '39 curtain walls on the even storeys',
        len(cw) == 39 and {A.storey_of(o['y'], 2.7) for o in cw} == {0, 2, 4, 6, 8, 10, 12, 14, 16, 18},
    )
    r = A.call_tool(
        d, 'add_canopy', {'group': 'tower', 'side': 'north', 'storey': 0, 'width': 6, 'depth': 3, 'height': 3.5}
    )
    check('a canopy accepts a curtain wall host', r.startswith('canopy') and 'north side' in r, r)
    r = A.call_tool(d, 'add_opening', {'group': 'tower', 'side': 'north', 'storey': 0, 'kind': 'door'})
    check(
        'a door on a curtain wall is refused with the fix',
        'is a curtain wall' in r and 'BEFORE add_curtain_wall' in r,
        r,
    )
    A.call_tool(d, 'add_parapet', {'group': 'tower', 'height': 1.1, 'cap': True})
    r = A.call_tool(
        d, 'add_pool', {'cell_from': 'FC104', 'cell_to': 'FL109', 'storey': 20, 'depth': 1.5, 'infinity': 'south'}
    )
    pool = [o for o in d.objs if o['kind'] == 'pool']
    check(
        'add_pool takes storey=20 and lands on the 54.3 deck',
        pool and abs(pool[0]['y'] - 54.3) < 1e-6 and 'lifted to its deck at 54.3' in r,
        r[:200],
    )
    r = A.call_tool(d, 'add_beach_set', {'cells': ['FG94', 'FH94'], 'umbrellas': False})
    ys = [o['y'] for o in d.objs if o['kind'] == 'sun_lounger']
    check(
        'loungers on a roof cell land on the deck without base_height', ys and all(abs(y - 54.3) < 1e-6 for y in ys), ys
    )
    r = A.call_tool(d, 'add_beach_set', {'cells': ['FH140'], 'umbrellas': False, 'name': 'street'})
    ys = [o['y'] for o in d.objs if o['kind'] == 'sun_lounger' and o['grp'] == 'street']
    check('loungers off the building stay on the ground', ys == [0.0], ys)
    r = A.call_tool(d, 'design_check', {})
    check(
        'design_check: the flat roof is the floor of storey 20 (no false slab error under the pool)',
        'no floor slab' not in r,
        r[:400],
    )
    d2 = A.Drawing({'objects': []})
    A.call_tool(d2, 'draw_box', {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 3, 'roof': 'none', 'name': 'b'})
    A.call_tool(d2, 'add_parapet', {'group': 'b', 'height': 1.1})
    d2.new('wall', {'len': 4, 'h': 2.7, 't': 0.24}, 0, 0, 8.1, 0.0, 'mat_concrete', name='plant screen', grp='b')
    r = A.call_tool(d2, 'design_check', {})
    check('design_check: without a roof or slab a walled storey still errors', 'no floor slab' in r, r[:300])
    txt = (
        'build a building with footprint of 20x20 , 20 stories high . infinity pool on the roof . make ground floor '
        'glass walls , 2nd floor rough concrete wall , repeat. center building at cell fh100. make it luxurious'
    )
    p = A.system_prompt(2.7, txt, d)
    info = dict(A.LAST_PROMPT_INFO)
    # 2026-09-16: the budget number is read from A.MAX_CALLS (28 -> 36 this day), so the
    # check tracks the constant instead of pinning a literal that a budget change breaks.
    check(
        'prompt: the recipe, the drawing-budget rule and the tower example are in',
        'ALTERNATING FACADES' in p
        and ('%d DRAWING calls' % A.MAX_CALLS) in p
        and 'centred on FH100' in p
        and 'block_around' in p,
    )
    check(
        'prompt: a tower request drops the terrain families but keeps the building ones',
        {'mountains', 'rivers_lakes', 'cliffs_rocks', 'coast_dunes', 'file_2d'} <= set(info['dropped'])
        and {
            'openings_special',
            'balconies_facade',
            'water_leisure',
            'stairs_vertical',
            'site_landscape',
            'blender_power',
        }
        <= set(info['kept'])
        and 'add_mountain_range(' not in p,
        (info['dropped'][:8], info['kept'][:8]),
    )
    full = A.system_prompt(2.7)
    check(
        'prompt: a tower prompt is at least a third shorter than the untrimmed one',
        len(p) < len(full) * 0.67,
        (len(p), len(full)),
    )
    p2 = A.system_prompt(2.7, 'a mountain range behind the house with a river and a cliff', d)
    check(
        'prompt: landscape words bring the families back',
        'add_mountain_range(' in p2 and 'add_river(' in p2 and 'add_cliff(' in p2,
    )
    d3 = A.Drawing({'objects': []})
    A.call_tool(
        d3, 'add_mountain', {'centre': 'K20', 'height': 60, 'radius': 40}
    ) if 'add_mountain' in A.TOOL_FN else None
    A.system_prompt(2.7, 'make it nicer', d3)  # populates A.LAST_PROMPT_INFO, checked next
    check(
        'prompt: a family whose kind is already in the drawing stays in',
        'mountains' in A.LAST_PROMPT_INFO['kept'] or not any(o['kind'].startswith('mountain') for o in d3.objs),
    )
    check('prompt: dropped families are named so the model can ask help()', 'More families exist' in p and 'help(' in p)
    check(
        'prompt: the ground-floor phrase does not summon the terrain families',
        'terrain' in info['dropped'] and 'ground_v3' in info['dropped'],
    )
    names = {t['name'] for t in A.TOOL_DEFS}
    check(
        'tools: block_around and cell_offset are tools; schemas still complete',
        {'block_around', 'cell_offset', 'add_mountain_range'} <= names,
    )


def test_live():
    """One real request through the real server. Prints, does not assert."""
    from zyg_workflows import http_json

    _zyg_log.info('live (spends tokens)')
    doc = {'name': 'probe', 'objects': []}
    body = {
        'text': 'On grid C4 build a house 4x4 squares, 2 storeys, glass windows every 2 floors, gable roof.',
        'history': [],
        'doc': doc,
        'name': 'probe',
        'defaults': {'wall_h': 2.7, 'wall_t': 0.24},
        'state': {'storey': 0, 'cells': True, 'view': 'perspective', 'selected': []},
        'backend': 'claude',
    }
    start_url = paths.ZYG_KANBAN_URL + '/inspect/api/architecture/assistant/start'
    jid = http_json.post_json(start_url, body, timeout=30)['id']
    t0 = time.time()
    while time.time() - t0 < 300:
        job_url = f'{paths.ZYG_KANBAN_URL}/inspect/api/architecture/assistant/job?id={jid}'
        j = http_json.request_json(job_url, timeout=30)
        if j['status'] == 'need_client':
            http_json.post_json(
                paths.ZYG_KANBAN_URL + '/inspect/api/architecture/assistant/render',
                {'id': jid, 'image': ''},
                timeout=30,
            )
        if j['status'] in ('done', 'error', 'question'):
            break
        time.sleep(1.5)
    _zyg_log.info(
        ' '.join(
            str(a)
            for a in (
                '  status',
                j['status'],
                '| backend',
                j.get('backend'),
                '| model',
                j.get('model'),
                '| steps',
                j.get('steps'),
                '| session',
                j.get('session'),
                '| usage',
                j.get('usage'),
            )
        )
    )
    _zyg_log.info(
        ' '.join(str(a) for a in ('  thoughts', len(j.get('thoughts') or []), '| thinking s', j.get('think_s')))
    )
    for t in (j.get('thoughts') or [])[:3]:
        _zyg_log.info('    thought %gs: %s' % (t['s'], t['text'][:160].replace(chr(10), ' ')))
    for line in j.get('log', []):
        _zyg_log.info(' '.join(str(a) for a in ('   ', line)))
    if j['status'] == 'done':
        objs = j['result']['doc']['objects']
        kinds = {}
        for o in objs:
            kinds[o['kind']] = kinds.get(o['kind'], 0) + 1
        _zyg_log.info(' '.join(str(a) for a in ('  result kinds', kinds, '| summary:', j['result']['summary'])))
        check('live: something was drawn', bool(objs))
    elif j['status'] == 'question':
        _zyg_log.info(' '.join(str(a) for a in ('  question:', j['question'])))
    else:
        check('live: no error', False, j.get('error'))
