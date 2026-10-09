# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The tables `fix_ai_model_mapping` writes, and the pure steps that shape them.

`fix_ai_model_mapping` was 384 lines, and 300 of them were one dict literal:
the model to agents table, the two model-family lists, and the template of the
`ai_model_agent_mapping.py` module the script generates. The script itself is
now the I/O around these — read the agent configuration, call `table`, render,
write, count — and every step that is only data in and data out lives here, so
the rendering and the counting can be checked without a configuration file on
disk or a file written to the working directory.

`table` takes the agent names because three rows (Claude 3, Llama 3, GPT-4 and
LangChain Llamalend) are "every agent there is": in the script those rows read
`list(agents.keys())` off the loaded configuration.
"""

# CPU-based models (for all tiers)
CPU_MODELS = [
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

# GPU-based models (only for Tier 1 agents)
GPU_MODELS = [
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


def table(agent_names):
    """The model to agents table, with *agent_names* standing in for "all agents".

    In: every agent id of the loaded configuration. Out: the full
    `{model: [agent, ...]}` mapping — the four rows that mean "any agent may use
    this model" are that list, the rest are the hand-maintained rosters.
    """
    return {
        # GPU-Intensive Models
        'Stable Diffusion 1.5 Xl': [
            '2D-Character-Designer-Agent',
            '3D-Character-Designer-Agent',
            '2D-Background-Artist-Agent',
            '3D-Environment-Agent',
            '3D-Modeling-Agent',
            '3D-Texturing-Agent',
            'YouTube-Thumbnail-Agent',
            '3D-Effects-Agent',
        ],
        'Dreamshaper Realisticvision': [
            '2D-Character-Designer-Agent',
            '3D-Character-Designer-Agent',
            '2D-Background-Artist-Agent',
            '3D-Environment-Agent',
            '3D-Modeling-Agent',
            '3D-Texturing-Agent',
            'YouTube-Thumbnail-Agent',
        ],
        'Stable Video Diffusion': [
            '3D-Animation-Agent',
            '2D-Animation-Agent',
            '3D-Series-Agent',
            '2D-Series-Agent',
            'YouTube-Video-Editor-Agent',
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
            'Portuguese-Voice-Agent',
            'Arabic-Voice-Agent',
            'Hindi-Voice-Agent',
            'Bengali-Voice-Agent',
            'Mandarin-Voice-Agent',
        ],
        'Bark-Voice-Cloning': ['2D-Voice-Agent', '3D-Voice-Agent', 'YouTube-Audio-Agent'],
        'Tortoise Tts': ['2D-Voice-Agent', '3D-Voice-Agent', 'YouTube-Audio-Agent'],
        'Realesrgan': ['3D-Effects-Agent', 'YouTube-Video-Editor-Agent'],
        '3D-Render-Farm-Manager-Agent': ['3D-Render-Farm-Manager-Agent'],
        # CPU-Intensive Models - ALL MODELS INCLUDED
        'Claude 3': list(agent_names),  # All agents can use Claude 3
        'Llama 3': list(agent_names),  # All agents can use Llama 3
        'GPT-4': list(agent_names),  # All agents can use GPT-4
        'Mistral Mixtral': [
            'Affiliate-Marketing-Overseer',
            '2D-Character-Designer-Agent',
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
            '2D-Series-Overseer',
            '2D-Voice-Agent',
            '3D-Animation-Agent',
            '3D-Character-Designer-Agent',
            '3D-Series-Overseer',
            '3D-Voice-Agent',
            'Arabic-Voice-Agent',
            'Bengali-Voice-Agent',
            'English-Voice-Agent',
            'French-Voice-Agent',
            'Hindi-Voice-Agent',
            'Mandarin-Voice-Agent',
            'Portuguese-Voice-Agent',
            'Spanish-Voice-Agent',
            '2D-Background-Artist-Agent',
            '3D-Environment-Agent',
            '3D-Modeling-Agent',
            '3D-Texturing-Agent',
            'YouTube-Content-Overseer',
            'YouTube-Audio-Agent',
            'YouTube-Video-Editor-Agent',
            'Business-Support-Overseer',
            'Animation-Media-Overseer',
            'Content-Production-Overseer',
        ],
        'Whisper': [
            'Voice-Localization-Master-Agent',
            '3D-Animation-Agent',
            '2D-Animation-Agent',
            'YouTube-Audio-Agent',
            '2D-Voice-Agent',
            '3D-Voice-Agent',
            'English-Voice-Agent',
            'Spanish-Voice-Agent',
            'French-Voice-Agent',
            'Arabic-Voice-Agent',
            'Hindi-Voice-Agent',
            'Bengali-Voice-Agent',
            'Mandarin-Voice-Agent',
        ],
        'Crewai Openagents': [
            'Affiliate-Marketing-Overseer',
            '2D-Character-Designer-Agent',
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
            '2D-Series-Overseer',
            '2D-Voice-Agent',
            '3D-Animation-Agent',
            '3D-Character-Designer-Agent',
            '3D-Series-Overseer',
            '3D-Voice-Agent',
            'Arabic-Voice-Agent',
            'Bengali-Voice-Agent',
            'English-Voice-Agent',
            'French-Voice-Agent',
            'Hindi-Voice-Agent',
            'Mandarin-Voice-Agent',
            'Portuguese-Voice-Agent',
            'Spanish-Voice-Agent',
            '2D-Background-Artist-Agent',
            '3D-Environment-Agent',
            '3D-Modeling-Agent',
            '3D-Texturing-Agent',
            'YouTube-Content-Overseer',
            'YouTube-Audio-Agent',
            'YouTube-Video-Editor-Agent',
            'Business-Support-Overseer',
            'Animation-Media-Overseer',
            'Content-Production-Overseer',
        ],
        'Humaneval': [
            '2D-Music-Agent',
            '3D-Music-Agent',
            'YouTube-Audio-Agent',
            '2D-Sound-Effects-Agent',
            '3D-Effects-Agent',
        ],
        'Fastapi': [
            'Affiliate-Marketing-Overseer',
            'Animation-Media-Overseer',
            'Business-Support-Overseer',
            'YouTube-Content-Overseer',
            'CEO-Agent',
            'CTO-Agent',
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
        'Davinci Resolve': ['YouTube-Video-Editor-Agent', '2D-Compositor-Agent', '3D-Compositor-Agent'],
        'Ai Qc Engine': [
            '2D-Quality-Control-Agent',
            '3D-Quality-Control-Agent',
            'Multi-Language-QC-Agent',
            'Error-Detector-Agent',
        ],
        'Clip': ['YouTube-Analytics-Agent'],
        'Lora': [
            '3D-Character-Designer-Agent',
            '2D-Character-Designer-Agent',
            '3D-Modeling-Agent',
            '3D-Texturing-Agent',
        ],
        'Plotly': ['Analytics-Reporting-Agent', 'YouTube-Analytics-Agent'],
        'Airflow': [
            '2D-Scheduling-Agent',
            '3D-Scheduling-Agent',
            'Daily-Production-Scheduler-Agent',
            'YouTube-Scheduling-Agent',
        ],
        'autosave_daemon': [
            '2D-Asset-Manager-Agent',
            '3D-Asset-Manager-Agent',
            'Document-Filing-Agent',
            'Case-Tracker-Agent',
        ],
        # Additional CPU models that were missing
        'LangChain Llamalend': list(agent_names),  # All agents can use LangChain
        'librosa': ['2D-Music-Agent', '3D-Music-Agent', 'YouTube-Audio-Agent', '2D-Sound-Effects-Agent'],
        'AssemblyAI': [
            '2D-Voice-Agent',
            '3D-Voice-Agent',
            'YouTube-Audio-Agent',
            'English-Voice-Agent',
            'Spanish-Voice-Agent',
            'French-Voice-Agent',
            'Arabic-Voice-Agent',
            'Hindi-Voice-Agent',
            'Bengali-Voice-Agent',
            'Mandarin-Voice-Agent',
        ],
        'Deepgram': [
            '2D-Voice-Agent',
            '3D-Voice-Agent',
            'YouTube-Audio-Agent',
            'English-Voice-Agent',
            'Spanish-Voice-Agent',
            'French-Voice-Agent',
            'Arabic-Voice-Agent',
            'Hindi-Voice-Agent',
            'Bengali-Voice-Agent',
            'Mandarin-Voice-Agent',
        ],
        # Additional GPU models that were missing
        'Kandinsky 2.2': [
            '2D-Character-Designer-Agent',
            '3D-Character-Designer-Agent',
            '2D-Background-Artist-Agent',
            '3D-Environment-Agent',
        ],
        'Deforum': ['3D-Animation-Agent', '2D-Animation-Agent', '3D-Series-Agent', '2D-Series-Agent'],
        'ComfyUI': ['3D-Modeling-Agent', '3D-Character-Designer-Agent', '2D-Character-Designer-Agent'],
        'VAE': [
            '3D-Character-Designer-Agent',
            '2D-Character-Designer-Agent',
            '3D-Modeling-Agent',
            '3D-Texturing-Agent',
        ],
        'ffmpeg': ['YouTube-Video-Editor-Agent', '2D-Compositor-Agent', '3D-Compositor-Agent'],
        'pyDub': ['YouTube-Audio-Agent', '2D-Music-Agent', '3D-Music-Agent'],
    }


_GENERATED_TAIL = """}

# Build agent_to_models mapping automatically
agent_to_models = {}
for model, agents in model_to_agents.items():
    for agent in agents:
        agent_to_models.setdefault(agent, []).append(model)

# CPU-based models (for all tiers)
CPU_MODELS = [
    'Claude 3', 'GPT-4', 'LLaMA 3', 'Mistral Mixtral', 'HumanEval',
    'CrewAI OpenAgents', 'LangChain Llamalend', 'Plotly', 'FastAPI',
    'AI QC Engine', 'Whisper', 'librosa', 'AssemblyAI', 'Deepgram'
]

# GPU-based models (only for Tier 1 agents)
GPU_MODELS = [
    'Stable Diffusion 1.5 XL', 'DreamShaper RealisticVision', 'AnimateDiff',
    'Stable Video Diffusion', 'ControlNet', 'RealESRGAN', 'Bark', 'Tortoise TTS',
    'Blender (bpy)', 'Kandinsky 2.2', 'Deforum', 'ComfyUI', 'Dreambooth',
    'LoRA', 'VAE', 'Davinci Resolve', 'ffmpeg', 'pyDub', 'CLIP'
]
"""


def render_mapping_module(model_to_agents):
    """The source of the `ai_model_agent_mapping.py` the script writes.

    In: the model to agents mapping. Out: the whole module text — the header,
    the table as a literal (one agent per line, in table order), the inversion
    loop and the two family lists. Nothing is written to disk here; the caller
    owns the file.
    """
    mapping_content = """# AI Model ↔ Agent Mapping for CrewAI Dashboard
# This file is auto-generated. Edit the mapping below as needed.

model_to_agents = {
"""

    for model, agents_list in model_to_agents.items():
        mapping_content += f'    "{model}": [\n'
        for agent in agents_list:
            mapping_content += f'        "{agent}",\n'
        mapping_content += '    ],\n'

    mapping_content += _GENERATED_TAIL
    return mapping_content


def count_mapped_models(model_to_agents):
    """How many of the CPU and GPU families the table actually maps.

    In: the model to agents mapping. Out: `(cpu, gpu)` — the number of its keys
    that name a `CPU_MODELS` entry and a `GPU_MODELS` entry. The two are counted
    independently: a key in neither list (the capitalised render-farm and
    daemon rows) counts in neither total.
    """
    cpu_model_count = 0
    gpu_model_count = 0
    for model in model_to_agents.keys():
        if model in CPU_MODELS:
            cpu_model_count += 1
        if model in GPU_MODELS:
            gpu_model_count += 1
    return cpu_model_count, gpu_model_count
