# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""medusa_victor.backends — HTTP to Ollama, the path fence, the crews/stills helpers and the turn image record.

Lines 201-390 of the original medusa_victor.py, moved verbatim
(2026-10-06 split). No logic changed.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request

from .constants import (
    CREWS_API,
    CREWS_TIMEOUT,
    DEFAULT_BRAIN,
    FENCE,
    OLLAMA_URL,
    ROOT,
    STILLS_API,
    STILLS_TIMEOUT,
    TOOL_RESULT_MAX,
    brain,
)


def _urlopen_http(url: str, timeout: float, data=None, headers=None, method=None):
    """Open *url*, refusing every scheme but http/https.

    ``ZYG_VICTOR_OLLAMA`` and ``MEDUSA_CREWS_API`` are configuration, so without this check
    a deployment could point these calls at ``file://`` and have Victor read local files.
    This is the audit :func:`zyg_workflows.net.safe_urlopen` performs; that function cannot
    be used directly because the call sites below need headers and a method, so this is the
    single reviewed URL open of the module.
    """
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in ('http', 'https'):
        raise ValueError(f'refusing to open {scheme or "scheme-less"} URL: {url}')
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)  # noqa: S310  checked above
    return urllib.request.urlopen(req, timeout=timeout)  # nosec B310  # noqa: S310  scheme checked above


def available() -> bool:
    """Is Ollama up? A GET, never a generate — the same rule VICKY_RULES.md sets
    for Vicky's own health check (never start a real job to test the service)."""
    try:
        with _urlopen_http(OLLAMA_URL + '/api/tags', 3):
            return True
    except Exception:  # noqa: BLE001
        return False


def models() -> list[str]:
    try:
        with _urlopen_http(OLLAMA_URL + '/api/tags', 5) as r:
            return [str(m.get('name') or '') for m in (json.load(r).get('models') or [])]
    except Exception:  # noqa: BLE001
        return []


def resolve_model(which=None) -> str:
    """The model this turn will actually run on. The brain's own model when it
    exists, its base otherwise — reported to the panel so the operator is never
    told a name that is not what answered."""
    b = brain(which)
    have = models()
    for want in (b['model'], b['model'] + ':latest', b['fallback'], b['fallback'] + ':latest'):
        if want in have:
            return want
    return b['model']


def info(which=None) -> dict:
    b = brain(which)
    up = available()
    got = resolve_model(which) if up else b['model']
    return {
        'engine': 'ollama',
        'brain': which or DEFAULT_BRAIN,
        'name': b['persona'],
        'url': OLLAMA_URL,
        'model': got,
        # `available` is not just "is Ollama up" — a brain whose model was
        # never built would answer as its fallback, which is a different
        # assistant wearing the name. The panel has to be able to say so.
        'built': up and got.split(':')[0] == b['model'].split(':')[0],
        'wanted': b['model'],
        'build': b['build'],
        'available': up,
        'models': models() if up else [],
    }


# ── the fence ────────────────────────────────────────────────────────────────
def _safe_path(path: str, must_exist: bool = False) -> str:
    """Resolve a path from the model, and enforce the fence only if it is on.

    OFF BY DEFAULT since 2026-09-17, at the operator's explicit instruction: this
    is a single-user box and the assistant is meant to reach the whole of it, the
    way the Claude-CLI half always effectively could. Set ZYG_VICKY_FENCE=on to
    put it back — the check is kept rather than deleted precisely so that is one
    env var and not a rewrite.

    What turning it off actually costs, stated plainly because the docstring is
    where the next reader will look: with the fence down these tools can
    overwrite or delete anything the `zygomatic` user owns — Medusa's own source,
    the chat store under data/runtime/vicky, the model files under ~/models. The
    fence was never the real boundary anyway (run_bash always took an arbitrary
    shell command and could name any path), so what changed here is the honesty
    of the arrangement more than its blast radius.

    Path arguments arrive from a language model either way, so they are still
    resolved before use: realpath collapses `..` and follows symlinks, which is
    what makes the fence meaningful when it IS on, and what keeps the returned
    path canonical when it is off.
    """
    p = os.path.realpath(path if os.path.isabs(path) else os.path.join(ROOT, path))
    if FENCE and p != ROOT and not p.startswith(ROOT + os.sep):
        raise PermissionError(
            f"{path!r} is outside Medusa's folder ({ROOT}) and ZYG_VICKY_FENCE is on. "
            'Unset it to let this assistant reach the rest of the machine.'
        )
    if must_exist and not os.path.exists(p):
        raise FileNotFoundError(f'no such file: {path}')
    return p


def _rel(p: str) -> str:
    """How a path is named back to the model and the operator. Relative inside
    Medusa, absolute outside it — with the fence off, relpath would otherwise
    answer a question about a sibling directory of the home directory with
    '../../<name>', which reads as a traversal attempt rather than as the plain
    fact of where the file is."""
    if p == ROOT or p.startswith(ROOT + os.sep):
        return os.path.relpath(p, ROOT)
    return p


def _clip(text: str, limit: int) -> str:
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + f'\n\n[... clipped, {len(text) - limit} more characters]'


# ── crews API helper (image + video generation live behind this) ─────────────
def _http_json(base: str, method: str, path: str, body=None, timeout: int | None = None) -> dict:
    """One JSON call to one of the render services. Always returns a dict the
    model can read — an HTTP error is DATA here, not an exception, because "that
    endpoint said 409 pipeline_busy" is a fact Victor has to act on, not a
    crash."""
    if not path.startswith('/'):
        path = '/' + path
    url = base + path
    data = json.dumps(body).encode('utf-8') if body is not None else None
    headers = {'Content-Type': 'application/json'} if data is not None else {}
    try:
        with _urlopen_http(url, timeout or CREWS_TIMEOUT, data=data, headers=headers, method=method.upper()) as r:
            raw = r.read().decode('utf-8', 'replace')
            try:
                return {'ok': True, 'status': r.status, 'data': json.loads(raw)}
            except ValueError:
                return {'ok': True, 'status': r.status, 'text': raw[:TOOL_RESULT_MAX]}
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', 'replace')
        try:
            return {'ok': False, 'status': e.code, 'error': json.loads(raw)}
        except ValueError:
            return {'ok': False, 'status': e.code, 'error': raw[:4000]}
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'error': f'could not reach {base}: {e}'}


def _crews(method: str, path: str, body=None, timeout: int | None = None) -> dict:
    out = _http_json(CREWS_API, method, path, body, timeout or CREWS_TIMEOUT)
    if not out.get('ok') and 'could not reach' in str(out.get('error') or ''):
        out['error'] = f'{out["error"]} (is the :5000 workflows server up?)'
    return out


def _stills(method: str, path: str, body=None, timeout: int | None = None) -> dict:
    out = _http_json(STILLS_API, method, path, body, timeout or STILLS_TIMEOUT)
    if not out.get('ok') and 'could not reach' in str(out.get('error') or ''):
        out['error'] = f'{out["error"]} (is the :8899 board server up?)'
    return out


# ── the picture a chat asks for, delivered back into the chat ────────────────
# A tool that produces a file has to hand the file to the panel itself. Leaving
# it to the model to mention a path means the operator gets a sentence about a
# picture instead of the picture, and gets nothing at all when the model forgets.
# So the turn collects them: run_turn parks the live job here, the tool appends
# what it actually rendered, and medusa_vicky writes that list onto the chat
# message. Nothing in this path comes from the model's own words.
_TURN = threading.local()


def _turn_job() -> dict | None:
    return getattr(_TURN, 'job', None)


def _record_image(path: str, name: str = '', prompt: str = '') -> None:
    job = _turn_job()
    if not job or not path:
        return
    imgs = job.setdefault('images', [])
    if any(i.get('path') == path for i in imgs):
        return
    rec = {'path': path, 'name': name or os.path.basename(path)}
    # The prompt the tool was called with — _history_messages replays it as the
    # tool call that made this picture. See there for why that matters.
    if prompt:
        rec['prompt'] = prompt
    imgs.append(rec)
