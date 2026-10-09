# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""composer_build.py — the stages of ``kids_music_theory.composer.compose``.

``compose`` was one 306-line function doing six things in sequence: read the
brief, lay the intro bars, walk the sections emitting lines of melody, lay the
outro bars, voice-lead the chords, and assemble the plan dictionary. Each seam
is a helper here, and the enclosing locals the loop used to carry are two
context objects: :class:`ComposeSetup` (what the brief and the seed decided,
never mutated) and :class:`ComposeState` (what the composition has accumulated
so far). The RNG draw order, the log lines, the side effects and their order
are unchanged — ``compose`` is still deterministic for a given (brief, seed).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from zyg_workflows.kids_music_theory.brief_prep import (
    _lines_per_section,
    _narrow_band_for_singer,
    _normalise_brief,
    _plan_sections,
    _progressions_for,
    _syllable_targets,
)
from zyg_workflows.kids_music_theory.forms import METERS, QUALITY, ROMAN
from zyg_workflows.kids_music_theory.pitch import (
    _Composer,
    _chord_degrees,
    _chord_pcs,
    _contour_target,
    _is_strong,
)
from zyg_workflows.kids_music_theory.rhythm import _cells_for, _pick_line_rhythm
from zyg_workflows.kids_music_theory.vocabulary import AGE_BANDS, MODES, MOODS, PARENT_OF, PITCH_NAMES

__all__ = [
    'ComposeSetup',
    'ComposeState',
    'assemble_plan',
    'emit_bars',
    'emit_line',
    'line_rhythm',
    'melody_index',
    'prepare_compose',
    'voice_chord',
    'voice_chords',
]


@dataclass
class ComposeSetup:
    """Everything the brief and the seed decided, before a single note exists.

    Built once by :func:`prepare_compose` and read — never written — by every
    other helper, which is exactly what the enclosing scope of the old
    ``compose`` provided.
    """

    brief: dict
    seed: int
    rng: random.Random
    meter: str
    mode: str
    parent: str
    band: Any
    tessitura: Any
    bar_beats: Any
    cells: Any
    lines_per: int
    order: list
    intro_bars: int
    outro_bars: int
    syl: list
    comp: _Composer
    prog_for: dict


@dataclass
class ComposeState:
    """The notes, chords, sections and counters accumulated so far.

    ``t``/``bar`` are the write head (beat position and bar number);
    ``prev_idx``/``prev_iv``/``repeats`` are the melodic memory the next note is
    chosen against; ``motif_cache`` is keyed on the section letter so every A
    really repeats.
    """

    melody: list = field(default_factory=list)
    chords: list = field(default_factory=list)
    sections: list = field(default_factory=list)
    motif_cache: dict = field(default_factory=dict)
    fit_errors: list = field(default_factory=list)
    motif_reuses: int = 0
    motif_rejects: int = 0
    t: float = 0.0
    bar: int = 0
    prev_idx: Any = None
    prev_iv: Any = None
    repeats: int = 0


def prepare_compose(brief, seed=None) -> ComposeSetup:
    """Normalise the brief and seed the composition.

    In: a raw brief dict (or anything ``_normalise_brief`` accepts) and an
    optional integer seed. Out: a :class:`ComposeSetup` with the key, meter,
    age band, tessitura, rhythm cells, section order and one progression per
    distinct section letter. The RNG is drawn from in this order — band
    narrowing, the ``_Composer``, then one ``rng.choice`` per section letter —
    so the seed means what it always meant.
    """
    brief = _normalise_brief(brief)
    seed = int(seed if seed is not None else 0)
    rng = random.Random(seed)

    meter = brief['meter']
    mode = brief['mode']
    parent = PARENT_OF[mode]
    band = AGE_BANDS[brief['age_band']]
    band, tessitura = _narrow_band_for_singer(band, brief)
    bar_beats = METERS[meter]['beats']
    cells = _cells_for(meter, band)
    lines_per = _lines_per_section(band)

    order, intro_bars, outro_bars = _plan_sections(brief)
    syl = _syllable_targets(brief, len(order))

    comp = _Composer(rng, brief['tonic_pc'], mode, band, meter)

    # One progression per distinct section letter, so every A really is the
    # same harmony (repetition is the point) while B goes somewhere else.
    prog_for = {}
    for name in dict.fromkeys(order):
        pool = _progressions_for(mode, name)
        prog_for[name] = list(rng.choice(pool))

    return ComposeSetup(
        brief=brief,
        seed=seed,
        rng=rng,
        meter=meter,
        mode=mode,
        parent=parent,
        band=band,
        tessitura=tessitura,
        bar_beats=bar_beats,
        cells=cells,
        lines_per=lines_per,
        order=order,
        intro_bars=intro_bars,
        outro_bars=outro_bars,
        syl=syl,
        comp=comp,
        prog_for=prog_for,
    )


def emit_bars(setup: ComposeSetup, st: ComposeState, *, root_deg, section, count) -> None:
    """Append `count` accompaniment-only bars on one chord.

    In: the chord degree to hold, the section marker (-1 intro, -2 outro) and a
    bar count. Out: nothing — ``st.chords`` grows and the write head
    (``st.t``, ``st.bar``) advances by `count` bars.
    """
    for _ in range(count):
        st.chords.append({'bar': st.bar, 'root_deg': root_deg, 'beats': setup.bar_beats, 't': st.t, 'section': section})
        st.t += setup.bar_beats
        st.bar += 1


def line_rhythm(setup: ComposeSetup, *, cached, reuse, line_i, target, is_final, is_last_line):
    """Choose one line's rhythm, reusing the section's cached motif when it fits.

    In: the cached motif for this section letter (or None), whether this pass
    decided to reuse it, the line number, the line's syllable target (0 =
    unconstrained), and the two cadence flags. Out:
    ``(cells, indices_or_None, fit_err, reused, rejected)`` — `indices` is the
    cached pitch line when the motif was taken, None when the rhythm was
    composed fresh; `rejected` is True when a cached motif was refused because
    its note count could not carry `target` syllables.
    """
    cand = (
        cached['lines'][line_i]
        if reuse and cached is not None and line_i < len(cached['lines']) and not is_final
        else None
    )
    rejected = False
    # A motif may only be reused on a line whose SYLLABLE COUNT it can
    # actually carry. The cached line has a fixed number of note onsets;
    # pasting it under a lyric line of a different length is how one
    # section's rhythm ended up on another section's words, with the
    # extra syllables having nowhere to land. target == 0 means the line
    # is unconstrained (no lyric), so any motif fits.
    if cand is not None and target and sum(len(c) for c in cand['cells']) != target:
        cand = None
        rejected = True

    if cand is not None:
        return cand['cells'], list(cand['indices']), cand['fit_err'], True, rejected

    cells, fit_err = _pick_line_rhythm(setup.rng, setup.cells, 2, target, cadence=is_last_line)
    return cells, None, fit_err, False, rejected


def melody_index(
    setup: ComposeSetup,
    st: ComposeState,
    *,
    chord_root,
    strong,
    role,
    sec_pos,
    last_note,
    is_final,
    is_last_line,
):
    """Choose the scale index of one freshly composed note.

    In: the bar's chord degree, whether the beat is strong, the section's
    contour role, the position inside the section (0..1) and the three
    "where am I" flags. Out: a scale index into ``comp.midi_of``. The final
    note of the song is forced home to a tonic; a non-final phrase ending is
    forced onto a chord tone of its bar.
    """
    comp = setup.comp
    force = None
    if last_note and is_final:
        force = set(comp.tonic_indices)
    elif last_note and is_last_line:
        # Non-final phrase endings land on a chord tone of
        # the bar — an open ending, not a full stop.
        pcs = set(_chord_pcs(comp.tonic_pc, setup.parent, chord_root))
        force = {i for i in comp.midi_of if comp.pc_of[i] in pcs}
    idx = comp.choose(
        st.prev_idx,
        st.prev_iv,
        chord_root,
        strong,
        _contour_target(role, sec_pos),
        st.repeats,
        force_degrees=force,
    )
    if last_note and is_final and idx not in comp.tonic_indices:
        # `choose` falls back to a neighbouring step when the
        # forced set has no candidate inside the interval cap.
        # For the very last note that trade is the wrong way
        # round: a song that does not come home is not
        # finished, and one slightly wide final leap is a
        # gesture every child's song already makes.
        idx = (
            min(comp.tonic_indices, key=lambda i: abs(comp.midi_of[i] - comp.midi_of[st.prev_idx]))
            if st.prev_idx is not None
            else comp.tonic_indices[0]
        )
    return idx


def emit_line(
    setup: ComposeSetup,
    st: ComposeState,
    *,
    prog,
    sec_start_bar,
    s_i,
    line_i,
    syl_i,
    role,
    line_cells,
    line_idx,
    motif_off,
    is_final,
    is_last_line,
    sec_notes,
):
    """Emit one line (two bars) of chords and notes.

    In: the section's progression and start bar, the section/line indices, the
    rhythm cells, the motif pitch line (or None to compose fresh) with its
    transposition offset, and the list collecting this section's notes. Out:
    the scale indices actually used, so the caller can cache them as the
    section's motif; ``st.chords``, ``st.melody``, `sec_notes` and the write
    head are advanced.
    """
    comp = setup.comp
    note_i = 0
    n_line = sum(len(c) for c in line_cells)
    new_idx = []
    for b_i, cell in enumerate(line_cells):
        chord_root = prog[(st.bar - sec_start_bar) % len(prog)]
        # A progression ending on V is a half cadence — right in the
        # middle of a song, wrong at the end of one. The last bar of the
        # last section comes home, whatever the loop would have played:
        # otherwise the melody lands on the tonic over a dominant chord
        # and the song stops rather than finishes.
        if is_final and b_i == len(line_cells) - 1:
            chord_root = 0
        st.chords.append({'bar': st.bar, 'root_deg': chord_root, 'beats': setup.bar_beats, 't': st.t, 'section': s_i})
        tb = 0.0
        for d in cell:
            strong = _is_strong(tb, setup.meter)
            pos = note_i / max(1, n_line - 1) if n_line > 1 else 0.0
            # Position inside the SECTION, so the arch spans the phrase
            # rather than restarting every two bars.
            sec_pos = (line_i + pos) / setup.lines_per
            if line_idx is not None and note_i < len(line_idx):
                idx = line_idx[note_i] + motif_off
            else:
                idx = melody_index(
                    setup,
                    st,
                    chord_root=chord_root,
                    strong=strong,
                    role=role,
                    sec_pos=sec_pos,
                    last_note=note_i == n_line - 1,
                    is_final=is_final,
                    is_last_line=is_last_line,
                )
            m = comp.midi_of.get(idx)
            if m is None:
                idx = max(comp.idx_min, min(comp.idx_max, idx))
                m = comp.midi_of[idx]
            iv = None if st.prev_idx is None else m - comp.midi_of[st.prev_idx]
            st.repeats = st.repeats + 1 if iv == 0 else 0
            st.prev_iv, st.prev_idx = iv, idx
            new_idx.append(idx)

            n = {
                't': round(st.t + tb, 6),
                'd': d,
                'p': m,
                'idx': idx,
                'bar': st.bar,
                'strong': strong,
                'section': s_i,
                'line': syl_i,
            }
            st.melody.append(n)
            sec_notes.append(n)
            tb += d
            note_i += 1
        st.t += setup.bar_beats
        st.bar += 1
    return new_idx


def voice_chord(pcs, prev_voicing):
    """Pick the inversion of `pcs` that moves least from `prev_voicing`.

    In: the chord's pitch classes in degree order and the previous chord's MIDI
    voicing (None for the first chord). Out: a list of MIDI notes, stacked
    upwards from above B2 and dropped an octave if it would reach the melody's
    B4. Voice leading rather than root position: every chord used to be rebuilt
    from scratch in one fixed octave, so I-V-vi-IV lurched a fifth up and a
    third down instead of moving by a step or two.
    """
    best, best_cost = None, None
    for inv in range(len(pcs)):
        rot = pcs[inv:] + pcs[:inv]
        voicing, last = [], 47  # first tone sits above B2
        for pc in rot:
            m = last + ((pc - last) % 12)
            if m == last:
                m += 12
            voicing.append(m)
            last = m
        if max(voicing) > 71:  # stay under the melody's B4
            voicing = [m - 12 for m in voicing]
        if prev_voicing is None:
            cost = abs(voicing[0] - 52)  # first chord: near E3
        else:
            cost = sum(abs(a - b) for a, b in zip(voicing, prev_voicing)) if len(voicing) == len(prev_voicing) else 99
        if best_cost is None or cost < best_cost:
            best, best_cost = voicing, cost
    return best


def voice_chords(setup: ComposeSetup, chords) -> None:
    """Label and voice every chord of the song, in time order.

    In: the chord events emitted by the intro, the lines and the outro. Out:
    nothing — each chord gains ``quality``, ``roman``, ``symbol``, ``midi``
    (voiced in the octave below the melody so the tune stays on top) and
    ``bass``.
    """
    parent = setup.parent
    tonic_pc = setup.brief['tonic_pc']
    steps = MODES[parent]['steps']
    prev_voicing = None
    for c in chords:
        degs = _chord_degrees(c['root_deg'], parent)
        root_pc = (tonic_pc + steps[c['root_deg'] % 7]) % 12
        c['quality'] = QUALITY[parent][c['root_deg'] % 7]
        c['roman'] = ROMAN[parent][c['root_deg'] % 7]
        c['symbol'] = PITCH_NAMES[root_pc] + (
            'm' if c['quality'] == 'min' else ('dim' if c['quality'] == 'dim' else '')
        )
        pcs = [(tonic_pc + steps[d]) % 12 for d in degs]
        best = voice_chord(pcs, prev_voicing)
        c['midi'] = best
        prev_voicing = best
        c['bass'] = 36 + root_pc


def assemble_plan(setup: ComposeSetup, st: ComposeState) -> dict:
    """Assemble the plan dictionary from the setup and the finished state.

    In: the setup and a state whose melody, chords and sections are complete.
    Out: the plan dict every consumer downstream reads — key, meter, form,
    bars, sections, chords, melody, range, tessitura, instrumentation and the
    lyric-fit telemetry — without the ``score`` key, which the caller adds.
    """
    brief = setup.brief
    mode = setup.mode
    total_beats = st.t
    seconds = total_beats * 60.0 / brief['bpm']
    return {
        'version': 1,
        'seed': setup.seed,
        'brief': brief,
        'key': {
            'tonic': brief['tonic'],
            'tonic_pc': brief['tonic_pc'],
            'mode': mode,
            'label': f'{brief["tonic"]} {MODES[mode]["label"].lower()}',
            # ACE-Step's keyscale vocabulary is major/minor only.
            'ace_keyscale': f'{brief["tonic"]} ' + ('minor' if 'minor' in mode else 'major'),
        },
        'meter': setup.meter,
        'bar_beats': setup.bar_beats,
        'ts': METERS[setup.meter]['ts'],
        'bpm': brief['bpm'],
        'form': brief['form'],
        'order': setup.order,
        'intro_bars': setup.intro_bars,
        'outro_bars': setup.outro_bars,
        'bars': st.bar,
        'total_beats': total_beats,
        'seconds': round(seconds, 2),
        'sections': st.sections,
        'chords': st.chords,
        'melody': st.melody,
        'range': {
            'lo': min((n['p'] for n in st.melody), default=0),
            'hi': max((n['p'] for n in st.melody), default=0),
        },
        # `range` is what the tune DID; `tessitura` is what it was allowed to do
        # and why. `source` says which constraint bound it: 'singer' when the
        # adult's sung window narrowed the age band, 'age_band' when nothing did.
        'tessitura': setup.tessitura,
        # Two instrumentations, deliberately: `instruments` are General MIDI
        # programs for the SoundFont path and stay keyed on the mood, while
        # `voices` names the SAMPLED library's voices the style asked for (None
        # without a style, which is exactly the old behaviour).
        'instruments': {k: MOODS[brief['mood']][k] for k in ('lead', 'pad', 'bass')},
        'style': brief.get('style'),
        'family': brief.get('family'),
        'voices': brief.get('voices'),
        # The cinematic family's fourth part (double / counter / ostinato /
        # arpeggio), None everywhere else — the children's styles have no such
        # layer and an always-present key is one more thing to ignore.
        'extra': brief.get('extra'),
        # Keyed on whether a style RESOLVED, not on whether its key is in the
        # children's table: 'chase' is a style with a percussion answer (no) and
        # `brief.get('style') in STYLES` said it was not one.
        'percussion': (brief['style_perc'] if 'style_perc' in brief else MOODS[brief['mood']]['perc']),
        # How well the rhythm search hit each line's syllable budget, and how
        # often a cached motif had to be refused because it could not carry the
        # target line. Surfaced rather than discarded: a song whose lines all
        # miss by two syllables is a song whose words do not sit on its tune.
        'lyric_fit': {
            'line_errors': st.fit_errors,
            'total_error': sum(st.fit_errors),
            'worst_line_error': max(st.fit_errors) if st.fit_errors else 0,
            'lines': len(st.fit_errors),
            'motif_reuses': st.motif_reuses,
            'motif_rejected_wrong_length': st.motif_rejects,
        },
    }
