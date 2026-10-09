# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The only seam between ``agent_zero`` and the live dashboard host (CONTRACT A).

Agent Zero v2 runs in two trees at once: here, where the host modules are packages
(``zyg_dashboard.*`` / ``zyg_workflows.*``), and in the pre-monorepo tree it was
written in, where the same modules are bare top-level names. Every name
``agent_zero`` borrows from the host therefore goes through this module and nowhere
else: no other file in the package may ``import crewai_web_gui`` (or quota_meter,
subscription_llm, llm_audit, bp_claude_clip) directly.

Everything here is lazy and forgiving. A missing host module is reported as ``None``
or a sane default with one logged warning -- importing ``agent_zero`` must never fail
because the dashboard is not importable, and must never pull the 2800-line Flask app
into the process as a side effect of an import.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from importlib import import_module
from typing import Any

_log = logging.getLogger(__name__)

# Host module candidates: the bare top-level name as the pre-monorepo tree has it,
# then the package-qualified name as this tree has it. First import that works wins.
_CANDIDATES = {
    'crewai_web_gui': ('crewai_web_gui', 'zyg_dashboard.crewai_web_gui'),
    'bp_claude_clip': ('bp_claude_clip', 'zyg_dashboard.bp_claude_clip'),
    'subscription_llm': ('subscription_llm', 'zyg_workflows.subscription_llm'),
    'quota_meter': ('quota_meter', 'zyg_dashboard.quota_meter'),
    'llm_audit': ('llm_audit', 'zyg_workflows.llm_audit'),
}

_modules: dict[str, Any] = {}
_warned: set[str] = set()


def _host_module(name: str):
    """Import a host module by its logical name, trying each candidate path.

    Returns ``None`` (warning logged once) when no candidate imports.
    """
    if name in _modules:
        return _modules[name]
    last_err: BaseException | None = None
    for dotted in _CANDIDATES.get(name, (name,)):
        try:
            mod = import_module(dotted)
        except Exception as exc:  # noqa: BLE001 - any import failure is a miss
            last_err = exc
            continue
        _modules[name] = mod
        return mod
    if name not in _warned:
        _warned.add(name)
        _log.warning('agent_zero: host module %s unavailable (%s)', name, last_err)
    _modules[name] = None
    return None


def app():
    """The live Flask application object, or ``None`` when the host is absent.

    Importing the host module is expensive (it starts the dashboard's watcher
    threads), so this is only ever called from request-time code paths.
    """
    mod = _host_module('crewai_web_gui')
    return getattr(mod, 'app', None) if mod is not None else None


def data_dir() -> str:
    """``crews/data`` -- the dashboard's canonical data directory."""
    mod = _modules.get('crewai_web_gui')
    if mod is not None:
        found = getattr(mod, 'DATA_DIR', None)
        if found:
            return str(found)
    # Derived without importing the host: agent_zero/ lives next to crewai_web_gui.py.
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')


def runtime_dir() -> str:
    """``crews/data/runtime`` -- created on demand."""
    path = os.path.join(data_dir(), 'runtime')
    os.makedirs(path, exist_ok=True)
    return path


def zero_config_path() -> str:
    """Path of Agent Zero's persisted configuration (``data/agent_zero.json``)."""
    return os.path.join(data_dir(), 'agent_zero.json')


def load_zero_config() -> dict:
    """Agent Zero's config as a dict; ``{}`` when the file is missing or broken."""
    path = zero_config_path()
    try:
        with open(path, encoding='utf-8') as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001 - a corrupt config must not crash a request
        _log.warning('agent_zero: cannot read %s (%s)', path, exc)
        return {}
    return cfg if isinstance(cfg, dict) else {}


def save_zero_config(cfg: dict) -> None:
    """Write Agent Zero's config atomically (tmp file in the same dir + os.replace)."""
    path = zero_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.agent_zero.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(cfg, fh, indent=2)
            fh.write('\n')
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def record_token_usage(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    stage: str = 'agent_zero_v2',
    pipeline_type: str = 'agent_zero',
) -> None:
    """Feed one turn's token usage into the dashboard's metrics store."""
    mod = _host_module('bp_claude_clip')
    fn = getattr(mod, '_record_token_usage', None) if mod is not None else None
    if fn is None:
        return
    try:
        fn(model, prompt_tokens, completion_tokens, stage=stage, pipeline_type=pipeline_type)
    except Exception as exc:  # noqa: BLE001 - metrics must never break a turn
        _log.warning('agent_zero: record_token_usage failed (%s)', exc)


def llm_audit():
    """The host's ``llm_audit`` module (``record``, ``ollama_post``) or ``None``."""
    return _host_module('llm_audit')


def quota_meter():
    """The host's ``quota_meter`` module (``price_tokens``, ``read_status``) or ``None``."""
    return _host_module('quota_meter')


def subscription_llm():
    """The host's ``subscription_llm`` module (``CLI_BIN``, ``_env``) or ``None``."""
    return _host_module('subscription_llm')


def ollama_url() -> str:
    """Base URL of the local Ollama server, without a trailing slash."""
    return os.environ.get('OLLAMA_HOST', 'http://localhost:11434').rstrip('/')


def claude_login_present() -> bool:
    """True when ``~/.claude/.credentials.json`` holds a Claude Code OAuth token."""
    mod = _host_module('subscription_llm')
    fn = getattr(mod, 'login_present', None) if mod is not None else None
    if fn is not None:
        try:
            return bool(fn())
        except Exception as exc:  # noqa: BLE001 - fall through to the file check
            _log.warning('agent_zero: subscription_llm.login_present failed (%s)', exc)
    path = os.path.expanduser('~/.claude/.credentials.json')
    try:
        with open(path, encoding='utf-8') as fh:
            creds = json.load(fh)
    except Exception:  # noqa: BLE001 - no file, no login
        return False
    oauth = creds.get('claudeAiOauth') if isinstance(creds, dict) else None
    return bool(isinstance(oauth, dict) and oauth.get('accessToken'))


def claude_cli_bin() -> str:
    """Path of the ``claude`` CLI used by the subscription backend."""
    mod = _host_module('subscription_llm')
    found = getattr(mod, 'CLI_BIN', None) if mod is not None else None
    if found:
        return str(found)
    return shutil.which('claude') or '/usr/local/bin/claude'


def user_name() -> str:
    """The logged-in operator's display name; ``'User'`` outside a request."""
    try:
        from flask import session
    except Exception:  # noqa: BLE001 - flask is optional at import time
        return 'User'
    try:
        return str(session.get('user_name') or session.get('user_id') or 'User')
    except Exception:  # noqa: BLE001 - no request context
        return 'User'
