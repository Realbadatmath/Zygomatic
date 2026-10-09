# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The command line.

Moved verbatim out of the old single-file kids_music_service.py (lines 4427-4513).
"""

from __future__ import annotations

import json
import os
import time
from zyg_workflows import kids_music_theory as T

from zyg_workflows.kids_music_service.base import (
    CINEMATIC_OUT_ROOT,
    OUT_ROOT,
)
from zyg_workflows.kids_music_service.run import run

# ── CLI ──────────────────────────────────────────────────────────────────────


def _main(argv):
    import argparse

    ap = argparse.ArgumentParser(description="Children's music workflow (CLI)")
    ap.add_argument('theme', nargs='?', default='a song about washing your hands')
    ap.add_argument('--age', default='preschool', choices=list(T.AGE_BANDS))
    ap.add_argument('--mood', default='happy', choices=list(T.MOODS))
    ap.add_argument('--meter', default='', choices=[''] + list(T.METERS))
    ap.add_argument('--form', default='AABA', choices=list(T.FORMS))
    ap.add_argument(
        '--family',
        default='children',
        choices=list(T.STYLE_FAMILIES),
        help="which style table --style is looked up in. 'cinematic' "
        'is an instrumental cue: no lyrics, no pictures, its '
        'own output root',
    )
    ap.add_argument(
        '--style',
        default='',
        choices=[''] + sorted(set(T.STYLES) | set(T.CINEMATIC_STYLES)),
        help='a Melodies style: sets the instruments, the ACE tags, '
        'the lyric rule and the shelf (see '
        'kids_music_theory.STYLES / CINEMATIC_STYLES)',
    )
    ap.add_argument('--seconds', type=float, default=45.0)
    ap.add_argument('--bpm', type=float, default=0)
    ap.add_argument('--tonic', default='')
    ap.add_argument('--instrumental', action='store_true')
    ap.add_argument(
        '--singer',
        default=T.DEFAULT_SINGER,
        choices=list(T.SINGERS),
        help='who sings it (adults only — see kids_music_theory.SINGERS)',
    )
    ap.add_argument('--no-ace', action='store_true')
    ap.add_argument('--candidates', type=int, default=48)
    ap.add_argument('--out', default='')
    a = ap.parse_args(argv)
    cinematic = a.family == 'cinematic'
    root = CINEMATIC_OUT_ROOT if cinematic else OUT_ROOT
    out = a.out or os.path.join(root, time.strftime('cli_%Y%m%d_%H%M%S'))
    m = run(
        {
            'theme': a.theme,
            'age_band': a.age,
            'mood': a.mood,
            'meter': a.meter,
            'form': a.form,
            'seconds': a.seconds,
            'bpm': a.bpm,
            'tonic': a.tonic,
            # Not `sung_forced_off`: the CLI knows the family before it builds
            # the brief, so it asks for the instrumental rather than asking for
            # a sung cue and being corrected.
            'sung': not (a.instrumental or cinematic),
            'singer': a.singer,
            'style': a.style or None,
            'family': a.family,
        },
        out,
        log_fn=lambda s: print(s, flush=True),
        candidates=a.candidates,
        want_ace=not a.no_ace,
    )
    # `picked` is now the MASTERED file; `mastered_from` says what it was made
    # from. The CLI used to print the un-mastered take as the answer.
    print(
        json.dumps(
            {
                'out': out,
                'ok': m['ok'],
                'score': m['score']['total'],
                'picked': m['delivery']['picked'],
                'mastered_from': m['delivery']['mastered_from'],
                'leg': m['delivery']['picked_leg'],
                'reason': m['delivery']['reason'],
                'singer_gate': (m['gates'].get('singer') or {}).get('status'),
                'ok_commercial': m['licence']['ok_commercial'],
            },
            indent=1,
        )
    )
    return 0 if m['ok'] else 1
