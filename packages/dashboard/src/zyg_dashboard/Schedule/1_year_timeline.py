#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
1-Year Timeline Script for CrewAI Agent Schedule
Manages and visualizes schedule data over a 1-year period
"""

import json
import datetime
from typing import Dict, List
import matplotlib.pyplot as plt
import numpy as np
from datetime import timedelta
from collections import defaultdict
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


class Timeline1Year:
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

    def get_year_entries(self, start_date: str = None) -> List[Dict]:
        """Get all schedule entries for a 1-year period starting from start_date"""
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')

        start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
        entries = []

        for i in range(365):
            current_date = start_dt + timedelta(days=i)
            date_str = current_date.strftime('%Y-%m-%d')

            if date_str in self.schedule_data:
                day_entries = self.schedule_data[date_str]
                for entry in day_entries:
                    entry['date'] = date_str
                    entry['day_of_week'] = current_date.strftime('%A')
                    entry['month'] = current_date.month
                    entry['month_name'] = current_date.strftime('%B')
                    entry['week_of_year'] = current_date.isocalendar()[1]
                    entries.append(entry)

        return entries

    def get_monthly_summary(self, start_date: str = None) -> Dict:
        """Get a summary of schedule entries grouped by months"""
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')

        start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
        monthly_summary = defaultdict(
            lambda: {
                'entries': [],
                'total_entries': 0,
                'total_gpu_hours': 0.0,
                'models_used': set(),
                'agents_used': set(),
                'days_with_activity': set(),
            }
        )

        for i in range(365):
            current_date = start_dt + timedelta(days=i)
            date_str = current_date.strftime('%Y-%m-%d')
            month_key = current_date.strftime('%Y-%m')

            if date_str in self.schedule_data:
                day_entries = self.schedule_data[date_str]
                monthly_summary[month_key]['entries'].extend(day_entries)
                monthly_summary[month_key]['total_entries'] += len(day_entries)
                monthly_summary[month_key]['days_with_activity'].add(date_str)

                for entry in day_entries:
                    if entry.get('ai_model'):
                        monthly_summary[month_key]['models_used'].add(entry.get('ai_model'))
                    if entry.get('agent'):
                        monthly_summary[month_key]['agents_used'].add(entry.get('agent'))

        # Calculate GPU hours and convert sets to lists
        for month_key in monthly_summary:
            month_data = monthly_summary[month_key]
            month_data['total_gpu_hours'] = self.calculate_total_gpu_hours(month_data['entries'])
            month_data['models_used'] = list(month_data['models_used'])
            month_data['agents_used'] = list(month_data['agents_used'])
            month_data['days_with_activity'] = len(month_data['days_with_activity'])
            month_data['avg_entries_per_day'] = (
                round(month_data['total_entries'] / month_data['days_with_activity'], 2)
                if month_data['days_with_activity'] > 0
                else 0
            )

        return dict(monthly_summary)

    def get_weekly_summary(self, start_date: str = None) -> Dict:
        """Get a summary of schedule entries grouped by weeks of the year"""
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')

        start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
        weekly_summary = defaultdict(
            lambda: {
                'entries': [],
                'total_entries': 0,
                'total_gpu_hours': 0.0,
                'models_used': set(),
                'days_with_activity': set(),
            }
        )

        for i in range(365):
            current_date = start_dt + timedelta(days=i)
            date_str = current_date.strftime('%Y-%m-%d')
            week_key = f'Week {current_date.isocalendar()[1]}'

            if date_str in self.schedule_data:
                day_entries = self.schedule_data[date_str]
                weekly_summary[week_key]['entries'].extend(day_entries)
                weekly_summary[week_key]['total_entries'] += len(day_entries)
                weekly_summary[week_key]['days_with_activity'].add(date_str)

                for entry in day_entries:
                    if entry.get('ai_model'):
                        weekly_summary[week_key]['models_used'].add(entry.get('ai_model'))

        # Calculate GPU hours and convert sets to lists
        for week_key in weekly_summary:
            week_data = weekly_summary[week_key]
            week_data['total_gpu_hours'] = self.calculate_total_gpu_hours(week_data['entries'])
            week_data['models_used'] = list(week_data['models_used'])
            week_data['days_with_activity'] = len(week_data['days_with_activity'])

        return dict(weekly_summary)

    def calculate_total_gpu_hours(self, entries: List[Dict]) -> float:
        """Calculate total GPU hours for a list of entries"""
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

    def generate_year_visualization(self, start_date: str = None, output_file: str = '1_year_timeline.png'):
        """Generate a 1-year timeline visualization"""
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')

        monthly_summary = self.get_monthly_summary(start_date)
        weekly_summary = self.get_weekly_summary(start_date)

        # Configuration
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(20, 16))

        # Plot 1: Monthly entry counts
        months = list(monthly_summary.keys())
        entry_counts = [monthly_summary[month]['total_entries'] for month in months]
        gpu_hours = [monthly_summary[month]['total_gpu_hours'] for month in months]

        x = np.arange(len(months))
        width = 0.35

        bars1a = ax1.bar(x - width / 2, entry_counts, width, label='Entries', color='skyblue', alpha=0.7)
        bars1b = ax1.bar(x + width / 2, gpu_hours, width, label='GPU Hours', color='lightgreen', alpha=0.7)

        ax1.set_xlabel('Month')
        ax1.set_ylabel('Count')
        ax1.set_title('Monthly Summary (1 Year)')
        ax1.set_xticks(x)
        ax1.set_xticklabels([month.split('-')[1] for month in months], rotation=45)
        ax1.legend()

        # Add value labels
        for bar in bars1a:
            height = bar.get_height()
            ax1.text(
                bar.get_x() + bar.get_width() / 2.0,
                height + 0.1,
                f'{int(height)}',
                ha='center',
                va='bottom',
                fontsize=8,
            )

        for bar in bars1b:
            height = bar.get_height()
            ax1.text(
                bar.get_x() + bar.get_width() / 2.0, height + 0.1, f'{height}h', ha='center', va='bottom', fontsize=8
            )

        # Plot 2: Weekly trend
        weeks = list(weekly_summary.keys())
        week_entries = [weekly_summary[week]['total_entries'] for week in weeks]

        ax2.plot(range(len(weeks)), week_entries, marker='o', color='red', linewidth=1, markersize=2)
        ax2.set_xlabel('Week of Year')
        ax2.set_ylabel('Number of Entries')
        ax2.set_title('Weekly Trend (1 Year)')
        ax2.set_xticks(range(0, len(weeks), 4))
        ax2.set_xticklabels([weeks[i] for i in range(0, len(weeks), 4)], rotation=45)
        ax2.grid(True, alpha=0.3)

        # Plot 3: Model usage over the year
        model_usage = self.get_model_usage_summary(start_date)
        if model_usage:
            models = list(model_usage.keys())
            total_hours = [model_usage[model]['total_hours'] for model in models]

            # Sort by hours and take top 15
            sorted_data = sorted(zip(models, total_hours), key=lambda x: x[1], reverse=True)
            models, total_hours = zip(*sorted_data[:15])

            bars3 = ax3.barh(range(len(models)), total_hours, color='lightcoral', alpha=0.7)
            ax3.set_yticks(range(len(models)))
            ax3.set_yticklabels(models)
            ax3.set_xlabel('Total GPU Hours')
            ax3.set_title('Top 15 AI Models (1 Year)')

            # Add value labels
            for _i, (bar, hours) in enumerate(zip(bars3, total_hours)):
                ax3.text(
                    bar.get_width() + 0.1,
                    bar.get_y() + bar.get_height() / 2,
                    f'{hours}h',
                    ha='left',
                    va='center',
                    fontsize=8,
                )

        # Plot 4: Activity heatmap (simplified)
        activity_data = self.get_activity_heatmap_data(start_date)
        if activity_data:
            im = ax4.imshow(activity_data, cmap='YlOrRd', aspect='auto')
            ax4.set_xlabel('Week of Year')
            ax4.set_ylabel('Day of Week')
            ax4.set_title('Activity Heatmap (1 Year)')
            ax4.set_yticks(range(7))
            ax4.set_yticklabels(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'])
            plt.colorbar(im, ax=ax4, label='Entries per Day')

        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()

        _zyg_log.info(f'Generated {output_file}')

    def get_activity_heatmap_data(self, start_date: str = None) -> np.ndarray:
        """Generate activity heatmap data for the year"""
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')

        start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
        heatmap = np.zeros((7, 53))  # 7 days, up to 53 weeks

        for i in range(365):
            current_date = start_dt + timedelta(days=i)
            date_str = current_date.strftime('%Y-%m-%d')

            day_of_week = current_date.weekday()  # 0=Monday, 6=Sunday
            week_of_year = current_date.isocalendar()[1] - 1  # 0-based

            if date_str in self.schedule_data:
                entry_count = len(self.schedule_data[date_str])
                heatmap[day_of_week, week_of_year] = entry_count

        return heatmap

    def get_model_usage_summary(self, start_date: str = None) -> Dict:
        """Get summary of AI model usage over the 1-year period"""
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')

        entries = self.get_year_entries(start_date)
        model_usage = {}

        for entry in entries:
            model = entry.get('ai_model', 'Unknown')
            if model not in model_usage:
                model_usage[model] = {
                    'total_entries': 0,
                    'total_hours': 0.0,
                    'days_used': set(),
                    'months_used': set(),
                    'agents': set(),
                }

            model_usage[model]['total_entries'] += 1
            model_usage[model]['days_used'].add(entry.get('date'))
            model_usage[model]['months_used'].add(entry.get('month'))
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
            model_usage[model]['months_used'] = list(model_usage[model]['months_used'])
            model_usage[model]['agents'] = list(model_usage[model]['agents'])
            model_usage[model]['total_hours'] = round(model_usage[model]['total_hours'], 2)

        return model_usage

    def generate_quarterly_report(self, start_date: str = None, output_file: str = '1_year_quarterly.png'):
        """Generate a quarterly report visualization"""
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')

        monthly_summary = self.get_monthly_summary(start_date)

        # Group by quarters
        quarters = {
            'Q1': {'months': [], 'entries': 0, 'hours': 0.0},
            'Q2': {'months': [], 'entries': 0, 'hours': 0.0},
            'Q3': {'months': [], 'entries': 0, 'hours': 0.0},
            'Q4': {'months': [], 'entries': 0, 'hours': 0.0},
        }

        for month_key, month_data in monthly_summary.items():
            month_num = int(month_key.split('-')[1])
            quarter = f'Q{(month_num - 1) // 3 + 1}'

            quarters[quarter]['months'].append(month_key)
            quarters[quarter]['entries'] += month_data['total_entries']
            quarters[quarter]['hours'] += month_data['total_gpu_hours']

        # Create visualization
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))

        # Plot 1: Quarterly entries
        quarter_names = list(quarters.keys())
        quarter_entries = [quarters[q]['entries'] for q in quarter_names]
        quarter_hours = [quarters[q]['hours'] for q in quarter_names]

        x = np.arange(len(quarter_names))
        width = 0.35

        bars1a = ax1.bar(x - width / 2, quarter_entries, width, label='Entries', color='skyblue', alpha=0.7)
        bars1b = ax1.bar(x + width / 2, quarter_hours, width, label='GPU Hours', color='lightgreen', alpha=0.7)

        ax1.set_xlabel('Quarter')
        ax1.set_ylabel('Count')
        ax1.set_title('Quarterly Summary (1 Year)')
        ax1.set_xticks(x)
        ax1.set_xticklabels(quarter_names)
        ax1.legend()

        # Add value labels
        for bar in bars1a:
            height = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width() / 2.0, height + 0.1, f'{int(height)}', ha='center', va='bottom')

        for bar in bars1b:
            height = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width() / 2.0, height + 0.1, f'{height}h', ha='center', va='bottom')

        # Plot 2: Pie chart of quarterly distribution
        ax2.pie(quarter_hours, labels=quarter_names, autopct='%1.1f%%', startangle=90)
        ax2.set_title('GPU Hours Distribution by Quarter')

        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()

        _zyg_log.info(f'Generated {output_file}')

    def get_year_data(self, date: str = None) -> dict:
        self.schedule_data = self.load_schedule_data()  # Always reload
        """Get comprehensive 1-year data for web interface"""
        if date is None:
            date = datetime.datetime.now().strftime('%Y-%m-%d')

        return {
            'start_date': date,
            'monthly_summary': self.get_monthly_summary(date),
            'weekly_summary': self.get_weekly_summary(date),
            'model_usage': self.get_model_usage_summary(date),
            'total_entries': len(self.get_year_entries(date)),
            'year_range': self.get_year_range(date),
        }

    def get_year_range(self, start_date: str) -> List[str]:
        """Get list of dates for the 1-year period"""
        start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
        dates = []

        for i in range(365):
            current_date = start_dt + timedelta(days=i)
            dates.append(current_date.strftime('%Y-%m-%d'))

        return dates


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
    main()
