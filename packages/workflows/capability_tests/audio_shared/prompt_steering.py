# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""audio_shared: Prompt — steering, plus the three universal columns that must be MEASURED."""

from __future__ import annotations

from .settings import CLAP_ABSENT_MAX, CLAP_MIN, CLAP_NULL_MARGIN, COND_ONE, COND_SOUND, SETTINGS
from .fixtures import BASE_LABEL, BASE_PROMPT, PROBES, _probe

# ── Prompt: steering — does a small edit give a small change ───────────────────────────
STEER_CHAIN = [
    ('a0_base', 'a heavy wooden door creaking open slowly, interior, close, dry'),
    ('a1_edit', 'a heavy wooden door creaking open quickly, interior, close, dry'),
    ('a2_fix', 'a heavy wooden door creaking open quickly, interior, close, dry, no music'),
]
PROBES.append(
    _probe(
        'pd_small_edit',
        'Prompt: one word changed, one thing changed',
        ['pd_small_edit', 'pd_fix_lands', 'pd_fix_breaks'],
        [
            {
                'check': 'audio_similarity_min',
                'to': 'a0_base',
                'min': 0.55,
                'on': 'log-mel cosine similarity, a0 vs a1 at the same seed',
            },
            {'check': 'duration_s', 'min': 0.1, 'max': 4.4},
            {'check': 'clap_label_min', 'label': 'a creaking door', 'min': CLAP_MIN, 'margin': CLAP_NULL_MARGIN},
            {
                'check': 'operator',
                'blind': True,
                'question': 'You will hear two recordings, A then B. Is B the same door, only faster? yes/no',
            },
        ],
        cond=dict(COND_ONE, repeats=3, seeds=SETTINGS['seeds']),
        inputs={'prompt': 'CHAIN', 'task': 'render each link of `chain` verbatim at every seed'},
        chain=[dict(link=_l, prompt=_p) for _l, _p in STEER_CHAIN],
        state_note=(
            'one chain, three columns, all read at the SAME seed so nothing but the prompt '
            'moved:\n'
            '  pd_small_edit  a0 -> a1 is ONE word. yes when the operator hears the same door '
            'faster AND the log-mel similarity stays above 0.55 (a smaller number means the '
            'whole render was re-rolled by a one-word edit)\n'
            '  pd_fix_lands   a1 -> a2 adds "no music". yes when a2 scores the music label below '
            f'{CLAP_ABSENT_MAX} in every repeat where a1 did not — the named fix landed\n'
            '  pd_fix_breaks  INVERTED: yes when a2 still passes everything a1 passed (the fix '
            'broke nothing); no when fixing the music cost the door\n'
            'The operator decides pd_small_edit; the other two are mechanical.'
        ),
    )
)

PROBES.append(
    _probe(
        'pd_seed_vs_prompt',
        'Prompt: prompt beats seed',
        ['pd_seed_vs_prompt'],
        [
            {'check': 'clap_label_min', 'label': 'CELL_LABEL', 'min': CLAP_MIN, 'margin': CLAP_NULL_MARGIN},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this the sound named with this trial, and only that? yes/no',
            },
        ],
        cond=dict(COND_SOUND),
        inputs={'prompt': 'GRID', 'task': 'render every cell of the grid: each prompt at each seed'},
        grid={
            'prompts': [
                ('a church bell ringing slowly, exterior, distant', 'a church bell'),
                ('a dog barking twice, exterior, close', 'a dog barking'),
                ('heavy rain on a tiled roof, interior', 'rain on a roof'),
            ],
            'seeds': SETTINGS['seeds'],
        },
        state_note=(
            '3 prompts x 3 seeds = 9 renders. yes when the PROMPT decides every cell: all three '
            'prompts land their own label at all three seeds. If a seed overrides a prompt in '
            'any column of the grid the seed is steering the output and the answer is no; one '
            'cell wrong out of nine is partial. The operator decides each cell, CLAP is the '
            'screen, and the grid is the point — a single prompt at a single seed cannot tell '
            'these apart.'
        ),
    ),
)
PROBES += [
    _probe(
        'pd_reusable',
        'Prompt: the prompt works on the next subject',
        ['pd_reusable'],
        [
            {'check': 'clap_label_min', 'label': 'SUBJECT_LABEL', 'min': CLAP_MIN, 'margin': CLAP_NULL_MARGIN},
            {'check': 'duration_s', 'min': 3.4, 'max': 4.4},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this the subject named with this trial, in a small dry interior, and only that? yes/no',
            },
        ],
        cond=dict(COND_SOUND),
        inputs={
            'prompt': '{subject}, interior, close, dry, one metre away, no music, no voices',
            'task': 'render the ONE template above with each subject in turn',
        },
        subjects=[
            ('a heavy wooden door creaking open slowly', 'a creaking door'),
            ('a hammer driving a nail into a plank', 'hammering wood'),
            ('coins counted onto a wooden table', 'coins'),
            ('a quill writing on paper', 'writing'),
        ],
        state_note=(
            'ONE template, four subjects. yes when all four pass with the template '
            'untouched; 2-3 -> partial; fewer -> no, and the sheet says the prompt has to '
            'be rewritten per subject. The operator decides; CLAP is the screen.'
        ),
    ),
    _probe(
        'pd_direction_words',
        'Prompt: direction words change the take',
        ['pd_direction_words'],
        [
            {
                'check': 'prosody_delta_min',
                'between': ['calm', 'urgent'],
                'wpm_delta': 15,
                'pitch_delta_semitones': 1.0,
                'applies_to': 'speech',
            },
            {'check': 'rms_delta_db', 'between': ['calm', 'urgent'], 'min_db': 2.0},
            {
                'check': 'operator',
                'blind': True,
                'question': 'You will hear two recordings, A then B. Is B more urgent than A? yes/no',
            },
        ],
        cond=dict(COND_SOUND),
        inputs={
            'prompt': 'The seam is open and the water is coming in.',
            'task': 'Read this line aloud once in each direction.',
            'variants': {
                'calm': 'Read it calmly and slowly, as a report.',
                'urgent': 'Read it urgently and fast, as a warning.',
            },
        },
        state_note=(
            'mechanical for a speech row: words per minute and median pitch must both '
            'move in the right direction by the stated margin, measured from the Whisper '
            'word timings and a YIN pitch track. For a non-speech row only the level '
            'difference is mechanical and the operator decides. The operator question is '
            'a blind A/B, presented in a shuffled order per trial.'
        ),
    ),
]

# ── Universal: the three that must be MEASURED, not read off the code ──────────────────
PROBES += [
    _probe(
        'u_failsafe',
        'Fails without breaking the caller',
        ['failsafe'],
        [
            {
                'check': 'operator',
                'blind': False,
                'question': 'Did the call return a value or raise a caught exception, leaving the '
                'process alive and the GPU free? yes/no',
            },
            {
                'check': 'file_absent',
                'path': 'output/capabilities/failsafe/partial.wav',
                'note': 'a half-written file left behind is a fail',
            },
        ],
        cond=dict(COND_ONE, repeats=3),
        inputs={
            'command': 'call the row on a DELIBERATELY broken input three ways: (1) prompt = '
            'the empty string; (2) audio = capability_tests/fixtures/audio/judge/truncated.wav '
            '(a WAV with a header that claims 40 s and 0.2 s of data); '
            '(3) seconds = 0'
        },
        state_note=(
            'three broken calls, all three must come back. yes = every call returned or '
            'raised something the caller can catch, the process is still up and nvidia-smi '
            'shows the VRAM released within 30 s. no = any hang past 120 s, any crash of '
            'the host process, any leaked allocation. This is the only universal column '
            'the operator answers SIGHTED — there is nothing to be blind about.'
        ),
    ),
    _probe(
        'u_degrades',
        'Degrades when the GPU is busy',
        ['degrades'],
        [
            {'check': 'clap_label_min', 'label': BASE_LABEL, 'min': CLAP_MIN, 'margin': CLAP_NULL_MARGIN},
            {'check': 'onset_count', 'n': 3, 'tolerance': 0},
            {
                'check': 'audio_similarity_min',
                'to': 'idle',
                'min': 0.90,
                'on': 'log-mel cosine similarity, busy vs idle at the same seed',
            },
            {'check': 'rtf_max', 'times': 4.0, 'on': 'the busy run, against the idle run'},
        ],
        cond=dict(COND_ONE, repeats=3),
        inputs={
            'prompt': BASE_PROMPT,
            'command': 'run the same render twice: once on an idle GPU, once while a fixed '
            'load holds 14 GB of VRAM and 90 % of the SMs '
            '(scripts/gpu_load.py --vram 14 --util 90)',
        },
        state_note=(
            'yes = the busy run produces the SAME audio (log-mel similarity >= 0.90) and '
            'takes no more than 4x the idle wall time. partial = it still produces the '
            'right sound but slower than 4x. no = OOM, a different result, or a hang. '
            'Fully mechanical; the load is fixed so two rows are comparable.'
        ),
    ),
    _probe(
        'u_offline',
        'Runs on this box',
        ['offline'],
        [
            {'check': 'clap_label_min', 'label': BASE_LABEL, 'min': CLAP_MIN, 'margin': CLAP_NULL_MARGIN},
            {
                'check': 'operator',
                'blind': False,
                'question': 'Did the call succeed with the network down, and did the packet capture '
                'show no outbound connection? yes/no',
            },
        ],
        cond=dict(COND_ONE, repeats=1),
        inputs={
            'prompt': BASE_PROMPT,
            'command': 'run the row once with outbound traffic blocked at the firewall '
            '(the loopback and 127.0.0.1:8188 stay open, because a local ComfyUI '
            'is still this box) and a tcpdump running on the default route',
        },
        state_note=(
            'a MEASUREMENT, not a claim: a row that reaches a vendor fails here even if '
            'its weights are on disk. edge-tts and any hosted judge are `no` by '
            'construction; a local service that quietly checks a licence server is the '
            'thing this probe exists to catch. One repeat is enough — the answer does '
            'not vary.'
        ),
    ),
]
