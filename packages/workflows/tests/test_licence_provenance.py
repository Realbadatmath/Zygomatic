#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Invariants of the commercial-licence gate.

Built 2026-08-09 when the channel became monetised. Unlike every other gate in
this repo, the defect this one detects is INVISIBLE: a FLUX.1-dev frame and an
Apache-2.0 frame are pixel-plausible twins, so no amount of looking finds it.
That makes these tests the only instrument, which is why they are strict.

    .venv-test/bin/python -m pytest tests/test_licence_provenance.py -q
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import licence_provenance as lp  # noqa: E402
from zyg_workflows import qc_contract as qc  # noqa: E402


# ── the registry actually loaded ────────────────────────────────────────────
def test_registry_loads_and_is_not_empty():
    """A silently-empty registry makes every weight UNKNOWN. That is not a pass,
    but it IS a way to lose the gate's usefulness without noticing."""
    reg = lp.load_registry()
    assert reg['weights'], 'model_licences.json has no weight rules'
    assert reg['families'], 'model_licences.json has no family rules'


def test_every_registry_entry_cites_a_source():
    """The registry rule: an entry exists only when its licence was read at the
    primary source. An uncited entry is a guess wearing a clearance."""
    reg = lp.load_registry()
    for rule in reg['weights']:
        assert rule.get('source'), f'{rule.get("licence")} has no source URL'
    for fam, rec in reg['families'].items():
        assert rec.get('source'), f'family {fam} has no source URL'


# ── the four statuses ───────────────────────────────────────────────────────
def test_flux_dev_is_non_commercial():
    assert lp.classify_weight('flux1-dev.safetensors')['status'] == lp.NON_COMMERCIAL


def test_flux_fill_dev_is_non_commercial():
    """HandFixer's model carries the same BFL non-commercial terms."""
    r = lp.classify_weight('flux1-fill-dev.safetensors')
    assert r['status'] == lp.NON_COMMERCIAL


def test_flux_schnell_is_cleared():
    assert lp.classify_weight('flux1-schnell.safetensors')['status'] == lp.CLEARED


def test_wan_is_cleared():
    r = lp.classify_weight('Wan2_1-T2V-14B_fp8_e4m3fn.safetensors')
    assert r['status'] == lp.CLEARED


def test_minimax_h3_is_territory_excluded_in_the_eu():
    """The whole reason this gate exists: H3 is 'open weights' and still forbidden
    here. Section V.4 covers the OUTPUTS, not just the weights."""
    r = lp.classify_weight('MiniMax-H3-Base.safetensors')
    assert r['status'] == lp.TERRITORY_EXCLUDED


def test_hunyuan_is_territory_excluded_in_the_eu():
    r = lp.classify_weight('hunyuan_video_720p.safetensors')
    assert r['status'] == lp.TERRITORY_EXCLUDED


def test_unregistered_weight_is_unknown_never_cleared():
    """qc_contract rule 1, applied to licences: a weight nobody recorded has not
    been cleared, it has merely not been looked at."""
    r = lp.classify_weight('SomeModelNobodyRecorded.safetensors')
    assert r['status'] == lp.UNKNOWN
    assert r['status'] != lp.CLEARED


def test_territory_is_configurable_and_defaults_to_eu():
    assert lp.TERRITORY == 'EU'


# ── verdict ordering ────────────────────────────────────────────────────────
def test_fail_outranks_unknown():
    """A known violation beats an unread licence — otherwise one unrecorded
    weight could mask a real one behind an UNKNOWN verdict."""
    assert lp._verdict_from([lp.UNKNOWN, lp.NON_COMMERCIAL]) is False


def test_unknown_outranks_pass():
    assert lp._verdict_from([lp.CLEARED, lp.UNKNOWN]) is None


def test_all_cleared_passes():
    assert lp._verdict_from([lp.CLEARED, lp.CLEARED]) is True


def test_licence_exposure_does_not_average():
    """One bad weight in a graph of twenty decides the verdict."""
    assert lp._verdict_from([lp.CLEARED] * 19 + [lp.NON_COMMERCIAL]) is False


def test_empty_statuses_is_unknown_not_pass():
    assert lp._verdict_from([]) is None


# ── LoRA lineage: the part that decides correctness ─────────────────────────
def test_lora_is_charged_with_its_base_licence(tmp_path):
    """A LoRA's own file has no licence — the base it was fine-tuned from does.
    A gate reading only the filename reports green on the exact exposure."""
    char = tmp_path / 'aaaaaaaaaaaa'
    char.mkdir()
    (char / 'training_status_flux.json').write_text(json.dumps({'model_family': 'flux'}))
    weights = char / 'lora-weights-flux'
    weights.mkdir()
    wf = weights / 'pytorch_lora_weights.safetensors'
    wf.write_text('')
    r = lp.classify_weight('pytorch_lora_weights.safetensors', kind='lora', path=str(wf))
    assert r['status'] == lp.NON_COMMERCIAL
    assert r['base_family'] == 'flux'


def test_weights_dir_names_the_family_exactly(tmp_path):
    d = tmp_path / 'c0ffeec0ffee' / 'lora-weights-sdxl'
    d.mkdir(parents=True)
    wf = d / 'pytorch_lora_weights.safetensors'
    wf.write_text('')
    fams, how = lp.lora_base_families('pytorch_lora_weights.safetensors', str(wf))
    assert fams == ['sdxl']
    assert how == 'weights-dir'


def test_dual_family_character_is_ambiguous_and_charged_the_worst(tmp_path):
    """THE bug this gate nearly shipped with. Characters here are trained TWICE —
    photoreal FLUX and animated SDXL twins — and staging copies the weights to
    zygchar_<id>.safetensors, stripping the directory that carried the answer.
    Resolving per-character then picks a twin arbitrarily; picking the clean one
    reports green on a FLUX exposure."""
    root = tmp_path / 'chars'
    char = root / 'abcdefabcdef'
    char.mkdir(parents=True)
    (char / 'training_status_flux.json').write_text(json.dumps({'model_family': 'flux'}))
    (char / 'training_status_sdxl.json').write_text(json.dumps({'model_family': 'sdxl'}))
    old = lp._LORA_OUTPUT_ROOTS[:]
    try:
        lp._LORA_OUTPUT_ROOTS[:] = [str(root)]
        fams, how = lp.lora_base_families('zygchar_abcdefabcdef.safetensors')
        assert set(fams) == {'flux', 'sdxl'}
        assert how == 'charid-ambiguous'
        r = lp.classify_weight('zygchar_abcdefabcdef.safetensors', kind='lora')
        assert r['status'] == lp.NON_COMMERCIAL, 'ambiguous lineage must charge the worst'
    finally:
        lp._LORA_OUTPUT_ROOTS[:] = old


def test_legacy_status_file_loses_to_family_scoped_ones(tmp_path):
    """training_status.json is written by whichever family trained LAST, so it is
    the least authoritative. The trainer's own lookup tries the scoped name first."""
    char = tmp_path / 'bbbbbbbbbbbb'
    char.mkdir()
    (char / 'training_status.json').write_text(json.dumps({'model_family': 'sdxl'}))
    (char / 'training_status_flux.json').write_text(json.dumps({'model_family': 'flux'}))
    recs = lp._status_records(str(char))
    assert [f for f, _ in recs] == ['flux'], 'scoped file must win over legacy'


def test_unresolvable_lora_lineage_is_unknown_not_cleared():
    r = lp.classify_weight('some_third_party_style.safetensors', kind='lora')
    assert r['status'] != lp.CLEARED


def test_char_id_is_not_a_lineage_key():
    """MEASURED FALSE POSITIVE, 2026-08-09: the first cut of this gate resolved
    wan_chars/wan_char_<id> by char id, found the SAME character's flux1-dev image
    LoRA, and charged a Wan video LoRA with a licence those weights never touched
    — FAIL on 40 of 41 captured graphs. One character owns several LoRAs on
    different bases; the name/folder convention is the lineage, not the id."""
    wan = lp.classify_weight('wan_chars/wan_char_0015c8a3f2e3.safetensors', kind='lora')
    assert wan['base_family'] == 'wan'
    assert wan['status'] == lp.CLEARED

    # The bare staged name carries no family (two writers share it), so the same
    # char_id must still resolve through the char-id scan and be charged the worst
    # of that character's legs — never quietly cleared because a Wan leg exists.
    # The scan reads that character's legs from the output roots on disk.
    if not any(os.path.isdir(os.path.join(r, '0015c8a3f2e3')) for r in lp._LORA_OUTPUT_ROOTS):
        pytest.skip("char 0015c8a3f2e3's LoRA legs are not on this box")
    bare = lp.classify_weight('zygchar_0015c8a3f2e3.safetensors', kind='lora')
    assert bare['status'] == lp.NON_COMMERCIAL
    assert bare.get('lineage') in ('charid', 'charid-ambiguous')


def test_lineage_rule_order_keeps_wan_out_of_the_flux_glob():
    """The flux rule matches broadly. If it were listed first, wan_char_* would
    fall into it and every VACE graph would fail again."""
    reg = lp.load_registry()
    fams = [r.get('family') for r in reg['lora_lineage']]
    assert fams.index('wan') < fams.index('flux')
    assert fams.index('sdxl') < fams.index('flux'), 'the _sdxl suffix must win over the broad *_flux/flux_* globs'


def test_family_suffixed_staging_names_resolve_exactly():
    """comfy_generation_service.py:1385 stages zygchar_<cid>_<mf>.safetensors."""
    assert lp.classify_weight('zygchar_c3345deb5bde_flux.safetensors', kind='lora')['base_family'] == 'flux'
    assert lp.classify_weight('zygchar_c3345deb5bde_sdxl.safetensors', kind='lora')['base_family'] == 'sdxl'


def test_bare_zygchar_name_is_not_assumed_to_be_flux():
    """arcane_restyle.py:112 stages the SDXL LoRA as bare zygchar_<id>.safetensors
    while comfy_generation_service stages family-suffixed ones — two writers, one
    filename, no family in it. A blanket zygchar_* -> flux rule charges SDXL
    weights with a non-commercial licence they never touched."""
    reg = lp.load_registry()
    for rule in reg['lora_lineage']:
        if rule.get('family') == 'flux':
            assert 'zygchar_*' not in (rule.get('match') or []), (
                'the bare zygchar_* glob must not be charged to flux by convention'
            )


def test_wan_props_and_antireal_are_cleared():
    for n in ('wan_props/wan_prop_book.safetensors', 'wan_antireal/antireal.safetensors'):
        assert lp.classify_weight(n, kind='lora')['status'] == lp.CLEARED


# ── the gate over a whole graph ─────────────────────────────────────────────
FLUX_GRAPH = {
    '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'flux1-dev.safetensors'}},
}
CLEAN_GRAPH = {
    '1': {'class_type': 'WanVideoModelLoader', 'inputs': {'model': 'Wan2_1-T2V-14B_fp8_e4m3fn.safetensors'}},
    '2': {'class_type': 'WanVideoVAELoader', 'inputs': {'model_name': 'Wan2_1_VAE_bf16.safetensors'}},
}


def test_control_arm_flux_graph_fails_clean_graph_passes():
    """The contract's declared control_arm, executable. A gate that fails both or
    passes both is measuring nothing."""
    bad = lp.attest_licences(FLUX_GRAPH, tag='flux', record=False)
    good = lp.attest_licences(CLEAN_GRAPH, tag='wan', record=False)
    assert bad['ok'] is False
    assert good['ok'] is True


def test_graph_with_no_model_refs_is_unknown_not_pass():
    r = lp.attest_licences({'1': {'class_type': 'PreviewImage', 'inputs': {}}}, record=False)
    assert r['ok'] is None


def test_broken_input_never_raises_and_never_passes():
    """A broken measurement must not stop a render, and must not report green."""
    for junk in (None, {}, 'not a graph', 42):
        r = lp.attest_licences(junk, record=False)
        assert r['ok'] is not True


def test_check_name_routes_to_the_registered_contract():
    bad = lp.attest_licences(FLUX_GRAPH, tag='flux', record=False)
    name = lp.check_name(bad)
    assert qc.contract_for(name) is not None
    assert qc.contract_for(name).name == 'licence_provenance'


# ── ladder registration ─────────────────────────────────────────────────────
def test_gate_is_registered_in_the_taxonomy():
    assert 'licence-provenance' in qc.DEFECT_TAXONOMY
    assert 'licence-provenance' in qc.gated_classes()


def test_gate_enters_at_shadow():
    """New gates earn authority; they are not born with it. Promotion is
    scripts/qc_gate_admin.py promote, which refuses unless golden passes."""
    assert qc.mode_for('licence_provenance:non_commercial') == qc.SHADOW


def test_contract_declares_a_control_arm_and_its_blindness():
    c = qc.contract_for('licence_provenance:cleared')
    assert c.control_arm, 'rule 4: a metric declares its control arm'
    assert c.blind_to, 'an honest gate says what it cannot see'


# ── the pause switch ────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _clean_env():
    old = os.environ.get('ZYG_FLUX_RENDERS')
    os.environ.pop('ZYG_FLUX_RENDERS', None)
    yield
    if old is None:
        os.environ.pop('ZYG_FLUX_RENDERS', None)
    else:
        os.environ['ZYG_FLUX_RENDERS'] = old


def test_flux_is_paused_by_default():
    """2026-08-09 operator decision: pause FLUX renders until migrated."""
    assert lp.flux_paused() is True


def test_typo_in_the_env_var_reads_as_paused():
    """The safe reading of a mistyped switch is 'do not produce more exposure'."""
    os.environ['ZYG_FLUX_RENDERS'] = 'alowed'
    assert lp.flux_paused() is True


def test_explicit_allow_resumes():
    os.environ['ZYG_FLUX_RENDERS'] = 'allowed'
    assert lp.flux_paused() is False
    assert lp.assert_flux_allowed('test') is True


def test_assert_raises_while_paused():
    with pytest.raises(lp.FluxRendersPaused):
        lp.assert_flux_allowed('test')


def test_pause_exception_is_catchable_as_exception():
    """Unlike qc_contract.QCBlocked (a BaseException control signal), a caller that
    degrades gracefully around a render SHOULD be able to catch this."""
    assert issubclass(lp.FluxRendersPaused, Exception)


# ── the publish boundary ────────────────────────────────────────────────────
def test_publish_refuses_unknown_lineage():
    """For a monetised channel, 'nobody recorded this licence' is not consent."""
    d = lp.publish_decision(['SomeUnrecordedModel.safetensors'])
    assert d['allowed'] is False
    assert d['verdict'] == 'unknown'


def test_publish_refuses_non_commercial():
    d = lp.publish_decision(['flux1-dev.safetensors'])
    assert d['allowed'] is False
    assert d['verdict'] == 'fail'


def test_family_decision_refuses_flux_while_paused():
    """The approval-boundary counterpart: at approval a contact-sheet run has no
    weights yet (it trains the adapter it will use), so the base family is the
    only knowable licence fact."""
    d = lp.family_decision('flux')
    assert d['allowed'] is False
    assert d['verdict'] == 'fail'


def test_family_decision_allows_wan():
    d = lp.family_decision('wan')
    assert d['allowed'] is True
    assert d['verdict'] == 'pass'


def test_family_decision_unknown_family_is_refused():
    d = lp.family_decision('some-model-nobody-registered')
    assert d['allowed'] is False
    assert d['verdict'] == 'unknown'


def test_pause_overrides_a_clean_registry_entry():
    """The pause is a stronger statement than the registry — an operator may
    pause a family for reasons the licence file knows nothing about."""
    os.environ['ZYG_FLUX_RENDERS'] = 'allowed'
    assert lp.family_decision('flux')['allowed'] is False, (
        'flux1-dev is non-commercial in the registry, so un-pausing alone must not clear it'
    )


def test_sdxl_family_clears_the_lora_not_the_render_checkpoint():
    """SDXL adapters train on SDXL base 1.0 (OpenRAIL++-M, commercial OK) but
    RENDER on Juggernaut/DynaVision, whose terms are unresolved. Clearing the
    family must not be read as clearing the render path."""
    assert lp.family_decision('sdxl')['allowed'] is True
    for ckpt in ('Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors', 'DynaVisionXL.safetensors'):
        assert lp.classify_weight(ckpt, kind='checkpoint')['status'] == lp.UNKNOWN


def test_deliberately_unresolved_entries_carry_an_open_question():
    """An entry that records ambiguity must say what would resolve it, or it is
    just a missing entry with extra words."""
    reg = lp.load_registry()
    for rule in reg['weights']:
        if 'commercial' not in rule:
            assert rule.get('open_question'), f'{rule.get("licence")} is unresolved but names no open question'


def test_publish_allows_fully_cleared_manifest():
    d = lp.publish_decision(['Wan2_1-T2V-14B_fp8_e4m3fn.safetensors', 'flux1-schnell.safetensors'])
    assert d['allowed'] is True
    assert d['verdict'] == 'pass'
