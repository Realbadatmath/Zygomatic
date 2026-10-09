#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers extracted from ``creature_sheet_service.build_sheet``.

``build_sheet`` was 618 lines with eight closures, so none of the logic below had ever
been exercised on its own: cell routing, the reference ranking, the judge's effect on a
cell record, the regen selection, the sheet caption. Each test here pins one behaviour
the old function had. Nothing touches a GPU, a service or the network.
"""

from __future__ import annotations

import json
import os

import pytest

from zyg_workflows.creature_sheet_service import build_anchors as BA
from zyg_workflows.creature_sheet_service import build_cells as BC


def _run(**kw) -> BA.SheetRun:
    """A SheetRun with inert callbacks, overridden by whatever the test cares about."""
    fields = dict(
        dataset_dir='/ds',
        brief={},
        source='reference',
        preset='standard',
        log=lambda _m: None,
        prog=lambda _m: None,
        halt=lambda: None,
        sdir='/ds/contact_sheet',
        desc='a creature',
        style_hint='',
        body_plan='',
        brief_neg='',
        locks={},
        lock_sig='',
        report={},
        t0=0.0,
    )
    fields.update(kw)
    return BA.SheetRun(**fields)


# ── references ───────────────────────────────────────────────────────────


def test_refs_agreement_reports_the_worst_pair_and_the_rounded_mean():
    assert BA.refs_agreement([0.9, 0.4, 0.5]) == {'min': 0.4, 'mean': 0.6}
    assert BA.refs_agreement([0.81, 0.82]) == {'min': 0.81, 'mean': 0.815}


def test_refs_agreement_of_a_single_pair_is_that_pair():
    assert BA.refs_agreement([0.72]) == {'min': 0.72, 'mean': 0.72}


def test_reference_is_whole_body_reads_the_whole_body_answer_only():
    yes = {'verdicts': [{'id': 'whole_body', 'answer': 'yes'}, {'id': 'one_subject', 'answer': 'no'}]}
    no = {'verdicts': [{'id': 'whole_body', 'answer': 'no'}]}
    assert BA.reference_is_whole_body(yes) is True
    assert BA.reference_is_whole_body(no) is False
    assert BA.reference_is_whole_body({}) is False


def test_reference_rank_key_puts_clean_whole_body_references_first():
    """The ladder build_sheet used: no criticals, then whole body, then earliest index."""
    whole = {'verdicts': [{'id': 'whole_body', 'answer': 'yes'}]}
    crop = {'verdicts': [{'id': 'whole_body', 'answer': 'no'}]}
    flagged = {'verdicts': [{'id': 'whole_body', 'answer': 'yes'}], 'criticals': ['two_subjects']}
    keys = {'whole': BA.reference_rank_key(whole, 1), 'crop': BA.reference_rank_key(crop, 0)}
    assert max(keys, key=keys.get) == 'whole'
    assert BA.reference_rank_key(flagged, 0) < BA.reference_rank_key(crop, 2)


def test_reference_rank_key_breaks_a_tie_towards_the_earlier_reference():
    whole = {'verdicts': [{'id': 'whole_body', 'answer': 'yes'}]}
    assert BA.reference_rank_key(whole, 0) > BA.reference_rank_key(whole, 3)


# ── anchors ──────────────────────────────────────────────────────────────


def test_scratch_prompt_carries_the_brief_and_appends_the_style_hint():
    prompt = BA.scratch_prompt('a teal pufferball', {'visual_traits': 'banded tail.'}, 'watercolour')
    assert prompt.startswith('a teal pufferball. banded tail. single creature, full body, front view,')
    assert 'no people, no text' in prompt
    assert prompt.endswith(', watercolour')


def test_scratch_prompt_without_a_style_hint_ends_on_the_fixed_tail():
    assert BA.scratch_prompt('a newt', {}, '').endswith('no people, no text')


def test_checkpoint_usable_needs_both_images_and_a_matching_lock_signature(tmp_path):
    ident = tmp_path / 'identity.png'
    full = tmp_path / 'full.png'
    ident.write_bytes(b'i')
    full.write_bytes(b'f')
    ck = {'identity': str(ident), 'full_body': str(full), 'lock_sig': 'sig-a'}
    assert BA.checkpoint_usable(ck, 'sig-a') is True
    assert BA.checkpoint_usable(ck, 'sig-b') is False
    assert BA.checkpoint_usable({**ck, 'full_body': str(tmp_path / 'gone.png')}, 'sig-a') is False
    assert BA.checkpoint_usable({}, '') is False


def test_resume_anchors_adopts_a_matching_checkpoint_and_says_so(tmp_path):
    sdir = tmp_path / 'contact_sheet'
    (sdir / 'anchors').mkdir(parents=True)
    ident = sdir / 'anchors' / 'identity.png'
    ident.write_bytes(b'i')
    side = sdir / 'anchors' / 'side.png'
    side.write_bytes(b's')
    (sdir / 'anchors' / 'anchors.json').write_text(
        json.dumps(
            {
                'identity': str(ident),
                'full_body': str(ident),
                'side': str(side),
                'side_mirror': str(tmp_path / 'never-written.png'),
                'lock_sig': 'sig-a',
                'report': {'identity': {'from': 'reference'}},
                'refs': [{'path': str(ident)}],
            }
        ),
        encoding='utf-8',
    )
    said: list[str] = []
    run = _run(sdir=str(sdir), lock_sig='sig-a', report={'anchors': {}, 'refs': []}, log=said.append)
    assert BA.resume_anchors(run) is True
    assert run.anchor_ref == str(ident)
    assert run.anchor_side == str(side)
    assert run.anchor_side_mirror is None  # the mirror is gone, so it is not reused
    assert run.report['anchors'] == {'identity': {'from': 'reference'}}
    assert said == ['resume: anchors reused from checkpoint']


def test_resume_anchors_rebuilds_when_the_locks_changed(tmp_path):
    sdir = tmp_path / 'contact_sheet'
    (sdir / 'anchors').mkdir(parents=True)
    full = sdir / 'anchors' / 'full.png'
    full.write_bytes(b'f')
    (sdir / 'anchors' / 'anchors.json').write_text(
        json.dumps({'identity': str(full), 'full_body': str(full), 'lock_sig': 'old'}), encoding='utf-8'
    )
    said: list[str] = []
    run = _run(sdir=str(sdir), lock_sig='new', report={'anchors': {}, 'refs': []}, log=said.append)
    assert BA.resume_anchors(run) is False
    assert run.anchor_full is None
    assert said == ['anchor checkpoint ignored: locks / body plan changed — rebuilding anchors']


def test_resume_anchors_survives_an_unreadable_checkpoint(tmp_path):
    sdir = tmp_path / 'contact_sheet'
    (sdir / 'anchors').mkdir(parents=True)
    (sdir / 'anchors' / 'anchors.json').write_text('{not json', encoding='utf-8')
    said: list[str] = []
    run = _run(sdir=str(sdir), report={'anchors': {}, 'refs': []}, log=said.append)
    assert BA.resume_anchors(run) is False
    assert said and said[0].startswith('anchor checkpoint unreadable (')


def test_candidate_record_defaults_to_pass_when_the_judge_said_nothing():
    rec = BA.candidate_record('/c0.png', {}, dino=None)
    assert rec == {
        'path': '/c0.png',
        'ok': True,
        'judged': False,
        'flags': [],
        'dino': None,
        'reasons': [],
        'verdicts': [],
    }


def test_anchors_ready_line_names_the_side_anchor_and_body_plan_only_when_present():
    bare = _run(anchor_ref='/a/identity.png', anchor_full='/a/anchor_full.png')
    assert BA.anchors_ready_line(bare) == 'anchors ready: identity=identity.png full_body=anchor_full.png'
    full = _run(
        anchor_ref='/a/identity.png',
        anchor_full='/a/anchor_full.png',
        anchor_side='/a/anchor_side.png',
        body_plan='four legs, long banded tail',
    )
    assert BA.anchors_ready_line(full) == (
        'anchors ready: identity=identity.png full_body=anchor_full.png '
        'side=anchor_side.png body_plan="four legs, long banded tail"'
    )


# ── cells ────────────────────────────────────────────────────────────────


def test_cell_source_copies_the_full_body_anchor_for_the_anchor_cell():
    run = _run(anchor_full='/a/full.png', anchor_ref='/a/ident.png')
    assert BC.cell_source(run, {'anchor': True, 'id': 'front_full'}) == ('/a/full.png', None, True)


def test_cell_source_rotates_a_side_cell_from_the_side_lock_or_its_mirror():
    run = _run(anchor_full='/a/full.png', anchor_side='/a/side.png', anchor_side_mirror='/a/mirror.png')
    src, instr, is_copy = BC.cell_source(run, {'side_source': 'side', 'side_turn': None, 'id': 'side_r'})
    assert (src, instr, is_copy) == ('/a/side.png', None, True)
    src, instr, is_copy = BC.cell_source(
        run,
        {'side_source': 'mirror', 'side_turn': 45, 'side_text': 'Rear three-quarter.', 'id': 'back_q_l'},
    )
    assert src == '/a/mirror.png'
    assert instr.startswith('Rotate the camera 45 degrees to the ')
    assert is_copy is False


def test_cell_source_only_orbits_from_a_closeup_reference_for_ref_source_cells():
    """The 2026-08-26 pufferball bug: an ORBIT from a crop invents what the crop cut off."""
    run = _run(anchor_full='/a/full.png', anchor_ref='/a/crop.png', ref_is_closeup=True)
    dolly = {'ref_source': True, 'instruction': 'Dolly in.', 'id': 'head_front'}
    orbit = {'instruction': 'Rotate 45 degrees.', 'id': 'head_q'}
    assert BC.cell_source(run, dolly) == ('/a/crop.png', 'Dolly in.', False)
    assert BC.cell_source(run, orbit) == ('/a/full.png', 'Rotate 45 degrees.', False)
    whole = _run(anchor_full='/a/full.png', anchor_ref='/a/full.png', ref_is_closeup=False)
    assert BC.cell_source(whole, dolly) == ('/a/full.png', 'Dolly in.', False)


def test_cell_sig_changes_with_the_source_pixels_and_with_the_prompt(tmp_path):
    src = tmp_path / 'full.png'
    src.write_bytes(b'pixels-v1')
    run = _run(anchor_full=str(src))
    a = {'instruction': 'Rotate 90 degrees.', 'id': 'side_r'}
    first = BC.cell_sig(run, a)
    assert first == BC.cell_sig(run, a)
    src.write_bytes(b'pixels-v2-longer')
    assert BC.cell_sig(run, a) != first
    assert BC.cell_sig(_run(anchor_full=str(src), body_plan='long tail'), a) != BC.cell_sig(run, a)


def test_failed_cell_record_stays_on_the_sheet_marked_render_failed():
    a = {'id': 'top_down', 'label': 'top-down', 'kind': 'body', 'band': 'wide'}
    rec = BC.failed_cell_record(a, 7, '/a/full.png')
    assert rec['reasons'] == ['render_failed']
    assert rec['ok'] is False
    assert (rec['idx'], rec['path'], rec['seed'], rec['source_anchor']) == (7, None, 7007, '/a/full.png')


def test_cell_log_line_shows_the_dino_score_only_when_one_was_measured():
    a = {'label': 'front view, full body'}
    ok = {'ok': True, 'reasons': [], 'dino': 0.8123}
    assert BC.cell_log_line(0, 14, a, ok) == 'cell 1/14 front view, full body: ok dino=0.81'
    unmeasured = {'ok': True, 'reasons': [], 'dino': None}
    assert BC.cell_log_line(3, 14, a, unmeasured) == 'cell 4/14 front view, full body: ok'
    bad = {'ok': False, 'reasons': ['render_failed', 'vlm:two_subjects'], 'dino': None}
    assert BC.cell_log_line(3, 14, a, bad) == ('cell 4/14 front view, full body: FAIL render_failed,vlm:two_subjects')


def test_resume_cell_reuses_a_cell_whose_source_and_prompt_still_match(tmp_path):
    sdir = tmp_path / 'contact_sheet'
    (sdir / 'cells').mkdir(parents=True)
    anchor = sdir / 'anchor_full.png'
    anchor.write_bytes(b'pixels')
    cell_png = sdir / 'cells' / 'cell_02.png'
    cell_png.write_bytes(b'cell')
    run = _run(sdir=str(sdir), anchor_full=str(anchor))
    a = {'id': 'side_r', 'label': 'right profile', 'instruction': 'Rotate 90 degrees.'}
    rec = {'idx': 2, 'id': 'side_r', 'path': str(cell_png), 'source_sig': BC.cell_sig(run, a)}
    (sdir / 'cells' / 'cell_02.json').write_text(json.dumps(rec), encoding='utf-8')

    said: list[str] = []
    run.log = said.append
    assert BC.resume_cell(run, a, 2) == rec
    assert said == ['resume: cell 02 right profile reused from checkpoint']

    said.clear()
    stale = {**rec, 'source_sig': 'something-else'}
    (sdir / 'cells' / 'cell_02.json').write_text(json.dumps(stale), encoding='utf-8')
    assert BC.resume_cell(run, a, 2) is None
    assert said == ['resume: cell 02 right profile stale (source or prompt changed) — re-rendering']


def test_resume_cell_returns_none_when_there_is_no_checkpoint(tmp_path):
    (tmp_path / 'cells').mkdir()
    run = _run(sdir=str(tmp_path))
    assert BC.resume_cell(run, {'id': 'front_full', 'label': 'front'}, 0) is None


def test_save_cell_writes_the_record_where_a_resume_looks_for_it(tmp_path):
    (tmp_path / 'cells').mkdir()
    run = _run(sdir=str(tmp_path))
    BC.save_cell(run, {'idx': 5, 'id': 'back_full', 'path': '/x.png'})
    written = json.load(open(os.path.join(str(tmp_path), 'cells', 'cell_05.json'), encoding='utf-8'))
    assert written == {'idx': 5, 'id': 'back_full', 'path': '/x.png'}


# ── the judge ────────────────────────────────────────────────────────────


def test_apply_cell_verdict_splits_hard_flags_from_soft_ones():
    rec = {'idx': 1, 'reasons': [], 'soft': [], 'ok': True, 'judged': False}
    BC.apply_cell_verdict(
        rec, {'judged': True, 'criticals': ['two_subjects'], 'majors': ['angle_match'], 'tier': 'full'}, lambda _m: None
    )
    assert rec['reasons'] == ['vlm:two_subjects']
    assert rec['soft'] == ['vlm:angle_match']
    assert rec['ok'] is False
    assert rec['judged'] is True
    assert rec['judge_tier'] == 'full'
    assert rec['caption_mode'] == 'neutral'


def test_apply_cell_verdict_exempts_a_locked_view_and_logs_it():
    """A copy of the operator's side lock may not be failed for its own viewpoint."""
    rec = {'idx': 9, 'reasons': [], 'soft': [], 'ok': True, 'locked_view': True}
    said: list[str] = []
    BC.apply_cell_verdict(rec, {'judged': True, 'criticals': ['whole_body', 'two_subjects']}, said.append)
    assert rec['exempt'] == ['vlm:whole_body']
    assert rec['reasons'] == ['vlm:two_subjects']
    assert said == ["cell 09 locked view: judge flags ['vlm:whole_body'] not applied (operator lock)"]


def test_apply_cell_verdict_drops_the_previous_rounds_vlm_flags():
    rec = {
        'idx': 2,
        'reasons': ['vlm:two_subjects', 'identity_lost:0.41<0.5'],
        'soft': ['vlm:angle_match'],
        'ok': False,
    }
    BC.apply_cell_verdict(rec, {'judged': True}, lambda _m: None)
    assert rec['reasons'] == ['identity_lost:0.41<0.5']  # the structural reason survives
    assert rec['soft'] == []
    assert rec['ok'] is False


def test_apply_cell_verdict_records_why_an_offline_judge_said_nothing():
    rec = {'idx': 0, 'reasons': [], 'soft': [], 'ok': True}
    BC.apply_cell_verdict(rec, {'judged': False, 'reason': 'no VRAM'}, lambda _m: None)
    assert rec['judge_offline'] == 'no VRAM'
    assert rec['ok'] is True
    assert rec['caption_mode'] == 'angle'


# ── regen + the sheet ────────────────────────────────────────────────────


def _plan(n: int) -> list[dict]:
    return [{'id': f'c{i}', 'anchor': i == 0} for i in range(n)]


def test_cells_to_regen_skips_the_anchor_cell_and_the_locked_views():
    plan = _plan(4)
    cells = [
        {'idx': 0, 'id': 'c0', 'ok': False},
        {'idx': 1, 'id': 'c1', 'ok': False},
        {'idx': 2, 'id': 'c2', 'ok': False, 'locked_view': True},
        {'idx': 3, 'id': 'c3', 'ok': True},
    ]
    assert [c['id'] for c in BC.cells_to_regen(cells, plan, 1)] == ['c1']


def test_cells_to_regen_chases_soft_flags_only_while_the_soft_rounds_last():
    plan = _plan(2)
    cells = [{'idx': 0, 'id': 'c0', 'ok': True}, {'idx': 1, 'id': 'c1', 'ok': True, 'soft': ['vlm:angle_match']}]
    assert [c['id'] for c in BC.cells_to_regen(cells, plan, BC.MAX_REGEN_SOFT)] == ['c1']
    assert BC.cells_to_regen(cells, plan, BC.MAX_REGEN_SOFT + 1) == []


def test_sheet_title_counts_the_training_cells_and_names_every_extra():
    cells = [
        {'ok': True},
        {'ok': True, 'soft': ['vlm:whole_body']},
        {'ok': False},
    ]
    run = _run(brief={'name': 'Pufferball'}, source='reference', anchor_side='/a/side.png', body_plan='long tail')
    assert BC.sheet_title(run, cells, 2, 1) == (
        'Pufferball — 2/3 cells train (1 with neutral/partial captions) — reference · side anchor · body plan'
    )


def test_sheet_title_falls_back_to_creature_and_drops_the_empty_clauses():
    run = _run(brief={}, source='scratch')
    assert BC.sheet_title(run, [{'ok': True}], 1, 0) == 'creature — 1/1 cells train — scratch'


# ── the context object ───────────────────────────────────────────────────


def test_new_run_refuses_reference_mode_without_a_usable_reference(tmp_path):
    with pytest.raises(RuntimeError, match='no reference image was provided'):
        BA.new_run(
            str(tmp_path),
            {'name': 'x'},
            source='reference',
            reference_paths=[str(tmp_path / 'absent.png')],
            preset='standard',
            log=lambda _m: None,
            prog=lambda _m: None,
            halt=lambda: None,
        )


def test_new_run_normalises_the_source_and_makes_the_scratch_dirs(tmp_path):
    run, refs_in = BA.new_run(
        str(tmp_path),
        {'description': ' a teal pufferball ', 'body_plan': ' long tail ', 'negative': ' no humans '},
        source='from_scratch',
        reference_paths=None,
        preset='compact',
        log=lambda _m: None,
        prog=lambda _m: None,
        halt=lambda: None,
    )
    assert (run.source, refs_in) == ('scratch', [])
    assert (run.desc, run.body_plan, run.brief_neg) == ('a teal pufferball', 'long tail', 'no humans')
    for sub in BA.SCRATCH_DIRS:
        assert os.path.isdir(os.path.join(run.sdir, sub)), sub
    assert run.report['preset'] == 'compact'
    assert run.report['cells'] == [] and run.report['anchors'] == {}


# ── reference_model/build.py: the stages of t_build_reference_asset ───────
#
# Two 2026-10-09 splits land in this one file because both their modules are
# named build.py (creature_sheet_service/build.py above, and
# arch_assistant_ext/reference_model/build.py here). t_build_reference_asset was
# a 337-line def: the argument refusals, the extend lookup, the Blender command
# line, the result parsing and the stale-preview sweep were one frame, and the
# only way to ask "is a bad view name refused?" was to have Blender installed.
# No Blender, no network below either — strings, dicts and a tmp_path.


@pytest.fixture(scope='module')
def BS():
    """`build_stages`, imported past the arch_assistant.prompts that raises at HEAD.

    prompts.py calls _relax_material_enums() before MATERIALS is bound, so the whole
    arch tree is unimportable without a stub; the fixture takes every key it added back
    out of sys.modules, so no other test file ever sees it.
    """
    import importlib
    import sys
    import types

    before = set(sys.modules)
    stub = types.ModuleType('zyg_workflows.arch_assistant.prompts')
    stub.__getattr__ = lambda name: object()
    sys.modules['zyg_workflows.arch_assistant.prompts'] = stub
    try:
        yield importlib.import_module('zyg_workflows.arch_assistant_ext.reference_model.build_stages')
    finally:
        for key in set(sys.modules) - before:
            if key.startswith('zyg_workflows.arch_assistant'):
                del sys.modules[key]


def test_an_empty_build_script_is_refused(BS):
    spec, refusal = BS.validate_build_request('   ', 'workbench', 'iso')
    assert spec is None
    assert refusal.startswith('refused: script is empty')


def test_an_oversized_build_script_names_the_limit(BS):
    spec, refusal = BS.validate_build_request('x' * (BS.MAX_SCRIPT + 1), 'workbench', 'iso')
    assert spec is None
    assert str(BS.MAX_SCRIPT) in refusal


def test_only_workbench_and_eevee_are_build_engines(BS):
    assert BS.validate_build_request('bpy', 'cycles', 'iso')[1] == 'refused: engine must be workbench or eevee'
    assert BS.validate_build_request('bpy', 'EEVEE', 'iso')[0].engine == 'eevee'


def test_an_unknown_view_is_named_in_the_refusal(BS):
    spec, refusal = BS.validate_build_request('bpy', 'workbench', 'iso, sideways')
    assert spec is None
    assert refusal.startswith('refused: view sideways is not one of')


def test_build_views_are_split_on_commas_and_spaces(BS):
    spec, refusal = BS.validate_build_request('  bpy  ', 'workbench', 'iso side,front')
    assert refusal == ''
    assert spec.views == ['iso', 'side', 'front']
    assert spec.src == 'bpy'


def test_a_plain_build_inherits_nothing_from_the_asset(BS):
    rec = {'id': 'm1', 'asset': {'blend': '/nope.blend', 'item': 'ship', 'script': 'old', 'edits': [{'ts': 't'}]}}
    target, refusal = BS.extend_target(rec, 'tower', extend=False)
    assert refusal == ''
    assert target.blend == ''
    assert target.name == 'tower'


def test_extend_without_a_built_asset_is_refused(BS):
    target, refusal = BS.extend_target({'id': 'm1'}, '', extend=True)
    assert target is None
    assert 'there is no built asset on disk to extend' in refusal


def test_extend_keeps_the_assets_own_item_name(BS, tmp_path):
    """The 2026-09-24 bug: a nameless extend forked the ship into a second item."""
    blend = tmp_path / 'ship.blend'
    blend.write_text('x')
    rec = {'id': 'm1', 'asset': {'blend': str(blend), 'item': 'ship', 'script': 'base', 'edits': [{'ts': 't'}]}}
    target, refusal = BS.extend_target(rec, '', extend=True)
    assert refusal == ''
    assert target.name == 'ship'
    assert target.script == 'base'
    assert target.edits == [{'ts': 't'}]


def test_the_blender_command_clamps_the_frame_and_takes_two_views(BS):
    cmd = BS.blender_command(
        work='/w',
        base='/w/ship',
        spec=BS.BuildSpec(src='bpy', engine='eevee', views=['iso', 'side', 'front']),
        width=99999,
        height=1,
        prev='',
        check=False,
        inspect=False,
        portfolio=False,
    )
    assert cmd[cmd.index('--views') + 1] == 'iso,side'
    assert cmd[cmd.index('--width') + 1] == '2560'
    assert cmd[cmd.index('--height') + 1] == '240'
    assert cmd[cmd.index('--engine') + 1] == 'eevee'
    assert '--check' not in cmd and '--inspect' not in cmd and '--portfolio' not in cmd
    assert '--edit-blend' not in cmd


def test_the_blender_command_carries_every_switch_that_is_on(BS):
    cmd = BS.blender_command(
        work='/w',
        base='/w/ship',
        spec=BS.BuildSpec(src='bpy', engine='workbench', views=[]),
        width=1280,
        height=720,
        prev='/old.blend',
        check=True,
        inspect=True,
        portfolio=True,
    )
    assert cmd[cmd.index('--views') + 1] == 'iso'
    assert cmd[cmd.index('--edit-blend') + 1] == '/old.blend'
    assert cmd[cmd.index('--inspect') + 1] == str(BS.INSPECT_N)
    assert cmd[cmd.index('--portfolio-engine') + 1] == 'eevee'
    assert '--check' in cmd


def test_the_last_result_line_is_the_one_that_counts(BS):
    out = 'noise\nREFBUILD_JSON {"ok": false}\nmore\nREFBUILD_JSON {"ok": true, "objects": 2}\ntail'
    res, fallback = BS.parse_build_result(out)
    assert fallback == ''
    assert res == {'ok': True, 'objects': 2}


def test_output_without_a_result_line_comes_back_as_the_output(BS):
    res, fallback = BS.parse_build_result('Blender quit\n\nsegfault\n')
    assert res is None
    assert 'the build produced no result line' in fallback
    assert 'segfault' in fallback


def test_a_raising_script_reports_its_traceback_and_what_it_printed(BS):
    txt = BS.build_error_text({'script_error': 'ZeroDivisionError'}, 'log line', 'printed line')
    assert txt.startswith('the script RAISED inside Blender')
    assert 'ZeroDivisionError' in txt and 'printed line' in txt and 'log line' in txt


def test_a_failed_build_quotes_its_error(BS):
    assert BS.build_error_text({'ok': False, 'error': 'no camera'}, '', '') == 'the build failed: no camera'


def test_a_script_that_left_no_geometry_says_so(BS):
    txt = BS.build_error_text({'ok': True, 'objects': 0}, 'the log', '')
    assert 'left NO geometry' in txt
    assert txt.endswith('the log')


def test_a_good_build_result_has_no_error_text(BS):
    assert BS.build_error_text({'ok': True, 'objects': 3}, '', '') == ''


def test_a_preview_set_is_swept_only_by_the_build_that_reshoots_it(BS, tmp_path):
    adir = tmp_path / 'asset'
    adir.mkdir()
    for leaf in ('inspect-0-iso.png', 'inspection-sheet.png', 'check-1-plan.png', 'preview.png'):
        (adir / leaf).write_text('x')
    gone = BS.sweep_stale_previews(str(adir), inspect=False, check=True)
    assert [os.path.basename(p) for p in gone] == ['check-1-plan.png']
    assert sorted(p.name for p in adir.iterdir()) == [
        'inspect-0-iso.png',
        'inspection-sheet.png',
        'preview.png',
    ]


def test_an_inspecting_build_sweeps_its_own_set_and_its_sheet(BS, tmp_path):
    adir = tmp_path / 'asset'
    adir.mkdir()
    for leaf in ('inspect-0-iso.png', 'inspection-sheet.png', 'check-1-plan.png'):
        (adir / leaf).write_text('x')
    BS.sweep_stale_previews(str(adir), inspect=True, check=False)
    assert sorted(p.name for p in adir.iterdir()) == ['check-1-plan.png']


# ── creature_sheet_service/build.py: the checkpoint key and the regen swap ─
#
# Four helpers of the 618-line build_sheet that the first pass left untested:
# the lock signature that decides whether an anchor checkpoint may be reused,
# the pairwise DINO agreement of the references, the checkpoint write itself and
# the best-of-N swap that decides whether a regen replaces the cell on the sheet.


def test_lock_signature_tracks_both_lock_files_and_the_body_plan(tmp_path):
    full = tmp_path / 'full.png'
    full.write_bytes(b'full-body')
    side = tmp_path / 'side.png'
    side.write_bytes(b'right profile')
    both = BA.lock_signature({'full_body': str(full), 'side': str(side)}, 'quadruped')
    assert len(both.split('|')) == 3
    # a different body plan, the same files: a checkpoint keyed on the old one is stale
    assert BA.lock_signature({'full_body': str(full), 'side': str(side)}, 'biped') != both
    # editing a lock file changes it too
    side.write_bytes(b'left profile')
    assert BA.lock_signature({'full_body': str(full), 'side': str(side)}, 'quadruped') != both


def test_lock_signature_leaves_no_empty_edges_when_nothing_is_locked():
    unlocked = BA.lock_signature({}, '')
    assert not unlocked.startswith('|') and not unlocked.endswith('|')
    assert unlocked == BA._text_sig('')


def test_pairwise_similarities_measures_every_pair_and_drops_the_unmeasured(monkeypatch):
    seen = []

    def _sim(a, b):
        seen.append((a, b))
        return None if 'x' in (a, b) else (a + b) / 100.0

    monkeypatch.setattr(BA._cid, 'similarity_emb', _sim)
    assert BA.pairwise_similarities([10, 20, 30]) == [0.3, 0.4, 0.5]
    assert seen == [(10, 20), (10, 30), (20, 30)]
    assert BA.pairwise_similarities(['x', 10, 20]) == [0.3]
    assert BA.pairwise_similarities([10]) == []


def test_write_anchor_checkpoint_records_what_a_resume_checks(tmp_path):
    (tmp_path / 'anchors').mkdir()
    run = _run(
        sdir=str(tmp_path),
        lock_sig='sig-1',
        body_plan='quadruped',
        anchor_ref='/a/identity.png',
        anchor_full='/a/full.png',
        anchor_side=None,
        anchor_side_mirror=None,
        report={'anchors': {'notes': ['conformed']}, 'refs': [{'path': '/a/ref_00.png'}]},
    )
    BA.write_anchor_checkpoint(run)
    ck = json.load(open(BA.anchor_ckpt(run), encoding='utf-8'))
    assert ck['identity'] == '/a/identity.png' and ck['full_body'] == '/a/full.png'
    assert ck['side'] is None and ck['side_mirror'] is None
    assert ck['lock_sig'] == 'sig-1' and ck['body_plan'] == 'quadruped'
    assert ck['report'] == {'notes': ['conformed']}
    assert ck['refs'] == [{'path': '/a/ref_00.png'}]
    # exactly the keys resume_anchors reads back
    assert BA.checkpoint_usable({**ck, 'identity': str(tmp_path), 'full_body': str(tmp_path)}, 'sig-1') is False


def _regen_cells(tmp_path, cur_ok, new_ok):
    """A one-cell sheet plus a candidate regen, both with a real file on disk."""
    (tmp_path / 'cells').mkdir()
    cur_path = tmp_path / 'cells' / 'cell_00.png'
    cur_path.write_bytes(b'current')
    cand = tmp_path / 'candidates' / 'regen.png'
    cand.parent.mkdir()
    cand.write_bytes(b'candidate')
    cur = {'idx': 0, 'path': str(cur_path), 'seed': 1, 'attempt': 0, 'reasons': [], 'soft': [], 'ok': cur_ok}
    new = {'idx': 0, 'path': str(cand), 'seed': 2, 'attempt': 1, 'reasons': [], 'soft': [], 'ok': new_ok}
    return [cur], new


def test_adopt_regen_replaces_the_cell_when_the_regen_scores_better(tmp_path):
    lines = []
    cells, new = _regen_cells(tmp_path, cur_ok=False, new_ok=True)
    run = _run(sdir=str(tmp_path), log=lines.append)
    BC.adopt_regen(run, cells, new, 1)
    assert cells[0] is new
    assert cells[0]['path'] == os.path.join(str(tmp_path), 'cells', 'cell_00.png')
    assert open(cells[0]['path'], 'rb').read() == b'candidate'
    assert [h['seed'] for h in cells[0]['history']] == [1]
    assert lines == ['cell 00 replaced by regen r1 (ok)']
    assert json.load(open(BC.cell_ckpt(run, 0), encoding='utf-8'))['seed'] == 2


def test_adopt_regen_keeps_the_sheet_cell_but_still_records_the_attempt(tmp_path):
    lines = []
    cells, new = _regen_cells(tmp_path, cur_ok=True, new_ok=False)
    run = _run(sdir=str(tmp_path), log=lines.append)
    BC.adopt_regen(run, cells, new, 2)
    assert cells[0]['seed'] == 1
    assert open(cells[0]['path'], 'rb').read() == b'current'
    assert [h['seed'] for h in cells[0]['history']] == [1]
    assert lines == []
    assert json.load(open(BC.cell_ckpt(run, 0), encoding='utf-8'))['seed'] == 1
