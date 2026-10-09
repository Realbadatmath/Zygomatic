# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the stage helpers split out of ``_render_char_preview_images``.

No GPU, no network, no services: the FLUX pipeline, the LoRA trainer and the
character bible are all replaced by stubs. These stages were unreachable while they
lived inside a 328-line function — in particular the fail-closed adapter guard, which
is the whole point of the c3345deb5bde fix and had no test at all.
"""

import os
import sys
import types

import pytest

from zyg_workflows import gui_state
from zyg_workflows.char_state_service import render_images_stages as st
from zyg_workflows.char_state_service.render_images_stages import (
    _PreviewRun,
    _apply_bible_auto_defaults,
    _attach_preview_lora,
    _comfy_flux_fast_path,
    _ensure_bible_package,
    _lora_unresolved_result,
    _preview_provenance_extra,
    _render_preview_slots,
    _resolve_flux_model_path,
    _resolve_lora_from_bible,
    _unload_preview_lora,
    _wait_for_preview_lora,
)


def _stub_submodule(monkeypatch, name, **attrs):
    """Install ``zyg_workflows.<name>`` as a stub for one test.

    Both the package attribute and ``sys.modules`` are patched: ``from zyg_workflows
    import x`` reads the attribute when the real module is already imported.
    """
    import zyg_workflows

    mod = types.ModuleType(f'zyg_workflows.{name}')
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, f'zyg_workflows.{name}', mod)
    monkeypatch.setattr(zyg_workflows, name, mod, raising=False)
    return mod


def _run(tmp_path, **over):
    logs = []
    kw = dict(
        char_id='c0ffee1234',
        params={},
        info={},
        dataset_dir=str(tmp_path),
        trigger='ZYG_CHAR_C0FFEE',
        model_family='flux',
        log=logs.append,
    )
    kw.update(over)
    run = _PreviewRun(**kw)
    return run, (logs if 'log' not in over else over['log'])


# ── the pure result builders ──────────────────────────────────────────────────


def test_lora_unresolved_result_refuses_the_render_without_an_error_of_none():
    """The c3345deb5bde defect was exactly an unresolved adapter returning error=None."""
    got = _lora_unresolved_result('flux')
    assert got == {
        'rendered': [],
        'skipped': False,
        'lora_used': False,
        'error': 'lora_unresolved',
        'backend': 'flux',
    }
    assert _lora_unresolved_result('sdxl')['backend'] == 'sdxl'


def test_preview_provenance_extra_marks_the_tier_from_the_adapter():
    locked = _preview_provenance_extra('flux', 'c0ffee', True)
    other = _preview_provenance_extra('sdxl', 'c0ffee', False)
    assert locked == {
        'renderer': 'diffusers_inprocess',
        'render_family': 'flux',
        'tier': 'locked',
        'lora_scale': 0.85,
        'char_id': 'c0ffee',
    }
    assert other['tier'] == 'other'
    assert other['lora_scale'] is None
    assert other['render_family'] == 'sdxl'


# ── the bible helpers ─────────────────────────────────────────────────────────


def test_ensure_bible_package_attaches_the_loaded_package(monkeypatch):
    _stub_submodule(monkeypatch, 'character_bible_service', load=lambda cid: {'conditioning': {'x': 1}})
    info = {}
    _ensure_bible_package('c0ffee', info, 'flux render')
    assert info['package'] == {'conditioning': {'x': 1}}


def test_ensure_bible_package_leaves_an_existing_package_alone(monkeypatch):
    def _boom(_cid):
        raise AssertionError('the bible must not be loaded twice')

    _stub_submodule(monkeypatch, 'character_bible_service', load=_boom)
    info = {'package': {'already': True}}
    _ensure_bible_package('c0ffee', info, 'flux preview')
    assert info == {'package': {'already': True}}


def test_ensure_bible_package_survives_a_failing_bible(monkeypatch):
    def _raise(_cid):
        raise RuntimeError('no bible on disk')

    _stub_submodule(monkeypatch, 'character_bible_service', load=_raise)
    info = {}
    _ensure_bible_package('c0ffee', info, 'flux render')  # must not raise
    assert 'package' not in info


def test_apply_bible_auto_defaults_returns_the_completed_params(monkeypatch):
    _stub_submodule(
        monkeypatch,
        'character_bible_service',
        apply_auto_defaults=lambda params, seed_key: {**params, 'seed_key': seed_key, 'quality_suffix': 'x'},
    )
    got = _apply_bible_auto_defaults('c0ffee', {'prompt': 'a'})
    assert got == {'prompt': 'a', 'seed_key': 'c0ffee', 'quality_suffix': 'x'}


def test_apply_bible_auto_defaults_falls_back_to_the_params_it_was_given(monkeypatch):
    def _raise(params, seed_key):
        raise ValueError('bible is corrupt')

    _stub_submodule(monkeypatch, 'character_bible_service', apply_auto_defaults=_raise)
    original = {'prompt': 'a'}
    got = _apply_bible_auto_defaults('c0ffee', original)
    assert got is original


# ── _comfy_flux_fast_path ─────────────────────────────────────────────────────


def test_comfy_fast_path_is_skipped_when_the_bible_asks_for_neither_feature(monkeypatch, tmp_path):
    _stub_submodule(monkeypatch, 'character_bible_service', load=lambda cid: None)
    run, logs = _run(tmp_path, info={'package': {'conditioning': {}}})

    def _never(*a, **k):
        raise AssertionError('ComfyUI must not be called without instantid/face_detail')

    assert _comfy_flux_fast_path(run, comfy_render=_never, log_fn=run.log, force=False) is None
    assert logs == []


def test_comfy_fast_path_returns_the_comfy_result_when_it_rendered(monkeypatch, tmp_path):
    _stub_submodule(monkeypatch, 'comfy_generation_service', is_available=lambda: True)
    monkeypatch.setattr(st, '_pick_char_preview_reference', lambda d, i: 'ref.png')
    run, _logs = _run(tmp_path, info={'package': {'conditioning': {'instantid_enabled': True}}})
    expected = {'rendered': ['front.png'], 'skipped': False}
    seen = {}

    def _comfy(char_id, params, info, *, log_fn, force, model_family):
        seen.update(char_id=char_id, force=force, model_family=model_family)
        return expected

    assert _comfy_flux_fast_path(run, comfy_render=_comfy, log_fn=run.log, force=True) is expected
    assert seen == {'char_id': 'c0ffee1234', 'force': True, 'model_family': 'flux'}


def test_comfy_fast_path_falls_back_in_process_when_comfy_produced_nothing(monkeypatch, tmp_path):
    _stub_submodule(monkeypatch, 'comfy_generation_service', is_available=lambda: True)
    monkeypatch.setattr(st, '_pick_char_preview_reference', lambda d, i: 'ref.png')
    run, logs = _run(tmp_path, info={'package': {'conditioning': {'face_detail_pass': True}}})
    got = _comfy_flux_fast_path(
        run,
        comfy_render=lambda *a, **k: {'rendered': [], 'skipped': False, 'error': 'queue timeout'},
        log_fn=run.log,
        force=False,
    )
    assert got is None
    assert logs == ['ComfyUI FLUX preview did not produce images (queue timeout) — falling back to in-process FLUX']


def test_comfy_fast_path_falls_back_when_comfy_is_unavailable(monkeypatch, tmp_path):
    def _raise():
        raise RuntimeError('connection refused')

    _stub_submodule(monkeypatch, 'comfy_generation_service', is_available=_raise)
    run, logs = _run(tmp_path, info={'package': {'conditioning': {'instantid_enabled': True}}})
    assert _comfy_flux_fast_path(run, comfy_render=lambda *a, **k: {}, log_fn=run.log, force=False) is None
    assert logs == ['ComfyUI FLUX preview unavailable (connection refused) — using in-process FLUX']


# ── adapter resolution ────────────────────────────────────────────────────────


class _Trainer:
    def __init__(self, statuses, path=None):
        self._statuses = list(statuses)
        self._path = path

    def get_status(self, char_id, *, model_family):
        return self._statuses.pop(0) if self._statuses else {}

    def get_lora_path(self, char_id, *, model_family):
        return self._path


def test_wait_for_preview_lora_resolves_a_readable_adapter(monkeypatch, tmp_path):
    adapter = tmp_path / 'char.safetensors'
    adapter.write_bytes(b'w')
    _stub_submodule(
        monkeypatch,
        'lora_trainer_service',
        get_trainer=lambda: _Trainer([{'lora_path': str(adapter)}]),
    )
    path, reason = _wait_for_preview_lora('c0ffee', 'flux', 60)
    assert path == str(adapter)
    assert reason == 'resolved'


def test_wait_for_preview_lora_reports_a_failed_trainer(monkeypatch):
    _stub_submodule(
        monkeypatch,
        'lora_trainer_service',
        get_trainer=lambda: _Trainer([{'failed': True}]),
    )
    assert _wait_for_preview_lora('c0ffee', 'flux', 60) == (None, 'trainer_failed')


def test_wait_for_preview_lora_reports_a_finished_trainer_with_no_path(monkeypatch):
    _stub_submodule(
        monkeypatch,
        'lora_trainer_service',
        get_trainer=lambda: _Trainer([{'done': True}]),
    )
    assert _wait_for_preview_lora('c0ffee', 'flux', 60) == (None, 'trainer_done_no_path')


def test_wait_for_preview_lora_times_out_without_sleeping_forever(monkeypatch):
    _stub_submodule(
        monkeypatch,
        'lora_trainer_service',
        get_trainer=lambda: _Trainer([{} for _ in range(4)]),
    )
    monkeypatch.setattr(st.time, 'sleep', lambda s: None)
    assert _wait_for_preview_lora('c0ffee', 'flux', 0) == (None, 'wait_timeout')


def test_wait_for_preview_lora_wraps_a_trainer_error(monkeypatch):
    def _raise():
        raise RuntimeError('trainer socket is gone')

    _stub_submodule(monkeypatch, 'lora_trainer_service', get_trainer=_raise)
    path, reason = _wait_for_preview_lora('c0ffee', 'flux', 60)
    assert path is None
    assert reason == 'trainer_error: trainer socket is gone'


def test_resolve_lora_from_bible_finds_what_the_trainer_did_not(monkeypatch, tmp_path):
    adapter = tmp_path / 'from_bible.safetensors'
    adapter.write_bytes(b'w')
    monkeypatch.setattr(st, '_char_preview_slot_lora_path', lambda cond, fam, cid, dd: str(adapter))
    logs = []
    got = _resolve_lora_from_bible({'package': {'conditioning': {}}}, 'c0ffee', str(tmp_path), logs.append)
    assert got == (str(adapter), 'resolved_from_bible')
    assert logs == ['Trainer had no adapter path — resolved from bible/disk: from_bible.safetensors']


def test_resolve_lora_from_bible_ignores_a_path_that_is_not_on_disk(monkeypatch, tmp_path):
    monkeypatch.setattr(st, '_char_preview_slot_lora_path', lambda *a: str(tmp_path / 'absent.safetensors'))
    logs = []
    assert _resolve_lora_from_bible({}, 'c0ffee', str(tmp_path), logs.append) == (None, None)
    assert logs == []


def test_resolve_lora_from_bible_never_raises(monkeypatch, tmp_path):
    def _raise(*a):
        raise KeyError('conditioning')

    monkeypatch.setattr(st, '_char_preview_slot_lora_path', _raise)
    assert _resolve_lora_from_bible({}, 'c0ffee', str(tmp_path), lambda m: None) == (None, None)


# ── _resolve_flux_model_path ──────────────────────────────────────────────────


def test_resolve_flux_model_path_prefers_dev_when_it_is_on_disk(monkeypatch):
    _stub_submodule(monkeypatch, 'licence_provenance', flux_paused=lambda: False)
    monkeypatch.setattr(st.os.path, 'isdir', lambda p: p.endswith('flux1-dev'))
    path, use_dev = _resolve_flux_model_path(lambda m: None)
    assert use_dev is True
    assert path.endswith('flux1-dev')


def test_resolve_flux_model_path_falls_back_to_schnell_when_dev_is_absent(monkeypatch):
    _stub_submodule(monkeypatch, 'licence_provenance', flux_paused=lambda: False)
    monkeypatch.setattr(st.os.path, 'isdir', lambda p: False)
    path, use_dev = _resolve_flux_model_path(lambda m: None)
    assert use_dev is False
    assert path.endswith('flux1-schnell')


def test_a_flux_licence_pause_downgrades_dev_to_schnell(monkeypatch):
    """Under a pause only the Apache-2.0 schnell weights may load."""
    _stub_submodule(monkeypatch, 'licence_provenance', flux_paused=lambda: True)
    monkeypatch.setattr(st.os.path, 'isdir', lambda p: True)
    logs = []
    path, use_dev = _resolve_flux_model_path(logs.append)
    assert use_dev is False
    assert path.endswith('flux1-schnell')
    assert logs == ['[licence] flux1-dev preview blocked (pause) — using schnell']


# ── _attach_preview_lora ──────────────────────────────────────────────────────


class _Pipe:
    def __init__(self, fail_load=False):
        self.fail_load = fail_load
        self.loaded = None
        self.adapters = None
        self.unloaded = 0

    def load_lora_weights(self, path, adapter_name):
        if self.fail_load:
            raise RuntimeError('rank mismatch')
        self.loaded = (path, adapter_name)

    def set_adapters(self, names, adapter_weights):
        self.adapters = (names, adapter_weights)

    def unload_lora_weights(self):
        self.unloaded += 1


def test_attach_preview_lora_loads_the_adapter_at_weight_085(monkeypatch, tmp_path):
    adapter = tmp_path / 'char.safetensors'
    adapter.write_bytes(b'w')
    pipe = _Pipe()
    monkeypatch.setattr(gui_state, '_FLUX_DEV_PIPELINE_CACHE', pipe)
    logs = []
    used, early = _attach_preview_lora(str(adapter), 'flux', logs.append)
    assert (used, early) == (True, None)
    assert pipe.loaded == (str(adapter), 'char_prev')
    assert pipe.adapters == (['char_prev'], [0.85])
    assert logs == ['Preview using trained LoRA: char.safetensors']


def test_attach_preview_lora_aborts_when_the_adapter_will_not_load(monkeypatch, tmp_path):
    adapter = tmp_path / 'char.safetensors'
    adapter.write_bytes(b'w')
    monkeypatch.setattr(gui_state, '_FLUX_DEV_PIPELINE_CACHE', _Pipe(fail_load=True))
    monkeypatch.setattr(st, '_release_flux_pipeline', lambda note, log=None: None)
    logs = []
    used, early = _attach_preview_lora(str(adapter), 'flux', logs.append)
    assert used is False
    assert early['error'].startswith('lora_load_failed: rank mismatch')
    assert early['rendered'] == [] and early['backend'] == 'flux'
    assert logs == ['ERROR: trained-LoRA load failed (rank mismatch) — aborting preview']


def test_attach_preview_lora_fails_closed_when_the_adapter_vanished(monkeypatch, tmp_path):
    """Belt and braces: an unresolved adapter must never reach a bare-FLUX render."""
    monkeypatch.setenv('ZYG_PREVIEW_REQUIRE_LORA', '1')
    monkeypatch.setattr(st, '_release_flux_pipeline', lambda note, log=None: None)
    logs = []
    used, early = _attach_preview_lora(str(tmp_path / 'absent.safetensors'), 'flux', logs.append)
    assert used is False
    assert early == _lora_unresolved_result('flux')
    assert logs[0].startswith('ERROR: adapter vanished before load (')


def test_attach_preview_lora_allows_a_base_render_only_when_the_guard_is_off(monkeypatch):
    monkeypatch.setenv('ZYG_PREVIEW_REQUIRE_LORA', '0')
    logs = []
    assert _attach_preview_lora(None, 'flux', logs.append) == (False, None)
    assert logs == []


def test_unload_preview_lora_never_raises_on_an_empty_cache(monkeypatch):
    pipe = _Pipe()
    monkeypatch.setattr(gui_state, '_FLUX_DEV_PIPELINE_CACHE', pipe)
    _unload_preview_lora()
    assert pipe.unloaded == 1
    monkeypatch.setattr(gui_state, '_FLUX_DEV_PIPELINE_CACHE', None)
    _unload_preview_lora()  # must not raise


# ── _render_preview_slots ─────────────────────────────────────────────────────


class _Image:
    def __init__(self, sink):
        self._sink = sink

    def save(self, path):
        self._sink.append(path)
        with open(path, 'wb') as fh:
            fh.write(b'png')


class _SlotPipe:
    """A stand-in for the FLUX pipeline: records its kwargs, yields a fake image."""

    def __init__(self, sink, fail_on=()):
        self.sink = sink
        self.fail_on = set(fail_on)
        self.calls = []

    def __call__(self, **kw):
        self.calls.append(kw)
        if kw['prompt'] in self.fail_on:
            raise RuntimeError('CUDA OOM')
        return types.SimpleNamespace(images=[_Image(self.sink)])


@pytest.fixture
def _slot_env(monkeypatch):
    saved = []
    monkeypatch.setattr(st, '_write_preview_provenance', lambda png, **kw: saved.append((png, kw)))
    monkeypatch.setattr(st, '_preview_restyle_name', lambda mf, p, i: 'noir')
    monkeypatch.setattr(st._runtime, 'bm_record', lambda *a, **k: None)
    return saved


def test_render_preview_slots_writes_png_prompt_and_provenance(monkeypatch, tmp_path, _slot_env):
    pipe = _SlotPipe([])
    monkeypatch.setattr(gui_state, '_FLUX_DEV_PIPELINE_CACHE', pipe)
    run, logs = _run(tmp_path)
    rendered, err = _render_preview_slots(
        run,
        [('preview_flux_front', ' a knight  ', 768, 1024)],
        use_dev=True,
        lora_used=True,
        lora_path='/models/char.safetensors',
    )
    png = str(tmp_path / 'preview_flux_front.png')
    assert rendered == [png]
    assert err is None
    assert os.path.isfile(png)
    with open(os.path.join(str(tmp_path), 'preview_flux_front.txt'), encoding='utf-8') as fh:
        assert fh.read() == 'a knight\n'
    assert logs == ['Saved preview_flux_front.png']
    assert pipe.calls[0]['num_inference_steps'] == 28
    assert pipe.calls[0]['guidance_scale'] == 2.8, '3.5 is FLUX plastic-skin territory'
    assert pipe.calls[0]['width'] == 768 and pipe.calls[0]['height'] == 1024
    (_p, kw) = _slot_env[0]
    assert kw['backend'] == 'flux_dev_inprocess'
    assert kw['lora_path'] == '/models/char.safetensors'
    assert kw['restyle'] == 'noir'
    assert kw['extra'] == _preview_provenance_extra('flux', 'c0ffee1234', True)


def test_render_preview_slots_uses_the_schnell_sampling_budget(monkeypatch, tmp_path, _slot_env):
    pipe = _SlotPipe([])
    monkeypatch.setattr(gui_state, '_FLUX_DEV_PIPELINE_CACHE', pipe)
    run, _logs = _run(tmp_path)
    _render_preview_slots(
        run,
        [('preview_flux_face', 'a face', 512, 512)],
        use_dev=False,
        lora_used=False,
        lora_path=None,
    )
    assert pipe.calls[0]['num_inference_steps'] == 8
    assert pipe.calls[0]['guidance_scale'] == 0.0
    assert _slot_env[0][1]['backend'] == 'flux_schnell_inprocess'
    assert _slot_env[0][1]['lora_path'] is None, 'an unused adapter must not be claimed'


def test_render_preview_slots_skips_sdxl_slots(monkeypatch, tmp_path, _slot_env):
    pipe = _SlotPipe([])
    monkeypatch.setattr(gui_state, '_FLUX_DEV_PIPELINE_CACHE', pipe)
    run, logs = _run(tmp_path)
    rendered, err = _render_preview_slots(
        run,
        [('preview_sdxl_front', 'p', 512, 512, 'sdxl')],
        use_dev=True,
        lora_used=False,
        lora_path=None,
    )
    assert rendered == [] and err is None
    assert pipe.calls == []
    assert logs == ['Skipping in-process FLUX for SDXL slot preview_sdxl_front (Comfy-only)']


def test_render_preview_slots_keeps_going_after_one_slot_fails(monkeypatch, tmp_path, _slot_env):
    pipe = _SlotPipe([], fail_on={'bad'})
    monkeypatch.setattr(gui_state, '_FLUX_DEV_PIPELINE_CACHE', pipe)
    run, logs = _run(tmp_path)
    rendered, err = _render_preview_slots(
        run,
        [('a', 'bad', 512, 512), ('b', 'good', 512, 512)],
        use_dev=True,
        lora_used=False,
        lora_path=None,
    )
    assert rendered == [str(tmp_path / 'b.png')]
    assert err == 'CUDA OOM'
    assert logs == ['Preview slot a failed: CUDA OOM', 'Saved b.png']
