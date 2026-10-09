# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Mesh QC (mesh_qc). 2026-09-30.

Question the sheet asks: is the geometry actually correct?

The rows of this step are not generators. They are CHECKERS, and a checker is measured the
only honest way a checker can be measured: PLANT a defect, hand the checker the broken mesh
and its clean twin, and ask whether it flagged exactly the planted one. Recall 1.0 on the
planted fixture, 0 false alarms on the twin. Nothing else counts. A checker that says "fail"
on everything has recall 1.0 and is worthless; a checker that says "pass" on everything has 0
false alarms and is worse. The twin is what makes the pair a measurement.

One planted defect per column, thirteen fixtures plus thirteen twins, all produced by one bpy
script this test NAMES and does not run:

    anatomy          a third arm grafted on the right shoulder
    proportions      crotch_height_over_stature driven to 0.42 — far outside the ANSUR p1p99
                     band (the real originals sat at male 0.4553 / z -1.86, female 0.4485 /
                     z -2.10, which is how big a real miss looks; 0.42 is unmistakable)
    phalanx          a right index finger with four phalanges instead of three
    manifold         one face deleted (a boundary hole) AND a pinch-vertex twin, because
                     geom/anthro/integrity.py exists precisely because trimesh.is_watertight
                     answers a boundary hole and an edge-in-three-faces with one bool and says
                     nothing at all about a pinch vertex
    selfint          the left forearm pushed 40 mm into the trunk — the Abel defect: a mesh
                     that passed every visual review and was unusable downstream
    normals          one shell's winding reversed so its normals point inward
    degenerate       twelve zero-area triangles and one duplicate-vertex face
    uv_overlap       one UV island translated onto another, 8 per cent of face area overlapping
    scale_check      the whole body scaled 10x (17 m tall)
    export           exported Z-up instead of +Y up (project_body_plates_gltf_upaxis)
    units            exported in centimetres, so a 1.75 m body reads 175 m
    material_export  the materials stripped on export, one default grey left

`automated` and `blocks` are the two columns a probe cannot answer, because they are facts
about the CODE PATH and not about a mesh: is the check on the pipeline's path, and can it stop
a ship. Both are `wiring`, read off geom/anthro/gates.py with the file and line, and are
visibly graded `assumed` so they can never be mistaken for a measurement.

Why the whole Builds band is na here
------------------------------------
The geometry bank asks all six 3D steps to BUILD 132 subjects. A checker builds nothing, and
there is no honest reading of "models a broken window" for geom/anthro/integrity.py. The
tempting re-reading — "checks a <subject> mesh correctly" — would need 132 planted subjects
with a verified answer key each, which is a bench in its own right and not this test; asserting
it from thirteen body fixtures would be a claim about meshes nobody planted. So all ten Builds
bands are `na` at step level with that reason written out, and the thirteen planted fixtures
carry the whole weight of the step.

The bank's Capacity, Space & relation and Attributes bands are LEFT to the bank, and they are
the weakest part of this sheet: they too are phrased for a builder. They are recorded here as a
known limitation rather than silently overridden, because overriding a validated shared bank
from one step's module is how a bank stops meaning the same thing in every step.
"""

from __future__ import annotations

# ── check kinds this module adds ─────────────────────────────────────────────────────────────
# A checker is graded on a PAIR — the planted fixture and its clean twin — so the kind has to
# take both. The bank has no such kind because the bank grades builders.
CHECK_KINDS = {
    'gate_flags_planted': 'the check under test is run on every fixture named in `planted` and on '
    'every clean twin in `clean`: it must flag the planted defect in at '
    'least `recall` of the planted set (default 1.0) and flag nothing in the '
    'clean set (false alarms <= `false_alarms`, default 0). Both halves must '
    'hold; either alone is not a result',
    'gate_flags_named': 'the flag the check raised is the one the fixture planted: the raised '
    'check id / gate id is in `expect_ids`. A checker that fails the right '
    'mesh for the wrong reason is not a working checker',
    'report_contains': "the check's own report text names the defect: every term in `terms` "
    'occurs (case-insensitive, word boundary) in the report for the planted '
    'fixture, and none of them occurs in the report for the clean twin',
    'gate_report_parses': 'the check returns a structured result (a dict or JSON) with a per-check '
    'pass flag, not a single boolean and not a printed line: a caller must be '
    'able to tell WHICH check failed without reading prose',
    'check_deterministic': 'the check run `repeats` times on the same fixture returns the same '
    'per-check pass flags and the same flagged ids every time',
}

FX = 'capability_tests/fixtures/geometry/planted'
MAKER = FX + '/make_planted.py'

# The generator, named once and run by nobody in this task. Every fixture's `generated` points
# at one subcommand of it, so the whole set is reproducible from one script and one seed.
MAKER_RECIPE = (
    'blender -b --python ' + MAKER + ' -- --defect <name> --out ' + FX + '/<name>.glb . The script '
    'loads the male CC0 base body from blender_scripts/build_human_base_library.py (stature pinned '
    'to 1.750 m, +Y up), writes the CLEAN twin <name>_clean.glb first, then applies exactly ONE '
    'planted defect and writes <name>.glb. Nothing else differs between the pair — same vertex '
    'order, same materials, same export settings — so any flag the checker raises on the pair is '
    'attributable to the plant and to nothing else.'
)

BODY = {'stature_m': 1.750, 'source': 'the male CC0 base body (blender_scripts/build_human_base_library.py)'}

COND = {
    'repeats': 3,
    'pair': 'the planted fixture and its clean twin, in that order, in one call each',
    'settings': "the check module's shipped defaults, unchanged and copied verbatim into the trial",
    'timeout_s': 600,
    'note': 'three repeats because a checker that is not deterministic is not a gate; the FIRST '
    'repeat is what first_take reads. A checker is CPU work — no seed, no sampler, nothing '
    'to vary but the implementation.',
}

ALL_ROWS = ['anatomy_qc_mesh', 'selfint', 'upaxis']
ANAT = ['anatomy_qc_mesh']
TOPO = ['selfint']
EXPO = ['upaxis']


def _defect(name, planted_cols, terms, expect_ids, blocks_note=None):
    """One planted-defect probe: the pair, the recall/false-alarm rule, the named flag."""
    return name, planted_cols, terms, expect_ids, blocks_note


def _p(pid, title, feeds, fixture, checks, rows, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {
            'fixture': fixture,
            'prompt': None,
            'note': 'the pair: ' + fixture + ' and its _clean twin, both from ' + MAKER,
        },
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': list(rows),
    }
    p.update(kw)
    return p


def _pair(name, terms, expect_ids, extra=None):
    """The three checks every planted-defect probe carries, plus any extra."""
    ch = [
        {
            'check': 'gate_flags_planted',
            'planted': [FX + '/' + name + '.glb'],
            'clean': [FX + '/' + name + '_clean.glb'],
            'recall': 1.0,
            'false_alarms': 0,
        },
        {'check': 'gate_flags_named', 'expect_ids': list(expect_ids)},
        {'check': 'report_contains', 'terms': list(terms)},
    ]
    return ch + list(extra or [])


PROBES = [
    # ── anatomy and proportions: the body checks (geom/body_metrics.py, geom/fit_proportions.py) ──
    _p(
        'plant_anatomy',
        'Catches a third arm',
        ['anatomy'],
        FX + '/anatomy_third_arm.glb',
        _pair('anatomy_third_arm', ['arm', 'limb'], ['anatomy.limb_count', 'integrity.shell_components']),
        ANAT,
        state_note='the plant is a whole extra arm grafted at the right shoulder — the coarsest '
        'anatomical defect there is. A checker that misses this one cannot be trusted on '
        'anything subtler, so it is first in run_order and it is the cheapest to run.',
    ),
    _p(
        'plant_proportions',
        'Catches legs outside the survey band',
        ['proportions'],
        FX + '/proportions_short_legs.glb',
        _pair(
            'proportions_short_legs',
            ['crotch', 'stature', 'proportion'],
            ['fit_proportions.crotch_height_over_stature', 'gates.band_check'],
        ),
        ANAT,
        state_note='crotch_height_over_stature driven to 0.42 against an ANSUR p1p99 band. The real '
        'originals missed by z -1.86 (male 0.4553) and z -2.10 (female 0.4485) before the '
        'fourth issue fixed them, so 0.42 is a MISS THAT ALREADY HAPPENED made larger, '
        'not an invented number. A checker that only reports ten independent marginal '
        'bands and no joint gate is a partial here: ten 90 per cent intervals admit at '
        'most 0.9^10 = 35 per cent of real people (geom/anthro/gates.py rule 1).',
    ),
    _p(
        'plant_phalanx',
        'Catches a four-bone finger',
        ['phalanx'],
        FX + '/phalanx_four_bone.glb',
        _pair('phalanx_four_bone', ['phalan', 'finger'], ['anatomy.phalanx_count']),
        ANAT,
        state_note='a right index finger with four phalanges. This is the defect no local VLM sees '
        '(defect judge bench 2026-09-27: 2/8 on extra digits and 2/8 on fused fingers), '
        'which is exactly why it must be a mechanical count off the mesh and not a '
        'picture question. MediaPipe hand_landmarker counts extended fingers on a RENDER '
        'and cannot count bones, so it is not an alternative here.',
    ),
    _p(
        'plant_scale',
        'Catches a 10x body',
        ['scale_check'],
        FX + '/scale_10x.glb',
        _pair(
            'scale_10x',
            ['scale', 'stature', 'metre'],
            ['scale.stature_m', 'body_plates.stature'],
            [{'check': 'gate_report_parses'}],
        ),
        ALL_ROWS,
        state_note='a 17.5 m body. Every row is asked this one because every row reads a dimension '
        'off the mesh before it means anything, and a silent 10x is the defect that '
        'travels furthest downstream: it survives every topological check ever written.',
    ),
    # ── topology and geometry: the integrity checks (geom/anthro/integrity.py) ──
    _p(
        'plant_manifold',
        'Catches a hole AND a pinch vertex',
        ['manifold'],
        FX + '/manifold_hole.glb',
        [
            {
                'check': 'gate_flags_planted',
                'planted': [FX + '/manifold_hole.glb', FX + '/manifold_pinch.glb', FX + '/manifold_edge3.glb'],
                'clean': [
                    FX + '/manifold_hole_clean.glb',
                    FX + '/manifold_pinch_clean.glb',
                    FX + '/manifold_edge3_clean.glb',
                ],
                'recall': 1.0,
                'false_alarms': 0,
            },
            {
                'check': 'gate_flags_named',
                'expect_ids': ['integrity.watertight', 'integrity.edge_manifold', 'integrity.vertex_manifold'],
            },
            {'check': 'report_contains', 'terms': ['manifold', 'boundary', 'edge']},
            {'check': 'gate_report_parses'},
        ],
        TOPO,
        state_note='THREE plants, not one, and they must be told apart: a deleted face (boundary '
        'hole), an edge used by three faces, and two cones meeting at one pinch vertex '
        'where every edge is perfectly 2-manifold. trimesh.is_watertight conflates the '
        'first two into one bool and is blind to the third '
        '(geom/anthro/integrity.py). A row that reports one `is_valid` boolean over all '
        'three is a PARTIAL however loudly it fails them, because the caller cannot tell '
        'which repair to run.',
        state_rule={'yes': 1.0, 'partial': 0.34},
    ),
    _p(
        'plant_selfint',
        'Catches a forearm inside the trunk',
        ['selfint'],
        FX + '/selfint_arm_trunk.glb',
        _pair(
            'selfint_arm_trunk',
            ['self-intersect', 'intersect'],
            ['integrity.self_intersection'],
            [{'check': 'gate_report_parses'}],
        ),
        TOPO,
        state_note='the left forearm pushed 40 mm into the trunk. This is the Abel finding and the '
        'reason self-intersection is a first-class check and not a nicety: the mesh '
        'passed every visual review and was unusable downstream. Self-intersection is '
        'invisible to every topological check there is — it is pure geometry — so a row '
        'that answers manifold and stops is a no on this column, not a partial.',
    ),
    _p(
        'plant_normals',
        'Catches an inward-facing shell',
        ['normals'],
        FX + '/normals_flipped.glb',
        _pair('normals_flipped', ['normal', 'winding', 'inward'], ['integrity.outward', 'integrity.winding']),
        TOPO,
        state_note="one shell's winding reversed. The trap the checker must avoid is answering this "
        'from the winding histogram alone: a consistently-wound shell can still be '
        'inside-out, and signed volume is what decides. integrity._check_outward REFUSES '
        'rather than answering when the winding is inconsistent, and a refusal on the '
        'planted fixture is a PARTIAL (honest) while a pass is a no.',
    ),
    _p(
        'plant_degenerate',
        'Catches zero-area and duplicate-vertex faces',
        ['degenerate'],
        FX + '/degenerate_faces.glb',
        _pair('degenerate_faces', ['degenerate', 'zero-area', 'duplicate'], ['integrity.degenerate']),
        TOPO,
        state_note='twelve zero-area triangles and one face with a repeated vertex, out of a body of '
        'roughly 14k faces — under 0.1 per cent, which is the point: a threshold that '
        'lets "a few" through lets exactly this through, and a zero-area face crashes a '
        'UV unwrap and a physics bake.',
    ),
    _p(
        'plant_uv',
        'Catches an overlapping UV island',
        ['uv_overlap'],
        FX + '/uv_overlap_island.glb',
        _pair('uv_overlap_island', ['uv', 'overlap'], ['uv.overlap_share']),
        TOPO,
        state_note='one island translated onto another, 8 per cent of face area overlapping. The '
        'clean twin has MIRRORED islands left in place on purpose: a checker that counts '
        'a deliberate mirror as an overlap raises a false alarm on the twin and fails the '
        'pair, which is the distinction between a UV checker and a UV complainer.',
    ),
    # ── export: the GLB contract (geom/body_plates.py) ──
    _p(
        'plant_export',
        'Catches a Z-up GLB',
        ['export'],
        FX + '/export_z_up.glb',
        _pair(
            'export_z_up',
            ['up-axis', 'up axis', 'orientation'],
            ['body_plates.up_axis', 'glb.up_axis'],
            [{'check': 'gate_report_parses'}],
        ),
        EXPO,
        state_note='the glTF importer expresses its Y-up to Z-up conversion AS rotation_euler '
        '(90,0,0) on the imported object, so re-ASSIGNING that rotation is a no-op — the '
        'first attempt in geom/body_plates.py did exactly that and the re-measured height '
        'came back 0.3922 unchanged. A checker that reads the object rotation rather than '
        'the measured vertical EXTENT will pass this fixture and is a no. The check must '
        'PROVE its verdict from the extent against the recorded stature, as '
        'geom/body_plates.py:227 does.',
    ),
    _p(
        'plant_units',
        'Catches centimetres exported as metres',
        ['units'],
        FX + '/units_centimetres.glb',
        _pair(
            'units_centimetres',
            ['unit', 'scale', 'metre'],
            ['units.scene_scale', 'glb.units'],
            [{'check': 'gate_report_parses'}],
        ),
        EXPO,
        state_note='a 1.750 m body exported in centimetres, so it reads 175 m. Distinct from '
        'scale_10x on purpose: 10x is a modelling error and 100x with a unit tag is an '
        'EXPORT SETTING error, and the two have different fixes. A checker that reports '
        'only "wrong size" for both is a partial.',
    ),
    _p(
        'plant_material',
        'Catches materials lost on export',
        ['material_export'],
        FX + '/material_dropped.glb',
        _pair('material_dropped', ['material', 'missing'], ['material.count', 'material.names']),
        EXPO,
        state_note="the twin carries the base body's named skin and eye materials; the plant has "
        'them stripped to one default grey. The check must notice the LOSS, which means '
        'it needs the expected material names from the build receipt — a bare "has at '
        'least one material" test passes the plant and is a no.',
    ),
    # ── the report itself ──
    _p(
        'explains',
        'Names what is wrong',
        ['explains_mesh'],
        FX + '/anatomy_third_arm.glb',
        [
            {'check': 'report_contains', 'terms': ['arm', 'limb']},
            {'check': 'gate_report_parses'},
            {'check': 'check_deterministic', 'repeats': 3},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Reading only this failure report, and without seeing the mesh: could you find and fix the defect it describes — does it name WHAT is wrong and WHERE? yes/no',
            },
        ],
        ALL_ROWS,
        state_note='the whole planted set is run and the column is the share of plants whose report '
        'names the planted defect. The operator question is asked on the report TEXT '
        'only, never with the mesh beside it: a report that is only readable next to the '
        'thing it describes is not a report. "FAIL" with an exit code is a no; a numbered '
        'per-check result with the observed value and the band is a yes.',
    ),
]

RUN_ORDER = [
    # every probe here is CPU seconds; the order is cheapest and most diagnostic first, so a
    # partial run still tells the operator whether the checker works at all
    'plant_anatomy',
    'plant_scale',
    'plant_degenerate',
    'plant_manifold',
    'plant_normals',
    'plant_selfint',
    'plant_uv',
    'plant_export',
    'plant_units',
    'plant_material',
    'plant_proportions',
    'plant_phalanx',
    'explains',
    'SHARED: capacity, space, attributes, prompt bands (the bank; see notes — weakest part of this sheet)',
]

# ── the Builds band: a checker builds nothing ────────────────────────────────────────────────
NA_BANDS = {
    'reason': (
        'A mesh_qc row is a CHECKER, not a builder: geom/anthro/integrity.py, '
        'geom/body_metrics.py and the GLB up-axis check take a mesh in and return a verdict. '
        'They cannot model a person, a barrel or a broken window at any setting, so "Models '
        'a <subject>" has no reading for them. The tempting re-reading, "checks a <subject> '
        'mesh correctly", would need 132 planted subject meshes each with its own verified '
        'answer key — a bench in its own right, not this test — and answering it from the '
        'thirteen planted BODY fixtures would be a claim about meshes nobody planted. The '
        'planted-defect probes are where this step is measured.'
    ),
    'bands': [
        'Builds: People',
        'Builds: The body',
        'Builds: Food',
        'Builds: Damage & wear',
        'Builds: Text & number',
        'Builds: Objects',
        'Builds: Animals',
        'Builds: Nature & weather',
        'Builds: Built environment',
        'Builds: Clothing',
    ],
}

# ── per-row exemptions: which row owns which check ──────────────────────────────────────────
_ANAT_NA = {
    c: (
        'geom/body_metrics.py and geom/fit_proportions.py measure body PROPORTIONS off '
        'landmarks and ratios; they assume a closed, orientable, non self-penetrating '
        'surface and do not test for one. This column belongs to the selfint row '
        '(geom/anthro/integrity.py), which is the tier that must pass before any number '
        'this row produces has a referent.'
    )
    for c in ['manifold', 'selfint', 'normals', 'degenerate', 'uv_overlap']
}
_ANAT_NA.update(
    {
        c: (
            'this row reads a mesh that is already in memory at real scale; the GLB '
            "export contract — orientation, units, materials — is the upaxis row's "
            'question and is decided before this row is ever called.'
        )
        for c in ['export', 'units', 'material_export']
    }
)

_TOPO_NA = {
    c: (
        'geom/anthro/integrity.py is Tier-1 mesh integrity and is deliberately ignorant of '
        'what the mesh depicts: it knows triangles, edges, shells and volumes, not arms, '
        "fingers or survey bands. Anatomy is the anatomy_qc_mesh row's question, and "
        'answering it here would be the exact merge of tiers that file exists to prevent.'
    )
    for c in ['anatomy', 'proportions', 'phalanx']
}
_TOPO_NA.update(
    {
        c: (
            'an integrity check runs on the vertex and face arrays, before and after any '
            "export; the GLB export contract is the upaxis row's question."
        )
        for c in ['export', 'units', 'material_export']
    }
)
_TOPO_NA['scale_check'] = (
    "integrity works in the mesh's own coordinates and is scale-free by "
    'construction — every one of its checks gives the same verdict on a 1x '
    'and a 10x body, which is precisely why a separate scale check is '
    'needed. Claiming it here would be claiming a check that cannot exist.'
)

_EXPO_NA = {
    c: (
        "the GLB up-axis / units / material check reads the exported file's transform, "
        'scene scale and material table. It never touches the triangles, so it cannot and '
        'must not answer a topology or an anatomy question.'
    )
    for c in ['anatomy', 'proportions', 'phalanx', 'manifold', 'selfint', 'normals', 'degenerate', 'uv_overlap']
}

TEST = {
    'step': 'mesh_qc',
    'version': '2026-09-30.1',
    'title': 'Thirteen planted defects and thirteen clean twins',
    'purpose': (
        'Measure each mesh check the only way a checker can be measured: plant one defect, '
        'hand it the broken mesh and its otherwise byte-identical clean twin, and require '
        'recall 1.0 on the plant with 0 false alarms on the twin, the right flag raised, '
        'and a report that names the defect.'
    ),
    'include_shared': 'geometry',
    'planted_set': {
        'dir': FX,
        'maker': MAKER,
        'recipe': MAKER_RECIPE,
        'body': BODY,
        'rule': 'one defect per fixture, one clean twin per fixture, nothing else different between the pair',
    },
    'run_order': RUN_ORDER,
    'na_bands': NA_BANDS,
    'rows': {
        'anatomy_qc_mesh': {
            'transport': 'service',
            'model': 'the house anatomy checks over a body mesh',
            'where': 'geom/body_metrics.py (five proportions as fractions of standing height, '
            'MediaPipe-only, Apache-2.0) and geom/fit_proportions.py '
            '(measure_ratios / ratio_z against the ANSUR-II reference), driven through '
            'geom/anthro/gates.py',
            'na': _ANAT_NA,
        },
        'selfint': {
            'transport': 'service',
            'model': 'Tier-1 mesh integrity (project_abel_self_intersection)',
            'where': 'geom/anthro/integrity.py check_integrity (line 1974): watertight, '
            'edge-manifold, vertex-manifold, winding, outward, degenerate, Euler, '
            'shell components and the exact triangle-pair self-intersection test',
            'na': _TOPO_NA,
        },
        'upaxis': {
            'transport': 'service',
            'model': 'the GLB export contract check (project_body_plates_gltf_upaxis)',
            'where': 'geom/body_plates.py:205-229 — measures the vertical EXTENT against the '
            'recorded stature, applies a -90 X delta when the glTF was authored Z-up, and '
            'raises rather than trusting the assignment (line 227)',
            'na': _EXPO_NA,
        },
    },
    'probes': PROBES,
    'derive': {
        'silent_fail': {
            'from': 'the planted set: the share of planted fixtures the row flagged at '
            'all. A defect the checker passes IS the silent failure this column '
            'asks about, so for a QC row this column is 1 minus the miss rate '
            'over the thirteen plants',
            'grade': 'measured',
            'unit': 'share of plants flagged',
        },
    },
    'lookup': {},
    'wiring': {
        'automated': {
            'read': "whether the check is on the pipeline's path rather than a script "
            'someone remembers to run. Read at geom/anthro/gates.py:2968-2972, '
            'where the gate engine calls '
            'geom.anthro.integrity.check_integrity and turns each returned '
            'per-check dict into a gate result with that source string, and at '
            'geom/anthro/gates.py:2999-3005 for the shell_components payload. '
            "Record the caller file:line for the row's own check and, where "
            'there is none, write "not wired" with the date checked. Never run — '
            'marked assumed and visibly so',
            'grade': 'assumed',
        },
        'blocks': {
            'read': 'whether a failure STOPS a ship or only records a note. Read off the '
            "gate engine's severity policy: geom/anthro/gates.py rule 6 — blocking "
            'severity is measured, not declared — and the ordering-assertion policy '
            'in rule 2, where only the steps with a measured 0 per cent violation '
            'rate over 6,068 ANSUR people block and the rest are WARNINGS carrying '
            'their violation rate (acromion above suprasternale is violated by '
            '45.8 per cent of ANSUR men, trochanterion above buttock by 19.8, '
            'iliocristale above omphalion by 42.5, buttock above crotch by 2.3). '
            'A check whose failure is a warning is a partial on this column, not a '
            'yes. Record file:line per row. Marked assumed',
            'grade': 'assumed',
        },
    },
    'na': {},
    'fixtures': [
        {
            'path': MAKER,
            'generated': 'Written by hand, once, as part of standing up this bench. One bpy script '
            'with a --defect subcommand per fixture below, so the whole planted set is '
            'reproducible from one file. It must write the CLEAN twin before applying the '
            'defect, from the same loaded body, so the pair differs in the plant and in '
            'nothing else.',
            'verified': False,
            'blocks': [
                'anatomy',
                'proportions',
                'phalanx',
                'manifold',
                'selfint',
                'normals',
                'degenerate',
                'uv_overlap',
                'scale_check',
                'export',
                'units',
                'material_export',
                'explains_mesh',
            ],
            'how_to_verify': 'Run each subcommand, then open each PAIR in Blender side by side and '
            'confirm (a) the clean twin has NO defect of any kind — it is the thing '
            'the false-alarm half of every probe is measured against, so a twin with '
            'an accidental degenerate face silently breaks every column, and (b) the '
            'planted fixture has EXACTLY the one defect its name claims and no '
            'second one. Then set verified = True. Until then every column of this '
            'step is written untested "fixture unverified".',
        },
        {
            'path': FX + '/anatomy_third_arm.glb',
            'generated': MAKER_RECIPE + ' --defect anatomy_third_arm: duplicate the right arm shell, '
            'mirror it 120 mm below the shoulder and join it to the body.',
            'verified': False,
            'blocks': ['anatomy'],
            'how_to_verify': 'Three arms in the plant, two in the twin, nothing else changed.',
        },
        {
            'path': FX + '/proportions_short_legs.glb',
            'generated': MAKER_RECIPE + ' --defect proportions_short_legs: scale the leg chain so '
            'crotch_height_over_stature reads 0.42 with stature held at 1.750 m (the '
            'fourth-issue arithmetic: stature is pinned, so the length has to come out of '
            'the legs and go into the torso).',
            'verified': False,
            'blocks': ['proportions'],
            'how_to_verify': 'Measure crotch height and stature with geom.fit_proportions.crotch_frac '
            "and confirm 0.42 +- 0.005 in the plant and the build's own value in the "
            'twin; confirm stature is still 1.750 m in BOTH, or the plant is a scale '
            "defect wearing a proportion defect's name.",
        },
        {
            'path': FX + '/phalanx_four_bone.glb',
            'generated': MAKER_RECIPE + ' --defect phalanx_four_bone: insert one extra phalanx segment '
            'into the right index finger, keeping total finger length unchanged.',
            'verified': False,
            'blocks': ['phalanx'],
            'how_to_verify': 'Count the creases on the right index finger: four segments in the plant, '
            'three in the twin, and the fingertip in the same place in both (a longer '
            'finger would also be a proportion defect).',
        },
        {
            'path': FX + '/manifold_hole.glb',
            'generated': MAKER_RECIPE + ' --defect manifold_hole: delete one face on the left flank.',
            'verified': False,
            'blocks': ['manifold'],
            'how_to_verify': 'Exactly one boundary loop of exactly one face in the plant, zero in the twin.',
        },
        {
            'path': FX + '/manifold_edge3.glb',
            'generated': MAKER_RECIPE + ' --defect manifold_edge3: add a third face sharing one '
            'existing edge on the left flank (a fin), so that edge is used by three faces.',
            'verified': False,
            'blocks': ['manifold'],
            'how_to_verify': 'The plant is still CLOSED (no boundary edge) — that is the whole point: '
            'a checker must tell this apart from manifold_hole, and trimesh answers '
            'both with one bool.',
        },
        {
            'path': FX + '/manifold_pinch.glb',
            'generated': MAKER_RECIPE + ' --defect manifold_pinch: merge two vertices from separate '
            'shells into one, so two cones meet at a single vertex.',
            'verified': False,
            'blocks': ['manifold'],
            'how_to_verify': 'Every EDGE of the plant is still 2-manifold and the mesh is still '
            'closed. This fixture is only a fixture if both of those hold — it exists '
            'to catch the check that is skipped because it needs a per-vertex '
            'link-graph traversal rather than an edge histogram.',
        },
        {
            'path': FX + '/selfint_arm_trunk.glb',
            'generated': MAKER_RECIPE + ' --defect selfint_arm_trunk: rotate the left forearm inward '
            'until it penetrates the trunk by 40 mm.',
            'verified': False,
            'blocks': ['selfint'],
            'how_to_verify': 'The plant is watertight, edge- and vertex-manifold, correctly wound and '
            'has no degenerate face — it passes every topological check and is '
            'unusable. If it fails any of those, it is not measuring self-'
            'intersection alone. Confirm the penetration depth is 40 mm +- 5.',
        },
        {
            'path': FX + '/normals_flipped.glb',
            'generated': MAKER_RECIPE + ' --defect normals_flipped: reverse the winding of the head shell only.',
            'verified': False,
            'blocks': ['normals'],
            'how_to_verify': "The head shell's signed volume is negative in the plant and positive in "
            'the twin, and the winding within that shell is CONSISTENT (an '
            'inconsistently wound shell is a different defect and makes '
            'integrity._check_outward refuse rather than answer).',
        },
        {
            'path': FX + '/degenerate_faces.glb',
            'generated': MAKER_RECIPE + ' --defect degenerate_faces: collapse twelve triangles to zero '
            'area on the back, and repeat one vertex in one further face.',
            'verified': False,
            'blocks': ['degenerate'],
            'how_to_verify': 'Exactly 13 bad faces in the plant, 0 in the twin, and the face count '
            'otherwise identical between the pair.',
        },
        {
            'path': FX + '/uv_overlap_island.glb',
            'generated': MAKER_RECIPE + ' --defect uv_overlap_island: translate the left-forearm UV '
            'island onto the right-forearm island, 8 per cent of face area overlapping.',
            'verified': False,
            'blocks': ['uv_overlap'],
            'how_to_verify': "Both plant and twin keep the base body's MIRRORED islands as authored — "
            'the twin is what proves a checker does not call a deliberate mirror an '
            'overlap. Confirm the overlap share is 0.08 +- 0.01 in the plant.',
        },
        {
            'path': FX + '/scale_10x.glb',
            'generated': MAKER_RECIPE + ' --defect scale_10x: scale the whole body by 10 about the '
            'origin, so stature reads 17.50 m.',
            'verified': False,
            'blocks': ['scale_check'],
            'how_to_verify': 'Stature 17.50 m in the plant, 1.750 m in the twin, and the GLB scene '
            'scale and unit tag IDENTICAL in both (otherwise this is the units '
            'fixture under another name).',
        },
        {
            'path': FX + '/export_z_up.glb',
            'generated': MAKER_RECIPE + ' --defect export_z_up: export with the up axis set to Z '
            'instead of Y, leaving the vertices alone.',
            'verified': False,
            'blocks': ['export'],
            'how_to_verify': "The MEASURED vertical extent of the plant is ~0.39 m (the body's depth) "
            'rather than 1.750 m — that is the observable geom/body_plates.py:227 '
            'raises on, and reading the node rotation instead would report the '
            "importer's own conversion and prove nothing.",
        },
        {
            'path': FX + '/units_centimetres.glb',
            'generated': MAKER_RECIPE + ' --defect units_centimetres: export with the scene unit scale '
            'set to centimetres, so a 1.750 m body writes 175 units.',
            'verified': False,
            'blocks': ['units'],
            'how_to_verify': 'The plant reads 175 m and the twin 1.750 m, and the ORIENTATION is +Y up '
            'in both — a fixture that is both Z-up and mis-scaled cannot tell the two '
            'columns apart.',
        },
        {
            'path': FX + '/material_dropped.glb',
            'generated': MAKER_RECIPE + ' --defect material_dropped: export with materials stripped, '
            'leaving one default grey.',
            'verified': False,
            'blocks': ['material_export'],
            'how_to_verify': "The twin carries the base body's named skin and eye materials and the "
            'plant carries exactly one unnamed default; the geometry is identical '
            'between the pair.',
        },
    ],
    'budget': {
        'calls': 90,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'a mesh check is numpy and trimesh over a vertex array; no language model is called anywhere on this step',
        'minutes': 45,
        'gpu_minutes': 0,
        'operator_minutes': 55,
        'note': (
            'DOMAIN: 15 planted fixtures + 15 clean twins = 30 meshes, each run 3 times = 90 check calls. The '
            'expensive one is the exact triangle-pair self-intersection test over a ~14k-face body — broadphase '
            'then exact, chunked at 250k pairs — at roughly 20 s a mesh; everything else is seconds. Call it '
            '45 min of CPU wall per row, 0 GPU (integrity is numpy, body_metrics is MediaPipe on CPU capped at '
            '20 of 24 cores per feedback_cpu_core_cap). SHARED BANK: the ten Builds bands are na for a checker '
            '(132 subjects x 3 seeds = 396 builds NOT spent, the single largest saving on this sheet); what '
            'remains of the bank is the capacity ladders, space, attributes and the 53 prompt columns, and for a '
            "service row with no prompt most of those land on the bank's own exemptions — budget ~20 further "
            'calls, included above. OPERATOR: 13 explains_mesh report reads x 3 repeats = 39 blind decisions, '
            'plus ~70 bank decisions on what survives = ~110 x 30 s = ~55 min per row. PLUS a ONE-TIME cost the '
            'rows do not carry: writing make_planted.py and verifying all 15 pairs by hand in Blender, '
            'realistically 4-6 hours, and until that is done every column of this step is untested. No '
            'claude_cli or anthropic_api row here, so the shared Claude week is untouched.'
        ),
    },
    'notes': [
        'A checker is graded on a PAIR. Recall on the plant without 0 false alarms on the twin is '
        'not a result: a checker that fails everything has perfect recall and no value.',
        'The clean twins are load-bearing fixtures in their own right. A twin with an accidental '
        'defect silently turns every column of this step into a false-alarm failure, which is why '
        'the maker script must write the twin BEFORE applying the plant, from the same loaded body.',
        'manifold carries three plants (hole, edge-in-three-faces, pinch vertex) and a state_rule '
        'of yes 1.0 / partial 0.34, so a row that catches one of the three reads partial rather '
        'than yes. This is the geom/anthro/integrity.py finding made into a threshold: a body mesh '
        'routinely passes three of these and fails the fourth.',
        "LIMITATION, recorded rather than hidden: the geometry bank's Capacity, Space & relation "
        'and Attributes bands are phrased for a builder and are left to the bank on this step. They '
        "are the weakest cells on this sheet. Overriding a validated shared bank from one step's "
        'module would stop the bank meaning the same thing in every step, so the honest move is to '
        'say so here and fix it in the bank if the house agrees.',
        'automated and blocks are wiring, not probes, and are graded assumed: they are facts about '
        'geom/anthro/gates.py, not about any mesh. A check whose failure is a WARNING rather than a '
        'block reads partial on `blocks` — gates.py rule 2 makes four "obvious" ordering assertions '
        'warnings because they are violated by real people.',
    ],
}
