# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""building_program.tools — the design check and the two tools.

Moved verbatim from arch_assistant_ext/building_program.py lines 1473-1782
(2026-10 split).
"""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.building_program.evidence import (
    DENSITY,
    EXT_KEY,
    USES,
    Drawing,
    _num,
    parse_cell,
    resolve_block,
)
from zyg_workflows.arch_assistant_ext.building_program.checklist import BY_KEY
from zyg_workflows.arch_assistant_ext.building_program.resolving import get_program, read_request, resolve, status


# ── the design check: done refuses while a REQUIRED item is missing ──────────
def check_program(d: Drawing) -> list:
    prog = get_program(d)
    if not prog:
        return []
    out = []
    rows = status(d, prog)
    missing = [r for r in rows if r['need'] == 'required' and not r['ok']]
    soft = [r for r in rows if r['need'] == 'recommended' and not r['ok']]
    for r in missing[:6]:
        out.append(
            {
                'sev': 'error',
                'code': 'program',
                'text': f'the program for this {prog["storeys"]}-storey {prog["use"]} requires '
                f'{r["title"].lower()} ({r["why"]}) — not found: {r["detail"]}. '
                f'Build it: {r["how"]}  [spec("{r["spec"]}")]. '
                f'If the user does not want it, plan_building(..., skip=["{r["key"]}"])',
            }
        )
    if len(missing) > 6:
        out.append(
            {
                'sev': 'error',
                'code': 'program',
                'text': f'{len(missing) - 6} more required item(s) not built: '
                + ', '.join(r['title'].lower() for r in missing[6:])
                + ' — program_status() lists them with the tool call for each',
            }
        )
    if soft:
        out.append(
            {
                'sev': 'warn',
                'code': 'program',
                'text': f'{len(soft)} recommended item(s) not built: '
                + '; '.join(f'{r["title"].lower()} ({r["how"].split("(")[0]})' for r in soft[:6]),
            }
        )
    return out


DESIGN_CHECKS = [check_program]


# ── the tools ────────────────────────────────────────────────────────────────
def _fmt(prog: dict, rows=None) -> str:
    L = [
        f'PROGRAM — {prog["storeys"]}-storey {prog["use"]} on {prog["cell_from"]}..{prog["cell_to"]} '
        f'({prog["w"]:g} x {prog["d"]:g} m plate, {prog["area"]:g} m2/floor, {prog["gross"]:g} m2 gross, '
        f'~{prog["occupants"]} occupants{", glazed facade" if prog["glass"] else ""}).'
    ]
    fr = prog.get('from_request') or []
    um = prog.get('unmapped') or []
    if fr or um:
        L.append('')
        L.append("FROM THE REQUEST — the user's own words, and what each one put on this checklist:")
        for r in fr:
            L.append(f'  · "{r.get("match")}" -> {r.get("says")}')
        if prog.get('finish_level') == 'luxury':
            L.append(
                '  · finish level LUXURY: the lobby, the roof deck and every visible surface answer to it '
                '— a library material, not a mat_ preset'
            )
        if um:
            L.append('REQUEST WORDS NOT MAPPED — decide and build, or tell the user: ' + ', '.join(um))
    by = {}
    for r in rows if rows is not None else prog['items']:
        by.setdefault(r['need'], []).append(r)
    for need, head in (
        ('required', 'REQUIRED — done refuses while one of these is missing'),
        ('recommended', 'RECOMMENDED'),
        ('waived', 'WAIVED by the request'),
    ):
        rs = by.get(need) or []
        if not rs:
            continue
        L.append('')
        L.append(head)
        for i, r in enumerate(rs, 1):
            mark = ''
            if 'ok' in r:
                mark = '[built] ' if r['ok'] else '[TODO] '
            cnt = f' x{r["n"]}' if r.get('n', 1) > 1 else ''
            L.append(f'{i:2d}. {mark}{r["title"]}{cnt}: {r["pick"]} — {r["how"]}')
            if 'ok' in r and not r['ok']:
                L.append(f'      not found: {r["detail"]}')
    dec = [r for r in prog['items'] if len(r.get('options') or []) > 1 and r['need'] != 'waived']
    if dec and rows is None:
        L.append('')
        L.append(
            'DECIDE — defaults already chosen; build with them unless the request asked to be consulted, '
            'and then put ALL of these in ONE ask_user:'
        )
        for r in dec[:8]:
            alt = ', '.join(o for o in r['options'] if o != r['pick'])
            L.append(f'  · {r["key"]}: {r["pick"]}  (or {alt})')
    L.append('')
    L.append(
        'Order: shell and storeys (draw_box: centre + width + depth) -> entrance (door + canopy by side) '
        '-> facade (add_curtain_wall storeys=[…]) -> core (stair + lift) -> lobby -> TYPICAL FLOORS '
        '(search_plans(kind="floor") -> place_plan(align="core", storey=1) -> repeat_floor; tile_units '
        'or layout_floor when no floor fits) -> facade -> roof and plant -> approach and landscape -> '
        'design_check -> present -> done. Call spec("<name>") for any item you are unsure of.'
    )
    L.append('Every how-line above is literal: call it with real cells; its reply names what it made.')
    return '\n'.join(L)


def t_plan_building(
    d: Drawing,
    a,
    use='office',
    storeys=1,
    cell_from='',
    cell_to='',
    glass=None,
    skip=None,
    name='',
    centre=None,
    width=None,
    depth=None,
    request='',
):
    try:
        cell_from, cell_to = resolve_block(cell_from, cell_to, centre, width, depth)  # 2026-09-10: centre + size
    except ValueError as e:
        return f'refused: {e}'
    u = str(use or '').strip().lower()
    if u not in DENSITY:
        return f'refused: use must be one of {", ".join(USES)}'
    if not cell_from or not cell_to:
        return 'refused: give the footprint as cell_from and cell_to (the block the building stands on)'
    try:
        parse_cell(cell_from), parse_cell(cell_to)
    except ValueError as e:
        return f'refused: {e}'
    st = int(_num(storeys, 1))
    if st < 1 or st > 200:
        return 'refused: storeys must be between 1 and 200'
    # the request's own words: what the job was asked for, not only what the use
    # and the height imply.  `request` overrides it for a replan.
    text = str(request or '') or str(getattr(d, 'request', '') or '')
    known = set(BY_KEY) | set(read_request(text)['require'])
    sk = skip if isinstance(skip, list) else ([skip] if skip else [])
    bad = [s for s in sk if str(s).strip().lower() not in known]
    if bad:
        return (
            f'refused: nothing to skip called {", ".join(str(b) for b in bad)} — keys are: {", ".join(sorted(known))}'
        )
    prog = resolve(u, st, cell_from, cell_to, glass, sk, request=text)
    prog['name'] = str(name or d.name or '')[:60]
    d.ext[EXT_KEY] = prog
    n_req = sum(1 for r in prog['items'] if r['need'] == 'required')
    return _fmt(prog) + f'\n\n({n_req} required items are now the done gate for this drawing.)'


def t_program_status(d: Drawing, a, skip=None):
    prog = get_program(d)
    if not prog:
        return (
            'no program on this drawing yet — call plan_building(use, storeys, cell_from, cell_to) once, '
            'before drawing, and the checklist is resolved in that single call'
        )
    if skip:
        sk = skip if isinstance(skip, list) else [skip]
        known = set(BY_KEY) | {r['key'] for r in prog.get('items') or []}
        bad = [s for s in sk if str(s).strip().lower() not in known]
        if bad:
            return f'refused: nothing to skip called {", ".join(str(b) for b in bad)}'
        # 2026-09-16 (job 71e9d42e559f): the model waived corridor, typical_floors,
        # wc, bike_store and refuse_store on a 20-storey residential to call it
        # 'a massing model' and handed over 19 bare storeys. skip= is for what the
        # USER does not want (parking, a loading bay); a REQUIRED item is built.
        want = {str(s).strip().lower() for s in sk}
        req = [r for r in prog['items'] if r['key'] in want and r.get('need') == 'required']
        if req:
            how = '; '.join(f'{r["key"]}: {str(r.get("how") or "")[:90]}' for r in req[:4])
            return (
                f'refused: {", ".join(r["key"] for r in req)} — REQUIRED for this building and not skippable; '
                f'build them ({how}). skip= is for recommended items the user does not want'
            )
        for r in prog['items']:
            if r['key'] in {str(s).strip().lower() for s in sk}:
                r['need'] = 'waived'
        d.ext[EXT_KEY] = prog
    rows = status(d, prog)
    todo = [r for r in rows if r['need'] == 'required' and not r['ok']]
    head = (
        'every required item is built' if not todo else f'{len(todo)} required item(s) still missing — done will refuse'
    )
    return _fmt(prog, rows) + '\n' + head


TOOLS = [
    (
        {
            'name': 'plan_building',
            'description': 'THE CHECKLIST. Call this ONCE, before drawing, whenever the request is for a building. It '
            'resolves the whole programme deterministically in one call — which items this building must '
            'have (entrance, core, lift count from the occupancy, second escape, corridors, WCs, roof, '
            'parapet, plant, approach lighting, stores, parking), each with its default already chosen '
            'and the tool call that builds it — and returns the build order. It costs one step and saves '
            'the whole question-and-answer round trip: do NOT ask the user item by item. If the request '
            'says to consult the user, put every line of the DECIDE block into ONE ask_user. The '
            'programme is stored on the drawing and becomes the done gate: done refuses while a REQUIRED '
            'item is missing. Use skip=["parking", …] for anything the user does not want.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'use': {
                        'type': 'string',
                        'description': 'house, residential, office, hotel, school, retail, warehouse, civic or mixed',
                    },
                    'storeys': {
                        'type': 'integer',
                        'description': 'storeys above ground, the number the user asked for',
                    },
                    'cell_from': {'type': 'string', 'description': 'one corner cell of the footprint'},
                    'cell_to': {'type': 'string', 'description': 'the opposite corner cell'},
                    'centre': {
                        'type': 'string',
                        'description': 'the centre cell — with width + depth instead of the corners',
                    },
                    'width': {'type': 'integer', 'description': 'cells along X, with centre'},
                    'depth': {'type': 'integer', 'description': 'cells along Z, with centre (default: width)'},
                    'glass': {
                        'type': 'boolean',
                        'description': 'a glazed/curtain-wall facade (default: inferred from use and height)',
                    },
                    'skip': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'programme keys the user does not want, e.g. ["parking", "balconies"]',
                    },
                    'request': {
                        'type': 'string',
                        'description': "the user's own words, if you are replanning — by "
                        'default the request that started the job is read '
                        'automatically, and its words add items (a roof pool, '
                        'a gym, balconies), force picks and set the finish level',
                    },
                    'name': {'type': 'string'},
                },
                'required': ['use', 'storeys'],
            },
        },
        t_plan_building,
    ),
    (
        {
            'name': 'program_status',
            'description': 'The checklist for this drawing measured against what is actually built: which required items '
            'are there and which are still missing, with the tool call for each. Call it after the shell '
            'is up and again before done. skip=[keys] waives items the user does not want.',
            'input_schema': {
                'type': 'object',
                'properties': {'skip': {'type': 'array', 'items': {'type': 'string'}}},
                'required': [],
            },
        },
        t_program_status,
    ),
]

PROMPT = (
    'BUILDING PROGRAMME: for a request to build a BUILDING, call plan_building(use, storeys, cell_from, '
    'cell_to) ONCE before drawing. It answers the whole checklist in one step — 3 storeys or more means '
    'lifts, every building has an entrance, and lift count, escape stairs, corridor width, WC count, '
    'parapet, plant and approach lighting follow from the use, the plate and the occupancy — each default '
    'already chosen with the tool call that builds it. Do NOT interview the user item by item: if the '
    'request asks to be consulted, put the whole DECIDE block into ONE ask_user. done REFUSES while a '
    'required item is missing; program_status() shows what is left and skip=[keys] waives it. '
    'Every how-line it prints is literal: run it with real cells.'
)
# 2026-09-16: the last sentence ("the core serves the ROOF DECK, not the top flat,
# and a deck needs a head house over the stair and the lift overrun beside it")
# is gone — add_core does exactly that, in one call, and the roof_access how-line
# below names it. The tower system prompt had 17 chars of slack; this paid for the
# recipe paragraph arch_assistant.tower_recipe() adds.
if len(PROMPT) > 900:
    raise RuntimeError(f'PROMPT is {len(PROMPT)} chars (max 900)')

EXAMPLES = [
    {
        'ask': 'a 20-storey glass office tower on FG150, nice entrance',
        'core': True,
        'calls': [
            {
                'tool': 'plan_building',
                'args': {'use': 'office', 'storeys': 20, 'cell_from': 'EW140', 'cell_to': 'FQ160'},
            },
            {'tool': 'draw_office_tower', 'args': {'cell_from': 'EW140', 'cell_to': 'FQ160', 'storeys': 20}},
        ],
    },
    {
        'ask': 'a block of flats, 6 storeys',
        'core': True,
        'calls': [
            {
                'tool': 'plan_building',
                'args': {'use': 'residential', 'storeys': 6, 'cell_from': 'K20', 'cell_to': 'X34'},
            }
        ],
    },
    {
        'ask': 'no parking and no balconies on it',
        'calls': [{'tool': 'program_status', 'args': {'skip': ['parking', 'balconies']}}],
    },
]
