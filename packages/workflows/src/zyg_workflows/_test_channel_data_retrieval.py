# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Quick test — run each fetcher, print status and item count."""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from zyg_workflows.channel_data_retrieval import REGISTRY

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

PASS, FAIL = [], []
for key, fn in REGISTRY.items():
    try:
        r = fn()
        status = r.get('status', '?')
        n = r.get('item_count', 0)
        src = r.get('source', '')
        err = r.get('error', '')
        if status == 'ok':
            _zyg_log.info(f'  OK  {key:30s}  {n:3d} items  [{src}]')
            PASS.append(key)
        else:
            _zyg_log.info(f' FAIL {key:30s}  {err[:80]}  [{src}]')
            FAIL.append((key, err))
    except Exception as ex:
        _zyg_log.info(f'  EXC {key:30s}  {ex}')
        FAIL.append((key, str(ex)))

_zyg_log.info(f'\n{"=" * 60}')
_zyg_log.info(f'PASSED: {len(PASS)}  FAILED: {len(FAIL)}')
if FAIL:
    _zyg_log.info('Failed:')
    for k, e in FAIL:
        _zyg_log.info(f'  {k}: {e[:100]}')
sys.exit(0 if not FAIL else 1)
