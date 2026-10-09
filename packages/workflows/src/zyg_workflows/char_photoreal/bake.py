#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char_photoreal — the bake section, verbatim lines 1969-2568 of the original module."""

from __future__ import annotations

import numpy as np

from zyg_workflows.char_photoreal.equalise import Vox
from zyg_workflows.char_photoreal.bake_views import (
    bake_view,
    gain_depth,
    load_anchors,
    load_bake_geometry,
)
from zyg_workflows.char_photoreal.bake_gain import match_view_gains
from zyg_workflows.char_photoreal.bake_blend import (
    blend_contributions,
    blend_weights,
    fill_holes,
    polish_atlas,
    resolve_blend,
    write_bake_manifest,
)


def stage_bake(body, log, force=False, views=None, probe=None):
    """Bake the rendered views into one albedo atlas and write its manifest.

    The orchestrator of the stages in :mod:`bake_stages`: rasterise the atlas,
    bake each view's colour and weights, match the per-view exposures, blend
    the detail and tone bands, run the finishing passes, fill the holes and
    pad the result. ``views`` restricts the bake to a subset; ``probe``, when
    given, is called with every intermediate field. Returns the manifest dict.
    """
    geom = load_bake_geometry(body, log)
    anchors = load_anchors(geom.wd)
    refs, per_view = {}, {}
    order = sorted(geom.cams['views'], key=lambda vid: gain_depth(vid, geom.cams['views']))
    for vid in order:
        if views and vid not in views:
            continue
        baked = bake_view(vid, geom, anchors, log, probe)
        if baked is None:
            continue
        refs[vid], per_view[vid] = baked

    match_view_gains(order, refs, per_view, geom, anchors, log)
    vox = Vox(geom.P.reshape(-1, 3))
    xm = 0.5 * (geom.P[..., 0].min() + geom.P[..., 0].max())
    log(f'[bake] 3D low-pass grid {vox.shape} at {vox.res * 1000:.1f} mm')
    contrib = [
        (refs[vid][0], refs[vid][1], refs[vid][3], vid, refs[vid][4], refs[vid][5], refs[vid][6], refs[vid][7])
        for vid in order
        if vid in refs
    ]

    weights = blend_weights(contrib, len(geom.ys))
    bands = blend_contributions(contrib, geom, weights, vox, log)
    blend, covered = resolve_blend(bands, weights, contrib, geom, probe, log)
    del bands

    island = np.zeros((geom.H, geom.W), np.uint8)
    island[geom.ys, geom.xs] = 1
    tex8, blend, sh, pair_gap, seam_log, hand_log = polish_atlas(blend, covered, geom, anchors, vox, xm, probe, log)
    pad = fill_holes(tex8, blend, covered, island, geom, vox, probe, log)
    return write_bake_manifest(body, geom, pad, per_view, covered, sh, pair_gap, seam_log, hand_log, log)
