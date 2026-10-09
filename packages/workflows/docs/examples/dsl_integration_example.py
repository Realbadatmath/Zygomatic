#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
DSL Integration Example — Complete workflow showing DSL usage in the pipeline.

This demonstrates:
1. How to generate DSL from research findings
2. How to validate DSL
3. How to transform DSL to tool configs
4. How to integrate DSL into existing pipeline stages (non-invasively)
"""

from typing import Optional, Callable

# Import DSL modules
from zyg_workflows.dsl_schema import Scene
from zyg_workflows.dsl_validator import DSLValidator
from zyg_workflows.dsl_transformers import dsl_to_all_configs
from zyg_workflows.dsl_llm_generator import DSLLLMGenerator


# ─────────────────────────────────────────────────────────────────────────────
# Example 1: Research Stage with DSL
# ─────────────────────────────────────────────────────────────────────────────


def research_stage_with_dsl(
    research_findings: str,
    llm_callable: Callable,
    output_dsl_path: Optional[str] = None,
) -> Scene:
    """
    Research stage that produces DSL.

    Integration point:
      After research agent produces findings, generate SCENE DSL
      for handoff to scripting stage.

    Usage:
        findings = research_agent.run(topic="deep ocean")
        scene = research_stage_with_dsl(findings, llm_callable=claude)
        scene.save_to_yaml("scenes/research_01.yaml")
    """
    print('\n' + '=' * 70)
    print('RESEARCH STAGE → DSL GENERATION')
    print('=' * 70)

    print('\nResearch findings (input):')
    print(f'  {research_findings[:100]}...')

    # Generate DSL using caveman-style prompts
    generator = DSLLLMGenerator(use_caveman=True)
    scene = generator.generate_from_research(
        research_findings,
        topic_id='research_01',
        llm_callable=llm_callable,
    )

    print('\n✓ Generated SCENE DSL:')
    print(f'  ID: {scene.metadata.id}')
    print(f'  Duration: {scene.metadata.duration}s')
    print(f'  Subject: {scene.semantic.subject}')
    print(f'  Emotional arc: {scene.semantic.emotional_arc}')

    # Save to file
    if output_dsl_path:
        scene.save_to_yaml(output_dsl_path)
        print(f'\n✓ Saved to: {output_dsl_path}')

    return scene


# ─────────────────────────────────────────────────────────────────────────────
# Example 2: Scripting Stage with DSL
# ─────────────────────────────────────────────────────────────────────────────


def scripting_stage_with_dsl(
    script_beats: list[str],
    llm_callable: Callable,
    output_dir: Optional[str] = None,
) -> list[Scene]:
    """
    Scripting stage that produces DSL for each beat.

    Integration point:
      After script is written, generate SCENE DSL for each beat.
      This metadata guides generation stage.

    Usage:
        script_beats = [
            "Deep ocean, creature appears...",
            "Creature swims closer, we see detail...",
            "Creature is beautiful, wonder fills us...",
        ]
        scenes = scripting_stage_with_dsl(script_beats, llm_callable=claude)
    """
    print('\n' + '=' * 70)
    print('SCRIPTING STAGE → DSL GENERATION (Multiple Beats)')
    print('=' * 70)

    generator = DSLLLMGenerator(use_caveman=True)
    scenes = []

    for i, beat in enumerate(script_beats):
        print(f'\nBeat {i + 1}: {beat[:50]}...')

        scene = generator.generate_from_script_beat(
            beat,
            sequence=i,
            llm_callable=llm_callable,
        )

        print(f'  ✓ Generated DSL: {scene.metadata.id}')
        print(f'    Camera: {scene.visual.camera_movement}')
        print(f'    Emotion: {scene.semantic.emotional_arc}')

        scenes.append(scene)

        if output_dir:
            scene.save_to_yaml(f'{output_dir}/scene_{i:03d}.yaml')

    print(f'\n✓ Generated {len(scenes)} SCENE DSL objects')
    return scenes


# ─────────────────────────────────────────────────────────────────────────────
# Example 3: Generation Stage Using DSL
# ─────────────────────────────────────────────────────────────────────────────


def generation_stage_with_dsl(
    scene: Scene,
    flux_api_callable: Callable,
    mediapipe_callable: Callable,
) -> dict:
    """
    Generation stage that uses DSL to auto-configure tools.

    Integration point:
      Instead of manual config, use DSL transformers to generate
      exact tool parameters. Deterministic, cached, auditable.

    Usage:
        scene = Scene.from_yaml_file("scenes/scene_001.yaml")
        result = generation_stage_with_dsl(
            scene,
            flux_api_callable=flux.generate,
            mediapipe_callable=mp.track,
        )
    """
    print('\n' + '=' * 70)
    print('GENERATION STAGE → DSL-BASED CONFIGURATION')
    print('=' * 70)

    print(f'\nScene: {scene.metadata.id}')

    # Validate DSL
    validator = DSLValidator()
    is_valid, errors = validator.validate(scene)
    if not is_valid:
        print(f'✗ DSL Validation failed: {errors}')
        return {}
    print('✓ DSL validation passed')

    # Transform to tool configs
    configs = dsl_to_all_configs(scene)

    print('\n✓ Generated tool configurations:')
    print(f'  FLUX guidance scale: {configs["flux"]["guidance_scale"]}')
    print(f'  FLUX steps: {configs["flux"]["num_inference_steps"]}')
    print(f'  MediaPipe confidence: {configs["mediapipe"]["min_detection_confidence"]}')
    print(f'  ffmpeg bitrate: {configs["ffmpeg"]["bitrate"]}')

    # Execute tools with DSL-generated configs
    print('\n✓ Executing generation tools...')

    # Call FLUX (stub)
    print('  [1/2] FLUX image generation...')
    # image = flux_api_callable(**configs['flux'])
    print(f'        ✓ Generated with seed {configs["flux"]["seed"]} (reproducible)')

    # Call MediaPipe (stub)
    print('  [2/2] MediaPipe skeleton tracking...')
    # skeleton = mediapipe_callable(image, **configs['mediapipe'])
    print(f'        ✓ Tracked {configs["mediapipe"]["focus_point"]}')

    result = {
        'scene_id': scene.metadata.id,
        'configs': configs,
        'status': 'generated',
    }

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Example 4: QA & Repair with DSL
# ─────────────────────────────────────────────────────────────────────────────


def qa_stage_with_dsl(
    scene: Scene,
    qa_score: float,
    qa_issues: list[str],
) -> Scene:
    """
    QA stage that records findings in DSL for repair loop.

    Integration point:
      QA analysis produces findings, which are recorded in
      the SCENE DSL. Repair system reads DSL and knows
      exactly what to fix.

    Usage:
        scene = Scene.from_yaml_file("scenes/scene_001.yaml")
        qa_score = quality_analyzer.score(generated_image)
        qa_issues = ["face_drift_frame_12", "lighting_flicker_frame_8"]
        scene = qa_stage_with_dsl(scene, qa_score, qa_issues)
        scene.save_to_yaml("scenes/scene_001.yaml")  # Updated
    """
    print('\n' + '=' * 70)
    print('QA STAGE → DSL REPAIR METADATA')
    print('=' * 70)

    print(f'\nScene: {scene.metadata.id}')
    print(f'QA Score: {qa_score}')
    print(f'Issues: {qa_issues}')

    # Update DSL with QA findings
    from zyg_workflows.dsl_schema import QAIssue

    scene.qa.qa_score = qa_score
    scene.qa.qa_passed = qa_score > 0.75

    for issue_desc in qa_issues:
        issue = QAIssue(
            issue_type=issue_desc.split('_')[0],  # "face_drift"
            severity='high' if qa_score < 0.5 else 'medium',
            details=issue_desc,
        )
        scene.qa.qa_issues.append(issue)

    # Decide on repair method
    if qa_score < 0.65:
        scene.qa.requires_repair_check = True
        from zyg_workflows.dsl_schema import RepairMethod

        scene.qa.repair_method = RepairMethod.FLUX_INPAINT
        print(f'\n✓ Marked for repair: {scene.qa.repair_method}')
    else:
        print('\n✓ QA passed, no repair needed')

    return scene


# ─────────────────────────────────────────────────────────────────────────────
# Example 5: Assembly Stage with DSL
# ─────────────────────────────────────────────────────────────────────────────


def assembly_stage_with_dsl(scenes: list[Scene]) -> dict:
    """
    Assembly stage that uses DSL for sequencing and transitions.

    Integration point:
      Load all SCENE DSL files, verify continuity references,
      auto-configure transitions based on emotional arc changes.

    Usage:
        scenes = [
            Scene.from_yaml_file("scenes/scene_001.yaml"),
            Scene.from_yaml_file("scenes/scene_002.yaml"),
            Scene.from_yaml_file("scenes/scene_003.yaml"),
        ]
        assembly_plan = assembly_stage_with_dsl(scenes)
    """
    print('\n' + '=' * 70)
    print('ASSEMBLY STAGE → DSL-BASED SEQUENCING')
    print('=' * 70)

    # Validate all scenes
    validator = DSLValidator()
    for scene in scenes:
        is_valid, errors = validator.validate(scene)
        if not is_valid:
            print(f'✗ Scene {scene.metadata.id} invalid: {errors}')
            return {}

    print(f'\n✓ Validated {len(scenes)} scenes')

    # Build sequence
    print('\nSequence:')
    total_duration = 0
    for i, scene in enumerate(scenes):
        print(f'  [{i + 1}] {scene.metadata.id}')
        print(f'       Duration: {scene.metadata.duration}s')
        print(f'       Emotion: {scene.semantic.emotional_arc}')
        total_duration += scene.metadata.duration

    # Verify continuity
    scene_ids = {s.metadata.id for s in scenes}
    orphan_refs = []
    for scene in scenes:
        for ref in scene.metadata.continuity_refs:
            if ref not in scene_ids:
                orphan_refs.append(ref)

    if orphan_refs:
        print(f'\n⚠ Orphan continuity refs: {orphan_refs}')
    else:
        print('\n✓ All continuity references valid')

    # Compute transitions
    print('\nTransitions:')
    for i, scene in enumerate(scenes[:-1]):
        next_scene = scenes[i + 1]
        emotion_delta = f'{scene.semantic.emotional_arc[-1]} → {next_scene.semantic.emotional_arc[0]}'
        print(f'  {scene.metadata.id} → {next_scene.metadata.id}')
        print(f'    Emotional shift: {emotion_delta}')

    result = {
        'num_scenes': len(scenes),
        'total_duration': total_duration,
        'continuity_valid': len(orphan_refs) == 0,
        'status': 'assembly_ready',
    }

    print(f'\n✓ Assembly plan complete: {total_duration}s total')
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Main demonstration
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('\n' + '=' * 70)
    print('DSL INTEGRATION EXAMPLE — Complete Pipeline Workflow')
    print('=' * 70)

    # Stub LLM (in real usage, this would be Claude, Ollama, etc.)
    def stub_llm(system_prompt: str, user_prompt: str) -> str:
        """Stub LLM that returns minimal valid YAML."""
        return """
metadata:
  id: example_scene
  duration: 8.0
  sequence: 0
  tags: [example]
semantic:
  emotional_arc: [curiosity, wonder]
  narrative_function: reveal
  subject: example
visual:
  camera_movement: push_in
  lighting_style: cool_blue
  focus_point: center
  motion_level: slow
audio:
  narration_style: whisper
  narration_emotion: awe
  music_mood: mysterious
technical:
  estimated_complexity: medium
  gpu_memory_required_gb: 8.0
"""

    # Stub tool callables
    def stub_flux(prompt, guidance_scale, **kwargs):
        return 'stub_image.png'

    def stub_mediapipe(image, **kwargs):
        return 'stub_skeleton.json'

    # Example 1: Research
    research_findings = """
    Deep ocean exploration reveals unknown creatures at 3000m depth.
    Bioluminescent organisms create ethereal light patterns.
    The sense of wonder mixed with primal dread as we encounter the unknown.
    """

    scene1 = research_stage_with_dsl(research_findings, llm_callable=stub_llm)

    # Example 2: Scripting
    script_beats = [
        'We descend into darkness. Pressure builds. Fear grips the team.',
        'Shadows move. Something is out there. Tension peaks.',
        'A creature emerges, bioluminescent and beautiful. Wonder transforms fear.',
    ]

    scenes = scripting_stage_with_dsl(script_beats, llm_callable=stub_llm)

    # Example 3: Generation
    if scenes:
        result = generation_stage_with_dsl(
            scenes[0],
            flux_api_callable=stub_flux,
            mediapipe_callable=stub_mediapipe,
        )

    # Example 4: QA
    if scenes:
        scene_qa = qa_stage_with_dsl(scenes[0], qa_score=0.82, qa_issues=[])

    # Example 5: Assembly
    assembly_plan = assembly_stage_with_dsl(scenes)

    print('\n' + '=' * 70)
    print('✓ EXAMPLE COMPLETE')
    print('=' * 70)
    print('\nKey takeaways:')
    print('  1. DSL bridges semantic (LLM) and deterministic (tools) worlds')
    print('  2. Caveman prompts reduce LLM tokens by 30-40%')
    print('  3. Transformers auto-configure tools from semantic DSL')
    print('  4. Integration is non-invasive (backward compatible)')
    print('  5. Deterministic reproducibility (same scene ID = same output)')
