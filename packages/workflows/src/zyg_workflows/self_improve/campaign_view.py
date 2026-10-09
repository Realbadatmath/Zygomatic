# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""campaign — the cross-run memory VIEW.

Split verbatim out of zyg_workflows/self_improve.py; see docs/self_improve_split_map.md.
"""

import os
import time
import logging as _zyg_logging

from zyg_workflows.self_improve.base import _mklog, _read_json, _write_text
from zyg_workflows.self_improve.chain import detect_chain
from zyg_workflows.self_improve.remedies import _kb_confidence, kb
from zyg_workflows.self_improve.signature import build_signature

_zyg_log = _zyg_logging.getLogger('zyg_workflows.self_improve')


# ══════════════════════════════════════════════════════════════════════════════
# 13.  campaign — the cross-run memory VIEW
# ══════════════════════════════════════════════════════════════════════════════


def campaign(run_dirs, out_path=None, log_fn=None):
    """Chronological table of attempts, applied remedies and metric trajectories.

    Reads whatever each run dir already holds (diagnosis.json, next_attempt.json,
    verification.json) and measures the delivered + raw clips of any run that has
    never been diagnosed, so a campaign over cold directories still produces a
    real trajectory instead of blanks.

    Returns {'ok','rows','markdown'} and optionally writes the markdown."""
    log = _mklog(log_fn)
    res = {'ok': False, 'rows': [], 'markdown': ''}
    try:
        rows = []
        for rd in run_dirs:
            rd = os.path.abspath(rd)
            if not os.path.isdir(rd):
                log(f'[self_improve] campaign: skipping missing {rd}')
                continue
            diag = _read_json(os.path.join(rd, 'diagnosis.json'))
            plan = _read_json(os.path.join(rd, 'next_attempt.json'))
            veri = _read_json(os.path.join(rd, 'verification.json'))
            sig = (diag or {}).get('signature')
            if not sig:
                log(f'[self_improve] campaign: {os.path.basename(rd)} not diagnosed — measuring now')
                sig = build_signature(rd, log_fn=log)
            chain = sig.get('chain_steps') or detect_chain(rd, log_fn=None)
            # Order by when the RUN happened (earliest chain artifact), not by when
            # its signature was built — a re-diagnosed old run must not jump to the
            # front of a campaign timeline.
            mts = [c['mtime'] for c in chain if c.get('mtime')]
            rows.append(
                {
                    'run': os.path.basename(rd),
                    'run_dir': rd,
                    'ran_at': (time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(min(mts))) if mts else None),
                    'sort_key': min(mts) if mts else 0.0,
                    'when': sig.get('built'),
                    'clip': os.path.basename(sig.get('clip') or ''),
                    'raw': os.path.basename(sig.get('raw_clip') or '') or '—',
                    'chain': ' → '.join(dict.fromkeys(c['step'] for c in chain if c['variant_of'] is None)),
                    'deltas': sig.get('region_deltas') or {},
                    'failures': sig.get('failures') or [],
                    'facts': sorted({f['ns'] for f in (sig.get('facts') or [])}),
                    'applied': [a['id'] for a in ((plan or {}).get('applied') or [])],
                    'verified': [(r['remedy'], r['verdict']) for r in ((veri or {}).get('results') or [])],
                    'ledger_run_id': (sig.get('ledger') or {}).get('run_id'),
                }
            )
        rows.sort(key=lambda r: (r.get('sort_key') or 0.0, r['run']))
        res['rows'] = rows
        res['markdown'] = _campaign_md(rows)
        res['ok'] = True
        if out_path:
            _write_text(out_path, res['markdown'], log)
            log(f'[self_improve] campaign written → {out_path}')
    except Exception as e:
        res['error'] = str(e)[:250]
        log(f'[self_improve] campaign failed: {e}')
    return res


def _campaign_md(rows):
    regions = []
    for r in rows:
        for k in r['deltas']:
            if k not in regions:
                regions.append(k)
    L = [
        '# Campaign — cross-run memory',
        '',
        'Flow values are `flow_norm` (px/sample rescaled to the 832x480 @17 fps, '
        'sample_every=4 gate calibration), so rows with different delivery '
        'geometries are comparable. `raw→del` is the raw render → delivered clip '
        'change: a large negative number is a post-process eating the render.',
        '',
    ]
    hdr = (
        ['run', 'ran at', 'chain', 'delivered']
        + [f'{r} (raw→del)' for r in regions]
        + ['failed gates', 'remedies applied', 'verified']
    )
    L.append('| ' + ' | '.join(hdr) + ' |')
    L.append('|' + '|'.join(['---'] * len(hdr)) + '|')
    for r in rows:
        cells = [r['run'], r.get('ran_at') or '—', r['chain'] or '—', r['clip'] or '—']
        for reg in regions:
            d = r['deltas'].get(reg)
            if not d:
                cells.append('—')
            elif d.get('raw') is not None:
                mark = '' if d.get('delivered_ok') else ' **FAIL**'
                cells.append(f'{d["raw"]:.3f}→{d["delivered"]:.3f} ({d.get("pct")}%){mark}')
            else:
                mark = '' if d.get('delivered_ok') else ' **FAIL**'
                cells.append(f'{d["delivered"]:.3f}{mark}')
        cells.append(', '.join(f['gate'] for f in r['failures']) or 'none')
        cells.append(', '.join(r['applied']) or '—')
        cells.append(', '.join(f'{a}={b}' for a, b in r['verified']) or '—')
        L.append('| ' + ' | '.join(cells) + ' |')
    L += ['', '## Signature facts per run', '']
    for r in rows:
        L.append(
            f'* **{r["run"]}** ({r["ledger_run_id"] or "no ledger id"}): '
            + (', '.join('`' + f + '`' for f in r['facts']) or 'no facts')
        )
    learned = _kb_learning_view(rows)
    if learned:
        L += [
            '',
            '## What the KB has learned (this is the self-improvement)',
            '',
            'Confidence is a posterior over verified outcomes, not a hand-set '
            'number: a remedy that keeps failing to move its target metric across '
            'its threshold sinks in the ranking on its own.',
            '',
            '| remedy | attempts | confirmed | effective confidence | KB confidence | last run |',
            '|---|---|---|---|---|---|',
        ]
        for e in learned:
            L.append(
                f'| {e["id"]} | {e["attempts"]} | {e["successes"]} | '
                f'**{e["confidence"]}** | {e["kb_confidence"]} | '
                f'{e["last_run"] or "—"} |'
            )
    return '\n'.join(L) + '\n'


def _kb_learning_view(rows):
    """Per-remedy attempt/success/confidence for every remedy this campaign touched.

    Reads whichever KB is live; returns [] when neither exposes its state."""
    ids = []
    for r in rows:
        for rid in r.get('applied') or []:
            if rid not in ids:
                ids.append(rid)
    if not ids:
        return []
    kbo = kb()
    out = []
    for rid in ids:
        row, prior = {}, None  # `prior` = the KB file's own (already learned) value
        try:
            row = (kbo.load_state() or {}).get(rid) or {}
            entry = next((x for x in (kbo.load_kb().get('remedies') or []) if x.get('id') == rid), {})
            prior = entry.get('confidence')
        except Exception:
            try:
                row = kbo.state.get(rid) or {}
                prior = round(row.get('alpha', 1) / max(1e-9, row.get('alpha', 1) + row.get('beta', 1)), 3)
            except Exception as _exc:
                _zyg_log.debug('kb state for %s unreadable, prior left unset: %s', rid, _exc)
        out.append(
            {
                'id': rid,
                'attempts': row.get('attempts', 0),
                'successes': row.get('successes', 0),
                'confidence': _kb_confidence(kbo, rid),
                'kb_confidence': prior,
                'last_run': row.get('last_run'),
            }
        )
    return out
