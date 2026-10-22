#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Debug Timeline Backend Script
Prints out all schedule entries, models, and bar counts for CPU and GPU timelines for a given date.
Highlights models/agents with zero scheduled bars.
"""

import os
import sys

# Make the Schedule directory importable for the timeline orchestrator the CLI loads.
sys.path.append(os.path.join(os.path.dirname(__file__), 'Schedule'))

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def print_timeline_data(timeline_data, label):
    _zyg_log.info(f'\n=== {label} Timeline Data ===')
    _zyg_log.info(f'Date: {timeline_data.get("date")}')
    _zyg_log.info(f'Models: {len(timeline_data.get("models", []))}')
    _zyg_log.info(f'Entries: {len(timeline_data.get("entries", []))}')
    _zyg_log.info('Model Agent Counts:')
    for model in timeline_data.get('models', []):
        count = timeline_data.get('model_agent_counts', {}).get(model, 0)
        _zyg_log.info(f'  {model}: {count}')
    _zyg_log.info('\nModels with zero scheduled bars:')
    for model in timeline_data.get('models', []):
        count = timeline_data.get('model_agent_counts', {}).get(model, 0)
        if count == 0:
            _zyg_log.info(f'  {model}')
    _zyg_log.info('\nFirst 5 entries:')
    for entry in timeline_data.get('entries', [])[:5]:
        _zyg_log.info(entry)
    _zyg_log.info('...\n')


if __name__ == '__main__':  # the CLI lives in debug_timeline_backend_cli
    from zyg_dashboard.debug_timeline_backend_cli import main as _cli_main

    raise SystemExit(_cli_main())
