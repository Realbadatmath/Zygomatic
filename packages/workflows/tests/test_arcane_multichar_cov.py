# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline coverage for ``zyg_workflows.arcane_multichar``: every ComfyUI / bible / QC / WAN
dependency is faked via the suite's ``stub_module`` fixture, so the whole multichar composition
chain runs on tiny PIL images under ``tmp_path``."""

import os
import re
import types

import numpy as np
import pytest
from PIL import Image

from zyg_workflows import arcane_multichar as MOD
from zyg_workflows.qc_contract import QCBlocked


class FakeComfy:
    """Records submitted graphs and answers with freshly written PNGs."""

    def __init__(self, outdir):
        self.outdir = str(outdir)
        self.graphs, self.staged = [], []
        self.size = (64, 48)
        self.outs = self.submit_exc = self.free_exc = None
        self.free_calls = 0

    def submit(self, graph, timeout_s=None):
        self.graphs.append(graph)
        if self.submit_exc is not None:
            raise self.submit_exc
        if self.outs is not None:
            return self.outs
        p = os.path.join(self.outdir, f'comfy_{len(self.graphs)}.png')
        Image.new('RGB', self.size, (30, 40, 50)).save(p)
        return [p]

    def stage_input_image(self, path):
        self.staged.append(path)
        return os.path.basename(path)

    def free_vram(self, unload_models=False, free_memory=False):
        self.free_calls += 1
        if self.free_exc is not None:
            raise self.free_exc


def make_embed(found, img_wh=(32, 48), bbox=(5, 5, 20, 30)):
    """``identity_qc_service.embed_images`` fake: a face in every column index of *found*."""

    def embed_images(paths, log_fn=None):
        p = paths[0]
        i = int(re.search(r'_mcreg_(\d+)', p).group(1))
        if i not in found:
            return {p: {'face_detected': False, 'bbox': None}}
        return {p: {'face_detected': True, 'bbox': list(bbox), 'img_w': img_wh[0], 'img_h': img_wh[1]}}

    return embed_images


def make_restyle(ok=True, exc=None):
    def restyle(char_id, prof, src, out, seed=0, log_fn=None):
        if exc is not None:
            raise exc
        if ok:
            Image.new('RGB', (40, 40), (200, 10, 10)).save(out)
        return ok

    return types.SimpleNamespace(
        load_profile=lambda name: {'restyle': {'recipe': name}},
        depth_controlnet_arcane_restyle=restyle,
    )


_LEDGER = {'found': 3, 'not_found': 0, 'not_detectable': 1, 'unmeasurable': 0}
_PER_CHAR = {'cosine': 0.4, 'cosine_p10': 0.2, 'spread': 0.1, 'pass_frac': 0.8, 'reason': 'ok', 'ledger': _LEDGER}


class FakeDebugRun:
    """Stands in for ``pipeline_debug.DebugRun``."""

    still_q = {'checks': [{'ok': False, 'check': 'exposure', 'note': 'hot'}, {'ok': True}]}
    clip_q = {
        'checks': [{'ok': False, 'check': 'motion', 'note': 'static'}],
        'identity': {'per_char': {'abel': _PER_CHAR}, 'sidecar': 'identity.json'},
    }
    clip_exc = None
    still_exc = None

    def __init__(self, out_dir, name=None):
        self.out_dir, self.stages = out_dir, []

    def stage(self, name, params=None):
        self.stages.append(name)

    def snapshot(self, name, path):
        return path

    def qc_still(self, name, path, char_regions=None, n_people=None):
        if self.still_exc is not None:
            raise self.still_exc
        return dict(self.still_q)

    def qc_clip(self, name, clip, char_regions=None, still_path=None, identity_chars=None):
        if self.clip_exc is not None:
            raise self.clip_exc
        return dict(self.clip_q)

    def finish(self):
        return {'ok': True}


def _mp4(path):
    open(path, 'wb').close()
    return path


def make_wan(out_dir, empty=False):
    def generate(items, outd, **kw):
        return [] if empty else [{'path': _mp4(os.path.join(str(out_dir), 'clip.mp4'))}]

    return types.SimpleNamespace(generate=generate)


def bible(lora='', **ident):
    """A ``character_bible_service`` fake whose profile carries a sanitizable clothing line."""
    p = {
        'identity': dict({'sex': 'male', 'age': 42}, **ident),
        'default_presentation': {'default_clothing': "a merchant's dress with a gown"},
        'conditioning': {'sdxl_lora_path': lora},
    }
    return types.SimpleNamespace(load=lambda cid: p)


@pytest.fixture
def cc(tmp_path, stub_module):
    (tmp_path / 'comfy').mkdir()
    fake = FakeComfy(tmp_path / 'comfy')
    stub_module('_comfy_client', fake)
    return fake


@pytest.fixture
def logs():
    return []


def _img(path, size=(64, 48), colour=(20, 30, 40)):
    Image.new('RGB', size, colour).save(path)
    return str(path)


@pytest.mark.parametrize(
    ('raw', 'expect'),
    [
        ("merchant's son's dress", 'attire'),
        ("merchant's dress", 'attire'),
        ('a plain dress', 'a plain attire'),
        ('silk GOWN', 'silk coat'),
        ('  doublet  ', 'doublet'),
        ('', ''),
        (None, ''),
    ],
)
def test_sanitize_clothing(raw, expect):
    assert MOD._sanitize_clothing(raw) == expect


def test_log_noop_and_feather():
    assert MOD._log_noop('anything') is None
    m = MOD._feather(40, 30)
    assert (m.mode, m.size) == ('L', (40, 30))
    arr = np.asarray(m, dtype=np.float32)
    assert arr[15, 20] > arr[0, 0]


def test_free_calls_comfy(cc, logs):
    MOD._free(logs.append)
    assert cc.free_calls == 1
    assert logs == []


def test_free_logs_failure_and_swallows_without_log(cc, logs):
    cc.free_exc = RuntimeError('no server')
    MOD._free(logs.append)
    assert any('free_vram skipped' in m for m in logs)
    assert MOD._free() is None


def test_char_desc_canon_first(stub_module):
    stub_module('character_bible_service', bible(lora='/x/abel.safetensors'))
    stub_module(
        'canon_service',
        types.SimpleNamespace(canon_phrase=lambda c: 'weathered sailor', canon_negative=lambda c: 'no beard'),
    )
    d = MOD._char_desc('abel-1234', shot='full-body')
    assert d['region_prompt'].startswith('weathered sailor')
    assert 'full body' in d['region_prompt']
    assert d['canon_negative'] == 'no beard'
    assert d['cloth'] == 'a attire with a coat'
    assert d['noun'] == 'man'
    assert d['lora'] == '/x/abel.safetensors'


def test_char_desc_without_canon_phrase(stub_module):
    stub_module('character_bible_service', bible())
    stub_module('canon_service', types.SimpleNamespace(canon_phrase=lambda c: '', canon_negative=lambda c: 'x'))
    d = MOD._char_desc('abel', shot='unknown-shot')
    assert d['region_prompt'].startswith('a 42 year old male man')
    assert 'waist up' in d['region_prompt']
    assert d['canon_negative'] == ''


def test_char_desc_canon_import_failure(stub_module):
    stub_module('character_bible_service', bible(sex='female', age=15))
    stub_module('canon_service', None)
    d = MOD._char_desc('nel')
    assert d['noun'] == 'teenage girl'
    assert 'teenage girl' in d['region_prompt']


def test_char_desc_teen_boy_and_bad_age(stub_module):
    stub_module('canon_service', None)
    stub_module('character_bible_service', bible(age=12))
    assert MOD._char_desc('kid')['noun'] == 'teenage boy'
    stub_module('character_bible_service', bible(age='ancient'))
    assert MOD._char_desc('odd')['noun'] == 'man'


def test_char_desc_empty_profile(stub_module):
    stub_module('character_bible_service', types.SimpleNamespace(load=lambda cid: None))
    stub_module('canon_service', None)
    d = MOD._char_desc('ghost')
    assert d['cid'] == 'ghost'
    assert (d['sex'], d['age'], d['cloth'], d['noun'], d['lora']) == ('male', None, '', 'man', '')
    assert d['region_prompt'] == 'a None year old male man, , waist up'


DESCS = [{'region_prompt': 'first man'}, {'region_prompt': 'second man'}]


def test_base_plate_default_graph(cc, tmp_path, logs):
    out = tmp_path / 'plate.png'
    assert MOD._base_plate(DESCS, 'in a hall', str(out), 7, 1152, 832, logs.append) == str(out)
    assert out.is_file()
    g = cc.graphs[0]
    assert g['90']['inputs']['text'].startswith('2 men standing together side by side')
    assert '91' not in g  # bg_strength == 1.0 → no background area node
    assert g['68']['inputs']['conditioning_2'] == ['90', 0]
    assert g['41']['inputs']['negative'] == ['95', 0]
    assert g['30']['inputs']['strength'] == 1.15
    assert (g['20']['inputs']['text'], g['21']['inputs']['text']) == ('first man', 'second man')
    assert '61' in g  # the two columns were combined


def test_base_plate_overrides_and_region_negatives(cc, tmp_path, logs):
    out = tmp_path / 'plate2.png'
    MOD._base_plate(
        DESCS,
        'at a table',
        str(out),
        11,
        1152,
        832,
        logs.append,
        shot='three-quarter',
        bg_prompt='two men seated at a table',
        region_prompts=['father writing', ''],
        region_negatives=['quill', None],
        region_strength=1.0,
        bg_strength=0.7,
    )
    g = cc.graphs[0]
    assert g['90']['inputs']['text'] == 'two men seated at a table'
    assert g['91']['inputs']['strength'] == 0.7
    assert g['68']['inputs']['conditioning_2'] == ['91', 0]
    assert g['20']['inputs']['text'] == 'father writing'
    assert g['21']['inputs']['text'] == 'second man'  # falsy override → the desc's own prompt
    assert g['70']['inputs']['text'] == 'quill'
    assert g['41']['inputs']['negative'] == ['96', 0]
    assert '71' not in g  # second person had no region negative


def test_repair_hands_success(cc, tmp_path, logs):
    src = _img(tmp_path / 'src.png')
    out = tmp_path / 'fixed.png'
    assert MOD._repair_hands(src, str(out), 3, logs.append) == str(out)
    assert out.is_file()
    assert cc.staged == [src]
    assert any('hand-repair pass done' in m for m in logs)
    assert cc.graphs[0]['3']['inputs']['model_name'] == 'bbox/hand_yolov8s.pt'


def test_repair_hands_no_output_copies_src(cc, tmp_path, logs):
    cc.outs = []
    src = _img(tmp_path / 'src.png')
    out = tmp_path / 'kept.png'
    MOD._repair_hands(src, str(out), 3, logs.append)
    assert out.is_file()
    assert any('produced no output' in m for m in logs)


def test_repair_hands_failure_is_fail_safe(cc, tmp_path, logs):
    cc.submit_exc = RuntimeError('comfy down')
    src = _img(tmp_path / 'same.png')
    MOD._repair_hands(src, src, 3, logs.append)  # src == out → no copy branch
    assert any('hand-repair failed' in m for m in logs)


def test_soften_highlights_without_clipping(tmp_path, logs):
    src = _img(tmp_path / 'dark.png', colour=(10, 10, 10))
    out = tmp_path / 'dark_out.png'
    assert MOD.soften_highlights(src, str(out), log_fn=logs.append) == str(out)
    assert out.is_file()
    assert logs == []
    flat = _img(tmp_path / 'flat.png', colour=(0, 0, 0))
    before = os.path.getmtime(flat)
    assert MOD.soften_highlights(flat) == flat
    assert os.path.getmtime(flat) == before  # in place and nothing clips → untouched


def test_soften_highlights_rolls_off_hot_spot(tmp_path, logs):
    im = Image.new('RGB', (96, 96), (40, 40, 40))
    im.paste(Image.new('RGB', (60, 60), (255, 255, 255)), (18, 18))
    src = tmp_path / 'hot.png'
    im.save(src)
    out = tmp_path / 'toned.png'
    MOD.soften_highlights(str(src), str(out), log_fn=logs.append)
    before = np.asarray(Image.open(src).convert('RGB'), dtype=np.float32)
    after = np.asarray(Image.open(out).convert('RGB'), dtype=np.float32)
    assert after[48, 48].max() < before[48, 48].max()
    assert any('clipped px' in m for m in logs)


def test_arcane_full_resizes_back(cc, tmp_path, logs):
    src = _img(tmp_path / 'base.png', size=(80, 60))
    out = tmp_path / 'styled.png'
    cc.size = (32, 24)  # comfy answers at another size → must be resized back
    assert MOD._arcane_full(src, str(out), 'a hall', 5, logs.append) == str(out)
    with Image.open(out) as res:
        assert res.size == (80, 60)
    g = cc.graphs[0]
    assert g['11']['inputs']['lora_name'] == 'style_arcane.safetensors'
    assert 'a hall' in g['20']['inputs']['text']
    assert g['15']['inputs']['ckpt_name'] == MOD._DEPTH_CKPT


def test_face_boxes_one_found_one_missing(tmp_path, stub_module, logs):
    stub_module('identity_qc_service', types.SimpleNamespace(embed_images=make_embed({0}, img_wh=(60, 80))))
    p = _img(tmp_path / 'plate.png', size=(120, 80))
    with Image.open(p) as im:
        boxes = MOD._face_boxes(im, 2, logs.append)
    assert boxes[1] is None
    x0, y0, x1, y1 = boxes[0]
    assert 0 <= x0 < x1 <= 120 and 0 <= y0 < y1 <= 80
    assert (tmp_path / '_mcreg_0.png').is_file()


def test_face_boxes_without_filename_uses_tmp_dir(tmp_path, monkeypatch, stub_module, logs):
    stub_module('identity_qc_service', types.SimpleNamespace(embed_images=make_embed(set())))
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    monkeypatch.setattr(MOD, 'tmp_dir', lambda sub='': scratch)
    assert MOD._face_boxes(Image.new('RGB', (40, 40), (1, 2, 3)), 1, logs.append) == [None]


def test_identity_pass_composites_face(tmp_path, stub_module, logs):
    stub_module('arcane_restyle', make_restyle(ok=True))
    base = _img(tmp_path / 'photo.png')
    plate = _img(tmp_path / 'plate.png', colour=(0, 0, 0))
    before = np.asarray(Image.open(plate).convert('RGB'), dtype=np.float32).sum()
    assert MOD._identity_pass(base, plate, (4, 4, 40, 40), 'abel-1234', {}, str(tmp_path), logs.append) == plate
    after = np.asarray(Image.open(plate).convert('RGB'), dtype=np.float32).sum()
    assert after > before
    assert (tmp_path / '_mccrop_abel-123.png').is_file()


def test_identity_pass_restyle_declined(tmp_path, stub_module, logs):
    stub_module('arcane_restyle', make_restyle(ok=False))
    base = _img(tmp_path / 'photo.png')
    plate = _img(tmp_path / 'plate.png')
    assert MOD._identity_pass(base, plate, (0, 0, 32, 24), 'cornelis', {}, str(tmp_path), logs.append) == plate
    assert any('identity pass FAILED' in m for m in logs)


@pytest.fixture
def still_world(tmp_path, cc, stub_module):
    """Everything ``generate_multichar_still`` needs, with a real LoRA file on disk."""
    lora = tmp_path / 'abel.safetensors'
    lora.write_bytes(b'\0')
    stub_module('character_bible_service', bible(lora=str(lora)))
    stub_module('canon_service', types.SimpleNamespace(canon_phrase=lambda c: '', canon_negative=lambda c: f'not {c}'))
    stub_module('identity_qc_service', types.SimpleNamespace(embed_images=make_embed({0})))
    stub_module('arcane_restyle', make_restyle(ok=True))
    return types.SimpleNamespace(cc=cc, stub=stub_module)


@pytest.mark.parametrize('ids', [[], ['only', None]])
def test_still_requires_two_characters(tmp_path, logs, ids):
    assert MOD.generate_multichar_still(ids, 'hall', str(tmp_path / 'o.png'), log_fn=logs.append) is None
    assert any('need >=2' in m for m in logs)


def test_still_aborts_without_lora(tmp_path, cc, stub_module, logs):
    stub_module('character_bible_service', bible(lora=''))
    stub_module('canon_service', None)
    stub_module('arcane_restyle', make_restyle())
    assert MOD.generate_multichar_still(['a', 'b'], 'hall', str(tmp_path / 'o.png'), log_fn=logs.append) is None
    assert any('has no SDXL LoRA' in m for m in logs)


def test_still_full_run(still_world, tmp_path, logs):
    out = tmp_path / 'work' / 'still.png'
    ids = ['abel-1234', 'cornelis-9', 'nel-77', 'extra-1']
    kw = dict(seed=7, W=64, H=48, log_fn=logs.append, repair_hands=True)
    got = MOD.generate_multichar_still(ids, 'in a 1672 interior', str(out), **kw)
    assert got == str(out)
    assert out.is_file()
    assert (tmp_path / 'work' / '_mc_base.png').is_file()
    joined = '\n'.join(logs)
    assert 'capping 4' in joined
    assert 'identity locked: abel-123' in joined
    assert 'no face found for cornelis' in joined
    assert 'DONE' in joined
    assert still_world.cc.free_calls >= 4


def test_still_identity_pass_error_is_caught(still_world, tmp_path, logs):
    still_world.stub('arcane_restyle', make_restyle(exc=RuntimeError('restyle blew up')))
    out = tmp_path / 'w2' / 'still.png'
    assert MOD.generate_multichar_still(['a', 'b'], 'hall', str(out), W=64, H=48, log_fn=logs.append) == str(out)
    assert any('identity pass errored' in m for m in logs)


def test_relock_identity_no_ids(tmp_path, cc, stub_module):
    stub_module('arcane_restyle', make_restyle())
    plate = _img(tmp_path / 'p.png')
    assert MOD.relock_identity(plate, [None, '']) == plate


def test_relock_identity_relocks_and_skips(tmp_path, cc, stub_module, logs):
    stub_module('arcane_restyle', make_restyle(ok=True))
    stub_module('identity_qc_service', types.SimpleNamespace(embed_images=make_embed({0})))
    plate = _img(tmp_path / 'p.png')
    assert MOD.relock_identity(plate, ['abel-1234', 'nel-77'], log_fn=logs.append) == plate
    joined = '\n'.join(logs)
    assert 'identity re-locked: abel-123' in joined
    assert 'no face found for nel-77' in joined


def test_relock_identity_failure_is_fail_safe(tmp_path, cc, stub_module, logs):
    stub_module('arcane_restyle', make_restyle(exc=OSError('crop gone')))
    stub_module('identity_qc_service', types.SimpleNamespace(embed_images=make_embed({0})))
    plate = _img(tmp_path / 'p.png')
    MOD.relock_identity(plate, ['abel'], log_fn=logs.append)
    assert any('[relock] failed for abel' in m for m in logs)


def test_relock_region_inpaints(cc, tmp_path, logs):
    plate = _img(tmp_path / 'plate.png', size=(80, 60))
    cc.size = (40, 30)  # forces the resize-back branch
    assert MOD.relock_region(plate, (0.1, 0.1, 0.5, 0.5), 'a clay pipe', log_fn=logs.append) == plate
    with Image.open(plate) as im:
        assert im.size == (80, 60)
    assert not os.path.exists(plate + '.relock_mask.png')
    g = cc.graphs[0]
    assert g['5']['inputs']['text'] == 'a clay pipe'
    assert g['6']['inputs']['text'].startswith('deformed')
    assert g['8']['inputs']['denoise'] == 0.55
    assert any('[region-lock] done' in m for m in logs)


def test_relock_region_no_output_keeps_plate(cc, tmp_path, logs):
    cc.outs = []
    plate = _img(tmp_path / 'plate.png')
    assert MOD.relock_region(plate, (0, 0, 1, 1), 'pipe', negative='blur', log_fn=logs.append) == plate
    assert logs == []


def test_relock_region_failure_is_fail_safe(cc, tmp_path, logs):
    cc.submit_exc = RuntimeError('inpaint down')
    plate = _img(tmp_path / 'plate.png')
    assert MOD.relock_region(plate, (0, 0, 1, 1), 'pipe', log_fn=logs.append) == plate
    assert any('[region-lock] failed' in m for m in logs)


@pytest.fixture
def clip_world(tmp_path, monkeypatch, stub_module):
    """Stub the still composition, the debug run, WAN and the set-lock."""
    FakeDebugRun.clip_exc = None
    FakeDebugRun.still_exc = None
    monkeypatch.setattr(MOD, 'generate_multichar_still', lambda ids, scene, out, **kw: _img(out))
    stub_module('pipeline_debug', types.SimpleNamespace(DebugRun=FakeDebugRun, set_active=lambda d: None))
    stub_module('wan_video_service', make_wan(tmp_path))
    stub_module(
        'wan_setlock',
        types.SimpleNamespace(lock_background=lambda clip, still, out, log_fn=None: _mp4(out)),
    )
    return types.SimpleNamespace(stub=stub_module, monkeypatch=monkeypatch)


def test_clip_full_run_with_setlock(clip_world, tmp_path, logs):
    kw = dict(log_fn=logs.append, lock_set=True, wan_prompt='the two men walk forward', steps=9)
    clip = MOD.generate_multichar_clip(['abel', 'cornelis'], 'in a hall', str(tmp_path / 'clipout'), **kw)
    assert clip.endswith('_setlocked.mp4')
    joined = '\n'.join(logs)
    assert 'QC-STILL FAIL' in joined
    assert 'QC-CLIP FAIL' in joined
    assert '[multichar][identity] abel: cos=0.4' in joined
    assert 'identity.json' in joined
    assert 'verdict PASS' in joined


def test_clip_reuses_still_and_default_prompt(clip_world, tmp_path, logs):
    out_dir = tmp_path / 'clip2'
    clip = MOD.generate_multichar_clip(
        ['abel', 'nel'],
        'at a quay',
        str(out_dir),
        still_path=_img(tmp_path / 'existing_still.png'),
        test_mode=False,
        log_fn=logs.append,
    )
    assert clip.endswith('clip.mp4')
    assert not clip.endswith('_setlocked.mp4')
    assert not (out_dir / 'multichar_still.png').exists()


def test_clip_identity_not_measured_and_setlock_failure(clip_world, tmp_path, logs, monkeypatch):
    monkeypatch.setattr(
        FakeDebugRun,
        'clip_q',
        {'checks': [], 'identity': {'measured': False, 'reason': 'no reference embedding'}},
    )
    clip_world.stub(
        'wan_setlock',
        types.SimpleNamespace(lock_background=lambda *a, **k: (_ for _ in ()).throw(RuntimeError('no ffmpeg'))),
    )
    clip = MOD.generate_multichar_clip(['abel'], 'hall', str(tmp_path / 'c3'), lock_set=True, log_fn=logs.append)
    assert clip.endswith('clip.mp4')
    joined = '\n'.join(logs)
    assert 'not measured: no reference embedding' in joined
    assert 'set-lock skipped' in joined


def test_clip_qc_blocked_propagates(clip_world, tmp_path, logs):
    FakeDebugRun.clip_exc = QCBlocked('face drift at mode=block')
    try:
        with pytest.raises(QCBlocked):
            MOD.generate_multichar_clip(['abel'], 'hall', str(tmp_path / 'c4'), log_fn=logs.append)
    finally:
        FakeDebugRun.clip_exc = None
    assert any('QC BLOCKED' in m for m in logs)


def test_clip_broken_qc_instruments_are_shrugged_off(clip_world, tmp_path, logs, monkeypatch):
    monkeypatch.setattr(FakeDebugRun, 'still_exc', RuntimeError('qc_still broken'))
    monkeypatch.setattr(FakeDebugRun, 'clip_exc', RuntimeError('qc_clip broken'))
    clip = MOD.generate_multichar_clip(['abel'], 'hall', str(tmp_path / 'c9'), log_fn=logs.append)
    assert clip.endswith('clip.mp4')
    assert not any('QC-STILL FAIL' in m for m in logs)


def test_clip_debug_import_failure_is_tolerated(clip_world, tmp_path, logs):
    clip_world.stub('pipeline_debug', None)
    clip = MOD.generate_multichar_clip(['abel'], 'hall', str(tmp_path / 'c5'), log_fn=logs.append)
    assert clip.endswith('clip.mp4')
    assert not any('QC-STILL' in m for m in logs)


def test_clip_still_failure_returns_none(clip_world, tmp_path, logs):
    clip_world.monkeypatch.setattr(MOD, 'generate_multichar_still', lambda *a, **k: None)
    assert MOD.generate_multichar_clip(['abel', 'nel'], 'hall', str(tmp_path / 'c6'), log_fn=logs.append) is None


def test_clip_wan_import_failure_returns_none(clip_world, tmp_path, logs):
    clip_world.stub('wan_video_service', None)
    assert MOD.generate_multichar_clip(['abel'], 'hall', str(tmp_path / 'c7'), log_fn=logs.append) is None
    assert any('wan import failed' in m for m in logs)


def test_clip_wan_produces_nothing(clip_world, tmp_path, logs):
    clip_world.stub('wan_video_service', make_wan(tmp_path, empty=True))
    assert MOD.generate_multichar_clip(['abel'], 'hall', str(tmp_path / 'c8'), log_fn=logs.append) is None
    assert any('wan produced no clip' in m for m in logs)
