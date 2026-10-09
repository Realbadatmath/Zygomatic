# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the Stage 5b steps extracted from ``stage_05b_burn_subtitles``.

Every one of these was a nested ``def`` or a block of locals inside a 458-line
function, so this file is the first time the caption timing, the SRT writer and
the three delivery gates are exercised in isolation. Nothing here touches the
GPU, the network or a service: the gates get a hand-built context object and the
only patched name is ``_update_marker`` (it writes into the subprocess
registry)."""

import types

import pytest
from zyg_workflows.storyteller import stage_05b_subtitles_captions as CAP


def _ctx(tmp_path, **over):
    """A minimal stand-in for StorytellerContext: the fields Stage 5b reads."""
    logged: list = []
    saved: list = []
    ctx = types.SimpleNamespace(
        job={},
        pipeline_state={},
        final_path=str(tmp_path / 'final.mp4'),
        narration_enabled=True,
        _pipeline_marker='marker-id',
        _log=lambda lvl, stage, msg: logged.append((lvl, stage, msg)),
        _save=lambda: saved.append(1),
    )
    ctx.__dict__.update(over)
    ctx.logged = logged
    ctx.saved = saved
    return ctx


# ── caption text ─────────────────────────────────────────────────────────────


def test_srt_timestamp_uses_the_comma_millisecond_form():
    """SRT wants HH:MM:SS,mmm — a dot there makes ffmpeg reject the cue."""
    assert CAP.srt_timestamp(0) == '00:00:00,000'
    assert CAP.srt_timestamp(3661.5) == '01:01:01,500'
    assert CAP.srt_timestamp(59.999) == '00:00:59,999'


def test_clean_caption_text_drops_the_unspoken_stage_directions():
    """'(pause)' and '(beat)' are never spoken, so they must not reach a caption."""
    assert CAP.clean_caption_text('Hello (pause) there') == 'Hello there'
    assert CAP.clean_caption_text('Wait ( BEAT )  then   go') == 'Wait then go'
    assert CAP.clean_caption_text('   ') == ''


def test_wrap_srt_text_wraps_without_dropping_a_single_word():
    """The 2026-07-24 r3 bug: the wrapper used to slice to 3 lines and lose ~64% of a cue."""
    txt = ' '.join(f'word{i}' for i in range(40))
    wrapped = CAP.wrap_srt_text(txt, max_chars=20)
    assert wrapped.split() == txt.split()
    assert all(len(line) <= 20 for line in wrapped.splitlines())
    assert len(wrapped.splitlines()) > 3


def test_split_caption_chunks_breaks_on_sentences_and_packs_long_ones():
    """One scene becomes several short cues: sentence boundaries first, word packing after."""
    chunks = CAP.split_caption_chunks('One two three. Four five six.', max_chars=16)
    assert chunks == ['One two three.', 'Four five six.']
    long_one = 'a' * 10 + ' ' + 'b' * 10 + ' ' + 'c' * 10
    assert CAP.split_caption_chunks(long_one, max_chars=12) == ['a' * 10, 'b' * 10, 'c' * 10]
    assert CAP.split_caption_chunks('   ') == []


# ── cue timing ───────────────────────────────────────────────────────────────


def test_entries_from_word_timings_breaks_on_punctuation_after_five_words():
    """A cue holds 5-12 words and ends early on '.', '?' or '!'."""
    words = ['one', 'two', 'three', 'four', 'five.', 'six', 'seven']
    entries = CAP.entries_from_word_timings([(w, float(i)) for i, w in enumerate(words)])
    assert [e[0] for e in entries] == ['one two three four five.', 'six seven']
    assert entries[0][1] == 0.0


def test_entries_from_word_timings_caps_a_cue_at_twelve_words():
    """Without punctuation the cue is cut at MAX_CUE_WORDS so captions stay readable."""
    timings = [(f'w{i}', float(i) * 0.5) for i in range(30)]
    entries = CAP.entries_from_word_timings(timings)
    assert all(len(e[0].split()) <= CAP.MAX_CUE_WORDS for e in entries)
    assert len(entries[0][0].split()) == CAP.MAX_CUE_WORDS


def test_entries_from_word_timings_clamps_the_end_off_the_next_word():
    """The 0.35s trailing buffer may not overlap the next word, and a cue lasts ≥0.5s."""
    timings = [('a', 0.0), ('b', 0.1), ('c', 0.2), ('d', 0.3), ('e.', 0.4), ('f', 0.5)]
    (text, start, end), *_rest = CAP.entries_from_word_timings(timings)
    assert text == 'a b c d e.'
    assert start == 0.0
    assert end == pytest.approx(0.5)  # min cue length wins over the 0.45 clamp


def test_entries_proportional_spends_the_whole_duration_by_character_share():
    """With no word timings the cues divide the video duration by character count."""
    entries = CAP.entries_proportional(['Short line.', 'A rather longer line of narration.'], 100.0)
    assert len(entries) == 2
    assert entries[0][1] == 0.0
    assert entries[1][1] == pytest.approx(entries[0][2])
    assert entries[-1][2] == pytest.approx(100.0)
    assert entries[0][2] < entries[1][2] - entries[1][1]  # the longer text gets more time


def test_write_srt_writes_indexed_cues_with_wrapped_text(tmp_path):
    """The written file is valid SRT: index line, timestamp arrow, text, blank line."""
    out = tmp_path / 'subs.srt'
    CAP.write_srt(str(out), [('Hello there', 0.0, 1.5), ('Bye', 2.0, 3.0)])
    assert out.read_text(encoding='utf-8') == (
        '1\n00:00:00,000 --> 00:00:01,500\nHello there\n\n2\n00:00:02,000 --> 00:00:03,000\nBye\n\n'
    )


def test_copy_srt_beside_video_uses_the_uploader_s_caption_name(tmp_path):
    """The YouTube uploader reads splitext(video)[0] + '.srt', nothing else."""
    srt = tmp_path / 'slug_subtitles.srt'
    srt.write_text('1\n', encoding='utf-8')
    CAP.copy_srt_beside_video(str(srt), str(tmp_path / 'final.mp4'), lambda *a: None)
    assert (tmp_path / 'final.srt').read_text(encoding='utf-8') == '1\n'


def test_copy_srt_beside_video_logs_instead_of_raising(tmp_path):
    """A caption-name copy failure is non-fatal — the render is still deliverable."""
    logged: list = []
    CAP.copy_srt_beside_video(str(tmp_path / 'missing.srt'), str(tmp_path / 'final.mp4'), lambda *a: logged.append(a))
    assert logged and logged[0][0] == 'WARNING'
    assert 'Caption-name copy failed' in logged[0][2]


# ── delivery gates ───────────────────────────────────────────────────────────


def test_write_subtitles_saves_the_srt_and_the_uploader_copy(tmp_path):
    """The whole subtitle step: proportional cues, the SRT in out_dir, the uploader copy."""
    ctx = _ctx(
        tmp_path,
        out_dir=str(tmp_path),
        _slug_st='slug',
        scenes=[{'narration': 'First scene speaks.'}, {'narration': 'Second scene replies.'}],
        tts_duration=10.0,
        duration_min=1,
        tts_word_timings=[],
        full_narration='First scene speaks. Second scene replies.',
        voice_style='narrator',
    )
    CAP.write_subtitles(ctx)
    assert (tmp_path / 'slug_subtitles.srt').exists()
    assert (tmp_path / 'final.srt').exists()
    assert any('SRT built from proportional char timing' in m for _l, _s, m in ctx.logged)


def test_write_subtitles_skips_a_run_with_no_narration(tmp_path):
    """No narration text: one log line and no file — never a raise."""
    ctx = _ctx(
        tmp_path,
        out_dir=str(tmp_path),
        _slug_st='slug',
        scenes=[{'narration': '  '}],
        tts_duration=10.0,
        duration_min=1,
        tts_word_timings=[],
        full_narration='',
        voice_style='narrator',
    )
    CAP.write_subtitles(ctx)
    assert not list(tmp_path.glob('*.srt'))
    assert ctx.logged[-1] == ('INFO', 'Stage 5b', 'No narration text — skipping subtitles')


def test_gate_final_video_fails_a_missing_or_tiny_delivery(tmp_path, monkeypatch):
    """A 0-byte slideshow must never be reported complete (run a6f458bc)."""
    monkeypatch.setattr(CAP, '_update_marker', lambda *a, **k: None)
    ctx = _ctx(tmp_path)
    assert CAP.gate_final_video(ctx) is True
    assert ctx.job['status'] == 'failed'
    assert 'Final video missing or empty' in ctx.job['error']
    assert ctx.job['current_stage'] == 'Failed — no final video'
    assert ctx.saved == [1]


def test_gate_final_video_passes_a_real_delivery(tmp_path, monkeypatch):
    """Over 1 MB on disk and the gate is silent — no job mutation, no save."""
    monkeypatch.setattr(CAP, '_update_marker', lambda *a, **k: None)
    video = tmp_path / 'final.mp4'
    video.write_bytes(b'\0' * 1_000_001)
    ctx = _ctx(tmp_path, final_path=str(video))
    assert CAP.gate_final_video(ctx) is False
    assert ctx.job == {}
    assert ctx.saved == []


def test_gate_narration_audio_fails_a_narrated_run_with_no_audio(tmp_path, monkeypatch):
    """Run 6278904c shipped a silent slideshow as completed — narration_missing now fails."""
    monkeypatch.setattr(CAP, '_update_marker', lambda *a, **k: None)
    ctx = _ctx(tmp_path, pipeline_state={'narration_missing': True})
    assert CAP.gate_narration_audio(ctx) is True
    assert ctx.job['status'] == 'failed'
    assert 'No narration audio' in ctx.job['error']
    assert ctx.job['result'] == ctx.final_path


def test_gate_narration_audio_fails_a_delivery_without_an_audio_stream(tmp_path, monkeypatch):
    """The mux check: a tts_path but no audio stream in the file is a failed product."""
    monkeypatch.setattr(CAP, '_update_marker', lambda *a, **k: None)
    monkeypatch.setattr(CAP, 'delivered_has_audio', lambda _p, _log: False)
    ctx = _ctx(tmp_path, pipeline_state={'tts_path': '/tmp/narration.wav'})
    assert CAP.gate_narration_audio(ctx) is True
    assert ctx.job['current_stage'] == 'Failed — video has no audio stream'


def test_gate_narration_audio_is_silent_when_the_audio_is_there(tmp_path, monkeypatch):
    """A narrated run whose file carries audio passes both gates untouched."""
    monkeypatch.setattr(CAP, '_update_marker', lambda *a, **k: None)
    monkeypatch.setattr(CAP, 'delivered_has_audio', lambda _p, _log: True)
    ctx = _ctx(tmp_path, pipeline_state={'tts_path': '/tmp/narration.wav'})
    assert CAP.gate_narration_audio(ctx) is False
    assert ctx.job == {}


def test_delivered_scene_count_prefers_the_delivered_frames():
    """The delivered frame list is the true denominator of the bad-frame share."""
    assert CAP.delivered_scene_count({'flux_images': ['a', 'b', 'c'], 'scene_count': 25}) == 3
    assert CAP.delivered_scene_count({'scene_count': 12}) == 12
    assert CAP.delivered_scene_count({}) == 25


def test_scan_near_duplicates_needs_three_frames_before_it_scans(tmp_path):
    """Fewer than three readable frames can never be a clone run."""
    assert CAP.scan_near_duplicates({}, lambda *a: None, 0.90) == []
    assert CAP.scan_near_duplicates({'flux_images': [str(tmp_path / 'nope.png')]}, lambda *a: None, 0.90) == []


def test_duplicate_signature_is_a_normalised_64x64_composition(tmp_path):
    """The clone check compares composition only, so a signature is zero-mean, unit-sigma."""
    np = pytest.importorskip('numpy')
    pytest.importorskip('PIL')
    from PIL import Image

    path = tmp_path / 'frame.png'
    Image.fromarray(np.arange(256 * 256, dtype=np.uint32).reshape(256, 256).astype('uint8')).save(path)
    sig = CAP.duplicate_signature(np, Image, str(path))
    assert sig.shape == (64, 64)
    assert float(sig.mean()) == pytest.approx(0.0, abs=1e-5)
    assert float(sig.std()) == pytest.approx(1.0, abs=1e-5)


def test_degradation_report_lists_every_reason_and_records_the_duplicates():
    """Bad frames are the union of the fault sets; a hand flag reports but never fails."""
    state = {
        '_st_fallback_scenes': [1],
        '_st_identity_drift_scenes': [(2, 0.4)],
        '_st_rescued_scenes': [3],
        '_st_no_face_scenes': [4],
        '_st_failed_scenes': [5],
        '_st_hand_flagged_scenes': [9],
        'narration_voice_fallback': True,
        'narration_truncated': True,
    }
    bad, bits = CAP.degradation_report(state, 10, [6])
    assert bad == [1, 2, 3, 4, 5, 6]
    assert state['_st_duplicate_scenes'] == [6]
    assert len(bits) == 9
    assert 'tinted reference-photo fallbacks' in bits[0]
    assert 'hand imperfection' in bits[6] and 'non-fatal' in bits[6]
    assert bits[-1].startswith('narration audio is suspiciously short')


def test_degradation_report_of_a_clean_run_is_empty():
    """No fault sets, no reasons — the run completes undegraded."""
    assert CAP.degradation_report({}, 12, []) == ([], [])


def test_fail_degraded_keeps_the_video_and_names_the_reasons(tmp_path, monkeypatch):
    """A rejected run still points at the file so the frames can be inspected."""
    marks: list = []
    monkeypatch.setattr(CAP, '_update_marker', lambda m, **k: marks.append((m, k)))
    ctx = _ctx(tmp_path)
    CAP.fail_degraded(ctx, [1, 2, 3, 4], 10, ['4/10 scenes are tinted reference-photo fallbacks (scenes [1, 2, 3, 4])'])
    assert ctx.job['status'] == 'failed'
    assert ctx.job['error'].startswith('Degraded output rejected: 4/10 scenes are tinted')
    assert ctx.job['final_output_file'] == ctx.final_path
    assert marks[0][1]['label'] == 'Storyteller DEGRADED (4/10 bad frames)'
    assert ctx.saved == [1]
