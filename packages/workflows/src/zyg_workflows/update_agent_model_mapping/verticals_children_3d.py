# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""BUSINESS_VERTICALS, part 2 of 3: 3d_children_series.

Verbatim from the single-file update_agent_model_mapping.py: lines 162-460.
"""

_PART_CHILDREN_3D = {
    '3d_children_series': {
        'agents': {
            '3D-Series-Overseer': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine'],
                'gpu_models': [
                    'Stable_Diffusion_1.5___XL',
                    'DreamShaper___RealisticVision',
                    'AnimateDiff',
                    'Stable_Video_Diffusion',
                    'Blender_(bpy)',
                ],
            },
            '3D-Series-Agent': {
                'ai_models': [
                    'Claude_3',
                    'GPT-4',
                    'LLaMA_3',
                    'Mistral___Mixtral',
                    'HumanEval',
                    'CrewAI___OpenAgents',
                    'LangChain___Llamalend',
                ],
                'gpu_models': [
                    'Stable_Video_Diffusion',
                    'AnimateDiff',
                    'Blender_(bpy)',
                    'Stable_Diffusion_1.5___XL',
                    'RealESRGAN',
                    'DreamShaper___RealisticVision',
                    'ControlNet',
                ],
            },
            '3D-Modeling-Agent': {
                'ai_models': [
                    'Claude_3',
                    'GPT-4',
                    'LLaMA_3',
                    'Mistral___Mixtral',
                    'HumanEval',
                    'CrewAI___OpenAgents',
                    'LangChain___Llamalend',
                ],
                'gpu_models': [
                    'Blender_(bpy)',
                    'Stable_Diffusion_1.5___XL',
                    'DreamShaper___RealisticVision',
                    'ControlNet',
                    'RealESRGAN',
                    'Dreambooth',
                    'LoRA',
                ],
            },
            '3D-Rendering-Agent': {
                'ai_models': [
                    'Claude_3',
                    'GPT-4',
                    'LLaMA_3',
                    'Mistral___Mixtral',
                    'HumanEval',
                    'CrewAI___OpenAgents',
                    'LangChain___Llamalend',
                ],
                'gpu_models': [
                    'Blender_(bpy)',
                    'Stable_Diffusion_1.5___XL',
                    'DreamShaper___RealisticVision',
                    'ControlNet',
                    'RealESRGAN',
                    'ComfyUI',
                    'Deforum',
                ],
            },
            '3D-Animation-Agent': {
                'ai_models': [
                    'Claude_3',
                    'GPT-4',
                    'LLaMA_3',
                    'Mistral___Mixtral',
                    'HumanEval',
                    'CrewAI___OpenAgents',
                    'LangChain___Llamalend',
                ],
                'gpu_models': [
                    'AnimateDiff',
                    'Stable_Video_Diffusion',
                    'Blender_(bpy)',
                    'Stable_Diffusion_1.5___XL',
                    'RealESRGAN',
                    'DreamShaper___RealisticVision',
                    'ControlNet',
                ],
            },
            '3D-Environment-Agent': {
                'ai_models': [
                    'Claude_3',
                    'GPT-4',
                    'LLaMA_3',
                    'Mistral___Mixtral',
                    'HumanEval',
                    'CrewAI___OpenAgents',
                    'LangChain___Llamalend',
                ],
                'gpu_models': [
                    'Blender_(bpy)',
                    'Stable_Diffusion_1.5___XL',
                    'DreamShaper___RealisticVision',
                    'ControlNet',
                    'RealESRGAN',
                    'Dreambooth',
                    'LoRA',
                ],
            },
            '3D-Effects-Agent': {
                'ai_models': [
                    'Claude_3',
                    'GPT-4',
                    'LLaMA_3',
                    'Mistral___Mixtral',
                    'HumanEval',
                    'CrewAI___OpenAgents',
                    'LangChain___Llamalend',
                ],
                'gpu_models': [
                    'Blender_(bpy)',
                    'Stable_Diffusion_1.5___XL',
                    'DreamShaper___RealisticVision',
                    'ControlNet',
                    'RealESRGAN',
                    'ComfyUI',
                    'Deforum',
                ],
            },
            '3D-Rigging-Agent': {
                'ai_models': [
                    'Claude_3',
                    'GPT-4',
                    'LLaMA_3',
                    'Mistral___Mixtral',
                    'HumanEval',
                    'CrewAI___OpenAgents',
                    'LangChain___Llamalend',
                ],
                'gpu_models': [
                    'Blender_(bpy)',
                    'Stable_Diffusion_1.5___XL',
                    'DreamShaper___RealisticVision',
                    'ControlNet',
                ],
            },
            '3D-Texturing-Agent': {
                'ai_models': [
                    'Claude_3',
                    'GPT-4',
                    'LLaMA_3',
                    'Mistral___Mixtral',
                    'HumanEval',
                    'CrewAI___OpenAgents',
                    'LangChain___Llamalend',
                ],
                'gpu_models': [
                    'Stable_Diffusion_1.5___XL',
                    'DreamShaper___RealisticVision',
                    'ControlNet',
                    'Dreambooth',
                    'LoRA',
                    'VAE',
                ],
            },
            '3D-Lighting-Agent': {
                'ai_models': [
                    'Claude_3',
                    'GPT-4',
                    'LLaMA_3',
                    'Mistral___Mixtral',
                    'HumanEval',
                    'CrewAI___OpenAgents',
                    'LangChain___Llamalend',
                ],
                'gpu_models': [
                    'Blender_(bpy)',
                    'Stable_Diffusion_1.5___XL',
                    'DreamShaper___RealisticVision',
                    'ControlNet',
                    'ComfyUI',
                ],
            },
            '3D-Compositor-Agent': {
                'ai_models': [
                    'Claude_3',
                    'GPT-4',
                    'LLaMA_3',
                    'Mistral___Mixtral',
                    'HumanEval',
                    'CrewAI___OpenAgents',
                    'LangChain___Llamalend',
                ],
                'gpu_models': [
                    'Davinci_Resolve',
                    'Stable_Video_Diffusion',
                    'AnimateDiff',
                    'RealESRGAN',
                    'ffmpeg',
                    'pyDub',
                ],
            },
            '3D-Storyboard-Agent': {
                'ai_models': [
                    'Claude_3',
                    'GPT-4',
                    'LLaMA_3',
                    'Mistral___Mixtral',
                    'HumanEval',
                    'CrewAI___OpenAgents',
                    'LangChain___Llamalend',
                ],
                'gpu_models': [
                    'Stable_Diffusion_1.5___XL',
                    'DreamShaper___RealisticVision',
                    'ControlNet',
                    'Kandinsky_2.2',
                ],
            },
            '3D-Script-Agent': {
                'ai_models': [
                    'Claude_3',
                    'GPT-4',
                    'LLaMA_3',
                    'Mistral___Mixtral',
                    'HumanEval',
                    'CrewAI___OpenAgents',
                    'LangChain___Llamalend',
                ]
            },
            '3D-Character-Designer-Agent': {
                'ai_models': [
                    'Claude_3',
                    'GPT-4',
                    'LLaMA_3',
                    'Mistral___Mixtral',
                    'HumanEval',
                    'CrewAI___OpenAgents',
                    'LangChain___Llamalend',
                ],
                'gpu_models': [
                    'Stable_Diffusion_1.5___XL',
                    'DreamShaper___RealisticVision',
                    'ControlNet',
                    'Dreambooth',
                    'LoRA',
                    'ComfyUI',
                ],
            },
            '3D-Voice-Agent': {
                'ai_models': [
                    'Claude_3',
                    'GPT-4',
                    'LLaMA_3',
                    'Mistral___Mixtral',
                    'HumanEval',
                    'CrewAI___OpenAgents',
                    'LangChain___Llamalend',
                ],
                'gpu_models': ['Bark', 'Tortoise_TTS', 'Whisper', 'librosa', 'AssemblyAI', 'Deepgram'],
            },
            '3D-Music-Agent': {
                'ai_models': [
                    'Claude_3',
                    'GPT-4',
                    'LLaMA_3',
                    'Mistral___Mixtral',
                    'HumanEval',
                    'CrewAI___OpenAgents',
                    'LangChain___Llamalend',
                ],
                'gpu_models': ['Bark', 'Tortoise_TTS', 'Whisper', 'librosa', 'AssemblyAI', 'Deepgram'],
            },
            '3D-Quality-Control-Agent': {
                'ai_models': [
                    'Claude_3',
                    'GPT-4',
                    'LLaMA_3',
                    'Mistral___Mixtral',
                    'HumanEval',
                    'CrewAI___OpenAgents',
                    'LangChain___Llamalend',
                ],
                'gpu_models': ['OpenCV', 'ImageHash_+_OpenCV', 'YOLOv8___Segment_Anything'],
            },
            '3D-Scheduling-Agent': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine']
            },
            '3D-Asset-Manager-Agent': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine']
            },
            '3D-Render-Farm-Manager-Agent': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine']
            },
        }
    },
}
