<!-- SPDX-FileCopyrightText: 2026 Zygomatic -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Changelog

All notable changes to this repository. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are tags at the
repository root and all four packages move together (see `docs/monorepo.md`).

## [Unreleased]

- README: a "Start reading here" list (three files) and a "How it is built" section that states
  how agents and the operator produce this code; the attribution-trailer rule now points there.
- Package versions move with the root: all four `pyproject.toml` say 1.0.0.
- Docs say "four packages" where they still said "four repositories".
- Two unreferenced images (5.3 MB together) removed from the dashboard package.

## [1.0.0] — 2026-10-09

The clean base. The public history starts at this commit (see `README.md` → History and
`docs/monorepo.md` → Provenance); the entries below it describe the development history that
was squashed into it.

- **No forged module identities.** The 310 `__file__`/`__name__` rebinds the modularization
  waves left in 240 split modules are gone, together with every `_origin.py`; paths come from
  each package's `paths` module and logger channels are explicit strings
  (`scripts/path_parity.py` proves the resulting paths unchanged over 1,239 values).
- **No function over 300 lines.** The 103 functions above that line (44,397 lines together)
  are orchestrators over extracted helpers in sibling modules, each helper with a docstring and
  a unit test; the long-function counter is 0.
- **No `print()` in library code.** 1,766 of 3,028 prints became logger calls through
  `scripts/codemod_print.py`; ruff T20 is enforced in all four packages, and the 1,262 left
  inside `main()` blocks of 255 non-CLI modules are grandfathered file by file.
- **No name injection.** The 64 names the split packages used to receive by `setattr` at the
  end of a package import are imported where they are used; the file-level `F821`
  suppressions that hid them are gone, and `ruff --select F821 --ignore-noqa` is clean.
- **Nothing happens at import.** Modules that configured log files, rewrote tracked assets,
  changed directory or created directories when imported no longer do.
- **Gates that hold the line.** `scripts/ratchet.py` records twelve quality counters per file
  (long functions, broad excepts, prints, noqa markers, rebinds, sys.path edits, legacy
  literals, missing docstrings, file-level suppressions, non-Python files, pyright errors,
  coverage) and refuses a commit that raises one; `ratchet.py direction` refuses a push whose
  baseline rose against `origin/main` without a stated reason; the scan fails on undefined
  names and on file-level suppressions; CI runs the gate, the four suites with a coverage
  ratchet, and pyright with its diagnostics kept as an artifact; a commit-msg hook enforces
  the message shape.
- **Path hygiene.** Tracked paths carry no spaces, tests write nothing into the source tree,
  caches the code refreshes are not in git, and every test passes with the crews root absent
  and under UTC.

- Demo page (`docs/demo.md`) with three clips and six screenshots of the operator GUI under
  `docs/media/`, linked from the top of the README.
- Dashboard god-module split: shared infrastructure moved out of `crewai_web_gui` into
  `appcore.py` and a `gui/` package (runtime state, telemetry, time utilities, the Zero
  store, the scholarly bridge, the controller); `kanban/`, `gamesim/` and `video_studio/`
  became packages. Importing the dashboard module needs neither `crewai` nor any
  environment variable, so the dashboard suite runs 563 tests instead of skipping them.
- `inspection.html` dropped from 36,501 to 2,336 lines: its styles and 29k-line inline
  script became `inspection.css` and `inspection_app.js`.
- Gate hardening: the scan now covers the three custom test harnesses
  (`capability_tests`, `tests_arch_ext`, `tests_vst`), which also lost their
  `/home/<user>` path literals; a pre-push hook runs the whole gate.
- Project meta: changelog, code of conduct, issue and pull-request templates, a
  model-setup guide (`docs/models.md`), hardware notes in the README.

## [0.3.0] — 2026-10-06

- **Content credentials.** Every deliverable is signed with a [C2PA](https://c2pa.org/)
  manifest naming the generator, pipeline, models and licence; an altered copy reads
  `Invalid`, an intact one chains to the root certificate the public site publishes.
  Public verify page; signing enforced at the egress gates. `ZYG_C2PA` defaults to
  `warn` so a checkout without the operator key still renders.
- Public site: the portfolio speedrun (3:03) joins the portfolio film; the `/Portfolio`
  vanity page takes its invite token from the environment only.
- CI: tests run with ffmpeg installed; history is scanned with the gitleaks binary
  (the gitleaks action cannot start from a parentless root commit).

## [0.2.1] — 2026-10-06

First release cut from this monorepo (the histories of the four packages were joined
with `git subtree` on 2026-10-05; see `docs/monorepo.md` for provenance).

- Portability: detector weights and VDB packs resolve under `ZYG_DATA_ROOT` instead of
  package-relative paths; scripts, tests and shell helpers read their roots from
  `zyg_workflows.paths`.
- Tests that depend on installation data or optional extras skip with a reason instead
  of failing on a machine that lacks them.

## [0.2.0] — 2026-10-05 (pre-monorepo, package tags)

Quality pass across the then-separate repositories: `/home/<user>` literals replaced
with environment-derived roots across `src/`, every historical silent exception
suppression reviewed and converted to logged handling, and the scholarly pipeline
monolith split into `zyg_workflows/scholarly/` stage modules.

## [0.1.0] — 2026-10-05 (pre-monorepo, package tags)

The studio rebuilt as four clean repositories — `workflows`, `dashboard`,
`zero-public`, `creator-nexus` — with secrets out, imports rewritten to package names,
an SPDX header on every file, and a scan gate (ruff, bandit, gitleaks, reuse,
import-linter) that had to pass before the first commit, so the history is clean by
construction.
