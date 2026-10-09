# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The stages of the storyteller pipeline — character LoRA to delivered episode.

`_run_storyteller_pipeline` in `zyg_workflows.pipeline_storyteller` was one
3,791-line function. Its nine `# ── Stage N …` blocks now live here, one
`stage_<nn>_<slug>(ctx)` function each, and they talk to each other through the
`StorytellerContext` in `context.py`:

    pipeline_storyteller._run_storyteller_pipeline(pipeline_id)
      │  prologue — job record, out_dir, the render markers, four closures
      ├─ ctx = StorytellerContext(…)
      ├─ try:
      │    stage_01_character_prep(ctx)        stage_01_character_prep.py
      │    stage_02_scene_budget(ctx)          stages_02_story_script.py
      │    stage_02a_sonnet_story(ctx)         stages_02_story_script.py
      │    stage_02b_render_prompts(ctx)       stage_02b_render_prompts.py
      │    stage_03_tts(ctx)                   stages_03_05_tts_assembly.py
      │    stage_035_image_generation(ctx)     stage_035_image_gen.py
      │      │  st = ImageGenState(…)          the loop's private state
      │      ├─ prepare_flux_paths/wait_for_vram/select_backend
      │      │                                 stage_035_backend.py
      │      ├─ generate_scene(ctx, st, …)     stage_035_scene_loop.py
      │      │    └─ generate_one(ctx, st, …)  stage_035_generate.py
      │      │         scene_quality_ok / …    stage_035_qa.py
      │      └─ stage_036_anatomy_repair(ctx, st)
      │                                        stage_036_anatomy.py
      │    stage_04_ken_burns(ctx)             stages_03_05_tts_assembly.py
      │    stage_05_final_assembly(ctx)        stages_03_05_tts_assembly.py
      │    stage_05b_burn_subtitles(ctx)       stage_05b_subtitles.py
      ├─ except Exception as exc:  …
      └─ finally:  _release_pipeline_vram(…)

Stage 3.5 is the one range that could not be a flat move: five nested `def`s
rebound seven of its locals through `nonlocal`. Those helpers are now
module-level functions that take `st: ImageGenState` and write its fields —
see `SPLIT_LOG.md`, task B, for the closure → function and `nonlocal` → field
tables.

**Nothing is re-exported here on purpose.** The stage modules import helpers and
constants out of `pipeline_storyteller` at module level, and
`pipeline_storyteller` imports the stage modules *lazily*, inside
`_run_storyteller_pipeline`, right before the `try:`. Only one of those two
directions can be at module level or the cycle closes at import time, and a
re-export block in this file would close it from the other side: importing
`zyg_workflows.storyteller` would pull in `pipeline_storyteller`, which the
dashboard imports for `_run_storyteller_pipeline` alone. `scholarly/__init__.py`
is empty for the same reason — import the module you want by its full path.

`SPLIT_LOG.md` is the history of the move and the list of what the name analysis
cannot see; read it before cutting another range out of the driver.
"""
