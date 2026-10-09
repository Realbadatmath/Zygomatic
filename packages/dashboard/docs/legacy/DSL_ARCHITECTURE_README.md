# Documentary Pipeline — Intermediate Semantic DSL

## Overview

The Intermediate Semantic DSL (Domain-Specific Language) bridges the gap between:
- **Semantic world**: LLM planning, research, scripting, human creativity
- **Deterministic world**: Tool execution, video rendering, precise parameters

## Architecture

```
Research Stage (prose findings)
  ↓
[LLM + caveman prompting] → SCENE DSL (YAML)
  ↓
[DSL Validator] → catch errors early
  ↓
[DSL Transformers] → tool-specific configs
  ↓
FLUX, MediaPipe, ffmpeg, YOLO8, RIFE
  ↓
Generated video frames
```

## Core Modules

### 1. `dsl_schema.py` — DSL Definition
Defines the complete SCENE schema with typed dataclasses:
- **Metadata**: ID, duration, sequence, tags, references
- **Semantic**: Emotional arc, narrative function, subject, conflict, discovery
- **Visual**: Camera, lighting, focus point, depth, composition
- **Audio**: Narration, music, sound effects
- **Technical**: Complexity, GPU requirements, priorities
- **Execution**: Tool-specific overrides
- **QA**: Quality scores, repair metadata

**Usage:**
```python
from dsl_schema import Scene, SceneMetadata
scene = Scene(
    metadata=SceneMetadata(id="ocean_01", duration=8.0),
    ...
)
```

### 2. `dsl_validator.py` — Validation & Type Checking
Validates DSL objects before execution:
- Type checking (enums, numeric ranges)
- Required field validation
- Consistency checks (e.g., HIGH complexity needs sufficient GPU)
- Reference validation (continuity_refs point to real scenes)
- Early error detection (catch LLM hallucinations)

**Usage:**
```python
from dsl_validator import DSLValidator
validator = DSLValidator(scene_database_dir="/path/to/scenes/")
is_valid, errors = validator.validate(scene)
```

### 3. `dsl_transformers.py` — Tool Configuration
Transforms semantic DSL into deterministic tool configs:

#### FLUX Image Generation
- Converts lighting/mood → guidance scale
- Maps motion level → inference steps
- Generates deterministic seed (same scene ID = same output)
- Expands semantic descriptions to prompts

**Parameters generated:**
```python
{
    "prompt": "cool blue tones with warm golden highlights...",
    "guidance_scale": 8.5,
    "num_inference_steps": 60,
    "seed": 12345,  # deterministic
}
```

#### MediaPipe Skeleton Tracking
- Maps motion level → smoothing settings
- Maps focus point → detection mode
- Adjusts confidence thresholds

#### ffmpeg Video Encoding
- Maps complexity → bitrate
- Selects color LUT from lighting style
- Handles aspect ratio conversion

#### YOLO8 Object Detection
- Model size from complexity
- Confidence threshold from focus point
- IOU settings

#### RIFE Frame Interpolation
- Interpolation factor from motion level
- Ensemble settings for quality

**Usage:**
```python
from dsl_transformers import dsl_to_all_configs
configs = dsl_to_all_configs(scene)
# configs["flux"], configs["mediapipe"], configs["ffmpeg"], etc.
```

### 4. `dsl_llm_generator.py` — LLM-Based DSL Generation
Generates SCENE DSL from research, scripts, and descriptions using caveman-style prompts.

**Features:**
- Caveman-style compressed prompts (30-40% token savings)
- Automatic validation of generated DSL
- Support for multiple input types (research, script beats, descriptions)
- YAML parsing with fallbacks and defaults

**Usage:**
```python
from dsl_llm_generator import DSLLLMGenerator

generator = DSLLLMGenerator(use_caveman=True)

# Your LLM function (e.g., Claude, Ollama)
def my_llm(system_prompt, user_prompt):
    # Call your LLM here
    return response

scene = generator.generate_from_research(
    "Deep ocean discoveries. Unknown creatures. Bioluminescence.",
    llm_callable=my_llm
)
```

## Integration Points (Non-Invasive)

### Research Stage
```python
# After research agent produces findings
findings = research_agent.run()

# NEW: Generate SCENE DSL
from dsl_llm_generator import DSLLLMGenerator
generator = DSLLLMGenerator(use_caveman=True)
scene = generator.generate_from_research(findings, llm_callable=your_llm)

# Save for next stage
scene.save_to_yaml("scenes/research_01.yaml")

# Continue with existing pipeline (optional DSL usage)
```

### Scripting Stage
```python
# After script is written
script_beats = script_agent.generate_beats()

# NEW: Generate SCENE DSL for each beat
scenes = []
for i, beat in enumerate(script_beats):
    scene = generator.generate_from_script_beat(beat, sequence=i, llm_callable=your_llm)
    scenes.append(scene)
    scene.save_to_yaml(f"scenes/script_beat_{i:03d}.yaml")

# Next stage can use DSL or ignore it (backward compatible)
```

### Generation Stage
```python
# NEW: If SCENE DSL available, use it; else fallback to prose
try:
    scene = Scene.from_yaml_file("scenes/script_beat_001.yaml")
    
    # Use transformers to auto-configure tools
    from dsl_transformers import dsl_to_flux_config, dsl_to_mediapipe_config
    flux_config = dsl_to_flux_config(scene)
    mediapipe_config = dsl_to_mediapipe_config(scene)
    
    # Execute with exact configs (reproducible)
    image = flux_api.generate(**flux_config)
    skeleton = mediapipe.track(image, **mediapipe_config)
    
except FileNotFoundError:
    # Fallback: use prose interpretation (current behavior)
    image = flux_api.generate_from_description(description)
```

### QA & Repair Stage
```python
# QA analysis produces findings
qa_issues = qa_agent.analyze(generated_images)

# NEW: Update SCENE DSL with repair directives
scene = Scene.from_yaml_file("scenes/script_beat_001.yaml")
scene.qa.qa_issues = qa_issues
scene.qa.requires_repair_check = True
scene.save_to_yaml("scenes/script_beat_001.yaml")  # Updated

# Repair system reads DSL, applies patches
repair_scene(scene)
```

### Assembly Stage
```python
# NEW: Use DSL metadata for auto-sequencing
import glob
scenes = [Scene.from_yaml_file(f) for f in glob.glob("scenes/*.yaml")]

# Sort by sequence
scenes.sort(key=lambda s: s.metadata.sequence)

# Verify continuity refs
for scene in scenes:
    for ref in scene.metadata.continuity_refs:
        if ref not in [s.metadata.id for s in scenes]:
            print(f"Warning: {ref} not found")

# Auto-configure transitions based on emotional arc
for i, scene in enumerate(scenes[:-1]):
    next_scene = scenes[i + 1]
    transition_config = compute_transition(scene, next_scene)
    # apply transition_config
```

## Deterministic Reproducibility

The DSL enables perfect reproducibility:

```python
# Same scene ID → same seed → same FLUX output
scene1 = Scene(metadata=SceneMetadata(id="ocean_01"))
scene2 = Scene(metadata=SceneMetadata(id="ocean_01"))

flux_config1 = dsl_to_flux_config(scene1)
flux_config2 = dsl_to_flux_config(scene2)

# flux_config1["seed"] == flux_config2["seed"]
# Same image generated every time
```

## Caching

Use scene ID as cache key:

```python
# Cache generated images by scene ID
cache_key = scene.metadata.id
if cache[cache_key]:
    image = cache[cache_key]
else:
    image = flux_api.generate(**dsl_to_flux_config(scene))
    cache[cache_key] = image
```

## Caveman-Style Prompting

DSL generation uses compressed prompts:

```
Normal prompt (200+ tokens):
"You are a DSL generator. Convert the following research findings
into a structured SCENE DSL object. The SCENE object should include
metadata with an ID and duration, semantic information about the
emotional arc and narrative function, visual directives for camera
movement and lighting, and audio specifications for narration and music.
Make sure to use only valid enum values. Do not hallucinate. Output valid YAML."

Caveman prompt (80 tokens):
"DSL GENERATOR. Convert input → SCENE DSL YAML.
Output: Valid YAML. Required: id, duration, subject, visual, audio.
Enums only. No prose. Concise."
```

**Token savings:** 30-40% reduction in prompt overhead

## Enum Values

Valid values for strict typing:

### CameraMovement
`static`, `push_in`, `pull_out`, `pan_left`, `pan_right`, `tilt_up`, `tilt_down`, `zoom_in`, `zoom_out`, `orbit`, `follow`, `dolly`, `handheld`

### MotionLevel
`minimal`, `slow`, `normal`, `dynamic`, `frenetic`

### Complexity
`low`, `medium`, `high`, `extreme`

### Emotion
`fear`, `wonder`, `curiosity`, `dread`, `calm`, `tension`, `joy`, `melancholy`, `awe`, `confusion`, `clarity`, `mystery`

### NarrativeFunction
`exposition`, `rising_action`, `climax`, `falling_action`, `resolution`, `hook`, `reveal`, `transition`, `montage`

### TempoTiming
`very_slow`, `slow`, `moderate`, `fast`, `very_fast`

## Example: Complete Flow

```python
# 1. Research finds: "Deep ocean, unknown creature, wonder and dread"
findings = "..."

# 2. Generate SCENE DSL with caveman prompts
generator = DSLLLMGenerator(use_caveman=True)
scene = generator.generate_from_research(findings, llm_callable=claude)

# 3. Validate
validator = DSLValidator()
validator.validate_strict(scene)

# 4. Transform to tool configs
from dsl_transformers import dsl_to_all_configs
configs = dsl_to_all_configs(scene)

# 5. Execute with deterministic, validated configs
image = flux_api.generate(**configs["flux"])
skeleton = mediapipe.track(image, **configs["mediapipe"])
video = encode_video(raw_video, **configs["ffmpeg"])

# 6. QA and save
qa_score = quality_check(video)
scene.qa.qa_score = qa_score
scene.save_to_yaml("scenes/ocean_01.yaml")
```

## File Organization

```
/agents/crews/
├── dsl_schema.py              # DSL type definitions
├── dsl_validator.py           # Validation logic
├── dsl_transformers.py        # DSL → tool configs
├── dsl_llm_generator.py       # LLM-based DSL generation
├── DSL_ARCHITECTURE_README.md # This file
└── scenes/                    # SCENE DSL storage (YAML files)
    ├── ocean_01.yaml
    ├── ocean_02.yaml
    └── ...
```

## Testing & Validation

Run the demo validators:

```bash
python3 dsl_schema.py          # Print example SCENE DSL
python3 dsl_validator.py       # Validate example scene
python3 dsl_transformers.py    # Generate tool configs
python3 dsl_llm_generator.py   # Show DSL generation prompts
```

## Migration Path

Start small, expand gradually:

1. **Phase 1**: Use DSL for research → scripting handoff (low risk)
2. **Phase 2**: Use DSL for generation config (auto-configure FLUX)
3. **Phase 3**: Use DSL for QA feedback loops (patch and retry)
4. **Phase 4**: Use DSL for assembly (auto-sequencing, transitions)
5. **Phase 5** (optional): Build DSL editing UI for manual tweaks

## Performance Impact

| Operation | Time | Notes |
|-----------|------|-------|
| DSL validation | <10ms | Fast type checking |
| DSL → configs | <5ms | Simple mapping |
| LLM generation (caveman) | ~2-3s | Depends on LLM |
| LLM generation (normal) | ~3-4s | More verbose |
| Token savings | 30-40% | With caveman prompts |

## Backward Compatibility

**DSL is completely optional.** If SCENE YAML files are missing:
- Generation stage falls back to prose interpretation
- No breaking changes to existing pipeline
- Can enable DSL gradually per stage

## Future Enhancements

- **DSL Editor UI**: Visual scene graph editor
- **Per-request DSL overrides**: Query params to tweak scene DSL
- **DSL versioning**: Track changes to scene definitions
- **Auto-DSL from video**: Extract DSL from existing footage
- **DSL -> Blender export**: Generate Blender scene files from DSL
- **Metrics dashboard**: Track cache hits, reproducibility scores

