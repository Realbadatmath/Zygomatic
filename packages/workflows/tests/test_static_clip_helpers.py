# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the stages extracted from generate_vace_static_clip (2026-10-09).

Every one of these behaviours used to live inside a 727-line function, where the only way
to reach it was a GPU render: the prompt prefixing, the dead-beat refusal, the aspect crop,
the grey fill under the mask, the node ids the graph wires. Here each is exercised on plain
inputs with a stub comfy client, so none of them needs a GPU, a network or a service.
"""

import numpy as np
import pytest
from PIL import Image

from zyg_workflows.wan_vace_service.static_clip_graph import (
    apply_graded_pin,
    build_vace_graph,
    stage_graph_inputs,
    wire_canon_refs,
    wire_set_embed,
    wire_source_nodes,
)
from zyg_workflows.wan_vace_service.static_clip_inputs import (
    STATIC_PREFIX,
    ControlPlan,
    MaskPlan,
    build_prompt_pair,
    fit_still_to_render,
    neutralised_control_image,
    resolve_beat_map,
    resolve_mask_inputs,
)


@pytest.fixture(autouse=True)
def _neutral_vace_env(monkeypatch):
    """No test here depends on the operator's env switches, so unset every one of them."""
    for name in (
        'ZYG_BEAT_MAP_GATE',
        'ZYG_CHAR_GEOM_CTRL',
        'ZYG_MASK_GATE',
        'ZYG_VACE_DIFFDIFF',
        'ZYG_VACE_DIFFDIFF_WHOLE_MASK',
        'ZYG_VACE_MASK_SEQ',
        'ZYG_WAN_BEAT_CHARS',
        'ZYG_WAN_HEIGHT',
        'ZYG_WAN_WIDTH',
    ):
        monkeypatch.delenv(name, raising=False)


class StubComfy:
    """Stands in for zyg_workflows._comfy_client: records what the graph staged."""

    def __init__(self):
        self.staged = []

    def stage_input_image(self, path):
        """Return a deterministic server-side name and remember the call order."""
        self.staged.append(path)
        return f'staged:{len(self.staged)}'


def _png(path, size=(64, 48), colour=(10, 20, 30)):
    Image.new('RGB', size, colour).save(path)
    return str(path)


def _mask_png(path, size=(64, 48)):
    """A mask whose left half is white (generate) and right half black (keep)."""
    a = np.zeros((size[1], size[0]), dtype=np.uint8)
    a[:, : size[0] // 2] = 255
    Image.fromarray(a, mode='L').save(path)
    return str(path)


# --------------------------------------------------------------------------- prompts


def test_the_static_camera_grammar_is_prefixed_onto_an_unscheduled_prompt():
    pos, neg = build_prompt_pair('a man reads a ledger', '', 'blurry, watermark')
    assert pos == STATIC_PREFIX + 'a man reads a ledger'
    assert neg == 'blurry, watermark'


def test_every_beat_of_a_scheduled_prompt_gets_its_own_prefix():
    pos, _ = build_prompt_pair('he turns | she looks up | both still', '', 'blurry')
    beats = pos.split(' | ')
    assert len(beats) == 3
    assert [b.removeprefix(STATIC_PREFIX) for b in beats] == ['he turns', 'she looks up', 'both still']


def test_extra_negative_is_prepended_to_the_base_negative():
    _, neg = build_prompt_pair('x', '  extra one, extra two,  ', 'blurry, watermark')
    assert neg == 'extra one, extra two, blurry, watermark'


# --------------------------------------------------------------------------- beat gate


def test_an_unscheduled_prompt_never_consults_the_beat_map():
    ok, beat_map = resolve_beat_map('one beat only', 65, False, 81, 24, 4)
    assert (ok, beat_map) == (True, None)


def test_a_scheduled_prompt_without_context_windows_is_blocked_before_the_gpu():
    lines = []
    ok, beat_map = resolve_beat_map('a | b', 65, False, 81, 24, 4, log_fn=lines.append)
    assert (ok, beat_map) == (False, None)
    assert any('BLOCKED before submit' in ln for ln in lines)


def test_the_beat_gate_downgrades_to_a_warning_when_its_env_switch_is_off(monkeypatch):
    monkeypatch.setenv('ZYG_BEAT_MAP_GATE', '0')
    lines = []
    ok, beat_map = resolve_beat_map('a | b', 65, False, 81, 24, 4, log_fn=lines.append)
    assert (ok, beat_map) == (True, None)
    assert any('WARNING (ZYG_BEAT_MAP_GATE=0)' in ln for ln in lines)


def test_a_reachable_schedule_returns_the_window_to_beat_mapping():
    ok, beat_map = resolve_beat_map('a | b', 161, True, 81, 24, 4)
    assert ok
    assert set(beat_map['mapping']) == {0, 1}


# --------------------------------------------------------------------------- still fit


def test_a_wider_still_is_centre_cropped_to_the_render_aspect(tmp_path):
    still = _png(tmp_path / 'still.png', size=(1000, 500))
    fitted, w, h = fit_still_to_render(still, str(tmp_path), width=832, height=480)
    assert (w, h) == (832, 480)
    with Image.open(fitted) as im:
        assert im.size == (832, 480)
    assert fitted.endswith('_vace_still.png')


def test_the_render_size_falls_back_to_the_env_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYG_WAN_WIDTH', '640')
    monkeypatch.setenv('ZYG_WAN_HEIGHT', '640')
    still = _png(tmp_path / 'still.png', size=(300, 200))
    _fitted, w, h = fit_still_to_render(still, str(tmp_path))
    assert (w, h) == (640, 640)


# --------------------------------------------------------------------------- control frame


def test_the_generate_region_is_grey_filled_and_the_set_is_left_alone(tmp_path):
    still = _png(tmp_path / 'still.png', size=(64, 48), colour=(10, 20, 30))
    mask = _mask_png(tmp_path / 'mask.png', size=(64, 48))
    lines = []
    out = neutralised_control_image(still, mask, str(tmp_path), (64, 48), log_fn=lines.append)
    arr = np.asarray(Image.open(out).convert('RGB'))
    assert arr[:, :32].min() == 127 and arr[:, :32].max() == 127  # generate region: flat grey
    assert tuple(arr[0, 40]) == (10, 20, 30)  # keep region: the still's own pixels
    assert lines == ['[vace] control frames neutralized under mask']


# --------------------------------------------------------------------------- mask inputs


def test_a_frame_sequence_mask_is_refused_while_its_env_gate_is_unset(tmp_path):
    seq = tmp_path / 'maskseq'
    seq.mkdir()
    _mask_png(seq / 'm_00000.png')
    lines = []
    plan = resolve_mask_inputs(str(seq), 'unused.png', str(tmp_path), (64, 48), 9, log_fn=lines.append)
    assert plan is None
    assert any('ZYG_VACE_MASK_SEQ' in ln for ln in lines)


def test_a_supplied_mask_is_resized_to_the_render_size_before_the_gate(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYG_MASK_GATE', '0')  # keep the C3 preflight advisory for this test
    mask = _mask_png(tmp_path / 'mask.png', size=(32, 24))
    plan = resolve_mask_inputs(mask, 'unused.png', str(tmp_path), (64, 48), 9)
    assert plan is not None
    assert (plan.mask_path, plan.mask_dir, plan.seq_mode) == (mask, None, False)
    assert plan.pin_mask_src == mask
    with Image.open(plan.mask_path) as im:
        assert im.size == (64, 48)


# --------------------------------------------------------------------------- graph wiring


def _plans(tmp_path, ctrl_dir=None, mask_dir=None):
    mask = _mask_png(tmp_path / 'mask.png')
    return (
        MaskPlan(mask_path=mask, mask_dir=mask_dir, pin_mask_src=mask, seq_mode=bool(mask_dir)),
        ControlPlan(control_src=str(tmp_path / 'ctrl.png'), ctrl_dir=ctrl_dir, ctrl_mode='single control image'),
    )


def test_staging_skips_the_channels_that_are_per_frame_directories(tmp_path):
    masks, controls = _plans(tmp_path, ctrl_dir=str(tmp_path / 'cseq'), mask_dir=str(tmp_path / 'mseq'))
    comfy = StubComfy()
    st_still, st_ctrl, st_mask, st_refs = stage_graph_inputs(comfy, 'still.png', controls, masks)
    assert (st_still, st_ctrl, st_mask, st_refs) == ('staged:1', None, None, [])
    assert comfy.staged == ['still.png']


def test_a_missing_ref_image_is_dropped_instead_of_staged(tmp_path):
    masks, controls = _plans(tmp_path)
    ref = _png(tmp_path / 'ref.png')
    comfy = StubComfy()
    _, _, _, st_refs = stage_graph_inputs(comfy, 'still.png', controls, masks, [ref, str(tmp_path / 'gone.png'), None])
    assert st_refs == ['staged:4']


def test_the_single_image_path_repeats_one_frame_and_the_sequence_path_reads_a_folder(tmp_path):
    single = {}
    wire_source_nodes(single, 'c.png', 'm.png', None, None, (832, 480), 65)
    assert single['13']['class_type'] == 'RepeatImageBatch'
    assert single['13']['inputs']['amount'] == 65
    assert single['15']['class_type'] == 'RepeatImageBatch'

    seq = {}
    lines = []
    wire_source_nodes(seq, None, None, str(tmp_path / 'c'), str(tmp_path / 'm'), (832, 480), 65, log_fn=lines.append)
    assert seq['13']['class_type'] == 'LoadImagesFromFolderKJ'
    assert seq['15']['class_type'] == 'LoadImagesFromFolderKJ'
    # the KJ node raises TypeError without these two, so they are never optional here
    assert seq['15']['inputs']['image_load_cap'] == 65
    assert seq['15']['inputs']['start_index'] == 0
    assert any('PER-FRAME MASK SEQUENCE' in ln for ln in lines)


def test_three_canon_refs_become_an_image_batch_chain_in_the_vace_ref_seat():
    g = {'60': {'inputs': {'ref_images': ['10', 0]}}}
    wire_canon_refs(g, ['a', 'b', 'c'])
    assert g['60']['inputs']['ref_images'] == ['77', 0]
    assert [g[n]['class_type'] for n in ('71', '72', '73')] == ['LoadImage'] * 3
    assert g['76']['inputs'] == {'image1': ['71', 0], 'image2': ['72', 0]}
    assert g['77']['inputs'] == {'image1': ['76', 0], 'image2': ['73', 0]}


def test_one_canon_ref_is_wired_directly_and_a_fourth_is_ignored():
    g = {'60': {'inputs': {'ref_images': ['10', 0]}}}
    wire_canon_refs(g, ['a'])
    assert g['60']['inputs']['ref_images'] == ['71', 0]

    g4 = {'60': {'inputs': {'ref_images': ['10', 0]}}}
    wire_canon_refs(g4, ['a', 'b', 'c', 'd'])
    assert '74' not in g4


def test_the_set_embed_copies_the_ref_wiring_and_relaxes_the_subject_embed(tmp_path):
    plate = _png(tmp_path / 'plate.png')
    g = {'60': {'inputs': {'ref_images': ['77', 0], 'strength': 0.7, 'vace_end_percent': 0.7}}}
    assert wire_set_embed(g, StubComfy(), plate, (832, 480), 65) is True
    assert g['59']['inputs']['ref_images'] == ['77', 0]
    assert g['59']['inputs']['strength'] == 1.0
    assert g['60']['inputs']['prev_vace_embeds'] == ['59', 0]
    assert (g['60']['inputs']['strength'], g['60']['inputs']['vace_end_percent']) == (0.5, 0.35)


def test_a_missing_set_plate_leaves_the_graph_single_embed(tmp_path):
    g = {'60': {'inputs': {'ref_images': ['10', 0]}}}
    lines = []
    assert wire_set_embed(g, StubComfy(), str(tmp_path / 'gone.png'), (832, 480), 65, log_fn=lines.append) is True
    assert '59' not in g
    assert any('set plate missing' in ln for ln in lines)


def test_the_set_embed_aborts_rather_than_hand_the_two_embeds_different_refs(tmp_path):
    plate = _png(tmp_path / 'plate.png')
    # a ref seat that does not survive list() — the copy would differ and the window
    # slicer would then index one latent frame out of range, hours into the render
    g = {'60': {'inputs': {'ref_images': ('77', 0)}}}
    lines = []
    assert wire_set_embed(g, StubComfy(), plate, (832, 480), 65, log_fn=lines.append) is False
    assert 'prev_vace_embeds' not in g['60']['inputs']
    assert any('mismatched ref_images' in ln for ln in lines)


# --------------------------------------------------------------------------- graded pin


def test_the_graded_pin_emits_nothing_while_its_env_flag_is_off(tmp_path):
    g = {'30': {'inputs': {}}}
    apply_graded_pin(g, StubComfy(), str(tmp_path), (832, 480), str(tmp_path / 'm.png'), [{'box': (0, 0, 1, 1)}])
    assert list(g) == ['30'] and g['30']['inputs'] == {}


def test_the_flag_alone_cannot_change_a_render_when_no_pin_region_is_given(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYG_VACE_DIFFDIFF', '1')
    g = {'30': {'inputs': {}}}
    lines = []
    apply_graded_pin(g, StubComfy(), str(tmp_path), (832, 480), str(tmp_path / 'm.png'), [], log_fn=lines.append)
    assert list(g) == ['30'] and g['30']['inputs'] == {}
    assert any('pin region list is EMPTY' in ln for ln in lines)


def test_a_render_size_off_the_latent_grid_skips_the_pin(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYG_VACE_DIFFDIFF', '1')
    g = {'30': {'inputs': {}}}
    lines = []
    apply_graded_pin(g, StubComfy(), str(tmp_path), (830, 480), 'm.png', [{'box': (0, 0, 1, 1)}], log_fn=lines.append)
    assert '19' not in g
    assert any('not divisible by 16' in ln for ln in lines)


# --------------------------------------------------------------------------- whole graph


def test_the_whole_graph_carries_the_nodes_the_sampler_needs(tmp_path):
    masks, controls = _plans(tmp_path)
    comfy = StubComfy()
    g = build_vace_graph(
        comfy,
        'still.png',
        masks,
        controls,
        (832, 480),
        'pos',
        'neg',
        num_frames=65,
        steps=12,
        seed=3,
        loras=[('wan_chars/a.safetensors', 0.8)],
        out_dir=str(tmp_path),
    )
    assert g is not None
    for nid in ('1', '2', '4', '7', '10', '11', '13', '14', '15', '16', '20', '30', '40', '45', '50'):
        assert nid in g, nid
    assert g['1']['inputs']['lora'] == ['80', 0]
    assert g['80']['inputs']['strength'] == 0.8
    assert g['20']['inputs']['positive_prompt'] == 'pos'
    assert g['30']['inputs']['steps'] == 12 and g['30']['inputs']['seed'] == 3
    assert 'context_options' not in g['30']['inputs']
    assert '65' not in g


def test_context_windows_add_the_options_node_and_wire_it_into_the_sampler(tmp_path):
    masks, controls = _plans(tmp_path)
    g = build_vace_graph(
        StubComfy(),
        'still.png',
        masks,
        controls,
        (832, 480),
        'pos',
        'neg',
        context_windows=True,
        fuse_method='pyramid',
        out_dir=str(tmp_path),
    )
    assert g['30']['inputs']['context_options'] == ['65', 0]
    assert g['65']['inputs']['fuse_method'] == 'pyramid'


def test_the_set_embed_in_a_whole_graph_copies_the_subject_embeds_ref_seat(tmp_path):
    masks, controls = _plans(tmp_path)
    plate = _png(tmp_path / 'plate.png')
    lines = []
    g = build_vace_graph(
        StubComfy(),
        'still.png',
        masks,
        controls,
        (832, 480),
        'pos',
        'neg',
        set_plate_path=plate,
        out_dir=str(tmp_path),
        log_fn=lines.append,
    )
    assert g is not None
    assert g['59']['inputs']['ref_images'] == ['10', 0]
    assert g['60']['inputs']['prev_vace_embeds'] == ['59', 0]
    assert not lines or all('ABORT' not in ln for ln in lines)
