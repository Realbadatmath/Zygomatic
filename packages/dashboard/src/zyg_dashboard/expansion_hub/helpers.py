# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from .constants import (
    ASSET_DIRS,
    ASSET_EXT,
    CODE_EXT,
    CONFIG_EXT,
    CONTENT_PRUNE,
    CREWS_DATA,
    CREWS_DATA_KEEP,
    DATA_PRUNE,
    DOCS_EXT,
    HARD_PRUNE,
    HOME,
    OUTPUT_PRUNE,
    PROMPT_NAME,
    ROOT,
    TABLE_EXT,
    THIRD_PARTY_ROOTS,
    _PROMPT_DIRS,
    _SKIP_BY_EXT,
    exe,
    os,
    re,
    subprocess,
    time,
)

import logging as _zyg_logging

# The logger is re-created here by assignment rather than imported from the sibling
# module: getLogger returns the one singleton the original module held, and an assigned
# global keeps the method-call bytecode of every `_zyg_log.debug(...)` below unchanged.
_zyg_log = _zyg_logging.getLogger('zyg_dashboard.expansion_hub')
# ── small helpers ────────────────────────────────────────────────────────────


def _iso(ts):
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(ts))


def _ext(name):
    base = name.lower()
    if base.startswith('dockerfile'):
        return 'dockerfile'
    if base.startswith('docker-compose'):
        return 'compose'
    if base in ('makefile', 'procfile', 'license', 'licence', 'readme', 'changelog', 'notice'):
        return base
    if base.startswith('requirements') and base.endswith('.txt'):
        return 'requirements'
    if base.startswith('.') and '.' not in base[1:]:
        return base  # .gitignore .dockerignore .env …
    return base.rsplit('.', 1)[1] if '.' in base else ''


# Runtime state the dashboard writes beside its code (dashboard_config.py names them).
RUNTIME_FILE = re.compile(
    r'^(dashboard_(error_logs|job_status|monitoring_jobs)|token_usage|probe_\d+|safety_audit_log|'
    r'.*_state|.*_ledger|.*_cache)\.json$',
    re.I,
)


def _is_backup_name(name):
    low = name.lower()
    return (
        '.bak' in low
        or low.endswith(('~', '.orig', '.swp', '.rej', '.old'))
        or '.pre_' in low
        or 'backup' in low
        or low.startswith('#')
        or re.search(r'\.v\d+-\d{8}$', low) is not None
    )


def _kind_of(path, ext, rel_parts):
    """code | config | docs | table | prompt | asset | other — or None when skipped."""
    base = os.path.basename(path)
    low_parts = {p.lower() for p in rel_parts}
    in_asset_dir = bool(low_parts & ASSET_DIRS)
    if ext in ASSET_EXT and in_asset_dir:
        return 'asset'
    if ext in _SKIP_BY_EXT:
        return None
    # Prompt material wins over its container format.
    if ext in ('json', 'txt', 'md', 'yaml', 'yml', 'toml'):
        if PROMPT_NAME.search(base) or (low_parts & _PROMPT_DIRS):
            return 'prompt'
        if 'agents' in low_parts and ext == 'json' and os.path.join('agents', 'crews', 'agents') in path:
            return 'prompt'  # the agent persona configs
    if ext in ('dockerfile', 'compose', 'makefile', 'requirements', 'procfile') or ext.startswith('.'):
        return 'config'
    if ext in ('license', 'licence', 'readme', 'changelog', 'notice'):
        return 'docs'
    if ext in CODE_EXT:
        return 'code'
    if ext in CONFIG_EXT:
        return 'config'
    if ext in DOCS_EXT:
        return 'docs'
    if ext in TABLE_EXT:
        return 'table'
    if ext == '':
        return 'other'
    return 'other'


KIND_LABEL = {
    'code': 'Code (py / js / html / css / sh …)',
    'config': 'Configuration (json / yaml / toml / ini / units)',
    'docs': 'Documentation (md / txt / rst)',
    'prompt': 'Prompts & personas',
    'table': 'Data tables (csv)',
    'asset': 'GUI assets (icons, themes, fonts, LUTs, pose refs)',
    'other': 'Other structural files',
}
KIND_ORDER = ('code', 'config', 'prompt', 'docs', 'table', 'asset', 'other')


# ── systemd: which units run which component ─────────────────────────────────


def _unit_files():
    out = []
    for scope, d in (('user', os.path.join(HOME, '.config', 'systemd', 'user')), ('system', '/etc/systemd/system')):
        try:
            names = sorted(os.listdir(d))
        except OSError as _exc:
            _zyg_log.debug('%s unit dir %s not listable, skipped: %s', scope, d, _exc)
            continue
        for n in names:
            p = os.path.join(d, n)
            if n.endswith('.service') and os.path.isfile(p) and not os.path.islink(p):
                out.append((scope, n, p))
    return out


def _parse_unit(path):
    wd = ''
    execs = []
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                line = line.strip()
                if line.startswith('WorkingDirectory='):
                    wd = line.split('=', 1)[1].strip().strip('"')
                elif line.startswith('ExecStart='):
                    execs.append(line.split('=', 1)[1].strip())
    except OSError:
        return '', []
    return wd.replace('%h', HOME), [e.replace('%h', HOME) for e in execs]


def _exec_paths(exec_line):
    """Absolute paths named on an ExecStart line (quoted or bare)."""
    toks = re.findall(r'"([^"]+)"|(\S+)', exec_line)
    out = []
    for q, b in toks:
        t = (q or b).lstrip('-@+!:')
        if t.startswith('/') and not t.startswith('/usr/bin/') and not t.startswith('/bin/'):
            out.append(t)
    return out


def _unit_states():
    states = {}
    # The GUI runs under a system unit with no session bus; `systemctl --user` needs the
    # runtime dir to find it, so point it at /run/user/<uid> when the env does not.
    env = dict(os.environ)
    env.setdefault('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
    env.setdefault('DBUS_SESSION_BUS_ADDRESS', f'unix:path={env["XDG_RUNTIME_DIR"]}/bus')
    for scope, flags in (('user', ['--user']), ('system', [])):
        try:
            r = subprocess.run(
                [exe('systemctl'), *flags]
                + ['list-units', '--type=service', '--all', '--plain', '--no-legend', '--no-pager'],
                capture_output=True,
                text=True,
                timeout=4,
                env=env,
            )
            for line in r.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    states[(scope, parts[0])] = f'{parts[2]} ({parts[3]})'
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.warning('systemctl list-units failed for %s scope, unit states unknown: %s', scope, _exc)
    return states


def _third_party(path):
    rel = os.path.relpath(path, HOME) if path.startswith(HOME + os.sep) else path
    first = rel.split(os.sep)[0]
    return first in THIRD_PARTY_ROOTS or path.startswith(('/usr', '/opt', '/bin', '/etc'))


def discover_components():
    """Primary monorepo + one component per systemd unit root under $HOME, + launchers."""
    comps = {
        'zygomatic_full': {
            'id': 'zygomatic_full',
            'label': 'legacy tree (ZYG_CREWS_ROOT)',
            'root': ROOT,
            'services': [],
            'kind': 'repo',
        }
    }
    launchers = {
        'id': 'launchers',
        'label': 'Launcher scripts (named in ExecStart)',
        'root': HOME,
        'services': [],
        'kind': 'files',
        'files': [],
    }
    services = []
    states = _unit_states()
    for scope, name, path in _unit_files():
        wd, execs = _parse_unit(path)
        paths = [p for e in execs for p in _exec_paths(e)]
        root = ''
        cand = wd or (os.path.dirname(paths[0]) if paths else '')
        if cand and cand.startswith(HOME + os.sep) and not _third_party(cand) and cand != os.path.join(HOME, 'bin'):
            root = cand
        rec = {
            'unit': name,
            'scope': scope,
            'state': states.get((scope, name), 'unknown'),
            'exec': execs[0] if execs else '',
            'working_dir': wd,
            'component': None,
            'third_party': False,
        }
        if root:
            # Under the monorepo → it is the monorepo. Else its own component.
            if root == ROOT or root.startswith(ROOT + os.sep):
                cid = 'zygomatic_full'
            else:
                cid = re.sub(r'[^a-z0-9]+', '_', os.path.basename(root).lower()).strip('_') or 'comp'
                if cid not in comps:
                    comps[cid] = {
                        'id': cid,
                        'label': os.path.basename(root),
                        'root': root,
                        'services': [],
                        'kind': 'app',
                    }
            rec['component'] = cid
            comps[cid]['services'].append(name)
        else:
            rec['third_party'] = bool(cand) and _third_party(cand)
            if not rec['third_party'] and not cand and paths:
                rec['third_party'] = all(_third_party(p) for p in paths)
        # Loose launcher scripts under $HOME (not inside any component) belong to 'launchers'.
        for p in paths:
            inside = any(
                p == c['root'] or p.startswith(c['root'] + os.sep) for c in comps.values() if c['kind'] != 'files'
            )
            if not inside and not _third_party(p) and os.path.isfile(p) and p not in launchers['files']:
                launchers['files'].append(p)
                if rec['component'] is None:
                    rec['component'] = 'launchers'
                if name not in launchers['services']:
                    launchers['services'].append(name)
        services.append(rec)
    # The health probe lives in /usr/local/bin but is ours: ExecStart names it directly.
    for rec in services:
        for p in _exec_paths(rec['exec']):
            if (
                p.startswith('/usr/local/bin/')
                and 'zygomatic' in p
                and os.path.isfile(p)
                and p not in launchers['files']
            ):
                launchers['files'].append(p)
                rec['third_party'] = False
                if rec['component'] is None:
                    rec['component'] = 'launchers'
                if rec['unit'] not in launchers['services']:
                    launchers['services'].append(rec['unit'])
    if launchers['files']:
        comps['launchers'] = launchers
    order = (
        ['zygomatic_full']
        + sorted(c for c in comps if c not in ('zygomatic_full', 'launchers'))
        + (['launchers'] if 'launchers' in comps else [])
    )
    return [comps[c] for c in order], services


# ── pruning rules ────────────────────────────────────────────────────────────


def _prune_reason(full, name, parent, comp_root):
    low = name.lower()
    if os.path.islink(full):
        return 'symlink (not followed)'
    if name in HARD_PRUNE or low.startswith('.venv') or low.endswith(('_venv', '.egg-info')) or low == '.venv-test':
        return 'third-party / cache (venv, node_modules, git, caches)'
    if 'backup' in low or '.bak' in low or low.startswith('bak-') or low == '_attic' or low.endswith('_quarantine'):
        return 'backup copy'
    if low in ('archive', 'archives'):
        return 'archive copy'
    if name == 'orchestrator.worktrees':
        return 'git worktree copies'
    if name == 'vendor':
        return 'third-party (vendored libraries)'
    if comp_root == ROOT and full == os.path.join(ROOT, 'models'):
        return 'third-party engines + weights (Applio voice conversion, NeMo diarization, legacy launchers)'
    if full == CREWS_DATA:
        return None  # walked, but only its allow-listed children survive
    if parent == CREWS_DATA:
        return None if name in CREWS_DATA_KEEP else 'generated or collected content under the crews data root'
    if os.path.dirname(parent) == CREWS_DATA:
        keep = CREWS_DATA_KEEP.get(os.path.basename(parent))
        if keep is not None and name not in keep:
            return 'generated content under the crews data root / ' + os.path.basename(parent)
    if low in OUTPUT_PRUNE:
        return 'generated output / logs'
    if low in CONTENT_PRUNE or low.startswith('bewijsstukken'):
        return 'user documents / app content'
    if low == 'legacy':
        return 'legacy copy (kept in the repo, not running)'
    if low in DATA_PRUNE:
        # A package called models/ or data/ that holds code (SQLAlchemy models, fixtures)
        # is structure, not weights: keep any such folder with a .py directly inside.
        try:
            if any(f.endswith('.py') for f in os.listdir(full)):
                return None
        except OSError as _exc:
            _zyg_log.debug('%s not listable, treating it as runtime data: %s', full, _exc)
        return 'runtime data / weights'
    return None
