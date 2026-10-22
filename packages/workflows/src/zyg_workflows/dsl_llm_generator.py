#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
DSL LLM Generator — Use caveman-style prompts to generate SCENE DSL from input.

This module provides:
  - Caveman-style prompts optimized for DSL generation
  - LLM integration (Claude, Ollama, etc.)
  - Input parsers for Research findings, Script beats, etc.
  - DSL generation with validation
"""

from zyg_workflows import paths
from zyg_workflows.dsl_schema import Scene
from zyg_workflows.dsl_validator import DSLValidator
import re

try:
    import sys

    _CAVEMAN_DIR = str(paths.ZYG_LEGACY_ROOT / 'orchestrator' / 'zyg-orchestrator' / 'legacy' / 'flask_dashboard')
    _inserted = _CAVEMAN_DIR not in sys.path
    if _inserted:
        # Append (not insert at 0) so the orchestrator dir doesn't shadow
        # same-named modules (e.g. dashboard_config) under ZYG_CREWS_ROOT.
        sys.path.append(_CAVEMAN_DIR)
    try:
        from zyg_workflows.caveman_style import get_caveman_instruction, CavemanStyle

        CAVEMAN_AVAILABLE = True
    finally:
        if _inserted and _CAVEMAN_DIR in sys.path:
            sys.path.remove(_CAVEMAN_DIR)
except ImportError:
    CAVEMAN_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# Caveman-style DSL prompts
# ─────────────────────────────────────────────────────────────────────────────

DSL_GENERATION_PROMPT_BASE = """You are a DSL generator for documentary production.
Convert input (research findings, script beats, descriptions) into structured SCENE DSL YAML.

Output format: Valid YAML matching the SCENE schema.
Required fields: metadata.id, metadata.duration, semantic.subject, visual.*, audio.*
Keep descriptions concise. No prose. Use exact enum values only.

Input:
{input_text}

Output SCENE DSL (YAML only, no markdown, no explanations):"""

DSL_GENERATION_PROMPT_CAVEMAN = """DSL GENERATOR. Convert input → SCENE DSL YAML.
Output: Valid YAML. Required: id, duration, subject, visual, audio.
Enums only. No prose. Concise.

Input:
{input_text}

SCENE DSL (YAML):"""


# ─────────────────────────────────────────────────────────────────────────────
# DSL Generator
# ─────────────────────────────────────────────────────────────────────────────


class DSLLLMGenerator:
    """Generate SCENE DSL from research/script input using LLMs."""

    def __init__(self, use_caveman: bool = True):
        """
        Initialize generator.

        Args:
            use_caveman: Use caveman-style compressed prompts (if available)
        """
        self.use_caveman = use_caveman and CAVEMAN_AVAILABLE
        self.validator = DSLValidator()

    def get_system_prompt(self) -> str:
        """Get system prompt (optionally with caveman style)."""
        base_prompt = (
            'You are a DSL generator for documentary production pipelines. '
            'Your job is to convert semantic descriptions into structured SCENE DSL objects. '
            'Always output valid YAML. Never hallucinate enum values. '
            'If unsure, use sensible defaults.'
        )

        if self.use_caveman:
            caveman_instruction = get_caveman_instruction(CavemanStyle.EXTENDED)
            return f'{base_prompt}\n\n{caveman_instruction}'

        return base_prompt

    def get_generation_prompt(self, input_text: str) -> str:
        """Get generation prompt (caveman or normal)."""
        if self.use_caveman:
            return DSL_GENERATION_PROMPT_CAVEMAN.format(input_text=input_text)
        else:
            return DSL_GENERATION_PROMPT_BASE.format(input_text=input_text)

    def generate_from_research(
        self,
        research_findings: str,
        topic_id: str = 'research',
        llm_callable=None,
    ) -> Scene:
        """
        Generate SCENE DSL from research findings.

        Args:
            research_findings: Raw research text (findings, key points, etc.)
            topic_id: Topic identifier (used in scene ID)
            llm_callable: Function that takes (system_prompt, user_prompt) → response

        Returns:
            Scene object (validated)

        Raises:
            DSLValidationError: If generated DSL is invalid
        """
        if not llm_callable:
            raise ValueError('llm_callable required (e.g., Claude, Ollama, etc.)')

        # Prepare prompt
        system_prompt = self.get_system_prompt()
        user_prompt = self.get_generation_prompt(research_findings)

        # Call LLM
        response = llm_callable(system_prompt, user_prompt)

        # Parse YAML
        scene = self._parse_yaml_response(response)

        # Set ID if not present
        if not scene.metadata.id:
            scene.metadata.id = f'{topic_id}_research'

        # Validate
        self.validator.validate_strict(scene)

        return scene

    def generate_from_script_beat(
        self,
        script_beat: str,
        sequence: int = 0,
        llm_callable=None,
    ) -> Scene:
        """
        Generate SCENE DSL from a script beat.

        Args:
            script_beat: Script text for one beat (paragraph or short section)
            sequence: Position in sequence
            llm_callable: LLM function

        Returns:
            Scene object (validated)
        """
        if not llm_callable:
            raise ValueError('llm_callable required')

        # Extract key info from beat
        input_with_context = (
            f'Script beat #{sequence}:\n{script_beat}\n\n'
            f'Generate SCENE DSL for this beat. '
            f'Set metadata.sequence={sequence}. '
            f'Infer emotional arc, camera movement, lighting.'
        )

        system_prompt = self.get_system_prompt()
        user_prompt = self.get_generation_prompt(input_with_context)

        response = llm_callable(system_prompt, user_prompt)
        scene = self._parse_yaml_response(response)

        # Set metadata
        if not scene.metadata.id:
            scene.metadata.id = f'script_beat_{sequence:03d}'
        scene.metadata.sequence = sequence

        self.validator.validate_strict(scene)
        return scene

    def generate_from_description(
        self,
        description: str,
        scene_id: str,
        llm_callable=None,
    ) -> Scene:
        """
        Generate SCENE DSL from a scene description.

        Args:
            description: Natural language scene description
            scene_id: Unique scene ID
            llm_callable: LLM function

        Returns:
            Scene object (validated)
        """
        if not llm_callable:
            raise ValueError('llm_callable required')

        system_prompt = self.get_system_prompt()
        user_prompt = self.get_generation_prompt(description)

        response = llm_callable(system_prompt, user_prompt)
        scene = self._parse_yaml_response(response)

        # Set ID
        if not scene.metadata.id:
            scene.metadata.id = scene_id

        self.validator.validate_strict(scene)
        return scene

    # ─────────────────────────────────────────────────────────────────────────
    # Parsing helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_yaml_response(self, response: str) -> Scene:
        """
        Parse YAML from LLM response.

        Handles:
          - Markdown code blocks
          - Extra whitespace
          - Partial YAML (uses defaults for missing fields)
        """
        # Extract YAML from markdown if present
        yaml_match = re.search(r'```ya?ml\n(.*?)\n```', response, re.DOTALL)
        if yaml_match:
            yaml_content = yaml_match.group(1)
        else:
            yaml_content = response

        try:
            import yaml

            data = yaml.safe_load(yaml_content)
            if not isinstance(data, dict):
                raise ValueError('YAML did not parse to dict')

            # Create Scene with defaults
            from zyg_workflows.dsl_schema import (
                Scene,
                SceneMetadata,
                SceneSemantic,
                SceneVisual,
                SceneAudio,
                SceneTechnical,
                SceneExecution,
                SceneQA,
            )

            # Extract nested dicts with defaults
            metadata_dict = data.get('metadata', {})
            if isinstance(metadata_dict, dict):
                metadata = SceneMetadata(
                    id=metadata_dict.get('id', ''),
                    duration=metadata_dict.get('duration', 0.0),
                    sequence=metadata_dict.get('sequence', 0),
                    tags=metadata_dict.get('tags', []),
                    continuity_refs=metadata_dict.get('continuity_refs', []),
                )
            else:
                metadata = SceneMetadata()

            # Similarly for other sections (use defaults)
            scene = Scene(
                metadata=metadata,
                semantic=SceneSemantic(**data.get('semantic', {}))
                if isinstance(data.get('semantic'), dict)
                else SceneSemantic(),
                visual=SceneVisual(**data.get('visual', {})) if isinstance(data.get('visual'), dict) else SceneVisual(),
                audio=SceneAudio(**data.get('audio', {})) if isinstance(data.get('audio'), dict) else SceneAudio(),
                technical=SceneTechnical(**data.get('technical', {}))
                if isinstance(data.get('technical'), dict)
                else SceneTechnical(),
                execution=SceneExecution(**data.get('execution', {}))
                if isinstance(data.get('execution'), dict)
                else SceneExecution(),
                qa=SceneQA(**data.get('qa', {})) if isinstance(data.get('qa'), dict) else SceneQA(),
            )

            return scene

        except Exception as e:
            raise ValueError(f'Failed to parse YAML from LLM response: {e}\n{response}') from e


# ─────────────────────────────────────────────────────────────────────────────
# Convenience functions
# ─────────────────────────────────────────────────────────────────────────────


def generate_dsl_from_text(
    text: str,
    text_type: str = 'research',  # research, script_beat, description
    scene_id: str = 'generated',
    llm_callable=None,
    use_caveman: bool = True,
) -> Scene:
    """
    Quick DSL generation.

    Args:
        text: Input text
        text_type: Type of input (research, script_beat, description)
        scene_id: Scene ID to assign
        llm_callable: LLM function
        use_caveman: Use caveman-style prompts

    Returns:
        Scene object
    """
    generator = DSLLLMGenerator(use_caveman=use_caveman)

    if text_type == 'research':
        return generator.generate_from_research(text, topic_id=scene_id, llm_callable=llm_callable)
    elif text_type == 'script_beat':
        return generator.generate_from_script_beat(text, llm_callable=llm_callable)
    else:
        return generator.generate_from_description(text, scene_id=scene_id, llm_callable=llm_callable)


if __name__ == '__main__':  # the CLI lives in dsl_llm_generator_cli
    from zyg_workflows.dsl_llm_generator_cli import main as _cli_main

    raise SystemExit(_cli_main())
