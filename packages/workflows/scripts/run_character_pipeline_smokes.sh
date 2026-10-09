#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Run all character-pipeline smoke checks (no full LoRA unless ZYG_SMOKE_SDXL_LORA=1).
set -euo pipefail
CREWS="$(cd "$(dirname "$0")/.." && pwd)"
cd "$CREWS"
echo "=== verify_char_kanban ==="
python3 scripts/verify_char_kanban.py
echo "=== test_sdxl_char_pipeline_smoke ==="
python3 scripts/test_sdxl_char_pipeline_smoke.py
if [[ "${ZYG_RUN_FAST_CHAR_SMOKE:-1}" == "1" ]]; then
  echo "=== test_char_gen_smoke_fast ==="
  python3 scripts/test_char_gen_smoke_fast.py
fi
if [[ "${ZYG_SMOKE_SDXL_LORA:-}" == "1" ]]; then
  echo "=== GPU mini SDXL LoRA (included in test_sdxl_char_pipeline_smoke) ==="
fi
echo "=== ALL CHARACTER PIPELINE SMOKES PASSED ==="
