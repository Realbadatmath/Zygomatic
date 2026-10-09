# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for char2d_mouth.py — the 3-shape pakupaku mouth and its timing."""

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zyg_workflows import char2d_mouth as M  # noqa: E402

BENCH = Path(__file__).resolve().parents[1] / 'output' / 'char2d' / '_bench_mika'


# --------------------------------------------------------------------------- #
# collapse
# --------------------------------------------------------------------------- #


def test_collapse_maps_every_rhubarb_shape():
    cues = [(i * 0.1, (i + 1) * 0.1, v) for i, v in enumerate('XABCDEFGH')]
    got = [s for _, _, s in M.collapse(cues)]
    # X,A -> closed ; B,C -> mid ; D -> open ; E,F,G,H -> mid
    assert got == ['closed', 'mid', 'open', 'mid']
    per_shape = {v: M.COLLAPSE_MAP[v] for v in 'XABCDEFGH'}
    assert per_shape == {
        'X': 'closed',
        'A': 'closed',
        'B': 'mid',
        'C': 'mid',
        'E': 'mid',
        'F': 'mid',
        'G': 'mid',
        'H': 'mid',
        'D': 'open',
    }


def test_collapse_merges_adjacent_equal_shapes():
    cues = [(0.0, 0.1, 'X'), (0.1, 0.2, 'A'), (0.2, 0.3, 'B'), (0.3, 0.4, 'C'), (0.4, 0.5, 'D')]
    out = M.collapse(cues)
    assert out == [(0.0, 0.2, 'closed'), (0.2, 0.4, 'mid'), (0.4, 0.5, 'open')]


# --------------------------------------------------------------------------- #
# quantise
# --------------------------------------------------------------------------- #


def _alternating_cues(n_frames, fps=24, shapes=('X', 'D')):
    """A cue list that flips every single frame — the worst case for the gate."""
    return [(i / fps, (i + 1) / fps, shapes[i % len(shapes)]) for i in range(n_frames)]


def test_quantise_alternating_every_frame_holds_and_rate():
    fps, min_hold, n = 24, 6, 144
    raw = _alternating_cues(n, fps)
    frames = M.quantise(M.collapse(raw), fps=fps, min_hold=min_hold, duration=n / fps)
    assert len(frames) == n
    assert M.min_run(frames) >= min_hold
    assert M.change_rate(frames, fps) <= 4.0


def test_quantise_alternating_three_shapes_rate():
    fps, min_hold, n = 24, 6, 240
    raw = _alternating_cues(n, fps, shapes=('X', 'B', 'D'))
    frames = M.quantise(M.collapse(raw), fps=fps, min_hold=min_hold, duration=n / fps)
    assert M.min_run(frames) >= min_hold
    assert M.change_rate(frames, fps) <= 4.0


def test_quantise_rate_never_exceeds_four_on_random_cues():
    rng = np.random.default_rng(20260916)
    fps, min_hold = 24, 6
    for _ in range(25):
        n = int(rng.integers(30, 400))
        vals = list('XABCDEFGH')
        raw = [(i / fps, (i + 1) / fps, vals[int(rng.integers(0, len(vals)))]) for i in range(n)]
        speech = M.speech_frames(raw, fps, n)
        frames = M.quantise(M.collapse(raw), fps=fps, min_hold=min_hold, speech=speech, duration=n / fps)
        assert M.min_run(frames) >= min_hold, (n, M._runs(frames))
        assert M.change_rate(frames, fps) <= 4.0, (n, M.change_rate(frames, fps))


def test_long_closed_hold_reopens_with_mid_while_speech_continues():
    fps, n = 24, 48
    # 2 s of Rhubarb 'A' (lips together, but still speech, not rest)
    raw = [(0.0, n / fps, 'A')]
    speech = [True] * n
    frames = M.quantise(M.collapse(raw), fps=fps, min_hold=6, speech=speech, duration=n / fps)
    runs = M._runs(frames)
    assert max(n for s, n in runs if s == 'closed') <= 10
    assert any(s == 'mid' for s, _ in runs)
    assert M.min_run(frames) >= 6
    assert M.change_rate(frames, fps) <= 4.0


def test_silent_closed_hold_is_left_alone():
    fps, n = 24, 48
    raw = [(0.0, n / fps, 'X')]
    speech = M.speech_frames(raw, fps, n)
    assert not any(speech)
    frames = M.quantise(M.collapse(raw), fps=fps, min_hold=6, speech=speech, duration=n / fps)
    assert set(frames) == {'closed'}


def test_split_closed_run_keeps_min_hold():
    for length in range(6, 120):
        parts = M._split_closed_run(length, 6, 10)
        assert sum(parts) == length
        assert min(parts) >= 6


# --------------------------------------------------------------------------- #
# sprites
# --------------------------------------------------------------------------- #


def _alpha(path):
    return np.asarray(Image.open(path).convert('RGBA').split()[3])


@pytest.fixture(scope='module')
def views_doc():
    p = BENCH / 'views.json'
    if not p.exists():
        pytest.skip(f'bench views missing: {p}')
    return json.loads(p.read_text())


def test_view_kind_from_yaw():
    assert M.view_kind(0.0) == 'front'
    assert M.view_kind(45.0) == 'front45'
    assert M.view_kind(315.0) == 'front45'
    assert M.view_kind(90.0) == 'profile'
    assert M.view_kind(270.0) == 'profile'
    assert M.view_kind(180.0) == 'back'


def test_back_overlays_are_empty(tmp_path, views_doc):
    anchor = views_doc['views']['back']
    png = BENCH / anchor['file']
    info = M.draw_mouth_set(png, anchor, tmp_path)
    assert info['kind'] == 'back'
    size = Image.open(png).size
    for shape in M.SHAPES:
        f = tmp_path / f'back_{shape}.png'
        assert f.exists()
        a = _alpha(f)
        assert Image.open(f).size == size, 'overlay must be full-frame'
        assert int(a.max()) == 0, f'back_{shape}.png must be fully transparent'


def test_profile_overlays_are_drawn_and_full_frame(tmp_path, views_doc):
    anchor = views_doc['views']['profileL']
    png = BENCH / anchor['file']
    info = M.draw_mouth_set(png, anchor, tmp_path)
    assert info['kind'] == 'profile'
    # the projected mouth width collapses to ~0 on a profile: fall back to the
    # head-height estimate so the wedge still has a real size
    assert anchor['mouth_w_px'] < 4.0
    assert info['mouth_w'] > 10.0
    size = Image.open(png).size
    for shape in M.SHAPES:
        f = tmp_path / f'profileL_{shape}.png'
        assert Image.open(f).size == size
        assert int(_alpha(f).max()) > 0, f'profileL_{shape}.png must not be empty'


def test_front_overlays_sit_on_the_mouth_anchor(tmp_path, views_doc):
    anchor = views_doc['views']['front']
    png = BENCH / anchor['file']
    M.draw_mouth_set(png, anchor, tmp_path)
    ax, ay = anchor['mouth_px']
    mw = anchor['mouth_w_px']
    for shape in M.SHAPES:
        a = _alpha(tmp_path / f'front_{shape}.png')
        ys, xs = np.nonzero(a > 8)
        assert len(xs), shape
        cx, cy = xs.mean(), ys.mean()
        assert abs(cx - ax) < mw, (shape, cx, ax)
        assert abs(cy - ay) < mw, (shape, cy, ay)


# --------------------------------------------------------------------------- #
# the delivered bench timing
# --------------------------------------------------------------------------- #


def test_bench_timing_document_is_within_the_gate():
    p = BENCH / 'talk' / 'timing.json'
    if not p.exists():
        pytest.skip(f'bench timing missing: {p}')
    d = json.loads(p.read_text())
    assert d['fps'] == 24
    assert d['min_run_frames'] >= 6
    assert d['changes_per_s'] <= 4.0
    assert set(d['frames']) <= set(M.SHAPES)
    assert M.change_rate(d['frames'], d['fps']) == pytest.approx(d['changes_per_s'], abs=1e-3)
