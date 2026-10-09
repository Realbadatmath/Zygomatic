# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""analyse_performance.tools — the ANALYSES registry, the sibling-family sweep behind code(), and the five assistant tools with their prompt and examples.

Moved verbatim from analyse_performance.py (lines 818-1170) by the 2026-10 modularization split;
no logic, constant or comment was changed.
"""

import os
import logging as _zyg_logging
from zyg_workflows.arch_assistant_ext.analyse_performance.geometry import (
    FAM,
    HERE,
)
from zyg_workflows.arch_assistant_ext.analyse_performance.fabric import (
    NL_LIMIT,
    daylight,
    energy,
    structure,
    uvalues,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_assistant_ext.analyse_performance')

# ── the registry convention every analysis family exports ────────────────────
ANALYSES = {
    'a_daylight': ('Daylight factor', lambda d: daylight(d)),
    'a_energy': ('Energy model', lambda d: energy(d)),
    'a_uvalue': ('U-values', lambda d: uvalues(d)),
    'a_struct': ('Structure', lambda d: structure(d)),
}
SIBLINGS = ['analyse_geometry', 'analyse_planning', 'light_studies']


def _load_sibling(name):
    """Import arch_assistant_ext/<name>.py by file path. Missing file, syntax
    error, anything at all: None, and the code check says so."""
    try:
        import importlib.util

        path = os.path.join(HERE, name + '.py')
        if not os.path.isfile(path):
            return None
        spec = importlib.util.spec_from_file_location('arch_assistant_ext._ap_' + name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:  # noqa: BLE001
        return None


def _norm_issues(res):
    if isinstance(res, str):
        return [{'severity': 'info', 'text': res, 'ids': []}]
    arr = (
        res
        if isinstance(res, list)
        else ((res.get('issues') or res.get('problems') or res.get('items') or []) if isinstance(res, dict) else [])
    )
    out = []
    for it in arr if isinstance(arr, list) else []:
        if isinstance(it, str):
            out.append({'severity': 'warning', 'text': it, 'ids': []})
        elif isinstance(it, dict):
            sev = str(it.get('severity') or it.get('level') or 'info').lower()
            sev = 'error' if sev in ('error', 'bad', 'fail') else ('warning' if sev in ('warning', 'warn') else 'info')
            ids = it.get('ids') or it.get('objects') or []
            out.append(
                {
                    'severity': sev,
                    'text': str(it.get('text') or it.get('msg') or it.get('message') or it),
                    'ids': [str(x) for x in ids] if isinstance(ids, list) else [],
                }
            )
    return out


def code(d, only=None):
    """Every analysis this process can reach: ours, plus each sibling family's
    ANALYSES that imports cleanly."""
    reg = [(k, v[0], v[1], FAM) for k, v in sorted(ANALYSES.items())]
    available, missing, silent = [], [], []
    for name in SIBLINGS:
        mod = _load_sibling(name)
        if mod is None:
            missing.append(name)
            continue
        found = getattr(mod, 'ANALYSES', None)
        n0 = len(reg)
        if isinstance(found, dict):
            for k, v in sorted(found.items()):
                try:
                    reg.append((k, str(v[0]), v[1], name))
                except Exception as _exc:  # noqa: BLE001
                    _zyg_log.warning('analysis %s in %s has a malformed spec, skipped: %s', k, name, _exc)
                    continue
        # A family that imports but exports no ANALYSES contributed nothing to
        # this sweep. Saying "available" of it would overstate what was run —
        # its icons may still register on AR_EXT.analyses in the tab.
        (available if len(reg) > n0 else silent).append(name)
    checks, errors, warnings, offenders = [], 0, 0, []
    for cid, cname, fn, fam in reg:
        if only and cid not in only:
            continue
        sec = {'id': cid, 'name': cname, 'family': fam, 'issues': [], 'error': '', 'summary': ''}
        try:
            res = fn(d)
            sec['issues'] = _norm_issues(res)
            sec['summary'] = str(res.get('summary', '')) if isinstance(res, dict) else ''
        except Exception as e:  # noqa: BLE001
            sec['error'] = '%s: %s' % (type(e).__name__, e)
        for i in sec['issues']:
            if i['severity'] == 'error':
                errors += 1
            elif i['severity'] == 'warning':
                warnings += 1
            for x in i['ids']:
                if x not in offenders:
                    offenders.append(x)
        checks.append(sec)
    return {
        'checks': checks,
        'errors': errors,
        'warnings': warnings,
        'offenders': offenders,
        'available': available,
        'missing': missing,
        'silent': silent,
        'summary': '%d errors, %d warnings across %d checks' % (errors, warnings, len(checks)),
    }


# ── the five assistant tools ─────────────────────────────────────────────────
def _lines(head, rows, issues, tail=''):
    out = [head]
    out += ['  ' + r for r in rows]
    if issues:
        out.append('%d flagged:' % len(issues))
        out += ['  [%s] %s' % (i['severity'], i['text']) for i in issues]
    else:
        out.append('nothing flagged')
    if tail:
        out.append(tail)
    return '\n'.join(out)


def t_daylight_check(d, a, **kw):
    target = a.get('target') if isinstance(a, dict) else None
    r = daylight(d, target)
    rows = [
        '%s: floor %.1f m2, %d window(s), Aw %.2f m2, Atotal %.1f m2, theta %.0f deg, '
        'DF %.2f %% (target %.1f %%)%s'
        % (
            x['room'],
            x['area'],
            x['windows'],
            x['Aw'],
            x['Atotal'],
            x['theta'],
            x['df'],
            x['target'],
            '' if x['df'] >= x['target'] else ' BELOW',
        )
        for x in r['rows']
    ]
    if not rows:
        rows = ['no enclosed room found (draw closed walls, or add a zone record with p.pts)']
    return _lines(
        'Daylight, BRE average DF = (Aw x theta x T 0.7) / (Atotal x (1 - R^2, R 0.5)); rooms from %s.' % r['source'],
        rows,
        r['issues'],
    )


def t_energy_summary(d, a, **kw):
    r = energy(d, a.get('degree_days') if isinstance(a, dict) else None)
    rows = [
        'exterior wall gross %.1f m2, net %.1f m2; windows %.1f m2, doors %.1f m2; '
        'roofs %.1f m2; ground slabs %.1f m2'
        % (r['wall_gross'], r['wall_net'], r['glass'], r['doors'], r['roof_area'], r['floor_area']),
        'glazing ratio overall %.1f %%' % (r['glazing_ratio'] * 100),
    ]
    for o in 'NESW':
        x = r['orient'][o]
        if x['wall'] >= 1:
            rows.append(
                '%s facade: wall %.1f m2, glass %.1f m2, ratio %.1f %%'
                % (o, x['wall'], x['glass'], 100 * x['glass'] / x['wall'])
            )
    rows += ['%s: A %.1f m2 x U %.3f = %.1f W/K' % (p['what'], p['area'], p['u'], p['h']) for p in r['parts']]
    rows.append('ventilation 0.5 ach x %.1f m3 x 0.34 W/m3K = %.1f W/K' % (r['volume'], r['Hv']))
    rows.append(
        'H total %.1f W/K; %.0f Kd degree-days -> %.0f kWh/year (H x 24 x Kd / 1000)'
        % (r['H'], r['degree_days'], r['kwh'])
    )
    return _lines(
        'Energy: heated envelope = every wall not fully interior, plus roofs and ground slabs. '
        'U-values from the a_uvalue table; no gains, no bridges, no system efficiency.',
        rows,
        r['issues'],
    )


def t_u_values(d, a, **kw):
    r = uvalues(d)
    rows = []
    for c in r['rows']:
        lay = ' + '.join(
            '%s %s'
            % (
                l['name'],
                ('R %.3f' % l['r'])
                if l.get('r') is not None
                else '%.3f m / %.3f' % (l.get('d', 0), l.get('lambda', 1)),
            )
            for l in c['layers']
        )
        lim = NL_LIMIT.get(c['type'])
        rows.append(
            '%s (%s, %s): U %.3f W/m2K%s%s | %s'
            % (
                c['label'],
                c['key'],
                c['type'],
                c['u'],
                ' limit %s' % lim if lim else '',
                ' [edited]' if c['edited'] else '',
                lay,
            )
        )
    return _lines(
        'U = 1 / (Rsi 0.13 + sum d/lambda + Rse 0.04). Limits: Bouwbesluit 2021 new-build '
        '(wall 0.21, roof 0.16, floor 0.21, glazing 1.65 W/m2K).',
        rows,
        r['issues'],
    )


def t_structure_check(d, a, **kw):
    r = structure(d)
    return _lines(
        'Structure, rules of thumb only (not a calculation): beam span/depth timber 20, '
        'concrete 25, steel 30; slab span/thickness 30; column height/least dimension 20; '
        'roof clear span 12 m.',
        r['rows'] or ['no beam, column, slab or roof in the drawing'],
        r['issues'],
    )


def t_code_check(d, a, **kw):
    only = a.get('only') if isinstance(a, dict) else None
    only = [str(x) for x in only] if isinstance(only, list) else None
    r = code(d, only)
    out = [
        r['summary'],
        'analysis families that contributed a check: %s' % (', '.join([FAM] + r['available'])),
        'imported but registering no server-side analysis: %s' % (', '.join(r['silent']) or 'none'),
        'not installed: %s' % (', '.join(r['missing']) or 'none'),
    ]
    for sec in r['checks']:
        if sec['error']:
            out.append('%s (%s, %s): FAILED — %s' % (sec['name'], sec['id'], sec['family'], sec['error']))
            continue
        out.append(
            '%s (%s, %s): %d issue(s)%s'
            % (
                sec['name'],
                sec['id'],
                sec['family'],
                len(sec['issues']),
                ' — ' + sec['summary'] if sec['summary'] else '',
            )
        )
        out += ['    [%s] %s' % (i['severity'], i['text']) for i in sec['issues']]
    if r['offenders']:
        out.append('offending objects: %s' % ', '.join(r['offenders']))
    return '\n'.join(out)


TOOLS = [
    (
        {
            'name': 'daylight_check',
            'description': 'Average daylight factor per room (BRE Digest 209): DF % = (Aw x theta x T) / '
            '(Atotal x (1 - R^2)). Flags rooms below 2 % (living) / 1 % (other), or below '
            'your own target.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'target': {
                        'type': 'number',
                        'description': 'Target DF % applied to every room. Omit for the BRE defaults.',
                    }
                },
                'required': [],
            },
        },
        t_daylight_check,
    ),
    (
        {
            'name': 'energy_summary',
            'description': 'The heated envelope: exterior wall/roof/slab areas gross and net, glazing ratio per '
            'orientation, heat-loss coefficient H = sum U.A + ventilation, and an annual heating estimate.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'degree_days': {'type': 'number', 'description': 'Heating degree-days, default 2800 (NL).'}
                },
                'required': [],
            },
        },
        t_energy_summary,
    ),
    (
        {
            'name': 'u_values',
            'description': 'Thermal transmittance of every construction: the layer build-up, U = 1/(Rsi + sum d/lambda '
            '+ Rse), and whether it passes the Bouwbesluit 2021 new-build limits.',
            'input_schema': {'type': 'object', 'properties': {}, 'required': []},
        },
        t_u_values,
    ),
    (
        {
            'name': 'structure_check',
            'description': 'Preliminary structural sanity: beam span/depth by material, slab span/thickness, column '
            'slenderness, roof clear span. Rules of thumb, not a calculation.',
            'input_schema': {'type': 'object', 'properties': {}, 'required': []},
        },
        t_structure_check,
    ),
    (
        {
            'name': 'code_check',
            'description': 'Run EVERY analysis installed in this studio (this family plus any other analysis family '
            'present) and report one list: issue counts, every issue, and which families were available.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'only': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Analysis ids to run, e.g. ["a_daylight"]. Omit to run all.',
                    }
                },
                'required': [],
            },
        },
        t_code_check,
    ),
]

PROMPT = (
    'Performance analysis (analyse_performance). press_button("a_daylight", args {target: %}) opens the daylight '
    'factor sheet and paints the rooms by DF; press_button("a_energy") opens the energy model (envelope, glazing '
    'ratio, H, kWh/year); press_button("a_uvalue", args {set: {mat_concrete: {layers: [{name, d, lambda}]}}}) opens '
    'the construction table and can overwrite one build-up; press_button("a_struct") opens the structural sanity '
    'sheet; press_button("a_code", args {only: [ids]}) runs every registered analysis into one compliance sheet. '
    'The same numbers without opening a sheet: daylight_check(target), energy_summary(degree_days), u_values(), '
    'structure_check(), code_check(only).'
)

EXAMPLES = [
    {'ask': 'is there enough daylight in these rooms?', 'calls': [{'tool': 'daylight_check', 'args': {}}]},
    {'ask': 'how much heat does this building lose?', 'calls': [{'tool': 'energy_summary', 'args': {}}]},
    {'ask': 'what is the U-value of the walls?', 'calls': [{'tool': 'u_values', 'args': {}}]},
    {'ask': 'are any of the beams too shallow for their span?', 'calls': [{'tool': 'structure_check', 'args': {}}]},
    {
        'ask': 'run the full compliance check and show me the report',
        'calls': [{'tool': 'code_check', 'args': {}}, {'tool': 'press_button', 'args': {'id': 'a_code'}}],
    },
    {
        'ask': 'show me the daylight overlay with a 1.5 % target',
        'calls': [{'tool': 'press_button', 'args': {'id': 'a_daylight', 'args': {'target': 1.5}}}],
    },
]
