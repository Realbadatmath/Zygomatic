# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""score.py — Scoring: the melodic / rhythmic gate (``score_plan``).

Moved verbatim out of ``kids_music_theory.py`` (original lines 2522-2522, 2529-2791).
"""

from __future__ import annotations


import statistics

from zyg_workflows.kids_music_theory.vocabulary import AGE_BANDS, PARENT_OF

from zyg_workflows.kids_music_theory.pitch import _chord_pcs, _note_name

from zyg_workflows.kids_music_theory.brief_prep import _narrow_band_for_singer


# ── Scoring: the melodic / rhythmic gate ─────────────────────────────────────


def score_plan(plan):
    """Measure the composed melody against the properties a children's song
    needs.  Every metric is a number a human can check by ear or on paper; the
    verdict is the weighted mean, and any hard failure vetoes it outright.
    """
    mel = plan['melody']
    if len(mel) < 4:
        return {'ok': False, 'total': 0.0, 'metrics': {}, 'fails': ['melody has fewer than 4 notes']}

    # Read the band the way compose() built it: a plan composed inside the
    # singer's narrowed window must be JUDGED against that window, or the gate
    # goes on approving the D5 the composer is no longer allowed to write.
    band, _tess = _narrow_band_for_singer(AGE_BANDS[plan['brief']['age_band']], plan['brief'])
    parent = PARENT_OF[plan['brief']['mode']]
    tonic_pc = plan['brief']['tonic_pc']
    bar_beats = plan['bar_beats']
    pitches = [n['p'] for n in mel]
    ivs = [pitches[i + 1] - pitches[i] for i in range(len(pitches) - 1)]

    M, fails, warns = {}, [], []

    # 1 — Range.  Hard: it decides whether the room can sing along at all.
    rng_semis = max(pitches) - min(pitches)
    M['range_semitones'] = rng_semis
    M['range_low'] = _note_name(min(pitches))
    M['range_high'] = _note_name(max(pitches))
    max_span = band.get('max_span', band['hi'] - band['lo'])
    M['max_span_allowed'] = max_span
    if min(pitches) < band['lo'] or max(pitches) > band['hi']:
        fails.append(
            f'range {M["range_low"]}–{M["range_high"]} leaves the '
            f'{band["label"]} band ({_note_name(band["lo"])}–{_note_name(band["hi"])})'
        )
    # The WINDOW says which notes exist; the SPAN says how far one tune may
    # stretch inside it. A melody can sit entirely inside a legal window and
    # still be unsingable because it covers an octave and a fourth of it.
    if rng_semis > max_span + 2:
        fails.append(f'melody spans {rng_semis} semitones; the {band["label"]} cap is {max_span}')
    s_range = 1.0 if rng_semis <= max_span else max(0.0, 1.0 - (rng_semis - max_span) * 0.25)
    if rng_semis < 5:
        s_range = 0.55  # under a fourth: not a tune, a chant
        warns.append('melodic range under a perfect fourth — very static')

    # WHERE the tune sits, not just how wide it is. A melody can be entirely
    # inside D4-B4 and still spend its life at the top of it, which for an adult
    # female is the passaggio. A warning rather than a fail — a high median is a
    # worse take, not an illegal one — but the score is docked so the seed search
    # in compose_best prefers the lower placement instead of merely tolerating it.
    M['median_midi'] = statistics.median(pitches)
    if (plan.get('tessitura') or {}).get('source') == 'singer':
        if M['median_midi'] > 67:
            warns.append(
                f'sung median above G4 ({_note_name(int(M["median_midi"]))}) '
                f'— an adult female sits in her passaggio here'
            )
            s_range *= 0.85

    # 2 — Stepwise motion.  The single strongest predictor of singability.
    steps = sum(1 for i in ivs if abs(i) <= 2)
    M['stepwise_ratio'] = round(steps / len(ivs), 3) if ivs else 0.0
    # Scored on a RAMP from the band's floor to a clearly-good value, not on
    # `ratio / floor`: under that formula every candidate that merely cleared the
    # minimum scored a flat 1.0, which is why a 48-seed search used to return a
    # perfect total for 13 of 21 band/mood combinations. A number two thirds of
    # searches max out cannot rank the thing it is there to rank.
    _sw_floor, _sw_good = band['stepwise_min'] * 0.75, band['stepwise_min'] + 0.20
    s_step = max(0.0, min(1.0, (M['stepwise_ratio'] - _sw_floor) / max(1e-6, _sw_good - _sw_floor)))
    if M['stepwise_ratio'] < band['stepwise_min'] * 0.8:
        fails.append(f'only {M["stepwise_ratio"]:.0%} of intervals are steps (band wants ≥{band["stepwise_min"]:.0%})')

    # 3 — Leaps: size cap and tritone ban.
    M['max_leap'] = max((abs(i) for i in ivs), default=0)
    M['tritones'] = sum(1 for i in ivs if abs(i) == 6)
    if M['max_leap'] > band['max_leap']:
        fails.append(f'largest leap {M["max_leap"]} semitones exceeds the band cap ({band["max_leap"]})')
    if M['tritones']:
        fails.append(f'{M["tritones"]} melodic tritone(s)')
    s_leap = 1.0 if (M['max_leap'] <= band['max_leap'] and not M['tritones']) else 0.0

    # 4 — Leap resolution: a big jump answered by a step the other way.
    leaps = [i for i, v in enumerate(ivs) if abs(v) >= 4]
    resolved = 0
    for i in leaps:
        if i + 1 < len(ivs):
            nxt = ivs[i + 1]
            if abs(nxt) <= 2 and (nxt == 0 or (nxt > 0) != (ivs[i] > 0)):
                resolved += 1
        else:
            resolved += 1  # a leap into the final note is a gesture
    M['leaps'] = len(leaps)
    M['leap_resolution'] = round(resolved / len(leaps), 3) if leaps else 1.0
    s_leapres = M['leap_resolution']
    if leaps and M['leap_resolution'] < 0.6:
        warns.append(f'only {M["leap_resolution"]:.0%} of leaps step back')

    # 5 — Chord tone on strong beats.
    chord_by_bar = {c['bar']: c for c in plan['chords']}
    strong_notes = [n for n in mel if n['strong']]
    good = 0
    for n in strong_notes:
        c = chord_by_bar.get(n['bar'])
        if not c:
            continue
        if n['p'] % 12 in set(_chord_pcs(tonic_pc, parent, c['root_deg'])):
            good += 1
    M['strong_beats'] = len(strong_notes)
    M['chord_tone_on_strong'] = round(good / len(strong_notes), 3) if strong_notes else 0.0
    # Same ramp: 0.85 is the point this stops being a problem, not the point it
    # becomes excellent. Full marks need every strong beat to land on the chord.
    s_chord = max(0.0, min(1.0, (M['chord_tone_on_strong'] - 0.70) / 0.30))
    if M['chord_tone_on_strong'] < 0.65:
        fails.append(f'only {M["chord_tone_on_strong"]:.0%} of strong beats are chord tones')

    # 6 — Rhythmic simplicity: how many different note lengths must be learned.
    durs = sorted({round(n['d'], 3) for n in mel})
    M['distinct_durations'] = len(durs)
    M['durations'] = durs
    s_rhythm = (
        1.0
        if len(durs) <= band['max_distinct_durations']
        else max(0.0, 1.0 - 0.25 * (len(durs) - band['max_distinct_durations']))
    )
    if len(durs) == 1:
        s_rhythm = 0.6
        warns.append('one note length for the whole tune — rhythmically flat')

    # 7 — Downbeats.  Every bar of the sung body must have an onset on beat 1;
    #     a child finds the beat by the word that lands on it.
    body_bars = {n['bar'] for n in mel}
    with_downbeat = 0
    for b in body_bars:
        if any(abs(n['t'] - b * bar_beats) < 1e-6 for n in mel if n['bar'] == b):
            with_downbeat += 1
    M['bars_with_downbeat'] = round(with_downbeat / len(body_bars), 3) if body_bars else 0.0
    s_down = M['bars_with_downbeat']
    if M['bars_with_downbeat'] < 0.9:
        warns.append(f'{1 - M["bars_with_downbeat"]:.0%} of bars have no onset on beat 1')

    # 8 — Repetition.  Too little and nobody learns it; too much and it is a loop.
    sigs = {}
    for n in mel:
        sigs.setdefault(n['bar'], []).append((round(n['t'] - n['bar'] * bar_beats, 3), round(n['d'], 3), n['p']))
    # Two signatures per bar, because "the same bar again" has two meanings a
    # child's ear does not distinguish: the identical bar, and the SAME SHAPE
    # somewhere else (a sequence — the motif engine transposes reused motifs to
    # join them legally, so an exact-pitch test alone reported almost no
    # repetition on songs that are audibly built from one idea).
    seen_exact, seen_shape, repeats = set(), set(), 0
    for b in sorted(sigs):
        rows = sigs[b]
        exact = tuple(rows)
        shape = tuple((t, d) for t, d, _ in rows) + tuple(rows[i + 1][2] - rows[i][2] for i in range(len(rows) - 1))
        if exact in seen_exact or shape in seen_shape:
            repeats += 1
        seen_exact.add(exact)
        seen_shape.add(shape)
    M['bars'] = len(sigs)
    M['repeated_bars'] = repeats
    M['repetition_ratio'] = round(repeats / len(sigs), 3) if sigs else 0.0
    r = M['repetition_ratio']
    if r < 0.15:
        s_rep = r / 0.15 * 0.7
        warns.append('almost no repeated bars — hard for a child to learn')
    elif r > 0.72:
        s_rep = max(0.0, 1.0 - (r - 0.72) / 0.28)
        warns.append('very high repetition — close to a loop')
    else:
        s_rep = 1.0

    # 9 — Cadence: the last note is the tonic, on a strong beat, and held.
    last = mel[-1]
    on_tonic = (last['p'] % 12) == tonic_pc
    long_enough = last['d'] >= max(1.0, bar_beats / 2.0)
    M['final_note'] = _note_name(last['p'])
    M['final_is_tonic'] = on_tonic
    M['final_is_strong'] = bool(last['strong'])
    M['final_duration_beats'] = last['d']
    s_cad = (0.5 * on_tonic) + (0.25 * bool(last['strong'])) + (0.25 * long_enough)
    if not on_tonic:
        fails.append(f'ends on {M["final_note"]}, not the tonic')

    # 10 — Density: notes per second of the SUNG BODY.
    #      Dividing by plan['seconds'] included the instrumental intro and outro
    #      — up to 4 bars of a 16-bar song — and understated the real singing
    #      rate by ~20%. The child sings the body, not the container.
    _body_beats = max(1e-6, plan['total_beats'] - (plan['intro_bars'] + plan['outro_bars']) * bar_beats)
    _body_s = _body_beats * 60.0 / max(1e-6, float(plan['bpm']))
    dens = len(mel) / max(1e-6, _body_s)
    M['sung_body_s'] = round(_body_s, 2)
    M['notes_per_second'] = round(dens, 2)
    s_dens = 1.0 if dens <= band['max_density'] else max(0.0, 1.0 - (dens - band['max_density']) / band['max_density'])
    if dens > band['max_density'] * 1.15:
        fails.append(f'{dens:.2f} notes/s is faster than the band can sing (≤{band["max_density"]})')

    # 11 — Contour: one clear high point, not a saw.
    peak = max(pitches)
    M['peak_count'] = sum(1 for p in pitches if p == peak)
    turns = sum(1 for i in range(1, len(ivs)) if ivs[i] and ivs[i - 1] and (ivs[i] > 0) != (ivs[i - 1] > 0))
    M['direction_changes_per_note'] = round(turns / len(ivs), 3) if ivs else 0.0
    s_cont = 1.0
    if M['direction_changes_per_note'] > 0.72:
        s_cont = max(0.3, 1.0 - (M['direction_changes_per_note'] - 0.72) * 2.5)
        warns.append('the line changes direction on most notes — zig-zag contour')

    # 12 — No note hammered more than four times running.
    run, worst = 1, 1
    for i in ivs:
        run = run + 1 if i == 0 else 1
        worst = max(worst, run)
    M['longest_repeated_pitch_run'] = worst
    s_rep_pitch = 1.0 if worst <= 4 else max(0.0, 1.0 - (worst - 4) * 0.25)
    if worst > 5:
        fails.append(f'the same pitch repeats {worst} times in a row')

    # NINE weighted metrics, not twelve.
    #
    # `range` and `downbeats` are not measurements of this melody — they are
    # CONSTRUCTION ASSERTIONS about the composer. Over 2,016 candidates each took
    # exactly one value (range == the band's span cap, downbeats == 1.000),
    # because the note chooser clamps to the band window and every cell starts on
    # beat 1 by construction. Averaging a constant into a weighted mean does not
    # measure anything; it just adds a fixed 2.3 of weight that lifts every total
    # and hides the metrics that do vary. Worse, `range` is precisely the check
    # that should catch a broken tessitura clamp, and as a fractional dip inside a
    # mean it could never be seen. They are now invariants: a violation is a loud
    # bug in the composer, reported separately and vetoing `ok` outright.
    invariants = {
        'range_inside_band': bool(min(pitches) >= band['lo'] and max(pitches) <= band['hi']),
        'range_within_span': bool(rng_semis <= max_span + 2),
        'every_bar_has_a_downbeat': bool(M['bars_with_downbeat'] >= 0.999),
    }
    broken = [k for k, v in invariants.items() if not v]
    for k in broken:
        if not any(k.split('_')[0] in f for f in fails):
            fails.append(f'construction invariant broken: {k}')

    weights = [
        ('stepwise', s_step, 1.6),
        ('leap_size', s_leap, 1.3),
        ('leap_resolution', s_leapres, 1.0),
        ('chord_tones', s_chord, 1.3),
        ('rhythm_simplicity', s_rhythm, 1.0),
        ('repetition', s_rep, 1.2),
        ('cadence', s_cad, 1.2),
        ('density', s_dens, 1.0),
        ('contour', s_cont, 0.8),
        ('pitch_runs', s_rep_pitch, 0.6),
    ]
    total = sum(s * w for _, s, w in weights) / sum(w for _, _, w in weights)

    return {
        'ok': not fails and total >= 0.70,
        'total': round(total, 4),
        'metric_count': len(weights),
        'subscores': {k: round(v, 3) for k, v, _ in weights},
        # Kept out of the mean, reported in full so the panel can show them.
        'invariants': invariants,
        'invariants_ok': not broken,
        'construction': {'range': round(s_range, 3), 'downbeats': round(s_down, 3)},
        'metrics': M,
        'fails': fails,
        'warnings': warns,
    }
