# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""TIER 5 — the form-module payload plumbing and the section gate.

Moved verbatim out of the old single-file gates.py (lines 5546-5958).
"""

import os

from zyg_workflows.geom.anthro.gates.policy import (
    ERROR,
    FAIL,
    NOT_APPLICABLE,
    NOT_IMPLEMENTABLE,
    PASS,
    REPORT,
    UNMEASURABLE,
    WARN,
)
from zyg_workflows.geom.anthro.gates.gate import _result
from zyg_workflows.geom.anthro.gates.subject import _ROLL_UP_ORDER


# =================================================================================
# TIER 5 — FORM, ANGLE, SECTION, RELIEF AND POSE GATES
#
# Tier 5 is the anthropometrically SILENT material: angles, signs, curvature, relief,
# joint ranges and digit chains. ANSUR II measures none of it (verified — the pack ships
# 49 ratios and no angle, no curvature and no joint range), which is precisely why a book
# is allowed to set a threshold here and is not allowed to set one on a height ratio.
#
# The measurements themselves live in five modules built alongside this file:
#   geom/form/ridge.py      ridge/strip/pit relief primitive + a re-probe of 32 landmarks
#   geom/form/angles.py     angle gates with printed bands
#   geom/form/sections.py   cross-section sign/ordering gates
#   geom/form/hands.py      digit chains, phalanx ratios, child hand form
#   geom/pose_limits.py     joint ROM, pose stiffness, kinematic invariants
# This file OWNS NO GEOMETRY for tier 5. It imports, adapts and registers, so that a
# threshold has exactly one home and a verdict has exactly one shape.
#
# ROLLBACK: ZYG_ANTHRO_TIER5, default 1. At 0 every tier-5 gate returns not_applicable
# NAMING THE FLAG and no form module is imported. The gates stay REGISTERED when disabled
# on purpose: dropping them from the registry would make a disabled tier and a tier that
# never existed look identical in the artefact, and a blocking gate that did not run would
# vanish from `blocking_gates_not_run` instead of being named there.
# =================================================================================
ZYG_TIER5_FLAG = 'ZYG_ANTHRO_TIER5'


def _tier5_enabled():
    return str(os.environ.get(ZYG_TIER5_FLAG, '1')).strip().lower() not in ('0', 'false', 'no', 'off', '')


# The five modules, by the name this file uses for them. `geom.pose_limits` sits outside
# geom.form on purpose (it is about the rig, not the surface) and is listed here anyway so
# that one import check covers all five.
_FORM_MODULES = (
    ('ridge', 'geom.form.ridge'),
    ('angles', 'geom.form.angles'),
    ('sections', 'geom.form.sections'),
    ('hands', 'geom.form.hands'),
    ('pose_limits', 'geom.pose_limits'),
)
_FORM_IMPORTED = {}


def form_module(key):
    """(module, None) or (None, why-not). Never raises, never returns a stub.

    Imported LAZILY rather than at the top of this file so that a break in one of the five
    new modules costs the five gates that read it and not the whole 36-gate engine. The
    failure is still loud: every gate that cannot get its module returns status ERROR,
    which gates.py classifies as blocking for a blocking gate and which report.py counts in
    its own 'error' bucket. It is never 'skip' and never 'pass'.
    """
    if key in _FORM_IMPORTED:
        return _FORM_IMPORTED[key]
    dotted = dict(_FORM_MODULES).get(key)
    if dotted is None:
        _FORM_IMPORTED[key] = (None, 'no module registered under key %r' % key)
        return _FORM_IMPORTED[key]
    try:
        import importlib

        _FORM_IMPORTED[key] = (importlib.import_module(dotted), None)
    except Exception as e:  # noqa: BLE001
        import traceback

        _FORM_IMPORTED[key] = (
            None,
            '%s could not be imported: %s: %s\n%s' % (dotted, type(e).__name__, e, traceback.format_exc()[-1200:]),
        )
    return _FORM_IMPORTED[key]


# Fallback payload cache, keyed by the subject's identity rather than stored on it.
#
# F9: the previous version returned a FRESH EMPTY DICT when the attribute could not be set
# (a Subject with __slots__), which silently disables caching — measure_angles alone is
# ~16 s and seven gates read it, so the same subject would pay it seven times with nothing
# in the report to say so. Caching is a performance property, not a correctness one, so the
# fix is to keep caching by another route and to RECORD it when even that is impossible.
_FORM_CACHE_FALLBACK = {}
_FORM_CACHE_NOTE = {}


def _form_cache_key(sub):
    return (getattr(sub, 'name', None), (getattr(sub, 'spec', None) or {}).get('cage_vert_sha256'), id(sub))


def _form_cache(sub):
    c = getattr(sub, '_tier5_cache', None)
    if c is not None:
        return c
    c = {}
    try:
        sub._tier5_cache = c
        return c
    except AttributeError:  # a Subject with __slots__
        key = _form_cache_key(sub)
        if key not in _FORM_CACHE_FALLBACK:
            _FORM_CACHE_FALLBACK[key] = {}
            _FORM_CACHE_NOTE[key] = (
                'this Subject does not accept an attribute (__slots__), so the tier-5 '
                'payload cache is held in gates._FORM_CACHE_FALLBACK keyed by '
                '(name, cage_vert_sha256, id). Caching is still in force; if this key were '
                'unusable every reader would recompute measure_angles (~16 s x 7 gates).'
            )
        return _FORM_CACHE_FALLBACK[key]


def _p_sections(sub, M):
    return M.evaluate(
        sub.v,
        sub.faces,
        lm=sub.landmarks,
        phenotype=sub.spec.get('phenotype'),
        local_changes=sub.spec.get('local_changes'),
        sex=sub.sex,
        name=sub.name,
    )


def _p_angles(sub, M):
    return M.measure_angles(
        sub.v,
        sub.faces,
        phenotype=sub.spec.get('phenotype'),
        local_changes=sub.spec.get('local_changes'),
        landmarks=sub.landmarks,
        sex=sub.sex,
        age_years=sub.age_years,
    )


def _p_pose_limits(sub, M):
    """EVERY subject each pose gate declares — the rest rig AND the fitted pose library.

    THE DEFECT THIS CLOSES (D3 / F3 / calibration finding 6). This adapter used to call
    run_character(), whose own docstring says it evaluates the rig "in its shipped REST
    CONFIGURATION". Rest pose is all-zero axis-angle, so t5_joint_rom returned "0 of 11
    ROM sub-checks failed" on every body — a blocking PASS that was a property of the pose
    it was handed, not of anything gated — while the registry text claimed the subject was
    a joint angle "in our own rig AND IN OUR OWN FITTED POSE LIBRARY". Run on the poses we
    actually ship to the VACE control channel, the identical gate fails 44/44 on abel and
    43/43 on cornelis.

    pose_layer() evaluates both subjects, publishes each verdict separately, and rolls them
    up with a DECLARED-but-unevaluated subject contributing UNRESOLVED — so a gate with no
    fitted library to check now reports unresolved rather than a rest-pose pass. Its dict
    contract is machine-verified on every call (PoseLayerContractError), which is what
    stops this adapter from reading keys the producer never returns (D1/F2).

    Cost measured 2026-08-06 on abel: run_character 0.4 s, pose_layer 1.3 s including all
    44 fitted poses and the diversity statistic. The library half is not expensive here.
    """
    return M.pose_layer(sub.name, sub.spec.get('phenotype'), sub.spec.get('local_changes'))


def _p_hands(sub, M):
    # params= carries the correction this body was ISSUED with. Without it the digit pack
    # would re-solve one from the phenotype, which is the same answer for a body issued
    # under the current version and the WRONG answer for one issued under an older
    # version or before the correction existed — i.e. it would report on a hand that
    # never shipped, which is the whole failure mode t5_phalanx_ratio exists to catch.
    return M.check_digits(
        sub.spec.get('phenotype'),
        sub.spec.get('local_changes'),
        sub.spec.get('bone_scales'),
        sub.spec.get('anatomy_layer'),
        params={'hand_correction': sub.spec.get('hand_correction')},
    )


def _p_ridge(sub, M):
    """Both ridge probe sets on one body, at the module's OWN measured null cut.

    ridge_null() is NOT re-run here: RIDGE_NULL_P99 already ships the measured per-station
    p99 for both modes (120 pools x 3 sizes, seed 20260806), and station_cut() reads it
    when no null object is passed. Re-measuring the null per character would cost minutes
    per body and would replace a fixed, reproducible cut with one that moves from run to
    run — the exact way a threshold ends up calibrated on our own assets.
    """
    from zyg_workflows.geom.form import curvature as CV
    from zyg_workflows.geom.form import regions as RG

    v, faces = sub.v, sub.faces
    S = sub.stature_mm / 1000.0
    ar = CV.mixed_voronoi_area(v, faces)
    nv = CV.vertex_normals(v, faces)
    cu = CV.curvature(v, faces, stature_m=S, normals=nv)
    doc = RG.load_regions(len(v))
    body = M.probe_pools(v, faces, M.body_pools(v, faces, S, nv, doc), stature_m=S, areas=ar, normals=nv, curv=cu)
    head = M.probe_pools(v, faces, M.head_pools(v, faces, S, nv), stature_m=S, areas=ar, normals=nv, curv=cu)
    return {'body': body, 'head': head, 'stature_m': S}


_FORM_PAYLOADS = {
    'sections': _p_sections,
    'angles': _p_angles,
    'pose_limits': _p_pose_limits,
    'hands': _p_hands,
    'ridge': _p_ridge,
}


def form_payload(sub, key):
    """(payload, None) or (None, why-not), computed once per subject and cached.

    measure_angles alone costs ~16 s and seven gates read it; the ridge double probe costs
    ~7 s and two gates read it. A builder that raises is cached AS THE ERROR STRING, never
    as an empty payload: an empty payload reads downstream as "nothing to report", which is
    the silent pass this package exists to prevent.
    """
    cache = _form_cache(sub)
    if key in cache:
        return cache[key]
    M, err = form_module(key)
    if M is None:
        cache[key] = (None, err)
        return cache[key]
    try:
        cache[key] = (_FORM_PAYLOADS[key](sub, M), None)
    except Exception as e:  # noqa: BLE001
        import traceback

        cache[key] = (
            None,
            'geom.%s payload raised %s: %s\n%s' % (key, type(e).__name__, e, traceback.format_exc()[-1200:]),
        )
    return cache[key]


def _t5_disabled(gate_id):
    """The rollback-flag row, stating ONLY what the flag actually does.

    F5: this row used to assert "no form module was imported", which is false and was
    measured to be false. t4_form_modules_importable is TIER 4, carries no _tier5_enabled()
    guard, and imports all five modules on every run — so with the flag at 0 the loaded
    module list after gating is still ['geom.form', 'geom.form.angles',
    'geom.form.curvature', 'geom.form.hands', 'geom.form.ridge', 'geom.form.sections',
    'geom.pose_limits']. The claim is deleted rather than repaired, because the tier-4
    import gate SHOULD keep running when tier 5 is off: its whole job is to notice a module
    that will not load, and a rollback flag that also switched off the detector would hide
    the thing it exists to find. What the flag gives is that no tier-5 gate CONSUMES a form
    module — that much is true, and is all that is claimed here.
    """
    return _result(
        NOT_APPLICABLE,
        '%s=%r, so tier 5 is switched off: this gate did NOT run and this row '
        'is not a pass. NOTE the exact scope — no tier-5 gate consumes a form '
        'module while the flag is 0, but the modules ARE still imported, by the '
        'tier-4 gate t4_form_modules_importable, which is deliberately not '
        'guarded by this flag (a rollback that also disabled the '
        'import-detector would hide the failure it exists to catch).'
        % (ZYG_TIER5_FLAG, os.environ.get(ZYG_TIER5_FLAG)),
        observed=None,
        source='rollback flag %s (default 1)' % ZYG_TIER5_FLAG,
        rollback_flag=ZYG_TIER5_FLAG,
        flag_scope='tier-5 gate execution only; t4_form_modules_importable is '
        'tier 4 and still imports geom.form.* and geom.pose_limits',
    )


def _t5_payload(sub, key, gate_id):
    """(payload, None) or (None, error_result). The second element is already a _result."""
    if not _tier5_enabled():
        return None, _t5_disabled(gate_id)
    payload, err = form_payload(sub, key)
    if payload is None:
        return None, _result(
            ERROR,
            'gate %s could not obtain its measurement: %s' % (gate_id, (err or 'unknown').splitlines()[0]),
            observed=None,
            source='geom.%s' % key,
            traceback=err,
        )
    return payload, None


# -- status translation ------------------------------------------------------------
# Each module speaks its own vocabulary. The two that differ from this file's are mapped
# HERE, by table, so the mapping is a fact in the code. An unrecognised status becomes
# ERROR and not PASS: a status this file cannot read is a defect, not a clean bill.
_SECTION_STATUS = {
    'pass': PASS,
    'fail': FAIL,
    'warn': WARN,
    'report': REPORT,
    'unmeasurable': UNMEASURABLE,
    'not_applicable': NOT_APPLICABLE,
}
_HAND_STATUS = {
    'pass': PASS,
    'fail': FAIL,
    'warn': WARN,
    'report': REPORT,
    'unmeasurable': UNMEASURABLE,
    'not_implementable': NOT_IMPLEMENTABLE,
    'not_applicable': NOT_APPLICABLE,
}


def _xlate(raw, table, where):
    st = table.get(str(raw))
    if st is None:
        return ERROR, (
            '%s returned status %r, which this file has no mapping for. '
            'Unmapped is recorded as ERROR, never as pass.' % (where, raw)
        )
    return st, None


# -- sections ----------------------------------------------------------------------
def _section_gate(section_gate_id):
    def fn(sub):
        payload, bail = _t5_payload(sub, 'sections', section_gate_id)
        if bail is not None:
            return bail
        g = (payload.get('gates') or {}).get(section_gate_id)
        if g is None:
            return _result(
                ERROR,
                'geom.form.sections.evaluate returned no gate %r; it '
                'returned %s' % (section_gate_id, sorted(payload.get('gates') or {})),
            )
        st, why = _xlate(g.get('status'), _SECTION_STATUS, 'geom.form.sections.%s' % section_gate_id)
        claims = g.get('claims') or {}
        rolled = {k: c.get('status') for k, c in sorted(claims.items())}
        failed = sorted(k for k, c in claims.items() if c.get('status') == 'fail')
        src = next((c.get('source') for c in claims.values() if c.get('source')), None)
        return _result(
            st,
            why
            or (
                '%d claim(s): %s%s'
                % (
                    len(claims),
                    ', '.join('%s=%s' % kv for kv in sorted(rolled.items())),
                    '' if not failed else ' | FAILED: %s' % ', '.join(failed),
                )
            ),
            observed=rolled,
            band=None,
            source=src,
            failed_claims=failed,
            claims=claims,
            module_flag=(payload.get('meta') or {}).get('flag'),
            stature_m=(payload.get('meta') or {}).get('stature_m'),
        )

    fn.__name__ = section_gate_id
    return fn


def t5_neck_section(sub):
    """The neck-section gate PLUS the paired sex test its own text says gates it.

    THE DEFECT THIS CLOSES (calibration finding 5). geom/form/sections.py's `taper` claim
    is REPORT-only and its explanation says, in the shipped artefact, that "the sex signal
    is gated by the paired direction test in neck_taper_dimorphism()". That function had
    exactly one caller in the whole repository — sections.py's own `main()` CLI printout.
    It is not in evaluate(), so it was in none of this gate's claims, and the HeadNeck
    p.172/173 sex claim could not fail on any character we ship. It is the only
    parameter-free form of the claim (hold one recipe, flip ONLY the gender macro, require
    the female neck to taper more), and it is the form that FAILS on the neutral recipe.

    It is wired in here, scored, and rolled up worst-first with the module's own claims.
    Measured cost: ~0 s per subject — the two meshes it builds are already cached.
    """
    base = _section_gate('t5_neck_section')(sub)
    if base['status'] in (NOT_APPLICABLE, ERROR):
        return base
    M, err = form_module('sections')
    if M is None or not hasattr(M, 'neck_taper_dimorphism'):
        base['status'] = ERROR
        base['explain'] = (
            'the paired neck-taper sex test could not be reached: %s. The '
            'gate claims to test it, so a missing test is an ERROR and not '
            'a quiet four-claim pass.' % (err or 'geom.form.sections has no neck_taper_dimorphism')
        )
        return base
    try:
        d = M.neck_taper_dimorphism(sub.spec.get('phenotype'), sub.spec.get('local_changes'))
    except Exception as e:  # noqa: BLE001
        import traceback

        base['status'] = ERROR
        base['explain'] = 'neck_taper_dimorphism raised %s: %s' % (type(e).__name__, e)
        base.setdefault('detail', {})['dimorphism_traceback'] = traceback.format_exc()[-1200:]
        return base
    st, why = _xlate(d.get('status'), _SECTION_STATUS, 'geom.form.sections.neck_taper_dimorphism')
    worst = min([base['status'], st], key=lambda s: _ROLL_UP_ORDER.get(s, _ROLL_UP_ORDER[ERROR]))
    base['status'] = worst
    base['explain'] = '%s | sex_taper_dimorphism=%s: %s' % (
        base.get('explain') or '',
        d.get('status'),
        why or d.get('explain') or '',
    )
    det = base.setdefault('detail', {})
    det['sex_taper_dimorphism'] = {
        'status': d.get('status'),
        'claim': d.get('claim'),
        'source': d.get('source'),
        'explain': d.get('explain'),
        'male_ratio': (d.get('evidence') or {}).get('male_ratio'),
        'female_ratio': (d.get('evidence') or {}).get('female_ratio'),
        'delta': (d.get('evidence') or {}).get('delta'),
        'note': "PAIRED DIRECTION TEST, no threshold: hold this character's recipe, flip "
        'ONLY the gender macro, require the female neck to taper more. Wired into '
        'the gate 2026-08-06; before that the gate text said it gated the sex '
        'signal and nothing called it.',
    }
    if isinstance(base.get('observed'), dict):
        base['observed'] = dict(base['observed'], sex_taper_dimorphism=d.get('status'))
    return base
