# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""STEP 4 / 4b — fusion with attribution, and the cross-run lesson memory."""

import json
import os
import time
import logging as _zyg_logging

from zyg_workflows.vlm_report.constants import (
    LESSONS_PATH,
    SEVERITY_ORDER,
    STATUS_ORDER,
    VLM_CLASS,
    VLM_UNRELIABLE_PASS,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.vlm_report')

# ── STEP 4: fusion + attribution ─────────────────────────────────────────────


def _release_judges(log):
    """Shut down any resident VLM judge held by vlm_inspector's persistent pool.

    Sibling of _release_detectors, and needed for the same reason: this stage is
    followed by work that wants the card back. The persistent judge
    (ZYG_VLM_PERSISTENT, added 2026-08-03 after the report stage was measured
    reloading an 8B checkpoint 57 times) holds ~10.7 GB between requests and would
    otherwise sit there until its 180s idle watchdog fires — long enough for the
    next render's wait_for_vram to stall on VRAM nothing is using.

    In the `finally` arm on purpose: a judge must be released even when the
    analysis raised, or a crashed report stage strands the GPU.
    """
    try:
        from zyg_workflows import vlm_inspector as VLM

        fn = getattr(VLM, 'shutdown_workers', None)
        if callable(fn):
            fn(log_fn=None)
    except Exception as e:
        log(f'judge release skipped ({e})')


def _release_detectors(log):
    """Drop GroundingDINO/SAM2/DINOv2 out of THIS process's VRAM.

    continuity_qc caches its models in a module dict keyed by (kind, device), so
    after grounding they sit on the card for the rest of the run. The boundary
    synthesis tier needs ~40 GB free; a forgotten 0.7 GB Swin-T is enough to
    force a silent downshift to the 8 B judge for the one step that most wants
    the 32 B. Called after ALL detector work is done.
    """
    try:
        from zyg_workflows import continuity_qc as CQ

        n = len(getattr(CQ, '_CACHE', {}) or {})
        CQ._CACHE.clear()
        import gc

        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception as _exc:
            _zyg_log.debug('vram release skipped: %s', _exc)
        log(f'released {n} cached detector model(s) from VRAM')
    except Exception as e:
        log(f'detector release skipped ({e})')


def _new_finding(region, klass, severity):
    return {
        'id': f'{region}:{klass}',
        'region': region,
        'defect_class': klass,
        'severity': severity,
        'status': 'pass',
        'source': None,
        'signals': [],
        'times': [],
        'boxes': [],
        'evidence': [],
        'caveats': [],
    }


def _fuse(vlm_results, localized, pixel, targets, log):
    """One row per (region, defect class); source = who witnessed it.

    A row seen by both halves gets source 'both' — that is the corroboration an
    operator can trust. A row seen only by the judge is 'vlm' (and carries the
    measured-blind-spot caveat where one exists); a row seen only by the metrics
    is 'pixel', which is the ONLY way frozen/morph defects can ever appear.
    """
    F = {}

    def _get(region, klass, severity):
        key = f'{region}:{klass}'
        if key not in F:
            F[key] = _new_finding(region, klass, severity)
        f = F[key]
        if SEVERITY_ORDER.get(severity, 0) > SEVERITY_ORDER.get(f['severity'], 0):
            f['severity'] = severity
        return f

    loc_by_item = {}
    for l in localized:
        loc_by_item.setdefault(l['item'], []).append(l)

    # ---- VLM signals --------------------------------------------------------
    for r in vlm_results:
        iid = r['item']
        region, klass = VLM_CLASS.get(iid, (r['target'], iid))
        sev = str(r.get('severity') or 'major').lower()
        f = _get(region, klass, sev)
        status = 'unknown' if (r['ok'] is None or r['skipped']) else ('pass' if r['ok'] else 'fail')
        sig = {
            'source': 'vlm',
            'name': iid,
            'asked_on': r['target'],
            'status': status,
            'answer': r.get('answer'),
            'expected': r.get('expected'),
            'k': r.get('k'),
            'votes': r.get('votes'),
            'reason': r.get('reason'),
            'model': r.get('model'),
            'tier': r.get('tier'),
        }
        if r.get('skipped'):
            sig['skipped_reason'] = r.get('skip_reason')
        if r.get('localize_note'):
            sig['note'] = r['localize_note']
        hits = [l for l in loc_by_item.get(iid, []) if l['target'] == r['target'] and l['ok'] is False]
        if hits:
            sig['fail_times'] = sorted({h['t'] for h in hits})
            f['times'] = sorted(set(f['times']) | set(sig['fail_times']))
            for h in hits:
                if h.get('bbox_full'):
                    f['boxes'].append(
                        {
                            't': h['t'],
                            'box_frac': h['bbox_full'],
                            'from_crop': os.path.basename(h['crop']),
                            'source': 'vlm-grounding',
                        }
                    )
                f['evidence'].append(h['crop'])
        elif status == 'fail':
            f['evidence'] += (r.get('crops') or [])[:4]
        if status == 'pass' and iid in VLM_UNRELIABLE_PASS:
            f['caveats'].append(f'{iid}: {VLM_UNRELIABLE_PASS[iid]}')
        f['signals'].append(sig)
        if STATUS_ORDER.get(status, 0) > STATUS_ORDER.get(f['status'], 0):
            f['status'] = status

    # ---- pixel signals ------------------------------------------------------
    rf = pixel.get('region_flow') or {}
    minf = rf.get('_min_flow') or {}
    for name, rec in (rf.get('regions') or {}).items():
        f = _get(name, 'motion', 'critical' if minf.get(name, 0) > 0 else 'major')
        status = 'pass' if rec.get('ok') else 'fail'
        why = []
        if minf.get(name, 0) > 0 and rec.get('flow_mean', 0) < minf.get(name, 0):
            why.append(f'flow {rec["flow_mean"]:.3f} px/sample < min {minf[name]} -> region FROZEN')
        if rec.get('churn_p95', 0) > 0.55:
            why.append(f'edge churn p95 {rec["churn_p95"]:.3f} > 0.55 -> structure re-drawn (morph/boil)')
        f['signals'].append(
            {
                'source': 'pixel',
                'name': f'region_flow:{name}',
                'status': status,
                'measured': rec,
                'threshold': {'min_flow': minf.get(name), 'max_churn_p95': 0.55},
                'reason': '; '.join(why) or 'within gate',
            }
        )
        if STATUS_ORDER.get(status, 0) > STATUS_ORDER.get(f['status'], 0):
            f['status'] = status
        tg = targets.get(name)
        if tg and status == 'fail':
            f['boxes'].append({'t': None, 'box_frac': tg['box_frac'], 'source': 'flow-region'})
            f['evidence'] += [c['path'] for c in (tg.get('crops') or [])[:3]]

    for role, pc in (pixel.get('prop_consistency') or {}).items():
        klass = 'prop_handling' if role == 'pipe' else 'prop_integrity'
        f = _get(role, klass, 'major')
        bad = [p for p in (pc.get('pairs') or []) if not p.get('ok')]
        status = 'fail' if bad else ('unknown' if pc.get('error') else 'pass')
        ncc = [p['ncc'] for p in (pc.get('pairs') or [])]
        f['signals'].append(
            {
                'source': 'pixel',
                'name': f'prop_consistency:{role}',
                'status': status,
                'measured': {
                    'ncc_min': round(min(ncc), 3) if ncc else None,
                    'ncc_max': round(max(ncc), 3) if ncc else None,
                    'pairs': pc.get('pairs'),
                },
                'threshold': {'ncc_min': 0.70},
                'reason': (
                    f'{len(bad)} context-window seam(s) below NCC 0.70 — the prop was re-imagined across the boundary'
                    if bad
                    else f'all {len(ncc)} seams NCC {min(ncc):.3f}-{max(ncc):.3f} '
                    f'>= 0.70 — prop stable across every chain boundary'
                    if ncc
                    else pc.get('error') or 'no pairs'
                ),
            }
        )
        if bad:
            f['times'] = sorted(set(f['times']) | {p['t1'] for p in bad})
        if STATUS_ORDER.get(status, 0) > STATUS_ORDER.get(f['status'], 0):
            f['status'] = status

    hq = pixel.get('hands') or {}
    if hq and not hq.get('error'):
        f = _get('frame', 'anatomy_hands', 'critical')
        # ok is None when qc_hands_clip never reached a decision (it initializes
        # to None). That is UNKNOWN, not clean — folding it into 'pass' would let
        # a dead detector look like healthy anatomy.
        status = {True: 'pass', False: 'fail'}.get(hq.get('ok'), 'unknown')
        f['signals'].append(
            {
                'source': 'pixel',
                'name': 'anatomy_qc.qc_hands_clip',
                'status': status,
                'measured': {
                    'frames_sampled': hq.get('frames_sampled'),
                    'frames_with_hands': hq.get('frames_with_hands'),
                    'detect_rate': hq.get('detect_rate'),
                    'issue_counts': hq.get('issue_counts'),
                    'chirality_flips': hq.get('chirality_flips'),
                    'expected_hands': hq.get('expected_hands'),
                },
                'threshold': {'issues': 'none'},
                'reason': '; '.join(str(i) for i in (hq.get('issues') or [])[:4]) or 'no MediaPipe hand issues',
            }
        )
        if STATUS_ORDER.get(status, 0) > STATUS_ORDER.get(f['status'], 0):
            f['status'] = status

    ao = pixel.get('action_ownership') or {}
    if ao and not ao.get('error'):
        f = _get('boy', 'action_ownership', 'critical')
        checks = ao.get('checks') or []
        wrong = [c for c in checks if c.get('verdict') == 'wrong-owner']
        decided = [c for c in checks if c.get('verdict') in ('wrong-owner', 'correct-owner')]
        # 'prop-not-found' / 'ambiguous' are NOT passes: the gate could not
        # attribute the prop, which is unknown, not clean.
        status = 'fail' if wrong else ('pass' if decided else 'unknown')
        f['signals'].append(
            {
                'source': 'pixel',
                'name': 'continuity_qc.action_ownership',
                'status': status,
                'measured': {'checks': checks, 'verdicts': [c.get('verdict') for c in checks]},
                'threshold': {'expected_owner': 'man'},
                'reason': (
                    f'{len(wrong)} timestamp(s) where the grounded pipe box was owned by the BOY, not the man'
                    if wrong
                    else f'pipe grounded to the man at all {len(decided)} decidable timestamps'
                    if decided
                    else f'no timestamp was decidable '
                    f'({[c.get("verdict") for c in checks]}) — the prop could '
                    f'not be grounded, so ownership is UNKNOWN, not clean'
                ),
            }
        )
        if STATUS_ORDER.get(status, 0) > STATUS_ORDER.get(f['status'], 0):
            f['status'] = status

    cont = pixel.get('continuity') or {}
    for obj in cont.get('objects') or []:
        role = obj.get('name') or 'object'
        f = _get(role, 'prop_integrity', 'major')
        status = 'pass' if obj.get('verdict') == 'present' else 'fail'
        f['signals'].append(
            {
                'source': 'pixel',
                'name': f'continuity:{role}',
                'status': status,
                'measured': obj,
                'reason': f'verdict={obj.get("verdict")} flags={obj.get("flags")}',
            }
        )
        if STATUS_ORDER.get(status, 0) > STATUS_ORDER.get(f['status'], 0):
            f['status'] = status

    # ---- attribution --------------------------------------------------------
    findings = []
    for f in F.values():
        srcs = {s['source'] for s in f['signals']}
        f['source'] = 'both' if srcs == {'vlm', 'pixel'} else ('vlm' if srcs == {'vlm'} else 'pixel')
        if f['source'] == 'vlm' and f['status'] == 'pass':
            f['caveats'].append(
                'single witness (judge only) — no pixel metric '
                'covers this defect class, so a PASS is weaker '
                'than a corroborated one'
            )
        if f['source'] == 'both':
            v = [s['status'] for s in f['signals'] if s['source'] == 'vlm']
            p = [s['status'] for s in f['signals'] if s['source'] == 'pixel']
            if ('fail' in v) != ('fail' in p):
                f['caveats'].append(
                    f'WITNESSES DISAGREE: judge={"fail" if "fail" in v else "pass"}, '
                    f'metrics={"fail" if "fail" in p else "pass"}'
                )
        f['evidence'] = sorted(set(f['evidence']))[:8]
        findings.append(f)
    findings.sort(key=lambda x: (-STATUS_ORDER.get(x['status'], 0), -SEVERITY_ORDER.get(x['severity'], 0), x['id']))
    log(f'fused {len(findings)} findings ({sum(1 for f in findings if f["status"] == "fail")} failing)')
    return findings


def _verdict_of(findings):
    crit = [f for f in findings if f['status'] == 'fail' and f['severity'] == 'critical']
    maj = [f for f in findings if f['status'] == 'fail' and f['severity'] == 'major']
    if crit:
        return 'FAIL', crit, maj
    if maj:
        return 'FAIL(major)', crit, maj
    return 'PASS', crit, maj


# ── STEP 4b: cross-run memory ────────────────────────────────────────────────

# Gate-name prefixes this reporter considers RELATED history. Its own rows come
# back as 'vlm_report:*', but the interesting cross-run memory on run 1 is what
# the rest of the QC battery already recorded about the same defect classes —
# without these prefixes a first run would be told "no prior runs" while the
# ledger holds a dozen relevant outcomes for the same scene.
RELATED_GATE_PREFIXES = (
    'vlm_report:',
    'region_flow',
    'prop_',
    'motion',
    'anatomy.hands',
    'anatomy.face',
    'action_ownership',
    'continuity:',
    'chain_seams',
    'color_drift',
    'camera_motion',
    'set_',
    'track:',
    'identity',
)


def _prior_context(gate_names, scene_key, days=21):
    """What previous runs already know: ledger trends + this scene's lessons.

    This is the self-improvement input. Without it every run starts cold and the
    LLM cannot say "this is the third run in a row where the boy's hand froze" —
    which is the single most useful sentence a reporter can produce.
    """
    out = {'trends': [], 'lessons': [], 'error': None}
    try:
        from zyg_workflows import run_ledger

        t = run_ledger.trends(days=days)
        if t.get('ok'):
            want = set(gate_names)
            out['trends'] = [
                g
                for g in (t.get('gates') or [])
                if g.get('gate') in want or str(g.get('gate', '')).startswith(RELATED_GATE_PREFIXES)
            ]
            out['alerts'] = t.get('alerts') or []
            out['runs'] = t.get('runs')
    except Exception as e:
        out['error'] = str(e)[:200]
    try:
        if os.path.isfile(LESSONS_PATH):
            with open(LESSONS_PATH, encoding='utf-8') as f:
                rows = [json.loads(ln) for ln in f if ln.strip()]
            out['lessons'] = [r for r in rows if r.get('scene') == scene_key][-8:]
    except (OSError, ValueError) as _exc:
        _zyg_log.warning('prior lessons unreadable, continuing without them: %s', _exc)
    return out


def _append_lessons(scene_key, run_id, clip, findings, synthesis_text):
    """Persist this run's diagnosis so the NEXT run is told about it."""
    try:
        os.makedirs(os.path.dirname(LESSONS_PATH), exist_ok=True)
        rows = []
        for f in findings:
            if f['status'] != 'fail':
                continue
            rows.append(
                {
                    'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    'scene': scene_key,
                    'run_id': run_id,
                    'clip': os.path.basename(clip),
                    'finding': f['id'],
                    'severity': f['severity'],
                    'source': f['source'],
                    'times': f['times'][:6],
                    'signals': [
                        {'name': s['name'], 'status': s['status'], 'reason': str(s.get('reason'))[:220]}
                        for s in f['signals']
                    ],
                    'llm_cause': (synthesis_text or '')[:900],
                }
            )
        if not rows:
            rows = [
                {
                    'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    'scene': scene_key,
                    'run_id': run_id,
                    'clip': os.path.basename(clip),
                    'finding': None,
                    'severity': None,
                    'source': None,
                    'note': 'clean run — every gate passed',
                }
            ]
        with open(LESSONS_PATH, 'a', encoding='utf-8') as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        return len(rows)
    except Exception:
        return 0


def _ledger_write(run_id, findings, log):
    n = 0
    try:
        from zyg_workflows import run_ledger

        for f in findings:
            outcome = {'pass': 'pass', 'fail': 'fail'}.get(f['status'], 'unknown')
            score = None
            for s in f['signals']:
                m = s.get('measured') or {}
                if isinstance(m, dict) and m.get('flow_mean') is not None:
                    score = m['flow_mean']
                    break
                if isinstance(m, dict) and m.get('ncc_min') is not None:
                    score = m['ncc_min']
                    break
            if run_ledger.record_gate(run_id, f'vlm_report:{f["id"]}', outcome, score=score, tag=f['source'] or ''):
                n += 1
    except Exception as e:
        log(f'ledger write failed ({e})')
    return n
