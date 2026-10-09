# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Architecture builds (arch). 2026-09-30.

The question the sheet asks: "Can the architecture assistant produce a correct building
unattended?" The sheet's own note says why only `unattended` ever carried a number — the
Analytics card counts builds by outcome, and nothing else in the step was measured. `correct`
was never a number because nobody had written down what correct means, mechanically, on a
drawing. This is that writing-down.

The shape of the test. SIX fixed briefs (verbatim below) are posted to the drawing assistant's
own HTTP surface, one job each, and nothing is answered afterwards: a build that asks a question
has failed `unattended`. What comes back is a drawing JSON, a .blend and a .glb. Every
correctness column is then measured on those files — by the studio's OWN design gates
(`arch_assistant.design_findings` -> `design_rules.run_checks`, the check that exists because on
2026-09-07 the assistant put a rooftop pool's water 0.4 m inside the roof slab and called the
render "really nice"), by `walk_rules` reachability, by a bpy measurement script, and by
`era_gate.py` for the period. Only where no detector exists (does the church READ as a church)
is the call an operator's, blind.

Four rows, and they are four different things, which is why most of the exemptions here are
per row and not per column:
  arch_assistant  the drawing assistant — `claude -p --model sonnet` on the operator LOGIN,
                  tools through arch_mcp_shim.py. It plans and draws; it alone can be asked
                  whether a brief was followed.
  blender_build   arch_blender_build.py, headless Blender 4.3, drawing JSON -> .blend/.glb. It
                  authors nothing; it can only be faithful, so it is measured on fidelity
                  (metres, ground seam, openings, roof, materials, export) and is `na` on every
                  column that asks about a design decision.
  ext_families    the 91 live families under arch_assistant_ext/ (the ~190-tool dock). A family
                  is a CAPABILITY, so the scope columns — landscape, interior, floor plans,
                  drawings, exports, reference models — are measured here and nowhere else.
  gates           the design gates themselves. Their column is `gates_arch`: three defects are
                  planted in a finished drawing and the gates must NAME each of them. A gate
                  that catches nothing is the most expensive thing in the step.

What is blocked and why. NOTHING in this module runs Opus. The assistant refuses Opus/Fable by
name (`arch_assistant.CHEAP_MODEL`, `EXPENSIVE`) and the standing rule is Sonnet on the CLI; the
only Opus exception on record is the headless drawing contest of 2026-09-17, which is not this
test. `model_rule` therefore checks the transcript for `--model sonnet` and for the ABSENCE of
opus, rather than trusting the config. The assistant module must never be imported by a test: it
starts threads, holds JOBS and talks to the studio, so the runner drives it as a SUBPROCESS only
and asserts `GET /assistant/active` reports `running == 0` before and after each job.

The five fixture briefs' expected outputs do not exist yet; each is declared with the exact
command that makes it. The Witsen 1671 pinas reference IS on disk and measured
(data/architecture/reference/2694b5765e77 — 37.94 x 9.485 x 3.794 m), so `reference_model` is a
real comparison and not an assertion.
"""

from __future__ import annotations

# ── check kinds this step needs and the runner does not have yet ─────────────────────
# Named for what is measured, against what, with the threshold field names spelled out.
CHECK_KINDS = {
    'assistant_active_zero': 'GET {base}/assistant/active reports running == 0 both immediately before the job is '
    'posted and after it reports finished; a non-zero count is an orphan job and fails',
    'transcript_tool_calls': 'count of tool calls in the assistant job transcript whose tool name == `tool`; passes '
    'when the count == `count`, or when `min` <= count <= `max` if those are given instead',
    'gates_pass': 'arch_assistant.design_findings(drawing) on the saved drawing JSON yields <= `max_errors` '
    'findings of sev "error" and <= `max_warns` of sev "warn"; the finding codes are recorded',
    'gates_name_planted': 'every entry of `planted` (each {id, codes}) is matched by at least one design finding '
    "whose `code` is in that entry's codes list; passes only when ALL are named",
    'graph_connected': 'walk_rules reachability on the drawing: from the entrance door cell, every `zone` record '
    'centre must be reachable across the `wide` (>= 1.0 m) width grid; passes when the count '
    'of unreachable zones <= `max_unreachable`',
    'structure_supported': 'a bpy script (fixture scripts/arch_structure_probe.py) measures every wall / column / '
    'partition record: its base z is within `base_tol_m` of the ground or slab top directly '
    'below it, and every slab or flat roof is carried at >= `min_supports` distinct bearing '
    'points; passes when violations == 0',
    'opening_dims_m': 'every door record has clear height within `door_h` = (min, max) metres and every window '
    "record's plan footprint lies inside a wall / curtain_wall footprint (not free in air) "
    'with its sill at or above `sill_min_m`; passes when violations == 0',
    'roof_geometry_ok': 'on every gable / hip / shed roof record the ridge z exceeds the eaves z by >= '
    '`min_rise_m`, and the roof shell leaves no gap wider than `max_gap_m` to the wall heads '
    'it covers (measured in the .blend by ray casts on a `grid_m` lattice)',
    'ground_seam_gap_max': 'for every wall / slab / column base, the signed vertical distance to '
    'arch_assistant.ground_height at its footprint corners is <= `max_float_m` above the '
    'ground and <= `max_sink_m` below it; passes when violations == 0',
    'era_gate_pass': "era_gate.py run on each named render for the brief's stated year returns no anachronism "
    'finding at or above severity `min_sev`; the findings are recorded verbatim',
    'brief_facts_landed': 'each entry of `facts` ({id, rule}) is a mechanical measurement on the saved drawing '
    '(record count by kind, storey count, roof kind present, bbox span in metres); passes '
    'when the number landed >= `min_landed` of len(facts)',
    'export_parses_as': 'the exported file parses with the strict reader for `format` — ifc: ifcopenshell.open; '
    'dxf: ezdxf.readfile; stl: trimesh.load with a non-empty watertight-or-not mesh; glb: '
    'pygltflib.GLTF2().load — and the reader reports >= `min_objects` objects / entities',
    'plan_rooms_match': 'the 2D plan artefact (DXF layers, or PNG + its sidecar JSON) names the same rooms as the '
    "drawing's `zone` records; passes when the symmetric difference of the name sets is "
    '<= `max_diff`',
}

BASE = 'http://127.0.0.1:8899/inspect/api/architecture'
PREFIX = BASE + '/assistant'

HARNESS = {
    'subprocess_only': (
        'arch_assistant.py is NEVER imported by the test (feedback_no_import_arch_assistant): it '
        'starts threads, owns JOBS and talks to the studio. The runner POSTs to '
        + PREFIX
        + '/start, polls /job, and reads the finished drawing off disk.'
    ),
    'model': (
        'the CLI backend, `claude -p --model sonnet` on the operator LOGIN through '
        'arch_assistant._cli_cmd + arch_mcp_shim.py. NEVER Opus (feedback_arch_assistant_no_opus): '
        'arch_assistant.CHEAP_MODEL / EXPENSIVE refuse opus, fable and mythos by name. The one Opus '
        'exception on record is the headless drawing contest of 2026-09-17, which is not this test.'
    ),
    'no_autoselect': (
        'ZYG_ARCH_BACKEND=cli — the "auto" backend must NOT be used '
        '(feedback_arch_no_autoselect): auto picks local Ollama or Haiku by free VRAM, so two '
        'runs of the same brief would not be the same test.'
    ),
    'viewport_labels': 'labels OFF in every render and every posted viewport shot (feedback_arch_labels_off).',
    'no_answers': (
        'the job is posted ONCE with no session id and is never answered. A job that parks in '
        '`need_client` for a `look` is served the SAME fixed viewport shot; a job that calls '
        'ask_user is left unanswered until it times out — that is the `unattended` measurement.'
    ),
    'active_guard': 'GET ' + PREFIX + '/active must report running == 0 before the job is posted and after it ends.',
    'fresh_drawing': (
        'each brief starts from a factory-empty drawing on a fresh project id; cell_m = 1.0, '
        'STOREY_M from the catalogue (2.7 m), MAX_OBJECTS 8000, MAX_CALLS as shipped (36).'
    ),
    'blend': (
        '`blender -b --python arch_blender_build.py -- --in DRAWING.json --out OUT.blend --glb OUT.glb`; '
        "Blender 4.3, the frame conversion in that module's docstring (blender x,y,z = studio x,-z,y)."
    ),
    'transcript': (
        "the job's own conversation log (" + PREFIX + '/log) plus the CLI stream-json stdout are kept '
        "as the transcript; every check reads that or the files, never the assistant's own summary."
    ),
    'repeats': 1,
    'wall_clock_min': 45,
}

COND = {
    'repeats': 1,
    'temperature': None,
    'seed': None,
    'backend': 'cli',
    'model': 'sonnet',
    'max_calls': 36,
    'wall_clock_min': 45,
    'answers_allowed': 0,
}


# ── the twelve checkable facts every brief carries ──────────────────────────────────
# Each is a mechanical measurement on the saved drawing; `brief_follow` counts how many landed.
def _facts(rooms, storeys, roof_kind, span_x, span_z, extras):
    return [
        {'id': 'rooms', 'rule': f'>= {rooms} `zone` records'},
        {'id': 'storeys', 'rule': f'storeys present == {storeys} (distinct slab/floor y levels)'},
        {'id': 'roof_kind', 'rule': f'at least one record of kind {roof_kind!r}'},
        {'id': 'span_x', 'rule': f'plan bbox x within {span_x[0]}-{span_x[1]} m'},
        {'id': 'span_z', 'rule': f'plan bbox z within {span_z[0]}-{span_z[1]} m'},
        {'id': 'entrance', 'rule': 'exactly one door record flagged entrance (or the programme names one)'},
        {'id': 'windows', 'rule': 'window records >= 1 per habitable zone'},
        {'id': 'programme', 'rule': "d.ext['building_program'] exists with no REQUIRED item missing"},
    ] + list(extras)


# ── the six briefs, verbatim ────────────────────────────────────────────────────────
BRIEFS = {
    'b1_farmhouse': (
        'Build a Dutch farmhouse of 1671 on cells H20 to R34. Two storeys, ground floor 2.7 m, '
        'first floor 2.4 m. A steep thatched gable roof with a 55 degree pitch and its ridge running '
        'east-west. Brick walls 0.24 m thick with a timber frame inside. Six rooms on the ground floor: '
        'a hall, a kitchen with a hearth on the north wall, a dairy, a byre, a store and a stair hall. '
        'Four rooms on the first floor. One front door on the south elevation, two metres wide, and '
        'twelve windows with timber shutters. The building stands on flat ground with a gravel yard '
        'five metres deep in front of the door. Build it, then stop.'
    ),
    'b2_quay_warehouse': (
        'Build an Amsterdam quay warehouse of 1671 on cells C40 to J52, standing with its gable to '
        'the water on the west side. Five storeys of 2.6 m each under a stepped brick gable, with a '
        'hoisting beam projecting from the gable apex at the top storey. Brick throughout, no glass '
        'curtain walling, no concrete. One double loading door per storey on the west elevation, all '
        'on the same vertical line, each 1.8 m wide and 2.1 m high. Two windows per storey on the '
        'north and south elevations. A stone quay edge one metre above the water, and water west of it. '
        'Timber floors carried on beams spanning north-south. Build it, then stop.'
    ),
    'b3_church': (
        'Build a small brick hall church on cells M60 to V78. One nave 12 m wide and 30 m long with a '
        'gable roof at 45 degrees, a square west tower 6 m by 6 m rising 22 m with a pyramid roof, '
        'and a lower chancel 8 m by 8 m at the east end. Inside the nave: two rows of eight benches '
        'either side of a central aisle 2 m wide, a pulpit against the north wall two thirds along, '
        'and a stone floor. Six tall windows per side wall of the nave, each 1.2 m wide and 4 m high '
        'with their sills at 3 m. One west door under the tower, 1.6 m wide and 2.6 m high. Build the '
        'interior as well as the shell, then stop.'
    ),
    'b4_tower': (
        'Build an eighteen-storey residential tower on cells EW140 to FH152. Storey height 3.0 m. A '
        'reinforced concrete frame with a central core holding two lifts and one scissor stair, both '
        'reaching the top storey. Six flats per typical floor, each with its own front door off a '
        'corridor at least 1.5 m wide that runs the full length of the floor and connects every flat '
        'door to the core. A double-height lobby at the ground floor with a reception desk, and a '
        'canopy over the entrance with its soffit at 3.2 m. Glass on the two long elevations, '
        'precast concrete on the two short ones. A flat roof with a parapet 1.1 m high. Build it, '
        'then stop.'
    ),
    'b5_pinas_hull': (
        'A reference model of a Dutch pinas of 1671 after Nicolaes Witsen is already in the reference '
        'library. Look at its plans and its photographs, then build the HULL of that ship as a '
        'reference asset: keel, stem, sternpost, frames, planking and one deck, at the real size the '
        'library records for it. Save it as a reference asset and render it over its own plans. Do '
        'not place it in any drawing. Then stop.'
    ),
    'b6_infinity_villa': (
        'Build a modern villa with an infinity pool on cells P100 to AB116, on ground that falls away '
        'to the south. Two storeys, 3.2 m each, flat roofs. The pool is 12 m by 4 m on the south '
        'terrace at the upper level, its water surface level with the terrace deck and its far edge '
        'overflowing to a catch basin one metre below. The terrace is guarded everywhere a person can '
        "fall more than one metre, except at the pool's overflow edge. Glass sliding doors along the "
        'whole south elevation of the living room. Five planted trees on the site, none closer than '
        'eight metres to another and none on the axis of the front door. Stone paving on the terrace, '
        'timber decking beside the pool. Build it, then stop.'
    ),
}

# The four core checks every brief is scored on, in the order the runner should apply them.
_CORE = [
    {'check': 'assistant_active_zero'},
    {'check': 'file_exists', 'path': 'OUT/drawing.json', 'note': 'the finished drawing'},
    {'check': 'file_exists', 'path': 'OUT/build.blend'},
    {'check': 'file_exists', 'path': 'OUT/build.glb'},
    {
        'check': 'transcript_absent',
        'pattern': r'"tool":\s*"ask_user"',
        'note': 'a build that asks a question is not unattended',
    },
    {'check': 'transcript_contains', 'pattern': r'--model\s+sonnet'},
    {'check': 'transcript_absent', 'pattern': r'(?i)\b(opus|fable|mythos)\b'},
    {
        'check': 'transcript_tool_calls',
        'tool': 'plan_building',
        'count': 1,
        'note': 'the checklist rule: the whole programme is resolved in ONE call (building_program.py)',
    },
    {
        'check': 'gates_pass',
        'max_errors': 0,
        'max_warns': 3,
        'note': 'arch_assistant.design_findings — done already refuses while errors remain, so an error here '
        'means the build was abandoned rather than finished',
    },
    {'check': 'structure_supported', 'base_tol_m': 0.02, 'min_supports': 3},
    {'check': 'opening_dims_m', 'door_h': (1.9, 2.2), 'sill_min_m': 0.4},
    {'check': 'graph_connected', 'max_unreachable': 0},
    {'check': 'roof_geometry_ok', 'min_rise_m': 0.5, 'max_gap_m': 0.05, 'grid_m': 0.25},
    {'check': 'ground_seam_gap_max', 'max_float_m': 0.02, 'max_sink_m': 0.05},
    {
        'check': 'material_names_present',
        'terms': ['mat_'],
        'note': 'every record carries a finish, not the fallback grey',
    },
]

_CORE_FEEDS = [
    'unattended',
    'correct',
    'one_call',
    'model_rule',
    'brief_follow',
    'scale_arch',
    'structure_arch',
    'openings',
    'circulation',
    'roof',
    'ground_seam',
    'materials_arch',
]


def _brief(bid, title, feeds, facts, extra_checks, span, **kw):
    p = {
        'id': bid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {
            'prompt': BRIEFS[bid],
            'task': BRIEFS[bid],
            'endpoint': PREFIX + '/start',
            'body': {'text': BRIEFS[bid], 'backend': 'cli', 'labels': False},
        },
        'conditions': dict(COND),
        'checks': list(_CORE)
        + [
            {
                'check': 'bbox_dims_m',
                'dims': span,
                'tol_m': 1.0,
                'note': 'the brief gives the cells and the storey heights, so the metres are checkable',
            },
            {'check': 'brief_facts_landed', 'facts': facts, 'min_landed': 10},
        ]
        + list(extra_checks),
        'grade': 'measured',
    }
    p.update(kw)
    return p


PROBES = [
    _brief(
        'b1_farmhouse',
        'B1 — a 1671 Dutch farmhouse, two storeys, thatched gable',
        _CORE_FEEDS,
        _facts(
            6,
            2,
            'roof_gable',
            (10, 12),
            (14, 16),
            [
                {'id': 'pitch', 'rule': 'gable roof pitch within 50-60 degrees'},
                {'id': 'wall_t', 'rule': 'wall thickness 0.24 m +- 0.02'},
                {'id': 'yard', 'rule': 'a gravel pad >= 4 m deep in front of the entrance'},
                {'id': 'hearth', 'rule': 'a hearth or fireplace record on the kitchen north wall'},
            ],
        ),
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this render read as a seventeenth-century Dutch farmhouse rather than a modern '
                'house with a steep roof? Answer yes or no.',
            }
        ],
        (11.0, 15.0, 8.0),
        state_note='the twelve-fact count is brief_follow; the gates are correct; the bpy measurements are '
        'scale_arch / structure_arch / openings / roof / ground_seam; walk_rules is circulation',
    ),
    _brief(
        'b2_quay_warehouse',
        'B2 — an Amsterdam quay warehouse of 1671, gable to the water',
        _CORE_FEEDS + ['period_arch'],
        _facts(
            5,
            5,
            'roof_gable',
            (8, 10),
            (12, 14),
            [
                {'id': 'hoist', 'rule': 'a beam record projecting from the gable apex at the top storey'},
                {
                    'id': 'loading_doors',
                    'rule': '5 double_door records on the west elevation within 0.1 m of one vertical line',
                },
                {'id': 'quay', 'rule': 'a stone quay edge record and a water record west of it'},
                {'id': 'no_modern', 'rule': 'zero curtain_wall records and zero mat_concrete finishes'},
            ],
        ),
        [
            {
                'check': 'era_gate_pass',
                'min_sev': 'warn',
                'year': 1671,
                'renders': ['quarter_sw', 'elevation_w', 'aerial', 'interior_storey_2'],
                'note': 'era_gate.py on four renders of the finished build',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Could this building stand on an Amsterdam canal in 1671? Look for anything that '
                'could not have been built then — sheet glass, exposed concrete, steel sections, '
                'machine-regular brick coursing. Answer yes or no.',
            },
        ],
        (9.0, 13.0, 15.0),
        state_note='period_arch = era_gate on four renders AND the blind operator call; both must pass',
    ),
    _brief(
        'b3_church',
        'B3 — a brick hall church with a west tower, interior built',
        _CORE_FEEDS + ['interior', 'floorplan'],
        _facts(
            3,
            1,
            'roof_gable',
            (18, 22),
            (28, 32),
            [
                {'id': 'tower', 'rule': 'a tower mass 6x6 m +- 0.5 reaching 22 m +- 1'},
                {'id': 'chancel', 'rule': 'a lower mass 8x8 m +- 0.5 at the east end'},
                {'id': 'benches', 'rule': '>= 32 bench / pew furniture records in two rows'},
                {'id': 'nave_windows', 'rule': '12 window records 1.2x4.0 m +- 0.15 with sills at 3.0 m +- 0.2'},
            ],
        ),
        [
            {
                'check': 'plan_rooms_match',
                'max_diff': 1,
                'note': "the 2D plan the drawings_2d family writes vs the drawing's own zone records",
            },
            {'check': 'file_exists', 'path': 'OUT/plan_ground.dxf'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Standing inside this render: is this the interior of a church — one tall space, '
                'seating facing one end, light from high windows — or an empty hall with benches '
                'dropped in it? Answer yes for a church interior.',
            },
        ],
        (20.0, 30.0, 22.0),
        state_note='interior = the bench/pulpit/floor records AND the blind interior call; floorplan = the '
        'DXF exists and its rooms match the zones',
    ),
    _brief(
        'b4_tower',
        'B4 — an eighteen-storey residential tower with a working core',
        _CORE_FEEDS,
        _facts(
            6,
            18,
            'roof_flat',
            (14, 16),
            (12, 14),
            [
                {
                    'id': 'core_to_top',
                    'rule': 'lift and stair records reach storey 17 (to_storey defaults 1 and 3 do NOT clear this)',
                },
                {'id': 'corridor_w', 'rule': 'corridor free width >= 1.5 m on every typical storey'},
                {'id': 'canopy_soffit', 'rule': 'entrance canopy soffit at 3.2 m +- 0.1 and no column piercing it'},
                {'id': 'parapet', 'rule': 'a parapet record 1.1 m +- 0.1 around the flat roof'},
            ],
        ),
        [
            {
                'check': 'graph_connected',
                'max_unreachable': 0,
                'note': "the 2026-09-12 tower run: layout_floor ran the corridor's north wall the full plate "
                'width with no opening at the core block and repeat_floor copied it up, so on every '
                'repeated storey NO flat door was reachable from the stair. This is the column that '
                'catches exactly that.',
            },
            {
                'check': 'transcript_absent',
                'pattern': r'to_storey["\s:=]+(1|3)\b',
                'note': 'add_stair defaults to_storey=1 and add_elevator to_storey=3; leaving the defaults on an '
                '18-storey tower makes the walk check vacuous',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': "Could a person walk from this building's front door to any flat door on the "
                'fifteenth floor? Follow the route in the plan and the section. Answer yes or no.',
            },
        ],
        (15.0, 13.0, 54.0),
        state_note='B4 is the repeat of the 2026-09-12 defects: pool-in-slab, column-through-canopy, '
        'merged tree crowns and the unreachable corridor. Its own gates_pass is the receipt.',
    ),
    _brief(
        'b5_pinas_hull',
        'B5 — build the Witsen 1671 pinas hull from the reference model',
        ['reference_model'],
        [
            {'id': 'length', 'rule': "hull length 37.94 m +- 1.0 (the library's measured figure for 134 voet)"},
            {'id': 'beam', 'rule': 'beam 9.485 m +- 0.5'},
            {'id': 'depth', 'rule': 'hull depth 3.794 m +- 0.4'},
            {'id': 'keel', 'rule': 'a keel member running the full length'},
            {'id': 'stem_stern', 'rule': 'a stem and a sternpost record'},
            {'id': 'frames', 'rule': '>= 20 frame members spaced along the keel'},
            {'id': 'planking', 'rule': 'a planked shell, not a single extruded box'},
            {'id': 'deck', 'rule': 'exactly one deck surface'},
            {'id': 'viewed_plans', 'rule': 'the transcript shows view_reference called on the pinas id'},
            {'id': 'asset_saved', 'rule': 'a .blend and a .glb under data/architecture/reference/<id>/asset'},
            {'id': 'overlay', 'rule': 'a check render exists per plan the build used'},
            {'id': 'not_placed', 'rule': 'no mesh_file or link record was added to any drawing'},
        ],
        [
            {'check': 'transcript_contains', 'pattern': r'view_reference'},
            {
                'check': 'bbox_dims_m',
                'dims': (37.94, 9.485, 3.794),
                'tol_m': 1.0,
                'note': "the library's own measurement of the Witsen pinas — data/architecture/reference/"
                '2694b5765e77/model.json, length_m 37.94, beam_m 9.485, height_m 3.794',
            },
            {
                'check': 'mesh_shell_count',
                'min': 20,
                'note': 'a planked hull is many shells; one shell means an extruded box was called a ship',
            },
            {'check': 'file_exists', 'path': 'OUT/reference_check_render_0.png'},
            {
                'check': 'operator',
                'blind': True,
                'question': "Held against Witsen's 1671 plates, is this the hull of a pinas — the sheer, the "
                'tuck, the stem rake — or a generic boat shape at the right length? Answer yes for '
                'a pinas hull.',
            },
        ],
        (37.94, 9.485, 3.794),
        conditions=dict(COND, wall_clock_min=60),
        state_note='reference_model = the measured bbox against the library figures AND the blind '
        'comparison against the plates; the bbox alone would pass a box',
    ),
    _brief(
        'b6_infinity_villa',
        'B6 — a modern villa with an infinity pool on falling ground',
        _CORE_FEEDS + ['landscape'],
        _facts(
            8,
            2,
            'roof_flat',
            (16, 20),
            (14, 18),
            [
                {
                    'id': 'pool_level',
                    'rule': 'pool water surface within 0.02 m of the terrace deck top, never below it',
                },
                {'id': 'catch_basin', 'rule': 'a catch basin 1.0 m +- 0.2 below the overflow edge'},
                {
                    'id': 'guarding',
                    'rule': 'guarding on every terrace edge with a drop > 1.0 m except the overflow edge',
                },
                {
                    'id': 'trees',
                    'rule': '5 trees, min pairwise centre distance >= 8 m, none within 1 m of the door axis',
                },
            ],
        ),
        [
            {
                'check': 'gates_pass',
                'max_errors': 0,
                'max_warns': 2,
                'note': 'the infinity-pool rules exist BECAUSE of 2026-09-07: water 0.4 m inside the roof slab '
                '(base 54, deck 54.3), 3.5 m columns through a 2.4 m canopy soffit, six 8 m trees 1.5-3 m '
                'apart in two blocks straddling the entrance axis. water_leisure.check_infinity_pools '
                'and finish_rules.check_deck_guarding are the gates.',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does the pool read as an infinity pool — water meeting its far edge with no lip and '
                'nothing visible behind it — and does the site read as designed ground rather than a '
                'flat pad with objects on it? Answer yes only if both hold.',
            },
        ],
        (18.0, 16.0, 6.4),
        state_note='landscape = the tree spacing and the falling-ground seam measured, plus the blind site '
        'call; the v3 ground is the surface the seam is measured against',
    ),
    # ── the gates' own column: plant three defects and see whether the gates name them ──
    {
        'id': 'g1_planted_defects',
        'title': 'G1 — three defects planted in a finished drawing',
        'feeds': ['gates_arch'],
        'inputs': {
            'fixture': 'capability_tests/fixtures/arch/planted_defects.json',
            'task': "run arch_assistant.design_findings on each of the three planted variants of B1's "
            'finished drawing and read the codes it returns',
            'variants': [
                {
                    'id': 'd1_pool_in_slab',
                    'edit': "move the terrace pool record's water y DOWN 0.4 m so it sits inside the deck slab "
                    '(base 2.9, deck 3.3) — the 2026-09-07 defect verbatim',
                    'codes': ['water_below_deck', 'buried', 'pool_in_slab'],
                },
                {
                    'id': 'd2_column_through_canopy',
                    'edit': 'raise the entrance column height from 2.3 m to 3.5 m so it pierces the canopy '
                    'soffit at 2.4 m',
                    'codes': ['column_pierces', 'clash', 'pierce'],
                },
                {
                    'id': 'd3_corridor_wall_no_opening',
                    'edit': 'close the corridor wall across the core block on storey 1 so no unit door is '
                    'reachable from the stair — the layout_floor / repeat_floor defect of 2026-09-16',
                    'codes': ['walk_storey', 'walk_more', 'unreachable'],
                },
            ],
        },
        'conditions': {
            'repeats': 3,
            'per_variant': 1,
            'wall_clock_min': 5,
            'note': 'three variants, one gate run each; the gates are deterministic so one run per '
            'variant is the whole measurement',
        },
        'checks': [
            {
                'check': 'gates_name_planted',
                'planted': [
                    {'id': 'd1_pool_in_slab', 'codes': ['water_below_deck', 'buried', 'pool_in_slab']},
                    {'id': 'd2_column_through_canopy', 'codes': ['column_pierces', 'clash', 'pierce']},
                    {'id': 'd3_corridor_wall_no_opening', 'codes': ['walk_storey', 'walk_more', 'unreachable']},
                ],
            },
            {
                'check': 'gates_pass',
                'max_errors': 0,
                'max_warns': 3,
                'note': 'the UNEDITED B1 drawing must still come back clean — a gate that fires on everything '
                'names nothing',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 1.0, 'partial': 0.5},
        'state_note': 'yes only when all three are named. A gate suite that catches two of three planted defects '
        'is worth saying out loud, which is why partial is 0.5 and not 0.4.',
    },
    # ── the drawings and the exports, off B1's finished build (one fixed input, no new build) ──
    {
        'id': 'p_drawings',
        'title': 'P1 — elevation, section and plan off the finished farmhouse',
        'feeds': ['drawings'],
        'inputs': {
            'fixture': 'capability_tests/fixtures/arch/b1_farmhouse_drawing.json',
            'task': 'from the finished B1 drawing, produce a south elevation, a long section and a ground '
            'floor plan through the drawings_2d / drawings_sheet families, labels OFF',
        },
        'conditions': {'repeats': 1, 'wall_clock_min': 10, 'labels': False},
        'checks': [
            {'check': 'file_exists', 'path': 'OUT/elevation_south.png'},
            {'check': 'file_exists', 'path': 'OUT/section_long.png'},
            {'check': 'file_exists', 'path': 'OUT/plan_ground.png'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Are these three sheets readable as an elevation, a section and a plan of one '
                'building — line weights, cut poché, dimensions where a builder needs them? '
                'Answer yes or no.',
            },
        ],
        'grade': 'measured',
        'state_note': "three files is the mechanical half; whether a builder could read them is the operator's",
    },
    {
        'id': 'p_exports',
        'title': 'P2 — IFC, DXF, STL and GLB all parse',
        'feeds': ['exports_arch'],
        'inputs': {
            'fixture': 'capability_tests/fixtures/arch/b1_farmhouse_drawing.json',
            'task': 'export the finished B1 drawing to IFC, DXF, STL and GLB and parse each with its own strict reader',
        },
        'conditions': {'repeats': 1, 'wall_clock_min': 10},
        'checks': [
            {'check': 'export_parses_as', 'format': 'ifc', 'min_objects': 20},
            {'check': 'export_parses_as', 'format': 'dxf', 'min_objects': 50},
            {'check': 'export_parses_as', 'format': 'stl', 'min_objects': 1},
            {'check': 'export_parses_as', 'format': 'glb', 'min_objects': 20},
            {'check': 'glb_up_axis', 'axis': 'Y', 'note': 'glTF is Y-up; the studio is Y-up; Blender is Z-up'},
        ],
        'grade': 'measured',
        'state_rule': {'yes': 1.0, 'partial': 0.5},
        'state_note': 'four formats; yes only when all four parse. A format that writes a file no reader accepts '
        'is worse than a format that is missing.',
    },
]

TEST = {
    'step': 'arch',
    'version': '2026-09-30.1',
    'title': "Six fixed briefs, unanswered, judged by the studio's own gates",
    'purpose': (
        'Measure a finished building, not a claim about one: six briefs go in with no operator in the '
        'loop and the drawing, the .blend and the .glb come out; the design gates, walk_rules, a bpy '
        'measurement script and era_gate do the judging, and the operator is asked only what no '
        'detector can decide.'
    ),
    'include_shared': 'geometry',
    'harness': HARNESS,
    'rows': {
        'arch_assistant': {
            'transport': 'claude_cli',
            'model': 'claude-sonnet (CLI `claude -p --model sonnet`)',
            'where': 'arch_assistant.py — driven as a SUBPROCESS through ' + PREFIX + '/start; never imported',
            'note': (
                'the standing rules this row is held to: NEVER Opus (feedback_arch_assistant_no_opus), no '
                'auto-select of the backend (feedback_arch_no_autoselect), viewport labels OFF, and the '
                'module must not be imported by a test (feedback_no_import_arch_assistant).'
            ),
            'budget': {
                'calls': 216,
                'tokens_in': 9000000,
                'tokens_out': 120000,
                'minutes': 190,
                'gpu_minutes': 0,
                'operator_minutes': 6,
                'note': (
                    'Six briefs x up to 36 model turns = 216 CLI turns. A 20-storey tower spent 27 '
                    'turns, 784 s and 1.26M CACHED tokens in one job (arch_assistant MAX_CALLS note), '
                    'so ~1.5M processed per brief = ~9M in and ~20k out each. Wall: 6 briefs x '
                    '25-35 min (Sonnet turns + the headless Blender build at the end) = ~190 min. '
                    'This row spends the SHARED Claude week (feedback_meter_is_shared) — schedule it '
                    'against the meter and record the % it cost; NEVER run it on Opus.'
                ),
            },
            'na': {
                'gates_arch': 'the planted-defect probe measures the GATES, not the model that drew the '
                'drawing they are run on; that column belongs to the `gates` row'
            },
        },
        'blender_build': {
            'transport': 'blender',
            'where': 'arch_blender_build.py — `blender -b --python arch_blender_build.py -- --in DRAWING.json '
            '--out OUT.blend --glb OUT.glb` (Blender 4.3, headless)',
            'note': (
                'this row authors nothing: it rebuilds every record of a drawing as a parametric mesh, so it '
                'is measured on FIDELITY — metres, ground seam, openings, roof, finishes, export — and is na '
                'on every column that asks about a design decision.'
            ),
            'budget': {
                'calls': 6,
                'tokens_in': 0,
                'tokens_out': 0,
                'minutes': 18,
                'gpu_minutes': 0,
                'operator_minutes': 0,
                'tokens_note': 'a deterministic bpy builder — no prompt, no language model, no tokens',
                'note': (
                    'Six finished drawings rebuilt headless, ~3 min each including Blender start and '
                    'the GLB write = ~18 min. CPU only: EEVEE is not invoked by the build, only by '
                    'the render families, so gpu_minutes is 0. No operator decisions — every check '
                    'on this row is a measurement on the .blend.'
                ),
            },
            'na': {
                'correct': 'a faithful rebuild of a wrong design is still wrong; whether the BUILDING is right '
                "is the assistant row's column, not the builder's",
                'one_call': 'there is no planning call here — the builder receives a finished drawing JSON and '
                'converts it record by record',
                'model_rule': 'no language model is involved: arch_blender_build.py is a deterministic bpy '
                'script, so there is no model choice to fix or to follow',
                'brief_follow': 'the builder never sees the brief; it sees the drawing the assistant wrote from it',
                'circulation': 'reachability is measured on the drawing records by walk_rules before the build; '
                'the .blend is the same topology and adds nothing to that answer',
                'period_arch': 'period is a design property of the records; the builder gives every kind the '
                'same mesh whatever century the brief named',
                'interior': 'the builder rebuilds interior records faithfully but designs no interior; whether '
                'there IS one is decided upstream',
                'floorplan': 'plan drawings come from the drawings_2d family and the 2D export path, not from '
                'the .blend builder',
                'drawings': 'elevations and sections are rendered by the render_offline / drawings families; '
                'this module writes a .blend and a .glb and nothing else',
                'reference_model': 'reference assets are built by arch_assistant_ext/reference_model.py in an '
                'empty scene, on a different path from the drawing build',
                'gates_arch': 'the gates read records, never meshes; this row is not the thing they judge',
                'tokens': 'no tokens are spent by a bpy script, so tokens per build is not a number that '
                'exists for this row',
            },
        },
        'ext_families': {
            'transport': 'service',
            'where': 'arch_assistant_ext/ (91 live family modules, the ~190-tool dock) via '
            'architecture_studio.ext_families(); each family also has arch_ext/<f>.js + .json, '
            'arch_blender_ext/<f>.py and tests_arch_ext/test_<f>.py',
            'note': (
                'a family IS the capability, so the SCOPE columns are measured here: floor_plans (the plan '
                'library is Swiss Dwellings / ResPlan / ProcTHOR under CC BY and Apache — NEVER CubiCasa or '
                'RPLAN, whose licences do not permit it), site_landscape + ground_v3 + water_v3 for the v3 '
                'landscape and the ground seam, interior_rooms + lobby_fitout + furniture_* for interiors, '
                'drawings_2d + drawings_sheet for the sheets, file_2d/file_2d_ifc + file_3d for the exports, '
                'reference_model for the Witsen pinas.'
            ),
            'budget': {
                'calls': 40,
                'tokens_in': 0,
                'tokens_out': 0,
                'minutes': 35,
                'gpu_minutes': 0,
                'operator_minutes': 3,
                'tokens_note': 'families are called as python functions on a fixture drawing; no prompt is sent',
                'note': (
                    'Each scope column is one or two direct calls into the owning family on the '
                    'finished B1/B3 drawings, plus the export readers: ~40 calls at well under a '
                    'minute each, but arch_ext_harness.blender_kinds shells out to headless Blender '
                    'TWICE per family it checks, so budget 35 min. That harness is FLAKY under a wide '
                    'session-tree fan-out — all kinds come back None at once — so a red Blender leg '
                    'is re-run before it is believed.'
                ),
            },
            'na': {
                'unattended': 'a family is a function, not a job; it has nothing to finish unattended and no '
                'operator to ask',
                'correct': 'a family draws what it is told to draw; architectural rightness is decided by the '
                'gates and by the assistant that composed the calls',
                'one_call': 'the one-call rule is about plan_building resolving the programme; a family is on '
                'the other side of that call',
                'model_rule': 'no model runs in a family module — they are plain python called by the assistant',
                'brief_follow': 'a family never sees a brief; it sees arguments',
                'period_arch': 'no family carries an era gate; period correctness is measured on renders by '
                'era_gate.py against the assistant row',
                'gates_arch': 'the gate families are measured as the `gates` row, where the planted defects are',
                'tokens': 'no tokens are spent by a python family call, so tokens per build does not exist here',
            },
        },
        'gates': {
            'transport': 'service',
            'where': 'arch_assistant.design_findings -> arch_assistant_ext/design_rules.run_checks, plus the '
            'check-only families the gate tree collects: walk_rules.check_walkable, '
            'clash_rules, circulation_rules, entrance_rules, facade_rules, floor_rules, opening_rules, '
            'deck_rules, sightline_rules, finish_rules.check_deck_guarding, '
            'water_leisure.check_infinity_pools, building_program.check_program',
            'note': (
                'the gates exist because of 2026-09-07 (pool inside its own slab, columns through the '
                'canopy, six trees in two blobs on the entrance axis, a self-congratulating render) and '
                '`done` refuses twice while errors remain. Their column is gates_arch: three defects are '
                'planted and the gates must NAME each. Whether the unedited drawing still comes back clean '
                'is part of the same measurement.'
            ),
            'budget': {
                'calls': 9,
                'tokens_in': 0,
                'tokens_out': 0,
                'minutes': 6,
                'gpu_minutes': 0,
                'operator_minutes': 2,
                'tokens_note': 'run_checks reads records and returns findings; no model call, no prompt',
                'note': (
                    'Three planted variants plus the unedited control on each of the two drawings '
                    'that carry the defects (B1 terrace, B4 tower) = 9 gate runs. run_checks is a '
                    'pass over the records: seconds each, so 6 min covers loading the fixtures and '
                    'the walk_rules width grids. Deterministic, hence one run per variant.'
                ),
            },
            'na': {
                'unattended': 'a gate has no build to finish; it is the thing that refuses a build, so '
                '"finishes unattended" is not a question about it',
                'one_call': 'the gates are not the planning call and cannot resolve a programme',
                'model_rule': 'no language model runs in the gate path — run_checks is arithmetic over records',
                'brief_follow': 'the gates never see the brief; check_program compares the drawing against the '
                'programme plan_building already resolved, which is a different question',
                'period_arch': 'no gate reads a date; era_gate.py is a separate judge run on renders, not part '
                'of design_findings',
                'floorplan': "the gates read the drawing's own records, not a plan artefact, and produce no "
                'plan of their own',
                'drawings': 'the gates write findings, not sheets; nothing in the gate path renders anything',
                'exports_arch': 'a gate has no export path — it returns a list of findings to the caller',
                'reference_model': 'no gate compares a build against a reference model; that comparison is the '
                'check render inside reference_model.build_reference_asset',
                'tokens': 'no tokens are spent by the gate pass, so tokens per build is not a number for this row',
            },
        },
    },
    'probes': PROBES,
    'derive': {
        'tokens': {
            'from': (
                "the CLI's OWN usage records for the six briefs: llm_audit rows for the job plus the "
                'stream-json `usage` blocks (input, cache_creation, cache_read, output). The column is '
                'the MEAN processed tokens per finished build, with the per-brief spread in the note. '
                'Cached tokens are counted and named as cached — a resumed turn wrote 1,950 cache '
                'tokens against 76,203 for a fresh spawn, so a mean that hides the split is a lie.'
            ),
            'grade': 'receipt',
            'unit': 'tokens',
        },
    },
    'lookup': {},
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': 'data/architecture/reference/2694b5765e77/model.json',
            'note': 'the Witsen 1671 pinas reference — Nicolaes Witsen, Aeloude en hedendaegsche scheeps-bouw en '
            'bestier, Amsterdam, Casparus Commelijn, 1671, scanned by the Getty Research Institute. The '
            "library's measured figures (length_m 37.94, beam_m 9.485, height_m 3.794 — a 134-voet pinas) "
            'are what B5 is scored against.',
            'verified': True,
        },
        {
            'path': 'data/architecture/reference/2694b5765e77/asset/witsen-pinas-hull.glb',
            'note': "the existing hull build, kept as the shape B5's own build is compared with by the operator",
            'verified': True,
        },
        {
            'path': 'capability_tests/fixtures/arch/b1_farmhouse_drawing.json',
            'generated': (
                'the FIRST repeat of probe b1_farmhouse, saved verbatim: `curl -s -X POST '
                + PREFIX
                + '/start -d \'{"text": "<BRIEFS[b1_farmhouse]>", "backend": "cli", '
                '"labels": false}\'`, poll ' + PREFIX + '/job until status=done, then copy the drawing '
                'JSON out of data/architecture/projects/<id>/ to this path. P1 and P2 run on this one '
                'fixed drawing so the sheets and the exports are measured on identical input.'
            ),
            'verified': False,
            'blocks': ['drawings', 'exports_arch'],
            'how_to_verify': (
                'the operator opens the saved drawing in Architecture Studio, confirms it is the '
                'farmhouse B1 asked for (two storeys, six ground-floor rooms, thatched gable) and '
                'flips verified to True. Until then P1 and P2 have no pinned input and their columns '
                'ship untested.'
            ),
        },
        {
            'path': 'capability_tests/fixtures/arch/planted_defects.json',
            'generated': (
                'three copies of the finished B1 and B4 drawings with one defect each, written by a small '
                'script that edits records only: d1 lowers the terrace pool water y by 0.4 m; d2 raises '
                'the entrance column height 2.3 -> 3.5 m under a 2.4 m canopy soffit; d3 closes the '
                'corridor wall across the core block on storey 1. `python3 -c "import json, copy; ..."` '
                'over the two saved drawings — no binaries, no rebuild.'
            ),
            'verified': False,
            'blocks': ['gates_arch'],
            'how_to_verify': (
                'the operator loads each variant in the studio and confirms the planted defect is the '
                'ONLY difference from the control, then flips verified to True. A planted-defect test '
                'whose variants also differ by accident measures nothing.'
            ),
        },
        {
            'path': 'capability_tests/fixtures/arch/scripts/arch_structure_probe.py',
            'generated': (
                'the bpy measurement script `structure_supported`, `roof_geometry_ok` and '
                '`ground_seam_gap_max` read: run as `blender -b OUT.blend --python '
                'arch_structure_probe.py -- --json OUT/structure.json`, it walks the objects, ray-casts '
                'down from every wall/column base and across every roof-to-wall-head joint on a 0.25 m '
                'lattice, and writes the violations. Written by the runner author from the check-kind '
                'definitions above; no model involved.'
            ),
            'verified': False,
            'blocks': ['structure_arch', 'roof', 'ground_seam'],
            'how_to_verify': (
                'run the probe on the existing witsen-pinas.blend and on one known-bad drawing (the '
                '2026-09-07 tower, if the .blend survives): it must report 0 violations on a clean '
                'file and name the pool-in-slab on the bad one. Until that calibration exists, its '
                'three columns ship untested.'
            ),
        },
    ],
    'budget': {
        'calls': 271,
        'tokens_in': 9000000,
        'tokens_out': 120000,
        'minutes': 249,
        'gpu_minutes': 0,
        'operator_minutes': 11,
        'note': (
            'Per row, defaulting to the assistant row and overridden for the other three. Assistant: 6 briefs '
            'x 36 turns = 216 CLI turns, ~1.5M processed per brief (measured: one 20-storey job spent 27 '
            'turns, 784 s, 1.26M cached), ~190 min wall; plus 40 family calls, 9 gate runs and 6 headless '
            'rebuilds = 271 calls and ~249 min. The SHARED geometry bank adds its own cost on top of this '
            'and is the larger half: its 210 probes over the Builds / Capacity / Space / Attributes / Prompt '
            'bands are subject renders, and for a row whose "render" is a Blender build each subject is a '
            'headless build — at 132 subjects x 3 seeds that is 396 builds at ~3 min = ~20 GPU-free hours '
            'per row, which is why run_order puts the bank LAST and the domain probes first. gpu_minutes is '
            '0 throughout: nothing here loads a model onto the card — the assistant runs on the login CLI '
            'and the builds are CPU bpy. Operator: 11 blind decisions at ~30 s (6 brief calls, 1 sheet call, '
            '2 gate-variant confirmations, 2 fixture verifications) = ~11 min. CLAUDE-WEEK WARNING: the '
            'arch_assistant row is claude_cli on the operator LOGIN and spends the shared weekly meter '
            '(feedback_meter_is_shared) — schedule it, watch the usage hold, and NEVER substitute Opus for '
            'Sonnet to make it finish sooner.'
        ),
    },
    'run_order': [
        'g1_planted_defects',
        'p_exports',
        'p_drawings',  # mechanical, minutes, no model
        'b1_farmhouse',
        'b4_tower',
        'b6_infinity_villa',  # the three builds the gates were written for
        'b2_quay_warehouse',
        'b3_church',
        'b5_pinas_hull',  # period, interior, reference — the long ones
        'SHARED:geometry',  # the subject bank last: 396 builds per row
    ],
    'notes': [
        'The gates are the judge of `correct`, and they are house code, not a model. That is the point: a local '
        'VLM does not reliably see a column through a canopy or a pool inside its own slab (defect judge bench '
        '2026-09-27: 34/40 on a global question, 2/8 on the hard cases), but a records pass sees both exactly. '
        'Where no such pass exists — does this read as a church, as 1671, as an infinity pool — the call is an '
        "operator's, blind, with the question written here.",
        'No row runs Opus. The assistant refuses opus / fable / mythos by name (arch_assistant.EXPENSIVE) and '
        '`model_rule` checks the transcript for `--model sonnet` AND for the absence of opus, so a config drift '
        'shows as a failed column rather than as a quiet bill. The headless drawing contest of 2026-09-17 is the '
        'only Opus exception on record and it is not part of this test.',
        'The floor-plan library is Swiss Dwellings, ResPlan and ProcTHOR under CC BY / Apache, and every placement '
        "appends its attribution line to d.ext['attributions']. CubiCasa and RPLAN are NEVER used here — their "
        'terms do not permit it — so a `floorplan` answer that came from either is a failed column, not a result.',
        'arch_ext_harness.blender_kinds shells out to headless Blender twice and is flaky under a wide '
        'session-tree fan-out: the signature is EVERY kind reporting None at once, where a real geometry bug '
        'fails one kind. A red Blender leg on the ext_families row is re-run before it is written to the sheet.',
        'A job that asks a question is a `no` on unattended, not an `untested`: it did that under the test. A '
        'transport failure — the CLI refusing on the quota, the studio not answering a `look`, Blender dying on '
        'start — is `untested` with the error as the note.',
    ],
}
