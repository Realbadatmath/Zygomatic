#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The body-plan lock (2026-08-25) and the anchor-agreement gate (2026-08-26).

Moved verbatim out of tests/test_creature_sheet.py when it became this package.
"""

from .common import cj, css, cts, json, needs_checklists, os
from .test_plan_and_sheet import _fake_edit, _noise

from .common import _isolate_review_cards  # noqa: F401  autouse fixture, see common.py

# ── body-plan lock (2026-08-25) ──────────────────────────────────────────────


def test_keep_sentence_and_side_instruction(monkeypatch):
    assert css.keep_sentence('') == css._KEEP
    s = css.keep_sentence('a ball-shaped body; one segmented tail.')
    assert 'Its anatomy: a ball-shaped body; one segmented tail.' in s and 'Plain background' in s
    monkeypatch.setattr(css, 'SIDE_TOWARD_BACK', 'right')
    plan = {a['id']: a for a in css.ANGLES}
    assert css.side_instruction(plan['side_right']) is None  # copy of the side anchor
    assert css.side_instruction(plan['side_left']) is None  # copy of its mirror
    assert css.side_instruction(plan['back']).startswith('Rotate the camera 90 degrees to the right.')
    assert css.side_instruction(plan['back_q_right']).startswith('Rotate the camera 45 degrees to the right.')
    assert css.side_instruction(plan['back_q_left']).startswith('Rotate the camera 45 degrees to the left.')
    assert css.side_instruction(plan['top_down']) == plan['top_down']['instruction']
    assert css.side_instruction(plan['q45_left']) is None and not plan['q45_left'].get('side_source')
    assert 'body_plan' in css.SOFT_FLAGS
    assert css._text_sig('abc') == css._text_sig('abc') and css._text_sig('abc') != css._text_sig('abd')


@needs_checklists
def test_checklist_body_plan_question_only_with_plan():
    cell = cj.load_items(cj.CELL_CHECKLIST)
    without = {i['id'] for i in cj.cell_items('side', kind='body', band='side', base=cell)}
    with_bp = cj.cell_items('side', kind='body', band='side', base=cell, body_plan='one segmented tail.')
    assert 'body_plan' not in without
    q = next(i for i in with_bp if i['id'] == 'body_plan')['question']
    assert 'one segmented tail' in q and '{body_plan}' not in q
    head = {i['id'] for i in cj.cell_items('close', kind='head', base=cell, body_plan='x')}
    assert 'body_plan' not in head


def test_locks_route_side_cells_and_invalidate(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYG_CREATURE_VLM', '0')
    monkeypatch.setenv('ZYG_CREATURE_DINO', '0')
    monkeypatch.setattr(css, 'SIDE_TOWARD_BACK', 'right')
    seen = []
    fake = _fake_edit(tmp_path)

    def spy(ref, instruction, dest, seed, log, size=1024, style_hint='', **kw):
        seen.append({'ref': ref, 'instruction': instruction, 'dest': dest, **kw})
        return fake(ref, instruction, dest, seed, log, size=size, style_hint=style_hint, **kw)

    monkeypatch.setattr(css, '_edit', spy)
    ref = _noise(tmp_path / 'ref.png', 3, size=(120, 80))
    side = _noise(tmp_path / 'side_pick.png', 4, size=(100, 100))
    full = _noise(tmp_path / 'front_pick.png', 5, size=(100, 100))
    brief = {
        'name': 'Puff',
        'description': 'teal furry ball',
        'species': 'pufferball',
        'body_plan': 'a ball-shaped body; one segmented turquoise tail curling up behind',
        'anchor_locks': {'full_body': full, 'side': side},
    }
    ds = tmp_path / 'ds'
    ds.mkdir()
    rep = css.build_sheet(str(ds), brief, source='reference', reference_paths=[ref], preset='standard')
    anchors = rep['anchors']
    assert anchors['full_body']['from'] == 'operator_lock' and anchors['side']['from'] == 'operator_lock'
    assert os.path.isfile(anchors['side']['mirror'])
    cells = {c['id']: c for c in rep['cells']}
    # copies: right profile = the side anchor, left profile = its mirror
    assert (
        cells['side_right']['instruction'] is None and cells['side_right']['source_anchor'] == anchors['side']['path']
    )
    assert cells['side_left']['source_anchor'] == anchors['side']['mirror']
    assert open(cells['side_right']['path'], 'rb').read() == open(anchors['side']['path'], 'rb').read()
    # rotations from the side anchor carry the orbit instruction; front cells still edit the front anchor
    assert cells['back']['source_anchor'] == anchors['side']['path']
    assert 'Rotate the camera 90 degrees to the right' in cells['back']['instruction']
    assert cells['back_q_left']['source_anchor'] == anchors['side']['mirror']
    assert '45 degrees to the left' in cells['back_q_left']['instruction']
    assert cells['q45_left']['source_anchor'] == anchors['full_body']['path']
    # every edit carried the body plan into the prompt; the locked anchor was neither derived nor conformed
    assert seen and all(e.get('body_plan') == brief['body_plan'] for e in seen)
    assert not any('full_cand' in e['dest'] or 'conform' in e['dest'] for e in seen)
    # captions carry the body plan
    css.training_tiles(rep, str(ds), 'ZYG_CREATURE_T', brief)
    cap = open(os.path.join(str(ds), 'training', 'sheet_04.txt')).read()
    assert 'one segmented turquoise tail' in cap and 'right side profile, full body' in cap
    # a re-picked side anchor invalidates exactly the cells rotated from it
    n_before = len(seen)
    side2 = _noise(tmp_path / 'side_pick2.png', 44, size=(100, 100))
    brief2 = dict(brief, anchor_locks={'full_body': full, 'side': side2})
    rep2 = css.build_sheet(str(ds), brief2, source='reference', reference_paths=[ref], preset='standard')
    redone = sorted(os.path.basename(e['dest']) for e in seen[n_before:])
    expect = sorted(
        f'cell_{i:02d}.png' for i, a in enumerate(css.ANGLES) if a.get('side_source') and a.get('side_turn') is not None
    )
    assert redone == expect, (redone, expect)
    assert rep2['anchors']['side']['src'] == side2
    assert open(rep2['cells'][4]['path'], 'rb').read() == open(rep2['anchors']['side']['path'], 'rb').read()


def test_conform_pass_without_lock(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYG_CREATURE_VLM', '0')
    monkeypatch.setenv('ZYG_CREATURE_DINO', '0')
    monkeypatch.setattr(css, 'CONFORM_SEEDS', 2)
    calls = []
    fake = _fake_edit(tmp_path)

    def spy(ref, instruction, dest, seed, log, size=1024, style_hint='', **kw):
        calls.append((os.path.basename(dest), kw.get('angles_scale')))
        return fake(ref, instruction, dest, seed, log, size=size, style_hint=style_hint, **kw)

    monkeypatch.setattr(css, '_edit', spy)
    ref = _noise(tmp_path / 'ref.png', 7, size=(120, 80))
    ds = tmp_path / 'ds'
    ds.mkdir()
    rep = css.build_sheet(
        str(ds),
        {'name': 'P', 'description': 'x', 'body_plan': 'a round body'},
        source='reference',
        reference_paths=[ref],
        preset='compact',
    )
    conform = [c for c in calls if c[0].startswith('conform_cand_')]
    assert len(conform) == 2 and all(s == 0.0 for _, s in conform), 'conform pass runs with the angles LoRA off'
    assert rep['anchors']['full_body']['from'].endswith('+conform')
    assert rep['anchors']['full_body']['conform']['path']
    assert not any(os.path.basename(c['source_anchor']).startswith('anchor_side') for c in rep['cells'])
    # the rotation cells did NOT switch the LoRA off
    assert all(s is None for name, s in calls if name.startswith('cell_'))


def test_brief_for_run_reuses_and_carries_locks(tmp_path):
    ds = tmp_path / 'ds'
    ds.mkdir()
    logs = []
    existing = {'name': 'Puff', 'description': 'old desc', 'body_plan': 'one tail', 'anchor_locks': {'side': '/x.png'}}
    json.dump(existing, open(ds / 'brief.json', 'w'))
    # resumed run: verbatim reuse
    b = cts._brief_for_run({'resumed': '2026-08-25'}, 'Puff', str(ds), [], logs.append)
    assert b['description'] == 'old desc' and b['body_plan'] == 'one tail' and b.get('profile_key')
    # fresh run: new brief, operator keys carried over
    from zyg_workflows import creature_training_service as _c

    orig = _c._generate_creature_brief
    _c._generate_creature_brief = lambda d, l, reference_paths=None: {
        'name': 'Puff',
        'description': 'new desc',
        'species': 'x',
        'visual_traits': 'y',
        'style_hint': '',
        'profile_key': 'real_wildlife',
    }
    try:
        b2 = cts._brief_for_run({}, 'Puff', str(ds), [], logs.append)
    finally:
        _c._generate_creature_brief = orig
    assert (
        b2['description'] == 'new desc' and b2['body_plan'] == 'one tail' and b2['anchor_locks'] == {'side': '/x.png'}
    )


@needs_checklists
def test_locked_copies_skip_view_flags_and_regen(tmp_path, monkeypatch):
    """A copy of the operator's side lock cannot be re-rendered: the judge's
    view/framing flags are recorded as exempt (no partial-view caption, no regen
    round), while a real rotation keeps them as soft flags."""
    monkeypatch.setenv('ZYG_CREATURE_DINO', '0')
    monkeypatch.setenv('ZYG_CREATURE_VLM', '1')
    monkeypatch.setattr(css, 'SIDE_TOWARD_BACK', 'right')
    edits = []
    fake = _fake_edit(tmp_path)

    def spy(ref, instruction, dest, seed, log, size=1024, style_hint='', **kw):
        edits.append(os.path.basename(dest))
        return fake(ref, instruction, dest, seed, log, size=size, style_hint=style_hint, **kw)

    monkeypatch.setattr(css, '_edit', spy)

    def fake_judge(jobs, *, offload=True, log_fn=None):
        out = {}
        for j in jobs:
            ids = [i['id'] for i in j['items']]
            majors = [f for f in ('angle_match', 'whole_body') if f in ids]
            out[j['key']] = {
                'judged': True,
                'ok': not majors,
                'flags': majors,
                'criticals': [],
                'majors': majors,
                'verdicts': [
                    {
                        'id': i,
                        'answer': 'no' if i in majors else 'yes',
                        'expected': 'yes',
                        'ok': i not in majors,
                        'severity': 'major',
                    }
                    for i in ids
                ],
                'tier': 'fake',
            }
        return out

    monkeypatch.setattr(cj, 'judge_batch', fake_judge)
    monkeypatch.setattr(cj, 'shutdown', lambda log_fn=None: None)
    ref = _noise(tmp_path / 'ref.png', 11, size=(120, 80))
    side = _noise(tmp_path / 'side.png', 12, size=(100, 100))
    full = _noise(tmp_path / 'full.png', 13, size=(100, 100))
    ds = tmp_path / 'ds'
    ds.mkdir()
    rep = css.build_sheet(
        str(ds),
        {'name': 'P', 'description': 'x', 'body_plan': 'one tail', 'anchor_locks': {'full_body': full, 'side': side}},
        source='reference',
        reference_paths=[ref],
        preset='standard',
    )
    cells = {c['id']: c for c in rep['cells']}
    assert cells['side_right']['locked_view'] and cells['side_left']['locked_view']
    assert cells['side_right']['soft'] == [] and cells['side_right']['exempt'] == ['vlm:angle_match', 'vlm:whole_body']
    assert cells['side_right']['caption_mode'] == 'angle' and cells['side_right']['ok']
    assert set(cells['back']['soft']) == {'vlm:angle_match', 'vlm:whole_body'} and not cells['back'].get('locked_view')
    # the regen ladder re-rendered the flagged rotations, never the locked copies
    assert 'cell_07_r1.png' in edits and not any(n.startswith(('cell_03_r', 'cell_04_r')) for n in edits)
    # reclassify keeps the exemption
    rep2 = css.reclassify(str(ds), rejudge_hard=False)
    c4 = next(c for c in rep2['cells'] if c['id'] == 'side_right')
    assert c4['soft'] == [] and c4['caption_mode'] == 'angle'


# ── anchor-agreement gate (2026-08-26) ───────────────────────────────────────
# Two operator locks that disagree about an appendage split the sheet into two
# families and no per-cell check can see it: every cell is faithful to the anchor
# it came from. Each question is asked of ONE lock and the answers compared in
# code — comparing the panels in the prompt was measured useless (a front and a
# side view really do differ, so "same angle in both?" answered no every time).


def _pair_locks(tmp_path):
    (tmp_path / 'anchors').mkdir(exist_ok=True)
    return (_noise(tmp_path / 'pf.png', 21, size=(100, 100)), _noise(tmp_path / 'ps.png', 22, size=(100, 100)))


def _panel_judge(front_answers, side_answers, *, error_ids=()):
    """Judge that answers each single-image job from a per-lock answer map."""

    def fake(jobs, *, offload=True, log_fn=None):
        out = {}
        for j in jobs:
            ans = front_answers if j['key'] == 'front' else side_answers
            vds = []
            for i in j['items']:
                rec = {'id': i['id'], 'answer': ans.get(i['id'], 'yes'), 'severity': 'critical'}
                if i['id'] in error_ids:
                    rec['error'] = 'worker died'
                vds.append(rec)
            out[j['key']] = {
                'judged': True,
                'ok': True,
                'flags': [],
                'criticals': [],
                'majors': [],
                'verdicts': vds,
                'tier': 'fake',
            }
        return out

    return fake


BP_TAIL = 'a ball-shaped body; one long banded tail; two feet'


@needs_checklists
def test_pair_items_selects_templates_by_body_plan():
    assert cj.pair_items('') == []
    # a plan naming no covered part asks nothing rather than asking about a tail
    assert cj.pair_items('a body with two arms and two feet') == []
    assert [i['id'] for i in cj.pair_items(BP_TAIL)] == ['tail_present', 'tail_long', 'tail_banded']
    assert [i['id'] for i in cj.pair_items('a lizard with two wings')] == ['wings_present', 'wings_spread']
    # every question is asked of one panel, so none carries an `expected` answer
    assert not any('expected' in i for i in cj.pair_items(BP_TAIL))


@needs_checklists
def test_anchor_agreement_flags_a_shorter_tail_on_one_lock(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYG_CREATURE_VLM', '1')
    a, b = _pair_locks(tmp_path)
    monkeypatch.setattr(
        cj,
        'judge_batch',
        _panel_judge(
            {'tail_present': 'yes', 'tail_long': 'yes', 'tail_banded': 'yes'},
            {'tail_present': 'yes', 'tail_long': 'no', 'tail_banded': 'yes'},
        ),
    )
    res = css.check_anchor_agreement(a, b, BP_TAIL, str(tmp_path), lambda _m: None)
    assert res['judged'] and res['ok'] is False and res['disagree'] == ['tail_long']
    assert os.path.isfile(res['strip'])


@needs_checklists
def test_anchor_agreement_passes_matching_locks(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYG_CREATURE_VLM', '1')
    a, b = _pair_locks(tmp_path)
    same = {'tail_present': 'yes', 'tail_long': 'yes', 'tail_banded': 'yes'}
    monkeypatch.setattr(cj, 'judge_batch', _panel_judge(same, dict(same)))
    res = css.check_anchor_agreement(a, b, BP_TAIL, str(tmp_path), lambda _m: None)
    assert res['judged'] and res['ok'] is True and res['disagree'] == []
    assert res['asked'] == ['tail_present', 'tail_long', 'tail_banded']


def test_anchor_agreement_skips_without_a_covered_part(tmp_path, monkeypatch):
    a, b = _pair_locks(tmp_path)
    called = []
    monkeypatch.setattr(cj, 'judge_batch', lambda *a_, **k: called.append(1) or {})
    assert css.check_anchor_agreement(a, b, '', str(tmp_path), lambda _m: None) is None
    assert css.check_anchor_agreement(a, b, 'a body and two feet', str(tmp_path), lambda _m: None) is None
    assert not called


@needs_checklists
def test_anchor_agreement_ignores_errored_questions(tmp_path, monkeypatch):
    """An errored answer is not evidence of disagreement — it is no evidence."""
    monkeypatch.setenv('ZYG_CREATURE_VLM', '1')
    a, b = _pair_locks(tmp_path)
    monkeypatch.setattr(
        cj,
        'judge_batch',
        _panel_judge(
            {'tail_present': 'yes', 'tail_long': 'yes', 'tail_banded': 'yes'},
            {'tail_present': 'yes', 'tail_long': 'no', 'tail_banded': 'yes'},
            error_ids=('tail_long',),
        ),
    )
    res = css.check_anchor_agreement(a, b, BP_TAIL, str(tmp_path), lambda _m: None)
    assert res['ok'] is True and 'tail_long' not in res['asked'] and res['errors'] == 1


@needs_checklists
def test_anchor_agreement_all_errors_is_not_a_verdict(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYG_CREATURE_VLM', '1')
    a, b = _pair_locks(tmp_path)
    monkeypatch.setattr(cj, 'judge_batch', _panel_judge({}, {}, error_ids=('tail_present', 'tail_long', 'tail_banded')))
    res = css.check_anchor_agreement(a, b, BP_TAIL, str(tmp_path), lambda _m: None)
    assert res['ok'] is None and res['judged'] is False


@needs_checklists
def test_anchor_agreement_offline_judge_is_not_a_verdict(tmp_path, monkeypatch):
    a, b = _pair_locks(tmp_path)
    monkeypatch.setattr(
        cj, 'judge_batch', lambda jobs, **k: {j['key']: {'judged': False, 'ok': True, 'verdicts': []} for j in jobs}
    )
    res = css.check_anchor_agreement(a, b, BP_TAIL, str(tmp_path), lambda _m: None)
    assert res['ok'] is None and res['judged'] is False


def test_conform_variants_defaults_to_no_camera_move(tmp_path, monkeypatch):
    """conform_variants edits in place (angles LoRA off) unless told otherwise —
    a rotation needs 1.0 or the creature under-rotates."""
    scales = []

    def spy(ref, instruction, dest, seed, log, **kw):
        scales.append(kw.get('angles_scale'))
        return _fake_edit(tmp_path)(ref, instruction, dest, seed, log, **kw)

    monkeypatch.setattr(css, '_edit', spy)
    monkeypatch.setattr(
        cj,
        'judge_batch',
        lambda jobs, **k: {
            j['key']: {
                'judged': True,
                'ok': True,
                'flags': [],
                'criticals': [],
                'majors': [],
                'verdicts': [{'id': i['id'], 'answer': 'yes', 'ok': True, 'severity': 'major'} for i in j['items']],
                'tier': 'fake',
            }
            for j in jobs
        },
    )
    src = _noise(tmp_path / 'src.png', 31, size=(100, 100))
    ident = _noise(tmp_path / 'id.png', 32, size=(100, 100))
    css.conform_variants(
        src, 'one tail', str(tmp_path / 'o1'), ident, lambda _m: None, variants=[('T', 'do a thing')], seeds=1
    )
    assert scales == [0.0]
    scales.clear()
    css.conform_variants(
        src,
        'one tail',
        str(tmp_path / 'o2'),
        ident,
        lambda _m: None,
        variants=[('T', 'rotate 90')],
        seeds=1,
        angles_scale=1.0,
    )
    assert scales == [1.0]
