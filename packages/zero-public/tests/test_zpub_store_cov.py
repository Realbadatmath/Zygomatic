# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Coverage tests for :mod:`zyg_zero.zpub_store`.

The store keeps jobs, queues and per-visitor indexes in Redis when it can and on
disk when it cannot. Every test here redirects the module's four path constants
into ``tmp_path`` and replaces ``_get_redis`` with either ``None`` (the
in-memory/disk fallback) or a :class:`FakeRedis`, so nothing touches the real
runtime directory or a server.
"""

import json
import logging
import sys
import types

import pytest

import zyg_zero.zpub_store as m


# ── Doubles ───────────────────────────────────────────────────────────────────


class FakeRedis:
    """Enough of a Redis client for the calls the store makes."""

    def __init__(self, *, fail: bool = False, ping_fail: bool = False) -> None:
        self.fail = fail
        self.ping_fail = ping_fail
        self.kv: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.expiries: dict[str, int] = {}
        self.pings = 0

    def _guard(self) -> None:
        if self.fail:
            raise RuntimeError('redis down')

    def ping(self) -> bool:
        self.pings += 1
        if self.ping_fail:
            raise RuntimeError('no pong')
        return True

    def setex(self, key, ttl, value):
        self._guard()
        self.kv[key] = value
        self.expiries[key] = ttl

    def get(self, key):
        self._guard()
        return self.kv.get(key)

    def delete(self, key):
        self._guard()
        self.kv.pop(key, None)

    def rpush(self, key, value):
        self._guard()
        self.lists.setdefault(key, []).append(value)

    def llen(self, key):
        self._guard()
        return len(self.lists.get(key, []))

    def lrange(self, key, start, end):
        self._guard()
        items = self.lists.get(key, [])
        return items[start:] if end == -1 else items[start : end + 1]

    def expire(self, key, ttl):
        self._guard()
        self.expiries[key] = ttl


def _job(job_id: str, **extra) -> dict:
    job = {'job_id': job_id, 'status': 'queued', 'created_at': f'2026-10-0{job_id[-1]}T00:00:00'}
    job.update(extra)
    return job


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point every path constant at tmp_path and start from empty memory."""
    log_dir = tmp_path / 'runtime'
    log_dir.mkdir()
    monkeypatch.setattr(m, '_LOG_DIR', str(log_dir))
    monkeypatch.setattr(m, 'ZPUB_LOG_PATH', str(log_dir / 'zpub_user_log.jsonl'))
    monkeypatch.setattr(m, '_ZPUB_PENDING_PATH', str(log_dir / 'zpub_pending.json'))
    monkeypatch.setattr(m, '_JOB_PERSIST_DIR', str(log_dir / 'zpub_jobs'))
    monkeypatch.setattr(m, '_redis', None)
    monkeypatch.setattr(m, '_mem_jobs', {})
    monkeypatch.setattr(m, '_mem_queue', [])
    monkeypatch.setattr(m, '_mem_running', None)
    monkeypatch.setattr(m, '_get_redis', lambda: None)
    return log_dir


@pytest.fixture
def with_redis(store, monkeypatch):
    """A healthy FakeRedis behind ``_get_redis``."""
    fake = FakeRedis()
    monkeypatch.setattr(m, '_get_redis', lambda: fake)
    return fake


@pytest.fixture
def broken_redis(store, monkeypatch):
    """A client that is handed out but raises on every command."""
    fake = FakeRedis(fail=True)
    monkeypatch.setattr(m, '_get_redis', lambda: fake)
    return fake


@pytest.fixture
def blocked_dir(store, monkeypatch):
    """Make ``_JOB_PERSIST_DIR``/``_LOG_DIR`` unmakeable: a regular file is in the way."""
    blocker = store / 'blocker'
    blocker.write_text('not a directory', encoding='utf-8')
    monkeypatch.setattr(m, '_JOB_PERSIST_DIR', str(blocker / 'jobs'))
    return blocker


# ── Key helpers ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('fn', 'arg', 'expected'),
    [
        ('_jk', 'j1', 'zpub:job:j1'),
        ('_sk', 's1', 'zpub:sess:s1'),
        ('_rk', '10.0.0.1', 'zpub:rate:10.0.0.1'),
        ('_tk', 'tok', 'zpub:token:tok'),
    ],
)
def test_key_helpers_namespace_their_argument(fn, arg, expected):
    assert getattr(m, fn)(arg) == expected


def test_module_level_key_constants():
    assert (m._QUEUE_KEY, m._RUNNING_KEY, m._HALT_KEY) == (
        'zpub:queue',
        'zpub:running',
        'zpub:halted',
    )


def test_check_rate_limit_is_always_permissive():
    assert m._check_rate_limit('203.0.113.7') is True


# ── Pending queue ─────────────────────────────────────────────────────────────


def test_pending_load_is_empty_when_no_file_exists(store):
    assert m._pending_load() == []


def test_pending_load_recovers_from_a_corrupt_file(store):
    (store / 'zpub_pending.json').write_text('{not json', encoding='utf-8')
    assert m._pending_load() == []


def test_pending_save_writes_atomically_and_leaves_no_tmp(store):
    m._pending_save([{'id': 'a'}])
    path = store / 'zpub_pending.json'
    assert json.loads(path.read_text(encoding='utf-8')) == [{'id': 'a'}]
    assert not (store / 'zpub_pending.json.tmp').exists()


def test_pending_save_creates_the_log_dir_if_missing(store, monkeypatch):
    nested = store / 'deep' / 'deeper'
    monkeypatch.setattr(m, '_LOG_DIR', str(nested))
    monkeypatch.setattr(m, '_ZPUB_PENDING_PATH', str(nested / 'zpub_pending.json'))
    m._pending_save([])
    assert nested.is_dir()


def test_pending_store_appends_and_returns_the_id(store):
    assert m._pending_store({'id': 'req-1', 'kind': 'write'}) == 'req-1'
    assert m._pending_store({'id': 'req-2'}) == 'req-2'
    assert [r['id'] for r in m._pending_load()] == ['req-1', 'req-2']


# ── Job disk persistence ──────────────────────────────────────────────────────


def test_persist_job_round_trips_through_disk(store):
    m._persist_job(_job('j1', prompt='héllo'))
    written = store / 'zpub_jobs' / 'j1.json'
    assert json.loads(written.read_text(encoding='utf-8'))['prompt'] == 'héllo'
    assert m._load_job_from_disk('j1') == _job('j1', prompt='héllo')


def test_persist_job_logs_and_swallows_a_write_failure(blocked_dir, caplog):
    with caplog.at_level(logging.INFO, logger=m.__name__):
        m._persist_job(_job('j1'))
    assert 'job persist error' in caplog.text


def test_load_job_from_disk_returns_none_when_absent(store):
    assert m._load_job_from_disk('nope') is None


def test_load_job_from_disk_returns_none_on_corrupt_json(store):
    jobs = store / 'zpub_jobs'
    jobs.mkdir()
    (jobs / 'bad.json').write_text('{[', encoding='utf-8')
    assert m._load_job_from_disk('bad') is None


# ── Activity log ──────────────────────────────────────────────────────────────


def test_zpub_log_appends_one_json_line_per_event(store):
    m._zpub_log('submit', job_id='j1')
    m._zpub_log('finish', job_id='j1', ok=True)
    lines = (store / 'zpub_user_log.jsonl').read_text(encoding='utf-8').strip().splitlines()
    entries = [json.loads(line) for line in lines]
    assert [e['event'] for e in entries] == ['submit', 'finish']
    assert entries[1]['ok'] is True
    assert entries[0]['ts']  # timestamp supplied by zpub_config._ams_iso


def test_zpub_log_creates_a_missing_parent_directory(store, monkeypatch):
    target = store / 'fresh' / 'log.jsonl'
    monkeypatch.setattr(m, 'ZPUB_LOG_PATH', str(target))
    m._zpub_log('ping')
    assert target.is_file()


def test_zpub_log_logs_and_swallows_a_write_failure(store, monkeypatch, caplog):
    blocker = store / 'file-in-the-way'
    blocker.write_text('x', encoding='utf-8')
    monkeypatch.setattr(m, 'ZPUB_LOG_PATH', str(blocker / 'sub' / 'log.jsonl'))
    with caplog.at_level(logging.INFO, logger=m.__name__):
        m._zpub_log('submit')
    assert 'log write error' in caplog.text


# ── _get_redis ────────────────────────────────────────────────────────────────


def _redis_module(client=None, *, raises=False):
    mod = types.ModuleType('redis')

    def from_url(url, **kwargs):
        if raises:
            raise OSError(f'cannot reach {url}')
        return client

    mod.from_url = from_url
    return mod


def test_get_redis_reuses_a_cached_client_that_still_answers(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(m, '_redis', fake)
    assert m._get_redis() is fake
    assert fake.pings == 1


def test_get_redis_replaces_a_cached_client_that_stopped_answering(monkeypatch):
    stale = FakeRedis(ping_fail=True)
    fresh = FakeRedis()
    monkeypatch.setattr(m, '_redis', stale)
    monkeypatch.setitem(sys.modules, 'redis', _redis_module(fresh))
    assert m._get_redis() is fresh
    assert m._redis is fresh


def test_get_redis_connects_and_caches_when_there_is_no_client_yet(monkeypatch):
    fresh = FakeRedis()
    monkeypatch.setattr(m, '_redis', None)
    monkeypatch.setitem(sys.modules, 'redis', _redis_module(fresh))
    assert m._get_redis() is fresh
    assert fresh.pings == 1


def test_get_redis_returns_none_and_logs_when_the_server_is_unreachable(monkeypatch, caplog):
    monkeypatch.setattr(m, '_redis', None)
    monkeypatch.setitem(sys.modules, 'redis', _redis_module(raises=True))
    with caplog.at_level(logging.INFO, logger=m.__name__):
        assert m._get_redis() is None
    assert 'Redis unavailable' in caplog.text


# ── _save_job / _load_job ─────────────────────────────────────────────────────


def test_save_job_without_redis_fills_memory_and_disk(store):
    m._save_job(_job('j1'))
    assert m._mem_jobs['j1']['job_id'] == 'j1'
    assert (store / 'zpub_jobs' / 'j1.json').is_file()


def test_save_job_with_redis_also_sets_the_job_key_with_a_ttl(with_redis):
    m._save_job(_job('j1'))
    assert json.loads(with_redis.kv['zpub:job:j1'])['job_id'] == 'j1'
    assert with_redis.expiries['zpub:job:j1'] == m.JOB_TTL


def test_save_job_survives_a_redis_that_raises(broken_redis, store):
    m._save_job(_job('j1'))
    assert m._mem_jobs['j1']['job_id'] == 'j1'
    assert (store / 'zpub_jobs' / 'j1.json').is_file()


def test_load_job_prefers_redis(with_redis):
    with_redis.kv['zpub:job:j1'] = json.dumps(_job('j1', status='done'))
    m._mem_jobs['j1'] = _job('j1', status='stale')
    assert m._load_job('j1')['status'] == 'done'


def test_load_job_falls_back_to_memory_when_redis_raises(broken_redis):
    m._mem_jobs['j1'] = _job('j1', status='running')
    assert m._load_job('j1')['status'] == 'running'


def test_load_job_falls_back_to_memory_when_redis_has_no_entry(with_redis):
    m._mem_jobs['j1'] = _job('j1')
    assert m._load_job('j1')['job_id'] == 'j1'


def test_load_job_warms_the_memory_cache_from_disk(store):
    m._persist_job(_job('j1', status='done'))
    assert m._mem_jobs == {}
    assert m._load_job('j1')['status'] == 'done'
    assert m._mem_jobs['j1']['status'] == 'done'


def test_load_job_returns_none_when_nothing_knows_the_id(store):
    assert m._load_job('ghost') is None


# ── Queue ─────────────────────────────────────────────────────────────────────


def test_enqueue_and_read_the_queue_through_redis(with_redis):
    m._enqueue('j1')
    m._enqueue('j2')
    assert with_redis.lists['zpub:queue'] == ['j1', 'j2']
    assert m._queue_length() == 2
    assert m._queue_position('j2') == 2
    assert m._queue_position('nope') == 0
    assert m._mem_queue == []


def test_enqueue_and_read_the_queue_in_memory(store):
    m._enqueue('j1')
    m._enqueue('j2')
    assert m._mem_queue == ['j1', 'j2']
    assert m._queue_length() == 2
    assert m._queue_position('j1') == 1
    assert m._queue_position('nope') == 0


def test_queue_operations_fall_back_to_memory_when_redis_raises(broken_redis):
    m._enqueue('j1')
    assert m._mem_queue == ['j1']
    assert m._queue_length() == 1
    assert m._queue_position('j1') == 1


# ── Running pointer ───────────────────────────────────────────────────────────


def test_running_pointer_round_trips_through_redis(with_redis):
    assert m._get_running() is None
    m._set_running('j1')
    assert with_redis.kv['zpub:running'] == 'j1'
    assert with_redis.expiries['zpub:running'] == m.JOB_TTL
    assert m._get_running() == 'j1'
    m._set_running(None)
    assert 'zpub:running' not in with_redis.kv
    assert m._get_running() is None


def test_running_pointer_round_trips_in_memory(store):
    assert m._get_running() is None
    m._set_running('j1')
    assert m._mem_running == 'j1'
    assert m._get_running() == 'j1'
    m._set_running(None)
    assert m._get_running() is None


def test_running_pointer_falls_back_to_memory_when_redis_raises(broken_redis):
    m._set_running('j1')
    assert m._mem_running == 'j1'
    assert m._get_running() == 'j1'


# ── Session index ─────────────────────────────────────────────────────────────


def test_persist_session_index_creates_then_extends_the_index(store):
    m._persist_session_index('s1', 'j1')
    m._persist_session_index('s1', 'j2')
    m._persist_session_index('s1', 'j1')  # idempotent
    idx = store / 'zpub_jobs' / '_sess_s1.json'
    assert json.loads(idx.read_text(encoding='utf-8')) == ['j1', 'j2']


def test_persist_session_index_rewrites_a_corrupt_index(store):
    jobs = store / 'zpub_jobs'
    jobs.mkdir()
    (jobs / '_sess_s1.json').write_text('garbage', encoding='utf-8')
    m._persist_session_index('s1', 'j1')
    assert json.loads((jobs / '_sess_s1.json').read_text(encoding='utf-8')) == ['j1']


def test_persist_session_index_logs_and_swallows_a_write_failure(blocked_dir, caplog):
    with caplog.at_level(logging.INFO, logger=m.__name__):
        m._persist_session_index('s1', 'j1')
    assert 'session index persist error' in caplog.text


def test_link_session_job_writes_redis_and_disk(with_redis, store):
    m._link_session_job('s1', 'j1')
    assert with_redis.lists['zpub:sess:s1'] == ['j1']
    assert with_redis.expiries['zpub:sess:s1'] == m.JOB_TTL
    assert (store / 'zpub_jobs' / '_sess_s1.json').is_file()


def test_link_session_job_still_writes_disk_when_redis_raises(broken_redis, store):
    m._link_session_job('s1', 'j1')
    assert (store / 'zpub_jobs' / '_sess_s1.json').is_file()


def test_session_jobs_reads_redis_first(with_redis):
    with_redis.lists['zpub:sess:s1'] = ['j1', 'j2']
    assert m._session_jobs('s1') == ['j1', 'j2']


def test_session_jobs_falls_back_to_disk_when_redis_is_empty(with_redis, store):
    m._persist_session_index('s1', 'j9')
    assert m._session_jobs('s1') == ['j9']


def test_session_jobs_falls_back_to_disk_when_redis_raises(broken_redis, store):
    m._persist_session_index('s1', 'j9')
    assert m._session_jobs('s1') == ['j9']


def test_session_jobs_is_empty_for_an_unknown_session(store):
    assert m._session_jobs('nobody') == []


def test_session_jobs_is_empty_when_the_disk_index_is_corrupt(store):
    jobs = store / 'zpub_jobs'
    jobs.mkdir()
    (jobs / '_sess_s1.json').write_text('oops', encoding='utf-8')
    assert m._session_jobs('s1') == []


# ── Token index ───────────────────────────────────────────────────────────────


def test_persist_token_index_creates_then_extends_the_index(store):
    m._persist_token_index('tok', 'j1')
    m._persist_token_index('tok', 'j2')
    m._persist_token_index('tok', 'j2')  # idempotent
    idx = store / 'zpub_jobs' / '_tok_tok.json'
    assert json.loads(idx.read_text(encoding='utf-8')) == ['j1', 'j2']


def test_persist_token_index_rewrites_a_corrupt_index(store):
    jobs = store / 'zpub_jobs'
    jobs.mkdir()
    (jobs / '_tok_tok.json').write_text('[[[', encoding='utf-8')
    m._persist_token_index('tok', 'j1')
    assert json.loads((jobs / '_tok_tok.json').read_text(encoding='utf-8')) == ['j1']


def test_persist_token_index_logs_and_swallows_a_write_failure(blocked_dir, caplog):
    with caplog.at_level(logging.INFO, logger=m.__name__):
        m._persist_token_index('tok', 'j1')
    assert 'token index persist error' in caplog.text


def test_link_token_job_writes_redis_and_disk(with_redis, store):
    m._link_token_job('tok', 'j1')
    assert with_redis.lists['zpub:token:tok'] == ['j1']
    assert with_redis.expiries['zpub:token:tok'] == m.JOB_TTL
    assert (store / 'zpub_jobs' / '_tok_tok.json').is_file()


def test_link_token_job_still_writes_disk_when_redis_raises(broken_redis, store):
    m._link_token_job('tok', 'j1')
    assert (store / 'zpub_jobs' / '_tok_tok.json').is_file()


# ── _jobs_for_token ───────────────────────────────────────────────────────────


def test_jobs_for_token_returns_newest_first_from_redis(with_redis):
    for jid in ('j1', 'j2', 'j3'):
        m._save_job(_job(jid))
        m._link_token_job('tok', jid)
    assert [j['job_id'] for j in m._jobs_for_token('tok')] == ['j3', 'j2', 'j1']


def test_jobs_for_token_falls_back_to_the_disk_index(store):
    for jid in ('j1', 'j2'):
        m._save_job(_job(jid))
        m._persist_token_index('tok', jid)
    assert [j['job_id'] for j in m._jobs_for_token('tok')] == ['j2', 'j1']


def test_jobs_for_token_falls_back_to_disk_when_redis_raises(broken_redis, store):
    m._save_job(_job('j1'))
    m._persist_token_index('tok', 'j1')
    assert [j['job_id'] for j in m._jobs_for_token('tok')] == ['j1']


def test_jobs_for_token_caps_at_fifty_and_drops_unknown_ids(store):
    for n in range(55):
        jid = f'job{n}'
        if n % 2 == 0:  # only half of the indexed ids have a stored job
            m._save_job({'job_id': jid, 'created_at': f'2026-01-01T00:{n:02d}:00'})
        m._persist_token_index('tok', jid)
    jobs = m._jobs_for_token('tok')
    assert len(jobs) == 25  # 50 newest ids, of which 25 resolve to a job
    assert jobs[0]['job_id'] == 'job54'


def test_jobs_for_token_is_empty_for_an_unknown_token(store):
    assert m._jobs_for_token('nobody') == []


def test_jobs_for_token_is_empty_when_the_disk_index_is_corrupt(store):
    jobs = store / 'zpub_jobs'
    jobs.mkdir()
    (jobs / '_tok_tok.json').write_text('nope', encoding='utf-8')
    assert m._jobs_for_token('tok') == []


# ── _jobs_for_library ─────────────────────────────────────────────────────────


def test_jobs_for_library_merges_session_and_token_jobs_newest_first(store):
    m._save_job({'job_id': 'old', 'created_at': '2026-01-01T00:00:00'})
    m._save_job({'job_id': 'mid', 'created_at': '2026-02-01T00:00:00'})
    m._save_job({'job_id': 'new', 'created_at': '2026-03-01T00:00:00'})
    m._persist_session_index('s1', 'old')
    m._persist_session_index('s1', 'new')
    m._persist_token_index('tok', 'mid')
    assert [j['job_id'] for j in m._jobs_for_library('tok', 's1')] == ['new', 'mid', 'old']


def test_jobs_for_library_dedupes_a_job_known_to_both_indexes(store):
    m._save_job(_job('j1'))
    m._persist_session_index('s1', 'j1')
    m._persist_token_index('tok', 'j1')
    assert [j['job_id'] for j in m._jobs_for_library('tok', 's1')] == ['j1']


@pytest.mark.parametrize('token', ['', '__admin__'])
def test_jobs_for_library_ignores_the_token_index_for_admin_and_empty_tokens(store, token):
    m._save_job(_job('j1'))
    m._save_job(_job('j2'))
    m._persist_session_index('s1', 'j1')
    m._persist_token_index(token or 'tok', 'j2')
    assert [j['job_id'] for j in m._jobs_for_library(token, 's1')] == ['j1']


def test_jobs_for_library_skips_ids_whose_job_is_gone(store):
    m._save_job(_job('j1'))
    m._persist_session_index('s1', 'j1')
    m._persist_session_index('s1', 'vanished')
    assert [j['job_id'] for j in m._jobs_for_library('', 's1')] == ['j1']


def test_jobs_for_library_caps_at_fifty(store):
    for n in range(60):
        jid = f'job{n:02d}'
        m._save_job({'job_id': jid, 'created_at': f'2026-01-01T00:{n:02d}:00'})
        m._persist_session_index('s1', jid)
    jobs = m._jobs_for_library('', 's1')
    assert len(jobs) == 50
    assert jobs[0]['job_id'] == 'job59'


def test_jobs_for_library_is_empty_for_an_unknown_browser(store):
    assert m._jobs_for_library('', 'nobody') == []
