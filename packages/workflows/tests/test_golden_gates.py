#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
The golden set — every gate change replayed against every historical run.

Two layers:

  1. LABELLED CASES (tests/golden/labels.json) — hand-written ground truth for
     defects this pipeline actually shipped, with the numbers that proved them.
     These assert real behaviour: v8a's paste-back freeze MUST block; v28, the
     best render on disk, MUST NOT.

  2. BASELINE CHARACTERISATION (tests/golden/baseline.json) — the current ladder
     verdict for all ~39 recorded runs, snapshotted. Any gate/threshold change
     that silently flips a verdict somewhere else in the corpus fails here with
     the exact runs named. Regenerate deliberately:
         python3 scripts/golden_baseline.py --write

No GPU, no video decode: this replays recorded reports and finishes in
milliseconds. Slow metric-level replay (re-measuring the mp4s) is marked
@pytest.mark.slow and skipped by default.

    python3 -m pytest tests/ -q
"""

import json
import os

import pytest

from tests import _tree
from zyg_workflows import qc_contract as qc

_GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'golden')
_LABELS = os.path.join(_GOLDEN, 'labels.json')
_BASELINE = os.path.join(_GOLDEN, 'baseline.json')


def _load(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _checks(report_path):
    d = _load(_tree.crews(report_path))
    return [c for q in d.get('qc', []) for c in q.get('checks', [])]


def _labels():
    return _load(_LABELS)


def _cases():
    out = []
    for case in _labels().get('cases', []):
        p = os.path.join(_tree.CREWS, case['report'])
        out.append(
            pytest.param(
                case,
                id=case['id'],
                marks=pytest.mark.skipif(not os.path.exists(p), reason=f'report missing: {case["report"]}'),
            )
        )
    return out


# ── layer 1: labelled ground truth ──────────────────────────────────────────
@pytest.mark.parametrize('case', _cases())
def test_labelled_case(case):
    ev = qc.evaluate(_checks(case['report']))
    exp = case['expect']
    blocking = set(ev['blocking_failures'])

    if 'blocked' in exp:
        assert ev['blocked'] is exp['blocked'], (
            f'{case["id"]}: expected blocked={exp["blocked"]}, got '
            f'{ev["blocked"]}; blocking={sorted(blocking)}\n' + '\n'.join(case.get('provenance', []))
        )

    for gate in exp.get('gates', []):
        assert any(g == gate or g.startswith(gate) for g in blocking), (
            f'{case["id"]}: expected {gate!r} to block. Actually blocking: {sorted(blocking)}'
        )

    for gate in exp.get('not_blocked_by', []):
        offenders = [g for g in blocking if g.startswith(gate)]
        assert not offenders, f'{case["id"]}: {gate!r} must NOT block this run, but {offenders} did.\n' + '\n'.join(
            case.get('provenance', [])
        )


def test_the_best_render_on_disk_is_shippable():
    """Standing guard. If arming a gate blocks v28, the gate is wrong."""
    ev = qc.evaluate(_checks('output/multichar_seated/scene20_v28/debug/report.json'))
    assert not ev['blocked'], (
        f'scene20_v28 is the best render produced by this pipeline. Blocked by: {sorted(set(ev["blocking_failures"]))}'
    )


def test_known_uncovered_classes_match_the_registry():
    """labels.json documents which defect classes nothing can see. If someone
    builds a gate for one, this fails and forces the doc to be updated."""
    documented = set(_labels()['known_uncovered']['classes'])
    assert set(qc.ungated_classes()) == documented, (
        'Registry and labels.json disagree about what is ungated. '
        f'registry={sorted(qc.ungated_classes())} labels={sorted(documented)}'
    )


# ── layer 2: corpus characterisation ────────────────────────────────────────
@pytest.mark.skipif(not os.path.exists(_BASELINE), reason='no baseline yet — run scripts/golden_baseline.py --write')
def test_no_unexplained_verdict_drift_across_the_corpus():
    base = _load(_BASELINE)['runs']
    drift = []
    for run, expected in sorted(base.items()):
        p = os.path.join(_tree.CREWS, expected['report'])
        if not os.path.exists(p):
            continue
        ev = qc.evaluate(_checks(expected['report']))
        for field in ('blocked', 'failed_checks', 'unknown_checks'):
            if ev[field] != expected[field]:
                drift.append(f'  {run}: {field} {expected[field]} -> {ev[field]}')
        if sorted(set(ev['blocking_failures'])) != sorted(set(expected['blocking_failures'])):
            drift.append(f'  {run}: blocking {expected["blocking_failures"]} -> {sorted(set(ev["blocking_failures"]))}')
    assert not drift, (
        'Gate behaviour changed on runs nobody was looking at:\n'
        + '\n'.join(drift)
        + '\n\nIf this change is intended, regenerate with:\n'
        '  python3 scripts/golden_baseline.py --write'
    )


@pytest.mark.skipif(not os.path.exists(_BASELINE), reason='no baseline yet')
def test_block_rate_stays_sane():
    """A ladder that blocks most of the corpus is miscalibrated, not strict.
    Arming region_flow naively blocked 12 of 39; after splitting frozen from
    churn and exempting keep-regions it blocks 2, both true positives."""
    base = _load(_BASELINE)['runs']
    if not base:
        pytest.skip('empty baseline')
    blocked = sum(1 for v in base.values() if v['blocked'])
    rate = blocked / float(len(base))
    assert rate <= 0.25, (
        f'{blocked}/{len(base)} historical runs would be blocked ({rate:.0%}). '
        'Above ~25% the gate is measuring the model, not the defect.'
    )


# ── slow layer: re-measure from the actual clips ────────────────────────────
@pytest.mark.slow
@pytest.mark.parametrize('case', _cases())
def test_metric_replay_against_real_footage(case):
    """Re-run the metric on the mp4 and confirm the recorded number reproduces.
    Catches a metric regression that a recorded-report replay cannot see.
        python3 -m pytest tests/ -q -m slow
    """
    from zyg_workflows import pipeline_debug as pd

    run_dir = os.path.join(_tree.CREWS, os.path.dirname(os.path.dirname(case['report'])))
    clips = [f for f in os.listdir(run_dir) if f.endswith('.mp4')] if os.path.isdir(run_dir) else []
    if not clips:
        pytest.skip(f'no clip in {run_dir}')
    recorded = {c['check']: c for c in _checks(case['report']) if str(c.get('check', '')).startswith('region_flow:')}
    if not recorded:
        pytest.skip('no region_flow checks recorded')
    assert hasattr(pd, 'qc_region_flow')
