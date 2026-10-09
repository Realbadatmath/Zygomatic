#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# The suite that must be green on any machine: no CUDA device, no ComfyUI, no Ollama, no
# Blender, no Postgres, no asset tree. That is what `-m "not gpu and not service"` buys —
# the markers are declared in pyproject.toml and are the contract, so a test that needs
# hardware or a daemon has to say so out loud instead of failing on a laptop.
#
#   scripts/run_tests.sh                       the portable suite
#   scripts/run_tests.sh tests/test_foo.py     the same filters, one file
#   scripts/run_tests.sh --all                 everything, gpu and service included
#   scripts/run_tests.sh --gpu                 only the CUDA tests
#   scripts/run_tests.sh --service             only the tests that want a live daemon
#   scripts/run_tests.sh --collect             collect only, the shape of the suite
#
# tests_arch_ext/, tests_vst/ and capability_tests/ are NOT pytest — they are standalone
# harnesses that act on import and need Blender or a browser. pyproject's testpaths and
# norecursedirs keep pytest out of them; see tests_arch_ext/README.md to run that one.
set -euo pipefail
cd "$(dirname "$0")/.."

# A repo .venv wins when it exists, because that is someone working on this checkout alone.
# The shared tools venv has all four repositories installed editable and is what the gate uses;
# $ZYG_TOOLS_PYTHON names it when this checkout is not a sibling of it.
TOOLS_PY="${ZYG_TOOLS_PYTHON:-$HOME/repos/.tools/venv/bin/python}"
PY=''
for cand in .venv/bin/python ../.tools/venv/bin/python "$TOOLS_PY"; do
  if [ -x "$cand" ]; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
  echo "no interpreter: make one here — python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
  exit 2
fi

MARK='not gpu and not service'
COLLECT=''
case "${1:-}" in
  --all) MARK=''; shift ;;
  --gpu) MARK='gpu'; shift ;;
  --service) MARK='service'; shift ;;
  --collect) COLLECT='--collect-only'; shift ;;
  -h | --help) sed -n '7,21p' "$0"; exit 0 ;;
esac

ARGS=(-m pytest -q -p no:cacheprovider --timeout=120)
[ -n "$MARK" ] && ARGS+=(-m "$MARK")
[ -n "$COLLECT" ] && ARGS+=("$COLLECT")

exec "$PY" "${ARGS[@]}" "$@"
