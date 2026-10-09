# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""The transition vocabulary and the xfade filter graph.

Moved verbatim out of the old single-file kids_video_service.py (lines 3690-3770).
"""

from __future__ import annotations

import random

from zyg_workflows.kids_video_service.constants import (
    FPS,
    OUT_H,
    OUT_W,
)


# ── Transitions and assembly ─────────────────────────────────────────────────
#
# There is no hard cut in this vocabulary at all.  A children's picture video
# reads as one continuous thing, and a smash cut is the opposite of that.
# `fadeblack` is absent for the same reason: a video that blinks to black
# thirty times looks broken to a three-year-old.

_SECTION_WIPES = ['smoothleft', 'smoothright', 'circleopen', 'radial', 'wipeleft', 'horzopen']


def transitions_for(slots, *, seed=0):
    """One smooth transition per join, sized to the pace.

    Long slot to long slot dissolves slowly; a burst run barely blinks, because a
    half-second dissolve inside a half-second picture is not a transition, it is
    a smear.  A section change gets a playful wipe so the form is visible.
    """
    rng = random.Random((int(seed) * 31337 + 5) & 0xFFFFFFFF)
    out = []
    for i in range(len(slots) - 1):
        a, b = slots[i], slots[i + 1]
        if a['burst'] or b['burst']:
            kind, dur = 'dissolve', 0.14
        elif a['section'] != b['section']:
            kind = _SECTION_WIPES[rng.randrange(len(_SECTION_WIPES))]
            dur = 0.45
        elif a['pace'] == 'double' or b['pace'] == 'double':
            kind, dur = ('dissolve' if i % 2 else 'fade'), 0.28
        else:
            kind, dur = ('fade' if i % 3 else 'dissolve'), 0.45
        # Never longer than 45 % of the shorter neighbour: past that the picture
        # spends more time half-there than there.
        dur = max(0.10, min(dur, 0.45 * min(a['dur'], b['dur'])))
        out.append({'i': i, 'transition': kind, 'duration': round(dur, 3)})
    return out


def _xfade_graph(slots, trans, n_inputs):
    """The filter graph, and the input length each clip must be encoded to.

    TWO THINGS ARE BEING GOT RIGHT HERE, and both are invisible until they are
    wrong.

    1. xfade OVERLAPS its two inputs, so a chain of N clips whose lengths sum to
       the song's duration finishes SHORTER than the song by the sum of every
       transition — twenty-odd seconds on a fifty-second video.  Each clip is
       therefore encoded longer than its slot by exactly the overlap it gives
       away.

    2. The transition is CENTRED on the beat, not started on it.  A dissolve is
       perceived to cut at its midpoint, so beginning a 0.45 s dissolve on the
       beat puts the new picture in a quarter-beat late — the cut measures
       perfect and reads loose.  Centring costs nothing: clip j's length becomes
       ``dur_j + (trans_in + trans_out)/2``, every term stays positive, every
       clip stays longer than both of its transitions, and the halves still sum
       so the finished video lands exactly on the song's last sample.
    """
    n = n_inputs
    lens = []
    for j in range(n):
        t_in = trans[j - 1]['duration'] if j > 0 else 0.0
        t_out = trans[j]['duration'] if j < len(trans) else 0.0
        lens.append(slots[j]['dur'] + (t_in + t_out) / 2.0)
    scale = ''.join(
        f'[{i}:v]scale={OUT_W}:{OUT_H}:flags=lanczos,fps={FPS},format=yuv420p,setsar=1[vs{i}];' for i in range(n)
    )
    if n == 1:
        return scale + '[vs0]copy[vout]', lens
    parts, cur, off = [], '[vs0]', 0.0
    for j in range(n - 1):
        t = trans[j]
        off = off + lens[j] - t['duration']
        lbl = '[vout]' if j == n - 2 else f'[x{j:03d}]'
        parts.append(
            f'{cur}[vs{j + 1}]xfade=transition={t["transition"]}:'
            f'duration={t["duration"]:.3f}:offset={max(0.0, off):.3f}{lbl}'
        )
        cur = lbl
    return scale + ';'.join(parts), lens
