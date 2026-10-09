#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
24-Hour Timeline Script for CrewAI Agent Schedule
Generates and manages the 24-hour timeline visualization
"""

import json
import os
import datetime
from typing import Dict, List, Tuple
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import textwrap
import random
import sys

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# Add parent directory to path to import ai_model_agent_mapping
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from zyg_workflows.ai_model_agent_mapping import model_to_agents, CPU_MODELS, GPU_MODELS
except ImportError:
    model_to_agents = {}
    CPU_MODELS = []
    GPU_MODELS = []


class Timeline24Hour:
    def __init__(self, schedule_file: str = 'schedule_data_ACTIVE.json'):
        self.schedule_file = schedule_file
        self.schedule_data = self.load_schedule_data()

        # AI Model to Agent Count mapping from ai_model_agent_mapping
        self.model_agent_mapping = {}
        for model_name, agents in model_to_agents.items():
            self.model_agent_mapping[model_name] = len(agents)

        # Sort by most agents to least
        self.model_agent_mapping = dict(sorted(self.model_agent_mapping.items(), key=lambda x: -x[1]))

        # Full model-to-bar-count mapping (from your config)
        self.full_model_bar_counts = {
            'claude 3': 95,
            'gpt 4': 95,
            'llama 3': 95,
            'mistral mixtral': 95,
            'humaneval': 44,
            'crewai openagents': 43,
            'langchain llamalend': 43,
            'plotly': 32,
            'fastapi': 32,
            'ai qc engine': 32,
            'google translate api': 1,
            'deepl api': 1,
            'microsoft translator api': 1,
            'cultural reference database': 1,
            'humor adaptation engine': 1,
            'mandarin translation api': 1,
            'hindi translation api': 1,
            'spanish translation api': 1,
            'french translation api': 1,
            'arabic translation api': 1,
            'bengali translation api': 1,
            'portuguese translation api': 1,
            'opencv': 1,
            'imagehash  opencv': 1,
            'stable diffusion 15 xl': 48,
            'dreamshaper realisticvision': 48,
            'controlnet': 29,
            'animatediff': 20,
            'comfyui': 19,
            'bark': 15,
            'tortoise tts': 15,
            'whisper': 15,
            'kandinsky 22': 15,
            'assemblyai': 14,
            'deepgram': 14,
            'deforum': 14,
            'realesrgan': 10,
            'blender bpy': 9,
            'stable video diffusion': 7,
            'librosa': 6,
            'dreambooth': 5,
            'lora': 5,
            'ffmpeg': 4,
            'pydub': 4,
            'yolov8 segment anything': 3,
            'davinci resolve': 3,
            'vae': 1,
        }

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

    def get_todays_entries(self, date: str = None) -> List[Dict]:
        self.schedule_data = self.load_schedule_data()  # Always reload
        if date is None:
            import datetime

            date = datetime.datetime.now().strftime('%Y-%m-%d')
        entries = self.schedule_data.get(date, [])
        return entries

    def add_schedule_entry(self, entry: Dict, date: str = None) -> bool:
        """Add a new schedule entry"""
        if date is None:
            date = datetime.datetime.now().strftime('%Y-%m-%d')

        if date not in self.schedule_data:
            self.schedule_data[date] = []

        # Generate unique ID if not provided
        if 'id' not in entry:
            import uuid

            entry['id'] = str(uuid.uuid4())

        # Add date to entry
        entry['date'] = date

        self.schedule_data[date].append(entry)
        self.save_schedule_data()
        return True

    def delete_schedule_entry(self, entry_id: str, date: str = None) -> bool:
        """Delete a schedule entry by ID"""
        if date is None:
            date = datetime.datetime.now().strftime('%Y-%m-%d')

        if date in self.schedule_data:
            self.schedule_data[date] = [entry for entry in self.schedule_data[date] if entry.get('id') != entry_id]
            self.save_schedule_data()
            return True
        return False

    def generate_timeline_visualization(self, date: str = None, output_file: str = '24_hour_timeline.png'):
        """Generate the 24-hour timeline visualization based on the PNG structure"""
        if date is None:
            date = datetime.datetime.now().strftime('%Y-%m-%d')

        entries = self.get_todays_entries(date)

        # Configuration
        BASE_WIDTH = 150
        HOURS = 24
        MODEL_COUNT = len(self.model_agent_mapping)
        MODEL_BOX_HEIGHT = 40
        BAR_HEIGHT = HOURS * 20

        # Generate colors for each model
        cmap = plt.get_cmap('tab20', MODEL_COUNT)
        model_colors = {model: cmap(i) for i, (model, _) in enumerate(self.model_agent_mapping.items())}

        # Create figure
        fig, ax = plt.subplots(figsize=(MODEL_COUNT * 1.5, 8))
        ax.set_xlim(0, MODEL_COUNT * (BASE_WIDTH + 20))
        ax.set_ylim(0, BAR_HEIGHT + MODEL_BOX_HEIGHT + 20)
        ax.axis('off')
        ax.invert_yaxis()

        # Draw model name boxes at the top
        for col_idx, (model_name, _n_bars) in enumerate(self.model_agent_mapping.items()):
            col_x = col_idx * (BASE_WIDTH + 20)

            # Draw model name box
            box = patches.FancyBboxPatch(
                (col_x, 0),
                BASE_WIDTH,
                MODEL_BOX_HEIGHT,
                boxstyle='round,pad=0.1',
                linewidth=1,
                edgecolor='black',
                facecolor='#e0e0ff',
                zorder=2,
            )
            ax.add_patch(box)

            # Wrap model name
            max_chars_per_line = 14
            wrapped_name = '\n'.join(textwrap.wrap(model_name, max_chars_per_line, break_long_words=False, max_lines=3))
            ax.text(
                col_x + BASE_WIDTH / 2,
                MODEL_BOX_HEIGHT / 2,
                wrapped_name,
                ha='center',
                va='center',
                fontsize=10,
                fontweight='bold',
                zorder=3,
            )

        # Draw time labels
        for h in range(HOURS):
            y = MODEL_BOX_HEIGHT + h * 20
            ax.text(-40, y + 10, f'{h:02d}:00', va='center', ha='right', fontsize=10)

        # Draw columns and schedule bars
        for col_idx, (model_name, n_bars) in enumerate(self.model_agent_mapping.items()):
            col_x = col_idx * (BASE_WIDTH + 20)
            color = model_colors[model_name]

            # Get entries for this model
            model_entries = [e for e in entries if e.get('ai_model') == model_name]

            for bar_idx in range(n_bars):
                bar_width = BASE_WIDTH / n_bars
                bar_x = col_x + bar_idx * bar_width

                # Draw bar outline
                rect = patches.Rectangle(
                    (bar_x, MODEL_BOX_HEIGHT),
                    bar_width,
                    BAR_HEIGHT,
                    linewidth=1,
                    edgecolor='black',
                    facecolor='white',
                    zorder=1,
                )
                ax.add_patch(rect)

                # Find entry for this bar
                if bar_idx < len(model_entries):
                    entry = model_entries[bar_idx]
                    start_time = entry.get('start_time', '00:00')
                    end_time = entry.get('end_time', '23:59')

                    # Parse times
                    start_hour = int(start_time.split(':')[0])
                    start_minute = int(start_time.split(':')[1]) if ':' in start_time else 0
                    end_hour = int(end_time.split(':')[0])
                    end_minute = int(end_time.split(':')[1]) if ':' in end_time else 0

                    # Calculate positions
                    y_start = MODEL_BOX_HEIGHT + (start_hour + start_minute / 60) * 20
                    y_end = MODEL_BOX_HEIGHT + (end_hour + end_minute / 60) * 20

                    # Handle overnight schedules
                    if end_hour < start_hour:
                        y_end = MODEL_BOX_HEIGHT + 24 * 20

                    # Draw filled schedule
                    filled = patches.Rectangle(
                        (bar_x, y_start), bar_width, y_end - y_start, linewidth=0, facecolor=color, alpha=0.85, zorder=2
                    )
                    ax.add_patch(filled)

                    # Add entry ID
                    entry_id = entry.get('id', '')[-4:]  # Last 4 chars
                    ax.text(
                        bar_x + bar_width / 2,
                        (y_start + y_end) / 2,
                        entry_id,
                        fontsize=10,
                        ha='center',
                        va='center',
                        rotation=0,
                        zorder=3,
                        color='black',
                        fontweight='bold',
                    )

        # Add legend
        legend_patches = [
            patches.Patch(color=model_colors[model], label=model.replace('\n', ' '))
            for model in self.model_agent_mapping.keys()
        ]
        ax.legend(handles=legend_patches, bbox_to_anchor=(1.01, 1), loc='upper left', fontsize=8, title='AI Models')

        plt.title(f'24-Hour Timeline - {date}', fontsize=14)
        plt.tight_layout(rect=[0, 0, 0.88, 1])
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()

        _zyg_log.info(f'Generated {output_file}')

    def generate_gpu_timeline_visualization(self, date: str = None, output_file: str = 'gpu_24_hour_timeline.png'):
        """Generate the 24-hour GPU timeline visualization with all AI models and their vertical bars"""
        if date is None:
            date = datetime.datetime.now().strftime('%Y-%m-%d')

        entries = self.get_todays_entries(date)

        # Load agent configurations to get model-to-agent mappings
        try:
            with open('agent_configurations.json', 'r') as f:
                agent_config = json.load(f)
        except Exception as e:
            _zyg_log.info(f'Error loading agent configurations: {e}')
            agent_config = {'agents': {}}

        # Load model ID to name mapping
        try:
            with open('gpu_ai_models.json', 'r') as f:
                model_id_to_name = json.load(f)
        except Exception as e:
            _zyg_log.info(f'Error loading model ID mapping: {e}')
            model_id_to_name = {}

        # Build model-to-agent mapping from agent configurations
        model_to_agents = {}
        for agent_name, agent_data in agent_config['agents'].items():
            ai_models = agent_data.get('ai_models', [])
            for model_id in ai_models:
                if model_id in model_id_to_name:
                    model_name = model_id_to_name[model_id]['name']
                    if model_name not in model_to_agents:
                        model_to_agents[model_name] = []
                    model_to_agents[model_name].append(agent_name)

        # Sort models by actual scheduled entries (descending)
        model_entry_counts = {}
        for model_name in model_to_agents.keys():
            model_entries = []
            for entry in entries:
                model_id = entry.get('ai_model')
                if model_id in model_id_to_name:
                    entry_model_name = model_id_to_name[model_id]['name']
                    if entry_model_name == model_name:
                        model_entries.append(entry)
            model_entry_counts[model_name] = len(model_entries)

        # Sort models by number of scheduled entries, then by agent count as tiebreaker
        sorted_models = sorted(
            model_to_agents.items(), key=lambda x: (model_entry_counts[x[0]], len(x[1])), reverse=True
        )

        # Configuration
        HOURS = 24
        MODEL_BOX_HEIGHT = 40
        BAR_HEIGHT = HOURS * 20

        # Calculate column widths and positions
        column_widths = {}
        total_width = 0
        for model_name, agents in sorted_models:
            agent_count = len(agents)
            if agent_count == 1:
                bar_width = 150
                column_width = 150
            elif agent_count == 2:
                bar_width = 75
                column_width = 150
            elif agent_count == 3:
                bar_width = 50
                column_width = 150
            elif agent_count == 4:
                bar_width = 37.5
                column_width = 150
            elif agent_count == 5:
                bar_width = 30
                column_width = 150
            elif agent_count == 6:
                bar_width = 25
                column_width = 150
            elif agent_count == 7:
                bar_width = 21.42
                column_width = 150
            elif agent_count == 8:
                bar_width = 18.75
                column_width = 150
            else:  # 9 or more
                bar_width = 19
                column_width = agent_count * 19

            column_widths[model_name] = {
                'width': column_width,
                'bar_width': bar_width,
                'agent_count': agent_count,
                'agents': agents,
            }
            total_width += column_width + 20  # 20px spacing between columns

        # Load gradient colors
        gradient_colors = []
        try:
            gradient_dir = 'static/Gradients/more_gradients'
            if os.path.exists(gradient_dir):
                # Use matplotlib colors for now (we'll replace with actual gradient loading later)
                cmap = plt.get_cmap('tab20', len(sorted_models))
                gradient_colors = [cmap(i) for i in range(len(sorted_models))]
            else:
                cmap = plt.get_cmap('tab20', len(sorted_models))
                gradient_colors = [cmap(i) for i in range(len(sorted_models))]
        except Exception as e:
            _zyg_log.info(f'Error loading gradients: {e}')
            cmap = plt.get_cmap('tab20', len(sorted_models))
            gradient_colors = [cmap(i) for i in range(len(sorted_models))]

        # Create figure
        fig, ax = plt.subplots(figsize=(max(total_width / 100, 20), 10))
        ax.set_xlim(0, total_width)
        ax.set_ylim(0, BAR_HEIGHT + MODEL_BOX_HEIGHT + 20)
        ax.axis('off')
        ax.invert_yaxis()

        # Generate unique bar IDs

        used_bar_ids = set()

        def generate_unique_bar_id():
            while True:
                bar_id = str(random.randint(100, 999999))
                if bar_id not in used_bar_ids:
                    used_bar_ids.add(bar_id)
                    return bar_id

        # Draw model name boxes at the top
        current_x = 0
        for idx, (model_name, _agents) in enumerate(sorted_models):
            col_width = column_widths[model_name]['width']

            # Draw model name box
            box = patches.FancyBboxPatch(
                (current_x, 0),
                col_width,
                MODEL_BOX_HEIGHT,
                boxstyle='round,pad=0.1',
                linewidth=1,
                edgecolor='black',
                facecolor=gradient_colors[idx],
                alpha=0.3,
                zorder=2,
            )
            ax.add_patch(box)

            # Wrap model name
            max_chars_per_line = 12
            wrapped_name = '\n'.join(textwrap.wrap(model_name, max_chars_per_line, break_long_words=False, max_lines=2))
            ax.text(
                current_x + col_width / 2,
                MODEL_BOX_HEIGHT / 2,
                wrapped_name,
                ha='center',
                va='center',
                fontsize=9,
                fontweight='bold',
                zorder=3,
            )

            current_x += col_width + 20

        # Draw time labels and grid
        for h in range(HOURS):
            y = MODEL_BOX_HEIGHT + h * 20
            ax.text(-40, y + 10, f'{h:02d}:00', va='center', ha='right', fontsize=10)

            # Draw horizontal grid lines
            ax.axhline(y=y, color='lightgray', alpha=0.3, linewidth=0.5)

        # Draw columns and schedule bars
        current_x = 0
        for idx, (model_name, _agents) in enumerate(sorted_models):
            col_width = column_widths[model_name]['width']
            bar_width = column_widths[model_name]['bar_width']
            agent_count = column_widths[model_name]['agent_count']
            color = gradient_colors[idx]

            # Get entries for this model
            model_entries = []
            for entry in entries:
                model_id = entry.get('ai_model')
                if model_id in model_id_to_name:
                    entry_model_name = model_id_to_name[model_id]['name']
                    if entry_model_name == model_name:
                        model_entries.append(entry)

            # Draw vertical bars for each agent
            for bar_idx in range(agent_count):
                bar_x = current_x + bar_idx * bar_width

                # Generate unique bar ID
                bar_id = generate_unique_bar_id()

                # Draw bar outline
                rect = patches.Rectangle(
                    (bar_x, MODEL_BOX_HEIGHT),
                    bar_width,
                    BAR_HEIGHT,
                    linewidth=1,
                    edgecolor='black',
                    facecolor='white',
                    zorder=1,
                )
                ax.add_patch(rect)

                # Centered, vertical (rotated) bar ID
                ax.text(
                    bar_x + bar_width / 2,
                    MODEL_BOX_HEIGHT + BAR_HEIGHT / 2,
                    bar_id,
                    fontsize=10,
                    ha='center',
                    va='center',
                    rotation=90,
                    zorder=3,
                    color='black',
                    fontweight='bold',
                )

                # Find entry for this bar (if any)
                if bar_idx < len(model_entries):
                    entry = model_entries[bar_idx]
                    start_time = entry.get('start_time', '00:00')
                    end_time = entry.get('end_time', '23:59')

                    # Parse times
                    start_hour = int(start_time.split(':')[0])
                    start_minute = int(start_time.split(':')[1]) if ':' in start_time else 0
                    end_hour = int(end_time.split(':')[0])
                    end_minute = int(end_time.split(':')[1]) if ':' in end_time else 0

                    # Calculate positions
                    y_start = MODEL_BOX_HEIGHT + (start_hour + start_minute / 60) * 20
                    y_end = MODEL_BOX_HEIGHT + (end_hour + end_minute / 60) * 20

                    # Handle overnight schedules
                    if end_hour < start_hour:
                        y_end = MODEL_BOX_HEIGHT + 24 * 20

                    # Draw filled schedule
                    filled = patches.Rectangle(
                        (bar_x, y_start), bar_width, y_end - y_start, linewidth=0, facecolor=color, alpha=0.85, zorder=2
                    )
                    ax.add_patch(filled)

                    # Add entry ID on the filled bar
                    entry_id = entry.get('id', '')[-4:]  # Last 4 chars
                    ax.text(
                        bar_x + bar_width / 2,
                        (y_start + y_end) / 2,
                        entry_id,
                        fontsize=8,
                        ha='center',
                        va='center',
                        rotation=0,
                        zorder=3,
                        color='white',
                        fontweight='bold',
                    )

            current_x += col_width + 20

        # Add legend
        legend_patches = [
            patches.Patch(color=gradient_colors[i], label=f'{model} ({len(agents)} agents)')
            for i, (model, agents) in enumerate(sorted_models)
        ]
        ax.legend(handles=legend_patches, bbox_to_anchor=(1.01, 1), loc='upper left', fontsize=8, title='AI Models')

        plt.title(f'GPU 24-Hour Timeline - {date}', fontsize=14)
        plt.tight_layout(rect=[0, 0, 0.88, 1])
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()

        _zyg_log.info(f'Generated {output_file}')
        _zyg_log.info(f'Total models: {len(sorted_models)}')
        _zyg_log.info(f'Total bars: {sum(len(agents) for _, agents in sorted_models)}')
        for model, agents in sorted_models:
            _zyg_log.info(f'{model}: {len(agents)} bars')

    def build_model_agent_mapping(self, date: str = None) -> dict:
        """Dynamically build model-to-agent count mapping from schedule data for the given date."""
        if date is None:
            import datetime

            date = datetime.datetime.now().strftime('%Y-%m-%d')
        entries = self.get_todays_entries(date)
        mapping = {}
        for entry in entries:
            model = entry.get('ai_model')
            agent = entry.get('agent')
            if model and agent:
                mapping.setdefault(model, set()).add(agent)
        # Convert sets to counts
        return {model: len(agents) for model, agents in mapping.items()}

    def get_model_agent_mapping(self, date: str = None) -> dict:
        return self.build_model_agent_mapping(date)

    def get_timeline_data(self, date: str = None) -> Dict:
        self.schedule_data = self.load_schedule_data()  # Always reload
        if date is None:
            import datetime

            date = datetime.datetime.now().strftime('%Y-%m-%d')
        entries = self.get_todays_entries(date)
        # Load model ID to name mapping
        try:
            with open('gpu_ai_models.json', 'r') as f:
                model_id_to_name = json.load(f)
        except Exception:
            model_id_to_name = {}
        # Use all model IDs from gpu_ai_models.json
        all_model_ids = list(model_id_to_name.keys())
        # Build a mapping of scheduled bars for each model ID
        scheduled_bars = {}
        for entry in entries:
            model_id = entry.get('ai_model')
            if model_id:
                scheduled_bars.setdefault(model_id, []).append(entry)
        # Only show scheduled bars (no placeholders)
        all_entries = []
        model_agent_counts = {}
        for model_id in all_model_ids:
            scheduled = scheduled_bars.get(model_id, [])
            all_entries.extend(scheduled)
            model_agent_counts[model_id] = len(scheduled)
        timeline_data = {
            'date': date,
            'models': all_model_ids,
            'hours': list(range(24)),
            'entries': all_entries,
            'model_agent_counts': model_agent_counts,
            'model_to_agents': model_to_agents,
            'model_id_to_name': model_id_to_name,
        }
        return timeline_data

    def normalize_model_name(self, name: str) -> str:
        return (name or '').replace(' ', '').replace('_', '').lower()

    def validate_schedule_entry(self, entry: Dict) -> Tuple[bool, str]:
        """Validate a schedule entry"""
        required_fields = ['ai_model', 'start_time', 'end_time', 'cpu_percent']
        for field in required_fields:
            if field not in entry:
                return False, f'Missing required field: {field}'
        # Robust model name matching
        normalized_entry_model = self.normalize_model_name(entry['ai_model'])
        valid_models = {self.normalize_model_name(m): m for m in self.model_agent_mapping}
        if normalized_entry_model not in valid_models:
            return (
                False,
                f'Invalid AI model: {entry["ai_model"]}. Valid models: {list(self.model_agent_mapping.keys())}',
            )
        # Replace with canonical model name
        entry['ai_model'] = valid_models[normalized_entry_model]
        # Validate times
        try:
            start_hour, start_minute = map(int, entry['start_time'].split(':'))
            end_hour, end_minute = map(int, entry['end_time'].split(':'))
            if not (0 <= start_hour <= 23 and 0 <= start_minute <= 59):
                return False, 'Invalid start time (must be 00:00-23:59)'
            if not (0 <= end_hour <= 23 and 0 <= end_minute <= 59):
                return False, 'Invalid end time (must be 00:00-23:59)'
        except ValueError:
            return False, 'Invalid time format (use HH:MM)'
        # Validate CPU percent
        try:
            cpu_percent = float(entry['cpu_percent'])
            if not (0 < cpu_percent <= 100):
                return False, 'CPU percent must be between 0 and 100'
        except ValueError:
            return False, 'Invalid CPU percent (must be a number)'
        return True, 'Valid entry'


def main():
    """Main function for testing"""
    timeline = Timeline24Hour()

    # Test data
    test_entry = {
        'ai_model': 'Claude_3',
        'start_time': '09:00',
        'end_time': '17:00',
        'gpu_percent': '99.9',
        'memory_fraction': '0.10',
        'gpu_device': 'NVIDIA GeForce GTX 970',
        'priority': 'High',
        'agent': 'CEO_Agent',
    }

    # Add test entry
    success, message = timeline.validate_schedule_entry(test_entry)
    if success:
        timeline.add_schedule_entry(test_entry)
        print('Added test entry successfully')
    else:
        print(f'Validation failed: {message}')

    # Generate visualization
    timeline.generate_timeline_visualization()

    # Get timeline data
    data = timeline.get_timeline_data()
    print(f'Timeline data for {data["date"]}: {len(data["entries"])} entries')


if __name__ == '__main__':
    main()
