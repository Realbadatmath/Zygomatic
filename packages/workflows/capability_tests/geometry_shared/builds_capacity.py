# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geometry_shared.builds_capacity — the Builds band (one probe per subject) and Capacity: ladders whose answer is a COUNT.

Verbatim from the former geometry_shared.py, lines 1215-1612.
"""

from __future__ import annotations

from .constants import COND_BUILD
from .subjects_people_body import SUBJECTS

# ── the Builds band: one probe per subject, built from the table ───────────────────────────
BUILD_STATE_RULE = {'yes': 1.0, 'partial': 0.67}
BUILD_STATE_NOTE = (
    'Three seeds. yes needs all three to pass, partial two of three — a subject a model gets '
    'right one time in three is not a capability, it is luck. The mechanical checks are a VETO '
    '(a build that fails manifold, self-intersection, shell count, bbox or up-axis is a no '
    "whatever the sheet looks like); on top of that the operator's blind yes is required, "
    'because no local VLM judges fused parts (defect bench 2026-09-27: 2/8 on fused fingers).'
)

PROBES = []

for _cid, (_label, _prompt, (_smin, _smax), (_axis, _lo, _hi), _extras) in SUBJECTS.items():
    _checks = [
        {'check': 'build_succeeds', 'when': 'report'},
        {'check': 'mesh_manifold', 'when': 'glb'},
        {'check': 'mesh_no_self_intersection', 'max': 0.0, 'when': 'glb'},
        {'check': 'mesh_shell_count', 'min': _smin, 'max': _smax, 'when': 'glb'},
        {'check': 'bbox_dims_m', 'axis': _axis, 'min': _lo, 'max': _hi, 'when': 'glb'},
        {'check': 'glb_up_axis', 'when': 'glb'},
        {'check': 'mesh_tris_min', 'min': 200, 'when': 'glb'},
        {'check': 'mesh_degenerate_max', 'max': 0.01, 'when': 'glb'},
        {'check': 'has_uv', 'overlap': 0.2, 'when': 'glb'},
        {'check': 'material_count_min', 'min': 1, 'when': 'glb'},
    ]
    _checks += list(_extras or [])
    _checks.append(
        {
            'check': 'operator',
            'when': 'sheet',
            'question': f'Is this a usable {_label} — the right parts present, nothing fused into its '
            f'neighbour, and plausible from all four views? yes/no',
        }
    )
    PROBES.append(
        {
            'id': 'geo_' + _cid,
            'title': f'builds {_label}',
            'feeds': [_cid],
            'inputs': {
                'prompt': _prompt,
                'image': f'capability_tests/fixtures/geometry/subjects/{_cid}.png',
                'library_query': _label,
            },
            'conditions': COND_BUILD,
            'checks': _checks,
            'grade': 'measured',
            'state_rule': BUILD_STATE_RULE,
            'state_note': BUILD_STATE_NOTE,
            'transport_variant': {
                'service': 'text-in rows get `prompt`; an image-conditioned row (Direct3D-S2) gets '
                '`image` and never a paraphrase of the prompt.',
                'blender': 'a headless builder takes no prompt: the row is driven by its own script on '
                'the subject id, and the id is the whole input. Checks unchanged.',
                'library': 'a LIBRARY row builds nothing. Replace every mesh check with '
                "library_has(min=1, terms=the subject label) over the library's own assets, "
                'then run the GLB checks on the item the library returns.',
                'claude_cli': 'arch_assistant.py builds by writing a Blender script; the prompt is the '
                "input and the script's GLB is the build. Checks unchanged.",
            },
        }
    )

del _cid, _label, _prompt, _smin, _smax, _axis, _lo, _hi, _extras, _checks


def _probe(pid, title, feeds, checks, inputs, cond=None, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': inputs,
        'conditions': dict(cond or COND_BUILD),
        'checks': checks,
        'grade': 'measured',
    }
    p.update(kw)
    return p


def _op(question):
    return {'check': 'operator', 'question': question, 'when': 'sheet'}


# ── Capacity: ladders whose answer is a COUNT ─────────────────────────────────────────────
# Every capacity probe climbs its ladder until a rung fails on two of three seeds, and the
# recorded answer is the LAST rung that passed. `unit: count` tells the hub to print the number
# rather than yes/no. The cell's state is yes when the count reaches `good`, partial at `some`.
CAP_NOTE = (
    'Climb the rungs in order on seeds [11, 12, 13]. A rung passes when its checks pass on at '
    'least two of the three seeds. The answer is the highest rung that passed, written as a '
    'count; the first failed rung stops the climb (no skipping ahead to a lucky rung).'
)

PROBES += [
    _probe(
        'geo_cap_people',
        'how many separate people before they fuse',
        ['cap_people'],
        [
            {'check': 'mesh_shell_count', 'min': 'rung', 'max': 'rung*8', 'when': 'glb'},
            {'check': 'person_count', 'n': 'rung', 'when': 'sheet'},
            {'check': 'mesh_no_self_intersection', 'max': 0.0, 'when': 'glb'},
            _op(
                'Count the standing people. Are there exactly N, each a whole separate body with no '
                'limb merged into a neighbour? yes/no — N is printed above the sheet.'
            ),
        ],
        {
            'prompt': 'N standing adults on flat ground, one metre apart in a row, plain period '
            'clothing, none touching another. N separate figures.'
        },
        ladder=[1, 2, 3, 5, 8, 12],
        unit='count',
        ladder_note=CAP_NOTE,
        state_rule={'yes': 0.8, 'partial': 0.4},
        state_note='yes at 5 or more separate people, partial at 2-4, no at 1 or none.',
    ),
    _probe(
        'geo_cap_named',
        'how many distinguishable named people',
        ['cap_named'],
        [
            {'check': 'face_identity_min', 'views': 'pairwise', 'max': 0.35, 'distinct': True, 'when': 'sheet'},
            {'check': 'mesh_shell_count', 'min': 'rung', 'max': 'rung*8', 'when': 'glb'},
            _op(
                'Are the N people visibly different individuals — different faces, builds and hair, '
                'not one body repeated? yes/no'
            ),
        ],
        {
            'prompt': 'N standing adults in a row, one metre apart: each a different age, build, hair '
            'and face, plain period clothing. N separate figures.'
        },
        ladder=[1, 2, 3, 5],
        unit='count',
        ladder_note=CAP_NOTE,
        state_note='ArcFace cosine between the faces must stay BELOW 0.35 for every pair — above '
        'that the row is building one person N times, which is the failure this column '
        'exists to catch. The operator confirms; the cosine vetoes.',
    ),
    _probe(
        'geo_cap_faces',
        'how many faces stay correct at once',
        ['cap_faces'],
        [
            {'check': 'person_count', 'n': 'rung', 'when': 'sheet'},
            {'check': 'mesh_part_names', 'terms': ['head'], 'when': 'glb'},
            _op(
                'Look at each face in turn. Do ALL N have two eyes, one nose and one mouth in the '
                'right places, with no melted or doubled features? yes/no'
            ),
        ],
        {
            'prompt': 'N adult heads and necks in a row, thirty centimetres apart, all facing forward, '
            'mouths closed, eyes open, no hair. N separate heads.'
        },
        ladder=[1, 2, 3, 5, 8],
        unit='count',
        ladder_note=CAP_NOTE,
    ),
    _probe(
        'geo_cap_hands',
        'how many hands stay correct at once',
        ['cap_hands'],
        [
            {'check': 'hand_landmarks', 'hands': 'rung', 'fingers': 5, 'views': ['0'], 'when': 'sheet'},
            {'check': 'mesh_shell_count', 'min': 'rung', 'max': 'rung*4', 'when': 'glb'},
            _op(
                'Count the fingers on every hand. Do ALL N hands have exactly five separate fingers, '
                'none fused and none extra? yes/no'
            ),
        ],
        {
            'prompt': 'N human hands in a row, ten centimetres apart, each open with the palm forward '
            'and the five fingers spread, each cut flat at the wrist.'
        },
        ladder=[1, 2, 4, 6, 8],
        unit='count',
        ladder_note=CAP_NOTE,
        state_note='MediaPipe hand_landmarker decides the finger count; the operator confirms '
        'fusing, which the landmarker misses. Both must pass.',
    ),
    _probe(
        'geo_cap_objects',
        'how many separate objects before they merge',
        ['cap_objects'],
        [
            {'check': 'mesh_shell_count', 'min': 'rung', 'max': 'rung*6', 'when': 'glb'},
            {'check': 'mesh_no_self_intersection', 'max': 0.0, 'when': 'glb'},
            _op(
                'Count the barrels. Are there exactly N, each whole and standing clear of its '
                'neighbours with daylight between them? yes/no'
            ),
        ],
        {
            'prompt': 'N oak barrels standing upright in a row on flat ground, twenty centimetres '
            'apart, none touching another. N separate barrels.'
        },
        ladder=[1, 3, 5, 8, 12, 20],
        unit='count',
        ladder_note=CAP_NOTE,
        state_note='yes at 8 or more, partial at 3-5. A row that fuses two barrels at N=3 cannot '
        'build a laid table, whatever a single barrel looks like.',
    ),
    _probe(
        'geo_cap_words',
        'how many carved words stay legible',
        ['cap_words'],
        [
            {'check': 'sheet_ocr_present', 'terms': 'rung_words', 'when': 'sheet'},
            _op(
                'Read the board aloud. Does it say exactly the words printed above the sheet, in that '
                'order, with no missing or invented letters? yes/no'
            ),
        ],
        {
            'prompt': 'A flat oak board with the words <WORDS> carved into it as raised capital '
            'letters on one line, nothing else on the board.',
            'word_bank': [
                'HAVEN',
                'KADE',
                'TOUW',
                'VAT',
                'ZEIL',
                'ANKER',
                'MAST',
                'ROER',
                'WERF',
                'SCHIP',
                'LOODS',
                'KAAP',
                'BAAK',
                'PALEN',
                'BRUG',
                'SLUIS',
            ],
        },
        ladder=[1, 2, 4, 8, 16],
        unit='count',
        ladder_note=CAP_NOTE + ' <WORDS> is the first `rung` entries of word_bank, joined by single spaces, verbatim.',
        state_note='tesseract OCR of the turntable sheet decides; the operator confirms, because '
        'OCR forgives a letter a reader would not.',
    ),
    _probe(
        'geo_cap_digits',
        'how many carved digits stay correct',
        ['cap_digits'],
        [
            {'check': 'sheet_ocr_equals', 'text': 'rung_digits', 'when': 'sheet'},
            _op('Read the number on the board. Is it exactly the number printed above the sheet? yes/no'),
        ],
        {
            'prompt': 'A flat oak board with the number <DIGITS> carved into it as raised numerals on '
            'one line, nothing else on the board.',
            'digit_bank': '16714928',
        },
        ladder=[1, 2, 3, 4, 6, 8],
        unit='count',
        ladder_note=CAP_NOTE + ' <DIGITS> is the first `rung` characters of digit_bank, verbatim.',
    ),
    _probe(
        'geo_cap_animals',
        'how many animals stay correct at once',
        ['cap_animals'],
        [
            {'check': 'mesh_shell_count', 'min': 'rung', 'max': 'rung*8', 'when': 'glb'},
            {'check': 'mesh_no_self_intersection', 'max': 0.0, 'when': 'glb'},
            _op(
                'Count the sheep and count their legs. Are there exactly N sheep, each with four '
                'separate legs, none merged into another? yes/no'
            ),
        ],
        {
            'prompt': 'N sheep standing on flat ground, one metre apart, all facing the same way, '
            'heads up, none touching another. N separate animals.'
        },
        ladder=[1, 2, 3, 5, 8],
        unit='count',
        ladder_note=CAP_NOTE,
    ),
    _probe(
        'geo_cap_prompt_terms',
        'how many prompt terms land in the build',
        ['cap_prompt_terms'],
        [
            {'check': 'mesh_part_names', 'terms': 'rung_terms', 'when': 'glb'},
            _op(
                'The terms asked for are printed above the sheet. Count how many are actually present '
                'in the model. Are ALL of them there? yes/no'
            ),
        ],
        {
            'prompt': 'A quayside scene containing exactly these things and nothing else: <TERMS>. '
            'Each thing a separate object at real scale.',
            'term_bank': [
                'a barrel',
                'a coil of rope',
                'a wooden crate',
                'a mooring bollard',
                'a lantern on a post',
                'a handcart',
                'a fish basket',
                'a plank gangway',
                'a stack of three planks',
                'a water trough',
                'an anchor',
                'a sack',
                'a ladder',
                'a bucket',
                'a stone kerb',
                'a broom',
                'a net on a frame',
                'a pair of oars',
                'a chain',
                'a tar bucket',
            ],
        },
        ladder=[5, 10, 20, 40, 60],
        unit='count',
        ladder_note=CAP_NOTE + ' <TERMS> is term_bank '
        'cycled to `rung` entries (the bank repeats with a numbered suffix past 20), joined by '
        'commas, verbatim. The answer is the count of terms PRESENT at the highest passing rung.',
    ),
    _probe(
        'geo_cap_res',
        'the triangle budget before detail collapses',
        ['cap_res'],
        [
            {'check': 'mesh_tris_max', 'max': 'rung', 'when': 'glb'},
            {'check': 'mesh_tris_min', 'min': 'rung/4', 'when': 'glb'},
            {'check': 'mesh_manifold', 'when': 'glb'},
            {'check': 'mesh_no_self_intersection', 'max': 0.0, 'when': 'glb'},
            _op(
                'At this triangle budget, are the carved letters on the barrel lid still readable and '
                'the hoops still distinct from the staves? yes/no'
            ),
        ],
        {
            'prompt': 'One oak barrel ninety centimetres tall with five iron hoops and the word VAT '
            'carved into its lid, standing upright.'
        },
        ladder=[5000, 20000, 100000, 500000, 2000000],
        unit='count',
        ladder_note=CAP_NOTE + ' The rung is the triangle budget the row is asked for (a decimation '
        "target where the row has one, otherwise the row's own density setting nearest the rung).",
        state_note='The answer is the HIGHEST budget the row can actually deliver without breaking '
        'manifoldness — and separately, the lowest at which the lettering survives. Both '
        'numbers go in the trial; the cell shows the highest clean budget.',
    ),
    _probe(
        'geo_cap_panels',
        'how many turntable views a build survives',
        ['cap_panels'],
        [
            {'check': 'sheet_cells_clean', 'share': 1.0, 'when': 'sheet'},
            _op(
                'Every view on this sheet shows the same handcart from a different angle. Is the cart '
                'correct and complete in EVERY view, with no missing or collapsed side? yes/no'
            ),
        ],
        {
            'prompt': 'One two-wheeled wooden handcart one and a half metres long with two spoked '
            'wheels, a flat bed and two shafts, standing level on flat ground.'
        },
        ladder=[4, 9, 16, 25],
        unit='count',
        ladder_note=CAP_NOTE + ' The rung is the number of evenly spaced views rendered onto one '
        'sheet (4, 9, 16 or 25 cells, always the same lens and lighting).',
        state_note='A generator that only works from the front fails at 9 views. The answer is the '
        'largest view count where every cell is still a correct cart.',
    ),
    _probe(
        'geo_cap_cells_clean',
        'how many sheet cells are clean at the largest view count',
        ['cap_cells_clean'],
        [
            {'check': 'sheet_cells_clean', 'share': 0.8, 'when': 'sheet'},
            _op(
                'Count the views on this sheet in which the cart is correct and complete. Is that '
                'count at least the number printed above the sheet? yes/no'
            ),
        ],
        {
            'prompt': 'One two-wheeled wooden handcart one and a half metres long with two spoked '
            'wheels, a flat bed and two shafts, standing level on flat ground.'
        },
        ladder=[16],
        unit='count',
        ladder_note='One 16-view sheet per seed. The answer is the COUNT of clean cells out of 16, '
        'averaged over the three seeds and rounded down — not a pass rate.',
        state_rule={'yes': 0.8, 'partial': 0.4},
        state_note='yes at 13 or more clean cells of 16, partial at 7-12. This is the column that '
        'separates a generator with one good angle from one that models an object.',
    ),
]
