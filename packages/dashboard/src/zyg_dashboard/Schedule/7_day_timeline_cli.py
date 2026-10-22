# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.Schedule.7_day_timeline`, moved out of the library module so that library code never prints; `python -m zyg_dashboard.Schedule.7_day_timeline` still reaches it."""

import importlib
import sys

# The library module's name starts with a digit, so it cannot be spelled in an import statement.
_mod = importlib.import_module('zyg_dashboard.Schedule.7_day_timeline')
Timeline7Day = _mod.Timeline7Day


def main():
    """Main function for testing"""
    timeline = Timeline7Day()

    # Get week data
    week_data = timeline.get_week_data()
    print('7-Day Timeline Data:')
    print(f'Start Date: {week_data["start_date"]}')
    print(f'Total Entries: {week_data["total_entries"]}')
    print(f'Week Range: {week_data["week_range"]}')

    # Generate visualizations
    timeline.generate_week_visualization()
    timeline.generate_model_usage_chart()

    # Print daily summary
    print('\nDaily Summary:')
    for date, summary in week_data['daily_summary'].items():
        print(
            f'{summary["day_name"]} ({date}): {summary["total_entries"]} entries, {summary["total_gpu_hours"]} GPU hours'
        )


if __name__ == '__main__':
    sys.exit(main())
