#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Test script for GPU timeline visualization
"""

import datetime
import importlib.util
import os
import sys

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

spec = importlib.util.spec_from_file_location('timeline_24h', 'Schedule/24_hour_timeline.py')
timeline_24h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(timeline_24h)
Timeline24Hour = timeline_24h.Timeline24Hour


def test_gpu_timeline():
    """Test the GPU timeline generation"""
    _zyg_log.info('Testing GPU timeline generation...')

    # Initialize timeline with GPU schedule file
    timeline = Timeline24Hour('Schedule/schedule_data_GPU.json')

    # Generate for today
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    output_file = f'Schedule/gpu_24_hour_timeline_{today}.png'

    _zyg_log.info(f'Generating GPU timeline for {today}...')
    timeline.generate_gpu_timeline_visualization(today, output_file)

    if os.path.exists(output_file):
        _zyg_log.info(f'✅ Successfully generated: {output_file}')
        _zyg_log.info(f'File size: {os.path.getsize(output_file)} bytes')
    else:
        _zyg_log.info(f'❌ Failed to generate: {output_file}')


if __name__ == '__main__':
    test_gpu_timeline()
