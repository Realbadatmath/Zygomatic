# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""blender_scripts/scene_render.py — import guard + the placement.json contract.

No Blender here: the module has to import under a plain CPython so the kanban
server and this test can read its constants and its frame-range parser without
paying for a 4 GB bpy.  What the test then checks is the file the renderer
actually wrote for the fixture shot, because placement.json is the interface
the studio overlay and the Video Studio placement tool read — a change in its
shape is a broken UI, not a failed render.
"""

from __future__ import annotations

import importlib.util
import json
import os

import pytest

from tests import _tree

SCRIPT = _tree.pkg('blender_scripts', 'scene_render.py')
SHOT_DIR = _tree.data('architecture', 'shots', 'fixture_house')
DRAFT = os.path.join(SHOT_DIR, 'draft', 'placement.json')


def _load():
    spec = importlib.util.spec_from_file_location('scene_render_under_test', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope='module')
def mod():
    return _load()


@pytest.fixture(scope='module')
def placement():
    if not os.path.isfile(DRAFT):
        pytest.skip('no draft placement.json yet — run scene_render.py --mode draft')
    with open(DRAFT, 'r', encoding='utf-8') as fh:
        return json.load(fh)


# --------------------------------------------------------------------------
# import guard
# --------------------------------------------------------------------------


def test_imports_without_blender(mod):
    assert mod.bpy is None and mod.mathutils is None
    assert mod.PLACEMENT_SCHEMA == 'zyg.scene_placement/1'
    assert mod.BOUNDS_SCHEMA == 'zyg.scene_effect_bounds/1'
    assert (mod.DRAFT_W, mod.DRAFT_H) == (320, 180)
    assert mod.DRAFT_ENGINE == 'BLENDER_WORKBENCH'
    assert mod.FULL_SAMPLES == 64
    assert len(mod.FX_COLOURS) == 6
    assert 0.0 < mod.BOX_ALPHA < 1.0
    assert mod.LABEL_M == 0.4


def test_parse_frames(mod):
    assert mod.parse_frames('', 1, 49) == (1, 49)
    assert mod.parse_frames('24:24', 1, 49) == (24, 24)
    assert mod.parse_frames('10:20', 1, 49) == (10, 20)
    assert mod.parse_frames('20:10', 1, 49) == (10, 20)  # swapped, not empty
    assert mod.parse_frames('0:900', 1, 49) == (1, 49)  # clamped to the shot
    assert mod.parse_frames('7', 1, 49) == (7, 7)


# --------------------------------------------------------------------------
# placement.json — the draft the renderer produced
# --------------------------------------------------------------------------


def test_placement_header(mod, placement):
    for k in (
        'schema',
        'shot',
        'mode',
        'width',
        'height',
        'fps',
        'frame_start',
        'frame_end',
        'n_frames',
        'pixel_origin',
        'effects',
        'actors',
        'frames',
    ):
        assert k in placement, 'placement.json lost key %r' % k
    assert placement['schema'] == mod.PLACEMENT_SCHEMA
    assert placement['shot'] == 'fixture_house'
    assert placement['mode'] == 'draft'
    assert (placement['width'], placement['height']) == (mod.DRAFT_W, mod.DRAFT_H)
    assert placement['fps'] == 24
    assert placement['pixel_origin'] == 'top-left, y down'
    assert placement['effects'] == ['fire1']
    assert placement['actors'] == ['abel']


def test_placement_covers_every_frame(placement):
    assert (placement['frame_start'], placement['frame_end']) == (1, 49)
    assert placement['n_frames'] == 49
    assert len(placement['frames']) == 49
    assert [r['f'] for r in placement['frames']] == list(range(1, 50))


def test_every_frame_carries_the_effect(placement):
    w, h = placement['width'], placement['height']
    for rec in placement['frames']:
        fx = rec['effects']['fire1']  # KeyError = the UI has nothing to draw
        for k in (
            'in_front',
            'clipped',
            'bbox_px',
            'centre_px',
            'ground_px',
            'distance_m',
            'ground_distance_m',
            'world_min',
            'world_max',
        ):
            assert k in fx, 'frame %d effect lost key %r' % (rec['f'], k)
        assert fx['in_front'] is True and fx['on_screen'] is True
        x0, y0, x1, y1 = fx['bbox_px']
        assert x1 > x0 and y1 > y0, 'frame %d: degenerate bbox' % rec['f']
        assert 0 <= x0 and x1 <= w and 0 <= y0 and y1 <= h
        gx, gy = fx['ground_px']
        assert x0 - 1 <= gx <= x1 + 1, 'frame %d: ground point outside the box' % rec['f']
        assert gy >= fx['centre_px'][1], 'frame %d: ground above centre (y runs down)' % rec['f']
        assert fx['distance_m'] > 0.0
        assert len(fx['world_min']) == 3 and len(fx['world_max']) == 3
        assert all(fx['world_max'][i] > fx['world_min'][i] for i in range(3))


def test_every_frame_carries_the_actor(placement):
    seen = set()
    for rec in placement['frames']:
        a = rec['actors']['abel']
        for k in ('ground_px', 'in_front', 'on_screen', 'distance_m', 'ry', 'world'):
            assert k in a, 'frame %d actor lost key %r' % (rec['f'], k)
        assert a['in_front'] is True
        assert a['distance_m'] > 0.0
        seen.add(tuple(a['ground_px']))
    # the fixture walks abel 4 m towards the camera, so the projected ground
    # point must actually move — a frozen one means the per-frame pass is
    # reading frame 1 over and over.
    assert len(seen) == 49


def test_effects_bounds_cache_shape(mod):
    path = os.path.join(SHOT_DIR, 'effects_bounds.json')
    if not os.path.isfile(path):
        pytest.skip('no effects_bounds.json yet')
    with open(path, 'r', encoding='utf-8') as fh:
        doc = json.load(fh)
    assert doc['schema'] == mod.BOUNDS_SCHEMA
    rec = doc['effects']['fire1']
    assert len(rec['local']) == 8 and all(len(c) == 3 for c in rec['local'])
    assert rec['size_m'][2] == pytest.approx(1.5, abs=0.05)  # shot says size_m 1.5
