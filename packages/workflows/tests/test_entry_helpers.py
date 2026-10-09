# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the stages extracted from vlm_report.analyze_render().

Path resolution, metadata loading, sample-time selection, the person fallback
and the two report records were all inline in the 313-line function, so none of
them could be exercised without a clip, a GPU and a local VLM service. These
tests use plain inputs and tmp_path only.
"""

import json
import os

from zyg_workflows.vlm_report import entry_stages as ES


def _judging(**over):
    """A _Judging record with harmless defaults; `over` replaces fields."""
    fields = {
        'results': [{'id': 'a', 'ok': True}],
        'localized': [],
        'n_calls': 7,
        'model': 'qwen2.5-vl-8b',
        'tier': 'resident',
    }
    fields.update(over)
    return ES._Judging(**fields)


def _info():
    """A _ClipInfo for a 1920x1080 25 fps 10 s clip sampled at three times."""
    return ES._ClipInfo(1920, 1080, 25.0, 10.0, [0.0, 5.0, 9.5])


# ── _prepare_run ─────────────────────────────────────────────────────────────


def test_the_output_tree_defaults_to_a_sibling_of_the_clip_and_is_created(tmp_path):
    scene = tmp_path / 'scene20'
    scene.mkdir()
    clip = scene / 'take_07.mp4'
    clip.write_bytes(b'x')
    paths = ES._prepare_run(str(clip), None, None)
    assert paths.stem == 'take_07'
    assert paths.out_dir == str(scene / 'vlm_report_take_07')
    assert paths.crops_dir == str(scene / 'vlm_report_take_07' / 'crops')
    assert paths.work_dir == str(scene / 'vlm_report_take_07' / '_work')
    assert os.path.isdir(paths.crops_dir) and os.path.isdir(paths.work_dir)


def test_the_scene_key_is_the_clips_parent_directory_name(tmp_path):
    scene = tmp_path / 'scene20'
    scene.mkdir()
    clip = scene / 'take_07.mp4'
    clip.write_bytes(b'x')
    assert ES._prepare_run(str(clip), None, None).scene_key == 'scene20'


def test_an_explicit_out_dir_and_run_id_are_kept(tmp_path):
    clip = tmp_path / 'take.mp4'
    clip.write_bytes(b'x')
    out = tmp_path / 'elsewhere' / 'report'
    paths = ES._prepare_run(str(clip), str(out), 'run-42')
    assert paths.out_dir == str(out)
    assert paths.run_id == 'run-42'
    assert os.path.isdir(out)


def test_a_generated_run_id_names_the_clip_stem(tmp_path):
    clip = tmp_path / 'take.mp4'
    clip.write_bytes(b'x')
    run_id = ES._prepare_run(str(clip), None, None).run_id
    assert run_id.startswith('vlmrep_take_')
    assert len(run_id) == len('vlmrep_take_20260101_000000')


# ── _load_metadata ───────────────────────────────────────────────────────────


def test_metadata_defaults_to_the_shot_metadata_sibling_of_the_clip(tmp_path):
    (tmp_path / 'shot_metadata.json').write_text(json.dumps({'beats': [1.0], 'pins': {}}), encoding='utf-8')
    clip = tmp_path / 'take.mp4'
    clip.write_bytes(b'x')
    logged = []
    meta = ES._load_metadata(None, str(clip), logged.append)
    assert meta == {'beats': [1.0], 'pins': {}}
    assert logged == ["metadata keys: ['beats', 'pins']"]


def test_no_metadata_file_is_an_empty_dict_not_a_failure(tmp_path):
    clip = tmp_path / 'take.mp4'
    clip.write_bytes(b'x')
    assert ES._load_metadata(None, str(clip), lambda m: None) == {}


def test_unreadable_metadata_is_logged_and_the_run_continues_without_pins(tmp_path):
    bad = tmp_path / 'shot_metadata.json'
    bad.write_text('{not json', encoding='utf-8')
    clip = tmp_path / 'take.mp4'
    clip.write_bytes(b'x')
    logged = []
    assert ES._load_metadata(str(bad), str(clip), logged.append) == {}
    assert logged[0].startswith('shot_metadata unreadable (')
    assert 'continuing without pins' in logged[0]


def test_a_metadata_file_holding_null_reads_as_an_empty_dict(tmp_path):
    meta_file = tmp_path / 'm.json'
    meta_file.write_text('null', encoding='utf-8')
    clip = tmp_path / 'take.mp4'
    clip.write_bytes(b'x')
    assert ES._load_metadata(str(meta_file), str(clip), lambda m: None) == {}


# ── _clip_info ───────────────────────────────────────────────────────────────


def test_explicit_beat_times_win_and_are_rounded_to_two_places(monkeypatch):
    monkeypatch.setattr(ES, '_probe', lambda p: (1920, 1080, 25.0, 10.0))
    logged = []
    info = ES._clip_info('/tmp/take.mp4', {}, [0.0, 1.23456, 9.999], logged.append)
    assert info.times == [0.0, 1.23, 10.0]
    assert (info.w, info.h, info.fps, info.dur) == (1920, 1080, 25.0, 10.0)
    assert logged[0] == 'clip: 1920x1080 @ 25.00 fps, 10.00s'


def test_without_beat_times_the_authored_defaults_are_used(monkeypatch):
    monkeypatch.setattr(ES, '_probe', lambda p: (1920, 1080, 25.0, 10.0))
    monkeypatch.setattr(ES, '_default_times', lambda meta, dur: [0.0, dur / 2])
    info = ES._clip_info('/tmp/take.mp4', {'beats': []}, None, lambda m: None)
    assert info.times == [0.0, 5.0]


# ── _resolve_targets ─────────────────────────────────────────────────────────


def test_a_role_with_no_detection_falls_back_to_its_half_frame_box(monkeypatch):
    monkeypatch.delenv('ZYG_VLM_REPORT_GROUND', raising=False)
    monkeypatch.setattr(ES, '_pin_targets', lambda meta, regions, log: {})
    monkeypatch.setattr(ES, '_ground_targets', lambda *a, **kw: {'_hands_per_t': {}})
    monkeypatch.setattr(ES, '_merge_targets', lambda pins, grounded, w, h, log: dict(pins))
    monkeypatch.setattr(ES, '_hand_side_targets', lambda *a: {})
    logged = []
    targets = ES._resolve_targets('/tmp/t.mp4', {}, None, None, [0.0], 1920, 1080, logged.append)
    assert set(targets) == {'man', 'boy'}
    assert targets['man']['source'] == 'fallback'
    assert targets['man']['box_frac'] == list(ES.PERSON_FALLBACK['man'])
    assert 'crops are LOOSER than normal here' in targets['man']['note']
    assert any('no usable detection' in line for line in logged)


def test_an_authored_pin_beats_a_detection_for_the_same_role(monkeypatch):
    pin = {'name': 'man', 'box_frac': [0.1, 0.1, 0.4, 0.9], 'source': 'pin', 'per_frame': {}}
    det = {'name': 'man', 'box_frac': [0.0, 0.0, 1.0, 1.0], 'source': 'ground', 'per_frame': {}}
    monkeypatch.setattr(ES, '_pin_targets', lambda meta, regions, log: {'man': dict(pin)})
    monkeypatch.setattr(ES, '_ground_targets', lambda *a, **kw: {'man': det, '_hands_per_t': {}})
    monkeypatch.setattr(ES, '_merge_targets', lambda pins, grounded, w, h, log: dict(pins))
    monkeypatch.setattr(ES, '_hand_side_targets', lambda *a: {})
    targets = ES._resolve_targets('/tmp/t.mp4', {}, None, True, [0.0], 1920, 1080, lambda m: None)
    assert targets['man']['source'] == 'pin'


def test_grounding_is_skipped_when_the_caller_says_so(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError('the detector must not run')

    monkeypatch.setattr(ES, '_pin_targets', lambda meta, regions, log: {})
    monkeypatch.setattr(ES, '_ground_targets', _boom)
    monkeypatch.setattr(ES, '_merge_targets', lambda pins, grounded, w, h, log: dict(pins))
    monkeypatch.setattr(ES, '_hand_side_targets', lambda *a: {})
    targets = ES._resolve_targets('/tmp/t.mp4', {}, None, False, [0.0], 1920, 1080, lambda m: None)
    assert targets['man']['source'] == 'fallback'


# ── _judge_crops and _tier_note ──────────────────────────────────────────────


def test_the_judging_record_reports_the_tier_that_actually_answered(monkeypatch):
    class _VLM:
        @staticmethod
        def model_for(tier):
            return f'model-for-{tier}'

    monkeypatch.setattr(
        ES,
        '_run_inspection',
        lambda *a: ([{'model': 'qwen-8b', 'tier': 'resident'}], [{'id': 'loc'}], 4),
    )
    logged = []
    judging = ES._judge_crops(_VLM, {}, 'cl', {}, 'boundary', 3, [], '/tmp', logged.append, None)
    assert (judging.model, judging.tier, judging.n_calls) == ('qwen-8b', 'resident', 4)
    assert logged == ['inspection: 1 screen verdicts, 1 localization verdicts, 4 worker runs on qwen-8b']


def test_an_empty_judging_round_reports_the_requested_tier(monkeypatch):
    class _VLM:
        @staticmethod
        def model_for(tier):
            return f'model-for-{tier}'

    monkeypatch.setattr(ES, '_run_inspection', lambda *a: ([], [], 0))
    judging = ES._judge_crops(_VLM, {}, 'cl', {}, 'boundary', 3, [], '/tmp', lambda m: None, None)
    assert (judging.model, judging.tier) == ('model-for-boundary', 'boundary')


def test_the_tier_note_names_the_tier_the_model_and_the_vote_count():
    note = ES._tier_note(_judging(tier='resident', model='qwen-8b'), 3)
    assert note == ('The judging tier was `resident` (qwen-8b); critical items were asked 3 times and majority-voted.')


# ── _synthesise ──────────────────────────────────────────────────────────────


def test_the_synthesis_prompt_is_saved_beside_the_report(monkeypatch, tmp_path):
    monkeypatch.setattr(ES, '_synthesis_prompt', lambda *a: 'THE PROMPT')
    monkeypatch.setattr(ES, '_run_synthesis', lambda prompt, *a, **kw: {'text': 'ok', 'prompt_seen': prompt})
    out = ES._synthesise(
        str(tmp_path), '/tmp/t.mp4', {}, '', [], {}, {}, {}, 3, 10.0, 'note', 'boundary', None, None, True
    )
    assert out == {'text': 'ok', 'prompt_seen': 'THE PROMPT'}
    assert (tmp_path / 'synthesis_prompt.txt').read_text(encoding='utf-8') == 'THE PROMPT'


def test_a_prompt_that_cannot_be_saved_still_synthesises(monkeypatch, tmp_path):
    monkeypatch.setattr(ES, '_synthesis_prompt', lambda *a: 'THE PROMPT')
    monkeypatch.setattr(ES, '_run_synthesis', lambda *a, **kw: {'text': 'ok'})
    missing = tmp_path / 'not' / 'there'
    out = ES._synthesise(
        str(missing), '/tmp/t.mp4', {}, '', [], {}, {}, {}, 3, 10.0, 'note', 'boundary', None, None, True
    )
    assert out == {'text': 'ok'}


# ── the two report records ───────────────────────────────────────────────────


def test_the_markdown_context_carries_the_synthesis_and_the_clip_geometry():
    ctx = ES._report_context(
        '/tmp/t.mp4',
        'run-1',
        _info(),
        _judging(),
        {'man': {}},
        3,
        [{'id': 'f1'}],
        'FAIL',
        {'sharpness': 1.0},
        {'prior': []},
        {'text': 'the report', 'model': 'qwen-32b', 'tier': 'boundary', 'seconds': 12.0, 'fell_back': False},
        'boundary',
        3,
        [1],
        [2],
        4096,
        31.4,
    )
    assert ctx['verdict'] == 'FAIL'
    assert ctx['synth_text'] == 'the report'
    assert ctx['synth_model'] == 'qwen-32b'
    assert ctx['requested_tier'] == 'boundary'
    assert ctx['inspect_model'] == 'qwen2.5-vl-8b'
    assert ctx['n_vlm_calls'] == 7
    assert (ctx['w'], ctx['h'], ctx['fps'], ctx['dur']) == (1920, 1080, 25.0, 10.0)
    assert ctx['times'] == [0.0, 5.0, 9.5]
    assert ctx['elapsed_s'] == 31.4


def test_the_raw_record_splits_the_synthesis_text_out_of_its_metadata():
    raw = ES._raw_record(
        '/tmp/t.mp4',
        'run-1',
        'scene20_binary',
        _info(),
        _judging(),
        {'man': {}},
        ['/tmp/crop0.png'],
        [{'id': 'f1'}],
        'PASS',
        {},
        {},
        {'text': 'the report', 'model': 'qwen-32b', 'seconds': 12.0},
        3,
        [],
        [],
        4096,
        31.4,
    )
    assert raw['ok'] is True
    assert raw['synthesis_text'] == 'the report'
    assert 'text' not in raw['synthesis']
    assert raw['synthesis']['model'] == 'qwen-32b'
    assert raw['clip_info'] == {'w': 1920, 'h': 1080, 'fps': 25.0, 'duration_s': 10.0}
    assert raw['checklist'] == 'scene20_binary'
    assert raw['vlm']['worker_runs'] == 7
    assert raw['vlm']['screen'] == [{'id': 'a', 'ok': True}]


# ── _write_reports ───────────────────────────────────────────────────────────


def _write_reports(paths, monkeypatch, **over):
    """Call _write_reports with the long argument list filled in."""
    args = {
        'checklist': 'scene20_binary',
        'info': _info(),
        'judging': _judging(),
        'targets': {},
        'crops': ['/tmp/c0.png'],
        'findings': [],
        'verdict': 'PASS',
        'pixel': {},
        'prior': {},
        'synth': {'text': 'the report'},
        'tier': 'boundary',
        'k_critical': 3,
        'ledger_rows': [],
        'lesson_rows': [],
        'peak_mb': 4096,
        'elapsed': 1.0,
        'log': lambda m: None,
    }
    args.update(over)
    return ES._write_reports(paths, **args)


def test_both_report_artefacts_are_written_to_the_out_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(ES, '_write_markdown', lambda path, ctx: path)
    paths = ES._RunPaths('/tmp/t.mp4', 't', str(tmp_path), str(tmp_path), str(tmp_path), 'run-1', 'scene20')
    md, rj = _write_reports(paths, monkeypatch)
    assert md == os.path.join(str(tmp_path), 'DEFECT_REPORT.md')
    assert rj == os.path.join(str(tmp_path), 'defect_report.json')
    assert json.loads(open(rj, encoding='utf-8').read())['run_id'] == 'run-1'


def test_a_raw_json_that_cannot_be_written_is_logged_and_reported_as_none(monkeypatch, tmp_path):
    monkeypatch.setattr(ES, '_write_markdown', lambda path, ctx: path)
    missing = tmp_path / 'not' / 'there'
    paths = ES._RunPaths('/tmp/t.mp4', 't', str(missing), str(missing), str(missing), 'run-1', 'scene20')
    logged = []
    md, rj = _write_reports(paths, monkeypatch, log=logged.append)
    assert md == os.path.join(str(missing), 'DEFECT_REPORT.md')
    assert rj is None
    assert logged[0].startswith('could not write raw json (')


# ── _record_ledger ───────────────────────────────────────────────────────────


def test_the_run_is_recorded_as_a_ledger_stage(monkeypatch):
    class _VLM:
        TIERS = {'resident': {'device': 'cuda:0'}}

    recorded = {}
    import zyg_workflows.run_ledger as run_ledger

    monkeypatch.setattr(run_ledger, 'record_stage', lambda name, **kw: recorded.update({'name': name, **kw}))
    ES._record_ledger(_VLM, _judging(), {'model': 'qwen-32b', 'fell_back': True}, 'run-1', 31.4, 4096)
    assert recorded['name'] == 'vlm_report'
    assert recorded['run_id'] == 'run-1'
    assert recorded['device'] == 'cuda:0'
    assert recorded['model_id'] == 'qwen2.5-vl-8b + qwen-32b'
    assert recorded['wall_s'] == 31.4
    assert recorded['vram_peak_mb'] == 4096
    assert recorded['fallback_taken'] is True


def test_a_ledger_that_refuses_does_not_fail_the_run(monkeypatch):
    class _VLM:
        TIERS = {}

    import zyg_workflows.run_ledger as run_ledger

    def _boom(*a, **kw):
        raise RuntimeError('no database')

    monkeypatch.setattr(run_ledger, 'record_stage', _boom)
    ES._record_ledger(_VLM, _judging(), {}, 'run-1', 1.0, 0)
