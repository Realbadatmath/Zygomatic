#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kids_music_service.run() with a Melodies style — the whole leg, end to end.

    ../.venv/bin/python -m pytest tests/test_kidsmusic_style_run.py

This is the join between the three pieces that were built separately: the style
table (kids_music_theory.STYLES), the sampled-instrument renderer
(melody_sampler) and the run that has to ship a filed, credited song. Each of
those has its own unit tests; none of them can tell you that a styled brief
actually produces a deliverable, because that only happens when all three agree.

No GPU, no LLM, no ComfyUI. The three things that would reach for one — the
ACE-Step leg, the lyric writer and the CLAP content gate — are stubbed, and the
stubs are honest about what they stand in for:

* `ace_available` -> False, so the SCORE render is the only leg. That is the
  point: it forces the run to stand behind the sampled render, mix margin and
  all, instead of hiding behind an ACE-Step variation.
* `write_lyrics` returns a fixed quatrain, because what is under test is where
  the style's lyric hint goes, not whether a model rhymes.
* `qc_clap` passes, because CLAP needs a 2 GB checkpoint. Which captions it was
  ASKED about is covered by tests/test_melody_styles.py.

What is deliberately NOT stubbed: composition, the MIDI, the SoundFont render,
the sampler, the mix-balance gate, the master, the licence fence and the filing.
Those are the subject.
"""

import json
import os

import pytest

from tests import _tree
from zyg_workflows import kids_music_service as K

pytest.importorskip('numpy')
pytest.importorskip('soundfile')


_LYRICS = (['one two three', 'four five six', 'one two three', 'four five six'], 'T', 'fallback', {})


@pytest.fixture
def offline(monkeypatch):
    """Everything that would need a GPU, a network or a paid API, stubbed."""
    pytest.importorskip('mido', reason='kids_music_service writes the MIDI stem with mido')
    _tree.instrument_samples()
    from zyg_workflows import audio_qc

    monkeypatch.setattr(K, 'ace_available', lambda: False)
    monkeypatch.setattr(K, 'write_lyrics', lambda *a, **kw: tuple(_LYRICS))
    monkeypatch.setattr(
        audio_qc,
        'qc_clap',
        lambda *a, **kw: {'ok': True, 'positive_prob': 0.9, 'effective_threshold': 0.5, 'scores': {}},
    )


def _run(tmp_path, brief, name='song'):
    out = str(tmp_path / name)
    man = K.run(dict(brief), out, candidates=6, want_ace=False)
    return out, man


# ── (a) a styled brief ships, filed and credited ─────────────────────────────


@pytest.fixture(scope='function')
def counting(offline, tmp_path):
    return _run(
        tmp_path,
        {
            'theme': 'counting ducks',
            'style': 'counting',
            'seconds': 25,
            'sung': True,
            'want_video': False,
            'want_ace': False,
        },
    )


def test_a_styled_brief_ships_a_sampled_render(counting):
    out, man = counting
    assert man['ok'] is True, man.get('reason') or man
    assert man['style'] == 'counting'
    assert man['family'] == 'children'
    assert man['render']['engine'] == 'sampler', man['render']
    assert os.path.isfile(os.path.join(out, 'melody.mp3'))
    # The sampler's own record travels with the manifest, but as COUNTS: the
    # sample id lists live in song.json so the board can poll this file.
    assert man['render']['voices']['lead']
    assert all(isinstance(v, int) for v in man['render']['files'].values())
    assert man['render']['fallback_reason'] == ''


def test_the_run_files_the_song_on_its_shelf(counting):
    """A styled song knows its shelf before it exists; the board never guesses."""
    out, _man = counting
    with open(os.path.join(out, 'shelf.json'), 'r', encoding='utf-8') as f:
        rec = json.load(f)
    assert rec['family'] == 'children'
    assert rec['shelf'] == 'counting'
    assert rec['by'] == 'style' and rec['filed']


def test_the_played_samples_are_credited_and_cleared(counting):
    out, man = counting
    with open(os.path.join(out, 'LICENSE.txt'), 'r', encoding='utf-8') as f:
        note = f.read()
    assert 'Sampled instruments' in note
    assert man['licence']['ok_commercial'] is True
    inst = man['licence']['instruments']
    assert inst['ok'] is True and inst['violations'] == []
    assert inst['licences'], 'no licence ids recorded for the voices played'


def test_the_ace_caption_names_the_instruments_actually_played(counting):
    """ACE-Step is conditioned on the score; its caption must describe THAT."""
    out, _man = counting
    with open(os.path.join(out, 'song.json'), 'r', encoding='utf-8') as f:
        plan = json.load(f)
    assert 'marimba' in K.ace_prompt(plan)


# ── (b) an unstyled brief is untouched ───────────────────────────────────────


def test_an_unstyled_brief_runs_exactly_as_before(offline, tmp_path):
    """The whole point of the style layer: it is opt-in, and invisible otherwise."""
    out, man = _run(
        tmp_path,
        {'theme': 'counting ducks', 'seconds': 25, 'sung': True, 'want_video': False, 'want_ace': False},
        name='plain',
    )
    assert man['ok'] is True, man.get('reason') or man
    assert man['style'] is None
    assert man['render']['engine'] == 'soundfont', man['render']
    assert not os.path.exists(os.path.join(out, 'shelf.json'))
    assert 'style' not in man['labels']


# ── (c) a sung style keeps its lyrics and its label ──────────────────────────


def test_a_sung_style_still_writes_lyrics_and_carries_its_label(offline, tmp_path):
    out, man = _run(
        tmp_path,
        {
            'theme': 'a sleepy moon',
            'style': 'lullaby',
            'seconds': 25,
            'sung': True,
            'want_video': False,
            'want_ace': False,
        },
        name='lull',
    )
    assert man['labels']['style'] == 'Lullaby'
    assert man['style'] == 'lullaby' and man['shelf'] == 'lullaby'
    assert os.path.isfile(os.path.join(out, 'lyrics.txt'))
    assert man['brief']['style'] == 'lullaby'
