# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers extracted from `stage_05_visual_intent_tagging`.

Every one of these was a closure or an inline block of the 750-line stage, so
none of this logic had ever been exercised on its own. Nothing here touches the
GPU, the network, Ollama or Anthropic: the two provider calls are reached only
through `_llm_scene_batch`, and the tests that go through it either hit the
benchmark-replay short circuit or stub the batch function itself.
"""

import pytest

from zyg_workflows.scholarly.stages_01_18 import stage_05_scenes
from zyg_workflows.scholarly.stages_01_18.stage_05_keywords import (
    _ANATOMY_HINTS_BY_TAG,
    _TAG_KEYWORDS,
    _tag_sentence,
)
from zyg_workflows.scholarly.stages_01_18.stage_05_scenes import (
    SceneDescJob,
    _fill_scene_descs,
    _generic_fallback_stats,
    _llm_scene_batch,
    _padded_descs,
    _prefill_inline_scenes,
    _scene_batch_prompt,
)


def _job(**kw):
    """A `SceneDescJob` that can reach no provider: no key, no replay, a debug
    sink that records what it was told."""
    kw.setdefault('topic', 'gladiators')
    kw.setdefault('pipeline_id', 'pid-1')
    kw.setdefault('api_key', '')
    kw.setdefault('replay_descs', None)
    kw.setdefault('debug', lambda *a: None)
    return SceneDescJob(**kw)


# ── _tag_sentence ─────────────────────────────────────────────────────────


def test_tag_sentence_picks_the_table_entry_with_the_most_hits():
    """Two keywords of 'telescope observatory' beat one of 'deep space vista'."""
    assert _tag_sentence('The astronomer aimed the telescope at a star.', 'space') == 'telescope observatory'


def test_tag_sentence_falls_back_to_the_generic_topic_tag():
    """No keyword hit at all -> '<topic> related imagery', the string the quality
    gate counts as a fallback."""
    assert _tag_sentence('Zzz qqq xxx.', 'gladiators') == 'gladiators related imagery'


def test_tag_sentence_is_case_insensitive():
    """The sentence is lowercased before matching, so shouting does not untag."""
    assert _tag_sentence('MEDIEVAL EMPIRE AT WAR', 'x') == _tag_sentence('medieval empire at war', 'x')


def test_every_anatomy_hint_tag_is_a_real_keyword_tag():
    """The hint table is looked up by keyword tag, so a typo there would silently
    give every shot of that category an empty anatomy hint."""
    assert set(_ANATOMY_HINTS_BY_TAG) <= set(_TAG_KEYWORDS)


# ── _scene_batch_prompt ───────────────────────────────────────────────────


def test_scene_batch_prompt_numbers_the_sentences_and_names_the_topic():
    """The prompt carries the topic and a 1-based numbered list, which is what
    makes the model's JSON array index-alignable to the batch."""
    prompt = _scene_batch_prompt(['First one.', 'Second one.'], 'gladiators')
    assert 'Topic: gladiators' in prompt
    assert '1. First one.' in prompt
    assert '2. Second one.' in prompt
    assert 'valid JSON array' in prompt


# ── _padded_descs ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('parsed', 'n', 'expected'),
    [
        (['a', 'b'], 2, ['a', 'b']),
        ([' a ', 'b'], 2, ['a', 'b']),
        (['a'], 3, ['a', '', '']),
        ([], 2, ['', '']),
        (['a', 'b', 'c'], 2, ['a', 'b', 'c']),
        ({'nope': 1}, 2, []),
        ('a string', 2, []),
    ],
)
def test_padded_descs_keeps_indexing_correct(parsed, n, expected):
    """A short answer is padded with empty strings, a long one is left long, and
    anything that is not a list is rejected so the caller tries the next
    provider — exactly what the pre-split if/elif ladder did."""
    assert _padded_descs(parsed, n) == expected


# ── _llm_scene_batch ──────────────────────────────────────────────────────


def test_llm_scene_batch_replays_the_recorded_descs_without_a_provider():
    """In benchmark replay the pool is cycled to the batch length and no provider
    is contacted at all."""
    got = _llm_scene_batch(_job(replay_descs=['one', 'two']), ['s1', 's2', 's3'])
    assert got == ['one', 'two', 'one']


def test_llm_scene_batch_tries_ollama_when_claude_returns_nothing(monkeypatch):
    """No API key means the Claude branch yields [], and the Ollama branch is the
    one whose answer comes back."""
    seen = []

    def _fake_ollama(job, sents, prompt):
        seen.append((len(sents), 'Topic: gladiators' in prompt))
        return ['from ollama'] * len(sents)

    monkeypatch.setattr(stage_05_scenes, '_ollama_scene_batch', _fake_ollama)
    assert _llm_scene_batch(_job(), ['s1']) == ['from ollama']
    assert seen == [(1, True)]


def test_llm_scene_batch_prefers_claude_over_ollama(monkeypatch):
    """A non-empty Claude answer short-circuits: Ollama is never called."""
    monkeypatch.setattr(stage_05_scenes, '_claude_scene_batch', lambda j, s, p: ['from claude'])
    monkeypatch.setattr(
        stage_05_scenes,
        '_ollama_scene_batch',
        lambda j, s, p: pytest.fail('Ollama must not be reached when Claude answered'),
    )
    assert _llm_scene_batch(_job(api_key='sk-test'), ['s1']) == ['from claude']


# ── _prefill_inline_scenes ────────────────────────────────────────────────


def test_prefill_inline_scenes_fills_by_index_and_counts():
    """Stage 3's inline scene list is aligned to the sentences by index; blank and
    non-string entries are left for the LLM batch below."""
    tags = [{'tag': 't%d' % i} for i in range(4)]
    assert _prefill_inline_scenes(tags, ['  a  ', '', None, 'd']) == 2
    assert [t.get('scene_desc') for t in tags] == ['a', None, None, 'd']


def test_prefill_inline_scenes_ignores_entries_past_the_end():
    """A longer inline list than there are sentences must not raise."""
    tags = [{'tag': 't0'}]
    assert _prefill_inline_scenes(tags, ['a', 'b', 'c']) == 1


# ── _fill_scene_descs ─────────────────────────────────────────────────────


def test_fill_scene_descs_batches_and_falls_back_to_the_keyword_tag(monkeypatch):
    """Sentences are sent in batches of `batch`; an entry the provider returned
    nothing for keeps its keyword tag as the scene description, so downstream
    always has a non-empty string."""
    calls = []

    def _fake_batch(job, sents):
        calls.append(list(sents))
        return ['desc-' + s for s in sents[:1]]  # only the first of each batch answered

    monkeypatch.setattr(stage_05_scenes, '_llm_scene_batch', _fake_batch)
    sentences = ['s0', 's1', 's2']
    tags = [{'sentence': s, 'tag': 'tag-' + s} for s in sentences]
    assert _fill_scene_descs(tags, sentences, _job(), batch=2) == 2
    assert calls == [['s0', 's1'], ['s2']]
    assert [t['scene_desc'] for t in tags] == ['desc-s0', 'tag-s1', 'desc-s2']


def test_fill_scene_descs_skips_a_fully_prefilled_batch(monkeypatch):
    """A batch whose every sentence already carries a scene_desc costs no API
    call, and a prefilled entry is never overwritten."""
    calls = []

    def _fake_batch(job, sents):
        calls.append(list(sents))
        return ['new-' + s for s in sents]

    monkeypatch.setattr(stage_05_scenes, '_llm_scene_batch', _fake_batch)
    sentences = ['s0', 's1', 's2']
    tags = [{'sentence': s, 'tag': 'tag-' + s} for s in sentences]
    tags[0]['scene_desc'] = 'kept'
    tags[1]['scene_desc'] = 'kept too'
    assert _fill_scene_descs(tags, sentences, _job(), batch=2) == 1
    assert calls == [['s2']]
    assert [t['scene_desc'] for t in tags] == ['kept', 'kept too', 'new-s2']


# ── _generic_fallback_stats ───────────────────────────────────────────────


def test_generic_fallback_stats_counts_the_generic_tag():
    """Half generic is 50%, which is over the stage's 30% warning threshold."""
    topic = 'gladiators'
    tags = [
        {'tag': 'historical archive', 'scene_desc': topic + ' related imagery'},
        {'tag': 'historical archive', 'scene_desc': 'a real scene'},
    ]
    assert _generic_fallback_stats(tags, topic) == (1, 50.0)


def test_generic_fallback_stats_uses_the_tag_when_there_is_no_scene_desc():
    """An entry the LLM never reached counts by its keyword tag."""
    assert _generic_fallback_stats([{'tag': 'x related imagery'}], 'x') == (1, 100.0)


def test_generic_fallback_stats_survives_an_empty_tag_list():
    """max(len, 1) in the divisor: no sentences must not be a ZeroDivisionError."""
    assert _generic_fallback_stats([], 'x') == (0, 0.0)
