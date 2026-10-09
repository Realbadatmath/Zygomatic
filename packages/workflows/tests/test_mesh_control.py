#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Invariants of the mesh -> diffusion control maps, and of the klein RefControl graph.

These test the ARTEFACTS rather than importing mesh_control, deliberately: that module
pulls geom.passes_io, which imports cv2 at module scope, and the test venv carries only
pytest/numpy/pillow. A test that skipped itself when cv2 was missing would stop guarding
the thing it exists for, so the depth maps are read with pillow and the graph with json.

    scripts/run_tests.sh tests/test_mesh_control.py
"""

import json
import os

import numpy as np
import pytest
from PIL import Image

from tests import _tree

# Not in this checkout: the rendered prop is in the asset tree. The control-map tests
# below already skip on the manifest, and the graph test does not need the prop at all.
ASSET_DIR = os.path.join(str(_tree.DATA), 'assets', 'prop_meshes', 'pufferball')
CTRL = os.path.join(ASSET_DIR, 'control')
MANIFEST = os.path.join(CTRL, 'control.json')

_have = os.path.isfile(MANIFEST)
needs_ctrl = pytest.mark.skipif(not _have, reason='control maps not built')


def _man():
    with open(MANIFEST, encoding='utf-8') as fh:
        return json.load(fh)


def _png(name):
    return np.asarray(Image.open(os.path.join(CTRL, name)))


# ── the defect that motivates the whole module ──────────────────────────────
@needs_ctrl
def test_the_ground_is_excluded_by_name():
    """THE 89% DEFECT. Every conditioning map normalises over its subject, and on a
    turntable sheet the GROUND PLANE is a rendered surface running to the horizon.
    Measured on front_full: the creature spans 1.236-1.608 m, the floor 1.004-4.429 m.
    Normalising over all rendered pixels spends 89% of the 0-255 range on floor and
    leaves the creature 27 levels for its entire form. The exclusion is BY NAME
    through the asset's own IndexOB vocabulary, because the integer differs per
    creature — a hard-coded 8 is the version of this that breaks silently."""
    m = _man()
    assert 'ground' in m['exclude'], m['exclude']
    assert m['excluded_indices'].get('ground'), 'ground never resolved to an index'


@needs_ctrl
def _creature_diagonal_m():
    """The longest line through the registered SOLID creature, from the registry's
    size_m — the most depth any camera angle can legitimately see."""
    import math

    reg = _tree.data('assets', 'prop_meshes', 'registry.json')
    with open(reg, encoding='utf-8') as fh:
        s = json.load(fh)['assets']['pufferball']['geometry']['size_m']
    return math.sqrt(s['width'] ** 2 + s['depth'] ** 2 + s['height'] ** 2)


def test_no_view_spans_the_floor_range():
    """The observable consequence of the above: a depth range wider than the creature
    is deep means the floor got back in.

    The ceiling is the creature's own diagonal, not a constant. A fixed 0.75 m was
    written for the 0.46 m creature and failed on 2026-08-28 for close_q_left at
    0.756 m — measured, every pixel in that view's far band was TAIL at the top of
    the frame (the tip curling behind the head), not floor. The floor, when it leaks
    in, spans metres."""
    ceiling = _creature_diagonal_m() + 0.06  # + fur reach
    for vid, e in _man()['views'].items():
        span = e['far_m'] - e['near_m']
        assert span < ceiling, (
            '%s spans %.3f m against a creature diagonal of %.3f m — '
            'the ground plane is in the range' % (vid, span, ceiling)
        )


# ── polarity: the one that silently builds the creature inside-out ──────────
@needs_ctrl
def test_depth_polarity_is_near_white_background_black():
    """Depth-Anything's non-metric checkpoints emit INVERSE depth (near = large) and
    apply no inversion, so every depth ControlNet in this repo is fed near=white. Our
    buffer is metric metres, where near is SMALL. Invert it wrongly and the model
    builds the subject inside-out — and nothing in the pipeline raises."""
    d = _png('front_full_depth.png')
    assert d.ndim == 2, 'depth map should be single channel, got %s' % (d.shape,)
    assert d.max() == 255, 'nearest surface is not white'
    assert d[0, 0] == 0 and d[-1, -1] == 0, 'background is not black'
    # the nearest surface on a front view is the face, which sits in the middle band
    h, w = d.shape
    centre = d[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4]
    assert centre.max() > d[: h // 8].max(), 'the brightest pixels are at the frame edge'


@needs_ctrl
def test_depth_and_matte_agree_exactly():
    """The matte is the subject mask; the depth is written over that same mask. If
    they disagree, one of them is describing a different set of pixels than the other
    and a composite built from both will be misaligned."""
    for vid in ('front_full', 'top_down', 'back'):
        d, m = _png('%s_depth.png' % vid), _png('%s_matte.png' % vid)
        assert ((d > 0) == (m > 0)).mean() > 0.999, '%s: depth and matte disagree' % vid


# ── fail closed ─────────────────────────────────────────────────────────────
@needs_ctrl
def test_no_control_map_is_blank():
    """A black control map is not a weak signal — it is a confident instruction to
    put every surface at infinity, and it looks like a successful run in every log.
    An empty subject mask must be SKIPPED and named, never written."""
    man = _man()
    for vid, e in man['views'].items():
        for kind in ('depth', 'matte'):
            if not e.get(kind):
                continue
            a = _png(e[kind])
            assert a.max() > 0, '%s_%s is entirely black' % (vid, kind)
            assert 0.001 < (a > 0).mean() < 0.999, '%s_%s covers %.4f of frame' % (vid, kind, (a > 0).mean())
    for vid, why in (man.get('skipped') or {}).items():
        assert why, 'view %s skipped with no reason recorded' % vid


@needs_ctrl
def test_coverage_matches_the_recorded_number():
    """The manifest's coverage figure is what an operator reads instead of opening
    the file. It must be the same number the file actually carries."""
    for vid, e in _man()['views'].items():
        if not e.get('matte'):
            continue
        got = float((_png(e['matte']) > 0).mean())
        assert got == pytest.approx(e['coverage'], abs=0.002), '%s: %.4f vs %.4f' % (vid, got, e['coverage'])


@needs_ctrl
def test_manifest_states_its_polarity_and_scope():
    """A control map with no stated convention is a guess for whoever consumes it."""
    m = _man()
    assert 'near=white' in m['polarity']
    assert m['normalize'] in ('view', 'asset')


# ── the klein RefControl graph ──────────────────────────────────────────────
GRAPH = _tree.pkg('_comfy_workflows', 'klein_refcontrol.json')
needs_graph = pytest.mark.skipif(not os.path.isfile(GRAPH), reason='graph absent')


def _graph():
    with open(GRAPH, encoding='utf-8') as fh:
        return json.load(fh)


@needs_graph
def test_reference_chain_order_puts_depth_first():
    """FLUX.2 concatenates every chained ReferenceLatent with an incrementing
    positional index, so CHAIN POSITION IS THE IMAGE INDEX. RefControl was trained
    with the depth map as image 1; swap the chain and the adapter is asked to take
    its geometry from a photograph. Nothing errors — the render is simply wrong."""
    g = _graph()
    assert g['24']['inputs']['pixels'] == ['23', 0]  # 23 <- 22, the depth LoadImage
    assert g['23']['inputs']['image'] == ['22', 0]
    assert g['44']['inputs']['pixels'] == ['43', 0]  # 43 <- 42, the reference
    assert g['43']['inputs']['image'] == ['42', 0]
    # first link in the chain carries the DEPTH latent...
    assert g['26']['inputs']['latent'] == ['24', 0]
    assert g['27']['inputs']['latent'] == ['24', 0]
    # ...and the second carries the reference, taking conditioning FROM the first
    assert g['28']['inputs']['conditioning'] == ['26', 0]
    assert g['29']['inputs']['conditioning'] == ['27', 0]
    assert g['28']['inputs']['latent'] == ['44', 0]
    assert g['29']['inputs']['latent'] == ['44', 0]
    # and the guider must consume the END of the chain, not the middle
    assert g['34']['inputs']['positive'] == ['28', 0]
    assert g['34']['inputs']['negative'] == ['29', 0]


@needs_graph
def test_control_lora_is_model_only_and_stacked_last():
    """The identity adapter goes first and the control adapter on top, matching the
    style-then-character order arcane_restyle uses on SDXL. Model-only is required:
    nodes 20/21 take clip straight off the CLIPLoader chain."""
    g = _graph()
    assert g['14']['class_type'] == 'LoraLoaderModelOnly'
    assert 'refcontrol' in g['14']['inputs']['lora_name']
    assert g['14']['inputs']['model'] == ['13', 0], 'control LoRA is not stacked on identity'
    assert g['34']['inputs']['model'] == ['14', 0], 'guider bypasses the control LoRA'


@needs_graph
def test_trigger_word_is_in_the_template():
    """The adapter has a trigger word. Without it the LoRA loads and does nothing
    recognisable — which looks exactly like 'the control image was ignored' and gets
    debugged in the wrong place."""
    assert 'refcontrol' in _graph()['20']['inputs']['text'].lower()


@needs_graph
def test_both_scalers_carry_resolution_steps():
    """resolution_steps is REQUIRED by this ComfyUI's ImageScaleToTotalPixels and is
    absent from UI exports. Without it the graph fails validation with 'Required input
    is missing', which reads like a broken link rather than node-signature drift."""
    g = _graph()
    for nid in ('23', '43'):
        assert 'resolution_steps' in g[nid]['inputs'], 'node %s missing resolution_steps' % nid


@needs_graph
def test_graph_is_api_format():
    """UI-format exports have nodes/links keys and do not submit. Every node here
    must be a flat id -> {inputs, class_type} record."""
    g = _graph()
    for nid, node in g.items():
        assert nid.isdigit(), 'non-numeric node id %r' % nid
        assert 'class_type' in node and 'inputs' in node, nid
