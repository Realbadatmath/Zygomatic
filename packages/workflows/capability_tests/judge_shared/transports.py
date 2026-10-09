# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .settings import COND_JSON, COND_JUDGE, COND_LONG, COND_NOTE, LEDGER_INTRO, RESOLUTION
from .subjects import MECHANICAL, NEG, SUBJECTS, SUBJECT_NEG_RULE, SUBJECT_PROMPT
from .probes_subjects import PROBES
from .probes_pairs import PAIRS
from .probes_ladders import LADDERS, LADDER_NOTE
from .prompt_damage import BASE_IMAGE, BASE_IMAGE_PROMPT, BASE_KEY, BASE_TASK, DAMAGE
from .prompt_clarity import CLARITY_LADDER, HOUSE_Q, PROSE_Q, TAGS_Q
from .universal import DERIVE, LOOKUP, NA, WIRING

# ── Per transport, what cannot be asked ─────────────────────────────────────
_BUILTIN_NA = (
    'an arithmetic gate compares pixels; it does not recognise subjects. look_gate, patch_gate, '
    'fill_check and plate_law take two pictures and return a number — there is no question to ask them '
    'and no name they could return.'
)
_BUILTIN_PROMPT_NA = (
    'an arithmetic gate takes no prompt at all, so there is no wording to damage, no clarity to '
    'vary and no limit to reach. Its threshold lives in the code, not in a question.'
)

TRANSPORT_NA = {
    'builtin': dict(
        {f'see_{_s}': _BUILTIN_NA for _s in SUBJECTS},
        **{f'identify_{_s}': _BUILTIN_NA for _s in SUBJECTS},
        **{_c: _BUILTIN_PROMPT_NA for _c in list(DAMAGE)},
        **{
            'pd_damage': _BUILTIN_PROMPT_NA,
            'pd_contradiction': _BUILTIN_PROMPT_NA,
            'pd_negation': _BUILTIN_PROMPT_NA,
            'pd_unstated': _BUILTIN_PROMPT_NA,
            'pd_bleed': _BUILTIN_PROMPT_NA,
            'pd_leak': _BUILTIN_PROMPT_NA,
            'pd_meta_literal': _BUILTIN_PROMPT_NA,
            'pd_damage_visible': _BUILTIN_PROMPT_NA,
            'pd_question_wording': _BUILTIN_PROMPT_NA,
            'pd_leading': _BUILTIN_PROMPT_NA,
            'pd_yes_bias': _BUILTIN_PROMPT_NA,
            'pd_clarity_floor': _BUILTIN_PROMPT_NA,
            'pd_terse_ok': _BUILTIN_PROMPT_NA,
            'pd_detail_helps': _BUILTIN_PROMPT_NA,
            'pd_sweet_spot': _BUILTIN_PROMPT_NA,
            'pd_prose_ok': _BUILTIN_PROMPT_NA,
            'pd_structure_needed': _BUILTIN_PROMPT_NA,
            'pd_house_template': _BUILTIN_PROMPT_NA,
            'pd_example_needed': _BUILTIN_PROMPT_NA,
            'pd_jargon_needed': _BUILTIN_PROMPT_NA,
            'pd_asks_back': _BUILTIN_PROMPT_NA,
            'pd_rubric_needed': _BUILTIN_PROMPT_NA,
            'pd_abstain': _BUILTIN_PROMPT_NA,
            'pd_max_hard': _BUILTIN_PROMPT_NA,
            'pd_max_soft': _BUILTIN_PROMPT_NA,
            'pd_max_words': _BUILTIN_PROMPT_NA,
            'pd_truncation_loud': _BUILTIN_PROMPT_NA,
            'pd_min_len': _BUILTIN_PROMPT_NA,
            'pd_unique_things': _BUILTIN_PROMPT_NA,
            'pd_unique_subjects': _BUILTIN_PROMPT_NA,
            'pd_attrs_per_thing': _BUILTIN_PROMPT_NA,
            'pd_instructions': _BUILTIN_PROMPT_NA,
            'pd_constraints': _BUILTIN_PROMPT_NA,
            'pd_order_wins': _BUILTIN_PROMPT_NA,
            'pd_negative_len': _BUILTIN_PROMPT_NA,
            'pd_batched_questions': _BUILTIN_PROMPT_NA,
            'pd_small_edit': _BUILTIN_PROMPT_NA,
            'pd_seed_vs_prompt': _BUILTIN_PROMPT_NA,
            'pd_fix_lands': _BUILTIN_PROMPT_NA,
            'pd_fix_breaks': _BUILTIN_PROMPT_NA,
            'pd_reusable': _BUILTIN_PROMPT_NA,
            'pd_portable': _BUILTIN_PROMPT_NA,
            'pd_recorded': _BUILTIN_PROMPT_NA,
            'pd_retries': _BUILTIN_PROMPT_NA,
            'cap_named': 'an arithmetic gate holds no names.',
            'cap_questions': 'an arithmetic gate is asked no questions.',
            'cap_prompt_terms': 'an arithmetic gate is given no terms.',
            'train_data': 'a gate written in this house has no training corpus; the column is about learned weights.',
            'ai_training': 'nothing was learned, so there is nothing to train on downstream.',
            'weights_pinned': 'there are no weights — the gate is arithmetic. The code revision is the receipt and '
            'it is recorded under `wired`.',
            'deterministic': 'arithmetic over the same two pictures is identical by construction; measuring it '
            'would be measuring the CPU.',
        },
    ),
    'service': {
        'cap_questions': 'a detector is not asked questions; it is called once and returns what it found.',
        'cap_prompt_terms': 'a closed-vocabulary detector takes no terms. GroundingDINO does, and its rows are '
        'measured; hand_yolov8s, MediaPipe and ArcFace rows are na here with this reason.',
        'pd_abstain': 'a detector abstains by returning nothing, which is already read as its answer; there is no '
        'separate "cannot tell" for it to say.',
    },
    'vlm_ollama': {
        'cap_images': 'the ollama /api/generate images field is accepted, but the house client sends one image per '
        'call; a row that needs more is measured through vlm_inspector instead.',
    },
    'retired': {},
}


SHARED = {
    'version': '2026-09-30.1',
    'kind': 'judge',
    'title': 'The bank every judge step runs identically',
    'probes': PROBES,
    'derive': DERIVE,
    'lookup': LOOKUP,
    'wiring': WIRING,
    'na': NA,
    'transport_na': TRANSPORT_NA,
    # ── informational: what a runner needs in order to reproduce the bank ──
    'fixed_settings': {
        'judge': COND_JUDGE,
        'json': COND_JSON,
        'long': COND_LONG,
        'note': COND_NOTE,
        'resolution': RESOLUTION,
        'seed': 11,
        'temperature': 0.0,
        'repeats': 3,
    },
    'subject_table': {
        'prompt_template': SUBJECT_PROMPT,
        'negative_rule': SUBJECT_NEG_RULE,
        'subjects': SUBJECTS,
        'negatives': NEG,
        'mechanical': MECHANICAL,
        'count': len(SUBJECTS),
        'prompt_length_note': (
            'every subject prompt is kept under 60 words on purpose: SDXL and the house image '
            'bank truncate at 77 CLIP tokens WITHOUT SAYING SO, and a subject clause that falls '
            'off the end produces a fixture that does not contain its own subject. Under 60 '
            'words the whole clause survives with room to spare. Any new subject added to this '
            'table must be checked against that limit before it is rendered.'
        ),
    },
    'pair_table': {
        'pairs': PAIRS,
        'count': len(PAIRS),
        'note': 'counting, space and attribute columns are matched A/B pairs with different keys, for '
        'the same reason the Sees band is pos/neg: a judge with a favourite number scores 50 %.',
    },
    'ladder_table': {'ladders': LADDERS, 'count': len(LADDERS), 'note': LADDER_NOTE},
    'prompt_base': {
        'task': BASE_TASK,
        'key': BASE_KEY,
        'image': BASE_IMAGE,
        'image_prompt': BASE_IMAGE_PROMPT,
        'damage': DAMAGE,
        'clarity_ladder': CLARITY_LADDER,
        'forms': {'prose': PROSE_Q, 'tags': TAGS_Q, 'house': HOUSE_Q},
    },
    'operator_protocol': [
        'BLIND. The operator is shown the output and the picture, never the model name, the transport, the seed, '
        'the rung number or how the mechanical check scored it. Outputs are anonymised and shuffled before the '
        'sitting, and the sitting is one question at a time.',
        'A "maybe" is a NO. Every operator question in this bank is written to be answerable yes or no by looking; '
        'if the operator needs to think about it, the model did not make it obvious and the trial did not pass.',
        'The operator answers the question WRITTEN HERE, not one they improvise at the keyboard. Where a rubric '
        'exists (clarity_rubric), the operator judges against the same rubric the model was given, so the standard '
        'is not applied twice at two different heights.',
        'The operator verifies FIXTURES in a separate pass, before any model is run, by looking at the render and '
        'writing the key from what is in the picture — never from what the prompt asked for. A fixture whose key is '
        'not verified blocks its columns, which are written untested with the note "key unverified".',
        'No VLM verifies a fixture. That is the whole lesson of the 2026-09-27 defect bench: the models that would '
        'be asked to check the key are the models being tested, and on the specific defects they scored 2/8.',
    ],
    'conditions_note': COND_NOTE,
    'honesty_note': (
        'Two things in this bank do the work. FIRST, every recognition column is a MATCHED PAIR: a positive fixture '
        'that contains the subject and a negative that does not, rendered from the same seed with the subject clause '
        'removed or contradicted. The column is scored on recall AND precision over both halves, so a judge that '
        'answers yes to everything scores 50 %, not 100 % — which is what a positives-only test would have shown. '
        "SECOND, wherever a detector exists the probe carries BOTH the model's answer and the detector's reading "
        '(MediaPipe hand_landmarker and face mesh from anatomy_qc.py, the ultralytics person class from '
        'continuity_qc.py, ArcFace from identity_qc_service.py, the typography OCR judge), and the state_note on '
        'that probe says which one decides. '
        'The reason is on the record: the defect-judge bench of 2026-09-27 '
        f'({LEDGER_INTRO}/intro/defect_bench/sheet.json — 6 pictures, 55 questions, 5 '
        'models) scored moondream at 34/40 on a global "is anything wrong with this picture" question and 2/8 on '
        'fused fingers, extra digits and the second feather. era_gate shows the same shape: moondream 34/40, '
        'Qwen3-VL 2/8. No local VLM on this box judges a specific defect reliably. So a correctness column here is '
        'never left to a model alone: it is the operator, blind, plus the mechanical check where one exists.'
    ),
}
