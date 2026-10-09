# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""selftest.py — CLI self-test.

Moved verbatim out of ``kids_music_theory.py`` (original lines 2858-2927).
"""

from __future__ import annotations


from zyg_workflows.kids_music_theory.vocabulary import AGE_BANDS, MOODS

from zyg_workflows.kids_music_theory.styles import STYLES

from zyg_workflows.kids_music_theory.cinematic import CINEMATIC_FAMILY, CINEMATIC_STYLES

from zyg_workflows.kids_music_theory.composer import compose_best


# ── CLI self-test ────────────────────────────────────────────────────────────


def _selftest():
    import json as _json

    ok = True
    for age in AGE_BANDS:
        for mood in MOODS:
            b = {'theme': 'self test', 'age_band': age, 'mood': mood, 'seconds': 45}
            p = compose_best(b, candidates=12)
            sc = p['score']
            flag = 'ok ' if sc['ok'] else 'FAIL'
            print(
                f'{flag} {age:<10} {mood:<9} {p["key"]["label"]:<20} '
                f'{p["meter"]} {p["bpm"]:>3}bpm  {len(p["melody"]):>3}n  '
                f'score={sc["total"]:.3f}  range={sc["metrics"]["range_low"]}–'
                f'{sc["metrics"]["range_high"]}  step={sc["metrics"]["stepwise_ratio"]:.2f}'
            )
            if not sc['ok']:
                ok = False
                print('      fails:', '; '.join(sc['fails']))
    # Every style at ITS OWN defaults. A style that cannot produce a passing
    # plan from the defaults the operator will actually pick is a broken style,
    # not a bad roll — so it fails the selftest.
    print()
    for style, _S in STYLES.items():
        p = compose_best({'theme': 'self test', 'style': style}, candidates=12)
        sc = p['score']
        flag = 'ok ' if sc['ok'] else 'FAIL'
        print(
            f'{flag} {style:<10} {p["brief"]["mood"]:<9} {p["key"]["label"]:<20} '
            f'{p["meter"]} {p["bpm"]:>3}bpm  {p["form"]:<4} '
            f'{p["seconds"]:>6.1f}s  score={sc["total"]:.3f}  '
            f'lead={p["voices"]["lead"]}'
        )
        if not sc['ok']:
            ok = False
            print('      fails:', '; '.join(sc['fails']))

    # The cinematic family at ITS defaults, same rule: a cue that cannot pass
    # the gate from the tempo and metre the operator will actually pick is a
    # broken style. `family` is required — 'storytime' is in both tables.
    print()
    for style, _S in CINEMATIC_STYLES.items():
        p = compose_best({'theme': 'self test', 'style': style, 'family': CINEMATIC_FAMILY}, candidates=12)
        sc = p['score']
        flag = 'ok ' if sc['ok'] else 'FAIL'
        print(
            f'{flag} {style:<11} {p["key"]["label"]:<22} '
            f'{p["meter"]} {p["bpm"]:>3}bpm  {p["form"]:<4} '
            f'{p["seconds"]:>6.1f}s  score={sc["total"]:.3f}  '
            f'{sc["metrics"]["notes_per_second"]:.2f}n/s  '
            f'lead={p["voices"]["lead"]}+{p["extra"]["voice"]}'
            f'({p["extra"]["role"]})'
        )
        if not sc['ok']:
            ok = False
            print('      fails:', '; '.join(sc['fails']))

    b = {
        'theme': 'brushing teeth',
        'age_band': 'preschool',
        'mood': 'happy',
        'seconds': 60,
        'lyrics_lines': ['Brush your teeth up and down', 'Round and round the town'],
    }
    p = compose_best(b, candidates=16)
    print('\nlyric-fitted sample:', _json.dumps(p['score']['metrics'], indent=None)[:300])
    return 0 if ok else 1
