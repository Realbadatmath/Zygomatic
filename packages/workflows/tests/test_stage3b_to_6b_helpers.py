# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers split out of ``_crime_stages_3b_to_6b``.

The crime pipeline's stages 3b-6b used to be one 494-line function, so none of this
logic had ever been exercised on its own. ``parse_tag_json`` and ``fmt_srt`` were
nested defs inside it; the subtitle grouping, the prompt assembly and the doc-card
sentence selection were inline blocks. Everything tested here is pure or writes only
into ``tmp_path``: no Ollama, no OpenAI, no TTS engine, no Pillow.
"""

import json
import os

from zyg_workflows.pipeline_crime.stage3b_to_6b_steps import (
    _raw_srt_entries,
    batch_tag_prompt,
    card_sentences,
    estimated_srt_entries,
    fmt_srt,
    parse_tag_json,
    pick_tag_llm,
    probe_tts_duration,
    srt_entries,
    stage_6a_srt,
)


def _log_sink(records):
    """Return a ``_log(level, stage, message)`` stand-in appending to ``records``."""

    def _log(level, stage, message):
        records.append((level, stage, message))

    return _log


# ── parse_tag_json ────────────────────────────────────────────────────────────


def test_a_plain_json_array_comes_back_unchanged():
    raw = '[{"type": "person", "subject": "Ted Bundy"}, {"type": "court", "subject": "the verdict"}]'
    assert parse_tag_json(raw) == [
        {'type': 'person', 'subject': 'Ted Bundy'},
        {'type': 'court', 'subject': 'the verdict'},
    ]


def test_a_markdown_fenced_array_is_unwrapped_before_parsing():
    raw = '```json\n[{"type": "location", "subject": "Seattle"}]\n```'
    assert parse_tag_json(raw) == [{'type': 'location', 'subject': 'Seattle'}]


def test_an_object_that_wraps_the_array_under_tags_is_unwrapped():
    raw = '{"tags": [{"type": "event", "subject": "the arrest"}]}'
    assert parse_tag_json(raw) == [{'type': 'event', 'subject': 'the arrest'}]


def test_unparseable_output_falls_back_to_scraping_one_tag_per_line():
    raw = 'Sure, here you go:\nperson: Ted Bundy\nCOURT - "the verdict"\nnot a tag at all'
    assert parse_tag_json(raw) == [
        {'type': 'person', 'subject': 'Ted Bundy'},
        {'type': 'court', 'subject': 'the verdict'},
    ]


def test_output_with_neither_json_nor_a_tag_line_yields_no_tags():
    assert parse_tag_json('I am sorry, I cannot help with that.') == []


# ── batch_tag_prompt ──────────────────────────────────────────────────────────


def test_the_batch_prompt_numbers_the_sentences_from_one():
    prompt = batch_tag_prompt(['First sentence.', 'Second sentence.'])
    assert '1. First sentence.' in prompt
    assert '2. Second sentence.' in prompt
    assert '0. ' not in prompt


def test_the_batch_prompt_names_every_tag_type_and_demands_bare_json():
    prompt = batch_tag_prompt(['Only one.'])
    for tag_type in ('person', 'location', 'event', 'court', 'crime_scene', 'generic'):
        assert tag_type in prompt
    assert 'Output ONLY valid JSON array, no explanation.' in prompt


# ── pick_tag_llm ──────────────────────────────────────────────────────────────


def test_no_local_model_is_loaded_when_openai_is_configured():
    records = []
    assert pick_tag_llm(_log_sink(records), True, 'gpt-oss:20b', object()) is None
    assert records == []


# ── probe_tts_duration ────────────────────────────────────────────────────────


class _FakeRun:
    """The one ``subprocess`` call ``probe_tts_duration`` makes."""

    def __init__(self, stdout='', boom=None):
        self.stdout = stdout
        self._boom = boom
        self.argv = None

    def run(self, argv, **_kw):
        self.argv = argv
        if self._boom is not None:
            raise self._boom
        return self


def test_the_duration_is_read_out_of_the_ffprobe_json():
    sp = _FakeRun(stdout=json.dumps({'format': {'duration': '931.44'}}))
    assert probe_tts_duration(sp, '/tmp/narration.mp3') == 931.44
    assert '/tmp/narration.mp3' in sp.argv


def test_an_ffprobe_that_cannot_be_read_falls_back_to_ten_minutes():
    assert probe_tts_duration(_FakeRun(stdout='not json'), '/tmp/narration.mp3') == 600.0
    assert probe_tts_duration(_FakeRun(boom=OSError('no ffprobe')), '/tmp/narration.mp3') == 600.0


# ── fmt_srt ───────────────────────────────────────────────────────────────────


def test_a_time_is_formatted_as_an_srt_timestamp_with_a_comma():
    assert fmt_srt(0.0) == '00:00:00,000'
    assert fmt_srt(1.5) == '00:00:01,500'
    assert fmt_srt(3661.25) == '01:01:01,250'


def test_a_negative_time_clamps_to_zero_rather_than_writing_a_minus_sign():
    assert fmt_srt(-5.0) == '00:00:00,000'


# ── the subtitle entry grouping ───────────────────────────────────────────────


def test_the_raw_word_stream_is_grouped_eight_words_to_an_entry():
    timings = [(f'w{i}', float(i)) for i in range(20)]
    entries = _raw_srt_entries(timings)
    assert len(entries) == 3
    assert entries[0][2] == 'w0 w1 w2 w3 w4 w5 w6 w7'
    assert entries[0][0] == 0.0


def test_an_entry_never_runs_into_the_next_ones_first_word():
    # the eighth word claims five seconds of its own, which would overrun the ninth
    timings = [(f'w{i}', float(i)) for i in range(7)] + [('w7', 7.0, 5.0)]
    timings += [(f'w{i}', float(i)) for i in range(8, 16)]
    first_end = _raw_srt_entries(timings)[0][1]
    assert first_end == 8.0 - 0.05


def test_a_word_that_carries_its_own_duration_extends_the_entry():
    timings = [('a', 0.0), ('b', 1.0, 2.5)]
    assert _raw_srt_entries(timings)[0][1] == 3.5


def test_every_entry_lasts_at_least_three_tenths_of_a_second():
    timings = [('a', 0.0), ('b', 0.01)]
    start, end, _line = _raw_srt_entries(timings)[0]
    assert end - start >= 0.3


def test_with_no_word_timings_the_script_is_spread_over_the_measured_duration():
    script = ' '.join(f'word{i}' for i in range(27))
    entries = estimated_srt_entries(script, 90.0)
    assert len(entries) == 3
    assert entries[0][0] == 0.0
    assert entries[-1][1] == 90.0
    assert entries[0][2].split() == [f'word{i}' for i in range(9)]


def test_an_empty_word_stream_is_reported_as_estimated_timing():
    entries, source = srt_entries('One sentence of narration here.', [], 30.0)
    assert source == 'estimated'
    assert entries


# ── stage_6a_srt ──────────────────────────────────────────────────────────────


def test_the_srt_file_is_written_beside_the_video_and_recorded_in_the_state(tmp_path):
    records = []
    state = {}
    script = ' '.join(f'word{i}' for i in range(18))
    path = stage_6a_srt(_log_sink(records), script, str(tmp_path), state, 'Crime_Chronicles_Case', 60.0, [])

    assert path == os.path.join(str(tmp_path), 'Crime_Chronicles_Case.srt')
    assert state['srt_path'] == path
    body = open(path).read()
    assert body.startswith('1\n00:00:00,000 --> ')
    assert '\n\n2\n' in body
    assert body.endswith('\n\n')
    assert ('INFO', 'Stage 6', 'SRT: 2 entries (estimated)') in records


def test_an_unwritable_output_directory_is_a_warning_and_no_path(tmp_path):
    records = []
    missing = tmp_path / 'does' / 'not' / 'exist'
    assert stage_6a_srt(_log_sink(records), 'A sentence.', str(missing), {}, 'T', 10.0, []) is None
    assert [r for r in records if r[0] == 'WARNING' and 'SRT generation failed' in r[2]]


# ── card_sentences ────────────────────────────────────────────────────────────


def _script(n, length=70):
    return ' '.join('%s.' % ('s%d ' % i + 'x' * length) for i in range(n))


def test_only_sentences_longer_than_sixty_characters_can_become_a_doc_card():
    script = 'Short one. ' + 'A sentence long enough to be quoted on a case-file card without trouble.'
    cards, n_long = card_sentences(script, 600.0)
    assert n_long == 1
    assert len(cards) == 1
    assert cards[0].startswith('A sentence long enough')


def test_the_card_count_follows_the_narration_duration_between_four_and_twelve():
    script = _script(40)
    assert len(card_sentences(script, 55.0 * 7)[0]) == 7
    assert len(card_sentences(script, 10.0)[0]) == 4
    assert len(card_sentences(script, 55.0 * 50)[0]) == 12


def test_the_chosen_sentences_are_spread_over_the_whole_script():
    script = _script(24)
    cards, n_long = card_sentences(script, 55.0 * 4)
    assert n_long == 24
    assert [c.split()[0] for c in cards] == ['s0', 's6', 's12', 's18']
