# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers carved out of ``_crime_stage_3_script``.

The 606-line stage function could only ever be exercised by running the whole
crime pipeline; these tests pin the behaviour of the pure pieces — preamble
stripping, prompt assembly, the enriched-source choice, the expansion ladder and
the LLM-free structured narration — with plain inputs: no GPU, no network, no
services.
"""

import pytest

from zyg_workflows.pipeline_crime.stage3_script_fallback import (
    CrimeCaseFacts,
    _build_structured_narration,
    _narration_intro_and_background,
    _narration_legacy_and_closing,
    _narration_trial_and_verdict,
)
from zyg_workflows.pipeline_crime.stage3_script_llm import (
    _MIN_WORDS,
    _build_enriched_source,
    _build_expansion_prompt,
    _build_haiku_prefill_prompt,
    _build_script_prompt,
    _expand_to_min_words,
    _llm_text,
    _run_haiku_prefill,
    _strip_llm_preamble,
    _try_claude_script,
    _try_gpt_script,
    _try_ollama_script,
)

CASE = {
    'name': 'John Doe',
    'crime_category': 'fraud',
    'year': 1987,
    'state': 'Ohio',
    'court': 'the Ohio Supreme Court',
    'summary': 'A long and detailed summary of what happened.',
    'why_narrate': 'It reshaped sentencing law.',
    'case_title': 'The Ledger Case',
    'description': 'a financier',
}


class _FakeLog:
    """Collect the (level, stage, message) triples the stage logger is handed."""

    def __init__(self):
        self.lines = []

    def __call__(self, level, stage, message):
        self.lines.append((level, stage, message))

    def levels(self):
        return [line[0] for line in self.lines]


# ── _strip_llm_preamble ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    'raw',
    [
        'Here is the full narration script:\nThe narration begins.',
        'Certainly!\nThe narration begins.',
        '**Note:**\nThe narration begins.',
        'Title: The Ledger Case\nThe narration begins.',
        'Narration: The narration begins.',
        '   The narration begins.   ',
    ],
)
def test_the_preamble_stripper_leaves_only_the_narration(raw):
    assert _strip_llm_preamble(raw) == 'The narration begins.'


def test_the_preamble_stripper_keeps_narration_that_has_no_preamble():
    body = 'Welcome to Crime Chronicles. The case is titled: The Ledger Case.'
    assert _strip_llm_preamble(body) == body


# ── prompt assembly ──────────────────────────────────────────────────────────


def test_the_script_prompt_carries_the_framework_block_facts_and_metadata():
    prompt = _build_script_prompt('FRAMEWORK BLOCK', 'CASE TEXT', CASE)
    assert 'FRAMEWORK BLOCK' in prompt
    assert 'CASE FACTS:\nCASE TEXT' in prompt
    assert 'SUBJECT: John Doe' in prompt
    assert 'CRIME CATEGORY: fraud' in prompt
    assert 'YEAR: 1987' in prompt
    # the floor the structured fallback and the expansion ladder both key off
    assert 'MINIMUM 1400 words' in prompt
    assert prompt.endswith('Write the full narration script now (minimum 1400 words):')


def test_the_script_prompt_tolerates_a_case_with_no_metadata():
    prompt = _build_script_prompt('', '', {})
    assert 'SUBJECT: \n' in prompt
    assert 'CRIME CATEGORY: \n' in prompt


def test_the_haiku_prompt_asks_the_seven_research_questions():
    prompt = _build_haiku_prefill_prompt(CASE)
    assert '"John Doe" (fraud case, 1987)' in prompt
    for n in range(1, 8):
        assert f'\n{n}. ' in prompt
    assert '300-400 words' in prompt


def test_the_haiku_prompt_falls_back_to_placeholders_for_an_empty_case():
    assert '"this subject" (crime case, )' in _build_haiku_prefill_prompt({})


# ── _build_enriched_source ───────────────────────────────────────────────────


def test_an_empty_prefill_leaves_the_court_text_untouched():
    assert _build_enriched_source('', 'COURT TEXT') == 'COURT TEXT'


def test_a_prefill_is_labelled_and_placed_ahead_of_the_court_text():
    out = _build_enriched_source('RESEARCH', 'COURT TEXT')
    assert out == ('ENRICHED CONTEXT (AI research supplement):\nRESEARCH\n\n--- PRIMARY CASE FACTS ---\nCOURT TEXT')
    assert out.index('RESEARCH') < out.index('COURT TEXT')


# ── the expansion ladder ─────────────────────────────────────────────────────


def test_the_expansion_prompt_asks_for_the_shortfall_plus_two_hundred_words():
    prompt = _build_expansion_prompt('EXISTING', 900, 1300)
    assert 'Add approximately 600 more words' in prompt
    assert 'Minimum 1300 words total.' in prompt
    assert prompt.endswith('EXISTING SCRIPT:\nEXISTING\n\nCONTINUE AND EXPAND:')


def test_llm_text_accepts_a_string_a_content_object_or_anything_else():
    class _WithContent:
        content = 'from content'

    class _Other:
        def __str__(self):
            return 'from str'

    assert _llm_text('plain') == 'plain'
    assert _llm_text(_WithContent()) == 'from content'
    assert _llm_text(_Other()) == 'from str'


class _ScriptedLLM:
    """Return the queued replies in order, recording every prompt it was sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def call(self, messages):
        self.prompts.append(messages[0]['content'])
        return self.replies.pop(0)


def test_a_long_enough_script_is_never_sent_for_expansion():
    llm = _ScriptedLLM([])
    log = _FakeLog()
    script = 'word ' * 20
    out, wc = _expand_to_min_words(llm, script, 20, 'qwen', 10, log)
    assert (out, wc) == (script, 20)
    assert llm.prompts == []
    assert log.lines == []


def test_the_expansion_ladder_stops_as_soon_as_the_floor_is_reached():
    log = _FakeLog()
    llm = _ScriptedLLM(['word ' * 12, 'unused'])
    out, wc = _expand_to_min_words(llm, 'word ' * 5, 5, 'qwen', 10, log)
    assert wc == 12
    assert out.split() == ['word'] * 12
    assert len(llm.prompts) == 1
    assert log.levels() == ['WARNING']


def test_the_expansion_ladder_gives_up_after_three_rounds_and_keeps_the_longest():
    log = _FakeLog()
    llm = _ScriptedLLM(['word ' * 6, 'word ' * 2, 'word ' * 7])
    out, wc = _expand_to_min_words(llm, 'word ' * 5, 5, 'qwen', 100, log)
    assert wc == 7  # the shorter round-2 reply was discarded
    assert out.split() == ['word'] * 7
    assert len(llm.prompts) == 3
    assert log.levels() == ['WARNING', 'WARNING', 'WARNING']


def test_the_word_floor_is_still_thirteen_hundred():
    # the pipeline needs ≥1232 words for 8.5 min of TTS
    assert _MIN_WORDS == 1300


# ── the provider chain short-circuits without credentials ────────────────────


def test_claude_and_gpt_are_skipped_silently_when_no_api_key_is_set(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    log = _FakeLog()
    assert _try_claude_script('PROMPT', 'pid', log) == ''
    assert _try_gpt_script('PROMPT', 'pid', log) == ''
    assert log.lines == []


def test_the_haiku_prefill_is_skipped_when_the_source_is_already_rich(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    log = _FakeLog()
    assert _run_haiku_prefill(CASE, 'word ' * 400, 'pid', log) == ''
    assert log.lines == []


def test_the_haiku_prefill_is_skipped_when_there_is_no_api_key(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    log = _FakeLog()
    assert _run_haiku_prefill(CASE, 'thin facts', 'pid', log) == ''
    assert log.lines == []


def test_ollama_is_skipped_when_the_host_is_unavailable(monkeypatch):
    monkeypatch.setattr('zyg_workflows.pipeline_crime.stage3_script_llm.OLLAMA_AVAILABLE', False)
    log = _FakeLog()
    assert _try_ollama_script('PROMPT', log) == (None, None, '')
    assert log.lines == []


# ── CrimeCaseFacts ───────────────────────────────────────────────────────────


def test_the_case_facts_carry_the_original_defaults_for_an_empty_case():
    facts = CrimeCaseFacts.from_selected({})
    assert facts.name == 'the subject'
    assert facts.category == 'serious offense'
    assert facts.title == 'The Case of the subject'
    assert facts.location == 'the United States'
    assert facts.when_phrase == 'In a period that would become etched in history, '


def test_a_state_and_a_year_become_the_location_and_the_opening_phrase():
    facts = CrimeCaseFacts.from_selected(CASE)
    assert facts.location == 'the state of Ohio'
    assert facts.when_phrase == 'In 1987, '
    assert facts.title == 'The Ledger Case'
    assert facts.year == '1987'  # always a string, even for an int in the case dict


# ── the structured narration ─────────────────────────────────────────────────


def test_the_structured_narration_is_long_enough_for_the_tts_floor():
    script = _build_structured_narration(CASE)
    assert len(script.split()) >= 1232
    assert script.startswith('Welcome to Crime Chronicles. ')
    assert script.endswith('from the public record of American criminal justice.')


def test_the_structured_narration_quotes_the_case_summary_and_the_why():
    script = _build_structured_narration(CASE)
    assert CASE['summary'] in script
    assert CASE['why_narrate'] in script
    assert 'The Ledger Case' in script
    assert 'the Ohio Supreme Court' in script
    assert 'the state of Ohio' in script


def test_the_structured_narration_is_the_four_parts_in_order():
    facts = CrimeCaseFacts.from_selected(CASE)
    parts = [
        _narration_intro_and_background(facts),
        _narration_trial_and_verdict(),
        _narration_legacy_and_closing(facts),
    ]
    script = _build_structured_narration(CASE)
    offsets = [script.index(part) for part in parts]
    assert offsets == sorted(offsets)
    assert ''.join(parts) != script  # the facts/investigation part sits between the first two


def test_the_structured_narration_still_reads_for_a_case_with_no_metadata():
    script = _build_structured_narration({})
    assert 'The Case of the subject' in script
    assert 'the United States' in script
    assert 'fell under the category of serious offense' in script
    assert len(script.split()) >= 1200
