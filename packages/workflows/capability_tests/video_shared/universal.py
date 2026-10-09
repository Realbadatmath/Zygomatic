# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The five universal columns that must be RUN, not read."""

from __future__ import annotations

from .settings import (
    COND_CLIP,
    COND_ONE,
    NEGATIVE,
    STATE_3OF3,
)
from .probes import (
    PROBES,
    _probe,
)
from .scenes import _op
from .prompt_bands import (
    VBASE,
    VMOTION,
)

# ── the five universal columns that must be RUN, not read ──────────────────────────────
PROBES += [
    _probe(
        'u_deterministic',
        'reliability: same input, same output',
        ['deterministic'],
        {
            'prompt': VBASE,
            'motion': VMOTION,
            'negative': NEGATIVE,
            'note': 'the base scene rendered TWICE at each of the three seeds, back to back, nothing else changed',
        },
        [
            {
                'check': 'identical_clips',
                'for': 'deterministic',
                'note': 'per-frame md5 lists must match between the two runs at the same seed',
            },
            {
                'check': 'similarity_min',
                'to': 'the first run at this seed',
                'min': 0.98,
                'for': 'deterministic',
                'note': 'the fallback reading for a row with a non-deterministic decoder: not bit-identical but visually '
                'the same clip. The trial says which of the two it achieved; only bit-identical is a full yes.',
            },
        ],
        cond=dict(COND_CLIP, repeats=6, note='3 seeds x 2 runs'),
        state_rule=STATE_3OF3,
        state_note=(
            'yes when all three seeds are bit-identical across the two runs. partial when they are '
            'visually identical (>= 0.98) but not bit-identical — the honest answer for a row with a '
            'non-deterministic VAE or an unpinned attention kernel. no when the same seed gives a '
            'different clip.'
        ),
    ),
    _probe(
        'u_failsafe',
        'reliability: fails without breaking the caller',
        ['failsafe'],
        {
            'fixture': 'fixtures/video/broken/truncated.png',
            'command': "the row's normal call, with the truncated still as the input and everything else as the base trial",
            'note': 'a PNG cut off at 40 % of its bytes. Three repeats so a flaky crash shows.',
        },
        [
            {
                'check': 'log_contains',
                'path': "the row's own run log for this trial",
                'pattern': '(?i)error|fail|invalid|cannot',
                'for': 'failsafe',
                'note': 'the failure must be SAID, not swallowed',
            },
            {
                'check': 'file_absent',
                'path': "the row's output path for this trial",
                'for': 'failsafe',
                'note': 'a half-written clip left on disk is not a clean failure',
            },
            {
                'check': 'pytest_passed',
                'for': 'failsafe',
                'note': "the runner's own smoke test is run AFTER the failure: the process, the comfy queue and the "
                'GUI must all still answer. A row that takes the server down with it is a no whatever it logged.',
            },
        ],
        cond=dict(COND_ONE, repeats=3),
        state_rule=STATE_3OF3,
    ),
    _probe(
        'u_degrades',
        'reliability: degrades when the GPU is busy',
        ['degrades'],
        {
            'command': 'the base trial rendered while the fixed load in `fixture` holds the card',
            'fixture': 'fixtures/video/gpu_load/hold_8gb.json',
            'prompt': VBASE,
            'motion': VMOTION,
            'note': 'hold_8gb.json is a recipe, not a binary: allocate 8 GiB on cuda:0 and busy-loop a matmul at '
            '~40 % utilisation for the duration of the render. The idle baseline is the same render with the '
            'card free, taken in the same session.',
        },
        [
            {
                'check': 'metric_within',
                'metric': 'wall seconds divided by the idle baseline',
                'target': 1.6,
                'tol': 0.8,
                'unit': 'x',
                'for': 'degrades',
                'note': 'slower is expected and fine; the failure is a crash, an OOM, or a clip that comes back wrong',
            },
            {'check': 'frames_exact', 'frames': 81, 'for': 'degrades'},
            {
                'check': 'similarity_min',
                'to': 'the idle baseline at the same seed',
                'min': 0.9,
                'for': 'degrades',
                'note': 'the busy card must not change what comes out',
            },
            _op(
                'This clip was rendered while the GPU was already 8 GiB and 40 % busy. Is it the same clip as the '
                'idle baseline beside it — no new artefacts, nothing missing, nothing truncated? yes/no'
            ),
        ],
        cond=dict(COND_ONE, repeats=3, note='one seed, three repeats, under the fixed load'),
        state_rule=STATE_3OF3,
        state_note=(
            'yes when it comes back correct, however much slower. partial when it completes but the clip '
            'differs beyond 0.9 similarity. no when it OOMs, crashes, or returns short. The measured '
            'slowdown is written into the trial either way — it is what the scheduler needs.'
        ),
    ),
    _probe(
        'u_offline',
        'operability: runs on this box',
        ['offline'],
        {
            'command': 'the base trial with the network interface down for the duration of the call',
            'prompt': VBASE,
            'motion': VMOTION,
            'note': 'the weights are already local; this measures whether the row reaches out anyway',
        },
        [
            {'check': 'file_exists', 'path': "the row's output path for this trial", 'for': 'offline'},
            {'check': 'frames_exact', 'frames': 81, 'for': 'offline'},
            {
                'check': 'log_contains',
                'path': "the row's own run log for this trial",
                'pattern': '(?i)resolve|dns|connection|timeout|huggingface|http',
                'for': 'offline',
                'note': 'read INVERTED: a match means it tried the network. A row that succeeds but fetched something '
                'is a partial, and the trial names what it fetched.',
            },
        ],
        cond=dict(COND_ONE, repeats=1),
        state_rule=STATE_3OF3,
        state_note=(
            'yes when the clip comes back with no network access and no network line in the log. partial '
            'when it succeeds but the log shows a call it did not need. no when it cannot run without the '
            'network — which for an API row is the truth, not a defect, and the trial says so.'
        ),
    ),
    _probe(
        'u_resumable',
        'operability: resumable or interruptible',
        ['resumable'],
        {
            'prompt': VBASE,
            'motion': 'she walks steadily along the quay and does not stop',
            'negative': NEGATIVE,
            'note': 'ONE 162-frame walk produced as TWO 81-frame windows, the second seeded from the last frame of '
            'the first, and the seam read at frame 81.',
        },
        [
            {'check': 'seam_continuity', 'at': 81, 'max_ratio': 2.5, 'for': 'resumable'},
            {
                'check': 'identity_cosine_min',
                'a': 0,
                'b': -1,
                'min': 0.35,
                'detector': 'insightface-buffalo_l',
                'for': 'resumable',
            },
            {
                'check': 'duration_s',
                'min': 9.9,
                'max': 10.4,
                'for': 'resumable',
                'note': '162 frames at 16 fps = 10.1 s; at 25 fps the bounds are 6.4-6.6 s and the trial records which',
            },
            _op(
                'This clip was made in two halves, the second continuing from the last frame of the first. Watch the '
                'join. Is it invisible — no jump in position, colour, light or style, and the same woman either '
                'side? yes/no'
            ),
        ],
        cond=dict(COND_CLIP, note='two windows per seed'),
        state_rule=STATE_3OF3,
        state_note=(
            'yes when the seam is invisible at all three seeds. partial when the seam is visible but the '
            'clip is usable (the honest answer for most Wan rows). no when the second window restarts the '
            'scene, which means the row cannot be extended and cap_seconds is capped at one clip.'
        ),
    ),
]
