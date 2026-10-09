# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the helpers extracted out of `stage_11b_flux_preflight`.

The pre-eval sequence builder, the arc/shot ladders, the checkpoint probe, the
Qwen availability probe and the FluxWorker claim were all blocks in the middle
of a 445-line stage function, so these are the first tests to exercise them on
their own. No GPU, no network, no services: the two probes get fakes, the
checkpoint probe gets a tmp directory.
"""

import types

from zyg_workflows.scholarly import stages_37_54_preflight as pf


def test_the_arc_zone_ladder_matches_the_episode_position():
    assert pf.arc_zone_for_fraction(0.0) == 'exposition'
    assert pf.arc_zone_for_fraction(0.149) == 'exposition'
    assert pf.arc_zone_for_fraction(0.15) == 'rising'
    assert pf.arc_zone_for_fraction(0.44) == 'rising'
    assert pf.arc_zone_for_fraction(0.45) == 'climax'
    assert pf.arc_zone_for_fraction(0.64) == 'climax'
    assert pf.arc_zone_for_fraction(0.65) == 'falling'
    assert pf.arc_zone_for_fraction(0.84) == 'falling'
    assert pf.arc_zone_for_fraction(0.85) == 'resolution'
    assert pf.arc_zone_for_fraction(1.0) == 'resolution'


def test_exposition_and_resolution_pin_their_shot_whatever_the_intensity():
    assert pf.shot_type_for_slot('exposition', 0.99) == 'wide establishing shot'
    assert pf.shot_type_for_slot('resolution', 0.0) == 'medium wide shot, reflective'


def test_every_other_zone_tightens_the_shot_as_intensity_rises():
    assert pf.shot_type_for_slot('climax', 0.9) == 'extreme close-up'
    assert pf.shot_type_for_slot('climax', 0.85) == 'extreme close-up'
    assert pf.shot_type_for_slot('rising', 0.7) == 'close-up'
    assert pf.shot_type_for_slot('rising', 0.5) == 'medium shot'
    assert pf.shot_type_for_slot('falling', 0.2) == 'medium wide shot'
    # A visual-tags entry with no 'arc' key reaches here as None.
    assert pf.shot_type_for_slot(None, 0.9) == 'extreme close-up'


def test_the_pre_eval_sequence_falls_back_to_defaults_on_an_empty_state():
    seq = pf.build_pre_eval_sequence(3, {}, [], 'the Sikh Empire')
    assert [s['idx'] for s in seq] == [0, 1, 2]
    assert [s['description'] for s in seq] == ['exposition', 'climax', 'resolution']
    assert [s['shot_type'] for s in seq] == [
        'wide establishing shot',
        'medium wide shot',
        'medium wide shot, reflective',
    ]
    assert all(s['emotion'] == 'calm' and s['intensity'] == 0.2 for s in seq)
    assert all(s['prompt'] == 'the Sikh Empire' for s in seq)
    assert all(s['transition'] == 'dissolve' and s['counterpoint'] is False for s in seq)
    # 300 s is the tts_duration default; every slot gets its equal share.
    assert all(s['duration'] == 100.0 for s in seq)


def test_the_pre_eval_sequence_reads_the_emotion_curve_and_the_visual_tags():
    state = {
        'emotion_curve': [{'emotion': 'dread', 'intensity': 0.9123}, {'emotion': 'grief', 'intensity': 0.5}],
        'visual_tags': [{'arc': 'climax', 'tag': 'the siege'}, {'arc': 'resolution', 'tag': 'the ruins'}],
        'tts_duration': 20.0,
    }
    seq = pf.build_pre_eval_sequence(2, state, [], 'topic')
    assert [s['emotion'] for s in seq] == ['dread', 'grief']
    assert [s['intensity'] for s in seq] == [0.91, 0.5]
    assert [s['description'] for s in seq] == ['climax', 'resolution']
    assert [s['shot_type'] for s in seq] == ['extreme close-up', 'medium wide shot, reflective']
    assert [s['prompt'] for s in seq] == ['the siege', 'the ruins']
    assert [s['duration'] for s in seq] == [10.0, 10.0]


def test_the_pre_eval_sequence_truncates_prompts_and_floors_the_duration():
    long_prompt = 'x' * 200
    seq = pf.build_pre_eval_sequence(2, {'tts_duration': 1.0}, [{'standard': long_prompt}, long_prompt], 't')
    assert seq[0]['prompt'] == 'x' * 60
    assert seq[1]['prompt'] == 'x' * 60
    assert [s['duration'] for s in seq] == [3.0, 3.0]


def test_a_single_slot_sequence_does_not_divide_by_zero():
    seq = pf.build_pre_eval_sequence(0, {}, [], 'topic')
    assert len(seq) == 1
    assert seq[0]['description'] == 'exposition'


def test_the_transition_plan_replaces_the_placeholder_dissolves():
    seq = pf.build_pre_eval_sequence(3, {}, [], 'topic')
    fake_murch = types.SimpleNamespace(
        build_xfade_filter_graph=lambda durations, emotions, shot_types: (
            None,
            [{'idx': 0, 'transition': 'cut'}, {'idx': 2, 'transition': 'zoomin'}],
        )
    )
    said = []
    pf.apply_transition_plan(seq, fake_murch, lambda stage, msg, **kw: said.append(msg))
    assert [s['transition'] for s in seq] == ['cut', 'dissolve', 'zoomin']
    assert said == ['Transition plan fed to self-eval: cut×1, dissolve×1, zoomin×1']


def test_a_failed_transition_plan_leaves_the_eval_on_all_dissolve():
    seq = pf.build_pre_eval_sequence(2, {}, [], 'topic')

    def _boom(durations, emotions, shot_types):
        raise RuntimeError('planner exploded')

    levels = []
    pf.apply_transition_plan(
        seq, types.SimpleNamespace(build_xfade_filter_graph=_boom), lambda s, m, **kw: levels.append(kw.get('level'))
    )
    assert [s['transition'] for s in seq] == ['dissolve', 'dissolve']
    assert levels == ['WARN']


def test_a_score_under_the_murch_floor_is_logged_as_a_warning(monkeypatch):
    monkeypatch.setenv('ZYG_SCHOLARLY_MURCH_FLOOR', '6')
    state, job, said = {}, {}, []
    verdict = {'score': 4, 'weakest_cuts': [1], 'overall_notes': 'repetitive', 'suggestions': ['vary the cuts']}
    pf.report_self_eval(verdict, [], state, job, lambda lvl, stage, msg: said.append((lvl, msg)), lambda *a, **k: None)
    assert state['murch_eval'] is verdict
    assert job['murch_eval'] is verdict
    assert said[0][0] == 'INFO'
    assert said[1] == ('WARNING', 'Murch self-eval score 4/10 is below the 6 floor — sequence plan is weak: repetitive')
    assert said[2] == ('WARNING', '  murch: vary the cuts')


def test_a_score_at_or_over_the_floor_is_only_reported(monkeypatch):
    monkeypatch.setenv('ZYG_SCHOLARLY_MURCH_FLOOR', '6')
    said = []
    pf.report_self_eval(
        {'score': 'not a number'}, [], {}, {}, lambda lvl, stage, msg: said.append((lvl, msg)), lambda *a, **k: None
    )
    assert [lvl for lvl, _ in said] == ['INFO']


def test_a_missing_checkpoint_directory_is_not_ready_and_says_nothing(tmp_path):
    said = []
    assert pf.probe_flux_ready(str(tmp_path / 'absent'), lambda *a: said.append(a)) is False
    assert said == []


def test_a_part_downloaded_checkpoint_reports_its_size_and_is_not_ready(tmp_path):
    transformer = tmp_path / 'transformer'
    transformer.mkdir()
    (transformer / 'a.safetensors').write_bytes(b'0' * 1024)
    (transformer / 'b.safetensors.index.json').write_bytes(b'0' * 4096)
    (transformer / 'notes.txt').write_bytes(b'0' * 4096)
    said = []
    assert pf.probe_flux_ready(str(tmp_path), lambda lvl, stage, msg: said.append(msg)) is False
    assert said == ['Transformer size: 0.0GB — still downloading']


def test_a_complete_checkpoint_is_ready(tmp_path):
    transformer = tmp_path / 'transformer'
    transformer.mkdir()
    shard = transformer / 'shard.safetensors'
    with shard.open('wb') as fh:
        fh.truncate(21 * 1024**3)  # sparse: the probe only reads the reported size
    said = []
    assert pf.probe_flux_ready(str(tmp_path), lambda lvl, stage, msg: said.append(msg)) is True
    assert said == ['Transformer size: 21.0GB — ready']


def test_the_qwen_probe_names_each_reason_it_is_unavailable():
    off = types.SimpleNamespace(is_available=lambda: False, has_qwen_t2i=lambda: True)
    assert pf.probe_qwen_t2i(off) == (False, 'ComfyUI not available (ZYG_USE_COMFYUI / server / breaker)')

    no_ckpt = types.SimpleNamespace(is_available=lambda: True, has_qwen_t2i=lambda: False)
    assert pf.probe_qwen_t2i(no_ckpt) == (
        False,
        'Qwen-Image-2512 checkpoint not found in the ComfyUI unet dir',
    )

    ready = types.SimpleNamespace(is_available=lambda: True, has_qwen_t2i=lambda: True)
    assert pf.probe_qwen_t2i(ready) == (True, '')


def test_a_raising_qwen_probe_is_reported_as_a_failed_probe():
    def _boom():
        raise OSError('comfy socket closed')

    ok, why = pf.probe_qwen_t2i(types.SimpleNamespace(is_available=_boom))
    assert ok is False
    assert why == "probe failed: OSError('comfy socket closed')"


class _FakeWorker:
    """A ScholarlyFluxWorker stand-in that records what the claim path asked of it."""

    def __init__(self, running, claim_ok=True, join_raises=False):
        self.running = running
        self.claim_ok = claim_ok
        self.join_raises = join_raises
        self.waited = False

    def is_running_or_starting(self):
        return self.running

    def wait_until_running(self, timeout):
        self.waited = True
        if self.join_raises:
            raise TimeoutError('worker never came up')

    def claim_start(self):
        return self.claim_ok


def _backend(worker, persistent=True):
    return types.SimpleNamespace(
        scholarly_flux_persistent_enabled=lambda: persistent,
        ScholarlyFluxWorker=types.SimpleNamespace(get=lambda: worker),
    )


def test_no_worker_is_claimed_when_the_persistent_path_is_off_or_unusable():
    worker = _FakeWorker(running=True)
    assert pf.claim_flux_worker(_backend(worker, persistent=False), True, False, lambda *a: None) == (
        None,
        False,
        False,
    )
    assert pf.claim_flux_worker(_backend(worker), False, False, lambda *a: None) == (None, False, False)
    assert pf.claim_flux_worker(_backend(worker), True, True, lambda *a: None) == (None, False, False)
    assert worker.waited is False


def test_a_running_worker_is_joined_so_flux_is_never_loaded():
    worker = _FakeWorker(running=True)
    said = []
    fw, active, claimed = pf.claim_flux_worker(_backend(worker), True, False, lambda lvl, s, m: said.append(m))
    assert (fw, active, claimed) == (worker, True, False)
    assert worker.waited is True
    assert said == ['[FluxWorker] joining running persistent worker — FLUX load/lock skipped']


def test_a_failed_join_falls_back_to_a_per_pipeline_load():
    worker = _FakeWorker(running=True, join_raises=True)
    said = []
    fw, active, claimed = pf.claim_flux_worker(_backend(worker), True, False, lambda lvl, s, m: said.append((lvl, m)))
    assert (fw, active, claimed) == (None, False, False)
    assert said[0][0] == 'WARNING'


def test_winning_the_start_claim_defers_the_worker_start_to_after_the_load():
    worker = _FakeWorker(running=False, claim_ok=True)
    fw, active, claimed = pf.claim_flux_worker(_backend(worker), True, False, lambda *a: None)
    assert (fw, active, claimed) == (worker, False, True)
    assert worker.waited is False


def test_losing_the_start_race_joins_the_winner_instead():
    worker = _FakeWorker(running=False, claim_ok=False)
    said = []
    fw, active, claimed = pf.claim_flux_worker(_backend(worker), True, False, lambda lvl, s, m: said.append(m))
    assert (fw, active, claimed) == (worker, True, False)
    assert said == ['[FluxWorker] claim race resolved — joining running worker']
