# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations


# ── the house system prompt: identical for every model in every text step ─────────────
SYSTEM = (
    "You write and reason for a Dutch production house that makes films, children's series "
    'and documentaries set mostly in the seventeenth-century Netherlands. Follow the '
    'instruction exactly. Return only what is asked for: no preamble, no commentary, no '
    'markdown fences unless asked. When the instruction says JSON, return one JSON object '
    'and nothing else. If an instruction cannot be followed, say so in one sentence and stop.'
)

# ── the passage ───────────────────────────────────────────────────────────────────────
# Every count and every relation below is stated exactly once and never contradicted.
# Changing a word here changes every key — bump SHARED['version'] if you do.
PASSAGE = (
    'The quay at the Kattenburg yard, 1671, late afternoon. Three tarred barrels stand in a '
    'row beside the crane, and behind them a stack of seven crates. Cornelis, the shipwright, '
    'holds a mallet in his right hand; his left hand, which lost two fingers to a caulking '
    "iron last winter, rests on the rail. Anna stands on Cornelis's left, holding a lantern. "
    'Her brother Joost sits on the nearest barrel, facing the water, holding a coil of rope. '
    'Two boys chase a three-legged dog along the quay; a cart horse waits at the far end, '
    'harnessed to an empty cart. The yard house behind them has two floors with four windows '
    'on each floor and a fifth, smaller window in the gable. Fourteen gulls sit along the '
    "ridge. A bell hangs above the door, but nobody rings it. A cat's bowl stands inside the "
    "doorway, but there is no cat anywhere on the quay. The lantern is lit; the crane's hook "
    'hangs over the water, above the moored pinas, whose mast hides the church tower from '
    "Anna's view."
)

# One atomic question per bank column — the era-gate lesson: a bundled question cannot be
# trusted, one checkable question per call can ([[project_anachronism_gate_qwen]]).
ATOMIC_SUFFIX = ' Answer with the single word or number only.'
KEYS = {
    'count_exact': {'q': 'How many barrels stand on the quay?', 'accept': ['3', 'three']},
    'count_large': {'q': 'How many gulls sit on the ridge?', 'accept': ['14', 'fourteen']},
    'count_people': {'q': 'How many people are on the quay in total, counting the boys?', 'accept': ['5', 'five']},
    'count_fingers': {
        'q': 'Counting thumbs as fingers, how many fingers does Cornelis have left on both hands together?',
        'accept': ['8', 'eight'],
    },
    'count_legs': {'q': 'How many legs do the dog and the horse have together?', 'accept': ['7', 'seven']},
    'count_windows': {'q': 'How many windows does the yard house have in total?', 'accept': ['9', 'nine']},
    'count_absent': {'q': 'Is there a cat on the quay?', 'accept': ['no']},
    'count_more_less': {'q': 'Are there more crates or more barrels?', 'accept': ['crates']},
    'sp_left_right': {'q': 'On which side of Cornelis does Anna stand, his left or his right?', 'accept': ['left']},
    'sp_front_behind': {'q': 'Are the crates in front of the barrels or behind them?', 'accept': ['behind']},
    'sp_holding_who': {'q': 'Who holds the lantern?', 'accept': ['anna']},
    'sp_inside': {'q': 'What stands inside the doorway?', 'accept': ['bowl', "cat's bowl", 'cats bowl', 'a bowl']},
    'sp_near_far': {
        'q': 'Which is nearer to Joost, the barrels or the cart horse?',
        'accept': ['barrels', 'the barrels', 'barrel'],
    },
    'sp_occlusion': {
        'q': "What hides the church tower from Anna's view?",
        'accept': ['mast', 'the mast', "the pinas's mast", 'the mast of the pinas'],
    },
    'sp_on_under': {'q': 'What hangs above the door?', 'accept': ['bell', 'a bell', 'the bell']},
    'sp_relative_size': {'q': 'Is the gable window larger or smaller than the other windows?', 'accept': ['smaller']},
    'sp_touching': {'q': "What is Cornelis's left hand touching?", 'accept': ['rail', 'the rail']},
    'sp_direction': {'q': 'Which way is Joost facing?', 'accept': ['water', 'the water']},
}

# ── the extraction task with one right answer ─────────────────────────────────────────
EXTRACT_TASK = (
    'Read the passage. List every named person and the object each is holding, and count '
    'the barrels. Return exactly this JSON and nothing else: '
    '{"people": [{"name": string, "holds": string}], "barrels": integer}'
)
EXTRACT_KEY = {
    'people': [
        {'name': 'cornelis', 'holds': 'mallet'},
        {'name': 'anna', 'holds': 'lantern'},
        {'name': 'joost', 'holds': 'rope'},
    ],
    'barrels': 3,
    'normalise': 'names lowercase; holds matched by keyword (mallet|lantern|rope) inside the string; order free',
}

# The damage variants. Same meaning as EXTRACT_TASK, worse writing. Each is scored with
# `equals_key` against EXTRACT_KEY — the answer must not move.
EXTRACT_VARIANTS = {
    'pd_paraphrase': 'Go through the passage and give me, as one JSON object, each person who is named together with whatever that person has in their hands, plus how many barrels there are. Shape: {"people": [{"name": string, "holds": string}], "barrels": integer}. Output the JSON only.',
    'pd_word_order': 'Barrels: how many? And for every named person, what they hold. JSON only, exactly {"barrels": integer, "people": [{"name": string, "holds": string}]}. Read the passage first.',
    'pd_synonym': 'Read the passage. List every named individual and the item each is carrying, and count the casks. Return exactly this JSON and nothing else: {"people": [{"name": string, "holds": string}], "barrels": integer}',
    'pd_typo': 'Read the pasage. List evrey named person and the object each is hodling, and count the barrles. Retrun exactly this JSON and nothing else: {"people": [{"name": string, "holds": string}], "barrels": integer}',
    'pd_grammar': 'passage read. named person all, thing in hand each. barrel count how much. JSON exact only: {"people": [{"name": string, "holds": string}], "barrels": integer}',
    'pd_punctuation': 'Read the passage; list every named, person and the object each is holding and count, the barrels. Return exactly this JSON, and nothing else {"people": [{"name": string, "holds": string}], "barrels": integer}',
    'pd_case': 'READ THE PASSAGE. LIST EVERY NAMED PERSON AND THE OBJECT EACH IS HOLDING, AND COUNT THE BARRELS. RETURN EXACTLY THIS JSON AND NOTHING ELSE: {"people": [{"name": string, "holds": string}], "barrels": integer}',
    'pd_filler': 'Please, if you would be so kind, very carefully and in a highly detailed, professional, thorough way, read the passage. Please list every single named person and the object each is holding, and please count the barrels. Return exactly this JSON and nothing else: {"people": [{"name": string, "holds": string}], "barrels": integer}',
    'pd_repetition': 'Read the passage. List every named person and the object each is holding, and count the barrels. Count the barrels. Barrels, barrels. Return exactly this JSON and nothing else: {"people": [{"name": string, "holds": string}], "barrels": integer}',
    'pd_tone_word': 'Read the grim passage. List every named person and the object each is holding, and count the barrels. Return exactly this JSON and nothing else: {"people": [{"name": string, "holds": string}], "barrels": integer}',
    'pd_multilingual': 'Lees de passage. Noem iedere persoon die bij naam wordt genoemd en het voorwerp dat hij of zij vasthoudt, en tel de tonnen. Geef precies deze JSON terug en niets anders: {"people": [{"name": string, "holds": string}], "barrels": integer}',
}

# ── deterministic padding ─────────────────────────────────────────────────────────────
FILLER_LINE = 'Entry {i}: on day {i} the water at the Kattenburg gauge stood at {h} duim and the wind was {w}.'
FILLER_WINDS = ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west']
FILLER_RULE = (
    'FILLER(n_tokens): concatenate FILLER_LINE for i = 1, 2, 3, … with h = (i*37) % 300 and '
    'w = FILLER_WINDS[i % 8], one line per entry, until the line count reaches '
    'round(n_tokens / 22) — one line is 22 tokens on the cl100k tokenizer, which the '
    'runner uses as the common yardstick for every model. Never random.'
)
NEEDLE = 'The password for the yard gate is "zeehond-{k}".'
NEEDLE_Q = 'What is the password for the yard gate? Answer with the password only.'
CONTEXT_SIZES = [2000, 8000, 32000, 64000, 128000]  # tokens of filler
NEEDLE_DEPTHS = [0.25, 0.50, 0.75]  # fraction of the filler the needle sits at

# ── run conditions ────────────────────────────────────────────────────────────────────
COND_LITERAL = {'temperature': 0.0, 'seed': 11, 'max_tokens': 400, 'repeats': 3}
COND_CREATIVE = {'temperature': 0.7, 'seeds': [11, 12, 13], 'max_tokens': 1200, 'repeats': 3}
COND_NOTE = (
    'Ollama rows take temperature and seed through `options`. The Anthropic API takes '
    'temperature and no seed. The claude_cli path takes NEITHER (subscription_llm drops '
    'temperature) — those rows run at the CLI default and the seed-dependent columns are '
    '`na` for them, see TRANSPORT_NA. This is recorded on every trial.'
)
