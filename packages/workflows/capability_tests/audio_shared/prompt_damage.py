# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""audio_shared: Prompt — damage. One base, one variant per column, one invariant key."""

from __future__ import annotations

from .settings import CLAP_ABSENT_MAX, CLAP_MIN, CLAP_NULL_MARGIN, COND_JUDGE, COND_SOUND
from .fixtures import BASE_CHECKS, BASE_PROMPT, DAMAGE_VARIANTS, PROBES, _probe

# ── Prompt: damage — ONE base, one variant per column, one invariant key ───────────────
# Mirrors text_shared: the base task has a mechanically checkable answer (three onsets, still a
# wooden door), every variant carries the SAME meaning written worse, and every variant is scored
# with the IDENTICAL checks. A damage column is `yes` when the variant's answer equals the base's.
PROBES.append(
    _probe(
        'pd_base',
        'Prompt: the undamaged base',
        ['pd_damage'],
        list(BASE_CHECKS),
        cond=dict(COND_SOUND),
        inputs={'prompt': BASE_PROMPT},
        state_note=(
            'pd_damage is read ACROSS the whole band: the fraction of the 10 variant probes '
            'below that still pass BASE_CHECKS. All 10 pass -> yes (a weak prompt costs '
            'nothing); >= 4 -> partial; fewer -> no. The base itself must pass, or the whole '
            'band is untested with the note "base failed" — a model that cannot do the clean '
            'prompt tells us nothing about damage.'
        ),
    )
)
for _col, _text in DAMAGE_VARIANTS.items():
    PROBES.append(
        _probe(
            f'var_{_col}',
            f'Prompt: damage — {_col[3:].replace("_", " ")}',
            [_col],
            list(BASE_CHECKS),
            cond=dict(COND_SOUND),
            inputs={'prompt': _text},
            base='pd_base',
            damage=_col[3:],
            state_note=(
                'scored against the SAME key as pd_base, mechanically. The column is about the '
                'PROMPT, not the sound: three onsets and the wooden-door label must survive '
                'this rewriting. No operator check — there is nothing here a human decides '
                'better than librosa and CLAP.'
            ),
        )
    )

# Damage columns with their own shape (a variant of the base cannot express them).
PROBES += [
    _probe(
        'pd_contradiction',
        'Prompt: a contradiction',
        ['pd_contradiction'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this recording follow ONE of the two contradictory instructions '
                'cleanly (either loud OR whispered), rather than something muddled '
                'between them? yes/no',
            },
            {
                'check': 'lufs_range',
                'min': -40.0,
                'max': -8.0,
                'note': 'either resolution is in range; a muddled take is usually neither',
            },
        ],
        cond=dict(COND_SOUND),
        inputs={
            'prompt': 'a man shouting a single word at the top of his lungs, whispered very quietly, interior, close'
        },
        state_note=(
            'the OPERATOR decides. What is scored is PREDICTABILITY, not which side wins: '
            'a take that commits to one reading is a pass, a take that averages the two '
            'into an unusable mumble is a fail. All 3 repeats must resolve the SAME way '
            'or the column is partial at best.'
        ),
    ),
    _probe(
        'pd_negation',
        'Prompt: a negation',
        ['pd_negation'],
        [
            {'check': 'clap_absent_max', 'labels': ['music', 'a person speaking', 'singing'], 'max': CLAP_ABSENT_MAX},
            {'check': 'clap_label_min', 'label': 'rain on a roof', 'min': CLAP_MIN, 'margin': CLAP_NULL_MARGIN},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is there any music, speech or singing anywhere in this recording? yes/no '
                '(a YES is a FAIL of this column)',
            },
        ],
        cond=dict(COND_SOUND),
        inputs={'prompt': 'heavy rain on a tiled roof, no music, no speech, no singing, no thunder'},
        state_note=(
            'mechanical first: CLAP must score the four negated labels BELOW '
            f'{CLAP_ABSENT_MAX} while the asked-for label clears the floor. The operator '
            'is the tie-break because CLAP is weak on quiet speech under noise, and the '
            'operator question is INVERTED here — the blind answer "yes, there is music" '
            'is a failing trial.'
        ),
    ),
    _probe(
        'pd_unstated',
        'Prompt: what is unstated is not invented',
        ['pd_unstated'],
        [
            {
                'check': 'clap_absent_max',
                'labels': ['music', 'a person speaking', 'birds chirping', 'a dog barking'],
                'max': CLAP_ABSENT_MAX,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this recording contain anything OTHER than a single bucket of water '
                'being poured out? yes/no (a YES is a FAIL of this column)',
            },
        ],
        cond=dict(COND_SOUND),
        inputs={'prompt': 'a bucket of water poured out onto stone'},
        state_note=(
            'the prompt names ONE thing and says nothing about room, music, weather or '
            'people. A model that adds a bed of birdsong or a music sting has invented '
            'what was unstated. The operator decides; the CLAP absence list is the '
            'screen for the four inventions we see most often.'
        ),
    ),
    _probe(
        'pd_bleed',
        'Prompt: a term lands only on its own subject',
        ['pd_bleed'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Are there two sounds here, with ONLY the bell being distant and echoing '
                'while the footsteps stay close and dry? yes/no',
            },
            {'check': 'clap_labels_all_min', 'labels': ['a church bell', 'footsteps on wooden boards'], 'min': 0.26},
            {
                'check': 'rt60_range',
                'min': 0.0,
                'max': 0.35,
                'window': 'the last 0.5 s after the final footstep, bell excluded by band-pass 2-8 kHz',
                'note': 'if the reverb bled onto the footsteps this window is far longer',
            },
        ],
        cond=dict(COND_SOUND),
        inputs={'prompt': 'close dry footsteps on wooden boards, and a distant church bell with a long echo, interior'},
        state_note=(
            'the OPERATOR decides whether the "distant, long echo" bled onto the '
            'footsteps. The RT60 window is a real mechanical screen for the commonest '
            'bleed (the whole render drowned in one reverb) and the CLAP pair proves '
            'both subjects are actually present.'
        ),
    ),
    _probe(
        'pd_leak',
        'Prompt: prompt text cannot leak into the output',
        ['pd_leak'],
        [
            {
                'check': 'transcript_absent_terms',
                'terms': ['interior', 'close', 'no music', 'dry', 'foley', 'prompt', 'seconds', 'wooden door'],
                'applies_to': 'speech',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does a voice read out any part of the instruction (words like "interior", '
                '"close", "no music", "48 kHz")? yes/no (a YES is a FAIL)',
            },
        ],
        cond=dict(COND_SOUND),
        inputs={'prompt': 'interior, close, dry, no music: three slow knocks on a wooden door, 4 seconds, 48 kHz mono'},
        state_note=(
            'mechanical for any row that can produce speech: Whisper the render and look '
            'for the instruction words. For a pure sfx row the transcript check is '
            'vacuous and the operator decides alone — the failure mode there is a '
            'text-to-speech artefact muttering the tags under the sound.'
        ),
    ),
    _probe(
        'pd_meta_literal',
        'Prompt: meta words are not taken literally',
        ['pd_meta_literal'],
        [
            {'check': 'clap_absent_max', 'labels': ['a person speaking', 'a bell', 'writing'], 'max': CLAP_ABSENT_MAX},
            {'check': 'clap_label_min', 'label': 'a horse galloping', 'min': CLAP_MIN, 'margin': CLAP_NULL_MARGIN},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this just a horse galloping, with nothing that sounds like someone '
                'saying or ringing the word "cue"? yes/no',
            },
        ],
        cond=dict(COND_SOUND),
        inputs={'prompt': 'on the cue, a horse galloping past on a dirt road; the cue itself is not a sound'},
        state_note=(
            'the OPERATOR decides. The mechanical screen catches the literal readings we '
            'have actually seen (a spoken "cue", a bell used as a cue tone). A model that '
            'renders the stage direction as audio has taken a meta word literally.'
        ),
    ),
    _probe(
        'pd_damage_visible',
        'Prompt: a bad prompt fails loudly',
        ['pd_damage_visible'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Listening to this alone, is it OBVIOUS that something went wrong '
                '(noise, silence, an unrelated sound) rather than plausible-but-wrong? yes/no',
            },
            {
                'check': 'clap_label_min',
                'label': 'noise',
                'min': 0.24,
                'note': 'a loud failure usually scores as noise; a quiet failure does not',
            },
            {
                'check': 'duration_s',
                'min': 0.1,
                'max': 4.4,
                'note': 'an empty file or a 0-length render is itself a loud failure and passes',
            },
        ],
        cond=dict(COND_SOUND),
        inputs={'prompt': 'qwrtp zzxv mmmk brrlg, tttt hhhh, 9 9 9'},
        state_note=(
            'deliberately meaningless input. `yes` means the failure ANNOUNCES itself '
            '(noise, silence, or an error the runner records); `no` means the model '
            'returned something confident and wrong that an operator would ship. The '
            'operator decides — this column is about how the failure LOOKS, and no '
            'detector can judge that. A transport error here is a PASS, recorded as '
            'the loudest possible failure.'
        ),
    ),
    _probe(
        'pd_text_vs_style',
        'Prompt: style prompt and content agree',
        ['pd_text_vs_style'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this sound like a small dry period interior (no modern gear, no '
                'synth, no big studio reverb) AND contain the pouring? yes/no',
            },
            {'check': 'clap_label_min', 'label': 'pouring water', 'min': CLAP_MIN, 'margin': CLAP_NULL_MARGIN},
            {'check': 'clap_absent_max', 'labels': ['electronic music', 'a synthesizer'], 'max': CLAP_ABSENT_MAX},
            {'check': 'rt60_range', 'min': 0.0, 'max': 0.6},
        ],
        cond=dict(COND_SOUND),
        inputs={
            'prompt': 'seventeenth-century Dutch interior, small room, dry, no modern equipment: '
            'wine poured from a stoneware jug into a pewter cup'
        },
        state_note=(
            'the OPERATOR decides whether the style sentence and the content sentence '
            'ended up describing the same recording. RT60 and the CLAP absence list are '
            'the mechanical screen for the two ways this breaks: a modern studio reverb '
            'and a synth pad under the foley.'
        ),
    ),
    _probe(
        'pd_spelling_sound',
        'Prompt: spelling does not distort pronunciation',
        ['pd_spelling_sound'],
        [
            {
                'check': 'transcript_contains_terms',
                'terms': ['Cornelis', 'Joost', 'Texel', 'pinas', 'Scheveningen', 'Gouda'],
                'applies_to': 'speech',
                'min_share': 1.0,
                'note': 'Whisper transcript of the render, accent-folded, case-insensitive',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Are all six Dutch names pronounced as a Dutch speaker would say them '
                '(not spelled out, not anglicised beyond recognition)? yes/no',
            },
        ],
        cond=dict(COND_SOUND),
        inputs={
            'prompt': 'Cornelis and Joost sailed from Scheveningen to Texel; the pinas carried Gouda cheese.',
            'task': 'Read this line aloud once, in a neutral voice, at a normal pace.',
        },
        state_note=(
            'mechanical FIRST: Whisper must recover all six names, which rules out '
            'letter-by-letter spelling and outright mangling. The operator then decides '
            'the pronunciation itself, blind, because Whisper happily normalises an '
            'anglicised "Texel" back to the written form. A row that cannot speak takes '
            'this column from the step module.'
        ),
    ),
    _probe(
        'pd_punct_timing',
        'Prompt: punctuation drives timing predictably',
        ['pd_punct_timing'],
        [
            {
                'check': 'pause_longer',
                'at': 'after "rail."',
                'than': 'after "mallet,"',
                'by_ms': 120,
                'applies_to': 'speech',
            },
            {'check': 'pause_ms', 'at': 'the em dash after "twice"', 'min': 250, 'max': 1200, 'applies_to': 'speech'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Do the pauses fall where the punctuation is, with the full stop clearly '
                'longer than the comma? yes/no',
            },
        ],
        cond=dict(COND_SOUND),
        inputs={
            'prompt': 'Cornelis lays down his mallet, picks up the lantern and sets it on the rail. '
            'He counts the barrels twice — then he stops.',
            'task': 'Read this line aloud once, in a neutral voice, at a normal pace.',
        },
        state_note=(
            'fully mechanical where a transcript with word timings exists (Whisper '
            'large-v3 word timestamps): the comma pause, the full-stop pause and the '
            'em-dash pause are measured and compared. The operator check is the '
            'fallback for a row whose transcript has no word timings.'
        ),
    ),
]

# The three judging-prompt columns. audio_judges and diarization ARE audio rows, so this bank
# owns them: the fixture is a WAV, the question is written here, and the same clipped file is put
# to the judge three ways.
JUDGE_FIX = 'capability_tests/fixtures/audio/judge/clipped.wav'
JUDGE_Q_NEUTRAL = 'Does this recording clip? Answer yes or no.'
PROBES += [
    _probe(
        'pd_question_wording',
        'Prompt: the verdict survives a reworded question',
        ['pd_question_wording'],
        [{'check': 'same_as_key_across', 'variants': ['neutral', 'formal', 'blunt'], 'accept': ['yes']}],
        cond=dict(COND_JUDGE),
        inputs={
            'audio': JUDGE_FIX,
            'task': JUDGE_Q_NEUTRAL,
            'variants': {
                'neutral': JUDGE_Q_NEUTRAL,
                'formal': 'Assess whether this audio exhibits clipping. Answer yes or no.',
                'blunt': 'clipped? yes or no',
            },
        },
        fixture_key='judge/clipped.wav',
        state_note=(
            'mechanical: the fixture clips by construction (4 % of its samples sit at '
            'full scale), so the key is `yes` for all three wordings. All three agree with '
            'the key -> yes; two -> partial; fewer -> no.'
        ),
    ),
    _probe(
        'pd_leading',
        'Prompt: resists a leading question',
        ['pd_leading'],
        [{'check': 'equals_key', 'accept': ['no']}],
        cond=dict(COND_JUDGE),
        inputs={
            'audio': 'capability_tests/fixtures/audio/judge/clean.wav',
            'task': 'This take is badly clipped and unusable, everyone agrees. Confirm it clips: answer yes or no.',
        },
        fixture_key='judge/clean.wav',
        state_note=(
            'mechanical: the fixture does NOT clip (true peak -3.2 dBTP by '
            'construction), so the honest answer is `no` against a prompt that pushes '
            'hard for `yes`. Nothing for an operator to decide.'
        ),
    ),
    _probe(
        'pd_yes_bias',
        'Prompt: no default-yes bias',
        ['pd_yes_bias'],
        [{'check': 'equals_key', 'accept': ['no']}],
        cond=dict(COND_JUDGE),
        inputs={
            'audio': 'capability_tests/fixtures/audio/judge/silence.wav',
            'task': 'Is there a dog barking in this recording? Answer yes or no.',
        },
        fixture_key='judge/silence.wav',
        state_note=(
            'mechanical: the fixture is 3 s of digital silence (every sample zero), so '
            'every yes/no question about a sound in it is `no`. A judge that answers yes '
            'has a default-yes bias and nothing else explains it.'
        ),
    ),
]
