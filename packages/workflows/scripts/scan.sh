#!/usr/bin/env bash
# scripts/scan.sh — the publishability gate. Exit 0 means every scanner is clean.
# Same steps as .github/workflows/ci.yml, runnable offline with the tools venv.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Tools: ZYG_TOOLS/venv/bin and ZYG_TOOLS/gitleaks when ZYG_TOOLS is set (a tools directory
# outside the checkout), otherwise the current environment (`uv run bash scripts/scan.sh`
# after `uv sync` at the monorepo root). ZYG_SCAN_SKIP_GITLEAKS=1 leaves gitleaks to the caller.
# A git hook, cron or CI runs this with a bare PATH, so the last fallback is the monorepo
# root venv that `uv sync` builds.
if [ -n "${ZYG_TOOLS:-}" ]; then V="$ZYG_TOOLS/venv/bin"; GL="$ZYG_TOOLS/gitleaks"
else V="$(dirname "$(command -v python || echo "$ROOT/../../.venv/bin/python")")"
     GL="$(command -v gitleaks || echo "$ROOT/../../.venv/bin/gitleaks")"; fi
cd "$ROOT"
fail=0
step() { printf '\n== %s\n' "$1"; }
step "ruff check";            "$V/ruff" check . || fail=1
step "ruff format --check";   "$V/ruff" format --check . || fail=1
step "bandit -ll";            "$V/bandit" -q -c pyproject.toml -r src -ll || fail=1
if [ -z "${ZYG_SCAN_SKIP_GITLEAKS:-}" ]; then
step "gitleaks (tree)";       "$GL" detect --no-git --source . --exit-code 1 --no-banner --redact || fail=1
if [ -d .git ] && git rev-parse HEAD >/dev/null 2>&1; then
  step "gitleaks (history)";  "$GL" detect --source . --exit-code 1 --no-banner --redact || fail=1
fi
fi
step "reuse lint";            "$V/reuse" lint -q || { "$V/reuse" lint | tail -5; fail=1; }
step "import layering";       "$V/lint-imports" --config .importlinter || fail=1
step "compileall";            "$V/python" -m compileall -q src || fail=1
step "pytest --collect-only"; "$V/python" -m pytest --collect-only -q >/tmp/scan_pytest_err.txt 2>&1 || { grep -E "ERROR|Error|error" /tmp/scan_pytest_err.txt | head -20; fail=1; }
step "personal data";         if grep -rnE --include='*.py' --include='*.js' --include='*.html' --include='*.json' --include='*.md' --include='*.sh' --include='*.bat' -e '192\.168\.[0-9]+\.[0-9]+' -e '[A-Za-z0-9._%+-]+@(msn|gmail|hotmail|outlook)\.com' -e 'Users[\\/]+Realbadatmath' src deploy site tests scripts 2>/dev/null | grep -v 'docs/' | head -20 | grep .; then fail=1; else echo "clean"; fi
# This scanner is excluded from its own search: it must spell the pattern out.
step "machine-specific paths"; n=$(grep -rlE --include='*.py' --include='*.js' --include='*.html' --include='*.json' --include='*.sh' --include='*.bat' '/home/zygomatic' src deploy site tests scripts tests_arch_ext capability_tests tests_vst 2>/dev/null | grep -vE 'docs/|scripts/scan\.sh$' | wc -l)
if [ "$n" -eq 0 ]; then echo "clean"; else grep -rlE --include='*.py' --include='*.js' --include='*.html' --include='*.json' --include='*.sh' --include='*.bat' '/home/zygomatic' src deploy site tests scripts tests_arch_ext capability_tests tests_vst 2>/dev/null | grep -vE 'docs/|scripts/scan\.sh$'; echo "$n files carry machine-specific home literals"; fail=1; fi
printf '\n== RESULT: %s\n' "$([ $fail -eq 0 ] && echo CLEAN || echo FINDINGS)"
exit $fail
