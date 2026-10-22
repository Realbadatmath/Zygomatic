# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.Schedule.history_timeline`, moved out of the library module so that library code never prints; `python -m zyg_dashboard.Schedule.history_timeline` still reaches it."""

import sys

from zyg_dashboard.Schedule.history_timeline import TimelineHistory


def main():
    """Main function for testing"""
    timeline = TimelineHistory()

    # Get history data
    history_data = timeline.get_history_data()
    summary = history_data['summary']

    print('Historical Timeline Data:')
    print(f'Total Entries: {summary["total_entries"]}')
    print(f'Total Days: {summary["total_days"]}')
    print(f'Total GPU Hours: {summary["total_gpu_hours"]}')
    print(f'Date Range: {summary["date_range"]["start"]} to {summary["date_range"]["end"]}')

    # Generate visualizations and reports
    timeline.generate_historical_visualization()
    timeline.generate_summary_report()

    # Print top models
    print('\nTop 5 AI Models by Historical Usage:')
    model_usage = history_data['model_usage']
    sorted_models = sorted(model_usage.items(), key=lambda x: x[1]['total_hours'], reverse=True)

    for i, (model, data) in enumerate(sorted_models[:5], 1):
        print(f'{i}. {model}: {data["total_hours"]} hours ({data["total_entries"]} entries)')


if __name__ == '__main__':
    sys.exit(main())
