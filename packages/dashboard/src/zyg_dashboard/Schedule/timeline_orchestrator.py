#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Timeline Orchestrator Script for CrewAI Agent Schedule
Main controller that manages all timeline functionality
"""

import datetime
import importlib.util
import json
import logging as _zyg_logging
import os
import sys
from typing import Dict, List

try:
    from zoneinfo import ZoneInfo

    _AMS_TZ = ZoneInfo('Europe/Amsterdam')
except Exception:
    _AMS_TZ = None

_zyg_log = _zyg_logging.getLogger(__name__)


def _ams_now() -> datetime.datetime:
    if _AMS_TZ is not None:
        try:
            return datetime.datetime.now(_AMS_TZ)
        except Exception as _exc:
            _zyg_log.warning('Amsterdam timezone clock read failed, continuing in UTC: %s', _exc)
    return datetime.datetime.now(datetime.timezone.utc)


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
add_entry_module = import_module_from_file('add_entry', os.path.join(current_dir, 'add_entry_timeline.py'))

Timeline24Hour = timeline_24h_module.Timeline24Hour
Timeline7Day = timeline_7d_module.Timeline7Day
Timeline28Day = timeline_28d_module.Timeline28Day
Timeline1Year = timeline_1y_module.Timeline1Year
TimelineHistory = timeline_history_module.TimelineHistory
AddEntryTimeline = add_entry_module.AddEntryTimeline


class TimelineOrchestrator:
    def __init__(self, schedule_file: str = 'schedule_data_ACTIVE.json'):
        self.schedule_file = schedule_file

        # Initialize all timeline modules
        self.timeline_24h = Timeline24Hour(schedule_file)
        self.timeline_7d = Timeline7Day(schedule_file)
        self.timeline_28d = Timeline28Day(schedule_file)
        self.timeline_1y = Timeline1Year(schedule_file)
        self.timeline_history = TimelineHistory(schedule_file)
        self.add_entry = AddEntryTimeline(schedule_file)

        # Timeline mapping
        self.timeline_modules = {
            '24h': self.timeline_24h,
            '7d': self.timeline_7d,
            '28d': self.timeline_28d,
            '1y': self.timeline_1y,
            'history': self.timeline_history,
            'add_entry': self.add_entry,
        }

    def get_timeline_data(self, timeline_type: str, **kwargs) -> Dict:
        """Get data for a specific timeline type"""
        if timeline_type not in self.timeline_modules:
            return {'error': f'Unknown timeline type: {timeline_type}'}

        module = self.timeline_modules[timeline_type]

        try:
            if timeline_type == '24h':
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
            return {'error': f'Error getting {timeline_type} data: {str(e)}'}

    def generate_visualization(self, timeline_type: str, **kwargs) -> str:
        """Generate visualization for a specific timeline type"""
        if timeline_type not in self.timeline_modules:
            return f'Unknown timeline type: {timeline_type}'

        module = self.timeline_modules[timeline_type]

        try:
            if timeline_type == '24h':
                output_file = kwargs.get('output_file', '24_hour_timeline.png')
                module.generate_timeline_visualization(**kwargs)
            elif timeline_type == '7d':
                output_file = kwargs.get('output_file', '7_day_timeline.png')
                module.generate_week_visualization(**kwargs)
                module.generate_model_usage_chart(**kwargs)
            elif timeline_type == '28d':
                output_file = kwargs.get('output_file', '28_day_timeline.png')
                module.generate_month_visualization(**kwargs)
                module.generate_calendar_view(**kwargs)
            elif timeline_type == '1y':
                output_file = kwargs.get('output_file', '1_year_timeline.png')
                module.generate_year_visualization(**kwargs)
                module.generate_quarterly_report(**kwargs)
            elif timeline_type == 'history':
                output_file = kwargs.get('output_file', 'history_timeline.png')
                module.generate_historical_visualization(**kwargs)
                module.generate_summary_report(**kwargs)

            return f'Generated {output_file}'
        except Exception as e:
            return f'Error generating {timeline_type} visualization: {str(e)}'

    def add_schedule_entry(self, entry: Dict, date: str = None) -> Dict:
        """Add a new schedule entry using the add_entry module"""
        try:
            success, message = self.add_entry.add_schedule_entry(entry, date)
            return {'success': success, 'message': message, 'entry_id': entry.get('id') if success else None}
        except Exception as e:
            return {'success': False, 'message': f'Error adding entry: {str(e)}', 'entry_id': None}

    def edit_schedule_entry(self, entry_id: str, updated_entry: Dict, date: str = None) -> Dict:
        """Edit an existing schedule entry"""
        try:
            success, message = self.add_entry.edit_schedule_entry(entry_id, updated_entry, date)
            return {'success': success, 'message': message}
        except Exception as e:
            return {'success': False, 'message': f'Error editing entry: {str(e)}'}

    def delete_schedule_entry(self, entry_id: str, date: str = None) -> Dict:
        """Delete a schedule entry"""
        try:
            success, message = self.add_entry.delete_schedule_entry(entry_id, date)
            return {'success': success, 'message': message}
        except Exception as e:
            return {'success': False, 'message': f'Error deleting entry: {str(e)}'}

    def validate_entry(self, entry: Dict) -> Dict:
        """Validate a schedule entry"""
        try:
            is_valid, message = self.add_entry.validate_schedule_entry(entry)
            return {'valid': is_valid, 'message': message}
        except Exception as e:
            return {'valid': False, 'message': f'Error validating entry: {str(e)}'}

    def get_available_models(self) -> List[str]:
        """Get list of available AI models"""
        return self.add_entry.get_available_models()

    def get_model_agent_count(self, model: str) -> int:
        """Get the number of agents that can use a specific model"""
        return self.add_entry.get_model_agent_count(model)

    def get_available_time_slots(self, model: str, date: str = None) -> List[Dict]:
        """Get available time slots for a specific model"""
        return self.add_entry.get_available_time_slots(model, date)

    def generate_all_visualizations(self, output_dir: str = '.') -> Dict:
        """Generate all timeline visualizations"""
        results = {}

        for timeline_type in ['24h', '7d', '28d', '1y', 'history']:
            try:
                output_file = os.path.join(output_dir, f'{timeline_type}_timeline.png')
                result = self.generate_visualization(timeline_type, output_file=output_file)
                results[timeline_type] = result
            except Exception as e:
                results[timeline_type] = f'Error: {str(e)}'

        return results

    def get_comprehensive_summary(self) -> Dict:
        """Get a comprehensive summary of all timeline data"""
        summary = {
            'current_date': _ams_now().strftime('%Y-%m-%d'),
            '24h_summary': self.timeline_24h.get_timeline_data(),
            '7d_summary': self.timeline_7d.get_week_data(),
            '28d_summary': self.timeline_28d.get_month_data(),
            '1y_summary': self.timeline_1y.get_year_data(),
            'history_summary': self.timeline_history.get_historical_summary(),
            'available_models': self.get_available_models(),
            'model_agent_counts': self.add_entry.model_agent_mapping,
        }

        return summary

    def export_schedule_data(self, output_file: str = 'exported_schedule.json') -> str:
        """Export all schedule data to a JSON file"""
        try:
            with open(self.schedule_file, 'r') as f:
                schedule_data = json.load(f)

            export_data = {
                'export_date': _ams_now().isoformat(timespec='milliseconds'),
                'schedule_data': schedule_data,
                'summary': self.get_comprehensive_summary(),
            }

            with open(output_file, 'w') as f:
                json.dump(export_data, f, indent=2)

            return f'Exported schedule data to {output_file}'
        except Exception as e:
            return f'Error exporting data: {str(e)}'

    def import_schedule_data(self, import_file: str) -> str:
        """Import schedule data from a JSON file"""
        try:
            with open(import_file, 'r') as f:
                import_data = json.load(f)

            if 'schedule_data' in import_data:
                schedule_data = import_data['schedule_data']
            else:
                schedule_data = import_data

            # Validate the imported data
            if not isinstance(schedule_data, dict):
                return 'Invalid import file format'

            # Backup current data
            backup_file = f'backup_{_ams_now().strftime("%Y%m%d_%H%M%S")}.json'
            with open(backup_file, 'w') as f:
                json.dump(self.timeline_24h.schedule_data, f, indent=2)

            # Import new data
            with open(self.schedule_file, 'w') as f:
                json.dump(schedule_data, f, indent=2)

            # Reload all modules
            self.__init__(self.schedule_file)

            return f'Imported schedule data from {import_file}. Backup saved as {backup_file}'
        except Exception as e:
            return f'Error importing data: {str(e)}'


def main():
    """Main function for testing the orchestrator"""
    orchestrator = TimelineOrchestrator()

    print('=== CrewAI Timeline Orchestrator ===')
    print(f'Current date: {_ams_now().strftime("%Y-%m-%d")}')

    # Test getting data for each timeline
    print('\n1. Testing timeline data retrieval:')
    for timeline_type in ['24h', '7d', '28d', '1y', 'history', 'add_entry']:
        data = orchestrator.get_timeline_data(timeline_type)
        if 'error' not in data:
            print(f'  ✓ {timeline_type}: Data retrieved successfully')
        else:
            print(f'  ✗ {timeline_type}: {data["error"]}')

    # Test adding a sample entry
    print('\n2. Testing entry addition:')
    sample_entry = orchestrator.add_entry.create_sample_entry('Claude_3')
    result = orchestrator.add_schedule_entry(sample_entry)
    print(f'  Add entry result: {result}')

    # Test validation
    print('\n3. Testing entry validation:')
    validation_result = orchestrator.validate_entry(sample_entry)
    print(f'  Validation result: {validation_result}')

    # Test available models
    print('\n4. Available AI models:')
    models = orchestrator.get_available_models()
    for model in models[:5]:  # Show first 5
        count = orchestrator.get_model_agent_count(model)
        print(f'  {model}: {count} agents')

    # Generate comprehensive summary
    print('\n5. Generating comprehensive summary:')
    summary = orchestrator.get_comprehensive_summary()
    print(f'  Summary generated with {len(summary)} sections')

    # Export data
    print('\n6. Testing data export:')
    export_result = orchestrator.export_schedule_data('test_export.json')
    print(f'  {export_result}')

    print('\n=== Orchestrator test completed ===')


if __name__ == '__main__':
    main()
