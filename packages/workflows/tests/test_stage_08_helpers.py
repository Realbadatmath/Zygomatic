# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers `stage_08_tts_pre_image_pass` was split into.

The 404-line stage block could only ever be exercised by synthesising a full
narration on the GPU.  Its steps are now module-level functions, so the
decisions they make are testable with a stub context: which narrator a subject
type resolves to, what a pre-emptive RECORD run skips, what a silent
placeholder produces instead of a Whisper pass, when the ASR read-back gate
refuses to build the film, and which keys the stage publishes.  No GPU, no
network, no service.
"""

from __future__ import annotations

import pytest

from zyg_workflows.scholarly.stages_01_18 import stage_08 as S


class _Ctx:
    """The fields of the scholarly run context these helpers actually read."""

    def __init__(self, **kw):
        self._sch_subject_type = kw.get('subject_type', 'war')
        self._preempt_mode = kw.get('preempt_mode', '')
        self.narration_enabled = kw.get('narration_enabled', True)
        self.narration_script = kw.get('script', 'one two three four five six')
        self.tts_duration = kw.get('tts_duration', 120.0)
        self.out_dir = kw.get('out_dir', '/tmp/does-not-exist')
        self._slug = 'slug'
        self.pipeline_id = 'abcdef1234'
        self.pipeline_state: dict = {}
        self._final_word_timings: list = []
        self.logs: list[tuple[str, str]] = []
        self.debugs: list[str] = []
        self.saved = 0
        self.done: list[tuple[str, dict]] = []

    def _log(self, level, stage, msg):
        self.logs.append((level, str(msg)))

    def _debug(self, stage, msg, level='DEBUG'):
        self.debugs.append(str(msg))

    def _save(self):
        self.saved += 1

    def _done(self, name, payload):
        self.done.append((name, payload))


def _clear_env(monkeypatch):
    for k in (
        'ZYG_SCHOLARLY_SEED_WAV',
        'ZYG_SCHOLARLY_EMO_ALPHA',
        'ZYG_SCHOLARLY_EMO_TEXT',
        'ZYG_SCHOLARLY_ASR_FLOOR',
    ):
        monkeypatch.delenv(k, raising=False)


# ── _tts_settings ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('subject_type', 'voice_id'),
    [
        ('person', 'en-GB-ThomasNeural'),
        ('war', 'en-GB-RyanNeural'),
        ('gold', 'en-US-GuyNeural'),
        ('something-else', 'en-GB-RyanNeural'),
    ],
)
def test_the_subject_type_picks_the_voice_id(monkeypatch, subject_type, voice_id):
    """The voice-id map, including the fallback an unknown subject type takes."""
    _clear_env(monkeypatch)
    st = S._tts_settings(_Ctx(subject_type=subject_type))
    assert st.voice_id == voice_id


def test_the_narrator_defaults_to_the_elder_seed_at_alpha_045_with_inference_off(monkeypatch):
    """Delivery defaults set on 2026-08-12: m03_elder_gravel, 0.45, no emo text."""
    _clear_env(monkeypatch)
    st = S._tts_settings(_Ctx())
    assert st.seed_wav.endswith('/data/assets/voice_seeds/pool/m03_elder_gravel.wav')
    assert st.emo_alpha == pytest.approx(0.45)
    assert st.emo_text is False
    assert st.skip_record is False


def test_the_seed_wav_and_the_dials_come_from_the_environment_when_set(monkeypatch):
    """An operator override replaces the seed and both delivery dials."""
    _clear_env(monkeypatch)
    monkeypatch.setenv('ZYG_SCHOLARLY_SEED_WAV', '/tmp/other.wav')
    monkeypatch.setenv('ZYG_SCHOLARLY_EMO_ALPHA', '0.8')
    monkeypatch.setenv('ZYG_SCHOLARLY_EMO_TEXT', 'yes')
    st = S._tts_settings(_Ctx())
    assert (st.seed_wav, st.emo_alpha, st.emo_text) == ('/tmp/other.wav', 0.8, True)


def test_a_preemptive_record_run_skips_synthesis_and_says_so(monkeypatch):
    """`preempt_mode == 'record'` banks Claude work only and logs one line."""
    _clear_env(monkeypatch)
    ctx = _Ctx(preempt_mode='record')
    st = S._tts_settings(ctx)
    assert st.skip_record is True
    assert any('[preempt] record run' in msg for _lvl, msg in ctx.logs)


# ── _collect_word_timings ────────────────────────────────────────────────


def test_a_silent_placeholder_gets_synthetic_linear_timings_not_whisper():
    """Whisper on silence hallucinates, so the silent branch interpolates."""
    ctx = _Ctx(script='a b c d', tts_duration=40.0)
    timings, stats, coverage = S._collect_word_timings(ctx, '/tmp/none.mp3', False, 'silent', [])
    assert [w for w, _t in timings] == ['a', 'b', 'c', 'd']
    assert [t for _w, t in timings] == [0.0, 10.0, 20.0, 30.0]
    assert ctx._final_word_timings == timings
    assert (stats, coverage) == ({}, None)
    assert any('SYNTHETIC linear word timings' in msg for _lvl, msg in ctx.logs)


def test_engine_timings_are_aligned_and_their_coverage_returned(monkeypatch):
    """Timings the engine itself returned go through the forced aligner."""
    ctx = _Ctx(script='a b')
    monkeypatch.setattr(S, '_align_narration_word_timings', lambda script, raw: ([('a', 0.0)], 0.5))
    timings, _stats, coverage = S._collect_word_timings(ctx, '/tmp/none.mp3', True, 'indextts2', [('a', 0.0)])
    assert timings == []  # no Whisper pass ran
    assert coverage == 0.5
    assert ctx._final_word_timings == [('a', 0.0)]


def test_no_audio_and_no_engine_timings_leaves_the_pick_empty():
    """Under 10 % Whisper coverage the raw engine timings win — here, none."""
    ctx = _Ctx()
    timings, _stats, coverage = S._collect_word_timings(ctx, '/tmp/none.mp3', False, 'indextts2', [])
    assert (timings, coverage) == ([], None)
    assert ctx._final_word_timings == []


# ── _asr_read_back ───────────────────────────────────────────────────────


def test_the_read_back_gate_is_skipped_for_a_silent_placeholder(monkeypatch):
    """Nothing was spoken, so there is no agreement to record."""
    _clear_env(monkeypatch)
    ctx = _Ctx()
    S._asr_read_back(ctx, 'silent', {}, 0.9)
    assert 'asr_alignment_coverage' not in ctx.pipeline_state


def test_a_whisper_failure_skips_the_gate_loudly_instead_of_reading_zero(monkeypatch):
    """`asr_error` must not be mistaken for "heard nothing" (match_ratio 0.0)."""
    _clear_env(monkeypatch)
    ctx = _Ctx()
    S._asr_read_back(ctx, 'indextts2', {'asr_error': 'model OOM', 'match_ratio': 0.0, 'n_script': 6}, None)
    assert ctx.pipeline_state['asr_error'] == 'model OOM'
    assert 'whisper_match_ratio' not in ctx.pipeline_state
    assert any('ASR read-back gate skipped' in msg for _lvl, msg in ctx.logs)


def test_a_good_read_back_records_the_honest_match_numbers(monkeypatch):
    """matched/N from the aligner's op counts, not the set intersection."""
    _clear_env(monkeypatch)
    ctx = _Ctx()
    ctx._final_word_timings = [('one', 0.0), ('two', 110.0)]
    stats = {
        'n_script': 6,
        'match_ratio': 0.9,
        'n_whisper_raw': 7,
        'n_match': 5,
        'n_delete': 1,
        'asr_empty': False,
        'matched_idx': [1],
    }
    S._asr_read_back(ctx, 'indextts2', stats, None)
    assert ctx.pipeline_state['whisper_raw_words'] == 7
    assert ctx.pipeline_state['whisper_matched'] == 5
    assert ctx.pipeline_state['whisper_match_ratio'] == 0.9
    assert ctx.pipeline_state['asr_alignment_coverage'] == 0.9
    assert not [msg for lvl, msg in ctx.logs if lvl in ('WARNING', 'ERROR')]


def test_a_read_back_under_the_floor_warns_but_builds(monkeypatch):
    """Between 30 % and the floor the film is built with a listen-first warning."""
    _clear_env(monkeypatch)
    ctx = _Ctx()
    stats = {'n_script': 6, 'match_ratio': 0.45, 'n_whisper_raw': 7, 'n_match': 3}
    S._asr_read_back(ctx, 'indextts2', stats, None)
    assert ctx.pipeline_state['asr_alignment_coverage'] == 0.45
    assert any('listen before publishing' in msg for lvl, msg in ctx.logs if lvl == 'WARNING')


def test_whisper_hearing_under_30_percent_refuses_to_build_the_film(monkeypatch):
    """The P-02 gate: an unusable narration must stop the pipeline."""
    _clear_env(monkeypatch)
    ctx = _Ctx()
    stats = {'n_script': 6, 'match_ratio': 0.1, 'n_whisper_raw': 7, 'n_match': 1}
    with pytest.raises(RuntimeError, match='narration unusable'):
        S._asr_read_back(ctx, 'indextts2', stats, None)


def test_an_empty_transcript_refuses_to_build_the_film(monkeypatch):
    """`asr_empty` is fatal even when the ratio looks fine."""
    _clear_env(monkeypatch)
    ctx = _Ctx()
    stats = {'n_script': 6, 'match_ratio': 1.0, 'n_whisper_raw': 0, 'n_match': 6, 'asr_empty': True}
    with pytest.raises(RuntimeError, match='narration unusable'):
        S._asr_read_back(ctx, 'indextts2', stats, None)


def test_a_last_matched_word_in_the_first_80_percent_warns_of_truncation(monkeypatch):
    """A tail nobody spoke is a warning, because the read may be cut short."""
    _clear_env(monkeypatch)
    ctx = _Ctx(tts_duration=100.0)
    ctx._final_word_timings = [('one', 0.0), ('two', 10.0)]
    stats = {'n_script': 2, 'match_ratio': 1.0, 'n_whisper_raw': 2, 'n_match': 2, 'matched_idx': [0, 1]}
    S._asr_read_back(ctx, 'indextts2', stats, None)
    assert any('may be truncated' in msg for lvl, msg in ctx.logs if lvl == 'WARNING')


# ── _extract_rhythm_cuts and _publish_tts_state ──────────────────────────


def test_no_narration_file_means_no_rhythm_cues():
    """Librosa is never asked about a file that does not exist."""
    assert S._extract_rhythm_cuts(_Ctx(), '/tmp/definitely-not-here.mp3', False) == []


def test_publishing_the_state_writes_every_key_and_closes_the_stage_once():
    """The stage's contract with every later stage, saved exactly once."""
    ctx = _Ctx(tts_duration=123.44)
    ctx._final_word_timings = [('one', 0.0)]
    S._publish_tts_state(ctx, '/tmp/n.mp3', True, 'indextts2 (seed m03)', [('one', 0.0)], [('one', 0.0)], [1.0, 2.0])
    assert ctx.pipeline_state['tts_path'] == '/tmp/n.mp3'
    assert ctx.pipeline_state['tts_duration'] == 123.4
    assert ctx.pipeline_state['tts_voice'] == 'indextts2 (seed m03)'
    assert ctx.pipeline_state['final_word_timings'] == [('one', 0.0)]
    assert ctx.pipeline_state['rhythm_cuts'] == [1.0, 2.0]
    assert ctx.pipeline_state['wan_enabled'] is False
    assert ctx.pipeline_state['wan_clips'] == []
    assert ctx.saved == 1
    assert ctx.done == [
        (
            'Stage 4: TTS Narration',
            {'duration_s': 123.4, 'voice': 'indextts2 (seed m03)', 'whisper_words': 1, 'rhythm_cuts': 2},
        )
    ]
