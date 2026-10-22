#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Dual Timeline Orchestrator Script for CrewAI Agent Schedule
Handles separate CPU and GPU schedule files
"""

import os
import sys
from typing import Dict

# Import all timeline modules
import importlib.util

# add_entry_timeline.py moved next to zyg_workflows in the monorepo split, so it is
# resolved from that package rather than from ../ next to zyg_dashboard.
import zyg_workflows as _zyg_workflows_pkg


# Import modules with numeric names
def import_module_from_file(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# Import timeline modules
current_dir = os.path.dirname(os.path.abspath(__file__))
timeline_24h_module = import_module_from_file('timeline_24h', os.path.join(current_dir, '24_hour_timeline.py'))
timeline_7d_module = import_module_from_file('timeline_7d', os.path.join(current_dir, '7_day_timeline.py'))
timeline_28d_module = import_module_from_file('timeline_28d', os.path.join(current_dir, '28_day_timeline.py'))
timeline_1y_module = import_module_from_file('timeline_1y', os.path.join(current_dir, '1_year_timeline.py'))
timeline_history_module = import_module_from_file('timeline_history', os.path.join(current_dir, 'history_timeline.py'))
add_entry_module = import_module_from_file(
    'add_entry', os.path.join(os.path.dirname(_zyg_workflows_pkg.__file__), 'add_entry_timeline.py')
)

Timeline24Hour = timeline_24h_module.Timeline24Hour
Timeline7Day = timeline_7d_module.Timeline7Day
Timeline28Day = timeline_28d_module.Timeline28Day
Timeline1Year = timeline_1y_module.Timeline1Year
TimelineHistory = timeline_history_module.TimelineHistory
AddEntryTimeline = add_entry_module.AddEntryTimeline


class DualTimelineOrchestrator:
    def __init__(
        self, cpu_schedule_file: str = 'schedule_data_CPU.json', gpu_schedule_file: str = 'schedule_data_GPU.json'
    ):
        # Convert to absolute paths if they're not already
        if not os.path.isabs(cpu_schedule_file):
            cpu_schedule_file = os.path.join(current_dir, cpu_schedule_file)
        if not os.path.isabs(gpu_schedule_file):
            gpu_schedule_file = os.path.join(current_dir, gpu_schedule_file)

        self.cpu_schedule_file = cpu_schedule_file
        self.gpu_schedule_file = gpu_schedule_file

        # Initialize CPU timeline modules
        self.cpu_timeline_24h = Timeline24Hour(cpu_schedule_file)
        self.cpu_timeline_7d = Timeline7Day(cpu_schedule_file)
        self.cpu_timeline_28d = Timeline28Day(cpu_schedule_file)
        self.cpu_timeline_1y = Timeline1Year(cpu_schedule_file)
        self.cpu_timeline_history = TimelineHistory(cpu_schedule_file)
        self.cpu_add_entry = AddEntryTimeline(cpu_schedule_file)

        # Initialize GPU timeline modules
        self.gpu_timeline_24h = Timeline24Hour(gpu_schedule_file)
        self.gpu_timeline_7d = Timeline7Day(gpu_schedule_file)
        self.gpu_timeline_28d = Timeline28Day(gpu_schedule_file)
        self.gpu_timeline_1y = Timeline1Year(gpu_schedule_file)
        self.gpu_timeline_history = TimelineHistory(gpu_schedule_file)
        self.gpu_add_entry = AddEntryTimeline(gpu_schedule_file)

        # Timeline mapping for CPU
        self.cpu_timeline_modules = {
            '24h': self.cpu_timeline_24h,
            '7d': self.cpu_timeline_7d,
            '28d': self.cpu_timeline_28d,
            '1y': self.cpu_timeline_1y,
            'history': self.cpu_timeline_history,
            'add_entry': self.cpu_add_entry,
        }

        # Timeline mapping for GPU
        self.gpu_timeline_modules = {
            '24h': self.gpu_timeline_24h,
            '7d': self.gpu_timeline_7d,
            '28d': self.gpu_timeline_28d,
            '1y': self.gpu_timeline_1y,
            'history': self.gpu_timeline_history,
            'add_entry': self.gpu_add_entry,
        }

    def get_cpu_timeline_data(self, timeline_type: str, **kwargs) -> Dict:
        """Get data for CPU timeline"""
        if timeline_type not in self.cpu_timeline_modules:
            return {'error': f'Unknown timeline type: {timeline_type}'}
        module = self.cpu_timeline_modules[timeline_type]
        try:
            if timeline_type == '24h':
                # PATCH REMOVED: Do not force a fixed date, allow dynamic date
                return module.get_timeline_data(**kwargs)
            elif timeline_type == '7d':
                return module.get_week_data(**kwargs)
            elif timeline_type == '28d':
                return module.get_month_data(**kwargs)
            elif timeline_type == '1y':
                return module.get_year_data(**kwargs)
            elif timeline_type == 'history':
                return module.get_history_data()
            elif timeline_type == 'add_entry':
                return module.get_entry_form_data(**kwargs)
        except Exception as e:
            return {'error': f'Error getting CPU {timeline_type} data: {str(e)}'}

    def get_gpu_timeline_data(self, timeline_type: str, **kwargs) -> Dict:
        """Get data for GPU timeline"""
        if timeline_type not in self.gpu_timeline_modules:
            return {'error': f'Unknown timeline type: {timeline_type}'}
        module = self.gpu_timeline_modules[timeline_type]
        try:
            if timeline_type == '24h':
                # PATCH REMOVED: Do not force a fixed date, allow dynamic date
                return module.get_timeline_data(**kwargs)
            elif timeline_type == '7d':
                return module.get_week_data(**kwargs)
            elif timeline_type == '28d':
                return module.get_month_data(**kwargs)
            elif timeline_type == '1y':
                return module.get_year_data(**kwargs)
            elif timeline_type == 'history':
                return module.get_history_data()
            elif timeline_type == 'add_entry':
                return module.get_entry_form_data(**kwargs)
        except Exception as e:
            return {'error': f'Error getting GPU {timeline_type} data: {str(e)}'}

    def add_cpu_schedule_entry(self, entry: Dict, date: str = None) -> Dict:
        """Add a new CPU schedule entry"""
        try:
            success, message = self.cpu_add_entry.add_schedule_entry(entry, date)
            return {'success': success, 'message': message, 'entry_id': entry.get('id') if success else None}
        except Exception as e:
            return {'success': False, 'message': f'Error adding CPU entry: {str(e)}', 'entry_id': None}

    def add_gpu_schedule_entry(self, entry: Dict, date: str = None) -> Dict:
        """Add a new GPU schedule entry"""
        try:
            success, message = self.gpu_add_entry.add_schedule_entry(entry, date)
            return {'success': success, 'message': message, 'entry_id': entry.get('id') if success else None}
        except Exception as e:
            return {'success': False, 'message': f'Error adding GPU entry: {str(e)}', 'entry_id': None}

    def generate_cpu_visualization(self, timeline_type: str, **kwargs) -> str:
        """Generate visualization for CPU timeline"""
        if timeline_type not in self.cpu_timeline_modules:
            return f'Unknown timeline type: {timeline_type}'

        module = self.cpu_timeline_modules[timeline_type]

        try:
            if timeline_type == '24h':
                output_file = kwargs.get('output_file', 'cpu_24_hour_timeline.png')
                module.generate_timeline_visualization(**kwargs)
            elif timeline_type == '7d':
                output_file = kwargs.get('output_file', 'cpu_7_day_timeline.png')
                module.generate_week_visualization(**kwargs)
                module.generate_model_usage_chart(**kwargs)
            elif timeline_type == '28d':
                output_file = kwargs.get('output_file', 'cpu_28_day_timeline.png')
                module.generate_month_visualization(**kwargs)
                module.generate_calendar_view(**kwargs)
            elif timeline_type == '1y':
                output_file = kwargs.get('output_file', 'cpu_1_year_timeline.png')
                module.generate_year_visualization(**kwargs)
                module.generate_quarterly_report(**kwargs)
            elif timeline_type == 'history':
                output_file = kwargs.get('output_file', 'cpu_history_timeline.png')
                module.generate_historical_visualization(**kwargs)
                module.generate_summary_report(**kwargs)

            return f'Generated {output_file}'
        except Exception as e:
            return f'Error generating CPU {timeline_type} visualization: {str(e)}'

    def generate_gpu_visualization(self, timeline_type: str, **kwargs) -> str:
        """Generate visualization for GPU timeline"""
        if timeline_type not in self.gpu_timeline_modules:
            return f'Unknown timeline type: {timeline_type}'

        module = self.gpu_timeline_modules[timeline_type]

        try:
            if timeline_type == '24h':
                output_file = kwargs.get('output_file', 'gpu_24_hour_timeline.png')
                module.generate_timeline_visualization(**kwargs)
            elif timeline_type == '7d':
                output_file = kwargs.get('output_file', 'gpu_7_day_timeline.png')
                module.generate_week_visualization(**kwargs)
                module.generate_model_usage_chart(**kwargs)
            elif timeline_type == '28d':
                output_file = kwargs.get('output_file', 'gpu_28_day_timeline.png')
                module.generate_month_visualization(**kwargs)
                module.generate_calendar_view(**kwargs)
            elif timeline_type == '1y':
                output_file = kwargs.get('output_file', 'gpu_1_year_timeline.png')
                module.generate_year_visualization(**kwargs)
                module.generate_quarterly_report(**kwargs)
            elif timeline_type == 'history':
                output_file = kwargs.get('output_file', 'gpu_history_timeline.png')
                module.generate_historical_visualization(**kwargs)
                module.generate_summary_report(**kwargs)

            return f'Generated {output_file}'
        except Exception as e:
            return f'Error generating GPU {timeline_type} visualization: {str(e)}'

    def get_combined_timeline_data(self, timeline_type: str, **kwargs) -> Dict:
        """Get combined data from both CPU and GPU timelines"""
        if timeline_type == '24h':
            # Use the most recent date with data, or today's date as fallback
            import datetime

            today = datetime.datetime.now().strftime('%Y-%m-%d')
            # Check if we have data for today, otherwise use a known date with data
            if today in self.cpu_timeline_24h.schedule_data or today in self.gpu_timeline_24h.schedule_data:
                kwargs['date'] = today
            else:
                # Use a date that we know has data
                kwargs['date'] = '2025-07-14'
        cpu_data = self.get_cpu_timeline_data(timeline_type, **kwargs)
        gpu_data = self.get_gpu_timeline_data(timeline_type, **kwargs)
        # Combine the data
        combined = {}
        if 'error' not in cpu_data:
            combined.update(cpu_data)
        if 'error' not in gpu_data:
            # Merge entries if they exist
            if 'entries' in combined and 'entries' in gpu_data:
                combined['entries'].extend(gpu_data['entries'])
            elif 'entries' in gpu_data:
                combined['entries'] = gpu_data['entries']
        return combined


if __name__ == '__main__':  # the CLI lives in timeline_orchestrator_dual_cli
    from zyg_dashboard.Schedule.timeline_orchestrator_dual_cli import main as _cli_main

    raise SystemExit(_cli_main())
