#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
qc_contract.py — the authority layer for pipeline QC.

Everything here exists because of a defect that already happened on this box.
Each rule cites the incident that bought it; do not relax one without reading it.

  1. THREE VERDICTS, NOT TWO.  A gate that could not look must not report green.
     pipeline_debug.py:520 recorded a skipped track check as {'ok': True} and
     finish() counted {'ok': None} as a FAILURE — the two opposite halves of the
     same missing concept. An ink PASS meant 0/7 recall, not clean.
  2. COVERAGE IS PART OF THE VERDICT.  'eyelid-aperture' was an undetected defect
     class for six renders while every gate measured face flow_median — which is
     ANTI-CORRELATED with eyelid aperture. Uncovered classes must be visible as
     UNKNOWN, not absent.
  3. A GATE RENDERS THE REGIME IT GATES.  generate_vace_with_probe forced
     context_windows=False, making the probe a different renderer from the run;
     it emitted false 'frozen' verdicts on a config measured at 82px and blocked
     two good renders (32 min lost).
  4. A METRIC DECLARES ITS NOISE FLOOR AND ITS CONTROL ARM.  Mean edge-NCC-vs-
     frame0 steered 15 versions before a STATIC BACKGROUND WALL was found to
     score at or above the book on every clip. Report drift(prop) - drift(static).
  5. WITNESSES ARE ADJUDICATED, NOT AVERAGED.  Two report runs disagreed about
     whether the boy's hands were visible and nothing resolved it.

Stdlib only, no hard dependencies: importing this must never be able to break a
render. Every public call is defensive.
"""

from __future__ import annotations

import json
import os
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_HERE, 'data', 'runtime', 'qc_gates.json')

# ── verdicts ────────────────────────────────────────────────────────────────
PASS = 'pass'  # noqa: S105  QC verdict literal, not a secret
FAIL = 'fail'
UNKNOWN = 'unknown'

# ── enforcement ladder ──────────────────────────────────────────────────────
SHADOW = 'shadow'  # measure, record, never surface as a blocker
WARN = 'warn'  # measure, record, mark the run loudly, do not stop it
BLOCK = 'block'  # measure, record, STOP the pipeline

_LADDER = (SHADOW, WARN, BLOCK)


class QCBlocked(BaseException):
    """Raised when a gate at mode=block returns FAIL. Carries the verdict.

    Deliberately derived from BaseException, not Exception — like SystemExit and
    KeyboardInterrupt, and for the same reason: this is a CONTROL-FLOW SIGNAL,
    not an error.

    This codebase is (correctly) full of fail-safe QC handlers whose whole job is
    to make sure broken measurement never stops a render:

        pipeline_debug.qc_region_flow:  "any internal error returns {'ok': True}
                                         — QC breakage never blocks generation"
        wan_vace_service:816            except Exception -> ok = True,
                                         "proceeding cautiously"
        arcane_multichar:615            except Exception: pass

    Every one of those would have caught a deliberate block and converted it back
    into a shrug — arming the ladder while leaving it disarmed in practice. A gate
    that decided to stop the pipeline must outrank the handler that exists to
    tolerate gates being broken.

    Catch it explicitly where you mean to:  except qc_contract.QCBlocked:
    Or disable enforcement entirely:        ZYG_QC_ENFORCE=0
    """

    def __init__(self, message, verdict=None, gates=None):
        super().__init__(message)
        self.verdict = verdict or {}
        self.gates = list(gates or [])


class RegimeMismatch(Exception):
    """A gate was asked to judge a run rendered under a config it was not
    calibrated for. See rule 3 — this is a TEST error, never a subject failure."""


# ── the defect taxonomy ─────────────────────────────────────────────────────
# Canonical failure classes for generated shots. Rows with no gate are the
# point of this table: they are what your eyes are still the only instrument for.
DEFECT_TAXONOMY = {
    'frozen-motion': 'a subject or region that should articulate does not',
    'motion-jitter': 'articulation exists but reverses/vibrates unnaturally',
    'character-imbalance': 'the shot is carried by one character, the other is set dressing',
    'prop-morph': 'a rigid object changes identity/shape/scale across the clip',
    'identity-drift': 'a face stops being the same person',
    'identity-provenance': 'the render used the WRONG identity asset (LoRA/anchor/ref)',
    'eyelid-aperture': 'eyes closed/squinting for a meaningful share of the shot',
    'texture-collapse': 'skin/material loses micro-detail (waxy, plastic, smeared)',
    'style-collapse': 'photoreal drifts to illustration/anime, or vice versa',
    'set-churn': 'background is re-drawn rather than re-lit',
    'chain-seam': 'a visible discontinuity at a segment/window boundary',
    'boundary-violation': 'a keep/generate mask cuts a rigid object or a moving occluder',
    'anatomy': 'hands/faces geometrically impossible',
    'ownership-semantics': 'the right action bound to the wrong subject',
    'camera-drift': 'camera moves when the shot is locked',
    'overexposure': 'clipped highlights / blown luma',
    'boiling': 'per-frame high-frequency instability (flicker, grain crawl)',
    'grade-drift': 'colour/grade wanders across the clip',
    'audio-loss': 'narration/bed missing, clipped, or mis-levelled',
    'regression': 'measurably worse than a named baseline',
    'licence-provenance': 'the weight lineage is not cleared for commercial publication',
    'restoration-hallucination': 'the upscaler INVENTED detail absent from the source',
    'qc-broken': 'the MEASUREMENT failed — not a defect in the subject',
}


class GateContract:
    """What a gate promises. The fields that matter are the honest ones:
    `blind_to` and `control_arm`."""

    __slots__ = (
        'name',
        'detects',
        'blind_to',
        'regime',
        'control_arm',
        'noise_floor',
        'calibrated_on',
        'default_mode',
        'note',
    )

    def __init__(
        self,
        name,
        detects=(),
        blind_to=(),
        regime=None,
        control_arm=None,
        noise_floor=None,
        calibrated_on=(),
        default_mode=SHADOW,
        note='',
    ):
        self.name = name
        self.detects = tuple(detects)
        self.blind_to = tuple(blind_to)
        self.regime = dict(regime or {})
        self.control_arm = control_arm
        self.noise_floor = noise_floor
        self.calibrated_on = tuple(calibrated_on)
        self.default_mode = default_mode if default_mode in _LADDER else SHADOW
        self.note = note

    def as_dict(self):
        return {
            'name': self.name,
            'detects': list(self.detects),
            'blind_to': list(self.blind_to),
            'regime': dict(self.regime),
            'control_arm': self.control_arm,
            'noise_floor': self.noise_floor,
            'calibrated_on': list(self.calibrated_on),
            'default_mode': self.default_mode,
            'note': self.note,
        }


# ── the registry ────────────────────────────────────────────────────────────
# Keyed by the check-name prefix pipeline_debug emits. Longest prefix wins.
#
# default_mode is BLOCK only where a gate has been shown to retro-FAIL a known
# bad run AND pass a known good one. Today that is exactly two gates
# (qc_region_flow, qc_prop_consistency: "Both retro-FAIL v7 exactly at its true
# defects" / clean on v8b). Everything else starts in shadow and is promoted by
# scripts/qc_gate_admin.py only after tests/golden proves it.
GATE_CONTRACTS = {
    'region_flow:': GateContract(
        'region_flow',
        detects=('frozen-motion',),
        blind_to=('motion-jitter', 'prop-morph', 'identity-drift'),
        regime={'measured_on': 'pre-fx intermediate'},
        control_arm='a static background region must score below the subject',
        noise_floor=0.06,
        calibrated_on=('scene20_v7', 'scene20_v8', 'scene20_v8b'),
        default_mode=BLOCK,
        note=(
            'Farneback dense flow. Supersedes PyrLK track-path, which PASSED a '
            'frozen Abel at 44px on candle flicker alone. min_flow 0.12 '
            'hands/props, 0.06 heads.'
        ),
    ),
    'region_churn:': GateContract(
        'region_churn',
        detects=('set-churn', 'boiling'),
        blind_to=('frozen-motion',),
        regime={'measured_on': 'pre-fx intermediate'},
        control_arm='a static background region churns at the clip noise floor',
        noise_floor=0.55,
        calibrated_on=(),
        default_mode=WARN,
        note=(
            'The OTHER half of qc_region_flow. Held at warn: it fired at '
            'churn_p95 0.553 against a 0.55 floor on v29 (a 0.5% margin) and '
            '0.684 on v22 — both known-good runs. A threshold that close to '
            'its own noise has not earned authority. Needs a static-background '
            'control arm measured per clip before promotion; painterly '
            'backgrounds boil irreducibly at high shift (bg_structure ~61 vs '
            'gate 30, documented as irreducible for OOD painterly).'
        ),
    ),
    'region_flow:keep': GateContract(
        'region_flow_keep',
        detects=(),  # detects NOTHING — see note
        blind_to=('frozen-motion',),
        default_mode=SHADOW,
        note=(
            'A keep/pin region is STATIC BY DESIGN. Measuring it for aliveness '
            'is a category error: it failed in 10 of 14 recorded runs including '
            'known-good ones (v22, v27, v29, v30). Never promote above shadow. '
            'What a keep region actually needs is boundary-violation checking — '
            'does a MOVING occluder cross it (the paste-back freeze) — which is '
            'mask_boundary + pasteback_dynamic, not flow.'
        ),
    ),
    'prop_ncc:': GateContract(
        'prop_consistency',
        detects=('prop-morph', 'chain-seam'),
        blind_to=('frozen-motion', 'texture-collapse'),
        regime={'measured_on': 'pre-fx intermediate', 'requires': 'context-window stride known'},
        control_arm='background box NCC over the same seam pair',
        noise_floor=0.70,
        calibrated_on=('scene20_v7', 'scene20_v8b'),
        default_mode=WARN,
        note=(
            'Morph pairs measured <=0.677, clean >=0.745; 0.60 was too loose. '
            'HELD AT WARN, not block: the fixed 0.70 floor fails the FINAL seam '
            'of every 20s clip (v22 0.568/0.419/0.300/0.419 at 16.62->19.0s) '
            'because prop fidelity DECAYS WITH ELAPSED GENERATED TIME — props '
            'are wall-stable for ~5s then 4-6x worse by ~s12. That is a '
            'measured property of the model, not a defect this run introduced. '
            'Blocking on it would stop every long take, including v28, the best '
            'render on disk. Promote only behind a time-aware threshold.'
        ),
    ),
    'track:': GateContract(
        'track_path',
        detects=('frozen-motion',),
        blind_to=('frozen-motion',),  # deliberately: it MISSES its own class
        noise_floor=3.0,
        calibrated_on=(),
        default_mode=SHADOW,
        note=(
            'DISCREDITED as a primary aliveness metric — shimmer-sensitive; '
            'passed frozen Abel at 44px. Kept for trend continuity only.'
        ),
    ),
    'motion:': GateContract('motion', detects=('frozen-motion',), default_mode=SHADOW),
    'motion_quality:': GateContract('motion_quality', detects=('motion-jitter',), default_mode=SHADOW),
    'motion_balance:': GateContract('motion_balance', detects=('motion-jitter',), default_mode=SHADOW),
    'character_balance:box_quality': GateContract(
        'character_balance_box',
        detects=('qc-broken',),
        default_mode=WARN,
        note='A diluted face box is a broken MEASUREMENT, not a shot defect.',
    ),
    'character_balance:measured': GateContract('character_balance_measured', detects=('qc-broken',), default_mode=WARN),
    'character_balance:': GateContract(
        'character_balance',
        detects=('character-imbalance',),
        blind_to=('frozen-motion',),
        default_mode=SHADOW,
        note=(
            'A RATIO CANNOT SEE "everyone is dead": passed at 1.77 with BOTH '
            'faces frozen. Only trustworthy WITH the per-character floors.'
        ),
    ),
    'beat_prominence': GateContract(
        'beat_prominence',
        detects=('character-imbalance',),
        regime={'measured_on': 'prompt text, no video'},
        default_mode=SHADOW,
    ),
    'identity:': GateContract(
        'identity',
        detects=('identity-drift',),
        blind_to=('identity-provenance', 'texture-collapse'),
        default_mode=SHADOW,
        note=(
            'Scores a render against ITS OWN anchor. If the anchor was staged '
            'from the wrong asset, this is self-consistent and green — the '
            'exact blindness that hid 65/67 wrong characters. '
            'identity-provenance needs lora_attest, not this.'
        ),
    ),
    'prop_geometry': GateContract('prop_geometry', detects=('prop-morph',), default_mode=SHADOW),
    'prop_triad': GateContract('prop_triad', detects=('prop-morph',), default_mode=SHADOW),
    'prop_scale': GateContract('prop_scale', detects=('prop-morph',), default_mode=SHADOW),
    'prop_ridge': GateContract('prop_ridge', detects=('prop-morph',), default_mode=SHADOW),
    'frame_border:': GateContract('frame_border', detects=('chain-seam',), default_mode=SHADOW),
    'chain_seams': GateContract('chain_seams', detects=('chain-seam',), default_mode=SHADOW),
    'set_stability': GateContract('set_stability', detects=('set-churn',), default_mode=SHADOW),
    'set_churn_residual': GateContract('set_churn', detects=('set-churn',), default_mode=SHADOW),
    'camera_motion': GateContract('camera_motion', detects=('camera-drift',), default_mode=SHADOW),
    'exposure:': GateContract('exposure', detects=('overexposure',), default_mode=SHADOW),
    'hand_count': GateContract(
        'hand_count',
        detects=('anatomy',),
        blind_to=('anatomy',),
        default_mode=SHADOW,
        note='Counts hands. Says nothing about whether a hand is possible.',
    ),
    'color_drift': GateContract('color_drift', detects=('grade-drift',), default_mode=SHADOW),
    'flicker_index': GateContract('flicker_index', detects=('boiling',), default_mode=SHADOW),
    'fx_': GateContract('fx_grain', detects=('boiling',), default_mode=SHADOW),
    'mask_boundary': GateContract(
        'mask_boundary',
        detects=('boundary-violation',),
        default_mode=WARN,
        note=('Earned its keep pre-render: caught the candle-carve/pipe-bowl collision, saved 85 min.'),
    ),
    'semantics': GateContract('semantics', detects=('ownership-semantics',), default_mode=SHADOW),
    'regression:provenance': GateContract('regression_provenance', detects=('qc-broken',), default_mode=WARN),
    'regression:measured': GateContract('regression_measured', detects=('qc-broken',), default_mode=WARN),
    'regression:': GateContract('regression', detects=('regression',), default_mode=SHADOW),
    'eye_openness': GateContract(
        'eye_openness',
        detects=('eyelid-aperture',),
        regime={'measured_on': 'FINAL clip only — never the probe'},
        noise_floor=0.15,
        calibrated_on=('scene20_v15', 'scene20_v17', 'scene20_v20', 'scene20_v22'),
        default_mode=WARN,
        note=(
            'MediaPipe EAR. The probe renders beat 1 only, where both '
            'characters read 100% open; aperture dips in beats 0 and 3.'
        ),
    ),
    'lora_attest': GateContract(
        'lora_attest',
        detects=('identity-provenance',),
        regime={'measured_on': 'the CAPTURED comfy graph, not the intended one'},
        default_mode=WARN,
        note=(
            'sha256 every model file in the executed graph vs model_pins.json. '
            'Detects hash_mismatch / missing_file / strength_zero / ORPHAN node. '
            'This is the gate the wrong-character bug needed.'
        ),
    ),
    'restoration_fidelity:': GateContract(
        'restoration_fidelity',
        detects=('restoration-hallucination',),
        blind_to=('identity-drift', 'texture-collapse', 'grade-drift'),
        regime={'measured_on': 'a (source, upscaled) frame PAIR from the finishing stage'},
        control_arm=(
            'a LANCZOS upscale of the same source invents nothing by '
            'construction: report residual(model) - residual(lanczos). '
            'Verified zero point — LANCZOS against itself scores exactly '
            '0.00000000, and NEAREST-NEIGHBOUR scores NEGATIVE (-0.004).'
        ),
        noise_floor=0.018911,
        calibrated_on=('FINAL_pipeline/up_in vs up_out, 65 frames, RealESRGAN_x2',),
        default_mode=SHADOW,
        note=(
            'Floor is the INCUMBENT ESRGAN worst frame x1.5, so it means '
            '"invents more than the finishing stage we already ship". Measured: '
            'incumbent 0.011826-0.012607 (65/65 PASS), injected sigma=0.05 '
            'invention 0.02228-0.02264 (15/15 FAIL). Tile separation is LOGGED '
            'AND NEVER WEIGHED: the first cut refused to decide below a guessed '
            '1.20, which returned UNKNOWN on the whole incumbent corpus '
            '(measured 1.10-1.32); the direction was also backwards (invention '
            'drove it DOWN, 1.23->1.06); and the populations overlap anyway '
            '(incumbent min 1.10 vs invention max 1.11), so no threshold on it '
            'separates them. '
            'BLIND TO IDENTITY: a restorer can invent a consistent face and '
            'score well here, which is why Phase 1 also moves identity QC to '
            'run after finishing.'
        ),
    ),
    'licence_provenance:': GateContract(
        'licence_provenance',
        detects=('licence-provenance',),
        blind_to=('identity-drift', 'texture-collapse', 'style-collapse', 'anatomy', 'frozen-motion'),
        regime={'measured_on': 'the weights a graph REFERENCES, not the pixels'},
        control_arm=(
            'a graph built only from Apache-2.0 weights must PASS while '
            'the same graph with a FLUX.1-dev checkpoint must FAIL'
        ),
        default_mode=SHADOW,
        note=(
            'The only class where the operator eye is not a weaker instrument '
            'but NO instrument: a FLUX-dev frame and an Apache frame are '
            'visually identical. Charges a character LoRA with its BASE model '
            'licence via training_status_<family>.json, because a LoRA is a '
            'derivative of what it was fine-tuned from. Unregistered weight => '
            'UNKNOWN, never PASS. Blind to the licence of the TRAINING DATA, '
            'which is a separate exposure this gate cannot see.'
        ),
    ),
    'qc_error:': GateContract('qc_error', detects=('qc-broken',), default_mode=WARN),
}

# Classes with NO gate anywhere in the registry are computed, not hardcoded —
# see uncovered_classes(). Today that surfaces texture-collapse, style-collapse,
# and audio-loss for video runs: real defect classes this pipeline cannot see.


# ── config (the ladder state on disk) ───────────────────────────────────────
_cfg_lock = threading.Lock()
_cfg_cache = {'mtime': None, 'data': None}

DEFAULT_CONFIG = {
    'mode': WARN,
    'enforce': True,
    'gates': {},
    '_comment': (
        'mode = global default for gates with no explicit entry. '
        'enforce=false turns every block into a warn without editing '
        'per-gate modes (the one switch to pull in an incident). '
        'Env ZYG_QC_ENFORCE=0 does the same without touching this file.'
    ),
}


def load_config(force=False):
    """Read qc_gates.json, cached on mtime. Never raises."""
    try:
        st = os.stat(_CONFIG_PATH)
        mtime = st.st_mtime
    except Exception:
        return dict(DEFAULT_CONFIG)
    with _cfg_lock:
        if not force and _cfg_cache['mtime'] == mtime and _cfg_cache['data'] is not None:
            return _cfg_cache['data']
        try:
            with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError('qc_gates.json is not an object')
            merged = dict(DEFAULT_CONFIG)
            merged.update(data)
            merged['gates'] = dict(data.get('gates') or {})
        except Exception:
            merged = dict(DEFAULT_CONFIG)
        _cfg_cache['mtime'] = mtime
        _cfg_cache['data'] = merged
        return merged


def enforcement_enabled():
    """False disables every block globally. Env wins over file so an operator can
    kill enforcement without an editor."""
    env = os.environ.get('ZYG_QC_ENFORCE')
    if env is not None:
        return str(env).strip().lower() not in ('0', 'false', 'no', '')
    return bool(load_config().get('enforce', True))


def effective_check_name(check):
    """Route a check to the gate that actually judged it.

    qc_region_flow emits ONE check name for TWO defect classes: 'frozen' (flow
    below floor) and 'churn' (edge structure re-drawn). They have different
    remedies and very different calibration maturity, so they cannot share a
    ladder mode. Measured: the frozen half separates 4.5x across its threshold
    (v8a abel_hand 0.080 -> v8b 0.364, gate 0.12); the churn half fired at 0.553
    against a 0.55 floor on v29 and 0.684 on v22, both known-good runs.

    Prefers the explicit fail_kind field; falls back to the note text so the 56
    historical reports on disk route correctly too."""
    if not isinstance(check, dict):
        return str(check or '')
    name = str(check.get('check') or '')
    if not name.startswith('region_flow:') or name.startswith('region_flow:keep'):
        return name
    kind = check.get('fail_kind')
    if kind is None:
        note = str(check.get('note') or '').lower()
        kind = 'churn' if ('churn' in note or 're-drawn' in note) else ('frozen' if 'frozen' in note else '')
    if kind == 'churn':
        return 'region_churn:' + name.split(':', 1)[1]
    return name


def contract_for(check_name):
    """Longest-prefix match into GATE_CONTRACTS. None if the gate is unregistered.

    Accepts either a check name or a whole check dict (which enables the
    frozen/churn split — see effective_check_name)."""
    if isinstance(check_name, dict):
        check_name = effective_check_name(check_name)
    name = str(check_name or '')
    best = None
    for prefix, contract in GATE_CONTRACTS.items():
        if name.startswith(prefix):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, contract)
    return best[1] if best else None


def mode_for(check_name):
    """Ladder mode for a check. Precedence: explicit per-gate entry (by contract
    name, then by raw prefix) > contract default > global default.

    An UNREGISTERED gate always lands in shadow regardless of the global default:
    a gate nobody has written a contract for has not earned authority. This is
    what makes 'new gates enter at shadow' automatic rather than a convention."""
    if isinstance(check_name, dict):
        check_name = effective_check_name(check_name)
    cfg = load_config()
    gates = cfg.get('gates') or {}
    contract = contract_for(check_name)

    if contract is not None and contract.name in gates:
        m = gates[contract.name]
        return m if m in _LADDER else contract.default_mode
    name = str(check_name or '')
    for key, m in gates.items():
        if name.startswith(key) and m in _LADDER:
            return m
    if contract is None:
        # No contract -> no authority. This is what makes "new gates enter at
        # shadow" enforced rather than remembered.
        return SHADOW
    # A contract's declared default WINS over the global default. Letting the
    # global promote an explicit `shadow` would mean a gate deliberately held
    # back — region_flow_keep, track_path, identity — silently gained a louder
    # voice because someone changed an unrelated line in qc_gates.json.
    return contract.default_mode


def mode_for_gate_name(gate_name):
    """Ladder mode by CONTRACT name (e.g. 'region_churn') rather than by check
    name. Used by scripts/qc_gate_admin.py, which speaks in gate names."""
    cfg = load_config()
    gates = cfg.get('gates') or {}
    if gate_name in gates and gates[gate_name] in _LADDER:
        return gates[gate_name]
    for _prefix, c in GATE_CONTRACTS.items():
        if c.name == gate_name:
            return c.default_mode
    return SHADOW


# ── classification ──────────────────────────────────────────────────────────
_SKIP_HINTS = (
    'skipped',
    'not available',
    'unavailable',
    'no reference',
    'no coverage',
    'not measured',
    'could not',
    'missing',
    'no faces',
    'undecided',
    'insufficient',
)


def classify(check):
    """PASS / FAIL / UNKNOWN for one recorded check.

    `ok is None` is UNKNOWN. So is ok=True carrying a skip note — that is
    pipeline_debug.py:520's `{'ok': True, 'note': 'skipped: ...'}`, a gate that
    could not look reporting green. Rule 1 exists for exactly this record."""
    if not isinstance(check, dict):
        return UNKNOWN
    ok = check.get('ok')
    if ok is None:
        return UNKNOWN
    note = str(check.get('note') or '').lower()
    if note and any(h in note for h in _SKIP_HINTS):
        return UNKNOWN
    if check.get('coverage') in (0, 0.0) or check.get('measured') is False:
        return UNKNOWN
    return PASS if ok else FAIL


def split_checks(checks):
    """-> (passes, fails, unknowns) as three lists."""
    p, f, u = [], [], []
    for c in checks or ():
        v = classify(c)
        (p if v == PASS else f if v == FAIL else u).append(c)
    return p, f, u


# ── coverage ────────────────────────────────────────────────────────────────
def coverage(checks):
    """Which defect classes did this run actually TEST?

    Returns {class: {'status': 'covered'|'unknown'|'uncovered',
                     'gates': [...], 'blind_gates': [...]}}

      covered   — at least one registered gate produced PASS or FAIL for it
      unknown   — a gate that detects it ran but could not decide
      uncovered — nothing that detects this class ran at all

    'uncovered' is the row that matters. A green run with six uncovered classes
    is not a clean run; it is a run with six unopened doors."""
    out = {k: {'status': 'uncovered', 'gates': [], 'blind_gates': []} for k in DEFECT_TAXONOMY}
    for c in checks or ():
        contract = contract_for(c)
        if contract is None:
            continue
        verdict = classify(c)
        for cls in contract.detects:
            row = out.setdefault(cls, {'status': 'uncovered', 'gates': [], 'blind_gates': []})
            if contract.name not in row['gates']:
                row['gates'].append(contract.name)
            if verdict in (PASS, FAIL):
                row['status'] = 'covered'
            elif row['status'] == 'uncovered':
                row['status'] = 'unknown'
        for cls in contract.blind_to:
            row = out.setdefault(cls, {'status': 'uncovered', 'gates': [], 'blind_gates': []})
            if contract.name not in row['blind_gates']:
                row['blind_gates'].append(contract.name)
    return out


def uncovered_classes(checks):
    """Defect classes this run never tested. The report's yellow rows."""
    cov = coverage(checks)
    return sorted(k for k, v in cov.items() if v['status'] == 'uncovered' and k != 'qc-broken')


def unknown_classes(checks):
    """Classes where a gate ran and refused to decide."""
    cov = coverage(checks)
    return sorted(k for k, v in cov.items() if v['status'] == 'unknown')


# ── enforcement ─────────────────────────────────────────────────────────────
def blocking_failures(checks):
    """Failed checks whose gate sits at mode=block. These stop a pipeline."""
    out = []
    for c in checks or ():
        if classify(c) != FAIL:
            continue
        if mode_for(c) == BLOCK:
            out.append(c)
    return out


def warning_failures(checks):
    out = []
    for c in checks or ():
        if classify(c) != FAIL:
            continue
        if mode_for(c) == WARN:
            out.append(c)
    return out


def evaluate(checks):
    """The whole contract in one call. Returns a dict suitable for splicing
    straight into a run verdict."""
    checks = list(checks or ())
    passes, fails, unknowns = split_checks(checks)
    blocking = blocking_failures(checks)
    warning = warning_failures(checks)
    cov = coverage(checks)
    uncov = [k for k, v in cov.items() if v['status'] == 'uncovered' and k != 'qc-broken']
    unk_cls = [k for k, v in cov.items() if v['status'] == 'unknown']
    return {
        'passed_checks': len(passes),
        'failed_checks': len(fails),
        'unknown_checks': len(unknowns),
        'blocking_failures': [effective_check_name(c) for c in blocking],
        'warning_failures': [effective_check_name(c) for c in warning],
        'blocked': bool(blocking) and enforcement_enabled(),
        'enforcement': enforcement_enabled(),
        'coverage': {k: v['status'] for k, v in sorted(cov.items())},
        'uncovered_classes': sorted(uncov),
        'unknown_classes': sorted(unk_cls),
        'coverage_score': round(sum(1 for v in cov.values() if v['status'] == 'covered') / max(1, len(cov)), 3),
    }


# ── rule 3: regime parity ───────────────────────────────────────────────────
def assert_regime(check_name, actual, strict=None):
    """A gate must render/measure the same regime as the run it gates.

    generate_vace_with_probe forced context_windows=False and so measured itself
    instead of the subject: false 'frozen' verdicts on a config measured at 82px,
    two good renders blocked, 32 minutes lost.

    Raises RegimeMismatch (a TEST error) rather than returning FAIL (a subject
    error) — the distinction that keeps an operator from re-rendering a fine shot.
    """
    contract = contract_for(check_name)
    if contract is None or not contract.regime:
        return True
    actual = dict(actual or {})
    bad = []
    for key, expected in contract.regime.items():
        if key in ('measured_on', 'requires'):
            continue
        if key in actual and actual[key] != expected:
            bad.append(f'{key}={actual[key]!r} expected {expected!r}')
    if bad:
        msg = (
            f'{check_name}: gate calibrated for a different regime than the '
            f'run it is judging ({"; ".join(bad)}). This is a TEST defect, '
            f'not a subject defect.'
        )
        if strict is None:
            strict = str(os.environ.get('ZYG_QC_STRICT_REGIME', '1')).lower() not in ('0', 'false', 'no')
        if strict:
            raise RegimeMismatch(msg)
        return msg
    return True


# ── rule 5: adjudication ────────────────────────────────────────────────────
def quorum(votes, k=3):
    """Adjudicate k independent witnesses. Never average, never take the first.

    votes: iterable of PASS/FAIL/UNKNOWN (or truthy/falsey/None).
    -> {'verdict', 'confidence', 'tally', 'escalate'}

    A straight split escalates rather than resolving — 'two report runs disagreed
    with each other about whether the boy's hands were consistently visible' and
    nothing adjudicated it."""
    norm = []
    for v in votes or ():
        if v in (PASS, FAIL, UNKNOWN):
            norm.append(v)
        elif v is None:
            norm.append(UNKNOWN)
        else:
            norm.append(PASS if v else FAIL)
    tally = {PASS: norm.count(PASS), FAIL: norm.count(FAIL), UNKNOWN: norm.count(UNKNOWN)}
    decided = tally[PASS] + tally[FAIL]
    if not norm or decided == 0:
        return {'verdict': UNKNOWN, 'confidence': 0.0, 'tally': tally, 'escalate': True}
    if tally[PASS] == tally[FAIL]:
        return {'verdict': UNKNOWN, 'confidence': 0.0, 'tally': tally, 'escalate': True}
    winner = PASS if tally[PASS] > tally[FAIL] else FAIL
    conf = round(max(tally[PASS], tally[FAIL]) / float(decided), 3)
    unanimous = max(tally[PASS], tally[FAIL]) == decided
    return {
        'verdict': winner,
        'confidence': conf,
        'tally': tally,
        'escalate': (not unanimous) or tally[UNKNOWN] > decided,
        'low_confidence': not unanimous,
    }


# ── rule 4: control arm ─────────────────────────────────────────────────────
def background_referenced(prop_score, static_score):
    """drift(prop) - drift(static_box). The raw number lies.

    Measured: a background WALL scored 0.305-0.395 edge-NCC-vs-frame0 — at or
    ABOVE the book on every clip — because the scale is dominated by texture
    decorrelation, not by 'is it the same book'. 'book +94% stability' did not
    mean what it said."""
    try:
        return round(float(prop_score) - float(static_score), 4)
    except Exception:
        return None


MIN_EDGE_DENSITY = 0.02


def usable_control_box(edge_density):
    """Boxes below ~2% Canny edge density are pure noise and produced fake
    'signal' (bg_l 2.5%, bg_top 1.65%). Refuse them as inputs."""
    try:
        return float(edge_density) >= MIN_EDGE_DENSITY
    except Exception:
        return False


# ── admin helpers (used by scripts/qc_gate_admin.py) ────────────────────────
def write_config(cfg):
    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    tmp = _CONFIG_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, _CONFIG_PATH)
    load_config(force=True)


def set_mode(gate_name, mode):
    if mode not in _LADDER:
        raise ValueError(f'mode must be one of {_LADDER}')
    cfg = dict(load_config())
    gates = dict(cfg.get('gates') or {})
    gates[gate_name] = mode
    cfg['gates'] = gates
    write_config(cfg)
    return cfg


def registry_table():
    """Rows for `qc_gate_admin.py list`."""
    rows = []
    for prefix, c in sorted(GATE_CONTRACTS.items(), key=lambda kv: kv[1].name):
        rows.append(
            {
                'gate': c.name,
                'prefix': prefix,
                'mode': mode_for(prefix),
                'default': c.default_mode,
                'detects': ', '.join(c.detects) or '-',
                'blind_to': ', '.join(c.blind_to) or '-',
                'calibrated_on': len(c.calibrated_on),
            }
        )
    return rows


def gated_classes():
    """Defect classes at least one registered gate claims to detect."""
    out = set()
    for c in GATE_CONTRACTS.values():
        out.update(c.detects)
    return out


def ungated_classes():
    """Classes NO gate in the registry detects — the permanent blind spots.
    These are what your eyes are still the only instrument for."""
    return sorted(set(DEFECT_TAXONOMY) - gated_classes())
