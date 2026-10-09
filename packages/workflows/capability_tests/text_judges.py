# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Anachronism and lettering judges (text_judges). 2026-09-30.

Question the sheet asks: can a model catch an anachronism or bad lettering in a frame? The
sheet's own note says what justifies this step's shape — *two measured negatives on the same
idea, moondream 34/40 false alarms and Qwen3-VL 2/8 recall on one global question, are what
justify the per-slot decomposition*. Both of those rows are therefore in this test as
`retired` with their receipt written into the skip reason, and the live rows are the
decomposed gates that replaced them.

The shape of the test
---------------------
ONE fixture set built by a script, not by a model: 12 modern objects pasted into 12 approved
1671 stills (`capability_tests/fixtures/text_judges/plant.py`), each still ALSO kept
un-pasted as its clean twin, plus 5 variants of one painted sign board. So `recall` and
`false` are measured on the SAME twelve pictures — a gate that flags everything scores 1.00
on recall and 0.00 on false, and the pair is what the moondream receipt says to watch for.
The paste box of every plant is written in this module in 0-1 fractions, so a flag's bbox
(era_gate returns 0-1000 coords) can be checked against the plant's location and not merely
against "something was flagged in this frame". That is the difference between catching the
anachronism and catching a lucky alarm.

No `operator` check appears in this module. Every one of the 16 probed columns is decided by
an overlap, a share or a string comparison against a key the paste script itself wrote.

What is blocked and why
-----------------------
All 16 probed columns are BLOCKED: the plants, the clean twins and the signs do not exist on
disk. The paste script is written and pinned here; nothing in this test executes it, renders
anything or calls a model. `decompose`, `crop_based` (wiring), `word_lock` (a receipt) and
`global` (na) need no fixture and are answered now.

The recognition bands are `na`, and on the text subjects that is not modesty
--------------------------------------------------------------------------
The judge bank scores the `Sees: Text & number` subjects with `ocr_equals`, and its own
engine field says that check IS the typography OCR judge. Running it on `ocr_judge` or
`typography` would be grading a row against itself. The other bands are na for the plainer
reason: these three rows are GATES with fixed entry points — a frame and a prompt in, flags
out — and there is no way to hand them the bank's 132 subject questions without rewriting
them into a different program. The subject-recognition capability of the underlying Qwen3-VL
belongs to a vlm_judges row; claiming it here would be counting one model as two.
"""

from __future__ import annotations

# ── check kinds this module adds to capability_tests.__init__.CHECK_KINDS ─────────────
CHECK_KINDS = {
    'gate_flags_planted': "over the planted frames whose `class` matches: the share on which the row returns a CRITICAL flag whose bbox (era_gate 0-1000 coords, rescaled) overlaps the plant box recorded by plant.py at IoU >= `iou` AND whose written reason contains the plant's `what`; passes when the share is >= `min`. A flag somewhere else in the frame does not count.",
    'gate_false_alarm_max': 'over the clean twins (the same stills with nothing pasted in): the share on which the row returns ANY critical flag; passes when that share is <= `max`',
    'items_match_prompt': "for each slot, the gate's derived item list is compared with the checkable nouns of that slot's render prompt: every noun in the fixture key appears as an item, and every item is supported by a noun of the prompt; passes when the share of slots where BOTH hold is >= `min`",
    'gate_rejects_lettering': 'over the sign fixtures whose fault is `what` (spelling|script|language|numerals): the share the row REJECTS with a written reason naming that fault; passes at >= `min`. A rejection with the wrong reason counts as a miss, so a row that rejects every sign scores 0 on three of the four faults.',
    'ocr_reads_exact': "the row's read-back of the sign region equals the fixture's `text` key after case folding and whitespace collapse, on >= `min` of the repeats; the point is that a faulty string read back EXACTLY is mechanically catchable by comparison with the prompt, while a string the reader silently corrects is not",
}

FXT = 'capability_tests/fixtures/text_judges'
MANIFEST = FXT + '/MANIFEST.json'
PLANTED = FXT + '/planted'
CLEAN = FXT + '/clean'
SIGNS = FXT + '/signs'

# The 12 plants, verbatim. `box` is the paste rectangle in 0-1 fractions of the still, which
# plant.py writes into MANIFEST.json and every probe scores a flag's bbox against.
PLANTS = (
    {
        'id': 'veh_bicycle',
        'class': 'vehicles',
        'what': 'bicycle',
        'box': (0.61, 0.58, 0.79, 0.86),
        'from': 'a CC0 photograph of a black roadster bicycle, cut out and desaturated to the plate',
    },
    {
        'id': 'veh_car',
        'class': 'vehicles',
        'what': 'car',
        'box': (0.05, 0.62, 0.34, 0.83),
        'from': "a CC0 photograph of a parked hatchback, cut out, scaled to the quay's perspective",
    },
    {
        'id': 'wir_powerline',
        'class': 'wires',
        'what': 'power line',
        'box': (0.00, 0.08, 1.00, 0.22),
        'from': 'four straight dark strokes drawn across the sky by plant.py, 2 px at 1024, with a slight catenary sag',
    },
    {
        'id': 'wir_streetlamp',
        'class': 'wires',
        'what': 'streetlight',
        'box': (0.72, 0.10, 0.86, 0.66),
        'from': 'a CC0 photograph of a steel street lamp, cut out',
    },
    {
        'id': 'wir_wirefence',
        'class': 'wires',
        'what': 'wire fence',
        'box': (0.28, 0.66, 0.74, 0.88),
        'from': 'a chain-link lattice drawn by plant.py at 40 % opacity over the cobbles',
    },
    {
        'id': 'clo_zip',
        'class': 'clothing_era',
        'what': 'zip',
        'box': (0.44, 0.38, 0.50, 0.58),
        'from': 'a CC0 macro photograph of a metal zip, cut out and laid down the front of the doublet',
    },
    {
        'id': 'clo_sneaker',
        'class': 'clothing_era',
        'what': 'sneaker',
        'box': (0.40, 0.84, 0.56, 0.95),
        'from': 'a CC0 photograph of a white trainer, cut out, one foot only',
    },
    {
        'id': 'hai_modern',
        'class': 'hair_era',
        'what': 'modern haircut',
        'box': (0.42, 0.10, 0.60, 0.30),
        'from': "a CC0 portrait crop of a faded undercut, cut out and matched to the sitter's head box",
    },
    {
        'id': 'obj_wristwatch',
        'class': 'objects_era',
        'what': 'wristwatch',
        'box': (0.33, 0.52, 0.41, 0.59),
        'from': 'a CC0 photograph of a steel wristwatch, cut out, sized to the wrist in the plate',
    },
    {
        'id': 'obj_bucket',
        'class': 'objects_era',
        'what': 'plastic bucket',
        'box': (0.14, 0.72, 0.29, 0.90),
        'from': 'a CC0 photograph of a blue plastic bucket, cut out',
    },
    {
        'id': 'obj_poster',
        'class': 'objects_era',
        'what': 'printed poster',
        'box': (0.66, 0.30, 0.84, 0.58),
        'from': 'a full-colour offset-printed poster rendered by plant.py from a CC0 photograph, pasted flat on the plank wall',
    },
    {
        'id': 'obj_clock',
        'class': 'objects_era',
        'what': 'digital clock',
        'box': (0.52, 0.22, 0.66, 0.33),
        'from': 'a seven-segment red 08:41 drawn by plant.py on a black rectangle',
    },
)

# One sign board, five variants. The base is the only historically correct one; each of the
# other four carries exactly ONE fault, so a rejection can be read as catching THAT fault.
SIGNS_TABLE = (
    {
        'id': 'sign_base',
        'fault': None,
        'text': 'KATTENBURG WERF DE ZEEHOND ANNO 1671',
        'face': 'DejaVuSerif-Bold',
        'note': 'the correct board: six words, period serif, Dutch, Arabic numerals as used on 17th-century Amsterdam yard boards. reads_text is scored here.',
    },
    {
        'id': 'sign_spelling',
        'fault': 'spelling',
        'text': 'KATTENBERG WERF DE ZEEHOND ANNO 1671',
        'face': 'DejaVuSerif-Bold',
        'note': 'one letter: KATTENBURG -> KATTENBERG. Everything else identical to the base.',
    },
    {
        'id': 'sign_script',
        'fault': 'script',
        'text': 'KATTENBURG WERF DE ZEEHOND ANNO 1671',
        'face': 'DejaVuSans-Bold',
        'note': 'the same six words in a geometric sans-serif, a typeface that does not exist in 1671. The STRING is correct, so a row that only reads text cannot catch this one and is na.',
    },
    {
        'id': 'sign_language',
        'fault': 'language',
        'text': 'KATTENBURG SHIPYARD THE SEAL ANNO 1671',
        'face': 'DejaVuSerif-Bold',
        'note': 'the Dutch words replaced by their English equivalents; same face, same numerals.',
    },
    {
        'id': 'sign_numerals',
        'fault': 'numerals',
        'text': 'KATTENBURG WERF DE ZEEHOND ANNO 2026',
        'face': 'DejaVuSerif-Bold',
        'note': '1671 -> 2026. One field, four characters.',
    },
)

COND = {
    'repeats': 3,
    'seed': 11,
    'temperature': 0.0,
    'max_tokens': 80,
    'resolution': '1024 px long side as stored; era_gate tiles it 3x2 and ENLARGES each tile, which is the method under test',
    'device': 'Qwen3-VL through vlm_inspector on the resident boundary model; typography_ocr and its OCR are CPU',
    'note': (
        '3 repeats at temperature 0 is not waste: the 2026-08-25 receipts are about a judge that answers '
        'differently on the same picture, and a row whose flags move between identical calls is a row whose '
        'recall number cannot be read. The FIRST repeat is what `first_take` reads.'
    ),
}

DOMAIN = (
    'decompose',
    'global',
    'word_lock',
    'crop_based',
    'prompt_derived',
    'recall',
    'false',
    'vehicles',
    'wires',
    'clothing_era',
    'hair_era',
    'objects_era',
    'reads_text',
    'spelling',
    'script_era',
    'language_frame',
    'numerals_frame',
)

ERA = ['era_gate']
LETTER = ['typography', 'ocr_judge']

# Which rows can answer each column. Everything else gets a written `na` built from the two
# tables below. `global` is a step-level na and `word_lock` a sheet-wide receipt, so neither
# appears here.
CAN = {
    'decompose': ERA,
    'crop_based': ERA,
    'prompt_derived': ERA,
    'recall': ERA,
    'false': ERA + LETTER,
    'vehicles': ERA,
    'wires': ERA,
    'clothing_era': ERA,
    'hair_era': ERA,
    'objects_era': ERA,
    'reads_text': LETTER,
    'spelling': LETTER,
    'script_era': ['typography'],
    'language_frame': LETTER,
    'numerals_frame': LETTER,
}

ROW_IS = {
    'era_gate': (
        'era_gate.py is the per-slot ANACHRONISM gate: it derives a checkable-object list from each S '
        'prompt and asks one atomic yes/no per item over 3x2 enlarged tiles'
    ),
    'typography': (
        'the documentary typography gate judges LETTERING only — typography_ocr.judge() and then the '
        'Qwen3-VL documentary_typography checklist, in that order'
    ),
    'ocr_judge': (
        'typography_ocr.read_lettering is a mechanical OCR reader: characters, a confidence and a box out, '
        'and no question put to any model'
    ),
}

COL_NEEDS = {
    'decompose': 'this column asks whether the judgement is broken into one question per prompt slot',
    'crop_based': 'this column asks whether the question is put to a crop rather than to the whole frame',
    'prompt_derived': 'this column asks whether the questions are derived from the render prompt',
    'recall': 'this column asks how many of the twelve planted modern OBJECTS are flagged',
    'vehicles': 'this column asks whether a modern vehicle pasted into a 1671 still is flagged',
    'wires': 'this column asks whether a wire, pole or cable pasted into a 1671 still is flagged',
    'clothing_era': 'this column asks whether modern clothing pasted into a 1671 still is flagged',
    'hair_era': 'this column asks whether a modern haircut pasted into a 1671 still is flagged',
    'objects_era': 'this column asks whether a modern small object pasted into a 1671 still is flagged',
    'reads_text': 'this column asks for the lettering in the frame to be read back',
    'spelling': 'this column asks for a misspelled word on a painted sign to be caught',
    'script_era': 'this column asks for a TYPEFACE that could not exist in 1671 to be caught',
    'language_frame': 'this column asks for a sign in the wrong language to be caught',
    'numerals_frame': 'this column asks for wrong numerals on a sign to be caught',
}


def _row_na(rid):
    return {c: f'{ROW_IS[rid]}, and {COL_NEEDS[c]}.' for c in DOMAIN if c in CAN and rid not in CAN[c]}


def _p(pid, title, col, checks, fixture, subset, rows=None, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': [col],
        'rows': list(rows or CAN[col]),
        'inputs': {'fixture': fixture, 'subset': subset, 'prompt': None},
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
    }
    p.update(kw)
    return p


def _class_probe(col, cls):
    named = [p for p in PLANTS if p['class'] == cls]
    return _p(
        f'planted_{cls}',
        f'Flags the planted {cls.replace("_era", "")}',
        col,
        [{'check': 'gate_flags_planted', 'class': cls, 'iou': 0.3, 'min': 0.9}],
        PLANTED,
        f'the {len(named)} planted frames of class {cls}: ' + ', '.join(p['what'] for p in named),
        state_note=(
            'the flag must land ON the plant (IoU >= 0.3 with the recorded paste box) and its written '
            'reason must name the object. A gate that flags the whole frame passes nothing here, which '
            'is the moondream failure mode made unscoreable.'
        ),
    )


PROBES = [
    _p(
        'prompt_derived',
        'The questions come from the prompt',
        'prompt_derived',
        [{'check': 'items_match_prompt', 'min': 0.9}],
        MANIFEST,
        'the 12 source slots, each with its render prompt and the operator-written list of checkable nouns',
        state_note=(
            "measured against the nouns the operator wrote down for each slot, not against era_gate's own "
            'output: an item the prompt does not support is as much a miss as a noun the gate dropped. '
            'derive_checks_offline is the keyword fallback and is scored in the same pass, so a Haiku outage '
            'shows as a lower share rather than as untested.'
        ),
    ),
    _p(
        'recall',
        'Catches the anachronisms present',
        'recall',
        [{'check': 'gate_flags_planted', 'iou': 0.3, 'min': 0.9}],
        PLANTED,
        'all 12 planted frames',
        state_note=(
            'the headline number, and it must be read beside `false` on the same twelve stills. run 2f1ffabb '
            'shipped 19 anachronisms, so a recall below 0.7 here is the receipt reproduced, not a surprise.'
        ),
    ),
    _p(
        'false',
        'Leaves correct frames alone',
        'false',
        [{'check': 'gate_false_alarm_max', 'max': 0.1}],
        CLEAN,
        'the 12 clean twins (era_gate) or the 36 clean frames of run 85f0659c (typography, ocr_judge)',
        state_note=(
            'moondream said yes on 34 of 40 clean frames — this column is where that shows. For the two '
            'lettering rows the standing receipt is FP 0 of 36 at conf >= 0.50, stable across conf 0.30-0.60, '
            'and this probe is that receipt re-measured rather than quoted.'
        ),
    ),
    _class_probe('vehicles', 'vehicles'),
    _class_probe('wires', 'wires'),
    _class_probe('clothing_era', 'clothing_era'),
    _class_probe('hair_era', 'hair_era'),
    _class_probe('objects_era', 'objects_era'),
    _p(
        'reads_text',
        'Reads the lettering',
        'reads_text',
        [{'check': 'ocr_equals', 'text': 'KATTENBURG WERF DE ZEEHOND ANNO 1671', 'engine': 'the row itself'}],
        SIGNS,
        'sign_base, the one correct board',
        state_note='six words on one board, read back exactly after case folding and whitespace collapse; the base sign carries no fault, so a miss here is a reading failure and nothing else',
    ),
    _p(
        'spelling_rejected',
        'Rejects the misspelling',
        'spelling',
        [{'check': 'gate_rejects_lettering', 'what': 'spelling', 'min': 0.9}],
        SIGNS,
        'sign_spelling',
        rows=['typography'],
        state_note='the reason must name the spelling, not merely reject the board: a row that rejects all five signs scores 1.00 on four columns it never understood, and naming the fault is what stops that',
    ),
    _p(
        'spelling_read',
        'Reads the misspelling back as painted',
        'spelling',
        [{'check': 'ocr_reads_exact', 'text': 'KATTENBERG WERF DE ZEEHOND ANNO 1671', 'min': 1.0}],
        SIGNS,
        'sign_spelling',
        rows=['ocr_judge'],
        state_note=(
            'a mechanical reader catches a misspelling by reading it EXACTLY and letting the comparison with '
            'the prompt do the catching. A reader that silently returns KATTENBURG has destroyed the evidence, '
            'which is why this is scored as an exact read and not as a rejection.'
        ),
    ),
    _p(
        'script_era',
        'Rejects the wrong typeface',
        'script_era',
        [{'check': 'gate_rejects_lettering', 'what': 'script', 'min': 0.9}],
        SIGNS,
        'sign_script — the correct string in a geometric sans-serif',
        state_note='the string is correct, so nothing mechanical in the text can fire; this is the one lettering column that needs the Qwen3-VL checklist half of the gate, and ocr_judge is na with that reason',
    ),
    _p(
        'language_rejected',
        'Rejects the wrong language',
        'language_frame',
        [{'check': 'gate_rejects_lettering', 'what': 'language', 'min': 0.9}],
        SIGNS,
        'sign_language',
        rows=['typography'],
        state_note='the reason must say the words are English on a Dutch yard board',
    ),
    _p(
        'language_read',
        'Reads the English board back as painted',
        'language_frame',
        [{'check': 'ocr_reads_exact', 'text': 'KATTENBURG SHIPYARD THE SEAL ANNO 1671', 'min': 1.0}],
        SIGNS,
        'sign_language',
        rows=['ocr_judge'],
        state_note='same reading as spelling: the exact string is the evidence the language is wrong',
    ),
    _p(
        'numerals_rejected',
        'Rejects the wrong numerals',
        'numerals_frame',
        [{'check': 'gate_rejects_lettering', 'what': 'numerals', 'min': 0.9}],
        SIGNS,
        'sign_numerals',
        rows=['typography'],
        state_note='the reason must name the year; a generic "text looks wrong" is a miss',
    ),
    _p(
        'numerals_read',
        'Reads 2026 back as painted',
        'numerals_frame',
        [{'check': 'ocr_reads_exact', 'text': 'KATTENBURG WERF DE ZEEHOND ANNO 2026', 'min': 1.0}],
        SIGNS,
        'sign_numerals',
        rows=['ocr_judge'],
        state_note='four characters; an OCR that reads 1671 because the rest of the board says 1671 fails this and should',
    ),
]

SEES_BANDS = [
    'Sees: People',
    'Sees: The body',
    'Sees: Food',
    'Sees: Damage & wear',
    'Sees: Text & number',
    'Sees: Objects',
    'Sees: Animals',
    'Sees: Nature & weather',
    'Sees: Built environment',
    'Sees: Clothing',
]
NAMES_BANDS = [b.replace('Sees:', 'Names:') for b in SEES_BANDS]
ASK_BANDS = [
    'Capacity',
    'Counting & quantity',
    'Space & relation',
    'Attributes',
    'Prompt: damage',
    'Prompt: clarity needed',
    'Prompt: limits',
    'Prompt: steering',
]

NOT_A_QUESTION_TAKER = {
    'reason': (
        'this row is a GATE with a fixed entry point — a frame (and, for era_gate, its render prompt) in, '
        "flags out — and there is no way to put the bank's own subject, counting, spatial, attribute or "
        'prompt-damage questions to it without rewriting it into a different program. On the text and number '
        'subjects there is a second, harder reason: the bank scores those with `ocr_equals` and its engine '
        'field says that check IS the typography OCR judge, so running it on these rows would be grading a row '
        'against itself. The subject-recognition capability of the underlying Qwen3-VL is a vlm_judges row; '
        'claiming it again here would count one model as two capabilities.'
    ),
    'bands': SEES_BANDS + NAMES_BANDS + ASK_BANDS,
}

TEST = {
    'step': 'text_judges',
    'version': '2026-09-30.1',
    'title': 'Twelve planted anachronisms with their clean twins, and one sign in five variants',
    'purpose': (
        'Measure whether a judge catches a modern object or bad lettering in a period frame, on a fixture '
        'set a script builds so recall and false alarms are read off the SAME twelve pictures — and keep the '
        'two rows that failed the global-question approach in the sheet with their receipts.'
    ),
    'include_shared': 'judge',
    'plants': PLANTS,
    'signs': SIGNS_TABLE,
    'rows': {
        'era_gate': {
            'transport': 'service',
            'where': (
                'era_gate.py — extract_checks (:333) with derive_checks_offline (:300) as the deterministic '
                "keyword fallback, build_items (:439) with scope 'tiles' at :451/:461/:467, tile_boxes (:485) "
                'and make_tiles (:503), then judge_frame (:582)'
            ),
            'model': 'Qwen3-VL through vlm_inspector, plus one claude-haiku extraction call per batch',
            'na': _row_na('era_gate'),
            'na_bands': NOT_A_QUESTION_TAKER,
            'budget': {
                'calls': 2820,
                'minutes': 130,
                'gpu_minutes': 125,
                'note': 'the only row that calls a model per tile: 24 frames x 6 tiles x ~2.5 items x 3 repeats plus 3 Haiku extraction calls, and Qwen3-VL holds the GPU throughout',
            },
            'note': 'the per-slot decomposition that replaced the two retired rows; every flag it returns carries a bbox in 0-1000 coords, which is what makes gate_flags_planted scoreable at all',
        },
        'moondream_era': {
            'transport': 'retired',
            'skip': (
                'retired 2026-08-25, superseded by the per-slot decomposition in era_gate.py. The receipt is why '
                'it is kept: asked ONE global anachronism question, moondream answered yes on 34 of 40 frames — '
                'a judge that flags 85 % of correct frames gates nothing, and no threshold recovers it. The row '
                'stays in the sheet so that number is on the record instead of being rediscovered.'
            ),
            'model': 'moondream2 (one global question)',
            'budget': {
                'calls': 0,
                'minutes': 0,
                'gpu_minutes': 0,
                'tokens_in': 0,
                'tokens_out': 0,
                'operator_minutes': 0,
                'note': 'retired: the runner skips the row and writes untested "retired" on every column, so it costs nothing',
            },
        },
        'qwen3vl_era': {
            'transport': 'retired',
            'skip': (
                'retired 2026-08-25 as a GLOBAL judge, superseded by era_gate.py which drives the same model per '
                'slot over enlarged tiles. The receipt: asked one global anachronism question at 1280 px, '
                'Qwen3-VL recalled 2 of 8 hard cases. The model is not the problem and is live inside the '
                "era_gate row — the one-question-per-frame method was, and this row is that method's record."
            ),
            'model': 'Qwen3-VL at 1280 px (one global question)',
            'budget': {
                'calls': 0,
                'minutes': 0,
                'gpu_minutes': 0,
                'tokens_in': 0,
                'tokens_out': 0,
                'operator_minutes': 0,
                'note': 'retired: the runner skips the row and writes untested "retired" on every column, so it costs nothing',
            },
        },
        'typography': {
            'transport': 'service',
            'where': (
                'the documentary typography gate: typography_ocr.judge() (:126) first, then the Qwen3-VL '
                'documentary_typography checklist — the order is pinned by '
                'scripts/test_documentary_stack.py::test_typography_judge_order'
            ),
            'model': 'typography_ocr (CPU OCR) + Qwen3-VL documentary_typography checklist',
            'na': _row_na('typography'),
            'na_bands': NOT_A_QUESTION_TAKER,
            'budget': {
                'calls': 120,
                'minutes': 8,
                'gpu_minutes': 6,
                'note': '5 signs plus 36 clean frames x 3 repeats through OCR at 0.58 s/frame, and the checklist half at ~2.7 s/frame on the GPU only where OCR found lettering',
            },
            'note': 'the only row that can answer script_era: the string is correct on sign_script, so the fault is visible to the checklist half and to nothing mechanical',
        },
        'ocr_judge': {
            'transport': 'service',
            'where': 'typography_ocr.read_lettering (:78), CPU, 0.58 s/frame',
            'model': 'the local OCR reader inside typography_ocr',
            'na': _row_na('ocr_judge'),
            'na_bands': NOT_A_QUESTION_TAKER,
            'budget': {
                'calls': 123,
                'minutes': 3,
                'gpu_minutes': 0,
                'note': '5 signs plus 36 clean frames x 3 repeats at 0.58 s/frame on the CPU; no GPU and no model call anywhere in the row',
            },
            'note': (
                'calibrated 2026-09-27 against Qwen3-VL over 48 frames of scholarly run 85f0659c (12 lettering, '
                '36 clean) at conf >= 0.50, box area >= 0.1 %, k >= 1: TP 12 FP 0 FN 0 TN 36, precision 1.00, '
                'recall 1.00, stable across conf 0.30-0.60. That receipt is what this test re-measures.'
            ),
        },
    },
    'probes': PROBES,
    'derive': {},
    'lookup': {
        'word_lock': {
            'grade': 'receipt',
            'unit': 'text',
            'from': 'the run 2f1ffabb post-mortem and the era_gate.py docstring that cites it',
            'requires': [
                "era_gate.py's own docstring: the gate exists because the previous guard policed WORDS in the prompt.",
                'run 2f1ffabb (the Black Death episode): the prompt contained NO banned word and the run shipped 19 '
                'anachronisms. Quote that sentence and the run id into the cell.',
                'the consequence, written as the answer: a word-level lock cannot be enough, because the anachronism '
                'enters through what the model DRAWS and not through what the prompt SAYS. This column is a lookup '
                'and not a probe because it is a settled receipt about a method, not a measurement of a row.',
            ],
            'note': (
                'sheet-wide on purpose: the answer is a property of the word-lock method, identical on all five '
                'rows, and re-measuring it would mean re-shipping 19 anachronisms.'
            ),
        },
    },
    'wiring': {
        'decompose': {
            'grade': 'assumed',
            'where': 'era_gate.py: extract_checks (:333), derive_checks_offline (:300), build_items (:439)',
            'how': (
                'read off the code path, never run. extract_checks makes ONE cheap Haiku call per batch that '
                'returns a checkable-object list per S prompt; derive_checks_offline is the deterministic keyword '
                'fallback for when that call is unavailable; build_items turns each object into one atomic yes/no '
                'item, and universal tells plus two content questions are appended. The sheet shows this as '
                '`assumed` because it is a reading of the program, and `prompt_derived` is the probe that tests '
                'whether the reading holds in practice.'
            ),
            'note': 'the two retired rows are the counterfactual: one question per frame is what 34/40 and 2/8 measure',
        },
        'crop_based': {
            'grade': 'assumed',
            'where': "era_gate.py: tile_boxes (:485), make_tiles (:503), scope 'tiles' at :451, :461, :467",
            'how': (
                "read off the code path. Every item whose scope is 'tiles' is asked of a 3x2 grid of ENLARGED "
                'tiles rather than of the frame, and each flag carries a bbox in 0-1000 coords so the answer can '
                'be put back on the frame. Enlargement is the point: a wristwatch is a handful of pixels in a '
                '1024 px frame and a readable object in an enlarged sixth of it.'
            ),
            'note': 'the 2/8 receipt was measured on the WHOLE frame at 1280 px, which is the comparison this column exists to record',
        },
    },
    'na': {
        'global': (
            'the one global question is precisely the approach this step retired, and this test records that '
            'rather than re-running it: moondream answered yes on 34 of 40 clean frames and Qwen3-VL recalled '
            '2 of 8 hard cases, both asked globally, both rows kept here as `retired` with those numbers in '
            'their skip reason. The three live rows do not have a global mode to measure — era_gate asks per '
            'item per tile by construction and the lettering rows look only at lettering regions. Writing a '
            'state in this column would mean rebuilding a judge everyone already agreed does not work.'
        ),
    },
    'fixtures': [
        {
            'path': MANIFEST,
            'verified': False,
            'generated': (
                'python3 ' + FXT + '/plant.py --write-manifest — it records, per plant, the source run id, the '
                "S slot, that slot's render prompt, the paste box and the cutout provenance; the operator then "
                'adds, per slot, the list of checkable nouns that prompt supports'
            ),
            'blocks': ['prompt_derived'],
            'how_to_verify': (
                'read each of the 12 render prompts and write down the checkable nouns it supports, then '
                'confirm the recorded paste box of each plant is where the plant actually is; ~30 minutes. '
                'The noun list is the KEY prompt_derived is scored against, so a list nobody wrote by hand '
                'would make the column measure the gate against itself.'
            ),
        },
        {
            'path': PLANTED,
            'verified': False,
            'generated': (
                'python3 ' + FXT + '/plant.py --planted — pastes the 12 cutouts of PLANTS into the 12 approved '
                '1671 stills named in MANIFEST.json at the recorded boxes, one plant per still, and writes '
                'planted/<plant id>.png. No model, no render: PIL compositing only'
            ),
            'blocks': ['recall', 'vehicles', 'wires', 'clothing_era', 'hair_era', 'objects_era'],
            'how_to_verify': (
                'look at each of the 12 once and confirm the plant is VISIBLE at 100 % and is the only '
                'anachronism in the frame — a still that already contained one is dropped and re-chosen, '
                'not corrected. ~20 minutes.'
            ),
        },
        {
            'path': CLEAN,
            'verified': False,
            'generated': 'python3 '
            + FXT
            + '/plant.py --clean — copies the same 12 source stills with nothing pasted into them, under the same ids, so recall and false are the same twelve pictures',
            'blocks': ['false'],
            'how_to_verify': (
                'confirm each clean twin is byte-identical to its source still and that no modern object, '
                'wire or lettering appears in any of the 12; ~15 minutes. This is the half that catches a '
                'gate which flags everything.'
            ),
        },
        {
            'path': SIGNS,
            'verified': False,
            'generated': (
                'python3 ' + FXT + '/plant.py --signs — draws the five boards of SIGNS_TABLE onto the same '
                'plank-wall still with PIL, one fault each, in the faces named in the table, and writes the '
                'painted string of each into MANIFEST.json as its key'
            ),
            'blocks': ['reads_text', 'spelling', 'script_era', 'language_frame', 'numerals_frame'],
            'how_to_verify': (
                'read all five boards off the screen and confirm each shows the string in the table and '
                'exactly ONE fault, and that sign_base and sign_script differ only in typeface; '
                '~15 minutes. An unverified sign key would grade a reader against a string nobody read.'
            ),
        },
    ],
    'run_order': [
        'ocr_judge first: CPU, three minutes, mechanical, and it fails loudly if the signs fixture is malformed',
        'typography next — the same signs plus the 36 clean frames, and it settles four of the five Lettering columns',
        'then era_gate on the 12 CLEAN twins: `false` before `recall`, because a gate that flags every clean frame makes every later number unreadable and there is no point spending the GPU on it',
        'then era_gate on the 12 planted frames for recall and the five class columns',
        "prompt_derived last of the domain columns: it needs the operator's noun lists, which are the slowest part of the fixture pass",
        "the judge bank's 132-subject set is na on every row of this step, so there is no bank pass to schedule here — the whole cost is the 16 probed columns plus the bank's three universal probes (failsafe, degrades, offline)",
    ],
    'budget': {
        'calls': 2820,
        'tokens_in': 260000,
        'tokens_out': 60000,
        'minutes': 130,
        'gpu_minutes': 125,
        'operator_minutes': 2,
        'note': (
            'Per row, sized on era_gate (the expensive one): 24 frames (12 planted + 12 clean) x 6 tiles x ~2.5 '
            'items x 3 repeats = ~1080 Qwen3-VL calls, plus the 5 signs and the sign tiles, plus 3 Haiku '
            'extraction calls (one per batch) — ~2820 calls, ~260k prompt tokens and ~60k completion tokens, of '
            'which Qwen3-VL is local and only the 3 extraction calls and any Anthropic vision fallback are '
            'billed. CLAUDE WEEK WARNING: extract_checks calls claude-haiku and judge_frame can fall back to '
            'Anthropic vision, so this row spends the SHARED weekly meter; run it once per model, not per '
            'debugging pass, and prefer derive_checks_offline (the deterministic keyword fallback) while '
            'iterating. gpu_minutes 125 of 130: Qwen3-VL is resident through the whole era_gate pass at ~2.7 '
            's/frame-tile. The other three rows are overridden and are cheap (typography 8 min / 6 GPU, '
            "ocr_judge 3 min / 0 GPU at 0.58 s/frame CPU, the two retired rows 0). The judge bank's 132-subject "
            'set is na on every row here, so unlike the other judge steps there is no ~2100-call bank pass; the '
            "only blind operator decision left is the bank's u_failsafe check, which is ~2 minutes per row and "
            'is the whole of operator_minutes. The fixture pass is '
            'ONE-TIME and outside this figure: ~80 minutes (12 noun lists ~30, 12 planted ~20, 12 clean ~15, '
            '5 signs ~15), and until it is done all 16 probed columns are blocked and the runner writes '
            'untested "key unverified".'
        ),
    },
    'notes': [
        'No `operator` check in this module. Every probed column is an overlap with a paste box the script recorded, '
        'a share over a named subset, or a string comparison with a key the script wrote — the 2026-09-27 defect '
        'bench (best local VLM 34/40 global, 2/8 hard) is why nothing here asks a model to judge a judge.',
        'recall and false are the same twelve stills, planted and clean. Read apart they are both meaningless: the '
        'moondream row is in this sheet precisely because a recall number was once read without its twin.',
        'gate_flags_planted requires the flag to LAND on the plant and to NAME it. A gate that returns one flag per '
        'frame saying "something looks modern" scores 0 on all six anachronism columns, which is the intended reading '
        'and not a harsh threshold.',
        'The Lettering band is measured two different ways on two rows and each state_note says which: typography '
        'must REJECT with the fault named, ocr_judge must READ the faulty string back exactly so the comparison can '
        'catch it. script_era has only the first, because the string on sign_script is correct.',
        'The bank is na on every row of this step, including the Sees: Text & number band — the bank scores that band '
        'with `ocr_equals` whose engine is the typography OCR judge, so two of these rows would be grading themselves.',
    ],
}
