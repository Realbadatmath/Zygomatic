# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The single-page Game Simulator UI."""

# ruff: noqa: F401

from .head import HEAD
from .css_creation import CSS_CREATION
from .css_simulation import CSS_SIMULATION
from .css_library import CSS_LIBRARY
from .css_boards import CSS_BOARDS
from .css_layout import CSS_LAYOUT
from .body import BODY
from .js_catalog import JS_CATALOG
from .js_creation import JS_CREATION
from .js_library import JS_LIBRARY
from .js_benchmark import JS_BENCHMARK
from .js_boards import JS_BOARDS
from .js_creator import JS_CREATOR

HTML = (
    HEAD
    + CSS_CREATION
    + CSS_SIMULATION
    + CSS_LIBRARY
    + CSS_BOARDS
    + CSS_LAYOUT
    + BODY
    + JS_CATALOG
    + JS_CREATION
    + JS_LIBRARY
    + JS_BENCHMARK
    + JS_BOARDS
    + JS_CREATOR
)

__all__ = ['HTML']
