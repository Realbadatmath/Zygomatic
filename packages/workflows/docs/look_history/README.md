# Look-development history

Superseded look-dev scripts, kept for provenance and never deleted. Nothing imports them;
they are not on the import path and are excluded from ruff, modcheck and compileall.

- `pufferball_look.p2r4.py` — the pufferball look as of pass 2 / revision 4.
- `scene_shores/` — the "shores" scene render script versions `run_scene_shores_v19.py`,
  `v20.py`, `v21.py` (single files) and `run_scene_shores_v22/` … `v26/` (packages), moved
  out of `src/zyg_workflows/` because `v27/` plus the `run_scene_shores_{bird,flame,screams,water}.py`
  scripts are the current entry points. The intra-package `zyg_workflows.run_scene_shores_vNN`
  imports inside the moved packages are frozen history and no longer resolve — read them, do
  not run them.
