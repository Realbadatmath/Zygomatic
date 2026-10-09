# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""vfx_place — the camera maths, the filtergraph and one real 320p draft.

The maths tests are pure arithmetic with a hand-computable answer, so they
catch a sign flip or a fov-axis mix-up that a "the composite ran" test never
would: a level camera's bottom-of-frame pixel lands at exactly
``height / tan(fov/2)`` metres ahead, and nothing else does.

The draft test is the only one that costs anything: a 2 s testsrc clip and the
Dust Shockwave preview through real ffmpeg. It is the claim the whole rack
makes — "press Draft and see it in seconds" — so it is measured rather than
asserted about.
"""

import math
import os
import subprocess
import time

import pytest

from zyg_workflows import vfx_place as V

W, H = 832, 480
FOV, CAM_H = 50.0, 1.6
DUST = 'vfx_volumes/DustShockwaveVDB.zip'

# The element library is tens of gigabytes of VDB and ProRes and lives in the asset tree,
# not in this repository. The camera maths below needs none of it and always runs; the
# tests that place a real element cannot, and say which one they wanted.
needs_library = pytest.mark.skipif(
    DUST not in V.sources(), reason='the VFX element library is not in this checkout: %s' % V.LIBS
)


def _cam(pitch=0.0):
    return V.Camera(W, H, FOV, CAM_H, pitch)


# ────────────────────────────────────────────────────────── camera maths
def test_bottom_centre_lands_at_the_computable_distance():
    """A level camera sees the ground at the bottom of its frame exactly
    height/tan(half-fov) ahead — the one distance in the picture that can be
    worked out on paper."""
    cam = _cam()
    g = cam.ground_point(W / 2.0, H)
    assert g is not None
    expect = CAM_H / math.tan(math.radians(FOV / 2.0))
    assert abs(g[1] - expect) / expect < 0.02, (g, expect)
    assert abs(g[0]) < 1e-6, 'the frame centre column is straight ahead'


def test_ground_point_round_trips_through_project():
    cam = _cam(pitch=12.0)
    u0, v0 = 300.0, 420.0
    gx, gz = cam.ground_point(u0, v0)
    u1, v1, depth = cam.project(gx, 0.0, gz)
    assert depth > 0
    assert abs(u1 - u0) < 1e-6 and abs(v1 - v0) < 1e-6


def test_moving_back_shrinks_the_element_monotonically():
    cam = _cam()
    anchor = (W / 2.0, H * 0.85)
    heights, depths = [], []
    for back in (0.0, 2.0, 4.0, 6.0, 8.0):
        p = cam.place(anchor, 0.0, 0.0, back, 3.0)
        assert p['visible']
        heights.append(p['height_px'])
        depths.append(p['depth'])
    assert all(b < a for a, b in zip(heights, heights[1:])), heights
    assert all(b > a for a, b in zip(depths, depths[1:])), depths
    # 2 m back of a 3.43 m anchor is ~1.58x the depth, so ~0.63x the size
    assert abs(heights[1] / heights[0] - depths[0] / depths[1]) < 1e-9


def test_anchor_above_the_horizon_is_not_placeable():
    cam = _cam()
    assert cam.ground_point(W / 2.0, 10.0) is None
    p = cam.place((W / 2.0, 10.0), 0.0, 0.0, 0.0, 3.0)
    assert p['visible'] is False
    assert 'horizon' in p['reason']


def test_pitch_moves_the_horizon_and_a_level_camera_puts_it_mid_frame():
    assert _cam().ground_point(W / 2.0, H / 2.0 + 1) is not None
    assert _cam().ground_point(W / 2.0, H / 2.0 - 1) is None
    # looking down 10 degrees: the horizon drops, so a pixel above mid-frame
    # that was sky at 0 degrees is now ground
    assert _cam(pitch=10.0).ground_point(W / 2.0, H / 2.0 - 1) is not None


def test_offsets_are_metres_right_up_and_back():
    cam = _cam()
    anchor = (W / 2.0, H)
    base = cam.place(anchor, 0, 0, 0, 3.0)
    right = cam.place(anchor, 1.0, 0, 0, 3.0)
    up = cam.place(anchor, 0, 1.0, 0, 3.0)
    assert right['u'] > base['u'] and abs(right['v'] - base['v']) < 1e-6
    assert up['v'] < base['v'] and abs(up['u'] - base['u']) < 1e-6
    # one metre right at the anchor's depth is focal_px / depth pixels
    assert abs((right['u'] - base['u']) - cam.focal_px / base['depth']) < 1e-6


def test_size_in_metres_scales_the_pixel_height_linearly():
    cam = _cam()
    a = cam.place((W / 2.0, H), 0, 0, 0, 3.0)['height_px']
    b = cam.place((W / 2.0, H), 0, 0, 0, 6.0)['height_px']
    assert abs(b - 2 * a) < 1e-9


# ──────────────────────────────────────────────────────────── the library
@needs_library
def test_element_options_offer_none_first_and_real_rows():
    opts = V.element_options()
    assert opts[0] == {'v': 'none', 'l': 'none'}
    assert any(o['v'] == DUST for o in opts[1:]), 'Dust Shockwave is in the library'


@needs_library
def test_a_draft_takes_the_preview_and_a_bake_takes_the_4k_element():
    d = V.element_for(DUST, draft=True)
    f = V.element_for(DUST, draft=False)
    assert d['mode'] == 'preview' and d['path'].endswith('.mp4')
    assert f['mode'] == 'element' and f['path'].endswith('.webm')
    assert f['alpha'] is True and d['alpha'] is False
    assert os.path.isfile(d['path']) and os.path.isfile(f['path'])
    assert d['aspect'] > 0 and f['aspect'] > 0


def test_an_unknown_element_is_refused_by_name():
    with pytest.raises(ValueError, match='unknown VFX element'):
        V.element_for('vfx_volumes/NotInTheLibrary.zip', draft=True)


# ──────────────────────────────────────────────────────────── the graph
def _ctx():
    return {'w': W, 'h': H, 'fps': 24.0, 'dur': 2.0}


@needs_library
def test_full_compile_overlays_the_alpha_element_at_full_size():
    cam = _cam()
    pl = cam.place((W / 2.0, H * 0.85), 1.0, 0.0, 2.0, 6.0)
    pl.update({'start_s': 0.0, 'opacity': 1.0})
    ins, fc, label = V.compile(_ctx(), pl, V.element_for(DUST, False), False)
    assert 'overlay' in fc
    assert 'format=auto' in fc, 'the matte has to be composited as alpha'
    assert 'scale=320' not in fc, 'a bake is full resolution'
    assert ins[:2] == ['-stream_loop', '-1']
    assert '-c:v' in ins and 'libvpx-vp9' in ins, 'the native vp9 decoder drops the alpha track'
    assert label == '[vout]'


@needs_library
def test_draft_compile_shrinks_the_clip_to_320_and_screens_the_preview():
    cam = _cam()
    pl = cam.place((W / 2.0, H * 0.85), 1.0, 0.0, 2.0, 6.0)
    pl.update({'start_s': 0.0, 'opacity': 1.0})
    ins, fc, _ = V.compile(_ctx(), pl, V.element_for(DUST, True), True)
    assert 'scale=320' in fc, fc
    assert 'overlay' in fc
    assert 'blend=all_mode=screen' in fc, 'the preview is matted on near-black'
    assert 'libvpx-vp9' not in ins, 'a preview mp4 needs no vp9 decoder'


@needs_library
def test_the_draft_places_the_element_on_the_same_part_of_the_frame():
    """The whole point of a draft: 320 px wide is 320/832 of the picture, and
    the element's box has to shrink by exactly that much and no other."""
    cam = _cam()
    pl = cam.place((W / 2.0, H * 0.85), 1.0, 0.0, 2.0, 6.0)
    pl.update({'start_s': 0.0, 'opacity': 1.0})
    el = V.element_for(DUST, True)
    _, full, _ = V.compile(_ctx(), pl, el, False)
    _, draft, _ = V.compile(_ctx(), pl, el, True)

    def box(fc):
        import re

        s = re.search(r'scale=(\d+):(\d+):flags=bilinear,setsar=1,setpts', fc)
        o = re.search(r'overlay=x=(-?\d+):y=(-?\d+)', fc)
        return [int(g) for g in s.groups()] + [int(g) for g in o.groups()]

    k = V.DRAFT_WIDTH / float(W)
    for a, b in zip(box(full), box(draft)):
        assert abs(a * k - b) <= 1.5, (a, b, k)


@needs_library
def test_opacity_reaches_the_graph_both_ways():
    cam = _cam()
    pl = cam.place((W / 2.0, H * 0.85), 0, 0, 0, 6.0)
    pl.update({'start_s': 1.25, 'opacity': 0.5})
    _, full, _ = V.compile(_ctx(), pl, V.element_for(DUST, False), False)
    _, draft, _ = V.compile(_ctx(), pl, V.element_for(DUST, True), True)
    assert 'colorchannelmixer=aa=0.500' in full
    assert 'colorchannelmixer=rr=0.500:gg=0.500:bb=0.500' in draft
    assert 'setpts=PTS-STARTPTS+1.250/TB' in full


# ─────────────────────────────────────────────── the scene-shot camera
def test_a_scene_shot_camera_wins_over_the_dials(tmp_path):
    shot = tmp_path / 'shot_x'
    (shot / 'plates_raw').mkdir(parents=True)
    # 4.2 m up, aimed 10 m ahead and 2.2 m down → pitch = atan(2.2/10)
    (shot / 'plates_raw' / 'camera.json').write_text(
        '{"frames": [{"f": 1, "p": [0.0, 4.2, 0.0], "t": [0.0, 2.0, 10.0], "fov": 35.0}]}', encoding='utf-8'
    )
    cam = V.camera_from_scene_shot(str(shot), W, H)
    assert cam is not None
    assert cam.source == 'scene'
    assert abs(cam.height - 4.2) < 1e-9
    assert abs(cam.fov - 35.0) < 1e-9
    assert abs(cam.pitch - math.degrees(math.atan2(2.2, 10.0))) < 1e-6
    # and camera_for prefers it over the dialled fov/height
    got = V.camera_for({'scene_shot': str(shot), 'vfx_cam_fov': 90.0, 'vfx_cam_height': 1.0}, W, H)
    assert got.source == 'scene' and abs(got.fov - 35.0) < 1e-9


def test_no_scene_shot_falls_back_to_the_dials():
    cam = V.camera_for({'vfx_cam_fov': 70.0, 'vfx_cam_height': 2.5, 'vfx_cam_pitch': -3.0}, W, H)
    assert cam.source == 'dials'
    assert (cam.fov, cam.height, cam.pitch) == (70.0, 2.5, -3.0)


def test_placement_for_reads_the_studio_params():
    cam = _cam()
    pl = V.placement_for(
        {'vfx_anchor': '0.25,0.90', 'vfx_offset': '1.5,0,3', 'vfx_size_m': 8.0, 'vfx_start_s': 2.0, 'vfx_opacity': 0.4},
        cam,
    )
    assert pl['anchor'] == [0.25, 0.90] and pl['offset_m'] == [1.5, 0.0, 3.0]
    assert pl['size_m'] == 8.0 and pl['start_s'] == 2.0 and pl['opacity'] == 0.4
    assert pl['visible'] and pl['depth'] > 0


# ───────────────────────────────────────────────────── the real draft
@pytest.fixture(scope='module')
def clip(tmp_path_factory):
    out = str(tmp_path_factory.mktemp('vfx') / 'src.mp4')
    r = subprocess.run(
        [
            'ffmpeg',
            '-y',
            '-v',
            'error',
            '-f',
            'lavfi',
            '-i',
            f'testsrc=size={W}x{H}:rate=24:duration=2',
            '-c:v',
            'libx264',
            '-preset',
            'ultrafast',
            '-pix_fmt',
            'yuv420p',
            out,
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    return out


def _probe_size(path):
    r = subprocess.run(
        [
            'ffprobe',
            '-v',
            'error',
            '-select_streams',
            'v:0',
            '-show_entries',
            'stream=width,height',
            '-of',
            'csv=p=0',
            path,
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    return [int(x) for x in r.stdout.strip().split(',')[:2]]


@needs_library
def test_a_draft_of_a_2s_clip_is_320_wide_and_takes_under_8_seconds(clip, tmp_path):
    out = str(tmp_path / 'draft.mp4')
    params = {
        'vfx_element': DUST,
        'vfx_anchor': '0.50,0.85',
        'vfx_offset': '1.0,0.0,2.0',
        'vfx_size_m': 6.0,
        'vfx_cam_fov': FOV,
        'vfx_cam_height': CAM_H,
        'vfx_cam_pitch': 0.0,
        'vfx_start_s': 0.0,
        'vfx_opacity': 1.0,
    }
    t0 = time.time()
    secs = V.draft(clip, params, out)
    wall = time.time() - t0
    assert os.path.isfile(out)
    assert _probe_size(out)[0] == 320
    assert secs < 8.0 and wall < 8.0, f'{secs:.2f}s / {wall:.2f}s'
    # and it actually composited something onto the picture
    assert os.path.getsize(out) > 1000


@needs_library
def test_a_draft_refuses_an_anchor_in_the_sky(clip, tmp_path):
    params = {
        'vfx_element': DUST,
        'vfx_anchor': '0.50,0.05',
        'vfx_cam_fov': FOV,
        'vfx_cam_height': CAM_H,
        'vfx_cam_pitch': 0.0,
    }
    with pytest.raises(ValueError, match='horizon'):
        V.draft(clip, params, str(tmp_path / 'sky.mp4'))


@needs_library
def test_plan_reports_the_camera_source_without_rendering(clip):
    rec = V.plan(clip, {'vfx_element': DUST}, draft=True)
    assert rec['cam_source'] == 'dials'
    assert rec['clip']['w'] == W and rec['clip']['h'] == H
    assert rec['element']['mode'] == 'preview'
    assert rec['placement']['visible']


# ───────────────────────────────────────────── the Video Studio contract
@needs_library
def test_the_studio_rack_carries_every_dial_the_module_reads():
    from zyg_workflows import video_studio as VS

    keys = {p['key'] for r in VS.RACKS if r['id'] == 'vfx' for p in r['params']}
    assert keys == {
        'vfx_element',
        'vfx_anchor',
        'vfx_offset',
        'vfx_size_m',
        'vfx_cam_fov',
        'vfx_cam_height',
        'vfx_cam_pitch',
        'vfx_start_s',
        'vfx_opacity',
    }
    assert any(a['id'] == 'vfx_draft' for a in VS.ACTIONS)
    # sanitize keeps them and refuses an element that is not in the library
    s = VS.sanitize({'vfx_element': DUST, 'vfx_size_m': 9999, 'vfx_opacity': -2})
    assert s['vfx_element'] == DUST
    assert s['vfx_size_m'] == 200.0 and s['vfx_opacity'] == 0.0
    assert VS.sanitize({'vfx_element': 'nope'})['vfx_element'] == 'none'
    assert VS.defaults()['vfx_element'] == 'none'
