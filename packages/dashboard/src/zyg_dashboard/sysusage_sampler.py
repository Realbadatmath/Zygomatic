#!/usr/bin/python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sysusage_sampler.py — one JSON line per minute of machine utilisation. 2026-09-18.

Why: the Analytics tab answers "how much of the system are we using per day / week /
month". Until now the only utilisation history was telemetry_<pipeline>.csv, written
by the GUI sampler ONLY while a clipfarm / crime / scholarly pipeline was running
(last file 2026-08-25) — a record of busy moments, not of the day. This service runs
under systemd --user (zyg-sysusage.service, Restart=always), samples every
SAMPLE_S seconds and appends the minute's mean to data/runtime/system_usage.jsonl:

  {"ts": 1789740000, "gpu_util": 37.2, "vram_pct": 61.0, "gpu_power_w": 210.4,
   "gpu_temp_c": 58, "cpu_pct": 12.5, "ram_pct": 22.1, "n": 4}

Stdlib + pynvml/psutil (both on /usr/bin/python3). nvidia-smi is the fallback when
pynvml is unavailable. Nothing here reads the GUI; the collector (analytics_hub.py)
aggregates the file per day, incrementally, by byte offset.
"""

import json
import logging as _zyg_logging
import os
import sys
import time

_zyg_log = _zyg_logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get('ZYG_SYSUSAGE_LOG') or os.path.join(HERE, 'data', 'runtime', 'system_usage.jsonl')
SAMPLE_S = float(os.environ.get('ZYG_SYSUSAGE_SAMPLE_S', '15'))
FLUSH_S = 60.0

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None


_nv = None
_handle = None


def _gpu_pynvml():
    global _nv, _handle
    if _nv is None:
        import pynvml

        pynvml.nvmlInit()
        _nv = pynvml
        _handle = pynvml.nvmlDeviceGetHandleByIndex(0)
    u = _nv.nvmlDeviceGetUtilizationRates(_handle)
    m = _nv.nvmlDeviceGetMemoryInfo(_handle)
    try:
        p = _nv.nvmlDeviceGetPowerUsage(_handle) / 1000.0
    except Exception:
        p = None
    try:
        t = _nv.nvmlDeviceGetTemperature(_handle, _nv.NVML_TEMPERATURE_GPU)
    except Exception:
        t = None
    return {
        'gpu_util': float(u.gpu),
        'vram_pct': m.used / m.total * 100.0 if m.total else None,
        'gpu_power_w': p,
        'gpu_temp_c': t,
    }


def _gpu_smi():
    import subprocess

    # Imported here, not at module scope: this sampler's import must stay stdlib-only so
    # the `#!/usr/bin/python3` shebang keeps working outside the venv. exe() resolves
    # nvidia-smi to an absolute path (ZYG_BIN_NVIDIA_SMI overrides it); a missing binary
    # raises MissingExecutable, which sample()'s `except Exception` already handles the
    # same way it handled FileNotFoundError before.
    from zyg_workflows.bin import exe

    out = subprocess.run(
        [
            exe('nvidia-smi'),
            '--query-gpu=utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu',
            '--format=csv,noheader,nounits',
        ],
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout
    a = [x.strip() for x in out.strip().splitlines()[0].split(',')]
    used, total = float(a[1]), float(a[2])
    return {
        'gpu_util': float(a[0]),
        'vram_pct': used / total * 100.0 if total else None,
        'gpu_power_w': float(a[3]) if a[3] not in ('', '[N/A]') else None,
        'gpu_temp_c': float(a[4]) if a[4] not in ('', '[N/A]') else None,
    }


def sample():
    s = {}
    try:
        s.update(_gpu_pynvml())
    except Exception:
        try:
            s.update(_gpu_smi())
        except Exception as _exc:
            _zyg_log.debug('no gpu sample, neither pynvml nor nvidia-smi answered: %s', _exc)
    if psutil:
        try:
            s['cpu_pct'] = psutil.cpu_percent(interval=None)
            s['ram_pct'] = psutil.virtual_memory().percent
        except Exception as _exc:
            _zyg_log.debug('psutil cpu/ram sample skipped: %s', _exc)
    return s


def _mean(rows, key):
    v = [r[key] for r in rows if r.get(key) is not None]
    return round(sum(v) / len(v), 1) if v else None


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if psutil:
        psutil.cpu_percent(interval=None)  # prime the counter
    bucket, bucket_start = [], time.time()
    print(f'[sysusage] sampling every {SAMPLE_S:g}s -> {OUT}', flush=True)
    while True:
        bucket.append(sample())
        now = time.time()
        if now - bucket_start >= FLUSH_S - SAMPLE_S / 2:
            row = {'ts': round(bucket_start + (now - bucket_start) / 2), 'n': len(bucket)}
            for k in ('gpu_util', 'vram_pct', 'gpu_power_w', 'gpu_temp_c', 'cpu_pct', 'ram_pct'):
                row[k] = _mean(bucket, k)
            try:
                with open(OUT, 'a', encoding='utf-8') as fh:
                    fh.write(json.dumps(row, separators=(',', ':')) + '\n')
            except OSError as exc:
                print(f'[sysusage] write failed: {exc}', file=sys.stderr, flush=True)
            bucket, bucket_start = [], now
        time.sleep(SAMPLE_S)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'once':
        print(json.dumps(sample()))
    else:
        main()
