#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Add Entry Timeline Script for CrewAI Agent Schedule
Manages adding, editing, and validating schedule entries
"""

import json
import os
import datetime
import uuid
from typing import Dict, List, Tuple
from datetime import timedelta
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


class AddEntryTimeline:
    def __init__(self, schedule_file: str = 'schedule_data_ACTIVE.json'):
        self.schedule_file = schedule_file
        self.schedule_data = self.load_schedule_data()
        # Canonical model names from ai_model_agent_mapping.py
        self.canonical_model_names = [
            'Stable Diffusion 1.5 Xl',
            'Dreamshaper Realisticvision',
            'Animatediff',
            'Stable Video Diffusion',
            'Controlnet',
            'Realesrgan',
            'Bark',
            'Tortoise Tts',
            'Blender (Bpy)',
            'Kandinsky 2.2',
            'Deforum',
            'Comfyui',
            'Dreambooth',
            'Lora',
            'Vae',
            'Davinci Resolve',
            'ffmpeg',
            'Pydub',
            'Clip',
            'Claude 3',
            'GPT-4',
            'LLaMA 3',
            'Mistral Mixtral',
            'HumanEval',
            'Crewai Openagents',
            'Langchain Llamalend',
            'Plotly',
            'Fastapi',
            'Ai Qc Engine',
            'Whisper',
            'librosa',
            'Assemblyai',
            'Deepgram',
        ]
        # Unified mapping (all canonical names)
        self.model_agent_mapping = {
            name: 4 for name in self.canonical_model_names
        }  # Use 4 as default, adjust as needed

    def normalize_model_name(self, name: str) -> str:
        """Normalize model name to canonical form."""
        if not name:
            return name
        # Lowercase, remove underscores, dashes, extra spaces, etc.
        name = name.replace('_', ' ').replace('-', ' ').replace('  ', ' ').strip().title()
        # Special cases
        replacements = {
            'Stable Diffusion 1.5 Xl': 'Stable Diffusion 1.5 Xl',
            'Dreamshaper Realisticvision': 'Dreamshaper Realisticvision',
            'Animatediff': 'Animatediff',
            'Stable Video Diffusion': 'Stable Video Diffusion',
            'Controlnet': 'Controlnet',
            'Realesrgan': 'Realesrgan',
            'Bark': 'Bark',
            'Tortoise Tts': 'Tortoise Tts',
            'Blender (Bpy)': 'Blender (Bpy)',
            'Kandinsky 2.2': 'Kandinsky 2.2',
            'Deforum': 'Deforum',
            'Comfyui': 'Comfyui',
            'Dreambooth': 'Dreambooth',
            'Lora': 'Lora',
            'Vae': 'Vae',
            'Davinci Resolve': 'Davinci Resolve',
            'Ffmpeg': 'Ffmpeg',
            'Pydub': 'Pydub',
            'Clip': 'Clip',
            'Claude 3': 'Claude 3',
            'Gpt-4': 'Gpt-4',
            'Llama 3': 'Llama 3',
            'Mistral Mixtral': 'Mistral Mixtral',
            'Humaneval': 'Humaneval',
            'Crewai Openagents': 'Crewai Openagents',
            'Langchain Llamalend': 'Langchain Llamalend',
            'Plotly': 'Plotly',
            'Fastapi': 'Fastapi',
            'Ai Qc Engine': 'Ai Qc Engine',
            'Whisper': 'Whisper',
            'Librosa': 'Librosa',
            'Assemblyai': 'Assemblyai',
            'Deepgram': 'Deepgram',
        }
        return replacements.get(name, name)

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
        abs_path = os.path.abspath(self.schedule_file)
        _zyg_log.warning(f'[DEBUG] Saving schedule data to: {abs_path}')
        with open(self.schedule_file, 'w') as f:
            json.dump(self.schedule_data, f, indent=2)

    def validate_schedule_entry(self, entry: Dict) -> Tuple[bool, str]:
        """Validate a schedule entry"""
        _zyg_log.warning(f'[DEBUG] validate_schedule_entry called with entry: {entry}')

        # Determine if this is a CPU or GPU entry
        if 'cpu_percent' in entry:
            required_fields = ['ai_model', 'start_time', 'end_time', 'cpu_percent']
            _zyg_log.warning(f'[DEBUG] CPU entry detected, required fields: {required_fields}')
        elif 'gpu_percent' in entry:
            required_fields = ['ai_model', 'start_time', 'end_time', 'gpu_percent']
            _zyg_log.warning(f'[DEBUG] GPU entry detected, required fields: {required_fields}')
        else:
            _zyg_log.warning('[DEBUG] Neither cpu_percent nor gpu_percent found in entry')
            return False, 'Missing required field: cpu_percent or gpu_percent'
        # Check required fields
        _zyg_log.warning(f'[DEBUG] Checking required fields: {required_fields}')
        for field in required_fields:
            _zyg_log.warning(f'[DEBUG] Checking field "{field}": value="{entry.get(field)}"')
            if field not in entry or not entry[field]:
                _zyg_log.warning(f'[DEBUG] Field "{field}" is missing or empty')
                return False, f'Missing required field: {field}'
        _zyg_log.warning('[DEBUG] All required fields present')
        # Validate AI model
        if 'gpu_percent' in entry:
            import os
            import json

            gpu_models_path = os.path.join(os.path.dirname(__file__), 'gpu_ai_models.json')
            _zyg_log.warning(f'[DEBUG] Loading GPU models from: {gpu_models_path}')
            _zyg_log.warning(f'[DEBUG] Current working directory: {os.getcwd()}')
            _zyg_log.warning(f'[DEBUG] File exists: {os.path.exists(gpu_models_path)}')
            try:
                with open(gpu_models_path, 'r', encoding='utf-8') as f:
                    gpu_models = json.load(f)
                _zyg_log.warning(f'[DEBUG] Loaded GPU models: {list(gpu_models.keys())}')
                _zyg_log.warning(f'[DEBUG] Checking model ID: {entry["ai_model"]} (type: {type(entry["ai_model"])})')
                _zyg_log.warning(f'[DEBUG] Model ID as string: "{str(entry["ai_model"])}"')
                _zyg_log.warning(f'[DEBUG] Model ID in gpu_models: {str(entry["ai_model"]) in gpu_models}')
                if str(entry['ai_model']) not in gpu_models:
                    _zyg_log.warning(f'[DEBUG] Model ID {entry["ai_model"]} not found in GPU models')
                    return False, f'Invalid AI model: {entry["ai_model"]}'
                else:
                    _zyg_log.warning(f'[DEBUG] Model ID {entry["ai_model"]} found in GPU models')
            except Exception as e:
                _zyg_log.warning(f'[DEBUG] Error loading GPU models: {e}')
                return False, f'Error loading GPU models: {e}'
        else:
            # CPU entry - validate against CPU model IDs
            import os
            import json

            cpu_models_path = os.path.join(os.path.dirname(__file__), 'cpu_ai_models.json')
            _zyg_log.warning(f'[DEBUG] Loading CPU models from: {cpu_models_path}')
            _zyg_log.warning(f'[DEBUG] Current working directory: {os.getcwd()}')
            _zyg_log.warning(f'[DEBUG] File exists: {os.path.exists(cpu_models_path)}')
            try:
                with open(cpu_models_path, 'r', encoding='utf-8') as f:
                    cpu_models = json.load(f)
                _zyg_log.warning(f'[DEBUG] Loaded CPU models: {list(cpu_models.keys())}')
                _zyg_log.warning(f'[DEBUG] Checking model ID: {entry["ai_model"]} (type: {type(entry["ai_model"])})')
                _zyg_log.warning(f'[DEBUG] Model ID as string: "{str(entry["ai_model"])}"')
                _zyg_log.warning(f'[DEBUG] Model ID in cpu_models: {str(entry["ai_model"]) in cpu_models}')
                if str(entry['ai_model']) not in cpu_models:
                    _zyg_log.warning(f'[DEBUG] Model ID {entry["ai_model"]} not found in CPU models')
                    return False, f'Invalid AI model: {entry["ai_model"]}'
                else:
                    _zyg_log.warning(f'[DEBUG] Model ID {entry["ai_model"]} found in CPU models')
            except Exception as e:
                _zyg_log.warning(f'[DEBUG] Error loading CPU models: {e}')
                return False, f'Error loading CPU models: {e}'
        # Validate times
        try:
            start_hour, start_minute = map(int, entry['start_time'].split(':'))
            end_hour, end_minute = map(int, entry['end_time'].split(':'))
            if not (0 <= start_hour <= 23 and 0 <= start_minute <= 59):
                return False, 'Invalid start time (use HH:MM format)'
            if not (0 <= end_hour <= 23 and 0 <= end_minute <= 59):
                return False, 'Invalid end time (use HH:MM format)'
        except ValueError:
            return False, 'Invalid time format (use HH:MM)'
        # Validate percent
        if 'cpu_percent' in entry:
            try:
                cpu_percent = float(entry['cpu_percent'])
                if not (0 < cpu_percent <= 100):
                    return False, 'CPU percent must be between 0 and 100'
            except ValueError:
                return False, 'Invalid CPU percent'
        if 'gpu_percent' in entry:
            try:
                gpu_percent = float(entry['gpu_percent'])
                if not (0 < gpu_percent <= 100):
                    return False, 'GPU percent must be between 0 and 100'
            except ValueError:
                return False, 'Invalid GPU percent'
        # Validate memory fraction
        if 'memory_fraction' in entry:
            try:
                memory_fraction = float(entry['memory_fraction'])
                if not (0 < memory_fraction <= 1):
                    return False, 'Memory fraction must be between 0 and 1'
            except ValueError:
                return False, 'Invalid memory fraction'
        # Check for conflicts
        conflict_check = self.check_schedule_conflicts(entry)
        if conflict_check[0]:
            return False, f'Schedule conflict: {conflict_check[1]}'
        return True, 'Valid entry'

    def check_schedule_conflicts(self, entry: Dict) -> Tuple[bool, str]:
        """Check for schedule conflicts with existing entries (only if same ai_model, agent, and bar_id)"""
        date = entry.get('date', datetime.datetime.now().strftime('%Y-%m-%d'))
        ai_model = entry.get('ai_model')
        agent = entry.get('agent')
        bar_id = entry.get('bar_id')
        start_time = entry.get('start_time')
        end_time = entry.get('end_time')

        if not all([date, ai_model, agent, bar_id, start_time, end_time]):
            return False, 'Missing required fields for conflict check'

        if date not in self.schedule_data:
            return False, 'No conflicts'

        # Only check for conflicts on the same agent and ai_model (same agent can't book same model twice)
        existing_entries = [
            e for e in self.schedule_data[date] if e.get('ai_model') == ai_model and e.get('agent') == agent
        ]

        # Parse new entry times
        try:
            new_start_hour, new_start_minute = map(int, start_time.split(':'))
            new_end_hour, new_end_minute = map(int, end_time.split(':'))
            new_start_total = new_start_hour + new_start_minute / 60
            new_end_total = new_end_hour + new_end_minute / 60
            # Handle overnight schedules
            if new_end_total < new_start_total:
                new_end_total += 24
        except ValueError:
            return False, 'Invalid time format'

        # Check for overlaps only on same bar
        for existing_entry in existing_entries:
            existing_start = existing_entry.get('start_time', '00:00')
            existing_end = existing_entry.get('end_time', '23:59')
            try:
                existing_start_hour, existing_start_minute = map(int, existing_start.split(':'))
                existing_end_hour, existing_end_minute = map(int, existing_end.split(':'))
                existing_start_total = existing_start_hour + existing_start_minute / 60
                existing_end_total = existing_end_hour + existing_end_minute / 60
                if existing_end_total < existing_start_total:
                    existing_end_total += 24
                # Check for overlap
                if new_start_total < existing_end_total and new_end_total > existing_start_total:
                    return (
                        True,
                        f'Agent {agent} already has an entry for model {ai_model} during {existing_start} - {existing_end}',
                    )
            except ValueError as _exc:
                _zyg_log.warning('unparsable times on an existing entry, overlap not checked against it: %s', _exc)
                continue
        return False, 'No conflicts'

    def add_schedule_entry(self, entry: Dict, date: str = None) -> Tuple[bool, str]:
        """Add a new schedule entry"""
        if date is None:
            date = datetime.datetime.now().strftime('%Y-%m-%d')

        # Validate entry
        is_valid, message = self.validate_schedule_entry(entry)
        if not is_valid:
            return False, message

        # Initialize date if not exists
        if date not in self.schedule_data:
            self.schedule_data[date] = []

        # Generate unique ID if not provided
        if 'id' not in entry:
            entry['id'] = str(uuid.uuid4())

        # Add date to entry
        entry['date'] = date

        # Add entry
        self.schedule_data[date].append(entry)
        self.save_schedule_data()

        return True, f'Entry added successfully with ID: {entry["id"]}'

    def edit_schedule_entry(self, entry_id: str, updated_entry: Dict, date: str = None) -> Tuple[bool, str]:
        """Edit an existing schedule entry"""
        if date is None:
            date = datetime.datetime.now().strftime('%Y-%m-%d')

        if date not in self.schedule_data:
            return False, 'Date not found in schedule'

        # Find the entry to edit
        entry_index = None
        for i, entry in enumerate(self.schedule_data[date]):
            if entry.get('id') == entry_id:
                entry_index = i
                break

        if entry_index is None:
            return False, 'Entry not found'

        # Preserve the original ID and date
        updated_entry['id'] = entry_id
        updated_entry['date'] = date

        # Validate the updated entry
        is_valid, message = self.validate_schedule_entry(updated_entry)
        if not is_valid:
            return False, message

        # Update the entry
        self.schedule_data[date][entry_index] = updated_entry
        self.save_schedule_data()

        return True, 'Entry updated successfully'

    def delete_schedule_entry(self, entry_id: str, date: str = None) -> Tuple[bool, str]:
        """Delete a schedule entry by ID"""
        if date is None:
            date = datetime.datetime.now().strftime('%Y-%m-%d')

        if date not in self.schedule_data:
            return False, 'Date not found in schedule'

        # Find and remove the entry
        original_length = len(self.schedule_data[date])
        self.schedule_data[date] = [entry for entry in self.schedule_data[date] if entry.get('id') != entry_id]

        if len(self.schedule_data[date]) == original_length:
            return False, 'Entry not found'

        self.save_schedule_data()
        return True, 'Entry deleted successfully'

    def get_available_models(self) -> List[str]:
        """Get list of available AI models"""
        return list(self.model_agent_mapping.keys())

    def get_model_agent_count(self, model: str) -> int:
        """Get the number of agents that can use a specific model"""
        return self.model_agent_mapping.get(model, 0)

    def get_todays_entries(self, date: str = None) -> List[Dict]:
        """Get all schedule entries for a specific date"""
        if date is None:
            date = datetime.datetime.now().strftime('%Y-%m-%d')

        return self.schedule_data.get(date, [])

    def get_entries_by_model(self, model: str, date: str = None) -> List[Dict]:
        """Get all entries for a specific model on a specific date"""
        if date is None:
            date = datetime.datetime.now().strftime('%Y-%m-%d')

        entries = self.get_todays_entries(date)
        return [entry for entry in entries if entry.get('ai_model') == model]

    def get_available_time_slots(self, model: str, date: str = None) -> List[Dict]:
        """Get available time slots for a specific model on a specific date"""
        if date is None:
            date = datetime.datetime.now().strftime('%Y-%m-%d')

        # Get existing entries for this model
        existing_entries = self.get_entries_by_model(model, date)

        # Get the maximum number of concurrent agents for this model
        max_agents = self.get_model_agent_count(model)

        # If we haven't reached the limit, any time slot is available
        if len(existing_entries) < max_agents:
            return [{'start_time': '00:00', 'end_time': '23:59', 'available': True}]

        # If we've reached the limit, find gaps in the schedule
        # This is a simplified implementation - in practice, you'd want more sophisticated gap detection
        occupied_slots = []
        for entry in existing_entries:
            occupied_slots.append(
                {'start_time': entry.get('start_time', '00:00'), 'end_time': entry.get('end_time', '23:59')}
            )

        # Sort occupied slots by start time
        occupied_slots.sort(key=lambda x: x['start_time'])

        # Find gaps (simplified - just return early morning and late night slots)
        available_slots = []

        # Check if early morning is available (00:00 - 06:00)
        early_morning_available = True
        for slot in occupied_slots:
            if slot['start_time'] <= '06:00' and slot['end_time'] >= '00:00':
                early_morning_available = False
                break

        if early_morning_available:
            available_slots.append({'start_time': '00:00', 'end_time': '06:00', 'available': True})

        # Check if late night is available (22:00 - 23:59)
        late_night_available = True
        for slot in occupied_slots:
            if slot['start_time'] <= '23:59' and slot['end_time'] >= '22:00':
                late_night_available = False
                break

        if late_night_available:
            available_slots.append({'start_time': '22:00', 'end_time': '23:59', 'available': True})

        return available_slots

    def get_entry_form_data(self, date: str = None) -> Dict:
        """Get data needed for the add entry form"""
        if date is None:
            date = datetime.datetime.now().strftime('%Y-%m-%d')

        return {
            'available_models': self.get_available_models(),
            'model_agent_counts': self.model_agent_mapping,
            'todays_entries': self.get_todays_entries(date),
            'date': date,
            'gpu_devices': ['CPU', 'NVIDIA GeForce GTX 970', 'NVIDIA GeForce RTX 3080', 'NVIDIA GeForce RTX 4090'],
            'priorities': ['High', 'Mid', 'Low'],
        }

    def create_sample_entry(self, model: str = None) -> Dict:
        """Create a sample entry for testing"""
        if model is None:
            model = list(self.model_agent_mapping.keys())[0]

        now = datetime.datetime.now()
        start_time = (now + timedelta(hours=1)).strftime('%H:%M')
        end_time = (now + timedelta(hours=2)).strftime('%H:%M')

        return {
            'ai_model': model,
            'start_time': start_time,
            'end_time': end_time,
            'gpu_percent': '99.9',
            'memory_fraction': '0.10',
            'gpu_device': 'NVIDIA GeForce GTX 970',
            'priority': 'High',
            'agent': 'Test_Agent',
        }


def main():
    """Main function for testing"""
    add_entry = AddEntryTimeline()

    # Test creating a sample entry
    sample_entry = add_entry.create_sample_entry('Claude_3')
    print('Sample entry:', sample_entry)

    # Test validation
    is_valid, message = add_entry.validate_schedule_entry(sample_entry)
    print(f'Validation: {is_valid}, Message: {message}')

    # Test adding entry
    success, message = add_entry.add_schedule_entry(sample_entry)
    print(f'Add entry: {success}, Message: {message}')

    # Get form data
    form_data = add_entry.get_entry_form_data()
    print(f'Available models: {len(form_data["available_models"])}')
    print(f"Today's entries: {len(form_data['todays_entries'])}")

    # Test available time slots
    available_slots = add_entry.get_available_time_slots('Claude_3')
    print(f'Available time slots for Claude_3: {available_slots}')


if __name__ == '__main__':
    main()
