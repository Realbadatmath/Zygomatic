# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The gated subject and the shared reference-comparison machinery.

Moved verbatim out of the old single-file gates.py (lines 2010-2541).
"""

import numpy as np
from zyg_workflows.geom import mesh_skeletons as MS
from zyg_workflows.geom.anthro import integrity as IG
from zyg_workflows.geom.anthro import landmarks as LMK
from zyg_workflows.geom.anthro import measure as ME
from zyg_workflows.geom.anthro.reference import reference

from zyg_workflows.geom.anthro.gates.policy import (
    ANSUR_AGE_MAX_Y,
    ANSUR_AGE_MIN_Y,
    ANSUR_COVERAGE_NOTE,
    BUILD_TARGET_STATURE_TOL_MM,
    ERROR,
    FAIL,
    MISSING,
    NOT_APPLICABLE,
    NOT_IMPLEMENTABLE,
    PASS,
    POLICY_ERROR,
    REPORT,
    UNMEASURABLE,
    WARN,
)
from zyg_workflows.geom.anthro.gates.bands import BAND_WIDTH_BLOCK, BAND_WIDTH_WARN, SubjectError
from zyg_workflows.geom.anthro.gates.gate import _result


# ---------------------------------------------------------------------------------
# Subject
# ---------------------------------------------------------------------------------
SPEC_KEYS = {
    'sex': 'male|female. Required for every population comparison.',
    'sex_source': 'how sex was determined (declared vs inferred from the gender macro).',
    'ancestry': 'DODRace group name, or None. None is not "average human": it warns.',
    'age_years': 'chronological age of the depicted person, in years.',
    'age_source': 'how age was determined.',
    'build_target_stature_mm': 'the stature the RECIPE asked for. None -> gate MISSING.',
    'stature_tolerance_mm': 'tolerance for the stature check. Default %g mm.' % BUILD_TARGET_STATURE_TOL_MM,
    'stature_claim': "'build_target' (default) or 'anthropometric'. The second one is "
    'subject to the diurnal-variation floor.',
    'stylization': 'dict recording the BodyProportions axis intent. None -> gate MISSING.',
    'phenotype': 'anny macro dict (0..1 sliders).',
    'local_changes': 'anny local-change dict (the +/-1 morph coefficients).',
    'anatomy_layer': 'our post-morph sculpt channel. NOT a morph coefficient.',
    'bone_scales': 'per-bone scale factors applied as a pose matrix AFTER the morph '
    'stack. Recorded so a bone-scaled body says so; not bounded by the '
    'morph-coefficient rule.',
    'hand_correction': 'the solved phalanx correction this body was ISSUED with '
    '(geom.anthro.hand_correction), or None if it predates the fix. '
    'Carried on the spec rather than re-solved so that a gate run '
    'measures the hand that shipped, and so that a body issued under '
    'an older correction version is visible as such instead of '
    'silently rebuilt as a different hand.',
    'topology_scope': "integrity.TOPOLOGY_SCOPES key. Default 'full'.",
    'vhi_band': '(lo, hi) in L/m^2, declared by the caller. None -> gate MISSING.',
    'vhi_override': "dict with a 'reason' to accept an out-of-band VHI; it is logged.",
    'realism_asymmetry_injected': 'True only if realism asymmetry was deliberately added.',
    'spine_endpoints': 'declared vertebral endpoints for a curvature measure, or None.',
    'age_pair': 'name of a sibling subject that is the same skeleton at another age.',
    'cast': 'list of Subject to compare against for diversity. None -> the registry cast.',
    'cage_vert_sha256': 'expected cage hash, verified when a subject is rebuilt.',
    'contact_sheet_id': 'storyteller character id whose 48-cell contact sheet was measured '
    'by geom/mvconsist.py, e.g. "c3345deb5bde". None -> '
    't4_multiview_consistency reports undeclared and never passes. '
    'Deliberately declared rather than inferred: the mesh registry '
    'carries no contact-sheet id, so any name-to-id mapping would be a '
    'guess, and grading a sheet against the wrong body is the failure '
    'that gate exists to catch.',
}


class Subject(object):
    """A body plus everything the pipeline declared about it.

    Measurement, landmark resolution and integrity are computed once, lazily, and cached:
    a full four-tier run touches them from a dozen different gates.
    """

    def __init__(self, name, v, faces, spec=None):
        v = np.asarray(v, np.float64)
        faces = np.asarray(faces)
        if v.ndim != 2 or v.shape[1] != 3:
            raise SubjectError('v must be (N,3), got %r' % (v.shape,))
        if faces.ndim != 2 or faces.shape[1] not in (3, 4):
            raise SubjectError('faces must be (F,3) or (F,4), got %r' % (faces.shape,))
        self.name = name
        self.v = v
        self.faces = faces
        self.spec = dict(spec or {})
        unknown = sorted(k for k in self.spec if k not in SPEC_KEYS)
        if unknown:
            raise SubjectError('unknown spec key(s) %s. Known: %s' % (', '.join(unknown), ', '.join(sorted(SPEC_KEYS))))
        self._meas = None
        self._integ = None
        self._lm = None

    # -- declared facts --------------------------------------------------------
    @property
    def sex(self):
        return self.spec.get('sex')

    @property
    def ancestry(self):
        return self.spec.get('ancestry')

    @property
    def age_years(self):
        return self.spec.get('age_years')

    @property
    def is_ansur_age(self):
        a = self.age_years
        return a is not None and ANSUR_AGE_MIN_Y <= a <= ANSUR_AGE_MAX_Y

    # -- derived, cached -------------------------------------------------------
    @property
    def landmarks(self):
        if self._lm is None:
            self._lm = LMK.resolve_landmarks(
                self.v, self.faces, self.spec.get('phenotype'), self.spec.get('local_changes')
            )
        return self._lm

    @property
    def measurements(self):
        if self._meas is None:
            self._meas = ME.measure_mesh(
                self.v,
                self.faces,
                sex=self.sex,
                landmarks=self.landmarks,
                phenotype=self.spec.get('phenotype'),
                local_changes=self.spec.get('local_changes'),
                name=self.name,
            )
        return self._meas

    @property
    def integrity(self):
        if self._integ is None:
            scope = self.spec.get('topology_scope', 'full')
            self._integ = IG.check_integrity(self.v, self.faces, expect_vertices=scope, expect_faces=scope)
        return self._integ

    @property
    def stature_mm(self):
        return self.measurements['meta']['stature_m'] * 1000.0

    def mm(self, key):
        """Measured value in mm, or None with the module's own reason attached."""
        r = self.measurements['measurements'].get(key)
        if r is None:
            return None
        return r.get('value_mm')

    def ratio(self, key):
        r = self.measurements['ratios'].get(key)
        return None if r is None else r.get('value')

    def ratio_rec(self, key):
        return self.measurements['ratios'].get(key)

    # -- constructors ----------------------------------------------------------
    @classmethod
    def from_mesh(cls, v, faces, spec, name='unnamed'):
        return cls(name, v, faces, spec)

    @classmethod
    def from_registry(cls, name, overrides=None, verify_hash=True):
        """Rebuild a registered character from its recorded recipe.

        The mesh is REBUILT from params.json rather than read back from the .glb, because
        the .glb is triangulated and both measure.py and integrity.py want the quad cage.
        The rebuild is then checked against the recorded cage_vert_sha256, so a library
        drift that changes geometry under a stable recipe fails here rather than silently
        producing a report about a different body.
        """
        reg = MS._registry()
        for section in ('originals', 'derived'):
            if name in reg.get(section, {}):
                rec = reg[section][name]
                break
        else:
            known = sorted(list(reg.get('originals', {})) + list(reg.get('derived', {})))
            raise SubjectError('no registered character %r. Known: %s' % (name, ', '.join(known)))
        p = rec['params']
        phen = p['phenotype']
        locs = p.get('local_changes') or None
        anat = p.get('anatomy_layer') or None
        # bone_scales MUST be passed: mesh_skeletons._rebuild_from_params passes them and
        # derive() hashes the bone-scaled mesh, so dropping them here rebuilds a DIFFERENT
        # body and then blames the library for the hash mismatch. Measured on abel with
        # {'upperleg': 1.15}: 1.7674 m rebuilt with them, 1.5200 m without, max vertex
        # delta 247 mm, and the hash check refused to gate the character at all.
        bones = p.get('bone_scales') or None
        # params= carries the RECORDED phalanx correction (geom.anthro.hand_correction)
        # for the same reason bone_scales is passed: derive() hashed a mesh that had it,
        # so rebuilding without it gates a different body. A body with no
        # `hand_correction` key predates the fix and rebuilds uncorrected, which is what
        # keeps its recorded hash reproducible.
        v, faces, _ = MS._build_mesh(phen, locs, bones, params=p)
        v = MS._apply_anatomy(v, faces, anat, phenotype=phen, local_changes=locs, bone_scales=bones, params=p).astype(
            np.float64
        )
        expect_sha = p.get('cage_vert_sha256')
        if verify_hash and expect_sha:
            got = MS._vert_sha(v)
            if got != expect_sha:
                from zyg_workflows.geom.anthro import hand_correction as HC

                hc = p.get('hand_correction') or {}
                stale = (
                    ''
                    if hc.get('version') == HC.HAND_CORRECTION_VERSION
                    else " It records hand_correction version %s against the process's "
                    'version %d, so it may predate the phalanx correction — '
                    're-derive it, or set %s=0 to reproduce it as issued.'
                    % (hc.get('version', 'none'), HC.HAND_CORRECTION_VERSION, HC.ENV_FLAG)
                )
                raise SubjectError(
                    'rebuilt cage for %r hashes %s but the registry recorded %s — the '
                    'recipe no longer reproduces the issued mesh. Refusing to gate a body '
                    'that is not the one that shipped.%s' % (name, got[:16], expect_sha[:16], stale)
                )

        declared_sex = p.get('sex')
        if declared_sex:
            sex, sex_src = declared_sex, 'declared in params.json'
        else:
            sex = 'female' if float(phen.get('gender', 0.0)) > 0.5 else 'male'
            sex_src = (
                'INFERRED from the anny gender macro (%.3f); params.json for a '
                'DERIVED character records no sex field' % float(phen.get('gender', 0.0))
            )
        # _age_years is measure.py's mapping and it is VERIFIED there against the two
        # derived characters; re-deriving it here would create a second source of truth.
        age = ME._age_years(phen['age']) if 'age' in phen else None

        spec = {
            'sex': sex,
            'sex_source': sex_src,
            'ancestry': p.get('ancestry'),
            'age_years': age,
            'age_source': 'anny age macro %.6f via measure._age_years' % phen.get('age', float('nan')),
            'build_target_stature_mm': (p['height_target_m'] * 1000.0 if p.get('height_target_m') else None),
            'stylization': p.get('stylization'),
            'phenotype': phen,
            'local_changes': p.get('local_changes') or {},
            'anatomy_layer': p.get('anatomy_layer') or {},
            'bone_scales': p.get('bone_scales') or {},
            'hand_correction': p.get('hand_correction'),
            'topology_scope': 'full',
            'cage_vert_sha256': expect_sha,
        }
        spec.update(overrides or {})
        return cls(name, v, faces, spec)


# ---------------------------------------------------------------------------------
# Shared reference-comparison machinery
# ---------------------------------------------------------------------------------
_ADULT_REF_CACHE = {}


def adult_reference(sex):
    """The convention-matched adult: the stock anny body at the vendor's neutral macros,
    measured through this exact pipeline.

    A child's proportions can only be compared to an adult's if both were measured the
    same way. Comparing a bald mesh's head length to ANSUR's over-hair head length, or a
    free-surface crotch height to ANSUR's bar-pressed one, produces a difference that is
    mostly convention. This reference removes that: it is NOT a survey mean and is never
    presented as one.
    """
    sex = 'female' if str(sex).lower().startswith('f') else 'male'
    if sex not in _ADULT_REF_CACHE:
        phen = dict(LMK.REF_FEMALE if sex == 'female' else LMK.REF_MALE)
        v, f, _ = MS._build_mesh(phen, None)
        v = np.asarray(v, np.float64)
        out = ME.measure_mesh(v, f, sex=sex, phenotype=phen, local_changes=None, name='anny-neutral-%s' % sex)
        _ADULT_REF_CACHE[sex] = {
            'measurement': out,
            'age_years': ME._age_years(phen['age']),
            'stature_mm': out['meta']['stature_m'] * 1000.0,
            'source': (
                'anny neutral %s (all macros 0.5, age macro 0.5 = %.1f y), built '
                'and measured by this pipeline. CONVENTION-MATCHED REFERENCE, not '
                'a survey mean.' % (sex, ME._age_years(phen['age']))
            ),
        }
    return _ADULT_REF_CACHE[sex]


def _band_check(sub, ratio_key, width_block=BAND_WIDTH_BLOCK, width_warn=BAND_WIDTH_WARN):
    """Compare one measured ratio to the population band for the subject's group.

    Three things happen here that a naive band check does not do. Outside ANSUR's age
    coverage the comparison is computed and printed but downgraded to NOT APPLICABLE.
    A measurement that measure.py flagged survey_comparable=False (A-pose bideltoid, bald
    head dimensions, the hand-length definition mismatch) is downgraded to REPORT carrying
    its own reason, because failing a character for a pose artefact is a false positive.
    And a missing ancestry is carried through into the result rather than absorbed.
    """
    rec = sub.ratio_rec(ratio_key)
    if rec is None or rec.get('value') is None:
        m = sub.measurements['measurements']
        why = None
        for k, mr in m.items():
            if mr.get('ansur_ratio') == ratio_key and mr.get('reason'):
                why = '%s: %s' % (k, mr['reason'])
                break
        return _result(
            UNMEASURABLE,
            'ratio %s not produced for this mesh' % ratio_key,
            detail_reason=why or 'measure.py emitted no value for this ratio',
        )
    x = float(rec['value'])
    ref = reference()
    blk = ref.band(ratio_key, sub.sex, sub.ancestry, width=width_block)
    wrn = ref.band(ratio_key, sub.sex, sub.ancestry, width=width_warn)
    pct = ref.percentile(ratio_key, x, sub.sex, sub.ancestry)
    common = dict(
        percentile=round(pct, 2),
        mean=blk['mean'],
        sd=blk['sd'],
        n=blk['n'],
        population=blk['population'],
        ancestry=blk['ancestry'],
        ancestry_declared=blk['ancestry_declared'],
        warn_band=[wrn['lo'], wrn['hi']],
        convention=rec.get('convention'),
        landmark=rec.get('landmark'),
    )
    band = [blk['lo'], blk['hi']]

    if rec.get('survey_comparable') is False:
        return _result(
            REPORT,
            '%s = %.5f (p%.1f of the band) but measure.py marks it NOT '
            'survey-comparable, so it is reported, not gated' % (ratio_key, x, pct),
            observed=x,
            band=band,
            source=blk['source'],
            not_comparable_because=rec.get('survey_not_comparable_because'),
            **common,
        )
    if not sub.is_ansur_age:
        return _result(
            NOT_APPLICABLE,
            '%s = %.5f; subject age %s y is outside ANSUR coverage so the '
            'adult band %.4f-%.4f is shown but not applied' % (ratio_key, x, sub.age_years, blk['lo'], blk['hi']),
            observed=x,
            band=band,
            source=blk['source'],
            coverage=ANSUR_COVERAGE_NOTE,
            **common,
        )
    if x < blk['lo'] or x > blk['hi']:
        return _result(
            FAIL,
            '%s = %.5f is outside the %s band %.4f-%.4f (p%.1f)'
            % (ratio_key, x, width_block, blk['lo'], blk['hi'], pct),
            observed=x,
            band=band,
            source=blk['source'],
            **common,
        )
    if x < wrn['lo'] or x > wrn['hi']:
        return _result(
            WARN,
            '%s = %.5f is inside %s but outside %s (p%.1f)' % (ratio_key, x, width_block, width_warn, pct),
            observed=x,
            band=band,
            source=blk['source'],
            **common,
        )
    return _result(
        PASS,
        '%s = %.5f, p%.1f of %s' % (ratio_key, x, pct, blk['ancestry']),
        observed=x,
        band=band,
        source=blk['source'],
        **common,
    )


# The roll-up order. Read it as "how far is this row from being evidence that the gate
# passed", worst first. The three SKIP statuses sit ABOVE pass for the same reason MISSING
# always did: a check that did not run is not evidence that it would have passed, and a
# gate whose evidence was all skipped must not report a pass. (Before 2026-08-05 they sat
# BELOW pass, so one trivially-passing row outranked seven unmeasurable ones and a tier-1
# blocking gate that evaluated none of its evidence read 'pass'/'ok'.)
#
# REPORT MOVED FROM 5 TO 3 ON 2026-08-06 (re-review D9), i.e. from "better than a pass" to
# "beside the non-verdicts, where it belongs". The old comment argued that REPORT ranks
# last because it is deliberate non-evidence and "therefore never outranks anything" —
# which is true of an ALL-report gate and false of a MIXED one. min() over {report, pass}
# returned PASS, so a gate with one gated row that passed and one row that was merely
# printed reported a clean pass, and the half that was never gated vanished. That is the
# same sentence the SKIP statuses were moved above PASS to prevent, applied to the one
# status that had been left behind. Measured before the change: injecting L=report,
# R=pass into the roll-up returned 'pass'.
#
# REPORT keeps rank 3 rather than something worse because it is a DELIBERATE non-verdict —
# the same class of fact as NOT_APPLICABLE — and an all-REPORT gate still rolls up to
# REPORT, unchanged. What changes is only that REPORT no longer loses to PASS.
# REPORT gets a rank OF ITS OWN (4) rather than sharing 3 with the skip statuses, because
# min() over a tie returns whichever row came first and a roll-up whose answer depends on
# row order is a coin toss dressed as a rule. Ordered: a skipped check is a worse thing to
# find than a printed one, and a printed one is worse than a pass.
# POLICY_ERROR shares rank 0 with FAIL and ERROR. It is a refused finding, not a softer
# one, and a sub-check refused on provenance may never be outranked by a sibling that
# passed. Sharing the rank with FAIL is safe here for the same reason ERROR does: rank 0 is
# the worst rank, so a tie can only ever be resolved to another rank-0 status.
_ROLL_UP_ORDER = {
    FAIL: 0,
    ERROR: 0,
    POLICY_ERROR: 0,
    WARN: 1,
    MISSING: 2,
    NOT_APPLICABLE: 3,
    UNMEASURABLE: 3,
    NOT_IMPLEMENTABLE: 3,
    REPORT: 4,
    PASS: 5,
}
_SKIPPED = (NOT_APPLICABLE, UNMEASURABLE, NOT_IMPLEMENTABLE)
# Statuses that reached NO VERDICT and therefore may never be classified 'ok'. REPORT is
# here for the same reason it moved in _ROLL_UP_ORDER: a row that was printed and not
# gated has verified nothing, so counting it as ok overstates what the run established.
# See report.py's _NO_VERDICT, which is the same rule on the renderer's side of the wall.
_NO_VERDICT_STATUSES = _SKIPPED + (REPORT,)

# ONE CONTRACT FOR "A DECLARED CLAIM THAT WAS NOT EVALUATED" (re-review N2).
#
# Two gate families were doing opposite things in the identical situation. The pose layer,
# handed a subject it declared and could not evaluate, contributes UNRESOLVED to its own
# roll-up, comes out NOT_IMPLEMENTABLE, is escalated on a blocking gate and is named in
# unrun_blocking. t5_canthal_tilt, whose page prints TWO claims (a sign and a ceiling),
# scored the ceiling, found the sign explicitly unresolvable, and returned PASS — counted
# in pass=25 on the CONTROL.
#
# The contract, and it is the pose layer's: A GATE THAT DECLARES N CLAIMS AND EVALUATES
# FEWER THAN N DOES NOT PASS. The unevaluated claim contributes NOT_IMPLEMENTABLE to the
# roll-up, which cannot be outranked by the claims that did pass, and the row says which
# claim it was. This is rule 4 ("a gate that cannot compute its claim must say so with
# evidence; never a PASS") applied to a gate that computed only part of one.
#
# It is deliberately NOT the other contract. Turning an unresolvable claim into a FAIL
# would be fabricating a measurement, which is the same offence pointing the other way.
UNEVALUATED_CLAIM = NOT_IMPLEMENTABLE
DECLARED_CLAIM_CONTRACT = (
    'a gate that declares more than one claim and evaluates fewer than all of them rolls '
    'up to %s, not to pass: the claims it did evaluate are not evidence about the one it '
    'did not. The unevaluated claim is named in the explanation and in the row detail. '
    'Applied to the pose family (geom.pose_limits.pose_layer, via its UNRESOLVED '
    'contribution) and to the angle family (_canthal_verdict) alike.' % UNEVALUATED_CLAIM
)


def _claim_rollup(statuses):
    """Worst-first fold over the statuses of a gate's DECLARED claims.

    Identical arithmetic to _roll_up(), over claims rather than rows, and sharing
    _ROLL_UP_ORDER so the two can never drift. An unknown status folds to ERROR rather
    than to better-than-everything.
    """
    sts = list(statuses)
    if not sts:
        return UNEVALUATED_CLAIM
    return min(sts, key=lambda s: _ROLL_UP_ORDER.get(s, _ROLL_UP_ORDER[ERROR]))


def _roll_up(rows, id_key='id'):
    """Fold a set of sub-checks into one gate result. The worst status wins, and every
    sub-check survives into the detail so nothing is hidden by the roll-up.

    Rows marked gating=False (see _note) are NOT folded: they are declarations about the
    pipeline's inputs — "no age-pair sibling was declared", "this step is not an ordering
    constraint in the first place" — and are not evidence about this body either way. They
    still travel in the detail, and _roll_up_summary counts them separately so a reader can
    see they were excluded. If a gate has nothing BUT such rows, the headline is
    NOT_APPLICABLE: nothing gateable ran.
    """
    if not rows:
        return NOT_APPLICABLE, []
    gating = [r for r in rows if r.get('gating', True)]
    if not gating:
        return NOT_APPLICABLE, rows
    # The default is ERROR's rank, not 9. With 9 an unrecognised status sorted BETTER than
    # every real one, so a row whose status this file has never heard of would have
    # outranked a pass and carried the gate. _digit_gate and _claim_rollup already do it
    # this way; this was the last caller that did not.
    worst = min(gating, key=lambda r: _ROLL_UP_ORDER.get(r['status'], _ROLL_UP_ORDER[ERROR]))['status']
    return worst, rows


def _roll_up_summary(rows):
    """The counts a roll-up explain has to carry: how many checks produced evidence, how
    many did not, and which ones. An explain that says "8 steps, 0 violated" when 7 of the
    8 were unmeasurable is the roll-up defect wearing a sentence."""
    gating = [r for r in rows if r.get('gating', True)]
    skipped = [r for r in gating if r['status'] in _SKIPPED]
    by = {}
    for r in gating:
        by[r['status']] = by.get(r['status'], 0) + 1
    return {
        'checks': len(rows),
        'gating': len(gating),
        'informational': len(rows) - len(gating),
        'evidence': len(gating) - len(skipped),
        'skipped': len(skipped),
        'skipped_ids': [r.get('id') for r in skipped],
        'by_status': by,
    }


def _skip_phrase(rows):
    """'; 3 of 8 did not run (a, b, c)' — or '' when everything ran. Appended to every
    roll-up explain so the headline sentence cannot omit the checks that were skipped."""
    s = _roll_up_summary(rows)
    if not s['skipped']:
        return ''
    return '; %d of %d DID NOT RUN (%s)' % (s['skipped'], s['gating'], ', '.join(str(i) for i in s['skipped_ids']))


def _sub(id_, status, explain, **kw):
    d = {'id': id_, 'status': status, 'explain': explain}
    d.update(kw)
    return d


def _note(id_, status, explain, **kw):
    """A sub-row that is a DECLARATION ABOUT THE INPUTS, not evidence about the body.

    It is excluded from the roll-up headline and counted separately. Use it only where the
    row says something about what the caller declared or about the survey ("this step is
    not an ordering constraint at all"), never to excuse a check that was supposed to run
    on this body and did not — that is what the SKIP statuses are for, and they now
    outrank a pass.
    """
    d = _sub(id_, status, explain, **kw)
    d['gating'] = False
    return d


def _predictability_split():
    """Which dimensions may be gated against a stature-anchored point, read from the pack.

    Nothing in this module decides tight-vs-wide. reference.predictability() applies its
    own MEASURED rule (r >= 0.80 and residual rmse <= 30 mm on the worse sex) and this is
    only a lookup of the answer.
    """
    ref = reference()
    tight, wide = [], []
    for dim in ref.dimensions():
        p = ref.predictability(dim)
        (tight if p['policy'] == 'tight' else wide).append(dim)
    return sorted(tight), sorted(wide)
