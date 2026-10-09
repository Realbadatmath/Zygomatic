# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the pure half of Stage 4b's director module.

Every behaviour asserted here was a behaviour of the 409-line
``_make_github_models`` closure before it was split into
``stage4b_models_director``: transcript reading, prompt assembly, code-fence
stripping and director-output parsing.  No network, no services, no GPU.
"""

from __future__ import annotations

import json

from zyg_workflows.stage_runner import stage4b_models
from zyg_workflows.stage_runner import stage4b_models_director as director


def _write_transcript(tmp_path, segments):
    path = tmp_path / 'tx.json'
    path.write_text(json.dumps({'segments': segments}))
    return str(path)


# ── transcript_scoring_lines ─────────────────────────────────────────────────


def test_scoring_lines_use_seconds_and_drop_empty_text(tmp_path):
    """Clip-picker lines are ``[12.3s] text``, trimmed, with blank segments gone."""
    tx = _write_transcript(
        tmp_path,
        [
            {'start': 0.0, 'text': 'hello there'},
            {'start': 61.44, 'text': '  spaced  '},
            {'start': 90.0, 'text': '   '},
        ],
    )
    assert director.transcript_scoring_lines(tx) == ['[0.0s] hello there', '[61.4s] spaced']


def test_scoring_lines_are_none_when_the_transcript_is_unreadable(tmp_path):
    """A missing transcript returns None so the caller can fall back to motion."""
    assert director.transcript_scoring_lines(str(tmp_path / 'nope.json')) is None


# ── director_transcript_lines ────────────────────────────────────────────────


def test_director_lines_use_mm_ss_and_cap_at_360(tmp_path):
    """Director lines are ``[mm:ss] text`` and never exceed 360 entries."""
    tx = _write_transcript(tmp_path, [{'start': 5.0 * i, 'text': f'line {i}'} for i in range(500)])
    lines = director.director_transcript_lines(tx)
    assert len(lines) == 360
    assert lines[0] == '[00:00] line 0'
    assert lines[13] == '[01:05] line 13'


def test_director_lines_fall_back_to_a_placeholder(tmp_path):
    """An unreadable transcript becomes one ``[transcript unavailable]`` line."""
    assert director.director_transcript_lines(str(tmp_path / 'nope.json')) == ['[transcript unavailable]']


# ── motion_peaks_str / clip_picker_prompt ────────────────────────────────────


def test_motion_peaks_are_the_twenty_loudest_descending():
    """Peaks are sorted loudest-first, capped at 20, rendered ``12s (0.91)``."""
    motion = {float(t): t / 100.0 for t in range(1, 31)}
    out = director.motion_peaks_str(motion)
    parts = out.split(', ')
    assert len(parts) == 20
    assert parts[0] == '30s (0.30)'
    assert parts[-1] == '11s (0.11)'


def test_clip_picker_prompt_states_the_count_duration_and_window():
    """The prompt carries n_clips, the duration and the duration-90 upper bound."""
    prompt = director.clip_picker_prompt(['[0.0s] hi'], {12.0: 0.9}, 600.0, 4)
    assert 'pick the 4 best moments' in prompt
    assert 'Video duration: 600 seconds' in prompt
    assert '- Return exactly 4 clips' in prompt
    assert 'start_seconds must be within 0 and 510' in prompt
    assert '12s (0.90)' in prompt
    assert '[0.0s] hi' in prompt


def test_clip_picker_prompt_caps_the_transcript_at_300_lines():
    """Only the first 300 transcript lines reach the model."""
    lines = [f'[{i}.0s] line {i}' for i in range(400)]
    prompt = director.clip_picker_prompt(lines, {}, 600.0, 5)
    assert '[299.0s] line 299' in prompt
    assert '[300.0s] line 300' not in prompt


def test_clip_picker_window_never_goes_negative():
    """A video shorter than the 90 s clip length clamps the window to 0."""
    prompt = director.clip_picker_prompt([], {}, 30.0, 1)
    assert 'start_seconds must be within 0 and 0' in prompt


# ── director_user_message ────────────────────────────────────────────────────


def test_director_user_message_header_and_objective():
    """The message opens with the objective and a VIDEO_ID/CHANNEL/DURATION header."""
    msg = director.director_user_message('v1', 'chan-one', 3725.0, ['[00:00] go'])
    assert msg.startswith(f'OBJECTIVE: {director.DIRECTOR_OBJECTIVE}')
    assert 'VIDEO_ID: v1 | CHANNEL: chan-one | DURATION: 62m5s' in msg
    assert msg.endswith('TRANSCRIPT:\n[00:00] go')


# ── strip_code_fences ────────────────────────────────────────────────────────


def test_strip_code_fences_removes_only_fenced_wrappers():
    """A fenced answer loses its ``` lines; unfenced text is returned unchanged."""
    assert director.strip_code_fences('```\nINTRO: hi\n```') == 'INTRO: hi'
    assert director.strip_code_fences('INTRO: hi') == 'INTRO: hi'
    assert director.strip_code_fences('text with ``` inside') == 'text with ``` inside'


# ── parse_director_output ────────────────────────────────────────────────────

SAMPLE = '\n'.join(
    [
        'PEAK MOMENT: 05:30 — the reveal',
        'INTRO: You will not guess what happens',
        'CUTS:',
        '[00:00-00:30] KEEP — strong hook',
        '[00:30-01:00] CUT — filler',
        '[01:00-01:30] MAYBE — maybe lands',
        '[05:30-06:00] KEEP — the reveal',
        '[09:00-09:30] KEEP — crowd gasp',
        '[20:00-20:30] KEEP — past the end',
        'SFX: 05:35 | crowd gasp | reversal lands here',
        'REACTION: 05:40 | shocked | 3',
        'EDIT NOTE: hold on the face',
    ]
)


def test_parse_director_output_picks_keeps_and_maybes_near_the_peak():
    """Starts come back sorted, peak-first in preference, CUT lines ignored."""
    starts, titles, sfx, react, intro = director.parse_director_output(SAMPLE, 1200.0, 5)
    assert starts == [0, 60, 330, 540]
    assert titles == ['strong hook', 'maybe lands', 'the reveal', 'crowd gasp']
    assert intro == 'You will not guess what happens'
    assert sfx == [{'ts_secs': 335, 'sound_name': 'crowd gasp'}]
    assert react == [{'ts_secs': 340, 'emotion': 'shocked', 'duration': 3}]


def test_parse_director_output_drops_clips_past_the_end():
    """A segment starting at or past the duration is never selected."""
    starts, _titles, _sfx, _react, _intro = director.parse_director_output(SAMPLE, 600.0, 5)
    assert starts == [0, 60, 330, 540]
    starts_short, _t, _s, _r, _i = director.parse_director_output(SAMPLE, 400.0, 5)
    assert starts_short == [0, 60, 330]


def test_parse_director_output_honours_n_clips_and_prefers_the_peak():
    """With n_clips=1 the one pick is the PEAK MOMENT segment."""
    starts, titles, _sfx, _react, _intro = director.parse_director_output(SAMPLE, 1200.0, 1)
    assert starts == [330]
    assert titles == ['the reveal']


def test_parse_director_output_spaces_picks_sixty_seconds_apart():
    """Two segments less than 60 s apart yield only the first."""
    text = '\n'.join(['[00:00-00:30] KEEP — one', '[00:30-01:00] KEEP — two'])
    starts, titles, _sfx, _react, _intro = director.parse_director_output(text, 600.0, 5)
    assert starts == [0]
    assert titles == ['one']


def test_parse_director_output_is_empty_for_prose():
    """Text with no CUTS ladder parses to empty plans and an empty intro."""
    assert director.parse_director_output('nothing to see here', 600.0, 5) == ([], [], [], [], '')


def test_parse_director_output_truncates_titles_at_fifty_chars():
    """A long KEEP reason becomes a title of at most 50 characters."""
    reason = 'r' * 90
    _starts, titles, _sfx, _react, _intro = director.parse_director_output(f'[00:00-00:30] KEEP — {reason}', 600.0, 5)
    assert titles == ['r' * 50]


# ── the orchestrator still hands back the bulk caller ────────────────────────


def test_make_github_models_returns_the_bulk_caller():
    """``_make_github_models`` still returns one callable, as Stage 4b expects."""
    bulk = stage4b_models._make_github_models(lambda _m: None, lambda _m: None, {})
    assert callable(bulk)
    assert bulk([]) == ({}, {}, {}, {}, {})
