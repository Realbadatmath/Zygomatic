# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Small shared helpers, and the defensive probes for the optional third-party pieces.

Moved verbatim out of the old single-file scan_ingest.py (lines 397-522).
"""

import json
import os
import sys
import numpy as np

from zyg_workflows.geom.scan_ingest.constants import (
    STAGES,
    ScanIngestError,
)


# ----------------------------------------------------------------------------------
# small shared helpers
# ----------------------------------------------------------------------------------
def _log(verbose, msg):
    if verbose:
        sys.stdout.write('[scan_ingest] %s\n' % msg)
        sys.stdout.flush()


def _atomic_json(path, doc):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(doc, f, indent=1, sort_keys=True, default=_jsonable)
    os.replace(tmp, path)
    return path


def _jsonable(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def _read_json(path, what):
    if not os.path.exists(path):
        raise ScanIngestError(
            '%s artefact missing: %s. Run that stage first — the stages '
            'are independently runnable precisely so a later failure '
            'does not cost an earlier success.' % (what, path)
        )
    with open(path) as f:
        return json.load(f)


def _stage_path(out_dir, stage):
    n = STAGES.index(stage) + 1
    return os.path.join(out_dir, '%02d_%s.json' % (n, stage))


def _maybe_call(x):
    """pycolmap 4.x exposes some of these as properties and some as zero-arg methods
    (Image.cam_from_world and Reconstruction.num_reg_images are methods in 4.1.1, and
    were properties in earlier releases). Resolve either shape rather than pin a version."""
    return x() if callable(x) else x


def _quads_to_tris(faces):
    faces = np.asarray(faces)
    if faces.shape[1] == 3:
        return faces.astype(np.int64)
    q = faces.astype(np.int64)
    return np.concatenate([q[:, [0, 1, 2]], q[:, [0, 2, 3]]], axis=0)


def _stature_of(v):
    """Body height as the z-extent of the cage. Matches how mesh_skeletons._measure does
    it; this module never re-derives a stature from anything else."""
    v = np.asarray(v, np.float64)
    return float(v[:, 2].max() - v[:, 2].min())


# ----------------------------------------------------------------------------------
# defensive imports — this module must be importable and self-testable on a machine
# where the optional pieces are absent, and must say so rather than crash on import.
# ----------------------------------------------------------------------------------
def _try_pycolmap():
    try:
        import pycolmap

        return pycolmap
    except Exception as e:  # pragma: no cover
        raise ScanIngestError(
            'pycolmap is not importable (%s). Sparse SfM is not optional; there is no fallback.' % e
        ) from e


def _try_cv2():
    try:
        import cv2

        return cv2
    except Exception:
        return None


def _try_trimesh():
    try:
        import trimesh

        return trimesh
    except Exception:
        return None


def _try_mvconsist():
    """geom/mvconsist.py is being built in parallel with the contract
    measure(image_dir) -> dict. Import it defensively: if it is there we record its
    verdict alongside the SfM report, and if it is not, nothing blocks. We never gate on
    it, because a module we cannot see the thresholds of cannot own a refusal here."""
    try:
        from zyg_workflows.geom import mvconsist
    except Exception:
        return None
    fn = getattr(mvconsist, 'measure', None)
    return fn if callable(fn) else None


def _target_cage(name):
    """The fitted cage for `name`, rebuilt from its recorded recipe.

    Uses geom.anthro.gates.Subject.from_registry, which rebuilds from params.json and
    verifies the result against cage_vert_sha256 — the .glb on disk is triangulated on
    export (13,718 verts / 27,420 TRIANGLES, no armature), and the quad cage this module
    subdivides and shrinkwraps exists only in Python. Catmull-Clark on triangles gives bad
    topology, so reading the .glb instead is not an option."""
    from zyg_workflows.geom.anthro.gates.subject import Subject

    s = Subject.from_registry(name)
    return np.asarray(s.v, np.float64), np.asarray(s.faces)
