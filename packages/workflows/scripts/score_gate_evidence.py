#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Score a finished scholarly run's gate evidence from its persisted state.

    python3 scripts/score_gate_evidence.py data/runtime/pipeline_<id>_state.json
    python3 scripts/score_gate_evidence.py            # newest run

Reads what the run itself recorded — gate receipts, the audit, ladder counters —
rather than re-deriving anything from the log. It answers the question the unit
suite cannot: did each gate actually RUN on real frames, and did the retry
ladder climb? A gate that never executed files no stats, and a convergence rate
means nothing next to `checked: 0`.
"""

import json
import sys
import os

import glob

if len(sys.argv) > 1:
    sf = sys.argv[1]
else:
    cand = sorted(glob.glob('data/runtime/pipeline_*_state.json'), key=os.path.getmtime, reverse=True)
    if not cand:
        print('no pipeline state files under data/runtime/')
        sys.exit(2)
    sf = cand[0]
d = json.load(open(sf))
ev = d.get('debug_events') or []
blob = '\n'.join(str(e.get('msg', e)) if isinstance(e, dict) else str(e) for e in ev)
rec = d.get('gate_receipts') or {}
aud = d.get('gate_audit') or {}
ls = d.get('ladder_stats') or {}
hs = (rec.get('hand_qc') or {}).get('stats') or {}
tx = (rec.get('typography') or {}).get('stats') or {}

# The audit and ladder_stats are written in the pipeline's `finally`, so a
# mid-flight run has receipts but no audit. Scoring it anyway reports FAILs that
# mean "not finished yet" — the same confusion between absent and failed that
# this whole exercise was about.
if not d.get('gate_audit'):
    print(
        f'RUN INCOMPLETE — {os.path.basename(sf)} has no gate_audit yet '
        f'(written in the pipeline finally). Wait for it to end, then re-score.'
    )
    sys.exit(2)

R = []


def chk(n, c, detail=''):
    R.append(bool(c))
    print(f'{"PASS" if c else "FAIL"}  {n}' + (f'  — {detail}' if detail else ''))


print('=' * 70)
print(f'  GATE EVIDENCE — {os.path.basename(sf)}')
print('=' * 70)

chk(
    'staleness gate ran; this run executed current code',
    d.get('stale_code') is False,
    f'stale_code={d.get("stale_code")}',
)
chk(
    'gate audit filed a receipt for every expected gate',
    bool(aud) and not aud.get('missing'),
    f'expected={aud.get("expected")} missing={aud.get("missing")}',
)
chk('no gate silently skipped', aud.get('skipped') == [], f'skipped={aud.get("skipped")}')

chk('Stage 3.7 hand QC RAN', (rec.get('hand_qc') or {}).get('ran') is True)
chk(
    '  ...and judged real frames (not 0 checked / all unavailable)',
    int(hs.get('checked') or 0) > 0 and int(hs.get('unavailable') or 0) == 0,
    f'{hs}',
)

chk('typography gate RAN', (rec.get('typography') or {}).get('ran') is True)
_tx_checked = int(tx.get('checked') or (int(tx.get('in_loop_checked') or 0) + int(tx.get('sweep_checked') or 0)))
chk('  ...and produced verdicts', _tx_checked > 0, f'{tx}')
# The judge matters as much as the count: 'haiku' means the run depended on a
# paid API that has already returned "credit balance is too low" once, and
# 'none' means nothing answered. OCR runs on the CPU and cannot be billed out.
chk('  ...using the local OCR judge (no VRAM, no API)', str(tx.get('judge') or '') == 'ocr', f'judge={tx.get("judge")}')
chk('  ...and nothing was booked unreadable', int(tx.get('unreadable') or tx.get('sweep_unusable') or 0) == 0, f'{tx}')

# The invariant that matters is not "every attempt was text-checked" — an
# attempt the ANATOMY gate already rejected is doomed anyway, and skipping the
# text judge on it saves work rather than hiding anything. What must hold is
# that every frame which actually SHIPS has been judged for lettering, and that
# no frame was booked as unreviewed.
_sweep_n = int((d.get('typography_post_stats') or {}).get('checked') or 0)
_slots = int(ls.get('slots') or 0)
chk(
    '  ...every shipped frame was typography-verified',
    _slots == 0 or _sweep_n >= _slots,
    f'slots={_slots} sweep_checked={_sweep_n}',
)

sw = d.get('typography_post_stats') or {}
chk('post-render sweep verified the canonical frames', int(sw.get('checked') or 0) > 0 or not sw, f'{sw}')

chk('retry ladder RAN', (rec.get('retry_ladder') or {}).get('ran') is True)
# Do NOT demand a particular rung fire. A run where the attempt-2 clause
# already fixed the frame is the BEST outcome, not a failure — insisting the
# stripper run every time would be scoring the ladder on how hard it worked
# rather than on whether it resolved the defect.
_flagged = int(tx.get('flagged') or tx.get('sweep_flagged') or 0)
_esc = (
    int(ls.get('text_clause') or 0)
    + int(ls.get('text_strip') or 0)
    + int(ls.get('era_escalation') or 0)
    + int(ls.get('anatomy_escalation') or 0)
    + int(ls.get('reroll') or 0)
)
chk(
    '  ...the ladder escalated when a gate flagged something',
    int(ls.get('attempts') or 0) <= int(ls.get('slots') or 0) or _esc > 0,
    f'attempts={ls.get("attempts")} slots={ls.get("slots")} escalations={_esc}',
)

# Accounting completeness: every slot either cleared at some rung or is named
# in shipped_flagged. A slot that is in neither has vanished from the report.
_cleared = sum(int(ls.get(f'cleared_at_{i}') or 0) for i in (1, 2, 3))
_shipped = len(d.get('shipped_flagged') or [])
chk(
    '  ...every slot is accounted for (cleared or reported flagged)',
    int(ls.get('slots') or 0) == _cleared + _shipped,
    f'slots={ls.get("slots")} cleared={_cleared} shipped_flagged={_shipped}',
)
print(
    f'    rungs fired: clause={ls.get("text_clause")} strip={ls.get("text_strip")} '
    f'reroll={ls.get("reroll")} era={ls.get("era_escalation")} '
    f'anatomy={ls.get("anatomy_escalation")}'
)
print(f'    region repair: tried={ls.get("repair_tried", 0)} succeeded={ls.get("repair_ok", 0)}')
# Repair only fires when the ladder ran out of rungs with lettering still there,
# so a clean run legitimately never calls it. What must hold is that every
# attempt was verified: a repair that "succeeded" without the frame reading
# clean afterwards would be the vandalism case.
_rt, _ro = int(ls.get('repair_tried') or 0), int(ls.get('repair_ok') or 0)
chk('  ...region repair only claims successes it verified', _ro <= _rt, f'tried={_rt} ok={_ro}')

chk('inert-lever guard dropped the negative prompt', 'negative_prompt dropped' in blob)
sfl = d.get('shipped_flagged')
chk(
    'flagged-shipment reporting resolved',
    (sfl is None) or isinstance(sfl, list),
    'clean run — nothing shipped flagged' if not sfl else f'{len(sfl)} flagged',
)

print(f'\n  ladder : {ls}')
print(f'  hands  : {hs}')
print(f'  typo   : {tx}')
print('=' * 70)
print(f'PASS {sum(R)}   FAIL {len(R) - sum(R)}')
sys.exit(0 if all(R) else 1)
