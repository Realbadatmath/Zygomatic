#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kids_music_service.run() with a CINEMATIC brief — the instrumental leg.

    ../.venv/bin/python -m pytest tests/test_cinematic_run.py

Same runner as the children's workflow, three deliberate differences, and this
file exists to hold all three at once because each is invisible from inside the
piece that implements it:

  * no lyric leg      — the family has no words, so `write_lyrics` is never
                        reached and no lyrics.txt is written;
  * no picture leg    — the cinematic styles carry no `look` and no motif pools,
                        so the video is declared not applicable rather than
                        attempted and failed;
  * a different genre — the ACE caption leads with 'cinematic instrumental
                        score', not "children's music", and the CLAP gate is
                        asked about orchestral captions.

No GPU, no LLM, no ComfyUI: `ace_available` is stubbed False (so the sampled
score render is the only leg and has to stand on its own) and `qc_clap` passes
(it needs a 2 GB checkpoint). Which captions it was ASKED about is asserted
directly against kids_music_theory instead.

What is NOT stubbed: composition, the four-layer cinematic arrangement, the
MIDI, the SoundFont render, the sampler, mix balance, the master, the licence
fence and the filing. Those are the subject.
"""

import json
import os

import pytest

from tests import _tree
from zyg_workflows import kids_music_service as K
from zyg_workflows import kids_music_theory as T

pytest.importorskip('numpy')
pytest.importorskip('soundfile')


@pytest.fixture
def offline(monkeypatch):
    """Everything that would need a GPU, a network or a paid API, stubbed."""
    pytest.importorskip('mido', reason='kids_music_service writes the MIDI stem with mido')
    _tree.instrument_samples()
    from zyg_workflows import audio_qc

    monkeypatch.setattr(K, 'ace_available', lambda: False)
    monkeypatch.setattr(
        audio_qc,
        'qc_clap',
        lambda *a, **kw: {'ok': True, 'positive_prob': 0.9, 'effective_threshold': 0.5, 'scores': {}},
    )


@pytest.fixture(scope='function')
def heroic(offline, tmp_path):
    out = str(tmp_path / 'cue')
    man = K.run(
        {'theme': 'the last stand', 'style': 'heroic', 'family': 'cinematic', 'seconds': 30},
        out,
        candidates=6,
        want_ace=False,
    )
    return out, man


# ── (a) a cinematic brief ships an instrumental cue ──────────────────────────


def test_a_cinematic_brief_ships_a_sampled_cue(heroic):
    out, man = heroic
    assert man['ok'] is True, man.get('delivery', {}).get('reason') or man
    assert man['kind'] == 'melody'
    assert man['family'] == 'cinematic'
    assert man['style'] == 'heroic' and man['shelf'] == 'heroic'
    assert man['render']['engine'] == 'sampler', man['render']
    assert os.path.isfile(os.path.join(out, 'melody.mp3'))


def test_the_cue_is_arranged_in_four_layers(heroic):
    """A trio plus the style's `extra` voice — the fourth is the whole point.

    `layers` is role -> voice key as the SAMPLER assigned them, which is the
    only record that the extra layer was played: the brief's `voices` dict
    never names it, it comes from the style's `extra`.
    """
    _out, man = heroic
    layers = man['render']['layers']
    assert sorted(layers) == ['bass', 'extra', 'lead', 'pad'], layers
    assert layers['lead'] == 'french_horn' and layers['extra'] == 'trumpet'


def test_there_is_no_lyric_leg(heroic):
    out, man = heroic
    assert not os.path.exists(os.path.join(out, 'lyrics.txt'))
    assert man['lyrics_source'] == 'none'
    assert man['brief']['sung'] is False


def test_there_is_no_picture_leg(heroic):
    """Declared not applicable — not attempted, not failed, not 'not requested'."""
    _out, man = heroic
    assert man['video']['ok'] is False
    assert 'not applicable' in man['video']['reason'], man['video']


def test_the_cue_is_filed_on_its_cinematic_shelf(heroic):
    out, _man = heroic
    with open(os.path.join(out, 'shelf.json'), 'r', encoding='utf-8') as f:
        rec = json.load(f)
    assert rec['family'] == 'cinematic'
    assert rec['shelf'] == 'heroic'
    assert rec['by'] == 'style' and rec['filed']


def test_the_labels_say_instrumental(heroic):
    _out, man = heroic
    assert man['labels']['singer'] == 'Instrumental'
    assert man['labels']['age_band'] == 'Instrumental'
    assert man['labels']['style'] == 'Heroic'


# ── (b) the captions describe a cue, not a children's song ───────────────────


def test_the_ace_caption_leads_with_the_cinematic_genre(heroic):
    out, _man = heroic
    with open(os.path.join(out, 'song.json'), 'r', encoding='utf-8') as f:
        plan = json.load(f)
    prompt = K.ace_prompt(plan)
    assert prompt.startswith('cinematic instrumental score'), prompt
    assert 'french horn' in prompt, prompt
    assert "children's music" not in prompt, prompt
    assert 'instrumental, no vocals' in prompt
    # The instrumental that DOES get a negative: no voice may appear.
    assert K.ace_negative(plan) == 'vocals, singing, lyrics, children singing'


def test_the_clap_gate_is_asked_about_orchestral_music():
    """`sad` is a cinematic-only key; `storytime` exists in both families."""
    assert T.clap_captions('sad', 'cinematic')[0] == 'a sad orchestral piece'
    assert T.clap_captions('storytime', 'cinematic')[0] == 'a gentle orchestral piece'
    assert T.clap_captions('storytime', 'children')[0] == "a gentle children's song"
    # 'horror drone' is a fail in a nursery rhyme and an instrument in a cue.
    assert 'horror drone' not in T.clap_negatives('cinematic')
    assert 'pop song with vocals' in T.clap_negatives('cinematic')
    assert 'horror drone' in T.clap_negatives('children')
