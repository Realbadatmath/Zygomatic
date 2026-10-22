# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.Schedule.28_day_timeline`, moved out of the library module so that library code never prints; `python -m zyg_dashboard.Schedule.28_day_timeline` still reaches it."""

import importlib
import sys

# The library module's name starts with a digit, so it cannot be spelled in an import statement.
_mod = importlib.import_module('zyg_dashboard.Schedule.28_day_timeline')
Timeline28Day = _mod.Timeline28Day


def main():
    """Main function for testing"""
    timeline = Timeline28Day()

    # Get month data
    month_data = timeline.get_month_data()
    print('28-Day Timeline Data:')
    print(f'Start Date: {month_data["start_date"]}')
    print(f'Total Entries: {month_data["total_entries"]}')

    # Generate visualizations
    timeline.generate_month_visualization()
    timeline.generate_calendar_view()

    # Print weekly summary
    print('\nWeekly Summary:')
    for week, summary in month_data['weekly_summary'].items():
        print(f'{week}: {summary["total_entries"]} entries, {summary["total_gpu_hours"]} GPU hours')


if __name__ == '__main__':
    sys.exit(main())
