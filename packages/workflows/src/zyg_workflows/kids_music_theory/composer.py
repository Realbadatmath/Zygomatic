# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""composer.py — Composition, part 2: ``compose`` (original lines 2214-2519) and the seed
search ``compose_best`` (original lines 2794-2855), which are mutually
recursive through ``score_plan`` and therefore share a module.

Moved verbatim out of ``kids_music_theory.py`` (original lines 2214-2519, 2794-2855).
"""

from __future__ import annotations


from zyg_workflows.kids_music_theory.forms import ROMAN

from zyg_workflows.kids_music_theory.composer_build import (
    ComposeState,
    assemble_plan,
    emit_bars,
    emit_line,
    line_rhythm,
    prepare_compose,
    voice_chords,
)

from zyg_workflows.kids_music_theory.score import score_plan


def compose(brief, *, seed=None):
    """Build one complete song plan.  Deterministic for a given (brief, seed)."""
    setup = prepare_compose(brief, seed)
    # Motifs are cached per section letter so an A section really repeats.
    st = ComposeState()

    # Intro: accompaniment only, on the home chord.
    emit_bars(setup, st, root_deg=setup.prog_for[setup.order[0]][0], section=-1, count=setup.intro_bars)

    for s_i, name in enumerate(setup.order):
        prog = setup.prog_for[name]
        role = 'bridge' if name in ('B', 'C') else ('answer' if s_i % 2 else 'call')
        sec_start_bar = st.bar
        sec_notes = []

        cached = st.motif_cache.get(name)
        reuse = cached is not None and setup.rng.random() < 0.82
        # 82%: a literal repeat almost every time, because that is what makes a
        # children's song learnable — but not ALWAYS, or the last A is a copy of
        # the first down to the cadence and the ending stops feeling like one.

        for line_i in range(setup.lines_per):  # 2-bar lines per section
            is_last_line = line_i == setup.lines_per - 1
            is_final = is_last_line and s_i == len(setup.order) - 1
            _syl_i = s_i * setup.lines_per + line_i
            target = setup.syl[_syl_i] if _syl_i < len(setup.syl) else 0

            line_cells, line_idx, fit_err, reused, rejected = line_rhythm(
                setup,
                cached=cached,
                reuse=reuse,
                line_i=line_i,
                target=target,
                is_final=is_final,
                is_last_line=is_last_line,
            )
            st.motif_reuses += int(reused)
            st.motif_rejects += int(rejected)
            # The fitter's near-misses were computed and then thrown away, so a
            # lyric that never quite fitted its rhythm left no trace anywhere.
            st.fit_errors.append(int(fit_err or 0))

            motif_off = 0
            if line_idx is not None:
                off = setup.comp.fit_motif(line_idx, st.prev_idx)
                if off is None:
                    line_idx = None  # no legal join — compose it fresh
                else:
                    motif_off = off

            new_idx = emit_line(
                setup,
                st,
                prog=prog,
                sec_start_bar=sec_start_bar,
                s_i=s_i,
                line_i=line_i,
                syl_i=_syl_i,
                role=role,
                line_cells=line_cells,
                line_idx=line_idx,
                motif_off=motif_off,
                is_final=is_final,
                is_last_line=is_last_line,
                sec_notes=sec_notes,
            )

            if not reuse or line_idx is None:
                lines = st.motif_cache.setdefault(name, {'lines': []})['lines']
                entry = {'cells': line_cells, 'indices': new_idx, 'fit_err': fit_err}
                if line_i < len(lines):
                    lines[line_i] = entry
                else:
                    lines.append(entry)

        st.sections.append(
            {
                'name': name,
                'role': role,
                'index': s_i,
                'bar_start': sec_start_bar,
                'bar_end': st.bar - 1,
                'progression': [ROMAN[setup.parent][d] for d in prog],
                'notes': len(sec_notes),
            }
        )

    # Outro: the home chord rings out.
    emit_bars(setup, st, root_deg=0, section=-2, count=setup.outro_bars)

    voice_chords(setup, st.chords)

    plan = assemble_plan(setup, st)
    plan['score'] = score_plan(plan)
    return plan


def compose_best(brief, *, candidates=48, seed0=0, min_score=0.70, log_fn=None):
    """Compose `candidates` variants and keep the best-scoring one.

    A seed search, not a retry loop: the constraints make every candidate legal,
    so this is choosing among good tunes rather than hunting for a valid one.
    Stops early on a strong result so a fast brief does not pay for 48 rolls.
    """
    best, best_s = None, -1.0
    tried = 0
    for k in range(max(1, int(candidates))):
        p = compose(brief, seed=seed0 + k)
        tried += 1
        s = p['score']['total'] if p['score']['ok'] else p['score']['total'] * 0.5
        if s > best_s:
            best, best_s = p, s
            if log_fn:
                log_fn(
                    f'compose: seed {seed0 + k} → {p["score"]["total"]:.3f}{"" if p["score"]["ok"] else " (soft fail)"}'
                )
        # No early exit. 48 candidates cost 30 ms measured, so stopping at the
        # first strong one buys nothing and costs the search: several candidates
        # routinely tie at the top of this scale, and breaking out meant the
        # panel honestly reported "best of 1" for a 48-candidate request.
    if best is not None:
        sc = best['score']
        # min_score was accepted, echoed into the plan and NEVER COMPARED TO
        # ANYTHING — so a 48-candidate search could not return a failing plan
        # however bad every candidate was. It is now the real bar: the kept plan
        # must clear it, and a search that could not is said so in the plan
        # rather than being presented as a pass.
        met = bool(sc['ok']) and float(sc['total']) >= float(min_score)
        best['search'] = {
            'candidates_tried': tried,
            'kept_seed': best['seed'],
            'min_score': min_score,
            'best_total': sc['total'],
            'met_min_score': met,
        }
        if not met and float(sc['total']) < float(min_score):
            sc.setdefault('fails', []).append(
                f'best of {tried} candidates scored {sc["total"]:.3f}, under the {float(min_score):.2f} minimum'
            )
            sc['ok'] = False
        if log_fn and not met:
            # NAME THE HALF THAT FAILED. `met` is two conditions — the score
            # bar AND the musical gates — and this line used to report only the
            # first, so a plan rejected by a GATE was announced as "NO candidate
            # met min_score 0.70 (best 0.977)": a number that plainly clears the
            # bar it is accused of missing. It read as a contradiction and sent
            # the reader to the score search instead of to the gate.
            if float(sc['total']) < float(min_score):
                log_fn(
                    f'compose: NO candidate met min_score {float(min_score):.2f} (best {sc["total"]:.3f} of {tried})'
                )
            else:
                _why = '; '.join(str(f) for f in (sc.get('fails') or [])[:3])
                log_fn(
                    f'compose: best of {tried} scored {sc["total"]:.3f} '
                    f'(clears the {float(min_score):.2f} minimum) but FAILED '
                    f'a musical gate — ' + (_why or 'see the score fails')
                )
    return best
