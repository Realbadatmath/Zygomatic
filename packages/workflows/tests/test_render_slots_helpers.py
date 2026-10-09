#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers extracted from ``char_state_service._render_char_preview_slots``.

The stage-1d preview renderer was a 336-line def, so none of the decisions inside it had
ever been exercised without ComfyUI: the fail-closed refusal when trained LoRA weights
exist but did not resolve, the per-slot conditioning deep copy, the best-of-N seed budget,
the early-exit result shape and the front-preview warnings. The 2026-10 split moved each
into ``render_slots_stages.py``; every test below calls one with plain dicts. Nothing here
starts ComfyUI, loads a model or touches the network — the one stage that renders
(``generate_slot_image``) is exercised against a stub backend, which is how its contract
with ``render_slot`` gets pinned.
"""

from __future__ import annotations

import os

import pytest

import zyg_workflows
from zyg_workflows.char_state_service import render_slots_stages as RS
from zyg_workflows.pipeline_config import (
    _CHAR_DRIFT_ANIMATED,
    _CHAR_DRIFT_MIN,
)


def _stub_sibling(monkeypatch, name: str, **members):
    """Put a stub in place of a ``zyg_workflows`` submodule for one test.

    The stages reach their siblings with ``from zyg_workflows import x``, which resolves
    through the PACKAGE ATTRIBUTE, not sys.modules — so a sys.modules stub alone is
    ignored once the real module has been imported. Both are set; monkeypatch undoes them.
    """
    import sys
    import types

    stub = types.ModuleType('zyg_workflows.' + name)
    for key, value in members.items():
        setattr(stub, key, value)
    monkeypatch.setitem(sys.modules, 'zyg_workflows.' + name, stub)
    monkeypatch.setattr(zyg_workflows, name, stub, raising=False)
    return stub


def _run(**kw) -> RS.SlotRun:
    """A SlotRun with an inert log, overridden by whatever the test cares about."""
    fields = dict(
        char_id='abcdef0123',
        dataset_dir='/ds',
        pkg={'conditioning': {}},
        params={},
        info={},
        mf='sdxl',
        blender_ds=False,
        front_slot='front',
        render_lc='photorealistic',
        slot_restyle='',
        base_seed=1000,
        log_fn=lambda _m: None,
    )
    fields.update(kw)
    return RS.SlotRun(**fields)


# ── the early-exit result ────────────────────────────────────────────────────


def test_a_preview_already_on_disk_is_a_skip_that_still_passes_quality():
    out = RS.early_preview_result('flux', skipped=True, error=None, warning='', quality_ok=True)
    assert out['skipped'] is True
    assert out['rendered'] == []
    assert out['error'] is None
    assert out['backend'] == 'flux'
    assert out['preview_quality_ok'] is True
    assert out['lora_used'] is False


def test_comfy_being_unavailable_is_not_a_skip_and_carries_the_error():
    out = RS.early_preview_result(
        'sdxl',
        skipped=False,
        error='comfy_unavailable',
        warning='ComfyUI unavailable',
        quality_ok=False,
    )
    assert out['skipped'] is False
    assert out['error'] == 'comfy_unavailable'
    assert out['preview_warning'] == 'ComfyUI unavailable'
    assert out['preview_quality_ok'] is False


def test_both_early_results_have_the_same_shape_a_real_run_returns():
    skipped = RS.early_preview_result('sdxl', skipped=True, error=None, warning='', quality_ok=True)
    failed = RS.early_preview_result('sdxl', skipped=False, error='e', warning='w', quality_ok=False)
    assert sorted(skipped) == sorted(failed)
    assert set(skipped) == {
        'rendered',
        'skipped',
        'lora_used',
        'error',
        'backend',
        'preview_quality_ok',
        'preview_warning',
        'backends',
        'slot_meta',
    }


# ── the checkpoint label and the render style ────────────────────────────────


def test_the_checkpoint_label_names_the_checkpoint_that_will_run():
    assert RS.preview_checkpoint_label('flux', True) == 'hybrid SDXL front + FLUX face'
    assert RS.preview_checkpoint_label('sdxl', True) == 'hybrid SDXL front + FLUX face'
    assert RS.preview_checkpoint_label('sdxl', False) == 'SDXL 1.0 base'
    assert RS.preview_checkpoint_label('flux', False) == 'FLUX'


def test_a_restyle_char_renders_as_restyle_on_sdxl_only(monkeypatch):
    monkeypatch.setattr(RS, '_char_restyle_profile', lambda p, i: {'restyle': 'arcane'})
    monkeypatch.setattr(RS, '_char_render_style', lambda p, i: 'photorealistic')
    assert RS.resolve_render_style('sdxl', {}, {}) == 'restyle'
    # the photoreal FLUX twin leg must stay photoreal — never arcane-ify it
    assert RS.resolve_render_style('flux', {}, {}) == 'photorealistic'


def test_a_plain_char_keeps_the_bible_render_style(monkeypatch):
    monkeypatch.setattr(RS, '_char_restyle_profile', lambda p, i: None)
    monkeypatch.setattr(RS, '_char_render_style', lambda p, i: 'animated')
    assert RS.resolve_render_style('sdxl', {}, {}) == 'animated'


# ── the run-wide conditioning state ─────────────────────────────────────────


def test_the_conditioning_state_turns_instantid_off_on_the_shared_package(monkeypatch):
    monkeypatch.setattr(RS, '_char_effective_hybrid_preview', lambda *a, **kw: False)
    monkeypatch.setattr(RS, '_char_preview_slot_lora_path', lambda *a, **kw: None)
    monkeypatch.setattr(RS, '_char_is_blender_dataset', lambda i, j: True)
    pkg = {'conditioning': {'instantid_enabled': True}}
    state = RS.preview_conditioning_state('c1', {}, {'package': pkg}, '/ds', 'sdxl', {})
    assert state['pkg'] is pkg
    assert pkg['conditioning']['instantid_enabled'] is False
    assert state['hybrid'] is False
    assert state['has_lora'] is False
    assert state['blender_ds'] is True
    assert state['label'] == 'SDXL 1.0 base'


def test_a_hybrid_flux_run_counts_an_sdxl_adapter_as_a_lora(monkeypatch):
    monkeypatch.setattr(RS, '_char_effective_hybrid_preview', lambda *a, **kw: True)
    monkeypatch.setattr(RS, '_char_is_blender_dataset', lambda i, j: False)
    monkeypatch.setattr(
        RS,
        '_char_preview_slot_lora_path',
        lambda cond, family, char_id, ds: '/w/sdxl.safetensors' if family == 'sdxl' else None,
    )
    state = RS.preview_conditioning_state('c1', {}, {'package': {}}, '/ds', 'flux', {})
    assert state['hybrid'] is True
    assert state['has_lora'] is True
    assert state['label'] == 'hybrid SDXL front + FLUX face'


def test_a_missing_package_still_yields_a_usable_state(monkeypatch):
    monkeypatch.setattr(RS, '_char_effective_hybrid_preview', lambda *a, **kw: False)
    monkeypatch.setattr(RS, '_char_preview_slot_lora_path', lambda *a, **kw: None)
    monkeypatch.setattr(RS, '_char_is_blender_dataset', lambda i, j: False)
    state = RS.preview_conditioning_state('c1', {}, {}, '/ds', 'sdxl', {})
    assert state['pkg']['conditioning']['instantid_enabled'] is False


# ── the fail-closed slot refusals ───────────────────────────────────────────


def test_existing_but_unresolved_lora_weights_refuse_the_slot(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(RS, '_preview_env_on', lambda name: True)
    monkeypatch.setattr(RS, '_char_family_lora_weights_exist', lambda c, d, f: True)
    reason = RS.slot_block_reason(
        'abcdef0123',
        '/ds',
        pslot='front',
        slot_mf='sdxl',
        has_lora_slot=False,
        ref_image='/ds/ref.png',
        log_fn=lines.append,
    )
    assert reason == 'lora_unresolved'
    assert 'refusing to render abcdef01 without its adapter' in lines[0]
    assert 'SDXL LoRA weights exist on disk' in lines[0]


def test_an_untrained_char_keeps_the_legitimate_reference_fallback(monkeypatch):
    monkeypatch.setattr(RS, '_preview_env_on', lambda name: True)
    monkeypatch.setattr(RS, '_char_family_lora_weights_exist', lambda c, d, f: False)
    reason = RS.slot_block_reason(
        'abcdef0123',
        '/ds',
        pslot='front',
        slot_mf='flux',
        has_lora_slot=False,
        ref_image='/ds/ref.png',
        log_fn=lambda _m: None,
    )
    assert reason == ''


def test_no_lora_and_no_reference_is_refused_whatever_the_env_says(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(RS, '_preview_env_on', lambda name: False)
    monkeypatch.setattr(RS, '_char_family_lora_weights_exist', lambda c, d, f: True)
    reason = RS.slot_block_reason(
        'abcdef0123',
        '/ds',
        pslot='face',
        slot_mf='flux',
        has_lora_slot=False,
        ref_image=None,
        log_fn=lines.append,
    )
    assert reason == 'no_reference_image'
    assert lines == ['Preview slot face: no reference and no LoRA (flux)']


def test_a_lora_locked_slot_is_never_blocked(monkeypatch):
    monkeypatch.setattr(RS, '_preview_env_on', lambda name: True)
    monkeypatch.setattr(RS, '_char_family_lora_weights_exist', lambda c, d, f: True)
    assert (
        RS.slot_block_reason(
            'abcdef0123',
            '/ds',
            pslot='front',
            slot_mf='sdxl',
            has_lora_slot=True,
            ref_image=None,
            log_fn=lambda _m: None,
        )
        == ''
    )


# ── the per-slot conditioning deep copy ─────────────────────────────────────


def test_slot_conditioning_never_mutates_the_shared_package(monkeypatch):
    monkeypatch.delenv('ZYG_PREVIEW_HAND_DETAIL_DENOISE', raising=False)
    pkg = {'conditioning': {'instantid_enabled': True}, 'trigger_token': 'tok'}
    slot = RS.slot_conditioning(pkg, slot_mf='sdxl', slot_lora='/w/a.safetensors', render_lc='animated', params={})
    assert slot is not pkg
    assert pkg['conditioning'] == {'instantid_enabled': True}
    assert slot['conditioning']['instantid_enabled'] is False
    assert slot['trigger_token'] == 'tok'


def test_sdxl_gets_the_hand_detail_pass_and_flux_does_not(monkeypatch):
    monkeypatch.setenv('ZYG_PREVIEW_HAND_DETAIL_DENOISE', '0.5')
    sdxl = RS.slot_conditioning({}, slot_mf='sdxl', slot_lora='/w/a', render_lc='animated', params={})
    assert sdxl['conditioning']['hand_detail_pass'] is True
    assert sdxl['conditioning']['hand_detail_strength'] == 0.5
    assert sdxl['conditioning']['sdxl_lora_path'] == '/w/a'
    assert sdxl['conditioning']['lora_path'] == '/w/a'
    flux = RS.slot_conditioning({}, slot_mf='flux', slot_lora='/w/b', render_lc='animated', params={})
    assert flux['conditioning']['hand_detail_pass'] is False
    assert flux['conditioning']['lora_path'] == '/w/b'
    assert 'sdxl_lora_path' not in flux['conditioning']


def test_an_sdxl_slot_beside_a_flux_adapter_leaves_the_generic_lora_path_alone():
    pkg = {'conditioning': {'flux_lora_path': '/w/flux', 'lora_path': '/w/flux'}}
    slot = RS.slot_conditioning(pkg, slot_mf='sdxl', slot_lora='/w/sdxl', render_lc='animated', params={})
    assert slot['conditioning']['sdxl_lora_path'] == '/w/sdxl'
    assert slot['conditioning']['lora_path'] == '/w/flux'


def test_only_a_photorealistic_render_gets_the_skin_pore_pass(monkeypatch):
    monkeypatch.setenv('ZYG_PREVIEW_FACE_PORE_DENOISE_PHOTOREAL', '0.4')
    photo = RS.slot_conditioning({}, slot_mf='sdxl', slot_lora=None, render_lc='photorealistic', params={})
    assert photo['conditioning']['skin_pore_pass'] is True
    assert photo['conditioning']['face_detail_strength'] == 0.4
    arcane = RS.slot_conditioning({}, slot_mf='sdxl', slot_lora=None, render_lc='restyle', params={})
    assert 'skin_pore_pass' not in arcane['conditioning']


def test_a_requested_smile_is_locked_with_its_face_detail_wildcard(monkeypatch):
    _stub_sibling(
        monkeypatch,
        'character_bible_service',
        wants_visible_smile=lambda params: bool(params.get('smile')),
        face_detail_wildcard_for_params=lambda params: 'a warm smile',
    )
    smiling = RS.slot_conditioning({}, slot_mf='flux', slot_lora=None, render_lc='animated', params={'smile': True})
    assert smiling['conditioning']['smile_requested'] is True
    assert smiling['conditioning']['smile_locked'] is True
    assert smiling['conditioning']['face_detail_wildcard'] == 'a warm smile'

    straight = RS.slot_conditioning({}, slot_mf='flux', slot_lora=None, render_lc='animated', params={})
    assert 'smile_requested' not in straight['conditioning']


def test_a_bible_that_will_not_load_leaves_the_conditioning_without_a_smile(monkeypatch):
    def _boom(params):
        raise RuntimeError('no bible')

    _stub_sibling(monkeypatch, 'character_bible_service', wants_visible_smile=_boom)
    slot = RS.slot_conditioning({}, slot_mf='flux', slot_lora=None, render_lc='animated', params={'smile': True})
    assert 'smile_requested' not in slot['conditioning']


# ── the seed budget ─────────────────────────────────────────────────────────


def test_only_a_lora_locked_slot_earns_a_best_of_n():
    assert RS.seed_candidate_count(has_lora_slot=False, slot_mf='sdxl', pslot='front', front_slot='front') == 1
    assert RS.seed_candidate_count(has_lora_slot=False, slot_mf='flux', pslot='front', front_slot='front') == 1


def test_the_sdxl_front_slot_gets_the_full_budget_and_a_face_slot_a_smaller_one(monkeypatch):
    monkeypatch.setenv('ZYG_PREVIEW_SEED_CANDIDATES_SDXL', '5')
    monkeypatch.setenv('ZYG_PREVIEW_FACE_SEED_CANDIDATES_SDXL', '2')
    n = RS.seed_candidate_count(has_lora_slot=True, slot_mf='sdxl', pslot='front', front_slot='front')
    assert n == 5
    face = RS.seed_candidate_count(has_lora_slot=True, slot_mf='sdxl', pslot='face_closeup', front_slot='front')
    assert face == 2
    other = RS.seed_candidate_count(has_lora_slot=True, slot_mf='sdxl', pslot='three_quarter', front_slot='front')
    assert other == 1


def test_the_flux_budget_comes_from_the_pipeline_config():
    assert (
        RS.seed_candidate_count(
            has_lora_slot=True,
            slot_mf='flux',
            pslot='front',
            front_slot='front',
        )
        == RS._PREVIEW_SEED_CANDIDATES
    )
    assert (
        RS.seed_candidate_count(
            has_lora_slot=True,
            slot_mf='flux',
            pslot='face',
            front_slot='front',
        )
        == RS._PREVIEW_FACE_SEED_CANDIDATES
    )


def test_a_seed_budget_is_never_below_one(monkeypatch):
    monkeypatch.setenv('ZYG_PREVIEW_SEED_CANDIDATES_SDXL', '0')
    assert RS.seed_candidate_count(has_lora_slot=True, slot_mf='sdxl', pslot='front', front_slot='front') == 1


# ── rendering one slot ──────────────────────────────────────────────────────


class _Backend:
    """A stand-in for comfy_generation_service: records the call, renders nothing."""

    def __init__(self, result=(True, 'character_locked_txt2img', True, 0.82)):
        self.result = result
        self.calls: list[dict] = []

    def generate_character_preview_still(self, out_png, prompt, **kw):
        self.calls.append(dict(kw, out_png=out_png, prompt=prompt))
        return self.result


def test_a_single_seed_slot_goes_straight_to_the_backend():
    backend = _Backend()
    out = RS.generate_slot_image(
        backend,
        out_png='/ds/front.png',
        prompt='  a portrait  ',
        width=896,
        height=1152,
        seed=7,
        n_cand=1,
        slot_pkg={},
        char_id='c1',
        ref_image=None,
        slot_mf='sdxl',
        blender_ds=False,
        mf='sdxl',
        params={},
        info={},
        pslot='front',
        front_slot='front',
        want_smile=False,
        log_fn=lambda _m: None,
    )
    assert out == (True, 'character_locked_txt2img', True, 0.82)
    assert backend.calls[0]['prompt'] == 'a portrait', 'the prompt is stripped'
    assert backend.calls[0]['seed'] == 7
    assert backend.calls[0]['width'] == 896


def test_a_seed_budget_routes_through_best_of_n_and_drops_the_chosen_seed(monkeypatch):
    seen: dict = {}

    def _best_of_n(**kw):
        seen.update(kw)
        return True, 'character_locked_txt2img', False, 0.31, 1234

    monkeypatch.setattr(RS, '_generate_preview_slot_best_of_n', _best_of_n)
    monkeypatch.setattr(RS, '_char_restyle_profile', lambda p, i: None)
    monkeypatch.setattr(RS, '_char_is_photoreal_style', lambda p, i: True)
    out = RS.generate_slot_image(
        _Backend(),
        out_png='/ds/front.png',
        prompt='a portrait',
        width=896,
        height=1152,
        seed=7,
        n_cand=5,
        slot_pkg={},
        char_id='c1',
        ref_image=None,
        slot_mf='sdxl',
        blender_ds=False,
        mf='sdxl',
        params={},
        info={},
        pslot='front',
        front_slot='front',
        want_smile=True,
        log_fn=lambda _m: None,
    )
    assert out == (True, 'character_locked_txt2img', False, 0.31)
    assert seen['n_candidates'] == 5
    assert seen['base_seed'] == 7
    assert seen['check_hands'] is True, 'only the sdxl front slot checks hands'
    assert seen['want_smile'] is True
    assert seen['want_photoreal'] is True


def test_a_restyle_front_render_is_never_rewarded_for_being_photoreal(monkeypatch):
    seen: dict = {}

    def _best_of_n(**kw):
        seen.update(kw)
        return True, 'character_locked_txt2img', True, 0.9, 1

    monkeypatch.setattr(RS, '_generate_preview_slot_best_of_n', _best_of_n)
    monkeypatch.setattr(RS, '_char_restyle_profile', lambda p, i: {'restyle': 'arcane'})
    monkeypatch.setattr(RS, '_char_is_photoreal_style', lambda p, i: True)
    RS.generate_slot_image(
        _Backend(),
        out_png='/ds/front.png',
        prompt='a portrait',
        width=896,
        height=1152,
        seed=1,
        n_cand=3,
        slot_pkg={},
        char_id='c1',
        ref_image=None,
        slot_mf='sdxl',
        blender_ds=False,
        mf='sdxl',
        params={},
        info={},
        pslot='front',
        front_slot='front',
        want_smile=False,
        log_fn=lambda _m: None,
    )
    assert seen['want_photoreal'] is False
    assert seen['check_hands'] is True


def test_a_face_slot_does_not_check_hands(monkeypatch):
    seen: dict = {}

    def _best_of_n(**kw):
        seen.update(kw)
        return True, 'b', True, 0.9, 1

    monkeypatch.setattr(RS, '_generate_preview_slot_best_of_n', _best_of_n)
    monkeypatch.setattr(RS, '_char_restyle_profile', lambda p, i: None)
    monkeypatch.setattr(RS, '_char_is_photoreal_style', lambda p, i: False)
    RS.generate_slot_image(
        _Backend(),
        out_png='/ds/face.png',
        prompt='a face',
        width=768,
        height=768,
        seed=1,
        n_cand=2,
        slot_pkg={},
        char_id='c1',
        ref_image=None,
        slot_mf='sdxl',
        blender_ds=False,
        mf='sdxl',
        params={},
        info={},
        pslot='face_closeup',
        front_slot='front',
        want_smile=False,
        log_fn=lambda _m: None,
    )
    assert seen['check_hands'] is False


# ── the sidecars beside a rendered PNG ──────────────────────────────────────


def test_a_locked_render_writes_the_prompt_and_a_truthful_provenance_sidecar(monkeypatch, tmp_path):
    written: dict = {}
    monkeypatch.setattr(RS, '_write_preview_provenance', lambda png, **kw: written.update(kw, png=png))
    out_png = str(tmp_path / 'front.png')
    RS.write_slot_sidecars(
        out_png,
        pslot='front',
        slot_mf='sdxl',
        prompt='  a portrait  ',
        backend='character_locked_txt2img',
        drift_ok=True,
        drift_sc=0.82,
        has_lora_slot=True,
        slot_lora='/w/a.safetensors',
        pkg={'trigger_token': 'tok'},
        info={},
        char_id='c1',
        mf='sdxl',
        slot_restyle='arcane',
        ref_image='/ds/ref.png',
        log_fn=lambda _m: None,
    )
    with open(str(tmp_path / 'front.txt'), encoding='utf-8') as fh:
        assert fh.read() == 'a portrait\n'
    assert written['lora_used'] is True
    assert written['lora_path'] == '/w/a.safetensors'
    assert written['trigger_token'] == 'tok'
    assert written['restyle'] == 'arcane'
    assert written['extra']['tier'] == 'locked'
    assert written['extra']['renderer'] == 'comfy_slots'
    assert written['extra']['drift_score'] == 0.82


def test_an_img2img_fallback_is_not_filed_as_a_lora_render(monkeypatch, tmp_path):
    written: dict = {}
    monkeypatch.setattr(RS, '_write_preview_provenance', lambda png, **kw: written.update(kw))
    RS.write_slot_sidecars(
        str(tmp_path / 'front.png'),
        pslot='front',
        slot_mf='sdxl',
        prompt='a portrait',
        backend='img2img_reference',
        drift_ok=False,
        drift_sc=None,
        has_lora_slot=True,
        slot_lora='/w/a.safetensors',
        pkg={},
        info={'trigger_token': 'tok2'},
        char_id='c1',
        mf='sdxl',
        slot_restyle='',
        ref_image=None,
        log_fn=lambda _m: None,
    )
    assert written['lora_used'] is False, 'an adapter that did not lock is not a LoRA render'
    assert written['extra']['tier'] == 'img2img'
    assert written['extra']['drift_score'] == 0.0
    assert written['extra']['reference_image'] is None
    assert written['trigger_token'] == 'tok2'


# ── one slot, end to end over the stubbed stages ────────────────────────────


def _stub_slot_stages(monkeypatch, *, ref='/ds/ref.png', lora='/w/a.safetensors', isfile=True):
    """Stub everything render_slot reaches outside render_slots_stages itself.

    The seed budget is pinned to one candidate so the single-seed leg runs against the
    stub backend; the best-of-N leg has its own tests above.
    """
    monkeypatch.setenv('ZYG_PREVIEW_SEED_CANDIDATES_SDXL', '1')
    monkeypatch.setenv('ZYG_PREVIEW_FACE_SEED_CANDIDATES_SDXL', '1')
    monkeypatch.setattr(RS, '_pick_char_preview_reference_for_slot', lambda d, i, s: ref)
    monkeypatch.setattr(RS, '_char_preview_slot_lora_path', lambda *a, **kw: lora)
    monkeypatch.setattr(RS, '_char_family_lora_weights_exist', lambda c, d, f: False)
    monkeypatch.setattr(RS, '_preview_env_on', lambda name: False)
    monkeypatch.setattr(os.path, 'isfile', lambda p: isfile)
    monkeypatch.setattr(RS, '_write_preview_provenance', lambda png, **kw: None)


def test_a_rendered_slot_lands_in_rendered_backends_and_slot_meta(monkeypatch, tmp_path):
    _stub_slot_stages(monkeypatch)
    lines: list[str] = []
    rendered: list[str] = []
    backends: list[str] = []
    slot_meta: dict = {}
    err = RS.render_slot(
        _run(dataset_dir=str(tmp_path), log_fn=lines.append),
        _Backend(),
        idx=2,
        slot=('front', 'a portrait', 896, 1152, 'sdxl'),
        rendered=rendered,
        backends=backends,
        slot_meta=slot_meta,
    )
    assert err == ''
    assert rendered == [os.path.join(str(tmp_path), 'front.png')]
    assert backends == ['character_locked_txt2img']
    assert slot_meta['front']['tier'] == 'locked'
    assert slot_meta['front']['drift_score'] == 0.82
    assert lines[-1] == 'Saved front.png via character_locked_txt2img (drift=0.820)'


def test_a_backend_that_reports_failure_becomes_the_runs_last_error(monkeypatch, tmp_path):
    _stub_slot_stages(monkeypatch)
    lines: list[str] = []
    rendered: list[str] = []
    err = RS.render_slot(
        _run(dataset_dir=str(tmp_path), log_fn=lines.append),
        _Backend(result=(False, 'comfy_timeout', False, 0.0)),
        idx=0,
        slot=('front', 'a portrait', 896, 1152, 'sdxl'),
        rendered=rendered,
        backends=[],
        slot_meta={},
    )
    assert err == 'comfy_timeout'
    assert rendered == []
    assert lines[-1] == 'Preview slot front failed (comfy_timeout)'


def test_a_raising_backend_is_caught_and_its_message_truncated(monkeypatch, tmp_path):
    _stub_slot_stages(monkeypatch)

    class _Boom:
        def generate_character_preview_still(self, *a, **kw):
            raise RuntimeError('x' * 500)

    lines: list[str] = []
    err = RS.render_slot(
        _run(dataset_dir=str(tmp_path), log_fn=lines.append),
        _Boom(),
        idx=0,
        slot=('front', 'a portrait', 896, 1152, 'sdxl'),
        rendered=[],
        backends=[],
        slot_meta={},
    )
    assert len(err) == 200
    assert lines[-1].startswith('Preview slot front failed: xxx')


def test_a_blocked_slot_never_reaches_the_backend(monkeypatch, tmp_path):
    _stub_slot_stages(monkeypatch, ref=None, lora=None, isfile=False)
    backend = _Backend()
    err = RS.render_slot(
        _run(dataset_dir=str(tmp_path)),
        backend,
        idx=0,
        slot=('front', 'a portrait', 896, 1152, 'sdxl'),
        rendered=[],
        backends=[],
        slot_meta={},
    )
    assert err == 'no_reference_image'
    assert backend.calls == []


def test_the_slot_seed_is_the_base_seed_offset_by_the_slot_index(monkeypatch, tmp_path):
    _stub_slot_stages(monkeypatch)
    backend = _Backend()
    RS.render_slot(
        _run(dataset_dir=str(tmp_path), base_seed=1000),
        backend,
        idx=3,
        slot=('three_quarter', 'a portrait', 896, 1152, 'sdxl'),
        rendered=[],
        backends=[],
        slot_meta={},
    )
    assert backend.calls[0]['seed'] == 1003


# ── the drift reference ─────────────────────────────────────────────────────


def test_only_a_locked_front_render_becomes_the_drift_reference(monkeypatch, tmp_path):
    registered: list[tuple] = []
    _stub_sibling(
        monkeypatch,
        'consistency_qa_service',
        register_reference=lambda char_id, png, log_fn=None: registered.append((char_id, png)),
    )
    front = tmp_path / 'front.png'
    front.write_bytes(b'x')
    lines: list[str] = []

    RS.register_front_reference(
        'c1',
        [str(front)],
        'front',
        {'front': {'backend': 'character_locked_txt2img'}},
        lines.append,
    )
    assert registered == [('c1', str(front))]
    assert lines == ['Consistency QA: preview registered as drift reference']

    registered.clear()
    RS.register_front_reference(
        'c1',
        [str(front)],
        'front',
        {'front': {'backend': 'img2img_reference'}},
        lambda _m: None,
    )
    assert registered == [], 'an img2img front would make the mannequin the reference'


def test_a_run_that_rendered_nothing_registers_nothing():
    RS.register_front_reference('c1', [], 'front', {}, lambda _m: None)
    RS.register_front_reference('', ['/ds/front.png'], 'front', {}, lambda _m: None)


# ── the front-preview verdict ───────────────────────────────────────────────


def _warn(**kw):
    """preview_warnings over a one-slot run, with the test's own front metadata."""
    fields = dict(
        mf='sdxl',
        params={},
        info={},
        rendered=['/ds/front.png'],
        slot_meta={'front': {'tier': 'locked', 'drift_ok': True, 'drift_score': 0.9}},
        front_slot='front',
        job={},
    )
    fields.update(kw)
    return RS.preview_warnings(
        fields.pop('mf'),
        fields.pop('params'),
        fields.pop('info'),
        **fields,
    )


def test_a_locked_front_render_with_good_drift_passes_without_a_warning():
    ok, warnings = _warn()
    assert ok is True
    assert warnings == []


def test_a_locked_render_with_low_drift_still_passes_but_says_so():
    ok, warnings = _warn(slot_meta={'front': {'tier': 'locked', 'drift_ok': False, 'drift_score': 0.41}})
    assert ok is True, 'drift is reported, never used to fail a locked render'
    assert warnings == [f'Identity drift 0.410 below {_CHAR_DRIFT_MIN:.2f} (locked render OK — review preview)']


def test_an_unknown_drift_is_not_reported_as_drift():
    ok, warnings = _warn(slot_meta={'front': {'tier': 'locked', 'drift_ok': False, 'drift_score': -1.0}})
    assert ok is True
    assert warnings == [
        'Identity NOT verified — no reference embedding for this character (locked render OK — review preview)',
    ]
    assert '-1.000' not in warnings[0]


def test_an_animated_char_is_judged_against_the_relaxed_drift_floor():
    _ok, warnings = _warn(
        params={'render_style': 'animated'},
        slot_meta={'front': {'tier': 'locked', 'drift_ok': False, 'drift_score': 0.41}},
    )
    assert f'below {_CHAR_DRIFT_ANIMATED:.2f}' in warnings[0]
    assert _CHAR_DRIFT_ANIMATED < _CHAR_DRIFT_MIN


def test_a_restyle_char_also_takes_the_relaxed_floor(monkeypatch):
    monkeypatch.setattr(RS, '_char_restyle_profile', lambda p, i: {'restyle': 'arcane'})
    _ok, warnings = _warn(slot_meta={'front': {'tier': 'locked', 'drift_ok': False, 'drift_score': 0.41}})
    assert f'below {_CHAR_DRIFT_ANIMATED:.2f}' in warnings[0]


def test_an_img2img_front_render_does_not_pass_and_names_the_mannequin():
    ok, warnings = _warn(slot_meta={'front': {'tier': 'img2img', 'drift_ok': True, 'drift_score': 0.9}})
    assert ok is False
    assert warnings == [
        'Front preview used img2img fallback (may clone Blender mannequin — re-run with LoRA)',
    ]


def test_an_otherwise_unlocked_front_render_does_not_pass():
    ok, warnings = _warn(slot_meta={'front': {'tier': 'instantid', 'drift_ok': True, 'drift_score': 0.9}})
    assert ok is False
    assert warnings == ['Front preview did not use LoRA-locked txt2img']


def test_a_failed_lora_training_is_named_beside_the_img2img_warning():
    ok, warnings = _warn(
        slot_meta={'front': {'tier': 'img2img', 'drift_ok': True, 'drift_score': 0.9}},
        job={'lora_failed': True},
    )
    assert ok is False
    assert warnings[-1] == 'LoRA training failed; only img2img fallback produced images'
    assert len(warnings) == 2


def test_a_run_that_rendered_nothing_neither_passes_nor_warns():
    ok, warnings = _warn(rendered=[], slot_meta={})
    assert ok is False
    assert warnings == []


def test_the_style_profile_render_style_outranks_the_params():
    _ok, warnings = _warn(
        params={'render_style': 'photorealistic'},
        info={'package': {'style_profile': {'render_style': 'animated'}}},
        slot_meta={'front': {'tier': 'locked', 'drift_ok': False, 'drift_score': 0.41}},
    )
    assert f'below {_CHAR_DRIFT_ANIMATED:.2f}' in warnings[0]


# ── the best-effort stages: a failure is a debug line, never a refusal ──────


def test_a_bible_package_already_present_is_not_reloaded():
    info = {'package': {'conditioning': {}}}
    RS.load_bible_package('c1', info)
    assert info['package'] == {'conditioning': {}}


def test_a_bible_that_loads_fills_the_package(monkeypatch):
    _stub_sibling(
        monkeypatch,
        'character_bible_service',
        load=lambda char_id: {'conditioning': {'from': char_id}},
    )
    info: dict = {}
    RS.load_bible_package('c1', info)
    assert info['package'] == {'conditioning': {'from': 'c1'}}


def test_a_bible_that_raises_leaves_the_package_absent(monkeypatch):
    def _boom(char_id):
        raise RuntimeError('no bible')

    _stub_sibling(monkeypatch, 'character_bible_service', load=_boom)
    info: dict = {}
    RS.load_bible_package('c1', info)
    assert 'package' not in info


def test_a_vram_wait_that_cannot_measure_does_not_stop_the_render(monkeypatch):
    def _boom(**kw):
        raise RuntimeError('no nvml')

    _stub_sibling(monkeypatch, '_comfy_client', wait_for_free_vram_gb=_boom)
    RS.wait_for_preview_vram(lambda _m: None)


def test_the_vram_wait_asks_for_the_preview_budget(monkeypatch):
    seen: dict = {}
    _stub_sibling(monkeypatch, '_comfy_client', wait_for_free_vram_gb=lambda **kw: seen.update(kw))
    RS.wait_for_preview_vram(lambda _m: None)
    assert seen['min_free_gb'] == 10.0
    assert seen['timeout_s'] == 120
    assert seen['try_evict'] is True


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__]))
