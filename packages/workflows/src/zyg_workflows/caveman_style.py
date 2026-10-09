#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Caveman Style Module
Brevity layer for LLM outputs and prompts.
Provides reusable instruction templates and helpers to inject caveman instructions into prompts.

Philosophy:
- Influence LLM behavior through prompt instructions (not post-processing)
- Preserve exact outputs for code, commands, JSON, model names, and technical terms
- Apply only to natural-language responses: chat replies, summaries, explanations, status updates
- Do not rewrite conversation history; only control the current reply style
"""

import os
from enum import Enum
from typing import Optional


class CavemanStyle(Enum):
    """Caveman style intensity levels."""

    OFF = 'off'  # No caveman style
    BASE = 'base'  # Basic brevity
    EXTENDED = 'extended'  # More aggressive brevity
    AGGRESSIVE = 'aggressive'  # Maximum brevity


# Style instruction templates
_CAVEMAN_INSTRUCTIONS = {
    CavemanStyle.OFF: '',
    CavemanStyle.BASE: (
        'Answer concisely. Use short, technical sentences. Avoid filler. Keep names and accuracy intact.'
    ),
    CavemanStyle.EXTENDED: (
        'Answer in caveman style: short phrases, technical precision, no over-explanation unless asked. '
        'Preserve all proper names, code, model IDs, and technical terms exactly. '
        'Use abbreviations only if standard (e.g., API, LLM, CPU). '
        'Skip pleasantries and verbose preambles.'
    ),
    CavemanStyle.AGGRESSIVE: (
        'Ultra-concise caveman reply: fragments ok if clear. Technical precision required. '
        'Preserve exact names, code, paths, and model identifiers. '
        'No filler, no explanations unless critical. '
        "Example: 'bug in line 42. fix: change X to Y. tested, works.'"
    ),
}


def get_caveman_style() -> CavemanStyle:
    """
    Get caveman style setting from environment or default.

    Environment variable: CAVEMAN_STYLE_ENABLED (true/false for BASE)
    Environment variable: CAVEMAN_STYLE_LEVEL (off/base/extended/aggressive)

    Defaults to OFF if not configured.
    """
    level_str = os.environ.get('CAVEMAN_STYLE_LEVEL', '').lower().strip()
    if level_str and level_str in [s.value for s in CavemanStyle]:
        return CavemanStyle(level_str)

    # Check legacy CAVEMAN_STYLE_ENABLED flag
    if os.environ.get('CAVEMAN_STYLE_ENABLED', '').lower() in ('true', '1', 'yes'):
        return CavemanStyle.BASE

    return CavemanStyle.OFF


def get_caveman_instruction(style: Optional[CavemanStyle] = None) -> str:
    """
    Get caveman instruction string for the given style.
    If style is None, uses the environment-configured style.

    Args:
        style: CavemanStyle enum value, or None to use environment setting

    Returns:
        Instruction string (empty if OFF)
    """
    if style is None:
        style = get_caveman_style()
    return _CAVEMAN_INSTRUCTIONS.get(style, '')


def inject_caveman_into_system_prompt(
    system_prompt: str, style: Optional[CavemanStyle] = None, append: bool = True
) -> str:
    """
    Inject caveman instruction into a system prompt.

    By default, appends the caveman instruction to the existing prompt.
    This allows the system prompt to retain its original instructions
    while adding the caveman brevity layer.

    Args:
        system_prompt: The original system prompt
        style: CavemanStyle enum value, or None to use environment setting
        append: If True, append to existing prompt; if False, prepend

    Returns:
        Updated system prompt with caveman instruction
    """
    caveman_instruction = get_caveman_instruction(style)
    if not caveman_instruction:
        return system_prompt

    if append:
        return f'{system_prompt}\n\n{caveman_instruction}'
    else:
        return f'{caveman_instruction}\n\n{system_prompt}'


def should_apply_caveman(content_type: str = 'default') -> bool:
    """
    Check if caveman style should be applied for a given content type.

    Safe to apply: chat, reply, summary, explanation, status
    Unsafe to apply: code, command, json, path, model_id, instruction

    Args:
        content_type: Type of content (default: 'default' = apply caveman)

    Returns:
        True if caveman style should be applied
    """
    style = get_caveman_style()
    if style == CavemanStyle.OFF:
        return False

    # Never apply to exact-output types
    unsafe_types = {'code', 'command', 'json', 'path', 'model_id', 'instruction', 'raw'}
    if content_type.lower() in unsafe_types:
        return False

    return True


def caveman_summary(text: str, max_lines: int = 3) -> str:
    """
    Create a caveman-style summary by truncating to key lines.
    Useful for error messages, status updates, etc.

    This is a simple truncation helper, not a full rewrite.
    Does NOT guarantee perfect caveman style — use prompt injection instead.

    Args:
        text: Text to summarize
        max_lines: Maximum number of lines to keep

    Returns:
        Truncated text
    """
    lines = text.strip().split('\n')
    return '\n'.join(lines[:max_lines])


# Public API
__all__ = [
    'CavemanStyle',
    'get_caveman_style',
    'get_caveman_instruction',
    'inject_caveman_into_system_prompt',
    'should_apply_caveman',
    'caveman_summary',
]
