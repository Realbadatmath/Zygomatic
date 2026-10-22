# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline coverage for :mod:`zyg_workflows._comfy_client`.

Every HTTP call, subprocess, /proc read, clock and flock is faked, so the whole
file runs on a bare runner with no ComfyUI, no GPU and no network.
"""

from __future__ import annotations

import errno
import fcntl
import io
import json
import logging
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
import requests

from zyg_workflows import _comfy_client as mod


class FakeResp:
    """Minimal stand-in for ``requests.Response``."""

    def __init__(self, status_code=200, payload=None, text='', bad_json=False):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.text = text
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError('not json')
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f'status {self.status_code}')


OK = FakeResp(200)
BOOM = requests.ConnectionError('connection refused')


def install_http(monkeypatch, get=None, post=None):
    """Route ``requests.get/post`` by URL path; returns the call log."""
    calls: list[tuple[str, str, dict]] = []

    def _make(table, verb):
        def _fn(url, **kw):
            path = url.split(f':{mod.COMFY_PORT}', 1)[-1]
            calls.append((verb, path, kw))
            for key in sorted(table or {}, key=len, reverse=True):
                if path.startswith(key):
                    out = table[key]
                    out = out(path, kw) if callable(out) else out
                    if isinstance(out, BaseException):
                        raise out
                    return out
            raise AssertionError(f'unrouted {verb} {path}')

        return _fn

    monkeypatch.setattr(mod.requests, 'get', _make(get, 'GET'))
    monkeypatch.setattr(mod.requests, 'post', _make(post, 'POST'))
    return calls


class FakeTime:
    """Deterministic monotonic clock; ``sleep`` advances it instead of waiting."""

    def __init__(self, start=1000.0, on_sleep=None):
        self.now = start
        self.slept: list[float] = []
        self.on_sleep = on_sleep

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += max(float(seconds), 0.001)
        if self.on_sleep:
            self.on_sleep(len(self.slept))


def queue_resp(running=(), pending=()):
    body = {'queue_running': [[1, p] for p in running], 'queue_pending': [[2, p] for p in pending]}
    return FakeResp(200, body)


@pytest.fixture(autouse=True)
def _clean_module_state(monkeypatch):
    """No cached /object_info, no owned prompts, no leftover timing, no env."""
    monkeypatch.setattr(mod, '_OBJECT_INFO_CACHE', None)
    monkeypatch.setattr(mod, '_OWNED_PROMPT_IDS', set())
    monkeypatch.setattr(mod, 'last_submit_timing', {})
    for var in (
        'ZYG_USE_COMFYUI',
        'ZYG_COMFY_KEEP_LOADED',
        'ZYG_COMFY_GLOBAL_INTERRUPT',
        'ZYG_COMFY_SUBMIT_LOCK',
        'ZYG_COMFY_SUBMIT_LOCK_PATH',
        'ZYG_COMFY_SUBMIT_LOCK_WAIT_S',
        'ZYG_COMFY_CLIENT_ID',
        'ZYG_COMFY_MAX_IDLE_RAM_MB',
        'ZYG_COMFY_RESTART_ON_STUCK',
        'ZYG_COMFY_FREE_GC_SEC',
        'ZYG_COMFY_FREE_ROUNDS',
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.parametrize(
    ('value', 'expected'), [('1', True), (' yes ', True), ('on', True), ('0', False), ('maybe', False)]
)
def test_is_enabled_reads_the_env_gate(monkeypatch, value, expected):
    monkeypatch.setenv('ZYG_USE_COMFYUI', value)
    assert mod.is_enabled() is expected
    assert mod._url('/queue') == f'http://{mod.COMFY_HOST}:{mod.COMFY_PORT}/queue'


def test_object_info_is_cached_and_failures_are_swallowed(monkeypatch):
    calls = install_http(monkeypatch, get={'/object_info': FakeResp(200, {'KSampler': {}})})
    assert mod.get_object_info() == {'KSampler': {}}
    assert mod.get_object_info() == {'KSampler': {}}
    assert len(calls) == 1
    assert mod.get_object_info(refresh=True) == {'KSampler': {}}
    assert len(calls) == 2
    assert mod.has_node('KSampler') is True
    assert mod.has_node('Nope') is False
    for result in (BOOM, FakeResp(500)):
        monkeypatch.setattr(mod, '_OBJECT_INFO_CACHE', None)
        install_http(monkeypatch, get={'/object_info': result})
        assert mod.get_object_info() == {}


def _instantid(raw):
    return {'InstantIDModelLoader': {'input': {'required': {'instantid_file': raw}}}}


@pytest.mark.parametrize(
    ('info', 'expected'),
    [
        (_instantid([['a.bin', 'b.bin', '']]), ['a.bin', 'b.bin']),
        (_instantid(['solo.bin']), ['solo.bin']),
        (_instantid([]), []),
        ({'InstantIDModelLoader': {'input': {'required': {}}}}, []),
        ({'InstantIDModelLoader': {}}, []),
        ({}, []),
    ],
)
def test_instantid_model_files(monkeypatch, info, expected):
    monkeypatch.setattr(mod, 'get_object_info', lambda refresh=False: info)
    assert mod.list_instantid_model_files() == expected


@pytest.mark.parametrize(
    ('available', 'preferred', 'expected'),
    [
        ([], 'x.bin', None),
        (['x.bin', 'y.bin'], 'y.bin', 'y.bin'),
        (['instantid_sdxl.safetensors', 'z.bin'], 'missing.bin', 'instantid_sdxl.safetensors'),
        (['ip-adapter.bin', 'z.bin'], None, 'ip-adapter.bin'),
        (['only.bin'], None, 'only.bin'),
    ],
)
def test_resolve_instantid_model_file(monkeypatch, available, preferred, expected):
    monkeypatch.setattr(mod, 'list_instantid_model_files', lambda: list(available))
    assert mod.resolve_instantid_model_file(preferred) == expected


@pytest.mark.parametrize(
    ('fn_name', 'get', 'post', 'expected'),
    [
        ('server_reachable', {'/system_stats': OK}, None, True),
        ('server_reachable', {'/system_stats': FakeResp(503)}, None, False),
        ('server_reachable', {'/system_stats': BOOM}, None, False),
        ('queue_is_busy', {'/system_stats': OK, '/queue': queue_resp(running=['p'])}, None, True),
        ('queue_is_busy', {'/system_stats': OK, '/queue': queue_resp()}, None, False),
        ('queue_is_busy', {'/system_stats': OK, '/queue': FakeResp(500)}, None, False),
        ('queue_is_busy', {'/system_stats': OK, '/queue': BOOM}, None, False),
        ('queue_is_busy', {'/system_stats': BOOM}, None, False),
        ('free_vram', {'/system_stats': OK}, {'/free': FakeResp(200)}, True),
        ('free_vram', {'/system_stats': OK}, {'/free': FakeResp(500)}, False),
        ('free_vram', {'/system_stats': OK}, {'/free': BOOM}, False),
        ('free_vram', {'/system_stats': BOOM}, None, False),
    ],
)
def test_http_probes(monkeypatch, fn_name, get, post, expected):
    install_http(monkeypatch, get=get, post=post)
    assert getattr(mod, fn_name)() is expected


@pytest.mark.parametrize(
    ('stdout', 'expected'), [('nope\n4242\n99\n', 4242), ('', None), ('not-a-pid\n', None), (None, None)]
)
def test_comfy_server_pid(monkeypatch, stdout, expected):
    def _run(*a, **k):
        if stdout is None:
            raise OSError('no pgrep')
        return SimpleNamespace(stdout=stdout)

    monkeypatch.setattr(subprocess, 'run', _run)
    assert mod.comfy_server_pid() == expected


def test_process_rss_mb(monkeypatch):
    monkeypatch.setattr(mod, 'comfy_server_pid', lambda: None)
    assert mod.comfy_process_rss_mb() == 0
    # pid 999999999 cannot exist -> OSError out of open(/proc/<pid>/status)
    assert mod.comfy_process_rss_mb(pid=999999999) == 0
    monkeypatch.setattr(mod, 'comfy_server_pid', lambda: 77)
    monkeypatch.setattr('builtins.open', lambda *a, **k: io.StringIO('Name:\tpython\nVmRSS:\t   2048 kB\n'))
    assert mod.comfy_process_rss_mb() == 2


def test_gpu_used_mb(monkeypatch):
    monkeypatch.setattr(mod, 'exe', lambda name: name)
    monkeypatch.setattr(mod, 'comfy_server_pid', lambda: None)
    assert mod.comfy_gpu_used_mb() == 0
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout='7, 100\n55, 4096\n bad line\n'))
    assert mod.comfy_gpu_used_mb(pid=55) == 4096
    assert mod.comfy_gpu_used_mb(pid=9) == 0

    def _boom(*a, **k):
        raise FileNotFoundError('nvidia-smi')

    monkeypatch.setattr(subprocess, 'run', _boom)
    assert mod.comfy_gpu_used_mb(pid=5) == 0


def test_queue_snapshot_reads_both_lists(monkeypatch):
    payload = {
        'queue_running': [[1, 'run-1', {}, {}, []], ['short'], [2, '']],
        'queue_pending': [[3, 'pend-1', {}, {}, []]],
    }
    install_http(monkeypatch, get={'/queue': FakeResp(200, payload)})
    assert mod.queue_snapshot() == {'running': ['run-1'], 'pending': ['pend-1']}
    for result in (BOOM, FakeResp(500), FakeResp(200, bad_json=True), FakeResp(200, ['not', 'a', 'dict'])):
        install_http(monkeypatch, get={'/queue': result})
        assert mod.queue_snapshot() == {}


@pytest.mark.parametrize(('busy', 'expected'), [(False, True), (True, False)])
def test_wait_for_idle(monkeypatch, busy, expected):
    monkeypatch.setattr(mod, 'time', FakeTime())
    monkeypatch.setattr(mod, 'queue_is_busy', lambda *a, **k: busy)
    assert mod.wait_for_idle(timeout_s=1.0, poll_s=0.5) is expected


def test_restart_server_skips_without_the_start_script(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, 'ZYG_COMFY_ROOT', tmp_path)
    seen: list[str] = []
    assert mod.restart_server(log_fn=seen.append) is False
    assert 'start_server.sh' in seen[0]


@pytest.fixture
def comfy_root(monkeypatch, tmp_path):
    """A ComfyUI root with a start script, a faked subprocess and a fake clock."""
    (tmp_path / 'start_server.sh').write_text('#!/bin/sh\n')
    monkeypatch.setattr(mod, 'ZYG_COMFY_ROOT', tmp_path)
    monkeypatch.setattr(mod, 'exe', lambda name: name)
    monkeypatch.setattr(mod, 'time', FakeTime())
    monkeypatch.setattr(mod, 'comfy_process_rss_mb', lambda *a, **k: 123)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: SimpleNamespace(pid=1))
    return tmp_path


@pytest.mark.parametrize(
    ('reachable', 'expected', 'last_log'), [(True, True, 'back online'), (False, False, 'timed out')]
)
def test_restart_server_waits_for_the_server(monkeypatch, comfy_root, reachable, expected, last_log):
    monkeypatch.setattr(mod, 'server_reachable', lambda **k: reachable)
    seen: list[str] = []
    assert mod.restart_server(timeout_s=5.0, log_fn=seen.append) is expected
    assert last_log in seen[-1]
    assert mod.restart_server(timeout_s=5.0) is expected  # log_fn=None path

    def _boom(*a, **k):
        raise OSError('pkill missing')

    monkeypatch.setattr(subprocess, 'run', _boom)
    seen.clear()
    assert mod.restart_server(log_fn=seen.append) is False
    assert 'restart failed' in seen[0]


@pytest.fixture
def live_server(monkeypatch):
    """A reachable server with a known pid and a fake clock."""
    monkeypatch.setattr(mod, 'time', FakeTime())
    monkeypatch.setattr(mod, 'server_reachable', lambda **k: True)
    monkeypatch.setattr(mod, 'comfy_server_pid', lambda: 11)
    monkeypatch.setattr(mod, '_wait_for_queue_idle', lambda **k: True)
    monkeypatch.setattr(mod, 'queue_is_busy', lambda *a, **k: False)
    monkeypatch.setattr(mod, 'comfy_gpu_used_mb', lambda *a, **k: 7)


def test_release_memory_skips_pinned_models_and_a_dead_server(monkeypatch):
    monkeypatch.setenv('ZYG_COMFY_KEEP_LOADED', '1')
    assert mod.release_memory() == {
        'ok': True,
        'skipped': True,
        'rss_mb_before': 0,
        'rss_mb_after': 0,
        'gpu_mb_after': 0,
        'restarted': False,
    }
    monkeypatch.delenv('ZYG_COMFY_KEEP_LOADED')
    monkeypatch.setattr(mod, 'server_reachable', lambda **k: False)
    assert mod.release_memory()['ok'] is False


def test_release_memory_posts_free_and_reports_ram(monkeypatch, live_server):
    monkeypatch.setattr(mod, 'free_vram', lambda *a, **k: True)
    monkeypatch.setattr(mod, 'comfy_process_rss_mb', lambda *a, **k: 100)
    out = mod.release_memory(max_idle_rss_mb=4096.0)
    assert out['ok'] is True and out['restarted'] is False
    assert out['rss_mb_after'] == 100 and out['gpu_mb_after'] == 7
    monkeypatch.setattr(mod, 'free_vram', lambda *a, **k: False)  # /free never lands -> break
    monkeypatch.setattr(mod, 'comfy_process_rss_mb', lambda *a, **k: 0)
    monkeypatch.setenv('ZYG_COMFY_RESTART_ON_STUCK', '0')
    assert mod.release_memory(wait=False)['ok'] is False


@pytest.mark.parametrize(('restart_ok', 'expected_ok'), [(True, True), (False, False)])
def test_release_memory_restarts_a_stuck_server(monkeypatch, live_server, restart_ok, expected_ok):
    monkeypatch.setattr(mod, 'free_vram', lambda *a, **k: True)
    monkeypatch.setattr(mod, 'comfy_process_rss_mb', lambda *a, **k: 9000)
    monkeypatch.setattr(mod, 'restart_server', lambda **k: restart_ok)
    monkeypatch.setenv('ZYG_COMFY_MAX_IDLE_RAM_MB', '4096')
    seen: list[str] = []
    out = mod.release_memory(log_fn=seen.append)
    assert out['ok'] is expected_ok and out['restarted'] is restart_ok
    assert 'restarting server' in seen[0]


def fake_torch(free_bytes, available=True, explode=False):
    def _mem_get_info(_idx):
        if explode:
            raise RuntimeError('cuda is sulking')
        return (free_bytes, 24_000_000_000)

    cuda = SimpleNamespace(is_available=lambda: available, empty_cache=lambda: None, mem_get_info=_mem_get_info)
    return SimpleNamespace(cuda=cuda)


def test_wait_for_free_vram_is_a_noop_without_cuda(monkeypatch):
    for stub in (None, fake_torch(0, available=False)):  # torch absent, then no GPU
        monkeypatch.setitem(sys.modules, 'torch', stub)
        assert mod.wait_for_free_vram_gb(10.0) == (True, float('inf'))


def test_wait_for_free_vram_polls_until_the_budget_runs_out(monkeypatch):
    monkeypatch.setattr(mod, 'time', FakeTime())
    monkeypatch.setattr(mod, 'free_vram', lambda *a, **k: True)
    monkeypatch.setitem(sys.modules, 'torch', fake_torch(20_000_000_000))
    seen: list[str] = []
    ok, free_gb = mod.wait_for_free_vram_gb(10.0, log_fn=seen.append)
    assert ok is True and free_gb == pytest.approx(20.0)
    assert seen == ['ComfyUI /free called — waiting for VRAM eviction…']
    monkeypatch.setitem(sys.modules, 'torch', fake_torch(0, explode=True))
    ok, free_gb = mod.wait_for_free_vram_gb(10.0, timeout_s=4.0, poll_s=2.0, try_evict=False)
    assert ok is False and free_gb == -1.0


def test_load_workflow(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, '_WORKFLOW_DIR', tmp_path)
    (tmp_path / 'demo.json').write_text(json.dumps({'1': {'class_type': 'KSampler'}}))
    assert mod.load_workflow('demo') == {'1': {'class_type': 'KSampler'}}
    with pytest.raises(mod.ComfyUIError, match='workflow template not found'):
        mod.load_workflow('ghost')


def test_prompt_ownership_round_trip():
    assert mod.owned_prompt_ids() == set()
    mod._track_prompt('p-1')
    assert mod.owned_prompt_ids() == {'p-1'}
    mod._untrack_prompt('p-1')
    mod._untrack_prompt('p-1')
    assert mod.owned_prompt_ids() == set()


def test_default_should_abort_follows_pipeline_control(monkeypatch):
    from zyg_workflows import pipeline_control

    monkeypatch.setattr(pipeline_control, 'halt_requested', lambda: True)
    assert mod._default_should_abort() is True


def test_default_should_abort_is_false_without_pipeline_control(monkeypatch):
    import zyg_workflows

    monkeypatch.delattr(zyg_workflows, 'pipeline_control', raising=False)
    monkeypatch.setitem(sys.modules, 'zyg_workflows.pipeline_control', None)
    assert mod._default_should_abort() is False


@pytest.mark.parametrize(
    ('owned', 'kwargs', 'stats', 'queue', 'interrupt', 'delete', 'expected'),
    [
        ((), {}, BOOM, None, None, None, False),  # server down
        ((), {'force_global': True}, OK, None, FakeResp(200), None, True),  # blind override
        ((), {'force_global': True}, OK, None, BOOM, None, False),
        (('mine',), {}, OK, queue_resp(), None, None, False),  # nothing running
        (('mine',), {}, OK, queue_resp(running=['theirs']), None, None, False),  # foreign render
        (('mine',), {}, OK, queue_resp(running=['mine']), FakeResp(200), None, True),  # ours
        ((), {'prompt_id': 'theirs'}, OK, queue_resp(running=['x']), None, None, False),  # unowned id
        (('mine',), {'prompt_id': 'mine'}, OK, queue_resp(running=['mine']), FakeResp(200), None, True),
        # ours but only pending -> dequeued instead of interrupted
        (('mine', 'ours2'), {'prompt_id': 'mine'}, OK, queue_resp(['ours2'], ['mine']), None, FakeResp(200), True),
        (('mine', 'ours2'), {'prompt_id': 'mine'}, OK, queue_resp(['ours2'], ['mine']), None, BOOM, False),
        (('mine', 'ours2'), {'prompt_id': 'mine'}, OK, queue_resp(running=['ours2']), None, None, False),  # finished
    ],
)
def test_interrupt_execution(monkeypatch, owned, kwargs, stats, queue, interrupt, delete, expected):
    for pid in owned:
        mod._track_prompt(pid)
    install_http(
        monkeypatch,
        get={'/system_stats': stats, '/queue': queue},
        post={'/interrupt': interrupt, '/queue': delete},
    )
    assert mod.interrupt_execution(**kwargs) is expected


@pytest.mark.parametrize('value', ['1', 'on'])
def test_interrupt_global_override_by_env(monkeypatch, value):
    monkeypatch.setenv('ZYG_COMFY_GLOBAL_INTERRUPT', value)
    install_http(monkeypatch, get={'/system_stats': OK}, post={'/interrupt': FakeResp(200)})
    assert mod.interrupt_execution() is True


def test_interrupt_falls_back_to_ownership_when_the_queue_is_unreadable(monkeypatch):
    mod._track_prompt('mine')
    calls = install_http(
        monkeypatch,
        get={'/system_stats': OK, '/queue': BOOM},
        post={'/interrupt': FakeResp(200), '/queue': FakeResp(200)},
    )
    assert mod.interrupt_execution(prompt_id='mine') is True
    assert ('POST', '/queue', {'json': {'delete': ['mine']}, 'timeout': 5.0}) in calls


def test_submit_lock_path(monkeypatch, tmp_path):
    monkeypatch.setenv('ZYG_COMFY_SUBMIT_LOCK_PATH', '/tmp/zyg-comfy-test.lock')
    assert mod.submit_lock_path() == '/tmp/zyg-comfy-test.lock'
    monkeypatch.delenv('ZYG_COMFY_SUBMIT_LOCK_PATH')
    # builds a path string only — nothing is created
    assert mod.submit_lock_path().endswith(f'/data/runtime/comfy_{mod.COMFY_PORT}.lock')
    fallback = str(tmp_path / f'zyg_comfy_{mod.COMFY_PORT}.lock')
    monkeypatch.setattr(mod, 'tmp_dir', lambda: tmp_path)
    monkeypatch.setattr(mod.os, 'access', lambda *a, **k: False)
    assert mod.submit_lock_path() == fallback

    def _boom(self, *a, **k):
        raise OSError('read-only fs')

    monkeypatch.setattr(mod.Path, 'mkdir', _boom)
    assert mod.submit_lock_path() == fallback


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [(None, 3600.0), ('', 3600.0), ('12.5', 12.5), ('nonsense', 3600.0), ('inf', 3600.0), ('-inf', 3600.0)],
)
def test_submit_lock_wait_budget(monkeypatch, raw, expected):
    if raw is not None:
        monkeypatch.setenv('ZYG_COMFY_SUBMIT_LOCK_WAIT_S', raw)
    assert mod._submit_lock_wait_s() == expected


def test_acquire_lock_is_skipped_when_disabled(monkeypatch):
    for value in ('0', 'false', 'OFF', 'no'):
        monkeypatch.setenv('ZYG_COMFY_SUBMIT_LOCK', value)
        assert mod._acquire_submit_lock() is None


def test_acquire_and_release_the_lock(monkeypatch, tmp_path):
    path = tmp_path / 'comfy.lock'
    monkeypatch.setenv('ZYG_COMFY_SUBMIT_LOCK_PATH', str(path))
    fd = mod._acquire_submit_lock(timeout_s='bogus')  # unusable timeout keeps the env budget
    assert isinstance(fd, int)
    assert path.is_file()
    mod._release_submit_lock(fd)
    mod._release_submit_lock(None)
    monkeypatch.setenv('ZYG_COMFY_SUBMIT_LOCK_PATH', '/nonexistent-dir-zyg/comfy.lock')
    assert mod._acquire_submit_lock() is None


@pytest.mark.parametrize('retry_works', [True, False])
def test_acquire_lock_retries_read_only_when_write_is_denied(monkeypatch, tmp_path, retry_works):
    path = tmp_path / 'ro.lock'
    path.write_text('')
    monkeypatch.setenv('ZYG_COMFY_SUBMIT_LOCK_PATH', str(path))
    real_open = os.open
    seen: list[int] = []

    def _fake_open(name, flags, *rest):
        if retry_works and seen:
            return real_open(name, flags, *rest)
        seen.append(flags)
        raise OSError(errno.EACCES, 'denied')

    monkeypatch.setattr(mod.os, 'open', _fake_open)
    fd = mod._acquire_submit_lock()
    monkeypatch.undo()
    assert isinstance(fd, int) if retry_works else fd is None
    mod._release_submit_lock(fd)

    def _no_locks(fd_, op):
        raise OSError(errno.ENOLCK, 'no locks available')

    monkeypatch.setenv('ZYG_COMFY_SUBMIT_LOCK_PATH', str(tmp_path / 'x.lock'))
    monkeypatch.setattr(mod.fcntl, 'flock', _no_locks)
    assert mod._acquire_submit_lock() is None


@pytest.fixture
def held_lock(monkeypatch, tmp_path):
    """A lock file already flocked by another descriptor of this process."""
    path = tmp_path / 'busy.lock'
    monkeypatch.setenv('ZYG_COMFY_SUBMIT_LOCK_PATH', str(path))
    holder = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    yield holder
    try:
        fcntl.flock(holder, fcntl.LOCK_UN)
        os.close(holder)
    except OSError:
        pass


@pytest.mark.parametrize(
    ('abort', 'wait_s', 'match'),
    [(True, '60', 'pipeline halt requested'), (False, '1', 'timed out after 1s')],
)
def test_acquire_lock_declines_behind_another_client(monkeypatch, held_lock, abort, wait_s, match):
    monkeypatch.setenv('ZYG_COMFY_SUBMIT_LOCK_WAIT_S', wait_s)
    monkeypatch.setattr(mod, 'time', FakeTime())
    with pytest.raises(mod.ComfyUIError, match=match):
        mod._acquire_submit_lock(should_abort=lambda: abort)


def test_acquire_lock_announces_a_long_wait_then_wins(monkeypatch, held_lock, caplog):
    def _release(count):
        if count == 8:
            fcntl.flock(held_lock, fcntl.LOCK_UN)

    monkeypatch.setenv('ZYG_COMFY_SUBMIT_LOCK_WAIT_S', '60')
    monkeypatch.setattr(mod, 'time', FakeTime(on_sleep=_release))
    with caplog.at_level(logging.INFO, logger=mod.__name__):
        fd = mod._acquire_submit_lock(timeout_s=10.0)
    assert isinstance(fd, int)
    mod._release_submit_lock(fd)
    assert any('submit lock busy' in m for m in caplog.messages)
    assert any('submit lock acquired after' in m for m in caplog.messages)


@pytest.fixture
def unlocked(monkeypatch):
    """submit() without the cross-process lock, on a fake clock."""
    monkeypatch.setenv('ZYG_COMFY_SUBMIT_LOCK', '0')
    monkeypatch.setenv('ZYG_COMFY_CLIENT_ID', 'fixed-client')
    monkeypatch.setattr(mod, 'time', FakeTime())


WF = {'6': {'class_type': 'CLIPTextEncode', 'inputs': {'text': 'old'}}, '9': {'class_type': 'SaveImage'}}


def test_submit_refuses_bad_input_and_a_bad_server(monkeypatch, unlocked):
    with pytest.raises(mod.ComfyUIError, match='unknown node id: 42'):
        mod.submit(WF, overrides={'42': {'text': 'hi'}})
    install_http(monkeypatch, post={'/prompt': BOOM})
    with pytest.raises(mod.ComfyUIError, match='submit failed'):
        mod.submit(WF)
    install_http(monkeypatch, post={'/prompt': FakeResp(500, text='gateway exploded', bad_json=True)})
    with pytest.raises(mod.ComfyUIError, match=r'submit rejected \(500\): unknown error'):
        mod.submit(WF)
    install_http(monkeypatch, post={'/prompt': FakeResp(200, {})})
    with pytest.raises(mod.ComfyUIError, match='no prompt_id in response'):
        mod.submit(WF)
    assert mod.last_submit_timing['prompt_id'] is None


def test_submit_reports_node_errors_from_a_rejection(monkeypatch, unlocked):
    payload = {
        'error': {'message': 'prompt outputs failed validation'},
        'node_errors': {'6': {'class_type': 'CLIPTextEncode', 'errors': [{'message': 'text is required'}]}},
    }
    install_http(monkeypatch, post={'/prompt': FakeResp(400, payload)})
    with pytest.raises(mod.ComfyUIError) as excinfo:
        mod.submit(WF)
    assert 'submit rejected (400): prompt outputs failed validation' in str(excinfo.value)
    assert 'node 6 [CLIPTextEncode]: text is required' in str(excinfo.value)


def test_submit_applies_overrides_and_returns_outputs(monkeypatch, unlocked, tmp_path):
    monkeypatch.setattr(mod, 'COMFY_OUTPUT', str(tmp_path))
    released: list[dict] = []
    monkeypatch.setattr(mod, 'release_memory', lambda **k: released.append(k))
    history = {
        'p-7': {
            'status': {'completed': True},
            'outputs': {'9': {'images': [{'filename': 'out.png', 'subfolder': 'sub'}, {'filename': ''}]}},
        }
    }
    calls = install_http(
        monkeypatch,
        get={'/system_stats': OK, '/history': FakeResp(200, history)},
        post={'/prompt': FakeResp(200, {'prompt_id': 'p-7'}), '/free': FakeResp(200)},
    )
    out = mod.submit(WF, overrides={'6': {'text': 'a cat'}}, timeout_s=30.0)
    assert out == [str(tmp_path / 'sub' / 'out.png')]
    assert WF['6']['inputs']['text'] == 'old'  # the template is never mutated
    body = next(kw['json'] for verb, path, kw in calls if path == '/prompt')
    assert body['prompt']['6']['inputs']['text'] == 'a cat'
    assert body['client_id'] == 'fixed-client'
    assert released == [{'wait': True, 'log_fn': None}]
    assert mod.last_submit_timing['prompt_id'] == 'p-7'
    assert mod.owned_prompt_ids() == set()


def test_submit_survives_a_failing_post_job_release(monkeypatch, unlocked, tmp_path):
    monkeypatch.setattr(mod, 'COMFY_OUTPUT', str(tmp_path))

    def _boom(**k):
        raise RuntimeError('housekeeping blew up')

    monkeypatch.setattr(mod, 'release_memory', _boom)
    history = {'p-8': {'status': {'completed': True}, 'outputs': {}}}
    install_http(
        monkeypatch,
        get={'/system_stats': OK, '/history': FakeResp(200, history)},
        post={'/prompt': FakeResp(200, {'prompt_id': 'p-8'}), '/free': FakeResp(200)},
    )
    assert mod.submit(WF) == []


def test_poll_aborts_fails_and_times_out(monkeypatch):
    monkeypatch.setattr(mod, 'time', FakeTime())
    seen: list[dict] = []
    monkeypatch.setattr(mod, 'interrupt_execution', lambda **k: seen.append(k) or True)
    monkeypatch.setattr(mod, 'free_vram', lambda *a, **k: True)
    with pytest.raises(mod.ComfyUIError, match='pipeline halt requested'):
        mod._poll_until_complete('p-1', 10.0, lambda: True)
    assert seen == [{'prompt_id': 'p-1'}]
    install_http(monkeypatch, get={'/history': BOOM})
    with pytest.raises(mod.ComfyUIError, match='history poll failed'):
        mod._poll_until_complete('p-1', 10.0, lambda: False)
    install_http(monkeypatch, get={'/history': FakeResp(200, {})})
    with pytest.raises(mod.ComfyUIError, match='timeout after 1.0s'):
        mod._poll_until_complete('p-1', 1.0, lambda: False)
    monkeypatch.setenv('ZYG_COMFY_KEEP_LOADED', '1')  # a completed job keeps its models
    install_http(monkeypatch, get={'/history': FakeResp(200, {'p-1': {'status': {'completed': True}}})})
    assert mod._poll_until_complete('p-1', 10.0, lambda: False) == []


def test_poll_waits_for_the_queue_then_releases_inline(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, 'time', FakeTime())
    monkeypatch.setattr(mod, 'COMFY_OUTPUT', str(tmp_path))
    monkeypatch.setattr(mod, 'free_vram', lambda *a, **k: True)
    released: list[dict] = []
    monkeypatch.setattr(mod, 'release_memory', lambda **k: released.append(k))
    done = {'p-1': {'status': {'completed': True}, 'outputs': {'9': {'gifs': [{'filename': 'a.webp'}]}}}}
    state = {'n': 0}

    def _history(_path, _kw):
        state['n'] += 1
        return FakeResp(200, {'p-1': {'status': {}}} if state['n'] == 1 else done)

    install_http(monkeypatch, get={'/history': _history})
    assert mod._poll_until_complete('p-1', 10.0, lambda: False) == [str(tmp_path / 'a.webp')]
    assert released == [{'wait': True, 'log_fn': None}]
    assert state['n'] == 2


def test_poll_surfaces_a_workflow_error(monkeypatch):
    monkeypatch.setattr(mod, 'time', FakeTime())
    err = {
        'node_id': '3',
        'node_type': 'KSampler',
        'exception_message': 'OOM',
        'traceback': ['l1', 'l2', 'l3', 'l4'],
    }
    history = {
        'p-1': {
            'status': {
                'status_str': 'error',
                'messages': [
                    ['execution_start', {}],
                    'not-a-pair',
                    ['execution_error', err],
                    ['execution_interrupted', {'exception_type': 'Interrupted'}],
                ],
            },
            'outputs': {'9': {'error': 'save failed'}},
        }
    }
    install_http(monkeypatch, get={'/history': FakeResp(200, history)})
    with pytest.raises(mod.ComfyUIError) as excinfo:
        mod._poll_until_complete('p-1', 10.0, lambda: False)
    text = str(excinfo.value)
    assert 'node 3 [KSampler]: OOM' in text
    assert '    l1' in text and 'l4' not in text
    assert 'node ? [?]: Interrupted' in text
    assert 'node 9 output error: save failed' in text


@pytest.mark.parametrize('symlinks', [True, False])
def test_stage_input_image(monkeypatch, tmp_path, symlinks):
    dest = tmp_path / 'comfy-input'
    monkeypatch.setattr(mod, 'COMFY_INPUT', str(dest))
    with pytest.raises(mod.ComfyUIError, match='input image not found'):
        mod.stage_input_image(str(tmp_path / 'ghost.png'))
    src = tmp_path / 'face.png'
    src.write_bytes(b'png')
    if not symlinks:

        def _boom(*a, **k):
            raise OSError('symlinks unsupported')

        monkeypatch.setattr(mod.os, 'symlink', _boom)
    name = mod.stage_input_image(str(src))
    assert name.endswith('_face.png')
    assert (dest / name).is_symlink() is symlinks
    assert (dest / name).read_bytes() == b'png'


def test_collect_outputs_walks_every_media_key(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, 'COMFY_OUTPUT', str(tmp_path))
    entry = {
        'outputs': {
            '1': {'images': [{'filename': 'i.png', 'subfolder': ''}]},
            '2': {'videos': [{'filename': 'v.mp4', 'subfolder': 'vid'}], 'audio': []},
            '3': {},
        }
    }
    assert mod._collect_outputs(entry) == [str(tmp_path / 'i.png'), str(tmp_path / 'vid' / 'v.mp4')]
    assert mod._collect_outputs({}) == []
