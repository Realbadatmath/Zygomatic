# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The six regional record builders `anchors._build_features` is now made of.

Every builder reads the same small surface of the anchor context — `S`, `z0`,
`v`, `shell`, `fz()`, `bone()`, `sex()` — so each one can be exercised on a stub
body without anny, a rig file or a GPU. What is checked is what a reader of the
relief report would check: the record names and their order, the claim each
record makes about itself ('bone' means a rig bone put it there), and the
anatomical relations the prose asserts.
"""

import numpy as np
import pytest

from zyg_workflows.geom.relief import anchors as AN
from zyg_workflows.geom.relief import anchors_features as AF

# A 1.80 m body, as the builders see one. Only the bones the six builders name are
# here; `bone()` raises on anything else, which is the real _Ctx's behaviour too.
STATURE = 1.80
BONES = {
    'clavicle.L': (np.array([0.02, -0.06, 1.46]), np.array([0.17, -0.03, 1.47])),
    'clavicle.R': (np.array([-0.02, -0.06, 1.46]), np.array([-0.17, -0.03, 1.47])),
    'upperarm02.L': (np.array([0.20, 0.0, 1.30]), np.array([0.24, 0.01, 1.12])),
    'lowerarm01.L': (np.array([0.25, 0.01, 1.10]), np.array([0.29, 0.0, 0.95])),
    'lowerarm02.L': (np.array([0.29, 0.0, 0.95]), np.array([0.33, -0.01, 0.84])),
    'metacarpal1.L': (np.array([0.33, -0.03, 0.82]), np.array([0.35, -0.05, 0.76])),
    'metacarpal4.L': (np.array([0.37, -0.01, 0.82]), np.array([0.39, -0.01, 0.74])),
    'pelvis.L': (np.array([0.09, 0.01, 0.95]), np.array([0.09, 0.01, 0.90])),
    'lowerleg01.L': (np.array([0.10, 0.0, 0.50]), np.array([0.10, 0.0, 0.12])),
    'foot.L': (np.array([0.10, 0.0, 0.075]), np.array([0.10, -0.06, 0.02])),
    'spine01': (np.array([0.0, 0.02, 1.20]), np.array([0.0, 0.03, 1.45])),
    'head': (np.array([0.0, 0.02, 1.58]), np.array([0.0, 0.01, 1.74])),
}


class StubCtx:
    """The anchor context, with a vertex cloud instead of a cage.

    `with_surface=False` leaves the shell empty, which is how the iliac-crest
    azimuth sweep comes back with nothing — the case `pelvis_records` must answer
    with no records at all rather than with a half-built pelvis.
    """

    def __init__(self, with_surface=True, sex='male'):
        if with_surface:
            # a vertical elliptical shell, dense enough for the crest sweep's
            # 0.012-of-stature height band and 0.030 sideways window to find a hit
            phi = np.linspace(0.0, 2.0 * np.pi, 72, endpoint=False)
            zs = np.linspace(0.0, STATURE, 240)
            self.v = np.array(
                [[0.16 * np.sin(p), 0.11 * np.cos(p), z] for z in zs for p in phi],
                np.float64,
            )
        else:
            self.v = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, STATURE]], np.float64)
        self.shell = np.ones(len(self.v), bool) if with_surface else np.zeros(len(self.v), bool)
        self.S = STATURE
        self.z0 = 0.0
        self._sex = sex

    def fz(self):
        return (self.v[:, 2] - self.z0) / self.S

    def bone(self, name):
        if name not in BONES:
            raise KeyError('bone %r is not on this rig' % name)
        return BONES[name]

    def sex(self):
        return self._sex


@pytest.fixture
def ctx():
    return StubCtx()


def _by_name(records):
    return [r['name'] for r in records]


# ── clavicle_records ─────────────────────────────────────────────────────────
def test_the_four_clavicular_records_come_out_in_append_order(ctx):
    assert _by_name(AF.clavicle_records(ctx)) == [
        'clavicle_ridge',
        'infraclavicular_fossa',
        'jugular_notch',
        'supraclavicular_fossa',
    ]


def test_the_clavicle_crest_is_an_s_with_exactly_one_sign_change(ctx):
    """AFS p.10: medial two thirds convex anteriorly, lateral third concave. The
    record carries that count as a measured number, so it can be read back."""
    ridge = AF.clavicle_records(ctx)[0]
    assert ridge['claim'] == 'bone'
    assert ridge['extra']['ap_sign_changes'] == 1
    assert 0.08 < ridge['extra']['bone_length_frac_stature'] < 0.14


def test_the_constructed_clavicular_records_say_so_and_the_bone_one_does_not(ctx):
    claims = {r['name']: r['claim'] for r in AF.clavicle_records(ctx)}
    assert claims['clavicle_ridge'] == 'bone'
    assert claims['infraclavicular_fossa'] == 'constructed'
    assert claims['jugular_notch'] == 'constructed'
    assert claims['supraclavicular_fossa'] == 'constructed'


def test_the_jugular_notch_is_a_single_midline_point(ctx):
    notch = {r['name']: r for r in AF.clavicle_records(ctx)}['jugular_notch']
    assert notch['op'] == 'point' and notch['midline'] is True
    assert notch['points'].shape == (1, 3)
    assert notch['points'][0][0] == 0.0


def test_the_supraclavicular_fossa_sits_above_the_crest_and_the_infraclavicular_below(ctx):
    recs = {r['name']: r for r in AF.clavicle_records(ctx)}
    crest_z = recs['clavicle_ridge']['points'][:, 2].mean()
    assert recs['supraclavicular_fossa']['points'][:, 2].mean() > crest_z
    assert recs['infraclavicular_fossa']['points'][:, 2].mean() < crest_z


# ── acromion_records ─────────────────────────────────────────────────────────
def test_the_acromion_is_the_clavicle_tail_nudged_superolaterally(ctx):
    (acr,) = AF.acromion_records(ctx)
    assert acr['name'] == 'acromion' and acr['claim'] == 'bone' and acr['op'] == 'point'
    tail = BONES['clavicle.L'][1]
    assert acr['points'][0][0] > tail[0]  # further lateral
    assert acr['points'][0][2] > tail[2]  # and higher
    assert acr['probes'] == ('acromion',)


# ── ankle_and_shank_records ──────────────────────────────────────────────────
def test_the_four_shank_records_come_out_in_append_order(ctx):
    assert _by_name(AF.ankle_and_shank_records(ctx)) == [
        'malleolus_med',
        'malleolus_lat',
        'tibial_facet',
        'fibula_control',
    ]


def test_the_medial_malleolus_apex_is_above_the_lateral_one(ctx):
    recs = {r['name']: r for r in AF.ankle_and_shank_records(ctx)}
    assert recs['malleolus_med']['points'][0][2] > recs['malleolus_lat']['points'][0][2]
    assert list(recs['malleolus_med']['aspect']) == [-1.0, 0.0, 0.0]
    assert list(recs['malleolus_lat']['aspect']) == [+1.0, 0.0, 0.0]


def test_the_tibial_facet_is_a_facet_and_the_fibula_a_zero_amplitude_control(ctx):
    recs = {r['name']: r for r in AF.ankle_and_shank_records(ctx)}
    assert recs['tibial_facet']['op'] == 'facet' and recs['tibial_facet']['amp_frac'] == 0.0
    assert recs['fibula_control']['op'] == 'control' and recs['fibula_control']['amp_frac'] == 0.0
    assert recs['fibula_control']['probes'] == ()
    # the control runs the SAME stations on the opposite aspect
    assert np.allclose(recs['fibula_control']['points'], recs['tibial_facet']['points'])
    assert np.allclose(recs['fibula_control']['aspect'], np.array([+1.0, 0.0, 0.0]))


# ── pelvis_records ───────────────────────────────────────────────────────────
def test_the_three_pelvic_records_come_out_in_append_order(ctx):
    assert _by_name(AF.pelvis_records(ctx)) == ['asis', 'iliac_crest', 'psis']


def test_every_pelvic_record_is_constructed_because_the_rig_has_no_pelvic_bone(ctx):
    assert {r['claim'] for r in AF.pelvis_records(ctx)} == {'constructed'}


def test_the_crest_height_is_the_ansur_fraction_and_the_sexes_differ(ctx):
    male = {r['name']: r for r in AF.pelvis_records(StubCtx(sex='male'))}['iliac_crest']
    female = {r['name']: r for r in AF.pelvis_records(StubCtx(sex='female'))}['iliac_crest']
    assert '0.6044 of stature, male)' in male['anchor']
    assert '0.6113 of stature, female)' in female['anchor']
    assert female['points'][:, 2].mean() > male['points'][:, 2].mean()


def test_the_psis_pair_sits_posterior_and_below_the_crest(ctx):
    recs = {r['name']: r for r in AF.pelvis_records(ctx)}
    psis, crest = recs['psis'], recs['iliac_crest']
    assert psis['points'][0][2] < crest['points'][:, 2].mean()
    assert psis['points'][0][1] > 0.0  # +y is posterior on this rig
    assert psis['points'][0][0] > 0.0  # the LEFT of the pair; mirroring makes the other


def test_an_empty_azimuth_sweep_yields_no_pelvic_records_at_all():
    """The old `if len(cpts):` guard, kept: a body whose shell the sweep cannot
    reach gets NO pelvis rather than a pelvis built on nothing."""
    assert AF.pelvis_records(StubCtx(with_surface=False)) == []


# ── neck_records ─────────────────────────────────────────────────────────────
def test_the_two_neck_records_are_both_on_the_midline(ctx):
    recs = AF.neck_records(ctx)
    assert _by_name(recs) == ['c7', 'nuchal_furrow']
    assert all(r['midline'] is True for r in recs)
    assert all(np.allclose(r['points'][:, 0], 0.0) for r in recs)


def test_the_nuchal_furrow_runs_from_the_occiput_down_to_the_c7_anchor(ctx):
    recs = {r['name']: r for r in AF.neck_records(ctx)}
    c7_z = recs['c7']['points'][0][2]
    nuch_z = recs['nuchal_furrow']['points'][:, 2]
    assert nuch_z.max() > c7_z  # starts above, at the occipital protuberance
    assert abs(nuch_z.min() - c7_z) < 0.05 * STATURE
    assert recs['c7']['claim'] == 'bone'  # spine01 tail is a real joint
    assert recs['nuchal_furrow']['claim'] == 'constructed'  # the rig has no occiput


# ── the orchestrator ─────────────────────────────────────────────────────────
def test_build_features_concatenates_the_six_builders_in_order(ctx, monkeypatch):
    """The split's contract: `_build_features` is the six builders' records, in
    the order they were always appended, and nothing else.

    `arm_records` is stood in for by a sentinel so its slot in the order is still
    checked: it cannot run on numpy 2.5 at all. `float(t)` on a shape-(1,) row of
    `np.linspace(...)[:, None]` raises TypeError, and it does so identically at
    HEAD — a pre-existing fault this split moved verbatim and did not cause.
    """
    monkeypatch.setattr(AF, 'arm_records', lambda c: [dict(name='ARM_SENTINEL')])
    assert _by_name(AN._build_features(ctx)) == (
        _by_name(AF.clavicle_records(ctx))
        + _by_name(AF.acromion_records(ctx))
        + ['ARM_SENTINEL']
        + _by_name(AF.ankle_and_shank_records(ctx))
        + _by_name(AF.pelvis_records(ctx))
        + _by_name(AF.neck_records(ctx))
    )
