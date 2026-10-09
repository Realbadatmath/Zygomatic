# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The stages of `selftest_rules._selftest_digest`, one assertion family per function.

Extracted from selftest_rules.py so each family can be exercised on its own: the
self-test used to be one 335-line body, which meant a single failure told you only that
"the digest self-test failed". Every function here raises AssertionError with the same
message the original raised, in the same order, and nothing in this module reads the
parent — the import direction is selftest_rules -> selftest_rules_digest.
"""

import json
import re
from zyg_workflows.geom.anthro.report.constants import (
    PASS,
    _CLOCK_RESIDUE_CONTENT_KEYS,
    _COUNT_KEYS,
    _INSTRUMENTATION_KEYS,
    _NO_VERDICT,
    _VERDICT_STATUSES,
)
from zyg_workflows.geom.anthro.report.textfmt import _jsonable, _num
from zyg_workflows.geom.anthro.report.document import build
from zyg_workflows.geom.anthro.report.digest import (
    _digest_residue,
    _is_instrumentation_key,
    _looks_like_a_clock_key,
    _volatile_content,
    stable_sha,
)
from zyg_workflows.geom.anthro.report.renderers import render_summary, render_text


def sneaky_gate():
    """The gate row that stamps a clock under a name the vocabulary does not have.

    Returns a fresh gate dict. The SAME object is handed to
    `assert_unknown_clock_name_is_a_defect` and `assert_declared_content_clocks`, as the
    single original body did, so the second one sees whatever `build` left behind.
    """
    return {
        'id': 'g_clock',
        'tier': 'frame',
        'severity': 'block',
        'status': 'pass',
        'observed': 0.5,
        'band': [0.0, 1.0],
        'source': 'HOUSE: fixture',
        'explanation': 'stamps a clock under a name the vocabulary does not have',
        'detail': {'probe_walltime_of_run': 0.42, 'checked_on': '2026-08-06T13:21:52'},
    }


def assert_fixture_is_armed(doc):
    """THE ARMING CHECK: the fixture still carries a NESTED wall-clock field.

    If it stops doing so, every assertion in the rest of the self-test is vacuously true
    and the test goes back to blessing the bug. Also pins the document's own
    `stable_sha256` against a fresh `stable_sha(doc)`.
    """
    by = {g['id']: g for g in doc['gates']}
    ev = by['stature_declared_vs_built']['evidence']
    if not (isinstance(ev, dict) and _num(ev.get('ms')) is not None):
        raise AssertionError('the fixture no longer carries gates[].evidence.ms, so this test tests nothing')
    if _num(ev['per_side']['L']['ms']) is None:
        raise AssertionError(
            'the fixture no longer carries a timing field NESTED inside gates[], which is the '
            'exact depth the old test could not reach'
        )
    if not (doc['stable_sha256'] == stable_sha(doc)):
        raise AssertionError


def assert_digest_ignores_the_clock(doc, fx):
    """THE CLOCK MOVES AND THE DIGEST DOES NOT — and it is not deaf to content either.

    Four claims, in the original order: a JSON round trip does not move the digest (this
    is how it reaches a consumer); mutating every wall-clock field at every depth it
    appears at does not move it; a CONTENT leaf at the SAME depth DOES move it, and so do
    status / observed / severity (or the strip has started eating the report instead of
    the clock); two builds of the same report agree, which is the claim the field's name
    makes, kept as a consequence rather than as the proof. Finally every removal is NAMED
    — a digest that quietly drops fields is the same defect with the sign reversed, so
    the excluded paths travel in the document.
    """
    rt = json.loads(json.dumps(doc, sort_keys=True, default=_jsonable))
    if not (stable_sha(rt) == doc['stable_sha256']):
        raise AssertionError('the digest must survive a round trip')
    hot = json.loads(json.dumps(doc, default=_jsonable))
    hby = {g['id']: g for g in hot['gates']}
    hby['stature_declared_vs_built']['evidence']['ms'] = 999.999
    hby['stature_declared_vs_built']['evidence']['per_side']['L']['ms'] = 0.001
    hby['stature_declared_vs_built']['evidence']['per_side']['R']['ms'] = 88.0
    hot['volatile']['generated'] = '1999-01-01T00:00:00'
    hot['volatile']['measurement_elapsed_s'] = 1234.5
    if not (stable_sha(hot) == doc['stable_sha256']):
        raise AssertionError('the digest moved when only wall-clock timings moved — stable_sha256 is a nonce')
    cold = json.loads(json.dumps(doc, default=_jsonable))
    cby = {g['id']: g for g in cold['gates']}
    cby['stature_declared_vs_built']['evidence']['per_side']['L']['value'] = 99
    if not (stable_sha(cold) != doc['stable_sha256']):
        raise AssertionError('a content change nested inside gates[] did not move the digest')
    for key, val in (('status', 'fail'), ('observed', 1.234), ('severity', 'block')):
        c2 = json.loads(json.dumps(doc, default=_jsonable))
        [g for g in c2['gates'] if g['id'] == 'stature_declared_vs_built'][0][key] = val
        if not (stable_sha(c2) != doc['stable_sha256']):
            raise AssertionError('the digest is blind to a change of %s' % key)
    d2 = build(fx, None, name='fixture', sex='male')
    if not (d2['stable_sha256'] == doc['stable_sha256']):
        raise AssertionError('two builds, two digests')
    dg = doc['digest']
    if not (dg['stable'] is True and dg['unstable_fields'] is None):
        raise AssertionError
    excl = dg['instrumentation_excluded']
    if not (any(p.endswith('.evidence.ms') for p in excl)):
        raise AssertionError(excl)
    if not (any(p.endswith('.per_side.L.ms') for p in excl)):
        raise AssertionError(excl)
    if not (dg['n_instrumentation_excluded'] == len(excl) >= 3):
        raise AssertionError
    if not (all(_is_instrumentation_key(p.rsplit('.', 1)[-1]) for p in excl)):
        raise AssertionError(excl)


def assert_unknown_clock_name_is_a_defect(sneaky):
    """A NEW CLOCK, UNDER A NAME THE STRIPPER DOES NOT KNOW, IS A DEFECT AND SAYS SO.

    Takes the `sneaky_gate()` row, builds a report around it and requires the digest to
    declare itself unstable, to name both smuggled paths, to raise the
    `digest_includes_the_clock` alarm, to lose the PASS and the zero exit code, and to
    say so in both the text report and the one-line summary. Without this, the fix holds
    only until the next timer is added, which is precisely how NEW-4 happened.
    """
    s = build({'tiers': {'frame': [sneaky]}}, None, name='clock', sex='male')
    if s['digest']['stable'] is not False:
        raise AssertionError('a per-run clock survived the strip and the digest still claimed to be stable')
    paths = {r['path'] for r in s['digest']['unstable_fields']}
    if not (any(p.endswith('probe_walltime_of_run') for p in paths)):
        raise AssertionError(paths)
    if not (any(p.endswith('checked_on') for p in paths)):
        raise AssertionError(paths)
    if 'digest_includes_the_clock' not in {a['kind'] for a in s['policy_alarms']}:
        raise AssertionError
    if not (s['verdict'] != PASS and s['exit_code'] != 0):
        raise AssertionError('a digest that cannot support its own name is not a silent PASS')
    if 'DIGEST IS NOT STABLE' not in render_text(s):
        raise AssertionError
    if 'sha_stable=NO' not in render_summary(s):
        raise AssertionError


# THE CLASS, NOT THE VOCABULARY (W4-2). `probe_walltime_of_run` matches the segment
# 'walltime' and `checked_on` is caught by the ISO-value regex, so the case above only
# ever sampled INSIDE the region the detector already covered and could not discover that
# the region was narrow. It was: measured against the shipped detector, NINETEEN ordinary
# names were silent nonces — they survived the strip, raised nothing, and moved the sha.
# Every one of them is here, and the last two need no name at all: a per-run value under a
# name nobody has ever thought of, and a UUID. This is what makes the fix a class fix
# rather than a longer list, which is the same defect one iteration later.
_NOW = 1786000000.0  # a plausible unix epoch, as a bare float
SILENT_BEFORE = (
    ('created_at', _NOW),
    ('updated_at', _NOW),
    ('measured_at', _NOW),
    ('gen_sec', 12.5),
    ('render_sec', 0.5),
    ('cost_s', 3.25),
    ('budget_s', 10.0),
    ('secs_taken', 4.0),
    ('sec', 9.0),
    ('lap', 2.5),
    ('tick', 17.0),
    ('unix', _NOW),
    ('when', _NOW),
    ('at', _NOW),
    ('stopwatch', 1.5),
    ('host_uptime', 98765.0),
    ('pid', 48213),
    ('run_uuid', 'not-a-shape-test'),
    ('gate_evaluation_wall_clock_in_milliseconds', 4.2),
    ('marker', _NOW),
    ('probe_ref', '9f1c2d34-5e6a-4b7c-8d9e-0f1a2b3c4d5e'),
)


def nonce_gate(name, value):
    """A gate row carrying `{name: value}` plus one content field, for the nonce sweep."""
    return {
        'id': 'g_' + re.sub(r'[^a-z0-9]+', '_', name.lower())[:20],
        'tier': 'frame',
        'severity': 'block',
        'status': 'pass',
        'observed': 0.5,
        'band': [0.0, 1.0],
        'source': 'HOUSE: fixture',
        'detail': {name: value, 'n_vertices': 226},
    }


def assert_silent_nonces_are_caught():
    """Each of the 21 SILENT_BEFORE names, injected at the depth the real clock lives at.

    Every one is asserted to be caught AND to be caught for a stated reason: the digest
    declares itself unstable, the path is named, the `digest_includes_the_clock` alarm
    fires, and the verdict is not a PASS.
    """
    for nm, val in SILENT_BEFORE:
        d = build({'tiers': {'frame': [nonce_gate(nm, val)]}}, None, name='resid', sex='male')
        if d['digest']['stable'] is not False:
            raise AssertionError(
                'a per-run value named %r is a SILENT NONCE: it survives the strip, raises no '
                'alarm and moves stable_sha256' % nm
            )
        paths = {r['path'] for r in d['digest']['unstable_fields']}
        if not (any(p.endswith(nm) for p in paths)):
            raise AssertionError((nm, paths))
        if 'digest_includes_the_clock' not in {a['kind'] for a in d['policy_alarms']}:
            raise AssertionError(nm)
        if not (d['verdict'] != PASS):
            raise AssertionError(nm)


def assert_the_clock_vocabulary():
    """CONTROL: content names and content values are silent, clock names are not.

    First the same gate shape as the nonce sweep with a CONTENT name and a CONTENT value,
    which must be stable and must PASS — so the sweep above is about per-run values and
    not about "any extra field". Then the live false positives the length bail was really
    about, the two identifier-shaped keys over 40 characters it used to exempt along with
    them, and THE THIRTEEN FALSE POSITIVES A BARE 'at' SEGMENT PRODUCED ON EVERY LIVE
    BODY: widening the alarm to catch `created_at` by segment rather than by suffix made
    the detector fire on English prepositions inside ordinary field names, and a detector
    that cries wolf on a real report is a detector somebody switches off.
    """
    quiet = build(
        {
            'tiers': {
                'frame': [
                    {
                        'id': 'g_q',
                        'tier': 'frame',
                        'severity': 'block',
                        'status': 'pass',
                        'observed': 0.5,
                        'band': [0.0, 1.0],
                        'source': 'HOUSE: fixture',
                        'detail': {
                            'n_vertices': 226,
                            'date': '1988-04-01',
                            'max_abs_drift': 0.0154,
                            'directed_edges': 82260,
                        },
                    }
                ]
            }
        },
        None,
        name='quiet',
        sex='male',
    )
    if quiet['digest']['stable'] is not True:
        raise AssertionError(quiet['digest']['unstable_fields'])
    if not (quiet['verdict'] == PASS):
        raise AssertionError(quiet['policy_alarms'])
    if _looks_like_a_clock_key('null_rate_point_only_or_better_either_mode'):
        raise AssertionError
    if _looks_like_a_clock_key('waist_circumference_omphalion_over_stature'):
        raise AssertionError
    for content_key in (
        'at_drive_deg',
        'max_fans_at_a_vertex',
        'gradient_max_at_wrist',
        'group_mean_spread_mm_at_this_stature',
        'columella_at_+0.8962',
        'comparator_discriminates_at_this_joint',
        'subject_owned_by_forearm_at_every_angle',
    ):
        if _looks_like_a_clock_key(content_key):
            raise AssertionError(content_key)
    for clock_key in (
        'created_at',
        'updated_at',
        'measured_at',
        'gen_sec',
        'cost_s',
        'host_uptime',
        'run_uuid',
        'secs_taken',
    ):
        if not (_looks_like_a_clock_key(clock_key)):
            raise AssertionError(clock_key)
    if not (_looks_like_a_clock_key('gate_evaluation_wall_clock_in_milliseconds')):
        raise AssertionError('the length bail must not exempt a long IDENTIFIER; it is about prose')


def assert_volatile_is_outside_the_digest(doc):
    """W4-4: THE ONE BLOCK THE DIGEST CANNOT SEE INTO.

    `volatile` is dropped by name and the residue detector runs on a tree it has already
    been removed from, so content placed there is invisible twice over, and nothing used
    to assert the boundary. `_volatile_content` must find nothing in the real block and
    nothing in a pure-clock block, and must name a smuggled measurement; a build that
    smuggles one must be unstable, must raise `volatile_contains_content` and must not
    PASS, while the same build without the smuggled key is stable and passes.
    """
    if not (_volatile_content(doc['volatile']) == []):
        raise AssertionError(doc['volatile'])
    if not (_volatile_content({'ms': 1.0, 'generated': 'x'}) == []):
        raise AssertionError
    if not (_volatile_content({'stature_m': 1.85}) == ['volatile.stature_m']):
        raise AssertionError
    okv = {
        'id': 'g_ok',
        'tier': 'frame',
        'severity': 'block',
        'status': 'pass',
        'observed': 0.5,
        'band': [0.0, 1.0],
        'source': 'HOUSE: fixture',
    }
    vd = build({'tiers': {'frame': [okv]}}, {'meta': {'generated': {'stature_m': 1.85}}}, name='vol', sex='male')
    if not (vd['digest']['volatile_content_fields'] == ['volatile.measurement_generated.stature_m']):
        raise AssertionError(vd['digest'])
    if vd['digest']['stable'] is not False:
        raise AssertionError('content the digest cannot see is not stability')
    if 'volatile_contains_content' not in {a['kind'] for a in vd['policy_alarms']}:
        raise AssertionError
    if not (vd['verdict'] != PASS):
        raise AssertionError('a report with content outside its own digest is not a PASS')
    vok = build({'tiers': {'frame': [okv]}}, {'meta': {'generated': '2026-08-06T00:00:00'}}, name='vol2', sex='male')
    if not (vok['digest']['stable'] is True and vok['verdict'] == PASS):
        raise AssertionError(vok['policy_alarms'])


def assert_declared_content_clocks(sneaky):
    """THE TWO FALSE POSITIVES MEASURED ON THE LIVE BODIES, and the one declared exemption.

    A detector that cries wolf on a real report is a detector somebody switches off, and
    then the next nonce ships. The first live key is a monotonicity check on a landmark
    chain; the second is a doc['provenance'] key, which is the whole citation as prose and
    contains the words "rubber stamp". `first_invalidated_at` now READS as a clock — that
    is what adding the '_at' family to the alarm means (W4-2), and it is the reason the
    exemption list exists: it is content by DECLARATION, not by shape, and the exemption
    is applied in _digest_residue, so the alarm stays quiet while the field stays inside
    the hash. The control is that an UNDECLARED `_at` key still raises it. Finally the
    same `sneaky` gate with the clock removed is stable and passes, so the assertions in
    `assert_unknown_clock_name_is_a_defect` are about the clock and not about the gate.
    """
    if _looks_like_a_clock_key('monotonic_chain_helper'):
        raise AssertionError
    if _looks_like_a_clock_key(
        'CANON — Anatomy For Sculptors p.181-182 ... a blocking rubber stamp ... SUBJECT CORRECTED 2026-08-06 ...'
    ):
        raise AssertionError
    for content_key in ('date', 'section_area', 'n', 'per_side', 'max_abs_drift', 'stature_m'):
        if _looks_like_a_clock_key(content_key):
            raise AssertionError(content_key)
    if not (_looks_like_a_clock_key('first_invalidated_at')):
        raise AssertionError
    if not (_digest_residue({'first_invalidated_at': '2026-08-06T13:21:52'}) == []):
        raise AssertionError('the one declared content clock must not raise the residue alarm')
    if not (_digest_residue({'second_invalidated_at': '2026-08-06T13:21:52'})):
        raise AssertionError('control: an UNDECLARED _at key must raise it, or the exemption is a blanket')
    for clock_key in (
        'probe_walltime_of_run',
        'run_duration',
        'started_timestamp',
        'gate_elapsed',
        'epoch',
        'wallclock_of_probe',
        'elapsed ms',
        'time-of-probe',
    ):
        if not (_looks_like_a_clock_key(clock_key)):
            raise AssertionError(clock_key)
    clean = build({'tiers': {'frame': [dict(sneaky, detail={'n_vertices': 226})]}}, None, name='clock2', sex='male')
    if not (clean['digest']['stable'] is True and clean['verdict'] == PASS):
        raise AssertionError


def assert_structural_invariants():
    """THE STRUCTURAL INVARIANTS between the stripper, the alarm and the status buckets.

    A key that is both stripped from the hash and exempt from the residue alarm would be
    an invisible per-run nonce by construction, so the two vocabularies must be disjoint
    and each must agree with `_is_instrumentation_key`. The stripper must also not eat the
    report: every content field named here must survive it. And every status must be
    either a verdict or not one — a third case means a bucket has appeared.
    """
    if _INSTRUMENTATION_KEYS & _CLOCK_RESIDUE_CONTENT_KEYS:
        raise AssertionError('a key cannot be both removed from the digest and exempt from the clock alarm')
    for k in sorted(_INSTRUMENTATION_KEYS):
        if not (_is_instrumentation_key(k)):
            raise AssertionError(k)
    for k in sorted(_CLOCK_RESIDUE_CONTENT_KEYS):
        if _is_instrumentation_key(k):
            raise AssertionError('%r is declared CONTENT but the stripper removes it from the digest' % k)
    for k in (
        'status',
        'observed',
        'band',
        'source',
        'severity',
        'stature_m',
        'date',
        'n',
        'value',
        'provenance_class',
        'delta_from_band',
        'reference_rejection_rate',
        'population',
        'explanation',
    ):
        if _is_instrumentation_key(k):
            raise AssertionError('the instrumentation strip would remove %r, which is content' % k)
    if not (set(_COUNT_KEYS) == set(_VERDICT_STATUSES) | set(_NO_VERDICT)):
        raise AssertionError('every status is either a verdict or not one; a third case has appeared')
