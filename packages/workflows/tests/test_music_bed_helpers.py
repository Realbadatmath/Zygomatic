# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Helpers of Stage 4.5, the music bed (`music_bed_mix`). 2026-10-09.

Pinned: the ACE-Step prompt follows the emotion curve (sombre from 35 % dark
beats, reflective otherwise); only a MEASURED silence or the 'silent' voice mode
counts as an absent voice, an unmeasurable one never does; the master trim is
skipped beyond 6 dB from -14 LUFS; a long-enough slideshow plays once and a
short one is looped; several clips are spread over the whole narration; and both
ffmpeg command pairs end with the NVENC and libx264 encoder arguments.

These were closure bodies inside `stage_16_music_bed` until the split, so this
is the first time the logic is exercised without an ffmpeg, a GPU or ACE-Step.
"""

import pytest

from zyg_workflows.scholarly.stages_19_36 import music_bed_mix as mb


def test_mood_is_sombre_once_a_third_of_the_curve_is_dark():
    curve = [{'emotion': 'grief'}, {'emotion': 'shock'}, {'emotion': 'wonder'}]
    assert 'sombre, mournful, low strings, sparse piano' in mb.bed_mood_prompt(curve)


def test_mood_is_reflective_for_a_light_or_missing_curve():
    light = mb.bed_mood_prompt([{'emotion': 'wonder'}, {'emotion': 'hope'}, {'emotion': 'grief'}])
    assert 'reflective, hopeful, warm strings, soft piano' in light
    # 1 of 3 is under the 0.35 gate; an empty curve must not score as dark either
    assert 'reflective, hopeful' in mb.bed_mood_prompt([])
    assert 'no vocals' in light and 'sits under narration' in light


@pytest.mark.parametrize(
    ('voice_lufs', 'sch_voice', 'absent'),
    [
        (None, 'silent', True),  # the placeholder voice is absent by declaration
        (-60.0, 'piper', True),  # a measured silence is absent
        (-45.0, 'piper', True),  # the gate is inclusive
        (-14.0, 'piper', False),
        (None, 'piper', False),  # unmeasurable must never drop the narration
    ],
)
def test_voice_absence_needs_a_measurement_or_the_silent_mode(voice_lufs, sch_voice, absent):
    assert mb.voice_is_absent(voice_lufs, sch_voice) is absent


def test_master_trim_only_applies_as_a_small_correction():
    assert mb.master_trim_applies(-16.0) is True
    assert mb.master_trim_applies(-8.0) is True
    assert mb.master_trim_applies(-34.0) is False  # a +20 dB lift into the limiter
    assert mb.master_trim_applies(None) is False


def test_music_bed_can_be_switched_off_by_env(monkeypatch):
    monkeypatch.setenv('ZYG_SCHOLARLY_MUSIC', '0')
    assert mb.music_bed_disabled() is True
    monkeypatch.setenv('ZYG_SCHOLARLY_MUSIC', 'No')
    assert mb.music_bed_disabled() is True
    monkeypatch.delenv('ZYG_SCHOLARLY_MUSIC', raising=False)
    assert mb.music_bed_disabled() is False


def test_a_short_narration_gets_no_bed():
    assert mb.build_music_bed(None, '/tmp/voice.wav', 12.0) == '/tmp/voice.wav'
    assert mb.build_music_bed(None, '/tmp/voice.wav', 0) == '/tmp/voice.wav'


def test_slideshow_repeats_once_when_it_covers_the_audio():
    assert mb.slideshow_repeats(300.0, 300.0) == 1
    assert mb.slideshow_repeats(298.0, 300.0) == 1  # the 2 s tolerance
    assert mb.slideshow_repeats(100.0, 300.0) == 4
    assert mb.slideshow_repeats(0.0, 300.0) >= 1  # a zero duration must not divide by zero


def test_clips_are_spread_over_the_whole_narration():
    clips = ['a.mp4', 'b.mp4', 'c.mp4']
    spread = mb.spread_clips(clips, 100.0)
    assert len(spread) == 5  # 100 / (100/3) + 2
    assert set(spread) <= set(clips)
    assert spread[:3] == clips  # order is preserved, the set is repeated
    assert mb.spread_clips(['only.mp4'], 30.0) == ['only.mp4', 'only.mp4', 'only.mp4']


def test_a_long_enough_slideshow_plays_once_and_logs_nothing(monkeypatch):
    monkeypatch.setattr(mb, '_probe_duration', lambda path, fallback: 400.0)
    logged = []
    plan = mb.plan_clip_sequence(['/o/slug_slideshow.mp4'], 300.0, 'slug', lambda *a: logged.append(a))
    assert plan == ['/o/slug_slideshow.mp4']
    assert logged == []


def test_a_short_slideshow_is_looped_and_the_loop_is_logged(monkeypatch):
    monkeypatch.setattr(mb, '_probe_duration', lambda path, fallback: 100.0)
    logged = []
    plan = mb.plan_clip_sequence(['/o/slug_slideshow.mp4'], 300.0, 'slug', lambda *a: logged.append(a))
    assert plan == ['/o/slug_slideshow.mp4'] * 4
    assert len(logged) == 1
    assert 'looping 4×' in logged[0][2]


def test_assembly_commands_mux_the_concat_list_and_fall_back_to_x264():
    nvenc, x264 = mb.concat_assembly_commands('/o/concat.txt', '/o/mix.wav', 120.0, '/o/film.mp4')
    assert nvenc[:8] == x264[:8]
    assert '/o/concat.txt' in nvenc and '/o/mix.wav' in nvenc
    assert nvenc[nvenc.index('-t') + 1] == '122.0'
    assert nvenc[-1] == x264[-1] == '/o/film.mp4'
    assert 'h264_nvenc' in nvenc and 'libx264' in x264


def test_the_no_video_assembly_draws_a_gradient_under_the_audio():
    nvenc, x264 = mb.black_assembly_commands('/o/mix.wav', 120.0, '/o/film.mp4')
    assert 'lavfi' in nvenc
    assert any('gradients=size=1920x1080' in a and 'duration=125' in a for a in nvenc)
    assert '-shortest' in nvenc and '-shortest' in x264
    assert nvenc[-1] == x264[-1] == '/o/film.mp4'
