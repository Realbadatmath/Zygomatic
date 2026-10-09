# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Script & story writing (llm_script). 2026-09-28.

Question the sheet asks: which language model turns a brief into shippable scene text
without a rewrite? The sheet's own `next_tests` said it: "ten briefs, every row, blind
operator ranking on first take — the only way to fill the brief and voice columns honestly."
This is those ten briefs, fixed, plus a mechanical check for everything a machine can decide.

Includes the shared text bank (counting, spatial, prompt damage, universal).
"""

from __future__ import annotations

from capability_tests.text_shared import COND_CREATIVE, COND_LITERAL

# ── word lists every brief is scored against ────────────────────────────────────────
PREAMBLE = [
    'Here is',
    "Here's",
    'Sure',
    'Certainly',
    'Of course',
    'Below is',
    'I have written',
    "I've written",
    'Absolutely',
    'Great',
    'Okay',
    'OK,',
    'Title:',
    '```',
    '**Scene',
    'As requested',
    'Hier is',
    'Natuurlijk',
    'Zeker',
    'Hieronder',
]
SIGNOFF = [
    'let me know',
    'hope this',
    'feel free',
    'would you like',
    'I can also',
    'laat het me weten',
    'hopelijk',
    'wil je dat ik',
]
REFUSAL = [
    "I can't",
    'I cannot',
    "I'm not able",
    'I am not able',
    "I won't",
    "I'm sorry",
    'Sorry',
    'As an AI',
    'I must decline',
    'not comfortable',
    'Ik kan niet',
    'Ik kan geen',
    'Het spijt me',
    'Sorry, maar',
]
ANACHRONISM_EN = [
    'police',
    'photograph',
    'photo',
    'camera',
    'cigarette',
    'train',
    'railway',
    'electric',
    'electricity',
    'kilometre',
    'kilometer',
    'metre',
    'meter',
    'centimetre',
    'centimeter',
    'plastic',
    'rubber',
    'okay',
    'ok',
    'guys',
    'cool',
    'weekend',
    'seconds',
    'second hand',
    'minutes',
    'wristwatch',
    'watch',
    'steam',
    'engine',
    'motor',
    'bicycle',
    'newspaper',
    'potato',
    'pencil',
    'teenager',
    'stress',
    'focus',
    'adrenaline',
]
ANACHRONISM_NL = [
    'politie',
    'foto',
    'camera',
    'sigaret',
    'trein',
    'spoor',
    'elektrisch',
    'elektriciteit',
    'kilometer',
    'meter',
    'centimeter',
    'plastic',
    'rubber',
    'oké',
    'ok',
    'cool',
    'weekend',
    'seconden',
    'minuten',
    'horloge',
    'stoom',
    'motor',
    'fiets',
    'krant',
    'aardappel',
    'potlood',
    'tiener',
    'stress',
]
CLICHES = [
    'little did they know',
    'little did he know',
    'little did she know',
    'a chill ran down',
    'in that moment',
    'time seemed to stop',
    'time stood still',
    'the silence was deafening',
    "let out a breath he didn't know",
    "let out a breath she didn't know",
    'a wave of',
    'heart pounding',
    'heart pounded',
    'heart raced',
    'blood ran cold',
    'shivers down',
    'without a word',
    'a single tear',
    'the weight of the world',
    'against all odds',
    'in the blink of an eye',
    'eyes widened',
    'jaw dropped',
    'a smile played',
    'darkness fell',
    'the sun dipped below',
    'painted the sky',
    'a tapestry of',
    'testament to',
    'delve',
    'palpable',
    'nestled',
    'echoed through',
    'hung in the air',
    'the air was thick',
    'cut through the silence',
    'ineens werd alles stil',
    'een rilling liep',
    'de tijd stond stil',
    'zonder een woord',
    'een traan',
]

SCENE_CHECKS = [
    {'check': 'starts_clean', 'banned': PREAMBLE},
    {'check': 'ends_clean', 'banned': SIGNOFF},
    {'check': 'absent', 'terms': CLICHES},
]
OPERATOR_TAKE = {'check': 'operator', 'blind': True, 'question': 'Usable as a first take without a rewrite? yes/no'}


def _brief(bid, title, feeds, prompt, checks, lang='en', cond=COND_CREATIVE, **kw):
    p = {
        'id': bid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'system': 'SYSTEM', 'passage': None, 'prompt': prompt, 'lang': lang},
        'conditions': dict(cond),
        'checks': SCENE_CHECKS + list(checks),
        'grade': 'measured',
    }
    p.update(kw)
    return p


# ── the ten briefs ──────────────────────────────────────────────────────────────────
# Each brief feeds `brief` (operator: usable first take) and the columns its checks decide.
BRIEFS = [
    _brief(
        'b01_yard',
        'B1 — the yard, the night before the launch',
        ['brief', 'period', 'names', 'structure'],
        'Write a 120-word scene. Kattenburg yard, Amsterdam, 1671, the night before the pinas is launched. '
        "Cornelis the shipwright and Anna, who keeps the yard's books, by tallow light. Anna has found that the "
        'tallow for the slipway was never ordered. Beginning, a turn, an end. Dialogue and action; no narration. '
        'No modern words.',
        [
            {'check': 'word_count', 'min': 100, 'max': 145},
            {'check': 'absent', 'terms': ANACHRONISM_EN},
            {'check': 'present', 'terms': ['Cornelis', 'Anna', 'tallow']},
            {'check': 'regex_absent', 'pattern': r'\b(Cornelius|Cornelia|Anne|Anneke|Annie)\b'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Can you point at the line where the scene turns, and does it end rather than stop? yes/no',
            },
            OPERATOR_TAKE,
        ],
    ),
    _brief(
        'b02_loft',
        'B2 — Abel finds the ledger (subtext)',
        ['brief', 'subtext', 'names', 'period'],
        "Write a 150-word scene. A farmhouse loft, 1671. Abel, nine, finds his father's ledger under the straw and "
        'reads a page he should not have read. His father Dirck calls from below. Abel is afraid of his father, but '
        'neither the word fear nor any of its synonyms may appear, and nothing may state that he is afraid — show it. '
        'Dialogue and action only.',
        [
            {'check': 'word_count', 'min': 125, 'max': 180},
            {'check': 'absent', 'terms': ANACHRONISM_EN},
            {
                'check': 'absent',
                'terms': [
                    'afraid',
                    'fear',
                    'feared',
                    'frightened',
                    'scared',
                    'terrified',
                    'terror',
                    'dread',
                    'anxious',
                    'nervous',
                    'panic',
                ],
            },
            {'check': 'present', 'terms': ['Abel', 'Dirck', 'ledger']},
            {'check': 'regex_absent', 'pattern': r'\b(Able|Abell|Derck|Dirk|Dirks)\b'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Did you understand that Abel is afraid of his father without being told? yes/no',
            },
            OPERATOR_TAKE,
        ],
    ),
    _brief(
        'b03_kip',
        'B3 — Kip Kaatje (kids, Dutch, reading age 5)',
        ['brief', 'register', 'lang', 'names'],
        'Schrijf een verhaaltje van 80 woorden voor kinderen van vijf, in het Nederlands. Kip Kaatje is haar ei kwijt '
        'op het erf. Ze vraagt het aan Bok Bram en aan Poes Pien. Het ei ligt in de hoed van de boer. Vrolijk einde. '
        'Korte zinnen, geen moeilijke woorden.',
        [
            {'check': 'word_count', 'min': 65, 'max': 100},
            {'check': 'language', 'lang': 'nl', 'min': 0.6},
            {'check': 'sentence_max_words', 'max': 10},
            {'check': 'max_word_len', 'max': 12},
            {'check': 'present', 'terms': ['Kaatje', 'Bram', 'Pien', 'ei', 'hoed']},
            {'check': 'regex_absent', 'pattern': r'\b(Katje|Kaatja|Kaat|Braam|Piem)\b'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is the Dutch correct and does it read at age five (no abstract words, nothing a parent would rephrase)? yes/no',
            },
            OPERATOR_TAKE,
        ],
        lang='nl',
    ),
    _brief(
        'b04_narration',
        'B4 — documentary narration (facts given, nothing added)',
        ['brief', 'facts', 'period'],
        'Write 90 words of documentary narration in English about the plague in Amsterdam in 1664 using ONLY these facts '
        'and adding none: the dead were carried out at night; the carts were preceded by a bell; burials were moved '
        'outside the city walls; the city council kept meeting. Use no numbers of any kind. Name no person. '
        'Plain, present tense, no rhetorical questions.',
        [
            {'check': 'word_count', 'min': 75, 'max': 105},
            {'check': 'digits_absent'},
            {
                'check': 'absent',
                'terms': ANACHRONISM_EN
                + [
                    'thousand',
                    'hundred',
                    'percent',
                    'per cent',
                    'half',
                    'third',
                    'quarter',
                    'Rembrandt',
                    'Witsen',
                    'doctor',
                ],
            },
            {'check': 'proper_nouns_allowlist', 'allow': ['Amsterdam']},
            {'check': 'regex_absent', 'pattern': r'\?'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does the text assert anything not in the four given facts? (yes = a fact was invented)',
                'invert': True,
            },
            OPERATOR_TAKE,
        ],
    ),
    _brief(
        'b05_kade',
        'B5 — Cornelis, dag 1 (Dutch, two voices)',
        ['brief', 'lang', 'voice', 'period'],
        'Schrijf een scène van 200 woorden in het Nederlands. Amsterdam, 1671, de kade bij de werf, vroege ochtend. '
        'Cornelis (scheepstimmerman: kort van stof, zeemanstaal, zegt nooit "alstublieft" of "graag") en Joost, zijn '
        'nieuwe knecht (praat te veel als hij zenuwachtig is). Joost is te laat op zijn eerste dag. Alleen dialoog en '
        'handeling, geen vertelstem, geen moderne woorden.',
        [
            {'check': 'word_count', 'min': 170, 'max': 240},
            {'check': 'language', 'lang': 'nl', 'min': 0.6},
            {'check': 'absent', 'terms': ANACHRONISM_NL},
            {'check': 'regex_absent', 'pattern': r'(?im)^\s*CORNELIS\s*:.*\b(alstublieft|alsjeblieft|graag)\b'},
            {'check': 'present', 'terms': ['Cornelis', 'Joost']},
            {
                'check': 'operator',
                'blind': True,
                'question': "Are Cornelis's lines terse and in sea idiom throughout, without softening by the end? yes/no",
            },
            OPERATOR_TAKE,
        ],
        lang='nl',
    ),
    _brief(
        'b06_two_hander',
        'B6 — twelve lines, two voices that must not converge',
        ['brief', 'multi_voice'],
        'Write exactly 12 lines of dialogue, alternating, each starting with the speaker name in capitals and a colon. '
        'CORNELIS: terse, sea idiom, sentences under eight words, never asks a question. JOOST: talks too much, hedges, '
        'asks questions, uses "I think" and "maybe". Subject: Joost has hidden a mistake in the planking. Output the 12 lines only.',
        [
            {'check': 'line_count', 'min': 12, 'max': 12},
            {'check': 'lines_alternate', 'speakers': ['CORNELIS:', 'JOOST:']},
            {'check': 'regex_absent', 'pattern': r'(?m)^CORNELIS:.*\?'},
            {'check': 'regex_present', 'pattern': r'(?m)^JOOST:.*\?'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'ATTRIBUTION TEST: the runner shows you the 12 lines with the names removed and shuffled. Assign each to Cornelis or Joost. Pass = at least 11 of 12 right.',
            },
            OPERATOR_TAKE,
        ],
    ),
    _brief(
        'b07_monologue',
        'B7 — a voice card held for 100 words',
        ['brief', 'voice'],
        'Write a 100-word monologue for Cornelis, spoken to a new apprentice on his first morning. Voice card: terse; '
        'sea idiom; no sentence over twelve words; never says please, sorry or thank you; never explains his feelings; '
        'ends on an order. Output the monologue only.',
        [
            {'check': 'word_count', 'min': 85, 'max': 115},
            {'check': 'sentence_max_words', 'max': 12},
            {
                'check': 'absent',
                'terms': ['please', 'sorry', 'thank you', 'thanks', 'I feel', 'I felt', "I'm afraid", 'I am afraid'],
            },
            {'check': 'regex_present', 'pattern': r'[.!]\s*$'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does the voice hold to the last line (no warm turn, no explaining himself)? yes/no',
            },
            OPERATOR_TAKE,
        ],
    ),
    _brief(
        'b08_kids_intro',
        'B8 — 40 spoken words for a kids song intro (Dutch)',
        ['brief', 'length', 'lang'],
        'Schrijf precies 40 woorden gesproken intro voor een kinderliedje over een rode trein die te vroeg vertrekt. '
        'Nederlands, vrolijk, één spreker, geen rijm. Alleen de tekst.',
        [
            {'check': 'word_count', 'min': 37, 'max': 43},
            {'check': 'language', 'lang': 'nl', 'min': 0.6},
            {'check': 'present', 'terms': ['trein']},
            OPERATOR_TAKE,
        ],
        lang='nl',
    ),
    _brief(
        'b09_hanging',
        'B9 — ordinary but grim (refusal set, 3 briefs)',
        ['refusals'],
        'SET',
        [{'check': 'starts_clean', 'banned': REFUSAL}, {'check': 'word_count', 'min': 70, 'max': 130}],
        set=[
            'Write 100 words: Amsterdam, 1664. Joost drives the plague cart through the Jordaan at night; a boy walks ahead ringing the bell. Joost counts the doors that have a cross on them. Third person, past tense, no gore.',
            'Schrijf 100 woorden: Amsterdam, 1671. Vanaf de kade ziet Anna in de verte de galg op de Volewijk, aan de overkant van het IJ. Ze denkt aan de man die er vorige week hing en aan zijn vrouw, die ze kent. Geen geweld in beeld, alleen wat Anna denkt.',
            "Schrijf 100 woorden voor kinderen van zeven: op de boerderij is het lammetje van Kaatje 's nachts gestorven. De boer legt uit dat dat soms gebeurt en dat ze het samen gaan begraven onder de appelboom. Rustig, troostend, eerlijk.",
        ],
        state_note='refusals = share of the 3 × 3 trials that were written rather than refused; yes = 9/9',
    ),
    _brief(
        'b10_edit_target',
        "B10 — a scene written to be edited (feeds pd_small_edit's `edit` on this step via the shared chain)",
        ['no_preamble'],
        'Write a 100-word scene: the quay at dawn, Anna lights the lantern, Cornelis arrives late for the first time in twenty years. Output the scene only.',
        [
            {'check': 'word_count', 'min': 85, 'max': 115},
            {'check': 'starts_clean', 'banned': PREAMBLE},
            {'check': 'ends_clean', 'banned': SIGNOFF},
            {'check': 'regex_absent', 'pattern': r'^\s*[#*`]'},
        ],
        state_note='no_preamble is read over EVERY brief trial on this sheet (starts_clean + ends_clean), not only this one',
    ),
]

PROBES = BRIEFS + [
    {
        'id': 'continuity',
        'title': 'Remembers earlier scenes (three-turn conversation)',
        'feeds': ['continuity'],
        'inputs': {'system': 'SYSTEM', 'passage': None, 'prompt': 'CHAIN'},
        'conditions': dict(COND_CREATIVE),
        'chain': [
            {
                'id': 'scene1',
                'prompt': 'Write a 150-word scene, the yard at Kattenburg, 1671. Plant these facts and keep them exact: the yard dog is called Pim; Cornelis is left-handed; it is a Tuesday; the pinas is called the Zeehond; the yard bell is cracked. Dialogue and action.',
            },
            {
                'id': 'filler',
                'prompt': 'Now something else. '
                + 'PASSAGE'
                + ' How many barrels stand on the quay? Answer with the number only.',
            },
            {
                'id': 'scene2',
                'prompt': 'Back to the yard. Write the next 150-word scene, the following morning. Use the dog, the bell, the ship and the day of the week again, and have Cornelis pick up the mallet.',
            },
        ],
        'checks': [
            {'check': 'present', 'terms': ['Pim', 'Zeehond', 'Wednesday', 'cracked']},
            {'check': 'regex_absent', 'pattern': r'\b(Tuesday|Thursday|Monday|Friday|Saturday|Sunday)\b'},
            {'check': 'regex_present', 'pattern': r'(?i)\bleft\b'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does scene 2 contradict scene 1 anywhere (a renamed dog, a whole bell, the wrong hand, a different ship)? (yes = contradiction)',
                'invert': True,
            },
        ],
        'grade': 'measured',
        'state_note': 'the checks apply to scene2 only; "the following morning" after a Tuesday must be Wednesday; the mallet must be in the LEFT hand',
    },
    {
        'id': 'cliche',
        'title': 'Avoids stock phrasing (read over every brief)',
        'feeds': ['cliche'],
        'inputs': {
            'system': 'SYSTEM',
            'passage': None,
            'prompt': 'DERIVED-FROM-BRIEFS',
            'task': 'the `absent CLICHES` check over every brief trial of this row',
        },
        'conditions': {'repeats': 1, 'note': 'no extra calls; reads the 10 briefs × 3 repeats'},
        'checks': [{'check': 'absent', 'terms': CLICHES}],
        'grade': 'measured',
        'state_note': 'yes when ≥ 27 of the 30 brief trials contain no phrase from CLICHES; the note lists the phrases that did occur',
    },
    {
        'id': 'length',
        'title': 'Obeys a length budget',
        'feeds': ['length'],
        'inputs': {'system': 'SYSTEM', 'passage': 'PASSAGE', 'prompt': 'LADDER'},
        'conditions': dict(COND_LITERAL),
        'ladder': [
            'Rewrite the passage in exactly 40 words.',
            'Rewrite the passage in exactly 120 words.',
            'Rewrite the passage in exactly 400 words.',
        ],
        'ladder_checks': [
            [{'check': 'word_count', 'min': 36, 'max': 44}],
            [{'check': 'word_count', 'min': 108, 'max': 132}],
            [{'check': 'word_count', 'min': 360, 'max': 440}],
        ],
        'checks': [{'check': 'word_count', 'min': 36, 'max': 440}],
        'grade': 'measured',
        'state_note': '±10 % of the budget on every step and repeat; the note records the mean error per budget',
    },
    {
        'id': 'json_flat',
        'title': 'Obeys a flat JSON contract',
        'feeds': ['json'],
        'inputs': {
            'system': 'SYSTEM',
            'passage': 'PASSAGE',
            'prompt': 'Return exactly this JSON and nothing else, filled from the passage: {"title": string, "location": string, "time_of_day": string, "characters": [string], "summary": string (one sentence)}',
        },
        'conditions': {'temperature': 0.0, 'seed': 11, 'max_tokens': 400, 'repeats': 5},
        'checks': [
            {'check': 'json_valid'},
            {'check': 'json_keys', 'keys': ['title', 'location', 'time_of_day', 'characters', 'summary']},
            {'check': 'regex_present', 'pattern': r'"characters"\s*:\s*\[[^\]]*Cornelis[^\]]*\]'},
        ],
        'grade': 'measured',
        'state_rule': {'yes': 1.0, 'partial': 0.6},
        'state_note': 'yes only at 5/5 — "returns the schema, every time" is the question',
    },
    {
        'id': 'json_deep',
        'title': 'Obeys a nested schema',
        'feeds': ['schema_deep'],
        'inputs': {
            'system': 'SYSTEM',
            'passage': 'PASSAGE',
            'prompt': 'Turn the passage into a scene as JSON, exactly this schema and nothing else: {"scene": {"slug": string, "beats": [{"n": integer, "lines": [{"speaker": string, "text": string, "direction": string|null}]}]}}. Two beats, two to three lines each, speakers only from the passage.',
        },
        'conditions': {'temperature': 0.0, 'seed': 11, 'max_tokens': 900, 'repeats': 5},
        'checks': [
            {'check': 'json_valid'},
            {
                'check': 'json_schema',
                'schema': {
                    'type': 'object',
                    'required': ['scene'],
                    'additionalProperties': False,
                    'properties': {
                        'scene': {
                            'type': 'object',
                            'required': ['slug', 'beats'],
                            'additionalProperties': False,
                            'properties': {
                                'slug': {'type': 'string'},
                                'beats': {
                                    'type': 'array',
                                    'minItems': 2,
                                    'maxItems': 2,
                                    'items': {
                                        'type': 'object',
                                        'required': ['n', 'lines'],
                                        'additionalProperties': False,
                                        'properties': {
                                            'n': {'type': 'integer'},
                                            'lines': {
                                                'type': 'array',
                                                'minItems': 2,
                                                'maxItems': 3,
                                                'items': {
                                                    'type': 'object',
                                                    'required': ['speaker', 'text', 'direction'],
                                                    'additionalProperties': False,
                                                    'properties': {
                                                        'speaker': {'enum': ['Cornelis', 'Anna', 'Joost']},
                                                        'text': {'type': 'string', 'minLength': 1},
                                                        'direction': {'type': ['string', 'null']},
                                                    },
                                                },
                                            },
                                        },
                                    },
                                },
                            },
                        }
                    },
                },
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 1.0, 'partial': 0.6},
    },
    {
        'id': 'temp',
        'title': 'Temperature behaves',
        'feeds': ['temp'],
        'inputs': {'system': 'SYSTEM', 'passage': 'PASSAGE', 'prompt': 'GRID'},
        'conditions': {'max_tokens': 400, 'repeats': 3, 'seed': 11},
        'grid': {'temperature': [0.0, 1.0], 'prompt': 'EXTRACT_TASK'},
        'checks': [{'check': 'equals_key', 'key': 'EXTRACT_KEY'}, {'check': 'identical_runs'}],
        'grade': 'measured',
        'state_note': 'yes when: key holds at both temperatures AND the three runs at 0.0 are identical AND the runs at 1.0 are not all identical; partial when the key holds but 0.0 is not reproducible',
    },
    {
        'id': 'variety',
        'title': 'Two runs differ usefully',
        'feeds': ['variety'],
        'inputs': {
            'system': 'SYSTEM',
            'passage': None,
            'prompt': 'Write 80 words: Anna lights the lantern on the quay and sees something in the water.',
        },
        'conditions': {'temperature': 0.8, 'seeds': [11, 12, 13], 'max_tokens': 300, 'repeats': 3},
        'checks': [{'check': 'pairwise_similarity_max', 'max': 0.6}, {'check': 'word_count', 'min': 65, 'max': 100}],
        'grade': 'measured',
        'state_note': 'yes when all three pairs differ (ratio < 0.6) and each is in budget; "not the same sentence twice"',
    },
]

TEST = {
    'step': 'llm_script',
    'version': '2026-09-28.1',
    'title': 'Ten briefs, blind, first take',
    'purpose': 'Fill the writing columns of the Script & story sheet with the same ten briefs for every model, scored mechanically where a machine can decide and blind where the operator must.',
    'include_shared': 'text',
    'rows': {
        'opus5': {
            'budget': {'minutes': 50, 'note': 'claude_cli is ~15 s a turn and spends the shared Claude week'},
            'transport': 'claude_cli',
            'model': 'claude-opus-5',
            'quota_note': 'spends the shared Claude week — the operator schedules the run ([[feedback_meter_is_shared]])',
        },
        'sonnet5': {'transport': 'anthropic_api', 'model': 'claude-sonnet-5'},
        'haiku45': {'transport': 'anthropic_api', 'model': 'claude-haiku-4-5-20251001'},
        'gptoss20b': {
            'budget': {'minutes': 30, 'gpu_minutes': 30},
            'transport': 'ollama',
            'model': 'gpt-oss:20b',
            'note': 'the json probe runs WITHOUT format:json on this row — that lever returned an empty body on the Kanban sync (receipt on the sheet); the cell note must keep both facts',
        },
        'qwen36': {'budget': {'minutes': 30, 'gpu_minutes': 30}, 'transport': 'ollama', 'model': 'qwen3.6:35b-a3b'},
        'qwen25_32b': {'budget': {'minutes': 35, 'gpu_minutes': 35}, 'transport': 'ollama', 'model': 'qwen2.5:32b'},
        'gpt4o': {'transport': 'github_models', 'model': 'gpt-4o'},
    },
    'probes': PROBES,
    'derive': {},
    'lookup': {},
    'wiring': {},
    'na': {},
    'fixtures': [],
    'run_order': [
        'bank questions (cheap, literal)',
        'extraction base and variants',
        'ten briefs',
        'chains and ladders',
        'needle grid last (largest prompts)',
    ],
    'budget_note': 'About 190 calls per row before the needle grid; the 128k needle at three depths is the expensive item — run it once per row, not per repeat, and say so in the note.',
    'budget': {
        'calls': 200,
        'tokens_in': 460000,
        'tokens_out': 30000,
        'minutes': 25,
        'gpu_minutes': 0,
        'operator_minutes': 40,
        'note': (
            '79 probes x 3 repeats minus the once-per-row items = ~200 calls per row. Prompt tokens: ~110 (system) + ~250 (passage, '
            'when included) + ~80 (question) = ~350 per bank call x 200 = 70k, plus the needle grid at 128k x 3 depths run ONCE per row = 384k, '
            'so ~460k in. Output: 100 one-line bank answers x 10 + 30 brief trials x 250 + json/ladder/variety ~ 8k = ~30k out. '
            'Wall: API rows ~6 s a call = 20 min + needle 3 x 90 s = 25 min; ollama rows hold the GPU the whole time (override). '
            'Operator: 25 blind questions x 3 repeats = 75 decisions x 30 s = ~40 min per row.'
        ),
    },
    'notes': [
        'Every brief trial is ALSO read for no_preamble (starts_clean/ends_clean) and cliche (absent CLICHES); those two columns are computed over all 30 brief trials of a row.',
        'gptoss20b row: the json probe runs without format:json (the lever that returned empty on the Kanban sync) so the model is measured, and the row note keeps the receipt that the lever is unusable.',
        'The operator attribution test on B6 is the honest multi_voice measure: if the two voices cannot be told apart with the names removed, they converged.',
    ],
}
