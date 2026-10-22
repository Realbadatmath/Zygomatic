#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
28-Day Timeline Script for CrewAI Agent Schedule
Manages and visualizes schedule data over a 28-day period (4 weeks)
"""

import json
import datetime
from typing import Dict, List
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
from datetime import timedelta
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


class Timeline28Day:
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

    def get_month_entries(self, start_date: str = None) -> List[Dict]:
        """Get all schedule entries for a 28-day period starting from start_date"""
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')

        start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
        entries = []

        for i in range(28):
            current_date = start_dt + timedelta(days=i)
            date_str = current_date.strftime('%Y-%m-%d')

            if date_str in self.schedule_data:
                day_entries = self.schedule_data[date_str]
                for entry in day_entries:
                    entry['date'] = date_str
                    entry['day_of_week'] = current_date.strftime('%A')
                    entry['week_number'] = (i // 7) + 1
                    entries.append(entry)

        return entries

    def get_weekly_summary(self, start_date: str = None) -> Dict:
        """Get a summary of schedule entries grouped by weeks"""
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')

        start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
        weekly_summary = {}

        for week in range(4):
            week_start = start_dt + timedelta(days=week * 7)
            week_entries = []
            week_dates = []

            for day in range(7):
                current_date = week_start + timedelta(days=day)
                date_str = current_date.strftime('%Y-%m-%d')
                week_dates.append(date_str)

                if date_str in self.schedule_data:
                    week_entries.extend(self.schedule_data[date_str])

            weekly_summary[f'Week {week + 1}'] = {
                'start_date': week_start.strftime('%Y-%m-%d'),
                'end_date': (week_start + timedelta(days=6)).strftime('%Y-%m-%d'),
                'entries': week_entries,
                'total_entries': len(week_entries),
                'dates': week_dates,
                'total_gpu_hours': self.calculate_week_gpu_hours(week_entries),
                'models_used': list(set([entry.get('ai_model') for entry in week_entries])),
            }

        return weekly_summary

    def calculate_week_gpu_hours(self, entries: List[Dict]) -> float:
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

    def get_daily_summary(self, start_date: str = None) -> Dict:
        """Get a summary of schedule entries for each day of the 28-day period"""
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')

        start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
        daily_summary = {}

        for i in range(28):
            current_date = start_dt + timedelta(days=i)
            date_str = current_date.strftime('%Y-%m-%d')
            day_name = current_date.strftime('%A')
            week_number = (i // 7) + 1

            daily_summary[date_str] = {
                'day_name': day_name,
                'date': date_str,
                'week_number': week_number,
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

    def generate_month_visualization(self, start_date: str = None, output_file: str = '28_day_timeline.png'):
        """Generate a 28-day timeline visualization"""
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')

        daily_summary = self.get_daily_summary(start_date)
        weekly_summary = self.get_weekly_summary(start_date)

        # Configuration
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))

        # Plot 1: Daily entry counts over 28 days
        dates = list(daily_summary.keys())
        entry_counts = [daily_summary[date]['total_entries'] for date in dates]

        ax1.bar(range(28), entry_counts, color='skyblue', alpha=0.7)
        ax1.set_xlabel('Day')
        ax1.set_ylabel('Number of Schedule Entries')
        ax1.set_title('28-Day Schedule Overview')
        ax1.set_xticks(range(0, 28, 7))
        ax1.set_xticklabels([f'Week {i + 1}' for i in range(4)])

        # Add week separators
        for i in range(1, 4):
            ax1.axvline(x=i * 7 - 0.5, color='red', linestyle='--', alpha=0.5)

        # Plot 2: Weekly summary
        weeks = list(weekly_summary.keys())
        week_entries = [weekly_summary[week]['total_entries'] for week in weeks]
        week_hours = [weekly_summary[week]['total_gpu_hours'] for week in weeks]

        x = np.arange(len(weeks))
        width = 0.35

        bars2a = ax2.bar(x - width / 2, week_entries, width, label='Entries', color='lightcoral', alpha=0.7)
        bars2b = ax2.bar(x + width / 2, week_hours, width, label='GPU Hours', color='lightgreen', alpha=0.7)

        ax2.set_xlabel('Week')
        ax2.set_ylabel('Count')
        ax2.set_title('Weekly Summary')
        ax2.set_xticks(x)
        ax2.set_xticklabels(weeks)
        ax2.legend()

        # Add value labels
        for bar in bars2a:
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width() / 2.0, height + 0.1, f'{int(height)}', ha='center', va='bottom')

        for bar in bars2b:
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width() / 2.0, height + 0.1, f'{height}h', ha='center', va='bottom')

        # Plot 3: GPU hours trend
        gpu_hours = [daily_summary[date]['total_gpu_hours'] for date in dates]
        ax3.plot(range(28), gpu_hours, marker='o', color='green', linewidth=2, markersize=4)
        ax3.set_xlabel('Day')
        ax3.set_ylabel('GPU Hours')
        ax3.set_title('GPU Usage Trend (28 Days)')
        ax3.set_xticks(range(0, 28, 7))
        ax3.set_xticklabels([f'Week {i + 1}' for i in range(4)])
        ax3.grid(True, alpha=0.3)

        # Add week separators
        for i in range(1, 4):
            ax3.axvline(x=i * 7 - 0.5, color='red', linestyle='--', alpha=0.5)

        # Plot 4: Model usage over 28 days
        model_usage = self.get_model_usage_summary(start_date)
        if model_usage:
            models = list(model_usage.keys())
            total_hours = [model_usage[model]['total_hours'] for model in models]

            # Sort by hours
            sorted_data = sorted(zip(models, total_hours), key=lambda x: x[1], reverse=True)
            models, total_hours = zip(*sorted_data[:10])  # Top 10 models

            bars4 = ax4.barh(range(len(models)), total_hours, color='lightblue', alpha=0.7)
            ax4.set_yticks(range(len(models)))
            ax4.set_yticklabels(models)
            ax4.set_xlabel('Total GPU Hours')
            ax4.set_title('Top 10 AI Models (28 Days)')

            # Add value labels
            for _i, (bar, hours) in enumerate(zip(bars4, total_hours)):
                ax4.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height() / 2, f'{hours}h', ha='left', va='center')

        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()

        _zyg_log.info(f'Generated {output_file}')

    def get_model_usage_summary(self, start_date: str = None) -> Dict:
        """Get summary of AI model usage over the 28-day period"""
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')

        entries = self.get_month_entries(start_date)
        model_usage = {}

        for entry in entries:
            model = entry.get('ai_model', 'Unknown')
            if model not in model_usage:
                model_usage[model] = {
                    'total_entries': 0,
                    'total_hours': 0.0,
                    'days_used': set(),
                    'weeks_used': set(),
                    'agents': set(),
                }

            model_usage[model]['total_entries'] += 1
            model_usage[model]['days_used'].add(entry.get('date'))
            model_usage[model]['weeks_used'].add(entry.get('week_number'))
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
            model_usage[model]['weeks_used'] = list(model_usage[model]['weeks_used'])
            model_usage[model]['agents'] = list(model_usage[model]['agents'])
            model_usage[model]['total_hours'] = round(model_usage[model]['total_hours'], 2)

        return model_usage

    def build_model_agent_mapping(self, start_date: str = None) -> dict:
        """Dynamically build model-to-agent count mapping from schedule data for the 28-day period."""
        import datetime

        mapping = {}
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')
        # Get all entries for the 28-day period
        entries = []
        for i in range(28):
            day = (datetime.datetime.strptime(start_date, '%Y-%m-%d') - datetime.timedelta(days=i)).strftime('%Y-%m-%d')
            entries.extend(self.schedule_data.get(day, []))
        for entry in entries:
            model = entry.get('ai_model')
            agent = entry.get('agent')
            if model and agent:
                mapping.setdefault(model, set()).add(agent)
        # Convert sets to counts
        return {model: len(agents) for model, agents in mapping.items()}

    def get_model_agent_mapping(self, start_date: str = None) -> dict:
        return self.build_model_agent_mapping(start_date)

    def generate_calendar_view(self, start_date: str = None, output_file: str = '28_day_calendar.png'):
        """Generate a calendar-style view of the 28-day period"""
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')

        daily_summary = self.get_daily_summary(start_date)

        # Create calendar grid
        fig, ax = plt.subplots(figsize=(14, 10))
        ax.set_xlim(0, 7)
        ax.set_ylim(0, 4)
        ax.axis('off')

        # Draw calendar grid
        for week in range(4):
            for day in range(7):
                x = day
                y = 3 - week  # Invert y-axis so week 1 is at top

                # Calculate date
                start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
                current_date = start_dt + timedelta(days=week * 7 + day)
                date_str = current_date.strftime('%Y-%m-%d')

                # Get day data
                day_data = daily_summary.get(date_str, {})
                entry_count = day_data.get('total_entries', 0)
                gpu_hours = day_data.get('total_gpu_hours', 0)

                # Color based on activity
                if entry_count > 0:
                    color = 'lightgreen' if gpu_hours > 8 else 'lightyellow'
                else:
                    color = 'lightgray'

                # Draw day box
                rect = patches.Rectangle((x, y), 1, 1, linewidth=1, edgecolor='black', facecolor=color)
                ax.add_patch(rect)

                # Add date
                day_num = current_date.day
                ax.text(x + 0.5, y + 0.8, f'{day_num}', ha='center', va='center', fontsize=12, fontweight='bold')

                # Add entry count
                if entry_count > 0:
                    ax.text(x + 0.5, y + 0.5, f'{entry_count} entries', ha='center', va='center', fontsize=8)
                    ax.text(x + 0.5, y + 0.2, f'{gpu_hours}h', ha='center', va='center', fontsize=8)

        # Add day labels
        day_labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        for i, label in enumerate(day_labels):
            ax.text(i + 0.5, 4.1, label, ha='center', va='center', fontsize=10, fontweight='bold')

        # Add week labels
        for i in range(4):
            ax.text(-0.5, 3 - i + 0.5, f'Week {i + 1}', ha='center', va='center', fontsize=10, fontweight='bold')

        plt.title(f'28-Day Calendar View - Starting {start_date}', fontsize=14)
        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()

        _zyg_log.info(f'Generated {output_file}')

    def get_month_data(self, date: str = None) -> dict:
        self.schedule_data = self.load_schedule_data()  # Always reload
        start_date = date
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')

        return {
            'start_date': start_date,
            'daily_summary': self.get_daily_summary(start_date),
            'weekly_summary': self.get_weekly_summary(start_date),
            'model_usage': self.get_model_usage_summary(start_date),
            'total_entries': len(self.get_month_entries(start_date)),
            'month_range': self.get_month_range(start_date),
        }

    def get_month_range(self, start_date: str) -> List[str]:
        """Get list of dates for the 28-day period"""
        start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
        dates = []

        for i in range(28):
            current_date = start_dt + timedelta(days=i)
            dates.append(current_date.strftime('%Y-%m-%d'))

        return dates


if __name__ == '__main__':  # the CLI lives in 28_day_timeline_cli
    import importlib

    # Digit-leading module names cannot be spelled in an import statement.
    raise SystemExit(importlib.import_module('zyg_dashboard.Schedule.28_day_timeline_cli').main())
