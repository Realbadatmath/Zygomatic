# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""reading — a verbatim section of the pre-split run_logbook.py.

The module docstring that documented the whole layer lives in the package
__init__.py; nothing in this file was rewritten, renamed or retuned.
"""

from __future__ import annotations

import json  # noqa: F401
import logging as _zyg_logging  # noqa: F401
import os  # noqa: F401

from zyg_workflows.run_logbook.plumbing import (  # noqa: F401
    CHECKPOINT_NAME,
    CHECKPOINT_SCHEMA,
    INDEX_PATH,
    LOGBOOK_DIR,
    _atomic_write,
    _file_facts,
    _handle,
    _log_noop,
    _now,
    _read_json,
    _read_jsonl,
)
from zyg_workflows.run_logbook.recording import (  # noqa: F401
    _emit,
)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.run_logbook')


# ── checkpoints ──────────────────────────────────────────────────────────────


def checkpoint_path(run_dir) -> str:
    return os.path.join(os.path.abspath(str(run_dir)), CHECKPOINT_NAME)


def _load_checkpoints(run_dir, log_fn=None):
    """(manifest, source). Three fallbacks in order: CHECKPOINTS.json → its .bak →
    replay of the append-only jsonl. A single bad write can never lose the manifest."""
    p = checkpoint_path(run_dir)
    m = _read_json(p)
    if isinstance(m, dict) and isinstance(m.get('checkpoints'), list):
        return m, 'manifest'
    m = _read_json(p + '.bak')
    if isinstance(m, dict) and isinstance(m.get('checkpoints'), list):
        return m, 'manifest.bak'
    h = _handle(run_dir)
    recs, _bad = _read_jsonl(h['jsonl'])
    cps = [r['checkpoint'] for r in recs if r.get('event') == 'checkpoint' and r.get('checkpoint')]
    if cps:
        return {
            'schema': CHECKPOINT_SCHEMA,
            'run_dir': os.path.abspath(str(run_dir)),
            'run_key': h['run_key'],
            'checkpoints': cps,
            'rebuilt': True,
        }, 'jsonl-replay'
    return {
        'schema': CHECKPOINT_SCHEMA,
        'run_dir': os.path.abspath(str(run_dir)),
        'run_key': h['run_key'],
        'checkpoints': [],
    }, 'empty'


def record_checkpoint(run_dir, stage, artifact_path, meta=None, log_fn=None) -> dict:
    """Mark `stage` complete and `artifact_path` as its resumable output.

    Writes BOTH the append-only jsonl event and the CHECKPOINTS.json manifest (atomic).
    The artifact's size + sha256 are captured so resume_from() can tell a good artifact
    from one that a later crash left half-written. Returns the checkpoint record."""
    log = log_fn or _log_noop
    try:
        run_dir = os.path.abspath(str(run_dir))
        h = _handle(run_dir)
        ts, iso = _now()
        cp = {'stage': str(stage), 'ts': ts, 'ts_iso': iso, 'meta': meta or {}}
        cp.update({'artifact': str(artifact_path)})
        cp['file'] = _file_facts(artifact_path, log_fn=log)
        _emit(h, 'checkpoint', {'checkpoint': cp}, log_fn=log)
        man, _src = _load_checkpoints(run_dir, log_fn=log)
        man.update({'schema': CHECKPOINT_SCHEMA, 'run_dir': run_dir, 'run_key': h['run_key'], 'updated': iso})
        man.setdefault('checkpoints', [])
        man['checkpoints'] = [c for c in man['checkpoints'] if c.get('stage') != cp['stage']]
        man['checkpoints'].append(cp)
        man['last_good'] = cp
        _atomic_write(checkpoint_path(run_dir), json.dumps(man, indent=1, default=str), log_fn=log)
        log(f'[run_logbook] checkpoint {h["run_key"]}/{stage} -> {os.path.basename(str(artifact_path))}')
        return cp
    except Exception as e:
        log(f'[run_logbook] record_checkpoint failed (ignored): {e}')
        return {}


def resume_from(run_dir, verify_sha=True, log_fn=None) -> dict:
    """The last COMPLETED stage whose artifact is still good, so a failed run restarts
    from there instead of re-rendering 90 minutes of GPU.

    Walks the manifest newest-first and skips any checkpoint whose artifact has since
    vanished or changed size (half-written on a crash). verify_sha additionally re-hashes
    — cheap for a 20MB mp4 via the (size, mtime) cache, skip it for very large artifacts.

    Returns {'ok','stage','artifact','ts_iso','source','completed_stages','stale',...}.
    ok=False with 'reason' when there is nothing to resume from."""
    log = log_fn or _log_noop
    try:
        run_dir = os.path.abspath(str(run_dir))
        man, source = _load_checkpoints(run_dir, log_fn=log)
        cps = sorted(man.get('checkpoints') or [], key=lambda c: c.get('ts') or 0)
        if not cps:
            return {'ok': False, 'run_dir': run_dir, 'source': source, 'reason': 'no checkpoints recorded'}
        stale = []
        for cp in reversed(cps):
            art = cp.get('artifact')
            rec = cp.get('file') or {}
            now = _file_facts(art, want_sha=bool(verify_sha and rec.get('sha256')), log_fn=log)
            if not now.get('exists'):
                stale.append({'stage': cp.get('stage'), 'artifact': art, 'why': 'missing'})
                continue
            if rec.get('size') is not None and now.get('size') != rec.get('size'):
                stale.append(
                    {'stage': cp.get('stage'), 'artifact': art, 'why': f'size {rec.get("size")} -> {now.get("size")}'}
                )
                continue
            if verify_sha and rec.get('sha256') and now.get('sha256') and now['sha256'] != rec['sha256']:
                stale.append({'stage': cp.get('stage'), 'artifact': art, 'why': 'sha256 mismatch'})
                continue
            return {
                'ok': True,
                'run_dir': run_dir,
                'source': source,
                'stage': cp.get('stage'),
                'artifact': art,
                'ts_iso': cp.get('ts_iso'),
                'meta': cp.get('meta') or {},
                'file': now,
                'completed_stages': [c.get('stage') for c in cps],
                'resume_after': cp.get('stage'),
                'stale': list(reversed(stale)),
                'note': (
                    f'resume AFTER stage "{cp.get("stage")}"; {len(stale)} later checkpoint(s) discarded'
                    if stale
                    else f'resume AFTER stage "{cp.get("stage")}"'
                ),
            }
        return {
            'ok': False,
            'run_dir': run_dir,
            'source': source,
            'reason': 'every checkpointed artifact is missing or changed',
            'stale': list(reversed(stale)),
            'completed_stages': [c.get('stage') for c in cps],
        }
    except Exception as e:
        log(f'[run_logbook] resume_from failed (ignored): {e}')
        return {'ok': False, 'error': str(e)[:200]}


# ── reading a run back ───────────────────────────────────────────────────────


def load_run(run) -> dict:
    """Fold the append-only jsonl into one view: {'run_key','run_id','run_dir','version',
    'driver','config','stages','metrics','gates','verdict','checkpoints','finish',...}.

    Later records win for scalars; stages/metrics/checkpoints accumulate. This is the
    only reader — LOGBOOK.md, compare_runs and the CLI all go through it."""
    from zyg_workflows.run_logbook import compare as _compare  # function-local: compare loads after reading

    h = _handle(run)
    recs, bad = _read_jsonl(h['jsonl'])
    out = {
        'run_key': h['run_key'],
        'run_dir': h.get('run_dir'),
        'run_id': None,
        'version': None,
        'driver': {},
        'config': {},
        'stages': [],
        'metrics': {},
        'metric_sources': {},
        'gates': {},
        'verdict': {},
        'checkpoints': [],
        'finish': {},
        'started': None,
        'finished': None,
        'events': len(recs),
        'bad_lines': bad,
        'jsonl': h['jsonl'],
        'warnings': [],
        'ok': None,
    }
    for r in recs:
        ev = r.get('event')
        if r.get('run_dir') and not out['run_dir']:
            out['run_dir'] = r['run_dir']
        if ev == 'start':
            out['started'] = r.get('started') or r.get('ts_iso')
            out['recorded'] = r.get('ts_iso')
            out['run_id'] = r.get('run_id') or out['run_id']
            out['version'] = r.get('version') or out['version']
            out['driver'] = r.get('driver') or out['driver']
            out['warnings'] += list(r.get('warnings') or [])
        elif ev == 'config':
            cfg = r.get('config') or {}
            out['config'] = cfg
            out['version'] = cfg.get('version') or out['version']
            if cfg.get('driver'):
                out['driver'] = cfg['driver']
        elif ev == 'stage':
            out['stages'].append(
                {
                    'stage': r.get('stage'),
                    'ts_iso': r.get('at') or r.get('ts_iso'),
                    'wall_s': r.get('wall_s'),
                    'vram_mb': r.get('vram_mb'),
                    'status': r.get('status'),
                    'params': r.get('params') or {},
                }
            )
        elif ev == 'metrics':
            flat = _compare.flatten(r.get('metrics') or {})
            out['metrics'].update(flat)
            for k in flat:
                out['metric_sources'][k] = r.get('source') or ''
        elif ev == 'gates':
            out['gates'].update(r.get('gates') or {})
            if r.get('verdict'):
                out['verdict'] = r['verdict']
        elif ev == 'checkpoint':
            if r.get('checkpoint'):
                out['checkpoints'].append(r['checkpoint'])
        elif ev == 'finish':
            out['finished'] = r.get('finished') or r.get('ts_iso')
            out['finish'] = r
            out['ok'] = r.get('ok')
    return out


def list_runs(limit=200):
    """Newest-first index of every run in the logbook dir (not just finished ones —
    an interrupted run is exactly the one you go looking for)."""
    rows = {}
    try:
        for fn in os.listdir(LOGBOOK_DIR):
            if not fn.endswith('.jsonl') or fn == os.path.basename(INDEX_PATH):
                continue
            key = fn[:-6]
            try:
                v = load_run(key)
            except Exception as _exc:
                _zyg_log.warning('run %s could not be loaded, left out of the index: %s', key, _exc)
                continue
            n_fail = sum(1 for g in v['gates'].values() if not g.get('ok'))
            rows[key] = {
                'run_key': key,
                'run_id': v.get('run_id'),
                'run_dir': v.get('run_dir'),
                'version': v.get('version'),
                'started': v.get('started'),
                'finished': v.get('finished'),
                'ok': v.get('ok'),
                'stages': len(v['stages']),
                'gates': len(v['gates']),
                'gates_failed': n_fail,
                'metrics': len(v['metrics']),
                'checkpoints': len(v['checkpoints']),
                'warnings': len(v.get('warnings') or []),
                'final': (v.get('finish') or {}).get('final', {}).get('path'),
            }
    except FileNotFoundError:
        return []
    except Exception as _exc:
        _zyg_log.warning('logbook index scan incomplete, listing what was read: %s', _exc)
    return sorted(rows.values(), key=lambda r: r.get('finished') or r.get('started') or '', reverse=True)[:limit]
