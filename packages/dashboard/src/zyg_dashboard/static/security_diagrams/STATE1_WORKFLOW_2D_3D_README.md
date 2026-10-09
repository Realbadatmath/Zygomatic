<!--
SPDX-FileCopyrightText: 2026 Zygomatic

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# State 1 – 2D & 3D Workflow Charts safekeeping

**Files:**
- `workflow_2d_state1.svg` – 2D workflow SVG snapshot
- `workflow_3d_state1.svg` – 3D workflow SVG snapshot
- `workflow_3d_state2.svg` – 3D workflow SVG snapshot (2025-03-10)
- `workflow_3d_state3.svg` – 3D workflow SVG snapshot (current)

Two separate correlating backup files preserving the current structure of the 2D and 3D workflow diagrams.

## What State 1 Includes

- **workflow_2d_state1.svg:** Snapshot of 2D workflow with:
  - Connector arrows and lines removed (per previous edits)
  - Stage 5 Distribution box labeled "Distribution"
  - Production Overseer and Media Overseer boxes
  - All stage agent boxes and layout

- **workflow_3d_state1.svg:** Snapshot of 3D workflow with:
  - Matching structure to 2D (connectors removed, Distribution label, overseers)
  - Same logical layout in 3D projection

- **workflow_3d_state2.svg:** Snapshot of 3D workflow (2025-03-10) with:
  - Brown connectors changed to sky blue (cls-4, cls-9)
  - All tab lists and structure intact
  - Current live state preserved

- **workflow_3d_state3.svg:** Snapshot of 3D workflow (current) with:
  - Episode→Quality Control arrow added
  - Single Scheduling Agent (unified across charts)
  - All previous state2 changes

## Restore Instructions

To revert to this state:

1. **2D only:** Copy `workflow_2d_state1.svg` over `workflow_2d.svg`
2. **3D only:** Copy `workflow_3d_state1.svg` over `workflow_3d.svg`
3. **3D state2:** Copy `workflow_3d_state2.svg` over `workflow_3d.svg`
4. **3D state3:** Copy `workflow_3d_state3.svg` over `workflow_3d.svg`
5. **Both:** Copy both state1 files over their respective live diagrams

The live diagrams used by the dashboard are `workflow_2d.svg` and `workflow_3d.svg`.
