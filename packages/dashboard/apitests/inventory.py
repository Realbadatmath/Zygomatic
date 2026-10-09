#!/usr/bin/env python3
"""Canonical route inventory for the four Zygomatic Flask apps.

Imports every app IN-PROCESS with background threads suppressed (see
_no_threads below) and writes:

  apitests/routes.json  {"generated": iso, "apps": {name: [rule records]}}
  apitests/routes.md    one markdown table per app + a counts header

The output is deterministic: two runs differ only in the "generated" field.

Run:  ../.venv/bin/python apitests/inventory.py
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import inspect
import json
import os
import re
import sys
import threading

CREWS = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
APITESTS = os.path.join(CREWS, 'apitests')
# The Medusa app is a separate checkout; ZYG_MEDUSA_APP_DIR names it (see docs/configuration.md).
MEDUSA_DIR = os.path.expanduser(os.environ.get('ZYG_MEDUSA_APP_DIR', '~/Zygomatic/medusa'))

# A route that takes a body is "dangerous" when its rule or endpoint name says
# it acts. Substring matching is right here: a POST is assumed to act until a
# hand classification in classify_A/B.json proves otherwise, so a false positive
# costs nothing.
DANGER_RE = re.compile(
    r'(start|run|launch|generate|render|train|restart|kill|stop|delete|purge'
    r'|approve|reject|reset|submit|build|spawn|clear|remove|cancel|resume'
    r'|pause|enqueue|trigger|execute|install|download|upload|convert|export'
    r'|import|write|save|set_|toggle|enable|disable|login|logout)'
)

# GET-only routes are judged differently, because for them a false positive is
# expensive: it drops the route out of the read-only smoke sweep, which is the
# only test it has. Substring matching made 31 read-only GETs unreachable —
# 'skill' matched kill, 'asset_manager' matched set_, 'run_id' matched run,
# 'training/...' matched train — in every case the verb named something else in
# the path, not this endpoint's action.
#
# So a GET acts only when
#   (a) an action verb is the WHOLE last segment of the rule
#       (/api/gpu/timeline/generate acts; /api/assetlib/generated lists), or
#   (b) its handler source writes.
# 'login' is not in the set (GET /login renders a form) but 'logout' is (it
# clears the session). 'download' and 'export' are not: on a GET they name a
# generated artefact being read back.
GET_ACTION_WORDS = frozenset(
    {
        'approve',
        'build',
        'cancel',
        'clear',
        'convert',
        'delete',
        'disable',
        'enable',
        'enqueue',
        'execute',
        'generate',
        'install',
        'kill',
        'launch',
        'logout',
        'migrate',
        'prune',
        'purge',
        'reject',
        'remove',
        'rename',
        'render',
        'reset',
        'restart',
        'resume',
        'retrain',
        'rotate',
        'save',
        'spawn',
        'start',
        'stop',
        'submit',
        'toggle',
        'train',
        'trigger',
        'upload',
        'write',
    }
)
# Calls that change state on disk. os.makedirs/mkdir are deliberately absent:
# every listing endpoint under /api/medusa/training ensures its already-existing
# root with exist_ok=True before scanning it, which is idempotent and writes no
# data.
HANDLER_WRITE_RE = re.compile(
    r"open\([^)]*,\s*['\"][wax]"
    r'|\.write_text\(|\.write_bytes\(|\.writelines\('
    r'|json\.dump\(|yaml\.(safe_)?dump\(|pickle\.dump\('
    r'|shutil\.(copy|copy2|copytree|move|rmtree)'
    r'|os\.(remove|unlink|rename|replace|rmdir|truncate|chmod)'
    r'|\.unlink\(|\.rmdir\('
)
# A route is "external" when its handler source reaches off-process.
# Case-insensitive on purpose: "ComfyUI" and "Comfy ESRGAN" in a handler's
# prose are as good a signal as the call itself, and this is what the
# creator's 2026-10-02 baseline (apitests/probe_20261002.json) measured.
EXTERNAL_RE = re.compile(
    r'(requests\.(get|post|put)|urlopen|subprocess\.|Popen|\.run\('
    r'|ollama|anthropic|comfy|socket\.)',
    re.IGNORECASE,
)

# ---------------------------------------------------------------- auth gates
# crewai_web_gui.require_login (crewai_web_gui.py:410-562), transcribed.
# Paths that need no session at all, from any source address.
DASH_OPEN_EXACT = {
    '/login',
    '/api/login',
    '/logout',
    '/api/logout',
    '/favicon.ico',
    '/apple-touch-icon.png',
    '/apple-touch-icon-precomposed.png',
    '/api/telemetry',
    '/api/vram/free',
    '/api/health',
    '/api/kanban/status',
    '/api/kanban/clear_errors',
    '/api/workflow_status/active',
    '/api/workflow/steps/agents',
    '/api/sports-video/status',
    '/api/output/new-videos',
    '/api/marketing/upload',
    '/api/marketing/dismiss',
    '/api/marketing/undismiss',
    '/api/marketing/dismissed',
    '/api/youtube/channel-videos',
    '/api/medusa/kanban_status',
}
DASH_OPEN_PREFIX = ('/static/', '/api/creator-nexus/')
# Paths that skip the session check only when remote_addr is 127.0.0.1 / ::1.
DASH_LOCAL_EXACT: set = set()  # 2026-10-05: /api/skill/inbound removed with the Skill VM
DASH_LOCAL_PREFIX = (
    '/api/medusa/',
    '/api/storyteller/training/',
    '/api/approval_queue/',
    '/api/preempt/',
    '/api/internal/kidsmusic/',
    '/api/internal/kidseries/',
    '/api/internal/movement/',
    '/api/internal/char2d/',
    '/api/internal/picture_studio/',
)


def dashboard_gate(rule: str) -> str:
    if rule in DASH_OPEN_EXACT or rule.startswith(DASH_OPEN_PREFIX):
        return 'open'
    if rule in DASH_LOCAL_EXACT or rule.startswith(DASH_LOCAL_PREFIX):
        return 'localhost'
    return 'login'


def zero_public_gate(rule: str) -> str:
    return 'invite' if rule.startswith('/api/') else 'public'


GATES = {
    'dashboard': dashboard_gate,
    'zero_public': zero_public_gate,
    'medusa': lambda rule: 'ipgate',
}


# ------------------------------------------------------------ safe importing
@contextlib.contextmanager
def _no_threads():
    """Neuter Thread.start for the duration of an import.

    Importing crewai_web_gui spawns 19 daemon workers (market-scheduler,
    preempt-watcher, zpub-worker, ...). A second copy of those next to the
    live GUI would act on real data, so they must never start here. The Otel
    exporter thread is let through: atexit joins it and raises if it never ran.
    """
    real = threading.Thread.start

    def start(self):
        if self.name.startswith('Otel'):
            real(self)

    threading.Thread.start = start
    try:
        yield
    finally:
        threading.Thread.start = real


@contextlib.contextmanager
def _in_dir(path: str):
    prev = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


def load_apps():
    """Return {name: flask_app} for all four apps, threads suppressed."""
    os.environ['CREWAI_PAGE_LOAD_DEBUG'] = '0'
    if CREWS not in sys.path:
        sys.path.insert(0, CREWS)

    apps = {}
    with _no_threads():
        from zyg_dashboard import crewai_web_gui

        apps['dashboard'] = crewai_web_gui.app

        from zyg_zero import zero_public_server

        apps['zero_public'] = zero_public_server.app

        # medusa lives in a different tree and resolves its own siblings
        # relative to cwd; keep its path entry only for the import.
        if os.path.isdir(MEDUSA_DIR):
            sys.path.insert(0, MEDUSA_DIR)
            try:
                with _in_dir(MEDUSA_DIR):
                    import medusa_server
                apps['medusa'] = medusa_server.app
            finally:
                sys.path.remove(MEDUSA_DIR)
        else:
            print(
                f'[inventory] Medusa checkout not present ({MEDUSA_DIR}); its routes are not inventoried',
                file=sys.stderr,
            )
    return apps


# --------------------------------------------------------------- inventorying
def converter_names(app):
    """Reverse werkzeug's converter registry: class -> preferred short name."""
    rev = {}
    for name in sorted(app.url_map.converters):
        if name == 'default':  # alias of 'string'; prefer the readable one
            continue
        rev.setdefault(app.url_map.converters[name], name)
    return rev


def rule_params(rule, rev):
    """Converter names of the rule's path params, in the order they appear."""
    out = []
    for token in re.findall(r'<([^>]+)>', rule.rule):
        arg = token.split(':')[-1]
        conv = rule._converters.get(arg)
        out.append(rev.get(type(conv), type(conv).__name__) if conv else 'string')
    return out


def handler_source(view):
    """(relative_path:lineno, line_count, source_text) for a view function."""
    func = inspect.unwrap(view)
    try:
        path = inspect.getsourcefile(func)
        lines, lineno = inspect.getsourcelines(func)
    except (OSError, TypeError):
        return None, 0, ''
    rel = os.path.relpath(path, CREWS) if path else '?'
    return f'{rel}:{lineno}', len(lines), ''.join(lines)


def route_danger(rule: str, endpoint: str, methods: list, src: str) -> bool:
    """Does calling this route act on real state? See DANGER_RE / GET_ACTION_WORDS."""
    if methods != ['GET']:
        return bool(DANGER_RE.search(rule + ' ' + endpoint))
    last = rule.rstrip('/').rsplit('/', 1)[-1]
    if last in GET_ACTION_WORDS:
        return True
    return bool(HANDLER_WRITE_RE.search(src))


def inventory_app(name, app):
    rev = converter_names(app)
    gate_of = GATES[name]
    rows = []
    for rule in app.url_map.iter_rules():
        endpoint = rule.endpoint
        if endpoint == 'static' or endpoint.endswith('.static'):
            continue
        methods = sorted(m for m in (rule.methods or ()) if m not in ('HEAD', 'OPTIONS'))
        func, src_lines, src = handler_source(app.view_functions[endpoint])
        rows.append(
            {
                'rule': rule.rule,
                'methods': methods,
                'endpoint': endpoint,
                'blueprint': endpoint.split('.')[0] if '.' in endpoint else '',
                'params': rule_params(rule, rev),
                'func': func,
                'src_lines': src_lines,
                'danger': route_danger(rule.rule, endpoint, methods, src),
                'external': bool(EXTERNAL_RE.search(src)),
                'gate': gate_of(rule.rule),
                'risk': None,
                'empty_body_status': None,
            }
        )
    rows.sort(key=lambda r: (r['rule'], ','.join(r['methods'])))
    return rows


# ------------------------------------------------------------------- reporting
def counts(rows):
    body = [r for r in rows if set(r['methods']) - {'GET'}]
    return {
        'routes': len(rows),
        'get_only': sum(1 for r in rows if r['methods'] == ['GET']),
        'with_params': sum(1 for r in rows if r['params']),
        'body_methods': len(body),
        'danger': sum(1 for r in rows if r['danger']),
        'external': sum(1 for r in rows if r['external']),
    }


def write_markdown(path, apps):
    tick = {True: 'yes', False: ''}
    out = ['# Route inventory', '']
    out.append('| app | routes | GET-only | with params | body methods | danger | external |')
    out.append('|---|---:|---:|---:|---:|---:|---:|')
    for name, rows in apps.items():
        c = counts(rows)
        out.append(
            '| {} | {routes} | {get_only} | {with_params} | {body_methods} | {danger} | {external} |'.format(name, **c)
        )
    out.append('')
    for name, rows in apps.items():
        out += [
            f'## {name} ({len(rows)} routes)',
            '',
            '| rule | methods | gate | danger | external | func |',
            '|---|---|---|---|---|---|',
        ]
        for r in rows:
            out.append(
                '| `{}` | {} | {} | {} | {} | {} |'.format(
                    r['rule'],
                    ' '.join(r['methods']),
                    r['gate'],
                    tick[r['danger']],
                    tick[r['external']],
                    r['func'] or '?',
                )
            )
        out.append('')
    with open(path, 'w') as fh:
        fh.write('\n'.join(out))


def main():
    apps = load_apps()
    order = ['dashboard', 'zero_public', 'medusa']  # skill_proxy retired 2026-10-05
    inv = {name: inventory_app(name, apps[name]) for name in order}

    doc = {
        'generated': _dt.datetime.now(_dt.timezone.utc).isoformat(timespec='seconds'),
        'apps': inv,
    }
    with open(os.path.join(APITESTS, 'routes.json'), 'w') as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
        fh.write('\n')
    write_markdown(os.path.join(APITESTS, 'routes.md'), inv)

    for name in order:
        print(f'{name:12s} {counts(inv[name])}')
    print('threads alive:', sorted(t.name for t in threading.enumerate()))


if __name__ == '__main__':
    main()
