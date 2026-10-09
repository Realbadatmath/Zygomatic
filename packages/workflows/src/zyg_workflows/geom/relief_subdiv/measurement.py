# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The measurement: measure(), the determinism check and the report formatting.

Moved verbatim out of the old single-file relief_subdiv.py (lines 1341-1766).

``measure`` is now the orchestrator of the three loops only — body, level, cut
kind. Each stage it calls, and the ``_row``/``_fmt`` row formatting, live in
``measurement_stages.py``, where they can be unit-tested without building a cage.
"""

import json
import os
import resource
import time

import numpy as np
import logging as _zyg_logging

from zyg_workflows.geom.relief_subdiv.constants import (
    CAGE_VERTS,
)
from zyg_workflows.geom.relief_subdiv.nulls import cuts_for
from zyg_workflows.geom.relief_subdiv.layer import apply_relief_at
from zyg_workflows.geom.relief_subdiv import measurement_stages as _stages
from zyg_workflows.geom.relief_subdiv.measurement_stages import (
    body_pools,
    cage_body_record,
    cuts_record,
    level_meshes,
    level_null_record,
    prepare_cage_body,
    print_cut_table,
    probe_all_states,
    report_header,
)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.geom.relief_subdiv')

# `_row` and `_fmt` moved into measurement_stages.py with their only callers.
# relief_subdiv.__init__ imports them from HERE, so they are re-bound by assignment
# (which ruff cannot prune) rather than re-exported behind a noqa.
_row = _stages._row
_fmt = _stages._fmt
# ---------------------------------------------------------------------------------
# the measurement
# ---------------------------------------------------------------------------------


def measure(
    which=('female',),
    levels=(2,),
    states=('base', 'cage2sub', 'sub'),
    cut_kinds=('level', 'shipped'),
    scale=1.0,
    verbose=True,
    out_path=None,
):
    """The whole experiment: nulls, three states, both cuts, per level, per body.

    THE THREE STATES AND WHY ALL THREE ARE NEEDED — a two-column table here would draw the
    wrong conclusion from a real number:
        base      subdivide(cage). No relief. Says what the finer null alone buys.
        cage2sub  subdivide(cage + relief.apply_relief at CAGE level). The layer that
                  already exists, seen by a probe at subdivision resolution.
        sub       subdivide(cage) + relief.apply_relief AT SUBDIVISION level. This module.
    `sub` minus `cage2sub` is the only part attributable to evaluating the field at the
    higher resolution, which is the claim this module is here to test.

    The cage level (level 0) is measured too when it is in `levels`, with `base` = the
    delivered cage and `sub` = relief.py's own result, so the published 0/20 is reproduced
    inside the same run rather than quoted from a docstring.
    """
    from zyg_workflows.geom import mesh_skeletons as MS
    from zyg_workflows.geom.form import regions as RG

    doc = RG.load_regions()  # no vertex-count argument: see the check below
    if int(doc['cage_vertices']) != CAGE_VERTS:
        raise ValueError(
            'regions.json is authored against a %d-vertex cage, not %d' % (doc['cage_vertices'], CAGE_VERTS)
        )
    reg = MS._registry()
    bone_names = [str(n) for n in MS._bone_names(MS._model())]
    t_start = time.time()
    out = report_header(scale, states, cut_kinds)

    for who in which:
        cb = prepare_cage_body(who, reg['originals'][who]['params'], scale, bone_names, verbose)
        body = cage_body_record(cb)
        if verbose:
            _zyg_log.info('\n################ %s  cage S=%.6f m ################' % (who, cb.stature_m))

        for lv in levels:
            lv = int(lv)
            if verbose:
                _zyg_log.info('\n---- level %d ----' % lv)
            lrec = {'level': lv}

            meshes, faces_s = level_meshes(cb, lv, scale, bone_names, lrec, verbose)
            S = float(meshes['base'][:, 2].max() - meshes['base'][:, 2].min())
            lrec['stature_m'] = S
            lrec['n_verts'] = int(len(meshes['base']))

            nul = level_null_record(meshes['base'], faces_s, lv, S, lrec, verbose)
            pools = body_pools(meshes['base'], faces_s, S, doc, lrec)

            lrec['states'] = {}
            for kind in cut_kinds:
                cuts = cuts_for(nul, kind)
                lrec.setdefault('cuts', {})[kind] = cuts_record(cuts)
                probe_all_states(lrec, meshes, faces_s, pools, cuts, states, kind, S, verbose)
                if verbose:
                    print_cut_table(lrec, pools, states, kind, cuts)

            body['levels'][str(lv)] = lrec
        out['bodies'][who] = body

    out['wall_clock_s'] = time.time() - t_start
    out['peak_rss_gb'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6
    if verbose:
        _zyg_log.info('\n==== %.0f s wall clock, peak RSS %.2f GB ====' % (out['wall_clock_s'], out['peak_rss_gb']))
    if out_path:
        tmp = out_path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(_jsonable(out), f, indent=1, sort_keys=True)
        os.replace(tmp, out_path)
        if verbose:
            _zyg_log.info('wrote %s' % out_path)
    return out


def determinism_check(who='female', level=2, threads=(1, 8)):
    """Subdivide and sculpt at two BLAS/OMP widths and compare the result BYTE FOR BYTE.

    Same contract relief.determinism_check holds for the cage layer, at the resolution this
    module adds. There is no unordered reduction in either half: Catmull-Clark is np.unique
    on sorted index pairs plus np.add.at over a fixed order, and relief.apply_relief is
    numpy plus a scipy dijkstra from a sorted seed array. "Should be deterministic" is not
    the same statement as "is", so it is run rather than asserted.
    """
    import hashlib
    from zyg_workflows.geom import mesh_skeletons as MS
    from zyg_workflows.geom import relief as RL

    reg = MS._registry()
    p = reg['originals'][who]['params']
    bone_names = [str(n) for n in MS._bone_names(MS._model())]
    v0, faces0, bones, weights = RL.bones_for(
        p['phenotype'], p.get('local_changes') or None, p.get('bone_scales') or None
    )
    v0 = np.asarray(MS._apply_anatomy(v0, faces0, p.get('anatomy_layer') or {}), np.float64)
    faces0 = np.asarray(faces0, np.int64)
    mate0, _ = RL.mirror_map(v0, RL.MIRROR_TOL_FRAC * float(v0[:, 2].max() - v0[:, 2].min()))
    hashes = []
    for nt in threads:
        try:
            import torch

            torch.set_num_threads(int(nt))
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('torch thread cap skipped: %s', _exc)
        _b, vr, _f, _r = apply_relief_at(
            v0, faces0, level, p['phenotype'], bones, weights, bone_names, mate_cage=mate0, verbose=False
        )
        hashes.append(hashlib.sha256(np.ascontiguousarray(vr, np.float64).tobytes()).hexdigest()[:16])
    return {
        'who': who,
        'level': int(level),
        'threads': list(threads),
        'hashes': hashes,
        'identical': len(set(hashes)) == 1,
    }


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(x) for x in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return _jsonable(o.tolist())
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o
