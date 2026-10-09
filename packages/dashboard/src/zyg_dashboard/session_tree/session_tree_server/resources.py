# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GPU/RAM probing, slots, the admission decision and the wait queue.

Moved verbatim from session_tree_server.py lines 486-612.
"""

from ._base import _zyg_log, os, shutil, subprocess
from .storage import CFG, list_trees, now


# ───────────────────────────── resources ─────────────────────────────────────

_res_cache = {'at': 0, 'val': None}


def resources():
    if now() - _res_cache['at'] < 2 and _res_cache['val']:
        return _res_cache['val']
    out = {'gpu': None, 'ram_avail_gb': None, 'ram_total_gb': None}
    try:
        # Absolute program path, never a bare name off PATH. Resolved here rather than with
        # zyg_workflows.bin.exe because this server is stdlib-only on purpose (it runs under
        # /usr/bin/python3, outside the venv) — same ZYG_BIN_NVIDIA_SMI override, same
        # PATH-then-fallback order. A missing binary still lands in the `except` below.
        smi = os.environ.get('ZYG_BIN_NVIDIA_SMI') or shutil.which('nvidia-smi') or 'nvidia-smi'
        q = subprocess.run(
            [
                smi,
                '--query-gpu=name,memory.used,memory.total,utilization.gpu',
                '--format=csv,noheader,nounits',
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        line = q.stdout.strip().splitlines()[0]
        name, used, total, util = [x.strip() for x in line.split(',')]
        out['gpu'] = {
            'name': name,
            'vram_used_gb': round(int(used) / 1024, 1),
            'vram_total_gb': round(int(total) / 1024, 1),
            'vram_free_gb': round((int(total) - int(used)) / 1024, 1),
            'util_pct': int(util),
        }
    except Exception as e:
        out['gpu'] = {'error': str(e)[:120]}
    try:
        info = {}
        with open('/proc/meminfo') as f:
            for ln in f:
                k, v = ln.split(':', 1)
                info[k] = int(v.strip().split()[0])
        out['ram_avail_gb'] = round(info['MemAvailable'] / 1024 / 1024, 1)
        out['ram_total_gb'] = round(info['MemTotal'] / 1024 / 1024, 1)
    except (OSError, ValueError, KeyError) as _exc:
        _zyg_log.debug('ram sample unavailable, reporting without it: %s', _exc)
    _res_cache.update(at=now(), val=out)
    return out


def executing_tasks():
    """All executing tasks with a live lease, across active trees."""
    out = []
    for t in list_trees():
        for task in t['tasks']:
            if task['status'] == 'executing':
                out.append((t, task))
    return out


def queue_state():
    ex = executing_tasks()
    t = now()
    heavy = [x for _, x in ex if x['weight'] == 'heavy' and x['lease_until'] > t]
    light = [x for _, x in ex if x['weight'] == 'light' and x['lease_until'] > t]
    return {
        'heavy_used': len(heavy),
        'heavy_slots': CFG['heavy_slots'],
        'light_used': len(light),
        'light_slots': CFG['light_slots'],
    }


def wait_queue(weight=None):
    """Queued reservations — claimed, waiting for a slot — FIFO across trees."""
    out = []
    for t in list_trees():
        for task in t['tasks']:
            if task['status'] == 'queued' and (weight is None or task['weight'] == weight):
                out.append((t, task))
    out.sort(key=lambda p: (p[1].get('queued_at') or 0, p[0]['id'], p[1]['id']))
    return out


def queue_position(tree_id, task):
    for i, (t, x) in enumerate(wait_queue(task['weight'])):
        if t['id'] == tree_id and x['id'] == task['id']:
            return i + 1
    return None


def admission(task):
    """Return None if the task may start now, else (reason, retry_after_s)."""
    qs = queue_state()
    res = resources()
    if task['weight'] == 'heavy':
        if qs['heavy_used'] >= qs['heavy_slots']:
            return ('heavy queue full: %d/%d heavy task(s) executing' % (qs['heavy_used'], qs['heavy_slots']), 120)
        gpu = res.get('gpu') or {}
        if 'vram_free_gb' in gpu:
            need = float(task.get('vram_gb', 8)) + CFG['vram_reserve_gb']
            if gpu['vram_free_gb'] < need:
                return (
                    'VRAM: %.1f GB free, task needs %.1f GB (+%.1f reserve) — something else '
                    'is on the GPU' % (gpu['vram_free_gb'], task.get('vram_gb', 8), CFG['vram_reserve_gb']),
                    180,
                )
            if gpu.get('util_pct', 0) >= CFG['gpu_busy_util_pct']:
                return (
                    'GPU busy: %d%% utilisation (limit %d%%) — a pipeline is rendering; '
                    'take a light task or wait' % (gpu['util_pct'], CFG['gpu_busy_util_pct']),
                    180,
                )
    else:
        if qs['light_used'] >= qs['light_slots']:
            return ('light queue full: %d/%d light task(s) executing' % (qs['light_used'], qs['light_slots']), 60)
    if res.get('ram_avail_gb') is not None:
        need = float(task.get('ram_gb', 4)) + CFG['ram_reserve_gb']
        if res['ram_avail_gb'] < need:
            return (
                'RAM: %.1f GB available, task needs %.1f GB (+%.1f reserve)'
                % (res['ram_avail_gb'], task.get('ram_gb', 4), CFG['ram_reserve_gb']),
                120,
            )
    return None
