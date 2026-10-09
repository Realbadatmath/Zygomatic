# S08: the pose track. SAM 3D Body per frame, MHR, plates, Anny

Read `README.md` first. Plan section 7 Phase 1. Notes: `understand_video_control.md` sections 1c, 1d, 3; `research_video_identity.md` section 5.

## Why this session exists
No per-shot pose track exists. The animator is a two-pose lerp (`geom/anny_animate.py:81-153`); `geom/keypoints.py:52-76` builds MediaPipe in IMAGE mode with no tracking; `anny_fit.fit_cell` (`:235`) takes a cell directory, not keypoints. SAM 3D Body is live: worker `/home/zygomatic/models/sam3/sam3d_body_worker.py` loads once per invocation (`:47-51`), loops images in-process (`:67-78`) and keeps `detected, bbox, global_rot, mhr_model_params[204], body_pose_params[133], hand_pose_params[108], shape_params[45], scale_params[28], pred_keypoints_3d[70x3], pred_cam_t, focal_length` (`:62-64`). The estimator (`/home/zygomatic/models/sam3/code/sam_3d_body/sam_3d_body_estimator.py:64-78, 195-215`) also produces `pred_keypoints_2d, pred_vertices, expr_params, joint global rotations, mask`, which the worker DROPS. `process_one_image(img, bboxes=None, masks=None, cam_int=None)` accepts boxes, but the worker's request has no `bboxes` field and detectron2 is deliberately absent. The 1.2 s per image figure is claimed, never receipted. `mhr` and `pymomentum` are installed in no venv. SOMA-X (Apache) on disk is the only Anny to MHR registration.

## Owns / reads
Owns: `/home/zygomatic/models/sam3/sam3d_body_worker.py`, packages in `/home/zygomatic/models/sam3/body_venv` (Python 3.11, torch 2.13 cu126), new `sam3d_body_service.py` (crews), new `geom/pose_track.py`, new `geom/track_plates.py`, `output/pose_tracks/**`, `data/runtime/model_licences_pending/S08.json` (the mhr package licence entry goes there; the shared registry is not yours to edit). Reads: `sam3_service.py` (`_run_worker` `:167-192` is the pattern to clone; `segment`, `segment_batch` for masks and boxes), `geom/char_vace.py` (`_BONES`, OpenPose colours `:47-57`), `geom/vace_control.py` (`build`, grey audit), `geom/anny_animate.py` (`render_depth` `:48-78`), `data/assets/mesh_packs/human_bases/soma_x/`.
GPU: flock lock; never beside a ComfyUI job. Disk budget 5 GB.

## Tasks
1. **Worker.** Add `pred_vertices`, `pred_keypoints_2d`, joint global rotations and `expr_params` to `keep`; accept `bboxes` per image; keep batching all frames of a clip in one process; print per-image timing. Receipt the real time per frame.
2. **MHR decode.** `pip install mhr` into body_venv (Apache-2.0 code and assets; read the README licence line and LICENSE first; `pymomentum-gpu` optional and experimental). If pip fails, use the estimator's `pred_vertices` directly and say so.
3. **`geom/pose_track.py`.** Driver clip to frames (ffmpeg, 16 or 17 fps to match the render); SAM 3 track for the subject's box and mask per frame (`sam3_service`); SAM 3D Body per frame with those boxes; lock `shape_params` to the median over the track; smooth rotations with a one-euro or Savitzky filter; write `track.json` (per frame: 3D joints, 2D keypoints, camera, global rotation, shape) and a mask sequence dir in the VACE format (`m_%05d.png`). CLI: `python -m geom.pose_track <clip> --out <dir> [--subject "phrase"]`, runnable from the body venv (S05's picker calls exactly this).
4. **`geom/track_plates.py`.** From `track.json`: per-frame skeleton (OpenPose-18 colours, `_BONES` convention), depth and normal rasterised from the MHR vertices (painter's algorithm like `anny_animate.render_depth`, near=white, camera-space normals), segment; output `ctrl_%05d.png` sized to the render, plus the grey-fraction audit from `vace_control.build`. This folder is S01's `control_dir` and S05's picker input.
5. **Anny mapping (stretch).** Map MHR joint rotations to Anny `pose_aa` through SOMA-X so a child's proportions are re-stated (Abel is 12 years, 1.52 m); measure the retarget error as joint-position mm between the mapped Anny body and the MHR joints. Anny is a torch model with per-joint rotations; the map is a joint-name table, not a solver.

GATES: per-frame reprojection px of the track's 2D keypoints against MediaPipe or RTMPose 2D on the same frame; jitter (frame-to-frame joint displacement) on a held pose; nulls are the held-first-frame track and the two-pose lerp. A track that does not beat the lerp is not a track. Ledger per frame (found, not_found, unmeasurable, not_detectable).

## Do not
Install anything SMPL-based (smplx is in that venv for SAM 3D Body's own use; never call it). Edit `wan_vace_service.py` (S01) or `movement_studio.py` (S05).

## Receipt
`receipts/S08.md`: worker diff summary, timing per frame, the track metrics with both nulls on one real driver clip, the plate folder path and grey fraction, the retarget error if attempted.
