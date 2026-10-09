#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
7-Day Timeline Script for CrewAI Agent Schedule
Manages and visualizes schedule data over a 7-day period
"""

import json
import datetime
from typing import Dict, List
import matplotlib.pyplot as plt
from datetime import timedelta
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


class Timeline7Day:
    def __init__(self, schedule_file: str = 'schedule_data_ACTIVE.json'):
        self.schedule_file = schedule_file
        self.schedule_data = self.load_schedule_data()

    def load_schedule_data(self) -> Dict:
        """Load schedule data from JSON file"""
        try:
            with open(self.schedule_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            _zyg_log.info(f'Schedule file {self.schedule_file} not found. Creating empty schedule.')
            return {}
        except json.JSONDecodeError:
            _zyg_log.info(f'Error reading {self.schedule_file}. Creating empty schedule.')
            return {}

    def save_schedule_data(self):
        """Save schedule data to JSON file"""
        with open(self.schedule_file, 'w') as f:
            json.dump(self.schedule_data, f, indent=2)

    def get_week_entries(self, start_date: str = None) -> List[Dict]:
        """Get all schedule entries for a 7-day period starting from start_date"""
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')

        start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
        entries = []

        for i in range(7):
            current_date = start_dt + timedelta(days=i)
            date_str = current_date.strftime('%Y-%m-%d')

            if date_str in self.schedule_data:
                day_entries = self.schedule_data[date_str]
                for entry in day_entries:
                    entry['date'] = date_str
                    entry['day_of_week'] = current_date.strftime('%A')
                    entries.append(entry)

        return entries

    def get_daily_summary(self, start_date: str = None) -> Dict:
        """Get a summary of schedule entries for each day of the week"""
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')

        start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
        daily_summary = {}

        for i in range(7):
            current_date = start_dt + timedelta(days=i)
            date_str = current_date.strftime('%Y-%m-%d')
            day_name = current_date.strftime('%A')

            daily_summary[date_str] = {
                'day_name': day_name,
                'date': date_str,
                'entries': self.schedule_data.get(date_str, []),
                'total_entries': len(self.schedule_data.get(date_str, [])),
                'models_used': list(set([entry.get('ai_model') for entry in self.schedule_data.get(date_str, [])])),
                'total_gpu_hours': self.calculate_total_gpu_hours(date_str),
            }

        return daily_summary

    def calculate_total_gpu_hours(self, date: str) -> float:
        """Calculate total GPU hours for a specific date"""
        entries = self.schedule_data.get(date, [])
        total_hours = 0.0

        for entry in entries:
            start_time = entry.get('start_time', '00:00')
            end_time = entry.get('end_time', '23:59')

            try:
                start_hour, start_minute = map(int, start_time.split(':'))
                end_hour, end_minute = map(int, end_time.split(':'))

                start_total = start_hour + start_minute / 60
                end_total = end_hour + end_minute / 60

                # Handle overnight schedules
                if end_total < start_total:
                    end_total += 24

                duration = end_total - start_total
                total_hours += duration

            except (ValueError, AttributeError) as _exc:
                _zyg_log.debug('skipping entry with unparseable time range: %s', _exc)
                continue

        return round(total_hours, 2)

    def generate_week_visualization(self, start_date: str = None, output_file: str = '7_day_timeline.png'):
        """Generate a 7-day timeline visualization"""
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')

        daily_summary = self.get_daily_summary(start_date)

        # Configuration
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

        # Plot 1: Daily entry counts
        dates = list(daily_summary.keys())
        entry_counts = [daily_summary[date]['total_entries'] for date in dates]
        day_names = [daily_summary[date]['day_name'] for date in dates]

        bars1 = ax1.bar(range(7), entry_counts, color='skyblue', alpha=0.7)
        ax1.set_xlabel('Day of Week')
        ax1.set_ylabel('Number of Schedule Entries')
        ax1.set_title('7-Day Schedule Overview')
        ax1.set_xticks(range(7))
        ax1.set_xticklabels(day_names, rotation=45)

        # Add value labels on bars
        for bar, count in zip(bars1, entry_counts):
            height = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width() / 2.0, height + 0.1, f'{count}', ha='center', va='bottom')

        # Plot 2: GPU hours per day
        gpu_hours = [daily_summary[date]['total_gpu_hours'] for date in dates]

        bars2 = ax2.bar(range(7), gpu_hours, color='lightgreen', alpha=0.7)
        ax2.set_xlabel('Day of Week')
        ax2.set_ylabel('Total GPU Hours')
        ax2.set_title('7-Day GPU Usage')
        ax2.set_xticks(range(7))
        ax2.set_xticklabels(day_names, rotation=45)

        # Add value labels on bars
        for bar, hours in zip(bars2, gpu_hours):
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width() / 2.0, height + 0.1, f'{hours}h', ha='center', va='bottom')

        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()

        _zyg_log.info(f'Generated {output_file}')

    def get_model_usage_summary(self, start_date: str = None) -> Dict:
        """Get summary of AI model usage over the 7-day period"""
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')

        entries = self.get_week_entries(start_date)
        model_usage = {}

        for entry in entries:
            model = entry.get('ai_model', 'Unknown')
            if model not in model_usage:
                model_usage[model] = {'total_entries': 0, 'total_hours': 0.0, 'days_used': set(), 'agents': set()}

            model_usage[model]['total_entries'] += 1
            model_usage[model]['days_used'].add(entry.get('date'))
            if entry.get('agent'):
                model_usage[model]['agents'].add(entry.get('agent'))

            # Calculate hours
            start_time = entry.get('start_time', '00:00')
            end_time = entry.get('end_time', '23:59')

            try:
                start_hour, start_minute = map(int, start_time.split(':'))
                end_hour, end_minute = map(int, end_time.split(':'))

                start_total = start_hour + start_minute / 60
                end_total = end_hour + end_minute / 60

                if end_total < start_total:
                    end_total += 24

                duration = end_total - start_total
                model_usage[model]['total_hours'] += duration

            except (ValueError, AttributeError) as _exc:
                _zyg_log.debug('skipping entry with unparseable time range in model usage: %s', _exc)
                continue

        # Convert sets to lists for JSON serialization
        for model in model_usage:
            model_usage[model]['days_used'] = list(model_usage[model]['days_used'])
            model_usage[model]['agents'] = list(model_usage[model]['agents'])
            model_usage[model]['total_hours'] = round(model_usage[model]['total_hours'], 2)

        return model_usage

    def generate_model_usage_chart(self, start_date: str = None, output_file: str = '7_day_model_usage.png'):
        """Generate a chart showing AI model usage over 7 days"""
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')

        model_usage = self.get_model_usage_summary(start_date)

        if not model_usage:
            _zyg_log.info('No model usage data found')
            return

        # Sort models by total hours
        sorted_models = sorted(model_usage.items(), key=lambda x: x[1]['total_hours'], reverse=True)

        models = [item[0] for item in sorted_models]
        hours = [item[1]['total_hours'] for item in sorted_models]
        entries = [item[1]['total_entries'] for item in sorted_models]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))

        # Plot 1: Total hours per model
        bars1 = ax1.barh(range(len(models)), hours, color='lightcoral', alpha=0.7)
        ax1.set_yticks(range(len(models)))
        ax1.set_yticklabels(models)
        ax1.set_xlabel('Total GPU Hours')
        ax1.set_title('AI Model Usage (7 Days) - Total Hours')

        # Add value labels
        for _i, (bar, hour) in enumerate(zip(bars1, hours)):
            ax1.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height() / 2, f'{hour}h', ha='left', va='center')

        # Plot 2: Number of entries per model
        bars2 = ax2.barh(range(len(models)), entries, color='lightblue', alpha=0.7)
        ax2.set_yticks(range(len(models)))
        ax2.set_yticklabels(models)
        ax2.set_xlabel('Number of Schedule Entries')
        ax2.set_title('AI Model Usage (7 Days) - Entry Count')

        # Add value labels
        for _i, (bar, entry_count) in enumerate(zip(bars2, entries)):
            ax2.text(
                bar.get_width() + 0.1, bar.get_y() + bar.get_height() / 2, f'{entry_count}', ha='left', va='center'
            )

        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()

        _zyg_log.info(f'Generated {output_file}')

    def get_week_data(self, date: str = None) -> dict:
        self.schedule_data = self.load_schedule_data()  # Always reload
        """Get comprehensive 7-day data for web interface"""
        if date is None:
            date = datetime.datetime.now().strftime('%Y-%m-%d')

        return {
            'start_date': date,
            'daily_summary': self.get_daily_summary(date),
            'model_usage': self.get_model_usage_summary(date),
            'total_entries': len(self.get_week_entries(date)),
            'week_range': self.get_week_range(date),
        }

    def get_week_range(self, start_date: str) -> List[str]:
        """Get list of dates for the 7-day period"""
        start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
        dates = []

        for i in range(7):
            current_date = start_dt + timedelta(days=i)
            dates.append(current_date.strftime('%Y-%m-%d'))

        return dates


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
    main()
