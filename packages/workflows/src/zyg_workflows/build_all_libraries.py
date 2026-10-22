# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""build_all_libraries.py — rebuild every Blender asset library from the packs.

    python3 build_all_libraries.py --plan
    python3 build_all_libraries.py                 # only what is stale
    python3 build_all_libraries.py --force

WHY A DRIVER. Each pack's .blend was built by hand, one `blender -b` at a time.
That was fine at 15 packs; at 72 it is a list nobody will keep straight, and
the failure mode is silent — a pack whose library was never built simply does
not appear in the Asset Browser, and looks identical to a pack that has no
assets.

STALENESS IS MEASURED, NOT ASSUMED. A pack is rebuilt when the newest file in
its tree is newer than its .blend. That means adding one model to a kit
rebuilds that kit and nothing else, and re-running with no changes does no
work at all. `--force` overrides.

ONE BLENDER PER PACK, ON PURPOSE. The import path leaks datablocks — glTF
brings its own materials and images, `object.join()` invalidates wrappers, and
a long-lived session accumulates all of it. A fresh process per pack costs
about 3.5 s of startup and removes a whole class of cross-pack contamination.
`--factory-startup` because the importer is bundled and the 30 installed
add-ons are not wanted here (MeasureIt_ARCH also cannot register headless and
prints a traceback that looks like a failure).
"""

from __future__ import annotations

import ast
import os
import subprocess
import time
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
PACKS_ROOT = os.path.join(HERE, 'data', 'assets', 'mesh_packs')
LIB_ROOT = os.path.join(HERE, 'data', 'assets', 'blender_library')
BUILDER = os.path.join(HERE, 'blender_scripts', 'build_asset_library.py')
BLENDER = os.environ.get('BLENDER', 'blender')


def blend_path(pack: str) -> str:
    d = os.path.join(LIB_ROOT, os.path.dirname(pack) or pack)
    return os.path.join(d, os.path.basename(pack) + '.blend')


GEN_PREVIEWS = os.path.join(PACKS_ROOT, '_generated_previews')


def _tree_mtime(path: str, skip_underscore: bool = True) -> float:
    m = 0.0
    for root, dirs, files in os.walk(path):
        if skip_underscore:
            dirs[:] = [d for d in dirs if not d.startswith(('_', '.'))]
        for f in files:
            try:
                m = max(m, os.path.getmtime(os.path.join(root, f)))
            except OSError as _exc:
                _zyg_log.debug('mtime scan skipped a file: %s', _exc)
    return m


def newest(pack: str) -> float:
    """When this pack last changed, INCLUDING its rendered previews.

    The previews are the reason this is not just the pack directory. They are
    written to _generated_previews, deliberately outside every pack so a
    re-download never has to reason about what is ours - which means rendering
    them moves no mtime inside the pack, and a staleness check that looked
    only there would leave every Smithsonian library sitting at 0 previews
    with nothing reporting a problem. Same shape as the catalogue cache's
    `_gen` entry, and found the same way: by the count coming back zero."""
    return max(_tree_mtime(os.path.join(PACKS_ROOT, pack)), _tree_mtime(os.path.join(GEN_PREVIEWS, pack), False))


def build_one(pack: str, licence: str, timeout: int) -> dict:
    cmd = [BLENDER, '-b', '--factory-startup', '--python', BUILDER, '--', '--pack', pack, '--licence', licence]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {'pack': pack, 'error': f'timeout after {timeout}s'}
    line = next((l for l in p.stdout.splitlines() if l.startswith('@@RESULT@@')), None)
    if not line:
        tail = (p.stderr or p.stdout).strip().splitlines()[-3:]
        return {'pack': pack, 'error': 'no result', 'tail': tail}
    try:
        r = ast.literal_eval(line[len('@@RESULT@@ ') :])
    except (ValueError, SyntaxError):
        return {'pack': pack, 'error': 'unparsable result'}
    r['secs'] = round(time.time() - t0, 1)
    return r


if __name__ == '__main__':  # the CLI lives in build_all_libraries_cli
    from zyg_workflows.build_all_libraries_cli import main as _cli_main

    raise SystemExit(_cli_main())
