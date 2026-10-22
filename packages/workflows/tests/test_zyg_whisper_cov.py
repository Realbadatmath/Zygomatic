# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline coverage tests for :mod:`zyg_workflows.zyg_whisper`.

faster-whisper and torch are both absent from the CI runner and both are
imported lazily inside the module's functions, so every test here injects its
own fake into ``sys.modules``: a ``faster_whisper.WhisperModel`` whose
``transcribe()`` yields fake segments, and a ``torch`` whose
``cuda.mem_get_info()`` reports whatever free VRAM the case needs. Putting
``None`` in ``sys.modules`` for a name makes ``import <name>`` raise, which is
how "torch is not installed" is simulated deterministically.

Nothing here touches the GPU, the network or the run ledger's Postgres: the
ledger's ``record_fallback`` is spied on by an autouse fixture.
"""

import importlib
import logging
import sys
import types

import pytest

from zyg_workflows import run_ledger
from zyg_workflows import zyg_whisper as MOD

GIB = 1024 * 1024 * 1024


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class _Word:
    def __init__(self, word, start, end, probability):
        self.word = word
        self.start = start
        self.end = end
        self.probability = probability


class _Seg:
    def __init__(self, start, end, text, words=None):
        self.start = start
        self.end = end
        self.text = text
        self.words = words


class _Info:
    language = 'en'
    language_probability = 0.99
    duration = 2.0


def _fake_torch(*, available=True, free=8 * GIB, probe_exc=None, flushes=None):
    """A stand-in for the lazily imported ``torch``."""
    mod = types.ModuleType('torch')

    def is_available():
        if probe_exc is not None:
            raise probe_exc
        return available

    def mem_get_info():
        return (free, 16 * GIB)

    def empty_cache():
        if flushes is not None:
            flushes.append('empty_cache')

    mod.cuda = types.SimpleNamespace(
        is_available=is_available,
        mem_get_info=mem_get_info,
        empty_cache=empty_cache,
    )
    return mod


@pytest.fixture
def fw(monkeypatch):
    """Inject a fake ``faster_whisper`` module; report what it built."""
    made = []

    class WhisperModel:
        fail_on = set()
        fail_first = 0

        def __init__(self, model_size, device='cpu', compute_type='int8'):
            if device in WhisperModel.fail_on or WhisperModel.fail_first > 0:
                WhisperModel.fail_first = max(0, WhisperModel.fail_first - 1)
                raise RuntimeError('CUDA out of memory; ' + 'x' * 500)
            self.model_size = model_size
            self.device = device
            self.compute_type = compute_type
            self.segments = []
            self.info = _Info()
            self.transcribe_calls = []
            made.append(self)

        def transcribe(self, audio_path, **kwargs):
            self.transcribe_calls.append((audio_path, kwargs))
            return iter(self.segments), self.info

    mod = types.ModuleType('faster_whisper')
    mod.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules, 'faster_whisper', mod)
    return types.SimpleNamespace(module=mod, cls=WhisperModel, made=made)


@pytest.fixture(autouse=True)
def degrades(monkeypatch):
    """Spy on the run ledger so no test can reach Postgres."""
    calls = []

    def spy(*args, **kwargs):
        calls.append({'args': args, 'kwargs': kwargs})
        return True

    monkeypatch.setattr(run_ledger, 'record_fallback', spy)
    return calls


@pytest.fixture(autouse=True)
def _clean_module_state(monkeypatch):
    for knob in (
        'ZYG_WHISPER_MODEL',
        'ZYG_WHISPER_COMPUTE',
        'ZYG_WHISPER_BEAM',
        'ZYG_WHISPER_CPU_MODEL',
        'ZYG_WHISPER_FW_MIN_VRAM_MB',
        'ZYG_WHISPER_MIN_VRAM_MB',
    ):
        monkeypatch.delenv(knob, raising=False)
    MOD._MODEL_CACHE.clear()
    yield
    MOD._MODEL_CACHE.clear()


# --------------------------------------------------------------------------- #
# _pick_device_compute
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ('torch_kw', 'env', 'expected'),
    [
        # torch is not importable at all -> the warning branch, cpu/int8
        (None, {}, ('cpu', 'int8')),
        # torch present, no CUDA
        ({'available': False}, {}, ('cpu', 'int8')),
        # ample free VRAM clears the default 5000 MB floor
        ({'available': True, 'free': 8 * GIB}, {}, ('cuda', 'int8_float16')),
        # 1 GiB free does not
        ({'available': True, 'free': 1 * GIB}, {}, ('cpu', 'int8')),
        # the modern knob lowers the floor
        ({'available': True, 'free': 2 * GIB}, {'ZYG_WHISPER_FW_MIN_VRAM_MB': '1000'}, ('cuda', 'int8_float16')),
        # the legacy murch_engine alias is honoured too
        ({'available': True, 'free': 2 * GIB}, {'ZYG_WHISPER_MIN_VRAM_MB': '1000'}, ('cuda', 'int8_float16')),
        # ... and can also raise the floor out of reach
        ({'available': True, 'free': 2 * GIB}, {'ZYG_WHISPER_MIN_VRAM_MB': '9000'}, ('cpu', 'int8')),
        # a broken driver probe is swallowed
        ({'probe_exc': RuntimeError('no CUDA driver')}, {}, ('cpu', 'int8')),
        # an unparseable floor is an exception too -> cpu
        ({'available': True, 'free': 8 * GIB}, {'ZYG_WHISPER_FW_MIN_VRAM_MB': 'lots'}, ('cpu', 'int8')),
        # ZYG_WHISPER_COMPUTE overrides the compute type on either device
        ({'available': True, 'free': 8 * GIB}, {'ZYG_WHISPER_COMPUTE': 'float16'}, ('cuda', 'float16')),
        (None, {'ZYG_WHISPER_COMPUTE': 'int8_float32'}, ('cpu', 'int8_float32')),
    ],
)
def test_pick_device_compute_table(monkeypatch, torch_kw, env, expected):
    if torch_kw is None:
        monkeypatch.setitem(sys.modules, 'torch', None)
    else:
        monkeypatch.setitem(sys.modules, 'torch', _fake_torch(**torch_kw))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert MOD._pick_device_compute() == expected


def test_pick_device_compute_logs_why_it_fell_back(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, 'torch', _fake_torch(probe_exc=RuntimeError('no CUDA driver')))
    with caplog.at_level(logging.WARNING, logger=MOD.__name__):
        assert MOD._pick_device_compute() == ('cpu', 'int8')
    assert 'cuda sizing probe failed' in caplog.text
    assert 'no CUDA driver' in caplog.text


# --------------------------------------------------------------------------- #
# get_model
# --------------------------------------------------------------------------- #
def test_get_model_caches_one_model_per_key(monkeypatch, fw):
    monkeypatch.setitem(sys.modules, 'torch', None)
    first = MOD.get_model('small')
    second = MOD.get_model('small')
    assert first is second
    assert len(fw.made) == 1
    assert (first.model_size, first.device, first.compute_type) == ('small', 'cpu', 'int8')
    assert list(MOD._MODEL_CACHE) == [('small', 'cpu', 'int8')]


def test_get_model_without_a_size_uses_the_module_default(monkeypatch, fw):
    monkeypatch.setitem(sys.modules, 'torch', None)
    model = MOD.get_model()
    assert model.model_size == MOD.DEFAULT_MODEL


def test_get_model_takes_cuda_when_vram_is_ample_and_flushes_after(monkeypatch, fw):
    flushes = []
    monkeypatch.setitem(sys.modules, 'torch', _fake_torch(available=True, free=8 * GIB, flushes=flushes))
    model = MOD.get_model('large-v3')
    assert (model.device, model.compute_type) == ('cuda', 'int8_float16')
    assert list(MOD._MODEL_CACHE) == [('large-v3', 'cuda', 'int8_float16')]
    assert flushes == ['empty_cache']


def test_get_model_falls_back_to_cpu_and_records_the_degrade(monkeypatch, fw, degrades):
    monkeypatch.setitem(sys.modules, 'torch', _fake_torch(available=True, free=8 * GIB))
    fw.cls.fail_on = {'cuda'}
    model = MOD.get_model('large-v3')
    assert (model.device, model.compute_type) == ('cpu', 'int8')
    # cached under the key it actually loaded with, not the one it asked for
    assert list(MOD._MODEL_CACHE) == [('large-v3', 'cpu', 'int8')]
    assert len(degrades) == 1
    assert degrades[0]['args'] == ('whisper', 'cuda:large-v3:int8_float16', 'cpu:large-v3:int8')
    detail = degrades[0]['kwargs']['detail']
    assert detail.startswith('WhisperModel load failed: CUDA out of memory;')
    assert len(detail) == len('WhisperModel load failed: ') + 300


def test_get_model_cpu_retry_records_nothing(monkeypatch, fw, degrades):
    """A CPU load that fails once and succeeds on retry is not a degrade."""
    monkeypatch.setitem(sys.modules, 'torch', None)
    fw.cls.fail_first = 1
    model = MOD.get_model('base')
    assert (model.device, model.compute_type) == ('cpu', 'int8')
    assert degrades == []


def test_get_model_drops_a_stale_copy_of_the_same_size(monkeypatch, fw):
    monkeypatch.setitem(sys.modules, 'torch', None)
    keeper = MOD.get_model('tiny')
    cpu_medium = MOD.get_model('medium')
    monkeypatch.setitem(sys.modules, 'torch', _fake_torch(available=True, free=8 * GIB))
    cuda_medium = MOD.get_model('medium')
    assert cuda_medium is not cpu_medium
    assert ('medium', 'cpu', 'int8') not in MOD._MODEL_CACHE
    assert MOD._MODEL_CACHE[('medium', 'cuda', 'int8_float16')] is cuda_medium
    # another size on the old device is untouched
    assert MOD._MODEL_CACHE[('tiny', 'cpu', 'int8')] is keeper


# --------------------------------------------------------------------------- #
# transcribe_segments
# --------------------------------------------------------------------------- #
def test_transcribe_segments_shapes_segments_and_words(monkeypatch, fw):
    monkeypatch.setitem(sys.modules, 'torch', _fake_torch(available=True, free=8 * GIB))
    monkeypatch.setenv('ZYG_WHISPER_BEAM', '7')
    model = MOD.get_model(MOD.DEFAULT_MODEL)  # same cache key transcribe_segments will hit
    model.segments = [
        _Seg(
            0.0, 1.25, '  hello there  ', words=[_Word(' hello ', 0.0, 0.5, 0.987654), _Word('there', 0.5, 1.25, 0.5)]
        ),
        _Seg('1.25', '2', None, words=None),
    ]

    out, info = MOD.transcribe_segments('/tmp/clip.mp4', want_words=True)

    assert info is model.info
    assert out == [
        {
            'start': 0.0,
            'end': 1.25,
            'text': 'hello there',
            'words': [
                {'word': 'hello', 'start': 0.0, 'end': 0.5, 'prob': 0.9877},
                {'word': 'there', 'start': 0.5, 'end': 1.25, 'prob': 0.5},
            ],
        },
        {'start': 1.25, 'end': 2.0, 'text': ''},
    ]
    path, kwargs = model.transcribe_calls[0]
    assert path == '/tmp/clip.mp4'
    assert kwargs == {
        'language': 'en',
        'task': 'transcribe',
        'beam_size': 7,
        'word_timestamps': True,
        'vad_filter': True,
    }


def test_transcribe_segments_without_words_omits_them(monkeypatch, fw):
    monkeypatch.setitem(sys.modules, 'torch', _fake_torch(available=True, free=8 * GIB))
    model = MOD.get_model(MOD.DEFAULT_MODEL)
    model.segments = [_Seg(0.0, 1.0, 'one', words=[_Word('one', 0.0, 1.0, 1.0)])]
    out, _info = MOD.transcribe_segments('/tmp/a.wav', want_words=False)
    assert out == [{'start': 0.0, 'end': 1.0, 'text': 'one'}]
    assert model.transcribe_calls[0][1]['beam_size'] == 5  # the default beam


def test_transcribe_segments_degrades_to_base_and_greedy_on_cpu(monkeypatch, fw, degrades, caplog):
    monkeypatch.setitem(sys.modules, 'torch', None)
    with caplog.at_level(logging.WARNING, logger=MOD.__name__):
        out, _info = MOD.transcribe_segments('/media/jobs/clip.mp4', language='fr', task='translate', vad=False)
    assert out == []
    model = fw.made[0]
    assert model.model_size == 'base'
    kwargs = model.transcribe_calls[0][1]
    assert kwargs['beam_size'] == 1
    assert kwargs['vad_filter'] is False
    assert kwargs['language'] == 'fr'
    assert kwargs['task'] == 'translate'
    assert 'CPU transcription' in caplog.text
    assert len(degrades) == 1
    assert degrades[0]['args'] == ('whisper', f'cuda:{MOD.DEFAULT_MODEL}', 'cpu:base')
    detail = degrades[0]['kwargs']['detail']
    assert 'beam=1' in detail and 'vad=False' in detail
    assert 'audio=clip.mp4' in detail  # basename only, no job path
    assert '5000MB' in detail  # the default VRAM floor it reports


def test_transcribe_segments_honours_the_cpu_model_knob(monkeypatch, fw, degrades):
    monkeypatch.setitem(sys.modules, 'torch', None)
    monkeypatch.setenv('ZYG_WHISPER_CPU_MODEL', 'tiny.en')
    monkeypatch.setenv('ZYG_WHISPER_MIN_VRAM_MB', '7000')
    MOD.transcribe_segments('/tmp/a.wav')
    assert fw.made[0].model_size == 'tiny.en'
    assert '7000MB' in degrades[0]['kwargs']['detail']


def test_transcribe_segments_keeps_an_explicitly_pinned_model_and_beam(monkeypatch, fw, degrades):
    monkeypatch.setitem(sys.modules, 'torch', None)
    MOD.transcribe_segments('/tmp/a.wav', model_size='large-v3', beam_size=3)
    assert fw.made[0].model_size == 'large-v3'
    assert fw.made[0].transcribe_calls[0][1]['beam_size'] == 3
    # still a degrade: large-v3 landed on the CPU
    assert degrades[0]['args'][2] == 'cpu:large-v3'


# --------------------------------------------------------------------------- #
# unload_models / _maybe_free_cuda / _record_degrade
# --------------------------------------------------------------------------- #
def test_unload_models_empties_the_cache_and_flushes_cuda(monkeypatch, fw):
    flushes = []
    monkeypatch.setitem(sys.modules, 'torch', _fake_torch(available=True, free=8 * GIB, flushes=flushes))
    MOD.get_model('tiny')
    MOD.get_model('small')
    assert len(MOD._MODEL_CACHE) == 2
    MOD.unload_models()
    assert MOD._MODEL_CACHE == {}
    assert flushes == ['empty_cache'] * 3  # one per load, one for the unload


def test_unload_models_on_an_empty_cache_is_a_no_op(monkeypatch):
    monkeypatch.setitem(sys.modules, 'torch', None)
    MOD.unload_models()
    assert MOD._MODEL_CACHE == {}


@pytest.mark.parametrize('available', [True, False])
def test_maybe_free_cuda_only_flushes_when_cuda_is_there(monkeypatch, available):
    flushes = []
    monkeypatch.setitem(sys.modules, 'torch', _fake_torch(available=available, flushes=flushes))
    MOD._maybe_free_cuda()
    assert flushes == (['empty_cache'] if available else [])


def test_maybe_free_cuda_without_torch_is_logged_and_swallowed(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, 'torch', None)
    with caplog.at_level(logging.DEBUG, logger=MOD.__name__):
        MOD._maybe_free_cuda()
    assert 'cuda cache flush skipped' in caplog.text


def test_record_degrade_reaches_the_ledger(degrades):
    MOD._record_degrade('cuda:large-v3', 'cpu:base', detail='why')
    assert degrades == [
        {'args': ('whisper', 'cuda:large-v3', 'cpu:base'), 'kwargs': {'detail': 'why'}},
    ]


def test_record_degrade_swallows_a_broken_ledger(monkeypatch, caplog):
    def boom(*_args, **_kwargs):
        raise RuntimeError('ledger down')

    monkeypatch.setattr(run_ledger, 'record_fallback', boom)
    with caplog.at_level(logging.DEBUG, logger=MOD.__name__):
        MOD._record_degrade('cuda:large-v3', 'cpu:base')
    assert 'not recorded in the run ledger' in caplog.text
    assert 'ledger down' in caplog.text


def test_default_model_is_read_from_the_env_at_import(monkeypatch):
    monkeypatch.setenv('ZYG_WHISPER_MODEL', 'distil-large-v3')
    try:
        reloaded = importlib.reload(MOD)
        assert reloaded.DEFAULT_MODEL == 'distil-large-v3'
    finally:
        monkeypatch.delenv('ZYG_WHISPER_MODEL', raising=False)
        importlib.reload(MOD)
    assert MOD.DEFAULT_MODEL == 'large-v3'
