# Mesh identity plan: ten parallel sessions

Plan of record: `../mesh_identity_plan_2026-09-02.md`. Notes: `../mesh_identity_plan_2026-09-02_notes/`.
Ten briefs, S01 to S10, designed to run AT THE SAME TIME: every file on disk has exactly one session allowed to write it. Paste this into each fresh Claude Code session, changing the number:

    Read "/home/zygomatic/Zygomatic Full/agents/crews/docs/mesh_identity_plan_2026-09-02_sessions/README.md" and then "S01_video_control_path.md" in the same folder, and execute that brief. Its rules are binding. Write only the files that brief owns.

| # | Brief | One line |
|---|---|---|
| S01 | `S01_video_control_path.md` | control frames reach the VACE render; the three-arm receipt |
| S02 | `S02_body_and_shape.md` | fit and animate use the registered body; shape from the sheet |
| S03 | `S03_identity_on_video.md` | a per-frame identity instrument, benched, wired advisory |
| S04 | `S04_gates_ledger.md` | gate ledger current; the phalanx split-brain |
| S05 | `S05_studios_gui.md` | Movement Studio plates, Mesh tab actions, Character Studio body tools (sole owner of the two shared GUI files) |
| S06 | `S06_video_engines.md` | Wan2.2-Animate-14B and Wan2.2-VACE-Fun as second engines |
| S07 | `S07_head.md` | GNM landmark fit, ICT FaceKit expressions, the bridge decision |
| S08 | `S08_pose_track.md` | SAM 3D Body per-frame track, MHR, plates |
| S09 | `S09_assets_pipeline.md` | generic GLB to sheet, registrations, Creature Studio mesh op, TRELLIS.2 texturing |
| S10 | `S10_creature_geometry.md` | Pixal3D, SAM 3D Objects, UniRig, against two nulls |

## Rules binding for every session (no git on this box; ten sessions write at once)

1. **One writer per file.** The ownership table below is exhaustive. You may READ anything. You may WRITE only what your brief owns. If a task needs a change in a file you do not own, write a new module in your own space or a note in your receipt; never edit it, not even "a one-liner".
2. **Never wait for, and never unblock yourself through, another session.** Each brief says what to do while a dependency is not landed (a stub, a flag check, a labelled interim). If importing a file another session owns fails (they are mid-edit), retry in a minute; do not fix it.
3. **Licence entries go to your own pending file.** Do NOT edit `data/runtime/model_licences.json`. Write new entries in the same schema to `data/runtime/model_licences_pending/S0X.json` and list them in your receipt. The merge is one later step by the operator.
4. **Verify state before building.** Grep and check mtimes first; another session may have just built something in ITS space. If it is not in your ownership table, do not build it.
5. **GPU: one job at a time.** Wrap every render or inference in `flock -w 7200 /home/zygomatic/.zyg_gpu.lock -c '<command>'`. Never run beside a ComfyUI job you did not start.
6. **Disk:** 137 GB free at start. Each brief has a download budget. `df -h /` before any download; stop if free space would fall under 60 GB.
7. **Interpreters (paths contain spaces, quote them):** geom and Anny: `/usr/bin/python3.12`. GPU scripts and the server venv: `"/home/zygomatic/Zygomatic Full/agents/.venv/bin/python"` (no Anny there). SAM 3D Body: `/home/zygomatic/models/sam3/body_venv/bin/python`. TRELLIS.2: `/home/zygomatic/TRELLIS.2/venv/bin/python`. Blender: `/usr/local/bin/blender -b --factory-startup`.
8. **Licence rules (operator in the Netherlands, monetised channel, never distributes tools).** Copyleft on tools is fine. The danger is a USE restriction: non-commercial, territory (EU), "outputs may not be used". Check at FILE level: fetch the LICENSE, grep source and requirements for `EUROPEAN UNION`, `Territory`, `non-commercial`, `nvdiffrast`, `diff-gaussian-rasterization`, `diffoctreerast`, `kaolin.non_commercial`. Weights and code are licensed separately. Banned: the SMPL family and everything built on it, DWPose, CoTracker, nvdiffrast, the Hunyuan family, the FLUX.1-dev family.
9. **Measure before claim.** Every number reports its null (what "doing nothing" scores) and a four-state ledger (found / not_found / unmeasurable / not_detectable). No gate without a receipt that it ran on the real path.
10. **Server restarts:** only S05 restarts `kanban-server.service`. Other sessions that change a module the server imports (S09 `creature_fx.py`, `mesh_control.py`) make the edit in one atomic Edit call and run `python -c "import <module>"` right after; the restart happens whenever S05 next does one.
11. **Memory:** when your harness saves a memory and adds a line to the shared `MEMORY.md` index, re-read that file immediately before adding your line.
12. **Receipt.** Before you end, write `receipts/S0X.md` in this folder: what you built (files, functions), every measured number with its null, what you did not do and why, and open items for other sessions. That file is how the operator collects your work.

## Ownership table (the only writers)

| Session | Owns (write) | Reads or calls only |
|---|---|---|
| S01 | `wan_vace_service.py`, `geom/vace_control.py`, `geom/char_vace.py`, new `scripts/vace_plate_receipt.py`, `output/vace_receipts/**` | `identity_bank.py`, `pipeline_debug.py`, `output/char_mesh/**` (S02's tracks) |
| S02 | `geom/anny_fit.py`, `geom/anny_animate.py`, `geom/phenotype.py`, `geom/body_grid.py`, new `geom/shape_fit.py`, `output/char_mesh/**`, `data/assets/mesh_skeletons/candidates/*_shape_fit.json` | `geom/mesh_skeletons.py`, `geom/anthro/gates.py`, the registry |
| S03 | `identity_bank.py`, `wan_face_restore.py`, `wan_prop_restore.py`, `pipeline_debug.py`, `arcane_multichar.py` (call sites only), `creature_identity.py`, new `scripts/identity_clip_bench.py`, `output/identity_bench/**` | `identity_qc_service.py`, `geom/keypoints.py`, clips under `output/**` |
| S04 | `geom/anthro/**`, `geom/mesh_skeletons.py`, `geom/form/hands.py`, `data/assets/anthro_reports/`, `data/assets/mesh_skeletons/**` except `candidates/` | everything else |
| S05 | `kanban_server.py`, `inspection.html`, `movement_studio.py`, `bp_movement.py`, `character_studio.py`, new `geom/body_plates.py`, `tests/test_movement_studio.py`, `tests/test_charstudio_body.py`, `data/assets/mesh_skeletons/candidates/*_studio.json`, `<dataset>/plates/**` | `mesh_control.py`, `prop_mesh_library.py`, `wan_vace_service.py` (signature check), `identity_bank.score_run` if present, `geom/mesh_skeletons.py` CLI, `geom/mv_render.py`, `geom/conditioning.py` |
| S06 | new `wan_animate_service.py`, new `_comfy_workflows/wan22_animate.json` and `wan22_vace_fun.json`, downloads under `/home/zygomatic/ai-models/comfyui/models/`, new `scripts/animate_receipt.py`, `output/animate_receipts/**`, `data/runtime/model_licences_pending/S06.json` | `wan_video_service.py`, `identity_qc_service.py`, `geom/char_vace.py`, S08's plates |
| S07 | `geom/gnm_head.py`, `geom/gnm_fit.py`, new `geom/ict_face.py`, new `geom/head_fit.py`, `data/assets/gnm_head/**`, new `data/assets/ict_facekit/**`, `output/head_fit/**`, `data/runtime/model_licences_pending/S07.json` | `geom/keypoints.py`, `geom/anny_fit.py`, `output/char_mesh/*/cell_*/mesh.json` |
| S08 | `/home/zygomatic/models/sam3/sam3d_body_worker.py`, packages in `body_venv`, new `sam3d_body_service.py`, new `geom/pose_track.py`, new `geom/track_plates.py`, `output/pose_tracks/**`, `data/runtime/model_licences_pending/S08.json` | `sam3_service.py`, `geom/char_vace.py`, `geom/vace_control.py`, `geom/anny_animate.py` |
| S09 | new files under `prop_mesh/`, `prop_mesh_library.py`, `mesh_control.py`, `creature_fx.py` (one new op, one atomic edit), `data/assets/prop_meshes/**` except the pufferball entry, `/home/zygomatic/TRELLIS.2/ztest/**`, `output/texturing/**` | `comfy_generation_service.py`, `creature_sheet_service.py`, `prop_mesh/pufferball*.py`, `pass_lib.py` |
| S10 | new clones and venvs under `/home/zygomatic/` (`Pixal3D`, `sam-3d-objects`, `UniRig`), `lora-datasets/creatures/<id>/mesh_pixal3d/`, `mesh_sam3do/`, `mesh_rigged/`, `data/runtime/model_licences_pending/S10.json` | `prop_mesh/pbmetrics.py`, `creature_identity.py`, S09's renderer if present, `/home/zygomatic/TRELLIS.2/` |

Not owned by anyone this round (do not touch): `comfy_generation_service.py`, `creature_sheet_service.py`, `contact_sheet_pipeline.py`, `identity_qc_service.py`, `pipeline_storyteller.py`, `pipeline_video.py`, `sam3_service.py`, `data/runtime/model_licences.json`, the pufferball registry entry and `pufferball_look.py`, every registered body's recipe (S04 may reissue, never re-derive with new inputs).

## Clash audit (why this set can run at once)

- Every path above has one writer. The two 1.5 MB and 230 KB GUI files have one owner (S05).
- Cross-session reads are of files that are either never written this round, or written atomically by their owner (JSON files are rewritten whole by one process; a reader that hits a half-written file retries).
- Runtime imports across sessions (S05 imports `mesh_control`, the server imports `creature_fx`) can fail transiently while the owner edits; rule 2 covers it.
- GPU and disk are shared physical resources: rules 5 and 6.
- Outputs are namespaced per session (`output/<session-purpose>/**`, `receipts/S0X.md`, `model_licences_pending/S0X.json`).

## Dependencies (none block; this is what to do while waiting)

- S05's control-folder picker needs S01's `control_dir=` argument: check `inspect.signature` at runtime and refuse with a clear message until it exists. The prop-plates rack and the Mesh tab and Character Studio work have no dependency.
- S01's receipt prefers S02's regenerated Abel track (`vace_ctrl_registry/`, `vace_ctrl_wrong/`): until it lands, use the legacy `vace_ctrl/` and label the receipt "legacy phenotype".
- S06's skeleton video prefers S08's track; until then draw 2D skeletons from MediaPipe or RTMPose per frame.
- S10's view-rank metric prefers S09's generic sheet renderer; a minimal Blender turntable under S10's own clone dir is the fallback.
- S05's Body axes are honest only after S04's phalanx fix; build them against the candidate-params file and say so in the UI.
- S03's `identity_bank.score_run` is called by S05 only if it exists.

## What only the operator can do

- Decide the pufferball's mouth (front anchor open with teeth, side anchor closed beak). No tool resolves anchors that disagree.
- Approve any reissue of a registered body (S04 prints BEFORE and AFTER cage hashes).
- Merge `model_licences_pending/*.json` into `model_licences.json` after reading them.
- Mint licence-clean anchors for the three FLUX creatures (klein scratch mode in Creature Studio).
- Spend money. The plan says spend nothing yet.
