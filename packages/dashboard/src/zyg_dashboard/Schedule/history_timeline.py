#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
History Timeline Script for CrewAI Agent Schedule
Manages and visualizes historical schedule data
"""

import json
import datetime
from typing import Dict, List
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


class TimelineHistory:
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

    def get_all_historical_entries(self) -> List[Dict]:
        """Get all historical schedule entries"""
        all_entries = []
        today = datetime.datetime.now().date()

        for date_str, entries in self.schedule_data.items():
            try:
                entry_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                if entry_date < today:  # Only historical entries
                    for entry in entries:
                        entry['date'] = date_str
                        entry['day_of_week'] = entry_date.strftime('%A')
                        entry['month'] = entry_date.month
                        entry['month_name'] = entry_date.strftime('%B')
                        entry['year'] = entry_date.year
                        entry['week_of_year'] = entry_date.isocalendar()[1]
                        all_entries.append(entry)
            except ValueError as _exc:
                _zyg_log.debug('skipping schedule bucket with unparseable date key: %s', _exc)
                continue

        return all_entries

    def get_historical_summary(self) -> Dict:
        """Get a comprehensive summary of all historical data"""
        entries = self.get_all_historical_entries()

        if not entries:
            return {
                'total_entries': 0,
                'total_days': 0,
                'total_gpu_hours': 0.0,
                'date_range': {'start': None, 'end': None},
                'models_used': [],
                'agents_used': [],
                'monthly_breakdown': {},
                'yearly_breakdown': {},
            }

        # Basic statistics
        total_entries = len(entries)
        unique_dates = set(entry['date'] for entry in entries)
        total_days = len(unique_dates)

        # Date range
        dates = sorted(unique_dates)
        date_range = {'start': dates[0], 'end': dates[-1]}

        # Calculate total GPU hours
        total_gpu_hours = 0.0
        for entry in entries:
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
                total_gpu_hours += duration

            except (ValueError, AttributeError) as _exc:
                _zyg_log.debug('skipping entry with unparseable time range in gpu hours: %s', _exc)
                continue

        # Models and agents used
        models_used = list(set(entry.get('ai_model') for entry in entries if entry.get('ai_model')))
        agents_used = list(set(entry.get('agent') for entry in entries if entry.get('agent')))

        # Monthly breakdown
        monthly_breakdown = defaultdict(lambda: {'entries': 0, 'gpu_hours': 0.0, 'models': set(), 'agents': set()})

        for entry in entries:
            month_key = f'{entry["year"]}-{entry["month"]:02d}'
            monthly_breakdown[month_key]['entries'] += 1

            if entry.get('ai_model'):
                monthly_breakdown[month_key]['models'].add(entry.get('ai_model'))
            if entry.get('agent'):
                monthly_breakdown[month_key]['agents'].add(entry.get('agent'))

            # Calculate hours for this entry
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
                monthly_breakdown[month_key]['gpu_hours'] += duration

            except (ValueError, AttributeError) as _exc:
                _zyg_log.debug('skipping entry with unparseable time range in monthly breakdown: %s', _exc)
                continue

        # Convert sets to lists
        for month_key in monthly_breakdown:
            monthly_breakdown[month_key]['models'] = list(monthly_breakdown[month_key]['models'])
            monthly_breakdown[month_key]['agents'] = list(monthly_breakdown[month_key]['agents'])
            monthly_breakdown[month_key]['gpu_hours'] = round(monthly_breakdown[month_key]['gpu_hours'], 2)

        # Yearly breakdown
        yearly_breakdown = defaultdict(
            lambda: {'entries': 0, 'gpu_hours': 0.0, 'months': set(), 'models': set(), 'agents': set()}
        )

        for entry in entries:
            year_key = str(entry['year'])
            yearly_breakdown[year_key]['entries'] += 1
            yearly_breakdown[year_key]['months'].add(entry['month'])

            if entry.get('ai_model'):
                yearly_breakdown[year_key]['models'].add(entry.get('ai_model'))
            if entry.get('agent'):
                yearly_breakdown[year_key]['agents'].add(entry.get('agent'))

            # Calculate hours for this entry
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
                yearly_breakdown[year_key]['gpu_hours'] += duration

            except (ValueError, AttributeError) as _exc:
                _zyg_log.debug('skipping entry with unparseable time range in yearly breakdown: %s', _exc)
                continue

        # Convert sets to lists
        for year_key in yearly_breakdown:
            yearly_breakdown[year_key]['months'] = list(yearly_breakdown[year_key]['months'])
            yearly_breakdown[year_key]['models'] = list(yearly_breakdown[year_key]['models'])
            yearly_breakdown[year_key]['agents'] = list(yearly_breakdown[year_key]['agents'])
            yearly_breakdown[year_key]['gpu_hours'] = round(yearly_breakdown[year_key]['gpu_hours'], 2)

        return {
            'total_entries': total_entries,
            'total_days': total_days,
            'total_gpu_hours': round(total_gpu_hours, 2),
            'date_range': date_range,
            'models_used': models_used,
            'agents_used': agents_used,
            'monthly_breakdown': dict(monthly_breakdown),
            'yearly_breakdown': dict(yearly_breakdown),
        }

    def generate_historical_visualization(self, output_file: str = 'history_timeline.png'):
        """Generate a comprehensive historical timeline visualization"""
        summary = self.get_historical_summary()

        if summary['total_entries'] == 0:
            _zyg_log.info('No historical data found')
            return

        # Configuration
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(20, 16))

        # Plot 1: Monthly activity over time
        monthly_data = summary['monthly_breakdown']
        months = sorted(monthly_data.keys())
        entries_per_month = [monthly_data[month]['entries'] for month in months]
        hours_per_month = [monthly_data[month]['gpu_hours'] for month in months]

        x = np.arange(len(months))
        width = 0.35

        ax1.bar(x - width / 2, entries_per_month, width, label='Entries', color='skyblue', alpha=0.7)
        ax1.bar(x + width / 2, hours_per_month, width, label='GPU Hours', color='lightgreen', alpha=0.7)

        ax1.set_xlabel('Month')
        ax1.set_ylabel('Count')
        ax1.set_title('Historical Activity by Month')
        ax1.set_xticks(x[::3])  # Show every 3rd month label
        ax1.set_xticklabels([month for month in months[::3]], rotation=45)
        ax1.legend()

        # Plot 2: Yearly summary
        yearly_data = summary['yearly_breakdown']
        years = sorted(yearly_data.keys())
        entries_per_year = [yearly_data[year]['entries'] for year in years]
        hours_per_year = [yearly_data[year]['gpu_hours'] for year in years]

        x2 = np.arange(len(years))
        bars2a = ax2.bar(x2 - width / 2, entries_per_year, width, label='Entries', color='lightcoral', alpha=0.7)
        bars2b = ax2.bar(x2 + width / 2, hours_per_year, width, label='GPU Hours', color='lightblue', alpha=0.7)

        ax2.set_xlabel('Year')
        ax2.set_ylabel('Count')
        ax2.set_title('Historical Activity by Year')
        ax2.set_xticks(x2)
        ax2.set_xticklabels(years)
        ax2.legend()

        # Add value labels
        for bar in bars2a:
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width() / 2.0, height + 0.1, f'{int(height)}', ha='center', va='bottom')

        for bar in bars2b:
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width() / 2.0, height + 0.1, f'{height}h', ha='center', va='bottom')

        # Plot 3: Model usage over time
        model_usage = self.get_model_usage_history()
        if model_usage:
            models = list(model_usage.keys())
            total_hours = [model_usage[model]['total_hours'] for model in models]

            # Sort by hours and take top 15
            sorted_data = sorted(zip(models, total_hours), key=lambda x: x[1], reverse=True)
            models, total_hours = zip(*sorted_data[:15])

            bars3 = ax3.barh(range(len(models)), total_hours, color='gold', alpha=0.7)
            ax3.set_yticks(range(len(models)))
            ax3.set_yticklabels(models)
            ax3.set_xlabel('Total GPU Hours')
            ax3.set_title('Historical AI Model Usage (Top 15)')

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

        # Plot 4: Activity timeline
        entries = self.get_all_historical_entries()
        if entries:
            dates = [entry['date'] for entry in entries]
            date_counts = defaultdict(int)
            for date in dates:
                date_counts[date] += 1

            sorted_dates = sorted(date_counts.keys())
            activity_counts = [date_counts[date] for date in sorted_dates]

            ax4.plot(
                range(len(sorted_dates)),
                activity_counts,
                marker='o',
                color='purple',
                linewidth=1,
                markersize=2,
                alpha=0.7,
            )
            ax4.set_xlabel('Time')
            ax4.set_ylabel('Entries per Day')
            ax4.set_title('Historical Activity Timeline')
            ax4.set_xticks(range(0, len(sorted_dates), len(sorted_dates) // 10))
            ax4.set_xticklabels(
                [sorted_dates[i] for i in range(0, len(sorted_dates), len(sorted_dates) // 10)], rotation=45
            )
            ax4.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()

        _zyg_log.info(f'Generated {output_file}')

    def get_model_usage_history(self) -> Dict:
        """Get historical AI model usage summary"""
        entries = self.get_all_historical_entries()
        model_usage = {}

        for entry in entries:
            model = entry.get('ai_model', 'Unknown')
            if model not in model_usage:
                model_usage[model] = {
                    'total_entries': 0,
                    'total_hours': 0.0,
                    'days_used': set(),
                    'months_used': set(),
                    'years_used': set(),
                    'agents': set(),
                }

            model_usage[model]['total_entries'] += 1
            model_usage[model]['days_used'].add(entry.get('date'))
            model_usage[model]['months_used'].add(entry.get('month'))
            model_usage[model]['years_used'].add(entry.get('year'))
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
            model_usage[model]['years_used'] = list(model_usage[model]['years_used'])
            model_usage[model]['agents'] = list(model_usage[model]['agents'])
            model_usage[model]['total_hours'] = round(model_usage[model]['total_hours'], 2)

        return model_usage

    def generate_summary_report(self, output_file: str = 'history_summary_report.txt'):
        """Generate a text summary report of historical data"""
        summary = self.get_historical_summary()

        with open(output_file, 'w') as f:
            f.write('CrewAI Agent Schedule - Historical Summary Report\n')
            f.write('=' * 50 + '\n\n')

            f.write(f'Total Schedule Entries: {summary["total_entries"]}\n')
            f.write(f'Total Days with Activity: {summary["total_days"]}\n')
            f.write(f'Total GPU Hours: {summary["total_gpu_hours"]}\n')
            f.write(f'Date Range: {summary["date_range"]["start"]} to {summary["date_range"]["end"]}\n\n')

            f.write(f'AI Models Used: {len(summary["models_used"])}\n')
            f.write(f'Agents Used: {len(summary["agents_used"])}\n\n')

            f.write('Monthly Breakdown:\n')
            f.write('-' * 20 + '\n')
            for month, data in sorted(summary['monthly_breakdown'].items()):
                f.write(f'{month}: {data["entries"]} entries, {data["gpu_hours"]} GPU hours\n')

            f.write('\nYearly Breakdown:\n')
            f.write('-' * 20 + '\n')
            for year, data in sorted(summary['yearly_breakdown'].items()):
                f.write(f'{year}: {data["entries"]} entries, {data["gpu_hours"]} GPU hours\n')

            f.write('\nTop AI Models by Usage:\n')
            f.write('-' * 20 + '\n')
            model_usage = self.get_model_usage_history()
            sorted_models = sorted(model_usage.items(), key=lambda x: x[1]['total_hours'], reverse=True)

            for i, (model, data) in enumerate(sorted_models[:10], 1):
                f.write(f'{i}. {model}: {data["total_hours"]} hours ({data["total_entries"]} entries)\n')

        _zyg_log.info(f'Generated {output_file}')

    def get_history_data(self) -> Dict:
        """Get comprehensive historical data for web interface"""
        self.schedule_data = self.load_schedule_data()  # Always reload
        return {
            'summary': self.get_historical_summary(),
            'model_usage': self.get_model_usage_history(),
            'all_entries': self.get_all_historical_entries(),
        }


if __name__ == '__main__':  # the CLI lives in history_timeline_cli
    from zyg_dashboard.Schedule.history_timeline_cli import main as _cli_main

    raise SystemExit(_cli_main())
