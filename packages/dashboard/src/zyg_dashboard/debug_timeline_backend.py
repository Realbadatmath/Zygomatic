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
from datetime import datetime

# Import timeline orchestrator and model mapping
sys.path.append(os.path.join(os.path.dirname(__file__), 'Schedule'))
from zyg_dashboard.Schedule.timeline_orchestrator_dual import DualTimelineOrchestrator
from zyg_workflows.ai_model_agent_mapping import model_to_agents

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


def main():
    date = datetime.now().strftime('%Y-%m-%d')
    if len(sys.argv) > 1:
        date = sys.argv[1]
    print(f'Debugging timeline data for date: {date}')
    orchestrator = DualTimelineOrchestrator(
        cpu_schedule_file='schedule_data_CPU.json', gpu_schedule_file='schedule_data_GPU.json'
    )
    cpu_data = orchestrator.get_cpu_timeline_data('24h', date=date)
    gpu_data = orchestrator.get_gpu_timeline_data('24h', date=date)
    print_timeline_data(cpu_data, 'CPU')
    print_timeline_data(gpu_data, 'GPU')
    print('\n=== Model to Agents Mapping (first 5 models) ===')
    for i, (model, agents) in enumerate(model_to_agents.items()):
        if i >= 5:
            break
        print(f'{model}: {agents}')


if __name__ == '__main__':
    main()
