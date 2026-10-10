<!-- SPDX-FileCopyrightText: 2026 Zygomatic -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Contributing

**What to expect.** This is an operator's studio, built and run by one person; there is no
team behind it. Issues — bug reports, questions, ideas — are welcome. Pull requests are
read, but open an issue to discuss the shape first: the layering rule and the gate are
non-negotiable, and a PR that fights either will be declined politely. The
[code of conduct](CODE_OF_CONDUCT.md) applies everywhere in this repository.

1. `uv sync` at the root, then `uv run pre-commit install` once. Ruff, gitleaks, bandit and
   reuse then run before every commit, for every package.
2. `uv run scripts/scan.sh` is the full gate and is the same gate CI runs. Keep it green.
   Pushes run that full gate too, through pre-commit's `pre-push` stage, so a red tree never
   leaves the machine. Install it once with `pre-commit install --hook-type pre-push`.
3. Every Python file carries an SPDX header (`uv run reuse annotate` adds one). Every new
   environment read is declared in the package's settings or paths module and appears in its
   `docs/configuration.md`; never read `os.environ` ad hoc.
4. Respect the layering: `zyg_workflows` imports nothing from the other three packages.
   import-linter enforces it; if a change needs the base library to call upward, add a hook
   in `zyg_workflows.runtime` instead.
5. Tests that need a GPU or a local service carry the `gpu` or `service` marker so the CPU
   run stays runnable on any machine.
6. A change that touches one package is committed with that package's prefix in the subject
   (`workflows:`, `dashboard:`, `zero-public:`, `creator-nexus:`); a change across packages
   says so.

## Commit messages

`scripts/commit_msg_check.py` runs as pre-commit's `commit-msg` hook (installed by
`uv run pre-commit install --hook-type commit-msg --hook-type pre-commit --hook-type pre-push`)
and refuses a message that breaks any of these rules:

a. the subject — the first line that is not a `#` comment — is 10 to 72 characters, has no
   trailing period, and does not open with the bare label `fix`, `wip` or `update`;
b. a blank line follows the subject, then a body of at least one line saying what changed
   and why;
c. no attribution trailer in the message: `Co-Authored-By`, a `Signed-off-by:` naming an agent,
   and `Generated with` are refused. Who and what writes this code is stated once, in the
   README's "How it is built" section, not per commit;
d. subjects git writes itself are exempt: `Merge `, `Revert `, `fixup! `, `squash! `.

```
workflows: move the pufferball sheet into its own package

The 1,200-line module held three unrelated stages; each is now its own file and
the original path stays a re-export shim, so no importer changes.
```

`python3 scripts/commit_msg_check.py --selftest` checks the rules against inline samples.

Every other rule a gate enforces — module and function size, errors, logging, paths,
dependencies, types, tests, and how to re-baseline a ratchet honestly — is in
[docs/conventions.md](docs/conventions.md).
