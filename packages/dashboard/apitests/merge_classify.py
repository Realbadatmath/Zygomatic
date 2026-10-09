#!/usr/bin/env python3
"""Merge the hand-written risk classification into the generated route inventory.

The inventory (``apitests/routes.json``) is generated from each app's
``url_map`` and carries ``risk``/``empty_body_status`` as ``null`` placeholders.
The classification of the dashboard's body-method routes (POST/PUT/DELETE/PATCH)
was produced by reading every handler, and lives in two hand-written parts:

* ``apitests/classify_A.json``  — part A of the dashboard's body routes
* ``apitests/classify_B.json``  — part B

This script copies ``risk``, ``empty_body_status`` and ``why`` from those parts
onto the matching inventory entries and leaves every other byte of
``routes.json`` untouched (same ``indent=1, sort_keys=True`` serialisation the
generator used, so a no-op merge is a no-op diff).

GET-only routes have no body and therefore no risk class; what decides whether
the read-only sweep calls them is the inventory's ``danger`` flag, computed by
``inventory.route_danger``. ``apitests/classify_get.json`` overrides that flag
by hand for the cases the heuristic cannot see (a handler that acts through a
helper, a route that answers 5xx). It is applied here, after the heuristic.

It is strict on purpose: a body-method route with no classification, a
classification naming a route that is not in the inventory, a duplicate key, a
risk outside ``safe|validate|exclude`` or a gate that disagrees with the
inventory all abort the merge before anything is written.

Run from the crews directory:

    ../.venv/bin/python apitests/merge_classify.py            # merge in place
    ../.venv/bin/python apitests/merge_classify.py --check    # verify only
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

APITESTS_DIR = Path(__file__).resolve().parent
ROUTES_JSON = APITESTS_DIR / 'routes.json'
PARTS = (APITESTS_DIR / 'classify_A.json', APITESTS_DIR / 'classify_B.json')
GET_OVERRIDES = APITESTS_DIR / 'classify_get.json'

BODY_METHODS = {'POST', 'PUT', 'DELETE', 'PATCH'}
RISKS = ('safe', 'validate', 'exclude')


# A route is identified by (rule, endpoint): the same rule can appear twice with
# different methods and different handlers (e.g. /api/admin/schedule-pause has a
# GET endpoint and a POST endpoint), so the rule alone is not a key.
def _key(entry):
    return (entry['rule'], entry['endpoint'])


def load_classification():
    """(by_key, parts_meta) — the union of the classification parts."""
    by_key = {}
    meta = []
    for path in PARTS:
        doc = json.loads(path.read_text())
        rows = doc['routes']
        meta.append(
            {
                'file': path.name,
                'part': doc.get('part'),
                'routes': len(rows),
            }
        )
        for row in rows:
            for field in ('rule', 'endpoint', 'risk', 'why'):
                if field not in row:
                    raise SystemExit(f'{path.name}: entry {row.get("rule")!r} is missing {field!r}')
            if row['risk'] not in RISKS:
                raise SystemExit(f'{path.name}: {row["rule"]} has risk {row["risk"]!r}, expected one of {RISKS}')
            key = _key(row)
            if key in by_key:
                raise SystemExit(f'{path.name}: {key} is classified twice (also in {by_key[key]["_src"]})')
            row = dict(row, _src=path.name)
            by_key[key] = row
    return by_key, meta


def apply_get_overrides(dashboard):
    """Force ``danger`` on GET-only routes from classify_get.json. Returns a summary."""
    doc = json.loads(GET_OVERRIDES.read_text())
    by_key = {e['rule']: e for e in dashboard if e['methods'] == ['GET']}
    applied, redundant = [], []
    seen = set()
    for row in doc['routes']:
        for field in ('rule', 'endpoint', 'danger', 'why'):
            if field not in row:
                raise SystemExit(f'{GET_OVERRIDES.name}: entry {row.get("rule")!r} is missing {field!r}')
        if not isinstance(row['danger'], bool):
            raise SystemExit(f'{GET_OVERRIDES.name}: {row["rule"]} has danger {row["danger"]!r}, expected true/false')
        if row['rule'] in seen:
            raise SystemExit(f'{GET_OVERRIDES.name}: {row["rule"]} is overridden twice')
        seen.add(row['rule'])
        entry = by_key.get(row['rule'])
        if entry is None:
            raise SystemExit(f'{GET_OVERRIDES.name}: {row["rule"]} is not a GET-only dashboard route in the inventory')
        if entry['endpoint'] != row['endpoint']:
            raise SystemExit(
                f'{GET_OVERRIDES.name}: {row["rule"]} names endpoint {row["endpoint"]!r} but '
                f'the inventory says {entry["endpoint"]!r}'
            )
        (applied if entry['danger'] != row['danger'] else redundant).append(row['rule'])
        entry['danger'] = row['danger']
        entry['danger_why'] = row['why']
    return {
        'file': GET_OVERRIDES.name,
        'overrides': len(doc['routes']),
        'changed_the_heuristic': sorted(applied),
        'pinned_agreement': sorted(redundant),
    }


def merge(write=True):
    raw = ROUTES_JSON.read_text()
    doc = json.loads(raw)
    dashboard = doc['apps']['dashboard']
    body = [e for e in dashboard if BODY_METHODS & set(e['methods'])]
    if not body:
        raise SystemExit('routes.json holds no dashboard body-method routes')

    by_key, meta = load_classification()
    inventory_keys = {_key(e) for e in body}

    missing = sorted(inventory_keys - set(by_key))
    if missing:
        raise SystemExit(f'{len(missing)} dashboard body-method route(s) are unclassified, first 5: {missing[:5]}')
    stray = sorted(set(by_key) - inventory_keys)
    if stray:
        raise SystemExit(f'{len(stray)} classified route(s) are not in the inventory, first 5: {stray[:5]}')

    for entry in body:
        row = by_key[_key(entry)]
        if row.get('gate') is not None and row['gate'] != entry['gate']:
            raise SystemExit(
                f'{entry["rule"]}: classification says gate={row["gate"]!r} but '
                f'the inventory says {entry["gate"]!r} — the gate is read from '
                f'crewai_web_gui, so the classification is wrong'
            )
        entry['risk'] = row['risk']
        entry['empty_body_status'] = row.get('empty_body_status')
        entry['why'] = row['why']

    get_overrides = apply_get_overrides(dashboard)

    # Same serialisation as the generator: indent=1, sort_keys=True, trailing \n.
    out = json.dumps(doc, indent=1, sort_keys=True) + '\n'
    changed = out != raw
    if write and changed:
        ROUTES_JSON.write_text(out)

    counts = Counter(e['risk'] for e in body)
    get_only = [e for e in dashboard if e['methods'] == ['GET']]
    return {
        'parts': meta,
        'body_routes': len(body),
        'get_only_routes': len(get_only),
        'get_only_danger': sum(1 for e in get_only if e['danger']),
        'get_only_external': sum(1 for e in get_only if e['external']),
        'get_overrides': get_overrides,
        'by_risk': dict(sorted(counts.items())),
        'by_gate': dict(sorted(Counter(e['gate'] for e in body).items())),
        'with_empty_body_status': sum(1 for e in body if e['empty_body_status'] is not None),
        'changed': changed,
        'written': bool(write and changed),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--check', action='store_true', help='validate and report, but do not write routes.json')
    args = ap.parse_args(argv)

    result = merge(write=not args.check)
    print(json.dumps(result, indent=2))
    if args.check and result['changed']:
        print('routes.json is NOT up to date with the classification', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
