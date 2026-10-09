# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""medusa_vicky.constants — the runtime paths, the Claude CLI knobs and the ENGINES table.

Lines 60-145 of the original medusa_vicky.py, moved verbatim
(2026-10-07 split). No logic changed.
"""

from __future__ import annotations

import os
import shutil
import threading

from zyg_zero import paths as _zero_paths

# Medusa's own folder. This code was written in medusa_vicky.py, one directory
# up, so every path below hangs off the medusa tree, not off this package.
HERE = str(_zero_paths.MEDUSA_DIR)
RULES_FILE = os.path.join(HERE, 'VICKY_RULES.md')
RUNTIME_DIR = os.path.join(HERE, 'data', 'runtime', 'vicky')
CONV_DIR = os.path.join(RUNTIME_DIR, 'conversations')
CHAT_DIR = os.path.join(RUNTIME_DIR, 'chats')  # the chat store the GUI reads back
CURRENT_FILE = os.path.join(RUNTIME_DIR, 'current.json')  # which chat a refresh reopens
CHAT_TITLE_MAX = 70
CHAT_KEEP_MESSAGES = int(os.environ.get('ZYG_VICKY_CHAT_MAX_MSGS', '600'))
PARTIAL_DIR = os.path.join(RUNTIME_DIR, 'partials')
UPLOAD_DIR = os.path.join(RUNTIME_DIR, 'uploads')
UPLOAD_MAX_AGE = 7 * 86400  # purge files older than 7 days on startup
PARTIAL_FLUSH_S = 2.0  # a kill loses at most this much time of a thinking block...
PARTIAL_FLUSH_CHARS = 4096  # ...or this many characters, whichever comes first
_CLOCK = threading.Lock()

# ── Claude Code CLI ───────────────────────────────────────────────────────────
CLI_BIN = os.environ.get('ZYG_VICKY_CLI', '') or shutil.which('claude') or '/usr/local/bin/claude'
CLI_MODEL = os.environ.get('ZYG_VICKY_CLI_MODEL', 'sonnet')
CLI_TIMEOUT = int(os.environ.get('ZYG_VICKY_CLI_TIMEOUT', '1800'))
CLI_MAX_OUTPUT = int(os.environ.get('ZYG_VICKY_CLI_OUT', '64000'))
CLI_MAX_TURNS = int(os.environ.get('ZYG_VICKY_CLI_MAX_TURNS', '60'))
CLI_DIR = HERE  # Vicky's cwd IS Medusa's own folder — her own settings.json lives here, nowhere else does
ALLOWED_TOOLS = 'Read,Write,Edit,Glob,Grep,Bash'

# ── engines ──────────────────────────────────────────────────────────────────
# The assistants share this whole module — the chat store, the ledger, the job
# machinery, the rules file. Only the thing that produces the tokens differs:
#
#   dolphin  Vicky   Dolphin-Mistral-24B-Venice-Edition Q8_0, local, run through
#                    medusa_victor's 'vicky' brain. THE DEFAULT since 2026-09-17.
#   ollama   Victor  qwen3.6:35b-a3b, local, medusa_victor's 'victor' brain.
#   claude   Vicky   a `claude -p --model sonnet` subprocess on the operator's
#                    Anthropic login. DISABLED since 2026-09-17.
#
# Memory differs by BACKEND, not by engine. The claude backend's memory is the
# CLI session id (--resume) and the chat only points at it; the ollama backend
# has no server-side session, so the chat's own `messages` list IS the memory,
# replayed whole every turn. Both local engines therefore pay for the display
# trim (CHAT_KEEP_MESSAGES) in real context where Sonnet paid nothing.
#
# The engine is stored ON THE CHAT, not in the browser, for the same reason the
# session id is: reopening a chat in another tab has to reopen the assistant
# that has its memory. Switching engine mid-chat is allowed and does not
# discard anything — Vicky keeps her session id and Victor keeps reading the
# messages — but they remember different halves of it, so the panel says so.
#
# WHY CLAUDE IS STILL IN THIS TABLE. The operator turned Sonnet off, not away:
# every Claude chat keeps its `session` uuid in the chat store, and that uuid is
# the only handle on a transcript that lives inside Claude Code rather than in
# our files. Deleting the row would strand those conversations with no way to
# resume them. ZYG_VICKY_CLAUDE=on brings the option back and they carry on.
#
# `backend` and `brain` are separate fields because two engines now share one
# backend: the first picks the code path, the second picks the model inside it.
ENGINES = {
    'dolphin': {
        'id': 'dolphin',
        'name': 'Vicky',
        'label': 'Vicky \u00b7 Dolphin 24B (local)',
        'where': 'this machine (free per turn)',
        'backend': 'ollama',
        'brain': 'vicky',
        'enabled': True,
    },
    'ollama': {
        'id': 'ollama',
        'name': 'Victor',
        'label': 'Victor \u00b7 Ollama (local)',
        'where': 'this machine (free per turn)',
        'backend': 'ollama',
        'brain': 'victor',
        'enabled': True,
    },
    'claude': {
        'id': 'claude',
        'name': 'Vicky',
        'label': 'Vicky \u00b7 Claude Sonnet',
        'where': 'Anthropic login (metered)',
        'backend': 'claude',
        'brain': None,
        'enabled': (os.environ.get('ZYG_VICKY_CLAUDE', 'off').strip().lower() in ('on', '1', 'true', 'yes')),
    },
}
DEFAULT_ENGINE = os.environ.get('ZYG_VICKY_ENGINE', 'dolphin')
if DEFAULT_ENGINE not in ENGINES or not ENGINES[DEFAULT_ENGINE]['enabled']:
    DEFAULT_ENGINE = next(k for k, e in ENGINES.items() if e['enabled'])
