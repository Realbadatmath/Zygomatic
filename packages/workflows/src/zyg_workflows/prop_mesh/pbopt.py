#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pbopt.py — search the Pufferball's parameter space with an optimiser instead of a judge.

WHY. Three look-dev convergence runs (68 agents, ~10 hours of wall clock) explored roughly
FIFTEEN points in a parameter space of about fifty dimensions, because every evaluation was
a ~30-minute sixteen-view render scored by an LLM critic. The critic's severity rubric was
`major = "different creature" or "obviously CG-flat"`, so it certified "zero majors" on a
render the operator called far off at a glance, and the loop's exit condition was the
absence of majors — it was built to stop there.

A single canon view at 512 px / 24 samples on this machine takes ELEVEN SECONDS including
the whole scene build. Two views is fifteen. That is ~240 candidates an hour against the
old loop's 1.5 per hour, and it removes the judge from the inner loop entirely: the judge's
proper job is picking the objective and reading the result, not standing in for a gradient.

THREE MODES, and the order matters:

  probe   Render each declared parameter at its LOW and HIGH bound and check the image
          actually CHANGED. Any parameter that does not move the picture is reported as
          INERT and excluded. This is not paranoia — `prop_mesh/pufferball_look.py` is
          7.7k lines of cumulative agent code where later sections deliberately shadow
          earlier names, so a constant can easily be read by dead code only. The same
          project has already measured FLUX.1-schnell silently discarding guidance_scale
          and negative_prompt, and `--patch fill` turned out to be inert here for exactly
          this reason: the look's own camera() hook re-frames after place() sets fill.
          An optimiser that searches a dead dimension reports "this parameter does not
          matter", which is a false measurement that then gets believed.

  sweep   One parameter, N steps, loss tabulated. Reads the shape of a single lever —
          monotone, flat, or with an interior optimum — before trusting a search over it.

  cma     CMA-ES over every live parameter at once. Covariance-adapting, so it handles the
          couplings (eye size <-> fur coverage <-> plate extent flip-flopped across three
          rounds when three agents each owned one of them).

THE OBJECTIVE is prop_mesh/pbmetrics.py, which refuses any term that cannot separate the
anchor from a known-bad null. Every term is normalised by that null's distance, so a loss
of 1.0 means "as wrong as the v1 sphere" and 0.0 means "indistinguishable from the anchor".
DINO is deliberately absent: it scores 0.78 on the current render and 0.83 on a worse one.

USAGE
    python3 prop_mesh/pbopt.py probe
    python3 prop_mesh/pbopt.py sweep --param LOOK.CAM_FIT.margin --steps 7
    python3 prop_mesh/pbopt.py cma --budget 400
"""

import argparse
import copy
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pbmetrics as M  # noqa: E402
from zyg_workflows import paths
from zyg_workflows.bin import exe
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
DS = str(paths.ZYG_LORA_DATASETS / 'creatures' / 'd0e44ab002ad')
ANCHORS = os.path.join(DS, 'contact_sheet', 'anchors')

# The two operator-locked anchors, and nothing else. The 16 contact-sheet cells contradict
# each other by 58% on the creature's own aspect ratio (front cell h/w 0.82, back 1.29)
# because they are 2D rotations that invent what the source never saw; fitting the tail to
# cell_07 cost two rebuilds and a 40% error.
VIEWS = [
    ('front_full', os.path.join(ANCHORS, 'anchor_full.png')),
    ('side_left', os.path.join(ANCHORS, 'anchor_side.png')),
]

# ── the known-bad nulls that set each term's scale ───────────────────────────
# TWO, NOT ONE. Every term used to be scaled by the v1 sphere alone, and on 2026-08-29
# that cost a 400-evaluation run: ALL NINE terms ranked a BALD render better than the
# furry production render, so the search drove the coat off the creature and scored itself
# for it. A single null tells you how far you are from that null; it cannot tell you when
# you are BECOMING it. `fill` was the loudest case — the sphere's fill (0.6469) is closer
# to the anchor (0.6755) than production (0.6311), so the known-bad outscored the render
# and `fill` was normalised by 0.0286 into a term worth 1.55 that paid for baldness.
#
# sphere: the v1 pre-look-dev render. Right for shape, framing, colour.
# bald:   a bald-but-correctly-framed render. Right for the coat (pbmetrics.COAT_TERMS).
#         The sphere CANNOT serve: uniformly smooth, it has no bare PATCH relative to its
#         own texture and scores selectivity 1.0 on side_left against this null's 100.6.
#
# Both now live beside the anchors. They used to live in a session scratchpad under /tmp,
# i.e. every scale in this project was one tmpreaper away from silently changing.
NULLS = os.path.join(DS, 'contact_sheet', 'nulls')
NULL_DIR = os.path.join(NULLS, 'sphere')
BALD_NULL_DIR = os.path.join(NULLS, 'bald')

# The KNOWN-GOOD half of the direction test (pbmetrics.direction_report). The nulls say how
# far a render is from something wrong; they cannot say whether a term points the right
# way. Paired with BALD_NULL_DIR this is a pair whose answer is known by construction — the
# furry render is the better creature — and any coat term that scores the bald one as
# closer is refused for that view. See contact_sheet/refs/README.txt.
FURRY_REF_DIR = os.path.join(DS, 'contact_sheet', 'refs', 'furry')

SHEET = os.path.join(HERE, 'pufferball_sheet.py')

# No single term may contribute more than this to a view's mean. See score().
TERM_CAP = 2.0

# ── the coat gate ───────────────────────────────────────────────────────────
# COAT PRESENCE IS A VALIDITY CONDITION, NOT A QUALITY DIMENSION, and it is enforced the
# way this codebase enforces the others (pufferball.assert_parts_visible: a part that
# renders in zero views is a FAILURE, not a low score; mesh_control: an empty subject mask
# is SKIPPED, never written as a black map, because "a black control map is not a weak
# signal, it is a confident instruction").
#
# WHY A GATE AND NOT A TERM. On 2026-08-29 a 400-evaluation run drove the coat off the
# creature. Adding the `bald` term fixed the measurement — it ranks a bald render 1.000
# against a furry 0.497 — but did NOT fix the search, because `fill` alone pays MORE for
# baldness (-0.772) than `bald` charges for it (+0.464), and five other terms lean the
# same way. With framing held equal, only three of ten terms rank a bald render worse than
# a furry one. A scored term can always be outvoted by enough terms that cannot see the
# defect; a gate cannot.
#
# CALIBRATION, largest bare patch as a MULTIPLE OF THE ANCHOR'S own, per view. Measured:
# worst view over the six renders that were actually built and judged by eye:
#     FURRY  production 2.87 | framing_only 3.01 | shipped 3.01 | no_lock_no_under 3.19
#     BALD   as-searched 4.44 | lock-shape-reverted 4.75
# The gate trips on the WORST view, because the failure is REGIONAL: the flank goes bare
# while the crown stays furred, and a view that hides it says nothing about one that does
# not. Set at the geometric midpoint of the measured separation (sqrt(3.19*4.44) = 3.76),
# which leaves 15% of headroom under the furriest passing render and rejects the nearest
# bald one by 18%. A first cut at 3.4 left only 6% below and would have been tripped by a
# legitimate groom. Re-derive it if the anchors or the lighting change; it is a ratio to
# the ANCHOR's own bare patch per view, so it survives resolution and framing changes.
COAT_GATE = 3.75


class CoatGateFailure(RuntimeError):
    """A candidate whose coat is gone. Not scored — rejected.

    Subclasses RuntimeError deliberately: every caller in this file already treats a
    RuntimeError from score() as "maximally bad, keep searching" rather than as a crash,
    so a gate failure fails SAFE at call sites that predate the gate.
    """


# ═════════════════════════════════════════════════════════════════════════════
# the parameter space
# ═════════════════════════════════════════════════════════════════════════════
# (path, low, high, note). Paths address the --patch document:
#     fill                      canon body framing fill fraction
#     P.<key>                   a build parameter in pufferball.py's P
#     LOOK.<DICT>.<key>         a module constant in pufferball_look.py
#     LOOK.<DICT>.<key>[i]      one component of a tuple-valued constant
#
# Bounds are deliberately generous. A bound that is too tight looks exactly like a lever
# that does not work.
SPEC = [
    # ── framing. Measured 2026-08-28: front render covers 32.5% of frame against the
    # anchor's 48.9%, and sits 17.6% off the bottom against 0.3%. Nothing in three
    # look-dev runs measured framing at all.
    ('LOOK.CAM_FIT.margin', -0.02, 0.10, 'frame margin; smaller = creature bigger'),
    ('LOOK.CAM_FIT.pad', -0.06, 0.14, 'world-space pad added around the bbox'),
    # ── the comb. TUFT7.lean is the per-region lay-over, the one spatially-varying comb
    # the groom already has. Measured deviation-from-radial says the anchor's coat lies
    # over 41.4 deg on average against our 32.1, and the deficit is concentrated on the
    # crown (-17.9 deg) and the upper flanks (-18.8, -15.8), not the belly (+2.1).
    ('LOOK.TUFT7.lean.crown', 0.10, 2.20, 'crown lay-over'),
    ('LOOK.TUFT7.lean.wisp', 0.10, 2.40, 'wisp lay-over'),
    ('LOOK.TUFT7.lean.flank', 0.30, 4.50, 'flank lay-over'),
    ('LOOK.TUFT7.lean.back', 0.30, 4.50, 'back lay-over'),
    ('LOOK.TUFT7.lean.belly', 0.30, 4.50, 'belly lay-over'),
    # ── lock shape: needles vs shingles. run1 of the lock work read "as a sea urchin from
    # every view" at half-width 5-7 mm; run2 widened them. This asks how far that should
    # have gone, and it is measured rather than judged.
    # BOX PULLED IN 2026-08-29. The fit finished with THREE OF THESE FOUR PINNED at the
    # corner — w_per_L at its ceiling, spacing at its ceiling, thick at its floor — i.e.
    # "as wide, as sparse and as flat as you are allowed", which renders as loose petals
    # rather than fur. Seven of the twenty parameters pinned overall; a search that ends
    # in a corner is telling you the box is wrong, not that the corner is good. These
    # bounds now bracket the operator-approved values (0.16 / 0.012 / 0.0075 / 0.30)
    # rather than extending to the shape regime nobody had looked at.
    ('LOOK.TUFT7.w_per_L', 0.05, 0.26, 'lock half-width per unit length'),
    ('LOOK.TUFT7.w_max', 0.0045, 0.0200, 'lock half-width ceiling, m'),
    ('LOOK.TUFT7.spacing', 0.0060, 0.0120, 'lock root spacing, m'),
    ('LOOK.TUFT7.thick', 0.15, 0.75, 'lock cross-section thickness'),
    # ── the wind, the only global comb the groom has. gravity is INERT on static hair
    # (measured: effector_weights.gravity 0/1/3 gave identical paths); a WIND field does
    # bend the path at cache time.
    ('LOOK.WIND.strength', 0.00, 0.30, 'wind strength'),
    ('LOOK.WIND.dir[1]', -1.00, 1.00, 'wind Y (front-back)'),
    ('LOOK.WIND.dir[2]', -1.00, 0.40, 'wind Z (up-down)'),
    # ── undercoat: what closes the silhouette. Measured fill-inside-own-bbox 0.630 against
    # the anchor's 0.668 — the coat lets the backdrop through between locks.
    #
    # UNDERCOAT2, NOT UNDERCOAT. The probe run of 2026-08-28 reported BOTH
    # LOOK.UNDERCOAT.len and LOOK.UNDERCOAT.count as INERT at mean|d| ~1e-7, i.e. exactly
    # the render noise floor: a 5x change in undercoat length moved nothing. The cause is
    # the shadowing this file's docstring warns about. `UNDERCOAT` is defined at
    # pufferball_look.py:387 and read at :486 by the r2-era `_undercoat`, which a later
    # section superseded; the live code at :1841 reads `UNDERCOAT2`. Worse, UNDERCOAT2's
    # own definition line is also misleading — it says len 0.060 / count 5000, and three
    # later `.update()` calls at :2630, :3756 and :6361 leave it at 0.036 / 2500. Neither
    # number can be obtained by reading the file, which is why x0_from_spec() resolves
    # every starting value through Blender.
    # CEILING CUT 0.120 -> 0.042 ON A MEASURED FAILURE. The 2026-08-29 fit chose
    # 0.0763, which is LONGER THAN THE LOCKS IT SITS UNDER in 7 of the 8 lock
    # regions (shortest lock 0.045 m, cap; flank 0.060; belly/back 0.055), so the
    # undercoat swallowed the coat and the flank rendered BARE. Production is 0.036
    # = 0.80 of the shortest lock. The ceiling is now that same ratio (0.045*0.93),
    # and pufferball_look.assert_coat_stands_proud() enforces the real invariant at
    # build time, where it cannot be sidestepped by editing this line.
    # 0.0410, and it must stay BELOW pufferball_look's bar of shortest_lock *
    # COAT_CLEARANCE = 0.045 * 0.93 = 0.0418. A first cut at 0.0420 put the ceiling
    # 0.0002 ABOVE the bar, so the optimiser could still propose a vector the build
    # then refused — a crash mid-search instead of an unreachable region. The gap is
    # asserted by tests/test_pbmetrics.py::test_undercoat_ceiling_is_below_the_coat_bar.
    ('LOOK.UNDERCOAT2.len', 0.008, 0.041, 'undercoat length, m; MUST stay under the shortest lock'),
    ('LOOK.UNDERCOAT2.count', 1500, 15000, 'undercoat strand count'),
    ('LOOK.UNDERCOAT2.child', 8, 72, 'undercoat children per parent'),
    # ── micro-displacement on the face plate. Before 2026-08-28 the pipeline had NO true
    # displacement anywhere (zero hits for displacement_method / use_adaptive_subdivision /
    # ShaderNodeDisplacement / feature_set across 9,183 lines) and the plate's pebbling was
    # a 0.5 mm bump — shading only, so no silhouette break and no self-shadowing.
    # `height` at 0 is the search's way of voting the whole thing off, which is why `on`
    # itself is not a search dimension: a binary is a poor parameter for CMA-ES.
    ('LOOK.MICRO.height', 0.0000, 0.0040, 'true displacement height, m'),
    ('LOOK.MICRO.scale', 120.0, 600.0, 'pebble cell frequency'),
    ('LOOK.MICRO.bump_keep', 0.0, 1.0, 'how much of the old bump survives'),
]


def spec_names():
    return [s[0] for s in SPEC]


def _set_path(doc, path, value):
    """Write `value` into the patch document at a SPEC path."""
    idx = None
    if path.endswith(']'):
        path, _, i = path[:-1].partition('[')
        idx = int(i)
    parts = path.split('.')
    node = doc
    for k in parts[:-1]:
        node = node.setdefault(k, {})
    leaf = parts[-1]
    if idx is None:
        node[leaf] = value
    else:
        cur = node.get(leaf)
        if not isinstance(cur, list):
            cur = [None, None, None]
        while len(cur) <= idx:
            cur.append(0.0)
        cur[idx] = value
        node[leaf] = cur
    return doc


def patch_from_vector(x, spec=SPEC, base=None):
    """Vector -> patch document. Integer-valued parameters are rounded, because a strand
    COUNT of 4712.6 is not a thing and Blender would coerce it silently."""
    doc = copy.deepcopy(base) if base else {}
    for (path, lo, hi, _note), v in zip(spec, x):
        v = float(np.clip(v, lo, hi))
        if path.rsplit('.', 1)[-1] in ('count', 'variants', 'rings', 'child', 'levels', 'seed', 'oversample'):
            v = int(round(v))
        _set_path(doc, path, v)
    # A tuple-valued constant must be patched WHOLE (pufferball_sheet's _deep_update
    # replaces lists rather than merging them), so any dir[i] we touched has to carry its
    # untouched siblings too. WIND.dir's default is (0.0, 0.30, -1.0).
    d = doc.get('LOOK', {}).get('WIND', {}).get('dir')
    if isinstance(d, list):
        default = [0.0, 0.30, -1.0]
        doc['LOOK']['WIND']['dir'] = [default[i] if d[i] is None else d[i] for i in range(3)]
    return doc


_READ_X0 = r"""
import json, sys
sys.path.insert(0, %r)
import pufferball as PB
import pufferball_look as LK
P = dict(PB.P); P.update(getattr(LK, 'PARAMS', {}))
out = {}
for path in json.loads(%r):
    p, idx = path, None
    if p.endswith(']'):
        p, _, i = p[:-1].partition('['); idx = int(i)
    parts = p.split('.')
    if parts[0] == 'P':
        v = P[parts[1]]
    elif parts[0] == 'LOOK':
        v = getattr(LK, parts[1])
        for k in parts[2:]:
            v = v[k]
    elif parts[0] == 'fill':
        v = 0.66
    else:
        raise SystemExit('bad SPEC path %%r' %% path)
    out[path] = float(v[idx] if idx is not None else v)
print('PBOPT_X0 ' + json.dumps(out))
"""


def x0_from_spec(spec=SPEC, cache=True):
    """The CURRENT production values, read out of the live modules rather than retyped.

    Read THROUGH BLENDER, because pufferball.py and pufferball_look.py both import bpy at
    module scope and cannot be imported by a plain interpreter. That is worth the
    subprocess: the alternative is transcribing sixteen numbers out of a 7.7k-line file
    whose later sections deliberately shadow earlier names, so the value you can see is
    not necessarily the value that runs.

    Retyping numbers is exactly how the human-body work shipped a mesh that was not the
    one it had approved — a recipe hand-transcribed from a stale stdout, 29 of 32 values
    wrong, caught only by an adversarial review. The rule from that day was: bake
    programmatically, never retype. A search's starting point silently defines what "no
    change" means, so it earns the same rule.
    """
    paths = [s[0] for s in spec]
    cp = os.path.join(HERE, '.pbopt_x0.json')
    if cache and os.path.isfile(cp):
        try:
            with open(cp) as f:
                got = json.load(f)
            if all(p in got for p in paths) and got.get('_mtime') == os.path.getmtime(
                os.path.join(HERE, 'pufferball_look.py')
            ):
                return np.array([float(np.clip(got[p], s[1], s[2])) for p, s in zip(paths, spec)])
        except Exception as _exc:
            _zyg_log.debug('x0 checkpoint unusable, re-reading parameters through blender: %s', _exc)
    code = _READ_X0 % (HERE, json.dumps(paths))
    r = subprocess.run(
        [exe('blender'), '-b', '--python-expr', code], cwd=CREWS, capture_output=True, text=True, timeout=300
    )
    line = next((l for l in r.stdout.splitlines() if l.startswith('PBOPT_X0 ')), None)
    if line is None:
        raise SystemExit(
            'could not read current parameter values through blender:\n%s\n%s' % (r.stdout[-1500:], r.stderr[-800:])
        )
    got = json.loads(line[len('PBOPT_X0 ') :])
    got['_mtime'] = os.path.getmtime(os.path.join(HERE, 'pufferball_look.py'))
    with open(cp, 'w') as f:
        json.dump(got, f, indent=1)
    return np.array([float(np.clip(got[p], s[1], s[2])) for p, s in zip(paths, spec)])


# ═════════════════════════════════════════════════════════════════════════════
# render + score
# ═════════════════════════════════════════════════════════════════════════════
class Evaluator:
    """Render a candidate and score it. Caches the anchors and the null scales."""

    # Every render is a fresh Blender process that imports these from disk, so editing one
    # mid-search silently changes the objective under the optimiser: the baseline was
    # rendered by one version of the code and the candidates by another, and every
    # parameter then looks live because the picture moved for an unrelated reason. That
    # happened on this file's first probe run — a micro-displacement section was appended
    # to pufferball_look.py while the probe was ten minutes in, and the run had to be
    # discarded. It is cheap to notice and expensive to miss, so it is checked per render.
    SOURCES = ('pufferball.py', 'pufferball_look.py', 'pufferball_sheet.py', 'pbmetrics.py')

    def __init__(self, work, res=512, samples=24, views=None, verbose=False):
        self.work = work
        self.res = res
        self.samples = samples
        self.views = views or [v[0] for v in VIEWS]
        self.verbose = verbose
        os.makedirs(work, exist_ok=True)
        self.n_render = 0
        self.t_render = 0.0
        self._src = self._source_fingerprint()
        self._anchor = {}
        self._scale = {}
        for vid, apath in VIEWS:
            if vid not in self.views:
                continue
            self._anchor[vid] = M.measure(apath)
            nullp = os.path.join(NULL_DIR, vid + '_beauty.png')
            if not os.path.isfile(nullp):
                raise SystemExit('null render missing for %s: %s' % (vid, nullp))
            far = M.compare(self._anchor[vid], M.measure(nullp))
            baldp = os.path.join(BALD_NULL_DIR, vid + '_beauty.png')
            far_bald = M.compare(self._anchor[vid], M.measure(baldp)) if os.path.isfile(baldp) else None
            furryp = os.path.join(FURRY_REF_DIR, vid + '_beauty.png')
            direction = None
            if os.path.isfile(baldp) and os.path.isfile(furryp):
                direction = M.direction_report(self._anchor[vid], M.measure(baldp), M.measure(furryp))
            self._scale[vid] = M.usable_terms(
                {'self': self._self_floor(apath), 'far': far, 'far_bald': far_bald, 'direction': direction}
            )
            if direction is not None:
                failed = sorted(t for t in M.COAT_TERMS if not direction.get(t, {}).get('passes', True))
                if failed and self.verbose:
                    _zyg_log.info('[%s] coat terms REFUSED on the direction test: %s' % (vid, ', '.join(failed)))
            if self.verbose:
                _zyg_log.info('[%s] usable terms: %s' % (vid, ', '.join(sorted(self._scale[vid]))))

    @staticmethod
    def _self_floor(apath, n=3):
        a = M.measure(apath)
        rgb = M.load_rgb(apath)
        rows = [M.compare(a, M.measure_rgb(M.perturb(rgb, seed=s))) for s in range(n)]
        return {t: float(np.nanmean([r[t] for r in rows])) for t in M.TERMS}

    @classmethod
    def _source_fingerprint(cls):
        h = hashlib.sha256()
        for name in cls.SOURCES:
            p = os.path.join(HERE, name)
            h.update(name.encode())
            if not os.path.isfile(p) and os.path.isdir(p[:-3]):
                # pufferball.py and pbmetrics.py became packages in the 2026-10 modularization:
                # fingerprint the package as its modules, sorted and concatenated
                d = p[:-3]
                for n in sorted(os.listdir(d)):
                    if n.endswith('.py'):
                        with open(os.path.join(d, n), 'rb') as f:
                            h.update(f.read())
                continue
            with open(p, 'rb') as f:
                h.update(f.read())
        return h.hexdigest()[:16]

    def _check_sources(self):
        now = self._source_fingerprint()
        if now != self._src:
            raise SystemExit(
                'the build sources changed mid-search (%s -> %s).\n'
                'Every render is a fresh process that reads them from disk, so the\n'
                'baseline and the candidates were made by different code and the results\n'
                'so far are not comparable. Restart the search.' % (self._src, now)
            )

    # ONE PROCESS PER VIEW. A view must be a function of the parameters, not of the views
    # rendered before it, and MEASURED 2026-09-01 it was not.
    #
    # Rendering is otherwise perfectly deterministic — two runs of the same configuration
    # are BIT-IDENTICAL. But the same parameters give a different side_left depending on
    # how many views preceded it in the process, and only on HOW MANY: side_left with one
    # prior view is bit-identical whether the run rendered 2 views or 3 (mean|d| 0.000000),
    # while `back` with two priors drifts further than side_left with one. The drift is
    # every fur strand on the body and tail, and the mechanism is the look's per-view
    # camera hook, which rebuilds the pupil and glint meshes (_gaze9 -> _replace_mesh ->
    # bpy.data.meshes.remove) and forces a depsgraph rebuild; the hair child distribution
    # follows the resulting evaluation order. Pinning every particle system's seed per view
    # was tried first and changed NOTHING — the post-fix renders were byte-identical, so
    # the seed was never the cause.
    #
    # WHY IT MATTERED: the search rendered 2 views and production renders 16, where
    # side_left is 4th. Measured at the search's own 512px/24-sample settings, production
    # and the search disagree by 0.0077 on the side_left view loss and 0.0038 on the
    # composite, so the search was not minimising the number production reports. (Both are
    # smaller than the 0.022 this file previously recorded, and smaller at 1024/96 still:
    # 0.0016 / 0.0008. The defect is worst exactly where the search lived — low resolution,
    # low samples — and nearly invisible at the resolution it was scored at.)
    #
    # The fix is structural rather than a hunt through a 9k-line look file whose numbers
    # are the spec: give every view its own process, so every view has zero prior views and
    # equals the render it would get alone. Costs one scene build per view.
    PER_VIEW_PROCESS = True

    def render(self, patch, tag):
        self._check_sources()
        out = os.path.join(self.work, tag)
        pj = os.path.join(self.work, tag + '.json')
        os.makedirs(out, exist_ok=True)
        with open(pj, 'w') as f:
            json.dump(patch, f)
        batches = [[v] for v in self.views] if self.PER_VIEW_PROCESS else [list(self.views)]
        t = time.time()
        last = None
        for views in batches:
            cmd = [
                exe('blender'),
                '-b',
                '-P',
                SHEET,
                '--',
                '--out',
                out,
                '--look',
                'canon',
                '--views',
                ','.join(views),
                '--samples',
                str(self.samples),
                '--w',
                str(self.res),
                '--h',
                str(self.res),
                '--patch',
                pj,
            ]
            last = subprocess.run(cmd, cwd=CREWS, capture_output=True, text=True, timeout=900)
            self.n_render += 1
        self.t_render += time.time() - t
        made = {v: os.path.join(out, 'beauty', v + '.png') for v in self.views}
        missing = [v for v, p in made.items() if not os.path.isfile(p)]
        if missing:
            tail = '\n'.join((last.stdout if last else '').strip().splitlines()[-12:])
            raise RuntimeError(
                'render produced no image for %s\n%s\n%s'
                % (missing, (last.stderr if last else '').strip()[-800:], tail)
            )
        return made

    def score(self, patch, tag):
        """Composite loss. 0 = indistinguishable from the anchors, 1 = as wrong as v1.

        Per-view means, then the mean across views, so one view cannot be sacrificed to
        buy the other — the side view is already the weaker of the two (bbox 0.678 of
        frame against the anchor's 0.833) and an unweighted sum would let a search make
        it worse.
        """
        made = self.render(patch, tag)
        per_view, detail = [], {}
        for vid, p in made.items():
            m = M.measure(p)
            # THE COAT GATE, before any scoring. See COAT_GATE above.
            ab = self._anchor[vid].get('bald')
            cb = m.get('bald')
            if ab and np.isfinite(ab) and np.isfinite(cb) and ab > 1e-9:
                ratio = cb / ab
                if ratio > COAT_GATE:
                    raise CoatGateFailure(
                        '%s: largest bare patch is %.1fx the anchor (%.4f vs %.4f), over '
                        'the %.1fx gate — the coat is gone. This is the 2026-08-29 '
                        'bald-flank failure; six of ten scored terms PREFER it, so it is '
                        'gated rather than scored.' % (vid, ratio, cb, ab, COAT_GATE)
                    )
            d = M.compare(self._anchor[vid], m)
            sc = self._scale[vid]
            # CAPPED. Run 1 was dominated by `lock_k`, which reached 4.66 against a
            # per-view mean of 1.31 because its null denominator was accidentally tiny
            # (the v1 sphere's lock wavenumber is 19.7 against the anchor's 20.1 — a
            # smooth ball has no locks, so its spectrum is noise that happened to land in
            # the right place). Raising the selectivity bar to 10 removes that particular
            # term, but the mechanism is general: any term whose null is nearly right gets
            # amplified without bound. A cap of TERM_CAP means "already as wrong as it is
            # worth measuring" and stops one term from owning the search.
            terms = {t: min(d[t] / s, TERM_CAP) for t, s in sc.items() if t in d and np.isfinite(d[t]) and s > 0}
            if not terms:
                raise RuntimeError('no usable terms scored for %s' % vid)
            per_view.append(float(np.mean(list(terms.values()))))
            detail[vid] = terms
        return float(np.mean(per_view)), detail, made


def _hash(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]


def _img_delta(a_made, b_made):
    """Mean absolute pixel difference between two {view: path} render sets, in [0,1].

    The unit the probe's "did this parameter do anything" test is expressed in. Averaged
    over views so one unchanged view cannot hide a changed one; a max would be swayed by a
    single stray sample."""
    ds = []
    for v, pa in a_made.items():
        pb = b_made.get(v)
        if not pb:
            continue
        ds.append(float(np.abs(M.load_rgb(pa) - M.load_rgb(pb)).mean()))
    return float(np.mean(ds)) if ds else 0.0


# ═════════════════════════════════════════════════════════════════════════════
# CMA-ES — compact, standard (Hansen), no new dependency
# ═════════════════════════════════════════════════════════════════════════════
class CMA:
    """(mu/mu_w, lambda)-CMA-ES on the unit cube; bounds handled by the caller's clipping.

    Written out rather than pulled in because the only dependency this module has is numpy
    and scipy, and because a search whose internals are opaque is exactly what got us here.
    """

    def __init__(self, x0, sigma0=0.25, popsize=None, seed=0):
        self.n = n = len(x0)
        self.mean = np.array(x0, dtype=float)
        self.sigma = float(sigma0)
        self.lam = popsize or (4 + int(3 * math.log(n)))
        self.mu = self.lam // 2
        w = math.log(self.mu + 0.5) - np.log(np.arange(1, self.mu + 1))
        self.w = w / w.sum()
        self.mueff = 1.0 / (self.w**2).sum()
        self.cc = (4 + self.mueff / n) / (n + 4 + 2 * self.mueff / n)
        self.cs = (self.mueff + 2) / (n + self.mueff + 5)
        self.c1 = 2 / ((n + 1.3) ** 2 + self.mueff)
        self.cmu = min(1 - self.c1, 2 * (self.mueff - 2 + 1 / self.mueff) / ((n + 2) ** 2 + self.mueff))
        self.damps = 1 + 2 * max(0, math.sqrt((self.mueff - 1) / (n + 1)) - 1) + self.cs
        self.pc = np.zeros(n)
        self.ps = np.zeros(n)
        self.B = np.eye(n)
        self.D = np.ones(n)
        self.C = np.eye(n)
        self.chiN = math.sqrt(n) * (1 - 1 / (4 * n) + 1 / (21 * n**2))
        self.rng = np.random.default_rng(seed)
        self.gen = 0

    def ask(self):
        self.z = self.rng.standard_normal((self.lam, self.n))
        self.y = self.z @ (self.B * self.D).T
        return self.mean + self.sigma * self.y

    def tell(self, xs, fs):
        order = np.argsort(fs)
        xs, ys = np.array(xs)[order], np.array(self.y)[order]
        old = self.mean.copy()
        self.mean = old + self.sigma * (self.w @ ys[: self.mu])
        Cinv_sqrt = self.B @ np.diag(1.0 / self.D) @ self.B.T
        self.ps = (1 - self.cs) * self.ps + math.sqrt(self.cs * (2 - self.cs) * self.mueff) * (
            Cinv_sqrt @ (self.mean - old) / self.sigma
        )
        self.gen += 1
        hsig = np.linalg.norm(self.ps) / math.sqrt(1 - (1 - self.cs) ** (2 * self.gen)) / self.chiN < 1.4 + 2 / (
            self.n + 1
        )
        self.pc = (1 - self.cc) * self.pc + hsig * math.sqrt(self.cc * (2 - self.cc) * self.mueff) * (
            self.mean - old
        ) / self.sigma
        artmp = ys[: self.mu]
        self.C = (
            (1 - self.c1 - self.cmu) * self.C
            + self.c1 * (np.outer(self.pc, self.pc) + (not hsig) * self.cc * (2 - self.cc) * self.C)
            + self.cmu * (artmp.T * self.w) @ artmp
        )
        self.sigma *= math.exp((self.cs / self.damps) * (np.linalg.norm(self.ps) / self.chiN - 1))
        self.C = np.triu(self.C) + np.triu(self.C, 1).T
        d, self.B = np.linalg.eigh(self.C)
        self.D = np.sqrt(np.maximum(d, 1e-20))


# ═════════════════════════════════════════════════════════════════════════════
# modes
# ═════════════════════════════════════════════════════════════════════════════
def mode_probe(ev, args):
    """Does each declared lever actually move the picture?"""
    x0 = x0_from_spec()
    base_patch = patch_from_vector(x0)
    base = ev.render(base_patch, 'probe_base')
    base_loss, base_detail, base2 = ev.score(base_patch, 'probe_base2')
    # DETERMINISM FIRST. The whole probe rests on "the bytes changed, so the parameter is
    # read". If two renders of the SAME patch already differ, every parameter looks live
    # and the probe certifies a dead lever as working — a false measurement dressed up as
    # evidence, which is the failure this file exists to prevent. So the identical render
    # is done twice and checked before anything else runs.
    noise_px = max(_img_delta(base, base2), 1e-9)
    base_loss2, _, _ = ev.score(base_patch, 'probe_base3')
    noise_loss = abs(base_loss2 - base_loss)
    if noise_px > 1e-3:
        raise SystemExit(
            'renders are not reproducible: two renders of the SAME patch differ by '
            'mean|d|=%.5f.\nThe probe cannot separate a live parameter from render noise '
            'until that is fixed.' % noise_px
        )
    _zyg_log.info('render noise floor: mean|d| %.2e over identical patches, dloss %.5f' % (noise_px, noise_loss))
    _zyg_log.info(
        'base loss %.4f   per-view %s'
        % (base_loss, {v: round(float(np.mean(list(t.values()))), 4) for v, t in base_detail.items()})
    )
    _zyg_log.info(
        'base terms  %s' % {v: {k: round(x, 2) for k, x in sorted(t.items())} for v, t in base_detail.items()}
    )
    # LIVE means "moved the picture further than the renderer's own noise", not "changed a
    # byte". Byte equality was the first test here and it failed on everything: two renders
    # of one patch differ by a single quantisation step on a few pixels, so every parameter
    # looked live and the probe would have certified dead levers as working.
    px_floor = max(20.0 * noise_px, 2e-5)
    loss_floor = max(5.0 * noise_loss, 0.002)
    _zyg_log.info('\n%-28s %9s %9s %10s  %s' % ('parameter', 'dloss_lo', 'dloss_hi', 'mean|d|', 'verdict'))
    _zyg_log.info('-' * 88)
    live, inert = [], []
    for i, (path, lo, hi, note) in enumerate(SPEC):
        ds, moves = [], []
        for end, val in (('lo', lo), ('hi', hi)):
            x = x0.copy()
            x[i] = val
            try:
                loss, _, made = ev.score(patch_from_vector(x), 'probe_%d_%s' % (i, end))
            except RuntimeError as exc:
                _zyg_log.info('%-28s  RENDER FAILED at %s: %s' % (path, end, str(exc)[:80]))
                ds.append(float('nan'))
                moves.append(0.0)
                continue
            ds.append(loss - base_loss)
            moves.append(_img_delta(base, made))
        mv = max(moves) if moves else 0.0
        dl = max((abs(d) for d in ds if np.isfinite(d)), default=0.0)
        alive = (mv > px_floor) or (dl > loss_floor)
        verdict = 'live' if alive else 'INERT — excluded'
        (live if alive else inert).append(path)
        _zyg_log.info(
            '%-28s %9.4f %9.4f %10.2e  %s   (%s)'
            % (path, ds[0] if ds else float('nan'), ds[1] if len(ds) > 1 else float('nan'), mv, verdict, note)
        )
    _zyg_log.info('-' * 78)
    _zyg_log.info('%d live, %d inert' % (len(live), len(inert)))
    if inert:
        _zyg_log.info('INERT: %s' % ', '.join(inert))
        _zyg_log.info('An inert parameter is not a parameter that does not matter — it is a')
        _zyg_log.info('parameter the pipeline never reads. Find the code that shadows it.')
    out = os.path.join(ev.work, 'probe.json')
    with open(out, 'w') as f:
        json.dump({'base_loss': base_loss, 'live': live, 'inert': inert}, f, indent=1)
    _zyg_log.info('-> %s   (%d renders, %.1f s each)' % (out, ev.n_render, ev.t_render / max(ev.n_render, 1)))
    return 0


def mode_sweep(ev, args):
    x0 = x0_from_spec()
    names = spec_names()
    if args.param not in names:
        raise SystemExit('unknown --param %r; known: %s' % (args.param, ', '.join(names)))
    i = names.index(args.param)
    path, lo, hi, note = SPEC[i]
    _zyg_log.info('sweep %s  [%g, %g]  %s\n' % (path, lo, hi, note))
    _zyg_log.info('%12s %9s  %s' % ('value', 'loss', 'per-term'))
    rows = []
    for v in np.linspace(lo, hi, args.steps):
        x = x0.copy()
        x[i] = v
        loss, detail, _ = ev.score(patch_from_vector(x), 'sweep_%s_%g' % (path.replace('.', '_'), v))
        first = detail[list(detail)[0]]
        _zyg_log.info(
            '%12.5f %9.4f  %s' % (v, loss, ' '.join('%s %.2f' % (k, val) for k, val in sorted(first.items())))
        )
        rows.append({'value': float(v), 'loss': loss, 'detail': detail})
    out = os.path.join(ev.work, 'sweep_%s.json' % path.replace('.', '_'))
    with open(out, 'w') as f:
        json.dump({'param': path, 'rows': rows}, f, indent=1)
    best = min(rows, key=lambda r: r['loss'])
    _zyg_log.info('\nbest %.5f at loss %.4f (start %.5f)  -> %s' % (best['value'], best['loss'], x0[i], out))
    return 0


def mode_cma(ev, args):
    x0 = x0_from_spec()
    if args.x0:
        # Warm start from a previous run's winner. The objective may have changed since,
        # so this is a starting POINT, not a starting score — the first generation
        # re-evaluates it under the current terms.
        with open(args.x0) as f:
            prev = json.load(f)['best_vector']
        names = spec_names()
        miss = [n for n in names if n not in prev]
        x0 = np.array([float(prev.get(n, x0[i])) for i, n in enumerate(names)])
        _zyg_log.info(
            'warm start from %s%s'
            % (
                args.x0,
                (' (%d new parameter(s) kept at current value: %s)' % (len(miss), ', '.join(miss))) if miss else '',
            )
        )
    lo = np.array([s[1] for s in SPEC], float)
    hi = np.array([s[2] for s in SPEC], float)
    span = hi - lo
    live = None
    probe = os.path.join(ev.work, 'probe.json')
    if os.path.isfile(probe):
        with open(probe) as f:
            live = set(json.load(f)['live'])
        _zyg_log.info('probe.json: optimising %d of %d parameters' % (len(live), len(SPEC)))
    idx = [i for i, s in enumerate(SPEC) if live is None or s[0] in live]
    if not idx:
        raise SystemExit('probe found no live parameters')

    def expand(u):
        x = x0.copy()
        x[idx] = lo[idx] + np.clip(u, 0.0, 1.0) * span[idx]
        return x

    u0 = (x0[idx] - lo[idx]) / span[idx]
    es = CMA(u0, sigma0=args.sigma, popsize=args.popsize, seed=args.seed)
    best = (float('inf'), None)
    hist = []
    t0 = time.time()
    n = 0
    while n < args.budget:
        us = es.ask()
        fs = []
        n_gated = globals().get('_n_gated_total', 0)
        for j, u in enumerate(us):
            if n >= args.budget:
                fs.append(best[0] if best[1] is not None else 1e3)
                continue
            x = expand(u)
            try:
                loss, detail, _ = ev.score(patch_from_vector(x), 'cma_%03d_%02d' % (es.gen, j))
            except CoatGateFailure as exc:
                # Rejected, not scored. The whole point of the gate is that no combination
                # of the other terms can buy this back.
                _zyg_log.info('   gen %3d cand %2d COAT GATE (%s)' % (es.gen, j, str(exc)[:90]))
                loss, n_gated = 10.0, n_gated + 1
            except RuntimeError as exc:
                # A candidate whose parameters crash the build is not a zero-loss point and
                # must not be silently dropped either: it is scored as maximally bad so the
                # search learns to avoid that region.
                _zyg_log.info('   gen %3d cand %2d RENDER FAILED (%s)' % (es.gen, j, str(exc)[:70]))
                loss = 10.0
            fs.append(loss)
            n += 1
            if loss < best[0]:
                best = (loss, x.copy())
                _zyg_log.info(
                    '   new best %.4f at eval %d  %s'
                    % (loss, n, ' '.join('%s=%.4g' % (SPEC[i][0].split('.')[-1], x[i]) for i in idx))
                )
        es.tell(us, fs)
        globals()['_n_gated_total'] = n_gated
        hist.append(
            {
                'gen': es.gen,
                'best': float(np.min(fs)),
                'mean': float(np.mean(fs)),
                'sigma': float(es.sigma),
                'evals': n,
                'gated_total': n_gated,
            }
        )
        _zyg_log.info(
            'gen %3d  best %.4f  mean %.4f  sigma %.3f  evals %d  %.1f min elapsed'
            % (es.gen, np.min(fs), np.mean(fs), es.sigma, n, (time.time() - t0) / 60.0)
        )
    out = os.path.join(ev.work, 'cma_result.json')
    with open(out, 'w') as f:
        json.dump(
            {
                'best_loss': best[0],
                'best_patch': patch_from_vector(best[1]) if best[1] is not None else None,
                'best_vector': dict(zip(spec_names(), map(float, best[1]))) if best[1] is not None else None,
                'start_vector': dict(zip(spec_names(), map(float, x0))),
                'history': hist,
                'evals': n,
                'seconds_per_render': ev.t_render / max(ev.n_render, 1),
            },
            f,
            indent=1,
        )
    _zyg_log.info('\nbest loss %.4f after %d evals -> %s' % (best[0], n, out))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('mode', choices=['probe', 'sweep', 'cma'])
    ap.add_argument('--work', default=os.environ.get('PBOPT_WORK') or os.path.join(tempfile.gettempdir(), 'pbopt'))
    ap.add_argument('--res', type=int, default=512)
    ap.add_argument('--samples', type=int, default=24)
    ap.add_argument('--views', default='front_full,side_left')
    ap.add_argument('--param', default=None)
    ap.add_argument('--steps', type=int, default=7)
    ap.add_argument('--budget', type=int, default=300)
    ap.add_argument('--popsize', type=int, default=None)
    ap.add_argument('--sigma', type=float, default=0.22)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--x0', default=None, help='cma_result.json to warm-start from (uses its best_vector)')
    a = ap.parse_args()
    ev = Evaluator(a.work, res=a.res, samples=a.samples, views=[v for v in a.views.split(',') if v], verbose=True)
    return {'probe': mode_probe, 'sweep': mode_sweep, 'cma': mode_cma}[a.mode](ev, a)


if __name__ == '__main__':
    sys.exit(main())
