# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""icon_probe — the server half of the ICON seam's worked example.

ROUTES maps an op name to fn(payload: dict, method: 'GET'|'POST'). Return a dict
(sent as JSON; {'error': ..., 'code': 404} sets the status) or a tuple
(bytes, mime, filename) that the server sends as a download. Reached at
/inspect/api/architecture/ext/icon_probe/<op>; the module is reloaded when this
file changes, so no server restart is needed.
"""


def ping(payload, method):
    return {'ok': True, 'method': method, 'echo': payload}


def text(payload, method):
    name = str(payload.get('name') or 'world')[:40]
    return (('hello %s' % name).encode('utf-8'), 'text/plain; charset=utf-8', 'hello.txt')


ROUTES = {'ping': ping, 'text': text}
