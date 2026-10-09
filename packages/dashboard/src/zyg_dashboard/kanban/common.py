# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kanban/common.py — shared paths, roots and the module logger every kanban section needs.

Split verbatim out of ``kanban_server.py`` (lines 51-82) on 2026-10-06; the handler
re-imports every name from here, so ``zyg_dashboard.kanban_server.<name>`` still resolves.
"""

import os
import logging as _zyg_logging
from zyg_workflows.bin import exe

# Named for the server module, not for this one: the log stream the operator greps
# ('zyg_dashboard.kanban_server') must not move because the code was split up.
_zyg_log = _zyg_logging.getLogger('zyg_dashboard.kanban_server')

# The encoder, resolved once and absolutely (ZYG_BIN_FFMPEG wins, then PATH). required=False
# with a bare-name fallback is deliberate: the three call sites below build their argv
# OUTSIDE their `except (OSError, subprocess.SubprocessError)` block and report a missing
# encoder by returning False, so a raise from exe() at argv-build time would turn a graceful
# "preview failed" into a 500. The bare name keeps today's FileNotFoundError path intact.
_FFMPEG = exe('ffmpeg', required=False) or 'ffmpeg'


PORT = int(os.environ.get('KANBAN_PORT', 8899))
# The zyg_dashboard package directory — one level ABOVE this sub-package, which is
# where kanban_server.py lives and where every data/, output/ and asset path below
# is anchored.
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CHARS_ROOT = os.path.realpath(
    os.environ.get('ZYG_STORYTELLER_CHARS', os.path.expanduser('~/lora-datasets/storyteller_chars'))
)
_RUNTIME = os.path.join(HERE, 'data', 'runtime')
_OUTPUT_ROOT = os.path.realpath(os.path.join(HERE, 'output'))
# 2026-08-11: generated video does NOT all live under output/. The workflows
# write to three disjoint trees, and the Videos tab only ever walked the first
# one — so storyteller episodes and documentary finals (the things worth
# inspecting) were invisible. Media URLs are now '<rootkey>/<relpath>'; a bare
# path still resolves under 'out' for older cached pages.
_DATA_OUTPUT_ROOT = os.path.realpath(os.path.join(HERE, 'data', 'output'))
_DATA_RUNTIME_ROOT = os.path.realpath(os.path.join(HERE, 'data', 'runtime'))
_MEDIA_ROOTS = {
    'out': _OUTPUT_ROOT,  # env/effects/wardrobe/multichar/storyteller scenes
    'dout': _DATA_OUTPUT_ROOT,  # documentary clips + storyteller episodes
    'drun': _DATA_RUNTIME_ROOT,  # in-flight pipeline working dirs (intermediates)
}
# .vtt rides the same whitelist as the media it captions: an HTML5 <video>
# cannot see a subtitle track muxed INSIDE the mp4, so the player's Captions
# menu only appears when the page can fetch a sibling WebVTT over this route.
