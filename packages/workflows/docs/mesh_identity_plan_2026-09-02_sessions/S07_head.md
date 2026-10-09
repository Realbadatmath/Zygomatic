# S07: the head. GNM landmark fit, ICT FaceKit expressions, the bridge decision

Read `README.md` first. Plan section 3 (Humans), section 7 Phase 2. Notes: `understand_body_head.md` section 5, `research_humans.md` sections 1 to 3.

## Why this session exists
GNM Head v3 (Apache, `geom/gnm_head.py`, 253 identity, 383 expression, 17,821 verts) is fitted to Anny heads by ICP (`geom/gnm_fit.py`), and the honest numbers are face RMS 4.3 to 4.8 mm with identity gain over the MEAN head of only 0.95 to 2.09 mm and one or two coefficients at the plus or minus 3 wall. There is no path from a contact sheet to a GNM identity: no MediaPipe-478 to GNM-68 mapping exists (grep 468, 478, mediapipe in `gnm_*.py` gives zero hits), although GNM ships 68 barycentric landmarks (`gnm_head.py:115-130`, `landmark_points()`). Google has released no fitter and no body (verified 2026-09-02); the paper's recipe is dense landmarks plus optimisation. ICT FaceKit's LIGHT model is plain MIT with 100 identity modes and 53 ARKit-named blendshapes, and MediaPipe emits ARKit-style blendshape scores, so an expression channel needs no fitter.

## Owns / reads
Owns: `geom/gnm_head.py`, `geom/gnm_fit.py`, new `geom/ict_face.py`, new `geom/head_fit.py`, `data/assets/gnm_head/**`, new `data/assets/ict_facekit/**` with `PROVENANCE.json`, `output/head_fit/**`, `data/runtime/model_licences_pending/S07.json` (licence entries go there; the shared registry is not yours to edit). Reads: `geom/keypoints.py` (Face Landmarker, 478 points plus 52 blendshapes, `facial_transformation_matrixes`), `geom/anny_fit.py` (pinhole camera and yaw seeding conventions, `:235`), `output/char_mesh/<id>/cell_*/mesh.json` (existing 478-point detections for Abel 43 of 48 and Cornelis 35 of 47 cells).
Interpreter: `/usr/bin/python3.12` (gnm-shape is installed there, editable, without tensorflow; keep it that way, the AST test enforces it).

## Tasks
1. **ICT FaceKit light.** Clone `github.com/ICT-VGL/ICT-FaceKit`; read LICENSE at file level (MIT, 2020 USC ICT); do NOT fetch anything labelled "full" (different USC licence). Load the light model (26,719 verts, 100 identity, 53 expression), write `PROVENANCE.json` with the licence quote and URL, write the licence entry to `model_licences_pending/S07.json`, expose `ict_face.model()` and a blendshape mapping from MediaPipe's 52 names to ICT's 53.
2. **MediaPipe-478 to GNM fit (`geom/head_fit.py`).** Build the 468 to 68 correspondence from MediaPipe's `canonical_face_model.obj` and the FACEMESH index sets (Apache) against GNM's 68; per image: pinhole camera as in `anny_fit`, similarity, GNM identity (prior 1e-5, the value the 2026-08-22 re-run settled on) plus expression; then a JOINT identity solve over a character's frontal and three-quarter cells with per-cell camera and expression. Null: the mean head (identity zero) through the same similarity. Report landmark RMS in px, identity gain in mm on held-out cells, and the count of coefficients past 2.5 against the plus or minus 3 wall.
3. **Expression plates.** MediaPipe blendshape scores from a short driver clip drive ICT (or GNM's expression space) to render per-frame face depth and normal plates (face only, near=white, camera-space normals per `geom/conditioning.py`); write to a folder S08 and S01 can composite. Validate on 40 frames by eye and by reprojection of the 68 landmarks.
4. **The bridge decision.** Compute the fitted-minus-mean GNM delta per body and the seam error of transferring it onto Anny head verts (crop definition `gnm_fit.py:50-57`, chin cut `:184-190`; blend over the neck ring with a Laplacian falloff). Build it as an `anatomy_layer` key ONLY if per-character identity gain exceeds the seam error; otherwise write the measured reason and stop. Topology and the registry hash contract must survive either way (this is why the bridge is a delta on Anny verts, not a mesh swap).

GATES: identity gain over the mean head on held-out cells, per body; saturation count; plates eyeballed; the bridge built or refused with numbers.

## Do not
Install tensorflow. Touch `mesh_skeletons.py` or the registry (S04). Fetch FLAME 2020, MICA, EMOCA, SMIRK or BFM (non-commercial) even as references.

## Receipt
`receipts/S07.md`: licence entry, correspondence table size, the fit table with nulls, plate folder path, the bridge decision with both numbers.
