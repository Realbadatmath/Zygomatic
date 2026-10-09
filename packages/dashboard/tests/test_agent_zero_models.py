# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for agent_zero.models -- no Flask app, no network, no GPU.

Every HTTP call the registry makes goes through ``models.requests``, which these tests
replace with a fake, and both state files (``agent_zero.json``, the provider key store)
are redirected into ``tmp_path`` by patching the two ``_host`` accessors.
"""

import json
import os
import time

import pytest

from zyg_dashboard.agent_zero import _host, models

KEY_ENVS = (
    'OPENAI_API_KEY',
    'ANTHROPIC_API_KEY',
    'GEMINI_API_KEY',
    'GOOGLE_API_KEY',
    'OPENROUTER_API_KEY',
    'GROQ_API_KEY',
    'DEEPSEEK_API_KEY',
    'MISTRAL_API_KEY',
    'XAI_API_KEY',
    'TOGETHER_API_KEY',
)

TAGS = {
    'models': [
        {
            'name': 'qwen3.5:9b',
            'size': 6_590_000_000,
            'modified_at': '2026-09-01T10:00:00Z',
            'details': {'family': 'qwen35', 'parameter_size': '9.7B'},
        },
        {
            'name': 'vicky:latest',
            'size': 25_050_000_000,
            'modified_at': '2026-08-01T10:00:00Z',
            'details': {'family': 'llama', 'parameter_size': '23.6B'},
        },
    ]
}


class FakeResp:
    def __init__(self, payload=None, status=200, lines=None):
        self._payload = payload if payload is not None else {}
        self.status_code = status
        self._lines = lines or []

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')

    def iter_lines(self):
        for line in self._lines:
            yield json.dumps(line).encode('utf-8')


class FakeRequests:
    """Answers /api/version and /api/tags; records every POST."""

    def __init__(self, pull_lines=None):
        self.pull_lines = pull_lines or []
        self.posts = []

    def get(self, url, **kwargs):
        if url.endswith('/api/version'):
            return FakeResp({'version': '0.17.7'})
        if url.endswith('/api/tags'):
            return FakeResp(TAGS)
        raise AssertionError(f'unexpected GET {url}')

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResp(lines=self.pull_lines)


@pytest.fixture()
def reg(tmp_path, monkeypatch):
    """The registry with its files in tmp_path, no API keys, and a fake HTTP client."""
    data = tmp_path / 'data'
    runtime = data / 'runtime'
    runtime.mkdir(parents=True)
    monkeypatch.setattr(_host, 'data_dir', lambda: str(data))
    monkeypatch.setattr(_host, 'runtime_dir', lambda: str(runtime))
    for name in KEY_ENVS:
        monkeypatch.delenv(name, raising=False)
    fake = FakeRequests()
    monkeypatch.setattr(models, 'requests', fake)
    models._live_cache.clear()
    with models._jobs_lock:
        models._jobs.clear()
    yield fake
    models._live_cache.clear()
    with models._jobs_lock:
        models._jobs.clear()


def test_catalog_counts():
    cat = models.catalog()
    assert len(cat['subscription']) == 6
    assert next(m['id'] for m in cat['subscription']) == 'claude-opus-5'
    assert len(cat['local']['ollama']) >= 40
    assert len(cat['api']) == 9
    for entry in cat['local']['ollama']:
        for field in ('id', 'label', 'size_gb', 'vram_gb', 'ram_gb', 'family', 'tools', 'vision'):
            assert field in entry, f'{entry["id"]} lacks {field}'


def test_default_selection_and_legacy_keys_survive(reg, tmp_path):
    cfg_path = tmp_path / 'data' / 'agent_zero.json'
    cfg_path.write_text(json.dumps({'name': 'Zero', 'llms': {'primary': 'legacy-model'}}), encoding='utf-8')

    assert models.get_selection() == {'provider': 'subscription', 'model': 'claude-opus-5'}

    models.set_selection('subscription', 'claude-sonnet-5-5')
    assert models.get_selection() == {'provider': 'subscription', 'model': 'claude-sonnet-5-5'}

    after = json.loads(cfg_path.read_text(encoding='utf-8'))
    assert after['name'] == 'Zero'
    assert after['llms'] == {'primary': 'legacy-model'}
    assert after['selected_model']['provider'] == 'subscription'


def test_set_selection_rejects_uninstalled_ollama_model(reg):
    with pytest.raises(ValueError) as err:
        models.set_selection('ollama', 'not-there')
    assert 'not installed' in str(err.value)
    # the installed one is accepted
    assert models.set_selection('ollama', 'qwen3.5:9b')['model'] == 'qwen3.5:9b'


def test_fit_rejects_a_65gb_model_on_this_gpu():
    entry = next(e for e in models.seed_models('ollama') if e['id'] == 'gpt-oss:120b')
    assert entry['size_gb'] == 65.0
    mach = {
        'vram_total_gb': 48.0,
        'vram_free_gb': 37.0,
        'ram_total_gb': 62.0,
        'ram_avail_gb': 40.0,
        'disk_free_gb': 44.0,
    }
    verdict = models.fit(entry, mach)
    assert verdict['ok'] is False
    vram_reason = next(r for r in verdict['reasons'] if 'VRAM' in r)
    assert '74' in vram_reason and '48' in vram_reason, vram_reason

    small = next(e for e in models.seed_models('ollama') if e['id'] == 'qwen3.5:9b')
    assert models.fit(small, mach)['ok'] is True


def test_fit_warns_when_vram_is_busy_but_big_enough():
    entry = next(e for e in models.seed_models('ollama') if e['id'] == 'qwen2.5:32b')
    mach = {'vram_total_gb': 48.0, 'vram_free_gb': 8.0, 'ram_total_gb': 62.0, 'disk_free_gb': 200.0}
    verdict = models.fit(entry, mach)
    assert verdict['ok'] is True
    assert any('free up' in r for r in verdict['reasons'])


def test_provider_status_and_key_store(reg, tmp_path):
    assert models.provider_status('openai')[0] == 'no_key'
    assert 'OPENAI_API_KEY' in models.provider_status('openai')[1]

    result = models.set_provider_key('openai', 'sk-test-abcd1234')
    assert result == {'set': True, 'suffix': '1234'}
    assert models.provider_status('openai')[0] == 'ready'

    keys_path = tmp_path / 'data' / 'runtime' / 'zero_provider_keys.json'
    assert oct(os.stat(keys_path).st_mode & 0o777) == '0o600'
    assert json.loads(keys_path.read_text(encoding='utf-8')) == {'openai': 'sk-test-abcd1234'}

    assert models.clear_provider_key('openai') == {'cleared': True}
    assert models.provider_status('openai')[0] == 'no_key'


def test_start_install_requires_confirmation(reg):
    with pytest.raises(ValueError) as err:
        models.start_install('qwen3:8b')
    assert 'confirmation required' in str(err.value)


def test_start_install_refuses_a_model_that_does_not_fit(reg, monkeypatch):
    monkeypatch.setattr(
        models,
        'machine',
        lambda: {
            'vram_total_gb': 48.0,
            'vram_free_gb': 48.0,
            'ram_total_gb': 62.0,
            'ram_avail_gb': 50.0,
            'disk_free_gb': 44.0,
            'ollama_version': '0.17.7',
        },
    )
    with pytest.raises(ValueError) as err:
        models.start_install('gpt-oss:120b', confirm=True)
    assert 'does not fit' in str(err.value)


def test_streaming_pull_finishes_at_100_pct(reg, tmp_path, monkeypatch):
    reg.pull_lines = [
        {'status': 'pulling manifest'},
        {'status': 'pulling 1a2b3c', 'digest': 'sha256:1a2b3c', 'total': 1000, 'completed': 400},
        {'status': 'pulling 1a2b3c', 'digest': 'sha256:1a2b3c', 'total': 1000, 'completed': 1000},
    ]
    job_id = models.start_install('tinyfake:1b', confirm=True)['job_id']

    deadline = time.time() + 10
    job = models.install_status(job_id)
    while job['status'] == 'running' and time.time() < deadline:
        time.sleep(0.05)
        job = models.install_status(job_id)

    assert job['status'] == 'done', job
    assert job['pct'] == 100
    assert job['total'] == 1000
    assert job['error'] == ''
    assert reg.posts[0][0].endswith('/api/pull')
    assert reg.posts[0][1]['json'] == {'model': 'tinyfake:1b', 'stream': True}

    log_path = tmp_path / 'data' / 'runtime' / 'zero_installs.jsonl'
    rows = [json.loads(line) for line in log_path.read_text(encoding='utf-8').splitlines()]
    assert [r['status'] for r in rows] == ['start', 'done']
    assert rows[1]['model'] == 'tinyfake:1b'


def test_one_install_at_a_time(reg, monkeypatch):
    with models._jobs_lock:
        models._jobs['busy'] = {'job_id': 'busy', 'model': 'qwen3:8b', 'status': 'running'}
    with pytest.raises(ValueError) as err:
        models.start_install('llama3.2:3b', confirm=True)
    assert 'already running' in str(err.value)


def test_list_models_payload_shape(reg, monkeypatch):
    monkeypatch.setattr(
        models,
        'machine',
        lambda: {
            'vram_total_gb': 48.0,
            'vram_free_gb': 37.0,
            'ram_total_gb': 62.0,
            'ram_avail_gb': 40.0,
            'disk_free_gb': 44.0,
            'ollama_version': '0.17.7',
        },
    )
    payload = models.list_models()
    assert set(payload) == {'selected', 'providers', 'machine', 'defaults'}
    assert payload['defaults'] == {'provider': 'subscription', 'model': 'claude-opus-5'}
    assert payload['selected'] == {'provider': 'subscription', 'model': 'claude-opus-5'}

    ids = [p['id'] for p in payload['providers']]
    assert ids[0] == 'subscription'
    assert ids[-1] == 'ollama'
    assert len(ids) == 11

    for prov in payload['providers']:
        assert set(prov) >= {'id', 'label', 'kind', 'status', 'status_text', 'models'}
        assert prov['kind'] in ('subscription', 'api', 'local')
        for entry in prov['models']:
            assert set(entry) >= {'id', 'label', 'installed', 'fit', 'seed'}

    ollama = payload['providers'][-1]
    assert ollama['kind'] == 'local'
    assert ollama['status'] == 'ready'
    by_id = {m['id']: m for m in ollama['models']}
    assert by_id['qwen3.5:9b']['installed'] is True
    assert by_id['llama3.3:70b']['installed'] is False
    # an installed model absent from the seed catalogue is still offered
    assert by_id['vicky:latest']['seed'] is False
    assert by_id['gpt-oss:120b']['fit']['ok'] is False

    api_block = next(p for p in payload['providers'] if p['id'] == 'openai')
    assert api_block['status'] == 'no_key'
    assert all(m['seed'] is True for m in api_block['models'])
