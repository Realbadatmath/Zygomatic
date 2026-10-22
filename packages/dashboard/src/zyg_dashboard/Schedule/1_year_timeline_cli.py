# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.Schedule.1_year_timeline`, moved out of the library module so that library code never prints; `python -m zyg_dashboard.Schedule.1_year_timeline` still reaches it."""

import importlib
import sys

# The library module's name starts with a digit, so it cannot be spelled in an import statement.
_mod = importlib.import_module('zyg_dashboard.Schedule.1_year_timeline')
Timeline1Year = _mod.Timeline1Year


def main():
    """Main function for testing"""
    timeline = Timeline1Year()

    # Get year data
    year_data = timeline.get_year_data()
    print('1-Year Timeline Data:')
    print(f'Start Date: {year_data["start_date"]}')
    print(f'Total Entries: {year_data["total_entries"]}')

    # Generate visualizations
    timeline.generate_year_visualization()
    timeline.generate_quarterly_report()

    # Print monthly summary
    print('\nMonthly Summary:')
    for month, summary in year_data['monthly_summary'].items():
        print(f'{month}: {summary["total_entries"]} entries, {summary["total_gpu_hours"]} GPU hours')


if __name__ == '__main__':
    sys.exit(main())
