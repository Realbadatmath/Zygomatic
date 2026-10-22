# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline coverage for ``tools/studio_verify/acceptance.py``.

The module is a Playwright acceptance pass over four studios. Nothing here starts a browser: a
``_Page`` stand-in answers every ``evaluate()`` by matching a needle against the JavaScript source
the module hands it, and writes a real little PNG for every ``screenshot()`` so the module's own PIL
maths (``mean_rgb``) runs for real. HTTP goes through a fake ``safe_urlopen`` and a fake ``sh``; the
only real subprocess is one ``python -c`` in the ``sh`` test.
"""

import contextlib
import importlib
import io
import json
import logging
import os
import sys
import types
import urllib.error

import pytest
from PIL import Image

from zyg_workflows.tools.studio_verify import acceptance as A

# Needle -> answer, in match order: the first needle contained in the script wins, so 'MS.rec' has
# to stay ahead of the #mesh-viewer needle (the mesh 'opened' probe reads both). A list answer is
# consumed one poll at a time (the creature pane: base, then not-yet-loaded, then its own mesh).
_SCRIPTS = json.loads("""
{"SX.ready": true, "switchView('charstudio')": null,
 "modelLoaded": {"modelLoaded": true, "modelType": "Group", "modelId": "ch1", "modelVerts": 50000,
   "hairExists": true, "hairChildren": 2, "hairLength": "long", "hairBox": {"minY": 1.2, "maxY": 1.7},
   "dressExists": true, "dressChildren": 3, "shoulderY": 1.4, "credit": "mesh by the house rig",
   "stubs": 0, "tools": 42, "torso": {"cx": 30, "cy": 30, "hw": 10}},
 "cst-panel-title": {"on": true, "title": "Jaw", "body": "appearance.jaw 0.5"},
 "input[type=color]": {"colour": 3, "paths": ["wardrobe.colour_top"]},
 "/inspect/api/list": {"id": "ch1", "name": "Ada", "total": 7},
 "handVerts": {"handVerts": 120, "maxX": 0.441, "px": {"hand": [30.0, 30.0], "forehead": [32.0, 28.0]}},
 "CS_TOOLS.forEach": {"ok": true, "tool": "jaw", "eid": "cst-in", "staged": "x", "wanted": "x"},
 "cstPanelClose": null, "cstRevertAll": 0, "switchView('creatures')": null,
 "biggestMeshVerts": {"ready": true, "global": "CRST3.model", "type": "Group", "isGroup": true,
   "meshes": 3, "verts": 9000, "biggestMeshVerts": 4000, "url": "", "glbUrl": "", "meshSource": "",
   "crstId": "", "hint": "Base stand-in: Quaternius CC0 pack", "bar3d": 1, "barPin": 1, "barBase": 1},
 "{r: r / n": [{"r": 0.5, "g": 0.5, "b": 0.5, "n": 9}, {"r": 0.1, "g": 0.2, "b": 0.9, "n": 9}],
 "ctAdd": null, "ctClear": null,
 "crstLoadCreature": {"ok": true, "id": "d0e44ab002ad", "name": "Thing", "total": 12},
 "switchView('movement')": null,
 "moTrackExtract": {"extract": "function", "visible": "block", "tools": 9},
 "data-view": "Mesh Studio", "switchView('mesh')": null,
 "msh-dock": {"all": 186, "ph": 186, "foot_scrollW": 100, "foot_clientW": 120},
 "mshOpenPicker": null,
 "MS.rec": {"rec": true, "name": "head.glb", "mode": "3d", "d3": "block", "viewer": "none"},
 "switchView('inspections')": null, "libOpenCat": null,
 "getElementById('mesh-viewer').style.display": "flex", "mvClose": null}
""")

_CS_OK, _SKIN_OK = _SCRIPTS['modelLoaded'], _SCRIPTS['handVerts']
_CRST_OK, _GLB = _SCRIPTS['biggestMeshVerts'], '/meshes/d0e44ab002ad.glb'
_CRST_OWN = dict(_CRST_OK, hint='Own mesh', glbUrl=_GLB, url=_GLB, meshSource='photogrammetry', crstId='d0e44ab002ad')
_SCRIPTS['biggestMeshVerts'] = [_CRST_OK, dict(_CRST_OWN, glbUrl='', hint='loading own mesh'), _CRST_OWN]


class _Page:  # a Playwright page, minus the browser
    def __init__(self, scripts=None, rgb=(200, 130, 110), size=(64, 64)):
        self.scripts = dict(_SCRIPTS)
        self.scripts.update(scripts or {})
        self.rgb, self.size = rgb, size
        self.calls, self.shots, self.handlers, self.console = [], [], {}, []
        self.fail_waits = ()
        self.cards = 3
        self._seen = {}

    def __getattr__(self, name):  # wait_for_selector / wait_for_timeout / click only record
        if name not in ('wait_for_selector', 'wait_for_timeout', 'click'):
            raise AttributeError(name)
        return lambda *a, **k: self.calls.append((name, a[0] if a else None, None))

    def evaluate(self, script, arg=None):
        self.calls.append(('evaluate', script, arg))
        for needle, val in self.scripts.items():
            if needle in script:
                i = self._seen.get(needle, 0)
                self._seen[needle] = i + 1
                if isinstance(val, list):
                    val = val[min(i, len(val) - 1)]
                return dict(val) if isinstance(val, dict) else val
        raise AssertionError('no scripted answer for %r' % script[:90])

    def wait_for_function(self, expr, timeout=None):
        self.calls.append(('wait_for_function', expr, timeout))
        for needle in self.fail_waits:
            if needle in expr:
                raise RuntimeError('timed out waiting for ' + needle)

    def eval_on_selector_all(self, sel, fn):
        self.calls.append(('eval_on_selector_all', sel, fn))
        return self.cards if 'length' in fn else None

    def screenshot(self, path):
        Image.new('RGB', self.size, self.rgb).save(path)
        self.shots.append(path)

    def on(self, event, cb):
        self.handlers[event] = cb

    def goto(self, url, **kw):
        self.calls.append(('goto', url, kw))
        for msg in self.console:
            self.handlers['console'](msg) if not isinstance(msg, str) else self.handlers['pageerror'](msg)


class _Resp:  # what safe_urlopen hands back
    def __init__(self, body=b'', status=200, ctype='application/json'):
        self._body, self.status = body, status
        self.headers = {'Content-Type': ctype}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _urlopen(table):  # dispatch on a substring of the requested url
    def fake(url, timeout=None):
        for needle, val in table.items():
            if needle in url:
                if isinstance(val, Exception):
                    raise val
                return val
        raise AssertionError('unmapped url ' + url)

    return fake


def _failures(names=''):  # assert every '|'-separated check name reached the module's failure list
    joined = ' | '.join(A.RES['failures'])
    for n in [x for x in names.split('|') if x]:
        assert n in joined, n
    return joined


_BUNDLE = '\n'.join('\u2500\u2500 %s.js' % m for m in A.EXPECTED_EXT).encode()
_SPEC, _OPS = json.loads("""
[{"actions": ["walk", "run"], "name": "movement", "nested": {"a": ["fine", 3, null]}},
 {"base_creatures": [{"id": "b1", "lb": "Horse", "pack": "Quaternius CC0"}, {"id": "b2", "lb": "Dog", "pack": "Kenney"},
   {"id": "b3", "lb": "Bird", "pack": "Smithsonian"}, {"id": "b4", "lb": "Fish", "pack": "Quaternius CC0"}]}]
""")
_URLS_OK = {
    '/studio_ext/bundle.js': _Resp(_BUNDLE, ctype='application/javascript'),
    '/inspect/api/movement/spec': _Resp(json.dumps(_SPEC).encode()),
    '/inspect/api/movement/driver': _Resp(b'{"error":"no such job"}', status=404),
    '/inspect/api/creature/fx/ops': _Resp(json.dumps(_OPS).encode()),
}


@pytest.fixture(autouse=True)
def _reset_res():
    """The module keeps one global report dict; no test may leak into the next."""
    A.RES['sections'], A.RES['failures'] = {}, []
    A.RES.pop('pass', None)
    yield
    A.RES['sections'], A.RES['failures'] = {}, []
    A.RES.pop('pass', None)


@pytest.fixture
def crews(tmp_path, monkeypatch):
    """Every path the module derives lands under tmp_path."""
    out = tmp_path / 'output' / 'studio_verify'
    out.mkdir(parents=True)
    monkeypatch.setattr(A, 'CREWS', str(tmp_path))
    monkeypatch.setattr(A, 'OUT', str(out))
    return tmp_path


# ── the pure reporting helpers ───────────────────────────────────────────────
def test_sect_creates_once_and_returns_the_same_section():
    s = A.sect('page')
    s['checks'].append({'name': 'x'})
    assert A.sect('page') is s and A.RES['sections']['page'] is s
    assert sorted(s) == ['checks', 'measured']


def test_check_records_pass_fail_and_only_failures_reach_the_list(caplog):
    with caplog.at_level(logging.INFO, logger=A.__name__):
        assert A.check('page', 'all good', 1, {'n': 2}) is True
        assert A.check('page', 'no measurement', True) is True
        assert A.check('mesh', 'bad', 0, {'why': 'nope'}) is False
    rows = A.RES['sections']['page']['checks']
    assert [r['ok'] for r in rows] == [True, True]
    assert rows[0]['measured'] == {'n': 2} and rows[1]['measured'] is None
    assert A.RES['failures'] == ['mesh: bad = {"why": "nope"}']
    assert 'PASS  page       all good   {"n": 2}' in caplog.text
    assert 'PASS  page       no measurement' in caplog.text
    assert 'FAIL  mesh       bad   {"why": "nope"}' in caplog.text


def test_measure_writes_under_the_named_section():
    A.measure('movement', 'spec_actions', 2)
    A.measure('movement', 'spec_keys', ['a'])
    assert A.RES['sections']['movement']['measured'] == {'spec_actions': 2, 'spec_keys': ['a']}


def test_sh_runs_a_fixed_argv_in_the_crews_tree(crews):
    rc, out = A.sh([sys.executable, '-c', 'import os,sys; print(os.getcwd()); sys.stderr.write("e")'])
    assert rc == 0 and out.endswith('e')
    assert os.path.realpath(str(crews)) in os.path.realpath(out.splitlines()[0])
    rc2, _ = A.sh([sys.executable, '-c', 'raise SystemExit(3)'])
    assert rc2 == 3


def test_api_json_parses_a_payload_and_turns_errors_into_a_dict(monkeypatch):
    monkeypatch.setattr(A, 'safe_urlopen', _urlopen({'/ops': _Resp(b'{"ok": true, "n": 4}')}))
    assert A.api_json('/ops', timeout=1) == {'ok': True, 'n': 4}
    monkeypatch.setattr(A, 'safe_urlopen', _urlopen({'/ops': OSError('connection refused')}))
    bad = A.api_json('/ops')
    assert bad['ok'] is False and bad['error'] == 'OSError: connection refused'


def test_mean_rgb_averages_a_box_clamps_it_and_refuses_a_degenerate_one(tmp_path):
    png = tmp_path / 'shot.png'
    im = Image.new('RGB', (40, 40), (10, 20, 30))
    im.paste(Image.new('RGB', (20, 40), (210, 110, 60)), (0, 0))
    im.save(png)
    rgb, box = A.mean_rgb(str(png), 10, 20, 5, 5)
    assert rgb == [210.0, 110.0, 60.0] and box == [5, 15, 15, 25]
    # the box is clamped to the image, so an oversized request still averages both halves
    rgb2, box2 = A.mean_rgb(str(png), 20, 20, 400, 400)
    assert box2 == [0, 0, 40, 40] and rgb2[0] == pytest.approx(110.0)
    # entirely off the left edge: nothing to average
    assert A.mean_rgb(str(png), -50, 20, 5, 5) == (None, [0, 15, -45, 25])


# ── page-level checks ────────────────────────────────────────────────────────
def _offline(monkeypatch, urls=None, shrc=(0, 'ok')):
    table = dict(_URLS_OK)
    table.update(urls or {})
    monkeypatch.setattr(A, 'safe_urlopen', _urlopen(table))
    monkeypatch.setattr(A, 'exe', lambda n: '/usr/bin/' + n)
    seen = []
    monkeypatch.setattr(A, 'sh', lambda argv: (seen.append(argv), shrc)[1])
    monkeypatch.setattr(A, 'base_creature_checks', lambda: A.measure('creatures', 'stub', True))
    monkeypatch.setattr(A, 'movement_track_checks', lambda: A.measure('movement', 'stub', True))
    return seen


def test_page_offline_checks_all_green(monkeypatch):
    seen = _offline(monkeypatch)
    A.page_offline_checks()
    assert A.RES['failures'] == []
    assert seen[0][1:] == ['tools/studio_verify/check_inspection_js.py']
    assert seen[1] == ['/usr/bin/node', 'tools/studio_verify/check_cst_placeholders.js']
    assert A.RES['sections']['page']['measured']['bundle_modules'] == A.EXPECTED_EXT
    mv = A.RES['sections']['movement']['measured']
    assert mv['spec_actions'] == 2 and mv['spec_keys'] == ['actions', 'name', 'nested']
    assert mv['driver_404']['code'] == 404
    assert mv['stub'] is True and A.RES['sections']['creatures']['measured']['stub'] is True


def test_page_offline_checks_reports_a_short_bundle_and_a_bad_script_exit(monkeypatch):
    short = _Resp('\u2500\u2500 char_file.js'.encode())
    _offline(monkeypatch, urls={'/studio_ext/bundle.js': short}, shrc=(2, 'boom'))
    A.page_offline_checks()
    _failures(
        'check_inspection_js.py exit 0|check_cst_placeholders.js exit 0|bundle serves all eight studio_ext modules'
    )
    assert A.RES['sections']['page']['measured']['bundle_modules'] == ['char_file']


def test_page_offline_checks_survives_both_fetches_failing(monkeypatch):
    down = {
        '/studio_ext/bundle.js': urllib.error.URLError('down'),
        '/inspect/api/movement/spec': OSError('reset'),
        '/inspect/api/movement/driver': OSError('reset'),
    }
    _offline(monkeypatch, urls=down)
    A.page_offline_checks()
    _failures('GET /studio_ext/bundle.js|GET /inspect/api/movement/spec|driver?job=nonexistent answers JSON 4xx')
    mv = A.RES['sections']['movement']['measured']
    assert mv['spec_actions'] == 0 and mv['spec_keys'] == []
    assert mv['driver_404'] == {'code': 0, 'ctype': '', 'body': 'reset'}


def test_page_offline_checks_flags_placeholder_wording_and_an_html_error_page(monkeypatch):
    spec = {'actions': [{'name': 'S08 stand-in'}], 'note': 'placeholder until rigged'}
    err = urllib.error.HTTPError(A.URL, 500, 'boom', {'Content-Type': 'text/html'}, io.BytesIO(b'<html>no json</html>'))
    bad = {'/inspect/api/movement/spec': _Resp(json.dumps(spec).encode()), '/inspect/api/movement/driver': err}
    _offline(monkeypatch, urls=bad)
    A.page_offline_checks()
    _failures("spec has no 'placeholder'/'S08' wording|driver?job=nonexistent answers JSON 4xx")
    hits = [c for c in A.RES['sections']['movement']['checks'] if 'placeholder' in c['name']][0]
    assert sorted(h['path'] for h in hits['measured']) == ['spec.actions[0].name', 'spec.note']
    mv = A.RES['sections']['movement']['measured']['driver_404']
    assert mv['code'] == 500 and mv['ctype'] == 'text/html'


def test_page_offline_checks_accepts_a_json_4xx_from_a_successful_read(monkeypatch):
    _offline(monkeypatch, urls={'/inspect/api/movement/driver': _Resp(b'{"ok":false}', status=499)})
    A.page_offline_checks()
    assert not [f for f in A.RES['failures'] if 'driver' in f]


# ── base creatures ───────────────────────────────────────────────────────────
def test_base_creature_checks_green_on_four_third_party_bases(monkeypatch):
    monkeypatch.setattr(A, 'api_json', lambda path: dict(_OPS))
    A.base_creature_checks()
    m = A.RES['sections']['creatures']['measured']
    assert A.RES['failures'] == []
    assert m['base_creatures_n'] == 4 and m['base_creature_ids'] == ['b1', 'b2', 'b3', 'b4']
    assert m['base_creature_labels'] == ['Horse', 'Dog', 'Bird', 'Fish']
    assert m['base_creature_packs'] == ['Kenney', 'Quaternius CC0', 'Smithsonian']
    A.RES['sections'], A.RES['failures'] = {}, []  # and again, with one of ours smuggled in
    ops = {'base_creatures': _OPS['base_creatures'] + [{'id': 'b5', 'lb': 'Pufferball', 'pack': 'house'}]}
    monkeypatch.setattr(A, 'api_json', lambda path: ops)
    A.base_creature_checks()
    assert 'b5' in _failures('no base creature mentions pufferball')
    assert A.RES['sections']['creatures']['measured']['base_creatures_n'] == 5


def test_base_creature_checks_on_an_api_error_fails_every_check(monkeypatch):
    monkeypatch.setattr(A, 'api_json', lambda path: {'ok': False, 'error': 'HTTPError: 502'})
    A.base_creature_checks()
    want = '/inspect/api/creature/fx/ops lists >= 4 base creatures|the bases come from third-party CC0 packs'
    assert [c['name'] for c in A.RES['sections']['creatures']['checks'] if not c['ok']] == want.split('|')
    assert A.RES['sections']['creatures']['measured']['base_creature_packs'] == []


# ── movement tracks on disk ──────────────────────────────────────────────────
def _track(crews, job_id, payload, pngs=('0001.png',), masks=('m0001.png',)):
    d = crews / 'output' / 'movement' / '_tracks' / job_id
    d.mkdir(parents=True)
    ctrl, mdir = d / 'control', d / 'mask'
    for sub, names in ((ctrl, pngs), (mdir, masks)):
        sub.mkdir()
        for n in names:
            Image.new('RGB', (4, 4), (0, 0, 0)).save(sub / n)
    body = {'job_id': job_id, 'control_dir': str(ctrl), 'mask_dir': str(mdir)}
    body.update(payload)
    (d / 'job.json').write_text(json.dumps(body))
    return d


def test_newest_done_track_skips_unreadable_and_unfinished_runs(crews):
    assert A.newest_done_track() == (None, None, None)
    _track(crews, 'running', {'status': 'running', 'ended': 9e12})
    bad = crews / 'output' / 'movement' / '_tracks' / 'broken'
    bad.mkdir(parents=True)
    (bad / 'job.json').write_text('{not json')
    _track(crews, 'old', {'status': 'done', 'ended': 100.0})
    _track(crews, 'new', {'status': 'done', 'updated': 200.0})
    when, path, job = A.newest_done_track()
    assert when == 200.0 and job['job_id'] == 'new' and path.endswith('new/job.json')
    _track(crews, 'nots', {'status': 'done'})  # no timestamp at all: the file mtime stands in
    when, path, job = A.newest_done_track()
    assert job['job_id'] == 'nots' and when == pytest.approx(os.path.getmtime(path))


def test_movement_track_checks_green_on_a_real_track(crews):
    _track(crews, 'j1', {'status': 'done', 'ended': 10.0, 'masks': 12, 'frames': 12, 'subject': 'ada'})
    A.movement_track_checks()
    assert A.RES['failures'] == []
    info = A.RES['sections']['movement']['measured']['newest_done_track']
    assert info['job_id'] == 'j1' and info['mask_pngs'] == 1 and info['control_pngs'] == 1
    assert info['control_first'] == '0001.png' and info['masks'] == 12


def test_movement_track_checks_flags_zero_masks_and_a_missing_control_dir(crews):
    _track(crews, 'j2', {'status': 'done', 'ended': 1.0, 'masks': 0, 'control_dir': '', 'mask_dir': ''})
    A.movement_track_checks()
    _failures('newest done track has masks > 0|newest done track has a control_dir with >= 1 png')
    info = A.RES['sections']['movement']['measured']['newest_done_track']
    assert info['mask_pngs'] == 0 and info['control_pngs'] == 0


def test_movement_track_checks_when_no_track_is_done(crews):
    A.movement_track_checks()
    want = 'movement: a done movement track exists = {"searched": "output/movement/_tracks/*/job.json"}'
    assert A.RES['failures'] == [want]
    assert 'newest_done_track' not in A.RES['sections']['movement']['measured']


# ── the skin sample ──────────────────────────────────────────────────────────
def test_skin_checks_pass_on_a_skin_coloured_patch(crews):
    pg = _Page()
    A.skin_checks(pg)
    assert A.RES['failures'] == []
    m = A.RES['sections']['charstudio']['measured']
    assert m['skin_landmarks']['handVerts'] == 120
    assert m['skin_forehead']['rgb'] == [200.0, 130.0, 110.0]
    assert m['skin_forehead']['max_channel'] == 200.0 and m['skin_hand']['r_minus_b'] == 90.0
    assert m['skin_hand']['centre'] == [30.0, 30.0]
    assert pg.shots == [os.path.join(A.OUT, 'final2_charstudio_skin.png')]


def test_skin_checks_catch_the_washed_out_body(crews):
    A.skin_checks(_Page(rgb=(250, 250, 250)))
    want = '%s 40x40 patch: no channel mean above 245|%s 40x40 patch: R > B (skin, not white/grey)'
    _failures('|'.join(want % (n, n) for n in ('forehead', 'hand')))


def test_skin_checks_report_a_missing_projection(crews):
    A.skin_checks(_Page(scripts={'handVerts': None}))
    joined = _failures('no projection for hand')
    assert joined.count('40x40 patch reads as skin') == 2
    assert A.RES['sections']['charstudio']['measured']['skin_landmarks'] is None


# ── studio 1 ─────────────────────────────────────────────────────────────────
def test_charstudio_green_end_to_end(crews):
    pg = _Page()
    A.charstudio(pg)
    assert A.RES['failures'] == []
    m = A.RES['sections']['charstudio']['measured']
    assert m['default']['stubs'] == 0 and m['staged_state']['dressChildren'] == 3
    assert m['injected'] == {'id': 'ch1', 'name': 'Ada', 'total': 7}
    assert [s['ok'] for s in m['staged']] == [True, True, True]
    assert m['torso_mean_rgb']['rgb'] == [200.0, 130.0, 110.0] and m['torso_mean_rgb']['redness'] == 80.0
    assert m['reverted_dirty_keys'] == 0
    assert [c[1] for c in pg.calls if c[0] == 'click'] == ['[data-cstool="jaw"]', '[data-cstool="wardrobecol"]']
    staged = [c[2]['path'] for c in pg.calls if c[0] == 'evaluate' and isinstance(c[2], dict)]
    assert staged == ['identity.hair_length', 'wardrobe.headwear', 'wardrobe.colour_top']


def test_charstudio_without_a_canvas_or_hair_box_fails_loudly(crews):
    probe = {k: v for k, v in _CS_OK.items() if k not in ('torso', 'hairBox')}
    probe.update(credit='Inject a character to begin', stubs=4, dressChildren=1, shoulderY=None)
    scripts = {
        'modelLoaded': probe,
        'cst-panel-title': {'on': False, 'title': '', 'body': ''},
        'input[type=color]': {'colour': 0, 'paths': []},
        'CS_TOOLS.forEach': {'ok': False, 'why': 'no tool owns it'},
        'cstRevertAll': 2,
    }
    A.charstudio(_Page(scripts=scripts))
    _failures(
        ".cst-tool.stub count == 0|#cs-credit does not say 'inject a character'"
        "|jaw tool opens #cst-panel.on with 'appearance.jaw'|wardrobe colour tool draws three colour inputs"
        '|all three fields staged via cstStageField|long hair reaches below the shoulder'
        '|CS3.dress has >= 2 children with a hat + top staged|torso mean colour is red-dominant'
        '|cstRevertAll() dropped every staged edit'
    )
    torso = [c for c in A.RES['sections']['charstudio']['checks'] if 'torso mean' in c['name']][0]
    assert torso['measured'] == 'no renderer canvas to project the torso onto'


# ── studio 2 ─────────────────────────────────────────────────────────────────
def test_creatures_green_including_the_injected_own_mesh(crews):
    pg = _Page()
    A.creatures(pg)
    assert A.RES['failures'] == []
    m = A.RES['sections']['creatures']['measured']
    assert m['default']['ready'] is True and 'Quaternius' in m['default_hint']
    assert m['colour_mean_before']['b'] == 0.5 and m['colour_mean_after_blue']['b'] == 0.9
    assert m['injected']['id'] == 'd0e44ab002ad' and m['own_mesh']['glbUrl'] == _GLB
    assert pg.shots == [os.path.join(A.OUT, n) for n in ('final2_creatures.png', 'final2_creatures_own.png')]


def test_creatures_when_the_pane_never_becomes_ready_and_injection_fails(crews):
    never = dict(_CRST_OK, ready=False, isGroup=False, hint='Pufferball placeholder', bar3d=0, barPin=0, barBase=0)
    nope = {'ok': False, 'why': 'no creature d0e44ab002ad', 'total': 0}
    pg = _Page(scripts={'biggestMeshVerts': never, '{r: r / n': None, 'crstLoadCreature': nope})
    A.creatures(pg)
    _failures(
        'base creature is a Group with a mesh > 1000 vertices|#crst-hint credits Quaternius / Kenney / Smithsonian'
        "|the default #crst-hint does not say 'Pufferball'|v_3d, v_pin and v_base all in the bars"
        '|cc_base #0044ff makes the mesh colour blue-dominant|d0e44ab002ad is in /inspect/api/creatures'
    )
    assert 'own_mesh' not in A.RES['sections']['creatures']['measured']
    assert pg._seen['biggestMeshVerts'] == 80  # the whole readiness loop ran
    assert pg.shots == [os.path.join(A.OUT, 'final2_creatures.png')]


# ── studio 3 ─────────────────────────────────────────────────────────────────
def test_movement_checks_the_extractor_and_shoots(crews):
    pg = _Page()
    A.movement(pg)
    assert A.RES['failures'] == []
    assert A.RES['sections']['movement']['measured']['page']['tools'] == 9
    assert pg.shots == [os.path.join(A.OUT, 'final2_movement.png')]
    A.RES['failures'] = []  # and again with the extractor undefined
    A.movement(_Page(scripts={'moTrackExtract': {'extract': 'undefined', 'visible': 'missing', 'tools': 0}}))
    want = 'typeof moTrackExtract === \'function\' = {"extract": "undefined", "visible": "missing", "tools": 0}'
    assert A.RES['failures'] == ['movement: ' + want]


# ── studio 4 ─────────────────────────────────────────────────────────────────
def test_mesh_green_end_to_end(crews):
    pg = _Page()
    A.mesh(pg)
    assert A.RES['failures'] == []
    m = A.RES['sections']['mesh']['measured']
    assert m['nav_label'] == 'Mesh Studio' and m['tools']['all'] == 186
    assert m['opened']['picker_cards'] == 3 and m['library_card'] == {'cards': 3, 'viewer': 'flex'}
    assert pg.shots == [os.path.join(A.OUT, 'final2_mesh.png')]
    assert [c[1] for c in pg.calls if c[0] == 'click'] == ['#msh-igo']


def test_mesh_reports_a_wrong_tool_count_a_scrolling_dock_and_a_dead_viewer(crews):
    scripts = {
        'data-view': 'Meshes',
        'msh-dock': {'all': 185, 'ph': 180, 'foot_scrollW': 400, 'foot_clientW': 120},
        'MS.rec': {'rec': False, 'name': '', 'mode': '', 'd3': 'none', 'viewer': 'none'},
        "getElementById('mesh-viewer').style.display": 'none',
    }
    A.mesh(_Page(scripts=scripts))
    _failures(
        "the nav button says 'Mesh Studio'|.msh-tool count == 186|.msh-tool.ph count == 186"
        '|foot dock does not scroll sideways|picker opens a mesh: MS.rec set'
        "|#msh-3d displayed for the opened mesh|the Library tab's mesh card still opens #mesh-viewer"
    )
    assert A.RES['sections']['mesh']['measured']['tools']['foot_scrollW'] == 400


def test_mesh_shoots_anyway_when_the_toast_hangs_and_records_a_library_error(crews):
    pg = _Page()
    pg.fail_waits = ('msh-toast', 'lib-board')
    A.mesh(pg)
    lib = A.RES['sections']['mesh']['measured']['library_card']
    assert lib['cards'] == 0 and lib['viewer'] == 'none'
    assert 'timed out waiting for lib-board' in lib['error']
    assert pg.shots == [os.path.join(A.OUT, 'final2_mesh.png')]
    _failures("the Library tab's mesh card still opens #mesh-viewer")


# ── main ─────────────────────────────────────────────────────────────────────
def _run_main(monkeypatch, page, out_dir):
    """main() with the browser replaced: a one-shot playwright whose chromium hands back `page`."""
    # main() and its playwright import moved to the sibling acceptance_cli when the CLI was split out
    # of the library module, so follow it wherever it lives; it still drives this module's four studio
    # walks and the one shared RES, but OUT has to be redirected on both modules (each binds its own).
    mod = A if hasattr(A, 'main') else importlib.import_module(A.__name__ + '_cli')
    rec = {}
    br = types.SimpleNamespace(
        new_page=lambda **kw: (rec.update(viewport=kw.get('viewport')), page)[1],
        close=lambda: rec.update(closed=True),
    )
    pw = types.SimpleNamespace(chromium=types.SimpleNamespace(launch=lambda **kw: (rec.update(launch=kw), br)[1]))
    monkeypatch.setattr(A, 'OUT', str(out_dir))
    monkeypatch.setattr(mod, 'OUT', str(out_dir), raising=False)
    monkeypatch.setattr(mod, 'sync_playwright', lambda: contextlib.nullcontext(pw))
    monkeypatch.setattr(mod, 'page_offline_checks', lambda: A.measure('page', 'offline', True))
    return mod.main(), rec


def test_main_walks_all_four_studios_and_writes_the_report(tmp_path, monkeypatch, capsys):
    out = tmp_path / 'studio_verify'
    pg = _Page()
    pg.console = [types.SimpleNamespace(type='warning', text='just a warning')]
    rc, rec = _run_main(monkeypatch, pg, out)
    assert rc == 0
    assert rec['launch']['executable_path'] == '/usr/bin/google-chrome'
    assert rec['viewport'] == {'width': A.VW, 'height': A.VH} and rec['closed'] is True
    written = json.loads((out / 'acceptance.json').read_text())
    assert written['pass'] is True and written['failures'] == []
    assert written['viewport'] == [A.VW, A.VH] and written['url'].endswith('/inspection.html')
    assert sorted(written['sections']) == ['charstudio', 'creatures', 'mesh', 'movement', 'page']
    page = written['sections']['page']['measured']
    assert page['offline'] is True and page['SX_present'] is True
    assert page['console_errors'] == [] and page['console_errors_total'] == 0
    cap = capsys.readouterr().out
    assert 'wrote ' + str(out / 'acceptance.json') in cap and 'RESULT PASS — 0 failure(s)' in cap


def test_main_returns_one_and_lists_the_failures_it_found(tmp_path, monkeypatch, capsys):
    out = tmp_path / 'studio_verify'
    pg = _Page(scripts={'SX.ready': False})
    pg.console = [
        types.SimpleNamespace(type='error', text='studio_ext/char_hair.js threw'),
        types.SimpleNamespace(type='log', text='quiet'),
        'TypeError: undefined is not a function',
    ]
    rc, _ = _run_main(monkeypatch, pg, out)
    assert rc == 1
    page = A.RES['sections']['page']['measured']
    assert page['SX_present'] is False and page['console_errors_total'] == 2
    assert page['console_errors'] == [
        'console.error: studio_ext/char_hair.js threw',
        'pageerror: TypeError: undefined is not a function',
    ]
    want = 'page: no console error mentions \'studio_ext\' = ["console.error: studio_ext/char_hair.js threw"]'
    assert A.RES['failures'] == [want]
    assert json.loads((out / 'acceptance.json').read_text())['pass'] is False
    cap = capsys.readouterr().out
    assert 'RESULT FAIL — 1 failure(s)' in cap and "   ! page: no console error mentions 'studio_ext'" in cap


def test_module_constants_describe_the_operator_zoom():
    assert (A.VW, A.VH) == (2507, 1567)
    assert len(A.EXPECTED_EXT) == 8 and 'movement_track' in A.EXPECTED_EXT
    assert A.URL.endswith('/inspection.html')
    for js in (A.STAGE_JS, A.CS_PROBE, A.CS_SKIN, A.CRST_PROBE, A.CRST_INJECT, A.CRST_MEAN):
        assert isinstance(js, str) and js.strip()
    assert 'VWPX' in A.CS_PROBE and 'VWPX' in A.CS_SKIN
