#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Angle plan, options/stages, checklists, image checks, and the sheet built with fake
renderers.

Moved verbatim out of tests/test_creature_sheet.py when it became this package.
"""

from .common import Image, cid, cj, css, csvc, cts, needs_checklists, needs_imagehash, os, pytest

from .common import _isolate_review_cards  # noqa: F401  autouse fixture, see common.py

# ── angle plan ───────────────────────────────────────────────────────────────


def test_angle_plan_shape():
    std = css.angle_plan('standard')
    cmp = css.angle_plan('compact')
    assert len(std) == 16 and len(cmp) == 8
    ids = [a['id'] for a in std]
    assert len(set(ids)) == len(ids)
    assert std[0].get('anchor') is True and std[0]['instruction'] is None
    for a in std[1:]:
        assert a['instruction'] and a['desc'], a['id']
        assert not a.get('anchor')
    for a in std:
        assert a['band'] in cid.BANDS, a['band']
        assert a['kind'] in ('body', 'head', 'wide', 'detail')
    assert cmp[0]['id'] == 'front_full'


def test_instructions_never_say_tilt():
    # "tilt" made Qwen roll the FRAME (human sheet cell_30 upside-down, 2026-07-16)
    for a in css.ANGLES:
        if a['instruction']:
            assert 'tilt' not in a['instruction'].lower(), a['id']


# ── options / stages ─────────────────────────────────────────────────────────


def test_normalize_options():
    o = cts.normalize_options({'source': 'photo', 'angles': 'compact', 'review_gate': '0'})
    assert o == {'source': 'reference', 'angles': 'compact', 'review_gate': False}
    o = cts.normalize_options({'source': 'text'})
    assert o['source'] == 'scratch' and o['review_gate'] is True and o['angles'] == 'standard'
    o = cts.normalize_options(None)
    assert o['source'] == '' and o['review_gate'] is True


def test_stage_keys_cover_every_stage():
    keys = [csvc._creature_stage_key(s) for s in cts.STAGES_ORDER]
    assert keys == [
        'creature_brief',
        'anchor',
        'sheet',
        'sheet_qc',
        'sheet_review',
        'captions',
        'lora_training',
        'preview_render',
    ]
    for k in keys:
        assert k in csvc.CREATURE_STAGE_ORDER
    # legacy May-2026 state files still derive
    assert csvc._creature_stage_key('Reference Image Generation') == 'reference_gen'
    assert (
        csvc._creature_derive_pipeline_stage({'status': 'awaiting_review', 'stage': 'sheet_review'}) == 'sheet_review'
    )
    assert csvc._creature_derive_pipeline_stage({'status': 'running', 'current_stage': 'Sheet QC'}) == 'sheet_qc'
    assert csvc._creature_derive_pipeline_stage({'status': 'rejected'}) == 'done'


# ── checklists ───────────────────────────────────────────────────────────────


@needs_checklists
def test_checklists_present_and_substituted():
    cell = cj.load_items(cj.CELL_CHECKLIST)
    anc = cj.load_items(cj.ANCHOR_CHECKLIST)
    assert cell and anc
    body = cj.cell_items('a top-down view', kind='body', base=cell)
    head = cj.cell_items('a close-up', kind='head', base=cell)
    ids_body = {i['id'] for i in body}
    ids_head = {i['id'] for i in head}
    assert 'whole_body' in ids_body and 'whole_body' not in ids_head
    q = next(i for i in body if i['id'] == 'angle_match')['question']
    assert 'a top-down view' in q and '{angle_desc}' not in q
    assert {'same_creature', 'single_subject', 'no_human'} <= ids_body
    back = {i['id'] for i in cj.cell_items('behind', kind='body', band='back', base=cell)}
    front = {i['id'] for i in cj.cell_items('front', kind='body', band='front', base=cell)}
    assert 'same_creature_back' in back and 'same_creature' not in back
    assert 'same_creature' in front and 'same_creature_back' not in front
    for it in body:
        assert it['expected'] in ('yes', 'no')
    a_no_brief = cj.anchor_items('', want_full_body=False, base=anc)
    assert not any(i['id'] in ('matches_brief', 'whole_body') for i in a_no_brief)
    a_brief = cj.anchor_items('teal furry ball', base=anc)
    assert any('teal furry ball' in i['question'] for i in a_brief)


@needs_checklists
def test_judge_offline_never_fails_a_cell(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYG_CREATURE_VLM', '0')
    img = tmp_path / 'x.png'
    Image.new('RGB', (64, 64), (200, 30, 30)).save(img)
    out = cj.judge_batch([{'key': 'k', 'image': str(img), 'items': cj.cell_items('x'), 'preamble': ''}])
    assert out['k']['judged'] is False and out['k']['ok'] is True and out['k']['flags'] == []


def test_judge_private_dependencies_exist():
    VI = pytest.importorskip('vlm_inspector')
    for name in ('_run_worker', '_aggregate', '_downshift', 'model_for', 'TIERS', 'shutdown_workers', 'available'):
        assert hasattr(VI, name), name
    assert 'resident' in VI.TIERS and 'boundary' in VI.TIERS


# ── image checks ─────────────────────────────────────────────────────────────


def _noise(path, seed, size=(256, 256)):
    import random

    rnd = random.Random(seed)
    im = Image.new('RGB', size)
    px = im.load()
    for y in range(size[1]):
        for x in range(size[0]):
            px[x, y] = (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
    im.save(path)
    return str(path)


@needs_imagehash
def test_structural_check(tmp_path):
    blank = tmp_path / 'blank.png'
    Image.new('RGB', (128, 128), (40, 40, 40)).save(blank)
    r = css.structural_check(str(blank))
    assert 'blank_frame' in r['reasons'] and not r['ok']
    a = _noise(tmp_path / 'a.png', 1)
    b = _noise(tmp_path / 'b.png', 2)
    same = tmp_path / 'same.png'
    Image.open(a).save(same)
    r = css.structural_check(str(same), a, expect_change=True)
    assert 'unchanged_from_anchor' in r['reasons']
    r = css.structural_check(str(same), a, expect_change=False)
    assert r['ok']
    r = css.structural_check(b, a, expect_change=True, siblings=[a])
    assert r['ok'], r


def test_strip_and_sheet(tmp_path):
    a = _noise(tmp_path / 'a.png', 3)
    b = _noise(tmp_path / 'b.png', 4)
    strip = css.make_strip(a, b, str(tmp_path / 's.png'))
    w, h = Image.open(strip).size
    assert w > h and w >= 2 * 768
    cells = [
        {'path': a, 'label': 'front', 'ok': True, 'dino': 0.81, 'reasons': []},
        {'path': b, 'label': 'back', 'ok': False, 'dino': 0.12, 'reasons': ['identity_lost']},
        {'path': None, 'label': 'missing', 'ok': False, 'dino': None, 'reasons': ['render_failed']},
    ]
    out = css.stitch_sheet(
        cells, str(tmp_path / 'sheet.png'), cols=2, cell_px=128, title='t', judge_note='JUDGE OFFLINE'
    )
    assert os.path.isfile(out) and Image.open(out).size[0] == 2 * 128 + 3 * 12


def test_identity_verdict_logic():
    v = cid.verdict(None, 'front')
    assert v['soft_ok'] and v['hard_ok'] and not v['measured']
    v = cid.verdict(0.10, 'back')
    assert not v['hard_ok']
    v = cid.verdict(0.30, 'back')
    assert v['hard_ok'] and v['soft_ok']
    v = cid.verdict(0.30, 'front')
    assert v['hard_ok'] and not v['soft_ok']


def test_identity_metric_if_cached(tmp_path):
    if not cid._load():
        pytest.skip(f'dinov2 not cached: {cid.unavailable_reason()}')
    a = _noise(tmp_path / 'a.png', 5)
    s = cid.similarity(a, a)
    assert s is not None and s > 0.95


# ── the sheet with fake renderers ────────────────────────────────────────────


def _fake_edit(tmp_root):
    def _edit(ref, instruction, dest, seed, log, size=1024, style_hint='', **kw):
        # a distinct image per (instruction, seed) so phash/duplicate checks pass
        _noise(dest, hash((instruction, seed)) & 0xFFFF, size=(96, 96))
        return True

    return _edit


def test_build_sheet_reference_mode(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYG_CREATURE_VLM', '0')
    monkeypatch.setenv('ZYG_CREATURE_DINO', '0')
    monkeypatch.setattr(css, '_edit', _fake_edit(tmp_path))
    ref = _noise(tmp_path / 'ref.png', 9, size=(120, 80))
    ds = tmp_path / 'ds'
    ds.mkdir()
    rep = css.build_sheet(
        str(ds),
        {'name': 'Puff', 'description': 'teal furry ball'},
        source='reference',
        reference_paths=[ref],
        preset='compact',
    )
    assert rep['cell_count'] == 8 and rep['pass_count'] == 8
    assert os.path.isfile(rep['sheet_path']) and os.path.isfile(rep['sheet_root_copy'])
    assert rep['anchors']['identity']['from'] == 'reference'
    # judge offline: the ref was not judged whole-body → a full-body anchor is derived by edit
    assert rep['anchors']['full_body']['from'] == 'edit_of_reference'
    assert rep['judged_any'] is False
    rep2 = css.load_report(str(ds))
    assert rep2['cell_count'] == 8
    tiles = css.training_tiles(
        rep2, str(ds), 'ZYG_CREATURE_ABC123', {'description': 'teal furry ball', 'species': 'pufferball'}
    )
    assert len(tiles) == 9  # 8 cells + 1 reference
    cap = open(os.path.join(str(ds), 'training', 'sheet_00.txt')).read()
    assert cap.startswith('ZYG_CREATURE_ABC123, teal furry ball, pufferball, front view, full body')


def test_build_sheet_scratch_mode(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYG_CREATURE_VLM', '0')
    monkeypatch.setenv('ZYG_CREATURE_DINO', '0')
    monkeypatch.setattr(css, '_edit', _fake_edit(tmp_path))
    monkeypatch.setattr(
        css, '_txt2img', lambda prompt, dest, seed, log, size=1024, family=None: bool(_noise(dest, seed, size=(96, 96)))
    )
    ds = tmp_path / 'ds'
    ds.mkdir()
    rep = css.build_sheet(str(ds), {'name': 'Dr', 'description': 'red dragon'}, source='scratch', preset='compact')
    assert rep['anchors']['full_body']['from'] == 'klein_txt2img'
    assert len(rep['anchors']['full_body']['candidates']) == css.SCRATCH_ANCHOR_SEEDS
    assert rep['pass_count'] == 8


def test_scratch_refuses_flux(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYG_CREATURE_T2I_FAMILY', 'flux')
    with pytest.raises(RuntimeError):
        css._txt2img('x', str(tmp_path / 'o.png'), 1, lambda m: None)
