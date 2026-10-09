# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers extracted from ``_pf_stage_4b``.

Every function exercised here was a closure inside the 568-line Stage 4b
branch and had never been called in isolation. No GPU, no network, no
services: the transcript helpers get a hand-written Whisper-shaped JSON file
and the phase helpers get plain dicts and recording log callbacks.
"""

import json

from zyg_workflows.stage_runner.stage4b_phases import _assign_moments
from zyg_workflows.stage_runner.stage4b_phases import _build_render_jobs
from zyg_workflows.stage_runner.stage4b_phases import _build_video_lookups
from zyg_workflows.stage_runner.stage4b_phases import _recover_processed_clips
from zyg_workflows.stage_runner.stage4b_phases import _report_quality_gate
from zyg_workflows.stage_runner.stage4b_scoring import _find_stupid_moments_in_clip
from zyg_workflows.stage_runner.stage4b_scoring import _get_natural_clip_duration
from zyg_workflows.stage_runner.stage4b_scoring import _pick_top_timestamps
from zyg_workflows.stage_runner.stage4b_scoring import _score_transcript
from zyg_workflows.stage_runner.stage4b_scoring import _snap_to_sentence_start


def _write_transcript(tmp_path, segments):
    """Write a Whisper-shaped transcript JSON and return its path as a str."""
    path = tmp_path / 'transcript.json'
    path.write_text(json.dumps({'segments': segments}))
    return str(path)


# ── _score_transcript ────────────────────────────────────────────────────────


def test_transcript_scores_are_normalised_per_second(tmp_path):
    tx = _write_transcript(
        tmp_path,
        [
            {'start': 0.0, 'text': 'nothing happens here'},
            {'start': 10.4, 'text': 'this is insane bro'},
            {'start': 20.0, 'text': 'insane'},
        ],
    )
    scores = _score_transcript(tx, 30.0, {'insane', 'bro'})
    # every second that has a segment is recorded; second 10 has two keyword
    # hits, second 20 has one, second 0 none, and 10 is the normalising max
    assert scores == {0: 0.0, 10: 1.0, 20: 0.5}


def test_exclamations_and_shouting_count_as_partial_hits(tmp_path):
    tx = _write_transcript(tmp_path, [{'start': 5.0, 'text': 'WHAT!'}])
    # 1 keyword + 1 '!' × 0.5 + one all-caps word × 0.3, alone so normalised to 1.0
    assert _score_transcript(tx, 10.0, {'what'}) == {5: 1.0}


def test_a_missing_or_unparsable_transcript_scores_nothing(tmp_path):
    assert _score_transcript('', 10.0, {'x'}) == {}
    assert _score_transcript(str(tmp_path / 'absent.json'), 10.0, {'x'}) == {}
    broken = tmp_path / 'broken.json'
    broken.write_text('not json at all')
    assert _score_transcript(str(broken), 10.0, {'x'}) == {}


# ── _pick_top_timestamps ─────────────────────────────────────────────────────


def test_top_timestamps_are_peaks_centred_five_seconds_early():
    motion = {100: 1.0, 500: 0.9}
    chosen = _pick_top_timestamps(motion, {}, 1000.0, n_clips=2, clip_len=100.0)
    assert chosen == [95.0, 495.0]


def test_top_timestamps_never_overlap():
    # three peaks 10s apart, clip_len 360 — only the strongest survives
    motion = {100: 1.0, 110: 0.9, 120: 0.8}
    assert _pick_top_timestamps(motion, {}, 1000.0, n_clips=3) == [95.0]


def test_no_scores_falls_back_to_evenly_spaced_starts():
    assert _pick_top_timestamps({}, {}, 1200.0, n_clips=3) == [300, 600, 900]


def test_transcript_weight_outranks_motion_weight():
    # equal raw scores: the transcript peak (0.55) beats the motion peak (0.45)
    chosen = _pick_top_timestamps({10: 1.0}, {900: 1.0}, 1000.0, n_clips=1)
    assert chosen == [895.0]


# ── _snap_to_sentence_start ──────────────────────────────────────────────────


def test_start_snaps_back_to_a_sentence_boundary(tmp_path):
    tx = _write_transcript(
        tmp_path,
        [
            {'start': 94.0, 'text': 'and then it ended.'},
            {'start': 96.0, 'text': 'a brand new thought'},
        ],
    )
    assert _snap_to_sentence_start(tx, 100.0, window=8.0) == 96.0


def test_start_is_kept_when_no_sentence_ends_in_the_window(tmp_path):
    tx = _write_transcript(
        tmp_path,
        [
            {'start': 94.0, 'text': 'still talking'},
            {'start': 96.0, 'text': 'and talking'},
        ],
    )
    assert _snap_to_sentence_start(tx, 100.0, window=8.0) == 100.0


def test_start_is_kept_without_a_transcript():
    assert _snap_to_sentence_start('', 42.0) == 42.0


# ── _get_natural_clip_duration ───────────────────────────────────────────────


def test_duration_ends_on_the_first_sentence_past_the_minimum(tmp_path):
    tx = _write_transcript(
        tmp_path,
        [
            {'start': 0.0, 'end': 50.0, 'text': 'early sentence.'},
            {'start': 50.0, 'end': 95.0, 'text': 'the one that counts.'},
            {'start': 95.0, 'end': 120.0, 'text': 'later still.'},
        ],
    )
    # 95.0 is the first sentence end past start+90; +0.5 of padding
    assert _get_natural_clip_duration(tx, 0.0, min_dur=90.0, max_dur=360.0) == 95.5


def test_duration_falls_back_to_a_silence_gap(tmp_path):
    tx = _write_transcript(
        tmp_path,
        [
            {'start': 0.0, 'end': 95.0, 'text': 'no punctuation here'},
            {'start': 97.0, 'end': 120.0, 'text': 'after a two second gap'},
        ],
    )
    # no sentence end at all, so the 2.0s gap at 95.0 wins; +0.3 of padding
    assert _get_natural_clip_duration(tx, 0.0, min_dur=90.0, max_dur=360.0) == 95.3


def test_duration_is_the_minimum_without_a_transcript():
    assert _get_natural_clip_duration('', 0.0, min_dur=90.0) == 90.0


# ── _find_stupid_moments_in_clip ─────────────────────────────────────────────


def test_cringe_moments_are_relative_to_the_clip_and_ranked(tmp_path):
    tx = _write_transcript(
        tmp_path,
        [
            {'start': 5.0, 'text': 'before the clip, cringe'},
            {'start': 110.0, 'text': 'mildly cringe'},
            {'start': 150.0, 'text': 'cringe and awkward!'},
            {'start': 900.0, 'text': 'after the clip, cringe'},
        ],
    )
    moments = _find_stupid_moments_in_clip(tx, 100.0, 200.0, {'cringe', 'awkward'})
    assert moments == [(50.0, 'cringe and awkward!'), (10.0, 'mildly cringe')]


def test_no_cringe_moments_without_a_transcript():
    assert _find_stupid_moments_in_clip('', 0.0, 10.0, {'cringe'}) == []


# ── _build_video_lookups ─────────────────────────────────────────────────────


def test_video_lookups_map_titles_and_channel_names():
    state = {
        'approved_clips': [{'video_id': 'v1', 'title': 'A Title', 'channel_name': 'Chan'}],
        'channels': [{'name': 'Chan', 'channel_id': 'UC123'}],
        'video_candidates': [{'video_id': 'v1', 'channel_name': 'Chan'}],
    }
    titles, channels = _build_video_lookups(state)
    assert titles == {'v1': 'A Title'}
    assert channels == {'v1': 'Chan'}

    from zyg_workflows.narrator_voice_service import _vid_to_channel_id

    assert _vid_to_channel_id['v1'] == 'UC123'


def test_video_lookups_of_an_empty_state_are_empty():
    assert _build_video_lookups({}) == ({}, {})


# ── _build_render_jobs ───────────────────────────────────────────────────────


def test_render_jobs_are_one_tuple_per_moment():
    scored = [
        {
            'vid_id': 'v1',
            'vid_path': '/v1.mp4',
            'tx_path': '/v1.json',
            'moments': [10.0, 20.0],
            'titles': ['first'],
            'sfx_plan': [{'at': 1}],
            'react_plan': [],
            'intro': 'hello',
        }
    ]
    jobs = _build_render_jobs(scored)
    assert jobs == [
        ('v1', '/v1.mp4', '/v1.json', 0, 10.0, 'first', [{'at': 1}], [], 'hello'),
        # the second moment has no title of its own — the field goes empty
        ('v1', '/v1.mp4', '/v1.json', 1, 20.0, '', [{'at': 1}], [], 'hello'),
    ]


# ── _assign_moments ──────────────────────────────────────────────────────────


def _scored_one_video():
    """One phase-A result with a single strong motion peak."""
    return [
        {
            'vid_id': 'v1',
            'vid_path': '/v1.mp4',
            'tx_path': '/v1.json',
            'tx_score': {},
            'motion_score': {600: 1.0},
            'vid_duration': 1200.0,
        }
    ]


def test_director_moments_are_used_as_returned():
    def _director(scored_raw, n_clips=5):
        return ({'v1': [1.0, 2.0]}, {'v1': ['t1', 't2']}, {'v1': ['sfx']}, {'v1': ['react']}, {'v1': 'intro'})

    videos, bulk = _assign_moments(_scored_one_video(), _director, lambda m: None, lambda m: None)
    assert bulk == {'v1': [1.0, 2.0]}
    assert videos[0]['moments'] == [1.0, 2.0]
    assert videos[0]['titles'] == ['t1', 't2']
    assert videos[0]['intro'] == 'intro'


def test_a_director_that_raises_falls_back_to_the_algorithm():
    warnings = []

    def _director(scored_raw, n_clips=5):
        raise RuntimeError('413 payload too large')

    videos, bulk = _assign_moments(_scored_one_video(), _director, warnings.append, lambda m: None)
    assert bulk == {}
    # the motion peak at 600 centred 5s early, and no titles at all
    assert videos[0]['moments'] == [595.0]
    assert videos[0]['titles'] == []
    assert any('algorithmic fallback for all videos' in w for w in warnings)


def test_a_video_the_director_skipped_falls_back_alone():
    def _director(scored_raw, n_clips=5):
        return ({}, {}, {}, {}, {})

    warnings = []
    videos, _ = _assign_moments(_scored_one_video(), _director, warnings.append, lambda m: None)
    assert videos[0]['moments'] == [595.0]
    assert any('returned NO clips for this video' in w for w in warnings)


# ── _recover_processed_clips ─────────────────────────────────────────────────


def test_recovery_scan_prefers_the_normalised_clip(tmp_path):
    (tmp_path / 'v1_clip0.mp4').write_bytes(b'raw')
    (tmp_path / 'v1_clip0_norm.mp4').write_bytes(b'normalised')
    (tmp_path / 'v1_clip1.mp4').write_bytes(b'raw')
    (tmp_path / 'notes.txt').write_bytes(b'ignored')
    processed = []
    _recover_processed_clips(processed, str(tmp_path), lambda m: None)
    assert [(p['video_id'], p['clip_index'], p['recovered']) for p in processed] == [
        ('v1', 0, True),
        ('v1', 1, True),
    ]
    assert processed[0]['path'].endswith('v1_clip0_norm.mp4')
    assert processed[1]['path'].endswith('v1_clip1.mp4')


def test_recovery_scan_leaves_a_non_empty_list_alone(tmp_path):
    (tmp_path / 'v1_clip0.mp4').write_bytes(b'raw')
    processed = [{'video_id': 'v9', 'clip_index': 0, 'path': '/already/there.mp4'}]
    _recover_processed_clips(processed, str(tmp_path), lambda m: None)
    assert processed == [{'video_id': 'v9', 'clip_index': 0, 'path': '/already/there.mp4'}]


# ── _report_quality_gate ─────────────────────────────────────────────────────


def test_quality_gate_flags_untitled_clips_and_empty_moments():
    warnings, infos = [], []
    jobs = [
        ('v1', '/v.mp4', '/v.json', 0, 1.0, 'has a title', [], [], ''),
        ('v1', '/v.mp4', '/v.json', 1, 2.0, '', [], [], ''),
    ]
    _report_quality_gate([{'path': 'a'}], jobs, {}, warnings.append, infos.append)
    assert any('1/2 clips have NO descriptive title' in w for w in warnings)
    assert any('ZERO clip moments for ALL videos' in w for w in warnings)
    assert infos == ['Stage 4b complete: 1 clips rendered, 1 with titles']


def test_quality_gate_is_silent_when_everything_worked():
    warnings, infos = [], []
    jobs = [('v1', '/v.mp4', '/v.json', 0, 1.0, 'titled', [], [], '')]
    _report_quality_gate([{'path': 'a'}], jobs, {'v1': [1.0]}, warnings.append, infos.append)
    assert warnings == []
    assert infos == ['Stage 4b complete: 1 clips rendered, 1 with titles']
