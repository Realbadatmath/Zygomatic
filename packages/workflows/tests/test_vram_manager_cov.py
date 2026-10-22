# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Offline coverage for ``zyg_workflows.vram_manager``: every nvidia-smi, systemctl, pgrep, torch,
Ollama/ComfyUI HTTP, psutil and sleep call is monkeypatched, so this runs on a bare runner."""

import json
import logging
import os
import subprocess
import sys
import threading
import time
import types

import psutil
import pytest

import zyg_workflows
from zyg_workflows import gui_state, vram_manager as M

_CALIB = {'max_vram_gb': 48.0, 'max_gpu_watts': 450.0, 'max_cpu_pct': 80.0, 'max_ram_gb': 56.0}


class _Stop(Exception):  # raised from a fake sleep, to break the module's unbounded loops
    pass


class _Clock:  # monotone fake wall clock: sleeping is the only thing that moves time on
    def __init__(self, monkeypatch, start=1000.0):
        self.now, self.slept = start, []
        monkeypatch.setattr(time, 'time', lambda: self.now)
        monkeypatch.setattr(time, 'sleep', self.sleep)

    def sleep(self, secs):
        self.slept.append(secs)
        self.now += secs


def _raiser(exc):
    def _fn(*a, **kw):
        raise exc

    return _fn


def _sub(monkeypatch, name, **attrs):  # a fake zyg_workflows.<name>; the real one never loads
    mod = types.ModuleType(f'zyg_workflows.{name}')
    mod.__dict__.update(attrs)
    monkeypatch.setitem(sys.modules, f'zyg_workflows.{name}', mod)
    monkeypatch.setattr(zyg_workflows, name, mod, raising=False)


def _unimportable(monkeypatch, *names):  # make `from zyg_workflows import <name>` raise ImportError
    for name in names:
        monkeypatch.delattr(zyg_workflows, name, raising=False)
        monkeypatch.setitem(sys.modules, f'zyg_workflows.{name}', None)


def _fake_torch(monkeypatch, available=True):
    calls, mod = [], types.ModuleType('torch')
    cuda = {'is_available': lambda: available, 'mem_get_info': lambda idx: (24 * 1024**3, 48 * 1024**3)}
    cuda.update({name: (lambda n=name: calls.append(n)) for name in ('empty_cache', 'ipc_collect')})
    mod.cuda = types.SimpleNamespace(**cuda)
    monkeypatch.setitem(sys.modules, 'torch', mod)
    return calls


def _fake_run(monkeypatch, stdout='', exc=None):  # nvidia-smi/pgrep, recording the argv it was given
    seen = []
    # `exe()` resolves the binary through PATH and raises when it is absent (a CI runner has no
    # nvidia-smi); the fake below is what must answer, so the lookup is bypassed.
    monkeypatch.setattr(M, 'exe', lambda name, **kw: name)

    def _run(cmd, **kwargs):
        seen.append(list(cmd))
        return _raiser(exc)() if exc else types.SimpleNamespace(stdout=stdout, returncode=0)

    monkeypatch.setattr(subprocess, 'run', _run)
    return seen


def _fake_urlopen(monkeypatch, payload=b'{}', exc=None):
    from zyg_workflows import net

    resp = types.SimpleNamespace(read=lambda: payload)
    monkeypatch.setattr(net, 'safe_urlopen', _raiser(exc) if exc else (lambda url, timeout=None: resp))


def _ram(used_gb, percent):
    return lambda: types.SimpleNamespace(used=used_gb * 1024**3, percent=percent)


def _log_run(fn, *a, **kw):  # call fn with a collecting log_fn -> (its result, the lines it logged)
    lines = []
    return fn(*a, log_fn=lines.append, **kw), lines


def _said(lines, needle):
    return not needle or any(needle in line for line in lines)


@pytest.fixture
def debug_log(monkeypatch):  # _backend_debug collected; the real calibration is None outside the GUI
    lines = []
    monkeypatch.setattr(M, '_backend_debug', lines.append)
    monkeypatch.setattr(gui_state, '_CALIBRATION', dict(_CALIB))
    return lines


def test_vram_probes_and_comfy_offload_env(monkeypatch, debug_log):
    smi = [
        ('20480, 49152\n', None, 48.0, 20.0),  # 8 GB used of a 48 GB ceiling: physical free wins
        ('46080, 49152', None, 48.0, 45.0),  # 3 GB used, so the ceiling is not the binding limit
        ('40960, 49152', None, 20.0, 12.0),  # 8 GB used, the calibrated ceiling clips the answer
        ('10240\n', None, 48.0, 10.0),  # no total column: the 48 GB default is assumed
        ('', None, 48.0, 999.0),  # nvidia-smi said nothing
        ('', FileNotFoundError('nvidia-smi'), 48.0, 999.0),  # no nvidia-smi at all
        ('20480, 49152', None, None, 999.0),  # calibration never loaded -> AttributeError
    ]
    for stdout, exc, ceiling, expected in smi:
        with monkeypatch.context() as mp:
            mp.setattr(gui_state, '_CALIBRATION', None if ceiling is None else {'max_vram_gb': ceiling})
            seen = _fake_run(mp, stdout=stdout, exc=exc)
            assert M._get_free_vram_gb() == pytest.approx(expected, abs=0.01), stdout
            assert '--query-gpu=memory.free,memory.total' in seen[0]
    waits = [
        ([40.0], 300, '', True, [], ''),
        ([1.0, 30.0], 60, '', True, [10], 'need 25 GB, have 1.0 GB free —'),
        ([1.0], 30, 'stage35', False, [10, 10, 10], 'need 25 GB, have 1.0 GB free [stage35]'),
    ]
    for readings, timeout, label, expected, slept, needle in waits:
        debug_log.clear()
        with monkeypatch.context() as mp:
            clock = _Clock(mp)
            free = iter(readings * 9)
            mp.setattr(M, '_get_free_vram_gb', lambda f=free: next(f))
            assert M._wait_for_vram(25.0, timeout=timeout, label=label) is expected
            assert clock.slept == slept and _said(debug_log[:1], needle)
    for reachable in (True, False, None):  # _ensure_comfy_offload_env; None = no client module
        with monkeypatch.context() as mp:
            for var in ('ZYG_COMFY_PRIMARY', 'ZYG_USE_COMFYUI'):
                mp.delenv(var, raising=False)
            if reachable is None:
                _unimportable(mp, '_comfy_client')
            else:
                _sub(mp, '_comfy_client', server_reachable=lambda r=reachable, **kw: r)
            assert M._ensure_comfy_offload_env() is None
            assert all((v in os.environ) is (reachable is True) for v in ('ZYG_COMFY_PRIMARY', 'ZYG_USE_COMFYUI'))


def test_deep_unload_flux_pipeline_cache(monkeypatch):
    def _pipe(lora_fails, comp_fails):  # a FLUX stand-in whose parts record where they were moved
        def _to(comp, dev):
            if comp_fails:
                raise RuntimeError('pinned')
            comp.device = dev

        lora = _raiser(RuntimeError('no lora')) if lora_fails else (lambda: None)
        pipe = types.SimpleNamespace(unload_lora_weights=lora)
        for attr in ('transformer', 'vae', 'text_encoder', 'text_encoder_2'):
            comp = types.SimpleNamespace(device='cuda')
            comp.to = lambda dev, c=comp: _to(c, dev)
            setattr(pipe, attr, comp)
        return pipe

    for lora_fails, comp_fails in ((False, False), (True, True)):
        with monkeypatch.context() as mp:
            _Clock(mp)
            calls = _fake_torch(mp)
            dev_pipe = _pipe(lora_fails, comp_fails)
            mp.setattr(gui_state, '_FLUX_DEV_PIPELINE_CACHE', dev_pipe)
            mp.setattr(gui_state, '_FLUX_PIPELINE_CACHE', _pipe(lora_fails, comp_fails))
            mp.setattr(gui_state, '_CN_PIPE_CACHE', object())
            _, lines = _log_run(M._deep_unload_flux_pipeline_cache)
            assert gui_state._FLUX_DEV_PIPELINE_CACHE is gui_state._FLUX_PIPELINE_CACHE is None
            assert gui_state._CN_PIPE_CACHE is None and calls.count('empty_cache') == 2
            assert dev_pipe.transformer.device == ('cuda' if comp_fails else 'cpu')
            assert lines[-1] == 'FLUX pipeline cache deep-unloaded'
    with monkeypatch.context() as mp:  # empty caches, no CUDA device
        calls = _fake_torch(mp, available=False)
        mp.setattr(gui_state, '_FLUX_DEV_PIPELINE_CACHE', None)
        mp.setattr(gui_state, '_FLUX_PIPELINE_CACHE', None)
        _, lines = _log_run(M._deep_unload_flux_pipeline_cache)
        assert calls == [] and lines == ['FLUX pipeline cache deep-unloaded']

    class _Hostile:
        transformer = property(_raiser(RuntimeError('cuda context lost')))
        unload_lora_weights = staticmethod(lambda: None)

    class _Frozen:
        _FLUX_DEV_PIPELINE_CACHE = _Hostile()
        _FLUX_PIPELINE_CACHE = None
        __setattr__ = _raiser(RuntimeError('read-only state'))

    monkeypatch.setitem(sys.modules, 'torch', None)  # the torch flush must stay non-fatal
    monkeypatch.setattr(gui_state, '_FLUX_DEV_PIPELINE_CACHE', _Hostile())
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', None)
    assert M._deep_unload_flux_pipeline_cache() is None
    monkeypatch.setattr(M, 'gui_state', _Frozen())
    assert _said(_log_run(M._deep_unload_flux_pipeline_cache)[1], 'FLUX cache detach warning')


def test_ollama_helpers(monkeypatch, capsys, debug_log):
    def _evict(log_fn=None):
        log_fn('two models dropped')
        return ['llava', 'qwen']

    _sub(monkeypatch, 'character_photo_analysis_service', evict_all_ollama_models=_evict)
    assert M._evict_all_ollama_models() == ['llava', 'qwen']
    assert '[VRAM] two models dropped' in capsys.readouterr().out  # the default log_fn is print
    _unimportable(monkeypatch, 'character_photo_analysis_service')
    got, lines = _log_run(M._evict_all_ollama_models)
    assert got == [] and _said(lines, 'Ollama evict-all failed')
    loaded = [
        (b'{"models": [{"size_vram": 1073741824}, {"size_vram": 536870912}]}', None, 1536),
        (b'{"models": [{"size_vram": "nonsense"}, {"size_vram": null}]}', None, 0),
        (b'{"models": []}', None, 0),
        (b'{}', None, 0),
        (b'not json at all', None, 0),
        (b'', OSError('connection refused'), 0),
    ]
    for payload, exc, expected in loaded:
        with monkeypatch.context() as mp:
            _fake_urlopen(mp, payload=payload, exc=exc)
            assert M._ollama_loaded_vram_mb() == expected, payload
    unloads = [
        (b'{"models": [{"name": "other:latest"}]}', None, 30, [], ''),
        (b'', OSError('refused'), 30, [], ''),
        (b'{"models": [{"name": "llava:13b"}]}', None, 3, [1, 1, 1], 'still present after 3s'),
    ]
    for payload, exc, timeout, slept, needle in unloads:
        debug_log.clear()
        with monkeypatch.context() as mp:
            clock = _Clock(mp)
            _fake_urlopen(mp, payload=payload, exc=exc)
            assert M._wait_ollama_unload('llava:13b', timeout=timeout) is None
            assert clock.slept == slept and _said(debug_log[:1], needle)


def test_release_pipeline_vram(monkeypatch):
    _Clock(monkeypatch)
    _fake_torch(monkeypatch)
    monkeypatch.setattr(gui_state, '_FLUX_DEV_PIPELINE_CACHE', None)
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', None)
    _sub(monkeypatch, 'character_photo_analysis_service', evict_all_ollama_models=lambda log_fn=None: ['llava'])
    _sub(monkeypatch, 'musicgen_service', unload=lambda: None)
    _sub(monkeypatch, 'ace_step_service', unload=lambda: None)
    _sub(monkeypatch, 'wan_video_service', _unload_pipe=lambda **kw: None, _unload_t2v_pipe=lambda **kw: None)
    outcomes = [
        ({'skipped': True}, 'keep-loaded'),
        ({'restarted': True, 'rss_mb_after': 120, 'gpu_mb_after': 0}, 'ComfyUI restarted'),
        ({'ok': True, 'rss_mb_before': 900, 'rss_mb_after': 120, 'gpu_mb_after': 0}, 'memory released'),
        ({'ok': False}, '/free skipped or failed'),
    ]
    for summary, needle in outcomes:
        with monkeypatch.context() as mp:
            _sub(mp, '_comfy_client', server_reachable=lambda **kw: True, release_memory=lambda s=summary, **kw: s)
            _, lines = _log_run(M._release_pipeline_vram, 'stage', allow_restart=False)
            assert all(line.startswith('stage: ') for line in lines if 'FLUX' not in line)
            for tag in (needle, 'Ollama VRAM released (1 model(s))', 'MusicGen unloaded', 'ACE-Step', 'WAN pipes'):
                assert _said(lines, tag)
    for freed, needle in ((True, 'models evicted'), (False, 'skipped or failed')):
        with monkeypatch.context() as mp:
            _sub(mp, '_comfy_client', server_reachable=lambda **kw: True, free_vram=lambda f=freed: f)
            assert _said(_log_run(M._release_pipeline_vram, wait_comfy=False)[1], needle)
    with monkeypatch.context() as mp:  # a probe that raises is logged, not re-raised
        _sub(mp, '_comfy_client', server_reachable=_raiser(RuntimeError('socket timeout')))
        assert _said(_log_run(M._release_pipeline_vram)[1], 'Comfy release non-fatal: socket timeout')
    with monkeypatch.context() as mp:
        _unimportable(mp, '_comfy_client')
        mp.setattr(M, '_evict_all_ollama_models', _raiser(RuntimeError('evict blew up')))
        assert _said(_log_run(M._release_pipeline_vram)[1], 'Ollama release non-fatal: evict blew up')
    with monkeypatch.context() as mp:  # a bare machine: no service module at all, and no torch
        mp.setitem(sys.modules, 'torch', None)  # the final cache flush must stay non-fatal
        _unimportable(mp, '_comfy_client', 'musicgen_service', 'ace_step_service', 'wan_video_service')
        _, lines = _log_run(M._release_pipeline_vram, 'boot')
        assert not any(_said(lines, tag) for tag in ('MusicGen', 'ACE-Step', 'WAN', 'ComfyUI'))


def test_process_helpers_and_stop_secondary_flask_dashboards(monkeypatch):
    me, dead = os.getpid(), 2**31 - 1
    assert M._proc_ppid(me) > 0 and M._proc_argv(me) and M._proc_in_gui_unit(me) is False
    assert M._proc_ppid(dead) == 0 and M._proc_argv(dead) == [] and M._proc_in_gui_unit(dead) is False
    for stdout, exc, expected in [('4242\n', None, 4242), ('0', None, 0), ('n/a', None, 0), ('', OSError(), 0)]:
        with monkeypatch.context() as mp:
            mp.setattr(subprocess, 'check_output', _raiser(exc) if exc else lambda cmd, s=stdout, **kw: s)
            assert M._gui_service_main_pid() == expected
    argvs = [
        (['python', 'crewai_web_gui.py'], True),
        (['python', '/srv/zyg/crewai_web_gui.py'], True),
        (['bash', '-c', 'echo crewai_web_gui.py is lovely'], False),  # the `pgrep -f` bug this replaced
        (['python', 'not_crewai_web_gui.py'], False),
        ([], False),
    ]
    for argv, expected in argvs:
        assert M._is_flask_dashboard_argv(argv) is expected, argv
    killed = []  # a /proc holding one duplicate dashboard (4242) plus noise
    _Clock(monkeypatch)
    monkeypatch.setattr(os, 'listdir', lambda path: ['self', 'cpuinfo', str(me), '4242', '777'])
    monkeypatch.setattr(os, 'kill', lambda pid, sig: killed.append(pid))
    monkeypatch.setattr(M, '_proc_ppid', lambda pid: 0)
    monkeypatch.setattr(M, '_gui_service_main_pid', lambda: 0)
    monkeypatch.setattr(M, '_proc_in_gui_unit', lambda pid: False)
    monkeypatch.setattr(M, '_proc_argv', lambda pid: ['python', 'crewai_web_gui.py'] if pid == 4242 else ['sshd'])
    cases = [
        ('1', None, [4242], 'Stopped 1 secondary Flask dashboard(s): [4242]'),
        ('1', (M, '_proc_ppid', lambda pid: 4242 if pid == me else 0), [], '[ancestor]'),
        ('1', (M, '_gui_service_main_pid', lambda: 4242), [], 'MainPID'),
        ('1', (M, '_proc_in_gui_unit', lambda pid: True), [], 'cgroup'),
        ('off', None, [], 'left running: [4242]'),
        ('1', (os, 'kill', _raiser(ProcessLookupError())), [], ''),
        ('1', (os, 'kill', _raiser(PermissionError())), [], 'permission denied'),
        ('1', (os, 'listdir', _raiser(OSError('/proc gone'))), [], 'Secondary Flask scan failed'),
    ]
    for env, patch, stopped, needle in cases:
        killed.clear()
        with monkeypatch.context() as mp:
            mp.setenv(M._KILL_SIBLING_FLASK_ENV, env)
            if patch:
                mp.setattr(*patch)
            got, lines = _log_run(M._stop_secondary_flask_dashboards)
            assert got == stopped and killed == stopped and _said(lines, needle), needle
    monkeypatch.setenv(M._KILL_SIBLING_FLASK_ENV, '1')
    assert M._stop_secondary_flask_dashboards(keep_pid=me) == [4242]  # log_fn is optional


def test_enforce_gpu_exclusivity_before_stage35(monkeypatch):
    _Clock(monkeypatch)
    _fake_torch(monkeypatch)
    monkeypatch.delenv('ZYG_SKIP_GPU_EXCLUSIVE', raising=False)
    monkeypatch.setattr(M, '_stop_secondary_flask_dashboards', lambda log_fn=None: [])
    monkeypatch.setattr(M, '_release_pipeline_vram', lambda *a, **kw: None)
    monkeypatch.setattr(M, '_evict_all_ollama_models', lambda log_fn=None: ['llava'])
    monkeypatch.setattr(M, '_ollama_loaded_vram_mb', lambda: 0)
    monkeypatch.setattr(M, '_wait_for_vram', lambda *a, **kw: True)
    _unimportable(monkeypatch, 'scholarly_stills_backend')
    cases = [  # (staggered?, the client's wait attribute, what it returns) -> timeout, log needle
        (False, 'wait_for_idle', True, M._STAGE35_COMFY_IDLE_TIMEOUT_S, 'queue idle after'),
        (True, '_wait_for_queue_idle', False, 10.0, 'queue busy after wait'),
    ]
    for stagger, attr, idle, expected_wait, needle in cases:
        with monkeypatch.context() as mp:
            waits = []
            if stagger:
                stag = {'scholarly_stagger_concurrent_enabled': lambda: True, '_STAGGER_CONCURRENT_ENV': 'ZYG_STAGGER'}
                _sub(mp, 'scholarly_stills_backend', **stag)
            waiter = {attr: lambda timeout_s, w=waits, i=idle: w.append(timeout_s) or i}
            _sub(mp, '_comfy_client', server_reachable=lambda **kw: True, free_vram=lambda: True, **waiter)
            _, lines = _log_run(M._enforce_gpu_exclusivity_before_stage35, pipeline_id='p1')
            assert waits == [expected_wait] and _said(lines, 'Ollama evicted 1 model(s): llava')
            assert _said(lines, needle)
            assert any('skipping secondary Flask shutdown' in line for line in lines) is stagger
    with monkeypatch.context() as mp:  # the whole sweep is opt-out-able
        mp.setenv('ZYG_SKIP_GPU_EXCLUSIVE', 'yes')
        got, lines = _log_run(M._enforce_gpu_exclusivity_before_stage35)
        assert got is None and lines == ['GPU exclusivity skipped (ZYG_SKIP_GPU_EXCLUSIVE)']
    with monkeypatch.context() as mp:  # Ollama never drains and VRAM never frees
        _sub(mp, '_comfy_client', server_reachable=lambda **kw: False, free_vram=lambda: True)
        mp.setattr(M, '_ollama_loaded_vram_mb', lambda: 4096)
        mp.setattr(M, '_wait_for_vram', lambda *a, **kw: False)
        _, lines = _log_run(M._enforce_gpu_exclusivity_before_stage35)
        for needle in ('may still hold VRAM (~4096 MiB)', '<25 GB VRAM free', 'Post-exclusivity VRAM free: 24.0 GB'):
            assert _said(lines, needle)
    monkeypatch.setitem(sys.modules, 'torch', None)  # a Comfy probe that raises, and no log_fn
    _sub(monkeypatch, '_comfy_client', server_reachable=_raiser(RuntimeError('comfy unreachable')))
    assert M._enforce_gpu_exclusivity_before_stage35() is None


def test_gpu_work_and_comfy_process_probes(monkeypatch, caplog):
    def _lock(locked=False, boom=False):  # a stand-in for the module's GPU pipeline lock
        probe = _raiser(RuntimeError('lock probe failed')) if boom else (lambda: locked)
        return types.SimpleNamespace(locked=probe)

    hostile = types.SimpleNamespace(values=_raiser(RuntimeError('job table corrupt')))
    jobs = [
        ({'status': 'running', 'pipeline_id': 'p1'}, True, True),
        ({'status': 'running', 'pipeline_id': 'p1'}, False, False),
        ({'status': 'running', 'pipeline_id': '  '}, True, False),
        ({'status': 'done', 'pipeline_id': 'p1'}, True, False),
        ({}, True, False),
        (None, True, False),
    ]
    for job, alive, expected in jobs:
        monkeypatch.setattr(M, '_workflow_pipeline_worker_alive', lambda pid, a=alive: a)
        assert M._workflow_job_gpu_active(job) is expected, job
    threads = [('abcdef0123', 'char-gen-abcdef01', True), ('abcdef0123', 'char-gen-x', False), ('  ', 'x', False)]
    for char_id, name, expected in threads:
        fake = [types.SimpleNamespace(name=name, is_alive=lambda: True)]
        monkeypatch.setattr(threading, 'enumerate', lambda f=fake: f)
        assert M._char_gen_worker_alive(char_id) is expected
    live = {'a': None, 'b': {'status': 'done'}, 'c': {'status': 'running', 'char_id': ' '}}
    live['d'] = {'status': 'running', 'char_id': 'cafebabe01'}
    active = [
        ([('_GPU_PIPELINE_LOCK', _lock(locked=True))], True),
        ([('_workflow_jobs', {'p1': {'status': 'running', 'pipeline_id': 'p1'}})], True),
        ([('_char_gen_jobs', live)], True),
        ([], False),
        ([('_GPU_PIPELINE_LOCK', _lock(boom=True)), ('_char_gen_jobs', hostile)], False),
    ]
    for patches, expected in active:
        with monkeypatch.context() as mp:
            mp.setattr(M, '_GPU_PIPELINE_LOCK', _lock())
            mp.setattr(M, '_workflow_jobs', hostile if not patches else {})
            mp.setattr(M, '_char_gen_jobs', {})
            mp.setattr(M, '_workflow_pipeline_worker_alive', lambda pid: True)
            mp.setattr(M, '_char_gen_worker_alive', lambda cid: True)
            for name, value in patches:
                mp.setattr(M, name, value)
            assert M._gpu_work_active() is expected, patches
    pids = [  # (cpu_cap behaviour, pgrep stdout, pgrep error) -> pid
        (lambda pid: None, 'notapid\n9123\n', None, 9123),
        (_raiser(RuntimeError('no taskset')), '9123\n', None, 9123),
        (lambda pid: None, '', None, None),
        (lambda pid: None, '', OSError('pgrep missing'), None),
    ]
    for apply_to_pid, stdout, exc, expected in pids:
        with monkeypatch.context() as mp:
            _sub(mp, 'cpu_cap', apply_to_pid=apply_to_pid)
            _fake_run(mp, stdout=stdout, exc=exc)
            assert M._comfy_server_pid() == expected
    used = [
        (9123, '9123, 7400\n', None, 7400),
        (9123, '555, 100\n9123, 7400', None, 7400),
        (9123, '555, 100\n', None, 0),
        (9123, 'garbage\n', None, 0),
        (9123, '', OSError('no nvidia-smi'), 0),
        (None, '', None, 0),
    ]
    for pid, stdout, exc, expected in used:
        with monkeypatch.context() as mp:
            mp.setattr(M, '_comfy_server_pid', lambda p=pid: p)
            _fake_run(mp, stdout=stdout, exc=exc)
            assert M._comfy_vram_used_mb() == expected, stdout
    reconciled, released = [], []
    monkeypatch.setattr(M, '_reconcile_stale_workflow_jobs', lambda: reconciled.append(True))
    monkeypatch.setattr(M, '_release_pipeline_vram', lambda label='', **kw: released.append(label))
    _fake_run(monkeypatch, stdout='8192, 40960\n')
    with caplog.at_level(logging.INFO, logger=M.__name__):
        M._startup_vram_sweep()
    assert reconciled == [True] and released == ['startup']
    assert 'GPU used 8192 MiB before release' in caplog.text and 'free 40960 MiB' in caplog.text
    for stdout, exc in (('', None), ('8192\n', None), ('', FileNotFoundError('nvidia-smi'))):
        with monkeypatch.context() as mp:
            _fake_run(mp, stdout=stdout, exc=exc)
            assert M._startup_vram_sweep() is None  # a silent, short or absent smi is not fatal


def test_comfy_idle_vram_sweeper_loop(monkeypatch, caplog, capsys):
    for var, value in (('SEC', '1'), ('MB', '8192'), ('RAM_MB', '6144')):  # an otherwise idle machine
        monkeypatch.setenv(f'ZYG_COMFY_IDLE_FREE_{var}', value)
    monkeypatch.delenv('ZYG_COMFY_KEEP_LOADED', raising=False)
    monkeypatch.setattr(M, '_gpu_work_active', lambda: False)
    monkeypatch.setattr(M, '_ollama_loaded_vram_mb', lambda: 0)
    monkeypatch.setattr(M, '_comfy_vram_used_mb', lambda: 0)
    _sub(monkeypatch, '_comfy_client', comfy_process_rss_mb=lambda: 0)
    state = types.SimpleNamespace(ticks=[], released=[])
    monkeypatch.setattr(M, '_release_pipeline_vram', lambda label='', **kw: state.released.append(label))

    def _sleep(secs):  # the loop runs one tick, then the second sleep breaks it out
        state.ticks.append(secs)
        if len(state.ticks) >= 2:
            raise _Stop

    monkeypatch.setattr(time, 'sleep', _sleep)
    hot_ollama = ('_ollama_loaded_vram_mb', lambda: 4096)
    hot_comfy = ('_comfy_vram_used_mb', lambda: 9000)
    evict_boom = ('_evict_all_ollama_models', _raiser(RuntimeError('ollama down')))
    release_boom = ('_release_pipeline_vram', _raiser(RuntimeError('release failed')))
    cases = [  # (env, module patches) -> labels released this tick, log/stdout needle
        ({'ZYG_COMFY_KEEP_LOADED': 'true'}, [], [], ''),
        ({}, [('_gpu_work_active', lambda: True)], [], ''),
        ({}, [hot_ollama, ('_evict_all_ollama_models', lambda log_fn=None: log_fn('evicted'))], [], '[VRAM] evicted'),
        ({}, [hot_ollama, evict_boom], [], 'Ollama idle sweeper error: ollama down'),
        ({}, [('_comfy_vram_used_mb', lambda: 10)], [], ''),
        ({}, [hot_comfy], ['idle-sweeper'], 'ComfyUI 9000 MiB VRAM'),
        ({}, [hot_comfy, release_boom], [], 'Idle sweeper error: release failed'),
    ]
    for env, patches, released, needle in cases:
        state.ticks.clear()
        state.released.clear()
        caplog.clear()
        with monkeypatch.context() as mp:
            for key, value in env.items():
                mp.setenv(key, value)
            for name, value in patches:
                mp.setattr(M, name, value)
            if release_boom in patches:  # the RSS probe may be broken too; it must not stop the sweep
                _sub(mp, '_comfy_client', comfy_process_rss_mb=_raiser(RuntimeError('no comfy')))
            with caplog.at_level(logging.INFO, logger=M.__name__), pytest.raises(_Stop):
                M._comfy_idle_vram_sweeper_loop()
            assert state.ticks == [1.0, 1.0] and state.released == released, needle
            assert needle in caplog.text + capsys.readouterr().out
    monkeypatch.setenv('ZYG_COMFY_IDLE_FREE_SEC', '0')
    assert M._comfy_idle_vram_sweeper_loop() is None  # a zero interval disables the sweeper


def test_hardware_headroom_thresholds_and_check_now(monkeypatch, tmp_path, debug_log):
    def _gpu(**over):
        base = {'index': 0, 'utilization_pct': 10, 'memory_total_mb': 49152, 'memory_used_mb': 1024}
        return {**base, 'temperature_c': 50, 'power_w': 90.0, **over}

    idle = {'gpus': [{'power_w': 100.0}], 'cpu_pct': 10.0}
    monkeypatch.setattr(psutil, 'cpu_percent', lambda interval=None: 5.0)
    monkeypatch.setattr(psutil, 'virtual_memory', _ram(8, 25.0))
    headroom = [
        ({}, None, True, [], ''),
        ({'gpus': []}, None, True, [], ''),  # nothing in the telemetry cache yet
        ({'gpus': [{'power_w': 999.0}]}, None, False, [5, 5], 'GPU 999W > limit 450W'),
        ({'cpu_pct': 95.0}, None, False, [5, 5], 'CPU 95% >= limit 80%'),
        ({}, _ram(60, 95.0), False, [5, 5], 'RAM 60.0 GB >= limit 56.0 GB'),
    ]
    for cache, ram, expected, slept, needle in headroom:
        debug_log.clear()
        with monkeypatch.context() as mp:
            clock = _Clock(mp)
            mp.setattr(M, '_TELEMETRY_CACHE', {**idle, **cache})
            if ram:
                mp.setattr(psutil, 'virtual_memory', ram)
            assert M._wait_for_hardware_headroom(label='stage3', timeout=10) is expected, needle
            assert clock.slept == slept and _said(debug_log[:1], needle)
            assert not debug_log or '[stage3]' in debug_log[0]
    thresholds = {
        'cpu': {'util_critical_pct': 95},
        'ram': {'critical_pct': 92},
        'gpu': {'temp_critical_c': 85, 'util_critical_pct': 100, 'vram_critical_pct': 93},
    }
    path = tmp_path / 'safety_thresholds.json'
    monkeypatch.setattr(M, '_SAFETY_THRESHOLDS_PATH', str(path))
    assert M._read_safety_thresholds() == {}
    path.write_text(json.dumps(thresholds), encoding='utf-8')
    assert M._read_safety_thresholds() == thresholds
    cases = [  # (telemetry overrides, psutil cpu, psutil ram, thresholds reader) -> blocked, needle
        ({'gpus': [_gpu(temperature_c=90)]}, None, None, None, True, 'temp critical'),
        ({'gpus': [_gpu(utilization_pct=101)]}, None, None, None, True, 'utilisation critical'),
        ({'gpus': [_gpu(memory_used_mb=48000)]}, None, None, None, True, 'VRAM critical'),
        ({'gpus': [_gpu(power_w=900.0)]}, None, None, None, True, 'power 900W'),
        ({'gpus': [_gpu(), _gpu(memory_total_mb=0, index=1)]}, None, None, None, False, ''),
        ({'cpu_pct': 99.0}, None, None, None, True, 'CPU critical: 99.0%'),
        ({'cpu_pct': 0}, 99.0, None, None, True, 'CPU critical: 99.0%'),  # cache miss -> live psutil
        ({}, None, _ram(60, 97.0), None, True, 'RAM critical: 97.0%'),
        ({'gpus': 17}, None, None, None, False, ''),  # a corrupt cache must not block
        ({}, None, None, _raiser(RuntimeError('disk gone')), False, ''),
    ]
    for cache, cpu, ram, reader, blocked, needle in cases:
        with monkeypatch.context() as mp:
            mp.setattr(psutil, 'cpu_percent', lambda interval=None, c=cpu: c if c else 7.0)
            mp.setattr(psutil, 'virtual_memory', ram or _ram(8, 30.0))
            mp.setattr(M, '_TELEMETRY_CACHE', {'cpu_pct': 11.0, 'gpus': [], **cache})
            if reader:
                mp.setattr(M, '_read_safety_thresholds', reader)
            got, reason = M._check_hardware_now()
            assert got is blocked and needle in reason, needle
    monkeypatch.setattr(gui_state, '_hw_block_active', False)
    monkeypatch.setattr(gui_state, '_hw_block_reason', '')
    monkeypatch.setattr(M, '_ams_iso', lambda **kw: '2026-10-22T12:00:00+02:00')
    monkeypatch.setattr(M, '_runtime_path', lambda name: str(tmp_path / name))
    naps = []
    monkeypatch.setattr(time, 'sleep', naps.append)
    log_path = tmp_path / 'clipfarm_processing_log.json'
    for preexisting in (False, True):
        naps.clear()
        gui_state._hw_block_active, gui_state._hw_block_reason = False, ''
        log_path.write_text('[{"level": "INFO"}]' if preexisting else '[]', encoding='utf-8')
        if not preexisting:
            log_path.unlink()
        job = {'status': 'running'}
        verdicts = iter([(True, 'GPU[0] temp critical: 90C'), (True, 'still hot'), (False, '')])

        def _check(j=job, v=verdicts):
            try:
                return next(v)
            except StopIteration:
                j['status'] = 'done'
                return False, ''

        with monkeypatch.context() as mp:
            mp.setattr(M, '_workflow_jobs', {'p1': job})
            mp.setattr(M, '_check_hardware_now', _check)
            M._hw_monitor_loop('p1')
        assert gui_state._hw_block_active is False and gui_state._hw_block_reason == ''
        assert naps == [5, 5, 20, 20]  # fast poll while blocked, slow once the gate lifts
        entries = json.loads(log_path.read_text(encoding='utf-8'))
        assert len(entries) == (2 if preexisting else 1) and entries[-1]['agent'] == 'hw_monitor'
        assert entries[-1]['pipeline_id'] == 'p1' and 'activated: GPU[0] temp critical: 90C' in entries[-1]['message']
    stuck = {'status': 'running'}

    def _block_once():
        stuck['status'] = 'done'
        return True, 'RAM critical'

    with monkeypatch.context() as mp:  # an unwritable log must not drop the block
        mp.setattr(M, '_runtime_path', lambda name: str(tmp_path))  # a directory, not a file
        mp.setattr(M, '_workflow_jobs', {'p1': stuck})
        mp.setattr(M, '_check_hardware_now', _block_once)
        M._hw_monitor_loop('p1')
    assert gui_state._hw_block_active is True and gui_state._hw_block_reason == 'RAM critical'
    naps.clear()
    monkeypatch.setattr(M, '_check_hardware_now', _raiser(AssertionError('should not probe')))
    for jobs in ({}, {'p1': {'status': 'done'}}):  # a finished pipeline exits before the first probe
        monkeypatch.setattr(M, '_workflow_jobs', jobs)
        M._hw_monitor_loop('p1')
    assert naps == []
