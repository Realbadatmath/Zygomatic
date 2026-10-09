#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Utility script to kill Flask processes on port 5000
Useful for cleaning up stuck Flask servers
"""

import subprocess
import platform
from zyg_workflows.bin import exe

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def kill_flask_processes():
    """Kill any Flask processes on port 5000"""
    system = platform.system().lower()

    _zyg_log.info('Checking for Flask processes on port 5000...')

    if system == 'windows':
        try:
            # Find processes using port 5000
            result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True, check=True)

            lines = result.stdout.split('\n')
            flask_pids = []

            for line in lines:
                if ':5000' in line and 'LISTENING' in line:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        pid = parts[-1]
                        flask_pids.append(pid)

            if flask_pids:
                _zyg_log.info(f'Found {len(flask_pids)} process(es) using port 5000')

                # Kill the processes
                for pid in flask_pids:
                    try:
                        subprocess.run(['taskkill', '/F', '/PID', pid], check=True)
                        _zyg_log.info(f'✓ Killed process with PID: {pid}')
                    except subprocess.CalledProcessError:
                        _zyg_log.info(f'✗ Could not kill process {pid}')
            else:
                _zyg_log.info('No processes found using port 5000')

        except subprocess.CalledProcessError:
            _zyg_log.info('Error: Could not check for existing Flask processes')

    else:
        # Linux/Mac
        try:
            # Find processes using port 5000
            result = subprocess.run([exe('lsof'), '-ti:5000'], capture_output=True, text=True, check=True)

            pids = result.stdout.strip().split('\n')

            if pids and pids[0]:
                _zyg_log.info(f'Found {len(pids)} process(es) using port 5000')

                for pid in pids:
                    if pid:
                        try:
                            subprocess.run(['kill', '-9', pid], check=True)
                            _zyg_log.info(f'✓ Killed process with PID: {pid}')
                        except subprocess.CalledProcessError:
                            _zyg_log.info(f'✗ Could not kill process {pid}')
            else:
                _zyg_log.info('No processes found using port 5000')

        except subprocess.CalledProcessError:
            _zyg_log.info('No processes found using port 5000')


if __name__ == '__main__':
    kill_flask_processes()
