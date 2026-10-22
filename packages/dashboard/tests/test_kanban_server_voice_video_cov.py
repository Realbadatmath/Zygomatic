# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage for :mod:`zyg_dashboard.kanban_server.voice_video`.

A request-handler mixin, not a blueprint: every method wants the
``BaseHTTPRequestHandler`` surface plus the sibling mixins' ``_send_json``,
``_query`` and ``_resolve_media_path``. ``_Handler`` supplies exactly that and
records what was sent, the six studio/merger accessors answer local fakes — so
every endpoint runs offline, with no GPU and no write outside ``tmp_path``.
"""

import io
import os
import sys
import json
import types

import pytest

import zyg_dashboard.kanban_server.voice_video as M


class _Rec:
    """The sibling mixins' surface, recorded instead of written to a socket."""

    def __init__(self, body=b'', query=None, media=None, length=None):
        self.rfile = io.BytesIO(body)
        self.headers = {'Content-Length': str(len(body) if length is None else length)}
        self.sent = self.code = None
        self.errors = []
        self._q = query or {}
        self.media = media or {}

    def _send_json(self, payload, code=200):
        self.sent, self.code = payload, code
        return 'json'

    def send_error(self, code, *a, **kw):
        self.errors.append(code)
        self.code = code
        return 'error'

    def _query(self):
        return self._q

    def _resolve_media_path(self, rel):
        return self.media.get(rel)


class _Handler(M._VoiceVideoMixin, _Rec):
    pass


def _mk(payload=None, **kw):
    """A handler whose request body is ``payload`` serialised as JSON."""
    if payload is not None:
        kw['body'] = json.dumps(payload).encode('utf-8')
    return _Handler(**kw)


def _boom(exc):
    def go(*a, **kw):
        raise exc

    return go


class _Fake:
    """A recording service double. ``_RETS`` maps a method name to its answer (a
    callable is handed the instance and the call); a recorded call raises ``boom``
    when one is set, and the read-only ``_QUIET`` lookups do neither."""

    _RETS: dict = {}
    _QUIET: tuple = ()
    boom = None

    def __init__(self, **kw):
        self.calls = []
        self.__dict__.update(kw)

    def _rec(self, name, *a, **kw):
        self.calls.append((name, a, kw))
        if self.boom is not None:
            raise self.boom

    def __getattr__(self, name):
        if name not in self._RETS:
            raise AttributeError(name)

        def call(*a, **kw):
            if name not in self._QUIET:
                self._rec(name, *a, **kw)
            r = self._RETS[name]
            return r(self, *a, **kw) if callable(r) else r

        return call


class _VS(_Fake):
    """Voice Studio."""

    voice_ok = True
    _QUIET = ('list_presets', 'voice', 'job', 'resolve_audio')
    _RETS = {
        'start_render': {'id': 'j1'},
        'save_preset': lambda s, vid, name, params, **kw: {'slug': kw['slug'] or 'auto', 'name': name},
        'delete_preset': True,
        'set_active': None,
        'start_prerender': {'id': 'p1', 'total': 3},
        'cancel_job': True,
        'start_bake': None,
        'stop_bake': None,
        'library_status': {'baking': False},
        'list_presets': {'presets': [], 'active': ''},
        'voice': lambda s, vid: {'id': vid} if s.voice_ok else None,
        'job': lambda s, jid: {'wav': 'take.wav'} if jid == 'done' else None,
        'resolve_audio': lambda s, rel: '/abs/' + rel if rel else '',
    }


_VA = type('_VA', (_Fake,), {'_RETS': {'save': lambda s, v, chars, w, **kw: {'voice': v, 'characters': chars}}})
_VST = type('_VST', (_Fake,), {'_RETS': {'generate': {'id': 's1'}}})  # still generation


class _VD(_Fake):
    """Video Studio. ``sanitize`` hands back a FRESH dict: the draft writes into it."""

    clean = None
    job_rec = None
    _QUIET = ('job', 'sanitize', 'compose_prompt', 'compose_link_prompts', 'presets')
    _RETS = {
        'job': lambda s, jid: s.job_rec,
        'sanitize': lambda s, params: dict(s.clean if s.clean is not None else params),
        'start_render': {'id': 'v1'},
        'start_render_from_video': {'id': 'v2'},
        'start_assemble': {'id': 'a1'},
        'compose_prompt': lambda s, params, subject: ('a ' + subject, None),
        'compose_link_prompts': lambda s, p, subject, n: [(f'link {i}', '') for i in range(n)],
        'preset_save': lambda s, name, params: name or 'untitled',
        'presets': ['untitled'],
        'preset_load': {'fps': 8},
        'preset_delete': None,
    }


class _MG(_Fake):
    """Both mixers. Every answer a handler decorates with a URL must be fresh."""

    mix = 'mix/out.wav'
    _RETS = {
        'render_mix': lambda s, items: {'mix': s.mix, 'items': [{'stem': 'stems/a.wav'}]},
        'stem': lambda s, cat, f, slots: {'stem': 'stems/b.wav'},
        'analyze': lambda s, cat, f, slots, **kw: {'lufs': -16.0, 'pictures': {'wave': 'pics/w.png'}},
        'export_mix': lambda s, items, **kw: {'export': 'exp/m.wav', 'bytes': 2048, 'format': kw['fmt'], **kw},
        'save_mix': lambda s, name, items: {
            'cat': 'merged',
            'file': 'take one.wav',
            'recipe': {'items': items},
            'duration': 1.25,
            'licence': 'CC0',
        },
        'voice_ref': {'ref': 'whole'},
        'take_ref': {'ref': 'take'},
        'check_sources': [True, False],
    }

    def save_recording(self, tmp, name):
        """Real, not table-driven: the size on disk proves the loop wrote every byte."""
        self._rec('save_recording', tmp, name, os.path.getsize(tmp))
        return {'cat': 'recorded', 'file': 'mic.wav', 'duration': 1.5}


@pytest.fixture(autouse=True)
def _no_service(monkeypatch, tmp_path):
    """Nothing resolves to a real studio, and temp uploads stay under tmp_path."""
    for name in ('_voice_studio', '_voice_assign', '_video_studio', '_video_stills', '_sfx_merger', '_voice_merger'):
        monkeypatch.setattr(M, name, lambda: None)
    monkeypatch.setattr(M, '_ALIB_CACHE', {'stale': 1})
    monkeypatch.setattr(M.tempfile, 'tempdir', str(tmp_path))


@pytest.fixture(autouse=True)
def log(caplog):
    """The module reports through `_zyg_log` at INFO; tests read `log.text`."""
    caplog.set_level('INFO', logger=M._zyg_log.name)
    return caplog


@pytest.fixture
def api(monkeypatch):
    """Every accessor answers a fresh fake. ``api.post(meth, *args, payload=…)``
    runs one request and hands back the handler; ``api.swap`` installs a variant."""
    made = [('vs', '_voice_studio', _VS()), ('va', '_voice_assign', _VA()), ('vd', '_video_studio', _VD())]
    made += [('vst', '_video_stills', _VST()), ('sfx', '_sfx_merger', _MG()), ('vm', '_voice_merger', _MG())]
    ns = types.SimpleNamespace(**{short: fake for short, _accessor, fake in made})
    ns.swap = lambda accessor, fake: monkeypatch.setattr(M, accessor, lambda: fake)
    for _short, accessor, fake in made:
        ns.swap(accessor, fake)

    def post(meth, *args, payload=None, **kw):
        h = _mk(payload, **kw)
        getattr(h, meth)(*args)
        return h

    ns.post = post
    return ns


_DISPATCH = 'accessor, svc, meth, path, bad'
_DISPATCHERS = [
    ('_voice_studio', _VS, '_voice_post', '/voice/api/render', '/voice/api/nope'),
    ('_video_studio', _VD, '_video_post', '/video/api/assemble', '/video/api/nope'),
    ('_sfx_merger', _MG, '_merge_post', '/inspect/api/merge/stem', '/inspect/api/merge/nope'),
    ('_voice_merger', _MG, '_voice_merge_post', '/voice/api/merge/stem', '/voice/api/merge/nope'),
]
_MIXER = 'meth, prefix, fake, audio'
_MIXERS = [
    ('_merge_post', '/inspect/api/merge', 'sfx', '/inspect/merge/audio?p='),
    ('_voice_merge_post', '/voice/api/merge', 'vm', '/voice/merge/audio?p='),
]
_RECORDERS = [('_merge_record', '_sfx_merger'), ('_voice_merge_record', '_voice_merger')]


@pytest.mark.parametrize(
    'body, length, expect',
    [
        (b'{"a": 1}', None, {'a': 1}),
        (b'', None, {}),
        (b'{"a": 1}', 'not-a-number', {}),
        (b'x' * 40, 70000, {}),
        (b'{nope', None, {}),
        (b'[1, 2]', None, {}),
        (b'\xff\xfe', None, {}),
    ],
)
def test_a_json_body_is_a_dict_or_nothing(body, length, expect):
    assert _Handler(body=body, length=length)._json_body() == expect


def test_a_body_the_socket_cannot_deliver_reads_as_empty():
    h = _Handler(body=b'{"a": 1}')
    h.rfile = types.SimpleNamespace(read=_boom(ConnectionResetError('gone')))
    assert h._json_body() == {}


@pytest.mark.parametrize(
    'meth, args, want',
    [
        ('_voice_post', ('/voice/api/render',), 'voice studio unavailable'),
        ('_video_post', ('/video/api/render',), 'video studio unavailable'),
        ('_merge_post', ('/inspect/api/merge/render',), 'sfx merger unavailable'),
        ('_voice_merge_post', ('/voice/api/merge/render',), 'voice merger unavailable'),
        ('_merge_record', (), 'sfx merger unavailable'),
        ('_voice_merge_record', (), 'voice merger unavailable'),
    ],
)
def test_every_api_answers_503_when_its_service_is_missing(meth, args, want):
    h = _mk({})
    getattr(h, meth)(*args)
    assert h.code == 503 and want in h.sent['error']


@pytest.mark.parametrize(
    'meth, path, payload, want',
    [
        ('_voice_post', '/voice/api/render', {'voice': 'ada', 'text': 'hi'}, {'ok': True, 'job': {'id': 'j1'}}),
        ('_voice_post', '/voice/api/preset/delete', {'slug': 'warm'}, {'ok': True, 'presets': [], 'active': ''}),
        ('_voice_post', '/voice/api/preset/activate', {'slug': 'warm'}, {'ok': True, 'presets': [], 'active': ''}),
        ('_voice_post', '/voice/api/prerender/cancel', {'job': 'p1'}, {'ok': True}),
        ('_video_post', '/video/api/assemble', {'params': {'shots': []}}, {'ok': True, 'job': {'id': 'a1'}}),
        ('_video_post', '/video/api/preset/save', {'name': 'd'}, {'ok': True, 'name': 'd', 'presets': ['untitled']}),
        ('_video_post', '/video/api/preset/load', {'name': 'd'}, {'ok': True, 'params': {'fps': 8}}),
        ('_video_post', '/video/api/preset/delete', {'name': 'd'}, {'ok': True, 'presets': ['untitled']}),
        ('_voice_merge_post', '/voice/api/merge/check', {'items': []}, {'ok': True, 'exists': [True, False]}),
    ],
)
def test_the_plain_routes_hand_back_what_their_service_answered(api, meth, path, payload, want):
    h = api.post(meth, path, payload=payload)
    assert (h.code, h.sent) == (200, want)


@pytest.mark.parametrize(
    'meth, fake, path, payload, called',
    [
        ('_voice_post', 'vs', '/voice/api/bake', {}, 'start_bake'),
        ('_voice_post', 'vs', '/voice/api/bake', {'stop': True}, 'stop_bake'),
        ('_voice_merge_post', 'vm', '/voice/api/merge/ref', {'voice': 'ada'}, 'take_ref'),
        ('_voice_merge_post', 'vm', '/voice/api/merge/ref', {'whole_voice': True}, 'voice_ref'),
    ],
)
def test_a_paired_route_calls_the_half_its_body_asked_for(api, meth, fake, path, payload, called):
    h = api.post(meth, path, payload=payload)
    assert h.code == 200
    assert getattr(api, fake).calls[0][0] == called


def test_saving_a_preset_freezes_the_jobs_preview_wav(api, log):
    body = {'voice': 'ada', 'name': 'Warm', 'slug': 'warm', 'job': 'done', 'metrics': {'lufs': -18}}
    h = api.post('_voice_post', '/voice/api/preset/save', payload=body)
    assert (h.code, h.sent['preset']) == (200, {'slug': 'warm', 'name': 'Warm'})
    assert api.vs.calls[0][1] == ('ada', 'Warm', {})
    assert api.vs.calls[0][2]['preview_wav'] == '/abs/take.wav'
    assert 'voice preset saved: ada/warm' in log.text


@pytest.mark.parametrize('jid, want', [('', ''), ('missing', ''), ('done', '/abs/take.wav')])
def test_only_a_finished_job_has_a_preview_wav(jid, want):
    assert M._VoiceVideoMixin._voice_job_wav(_VS(), jid) == want


def test_the_starter_tier_is_installed_on_demand(api, monkeypatch, log):
    import zyg_workflows

    fake = types.SimpleNamespace(install=lambda vid: ['a.json', 'b.json'])
    monkeypatch.setitem(sys.modules, 'zyg_workflows.voice_presets_starter', fake)
    monkeypatch.setattr(zyg_workflows, 'voice_presets_starter', fake, raising=False)
    h = api.post('_voice_post', '/voice/api/preset/starters', payload={'voice': 'ada'})
    assert (h.code, h.sent['written']) == (200, 2) and 'starter presets for ada: 2 written' in log.text


def test_a_prerender_reports_how_many_presets_it_queued(api, log):
    h = api.post('_voice_post', '/voice/api/prerender', payload={'voice': 'ada', 'text': 'hi', 'force': True})
    assert (h.sent, api.vs.calls[0][2]) == ({'ok': True, 'job': {'id': 'p1', 'total': 3}}, {'force': True})
    assert 'pre-render ada: 3 preset(s), job p1' in log.text


@pytest.mark.parametrize(
    'assign, voice_ok, code, want',
    [(False, True, 503, 'assignments unavailable'), (True, False, 400, 'unknown voice')],
)
def test_an_assignment_needs_its_module_and_a_known_voice(api, assign, voice_ok, code, want):
    api.swap('_voice_studio', _VS(voice_ok=voice_ok))
    if not assign:
        api.swap('_voice_assign', None)
    h = api.post('_voice_post', '/voice/api/assign/save', payload={'voice': 'ada'})
    assert h.code == code and want in h.sent['error']


def test_an_assignment_is_capped_and_logged(api, log):
    body = {'voice': 'ada', 'characters': list(range(2100)), 'workflows': ['w1'], 'preset': 'warm'}
    h = api.post('_voice_post', '/voice/api/assign/save', payload=body)
    assert h.code == 200
    assert len(api.va.calls[0][1][1]) == 2000 and api.va.calls[0][1][1][0] == '0'
    assert 'voice assign ada: 2000 character(s), 1 workflow(s)' in log.text


@pytest.mark.parametrize(_DISPATCH, _DISPATCHERS)
@pytest.mark.parametrize('boom, want_code', [(ValueError('no good'), 400), (RuntimeError('exploded'), 500)])
def test_a_raising_service_400s_or_500s_and_an_unknown_path_404s(api, accessor, svc, meth, path, bad, boom, want_code):
    api.swap(accessor, svc(boom=boom))
    h = api.post(meth, path, payload={'items': []})
    assert h.code == want_code
    assert 'no good' in h.sent['error'] or 'RuntimeError: exploded' in h.sent['error']
    assert api.post(meth, bad, payload={}).errors == [404]


def test_a_render_from_a_still_takes_the_images_basename_as_its_label(api, log):
    body, media = {'src_image': {'path': 'out/_stills/dawn.png'}}, {'out/_stills/dawn.png': '/abs/dawn.png'}
    h = api.post('_video_post', '/video/api/render', payload=body, media=media)
    assert (h.sent, api.vd.calls[0][1][:3]) == (
        {'ok': True, 'job': {'id': 'v1'}},
        ('still', 'dawn.png', '/abs/dawn.png'),
    )
    assert 'video render (from still) started: dawn.png job v1' in log.text


def test_a_render_continues_an_existing_clip(api, log):
    body = {'src_video': {'path': 'out/v/clip.mp4'}, 'video_id': 'c7', 'video_label': 'Shot 7'}
    h = api.post('_video_post', '/video/api/render', payload=body, media={'out/v/clip.mp4': '/abs/clip.mp4'})
    assert (h.sent, api.vd.calls[0][1][:3]) == ({'ok': True, 'job': {'id': 'v2'}}, ('c7', 'Shot 7', '/abs/clip.mp4'))
    assert 'video render (continue clip) started: Shot 7 job v2' in log.text


@pytest.mark.parametrize(
    'payload, media, want',
    [
        ({'src_image': {'path': 'nope.png'}}, {}, 'still not found'),
        ({'src_image': {'path': 'a.txt'}}, {'a.txt': '/abs/a.txt'}, 'still not found'),
        ({'src_video': {'path': 'nope.mp4'}}, {}, 'video not found'),
        ({'src_video': {'path': 'a.mov'}}, {'a.mov': '/abs/a.mov'}, 'video not found'),
    ],
)
def test_a_render_source_outside_the_whitelist_is_a_400(api, payload, media, want):
    h = api.post('_video_post', '/video/api/render', payload=payload, media=media)
    assert (h.code, h.sent) == (400, {'error': want})


def test_a_still_needs_the_still_module(api):
    api.swap('_video_stills', None)
    h = api.post('_video_post', '/video/api/still', payload={'prompt': 'a dawn'})
    assert h.code == 503 and 'still generation unavailable' in h.sent['error']


@pytest.mark.parametrize(
    'payload, want',
    [
        ({}, 'prompt is required'),
        ({'prompt': ' '}, 'prompt is required'),
        ({'prompt': 'p' * 2001}, 'prompt too long (max 2000 chars)'),
        ({'prompt': 'p', 'width': 'wide'}, 'width must be a number'),
        ({'prompt': 'p', 'width': 256}, 'width must be 512..1536 and a multiple of 16'),
        ({'prompt': 'p', 'height': 721}, 'height must be 512..1536 and a multiple of 16'),
        ({'prompt': 'p', 'seed': 'lucky'}, 'seed must be a number'),
    ],
)
def test_a_malformed_still_request_is_a_400(api, payload, want):
    h = api.post('_video_post', '/video/api/still', payload=payload)
    assert (h.code, h.sent) == (400, {'error': want})


def test_a_still_is_queued_with_the_dimensions_qwen_wants(api, log):
    body = {'prompt': 'a dawn', 'width': 1024, 'height': 576, 'seed': 7, 'medusa': True, 'label': 'dawn'}
    h = api.post('_video_post', '/video/api/still', payload=body)
    assert h.sent == {'ok': True, 'job': {'id': 's1'}}
    assert api.vst.calls[0][1:] == (('a dawn', 1024, 576, 7, '', 'qwen', 'dawn'), {'medusa': True})
    assert 'still generation started: job s1 1024x576' in log.text


@pytest.mark.parametrize(
    'frames, want',
    [(16, [['link 0', ''], ['link 1', ''], ['link 2', '']]), ('many', [['a a fox', '']])],
)
def test_the_prompt_preview_shows_every_link_or_falls_back_to_one(api, frames, want):
    api.swap('_video_studio', _VD(clean={'frames': frames, 'fps': 8, 'duration_s': 6}))
    h = api.post('_video_post', '/video/api/prompt', payload={'subject': 'a fox', 'params': {}})
    assert (h.sent['positive'], h.sent['negative'], h.sent['links']) == ('a a fox', '', want)


@pytest.fixture
def vs_out(tmp_path, monkeypatch):
    """A Video Studio output tree with one rendered clip in a job dir."""
    (tmp_path / 'video_studio' / 'j1').mkdir(parents=True)
    clip = tmp_path / 'video_studio' / 'j1' / 'clip.mp4'
    clip.write_bytes(b'MP4')
    monkeypatch.setattr(M._VoiceVideoMixin, '_VS_OUT', str(tmp_path / 'video_studio'))
    return clip


@pytest.fixture
def vfx_place(monkeypatch):
    """A stand-in for zyg_workflows.vfx_place that never touches ffmpeg."""
    import zyg_workflows

    el = {'key': 'smoke', 'name': 'Smoke', 'mode': 'over', 'w': 8, 'h': 8, 'draft_only': False, 'x': 1}
    rec = {'placement': {'depth': 2.5}, 'camera': {'fov': 40}, 'cam_source': 'scene shot', 'element': el}
    fake = types.SimpleNamespace(
        DRAFT_WIDTH=320,
        plan=lambda clip, params, draft=False: rec,
        draft=lambda clip, params, out: (open(out, 'wb').write(b'draft'), 0.5)[1],
    )
    monkeypatch.setitem(sys.modules, 'zyg_workflows.vfx_place', fake)
    monkeypatch.setattr(zyg_workflows, 'vfx_place', fake, raising=False)
    return fake


def test_a_draft_without_the_placement_module_is_a_400(api, monkeypatch):
    import zyg_workflows

    monkeypatch.delattr(zyg_workflows, 'vfx_place', raising=False)
    monkeypatch.setitem(sys.modules, 'zyg_workflows.vfx_place', None)
    h = api.post('_video_post', '/video/api/vfx/draft', payload={})
    assert h.code == 400 and 'vfx placement unavailable' in h.sent['error']


@pytest.mark.parametrize(
    'rel, use_media, want',
    [
        ('out/video_studio/j1/ghost.mp4', False, 'clip not found'),
        ('out/n.txt', True, 'clip not found'),
        ('far/c.mp4', True, 'a VFX draft only runs on a Video Studio clip'),
        ('out/video_studio/j1/clip.mp4', True, 'pick a VFX element first'),
    ],
)
def test_a_draft_refuses_anything_but_a_studio_clip_with_an_element(api, vs_out, vfx_place, rel, use_media, want):
    media = {'out/n.txt': 'x.txt', 'far/c.mp4': 'y.mp4', 'out/video_studio/j1/clip.mp4': str(vs_out)}
    h = api.post('_video_post', '/video/api/vfx/draft', payload={'clip': rel}, media=media if use_media else {})
    assert (h.code, h.sent) == (400, {'error': want})


@pytest.mark.parametrize(
    'job_rec, shot', [(None, ''), ({'url': '/inspect/media?path=out/video_studio/j1/clip.mp4'}, 'sh010')]
)
def test_a_draft_resolves_the_clip_from_a_job_id_and_honours_its_camera(api, vs_out, vfx_place, log, job_rec, shot):
    settings = json.dumps({'changed': {'scene_shot': shot}}) if shot else '{ not json'
    (vs_out.parent / 'clip.settings.json').write_text(settings)
    (vs_out.parent / 'vfx_draft_1.mp4').write_bytes(b'old')
    api.swap('_video_studio', _VD(job_rec=job_rec, clean={'vfx_element': 'smoke'}))
    media = {'out/video_studio/j1/clip.mp4': str(vs_out)}
    h = api.post('_video_post', '/video/api/vfx/draft', payload={'job_id': 'j1', 'params': {}}, media=media)
    assert (h.code, h.sent['url']) == (200, '/inspect/media?path=out/video_studio/j1/vfx_draft_2.mp4')
    assert (h.sent['seconds'], h.sent['width']) == (0.5, 320)
    assert h.sent['element'] == {'key': 'smoke', 'name': 'Smoke', 'mode': 'over', 'w': 8, 'h': 8, 'draft_only': False}
    assert 'j1/vfx_draft_2.mp4 — Smoke at 2.50m in 0.50s (camera scene shot)' in log.text


@pytest.mark.parametrize(_MIXER, _MIXERS)
def test_a_render_without_an_items_list_is_a_400(api, meth, prefix, fake, audio):
    h = api.post(meth, prefix + '/render', payload={'items': 'all of them'})
    assert (h.code, h.sent) == (400, {'error': 'no items in request body'})


@pytest.mark.parametrize(_MIXER, _MIXERS)
@pytest.mark.parametrize('mix', ['mix/out.wav', ''])
def test_a_rendered_mix_gets_a_playable_url_per_stem(api, meth, prefix, fake, audio, mix):
    api.swap('_sfx_merger' if fake == 'sfx' else '_voice_merger', _MG(mix=mix))
    h = api.post(meth, prefix + '/render', payload={'items': [{'cat': 'foley'}]})
    assert h.code == 200
    assert h.sent.get('url') == (audio + mix if mix else None)
    assert h.sent['items'][0]['url'] == audio + 'stems/a.wav'


@pytest.mark.parametrize(_MIXER, _MIXERS)
def test_one_stem_is_rendered_on_its_own(api, meth, prefix, fake, audio):
    h = api.post(meth, prefix + '/stem', payload={'cat': 'foley', 'f': 'door.wav', 'slots': [{'gain': 1}]})
    assert h.sent == {'stem': 'stems/b.wav', 'ok': True, 'url': audio + 'stems/b.wav'}
    assert getattr(api, fake).calls[0][1] == ('foley', 'door.wav', [{'gain': 1}])


@pytest.mark.parametrize(_MIXER, _MIXERS)
def test_a_saved_mix_invalidates_the_library_list(api, log, meth, prefix, fake, audio):
    h = api.post(meth, prefix + '/save', payload={'name': 'take one', 'items': [{'cat': 'foley'}]})
    assert h.sent['url'] == '/inspect/sfx?cat=merged&f=take%20one.wav'
    assert M._ALIB_CACHE == {}
    assert 'merge saved: merged/take one.wav' in log.text and '1 layers, 1.250 s, licence CC0' in log.text


@pytest.mark.parametrize('payload, pictures', [({}, True), ({'pictures': False}, False)])
def test_an_analysis_links_its_pictures_through_the_asset_route(api, payload, pictures):
    h = api.post('_merge_post', '/inspect/api/merge/analyze', payload={'cat': 'foley', 'f': 'd.wav', **payload})
    assert h.sent['pictures'] == {'wave': '/inspect/merge/asset?p=pics/w.png'}
    assert api.sfx.calls[0][2] == {'pictures': pictures}


def test_an_export_is_logged_and_linked_with_a_download_name(api, log):
    body = {'items': [], 'format': 'flac', 'rate': 44100, 'name': 'door slam'}
    h = api.post('_merge_post', '/inspect/api/merge/export', payload=body)
    assert h.sent['url'] == '/inspect/merge/asset?p=exp/m.wav&dl=door%20slam'
    assert api.sfx.calls[0][2] == {'fmt': 'flac', 'rate': 44100, 'dither': 'triangular_hp'}
    assert 'sfx export: exp/m.wav (flac @ 44100 Hz, 2048 bytes)' in log.text


@pytest.mark.parametrize('meth, accessor', _RECORDERS)
@pytest.mark.parametrize(
    'length, want_code, want',
    [
        ('eleven', 400, 'bad Content-Length'),
        (0, 400, 'empty recording'),
        (M._REC_MAX_UPLOAD + 1, 413, 'recording is 60 MB; the cap is 60 MB'),
    ],
)
def test_a_recording_is_refused_before_a_byte_is_read(api, meth, accessor, length, want_code, want):
    h = api.post(meth, length=length)
    assert (h.code, h.sent) == (want_code, {'error': want})


@pytest.mark.parametrize('meth, accessor', _RECORDERS)
@pytest.mark.parametrize('unlink_ok', [True, False])
def test_an_upload_the_socket_cuts_short_is_a_400(api, monkeypatch, meth, accessor, unlink_ok):
    # Both halves of the read loop: a short socket and a raising one. The temp
    # file's removal is best effort — a failing unlink only logs.
    if not unlink_ok:
        monkeypatch.setattr(M.os, 'unlink', _boom(OSError('busy')))
    h = api.post(meth, body=b'audio', length=32)
    assert (h.code, h.sent) == (400, {'error': 'truncated upload: 5/32 bytes'})

    broken = _Handler(length=32)
    broken.rfile = types.SimpleNamespace(read=_boom(OSError('reset')))
    getattr(broken, meth)()
    assert broken.code == 400
    assert broken.sent['error'].startswith('upload failed after 0 bytes:')


@pytest.mark.parametrize('meth, accessor', _RECORDERS)
@pytest.mark.parametrize(
    'boom, want_code, want',
    [
        (ValueError('not audio'), 400, 'not audio'),
        (RuntimeError('ffprobe gone'), 500, 'RuntimeError: ffprobe gone'),
    ],
)
def test_a_recording_the_merger_rejects_never_500s_silently(api, meth, accessor, boom, want_code, want):
    api.swap(accessor, _MG(boom=boom))
    h = api.post(meth, body=b'audio')
    assert (h.code, h.sent) == (want_code, {'error': want})


@pytest.mark.parametrize('meth, accessor', _RECORDERS)
@pytest.mark.parametrize('unlink_ok', [True, False])
def test_an_adopted_mic_take_lands_in_the_library(api, monkeypatch, log, meth, accessor, unlink_ok):
    mg = _MG()
    api.swap(accessor, mg)
    if not unlink_ok:
        monkeypatch.setattr(M.os, 'unlink', _boom(OSError('busy')))
    h = api.post(meth, body=b'audio' * 300, query={'name': 'take ' + 'x' * 200})
    assert (h.code, h.sent) == (200, {'cat': 'recorded', 'file': 'mic.wav', 'duration': 1.5})
    assert M._ALIB_CACHE == {}
    assert len(mg.calls[0][1][1]) == 120 and mg.calls[0][1][2] == 1500
    assert 'recording saved' in log.text and 'mic.wav' in log.text
