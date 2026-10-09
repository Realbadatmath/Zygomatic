# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Portfolio deck contract — the edit behind /portfolio-slideshow.

Deck-only on purpose: importing the Zero public server starts its worker
thread, so the route behaviour is covered by the in-process client run in
the build notes rather than here.
"""

import os

import pytest

from zyg_zero import zpub_portfolio_deck as deck_mod


def _words(s: str) -> int:
    return len(str(s).split())


def test_hero_follows_the_readme_pattern():
    hero = deck_mod.HERO
    assert hero['name']
    # Tagline band shared by the twenty flagship READMEs (9-16 words), WHAT-first.
    assert 9 <= _words(hero['tagline']) <= 16
    assert hero['tagline'].lower().startswith('a ')
    assert 3 <= len(hero['facts']) <= 5
    for f in hero['facts']:
        assert f['k'] and f['v']


def test_every_slide_is_one_what_and_at_most_three_points():
    for ch in deck_mod.CHAPTERS:
        assert ch['id'] and ch['title'] and ch['slides']
        for s in ch['slides']:
            assert s['title']
            assert s.get('what'), f'{ch["id"]}/{s["title"]} has no WHAT line'
            assert len(s.get('points') or []) <= 3
            if s.get('file'):
                assert deck_mod.SLIDE_NAME_RE.match(s['file']), s['file']


def test_chapter_ids_are_unique():
    ids = [ch['id'] for ch in deck_mod.CHAPTERS]
    assert len(ids) == len(set(ids))


def test_build_deck_drops_missing_files_and_keeps_text_cards(tmp_path):
    # Only two of the referenced pictures exist in this folder.
    keep = []
    for ch in deck_mod.CHAPTERS:
        for s in ch['slides']:
            if s.get('file') and len(keep) < 2:
                (tmp_path / s['file']).write_bytes(b'\x89PNG')
                keep.append(s['file'])
    (tmp_path / '999_loose_frame.png').write_bytes(b'\x89PNG')
    (tmp_path / '.hidden.png').write_bytes(b'')
    d = deck_mod.build_deck(str(tmp_path))
    files = [s['file'] for ch in d['chapters'] for s in ch['slides'] if s['file']]
    assert sorted(files) == sorted(keep)
    texts = [s for ch in d['chapters'] for s in ch['slides'] if not s['file']]
    assert texts, 'text-only cards must survive a missing folder'
    assert d['count'] == len(files) + len(texts)
    assert [x['file'] for x in d['extra']] == ['999_loose_frame.png']
    assert d['extra'][0]['title'] == 'loose frame'


def test_build_deck_on_missing_folder_is_empty_not_an_error(tmp_path):
    d = deck_mod.build_deck(str(tmp_path / 'nope'))
    assert d['extra'] == []
    assert all(not s['file'] for ch in d['chapters'] for s in ch['slides'])


@pytest.mark.skipif(not os.path.isdir(deck_mod.SLIDES_DIR), reason='screenshot folder not on this machine')
def test_live_folder_resolves_every_referenced_picture():
    d = deck_mod.build_deck()
    referenced = {s['file'] for ch in deck_mod.CHAPTERS for s in ch['slides'] if s.get('file')}
    resolved = {s['file'] for ch in d['chapters'] for s in ch['slides'] if s['file']}
    assert referenced == resolved, sorted(referenced - resolved)
    assert len(d['chapters']) == len(deck_mod.CHAPTERS)


def test_deck_cache_is_per_folder(tmp_path):
    a = tmp_path / 'a'
    a.mkdir()
    b = tmp_path / 'b'
    b.mkdir()
    (a / '001_x.png').write_bytes(b'\x89PNG')
    da = deck_mod.deck(str(a))
    db = deck_mod.deck(str(b))
    assert [x['file'] for x in da['extra']] == ['001_x.png']
    assert db['extra'] == []
