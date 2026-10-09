#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The voice leg: vocal_analysis decisions and what run() does with them.

    scripts/run_tests.sh tests/test_voice_leg.py

No GPU, no demucs, no Whisper, no ComfyUI. The measurements themselves were
calibrated on real takes (tools/voice_analysis_calibrate.py, lyric_asr_bench.py,
kidsmusic_repaint_spike.py); these tests pin the logic that turns measurements
into problems, windows, splices, mixes and ship decisions.
"""

import json
import os
import shutil

import pytest

np = pytest.importorskip('numpy')
sf = pytest.importorskip('soundfile')
# run() writes the MIDI stem before it ever touches a take, so the whole leg needs mido.
pytest.importorskip('mido', reason='kids_music_service writes the MIDI stem with mido')

from zyg_workflows import kids_music_service as K  # noqa: E402
from zyg_workflows import kids_music_theory as T  # noqa: E402
from zyg_workflows import vocal_analysis as VA  # noqa: E402

MALE = T.SINGERS['adult_male']


def _plan(lines=('the bee lands on red', 'he buzzes every flower', 'he flies to blue')):
    melody = []
    for li in range(len(lines)):
        for b in range(4):
            melody.append({'t': 8.0 + li * 8 + b * 2, 'd': 2.0, 'p': 62, 'line': li})
    return {
        'bpm': 120,
        'lyrics': list(lines),
        'melody': melody,
        'key': {'tonic_pc': 2, 'mode': 'major', 'ace_keyscale': 'D major'},
    }


def _words(text, t0, step=0.4):
    return [
        {'w': w, 'start': round(t0 + i * step, 2), 'end': round(t0 + i * step + 0.3, 2), 'p': 0.9}
        for i, w in enumerate(text.split())
    ]


# ── lyrics ───────────────────────────────────────────────────────────────────


def test_every_line_heard_in_order_is_sung_and_placed():
    plan = _plan()
    words = (
        _words('the bee lands on red', 4.0) + _words('he buzzes every flower', 9.0) + _words('he flies to blue', 14.0)
    )
    al = VA.align_lines(plan, words)
    assert [r['sung'] for r in al['lines']] == [True, True, True]
    assert al['lines'][1]['start_s'] == 9.0 and al['extra_words'] == 0


def test_a_skipped_line_is_missing_and_its_neighbours_are_not():
    plan = _plan()
    words = _words('the bee lands on red', 4.0) + _words('he flies to blue', 14.0)
    al = VA.align_lines(plan, words)
    assert [r['sung'] for r in al['lines']] == [True, False, True]


def test_a_repeated_refrain_does_not_count_as_the_line_it_replaced():
    plan = _plan(('he buzzes every flower', 'he lands on white', 'he buzzes every flower'))
    words = (
        _words('he buzzes every flower', 4.0)
        + _words('he buzzes every flower', 9.0)
        + _words('he buzzes every flower', 14.0)
    )
    al = VA.align_lines(plan, words)
    assert al['lines'][1]['sung'] is False
    assert al['lines'][0]['sung'] and al['lines'][2]['sung']


def test_misheard_spelling_still_matches():
    plan = _plan(('he flies high above the grassy green hill',))
    al = VA.align_lines(plan, _words('he flies high above the grassy green hills', 3.0))
    assert al['lines'][0]['sung'] and al['lines'][0]['coverage'] == 1.0


def test_no_words_means_nothing_sung_not_everything():
    al = VA.align_lines(_plan(), [])
    assert not any(r['sung'] for r in al['lines'])


# ── problems ─────────────────────────────────────────────────────────────────


def _report(**over):
    rep = {
        'register': {'band_hz': [110.0, 285.0], 'f0_median_hz': 220.0, 'voiced_s': 20.0},
        'key': {'in_key_share': 0.95},
        'lines': [
            {
                'line': 0,
                'sung': True,
                'f0_median_hz': 215.0,
                'start_s': 4.0,
                'end_s': 8.0,
                'vocal_over_backing_db': -2.0,
            },
            {
                'line': 1,
                'sung': True,
                'f0_median_hz': 230.0,
                'start_s': 9.0,
                'end_s': 13.0,
                'vocal_over_backing_db': -1.0,
            },
        ],
    }
    rep.update(over)
    return rep


def test_a_clean_take_has_no_problems():
    assert VA.problems(_report(), MALE) == []


def test_a_line_mostly_above_the_ceiling_is_repaintable():
    rep = _report()
    rep['lines'][1]['above_ceiling_share'] = 0.65
    p = VA.problems(rep, MALE)
    assert [(x['kind'], x['line'], x['fix']) for x in p] == [('line_high', 1, 'repaint')]


def test_a_line_that_only_touches_the_octave_is_not_flagged_by_its_median():
    # bumblebee line 9: median 439 Hz on one window, 221 on the next, 41-49 % above
    rep = _report()
    rep['lines'][1].update(f0_median_hz=439.0, above_ceiling_share=0.45)
    assert VA.problems(rep, MALE) == []


def test_the_ceiling_comes_from_the_singer():
    assert MALE['line_ceiling_hz'] == 300.0
    assert T.SINGERS['adult_female'].get('line_ceiling_hz') is None


def test_a_last_line_the_song_ends_inside_is_reported_not_repainted():
    rep = _report(seconds=57.4)
    rep['lines'].append({'line': 2, 'sung': False, 'coverage': 0.57, 'start_s': 53.7, 'end_s': 55.7})
    p = VA.problems(rep, MALE)
    assert [(x['kind'], x['fix']) for x in p] == [('line_cut', 'none')]
    assert VA.repair_windows(rep, p, seconds=57.4) == []


def test_a_missing_last_line_far_from_the_end_is_still_repaintable():
    rep = _report(seconds=57.4)
    rep['lines'].append({'line': 2, 'sung': False, 'coverage': 0.2, 'start_s': 40.0, 'end_s': 41.0})
    assert [x['kind'] for x in VA.problems(rep, MALE)] == ['line_missing']


def test_off_key_and_no_vocal_rerender():
    assert [x['kind'] for x in VA.problems(_report(key={'in_key_share': 0.5}), MALE)] == ['off_key']
    assert VA.problems(_report(register={'band_hz': [110, 285], 'voiced_s': 0}), MALE)[0]['fix'] == 'rerender'


def test_a_buried_voice_gets_a_clamped_remix_gain():
    rep = _report()
    for ln in rep['lines']:
        ln['vocal_over_backing_db'] = -12.0
    lvl = [x for x in VA.problems(rep, MALE) if x['kind'] == 'level'][0]
    assert lvl['fix'] == 'remix' and lvl['gain_db'] == VA.LEVEL_MAX_GAIN_DB


def test_severity_orders_hard_problems_above_line_problems():
    assert VA.severity([{'kind': 'off_key'}]) > VA.severity([{'kind': 'line_missing'}] * 3)


# ── intelligibility: the bare decode (LINE_CLEAR_COVERAGE) ───────────────────


def test_a_line_sung_but_not_recoverable_without_the_prompt_is_repainted():
    """The false pass this gate exists for: placed, in range, scored sung by the
    prompted decode, and still mush. df012ec48502 L5 shipped exactly like this."""
    rep = _report()
    rep['lines'][1].update(clear=False, coverage_bare=0.17, heard_bare='four')
    p = VA.problems(rep, MALE)
    assert [(x['kind'], x['line'], x['fix']) for x in p] == [('line_unclear', 1, 'repaint')]
    assert 'four' in p[0]['detail'] and '17%' in p[0]['detail']


def test_an_unclear_line_is_repainted_over_its_own_span():
    rep = _report()
    rep['lines'][1].update(clear=False, coverage_bare=0.2)
    wins = VA.repair_windows(rep, VA.problems(rep, MALE), seconds=20.0)
    assert len(wins) == 1
    assert wins[0]['start_s'] < 9.0 and wins[0]['end_s'] > 13.0 and wins[0]['lines'] == [1]


def test_a_clear_line_is_not_flagged():
    rep = _report()
    for ln in rep['lines']:
        ln.update(clear=True, coverage_bare=1.0)
    assert VA.problems(rep, MALE) == []


def test_an_unmeasured_bare_decode_never_flags_and_never_claims_clear():
    """clear=None is 'did not run'. It must not become a problem, and it must not
    be reported as clear either — a gate that fails open is the bug being fixed."""
    rep = _report()
    for ln in rep['lines']:
        ln.update(clear=None, coverage_bare=None)
    assert VA.problems(rep, MALE) == []


def test_a_missing_line_outranks_an_unclear_one_and_both_outrank_high():
    assert (
        VA.severity([{'kind': 'line_missing'}])
        > VA.severity([{'kind': 'line_unclear'}])
        > VA.severity([{'kind': 'line_high'}])
    )


def test_an_already_missing_line_is_not_also_reported_unclear():
    """A line nobody sang is line_missing, once — not missing AND unclear."""
    rep = _report(seconds=57.4)
    rep['lines'].append(
        {
            'line': 2,
            'sung': False,
            'coverage': 0.1,
            'start_s': 20.0,
            'end_s': 24.0,
            'clear': False,
            'coverage_bare': 0.0,
        }
    )
    assert [x['kind'] for x in VA.problems(rep, MALE)] == ['line_missing']


def test_measure_joins_the_bare_decode_by_line_and_never_lets_it_move_one():
    plan = _plan()
    words = (
        _words('the bee lands on red', 4.0) + _words('he buzzes every flower', 9.0) + _words('he flies to blue', 14.0)
    )
    # the bare decode hears line 1 as mush, and hears it somewhere else entirely
    bare = _words('the bee lands on red', 4.0) + _words('he buzzes zzz zzz', 40.0) + _words('he flies to blue', 14.0)
    al = VA.align_lines(plan, words)
    alb = VA.align_lines(plan, bare)
    assert al['lines'][1]['start_s'] == 9.0  # placement from the PROMPTED decode
    assert alb['lines'][1]['coverage'] < VA.LINE_CLEAR_COVERAGE


def test_clear_threshold_is_the_same_bar_as_sung():
    assert VA.LINE_CLEAR_COVERAGE == VA.LINE_SUNG_COVERAGE == 0.6


# ── repair windows ───────────────────────────────────────────────────────────


def test_missing_line_window_spans_the_gap_between_placed_neighbours():
    rep = {
        'lines': [
            {'line': 0, 'sung': True, 'start_s': 4.0, 'end_s': 8.0},
            {'line': 1, 'sung': False},
            {'line': 2, 'sung': True, 'start_s': 12.5, 'end_s': 16.0},
        ],
        'planned_windows': [{'line': i, 'start_s': 4.0 + 4 * i, 'end_s': 8.0 + 4 * i} for i in range(3)],
    }
    w = VA.repair_windows(rep, [{'kind': 'line_missing', 'line': 1}], seconds=30.0)
    assert w == [{'start_s': 7.8, 'end_s': 12.7, 'lines': [1]}]


def test_a_neighbour_that_swallowed_the_gap_is_trimmed_to_its_planned_length():
    # the bumblebee: the refrain after the skipped line matched across 8 s of a 4 s line
    rep = {
        'lines': [
            {'line': 0, 'sung': True, 'start_s': 16.0, 'end_s': 20.3},
            {'line': 1, 'sung': False},
            {'line': 2, 'sung': True, 'start_s': 20.3, 'end_s': 28.4},
        ],
        'planned_windows': [{'line': i, 'start_s': 16.0 + 4.1 * i, 'end_s': 20.1 + 4.1 * i} for i in range(3)],
    }
    w = VA.repair_windows(rep, [{'kind': 'line_missing', 'line': 1}], seconds=57.0)
    assert w[0]['start_s'] == pytest.approx(20.1, abs=0.01)
    assert w[0]['end_s'] == pytest.approx(24.5, abs=0.01)


def test_a_missing_first_line_does_not_repaint_the_intro():
    rep = {
        'lines': [{'line': 0, 'sung': False}, {'line': 1, 'sung': True, 'start_s': 9.0, 'end_s': 12.0}],
        'planned_windows': [{'line': 0, 'start_s': 4.1, 'end_s': 8.2}, {'line': 1, 'start_s': 8.2, 'end_s': 12.3}],
    }
    w = VA.repair_windows(rep, [{'kind': 'line_missing', 'line': 0}], seconds=57.0)
    assert w == [{'start_s': 3.9, 'end_s': 9.2, 'lines': [0]}]


def test_touching_windows_merge_and_tiny_ones_drop():
    rep = {'lines': [], 'planned_windows': []}
    probs = [
        {'kind': 'line_high', 'line': 0, 'start_s': 4.0, 'end_s': 8.0},
        {'kind': 'line_high', 'line': 1, 'start_s': 8.1, 'end_s': 12.0},
        {'kind': 'line_high', 'line': 2, 'start_s': 20.0, 'end_s': 20.5},
    ]
    w = VA.repair_windows(rep, probs, seconds=60.0)
    assert w == [{'start_s': 3.8, 'end_s': 12.2, 'lines': [0, 1]}]


# ── splice + remix ───────────────────────────────────────────────────────────


def _tone(path, seconds, hz, sr=44100, amp=0.3):
    t = np.arange(int(seconds * sr)) / sr
    y = (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)
    sf.write(path, np.stack([y, y], 1), sr, subtype='PCM_16')


def _song_and_repaint(tmp_path, delay=0, sr=44100):
    """A 'song' (noise-like, so alignment has one answer) and a repaint that is
    the same song outside 3.5-6.5 s — as a real masked repaint is — and a tone
    inside, optionally delayed like a decoder offset."""
    rng = np.random.default_rng(7)
    y = (0.1 * rng.standard_normal(10 * sr)).astype(np.float32)
    p = y.copy()
    t = np.arange(int(3.0 * sr)) / sr
    p[int(3.5 * sr) : int(6.5 * sr)] = (0.3 * np.sin(2 * np.pi * 330.0 * t)).astype(np.float32)
    if delay:
        p = np.concatenate([np.zeros(delay, dtype=np.float32), p])[: len(y)]
    o_path, p_path = str(tmp_path / 'o.wav'), str(tmp_path / 'p.wav')
    sf.write(o_path, np.stack([y, y], 1), sr, subtype='FLOAT')
    sf.write(p_path, np.stack([p, p], 1), sr, subtype='FLOAT')
    return o_path, p_path, y


def test_splice_keeps_the_original_outside_the_window(tmp_path):
    o, p, ref = _song_and_repaint(tmp_path)
    rec = K.splice_window(o, p, str(tmp_path / 's.wav'), 4.0, 6.0, guard_s=0.5, xfade_s=0.1)
    y, sr = sf.read(rec['path'], dtype='float32')
    assert rec['lag_samples'] == 0
    assert np.allclose(y[: int(3.3 * sr), 0], ref[: int(3.3 * sr)], atol=2e-4)
    assert np.allclose(y[int(6.7 * sr) :, 0], ref[int(6.7 * sr) :], atol=2e-4)
    t = np.arange(int(1.0 * sr)) / sr + 1.0  # 4.5-5.5 s is 1.0-2.0 s into the tone
    tone = 0.3 * np.sin(2 * np.pi * 330.0 * t)
    assert np.allclose(y[int(4.5 * sr) : int(5.5 * sr), 0], tone, atol=2e-4)


def test_splice_undoes_a_decoder_delay_to_the_sample(tmp_path):
    o, p, ref = _song_and_repaint(tmp_path, delay=203)
    rec = K.splice_window(o, p, str(tmp_path / 's.wav'), 4.0, 6.0, guard_s=0.5, xfade_s=0.1)
    y, sr = sf.read(rec['path'], dtype='float32')
    assert rec['lag_samples'] == 203
    assert np.allclose(y[: int(3.3 * sr), 0], ref[: int(3.3 * sr)], atol=2e-4)


def test_a_window_at_the_start_aligns_on_the_audio_after_it(tmp_path):
    rng = np.random.default_rng(3)
    sr = 44100
    y = (0.1 * rng.standard_normal(10 * sr)).astype(np.float32)
    p = y.copy()
    p[: int(2.0 * sr)] = 0.0  # the repaint changed the first 2 s
    p = np.concatenate([np.zeros(96, dtype=np.float32), p])[: len(y)]
    o_path, p_path = str(tmp_path / 'o.wav'), str(tmp_path / 'p.wav')
    sf.write(o_path, np.stack([y, y], 1), sr, subtype='FLOAT')
    sf.write(p_path, np.stack([p, p], 1), sr, subtype='FLOAT')
    rec = K.splice_window(o_path, p_path, str(tmp_path / 's.wav'), 0.5, 1.5, guard_s=0.3, xfade_s=0.05)
    assert rec['lag_samples'] == 96


def test_remix_applies_the_gains(tmp_path):
    v, b = str(tmp_path / 'v.flac'), str(tmp_path / 'b.flac')
    _tone(v, 1.0, 440.0, amp=0.1)
    _tone(b, 1.0, 110.0, amp=0.1)
    out = K.remix_stems(v, b, str(tmp_path / 'm.wav'), vocal_db=6.0, backing_db=-6.0)
    y, _ = sf.read(out['path'], dtype='float32')
    vv, _ = sf.read(v, dtype='float32')
    bb, _ = sf.read(b, dtype='float32')
    assert np.allclose(y, vv * 10 ** (6 / 20) + bb * 10 ** (-6 / 20), atol=1e-4)


# ── run(): what the review decides ───────────────────────────────────────────

_LYRICS = (['one two three', 'four five six', 'one two three', 'four five six'], 'T', 'fallback', {})


@pytest.fixture
def voice_run(monkeypatch):
    from zyg_workflows import audio_qc

    for var in (
        'ZYG_KIDSMUSIC_SINGER_RETRIES',
        'ZYG_KIDSMUSIC_TAKES',
        'ZYG_KIDSMUSIC_ACE_MODE',
        'ZYG_KIDSMUSIC_A2A',
        'ZYG_KIDSMUSIC_VOICE_REVIEW',
        'ZYG_KIDSMUSIC_REPAIR',
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(K, 'write_lyrics', lambda *a, **kw: tuple(_LYRICS))
    monkeypatch.setattr(
        audio_qc,
        'qc_clap',
        lambda *a, **kw: {'ok': True, 'positive_prob': 0.9, 'effective_threshold': 0.5, 'scores': {}},
    )
    monkeypatch.setattr(K, 'ace_available', lambda: True)
    st = {
        'renders': 0,
        'reviews': [],
        'repairs': 0,
        'review_script': [],
        'repair_result': None,
        'bare_takes': [],
        # one entry per take: the number of lines a listener can make out (of 4),
        # and whether chroma says the take still follows the composed melody
        'clear_script': [],
        'followed_script': [],
        'denoises': [],
    }

    def fake_ace(plan, out_path, *, seed=None, info=None, melody_wav=None, cover_wav=None, denoise=None, **kw):
        st['renders'] += 1
        st['denoises'].append(denoise)
        shutil.copyfile(melody_wav, out_path)
        info.update(
            {'ran': True, 'seed': seed, 'mode': 'a2a', 'ace_tags': 't', 'seconds': 25.0, 'a2a_denoise': denoise}
        )
        return out_path

    def fake_gate(path, plan, *, work_dir=None, **kw):
        if work_dir:
            os.makedirs(os.path.join(work_dir, 'stems'), exist_ok=True)
            for n in ('vocals.wav', 'no_vocals.wav'):
                shutil.copyfile(path, os.path.join(work_dir, 'stems', n))
        return {'gate': 'singer', 'status': 'pass', 'ok': True, 'checks': {'f0_median_hz': 220.0}, 'detail': 'ok'}

    def fake_review(take, plan, singer, work_dir, *, sep=None, log_fn=None, bare_take=None):
        probs = st['review_script'].pop(0) if st['review_script'] else []
        st['reviews'].append(take)
        st['bare_takes'].append(bare_take)
        clear = st['clear_script'].pop(0) if st['clear_script'] else 4
        return {
            'ok': True,
            'problems': probs,
            'severity': VA.severity(probs),
            'stems': {'vocals': sep['vocals'], 'rest': sep['rest']},
            'lines': [],
            'lyrics': {'measured': True, 'lines': 4, 'sung': 4, 'missing': []},
            'lyrics_bare': {'measured': True, 'lines': 4, 'clear': clear, 'unclear': list(range(4 - clear))},
            'register': {},
            'key': {},
            'level': {},
            'words': [],
            'words_bare': [],
        }

    def fake_chroma(audio, plan, nulls, log_fn=None):
        f = st['followed_script'].pop(0) if st['followed_script'] else True
        return {'z': 9.0 if f else 0.5, 'similarity': 0.1, 'followed': f, 'nulls': 8}

    monkeypatch.setattr(K, 'chroma_follow', fake_chroma)

    def fake_repair(take, plan, singer, rep, info, work_dir, **kw):
        st['repairs'] += 1
        return st['repair_result'](take, rep) if st['repair_result'] else (take, rep, [])

    monkeypatch.setattr(K, 'ace_render', fake_ace)
    monkeypatch.setattr(K, 'gate_singer_age', fake_gate)
    monkeypatch.setattr(VA, 'review', fake_review)
    monkeypatch.setattr(K, 'repair_take', fake_repair)
    # These pin the voice leg as it was before the conversion step; the
    # conversion's own run-level test turns it back on with stubs.
    monkeypatch.setenv('ZYG_KIDSMUSIC_VC', '0')
    return st


def _run(tmp_path):
    out = str(tmp_path / 'song')
    man = K.run(
        {'theme': 'counting ducks', 'seconds': 25, 'sung': True, 'want_video': False, 'singer': 'adult_male'},
        out,
        candidates=6,
        want_ace=True,
    )
    return out, man


MISSING = {'kind': 'line_missing', 'line': 1, 'detail': 'line 2 not sung', 'fix': 'repaint'}
OFFKEY = {'kind': 'off_key', 'detail': 'off key', 'fix': 'rerender'}
LEVEL = {'kind': 'level', 'detail': 'buried', 'gain_db': 3.0, 'fix': 'remix'}


def test_a_clean_first_take_ships_after_one_review(tmp_path, voice_run):
    out, man = _run(tmp_path)
    assert voice_run['renders'] == 1 and len(voice_run['reviews']) == 1 and voice_run['repairs'] == 0
    v = man['voice']
    assert v['reviewed'] and v['take'] == 1 and v['problems'] == []
    assert v['stems'] == {'vocals': 'stems/vocals.flac', 'backing': 'stems/backing.flac'}
    for f in v['stems'].values():
        assert os.path.isfile(os.path.join(out, f))
    assert os.path.isfile(os.path.join(out, 'voice_report.json'))
    assert not os.path.exists(os.path.join(out, '_takes'))
    assert man['delivery']['picked_leg'] == 'produced'


def test_a_line_problem_is_repaired_in_place_not_rerendered(tmp_path, voice_run):
    voice_run['review_script'] = [[MISSING]]

    def fixed(take, rep):
        return take, dict(rep, problems=[], severity=0), [{'result': 'kept'}]

    voice_run['repair_result'] = fixed
    _out, man = _run(tmp_path)
    assert voice_run['renders'] == 1 and voice_run['repairs'] == 1
    assert man['voice']['problems'] == [] and man['voice']['problems_before_repair'] == [MISSING]
    assert man['voice']['repairs'] == [{'result': 'kept'}]


def test_a_hard_problem_rerenders_without_repairing(tmp_path, voice_run):
    voice_run['review_script'] = [[OFFKEY], []]
    _out, man = _run(tmp_path)
    assert voice_run['renders'] == 2 and voice_run['repairs'] == 0
    assert man['voice']['take'] == 2


def test_when_problems_remain_everywhere_the_least_wrong_take_ships(tmp_path, voice_run, monkeypatch):
    monkeypatch.setenv('ZYG_KIDSMUSIC_SINGER_RETRIES', '3')
    voice_run['review_script'] = [[MISSING, MISSING], [OFFKEY], [MISSING, MISSING, MISSING]]
    _out, man = _run(tmp_path)
    assert voice_run['renders'] == 3
    assert man['voice']['take'] == 1 and man['voice']['severity'] == 12
    assert man['delivery']['picked_leg'] == 'produced'


def test_a_level_problem_alone_ships_with_a_remix_gain(tmp_path, voice_run):
    voice_run['review_script'] = [[LEVEL]]
    _out, man = _run(tmp_path)
    assert voice_run['renders'] == 1
    assert man['voice']['mix'] == {'vocal_db': 3.0, 'backing_db': 0.0, 'by': 'voice review'}


def test_review_off_is_the_old_behaviour(tmp_path, voice_run, monkeypatch):
    monkeypatch.setenv('ZYG_KIDSMUSIC_VOICE_REVIEW', '0')
    _out, man = _run(tmp_path)
    assert voice_run['reviews'] == [] and man['voice'] is None


def test_the_male_run_converts_the_voice_and_keeps_the_unconverted_master(tmp_path, voice_run, monkeypatch):
    """Receipt that run() reaches the conversion: both masters, the kept stem,
    the manifest record and the licence attribution."""
    from zyg_workflows import voice_conversion as VC

    monkeypatch.setenv('ZYG_KIDSMUSIC_VC', '1')
    called = []

    def fake_convert(vocals_wav, work_dir, **kw):
        called.append(kw.get('weights'))
        os.makedirs(work_dir, exist_ok=True)
        dst = os.path.join(work_dir, 'vocals_converted.wav')
        shutil.copyfile(vocals_wav, dst)
        return {
            'ok': True,
            'path': dst,
            'engine': VC.ENGINE,
            'weights': kw.get('weights'),
            'lag_samples': 0,
            'envelope_corr': 0.9,
            'gain_db': 0.0,
            'convert_s': 0.1,
        }

    monkeypatch.setattr(VC, 'convert_stem', fake_convert)
    monkeypatch.setattr(
        VC, 'melody_drift', lambda a, b: {'measured': True, 'median_abs_cents': 5.0, 'octave_error_share': 0.0}
    )
    out, man = _run(tmp_path)
    assert called == [T.SINGERS['adult_male']['vc_weights']]
    c = man['voice']['conversion']
    assert c['shipped'], c
    assert os.path.isfile(os.path.join(out, 'master.mp3'))
    assert os.path.isfile(os.path.join(out, 'master_unconverted.mp3'))
    assert man['files']['master_unconverted'] == 'master_unconverted.mp3'
    assert os.path.isfile(os.path.join(out, 'stems', 'vocals_unconverted.flac'))
    assert 'VCTK' in man['licence']['voice_conversion']['attribution']
    assert 'VCTK' in open(os.path.join(out, 'LICENSE.txt')).read()
    assert json.load(open(os.path.join(out, 'voice_report.json')))['conversion']['shipped']
    assert not os.path.exists(os.path.join(out, '_vc'))


# ── the denoise ladder: articulation vs melody ──────────────────────────────


def test_a_take_that_kept_the_tune_beats_one_that_lost_it_even_on_severity():
    """The ladder buys clarity with melody adherence, so severity alone cannot
    choose. delivery.melody_followed is a claim the GUI draws a piano roll on."""
    kept = {'sev': 40, 'followed': True}
    lost = {'sev': 0, 'followed': False}
    assert K._better_take(kept, lost)
    assert not K._better_take(lost, kept)


def test_among_takes_that_all_kept_the_tune_the_least_wrong_wins():
    assert K._better_take({'sev': 5, 'followed': True}, {'sev': 9, 'followed': True})
    assert not K._better_take({'sev': 9, 'followed': True}, {'sev': 5, 'followed': True})


def test_an_unmeasured_chroma_counts_as_kept_not_as_lost():
    """A check that could not run must not silently demote a take."""
    assert K._better_take({'sev': 1, 'followed': None}, {'sev': 5, 'followed': None})
    assert not K._better_take({'sev': 1, 'followed': False}, {'sev': 5, 'followed': None})


def test_the_first_take_renders_at_the_bottom_of_the_ladder():
    assert K.A2A_DENOISE_LADDER[0] == K.A2A_DENOISE == 0.45


def test_an_unclear_take_climbs_the_ladder_and_a_clear_one_does_not(tmp_path, voice_run):
    """Measured: d0.45 left 41/82 lines unintelligible, d0.55 left 14/82. The
    climb is per song, only when the take is measurably unclear."""
    voice_run['review_script'] = [
        [{'kind': 'line_missing', 'line': 0, 'fix': 'repaint', 'detail': 'line 1 not sung', 'text': 'x'}],
        [],
    ]
    voice_run['clear_script'] = [1, 4]  # take 1 mush (25 %), take 2 fine
    _run(tmp_path)
    assert voice_run['denoises'][:2] == [0.45, 0.55], voice_run['denoises']


def test_a_take_that_is_merely_imperfect_does_not_climb(tmp_path, voice_run):
    """A line problem that is not a clarity problem re-seeds at the same rung —
    the ladder costs melody adherence and is not spent on anything else."""
    voice_run['review_script'] = [
        [
            {
                'kind': 'line_high',
                'line': 0,
                'fix': 'repaint',
                'detail': 'line 1 sung too high',
                'text': 'x',
                'start_s': 1.0,
                'end_s': 2.0,
            }
        ],
        [],
    ]
    voice_run['clear_script'] = [4, 4]  # every line audible on both takes
    _run(tmp_path)
    assert set(voice_run['denoises'][:2]) == {0.45}, voice_run['denoises']


def test_a_louder_but_tuneless_take_does_not_ship(tmp_path, voice_run):
    """Take 1 mush but on the tune; take 2 clear and off the tune. The song that
    ships is the one that still follows its own score."""
    voice_run['review_script'] = [
        [{'kind': 'line_missing', 'line': 0, 'fix': 'repaint', 'detail': 'line 1 not sung', 'text': 'x'}],
        [],
    ]
    voice_run['clear_script'] = [1, 4]
    voice_run['followed_script'] = [True, False]
    out, man = _run(tmp_path)
    assert man['voice']['take'] == 1, man['voice']['take']
