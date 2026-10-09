#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The ten skeleton ops of studio_ext_server/movement_rig.py.

What these guard is the seam, not the geometry. movement_rig is reached only
through studio_ext_dispatch.ext_module, so every test below loads it the way
kanban_server does — if the module stops importing, or an op disappears from
ROUTES, the panel gets a 404 and nothing else notices. Blender is never run
here: `build` is tested on the paths that REFUSE (unknown character, unknown
motion) and on its naming rule, and `render` on the ComfyUI probe with the
probe monkeypatched, because starting a real render from a unit test would take
the GPU for half an hour.

The fences get their own tests because they are the only thing standing between
a query string and open(): `glb` must refuse '../x' on the NAME and an unknown
actor on the PATH.

Run:  scripts/run_tests.sh tests/test_movement_rig_ops.py
"""

import os

import pytest

from zyg_workflows import motion_library as ML
from zyg_workflows import studio_ext_dispatch

# Every op here reads the motion library and the fixture capture shot, both of which are in
# the asset tree rather than in this repository.
if not os.path.isfile(ML.LIBRARY_JSON):
    pytest.skip('the motion library is not in this checkout: %s' % ML.ROOT, allow_module_level=True)

ABEL = 'c3345deb5bde'
OPS = ('subjects', 'clips', 'metrics', 'build', 'job', 'glb', 'video', 'edit', 'capture', 'render')


@pytest.fixture(scope='module')
def m():
    mod = studio_ext_dispatch.ext_module('movement_rig')
    assert mod is not None, 'studio_ext_server/movement_rig.py does not load'
    return mod


# ── the seam ────────────────────────────────────────────────────────────────
def test_routes_hold_all_ten_ops(m):
    missing = [op for op in OPS if op not in m.ROUTES]
    assert not missing, f'not in ROUTES: {missing}'
    assert len(m.ROUTES) == 10, sorted(m.ROUTES)
    assert all(callable(fn) for fn in m.ROUTES.values())


def test_the_module_is_listed_by_the_dispatcher(m):  # noqa: ARG001
    mods = studio_ext_dispatch.ext_mods()
    assert 'movement_rig' in mods
    assert sorted(OPS) == mods['movement_rig']


# ── subjects ────────────────────────────────────────────────────────────────
def test_subjects_lists_abel_with_his_bible_height(m):
    res = m.ROUTES['subjects']({}, 'GET')
    assert res['ok'] is True
    rows = {r['id']: r for r in res['subjects']}
    assert ABEL in rows, 'Abel is not among the subjects'
    abel = rows[ABEL]
    assert abel['name'] == 'Abel Van Haren'
    assert abel['height_m'] == 1.52
    assert abel['gender'] == 'male'
    assert abel['age'] == 12
    # the four flags the panel needs to know what it may offer
    for key in ('has_body_cell', 'has_metrics', 'actors', 'body_build'):
        assert key in abel


def test_subjects_is_cached(m):
    a = m.ROUTES['subjects']({}, 'GET')
    b = m.ROUTES['subjects']({}, 'GET')
    assert a['subjects'] is b['subjects'], 'the 30 s cache is not holding'


# ── clips ───────────────────────────────────────────────────────────────────
def test_clips_carries_every_bucket(m):
    res = m.ROUTES['clips']({}, 'GET')
    assert res['ok'] is True
    by_id = {c['id']: c for c in res['clips']}
    assert 'cmu/02_01' in by_id
    assert 'capture/qa_sword' in by_id
    assert by_id['cmu/02_01']['bucket'] == 'cmu'
    assert by_id['capture/qa_sword']['bucket'] == 'capture'
    assert by_id['cmu/02_01']['label'] == 'walk'
    # a capture's licence is the licence of the video it came from, and the
    # rest frame is the one frame that is NOT part of the performance
    assert by_id['capture/qa_sword']['rest_frame'] == 1
    assert by_id['capture/qa_sword']['publishable'] is False
    assert {'auth', 'cmu', 'capture'} <= {c['bucket'] for c in res['clips']}


# ── the name fence ──────────────────────────────────────────────────────────
@pytest.mark.parametrize('name', ['../x', '../../etc/passwd', '', 'a/b', 'abel capture', 'x' * 81])
def test_glb_refuses_a_bad_name(m, name):
    res = m.ROUTES['glb']({'name': name}, 'GET')
    assert isinstance(res, dict), 'a refused name must not return bytes'
    assert res.get('error') and not res.get('ok')
    assert res['code'] == 404


def test_glb_refuses_an_unknown_actor(m):
    res = m.ROUTES['glb']({'name': 'no_such_actor_at_all'}, 'GET')
    assert isinstance(res, dict) and res.get('error') and res['code'] == 404


def test_glb_serves_bytes_with_no_attachment(m):
    """The built actor streams as glTF. filename must be None — a
    Content-Disposition would make the browser download it instead of
    letting the glTF loader read it."""
    name = m.actor_name(ABEL, 'cmu/02_01')
    adir = m._actor_dir(name)
    if not adir or not os.path.isfile(os.path.join(adir, name + '.glb')):
        pytest.skip(f'{name}.glb is not built in this checkout')
    res = m.ROUTES['glb']({'name': name}, 'GET')
    assert isinstance(res, tuple) and len(res) == 3
    blob, mime, filename = res
    assert blob[:4] == b'glTF'
    assert mime == 'model/gltf-binary'
    assert filename is None


# ── build ───────────────────────────────────────────────────────────────────
def test_the_actor_naming_rule(m):
    assert m.actor_name(ABEL, 'cmu/02_01') == f'{ABEL}__cmu_02_01'
    assert m.actor_name(ABEL, 'capture/qa_sword') == f'{ABEL}__capture_qa_sword'


def test_build_refuses_an_unknown_character(m):
    res = m.ROUTES['build']({'char_id': 'zzzzzzzzzzzz', 'motion': 'cmu/02_01'}, 'POST')
    assert res.get('error') and not res.get('ok')
    assert res['code'] == 404


def test_build_refuses_an_unknown_motion(m):
    res = m.ROUTES['build']({'char_id': ABEL, 'motion': 'cmu/nope'}, 'POST')
    assert res.get('error') and not res.get('ok')
    assert res['code'] == 404


def _fresh_actor(m):
    """The first of Abel's built actors whose GLB is newer than all its inputs.

    Rebuilding the base rig invalidates every actor, so which of them is fresh
    depends on what has been built since — the test asks rather than assumes.
    fit=False, because whether it carries a fit is the NEXT test's question."""
    for motion in ('capture/qa_sword', 'cmu/02_01'):
        name = m.actor_name(ABEL, motion)
        adir = m._actor_dir(name)
        if adir and os.path.isfile(os.path.join(adir, name + '.glb')) and m._glb_is_fresh(name, motion, fit=False):
            return name, motion
    return None, None


def test_build_returns_the_cached_glb_without_starting_a_job(m):
    """A GLB newer than all its inputs is served straight back — no Blender."""
    name, motion = _fresh_actor(m)
    if not name:
        pytest.skip('no freshly built actor for Abel in this checkout')
    res = m.ROUTES['build']({'char_id': ABEL, 'motion': motion, 'fit': False}, 'POST')
    assert res['ok'] is True and res['cached'] is True
    assert res['actor'] == name
    assert res['glb'] == f'/inspect/api/studio/movement_rig/glb?name={name}'
    assert 'job_id' not in res, 'a cached build must not start a job'
    assert res['meta']['motion'] == motion


def test_an_unfitted_actor_is_never_fresh_for_a_fitted_build(m):
    """fit:true must always deliver a fit, so an actor whose sidecar carries no
    fit report is stale no matter how new its GLB is."""
    name, motion = _fresh_actor(m)
    if not name:
        pytest.skip('no freshly built actor for Abel in this checkout')
    fitted = bool((m._actor_meta(name).get('fit') or {}).get('status'))
    assert m._glb_is_fresh(name, motion, fit=True) is fitted


# ── jobs ────────────────────────────────────────────────────────────────────
def test_job_and_video_refuse_an_unknown_id(m):
    for op in ('job', 'video'):
        res = m.ROUTES[op]({'job_id': 'deadbeefcafe'}, 'GET')
        assert res.get('error') and res['code'] == 404, op


def test_job_id_shape_is_fenced(m):
    assert m._job_dir('../../etc') is None
    assert m._job_dir('not-a-hex-id') is None
    assert m._job_dir('a96ab24393c3') is not None


# ── metrics / edit / capture validation ─────────────────────────────────────
def test_metrics_refuses_an_unknown_character(m):
    res = m.ROUTES['metrics']({'char_id': 'zzzzzzzzzzzz'}, 'POST')
    assert res.get('error') and res['code'] == 404


def test_edit_refuses_an_unknown_source_and_a_bad_slug(m):
    bad_src = m.ROUTES['edit']({'src': 'cmu/nope', 'save': 'x', 'mirror': True}, 'POST')
    assert bad_src.get('error') and bad_src['code'] == 404
    bad_slug = m.ROUTES['edit']({'src': 'cmu/02_01', 'save': '../escape', 'mirror': True}, 'POST')
    assert bad_slug.get('error') and not bad_slug.get('ok')


def test_edit_refuses_a_no_op(m):
    res = m.ROUTES['edit']({'src': 'cmu/02_01', 'save': 'whatever'}, 'POST')
    assert res.get('error') and 'nothing to do' in res['error']


def test_capture_refuses_a_missing_video_and_a_bad_clip_id(m):
    no_video = m.ROUTES['capture']({'video': '/nope.mp4', 'clip_id': 'capture/x', 'label': 'x'}, 'POST')
    assert no_video.get('error') and no_video['code'] == 404
    bad_id = m.ROUTES['capture']({'video': __file__, 'clip_id': 'cmu/x', 'label': 'x'}, 'POST')
    assert bad_id.get('error') and 'capture/' in bad_id['error']


# ── render ──────────────────────────────────────────────────────────────────
def test_render_refuses_an_unknown_actor(m):
    res = m.ROUTES['render']({'actor': 'no_such_actor_at_all'}, 'POST')
    assert res.get('error') and res['code'] == 404


def test_render_refuses_409_when_comfyui_is_unreachable(m, monkeypatch):
    """Half an hour of VACE against a dead ComfyUI is half an hour of waiting
    for a failure, so the probe is a precondition and it names what it missed."""
    name = m.actor_name(ABEL, 'cmu/02_01')
    adir = m._actor_dir(name)
    if not adir or not os.path.isfile(os.path.join(adir, name + '.blend')):
        pytest.skip(f'{name}.blend is not built in this checkout')
    monkeypatch.setattr(m, '_comfy_up', lambda: False)
    res = m.ROUTES['render']({'actor': name}, 'POST')
    assert res.get('error') and not res.get('ok')
    assert res['code'] == 409
    assert '8188' in res['error']
    assert 'job_id' not in res, 'a refused render must not start a job'


def test_render_checks_the_actor_before_the_gpu(m, monkeypatch):
    """The 404 for an unknown actor must come out even when ComfyUI is up —
    order matters, or an operator typo becomes a GPU reservation."""
    monkeypatch.setattr(m, '_comfy_up', lambda: True)
    res = m.ROUTES['render']({'actor': 'no_such_actor_at_all'}, 'POST')
    assert res['code'] == 404


def test_render_shot_copies_the_take_10_recipe(m, tmp_path, monkeypatch):
    """The fixture's VACE block is the recipe that makes the identity hold —
    _render_shot may swap the actor and the frame count and nothing else."""
    name = m.actor_name(ABEL, 'cmu/02_01')
    if not m._actor_dir(name):
        pytest.skip(f'{name} is not built in this checkout')
    import json

    monkeypatch.setattr(m, 'SHOTS_DIR', str(tmp_path))
    with open(m.FIXTURE_SHOT, encoding='utf-8') as fh:
        fixture = json.load(fh)
    path, sdir, frames = m._render_shot('abc123abc123', name, '', 40)
    with open(path, encoding='utf-8') as fh:
        shot = json.load(fh)
    assert shot['id'] == 'mvr_abc123abc123'
    assert shot['schema'] == 'zyg.scene_shot/1'
    assert shot['actors'][0]['proxy'] == name
    assert shot['actors'][0]['char_id'] == ABEL
    assert shot['video'] == fixture['video'], 'the VACE recipe was altered'
    assert shot['frames'] == frames == 40
    # no keyframe may point past the end of the shot
    assert all(k['f'] <= 40 for k in shot['camera']['keys'])
    assert all(k['f'] <= 40 for k in shot['actors'][0]['path'])


def test_render_frames_are_capped_at_the_fixture_length(m, tmp_path):
    name = m.actor_name(ABEL, 'cmu/02_01')
    if not m._actor_dir(name):
        pytest.skip(f'{name} is not built in this checkout')
    import json

    orig = m.SHOTS_DIR
    m.SHOTS_DIR = str(tmp_path)
    try:
        path, _, frames = m._render_shot('abc123abc124', name, 'a prompt', 9999)
    finally:
        m.SHOTS_DIR = orig
    assert frames == 97
    with open(path, encoding='utf-8') as fh:
        assert json.load(fh)['video']['prompt'] == 'a prompt'
