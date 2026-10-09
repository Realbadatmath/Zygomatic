# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""BUSINESS_VERTICALS, part 1 of 3: affiliate_marketing and youtube_channels.

Verbatim from the single-file update_agent_model_mapping.py: lines 18-161, the
first two entries of the BUSINESS_VERTICALS literal, rewrapped unchanged in a part
dict that verticals.py splices back together in the original order.
"""

_PART_MARKETING = {
    'affiliate_marketing': {
        'agents': {
            'Affiliate-Marketing-Overseer': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine'],
                'gpu_models': ['Stable_Diffusion_1.5___XL', 'DreamShaper___RealisticVision'],
            },
            'Affiliate-Marketing-Agent': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine'],
                'gpu_models': ['Stable_Diffusion_1.5___XL', 'DreamShaper___RealisticVision'],
            },
            'Campaign-Builder-Agent': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine'],
                'gpu_models': ['Stable_Diffusion_1.5___XL', 'DreamShaper___RealisticVision'],
            },
            'SEO-Agent': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine'],
                'gpu_models': ['Stable_Diffusion_1.5___XL', 'DreamShaper___RealisticVision'],
            },
            'Conversion-Optimizer-Agent': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine'],
                'gpu_models': ['Stable_Diffusion_1.5___XL', 'DreamShaper___RealisticVision'],
            },
            'Content-Writer-Agent': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine'],
                'gpu_models': ['Stable_Diffusion_1.5___XL', 'DreamShaper___RealisticVision'],
            },
            'Email-Marketing-Agent': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine'],
                'gpu_models': ['Stable_Diffusion_1.5___XL', 'DreamShaper___RealisticVision'],
            },
            'PPC-Agent': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine'],
                'gpu_models': ['Stable_Diffusion_1.5___XL', 'DreamShaper___RealisticVision'],
            },
            'Social-Media-Marketing-Agent': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine'],
                'gpu_models': ['Stable_Diffusion_1.5___XL', 'DreamShaper___RealisticVision'],
            },
            'Analytics-Reporting-Agent': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine']
            },
            'Audience-Targeting-Agent': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine']
            },
            'Revenue-Optimization-Agent': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine']
            },
        }
    },
    'youtube_channels': {
        'agents': {
            'YouTube-Content-Overseer': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine'],
                'gpu_models': [
                    'Stable_Diffusion_1.5___XL',
                    'DreamShaper___RealisticVision',
                    'AnimateDiff',
                    'Stable_Video_Diffusion',
                ],
            },
            'YouTube-Script-Agent': {
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
            'YouTube-Thumbnail-Agent': {
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
            'YouTube-Video-Editor-Agent': {
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
            'YouTube-Audio-Agent': {
                'ai_models': [
                    'Claude_3',
                    'GPT-4',
                    'LLaMA_3',
                    'Mistral___Mixtral',
                    'HumanEval',
                    'CrewAI___OpenAgents',
                    'LangChain___Llamalend',
                ],
                'gpu_models': ['Bark', 'Tortoise_TTS', 'Whisper', 'librosa', 'ffmpeg', 'pyDub'],
            },
            'YouTube-SEO-Agent': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine']
            },
            'YouTube-Analytics-Agent': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine']
            },
            'YouTube-Community-Agent': {
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
            'YouTube-Scheduling-Agent': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine']
            },
            'YouTube-Trend-Analyst-Agent': {
                'ai_models': ['Claude_3', 'GPT-4', 'LLaMA_3', 'Mistral___Mixtral', 'Plotly', 'FastAPI', 'AI_QC_Engine']
            },
        }
    },
}
