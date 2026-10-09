<!-- SPDX-FileCopyrightText: 2026 Zygomatic -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Provenance

Where every non-source artefact in this repository comes from, and under what licence. Written
2026-10-05.

The repository as a whole is AGPL-3.0-or-later (`LICENSE`), declared file by file through SPDX
headers, sidecar `.license` files and the catch-all annotation in `REUSE.toml`. `reuse lint`
checks that nothing is uncovered. This document is the part `reuse lint` cannot check: whether the
Zygomatic copyright claim on a given file is actually correct, and what licence applies to the
things the code downloads but does not ship.

## 2026-10-05: where the generated indices live, and how the kept ones store paths

A data file under `src/zyg_workflows/data/` is either real configuration or a generated index,
and the two no longer live in the same place. The rule a reviewer can apply: **a path stored in
a repository data file is written against a named root from `zyg_workflows.paths`, never against
one machine's disk.** What was done, file by file:

- `data/runtime/model_licences.json` — **kept** (configuration). It is the licence registry the
  `licence_provenance` gate reads, and the only record of where each weight's licence was read;
  regenerating it is not possible. Its `source` and `note` fields are now re-keyed against named
  roots — `ZYG_MODELS_ROOT/gnm/LICENSE`, `ZYG_MODELS_DIR/sam3/...`, `ZYG_HOME/UniRig/LICENSE` —
  and `licence_provenance.resolve_root_path()` expands them inside `load_registry()`. A field
  that still carries an absolute path is returned unchanged, so a merge out of
  `model_licences_pending/` cannot break. Locked by `tests/test_model_licences_rekey.py`, which
  asserts the GNM entry resolves to the same absolute LICENSE the pre-re-keying file named.
  Lookups were never affected: the gate matches by filename glob, not by stored path.
- `data/runtime/asset_library_vfx_meta.json` — **moved out** (generated index). Every record is
  rebuilt by a `vfx_ingest.py` run and its `source` field names the build script on the machine
  that rendered the clip. `vfx_ingest.SIDECAR` is now
  `$ZYG_DATA_ROOT/runtime/asset_library_vfx_meta.json`, the pattern is in `.gitignore` beside its
  already-ignored `asset_library_instruments_meta.json` sibling, and an ingest run recreates it.
  The last committed copy is recoverable with
  `git show 918c8b7:src/zyg_workflows/data/runtime/asset_library_vfx_meta.json`.
- `tools/studio_verify/_report_ecorche.json` — **removed** (run artefact). One session's
  verification report, left next to the check that printed it; nothing in the package reads or
  writes it, and every path in it points into the legacy production tree. `_report_*.json` under
  `tools/studio_verify/` is now ignored.
- `data/stack_lineage/{mesh,asr}.json` — **kept** (configuration). Their absolute paths were in
  human prose (the `where` field and issue text), not in any lookup, and are now written
  home-relative (`~/Direct3D-S2`) like the rest of the prose in the same files.

The audio sidecars (`asset_library_{sfx,foley,soundtracks,…}_meta.json`, written by
`asset_library_service.set_audio_meta_many` and read by `melody_sampler`) stay in the package:
they are keyed by bare filename and store no path at all.

## Ships in the repository

### LUTs: `src/zyg_workflows/assets/luts/*.cube`

`anime.cube`, `cinematic.cube`, `documentary.cube`, `filmic.cube`, `orange_teal.cube`.

Own work. They are computed, not sampled from anyone's film stock: `scripts/generate_luts.py`
builds each one as a 33x33x33 table from closed-form maths in that file, and the `TITLE` line
inside each `.cube` matches the string the generator writes (`write_cube('cinematic.cube',
cinematic, 'Cinematic Grade - Zygomatic')` at `scripts/generate_luts.py:138-142`). They are
loaded at pipeline runtime by the ffmpeg `lut3d` filter.

Two caveats, both small and both real:

- The committed files have not been diffed byte for byte against a fresh run of the generator, so
  a hand edit after generation would not show up. Re-running the script is the way to confirm.
- `scripts/generate_luts.py` writes to `<repo>/assets/luts/`, while the files the package loads
  live at `src/zyg_workflows/assets/luts/`. The generator's output path needs updating before the
  next regeneration; this is recorded here rather than fixed, because the script is not this
  document's file.

### Agent definitions: `src/zyg_workflows/agents/**/*.json`, `src/zyg_workflows/data/*.json`

Own work: role definitions, model mappings, schedules, topic pools and the agent index. Each
carries a sidecar `.license` naming Zygomatic and AGPL-3.0-or-later. They contain configuration
only, no third-party text or data.

### ComfyUI graphs: `src/zyg_workflows/_comfy_workflows/*.json`

Own work: graphs authored for this pipeline, each with a sidecar `.license`.

**No model weights are in this repository.** A graph references weights by filename, and those
files live outside the tree under `ZYG_COMFY_ROOT` / `ZYG_MODELS_ROOT`. The licence of the
referenced weights is therefore not a property of these JSON files, and it is checked at run time
rather than asserted here: `src/zyg_workflows/licence_provenance.py` walks every graph (through
`lora_attest.collect_model_refs`), classifies each referenced weight as cleared, non-commercial,
territory-excluded or unknown, and fails the gate on anything that is not cleared. `unknown` never
passes.

Two classes of weight that gate documents explicitly, as the reason the gate exists:

- **FLUX.1-dev and FLUX.1-Fill-dev**: Black Forest Labs Non-Commercial License v2.0. Every
  character LoRA trained on `flux1-dev` is a derivative of a non-commercial base, which is why
  `licence_provenance.py` resolves LoRA lineage from `training_status_<family>.json` and charges a
  LoRA with its base model's licence instead of its own filename.
- **MiniMax and Tencent Hunyuan community licences**: their Territory clause excludes the European
  Union, and it excludes use of the *outputs*, not only of the weights. Distribution is not
  required for the restriction to bite.

### Pose maps: `src/zyg_workflows/assets/contact_sheet_poses/*.png`

Own work: 24 OpenPose-style skeleton maps at 640x720, drawn with Pillow by
`scripts/generate_contact_sheet_poses.py`. The limb palette follows the DWPose convention (a
colour convention, not copied data). Each PNG has a sidecar `.license`.

### Architecture Studio capability files: `src/zyg_workflows/arch_ext/*`, `arch_assistant_ext/*`, `arch_blender_ext/*`

Own work. The JavaScript files here are hand-written geometry and label definitions for this
application; no third-party library is vendored into the repository. The three.js runtime the
Architecture Studio viewport uses is loaded by the dashboard's page, not stored here.

### Everything else under `src/`, `tests*/`, `scripts/`, `docs/`

Own work, AGPL-3.0-or-later, SPDX header per file.

## Does not ship, but is fetched at run time

These are the weights the code downloads on first use. They are not in the repository and not in
any distribution built from it, so they do not affect the licence of this package; they do affect
anyone who runs it.

| artefact | fetched by | from | licence |
| --- | --- | --- | --- |
| `hand_landmarker.task` | `anatomy_qc.py` (`HAND_TASK_URL`) | `storage.googleapis.com/mediapipe-models/hand_landmarker/.../float16/1/` | Apache-2.0 (Google AI Edge MediaPipe model garden) |
| `face_landmarker.task` | `anatomy_qc.py` (`FACE_TASK_URL`) | `storage.googleapis.com/mediapipe-models/face_landmarker/.../float16/1/` | Apache-2.0 (same model garden) |
| `pose_landmarker_full.task` | expected on disk by `geom/keypoints.py`, `medusa_sheet_service.py`, `vfx_landmarks.py` | same MediaPipe model garden; no download helper in this repository, so it is provisioned by hand | Apache-2.0 |
| `hand_yolov8s.pt` | `comfy_generation_service.ensure_hand_yolo_weights()` | `huggingface.co/Bingsu/adetailer` | AGPL-3.0, the ultralytics YOLOv8 licence, inherited by these ADetailer weights |
| `face_yolov8m.pt` | expected on disk under `ZYG_COMFY_ROOT/models/ultralytics/bbox/` by `comfy_generation_service.py`, `hand_qc_service.py`, `char_state_service.py`, `settings.py` | same ADetailer repository; provisioned with the ComfyUI stack | AGPL-3.0, same inheritance |
| `en_core_web_sm` | `spacy.load()` in `tools/nlp_tools.py` | spaCy model index | MIT |

Notes on the two YOLO entries. The `ultralytics` runtime itself is AGPL-3.0, and so are the
Bingsu weights built on it. The research note at `pipeline_debug.py:1604-1606` records the
position taken: acceptable for internal QC signals, and the planned replacement before any
redistribution scenario is MediaPipe Hands (Apache-2.0). Since this repository is itself
AGPL-3.0-or-later, the runtime licence is compatible; what the note is really guarding against is
a future relicensing of this project.

The MediaPipe download target defaults to `ZYG_MP_MODEL_DIR`, which falls back to
`src/zyg_workflows/data/models/mediapipe`, a path inside the package. The directory does not
exist in the checkout and nothing is committed there, but the default should point under
`ZYG_DATA_ROOT` like every other runtime path. Set `ZYG_MP_MODEL_DIR` explicitly until it does.

## Declared but deliberately unpinned dependencies

`pyproject.toml` records, with the reason on each, the imports that are **not** declared as
dependencies: `basicsr` and `realesrgan` (upstream unmaintained, advisories with no fixed
version, so declaring them would make the lock permanently vulnerable), `facenet-pytorch` (caps
torch below the security floor and does not resolve), `bpy` (comes with Blender, not a PyPI
distribution), and the soft imports that the code paths already guard (`trimesh`, `pycolmap`,
`insightface`, `open_clip`, `nemo`, `speechbrain`, `faiss`). None of them is vendored here.

The pinned set is in `requirements-lock.txt` and is audited with `pip-audit`; CI runs
`pip-audit --strict` over the project.

## How to keep this document true

- A new asset committed under `src/`: add it here with its origin, and give it an SPDX header or a
  sidecar `.license` so `reuse lint` stays green.
- A new weight downloaded at run time: add a row to the table above with the URL and the licence,
  and make sure `licence_provenance.py` has a registry entry for it, because an unregistered
  weight is classified `unknown` and will fail the gate rather than pass it silently.
- A new third-party library vendored into the tree: it needs its own licence file in `LICENSES/`
  and its own section here. Prefer a dependency over a vendored copy.
