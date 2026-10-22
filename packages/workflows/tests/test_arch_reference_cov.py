# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage tests for zyg_workflows.arch_reference — the reference model store.

An autouse fixture redirects the module's two root constants (REF_DIR,
PORTFOLIO_DIR) at tmp_path, so nothing here can write into the repo's tracked
data/ tree. Pillow is a declared dependency, so the image paths run for real;
the "no Pillow" branches are reached by stubbing the module's own `_pillow()`
or by hiding PIL from sys.modules.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys

import pytest
from PIL import Image

from zyg_workflows import arch_reference as mod


# ── helpers ──────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def roots(tmp_path, monkeypatch):
    ref, pf = tmp_path / 'ref', tmp_path / 'portfolio'
    ref.mkdir()
    pf.mkdir()
    monkeypatch.setattr(mod, 'REF_DIR', str(ref))
    monkeypatch.setattr(mod, 'PORTFOLIO_DIR', str(pf))
    return ref, pf


def _png(w: int = 6, h: int = 4, mode: str = 'RGB') -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (w, h), (10, 20, 30) if mode == 'RGB' else None).save(buf, 'PNG')
    return buf.getvalue()


def _url(raw: bytes, mime: str = 'image/png') -> str:
    return f'data:{mime};base64,' + base64.b64encode(raw).decode('ascii')


def _png_file(path, w: int = 30, h: int = 20) -> str:
    Image.new('RGB', (w, h), (200, 30, 30)).save(str(path), 'PNG')
    return str(path)


def _with_image():
    rec = mod.create('Clyde Ship', 'a ship')
    return rec['id'], mod.add_image(rec['id'], _url(_png()), 'bow.png', 'view_side', 'the bow')['id']


def _read(path) -> str:
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def _meta(**kw) -> dict:
    return {'built': '2026-09-23', 'engine': 'cycles', 'dims': '12x3x4', 'tris': 1234, **kw}


# ── slug / ids / numbers ─────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ('name', 'want'),
    [
        ('Clyde Ship', 'clyde-ship'),
        ('  MIXED__case 42 ', 'mixed-case-42'),
        ('', 'reference'),
        (None, 'reference'),
        ('!!!', 'reference'),
        ('Pont de Quebec', 'pont-de-quebec'),
    ],
)
def test_slug(name, want):
    assert mod.slug(name) == want


@pytest.mark.parametrize('bad', ['', None, 'xyz', 'abc', '../etc', 'A1B2C3', 'f' * 33])
def test_model_dir_rejects_bad_ids(bad):
    assert mod._mid_ok(bad) is False
    with pytest.raises(ValueError, match='bad reference model id'):
        mod.model_dir(bad)


@pytest.mark.parametrize(
    ('raw', 'want'), [('2.5', 2.5), (3, 3.0), (None, 0.0), ('nope', 0.0), (float('inf'), 0.0), (float('nan'), 0.0)]
)
def test_num(raw, want):
    assert mod._num(raw) == want


# ── CRUD lifecycle ───────────────────────────────────────────────────────────
def test_create_read_update_delete_roundtrip(roots):
    rec = mod.create('Clyde Ship', 'a ship')
    mid = rec['id']
    assert mod._mid_ok(mid) and mod.model_dir(mid) == os.path.join(str(roots[0]), mid)
    assert os.path.isdir(os.path.join(mod.model_dir(mid), 'images'))
    assert (rec['length_m'], rec['images'], rec['asset']) == (0.0, [], None)
    got = mod.read(mid)
    assert (got['name'], got['subject'], got['id']) == ('Clyde Ship', 'a ship', mid)

    up = mod.update(mid, {'name': 'Clyde', 'notes': 'n' * 5000, 'length_m': '12.345678', 'beam_m': -4})
    assert up['name'] == 'Clyde' and len(up['notes']) == 4000
    assert (up['length_m'], up['beam_m'], up['height_m']) == (12.3457, 0.0, 0.0)
    assert mod.update(mid, {})['name'] == 'Clyde'

    long_ = mod.create('x' * 500, 'y' * 500)
    assert (len(long_['name']), len(long_['subject'])) == (120, 120)
    assert mod.create('')['name'] == 'Untitled reference'

    assert mod.delete(mid) is True and mod.read(mid) is None
    assert mod.delete(mid) is False and mod.update(mid, {'name': 'nope'}) is None


def test_read_handles_broken_non_dict_and_sparse_records():
    rec = mod.create('Broken')
    path = mod._json_path(rec['id'])
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('{not json')
    assert mod.read(rec['id']) is None
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump([1, 2], fh)
    assert mod.read(rec['id']) is None
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump({'name': 'Sparse'}, fh)
    got = mod.read(rec['id'])
    assert (got['images'], got['asset'], got['id']) == ([], None, rec['id'])


def test_models_lists_only_real_models_newest_first(roots):
    a, b = mod.create('A'), mod.create('B')
    for rec, when in ((a, '2026-01-02T00:00:00'), (b, '2026-01-01T00:00:00')):
        stored = mod.read(rec['id'])
        stored['updated'] = when
        with open(mod._json_path(rec['id']), 'w', encoding='utf-8') as fh:
            json.dump(stored, fh)
    (roots[0] / 'not-a-model-id').mkdir()
    (roots[0] / 'ffffffffffff').write_text('a file, not a directory', encoding='utf-8')
    assert [r['id'] for r in mod.models()] == [a['id'], b['id']]


def test_models_and_root_index_survive_a_missing_root(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, 'REF_DIR', str(tmp_path / 'gone'))
    monkeypatch.setattr(mod, 'PORTFOLIO_DIR', str(tmp_path / 'gone'))
    assert mod.models() == []
    assert mod._pf_root_index() == ''


def test_model_bytes_counts_files_and_skips_unreadable_ones():
    mid = mod.create('Sized')['id']
    assert (first := mod.model_bytes(mid)) > 0
    images = os.path.join(mod.model_dir(mid), 'images')
    os.symlink(os.path.join(images, 'nothing-here'), os.path.join(images, 'dangle'))
    assert mod.model_bytes(mid) == first


# ── the current model ────────────────────────────────────────────────────────
def test_current_and_set_current():
    assert (mod.current(), mod._cur_id_raw()) == ('', '')
    mid = mod.create('Open me')['id']
    assert mod.set_current(mid) == mid
    assert (mod.current(), mod._cur_id_raw()) == (mid, mid)
    assert mod.set_current('') == ''
    assert mod.current() == ''
    with pytest.raises(ValueError, match='no such reference model'):
        mod.set_current('aaaaaaaaaaaa')


@pytest.mark.parametrize(
    ('body', 'raw'), [('{"id": "aaaaaaaaaaaa"}', 'aaaaaaaaaaaa'), ('{oops', ''), ('{"id": ""}', '')]
)
def test_current_ignores_stale_or_unreadable_json(roots, body, raw):
    (roots[0] / 'current.json').write_text(body, encoding='utf-8')
    assert mod.current() == ''
    assert mod._cur_id_raw() == raw


def test_delete_releases_the_current_model_and_its_portfolio():
    mid = mod.create('Doomed')['id']
    mod.set_current(mid)
    pf = mod.portfolio_dir(mod.read(mid))
    os.makedirs(pf, exist_ok=True)
    assert mod.delete(mid) is True
    assert not os.path.isdir(pf)
    assert mod._cur_id_raw() == ''


@pytest.mark.parametrize(
    ('attr', 'wanted'), [('portfolio_dir', 'portfolio cleanup'), ('current', 'releasing the deleted model')]
)
def test_delete_logs_but_survives_a_failing_cleanup(monkeypatch, caplog, attr, wanted):
    mid = mod.create('Doomed too')['id']

    def boom(*_a):
        raise OSError('that step failed')

    monkeypatch.setattr(mod, attr, boom)
    with caplog.at_level('WARNING', logger=mod.__name__):
        assert mod.delete(mid) is True
    assert wanted in caplog.text


# ── resolve ──────────────────────────────────────────────────────────────────
def test_resolve_given_nothing():
    assert mod.resolve() is None
    assert mod.resolve('   ') is None
    a = mod.create('A ship')
    assert mod.resolve()['id'] == a['id']  # the only one there is
    mod.create('B ship')
    assert mod.resolve() is None  # ambiguous
    mod.set_current(a['id'])
    assert mod.resolve()['id'] == a['id']  # the current one


def test_resolve_by_id_name_slug_and_substring():
    rec = mod.create('Clyde Ship')
    mod.create('Quite Another Thing')
    assert mod.resolve(rec['id'])['id'] == rec['id']
    assert mod.resolve('clyde ship')['id'] == rec['id']
    assert mod.resolve('Clyde--Ship')['id'] == rec['id']
    assert mod.resolve('clyde')['id'] == rec['id']
    assert mod.resolve('nothing like it') is None
    named = mod.create('aaaaaaaaaaaa')  # an unknown hex id falls back to the name search
    assert mod.resolve('aaaaaaaaaaaa')['id'] == named['id']
    mod.create('Ship one')
    mod.create('Ship two')
    assert mod.resolve('ship') is None  # two substring hits


# ── decoding and normalising ─────────────────────────────────────────────────
@pytest.mark.parametrize(
    ('url', 'match'),
    [
        ('', 'not a jpeg'),
        (None, 'not a jpeg'),
        ('data:image/gif;base64,AAAA', 'not a jpeg'),
        ('data:image/png;base64,A', 'did not decode'),
        ('data:image/png;base64,!!!!', 'picture is empty'),
    ],
)
def test_decode_rejects_bad_urls(url, match):
    with pytest.raises(ValueError, match=match):
        mod._decode(url)


@pytest.mark.parametrize('mime', ['image/jpeg', 'image/png', 'image/webp'])
def test_decode_accepts_each_mime(mime):
    assert mod._decode(_url(b'\x89PNG-ish', mime)) == (b'\x89PNG-ish', mime)


def test_normalise_keeps_a_small_picture_and_gives_up_on_a_non_image():
    raw = _png()
    assert mod._normalise(raw, 'image/png') == (raw, 'image/png', 6, 4)
    assert mod._normalise(b'not an image', 'image/png') == (b'not an image', 'image/png', 0, 0)


def test_normalise_resamples_an_oversized_plan_and_photo(monkeypatch):
    monkeypatch.setattr(mod, 'MAX_EDGE', 4)
    out, mime, w, h = mod._normalise(_png(12, 6, 'RGBA'), 'image/png')
    assert (mime, w, h) == ('image/png', 4, 2)
    assert out.startswith(b'\x89PNG')
    out, mime, w, h = mod._normalise(_png(12, 6), 'image/jpeg')
    assert (mime, w, h, out[:2]) == ('image/jpeg', 4, 2, b'\xff\xd8')
    monkeypatch.setattr(mod, 'MAX_EDGE', 4096)
    monkeypatch.setattr(mod, 'MAX_IMAGE_BYTES', 1)  # small, but over the byte cap: recompressed
    out, mime, _w, _h = mod._normalise(_png(), 'image/jpeg')
    assert (mime, out[:2]) == ('image/jpeg', b'\xff\xd8')


def test_without_pillow(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, 'PIL', None)
    assert mod._pillow() is None
    assert mod._normalise(b'raw', 'image/png') == (b'raw', 'image/png', 0, 0)
    assert mod.contact_sheet([{'path': 'x', 'title': 'y'}], str(tmp_path / 'sheet.png')) == ''


# ── images ───────────────────────────────────────────────────────────────────
def test_add_image_stores_the_file_and_the_record():
    mid = mod.create('Clyde Ship')['id']
    img = mod.add_image(mid, _url(_png()), 'bow.png', 'view_side', 'n' * 600)
    assert img['file'] == img['id'] + '.png' and img['role'] == 'view_side'
    assert len(img['note']) == 400 and img['name'] == 'bow.png'
    assert (img['w'], img['h'], img['span_m'], img['flip'], img['datum']) == (6, 4, 0.0, False, [0.5, 0.5])
    assert img['bytes'] > 0 and os.path.isfile(os.path.join(mod.model_dir(mid), 'images', img['file']))
    assert [i['id'] for i in mod.read(mid)['images']] == [img['id']]
    assert mod.add_image(mid, _url(_png()), role='not-a-role')['role'] == mod.DEFAULT_ROLE
    with pytest.raises(ValueError, match='no such reference model'):
        mod.add_image('aaaaaaaaaaaa', _url(_png()))


@pytest.mark.parametrize(
    ('const', 'value', 'match'),
    [
        ('MAX_IMAGES', 0, 'already holds 0 pictures'),
        ('MAX_IMAGE_BYTES', 1, 'the limit is 0 MB'),
        ('MAX_MODEL_BYTES', 1, 'MB ceiling'),
    ],
)
def test_add_image_refuses_past_every_cap(monkeypatch, const, value, match):
    mid = mod.create('Full')['id']
    monkeypatch.setattr(mod, '_normalise', lambda raw, mime: (raw, mime, 1, 1))
    monkeypatch.setattr(mod, const, value)
    with pytest.raises(ValueError, match=match):
        mod.add_image(mid, _url(_png()))


def test_set_image_updates_every_field_and_misses_cleanly():
    mid, iid = _with_image()
    img = mod.set_image(
        mid, iid, {'role': 'view_top', 'note': 'x' * 500, 'span_m': '7.123456', 'flip': 'on', 'datum': '0.25 0.75'}
    )
    assert img['role'] == 'view_top'
    assert len(img['note']) == 400
    assert (img['span_m'], img['flip'], img['datum']) == (7.1235, True, [0.25, 0.75])
    assert mod.read(mid)['images'][0]['role'] == 'view_top'
    back = mod.set_image(mid, iid, {'role': 'nope', 'span_m': -3, 'flip': 0})
    assert (back['role'], back['span_m'], back['flip']) == ('view_top', 0.0, False)
    assert mod.set_image(mid, 'nosuchimage', {'note': 'hi'}) is None
    assert mod.set_image('aaaaaaaaaaaa', 'x', {'note': 'hi'}) is None


@pytest.mark.parametrize(
    ('datum', 'want'),
    [
        ('0.1,0.2', [0.1, 0.2]),
        ([2.0, -1.0], [1.0, 0.0]),
        ('nonsense', [0.5, 0.5]),
        ([], [0.5, 0.5]),
        (None, [0.5, 0.5]),
    ],
)
def test_set_image_clamps_the_datum(datum, want):
    mid, iid = _with_image()
    assert mod.set_image(mid, iid, {'datum': datum})['datum'] == want


def test_del_image_removes_the_file_the_thumb_and_the_record():
    mid, iid = _with_image()
    path = mod.image_path(mid, iid)
    mod.image_bytes(mid, iid, thumb=True)
    assert os.path.isfile(path + '.th.jpg')
    assert mod.del_image(mid, iid) is True
    assert not os.path.exists(path) and not os.path.exists(path + '.th.jpg')
    assert mod.read(mid)['images'] == []
    assert mod.del_image(mid, iid) is False and mod.del_image('aaaaaaaaaaaa', 'x') is False


def test_del_image_survives_a_file_already_gone():
    mid, iid = _with_image()
    os.remove(mod.image_path(mid, iid))
    assert mod.del_image(mid, iid) is True


def test_image_bytes_returns_the_stored_file_and_guesses_the_mime():
    mid, iid = _with_image()
    raw, mime = mod.image_bytes(mid, iid)
    assert mime == 'image/png' and raw.startswith(b'\x89PNG')
    for args in ((mid, 'nosuchimage'), ('aaaaaaaaaaaa', 'x')):
        with pytest.raises(ValueError, match='no such picture'):
            mod.image_path(*args)
    rec = mod.read(mid)
    rec['images'][0]['file'] = 'odd.bin'
    mod._write(rec)
    with open(os.path.join(mod.model_dir(mid), 'images', 'odd.bin'), 'wb') as fh:
        fh.write(b'blob')
    assert mod.image_bytes(mid, iid) == (b'blob', 'application/octet-stream')


def test_image_bytes_makes_and_then_reuses_a_thumbnail(monkeypatch):
    mid, iid = _with_image()
    small, mime = mod.image_bytes(mid, iid, thumb=True)  # under THUMB_EDGE: not resampled
    assert mime == 'image/jpeg'
    with Image.open(io.BytesIO(small)) as im:
        assert im.size == (6, 4)
    monkeypatch.setattr(mod, 'THUMB_EDGE', 3)
    os.remove(mod.image_path(mid, iid) + '.th.jpg')
    raw, mime = mod.image_bytes(mid, iid, thumb=True)
    assert (mime, raw[:2]) == ('image/jpeg', b'\xff\xd8')
    assert mod.image_bytes(mid, iid, thumb=True)[0] == raw  # the cached thumbnail
    with Image.open(io.BytesIO(raw)) as im:
        assert max(im.size) == 3


def test_thumb_and_b64_without_pillow_return_the_original(monkeypatch):
    mid, iid = _with_image()
    monkeypatch.setattr(mod, '_pillow', lambda: None)
    raw, mime = mod.image_bytes(mid, iid, thumb=True)
    assert mime == 'image/png' and raw.startswith(b'\x89PNG')
    mime, b64 = mod.image_b64(mid, iid)
    assert mime == 'image/png' and base64.b64decode(b64).startswith(b'\x89PNG')


def test_image_b64_sizes_the_picture_and_walks_down_the_quality_ladder():
    mid, iid = _with_image()
    mime, b64 = mod.image_b64(mid, iid, max_edge=3)
    assert mime == 'image/jpeg'
    with Image.open(io.BytesIO(base64.b64decode(b64))) as im:
        assert max(im.size) == 3
    mime, b64 = mod.image_b64(mid, iid, max_bytes=1)
    assert mime == 'image/jpeg' and len(base64.b64decode(b64)) > 1


# ── what the assistant is told ───────────────────────────────────────────────
@pytest.mark.parametrize(
    ('rec', 'want'),
    [
        (None, False),
        ({}, False),
        ({'length_m': 0, 'beam_m': 0, 'height_m': 0}, False),
        ({'length_m': 3}, True),
        ({'beam_m': 3}, True),
        ({'height_m': 3}, True),
    ],
)
def test_measurable(rec, want):
    assert mod.measurable(rec) is want


def test_brief_with_nothing_and_of_a_bare_model():
    assert mod.brief(None) == 'no reference model'
    assert mod.brief({}) == 'no reference model'
    out = mod.brief(mod.read(mod.create('Clyde Ship')['id']))
    assert '"Clyde Ship"' in out and 'measured: NOTHING' in out
    assert '0 pictures' in out and 'no asset built yet' in out


def test_brief_of_a_measured_model_with_pictures():
    mid = mod.create('Clyde Ship', 'a ship')['id']
    mod.update(mid, {'length_m': 12, 'beam_m': 3.5, 'height_m': 4, 'notes': 'n' * 900})
    one = mod.add_image(mid, _url(_png()), 'bow.png', 'view_side')
    mod.set_image(mid, one['id'], {'span_m': 14, 'flip': True, 'datum': [0.1, 0.2], 'note': 'the plate'})
    mod.add_image(mid, _url(_png()), 'snap.png', 'photo')
    out = mod.brief(mod.read(mid))
    assert 'subject: a ship' in out and 'measured: length 12 m, beam 3.5 m, height 4 m' in out
    assert '2 pictures: 1 photo, 1 view_side' in out and 'notes: ' + 'n' * 600 in out
    assert 'spans 14 m across' in out and '[laid out MIRRORED]' in out
    assert 'datum 0.1,0.2' in out and 'the plate' in out


def test_brief_of_one_picture_is_singular_terse_and_names_a_built_asset():
    mid = mod.create('Clyde Ship')['id']
    mod.add_image(mid, _url(_png()), role='unknown-role')
    out = mod.brief(mod.read(mid), verbose=False)
    assert '1 picture: 1 photo' in out and 'pictures:' not in out
    bare = {'id': 'aaaaaaaaaaaa', 'name': 'x', 'images': [{'id': 'i1', 'role': '', 'datum': [0.5, 0.5]}]}
    assert '1 picture: 1 photo' in mod.brief(bare)
    built = mod.read(mid)
    built['asset'] = {'built': '2026-09-23', 'glb': '/tmp/out/clyde.glb', 'pack': 'zyg_reference'}
    said = mod.brief(built)
    assert 'asset BUILT 2026-09-23: clyde.glb' in said and 'place_reference_asset (pack zyg_reference)' in said
    built['asset']['pack'] = ''
    assert 'place_reference_asset' not in mod.brief(built)


def test_public_of_nothing_is_empty_and_of_a_model_gives_urls():
    assert mod.public(None) == {}
    assert mod.public({}) == {}
    mid, iid = _with_image()
    mod.update(mid, {'length_m': 12})
    out = mod.public(mod.read(mid))
    assert out['measurable'] is True and out['asset'] is None
    assert out['images'][0]['url'].endswith(f'image?m={mid}&i={iid}')
    assert out['images'][0]['thumb'].endswith('&t=1')
    bare = {'id': 'aaaaaaaaaaaa', 'name': 'Clyde', 'images': [], 'asset': {'glb': '', 'blend': ''}}
    a = mod.public(bare)['asset']
    assert (a['preview_url'], a['sheet_url'], a['check_urls'], a['portfolio_dir']) == ('', '', [], '')


def test_public_rewrites_a_whole_asset_record():
    asset = dict.fromkeys(('preview', 'sheet', 'script'), '/abs/path/x')
    asset.update(
        glb='/abs/path/clyde.glb',
        blend='/abs/path/clyde.blend',
        edits=['nudge'],
        checks=[{'title': 'scale', 'path': '/abs/c0.png'}],
        inspect=[{'title': 'bow', 'path': '/abs/i0.png'}, {'title': 'stern', 'path': '', 'note': 'no room'}],
        portfolio={'dir': '/abs/portfolio/clyde', 'sheets': ['s1.png', 's2.png']},
        portfolio_shots=[{'title': 'frame 1', 'file': '01-bow.png'}, {'title': 'frame 2', 'file': ''}],
        audit={'findings': ['the hull has a hole']},
    )
    rec = {'id': 'aaaaaaaaaaaa', 'name': 'Clyde', 'images': [], 'asset': asset}
    a = mod.public(rec)['asset']
    assert (a['glb'], a['blend']) == ('clyde.glb', 'clyde.blend')
    assert a['preview_url'].endswith('preview?m=aaaaaaaaaaaa') and a['sheet_url'].endswith('&s=1')
    assert [[x['title'] for x in a[k]] for k in ('check_urls', 'inspect_urls', 'inspect_notes')] == [
        ['scale'],
        ['bow'],
        ['stern'],
    ]
    assert [s['title'] for s in a['portfolio_sheets']] == ['contact sheet 1', 'contact sheet 2']
    assert [p['title'] for p in a['portfolio_urls']] == ['frame 1']
    assert [p['title'] for p in a['portfolio_notes']] == ['frame 2']
    assert a['portfolio_dir'] == '/abs/portfolio/clyde' and a['audit_findings'] == ['the hull has a hole']
    for dead in ('preview', 'sheet', 'checks', 'inspect', 'script', 'edits', 'portfolio', 'portfolio_shots', 'audit'):
        assert dead not in a


# ── the portfolio folder ─────────────────────────────────────────────────────
def test_contact_sheet_draws_every_frame_and_refuses_junk(tmp_path):
    assert mod.contact_sheet([], str(tmp_path / 'sheet.png')) == ''
    assert mod.contact_sheet([{'path': str(tmp_path / 'gone.png')}], str(tmp_path / 'sheet.png')) == ''
    bad = tmp_path / 'bad.png'
    bad.write_text('not a picture', encoding='utf-8')
    assert mod.contact_sheet([{'path': str(bad), 'title': 't'}], str(tmp_path / 'sheet.png')) == ''
    shots = [{'path': _png_file(tmp_path / f'{n}.png', 40, 20), 'title': f'view {n}'} for n in range(7)]
    dest = str(tmp_path / 'sheet.png')
    assert mod.contact_sheet(shots, dest) == dest
    with Image.open(dest) as im:
        assert im.size[0] > 500


def test_write_portfolio_sweeps_copies_sheets_and_indexes(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'SHEET_PER', 2)
    rec = mod.read(mod.create('Clyde Ship')['id'])
    root = mod.portfolio_dir(rec)
    assert root.endswith('clyde-ship-' + rec['id'])
    assert mod.portfolio_dir({'id': 'bbbbbbbbbbbb', 'name': '!!!'}).endswith('reference-bbbbbbbbbbbb')
    os.makedirs(root, exist_ok=True)
    for stale in ('99-old.png', 'index.html', 'portfolio.json'):
        with open(os.path.join(root, stale), 'w', encoding='utf-8') as fh:
            fh.write('stale')
    shots = [{'title': f'View {n}', 'path': _png_file(tmp_path / f'{n}.png'), 'note': f'{n} m'} for n in range(3)]
    shots.append({'title': 'Stern', 'path': str(tmp_path / 'missing.png'), 'note': 'camera blocked'})
    shots.append({'title': '', 'path': '', 'note': ''})
    out = mod.write_portfolio(rec, shots, {'findings': ['a <hole> in the hull']}, _meta())
    assert out['dir'] == root and (out['n'], out['planned'], len(out['sheets'])) == (3, 5, 2)
    assert not os.path.exists(os.path.join(root, '99-old.png'))
    assert os.path.isfile(os.path.join(root, '01-view-0.png'))
    html = _read(out['index'])
    assert 'a &lt;hole&gt; in the hull' in html and '1234 triangles' in html
    assert 'NO PICTURE' in html and 'contact sheet 2' in html
    with open(os.path.join(root, 'portfolio.json'), encoding='utf-8') as fh:
        meta = json.load(fh)
    assert meta['model'] == rec['id'] and all('path' not in s for s in meta['shots'])
    assert meta['sheets'] == [os.path.basename(x) for x in out['sheets']]
    assert os.path.isfile(os.path.join(str(mod.PORTFOLIO_DIR), 'index.html'))


def test_write_portfolio_with_no_pictures_writes_a_sheetless_index():
    rec = mod.read(mod.create('Empty')['id'])
    out = mod.write_portfolio(rec, [], {}, {})
    assert (out['n'], out['sheets']) == (0, [])
    assert 'contact sheet' not in _read(out['index'])


def test_write_portfolio_survives_an_unremovable_stale_file(caplog):
    rec = mod.read(mod.create('Clyde Ship')['id'])
    os.makedirs(os.path.join(mod.portfolio_dir(rec), '99-old.png'))
    with caplog.at_level('DEBUG', logger=mod.__name__):
        out = mod.write_portfolio(rec, [], {}, {})
    assert 'stale portfolio file removal skipped' in caplog.text and out['planned'] == 0


def test_pf_root_index_lists_every_project():
    for name, findings in (('Clyde Ship', ['a hole']), ('Second Thing', [])):
        rec = mod.read(mod.create(name)['id'])
        mod.write_portfolio(rec, [{'title': 'View', 'path': '', 'note': ''}], {'findings': findings}, _meta())
    html = _read(mod._pf_root_index())
    assert 'Architecture portfolios — 2 projects' in html and 'Clyde Ship' in html
    assert '1 audit finding(s)' in html and '0 of 1 pictures' in html


def test_pf_root_index_shows_a_sheet_and_the_singular(tmp_path):
    rec = mod.read(mod.create('Clyde Ship')['id'])
    shot = {'title': 'View', 'path': _png_file(tmp_path / 'a.png'), 'note': '1 m'}
    mod.write_portfolio(rec, [shot], {}, _meta())
    html = _read(mod._pf_root_index())
    assert 'Architecture portfolios — 1 project<' in html and 'contact-sheet-1.png' in html


def test_pf_root_index_skips_junk_and_cannot_write_over_a_directory(roots, caplog):
    pf = roots[1]
    (pf / 'loose-file').write_text('x', encoding='utf-8')
    (pf / 'no-meta').mkdir()
    (pf / 'bad-meta').mkdir()
    (pf / 'bad-meta' / 'portfolio.json').write_text('{oops', encoding='utf-8')
    with caplog.at_level('WARNING', logger=mod.__name__):
        html = _read(mod._pf_root_index())
    assert 'portfolio meta unreadable' in caplog.text and 'Architecture portfolios — 0 projects' in html
    os.remove(pf / 'index.html')  # it was just written; a directory cannot replace a file
    os.makedirs(pf / 'index.html')
    assert mod._pf_root_index() == ''
