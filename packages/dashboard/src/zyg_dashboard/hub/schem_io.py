#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Import and capture — the two front-ends that bring in real geometry.

Both shell out to Node scripts in GameSim/mineflayer_toolkit, which is where
prismarine-schematic and mineflayer already live. Nothing is installed and the
shared GameSim/minecraft/node_modules tree (symlinked into three sims) is never
touched.

Everything here funnels into the same {x,y,z,mat,state} block list the compiler
proves — that is the whole point of the source/compiler split: two more ways in,
zero compiler changes.
"""

import json
import subprocess
from pathlib import Path
from zyg_workflows.bin import MissingExecutable, exe
from zyg_workflows.paths import tmp_dir
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


TOOLKIT = Path('~/Zygomatic/GameSim/mineflayer_toolkit').expanduser()
CONVERT = TOOLKIT / 'schem_convert.js'
CAPTURE = TOOLKIT / 'capture_region.js'

# Blocks a capture should never carry into a schematic: the pad itself, and
# anything the bot could not obtain or place meaningfully.
CAPTURE_SKIP = {'grass_block', 'dirt', 'bedrock', 'air', 'cave_air', 'water', 'lava'}


class IOError_(Exception):
    pass


def _run_node(args, timeout=180):
    try:
        p = subprocess.run(
            [exe('node')] + [str(a) for a in args],
            cwd=str(TOOLKIT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise IOError_('node script timed out') from exc
    except (FileNotFoundError, MissingExecutable) as exc:
        raise IOError_('node is not on PATH') from exc
    if p.returncode != 0:
        detail = p.stderr.strip() or p.stdout.strip() or f'exit {p.returncode}'
        try:
            detail = json.loads(detail).get('error', detail)
        except (ValueError, TypeError) as _exc:
            _zyg_log.debug('node error detail is not JSON, using it verbatim: %s', _exc)
        raise IOError_(detail[:400])
    try:
        return json.loads(p.stdout)
    except Exception as exc:
        raise IOError_('node script returned unparseable output: ' + p.stdout[:200]) from exc


def import_schem(path, anchor=None):
    """Read a Sponge .schem into world-anchored blocks."""
    if not Path(path).exists():
        raise IOError_(f'file not found: {path}')
    args = [CONVERT, 'import', path]
    if anchor:
        args += ['--anchor', ' '.join(str(int(v)) for v in anchor)]
    return _run_node(args)


def export_schem(blocks, out_path):
    """Write blocks out as a Sponge .schem so a build can be opened in WorldEdit
    or Litematica."""
    tmp = tmp_dir('hub') / 'hub_schem_export_src.json'
    tmp.write_text(json.dumps({'blocks': blocks}))
    return _run_node([CONVERT, 'export', tmp, out_path])


def capture_region(frm, to, port=25567, settle=6000):
    """Capture a hand-built region from the live server."""
    data = _run_node(
        [
            CAPTURE,
            '--from',
            ' '.join(str(int(v)) for v in frm),
            '--to',
            ' '.join(str(int(v)) for v in to),
            '--port',
            str(port),
            '--settle',
            str(settle),
        ],
        timeout=180,
    )
    if data.get('error'):
        raise IOError_(data['error'])
    return data


def clean_capture(blocks, drop_ground=True):
    """Strip the build pad out of a capture.

    A capture of the pad picks up the grass floor kit.py laid down; keeping it
    would make the schematic rebuild the ground it is standing on.
    """
    out = []
    for b in blocks:
        if drop_ground and b.get('mat') in CAPTURE_SKIP:
            continue
        out.append(b)
    return out


def cubify(blocks, manifest_lookup):
    """Replace blocks the bot cannot place with their nearest full-cube cousin.

    Imports from the wild are full of fences, panes, carpets and plants. Rather
    than fail the whole file, swap what we can and let the compiler report the
    rest. Returns (blocks, changes).
    """
    subs = {
        '_pane': '_stained_glass',
        'cobblestone_wall': 'cobblestone',
        '_fence': '_planks',
        '_carpet': '_wool',
        '_trapdoor': '_planks',
    }
    changed = []
    out = []
    for b in blocks:
        mat = b['mat']
        info = manifest_lookup(mat)
        if info and info['bb'] == 'block' and info['give']:
            out.append(b)
            continue
        new = None
        for suffix, repl in subs.items():
            if mat.endswith(suffix):
                cand = mat.replace(suffix, repl)
                if manifest_lookup(cand):
                    new = cand
                    break
        if new:
            changed.append((mat, new))
            nb = dict(b)
            nb['mat'] = new
            nb.pop('state', None)
            out.append(nb)
        else:
            changed.append((mat, None))  # dropped
    return out, changed
