# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""audio_shared: Prompt — clarity needed. How much writing a row needs before it obeys."""

from __future__ import annotations

from .settings import CLAP_MIN, CLAP_NULL_MARGIN, COND_JUDGE, COND_SOUND
from .fixtures import BASE_CHECKS, BASE_PROMPT, PROBES, _probe

# ── Prompt: clarity needed — how much writing the row needs before it obeys ────────────
# One subject, five rungs of increasing specification, the SAME mechanical target at every rung.
# The rungs are verbatim; a runner may not interpolate between them.
CLARITY_RUNGS = [
    ('r1_bare', 'knocking'),
    ('r2_subject', 'knocking on a door'),
    ('r3_counted', 'three slow knocks on a wooden door'),
    ('r4_placed', 'three slow knocks on a wooden door, then silence, interior, close'),
    ('r5_full', BASE_PROMPT),
]
PROBES.append(
    _probe(
        'pd_clarity_ladder',
        'Prompt: the clarity ladder (5 rungs, one target)',
        ['pd_clarity_floor', 'pd_terse_ok', 'pd_detail_helps', 'pd_sweet_spot', 'pd_min_len'],
        list(BASE_CHECKS)
        + [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this three separate knocks on wood, and only that? yes/no',
            }
        ],
        cond=dict(COND_SOUND),
        inputs={'prompt': 'LADDER', 'task': 'render each rung of `ladder` verbatim'},
        ladder=[dict(rung=_r, prompt=_p) for _r, _p in CLARITY_RUNGS],
        unit='rung',
        state_note=(
            'ONE ladder answers five columns, each read off the pass rate per rung:\n'
            '  pd_clarity_floor  the LOWEST rung that passes (r1-r2 -> yes, r3 -> partial, r4-r5 -> no)\n'
            '  pd_terse_ok       r1 or r2 passes -> yes; only r3+ -> no\n'
            '  pd_detail_helps   pass rate never falls as the rungs get longer -> yes; one '
            'dip -> partial; a fall from r3 to r5 (over-specification hurting) -> no\n'
            '  pd_sweet_spot     reported as the rung id with the highest pass rate, ties to '
            'the shortest — a value, not a yes/no\n'
            '  pd_min_len        the word count of the pd_clarity_floor rung, `unit: count`\n'
            'The operator answers the same blind question at every rung; the operator decides '
            'the sound, the onset count decides the obedience.'
        ),
    )
)

PROSE_VARIANTS = {
    'prose': 'Three slow knocks land on a wooden door inside a quiet room, close to the listener, '
    'and then everything goes silent. There is no music and nobody speaks.',
    'tags': 'knock, wooden door, x3, slow, interior, close, dry, silence after, no music, no voices',
    'template': 'SUBJECT: three slow knocks on a wooden door\nCOUNT: 3\nSPACE: interior, close, dry\n'
    'AFTER: silence\nEXCLUDE: music, voices\nLENGTH: 4 s',
}
PROBES.append(
    _probe(
        'pd_prose_vs_tags',
        'Prompt: prose, tag list and house template, same content',
        ['pd_prose_ok', 'pd_structure_needed', 'pd_house_template'],
        list(BASE_CHECKS),
        cond=dict(COND_SOUND),
        inputs={'prompt': PROSE_VARIANTS['prose'], 'variants': dict(PROSE_VARIANTS)},
        state_note=(
            'three writings of one content, scored with the same key:\n'
            '  pd_prose_ok          the prose variant passes\n'
            '  pd_structure_needed  INVERTED: prose fails while tags or template pass -> yes '
            '(it needs structure); prose passes -> no\n'
            '  pd_house_template    the template variant passes AND is the best of the three; '
            'if it merely ties, partial\n'
            'Mechanical throughout — the key is three onsets and a wooden door.'
        ),
    )
)

PROBES += [
    _probe(
        'pd_example_needed',
        'Prompt: needs an example to obey',
        ['pd_example_needed'],
        [
            {'check': 'onset_count', 'n': 5, 'tolerance': 0},
            {
                'check': 'clap_sequence',
                'labels': ['knocking on a wooden door', 'a door opening'],
                'order': True,
                'min': 0.24,
            },
        ],
        cond=dict(COND_SOUND),
        inputs={
            'prompt': 'five knocks on a wooden door in the rhythm short-short-long-short-short, then the door opens',
            'variants': {
                'no_example': 'five knocks on a wooden door in the rhythm short-short-long-short-short, then the door opens',
                'with_example': 'five knocks on a wooden door, then the door opens. '
                'The rhythm is written as X X --- X X, where X is a short knock, '
                '--- is a long one and a space is a gap of about 0.2 s: '
                'X X --- X X',
            },
        },
        state_note=(
            'INVERTED column: `yes` means the model did NOT need the example — the '
            'no_example variant already passes. Only with_example passes -> no (it needs '
            'one). Both fail -> the column is `no` with the note "fails either way". '
            'Mechanical: five onsets in order, and the opening after them.'
        ),
    ),
    _probe(
        'pd_jargon_needed',
        'Prompt: needs domain vocabulary',
        ['pd_jargon_needed'],
        [
            {
                'check': 'clap_label_min',
                'label': 'rope and rigging creaking',
                'min': CLAP_MIN,
                'margin': CLAP_NULL_MARGIN,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this rope under load creaking against wood on a ship, and only that? yes/no',
            },
        ],
        cond=dict(COND_SOUND),
        inputs={
            'prompt': 'rope creaking as it takes the weight of a sail, on a wooden ship, close',
            'variants': {
                'plain': 'rope creaking as it takes the weight of a sail, on a wooden ship, close',
                'jargon': 'the halyard creaking through a wooden block as the mainsail is sheeted home aboard a pinas, close',
            },
        },
        state_note=(
            'INVERTED: `yes` means plain English is enough (the plain variant passes). '
            'Only the jargon variant passes -> no, and the sheet says the row needs house '
            'vocabulary. The operator decides the sound; CLAP is the screen.'
        ),
    ),
    _probe(
        'pd_asks_back',
        'Prompt: says it is unsure instead of guessing',
        ['pd_asks_back'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Did the row REFUSE or ASK (an error, a question, an empty result with a '
                'reason) rather than silently render something? yes/no',
            },
            {
                'check': 'duration_s',
                'min': 0.0,
                'max': 4.4,
                'note': 'a refusal is often a 0-length render; a guess is always full length',
            },
        ],
        cond=dict(COND_SOUND),
        inputs={'prompt': 'the sound'},
        state_note=(
            'a prompt with no content at all. `yes` = the row said it could not tell '
            '(error text, a question, a refusal the runner records); `no` = it rendered '
            'a confident guess. The operator decides, because a refusal reaches us as '
            'text next to an empty file and no detector reads that. Most generative '
            'audio rows will be `no` and that is an honest answer, not a bug.'
        ),
    ),
    _probe(
        'pd_tag_vocab',
        'Prompt: works outside a fixed tag vocabulary',
        ['pd_tag_vocab'],
        [
            {'check': 'clap_label_min', 'label': 'pottery smashing', 'min': CLAP_MIN, 'margin': CLAP_NULL_MARGIN},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this a fired clay pot shattering on a hard floor, and only that? yes/no',
            },
        ],
        cond=dict(COND_SOUND),
        inputs={'prompt': 'a glazed earthenware pot shattering on a flagstone floor, one impact, close, dry'},
        state_note=(
            'the words "earthenware", "glazed", "flagstone" are outside any tag list the '
            'house or a vendor ships. `yes` = the row still lands the sound. The operator '
            'decides; CLAP\'s generic "pottery smashing" label is the screen, and the '
            'gap between the two is exactly what this column is about.'
        ),
    ),
    _probe(
        'pd_rubric_needed',
        'Prompt: needs the threshold spelled out',
        ['pd_rubric_needed'],
        [{'check': 'equals_key', 'accept': ['no', 'pass', 'usable']}],
        cond=dict(COND_JUDGE),
        inputs={
            'audio': 'capability_tests/fixtures/audio/judge/quiet_-26lufs.wav',
            'task': 'Is this take too quiet to ship? Answer yes or no.',
            'variants': {
                'bare': 'Is this take too quiet to ship? Answer yes or no.',
                'rubric': 'House standard: a take ships when integrated loudness is '
                'between -20 and -14 LUFS and true peak is at or below '
                '-1.0 dBTP. Is this take too quiet to ship? Answer yes or no.',
            },
        },
        fixture_key='judge/quiet_-26lufs.wav',
        state_note=(
            'the fixture is -26.0 LUFS by construction, which the house standard calls '
            'too quiet, so the key is `yes` for BOTH variants. INVERTED column: `yes` '
            'means the judge did NOT need the rubric (the bare variant already agrees '
            'with the key). Only the rubric variant agreeing -> no. Mechanical.'
        ),
    ),
    _probe(
        'pd_abstain',
        'Prompt: can answer "cannot tell"',
        ['pd_abstain'],
        [
            {
                'check': 'equals_key',
                'accept': ['cannot tell', 'unknown', 'not sure', 'unclear', 'cannot determine', '0', 'zero', 'none'],
            }
        ],
        cond=dict(COND_JUDGE),
        inputs={
            'audio': 'capability_tests/fixtures/audio/judge/silence.wav',
            'task': 'How many people are speaking in this recording? Answer with a number, '
            'or with the words "cannot tell" if the recording does not let you decide.',
        },
        fixture_key='judge/silence.wav',
        state_note=(
            'the fixture is 3 s of digital silence: there is no number to give, so '
            '"cannot tell" is the honest answer and 0 is accepted as equivalent (both '
            'are in the key). Mechanical. A judge that names any other number has no '
            'abstention.'
        ),
    ),
]
