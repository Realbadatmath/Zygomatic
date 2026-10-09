<!-- SPDX-FileCopyrightText: 2026 Zygomatic -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Demo

What the studio looks like when it runs, and what comes out of it. Every picture and clip on
this page was captured from, or rendered by, the installation described in the
[README](../README.md). Nothing here is a mock-up.

The clips play inline as silent previews. Click one to open the full-resolution file with sound.

## Clips

### The intro: sand letters and Ubi

[![Steel sand grains form the words Zygomatic Ai, then Ubi pops in and hops on each word](media/intro-ubi-sand-letters.gif)](media/intro-ubi-sand-letters.mp4)

Eight million steel grains fly in as five streams and fuse into solid letters (Blender
Geometry Nodes, deterministic, no simulation). Ubi, the studio's creature, then pops in and
hops on each word until it sinks into the floor (LTX video, guided by composited plates).
25 s, 720p.

### Solidify and de-solidify: Abel on deck

[![Ash blows in and solidifies into Abel at a ship's rail, then he burns back to ash and blows away](media/abel-solidify-desolidify.gif)](media/abel-solidify-desolidify.mp4)

From the intro of *The Second Ledger*. A cloud of ash gathers into the painted figure, holds,
then burns back to ash and leaves on the wind. Every grain is born with the colour of the
pixel it replaces, which is why the crossfade is invisible. 8 s, 1080p, cut from the full
intro.

### VFX Studio: a volume element with its alpha

[![The VFX Studio tab playing a dust shockwave volume beside its alpha element](media/vfx-studio-dust-shockwave.gif)](media/vfx-studio-dust-shockwave.mp4)

The VFX Studio tab with a dust shockwave volume selected from the library: the lit preview on
the left, the keyed element with alpha on the right, the tool dock underneath. Screen
recording, 10 s.

## The operator GUI

### Library

![The Library home: Characters, Creatures, Videos, Melodies, Movement, VFX, Architecture, Mesh, SFX, Voices](media/library-home.webp)

Everything the studios produce lands in one library, by kind.

### A creature, as the studio knows it

![Sheet cells and operator anchor locks for the creature Ubi](media/library-creature-ubi.webp)

Ubi's sheet cells (what the model was taught) and the operator's anchor locks.

### A character, from every angle

![Angle sheet cells for the character Cornelis van Haren](media/library-character-cornelis.webp)

The angle sheet for Cornelis van Haren. Sheets like this are what keep a character the same
person from shot to shot.

### Workflows: 3 documentary runs running simultaneously for testing purposes

![The Workflows board with three documentary runs stacked on every stage: research and scripting done, narration running, the rest queued](media/workflows-documentary-pipeline.webp)

Three documentary runs (runs 2, 3 and 4) moving through the pipeline at the same time, stage
by stage, with GPU, CPU, VRAM and RAM gauges and the live tail.

### Architecture Studio

![A 17th-century pinas ship model in the Architecture Studio viewport](media/architecture-studio-witsen-pinas.webp)

The Architecture Studio viewport and tool dock, here holding the Witsen pinas reference model.

### Creator Nexus

![Creator Nexus: the channel list and one channel's published videos](media/creator-nexus-channels.webp)

The channel board: one channel's published videos with their platform switches.

### Metrics

![The Metrics tab on its Quota page: weekly and session usage, cost per model, and production against infrastructure](media/metrics-quota.webp)

Metrics Quota tab and many more metrics in the other subtabs.

## The studio at a glance

### What runs underneath

![The backend: web layer, data and state, process and hardware, media and I/O](media/slide-backend.webp)

The Backend

### Main tabs, studios and the library

![The dashboard tabs, the twelve studios and the ten library categories](media/slide-tabs-studios-library.webp)

The sixteen dashboard tabs, the twelve studios and the ten kinds of thing the library holds.

### Workflows

![Every workflow on the board; the ones that run unattended are marked Fully Automated, the production workflows still being built are marked Under Development](media/slide-workflows.webp)

Every workflow on the board. The ones marked **Fully Automated** run on their own schedule,
from topic to finished output, with no operator step in between. (Uploading to pre-selected
platforms included)

The production workflows marked **Under Development** are still being improved. Each workflow
step is proven and works. However, the steps need to be upgraded, refined and tested to get the
desired results before a fully automated claim can be made.
