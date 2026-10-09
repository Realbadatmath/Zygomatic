#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers extracted from ``measure.mesh.measure_mesh``.

``measure_mesh`` was a 337-line def: the height table, the cervicale substitution, the
length table, the girths, the extents, the volume block and the whole provenance meta
block were one frame sharing a dozen locals, so "is an unresolved landmark recorded
UNMEASURABLE with a reason?" could only be asked by measuring a real anny cage. The
2026-10 split moved each pass into ``measure/mesh_tables.py`` behind a ``MeshScan``;
every test below runs one pass on a hand-built scan. No Blender, no anny, no GPU — the
two passes that need real geometry (``_girth_site``, ``_extent_measure``, ``body_volume``)
are stubbed, which is exactly how their CONTRACT with the pass gets pinned.
"""

from __future__ import annotations

import numpy as np
import pytest

from zyg_workflows.geom.anthro import landmarks as LMK
from zyg_workflows.geom.anthro.measure import mesh_tables as MT
from zyg_workflows.geom.anthro.measure.constants import (
    ANNY_VENDOR_DENSITY_KG_M3,
    BODY_DENSITY_KG_M3,
)
from zyg_workflows.geom.anthro.measure.tables_extent import (
    BREADTH_SPEC,
    DEPTH_SPEC,
    HEIGHT_SPEC,
    LENGTH_SPEC,
    UNMEASURABLE,
)
from zyg_workflows.geom.anthro.measure.tables_girth import GIRTH_SITES

STATURE_M = 1.75


def _topo() -> dict:
    """A body-shell topology with two of its three triangles on the shell."""
    return {
        'tri': np.zeros((3, 3), dtype=int),
        'body_tris': np.array([True, True, False]),
        'shell_note': 'shell note',
        'arm_mask_provenance': {'ran': True},
    }


def _scan(**kw) -> MT.MeshScan:
    """A MeshScan over a two-vertex stand-in cage, overridden by the test's own fields."""
    fields = dict(
        v=np.array([[0.0, 0.0, 0.0], [0.1, 0.0, STATURE_M]]),
        faces=np.zeros((1, 4), dtype=int),
        zmin=0.0,
        H=STATURE_M,
        topo=_topo(),
        landmarks={},
        axes=None,
        coco=None,
        coco_src='test',
        pose={
            'pose': 'A-pose',
            'axis_convention': 'z up',
            'handedness': 'right',
            'ground_plane': 'z=0',
        },
        pose_ref=None,
        pose_ref_info={'built': False},
        step=0.005,
        ear_top=0.93,
        crotch_frac=0.47,
    )
    fields.update(kw)
    return MT.MeshScan(**fields)


def _landmark(height_m: float, point=(0.0, 0.0, 0.0), *, confidence: str = 'high') -> dict:
    """A resolved landmark record of the shape ``landmarks.resolve_landmarks`` returns."""
    return {
        'height_m': height_m,
        'frac_stature': height_m / STATURE_M,
        'anchor': 'ring deltoid',
        'confidence': confidence,
        'point': np.asarray(point, np.float64),
    }


# ── the height table ─────────────────────────────────────────────────────────


def test_stature_is_the_mesh_z_extent_and_the_whole_of_itself():
    M: dict = {}
    MT.height_rows(M, _scan())
    assert M['stature']['value_mm'] == pytest.approx(1750.0)
    assert M['stature']['frac_stature'] == 1.0
    assert M['stature']['landmark'] == 'vertex to standing surface'
    assert M['stature']['convention'] == 'mesh z-extent'
    assert M['stature']['provenance'] == 'MEASURED'


def test_a_resolved_landmark_height_is_millimetres_above_the_standing_surface():
    spec = next(s for s in HEIGHT_SPEC if s['name'] != 'stature')
    M: dict = {}
    MT.height_rows(M, _scan(landmarks={spec['landmark']: _landmark(1.45)}))
    row = M[spec['name']]
    assert row['value_mm'] == pytest.approx(1450.0)
    assert row['frac_stature'] == pytest.approx(1.45 / STATURE_M)
    assert row['landmark_confidence'] == 'high'
    assert spec['landmark'] in row['landmark']


def test_every_unresolved_height_landmark_is_unmeasurable_and_names_itself():
    M: dict = {}
    MT.height_rows(M, _scan(landmarks={}))
    for spec in HEIGHT_SPEC:
        if spec['name'] == 'stature':
            continue
        row = M[spec['name']]
        assert row['value_mm'] is None
        assert row['provenance'] == 'UNMEASURABLE'
        assert spec['landmark'] in row['reason']


def test_a_landmark_that_resolved_without_a_height_is_still_unmeasurable():
    spec = next(s for s in HEIGHT_SPEC if s['name'] != 'stature')
    M: dict = {}
    MT.height_rows(M, _scan(landmarks={spec['landmark']: {'height_m': None}}))
    assert M[spec['name']]['provenance'] == 'UNMEASURABLE'


# ── the cervicale HOUSE substitution ─────────────────────────────────────────


def test_cervicale_adds_the_ansur_offset_to_the_suprasternale_and_says_it_is_house():
    off = LMK.CERVICALE_OVER_SUPRASTERNALE['male']
    M = {'suprasternale_height': {'value_mm': 1400.0}}
    MT.cervicale_row(M, _scan(sex='male'))
    row = M['cervicale_height_house']
    assert row['provenance'] == 'HOUSE'
    assert row['value_mm'] == pytest.approx(1400.0 + off[0] * STATURE_M * 1000)
    assert row['offset_frac_stature'] == off[0]
    assert row['offset_sd_mm'] == pytest.approx(off[1] * STATURE_M * 1000)


def test_cervicale_without_a_declared_sex_is_unmeasurable_for_that_reason():
    M = {'suprasternale_height': {'value_mm': 1400.0}}
    MT.cervicale_row(M, _scan(sex=None))
    assert M['cervicale_height_house']['provenance'] == 'UNMEASURABLE'
    assert M['cervicale_height_house']['reason'] == 'sex not declared'


def test_cervicale_without_a_suprasternale_blames_the_suprasternale():
    M: dict = {}
    MT.cervicale_row(M, _scan(sex='female'))
    assert M['cervicale_height_house']['reason'] == 'suprasternale unresolved'


# ── the length table ─────────────────────────────────────────────────────────


def test_each_length_mode_takes_the_distance_its_mode_names():
    a, b = (0.3, 0.4, 1.0), (0.0, 0.0, 0.4)
    marks = {}
    for spec in LENGTH_SPEC:
        marks[spec['a']] = _landmark(1.0, a)
        marks[spec['b']] = _landmark(0.4, b)
    M: dict = {}
    MT.length_rows(M, _scan(landmarks=marks))
    expected = {'horizontal': 0.5, 'vertical': 0.6, '3d': float(np.linalg.norm(np.array(a) - np.array(b)))}
    for spec in LENGTH_SPEC:
        row = M[spec['name']]
        want = expected[spec['mode']]
        assert row['value_mm'] == pytest.approx(want * 1000), spec['name']
        assert row['frac_stature'] == pytest.approx(want / STATURE_M)
        assert row['provenance'] == 'MEASURED'


def test_a_length_with_one_unresolved_end_is_unmeasurable():
    spec = LENGTH_SPEC[0]
    M: dict = {}
    MT.length_rows(M, _scan(landmarks={spec['a']: _landmark(1.0, (0.0, 0.0, 1.0))}))
    row = M[spec['name']]
    assert row['value_mm'] is None
    assert row['reason'] == 'one of the two landmarks is unresolved'
    assert row['landmark'] == '%s to %s' % (spec['a'], spec['b'])


def test_a_length_spec_marked_not_survey_comparable_carries_its_reason():
    spec = next((s for s in LENGTH_SPEC if s.get('survey_comparable') is False), None)
    if spec is None:
        pytest.skip('no non-survey-comparable length in the table today')
    marks = {spec['a']: _landmark(1.0, (0.0, 0.0, 1.0)), spec['b']: _landmark(0.9, (0.0, 0.0, 0.9))}
    M: dict = {}
    MT.length_rows(M, _scan(landmarks=marks))
    assert M[spec['name']]['survey_comparable'] is False
    assert M[spec['name']]['survey_not_comparable_because'] == spec['survey_reason']


# ── the girth and extent tables ──────────────────────────────────────────────


def test_a_girth_site_gets_one_row_per_side_and_an_unsided_site_gets_one(monkeypatch):
    seen: list[tuple] = []

    def _fake(v, faces, spec, side, *a, **kw):
        seen.append((spec['name'], side))
        return {'value_mm': 1.0}

    monkeypatch.setattr(MT, '_girth_site', _fake)
    M: dict = {}
    MT.girth_rows(M, _scan())
    expected = []
    for spec in GIRTH_SITES:
        for side in spec['sides'] or (None,):
            expected.append(spec['name'] + ('_' + side if side else ''))
    assert sorted(M) == sorted(expected)
    assert len(seen) == len(expected)


def test_an_unmeasurable_breadth_is_recorded_without_asking_the_geometry(monkeypatch):
    asked: list[str] = []

    def _fake(v, faces, spec, *a, **kw):
        asked.append(spec['name'])
        return {'value_mm': 2.0}

    monkeypatch.setattr(MT, '_extent_measure', _fake)
    M: dict = {}
    MT.extent_rows(M, _scan())
    refused = [s['name'] for s in BREADTH_SPEC if not s.get('measurable', True)]
    assert refused, 'the table has always carried at least one refused breadth'
    for name in refused:
        assert M[name]['provenance'] == 'UNMEASURABLE'
        assert M[name]['convention'] == 'not applicable'
        assert name not in asked
    for spec in DEPTH_SPEC:
        assert spec['name'] in asked


def test_breadths_are_taken_on_x_and_depths_on_y(monkeypatch):
    axes: dict[str, str] = {}

    def _fake(v, faces, spec, lm, zmin, H, step, axis, *a, **kw):
        axes[spec['name']] = axis
        return {'value_mm': 3.0}

    monkeypatch.setattr(MT, '_extent_measure', _fake)
    MT.extent_rows({}, _scan())
    for spec in BREADTH_SPEC:
        if spec.get('measurable', True):
            assert axes[spec['name']] == 'x', spec['name']
    for spec in DEPTH_SPEC:
        assert axes[spec['name']] == 'y', spec['name']


# ── the volume block ─────────────────────────────────────────────────────────


def test_volume_is_geometry_but_mass_and_bmi_are_house(monkeypatch):
    monkeypatch.setattr(MT, 'body_volume', lambda v, f: (0.070, 0.072, 'closed'))
    M: dict = {}
    MT.volume_rows(M, _scan())
    assert M['body_volume_l']['value'] == pytest.approx(70.0)
    assert M['body_volume_l']['units'] == 'L'
    assert M['body_volume_l']['inclusions_l'] == pytest.approx(2.0)
    assert M['body_volume_l']['provenance'] == 'MEASURED'
    assert M['volume_height_index']['value'] == pytest.approx(70.0 / STATURE_M**2)
    assert M['volume_height_index']['provenance'] == 'MEASURED'
    mass = 0.070 * BODY_DENSITY_KG_M3
    assert M['derived_mass_kg']['value'] == pytest.approx(mass)
    assert M['derived_mass_kg']['provenance'] == 'HOUSE'
    assert M['derived_mass_kg']['alternative_at_vendor_density_kg'] == pytest.approx(
        0.070 * ANNY_VENDOR_DENSITY_KG_M3,
    )
    assert M['derived_bmi']['value'] == pytest.approx(mass / STATURE_M**2)
    assert M['derived_bmi']['provenance'] == 'HOUSE'


def test_the_shell_note_reaches_the_volume_row(monkeypatch):
    monkeypatch.setattr(MT, 'body_volume', lambda v, f: (0.06, 0.06, 'NOT CLOSED: 4 holes'))
    M: dict = {}
    MT.volume_rows(M, _scan())
    assert M['body_volume_l']['note'].endswith('NOT CLOSED: 4 holes')


# ── provenance: the coco source and the meta block ───────────────────────────


def test_no_phenotype_is_announced_as_a_neutral_fallback(monkeypatch):
    monkeypatch.setattr(LMK, '_coco', lambda p, lc: 'KEYPOINTS')
    coco, src = MT.resolve_coco(None, None)
    assert coco == 'KEYPOINTS'
    assert src.startswith('NEUTRAL FALLBACK')
    assert '16-19 mm' in src


def test_a_phenotype_is_announced_as_this_recipe(monkeypatch):
    monkeypatch.setattr(LMK, '_coco', lambda p, lc: 'KEYPOINTS')
    coco, src = MT.resolve_coco({'height': 1.8}, {})
    assert coco == 'KEYPOINTS'
    assert src == 'anny COCO keypoint regressor on THIS recipe'


def test_a_regressor_failure_leaves_no_anchors_and_says_why(monkeypatch):
    def _boom(p, lc):
        raise RuntimeError('no torch')

    monkeypatch.setattr(LMK, '_coco', _boom)
    coco, src = MT.resolve_coco({'height': 1.8}, {})
    assert coco is None
    assert src == 'UNAVAILABLE: no torch'


def test_the_meta_block_carries_the_pose_the_scope_and_the_conventions():
    meta = MT.meta_block(_scan(sex='female', name='ada', t_start=0.0))
    assert meta['schema'] == 'geom.anthro.measure/1'
    assert meta['name'] == 'ada'
    assert meta['sex_declared'] == 'female'
    assert meta['pose'] == 'A-pose'
    assert meta['axis_convention'] == 'z up'
    assert meta['stature_m'] == STATURE_M
    assert '2 vertices' in meta['vertex_scope']
    assert '2 triangles of 3' in meta['vertex_scope']
    assert meta['vertex_scope'].endswith('shell note')
    assert meta['coco_source'] == 'test'
    assert meta['ear_top_frac_stature'] == 0.93
    assert meta['crotch_frac_stature'] == 0.47
    assert meta['density_assumption_kg_m3'] == BODY_DENSITY_KG_M3
    assert meta['arm_mask_provenance'] == {'ran': True}
    assert meta['a_pose_bias']['built'] is False
    assert meta['elapsed_s'] >= 0.0


# ── the refusals table ───────────────────────────────────────────────────────


def test_every_dimension_this_cage_cannot_give_is_recorded_as_a_refusal():
    M: dict = {}
    MT.unmeasurable_rows(M)
    assert sorted(M) == sorted(s['name'] for s in UNMEASURABLE)
    for spec in UNMEASURABLE:
        row = M[spec['name']]
        assert row['value_mm'] is None
        assert row['provenance'] == 'UNMEASURABLE'
        assert row['reason'] == spec['reason']
        assert row['kind'] == spec['kind']


# ── the orchestrator: the passes still run in the original order ─────────────


def test_measure_mesh_runs_the_table_passes_in_the_order_the_old_body_did(monkeypatch):
    import types

    from zyg_workflows.geom.anthro.measure import mesh as MM

    calls: list[str] = []

    def _record(name, result=None):
        def _fn(*a, **kw):
            calls.append(name)
            return result

        return _fn

    tables = types.SimpleNamespace(
        MeshScan=MT.MeshScan,
        resolve_coco=_record('resolve_coco', ('COCO', 'src')),
        height_rows=_record('height_rows'),
        cervicale_row=_record('cervicale_row'),
        length_rows=_record('length_rows'),
        girth_rows=_record('girth_rows'),
        extent_rows=_record('extent_rows'),
        volume_rows=_record('volume_rows'),
        meta_block=_record('meta_block', {'schema': 'x'}),
        unmeasurable_rows=_record('unmeasurable_rows'),
    )
    monkeypatch.setattr(MM, '_tables', tables)
    monkeypatch.setattr(MM, 'check_pose_and_frame', lambda v, f: {'pose': 'A-pose'})
    monkeypatch.setattr(MM, '_topology', lambda f: _topo())
    monkeypatch.setattr(MM, '_limb_axes', lambda coco: 'AXES')
    monkeypatch.setattr(MM, 'adducted_copy', lambda v, coco: ('REF', {'built': True}))
    monkeypatch.setattr(MM, '_ear_top_frac', lambda v, zmin, H: 0.9)
    monkeypatch.setattr(MM, '_ratios', _record('_ratios', {'r': 1.0}))

    out = MM.measure_mesh(
        [[0.0, 0.0, 0.0], [0.1, 0.0, STATURE_M]],
        [[0, 1, 1, 0]],
        sex='male',
        landmarks={'crotch': {'frac_stature': 0.47}},
        name='ada',
    )
    assert calls == [
        'resolve_coco',
        'height_rows',
        'cervicale_row',
        'length_rows',
        'girth_rows',
        'extent_rows',
        'volume_rows',
        '_ratios',
        'meta_block',
        'unmeasurable_rows',
    ]
    assert sorted(out) == ['measurements', 'meta', 'ratios']
    assert out['meta'] == {'schema': 'x'}
    assert out['ratios'] == {'r': 1.0}


def test_measure_mesh_hands_every_pass_one_scan_built_from_the_mesh(monkeypatch):
    import types

    from zyg_workflows.geom.anthro.measure import mesh as MM

    seen: list[MT.MeshScan] = []

    def _grab(M, scan):
        seen.append(scan)

    tables = types.SimpleNamespace(
        MeshScan=MT.MeshScan,
        resolve_coco=lambda p, lc: ('COCO', 'SRC'),
        height_rows=_grab,
        cervicale_row=_grab,
        length_rows=_grab,
        girth_rows=_grab,
        extent_rows=_grab,
        volume_rows=_grab,
        meta_block=lambda scan: {},
        unmeasurable_rows=lambda M: None,
    )
    monkeypatch.setattr(MM, '_tables', tables)
    monkeypatch.setattr(MM, 'check_pose_and_frame', lambda v, f: {'pose': 'A-pose'})
    monkeypatch.setattr(MM, '_topology', lambda f: _topo())
    monkeypatch.setattr(MM, '_limb_axes', lambda coco: 'AXES')
    monkeypatch.setattr(MM, 'adducted_copy', lambda v, coco: ('REF', {'built': True}))
    monkeypatch.setattr(MM, '_ear_top_frac', lambda v, zmin, H: 0.9)
    monkeypatch.setattr(MM, '_ratios', lambda M, H: {})

    MM.measure_mesh(
        [[0.0, 0.0, 0.25], [0.1, 0.0, 2.0]],
        [[0, 1, 1, 0]],
        sex='male',
        landmarks={'crotch': {'frac_stature': 0.47}},
    )
    assert len({id(s) for s in seen}) == 1, 'every pass shares one scan'
    scan = seen[0]
    assert scan.zmin == pytest.approx(0.25)
    assert scan.H == pytest.approx(1.75)
    assert scan.coco == 'COCO' and scan.coco_src == 'SRC'
    assert scan.axes == 'AXES'
    assert scan.pose_ref == 'REF' and scan.pose_ref_info == {'built': True}
    assert scan.ear_top == 0.9
    assert scan.crotch_frac == 0.47
    assert scan.sex == 'male'
    assert scan.v.dtype == np.float64
