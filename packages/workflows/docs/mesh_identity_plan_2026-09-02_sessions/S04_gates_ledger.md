# S04: the gate ledger current, and the phalanx split-brain

Read `README.md` first. Plan section 1 (finding 9), section 7 (Phase 0). Notes: `understand_body_head.md` sections 1, 2, 6. Memory context: the hand phalanx correction was solved per body and recorded exactly, but the shipped gate report still measures the UNCORRECTED chain (proof: Abel's reported `observed` 3.54748171601662 equals the worst z of `mid_over_prox` recomputed from the recorded `before` values through `hands._ratio_band`, to 14 significant figures).

## Why this session exists
`python3.12 -m geom.anthro.pack` prints STALE: artefacts date 2026-08-08 21:21, newest source `mesh_skeletons.py` 2026-08-26 22:43, so every gate status is a memory of older code. All five subjects (abel, anny-neutral, cornelis, female, male) read FAIL, exit 2. Abel's blocking set is `t5_joint_rom, t5_patellar_ligament, t5_digit_chains, t5_phalanx_ratio`, plus 11 blocking gates UNRUN including `t1_build_target_stature` (status missing because `derive` never records `height_target_m`). The reissue aux-hash defect was repaired on 2026-08-26 (`mesh_skeletons.py:2762-2776`); confirm it holds.

## Owns / reads
Owns: `geom/anthro/**` (`gates.py` is about 424 KB: grep, read windows, never the whole file), `geom/mesh_skeletons.py`, `data/assets/anthro_reports/`, `data/assets/mesh_skeletons/**` (reissue outputs, registry). Reads: everything else.
Interpreter: `/usr/bin/python3.12`. Run the suite once per change, not once per question; its full output lands on disk under `data/assets/anthro_reports/*.json`, read that.

## Tasks
1. **Refresh the ledger.** `python3.12 -m geom.anthro.pack` then `python3.12 -m geom.anthro check all`. Record per body the four-state counts (pass, warn, fail, skip, report, missing, unrun-blocking) BEFORE and AFTER every change below. The pack must stop printing STALE.
2. **Fix `t5_phalanx_ratio` measuring the pre-correction chain.** Candidates named in memory: a stale `_SKEL` cache key, a report generated with `apply_hand_correction=False`, or the measurement running on the original cage rather than the delivered mesh. Locate the gate's measurement function (grep `t5_phalanx_ratio`, `mid_over_prox`, `_ratio_band` in `geom/anthro/gates.py`, `geom/form/hands.py`, `geom/anthro/hand_correction.py:308 effective_scales`) and make it measure the DELIVERED mesh through the same door `_build_mesh` uses (`mesh_skeletons.py:621-672`). Add a self-test: a body with a recorded `hand_correction` must report z about 0 on the 8 gated ratios; a body without one must reproduce the old number. Check `t5_digit_chains` for the same fault.
3. **`t1_build_target_stature`.** Make `derive` and `reissue` record `height_target_m` in `params.json` (three-state params contract: a body issued before the field existed keeps reproducing its own hash) so the gate can run.
4. **Reissue with receipts.** `python3.12 -m geom.mesh_skeletons reissue abel cornelis --dry-run` first; print BEFORE and AFTER cage hashes; expect UNCHANGED hashes unless a declared input changed (the gate fix changes measurements, not geometry). Then the real reissue; verify originals stay `verified-immutable`; refresh previews only through `refresh-previews`.
5. **Report the honest blocking sets** per body after the fixes, and the `a_pose_bias_mm` and `_vertex_normals` asymmetry notes as still-open if untouched.

GATES: pack not STALE; phalanx self-test passes on all four bodies; hash receipts printed and pasted; the gate verdict WORD must change only for a measured reason (write the reason).

## Do not
Move any threshold to make a gate pass (the relief amplitude shortfall is deliberate). Edit `anny_fit.py` or `anny_animate.py` (S02). Bake S02's shape candidates into the registry without the operator's decision.

## Receipt
`receipts/S04.md`: before and after ledger tables, the phalanx root cause with file and line, hash receipts, remaining blocking sets, what changed in `params.json`.
