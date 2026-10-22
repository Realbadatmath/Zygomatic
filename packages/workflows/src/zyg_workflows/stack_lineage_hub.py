# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""stack_lineage_hub.py — the Metrics > Lineage collector and store (:5000/metrics,
subtab Lineage). 2026-10-04.

What this tab answers, for EVERY model and tool the program has used: what it was for,
what went wrong with it, what the thing that replaced it actually fixed, and what is
still wrong today. The dated decision-by-decision chart is
``docs/stack_upgrade_history.md``; this is its entity-keyed twin, so the same history can
be read per tool instead of per day.

The store is the interface — the board computes nothing it cannot derive
----------------------------------------------------------------------------------------
One JSON file per lane in ``data/stack_lineage/<lane>.json``. A lane file is:

    {"lane": "image", "label": "Image generation", "note": "one line",
     "entities": [ {...}, ... ]}

An entity is one model, tool, service or dataset:

    {
      "id": "flux1_dev",                  # unique across the whole store, stable
      "name": "FLUX.1-dev",
      "kind": "model" | "tool" | "service" | "dataset",
      "role": "what job it held",
      "status": one of STATUSES (live, fallback, gated_off, paused, retired, removed,
                                rejected, candidate, broken, unrecorded)
      "licence": "BFL Non-Commercial",   # as READ, not as assumed
      "adopted": "2026-05-08",           # ISO date or '' when undatable
      "ended":   "2026-08-26",
      "replaced":    ["sd15"],           # ids it took over from
      "replaced_by": ["flux2_klein_4b"], # ids that took over from it
      "where": "comfy_generation_service.py",
      "summary": "one or two sentences",
      "issues": [ {...} ],
      "sources": ["project_licence_gate", "docs/stack_upgrade_history.md §1"]
    }

An issue is ONE thing that was wrong, or one thing a swap fixed:

    {
      "text":  "what was wrong, in one sentence, with the number if there is one",
      "state": "open" | "solved" | "mitigated" | "accepted" | "unmeasured",
      "found": "2026-08-09",             # when it was first recorded
      "fixed": "2026-08-25",             # only with state solved
      "by":    "flux2_klein_4b",         # the entity that fixed it, when there is one
      "grade": "measured" | "receipt" | "licence" | "operator" | "vendor" | "assumed",
      "evidence": "project_licence_gate" # the file that says so
    }

``state`` is what the operator asked this tab to show: `open` and `unmeasured` are "still
there", `solved` is "the upgrade fixed it", `mitigated`/`accepted` are "worked around or
paid for on purpose". ``grade`` is the honesty lever, the same ladder the Capabilities tab
uses ([[feedback_measure_before_claim]]): `measured` means a bench in this repo produced
the number, `receipt` means a production run or a commit records it, `licence` means a
licence was read in full, `operator` means it was a ruling, `vendor` means a model card
claims it and we have not checked, `assumed` means someone reasoned it. Nothing here
upgrades a grade on its own, and an entity with no issues recorded reads as "nothing
recorded", never as "no problems".

What the collector derives (and therefore what must NOT be written down):
  * ``solved_for`` — read off OTHER entities' issues that name this one in ``by``. The
    "what upgrading fixed" column is the predecessors' own problem list, so it can never
    disagree with it.
  * ``chains`` — the lineage order inside a lane, walked from replaced/replaced_by.
  * every count, the timeline, and the open-issue ranking.

Adding a row: edit the lane file the day a swap goes live, with the evidence named, then
add the same row to ``docs/stack_upgrade_history.md``. ``python3 stack_lineage_hub.py
check`` validates ids, links, enums and dates and is the only thing standing between a
typo and a silently empty card.
"""

import json
import os
import re
import time
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, 'data', 'stack_lineage')
CHART = 'docs/stack_upgrade_history.md'

KINDS = ('model', 'tool', 'service', 'dataset')
# Order is the reading order on the board: what runs now, then what is held back, then
# what is gone, then what was refused.
STATUSES = (
    'live',
    'fallback',
    'gated_off',
    'paused',
    'broken',
    'retired',
    'removed',
    'rejected',
    'candidate',
    'unrecorded',
)
STATUS_LABEL = {
    'live': 'Live',
    'fallback': 'Fallback',
    'gated_off': 'Installed, default off',
    'paused': 'Paused',
    'broken': 'Broken',
    'retired': 'Retired',
    'removed': 'Removed',
    'rejected': 'Measured and refused',
    'candidate': 'Candidate, never installed',
    'unrecorded': 'Unrecorded',
}
# A status is 'in the stack' if something can still call it today.
IN_STACK = ('live', 'fallback', 'gated_off', 'paused', 'broken')

STATES = ('open', 'unmeasured', 'mitigated', 'accepted', 'solved')
STATE_LABEL = {
    'open': 'Still open',
    'unmeasured': 'Not measured',
    'mitigated': 'Worked around',
    'accepted': 'Accepted cost',
    'solved': 'Fixed',
}
GRADES = ('measured', 'receipt', 'licence', 'operator', 'vendor', 'assumed')
GRADE_LABEL = {
    'measured': 'measured here',
    'receipt': 'production receipt',
    'licence': 'licence read',
    'operator': 'operator ruling',
    'vendor': 'vendor claim',
    'assumed': 'reasoned',
}

_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

_CACHE = {'mtime': 0.0, 'data': None}


# ── store ────────────────────────────────────────────────────────────────────


def _store_files():
    try:
        return sorted(
            os.path.join(STORE, f) for f in os.listdir(STORE) if f.endswith('.json') and not f.startswith('.')
        )
    except OSError:
        return []


def _store_mtime(files):
    m = 0.0
    for p in files:
        try:
            m = max(m, os.path.getmtime(p))
        except OSError as _exc:
            _zyg_log.debug('mtime of %s unavailable, not counted: %s', p, _exc)
    # A deleted lane file changes the count, not the newest mtime.
    return (m, len(files))


def load_store(fresh=False):
    """Every lane file, plus the problems found while reading them. Cached on mtime so a
    board poll costs one stat per file (same rule as the other hub collectors)."""
    files = _store_files()
    key = _store_mtime(files)
    if not fresh and _CACHE['data'] is not None and _CACHE['mtime'] == key:
        return _CACHE['data']
    lanes, problems = [], []
    for path in files:
        name = os.path.basename(path)
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                raw = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            problems.append(f'{name}: unreadable ({type(exc).__name__}: {exc})')
            continue
        lane = str(raw.get('lane') or os.path.splitext(name)[0])
        ents = raw.get('entities')
        if not isinstance(ents, list):
            problems.append(f'{name}: no entities list')
            ents = []
        lanes.append(
            {
                'lane': lane,
                'label': raw.get('label') or lane.title(),
                'note': raw.get('note') or '',
                'file': name,
                'entities': [e for e in ents if isinstance(e, dict)],
            }
        )
    data = {'lanes': lanes, 'problems': problems, 'files': [os.path.basename(p) for p in files]}
    _CACHE.update(mtime=key, data=data)
    return data


def validate(fresh=True):
    """Problems a reader cannot see: duplicate ids, links to nothing, bad enums, bad
    dates, an issue with no evidence. Returns a list of strings, empty when clean."""
    store = load_store(fresh=fresh)
    bad = list(store['problems'])
    seen = {}
    for lane in store['lanes']:
        for e in lane['entities']:
            eid = e.get('id')
            where = f'{lane["file"]}:{eid or e.get("name") or "?"}'
            if not eid:
                bad.append(f'{where}: entity with no id')
                continue
            if eid in seen:
                bad.append(f'{where}: duplicate id, also in {seen[eid]}')
            seen[eid] = lane['file']
            if not e.get('name'):
                bad.append(f'{where}: no name')
            if not e.get('summary'):
                bad.append(f'{where}: no summary')
            if e.get('kind') not in KINDS:
                bad.append(f'{where}: kind {e.get("kind")!r} not in {KINDS}')
            if e.get('status') not in STATUSES:
                bad.append(f'{where}: status {e.get("status")!r} not in {STATUSES}')
            for field in ('adopted', 'ended'):
                v = e.get(field, '')
                if v and not _DATE.match(str(v)):
                    bad.append(f'{where}: {field} {v!r} is not an ISO date')
            for i, iss in enumerate(e.get('issues') or []):
                tag = f'{where}#issue{i}'
                if not isinstance(iss, dict) or not iss.get('text'):
                    bad.append(f'{tag}: no text')
                    continue
                if iss.get('state') not in STATES:
                    bad.append(f'{tag}: state {iss.get("state")!r} not in {STATES}')
                if iss.get('grade') not in GRADES:
                    bad.append(f'{tag}: grade {iss.get("grade")!r} not in {GRADES}')
                if not iss.get('evidence'):
                    bad.append(f'{tag}: no evidence named')
                if iss.get('state') == 'solved' and not (iss.get('fixed') or iss.get('by')):
                    bad.append(f'{tag}: solved with neither a fix date nor a fixer')
                for field in ('found', 'fixed'):
                    v = iss.get(field, '')
                    if v and not _DATE.match(str(v)):
                        bad.append(f'{tag}: {field} {v!r} is not an ISO date')
    # Links are checked after every id is known, so order in the store does not matter.
    for lane in store['lanes']:
        for e in lane['entities']:
            for field in ('replaced', 'replaced_by'):
                for ref in e.get(field) or []:
                    if ref not in seen:
                        bad.append(f'{lane["file"]}:{e.get("id")}: {field} -> unknown id {ref!r}')
            for iss in e.get('issues') or []:
                by = isinstance(iss, dict) and iss.get('by')
                if by and by not in seen:
                    bad.append(f'{lane["file"]}:{e.get("id")}: issue by -> unknown id {by!r}')
    return bad


# ── derivation ───────────────────────────────────────────────────────────────


def _month(date):
    return str(date)[:7] if date and _DATE.match(str(date)) else ''


def _chains(entities):
    """Lineage orders inside a lane, walked forward over replaced_by. A chain starts at an
    entity nothing in this lane replaced, and stops when a link leaves the lane (the id is
    kept so the card can still name it)."""
    by_id = {e['id']: e for e in entities if e.get('id')}
    succ = {i: [r for r in (e.get('replaced_by') or []) if r in by_id] for i, e in by_id.items()}
    has_pred = set()
    for i, e in by_id.items():
        for r in succ[i]:
            has_pred.add(r)
        for r in e.get('replaced') or []:
            if r in by_id:
                has_pred.add(i)
    chains = []
    for root in [i for i in by_id if i not in has_pred]:
        # Depth-first, longest branch first; a diamond is walked once per branch.
        stack = [[root]]
        while stack:
            path = stack.pop()
            nxt = [r for r in succ[path[-1]] if r not in path]
            if not nxt:
                if len(path) > 1:
                    chains.append(path)
                continue
            for r in nxt:
                stack.append(path + [r])
    chains.sort(key=len, reverse=True)
    # A diamond (A replaced by both B and C, both replaced by D) yields the long walk AND
    # the short one. The short one says nothing the long one does not, so drop any chain
    # that is a subsequence of one already kept.
    kept = []
    for c in chains:
        if not any(_subseq(c, k) for k in kept):
            kept.append(c)
    return kept


def _subseq(small, big):
    it = iter(big)
    return all(any(x == y for y in it) for x in small)


def build(fresh=False):
    store = load_store(fresh=fresh)
    names, lane_of = {}, {}
    for lane in store['lanes']:
        for e in lane['entities']:
            if e.get('id'):
                names[e['id']] = e.get('name') or e['id']
                lane_of[e['id']] = lane['lane']

    # What each entity fixed FOR SOMEONE ELSE, read off the other entity's own issue list.
    solved_for = {}
    for lane in store['lanes']:
        for e in lane['entities']:
            for iss in e.get('issues') or []:
                by = iss.get('by')
                if by and by != e.get('id'):
                    solved_for.setdefault(by, []).append(
                        {
                            'entity': e.get('id'),
                            'entity_name': names.get(e.get('id'), e.get('id')),
                            'lane': lane['lane'],
                            'text': iss.get('text'),
                            'fixed': iss.get('fixed', ''),
                            'grade': iss.get('grade', 'assumed'),
                            'evidence': iss.get('evidence', ''),
                        }
                    )

    totals = {'entities': 0, 'lanes': 0, 'issues': 0, 'documented': 0, 'undocumented': 0}
    state_counts = {s: 0 for s in STATES}
    status_counts = {s: 0 for s in STATUSES}
    kind_counts = {k: 0 for k in KINDS}
    grade_counts = {g: 0 for g in GRADES}
    months = {}
    open_issues = []
    out_lanes = []

    def bump_month(key, field, label):
        if not key:
            return
        m = months.setdefault(key, {'month': key, 'adopted': 0, 'ended': 0, 'fixed': 0, 'found': 0, 'events': []})
        m[field] += 1
        if label and len(m['events']) < 40:
            m['events'].append(label)

    for lane in store['lanes']:
        ents = [e for e in lane['entities'] if e.get('id')]
        lane_state = {s: 0 for s in STATES}
        lane_status = {s: 0 for s in STATUSES}
        rows = []
        for e in ents:
            eid = e['id']
            issues = [i for i in (e.get('issues') or []) if isinstance(i, dict) and i.get('text')]
            counts = {s: 0 for s in STATES}
            for iss in issues:
                st = iss.get('state') if iss.get('state') in STATES else 'unmeasured'
                gr = iss.get('grade') if iss.get('grade') in GRADES else 'assumed'
                counts[st] += 1
                state_counts[st] += 1
                lane_state[st] += 1
                grade_counts[gr] += 1
                if st in ('open', 'unmeasured'):
                    open_issues.append(
                        {
                            'entity': eid,
                            'entity_name': e.get('name') or eid,
                            'lane': lane['lane'],
                            'lane_label': lane['label'],
                            'status': e.get('status'),
                            'state': st,
                            'in_stack': e.get('status') in IN_STACK,
                            'text': iss.get('text'),
                            'found': iss.get('found', ''),
                            'grade': gr,
                            'evidence': iss.get('evidence', ''),
                        }
                    )
                if st == 'solved':
                    bump_month(_month(iss.get('fixed')), 'fixed', None)
                else:
                    bump_month(_month(iss.get('found')), 'found', None)
            status = e.get('status') if e.get('status') in STATUSES else 'unrecorded'
            kind = e.get('kind') if e.get('kind') in KINDS else 'tool'
            status_counts[status] += 1
            kind_counts[kind] += 1
            lane_status[status] += 1
            totals['entities'] += 1
            totals['issues'] += len(issues)
            totals['documented' if issues else 'undocumented'] += 1
            bump_month(_month(e.get('adopted')), 'adopted', f'+ {e.get("name")}')
            bump_month(_month(e.get('ended')), 'ended', f'- {e.get("name")}')
            rows.append(
                dict(
                    e,
                    lane=lane['lane'],
                    lane_label=lane['label'],
                    kind=kind,
                    status=status,
                    status_label=STATUS_LABEL[status],
                    in_stack=status in IN_STACK,
                    issues=issues,
                    issue_counts=counts,
                    open_count=counts['open'] + counts['unmeasured'],
                    solved_count=counts['solved'],
                    replaced_names=[names.get(r, r) for r in (e.get('replaced') or [])],
                    replaced_by_names=[names.get(r, r) for r in (e.get('replaced_by') or [])],
                    solved_for=solved_for.get(eid, []),
                )
            )
        # Live first, then held back, then gone; inside a group the most problems first.
        rows.sort(key=lambda r: (STATUSES.index(r['status']), -r['open_count'], -r['solved_count'], r['name'].lower()))
        totals['lanes'] += 1
        out_lanes.append(
            {
                'lane': lane['lane'],
                'label': lane['label'],
                'note': lane['note'],
                'file': lane['file'],
                'counts': {
                    'entities': len(rows),
                    'in_stack': sum(1 for r in rows if r['in_stack']),
                    'open': lane_state['open'] + lane_state['unmeasured'],
                    'solved': lane_state['solved'],
                    'issues': sum(len(r['issues']) for r in rows),
                },
                'status_counts': lane_status,
                'state_counts': lane_state,
                'chains': [{'ids': c, 'names': [names.get(i, i) for i in c]} for c in _chains(ents)],
                'entities': rows,
            }
        )

    out_lanes.sort(key=lambda l: -l['counts']['entities'])
    # Ranked by what the operator can still act on: something that is in the stack today,
    # then a measured number over a reasoned one, then the newest finding first. An open
    # issue on a refused candidate is the reason it was refused, so it sorts last.
    open_issues.sort(
        key=lambda i: (
            not i['in_stack'],
            GRADES.index(i['grade']) if i['grade'] in GRADES else 9,
            i['state'] != 'open',
            [-ord(c) for c in (i['found'] or '0000-00-00')],
            i['entity_name'],
        )
    )
    dated = [m for m in months if m]
    timeline = [months[m] for m in sorted(dated)]
    adopted_dates = sorted(
        d for d in (e.get('adopted') for lane in store['lanes'] for e in lane['entities']) if d and _DATE.match(str(d))
    )

    problems = validate(fresh=False)
    payload = {
        'success': True,
        'totals': dict(
            totals,
            in_stack=sum(1 for l in out_lanes for e in l['entities'] if e['in_stack']),
            gone=sum(status_counts[s] for s in ('retired', 'removed')),
            refused=status_counts['rejected'] + status_counts['candidate'],
            open=state_counts['open'] + state_counts['unmeasured'],
            solved=state_counts['solved'],
            carried=state_counts['mitigated'] + state_counts['accepted'],
        ),
        'status_counts': status_counts,
        'kind_counts': kind_counts,
        'state_counts': state_counts,
        'grade_counts': grade_counts,
        'labels': {'status': STATUS_LABEL, 'state': STATE_LABEL, 'grade': GRADE_LABEL},
        'span': {
            'first': adopted_dates[0] if adopted_dates else '',
            'last': adopted_dates[-1] if adopted_dates else '',
        },
        'timeline': timeline,
        'lanes': out_lanes,
        'open_issues': open_issues,
        'store': {'path': os.path.relpath(STORE, HERE), 'files': store['files'], 'chart': CHART},
        'problems': problems,
        'notes': [
            'One row per model or tool, not per decision: the dated decision-by-decision chart is '
            + CHART
            + ', and this is its entity-keyed twin.',
            "What an upgrade FIXED is never written on the upgrade — it is read off the predecessor's own "
            'issue list (the "by" field), so the two can never disagree.',
            'Every issue names the file that says so, and carries a grade: measured here, production receipt, '
            'licence read, operator ruling, vendor claim, or reasoned. A vendor claim is a claim, not a fact.',
            'An entity with no issues recorded reads as "nothing recorded", never as "no problems" — '
            + str(totals['undocumented'])
            + ' of '
            + str(totals['entities'])
            + ' entities are in that state.',
            'Dates are the date in the record (the day the decision was taken or deployed). Nothing before '
            '2026-05-08 is recorded on this box, and crews auto-snapshots stop at 2026-08-04, so later swaps '
            'are dated from memory files and backup directories rather than from commits.',
        ],
        'limitations': [
            'Coverage is the chart plus the memory files it cites. A tool that was never written down is not here.',
            'Statuses are as of the last store edit, not probed live: this tab does not ask the GPU what is loaded.',
            'Rejections are kept deliberately — a refused upgrade is a decision with a reason, and the reason '
            'is usually a measurement that would otherwise be lost.',
        ],
    }
    payload['data_version'] = _version(payload)
    return payload


def _version(payload):
    """djb2 over the store-derived parts of the payload, so a poll that reads the same
    store says 'Checked' rather than 'Updated' (same rule as the other boards)."""
    try:
        s = json.dumps([payload['lanes'], payload['totals'], payload['problems']], sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        return str(int(time.time()))
    h = 5381
    for ch in s:
        h = ((h * 33) ^ ord(ch)) & 0xFFFFFFFF
    return format(h, 'x')


def section_stack_lineage(days=30, now=None, fresh=False):
    """Metrics > Lineage (2026-10-04): one card per model/tool — what it was for, what went
    wrong, what the replacement fixed, what is still open. `days` is ignored: a lineage is
    what is true now plus everything before it, not a window."""
    return build(fresh=fresh)


if __name__ == '__main__':  # the CLI lives in stack_lineage_hub_cli
    from zyg_workflows.stack_lineage_hub_cli import main as _cli_main

    raise SystemExit(_cli_main())
