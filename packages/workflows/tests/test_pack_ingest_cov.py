# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline coverage for :mod:`zyg_workflows.pack_ingest`: every destination the
module derives is redirected to ``tmp_path`` and every heavy dependency
(faster-whisper, soundfile, ffmpeg, the asset library) is a fake, so nothing
here reads the repo's data/ tree, loads a model or shells out.
"""

import json
import os
import subprocess
import sys
import types

import pytest

from zyg_workflows import pack_ingest as mod


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point every module constant at tmp_path and clear the USC cache."""
    orig = tmp_path / 'originals'
    runtime = tmp_path / 'runtime'
    orig.mkdir()
    runtime.mkdir()
    monkeypatch.setattr(mod, '_HERE', str(tmp_path / 'pkg'))
    monkeypatch.setattr(mod, 'ORIG', str(orig))
    monkeypatch.setattr(mod, 'RUNTIME', str(runtime))
    monkeypatch.setattr(mod, 'QUAR_JSON', str(runtime / 'quar.json'))
    monkeypatch.setattr(mod, 'WHISPER_JSON', str(runtime / 'whisper.json'))
    monkeypatch.setattr(mod, 'SLATE_JSON', str(runtime / 'slate.json'))
    monkeypatch.setattr(mod, 'USC_WORDS_JSON', str(runtime / 'words.json'))
    monkeypatch.setattr(mod, '_USC_MANIFEST', {})  # a fresh cache, never the process-wide one
    return types.SimpleNamespace(root=tmp_path, orig=orig, runtime=runtime)


def _wav(root, rel, payload=b'RIFF0000'):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(payload)
    return p


def _fake_al(meta=None, dirs=None, assets=None):
    """A stand-in for zyg_workflows.asset_library_service."""
    calls = []
    return types.SimpleNamespace(
        _load_audio_meta=lambda cat: dict(meta or {}).get(cat, {}),
        set_audio_meta=lambda cat, fid, upd: calls.append((cat, fid, upd)) or True,
        _audio_dir=lambda cat: str((dirs or {}).get(cat, '/tmp/zyg-nonexistent')),
        load_assets=lambda cat: list((assets or {}).get(cat, [])),
        calls=calls,
    )


# ── pure helpers ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('raw', 'n', 'want'),
    [
        ('Female Horror Scream', 72, 'female_horror_scream'),
        ('A--B__C', 72, 'a_b_c'),
        ('Trailing!!!', 72, 'trailing'),
        ('abcdefghij', 4, 'abcd'),
        ('ab cdefgh', 3, 'ab'),
        (12, 72, '12'),
    ],
)
def test_slug(raw, n, want):
    assert mod._slug(raw, n) == want


@pytest.mark.parametrize(
    ('stem', 'want'),
    [
        (
            'VOXScrm_Male Being Tortured, Perspective 1_344 Audio_Screaming',
            ('VOXScrm', 'Male Being Tortured, Perspective 1'),
        ),
        ('VOXScrm_Female Horror Scream_344 Audio_Screaming_01', ('VOXScrm', 'Female Horror Scream 01')),
        ('VOXScrm_Thing 2_344 Audio_01', ('VOXScrm', 'Thing 2')),
        ('HUMN_Shout_SNDBTS', ('HUMN', 'Shout')),
        ('CRWD_Stadium_CS_USC', ('CRWD', 'Stadium')),
        ('plain', ('plain', '')),
    ],
)
def test_strip_vendor(stem, want):
    assert mod._strip_vendor(stem) == want


# ── routers ──────────────────────────────────────────────────────────────────


# (router, master path relative to the pack, expected category, expected name) —
# a 'quarantine' category carries the reason in place of the name, and (None, None)
# means the router declines the file (demo tracks, docs, a loose master).
_SCR = 'VOXScrm_Female Horror Scream_344 Audio.wav'
_Q_GAS = 'atrocity reference (gas chamber)'
_Q_XYL = 'spoken English / chant (source recording)'
_ROUTES = [
    (mod._route_screaming, 'loose.wav', None, None),
    (mod._route_screaming, 'Male/VOXScrm_Male Grunt_344 Audio.wav', 'vocal_fx', 'scr_m_grunt'),
    (mod._route_screaming, f'Female/General/{_SCR}', 'vocal_fx', 'scr_f_horror_scream'),
    (mod._route_ss2, 'VOICES/MALE/VOXScrm_Male Shout_SNDBTS.wav', 'vocal_fx', 'ss2_m_shout'),
    (mod._route_ss2, 'VOICES/FEMALE/VOXScrm_Female Cry_SNDBTS.wav', 'vocal_fx', 'ss2_f_cry'),
    (mod._route_ss2, 'VOICES/CHILD/a.wav', 'quarantine', 'child/baby content (child)'),
    (mod._route_ss2, 'VOICES/BABY/a.wav', 'quarantine', 'child/baby content (baby)'),
    (mod._route_ss2, 'OTHER/MALE/a.wav', None, None),
    (mod._route_ss2, 'VOICES/MALE', None, None),
    (mod._route_hw1, 'loose.wav', None, None),
    (mod._route_hw1, 'Flesh Impacts/VOXHit_Sword Flesh_344 Audio.wav', 'foley', 'hw1_sword_flesh'),
    (mod._route_uh, 'loose.wav', None, None),
    (mod._route_uh, 'Horror - Mini/Prisoner Screaming, Gas Chamber.wav', 'quarantine', _Q_GAS),
    (mod._route_uh, 'Ambiences - Mini/sub/VOXScrm_Creepy Room.wav', 'sfx', 'uh_voxscrm_creepy_room'),
    (mod._route_uh, 'Voices/VOXScrm_Female Horror Scream.wav', 'vocal_fx', 'uh_voxscrm_female_horror_scream'),
    (mod._route_uh, 'Voices/VOXScrm_Male Muffled Loud Scream.wav', 'vocal_fx', 'uh_voxscrm_male_muffled_loud_scream'),
    (mod._route_uh, 'Impacts - Mini/VOXHit_Metal Hit.wav', 'foley', 'uh_voxhit_metal_hit'),
    (mod._route_xylon, 'Source Recordings/voice _have a nice day 01.wav', 'quarantine', _Q_XYL),
    (mod._route_xylon, 'Source Recordings/Po River 01.wav', 'sfx', 'xyl_src_po_river_01'),
    (mod._route_xylon, 'Source Recordings/Wood Scrape.wav', 'foley', 'xyl_src_wood_scrape'),
    (mod._route_xylon, 'Designed Sounds/Interface/Beep 01.wav', 'foley', 'xyl_interface_beep_01'),
    (mod._route_xylon, 'Designed Sounds/Beep.wav', None, None),
    (mod._route_xylon, 'Docs/readme.wav', None, None),
    (mod._route_mrfossy, 'nope.wav', None, None),
    (mod._route_mrfossy, '123__mrfossy__voice_adultmale_grunt.wav', 'vocal_fx', 'mrfossy_grunt'),
    (mod._route_usc, 'item/cover.mp3', None, None),
    (mod._route_usc, 'SSE_Library_CROWDS/CRWD_Stadium.wav', 'sfx', 'usc_crwd_stadium'),
    (mod._route_usc, 'Foley_Props_Reel/thing.wav', 'foley', 'usc_thing'),
    (mod._route_usc, 'tapes/wilhelm scream.wav', 'vocal_fx', 'usc_wilhelm_scream'),
]


@pytest.mark.parametrize(('fn', 'rel', 'cat', 'name'), _ROUTES, ids=[f'{f.__name__}-{r}' for f, r, _c, _n in _ROUTES])
def test_router_destinations(sandbox, fn, rel, cat, name):
    got = fn(rel.replace('/', os.sep))
    if cat is None:
        assert got is None
    elif cat == 'quarantine':
        assert got == (cat, name)
    else:
        assert got[:2] == (cat, name)


# (router, path, the meta keys that carry the routing decision)
_ROUTE_META = [
    (mod._route_screaming, 'Male/VOXScrm_Male Grunt_344 Audio.wav', {'sex': 'male', 'group': 'misc'}),
    (mod._route_screaming, f'Female/General/{_SCR}', {'sex': 'female', 'group': 'General'}),
    (mod._route_ss2, 'VOICES/FEMALE/VOXScrm_Female Cry_SNDBTS.wav', {'sex': 'female', 'group': 'Female'}),
    (mod._route_hw1, 'Flesh Impacts/VOXHit_Sword Flesh_344 Audio.wav', {'descriptor': 'Sword Flesh'}),
    (mod._route_uh, 'Ambiences - Mini/sub/VOXScrm_Creepy Room.wav', {'bed': True, 'group': 'Ambiences'}),
    (mod._route_uh, 'Voices - Mini/VOXScrm_Female Horror Scream 1.wav', {'sex': 'female'}),
    (mod._route_uh, 'Voices - Mini/VOXScrm_Male Muffled Loud Scream 2.wav', {'sex': 'male'}),
    (mod._route_xylon, 'Source Recordings/Po River 01.wav', {'bed': True, 'group': 'Source'}),
    (mod._route_xylon, 'Designed Sounds/Interface/Beep 01.wav', {'designed': True, 'group': 'Interface'}),
    (mod._route_mrfossy, '7__mrfossy__grunt.wav', {'sex': 'male', 'source_url': 'https://freesound.org/s/7/'}),
    (mod._route_usc, 'SSE_Library_CROWDS/CRWD_Stadium.wav', {'bed': True, 'ucs': None}),
    (mod._route_usc, 'tapes/wilhelm scream.wav', {'no_ai_training': True, 'transform': 'dsp'}),
]


@pytest.mark.parametrize(('fn', 'rel', 'want'), _ROUTE_META, ids=[f'{f.__name__}-{r}' for f, r, _w in _ROUTE_META])
def test_router_metadata(sandbox, fn, rel, want):
    _cat, _name, meta = fn(rel.replace('/', os.sep))
    assert {k: meta.get(k) for k in want} == want


def test_route_usc_url_and_wilhelm_note(sandbox):
    _c, _n, meta = mod._route_usc(os.path.join('SSE_Library_CROWDS', 'CRWD_Stadium.wav'))
    assert meta['source_url'] == 'https://archive.org/details/SSE_Library_CROWDS'
    _c, _n, meta = mod._route_usc(os.path.join('tapes', 'wilhelm scream.wav'))
    assert 'provenance disputed' in meta['notes_extra']


def test_usc_manifest_reads_then_caches(sandbox):
    item = sandbox.orig / 'usc_sound_effect_archive'
    item.mkdir()
    (item / 'MANIFEST.json').write_text(
        json.dumps({'files': [{'item': 'tapes', 'name': 'a.wav', 'md5': 'ff', 'comment': 'hi'}]})
    )
    got = mod._usc_manifest()
    assert got[os.path.join('tapes', 'a.wav')]['md5'] == 'ff'
    assert mod._usc_manifest() is got  # second call uses the cache
    _c, _n, meta = mod._route_usc(os.path.join('tapes', 'a.wav'))
    assert meta['ia_md5'] == 'ff' and meta['ia_comment'] == 'hi'


def test_usc_manifest_missing_file_warns(sandbox, caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger=mod.__name__):
        assert mod._usc_manifest() == {}
    assert 'unreadable' in caplog.text


# ── enumeration and planning ─────────────────────────────────────────────────


def test_masters_walks_wav_only(sandbox):
    _wav(sandbox.orig, os.path.join('p', 'Sounds', 'b', 'two.wav'))
    _wav(sandbox.orig, os.path.join('p', 'Sounds', 'one.WAV'))
    (sandbox.orig / 'p' / 'Sounds' / 'notes.txt').write_text('x')
    got = mod.masters('p', 'Sounds')
    assert [r for r, _f in got] == [os.path.join('b', 'two.wav'), 'one.WAV']
    assert got[0][1] == str(sandbox.orig / 'p' / 'Sounds' / 'b' / 'two.wav')
    rooted = [r for r, _f in mod.masters('p', '')]  # an empty sub walks from the pack root
    assert rooted == [os.path.join('Sounds', 'b', 'two.wav'), os.path.join('Sounds', 'one.WAV')]
    assert mod.masters('absent', 'Sounds') == []


def _build_plan_tree(orig):
    scr = os.path.join('344_screaming', 'Sound Effects')
    _wav(orig, os.path.join(scr, 'loose.wav'), b'skipme')
    _wav(orig, os.path.join(scr, 'Female', 'General', 'VOXScrm_Female Horror Scream_344 Audio_01.wav'), b'same')
    _wav(orig, os.path.join(scr, 'Female', 'Other', 'VOXScrm_Female Horror Scream_344 Audio_01.wav'), b'same')
    _wav(orig, os.path.join(scr, 'Male', 'Group A', 'VOXScrm_Male Pain_344 Audio.wav'), b'aaa')
    _wav(orig, os.path.join(scr, 'Male', 'Group B', 'VOXScrm_Male Pain_344 Audio.wav'), b'bbbb')
    _wav(orig, os.path.join('soundbits_screams_shouts_2', 'Sounds', 'VOICES', 'CHILD', 'cry.wav'), b'child')


def test_plan_dedups_and_disambiguates(sandbox, capsys):
    _build_plan_tree(sandbox.orig)
    rows = mod.plan()
    out = capsys.readouterr().out
    assert 'NO MASTERS' in out
    assert '[plan] 1 byte-identical duplicates skipped' in out
    assert 'renamed 1 name collisions' in out
    by_dest = {}
    for r in rows:
        by_dest.setdefault(r['dest'], []).append(r)
    assert len(by_dest['quarantine']) == 1
    assert by_dest['quarantine'][0]['why'] == 'child/baby content (child)'
    skips = {r['rel'] for r in by_dest['skip']}
    assert 'loose.wav' in skips
    assert any(r.get('why', '').startswith('duplicate of 344_screaming/') for r in by_dest['skip'])
    names = sorted(r['name'] for r in by_dest['vocal_fx'])
    assert names == ['scr_f_horror_scream_01', 'scr_m_pain', 'scr_m_pain_group_b']
    assert all('md5' in r for r in by_dest['vocal_fx'])


def test_plan_empty_tree_is_quiet(sandbox):
    msgs = []
    assert mod.plan(log_fn=msgs.append) == []
    assert sum(1 for m in msgs if 'NO MASTERS' in m) == len(mod.PACKS)


# ── scans ────────────────────────────────────────────────────────────────────


def _row(pack, dest, rel='a.wav', full='/m/a.wav'):
    return {'pack': pack, 'dest': dest, 'rel': rel, 'full': full}


def test_vocal_candidates_selection():
    rows = [
        _row('344_screaming', 'skip', full='/m/skip.wav'),
        _row('344_screaming', 'vocal_fx', full='/m/v.wav'),
        _row('344_screaming', 'quarantine', full='/m/q.wav'),
        _row('usc_sound_effect_archive', 'foley', full='/m/usc.wav'),
        _row('344_ultimate_horror_mini', 'foley', rel='Voices/x.wav', full='/m/uh.wav'),
        _row('344_ultimate_horror_mini', 'foley', rel='Impacts/x.wav', full='/m/uh2.wav'),
        _row('asfx_xylon', 'foley', rel='Source/Laugh.wav', full='/m/x.wav'),
        _row('asfx_xylon', 'foley', rel='Source/Wood.wav', full='/m/x2.wav'),
    ]
    assert mod._vocal_candidates(rows) == ['/m/v.wav', '/m/q.wav', '/m/usc.wav', '/m/uh.wav', '/m/x.wav']


@pytest.mark.parametrize('rc', [0, 1])
def test_run_whisper_shells_out(sandbox, monkeypatch, capsys, rc):
    seen = {}

    def fake_run(cmd, timeout=None):
        seen['cmd'] = cmd
        seen['timeout'] = timeout
        return types.SimpleNamespace(returncode=rc)

    monkeypatch.setattr(subprocess, 'run', fake_run)
    rows = [_row('344_screaming', 'vocal_fx', full='/m/v.wav')]
    assert mod.run_whisper(rows) is (rc == 0)
    assert '[whisper] 1 candidates' in capsys.readouterr().out
    assert seen['cmd'][0] == mod.ASR_PY and seen['cmd'][1] == '-c'
    assert seen['cmd'][-1] == mod.WHISPER_JSON
    assert seen['timeout'] == 4 * 3600
    assert json.load(open(seen['cmd'][-2])) == ['/m/v.wav']


@pytest.fixture
def fake_soundfile(monkeypatch):
    import numpy as np

    def read(path, dtype='float32', always_2d=True):
        sr, dur = int(path.split('@')[1]), float(path.split('@')[2])
        t = np.arange(int(sr * dur), dtype='float32') / sr
        x = 0.001 * np.sin(2 * np.pi * 300 * t)
        hit = (t > dur * 0.4) & (t < dur * 0.4 + 1.0)
        x[hit] += 0.5 * np.sin(2 * np.pi * 1000 * t[hit])
        return x.reshape(-1, 1), sr

    monkeypatch.setitem(sys.modules, 'soundfile', types.SimpleNamespace(read=read))


def test_slate_measure_short_file_is_none(fake_soundfile):
    assert mod._slate_measure('f@8000@2.0') is None


def test_slate_measure_finds_the_burst(fake_soundfile):
    burst, band, t, dur, width = mod._slate_measure('f@8000@10.0')
    assert burst > 20.0
    assert 0.0 <= band <= 1.0
    assert dur == pytest.approx(10.0, abs=0.1)
    assert 3.9 <= t <= 5.1
    assert width >= 0.45


def test_run_slate_without_a_cache_file(sandbox, caplog):
    import logging

    with caplog.at_level(logging.DEBUG, logger=mod.__name__):
        assert mod.run_slate([], log_fn=lambda m: None) == {}
    assert 're-measuring' in caplog.text
    assert json.load(open(mod.SLATE_JSON)) == {}


def test_run_slate_measures_caches_and_flags(sandbox, monkeypatch, capsys):
    json.dump({'/m/cached.wav': {'suspect': False}}, open(mod.SLATE_JSON, 'w'))
    answers = {
        '/m/boom.wav': (30.0, 0.5, 1.2, 12.0, 0.9),
        '/m/quiet.wav': (5.0, 0.5, 1.2, 12.0, 0.9),
        '/m/short.wav': None,
    }

    def fake_measure(path):
        if path == '/m/bad.wav':
            raise RuntimeError('x' * 200)
        if path in answers:
            return answers[path]
        return (30.0, 0.9, 0.5, 12.0, 0.9)

    monkeypatch.setattr(mod, '_slate_measure', fake_measure)
    rows = [
        _row('p', 'skip', full='/m/skipped.wav'),
        _row('p', 'sfx', full='/m/cached.wav'),
        _row('p', 'sfx', full='/m/bad.wav'),
        _row('p', 'sfx', full='/m/short.wav'),
        _row('p', 'sfx', full='/m/boom.wav'),
        _row('p', 'sfx', full='/m/quiet.wav'),
    ]
    rows += [_row('p', 'sfx', full=f'/m/bulk{i}.wav') for i in range(98)]
    res = mod.run_slate(rows)
    out = capsys.readouterr().out
    assert '[slate] 100 measured, 1 suspect' in out
    assert '[slate] measured 100 long files, 1 suspect' in out
    shape = {'burst_db': 30.0, 'speech_band': 0.5, 'burst_width_s': 0.9}
    assert res['/m/boom.wav'] == dict(shape, t_s=1.2, dur_s=12.0, suspect=True)
    assert res['/m/quiet.wav']['suspect'] is False
    assert len(res['/m/bad.wav']['error']) == 120
    assert '/m/short.wav' not in res and '/m/skipped.wav' not in res
    assert res['/m/cached.wav'] == {'suspect': False}
    assert json.load(open(mod.SLATE_JSON))['/m/boom.wav']['suspect'] is True


# ── install / annotate ───────────────────────────────────────────────────────


@pytest.fixture
def library(stub_module):
    """Install fakes for the three lazily-imported sibling modules."""
    made = []

    def register(cat, src, meta, name=None, convert=True, log_fn=None):
        if name == 'boom':
            return None
        made.append((cat, name, meta))
        return {'id': f'{name}.wav'}

    ai = types.SimpleNamespace(
        register_audio_asset=register,
        audit_category=lambda cat: [] if cat == 'vocal_fx' else ['dirty'],
        training_gate=lambda pairs, log_fn=None: {'ok': False},
        made=made,
    )
    stub_module('ambience_ingest', ai)
    stub_module('vocal_fx_ingest', types.SimpleNamespace(classify=lambda text, p: (bool(text), 'asr text')))
    return ai


def _install_row(sandbox, dest, name, **extra):
    row = {
        'pack': 'pk',
        'rel': f'{name}.wav',
        'full': os.path.join(sandbox.root, 'pkg', 'data', 'asset_libraries', '_originals', f'{name}.wav'),
        'dest': dest,
        'name': name,
        'extra': {'descriptor': name.title(), 'group': 'G'},
        'lic': {'license_id': 'cc0', 'no_ai_training': False},
        'label': 'Some Pack',
    }
    row.update(extra)
    return row


def test_install_without_scans_warns_and_installs(sandbox, library, stub_module, capsys):
    stub_module('asset_library_service', _fake_al())
    rows = [
        _install_row(sandbox, 'skip', 'nope'),
        _install_row(sandbox, 'quarantine', 'kid', why='child/baby content (child)'),
        _install_row(sandbox, 'vocal_fx', 'grunt'),
        _install_row(sandbox, 'foley', 'boom'),
    ]
    stats = mod.install(rows)
    out = capsys.readouterr().out
    assert 'no whisper scan' in out
    assert '[install] FAILED pk/boom.wav' in out
    assert stats == {'installed': 1, 'skipped': 0, 'failed': 1, 'quarantined': 1, 'verbal': 0, 'slate': 0}
    cat, name, meta = library.made[0]
    assert (cat, name) == ('vocal_fx', 'grunt')
    assert meta['verbal_why'] == 'not scanned'
    assert meta['asr_no_speech_prob'] is None
    assert meta['notes'] == 'Some Pack — Grunt (G)'
    assert meta['master'] == os.path.join('_originals', 'grunt.wav')
    saved = json.load(open(mod.QUAR_JSON))
    assert saved['files'] == [
        {'pack': 'pk', 'master': os.path.join('_originals', 'kid.wav'), 'why': 'child/baby content (child)'}
    ]


def test_install_with_scans_notes_and_idempotency(sandbox, library, stub_module):
    rows = [
        _install_row(sandbox, 'vocal_fx', 'scream'),
        _install_row(sandbox, 'sfx', 'bed'),
        _install_row(sandbox, 'foley', 'wilhelm'),
    ]
    rows[2]['lic'] = {'license_id': 'cc0', 'no_ai_training': True}
    rows[2]['extra'] = {'descriptor': 'Wilhelm', 'notes_extra': 'disputed'}
    json.dump(
        {
            rows[0]['full']: {'text': 'number three', 'no_speech_prob': 0.01},
            rows[2]['full']: {'text': '', 'no_speech_prob': 0.9},
        },
        open(mod.WHISPER_JSON, 'w'),
    )
    json.dump({rows[0]['full']: {'suspect': True, 't_s': 1.5, 'burst_db': 28.0}}, open(mod.SLATE_JSON, 'w'))
    already = os.path.join('_originals', 'bed.wav')
    stub_module('asset_library_service', _fake_al(meta={'sfx': {'bed.wav': {'master': already}}}))

    stats = mod.install(rows)
    assert stats['installed'] == 2 and stats['skipped'] == 1
    assert stats['verbal'] == 1 and stats['slate'] == 1
    notes = {name: meta['notes'] for _c, name, meta in library.made}
    assert 'CONTAINS SPEECH (asr text)' in notes['scream']
    assert 'SLATE SUSPECT at 1.5s (28.0 dB burst)' in notes['scream']
    assert 'Mix-only: no AI/voice-reference use' in notes['wilhelm']
    assert 'provenance disputed, mix-only' in notes['wilhelm']
    assert all('notes_extra' not in meta for _c, _n, meta in library.made)


def test_install_logs_every_200th(sandbox, library, stub_module, capsys):
    stub_module('asset_library_service', _fake_al())
    rows = [_install_row(sandbox, 'foley', f'hit{i}') for i in range(200)]
    stats = mod.install(rows)
    assert stats['installed'] == 200
    assert "'installed': 200" in capsys.readouterr().out


def test_install_defaults_to_plan(sandbox, library, stub_module):
    stub_module('asset_library_service', _fake_al())
    assert mod.install()['installed'] == 0


def test_annotate_updates_only_changed_records(sandbox, library, stub_module):
    rows = [
        _install_row(sandbox, 'skip', 'nope'),
        _install_row(sandbox, 'foley', 'missing'),
        _install_row(sandbox, 'foley', 'unscanned'),
        _install_row(sandbox, 'foley', 'errored'),
        _install_row(sandbox, 'foley', 'stable'),
        _install_row(sandbox, 'vocal_fx', 'fresh'),
    ]
    json.dump(
        {
            rows[3]['full']: {'error': 'boom'},
            rows[4]['full']: {'text': 'hi', 'no_speech_prob': 0.25},
            rows[5]['full']: {'text': 'number three', 'no_speech_prob': 0.01},
        },
        open(mod.WHISPER_JSON, 'w'),
    )
    json.dump({rows[5]['full']: {'suspect': True}}, open(mod.SLATE_JSON, 'w'))
    stable = {
        'master': os.path.join('_originals', 'stable.wav'),
        'asr_text': 'hi',
        'asr_no_speech_prob': 0.25,
        'verbal': True,
        'verbal_why': 'asr text',
        'slate_suspect': False,
    }
    old_note = 'Some Pack — Fresh. CONTAINS SPEECH (old) — not for a non-English or period scene'
    fresh = {'master': os.path.join('_originals', 'fresh.wav'), 'notes': old_note}
    al = _fake_al(
        meta={
            'foley': {'stable.wav': stable, 'errored.wav': {'master': os.path.join('_originals', 'errored.wav')}},
            'vocal_fx': {'fresh.wav': fresh},
        }
    )
    stub_module('asset_library_service', al)

    assert mod.annotate(rows) == 1
    cat, fid, upd = al.calls[0]
    assert (cat, fid) == ('vocal_fx', 'fresh.wav')
    assert upd['verbal'] is True and upd['slate_suspect'] is True
    assert upd['notes'].count('CONTAINS SPEECH') == 1
    assert '(asr text)' in upd['notes']


def test_annotate_defaults_to_plan(sandbox, library, stub_module):
    stub_module('asset_library_service', _fake_al())
    assert mod.annotate() == 0


# ── head slates and the report ───────────────────────────────────────────────


@pytest.mark.parametrize('dry', [True, False])
def test_trim_heads(sandbox, library, stub_module, monkeypatch, capsys, dry):
    audio = sandbox.root / 'audio'
    audio.mkdir()
    # fid -> (category, [(word, start, end, probability)]): a slate to cut, a file whose
    # head is content, one with no words at all, and one whose ffmpeg call fails.
    slate = [('Number', 0.1, 0.6, 0.9), ('three', 0.7, 1.05, 0.9), ('later', 9.0, 9.4, 0.9), ('faint', 1.2, 1.4, 0.1)]
    heads = {'slate.wav': ('sfx', slate), 'content.wav': ('sfx', [('wind', 0.2, 0.5, 0.9)]), 'silent.wav': ('sfx', [])}
    heads['broken.wav'] = ('foley', [('take', 0.1, 0.4, 0.9)])
    words = {
        fid: {'cat': cat, 'master': f'/m/{fid}', 'words': [{'w': w, 's': s, 'e': e, 'p': p} for w, s, e, p in ws]}
        for fid, (cat, ws) in heads.items()
    }
    json.dump(words, open(mod.USC_WORDS_JSON, 'w'))
    al = _fake_al(dirs={'sfx': audio, 'foley': audio})
    stub_module('asset_library_service', al)
    monkeypatch.setattr(mod, 'exe', lambda name: f'/usr/bin/{name}')
    calls = []

    def fake_run(cmd, capture_output=False, timeout=None):
        calls.append(cmd)
        ok = not cmd[-1].endswith('broken.wav')
        return types.SimpleNamespace(returncode=0 if ok else 1, stderr=b'e' * 300)

    monkeypatch.setattr(subprocess, 'run', fake_run)

    done = mod.trim_heads(dry=dry)
    out = capsys.readouterr().out
    if dry:
        assert done == []
        assert calls == []
        assert "would cut sfx/slate.wav at 1.2s  ('Number three')" in out
        assert '[trim] 0 working copies re-cut' in out
        return
    assert done == [('sfx', 'slate.wav', 1.2, 'Number three')]
    assert '[trim] FAILED broken.wav: ' in out
    assert '[trim] 1 working copies re-cut from master' in out
    assert len(calls) == 2
    cmd = calls[0]
    assert cmd[:7] == ['/usr/bin/ffmpeg', '-y', '-ss', '1.2', '-i', '/m/slate.wav', '-vn']
    assert cmd[-1] == str(audio / 'slate.wav')
    cat, fid, upd = al.calls[0]
    assert (cat, fid) == ('sfx', 'slate.wav')
    assert upd['trimmed_head_s'] == 1.2
    assert upd['trim_reason'] == 'spoken slate: Number three'
    assert 'master untouched' in upd['notes_trim']


def test_report(sandbox, library, stub_module, capsys):
    assets = {
        'vocal_fx': [
            {'id': 'a', 'pack': 'pk', 'verbal': True, 'no_ai_training': True},
            {'id': 'b', 'slate_suspect': True},
        ],
        'foley': [{'id': 'c', 'pack': 'pk'}],
        'sfx': [],
    }
    stub_module('asset_library_service', _fake_al(assets=assets))
    mod.report()
    out = capsys.readouterr().out
    assert 'vocal_fx: 2 files; licence audit CLEAN' in out
    assert 'foley: 1 files; licence audit 1 UNCLEAN' in out
    assert 'sfx: 0 files; licence audit 1 UNCLEAN' in out
    assert '   verbal-flagged 1, slate-suspect 1' in out
    assert '   training gate refuses a mix-only sample: True' in out
    assert '       1  pk' in out
    assert '       1  (pre-existing)' in out
