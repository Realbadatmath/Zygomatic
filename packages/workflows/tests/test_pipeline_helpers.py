# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers extracted from the two ``pipeline.py`` orchestrators:
``pipeline_remixai._run_pipeline`` (first half) and ``pipeline_sports._run`` (second
half, under its own banner below) — both stems are ``pipeline``, so both families of
helper tests belong in this one file.

``_run_pipeline`` was one 488-line function: it sweeps YouTube, loads a diffusion model
and a VLM onto the GPU and needs a live job on the board, so none of the decisions inside
it had ever been exercised in isolation. The split into ``pipeline_stages`` pulled the
pure ones out — which candidate is next, what the manifest keeps about the source, the
narration rate, what of a divergence report may be persisted, and the run context the
stages thread through. This file is the first test any of them has had.

No GPU, no network, no services: everything here runs on plain dicts and a tmp_path.

    cd packages/workflows && .venv/bin/python -m pytest tests/test_pipeline_helpers.py -q
"""

import os
import types

import pytest

from zyg_workflows.pipeline_remixai import pipeline, pipeline_stages
from zyg_workflows.pipeline_sports import pipeline as P
from zyg_workflows.pipeline_sports import pipeline_card as CARD
from zyg_workflows.pipeline_sports import pipeline_render as VIDEO


# ── pick_candidate ───────────────────────────────────────────────────────────


def test_pick_candidate_skips_the_ones_already_worked():
    """A candidate whose ledger state is 'worked' is passed over for the next one."""
    cands = [{'video_id': 'a'}, {'video_id': 'b'}, {'video_id': 'c'}]
    seen = {'a': {'state': 'worked'}, 'b': {'state': 'failed'}}

    assert pipeline_stages.pick_candidate(cands, seen) == {'video_id': 'b'}


def test_pick_candidate_tolerates_a_null_ledger_row():
    """``seen[vid]`` may be None — the old code's ``or {}`` — and that is not 'worked'."""
    assert pipeline_stages.pick_candidate([{'video_id': 'a'}], {'a': None}) == {'video_id': 'a'}


def test_pick_candidate_returns_none_when_everything_is_worked():
    """Exhausting the list is how the stage learns to raise 'no eligible source found'."""
    cands = [{'video_id': 'a'}, {'video_id': 'b'}]
    seen = {'a': {'state': 'worked'}, 'b': {'state': 'worked'}}

    assert pipeline_stages.pick_candidate(cands, seen) is None


# ── source_manifest ──────────────────────────────────────────────────────────


def test_source_manifest_keeps_only_the_source_keys():
    """The description and the tags the sweep carried must not reach the manifest."""
    cand = {
        'video_id': 'xyz',
        'title': 'A Title',
        'channel': 'Chan',
        'description': 'the source description, which is not ours to keep',
        'tags': ['a', 'b'],
    }

    out = pipeline_stages.source_manifest(cand)

    assert set(out) == set(pipeline_stages.SOURCE_KEYS)
    assert out['video_id'] == 'xyz'
    assert out['title'] == 'A Title'
    assert 'description' not in out
    assert 'tags' not in out


def test_source_manifest_shape_does_not_depend_on_the_sweep():
    """A sparse candidate still yields every key, with None for what it did not carry."""
    out = pipeline_stages.source_manifest({'video_id': 'v'})

    assert set(out) == set(pipeline_stages.SOURCE_KEYS)
    assert out['velocity'] is None


# ── narration_stats ──────────────────────────────────────────────────────────


def test_narration_stats_counts_words_only_from_voiced_beats():
    """A beat TTS failed on contributes neither its seconds nor its words."""
    beats = [
        {'text': 'one two three', 'wav': '/tmp/a.wav', 'wav_dur': 2.0},
        {'text': 'four five', 'wav': '/tmp/b.wav', 'wav_dur': 1.0},
        {'text': 'never spoken at all', 'wav': None, 'wav_dur': 0.0},
    ]

    seconds, words, wpm = pipeline_stages.narration_stats(beats)

    assert seconds == pytest.approx(3.0)
    assert words == 5
    assert wpm == pytest.approx(100.0)


def test_narration_stats_reports_no_rate_under_a_second():
    """Below a second of audio the rate is 0.0, so one short beat cannot invent a wpm."""
    seconds, words, wpm = pipeline_stages.narration_stats([{'text': 'hi', 'wav': '/tmp/a.wav', 'wav_dur': 0.4}])

    assert (seconds, words, wpm) == (0.4, 1, 0.0)


def test_narration_stats_on_no_beats_is_all_zero():
    """The empty case cannot divide by zero."""
    assert pipeline_stages.narration_stats([]) == (0, 0, 0.0)


# ── divergence_to_persist ────────────────────────────────────────────────────


def test_divergence_to_persist_drops_the_evidence_on_a_pass():
    """Evidence quotes the source's own sentences, so a shipped episode keeps none of it."""
    report = {'verdict': 'pass', 'scores': {'jaccard': 0.1}, 'evidence': ['a source sentence']}

    out = pipeline_stages.divergence_to_persist(report)

    assert 'evidence' not in out
    assert out['scores'] == {'jaccard': 0.1}
    assert 'evidence' in report, 'the report itself must not be mutated'


def test_divergence_to_persist_keeps_the_evidence_on_a_fail():
    """A failed gate is the one case a human has to be able to see the overlap."""
    report = {'verdict': 'fail', 'failed': ['jaccard'], 'evidence': ['a source sentence']}

    assert pipeline_stages.divergence_to_persist(report)['evidence'] == ['a source sentence']


def test_divergence_to_persist_drops_the_evidence_on_degraded():
    """'degraded' ships, so it is not a fail and keeps nothing of the source's text."""
    out = pipeline_stages.divergence_to_persist({'verdict': 'degraded', 'evidence': ['x']})

    assert 'evidence' not in out


# ── new_run ──────────────────────────────────────────────────────────────────


@pytest.fixture
def quiet_marker(monkeypatch):
    """``_marker`` replaced by a recorder, so ``new_run`` registers nothing real."""
    seen = []

    def fake_marker(thread_name, pid):
        seen.append((thread_name, pid))
        return 'marker-id'

    monkeypatch.setattr(pipeline_stages, '_marker', fake_marker)
    return seen


def test_new_run_uses_the_jobs_output_dir_and_makes_the_work_dir(tmp_path, monkeypatch, quiet_marker):
    """The context takes the board's output_dir and creates ``<out_dir>/work`` under it."""
    out_dir = tmp_path / 'episode'
    monkeypatch.setattr(pipeline_stages, '_jobs', lambda: {'pid1': {'output_dir': str(out_dir)}})

    run = pipeline_stages.new_run('pid1')

    assert run.out_dir == str(out_dir)
    assert run.work == os.path.join(str(out_dir), 'work')
    assert os.path.isdir(run.work)
    assert quiet_marker == [('remixai-pid1', 'pid1')]
    assert run.mid == 'marker-id'


def test_new_run_falls_back_to_the_output_root(tmp_path, monkeypatch, quiet_marker):
    """A job with no output_dir — or no job at all — lands under ``_OUT_ROOT/<pid>``."""
    monkeypatch.setattr(pipeline_stages, '_jobs', lambda: {})
    monkeypatch.setattr(pipeline_stages, '_OUT_ROOT', str(tmp_path))

    run = pipeline_stages.new_run('pid2')

    assert run.out_dir == os.path.join(str(tmp_path), 'pid2')
    assert os.path.isdir(run.work)


def test_new_run_seeds_the_manifest_sections(tmp_path, monkeypatch, quiet_marker):
    """Every section downstream stages write into exists before stage 1 runs."""
    monkeypatch.setattr(pipeline_stages, '_jobs', lambda: {'p': {'output_dir': str(tmp_path)}})

    run = pipeline_stages.new_run('p')

    assert run.manifest['pipeline_id'] == 'p'
    assert run.manifest['department'] == pipeline_stages.DEPARTMENT
    assert run.manifest['started']
    assert run.manifest['source'] == {}
    assert run.manifest['analysis'] == {}
    assert run.manifest['regenerated'] == {}
    assert run.manifest['output'] == {}


def test_new_run_starts_with_no_source_on_disk(tmp_path, monkeypatch, quiet_marker):
    """``src_path`` is None until stage 2 downloads, which is what the finally block reads."""
    monkeypatch.setattr(pipeline_stages, '_jobs', lambda: {'p': {'output_dir': str(tmp_path)}})

    assert pipeline_stages.new_run('p').src_path is None


# ── the orchestrator's contract with the stages ──────────────────────────────


def test_run_pipeline_walks_the_stages_in_order(tmp_path, monkeypatch):
    """The eight stage calls happen in order, the seal is stamped, then delivery finishes.

    This is the one behaviour the 488-line function had that no helper test can show: the
    sequence, and that the content credential is stamped before anything records the file.
    """
    calls = []
    run = pipeline_stages.RunContext(pid='p', out_dir=str(tmp_path), work=str(tmp_path / 'work'), mid='m', manifest={})
    run.final, run.title = str(tmp_path / 'FINAL_x.mp4'), 'A New Title'

    monkeypatch.setattr(pipeline, 'new_run', lambda pid: run)
    for name in (
        'stage_source',
        'stage_analysis',
        'stage_soundtrack',
        'stage_script',
        'stage_title',
        'stage_visuals',
        'stage_assembly',
    ):
        monkeypatch.setattr(pipeline, name, lambda *a, _n=name: calls.append(_n))
    monkeypatch.setattr(pipeline, 'stage_delivery', lambda r: calls.append('stage_delivery') or {'path': r.final})
    monkeypatch.setattr(pipeline, '_update_stage', lambda *a: calls.append(f'update:{a[1]}'))
    monkeypatch.setattr(pipeline, '_log', lambda *a: None)
    monkeypatch.setattr(pipeline, '_finish', lambda *a, **kw: calls.append(f'finish:{a[1]}'))
    monkeypatch.setattr(pipeline, '_marker_update', lambda mid, status: calls.append(f'marker:{status}'))
    monkeypatch.setattr(pipeline._seal, 'seal', lambda path, **kw: calls.append(f'seal:{kw["pipeline"]}'))
    monkeypatch.setattr(pipeline.RA, '_ollama_release', lambda: calls.append('release'))

    pipeline._run_pipeline('p', None)

    assert calls == [
        'stage_source',
        'stage_analysis',
        'stage_soundtrack',
        'stage_script',
        'stage_title',
        'stage_visuals',
        'stage_assembly',
        'update:Delivery',
        'seal:remixai',
        'stage_delivery',
        'finish:True',
        'marker:done',
        'release',
    ]


def test_run_pipeline_reports_a_stage_failure_and_still_releases_ollama(tmp_path, monkeypatch):
    """A raising stage marks the job failed, not stopped, and the finally block still runs."""
    calls = []
    run = pipeline_stages.RunContext(pid='p', out_dir=str(tmp_path), work=str(tmp_path / 'work'), mid='m', manifest={})

    monkeypatch.setattr(pipeline, 'new_run', lambda pid: run)
    monkeypatch.setattr(pipeline, 'stage_source', lambda *a: (_ for _ in ()).throw(RuntimeError('disk gate: full')))
    monkeypatch.setattr(pipeline, '_log', lambda pid, level, stage, msg: calls.append(f'log:{level}:{stage}'))
    monkeypatch.setattr(pipeline, '_finish', lambda *a, **kw: calls.append(f'finish:{a[1]}:{kw.get("error")}'))
    monkeypatch.setattr(pipeline, '_marker_update', lambda mid, status: calls.append(f'marker:{status}'))
    monkeypatch.setattr(pipeline.RA, '_ollama_release', lambda: calls.append('release'))

    pipeline._run_pipeline('p', None)

    assert calls == ['log:ERROR:Failed', 'finish:False:disk gate: full', 'marker:failed', 'release']


# ════════════════════════════════════════════════════════════════════════════
# pipeline_sports.pipeline._run — the second `pipeline.py` whose helpers the
# split pulled out. `_run` was 513 lines of seven inlined stages over ~20
# shared locals: the card sizes, the one-unit starring floor, the form veto,
# the photo-credit note, the episode.json payload, the four ZYG_BRIEF_*
# switches and the description text had never been exercised without the Odds
# API, TheSportsDB, ollama and the render engine. They live in
# `pipeline_card`/`pipeline_render` now; below is their first test.
# ════════════════════════════════════════════════════════════════════════════


def _bet(event_id, home, away, selection, **over):
    """One researched bet row, with the keys the selection stages read."""
    b = {
        'event_id': event_id,
        'home': home,
        'away': away,
        'selection': selection,
        'price': 2.1,
        'fair_price': 1.9,
        'fair_prob': 0.5,
        'book': 'pinnacle',
        'bet_type': 'value',
        'edge_pct': 4.2,
        'n_books': 6,
    }
    b.update(over)
    return b


def _sports_run(**over):
    """An EpisodeRun-shaped stand-in: only `pid`, `s`, `ch` and `cat` are read by
    the pure stages tested here."""
    fields = {
        'pid': 'job0001',
        'department': 'tokitoki',
        'category': 'soccer',
        'ch': {'label': 'TokiToki', 'theme': 'tokitoki', 'voice_key': 'tokitoki_voice'},
        'cat': {'label': 'Soccer', 'emoji': '*', 'entity': 'team'},
        'th_brand': {'name': 'TokiToki Soccer'},
        's': {},
        'out_dir': '/tmp/out',
        'work_dir': '/tmp/out/work',
        'charts_dir': '/tmp/out/charts',
        'mid': 1,
        'flags': CARD.EpisodeFlags(),
    }
    fields.update(over)
    return types.SimpleNamespace(**fields)


def _capture_card_log(monkeypatch):
    """Redirect `pipeline_card._log` into a list of (level, message) pairs."""
    lines: list[tuple[str, str]] = []
    monkeypatch.setattr(CARD, '_log', lambda pid, level, stage, msg: lines.append((level, msg)))
    return lines


# ── card_sizes ───────────────────────────────────────────────────────────────


def test_card_sizes_fall_back_to_seven_on_air_and_four_on_ice():
    """An empty settings snapshot keeps the 7/4 default the inline
    `int(s.get(...) or 7)` expressions encoded."""
    assert CARD.card_sizes({}) == (7, 4)
    assert CARD.card_sizes({'bets_per_episode': 0, 'icebox_hold': ''}) == (7, 4)


def test_card_sizes_read_the_settings_rows_as_integers():
    """Operator rows win, and arrive as ints even when stored as strings."""
    assert CARD.card_sizes({'bets_per_episode': '5', 'icebox_hold': 2}) == (5, 2)


# ── _star_one_unit_bets ──────────────────────────────────────────────────────


def test_star_one_unit_bets_marks_the_two_most_likely_over_the_floor(monkeypatch):
    """Of the on-air card, the two selections most likely to win are starred —
    and only those two, highest `fair_prob` first."""
    lines = _capture_card_log(monkeypatch)
    on_air = [
        _bet('e1', 'A', 'B', 'A', fair_prob=0.41),
        _bet('e2', 'C', 'D', 'C', fair_prob=0.72),
        _bet('e3', 'E', 'F', 'E', fair_prob=0.55),
    ]

    CARD._star_one_unit_bets(_sports_run(), on_air)

    assert [b['event_id'] for b in on_air if b.get('starred')] == ['e2', 'e3']
    assert lines and lines[0][0] == 'INFO'
    assert 'one-unit bet(s) of the day' in lines[0][1]


def test_star_one_unit_bets_stars_nothing_below_the_likelihood_floor(monkeypatch):
    """A thin card of 18-25% Draws clears no floor: zero unit bets, said out loud
    (the 2026-08-08 operator rule the inline branch encoded)."""
    lines = _capture_card_log(monkeypatch)
    on_air = [_bet('e1', 'A', 'B', 'Draw', fair_prob=0.2), _bet('e2', 'C', 'D', 'Draw', fair_prob=0.25)]

    CARD._star_one_unit_bets(_sports_run(), on_air)

    assert not [b for b in on_air if b.get('starred')]
    assert 'no one-unit bets this episode' in lines[-1][1]


def test_star_one_unit_bets_honours_an_operator_floor(monkeypatch):
    """`unit_bet_min_prob` in the settings replaces the 0.35 default."""
    _capture_card_log(monkeypatch)
    on_air = [_bet('e1', 'A', 'B', 'A', fair_prob=0.5), _bet('e2', 'C', 'D', 'C', fair_prob=0.62)]

    CARD._star_one_unit_bets(_sports_run(s={'unit_bet_min_prob': 0.6}), on_air)

    assert [b['event_id'] for b in on_air if b.get('starred')] == ['e2']


# ── _form_veto ───────────────────────────────────────────────────────────────


def test_form_veto_moves_a_star_off_a_rotten_run_onto_a_pick_in_form(monkeypatch):
    """A starred side at <=0.4 pts/game yields its star to the next most-likely
    unstarred pick at >=1.5 pts/game, with a WARNING naming both."""
    lines = _capture_card_log(monkeypatch)
    rotten = _bet('e1', 'A', 'B', 'A', fair_prob=0.7, starred=True, form_score=0.2)
    good = _bet('e2', 'C', 'D', 'C', fair_prob=0.6, form_score=2.0)
    weak = _bet('e3', 'E', 'F', 'E', fair_prob=0.65, form_score=1.0)

    CARD._form_veto(_sports_run(), [rotten, good, weak])

    assert rotten['starred'] is False
    assert good['starred'] is True
    assert 'starred' not in weak
    assert [level for level, _ in lines] == ['WARNING']
    assert 'form veto' in lines[0][1]


def test_form_veto_keeps_the_star_when_no_replacement_is_in_form(monkeypatch):
    """With nobody at >=1.5 pts/game the star stays put and nothing is logged."""
    lines = _capture_card_log(monkeypatch)
    rotten = _bet('e1', 'A', 'B', 'A', fair_prob=0.7, starred=True, form_score=0.1)

    CARD._form_veto(_sports_run(), [rotten, _bet('e2', 'C', 'D', 'C', fair_prob=0.6, form_score=0.9)])

    assert rotten['starred'] is True
    assert lines == []


def test_form_veto_leaves_a_star_without_recorded_form_alone(monkeypatch):
    """`form_score is None` means no coverage, which is never a reason to veto."""
    _capture_card_log(monkeypatch)
    starred = _bet('e1', 'A', 'B', 'A', fair_prob=0.7, starred=True, form_score=None)

    CARD._form_veto(_sports_run(), [starred, _bet('e2', 'C', 'D', 'C', fair_prob=0.6, form_score=3.0)])

    assert starred['starred'] is True


# ── attribution_note ─────────────────────────────────────────────────────────


def test_attribution_note_credits_only_the_sources_actually_on_screen():
    """A source is credited once, and only when a cutout that used it made the cut."""
    note = VIDEO.attribution_note(
        {
            ('e1', 'home'): [{'name': 'P', 'img': '/a.png', 'source': 'ESPN'}],
            ('e1', 'away'): [{'name': 'Q', 'img': '/b.png', 'source': ''}],
        }
    )

    assert note == VIDEO.ATTRIBUTION + ' Additional player photos: ESPN.'


def test_attribution_note_is_the_fixed_text_when_no_cutouts_were_used():
    """No cutouts at all — the soccer case — leaves the plain attribution."""
    assert VIDEO.attribution_note({}) == VIDEO.ATTRIBUTION
    assert VIDEO.attribution_note({('e1', 'home'): []}) == VIDEO.ATTRIBUTION


# ── episode_record ───────────────────────────────────────────────────────────


def _render_result():
    """The render engine's result dict, with the keys `episode_record` reads."""
    return {
        'duration': 420.0,
        'video': '/out/ep.mp4',
        'description': 'desc',
        'chapters': [{'t': 0}],
        'qc': {'ok': True},
    }


def test_episode_record_drops_raw_outcomes_and_lists_the_unit_bets():
    """The payload keeps every on-air bet minus its `all_outcomes` blob, and
    repeats the starred ones as one-unit, three-star rows."""
    on_air = [
        _bet('e1', 'A', 'B', 'A', starred=True, all_outcomes=[1, 2, 3]),
        _bet('e2', 'C', 'D', 'C', all_outcomes=[4]),
    ]

    ep = VIDEO.episode_record(
        _sports_run(),
        _render_result(),
        {'skipped': ['no price'], 'credit_note': '3 credits left'},
        on_air,
        [_bet('e3', 'E', 'F', 'E')],
        [{'label': 'Double'}],
        '2026-10-09',
    )

    assert [b['event_id'] for b in ep['bets']] == ['e1', 'e2']
    assert all('all_outcomes' not in b for b in ep['bets'])
    assert ep['unit_bets'] == [
        {'match': 'A vs B', 'selection': 'A', 'odds': 2.1, 'book': 'pinnacle', 'fair_prob': 0.5, 'units': 1, 'stars': 3}
    ]
    assert ep['icebox'] == ['E vs F']
    assert ep['match_day'] == '2026-10-09'
    assert ep['sub_channel'] == 'TokiTokiSoccer'
    assert ep['odds_credit_note'] == '3 credits left'
    assert ep['artwork_source'] == 'TheSportsDB'


def test_episode_record_ttl_falls_back_to_seventy_two_hours():
    """A missing `delivery_ttl_hours` row keeps the 72 h default."""
    assert VIDEO.episode_record(_sports_run(), _render_result(), {}, [], [], [], 'd')['ttl_hours'] == 72.0
    run = _sports_run(s={'delivery_ttl_hours': '24'})
    assert VIDEO.episode_record(run, _render_result(), {}, [], [], [], 'd')['ttl_hours'] == 24.0


# ── the ZYG_BRIEF_* switches ─────────────────────────────────────────────────


def test_flag_on_defaults_to_true_and_reads_the_off_words(monkeypatch):
    """An unset variable is on; 0/false/no/off (any case, any padding) are off."""
    monkeypatch.delenv('ZYG_TEST_FLAG', raising=False)
    assert P._flag_on('ZYG_TEST_FLAG') is True
    for off in ('0', 'false', 'NO', ' Off '):
        monkeypatch.setenv('ZYG_TEST_FLAG', off)
        assert P._flag_on('ZYG_TEST_FLAG') is False
    monkeypatch.setenv('ZYG_TEST_FLAG', '1')
    assert P._flag_on('ZYG_TEST_FLAG') is True


def test_episode_flags_reads_all_four_switches(monkeypatch):
    """Each of the four names lands on its own field of the record."""
    for name in ('INJURIES', 'PLAYER_ART', 'PARLAYS', 'JINGLES'):
        monkeypatch.delenv(f'ZYG_BRIEF_{name}', raising=False)
    assert P._episode_flags() == CARD.EpisodeFlags(True, True, True, True)

    monkeypatch.setenv('ZYG_BRIEF_PARLAYS', '0')
    monkeypatch.setenv('ZYG_BRIEF_JINGLES', 'off')
    flags = P._episode_flags()

    assert (flags.injuries, flags.player_art, flags.parlays, flags.jingles) == (True, True, False, False)


# ── _description_intro ───────────────────────────────────────────────────────


def test_description_intro_lists_every_selection_and_tags_its_kind():
    """One numbered line per bet, VALUE or CONFIDENCE by `bet_type`, and the
    standing telegram and 18+ lines at the end."""
    run = _sports_run()

    text = P._description_intro(
        run.ch,
        run.cat,
        [_bet('e1', 'A', 'B', 'A'), _bet('e2', 'C', 'D', 'C', bet_type='confidence', edge_pct=-1.5)],
        'Friday 9 October',
    )

    lines = text.splitlines()
    assert lines[0] == 'TokiToki Soccer — matches on Friday 9 October'
    assert '2 selections' in text
    assert '1. A vs B — A @ 2.1 (pinnacle) · VALUE · edge +4.2%' in lines
    assert '2. C vs D — C @ 2.1 (pinnacle) · CONFIDENCE · edge -1.5%' in lines
    assert 'PARLAY SHEET' not in text
    assert lines[-1] == '18+ · gamble responsibly.'


def test_description_intro_appends_the_parlay_sheet_when_there_is_one():
    """Parlays add their own block, each line naming the legs, the payout, the
    chance, the edge and the stake cap."""
    run = _sports_run()
    parlay = {
        'label': 'Double',
        'legs': [{'selection': 'A', 'price': 2.1}, {'selection': 'C', 'price': 1.5}],
        'price': 3.15,
        'prob_pct': 33.5,
        'edge_pct': 5.5,
        'stake_pct': 1,
    }

    text = P._description_intro(run.ch, run.cat, [_bet('e1', 'A', 'B', 'A')], 'Friday 9 October', parlays=[parlay])

    assert 'PARLAY SHEET (2-4 legs' in text
    assert 'Double: A @ 2.1 + C @ 1.5 → pays 3.15 · 33.5% chance · edge +5.5% · stake ≤1%' in text.splitlines()
