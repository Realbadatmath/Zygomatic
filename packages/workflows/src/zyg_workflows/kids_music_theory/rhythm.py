# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""rhythm.py — Rhythm cells and the line-rhythm picker.

Moved verbatim out of ``kids_music_theory.py`` (original lines 1367-1535).
"""

from __future__ import annotations


from zyg_workflows.kids_music_theory.forms import METERS


# ── Rhythm cells ─────────────────────────────────────────────────────────────
# A cell is one bar of rhythm as a tuple of durations in beats.  They are written
# out rather than generated because the set of bar rhythms a child can clap back
# is small, finite, and better chosen than sampled.

_CELLS = {
    '4/4': [
        (4.0,),
        (2.0, 2.0),
        (3.0, 1.0),
        (1.0, 3.0),
        (2.0, 1.0, 1.0),
        (1.0, 1.0, 2.0),
        (1.0, 2.0, 1.0),
        (1.0, 1.0, 1.0, 1.0),
        (0.5, 0.5, 1.0, 2.0),
        (1.0, 0.5, 0.5, 2.0),
        (2.0, 0.5, 0.5, 1.0),
        (0.5, 0.5, 1.0, 1.0, 1.0),
        (1.0, 0.5, 0.5, 1.0, 1.0),
        (1.0, 1.0, 0.5, 0.5, 1.0),
        (1.0, 1.0, 1.0, 0.5, 0.5),
        (0.5, 0.5, 0.5, 0.5, 1.0, 1.0),
        (1.0, 1.0, 0.5, 0.5, 0.5, 0.5),
        (0.5, 0.5, 1.0, 0.5, 0.5, 1.0),
        (0.5, 0.5, 0.5, 0.5, 2.0),
        (1.5, 0.5, 1.0, 1.0),
        (1.0, 1.0, 1.5, 0.5),
        (1.5, 0.5, 2.0),
    ],
    '2/4': [
        (2.0,),
        (1.0, 1.0),
        (0.5, 0.5, 1.0),
        (1.0, 0.5, 0.5),
        (0.5, 0.5, 0.5, 0.5),
        (1.5, 0.5),
    ],
    '3/4': [
        (3.0,),
        (2.0, 1.0),
        (1.0, 2.0),
        (1.0, 1.0, 1.0),
        (0.5, 0.5, 1.0, 1.0),
        (1.0, 0.5, 0.5, 1.0),
        (1.0, 1.0, 0.5, 0.5),
        (0.5, 0.5, 0.5, 0.5, 1.0),
        (1.5, 0.5, 1.0),
        (1.0, 0.5, 0.5, 0.5, 0.5),
    ],
    '6/8': [
        (3.0,),
        (1.5, 1.5),
        (1.5, 1.0, 0.5),
        (1.0, 0.5, 1.5),
        (1.0, 0.5, 1.0, 0.5),
        (0.5, 0.5, 0.5, 1.5),
        (1.5, 0.5, 0.5, 0.5),
        (1.0, 0.5, 0.5, 0.5, 0.5),
        (0.5, 0.5, 0.5, 0.5, 0.5, 0.5),
    ],
}


def _onsets(cell):
    """Onset position of every note in a cell, relative to the bar."""
    out, t = [], 0.0
    for d in cell:
        out.append(t)
        t += d
    return out


def _cell_ok(cell, meter, band):
    """Is this bar rhythm allowed for this age band in this meter?

    Three rules, each of which a child's ear enforces anyway:
      * eighths come in PAIRS that start on a beat (or on a 6/8 strong position),
        so nobody has to feel a lone off-beat subdivision;
      * a note that starts off the grid's strong points may not last longer than
        the subdivision it started on — that is the definition of syncopation,
        and the two younger bands do not get it;
      * dotted values are a preschool-and-up shape.
    """
    if abs(sum(cell) - METERS[meter]['beats']) > 1e-6:
        return False
    compound = meter == '6/8'
    # COMPOUND METRE IS EXEMPT FROM THE DOTTED BAN. In 6/8 the dotted quarter IS
    # the pulse — banning it does not simplify the rhythm, it deletes the metre.
    # Measured 2026-08-29: the ban left the toddler band 3 of 9 hand-written 6/8
    # cells and rejected (1.5, 1.5), the most idiomatic 6/8 bar there is. Both
    # `lullaby` and `gentle` default to 6/8, so the delivered toddler lullaby
    # contained not one dotted value and still scored rhythm_simplicity 1.000 —
    # that metric rewards FEWER distinct durations, so the degenerate vocabulary
    # it produced scored best. The ban is what a simple-metre child's ear needs;
    # it is not what a compound-metre one does.
    if not band['allow_dotted'] and not compound and any(abs(d - 1.5) < 1e-6 or abs(d - 3.0) < 1e-6 for d in cell):
        # A single note filling the whole bar is not a dot the child has to
        # feel — it is just "hold it". Only bar-SUBDIVIDING dots are refused.
        if len(cell) > 1:
            return False
    if not band['allow_eighths'] and any(d < 1.0 - 1e-6 for d in cell):
        return False

    ons = _onsets(cell)
    # The positions a note may START on without it counting as syncopation. In
    # simple metre that is every beat; in 6/8 it is the two dotted-quarter
    # pulses plus the three eighths inside each of them, which is how a compound
    # bar is actually felt.
    beat_pos = (0.0, 1.5) if compound else tuple(float(i) for i in range(int(METERS[meter]['beats'])))
    div_pos = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5) if compound else beat_pos

    def _at(t, positions):
        return any(abs(t - x) < 1e-6 for x in positions)

    for i, (t, d) in enumerate(zip(ons, cell)):
        if d < 0.75:  # an eighth
            # must pair: either it starts on a division and the next note is also
            # an eighth, or it is itself the second half of such a pair.
            #
            # The old test enumerated (0.0, 1.5, 1.0, 2.0, 0.5, 2.5) for 6/8 —
            # EVERY half-beat position in a 3-beat bar — so `on_beat` was always
            # true and the rule tested nothing. It is now the real division set.
            on_beat = _at(t, div_pos)
            prev_eighth = i > 0 and cell[i - 1] < 0.75
            next_eighth = i + 1 < len(cell) and cell[i + 1] < 0.75
            if not band['allow_syncopation']:
                if not ((on_beat and next_eighth) or prev_eighth):
                    return False
        elif not band['allow_syncopation']:
            if not _at(t, beat_pos):
                return False
    return True


def _cells_for(meter, band):
    cells = [c for c in _CELLS[meter] if _cell_ok(c, meter, band)]
    # A band whose filters remove everything would silently compose nothing, so
    # fall back to the plainest bar that meter can hold rather than raise.
    return cells or [tuple([1.0] * int(METERS[meter]['beats']))]


def _pick_line_rhythm(rng, cells, n_bars, target_notes, cadence, tries=140):
    """Choose `n_bars` cells whose note count hits `target_notes` (the syllables
    of one lyric line), ending long when `cadence` is set.

    A bounded random search rather than a solver: the space is tiny, and a search
    that occasionally misses by a note is better than one that always returns the
    same three rhythms — the near-misses are absorbed by the lyric fitter.
    """
    long_end = [c for c in cells if c[-1] >= 1.5] or [c for c in cells if c[-1] >= 1.0] or cells
    best, best_err = None, 1e9
    for _ in range(tries):
        pick = []
        for b in range(n_bars):
            pool = long_end if (cadence and b == n_bars - 1) else cells
            pick.append(rng.choice(pool))
        n = sum(len(c) for c in pick)
        err = abs(n - target_notes) if target_notes else 0
        # Prefer variety inside the line: two identical bars back to back are
        # fine as a motif repeat (the motif engine does that on purpose) but a
        # rhythm search that lands there by accident just sounds thin.
        if n_bars > 1 and pick[0] == pick[1]:
            err += 0.4
        if err < best_err:
            best, best_err = pick, err
            if err == 0:
                break
    return best, int(best_err)
