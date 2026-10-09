# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the finishing stages `_post_process` orchestrates.

Every helper under test used to be a block inside the 428-line
`ffmpeg_finish._post_process`, so none of this logic had ever been exercised on
its own. The filtergraph builders are pure — they take the sanitised parameter
dict and return the filter links plus the words the finish log is made of — so
these run with no ffmpeg, no GPU and no services.
"""

import os

import pytest

from zyg_workflows import video_studio
from zyg_workflows.video_studio import ffmpeg_finish_post as fp


def _p(**over):
    """A sanitised Video Studio parameter dict with the named dials changed."""
    return video_studio.sanitize(dict(over))


# ── _timeline_chain ────────────────────────────────────────────────────────


def test_timeline_chain_is_empty_at_the_defaults():
    chain, notes, w, h, eff_speed = fp._timeline_chain(_p(), '', 1920, 1080)
    assert chain == []
    assert notes == []
    assert (w, h) == (1920, 1080)
    assert eff_speed == 1.0


def test_timeline_chain_holds_the_frame_before_anything_else():
    chain, notes, _w, _h, _s = fp._timeline_chain(_p(hold_head=0.5, hold_tail=1.0, reverse=True), '', 1920, 1080)
    assert chain[0] == 'tpad=start_mode=clone:start_duration=0.50:stop_mode=clone:stop_duration=1.00'
    assert chain[1] == 'reverse'
    assert notes[0] == 'hold 0.5s+1s'


def test_timeline_chain_puts_the_colour_match_before_the_grade_dials():
    chain, notes, _w, _h, _s = fp._timeline_chain(_p(deflicker=True), 'lutrgb=r=val', 1920, 1080)
    assert chain == ['lutrgb=r=val', 'deflicker=size=5:mode=am']
    assert notes == ['colour match', 'deflicker']


def test_timeline_chain_folds_speed_and_fast_forward_into_one_setpts():
    chain, notes, _w, _h, eff_speed = fp._timeline_chain(_p(speed=2.0, speed_x='20'), '', 1920, 1080)
    assert eff_speed == 40.0
    assert chain == ['setpts=0.025000*PTS'], 'one setpts only, or eff_dur stops being computable'
    assert notes == ['speed 40x']


def test_timeline_chain_resample_reports_the_new_even_frame_size():
    chain, notes, w, h, _s = fp._timeline_chain(_p(resample='1.5'), '', 1919, 1081)
    assert (w, h) == (2878, 1620), 'both sides are rounded down to even'
    assert chain == ['scale=2878:1620:flags=lanczos']
    assert notes == ['resample 1.5x -> 2878x1620']


def test_timeline_chain_skips_the_resample_when_the_probe_found_no_size():
    chain, _n, w, h, _s = fp._timeline_chain(_p(resample='1.5'), '', 0, 0)
    assert chain == []
    assert (w, h) == (0, 0)


# ── _geometry_chain ────────────────────────────────────────────────────────


def test_geometry_chain_is_empty_at_the_defaults():
    assert fp._geometry_chain(_p(), 1920, 1080, 6.0, 'black') == ([], [])


def test_geometry_chain_punch_in_pans_across_the_slack_the_zoom_made():
    chain, notes = fp._geometry_chain(_p(crop_zoom=1.5, pan_x=1.0, pan_y=-1.0), 1000, 500, 6.0, 'black')
    # 1.5x of 1000x500 is 1500x750; pan_x=+1 uses all the slack, pan_y=-1 none
    assert chain == ['scale=1500:750:flags=lanczos,crop=1000:500:500:0']
    assert notes == ['punch in 1.5x']


def test_geometry_chain_ken_burns_in_zooms_by_one_step_per_frame():
    chain, notes = fp._geometry_chain(_p(ken_burns='in', ken_burns_amount=0.2, fps=25), 1920, 1080, 4.0, 'black')
    # 4 s at 25 fps is 100 frames, so the per-frame step is 0.2/100
    assert chain == [
        "zoompan=z='min(zoom+0.002000,1.2000)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1920x1080:fps=25"
    ]
    assert notes == ['post move in 0.2']


def test_geometry_chain_ken_burns_travel_holds_the_zoom_and_moves_x():
    chain, _n = fp._geometry_chain(_p(ken_burns='right', ken_burns_amount=0.3, fps=10), 640, 480, 2.0, 'black')
    assert chain[0].startswith("zoompan=z='1.3000':x='(iw-iw/zoom)*(on/20)'")


def test_geometry_chain_rotate_pads_with_the_pad_colour_and_crops_back():
    chain, notes = fp._geometry_chain(_p(rotate=15.0), 1920, 1080, 6.0, '#123456')
    assert chain[0] == 'rotate=0.26180:fillcolor=#123456'
    # cos15 + sin15 = 1.2247, so the frame is zoomed back in past the corners
    assert chain[1] == 'scale=2350:1322:flags=lanczos,crop=1920:1080'
    assert notes == ['rotate 15deg']


def test_geometry_chain_flips_come_last_and_in_h_then_v_order():
    chain, notes = fp._geometry_chain(_p(flip_h=True, flip_v=True), 1920, 1080, 6.0, 'black')
    assert chain == ['hflip', 'vflip']
    assert notes == ['flip h', 'flip v']


# ── _look_chain ────────────────────────────────────────────────────────────


def test_look_chain_puts_the_named_grade_before_the_grade_rack():
    chain, notes = fp._look_chain(_p(grade='mono', saturation=1.4), 1920, 1080, 'black')
    assert chain == ['hue=s=0', 'eq=saturation=1.400']
    assert notes == ['grade mono', 'saturation 1.4']


def test_look_chain_ignores_a_grade_name_it_does_not_know():
    assert fp._look_chain(_p(grade='none'), 1920, 1080, 'black') == ([], [])


def test_look_chain_letterbox_narrower_than_source_crops_the_width():
    chain, notes = fp._look_chain(_p(letterbox='1.0'), 1920, 1080, 'grey')
    assert chain == ['crop=1080:1080,pad=1920:1080:420:0:grey']
    assert notes == ['matte 1.0']


def test_look_chain_letterbox_wider_than_source_mattes_the_height():
    chain, _n = fp._look_chain(_p(letterbox='2.39'), 1920, 1080, 'grey')
    assert chain == ['crop=1920:802,pad=1920:1080:0:139:grey']


def test_look_chain_vignette_maps_the_dial_across_the_falloff_range():
    chain, _n = fp._look_chain(_p(vignette=1.0), 1920, 1080, 'black')
    assert chain == ['vignette=angle=1.3090'], 'the dial at 1 is the heavy PI/2.4 falloff'


# ── _rate_chain ────────────────────────────────────────────────────────────


def test_rate_chain_leaves_the_rate_alone_when_rife_already_conformed_it():
    assert fp._rate_chain(_p(interpolate='60', interp_mode='rife'), True, 1.0) == ([], [])


def test_rate_chain_conforms_without_synthesising_when_rife_failed():
    chain, notes = fp._rate_chain(_p(interpolate='60', interp_mode='rife'), False, 1.0)
    assert chain == ['fps=60']
    assert notes == ['conform 60fps (RIFE unavailable, no frames synthesised)']
    assert 'minterpolate' not in ''.join(chain), 'minterpolate is not a silent substitute for RIFE'


def test_rate_chain_uses_minterpolate_for_every_other_interp_mode():
    chain, notes = fp._rate_chain(_p(interpolate='60', interp_mode='mci'), False, 1.0)
    assert chain == ['minterpolate=fps=60:mi_mode=mci']
    assert notes == ['interpolate 60fps/mci']


def test_rate_chain_out_fps_only_wins_when_interpolation_is_off():
    assert fp._rate_chain(_p(out_fps='24'), False, 1.0) == (['fps=24'], ['conform 24fps'])
    chain, _n = fp._rate_chain(_p(out_fps='24', interpolate='60', interp_mode='mci'), False, 1.0)
    assert chain == ['minterpolate=fps=60:mi_mode=mci']


def test_rate_chain_drops_a_fast_forward_back_to_the_render_rate():
    chain, notes = fp._rate_chain(_p(fps=16), False, 30.0)
    assert chain == ['fps=16'], 'setpts alone would carry 480 fps timestamps'
    assert notes == ['conform 16fps after speed']
    assert fp._rate_chain(_p(fps=16), False, 2.0) == ([], []), '2x and under keeps the stretched rate'


# ── _burn_in_chain ─────────────────────────────────────────────────────────


def test_burn_in_chain_escapes_the_watermark_and_places_it():
    chain, notes = fp._burn_in_chain(_p(watermark="  a:b'c%  ", watermark_pos='tl'))
    if not os.path.isfile(fp._FONT):  # no bundled font, nothing to draw with
        assert (chain, notes) == ([], [])
        return
    assert notes == ['burn-in text']
    assert r"text='a\:b\'c\%'" in chain[0], 'drawtext parses :, \\, quote and %'
    assert chain[0].endswith(':x=24:y=24'), 'tl is the top-left safe margin'


def test_burn_in_chain_falls_back_to_the_bottom_right_for_an_unknown_corner():
    chain, _n = fp._burn_in_chain(_p(watermark='x', watermark_pos='nowhere'))
    if not os.path.isfile(fp._FONT):
        return
    assert chain[0].endswith(':x=w-tw-24:y=h-th-24')


def test_burn_in_chain_is_empty_without_a_watermark_or_a_timecode():
    assert fp._burn_in_chain(_p()) == ([], [])
    assert fp._burn_in_chain(_p(watermark='   ')) == ([], [])


# ── _fade_chain ────────────────────────────────────────────────────────────


def test_fade_chain_measures_the_duration_after_hold_trim_and_speed():
    _c, _n, eff_dur = fp._fade_chain(
        _p(hold_head=1.0, hold_tail=1.0, trim_head=0.5, trim_tail=0.5, speed=2.0), 6.0, 2.0
    )
    assert eff_dur == 3.5, '6 + 2 - 1 held/trimmed, then halved by the 2x speed'


def test_fade_chain_places_the_fade_out_against_that_duration():
    chain, notes, eff_dur = fp._fade_chain(_p(fade_in=0.5, fade_out=1.0, fade_color='white'), 6.0, 1.0)
    assert eff_dur == 6.0
    assert chain == ['fade=t=in:st=0:d=0.50:color=white', 'fade=t=out:st=5.00:d=1.00:color=white']
    assert notes == ['fade in 0.5s', 'fade out 1s']


def test_fade_chain_skips_a_fade_out_longer_than_the_clip():
    chain, notes, _d = fp._fade_chain(_p(fade_out=2.0), 1.0, 1.0)
    assert chain == []
    assert notes == []


def test_fade_chain_never_divides_by_a_zero_speed():
    _c, _n, eff_dur = fp._fade_chain(_p(), 6.0, 0.0)
    assert eff_dur == 600.0, 'the speed floor is 0.01, not 0'


# ── filter_chain, the six blocks as one filtergraph ───────────────────────


def test_filter_chain_is_empty_at_the_defaults():
    chain, notes, w, h, eff_dur = fp.filter_chain(_p(), '', 1920, 1080, 6.0, False, 'black')
    assert (chain, notes) == ([], []), 'a defaults-only render carries no filtergraph'
    assert (w, h, eff_dur) == (1920, 1080, 6.0)


def test_filter_chain_keeps_the_blocks_in_the_order_they_compose_in():
    chain, notes, _w, _h, _d = fp.filter_chain(
        _p(reverse=True, flip_h=True, sharpen=0.5, fade_in=0.5), '', 1920, 1080, 6.0, False, 'black'
    )
    # timeline, then geometry, then the look, then the burn-ins, then the fades
    assert chain.index('reverse') < chain.index('hflip') < len(chain) - 1
    assert chain[-1].startswith('fade=t=in')
    assert notes[0] == 'reverse' and notes[-1] == 'fade in 0.5s'


def test_filter_chain_sizes_the_later_blocks_off_the_resample():
    # the resample doubles 1920x1080, and the rotate cover is computed off that
    chain, _n, w, h, _d = fp.filter_chain(_p(resample='2', rotate=15.0), '', 1920, 1080, 6.0, False, 'black')
    assert (w, h) == (3840, 2160)
    assert 'scale=4702:2644:flags=lanczos,crop=3840:2160' in chain


def test_filter_chain_hands_back_the_duration_the_fades_were_placed_against():
    _c, _n, _w, _h, eff_dur = fp.filter_chain(_p(speed=2.0), '', 1920, 1080, 6.0, False, 'black')
    assert eff_dur == 3.0, 'the audio mix falls back on the post-speed length'


# ── _encode_plan ───────────────────────────────────────────────────────────


def test_encode_plan_at_the_defaults_needs_no_encode_at_all():
    plan = fp._encode_plan(_p(), [])
    assert plan.delivery_default is True
    # falsy, not literally False: the last term of the or-chain is p['x_tune'], ''
    assert not plan.reencode, 'a defaults-only render must still produce the same bytes'
    assert plan.master_crf == 20
    assert (plan.vcodec, plan.ext) == ('libx264', '.mp4')


def test_encode_plan_a_filtergraph_alone_earns_the_encode():
    assert fp._encode_plan(_p(), ['hflip']).reencode is True


def test_encode_plan_a_trim_alone_earns_the_encode():
    plan = fp._encode_plan(_p(trim_tail=0.5), [])
    assert plan.trimming is True
    assert plan.reencode is True


def test_encode_plan_goes_near_lossless_when_a_post_pass_will_re_encode():
    assert fp._encode_plan(_p(crf=20, bloom=0.3), []).master_crf == 12
    assert fp._encode_plan(_p(crf=20, loop_mode='pingpong'), []).master_crf == 12
    assert fp._encode_plan(_p(crf=10, bloom=0.3), []).master_crf == 10, 'a lower dial is already better than 12'


def test_encode_plan_another_codec_or_container_is_a_second_encode():
    h265 = fp._encode_plan(_p(codec='h265'), [])
    assert (h265.vcodec, h265.delivery_default, h265.master_crf) == ('libx265', False, 12)
    mkv = fp._encode_plan(_p(container='mkv'), [])
    assert (mkv.ext, mkv.delivery_default) == ('.mkv', False)
    assert fp._encode_plan(_p(rate_mode='bitrate'), []).delivery_default is False


def test_encode_plan_falls_back_to_x264_mp4_for_an_unknown_dial():
    plan = fp._encode_plan(_p(), [])
    assert fp._encode_plan({**plan.__dict__, **_p(), 'codec': 'xyz', 'container': 'xyz'}, []).vcodec == 'libx264'


# ── _master_args ───────────────────────────────────────────────────────────


def test_master_args_seeks_the_trim_on_the_input():
    args = fp._master_args('in.mp4', 'out.mp4', _p(trim_head=1.5, trim_tail=0.5), [], 6.0, 20)
    assert args[args.index('-ss') + 1] == '1.500'
    assert args[args.index('-to') + 1] == '5.500'
    assert args.index('-ss') < args.index('-i'), 'the decoder seeks, the graph does not discard'


def test_master_args_leaves_the_tail_trim_out_with_no_probed_duration():
    args = fp._master_args('in.mp4', 'out.mp4', _p(trim_tail=0.5), [], 0.0, 20)
    assert '-to' not in args


def test_master_args_joins_the_filtergraph_with_commas():
    args = fp._master_args('in.mp4', 'out.mp4', _p(), ['hflip', 'vflip'], 6.0, 20)
    assert args[args.index('-vf') + 1] == 'hflip,vflip'


def test_master_args_carries_the_preset_tune_crf_and_faststart():
    args = fp._master_args('in.mp4', 'out.mp4', _p(x_preset='slow', x_tune='film', pix_fmt='yuv444p'), [], 6.0, 12)
    assert args[args.index('-preset') + 1] == 'slow'
    assert args[args.index('-tune') + 1] == 'film'
    assert args[args.index('-crf') + 1] == '12'
    assert args[args.index('-pix_fmt') + 1] == 'yuv444p'
    assert args[-2:] == ['+faststart', 'out.mp4']


def test_master_args_always_encodes_the_master_as_x264():
    args = fp._master_args('in.mp4', 'out.mp4', _p(codec='prores'), [], 6.0, 20)
    assert args[args.index('-c:v') + 1] == 'libx264', 'the preview player needs an mp4 master'


# ── _delivery_args / _delivery_path ─────────────────────────────────────────


def test_delivery_path_names_the_file_by_codec_as_well_as_container():
    assert fp._delivery_path('/a/clip.mp4', _p(codec='h265'), '.mp4') == '/a/clip.h265.mp4'


def test_delivery_args_lifts_prores_off_a_420_pixel_format():
    plan = fp._encode_plan(_p(codec='prores', container='mov'), [])
    args = fp._delivery_args('in.mp4', 'out.mov', _p(codec='prores', pix_fmt='yuv420p'), plan)
    assert args[args.index('-pix_fmt') + 1] == 'yuv422p10le', 'ProRes has no 4:2:0 profile'
    assert args[args.index('-profile:v') + 1] == '3'
    assert '-crf' not in args and '-preset' not in args


def test_delivery_args_gives_vp9_its_zero_bitrate_beside_the_crf():
    plan = fp._encode_plan(_p(codec='vp9', container='webm'), [])
    args = fp._delivery_args('in.mp4', 'out.webm', _p(codec='vp9', crf=31), plan)
    assert args[args.index('-crf') + 1] == '31'
    assert args[args.index('-b:v') + 1] == '0'


def test_delivery_args_uses_a_bitrate_when_the_rate_mode_asks_for_one():
    plan = fp._encode_plan(_p(codec='h265', rate_mode='bitrate', bitrate=9000), [])
    args = fp._delivery_args('in.mp4', 'out.mp4', _p(codec='h265', rate_mode='bitrate', bitrate=9000), plan)
    assert args[args.index('-b:v') + 1] == '9000k'
    assert '-crf' not in args


def test_delivery_args_only_faststarts_a_container_that_has_a_moov_atom():
    plan = fp._encode_plan(_p(codec='vp9', container='webm'), [])
    assert '-movflags' not in fp._delivery_args('in.mp4', 'out.webm', _p(codec='vp9'), plan)


def test_delivery_encode_writes_nothing_when_the_master_is_the_delivery(monkeypatch):
    calls = []
    monkeypatch.setattr(fp._ff, '_run_ff', lambda *a, **k: calls.append(a) or True)
    assert fp.delivery_encode('/a/clip.mp4', _p(), print, fp._encode_plan(_p(), [])) == ''
    assert calls == []


def test_delivery_encode_returns_the_path_it_wrote(monkeypatch):
    lines = []
    monkeypatch.setattr(fp._ff, '_run_ff', lambda *a, **k: True)
    plan = fp._encode_plan(_p(codec='h265'), [])
    assert fp.delivery_encode('/a/clip.mp4', _p(codec='h265'), lines.append, plan) == '/a/clip.h265.mp4'
    assert lines == ['finish: delivery clip.h265.mp4 (h265) written from the finished mp4']


def test_delivery_encode_returns_nothing_when_ffmpeg_failed(monkeypatch):
    monkeypatch.setattr(fp._ff, '_run_ff', lambda *a, **k: False)
    plan = fp._encode_plan(_p(codec='h265'), [])
    assert fp.delivery_encode('/a/clip.mp4', _p(codec='h265'), print, plan) == ''


# ── encode_master ─────────────────────────────────────────────────────────


def test_encode_master_logs_the_notes_and_replaces_the_render(monkeypatch, tmp_path):
    clip = tmp_path / 'clip.mp4'
    clip.write_bytes(b'raw')
    (tmp_path / 'clip.mp4.fin.mp4').write_bytes(b'finished')
    lines = []
    monkeypatch.setattr(fp._ff, '_run_ff', lambda *a, **k: True)
    plan, ok = fp.encode_master(str(clip), _p(), lines.append, ['hflip'], ['flip h'], 6.0)
    assert ok is True
    assert plan == fp._encode_plan(_p(), ['hflip']), 'the plan it acted on is the one it hands back'
    assert clip.read_bytes() == b'finished'
    assert lines == ['finish: flip h']


def test_encode_master_says_trim_encode_only_when_there_are_no_notes(monkeypatch, tmp_path):
    clip = tmp_path / 'clip.mp4'
    clip.write_bytes(b'raw')
    (tmp_path / 'clip.mp4.fin.mp4').write_bytes(b'finished')
    lines = []
    monkeypatch.setattr(fp._ff, '_run_ff', lambda *a, **k: True)
    fp.encode_master(str(clip), _p(trim_head=1.0), lines.append, [], [], 6.0)
    assert lines == ['finish: trim/encode only']


def test_encode_master_keeps_the_un_finished_render_on_failure(monkeypatch, tmp_path):
    clip = tmp_path / 'clip.mp4'
    clip.write_bytes(b'raw')
    lines = []
    monkeypatch.setattr(fp._ff, '_run_ff', lambda *a, **k: False)
    assert fp.encode_master(str(clip), _p(), lines.append, ['hflip'], ['flip h'], 6.0)[1] is False
    assert clip.read_bytes() == b'raw'
    assert lines == ['finish: post chain failed — keeping the un-finished render']


def test_encode_master_at_the_defaults_runs_no_ffmpeg_at_all(monkeypatch, tmp_path):
    clip = tmp_path / 'clip.mp4'
    clip.write_bytes(b'raw')
    lines = []
    monkeypatch.setattr(fp._ff, '_run_ff', lambda *a, **k: pytest.fail('the render already IS the master'))
    plan, ok = fp.encode_master(str(clip), _p(), lines.append, [], [], 6.0)
    assert (ok, plan.reencode, lines) == (True, '', [])
    assert clip.read_bytes() == b'raw'


# ── the passes that are not a filter link ─────────────────────────────────


def test_bloom_and_loop_runs_neither_at_the_defaults(monkeypatch):
    calls = []
    monkeypatch.setattr(fp._ff, '_bloom_pass', lambda *a, **k: calls.append('bloom') or True)
    monkeypatch.setattr(fp._ff, '_loop_pass', lambda *a, **k: calls.append('loop') or True)
    fp.bloom_and_loop('/a/clip.mp4', _p(), print, 20)
    assert calls == []


def test_bloom_and_loop_runs_bloom_before_the_loop(monkeypatch, tmp_path):
    clip = tmp_path / 'clip.mp4'
    clip.write_bytes(b'raw')
    calls, lines = [], []

    def bloom(src, dst, amount, log, crf=12):
        calls.append(('bloom', amount, crf))
        open(dst, 'wb').write(b'bloomed')
        return True

    def loop(src, dst, mode, log):
        calls.append(('loop', mode))
        open(dst, 'wb').write(b'looped')
        return True

    monkeypatch.setattr(fp._ff, '_bloom_pass', bloom)
    monkeypatch.setattr(fp._ff, '_loop_pass', loop)
    fp.bloom_and_loop(str(clip), _p(bloom=0.4, loop_mode='pingpong'), lines.append, 12)
    assert calls == [('bloom', 0.4, 12), ('loop', 'pingpong')]
    assert clip.read_bytes() == b'looped'
    assert lines == ['finish: bloom 0.4', 'finish: loop pingpong']


def test_bloom_and_loop_keeps_the_clip_when_a_pass_produced_nothing(monkeypatch, tmp_path):
    clip = tmp_path / 'clip.mp4'
    clip.write_bytes(b'raw')
    monkeypatch.setattr(fp._ff, '_bloom_pass', lambda *a, **k: False)
    lines = []
    fp.bloom_and_loop(str(clip), _p(bloom=0.4), lines.append, 12)
    assert clip.read_bytes() == b'raw'
    assert lines == []


# ── _overlay_layers ────────────────────────────────────────────────────────


def test_overlay_layers_is_empty_with_no_placement_record():
    assert fp._overlay_layers(_p(), print) == ({}, None)


def test_overlay_layers_reads_the_layers_out_of_the_record():
    rec, layers = fp._overlay_layers(_p(overlay_record='{"layers": [{"id": "a"}, {"id": "b"}]}'), print)
    assert layers == [{'id': 'a'}, {'id': 'b'}]
    assert rec['layers'] is layers


def test_overlay_layers_treats_unreadable_json_as_no_overlay():
    lines = []
    # sanitize() would turn the broken record into '{}', so it is set past it:
    # the guard exists for a record that reaches the finish by another route.
    assert fp._overlay_layers({**_p(), 'overlay_record': '{not json'}, lines.append) == ({}, None)
    assert len(lines) == 1
    assert lines[0].startswith('overlay unavailable: unreadable placement record (')


def test_overlay_layers_ignores_a_record_that_is_not_an_object():
    assert fp._overlay_layers(_p(overlay_record='[1, 2]'), print) == ([1, 2], None)


# ── pre_passes ────────────────────────────────────────────────────────────


def test_pre_passes_does_nothing_and_reports_no_rife_at_the_defaults(monkeypatch):
    calls = []
    monkeypatch.setattr(fp._ff, '_stabilize', lambda *a: calls.append('stab') or True)
    assert fp.pre_passes('/a/clip.mp4', _p(), print) is False
    assert calls == []


def test_pre_passes_stabilises_in_place_and_logs_it(monkeypatch, tmp_path):
    clip = tmp_path / 'clip.mp4'
    clip.write_bytes(b'shaky')
    lines = []

    def stabilize(src, dst, log):
        open(dst, 'wb').write(b'steady')
        return True

    monkeypatch.setattr(fp._ff, '_stabilize', stabilize)
    assert fp.pre_passes(str(clip), _p(stabilize=True), lines.append) is False
    assert clip.read_bytes() == b'steady'
    assert lines == ['finish: stabilised']


def test_pre_passes_keeps_the_render_when_the_stabiliser_failed(monkeypatch, tmp_path):
    clip = tmp_path / 'clip.mp4'
    clip.write_bytes(b'shaky')
    lines = []
    monkeypatch.setattr(fp._ff, '_stabilize', lambda *a: False)
    fp.pre_passes(str(clip), _p(stabilize=True), lines.append)
    assert clip.read_bytes() == b'shaky'
    assert lines == ['finish: stabilise skipped (see error above)']


def test_pre_passes_reports_no_rife_when_the_module_is_unavailable():
    lines = []
    # video_finish.rife_2x has no model on a CPU box: the pass must log one line
    # and leave the clip it was handed intact rather than lose the render.
    assert fp.pre_passes('/nonexistent/clip.mp4', _p(interpolate='60', interp_mode='rife'), lines.append) is False
    assert len(lines) == 1
    assert lines[0].startswith('rife unavailable: ')


def test_pre_passes_does_not_try_rife_for_another_interp_mode():
    lines = []
    assert fp.pre_passes('/nonexistent/clip.mp4', _p(interpolate='60', interp_mode='mci'), lines.append) is False
    assert lines == []
