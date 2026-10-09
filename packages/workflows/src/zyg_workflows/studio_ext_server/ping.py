# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Smoke-test module for the studio ext seam — proves hot reload and GET+POST."""

ROUTES = {'ping': lambda payload, method: {'ok': True, 'pong': payload.get('x', ''), 'method': method}}
