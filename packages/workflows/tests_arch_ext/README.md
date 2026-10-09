<!--
SPDX-FileCopyrightText: 2026 Zygomatic

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# tests_arch_ext — the Architecture Studio proof sweep

This directory is **not a pytest suite**. It is 116 standalone family scripts plus one runner, and
every one of them does its work *at import time*: the module body calls into the assistant,
drives headless Chrome and headless Blender, prints `ok` / `FAIL` per check, and ends by
calling `arch_ext_harness.finish()`, which calls `sys.exit()`.

That matters for one practical reason: if pytest ever collected this directory it would
*run* the whole sweep during collection — launching Blender and two dozen browsers — and
then die on the first `SystemExit`. So `pyproject.toml` keeps pytest out twice over,
with `testpaths = ["tests"]` and with `norecursedirs`. Do not undo either; run the sweep
with its own runner instead.

## Running it

```bash
# the shared tools venv, as scripts/run_tests.sh resolves it
PY="${ZYG_TOOLS_PYTHON:-$HOME/repos/.tools/venv/bin/python}"

# the whole sweep: every family, then the cross-family checks
"$PY" tests_arch_ext/test_all.py

# one family while you work on it
"$PY" tests_arch_ext/test_stairs.py
```

Each script exits `0` on `ALL GREEN` and `1` on `N FAILED`, naming the failed checks, so
either form is usable from CI or a pre-push hook. `test_all.py` runs the families
**sequentially on purpose**: `arch_ext_harness` serialises Blender across processes with a
file lock, so running them in parallel only queues them behind each other while holding two
dozen idle Chrome instances open.

`test_all.py` also regenerates `arch_ext/CAPABILITIES.md` from the live registries, which is
why it is the sweep and not just a loop over the others — the index cannot go stale if
proving the system rewrites it.

## What it needs on the machine

The sweep checks three things that can each be right while the others are wrong, so it needs
all three to be present:

| For | Requirement | How it is found |
| --- | --- | --- |
| the assistant (Python, no model) | `zyg_workflows` importable | the venv it runs in |
| the tab (WebGL geometry) | **Google Chrome** + **Playwright** (`playwright install chrome`) | `pw.chromium.launch(channel='chrome')`, software GL via `--enable-unsafe-swiftshader` |
| the tab | the **kanban GUI on :8899** serving `inspection.html` | `http://127.0.0.1:8899/inspection.html#architecture` |
| Blender (mesh build) | **Blender**, headless | `$BLENDER_BIN`, default `/usr/local/bin/blender` |
| fixtures | `tests_arch_ext/fixtures/` | in this directory |

No CUDA device is required: the browser renders through SwiftShader and Blender builds
meshes without rendering them.

The GUI on :8899 lives in the **dashboard** repository (`kanban-server.service` in
production), not here. That is the one dependency this repository cannot satisfy on its own,
and it is why these scripts are not part of the portable suite: `scripts/run_tests.sh` runs
`-m "not gpu and not service"`, and every check in here is a service check.

## Output

`test_all.py` writes `last_sweep.json` and `last_sweep_plans.json` beside itself — the
per-family results and the plans the assistant produced — and per-family artefacts under
`out/`. Both are overwritten on each run; neither is an input to anything.
