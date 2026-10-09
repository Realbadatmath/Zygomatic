# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Life of Jack / Life of Mona — the two children's song series (2026-10-02).

Three claims, none of which needs a GPU, a model or the GUI:

  * the two children are WELL FORMED and cannot bleed into each other — a look, a
    lyric hint and a pool that each name their own child and never the other;
  * the ledger makes the series a series: episode numbers rise, a moment already
    sung is never offered again, and the pool rotates instead of restarting;
  * the brief carries the whole contract — the face (``look``), the point of view
    (``lyric_hint``), the voice (``singer``) and a length inside the band — and
    the picture leg actually reads the face off it.

``kids_series_people`` imports no Flask and no GUI, which is why this file can
exist; the batcher that schedules it (bp_jackmona_daily) is tested through the
approval-queue card instead.
"""

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
if CREWS not in sys.path:
    sys.path.insert(0, CREWS)

from zyg_workflows import kids_music_theory as T  # noqa: E402
from zyg_workflows import kids_series_people as P  # noqa: E402
from zyg_workflows import kids_video_service as V  # noqa: E402


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """A ledger of its own, so a test never writes the real one."""
    path = tmp_path / 'episodes.json'
    monkeypatch.setattr(P, 'LEDGER_PATH', str(path))
    return path


@pytest.fixture
def no_llm(monkeypatch):
    """No model in the room: the hand-written pool is the only source."""
    monkeypatch.setattr(P, 'propose_moment', lambda *a, **k: '')


# ── (a) the two children ─────────────────────────────────────────────────────


def test_there_are_exactly_two_series_and_they_run_in_a_fixed_order():
    assert P.SLUGS == ('jack', 'mona')
    assert set(P.PEOPLE) == set(P.SLUGS)
    assert [P.PEOPLE[s]['name'] for s in P.SLUGS] == ['Jack', 'Mona']


def test_each_child_has_its_own_voice_and_both_are_cast_singers():
    singers = {s: P.PEOPLE[s]['singer'] for s in P.SLUGS}
    assert singers == {'jack': 'adult_male', 'mona': 'adult_female'}
    for key in singers.values():
        assert key in T.SINGERS, key


@pytest.mark.parametrize('slug', P.SLUGS)
def test_the_look_names_its_own_child_and_is_drawably_specific(slug):
    p = P.PEOPLE[slug]
    look = p['look']
    assert p['name'] in look
    # It is the leading clause of every picture prompt, so it has to be short
    # enough to survive beside BASE_STYLE and the idea text (build_prompt caps
    # the whole prompt at 1200).
    assert 80 <= len(look) <= 400, len(look)
    # Specific enough to draw the same child twice: hair, eyes and clothes.
    low = look.lower()
    assert 'hair' in low and 'eyes' in low
    assert any(w in low for w in ('wearing', 'dressed'))


@pytest.mark.parametrize('slug', P.SLUGS)
def test_neither_child_mentions_the_other_anywhere(slug):
    """The operator asked twice for each series to be only about its own child,
    so it is a property of the data and not a tendency of a prompt."""
    others = [q['name'] for s, q in P.PEOPLE.items() if s != slug]
    p = P.PEOPLE[slug]
    blobs = [p['look'], p['lyric_hint'], p['world'], p['blurb']] + list(p['pool'])
    for other in others:
        for blob in blobs:
            assert other.lower() not in str(blob).lower(), (other, blob)


@pytest.mark.parametrize('slug', P.SLUGS)
def test_the_lyric_hint_pins_the_point_of_view(slug):
    h = P.PEOPLE[slug]['lyric_hint']
    assert P.PEOPLE[slug]['name'] in h
    assert len(h) > 60


@pytest.mark.parametrize('slug', P.SLUGS)
def test_the_pool_is_large_clean_and_all_about_its_own_child(slug):
    p = P.PEOPLE[slug]
    pool = p['pool']
    assert len(pool) >= 30, len(pool)
    assert len(set(P._norm(m) for m in pool)) == len(pool), 'a duplicated moment'
    for m in pool:
        assert m.startswith(p['name'] + ' '), m
        assert 12 <= len(m) <= 110, m
        assert not P._BANNED.search(m), m


@pytest.mark.parametrize('slug', P.SLUGS)
def test_every_pool_moment_passes_the_gate_that_screens_the_model(slug):
    for m in P.PEOPLE[slug]['pool']:
        assert P.moment_ok(slug, m, set()), m


def test_the_gate_rejects_the_other_child_the_banned_list_and_repeats():
    assert not P.moment_ok('jack', 'Mona feeds the ducks at the pond', set())
    assert not P.moment_ok('jack', 'Jack goes to the hospital', set())
    assert not P.moment_ok('jack', 'Jack buys a toy for ten euro', set())
    assert not P.moment_ok('jack', 'Jack', set()), 'too short'
    assert not P.moment_ok('jack', 'A boy feeds the ducks', set()), 'not named'
    used = {P._norm('Jack feeds the ducks at the pond')}
    assert not P.moment_ok('jack', 'Jack feeds the ducks at the pond', used)
    assert P.moment_ok('jack', 'Jack finds a pebble in his boot', set())


# ── (b) the ledger makes it a series ─────────────────────────────────────────


def test_episode_numbers_rise_and_are_never_reused(ledger):
    assert P.next_number('jack') == 1
    P.record_episode('jack', 'Jack wakes up and opens the curtains', n=1)
    assert P.next_number('jack') == 2
    P.record_episode('jack', 'Jack eats toast with too much jam', n=2)
    assert P.next_number('jack') == 3
    assert P.next_number('mona') == 1, 'the two series count separately'


def test_a_moment_already_sung_is_never_offered_again(ledger, no_llm):
    seen = []
    for n in range(1, 13):
        m = P.pick_moment('jack')
        assert m not in seen, m
        seen.append(m)
        P.record_episode('jack', m, n=n)
    assert len(set(seen)) == 12


def test_past_the_pool_it_reuses_the_least_recently_sung_moment(ledger, no_llm):
    """Every moment is a repeat once the pool is spent, so the oldest one is the
    right answer — and the day after it must move on rather than stick."""
    pool = P.PEOPLE['jack']['pool']
    for n, m in enumerate(pool, start=1):
        P.record_episode('jack', m, n=n)
    assert {r['slug']: r['pool_left'] for r in P.series_rows()}['jack'] == 0
    first = P.pick_moment('jack')
    assert first == pool[0], 'the moment sung longest ago'
    P.record_episode('jack', first, n=len(pool) + 1)
    second = P.pick_moment('jack')
    assert second == pool[1], 'it rotates on rather than sticking'
    assert second != first


def test_the_ledger_survives_a_reread_and_carries_the_job(ledger):
    P.record_episode('mona', 'Mona ties her own shoelaces slowly', n=1)
    P.attach_job('mona', 1, 'abc123')
    P.settle_episode('mona', 'abc123', title='Shoelaces Song', status='done')
    rows = json.load(open(ledger))['mona']
    assert rows[0]['job_id'] == 'abc123'
    assert rows[0]['title'] == 'Shoelaces Song'
    assert rows[0]['status'] == 'done'


def test_series_rows_report_what_the_board_shows(ledger, no_llm):
    P.record_episode('jack', P.PEOPLE['jack']['pool'][0], n=1)
    rows = {r['slug']: r for r in P.series_rows()}
    assert rows['jack']['episodes'] == 1 and rows['jack']['next_episode'] == 2
    assert rows['jack']['pool_left'] == rows['jack']['pool_size'] - 1
    assert rows['mona']['episodes'] == 0 and rows['mona']['next_episode'] == 1


# ── (c) the brief is the whole contract ──────────────────────────────────────


@pytest.mark.parametrize('slug', P.SLUGS)
def test_the_brief_carries_face_voice_view_and_a_length_in_the_band(ledger, slug, no_llm):
    b = P.episode_brief(slug)
    p = P.PEOPLE[slug]
    assert b['look'] == p['look'] and b['lyric_hint'] == p['lyric_hint']
    assert b['singer'] == p['singer']
    assert b['subject'] == p['name']
    assert b['series'] == slug and b['episode'] == 1
    assert b['sung'] is True and b['want_video'] is True
    assert T.SONG_SECONDS[0] <= b['seconds'] <= T.SONG_SECONDS[1]
    assert b['theme'].startswith(p['name'])


def test_the_same_episode_renders_the_same_song(ledger, no_llm):
    a = P.episode_brief('jack', moment='Jack feeds the ducks at the pond', n=4)
    b = P.episode_brief('jack', moment='Jack feeds the ducks at the pond', n=4)
    assert a == b, 'an episode must be reproducible'
    c = P.episode_brief('jack', moment='Jack feeds the ducks at the pond', n=5)
    assert c['seed'] != a['seed'], 'two episodes must not collide'


def test_consecutive_episodes_vary_in_mood_and_length(ledger, no_llm):
    briefs = [P.episode_brief('jack', moment=f'Jack does thing {n}', n=n) for n in range(1, 7)]
    assert len({b['mood'] for b in briefs}) > 1
    assert len({b['seconds'] for b in briefs}) > 1
    for b in briefs:
        assert T.SONG_SECONDS[0] <= b['seconds'] <= T.SONG_SECONDS[1]


def test_an_unknown_series_is_an_error_not_a_default(ledger):
    with pytest.raises(KeyError):
        P.episode_brief('nobody')


# ── (d) the picture leg really reads the face off the brief ──────────────────


@pytest.mark.parametrize('slug', P.SLUGS)
def test_every_picture_and_every_motion_prompt_carries_the_child(ledger, slug, no_llm):
    b = P.episode_brief(slug)
    name = P.PEOPLE[slug]['name']
    # look_for is the single owner of the prompt's leading clause
    assert V.look_for(b) == P.PEOPLE[slug]['look']
    still = V.build_prompt(V.style_for(b), f'{name} plays in the garden')
    assert name in still and 'hair' in still.lower()
    assert still.startswith(V.BASE_STYLE), 'the flat-2D contract still leads'
    assert len(still) <= 1200
    motion = V.motion_prompt(b, {'i': 0, 'idea': f'{name} waves', 'motif': 'journey'})
    assert name in motion and 'first frame' in motion


def test_an_explicit_look_beats_the_style_and_the_mood():
    assert V.look_for({'look': 'ONLY THIS', 'style': 'playtime', 'mood': 'happy'}) == 'ONLY THIS'
    assert V.look_for({'style': 'playtime'}) == T.STYLES['playtime']['look']
    assert V.look_for({'mood': 'lullaby'}) == V.MOOD_LOOK['lullaby']
    assert V.look_for({'look': '   '}) == V.MOOD_LOOK['happy'], 'blank is not a look'


def test_an_explicit_hint_beats_the_style_in_the_one_owner():
    assert T.lyric_hint_for({'lyric_hint': 'MINE', 'style': 'storytime'}) == 'MINE'
    assert T.lyric_hint_for({'style': 'storytime'}) == T.STYLES['storytime']['lyric_hint']
    assert T.lyric_hint_for({}) == ''


# ── (e) the duration band ────────────────────────────────────────────────────


def test_every_childrens_format_is_in_the_band():
    lo, hi = T.SONG_SECONDS
    assert (lo, hi) == (130.0, 210.0)
    for key, s in T.STYLES.items():
        assert lo <= s['seconds'] <= hi, (key, s['seconds'])


def test_a_song_with_no_style_is_the_bands_middle_and_explicit_still_wins():
    assert T._normalise_brief({'theme': 'x'})['seconds'] == T.SONG_SECONDS_DEFAULT
    assert T._normalise_brief({'theme': 'x', 'seconds': 25})['seconds'] == 25.0
    assert T._normalise_brief({'theme': 'x', 'seconds': 999})['seconds'] == T.SONG_SECONDS_HARD[1]


def test_the_rotation_stays_in_the_band_and_actually_varies():
    lo, hi = T.SONG_SECONDS
    vals = [T.song_seconds(n) for n in range(9)]
    assert all(lo <= v <= hi for v in vals), vals
    assert len(set(vals)) >= 3
    assert T.song_seconds() == T.SONG_SECONDS_DEFAULT


def test_the_cinematic_family_is_not_childrens_music_and_is_untouched():
    """Its cues are played, not sung, and were never a minute of children's song."""
    for key, c in T.CINEMATIC_STYLES.items():
        assert c['seconds'] < T.SONG_SECONDS[0], (key, c['seconds'])
