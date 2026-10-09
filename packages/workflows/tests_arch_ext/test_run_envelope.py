# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_run_envelope.py — proof for the fifth layer: an honest
run envelope.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_run_envelope.py

Job 71ac02b0 (2026-09-10) ended subtype 'error_max_turns' at turn 29 with NO
done call and was handed to the operator as status 'done' with the model's half
sentence "Now the aerial:" as the summary. This file pins the five things that
make that impossible:

  · the DRAWING BUDGET — MAX_CALLS counts calls that CHANGE the drawing; reads,
    checks, spec/explain and renders are free, and the CLI's --max-turns sits
    CLI_TURN_HEADROOM above the budget so a run can always reach done.
  · server_summary(job, d) — when the model never calls done the SERVER writes
    the summary out of the drawing: what was built, what the design check says,
    what the programme still wants.
  · job['auth'] — which credential the CLI used. It must be the login.
  · Drawing.request — the request's own words on the drawing, never in to_doc().
  · the present gate — done is refused until present() has shown THIS drawing.

Offline: no CLI is spawned, no GPU, no Blender. The CLI is driven with fake
stream-json events through a fake subprocess.
"""

import io
import json
import os
import sys
import threading
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402

from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
BP = A.EXT_MODULES['blender_power']


def job_of(jid: str, d, **extra) -> dict:
    j = {
        'id': jid,
        'status': 'running',
        'phase': 'drawing',
        'log': [],
        't0': time.time(),
        'steps': 0,
        'question': None,
        'error': None,
        'need': None,
        'result': None,
        'reply': '',
        'backend': 'claude',
        'cancel': False,
        'usage': None,
        'session': None,
        'model': None,
        'thinking': '',
        'thoughts': [],
        'think_s': 0.0,
        'reply_live': '',
        'auth': None,
        'incomplete': False,
        'stop': None,
        '_render': None,
        '_ev': threading.Event(),
        '_proc': None,
        '_token': 'tok-' + jid,
        '_d': d,
        '_final': '',
        '_draw_calls': 0,
        'body': {'text': 'x', 'session': '', 'history': []},
    }
    j.update(extra)
    A.JOBS[jid] = j
    return j


def shim(j, name, args):
    return A.shim_tool({'id': j['id'], 'token': j['_token'], 'name': name, 'args': args})


# ── (1) the drawing budget ───────────────────────────────────────────────────
print('drawing budget')
check(
    'budget: draws() knows a read from a draw',
    A.draws('draw_box')
    and not A.draws('get_state')
    and not A.draws('design_check')
    and not A.draws('measure_room')
    and not A.draws('list_floor_openings')
    and not A.draws('present'),
    [A.draws(n) for n in ('draw_box', 'get_state', 'design_check', 'measure_room', 'list_floor_openings', 'present')],
)
check('budget: an unknown tool is assumed to draw', A.draws('add_something_new'))

_MAX = A.MAX_CALLS
A.MAX_CALLS = 2
try:
    d = A.Drawing({'objects': []})
    j = job_of('tbudget', d)
    r1 = shim(j, 'draw_box', {'cell_from': 'C4', 'cell_to': 'F7', 'storeys': 1})
    check(
        'budget: the first drawing call runs and costs 1',
        r1.get('ok') and j['_draw_calls'] == 1 and len(d.added) >= 4,
        f'{j["_draw_calls"]} {str(r1)[:120]}',
    )
    r2 = shim(j, 'draw_box', {'cell_from': 'K4', 'cell_to': 'N7', 'storeys': 1})
    check(
        'budget: the second costs 1 and the log says so',
        r2.get('ok') and j['_draw_calls'] == 2 and any(l.startswith('budget: 2/2') for l in j['log']),
        f'{j["_draw_calls"]} {[l for l in j["log"] if l.startswith("budget")]}',
    )
    n_before = len(d.objs)
    r3 = shim(j, 'draw_box', {'cell_from': 'T4', 'cell_to': 'W7', 'storeys': 1})
    check(
        'budget: the third is REFUSED with the word budget and draws nothing',
        r3.get('ok')
        and 'budget' in r3.get('text', '')
        and 'refused' in r3.get('text', '')
        and len(d.objs) == n_before
        and j['_draw_calls'] == 2,
        str(r3)[:160],
    )
    check(
        'budget: the refusal names the way out (present, then done)',
        'present()' in r3.get('text', '') and 'done(summary)' in r3.get('text', ''),
        r3.get('text', '')[:160],
    )
    r4 = shim(j, 'get_state', {})
    check(
        'budget: a read still runs once the budget is spent',
        r4.get('ok') and 'refused: the drawing budget' not in r4.get('text', ''),
        str(r4)[:160],
    )
    check('budget: a read never costs budget', j['_draw_calls'] == 2)
    r5 = shim(j, 'design_check', {})
    check(
        'budget: the design check still runs on a spent budget',
        r5.get('ok') and 'refused: the drawing budget' not in r5.get('text', ''),
        str(r5)[:160],
    )
    v = A._job_view(j)
    check(
        'budget: the job view carries draw_calls and budget',
        v.get('draw_calls') == 2 and v.get('budget') == 2,
        {k: v.get(k) for k in ('draw_calls', 'budget')},
    )
finally:
    A.MAX_CALLS = _MAX
    A.JOBS.pop('tbudget', None)

cmd = A._cli_cmd({'id': 'tcmd', '_token': 'tok', 'body': {'session': ''}}, 'sys', True)
turns = cmd[cmd.index('--max-turns') + 1]
check(
    'budget: --max-turns sits above the drawing budget, so done is always reachable',
    int(turns) == A.MAX_CALLS + A.CLI_TURN_HEADROOM and A.CLI_TURN_HEADROOM >= 1,
    f'{turns} vs {A.MAX_CALLS} + {A.CLI_TURN_HEADROOM}',
)

# ── (2) the summary the server writes ────────────────────────────────────────
print('\nserver_summary')
d = A.Drawing({'objects': []})
A.call_tool(d, 'plan_building', {'use': 'residential', 'storeys': 20, 'centre': 'FH100', 'width': 20, 'depth': 20})
A.call_tool(d, 'draw_box', {'centre': 'FH100', 'width': 20, 'depth': 20, 'storeys': 20, 'roof': 'flat'})
d.new(
    'stair_u',
    {'steps': 285, 'rise': 0.14, 'run': 0.28, 'w': 1.2},
    0.0,
    0.0,
    0.0,
    0.0,
    'mat_concrete',
    name='the giant stair',
    grp='core',
)
jj = job_of('tsum', d, usage={'turns': 29}, reply='Now the aerial:')
txt = A.server_summary(jj, d)
A.JOBS.pop('tsum', None)
print('   ' + txt[:400])
check('summary: it says UNFINISHED and how many turns', 'UNFINISHED' in txt and '29 turns' in txt, txt[:160])
check('summary: it counts what was built, by kind', ('Built: +%d' % len(d.added)) in txt and ' slab' in txt, txt[:200])
check(
    'summary: it reports the design check in errors and warnings',
    'Design check:' in txt and 'errors' in txt and 'warnings' in txt,
    txt[:300],
)
prog = A.EXT_MODULES['building_program'].get_program(d)
rows = A.EXT_MODULES['building_program'].status(d, prog)
missing = [r['title'] for r in rows if r['need'] == 'required' and not r['ok']]
check('summary: the programme is real (a 20-storey block still wants required items)', bool(missing), rows and missing)
check(
    'summary: it names a required programme item that was not built',
    'Programme: required items not built:' in txt and any(t in txt for t in missing[:8]),
    (missing[:8], txt[-300:]),
)

d0 = A.Drawing({'objects': []})
check(
    'summary: an empty run still produces an honest sentence, never a crash',
    'UNFINISHED' in A.server_summary(job_of('tsum0', d0, usage={'turns': 1}), d0)
    and A.JOBS.pop('tsum0', None) is not None,
)

# ── (3) which credential the CLI used ────────────────────────────────────────
print('\nauth')
j = job_of('tauth', None)
A._cli_event(
    j,
    {
        'type': 'system',
        'subtype': 'init',
        'mcp_servers': [{'name': 'arch', 'status': 'connected'}],
        'apiKeySource': 'none',
        'model': 'claude-sonnet-4-6',
    },
    lambda s: j['log'].append(str(s)),
)
check("auth: apiKeySource 'none' is the operator's login", j['auth'] == 'login', j['auth'])
check(
    'auth: the log line says which credential was used',
    any('auth login' in l and 'tools connected' in l for l in j['log']),
    j['log'],
)
check('auth: no warning on a login run', not any(l.startswith('WARNING') for l in j['log']), j['log'])
j2 = job_of('tauth2', None)
A._cli_event(
    j2,
    {
        'type': 'system',
        'subtype': 'init',
        'mcp_servers': [{'name': 'arch', 'status': 'connected'}],
        'apiKeySource': 'ANTHROPIC_API_KEY',
        'model': 'claude-sonnet-4-6',
    },
    lambda s: j2['log'].append(str(s)),
)
check(
    'auth: an API key is named as one',
    str(j2['auth']).startswith('api-key:') and 'ANTHROPIC_API_KEY' in j2['auth'],
    j2['auth'],
)
check(
    'auth: an API key raises a WARNING in the log',
    any(l.startswith('WARNING: an API key reached the CLI') for l in j2['log']),
    j2['log'],
)
check('auth: the job view exposes auth', A._job_view(j2).get('auth') == j2['auth'])
A.JOBS.pop('tauth', None)
A.JOBS.pop('tauth2', None)

# ── (4) the request's own words ──────────────────────────────────────────────
print('\nDrawing.request')
check('request: a fresh drawing has an empty request, never None', A.Drawing(None).request == '')
check('request: it is read from the doc', A.Drawing({'request': 'make it luxurious'}).request == 'make it luxurious')
check(
    'request: to_doc() never writes it back (it is run state, not document state)',
    'request' not in A.Drawing({'request': 'x'}).to_doc(),
    sorted(A.Drawing({'request': 'x'}).to_doc()),
)

# ── (5) the present gate ─────────────────────────────────────────────────────
print('\npresent gate')
d = A.Drawing({'objects': []})
d.new('box', {'w': 4, 'd': 4, 'h': 2.7}, 0.0, 0.0, 0.0)
j = {'log': []}
ref = A.design_gate(j, d, {}, lambda s: j['log'].append(str(s)))
check(
    'present: done is refused while present() has not shown this drawing',
    'done REFUSED' in ref and 'call present() first' in ref and 'Attempt 1 of 2' in ref,
    ref[:200],
)
check(
    'present: the refusal names the views it renders',
    all(w in ref for w in ('approach', 'section', 'elevation', 'aerial', 'lobby')),
    ref[:250],
)
d.ext['presented'] = {'sig': BP.present_sig(d)}
check(
    'present: done passes once the stored signature matches the drawing', A.design_gate(j, d, {}, lambda s: None) == ''
)
d.new('box', {'w': 4, 'd': 4, 'h': 2.7}, 10.0, 0.0, 0.0)  # the drawing moved on after present()
ref2 = A.design_gate({'log': []}, d, {}, lambda s: None)
check('present: a drawing changed after present() is refused again', 'call present() first' in ref2, ref2[:160])
check(
    'present: force=true from the model no longer bypasses the gate',
    'call present() first' in A.design_gate({'log': []}, d, {'force': True}, lambda s: None),
)
j3 = {'log': [], '_gate': A.GATE_MAX}
check(
    'present: the gate gives up after GATE_MAX attempts, it does not block for ever',
    A.design_gate(j3, d, {}, lambda s: None) == '',
)

try:  # the NAME is the contract

    class _Stub:
        @staticmethod
        def present_sig(dd):
            return 'stub-signature'

    A.EXT_MODULES['blender_power'] = _Stub
    d2 = A.Drawing({'objects': []})
    check(
        'present: the gate reads present_sig off EXT_MODULES["blender_power"]',
        'call present() first' in A.design_gate({'log': []}, d2, {}, lambda s: None),
    )
    d2.ext['presented'] = {'sig': 'stub-signature'}
    check('present: the stub signature satisfies it too', A.design_gate({'log': []}, d2, {}, lambda s: None) == '')
finally:
    A.load_extensions(force=True)

# ── (6) the cap exit: a run that never called done ───────────────────────────
print('\ncap exit (fake CLI)')


class FakeProc:
    def __init__(self, lines):
        self.stdin = io.StringIO()
        self.stdout = iter(lines)
        self.stderr = io.StringIO('')
        self.returncode = 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class FakeSub:
    PIPE = -1

    def __init__(self, proc):
        self._p = proc

    def Popen(self, *a, **k):
        return self._p


SID = str(uuid.uuid4())
EVENTS = [
    json.dumps(
        {
            'type': 'system',
            'subtype': 'init',
            'mcp_servers': [{'name': 'arch', 'status': 'connected'}],
            'apiKeySource': 'none',
            'model': 'claude-sonnet-4-6',
        }
    )
    + '\n',
    json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Now the aerial:'}]}}) + '\n',
    json.dumps(
        {
            'type': 'result',
            'subtype': 'error_max_turns',
            'is_error': True,
            'num_turns': 29,
            'session_id': SID,
            'result': 'Reached max turns',
            'usage': {'input_tokens': 10, 'output_tokens': 5},
            'total_cost_usd': 0.01,
        }
    )
    + '\n',
]

d = A.Drawing({'objects': []})
A.call_tool(d, 'draw_box', {'centre': 'FH100', 'width': 4, 'depth': 4, 'storeys': 2, 'roof': 'flat'})
j = job_of('tcap', d)
_sub, _au = A.subprocess, A._audit
try:
    A.subprocess = FakeSub(FakeProc(EVENTS))
    A._audit = lambda: None
    raised = ''
    try:
        out = A._run_cli(j, d, lambda s: j['log'].append(str(s)), 'build me a tower', None, 'system')
    except Exception as e:  # noqa: BLE001
        out, raised = '', repr(e)
finally:
    A.subprocess, A._audit = _sub, _au
    A.JOBS.pop('tcap', None)

check('cap: a max-turns exit no longer raises', not raised, raised)
check('cap: the job is marked incomplete', j.get('incomplete') is True, j.get('incomplete'))
check("cap: job['stop'] carries the CLI's own subtype", j.get('stop') == 'error_max_turns', j.get('stop'))
check(
    'cap: the reply keeps the model text AND the server summary',
    'Now the aerial:' in out and 'UNFINISHED' in out and 'Design check:' in out,
    out[:300],
)
check('cap: the reply on the job is the same text', j.get('reply') == out)
check(
    'cap: the log says the server wrote the summary',
    any(l.startswith('UNFINISHED (error_max_turns)') for l in j['log']),
    [l for l in j['log'] if 'UNFINISH' in l],
)
check(
    'cap: the drawing is untouched and still injectable',
    len(d.added) >= 4 and isinstance(d.to_doc().get('objects'), list),
    len(d.added),
)
vj = A._job_view(j)
check(
    'cap: the job view exposes incomplete and stop',
    vj.get('incomplete') is True and vj.get('stop') == 'error_max_turns',
    {k: vj.get(k) for k in ('incomplete', 'stop')},
)

finish()
