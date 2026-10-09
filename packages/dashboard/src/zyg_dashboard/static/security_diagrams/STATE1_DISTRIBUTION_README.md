<!--
SPDX-FileCopyrightText: 2026 Zygomatic

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# State 1 – Distribution Chart safekeeping

**Files:**
- `workflow_distribution_state1.svg` – SVG snapshot
- Related: `static/js/dashboard_tabs.js`, `step_to_agents.json`, `agent_configurations.json`, `orchestration_permissions.json`, `crewai_web_gui.py`

Snapshot of the Distribution Chart with correct agent assignments, orchestration hierarchy, and workflow box dialog fixes.

## What State 1 Includes

- **SVG:** Current layout with correct box positions and label matching
- **JS (dashboard_tabs.js):**
  - `labelsMatch()` for two-line labels (e.g. "Mandarin"+"Marketing" → "Mandarin Marketing")
  - AbortController + request-id logic so rapid opening of workflow box dialogs no longer causes stale/empty agent data
- **Agent assignments (step_to_agents.json):** All workflow boxes mapped per Distribution documents; Campaign Builder → Campaign-Builder-Agent, Conversion Optimizer → Conversion-Optimizer-Agent, Audience Targeting → Audience-Targeting-Agent, etc.
- **Orchestration hierarchy (distribution_orchestrated_by):**
  - Stage 1 & 2 → Content Overseer
  - Stage 3 & 4 → Affiliate Overseer
  - Stage 5, 6, 7 & 8 → Support Overseer
  - Content/Affiliate/Support Overseers → Media Overseer
  - Media Overseer → Zero (placeholder)
- **Orchestration permissions:** Distribution overseers in `orchestration_permissions.json`

## Restore Instructions

1. **SVG only:** Copy `workflow_distribution_state1.svg` over `workflow_distribution.svg`
2. **Full restore:** Ensure `step_to_agents.json` has `distribution_orchestrated_by` and correct agent mappings; `crewai_web_gui.py` uses distribution_orchestrated_by for workflow_distribution chart; `dashboard_tabs.js` has labelsMatch and AbortController logic.

The live diagram is `workflow_distribution.svg`.
