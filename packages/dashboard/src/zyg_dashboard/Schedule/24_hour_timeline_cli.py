# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.Schedule.24_hour_timeline`, moved out of the library module so that library code never prints; `python -m zyg_dashboard.Schedule.24_hour_timeline` still reaches it."""

import importlib
import sys

# The library module's name starts with a digit, so it cannot be spelled in an import statement.
_mod = importlib.import_module('zyg_dashboard.Schedule.24_hour_timeline')
Timeline24Hour = _mod.Timeline24Hour


def main():
    """Main function for testing"""
    timeline = Timeline24Hour()

    # Test data
    test_entry = {
        'ai_model': 'Claude_3',
        'start_time': '09:00',
        'end_time': '17:00',
        'gpu_percent': '99.9',
        'memory_fraction': '0.10',
        'gpu_device': 'NVIDIA GeForce GTX 970',
        'priority': 'High',
        'agent': 'CEO_Agent',
    }

    # Add test entry
    success, message = timeline.validate_schedule_entry(test_entry)
    if success:
        timeline.add_schedule_entry(test_entry)
        print('Added test entry successfully')
    else:
        print(f'Validation failed: {message}')

    # Generate visualization
    timeline.generate_timeline_visualization()

    # Get timeline data
    data = timeline.get_timeline_data()
    print(f'Timeline data for {data["date"]}: {len(data["entries"])} entries')


if __name__ == '__main__':
    sys.exit(main())
