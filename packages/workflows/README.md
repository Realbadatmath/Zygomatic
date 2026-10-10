<!-- SPDX-FileCopyrightText: 2026 Zygomatic -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# zygomatic-workflows

The base library of the Zygomatic content studio: the code that plans a video, generates its
stills and clips, builds and keeps its characters, speaks and scores it, gates the result on
quality and licence, and writes the finished assets to a data root.

Everything here is a library or a long-running job. There is no user interface in this
repository; the GUI that drives these jobs lives in `zygomatic-dashboard`, which depends on this
package. Python package: `zyg_workflows` under `src/`.

## What is in it

**Pipelines** (`src/zyg_workflows/pipeline_*.py`), one module per department, each registering a
job and running it on a thread:

| pipeline | module | what it makes |
| --- | --- | --- |
| documentary | `pipeline_scholarly.py` | researched documentary videos (crime, religion, luxury, finance, general), FLUX stills with a film look (`documentary_film_look.py`), narration, assembly |
| storyteller | `pipeline_storyteller.py` | character-driven story scenes with locked identity |
| kids | `pipeline_kids_*.py`, `pipeline_kidsmusic.py` | the children's series (trains, ducks, balloons, shapes, bubbles, moon, car, plane, tractor, which-sound) and the children's music workflow |
| sports | `pipeline_sports.py` | the TokiToki and Arena betting boards: MMA, tennis, soccer, basketball, NFL, all one code path |
| remix | `pipeline_remix.py`, `pipeline_remixai.py` | highlight clips over self-recorded game b-roll, narrated, captioned, QC-gated |
| environments, effects, video, clipfarm, market, crime, char2d | `pipeline_environments.py`, `pipeline_effects.py`, `pipeline_video.py`, `pipeline_clipfarm.py`, `pipeline_market.py`, `pipeline_crime.py`, `pipeline_char2d.py` | the supporting runners the departments above call into |

**Studios** are the option surfaces behind the studio tabs of the dashboard. Each one is a
declarative registry (parameter racks, actions, presets) plus the server-side work, so the page
holds no tool list and a new knob is one entry here:
`character_studio.py`, `creature_sheet_service.py` and `creature_library_service.py`,
`architecture_studio.py`, `mesh_studio.py` (with `mesh_studio_ops/`), `movement_studio.py`,
`voice_studio.py`, `music_studio.py`, `video_studio.py`.

**QC gates.** `qc_contract.py` is the authority layer: three verdicts, not two, so a gate that
could not look never reports green. Around it sit `anatomy_qc.py`, `hand_qc_service.py`,
`identity_qc_service.py`, `continuity_qc.py`, `audio_qc.py`, `voice_qc.py`, `restoration_qc.py`,
`era_gate.py` and `preview_judge.py`. See `docs/QC_README.md`.

**Licence provenance.** `licence_provenance.py` answers one question per ComfyUI graph: is every
weight it references cleared for commercial publication? It classifies each model file as
cleared, non-commercial, territory-excluded or unknown, and resolves LoRA lineage so that a LoRA
is charged with the licence of the base it was fine-tuned from. `lora_attest.py` does the graph
walk.

**Geometry and anthropometry.** `geom/` holds the mesh identity stack: landmarks and keypoints
(`geom/keypoints.py`), body measurement and fitting (`geom/body_metrics.py`,
`geom/fit_proportions.py`, `geom/shape_fit.py`), drift gates (`geom/drift_gate.py`,
`geom/gate_character.py`), and `geom/anthro/` for the anthropometric reference with its integrity
checks and hand correction.

**Services** are the adapters onto the local tools: `comfy_generation_service.py` and
`_comfy_client.py` for ComfyUI, `wan_video_service.py` and `wan_vace_service.py` for video,
`tts_service.py`, `voice_conversion.py` and `narration_service.py` for speech,
`musicgen_service.py` and `ace_step_service.py` for music, `blender_character_service.py` with
`blender_scripts/` for Blender, `lora_trainer_service.py` for training.

## The four packages and the layering rule

The studio is four packages in one repository (each was a repository of its own until 2026-10-05;
the names below are their directories under `packages/`):

| package | Python package | what it is |
| --- | --- | --- |
| `workflows` | `zyg_workflows` | this one: pipelines, studios, services, gates. The base library |
| `dashboard` | `zyg_dashboard` | the operator GUI on port 5000, the kanban board on 8899, the hub, the session tree, deployment |
| `zero-public` | `zyg_zero` | the public site on port 5001, nomologin, medusa |
| `creator-nexus` | `zyg_nexus` | the creator nexus package and its site |

The contract: **the dashboard, the public site and the creator nexus may import
`zyg_workflows`; `zyg_workflows` must never import any of them.** The public site and the creator
nexus must not import the dashboard either. The rule is machine-checked by import-linter (the
layers contract in `.importlinter`), and it is the reason `runtime.py` exists. See
`docs/ARCHITECTURE.md`.

## Install

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

Python 3.12 or newer is required; the floor comes from the dependency set.
`requirements-lock.txt` carries the resolved pins, and the comment block at the top of
`pyproject.toml` records how it is regenerated and how the lower bounds are chosen.

Optional extras, none of which the CPU test run needs:

- `gpu`: torch, diffusers, transformers, ultralytics, safetensors, sentence-transformers
- `audio`: demucs, faster-whisper, librosa, pedalboard, soundfile, mido
- `3d`: shapely
- `llm`: anthropic, langchain

A handful of imports are deliberately **not** declared, each with its reason written out in
`pyproject.toml`: `basicsr` and `realesrgan` (unmaintained, unfixed advisories),
`facenet-pytorch` (caps torch below the security floor), and the soft imports the code paths
already guard (`trimesh`, `pycolmap`, `insightface`, `open_clip`, `nemo`, `speechbrain`, `faiss`).

`bpy` is Blender's own Python module, not a PyPI distribution. Anything that imports it runs
**inside** Blender (see `src/zyg_workflows/blender_scripts/` and `docs/blender_scene_bridge.md`);
do not try to `pip install bpy` for this repository.

## Configuration

Every filesystem root, service endpoint and feature flag is read from the environment with a
default, so an unconfigured checkout behaves like the production installation. The full generated
reference is **`docs/configuration.md`**; `.env.example` is the annotated template. The
declarations themselves live in `src/zyg_workflows/paths.py` (roots and endpoints) and
`src/zyg_workflows/settings.py` (flags).

The two that matter most on a fresh machine:

- `ZYG_CREWS_ROOT`: the tree the crews read and write. Default `~/Zygomatic Full/agents/crews`.
- `ZYG_DATA_ROOT`: where runtime data, job state and the audit trail live. Default
  `$ZYG_CREWS_ROOT/data`.

Runtime data never belongs in the repository. Renders, LoRAs, job state, audit logs and generated
media all land under `ZYG_DATA_ROOT` and `ZYG_OUTPUT_ROOT`; model weights under `ZYG_MODELS_ROOT`
and `ZYG_COMFY_ROOT`. `paths.py` touches no disk at import time except the PATH lookup for
Blender, and the only directory it creates is the scratch directory handed out by `tmp_dir()`.

Services default to loopback (`BIND_HOST=127.0.0.1`): no workflow service is meant to be
reachable from the network.

New code goes through those declarations rather than around them: a filesystem location is a
`paths` constant (`paths.ZYG_COMFY_LORA_DIR`, `paths.tmp_dir('my_job')`), a flag is
`settings.get('ZYG_MY_FLAG', bool)`, and the first element of a subprocess argument list is
`bin.exe('ffmpeg')` — which resolves an absolute path, honours a `ZYG_BIN_FFMPEG` override and
raises a named error instead of failing somewhere inside the shell. No module hardcodes a home
directory, a `host:port` pair or a bare program name; `scripts/scan.sh` greps for the first two as
a gate, and `settings.py`, `.env.example` and `docs/configuration.md` are generated from the reads
themselves by `scripts/gen_settings.py`, so `--check` fails when a new environment read has not
been registered.

## Content credentials

Every deliverable this package ships is signed with a [C2PA](https://c2pa.org/) content credential:
a tamper-evident manifest embedded in the file, naming the generator, the pipeline, the models and
the licence. `provenance_seal.seal()` is called by the mux, render, assembly, take and egress steps;
intermediates, subtitle and JSON sidecars and live transcodes are deliberately left alone.

The seal is fail-safe. `ZYG_C2PA` defaults to `warn`, which signs when `ZYG_C2PA_KEY` and
`ZYG_C2PA_CERT_CHAIN` are on disk and logs and continues when they are not, so a fresh checkout with
no key renders normally; `strict` refuses to ship unsigned, `off` skips it. The key lives under
`~/.config/zygomatic/c2pa` at mode `0600` and never in the repository.

Verify a file with `python -m zyg_workflows.provenance_seal verify FILE`, or with `c2patool` and the
root certificate the public site publishes. **`docs/content_credentials.md`** has the full story: what a
credential proves and what it does not, the hook list, and the key generation and rotation runbook.

## What runs without a GPU, and what does not

On a plain CPU checkout:

```bash
pytest -m "not gpu and not service"   # the tests that need neither a CUDA device nor a local service
scripts/scan.sh                       # the publishability gate
```

`scripts/scan.sh` runs, in order: `ruff check`, `ruff format --check`, `bandit -ll`, gitleaks over
the tree and over the git history, `reuse lint`, the import layering contract, `compileall` over
`src`, `pytest --collect-only`, and a grep for personal data (private IP ranges, personal mail
addresses, home paths). Exit 0 means publishable, and `.github/workflows/ci.yml` runs the same
steps.

Everything else needs hardware or a service, and carries the `gpu` or `service` marker so the CPU
run skips it:

| needs | used for |
| --- | --- |
| CUDA GPU | diffusion stills, Wan video, LoRA training, upscaling, embeddings, VLM judging |
| ComfyUI on `:8188` (`ZYG_COMFY_URL`) | graph-driven generation, HandFixer, detailers |
| Ollama on `:11434` (`ZYG_OLLAMA_URL`) | local LLM calls for research, briefs and prompts |
| Blender (`BLENDER_BIN`) | mesh and character builds, Cycles renders, the scene bridge |
| PostgreSQL (`pgdb.py`) | job and asset state in the production configuration |

The other markers declared in `pyproject.toml` are `slow`, `api` and `timeout`. The test trees are
`tests/` (the default `testpaths`), `tests_arch_ext/` (one test per Architecture Studio capability
family), `tests_vst/` and `capability_tests/`.

## Licence

AGPL-3.0-or-later. The full text is in `LICENSE`, and `LICENSES/` holds the copy REUSE expects.
Every file in the repository carries copyright and licence information: source files have an SPDX
header, data and asset files are covered by `REUSE.toml` or by a sidecar `.license` file. The
check is `reuse lint`, and it is part of both `scripts/scan.sh` and CI.

Third-party material that ships here, and the weights that do not ship but are fetched at
runtime, are itemised in **`docs/PROVENANCE.md`**.

If you deploy a modified version of this code over a network, the AGPL requires you to offer the
modified source to its users.

## A tour of the main modules

Read these first, in this order.

1. **`paths.py`**: every root and endpoint in one place. Nothing in the package should hardcode a
   path, and this is where you look when something writes to the wrong disk. Its
   `LEGACY_PREFIXES` map is the honest record of the call sites still to be converted.
2. **`runtime.py`**: the hook registry. Pipelines call `runtime.bm_record(...)`,
   `runtime.zero_audit_log(...)`, `runtime.workflow_jobs` and friends. Headless, the safe
   defaults apply; with the dashboard running, it has registered its real implementations. This
   is what lets a pipeline run from cron or from a test with no GUI present.
3. **`pipeline_scholarly.py`**: the documentary pipeline, the longest path in the repository and
   the one the other departments were shaped after.
4. **`contact_sheet_pipeline.py`**: how a character comes to exist and stays recognisable.
   `sheet_generate → awaiting_approval → tile_crop → identity_qc → captions → lora_training →
   angle_expansion → lora_refine → done`, with an identity drift gate against the sheet anchor
   and a LoRA flywheel for the angles that face embeddings cannot lock.
5. **`comfy_generation_service.py`**: the ComfyUI execution subsystem. Graph submission, model
   readiness checks, weight fetching, the HandFixer post-pass. The graphs themselves are JSON in
   `_comfy_workflows/`.
6. **`licence_provenance.py`**: the gate whose finding is invisible to the eye. A
   non-commercially-licensed frame and a cleared frame look identical at every resolution, which
   is the whole argument for checking it in software.
7. **`geom/`** and **`geom/anthro/`**: the geometry stack, from landmarks to a fitted body to the
   gates that decide whether a mesh still is the character.
8. **`arch_ext/`**: the plugin seam. One Architecture Studio capability family is one basename in
   five places and nothing else changes. `src/zyg_workflows/arch_ext/README.md` is the onboarding
   document, with a worked example to copy; `src/zyg_workflows/arch_ext/CAPABILITIES.md` is the
   generated index of what exists today, rewritten by the test sweep so that it cannot go stale.
   `studio_ext/` is the same idea for the other studios.

Then `docs/ARCHITECTURE.md` for how the four packages fit together, `docs/README.md` for an
index of every document in `docs/`, and `CONTRIBUTING.md` for the local loop.
