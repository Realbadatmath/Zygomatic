<!-- SPDX-FileCopyrightText: 2026 Zygomatic -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Zygomatic

**[Demo](docs/demo.md)** · [Models](docs/models.md) · [Monorepo layout](docs/monorepo.md) · [Conventions](docs/conventions.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

[![ci](https://github.com/Realbadatmath/Zygomatic/actions/workflows/ci.yml/badge.svg)](https://github.com/Realbadatmath/Zygomatic/actions/workflows/ci.yml)
[![licence: AGPL-3.0-or-later](https://img.shields.io/badge/licence-AGPL--3.0--or--later-blue)](LICENSE)
[![REUSE compliant](https://img.shields.io/badge/REUSE-compliant-green)](https://reuse.software/)

An AI content studio that runs on one machine: it plans a video, generates its stills and
clips, builds and keeps its characters, speaks and scores it, gates the result on quality and
licence, and publishes it. Everything runs on local models (ComfyUI, Blender, local TTS and
music models, a local LLM) with an operator GUI in front and a small public site at the edge.

[zero.zygomaticszero.com](https://zero.zygomaticszero.com) is this studio's own installation:
everything published there — every still, scene, voice and film — was produced by the code in
this repository, on the machine described below. The site is the output; this is the factory.

**See it before reading it:**

[![Steel sand grains form the words Zygomatic Ai, then Ubi pops in and hops on each word](docs/media/intro-ubi-sand-letters.gif)](docs/demo.md)

**[Demo page](docs/demo.md)**: three clips (the intro above, a solidify and de-solidify shot, the VFX Studio
running), seven screenshots of the operator GUI and three overview slides.

- [Zygomatic Atlas](https://zero.zygomaticszero.com/atlas): a zoomable map of the whole studio, every service and the
  traces between them. [Download the file](https://zero.zygomaticszero.com/atlas/download) to keep it offline.
- [Zygomatic Architecture](https://zero.zygomaticszero.com/architecture): the compact edition, structure only, one
  screen. [Download the file](https://zero.zygomaticszero.com/architecture/download).
- [Portfolio video](https://zero.zygomaticszero.com/portfolio) (17:36): the studio explained tab by tab by its own
  characters, every scene produced by the pipelines in this repository.
- [Portfolio speedrun](https://zero.zygomaticszero.com/portfolio#speedrun) (3:03): the whole studio in three minutes,
  narrated by Ubi.

This repository holds the whole studio as four packages. Each one was a repository of its own
until 2026-10-05; their histories are preserved under `packages/`.

| package | Python package | what it is | listens on |
| --- | --- | --- | --- |
| [`packages/workflows`](packages/workflows/) | `zyg_workflows` | the base library: pipelines, studios, services, QC gates, licence provenance, geometry. No user interface | nothing (library and jobs) |
| [`packages/dashboard`](packages/dashboard/) | `zyg_dashboard` | the operator surface: Flask GUI, kanban board, approval queue, metrics hubs, the hub launcher, the Session Tree agent job board, deployment units | 5000, 8899, 7100, 7000-7777 |
| [`packages/zero-public`](packages/zero-public/) | `zyg_zero` | the outward-facing site: an invited visitor's prompt goes on a queue, the pipelines do the work, the result streams back. Plus three small sidecars | 5001, 8750 |
| [`packages/creator-nexus`](packages/creator-nexus/) | `zyg_nexus` | the channel and creator planning board: channel registry, upload and marketing pipelines, metrics | 8090 |

Each package README describes what is inside it. Start with
[`packages/workflows/README.md`](packages/workflows/README.md) and
[`packages/workflows/docs/ARCHITECTURE.md`](packages/workflows/docs/ARCHITECTURE.md).

## Start reading here

Three files show how this codebase thinks, in about twenty minutes:

- [`qc_contract.py`](packages/workflows/src/zyg_workflows/qc_contract.py): the authority layer every
  QC gate reports through. Three verdicts instead of two, so a gate that could not look never
  reports green. Each rule in its header cites the production defect that bought it.
- [`licence_provenance.py`](packages/workflows/src/zyg_workflows/licence_provenance.py): answers one
  question per ComfyUI graph, is every weight in it cleared for commercial publication, and
  charges a LoRA with the licence of the base it was trained from. The one defect class an
  operator cannot see.
- [`scripts/ratchet.py`](scripts/ratchet.py): twelve quality counters recorded per file that may
  only go down. It reads the git index, not the worktree, so it measures the tree about to be
  committed, and `direction` refuses a push whose baseline rose against `origin/main`.

## The one rule between the packages

**`zyg_workflows` is the base. The dashboard, the public site and the creator nexus import it;
it imports none of them. The public site and the creator nexus never import the dashboard.**

The rule is machine-checked by import-linter (the layers contract in [`.importlinter`](.importlinter))
and is part of the gate, so the base library stays usable without any GUI.

## Install

[uv](https://docs.astral.sh/uv/) drives the workspace. One command installs all four packages
editable into one virtual environment with their CPU dependencies and the development tools:

```bash
uv sync
uv run pytest packages/workflows -m "not gpu and not service"
uv run scripts/scan.sh
```

Python 3.12 or newer is required; the floor comes from the dependency set. The GPU stack is an
extra (`uv sync --extra gpu`), as are the audio and LLM stacks; see the comment block at the top
of [`packages/workflows/pyproject.toml`](packages/workflows/pyproject.toml) for what is deliberately
not declared and why. `bpy` is Blender's own module and is never installed from PyPI: the code
that imports it runs inside Blender.

Without uv, each package installs on its own with `pip install -e packages/<name>[dev]`, base
library first.

## What it runs on

The reference installation is one Linux box: an RTX 4090 (48 GB VRAM), a 24-thread
i7-13700F, 64 GB RAM and a 2 TB NVMe drive — the model library alone claims hundreds of
gigabytes of that. Everything in this repository was built and is run on that machine.

What needs what:

- **No GPU**: the library code, the CPU test suite, the gate, the dashboard GUI, the kanban
  board, the metrics hubs and the public site all run anywhere Python 3.12 runs.
- **An NVIDIA GPU**: every route that renders — image and video generation, upscales, TTS
  and music synthesis, Blender GPU renders. The pipelines are written against CUDA; smaller
  cards mean smaller model choices and batch sizes, and nothing here is tested on
  non-NVIDIA hardware.
- **Model weights**: not in this repository, never downloaded for you.
  [`docs/models.md`](docs/models.md) lists which external tools and model families each
  pipeline expects and where to put them.

### Trying it without a GPU

[`packages/dashboard/deploy/`](packages/dashboard/deploy/) ships a CPU-only container for
exactly this. From `packages/dashboard/`, put two secrets of your choosing in an env file
(`FLASK_SECRET_KEY`, `REDIS_PASSWORD` — see `deploy/README.md` for the full variable list),
then `docker compose -f deploy/docker-compose.cpu.yml up`. That brings up the operator GUI,
the kanban board and the metrics hubs alongside their own Redis and a CPU Ollama; every
route that renders needs a GPU and will say so. The GPU image, the systemd user units and
the nginx front door are documented in
[`packages/dashboard/deploy/README.md`](packages/dashboard/deploy/README.md).

## Configuration

Every filesystem root, service endpoint and feature flag is read from the environment with a
default, so an unconfigured checkout behaves like the production installation. The two that
matter on a fresh machine are `ZYG_CREWS_ROOT` (the tree the jobs read and write) and
`ZYG_DATA_ROOT` (runtime data, job state, the audit trail). Services bind to loopback unless
`BIND_HOST` says otherwise. Each package generates its own reference:

- [`packages/workflows/docs/configuration.md`](packages/workflows/docs/configuration.md)
- [`packages/dashboard/docs/configuration.md`](packages/dashboard/docs/configuration.md)
- [`packages/zero-public/docs/configuration.md`](packages/zero-public/docs/configuration.md)

Runtime data never belongs in the repository: renders, model weights, LoRAs, voice seeds,
training sets, job state and logs all live under those roots and are ignored by git.

## The gate

[`scripts/scan.sh`](scripts/scan.sh) is the publishability gate; CI runs the same steps on every
push. It runs each package's own gate (ruff, bandit, gitleaks, reuse, import-linter, byte-compile,
test collection, and a grep for machine addresses and home directories) and then the checks that
only make sense for the whole repository: gitleaks over the full history, the cross-package
import contract, and the root files' licence headers. Exit code 0 means publishable.

Past that gate, every deliverable is signed. Content credentials — a [C2PA](https://c2pa.org/)
manifest embedded in the file itself, naming the generator, the pipeline, the models and the
licence — make a copy that has been altered by one byte read `Invalid`, while an intact one chains
back to the root certificate the public site publishes. `ZYG_C2PA` defaults to `warn`: it signs when
the operator's signing key is present and renders normally when it is not, and the key lives outside
every checkout.
[`packages/workflows/docs/content_credentials.md`](packages/workflows/docs/content_credentials.md) says what a
credential proves and what it does not, which outputs are sealed, and how to verify one.

## How it is built

One person operates this studio; nobody else has committed to it. Most of the code was typed by
Claude agents working under that operator's direction, and the repository is arranged so that
this is safe rather than hidden. Work arrives as a *tree* of tasks on the Session Tree board
([`packages/dashboard`](packages/dashboard/)): the operator and a planning agent write each task
as a brief with a verification command, the board spawns one executor agent per task in its own
session, and a task is only finished when its command passes. The executors never commit; the
operator reviews a tree's reports and commits it once. The gate ([`scripts/scan.sh`](scripts/scan.sh)),
the ratchet and the import contract are the control surface: they decide what lands, not the
agent that wrote it. [`CLAUDE.md`](CLAUDE.md) is the standing instruction set those agents read.

The design decisions, the defect taxonomy, the licence policy and every rule in
[`docs/conventions.md`](docs/conventions.md) are the operator's; the headers of the files above
record which production incident each one answers. Commit messages carry no per-commit
attribution trailer because authorship is stated here, once, for the whole history.

## History

The public history of this repository starts at a single commit, made on 2026-10-09 when the
restructuring of the four packages was complete: the split of the 2026-10-06/07 modularization
waves, every `__file__`/`__name__` rebind and name injection replaced by imports, no function over
300 lines, `print()` out of library code, and the ratchet and scan gates that keep each of those
counters from rising again. The 258 development commits that produced that state — four
repositories joined on 2026-10-05 and the three days of trees that reshaped them — are kept
privately by the maintainer as a git bundle, not here; the releases they carried are listed in
[`CHANGELOG.md`](CHANGELOG.md) for the record, without tags in this history.

## Licence

AGPL-3.0-or-later for every file, declared per file through [REUSE](https://reuse.software/)
(`REUSE.toml` at the root and in each package). See [`LICENSE`](LICENSE).

**Why AGPL.** The studio's licence gates exist because models and assets come with terms
that must be honoured; the same courtesy is asked of this code. AGPL means you can run,
study, change and redistribute all of it — including as a network service — as long as the
people you serve get the same rights. If that doesn't fit your use, open an issue and say
what would.

**Outputs are not covered by the code licence.** A video rendered by these pipelines is not
a derivative work of this code; what you may do with an output is governed by the licences
of the model weights that produced it, which is exactly the question
`zyg_workflows.licence_provenance` answers before anything is published here.

Model weights, LoRAs, datasets and rendered media are not part of this repository and carry
their own licences. `zyg_workflows.licence_provenance` is the component that classifies each
weight a generation graph references before anything is published; its findings are kept
outside the repository with the weights.

## Contributing and security

[`CONTRIBUTING.md`](CONTRIBUTING.md) is the short version: install the hooks, keep the gate
green, declare every new environment read — and what to expect as an outside contributor.
The [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) applies in every space of this repository.
[`SECURITY.md`](SECURITY.md) says how to report a vulnerability. [`CHANGELOG.md`](CHANGELOG.md)
tracks releases. [`docs/monorepo.md`](docs/monorepo.md) records how the four histories were
brought together and how to work across packages.
