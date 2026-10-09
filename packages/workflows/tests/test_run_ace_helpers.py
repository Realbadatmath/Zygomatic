# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers ``stage_ace`` was split into.

``stage_ace`` was a 460-line block; nothing inside it had ever been called in
isolation. These tests exercise the decisions it used to make inline — the ACE
mode, the take count, what gets handed to ace_render, the re-seed shift, one
take's inputs, the manifest records, the denoise ladder and the two ways a take
is promoted — with plain inputs, no GPU, no network and no services.
"""

from __future__ import annotations

import json
import os

import pytest

from zyg_workflows.kids_music_service import run_ace as R
from zyg_workflows.kids_music_service import run_ace_takes as T

_FLAGS = (
    'ZYG_KIDSMUSIC_ACE_MODE',
    'ZYG_KIDSMUSIC_TAKES',
    'ZYG_KIDSMUSIC_SINGER_RETRIES',
    'ZYG_KIDSMUSIC_VOICE_REVIEW',
    'ZYG_KIDSMUSIC_REPAIR',
    'ZYG_KIDSMUSIC_VOICE_BUDGET_S',
    'ZYG_KIDSMUSIC_REPAIR_BUDGET_S',
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """No ZYG_KIDSMUSIC_* flag from the operator's shell reaches a test."""
    for name in _FLAGS:
        monkeypatch.delenv(name, raising=False)


def _leg(tmp_path, **kw):
    """An AceLeg with a sung brief, a named singer and a recording log."""
    logs = kw.pop('logs', [])
    fields = {
        'plan': {'brief': {'sung': True, 'title': 'T'}},
        'singer': {'voice': 'adult_male', 'ace_seed': 1000, 'singer_retries': 3},
        'midi': str(tmp_path / 'song.mid'),
        'out_dir': str(tmp_path),
        'cinematic': False,
        'log_fn': logs.append,
        'should_abort': lambda: False,
        'abort': lambda: False,
        'stage': lambda _name: None,
        'ace_mode': 'auto',
        'cond_melody': str(tmp_path / 'render.wav'),
        'cond_cover': None,
        'n_takes': 1,
    }
    fields.update(kw)
    return T.AceLeg(**fields)


def _gate(ok, detail='', **checks):
    base = {'f0_median_hz': 220.0, 'voice_qc_verdict': 'fine', 'sharpness_acum': 1.5, 'hf_ratio_2k8k': 0.2}
    base.update(checks)
    return {'status': 'ok' if ok else 'failed', 'ok': ok, 'detail': detail, 'checks': base}


# ── the environment levers ───────────────────────────────────────────────────


def test_the_ace_mode_defaults_to_auto_and_is_case_folded(monkeypatch):
    logs: list[str] = []
    assert R._ace_mode(logs.append) == 'auto'
    monkeypatch.setenv('ZYG_KIDSMUSIC_ACE_MODE', '  COVER ')
    assert R._ace_mode(logs.append) == 'cover'
    assert logs == []


def test_an_unknown_ace_mode_is_logged_and_falls_back(monkeypatch):
    logs: list[str] = []
    monkeypatch.setenv('ZYG_KIDSMUSIC_ACE_MODE', 'remix')
    assert R._ace_mode(logs.append) == 'auto'
    assert logs == ["ace: unknown ACE mode 'remix' — running the default"]


def test_the_take_count_is_one_unless_the_environment_says_more(monkeypatch):
    assert R._take_count() == 1
    monkeypatch.setenv('ZYG_KIDSMUSIC_TAKES', '4')
    assert R._take_count() == 4


@pytest.mark.parametrize('raw', ['', 'many', '0', '-3'])
def test_an_unusable_take_count_is_one_take(monkeypatch, raw):
    monkeypatch.setenv('ZYG_KIDSMUSIC_TAKES', raw)
    assert R._take_count() == 1


def test_auto_conditioning_is_the_kept_render_only_when_a2a_is_wanted():
    assert R._conditioning('auto', True, 'kept.wav', 'score.wav', print) == ('kept.wav', None)
    assert R._conditioning('auto', False, 'kept.wav', 'score.wav', print) == (None, None)


def test_text_mode_invents_the_audio_codes_and_a2a_forces_the_score():
    assert R._conditioning('text', True, 'kept.wav', 'score.wav', print) == (None, None)
    assert R._conditioning('a2a', False, 'kept.wav', 'score.wav', print) == ('score.wav', None)


def test_cover_mode_hands_the_score_over_as_a_cover():
    logs: list[str] = []
    assert R._conditioning('cover', True, 'kept.wav', 'score.wav', logs.append) == (None, 'score.wav')
    assert logs == []


def test_cover_mode_without_a_score_render_warns_and_falls_back_to_text():
    logs: list[str] = []
    assert R._conditioning('cover', True, 'kept.wav', None, logs.append) == (None, None)
    assert logs == ['ace: cover mode asked for, but there is no score render to cover — falling back to text-to-music']


def test_the_retry_budget_prefers_the_environment_then_the_singer(monkeypatch):
    assert R._singer_retries({'singer_retries': 6}) == 6
    assert R._singer_retries({}) == 3
    monkeypatch.setenv('ZYG_KIDSMUSIC_SINGER_RETRIES', ' 2 ')
    assert R._singer_retries({'singer_retries': 6}) == 2


@pytest.mark.parametrize('raw', ['0', 'false', 'no', 'off'])
def test_the_voice_review_and_the_repaint_are_switchable_off(monkeypatch, raw):
    monkeypatch.setenv('ZYG_KIDSMUSIC_VOICE_REVIEW', raw)
    monkeypatch.setenv('ZYG_KIDSMUSIC_REPAIR', raw)
    assert R._voice_review_on() is False
    assert R._repair_on() is False


def test_the_voice_review_and_the_repaint_are_on_by_default():
    assert R._voice_review_on() is True
    assert R._repair_on() is True


def test_the_budgets_are_seconds_read_from_the_environment(monkeypatch):
    assert R._voice_budget_s() == 900.0
    assert R._repair_budget_s() == 360.0
    monkeypatch.setenv('ZYG_KIDSMUSIC_VOICE_BUDGET_S', '120.5')
    monkeypatch.setenv('ZYG_KIDSMUSIC_REPAIR_BUDGET_S', '30')
    assert R._voice_budget_s() == 120.5
    assert R._repair_budget_s() == 30.0


# ── the gates the leg hands back to run() ────────────────────────────────────


def test_a_passing_singer_gate_is_recorded_beside_the_produced_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(R, 'gate_audio', lambda *a, **kw: {'ok': True, 'fails': []})
    leg = _leg(tmp_path, ace_mp3='song.mp3')
    leg.singer_gate = _gate(True)
    gates: dict = {}
    R._apply_gates(leg, gates)
    assert gates['produced'] == {'ok': True, 'fails': []}
    assert gates['singer'] is leg.singer_gate


def test_a_failed_singer_gate_fails_the_produced_gate_with_its_detail(tmp_path, monkeypatch):
    monkeypatch.setattr(R, 'gate_audio', lambda *a, **kw: {'ok': True, 'fails': []})
    leg = _leg(tmp_path, ace_mp3='song.mp3')
    leg.singer_gate = _gate(False, 'too shrill')
    gates: dict = {}
    R._apply_gates(leg, gates)
    assert gates['produced']['ok'] is False
    assert gates['produced']['fails'] == ['singer gate: too shrill']


def test_a_skipped_singer_gate_leaves_the_produced_gate_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(R, 'gate_audio', lambda *a, **kw: {'ok': True, 'fails': []})
    leg = _leg(tmp_path, ace_mp3='song.mp3')
    leg.singer_gate = {'status': 'skipped', 'ok': False}
    gates: dict = {}
    R._apply_gates(leg, gates)
    assert gates['produced']['ok'] is True
    assert gates['produced']['fails'] == []


# ── the re-seed walk ─────────────────────────────────────────────────────────


def test_a_singer_with_a_retry_shift_alternates_the_lowered_melody(tmp_path):
    leg = _leg(tmp_path)
    leg.singer['retry_lead_shift_st'] = -3
    assert T.alt_lead_shift(leg) == -3


@pytest.mark.parametrize(
    ('field', 'value'),
    [('n_takes', 2), ('cond_melody', None), ('cinematic', True)],
)
def test_best_of_n_cover_and_cinematic_runs_do_not_alternate(tmp_path, field, value):
    leg = _leg(tmp_path, **{field: value})
    leg.singer['retry_lead_shift_st'] = -3
    assert T.alt_lead_shift(leg) is None


def test_a_cover_run_and_an_instrumental_brief_do_not_alternate(tmp_path):
    cover = _leg(tmp_path, cond_cover='score.wav')
    cover.singer['retry_lead_shift_st'] = -3
    assert T.alt_lead_shift(cover) is None
    spoken = _leg(tmp_path, plan={'brief': {'sung': False}})
    spoken.singer['retry_lead_shift_st'] = -3
    assert T.alt_lead_shift(spoken) is None


def test_a_singer_without_a_retry_shift_never_alternates(tmp_path):
    assert T.alt_lead_shift(_leg(tmp_path)) is None


# ── one take's inputs ────────────────────────────────────────────────────────


def test_one_take_renders_to_song_mp3_on_the_singers_own_seed(tmp_path):
    leg = _leg(tmp_path, base_seed=1000)
    inp = T.take_inputs(leg, 0)
    assert inp.dest == str(tmp_path / 'song.mp3')
    assert (inp.seed, inp.shift_st) == (1000, 0)
    assert inp.melody == leg.cond_melody
    assert inp.denoise == R.A2A_DENOISE_LADDER[0]


def test_the_seed_walks_up_one_per_reseed_and_the_takes_are_numbered(tmp_path):
    leg = _leg(tmp_path, n_takes=3, base_seed=1000)
    assert [T.take_inputs(leg, k).seed for k in range(3)] == [1000, 1001, 1002]
    assert T.take_inputs(leg, 2).dest == str(tmp_path / 'song_take3.mp3')


def test_a_random_first_seed_stays_none_until_ace_step_reports_one(tmp_path):
    assert T.take_inputs(_leg(tmp_path), 0).seed is None


def test_an_alternating_take_renders_the_lowered_lead_once_and_holds_the_seed(tmp_path, monkeypatch):
    logs: list[str] = []
    leg = _leg(tmp_path, logs=logs, base_seed=1000, alt_st=-3)
    calls = []

    def fake_lowered(midi, dest, shift, *, log_fn):
        calls.append((midi, dest, shift))
        return dest

    monkeypatch.setattr(R, 'lowered_lead_wav', fake_lowered)
    first = T.take_inputs(leg, 0)
    second = T.take_inputs(leg, 1)
    third = T.take_inputs(leg, 2)
    assert (first.shift_st, second.shift_st, third.shift_st) == (0, -3, 0)
    assert (first.seed, second.seed, third.seed) == (1000, 1000, 1001)
    assert second.melody == str(tmp_path / '_render_low.wav')
    assert len(calls) == 1
    assert 'ace: take 2 — seed 1000 on the melody lowered 3 st' in logs


def test_a_lowered_lead_that_cannot_be_rendered_drops_back_to_a_plain_walk(tmp_path, monkeypatch):
    leg = _leg(tmp_path, base_seed=1000, alt_st=-3)
    monkeypatch.setattr(R, 'lowered_lead_wav', lambda *a, **kw: '')
    second = T.take_inputs(leg, 1)
    assert leg.alt_st is None
    assert (second.shift_st, second.melody) == (0, leg.cond_melody)
    assert second.seed == 1001


def test_a_climbed_rung_picks_the_next_denoise_and_says_why(tmp_path):
    logs: list[str] = []
    leg = _leg(tmp_path, logs=logs, rung=1)
    inp = T.take_inputs(leg, 0)
    assert inp.denoise == R.A2A_DENOISE_LADDER[1]
    assert logs == [
        f'ace: take 1 — climbing the denoise ladder to {R.A2A_DENOISE_LADDER[1]:g} '
        '(the last take could not be made out)'
    ]


def test_the_rung_is_clamped_to_the_top_of_the_ladder(tmp_path):
    leg = _leg(tmp_path, rung=99)
    assert T.take_inputs(leg, 0).denoise == R.A2A_DENOISE_LADDER[-1]


# ── the manifest records ─────────────────────────────────────────────────────


def test_an_attempt_records_the_seed_the_shift_and_the_verdict():
    rec = T.attempt_record(2, {'seed': 1001}, -3, _gate(False, 'too shrill', voice_qc_verdict='shrill'))
    assert rec == {
        'attempt': 3,
        'seed': 1001,
        'lead_shift_st': -3,
        'result': 'failed',
        'f0_hz': 220.0,
        'verdict': 'shrill',
        'detail': 'too shrill',
    }


def test_a_best_of_n_take_keeps_its_own_path_gate_and_info():
    info = {'seed': 7}
    sg = _gate(True, sharpness_acum=2.25)
    rec = T.take_record(0, info, '/out/song_take1.mp3', sg)
    assert rec['take'] == 1
    assert rec['file'] == 'song_take1.mp3'
    assert rec['ok'] is True
    assert rec['sharpness_acum'] == 2.25
    assert (rec['_path'], rec['_info'], rec['_gate']) == ('/out/song_take1.mp3', info, sg)


def test_a_voice_note_counts_the_repairs_and_keeps_at_most_eight_problems():
    rep = {'ok': True, 'problems': [{'detail': f'p{i}', 'fix': 'repaint'} for i in range(10)]}
    recs = [{'result': 'kept'}, {'result': 'dropped'}, {'result': 'kept'}]
    note = T.voice_attempt_note(rep, recs, 4)
    assert note['severity'] == 4
    assert note['problems'] == [f'p{i}' for i in range(8)]
    assert (note['repairs_kept'], note['repairs_tried']) == (2, 3)


def test_an_unmeasured_severity_sorts_a_candidate_last():
    cand = T.candidate_take(0, '/p.mp3', {}, {}, {'ok': False}, {}, [], 0.8, {'followed': True, 'z': 1.0}, None)
    assert cand['sev'] == 10**6
    assert (cand['take'], cand['denoise'], cand['followed']) == (1, 0.8, True)
    assert T.candidate_take(0, '/p.mp3', {}, {}, {}, {}, [], 0.8, {}, 3)['sev'] == 3


# ── the denoise ladder ───────────────────────────────────────────────────────


def test_too_few_clear_lines_climbs_the_ladder_one_rung(tmp_path):
    logs: list[str] = []
    leg = _leg(tmp_path, logs=logs)
    T.maybe_climb_ladder(leg, 0, {'lyrics_bare': {'measured': True, 'clear': 1, 'lines': 4}})
    assert leg.rung == 1
    assert logs and 'only 25% of its lines can be made out' in logs[0]


def test_a_take_whose_lines_can_be_made_out_stays_on_its_rung(tmp_path):
    leg = _leg(tmp_path)
    T.maybe_climb_ladder(leg, 0, {'lyrics_bare': {'measured': True, 'clear': 4, 'lines': 4}})
    assert leg.rung == 0


def test_an_unmeasured_take_a_cover_run_and_the_top_rung_never_climb(tmp_path):
    bare = {'lyrics_bare': {'measured': False, 'clear': 0, 'lines': 4}}
    unmeasured = _leg(tmp_path)
    T.maybe_climb_ladder(unmeasured, 0, bare)
    assert unmeasured.rung == 0
    low = {'lyrics_bare': {'measured': True, 'clear': 0, 'lines': 4}}
    cover = _leg(tmp_path, cond_melody=None, cond_cover='score.wav')
    T.maybe_climb_ladder(cover, 0, low)
    assert cover.rung == 0
    top = _leg(tmp_path, rung=len(R.A2A_DENOISE_LADDER) - 1)
    T.maybe_climb_ladder(top, 0, low)
    assert top.rung == len(R.A2A_DENOISE_LADDER) - 1


# ── the budget bookkeeping ───────────────────────────────────────────────────


def test_queue_time_behind_other_clients_is_not_counted_as_work(tmp_path):
    leg = _leg(tmp_path)
    leg.voice_t0 = 0.0
    leg.voice_waited = 10.0**12
    assert T.voice_work_s(leg) < 0


def test_a_repaint_is_skipped_when_a_line_needs_a_whole_re_render(tmp_path, monkeypatch):
    monkeypatch.setattr(R, 'repair_take', lambda *a, **kw: pytest.fail('repaired a hard problem'))
    leg = _leg(tmp_path, want_repair=True, voice_budget_s=900.0)
    leg.voice_t0 = T.time.time()
    rep = {'ok': True, 'problems': [{'fix': 'rerender', 'detail': 'x'}, {'fix': 'repaint', 'detail': 'y'}]}
    assert T.repair_lines(leg, '/take.mp3', {}, '/dir', rep) == ('/take.mp3', rep, [])


def test_a_repaint_runs_inside_the_remaining_budget_and_adds_its_queue_time(tmp_path, monkeypatch):
    seen = {}

    def fake_repair(path, plan, singer, rep, info, take_dir, *, log_fn, should_abort, budget_s):
        seen['budget_s'] = budget_s
        return '/fixed.mp3', {'ok': True, 'severity': 1, 'problems': []}, [{'result': 'kept', 'lock_wait_s': 4.0}]

    monkeypatch.setattr(R, 'repair_take', fake_repair)
    leg = _leg(tmp_path, want_repair=True, voice_budget_s=900.0)
    leg.voice_t0 = T.time.time()
    rep = {'ok': True, 'problems': [{'fix': 'repaint', 'detail': 'y'}]}
    path, rep_k, recs = T.repair_lines(leg, '/take.mp3', {}, '/dir', rep)
    assert (path, rep_k['severity'], len(recs)) == ('/fixed.mp3', 1, 1)
    assert seen['budget_s'] == 360.0
    assert leg.voice_waited == 4.0


def test_a_spent_budget_leaves_the_take_as_it_is(tmp_path, monkeypatch):
    monkeypatch.setattr(R, 'repair_take', lambda *a, **kw: pytest.fail('repaired without a budget'))
    leg = _leg(tmp_path, want_repair=True, voice_budget_s=1.0)
    leg.voice_t0 = T.time.time() - 10.0
    rep = {'ok': True, 'problems': [{'fix': 'repaint', 'detail': 'y'}]}
    assert T.repair_lines(leg, '/take.mp3', {}, '/dir', rep) == ('/take.mp3', rep, [])


# ── opening the leg ──────────────────────────────────────────────────────────


def test_opening_the_leg_starts_on_the_singers_seed_and_sets_the_budget(tmp_path):
    logs: list[str] = []
    leg = _leg(tmp_path, logs=logs)
    T.open_leg(leg)
    assert (leg.max_try, leg.rounds, leg.base_seed) == (3, 3, 1000)
    assert (leg.want_voice, leg.want_repair, leg.voice_budget_s) == (True, True, 900.0)
    assert logs == ['ace: singer voice "adult_male" — starting on its seed 1000']


def test_best_of_n_rounds_are_the_take_count_and_say_so(tmp_path):
    logs: list[str] = []
    leg = _leg(tmp_path, logs=logs, n_takes=5, ace_mode='a2a')
    T.open_leg(leg)
    assert leg.rounds == 5
    assert leg.want_voice is False
    assert logs[-1] == ('ace: best-of-5 — every take is gated, the least shrill passer ships (mode a2a)')


def test_an_instrumental_brief_keeps_a_random_seed_and_no_voice_review(tmp_path):
    leg = _leg(tmp_path, plan={'brief': {'sung': False}})
    T.open_leg(leg)
    assert leg.base_seed is None
    assert leg.want_voice is False


# ── the loop and the two promotions ──────────────────────────────────────────


def _stub_render(monkeypatch, gates):
    """Patch ace_render/gate_singer_age to return one gate verdict per take."""
    rendered = []

    def fake_render(plan, dest, *, seed, denoise, log_fn, should_abort, info, melody_wav, cover_wav):
        rendered.append(dest)
        info['seed'] = seed if seed is not None else 99
        with open(dest, 'w') as fh:
            fh.write('audio')
        return dest

    def fake_gate(path, plan, *, work_dir, log_fn):
        return gates[len(rendered) - 1]

    monkeypatch.setattr(R, 'ace_render', fake_render)
    monkeypatch.setattr(R, 'gate_singer_age', fake_gate)
    return rendered


def test_the_loop_stops_on_the_first_take_the_singer_gate_passes(tmp_path, monkeypatch):
    rendered = _stub_render(monkeypatch, [_gate(True), _gate(True)])
    leg = _leg(tmp_path, rounds=3, max_try=3, base_seed=1000)
    T.run_take_loop(leg)
    assert leg.produced_status == 'ok'
    assert len(rendered) == 1
    assert leg.ace_mp3 == str(tmp_path / 'song.mp3')
    assert [a['attempt'] for a in leg.attempts] == [1]


def test_the_loop_re_seeds_until_the_budget_is_out_and_says_which_attempt(tmp_path, monkeypatch):
    logs: list[str] = []
    rendered = _stub_render(monkeypatch, [_gate(False, 'shrill')] * 3)
    leg = _leg(tmp_path, logs=logs, rounds=3, max_try=3, base_seed=1000)
    T.run_take_loop(leg)
    assert leg.produced_status == 'failed:singer gate — shrill'
    assert len(rendered) == 3
    assert logs[-1] == 'ace: singer gate failed on all 3 takes'
    assert logs[0] == 'ace: singer gate failed — re-rendering (attempt 2 of 3)'


def test_a_halt_stops_the_loop_without_rendering(tmp_path, monkeypatch):
    logs: list[str] = []
    rendered = _stub_render(monkeypatch, [_gate(True)])
    leg = _leg(tmp_path, logs=logs, rounds=3, max_try=3, abort=lambda: True)
    T.run_take_loop(leg)
    assert leg.produced_status == 'skipped_by_operator'
    assert rendered == []
    assert logs == ['ace: halt requested — stopping the retry loop']


def test_no_audio_records_the_reason_and_ends_the_loop(tmp_path, monkeypatch):
    def fake_render(plan, dest, *, seed, denoise, log_fn, should_abort, info, melody_wav, cover_wav):
        info['seed'] = 5
        info['reason'] = 'comfy down'
        return None

    monkeypatch.setattr(R, 'ace_render', fake_render)
    leg = _leg(tmp_path, rounds=3, max_try=3)
    T.run_take_loop(leg)
    assert leg.produced_status == 'failed:comfy down'
    assert leg.attempts == [{'attempt': 1, 'seed': 5, 'result': 'no audio', 'reason': 'comfy down'}]


def test_every_best_of_n_take_is_rendered_gated_and_kept(tmp_path, monkeypatch):
    rendered = _stub_render(monkeypatch, [_gate(True), _gate(False, 'shrill'), _gate(True)])
    leg = _leg(tmp_path, n_takes=3, rounds=3, max_try=3, base_seed=1000)
    T.run_take_loop(leg)
    assert len(rendered) == 3
    assert [t['take'] for t in leg.ace_takes] == [1, 2, 3]
    assert [t['ok'] for t in leg.ace_takes] == [True, False, True]


def test_the_ranked_pick_promotes_the_best_passer_and_strips_the_handles(tmp_path, monkeypatch):
    logs: list[str] = []
    takes = []
    for i, ok in enumerate((True, False, True)):
        path = tmp_path / f'song_take{i + 1}.mp3'
        path.write_text(f'take{i + 1}')
        takes.append(T.take_record(i, {'seed': 1000 + i}, str(path), _gate(ok)))

    def fake_rank(rows):
        for row in rows:
            row['rank'] = 0.0 if row['take'] == 3 else 1.0

    monkeypatch.setattr('zyg_workflows.sung_pitch.rank_score', fake_rank)
    leg = _leg(tmp_path, logs=logs, n_takes=3)
    leg.ace_takes = takes
    T.pick_ranked_take(leg)
    assert leg.ace_mp3 == str(tmp_path / 'song.mp3')
    assert (tmp_path / 'song.mp3').read_text() == 'take3'
    assert leg.produced_status == 'ok'
    assert leg.picked_take['take'] == 3
    assert all('_path' not in t and '_info' not in t and '_gate' not in t for t in leg.ace_takes)
    assert 'ace: kept take 3 of 3' in logs[-1]


def test_when_no_take_passed_the_least_shrill_failure_still_carries_on(tmp_path, monkeypatch):
    path = tmp_path / 'song_take1.mp3'
    path.write_text('take1')
    monkeypatch.setattr('zyg_workflows.sung_pitch.rank_score', lambda rows: None)
    leg = _leg(tmp_path, n_takes=2)
    leg.ace_takes = [T.take_record(0, {'seed': 1}, str(path), _gate(False, 'too shrill'))]
    T.pick_ranked_take(leg)
    assert leg.produced_status == 'failed:singer gate — too shrill'
    assert leg.ace_mp3 == str(tmp_path / 'song.mp3')


# ── the reviewed take that ships ─────────────────────────────────────────────


def test_the_voice_record_carries_the_review_the_repairs_and_the_mix_gain():
    rep_b = {
        'ok': True,
        'severity': 2,
        'problems': [{'kind': 'level', 'fix': 'remix', 'detail': 'quiet', 'gain_db': 2.5}],
        'lyrics': {'lines': 4},
        'lyrics_bare': {'measured': True, 'clear': 4, 'lines': 4},
        'register': 'mid',
        'key': 'C',
        'level': -14.0,
        'lines': [{'i': 1}],
        'stems': {'vocals': '/v.wav'},
    }
    bv = {'take': 2, 'repairs': [{'result': 'kept'}], 'first': {'severity': 6, 'problems': [{'detail': 'd'}]}}
    rec = T.voice_record(bv, rep_b, {'vocals': 'stems/vocals.wav'}, rep_b['problems'][0], T.time.time())
    assert rec['reviewed'] is True
    assert (rec['take'], rec['take_file'], rec['severity']) == (2, 'song.mp3', 2)
    assert rec['severity_before_repair'] == 6
    assert rec['mix'] == {'vocal_db': 2.5, 'backing_db': 0.0, 'by': 'voice review'}
    assert rec['identity']['measured'] is False
    assert rec['_stems'] == {'vocals': '/v.wav'}


def test_a_take_with_no_level_problem_is_mixed_by_nobody():
    rep_b = {'ok': True, 'severity': 1, 'problems': []}
    bv = {'take': 1, 'repairs': [], 'first': {}}
    rec = T.voice_record(bv, rep_b, {}, None, T.time.time())
    assert rec['mix'] == {'vocal_db': 0.0, 'backing_db': 0.0, 'by': 'none'}


def test_the_voice_report_is_written_without_the_private_handles(tmp_path):
    voice = {'take': 1, 'severity': 2, '_stems': {'vocals': '/v.wav'}}
    T.write_voice_report(str(tmp_path), voice, {'words': [{'w': 'hi'}]})
    on_disk = json.loads((tmp_path / 'voice_report.json').read_text())
    assert on_disk == {'take': 1, 'severity': 2, 'words': [{'w': 'hi'}]}


def test_an_unwritable_voice_report_is_logged_and_never_fatal(tmp_path, caplog):
    missing = tmp_path / 'gone'
    with caplog.at_level('WARNING'):
        T.write_voice_report(str(missing), {'take': 1}, {})
    assert not os.path.exists(missing)
    assert 'voice_report.json write failed' in caplog.text


def test_shipping_a_reviewed_wav_take_transcodes_it_to_song_mp3(tmp_path, monkeypatch):
    logs: list[str] = []
    calls = []

    def fake_mp3(src, dest, *, log_fn, br):
        calls.append((src, dest, br))
        with open(dest, 'w') as fh:
            fh.write('mp3')

    monkeypatch.setattr(R, '_mp3', fake_mp3)
    monkeypatch.setattr(R, 'save_stems', lambda vocals, rest, out: {'vocals': 'stems/vocals.wav'})
    leg = _leg(tmp_path, logs=logs)
    leg.voice_t0 = T.time.time()
    leg.attempts = [{'attempt': 1}, {'attempt': 2}]
    leg.best_voice = {
        'take': 1,
        'path': str(tmp_path / 'take.wav'),
        'info': {'seed': 7},
        'sg': _gate(True),
        'rep': {'ok': True, 'severity': 3, 'problems': [], 'stems': {'vocals': '/v.wav', 'rest': '/r.wav'}},
        'first': {'severity': 5},
        'repairs': [],
        'sev': 3,
    }
    T.ship_reviewed_take(leg)
    assert calls == [(str(tmp_path / 'take.wav'), str(tmp_path / 'song.mp3'), '320k')]
    assert leg.ace_mp3 == str(tmp_path / 'song.mp3')
    assert leg.produced_status == 'ok'
    assert leg.voice['stems'] == {'vocals': 'stems/vocals.wav'}
    assert (tmp_path / 'voice_report.json').is_file()
    assert any('shipping take 1 (severity 3)' in line for line in logs)
