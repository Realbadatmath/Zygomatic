#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Multi-angle contact sheet pipeline — fast wiring smokes (mock via API body, not env).
set -euo pipefail
CREWS="$(cd "$(dirname "$0")/.." && pwd)"
cd "$CREWS"
export PYTHONPATH="${CREWS}:${PYTHONPATH:-}"
echo "=== verify_contact_sheet_kanban ==="
python3 scripts/verify_contact_sheet_kanban.py
echo "=== done ==="
