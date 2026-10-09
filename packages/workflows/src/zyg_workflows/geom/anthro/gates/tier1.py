# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""TIER 1 — blocking, cheap, runs first.

Moved verbatim out of the old single-file gates.py (lines 3365-4056).
"""

from zyg_workflows.geom.anthro import integrity as IG

from zyg_workflows.geom.anthro.gates.policy import (
    BUILD_TARGET_STATURE_TOL_MM,
    DIURNAL_STATURE_RANGE_MM,
    FAIL,
    MISSING,
    MORPH_COEFF_ABS_MAX,
    PASS,
    REPORT,
    UNMEASURABLE,
    WARN,
)
from zyg_workflows.geom.anthro.gates.bands import (
    GIRTH_CHAIN_SOURCE,
    HARD_GIRTH_CHAINS,
    HARD_HEIGHT_CHAIN,
    HEIGHT_CHAIN_SOURCE,
    SOFT_HEIGHT_CHAIN,
)
from zyg_workflows.geom.anthro.gates.gate import _result
from zyg_workflows.geom.anthro.gates.subject import _note, _roll_up, _roll_up_summary, _skip_phrase, _sub


# ---------------------------------------------------------------------------------
# TIER 1 — blocking, cheap, runs first
# ---------------------------------------------------------------------------------
def _integrity_gate(key):
    """Wrap one integrity check as a gate.

    UNMEASURABLE IS NOT FAIL, and collapsing the two would undo the fix it exists for.
    integrity._check_outward now REFUSES rather than answering when the winding is
    inconsistent — signed volume is only a volume on a coherently oriented surface, so on a
    partially flipped mesh the question has no answer. Reporting that refusal as FAIL would
    claim something we did not determine ("the normals point inward") and would put a
    second failure on a body whose real defect is already named by winding_consistent.
    The registry distinguishes these states everywhere else; this wrapper now does too.
    """

    def fn(sub):
        r = sub.integrity[key]
        d = r['detail']
        if r.get('unmeasurable') or r.get('pass') is None:
            return _result(
                UNMEASURABLE,
                'integrity.%s could not be evaluated: %s' % (key, (d or {}).get('reason', 'no reason recorded')),
                observed=d,
                source='geom.anthro.integrity.check_integrity',
                ms=r['ms'],
            )
        return _result(
            PASS if r['pass'] else FAIL,
            'integrity.%s %s' % (key, 'PASS' if r['pass'] else 'FAIL'),
            observed=d,
            source='geom.anthro.integrity.check_integrity',
            ms=r['ms'],
        )

    return fn


def t1_shell_containment(sub):
    """WHERE THE NON-BODY SHELLS ARE. Until 2026-08-05 nothing read this at all.

    integrity.check_integrity runs a full containment engine on every character — shell
    inventory, generalised winding number against the body component, a ray-parity
    cross-check and an escape ("open sky") test — at about 65% of the whole integrity cost,
    and no gate consumed one bit of it. Measured consequence, on the issued male cage:
    teleport the 226-vertex tongue shell two metres in front of the body and every one of
    the 34 gates returns exactly what it returns for the pristine body — 0 blocking, 0
    warnings, PASS WITH WARNINGS. The shell inventory said 'detached_in_open_air' the whole
    time and nobody was listening.

    What is gated here is only integrity's own defect classification:
      DEFECT      detached_in_open_air / straddles_without_crossing /
                  enclosed_but_crossing / indeterminate  -> FAIL
      REPORTED    protrudes_through_body_surface — correct for an eyeball seen through
                  the eyelid aperture and a defect for anything else. The check cannot
                  tell those apart, so it does not pretend to: it reports.
      NOT A PASS  not_tested / crossing_not_tested / a body component too ambiguous to
                  identify -> UNMEASURABLE. Containment that was never established is not
                  containment that was established as fine.
    """
    r = sub.integrity.get('shell_components')
    if r is None:
        return _result(
            MISSING,
            'integrity.check_integrity produced no shell_components payload '
            '(shell_components=False?), so where the non-body shells sit was '
            'never established for this cage',
            source='geom.anthro.integrity.check_integrity',
        )
    d = r['detail']
    rows = []
    for e in d.get('inventory') or []:
        if e.get('role') == 'body':
            rows.append(
                _note(
                    'component_%d_body' % e['component'],
                    REPORT,
                    'body component: %d vertices, chi=%s genus=%s closed=%s'
                    % (e['vertices'], d.get('body_euler_chi'), d.get('body_genus'), d.get('body_closed')),
                    selected_by=d.get('body_component_selected_by'),
                )
            )
            continue
        c = e.get('containment') or {}
        state = c.get('state')
        ident = '%s (component %d, %d v)' % (e.get('name'), e['component'], e['vertices'])
        if state is None:
            st, why = MISSING, 'no containment verdict was recorded for %s' % ident
        elif c.get('defect'):
            st, why = (
                FAIL,
                ('%s is %s — %s' % (ident, state, c.get('state_meaning') or 'declared a defect state by integrity.py')),
            )
        elif state in ('not_tested', 'crossing_not_tested'):
            st, why = (
                UNMEASURABLE,
                ('%s was NOT containment-tested (%s), so nothing is asserted about where it sits' % (ident, state)),
            )
        elif state == 'protrudes_through_body_surface':
            st, why = (
                REPORT,
                (
                    '%s crosses the body surface. Correct for an eyeball seen '
                    'through the eyelid aperture, a defect for anything that '
                    'is not meant to be visible — this check reports the '
                    'geometry and does not guess which' % ident
                ),
            )
        else:
            st, why = PASS, '%s is %s' % (ident, state)
        rows.append(
            _sub(
                'component_%d' % e['component'],
                st,
                why,
                # 'shell' here is a mesh shell name for _sub(), unrelated to a subprocess shell.
                shell=e.get('name'),  # nosec B604
                vertices=e['vertices'],
                state=state,
                z_frac=[e.get('z_frac_min'), e.get('z_frac_max')],
                vertices_inside_body=c.get('vertices_inside_body'),
                open_sky=c.get('open_sky_from_outside_vertices'),
                max_outside_vertex_to_body_vertex_m=c.get('max_outside_vertex_to_body_vertex_m'),
            )
        )
    if d.get('body_component_ambiguous'):
        rows.append(
            _sub(
                'body_identification',
                UNMEASURABLE,
                'the largest component is not dominant enough to be called "the '
                'body", so containment was not attempted: %s' % d.get('containment_skipped_because'),
            )
        )
    if d.get('containment_cap'):
        rows.append(_sub('containment_cap', UNMEASURABLE, d['containment_cap']))
    if not d.get('body_component_ambiguous'):
        probes = str(d.get('ray_parity_agreement') or '')
        got, _, total = probes.partition('/')
        total = (total.split() or [''])[0]
        if not (got.strip().isdigit() and total.strip().isdigit()):
            # Unparseable is not agreement. Saying nothing here would let a changed
            # payload format quietly retire the cross-check.
            rows.append(
                _sub(
                    'ray_parity_cross_check',
                    UNMEASURABLE,
                    'integrity reported the ray-parity agreement as %r, which '
                    'this gate cannot read, so whether the two containment '
                    'methods agree is unknown' % probes,
                )
            )
        elif got.strip() != total.strip():
            rows.append(
                _sub(
                    'ray_parity_cross_check',
                    UNMEASURABLE,
                    'the winding-number and ray-parity containment tests '
                    'DISAGREE (%s), so the containment verdicts above rest on '
                    'two methods that contradict each other and are not '
                    'established' % probes,
                )
            )
    if not rows:
        rows.append(_sub('shells', UNMEASURABLE, 'no shell inventory was produced for this cage'))
    status, rows = _roll_up(rows)
    # Last line of defence: integrity may fail this check for a reason this gate did not
    # itemise (a new defect state, a new cap). A pass here while integrity says pass=False
    # would be this gate inventing a verdict, so it reports the disagreement instead.
    if not r['pass'] and status in (PASS, REPORT):
        rows.append(
            _sub(
                'integrity_disagreement',
                MISSING,
                'integrity.shell_components reports pass=False but this gate '
                'itemised no defect — the reason is in the payload and not in '
                'this gate, so no pass is claimed. failed detail keys: %s'
                % sorted(k for k in d if k in ('nothing_asserted', 'containment_cap', 'containment_skipped_because')),
            )
        )
        status, rows = _roll_up(rows)
    return _result(
        status,
        '%d shell(s) beside the body: %d defective, %d protruding, %d not '
        'tested%s'
        % (
            d.get('shells', 0),
            len(d.get('shells_defective') or []),
            len(d.get('shells_protruding') or []),
            len(d.get('shells_not_tested') or []) + len(d.get('shells_nothing_asserted') or []),
            _skip_phrase(rows),
        ),
        observed=len(d.get('shells_defective') or []),
        band=[0, 0],
        shells_defective=d.get('shells_defective'),
        shells_protruding=d.get('shells_protruding'),
        shells_not_tested=d.get('shells_not_tested'),
        shells_nothing_asserted=d.get('shells_nothing_asserted'),
        source='geom.anthro.integrity shell_components: winding-number '
        'containment against the body component, ray-parity '
        'cross-checked',
        checks=rows,
        roll_up=_roll_up_summary(rows),
        all_shells_enclosed=d.get('all_shells_enclosed'),
        integrity_pass=r['pass'],
        ms=r['ms'],
        method=d.get('method'),
        note=d.get('note'),
    )


def t1_euler_genus(sub):
    """Per-component Euler characteristic and genus, REPORTED and never gated.

    The other half of the "computed and read by nobody" finding. integrity.py deliberately
    does not assert genus 0 — a cage whose mouth cavity connects to the throat is
    legitimately higher genus, and the whole-mesh chi is a sum over however many shells the
    exporter included — so this gate does not either. It publishes the numbers so a genus
    change between two builds of the same character is visible in the artefact instead of
    living only in a payload nothing reads. The one thing it does assert is the thing
    integrity itself asserts: a component that is not closed.
    """
    r = sub.integrity.get('euler_genus')
    if r is None:
        return _result(MISSING, 'integrity produced no euler_genus payload')
    d = r['detail']
    rows = []
    for c in d.get('per_component') or []:
        open_ = not c.get('closed')
        rows.append(
            _sub(
                'component_%d' % c['component'],
                FAIL if open_ else REPORT,
                'chi=%d genus=%s closed=%s (%d v, %d e, %d tri, z %.4f-%.4f)'
                % (
                    c['euler_chi'],
                    c['genus'],
                    c['closed'],
                    c['vertices'],
                    c['edges'],
                    c['faces_tri'],
                    c['z_min'],
                    c['z_max'],
                ),
                **{k: c[k] for k in ('euler_chi', 'genus', 'closed')},
            )
        )
    status, rows = _roll_up(rows)
    return _result(
        status,
        'chi total %s over %d components; genus is REPORTED, never '
        'gated%s' % (d.get('euler_chi_total'), d.get('components'), _skip_phrase(rows)),
        observed=d.get('euler_chi_total'),
        source='geom.anthro.integrity euler_genus (%s)' % d.get('note'),
        checks=rows,
        roll_up=_roll_up_summary(rows),
        ms=r['ms'],
    )


def t1_self_intersection(sub):
    """Only intersections found under BOTH quad diagonals block.

    A non-planar quad has two valid triangulations that can disagree about self-contact,
    so a pair seen under one diagonal only is an artefact of the split, not evidence the
    cage penetrates itself. integrity.py separates the two counts and this gate uses the
    robust one.
    """
    r = sub.integrity['self_intersection']
    d = r['detail']
    robust = int(d['face_pairs_both_diagonals'])
    art = int(d['face_pairs_diagonal_dependent'])
    ok = robust == 0
    return _result(
        PASS if ok else FAIL,
        'robust self-intersecting quad pairs: %d (plus %d diagonal-dependent '
        'artefacts, which do not count)' % (robust, art),
        observed=robust,
        band=[0, 0],
        source='geom.anthro.integrity self-intersection, both quad diagonals',
        diagonal_dependent=art,
        vertices_involved=int(d['vertices_involved']),
        vertex_fraction=float(d['vertex_fraction']),
        narrowphase_pairs_tested=int(d['narrowphase_pairs_tested']),
    )


def _region_hint(lo, hi):
    """Name the stature band an intersection sits in, so a z-fraction is actionable.

    Bands are read off the measured ANSUR landmark ratios in the reference pack (crotch
    .482, waist .585, acromion .820, cervicale .864); the head band is where the eyeball
    and mouth-interior geometry lives on this cage.
    """
    bands = (
        (0.00, 0.06, 'the foot/toes'),
        (0.06, 0.30, 'the lower leg'),
        (0.30, 0.48, 'the thigh'),
        (0.48, 0.62, 'the pelvis/waist'),
        (0.62, 0.82, 'the torso'),
        (0.82, 0.87, 'the shoulders/neck'),
        (0.87, 1.01, 'the head'),
    )
    hit = [name for a, b, name in bands if lo < b and hi >= a]
    return hit[0] if len(hit) == 1 else 'spanning ' + ' and '.join(hit)


def t1_self_intersection_locality(sub):
    """Where the intersections are, so a failure is actionable rather than a red light.

    The public integrity payload returns 8 example pairs, not the full list, so this
    localises and does not enumerate — it can say "at least here", never "only here".
    """
    d = sub.integrity['self_intersection']['detail']
    ex = d.get('examples') or []
    if not ex:
        return _result(REPORT, 'no intersecting pairs to localise', observed=None)
    # integrity.py ships the z-fractions already resolved. Re-deriving them here is what
    # the first version did, and it was wrong: `examples` carries QUAD indices while
    # ME._topology() returns anny's vendor triangulation, so indexing one with the other
    # silently read a different face and mislocated female's toe defect to mid-torso.
    loc = d.get('example_locality') or {}
    pairs = loc.get('pairs') or []
    if not pairs:
        return _result(
            REPORT,
            '%d example pairs, but integrity.py shipped no example_locality to place them' % len(ex),
            observed=None,
            note='integrity.py predates the example_locality payload',
        )
    fr = [f for p in pairs for f in (p.get('z_frac') or [])]
    if not fr:
        return _result(REPORT, 'example_locality carried no z fractions', observed=None)
    lo, hi = min(fr), max(fr)
    return _result(
        REPORT,
        'the %d example pairs sit at %.3f-%.3f of stature (1.0 = vertex, '
        '0.0 = sole); %s' % (len(pairs), lo, hi, _region_hint(lo, hi)),
        observed=[round(lo, 4), round(hi, 4)],
        source='example_locality from integrity.py (quad-index space)',
        note='EXAMPLES ONLY (%d of %d pairs); this localises, it does not '
        'enumerate' % (len(pairs), d['intersecting_face_pairs']),
    )


def t1_build_target_stature(sub):
    """Delivered stature against the stature the RECIPE ASKED FOR.

    This is a BUILD-TARGET check and explicitly NOT an anthropometric-accuracy claim. It
    asks one question — did the height solver converge — and +/-2 mm is a fair question to
    ask of a solver. It would be a meaningless question to ask of a body, because a real
    person's stature moves %.1f-%.1f mm over a single day.
    """ % DIURNAL_STATURE_RANGE_MM
    target = sub.spec.get('build_target_stature_mm')
    tol = float(sub.spec.get('stature_tolerance_mm', BUILD_TARGET_STATURE_TOL_MM))
    got = sub.stature_mm
    if target is None:
        return _result(
            MISSING,
            'no build target recorded for %r, so delivered %.1f mm cannot be '
            'checked against anything. params.json stores only the ACHIEVED '
            'height for derived characters; mesh_skeletons.derive() should '
            'record height_target_m the way build_originals() does.' % (sub.name, got),
            observed=got,
            source='data/assets/mesh_skeletons/registry.json params',
        )
    d = got - float(target)
    ok = abs(d) <= tol
    return _result(
        PASS if ok else FAIL,
        'delivered %.2f mm vs declared build target %.1f mm (%+.2f mm, tolerance +/-%.1f mm)' % (got, target, d, tol),
        observed=got,
        band=[target - tol, target + tol],
        source='declared build target; tolerance is HOUSE and is a BUILD check, not an anthropometric-accuracy claim',
        delta_mm=round(d, 3),
        claim=sub.spec.get('stature_claim', 'build_target'),
    )


def t1_morph_bounds(sub):
    """Every morph coefficient |v| <= %.1f. FAIL, never clamp.

    Scope is the +/-1 local-change target weights. The 0..1 macro sliders are checked
    against their own domain instead: 0 and 1 are legitimate endpoints there (gender=0.0
    is male and gender=1.0 is female, both in daily use), so applying the +/-0.8 rule to
    them would reject the vendor's own parameterisation.
    """ % MORPH_COEFF_ABS_MAX
    locs = sub.spec.get('local_changes') or {}
    macros = sub.spec.get('phenotype') or {}
    anat = sub.spec.get('anatomy_layer') or {}
    over = sorted(
        ((k, float(v)) for k, v in locs.items() if abs(float(v)) > MORPH_COEFF_ABS_MAX), key=lambda kv: -abs(kv[1])
    )
    bad_macro = sorted((k, float(v)) for k, v in macros.items() if not (0.0 <= float(v) <= 1.0))
    worst = max((abs(float(v)) for v in locs.values()), default=0.0)
    rows = [
        _sub(
            'local_changes',
            FAIL if over else PASS,
            'max |coefficient| = %.4f over %d local changes' % (worst, len(locs)),
            violations=over,
            limit=MORPH_COEFF_ABS_MAX,
        ),
        _sub(
            'macro_domain',
            FAIL if bad_macro else PASS,
            '%d macro sliders, all inside 0..1' % len(macros)
            if not bad_macro
            else 'macro sliders outside 0..1: %r' % (bad_macro,),
            violations=bad_macro,
        ),
    ]
    if anat:
        rows.append(
            _note(
                'anatomy_layer',
                REPORT,
                'the post-morph sculpt channel is %r — NOT a morph coefficient and outside '
                'this rule. It is the channel through which a mirror-asymmetric edit would '
                'enter (gate t3_morph_symmetry): the abs_definition sculpt did exactly that '
                'at 2.93-3.76 mm until it was made symmetric by construction on 2026-08-05, '
                'and with that fixed all four issued bodies sit at 0.0014-0.0632 mm, which is '
                "anny's own non-bit-symmetric morph data and not our layer." % anat,
                values=anat,
            )
        )
    bones = sub.spec.get('bone_scales') or {}
    if bones:
        rows.append(
            _note(
                'bone_scales',
                REPORT,
                'the recipe also carries %d per-bone scale(s) %r. These are NOT morph '
                'coefficients — they are a pose-matrix scale applied after the morph stack — '
                'so the +/-%.1f rule does not apply to them and this gate does not bound '
                'them. They DO move the cage (a 1.15 upperleg scale moves vertices by 247 mm '
                'on abel), so they are named here rather than left invisible.'
                % (len(bones), bones, MORPH_COEFF_ABS_MAX),
                values=bones,
            )
        )
    status, rows = _roll_up(rows)
    return _result(
        status,
        next((r['explain'] for r in rows if r['status'] == status), 'no gateable morph row produced a result')
        + _skip_phrase(rows),
        observed=worst,
        band=[-MORPH_COEFF_ABS_MAX, MORPH_COEFF_ABS_MAX],
        source='HOUSE limit on anny local-change target weights',
        checks=rows,
        roll_up=_roll_up_summary(rows),
    )


def _chain_rows(sub, chain, hard):
    rows = []
    for hi, lo, vm, vf, mm_m, mm_f in chain:
        a, b = sub.mm(hi), sub.mm(lo)
        rate = vm if sub.sex == 'male' else vf
        margin = mm_m if sub.sex == 'male' else mm_f
        if a is None or b is None:
            rows.append(
                _sub(
                    '%s>%s' % (hi, lo),
                    UNMEASURABLE,
                    'one of the two heights is not measurable on this cage',
                    violation_rate_in_ansur=rate,
                )
            )
            continue
        d = a - b
        ok = d > 0.0
        if hard:
            st = PASS if ok else FAIL
            why = (
                '%s %.1f > %s %.1f by %.1f mm (this step holds in ALL %s ANSUR '
                'subjects; smallest real margin %.0f mm)'
                % (hi, a, lo, b, d, 'male n=4082' if sub.sex == 'male' else 'female n=1986', margin)
            )
            if not ok:
                why = '%s %.1f is NOT above %s %.1f (%.1f mm) — no ANSUR subject violates this step' % (hi, a, lo, b, d)
        else:
            st = PASS if ok else WARN
            why = (
                '%s %.1f vs %s %.1f (%+.1f mm); %.2f%% of real %s subjects violate '
                'this step, so it is a warning and never a block' % (hi, a, lo, b, d, 100.0 * rate, sub.sex)
            )
        rows.append(
            _sub(
                '%s>%s' % (hi, lo),
                st,
                why,
                delta_mm=round(d, 2),
                violation_rate_in_ansur=rate,
                smallest_real_margin_mm=margin,
            )
        )
    return rows


def t1_landmark_ordering_hard(sub):
    """The height-chain steps that NO ANSUR subject violates. These may block."""
    rows = _chain_rows(sub, HARD_HEIGHT_CHAIN, True)
    zmin = sub.mm('tibiale_height')
    if zmin is not None:
        rows.append(
            _sub('tibiale>ground', PASS if zmin > 0 else FAIL, 'tibiale %.1f mm above the standing surface' % zmin)
        )
    heights = [(k, sub.mm(k)) for k, _, _, _, _, _ in HARD_HEIGHT_CHAIN]
    seq = [x for _, x in heights if x is not None]
    chain = IG.monotonic_chain(seq, names=[k for k, x in heights if x is not None], increasing=False)
    status, rows = _roll_up(rows)
    return _result(
        status,
        '%d hard ordering steps, %d violated%s'
        % (len(rows), sum(1 for r in rows if r['status'] == FAIL), _skip_phrase(rows)),
        observed={k: sub.mm(k) for k in sorted({x for t in HARD_HEIGHT_CHAIN for x in t[:2]})},
        source=HEIGHT_CHAIN_SOURCE,
        checks=rows,
        roll_up=_roll_up_summary(rows),
        monotonic_chain_helper=chain,
    )


def t1_landmark_ordering_soft(sub):
    """The height-chain steps REAL PEOPLE violate. These may only warn.

    Encoding these as blocks is the classic anthropometric gate bug: trochanterion above
    buttock looks self-evident and is false for one adult in five.
    """
    rows = _chain_rows(sub, SOFT_HEIGHT_CHAIN, False)
    # A NOTE, not a skipped check: this step is not an ordering constraint on ANY body
    # (42.50% of ANSUR men violate it), so it is not evidence this gate was ever going to
    # weigh, and excluding it from the roll-up is not the same as excusing a check that
    # should have run on this cage.
    rows.append(
        _note(
            'iliocristale~waist',
            UNMEASURABLE,
            'iliocristale is unresolvable on this cage, and in ANSUR the step '
            'iliocristale > omphalion is violated by 42.50% of men and 20.85% '
            'of women, so it is not an ordering constraint even when both are '
            'measurable',
        )
    )
    status, rows = _roll_up(rows)
    return _result(
        status,
        '%d soft ordering steps, %d flagged%s'
        % (len(rows), sum(1 for r in rows if r['status'] == WARN), _skip_phrase(rows)),
        source=HEIGHT_CHAIN_SOURCE,
        checks=rows,
        roll_up=_roll_up_summary(rows),
    )


def _girth_steps():
    """Every girth step as its own calibration record, with the id the gate reports it
    under. Flattened here so the gate and its calibration read ONE table."""
    out = []
    for chain in HARD_GIRTH_CHAINS:
        for s in chain['steps']:
            out.append(
                dict(
                    s,
                    chain=chain['name'],
                    id='%s:%s>%s'
                    % (
                        chain['name'],
                        s['hi'].replace('_circumference', '').replace('_relaxed', ''),
                        s['lo'].replace('_circumference', ''),
                    ),
                )
            )
    return tuple(out)


GIRTH_STEPS = _girth_steps()


def t1_girth_chain(sub):
    """Monotonic limb girths, PER STEP, plus underbust <= bust where both rings exist.

    Per step and not per chain, because the evidence is per step. The arm chain runs
    upperarm > elbow > wrist on this cage, and ANSUR II has no elbow circumference column
    at all: the end-to-end step upper arm > wrist is the only one of the three with a
    survey rate behind it, so it is the only one allowed to FAIL. The two elbow steps warn
    and carry the rate of the nearest surveyed analogue, clearly labelled as an analogue.
    """
    rows = []
    for step in GIRTH_STEPS:
        a, b = sub.mm(step['hi']), sub.mm(step['lo'])
        rate = step['violation_male'] if sub.sex == 'male' else step['violation_female']
        margin = step['min_margin_mm'][0 if sub.sex == 'male' else 1]
        if a is None or b is None:
            rows.append(
                _sub(
                    step['id'],
                    UNMEASURABLE,
                    'missing: %s' % ', '.join(k for k, x in ((step['hi'], a), (step['lo'], b)) if x is None),
                    blocking_step=bool(step.get('blocking')),
                    violation_rate_in_ansur=rate,
                )
            )
            continue
        d = a - b
        ok = d > 0.0
        st = PASS if ok else (FAIL if step.get('blocking') else WARN)
        if ok:
            why = '%s %.1f > %s %.1f by %.1f mm' % (step['hi'], a, step['lo'], b, d)
        elif step.get('blocking'):
            why = (
                '%s %.1f is NOT above %s %.1f (%.1f mm) — the surveyed step %s is '
                'violated by %.4f%% of the 6,068 real subjects, smallest real margin '
                '%.0f mm' % (step['hi'], a, step['lo'], b, d, step['survey_pair'], 100.0 * rate, margin)
            )
        else:
            why = (
                '%s %.1f is NOT above %s %.1f (%.1f mm). WARNS, never blocks: ANSUR II '
                'has no column for this step, so no rejection rate for it exists. The '
                'nearest surveyed analogue is %s, violated by %.4f%% of real %s '
                'subjects — an analogue, not this step'
                % (step['hi'], a, step['lo'], b, d, step.get('nearest_survey_pair') or 'none', 100.0 * rate, sub.sex)
            )
        rows.append(
            _sub(
                step['id'],
                st,
                why,
                delta_mm=round(d, 2),
                chain=step['chain'],
                blocking_step=bool(step.get('blocking')),
                survey_pair=step.get('survey_pair'),
                nearest_survey_pair=step.get('nearest_survey_pair'),
                evidence=step['evidence'],
                violation_rate_in_ansur=rate,
                smallest_real_margin_mm=margin,
            )
        )
    for chain in HARD_GIRTH_CHAINS:
        vals = [(k, sub.mm(k)) for k in chain['keys']]
        if any(x is None for _, x in vals):
            continue
        # ' | ', never ' > ': the row is a readout of the three girths in chain order, and
        # printing '215.2 > 255.2' would assert an ordering the step rows just refuted.
        rows.append(
            _note(
                '%s:chain' % chain['name'],
                REPORT,
                'chain readout: '
                + ' | '.join('%s %.1f' % (k.replace('_circumference', '').replace('_relaxed', ''), x) for k, x in vals),
                caveat=chain['caveat'],
                monotonic_chain_helper=IG.monotonic_chain(
                    [x for _, x in vals], names=[k for k, _ in vals], increasing=False
                ),
            )
        )
    bust = sub.mm('bust_circumference_makehuman_ring')
    under = sub.mm('underbust_circumference_makehuman_ring')
    if bust is None or under is None:
        rows.append(_sub('bust', UNMEASURABLE, 'one of the two MakeHuman rings is absent'))
    else:
        rows.append(
            _sub(
                'bust',
                PASS if under <= bust else WARN,
                'underbust %.1f <= bust %.1f' % (under, bust)
                if under <= bust
                else 'underbust %.1f EXCEEDS bust %.1f by %.1f mm' % (under, bust, under - bust),
                caveat='HOUSE. ANSUR has no underbust column, so there is no '
                'survey violation rate for this pair and it may only '
                'warn. For reference the nearest surveyed pair, chest '
                '> waist circumference, is violated by 1.84% of men and '
                '5.64% of women.',
            )
        )
    status, rows = _roll_up(rows)
    gating = [r for r in rows if r.get('gating', True)]
    n_block = sum(1 for r in gating if r.get('blocking_step'))
    return _result(
        status,
        '%d girth steps checked (%d fail-capable, %d warn-only), %d violated%s'
        % (
            len(gating),
            n_block,
            len(gating) - n_block,
            sum(1 for r in gating if r['status'] in (FAIL, WARN)),
            _skip_phrase(rows),
        ),
        source=GIRTH_CHAIN_SOURCE,
        checks=rows,
        roll_up=_roll_up_summary(rows),
    )
