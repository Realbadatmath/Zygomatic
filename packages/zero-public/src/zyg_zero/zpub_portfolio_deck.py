#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Portfolio deck — the curated slideshow shown by /portfolio-slideshow.
=====================================================================

The screenshot folder (ZPUB_PORTFOLIO_SLIDES, 104 frames captured 2026-10-02)
is the raw material; this module is the EDIT.  It turns the folder into a
presentation with the structure the most-starred GitHub projects share
(researched 2026-10-04, 20 flagship repos — see
docs/portfolio_presentation_patterns.md):

  * one hero with a WHAT-first tagline of 9-16 words and a row of facts
  * chapters in the order a reader needs them (what it is → see it → how it
    works → what it costs → what runs underneath → who built it)
  * every slide = one picture + a one-line WHAT + at most three bullets
  * a quick-start-style "how to read this" and an honest "limits" slide
  * closing slides that say what was learned and what the author offers

Every claim below is lifted from Levi's written portfolio (``Welcome
portfolio.pdf``) or from measured notes in the repo; nothing is invented.

The deck is DATA.  ``build_deck()`` resolves it against the folder on disk
and silently drops any slide whose file is missing, so a renamed screenshot
can never 404 inside the player.  Durations are not stored here — the player
derives them from caption length (reading speed) so the movie stays paced
when captions are edited.
"""

from __future__ import annotations

import os
import re
import time

from zyg_zero import settings

SLIDES_DIR = os.environ.get('ZPUB_PORTFOLIO_SLIDES') or str(settings.ZYG_PORTFOLIO_DIR / 'slideshow')

# Bare filenames only — same rule as the slide route (no separators, no
# leading dot), so a deck entry can never address a file outside the folder.
SLIDE_NAME_RE = re.compile(r'^[0-9A-Za-z][0-9A-Za-z._-]*\.(?:png|jpe?g|webp)$', re.IGNORECASE)

# ── Hero ──────────────────────────────────────────────────────────────────────
HERO = {
    'name': 'Levi Harley',
    # 14 words, WHAT-first — the length band every flagship README sits in.
    'tagline': 'A self-producing 2D and 3D video stack, built and tested on one workstation.',
    'sub': 'Portfolio 2026 · the studios, the workflows, the numbers',
    # The "badge row": facts, not decoration. Each one is in the written portfolio.
    'facts': [
        {'k': '14', 'v': 'studios, one per specialist'},
        {'k': 'Mar 2026', 'v': 'workstation built'},
        {'k': '€ 0.015', 'v': 'per documentary episode'},
        {'k': '0', 'v': 'human steps in the documentary workflow'},
    ],
}

# ── Chapters ──────────────────────────────────────────────────────────────────
# Each slide: file (in SLIDES_DIR), title, what (one line), points (≤3).
# A slide may omit 'file' to be a text card rendered on the chapter colour.
CHAPTERS = [
    {
        'id': 'anatomy',
        'title': 'What a video is made of',
        'lead': 'Imagery, scenery, architecture, music, sound effects, voices, characters, 3D elements, storytelling, screenplay and an emotional arc.',
        'slides': [
            {
                'file': '063_inspection_home.png',
                'title': 'One studio per specialist',
                'what': 'Normally a team of professionals covers these areas. Here each area has its own studio.',
                'points': [
                    'Every option, and how it is applied to the subject, is tested, trained and verified.',
                    'The home screen lists the fourteen studios the rest of this deck walks through.',
                ],
            },
            {
                'file': '064_inspection_library.png',
                'title': 'The Library',
                'what': 'Everything a studio produces lands in one library: characters, creatures, videos, melodies, meshes, voices.',
                'points': [
                    'Anything here can be pulled into a workflow or a new studio session.',
                    'Hover previews play the video and audio entries in place.',
                ],
            },
        ],
    },
    {
        'id': 'studios',
        'title': 'Fourteen studios',
        'lead': 'Each studio replicates one specialist’s craft, outfitted with its own options, quality gates and benches.',
        'slides': [
            {
                'file': '065_inspection_video_studio.png',
                'title': 'Video Studio',
                'what': 'Turns a plate or a prompt into a clip, with the model, motion and camera options exposed.',
                'points': [
                    'Backends are swapped per shot; the studio keeps the same option bars.',
                    'Finished clips are reviewed here before a workflow may use them.',
                ],
            },
            {
                'file': '067_inspection_picture_studio.png',
                'title': 'Picture Studio',
                'what': 'Still images across model families, styles and LoRAs, with contact sheets for comparison.',
                'points': [
                    'Every render is logged with its prompt, seed and model so results can be reproduced.',
                ],
            },
            {
                'file': '068_inspection_character_studio.png',
                'title': 'Character Studio',
                'what': 'Builds a character once, then keeps that identity across angles, scenes and styles.',
                'points': [
                    'Photoreal skin, eyes and strand hair are separate layers that can be switched on and measured.',
                    'A 3D compare view checks the drawn character against its mesh.',
                ],
            },
            {
                'file': '069_inspection_creature_studio.png',
                'title': 'Creature Studio',
                'what': 'Designs creatures from a locked body plan and renders multi-angle sheets.',
                'points': [
                    'The body plan is fixed first so a creature cannot drift between shots.',
                ],
            },
            {
                'file': '070_inspection_movement_studio.png',
                'title': 'Movement Studio',
                'what': 'Skeleton, anatomy layers and captured motion, retargeted onto the stack’s own bodies.',
                'points': [
                    'Real anatomy is layered on the skeleton so a pose moves the chest wall, not just the bones.',
                ],
            },
            {
                'file': '066_inspection_mesh_studio.png',
                'title': 'Mesh Studio',
                'what': '3D meshes for characters, props and bodies, with rigging benches and a Blender bridge.',
                'points': [
                    'Geometry made here is the plan for solving identity drift and morphing at the source.',
                ],
            },
            {
                'file': '071_inspection_voice_studio.png',
                'title': 'Voice Studio',
                'what': 'Cloned and designed voices, benches of candidate takes, and direction per line.',
                'points': [
                    'Each character has a frozen voice seed; benches compare takes before one is picked.',
                ],
            },
            {
                'file': '072_inspection_music_studio.png',
                'title': 'Music Studio',
                'what': 'Full songs with a sung voice leg, measured for intelligibility before they ship.',
                'points': [
                    'A denoise ladder per song lifted intelligibility from 49 % to 94 % in the children’s series.',
                ],
            },
            {
                'file': '075_inspection_melody_studio.png',
                'title': 'Melody Studio',
                'what': 'Melodies and arrangements, grown as style trees so a register can be explored and kept.',
                'points': [],
            },
            {
                'file': '073_inspection_sfx_studio.png',
                'title': 'SFX Studio',
                'what': 'A sound-effects library with slates, a merger, and instruments catalogued by licence.',
                'points': [
                    'Licences are tracked per file; the first AI-training-forbidding licence was found here.',
                ],
            },
            {
                'file': '074_inspection_vfx_studio.png',
                'title': 'VFX Studio',
                'what': 'Visual effects as reusable elements: ash, dust, water, fire, volume and transitions.',
                'points': [
                    'The ash-to-character effect from the film lives here as a taught, repeatable skill.',
                ],
            },
            {
                'file': '076_inspection_architecture_studio.png',
                'title': 'Architecture Studio',
                'what': 'Buildings, floor plans and landscapes from a dock of about 190 tools and written design rules.',
                'points': [
                    'Quality gates check the drawing against the rules before a scene is handed to Blender.',
                ],
            },
            {
                'file': '105_object_studio_immersive.png',
                'title': 'Object Studio',
                'what': 'A spoken name becomes a 3D object: an agent writes the build plan, headless Blender builds the GLB.',
                'points': [
                    'Shown here as its immersive room: the generator bench, the hologram and the display walls.',
                    'Finished objects land in the wall cabinets and are recalled, shown and modified by voice.',
                ],
            },
            {
                'file': '077_inspection_bakeoff.png',
                'title': 'Bakeoff',
                'what': 'The same brief through several models or tools, side by side, so the pick is measured.',
                'points': [],
            },
        ],
    },
    {
        'id': 'skill',
        'title': 'The taught skill, and geometry first',
        'lead': 'The film was a test of one new effect. The fix for most of its defects is geometry.',
        'slides': [
            {
                'file': '085_library_vfx.png',
                'title': 'Characters that turn to ash',
                'what': 'Every character, object and letter is treated as solid mass made of millions of particles.',
                'points': [
                    'Each particle is controlled one by one: dissolve, blow away, re-solidify as someone else.',
                    'About 8 rounds of fine-tuning, roughly 10 hours of GPU time, until it behaved.',
                    'Now it is a skill that applies to anything the stack generates.',
                ],
            },
            {
                'file': '087_library_mesh.png',
                'title': 'Geometry first',
                'what': 'Models, architecture, scenery and effects are being built in Blender, then trained into the workflows.',
                'points': [
                    'Geometry gives boundaries: no identity drift across scenes or while moving.',
                    'No morphing objects or scenery. Every hand has four fingers and a thumb.',
                ],
            },
        ],
    },
    {
        'id': 'assistants',
        'title': 'From hundreds of agents to scripts',
        'lead': 'Each step only has to be done correctly once. Then the agent is replaced by a script and a quality gate.',
        'slides': [
            {
                'file': '054_kanban_card_dialog_overview.png',
                'title': 'A step, opened',
                'what': 'The first schematics had hundreds of agents. Once a step was proven, it became a script with a gate.',
                'points': [
                    'Fewer tokens, and no dependency on AI guidance once the stack is built and tested.',
                ],
            },
            {
                'file': '058_kanban_card_dialog_llms.png',
                'title': 'Where AI still helps',
                'what': 'Script writing for content, building and testing the stack, and VLM judges for what gates cannot see.',
                'points': [
                    'Agents are spawned through a Claude Max subscription: Fable, Opus and Sonnet.',
                ],
            },
        ],
    },
    {
        'id': 'session_tree',
        'title': 'Session tree',
        'lead': 'Fable plans and splits the build; Opus and Sonnet executors take one task each.',
        'slides': [
            {
                'file': '092_sessiontree_active.png',
                'title': 'One task per session',
                'what': 'Fable thinks of a build, splits it into tasks; an agent is spawned per task, up to thirty at once.',
                'points': [
                    'Fable reviews every finished and failed task and plans a new tree if needed.',
                ],
            },
            {
                'file': '093_sessiontree_planned.png',
                'title': 'Why the tree exists',
                'what': 'Using Fable to build directly made token usage skyrocket. Using it only as the brain brought it down.',
                'points': [
                    'Every complex build and every new 3D element has gone through the tree since.',
                ],
            },
            {
                'file': '095_sessiontree_metrics.png',
                'title': 'Tree metrics',
                'what': 'Tokens, minutes and verdicts per task, so the cost of a build is known before the next one.',
                'points': [],
            },
        ],
    },
    {
        'id': 'workflows',
        'title': 'Workflows',
        'lead': 'A kanban board per workflow. A card activates when the step before it is done and has passed its gate.',
        'slides': [
            {
                'file': '028_kanban_documentary.png',
                'title': 'The documentary workflow',
                'what': 'Produces documentaries and uploads them to its channels, fully automated, without human interaction.',
                'points': [
                    'Tested multiple times, runs without fail.',
                    'Quality per episode is being raised and cost per episode lowered before a fixed schedule is switched on.',
                ],
            },
            {
                'file': '033_kanban_storyteller.png',
                'title': 'More boards',
                'what': 'Storyteller, video, character and creature creation, sports and finance series, each with its own board.',
                'points': [
                    'Some are finished, some are being upgraded, some are placeholders for what is still to build.',
                ],
            },
            {
                'file': '059_kanban_live_tail_log.png',
                'title': 'Live tail',
                'what': 'The same progress in depth: logs, telemetry and the agents spawned for a step, all tracked.',
                'points': [
                    'Every metric related to a workflow is logged here first.',
                ],
            },
        ],
    },
    {
        'id': 'approval',
        'title': 'Approval queue',
        'lead': 'Only workflows that work from A to Z appear here. Each one can be put on a production schedule.',
        'slides': [
            {
                'file': '008_dashboard_approval_queue.png',
                'title': 'Toggle, then schedule',
                'what': 'The documentary workflow is set to 6 episodes every 2 days, airing 3 per day at chosen times.',
                'points': [
                    'Restarts are limited so a broken workflow cannot loop.',
                ],
            },
        ],
    },
    {
        'id': 'nexus',
        'title': 'Content creation hub',
        'lead': 'All content is uploaded through the Creator Nexus, one channel at a time, with its own settings.',
        'slides': [
            {
                'file': '099_nexus_channels.png',
                'title': 'Channels',
                'what': 'Per channel: AdSense, personal information, connected platforms and upload rules.',
                'points': [
                    'The documentaries channel ran the first successful A-to-Z tests.',
                ],
            },
            {
                'file': '101_nexus_metrics.png',
                'title': 'A feedback loop',
                'what': 'Metrics per channel and per video flow back into which topics to make next and which to avoid.',
                'points': [],
            },
        ],
    },
    {
        'id': 'schedule',
        'title': 'CPU and GPU schedule',
        'lead': 'Calendars that go back five years and can be planned one year ahead.',
        'slides': [
            {
                'file': '002_dashboard_gpu_schedule.png',
                'title': 'The GPU calendar',
                'what': 'When a workflow is switched on, its time estimate appears on the calendar and adjusts itself as runs finish.',
                'points': [
                    'Orange: agent sessions used to build and test. Blue: workflows that produce content.',
                    'Click a slot to open the traces and logs of that job.',
                ],
            },
            {
                'file': '003_dashboard_cpu_schedule.png',
                'title': 'Reading the calendar',
                'what': 'As more workflows finish, the prediction of production capacity improves.',
                'points': [
                    'Workflows that underperform stick out, so they are improved or discarded.',
                ],
            },
        ],
    },
    {
        'id': 'metrics',
        'title': 'The metrics hub',
        'lead': 'Everything the workflows and the app do is measured, so a feedback loop can heal and improve the stack.',
        'slides': [
            {
                'file': '019_metrics_llm.png',
                'title': 'Cost per episode',
                'what': 'A documentary episode cost € 0.17 on Haiku and Sonnet API calls. Through the subscription, on Opus, it costs € 0.015.',
                'points': [
                    'About 30 times cheaper on the subscription; still 11 times cheaper after moving every call to Opus.',
                    'About 90 episodes a month comes to € 1.35 in Opus calls.',
                ],
            },
            {
                'file': '023_metrics_quota.png',
                'title': 'Quota',
                'what': 'What the subscription saves against API pricing, across workflows, session trees and coding sessions.',
                'points': [],
            },
            {
                'file': '021_metrics_quality.png',
                'title': 'Quality',
                'what': 'Every quality-gate result with its run verdict, so a problem can be pinpointed and solved.',
                'points': [],
            },
            {
                'file': '027_metrics_capabilities.png',
                'title': 'Capabilities',
                'what': 'Every skill used in the workflows, with a default test per category to benchmark each model and tool.',
                'points': [
                    'The benchmark decides which model and tool handles which scenario.',
                ],
            },
        ],
    },
    {
        'id': 'gates',
        'title': 'Gates, audit and limits',
        'lead': 'Traces from every action are stored. Every tool and model has limits, and finding them is the job.',
        'slides': [
            {
                'file': '010_dashboard_integrity_gate.png',
                'title': 'Integrity gate',
                'what': 'Each render is checked against its receipt before it may continue down the board.',
                'points': [],
            },
            {
                'file': '009_dashboard_audit.png',
                'title': 'Audit trail',
                'what': 'Hash-chained logs of what ran, when, and with what verdict.',
                'points': [],
            },
            {
                'file': '014_dashboard_benchmark.png',
                'title': 'Known limits',
                'what': 'No local vision model reliably sees an extra finger. Identity spread on video is never continuity.',
                'points': [
                    'Those limits are written down and gated around, not hidden.',
                ],
            },
        ],
    },
    {
        'id': 'backend',
        'title': 'What runs underneath',
        'lead': 'Flask and Jinja2 for the production app, FastAPI for the control plane, Postgres 16 and Redis for state.',
        'slides': [
            {
                'file': '017_metrics_system.png',
                'title': 'The stack',
                'what': 'Waitress and nginx in front, systemd services, a Cloudflare tunnel for the public gateway.',
                'points': [
                    'ffmpeg in about 150 modules, headless Blender in about 180, Playwright for the browser work.',
                    'Telemetry from psutil and NVML drives protection levels 0 to 4.',
                ],
            },
            {
                'file': '103_public_zero_gate.png',
                'title': 'Public surfaces',
                'what': 'The invite-only gateway you are reading this on, and the studio front door behind TLS.',
                'points': [],
            },
        ],
    },
    {
        'id': 'closing',
        'title': 'What was learned, and what I offer',
        'lead': 'AI needs guidance and rules. It is smart, and in many ways still a toddler.',
        'slides': [
            {
                'file': '001_dashboard_agent_overview.png',
                'title': 'A few of the things I have learned',
                'what': 'Every step AI performs has to be mapped, tested and in some cases trained.',
                'points': [
                    'AI-generated content is numbers; geometry and metrics are sacred.',
                    'The more failures you can emulate, the more you can prevent.',
                    'To build a tool, you have to intimately understand the thing you build it for.',
                ],
            },
            {
                'file': '016_metrics_overview.png',
                'title': 'How I can contribute',
                'what': 'Carpenter and epoxy-flooring background: a bridge between building companies and AI-driven solutions.',
                'points': [
                    'Able to design, build and test multi-layered systems with the return on every cent and hour in mind.',
                    'Used to talking with customers and turning their ideas into drawings and schematics.',
                    'Incredibly persistent.',
                ],
            },
            {
                'title': 'Thank you',
                'what': 'My name is Levi Harley, and in all humbleness, I thank you for your time.',
                'points': [],
            },
        ],
    },
]

_CACHE = {'at': 0.0, 'deck': None, 'dir': None}
_CACHE_TTL = 30.0


def _available_files() -> list[str]:
    try:
        return sorted(n for n in os.listdir(SLIDES_DIR) if SLIDE_NAME_RE.match(n))
    except OSError:
        return []


def build_deck(slides_dir: str | None = None) -> dict:
    """Resolve the deck against the folder on disk.

    Returns {hero, chapters, extra, count} where every slide with a 'file'
    exists; slides whose file is missing are dropped (text cards stay) and
    chapters left with no slides are dropped too.  ``extra`` lists frames in
    the folder the edit does not use, so the "all frames" index can show them.
    """
    folder = slides_dir or SLIDES_DIR
    try:
        names = sorted(n for n in os.listdir(folder) if SLIDE_NAME_RE.match(n))
    except OSError:
        names = []
    have = set(names)
    used: set[str] = set()
    chapters = []
    n = 0
    for ch in CHAPTERS:
        slides = []
        for s in ch['slides']:
            f = s.get('file')
            if f and f not in have:
                continue
            if f:
                used.add(f)
            slides.append(
                {
                    'file': f,
                    'title': s['title'],
                    'what': s.get('what', ''),
                    'points': list(s.get('points') or [])[:3],
                }
            )
        if not slides:
            continue
        n += len(slides)
        chapters.append(
            {
                'id': ch['id'],
                'title': ch['title'],
                'lead': ch.get('lead', ''),
                'slides': slides,
            }
        )
    extra = []
    for name in names:
        if name in used:
            continue
        stem = os.path.splitext(name)[0]
        m = re.match(r'^(\d+)[_-](.+)$', stem)
        extra.append(
            {
                'file': name,
                'title': (m.group(2) if m else stem).replace('_', ' ').strip(),
            }
        )
    return {'hero': HERO, 'chapters': chapters, 'extra': extra, 'count': n}


def deck(slides_dir: str | None = None) -> dict:
    """Cached build_deck — a page render never costs a directory listing."""
    folder = slides_dir or SLIDES_DIR
    now = time.time()
    if _CACHE['deck'] is not None and _CACHE['dir'] == folder and now - _CACHE['at'] < _CACHE_TTL:
        return _CACHE['deck']
    d = build_deck(folder)
    _CACHE.update(at=now, deck=d, dir=folder)
    return d


if __name__ == '__main__':
    d = build_deck()
    print(f'{d["count"]} slides in {len(d["chapters"])} chapters, {len(d["extra"])} extra frames')
    for ch in d['chapters']:
        print(f'  {ch["title"]}: {len(ch["slides"])}')
    missing = [
        s['file']
        for ch in CHAPTERS
        for s in ch['slides']
        if s.get('file') and not os.path.isfile(os.path.join(SLIDES_DIR, s['file']))
    ]
    if missing:
        print('MISSING:', missing)
