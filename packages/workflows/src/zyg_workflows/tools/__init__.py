# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
CLIPFARM Agent Tools
All tool implementations used by the 103-agent CrewAI system.

The eight submodules below each export their own `__all__`; this package
re-exports the modules rather than star-importing their names. Star imports made
every tool class a `zyg_workflows.tools.X` attribute whose defining module
neither a reader nor a linter could tell, and with eight of them a name defined
twice was silently decided by import order. Every caller across the four repos
already imports the submodule it needs, so nothing relied on the flat namespace.
"""

from . import (
    audio_tools,
    data_tools,
    ffmpeg_tools,
    infrastructure_tools,
    nlp_tools,
    pipeline_tools,
    speech_tools,
    vision_tools,
)

__all__ = [
    'audio_tools',
    'data_tools',
    'ffmpeg_tools',
    'infrastructure_tools',
    'nlp_tools',
    'pipeline_tools',
    'speech_tools',
    'vision_tools',
]
