#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Expand Timeline with Agents Script
Expands the 24-hour timeline to include all agents with unique vertical bars
"""

import json
import uuid
from pathlib import Path
from typing import Dict, List, Any, Tuple
from datetime import datetime

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


class TimelineExpander:
    def __init__(self, agents_dir: str = 'agents', schedule_dir: str = 'Schedule'):
        self.agents_dir = Path(agents_dir)
        self.schedule_dir = Path(schedule_dir)
        self.index_path = self.agents_dir / 'index.json'

        # AI Model to Agent mapping based on agent roles and capabilities
        self.agent_ai_model_mapping = {
            # GPU-Intensive Models (Visual/Audio Generation)
            'Stable Diffusion 1.5 Xl': [
                '2D-Character-Designer-Agent',
                '3D-Character-Designer-Agent',
                '2D-Background-Artist-Agent',
                '3D-Environment-Agent',
                '3D-Modeling-Agent',
                '3D-Texturing-Agent',
                'Thumbnail-Agent',
                'YouTube-Thumbnail-Agent',
                '3D-Effects-Agent',
                'Effects-Agent',
            ],
            'Dreamshaper Realisticvision': [
                '2D-Character-Designer-Agent',
                '3D-Character-Designer-Agent',
                '2D-Background-Artist-Agent',
                '3D-Environment-Agent',
                '3D-Modeling-Agent',
                '3D-Texturing-Agent',
                'Thumbnail-Agent',
                'YouTube-Thumbnail-Agent',
            ],
            'Stable Video Diffusion': [
                '3D-Animation-Agent',
                '2D-Animation-Agent',
                '3D-Series-Agent',
                '2D-Series-Agent',
                'YouTube-Video-Editor-Agent',
                'Render-Agent',
            ],
            'Animatediff': [
                '3D-Animation-Agent',
                '2D-Animation-Agent',
                '3D-Series-Agent',
                '2D-Series-Agent',
                'YouTube-Video-Editor-Agent',
            ],
            'Controlnet': [
                '3D-Modeling-Agent',
                '3D-Character-Designer-Agent',
                '2D-Character-Designer-Agent',
                '3D-Environment-Agent',
            ],
            'Dreambooth': [
                '3D-Character-Designer-Agent',
                '2D-Character-Designer-Agent',
                '3D-Modeling-Agent',
                '3D-Texturing-Agent',
            ],
            'Bark': [
                '2D-Voice-Agent',
                '3D-Voice-Agent',
                'YouTube-Audio-Agent',
                'English-Voice-Agent',
                'Spanish-Voice-Agent',
                'French-Voice-Agent',
                'German-Voice-Agent',
                'Italian-Voice-Agent',
                'Portuguese-Voice-Agent',
                'Russian-Voice-Agent',
                'Japanese-Voice-Agent',
                'Korean-Voice-Agent',
                'Arabic-Voice-Agent',
                'Hindi-Voice-Agent',
                'Bengali-Voice-Agent',
                'Mandarin-Voice-Agent',
            ],
            'Bark-Voice-Cloning': [
                '2D-Voice-Agent',
                '3D-Voice-Agent',
                'YouTube-Audio-Agent',
                'English-Voice-Agent',
                'Spanish-Voice-Agent',
                'French-Voice-Agent',
                'German-Voice-Agent',
                'Italian-Voice-Agent',
                'Portuguese-Voice-Agent',
                'Russian-Voice-Agent',
                'Japanese-Voice-Agent',
                'Korean-Voice-Agent',
                'Arabic-Voice-Agent',
                'Hindi-Voice-Agent',
                'Bengali-Voice-Agent',
                'Mandarin-Voice-Agent',
            ],
            'Tortoise Tts': [
                '2D-Voice-Agent',
                '3D-Voice-Agent',
                'YouTube-Audio-Agent',
                'English-Voice-Agent',
                'Spanish-Voice-Agent',
                'French-Voice-Agent',
                'German-Voice-Agent',
                'Italian-Voice-Agent',
                'Portuguese-Voice-Agent',
                'Russian-Voice-Agent',
                'Japanese-Voice-Agent',
                'Korean-Voice-Agent',
                'Arabic-Voice-Agent',
                'Hindi-Voice-Agent',
                'Bengali-Voice-Agent',
                'Mandarin-Voice-Agent',
            ],
            'Realesrgan': [
                '3D-Rendering-Agent',
                'Render-Agent',
                'YouTube-Video-Editor-Agent',
                '2D-Compositor-Agent',
                '3D-Compositor-Agent',
            ],
            '3D-Render-Farm-Manager-Agent': ['3D-Rendering-Agent', 'Render-Agent', '3D-Render-Farm-Manager-Agent'],
            # CPU-Intensive Models (Text/Logic Processing)
            'Claude 3': [
                'CEO-Agent',
                'CTO-Agent',
                'Affiliate-Marketing-Overseer',
                'Animation-Media-Overseer',
                'Business-Support-Overseer',
                'Content-Production-Overseer',
                'Adult-NSFW-Overseer',
                '2D-Series-Overseer',
                '3D-Series-Overseer',
                'YouTube-Content-Overseer',
                'Content-Production-Overseer',
                'Business-Support-Overseer',
            ],
            'Llama 3': [
                'CEO-Agent',
                'CTO-Agent',
                'Affiliate-Marketing-Overseer',
                'Animation-Media-Overseer',
                'Business-Support-Overseer',
                'Content-Production-Overseer',
                '2D-Series-Overseer',
                '3D-Series-Overseer',
            ],
            'Mistral Mixtral': [
                'Animation-Media-Overseer',
                '2D-Series-Overseer',
                '3D-Series-Overseer',
                'Content-Production-Overseer',
                'Business-Support-Overseer',
            ],
            'Whisper': [
                '3D-Animation-Agent',
                '2D-Animation-Agent',
                'YouTube-Audio-Agent',
                '2D-Voice-Agent',
                '3D-Voice-Agent',
                'English-Voice-Agent',
                'Spanish-Voice-Agent',
                'French-Voice-Agent',
                'German-Voice-Agent',
                'Italian-Voice-Agent',
                'Portuguese-Voice-Agent',
                'Russian-Voice-Agent',
                'Japanese-Voice-Agent',
                'Korean-Voice-Agent',
                'Arabic-Voice-Agent',
                'Hindi-Voice-Agent',
                'Bengali-Voice-Agent',
                'Mandarin-Voice-Agent',
            ],
            'Crewai Openagents': [
                'CEO-Agent',
                'CTO-Agent',
                'Affiliate-Marketing-Overseer',
                'Animation-Media-Overseer',
                'Business-Support-Overseer',
                'Content-Production-Overseer',
                '2D-Series-Overseer',
                '3D-Series-Overseer',
            ],
            'Humaneval': [
                'Audio-Editor-Agent',
                'YouTube-Audio-Agent',
                '2D-Sound-Effects-Agent',
                '3D-Effects-Agent',
                'Effects-Agent',
            ],
            'Fastapi': [
                'CEO-Agent',
                'CTO-Agent',
                'Affiliate-Marketing-Overseer',
                'Animation-Media-Overseer',
                'Business-Support-Overseer',
                'Content-Production-Overseer',
            ],
            'Blender (Bpy)': [
                '3D-Modeling-Agent',
                '3D-Animation-Agent',
                '3D-Rendering-Agent',
                '3D-Environment-Agent',
                '3D-Lighting-Agent',
                '3D-Rigging-Agent',
                '3D-Texturing-Agent',
                '3D-Compositor-Agent',
                '3D-Storyboard-Agent',
            ],
            'Davinci Resolve': [
                'YouTube-Video-Editor-Agent',
                'Render-Agent',
                '2D-Compositor-Agent',
                '3D-Compositor-Agent',
                'Scene-Editor-Agent',
                'Effects-Agent',
            ],
            'Ai Qc Engine': [
                '2D-Quality-Control-Agent',
                '3D-Quality-Control-Agent',
                'Quality-Control-Agent',
                'Multi-Language-QC-Agent',
            ],
            'Clip': [
                'Analytics-Agent',
                'Analytics-Reporting-Agent',
                'YouTube-Analytics-Agent',
                'Metadata-Agent',
                'Progress-Tracker-Agent',
            ],
            'Lora': [
                '3D-Character-Designer-Agent',
                '2D-Character-Designer-Agent',
                '3D-Modeling-Agent',
                '3D-Texturing-Agent',
            ],
            'Plotly': [
                'Analytics-Agent',
                'Analytics-Reporting-Agent',
                'YouTube-Analytics-Agent',
                'Financial-Report-Agent',
                'Performance-Evaluator-Agent',
            ],
            'Airflow': [
                'Daily-Production-Scheduler-Agent',
                'Task-Scheduler-Agent',
                '2D-Scheduling-Agent',
                '3D-Scheduling-Agent',
                'Video-Scheduler-Agent',
                'YouTube-Scheduling-Agent',
                'Reminder-Agent',
            ],
            'autosave_daemon': [
                '2D-Asset-Manager-Agent',
                '3D-Asset-Manager-Agent',
                'Footage-Organizer-Agent',
                'Document-Filing-Agent',
                'Case-Tracker-Agent',
            ],
        }

        # Separate CPU and GPU models
        self.gpu_models = [
            'Stable Diffusion 1.5 Xl',
            'Dreamshaper Realisticvision',
            'Stable Video Diffusion',
            'Animatediff',
            'Controlnet',
            'Dreambooth',
            'Bark',
            'Bark-Voice-Cloning',
            'Tortoise Tts',
            'Realesrgan',
            '3D-Render-Farm-Manager-Agent',
        ]

        self.cpu_models = [
            'Claude 3',
            'Llama 3',
            'Mistral Mixtral',
            'Whisper',
            'Crewai Openagents',
            'Humaneval',
            'Fastapi',
            'Blender (Bpy)',
            'Davinci Resolve',
            'Ai Qc Engine',
            'Clip',
            'Lora',
            'Plotly',
            'Airflow',
            'autosave_daemon',
        ]

    def load_agents_index(self) -> Dict[str, Any]:
        """Load the agents index file"""
        if not self.index_path.exists():
            raise FileNotFoundError(f'Index file not found: {self.index_path}')

        with open(self.index_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def get_all_agents(self) -> List[Dict[str, Any]]:
        """Get all agents from the index"""
        index_data = self.load_agents_index()
        all_agents = []

        for overseer, agents in index_data['agents_by_overseer'].items():
            for agent_info in agents:
                agent_info['overseer'] = overseer
                all_agents.append(agent_info)

        return all_agents

    def generate_bar_id(self) -> str:
        """Generate a unique bar ID"""
        return str(uuid.uuid4())[:8]

    def create_agent_schedule_entries(self) -> Tuple[Dict[str, List], Dict[str, List]]:
        """Create schedule entries for all agents"""
        all_agents = self.get_all_agents()
        cpu_entries = {}
        gpu_entries = {}

        # Initialize with today's date
        today = datetime.now().strftime('%Y-%m-%d')

        for agent_info in all_agents:
            agent_name = agent_info['name']
            agent_id = agent_info['id']
            overseer = agent_info['overseer']

            # Find which AI models this agent can use
            agent_models = []
            for model, agents in self.agent_ai_model_mapping.items():
                if agent_name in agents:
                    agent_models.append(model)

            # If no specific models found, assign to general CPU models
            if not agent_models:
                agent_models = ['Claude 3', 'Llama 3']

            # Create schedule entries for each model
            for model in agent_models:
                bar_id = self.generate_bar_id()

                # Create base entry
                entry = {
                    'ai_model': model,
                    'agent': agent_name,
                    'agent_id': agent_id,
                    'overseer': overseer,
                    'bar_id': bar_id,
                    'priority': 'Medium',
                    'id': str(uuid.uuid4()),
                    'date': today,
                }

                # Add model-specific settings
                if model in self.gpu_models:
                    entry.update(
                        {
                            'start_time': '09:00',
                            'end_time': '17:00',
                            'gpu_percent': '50.0',
                            'memory_fraction': '0.10',
                            'gpu_device': 'NVIDIA GeForce GTX 970',
                        }
                    )

                    if today not in gpu_entries:
                        gpu_entries[today] = []
                    gpu_entries[today].append(entry)

                else:  # CPU models
                    entry.update(
                        {
                            'start_time': '09:00',
                            'end_time': '17:00',
                            'cpu_percent': '25.0',
                            'memory_fraction': '0.10',
                            'cpu_device': 'CPU 1',
                        }
                    )

                    if today not in cpu_entries:
                        cpu_entries[today] = []
                    cpu_entries[today].append(entry)

        return cpu_entries, gpu_entries

    def update_schedule_files(self):
        """Update the CPU and GPU schedule files with new agent entries"""
        _zyg_log.info('Creating schedule entries for all agents...')
        cpu_entries, gpu_entries = self.create_agent_schedule_entries()

        # Update CPU schedule file
        cpu_file = self.schedule_dir / 'schedule_data_CPU.json'
        _zyg_log.info(f'Updating {cpu_file} with {sum(len(entries) for entries in cpu_entries.values())} entries...')
        with open(cpu_file, 'w', encoding='utf-8') as f:
            json.dump(cpu_entries, f, indent=2, ensure_ascii=False)

        # Update GPU schedule file
        gpu_file = self.schedule_dir / 'schedule_data_GPU.json'
        _zyg_log.info(f'Updating {gpu_file} with {sum(len(entries) for entries in gpu_entries.values())} entries...')
        with open(gpu_file, 'w', encoding='utf-8') as f:
            json.dump(gpu_entries, f, indent=2, ensure_ascii=False)

        _zyg_log.info('✅ Schedule files updated successfully!')
        return cpu_entries, gpu_entries

    def create_agent_bar_mapping(self) -> Dict[str, Dict]:
        """Create a mapping of agents to their bar IDs and models"""
        all_agents = self.get_all_agents()
        agent_mapping = {}

        for agent_info in all_agents:
            agent_name = agent_info['name']
            agent_id = agent_info['id']

            # Find models for this agent
            models = []
            for model, agents in self.agent_ai_model_mapping.items():
                if agent_name in agents:
                    models.append(model)

            if not models:
                models = ['Claude 3', 'Llama 3']  # Default models

            agent_mapping[agent_name] = {
                'agent_id': agent_id,
                'models': models,
                'bar_ids': [self.generate_bar_id() for _ in models],
            }

        return agent_mapping

    def save_agent_bar_mapping(self, mapping: Dict[str, Dict]):
        """Save the agent to bar mapping"""
        mapping_file = self.schedule_dir / 'agent_bar_mapping.json'
        with open(mapping_file, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, indent=2, ensure_ascii=False)
        _zyg_log.info(f'✅ Agent bar mapping saved to {mapping_file}')


def main():
    expander = TimelineExpander()

    try:
        print('🚀 Expanding timeline with all agents...')

        # Get agent count
        all_agents = expander.get_all_agents()
        print(f'📊 Found {len(all_agents)} agents to process')

        # Create agent bar mapping
        print('🔗 Creating agent to bar mapping...')
        agent_mapping = expander.create_agent_bar_mapping()
        expander.save_agent_bar_mapping(agent_mapping)

        # Update schedule files
        print('📅 Updating schedule files...')
        cpu_entries, gpu_entries = expander.update_schedule_files()

        # Summary
        total_cpu_entries = sum(len(entries) for entries in cpu_entries.values())
        total_gpu_entries = sum(len(entries) for entries in gpu_entries.values())

        print('\n✅ Timeline expansion complete!')
        print('📈 Summary:')
        print(f'   - Total agents: {len(all_agents)}')
        print(f'   - CPU schedule entries: {total_cpu_entries}')
        print(f'   - GPU schedule entries: {total_gpu_entries}')
        print(f'   - Total schedule entries: {total_cpu_entries + total_gpu_entries}')
        print(f'   - Agent bar mapping: {len(agent_mapping)} agents mapped')

    except Exception as e:
        print(f'❌ Error: {e}')
        return 1

    return 0


if __name__ == '__main__':
    exit(main())
