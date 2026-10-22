#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Migrate Schedule Data to Model IDs
Converts all existing schedule entries from model names to model IDs
"""

import json
import os
import shutil
from datetime import datetime

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def migrate_schedule_to_model_ids():
    """Migrate all schedule data files to use model IDs instead of model names"""

    _zyg_log.info('🔧 MIGRATING SCHEDULE DATA TO MODEL IDS')
    _zyg_log.info('=' * 50)

    # Load the model ID mapping
    model_id_path = 'gpu_ai_models.json'
    if not os.path.exists(model_id_path):
        _zyg_log.info(f'❌ Model ID mapping file not found: {model_id_path}')
        return

    with open(model_id_path, 'r', encoding='utf-8') as f:
        model_id_map = json.load(f)

    # Create reverse mapping from name to ID
    name_to_id = {}
    for model_id, model_info in model_id_map.items():
        name_to_id[model_info['name']] = model_id

    # Add some common variations that might exist in the data
    name_variations = {
        'Claude_3': '1030',
        'Stable Diffusion 1.5 XL': '1001',
        'Stable Diffusion 1.5 Xl': '1001',
        'Dreamshaper Realisticvision': '1002',
        'Animatediff': '1003',
        'AnimateDiff': '1003',
        'Stable Video Diffusion': '1004',
        'Controlnet': '1005',
        'ControlNet': '1005',
        'Realesrgan': '1006',
        'Bark': '1007',
        'Tortoise TTS': '1008',
        'Tortoise Tts': '1008',
        'Blender (bpy)': '1009',
        'Blender (Bpy)': '1009',
        'Kandinsky 2.2': '1010',
        'Deforum': '1011',
        'ComfyUI': '1012',
        'Dreambooth': '1013',
        'Ffmpeg': '1014',
        'Pydub': '1015',
        'Clip': '1016',
        'Cia 3d': '1017',
        'Llama 3': '1018',
        'Mistral Mixtral': '1019',
        'HumanEval': '1020',
        'Humaneval': '1020',
        'Crewai Openagents': '1021',
        'Langchain Llamalend': '1022',
        'Plotly': '1023',
        'Fastapi': '1024',
        'AI QC Engine': '1025',
        'Ai Qc Engine': '1025',
        'AI_QC_Engine': '1025',
        'Whisper': '1026',
        'Librosa': '1027',
        'AssemblyAI': '1028',
        'Deepgram': '1029',
        'GPT-4': '1031',
        'Bark-Voice-Cloning': '1032',
        'Airflow': '1033',
        'autosave_daemon': '1034',
        'VAE': '1035',
        'LoRA': '1036',
        'Davinci Resolve': '1037',
        'pyDub': '1038',
        'LangChain Llamalend': '1039',
        'CrewAI OpenAgents': '1040',
        'ElevenLabs': '1041',
        'Midjourney': '1042',
        'SEMrush': '1043',
        'Runway': '1044',
        'Stable Diffusion': '1045',
        'Pika Labs': '1046',
        'Google Analytics': '1047',
    }

    name_to_id.update(name_variations)

    _zyg_log.info(f'📊 Loaded {len(name_to_id)} model name to ID mappings')

    # List of schedule files to migrate
    schedule_files = [
        'Schedule/schedule_data_ACTIVE.json',
        'Schedule/schedule_data_GPU.json',
        'Schedule/schedule_data_CPU.json',
        'Schedule/schedule_data.json',
    ]

    total_converted = 0
    total_errors = 0

    for schedule_file in schedule_files:
        if not os.path.exists(schedule_file):
            _zyg_log.info(f'⚠️  Schedule file not found: {schedule_file}')
            continue

        _zyg_log.info(f'\n📁 Processing: {schedule_file}')

        # Create backup
        backup_file = f'{schedule_file}.backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        shutil.copy2(schedule_file, backup_file)
        _zyg_log.info(f'💾 Backup created: {backup_file}')

        # Load schedule data
        with open(schedule_file, 'r', encoding='utf-8') as f:
            schedule_data = json.load(f)

        file_converted = 0
        file_errors = 0

        # Process each date
        for _date_key, entries in schedule_data.items():
            if not isinstance(entries, list):
                continue

            for entry in entries:
                if not isinstance(entry, dict):
                    continue

                model_name = entry.get('ai_model')
                if not model_name:
                    continue

                # Skip if already a numeric ID
                if str(model_name).isdigit():
                    continue

                if model_name in name_to_id:
                    model_id = name_to_id[model_name]
                    entry['ai_model'] = model_id
                    file_converted += 1
                    _zyg_log.info(f'✅ Converted: {model_name} -> {model_id}')
                else:
                    _zyg_log.info(f"⚠️  Warning: Model name '{model_name}' not found in ID mapping")
                    file_errors += 1

        # Save the migrated data
        with open(schedule_file, 'w', encoding='utf-8') as f:
            json.dump(schedule_data, f, indent=2, ensure_ascii=False)

        _zyg_log.info(f'📈 File summary: {file_converted} converted, {file_errors} errors')
        total_converted += file_converted
        total_errors += file_errors

    _zyg_log.info('\n🎉 MIGRATION COMPLETE')
    _zyg_log.info(f'✅ Total entries converted: {total_converted}')
    _zyg_log.info(f'⚠️  Total errors: {total_errors}')
    _zyg_log.info('💾 All files backed up before migration')


if __name__ == '__main__':
    migrate_schedule_to_model_ids()
