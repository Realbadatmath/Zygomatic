# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kanban/studios.py — the lazily imported studio backends: agents, VFX, architecture, character, voices, video, stills.

Split verbatim out of ``kanban_server.py`` (lines 2805-2960) on 2026-10-06; the handler
re-imports every name from here, so ``zyg_dashboard.kanban_server.<name>`` still resolves.
"""

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# ── Agent sessions (2026-08-30) ─────────────────────────────────────────────
# Which Claude Code sessions are on this box's CPU/GPU right now. Lazily
# imported and fail-soft in exactly the same shape as the VFX analyzer below:
# the skull badge going dark must never be able to take the board with it.
_AGENT_MOD = {'m': None, 'err': ''}


def _agents():
    if _AGENT_MOD['m'] is None and not _AGENT_MOD['err']:
        try:
            from zyg_dashboard import agent_activity

            agent_activity.start()
            _AGENT_MOD['m'] = agent_activity
        except Exception as e:  # noqa: BLE001 — fatal to the skull badge only
            _AGENT_MOD['err'] = f'{type(e).__name__}: {e}'
            _zyg_log.info(f'[KANBAN-SERVER] agent_activity unavailable — {_AGENT_MOD["err"]}')
    return _AGENT_MOD['m']


_VFX_MOD = {'m': None, 'err': ''}


def _vfx():
    if _VFX_MOD['m'] is None and not _VFX_MOD['err']:
        try:
            from zyg_workflows import vfx_analyzer

            _VFX_MOD['m'] = vfx_analyzer
        except Exception as e:  # noqa: BLE001 — fatal to the VFX tab only
            _VFX_MOD['err'] = f'{type(e).__name__}: {e}'
            _zyg_log.info(f'[KANBAN-SERVER] vfx_analyzer unavailable — {_VFX_MOD["err"]}')
    return _VFX_MOD['m']


# ── Architecture Studio (2026-09-01) ─────────────────────────────────────────
# The tab's drawing engine is three.js in the browser (WebGL2 on the local GPU);
# this module is only its catalogue and its project store. Lazy + defensive like
# every other tab module: a broken import must cost the Architecture tab and
# nothing else.
_ARCH_MOD = {'m': None, 'err': ''}


def _arch():
    if _ARCH_MOD['m'] is None and not _ARCH_MOD['err']:
        try:
            from zyg_workflows import architecture_studio

            _ARCH_MOD['m'] = architecture_studio
        except Exception as e:  # noqa: BLE001 — fatal to the Architecture tab only
            _ARCH_MOD['err'] = f'{type(e).__name__}: {e}'
            _zyg_log.info(f'[KANBAN-SERVER] architecture_studio unavailable — {_ARCH_MOD["err"]}')
    return _ARCH_MOD['m']


# ── Character Studio (2026-09-02): the character's bible, read-write ─────────
# The studio's rail edits fields that ALREADY EXIST in character_bible.json.
# character_studio owns the whitelist, the type coercion and the mirrored
# presentation keys; this server only routes and applies the same fail-closed
# medusa scope guard /inspect/api/char uses. Imported lazily and defensively
# for the reason every other studio is: it pulls in character_bible_service,
# and a broken import there must cost the Character Studio tab, not the board.
_CSTUDIO_MOD = {'m': None, 'err': ''}


def _cstudio():
    if _CSTUDIO_MOD['m'] is None and not _CSTUDIO_MOD['err']:
        try:
            from zyg_workflows import character_studio

            _CSTUDIO_MOD['m'] = character_studio
        except Exception as e:  # noqa: BLE001 — fatal to the Character Studio tab only
            _CSTUDIO_MOD['err'] = f'{type(e).__name__}: {e}'
            _zyg_log.info(f'[KANBAN-SERVER] character_studio unavailable — {_CSTUDIO_MOD["err"]}')
    return _CSTUDIO_MOD['m']


# ── Voices tab (2026-08-11): the voice studio, read-write ────────────────────
# voice_studio owns the knobs, the preset store and the render jobs; this server
# only routes. Imported LAZILY and defensively: it shells out to the TTS venvs and
# to Praat, and a broken engine install must degrade the Voices tab, never take
# the Kanban board and the Inspections SPA down with it.
_VOICE_MOD = {'m': None, 'err': ''}


def _voice_studio():
    if _VOICE_MOD['m'] is None and not _VOICE_MOD['err']:
        try:
            from zyg_workflows import voice_studio

            _VOICE_MOD['m'] = voice_studio
            # Explicit, not on import: importing a module must not start a job
            # that holds the GPU for hours. The operator asked for the library to
            # BE rendered, though, so a server bounce mid-bake resumes it here.
            voice_studio.resume_bake_if_interrupted()
        except Exception as e:  # noqa: BLE001 — any import failure is fatal to the tab only
            _VOICE_MOD['err'] = f'{type(e).__name__}: {e}'
            _zyg_log.info(f'[KANBAN-SERVER] voice_studio unavailable — {_VOICE_MOD["err"]}')
    return _VOICE_MOD['m']


# Same lazy/defensive contract as _voice_studio(): video_studio shells out to
# ComfyUI for Wan2.2 I2V rendering, and a broken/absent ComfyUI install must
# degrade only the Video Studio tab, never the rest of the SPA.
_VIDEO_MOD = {'m': None, 'err': ''}


def _video_studio():
    if _VIDEO_MOD['m'] is None and not _VIDEO_MOD['err']:
        try:
            from zyg_workflows import video_studio

            _VIDEO_MOD['m'] = video_studio
        except Exception as e:  # noqa: BLE001 — any import failure is fatal to the tab only
            _VIDEO_MOD['err'] = f'{type(e).__name__}: {e}'
            _zyg_log.info(f'[KANBAN-SERVER] video_studio unavailable — {_VIDEO_MOD["err"]}')
    return _VIDEO_MOD['m']


# Guarded separately again: video_stills spawns a CHILD interpreter to make the
# intro frame, precisely so this process never imports comfy_generation_service
# (CLIP loads at import). Losing it must cost the Still button and nothing else.
_STILL_MOD = {'m': None, 'err': ''}


def _video_stills():
    if _STILL_MOD['m'] is None and not _STILL_MOD['err']:
        try:
            from zyg_workflows import video_stills

            _STILL_MOD['m'] = video_stills
        except Exception as e:  # noqa: BLE001 — any import failure is fatal to the button only
            _STILL_MOD['err'] = f'{type(e).__name__}: {e}'
            _zyg_log.info(f'[KANBAN-SERVER] video_stills unavailable — {_STILL_MOD["err"]}')
    return _STILL_MOD['m']


# Separately guarded from voice_studio on purpose: voice_assign reads character
# bibles, the board picker and the briefing settings, so its failure modes are
# nothing like the studio's. Losing it must cost the Assign panel and leave the
# knobs, the presets and the render loop working.
_ASSIGN_MOD = {'m': None, 'err': ''}


def _voice_assign():
    if _ASSIGN_MOD['m'] is None and not _ASSIGN_MOD['err']:
        try:
            from zyg_workflows import voice_assign

            _ASSIGN_MOD['m'] = voice_assign
        except Exception as e:  # noqa: BLE001
            _ASSIGN_MOD['err'] = f'{type(e).__name__}: {e}'
            _zyg_log.info(f'[KANBAN-SERVER] voice_assign unavailable — {_ASSIGN_MOD["err"]}')
    return _ASSIGN_MOD['m']
