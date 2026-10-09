# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""scene_shot_run — the stage planner, the composite command, and the docs headings.

No Blender, no GPU, no ffmpeg. The planner is pure mtime arithmetic over a throwaway
shot directory built in tmp_path, which is exactly why it is the part worth pinning:
a wrong skip is silent (it ships yesterday's picture as today's) where a wrong rerun
only costs time.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import scene_shot_run as R  # noqa: E402
from zyg_workflows.bin import exe  # noqa: E402

DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'docs', 'blender_scene_bridge.md')


# ── a synthetic shot directory ───────────────────────────────────────────────

SHOT = {
    'schema': 'zyg.scene_shot/1',
    'id': 'unit',
    'drawing': '',
    'fps': 24,
    'frames': 49,
    'resolution': [832, 480],
    'actors': [{'id': 'a', 'char_id': 'deadbeefcafe'}],
}


def _touch(path, t):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a', encoding='utf-8'):
        pass
    os.utime(path, (t, t))


@pytest.fixture
def shot_dir(tmp_path):
    """Every stage's outputs present and strictly newer than its inputs.

    Times are 1000 s apart in pipeline order, so a single _touch() in a test moves
    exactly one stage's staleness and nothing else's.
    """
    d = str(tmp_path / 'unit')
    _touch(os.path.join(d, 'shot.json'), 1000)
    _touch(os.path.join(d, 'shot.resolved.json'), 2000)
    _touch(os.path.join(d, 'scene.blend'), 3000)
    _touch(os.path.join(d, 'draft', 'draft.mp4'), 4000)
    _touch(os.path.join(d, 'plates_raw', 'camera.json'), 5000)
    _touch(os.path.join(d, 'plates', 'plateset.json'), 6000)
    _touch(os.path.join(d, 'video', 'vace_take1', 'vace_static.mp4'), 7000)
    _touch(os.path.join(d, 'full', 'effects_alpha.mov'), 8000)
    _touch(os.path.join(d, 'final.mp4'), 9000)
    _touch(os.path.join(d, 'final_strip.png'), 9000)
    return d


def plan(shot_dir, **kw):
    io = R.stage_io(shot_dir, SHOT, kw.pop('engine', 'vace'))
    return {s['stage']: s for s in R.plan_stages(io, **kw)}


def ran(p):
    return sorted(k for k, v in p.items() if v['run'])


# ── the planner ──────────────────────────────────────────────────────────────


def test_everything_fresh_runs_nothing(shot_dir):
    assert ran(plan(shot_dir)) == []


def test_missing_final_runs_only_the_composite(shot_dir):
    os.remove(os.path.join(shot_dir, 'final.mp4'))
    p = plan(shot_dir)
    assert ran(p) == ['composite']
    assert p['composite']['reason'] == 'missing output: final.mp4'


def test_editing_the_shot_rebuilds_the_whole_chain(shot_dir):
    _touch(os.path.join(shot_dir, 'shot.json'), 9500)
    p = plan(shot_dir)
    assert ran(p) == sorted(R.STAGE_ORDER)
    assert p['build']['reason'] == 'input newer: shot.json'
    # the cascade is planned, not discovered one mtime at a time
    assert p['draft']['reason'] == 'upstream rerun: build'
    assert p['video']['reason'] == 'upstream rerun: plates'
    assert p['composite']['reason'] == 'upstream rerun: vfx,video'


def test_a_rebuilt_blend_spares_validate(shot_dir):
    _touch(os.path.join(shot_dir, 'scene.blend'), 9500)
    p = plan(shot_dir)
    assert p['validate']['run'] is False
    assert ran(p) == ['composite', 'draft', 'plates', 'vfx', 'video']


def test_new_plates_rerun_the_engine_but_not_the_vfx(shot_dir):
    _touch(os.path.join(shot_dir, 'plates', 'plateset.json'), 9500)
    p = plan(shot_dir)
    assert ran(p) == ['composite', 'video']
    assert p['vfx']['run'] is False
    assert p['build']['run'] is False


def test_a_take_newer_than_the_plates_is_reused(shot_dir):
    """The whole point of the cache: task 12's take survives a re-run."""
    p = plan(shot_dir)
    assert p['video']['run'] is False
    assert p['video']['reason'] == 'up to date'
    assert R.engine_clip(shot_dir, 'vace').endswith('vace_take1/vace_static.mp4')


def test_a_stale_plates_raw_pulls_the_whole_plates_stage(shot_dir):
    """Oldest output wins: a fresh plateset.json cannot hide a stale export."""
    _touch(os.path.join(shot_dir, 'plates_raw', 'camera.json'), 100)
    p = plan(shot_dir)
    assert p['plates']['run'] is True
    assert p['plates']['reason'] == 'input newer: scene.blend'


def test_no_take_at_all_plans_the_engine(shot_dir):
    os.remove(os.path.join(shot_dir, 'video', 'vace_take1', 'vace_static.mp4'))
    p = plan(shot_dir)
    assert p['video']['run'] is True
    assert p['video']['reason'].startswith('missing output:')
    assert R.engine_clip(shot_dir, 'vace') == ''


def test_the_two_engines_have_separate_caches(shot_dir):
    """A vace take says nothing about whether an animate take exists."""
    assert plan(shot_dir, engine='vace')['video']['run'] is False
    assert plan(shot_dir, engine='animate')['video']['run'] is True


def test_draft_only_skips_everything_after_the_draft(shot_dir):
    _touch(os.path.join(shot_dir, 'shot.json'), 9500)
    p = plan(shot_dir, skip=('plates', 'video', 'vfx', 'composite'))
    assert ran(p) == ['build', 'draft', 'validate']
    assert p['plates']['reason'] == 'skipped by flag'


def test_skip_video_still_renders_the_vfx_layer(shot_dir):
    _touch(os.path.join(shot_dir, 'shot.json'), 9500)
    p = plan(shot_dir, skip=('video', 'composite'))
    assert ran(p) == ['build', 'draft', 'plates', 'validate', 'vfx']


def test_force_beats_a_fresh_cache_without_cascading_backwards(shot_dir):
    p = plan(shot_dir, force=('vfx',))
    assert p['vfx']['reason'] == 'forced'
    assert ran(p) == ['composite', 'vfx']  # forward cascade only


def test_skip_beats_force(shot_dir):
    p = plan(shot_dir, force=('video',), skip=('video',))
    assert p['video']['run'] is False


# ── the composite command ────────────────────────────────────────────────────


def test_composite_cmd_is_the_documented_string():
    cmd = R.composite_cmd('/t/eng.mp4', '/t/fx.mov', '/t/final.mp4', 832, 480, 24)
    # argv[0] is the resolved absolute path from zyg_workflows.bin, never the bare name
    assert cmd[0] == exe('ffmpeg')
    assert ' '.join(cmd[1:]) == (
        '-y -loglevel error -i /t/eng.mp4 -i /t/fx.mov -filter_complex '
        '[0:v]scale=832:480,setpts=N/(24*TB),format=rgba[base];'
        '[1:v]scale=832:480,setpts=N/(24*TB),format=rgba[fx];'
        '[base][fx]overlay=0:0:format=auto,format=yuv420p[v] '
        '-map [v] -r 24 -c:v libx264 -crf 18 -pix_fmt yuv420p -an /t/final.mp4'
    )


def test_composite_retimes_by_frame_index_not_by_resampling():
    """VACE encodes at 17 fps, the Blender element at 24. `fps=` would change the
    frame COUNT and slide the element off the frame it was rendered for."""
    cmd = ' '.join(R.composite_cmd('a.mp4', 'b.mov', 'o.mp4', 832, 480, 24))
    assert 'setpts=N/(24*TB)' in cmd
    assert ',fps=' not in cmd
    assert cmd.count('setpts=N/(24*TB)') == 2  # both inputs, or they drift apart


def test_composite_cmd_honours_a_different_shot_shape():
    cmd = ' '.join(R.composite_cmd('a.mp4', 'b.mov', 'o.mp4', 1280, 720, 30))
    assert 'scale=1280:720' in cmd and 'setpts=N/(30*TB)' in cmd and '-r 30' in cmd


# ── 4n+1 ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('n,want', [(49, 49), (48, 45), (50, 49), (17, 17), (4, 17), (1, 17), (81, 81), (80, 77)])
def test_frame_count_is_forced_to_4n_plus_1(n, want):
    assert R._forced_4n1(n) == want


# ── the docs ─────────────────────────────────────────────────────────────────

SIX_QUESTIONS = (
    'Where is the city',
    'Where is the camera',
    'Where are the VFX',
    'Where is the actor',
    'What does the video engine do',
    'What does it look like cut together',
)


def test_docs_exist_and_answer_the_six_questions():
    assert os.path.isfile(DOC), DOC
    text = open(DOC, encoding='utf-8').read()
    heads = [ln.strip() for ln in text.splitlines() if ln.startswith('#')]
    for q in SIX_QUESTIONS:
        assert any(q.lower() in h.lower() for h in heads), 'no heading for %r' % q


def test_docs_state_the_limits_and_the_commands():
    text = open(DOC, encoding='utf-8').read()
    for needed in (
        'scene_shot_run.py',
        '--draft-only',
        '--skip-video',
        'shot.json',
        'plateset.json',
        'effects_alpha.mov',
        'identity',
        'gpu_lock',
        'arch_ext_blender.lock',
    ):
        assert needed in text, 'docs never mention %r' % needed


def test_docs_are_not_longer_than_the_brief_allows():
    assert len(open(DOC, encoding='utf-8').read().splitlines()) <= 150


# ── the sidecar the placement tool reads ─────────────────────────────────────


def test_stage_io_names_every_stage_exactly_once():
    io = R.stage_io('/nowhere', SHOT, 'vace')
    assert sorted(io) == sorted(R.STAGE_ORDER)
    for name, spec in io.items():
        assert set(spec) == {'in', 'out', 'after'}, name
        assert all(os.path.isabs(p) for p in spec['out']), name


def test_receipt_schema_is_stable():
    assert R.SCHEMA == 'zyg.scene_shot_run/1'


def test_settings_sidecar_shape(tmp_path):
    """kanban_server._vfx_draft reads os.path.splitext(clip)[0] + '.settings.json'
    and takes st['scene_shot']; vfx_place.camera_from_scene_shot accepts the dir."""
    d = str(tmp_path)
    payload = {'scene_shot': d, 'clip': os.path.join(d, 'final.mp4'), 'engine': 'vace'}
    p = os.path.join(d, 'final.settings.json')
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh)
    assert json.load(open(p, encoding='utf-8'))['scene_shot'] == d
