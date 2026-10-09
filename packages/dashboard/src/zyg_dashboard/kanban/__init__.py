# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Kanban server's module-level sections, split out of ``kanban_server.py``.

One module per concern; ``kanban_server`` imports every name back so the HTTP
handler keeps referring to them by bare name and external callers keep seeing
``zyg_dashboard.kanban_server.<name>``.
"""
