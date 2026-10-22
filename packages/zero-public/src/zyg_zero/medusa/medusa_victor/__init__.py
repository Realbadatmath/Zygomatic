# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""medusa_victor.py — the local brains behind Medusa's chat assistant.

Built 2026-09-17 for Victor, when he was the local alternative to a metered
Vicky. Later the same day Vicky moved here too, so this module now serves BOTH
personas and the name on the file is history rather than scope:

    Vicky   Dolphin-Mistral-24B-Venice-Edition Q8_0 (brain 'vicky'). The
            default. Dense 24B — every token reads all 25 GB of weights, so it
            is roughly a third of Victor's speed and the better reasoner for it.
    Victor  qwen3.6:35b-a3b (brain 'victor'). MoE, ~3B active per token, fast.

    Vicky   `claude -p --model sonnet` — was the original, now DISABLED. That
            path still lives in medusa_vicky.py, not here.

A persona is nothing but a row in BRAINS: name, model, context. Everything else
is shared, which is the point.

MEMORY. The Claude path resumed a CLI session id (`--resume <uuid>`) and the
chat store only held a pointer to it. Ollama has no server-side session at all,
so a local brain's memory IS the chat store's ``messages`` list, replayed as the
request every turn. That inverts the rule the chat store was built around: a
Claude chat with messages but no session looks continuous and answers as a
stranger; here the messages ARE the memory and the session id is meaningless. It
also means the display transcript's trim (CHAT_KEEP_MESSAGES) costs real context
now, where it cost Sonnet none — see _history_messages().

TOOLS AND REACH. Every tool these models can call is defined in this file. There
WAS a path fence here — a realpath that had to sit inside Medusa's own folder —
and as of 2026-09-17 it is OFF by default at the operator's explicit
instruction: this is their machine and their assistant, and it is meant to reach
the whole of it. The check survives behind ZYG_VICKY_FENCE=on rather than being
deleted, so putting it back is one env var. See _safe_path for what that costs.
Note the fence was never the real boundary in any case: `run_bash` has always
taken an arbitrary shell command and could always name any path.

GENERATION. Medusa itself renders nothing. The typed image_*, picture_* and
video_* tools below are the SAME endpoints a shell would curl, and they reach
TWO different services which are not variants of each other:

    picture_generate  ONE picture from one prompt, ~a minute, on the still
                      generator at :8899 (STILLS_API). This is what a chat means
                      by "generate a picture". It also hands the finished file to
                      the panel, so the picture lands in the conversation rather
                      than a path the operator has to go and open (_record_image).
    image_generate    A CHARACTER SHEET on the crews API at :5000 — a named woman
                      in 48 camera angles, hours of GPU, for a training set. It
                      also approves its own request, because /api/medusa/generate
                      only ever parks one and the operator asking IS the approval
                      (see IMAGE_APPROVAL).

Describing the first in terms of the second is how a request for one picture
became a 48-angle run (2026-09-17): they are separate stories and the rules file
keeps them apart. video_render_start -> /api/internal/movement/start, with
crews_api() as the general escape hatch. They are typed because a local model
handed "you may curl things" does not reliably invent the right JSON body — but
they are not a fence, and run_bash remains available for anything they miss.

Those crews POST routes are localhost-gated (`_local_only()` on :5000). Medusa
runs on the same box, so a call from this module passes that gate: these
assistants act with the operator's authority there, which is the arrangement
that was asked for.

TEMPLATES ARE NOT AUTOMATIC. Vicky's GGUF ships a Jinja chat template that
Ollama cannot convert (it calls strftime_now) and that has no tool support in
any case. Ollama does not say so — it silently falls back to `{{ .Prompt }}` and
`completion`-only capability, and the model then answers fluently while every
tool call becomes prose. config/Vicky.Modelfile carries a hand-written Mistral
v7 template for exactly this reason. Check `ollama show <model>` lists `tools`
after ever rebuilding either model.

RULES. Read fresh from VICKY_RULES.md every turn via medusa_vicky.vicky_rules().
Nothing is baked into either Modelfile, so an edit to the rules file takes
effect on the next message.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import logging as _zyg_logging

from zyg_workflows import paths

# The sections of the original medusa_victor.py, imported in their original order
# so module-level side effects still happen in that order, then every name the
# single-file module defined, re-exported so no importer anywhere changes.
from .constants import (
    BASH_MAX,
    BASH_TIMEOUT,
    BRAINS,
    CREWS_API,
    CREWS_TIMEOUT,
    DEFAULT_BRAIN,
    FENCE,
    GLOB_MAX_HITS,
    GREP_MAX_HITS,
    HERE,
    HTTP_TIMEOUT,
    IMAGE_APPROVAL,
    MAX_HISTORY,
    MAX_STEPS,
    OLLAMA_URL,
    READ_MAX,
    ROOT,
    STILLS_API,
    STILLS_DEFAULT_FAMILY,
    STILLS_TIMEOUT,
    STILLS_WAIT,
    TOOL_RESULT_MAX,
    brain,
)
from .backends import (
    _TURN,
    _clip,
    _crews,
    _http_json,
    _record_image,
    _rel,
    _safe_path,
    _stills,
    _turn_job,
    _urlopen_http,
    available,
    info,
    models,
    resolve_model,
)
from .tools_files import (
    _t_edit_file,
    _t_list_files,
    _t_read_file,
    _t_run_bash,
    _t_search_files,
    _t_write_file,
)
from .tools_media import (
    _SHEET_ASK_DIR,
    _SHEET_ASK_TTL_S,
    _SHEET_NO,
    _SHEET_YES,
    _sheet_ask_path,
    _sheet_clear_ask,
    _sheet_consent,
    _sheet_record_ask,
    _still_dim,
    _t_crews_api,
    _t_image_angles,
    _t_image_capability,
    _t_image_decide,
    _t_image_edit,
    _t_image_edit_status,
    _t_image_generate,
    _t_image_jobs,
    _t_image_pending,
    _t_picture_generate,
    _t_picture_status,
    _t_video_prompt,
    _t_video_render_start,
    _t_video_render_status,
    _t_video_render_stop,
    _t_video_spec,
)
from .schemas import (
    TOOLS,
    TOOL_SCHEMAS,
    _B,
    _I,
    _O,
    _S,
    _schema,
    system_prompt,
)
from .turn import (
    AGE_GATE_PATH,
    EMPTY_NUDGE,
    MAX_NUDGES,
    NUDGE,
    PICTURE_NUDGE,
    REFUSAL_NUDGE,
    _AGE_GATE,
    _AGE_GATE_TRIED,
    _INTENT,
    _MINOR_HINT,
    _PICTURE_CLAIM,
    _REFUSAL,
    _age_gate,
    _chat_once,
    _claims_picture,
    _history_messages,
    _images_b64,
    _is_intent,
    _minor_language,
    _refuses_content,
    run_turn,
)

_zyg_log = _zyg_logging.getLogger(__name__)

# The single-file module carried one module-level annotation; restated bare (it
# binds nothing) so this package's __annotations__ matches the old module's.
TOOLS: dict[str, tuple[dict, callable]]

# ── re-export surface ────────────────────────────────────────────────────────
# Every name the single medusa_victor.py defined, so attribute access on this module
# keeps resolving after the split. Declaring them is what makes the re-export
# deliberate rather than an unused import; nothing does ``import *`` from here,
# so __all__ changes no behaviour.
__all__ = [
    'fnmatch',
    'json',
    'os',
    're',
    'subprocess',
    'threading',
    'time',
    'urllib',
    '_zyg_logging',
    'paths',
    'BASH_MAX',
    'BASH_TIMEOUT',
    'BRAINS',
    'CREWS_API',
    'CREWS_TIMEOUT',
    'DEFAULT_BRAIN',
    'FENCE',
    'GLOB_MAX_HITS',
    'GREP_MAX_HITS',
    'HERE',
    'HTTP_TIMEOUT',
    'IMAGE_APPROVAL',
    'MAX_HISTORY',
    'MAX_STEPS',
    'OLLAMA_URL',
    'READ_MAX',
    'ROOT',
    'STILLS_API',
    'STILLS_DEFAULT_FAMILY',
    'STILLS_TIMEOUT',
    'STILLS_WAIT',
    'TOOL_RESULT_MAX',
    'brain',
    '_TURN',
    '_clip',
    '_crews',
    '_http_json',
    '_record_image',
    '_rel',
    '_safe_path',
    '_stills',
    '_turn_job',
    '_urlopen_http',
    'available',
    'info',
    'models',
    'resolve_model',
    '_t_edit_file',
    '_t_list_files',
    '_t_read_file',
    '_t_run_bash',
    '_t_search_files',
    '_t_write_file',
    '_SHEET_ASK_DIR',
    '_SHEET_ASK_TTL_S',
    '_SHEET_NO',
    '_SHEET_YES',
    '_sheet_ask_path',
    '_sheet_clear_ask',
    '_sheet_consent',
    '_sheet_record_ask',
    '_still_dim',
    '_t_crews_api',
    '_t_image_angles',
    '_t_image_capability',
    '_t_image_decide',
    '_t_image_edit',
    '_t_image_edit_status',
    '_t_image_generate',
    '_t_image_jobs',
    '_t_image_pending',
    '_t_picture_generate',
    '_t_picture_status',
    '_t_video_prompt',
    '_t_video_render_start',
    '_t_video_render_status',
    '_t_video_render_stop',
    '_t_video_spec',
    'TOOLS',
    'TOOL_SCHEMAS',
    '_B',
    '_I',
    '_O',
    '_S',
    '_schema',
    'system_prompt',
    'AGE_GATE_PATH',
    'EMPTY_NUDGE',
    'MAX_NUDGES',
    'NUDGE',
    'PICTURE_NUDGE',
    'REFUSAL_NUDGE',
    '_AGE_GATE',
    '_AGE_GATE_TRIED',
    '_INTENT',
    '_MINOR_HINT',
    '_PICTURE_CLAIM',
    '_REFUSAL',
    '_age_gate',
    '_chat_once',
    '_claims_picture',
    '_history_messages',
    '_images_b64',
    '_is_intent',
    '_minor_language',
    '_refuses_content',
    'run_turn',
]
