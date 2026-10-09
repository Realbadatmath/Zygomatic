# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""image_shared.attributes — attribute probes and the four universal columns."""

from __future__ import annotations

from capability_tests.image_shared.conditions import COND_RENDER
from capability_tests.image_shared.probes import PROBES, _probe
from capability_tests.image_shared.count_space import _SP_SCENE

# ── Attributes ─────────────────────────────────────────────────────────────────────────────
PROBES += [
    _probe(
        'at_colour_named',
        'Attributes: one named colour on one thing',
        ['at_colour_named'],
        'A green wooden barrel stands alone' + _SP_SCENE,
        [
            {'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 1},
            {'check': 'colour_of_thing', 'thing': 'wooden barrel', 'colour': 'green', 'min_share': 0.45},
        ],
        state_note='Wholly mechanical against COLOUR_BANDS. Green because it is the colour a '
        'model is least likely to produce by accident on a barrel, so the cell '
        'measures obedience rather than luck.',
    ),
    _probe(
        'at_colour_two',
        'Attributes: two colours bound to two things',
        ['at_colour_two'],
        'A green wooden barrel on the left and a yellow wicker basket on the right, standing '
        'apart from one another' + _SP_SCENE,
        [
            {'check': 'colour_of_thing', 'thing': 'wooden barrel', 'colour': 'green', 'min_share': 0.45},
            {'check': 'colour_of_thing', 'thing': 'wicker basket', 'colour': 'yellow', 'min_share': 0.45},
            {'check': 'colour_of_thing', 'thing': 'wooden barrel', 'colour': 'yellow', 'max_share': 0.1},
            {'check': 'colour_of_thing', 'thing': 'wicker basket', 'colour': 'green', 'max_share': 0.1},
        ],
        state_note='The classic attribute-binding test, and the reason this bank has a colour '
        'check at all. Four mechanical facts: each colour must be ON its thing and '
        'OFF the other. A swap fails, and so does a bleed. No operator needed.',
    ),
    _probe(
        'at_material',
        'Attributes: the material a thing is made of',
        ['at_material'],
        'A wicker basket and a copper pot stand side by side on a plain wooden table in plain '
        'daylight, nothing else in frame.',
        [
            {'check': 'open_vocab_present', 'terms': ['wicker basket', 'copper pot'], 'min_score': 0.3},
            {
                'check': 'operator',
                'question': 'Is the basket plainly woven wicker and the pot plainly copper, each the material named and not the other? yes/no',
            },
        ],
        state_note='Operator-led: no house detector reports a material. GroundingDINO '
        'confirms both things are present, which stops an empty table passing.',
    ),
    _probe(
        'at_texture',
        'Attributes: a named surface texture',
        ['at_texture'],
        'A rough unplaned oak plank and a smooth polished oak plank lie side by side on a '
        'stone floor in plain daylight, nothing else in frame.',
        [
            {'check': 'open_vocab_count', 'query': 'wooden plank', 'min_score': 0.3, 'count': 2},
            {
                'check': 'operator',
                'question': 'Is one plank plainly rough and splintery and the other plainly smooth and polished? yes/no',
            },
        ],
        state_note='Operator-led. The pair in one frame is deliberate: a texture claim about '
        'one plank alone is not falsifiable, a contrast between two is.',
    ),
    _probe(
        'at_age_object',
        'Attributes: new against old',
        ['at_age_object'],
        'A brand-new rope and an old frayed grey rope lie coiled side by side' + _SP_SCENE,
        [
            {'check': 'open_vocab_count', 'query': 'coiled rope', 'min_score': 0.3, 'count': 2},
            {
                'check': 'operator',
                'question': 'Is one rope plainly new and clean and the other plainly old, greyed and frayed? yes/no',
            },
        ],
        state_note='Operator-led, same contrast-pair reasoning as at_texture. Period ageing is '
        'what the house buys these rows for, so the cell is worth an operator '
        'minute rather than a guess.',
    ),
    _probe(
        'at_size',
        'Attributes: a named absolute size',
        ['at_size'],
        'A wooden barrel as tall as a man stands beside a Dutch shipwright'
        + _SP_SCENE.replace('nobody present.', 'his whole body in frame.'),
        [
            {'check': 'detector_count', 'class': 'person', 'count': 1},
            {'check': 'spatial_relation', 'a': 'wooden barrel', 'b': 'person', 'relation': 'apart', 'margin_px': 0},
            {
                'check': 'operator',
                'question': 'Is the barrel about as tall as the man — not knee-high, not twice his height? yes/no',
            },
        ],
        state_note='A size claim needs something to measure against, so the man is in the '
        'frame on purpose. The boxes establish that both are there and separate; '
        'the ratio is the operator, because a barrel behind the man would give a '
        'true box ratio and a false answer.',
    ),
    _probe(
        'at_state',
        'Attributes: open against shut',
        ['at_state'],
        'A wooden door standing wide open in a brick wall, Amsterdam, 1671, plain daylight, '
        'seen straight on, the dark interior visible through the opening.',
        [
            {'check': 'open_vocab_count', 'query': 'door', 'min_score': 0.3, 'count': 1},
            {
                'check': 'operator',
                'question': 'Is the door plainly wide open with the space behind it visible, rather than shut or ajar? yes/no',
            },
        ],
        state_note='Operator-led. Open/shut is a state no detector in the house reports, and '
        'it is the state the house asks for most on architecture rows.',
    ),
    _probe(
        'at_wet_dry',
        'Attributes: wet against dry',
        ['at_wet_dry'],
        'Two lengths of grey wool cloth lie side by side on a stone floor in plain daylight, '
        'the left one soaked and dark with water, the right one dry, nothing else in frame.',
        [
            {'check': 'open_vocab_count', 'query': 'cloth', 'min_score': 0.3, 'min': 1},
            {
                'check': 'operator',
                'question': 'Is the left cloth plainly soaking wet and the right one plainly dry? yes/no',
            },
        ],
        state_note='Operator-led, contrast pair. Wetness is the attribute the house needs for '
        'rain and harbour work and the one no metric reports.',
    ),
    _probe(
        'at_clean_dirty',
        'Attributes: clean against dirty',
        ['at_clean_dirty'],
        'Two white linen aprons hang side by side on a wooden rail in plain daylight, the '
        'left one clean and white, the right one filthy with mud and soot, nothing else in frame.',
        [
            {'check': 'colour_of_thing', 'thing': 'left apron', 'colour': 'white', 'min_share': 0.6},
            {'check': 'colour_of_thing', 'thing': 'right apron', 'colour': 'white', 'max_share': 0.3},
            {
                'check': 'operator',
                'question': 'Is the left apron plainly clean and the right one plainly filthy? yes/no',
            },
        ],
        state_note='Half mechanical for once: the dirty apron must have measurably less white '
        'in it than the clean one, which catches the common failure of two '
        'identical clean aprons. The operator confirms the dirt is dirt.',
    ),
    _probe(
        'at_emotion',
        'Attributes: a named expression on a face',
        ['at_emotion'],
        'Head and shoulders of a Dutch shipwright, 1671, plain daylight, plainly angry, '
        'brows down and mouth set, facing the camera, plain grey wall behind him.',
        [
            {'check': 'detector_count', 'class': 'face', 'count': 1},
            {'check': 'face_emotion_top', 'expect': ['angry']},
            {
                'check': 'operator',
                'question': 'Does this man look plainly angry, rather than neutral, sad or merely serious? yes/no',
            },
        ],
        state_note='The one place a classifier reports an attribute directly, so both halves '
        'run: the pinned expression classifier must put "angry" on top AND the '
        'operator must agree. Where they disagree the trial keeps both and the '
        'cell follows the operator, because the classifier was trained on modern '
        'photographs and these are period portraits.',
    ),
]

# ── the four universal columns that need a run of their own ────────────────────────────────
U_PROMPT = (
    'A Dutch shipwright stands alone on the Kattenburg quay, 1671, plain daylight, '
    'whole body in frame, facing the camera.'
)

PROBES += [
    _probe(
        'u_deterministic',
        'Reliability: the same seed twice',
        ['deterministic'],
        U_PROMPT,
        [{'check': 'identical_images'}, {'check': 'render_returned'}],
        conditions=dict(COND_RENDER, seeds=[11, 11, 11], repeats=3),
        state_note='The ONE probe that does not use three different seeds: the same seed '
        'three times, and the three PNGs must be byte-identical once PNG metadata '
        'is stripped. Wholly mechanical. A row that is not deterministic at a '
        'fixed seed cannot be compared across a model change at all, so this cell '
        'is read before any other on the sheet. Listed as a probe and not a derive '
        'because nothing in the other probes holds a seed still.',
    ),
    _probe(
        'u_failsafe',
        'Reliability: what happens when the queue is not there',
        ['failsafe'],
        U_PROMPT,
        [
            {'check': 'render_returned'},
            {
                'check': 'log_contains',
                'path': 'the runner own log for this trial',
                'pattern': r'(?i)refused|unreachable|timeout|connection',
            },
            {
                'check': 'operator',
                'question': 'Did the house report a clear failure for this render, naming the unreachable service, rather than reporting success or going silent? yes/no',
            },
        ],
        conditions=dict(
            COND_RENDER,
            repeats=1,
            transport_override='the same transport pointed at http://127.0.0.1:1, which refuses every connection',
        ),
        state_note='render_returned must FAIL here and the runner inverts it: a frame coming '
        'back from a dead queue would mean a cached or invented result, which is '
        'the worst outcome on the sheet. yes needs a named error in the log and '
        'the operator confirming the house said so. One repeat, because a refused '
        'connection does not vary.',
    ),
    _probe(
        'u_degrades',
        'Reliability: the same renders with the GPU already busy',
        ['degrades'],
        U_PROMPT,
        [
            {'check': 'render_returned'},
            {'check': 'detector_count', 'class': 'person', 'count': 1},
            {
                'check': 'operator',
                'question': 'Is this picture as good as the one made on an idle machine — same subject, same finish, nothing cut short? yes/no',
            },
        ],
        conditions=dict(
            COND_RENDER,
            repeats=3,
            load='a second process holding 12 GB of VRAM and one GPU stream busy '
            'for the whole probe, started before the first render and left '
            'running until the last',
        ),
        load_subset=['render_person_one', 'render_hand_two', 'render_text_word', 'render_animal_horse'],
        state_note='Four subjects from DEGRADE_SUBSET are re-rendered under load and compared '
        'with their idle runs: the frames must still come back, still hold the key, '
        'and still look the same to a blind operator. Slower is NOT a failure here '
        '— speed is derived separately; a changed or truncated picture is. A row '
        'that OOMs under load is a no with the OOM in the note, not untested: '
        'falling over on a busy machine is what the column asks about.',
    ),
    _probe(
        'u_offline',
        'Operability: the same renders with no network',
        ['offline'],
        U_PROMPT,
        [
            {'check': 'render_returned'},
            {'check': 'detector_count', 'class': 'person', 'count': 1},
            {
                'check': 'log_contains',
                'path': 'the runner own log for this trial',
                'pattern': r'(?i)^(?!.*(huggingface|civitai|https?://(?!127\.0\.0\.1|localhost)))',
            },
        ],
        conditions=dict(
            COND_RENDER,
            repeats=3,
            network='the whole render runs inside `unshare -n`, so there is no network at all and no DNS',
        ),
        state_note='Wholly mechanical: with the network taken away the render either happens '
        'or it does not. A row that needs to reach huggingface for a weight it '
        'claims to have pinned fails here, which is exactly the finding the column '
        'is for. The log check records any outbound host that was attempted.',
    ),
]
