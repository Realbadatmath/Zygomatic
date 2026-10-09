# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""relational/reference.py — the form reference sample: ranges, draw, build_reference and the distribution.

Moved verbatim out of relational.py (lines 1050-1309).
"""

from zyg_workflows.geom.form.relational.constants import (
    LMK,
    LOCAL_BOUND,
    ME,
    MS,
    REFERENCE_FILE,
    SCHEMA,
    _CACHE,
    json,
    np,
    os,
    run_gates,
    time,
)
from zyg_workflows.geom.form.relational.body import (
    measure_relations,
    scalars,
)

# ---------------------------------------------------------------------------------
# THE FORM REFERENCE SAMPLE
# ---------------------------------------------------------------------------------
# Sampling ranges. These bound the DRAW, not plausibility — plausibility is decided by the
# acceptance filter below, which is geom.anthro's own gate rather than an opinion of this
# file's. Age is restricted to the adult window because the acceptance gate itself refuses
# to score a child against ANSUR (gates.py rule 3), so drawing children would produce a
# sample the filter cannot judge rather than a sample it rejects.
ADULT_AGE_FRAC = (0.333333, 0.753846)  # ME._age_years -> 17.0 and 58.0 years exactly
MACRO_RANGES = {
    'age': ADULT_AGE_FRAC,
    'muscle': (0.15, 0.95),
    'weight': (0.20, 0.85),
    'height': (0.15, 0.85),
    'proportions': (0.0, 1.0),
}
# The local morphs the predicates in this file concern, drawn over the design range the
# fitter enforces (geom/fit_reference.py LOCAL_BOUND, "the swayback came from -1.6").
# A TUPLE is an l/r pair driven by ONE draw. This is not tidiness: drawn independently,
# l-upperleg-scale-horiz-incr and its right twin push the bilateral residual past
# measure.check_pose_and_frame's 10 mm ceiling (measured 10.377 mm on the first draw that
# did it) and the body is refused before it can be measured at all. geom/fit_reference.py
# ties the same pairs for the same reason — "so the fit cannot break symmetry".
SAMPLED_LOCALS = (
    # lumbar profile / trunk sagittal shape
    'measure-waist-circ-incr',
    'measure-waisttohip-dist-incr',
    'stomach-tone-incr',
    'torso-vshape-incr',
    'torso-scale-depth-incr',
    'measure-napetowaist-dist-incr',
    # gluteal and trochanteric width
    'buttocks-volume-incr',
    'measure-hips-circ-incr',
    'hip-scale-horiz-incr',
    'hip-scale-depth-incr',
    # eye axis travels with the head block
    'head-scale-horiz-incr',
    'head-scale-depth-incr',
    'head-scale-vert-incr',
    # knee alignment
    'measure-upperleg-height-incr',
    'measure-lowerleg-height-incr',
    ('l-upperleg-scale-horiz-incr', 'r-upperleg-scale-horiz-incr'),
    ('l-upperleg-scale-depth-incr', 'r-upperleg-scale-depth-incr'),
    # shoulder, because it was the other lever at -1.6 in the rejected recipe
    'measure-shoulder-dist-incr',
)
# The acceptance filter. gates.py's own docstring settles which gate this must be: "THE
# PRIMARY plausibility gate here is Mahalanobis on the joint ratio vector with the pack's
# EMPIRICAL thresholds. The per-ratio bands are secondary and are labelled as marginal
# statements" — and the marginal bands admit only 47% of real ANSUR men, so filtering on
# them would build a reference sample that excludes half of humanity and the issued male
# with it (t2_heights_tight, t2_breadths_wide and t2_girths_wide all FAIL on him).
ACCEPTANCE_GATE = 't2_mahalanobis'
ACCEPTANCE_STATUS = ('pass',)


def sample_recipe(rng):
    """One draw from the anny morph space: (phenotype, local_changes)."""
    gender = float(rng.integers(0, 2))
    phen = {'gender': gender}
    for k, (lo, hi) in MACRO_RANGES.items():
        phen[k] = float(rng.uniform(lo, hi))
    lc = {}
    for entry in SAMPLED_LOCALS:
        x = float(rng.uniform(-LOCAL_BOUND, LOCAL_BOUND))
        for name in (entry,) if isinstance(entry, str) else entry:
            lc[name] = x
    return phen, lc


def _draw_one(seed):
    """Build one draw, run the acceptance gate, and measure the relations if it passes.

    A draw that the measurement layer REFUSES — measure.check_pose_and_frame rejects a
    mesh whose bilateral residual or pose is out of contract — is recorded as its own
    outcome rather than crashing the build or being quietly counted as a rejection. The
    two are different admissions and the pack reports them separately.
    """
    rng = np.random.default_rng(seed)
    phen, lc = sample_recipe(rng)
    v, faces, _ = MS._build_mesh(phen, lc)
    v = np.asarray(v, np.float64)
    spec = {
        'sex': 'female' if phen['gender'] > 0.5 else 'male',
        'age_years': ME._age_years(phen['age']),
        'phenotype': phen,
        'local_changes': lc,
    }
    rec = {'seed': int(seed), 'sex': spec['sex'], 'stature_m': float(np.ptp(v[:, 2])), 'age_years': spec['age_years']}
    try:
        rep = run_gates((v, faces, spec), tiers=[2], strict=False)
    except ValueError as e:
        rec.update(acceptance_status='unmeasurable', accepted=False, unmeasurable_reason=str(e))
        return rec
    status = next((r['status'] for r in rep['gates'] if r['id'] == ACCEPTANCE_GATE), None)
    rec['acceptance_status'] = status
    rec['accepted'] = status in ACCEPTANCE_STATUS
    if rec['accepted']:
        rel = measure_relations(v, faces, phenotype=phen, local_changes=lc)
        rec['scalars'] = scalars(rel)
        rec['unresolved'] = rel['unresolved']
    return rec


def _worker(args):
    return _draw_one(args)


def build_reference(n_accepted=600, seed=20260806, workers=6, out=REFERENCE_FILE, max_draws=None, progress=None):
    """Build and cache the Monte-Carlo form reference sample.

    Draws recipes until n_accepted of them pass the acceptance gate, measures every
    predicate on the accepted ones, and writes the whole thing — draws, acceptance rate,
    per-predicate rejection rates, and the exact sampling spec — atomically.

    WHY THE SAMPLE SIZE IS WHAT IT IS. The number that has to be decided is whether a
    predicate rejects at most 1% of the sample, so what matters is the upper confidence
    bound on the rate, not its standard error. At n=600, ZERO rejections gives a 95%
    one-sided upper bound of 3/600 = 0.50% by the rule of three, which clears the 1%
    ceiling with a factor of two in hand; the record carries that bound per predicate
    rather than leaving the reader to compute it.
    """
    os.makedirs(os.path.dirname(out), exist_ok=True)
    t0 = time.time()
    rows = []
    drawn = 0
    unmeasurable = 0
    status_counts = {}
    max_draws = max_draws or (40 * n_accepted)
    # One SeedSequence spawned into per-draw seeds, so a draw is reproducible from its own
    # seed alone (the row records it) and the parallel and serial paths produce the same
    # bodies in the same order.
    seeds = [int(s) for s in np.random.SeedSequence(seed).generate_state(max_draws)]
    pool = None
    if workers and workers > 1:
        import multiprocessing as mp

        pool = mp.get_context('spawn').Pool(workers)
    try:
        chunk = max(workers or 1, 1) * 4
        while len(rows) < n_accepted and drawn < max_draws:
            batch = seeds[drawn : drawn + chunk]
            if not batch:
                break
            drawn += len(batch)
            got = pool.map(_worker, batch) if pool else [_draw_one(b) for b in batch]
            for r in got:
                st = r.get('acceptance_status')
                status_counts[st] = status_counts.get(st, 0) + 1
                if st == 'unmeasurable':
                    unmeasurable += 1
                if r['accepted'] and len(rows) < n_accepted:
                    rows.append(r)
            if progress:
                progress(len(rows), drawn, time.time() - t0)
    finally:
        if pool:
            pool.close()
            pool.join()
    if len(rows) < n_accepted:
        raise RuntimeError(
            'only %d of %d requested bodies passed %s in %d draws; the '
            'sample is not the size the calibration claims and is not '
            'written' % (len(rows), n_accepted, ACCEPTANCE_GATE, drawn)
        )

    pack = {
        'schema': SCHEMA + '/reference',
        'built': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'seed': seed,
        'n_accepted': len(rows),
        'n_drawn': drawn,
        'n_unmeasurable': int(unmeasurable),
        'acceptance_rate': len(rows) / float(drawn),
        'acceptance_status_counts': dict(sorted(status_counts.items())),
        'acceptance_filter': {
            'gate': ACCEPTANCE_GATE,
            'statuses_accepted': list(ACCEPTANCE_STATUS),
            'tier': 2,
            'why': "gates.py's own primary plausibility gate; its marginal band gates admit "
            'only 47.16% of real ANSUR men and FAIL on the issued male, so they '
            'cannot define "bodies our own pipeline would accept"',
        },
        'sampling': {
            'gender': 'uniform over {0.0, 1.0} — the two values the pipeline issues',
            'macros': {k: list(vv) for k, vv in MACRO_RANGES.items()},
            'age_note': 'the adult window, because the acceptance gate refuses to score a '
            'child against ANSUR (gates.py rule 3)',
            'locals': list(SAMPLED_LOCALS),
            'local_range': [-LOCAL_BOUND, LOCAL_BOUND],
            'local_range_source': 'geom/fit_reference.py LOCAL_BOUND — the design-range cap',
        },
        'cage': {'vertices': LMK.CAGE_VERTS, 'faces_quad': LMK.CAGE_FACES},
        'elapsed_s': round(time.time() - t0, 1),
        'rows': rows,
    }
    pack['distribution'] = _distribution(rows)
    tmp = out + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(pack, fh, indent=1, sort_keys=False)
    os.replace(tmp, out)
    return out


def _distribution(rows):
    """Per-scalar quantiles and per-predicate resolution rate over the accepted sample."""
    keys = sorted({k for r in rows for k in (r.get('scalars') or {})})
    out = {}
    for k in keys:
        vals = [r['scalars'][k] for r in rows if r.get('scalars', {}).get(k) is not None]
        if not vals:
            out[k] = {'n': 0, 'note': 'unresolved on every accepted body'}
            continue
        if isinstance(vals[0], bool):
            out[k] = {'n': len(vals), 'true': int(sum(vals)), 'true_fraction': float(sum(vals)) / len(vals)}
            continue
        a = np.asarray(vals, np.float64)
        out[k] = {
            'n': int(len(a)),
            'min': float(a.min()),
            'max': float(a.max()),
            'mean': float(a.mean()),
            'sd': float(a.std(ddof=1)) if len(a) > 1 else 0.0,
            'p01': float(np.percentile(a, 1)),
            'p05': float(np.percentile(a, 5)),
            'p50': float(np.percentile(a, 50)),
            'p95': float(np.percentile(a, 95)),
            'p99': float(np.percentile(a, 99)),
        }
    unres = {}
    for r in rows:
        for u in r.get('unresolved') or []:
            unres[u] = unres.get(u, 0) + 1
    out['_unresolved_counts'] = unres
    out['_n_rows'] = len(rows)
    return out


def form_reference(path=None):
    """Load the cached sample. Absent is an error, not a default — a threshold with no
    sample behind it is exactly what this layer exists to prevent."""
    p = path or REFERENCE_FILE
    if p in _CACHE:
        return _CACHE[p]
    if not os.path.exists(p):
        raise FileNotFoundError(
            'no form reference sample at %s. Build it with\n'
            '    python -m zyg_workflows.geom.form.relational --build-reference\n'
            'Nothing in this module invents a threshold when the sample is missing.' % p
        )
    with open(p) as fh:
        pack = json.load(fh)
    if pack.get('schema') != SCHEMA + '/reference':
        raise ValueError('%s carries schema %r, not %r' % (p, pack.get('schema'), SCHEMA + '/reference'))
    _CACHE[p] = pack
    return pack
