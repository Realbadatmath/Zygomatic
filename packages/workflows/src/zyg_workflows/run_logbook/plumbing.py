# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401
# F401: this module inherited the original top import block of run_logbook.py. Every name
# in it is re-exported by the package __init__ and imported by the sibling
# sections, so nothing here may be pruned as unused.
"""plumbing — a verbatim section of the pre-split run_logbook.py.

The module docstring that documented the whole layer lives in the package
__init__.py; nothing in this file was rewritten, renamed or retuned.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import logging as _zyg_logging

from zyg_workflows import paths

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.run_logbook')


_CREWS = str(paths.PKG_DIR)
_RUNTIME = str(paths.DATA_DIR / 'runtime')
LOGBOOK_DIR = os.environ.get('ZYG_LOGBOOK_DIR') or os.path.join(_RUNTIME, 'logbook')
INDEX_PATH = os.path.join(LOGBOOK_DIR, 'index.jsonl')

SCHEMA = 'zyg.logbook/1'
CHECKPOINT_SCHEMA = 'zyg.checkpoints/1'
CHECKPOINT_NAME = 'CHECKPOINTS.json'
LOGBOOK_NAME = 'LOGBOOK.md'

# 2026-07-31 proven-win constant (V7): per-beat prompt clipping at 1500 chars.  A beat
# over this is silently truncated by the encoder, i.e. the tail of the beat never renders.
BEAT_CHAR_LIMIT = int(os.environ.get('ZYG_BEAT_CHAR_LIMIT') or 1500)

# Every ZYG_* the wan/VACE render path actually READS.  Listed explicitly so an UNSET
# but read variable is recorded as null rather than being invisible — "the flag that
# wasn't there" is exactly as load-bearing as the flag that was (v11 pinned
# ZYG_VACE_DIFFDIFF=0 on purpose; a run that simply never set it is NOT the same run).
KNOWN_ZYG_KEYS = (
    'ZYG_VACE_DIFFDIFF',
    'ZYG_VACE_DIFFDIFF_LEVEL',
    'ZYG_VACE_DIFFDIFF_KEEP',
    'ZYG_VACE_MASK_SEQ',
    'ZYG_NEG_ALLOW_FACE_MOTION',
    'ZYG_WAN_BEAT_CHARS',
    'ZYG_WAN_WIDTH',
    'ZYG_WAN_HEIGHT',
    'ZYG_WAN_T2V_MODEL',
    'ZYG_WAN_VACE_MODULE',
    'ZYG_WAN_TIMEOUT_S',
    'ZYG_BEAT_MAP_GATE',
    'ZYG_MASK_GATE',
    'ZYG_MASK_MAX_WHITE',
    'ZYG_LORA_ATTEST',
    'ZYG_INK_SAM2',
    'ZYG_INK_AUTO_BLUR',
    'ZYG_MANIFEST_SHA256',
    'ZYG_MANIFEST_SHA256_MAX_MB',
    'ZYG_COMFY_HOST',
    'ZYG_COMFY_PORT',
    'ZYG_COMFY_SERVER',
    'ZYG_RUN_ID',
    # 2026-08-09 stack upgrade: attention backend + Wan2.2/Lightning gates
    'ZYG_WAN_ATTENTION',
    'ZYG_WAN22',
    'ZYG_WAN_LIGHTNING',
    'ZYG_WAN_MODEL',
)


def _log_noop(_m):
    pass


def _now():
    t = time.time()
    return t, time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t))


# ── plumbing: atomic + append-only ───────────────────────────────────────────


def _safe_key(s) -> str:
    """Filesystem-safe run key. Anything exotic collapses to '_' so the key can be a
    filename, a CLI argument and a dict key without quoting rules differing."""
    out = []
    for ch in str(s or 'run'):
        out.append(ch if (ch.isalnum() or ch in '-_.') else '_')
    return (''.join(out) or 'run')[:120]


def _atomic_write(path, text, log_fn=None) -> bool:
    """tmp + fsync + os.replace, keeping one .bak. Crash-mid-write leaves the OLD file
    whole (os.replace is atomic on POSIX); the .bak covers a crash between replace and
    the next write's flush. Never raises."""
    log = log_fn or _log_noop
    tmp = None
    try:
        path = os.path.abspath(path)
        d = os.path.dirname(path) or '.'
        os.makedirs(d, exist_ok=True)
        tmp = os.path.join(d, '.%s.tmp.%d' % (os.path.basename(path), os.getpid()))
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(path):
            try:
                shutil.copy2(path, path + '.bak')
            except OSError as _exc:
                _zyg_log.warning('backup of %s before the atomic write failed: %s', path, _exc)
        os.replace(tmp, path)
        tmp = None
        return True
    except Exception as e:
        log(f'[run_logbook] atomic write {path} failed (ignored): {e}')
        return False
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError as _exc:
                _zyg_log.debug('temp file %s cleanup skipped: %s', tmp, _exc)


def _append_jsonl(path, obj, log_fn=None) -> bool:
    """Append one JSON record. If the previous append was torn by a crash (no trailing
    newline) a newline is written FIRST, so the damage stays confined to that one line
    instead of fusing two records into an unparsable third. Never raises."""
    log = log_fn or _log_noop
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
        need_nl = False
        try:
            if os.path.getsize(path) > 0:
                with open(path, 'rb') as f:
                    f.seek(-1, os.SEEK_END)
                    need_nl = f.read(1) != b'\n'
        except (OSError, ValueError):
            need_nl = False
        line = json.dumps(obj, default=str, ensure_ascii=False)
        with open(path, 'a', encoding='utf-8') as f:
            if need_nl:
                f.write('\n')
            f.write(line + '\n')
            f.flush()
            os.fsync(f.fileno())
        return True
    except Exception as e:
        log(f'[run_logbook] append {path} failed (ignored): {e}')
        return False


def _read_jsonl(path):
    """(records, n_bad). Unparsable lines are SKIPPED and counted — a torn tail must
    never make the whole logbook unreadable."""
    recs, bad = [], 0
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                    if isinstance(o, dict):
                        recs.append(o)
                    else:
                        bad += 1
                except Exception:
                    bad += 1
    except FileNotFoundError:
        return [], 0
    except Exception:
        return recs, bad + 1
    return recs, bad


def _read_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _sha256(path, log_fn=None):
    """Reuse run_ledger's (size, mtime_ns)-cached hasher so a repeated checkpoint on an
    unchanged artifact is a stat(). Falls back to a local hash if run_ledger is absent."""
    try:
        from zyg_workflows import run_ledger

        return run_ledger.sha256_file(path, log_fn=log_fn)
    except Exception as _exc:
        _zyg_log.debug('ledger sha256 unavailable, hashing locally: %s', _exc)
    try:
        import hashlib

        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(4 * 1024 * 1024), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _file_facts(path, want_sha=True, log_fn=None):
    """{'path','exists','size','mtime_iso','sha256'} — or exists=False. Directories get a
    file count + total size instead of a digest (a mask_seq dir is a legitimate artifact)."""
    rec = {'path': str(path), 'exists': False}
    try:
        p = os.path.abspath(str(path))
        rec['abs'] = p
        if os.path.isdir(p):
            n, total = 0, 0
            for root, _dirs, files in os.walk(p):
                for fn in files:
                    try:
                        total += os.path.getsize(os.path.join(root, fn))
                        n += 1
                    except OSError as _exc:
                        _zyg_log.debug('size of %s unavailable, not counted: %s', fn, _exc)
            rec.update(
                {
                    'exists': True,
                    'kind': 'dir',
                    'n_files': n,
                    'size': total,
                    'mtime_iso': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(p))),
                }
            )
            return rec
        st = os.stat(p)
        rec.update(
            {
                'exists': True,
                'kind': 'file',
                'size': st.st_size,
                'mtime_iso': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime)),
            }
        )
        if want_sha:
            rec['sha256'] = _sha256(p, log_fn=log_fn)
    except Exception as e:
        rec['error'] = str(e)[:160]
    return rec


# ── run identity ─────────────────────────────────────────────────────────────


def jsonl_path(run_key) -> str:
    return os.path.join(LOGBOOK_DIR, _safe_key(run_key) + '.jsonl')


def _handle(run):
    """Accept a handle dict, a run_key, or a run_dir path. One resolver so no caller
    has to care which of the three it is holding."""
    if isinstance(run, dict) and run.get('run_key'):
        return run
    s = str(run)
    if os.path.isdir(s):
        key = _safe_key(os.path.basename(os.path.abspath(s)))
        return {'run_key': key, 'run_dir': os.path.abspath(s), 'jsonl': jsonl_path(key)}
    key = _safe_key(s)
    h = {'run_key': key, 'run_dir': None, 'jsonl': jsonl_path(key)}
    recs, _ = _read_jsonl(h['jsonl'])
    for r in recs:
        if r.get('run_dir'):
            h['run_dir'] = r['run_dir']
            break
    return h


def resolve_run(ref):
    """Resolve a user-supplied run reference to a handle: exact key → run_dir path →
    run_id recorded in some logbook → basename match. Returns None when nothing matches."""
    from zyg_workflows.run_logbook import reading as _reading  # function-local: reading loads after plumbing

    if not ref:
        return None
    s = str(ref)
    cand = jsonl_path(s)
    if os.path.exists(cand):
        return _handle(s)
    if os.path.isdir(s):
        h = _handle(s)
        if os.path.exists(h['jsonl']):
            return h
    base = _safe_key(os.path.basename(s.rstrip('/')))
    if os.path.exists(jsonl_path(base)):
        return _handle(base)
    for row in _reading.list_runs():
        if s in (row.get('run_key'), row.get('run_id'), row.get('run_dir')):
            return _handle(row['run_key'])
    return None
