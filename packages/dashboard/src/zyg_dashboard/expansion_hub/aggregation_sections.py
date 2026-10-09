# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The sections `aggregation.build` stitches into one Expansion payload.

`build` used to be one 330-line function: a filesystem sweep, nine independent
tallies over the swept rows, and a literal payload dict at the end. Each tally
is a pure function of the swept rows, so each one lives here with explicit
parameters — the orchestrator in `aggregation.py` only names them in order.
Nothing about the census changed: the same rows, the same sort keys, the same
payload keys in the same order.
"""

import os
import statistics
import time

from .constants import (
    ASSET_DIRS,
    CACHE_PATH,
    CONTENT_PRUNE,
    CREWS_DATA_KEEP,
    DATA_PRUNE,
    EXTRA_FILES,
    HARD_PRUNE,
    OUTPUT_PRUNE,
    PROMPT_NAME,
    ROOT,
    SCAN_TTL_S,
    SKIP_EXT,
    TRAINING_ROOTS,
)
from .helpers import KIND_LABEL, KIND_ORDER, _iso, discover_components
from .reading import _add_file, _load_cache, _save_cache, _walk_component


class ScanResult:
    """One filesystem sweep: the file rows and everything the walk learned beside them.

    Hand-written rather than a `@dataclass` because `test_expansion_hub.py`
    holds every module of this package to a stdlib allowlist that predates it.
    """

    def __init__(self, files, dirs_seen, comps, services, excluded, skipped, misses, walk_ms):
        self.files = files
        self.dirs_seen = dirs_seen
        self.comps = comps
        self.services = services
        self.excluded = excluded
        self.skipped = skipped
        self.misses = misses
        self.walk_ms = walk_ms


class LanguageFiles:
    """The per-language slices of the swept rows that several sections share."""

    def __init__(self, py, js, html, css, tests):
        self.py = py
        self.js = js
        self.html = html
        self.css = css
        self.tests = tests


class Sections:
    """The finished tallies `_payload` puts into the response, in payload order."""

    def __init__(self, by_kind, by_ext, components, folders, files, structure, prompts, excluded, skipped):
        self.by_kind = by_kind
        self.by_ext = by_ext
        self.components = components
        self.folders = folders
        self.files = files
        self.structure = structure
        self.prompts = prompts
        self.excluded = excluded
        self.skipped = skipped


def _agg(rows):
    a = {'files': len(rows), 'bytes': sum(r['bytes'] for r in rows), 'lines': sum(r['lines'] for r in rows)}
    return a


def _scan_tree(t0):
    """Walk every component root once; return the raw census as a `ScanResult`.

    `t0` is the caller's start time, so `walk_ms` measures the same span the
    monolith measured. The file cache is read, pruned of rows whose file is
    gone, and written back only when something was actually read this time.
    """
    cache = _load_cache()
    cache_files = cache.setdefault('files', {})
    misses = []
    excluded = []
    skipped = {}
    for r in list(SKIP_EXT) + ['other', 'backup copies']:
        skipped[r] = [0, 0]
    files = []
    dirs_seen = []
    comps, services = discover_components()
    for comp in comps:
        if comp['kind'] != 'files' and not os.path.isdir(comp['root']):
            comp['missing'] = True
            continue
        _walk_component(comp, cache_files, misses, excluded, skipped, files, dirs_seen)
    for p in EXTRA_FILES:
        if os.path.isfile(p):
            _add_file(p, comps[0], ROOT, cache_files, misses, skipped, files)
    # Drop cache rows for files that no longer exist (keeps the cache from growing forever).
    live = {f['abs'] for f in files}
    for k in [k for k in cache_files if k not in live]:
        del cache_files[k]
    if misses:
        _save_cache(cache)
    return ScanResult(
        files=files,
        dirs_seen=dirs_seen,
        comps=comps,
        services=services,
        excluded=excluded,
        skipped=skipped,
        misses=misses,
        walk_ms=round((time.time() - t0) * 1000),
    )


def _kind_rows(files):
    """One row per kind in `KIND_ORDER` that has files, with its share of all lines."""
    by_kind = []
    total_lines = sum(f['lines'] for f in files) or 1
    for k in KIND_ORDER:
        rows = [f for f in files if f['kind'] == k]
        if not rows:
            continue
        a = _agg(rows)
        by_kind.append(dict(kind=k, label=KIND_LABEL[k], share_lines=round(100 * a['lines'] / total_lines, 1), **a))
    return by_kind


def _ext_rows(files):
    """One row per extension: totals, the line min/median/max and the largest file."""
    by_ext = []
    exts = {}
    for f in files:
        exts.setdefault(f['ext'], []).append(f)
    for e, rows in exts.items():
        a = _agg(rows)
        lines = [r['lines'] for r in rows]
        big = max(rows, key=lambda r: r['lines'])
        by_ext.append(
            dict(
                ext=e,
                kind=max({r['kind'] for r in rows}, key=lambda k: sum(1 for r in rows if r['kind'] == k)),
                min_lines=min(lines),
                median_lines=int(statistics.median(lines)),
                max_lines=max(lines),
                largest=big['path'],
                **a,
            )
        )
    by_ext.sort(key=lambda r: (-r['lines'], -r['files']))
    return by_ext


def _component_rows(comps, files, dirs_seen):
    """One row per component: its totals, its walked directory count and its per-kind tally."""
    comp_rows = []
    for c in comps:
        rows = [f for f in files if f['comp'] == c['id']]
        a = _agg(rows)
        kinds = {}
        for r in rows:
            kinds[r['kind']] = kinds.get(r['kind'], 0) + 1
        comp_rows.append(
            {
                'id': c['id'],
                'label': c['label'],
                'root': c['root'],
                'kind': c['kind'],
                'services': c['services'],
                'missing': c.get('missing', False),
                'dirs': sum(1 for cid, _ in dirs_seen if cid == c['id']),
                'kinds': kinds,
                'py': sum(1 for r in rows if r['ext'] == 'py'),
                'js': sum(1 for r in rows if r['ext'] in ('js', 'mjs', 'cjs')),
                'html': sum(1 for r in rows if r['ext'] in ('html', 'htm')),
                'json': sum(1 for r in rows if r['ext'] == 'json'),
                **a,
            }
        )
    return comp_rows


def _language_groups(files):
    """Slice the swept rows into the py / js / html / css / tests lists later sections need."""
    py = [f for f in files if f['ext'] == 'py']
    tests = [
        f
        for f in py
        if os.path.basename(f['abs']).startswith('test_')
        or f['abs'].endswith('_test.py')
        or any(p.startswith('tests') or p == 'apitests' for p in f['path'].split(os.sep)[:-1])
    ]
    return LanguageFiles(
        py=py,
        js=[f for f in files if f['ext'] in ('js', 'mjs', 'cjs', 'ts')],
        html=[f for f in files if f['ext'] in ('html', 'htm', 'jinja', 'j2')],
        css=[f for f in files if f['ext'] in ('css', 'scss', 'less')],
        tests=tests,
    )


def _structure_counts(files, langs):
    """The 'what the program is made of' counters: modules, defs, routes, templates, scripts."""
    py, js, html, css, tests = langs.py, langs.js, langs.html, langs.css, langs.tests
    return {
        'py_modules': len(py),
        'py_lines': sum(f['lines'] for f in py),
        'py_bytes': sum(f['bytes'] for f in py),
        'functions': sum(f['defs'] or 0 for f in py),
        'classes': sum(f['classes'] or 0 for f in py),
        'routes': sum(f['routes'] or 0 for f in py),
        'entry_points': sum(f['main'] or 0 for f in py),
        'blueprints': sum(1 for f in py if os.path.basename(f['abs']).startswith(('bp_', 'zpub_'))),
        'tests': len(tests),
        'test_lines': sum(f['lines'] for f in tests),
        'js_files': len(js),
        'js_lines': sum(f['lines'] for f in js),
        'js_functions': sum(f['defs'] or 0 for f in js),
        'html_files': len(html),
        'html_lines': sum(f['lines'] for f in html),
        'html_includes': sum(f['defs'] or 0 for f in html),
        'html_script_tags': sum(f['scripts'] or 0 for f in html),
        'css_files': len(css),
        'css_lines': sum(f['lines'] for f in css),
        'templates': sum(1 for f in html if 'templates' in f['path'].split(os.sep)),
        'static_js': sum(1 for f in js if 'static' in f['path'].split(os.sep)),
        'comfy_workflows': sum(
            1 for f in files if '_comfy_workflows' in f['path'].split(os.sep) and f['ext'] == 'json'
        ),
        'blender_scripts': sum(1 for f in py if 'blender' in f['path'].lower()),
        'capability_tests': sum(1 for f in py if 'capability_tests' in f['path'].split(os.sep)),
        'shell_scripts': sum(1 for f in files if f['ext'] in ('sh', 'bash', 'zsh')),
        'sql_migrations': sum(
            1 for f in py if 'alembic' in f['path'].split(os.sep) and 'versions' in f['path'].split(os.sep)
        ),
    }


def _prompt_group(f):
    """Which prompt group one prompt file belongs to, by where it sits and what it is called."""
    parts = f['path'].split(os.sep)
    if '_comfy_workflows' in parts:
        return 'ComfyUI workflow graphs'
    if os.path.join('agents', 'crews', 'agents') in f['abs']:
        return 'Agent persona configs'
    if 'briefs' in parts:
        return 'Character briefs'
    if os.path.basename(f['abs']) == 'prompt_registry.json':
        return 'Prompt registry'
    if os.path.basename(f['abs']) == 'vlm_checklists.json':
        return 'VLM judge checklists'
    return 'Stand-alone prompt files'


def _prompt_summary(files, py):
    """The prompts section: prompt files grouped by shape, plus the literals found in the code."""
    prompt_files = sorted([f for f in files if f['kind'] == 'prompt'], key=lambda f: (-(f['units'] or 0), -f['lines']))
    in_code = sorted([f for f in py if f['p_lits']], key=lambda f: -(f['p_chars'] or 0))
    prompt_groups = {}
    for f in prompt_files:
        g = _prompt_group(f)
        r = prompt_groups.setdefault(g, {'group': g, 'files': 0, 'units': 0, 'lines': 0, 'bytes': 0})
        r['files'] += 1
        r['units'] += f['units'] or 0
        r['lines'] += f['lines']
        r['bytes'] += f['bytes']
    return {
        'files': len(prompt_files),
        'units': sum(f['units'] or 0 for f in prompt_files),
        'lines': sum(f['lines'] for f in prompt_files),
        'bytes': sum(f['bytes'] for f in prompt_files),
        'groups': sorted(prompt_groups.values(), key=lambda r: -r['units']),
        'in_code_files': len(in_code),
        'in_code_literals': sum(f['p_lits'] or 0 for f in in_code),
        'in_code_chars': sum(f['p_chars'] or 0 for f in in_code),
        'in_code_lines': sum(f['p_lines'] or 0 for f in in_code),
        'file_rows': [
            {
                'path': f['path'],
                'ext': f['ext'],
                'units': f['units'] or 0,
                'rule': f['units_rule'] or '',
                'lines': f['lines'],
                'bytes': f['bytes'],
            }
            for f in prompt_files
        ],
        'code_rows': [
            {
                'path': f['path'],
                'literals': f['p_lits'],
                'chars': f['p_chars'],
                'lines': f['p_lines'],
                'file_lines': f['lines'],
            }
            for f in in_code
        ],
    }


def _exclusion_rows(excluded, skipped):
    """`(excluded by reason, skipped by reason)` — the two 'what was left out' tables."""
    ex_by_reason = {}
    for e in excluded:
        ex_by_reason.setdefault(e['reason'], []).append(e['path'])
    excluded_rows = sorted(
        [{'reason': r, 'count': len(p), 'paths': sorted(p)} for r, p in ex_by_reason.items()], key=lambda r: -r['count']
    )
    skipped_rows = sorted(
        [{'reason': r, 'files': v[0], 'bytes': v[1]} for r, v in skipped.items() if v[0]], key=lambda r: -r['files']
    )
    return excluded_rows, skipped_rows


def _file_rows(files):
    """The compact per-file table (short keys) the browser filters client-side."""
    return [
        {
            'p': f['path'],
            'c': f['comp'],
            'k': f['kind'],
            'e': f['ext'],
            'b': f['bytes'],
            'l': f['lines'],
            'bl': f['blank'],
            'cm': f['comment'],
            'd': f['defs'],
            'cl': f['classes'],
            'r': f['routes'],
            'm': f['mtime'],
            'u': f['units'],
            'pl': f['p_lits'],
        }
        for f in files
    ]


NOTES = (
    'Structural = what the program is made of: code, configuration, documentation, prompts, GUI assets. '
    'Generated = what it produces or collects: output folders, runtime state, logs, rendered media, mesh/sound/VFX '
    'libraries, weights, caches. Every pruned directory is listed under "What was excluded" with the rule that pruned it.',
    'Components come from the systemd units (user + system): a unit whose WorkingDirectory or ExecStart points under '
    "the operator's home and is not a third-party engine is a component. The monorepo is always the first one.",
    'Lines = newline count of the file (+1 for an unterminated last line). Blank and comment lines are counted on '
    'files up to 8 MB; comment markers follow the language (# / // / <!--).',
    'Functions, classes and routes are regex counts of def / class / @x.route( at line start; a decorator split '
    'over lines or a route registered by add_url_rule is not seen.',
    'Prompt literals in code are found by parsing each Python file (AST): assignments whose target name contains '
    'prompt / persona / instruction / question / checklist with a string (or a bank of 20+ character strings), '
    'keyword arguments prompt= / system= / instructions= / negative_prompt= with a string, and {"role": "system", '
    '"content": …} dicts. A prompt built by a function call from fragments is NOT counted.',
    'Prompt files are counted in units by their shape: a .txt/.md is one prompt, a ComfyUI graph counts its text '
    'inputs, the prompt registry its entries, the VLM checklists their binary questions, a persona or brief is one.',
    'Training data: every file under the training roots is counted by class (image / caption / audio / video / '
    'manifest / other) per first-level dataset folder. Nothing under them is read.',
    'Media (images, audio, video, fonts) counts as structural only inside GUI asset folders (static, assets, icons, '
    'themes, LUTs, pose references); the same extensions elsewhere are generated or collected content and are skipped.',
    'Backup copies (*.bak-*, *backup* folders, _attic, archive and worktree copies) are excluded so the same line is '
    'never counted twice.',
)

_LIMITATIONS = (
    'The monorepo is not a git checkout at its root (its crews dir has its own .git), so there is no '
    'commit-based authorship or churn here — only mtimes.',
    'orchestrator/zyg-orchestrator/legacy/flask_dashboard is a legacy copy of the dashboard kept in the repo; it is '
    'excluded as "legacy copy" so the same persona files are not counted twice.',
    'The sibling apps (legal assistant, transcriber, hub …) are counted for their code only: what the operator put '
    'INTO them (case files, mail, transcripts, schematics) is app content and is pruned by folder name.',
    'Third-party engines installed under the repo (models/ at the root: Applio, NeMo diarization) are excluded as a '
    'whole, which also drops the handful of legacy launcher stubs that sit beside them.',
    'Prompt text that reaches a model only through the ComfyUI API at run time (built from brief fields) is not a file '
    "and is not counted; the Capabilities tab's PROMPT DAMAGE bank covers that side.",
)


def _limitations(walk_ms, files_read):
    """The fixed caveats plus the one that quotes this scan's own cost."""
    return [
        *_LIMITATIONS,
        f'Scan cost: walk {walk_ms} ms, {files_read} files read this time, the rest from the cache. A payload is held '
        f'for {SCAN_TTL_S} s; ?fresh=1 forces a rescan.',
    ]


def _rules():
    """The census rules, echoed into the payload so the page can show what it excluded and why."""
    return {
        'prune_dirs': sorted(
            HARD_PRUNE
            | OUTPUT_PRUNE
            | DATA_PRUNE
            | CONTENT_PRUNE
            | {'vendor', 'archive', 'legacy', 'orchestrator.worktrees', '*backup*', '_attic', 'bewijsstukken*'}
        ),
        'crews_data_keep': {k: sorted(v) if v else 'all' for k, v in CREWS_DATA_KEEP.items()},
        'skip_ext': {r: sorted(s) for r, s in SKIP_EXT.items()},
        'asset_dirs': sorted(ASSET_DIRS),
        'prompt_name': PROMPT_NAME.pattern,
        'training_roots': [t['root'] for t in TRAINING_ROOTS],
        'extra_files': EXTRA_FILES,
    }


def _totals(scan, sec, training_totals):
    """The headline numbers: one row of counters over the whole census."""
    files, skipped = scan.files, scan.skipped
    structure, prompts = sec.structure, sec.prompts
    return {
        'files': len(files),
        'bytes': sum(f['bytes'] for f in files),
        'lines': sum(f['lines'] for f in files),
        'blank': sum(f['blank'] for f in files),
        'comment': sum(f['comment'] for f in files),
        'dirs': len(scan.dirs_seen),
        'components': sum(1 for c in sec.components if not c['missing']),
        'services': sum(1 for s in scan.services if s['component']),
        'services_active': sum(1 for s in scan.services if s['component'] and s['state'].startswith('active')),
        'excluded_dirs': len(scan.excluded),
        'skipped_files': sum(v[0] for v in skipped.values()),
        'skipped_bytes': sum(v[1] for v in skipped.values()),
        'py': structure['py_modules'],
        'js': structure['js_files'],
        'html': structure['html_files'],
        'css': structure['css_files'],
        'json': sum(1 for f in files if f['ext'] == 'json'),
        'md': sum(1 for f in files if f['ext'] == 'md'),
        'sh': structure['shell_scripts'],
        'yaml': sum(1 for f in files if f['ext'] in ('yaml', 'yml')),
        'prompt_files': prompts['files'],
        'prompt_units': prompts['units'],
        'prompt_literals': prompts['in_code_literals'],
        'training_bytes': training_totals['bytes'],
        'training_files': training_totals['files'],
        'training_datasets': training_totals['datasets'],
    }


def _payload(scan, t0, version, sec, training, training_totals):
    """Assemble the response: the scan cost, the totals, every section, the rules and the caveats."""
    files = scan.files
    largest = sorted(files, key=lambda f: -f['lines'])[:40]
    newest = sorted(files, key=lambda f: -f['mtime'])[:25]
    return {
        'data_version': version,
        'scanned_at': _iso(time.time()),
        'scan': {
            'walk_ms': scan.walk_ms,
            'total_ms': round((time.time() - t0) * 1000),
            'files_read': len(scan.misses),
            'files_from_cache': len(files) - len(scan.misses),
            'cache_path': CACHE_PATH,
        },
        'totals': _totals(scan, sec, training_totals),
        'by_kind': sec.by_kind,
        'by_ext': sec.by_ext,
        'components': sec.components,
        'folders': sec.folders,
        'files': sec.files,
        'largest': [
            {'path': f['path'], 'kind': f['kind'], 'ext': f['ext'], 'lines': f['lines'], 'bytes': f['bytes']}
            for f in largest
        ],
        'newest': [
            {'path': f['path'], 'ext': f['ext'], 'lines': f['lines'], 'mtime': _iso(f['mtime'])} for f in newest
        ],
        'structure': sec.structure,
        'prompts': sec.prompts,
        'training': {'roots': training, 'totals': training_totals},
        'services': sorted(
            scan.services, key=lambda s: (s['component'] is None, s['third_party'], s['scope'], s['unit'])
        ),
        'excluded': sec.excluded,
        'skipped': sec.skipped,
        'rules': _rules(),
        'notes': list(NOTES),
        'limitations': _limitations(scan.walk_ms, len(scan.misses)),
    }
