# S03: identity measured on video

Read `README.md` first. Plan section 1 (finding 3), section 7 (Phase 0 receipt). Notes: `understand_video_control.md` section 4 and the null models at its end.

## Why this session exists
Nothing in production measures WHO is in a finished clip. `identity_bank.check_clip` (`identity_bank.py:571-627`) samples five fixed times through a STATIC box, its spread alarm was calibrated on one render (`:611-614`), and it has zero callers (`grep check_clip(` finds only its own `__main__`). `wan_face_restore.restore_faces` (`wan_face_restore.py:63-175`) re-synthesises faces with no identity score before or after and also has no callers. Clip QC that does run (`pipeline_debug.qc_clip`, `:481`) measures per-region motion and colour drift, not identity. `identity_qc_service` scores stills only (`:68-80` thresholds; AuraFace pack frontal 0.465, oblique 0.317, profile 0.206). Creatures have `creature_identity.py` (DINOv2) for stills and no clip path.

## Owns / reads
Owns: `identity_bank.py`, `wan_face_restore.py`, `wan_prop_restore.py`, `pipeline_debug.py` (the `qc_clip` region only), `arcane_multichar.py` (only the call sites around `:613-622`), `creature_identity.py` (a new clip function), new `scripts/identity_clip_bench.py`. Reads: `identity_qc_service.py`, `geom/keypoints.py` (MediaPipe detector), `output/**` for clips.
Interpreter: `"/home/zygomatic/Zygomatic Full/agents/.venv/bin/python"` for facenet and DINOv2 (CPU is acceptable; GPU only under the flock lock).

## Tasks
1. **Bench the instrument before trusting it (`scripts/identity_clip_bench.py`).** Arms: (a) the canon still repeated 341 times as an mp4 (ceiling); (b) the newest real finished clip of Abel and of Cornelis under `output/` (find them; record paths); (c) an impostor clip: another character in the same style; (d) a frame-shuffled copy of (b). Report cosine min, mean, spread and the z-floor for each arm. Set the floors from this bench, not from the single render in `:611-614`. If the impostor is not separated from the true clip, the metric is not usable and the receipt says so.
2. **Make `check_clip` a per-frame instrument.** Sample every Nth frame (N default 4) instead of five times; track the face box per frame with the MediaPipe detector (`geom/keypoints.py`) instead of a static `box_frac`; return a per-frame series plus a four-state ledger per frame (found, not_found, unmeasurable, not_detectable, e.g. a rear view is not_detectable, not a failure); keep the old behaviour behind a flag for comparison.
3. **Wire it, advisory only.** Call it from `pipeline_debug.qc_clip` and from the post-lock step in `arcane_multichar.py` (`:613-622`); write `identity_clip.json` next to the clip; env `ZYG_IDENTITY_CLIP=1` default on; never fail a pipeline on it yet. Also export a plain function `identity_bank.score_run(run_dir)` that S05's Movement Studio can call on a finished job (S05 will call it; do not edit `bp_movement.py`).
4. **Face restore scores itself.** In `restore_faces`, score identity on the input and on the output and write the delta into the output's sidecar; with `ZYG_FACE_RESTORE_REQUIRE_GAIN=1` refuse to overwrite when identity fell. Same for `wan_prop_restore` with the DINOv2 patch score against the prop reference.
5. **Creature clips.** `creature_identity.clip_similarity(clip, anchor)`: DINOv2 CLS per sampled frame against the anchor, bands as in `BANDS`, same ledger.

GATES: the bench table with ceiling, impostor and shuffle arms; impostor below floor, ceiling at top; per-frame series plotted once for one real clip and eyeballed (a metric you have not looked at is a rumour).

## Do not
Edit `wan_vace_service.py` (S01), `bp_movement.py` (S05), `identity_qc_service.py` thresholds. Run GPU embedding beside a render.

## Receipt
`receipts/S03.md`: bench table, chosen floors with their derivation, where the calls are wired, the restore delta on one real clip, the creature clip result.
