# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The model registry behind Agent Zero v2's "Select Model" panel.

Everything the operator needs in order to choose which brain Agent Zero runs on:

* the seed catalogue (``models_catalog.json``) of every LLM a person might plausibly
  run here -- the Claude Code subscription, nine hosted APIs, and the local Ollama
  library;
* live status per provider (key present? CLI logged in? Ollama up?) and the live
  ``/models`` list of a provider once its key is known;
* a machine-fit check, so a 70B model is never offered as if it fitted in the GPU;
* Ollama pull jobs with progress, so a model can be installed from the panel;
* the persisted selection (default: Claude Opus 5 on the subscription).

No Flask here -- the HTTP surface lives in :mod:`agent_zero.routes_models`. Every host
name comes from :mod:`agent_zero._host`.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid

import requests

from . import _host
from .contracts import PROVIDERS

_log = logging.getLogger(__name__)

CATALOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models_catalog.json')
KEYS_FILENAME = 'zero_provider_keys.json'
INSTALL_LOG_FILENAME = 'zero_installs.jsonl'
SELECTION_KEY = 'selected_model'
DEFAULT_SELECTION = {'provider': 'subscription', 'model': 'claude-opus-5'}

#: How long a provider's live /models answer is reused.
LIVE_CACHE_S = 600
#: VRAM headroom (GB) kept free when judging whether a model can load right now.
VRAM_RESERVE_GB = 2.0
#: Disk headroom (GB) on top of a model's download size.
DISK_RESERVE_GB = 2.0

_catalog_cache: dict | None = None
_live_cache: dict[str, tuple[float, list[dict], str]] = {}
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


# --------------------------------------------------------------------------- catalogue


def catalog() -> dict:
    """The seed catalogue, parsed once and cached."""
    global _catalog_cache
    cache = _catalog_cache
    if cache is None:
        with open(CATALOG_PATH, encoding='utf-8') as fh:
            cache = json.load(fh)
        _catalog_cache = cache
    return cache


def seed_models(provider: str) -> list[dict]:
    """The catalogue's seed model list for one provider id."""
    cat = catalog()
    if provider == 'subscription':
        return list(cat.get('subscription') or [])
    if provider == 'ollama':
        return list((cat.get('local') or {}).get('ollama') or [])
    entry = (cat.get('api') or {}).get(provider) or {}
    return list(entry.get('models') or [])


def provider_meta(provider: str) -> dict:
    """Label / key_env / base_url / models_endpoint for one provider id."""
    if provider == 'subscription':
        return {
            'label': 'Claude Code subscription',
            'key_env': [],
            'base_url': '',
            'models_endpoint': None,
        }
    if provider == 'ollama':
        return {
            'label': 'Local (Ollama)',
            'key_env': [],
            'base_url': _host.ollama_url(),
            'models_endpoint': '/api/tags',
        }
    entry = (catalog().get('api') or {}).get(provider) or {}
    return {
        'label': entry.get('label') or provider,
        'key_env': list(entry.get('key_env') or []),
        'base_url': entry.get('base_url') or '',
        'models_endpoint': entry.get('models_endpoint'),
    }


def api_provider_ids() -> list[str]:
    """The hosted-API provider ids, in catalogue order."""
    return [p for p in (catalog().get('api') or {})]


# ----------------------------------------------------------------------------- machine


def machine() -> dict:
    """What this box can actually run: GPU, RAM, disk, Ollama version.

    Every field is ``None`` when it cannot be measured; nothing here raises.
    """
    vram_total = vram_free = None
    try:
        out = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.total,memory.used', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        line = (out.stdout or '').strip().splitlines()[0]
        total_mib, used_mib = (float(x.strip()) for x in line.split(',')[:2])
        vram_total = round(total_mib / 1024.0, 1)
        vram_free = round((total_mib - used_mib) / 1024.0, 1)
    except Exception as exc:  # noqa: BLE001 - no GPU / no driver / odd output
        _log.debug('agent_zero: nvidia-smi unavailable (%s)', exc)

    ram_total = ram_avail = None
    try:
        import psutil

        vm = psutil.virtual_memory()
        ram_total = round(vm.total / 1024**3, 1)
        ram_avail = round(vm.available / 1024**3, 1)
    except Exception as exc:  # noqa: BLE001 - psutil absent
        _log.debug('agent_zero: psutil unavailable (%s)', exc)

    disk_free = None
    try:
        disk_free = round(shutil.disk_usage('/').free / 1024**3, 1)
    except Exception as exc:  # noqa: BLE001
        _log.debug('agent_zero: disk_usage failed (%s)', exc)

    ollama_version = None
    try:
        resp = requests.get(f'{_host.ollama_url()}/api/version', timeout=5)
        if resp.status_code == 200:
            ollama_version = (resp.json() or {}).get('version')
    except Exception as exc:  # noqa: BLE001 - server down
        _log.debug('agent_zero: ollama version unavailable (%s)', exc)

    return {
        'vram_total_gb': vram_total,
        'vram_free_gb': vram_free,
        'ram_total_gb': ram_total,
        'ram_avail_gb': ram_avail,
        'disk_free_gb': disk_free,
        'ollama_version': ollama_version,
    }


def fit(entry: dict, mach: dict) -> dict:
    """Can this local model run on this machine? ``{'ok': bool, 'reasons': [str]}``.

    Hard reasons (VRAM capacity, disk, RAM) clear ``ok``. A model that fits the card
    but not the VRAM free *right now* stays ``ok`` with a warn-only reason.
    """
    reasons: list[str] = []
    ok = True

    need_vram = entry.get('vram_gb')
    vram_total = (mach or {}).get('vram_total_gb')
    if need_vram is not None and vram_total is not None and need_vram > vram_total:
        ok = False
        reasons.append(f'needs {_num(need_vram)} GB VRAM, GPU has {_num(vram_total)}')

    need_disk = entry.get('size_gb')
    disk_free = (mach or {}).get('disk_free_gb')
    if need_disk is not None and disk_free is not None and need_disk + DISK_RESERVE_GB > disk_free:
        ok = False
        reasons.append(f'needs {_num(need_disk + DISK_RESERVE_GB)} GB disk, {_num(disk_free)} free')

    need_ram = entry.get('ram_gb')
    ram_total = (mach or {}).get('ram_total_gb')
    if need_ram is not None and ram_total is not None and need_ram > ram_total:
        ok = False
        reasons.append(f'needs {_num(need_ram)} GB RAM, machine has {_num(ram_total)}')

    vram_free = (mach or {}).get('vram_free_gb')
    if ok and need_vram is not None and vram_free is not None and need_vram > vram_free:
        reasons.append(f'will wait for {_num(need_vram - vram_free)} GB of VRAM to free up')

    return {'ok': ok, 'reasons': reasons}


def _num(value) -> str:
    """Format a GB number without a pointless trailing ``.0``."""
    try:
        fval = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(fval)) if fval == int(fval) else f'{fval:.1f}'


# ------------------------------------------------------------------------ provider keys


def _keys_path() -> str:
    return os.path.join(_host.runtime_dir(), KEYS_FILENAME)


def _load_keys() -> dict:
    try:
        with open(_keys_path(), encoding='utf-8') as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001 - never leak the file contents
        _log.warning('agent_zero: provider key store unreadable (%s)', exc)
        return {}
    return data if isinstance(data, dict) else {}


def _save_keys(keys: dict) -> None:
    """Write the key store with mode 0600 (owner only), atomically."""
    path = _keys_path()
    tmp = f'{path}.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(keys, fh, indent=2)
            fh.write('\n')
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def provider_key(provider: str) -> str:
    """The API key for a provider: environment first, then the local key store."""
    for env_name in provider_meta(provider).get('key_env') or []:
        value = os.environ.get(env_name)
        if value:
            return value
    value = _load_keys().get(provider)
    return str(value) if value else ''


def set_provider_key(provider: str, key: str) -> dict:
    """Store an API key for a provider. Never logs or returns the key itself."""
    if provider not in PROVIDERS:
        raise ValueError(f'unknown provider: {provider}')
    key = (key or '').strip()
    if not key:
        raise ValueError('key is empty')
    keys = _load_keys()
    keys[provider] = key
    _save_keys(keys)
    _live_cache.pop(provider, None)
    _log.info('agent_zero: stored API key for %s', provider)
    return {'set': True, 'suffix': key[-4:]}


def clear_provider_key(provider: str) -> dict:
    """Forget the stored API key for a provider (the environment still wins)."""
    keys = _load_keys()
    existed = keys.pop(provider, None) is not None
    if existed:
        _save_keys(keys)
    _live_cache.pop(provider, None)
    return {'cleared': existed}


# ---------------------------------------------------------------------------- ollama


def installed_ollama() -> tuple[list[dict], str]:
    """``(entries, status)`` from ``GET /api/tags``; ``([], 'offline')`` when down.

    Entries carry ``id``, ``size_gb``, ``modified``, ``family``, ``parameter_size``.
    Models that are installed but absent from the seed catalogue are still listed.
    """
    try:
        resp = requests.get(f'{_host.ollama_url()}/api/tags', timeout=5)
        resp.raise_for_status()
        raw = (resp.json() or {}).get('models') or []
    except Exception as exc:  # noqa: BLE001 - server down or garbage answer
        _log.debug('agent_zero: ollama tags unavailable (%s)', exc)
        return [], 'offline'

    out = []
    for item in raw:
        name = item.get('name') or item.get('model') or ''
        if not name:
            continue
        size_gb = round((item.get('size') or 0) / 1024**3, 1)
        details = item.get('details') or {}
        out.append(
            {
                'id': name,
                'size_gb': size_gb,
                'modified': item.get('modified_at') or item.get('modified') or '',
                'family': details.get('family') or '',
                'parameter_size': details.get('parameter_size') or '',
            }
        )
    return out, 'ready'


def _entry_from_installed(item: dict) -> dict:
    """A catalogue-shaped entry for an installed model we have no seed row for."""
    size_gb = float(item.get('size_gb') or 0)
    return {
        'id': item['id'],
        'label': item['id'],
        'context': None,
        'vision': False,
        'tools': False,
        'price_in': None,
        'price_out': None,
        'size_gb': size_gb,
        'vram_gb': round(size_gb * 1.1 + 2),
        'ram_gb': round(size_gb + 4, 1),
        'family': item.get('family') or '',
        'notes': 'installed locally, not in the seed catalogue',
    }


# --------------------------------------------------------------------------- statuses


def provider_status(provider: str) -> tuple[str, str]:
    """``(status, status_text)`` where status is ready / no_key / offline / no_login."""
    if provider == 'subscription':
        cli = _host.claude_cli_bin()
        if not _host.claude_login_present():
            return 'no_login', 'no Claude Code login found (~/.claude/.credentials.json)'
        if not os.path.exists(cli):
            return 'no_login', f'claude CLI not found at {cli}'
        return 'ready', f'logged in, CLI at {cli}'

    if provider == 'ollama':
        mach_version = None
        try:
            resp = requests.get(f'{_host.ollama_url()}/api/version', timeout=5)
            if resp.status_code == 200:
                mach_version = (resp.json() or {}).get('version')
        except Exception as exc:  # noqa: BLE001
            return 'offline', f'ollama not reachable at {_host.ollama_url()} ({exc.__class__.__name__})'
        if not mach_version:
            return 'offline', f'ollama not reachable at {_host.ollama_url()}'
        return 'ready', f'ollama {mach_version}'

    meta = provider_meta(provider)
    if not provider_key(provider):
        names = ' or '.join(meta.get('key_env') or ['an API key'])
        return 'no_key', f'no API key ({names})'
    return 'ready', 'API key present'


def live_models(provider: str) -> tuple[list[dict], str]:
    """``(models, status_text)`` from the provider's live ``/models``, else the seed list.

    Answers are cached for :data:`LIVE_CACHE_S` seconds per provider. Any failure falls
    back to the seed list and reports the error in ``status_text``.
    """
    seed = seed_models(provider)
    if provider in ('subscription', 'ollama'):
        return seed, ''

    cached = _live_cache.get(provider)
    if cached and time.time() - cached[0] < LIVE_CACHE_S:
        return cached[1], cached[2]

    meta = provider_meta(provider)
    key = provider_key(provider)
    if not key:
        return seed, ''

    try:
        if provider == 'anthropic':
            resp = requests.get(
                'https://api.anthropic.com/v1/models',
                headers={'x-api-key': key, 'anthropic-version': '2023-06-01'},
                timeout=8,
            )
        else:
            endpoint = meta.get('models_endpoint') or '/models'
            resp = requests.get(
                f'{meta["base_url"].rstrip("/")}{endpoint}',
                headers={'Authorization': f'Bearer {key}'},
                timeout=8,
            )
        resp.raise_for_status()
        ids = _model_ids(resp.json() or {})
    except Exception as exc:  # noqa: BLE001 - network, auth, schema; all non-fatal
        text = f'live model list failed: {exc.__class__.__name__}: {exc}'
        _log.info('agent_zero: %s (%s)', text, provider)
        _live_cache[provider] = (time.time(), seed, text)
        return seed, text

    if not ids:
        text = 'live model list was empty, showing the seed list'
        _live_cache[provider] = (time.time(), seed, text)
        return seed, text

    by_id = {m['id']: m for m in seed}
    models = [dict(by_id[i], seed=False) if i in by_id else _live_entry(i) for i in ids]
    text = f'{len(models)} models from the provider'
    _live_cache[provider] = (time.time(), models, text)
    return models, text


def _model_ids(payload: dict) -> list[str]:
    """Pull model ids out of an OpenAI-shaped or Anthropic-shaped /models answer."""
    rows = payload.get('data') if isinstance(payload.get('data'), list) else payload.get('models')
    if not isinstance(rows, list):
        return []
    ids = []
    for row in rows:
        if isinstance(row, str):
            ids.append(row)
        elif isinstance(row, dict):
            found = row.get('id') or row.get('name') or row.get('model')
            if found:
                ids.append(str(found))
    return ids


def _live_entry(model_id: str) -> dict:
    """A catalogue-shaped entry for a live model id we have no seed row for."""
    return {
        'id': model_id,
        'label': model_id,
        'context': None,
        'vision': False,
        'tools': True,
        'price_in': None,
        'price_out': None,
    }


# ------------------------------------------------------------------------- the payload


def list_models() -> dict:
    """CONTRACT B: everything the Select Model panel renders, in one payload."""
    mach = machine()
    providers = [_subscription_block()]
    for pid in api_provider_ids():
        providers.append(_api_block(pid))
    providers.append(_ollama_block(mach))
    return {
        'selected': get_selection(),
        'providers': providers,
        'machine': mach,
        'defaults': dict(DEFAULT_SELECTION),
    }


def _subscription_block() -> dict:
    status, status_text = provider_status('subscription')
    models = [dict(m, installed=True, fit={'ok': True, 'reasons': []}, seed=True) for m in seed_models('subscription')]
    meta = provider_meta('subscription')
    return {
        'id': 'subscription',
        'label': meta['label'],
        'kind': 'subscription',
        'status': status,
        'status_text': status_text,
        'key_env': meta['key_env'],
        'models': models,
    }


def _api_block(provider: str) -> dict:
    status, status_text = provider_status(provider)
    models, live_text = live_models(provider)
    if live_text:
        status_text = f'{status_text}; {live_text}' if status_text else live_text
    out = [
        dict(m, installed=status == 'ready', fit={'ok': True, 'reasons': []}, seed=bool(m.get('seed', True)))
        for m in models
    ]
    meta = provider_meta(provider)
    return {
        'id': provider,
        'label': meta['label'],
        'kind': 'api',
        'status': status,
        'status_text': status_text,
        'key_env': meta['key_env'],
        'models': out,
    }


def _ollama_block(mach: dict) -> dict:
    installed, tags_status = installed_ollama()
    status, status_text = ('offline', f'ollama not reachable at {_host.ollama_url()}')
    if tags_status == 'ready':
        status, status_text = provider_status('ollama')
    installed_ids = {item['id'] for item in installed}
    # A bare seed id such as 'llama3.1:8b' is installed as itself; 'nomic-embed-text'
    # shows up as 'nomic-embed-text:latest'.
    installed_bare = {i.split(':')[0] for i in installed_ids}

    models = []
    for entry in seed_models('ollama'):
        is_installed = entry['id'] in installed_ids or (':' not in entry['id'] and entry['id'] in installed_bare)
        models.append(dict(entry, installed=is_installed, fit=fit(entry, mach), seed=True))

    seed_ids = {m['id'] for m in models}
    for item in installed:
        if item['id'] in seed_ids:
            continue
        entry = _entry_from_installed(item)
        models.append(dict(entry, installed=True, fit=fit(entry, mach), seed=False))

    return {
        'id': 'ollama',
        'label': provider_meta('ollama')['label'],
        'kind': 'local',
        'status': status,
        'status_text': status_text,
        'key_env': [],
        'models': models,
    }


# ------------------------------------------------------------------------- selection


def get_selection() -> dict:
    """The persisted ``{'provider', 'model'}``; the default when nothing is stored."""
    stored = _host.load_zero_config().get(SELECTION_KEY)
    if isinstance(stored, dict) and stored.get('provider') and stored.get('model'):
        return {'provider': str(stored['provider']), 'model': str(stored['model'])}
    return dict(DEFAULT_SELECTION)


def set_selection(provider: str, model: str, allow_custom: bool = False) -> dict:
    """Persist the chosen provider/model into ``data/agent_zero.json``.

    Every other key of the config file (the legacy ``llms`` map, role, goal, ...) is
    preserved; the write is atomic. Raises ``ValueError`` on an unusable choice.
    """
    if provider not in PROVIDERS:
        raise ValueError(f'unknown provider: {provider}')
    model = (model or '').strip()
    if not model:
        raise ValueError('model is required')

    if provider == 'ollama':
        installed, status = installed_ollama()
        if status != 'ready':
            raise ValueError(f'ollama not reachable at {_host.ollama_url()}')
        names = {item['id'] for item in installed} | {item['id'].split(':')[0] for item in installed}
        if model not in names and not allow_custom:
            raise ValueError(f'not installed: use install first ({model})')
    elif provider != 'subscription' and not allow_custom:
        known = {m['id'] for m in live_models(provider)[0]} | {m['id'] for m in seed_models(provider)}
        if model not in known:
            raise ValueError(f'unknown model for {provider}: {model}')
    elif provider == 'subscription':
        known = {m['id'] for m in seed_models('subscription')}
        if model not in known and not allow_custom:
            raise ValueError(f'unknown subscription model: {model}')

    cfg = _host.load_zero_config()
    cfg[SELECTION_KEY] = {'provider': provider, 'model': model, 'ts': time.time()}
    _host.save_zero_config(cfg)
    _log.info('agent_zero: model selection is now %s/%s', provider, model)
    return {'provider': provider, 'model': model}


# -------------------------------------------------------------------- install jobs


def start_install(model: str, confirm: bool = False) -> dict:
    """Start an Ollama pull in a daemon thread. ``{'job_id': ...}``.

    Refuses without an explicit confirmation, when another install is running, and
    when the model does not fit this machine.
    """
    model = (model or '').strip()
    if not model:
        raise ValueError('model is required')
    if confirm is not True:
        raise ValueError('confirmation required')

    with _jobs_lock:
        running = [j for j in _jobs.values() if j['status'] == 'running']
    if running:
        raise ValueError(f'another install is already running: {running[0]["model"]}')

    entry = next((e for e in seed_models('ollama') if e['id'] == model), None)
    if entry is not None:
        verdict = fit(entry, machine())
        if not verdict['ok']:
            raise ValueError('does not fit this machine: ' + '; '.join(verdict['reasons']))

    job_id = uuid.uuid4().hex[:12]
    job = {
        'job_id': job_id,
        'model': model,
        'status': 'running',
        'status_text': 'starting',
        'total': 0,
        'completed': 0,
        'pct': 0,
        'started': time.time(),
        'finished': None,
        'error': '',
    }
    with _jobs_lock:
        _jobs[job_id] = job
    _append_install_log({'ts': job['started'], 'model': model, 'status': 'start', 'seconds': 0, 'error': ''})

    thread = threading.Thread(target=_run_install, args=(job_id, model), name=f'zero-pull-{job_id}', daemon=True)
    thread.start()
    return {'job_id': job_id}


def install_status(job_id: str) -> dict | None:
    """A copy of one install job's progress dict, or ``None`` when unknown."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _run_install(job_id: str, model: str) -> None:
    """Stream ``POST /api/pull`` and keep the job dict up to date."""
    url = f'{_host.ollama_url()}/api/pull'
    try:
        resp = requests.post(url, json={'model': model, 'stream': True}, stream=True, timeout=(10, 600))
        resp.raise_for_status()
        for raw in resp.iter_lines():
            if not raw:
                continue
            try:
                line = json.loads(raw.decode('utf-8') if isinstance(raw, bytes) else raw)
            except Exception as exc:  # noqa: BLE001 - a non-JSON keepalive line
                _log.debug('agent_zero: skipping a non-JSON pull line (%s)', exc)
                continue
            if line.get('error'):
                raise RuntimeError(str(line['error']))
            _update_job(job_id, line)
        _finish_job(job_id, 'done', '')
    except Exception as exc:  # noqa: BLE001 - the job records the failure
        _log.warning('agent_zero: install of %s failed (%s)', model, exc)
        _finish_job(job_id, 'error', f'{exc.__class__.__name__}: {exc}')


def _update_job(job_id: str, line: dict) -> None:
    """Fold one progress line into the job: pct comes from the largest layer seen."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job['status_text'] = str(line.get('status') or job['status_text'])
        total = line.get('total')
        completed = line.get('completed')
        if isinstance(total, (int, float)) and total > 0:
            if total >= job['total']:
                job['total'] = int(total)
                job['completed'] = int(completed or 0)
            if job['total']:
                job['pct'] = max(0, min(100, int(job['completed'] * 100 / job['total'])))


def _finish_job(job_id: str, status: str, error: str) -> None:
    """Close a job: the log line is written *before* the job turns terminal.

    That order matters -- a caller that sees ``status != 'running'`` can rely on the
    install log already holding the matching line.
    """
    finished = time.time()
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        record = {
            'ts': finished,
            'model': job['model'],
            'status': status,
            'seconds': round(finished - job['started'], 1),
            'error': error,
        }
    _append_install_log(record)
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job['finished'] = finished
        job['error'] = error
        if status == 'done':
            job['pct'] = 100
            job['status_text'] = 'success'
            if job['total']:
                job['completed'] = job['total']
        else:
            job['status_text'] = error or 'error'
        job['status'] = status


def _append_install_log(record: dict) -> None:
    """One JSONL line per install start/finish, for the metrics panel."""
    try:
        path = os.path.join(_host.runtime_dir(), INSTALL_LOG_FILENAME)
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(record) + '\n')
    except Exception as exc:  # noqa: BLE001 - metrics must never break an install
        _log.warning('agent_zero: cannot append to the install log (%s)', exc)
