#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Populate Schedule Files with AI Models and Vertical Bars
This script creates comprehensive schedule data for all AI models with proper vertical bar assignments.
"""

import json
import os
import random
import uuid

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def clean_model_name(name):
    """Remove underscores and parentheses from model names"""
    return name.replace('_', ' ').replace('(', '').replace(')', '')


def get_bar_width(agent_count):
    """Calculate bar width based on number of agents using the model"""
    if agent_count == 1:
        return 150
    elif agent_count == 2:
        return 75
    elif agent_count == 3:
        return 50
    elif agent_count == 4:
        return 37.5
    elif agent_count == 5:
        return 30
    elif agent_count == 6:
        return 25
    elif agent_count == 7:
        return 21.42
    elif agent_count == 8:
        return 18.75
    else:
        return 19


def get_gradient_files():
    """Get available gradient files"""
    cpu_gradients = []
    gpu_gradients = []

    # CPU gradients
    cpu_path = 'static/CPU_Gradients'
    if os.path.exists(cpu_path):
        for file in os.listdir(cpu_path):
            if file.endswith('.png'):
                cpu_gradients.append(file)

    # GPU gradients (more_gradients folder)
    gpu_path = 'static/Gradients/more_gradients'
    if os.path.exists(gpu_path):
        for file in os.listdir(gpu_path):
            if file.endswith('.png'):
                gpu_gradients.append(file)

    return cpu_gradients, gpu_gradients


def generate_unique_id():
    """Generate a unique 3-6 digit ID"""
    return str(random.randint(100, 999999))


def create_schedule_entries():
    """Create schedule entries for all AI models"""

    # AI Model usage counts from your data
    cpu_models = {
        'claude_3': 95,
        'gpt_4': 95,
        'llama_3': 95,
        'mistral_mixtral': 95,
        'humaneval': 44,
        'crewai_openagents': 43,
        'langchain_llamalend': 43,
        'plotly': 32,
        'fastapi': 32,
        'ai_qc_engine': 32,
        'google_translate_api': 1,
        'deepl_api': 1,
        'microsoft_translator_api': 1,
        'cultural_reference_database': 1,
        'humor_adaptation_engine': 1,
        'mandarin_translation_api': 1,
        'hindi_translation_api': 1,
        'spanish_translation_api': 1,
        'french_translation_api': 1,
        'arabic_translation_api': 1,
        'bengali_translation_api': 1,
        'portuguese_translation_api': 1,
        'opencv': 1,
        'imagehash__opencv': 1,
    }

    gpu_models = {
        'stable_diffusion_15_xl': 48,
        'dreamshaper_realisticvision': 48,
        'controlnet': 29,
        'animatediff': 20,
        'comfyui': 19,
        'bark': 15,
        'tortoise_tts': 15,
        'whisper': 15,
        'kandinsky_22': 15,
        'assemblyai': 14,
        'deepgram': 14,
        'deforum': 14,
        'realesrgan': 10,
        'blender_bpy': 9,
        'stable_video_diffusion': 7,
        'librosa': 6,
        'dreambooth': 5,
        'lora': 5,
        'ffmpeg': 4,
        'pydub': 4,
        'yolov8_segment_anything': 3,
        'davinci_resolve': 3,
        'opencv': 2,
        'imagehash__opencv': 2,
        'vae': 1,
    }

    # Get gradient files
    cpu_gradients, gpu_gradients = get_gradient_files()

    # Sample agents (you can expand this list)
    sample_agents = [
        'Affiliate-Marketing-Overseer',
        'Affiliate-Marketing-Agent',
        'Campaign-Builder-Agent',
        'SEO-Agent',
        'Conversion-Optimizer-Agent',
        'Content-Writer-Agent',
        'Email-Marketing-Agent',
        'PPC-Agent',
        'Social-Media-Marketing-Agent',
        'Analytics-Reporting-Agent',
        'Audience-Targeting-Agent',
        'Revenue-Optimization-Agent',
        'YouTube-Content-Overseer',
        'YouTube-Script-Agent',
        'YouTube-Thumbnail-Agent',
        'YouTube-Video-Editor-Agent',
        'YouTube-Audio-Agent',
        'YouTube-SEO-Agent',
        'YouTube-Analytics-Agent',
        'YouTube-Community-Agent',
        'YouTube-Scheduling-Agent',
        'YouTube-Trend-Analyst-Agent',
        '3D-Series-Overseer',
        '3D-Series-Agent',
        '3D-Modeling-Agent',
        '3D-Rendering-Agent',
        '3D-Animation-Agent',
        '3D-Environment-Agent',
        '3D-Effects-Agent',
        '3D-Rigging-Agent',
        '3D-Texturing-Agent',
        '3D-Lighting-Agent',
        '3D-Compositor-Agent',
        '3D-Storyboard-Agent',
        '3D-Script-Agent',
        '3D-Character-Designer-Agent',
        '3D-Voice-Agent',
        '3D-Music-Agent',
        '3D-Quality-Control-Agent',
        '3D-Scheduling-Agent',
        '3D-Asset-Manager-Agent',
        '3D-Render-Farm-Manager-Agent',
        '2D-Series-Overseer',
        '2D-Series-Agent',
        '2D-Character-Designer-Agent',
        '2D-Background-Artist-Agent',
        '2D-Animation-Agent',
        '2D-Storyboard-Agent',
        '2D-Script-Agent',
        '2D-Voice-Agent',
        '2D-Music-Agent',
        '2D-Sound-Effects-Agent',
        '2D-Colorist-Agent',
        '2D-Compositor-Agent',
        '2D-Quality-Control-Agent',
        '2D-Scheduling-Agent',
        '2D-Asset-Manager-Agent',
        '2D-Series-1-Agent',
        '2D-Series-2-Agent',
        '2D-Series-3-Agent',
        '2D-Series-4-Agent',
        '2D-Series-5-Agent',
        '2D-Series-6-Agent',
        '2D-Series-7-Agent',
        '2D-Series-8-Agent',
        '2D-Series-9-Agent',
        '2D-Series-10-Agent',
        'Localization-Master-Agent',
        'Cultural-Adaptation-Master-Agent',
        'Voice-Localization-Master-Agent',
        'English-Localization-Agent',
        'Mandarin-Localization-Agent',
        'Hindi-Localization-Agent',
        'Spanish-Localization-Agent',
        'French-Localization-Agent',
        'Arabic-Localization-Agent',
        'Bengali-Localization-Agent',
        'Portuguese-Localization-Agent',
        'English-Voice-Agent',
        'Mandarin-Voice-Agent',
        'Hindi-Voice-Agent',
        'Spanish-Voice-Agent',
        'French-Voice-Agent',
        'Arabic-Voice-Agent',
        'Bengali-Voice-Agent',
        'Portuguese-Voice-Agent',
        'English-Marketing-Agent',
        'Mandarin-Marketing-Agent',
        'Hindi-Marketing-Agent',
        'Spanish-Marketing-Agent',
        'French-Marketing-Agent',
        'Arabic-Marketing-Agent',
        'Bengali-Marketing-Agent',
        'Portuguese-Marketing-Agent',
        'Multi-Language-QC-Agent',
    ]

    # Create CPU schedule data
    cpu_schedule_data = {'2025-07-13': []}
    cpu_bar_id_counter = 1

    for model, agent_count in cpu_models.items():
        clean_name = clean_model_name(model)
        bar_width = get_bar_width(agent_count)

        # Select gradient color
        gradient_file = cpu_gradients[cpu_bar_id_counter % len(cpu_gradients)] if cpu_gradients else 'gradient_01.png'

        # Create entries for each agent using this model
        for i in range(agent_count):
            agent = sample_agents[i % len(sample_agents)]

            # Generate random time slots
            start_hour = random.randint(0, 23)
            start_minute = random.choice([0, 15, 30, 45])
            start_time = f'{start_hour:02d}:{start_minute:02d}'

            end_hour = (start_hour + random.randint(1, 4)) % 24
            end_minute = random.choice([0, 15, 30, 45])
            end_time = f'{end_hour:02d}:{end_minute:02d}'

            entry = {
                'ai_model': clean_name,
                'agent': agent,
                'start_time': start_time,
                'end_time': end_time,
                'cpu_percent': str(random.randint(10, 90)),
                'memory_fraction': str(round(random.uniform(0.1, 0.8), 2)),
                'priority': random.choice(['High', 'Medium', 'Low']),
                'bar_id': str(cpu_bar_id_counter).zfill(6),
                'date': '2025-07-13',
                'id': str(uuid.uuid4()),
                'agent_id': str(uuid.uuid4()),
                'bar_width': bar_width,
                'gradient_file': gradient_file,
                'model_type': 'CPU',
            }

            cpu_schedule_data['2025-07-13'].append(entry)
            cpu_bar_id_counter += 1

    # Create GPU schedule data
    gpu_schedule_data = {'2025-07-13': []}
    gpu_bar_id_counter = 1

    for model, agent_count in gpu_models.items():
        clean_name = clean_model_name(model)
        bar_width = get_bar_width(agent_count)

        # Select gradient color
        gradient_file = gpu_gradients[gpu_bar_id_counter % len(gpu_gradients)] if gpu_gradients else 'gradient_01.png'

        # Create entries for each agent using this model
        for i in range(agent_count):
            agent = sample_agents[i % len(sample_agents)]

            # Generate random time slots
            start_hour = random.randint(0, 23)
            start_minute = random.choice([0, 15, 30, 45])
            start_time = f'{start_hour:02d}:{start_minute:02d}'

            end_hour = (start_hour + random.randint(1, 4)) % 24
            end_minute = random.choice([0, 15, 30, 45])
            end_time = f'{end_hour:02d}:{end_minute:02d}'

            entry = {
                'ai_model': clean_name,
                'agent': agent,
                'start_time': start_time,
                'end_time': end_time,
                'gpu_percent': str(random.randint(10, 90)),
                'memory_fraction': str(round(random.uniform(0.1, 0.8), 2)),
                'gpu_device': 'RTX 4090',
                'priority': random.choice(['High', 'Medium', 'Low']),
                'bar_id': str(gpu_bar_id_counter).zfill(6),
                'date': '2025-07-13',
                'id': str(uuid.uuid4()),
                'agent_id': str(uuid.uuid4()),
                'bar_width': bar_width,
                'gradient_file': gradient_file,
                'model_type': 'GPU',
            }

            gpu_schedule_data['2025-07-13'].append(entry)
            gpu_bar_id_counter += 1

    return cpu_schedule_data, gpu_schedule_data


def save_schedule_files():
    """Save the schedule data to JSON files"""
    cpu_data, gpu_data = create_schedule_entries()

    # Save CPU schedule
    with open('Schedule/schedule_data_CPU.json', 'w') as f:
        json.dump(cpu_data, f, indent=2)

    # Save GPU schedule
    with open('Schedule/schedule_data_GPU.json', 'w') as f:
        json.dump(gpu_data, f, indent=2)

    _zyg_log.info('✅ Schedule files created successfully!')
    _zyg_log.info(f'📊 CPU Schedule: {len(cpu_data["2025-07-13"])} entries')
    _zyg_log.info(f'📊 GPU Schedule: {len(gpu_data["2025-07-13"])} entries')
    _zyg_log.info(f'📊 Total Vertical Bars: {len(cpu_data["2025-07-13"]) + len(gpu_data["2025-07-13"])}')


if __name__ == '__main__':
    save_schedule_files()
