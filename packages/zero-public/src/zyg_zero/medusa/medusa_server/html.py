# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Reassembles the single-page GUI from its parts.

The parts are the original `HTML` string literal of medusa_server.py (lines 70-3885)
cut at its own seams; concatenating them in this order rebuilds it character for
character. TAIL is the closing lines 3884-3885.
"""

from .html_head_css import HEAD_CSS
from .html_css_panels import CSS_PANELS
from .html_body import BODY
from .js_core import JS_CORE
from .js_training import JS_TRAINING
from .js_inspection import JS_INSPECTION
from .js_resources import JS_RESOURCES
from .js_vicky import JS_VICKY
from .js_models import JS_MODELS

TAIL = """</body>
</html>"""

HTML = HEAD_CSS + CSS_PANELS + BODY + JS_CORE + JS_TRAINING + JS_INSPECTION + JS_RESOURCES + JS_VICKY + JS_MODELS + TAIL
