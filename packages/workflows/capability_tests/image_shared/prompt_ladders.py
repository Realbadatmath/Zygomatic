# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""image_shared.prompt_ladders — the clarity ladder and the prompt-length limits ladder."""

from __future__ import annotations

from capability_tests.image_shared.probes import PROBES, _probe

# ── Prompt: clarity needed — one ladder from a word to a full brief ─────────────────────────
CLARITY_KEY = [
    {'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 1},
    {'check': 'colour_of_thing', 'thing': 'wooden barrel', 'colour': 'red', 'min_share': 0.4},
    {
        'check': 'operator',
        'question': 'Is this a plausible 1671 Dutch stone quay with exactly one red barrel standing on it and nobody present? yes/no',
    },
]
CLARITY_LADDER = [
    'quay',
    'a Dutch quay in 1671',
    'A red barrel on a stone quay in Amsterdam, 1671, plain daylight.',
    'A red barrel with iron hoops stands on a wet stone quay in Amsterdam, 1671, plain '
    'daylight, moored hulls behind it, nobody present.',
    'A red barrel bound with three iron hoops stands alone on the wet stone quay at '
    'Kattenburg, Amsterdam, 1671, in plain overcast daylight. Behind it the black hulls of two '
    'moored merchantmen and a brick warehouse gable. Nobody is present, nothing else stands on '
    'the quay, and the cobbles are dark with rain.',
]

PROBES.append(
    _probe(
        'pd_clarity_ladder',
        'Prompt clarity: five rungs, one word to a full brief',
        ['pd_clarity_floor', 'pd_terse_ok', 'pd_detail_helps', 'pd_sweet_spot'],
        CLARITY_LADDER[2],
        CLARITY_KEY,
        ladder=CLARITY_LADDER,
        ladder_note='Every rung is rendered on all three seeds against the SAME key. The prompt '
        'field holds rung 3 only because a probe must name one fixed input; the runner '
        'renders all five.',
        reads={
            'pd_clarity_floor': 'the LOWEST rung whose key passes on 3/3 seeds. yes if that is rung 1 or 2, partial if rung 3, no if no rung under 5 passes.',
            'pd_terse_ok': 'yes if rung 2 (four words) passes 3/3, partial 2/3.',
            'pd_detail_helps': 'yes if the pass rate rises from rung 3 to rung 5, partial if it is flat, no if it falls — detail that costs accuracy is a real finding.',
            'pd_sweet_spot': 'the rung with the highest pass rate, ties to the shortest. yes if that rung is 3 or 4 (the house writes at that length), partial if 5, no if 1 or 2.',
        },
        state_note='All four cells come off one five-rung ladder, so they cannot contradict one '
        'another. The mechanical half (one barrel, red) decides the count and the '
        'colour; the operator decides the period and the emptiness of the quay.',
    )
)

PROBES += [
    _probe(
        'pd_form_three_ways',
        'Prompt clarity: the same brief as prose, as tags, as the house template',
        ['pd_prose_ok', 'pd_structure_needed', 'pd_house_template'],
        CLARITY_LADDER[3],
        CLARITY_KEY,
        variants={
            'prose': CLARITY_LADDER[3],
            'tags': 'red barrel, iron hoops, wet stone quay, Amsterdam, 1671, plain '
            'daylight, moored hulls behind, no people',
            'house_template': 'SUBJECT: a red barrel with iron hoops. SETTING: the wet '
            'stone quay at Kattenburg, Amsterdam, 1671. LIGHT: plain '
            'overcast daylight. BACKGROUND: moored hulls. PEOPLE: none.',
        },
        reads={
            'pd_prose_ok': 'the prose form pass rate against the key.',
            'pd_structure_needed': 'yes if tags or the template beat prose by a whole seed, partial if they tie, no if prose wins — "structure needed" is a claim about this model, not a preference.',
            'pd_house_template': 'the template form pass rate; yes means the house template is safe to standardise on for this row.',
        },
        state_note='Three forms of ONE brief, same key, same seeds. The three cells are the '
        'three pass rates and the comparison between them.',
    ),
    _probe(
        'pd_example_needed',
        'Prompt clarity: does a reference picture beat words',
        ['pd_example_needed'],
        CLARITY_LADDER[3],
        CLARITY_KEY,
        pair=['words only', 'the same words plus the reference picture'],
        inputs_note='the paired run adds inputs.image; on t2i, which has no image slot, the '
        'paired run is the same words plus the rung-5 brief instead',
        fixture={
            'path': 'capability_tests/fixtures/image/reference/red_barrel_quay.png',
            'generated': 'the t2i default test, row sdxl_base, pd_clarity_ladder rung 5, '
            'seed 11, the frame the operator passed',
            'verified': False,
            'blocks': ['pd_example_needed'],
            'how_to_verify': 'the operator looks at the frame and confirms it shows one '
            'red hooped barrel on an empty 1671 quay; until then this '
            'column is untested with the note "reference unverified"',
        },
        state_note='yes if the reference raises the pass rate by a whole seed, partial if it '
        'ties, no if it lowers it. On a row with no image lever the second half of '
        'the pair is the longer brief and the state_note on the cell says so.',
    ),
    _probe(
        'pd_jargon_needed',
        'Prompt clarity: trade words against plain words',
        ['pd_jargon_needed'],
        'A red barrel on a stone quay in Amsterdam, 1671, strong light from one side, the '
        'shadowed side still readable, shallow focus, the background soft.',
        [
            {'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 1},
            {'check': 'colour_of_thing', 'thing': 'wooden barrel', 'colour': 'red', 'min_share': 0.4},
            {
                'check': 'operator',
                'question': 'Is the light strong from one side with the shadow side still readable, and is the background clearly softer than the barrel? yes/no',
            },
        ],
        pair=[
            'plain words (the prompt above)',
            'the trade words: A red barrel on a stone quay in Amsterdam, 1671, dramatic '
            'chiaroscuro, Rembrandt lighting, 85mm at f1.4, shallow depth of field, bokeh.',
        ],
        state_note='Same picture asked for twice, once in plain words and once in the trade '
        'vocabulary. yes means the jargon is NEEDED (it lands and the plain words '
        'do not), partial means both work, no means plain words are enough — '
        'which is the answer the house prefers to find.',
    ),
]

# ── Prompt: limits — a length ladder whose LAST clause is always the red lantern ─────────────
LANTERN_TAIL = 'and a red lantern hangs on the wall at the far right of the frame'
FILLER_CLAUSES = [
    'the cobbles are wet and dark from the morning rain',
    'a coil of tarred hemp rope lies against the quay wall',
    'the brick warehouse gable behind is weathered and patched',
    'two gulls stand at the water edge without moving',
    'the water of the harbour is flat and grey',
    'a low overcast sky sits over the roofs',
    'the timber of the quay edge is scarred by mooring lines',
    'an empty handcart stands with its shafts on the ground',
    'the air is still and nothing is in motion',
    'the far bank of the harbour is just visible',
    'a wooden crate stands closed beside the warehouse door',
    'the light is plain and even with no sun in it',
]
LENGTH_RUNGS = [20, 60, 77, 120, 200, 400]
LENGTH_RULE = (
    'A rung of N words is built the same way every time: the opening "A red barrel stands on '
    'the stone quay at Kattenburg, Amsterdam, 1671, in plain daylight.", then FILLER_CLAUSES in '
    'order, repeating the list from the start when it runs out, joined with ", ", until the next '
    'clause would pass N words, then ", " and LANTERN_TAIL last. The lantern clause is ALWAYS '
    'the final clause, so what the ladder measures is how far into the prompt the model still '
    'reads. The runner builds the rungs from this rule and writes each finished prompt into the '
    'trial verbatim.'
)
LENGTH_KEY = [
    {'check': 'render_returned'},
    {'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 1},
    {'check': 'open_vocab_present', 'terms': ['lantern'], 'min_score': 0.3},
    {'check': 'colour_of_thing', 'thing': 'lantern', 'colour': 'red', 'min_share': 0.3},
]

PROBES.append(
    _probe(
        'pd_length_ladder',
        'Prompt limits: 20 to 400 words, the red lantern always last',
        ['pd_max_hard', 'pd_max_soft', 'pd_max_words', 'pd_truncation_loud', 'pd_min_len'],
        'A red barrel stands on the stone quay at Kattenburg, Amsterdam, 1671, in plain daylight, '
        'the cobbles are wet and dark from the morning rain, ' + LANTERN_TAIL,
        LENGTH_KEY + [{'check': 'log_warns', 'pattern': r'(?i)token|truncat|clip.*77|longer than'}],
        ladder=LENGTH_RUNGS,
        ladder_rule=LENGTH_RULE,
        reads={
            'pd_max_hard': 'the shortest rung at which render_returned FAILS (the queue errors or returns nothing). yes if no rung under 400 words fails, partial if only 400 fails, no if 200 or less fails.',
            'pd_max_soft': 'the shortest rung at which the lantern stops arriving on 3/3 seeds — the length past which the tail is silently dropped. yes if that is 200 or more, partial 120, no 77 or less.',
            'pd_max_words': 'pd_max_soft as a NUMBER of words, written into the cell note so two rows can be compared without reading the ladder.',
            'pd_truncation_loud': 'yes only if log_warns fires at the first rung where the lantern is lost — the model SAID it truncated. A silent drop is no, and for SDXL it is expected to be no.',
            'pd_min_len': 'the 20-word rung: yes if the whole key passes 3/3 at 20 words, partial 2/3.',
        },
        state_note='One ladder, five cells, no contradiction possible. Everything here is '
        'mechanical: the queue either returned a frame, GroundingDINO either found a red '
        'lantern, and the log either warned. pd_clip77 asks the same question at one '
        'fixed length and is the cell to quote when a row is SDXL.',
    )
)

PROBES += [
    _probe(
        'pd_clip77',
        'Prompt limits: does anything past the 77-token window arrive',
        ['pd_clip77'],
        'A red barrel bound with iron hoops stands on the wet stone quay at Kattenburg, '
        'Amsterdam, 1671, in plain overcast daylight, the cobbles dark from the morning '
        'rain, a coil of tarred hemp rope against the quay wall, the brick warehouse gable '
        'behind weathered and patched, two gulls standing at the water edge without moving, '
        'the harbour water flat and grey, a low sky over the roofs, the timber quay edge '
        'scarred by mooring lines, an empty handcart with its shafts down, the air still, '
        'the far bank just visible, a closed crate beside the warehouse door, ' + LANTERN_TAIL,
        [
            {'check': 'clip_tokens_max', 'max': 300, 'tokenizer': 'openai/clip-vit-large-patch14'},
            {'check': 'open_vocab_present', 'terms': ['lantern'], 'min_score': 0.3},
            {'check': 'colour_of_thing', 'thing': 'lantern', 'colour': 'red', 'min_share': 0.3},
            {'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 1},
        ],
        state_note='The ONE probe in this bank that is deliberately over 60 words: 120 words, '
        'well past SDXL 77 CLIP tokens, with the red lantern in the LAST clause. '
        'Pass = the lantern appears. Wholly mechanical. A model with chunked or '
        'long-context conditioning (FLUX T5, Qwen) passes; a bare SDXL text '
        'encoder cannot, and the cell is then a true no rather than a guess. The '
        'clip_tokens_max check is set to 300 only to record the token count in the '
        'trial, not to gate.',
    ),
    _probe(
        'pd_unique_things',
        'Prompt limits: how many named things fit in one frame',
        ['pd_unique_things'],
        'On the stone quay at Kattenburg, Amsterdam, 1671, plain daylight: a red barrel, a '
        'blue crate, a coiled rope, a lantern, a handcart.',
        [
            {
                'check': 'open_vocab_present',
                'terms': ['wooden barrel', 'wooden crate', 'coiled rope', 'lantern', 'handcart'],
                'min_score': 0.3,
            }
        ],
        ladder=[3, 5, 8, 12, 16, 24],
        ladder_rule='rung N names the first N of: red barrel, blue crate, coiled rope, '
        'lantern, handcart, wicker basket, wooden bucket, iron anchor, ship '
        'wheel, oar, fishing net, glass bottle, pewter tankard, leather boot, '
        'wide-brimmed hat, folded sail, axe, ladder, birdcage, pair of scales, '
        'brass bell, spoked wheel, oil jar, coil of chain — in that order, same '
        'opening clause, joined with ", ". The check is open_vocab_present on all '
        'N terms; the unit is the COUNT of terms found, and the rung cell is the '
        'highest N where every term is found on 3/3 seeds.',
        unit='count',
        state_note='The cell is a NUMBER: the largest N all of whose things appear on all '
        'three seeds. Wholly mechanical (GroundingDINO at 0.3). Where a rung would '
        'take the prompt over 60 words the rung is rendered anyway — past rung 12 '
        'this probe and pd_clip77 measure the same wall, and the state_note on the '
        'cell says which.',
    ),
    _probe(
        'pd_unique_subjects',
        'Prompt limits: how many distinct PEOPLE fit in one frame',
        ['pd_unique_subjects'],
        'Two Dutch dockworkers stand on the Kattenburg quay, 1671, plain daylight: one in a '
        'red cap, one in a blue coat, both whole bodies in frame, facing the camera.',
        [
            {'check': 'detector_count', 'class': 'person', 'count': 2},
            {'check': 'detector_count', 'class': 'face', 'count': 2},
            {
                'check': 'operator',
                'question': 'Is every person in this picture told apart by the clothing the prompt gave them, with no two wearing the same thing? yes/no',
            },
        ],
        ladder=[2, 3, 4, 5],
        ladder_rule='rung N names N dockworkers, each with one distinguishing garment from: '
        'a red cap, a blue coat, a white apron, a black hat, a green scarf — in '
        'that order. The counts in the checks scale with N.',
        unit='count',
        state_note='A COUNT: the largest N where the person count, the face count and the '
        'operator all hold on 3/3. The detector decides the number; only the '
        'operator can say whether the garments were kept apart, which is the part '
        'that actually fails.',
    ),
    _probe(
        'pd_attrs_per_thing',
        'Prompt limits: how many attributes one thing can carry',
        ['pd_attrs_per_thing'],
        'A red barrel bound with three iron hoops stands on the stone quay at Kattenburg, '
        'Amsterdam, 1671, plain daylight.',
        [
            {'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 1},
            {'check': 'colour_of_thing', 'thing': 'wooden barrel', 'colour': 'red', 'min_share': 0.4},
        ],
        ladder=[1, 2, 3, 4, 5, 6],
        ladder_rule='the attributes are added to the one barrel in this order: (1) red, '
        '(2) three iron hoops, (3) standing upright, (4) a cracked stave on its '
        'left side, (5) wet, (6) a rope looped round its middle. Rung N carries '
        'the first N. The checks gain one mechanical test per attribute: hoops '
        'and rope by open_vocab_present, wet and the crack by a written operator '
        'question, upright by the operator.',
        unit='count',
        state_note='A COUNT: the most attributes the model holds on ONE object across 3/3 '
        'seeds. Attribute binding is where image models fail first, so each rung '
        'is scored on ALL its attributes, not on the newest one.',
    ),
    _probe(
        'pd_rules_ladder',
        'Prompt limits: how many separate instructions and constraints hold',
        ['pd_instructions', 'pd_constraints'],
        'A red barrel on the stone quay at Kattenburg, Amsterdam, 1671, plain daylight. Put '
        'the barrel on the left. Show nobody. Keep the sky out of the frame.',
        [
            {'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 1},
            {
                'check': 'spatial_relation',
                'a': 'wooden barrel',
                'b': 'stone quay',
                'relation': 'left_of',
                'margin_px': 0,
            },
            {'check': 'detector_count', 'class': 'person', 'count': 0},
            {'check': 'operator', 'question': 'Is the sky entirely out of this frame? yes/no'},
        ],
        ladder=[1, 2, 3, 4, 5, 6],
        ladder_rule='six cumulative rules, added in this order, each with its own mechanical '
        'test where one exists: (1) the barrel on the left [spatial_relation], '
        '(2) nobody in the frame [detector_count person 0], (3) no sky in the '
        'frame [operator], (4) exactly three gulls on the wall '
        '[detector_count bird 3], (5) the word HARING on the crate [ocr_equals], '
        '(6) no hat anywhere [open_vocab_absent]. Rung N carries rules 1..N and '
        'is scored on all of them.',
        unit='count',
        reads={
            'pd_instructions': 'the largest N where every POSITIVE rule (1, 4, 5) holds on 3/3.',
            'pd_constraints': 'the largest N where every NEGATIVE rule (2, 3, 6) holds on 3/3 — the forbidding kind, which is the kind that slips.',
        },
        state_note='Two cells off one cumulative ladder, split by the KIND of rule, because '
        'the house sees positive rules hold long after the forbidding ones have '
        'stopped. Five of the six rules are mechanical; "no sky" is the operator.',
    ),
    _probe(
        'pd_order_wins',
        'Prompt limits: the front of the prompt against the end of it',
        ['pd_order_wins'],
        'A red barrel stands on the stone quay at Kattenburg, Amsterdam, 1671, in plain '
        'daylight, the cobbles wet from the rain, a coil of rope against the wall, a brick '
        'gable behind, the harbour flat and grey, and the barrel is blue.',
        [
            {'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 1},
            {'check': 'colour_of_thing', 'thing': 'wooden barrel', 'colour': 'red', 'min_share': 0.4},
            {'check': 'colour_of_thing', 'thing': 'wooden barrel', 'colour': 'blue', 'max_share': 0.1},
        ],
        pair=[
            'red first and blue last (the prompt above)',
            'the same prompt with the two colour words swapped: blue at the front, red at the end',
        ],
        state_note='Wholly mechanical: whichever colour wins, the pixels say so. yes means '
        'the FRONT wins in both halves of the pair (the house standing rule for '
        'SDXL); partial means it flips with the order; no means the END wins. The '
        'checks as written score the first half; the runner inverts them for the '
        'second half and the trial holds both.',
    ),
    _probe(
        'pd_negative_len',
        'Prompt limits: how long a negative prompt still does work',
        ['pd_negative_len'],
        'A Dutch shipwright stands alone on the Kattenburg quay, 1671, plain daylight, whole '
        'body in frame, facing the camera, wearing a wide-brimmed hat.',
        [
            {'check': 'open_vocab_absent', 'terms': ['hat'], 'min_score': 0.3},
            {'check': 'detector_count', 'class': 'person', 'count': 1},
        ],
        ladder=[5, 20, 50, 100],
        ladder_rule='the negative prompt for this probe ONLY is: "hat" plus the first N-1 '
        'words of the shared NEGATIVE, so the term that must do the work ("hat") '
        'is always first and the negative grows around it. The positive prompt '
        'asks for the hat; the negative forbids it.',
        unit='count',
        state_note='A COUNT of negative words past which the first term stops working. '
        'Mechanical: GroundingDINO either finds a hat or it does not. This is the '
        'only probe that changes the shared negative, and it changes it by rule.',
    ),
    _probe(
        'pd_weight_range',
        'Prompt limits: how far a numeric term weight can be pushed',
        ['pd_weight_range'],
        'A (red:1.0) barrel on the stone quay at Kattenburg, Amsterdam, 1671, plain daylight.',
        [
            {'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 1},
            {'check': 'colour_of_thing', 'thing': 'wooden barrel', 'colour': 'red', 'min_share': 0.4},
            {
                'check': 'operator',
                'question': 'Is this picture free of burn-in — no blown-out colour, no posterised blocks, no melted edges? yes/no',
            },
        ],
        ladder=[1.0, 1.2, 1.5, 2.0, 3.0],
        ladder_rule='rung W renders "(red:W)" and nothing else changes.',
        unit='count',
        state_note='Image models DO have numeric prompt weighting (the (term:w) syntax the '
        'house comfy graphs parse), unlike text models where this column is na. '
        'The cell is the HIGHEST weight at which the colour still lands and the '
        'frame is not burnt: the colour half is mechanical, the burn-in half is '
        'the operator. A row whose workflow does not parse the syntax at all '
        'fails rung 1.0 and the trial note says the syntax was ignored, which is '
        'a different finding from a narrow range.',
    ),
    _probe(
        'pd_count_words',
        'Prompt limits: does a written number become that many things',
        ['pd_count_words'],
        'Three white gulls stand on the stone quay at Kattenburg, Amsterdam, 1671, plain '
        'daylight, nothing else in frame.',
        [{'check': 'detector_count', 'class': 'bird', 'count': 3}],
        ladder=[2, 3, 5, 7],
        ladder_rule='rung N writes the number as a WORD (two, three, five, seven) and the '
        'check counts N birds. A second pass writes the same rungs as DIGITS '
        '(2, 3, 5, 7); the trial holds both so the cell can say whether the word '
        'form and the digit form differ.',
        unit='count',
        state_note='Wholly mechanical (YOLO bird). The cell is the largest N the model gets '
        'right on 3/3 seeds. Read beside count_exact and count_large, which ask '
        'the same of other subjects; this column is specifically about the NUMBER '
        'WORD in the prompt, which is why both the word and the digit forms run.',
    ),
]
