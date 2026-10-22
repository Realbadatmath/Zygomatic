# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage for ``zyg_dashboard.kanban.media_scan`` — the Videos/Pictures scan.

Offline by construction: every cache directory, the preview registry and the
three media roots are redirected into ``tmp_path``, ffmpeg is replaced by a fake
``subprocess`` namespace that writes the file it is asked for, and the
provenance seal is stubbed. Nothing here shells out, opens a socket or reads the
repo's runtime JSON.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

import zyg_dashboard.kanban.media_scan as MOD


# ── helpers ──────────────────────────────────────────────────────────────────


def _touch(path, data=b'x'):
    """Create `path` (and its parents) holding `data`; returns the path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(data)
    return path


def _fake_sub(returncode=0, stderr=b'', write=b'data', boom=None):
    """A stand-in for the ``subprocess`` module as media_scan uses it.

    ``write`` bytes land in the last argv element (always the '.part' temp);
    ``write=None`` writes nothing at all, ``boom`` is raised instead of running.
    """
    calls = []

    def run(cmd, **kw):
        calls.append((list(cmd), kw))
        if boom is not None:
            raise boom
        if write is not None:
            _touch(cmd[-1], write)
        return SimpleNamespace(returncode=returncode, stderr=stderr)

    return SimpleNamespace(run=run, SubprocessError=subprocess.SubprocessError, calls=calls)


@pytest.fixture
def mod(tmp_path, monkeypatch):
    """media_scan with every on-disk path redirected under tmp_path."""
    for name, leaf in (
        ('_THUMB_DIR', 'vidthumbs'),
        ('_PREVIEW_DIR', 'vidpreviews'),
        ('_SUBBURN_DIR', 'vidsubburn'),
        ('_IMG_THUMB_DIR', 'imgthumbs'),
    ):
        monkeypatch.setattr(MOD, name, str(tmp_path / 'cache' / leaf))
    monkeypatch.setattr(MOD, '_PREVIEW_REG', str(tmp_path / 'cache' / 'vid_previews.json'))
    monkeypatch.setattr(MOD, '_VID_CACHE', {'ts': 0.0, 'key': None, 'data': None})
    monkeypatch.setattr(MOD, '_PREVIEW_CACHE', {'ts': 0.0, 'mt': -1.0, 'reg': {}})
    monkeypatch.setattr(MOD, '_FFMPEG', '/nonexistent/ffmpeg')
    return MOD


@pytest.fixture
def roots(tmp_path, monkeypatch, mod):
    """The three media roots as real directories under tmp_path."""
    made = {}
    for key in ('out', 'dout', 'drun'):
        p = tmp_path / 'media' / key
        p.mkdir(parents=True)
        made[key] = os.path.realpath(str(p))
    monkeypatch.setattr(mod, '_MEDIA_ROOTS', made)
    monkeypatch.setattr(mod, '_OUTPUT_ROOT', made['out'])
    return made


# ── test-job detection ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('name', 'strict', 'want'),
    [
        ('docsmoke-abc', True, True),
        ('gatecheck-1', True, True),
        ('introsmoke-9', True, True),
        ('smoke_plume', True, False),
        ('sikh_empire', True, False),
        ('docsmoke-abc', False, True),
        ('smoke', False, True),
        ('sikh_empire', False, False),
        (None, False, False),
        ('', True, False),
    ],
)
def test_vid_is_test_job(mod, name, strict, want):
    assert mod._vid_is_test_job(name, strict=strict) is want


def test_vid_is_test_job_helper_refusal_falls_back(mod, monkeypatch):
    def boom(_name):
        raise RuntimeError('helper is unhappy')

    monkeypatch.setattr(mod, '_pc_is_test_pipeline_id', boom)
    assert mod._vid_is_test_job('docsmoke-x') is True
    assert mod._vid_is_test_job('sikh_empire') is False


def test_vid_is_test_job_without_helper(mod, monkeypatch):
    monkeypatch.setattr(mod, '_pc_is_test_pipeline_id', None)
    assert mod._vid_is_test_job('smoke') is True
    assert mod._vid_is_test_job('hero') is False


# ── cache-key paths ──────────────────────────────────────────────────────────


def test_cache_key_paths_are_stable_and_mtime_keyed(mod):
    a = mod._thumb_path('/x/clip.mp4', 1700000000.4)
    assert a == mod._thumb_path('/x/clip.mp4', 1700000000.9)
    assert a != mod._thumb_path('/x/clip.mp4', 1700000001.0)
    assert a.startswith(mod._THUMB_DIR + os.sep) and a.endswith('.jpg')

    p = mod._preview_path('/x/clip.mp4', 1.0, 2.0, 5.0)
    assert p.startswith(mod._PREVIEW_DIR + os.sep) and p.endswith('.mp4')
    assert p != mod._preview_path('/x/clip.mp4', 1.0, 2.5, 5.0)

    s = mod._subburn_path('/x/clip.mp4', 1.0)
    assert s.startswith(mod._SUBBURN_DIR + os.sep) and s.endswith('.mp4')
    assert s != mod._subburn_path('/x/other.mp4', 1.0)

    i = mod._img_thumb_path('/x/pic.png', 1.0, 480)
    assert i != mod._img_thumb_path('/x/pic.png', 1.0, 240)
    assert i.startswith(mod._IMG_THUMB_DIR + os.sep)


# ── preview registry ─────────────────────────────────────────────────────────


def _write_reg(mod, previews):
    return _touch(mod._PREVIEW_REG, json.dumps({'previews': previews}).encode())


def test_preview_registry_missing_file_is_no_previews(mod):
    assert mod._preview_registry() == {}
    assert mod._PREVIEW_CACHE['mt'] == -1.0


def test_preview_registry_keeps_usable_entries_only(mod):
    _write_reg(
        mod,
        {
            'out/a.mp4': {'start': 1.0, 'end': 3.5},
            'out/clamped.mp4': {'start': 0, 'end': 999},
            'out/backwards.mp4': {'start': 9, 'end': 2},
            'out/negative.mp4': {'start': -1, 'end': 4},
            'out/nokey.mp4': {'end': 4},
            'out/text.mp4': {'start': 'soon', 'end': 'later'},
            'out/none.mp4': {'start': None, 'end': 2},
        },
    )
    reg = mod._preview_registry()
    assert set(reg) == {'out/a.mp4', 'out/clamped.mp4'}
    assert reg['out/a.mp4'] == {'start': 1.0, 'end': 3.5}
    assert reg['out/clamped.mp4']['end'] == pytest.approx(mod._PREVIEW_MAX_S)


def test_preview_registry_caches_then_rereads_on_same_mtime(mod):
    _write_reg(mod, {'out/a.mp4': {'start': 0, 'end': 1}})
    first = mod._preview_registry()
    assert mod._preview_registry() is first  # inside the 5 s window: no stat
    mod._PREVIEW_CACHE['ts'] = 0.0  # force the stat; mtime has not moved
    assert mod._preview_registry() is first


def test_preview_registry_tolerates_garbage_and_a_missing_section(mod):
    _touch(mod._PREVIEW_REG, b'{not json at all')
    assert mod._preview_registry() == {}
    mod._PREVIEW_CACHE.update(ts=0.0, mt=-2.0)
    _touch(mod._PREVIEW_REG, json.dumps({'other': 1}).encode())
    assert mod._preview_registry() == {}
    # 'previews' present but not a mapping: the .items() AttributeError is caught too
    mod._PREVIEW_CACHE.update(ts=0.0, mt=-3.0)
    _touch(mod._PREVIEW_REG, json.dumps({'previews': 'soon'}).encode())
    assert mod._preview_registry() == {}


# ── featured preview ─────────────────────────────────────────────────────────


def test_featured_preview_empty_registry(mod):
    assert mod._featured_preview() == {}


def test_featured_preview_single_entry_is_the_tile(mod, roots):
    _touch(os.path.join(roots['out'], 'scene', 'hero_cut.mp4'))
    _write_reg(mod, {'out/scene/hero_cut.mp4': {'start': 0, 'end': 2}})
    out = mod._featured_preview()
    assert out['label'] == 'hero cut'
    assert out['thumb'] == '/inspect/thumb?path=out/scene/hero_cut.mp4'
    assert out['preview'] == '/inspect/preview?path=out/scene/hero_cut.mp4'


def test_featured_preview_honours_the_featured_flag(mod, roots):
    _touch(os.path.join(roots['out'], 'b.mp4'))
    _write_reg(mod, {'out/a.mp4': {'start': 0, 'end': 1}, 'out/b.mp4': {'start': 0, 'end': 1, 'featured': True}})
    assert mod._featured_preview()['label'] == 'b'


def test_featured_preview_two_entries_none_featured(mod, roots):
    _write_reg(mod, {'out/a.mp4': {'start': 0, 'end': 1}, 'out/b.mp4': {'start': 0, 'end': 1}})
    assert mod._featured_preview() == {}


def test_featured_preview_missing_clip_degrades_to_nothing(mod, roots):
    _write_reg(mod, {'out/gone.mp4': {'start': 0, 'end': 1}})
    assert mod._featured_preview() == {}


def test_featured_preview_refuses_a_key_that_escapes_its_root(mod, roots):
    """'<rootkey>/../x' names a real file OUTSIDE the root: no tile, no leak."""
    _touch(os.path.join(os.path.dirname(roots['out']), 'escape.mp4'))
    _write_reg(mod, {'out/../escape.mp4': {'start': 0, 'end': 1}})
    assert mod._featured_preview() == {}


def test_featured_preview_bare_key_resolves_under_the_output_root(mod, roots):
    _touch(os.path.join(roots['out'], 'loose.mp4'))
    _write_reg(mod, {'loose.mp4': {'start': 0, 'end': 1}})
    assert mod._featured_preview()['label'] == 'loose'


def test_featured_preview_unreadable_file_after_a_warm_cache(mod, roots):
    """The cached registry survives the file going bad, but the flag is unreadable."""
    _touch(os.path.join(roots['out'], 'a.mp4'))
    _write_reg(
        mod,
        {
            'out/a.mp4': {'start': 0, 'end': 1, 'featured': True},
            'out/b.mp4': {'start': 0, 'end': 1},
        },
    )
    assert len(mod._preview_registry()) == 2  # warm: the registry outlives the garbage
    _touch(mod._PREVIEW_REG, b'<<<not json')
    assert mod._featured_preview() == {}


# ── ffmpeg-backed builders ───────────────────────────────────────────────────


def test_make_preview_success(mod, tmp_path, monkeypatch):
    fake = _fake_sub()
    monkeypatch.setattr(mod, 'subprocess', fake)
    dst = str(tmp_path / 'out.mp4')
    assert mod._make_preview('/x/clip.mp4', dst, 1.0, 4.0) is True
    assert os.path.isfile(dst) and not os.path.exists(dst + '.part')
    cmd = fake.calls[0][0]
    assert '-an' in cmd and f'scale={mod._PREVIEW_W}:-2' in cmd
    assert cmd[cmd.index('-ss') + 1] == '1.000'


def test_make_preview_ffmpeg_error_is_false(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'subprocess', _fake_sub(returncode=1, stderr=b'boom'))
    dst = str(tmp_path / 'out.mp4')
    assert mod._make_preview('/x/clip.mp4', dst, 0.0, 1.0) is False
    assert not os.path.exists(dst) and not os.path.exists(dst + '.part')


def test_make_preview_empty_output_is_false(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'subprocess', _fake_sub(returncode=0, stderr=None, write=None))
    assert mod._make_preview('/x/clip.mp4', str(tmp_path / 'o.mp4'), 0.0, 0.0) is False


def test_make_preview_launch_failure_is_false(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'subprocess', _fake_sub(boom=OSError('no ffmpeg')))
    assert mod._make_preview('/x/clip.mp4', str(tmp_path / 'o.mp4'), 0.0, 1.0) is False


def test_make_subburn_success_seals_the_copy(mod, tmp_path, monkeypatch):
    fake = _fake_sub()
    monkeypatch.setattr(mod, 'subprocess', fake)
    sealed = []
    monkeypatch.setattr(mod._seal, 'seal_derived', lambda d, p, pipeline=None: sealed.append((d, p, pipeline)))
    clip = _touch(str(tmp_path / 'job' / 'clip.mp4'))
    srt = _touch(str(tmp_path / 'job' / 'clip.srt'), b'1\n')
    dst = str(tmp_path / 'burnt.mp4')
    assert mod._make_subburn(clip, srt, dst) is True
    assert sealed == [(dst, clip, 'subburn')]
    cmd, kw = fake.calls[0]
    assert kw['cwd'] == os.path.dirname(clip)
    assert '-sn' in cmd and f"subtitles=clip.srt:force_style='{mod._SUBBURN_STYLE}'" in cmd


def test_make_subburn_failure_cleans_up(mod, tmp_path, monkeypatch):
    """ffmpeg refused the filter and wrote nothing: no .part is left behind."""
    monkeypatch.setattr(mod, 'subprocess', _fake_sub(returncode=3, stderr=b'bad filter', write=None))
    clip = _touch(str(tmp_path / 'job' / 'clip.mp4'))
    dst = str(tmp_path / 'burnt.mp4')
    assert mod._make_subburn(clip, clip + '.srt', dst) is False
    assert not os.path.exists(dst + '.part')


def test_make_subburn_launch_failure(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'subprocess', _fake_sub(boom=subprocess.SubprocessError('died')))
    clip = _touch(str(tmp_path / 'job' / 'clip.mp4'))
    assert mod._make_subburn(clip, clip + '.srt', str(tmp_path / 'b.mp4')) is False


def test_make_thumb_first_seek_wins(mod, tmp_path, monkeypatch):
    fake = _fake_sub()
    monkeypatch.setattr(mod, 'subprocess', fake)
    dst = str(tmp_path / 't.jpg')
    assert mod._make_thumb('/x/clip.mp4', dst) is True
    assert os.path.isfile(dst)
    assert len(fake.calls) == 1
    assert fake.calls[0][0][fake.calls[0][0].index('-ss') + 1] == '00:00:01'


def test_make_thumb_falls_through_to_no_seek(mod, tmp_path, monkeypatch):
    """A still image gives every seek an empty result; the third try has no -ss."""
    seen = []

    def run(cmd, **kw):
        seen.append(list(cmd))
        if '-ss' not in cmd:
            _touch(cmd[-1], b'jpeg')
        return SimpleNamespace(returncode=0, stderr=b'')

    monkeypatch.setattr(mod, 'subprocess', SimpleNamespace(run=run, SubprocessError=subprocess.SubprocessError))
    dst = str(tmp_path / 't.jpg')
    assert mod._make_thumb('/x/poster.png', dst) is True
    assert len(seen) == 3 and '-ss' not in seen[-1]


def test_make_thumb_all_attempts_empty(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'subprocess', _fake_sub(returncode=0, stderr=b'nope', write=b''))
    dst = str(tmp_path / 't.jpg')
    assert mod._make_thumb('/x/clip.mp4', dst) is False
    assert not os.path.exists(dst) and not os.path.exists(dst + '.part')


def test_make_thumb_launch_failure_breaks_out(mod, tmp_path, monkeypatch):
    fake = _fake_sub(boom=OSError('no ffmpeg'))
    monkeypatch.setattr(mod, 'subprocess', fake)
    assert mod._make_thumb('/x/clip.mp4', str(tmp_path / 't.jpg')) is False
    assert len(fake.calls) == 1  # broke after the first attempt, did not retry


# ── image thumbnails ─────────────────────────────────────────────────────────


def _png(path, size):
    from PIL import Image

    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new('RGB', size, (10, 120, 200)).save(path, 'PNG')
    return path


def test_make_img_thumb_downscales(mod, tmp_path):
    from PIL import Image

    src = _png(str(tmp_path / 'src' / 'big.png'), (600, 300))
    dst = str(tmp_path / 'small.jpg')
    assert mod._make_img_thumb(src, dst, 480) is True
    with Image.open(dst) as im:
        assert im.size == (480, 240)


def test_make_img_thumb_never_upscales(mod, tmp_path):
    from PIL import Image

    src = _png(str(tmp_path / 'src' / 'small.png'), (100, 50))
    dst = str(tmp_path / 'thumb.jpg')
    assert mod._make_img_thumb(src, dst, 480) is True
    with Image.open(dst) as im:
        assert im.size == (100, 50)


def test_make_img_thumb_without_pillow(mod, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'PIL', None)
    assert mod._make_img_thumb(str(tmp_path / 'x.png'), str(tmp_path / 'y.jpg'), 480) is False


def test_make_img_thumb_on_a_non_image(mod, tmp_path):
    src = _touch(str(tmp_path / 'src' / 'notapng.png'), b'this is not an image')
    dst = str(tmp_path / 'y.jpg')
    assert mod._make_img_thumb(src, dst, 480) is False
    assert not os.path.exists(dst) and not os.path.exists(dst + '.part')


# ── department labels ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('root_key', 'seg0', 'want'),
    [
        ('dout', 'clips', 'documentary'),
        ('dout', 'remix_ai', 'remix ai'),
        ('dout', 'tokitoki', 'tokitoki'),
        ('out', 'effects', 'effects'),
        ('out', 'video_studio', 'video studio'),
        ('out', 'clips', 'clips'),
        ('out', 'multichar_scene_7', 'multichar'),
        ('out', 'quarantine_2026', 'quarantine'),
        ('out', 'video_pipeline_x', 'video'),
        ('out', 'manga_pipeline_x', 'manga'),
        ('out', 'assetlib_props', 'asset library'),
        ('out', 'some_other_tree', 'some other tree'),
        ('out', '', 'out'),
    ],
)
def test_vid_group(mod, root_key, seg0, want):
    assert mod._vid_group(root_key, seg0) == want


def test_vid_group_truncates_long_labels(mod):
    assert len(mod._vid_group('out', 'a_very_long_department_name_indeed_yes')) == 28


# ── the scan itself ──────────────────────────────────────────────────────────


def test_api_videos_medusa_scope_is_empty(mod):
    assert mod._api_videos(scope='medusa') == {
        'videos': [],
        'groups': [],
        'total': 0,
        'hidden_intermediates': 0,
        'hidden_downloads': 0,
        'hidden_tests': 0,
    }


def test_api_videos_skips_a_missing_root(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, '_MEDIA_ROOTS', {'out': str(tmp_path / 'nope')})
    assert mod._api_videos()['total'] == 0


def test_api_videos_survives_an_unlistable_root(mod, roots, monkeypatch):
    real = os.listdir

    def listdir(path, *a, **kw):
        if os.path.realpath(path) == roots['out']:
            raise OSError('permission denied')
        return real(path, *a, **kw)

    monkeypatch.setattr(mod.os, 'listdir', listdir)
    _touch(os.path.join(roots['dout'], 'clips', 'j1', 'hero.mp4'))
    data = mod._api_videos()
    assert [v['name'] for v in data['videos']] == ['hero.mp4']


def _build_tree(roots):
    """A small media tree exercising every branch of the walk."""
    d, o, r = roots['dout'], roots['out'], roots['drun']
    # excluded top-level trees
    for top in ('stocks', 'kids_series_abc', '.hidden', 'medusa_lab'):
        _touch(os.path.join(d, top, 'nope.mp4'))
    _touch(os.path.join(d, 'loose_file.txt'))  # a top that is not a directory
    _touch(os.path.join(d, 'empty_tree', 'readme.txt'))  # a dir with no mp4s
    # the documentary job: deliverables, downloads, cuts, working files
    job = os.path.join(d, 'clips', 'job1')
    _touch(os.path.join(job, 'sikh_empire.mp4'), b'0123456789')
    _touch(os.path.join(job, 'sikh_empire.vtt'), b'WEBVTT\n')
    _touch(os.path.join(job, 'multichar_still.png'))
    _touch(os.path.join(job, 'FINAL_hero.mp4'))
    _touch(os.path.join(job, 'epilogue_final.mp4'))
    _touch(os.path.join(job, 'dQw4w9WgXcQ_transcript.json'), b'{}')
    _touch(os.path.join(job, 'dQw4w9WgXcQ.mp4'))
    _touch(os.path.join(job, 'dQw4w9WgXcQ_clip1_norm.mp4'))
    _touch(os.path.join(job, 'aBcDeFgHiJk_clip2.mp4'))
    _touch(os.path.join(job, 'medusa_leak.mp4'))
    _touch(os.path.join(job, 'act1_graded.mp4'))
    os.symlink(os.path.join(job, 'gone-forever.mp4'), os.path.join(job, 'dangling.mp4'))
    _touch(os.path.join(job, 'bed', 'seg_01.mp4'))
    _touch(os.path.join(job, '_prev_cut_2026', 'old.mp4'))
    _touch(os.path.join(job, 'clips', 'wip.mp4'))
    # test jobs: by id, by marker in the dir, by marker in the job dir
    _touch(os.path.join(d, 'clips', 'docsmoke-1', 'x.mp4'))
    _touch(os.path.join(d, 'clips', 'marked', 'y.mp4'))
    _touch(os.path.join(d, 'clips', 'marked', MOD._VID_SMOKE_MARKER))
    _touch(os.path.join(d, 'clips', 'markedtop', MOD._VID_SMOKE_MARKER))
    _touch(os.path.join(d, 'clips', 'markedtop', 'sub', 'z.mp4'))
    # groups and posters
    _touch(os.path.join(d, 'quarantine_2026', 'q.mp4'))
    _touch(os.path.join(d, 'multichar_7', 'm.mp4'))
    _touch(os.path.join(d, 'multichar_7', 'FINAL_still_plate.png'))
    _touch(os.path.join(d, 'weird_name', 'w.mp4'))
    _touch(os.path.join(d, 'weird_name', '_ignored.png'))
    _touch(os.path.join(d, 'weird_name', 'a_poster.jpg'))
    _touch(os.path.join(d, 'no_stills', 'n.mp4'))
    # the 'out' tree: table label, and a bare-'smoke' dir that is NOT a test job
    _touch(os.path.join(o, 'storyteller', 'ep1', 'episode.mp4'))
    _touch(os.path.join(o, 'smoke_plume', 's.mp4'))
    # every drun file is a working file by root
    _touch(os.path.join(r, 'pipe', 'inflight.mp4'))


def test_api_videos_deliverables_only(mod, roots):
    _build_tree(roots)
    data = mod._api_videos()
    names = {v['name'] for v in data['videos']}
    assert names == {
        *('sikh_empire.mp4', 'FINAL_hero.mp4', 'epilogue_final.mp4', 'w.mp4'),
        *('n.mp4', 'm.mp4', 'episode.mp4', 's.mp4'),
    }
    assert data['total'] == len(data['videos']) == 8
    assert data['hidden_downloads'] == 3
    assert data['hidden_intermediates'] >= 7
    assert data['hidden_tests'] == 3
    assert data['groups'] == sorted(data['groups'])
    assert {'documentary', 'storyteller', 'multichar', 'smoke plume', 'weird name'} <= set(data['groups'])
    # the list is newest first
    assert [v['mtime'] for v in data['videos']] == sorted((v['mtime'] for v in data['videos']), reverse=True)

    by = {v['name']: v for v in data['videos']}
    assert by['sikh_empire.mp4']['size'] == 10
    assert by['sikh_empire.mp4']['label'] == 'sikh empire'
    assert by['sikh_empire.mp4']['url'] == '/inspect/media?path=dout/clips/job1/sikh_empire.mp4'
    assert by['sikh_empire.mp4']['subs'] == '/inspect/media?path=dout/clips/job1/sikh_empire.vtt'
    assert by['sikh_empire.mp4']['still'].endswith('multichar_still.png')
    assert by['sikh_empire.mp4']['thumb'].endswith('multichar_still.png')
    assert by['sikh_empire.mp4']['final'] is False
    assert by['sikh_empire.mp4']['job'] == 'job1'
    assert by['FINAL_hero.mp4']['final'] is True
    assert by['epilogue_final.mp4']['final'] is True
    assert by['m.mp4']['still'].endswith('FINAL_still_plate.png')
    assert by['w.mp4']['still'].endswith('a_poster.jpg')
    assert by['n.mp4']['still'] == '' and by['n.mp4']['subs'] == ''
    assert by['n.mp4']['thumb'] == '/inspect/thumb?path=dout/no_stills/n.mp4'
    assert by['s.mp4']['test'] is False  # bare 'smoke' is not a test id outside dout
    assert all(v['intermediate'] is False for v in data['videos'])


def test_api_videos_with_intermediates(mod, roots):
    _build_tree(roots)
    data = mod._api_videos(intermediates=True)
    names = {v['name'] for v in data['videos']}
    # working files are back …
    assert {'seg_01.mp4', 'old.mp4', 'wip.mp4', 'inflight.mp4', 'q.mp4', 'act1_graded.mp4'} <= names
    # … test jobs too, flagged …
    assert {'x.mp4', 'y.mp4', 'z.mp4'} <= names
    assert {v['name'] for v in data['videos'] if v['test']} == {'x.mp4', 'y.mp4', 'z.mp4'}
    # … but downloads and medusa never are, in either mode
    assert not names & {'dQw4w9WgXcQ.mp4', 'dQw4w9WgXcQ_clip1_norm.mp4', 'aBcDeFgHiJk_clip2.mp4'}
    assert not any('medusa' in n for n in names)
    assert data['hidden_intermediates'] == 0 and data['hidden_tests'] == 0
    assert data['hidden_downloads'] == 3
    assert {v['name'] for v in data['videos'] if v['intermediate']} == {
        *('seg_01.mp4', 'old.mp4', 'wip.mp4', 'inflight.mp4', 'q.mp4'),
        *('act1_graded.mp4', 'x.mp4', 'y.mp4', 'z.mp4'),
    }


def test_api_videos_marks_registered_previews(mod, roots):
    _touch(os.path.join(roots['dout'], 'clips', 'j', 'hero.mp4'))
    _touch(os.path.join(roots['dout'], 'clips', 'j', 'plain.mp4'))
    _write_reg(mod, {'dout/clips/j/hero.mp4': {'start': 1, 'end': 3}})
    by = {v['name']: v for v in mod._api_videos()['videos']}
    assert by['hero.mp4']['preview'] == '/inspect/preview?path=dout/clips/j/hero.mp4'
    assert by['plain.mp4']['preview'] == ''


def test_api_videos_caches_per_mode(mod, roots):
    _touch(os.path.join(roots['dout'], 'clips', 'j', 'one.mp4'))
    first = mod._api_videos()
    _touch(os.path.join(roots['dout'], 'clips', 'j', 'two.mp4'))
    assert mod._api_videos() is first  # same key, inside the TTL
    assert mod._api_videos(intermediates=True)['total'] == 2  # other key: recomputed
    mod._VID_CACHE['ts'] = 0.0
    assert mod._api_videos()['total'] == 2  # expired: recomputed


# ── import-time fallback when pipeline_common is unavailable ─────────────────


def test_module_falls_back_to_the_local_regex_without_pipeline_common(monkeypatch):
    import importlib

    monkeypatch.setitem(sys.modules, 'zyg_workflows.pipeline_common', None)
    try:
        reloaded = importlib.reload(MOD)
        assert reloaded._pc_is_test_pipeline_id is None
        assert reloaded._VID_SMOKE_MARKER == 'SMOKE_RUN'
        assert reloaded._vid_is_test_job('docsmoke-1') is True
    finally:
        monkeypatch.undo()
        importlib.reload(MOD)
    assert MOD._pc_is_test_pipeline_id is not None
