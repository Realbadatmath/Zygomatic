# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Azure cloud integrations — Blob Storage, Event Grid, Azure Functions.

All calls are:
  1. Guarded by azure_budget — auto-skipped when 95% of free tier is reached
  2. Fully async (fire-and-forget threads) — never block the pipeline
  3. Opt-in via config — if credentials are missing, silently no-op

Config is read from data/runtime/azure_config.json (managed by the dashboard
Settings → Security → Azure Cloud panel) with env var fallbacks.
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from urllib.parse import urlsplit

try:
    from zoneinfo import ZoneInfo

    _AMS_TZ = ZoneInfo('Europe/Amsterdam')
except Exception:
    _AMS_TZ = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def _ams_iso(timespec: str = 'milliseconds') -> str:
    if _AMS_TZ is not None:
        try:
            return datetime.now(_AMS_TZ).isoformat(timespec=timespec)
        except Exception as _exc:
            _zyg_log.debug('Amsterdam timezone unavailable, using UTC: %s', _exc)
    return datetime.now(timezone.utc).isoformat(timespec=timespec)


log = logging.getLogger('azure_integrations')

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'data', 'runtime', 'azure_config.json')


# ── Config helpers ────────────────────────────────────────────────────────────


def load_config() -> dict:
    """Load Azure config from azure_config.json. Env vars are fallbacks."""
    try:
        if os.path.exists(_CONFIG_PATH):
            with open(_CONFIG_PATH) as f:
                return json.load(f)
    except (OSError, ValueError) as _exc:
        _zyg_log.warning('azure config unreadable, continuing with defaults: %s', _exc)
    return {}


def save_config(data: dict) -> None:
    """Persist Azure config (called by the dashboard settings API)."""
    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    # Never log or store plaintext secrets in logs — only save to the JSON file
    with open(_CONFIG_PATH, 'w') as f:
        json.dump(data, f, indent=2)


def _cfg(key: str, env_var: str = '') -> str:
    cfg = load_config()
    return cfg.get(key) or (os.environ.get(env_var, '') if env_var else '')


def is_service_enabled(service: str) -> bool:
    """Check if a specific service is toggled on in the config."""
    cfg = load_config()
    return cfg.get(f'{service}_enabled', False)


# ── Blob Storage ──────────────────────────────────────────────────────────────


def upload_to_blob(job_id: str, file_paths: list) -> None:
    """
    Fire-and-forget: upload finished output files to Azure Blob Storage.
    Called after job completion — never blocks the pipeline.
    """
    if not is_service_enabled('blob'):
        return
    conn_str = _cfg('blob_connection_string', 'AZURE_STORAGE_CONNECTION_STRING')
    container = _cfg('blob_container') or 'zygomatic-outputs'
    if not conn_str:
        return  # not configured

    threading.Thread(
        target=_do_blob_upload,
        args=(job_id, file_paths, conn_str, container),
        daemon=True,
        name=f'az-blob-{job_id[:8]}',
    ).start()


def _do_blob_upload(job_id: str, file_paths: list, conn_str: str, container: str) -> None:
    from zyg_workflows.azure_budget import check_and_increment

    try:
        from azure.storage.blob import BlobServiceClient
    except ImportError:
        log.warning('[Azure] azure-storage-blob not installed. Run: pip install azure-storage-blob')
        return

    try:
        client = BlobServiceClient.from_connection_string(conn_str)
        cont_client = client.get_container_client(container)
        try:
            cont_client.create_container()
        except Exception as _exc:
            _zyg_log.debug('container already exists or could not be created here: %s', _exc)

        blob_urls = []
        for fp in file_paths:
            if not fp or not os.path.exists(fp):
                continue
            file_size = os.path.getsize(fp)

            if not check_and_increment('blob_uploads', 1):
                log.warning('[Azure] Blob upload skipped — monthly operations budget (95%) reached')
                break
            if not check_and_increment('blob_bytes', file_size):
                log.warning('[Azure] Blob upload skipped — monthly storage budget (95%) reached')
                break

            blob_name = f'{job_id}/{os.path.basename(fp)}'
            with open(fp, 'rb') as data:
                cont_client.upload_blob(blob_name, data, overwrite=True)

            url = f'https://{client.account_name}.blob.core.windows.net/{container}/{blob_name}'
            blob_urls.append(url)
            log.info(f'[Azure] Blob upload: {os.path.basename(fp)} → {url}')

        if blob_urls:
            _write_job_blob_urls(job_id, blob_urls)

    except Exception as e:
        log.warning(f'[Azure] Blob upload error for job {job_id[:8]}: {e}')


def _write_job_blob_urls(job_id: str, urls: list) -> None:
    """Persist blob URLs to a sidecar file for dashboard retrieval."""
    runtime_dir = os.path.join(os.path.dirname(__file__), 'data', 'runtime')
    state_path = os.path.join(runtime_dir, f'azure_job_{job_id}.json')
    try:
        with open(state_path, 'w') as f:
            json.dump(
                {
                    'job_id': job_id,
                    'blob_urls': urls,
                    'uploaded_at': _ams_iso(),
                },
                f,
                indent=2,
            )
    except (OSError, TypeError) as _exc:
        _zyg_log.warning('blob-url state write failed, the dashboard will not see these uploads: %s', _exc)


def get_job_blob_urls(job_id: str) -> list:
    """Return previously uploaded blob URLs for a job (used by dashboard)."""
    runtime_dir = os.path.join(os.path.dirname(__file__), 'data', 'runtime')
    state_path = os.path.join(runtime_dir, f'azure_job_{job_id}.json')
    try:
        with open(state_path) as f:
            return json.load(f).get('blob_urls', [])
    except Exception:
        return []


# ── Event Grid ────────────────────────────────────────────────────────────────


def publish_job_done_event(job_id: str, prompt: str, output_files: list) -> None:
    """
    Fire-and-forget: publish a PipelineJobCompleted event to Azure Event Grid.
    External subscribers (Azure Functions, Logic Apps, etc.) can react to this.
    """
    if not is_service_enabled('eventgrid'):
        return
    endpoint = _cfg('eventgrid_endpoint', 'AZURE_EVENT_GRID_ENDPOINT')
    key = _cfg('eventgrid_key', 'AZURE_EVENT_GRID_KEY')
    if not endpoint or not key:
        return  # not configured

    threading.Thread(
        target=_do_eventgrid_publish,
        args=(job_id, prompt, output_files, endpoint, key),
        daemon=True,
        name=f'az-eg-{job_id[:8]}',
    ).start()


def _do_eventgrid_publish(job_id: str, prompt: str, output_files: list, endpoint: str, key: str) -> None:
    from zyg_workflows.azure_budget import check_and_increment

    if not check_and_increment('eventgrid_events', 1):
        log.warning('[Azure] Event Grid publish skipped — monthly event budget (95%) reached')
        return

    try:
        from azure.eventgrid import EventGridPublisherClient, EventGridEvent
        from azure.core.credentials import AzureKeyCredential
    except ImportError:
        log.warning('[Azure] azure-eventgrid not installed. Run: pip install azure-eventgrid')
        return

    try:
        client = EventGridPublisherClient(endpoint, AzureKeyCredential(key))
        event = EventGridEvent(
            subject=f'pipeline/job/{job_id}',
            event_type='Zygomatic.Pipeline.JobCompleted',
            data={
                'job_id': job_id,
                'prompt': (prompt or '')[:200],
                'output_files': len(output_files),
                'completed_at': _ams_iso(),
            },
            data_version='1.0',
        )
        client.send([event])
        log.info(f'[Azure] Event Grid: published JobCompleted for job {job_id[:8]}')
    except Exception as e:
        log.warning(f'[Azure] Event Grid publish error for job {job_id[:8]}: {e}')


# ── Azure Function webhook forward ────────────────────────────────────────────


def forward_to_function(payload: dict) -> dict | None:
    """
    Synchronously forward a webhook payload to the configured Azure Function.
    Used when an external trigger comes in and should route into the pipeline.
    Returns the Function's JSON response, or None on error/not configured.
    """
    if not is_service_enabled('function'):
        return None
    func_url = _cfg('function_url', 'AZURE_FUNCTION_URL')
    func_key = _cfg('function_key', 'AZURE_FUNCTION_KEY')
    if not func_url:
        return None
    # AZURE_FUNCTION_URL comes from config or the environment: urlopen would follow a file:// or
    # custom scheme out of it, so the payload only ever leaves over http(s).
    if urlsplit(func_url).scheme not in ('http', 'https'):
        log.warning('[Azure] Function URL must be http(s), got %r', func_url[:80])
        return None

    from zyg_workflows.azure_budget import check_and_increment

    if not check_and_increment('function_calls', 1):
        log.warning('[Azure] Function call skipped — monthly call budget (95%) reached')
        return None

    try:
        import urllib.request

        headers = {'Content-Type': 'application/json'}
        if func_key:
            headers['x-functions-key'] = func_key
        req = urllib.request.Request(  # noqa: S310  func_url scheme checked before the budget call
            func_url,
            data=json.dumps(payload).encode(),
            headers=headers,
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310  # noqa: S310  req holds the checked URL
            return json.loads(resp.read())
    except Exception as e:
        log.warning(f'[Azure] Function forward error: {e}')
        return None
