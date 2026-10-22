#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Comprehensive AI Model Analysis
This script will:
1. Count all AI models available in the system
2. Calculate total vertical bars needed for all agent-model combinations
3. Compare current vs expected model usage
4. Generate detailed report
"""

import json

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def load_agent_configurations():
    """Load agent configurations"""
    try:
        with open('agent_configurations.json', 'r') as f:
            return json.load(f)
    except Exception as e:
        _zyg_log.info(f'Error loading agent_configurations.json: {e}')
        return None


def load_agent_model_mapping():
    """Load agent model bar mapping"""
    try:
        with open('agent_model_bar_mapping.json', 'r') as f:
            return json.load(f)
    except Exception as e:
        _zyg_log.info(f'Error loading agent_model_bar_mapping.json: {e}')
        return None


def get_all_available_models():
    """Get all available AI models from the system"""

    # Models from ai_model_agent_mapping.py
    cpu_models = [
        'Claude 3',
        'GPT-4',
        'LLaMA 3',
        'Mistral Mixtral',
        'HumanEval',
        'CrewAI OpenAgents',
        'LangChain Llamalend',
        'Plotly',
        'FastAPI',
        'AI QC Engine',
        'Whisper',
        'librosa',
        'AssemblyAI',
        'Deepgram',
    ]

    gpu_models = [
        'Stable Diffusion 1.5 XL',
        'DreamShaper RealisticVision',
        'AnimateDiff',
        'Stable Video Diffusion',
        'ControlNet',
        'RealESRGAN',
        'Bark',
        'Tortoise TTS',
        'Blender (bpy)',
        'Kandinsky 2.2',
        'Deforum',
        'ComfyUI',
        'Dreambooth',
        'LoRA',
        'VAE',
        'Davinci Resolve',
        'ffmpeg',
        'pyDub',
        'CLIP',
    ]

    # Additional models from web GUI
    web_gui_models = [
        'Stable_Diffusion_1.5___XL',
        'DreamShaper___RealisticVision',
        'AnimateDiff',
        'Stable_Video_Diffusion',
        'ControlNet',
        'RealESRGAN',
        'Bark',
        'Tortoise_TTS',
        'Blender_(bpy)',
        'Kandinsky_2.2',
        'Deforum',
        'ComfyUI',
        'Dreambooth',
        'LoRA',
        'VAE',
        'Davinci_Resolve',
        'ffmpeg',
        'pyDub',
        'CLIP',
        'Claude_3',
        'GPT-4',
        'LLaMA_3',
        'Mistral___Mixtral',
        'HumanEval',
        'CrewAI___OpenAgents',
        'LangChain___Llamalend',
        'Plotly',
        'FastAPI',
        'AI_QC_Engine',
        'Whisper',
        'librosa',
        'AssemblyAI',
        'Deepgram',
    ]

    # Models from model_to_agents mapping
    mapping_models = [
        'Claude 3',
        'Llama 3',
        'Crewai Openagents',
        'Animatediff',
        'Stable Video Diffusion',
        'Whisper',
        'Controlnet',
        'Dreamshaper Realisticvision',
        'Stable Diffusion 1.5 Xl',
        'Dreambooth',
        'Mistral Mixtral',
        'Bark',
        'Tortoise Tts',
        'Bark-Voice-Cloning',
        'Blender (Bpy)',
        'Ai Qc Engine',
        'autosave_daemon',
        'Realesrgan',
        'Humaneval',
        'Airflow',
        '3D-Render-Farm-Manager-Agent',
        'Plotly',
        'Clip',
        'Davinci Resolve',
    ]

    # Combine all models and remove duplicates
    all_models = set()
    all_models.update(cpu_models)
    all_models.update(gpu_models)
    all_models.update(web_gui_models)
    all_models.update(mapping_models)

    return list(all_models)


def analyze_current_model_usage():
    """Analyze current model usage in agent configurations"""
    _zyg_log.info('=== CURRENT MODEL USAGE ANALYSIS ===')

    configs = load_agent_configurations()
    if not configs:
        return {}

    agents = configs.get('agents', {})
    current_models = set()
    model_usage = {}

    for _agent_name, config in agents.items():
        ai_models = config.get('ai_models', [])
        for model in ai_models:
            current_models.add(model)
            model_usage[model] = model_usage.get(model, 0) + 1

    _zyg_log.info(f'Current models in use: {len(current_models)}')
    _zyg_log.info(f'Total model assignments: {sum(model_usage.values())}')

    _zyg_log.info('\nCurrent Model Usage:')
    for model, count in sorted(model_usage.items(), key=lambda x: x[1], reverse=True):
        _zyg_log.info(f'  {model}: {count} agents')

    return current_models, model_usage


def calculate_expected_model_usage():
    """Calculate expected model usage based on agent specializations"""
    _zyg_log.info('\n=== EXPECTED MODEL USAGE CALCULATION ===')

    configs = load_agent_configurations()
    if not configs:
        return {}

    agents = configs.get('agents', {})
    expected_models = set()
    expected_usage = {}

    # Define expected models for different agent types
    model_assignments = {
        # Base models for all agents
        'base_models': ['Claude 3', 'Llama 3'],
        # Management tier models
        'management_models': ['Crewai Openagents'],
        # Animation models
        'animation_models': [
            'Stable Diffusion 1.5 XL',
            'DreamShaper RealisticVision',
            'AnimateDiff',
            'Stable Video Diffusion',
            'ControlNet',
            'Dreambooth',
            'LoRA',
            'VAE',
        ],
        # Voice/Audio models
        'voice_models': ['ElevenLabs', 'Whisper', 'Bark', 'Tortoise TTS', 'Bark-Voice-Cloning'],
        # Video/Editor models
        'video_models': ['Runway', 'Pika Labs', 'Davinci Resolve', 'ffmpeg', 'pyDub'],
        # SEO/Analytics models
        'analytics_models': ['Google Analytics', 'SEMrush', 'Plotly', 'CLIP'],
        # 3D models
        '3d_models': ['Blender (bpy)', 'RealESRGAN', 'ComfyUI'],
        # Quality control models
        'qc_models': ['AI QC Engine'],
        # Scheduling models
        'scheduling_models': ['Airflow'],
        # Music models
        'music_models': ['HumanEval', 'librosa'],
        # Additional specialized models
        'specialized_models': [
            'Kandinsky 2.2',
            'Deforum',
            'AssemblyAI',
            'Deepgram',
            'GPT-4',
            'Mistral Mixtral',
            'LangChain Llamalend',
            'FastAPI',
        ],
    }

    # Calculate expected usage for each agent
    for agent_name, config in agents.items():
        tier = config.get('tier', 'Specialist')
        department = config.get('department', 'General')

        # Start with base models
        expected_agent_models = model_assignments['base_models'].copy()

        # Add management models for management tier
        if tier == 'Management':
            expected_agent_models.extend(model_assignments['management_models'])

        # Add specialized models based on agent type
        if 'Animation' in agent_name or '2D' in agent_name or '3D' in agent_name:
            expected_agent_models.extend(model_assignments['animation_models'])
            if '3D' in agent_name:
                expected_agent_models.extend(model_assignments['3d_models'])

        if 'Voice' in agent_name or 'Audio' in agent_name:
            expected_agent_models.extend(model_assignments['voice_models'])

        if 'Video' in agent_name or 'Editor' in agent_name:
            expected_agent_models.extend(model_assignments['video_models'])

        if 'SEO' in agent_name or 'Analytics' in agent_name:
            expected_agent_models.extend(model_assignments['analytics_models'])

        if 'Quality' in agent_name or 'QC' in agent_name:
            expected_agent_models.extend(model_assignments['qc_models'])

        if 'Scheduling' in agent_name or 'Scheduler' in agent_name:
            expected_agent_models.extend(model_assignments['scheduling_models'])

        if 'Music' in agent_name or 'Sound' in agent_name:
            expected_agent_models.extend(model_assignments['music_models'])

        # Add some specialized models for certain departments
        if department == 'Production':
            expected_agent_models.extend(model_assignments['video_models'])

        if department == 'Animation':
            expected_agent_models.extend(model_assignments['animation_models'])

        # Remove duplicates and count usage
        expected_agent_models = list(set(expected_agent_models))
        for model in expected_agent_models:
            expected_models.add(model)
            expected_usage[model] = expected_usage.get(model, 0) + 1

    _zyg_log.info(f'Expected models: {len(expected_models)}')
    _zyg_log.info(f'Expected total assignments: {sum(expected_usage.values())}')

    _zyg_log.info('\nExpected Model Usage:')
    for model, count in sorted(expected_usage.items(), key=lambda x: x[1], reverse=True):
        _zyg_log.info(f'  {model}: {count} agents')

    return expected_models, expected_usage


def calculate_vertical_bars():
    """Calculate total vertical bars needed"""
    _zyg_log.info('\n=== VERTICAL BARS CALCULATION ===')

    # Get all available models
    all_models = get_all_available_models()

    # Get current and expected usage
    current_models, current_usage = analyze_current_model_usage()
    expected_models, expected_usage = calculate_expected_model_usage()

    # Calculate bars for current usage
    current_total_bars = sum(current_usage.values())

    # Calculate bars for expected usage
    expected_total_bars = sum(expected_usage.values())

    # Calculate bars for all available models (if every agent could use every model)
    configs = load_agent_configurations()
    total_agents = len(configs.get('agents', {})) if configs else 0
    max_possible_bars = len(all_models) * total_agents

    _zyg_log.info(f'Total available AI models: {len(all_models)}')
    _zyg_log.info(f'Total agents: {total_agents}')
    _zyg_log.info(f'Current total bars: {current_total_bars}')
    _zyg_log.info(f'Expected total bars: {expected_total_bars}')
    _zyg_log.info(f'Maximum possible bars: {max_possible_bars}')

    return {
        'available_models': len(all_models),
        'total_agents': total_agents,
        'current_bars': current_total_bars,
        'expected_bars': expected_total_bars,
        'max_possible_bars': max_possible_bars,
        'all_models': all_models,
        'current_usage': current_usage,
        'expected_usage': expected_usage,
    }


def generate_comprehensive_report():
    """Generate comprehensive analysis report"""
    _zyg_log.info('\n' + '=' * 80)
    _zyg_log.info('COMPREHENSIVE AI MODEL ANALYSIS REPORT')
    _zyg_log.info('=' * 80)

    # Calculate all metrics
    results = calculate_vertical_bars()

    _zyg_log.info('\n📊 SUMMARY STATISTICS:')
    _zyg_log.info(f'   Available AI Models: {results["available_models"]}')
    _zyg_log.info(f'   Total Agents: {results["total_agents"]}')
    _zyg_log.info(f'   Current Vertical Bars: {results["current_bars"]}')
    _zyg_log.info(f'   Expected Vertical Bars: {results["expected_bars"]}')
    _zyg_log.info(f'   Maximum Possible Bars: {results["max_possible_bars"]}')

    _zyg_log.info(f'\n🤖 AVAILABLE AI MODELS ({results["available_models"]} total):')
    for i, model in enumerate(sorted(results['all_models']), 1):
        _zyg_log.info(f'   {i:2d}. {model}')

    _zyg_log.info('\n📈 USAGE COMPARISON:')
    _zyg_log.info(f'   Current vs Expected Bars: {results["current_bars"]} vs {results["expected_bars"]}')
    _zyg_log.info(f'   Difference: {results["expected_bars"] - results["current_bars"]}')
    _zyg_log.info(f'   Utilization: {results["current_bars"] / results["expected_bars"] * 100:.1f}% of expected')

    _zyg_log.info('\n🎯 RECOMMENDATIONS:')
    if results['current_bars'] < results['expected_bars']:
        _zyg_log.info(
            f'   ⚠️  Current system is using {results["expected_bars"] - results["current_bars"]} fewer bars than expected'
        )
        _zyg_log.info('   💡 Consider adding missing model assignments to agents')
    else:
        _zyg_log.info('   ✅ Current system is properly utilizing AI models')

    _zyg_log.info('\n🔧 TECHNICAL DETAILS:')
    _zyg_log.info('   Each vertical bar represents one agent-model combination')
    _zyg_log.info(f'   Total unique bar IDs needed: {results["expected_bars"]}')
    _zyg_log.info('   Format: AgentName__ModelName')

    _zyg_log.info('\n🎯 FINAL ANSWER:')
    _zyg_log.info(f'   There should be approximately {results["available_models"]} AI models in the system')
    _zyg_log.info(f'   Total vertical bars needed: {results["expected_bars"]}')
    _zyg_log.info(f'   Current vertical bars: {results["current_bars"]}')

    _zyg_log.info('=' * 80)


def main():
    """Main analysis function"""
    print('Starting Comprehensive AI Model Analysis...')
    generate_comprehensive_report()


if __name__ == '__main__':
    main()
