# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers extracted from `setup_flux_pipes`.

`setup_flux_pipes` was 390 lines of "get FLUX, its LoRA, its ControlNet and its
worker onto the card" in one frame, so none of it had ever run without a GPU.
The blocks are now `stages_37_54_flux_setup_load`, and the ones below take a
plain stand-in context instead of the stage's: the LoRA key rewrite and the
style ladder are pure, and the ControlNet resolution, the worker claim and the
gate publication only need the handles the context carries.

No GPU, no network, no diffusers: `gui_state`'s two module-level caches are the
only global state involved and every test restores them.
"""

from types import SimpleNamespace

import pytest

from zyg_workflows import gui_state
from zyg_workflows.pipeline_config import _STYLE_LORA_CONFIG
from zyg_workflows.scholarly import (
    stages_37_54_flux_setup as setup,
    stages_37_54_flux_setup_load as load,
)


@pytest.fixture
def ctx():
    """A stand-in for the stage context, recording every log line in order."""
    lines: list[tuple] = []
    return SimpleNamespace(
        lines=lines,
        _log=lambda level, stage, msg: lines.append((level, msg)),
        _debug=lambda stage, msg, level='DEBUG': lines.append((level, msg)),
        _sch_fw=None,
        _sch_backend=None,
        _fw_claimed_start=False,
        visual_style='cinematic',
    )


@pytest.fixture(autouse=True)
def _restore_gui_state_caches():
    """`gui_state`'s two FLUX caches are module-level; put them back afterwards."""
    flux, cn = gui_state._FLUX_PIPELINE_CACHE, gui_state._CN_PIPE_CACHE
    yield
    gui_state._FLUX_PIPELINE_CACHE, gui_state._CN_PIPE_CACHE = flux, cn


# ── normalize_lora_keys ──────────────────────────────────────────────────


def test_simpletuner_lora_keys_are_rewritten_to_the_diffusers_convention():
    """`.lora.down.` → `.lora_A.` and `.lora.up.` → `.lora_B.`, values untouched."""
    tensor_down, tensor_up = object(), object()
    raw = {
        'transformer.blocks.0.attn.to_q.lora.down.weight': tensor_down,
        'transformer.blocks.0.attn.to_q.lora.up.weight': tensor_up,
    }

    rewritten = load.normalize_lora_keys(raw)

    assert rewritten == {
        'transformer.blocks.0.attn.to_q.lora_A.weight': tensor_down,
        'transformer.blocks.0.attn.to_q.lora_B.weight': tensor_up,
    }
    assert rewritten['transformer.blocks.0.attn.to_q.lora_A.weight'] is tensor_down


def test_a_key_already_in_the_diffusers_convention_is_left_alone():
    """The rewrite is idempotent, which is why both dir branches may call it."""
    already = {'transformer.x.lora_A.weight': 1, 'transformer.x.lora_B.weight': 2}

    assert load.normalize_lora_keys(already) == already
    assert load.normalize_lora_keys(load.normalize_lora_keys(already)) == already
    assert load.normalize_lora_keys({}) == {}


def test_both_substitutions_apply_to_one_key():
    """A key naming both halves is rewritten in both places, left to right."""
    rewritten = load.normalize_lora_keys({'a.lora.down.b.lora.up.c': 7})

    assert rewritten == {'a.lora_A.b.lora_B.c': 7}


# ── style_lora_config ────────────────────────────────────────────────────


def test_a_known_visual_style_gets_its_own_lora_configuration():
    """`style_lora_config` is the `_STYLE_LORA_CONFIG` lookup, by identity."""
    for style in ('cinematic', 'anime', 'disney'):
        assert load.style_lora_config(style) is _STYLE_LORA_CONFIG[style]


def test_an_unknown_visual_style_falls_back_to_cinematic():
    """This default is what keeps a typo in the style from crashing the load."""
    assert load.style_lora_config('no-such-style') is _STYLE_LORA_CONFIG['cinematic']
    assert load.style_lora_config('') is _STYLE_LORA_CONFIG['cinematic']
    assert load.style_lora_config(None) is _STYLE_LORA_CONFIG['cinematic']


def test_every_style_configuration_carries_the_claude_hint_the_load_logs():
    """`load_style_lora` ends on `_sch_vscfg['claude_hint']`, so it must be there."""
    for style in _STYLE_LORA_CONFIG:
        assert load.style_lora_config(style)['claude_hint']


# ── teardown_stale_controlnet ────────────────────────────────────────────


def test_an_empty_controlnet_cache_means_the_teardown_does_nothing(ctx):
    """Nothing is logged and `torch` is never touched when there is no pipeline."""
    gui_state._CN_PIPE_CACHE = None
    torch_that_must_not_be_used = SimpleNamespace()

    load.teardown_stale_controlnet(ctx, torch_that_must_not_be_used)

    assert ctx.lines == []


def test_a_stale_controlnet_pipeline_is_dropped_and_the_vram_reported(ctx):
    """The cache is cleared, CUDA is emptied and the free VRAM is logged."""
    gui_state._CN_PIPE_CACHE = object()
    emptied = []
    torch_flux = SimpleNamespace(
        cuda=SimpleNamespace(
            empty_cache=lambda: emptied.append(True),
            mem_get_info=lambda _i: (17 * 1024**3, 48 * 1024**3),
        )
    )

    load.teardown_stale_controlnet(ctx, torch_flux)

    assert gui_state._CN_PIPE_CACHE is None
    assert emptied == [True]
    assert ('INFO', 'ControlNet torn down before FLUX load — 17.0 GB VRAM free') in ctx.lines


# ── resolve_controlnet_pipe ──────────────────────────────────────────────


def test_no_controlnet_anywhere_resolves_to_no_pipe_at_all(ctx):
    """`(None, None)` is "every shot uses base FLUX", and it is only a debug line."""
    gui_state._CN_PIPE_CACHE = None

    assert load.resolve_controlnet_pipe(ctx, sch_fw_active=False) == (None, None)
    assert ('DEBUG', 'ControlNet not available — using base FLUX for all shots') in ctx.lines


def test_a_cached_controlnet_pipe_is_returned_with_the_service_module(ctx):
    """On a cache hit the pipe carries over and `controlnet_service` comes with it."""
    pipe = object()
    gui_state._CN_PIPE_CACHE = pipe

    cns, cn_pipe = load.resolve_controlnet_pipe(ctx, sch_fw_active=False)

    assert cn_pipe is pipe
    assert cns is not None and hasattr(cns, 'teardown')
    assert ('INFO', 'ControlNet pose conditioning active — anatomy shots guided by pose skeleton') in ctx.lines


def test_an_active_flux_worker_owns_the_controlnet_pipe_not_the_cache(ctx):
    """When the worker holds the pipes, its `get_cn_pipe()` wins over `gui_state`."""
    worker_pipe, cached_pipe = object(), object()
    gui_state._CN_PIPE_CACHE = cached_pipe
    ctx._sch_fw = SimpleNamespace(get_cn_pipe=lambda: worker_pipe)

    _cns, cn_pipe = load.resolve_controlnet_pipe(ctx, sch_fw_active=True)

    assert cn_pipe is worker_pipe


# ── claim_flux_worker ────────────────────────────────────────────────────


def test_without_a_flux_worker_the_pipe_and_the_flag_pass_straight_through(ctx):
    """No worker configured: nothing is claimed, nothing is logged, nothing moves."""
    pipe = object()
    fs = SimpleNamespace(_sch_fw_active=False)
    ctx._sch_fw = None

    assert load.claim_flux_worker(fs, ctx, pipe, sch_fw_active=False) == (pipe, False)
    assert ctx.lines == []
    assert fs._sch_fw_active is False


def test_the_gpu_lock_moves_with_the_flux_ownership(ctx):
    """The transfer sets `_sch_fw_active` and clears `ctx._sch_gpu_lock_held`.

    Releasing a lock the FluxWorker now owns is the one staleness here that
    would be a real bug, which is why the flag is cleared in this frame.
    """
    loaded_pipe, worker_pipe = object(), object()
    completed: list[tuple] = []
    fs = SimpleNamespace(_sch_fw_active=False)
    ctx._fw_claimed_start = True
    ctx._sch_gpu_lock_held = True
    ctx._sch_fw = SimpleNamespace(
        complete_start=lambda pipe, cn, teardown, log_fn: completed.append((pipe, cn, teardown)),
        acquire_pipe_slot=lambda timeout: (worker_pipe, None),
    )
    gui_state._CN_PIPE_CACHE = None

    pipe, active = load.claim_flux_worker(fs, ctx, loaded_pipe, sch_fw_active=False)

    assert completed and completed[0][0] is loaded_pipe
    assert callable(completed[0][2])  # the no-argument release the worker calls
    assert active is True and fs._sch_fw_active is True
    assert ctx._sch_gpu_lock_held is False
    # the worker owns the pipe now, so the slot it hands back is what we render with
    assert pipe is worker_pipe


def test_an_already_active_worker_is_not_claimed_twice_only_a_slot_is_taken(ctx):
    """A second Stage 3.5 in one process acquires a slot and transfers nothing."""
    worker_pipe = object()
    fs = SimpleNamespace(_sch_fw_active=True)
    ctx._fw_claimed_start = True
    ctx._sch_fw = SimpleNamespace(
        complete_start=lambda *a, **k: pytest.fail('ownership must not transfer twice'),
        acquire_pipe_slot=lambda timeout: (worker_pipe, None),
    )

    pipe, active = load.claim_flux_worker(fs, ctx, object(), sch_fw_active=True)

    assert (pipe, active) == (worker_pipe, True)
    assert ctx.lines == []


# ── setup_gates ──────────────────────────────────────────────────────────


def test_the_two_qa_passes_are_published_before_the_gate_state_is_set(ctx, monkeypatch):
    """The gates close over `fs` and `ctx`, and `init_gate_state` runs last.

    `init_gate_state` reads a dozen more context fields and is stubbed here;
    what this proves is `setup_gates`' own contract — the two closures are on
    `ctx`, they take no arguments, and the gate fields are set after them.
    """
    fs = SimpleNamespace()
    order: list[str] = []
    monkeypatch.setattr(
        setup._flux_state,
        'init_gate_state',
        lambda seen_fs, seen_ctx: order.append('gates') or None,
    )

    setup.setup_gates(fs, ctx)

    assert order == ['gates']
    assert ctx._sch_typography_pass.__code__.co_argcount == 0
    assert ctx._sch_hand_qc_pass.__code__.co_argcount == 0
    # each closure carries the pair it was built with, so it still works later
    assert ctx._sch_typography_pass.__closure__ is not None
    captured = [cell.cell_contents for cell in ctx._sch_typography_pass.__closure__]
    assert any(held is fs for held in captured)
    assert any(held is ctx for held in captured)
