# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The children's-music writing legs on Opus 5 through the subscription (2026-10-02).

Three steps write what a children's song IS — the daily series' moment, the lyric, and the
one-picture-per-clip storyboard — and all three now ask Claude Opus 5 through the operator's
login. Pinned here:

  * the turn goes through subscription_llm (the CLI on the login) with the model NAMED, so
    no tier mapping can quietly answer with something cheaper, and nothing in this path can
    reach an API key: `kids_llm` imports no SDK, and the spawn env of the turn it asks for
    carries no ANTHROPIC_* variable;
  * Opus first, the LOCAL model second, the caller's own floor (template / motif deck /
    hand-written pool) last — a weekly-limit refusal must land on Ollama, never on billing;
  * the backend that actually answered reaches the manifest, so a song can be read back to
    the model that wrote it;
  * the local prompts are byte-identical to the pre-Opus ones (they are the fallback), and
    the Opus prompts carry what the local ones could not: the section map with the chorus,
    each line's syllable budget, the filtered words, and — for the storyboard — the whole
    sequence in one turn;
  * the validators downstream of the model did not move: a banned word still loses its line,
    title-cased JSON keys are still folded, a short answer is still padded from the model's
    own lines.

CPU-only: no CLI, no ollama, no GPU — every model answer here is a stub.
"""

import json
import os
import sys

import pytest

from tests import _tree

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CREWS not in sys.path:
    sys.path.insert(0, _CREWS)

from zyg_workflows import kids_llm  # noqa: E402
from zyg_workflows import kids_music_service as M  # noqa: E402
from zyg_workflows import kids_music_theory as T  # noqa: E402
from zyg_workflows import kids_series_people as P  # noqa: E402
from zyg_workflows import kids_video_service as V  # noqa: E402
from zyg_workflows import subscription_llm as S  # noqa: E402

BRIEF = {
    'theme': 'a happy green tractor and his farm friends',
    'age_band': 'preschool',
    'mood': 'happy',
    'seconds': 60,
    'sung': True,
    'style': 'storytime',
    'singer': 'adult_male',
    'title': '',
}

LYRICS = [
    'The green tractor wakes up',
    'He rolls out through the big red gate',
    'Green tractor, beep beep beep',
    'The cow and duck can hardly wait',
    'He puts the hay in piles',
    'The woolly sheep all hop and run',
]


class _Usage:
    input_tokens = 11
    output_tokens = 22
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _Block:
    def __init__(self, text):
        self.type, self.text = 'text', text


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]
        self.usage = _Usage()
        self.session_id = 'sid-test'
        self.model = 'claude-opus-5'


@pytest.fixture
def opus(monkeypatch):
    """Opus available and answering. Returns the recorder of what it was asked."""
    seen = []
    answer = {'text': '{"ok": true}'}

    def fake_run_turn(messages, **kw):
        seen.append({'messages': messages, **kw})
        if isinstance(answer.get('raise'), BaseException):
            raise answer['raise']
        return _Resp(answer['text'] if not callable(answer['text']) else answer['text'](len(seen)))

    monkeypatch.setattr(S, 'run_turn', fake_run_turn)
    monkeypatch.setattr(kids_llm, 'opus_available', lambda: True)
    monkeypatch.delenv('ZYG_KIDSMUSIC_LLM_BACKEND', raising=False)
    monkeypatch.setattr(kids_llm, 'BACKEND', 'subscription')
    return {'seen': seen, 'answer': answer}


@pytest.fixture
def no_ollama(monkeypatch):
    """The local model is DOWN, so a test that reaches it fails loudly instead of
    silently hitting a real server (the candidate-pool fixture learned that the hard way)."""
    calls = []

    def fake_ask_ollama(prompt, **kw):
        calls.append(prompt)
        return None, {'backend': 'ollama', 'model': kids_llm.OLLAMA_MODEL, 'reason': 'LLM unavailable (URLError)'}

    monkeypatch.setattr(kids_llm, '_ask_ollama', fake_ask_ollama)
    return calls


# ── the router ───────────────────────────────────────────────────────────────


def test_parse_json_shapes():
    assert kids_llm.parse_json('{"a": 1}') == {'a': 1}
    assert kids_llm.parse_json('```json\n{"a": 1}\n```') == {'a': 1}
    assert kids_llm.parse_json('Here you go:\n{"a": 1}\nHope that helps.') == {'a': 1}
    assert kids_llm.parse_json('no json here') is None
    assert kids_llm.parse_json('') is None
    assert kids_llm.parse_json('[1, 2]') is None  # an object, not a list


def test_backend_env_switches_off(monkeypatch):
    monkeypatch.setattr(kids_llm, 'opus_available', lambda: True)
    monkeypatch.setenv('ZYG_KIDSMUSIC_LLM_BACKEND', 'ollama')
    assert kids_llm.opus_on() is False
    monkeypatch.setenv('ZYG_KIDSMUSIC_LLM_BACKEND', 'subscription')
    assert kids_llm.opus_on() is True


def test_no_login_means_no_opus(monkeypatch):
    monkeypatch.setattr(S, 'login_present', lambda: False)
    assert kids_llm.opus_available() is False


def test_opus_is_named_not_inferred(opus, no_ollama):
    """resolve_model() maps a requested family onto the documentary pipeline's own tiers —
    'opus' there is the script tier, which an env var can repoint. The model is passed
    explicitly so nothing downstream can answer with a cheaper one."""
    kids_llm.ask_json(opus_prompt='p', ollama_prompt='q', stage='st')
    assert opus['seen'][0]['model'] == 'claude-opus-5'
    assert opus['seen'][0]['stage'] == 'st'
    assert not no_ollama  # Opus answered; the local model was never asked


def test_limit_falls_back_to_the_local_model_never_to_a_key(opus, no_ollama):
    opus['answer']['raise'] = S.SubscriptionLimitError("you've hit your weekly limit")
    data, info = kids_llm.ask_json(opus_prompt='p', ollama_prompt='q', stage='st')
    assert data is None  # the local model is down too in this test
    assert info['fallback'] is True
    assert no_ollama == ['q']  # asked, with the LOCAL prompt
    assert 'weekly limit' in info['reason']  # the Opus reason is the one kept
    assert info['backend'] == 'ollama'


def test_unparseable_opus_answer_falls_back(opus, no_ollama):
    opus['answer']['text'] = 'I had a think about this and here are some lovely ideas!'
    data, info = kids_llm.ask_json(opus_prompt='p', ollama_prompt='q', stage='st')
    assert data is None and no_ollama == ['q']
    assert 'no JSON object' in info['reason']


def test_nothing_in_this_path_can_bill_an_api_key():
    src = open(_tree.pkg('kids_llm.py'), encoding='utf-8').read()
    assert 'import anthropic' not in src
    assert 'ANTHROPIC_API_KEY' not in src
    # The turn itself: subscription_llm strips every ANTHROPIC_* from the spawn env.
    env = S._env(2000)
    assert not [k for k in env if k.startswith('ANTHROPIC_')]


# ── the lyric ────────────────────────────────────────────────────────────────


def _probe_order():
    probe = T.compose(BRIEF, seed=0)
    return probe['order'], len(probe['order']) * 2, T._syllable_targets(BRIEF, len(probe['order']))


def test_section_map_marks_the_chorus_and_its_repeats():
    one = M._section_map(['A', 'B', 'A', 'C'], [6, 8] * 4, 8)
    assert 'CHORUS (section B)' in one and 'lines 3-4' in one
    assert 'catchiest' in one and 'word for word' not in one
    two = M._section_map(['A', 'B', 'A', 'B'], [6, 8] * 4, 8)
    assert 'word for word' in two and '3-4 and 7-8' in two


def test_lyric_prompt_carries_the_budget_and_the_filter():
    order, n, syl = _probe_order()
    p = M._lyric_prompt_opus(BRIEF, n, syl, order, 7, 5, 9, False, '')
    assert f'exactly {n} sung lines' in p
    assert 'between 5 and 9 syllables' in p
    assert 'about 6 and 8 syllables' in p  # each line's own target
    for w in ('kill', 'blood', 'stupid'):  # the filter that silently drops a line
        assert w in p
    assert 'ONE PICTURE for every line' in p  # true since the 2026-10-02 cadence
    assert '"title"' in p and '"lines"' in p


def test_lyric_prompt_facts_mode_keeps_the_one_fact_grammar():
    order, n, syl = _probe_order()
    brief = dict(BRIEF, lyrics_mode='facts', subject='Train')
    p = M._lyric_prompt_opus(brief, n, syl, order, 7, 5, 9, True, '')
    assert 'EDUCATIONAL' in p and 'Subject: Train' in p
    assert 'SAME short sentence pattern' in p


def test_write_lyrics_on_opus(opus, no_ollama):
    order, n, syl = _probe_order()
    opus['answer']['text'] = json.dumps(
        {
            'Title': 'The Happy Green Tractor',  # title-cased keys still fold
            'lines': [f'Line number {i} rolls along' for i in range(n)],
        }
    )
    lines, title, src, info = M.write_lyrics(BRIEF, n, syl, order=order)
    assert src == 'llm' and len(lines) == n
    assert title == 'The Happy Green Tractor'
    assert info['backend'] == 'subscription' and info['model'] == 'claude-opus-5'
    assert info['fallback_backend'] is False
    assert not no_ollama
    # The section map reached the model.
    assert "The song's shape" in opus['seen'][0]['messages'][0]['content']


def test_write_lyrics_still_drops_a_banned_line_and_pads_from_its_own(opus, no_ollama):
    order, n, syl = _probe_order()
    opus['answer']['text'] = json.dumps(
        {'title': 'T', 'lines': ['Tractor rolls along', 'The engine is dead', 'Hens hop on the seat']}
    )
    lines, _title, src, info = M.write_lyrics(BRIEF, n, syl, order=order)
    assert 'The engine is dead' not in lines  # the filter is unchanged
    assert src == 'llm (padded)' and len(lines) == n
    assert lines[:2] == ['Tractor rolls along', 'Hens hop on the seat']
    assert lines[2] == lines[0]  # cycles its own lines, not the template


def test_write_lyrics_template_floor_when_both_models_are_down(opus, no_ollama):
    order, n, syl = _probe_order()
    opus['answer']['raise'] = S.SubscriptionLLMError('cli missing')
    lines, _t, src, info = M.write_lyrics(BRIEF, n, syl, order=order)
    assert src == 'fallback' and len(lines) == n
    assert info['backend'] == 'ollama' and info['fallback_backend'] is True


def test_the_local_lyric_prompt_did_not_change(opus, no_ollama):
    """The fallback prompt is the one that shipped ten songs; it must reach Ollama verbatim."""
    order, n, syl = _probe_order()
    opus['answer']['raise'] = S.SubscriptionLimitError('limit')
    M.write_lyrics(BRIEF, n, syl, order=order)
    sent = no_ollama[0]
    assert sent.startswith('You write lyrics for young children. Reply with JSON only.')
    assert 'lines 1-2 and 5-6 should rhyme in pairs' in sent
    assert '{"title": "...", "lines": ["...", "..."]}' in sent


# ── the storyboard ───────────────────────────────────────────────────────────


def test_idea_batch_is_the_whole_film_on_opus_and_tens_locally(monkeypatch):
    monkeypatch.setattr(kids_llm, 'opus_available', lambda: True)
    monkeypatch.setenv('ZYG_KIDSMUSIC_LLM_BACKEND', 'subscription')
    assert V.idea_batch(14) == 14
    monkeypatch.setenv('ZYG_KIDSVIDEO_IDEA_BATCH_OPUS', '6')
    assert V.idea_batch(14) == 6
    monkeypatch.delenv('ZYG_KIDSVIDEO_IDEA_BATCH_OPUS')
    monkeypatch.setenv('ZYG_KIDSMUSIC_LLM_BACKEND', 'ollama')
    assert V.idea_batch(14) == V.IDEA_BATCH == 10


def test_ideas_prompt_says_what_a_picture_has_to_survive():
    p = V._ideas_prompt_opus(
        BRIEF, {'order': ['A', 'B']}, LYRICS, 14, 'a green tractor', '', 0, 14, 'Storytime', '1. one\n2. two'
    )
    assert 'exactly 14 picture descriptions' in p
    assert 'FIRST FRAME' in p and 'still camera' in p  # every picture becomes an LTX clip
    assert 'style is added automatically' in p  # build_prompt prefixes it
    assert '14 pictures for 6 sung lines' in p
    assert 'a green tractor' in p
    assert '"hero"' in p and '"pictures"' in p


def test_whole_storyboard_in_one_turn_on_opus(opus, no_ollama):
    opus['answer']['text'] = json.dumps(
        {
            'hero': 'a happy green tractor',
            'pictures': [f'A happy green tractor does thing {i} in a sunny field' for i in range(14)],
        }
    )
    ideas, info = V.llm_ideas(BRIEF, {'order': ['A', 'B']}, LYRICS, 14)
    assert len(ideas) == 14
    assert info['batches'] == 1  # not two batches of ten
    assert info['backend'] == 'subscription' and info['model'] == 'claude-opus-5'
    assert info['hero'] == 'a happy green tractor'
    assert not no_ollama


def test_storyboard_falls_back_to_the_motif_deck_when_both_are_down(opus, no_ollama):
    opus['answer']['raise'] = S.SubscriptionLimitError('limit')
    ideas, info = V.llm_ideas(BRIEF, {'order': ['A', 'B']}, LYRICS, 14)
    assert ideas == [] and info['got'] == 0
    assert no_ollama and no_ollama[0].startswith('You plan the pictures for a cartoon music video')
    # assign_ideas' own floor: every slot still gets something to show.
    slots = [{'i': i, 'burst': False, 'seconds': 5.0} for i in range(6)]
    out = V.assign_ideas(slots, BRIEF, {'order': ['A', 'B'], 'lyrics': LYRICS}, seed=1)
    assert all(s['idea'] for s in slots)
    assert out['from_song'] == 0 and out['from_motifs'] == 6


# ── the daily series' moment ─────────────────────────────────────────────────


def test_series_moment_on_opus(opus, no_ollama):
    opus['answer']['text'] = json.dumps({'Moment': 'Jack carries a very full cup of milk'})
    got = P.propose_moment('jack', avoid=set())
    assert got == 'Jack carries a very full cup of milk'
    sent = opus['seen'][0]['messages'][0]['content']
    assert 'Jack is four' in sent  # the child's world
    assert 'fourteen pictures' in sent  # why it has to be drawable
    assert not no_ollama


def test_series_moment_falls_back_to_the_pool(opus, no_ollama):
    opus['answer']['raise'] = S.SubscriptionLimitError('limit')
    assert P.propose_moment('mona', avoid=set()) == ''  # '' is what sends pick_moment to the pool
    assert no_ollama and no_ollama[0].startswith('You write episode ideas for a song series')
    assert P.pool_moment('mona', avoid=set())
