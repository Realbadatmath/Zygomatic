# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""identity_bank.py — longitudinal face/subject identity bank (2026-07-30).

Why this exists
---------------
Two verified failure modes had no detector:

  1. Character identity drifts ACROSS context windows inside a single render while the
     whole-image CLIP gate (0.80) happily passes — CLIP scores "a bearded man in a
     brown coat at a table", not "THIS man".
  2. Slow cross-episode ratchet drift after a retrain / restyle. The per-render gate is
     memoryless, so a character can walk away from its canon a few percent per episode
     and never trip anything.

This module gives every character a PERSISTENT embedding bank keyed by
(char_id, style_profile, backend), so a new render is scored against the character's own
historical distribution — cosine vs the bank centroid AND a z-score vs the bank spread.

License posture (STRICT commercial bar)
---------------------------------------
  * facenet-pytorch — MIT (code + converted weights). Installed with --no-deps so it
    cannot downgrade the venv torch (its metadata pins torch<2.3).
  * DINOv2 ViT-S/14 (`facebook/dinov2-small`) — Apache-2.0 (DINOv2 was relicensed from
    CC-BY-NC in 2024). Do NOT swap in any *-NC checkpoint.
  * This module exists to retire the NON-COMMERCIAL insightface dependency in the
    identity QC path. Nothing here imports insightface.
  * CAVEAT, flagged not hidden: the facenet `vggface2` weights were trained on the
    VGGFace2 dataset, whose *dataset* terms are research-oriented even though the
    facenet-pytorch code+weights ship MIT. If legal wants zero dataset-provenance risk,
    set ZYG_IDENTITY_BACKEND=dinov2 — the DINOv2 path is fully Apache-2.0 (LVD-142M) and
    is measurably discriminative on our stylized cast (see MEASURED, below).

MEASURED on the real Second Ledger cast (2026-07-30, CPU, scene20_v7/pasted17.mp4)
---------------------------------------------------------------------------------
Cast: Cornelis 0015c8a3f2e3 (box 0.10,0.02,0.45,0.50) and Abel c3345deb5bde
(box 0.60,0.02,0.96,0.56), windows sampled at 2/6/9/13/16 s.

  MTCNN detection rate on arcane-stylized faces: 14/14 = 100% (both canon portraits,
  both canon face crops, all ten per-window head crops), det_prob 0.87-1.00.
  => Face-ID nets do NOT fail on this style. `facenet` is the PRIMARY backend.

  facenet (bank = canon portrait + canon face crop):
      genuine  cos 0.468 - 0.586  (mean 0.534)
      impostor cos -0.029 - 0.250 (mean 0.087)     margin  +0.218
      canon-Cornelis vs canon-Abel = 0.292
  dinov2 region (same banks, whole head box):
      genuine  cos 0.414 - 0.591  (mean 0.488)
      impostor cos  0.273 - 0.367 (mean 0.325)     margin  +0.048
      canon-Cornelis vs canon-Abel = 0.567  <-- same style + same framing dominates

  => DINOv2-on-a-head-box is largely a STYLE/COMPOSITION descriptor, not an identity
     descriptor: two different people in the same arcane style score 0.57. Keep it as
     the no-face FALLBACK and treat a dinov2 fail as "flag for review", never as a hard
     identity verdict. Floors: facenet 0.35 (0.12 under the worst genuine, 0.10 over the
     best impostor); dinov2 0.50 (calibrated against a render-domain bank).

BENCH CLIP — the per-frame clip instrument (2026-09-02, scripts/identity_clip_bench.py)
--------------------------------------------------------------------------------------
The old check_clip sampled five fixed times through a STATIC box, had its spread
alarm calibrated on ONE render, and had zero callers. It was replaced by a
per-frame instrument and BENCHED BEFORE BEING TRUSTED. 12 arms, 419 scored frames,
facenet backend, banks of 3 (canon portrait + canon face crop + anchor crop):

  arm                                          n   cos_min  p10    mean   spread
  ceiling/Abel      (canon still x341 @24fps) 15   0.9327  0.933  0.9355  0.012
  ceiling/Cornelis                            15   0.9465  0.947  0.9471  0.003
  true/Abel         shores_v27_leanfix        34   0.7287  0.745  0.7666  0.092
  true/Cornelis     cornelis_day1             26   0.4980  0.500  0.5240  0.074
  true/Cornelis-left   20s_pipe_smoke (L col) 55   0.4775  0.523  0.5879  0.190
  true/Abel-right      20s_pipe_smoke (R col) 50   0.3943  0.503  0.5667  0.299
  shuffle/Abel      same frames, random order 34   0.7387  0.743  0.7656  0.073
  shuffle/Cornelis                            25   0.5072  0.512  0.5319  0.079
  impostor/Abel-bank on Cornelis clip         26   0.0276  0.030  0.0740  0.163
  impostor/Cornelis-bank on Abel clip         34   0.2917  0.315  0.3404  0.085
  impostor/Cornelis-bank on Abel column       50  -0.0581  0.019  0.1458  0.350
  impostor/Abel-bank on Cornelis column       55   0.1065  0.128  0.1747  0.173

  * IMPOSTORS ARE SEPARATED. Worst case is Cornelis' bank on Abel's clip: arm mean
    0.340 against a worst genuine arm mean of 0.524 — a gap of 0.184 at the arm
    level, 0.185 at p10. The two SAME-CLIP impostor arms (the other character's
    column of the very same two-hander: identical style, grade, framing and render)
    score 0.146 and 0.175, i.e. the hardest impostor available is not the closest
    one. The metric is reading the face, not the render.
  * BUT THE PER-FRAME GAP IS RAZOR THIN: worst genuine frame 0.3943, best impostor
    frame 0.3763 — an overlap-free window only 0.018 wide. So no single frame may
    decide a clip; the verdict is `pass_frac` over found frames (CLIP_PASS_FRAC).
  * THE TWO CHARACTERS ARE NOT EQUALLY SAFE. Abel's true clip sits at 0.73-0.82,
    Cornelis' at 0.50-0.57 — both pass, but Cornelis has ~0.08 of headroom over
    the 0.42 floor and Abel has ~0.31. Whatever trips first will be Cornelis, and
    it will not necessarily mean his identity moved: it may mean his bank of three
    canon images is a worse centroid than Abel's. Enrol more before tightening.
  * SHUFFLE says the summary statistics carry NO temporal information: the shuffled
    frame SET scores 0.7656 vs 0.7666 (Abel) and 0.5319 vs 0.5240 (Cornelis). This
    is the expected result for an order-blind metric and it is the reason `spread`
    is informational only — it is dispersion, never continuity.
  * CEILING is IN-BANK (the canon portrait is one of the three enrolled images), so
    0.93-0.95 is the top of the achievable scale plus the cost of an h264 round
    trip, not an independent genuine sample.
  * LEDGER: true/Abel found 34, not_found 20, not_detectable 5 over a 59 s scene.
    The 20 not_found frames are harbour shots with nobody in them — the old
    instrument had no state for those and its five fixed times only ever landed in
    the one shot where Abel is on screen.
  * LEGACY comparison on the same clip (5 times, static box (0.45,0,1,0.6)):
    mean 0.7736 over 5 windows, verdict "ok". Not wrong — blind. It sampled 5
    moments of a 1411-frame clip and all 5 fell inside a single shot.

Usage
-----
    from zyg_workflows import identity_bank as ib
    ib.enroll('0015c8a3f2e3', 'arcane', [canon_portrait, canon_face_crop, anchor_crop])
    r = ib.check('0015c8a3f2e3', 'arcane', frame_png, box_frac=(0.10, 0.02, 0.45, 0.50))
    # -> {'ok': True, 'cosine': 0.71, 'z': 0.3, 'n_bank': 3, 'backend': 'facenet', ...}
    ib.drift_report('0015c8a3f2e3')     # time-series for the nightly dashboard

Every public call is fail-safe: on any internal error it returns
{'ok': None, 'error': '...'} (ok=None means UNKNOWN, never a silent pass and never an
exception into the generation path).
"""

# ruff: noqa: E402,F401
import os
import time

from zyg_workflows import pgdb
import logging as _zyg_logging
from zyg_workflows.bin import exe

from .embedding import (  # noqa: F401
    DEFAULT_BACKEND,
    DEVICE,
    RATCHET_DELTA,
    RATCHET_MIN_RENDERS,
    SPREAD_ALARM,
    Z_FLOOR,
    Z_MIN_BANK,
    Z_MIN_STD,
    _DINO,
    _DINOV2_DIM,
    _FACENET_DIM,
    _FLOORS,
    _HERE,
    _HF_REVISION,
    _IMNET_MEAN,
    _IMNET_STD,
    _MTCNN,
    _RESNET,
    _RUNTIME,
    _blob,
    _get_dino,
    _get_facenet,
    _l2,
    _ledger_fallback,
    _ledger_gate,
    _log,
    _np,
    _open_crop,
    _run_id,
    _unblob,
    _zyg_log,
    embed_auto,
    embed_face,
    embed_region,
)

from .gate import (  # noqa: F401
    _bank,
    _pick_backend,
    _record_check,
    bank_backends,
    bank_stats,
    check,
    enroll,
)

from .clip import (  # noqa: F401
    CLIP_FLOORS,
    CLIP_FLOOR_BENCHED,
    CLIP_MAX_FRAMES,
    CLIP_MIN_FOUND,
    CLIP_MODE,
    CLIP_PASS_FRAC,
    CLIP_SPREAD_ALARM,
    CLIP_STRIDE,
    FACE_BOX_MARGIN,
    LEDGER_STATES,
    _check_clip_legacy,
    _clamp01,
    _explode,
    _pct,
    _probe_fps,
    check_clip,
    enabled,
    track_face_box,
)

from .runs import (  # noqa: F401
    _RUN_CHAR_KEYS,
    _bankable,
    drift_report,
    enroll_from_canon,
    purge,
    run_char_ids,
    score_run,
)

# --- monkeypatch bridge -------------------------------------------------------
# `identity_bank` was one module: rebinding an attribute on it —
# monkeypatch.setattr(ib, 'DEVICE', 'cuda') — changed the value every function
# saw. Across modules a plain setattr would only touch the package, so the
# package writes a rebinding through to every section module that holds the name.
import sys as _sys
from types import ModuleType as _ModuleType

_SECTIONS = tuple(_sys.modules[f'{__name__}.{_n}'] for _n in ('embedding', 'gate', 'clip', 'runs'))


class _IdentityBankModule(_ModuleType):
    def __setattr__(self, name, value):
        _ModuleType.__setattr__(self, name, value)
        for _m in self.__dict__.get('_SECTIONS') or ():
            if name in _m.__dict__:
                _m.__dict__[name] = value

    def __delattr__(self, name):
        _ModuleType.__delattr__(self, name)
        for _m in self.__dict__.get('_SECTIONS') or ():
            _m.__dict__.pop(name, None)


_sys.modules[__name__].__class__ = _IdentityBankModule
