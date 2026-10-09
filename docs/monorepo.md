<!-- SPDX-FileCopyrightText: 2026 Zygomatic -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# How this repository is put together

## Provenance

The studio was rebuilt on 2026-10-05 as four clean repositories (secrets out, imports rewritten
to package names, licence headers on every file, a scan gate that had to pass before the first
commit). The same day they were joined into this repository with `git subtree add`, one prefix
per package, so each package's commits are preserved verbatim under `packages/`:

| prefix | former repository |
| --- | --- |
| `packages/workflows` | `zygomatic-workflows` |
| `packages/dashboard` | `zygomatic-dashboard` |
| `packages/zero-public` | `zygomatic-zero-public` |
| `packages/creator-nexus` | `zygomatic-creator-nexus` |

The code the studio ran before that date lived in one working tree with a 62 GB history that
carried credentials and commercially licensed asset packs. That history was archived offline
and is not part of this repository or of any of the four it was built from.

On 2026-10-09, after the clean-base trees had finished (gates, rebinds, long functions, prints,
injected names), the whole history above — the subtree merges included — was squashed to one root
commit for the public repository. The 258-commit development history is kept by the maintainer as
a local git bundle (`zygomatic-history-2026-10-09.bundle`) and is not pushed anywhere; the per-package
provenance in the table stays true of the code, not of the visible commits.

## Working across packages

- The workspace is one uv project (`pyproject.toml` at the root). `uv sync` installs the four
  packages editable, so a change in `packages/workflows` is visible to the dashboard at once.
- Each package keeps its own `pyproject.toml`, `ruff.toml`, `REUSE.toml`, `.importlinter`,
  `scripts/scan.sh` and tests, and can still be installed on its own with pip. The root files
  add the cross-package checks, the shared CI and the shared pre-commit hooks.
- Package versions move together. The root `pyproject.toml` carries the repository version; a
  tag `vX.Y.Z` at the root is the release.
- Dependencies between packages are declared as workspace sources
  (`zygomatic-workflows = { workspace = true }`), never as relative paths.

## CI

`.github/workflows/ci.yml` runs three jobs on every push and pull request. **gate** mirrors
`scripts/scan.sh`: each package's own gate (ruff, bandit, gitleaks, reuse, import-linter,
compileall, test collection, address and path greps), then the whole-repository checks — the
cross-package import contract, root `reuse lint`, the workspace-source and stray-CI greps, and
a gating `pip-audit --strict` over `packages/workflows/requirements-lock.txt`. **tests** is a
matrix over the four packages, each pairing a package with its import name
(`workflows`/`zyg_workflows`, `dashboard`/`zyg_dashboard`, `zero-public`/`zyg_zero`,
`creator-nexus`/`zyg_nexus`); it runs `pytest -m "not gpu and not service"` with
`--cov=<module> --cov-report=xml:coverage.xml` and then `scripts/ratchet.py coverage` so a
package's line rate may never fall more than 0.5 pp below the rate recorded in
`scripts/ratchet_baseline.json`. **types** runs `scripts/ratchet.py check --with-pyright`,
which type-checks the four `src` trees against `pyrightconfig.json` (basic mode, Python 3.12)
and fails if any package's pyright error count grows above its baseline. All three counters
only ever ratchet down; re-recording one upwards needs
`ratchet.py baseline --allow-up "<reason>"` and a justification in the commit message.

## What is deliberately not here

- Model weights, LoRAs, voice seeds, training sets, renders, job state, logs: all under the
  roots named in each package's `docs/configuration.md`.
- Deployment secrets, invite tokens, API keys: environment variables or files outside the
  checkout.
