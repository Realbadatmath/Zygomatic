# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.sysusage_sampler`, moved out of the library module so
that library code never prints; `python -m zyg_dashboard.sysusage_sampler` still reaches it.
"""

import json
import os
import sys
import time

from zyg_dashboard.sysusage_sampler import (
    FLUSH_S,
    OUT,
    SAMPLE_S,
    _mean,
    psutil,
    sample,
)


def _run() -> None:
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


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == 'once':
        print(json.dumps(sample()))
    else:
        _run()
    return 0


if __name__ == '__main__':
    sys.exit(main())
