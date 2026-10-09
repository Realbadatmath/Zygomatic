#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Regenerate Schedule Files with Backup Logic
This script recreates the schedule files using the proper backup implementation
"""

import json
import os
from datetime import datetime
import uuid

# Import the corrected AI model mapping
from zyg_workflows.ai_model_agent_mapping import model_to_agents, CPU_MODELS, GPU_MODELS

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def create_schedule_entry(
    model_name, agent_name, bar_id, start_time, end_time, cpu_percent=None, gpu_percent=None, memory_fraction=0.5
):
    """Create a schedule entry with proper structure"""
    entry = {
        'id': str(uuid.uuid4()),
        'ai_model': model_name,
        'agent': agent_name,
        'bar_id': bar_id,
        'start_time': start_time,
        'end_time': end_time,
        'memory_fraction': memory_fraction,
        'date': datetime.now().strftime('%Y-%m-%d'),
    }

    if cpu_percent:
        entry['cpu_percent'] = cpu_percent
    if gpu_percent:
        entry['gpu_percent'] = gpu_percent

    return entry


def generate_cpu_schedule():
    """Generate CPU schedule with all CPU models and their agent mappings"""
    cpu_schedule = {}
    current_date = datetime.now().strftime('%Y-%m-%d')
    cpu_schedule[current_date] = []

    bar_id_counter = 1

    for model_name in CPU_MODELS:
        if model_name in model_to_agents:
            agents = model_to_agents[model_name]
            for agent in agents:
                # Create multiple bars for each agent-model combination
                for _bar_num in range(1, 5):  # 4 bars per agent-model
                    entry = create_schedule_entry(
                        model_name=model_name,
                        agent_name=agent,
                        bar_id=bar_id_counter,
                        start_time='09:00',
                        end_time='17:00',
                        cpu_percent=25.0,
                        memory_fraction=0.25,
                    )
                    cpu_schedule[current_date].append(entry)
                    bar_id_counter += 1

    return cpu_schedule


def generate_gpu_schedule():
    """Generate GPU schedule with all GPU models and their agent mappings"""
    gpu_schedule = {}
    current_date = datetime.now().strftime('%Y-%m-%d')
    gpu_schedule[current_date] = []

    bar_id_counter = 1

    for model_name in GPU_MODELS:
        if model_name in model_to_agents:
            agents = model_to_agents[model_name]
            for agent in agents:
                # Create multiple bars for each agent-model combination
                for _bar_num in range(1, 4):  # 3 bars per agent-model (GPU is more limited)
                    entry = create_schedule_entry(
                        model_name=model_name,
                        agent_name=agent,
                        bar_id=bar_id_counter,
                        start_time='09:00',
                        end_time='17:00',
                        gpu_percent=33.33,
                        memory_fraction=0.33,
                    )
                    gpu_schedule[current_date].append(entry)
                    bar_id_counter += 1

    return gpu_schedule


def save_schedule_file(schedule_data, filename):
    """Save schedule data to JSON file"""
    filepath = os.path.join('Schedule', filename)
    with open(filepath, 'w') as f:
        json.dump(schedule_data, f, indent=2)
    _zyg_log.info(f'Saved {filename} with {len(schedule_data.get(datetime.now().strftime("%Y-%m-%d"), []))} entries')


def main():
    """Main function to regenerate schedule files"""
    print('=== Regenerating Schedule Files with Backup Logic ===')

    # Create Schedule directory if it doesn't exist
    os.makedirs('Schedule', exist_ok=True)

    # Generate CPU schedule
    print('\nGenerating CPU schedule...')
    cpu_schedule = generate_cpu_schedule()
    save_schedule_file(cpu_schedule, 'schedule_data_CPU.json')

    # Generate GPU schedule
    print('\nGenerating GPU schedule...')
    gpu_schedule = generate_gpu_schedule()
    save_schedule_file(gpu_schedule, 'schedule_data_GPU.json')

    # Print statistics
    cpu_entries = len(cpu_schedule.get(datetime.now().strftime('%Y-%m-%d'), []))
    gpu_entries = len(gpu_schedule.get(datetime.now().strftime('%Y-%m-%d'), []))

    print('\n=== Schedule Generation Complete ===')
    print(f'CPU Entries: {cpu_entries}')
    print(f'GPU Entries: {gpu_entries}')
    print(f'Total Entries: {cpu_entries + gpu_entries}')
    print(f'CPU Models: {len(CPU_MODELS)}')
    print(f'GPU Models: {len(GPU_MODELS)}')

    # Print model usage statistics
    print('\n=== Model Usage Statistics ===')
    for model in CPU_MODELS:
        if model in model_to_agents:
            agent_count = len(model_to_agents[model])
            print(f'CPU {model}: {agent_count} agents')

    for model in GPU_MODELS:
        if model in model_to_agents:
            agent_count = len(model_to_agents[model])
            print(f'GPU {model}: {agent_count} agents')


if __name__ == '__main__':
    main()
