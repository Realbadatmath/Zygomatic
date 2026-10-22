# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline coverage tests for character_photo_analysis_service: every outbound call (Ollama HTTP,
the anthropic SDK, the blender service import) is faked, so this runs with no network and no GPU."""

from __future__ import annotations

import builtins
import itertools
import json
import sys
import time
import types
from typing import Any

import pytest
import zyg_workflows
from zyg_workflows import character_photo_analysis_service as MOD

MP = pytest.MonkeyPatch

# One raw vision answer that exercises every branch of normalize_analysis: alias values
# ('woman', 'brunette', 'clean shaven'), numeric strings, a height that must be snapped.
_FULL_RAW: dict[str, Any] = json.loads(
    '{"gender": "woman", "age": "31.4", "hair_color": "brunette", "eye_color": "hazel",'
    ' "skin_tone": "olive", "height": 1.73, "facial_hair": "clean shaven", "muscle_mass": 42,'
    ' "hair_style": "long wavy", "hair_length": "shoulder", "hair_texture": "wavy",'
    ' "face_shape": "oval", "eye_shape": "almond", "eyebrow_style": "natural arched",'
    ' "nose_shape": "balanced", "lip_shape": "natural full", "distinctive_marks": "small scar",'
    ' "ethnic_heritage": "southern european", "default_clothing": "grey knit sweater",'
    ' "default_expression": "warm welcoming", "accessories": "thin gold necklace",'
    ' "posture": "relaxed, shoulders square",'
    ' "per_image_caption": "TRIGGER_TOKEN woman, brown hair, hazel eyes"}'
)


class _Resp:
    def __init__(self, status_code: int = 200, payload: Any = None):
        self.status_code = status_code
        self._payload = {} if payload is None else payload

    def json(self) -> Any:
        return self._payload


def _raise(*_a: Any, **_k: Any) -> Any:
    raise OSError('connection refused')


class _FakeRequests:
    """Stand-in for the `requests` module the service imports lazily."""

    def __init__(self) -> None:
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []
        self.get_handler = lambda url, **kw: _Resp(200, {'models': []})
        self.post_handler = lambda url, **kw: _Resp(200, {})

    def get(self, url: str, **kw: Any) -> _Resp:
        self.get_calls.append((url, kw))
        return self.get_handler(url, **kw)

    def post(self, url: str, **kw: Any) -> _Resp:
        self.post_calls.append((url, kw))
        return self.post_handler(url, **kw)


@pytest.fixture
def req(monkeypatch: MP) -> _FakeRequests:
    fake = _FakeRequests()
    monkeypatch.setitem(sys.modules, 'requests', fake)
    monkeypatch.setattr(time, 'sleep', lambda _s: None)
    return fake


@pytest.fixture
def no_net(monkeypatch: MP) -> None:
    """Neutralise every outbound call analyze_* can reach."""
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.setattr(MOD, '_wait_ollama_unload', lambda *a, **k: None)
    monkeypatch.setattr(MOD, 'evict_ollama_model', lambda *a, **k: None)
    monkeypatch.setattr(MOD, '_ollama_list_loaded', lambda: [])


def _install_anthropic(mp: MP, *, text: str = '', exc: Exception | None = None, empty: bool = False):
    class _Messages:
        def create(self, **_kw: Any) -> Any:
            if exc is not None:
                raise exc
            return types.SimpleNamespace(content=[] if empty else [types.SimpleNamespace(text=text)])

    mod = types.ModuleType('anthropic')
    mod.Anthropic = lambda api_key=None: types.SimpleNamespace(messages=_Messages())  # type: ignore[attr-defined]
    mp.setitem(sys.modules, 'anthropic', mod)
    mp.setenv('ANTHROPIC_API_KEY', 'test-key')


def _chat(obj: Any) -> dict[str, Any]:
    return {'message': {'content': json.dumps(obj)}}


def _fake_bcs(monkeypatch: MP, *, broken: bool = False) -> None:
    def _style(style: str) -> str:
        if broken:
            raise RuntimeError('no style table')
        return f'{style} look'

    mod = types.ModuleType('zyg_workflows.blender_character_service')
    mod.caption_style_description = _style  # type: ignore[attr-defined]
    monkeypatch.setattr(zyg_workflows, 'blender_character_service', mod, raising=False)


def _patch_open(monkeypatch: MP, bad_suffix: str) -> None:
    real_open = builtins.open

    def _open(path: Any, *a: Any, **k: Any) -> Any:
        if str(path).endswith(bad_suffix):
            raise OSError('permission denied')
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, 'open', _open)


def _result(backend: Any, fields: dict[str, Any], caption: str, conf: str, amb: list[str]) -> dict[str, Any]:
    """One analyze_image_bytes return value, as analyze_photo_paths consumes it."""
    keys = ('ok', 'backend', 'fields', 'per_image_caption', 'confidence', 'ambiguous_fields')
    return dict(zip(keys, (True, backend, fields, caption, conf, amb)))


_FLAG_FNS = [
    (MOD.analysis_enabled, 'ZYG_CHAR_PHOTO_ANALYSIS'),
    (MOD.prefer_ollama, 'ZYG_CHAR_PHOTO_PREFER_OLLAMA'),
    (MOD.consensus_enabled, 'ZYG_CHAR_PHOTO_CONSENSUS'),
]
_FLAG_VALUES = [(None, True), ('1', True), ('yes', True), (' TRUE ', True)]
_FLAG_VALUES += [('0', False), ('false', False), ('No', False), (' OFF ', False)]


@pytest.mark.parametrize(('fn', 'env'), _FLAG_FNS)
@pytest.mark.parametrize(('value', 'expected'), _FLAG_VALUES)
def test_flags(monkeypatch: MP, fn: Any, env: str, value: str | None, expected: bool) -> None:
    if value is None:
        monkeypatch.delenv(env, raising=False)
    else:
        monkeypatch.setenv(env, value)
    assert fn() is expected


def test_module_constants_sane() -> None:
    assert MOD.CONSENSUS_N >= 2 and MOD.OLLAMA_VISION_NUM_CTX > 0 and MOD.OLLAMA_VISION_NUM_PREDICT > 0
    assert 'JSON' in MOD._SYSTEM_PROMPT and 'per_image_caption' in MOD._USER_PROMPT


# One-argument pure helpers, packed as (function, [(argument, expected), …]).
_ONE_ARG: list[tuple[Any, list[tuple[Any, Any]]]] = [
    (MOD._parse_json, [('', None), ('   ', None), ('no braces here', None), ('{not json}', None)]),
    (MOD._parse_json, [('[1, 2]', None), ('noise {"a": 1} tail {"b": 2}', None), ('prefix {"a": 1} suffix', {'a': 1})]),
    (MOD._parse_json, [('```json\n{"a": [1, 2]}\n```', {'a': [1, 2]})]),
    (MOD._norm, [(None, ''), ('', ''), ('  A  b\n c ', 'a b c'), (12, '12')]),
    (MOD._snap_height, [(None, None), (1.73, '1.75'), ('1.60', '1.60'), (0.1, '1.10'), (9.9, '2.10'), ('nope', None)]),
    (MOD._snap_muscle, [(None, None), ('nope', None), (0, 1), (500, 100), ('42.9', 42)]),
    (MOD._snap_age, [(None, None), ('nope', None), (-5, 1), (140, 99), ('31.4', 31)]),
    (MOD._match_hair_style, [(None, None), ('', None), ('AUTO', 'auto'), ('pixie cut', 'pixie cut')]),
    (MOD._match_hair_style, [('very long wavy hair', 'long wavy'), ('an impressive afro today', 'afro')]),
    (MOD._match_hair_style, [('xqz wrapped headscarf qqq', 'xqz wrapped headscarf qqq')]),
    (MOD._is_auto, [(None, True), ('', True), ('  auto ', True), ('none-selected', True), ('default', True)]),
    (MOD._is_auto, [('(auto)', True), ('long wavy', False), (7, False)]),
]
_PURE_CASES: list[tuple[Any, tuple[Any, ...], Any]] = [
    (fn, (arg,), expected) for fn, cases in _ONE_ARG for arg, expected in cases
]
_PURE_CASES += [
    (MOD._pick_enum, (None, MOD.GENDER_VALUES, 'male'), 'male'),
    (MOD._pick_enum, ('   ', MOD.GENDER_VALUES, 'male'), 'male'),
    (MOD._pick_enum, ('female', MOD.GENDER_VALUES), 'female'),
    (MOD._pick_enum, ('dark brown hair', MOD.HAIR_COLOR_VALUES), 'brown'),
    (MOD._pick_enum, ('gray', MOD.HAIR_COLOR_VALUES), 'grey'),
    (MOD._pick_enum, ('woman', MOD.GENDER_VALUES), 'female'),
    (MOD._pick_enum, ('man', MOD.GENDER_VALUES), 'male'),
    (MOD._pick_enum, ('qqqqqqqqqq', MOD.GENDER_VALUES), None),
    (MOD._pick_enum, ('zzzzzzzzzz', MOD.EYE_COLOR_VALUES, 'brown'), 'brown'),
]


@pytest.mark.parametrize(('fn', 'args', 'expected'), _PURE_CASES)
def test_pure_helpers(fn: Any, args: tuple[Any, ...], expected: Any) -> None:
    assert fn(*args) == expected


# What normalize_analysis must make of _FULL_RAW.
_NORM_EXPECT: dict[str, Any] = json.loads(
    '{"gender": "female", "age": 31, "hair_color": "brown", "eye_color": "hazel",'
    ' "skin_tone": "olive", "height": "1.75", "facial_hair": "none", "muscle_mass": 42,'
    ' "hair_style": "long wavy", "default_expression": "warm welcoming",'
    ' "posture": "relaxed, shoulders square"}'
)


def test_normalize_analysis_empty() -> None:
    assert MOD.normalize_analysis(None) == {}
    assert MOD.normalize_analysis({}) == {}


def test_normalize_analysis_full() -> None:
    out = MOD.normalize_analysis(_FULL_RAW)
    assert {k: out[k] for k in _NORM_EXPECT} == _NORM_EXPECT
    assert out['per_image_caption'].startswith('TRIGGER_TOKEN')


def test_normalize_analysis_sentinels_and_aliases() -> None:
    raw = {'distinctive_marks': ' N/A ', 'accessories': 'NONE', 'height_m': '1.60'}
    out = MOD.normalize_analysis({**raw, 'caption': 'fallback caption', 'ethnic_heritage': '   ', 'posture': ''})
    assert out['distinctive_marks'] == 'none'
    assert out['accessories'] == 'none'
    assert out['height'] == '1.60'
    assert out['per_image_caption'] == 'fallback caption'
    assert 'ethnic_heritage' not in out and 'posture' not in out


def test_merge_no_analysis_returns_same_object() -> None:
    params = {'gender': 'male'}
    assert MOD.merge_analysis_into_params(params, None) is params
    assert MOD.merge_analysis_into_params(params, {}) is params


def test_merge_core_overwrites_identity_respects_auto() -> None:
    params = {'gender': 'male', 'hair_style': 'crew cut', 'hair_length': 'auto'}
    out = MOD.merge_analysis_into_params(
        {**params, 'default_clothing': 'tuxedo', 'accessories': ''}, {'fields': _FULL_RAW}
    )
    assert out['gender'] == 'female'
    assert out['hair_style'] == 'crew cut'
    assert out['hair_length'] == 'shoulder'
    assert out['default_clothing'] == 'tuxedo'
    assert out['accessories'] == 'thin gold necklace'
    assert params['gender'] == 'male'


def test_merge_only_auto_false_locked_and_freetext_guard() -> None:
    params = {'gender': 'male', 'hair_style': 'crew cut', 'eye_color': 'blue', 'default_clothing': 'tuxedo'}
    out = MOD.merge_analysis_into_params(params, _FULL_RAW, locked_fields={'Eye_Color'}, only_auto=False)
    assert out['hair_style'] == 'long wavy'
    assert out['eye_color'] == 'blue'
    assert out['gender'] == 'female'
    assert out['default_clothing'] == 'tuxedo'


def test_merge_ignores_non_dict_fields_key() -> None:
    assert MOD.merge_analysis_into_params({}, {'fields': 'not-a-dict', 'gender': 'man'})['gender'] == 'male'


def test_ollama_host_env_override(monkeypatch: MP) -> None:
    monkeypatch.setenv('OLLAMA_HOST', 'http://ollama.example.org:11434/')
    assert MOD._ollama_host() == 'http://ollama.example.org:11434'
    monkeypatch.delenv('OLLAMA_HOST', raising=False)
    assert not MOD._ollama_host().endswith('/')


def test_ollama_list_loaded(req: _FakeRequests) -> None:
    req.get_handler = lambda url, **kw: _Resp(200, {'models': [{'name': 'qwen3.5:9b'}, {'name': '  '}, {}]})
    assert MOD._ollama_list_loaded() == ['qwen3.5:9b']
    assert req.get_calls[0][0].endswith('/api/ps')
    req.get_handler = lambda url, **kw: _Resp(503, {})
    assert MOD._ollama_list_loaded() == []
    req.get_handler = _raise
    assert MOD._ollama_list_loaded() == []


def test_wait_ollama_unload_returns_when_gone(monkeypatch: MP) -> None:
    seen = iter([['qwen3.5:9b'], ['qwen3.5:9b'], []])
    monkeypatch.setattr(MOD, '_ollama_list_loaded', lambda: next(seen))
    monkeypatch.setattr(time, 'sleep', lambda _s: None)
    MOD._wait_ollama_unload('qwen3.5:9b', timeout=30)


def test_wait_ollama_unload_times_out(monkeypatch: MP) -> None:
    monkeypatch.setattr(MOD, '_ollama_list_loaded', lambda: ['qwen3.5:9b'])
    monkeypatch.setattr(time, 'sleep', lambda _s: None)
    ticks = itertools.count(0.0, 0.6)
    monkeypatch.setattr(time, 'time', lambda: next(ticks))
    MOD._wait_ollama_unload('qwen3.5:9b', timeout=1)


def test_evict_ollama_model(req: _FakeRequests, monkeypatch: MP) -> None:
    MOD.evict_ollama_model('')
    assert req.post_calls == []
    waited: list[str] = []
    monkeypatch.setattr(MOD, '_wait_ollama_unload', lambda n, timeout=30: waited.append(n))
    logs: list[str] = []
    MOD.evict_ollama_model('qwen3.5:9b', log_fn=logs.append, wait=True)
    url, kw = req.post_calls[0]
    assert url.endswith('/api/generate')
    assert kw['json']['keep_alive'] == 0
    assert waited == ['qwen3.5:9b']
    assert 'evict requested' in logs[0]
    req.post_handler = _raise
    MOD.evict_ollama_model('moondream:latest', log_fn=logs.append, wait=False)
    assert 'evict failed' in logs[-1]


def test_evict_all_ollama_models(req: _FakeRequests, monkeypatch: MP) -> None:
    evicted: list[str] = []
    monkeypatch.setattr(MOD, 'evict_ollama_model', lambda name, log_fn=None, wait=True: evicted.append(name))
    monkeypatch.setattr(MOD, '_ollama_list_loaded', lambda: ['a:1', 'b:2'])
    logs: list[str] = []
    assert MOD.evict_all_ollama_models(log_fn=logs.append) == ['a:1', 'b:2']
    assert evicted == ['a:1', 'b:2']
    assert 'evicted 2 model(s)' in logs[-1]
    monkeypatch.setattr(MOD, '_ollama_list_loaded', lambda: [])
    logs.clear()
    assert MOD.evict_all_ollama_models(log_fn=logs.append) == []
    assert logs == []


def test_anthropic_vision_no_key(monkeypatch: MP) -> None:
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    assert MOD._call_anthropic_vision(b'img', 'image/png') is None


@pytest.mark.parametrize(
    ('kwargs', 'media_type', 'expected', 'fragment'),
    [
        ({'text': '{"gender": "female"}'}, 'image/png', {'gender': 'female'}, 'Claude OK'),
        ({'text': '{"age": 40}'}, 'application/octet-stream', {'age': 40}, 'Claude OK'),
        ({'empty': True}, 'image/jpeg', None, None),
        ({'text': 'not json at all'}, 'image/jpeg', None, None),
        ({'exc': RuntimeError('rate limited')}, 'image/jpeg', None, 'Claude failed'),
    ],
)
def test_anthropic_vision(monkeypatch: MP, kwargs: Any, media_type: str, expected: Any, fragment: Any) -> None:
    _install_anthropic(monkeypatch, **kwargs)
    logs: list[str] = []
    assert MOD._call_anthropic_vision(b'img', media_type, log_fn=logs.append) == expected
    if fragment:
        assert fragment in logs[0]
    else:
        assert logs == []


def test_ollama_collect_two_models(req: _FakeRequests, monkeypatch: MP) -> None:
    monkeypatch.setattr(MOD, 'OLLAMA_VISION_MODELS', ['qwen3.5:9b', 'moondream:latest'])
    monkeypatch.setattr(MOD, 'OLLAMA_KEEP_ALIVE', '0')
    evicted: list[str] = []
    monkeypatch.setattr(MOD, 'evict_ollama_model', lambda m, log_fn=None, wait=True: evicted.append(m))
    answers = {'qwen3.5:9b': _chat({'gender': 'female'}), 'moondream:latest': _chat({'gender': 'female', 'age': 30})}
    req.post_handler = lambda url, **kw: _Resp(200, answers[kw['json']['model']])
    logs: list[str] = []
    out = MOD._call_ollama_vision_collect(b'img', max_results=2, log_fn=logs.append)
    assert [m for m, _r in out] == ['qwen3.5:9b', 'moondream:latest']
    assert req.post_calls[0][1]['json']['think'] is False
    assert 'think' not in req.post_calls[1][1]['json']
    assert evicted == ['qwen3.5:9b', 'moondream:latest']
    assert any('Ollama OK' in m for m in logs)


def test_ollama_collect_stops_at_max_results(req: _FakeRequests, monkeypatch: MP) -> None:
    monkeypatch.setattr(MOD, 'OLLAMA_VISION_MODELS', ['qwen3.5:9b', 'moondream:latest'])
    monkeypatch.setattr(MOD, 'OLLAMA_KEEP_ALIVE', '5m')
    req.post_handler = lambda url, **kw: _Resp(200, _chat({'gender': 'male'}))
    assert len(MOD._call_ollama_vision_collect(b'img', max_results=1)) == 1
    assert len(req.post_calls) == 1


def test_ollama_collect_bad_status_unparseable_and_raise(req: _FakeRequests, monkeypatch: MP) -> None:
    monkeypatch.setattr(MOD, 'OLLAMA_VISION_MODELS', ['bad:1', 'junk:1', 'boom:1'])
    monkeypatch.setattr(MOD, 'OLLAMA_KEEP_ALIVE', '0')
    monkeypatch.setattr(MOD, 'evict_ollama_model', lambda *a, **k: None)

    def _handler(url: str, **kw: Any) -> _Resp:
        model = kw['json']['model']
        if model == 'bad:1':
            return _Resp(500, {})
        if model == 'junk:1':
            return _Resp(200, {'message': 'plain string message'})
        raise OSError('socket closed')

    req.post_handler = _handler
    logs: list[str] = []
    assert MOD._call_ollama_vision_collect(b'img', max_results=2, log_fn=logs.append) == []
    assert any('boom:1 failed' in m for m in logs)


def test_call_ollama_vision_single(monkeypatch: MP) -> None:
    one = [('m', {'gender': 'female'})]
    monkeypatch.setattr(MOD, '_call_ollama_vision_collect', lambda b, max_results, log_fn=None: one)
    assert MOD._call_ollama_vision(b'img') == {'gender': 'female'}
    monkeypatch.setattr(MOD, '_call_ollama_vision_collect', lambda b, max_results, log_fn=None: [])
    assert MOD._call_ollama_vision(b'img') is None


_AGREE = [('a', {'gender': 'female', 'age': 30, 'hair_style': 'long wavy'}), ('b', {'gender': 'woman', 'age': '30'})]
_CLASH = [('a', {'gender': 'female', 'hair_color': 'blonde'}), ('b', {'gender': 'male', 'hair_color': 'blonde'})]
_FH = {'facial_hair': 'none'}  # normalize_analysis fills this in for every answer
_RECON_CASES = [
    ([], ({}, [], 'single_backend')),
    ([('m', {'gender': 'female'})], ({**_FH, 'gender': 'female'}, [], 'single_backend')),
    (_AGREE, ({**_FH, 'gender': 'female', 'age': 30, 'hair_style': 'long wavy'}, [], 'agreed')),
    (_CLASH, ({**_FH, 'hair_color': 'blonde'}, ['gender'], 'disputed')),
]


@pytest.mark.parametrize(('results', 'expected'), _RECON_CASES)
def test_reconcile_backends(results: Any, expected: Any) -> None:
    assert MOD._reconcile_backends(results) == expected


# (backend selection: setup kwargs → the keys of the result that must match, log fragment)
_DISPUTED = [('a', {'gender': 'female', 'per_image_caption': 'TRIGGER_TOKEN a'}), ('b', {'gender': 'male'})]
_AIB_CASES: list[tuple[dict[str, Any], dict[str, Any], str | None]] = [
    (
        {'prefer': '1', 'consensus': '1', 'models': ['a', 'b'], 'collect': _DISPUTED},
        {'backend': 'a+b', 'confidence': 'disputed', 'fields': _FH, 'per_image_caption': 'TRIGGER_TOKEN a'},
        'DISPUTED',
    ),
    (
        {'prefer': '1', 'single': {'gender': 'female'}},
        {'backend': 'ollama', 'confidence': 'single_backend', 'fields': {**_FH, 'gender': 'female'}},
        None,
    ),
    (
        {'prefer': '1', 'claude': {'gender': 'male', 'caption': 'TRIGGER_TOKEN man'}},
        {'backend': 'claude', 'confidence': 'single_backend', 'per_image_caption': 'TRIGGER_TOKEN man'},
        None,
    ),
    ({'prefer': '0', 'single': {'age': 44}}, {'backend': 'ollama', 'fields': {**_FH, 'age': 44}}, None),
]


def _setup_vision(monkeypatch: MP, **kw: Any) -> None:
    monkeypatch.setenv('ZYG_CHAR_PHOTO_ANALYSIS', '1')
    monkeypatch.setenv('ZYG_CHAR_PHOTO_PREFER_OLLAMA', kw.get('prefer', '1'))
    monkeypatch.setenv('ZYG_CHAR_PHOTO_CONSENSUS', kw.get('consensus', '0'))
    if kw.get('models'):
        monkeypatch.setattr(MOD, 'OLLAMA_VISION_MODELS', kw['models'])
    collect = kw.get('collect') or []
    monkeypatch.setattr(MOD, '_call_ollama_vision_collect', lambda b, max_results, log_fn=None: collect)
    monkeypatch.setattr(MOD, '_call_ollama_vision', lambda b, log_fn=None: kw.get('single'))
    monkeypatch.setattr(MOD, '_call_anthropic_vision', lambda b, mt, log_fn=None: kw.get('claude'))


@pytest.mark.parametrize(('setup', 'expected', 'fragment'), _AIB_CASES)
def test_analyze_image_bytes_backends(monkeypatch: MP, no_net: None, setup: Any, expected: Any, fragment: Any) -> None:
    _setup_vision(monkeypatch, **setup)
    logs: list[str] = []
    out = MOD.analyze_image_bytes(b'img', log_fn=logs.append)
    assert out['ok'] is True
    assert {k: out[k] for k in expected} == expected
    if fragment:
        assert any(fragment in m for m in logs)


def test_analyze_image_bytes_disabled_or_empty(monkeypatch: MP) -> None:
    monkeypatch.setenv('ZYG_CHAR_PHOTO_ANALYSIS', '0')
    assert MOD.analyze_image_bytes(b'img') == {'ok': False, 'error': 'disabled', 'fields': {}}
    monkeypatch.setenv('ZYG_CHAR_PHOTO_ANALYSIS', '1')
    assert MOD.analyze_image_bytes(b'') == {'ok': False, 'error': 'empty_image', 'fields': {}}


def test_analyze_image_bytes_vision_unavailable(monkeypatch: MP, no_net: None) -> None:
    _setup_vision(monkeypatch, prefer='0')
    expected = {'ok': False, 'error': 'vision_unavailable', 'fields': {}, 'backend': None}
    assert MOD.analyze_image_bytes(b'img') == expected


def test_analyze_photo_paths_no_paths() -> None:
    assert MOD.analyze_photo_paths([]) == {'ok': False, 'error': 'no_paths', 'fields': {}, 'image_captions': []}


def test_analyze_photo_paths_all_fail(tmp_path: Any, monkeypatch: MP, no_net: None) -> None:
    img = tmp_path / 'a.jpg'
    img.write_bytes(b'jpegbytes')
    monkeypatch.setattr(MOD, 'analyze_image_bytes', lambda d, mt, log_fn=None: {'ok': False})
    expected = {'ok': False, 'error': 'analysis_failed', 'fields': {}, 'image_captions': []}
    assert MOD.analyze_photo_paths([str(img), str(tmp_path / 'missing.png')]) == expected


def test_analyze_photo_paths_unreadable_is_logged(tmp_path: Any, monkeypatch: MP, no_net: None) -> None:
    img = tmp_path / 'a.jpg'
    img.write_bytes(b'jpegbytes')
    _patch_open(monkeypatch, 'a.jpg')
    logs: list[str] = []
    assert MOD.analyze_photo_paths([str(img)], log_fn=logs.append)['error'] == 'analysis_failed'
    assert any('cannot read' in m for m in logs)


_MT_CASES = [('a.jpg', 'image/jpeg'), ('a.jpeg', 'image/jpeg'), ('a.png', 'image/png')]
_MT_CASES += [('a.webp', 'image/webp'), ('a.x', 'image/jpeg')]


@pytest.mark.parametrize(('name', 'media_type'), _MT_CASES)
def test_analyze_photo_paths_media_types(tmp_path: Any, monkeypatch: MP, no_net: None, name: str, media_type: str):
    img = tmp_path / name
    img.write_bytes(b'bytes')
    seen: list[str] = []

    def _analyze(data: bytes, mt: str, log_fn: Any = None) -> dict[str, Any]:
        seen.append(mt)
        return {'ok': True, 'backend': 'claude', 'fields': {'gender': 'female'}}

    monkeypatch.setattr(MOD, 'analyze_image_bytes', _analyze)
    assert MOD.analyze_photo_paths([str(img)])['ok'] is True
    assert seen == [media_type]


def test_analyze_photo_paths_aggregates_and_evicts(tmp_path: Any, monkeypatch: MP, no_net: None) -> None:
    first, second = tmp_path / 'a.jpg', tmp_path / 'b.png'
    first.write_bytes(b'1')
    second.write_bytes(b'2')
    results = iter(
        [
            _result('a:1+b:1', {'gender': 'female'}, ' cap one ', 'agreed', []),
            _result(None, {'gender': 'male'}, '', 'disputed', ['age']),
        ]
    )
    monkeypatch.setattr(MOD, 'analyze_image_bytes', lambda d, mt, log_fn=None: next(results))
    evicted: list[bool] = []
    monkeypatch.setattr(MOD, 'evict_all_ollama_models', lambda log_fn=None: evicted.append(True))
    out = MOD.analyze_photo_paths([str(first), str(second)])
    assert out['ok'] is True
    assert out['backend'] == 'a:1+b:1'
    assert out['fields'] == {'gender': 'female'}
    assert out['confidence'] == 'disputed'
    assert out['ambiguous_fields'] == ['age']
    assert [c['caption'] for c in out['image_captions']] == ['cap one', '']
    assert evicted == [True]


def test_analyze_photo_paths_claude_does_not_evict(tmp_path: Any, monkeypatch: MP, no_net: None) -> None:
    img = tmp_path / 'a.jpg'
    img.write_bytes(b'1')
    result = {'ok': True, 'backend': 'claude', 'fields': {'age': 20}}
    monkeypatch.setattr(MOD, 'analyze_image_bytes', lambda d, mt, log_fn=None: result)
    evicted: list[bool] = []
    monkeypatch.setattr(MOD, 'evict_all_ollama_models', lambda log_fn=None: evicted.append(True))
    assert MOD.analyze_photo_paths([str(img)])['backend'] == 'claude'
    assert evicted == []


def test_fallback_caption_with_and_without_clothing() -> None:
    params = {'gender': 'female', 'hair_color': 'blonde', 'eye_color': 'blue', 'skin_tone': 'fair'}
    full = {**params, 'default_clothing': 'red dress', 'default_expression': 'playful'}
    cap = MOD._fallback_caption('zygtrig', full, 'portrait, facing camera', 'photorealistic')
    assert cap.startswith('zygtrig, female, blonde hair, blue eyes, fair skin tone')
    assert 'wearing red dress' in cap
    assert cap.endswith('portrait, facing camera')
    bare = MOD._fallback_caption('zygtrig', {'default_clothing': 'auto'}, 'close-up face', '')
    assert 'wearing' not in bare
    assert 'neutral confident' in bare


def test_write_training_captions_from_analysis(tmp_path: Any, monkeypatch: MP) -> None:
    _fake_bcs(monkeypatch)
    images = []
    for i in range(3):
        p = tmp_path / f'img{i}.png'
        p.write_bytes(b'x')
        images.append(str(p))
    captions: list[Any] = [
        {'index': 0, 'caption': 'TRIGGER_TOKEN woman, blonde hair'},
        {'index': 1, 'caption': 'a woman without the trigger'},
        {'index': 2, 'caption': '   '},
        {'index': -1, 'caption': 'ignored'},
        'not-a-dict',
    ]
    logs: list[str] = []
    written = MOD.write_training_captions(
        images,
        {'gender': 'female', 'style': 'anime'},
        'zygtrig',
        analysis={'image_captions': captions},
        log_fn=logs.append,
    )
    assert written == 3
    assert (tmp_path / 'img0.txt').read_text() == 'zygtrig woman, blonde hair'
    assert (tmp_path / 'img1.txt').read_text() == 'zygtrig a woman without the trigger'
    assert 'anime look' in (tmp_path / 'img2.txt').read_text()
    assert 'Wrote 3 vision/training caption(s)' in logs[-1]


def test_write_training_captions_style_lookup_failure(tmp_path: Any, monkeypatch: MP) -> None:
    _fake_bcs(monkeypatch, broken=True)
    img = tmp_path / 'only.jpg'
    img.write_bytes(b'x')
    assert MOD.write_training_captions([str(img)], {}, 'zygtrig') == 1
    assert 'photorealistic, film photography' in (tmp_path / 'only.txt').read_text()


def test_write_training_captions_write_error(tmp_path: Any, monkeypatch: MP) -> None:
    _fake_bcs(monkeypatch)
    img = tmp_path / 'a.jpg'
    img.write_bytes(b'x')
    _patch_open(monkeypatch, 'a.txt')
    logs: list[str] = []
    assert MOD.write_training_captions([str(img)], {}, 'zygtrig', log_fn=logs.append) == 0
    assert any('Caption write failed' in m for m in logs)
