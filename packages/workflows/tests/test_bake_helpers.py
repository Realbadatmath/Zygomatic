# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers ``stage_bake`` was split into (2026-10-09).

``gain_depth``, ``gain_ratio`` and ``covered_image`` used to be the closures
``_gdepth``, ``_ratio`` and ``_img`` inside the 598-line stage, so this is the
first time their logic is exercised on its own.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from zyg_workflows.char_photoreal.constants import GAIN_MIN_SHARED, GAIN_MIN_SHARED_HAND, HAND_RADIUS
from zyg_workflows.char_photoreal.bake_views import BakeGeom, gain_depth, load_anchors
from zyg_workflows.char_photoreal.bake_gain import gain_ratio
from zyg_workflows.char_photoreal.bake_blend import (
    BlendBands,
    BlendWeights,
    blend_weights,
    covered_image,
    resolve_blend,
)


def _geom(**over):
    """A BakeGeom with the fields the pure helpers read and dummies elsewhere."""
    empty = np.zeros((0, 3), np.float64)
    fields = dict(
        wd='/nonexistent',
        P=empty,
        N=empty,
        UV=empty,
        cams={'size': 8, 'views': {}},
        tiles=[],
        W=1,
        H=1,
        AUV=empty,
        ids=np.zeros(0, np.int64),
        ys=np.zeros(0, np.int64),
        xs=np.zeros(0, np.int64),
        tid=np.zeros(0, np.int64),
        bary=empty,
        Pt=empty,
        Nt=empty,
    )
    fields.update(over)
    return BakeGeom(**fields)


def _view(w, edge, *, w2=None, cov=None, vid='body_front'):
    """One ``contrib`` record: (col, w, wl, vid, edge, w2, wl2, cov)."""
    w = np.asarray(w, np.float32)
    edge = np.asarray(edge, np.float32)
    zeros = np.zeros_like(w)
    return (
        zeros,
        w,
        zeros,
        vid,
        edge,
        np.asarray(w if w2 is None else w2, np.float32),
        zeros,
        np.asarray(zeros if cov is None else cov, np.float32),
    )


# ── gain_depth (was the _gdepth closure) ─────────────────────────────────────


def test_gain_depth_counts_the_hops_up_the_render_chain():
    views = {'body_front': {}, 'body_fl': {}, 'body_left': {}, 'body_bl': {}}
    # body_front's parent (ref_seed) is not a view, so it is the chain's root
    assert gain_depth('body_front', views) == 0
    assert gain_depth('body_fl', views) == 1
    assert gain_depth('body_left', views) == 2
    assert gain_depth('body_bl', views) == 3


def test_gain_depth_stops_at_a_parent_outside_the_view_set():
    """Sorting by the depth must bake a parent before its children."""
    views = {'body_left': {}, 'body_bl': {}}
    assert gain_depth('body_left', views) == 0  # body_fl was not rendered
    assert gain_depth('body_bl', views) == 1
    assert sorted(views, key=lambda v: gain_depth(v, views)) == ['body_left', 'body_bl']


def test_gain_depth_of_an_unknown_view_is_zero():
    assert gain_depth('not_a_view', {'not_a_view': {}}) == 0


# ── load_anchors ─────────────────────────────────────────────────────────────


def test_load_anchors_reads_the_blender_report(tmp_path):
    (tmp_path / 'blender_report.json').write_text(
        json.dumps(
            {'hand_c': {'hand_l': [0.1, 0.2, 0.3]}, 'eye_c': {'eye_r': [0, 0, 1.6]}, 'hi': [0, 0, 1.78], 'head_h': 0.23}
        )
    )
    anchors = load_anchors(str(tmp_path))
    assert list(anchors.hand_c) == ['hand_l']
    np.testing.assert_allclose(anchors.hand_c['hand_l'], [0.1, 0.2, 0.3])
    np.testing.assert_allclose(anchors.eye_c['eye_r'], [0.0, 0.0, 1.6])
    assert anchors.head_top_z == pytest.approx(1.78)
    assert anchors.head_h == pytest.approx(0.23)


def test_load_anchors_survives_a_missing_report(tmp_path):
    """A bake without the report runs on, with no hand or eye zone."""
    anchors = load_anchors(str(tmp_path))
    assert anchors.hand_c == {} and anchors.eye_c == {}
    assert anchors.head_top_z == 0.0 and anchors.head_h == 0.0


# ── covered_image (was the _img closure) ─────────────────────────────────────


def test_covered_image_paints_and_clips_only_the_covered_texels():
    geom = _geom(W=3, H=2, ys=np.array([0, 1, 1]), xs=np.array([0, 1, 2]))
    covered = np.array([True, False, True])
    im = covered_image(np.array([[10.0, 20.0, 30.0], [300.0, -5.0, 40.0]]), geom, covered)
    assert im.shape == (2, 3, 3) and im.dtype == np.uint8
    assert im[0, 0].tolist() == [10, 20, 30]
    assert im[1, 2].tolist() == [255, 0, 40]  # clipped into 0..255
    assert im[1, 1].tolist() == [0, 0, 0]  # the uncovered texel stays black


# ── blend_weights ────────────────────────────────────────────────────────────


def test_blend_weights_reduces_the_views_to_the_blend_envelopes():
    a = _view([1.0, 0.0, 2.0], [1.0, 1.0, 1.0], w2=[1.0, 5.0, 2.0], cov=[0.3, 0.9, 0.0], vid='body_front')
    b = _view([4.0, 3.0, 0.0], [1.0, 1.0, 1.0], w2=[4.0, 3.0, 0.0], cov=[0.1, 2.0, 0.0], vid='body_fl')
    weights = blend_weights([a, b], 3)
    assert isinstance(weights, BlendWeights)
    np.testing.assert_allclose(weights.wmax, [4.0, 3.0, 2.0])
    np.testing.assert_allclose(weights.wlin, [5.0, 3.0, 2.0])
    np.testing.assert_allclose(weights.wbmax, [4.0, 3.0, 2.0])
    np.testing.assert_allclose(weights.wmax_l, [4.0, 5.0, 2.0])
    # no view yields its tone today, so the coverage of "the others" is every
    # view's, clipped into 0..1
    np.testing.assert_allclose(weights.cov_others, [0.3, 1.0, 0.0])


def test_blend_weights_soft_zone_follows_the_mask_feather():
    """A view that matters and is inside its own feather blends linearly."""
    inside = _view([1.0, 1.0], [1.0, 0.25], vid='body_front')
    weights = blend_weights([inside], 2)
    np.testing.assert_allclose(weights.soft, [0.0, 0.75])


def test_blend_weights_ignores_a_view_too_weak_to_matter():
    strong = _view([0.0, 10.0], [1.0, 1.0], vid='body_front')
    weak = _view([0.0, 0.1], [1.0, 0.5], vid='body_fl')  # 0.2 of 10 unfeathered
    weights = blend_weights([strong, weak], 2)
    np.testing.assert_allclose(weights.soft, [0.0, 0.0])


# ── gain_ratio (was the _ratio closure) ──────────────────────────────────────


def _refs(n, col, pcol, cos=0.9):
    full = np.ones(n, np.float32)
    return {
        'child': [np.full((n, 3), col, np.float32), full, full * cos],
        'parent': [np.full((n, 3), pcol, np.float32), full, full * cos],
    }


def test_gain_ratio_is_the_median_over_squarely_shared_texels():
    n = GAIN_MIN_SHARED + 10
    r, shared = gain_ratio('child', 'parent', _refs(n, 100.0, 150.0), np.zeros((n, 3)), {})
    assert shared == n
    np.testing.assert_allclose(r, [1.5, 1.5, 1.5])


def test_gain_ratio_refuses_too_little_shared_skin():
    """Below GAIN_MIN_SHARED the caller must inherit the parent's gain instead."""
    n = GAIN_MIN_SHARED - 1
    r, shared = gain_ratio('child', 'parent', _refs(n, 100.0, 150.0), np.zeros((n, 3)), {})
    assert r is None and shared == n


def test_gain_ratio_skips_the_texels_neither_view_sees_squarely():
    n = GAIN_MIN_SHARED + 10
    refs = _refs(n, 100.0, 150.0)
    refs['child'][2] = np.full(n, 0.4, np.float32)  # grazing angle everywhere
    r, shared = gain_ratio('child', 'parent', refs, np.zeros((n, 3)), {})
    assert r is None and shared == 0


def test_gain_ratio_of_a_hand_view_is_taken_over_the_wrist_band():
    n = 2 * GAIN_MIN_SHARED_HAND
    refs = _refs(n, 100.0, 150.0)
    centre = np.zeros(3)
    Pt = np.zeros((n, 3))
    in_band = 0.5 * (HAND_RADIUS[0] - 0.03 + HAND_RADIUS[1] + 0.03)
    Pt[: n // 2, 0] = in_band  # the wrist band
    Pt[n // 2 :, 0] = 1.0  # the thigh the hand photo also shares
    r, shared = gain_ratio('child', 'parent', refs, Pt, {'child': centre})
    assert shared == n // 2
    np.testing.assert_allclose(r, [1.5, 1.5, 1.5])


# ── resolve_blend ────────────────────────────────────────────────────────────


def test_resolve_blend_prefers_the_strict_band_and_falls_back_to_loose():
    geom = _geom(W=3, H=1, ys=np.array([0, 0, 0]), xs=np.array([0, 1, 2]))
    zero3 = np.zeros((3, 3), np.float64)
    bands = BlendBands(
        acc=np.array([[4.0] * 3, [0.0] * 3, [0.0] * 3]),
        wsum=np.array([4.0, 0.0, 0.0]),
        acc2=np.array([[0.0] * 3, [2.0] * 3, [0.0] * 3]),
        wsum2=np.array([0.0, 2.0, 0.0]),
        acc_lp=np.array([[100.0] * 3, [0.0] * 3, [0.0] * 3]),
        wls=np.array([2.0, 0.0, 0.0]),
        acc_lp2=zero3.copy(),
        wls2=np.array([0.0, 3.0, 0.0]),
        winner=np.array([0, 1, -1], np.int16),
    )
    bands.acc_lp2[1] = 60.0
    weights = BlendWeights(
        wmax=np.zeros(3, np.float32),
        wlin=np.zeros(3),
        wbmax=np.zeros(3, np.float32),
        cov_others=np.zeros(3, np.float32),
        soft=np.zeros(3, np.float32),
        wmax_l=np.zeros(3, np.float32),
    )
    lines = []
    blend, covered = resolve_blend(bands, weights, [], geom, None, lines.append)
    assert covered.tolist() == [True, True, False]
    # texel 0: tone 100/2 x ratio 4/4; texel 1 has no strict band at all and
    # takes the loose tone 60/3 and the loose detail ratio 2/2
    np.testing.assert_allclose(blend, [[50.0] * 3, [20.0] * 3])
    assert any('loose-only detail on 1 texels' in ln for ln in lines)
    assert any('covered 0.667' in ln for ln in lines)
