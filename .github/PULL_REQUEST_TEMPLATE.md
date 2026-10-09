<!-- SPDX-FileCopyrightText: 2026 Zygomatic -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

## What this changes

<!-- One or two sentences. Which package(s)? The commit subject should carry the
     package prefix (workflows: / dashboard: / zero-public: / creator-nexus:). -->

## Why

## Checklist

- [ ] `uv run scripts/scan.sh` is green (the same gate CI runs)
- [ ] New environment reads are declared in the package's settings/paths module and
      appear in its `docs/configuration.md`
- [ ] Tests that need a GPU or a running service carry the `gpu` / `service` marker
- [ ] No runtime data, weights, renders or logs are added to the tree
