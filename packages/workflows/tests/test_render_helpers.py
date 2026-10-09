# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the slot loop extracted out of `kids_video_service.render_images`.

The renderer itself is stubbed: `RenderLeg` carries the render callable, the
screening worker and the counting-card drawer as attributes, so the loop can be
exercised with plain functions. No model, no GPU, no network.
"""

import os

from zyg_workflows.kids_video_service import render_slots as RS


class _Rng:
    """A deterministic stand-in for `random.Random` — only `randrange` is used."""

    def __init__(self):
        self.n = 0

    def randrange(self, lo, hi):
        self.n += 1
        return lo + self.n


_GEN = object()  # stands in for the generator: the leg only ever checks it against None


def _leg(tmp_path, *, gen=_GEN, candidates=1, screen_on=False, abort=False):
    info = RS._new_info('hidream', 20, 3.0, 'unet', False, False, [])
    leg = RS.RenderLeg(
        gen,
        info,
        lambda _m: None,
        (lambda: abort),
        _Rng(),
        'storybook',
        str(tmp_path),
        candidates,
        screen_on,
    )
    leg.render = lambda s, p, seed, clear=False: True
    leg.draw_count_card = lambda spec, p, rng: True
    return leg


def test_new_info_starts_every_counter_at_zero_and_keeps_the_model_facts():
    info = RS._new_info('hidream', 20, 3.5, 'fast.safetensors', True, True, ['slow vae'])
    assert info['family'] == 'hidream'
    assert (info['steps'], info['cfg'], info['unet']) == (20, 3.5, 'fast.safetensors')
    assert info['fast'] is True and info['fast_requested'] is True
    assert info['speed_warnings'] == ['slow vae']
    for k in ('generated', 'drawn', 'drawn_count', 'drawn_screen', 'reused', 'failed', 'retries', 'unique'):
        assert info[k] == 0, k
    assert info['seconds'] == 0.0
    assert info['reuse_map'] == {}
    assert info['aborted'] is False
    assert 'pool' not in info


def test_render_leg_without_a_generator_has_no_pool(tmp_path):
    leg = _leg(tmp_path, gen=None, candidates=4)
    assert leg.pool is False
    assert leg.n_cand == 1
    assert leg.screen is False
    assert 'pool' not in leg.info
    assert not os.path.isdir(leg.cdir)


def test_render_leg_with_candidates_opens_the_pool_and_its_directory(tmp_path):
    leg = _leg(tmp_path, candidates=3)
    assert leg.pool is True
    assert leg.n_cand == 3
    assert leg.screen is False
    assert os.path.isdir(leg.cdir)
    assert leg.executor is None
    pool = leg.info['pool']
    assert pool['candidates_per_slot'] == 3
    assert pool['screen'] is False
    assert pool['screen_model'] is None
    assert (pool['rendered'], pool['rejected'], pool['screen_s']) == (0, 0, 0.0)


def test_render_leg_wipes_a_re_illustrated_songs_candidate_directories(tmp_path):
    stale = tmp_path / '_cand' / 'f000_c0.png'
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b'old')
    leg = _leg(tmp_path, candidates=2)
    assert os.path.isdir(leg.cdir)
    assert not stale.exists()


def test_progress_line_reports_what_has_been_made_so_far():
    info = RS._new_info('hidream', 20, 3.0, 'unet', False, False, [])
    info.update(generated=4, drawn_count=2)
    assert RS._progress_line(info, 6, 30, 12.4, 0, False) == 'images: 6/30 (4 generated, 2 counting cards drawn, 12s)'


def test_progress_line_names_the_fallbacks_and_the_candidates_only_when_there_are_some():
    info = RS._new_info('hidream', 20, 3.0, 'unet', False, False, [])
    info.update(generated=4, drawn_count=1, drawn=2, pool={'rendered': 9})
    line = RS._progress_line(info, 7, 30, 20.0, 1, True)
    assert line == 'images: 7/30 (5 generated, 1 counting cards drawn, 2 drawn as fallback, 9 candidates rendered, 20s)'


def test_render_slot_candidates_renders_one_frame_in_place_without_the_pool(tmp_path):
    leg = _leg(tmp_path)
    calls = []
    leg.render = lambda s, p, seed, clear=False: calls.append((p, seed, clear)) or True
    slots = [{'i': 0, 'idea': 'a cat'}, {'i': 1, 'idea': 'a dog'}]
    ok, cands, gid = RS._render_slot_candidates(leg, slots[1], 'out/f001.png', slots)
    assert (ok, cands, gid) == (True, [], '')
    # The last slot releases the models; every other keeps them resident.
    assert calls == [('out/f001.png', 2, True)]


def test_render_slot_candidates_share_one_seed_per_candidate_index_in_a_seed_group(tmp_path):
    leg = _leg(tmp_path, candidates=2)
    slots = [
        {'i': 0, 'idea': 'one block', 'seed_group': 'count'},
        {'i': 1, 'idea': 'two blocks', 'seed_group': 'count'},
    ]
    _ok, first, gid = RS._render_slot_candidates(leg, slots[0], 'unused', slots)
    _ok, second, _gid = RS._render_slot_candidates(leg, slots[1], 'unused', slots)
    assert gid == 'count'
    assert [c['seed'] for c in first] == [c['seed'] for c in second]
    assert first[0]['seed'] != first[1]['seed']
    assert [os.path.basename(c['path']) for c in second] == ['f001_c0.png', 'f001_c1.png']
    assert leg.info['pool']['rendered'] == 4


def test_render_slot_loop_records_a_generated_slot(tmp_path):
    leg = _leg(tmp_path)
    slots = [{'i': 0, 'idea': 'a cat'}]
    RS._render_slot_loop(leg, slots, None)
    assert slots[0]['source_render'] == 'generated'
    assert leg.info['generated'] == 1
    assert leg.paths == [os.path.join(str(tmp_path), 'f000.png')]
    assert leg.prompts[0]
    assert leg.made == {'a cat': 0}


def test_render_slot_loop_counts_a_counting_card_apart_from_the_fallback(tmp_path):
    leg = _leg(tmp_path)
    slots = [{'i': 0, 'idea': 'three blocks', 'draw': {'kind': 'count', 'n': 3}}]
    RS._render_slot_loop(leg, slots, None)
    assert slots[0]['source_render'] == 'drawn_count'
    assert leg.info['drawn_count'] == 1
    assert leg.info['drawn'] == 0
    assert leg.info['generated'] == 0


def test_render_slot_loop_reuses_a_repeated_idea_when_reuse_is_on(tmp_path):
    leg = _leg(tmp_path)
    slots = [{'i': 0, 'idea': 'A Cat'}, {'i': 1, 'idea': 'a cat '}]
    RS._render_slot_loop(leg, slots, True)
    assert [s['source_render'] for s in slots] == ['generated', 'reused']
    assert leg.info['reused'] == 1
    assert leg.info['generated'] == 1
    assert leg.info['reuse_map'] == {'1': 'f000.png'}
    assert slots[1]['_reuse_of'] == 0


def test_render_slot_loop_stops_and_marks_the_run_aborted(tmp_path):
    leg = _leg(tmp_path, abort=True)
    slots = [{'i': 0, 'idea': 'a cat'}, {'i': 1, 'idea': 'a dog'}]
    RS._render_slot_loop(leg, slots, None)
    assert leg.info['aborted'] is True
    assert leg.info['generated'] == 0
    assert 'source_render' not in slots[0]


def test_copy_reused_frames_copies_the_picture_the_idea_ended_up_with(tmp_path):
    info = RS._new_info('hidream', 20, 3.0, 'unet', False, False, [])
    info['reused'] = 1
    (tmp_path / 'f000.png').write_bytes(b'picture')
    slots = [{'i': 0}, {'i': 1, 'source_render': 'reused', '_reuse_of': 0}]
    RS._copy_reused_frames(slots, str(tmp_path), info)
    assert (tmp_path / 'f001.png').read_bytes() == b'picture'
    assert info['failed'] == 0
    assert info['reused'] == 1
    assert '_reuse_of' not in slots[1]


def test_copy_reused_frames_marks_a_failed_copy_missing(tmp_path):
    info = RS._new_info('hidream', 20, 3.0, 'unet', False, False, [])
    info['reused'] = 1
    slots = [{'i': 3, 'source_render': 'reused', '_reuse_of': 9}]
    RS._copy_reused_frames(slots, str(tmp_path), info)
    assert slots[0]['source_render'] == 'missing'
    assert info['failed'] == 1
    assert info['reused'] == 0


def test_screen_candidate_keeps_a_clean_frame(tmp_path):
    cand = {'c': 0, 'seed': 1, 'path': str(tmp_path / 'f000_c0.png')}
    (tmp_path / 'f000_c0.png').write_bytes(b'picture')
    out = RS._screen_candidate(cand, str(tmp_path), lambda _p: {'verdict': 'ok', 'score': 7})
    assert out is cand
    assert cand['screen'] == {'verdict': 'ok', 'score': 7}
    assert 'rejected' not in cand
    assert (tmp_path / 'f000_c0.png').exists()
