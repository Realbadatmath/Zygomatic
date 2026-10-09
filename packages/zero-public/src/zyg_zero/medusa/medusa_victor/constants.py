# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""medusa_victor.constants — the fence switch, the Ollama endpoint, the BRAINS table and the tool-output limits.

Lines 99-198 of the original medusa_victor.py, moved verbatim
(2026-10-06 split). No logic changed.
"""

from __future__ import annotations

import os

from zyg_zero import paths as _zero_paths

HERE = str(_zero_paths.MEDUSA_DIR)
ROOT = os.path.realpath(HERE)  # Medusa's own folder; also the fence, when the fence is on

# The path fence, off by default since 2026-09-17 — see _safe_path for what that
# means and what it costs. `on`/`1`/`true` turn it back on.
FENCE = os.environ.get('ZYG_VICKY_FENCE', 'off').strip().lower() in ('on', '1', 'true', 'yes')

# ── Ollama ───────────────────────────────────────────────────────────────────
OLLAMA_URL = (os.environ.get('ZYG_VICTOR_OLLAMA') or 'http://127.0.0.1:11434').rstrip('/')

# ── brains ───────────────────────────────────────────────────────────────────
# This module used to serve one assistant, so the model was a constant. It now
# serves two, because on 2026-09-17 Vicky stopped being a metered `claude -p`
# subprocess and became a local model too. Everything below the model name is
# identical for both — same chat store, same tools, same fence, same rules file —
# so a persona here is nothing more than (name, model, context), and adding a
# third is a row in this table rather than a third module.
#
#   vicky   Dolphin-Mistral-24B-Venice-Edition Q8_0, built from
#           config/Vicky.Modelfile. DENSE 24B: every token reads all 25 GB of
#           weights, so it runs at roughly a third of Victor's tokens per second
#           and is the better reasoner for it. It fits in VRAM only because this
#           box's 4090 reports 48 GB; on a 24 GB card this brain would spill to
#           CPU and be unusable, which is why the quant is recorded here and not
#           just in the Modelfile.
#   victor  qwen3.6:35b-a3b via config/Victor.Modelfile. MoE — 35B of weights
#           but ~3B active per token, hence fast.
#
# Each `fallback` is that brain's base model, so a machine where `ollama create`
# was never run still answers instead of 404-ing on every turn.
BRAINS = {
    'vicky': {
        'persona': 'Vicky',
        'model': os.environ.get('ZYG_VICKY_MODEL', 'vicky'),
        'fallback': os.environ.get('ZYG_VICKY_MODEL_FALLBACK', 'victor'),
        'num_ctx': int(os.environ.get('ZYG_VICKY_NUM_CTX', '32768')),
        'build': 'ollama create vicky -f config/Vicky.Modelfile',
    },
    'victor': {
        'persona': 'Victor',
        'model': os.environ.get('ZYG_VICTOR_MODEL', 'victor'),
        'fallback': os.environ.get('ZYG_VICTOR_MODEL_FALLBACK', 'qwen3.6:35b-a3b'),
        'num_ctx': int(os.environ.get('ZYG_VICTOR_NUM_CTX', '32768')),
        'build': 'ollama create victor -f config/Victor.Modelfile',
    },
}
DEFAULT_BRAIN = 'victor'


def brain(name=None) -> dict:
    """Resolve a brain key to its row. Unknown names fall back rather than raise:
    the key arrives from a chat file written by an older build, and an assistant
    that answers as the wrong persona is a far smaller failure than one that 500s
    on every turn of a restored chat."""
    return BRAINS.get(str(name or '').strip().lower() or DEFAULT_BRAIN, BRAINS[DEFAULT_BRAIN])


HTTP_TIMEOUT = int(os.environ.get('ZYG_VICTOR_TIMEOUT', '1800'))
MAX_STEPS = int(os.environ.get('ZYG_VICTOR_MAX_STEPS', '24'))  # tool rounds per turn
MAX_HISTORY = int(os.environ.get('ZYG_VICTOR_HISTORY', '40'))  # messages replayed

# ── crews API (the :5000 process that owns image + video generation) ─────────
CREWS_API = (os.environ.get('MEDUSA_CREWS_API') or 'http://127.0.0.1:5000').rstrip('/')
CREWS_TIMEOUT = int(os.environ.get('ZYG_VICTOR_CREWS_TIMEOUT', '30'))

# ── one picture (a different service, and deliberately a different story) ────
# Asking a chat assistant for a picture is not asking for a character: it is one
# prompt and one PNG. That has its own generator — the Video Studio still maker
# on the board server at :8899 (video_stills.py over there) — which takes a free
# text prompt, renders a single image and hands back its path. It shares nothing
# with the character sheet on :5000 beyond both ending up in ComfyUI, and the
# two must not be described in terms of each other: a sheet is a character in 48
# camera angles and runs for hours; this is one frame in about a minute.
STILLS_API = (os.environ.get('ZYG_MEDUSA_STILLS_API') or 'http://127.0.0.1:8899').rstrip('/')
STILLS_TIMEOUT = int(os.environ.get('ZYG_VICKY_STILLS_TIMEOUT', '30'))
# How long picture_generate stands and waits for the render before handing back
# a job id instead. The service's own ceiling is 900 s; a resident Qwen frame is
# 40-90 s, and the first one of a session also pays the model load.
STILLS_WAIT = int(os.environ.get('ZYG_VICKY_STILLS_WAIT', '600'))
STILLS_DEFAULT_FAMILY = os.environ.get('ZYG_VICKY_STILLS_FAMILY', 'qwen')

# The :5000 generate endpoint parks every request in an operator-approval queue
# and renders nothing until someone clicks Approve. As of 2026-09-17 that second
# click is OFF for these assistants at the operator's explicit instruction: when
# they ask for an image they want the image, not a queue entry. image_generate
# therefore submits AND approves in one tool call. The queue itself is untouched
# (the crews API is out of scope to edit, and the GUI's Pending Approvals panel
# still works for anything submitted from the Character Studio form) — this only
# changes what the assistant does after a successful submit. Set
# ZYG_MEDUSA_APPROVAL=on to put the parking back. Same reasoning as the path
# fence above: the guard is kept behind an env var, not deleted.
IMAGE_APPROVAL = os.environ.get('ZYG_MEDUSA_APPROVAL', 'off').strip().lower() in ('on', '1', 'true', 'yes')

# ── tool output limits ───────────────────────────────────────────────────────
READ_MAX = 60_000  # characters returned from one read_file
BASH_MAX = 20_000  # characters of combined stdout+stderr
BASH_TIMEOUT = int(os.environ.get('ZYG_VICTOR_BASH_TIMEOUT', '180'))
GREP_MAX_HITS = 200
GLOB_MAX_HITS = 400
TOOL_RESULT_MAX = 24_000  # every tool result is clipped to this before it goes back
