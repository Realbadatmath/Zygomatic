# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""building_program.checklist — ITEMS — the checklist itself — and BY_KEY.

Moved verbatim from arch_assistant_ext/building_program.py lines 684-1181
(2026-10 split).
"""

from __future__ import annotations

import math
from zyg_workflows.arch_assistant_ext.building_program.evidence import (
    DOORS,
    ROOFS,
    TREES,
    _A,
    _count,
    _ev_lift,
    _ev_plant,
    _ev_roof_access,
    _ev_second_escape,
    _ev_stair,
    _groups,
    _top_storey,
)
from zyg_workflows.arch_assistant_ext.building_program.request_items import (
    _ev_balconies,
    _ev_corridor,
    _ev_deck_furniture,
    _ev_finishes,
    _ev_lobby,
    _ev_roof_pool,
    _ev_typical_floors,
    _how_typical_floors,
)


# ── the checklist ────────────────────────────────────────────────────────────
# need: 'required' | 'recommended' | 'no'.  default(ctx) -> the chosen answer,
# already decided.  options: the genuine either/or, first = the default.
# ev(d, ctx) -> (bool ok, str detail).
def _R(ctx, cond):
    return 'required' if cond else 'recommended'


# 2026-09-16: a how-line names the MACRO first. The three kit families
# (core_kit, entrance_kit, roof_kit) do in ONE clash-free call what the manual
# sequence below them took five to eight calls and a design_check full of
# clashes to do. The family is fetched lazily — families load alphabetically, so
# it is not there at import time — and when it is missing the old hand-built
# sentence is printed instead, because a checklist must never name a tool that
# does not exist.
def _macro(family: str, macro_line: str, manual_line: str) -> str:
    return macro_line if _A.EXT_MODULES.get(family) is not None else manual_line


ITEMS = [
    {
        'key': 'entrance',
        'title': 'Entrance',
        'spec': 'entrance',
        'need': lambda c: 'required',
        'why': 'every building has one place a visitor is meant to arrive at',
        'options': ['porte_cochere', 'recessed', 'glazed_lobby', 'shopfront'],
        'default': lambda c: (
            'shopfront'
            if c['use'] == 'retail'
            else 'recessed'
            if c['use'] == 'house'
            else 'porte_cochere'
            if (c['storeys'] >= 8 or c['use'] in ('hotel', 'office', 'civic'))
            else 'glazed_lobby'
        ),
        'how': lambda c: _macro(
            'entrance_kit',
            'build_entrance(group, side="south") — the door, the porte-cochère, the lobby, the reception desk, the '
            'drive and the lamps in ONE call; run it BEFORE add_curtain_wall, which keeps the door wall as glass',
            'add_opening(group, side="south", storey=0, kind="double_door") on the entrance axis'
            + (
                ', then add_canopy(group, side="south", storey=0, width>=8, depth=4..6, height=3.5..4.5, columns=4)'
                if c['pick'] == 'porte_cochere'
                else ''
            )
            + ' — both BEFORE add_curtain_wall, which keeps the door wall as glass',
        ),
        'ev': lambda d, c: (_count(d, DOORS, storey=0) > 0, f'{_count(d, DOORS, storey=0)} door(s) on storey 0'),
    },
    {
        'key': 'stair',
        'title': 'Stair',
        'spec': 'stair',
        'need': lambda c: 'required' if c['storeys'] >= 2 else 'no',
        'why': 'the way up that works with the power off, and the way out in a fire',
        'options': ['u', 'l', 'straight', 'spiral'],
        'default': lambda c: 'u' if c['storeys'] >= 4 else ('straight' if c['use'] == 'house' else 'l'),
        'how': lambda c: _macro(
            'core_kit',
            f'add_core(group, position="north", stair="{c["pick"]}", '
            f'stair_width={1.0 if c["use"] == "house" else 1.2}) — the stair, the lifts and the landing they share, '
            f'storey 0 to the deck, clash-free; it answers the Lift(s) line too',
            f'add_stair(cell=<a cell in the core>, from_storey=0, to_storey={_top_storey(c)}, '
            f'kind="{c["pick"]}", width={1.0 if c["use"] == "house" else 1.2}) — one record per '
            f'storey: it cuts the floor opening through each slab and adds the rails',
        ),
        'ev': _ev_stair,
    },
    {
        'key': 'elevator',
        'title': 'Lift(s)',
        'spec': 'elevator',
        'need': lambda c: (
            'required'
            if c['storeys'] >= 3
            else ('recommended' if c['storeys'] == 2 and c['use'] in ('office', 'hotel', 'civic', 'retail') else 'no')
        ),
        'why': 'a building of three storeys or more is not usable without one',
        'options': ['passenger', 'passenger+goods', 'goods'],
        'default': lambda c: 'passenger+goods' if c['use'] in ('hotel', 'retail', 'warehouse') else 'passenger',
        'count': lambda c: min(6, max(1, 1 + (c['storeys'] > 8) + max(0, int(c['occupants'] // 300)))),
        'how': lambda c: _macro(
            'core_kit',
            f'add_core(group, position="north", lifts={c["n"]}) — the same ONE call as the Stair line: it lays the '
            f'{c["n"]} shaft(s) out beside the stair, clear of the 1.2 m at its foot, doors to the lobby, overrun '
            f'above the top landing',
            f'add_elevator(cell=<a cell in the core, beside the stair but clear of its plan and of '
            f'the 1.2 m in front of its foot: >= 4 cells west / >= 3 cells east of the stair cell>, '
            f'from_storey=0, '
            f'to_storey={_top_storey(c)}, w=1.8, depth=2.0) x {c["n"]} — a door on every storey it '
            f'passes, and the overrun above the top landing',
        ),
        'ev': _ev_lift,
    },
    {
        'key': 'second_escape',
        'title': 'Second escape stair',
        'spec': 'fire_escape',
        'need': lambda c: _R(c, c['storeys'] >= 5 or c['area'] > 500 or c['occupants'] > 60),
        'why': 'one fire must not close both ways out',
        'options': ['protected_stair', 'external_stair'],
        'default': lambda c: 'protected_stair' if c['storeys'] >= 8 else 'external_stair',
        'how': lambda c: (
            f'add_fire_escape(group, side="north", storeys={c["storeys"]}, width=1.2) — the side '
            f'OPPOSITE the entrance (which is on the south) and OUTSIDE the facade, bolted to it; '
            f"a cell inside the plan puts the escape stair in somebody's flat. "
            f'Then egress_check(max=30)'
        ),
        'ev': _ev_second_escape,
    },
    {
        'key': 'lobby',
        'title': 'Entrance lobby',
        'spec': 'lobby',
        'need': lambda c: _R(c, c['storeys'] >= 3 and c['use'] != 'house'),
        'why': 'the door hands people to the core; without a lobby the door is the queue',
        'options': ['single_height', 'double_height'],
        'default': lambda c: (
            'double_height' if (c['storeys'] >= 10 or c.get('finish_level') == 'luxury') else 'single_height'
        ),
        'how': lambda c: _macro(
            'entrance_kit',
            'build_entrance(group, side="south") builds the lobby with the door — reception desk, seating and all, '
            'deep enough for the programme, off the lift core and never a partition on the facade line'
            + (
                ' (a luxury lobby is a room, not a corridor: it makes it at least 8 x 6 cells)'
                if c.get('finish_level') == 'luxury'
                else ''
            ),
            'add_room(cell_from, cell_to, storey=0, name="Lobby") on the entrance axis, core at its '
            'far end'
            + (
                ' — at least 8 cells across AND 6 deep: a luxury lobby is a room, not a corridor'
                if c.get('finish_level') == 'luxury'
                else ''
            )
            + ' then furnish_lobby(cell_from, cell_to, storey=0, entrance_side=<side>)',
        ),
        'ev': _ev_lobby,
    },
    {
        'key': 'corridor',
        'title': 'Corridor / circulation',
        'spec': 'corridor',
        'need': lambda c: _R(
            c, c['use'] in ('residential', 'office', 'hotel', 'school', 'civic', 'mixed') and c['area'] > 120
        ),
        'why': 'rooms reach the core along something, and its width is decided not left over',
        'options': ['1.5', '1.8', '1.2'],
        'default': lambda c: '1.8' if (c['occupants'] > 200 or c['use'] in ('school', 'hotel')) else '1.5',
        'how': lambda c: (
            f'layout_floor(cell_from, cell_to, use="{c["use"]}", corridor_w={c["pick"]}) cuts a '
            f'whole floor, or add_corridor(cell_from, cell_to, width={c["pick"]}) one at a time '
            f'(the block must be wider than the corridor, or it refuses)'
        ),
        'ev': _ev_corridor,
    },
    # A tower whose upper storeys hold nothing but slab and facade is a massing
    # model, and until 2026-09-11 nothing on the checklist asked what was on them.
    {
        'key': 'typical_floors',
        'title': 'Typical floors: a plan on every upper storey',
        'spec': 'floor_plan',
        'need': lambda c: (
            'required'
            if (c['use'] in ('residential', 'hotel', 'office', 'mixed') and c['storeys'] >= 2)
            else 'recommended'
            if c['storeys'] >= 2
            else 'no'
        ),
        'why': 'nineteen empty storeys passed the last gate — a storey with no rooms is a massing model',
        'options': ['real_plan', 'tiled_units', 'layout_floor'],
        'default': lambda c: 'real_plan' if c['use'] in ('residential', 'hotel') else 'layout_floor',
        'how': _how_typical_floors,
        'ev': _ev_typical_floors,
    },
    {
        'key': 'wc',
        'title': 'Toilets',
        'spec': 'wc',
        'need': lambda c: _R(c, c['use'] != 'house'),
        'why': 'occupancy sets the count; every floor of a public building needs an accessible one',
        'options': ['per_floor', 'ground_only'],
        'default': lambda c: 'per_floor' if c['storeys'] >= 2 else 'ground_only',
        'count': lambda c: max(1, int(math.ceil(c['occupants'] / 20.0 / max(1, c['storeys'])))),
        'how': lambda c: (
            f'add_room(..., name="WC") at the core on every floor, then furnish_bathroom(...) — '
            f'about {c["n"]} fixture(s) per floor plus one accessible cubicle 1.5 x 2.2 m'
        ),
        'ev': lambda d, c: (
            _count(d, ('toilet', 'washbasin'), words=('wc', 'toilet', 'washroom', 'restroom')) > 0,
            'toilet/washbasin records or a room named WC',
        ),
    },
    {
        'key': 'roof',
        'title': 'Roof',
        'spec': 'roof_deck',
        'need': lambda c: 'required',
        'why': 'a building without a roof record is a massing study',
        'options': ['flat', 'flat_deck', 'gable', 'hip'],
        'default': lambda c: 'gable' if c['use'] == 'house' else 'flat_deck' if c['storeys'] >= 8 else 'flat',
        # the how-line has to be the call that WORKS: add_roof takes cells and a bare
        # kind word ('flat'), not a group and not a 'roof_flat' record kind.
        'how': lambda c: (
            f'draw_box(..., storeys={c["storeys"]}, roof="{"flat" if c["pick"].startswith("flat") else c["pick"]}") '
            f'builds it with the shell, or add_roof(cell_from, cell_to, storey={c["storeys"]}, '
            f'kind="{"flat" if c["pick"].startswith("flat") else c["pick"]}") on an existing one'
            + (
                ' — then add_parapet(group, height=1.1) and put the terrace ON the deck (roof y + t)'
                if c['pick'] == 'flat_deck'
                else ''
            )
        ),
        'ev': lambda d, c: (_count(d, ROOFS) > 0, f'{_count(d, ROOFS)} roof record(s)'),
    },
    {
        'key': 'parapet',
        'title': 'Parapet / guarding',
        'spec': 'roof_deck',
        'need': lambda c: _R(c, c['storeys'] >= 2 and c['use'] != 'house'),
        'why': 'an accessible flat roof or a balcony without guarding is not buildable',
        'options': ['1.1'],
        'default': lambda c: '1.1',
        'how': lambda c: 'add_parapet(group, height=1.1) round the roof edge; guarding_check() proves it',
        # add_parapet makes plain `wall` records NAMED parapet, so match the name too
        'ev': lambda d, c: (
            _count(
                d,
                ('parapet', 'parapet_cap', 'railing', 'balcony'),
                words=('parapet', 'balustrade', 'guarding', 'railing'),
            )
            > 0,
            'parapet, balustrade or railing records',
        ),
    },
    {
        'key': 'roof_access',
        'title': 'Roof access: head house + overrun',
        'spec': 'roof_deck',
        'need': lambda c: (
            'required' if (c['pick_of'].get('roof') == 'flat_deck' or c['storeys'] >= 8) else 'recommended'
        ),
        'why': 'a roof deck nobody can reach is a picture',
        'options': ['stair+lift', 'stair'],
        'default': lambda c: 'stair+lift' if c['storeys'] >= 3 else 'stair',
        'how': lambda c: _macro(
            'core_kit',
            f'add_core(group, position) already runs to storey {c["storeys"]} — the deck — with the head house over '
            f'the stair and the lift overrun beside it; build_roof_deck(group, view) puts a door in that head house '
            f'if the stair arrives in a sealed box',
            f'add_stair(..., to_storey={c["storeys"]}) reaches the deck and builds the head house; '
            f'add_elevator(..., to_storey={c["storeys"]}) adds the overrun',
        ),
        'ev': _ev_roof_access,
    },
    # from the request only: nothing about a use or a height implies a roof pool,
    # and the one request that asked for one got a tower whose core stopped a
    # storey below it.
    {
        'key': 'roof_pool',
        'title': 'Roof pool',
        'spec': 'roof_deck',
        'need': lambda c: 'no',
        'why': 'the pool is the brief',
        'options': ['infinity', 'plain'],
        'default': lambda c: 'infinity',
        'how': lambda c: _macro(
            'roof_kit',
            'build_roof_deck(group, view="south") — ONE call: the 1.1 m guard on every deck edge first, then the '
            'infinity pool in a band along that facade, 1.5 m clear of every stair, shaft and head house, with its '
            'loungers, parasols, palms, lounge and lights, then the rooftop plant moved out of the view '
            '(explain("infinity pool") is the rule sheet)',
            f'add_infinity_pool(cell_from, cell_to, view="south", storey={c["storeys"]}) — ONE call: '
            f'deck-level water with the tank zone below, glass weir + trough on the view edge, a glass '
            f'balustrade outboard of it, steps, loungers, parasols, palms, lounge, lights, tile '
            f'(explain("infinity pool") is the rule sheet); add_pool(cell_from, cell_to, '
            f'storey={c["storeys"]}, raised="auto", infinity="south") is the bare basin — storey '
            f'{c["storeys"]} IS the deck of a {c["storeys"]}-storey box',
        ),
        'ev': _ev_roof_pool,
    },
    {
        'key': 'facade_bands',
        'title': 'Floor line on the facade',
        'spec': 'curtain_wall',
        'need': lambda c: _R(c, c['glass'] and c['storeys'] >= 4),
        'why': 'a curtain wall hides the slab edge, and the tower then reads as hollow',
        'options': ['string_course', 'spandrel'],
        'default': lambda c: 'string_course',
        'how': lambda c: (
            'add_curtain_wall(walls, storeys) then add_facade_bands(kind="string_course") per glazed storey'
        ),
        'ev': lambda d, c: (
            _count(d, ('string_course', 'cornice')) > 0 or _count(d, ('curtain_wall',)) == 0,
            'string courses present, or no curtain wall to hide a slab',
        ),
    },
    {
        'key': 'plant',
        'title': 'Rooftop plant + lift overrun',
        'spec': 'plant_room',
        'need': lambda c: _R(c, c['storeys'] >= 4),
        'why': 'a bare flat roof is the single clearest tell of a model',
        'options': ['screened', 'open'],
        'default': lambda c: 'screened',
        'how': lambda c: (
            'add_rooftop_plant(group) puts plant, tank and screen on the core side; the lift '
            f"overrun is the shaft's own, from add_elevator(..., to_storey={_top_storey(c)}) — "
            'a roof with plant but no overrun says the lifts stop below it'
        ),
        'ev': _ev_plant,
    },
    {
        'key': 'approach',
        'title': 'Approach: path, drive, lighting',
        'spec': 'lamp_post',
        'need': lambda c: 'required',
        'why': 'the entrance has to be reached, and be lit; a door onto grass reads as unfinished',
        'options': ['drive_and_path', 'path_only'],
        'default': lambda c: 'drive_and_path' if c['pick_of'].get('entrance') == 'porte_cochere' else 'path_only',
        'how': lambda c: (
            'add_road / add_object(kind="path") to the entrance, then '
            'add_street_furniture(kind="lamp_post", height=5) every 8-12 m along both edges, '
            '0.5 m outside the carriageway and clear of the canopy footprint'
        ),
        'ev': lambda d, c: (
            _count(d, ('lamp_post',), words=('lamp', 'street light', 'lighting column')) >= 2
            and _count(d, ('road', 'path', 'sidewalk', 'road_curved', 'kerb'), words=('driveway', 'footpath', 'paving'))
            > 0,
            f'{_count(d, ("lamp_post",), words=("lamp",))} lamp(s), '
            f'{_count(d, ("road", "path", "sidewalk", "road_curved", "kerb"), words=("driveway",))} '
            f'route record(s)',
        ),
    },
    {
        'key': 'bike_store',
        'title': 'Cycle store',
        'spec': 'bike_store',
        'need': lambda c: _R(c, c['use'] in ('residential', 'mixed')),
        'why': 'one space per dwelling, on the ground storey, not through the lobby carpet',
        'options': ['room', 'covered_racks'],
        'default': lambda c: 'room',
        'how': lambda c: 'add_room(..., storey=0, name="Cycle store") on the street side',
        'ev': lambda d, c: (
            bool(_groups(d, ('cycle', 'bike', 'bicycle'))) or _count(d, ('bicycle',)) > 0,
            'a cycle store room or cycle records',
        ),
    },
    {
        'key': 'refuse_store',
        'title': 'Refuse store',
        'spec': 'refuse_store',
        'need': lambda c: _R(c, c['use'] in ('residential', 'hotel', 'mixed')),
        'why': 'the bin route is a plan decision; found later it goes through the lobby',
        'options': ['room', 'enclosure'],
        'default': lambda c: 'room',
        'how': lambda c: 'add_room(..., storey=0, name="Refuse store") with a level route to the kerb, under 25 m',
        'ev': lambda d, c: (
            bool(_groups(d, ('refuse', 'bin store', 'waste'))) or _count(d, ('dumpster',)) > 0,
            'a refuse room or dumpster records',
        ),
    },
    {
        'key': 'parking',
        'title': 'Parking',
        'spec': 'parking_bay',
        'need': lambda c: _R(c, c['use'] in ('retail', 'warehouse')),
        'why': 'bays and their 6 m aisle are planned together or the aisle never fits',
        'options': ['surface', 'undercroft', 'garage'],
        'default': lambda c: 'garage' if c['gross'] > 6000 else 'surface',
        'how': lambda c: (
            'add_parking(cell_from, cell_to, aisle=6.0) or draw_parking_garage(decks=N); '
            'park_cars() fills a few bays for the render'
        ),
        'ev': lambda d, c: (
            _count(d, ('parking_bay',), words=('parking bay',)) > 0,
            f'{_count(d, ("parking_bay",), words=("parking bay",))} bay(s)',
        ),
    },
    {
        'key': 'balconies',
        'title': 'Balconies',
        'spec': 'balcony',
        'need': lambda c: _R(c, False) if c['use'] in ('residential', 'mixed') and c['storeys'] >= 2 else 'no',
        'why': 'a residential facade with no balcony reads as an office',
        'options': ['1.8', '2.2', '1.5'],
        'default': lambda c: '1.8',
        'how': lambda c: (
            f'add_balconies(walls, storeys, depth={c["pick"]}, railing=True) on the best facade — '
            f'on at least {max(1, int(c["storeys"]) // 4)} storeys, spread over '
            f'{max(1, int(c["storeys"]) // 2)} of the {int(c["storeys"])}; '
            f'"added 0 balconies, skipped 11 walls" is a refusal, not a result'
        ),
        # one balcony on a 20-storey block of flats is a token, and forty of them on
        # one storey is the same token four times over: _ev_balconies counts STOREYS.
        'ev': _ev_balconies,
    },
    {
        'key': 'reception',
        'title': 'Reception desk',
        'spec': 'reception_desk',
        'need': lambda c: _R(c, False) if c['use'] in ('office', 'hotel', 'civic') else 'no',
        'why': 'a lobby with nothing in it reads as a car park',
        'options': ['desk', 'none'],
        'default': lambda c: 'desk',
        'how': lambda c: (
            'place_asset(cell, query="reception desk", storey=0) facing the entrance, 1.5 m of queueing space in front'
        ),
        'ev': lambda d, c: (_count(d, (), words=('reception',)) > 0, 'a reception record'),
    },
    {
        'key': 'loading',
        'title': 'Loading bay',
        'spec': 'loading_bay',
        'need': lambda c: (
            _R(c, c['use'] in ('warehouse', 'retail'))
            if (c['use'] in ('warehouse', 'retail') or c['gross'] > 2000)
            else 'no'
        ),
        'why': 'a lorry must never share the arrival route',
        'options': ['bay', 'yard'],
        'default': lambda c: 'yard' if c['use'] == 'warehouse' else 'bay',
        'how': lambda c: 'a 3.5 x 12 m bay with 12 m of manoeuvring, on the opposite side from the entrance',
        'ev': lambda d, c: (
            bool(_groups(d, ('loading', 'service yard'))) or _count(d, ('truck',)) > 0,
            'a loading group or truck records',
        ),
    },
    {
        'key': 'landscape',
        'title': 'Planting clear of the axis',
        'spec': 'tree',
        'need': lambda c: _R(c, False),
        'why': 'real trees, one crown apart, 6 m off the entrance axis',
        'options': ['real', 'parametric'],
        'default': lambda c: 'real',
        'how': lambda c: (
            'plant_trees(cell_from, cell_to, count, height, model="real") — take the block the tool '
            'names if it refuses; never fall through to another tree tool'
        ),
        'ev': lambda d, c: (
            _count(d, TREES, words=('tree', 'oak', 'pine', 'fir', 'birch', 'jacaranda')) > 0,
            f'{_count(d, TREES, words=("tree", "oak", "pine", "fir"))} planting record(s)',
        ),
    },
    {
        'key': 'atrium',
        'title': 'Atrium / second daylight source',
        'spec': 'atrium',
        'need': lambda c: _R(c, False) if c['depth'] > 24 else 'no',
        'why': 'a plate deeper than 24 m has a dark middle',
        'options': ['atrium', 'lightwell'],
        'default': lambda c: 'atrium',
        'how': lambda c: 'add_atrium(cell_from, cell_to, from_storey, to_storey), at least 6 m across, guarded edges',
        'ev': lambda d, c: (bool(_groups(d, ('atrium', 'void', 'lightwell'))), 'an atrium group or zone'),
    },
    # ── what "luxurious" costs, as items ────────────────────────────────────────
    {
        'key': 'deck_furniture',
        'title': 'Deck furniture',
        'spec': 'roof_deck',
        'need': lambda c: (
            'required'
            if (c.get('finish_level') == 'luxury' and (c.get('need_of') or {}).get('roof_access') == 'required')
            else 'no'
        ),
        'why': 'an empty roof deck reads as a plant deck, whatever the pool cost',
        'options': ['loungers+parasols', 'loungers'],
        'default': lambda c: 'loungers+parasols',
        'how': lambda c: _macro(
            'roof_kit',
            'build_roof_deck(group, view) brings the loungers, parasols, palms and the fire-pit lounge with the '
            'pool — the same ONE call as the Roof pool line, nothing to place by hand',
            f'add_beach_set(cells=[four or more deck cells], storey={c["storeys"]}) — every piece '
            f'lands on the deck under it; or add_object(kind="sun_lounger", ...) one at a time',
        ),
        'ev': _ev_deck_furniture,
    },
    {
        'key': 'finishes',
        'title': 'Finishes',
        'spec': 'material',
        'need': lambda c: 'required' if c.get('finish_level') == 'luxury' else 'no',
        'why': 'a luxury request answered in mat_concrete and mat_steel is a grey massing model',
        'options': ['library', 'presets'],
        'default': lambda c: 'library',
        'how': lambda c: (
            'search_materials("marble") for the id, then set_finish(group, floor_material=<library '
            'id>, wall_material=<library id>, roof_material=<library id>), or set_material(ids, '
            '<library id>) for the rest — a flat mat_ preset is the default, not a finish'
        ),
        'ev': _ev_finishes,
    },
]
BY_KEY = {i['key']: i for i in ITEMS}
