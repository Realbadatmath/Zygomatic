# S02: the body the plates state (split-brain fix) and shape from the sheet

Read `README.md` first. Plan sections 1 (findings 4 and 5), 3, 7 (Phase 0 and Phase 2). Notes: `understand_body_head.md` (whole), `understand_video_control.md` section 1c.

## Why this session exists
`geom/anny_fit.py:470-476` and `geom/anny_animate.py:96-101` build the body from `phenotype.calibrate()` (`geom/phenotype.py:33-74`, which solves only height for a declared age), never from the registry's `params.json`. So locals, anatomy layers, the hand correction and bone scales of the registered body never reach a fit or a plate. Measured: only 9 of 44 Abel fits and 6 of 43 Cornelis fits carry a phenotype at all; the ones that do carry gender 1.0 (female macro in Anny's convention, where 0.0 is male) and height 0.9702 against the registered Abel's gender 0.0 and height 0.8873. `anim_report.json` for the 41-frame track carries the same wrong body. There is also no path from a 2D sheet to a body SHAPE: the fitter's free parameters are camera, global rotation and pose only (`anny_fit.py:41-43`, `:351-357`).

## Owns / reads
Owns: `geom/anny_fit.py`, `geom/anny_animate.py`, `geom/phenotype.py`, `geom/body_grid.py`, new `geom/shape_fit.py`, `output/char_mesh/**`, new `data/assets/mesh_skeletons/candidates/`. Reads: `geom/mesh_skeletons.py` (the builder; do not edit, S04 owns it), `geom/anthro/gates.py:1959-1965` (`Subject.from_registry`, the pattern that rebuilds a body from its recorded params), `data/assets/mesh_skeletons/registry.json`, `data/assets/manifest.json` (`assets.char_abel.mesh.phenotype_target`).
Interpreter: `/usr/bin/python3.12` (Anny, warp, trimesh live there; the agents venv has no Anny). CPU is fine; the fit is 0.04 s forward and backward.

## Tasks
1. **Build from the registry.** Add `--body <registry name>` to `anny_fit` and `anny_animate` (and a `body=` parameter on `fit_cell`). Resolve registry name to `params.json`, rebuild through the same builder the gates use (`Subject.from_registry` pattern, `mesh_skeletons._build_mesh` with `params`), so phenotype, locals, anatomy layer, hand correction and bone scales all apply. Before fitting, assert the rebuilt cage's `cage_vert_sha256` equals the registry value; refuse otherwise. Keep the old path behind `--legacy-phenotype` for the comparison below. Character to registry mapping: Abel `c3345deb5bde` is registry `abel`, Cornelis `0015c8a3f2e3` is `cornelis` (manifest `char_abel.mesh.summary.char_id` links them).
2. **Re-fit and compare.** Re-run the fits for both characters with `--body`; table per character: median reprojection px full and upper mode, legacy versus registry body, and the phenotype actually used (print gender, age, height). Keep the legacy `anny_fit.json` files as `anny_fit_legacy.json` so nothing on disk is silently replaced.
3. **Regenerate the 41-frame track from the registered Abel** (cell_24 to cell_26 as before) into `output/char_mesh/c3345deb5bde/vace_ctrl_registry/` plus `anim_report.json` there; do not overwrite the old `vace_ctrl/`. Also write a WRONG-body track, the Cornelis body on Abel's poses, to `vace_ctrl_wrong/`. Both are S01's receipt inputs; say so in your receipt with the grey-fraction audit numbers.
4. **Shape from the sheet (`geom/shape_fit.py`).** A bounded joint solve over N cells of a character: free variables are Anny macro axes muscle, weight, proportions within plus or minus 0.3 of the declared values and a small set of `measure-*` locals capped at plus or minus 0.8 (the swayback lesson: width-only metrics let the solver dump error into the side profile). Age, height and gender stay FIXED to the bible. Evidence per cell: silhouette (MediaPipe person segmentation, already produced by `keypoints.detect`) and keypoints; hold out a third of the cells. Nulls: the phenotype-only body (do nothing) and the mean Anny body at the declared age and height. Report held-out reprojection px and silhouette IoU for fit and both nulls; render front AND side views before and after and look at them. Output a candidate delta to `data/assets/mesh_skeletons/candidates/<name>_shape_fit.json` with the numbers inside. Do NOT bake into the registry; a reissue is S04's and the operator's decision.

GATE for task 4: held-out cells beat both nulls, or the receipt says the sheet does not carry shape information beyond the declared build.

## Do not
Edit `mesh_skeletons.py` or anything under `geom/anthro/`. Retype numbers into recipes; every value is written programmatically from the fit JSON.

## Receipt
`receipts/S02.md`: hash assertion output, the before and after table, paths of the three track dirs with grey fractions, the shape-fit table with both nulls, side-view renders paths.
