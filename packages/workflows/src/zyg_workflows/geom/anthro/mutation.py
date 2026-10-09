# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""MUTATION TESTING FOR THE GATE REGISTRY — break the body on purpose, see who notices.

WHY THIS EXISTS. The single most common defect in this project is not a wrong threshold or
a bad measurement. It is A CHECK THAT CANNOT FAIL. Seven were found by hand, each by
somebody reading carefully enough to notice:

  * `kept_by_residual = 1 - r` in scan_ingest — algebra emitted as if it were a measurement
  * `_need(out['falloff_inside_collar'], ...)` in relief_subdiv — a dict is always truthy,
    so the assertion asserted nothing
  * t5_landmark_relief counting `point_only` as resolved, when point_only sits INSIDE the
    module's own null at a 37.8% chance rate
  * t5_joint_rom passing on the rest pose while its title claimed the whole pose library
    (real answer once fixed: abel 44/44 poses FAIL)
  * `_settings_mismatch` failing OPEN when a setting was absent
  * `_validate_consent` accepting a record whose every field was null
  * `main()` returning 0 on failure, and a Blender subprocess exiting 0 on an exception

Every one of those passed a body it had no business passing. Every one was caught by a
human reading source. That does not scale, and it did not catch them before they shipped.

THE METHOD. Take a body the registry already knows. Break it in a way that is
unambiguously wrong — shrink the stature, snap the mirror symmetry, flatten the relief,
inject NaN, lie in the declaration. Re-run the whole registry. Then compare, gate by gate,
against the same run on the unbroken body.

THE VERDICT THAT MATTERS is not "did the gate fail". It is "did the gate CHANGE". A gate
that reports exactly the same thing about a correct body and a deliberately corrupted one
is not measuring that body. It might still be a fine gate for a different property — that
is why an unreactive gate is reported per mutation rather than condemned outright — but a
gate that no mutation in the panel moves is a gate nobody can say how to break, and that
is itself the finding.

OUTCOMES PER (GATE, MUTATION):

  REACTED    status got worse under the mutation. The gate works. Nothing to do.
  MOVED      the verdict held, but the gate's OWN NUMBERS changed. It measured the
             mutation and stayed inside its band. Normally correct behaviour.
  UNMOVED    the verdict held AND nothing the gate said changed at all — same bands, same
             observed values, same sub-checks. This is the suspect.
  FRAGILE    the gate raised instead of judging. A corrupted body is a body it should fail
             cleanly, not crash on; a crash in the engine reads differently from a verdict
             and can be swallowed by the wrong except.
  EVASIVE    the gate answered `skip` / `not_applicable` / `unmeasurable` on a body it
             judged fine a moment ago. That is the escape hatch the point_only bug used:
             declining to judge is not the same as judging, and a gate that ducks under
             pressure will duck on a real defect too.
  DEFERRED   the gate declined AND named a dependency AND that dependency is itself
             failing in the same run. A refusal that names a verifiable reason is not
             evasion — it is a gate refusing to answer an ill-posed question, which is
             what we want. The reason is CHECKED, never taken on trust: if the named
             dependency is passing, the refusal is unjustified and the outcome stays
             EVASIVE. Added 2026-08-08, after this harness reported t1_outward_normals as
             `evasive via flip_face_winding` — that gate had just been fixed to return
             UNMEASURABLE on a partially flipped mesh, because signed volume is not a
             volume there, and the harness flagged the fix as the defect.
  NOT_RUN    the mutated body was refused UPSTREAM and no gate was asked. Not evidence
             about any gate — see _classify.

THAT IS THE THIRD TIME THIS HARNESS CALLED CORRECT BEHAVIOUR A DEFECT, and the pattern is
worth naming because it will recur: a precondition rejection (34 false majors), an
out-of-domain age declaration (6 false majors), and a dependency-aware refusal (1). Every
one was the system declining to measure something it should decline to measure, and every
one looked like ducking from the outside. The general rule the harness now encodes is that
A REFUSAL IS LEGITIMATE WHEN IT NAMES A REASON THE HARNESS CAN INDEPENDENTLY VERIFY — and
the verification is the load-bearing half, or `depends_on` becomes a magic word any gate
can print to opt out of being tested.

THE MOVED/UNMOVED SPLIT EXISTS BECAUSE ITS ABSENCE PRODUCED A FALSE FINDING. Comparing
top-level status alone, this harness reported that flipping a body's declared sex moved
0 of 62 gates, and I read that as sex conditioning being unwired. It is not. t2_heights_tight
swings its acromial prediction 1380.4 mm -> 1372.7 mm and its band +/-27.3 -> +/-32.3;
t2_girths_wide moves the neck band [0.1796, 0.2385] -> [0.1939, 0.2670] and the percentile
p78.4 -> p16.4, and its own roll-up changes from '1 fail, 1 warn' to '1 fail, 0 warn'.
Every one of those gates responded correctly; none crossed a threshold, because the body
sits inside both sexes' bands. That is a fact about the body, not about the gates.
Status-only comparison cannot distinguish 'ignored it' from 'measured it and stayed in
band', and those are opposite findings.

WHAT THIS DELIBERATELY DOES NOT DO. It never edits a gate, never edits a threshold, and
never writes to the delivered characters. Mutated meshes exist only in memory. The output
is a finding list; acting on it is a separate decision by a person.

AND IT MUST BE POINTED AT THE CONTROLS TOO. A control that never fires becomes decoration
and nobody notices when it stops working — my own sfm_capability BROKEN path was verified
by SIMULATING a baseline diff rather than by inducing a real break, which is the same
weakness one level up. `--include-controls` runs the panel against the control modules for
that reason.
"""

from __future__ import annotations

import json
import os
import time

import numpy as np

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

SCHEMA = 'geom.anthro.mutation/1'

REACTED = 'reacted'
INERT = 'inert'
FRAGILE = 'fragile'
EVASIVE = 'evasive'

# Statuses that mean "I judged it and it is fine".
_OK = ('pass',)
# Statuses that mean "I judged it and it is not fine". Reacting INTO one of these is the
# behaviour a working gate shows under a mutation.
_BAD = ('fail', 'warn')
# Statuses that mean "I declined to judge". Moving INTO one of these under a mutation is
# EVASIVE, not a reaction — the distinction the point_only defect turned on.
_DUCK = ('skip', 'not_applicable', 'unmeasurable', 'not_implementable', 'missing')
_ERR = ('error', 'crashed')

DEFAULT_SUBJECT = 'female'


class MutationError(RuntimeError):
    pass


# ----------------------------------------------------------------------------------
# THE PANEL
# ----------------------------------------------------------------------------------
#
# Each mutation must be UNAMBIGUOUSLY WRONG — a body a competent gate should object to —
# and it must state WHAT it breaks, so a gate that stays inert can be judged against
# whether it ever claimed to measure that thing. Magnitudes are deliberately gross: this
# panel asks "does the gate react AT ALL", not "where is its threshold". A gate that
# cannot notice a 12% stature error will not notice a 1% one either.


def _mut_stature(v, faces, spec, rng):
    """Body 12% shorter. Every stature-normalised and absolute-length claim should move."""
    out = v.copy()
    out[:, 2] *= 0.88
    return out, faces, spec


def _mut_break_mirror(v, faces, spec, rng):
    """Snap left/right symmetry on 3% of vertices, one side only, by ~4 mm.

    The specific defect this imitates is real: geom/relief_subdiv found the geometric
    mirror map MIS-PAIRING 40 vertices on the male at subdivision level 2.
    """
    out = v.copy()
    S = float(out[:, 2].max() - out[:, 2].min())
    left = np.nonzero(out[:, 0] > 0.02 * S)[0]
    if left.size == 0:
        return out, faces, spec
    pick = rng.choice(left, size=max(1, int(0.03 * left.size)), replace=False)
    out[pick, 0] += 0.0024 * S
    return out, faces, spec


def _mut_flatten_relief(v, faces, spec, rng):
    """Smooth the surface toward its own local mean — erases exactly the bony landmarks
    the relief layer exists to produce, while leaving every proportion intact."""
    from zyg_workflows.geom.form import curvature as CV

    out = v.copy()
    A = CV.vertex_adjacency(faces, n_vertices=len(out))
    deg = np.asarray(A.sum(axis=1)).ravel()
    deg[deg == 0] = 1.0
    for _ in range(12):
        out = out + 0.5 * ((A @ out) / deg[:, None] - out)
    return out, faces, spec


def _mut_segment_scale(v, faces, spec, rng):
    """Lengthen the lower body 8% about the hip line. A pure proportion lie: stature is
    re-normalised afterwards so ONLY the ratios move, which is what the proportion gates
    claim to measure and the stature gates do not."""
    out = v.copy()
    S = float(out[:, 2].max() - out[:, 2].min())
    z0 = float(out[:, 2].min())
    hip = z0 + 0.52 * S
    below = out[:, 2] < hip
    out[below, 2] = hip - (hip - out[below, 2]) * 1.08
    z = out[:, 2]
    out[:, 2] = (z - z.min()) / max(z.max() - z.min(), 1e-12) * S + z0
    return out, faces, spec


def _mut_nan(v, faces, spec, rng):
    """One NaN vertex. Integrity gates must refuse; anything that silently propagates it
    is emitting numbers computed from a NaN."""
    out = v.copy()
    out[int(rng.integers(0, len(out))), 1] = np.nan
    return out, faces, spec


def _mut_spike(v, faces, spec, rng):
    """A single vertex thrown 6% of stature off the surface — a gross topology/outlier
    defect that no smooth measure should average away."""
    out = v.copy()
    S = float(out[:, 2].max() - out[:, 2].min())
    out[int(rng.integers(0, len(out))), 0] += 0.06 * S
    return out, faces, spec


def _mut_declare_wrong_sex(v, faces, spec, rng):
    """Body unchanged, DECLARATION lied about. Every gate that compares a body against a
    sex-specific reference should now object; one that does not is not reading the
    declaration it claims to gate on."""
    s = dict(spec)
    s['sex'] = 'male' if str(s.get('sex', '')).lower().startswith('f') else 'female'
    return v, faces, s


def _mut_declare_wrong_age(v, faces, spec, rng):
    """Same body, declared 19 years younger — and still an ADULT, deliberately.

    THE FIRST VERSION DECLARED AGE 7 AND PRODUCED SIX FALSE 'EVASIVE' FINDINGS. ANSUR II
    covers ages 17-58, so a body declared as a seven-year-old is outside the reference
    population altogether and t2_heights_tight, t2_girths_wide, t2_mahalanobis and friends
    are RIGHT to answer not_applicable. Refusing to score a body against a population it
    does not belong to is the correct behaviour, and this harness recorded it as ducking.

    A mutation has to stay inside the domain where the gate is obliged to answer, or it
    tests the domain check instead of the gate. 44 -> 25 keeps the body squarely in ANSUR's
    range, so any evasion now is real evasion.
    """
    s = dict(spec)
    cur = s.get('age_years')
    s['age_years'] = 25.0 if (cur is None or cur > 30) else 50.0
    return v, faces, s


def _mut_degenerate_faces(v, faces, spec, rng):
    """Collapse 40 faces to a single vertex each: zero-area geometry, which is where
    cotangent weights blow up and normals become undefined."""
    f = np.array(faces, copy=True)
    n = min(40, len(f))
    idx = rng.choice(len(f), size=n, replace=False)
    for i in idx:
        f[i, :] = f[i, 0]
    return v, f, spec


def _mut_flip_winding(v, faces, spec, rng):
    """Reverse vertex order on 4% of faces.

    THE GAP THIS FILLS. The first panel had three mutations aimed at topology and all
    three were refused UPSTREAM — a NaN mesh, a 6%-of-stature spike and 200 collapsed
    faces never reached the registry, so t1_watertight, t1_edge_manifold,
    t1_vertex_manifold, t1_winding_consistent and t1_outward_normals were never actually
    asked anything and then reported as 'never reacted'. A mutation that tests them has to
    survive the precondition, which means it must keep the mesh manifold and watertight and
    break only ORIENTATION. Reversing a face does exactly that: every edge is still used
    twice, no vertex moves, and the surface is still closed — but the two faces sharing an
    edge now traverse it in the same direction, which is precisely what winding consistency
    means.
    """
    f = np.array(faces, copy=True)
    n = max(1, int(0.04 * len(f)))
    idx = rng.choice(len(f), size=n, replace=False)
    f[idx] = f[idx][:, ::-1]
    return v, f, spec


def _mut_invert_all_normals(v, faces, spec, rng):
    """Reverse EVERY face. Winding stays perfectly consistent; the surface is inside-out.

    The complement of the mutation above, and the pair is the point: this one must move
    t1_outward_normals and must NOT move t1_winding_consistent, while flip_winding must do
    the opposite. Two gates that both react to both mutations are not measuring two
    different things.
    """
    return v, np.array(faces, copy=True)[:, ::-1], spec


def _mut_small_spike(v, faces, spec, rng):
    """A 1.2%-of-stature displacement on one vertex — under the precondition's guard.

    The 6% spike was refused before measurement, which is correct but means nothing
    downstream was tested. This is small enough to pass the up-front check and large enough
    that a surface-sanity or outlier gate ought to object: ~20 mm on a 1.68 m body, roughly
    five times the cage's own relief null.
    """
    out = v.copy()
    S = float(out[:, 2].max() - out[:, 2].min())
    i = int(rng.integers(0, len(out)))
    out[i, 1] += 0.012 * S
    return out, faces, spec


def _mut_girth(v, faces, spec, rng):
    """Inflate girth 9% over the torso band, leaving every HEIGHT untouched.

    THE GAP THIS FILLS. t1_girth_chain and t3_depths_wide were reported as 'never
    reacted', and the reason was this panel, not those gates: stature_shrink scales z
    uniformly (invisible to a stature-normalised ratio) and segment_proportion_8pct moves
    lengths only. Neither mutation changes a CIRCUMFERENCE, which is the entire quantity a
    girth gate measures. A gate cannot be blamed for ignoring a property nothing in the
    panel altered.

    Radial scaling about the body axis over a height window: girths change, heights and
    landmark ordering do not.
    """
    out = v.copy()
    S = float(out[:, 2].max() - out[:, 2].min())
    z0 = float(out[:, 2].min())
    lo, hi = z0 + 0.40 * S, z0 + 0.75 * S
    band = (out[:, 2] >= lo) & (out[:, 2] <= hi)
    t = np.clip((out[band, 2] - lo) / max(hi - lo, 1e-12), 0, 1)
    w = np.sin(np.pi * t)  # zero at both ends: no seam, no crease
    out[band, 0] *= 1.0 + 0.09 * w
    out[band, 1] *= 1.0 + 0.09 * w
    return out, faces, spec


def _mut_depth(v, faces, spec, rng):
    """Scale DEPTH (y) 10% without touching BREADTH (x) or any height.

    The companion to the girth mutation, and the pair is the point: a chest DEPTH gate and
    a chest BREADTH gate must not both react to both, or they are not measuring two
    different things. This changes the depth/breadth ratio while leaving stature, segment
    lengths and left/right symmetry exactly as they were.
    """
    out = v.copy()
    out[:, 1] *= 1.10
    return out, faces, spec


PANEL = (
    ('girth_inflate_9pct', _mut_girth, 'CIRCUMFERENCES over the torso; heights untouched'),
    ('depth_scale_10pct', _mut_depth, 'DEPTH (y) only; breadth and all heights untouched'),
    ('stature_shrink_12pct', _mut_stature, 'absolute and stature-normalised lengths'),
    ('flip_face_winding', _mut_flip_winding, 'face ORIENTATION only; mesh stays manifold and watertight'),
    ('invert_all_normals', _mut_invert_all_normals, 'normal direction only; winding stays consistent'),
    ('small_spike_1.2pct', _mut_small_spike, 'a single outlier vertex, below the precondition guard'),
    ('break_mirror_symmetry', _mut_break_mirror, 'left/right symmetry and the mirror map'),
    ('flatten_relief', _mut_flatten_relief, 'bony landmark relief, with proportions left intact'),
    ('segment_proportion_8pct', _mut_segment_scale, 'segment RATIOS only, stature re-normalised'),
    ('inject_nan', _mut_nan, 'numeric integrity'),
    ('single_vertex_spike', _mut_spike, 'outliers and surface sanity'),
    ('declare_wrong_sex', _mut_declare_wrong_sex, 'the DECLARATION, body untouched'),
    ('declare_wrong_age', _mut_declare_wrong_age, 'the DECLARATION, body untouched'),
    ('degenerate_faces', _mut_degenerate_faces, 'face topology and zero-area geometry'),
)


# ----------------------------------------------------------------------------------
# HARNESS
# ----------------------------------------------------------------------------------


def _rows(report):
    """gate id -> (normalised status, payload digest).

    THE DIGEST IS NOT DECORATION — its absence produced this harness's second false
    finding. The first version compared TOP-LEVEL STATUS only, and on that basis reported
    that flipping a body's declared sex moved 0 of 62 gates, which I read as sex
    conditioning being unwired. It is not: t2_heights_tight swings its acromial prediction
    from 1380.4 mm to 1372.7 mm and its band from +/-27.3 to +/-32.3, t2_girths_wide moves
    the neck band from [0.1796, 0.2385] to [0.1939, 0.2670] and the percentile from p78.4
    to p16.4, and its own sub-check roll-up changes from '1 fail, 1 warn' to '1 fail, 0
    warn'. Every one of those gates responded correctly. None of them crossed a threshold,
    because the body sits inside both sexes' bands — which is a fact about this body, not
    about the gates.

    Status-only comparison cannot tell 'ignored the mutation' from 'responded but did not
    cross'. Those are opposite findings. So the payload is hashed too, and INERT splits
    into UNMOVED (nothing changed at all — the real suspect) and MOVED_NOT_CROSSED
    (internals responded, verdict held), which is usually a gate working as designed.
    """
    import hashlib
    from zyg_workflows.geom.anthro import report as RP

    out = {}
    for g in report.get('gates') or []:
        gid = g.get('id') or g.get('gate')
        if not gid:
            continue
        raw = g.get('effective_status', g.get('status'))
        try:
            st = RP.normalize_status(raw)
        except Exception:  # noqa: BLE001
            st = str(raw)
        # Hash everything the gate SAID, minus the fields that move on every run for
        # reasons unrelated to the body (timings, ids). A digest that changed with the
        # clock would make every gate look reactive.
        payload = {k: v for k, v in g.items() if k not in ('elapsed_s', 'started', 'finished', 'index', 'order')}
        try:
            blob = json.dumps(payload, sort_keys=True, default=str)
        except Exception:  # noqa: BLE001
            blob = repr(payload)
        out[gid] = (str(st).lower(), hashlib.blake2b(blob.encode(), digest_size=12).hexdigest())
    return out


NOT_RUN = 'not_run'
PRECONDITION = 'precondition_caught'
UNMOVED = 'unmoved'  # nothing in the payload changed — the real suspect
MOVED = 'moved_not_crossed'  # internals responded, verdict held
DEFERRED = 'deferred_to_dependency'  # refused, named a reason, and the reason checks out


def _depends_on(payload):
    """The gate this result says it cannot be evaluated until someone else settles.

    Walks the whole payload rather than reading a fixed path, because `depends_on` is
    emitted deep inside an integrity detail block and nothing guarantees where the next
    one will live. Returns the first name found, or None.
    """
    stack, seen = [payload], set()
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            if id(o) in seen:
                continue
            seen.add(id(o))
            for k, val in o.items():
                if str(k).lower() == 'depends_on' and isinstance(val, str) and val:
                    return val
                stack.append(val)
        elif isinstance(o, (list, tuple)):
            stack.extend(o)
    return None


def _dependency_is_failing(dep, mut_status):
    """Is the named dependency ACTUALLY in a bad state in this same mutated run?

    THE VERIFICATION IS THE WHOLE POINT. A gate that ducks and names a reason is only
    excused if the reason is TRUE — otherwise 'depends_on' becomes a magic word any gate
    could print to opt out of being tested, which is a worse hole than the one this
    closes. The name is resolved leniently (gates are registered as t1_winding_consistent
    while the integrity check calls itself winding_consistent) but the STATUS is checked
    strictly: the dependency must itself be failing, warning or unmeasurable. If it is
    passing, the refusal is unjustified and the gate is still evasive.
    """
    if not dep:
        return None
    d = str(dep).lower()
    for gid, st in mut_status.items():
        g = str(gid).lower()
        if g == d or g.endswith('_' + d) or d in g:
            return (gid, st, st in _BAD or st in _DUCK or st in _ERR)
    return (None, None, False)


def _classify(base, mut, base_dig=None, mut_dig=None, mut_payload=None, mut_status=None):
    """What one gate did between the clean body and the broken one.

    NOT_RUN IS NOT EVASIVE, and conflating them was a real defect in this harness — one it
    committed on its very first run. Three mutations (inject_nan, single_vertex_spike,
    degenerate_faces) raised UPSTREAM of the registry: Subject construction and the
    measurement precondition refused the mesh before a single gate executed. The first
    version recorded every gate as 'missing' for those runs and classified 34 of them as
    EVASIVE, producing a page of confident 'major' findings that described nothing but its
    own control flow. It also depressed the reaction count of exactly the t1 integrity
    gates those mutations were written to exercise, manufacturing 'never_reacted'
    criticals out of gates that were never asked.

    And the upstream refusal is the SYSTEM WORKING. A NaN mesh, a non-manifold cage and a
    surface with a 6%-of-stature spike are bodies the pipeline should refuse to measure at
    all. Being caught by a precondition is a better outcome than being caught by a gate,
    not a worse one. It is reported as PRECONDITION rather than folded into either column.
    """
    if mut == NOT_RUN:
        return NOT_RUN
    if mut in _ERR and base not in _ERR:
        return FRAGILE
    if base in _OK and mut in _BAD:
        return REACTED
    if mut in _DUCK and (base in _OK or base in _BAD):
        # A REFUSAL THAT NAMES A VERIFIABLE REASON IS NOT EVASION, and this harness has
        # now called correct behaviour a defect three separate times for want of that
        # distinction — a precondition rejection, an out-of-domain age declaration, and
        # this one. t1_outward_normals was fixed on 2026-08-08 to return UNMEASURABLE
        # when the winding is inconsistent, because signed volume is not a volume on a
        # partially flipped mesh; the harness promptly reported that fix as `evasive via
        # flip_face_winding`, i.e. it flagged the gate for refusing to answer an
        # ill-posed question, which is exactly what we had just asked it to do.
        #
        # The excuse is granted only where it is CHECKED: the result must name a
        # dependency AND that dependency must itself be failing in the SAME mutated run.
        # Otherwise `depends_on` would be a magic word for opting out of measurement.
        dep = _depends_on(mut_payload)
        if dep and mut_status:
            _gid, _st, ok = _dependency_is_failing(dep, mut_status)
            if ok:
                return DEFERRED
        return EVASIVE
    if base != mut and mut in _BAD:
        return REACTED
    # Same verdict. Did anything the gate SAID change? That is the difference between a
    # gate that ignored the mutation and one that measured it and stayed inside its band.
    if base_dig is not None and mut_dig is not None:
        return UNMOVED if base_dig == mut_dig else MOVED
    return INERT


def run(subject=DEFAULT_SUBJECT, mutations=None, tiers=None, seed=20260808, verbose=True):
    from zyg_workflows.geom.anthro.gates.engine import run_gates
    from zyg_workflows.geom.anthro.gates.subject import Subject

    names = [m[0] for m in PANEL] if not mutations else list(mutations)
    panel = [m for m in PANEL if m[0] in names]
    unknown = sorted(set(names) - {m[0] for m in PANEL})
    if unknown:
        raise MutationError('unknown mutation(s): %s. Known: %s' % (', '.join(unknown), ', '.join(m[0] for m in PANEL)))

    sub = Subject.from_registry(subject)
    v0, f0, spec0 = np.array(sub.v, copy=True), np.array(sub.faces, copy=True), dict(sub.spec)

    if verbose:
        _zyg_log.info('baseline: %s (%d verts) — running the clean body first' % (subject, len(v0)))
    t0 = time.time()
    base_rep = run_gates(Subject.from_mesh(v0, f0, spec0), tiers=tiers, strict=False)
    base_full = _rows(base_rep)
    base = {g: st for g, (st, _d) in base_full.items()}
    if verbose:
        _zyg_log.info('  %d gates, %.0fs' % (len(base), time.time() - t0))

    results, per_gate = {}, {gid: {} for gid in base}
    for name, fn, breaks in panel:
        rng = np.random.default_rng(seed)
        t1 = time.time()
        try:
            vm, fm, sm = fn(v0.copy(), np.array(f0, copy=True), dict(spec0), rng)
            rep = run_gates(Subject.from_mesh(vm, fm, sm), tiers=tiers, strict=False)
            mut_full = _rows(rep)
            mut = {g: st for g, (st, _d) in mut_full.items()}
            err = None
        except Exception as e:  # noqa: BLE001
            mut, mut_full, err = {}, {}, '%s: %s' % (type(e).__name__, e)

        row = {}
        for gid, b in base.items():
            # If the run never reached the registry, NO gate was asked anything. Recording
            # 'missing' here and letting it classify as EVASIVE is what produced this
            # harness's first 34 false findings.
            m = NOT_RUN if err else mut.get(gid, 'missing')
            bd = base_full.get(gid, (None, None))[1]
            md = mut_full.get(gid, (None, None))[1] if not err else None
            row[gid] = _classify(b, m, bd, md, mut_payload=md, mut_status=mut)
            per_gate[gid][name] = {
                'baseline': b,
                'mutated': m,
                'outcome': row[gid],
                'payload_changed': (bd != md) if md is not None else None,
            }
        counts = {
            k: sum(1 for x in row.values() if x == k)
            for k in (REACTED, INERT, UNMOVED, MOVED, FRAGILE, EVASIVE, NOT_RUN, DEFERRED)
        }
        results[name] = {
            'breaks': breaks,
            'counts': counts,
            'elapsed_s': time.time() - t1,
            'harness_error': err,
            'outcome': PRECONDITION if err else 'ran',
            'precondition_note': (
                'the mutated body was refused UPSTREAM of the registry, so no '
                'gate was asked. That is the pipeline working: this body '
                'should never be measured. It is not evidence about any '
                'gate.'
            )
            if err
            else None,
        }
        if verbose:
            if err:
                _zyg_log.info(
                    '  %-26s PRECONDITION CAUGHT IT — refused before any gate ran (%.0fs)' % (name, time.time() - t1)
                )
                _zyg_log.info('      %s' % err.split('\n')[0][:140])
            else:
                _zyg_log.info(
                    '  %-26s reacted %3d  moved %3d  UNMOVED %3d  fragile %2d  '
                    'evasive %2d  deferred %2d   (%.0fs)'
                    % (
                        name,
                        counts[REACTED],
                        counts[MOVED],
                        counts[UNMOVED],
                        counts[FRAGILE],
                        counts[EVASIVE],
                        counts[DEFERRED],
                        time.time() - t1,
                    )
                )

    findings = _findings(per_gate, base)
    return {
        'schema': SCHEMA,
        'subject': subject,
        'seed': int(seed),
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'n_gates': len(base),
        'panel': [m[0] for m in panel],
        'baseline_status': base,
        'by_mutation': results,
        'by_gate': per_gate,
        'findings': findings,
        'elapsed_s': time.time() - t0,
    }


# WHICH DOMAIN EACH MUTATION ATTACKS. Used only to tell a possible fake gate apart from a
# hole in this panel; it is deliberately coarse, because a fine-grained map would be a
# second place to get the answer wrong.
MUTATION_DOMAINS = {
    'stature_shrink_12pct': ('size', 'proportion'),
    'segment_proportion_8pct': ('proportion',),
    'break_mirror_symmetry': ('symmetry',),
    'flatten_relief': ('relief',),
    'flip_face_winding': ('topology',),
    'invert_all_normals': ('topology',),
    'small_spike_1.2pct': ('surface',),
    'inject_nan': ('numeric', 'surface'),
    'single_vertex_spike': ('surface',),
    'degenerate_faces': ('topology', 'numeric'),
    'declare_wrong_sex': ('declaration',),
    'declare_wrong_age': ('declaration',),
    'girth_inflate_9pct': ('girth', 'proportion'),
    'depth_scale_10pct': ('depth', 'proportion'),
}

# Coarse domain per gate, by id. Anything unmatched returns None and is judged the strict
# way — an unclassified gate is not given the benefit of the doubt.
_DOMAIN_PATTERNS = (
    (
        'topology',
        (
            'watertight',
            'manifold',
            'winding',
            'outward_normals',
            'degenerate_geometry',
            'topology_identity',
            'self_intersection',
        ),
    ),
    ('symmetry', ('symmetry', 'asymmetry', 'mirror')),
    ('relief', ('relief', 'landmark_relief', 'canthal', 'section')),
    ('girth', ('girth', 'circumference')),
    ('depth', ('depth',)),
    (
        'proportion',
        ('height', 'breadth', 'chain', 'ratio', 'leg', 'proportion', 'mahalanobis', 'cormic', 'canon', 'phalanx'),
    ),
    ('declaration', ('age_channel', 'ancestry', 'child_')),
    (
        'registry',
        ('importable', 'provenance', 'tolerance_sanity', 'stylization_axis', 'cast_diversity', 'morph_bounds'),
    ),
)


def _domain_of(gid):
    for dom, pats in _DOMAIN_PATTERNS:
        if any(p in gid for p in pats):
            return dom
    return None


def _findings(per_gate, base):
    """The list a person should read. Ordered by how much it should worry them."""
    out = []
    for gid, row in sorted(per_gate.items()):
        # Only mutations that actually REACHED the registry are evidence about a gate.
        row = {k: r for k, r in row.items() if r['outcome'] != NOT_RUN}
        if not row:
            continue
        outcomes = [r['outcome'] for r in row.values()]
        if FRAGILE in outcomes:
            which = sorted(k for k, r in row.items() if r['outcome'] == FRAGILE)
            out.append(
                {
                    'severity': 'major',
                    'gate': gid,
                    'kind': 'fragile',
                    'mutations': which,
                    'why': 'raised instead of judging. A corrupted body is a body this '
                    'gate should FAIL cleanly; a crash is a different signal '
                    'from a verdict and can be swallowed by the wrong except.',
                }
            )
        if EVASIVE in outcomes:
            which = sorted(k for k, r in row.items() if r['outcome'] == EVASIVE)
            out.append(
                {
                    'severity': 'major',
                    'gate': gid,
                    'kind': 'evasive',
                    'mutations': which,
                    'why': 'declined to judge a body it judged a moment earlier. This '
                    'is the escape hatch the point_only defect used: declining '
                    'is not the same as judging, and a gate that ducks under a '
                    'deliberate break will duck on a real one.',
                }
            )
        if base.get(gid) in _OK and REACTED not in outcomes and MOVED not in outcomes:
            # SEVERITY MUST DISTINGUISH TWO VERY DIFFERENT THINGS, and the first version of
            # this harness did not. A gate that stayed still while mutations aimed AT ITS
            # OWN DOMAIN reached it is a possible fake gate. A gate that stayed still
            # because the panel contains nothing aimed at it is a PANEL GAP — the finding
            # is against this file, not against the gate. Reporting both as 'critical'
            # produced sixteen alarming rows of which most were my own missing coverage.
            dom = _domain_of(gid)
            reached = {m for m in row}
            targeted = {m for m in reached if dom and dom in MUTATION_DOMAINS.get(m, ())}
            if dom and not targeted:
                out.append(
                    {
                        'severity': 'minor',
                        'gate': gid,
                        'kind': 'panel_gap',
                        'domain': dom,
                        'mutations': sorted(reached),
                        'why': 'no mutation that REACHED this gate targets its domain '
                        '(%s). This is a gap in the panel, not evidence about '
                        'the gate. Add a mutation that breaks %s and survives '
                        'the precondition, then re-run.' % (dom, dom),
                    }
                )
                continue
            out.append(
                {
                    'severity': 'critical',
                    'gate': gid,
                    'kind': 'never_reacted',
                    'domain': dom,
                    'targeted_by': sorted(targeted),
                    'mutations': sorted(row),
                    'why': 'PASSED the clean body and PASSED every deliberately broken '
                    'one THAT REACHED IT. Nothing in the panel moved it. Either '
                    'it measures something the panel does not touch — in which '
                    'case a mutation for it is missing and should be added — or '
                    'it is not measuring the body at all. Mutations refused '
                    'upstream by a precondition are excluded from this judgement: '
                    'a gate cannot be blamed for a body it was never shown.',
                }
            )
    order = {'critical': 0, 'major': 1, 'minor': 2}
    return sorted(out, key=lambda f: (order.get(f['severity'], 9), f['gate']))


ARTEFACT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'data',
    'assets',
    'anthro_reports',
    'mutation',
    'latest.json',
)


def _jsonable(o):
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(x) for x in o]
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    return o


if __name__ == '__main__':  # the CLI lives in mutation_cli
    from zyg_workflows.geom.anthro.mutation_cli import main as _cli_main

    raise SystemExit(_cli_main())
