# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""skill_integrity_monitor.py — File integrity monitor for critical server files.

On first run: hashes the critical files and saves a baseline.
On subsequent runs: compares hashes and logs any changes.

Run via cron every 5 minutes:
    */5 * * * * /path/to/.venv/bin/python3 skill_integrity_monitor.py

Or run once manually to create/refresh the baseline:
    python3 skill_integrity_monitor.py --reset
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
_BASE = os.path.join(_HERE, 'data', 'runtime', 'integrity_baseline.json')
_ALERTS = os.path.join(_HERE, 'data', 'runtime', 'integrity_alerts.log')

CRITICAL_FILES = [
    os.path.join(_HERE, 'crewai_web_gui.py'),
    os.path.join(_HERE, 'skill_sandbox.py'),
    os.path.join(_HERE, 'skill_integrity_monitor.py'),
]

# Also monitor the zero_public_server if it exists
_zps = os.path.join(os.path.dirname(_HERE), 'zero_public_server.py')
if os.path.exists(_zps):
    CRITICAL_FILES.append(_zps)
_zps2 = os.path.join(_HERE, 'zero_public_server.py')
if os.path.exists(_zps2) and _zps2 not in CRITICAL_FILES:
    CRITICAL_FILES.append(_zps2)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _load_baseline() -> dict:
    if not os.path.exists(_BASE):
        return {}
    with open(_BASE) as f:
        return json.load(f)


def _save_baseline(baseline: dict) -> None:
    os.makedirs(os.path.dirname(_BASE), exist_ok=True)
    with open(_BASE, 'w') as f:
        json.dump(baseline, f, indent=2)


def _alert(msg: str) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    line = f'[{ts}] {msg}\n'
    os.makedirs(os.path.dirname(_ALERTS), exist_ok=True)
    with open(_ALERTS, 'a') as f:
        f.write(line)
    _zyg_log.warning(f'[INTEGRITY-ALERT] {msg}')


def build_baseline() -> dict:
    baseline = {}
    for path in CRITICAL_FILES:
        if os.path.exists(path):
            baseline[path] = {
                'sha256': _sha256(path),
                'size': os.path.getsize(path),
                'ts': datetime.now(timezone.utc).isoformat(),
            }
        else:
            baseline[path] = {'sha256': None, 'size': None, 'ts': None, 'missing': True}
    return baseline


def check_integrity() -> bool:
    """Returns True if all files match baseline (clean), False if any change detected."""
    baseline = _load_baseline()
    if not baseline:
        _zyg_log.info('[INTEGRITY] No baseline found — creating baseline now.')
        _save_baseline(build_baseline())
        _zyg_log.info(f'[INTEGRITY] Baseline written to {_BASE}')
        return True

    all_clean = True
    for path in CRITICAL_FILES:
        if path not in baseline:
            _alert(f'NEW FILE not in baseline: {path}')
            all_clean = False
            continue

        expected = baseline[path]

        if not os.path.exists(path):
            if not expected.get('missing'):
                _alert(f'FILE DELETED: {path}')
                all_clean = False
            continue

        current_hash = _sha256(path)
        if current_hash != expected.get('sha256'):
            _alert(f'FILE MODIFIED: {path} — expected {expected["sha256"][:12]}… got {current_hash[:12]}…')
            all_clean = False
        else:
            _zyg_log.info(f'[INTEGRITY] OK  {os.path.basename(path)}')

    return all_clean


def main():
    parser = argparse.ArgumentParser(description='File integrity monitor')
    parser.add_argument('--reset', action='store_true', help='Rebuild baseline from current file state')
    args = parser.parse_args()

    if args.reset:
        baseline = build_baseline()
        _save_baseline(baseline)
        print(f'[INTEGRITY] Baseline reset — {len(baseline)} files hashed.', flush=True)
        for path, info in baseline.items():
            print(f'  {info["sha256"][:16]}…  {os.path.basename(path)}', flush=True)
        sys.exit(0)

    clean = check_integrity()
    sys.exit(0 if clean else 1)


if __name__ == '__main__':
    main()
