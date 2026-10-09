#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Verify Schedule Population Results
This script analyzes the populated schedule files and provides statistics.
"""

import json
from collections import defaultdict

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def analyze_schedule_files():
    """Analyze the populated schedule files"""

    # Load CPU schedule
    with open('Schedule/schedule_data_CPU.json', 'r') as f:
        cpu_data = json.load(f)

    # Load GPU schedule
    with open('Schedule/schedule_data_GPU.json', 'r') as f:
        gpu_data = json.load(f)

    # Analyze CPU data
    cpu_entries = cpu_data['2025-07-13']
    cpu_model_counts = defaultdict(int)
    cpu_agent_counts = defaultdict(int)
    cpu_bar_widths = defaultdict(list)

    for entry in cpu_entries:
        model = entry['ai_model']
        agent = entry['agent']
        bar_width = entry['bar_width']

        cpu_model_counts[model] += 1
        cpu_agent_counts[agent] += 1
        cpu_bar_widths[model].append(bar_width)

    # Analyze GPU data
    gpu_entries = gpu_data['2025-07-13']
    gpu_model_counts = defaultdict(int)
    gpu_agent_counts = defaultdict(int)
    gpu_bar_widths = defaultdict(list)

    for entry in gpu_entries:
        model = entry['ai_model']
        agent = entry['agent']
        bar_width = entry['bar_width']

        gpu_model_counts[model] += 1
        gpu_agent_counts[agent] += 1
        gpu_bar_widths[model].append(bar_width)

    # Print results
    _zyg_log.info('=== SCHEDULE POPULATION VERIFICATION ===\n')

    _zyg_log.info('📊 CPU SCHEDULE STATISTICS:')
    _zyg_log.info('-' * 50)
    _zyg_log.info(f'Total CPU entries: {len(cpu_entries)}')
    _zyg_log.info(f'Unique CPU models: {len(cpu_model_counts)}')
    _zyg_log.info(f'Unique CPU agents: {len(cpu_agent_counts)}')

    _zyg_log.info('\n🤖 CPU MODELS AND THEIR VERTICAL BARS:')
    for model, count in sorted(cpu_model_counts.items(), key=lambda x: x[1], reverse=True):
        avg_width = sum(cpu_bar_widths[model]) / len(cpu_bar_widths[model])
        _zyg_log.info(f'  {model}: {count} bars (avg width: {avg_width:.2f}px)')

    _zyg_log.info('\n📊 GPU SCHEDULE STATISTICS:')
    _zyg_log.info('-' * 50)
    _zyg_log.info(f'Total GPU entries: {len(gpu_entries)}')
    _zyg_log.info(f'Unique GPU models: {len(gpu_model_counts)}')
    _zyg_log.info(f'Unique GPU agents: {len(gpu_agent_counts)}')

    _zyg_log.info('\n🤖 GPU MODELS AND THEIR VERTICAL BARS:')
    for model, count in sorted(gpu_model_counts.items(), key=lambda x: x[1], reverse=True):
        avg_width = sum(gpu_bar_widths[model]) / len(gpu_bar_widths[model])
        _zyg_log.info(f'  {model}: {count} bars (avg width: {avg_width:.2f}px)')

    _zyg_log.info('\n🎯 TOTAL SUMMARY:')
    _zyg_log.info('-' * 50)
    _zyg_log.info(f'Total vertical bars: {len(cpu_entries) + len(gpu_entries)}')
    _zyg_log.info(f'Total unique models: {len(cpu_model_counts) + len(gpu_model_counts)}')
    _zyg_log.info(f'Total unique agents: {len(set(cpu_agent_counts.keys()) | set(gpu_agent_counts.keys()))}')

    # Verify bar width logic
    _zyg_log.info('\n📏 BAR WIDTH VERIFICATION:')
    _zyg_log.info('-' * 50)

    def verify_bar_widths(model_counts, bar_widths, model_type):
        _zyg_log.info(f'\n{model_type} Bar Widths:')
        for model, count in model_counts.items():
            widths = bar_widths[model]
            expected_width = 19 if count >= 9 else (150 / count if count <= 8 else 19)
            actual_width = widths[0] if widths else 0
            _zyg_log.info(f'  {model}: {count} agents → expected: {expected_width:.2f}px, actual: {actual_width}px')

    verify_bar_widths(cpu_model_counts, cpu_bar_widths, 'CPU')
    verify_bar_widths(gpu_model_counts, gpu_bar_widths, 'GPU')


if __name__ == '__main__':
    analyze_schedule_files()
