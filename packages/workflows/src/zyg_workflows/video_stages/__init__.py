# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The stages of `zyg_workflows.pipeline_video._run_video_pipeline`.

The driver is the prologue (the job record, `out_dir`, the four logging
closures), one `VideoContext`, the stage calls, and the `try/except/finally`
around the run. Every stage lives here:

| module | functions | what |
| --- | --- | --- |
| `stage_01_scene_plan.py` | `stage_01_scene_plan` | the VRAM startup sweep and Claude's scene list |
| `stage_02_images.py` | `stage_02_image_prep`, `stage_02c_still_gate`, `stage_02b_anatomy_repair` | stills in / generated / gated |
| `stage_03_tts.py` | `stage_03_tts` | IndexTTS-2 narration per scene |
| `stage_04_video_generation.py` | `stage_04_video_generation` | the Stage 4 skeleton: setup, manga branch, the three calls below, `good_clips` |
| `stage_04_vram_prep.py` | `prepare_vram_and_services` | the competing-VRAM sweep, the cache flush, the WAN/audio service imports |
| `stage_04_wan_generate.py` | `generate_wan_clips` | WAN animate (chained or batched) plus Stages 4b/4c/4d |
| `stage_04_clip_mux.py` | `mux_clips` | the per-scene loop: trim/loop, Ken Burns fallback, audio + foley mux |
| `stage_05_assembly.py` | `stage_05_assembly` | concat, music, ending card, 4K master, seal |

Only `stage_04_video_generation` carries the `stage_` prefix the split's gate
(`scripts/check_free_names.py --stage-prefix`) selects by default; its three
helpers are named for what they do, so run that gate with `--stage-prefix ''`
to cover them as well.

**This package deliberately re-exports nothing.** `pipeline_video` imports the
stage modules *inside* `_run_video_pipeline`; the stage modules import helpers
and constants out of their own source modules at module level. Only one of the
two directions can be at module level or the cycle closes at import time — do
not tidy the lazy imports up to the top of `pipeline_video.py`, and do not add
re-exports here: `tests/test_egress_seal.py` imports `pipeline_video` at module
level and must not drag the whole stage set in with it.
"""
