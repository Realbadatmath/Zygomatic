<!-- SPDX-FileCopyrightText: 2026 Zygomatic -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Project rules for agent sessions

Read [docs/conventions.md](docs/conventions.md) once: it is the full set of rules, each named
with the gate that enforces it. This page is the short list that applies to every session.

**Tools.** Always `uv run --no-sync <tool>` from the repo root (the `VIRTUAL_ENV` warning is
harmless). ruff, pytest, pyright, pre-commit and the gate scripts live in `.venv`.

**Before any push**, run `uv run --no-sync bash scripts/scan.sh` and get `== RESULT: CLEAN`; the
`pre-push` hook runs the same gate, so a red tree never leaves the machine. **Never `--force`
push**, and never `--no-verify`: if a hook refuses, fix the cause. `origin` is a public GitHub
repository — do not push unless the task says to.

**Commits.** Subject ≤72 characters, imperative, no trailing period; a blank line; a body of at
least one line saying what changed and why; no attribution trailer (`Co-Authored-By`,
`Signed-off-by:` naming an agent, `Generated with`): authorship is stated once, in the README's
"How it is built" section. Commit only the files you changed, by
name, in one command:

```bash
git add <paths> && git commit -q -m "<subject>" -m "<body>" -- <paths>
```

Never `git add -A` or `git add .`. On `index.lock`, wait 5 s and retry — up to 30 executors
commit in parallel.

<!-- REUSE-IgnoreStart -->
**Licence headers.** Every new `.py` file opens with `# SPDX-FileCopyrightText: 2026 Zygomatic`
and `# SPDX-License-Identifier: AGPL-3.0-or-later`; every new non-code file needs a
`<file>.license` sidecar with the same two lines, or `reuse lint` fails.
<!-- REUSE-IgnoreEnd -->

**Modularization is suggested, never started.** A file over the 1000-line cap or in the 800-line
brand band becomes a session-tree suggestion (`st suggest`) for the operator to accept; do not
split files on your own initiative. New modules a split creates aim for 300–600 lines.

**Scope.** Do the task you were given; things you noticed but were not asked to fix go in the
report's notes, not the diff. Do not restart services unless the task says so.
