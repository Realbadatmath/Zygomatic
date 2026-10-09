# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The pure helpers Stage 4b's clip renderer was split into.

`_make_render_clip` was one 324-line closure factory, so none of the arithmetic
below had ever been reachable from a test: the SRT cue timing, the title
fallback chain, the filename sanitising, the fade filter chains and the two
ffmpeg command lines were all inline in the body that shells out to ffmpeg.
They are `stage4b_render_clip` functions now, and these are their first unit
tests. Nothing here touches ffmpeg, the GPU or the network.
"""

import os

from zyg_workflows.stage_runner import stage4b_render as sr
from zyg_workflows.stage_runner import stage4b_render_clip as rc


def test_a_cue_clock_reading_is_srt_hh_mm_ss_comma_millis():
    assert rc._srt_timestamp(0.0) == '00:00:00,000'
    assert rc._srt_timestamp(3661.5) == '01:01:01,500'
    assert rc._srt_timestamp(59.999) == '00:00:59,999'
    # the millisecond field truncates, it does not round, so a cue never
    # advertises itself as starting later than it does
    assert rc._srt_timestamp(1.0009) == '00:00:01,000'


def test_cues_are_numbered_from_one_and_timed_off_the_clip_start():
    segs = [
        {'start': 100.0, 'end': 101.0, 'text': 'first'},
        {'start': 102.0, 'end': 103.0, 'text': 'second'},
    ]
    cues = rc.srt_cue_lines(segs, 100.0, 10.0)
    assert len(cues) == 2
    assert cues[0].startswith('1\n00:00:00,000 --> ')
    assert cues[0].endswith('first\n')
    # the 0.8 s hold fits inside the gap to the next cue, so cue 1 ends at 1.8 s
    assert '--> 00:00:01,800\n' in cues[0]
    # the last cue has nothing after it and gets the full hold (3.0 + 0.8,
    # one millisecond short of 3.800 because the field truncates a binary float)
    assert cues[1].startswith('2\n00:00:02,000 --> 00:00:03,799\n')


def test_the_hold_is_cut_short_rather_than_overlap_the_next_cue():
    segs = [
        {'start': 0.0, 'end': 1.0, 'text': 'first'},
        {'start': 1.5, 'end': 2.5, 'text': 'second'},
    ]
    cues = rc.srt_cue_lines(segs, 0.0, 10.0)
    # 1.0 + 0.8 would run past 1.5, so the cue stops 0.05 s before it
    assert cues[0].startswith('1\n00:00:00,000 --> 00:00:01,449\n')


def test_a_cue_is_never_shorter_than_three_tenths_of_a_second():
    segs = [
        {'start': 0.0, 'end': 0.05, 'text': 'blink'},
        {'start': 0.1, 'end': 1.0, 'text': 'next'},
    ]
    cues = rc.srt_cue_lines(segs, 0.0, 10.0)
    # min(0.85, 0.05) is below the floor, so the floor wins
    assert cues[0].startswith('1\n00:00:00,000 --> 00:00:00,300\n')


def test_cues_skip_segments_outside_the_window_and_blank_text():
    segs = [
        {'start': 0.0, 'end': 1.0, 'text': 'before'},
        {'start': 50.0, 'end': 51.0, 'text': '   '},
        {'start': 52.0, 'end': 53.0, 'text': 'kept'},
        {'start': 900.0, 'end': 901.0, 'text': 'after'},
    ]
    cues = rc.srt_cue_lines(segs, 40.0, 20.0)
    assert len(cues) == 1
    assert cues[0].startswith('1\n')
    assert cues[0].endswith('kept\n')


def test_a_window_nothing_overlaps_has_no_cues():
    assert rc.srt_cue_lines([{'start': 0.0, 'end': 1.0, 'text': 'x'}], 500.0, 10.0) == []


def test_the_title_falls_back_from_director_to_youtube_to_the_channel():
    assert rc.clip_title_source('Director Title', 'chan', 'YT Title', 0) == 'Director Title'
    assert rc.clip_title_source('', 'chan', 'YT Title', 0) == 'YT Title'
    assert rc.clip_title_source(None, 'chan', '', 2) == 'chan clip 3'
    assert rc.clip_title_source('', '', '', 4) == 'clip_5'


def test_the_filename_drops_path_characters_and_caps_the_stem_at_80(tmp_path):
    p = rc.clip_output_path(str(tmp_path), 'Why: a/b "thing"? *now*', 0)
    assert os.path.dirname(p) == str(tmp_path)
    assert os.path.basename(p) == 'Why_ab_thing_now.mp4'
    long_stem = os.path.basename(rc.clip_output_path(str(tmp_path), 'x' * 200, 0))
    assert long_stem == 'x' * 80 + '.mp4'


def test_an_existing_filename_gets_the_clip_number_appended(tmp_path):
    first = rc.clip_output_path(str(tmp_path), 'Same Title', 0)
    open(first, 'w').close()
    second = rc.clip_output_path(str(tmp_path), 'Same Title', 1)
    assert second != first
    assert os.path.basename(second) == 'Same_Title_2.mp4'


def test_the_filters_letterbox_to_1080p30_and_fade_out_half_a_second_early():
    vf, af = rc.clip_filters(600.0)
    assert vf == (
        'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30,'
        'fade=t=in:st=0:d=0.5,fade=t=out:st=599.500:d=0.5'
    )
    assert af == 'afade=t=in:st=0:d=0.5,afade=t=out:st=599.500:d=0.5'


def test_both_command_lines_share_the_input_half_and_differ_only_in_the_codec():
    args = (['taskset', '-c', '0-19'], 12.5, '/src/v.mp4', 480.0, 'VF', 'AF', '/out/c.mp4')
    gpu, cpu = rc.nvenc_cmd(*args), rc.cpu_cmd(*args)
    head = ['taskset', '-c', '0-19']
    assert gpu[:3] == head and cpu[:3] == head
    shared = ['-y', '-ss', '12.5', '-i', '/src/v.mp4', '-t', '480.0', '-vf', 'VF', '-af', 'AF']
    assert gpu[4:15] == shared
    assert cpu[4:15] == shared
    assert gpu[15:19] == ['-c:v', 'h264_nvenc', '-preset', 'p4']
    assert cpu[15:19] == ['-c:v', 'libx264', '-preset', 'veryfast']
    assert gpu[-1] == cpu[-1] == '/out/c.mp4'
    assert gpu[-2:] == ['1', '/out/c.mp4'] and gpu[-3] == '-threads'
    assert cpu[-2:] == ['2', '/out/c.mp4'] and cpu[-3] == '-threads'


def test_the_factory_binds_every_name_the_old_closure_read():
    job_fields = set(rc.RenderClipJob.__dataclass_fields__)
    assert len(job_fields) == 14
    bound = sr._make_render_clip(
        'dur', 'err', 'info', 'warn', {'nl': 1}, 'post', {'qm': 2}, 'snap', {'ch': 3}, {'mt': 4}, '/out', 7, [], None
    )
    job = bound.args[0]
    assert isinstance(job, rc.RenderClipJob)
    assert (job.out_dir, job.pipeline_id, job.processed) == ('/out', 7, [])
    assert (job.log_err, job.log_info, job.log_warn) == ('err', 'info', 'warn')
    assert job.vid_channel_map == {'ch': 3} and job.vid_meta_titles == {'mt': 4}
    assert bound.func is sr._render_clip
