# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage tests for zyg_workflows.geom.anthro.hand_correction.

The solver talks to geom.form.hands through the module's own lazy `_hands()` accessor, so
every test that would otherwise build a real skeleton replaces that accessor with a small
analytic stand-in: bone length = base * local-Y scale. That model is linear, so the
fixed-point iteration converges in two passes and the expected numbers are closed form.
"""

import builtins
import io
import json
import os
import sys
import types

import numpy as np
import pytest

from zyg_workflows.geom.anthro import hand_correction as MOD

R1 = 0.6
R2 = 0.5
BASE_M = {'p': 0.030, 'm': 0.020, 'd': 0.015}


@pytest.fixture(autouse=True)
def _clear_solve_cache():
    MOD._SOLVE_CACHE.clear()
    yield
    MOD._SOLVE_CACHE.clear()


class FakeHands:
    """Analytic stand-in for geom.form.hands.

    `skeleton` returns the proposed scales plus the number of the call that produced them,
    and `_blen` reads the length straight back out of it. `drift` injects a multiplier on
    one numbered call so the module's own consistency checks can be reached; `frozen`
    makes the rig ignore the scales entirely, which is what non-convergence looks like.
    """

    def __init__(self, drift=None, frozen=False):
        self.DIGIT_BONES = {d: ('mc_%s' % d, 'p_%s' % d, 'm_%s' % d, 'd_%s' % d) for d in MOD.CORRECTED_DIGITS}
        self.drift = dict(drift or {})
        self.frozen = frozen
        self.calls = 0

    def _ratio_band(self, digit, which):
        return {'centre': R1 if which == 'mid_over_prox' else R2}

    def skeleton(self, phenotype, local_changes=None, bone_scales=None, apply_hand_correction=True):
        assert apply_hand_correction is False
        self.calls += 1
        return {'scales': dict(bone_scales or {}), 'call': self.calls}

    def _blen(self, sk, bone, side):
        base = BASE_M[bone.split('_')[0]]
        if self.frozen:
            return base
        length = base * float(sk['scales'].get(bone, (1.0, 1.0, 1.0))[1])
        factor = self.drift.get(sk['call'])
        return length if factor is None else length * factor


def _use(monkeypatch, fake):
    monkeypatch.setattr(MOD, '_hands', lambda: fake)
    return fake


def _want_mm():
    ray = 1000.0 * (BASE_M['p'] + BASE_M['m'] + BASE_M['d'])
    P = ray / (1.0 + R1 + R1 * R2)
    return [P, R1 * P, R1 * R2 * P]


# ---------------------------------------------------------------- enabled / _hands


@pytest.mark.parametrize(
    ('value', 'want'),
    [
        (None, True),
        ('1', True),
        ('yes', True),
        ('ON', True),
        ('', True),
        ('0', False),
        ('false', False),
        ('  No  ', False),
        ('OFF', False),
    ],
)
def test_enabled_reads_the_env_flag(monkeypatch, value, want):
    if value is None:
        monkeypatch.delenv(MOD.ENV_FLAG, raising=False)
    else:
        monkeypatch.setenv(MOD.ENV_FLAG, value)
    assert MOD.enabled() is want


def test_hands_accessor_returns_the_real_module():
    H = MOD._hands()
    assert 'index' in H.DIGIT_BONES


# ---------------------------------------------------------------- targets / _lengths


def test_targets_reads_the_band_centres(monkeypatch):
    _use(monkeypatch, FakeHands())
    assert MOD.targets('index') == (R1, R2)


def test_targets_refuses_a_digit_with_no_published_band():
    with pytest.raises(RuntimeError, match='no published band'):
        MOD.targets('thumb')


def test_targets_on_the_real_bands_is_the_two_series_midpoint():
    r1, r2 = MOD.targets('index')
    assert 0.0 < r1 < 1.5 and 0.0 < r2 < 1.5


def test_lengths_are_millimetres_of_the_three_phalanges(monkeypatch):
    fake = _use(monkeypatch, FakeHands())
    sk = fake.skeleton({}, None, None, apply_hand_correction=False)
    assert MOD._lengths(sk, 'index', 'L') == pytest.approx([30.0, 20.0, 15.0])


# ---------------------------------------------------------------- merge


@pytest.mark.parametrize(
    ('dicts', 'want'),
    [
        ((), {}),
        ((None, None), {}),
        (({'a': 2.0},), {'a': [2.0, 2.0, 2.0]}),
        (({'a': (1.0, 2.0, 3.0)},), {'a': [1.0, 2.0, 3.0]}),
        (({'a': [1.0, 2.0, 3.0]}, {'b': 1.5}), {'a': [1.0, 2.0, 3.0], 'b': [1.5, 1.5, 1.5]}),
        (({'a': [1.0, 2.0, 1.0]}, {'a': [1.0, 3.0, 1.0]}), {'a': [1.0, 6.0, 1.0]}),
        (({'a': 2}, {'a': 3}), {'a': [6.0, 6.0, 6.0]}),
    ],
)
def test_merge_composes_multiplicatively(dicts, want):
    assert MOD.merge(*dicts) == want


def test_merge_copies_rather_than_aliasing():
    src = {'a': [1.0, 2.0, 1.0]}
    out = MOD.merge(src)
    out['a'][1] = 99.0
    assert src['a'][1] == 2.0


# ---------------------------------------------------------------- solve


def test_solve_puts_both_ratios_on_the_band_centres(monkeypatch):
    fake = _use(monkeypatch, FakeHands())
    rec = MOD.solve({'gender': 0.0}, {'some-morph': 1.0}, side='L')

    assert rec['version'] == MOD.HAND_CORRECTION_VERSION
    assert rec['side_solved'] == 'L'
    assert rec['digits'] == list(MOD.CORRECTED_DIGITS)
    assert rec['iterations'] == 2
    assert rec['residual'] < MOD.SOLVE_TOL
    assert set(rec['scales']) == {'%s_%s' % (p, d) for d in MOD.CORRECTED_DIGITS for p in ('p', 'm', 'd')}
    for bone, s in rec['scales'].items():
        assert s[0] == 1.0 and s[2] == 1.0, bone
        assert s[1] > 0.0

    want = _want_mm()
    for d in MOD.CORRECTED_DIGITS:
        assert rec['targets'][d] == {'mid_over_prox': R1, 'dist_over_mid': R2}
        assert rec['before'][d]['mid_over_prox'] == pytest.approx(20.0 / 30.0)
        assert rec['before'][d]['dist_over_mid'] == pytest.approx(15.0 / 20.0)
        assert rec['before'][d]['ray_mm'] == pytest.approx(65.0)
        assert rec['after'][d]['mid_over_prox'] == pytest.approx(R1)
        assert rec['after'][d]['dist_over_mid'] == pytest.approx(R2)
        assert rec['after'][d]['proximal_mm'] == pytest.approx(want[0])
        assert rec['after'][d]['middle_mm'] == pytest.approx(want[1])
        assert rec['after'][d]['distal_mm'] == pytest.approx(want[2])
        assert rec['after'][d]['ray_mm'] == pytest.approx(rec['before'][d]['ray_mm'])
        assert abs(rec['ray_length_change_mm'][d]) <= 1e-6
    assert 'Buryanov' in rec['target_source']
    assert 'metacarpal' in rec['not_corrected'] and 'thumb' in rec['not_corrected']
    assert fake.calls == 4


def test_solve_is_cached_per_argument_tuple(monkeypatch):
    fake = _use(monkeypatch, FakeHands())
    first = MOD.solve({'gender': 1.0}, None, 'R', {'p_index': 1.1})
    calls = fake.calls
    second = MOD.solve({'gender': 1.0}, None, 'R', {'p_index': 1.1})
    assert second is first
    assert fake.calls == calls
    MOD.solve({'gender': 1.0}, None, 'L', {'p_index': 1.1})
    assert fake.calls > calls


def test_solve_refuses_a_non_positive_bone(monkeypatch):
    _use(monkeypatch, FakeHands(drift={2: 0.0}))
    with pytest.raises(RuntimeError, match='non-positive length'):
        MOD.solve({}, None)


def test_solve_refuses_to_issue_scales_that_do_not_converge(monkeypatch):
    _use(monkeypatch, FakeHands(frozen=True))
    with pytest.raises(RuntimeError, match='did not converge'):
        MOD.solve({}, None)


def test_solve_refuses_a_correction_that_moved_the_ray(monkeypatch):
    _use(monkeypatch, FakeHands(drift={4: 1.001}))
    with pytest.raises(RuntimeError, match='moved a finger ray'):
        MOD.solve({}, None)


# ---------------------------------------------------------------- scales_from_params


@pytest.mark.parametrize(
    'params',
    [
        None,
        {},
        {'hand_correction': None},
        {'hand_correction': {}},
        {'hand_correction': {'applied': False, 'scales': {'p_index': [1.0, 1.2, 1.0]}}},
    ],
)
def test_scales_from_params_is_none_without_an_applied_record(params):
    assert MOD.scales_from_params(params) is None


def test_scales_from_params_returns_the_recorded_scales():
    rec = {'applied': True, 'scales': {'p_index': [1.0, 1.2, 1.0]}}
    out = MOD.scales_from_params({'hand_correction': rec})
    assert out == {'p_index': [1.0, 1.2, 1.0]}
    out['p_index'][1] = 9.0
    assert rec['scales']['p_index'][1] == 1.2


def test_scales_from_params_tolerates_an_applied_record_with_no_scales():
    assert MOD.scales_from_params({'hand_correction': {'applied': True}}) == {}


# ---------------------------------------------------------------- effective_scales


@pytest.mark.parametrize('bone_scales', [None, {'p_index': [1.0, 1.3, 1.0]}])
def test_effective_scales_passes_through_when_switched_off(monkeypatch, bone_scales):
    monkeypatch.setenv(MOD.ENV_FLAG, '0')
    scales, rec = MOD.effective_scales({}, None, bone_scales)
    assert scales == bone_scales
    assert rec['applied'] is False
    assert rec['version'] == MOD.HAND_CORRECTION_VERSION
    assert MOD.ENV_FLAG in rec['why']


@pytest.mark.parametrize('bone_scales', [None, {'p_index': [1.0, 1.3, 1.0]}])
def test_effective_scales_applies_nothing_to_a_pre_correction_body(monkeypatch, bone_scales):
    monkeypatch.delenv(MOD.ENV_FLAG, raising=False)
    scales, rec = MOD.effective_scales({}, None, bone_scales, params={'seed': 7})
    assert scales == bone_scales
    assert rec['applied'] is False
    assert rec['version'] is None
    assert 'issued before the phalanx correction' in rec['why']


def test_effective_scales_reuses_a_recorded_correction(monkeypatch):
    monkeypatch.delenv(MOD.ENV_FLAG, raising=False)
    recorded = {
        'applied': True,
        'version': MOD.HAND_CORRECTION_VERSION,
        'scales': {'p_index': [1.0, 0.5, 1.0]},
    }
    scales, rec = MOD.effective_scales({}, None, {'p_index': [1.0, 4.0, 1.0]}, params={'hand_correction': recorded})
    assert scales == {'p_index': [1.0, 2.0, 1.0]}
    assert rec == recorded
    assert rec is not recorded


def test_effective_scales_solves_for_a_fresh_build(monkeypatch):
    monkeypatch.delenv(MOD.ENV_FLAG, raising=False)
    _use(monkeypatch, FakeHands())
    scales, rec = MOD.effective_scales({'gender': 0.0})
    assert rec['applied'] is True
    assert rec['iterations'] == 2
    want = _want_mm()
    assert scales['p_index'][1] == pytest.approx(want[0] / 30.0)
    assert scales['p_index'][0] == 1.0 and scales['p_index'][2] == 1.0


def test_effective_scales_composes_the_request_with_the_solved_correction(monkeypatch):
    monkeypatch.delenv(MOD.ENV_FLAG, raising=False)
    _use(monkeypatch, FakeHands())
    asked = {'p_index': [1.0, 2.0, 1.0]}
    scales, rec = MOD.effective_scales({'gender': 0.0}, None, asked)
    solved = rec['scales']['p_index'][1]
    assert scales['p_index'][1] == pytest.approx(2.0 * solved)


# ---------------------------------------------------------------- _hand_length_sd_mm


def _fake_reference(sex='female', entry=None):
    pooled = {} if entry is None else {'hand_length_over_stature': entry}
    return {'stats': {sex: {'pooled': pooled}}}


def _install_reference(monkeypatch, ref, stature_m=1.70):
    monkeypatch.setattr(os.path, 'exists', lambda p: True)
    monkeypatch.setattr(builtins, 'open', lambda *a, **k: io.StringIO(''))
    monkeypatch.setattr(json, 'load', lambda fh: ref)
    fake_ms = types.SimpleNamespace(
        _build_mesh=lambda ph, lc, bs: (np.zeros((3, 3)), None, None),
        _measure=lambda v: {'height_m': stature_m},
    )
    import zyg_workflows.geom as G

    monkeypatch.setitem(sys.modules, 'zyg_workflows.geom.mesh_skeletons', fake_ms)
    monkeypatch.setattr(G, 'mesh_skeletons', fake_ms, raising=False)


def test_hand_length_sd_is_none_without_a_reference_pack():
    assert MOD._hand_length_sd_mm({'gender': 0.0}) is None


def test_hand_length_sd_scales_the_ratio_sd_by_this_bodys_stature(monkeypatch):
    _install_reference(monkeypatch, _fake_reference('female', {'sd': 0.0005}))
    assert MOD._hand_length_sd_mm({'gender': 1.0}) == pytest.approx(0.0005 * 1700.0)


def test_hand_length_sd_picks_the_male_pack_below_the_gender_midpoint(monkeypatch):
    _install_reference(monkeypatch, _fake_reference('male', {'sd': 0.001}), stature_m=1.80)
    assert MOD._hand_length_sd_mm(None) == pytest.approx(0.001 * 1800.0)


@pytest.mark.parametrize('entry', [None, {}, {'sd': 0.0}])
def test_hand_length_sd_is_none_when_the_pack_has_no_sd(monkeypatch, entry):
    _install_reference(monkeypatch, _fake_reference('female', entry))
    assert MOD._hand_length_sd_mm({'gender': 1.0}) is None


def test_hand_length_sd_swallows_a_broken_pack(monkeypatch):
    _install_reference(monkeypatch, {'stats': 'not-a-mapping'})
    assert MOD._hand_length_sd_mm({'gender': 1.0}) is None


# ---------------------------------------------------------------- _anisotropy


def _ring(xr, zr, n=16):
    a = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    return np.column_stack([xr * np.cos(a), np.linspace(0.1, 0.9, n), zr * np.sin(a)])


def _sk_for(head, tail, nm='p_index.L'):
    return {'index': {nm: 0}, 'head': [np.asarray(head, float)], 'tail': [np.asarray(tail, float)]}


def test_anisotropy_measures_the_cross_section_axis_ratio():
    v = _ring(2.0, 1.0)
    w = {'p_index.L': np.ones(len(v))}
    got = MOD._anisotropy(v, _sk_for([0, 0, 0], [0, 1, 0]), 'p_index', w)
    assert got == pytest.approx(2.0, rel=1e-6)


def test_anisotropy_of_a_circular_section_is_one():
    v = _ring(1.0, 1.0)
    w = {'p_index.L': np.ones(len(v))}
    got = MOD._anisotropy(v, _sk_for([0, 0, 0], [0, 1, 0]), 'p_index', w)
    assert got == pytest.approx(1.0, rel=1e-6)


def test_anisotropy_is_none_for_a_bone_with_no_weights():
    v = _ring(2.0, 1.0)
    assert MOD._anisotropy(v, _sk_for([0, 0, 0], [0, 1, 0]), 'p_index', {}) is None


def test_anisotropy_is_none_with_too_few_bound_vertices():
    v = _ring(2.0, 1.0)
    w = np.zeros(len(v))
    w[:3] = 1.0
    got = MOD._anisotropy(v, _sk_for([0, 0, 0], [0, 1, 0]), 'p_index', {'p_index.L': w})
    assert got is None


def test_anisotropy_is_none_for_a_zero_length_bone():
    v = _ring(2.0, 1.0)
    w = {'p_index.L': np.ones(len(v))}
    got = MOD._anisotropy(v, _sk_for([1, 2, 3], [1, 2, 3]), 'p_index', w)
    assert got is None


def test_anisotropy_is_none_for_a_degenerate_flat_section():
    n = 12
    v = np.column_stack([np.linspace(-1.0, 1.0, n), np.linspace(0.1, 0.9, n), np.zeros(n)])
    w = {'p_index.R': np.ones(n)}
    got = MOD._anisotropy(v, _sk_for([0, 0, 0], [0, 1, 0], 'p_index.R'), 'p_index', w, side='R')
    assert got is None


# ---------------------------------------------------------------- comparison helpers


@pytest.mark.parametrize(
    ('a', 'b', 'figs', 'want'),
    [
        (1.0, 1.0, 12, True),
        (0.0, 0.0, 12, True),
        (1.0, 1.0 + 1e-15, 12, True),
        (1.0, 1.001, 12, False),
        (1.0, 1.001, 2, True),
        (1.0, 1.0001, 3, True),
        (-2.0, -2.0 - 1e-14, 12, True),
    ],
)
def test_close_sigfigs(a, b, figs, want):
    assert MOD._close_sigfigs(a, b, figs) is want


@pytest.mark.parametrize(
    ('a', 'b', 'want'),
    [
        (None, None, True),
        (None, {}, True),
        ({'x': [1.0, 2.0, 1.0]}, {'x': [1.0, 2.0, 1.0]}, True),
        ({'x': [1.0, 2.0, 1.0]}, {'x': [1.0, 2.0, 1.0 + 1e-16]}, True),
        ({'x': [1.0, 2.0, 1.0]}, {'x': [1.0, 2.5, 1.0]}, False),
        ({'x': [1.0, 2.0, 1.0]}, {'y': [1.0, 2.0, 1.0]}, False),
        ({'x': [1.0, 2.0, 1.0]}, {}, False),
    ],
)
def test_scales_equal(a, b, want):
    assert MOD._scales_equal(a, b) is want


def test_gate_constants_are_the_documented_ones():
    assert MOD.GATE_Z_CORRECTED_MAX == 1e-9
    assert MOD.GATE_Z_BEFORE_SIGFIGS == 12
    assert MOD.SOLVE_MAX_ITER == 32
    assert MOD.SOLVE_TOL == 1e-10
    assert MOD.CORRECTED_DIGITS == ('index', 'middle', 'ring', 'little')
