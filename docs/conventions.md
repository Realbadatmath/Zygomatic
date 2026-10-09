<!-- SPDX-FileCopyrightText: 2026 Zygomatic -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Conventions

Every rule on this page is enforced by a gate, and every gate is listed with the rule it
enforces. Nothing here is a style preference waiting for a reviewer's opinion: a commit that
breaks one of these is refused by `pre-commit`, by the `pre-push` gate, or by CI. If a rule
feels wrong, change the gate and this page in the same commit — not the other way round.

Gates: `scripts/modcheck.py` (module size), `scripts/ratchet.py` (quality counters),
`scripts/commit_msg_check.py` (commit messages), `scripts/scan.sh` (the full publishability
gate), `.importlinter` (layering), `.github/workflows/ci.yml` (the same three in CI).

## Commits

Checked by `scripts/commit_msg_check.py`, run as pre-commit's `commit-msg` stage.

- The subject — the first line that is not a `#` comment — is 10 to 72 characters, imperative,
  with no trailing period, and does not open with the bare label `fix`, `wip` or `update`.
- A blank line follows the subject, then a body of at least one non-empty line saying **what**
  changed and **why**.
- No attribution trailer anywhere in the message: `Co-Authored-By`, a `Signed-off-by:` naming
  Claude, and `Generated with` are refused. They never land in this history.
- Subjects git writes itself are exempt: `Merge `, `Revert `, `fixup! `, `squash! `.
- A change inside one package carries that package's prefix in the subject (`workflows:`,
  `dashboard:`, `zero-public:`, `creator-nexus:`); a change across packages says so.

Commit named paths, never `git add -A`. `python3 scripts/commit_msg_check.py --selftest`
checks the rules against inline samples and prints `selftest: 15/15 samples behaved as
expected`. More, with an example message, in [CONTRIBUTING.md](../CONTRIBUTING.md).

## Module size

Checked by `scripts/modcheck.py check` (rules A and C; rule B is the split work itself, planned
on the session-tree board).

- **Hard cap, 1000 lines.** A tracked `.py` file that is not in `scripts/modcheck_baseline.json`
  may never exceed it. Files already over the cap when the gate arrived are listed in the
  baseline with the line count they had; a listed file may shrink but never grow.
- **The brand line is 800** (80 % of the cap). A file above it, or any baseline file, is
  *branded*: it may only **receive connector code** — imports, re-export aliases (`name = other`,
  `name = module.attr`), an `__all__` assignment, a docstring, a `if TYPE_CHECKING:` block — and
  its growth must be covered by those added lines. Logic goes into a new module.
- **A split aims for 300–600 lines per new module.** Under 300 is gold, under 600 silver; those
  are reporting medals, not thresholds. Never force-split a cohesive 600–800-line section to win
  a medal, and never let a module a split creates pass 800.
- The file a split empties ends as a thin re-export shim or is deleted. Importers do not change.
- Exemptions are paths under `"exempt"` in the baseline (each with a reason) and files carrying
  a `# zyg: no-split` marker in their first 60 lines — provenance files where the layout *is* the
  spec. Both are deliberate; neither is a place to hide new code.

`scripts/modcheck.py report` ranks the offenders and the brand-band files. Those reports feed
modularization trees, which are **suggested** to the operator (`st suggest`), never created.

## Function size

- A `def`/`async def` longer than **300 lines** — methods and nested functions included — counts
  against the `long_functions` ratchet. 102 of them exist; the number may only fall.
- Fix one by extracting helpers, not by reflowing it. Each extracted helper gets a docstring and
  **a unit test of its own**: a helper nobody calls from a test is a helper nobody can refactor.
- A helper's parameters come from what the block actually binds, not from the order the source
  happened to be in. Pull the dataflow out first, then move the lines.

## Errors

- **No new broad excepts.** `except Exception`, `except BaseException` and a bare `except:` all
  count against the `broad_except` ratchet (3887 today, falling only).
- Catch the exception you can actually handle, on the narrowest statement that raises it, and
  either recover or re-raise. A broad catch that swallows and logs is a bug that will be reported
  as "nothing happened".
- When you touch a function that already has one, narrow it. That is how the counter goes down.

## Imports

- **Every name a module uses is imported at the top of that module.** A function-local import
  exists only to break a real import cycle, and then it carries the comment that names the cycle;
  "it is only needed in one branch" is not a reason.
- **No module writes into another module's namespace.** A re-export package binds the names in its
  own `__init__`; it never assigns attributes onto a sibling or a parent to make a name appear
  there. A name that is not bound where it is read is an `F821` waiting to happen.
- **`F821` is never suppressed.** `scripts/scan.sh` runs `ruff check --select F821 --ignore-noqa`
  over `packages/*/src`, so a `# noqa` cannot hide an undefined name: the fix is to import or
  define it.
- **No file-level suppression** — `# ruff: noqa`, `# ruff: noqa: F401`, `# pyright: basic`,
  `# type: ignore` at the top of a file switch the rule off for everything below, including the
  finding nobody has made yet. Narrow it to the line. scan.sh fails on any file-level
  suppression except `E402` (an import that genuinely has to sit below bootstrap code) and
  `F401` (the split modules' re-export surfaces, which should declare `__all__` instead); those
  two are tolerated only while the ratchet's `file_noqa` counter (277 files on 2026-10-09)
  drives them to zero. **NEW code gets neither** — a file-level suppression it adds pushes that
  counter up, and the ratchet refuses it.

## Logging

- Module logger, once, at the top: `_zyg_log = logging.getLogger(__name__)`. Call it through the
  name (`_zyg_log.warning(...)`); never pass the logger between modules with
  `from other import _zyg_log` — assign it in the module that uses it.
- **No `print()` outside a CLI or a `__main__`.** A CLI entry point may print; the library it
  calls may not. Two gates enforce this:
  - **ruff `T20` is on** in all four `packages/*/ruff.toml`, so a `print` (or `pprint`) in library
    code fails `ruff check` — and therefore `scripts/scan.sh`, the pre-commit and the pre-push
    hook. Print is allowed only where `[lint.per-file-ignores]` grants `T201`: `__main__.py`,
    `cli.py`, `*_cli.py`, `selftest.py`, `scripts/`, the test trees, and the named list of
    grandfathered CLI modules whose every print already sits inside a `main()` body or an
    `if __name__` block. **Adding a module to that list is not a way to keep a new print** — a new
    CLI gets a `main()` and a `__main__.py` instead; the list only records what predates the gate.
  - The `print_calls` ratchet (1277 today) counts statement-level `print(` lines in library code
    and may only fall, so the grandfathered modules cannot grow new prints either.
- Libraries never configure handlers or levels. The process entry point does that.

## Paths

- Every filesystem root and service URL comes from `zyg_workflows.paths`: `ZYG_HOME`,
  `ZYG_CREWS_ROOT`, `ZYG_DATA_ROOT`, `ZYG_OUTPUT_ROOT`, `ZYG_MODELS_ROOT`, the ComfyUI
  directories, the service URLs and ports. Each is read from the environment with the production
  default as its fallback, so an unconfigured checkout behaves like the installation.
- Inside a package, files that ship with the code are reached through `PKG_DIR` (the package
  directory) and `DATA_DIR` (`PKG_DIR / 'data'`). Never recompute either from `__file__` locally.
- **A pre-monorepo literal (`Zygomatic Full`, `agents/crews`) outside `zyg_workflows/paths.py` is
  a zero-rule**: the `legacy_literals` counter is at 0 and may not rise.
- **Never rebind `__file__` or `__name__`** (`dunder_rebinds`, 310 today, falling only) and
  **never edit `sys.path`** outside a `__main__.py` or an `entry.py` (`sys_path_edits`, 197).
  Both exist only as scars from the pre-package era; a new file gets neither.
- Package data lives under `<pkg>/data`, `templates/` or `static/` and nowhere else. The *set* of
  non-Python directories under `packages/<p>/src/<pkg>/` is frozen by `nonpy_dirs`: adding a file
  to a known one is free, inventing a new one is refused.
- **No new path with a space in it** (`space_paths` is a zero-rule at 0).
- Every environment read is declared in the package's settings or paths module and documented in
  its `docs/configuration.md`. Never read `os.environ` ad hoc.
- Layering, enforced by `.importlinter`: `zyg_workflows` is the base and imports nothing from the
  other three. `zyg_zero` and `zyg_nexus` build on it; `zyg_dashboard` sits on top. If the base
  library needs to call upward, register a hook in `zyg_workflows.runtime`.

## Dependencies

- Add one with `uv add` in the owning package, never by hand in `pyproject.toml` and never with
  bare `pip install`. The root `uv.lock` is committed with the change that needs it.
- Each package also keeps a resolved `requirements-lock.txt`, regenerated with the exact
  `uv pip compile` command in the comment block at the top of its `pyproject.toml`.
- CI audits those pins: `pip-audit --strict --desc off -r packages/workflows/requirements-lock.txt
  --no-deps`. A new dependency with a known advisory fails the `gate` job, so audit before you
  commit the lock, not after the push.
- A dependency is also a licence: everything must stay REUSE-compliant and AGPL-compatible.

## Types

- `pyright` runs in **basic** mode over all four `src` trees (`pyrightconfig.json`), and its error
  count is ratcheted **per package** in `scripts/ratchet_baseline.json` (3199 at the seed).
- The counts may only go down. Annotate what you touch; do not silence with `# type: ignore` —
  that trades a type error for a `noqa`-class marker, and `noqa_markers` (2611) is ratcheted too.
- CI's `types` job is `ratchet.py check --with-pyright`. It fails on a *rise*, not on a non-zero
  count, so a file you clean up is progress even while the repo is far from zero.

## Tests

The coverage baseline is the number the CI runner measures (CPU only, no local services, no assets), never a local run: a developer's machine executes more tests and would set a ceiling CI can never reach. Raise it only with CI's own figure.

- Coverage is ratcheted **up**, per package, in `scripts/ratchet_baseline.json`: workflows 8.12 %,
  dashboard 24.18 %, zero-public 14.53 %, creator-nexus 36.75 %. CI's `tests` job runs
  `pytest -q -m "not gpu and not service" --cov=<module>` and then
  `ratchet.py coverage coverage.xml --package <p>`; a line rate below the baseline fails.
- Every helper extracted from a long function gets a unit test in the same commit. That is how
  coverage rises without a campaign.
- **Tests prove behaviour, not source text.** Assert what a function returns, writes or raises —
  never that a file contains a string, that a module has N lines, or that a name appears in the
  source. A test that reads the code it tests passes a refactor it should have caught.
- Tests needing a GPU or a running local service carry the `gpu` or `service` marker, so the CPU
  run stays runnable on any machine.
- `missing_docstrings` (2837) is ratcheted: a new public module-level function or class gets a
  docstring saying what it does.

## How the gates run

| when | what runs |
| --- | --- |
| **every commit** (`pre-commit`) | ruff `--fix`, ruff-format, gitleaks, bandit per package, reuse, `modcheck.py check`, `ratchet.py check` |
| **the commit message** (`commit-msg`) | `commit_msg_check.py` |
| **every push** (`pre-push`) | `bash scripts/scan.sh` — the full publishability gate |
| **CI** (`.github/workflows/ci.yml`) | `gate` (scan.sh's steps + full-history gitleaks + import-linter + pip-audit), `tests` (four packages, coverage ratchet), `types` (`ratchet.py check --with-pyright`) |

Install the hooks once:

```bash
uv sync
uv run pre-commit install --hook-type commit-msg --hook-type pre-commit --hook-type pre-push
```

Then run the whole thing yourself before any push: `uv run --no-sync bash scripts/scan.sh`.
It ends in `== RESULT: CLEAN` or `== RESULT: FINDINGS`. Tools come from the repo's `.venv`; run
them as `uv run --no-sync <tool>` from the repo root so ruff picks each package's own
`ruff.toml` (single quotes, line length 120).

Both ratchets read file contents from **git's index**, not the worktree, so they always measure
the tree that is about to be committed. An unstaged edit neither passes nor fails a gate.

## Re-baselining honestly

`scripts/ratchet.py baseline` re-records the counters. It is a **downwards-only** tool: a counter
that improved is tightened, and that is all it may do without being told. A counter that went up
needs `ratchet.py baseline --allow-up "<reason>"`, which writes the reason and the exact
`counter old→new` deltas into the `allow_up` list in `scripts/ratchet_baseline.json` and says so
loudly on stdout. The one entry there today reads *"seed the new pyright_errors counter: 0 is the
absent-metric default, not a measured count"* — that is the standard the reason has to meet.

`--allow-up` used to be a hole: `check` only compares the tree with the baseline shipped beside
it, so once a higher number was recorded no gate noticed (commit 51c8b16 raised `broad_except`
3887→3968 and CI stayed green). `scripts/ratchet.py direction` closes it by diffing the recorded
totals against `origin/main`'s baseline: **raising a counter needs `ZYG_RATCHET_UP_OK=<reason>`
set on the push, and the same reason in the commit message.** Without it the push and CI fail on
the rise. It runs in `scripts/scan.sh` and in CI's `gate` job.

The same applies to `modcheck.py baseline`, which re-records shrunk files so the line-count
ratchet only ever tightens, and to `ratchet.py coverage FILE --package P --baseline`.

Three things `--allow-up` is never for: making a red commit go green, recording a number you did
not measure, and absorbing someone else's regression. Prefer `ratchet.py report` first — it shows
the delta and the top ten files per metric, which is usually enough to find the file that moved.
