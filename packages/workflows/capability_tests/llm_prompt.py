# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Prompt building & expansion (llm_prompt). 2026-09-28.

Question the sheet asks: which model turns a short intent into a render prompt the
image/video model obeys? Ten fixed intents, one output contract, and — for `obeyed` — one
FIXED renderer, because a prompt's quality is what the picture does with it.

The counting and spatial bank is OVERRIDDEN here: for a prompt builder those questions mean
"does the count / relation the intent states survive into the prompt text", not "can it
reason about a passage". The shared probes are replaced by the fidelity probe on intent I10;
what the renderer then draws is the t2i sheet's business, not this one's.

Rows `racks` and `creature` are deterministic builders with no prompt: they are measured on
the string they emit (tokens, leaks, filler, negatives, determinism) and `na` on everything
that needs an intent, with the reason on each cell.
"""

from __future__ import annotations

from capability_tests.text_shared import KEYS, COND_LITERAL

CONTRACT = (
    'Return exactly this JSON and nothing else: {"positive": string, "negative": string, '
    '"engine": "sdxl"|"qwen_image"}. `positive` is the render prompt for the named engine; '
    '`negative` is what must NOT appear.'
)

PROMPT_SYSTEM = (
    'You turn a short production intent into a render prompt for a named image engine. For sdxl: '
    'comma-separated tags, the whole positive prompt under 77 CLIP tokens, subject first, then '
    'costume, then camera, then light, then style; put every unwanted element in the negative. For '
    'qwen_image: natural prose, 40-120 words, one paragraph. Never add quality filler '
    '(masterpiece, best quality, 8k, highly detailed, trending). Never restate the instruction. '
    'Keep every noun the intent names; qualify period nouns so a modern object cannot be drawn. '
    'Say what hands are doing. ' + CONTRACT
)

FILLER = [
    'masterpiece',
    'best quality',
    'highly detailed',
    'ultra detailed',
    '8k',
    '4k',
    'trending on artstation',
    'award winning',
    'award-winning',
    'stunning',
    'breathtaking',
    'beautiful',
    'cinematic masterpiece',
    'photorealistic, photorealistic',
    'high resolution',
    'hyperrealistic',
    'intricate details',
]
LEAK = [
    'the user',
    'the intent',
    'render prompt',
    'as requested',
    'prompt for',
    'expand',
    'expansion',
    'here is',
    'positive prompt',
    'negative prompt',
    'the following',
    'engine:',
    'json',
]
MODERN = [
    'motor',
    'engine',
    'steel hull',
    'steel',
    'yacht',
    'container',
    'crane truck',
    'concrete',
    'asphalt',
    'plastic',
    'neon',
    'streetlight',
    'street light',
    'electric',
    'wristwatch',
    'sneakers',
    'jeans',
    't-shirt',
    'zipper',
]
CLIP = {'tokenizer': 'openai/clip-vit-large-patch14', 'note': 'the real SDXL text-encoder tokenizer, not a word count'}

RENDER = {
    'sdxl': {
        'checkpoint': 'sd_xl_base_1.0.safetensors',
        'lora': None,
        'size': [1024, 1024],
        'steps': 30,
        'cfg': 7.0,
        'sampler': 'dpmpp_2m',
        'scheduler': 'karras',
        'seed': 7,
        'batch': 1,
        'note': 'base only — no LoRA, so the prompt is the only lever ([[project_comfy_lora_never_applied]])',
    },
    'qwen_image': {
        'checkpoint': 'the qwen_image checkpoint pinned in the ComfyUI store on the run date (record its digest)',
        'size': [1024, 1024],
        'steps': 30,
        'cfg': 4.0,
        'seed': 7,
        'batch': 1,
    },
    'rule': "one render per positive/negative pair per repeat; the operator judges the picture BLIND against the intent's element list",
}

BASE_CHECKS = [
    {'check': 'json_valid'},
    {'check': 'json_keys', 'keys': ['positive', 'negative', 'engine']},
    {'check': 'absent', 'terms': LEAK},
    {'check': 'absent', 'terms': FILLER},
]


def _intent(iid, title, feeds, intent, engine, checks, elements, **kw):
    p = {
        'id': iid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'system': 'PROMPT_SYSTEM', 'passage': None, 'prompt': f'Engine: {engine}. Intent: {intent}'},
        'conditions': dict(COND_LITERAL),
        'checks': BASE_CHECKS + list(checks),
        'grade': 'measured',
        'render': engine,
        'elements': elements,
    }
    p.update(kw)
    return p


INTENTS = [
    _intent(
        'i01_cornelis',
        'I1 — Cornelis with the lantern (costume, camera, light)',
        ['obeyed', 'costume', 'camera', 'light'],
        'Cornelis, a shipwright of fifty, on the Kattenburg quay at dusk, 1671, holding a lit lantern in his left hand; '
        'red wool cloak with brass buttons; full figure, low angle, 35mm; light from a single candle to his left',
        'sdxl',
        [
            {'check': 'clip_tokens_max', 'max': 77, **CLIP},
            {
                'check': 'present',
                'terms': [
                    'red',
                    'wool',
                    'cloak',
                    'brass',
                    'button',
                    'lantern',
                    'low angle',
                    '35mm',
                    'candle',
                    'left',
                    'full figure',
                ],
            },
            {'check': 'regex_absent', 'pattern': r'(?i)\b(blue|green|black|brown|grey|gray)\b[^,]{0,12}\bcloak\b'},
            {'check': 'absent', 'terms': MODERN},
        ],
        [
            'a man of about fifty',
            'red cloak with visible buttons',
            'lantern in the LEFT hand, lit',
            'low camera angle, whole body in frame',
            'light from the left, warm, single source',
        ],
    ),
    _intent(
        'i02_pinas',
        'I2 — the pinas at Kattenburg (period nouns)',
        ['obeyed', 'period_terms'],
        'a pinas moored at the Kattenburg yard, morning mist, wide shot, 1671',
        'sdxl',
        [
            {'check': 'clip_tokens_max', 'max': 77, **CLIP},
            {
                'check': 'present_any',
                'terms': [
                    'wooden',
                    'timber',
                    'sailing',
                    '17th-century',
                    'seventeenth-century',
                    'dutch sailing ship',
                    'three-masted',
                ],
            },
            {
                'check': 'regex_present',
                'pattern': r'(?i)\b(motor|engine|steel|yacht|container|modern)\b',
                'where': 'negative',
                'note': 'the modern reading of "vessel" goes in the NEGATIVE',
            },
            {'check': 'absent', 'terms': MODERN, 'where': 'positive'},
        ],
        [
            'a wooden sailing ship, not a motor vessel',
            'moored at a quay with a wooden crane or shipyard',
            'mist, morning light',
            'wide shot, ship whole',
            'nothing modern in frame',
        ],
    ),
    _intent(
        'i03_abel',
        'I3 — Abel and the ledger (hands)',
        ['obeyed', 'anatomy_terms'],
        'Abel, a boy of nine, alone in a dark farmhouse loft, 1671, reading a ledger by one candle; close on his hands turning a page',
        'sdxl',
        [
            {'check': 'clip_tokens_max', 'max': 77, **CLIP},
            {
                'check': 'regex_present',
                'pattern': r'(?i)\b(hands?|fingers?)\b[^,]{0,40}\b(turning|turns|holding|holds|resting|on the page|gripping)\b',
            },
            {'check': 'present', 'terms': ['boy', 'ledger', 'candle', 'loft']},
            {
                'check': 'regex_present',
                'pattern': r'(?i)\b(extra fingers|six fingers|deformed hands|fused fingers|missing fingers)\b',
                'where': 'negative',
            },
        ],
        [
            'a boy, not a man',
            'a bound book/ledger open',
            'both hands visible, one turning a page, five fingers each',
            'single candle light',
            'dark loft, straw or beams',
        ],
    ),
    _intent(
        'i04_anna_reuse',
        'I4 — the same as I1 with Anna (reuse)',
        ['reuse'],
        'Anna, a woman of thirty, on the Kattenburg quay at dusk, 1671, holding a lit lantern in her left hand; '
        'red wool cloak with brass buttons; full figure, low angle, 35mm; light from a single candle to her left',
        'sdxl',
        [
            {'check': 'clip_tokens_max', 'max': 77, **CLIP},
            {
                'check': 'present',
                'terms': [
                    'red',
                    'wool',
                    'cloak',
                    'brass',
                    'button',
                    'lantern',
                    'low angle',
                    '35mm',
                    'candle',
                    'left',
                    'full figure',
                ],
            },
            {'check': 'similarity_min', 'to': 'i01_cornelis', 'min': 0.6},
        ],
        [
            'a woman of about thirty',
            'red cloak with visible buttons',
            'lantern in the LEFT hand, lit',
            'low camera angle, whole body in frame',
            'light from the left',
        ],
        state_note='reuse = the I1 checks pass on I4 AND the prompt shape is the same (similarity ≥ 0.6 with only the subject swapped)',
    ),
    _intent(
        'i05_kaatje',
        'I5 — Kip Kaatje for Qwen-Image (per engine)',
        ['obeyed', 'per_engine'],
        "Kip Kaatje, a cheerful brown hen with a red comb, in a sunny farmyard beside a blue barn door, children's picture-book style, soft edges",
        'qwen_image',
        [
            {'check': 'word_count', 'min': 40, 'max': 130, 'where': 'positive'},
            {
                'check': 'regex_absent',
                'pattern': r'^(\s*[\w\- ]{1,24},){6,}',
                'where': 'positive',
                'note': 'not a tag list',
            },
            {'check': 'present', 'terms': ['hen', 'brown', 'red comb', 'blue', 'barn', 'farmyard']},
            {'check': 'regex_present', 'pattern': r'"engine"\s*:\s*"qwen_image"'},
        ],
        [
            'a hen, brown, with a red comb',
            'a blue barn door',
            'sunny farmyard',
            'picture-book style, soft',
            'nothing photographic or gritty',
        ],
        state_note='per_engine = the sdxl intents came back as ≤77-token tag lists AND this one came back as prose; both forms from the same model',
    ),
    _intent(
        'i06_cart',
        'I6 — the plague cart, no faces (negatives, refusal wording)',
        ['obeyed'],
        'a plague cart at night in the Jordaan, Amsterdam 1664, a boy with a bell walking ahead; no faces visible, no gore, no wounds',
        'sdxl',
        [
            {'check': 'clip_tokens_max', 'max': 77, **CLIP},
            {'check': 'regex_present', 'pattern': r'(?i)\b(faces?|gore|wounds?|blood)\b', 'where': 'negative'},
            {
                'check': 'regex_absent',
                'pattern': r'(?i)\bno (faces?|gore|wounds?)\b',
                'where': 'positive',
                'note': 'the fix goes in the negative, not as "no X" in the positive',
            },
            {
                'check': 'starts_clean',
                'banned': ["I can't", 'I cannot', "I'm not able", "I won't", 'Sorry', "I'm sorry", 'As an AI'],
            },
        ],
        [
            'a cart at night with a lantern or torch',
            'a boy with a bell ahead of it',
            'no readable faces',
            'no blood or wounds',
            'a 17th-century street, nothing modern',
        ],
    ),
    _intent(
        'i07_crane',
        'I7 — the crane from above (camera vocabulary)',
        ['obeyed', 'camera'],
        'a wooden treadwheel harbour crane on a quay, seen from directly above, isometric, midday, 1671',
        'sdxl',
        [
            {'check': 'clip_tokens_max', 'max': 77, **CLIP},
            {
                'check': 'present_any',
                'terms': ['from above', 'top-down', 'top down', "bird's-eye", 'birds-eye', 'overhead', 'isometric'],
            },
            {'check': 'present', 'terms': ['crane', 'quay', 'wooden']},
        ],
        [
            'a wooden crane with a treadwheel',
            'seen from above, not eye level',
            'a quay edge with water',
            'midday light, short shadows',
            'nothing modern',
        ],
    ),
    _intent(
        'i08_verbatim',
        'I8 — a verbatim instruction',
        ['verbatim'],
        'Anna at the yard gate at dawn. VERBATIM, include exactly: "tallow-lit, sea-green haze, wet cobbles"',
        'sdxl',
        [
            {'check': 'clip_tokens_max', 'max': 77, **CLIP},
            {'check': 'regex_present', 'pattern': r'tallow-lit, sea-green haze, wet cobbles', 'where': 'positive'},
            {'check': 'absent', 'terms': ['VERBATIM', 'include exactly']},
        ],
        ['a woman at a wooden gate', 'dawn', 'greenish haze', 'wet cobbles', 'warm lantern/tallow light'],
        state_note='verbatim = the quoted phrase appears character-exact in the positive and the word VERBATIM does not',
    ),
    {
        'id': 'i09_style_lock',
        'title': 'I9 — five intents, one style block (style lock)',
        'feeds': ['style_lock'],
        'inputs': {'system': 'PROMPT_SYSTEM', 'passage': None, 'prompt': 'SET'},
        'conditions': dict(COND_LITERAL),
        'set': [
            f'Engine: sdxl. Style for the whole set, keep it identical in every prompt: "Arcane painterly style, dark teal palette, visible brush texture". Intent: {s}'
            for s in [
                'Cornelis at the mallet, dusk',
                'Anna at the ledger, candle',
                'Joost coiling rope on the quay',
                'the pinas under a grey sky',
                'the yard dog Pim asleep by the bell',
            ]
        ],
        'checks': BASE_CHECKS
        + [
            {
                'check': 'regex_present',
                'pattern': r'Arcane painterly style, dark teal palette, visible brush texture',
                'where': 'positive',
            },
            {'check': 'clip_tokens_max', 'max': 77, **CLIP},
        ],
        'grade': 'measured',
        'render': 'sdxl',
        'state_note': 'yes when the style phrase is character-identical in all 5 × 3 prompts',
    },
    {
        'id': 'i10_fidelity',
        'title': 'I10 — counts and relations stated in the intent survive into the prompt',
        'feeds': list(KEYS.keys()),
        'inputs': {
            'system': 'PROMPT_SYSTEM',
            'passage': None,
            'prompt': 'Engine: qwen_image. Intent: render this passage as one picture, keeping every count and every spatial relation it states: '
            + 'PASSAGE',
        },
        'conditions': dict(COND_LITERAL),
        'checks': BASE_CHECKS
        + [
            {'check': 'regex_present', 'pattern': r'(?i)\b(three|3) (tarred )?barrels\b', 'col': 'count_exact'},
            {'check': 'regex_present', 'pattern': r'(?i)\b(fourteen|14) gulls\b', 'col': 'count_large'},
            {
                'check': 'regex_present',
                'pattern': r'(?i)\b(five|5) (people|figures)\b|\b(two|2) boys\b.*\bthree (named )?(people|figures|adults)\b|\bCornelis\b.*\bAnna\b.*\bJoost\b.*\b(two|2) boys\b',
                'col': 'count_people',
            },
            {
                'check': 'regex_present',
                'pattern': r'(?i)\b(two|2) (fingers )?missing\b|\bmissing (two|2) fingers\b|\b(eight|8) fingers\b|\bthree fingers on (his|the) left hand\b',
                'col': 'count_fingers',
            },
            {'check': 'regex_present', 'pattern': r'(?i)\bthree-legged dog\b', 'col': 'count_legs'},
            {
                'check': 'regex_present',
                'pattern': r'(?i)\b(four|4) windows\b.*\b(each|per) floor\b.*\b(gable|fifth|smaller)\b|\b(nine|9) windows\b',
                'col': 'count_windows',
            },
            {
                'check': 'regex_present',
                'pattern': r'(?i)\b(cat|cats)\b',
                'where': 'negative',
                'col': 'count_absent',
                'note': 'the absent thing must be in the NEGATIVE, not described in the positive',
            },
            {'check': 'regex_present', 'pattern': r'(?i)\b(seven|7) crates\b', 'col': 'count_more_less'},
            {
                'check': 'regex_present',
                'pattern': r'(?i)\bAnna\b[^.]{0,60}\b(on|to|at) (his|Cornelis\'s) left\b|\bleft of Cornelis\b',
                'col': 'sp_left_right',
            },
            {
                'check': 'regex_present',
                'pattern': r'(?i)\bcrates?\b[^.]{0,40}\bbehind\b[^.]{0,20}\bbarrels?\b|\bbehind (them|the barrels)\b[^.]{0,20}\bcrates\b',
                'col': 'sp_front_behind',
            },
            {
                'check': 'regex_present',
                'pattern': r'(?i)\bAnna\b[^.]{0,40}\b(holding|holds|with) (a |the )?lantern\b',
                'col': 'sp_holding_who',
            },
            {
                'check': 'regex_present',
                'pattern': r'(?i)\bbowl\b[^.]{0,30}\b(inside|in) the doorway\b|\bdoorway\b[^.]{0,30}\bbowl\b',
                'col': 'sp_inside',
            },
            {
                'check': 'regex_present',
                'pattern': r'(?i)\b(horse|cart)\b[^.]{0,40}\b(far end|distance|background|far)\b',
                'col': 'sp_near_far',
            },
            {
                'check': 'regex_present',
                'pattern': r'(?i)\bmast\b[^.]{0,50}\b(hides|hiding|blocks|blocking|in front of|obscur)\w*\b[^.]{0,30}\b(church )?tower\b',
                'col': 'sp_occlusion',
            },
            {
                'check': 'regex_present',
                'pattern': r'(?i)\bbell\b[^.]{0,30}\b(above|over) the door\b',
                'col': 'sp_on_under',
            },
            {
                'check': 'regex_present',
                'pattern': r'(?i)\b(smaller|small) (gable )?window\b[^.]{0,20}\bgable\b|\bgable\b[^.]{0,30}\bsmaller\b',
                'col': 'sp_relative_size',
            },
            {
                'check': 'regex_present',
                'pattern': r'(?i)\bleft hand\b[^.]{0,40}\b(on|resting on|touching) the rail\b',
                'col': 'sp_touching',
            },
            {
                'check': 'regex_present',
                'pattern': r'(?i)\bJoost\b[^.]{0,60}\bfacing the water\b|\bfacing the water\b[^.]{0,40}\bJoost\b',
                'col': 'sp_direction',
            },
        ],
        'grade': 'measured',
        'state_note': 'each `col` check writes ITS column: pass rate over 3 repeats. This measures whether the prompt SAYS it, not whether the renderer draws it (that is the t2i sheet).',
    },
    {
        'id': 'determinism',
        'title': 'Same intent, same prompt',
        'feeds': ['determinism'],
        'inputs': {
            'system': 'PROMPT_SYSTEM',
            'passage': None,
            'prompt': 'Engine: sdxl. Intent: Cornelis, a shipwright of fifty, on the Kattenburg quay at dusk, 1671, holding a lit lantern in his left hand',
        },
        'conditions': {'temperature': 0.0, 'seed': 11, 'max_tokens': 400, 'repeats': 3},
        'checks': [{'check': 'identical_runs'}],
        'grade': 'measured',
        'builtin_inputs': {
            'racks': 'RACKS default settings dict from movement_studio.py, called twice',
            'creature': 'the wolf body-plan lock, called twice',
        },
    },
    {
        'id': 'weights',
        'title': 'Uses prompt weighting correctly',
        'feeds': ['weights'],
        'inputs': {
            'system': 'PROMPT_SYSTEM',
            'passage': None,
            'prompt': 'Engine: sdxl. Intent: Anna on the quay; the lantern matters most, the cloak least. Use SDXL (term:weight) emphasis, weights between 0.8 and 1.4, on those two terms only.',
        },
        'conditions': dict(COND_LITERAL),
        'checks': BASE_CHECKS
        + [
            {'check': 'regex_present', 'pattern': r'\(lantern:1\.[1-4]\)', 'where': 'positive'},
            {'check': 'regex_present', 'pattern': r'\(cloak:0\.[89]\)|\(cloak:1\.0\)', 'where': 'positive'},
            {'check': 'regex_absent', 'pattern': r'\((?!lantern|cloak)[^:()]+:\d', 'where': 'positive'},
            {'check': 'regex_absent', 'pattern': r':\s*(0\.[0-7]|1\.[5-9]|[2-9]\.)\d*\)', 'where': 'positive'},
        ],
        'grade': 'measured',
    },
]

BUILTIN_REASON = 'deterministic builder: assembles a fixed phrase dictionary from a settings dict; there is no intent and no prompt to damage, so this question has nothing to measure on this row'
BUILTIN_NA_BANDS = [
    'Prompt: damage',
    'Prompt: clarity needed',
    'Prompt: limits',
    'Prompt: steering',
    'Counting & quantity',
    'Space & relation',
]
BUILTIN_NA_COLS = [
    'obeyed',
    'verbatim',
    'costume',
    'camera',
    'light',
    'period_terms',
    'anatomy_terms',
    'style_lock',
    'per_engine',
    'reuse',
] + list(KEYS.keys())

TEST = {
    'step': 'llm_prompt',
    'version': '2026-09-28.1',
    'title': 'Ten intents, one contract, one renderer',
    'purpose': "Measure whether an expanded prompt carries every noun, count and relation the intent stated, fits the engine's window, and is obeyed by a FIXED renderer judged blind.",
    'include_shared': 'text',
    'system_override': PROMPT_SYSTEM,
    'render': RENDER,
    'rows': {
        'sonnet5': {
            'transport': 'claude_cli',
            'model': 'claude-sonnet-5',
            'note': 'the arch assistant path: `claude -p --model sonnet` on the login',
        },
        'gptoss20b': {'budget': {'minutes': 30, 'gpu_minutes': 30}, 'transport': 'ollama', 'model': 'gpt-oss:20b'},
        'qwen36': {'budget': {'minutes': 30, 'gpu_minutes': 30}, 'transport': 'ollama', 'model': 'qwen3.6:35b-a3b'},
        'racks': {
            'transport': 'builtin',
            'model': 'movement_studio.py RACKS/_PARAMS',
            'na_bands': {'reason': BUILTIN_REASON, 'bands': BUILTIN_NA_BANDS},
            'na': {
                **{c: BUILTIN_REASON for c in BUILTIN_NA_COLS},
                **{
                    'obeyed': 'the rack prompt drives Wan video; whether the clip performs it is measured on the movement sheet, not here'
                },
            },
        },
        'creature': {
            'transport': 'builtin',
            'model': 'creature studio body-plan builder',
            'na_bands': {'reason': BUILTIN_REASON, 'bands': BUILTIN_NA_BANDS},
            'na': {
                **{c: BUILTIN_REASON for c in BUILTIN_NA_COLS},
                **{
                    'obeyed': 'KEEP THE RECEIPT already on the sheet (render-prompt gap: body-plan text the renderer did not act on); the run must not overwrite it'
                },
            },
        },
    },
    'probes': INTENTS,
    'derive': {
        'length': {
            'from': 'CLIP tokens of the positive prompt over every sdxl intent trial (max, mean in the note); builtin rows: tokens of the emitted string',
            'grade': 'measured',
            'unit': 'int',
        },
        'brevity': {
            'from': 'the `absent FILLER` check over every intent trial; yes when 0 filler terms in ≥ 90 % of trials',
            'grade': 'measured',
        },
        'no_leak': {'from': 'the `absent LEAK` check over every intent trial', 'grade': 'measured'},
        'negatives': {
            'from': 'over I2, I3, I6 and I10: the unwanted element is in the negative and not written as "no X" in the positive',
            'grade': 'measured',
        },
    },
    'lookup': {},
    'wiring': {},
    'na': {},
    'fixtures': [],
    'budget': {
        'calls': 170,
        'tokens_in': 445000,
        'tokens_out': 25000,
        'minutes': 25,
        'gpu_minutes': 5,
        'operator_minutes': 15,
        'note': (
            '56 probes x 3 repeats = ~170 calls per row. ~350 prompt tokens per call x 170 = 60k + the needle grid 128k x 3 once = 384k -> '
            '~445k in; ~150 tokens per answer x 170 = ~25k out. `obeyed` renders the ten intents x 3 repeats = 30 SDXL base pictures at '
            '~10 s = 5 GPU minutes on EVERY row (the renderer is fixed); ollama rows also hold the GPU for their own calls (override). '
            'Wall ~25 min; operator 9 blind questions x 3 = 27 decisions x 30 s = ~15 min.'
        ),
    },
    'notes': [
        "`obeyed` is the only column that needs the GPU: 8 sdxl intents + 1 qwen intent × 3 repeats × rows, one render each at the fixed settings; the operator ticks the intent's five elements blind. obeyed = mean share of elements present.",
        "The bank columns on this sheet mean prompt FIDELITY (does the count survive into the text), and I10 measures exactly that. The renderer's counting is on the t2i sheet.",
        'A builtin row is not "bad at prompts"; it has no prompt. Its na cells carry that reason so the sheet does not read as 60 failures.',
    ],
}
