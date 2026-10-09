# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The documentary picture count IS the LTX clip length (2026-10-02).

Every documentary picture now becomes one LTX-2.5 clip, so the count is however
many clip-length slots the narration needs — not the old hardcoded
``max(10, int(duration / 20))``.  What is checked here:

  * the count is derived from CLIP_S, CLIP_S is clamped to the MEASURED VRAM
    ceiling (20 s at 1280x704 on the 4090 — 47.9 GB of 49.1 GB), and no slot is
    ever longer than the clip that has to cover it;
  * the 10-picture floor is gone, so a short episode stops over-generating;
  * a longer clip buys proportionally fewer pictures;
  * the motion prompt FREEZES the subject.  This is the regression that matters:
    with a loose prompt LTX had two men who were shouting at each other kissing
    by second four of a 20 s clip.  The prompt is the only guard — the distilled
    graph runs at CFG 1, so there is no negative prompt to lean on;
  * a run with no LTX server reports its Ken Burns fallback instead of claiming
    coverage it does not have.

CPU-only: no ComfyUI, no GPU, no ffmpeg.
"""

import importlib
import math
import os
import sys

import pytest

from tests import _tree

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mod(**env):
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    from zyg_workflows import scholarly_motion

    return importlib.reload(scholarly_motion)


@pytest.fixture
def sm():
    m = _mod(ZYG_SCHOLARLY_CLIP_S=None, ZYG_SCHOLARLY_LTX=None)
    yield m
    _mod(ZYG_SCHOLARLY_CLIP_S=None, ZYG_SCHOLARLY_LTX=None)


# ── the count is derived, not hardcoded ──────────────────────────────────────


def test_count_is_narration_over_clip_length(sm):
    for duration in (120, 360, 600, 1036, 1800):
        n = sm.n_images_for(duration)
        assert n == max(sm.MIN_IMAGES, math.ceil(duration / sm.clip_target_s()))


def test_no_slot_outruns_its_clip(sm):
    """ceil, not int: rounding the count down is what makes the last slot
    longer than the clip ceiling, and that is the case that OOMs."""
    for duration in (61, 199, 1036, 1037, 1110, 2400):
        n = sm.n_images_for(duration)
        assert duration / n <= sm.clip_target_s() + 1e-9


def test_short_episode_stops_over_generating(sm):
    """The old floor handed a 60 s episode ten pictures of six seconds each."""
    assert max(10, int(60 / 20)) == 10
    assert sm.n_images_for(60) == 3
    assert sm.n_images_for(120) == 6


def test_full_length_episode_tracks_the_old_cadence(sm):
    """A 17-min episode asked for 51 pictures before and 52 now — the extra one
    is the ceil that keeps every slot under the clip ceiling, not a surplus."""
    assert sm.n_images_for(1036) == 52


def test_longer_clip_buys_fewer_pictures(sm):
    counts = [_mod(ZYG_SCHOLARLY_CLIP_S=str(c)).n_images_for(600) for c in (5, 10, 15, 20)]
    assert counts == sorted(counts, reverse=True)
    assert counts[0] > counts[-1]


def test_clip_length_is_clamped_to_the_measured_ceiling(sm):
    assert _mod(ZYG_SCHOLARLY_CLIP_S='45').clip_target_s() == sm.CLIP_MAX_S
    assert _mod(ZYG_SCHOLARLY_CLIP_S='0.5').clip_target_s() == sm.CLIP_MIN_S
    assert _mod(ZYG_SCHOLARLY_CLIP_S='nonsense').clip_target_s() == sm.CLIP_MAX_S


def test_rendered_clip_never_exceeds_the_ceiling(sm):
    for duration in (60, 360, 1036, 2400):
        n = sm.n_images_for(duration)
        assert sm.clip_seconds(duration / n) <= sm.CLIP_MAX_S


def test_clip_carries_xfade_headroom_over_its_slot(sm):
    assert sm.clip_seconds(7.0) >= 8
    assert sm.clip_seconds(0.1) >= 2  # LTX needs 8n+1 frames


def test_floor_holds_for_a_degenerate_duration(sm):
    for d in (0, -5, None, 'x'):
        assert sm.n_images_for(d) == sm.MIN_IMAGES


# ── the prompt is the guard ──────────────────────────────────────────────────


def test_motion_prompt_freezes_the_subject(sm):
    p = sm.motion_prompt({'subject': 'two men arguing', 'shot_type': 'close-up, dramatic'})
    low = p.lower()
    assert 'same pose' in low and 'same expression' in low and 'same position' in low
    assert 'no new action' in low


def test_motion_prompt_never_asks_for_a_camera_move(sm):
    """Measured twice: a prompted "push in" pulled the camera BACK and invented a
    crowd of deformed faces, and restating it with NEVER-widens did the same. The
    move belongs in render_move, where a crop cannot hallucinate."""
    low = sm.motion_prompt({'subject': 'a crowd', 'shot_type': 'wide establishing shot'}).lower()
    assert 'locked off' in low and 'does not move at all' in low
    for banned in ('push', 'dolly', 'zoom in', 'pull back', 'widen', 'tighter', 'drift'):
        assert banned not in low, banned


def test_motion_prompt_asks_for_no_text_and_no_new_people(sm):
    p = sm.motion_prompt({'subject': 'a harbour', 'shot_type': 'wide establishing shot'}).lower()
    assert 'no text' in p and 'no extra people' in p and 'no cut' in p


def test_motion_prompt_survives_a_bare_entry(sm):
    for entry in ({}, {'subject': None, 'shot_type': None}):
        p = sm.motion_prompt(entry)
        assert 'first frame' in p and len(p) > 100


# ── the camera move ──────────────────────────────────────────────────────────


def test_move_direction_alternates(sm):
    z0_even, z1_even, _ = sm.move_for(0)
    z0_odd, z1_odd, _ = sm.move_for(1)
    assert z1_even > z0_even  # push in
    assert z1_odd < z0_odd  # pull out


def test_move_travel_is_the_same_either_way(sm):
    for i in (0, 1, 8, 15):
        z0, z1, _ = sm.move_for(i)
        assert abs(abs(z1 - z0) - sm.ZOOM) < 1e-9


def test_move_never_zooms_below_one(sm):
    """Anything under 1.0 would need pixels outside the frame — the exact thing
    a prompted pull-out invented."""
    for i in range(12):
        z0, z1, _ = sm.move_for(i)
        assert min(z0, z1) >= 1.0


def test_focal_zone_biases_the_centre(sm):
    assert sm.move_for(0, 'left')[2] < sm.move_for(0, 'center')[2] < sm.move_for(0, 'right')[2]
    assert sm.move_for(0, 'nonsense')[2] == sm.move_for(0, 'center')[2]


def test_zoompan_filter_is_well_formed(sm):
    vf = sm._zoompan_vf(20.0, 0, 'center')
    assert 'zoompan=' in vf and 's=1920x1080' in vf and 'fps=30' in vf
    assert f'{sm._WORK_W}:{sm._WORK_H}' in vf  # 2x work canvas kills the stepping
    assert 'min(on/600,1)' in vf  # 20 s x 30 fps, clamped


def test_zoompan_clamp_tracks_clip_length(sm):
    assert 'min(on/150,1)' in sm._zoompan_vf(5.0, 0, 'center')
    assert 'min(on/1,1)' in sm._zoompan_vf(0.0, 0, 'center')  # never divides by zero


# ── honest reporting ─────────────────────────────────────────────────────────


def test_disabled_run_reports_kenburns_not_coverage(sm):
    m = _mod(ZYG_SCHOLARLY_LTX='0')
    rec = m.animate_stills([{'path': '/nonexistent/a.png'}] * 4, '/tmp', total_s=80)
    assert rec['clips'] == 0
    assert rec['kenburns'] == 4
    assert rec['motion_coverage'] == 0.0
    assert 'ZYG_SCHOLARLY_LTX=0' in rec['reason']


def test_no_pictures_is_not_an_error(sm):
    rec = sm.animate_stills([], '/tmp', total_s=80)
    assert rec['clips'] == 0 and rec['pictures'] == 0


def test_server_down_falls_back_and_says_so(sm, stub_module):
    class _Stub:
        @staticmethod
        def ensure_up(log_fn=None):
            return False

    stub_module('ltx_hidream_service', _Stub)
    rec = sm.animate_stills([{'path': __file__}] * 3, '/tmp', total_s=60)
    assert rec['clips'] == 0
    assert rec['kenburns'] == 3
    assert rec['motion_coverage'] == 0.0
    assert ':8189' in rec['reason']


# ── the pipeline reads the same rule ─────────────────────────────────────────
# pipeline_scholarly cannot be imported standalone (it pulls the whole Flask GUI
# in through a circular import), so these read its source.  The regression they
# guard is real and has bitten before: the picture count used to be written out
# at TWO sites and they have to move together.
#
# The stages moved out of the monolith into zyg_workflows/scholarly/stages_*.py
# (2026-10-05), so the sites live there now; the source read is the driver plus
# the stage package, which is what "the pipeline" is.
# A stage module may itself be a package since 2026-10-06, so the stage sources
# are discovered rather than listed: stages_*.py plus every *.py in a stages_*/.


def _pipeline_sources():
    stage_dir = _tree.pkg('scholarly')
    out = []
    for name in os.listdir(stage_dir):
        if not name.startswith('stages_'):
            continue
        path = os.path.join(stage_dir, name)
        if name.endswith('.py') and os.path.isfile(path):
            out.append(path)
        elif os.path.isdir(path):
            out += [
                os.path.join(path, sub)
                for sub in os.listdir(path)
                if sub.endswith('.py') and os.path.isfile(os.path.join(path, sub))
            ]
    # the driver is a package since 2026-10 (pipeline_scholarly/): every module of it is the driver
    drv = _tree.pkg('pipeline_scholarly')
    driver = sorted(os.path.join(drv, n) for n in os.listdir(drv) if n.endswith('.py'))
    return [*driver, *sorted(out)]


def _pipeline_src():
    out = []
    for path in _pipeline_sources():
        with open(path, encoding='utf-8') as fh:
            out.append(fh.read())
    return '\n'.join(out)


def test_no_hardcoded_picture_count_survives(sm):
    src = _pipeline_src()
    assert 'max(10, int(tts_duration / 20))' not in src
    assert 'max(10, int(_est_duration / 20))' not in src
    assert 'max(3, int(float(td) / 20))' not in src


def test_every_count_site_goes_through_the_helper(sm):
    src = _pipeline_src()
    assert src.count('_scholarly_n_images(') >= 5  # def + 4 call sites
    for site in (
        '_tls_n = _scholarly_n_images(ctx.tts_duration)',
        '_n_flux_images = _scholarly_n_images(_est_duration)',
        'n_flux_images = _scholarly_n_images(float(td))',
    ):
        assert site in src, site


def test_helper_delegates_to_this_module(sm):
    src = _pipeline_src()
    assert 'import scholarly_motion as _scholarly_motion' in src
    assert 'return _scholarly_motion.n_images_for(duration_s)' in src


def test_stage_6_reads_the_ltx_manifest(sm):
    src = _pipeline_src()
    assert '_scholarly_motion.MANIFEST_REL' in src
    assert "_stage_start('Stage 5: LTX Motion')" in src


def test_a_cap_cannot_make_a_slot_outrun_its_clip(sm):
    """A 150 s request that narrates to 221.8 s left an 8-picture cap covering
    27.7 s a slot against a 20 s clip — every shot would have looped."""
    src = _pipeline_src()
    assert '_motion_floor = _scholarly_n_images(_est_duration)' in src
    assert 'if _n_flux_images < _motion_floor:' in src
    # the floor it raises to is the one that keeps a slot inside a clip
    assert 221.8 / sm.n_images_for(221.8) <= sm.clip_target_s()
    assert sm.n_images_for(221.8) == 12
