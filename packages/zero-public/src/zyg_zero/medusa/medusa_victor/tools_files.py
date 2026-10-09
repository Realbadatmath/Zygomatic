# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""medusa_victor.tools_files — the read/write/edit/list/search/bash tools.

Lines 391-516 of the original medusa_victor.py, moved verbatim
(2026-10-06 split). No logic changed.
"""

from __future__ import annotations

import fnmatch
import logging as _zyg_logging
import os
import re
import subprocess

from .constants import BASH_MAX, BASH_TIMEOUT, GLOB_MAX_HITS, GREP_MAX_HITS, READ_MAX, ROOT

from .backends import _clip, _rel, _safe_path

# Bound by assignment (never `from . import`), to __package__ — which IS the
# old module's own __name__, whichever route it is imported by. The logger a
# moved line writes to must not be renamed by the move.
_zyg_log = _zyg_logging.getLogger(__package__)


# ── tools ────────────────────────────────────────────────────────────────────
# Each entry: name -> (json schema for the model, python implementation).
# The implementations return anything JSON-serialisable; the loop stringifies.


def _t_read_file(path: str, offset: int = 0, limit: int = 0) -> dict:
    p = _safe_path(path, must_exist=True)
    if os.path.isdir(p):
        return {'error': f'{_rel(p)} is a directory — use list_files'}
    with open(p, encoding='utf-8', errors='replace') as fh:
        lines = fh.readlines()
    off = max(0, int(offset or 0))
    end = off + int(limit) if limit else len(lines)
    body = ''.join(f'{i + 1}\t{ln}' for i, ln in enumerate(lines[off:end], start=off))
    return {
        'path': _rel(p),
        'lines': len(lines),
        'shown': f'{off + 1}-{min(end, len(lines))}',
        'content': _clip(body, READ_MAX),
    }


def _t_write_file(path: str, content: str) -> dict:
    p = _safe_path(path)
    existed = os.path.exists(p)
    os.makedirs(os.path.dirname(p) or ROOT, exist_ok=True)
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(content or '')
    return {
        'ok': True,
        'path': _rel(p),
        'bytes': len(content or ''),
        'note': 'overwrote an existing file' if existed else 'created a new file',
    }


def _t_edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False) -> dict:
    p = _safe_path(path, must_exist=True)
    with open(p, encoding='utf-8') as fh:
        src = fh.read()
    n = src.count(old_text)
    if n == 0:
        return {
            'ok': False,
            'error': 'old_text does not appear in the file — read it first '
            'and copy the exact text, whitespace included',
        }
    if n > 1 and not replace_all:
        return {
            'ok': False,
            'error': f'old_text appears {n} times — include more surrounding '
            'lines to make it unique, or pass replace_all',
        }
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(src.replace(old_text, new_text) if replace_all else src.replace(old_text, new_text, 1))
    return {'ok': True, 'path': _rel(p), 'replaced': n if replace_all else 1}


def _t_list_files(pattern: str = '*', path: str = '.') -> dict:
    base = _safe_path(path or '.')
    hits: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in ('__pycache__', '.git', 'node_modules')]
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, base)
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(name, pattern):
                hits.append(_rel(full))
                if len(hits) >= GLOB_MAX_HITS:
                    return {'files': sorted(hits), 'truncated': True}
    return {'files': sorted(hits), 'count': len(hits)}


def _t_search_files(pattern: str, path: str = '.', glob: str = '*') -> dict:
    base = _safe_path(path or '.')
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return {'error': f'bad regular expression: {e}'}
    hits: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in ('__pycache__', '.git', 'node_modules')]
        for name in filenames:
            if not fnmatch.fnmatch(name, glob):
                continue
            full = os.path.join(dirpath, name)
            try:
                with open(full, encoding='utf-8', errors='replace') as fh:
                    for i, line in enumerate(fh, 1):
                        if rx.search(line):
                            hits.append({'file': _rel(full), 'line': i, 'text': line.rstrip()[:300]})
                            if len(hits) >= GREP_MAX_HITS:
                                return {'matches': hits, 'truncated': True}
            except OSError as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
                continue
    return {'matches': hits, 'count': len(hits)}


def _t_run_bash(command: str, timeout: int = 0) -> dict:
    """Runs with cwd pinned to Medusa's folder. NOTE the fence does not reach
    here — a shell command can name any path on the machine. That is the same
    accepted gap Vicky has (Claude Code has no per-directory Bash rule either);
    it is documented rather than pretended away.

    The interpreter is named explicitly in the argument list instead of through ``shell=True``
    so that no part of this depends on the parent process's ``SHELL``/``COMSPEC``: the command
    string is a bash script by contract (the tool schema says so) and nothing else parses it.
    """
    try:
        r = subprocess.run(
            ['/bin/bash', '-c', command],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=min(int(timeout) or BASH_TIMEOUT, 600),
            errors='replace',
        )
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': f'timed out after {timeout or BASH_TIMEOUT}s'}
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'error': str(e)[:500]}
    out = (r.stdout or '') + (('\n[stderr]\n' + r.stderr) if r.stderr else '')
    return {'ok': r.returncode == 0, 'exit_code': r.returncode, 'output': _clip(out.strip(), BASH_MAX)}
