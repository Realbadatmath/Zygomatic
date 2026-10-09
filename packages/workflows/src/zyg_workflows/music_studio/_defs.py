# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The registry primitives: the tool/section constructors and SECTIONS.

`SECTIONS` is appended to by every section module, never rebound, so the list
object itself is the registry.
"""


# ── the sections ──────────────────────────────────────────────────────────
# Each: id, title (the caption printed above the group), place, tools.
# Each tool: id, lb (label), tip (one line — what it would do), svg, live.


def _t(tid, lb, tip, svg, live=False):
    return {'id': tid, 'lb': lb, 'tip': tip, 'svg': svg, 'live': live}


SECTIONS = []


def _sec(sid, title, place, tools):
    SECTIONS.append({'id': sid, 'title': title, 'place': place, 'tools': tools})
