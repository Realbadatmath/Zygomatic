#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# scripts/scan.sh — the publishability gate of the monorepo. Exit 0 means every scanner is clean.
# Same steps as .github/workflows/ci.yml, runnable offline.
#
# Runs with the tools of the current environment (`uv run scripts/scan.sh` after `uv sync`),
# or with ZYG_TOOLS=<dir> holding venv/bin/{ruff,bandit,reuse,lint-imports,python} and gitleaks.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PACKAGES="workflows dashboard zero-public creator-nexus"
if [ -n "${ZYG_TOOLS:-}" ]; then
  V="$ZYG_TOOLS/venv/bin"; GITLEAKS="$ZYG_TOOLS/gitleaks"
else
  V="$(dirname "$(command -v python)")"; GITLEAKS="$(command -v gitleaks || echo "$ROOT/.venv/bin/gitleaks")"
fi
export ZYG_TOOLS_BIN="$V"
fail=0
step() { printf '\n== %s\n' "$1"; }

# 1. Every package's own gate, in its own directory (ruff, bandit, gitleaks on the tree, reuse,
#    its layering contract, compileall, test collection, personal data, machine paths).
for p in $PACKAGES; do
  step "packages/$p: scripts/scan.sh"
  if ( cd "packages/$p" && ZYG_TOOLS="${ZYG_TOOLS:-}" ZYG_SCAN_NESTED=1 bash scripts/scan.sh ); then :; else fail=1; fi
done

# 2. Whole-repository checks.
step "gitleaks (full history)"
if git rev-parse HEAD >/dev/null 2>&1; then
  "$GITLEAKS" detect --source . --exit-code 1 --no-banner --redact || fail=1
else
  echo "no commit yet — skipped"
fi
step "reuse lint (root)";       "$V/reuse" lint -q || { "$V/reuse" lint | tail -5; fail=1; }
step "import layering (root)";  "$V/lint-imports" --config .importlinter || fail=1
step "ruff (root files)";       "$V/ruff" check scripts && "$V/ruff" format --check scripts || fail=1
step "modcheck (line caps)";    "$V/python" scripts/modcheck.py check || fail=1
step "ratchet (quality counters)"; "$V/python" scripts/ratchet.py check || fail=1
step "ratchet baseline direction"; "$V/python" scripts/ratchet.py direction || fail=1
# An undefined name is a bug ruff already found. --ignore-noqa so a suppression cannot hide one.
step "undefined names"
if undef="$("$V/ruff" check --select F821 --ignore-noqa --output-format concise packages/*/src 2>&1)" &&
  [ "$undef" = "All checks passed!" ]; then
  echo "clean"
else
  printf '%s\n' "$undef"
  echo "fix the name; F821 is never suppressed"
  fail=1
fi
# A file-level suppression hides the next real finding in that file too. Allowed codes are a
# non-empty subset of {E402, F401} — an import that has to sit below bootstrap code, and the
# re-export surfaces the modularization waves left behind. A bare `# ruff: noqa` (every rule,
# for ever) and any other code are findings: narrow them to the line, or fix the code.
step "file-level suppressions"
sup="$(
  grep -rnE "^# ruff: noqa" packages/*/src --include=*.py | grep -vE ':# ruff: noqa:? *((E402|F401)(, *)?)+( +[^A-Z].*)?$'
  grep -rnE "^# pyright: basic|^# type: ignore" packages/*/src --include=*.py
)"
if [ -z "$sup" ]; then echo "clean"; else
  printf '%s\n' "$sup"
  echo "narrow each of these to the line it is about, or fix the code (only E402/F401 may stay file-level)"
  fail=1
fi
step "workspace sources";       if grep -nE 'path = "\.\./' packages/*/pyproject.toml; then echo "package dependencies must be workspace sources"; fail=1; else echo "clean"; fi
step "stray CI";                if ls -d packages/*/.github 2>/dev/null | grep .; then echo "CI lives at the root only"; fail=1; else echo "clean"; fi

printf '\n== RESULT: %s\n' "$([ $fail -eq 0 ] && echo CLEAN || echo FINDINGS)"
exit $fail
