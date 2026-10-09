# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The stages `_check_shell_components` is assembled from, exercised on their own.

`_check_shell_components` was a 402-line def: the component inventory, the per-shell
measurement pass, the state ladder, the payload and the verdict all in one frame. Nothing
in it had ever been called in isolation, so the only way to ask "does a shell outside the
envelope come back a defect?" was to build a mesh that put one there. The 2026-10-09 split
gave each stage its own function in `shells_containment`, and these tests pin the two
pieces that carry the meaning — the state ladder (`select_shell_state`) and the roll-up
(`build_shell_report`) — plus the inventory that feeds them, on plain arrays and dicts.

The ladder tests use a `SimpleNamespace` rather than a `ShellMeasure` on purpose: they
assert what the ladder reads, so a field it stops reading must show up as a failure here.
No GPU, no services; numpy and scipy only.
"""

from __future__ import annotations

import numpy as np
import pytest
from types import SimpleNamespace
from zyg_workflows.geom.anthro.integrity import shells_containment as SC
from zyg_workflows.geom.anthro.integrity.shells import _STATE_MEANING


def measure(**kw):
    """A measured shell with the benign defaults the ladder reads, overridden by **kw."""
    base = {
        'ambig': np.zeros(8, bool),
        'crossing': 0,
        'n_in': 8,
        'n_out': 0,
        'out_env': 0,
        'sky': {'mean': 0.0, 'min': 0.0, 'max': 0.0},
        'consistent': True,
        'env_reason': None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


# ── select_shell_state: the ladder ────────────────────────────────────────────


def test_a_dirty_winding_number_beats_every_other_branch():
    """The winding number did not come back cleanly 0 or 1, so containment has no answer
    on this geometry — unverifiable, not benign, and decided before anything else."""
    state, why = SC.select_shell_state(measure(ambig=np.array([False, True]), crossing=None, n_out=5, n_in=5))
    assert state == 'indeterminate'
    assert why is None


def test_unmeasured_face_crossings_assert_nothing():
    """`crossing is None` means self_intersection was switched off. Calling a shell
    'enclosed' on evidence nobody gathered is the exact failure this file prevents."""
    state, why = SC.select_shell_state(measure(crossing=None))
    assert state == 'crossing_not_tested'
    assert why is None


def test_every_vertex_inside_is_enclosed_and_a_crossing_makes_it_a_defect():
    assert SC.select_shell_state(measure(n_in=8, n_out=0, crossing=0))[0] == 'enclosed'
    assert SC.select_shell_state(measure(n_in=8, n_out=0, crossing=3))[0] == 'enclosed_but_crossing'


def test_vertices_on_both_sides_without_a_crossing_is_contradictory():
    """Either the containment test or the intersection test is wrong, so it is a defect
    rather than a pass."""
    assert SC.select_shell_state(measure(n_in=4, n_out=4, crossing=0))[0] == 'straddles_without_crossing'
    assert SC.select_shell_state(measure(n_in=4, n_out=4, crossing=9))[0] == 'protrudes_through_body_surface'


def test_an_unavailable_envelope_is_unresolved_and_carries_the_hulls_own_reason():
    """The envelope test is one of the only two position measurements, so without it the
    verdict is UNDECIDED — and the hull's own explanation is preferred to the generic one."""
    state, why = SC.select_shell_state(measure(n_in=0, n_out=8, out_env=None, env_reason='qhull fell over'))
    assert state == 'outside_body_position_unresolved'
    assert why == 'qhull fell over'
    _, generic = SC.select_shell_state(measure(n_in=0, n_out=8, out_env=None, env_reason=None))
    assert 'the convex envelope was not available' in generic


def test_leaving_the_envelope_is_a_defect_that_a_disagreeing_sample_cannot_clear():
    """The envelope test is exact and the escape fraction is a ray sample, so `consistent
    is False` is recorded but never promotes the call back to benign."""
    for consistent in (True, False, None):
        state, why = SC.select_shell_state(
            measure(n_in=0, n_out=8, out_env=3, consistent=consistent, sky={'max': 0.0, 'min': 0.0, 'mean': 0.0})
        )
        assert state == 'detached_in_open_air'
        assert why is None


def test_a_sealed_pocket_needs_zero_escape_and_an_open_one_is_a_separate_state():
    """An invagination is topologically exterior, so this is the correct state for a
    tongue, not a defect — and neither state is in the defect list."""
    sealed, _ = SC.select_shell_state(measure(n_in=0, n_out=8, out_env=0, sky={'max': 0.0}))
    opened, _ = SC.select_shell_state(measure(n_in=0, n_out=8, out_env=0, sky={'max': 0.008}))
    assert sealed == 'in_sealed_body_cavity'
    assert opened == 'in_open_body_cavity'
    assert sealed not in SC._DEFECT_STATES and opened not in SC._DEFECT_STATES


def test_inside_the_envelope_a_high_escape_fraction_downgrades_to_unresolved():
    """House policy: nothing that sees sky in most directions is in a pocket of the body,
    even when the envelope contains it. The sentence quotes both numbers."""
    state, why = SC.select_shell_state(measure(n_in=0, n_out=8, out_env=0, consistent=False, sky={'max': 0.731}))
    assert state == 'outside_body_position_unresolved'
    assert '0.731' in why
    assert 'neither verdict is' in why


def test_no_outside_probe_point_is_unresolved_too():
    state, why = SC.select_shell_state(measure(n_in=0, n_out=8, out_env=0, sky=None, consistent=None))
    assert state == 'outside_body_position_unresolved'
    assert why == 'no outside-of-solid probe point was available for the escape cross-check'


def test_every_state_the_ladder_can_return_has_a_meaning_and_a_defect_verdict():
    """`_STATE_MEANING[state]` is read unconditionally by the payload, so a state the
    ladder can reach but the table does not know is a KeyError in production."""
    reachable = {
        SC.select_shell_state(m)[0]
        for m in (
            measure(ambig=np.array([True])),
            measure(crossing=None),
            measure(),
            measure(crossing=2),
            measure(n_in=4, n_out=4, crossing=0),
            measure(n_in=4, n_out=4, crossing=1),
            measure(n_in=0, n_out=8, crossing=1),
            measure(n_in=0, n_out=8, out_env=None),
            measure(n_in=0, n_out=8, out_env=4),
            measure(n_in=0, n_out=8, sky=None, consistent=None),
            measure(n_in=0, n_out=8, consistent=False, sky={'max': 0.9}),
            measure(n_in=0, n_out=8, sky={'max': 0.0}),
            measure(n_in=0, n_out=8, sky={'max': 0.01}),
        )
    }
    assert len(reachable) == 10
    for state in reachable:
        assert _STATE_MEANING[state]


# ── containment_payload ───────────────────────────────────────────────────────


def full_measure():
    """A measured shell with every array the payload reads, well outside the envelope."""
    return SC.ShellMeasure(
        component=1,
        pts=np.zeros((4, 3)),
        pts_all=np.zeros((9, 3)),
        w=np.array([0.0, 0.0, 0.0, 0.0]),
        inside=np.zeros(4, bool),
        ambig=np.zeros(4, bool),
        wp=np.array([0.0, 0.0]),
        agree=2,
        n_probes=2,
        crossing=0,
        marg=np.array([0.001, 0.004, -0.002]),
        out_env=2,
        sky={'mean': 0.1, 'min': 0.0, 'max': 0.2},
        sky_env={'mean': 0.1, 'min': 0.1, 'max': 0.2},
        far_m=0.12,
        near_m=0.03,
        n_in=0,
        n_out=4,
        consistent=False,
        env_reason=None,
    )


def test_the_payload_reports_the_subsample_and_the_margins_in_millimetres():
    out = SC.containment_payload(full_measure(), 'detached_in_open_air', None)
    assert out['vertices_probed'] == 4
    assert out['subsampled'] is True
    assert out['envelope_vertices_tested'] == 3
    assert out['envelope_margin_max_mm'] == pytest.approx(4.0)
    assert out['envelope_margin_min_mm'] == pytest.approx(-2.0)
    assert out['ray_parity_probes_agreeing'] == '2/2'
    assert out['state'] == 'detached_in_open_air'
    assert out['state_meaning'] == _STATE_MEANING['detached_in_open_air']
    assert out['defect'] is True


def test_a_prediction_that_cannot_fail_and_did_is_said_out_loud():
    """Outside the envelope the escape bound is DERIVED, so a False there means the ray
    sample and the hull disagree. The defect call stands; the disagreement is reported."""
    out = SC.containment_payload(full_measure(), 'detached_in_open_air', None)
    assert '2 vertices lie outside the convex envelope' in out['envelope_escape_disagreement']
    assert 'one of them is unreliable on this geometry' in out['envelope_escape_disagreement']


def test_no_disagreement_line_when_the_sample_agrees_and_none_when_inside():
    agreeing = SC.containment_payload(full_measure(), 'detached_in_open_air', None)
    assert 'envelope_escape_disagreement' in agreeing
    m = full_measure()
    m.consistent = True
    assert 'envelope_escape_disagreement' not in SC.containment_payload(m, 'detached_in_open_air', None)
    m2 = full_measure()
    m2.out_env = 0
    assert 'envelope_escape_disagreement' not in SC.containment_payload(m2, 'in_open_body_cavity', None)


def test_unresolved_because_is_only_present_when_there_is_one():
    m = full_measure()
    assert 'unresolved_because' not in SC.containment_payload(m, 'enclosed', None)
    assert SC.containment_payload(m, 'outside_body_position_unresolved', 'because')['unresolved_because'] == 'because'


def test_a_missing_envelope_reports_none_not_zero():
    """None means the envelope was unavailable, which is not the same answer as zero."""
    m = full_measure()
    m.marg = None
    m.out_env = None
    out = SC.containment_payload(m, 'outside_body_position_unresolved', 'no hull')
    assert out['envelope_vertices_tested'] is None
    assert out['envelope_margin_max_mm'] is None
    assert out['envelope_vertices_outside'] is None


# ── build_shell_inventory ─────────────────────────────────────────────────────


def box(cx, cy, cz, s):
    """An axis-aligned cube of side `s` centred on (cx, cy, cz), as quads."""
    h = s / 2.0
    v = np.array(
        [
            [cx - h, cy - h, cz - h],
            [cx + h, cy - h, cz - h],
            [cx + h, cy + h, cz - h],
            [cx - h, cy + h, cz - h],
            [cx - h, cy - h, cz + h],
            [cx + h, cy - h, cz + h],
            [cx + h, cy + h, cz + h],
            [cx - h, cy + h, cz + h],
        ],
        np.float64,
    )
    f = np.array([[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]], np.int64)
    return v, f


def scene(parts, loose_points=()):
    """`parts` cubes plus `loose_points` face-less vertices, one component each."""
    vs, fs, labels = [], [], []
    off = 0
    for i, (c, s) in enumerate(parts):
        v, f = box(c[0], c[1], c[2], s)
        vs.append(v)
        fs.append(f + off)
        labels.extend([i] * len(v))
        off += len(v)
    for j, p in enumerate(loose_points):
        vs.append(np.array([p], np.float64))
        labels.append(len(parts) + j)
    return np.vstack(vs), np.vstack(fs), np.array(labels, np.int64)


def test_the_body_is_the_biggest_bounding_box_and_the_rest_are_shells():
    v, faces, labels = scene([((0, 0, 1.0), 0.4), ((0, 0, 1.0), 2.0)])
    sh = SC.build_shell_inventory(v, faces, labels, 2, [])
    assert sh.body == 1
    assert [e['component'] for e in sh.inv] == [1, 0]
    assert [e['role'] for e in sh.inv] == ['body', 'shell']
    assert sh.shells == [sh.inv[1]]
    assert sh.ambiguous is False
    assert sh.ratio == pytest.approx(5.0)
    assert sh.stature_m == pytest.approx(2.0)


def test_two_comparable_components_refuse_to_name_a_body():
    """Below BODY_DOMINANCE_MIN_RATIO the check refuses to guess which shell is the
    person, which is what suppresses containment entirely."""
    v, faces, labels = scene([((0, 0, 1.0), 2.0), ((4.0, 0, 1.0), 1.95)])
    sh = SC.build_shell_inventory(v, faces, labels, 2, [])
    assert sh.ambiguous is True
    assert sh.ratio < SC.BODY_DOMINANCE_MIN_RATIO


def test_an_unreferenced_vertex_is_loose_and_never_a_shell():
    """A point is not a surface, so every number containment would produce for it is
    noise — it must not be dressed up as a shell."""
    v, faces, labels = scene([((0, 0, 1.0), 2.0), ((0, 0, 1.0), 0.3)], loose_points=[(9.0, 9.0, 9.0)])
    sh = SC.build_shell_inventory(v, faces, labels, 3, [])
    assert sh.loose == [2]
    assert [e['component'] for e in sh.shells] == [1]
    assert next(e for e in sh.inv if e['component'] == 2)['role'] == 'loose_vertices'
    assert sh.ratio == pytest.approx(float(sh.diag[sh.body]) / float(sh.diag[1]))


def test_the_inventory_records_position_as_a_fraction_of_stature():
    v, faces, labels = scene([((0, 0, 1.0), 2.0), ((0, 0, 1.8), 0.2)])
    sh = SC.build_shell_inventory(v, faces, labels, 2, [])
    shell = sh.shells[0]
    assert shell['vertices'] == 8
    assert shell['faces'] == 6
    assert shell['z_frac_min'] == pytest.approx(0.85)
    assert shell['z_frac_max'] == pytest.approx(0.95)
    assert shell['centroid_m'] == [0.0, 0.0, 1.8]
    assert shell['name_confidence'] in ('high', 'none')


def test_the_euler_records_are_joined_on_the_component_number():
    v, faces, labels = scene([((0, 0, 1.0), 2.0), ((0, 0, 1.0), 0.3)])
    euler = [{'component': 1, 'euler_chi': 2, 'closed': True, 'genus': 0}]
    sh = SC.build_shell_inventory(v, faces, labels, 2, euler)
    assert sh.shells[0]['euler_chi'] == 2
    assert sh.shells[0]['genus'] == 0
    assert next(e for e in sh.inv if e['role'] == 'body')['euler_chi'] is None


# ── build_shell_report ────────────────────────────────────────────────────────


def report(states, containment=True, probe_agree=4, probe_total=4, env=None):
    """A roll-up over one synthetic shell per state in `states`."""
    inv = [{'component': 0, 'role': 'body'}]
    for i, state in enumerate(states):
        inv.append(
            {
                'component': i + 1,
                'role': 'shell',
                'containment': {'state': state, 'state_meaning': _STATE_MEANING[state]},
            }
        )
    sh = SC.ShellInventory(
        sizes=np.array([100] + [8] * len(states)),
        fsizes=np.array([6] * (len(states) + 1)),
        vsort=np.arange(0),
        vstart=np.zeros(1, int),
        vend=np.zeros(1, int),
        diag=np.array([2.0] + [0.3] * len(states)),
        body=0,
        loose=[],
        second=0.3,
        ratio=6.67,
        ambiguous=False,
        stature_m=1.8,
        stature_scale=1.8,
        euler_by_component={0: {'euler_chi': 2, 'closed': True, 'genus': 0}},
        inv=inv,
        shells=inv[1:],
    )
    return SC.build_shell_report(sh, len(states) + 1, containment, probe_agree, probe_total, env)


def test_all_enclosed_shells_with_full_parity_agreement_pass():
    out = report(['enclosed', 'enclosed'])
    assert out['pass'] is True
    assert out['detail']['all_shells_enclosed'] is True
    assert out['detail']['asserted'] is True
    assert out['detail']['ray_parity_agreement'] == '4/4 probes'
    assert 'nothing_asserted' not in out['detail']


def test_a_pocket_is_not_enclosed_and_still_passes():
    """An INVAGINATION IS OUTSIDE: a tongue in the mouth scores winding 0 everywhere, so
    `all_shells_enclosed` is False on a perfectly good cage and is reported, not gated."""
    out = report(['in_sealed_body_cavity', 'in_open_body_cavity'])
    assert out['detail']['all_shells_enclosed'] is False
    assert out['pass'] is True
    assert out['detail']['asserted'] is True


def test_a_defect_state_fails_and_is_listed():
    out = report(['enclosed', 'detached_in_open_air'])
    assert out['pass'] is False
    assert out['detail']['shells_defective'] == [2]
    assert out['detail']['shells_protruding'] == []


def test_never_tested_is_none_not_false_and_fails_the_check():
    """'not enclosed' and 'not looked at' are different answers and only one of them is a
    measurement."""
    out = report(['enclosed', 'not_tested'])
    assert out['detail']['all_shells_enclosed'] is None
    assert out['detail']['shells_not_tested'] == [2]
    assert out['detail']['asserted'] is False
    assert out['pass'] is False
    assert 'MAX_SHELLS_ANALYSED' in out['detail']['containment_cap']


def test_switching_self_intersection_off_asserts_nothing_and_fails():
    out = report(['crossing_not_tested'])
    assert out['detail']['nothing_asserted'] is True
    assert 'face crossings are unmeasured' in out['detail']['note_containment']
    assert out['pass'] is False


def test_the_callers_opt_out_says_so_out_loud_and_still_passes():
    """`containment=False` is an explicit opt-out: a question that was never asked is not
    a failure, but the payload must say nothing was asserted."""
    out = report(['not_tested'], containment=False)
    assert out['detail']['containment_tested'] is False
    assert out['detail']['nothing_asserted'] is True
    assert 'containment=False' in out['detail']['note_containment']
    assert out['detail']['asserted'] is False
    assert out['pass'] is True


def test_a_parity_disagreement_alone_fails_the_check():
    """Two independent methods agreeing is evidence; one of them asserting is not."""
    assert report(['enclosed'], probe_agree=3, probe_total=4)['pass'] is False
    assert report(['enclosed'], probe_agree=0, probe_total=0)['pass'] is True


def test_the_envelope_is_reported_without_its_half_spaces():
    """`A` and `b` are numpy arrays the payload must not try to serialise."""
    env = {
        'available': True,
        'verified': True,
        'facets': 42,
        'body_vertices_max_margin_m': 1e-9,
        'reason': None,
        'method': 'qhull',
        'A': np.zeros((2, 3)),
        'b': np.zeros(2),
    }
    out = report(['enclosed'], env=env)
    assert set(out['detail']['convex_envelope']) == {
        'available',
        'verified',
        'facets',
        'body_vertices_max_margin_m',
        'reason',
        'method',
    }
    assert report(['enclosed'], env=None)['detail']['convex_envelope'] is None
