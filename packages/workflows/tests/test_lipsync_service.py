#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Invariants of the InfiniteTalk lipsync leg.

    .venv-test/bin/python -m pytest tests/test_lipsync_service.py -q

`.venv-test` carries pytest/numpy/PIL but NOT requests, so `_comfy_client` cannot
be imported here. lipsync_service only ever imports it inside functions, which is
what makes that testable: the tests below install a stub module that loads the real
_comfy_workflows/infinitetalk_i2v.json and records what would have been submitted.
No GPU, no ComfyUI, no network.
"""

import json
import os
import types

import pytest

from tests import _tree
from zyg_workflows import lipsync_service as LS

_GRAPHS = os.path.join(_tree.PKG, '_comfy_workflows')
_WORKFLOW = os.path.join(_GRAPHS, f'{LS.WORKFLOW_NAME}.json')


@pytest.fixture
def comfy(stub_module):
    """Stub _comfy_client: real graph off disk, submit() recorded not sent."""
    stub = types.ModuleType('_comfy_client')
    stub.COMFY_HOST, stub.COMFY_PORT = '127.0.0.1', 8188
    stub.calls = {'submitted': [], 'staged': []}

    def load_workflow(name):
        with open(os.path.join(_GRAPHS, f'{name}.json')) as fh:
            return json.load(fh)

    def stage_input_image(path):
        stub.calls['staged'].append(path)
        return os.path.basename(path)

    def submit(wf, overrides=None, timeout_s=None, should_abort=None):
        stub.calls['submitted'].append(wf)
        return []

    stub.load_workflow = load_workflow
    stub.stage_input_image = stage_input_image
    stub.submit = submit
    stub.server_reachable = lambda *a, **k: True
    stub.has_node = lambda _c: True
    stub_module('_comfy_client', stub)
    return stub


# ── the graph the service will actually submit ──────────────────────────────
def test_workflow_ships_and_is_the_infinitetalk_graph():
    """The graph builder drives node ids from the committed file, so the file's
    class_types are part of the contract, not an implementation detail."""
    with open(_WORKFLOW) as fh:
        wf = json.load(fh)
    classes = {nid: node['class_type'] for nid, node in wf.items()}
    assert classes[LS.NODE_IMAGE] == 'LoadImage'
    assert classes[LS.NODE_AUDIO] == 'LoadAudio'
    assert classes[LS.NODE_EMBEDS] == 'MultiTalkWav2VecEmbeds'
    assert classes[LS.NODE_MULTITALK] == 'WanVideoImageToVideoMultiTalk'
    assert classes[LS.NODE_SAMPLER] == 'WanVideoSampler'
    assert wf[LS.NODE_MULTITALK]['inputs']['mode'] == 'infinitetalk'
    assert all('title' in node['_meta'] for node in wf.values())


def test_build_graph_sets_image_audio_size_and_prompt(comfy):
    g = LS.build_graph(
        'abel.png', 'line.wav', width=640, height=384, frames=75, steps=12, seed=99, prompt='a boy shouting a warning'
    )
    assert g[LS.NODE_IMAGE]['inputs']['image'] == 'abel.png'
    assert g[LS.NODE_AUDIO]['inputs']['audio'] == 'line.wav'
    assert g[LS.NODE_RESIZE]['inputs']['width'] == 640
    assert g[LS.NODE_RESIZE]['inputs']['height'] == 384
    assert g[LS.NODE_MULTITALK]['inputs']['width'] == 640
    assert g[LS.NODE_MULTITALK]['inputs']['height'] == 384
    assert g[LS.NODE_EMBEDS]['inputs']['num_frames'] == 75
    assert g[LS.NODE_SAMPLER]['inputs']['steps'] == 12
    assert g[LS.NODE_SAMPLER]['inputs']['seed'] == 99
    assert g[LS.NODE_TEXT]['inputs']['positive_prompt'] == 'a boy shouting a warning'


def test_build_graph_pins_25_fps_on_both_the_embeds_and_the_mux(comfy):
    """InfiniteTalk's wav2vec window is 25 fps upstream; the graph never argues
    with it — the service resamples afterwards instead."""
    g = LS.build_graph('abel.png', 'line.wav')
    assert g[LS.NODE_EMBEDS]['inputs']['fps'] == LS.NATIVE_FPS == 25.0
    assert g[LS.NODE_VIDEO]['inputs']['fps'] == 25.0


def test_workflow_attaches_the_lora_unmerged(comfy):
    """Not cosmetic: merge_loras=false is the only branch of the wrapper's
    loadmodel that reaches _replace_linear, which is the only code that applies
    the InfiniteTalk module's fp8 .scale_weight tensors. Merged (or absent), the
    audio cross-attention weights are ~11x too large and the take is noise."""
    with open(_WORKFLOW) as fh:
        wf = json.load(fh)
    assert wf[LS.NODE_LORA]['class_type'] == 'WanVideoLoraSelect'
    assert wf[LS.NODE_LORA]['inputs']['merge_loras'] is False
    assert wf['1']['inputs']['lora'] == [LS.NODE_LORA, 0]
    assert wf['1']['inputs']['quantization'] == 'fp8_e4m3fn'
    g = LS.build_graph('abel.png', 'line.wav', lora='wan_chars/other.safetensors', lora_strength=0.6)
    assert g[LS.NODE_LORA]['inputs']['lora'] == 'wan_chars/other.safetensors'
    assert g[LS.NODE_LORA]['inputs']['strength'] == 0.6


def test_build_graph_without_prompt_keeps_the_templates_own(comfy):
    with open(_WORKFLOW) as fh:
        default = json.load(fh)[LS.NODE_TEXT]['inputs']['positive_prompt']
    g = LS.build_graph('abel.png', 'line.wav', prompt=None)
    assert g[LS.NODE_TEXT]['inputs']['positive_prompt'] == default


def test_build_graph_does_not_mutate_the_file_on_disk(comfy):
    before = open(_WORKFLOW, 'rb').read()
    LS.build_graph('x.png', 'y.wav', width=1280, height=720, seed=1234)
    assert open(_WORKFLOW, 'rb').read() == before


# ── fail-safe contract: every failure returns None, nothing raises ──────────
def test_lipsync_returns_none_on_missing_wav(tmp_path, comfy):
    src = tmp_path / 'still.png'
    src.write_bytes(b'\x89PNG\r\n\x1a\n')
    logged = []
    out = LS.lipsync(str(src), str(tmp_path / 'nope.wav'), str(tmp_path / 'out'), log_fn=logged.append)
    assert out is None
    assert any('wav missing' in m for m in logged)
    assert not comfy.calls['submitted']


def test_lipsync_returns_none_on_missing_source(tmp_path, comfy):
    wav = tmp_path / 'line.wav'
    wav.write_bytes(b'RIFF')
    out = LS.lipsync(str(tmp_path / 'nope.png'), str(wav), str(tmp_path / 'out'))
    assert out is None
    assert not comfy.calls['submitted']


def test_lipsync_returns_none_when_comfy_is_unavailable(tmp_path, comfy, monkeypatch):
    monkeypatch.setattr(comfy, 'server_reachable', lambda *a, **k: False)
    src, wav = tmp_path / 'still.png', tmp_path / 'line.wav'
    src.write_bytes(b'\x89PNG\r\n\x1a\n')
    wav.write_bytes(b'RIFF')
    logged = []
    assert LS.lipsync(str(src), str(wav), str(tmp_path / 'out'), log_fn=logged.append) is None
    assert any('unavailable' in m for m in logged)


def test_lipsync_returns_none_when_submit_produces_nothing(tmp_path, comfy, monkeypatch):
    """The whole chain runs (duration probe, attest, submit) and still degrades."""
    src, wav = tmp_path / 'still.png', tmp_path / 'line.wav'
    src.write_bytes(b'\x89PNG\r\n\x1a\n')
    wav.write_bytes(b'RIFF')
    monkeypatch.setattr(LS, 'probe_duration_s', lambda _p: 3.0)
    monkeypatch.setattr(LS, '_attest', lambda _g, _log: True)
    logged = []
    assert LS.lipsync(str(src), str(wav), str(tmp_path / 'out'), log_fn=logged.append) is None
    assert comfy.calls['submitted'], 'submit should have been reached'
    g = comfy.calls['submitted'][0]
    assert g[LS.NODE_EMBEDS]['inputs']['num_frames'] == 75  # 3.0 s x 25 fps
    assert any('no output file produced' in m for m in logged)


def test_lipsync_swallows_an_exploding_submit(tmp_path, comfy, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError('comfy said no')

    monkeypatch.setattr(comfy, 'submit', boom)
    monkeypatch.setattr(LS, 'probe_duration_s', lambda _p: 3.0)
    monkeypatch.setattr(LS, '_attest', lambda _g, _log: True)
    src, wav = tmp_path / 'still.png', tmp_path / 'line.wav'
    src.write_bytes(b'\x89PNG\r\n\x1a\n')
    wav.write_bytes(b'RIFF')
    logged = []
    assert LS.lipsync(str(src), str(wav), str(tmp_path / 'out'), log_fn=logged.append) is None
    assert any('comfy said no' in m for m in logged)


def test_lipsync_refuses_when_the_licence_gate_blocks(tmp_path, comfy, monkeypatch):
    monkeypatch.setattr(LS, 'probe_duration_s', lambda _p: 3.0)
    monkeypatch.setattr(LS, '_attest', lambda _g, _log: False)
    src, wav = tmp_path / 'still.png', tmp_path / 'line.wav'
    src.write_bytes(b'\x89PNG\r\n\x1a\n')
    wav.write_bytes(b'RIFF')
    assert LS.lipsync(str(src), str(wav), str(tmp_path / 'out')) is None
    assert not comfy.calls['submitted']
