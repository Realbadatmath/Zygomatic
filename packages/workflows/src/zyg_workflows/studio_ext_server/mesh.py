# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Mesh Studio through the studio ext seam.

Answers at /inspect/api/studio/mesh/<op>, GET or POST. Hot-reloaded on mtime
change, so editing this file — or any of mesh_studio_ops/*.py it reaches —
needs no restart of kanban-server.

`mesh_studio` is imported INSIDE each handler, never at module scope: a typo
or a duplicate-id assert in a part file must come back to the page as
{'error': ...} with a status, not take the reload out at import time and leave
the whole seam missing an op.
"""


def _ops(payload, method):
    try:
        from zyg_workflows import mesh_studio

        return mesh_studio.ops_payload()
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}', 'code': 500}


def _spec(payload, method):
    try:
        from zyg_workflows import mesh_studio

        return mesh_studio.spec()
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}', 'code': 500}


ROUTES = {
    'ops': _ops,
    'spec': _spec,
}
