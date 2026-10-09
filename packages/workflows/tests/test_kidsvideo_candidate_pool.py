#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The picture leg's candidate pool + defect screen (2026-09-15).

    scripts/run_tests.sh tests/test_kidsvideo_candidate_pool.py

No ComfyUI, no ollama, no CLIP: the generator writes flat PNGs and the screen is
stubbed per seed. The screen's accuracy was calibrated on 1,112 real frames
(output/kidsmusic/_frame_defect_bench); these pin doubling, throw-out, the pick,
the spares on disk, and the rule that reads the VLM's description.
"""

import os
import types

import pytest

PIL = pytest.importorskip('PIL')
from PIL import Image  # noqa: E402

from zyg_workflows import kids_video_service as KV  # noqa: E402


@pytest.fixture
def fake_comfy(monkeypatch, stub_module):
    calls = []

    def generate_still(path, prompt, *, seed=0, **kw):
        calls.append(seed)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Image.new('RGB', (64, 36), ((seed * 37) % 255, 120, 200)).save(path)
        return True, 'fake'

    mod = types.SimpleNamespace(is_available=lambda: True, generate_still=generate_still)
    stub_module('comfy_generation_service', mod)
    # The pool mechanics are generator-agnostic; pin the klein path so the test
    # never reaches the live HiDream server on :8189 (default family since 2026-10-02).
    monkeypatch.setattr(KV, 'MODEL_FAMILY', 'klein')
    monkeypatch.setattr(KV, '_enable_comfy', lambda: None)
    monkeypatch.setattr(KV, 'release_comfy_vram', lambda log_fn=None: {'released': True})
    monkeypatch.setattr(KV, 'release_ollama', lambda log_fn=None, why='': [])
    monkeypatch.setattr(KV, 'CANDIDATES', 2)
    monkeypatch.setattr(KV, 'SCREEN_ON', True)
    return calls


def _screen(bad_candidates):
    """Stub screen: a candidate path ending in one of `bad_candidates` is a defect."""

    def screen(path):
        name = os.path.basename(path)
        if any(name.endswith(b + '.png') for b in bad_candidates):
            return {
                'verdict': 'defect',
                'reasons': ['rocking horse: 2 heads'],
                'soft': [],
                'cartoon': 0.95,
                'vlm': 'ran',
                'seconds': 0.01,
            }
        return {
            'verdict': 'healthy',
            'reasons': [],
            'soft': [],
            'cartoon': 0.9 + (0.05 if name.endswith('_c1.png') else 0.0),
            'vlm': 'ran',
            'seconds': 0.01,
        }

    return screen


def _slots(n, **extra):
    return [dict({'i': i, 'idea': f'idea {i}', 'start': float(i), 'dur': 1.0}, **extra) for i in range(n)]


def test_every_generated_picture_is_rendered_twice(tmp_path, fake_comfy, monkeypatch):
    monkeypatch.setattr(KV, 'screen_frame', _screen([]))
    slots = _slots(5)
    paths, info = KV.render_images(slots, {}, str(tmp_path), seed=3)
    assert len(fake_comfy) == 10
    assert info['pool']['rendered'] == 10 and info['pool']['in_song'] == 5
    assert all(os.path.isfile(p) for p in paths)
    assert info['generated'] == 5
    # the healthiest (higher cartoon) went in; the other is a kept spare
    assert all(s['candidates'][1]['chosen'] for s in slots)
    assert sorted(os.listdir(tmp_path / 'frames' / 'excess')) == [f'f{i:03d}_c0.png' for i in range(5)]
    assert info['pool']['excess_kept'] == 5
    assert not (tmp_path / 'frames' / '_cand').exists()


def test_a_defect_is_thrown_out_and_its_healthy_twin_ships(tmp_path, fake_comfy, monkeypatch):
    monkeypatch.setattr(KV, 'screen_frame', _screen(['f001_c1']))
    slots = _slots(3)
    paths, info = KV.render_images(slots, {}, str(tmp_path), seed=3)
    s1 = slots[1]
    assert [c['verdict'] for c in s1['candidates']] == ['healthy', 'defect']
    assert s1['candidates'][0]['chosen'] and s1['source_render'] == 'generated'
    assert info['pool']['rejected'] == 1 and info['pool']['rejected_reasons'] == {'heads': 1}
    # thrown out: no full-size file anywhere, a small receipt in frames/rejected
    assert not (tmp_path / 'frames' / 'excess' / 'f001_c1.png').exists()
    assert (tmp_path / 'frames' / 'rejected' / 'f001_c1.jpg').is_file()
    assert info['pool']['excess_kept'] == 2


def test_a_slot_with_every_candidate_rejected_is_reseeded_once(tmp_path, fake_comfy, monkeypatch):
    monkeypatch.setattr(KV, 'screen_frame', _screen(['f000_c0', 'f000_c1']))
    slots = _slots(2)
    paths, info = KV.render_images(slots, {}, str(tmp_path), seed=3)
    s0 = slots[0]
    assert info['pool']['reseeded_slots'] == 1
    assert s0['candidates'][-1]['reseed'] and s0['candidates'][-1]['chosen']
    assert s0['source_render'] == 'generated' and os.path.isfile(paths[0])


def test_when_the_reseed_is_rejected_too_the_slot_is_drawn_not_shipped_broken(tmp_path, fake_comfy, monkeypatch):
    monkeypatch.setattr(KV, 'screen_frame', _screen(['f000_c0', 'f000_c1', 'f000_c2']))
    slots = _slots(2)
    paths, info = KV.render_images(slots, {}, str(tmp_path), seed=3)
    assert slots[0]['source_render'] == 'drawn_screen' and info['drawn_screen'] == 1
    assert os.path.isfile(paths[0])
    assert not any(c['chosen'] for c in slots[0]['candidates'])


def test_a_counting_run_keeps_one_candidate_index_when_it_can(tmp_path, fake_comfy, monkeypatch):
    # c1 scores higher everywhere except the run's first slot, where c1 is broken:
    # the run then sticks with c0 so the blocks keep one colour.
    monkeypatch.setattr(KV, 'screen_frame', _screen(['f000_c1']))
    slots = _slots(3, seed_group='count-1')
    KV.render_images(slots, {}, str(tmp_path), seed=3)
    assert [next(c['c'] for c in s['candidates'] if c['chosen']) for s in slots] == [0, 0, 0]
    # and every slot of the run shared each candidate's seed
    assert len({s['candidates'][0]['seed'] for s in slots}) == 1
    assert len({s['candidates'][1]['seed'] for s in slots}) == 1


def test_counting_cards_are_drawn_once_not_doubled(tmp_path, fake_comfy, monkeypatch):
    monkeypatch.setattr(KV, 'screen_frame', _screen([]))
    monkeypatch.setattr(KV, 'draw_count_card', lambda spec, p, rng: Image.new('RGB', (8, 8)).save(p) or True)
    slots = _slots(2)
    slots[0]['draw'] = {'kind': 'count'}
    KV.render_images(slots, {}, str(tmp_path), seed=3)
    assert slots[0]['source_render'] == 'drawn_count' and len(fake_comfy) == 2


def test_reused_slots_copy_the_picture_that_was_picked(tmp_path, fake_comfy, monkeypatch):
    monkeypatch.setattr(KV, 'screen_frame', _screen([]))
    slots = _slots(2)
    slots[1]['idea'] = slots[0]['idea']
    paths, info = KV.render_images(slots, {}, str(tmp_path), seed=3, reuse=True)
    assert slots[1]['source_render'] == 'reused' and len(fake_comfy) == 2
    assert open(paths[0], 'rb').read() == open(paths[1], 'rb').read()


def test_candidates_one_is_the_old_single_render_path(tmp_path, fake_comfy, monkeypatch):
    monkeypatch.setattr(KV, 'CANDIDATES', 1)
    monkeypatch.setattr(KV, '_repair_frames', lambda *a, **k: None)
    slots = _slots(3)
    paths, info = KV.render_images(slots, {}, str(tmp_path), seed=3)
    assert len(fake_comfy) == 3 and 'pool' not in info
    assert not (tmp_path / 'frames' / 'excess').exists()


# ── the rule that reads the VLM's description (calibrated cases) ────────────


def test_rule_flags_the_calibrated_hits():
    J = KV.judge_description
    assert J({'characters': [{'what': 'rocking horse', 'heads': 2}]}) == ['rocking horse: 2 heads']
    assert J({'characters': [], 'wrong': ['small child has no eyes']}) == ['small child has no eyes']
    assert J({'characters': [], 'wrong': [], 'writing': 'Wlof'}) == ['writing: Wlof']


def test_rule_ignores_the_calibrated_false_alarms():
    J = KV.judge_description
    # five children in a train's windows, counted as one "person: 5 heads"
    assert J({'characters': [{'what': 'children', 'heads': 2}, {'what': 'person', 'heads': 5}]}) == []
    assert J({'characters': [], 'wrong': ['The tree has a face-like shape, but it is not an animal']}) == []
    assert J({'characters': [], 'wrong': ['none'], 'writing': ''}) == []
    assert J({'characters': [], 'wrong': [], 'writing': '8 0'}) == []


def test_an_unanswered_vlm_is_unmeasured_never_healthy(tmp_path, monkeypatch):
    p = str(tmp_path / 'x.png')
    Image.new('RGB', (32, 18), (200, 200, 50)).save(p)
    monkeypatch.setattr(KV, 'vlm_defects', lambda path, timeout=60: (None, 'URLError'))
    monkeypatch.setattr(KV, 'reads_text', lambda path: [])
    monkeypatch.setattr(KV, '_clip', lambda: None)
    KV._VLM_FAILS['n'] = 0
    assert KV.screen_frame(p)['verdict'] == 'unmeasured'


def test_rule_ignores_the_live_tractor_song_false_alarms():
    """Job 7a9514bf0b42: reasons recorded at full size on healthy candidates."""
    J = KV.judge_description
    for w in (
        'The tractor has two eyes on its front grill.',
        'The tractor has only one eye.',
        'a tractor is partially hidden by a bush',
        'no animals, people or characters in the image',
    ):
        assert J({'characters': [], 'wrong': [w]}) == [], w
    # ...while the real live hit and the calibrated hits still count
    assert J({'characters': [], 'wrong': ['The tractor has two front wheels merged into one body part.']})
    assert J({'characters': [], 'wrong': ['small child has no eyes']})
    assert J({'characters': [], 'wrong': ['missing head on the legs of the boy in orange shirt']})


def _screen_env(monkeypatch, tmp_path, vlm):
    p = str(tmp_path / 'x.png')
    Image.new('RGB', (32, 18), (200, 200, 50)).save(p)
    monkeypatch.setattr(KV, 'vlm_defects', lambda path, timeout=60: vlm)
    monkeypatch.setattr(KV, 'reads_text', lambda path: [{'text': 'Ano', 'conf': 0.9, 'area_frac': 0.01}])
    monkeypatch.setattr(KV, '_clip', lambda: None)
    KV._VLM_FAILS['n'] = 0
    return p


def test_ocr_lettering_alone_is_soft(tmp_path, monkeypatch):
    r = KV.screen_frame(_screen_env(monkeypatch, tmp_path, ([], {})))
    assert r['verdict'] == 'soft' and 'OCR only' in r['soft'][0]


def test_ocr_lettering_the_vlm_also_reads_is_a_defect(tmp_path, monkeypatch):
    r = KV.screen_frame(_screen_env(monkeypatch, tmp_path, (['writing: Hello'], {})))
    assert r['verdict'] == 'defect' and any(x.startswith('lettering') for x in r['reasons'])


# ── one of a pair: a side view hides one (soft, never a reject) ─────────────


def test_one_of_a_pair_claims_are_soft_not_hard():
    """Every recorded false alarm of this class, plus the words it will wear next:
    duck f9c4f3e17c20 f005 'one eye', the calibration bee, the tractor, and the
    bird song's rabbit running in profile (c29fcac02d69 f016 'missing arm')."""
    for w in (
        'duck has one eye',
        'the bee has only one eye',
        'missing arm',
        'the rabbit is missing a front leg',
        'bird has only one wing',
        'has no left eye',
        'one of its legs is missing',
        'left arm missing',
        'a single ear',
        'lacks an antenna',
        'cat without a paw',
    ):
        hard, soft = KV.judge({'characters': [], 'wrong': [w]})
        assert hard == [] and len(soft) == 1 and soft[0].startswith(w), w
        assert KV.judge_description({'characters': [], 'wrong': [w]}) == []
    # the tractor's eye is a face on an object — the earlier filter takes it, not even soft
    assert KV.judge({'characters': [], 'wrong': ['The tractor has only one eye.']}) == ([], [])


def test_zero_and_extra_counts_stay_hard():
    """A count of none or of too many is not a view — every real hit on record."""
    for w in (
        'small child has no eyes',
        'pink fairy has no legs',
        'one bird has no eyes',
        'The first duck has three legs.',
        'missing head',
        'missing legs on the person in pink',
        'missing head on the legs of the boy in orange shirt',
        'The tractor has a second head.',
        'The tractor has two front wheels merged into one body part.',
        'two creatures merged into one body',
        'the frog has three eyes',
        'extra arm growing from the back',
    ):
        hard, soft = KV.judge({'characters': [], 'wrong': [w]})
        assert hard == [w] and soft == [], w


def test_a_soft_claim_ranks_below_a_clean_twin_but_ships(tmp_path, monkeypatch):
    """screen_frame: a one-of-a-pair claim makes the candidate 'soft' — usable,
    ranked under 'healthy' — and the model's description rides along."""
    raw = {
        'characters': [{'what': 'rabbit', 'heads': 1, 'eyes': 1, 'legs': 2, 'arms': 0}],
        'wrong': ['missing arm'],
        'writing': '',
    }
    p = str(tmp_path / 'x.png')
    Image.new('RGB', (32, 18), (200, 200, 50)).save(p)
    monkeypatch.setattr(KV, 'vlm_defects', lambda path, timeout=60: (KV.judge_description(raw), raw))
    monkeypatch.setattr(KV, 'reads_text', lambda path: [])
    monkeypatch.setattr(KV, '_clip', lambda: None)
    KV._VLM_FAILS['n'] = 0
    r = KV.screen_frame(p)
    assert r['verdict'] == 'soft' and r['reasons'] == [] and 'missing arm' in r['soft'][0]
    assert r['described'] == {
        'characters': [{'what': 'rabbit', 'heads': 1, 'eyes': 1, 'legs': 2, 'arms': 0}],
        'wrong': ['missing arm'],
    }
    assert KV._SCREEN_RANK['healthy'] < KV._SCREEN_RANK['soft'] < KV._SCREEN_RANK['defect']


def test_description_is_kept_on_a_healthy_candidate_too(tmp_path, monkeypatch):
    raw = {'characters': [{'what': 'duck', 'heads': 1, 'eyes': 2, 'legs': 2, 'arms': 0}], 'wrong': []}
    p = str(tmp_path / 'y.png')
    Image.new('RGB', (32, 18), (200, 200, 50)).save(p)
    monkeypatch.setattr(KV, 'vlm_defects', lambda path, timeout=60: ([], raw))
    monkeypatch.setattr(KV, 'reads_text', lambda path: [])
    monkeypatch.setattr(KV, '_clip', lambda: None)
    KV._VLM_FAILS['n'] = 0
    r = KV.screen_frame(p)
    assert r['verdict'] == 'healthy' and r['described']['characters'][0]['what'] == 'duck'


def test_an_unanswered_vlm_keeps_no_description(tmp_path, monkeypatch):
    p = str(tmp_path / 'z.png')
    Image.new('RGB', (32, 18), (200, 200, 50)).save(p)
    monkeypatch.setattr(KV, 'vlm_defects', lambda path, timeout=60: (None, 'URLError'))
    monkeypatch.setattr(KV, 'reads_text', lambda path: [])
    monkeypatch.setattr(KV, '_clip', lambda: None)
    KV._VLM_FAILS['n'] = 0
    assert KV.screen_frame(p)['described'] is None
