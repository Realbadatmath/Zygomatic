# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pitch.py — Pitch machinery: scale/chord arithmetic, contour archetypes and the
constraint composer.

``_note_name`` (original lines 2525-2526, head of the Scoring section) lives
here because both ``brief_prep`` and ``score`` call it; keeping it in
``score`` would make ``brief_prep`` and ``score`` import each other.

Moved verbatim out of ``kids_music_theory.py`` (original lines 1538-1768, 2525-2526).
"""

from __future__ import annotations


import math

from zyg_workflows.kids_music_theory.vocabulary import MODES, PARENT_OF, PITCH_NAMES

from zyg_workflows.kids_music_theory.forms import METERS


# ── Pitch machinery ──────────────────────────────────────────────────────────


def _scale_midi(tonic_pc, mode, index, base_octave_midi):
    """Scale index -> MIDI note.  index 0 = tonic at base octave; ±len(steps) = octave."""
    steps = MODES[mode]['steps']
    n = len(steps)
    octave, deg = divmod(index, n)
    return base_octave_midi + tonic_pc + 12 * octave + steps[deg]


def _chord_degrees(root_deg, parent):
    """Triad as parent-scale degrees (root, third, fifth)."""
    return [root_deg % 7, (root_deg + 2) % 7, (root_deg + 4) % 7]


def _chord_pcs(tonic_pc, parent, root_deg):
    steps = MODES[parent]['steps']
    return [(tonic_pc + steps[d]) % 12 for d in _chord_degrees(root_deg, parent)]


def _index_pcs(tonic_pc, mode, lo, hi, base):
    """Every usable scale index inside [lo, hi], with its pitch class."""
    out = []
    n = len(MODES[mode]['steps'])
    for idx in range(-2 * n, 3 * n):
        m = _scale_midi(tonic_pc, mode, idx, base)
        if lo <= m <= hi:
            out.append((idx, m, m % 12))
    return out


_ARCH = {
    # Target contour height (0 = bottom of the singable range, 1 = top) per
    # quarter of a phrase.  Children's phrases are arches: rise, peak a little
    # past the middle, settle home.  'answer' phrases invert the last quarter so
    # a repeated A section does not land identically twice.
    'call': (0.30, 0.55, 0.72, 0.45),
    'answer': (0.35, 0.62, 0.50, 0.15),
    'bridge': (0.50, 0.75, 0.85, 0.55),
}


def _contour_target(role, pos):
    pts = _ARCH.get(role, _ARCH['call'])
    x = max(0.0, min(0.999, pos)) * (len(pts) - 1)
    i = int(x)
    f = x - i
    return pts[i] * (1 - f) + pts[min(i + 1, len(pts) - 1)] * f


class _Composer:
    """Holds the per-song constants so the note loop stays readable."""

    def __init__(self, rng, tonic_pc, mode, band, meter, base=48):
        self.rng = rng
        self.tonic_pc = tonic_pc
        self.mode = mode
        self.parent = PARENT_OF[mode]
        self.band = band
        self.meter = meter
        self.base = base
        self.max_span = band.get('max_span', band['hi'] - band['lo'])
        window = _index_pcs(tonic_pc, mode, band['lo'], band['hi'], base)
        if not window:  # a range narrower than the scale
            window = _index_pcs(tonic_pc, mode, band['lo'] - 4, band['hi'] + 4, base)

        # TESSITURA, not just a window.  The band's lo/hi say which notes a child
        # of that age can reach at all; the span cap says how far ONE tune may
        # stretch.  Enforcing the second only as an after-the-fact test threw
        # away two thirds of every candidate (measured: 119/180 toddler seeds
        # failed on span alone), because nothing in the note loop knew about it.
        # So the loop is given a sub-window `max_span` wide, chosen per song, and
        # the constraint becomes structural instead of a rejection.
        n = len(MODES[mode]['steps'])
        win_span = max(m for _, m, _ in window) - min(m for _, m, _ in window)
        want_span = min(self.max_span, win_span)
        placements = []
        for i0, m0, _ in window:
            inside = [(i, m, pc) for i, m, pc in window if m0 <= m <= m0 + self.max_span]
            # A placement anchored near the top of the window fits only a few
            # notes above it. Accepting those produced tessituras a perfect
            # fourth wide sitting at the ceiling — legal, and no tune at all.
            # A placement must therefore be (nearly) the full span it is allowed.
            if len(inside) < 5:
                continue
            if (max(m for _, m, _ in inside) - m0) < want_span - 2:
                continue
            # A tessitura with no tonic in it cannot carry the final cadence,
            # and "ends on the tonic" is not negotiable in this repertoire.
            if not any(i % n == 0 for i, _, _ in inside):
                continue
            # Weight toward the two placements a singer would actually pick:
            # bottom note = the tonic (the tune sits on its home) or the fifth
            # below it (the tonic lands comfortably mid-voice).
            deg0 = i0 % n
            w = 3.0 if deg0 == 0 else (2.0 if deg0 in (n - 3, n - 2) else 1.0)
            placements.extend([inside] * int(w))
        self.usable = rng.choice(placements) if placements else window

        self.lo = min(m for _, m, _ in self.usable)
        self.hi = max(m for _, m, _ in self.usable)
        self.idx_min = min(i for i, _, _ in self.usable)
        self.idx_max = max(i for i, _, _ in self.usable)
        self.midi_of = {i: m for i, m, _ in self.usable}
        self.pc_of = {i: pc for i, _, pc in self.usable}
        self.tonic_indices = [i for i in self.midi_of if i % n == 0]

    def fit_motif(self, indices, prev_idx):
        """Offset a cached motif so it can be reused HERE.

        A motif recalled after a different preceding note can otherwise enter on
        an interval the band never allows — that was the source of every
        'largest leap exceeds the band cap' failure, because a reused motif is
        pasted in without passing through `choose`.  Shifting it by whole scale
        degrees keeps the shape (that is what makes it the same motif) while
        repairing the join, which is what a sequence is.
        """
        if not indices:
            return 0
        best, best_w = 0, -1.0
        for off in (0, 1, -1, 2, -2, 3, -3):
            shifted = [i + off for i in indices]
            if any(i not in self.midi_of for i in shifted):
                continue
            w = 3.0 if off == 0 else 1.0 / (1 + abs(off))
            if prev_idx is not None:
                iv = self.midi_of[shifted[0]] - self.midi_of[prev_idx]
                a = abs(iv)
                if a > self.band['max_leap'] or a == 6:
                    continue
                w *= 3.0 if a <= 2 else (1.2 if a <= 4 else 0.5)
            if w > best_w:
                best, best_w = off, w
        return best if best_w > 0 else None

    # -- one note -------------------------------------------------------------
    def choose(self, prev_idx, prev_interval, chord_root, strong, target_h, repeats, force_degrees=None):
        """Pick the next scale index under the melodic constraints.

        Hard: inside the range; never a tritone; never a leap beyond the band's
        cap; never a fifth identical pitch in a row.
        Soft (scored, then sampled): stepwise preferred, chord tone on strong
        beats, contour follows the arch, a leap wants a step back.
        """
        band = self.band
        chord = set(_chord_pcs(self.tonic_pc, self.parent, chord_root))
        cands = []
        for idx in range(self.idx_min, self.idx_max + 1):
            if idx not in self.midi_of:
                continue
            if force_degrees is not None and idx not in force_degrees:
                continue
            m = self.midi_of[idx]
            if prev_idx is None:
                # Openings start on a chord tone, low-to-middle: a tune that
                # opens on its own ceiling has nowhere to go.
                if self.pc_of[idx] not in chord:
                    continue
                h = (m - self.lo) / max(1, self.hi - self.lo)
                # Gaussian, not a linear taper: under a taper the very top of
                # the range still scored ~half the weight of the bottom, and a
                # tune that opens on its own ceiling has nowhere left to rise.
                cands.append((idx, math.exp(-((h - 0.30) ** 2) / 0.045)))
                continue
            iv = m - self.midi_of[prev_idx]
            a = abs(iv)
            if a > band['max_leap']:
                continue
            if a == 6:  # tritone, in any octave
                continue
            if a == 0 and repeats >= 3:
                continue

            w = 1.0
            # Interval preference — the shape of this curve IS the "mostly
            # stepwise" property the score later measures.
            if a == 0:
                w *= 0.55 if repeats < 2 else 0.18
            elif a <= 2:
                w *= 3.0
            elif a <= 4:
                w *= 1.15
            elif a <= 5:
                w *= 0.55
            elif a <= 7:
                w *= 0.34
            else:
                w *= 0.10
            # Leap resolution: after a leap of a fourth or more, a step in the
            # OPPOSITE direction is the move that makes the leap sound intended.
            if prev_interval is not None and abs(prev_interval) >= 4:
                if a <= 2 and (iv == 0 or (iv > 0) != (prev_interval > 0)):
                    w *= 4.0
                elif a >= 4 and (iv > 0) == (prev_interval > 0):
                    w *= 0.06  # two leaps the same way = an arpeggio run
                else:
                    w *= 0.5
            # Strong beats want a chord tone; weak beats may pass between them.
            if strong:
                w *= 3.2 if self.pc_of[idx] in chord else 0.10
            else:
                w *= 1.25 if self.pc_of[idx] in chord else 1.0
            # Contour
            h = (m - self.lo) / max(1, self.hi - self.lo)
            w *= math.exp(-((h - target_h) ** 2) / 0.10)
            cands.append((idx, w))

        if not cands:
            # Nothing satisfied the hard constraints (usually a corner of the
            # range).  Step back toward the middle rather than fail the song.
            mid = (self.idx_min + self.idx_max) // 2
            return mid if prev_idx is None else max(self.idx_min, min(self.idx_max, prev_idx - 1))
        total = sum(w for _, w in cands)
        if total <= 0:
            return self.rng.choice([i for i, _ in cands])
        r = self.rng.random() * total
        acc = 0.0
        for idx, w in cands:
            acc += w
            if r <= acc:
                return idx
        return cands[-1][0]


def _bar_of(t, bar_beats):
    return int(t // bar_beats + 1e-9)


def _is_strong(t_in_bar, meter):
    return any(abs(t_in_bar - s) < 1e-6 for s in METERS[meter]['strong'])


def _note_name(m):
    return f'{PITCH_NAMES[m % 12]}{m // 12 - 1}'
