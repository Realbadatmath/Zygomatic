# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Prompt families, the system prompt, the cell tools and the tool dispatcher.

Moved verbatim out of the old single-file arch_assistant.py (lines 2157-2477).
"""

from __future__ import annotations

import json
import re

from zyg_workflows.arch_assistant._base import _zyg_log

from zyg_workflows.arch_assistant.walls import (
    TOOL_DEFS,
    TOOL_FN,
)
from zyg_workflows.arch_assistant.ground import (
    load_extensions,
    t_help,
)

# ── prompt families (2026-09-10) ─────────────────────────────────────────────
# The prompt carried every capability family — cliffs, dunes, polders, IFC
# export, turntables — on every request, 90k chars, and the model reasoned
# about all of it before a tower. A family listed here is OPTIONAL: its prose
# and examples go in only when the request mentions one of its words, or the
# drawing already holds one of its kinds. Every family not listed is always in.
# The TOOL SCHEMAS are never trimmed — a tool stays callable whether or not its
# prose is present (help lists them all); only the reading load changes.
PROMPT_FAMILIES = {  # family -> phrases (comma-separated; a short one must match a whole word)
    'mountains': 'mountain, ridge, valley, peak, alpine, summit',
    'rivers_lakes': 'river, stream, lake, waterfall, creek, brook',
    'water_v3': 'lake, river, the sea, flood, carve',
    'cliffs_rocks': 'cliff, rock, boulder, scree, escarp, sea stack',
    'coast_dunes': 'coast, the sea, beach, dune, island, breakwater, shore, harbour, harbor',
    'fields_meadows': 'field, meadow, pasture, marsh, vineyard, polder, farmland, crop',
    'terrain': 'terrain, hill, slope, retaining, flatten, mound',
    'ground_v3': 'terrain, hill, slope, raise the ground, lower the ground, level the ground, heightfield',
    'site_terrain': 'contour, cut and fill, cut/fill, terrain',
    'landscape_composer': 'landscape, scenery, scene',
    'civil_infrastructure': 'bridge, tunnel, dam, quay, jetty, embankment, harbour, harbor, viaduct',
    'vehicles_props': 'car, cars, vehicle, truck, bus, scaffold, construction, crane, lorry, van',
    'mep_services': 'solar, chimney, gutter, downpipe, radiator, pipe, duct, hvac',
    'furniture_kitchen_bath': 'kitchen, bathroom, utility, furnish',
    'furniture_living': 'furnish, furniture, sofa, bed, table, chair, interior',
    'interior_rooms': 'room, corridor, interior, ceiling, floor finish, skirting, subdivide, partition',
    'floor_layouts': 'layout, floor plan, apartment plan, repeat floor, typical floor, storey, storeys, stories, tower, residential, office, hotel, flats',
    'floor_plans': 'floor plan, floorplan, apartment, apartments, unit, units, layout, interior, rooms, house plan, tile, storey, storeys, stories, tower, residential, office, hotel, flats',
    'site_context': 'site boundary, site plan, plot, setback, geolocation, latitude, aerial, satellite, '
    'osm, site trees, street trees',
    'water_leisure': 'pool, pond, canal, fountain, playground, beach, lounger, parasol, tennis, basketball, '
    'football, sports court, swimming',
    'file_2d': 'export, ifc, dxf, dwg, svg',
    'file_3d': 'export, glb, obj, fbx, import, mesh, link drawing',
    'file_manage_setup': 'template, version, restore, snapshot',
    'drawings_2d': 'plan drawing, section, elevation, 2d, sheet',
    'drawings_sheet': 'sheet, title block, revision, pdf',
    'share_collab': 'share, issue, markup, compare, comment',
    'quantities': 'quantit, cost, rate, price, m2, bill of',
    'render_offline': 'ray trace, raytrace, path trace, still',
    'render_post': 'post-process, grade, tone map, exposure, bloom',
    'light_lamps_env': 'ies, hdri, light fixture, spotlight',
    'light_studies': 'sun hours, daylight, shadow study, solar study',
    'light_sun': 'sun position, sun model, time of day, shadow',
    'analyse_geometry': 'clash, headroom, guarding, stair check',
    'analyse_performance': 'daylight, energy, u-value, u value, structure check, code check',
    'analyse_planning': 'egress, accessib, occupancy, fire compartment, wheelchair',
    'measure_annotations': 'dimension, annot, label, angle',
    'organise_layers': 'layer, tag, selection set',
    'organise_model': 'component, zone, grid line, add storeys',
    'precision_input': 'precise, snap, type-in, numeric',
    'precision_snaps': 'snap',
    'display_helpers': 'bbox, bounding box, display, show, hide, ground plane',
    'display_styles': 'display style, wireframe, texture, edges',
    'view_camera': 'camera, orbit, turntable, walk, fly, animation, two-point',
    'edit_ops': 'align, distribute',
    'modify_ops': 'offset, fillet, sweep, profile',
    'solids_boolean': 'boolean, subtract, hole, cut',
    'draw_guides': 'guide arc, guide polygon, guide path',
    'landmarks_special': 'landmark, monument, statue, eiffel, pyramid, famous',
    'curved_walls': 'curved, curve, arc, round, circular, cylinder',
    'polygon_footprints': 'polygon, l-shape, l shaped, atrium, hexagon, octagon, irregular',
    'massing_morph': 'massing, morph, stack storeys, taper',
    'typologies_commercial': 'office, warehouse, shop, school, church, parking, garage',
    'typologies_residential': 'house, villa, farm, flats, apartment, row house, bungalow',
    'structure_frames': 'column grid, colonnade, beam, portal, pergola, bracing, frame, truss',
    'roofs_advanced': 'skylight, mansard, gambrel, butterfly, sawtooth, vault, dome',
    'v3probe': '',
    'icon_probe': '',
}
_PHRASE_STRIP = (
    'ground floor',
    'ground level',
    'at ground',
    'on the ground',
    'floor plan',
)  # words that name a storey, not the terrain
LAST_PROMPT_INFO: dict = {}


def prompt_families(request: str = '', d=None) -> tuple:
    """(kept, dropped): extension module names whose prose goes into the prompt
    for this request. Always-in families are those not in PROMPT_FAMILIES."""
    txt = ' ' + str(request or '').lower() + ' '
    for ph in _PHRASE_STRIP:
        txt = txt.replace(ph, ' ')
    kinds = {o.get('kind') for o in (getattr(d, 'objs', None) or [])}
    everything = not str(request or '').strip() and d is None  # the bare call (probes, docs): the whole prompt
    kept, dropped = [], []

    def hit_word(w: str) -> bool:  # a stem may run on ("quantit"); a short word may not ("sea")
        tail = r'\b' if len(w) <= 4 else ''
        return re.search(r'\b' + re.escape(w) + tail, txt) is not None

    for name, mod in EXT_MODULES.items():
        words = PROMPT_FAMILIES.get(name)
        if words is None or everything:
            kept.append(name)
            continue
        hit = any(hit_word(w.strip()) for w in words.split(',') if w.strip()) if words else False
        if not hit and kinds:
            hit = bool(kinds & set((getattr(mod, 'KINDS', {}) or {}).keys()))
        (kept if hit else dropped).append(name)
    return kept, dropped


# 2026-09-16: THE RECIPE. The manual sentences this replaces ("add_opening then
# add_canopy then add_room then furnish_lobby", "add_stair + add_elevator",
# "add_parapet + add_infinity_pool + add_rooftop_plant") cost the model about 20
# drawing calls and a design_check full of clashes; the three kits do the same
# work in three calls, clash-free. So the recipe names the MACRO first and only
# falls back to the hand-built sequence when that family is not loaded — the
# prompt must never name a tool that does not exist.
def tower_recipe() -> str:
    def step(family: str, macro: str, manual: str) -> str:
        return macro if EXT_MODULES.get(family) is not None else manual

    core = step('core_kit', 'add_core(group, position)', 'add_stair + add_elevator')
    ent = step(
        'entrance_kit',
        'build_entrance(group, side)',
        'add_opening(kind="double_door") + add_canopy + add_room("Lobby") + furnish_lobby',
    )
    roof = step('roof_kit', 'build_roof_deck(group, view)', 'add_parapet + add_infinity_pool + add_rooftop_plant')
    steps = [
        'plan_building',
        'draw_box',
        'add_curtain_wall(storeys=[0,2,4,…])',
        'add_facade_bands',
        core,
        ent,
        'layout_floor(core_from/core_to from ' + core.split('(')[0] + "'s reply)",
        'repeat_floor',
        roof,
        'add_balconies(sides=["east","west"], per_wall=2)',
        'present',
        'done',
    ]
    # What each macro contains is in its tool description, which is never trimmed;
    # the recipe is only the ORDER and the hand-off between the calls.
    return (
        'A WHOLE TOWER IS 12 DRAWING CALLS, in this order: ' + ' -> '.join(steps) + '. Use the macro, never its parts.'
    )


def system_prompt(storey_h: float, request: str = '', d=None) -> str:
    base = SYSTEM.replace('{storey_h}', f'{storey_h:g}').replace('{max_calls}', str(MAX_CALLS))
    parts = [base, tower_recipe()]
    kept, dropped = prompt_families(request, d)
    keep = set(kept)
    prompts, examples = [], []
    for name, mod in EXT_MODULES.items():
        if name not in keep:
            continue
        pr = str(getattr(mod, 'PROMPT', '') or '').strip()
        if pr and pr not in prompts:
            prompts.append(pr)
        examples.extend(getattr(mod, 'EXAMPLES', []) or [])
    if prompts:
        parts.append('CAPABILITIES (extensions):\n' + '\n'.join('- ' + p for p in prompts))
    if dropped:
        parts.append(
            'More families exist (' + ', '.join(sorted(dropped)) + ') — their tools are all callable; '
            'help("<word>") lists them.'
        )
    if EXT_KINDS:
        parts.append('EXTRA KINDS for add_object: ' + ', '.join(sorted(EXT_KINDS)))
    if examples:
        ex = []
        core = [e for e in examples if e.get('core')]
        rest = [e for e in examples if not e.get('core')]
        for e in (core + rest)[:40]:
            calls = '; '.join(
                f'{c.get("tool")}({json.dumps(c.get("args") or {}, ensure_ascii=False)})' for c in e.get('calls') or []
            )
            ex.append(f'- "{e.get("ask")}" -> {calls}')
        parts.append('WORKED EXAMPLES (request -> tool calls):\n' + '\n'.join(ex))
    out = '\n\n'.join(parts)
    LAST_PROMPT_INFO.update({'kept': kept, 'dropped': dropped, 'chars': len(out)})
    return out


TOOL_FN['help'] = t_help


def t_block_around(d: Drawing, a, centre, width, depth=None):
    cf, ct = block_around(centre, width, depth)
    c, r = parse_cell(centre)
    c0, r0 = parse_cell(cf)
    c1, r1 = parse_cell(ct)
    return (
        f'{cf}..{ct}: {c1 - c0 + 1} x {r1 - r0 + 1} cells (columns {c0 + 1}..{c1 + 1}, rows {r0 + 1}..{r1 + 1}) '
        f'around {cell_name(c, r)} (column {c + 1}, row {r + 1}). Pass these as cell_from / cell_to, or give '
        f'draw_box the centre + width + depth directly'
    )


def t_cell_offset(d: Drawing, a, cell, east=0, south=0):
    c, r = parse_cell(cell)
    out = cell_offset(cell, east, south)
    return f'{out} is {int(_num(east, 0)):+d} columns (east) and {int(_num(south, 0)):+d} rows (south) from {cell_name(c, r)}'


TOOL_DEFS.append(
    {
        'name': 'block_around',
        'description': 'The corner cells of a width x depth block centred on a cell — "20 x 20 centred on FH100" -> EX90..FQ109. Use this (or draw_box centre + width + depth) instead of converting column letters to numbers yourself.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'centre': {'type': 'string'},
                'width': {'type': 'integer'},
                'depth': {'type': 'integer', 'description': 'default: width'},
            },
            'required': ['centre', 'width'],
        },
    }
)
TOOL_DEFS.append(
    {
        'name': 'cell_offset',
        'description': 'The cell N columns east (+X, negative = west) and M rows south (+Z, negative = north) of a cell — "6 m west of FH112" -> cell_offset("FH112", -6, 0) = FB112. Never count column letters in your head.',
        'input_schema': {
            'type': 'object',
            'properties': {'cell': {'type': 'string'}, 'east': {'type': 'integer'}, 'south': {'type': 'integer'}},
            'required': ['cell'],
        },
    }
)
TOOL_FN['block_around'] = t_block_around
TOOL_FN['cell_offset'] = t_cell_offset
load_extensions()


def _relax_material_enums():
    """2026-09-07: every `material` property carried enum=MATERIALS (the 21
    presets). The library ids are valid too now, and a 1,500-entry enum would
    bloat every request, so the enum goes and a description says both."""
    for t in TOOL_DEFS:
        props = (t.get('input_schema') or {}).get('properties') or {}
        for _k, pr in props.items():
            if isinstance(pr, dict) and pr.get('enum') is not None and list(pr['enum']) == list(MATERIALS):
                pr.pop('enum', None)
                pr['type'] = 'string'
                pr['description'] = (
                    (pr.get('description') or '')
                    + (' ' if pr.get('description') else '')
                    + 'a preset ('
                    + ', '.join(MATERIALS[:8])
                    + ' ...) or a library material id from search_materials (acg_..., pht_...)'
                )


_relax_material_enums()


def _coerce_args(name: str, args: dict) -> dict:
    """2026-09-07: Sonnet handed `storeys="[1, 3, 5]"` and `walls='["o319", ...]'`
    to add_curtain_wall — JSON lists serialised as STRINGS, because those two
    properties carry no `type` in their schema. The tool then matched nothing and
    "refused" five times in a row. So: a string that parses as a JSON list/object
    becomes one (no real group name starts with "[" or "{"), and for properties
    typed number / integer / boolean a numeric or true/false string is converted."""
    if not isinstance(args, dict):
        return {}
    props = {}
    for t in TOOL_DEFS:
        if t['name'] == name:
            props = (t.get('input_schema') or {}).get('properties') or {}
            break
    out = {}
    for k, v in args.items():
        if isinstance(v, str):
            s = v.strip()
            typ = (props.get(k) or {}).get('type')
            types = typ if isinstance(typ, list) else ([typ] if typ else [])
            if s[:1] in '[{' and s[-1:] in ']}' and (not types or 'array' in types or 'object' in types):
                try:
                    v = json.loads(s)
                except ValueError as _exc:
                    _zyg_log.debug('tool arg %s is not JSON, keeping the string: %s', k, _exc)
            elif types and 'string' not in types:
                if 'boolean' in types and s.lower() in ('true', 'false'):
                    v = s.lower() == 'true'
                elif 'integer' in types or 'number' in types:
                    try:
                        v = int(s) if re.fullmatch(r'-?\d+', s) else float(s)
                    except ValueError as _exc:
                        _zyg_log.debug('tool arg %s is not numeric, keeping the string: %s', k, _exc)
        out[k] = v
    return out


def call_tool(d: Drawing, name: str, args: dict) -> str:
    fn = TOOL_FN.get(name)
    if not fn:
        return f'unknown tool {name}'
    args = _coerce_args(name, args)
    with _Scale(getattr(d, 'cell_m', CELL_M)):
        try:
            return fn(d, args, **{k: v for k, v in (args or {}).items()})
        except TypeError as e:
            return f'bad arguments for {name}: {e}'
        except ValueError as e:
            return f'refused: {e}'


SYSTEM = """You are the drawing assistant inside Architecture Studio, a parametric 3D drawing board. You build what the user asks by calling tools; the result is injected into their viewport as one undoable step.

THE GRID. The ground is a 300 x 300 grid of 1-metre cells. Columns are letters A..KN left to right (+X), rows are numbers 1..300 top to bottom in the plan view (+Z). A cell is named like C4 or AB12; users often type it in lower case ("ex146" is EX146, column EX row 146 — never E146). When the user presses Shift+R the labels are painted on every cell of a 150 x 150 field around their view, so cells they name are exact places — use them exactly. A block "from C4 to L13" is inclusive: 10 x 10 cells = 10 x 10 metres. The cell size belongs to the drawing: for a landscape at real scale call set_grid_scale(5) or (10) FIRST on an empty drawing; every cell and size after that is in metres as before, but the field is then 1500 m or 3000 m across.

HEIGHT. Height is counted in STOREYS, one storey = {storey_h} m (the wall height). A "square" is a horizontal unit; if the user gives a height in squares or in a unit that could mean storeys OR metres, call ask_user ONCE before drawing ("100 squares high — 100 storeys of 2.7 m, or 100 metres = 37 storeys?"). If the meaning is clear (e.g. "10 floors", "3 storeys", "30 m tall") do not ask. Once the user has answered, do not ask again in later requests about the same building. Storey 0 is the GROUND under the footprint, not y = 0: draw_box, draw_wall, add_slab, add_roof and add_object find it themselves, and level the ground under the footprint first (a sculpt_flat + a pad) when it is more than 0.3 m out of level, so a building on a hillside neither floats nor sinks. Pass base_height only to overrule that with a height in metres.

HOW TO BUILD. For a rectangular building use draw_box (walls + slabs per storey, optional roof). Give it centre + width + depth in cells — "20 x 20 centred on FH100" is draw_box(centre="FH100", width=20, depth=20, storeys=20, roof="flat", material=<solid>) — or the two corner cells. NEVER convert column letters to numbers yourself: block_around and cell_offset do that, and every footprint tool takes centre + width + depth. ALTERNATING FACADES ("ground floor glass, next floor concrete, repeat"; "every 2 floors glass") are ONE call: draw the whole box in the solid material, then add_curtain_wall(walls=<group>, storeys=[0, 2, 4, …]) for the glass storeys — there is no per-storey material, no per-storey draw_box and no Blender script for this. "Glass windows every 2 floors" on a solid facade = add_windows with every_n_storeys=2, material=mat_glass. Windows go on walls, so draw walls first. Storey 0 is the ground floor. Keep object counts sane: a 100-storey box is already 500 objects; do not add per-storey extras nobody asked for.

WORK FROM RESULTS — DO NOT PRE-PLAN. The budget is generous: a request has {max_calls} DRAWING calls (reads, checks, spec/explain, renders and the repair tools — set_material, set_finish, apply_finishes, move, rotate, delete, cut_floor_opening — are all free, so fixing what design_check reports costs nothing), several tool calls in one turn count as ONE turn, and unfinished work simply continues in the user's next message. So think for a sentence, make the first call (plan_building, then draw_box), and plan the rest from what comes back: draw_box's reply names the group, the wall ids per side and the roof deck; every placing tool says where it landed; a refusal says what to change. Never work out in your head what a tool will return, which id a wall has, what height a deck is, or where a column letter falls — call and read. Do not write Blender scripts for anything a drawing tool does.

RULES. Draw only what was asked; never delete or restyle existing objects unless told to. Use get_state when you need to know what exists (the summary is already in the message). Use look when the result is worth checking, at most twice per request. The screenshot shows what the user is looking at — orientation, selection, roughly where things are — but the tool results are the truth about positions; do not count from pixels. Carry the user's material words into the material argument (brick → mat_brick, glass → mat_glass, timber/wood → mat_timber, steel → mat_steel, concrete → mat_concrete, stone → mat_stone, plaster/white → mat_plaster). Compass words: north = the -Z side (up in the top view), south = +Z, east = +X, west = -X; an arc 'facing south' spans 180°..360°. ALWAYS end by calling done(summary) — a short plain summary of what, where, how many; never end with a question or a chat message (questions go through ask_user, and only before drawing). Write the summary and any question in the same language the request was written in — an English request gets an English answer. Be brief; you are not writing a report.

DESIGN RULES (design_check enforces them; done refuses while they fail). 1. FLOORS: every storey has its slab; a glass storey shows its edge (add_facade_bands). 2. DECKS: a slab or flat roof is solid, the deck is its TOP — leave base_height OUT, or pass storey=<top storey>. 3. WATER SHOWS: a roof pool is raised, or sunk=true in a plant storey. 4. A COLUMN CARRIES WHAT IT MEETS: as tall as its soffit. explain("design rules") is the sheet."""


# Imported here, at the foot of the module, because these names are used only inside
# function bodies and their modules import this one back: by this line every name
# above is already bound, so the call-time cycle resolves either way round.
from zyg_workflows.arch_assistant.config import (  # noqa: E402
    CELL_M,
    MATERIALS,
    MAX_CALLS,
    _Scale,
    _num,
    block_around,
    cell_name,
    cell_offset,
    parse_cell,
)
from zyg_workflows.arch_assistant.drawing import Drawing  # noqa: E402
from zyg_workflows.arch_assistant.ground import (  # noqa: E402
    EXT_KINDS,
    EXT_MODULES,
)
