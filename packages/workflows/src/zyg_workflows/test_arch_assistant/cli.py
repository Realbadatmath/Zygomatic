# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Claude Code CLI backend, offline: test_cli and test_cli_events."""

from zyg_workflows import arch_assistant as A
import json
import sys
import time
from zyg_workflows.test_arch_assistant.drawer import FIXTURE_TOKEN, check


def test_cli():
    """The Claude Code CLI backend, OFFLINE: the tool route (token, prefixed
    names, ask_user, done, look), the spawn env + command, the first turn, and
    the MCP shim end to end over HTTP against a throwaway server that speaks
    handle_get/handle_post. Nothing here spawns `claude`."""
    import http.server
    import os
    import subprocess
    import threading
    import urllib.parse

    print('cli backend (offline)')
    d = A.Drawing({'objects': []})
    job = {
        'id': 'tcli',
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
        '_render': None,
        '_ev': threading.Event(),
        '_proc': None,
        '_token': FIXTURE_TOKEN,
        '_d': d,
        '_final': '',
        'body': {'text': 'x', 'session': ''},
    }
    A.JOBS['tcli'] = job
    out, code = A.handle_get(A.PREFIX + '/tools', {'id': 'tcli', 'token': 'wrong'})
    check('cli: tool list refuses a bad token', code == 403 and not out.get('ok'))
    out, code = A.handle_get(A.PREFIX + '/tools', {'id': 'tcli', 'token': FIXTURE_TOKEN})
    names = [t['name'] for t in out.get('tools', [])]
    check(
        'cli: tool list carries the drawer + extensions',
        code == 200 and 'draw_box' in names and 'look' in names and len(names) == len(A.TOOL_DEFS),
        f'{code} {len(names)} vs {len(A.TOOL_DEFS)}',
    )
    out, code = A.handle_post(A.PREFIX + '/tool', {'id': 'tcli', 'token': 'wrong', 'name': 'draw_box', 'args': {}})
    check('cli: tool call refuses a bad token', code == 400 and not out.get('ok') and not d.added)
    out, code = A.handle_post(
        A.PREFIX + '/tool',
        {
            'id': 'tcli',
            'token': FIXTURE_TOKEN,
            'name': 'mcp__arch__draw_box',
            'args': {'cell_from': 'C4', 'cell_to': 'F7', 'storeys': 2},
        },
    )
    check(
        'cli: a prefixed tool name draws on the job copy',
        out.get('ok') and len(d.added) >= 8,
        f'{code} {out.get("error")} added={len(d.added)}',
    )
    check('cli: the call and its result land in the job log', any(l.startswith('draw_box(') for l in job['log']))
    out, _ = A.handle_post(
        A.PREFIX + '/tool',
        {'id': 'tcli', 'token': FIXTURE_TOKEN, 'name': 'ask_user', 'args': {'question': 'storeys or metres?'}},
    )
    check(
        'cli: ask_user posts the question and tells the model to stop',
        out.get('ok') and job['question'] == 'storeys or metres?' and 'End your turn' in out['text'],
    )
    job['question'] = None
    out, _ = A.handle_post(
        A.PREFIX + '/tool',
        {'id': 'tcli', 'token': FIXTURE_TOKEN, 'name': 'done', 'args': {'summary': 'a 4x4 house at C4'}},
    )
    check(
        'cli: done is refused until present() has shown this drawing',
        out.get('ok') and 'call present() first' in out.get('text', '') and not job['_final'],
        str(out)[:200],
    )
    d.ext['presented'] = {'sig': A.EXT_MODULES['blender_power'].present_sig(d)}  # what present() stores
    out, _ = A.handle_post(
        A.PREFIX + '/tool',
        {'id': 'tcli', 'token': FIXTURE_TOKEN, 'name': 'done', 'args': {'summary': 'a 4x4 house at C4'}},
    )
    check(
        'cli: done is refused while the design check finds errors (a 2-storey box with no stair)',
        out.get('ok') and 'design check found errors' in out.get('text', '') and not job['_final'],
        str(out)[:200],
    )
    out, _ = A.handle_post(
        A.PREFIX + '/tool',
        {'id': 'tcli', 'token': FIXTURE_TOKEN, 'name': 'done', 'args': {'summary': 'a 4x4 house at C4', 'force': True}},
    )
    # 2026-09-11: force is IGNORED (the author does not hold the gate). This is the gate's
    # third attempt, so it gives up — the drawing is handed over marked UNFINISHED with the
    # open error count and the design note, and the job carries incomplete=True.
    check(
        'cli: the third done is accepted marked UNFINISHED (force ignored, design note appended)',
        out.get('ok')
        and str(job['_final']).startswith('UNFINISHED')
        and 'a 4x4 house at C4' in str(job['_final'])
        and job.get('incomplete') is True
        and 'design error' in str(job.get('stop') or ''),
        (str(out)[:200], str(job['_final'])[:120], job.get('stop')),
    )

    def answer():
        for _ in range(200):
            if job['status'] == 'need_client':
                A.provide_render({'id': 'tcli', 'image': 'data:image/jpeg;base64,QUJD'})
                return
            time.sleep(0.02)

    threading.Thread(target=answer, daemon=True).start()
    out, _ = A.handle_post(
        A.PREFIX + '/tool', {'id': 'tcli', 'token': FIXTURE_TOKEN, 'name': 'look', 'args': {'view': 'top'}}
    )
    check(
        'cli: look parks in need_client and returns the studio picture',
        out.get('ok')
        and out.get('image') == ['image/jpeg', 'QUJD']
        and job['status'] == 'running'
        and (job.get('need') is None),
        str(out)[:120],
    )
    out, _ = A.handle_post(
        A.PREFIX + '/tool', {'id': 'tcli', 'token': FIXTURE_TOKEN, 'name': 'no_such_tool', 'args': {}}
    )
    check('cli: an unknown tool answers, never crashes', isinstance(out, dict) and 'ok' in out)
    # spawn env + command
    os.environ['ANTHROPIC_API_KEY'] = 'sk-test-only'
    os.environ['CLAUDECODE'] = '1'
    env = A._cli_env()
    os.environ.pop('ANTHROPIC_API_KEY', None)
    os.environ.pop('CLAUDECODE', None)
    check(
        'cli: the spawn env carries no API key and no nested-session marker (the login must bill)',
        'ANTHROPIC_API_KEY' not in env and 'CLAUDECODE' not in env and env.get('MCP_TOOL_TIMEOUT') == '180000',
    )
    check(
        'cli: the output cap is the CLI ceiling (64000) and the watchdog has room for it (>= 1800 s)',
        env.get('CLAUDE_CODE_MAX_OUTPUT_TOKENS') == '64000' and A.CLI_TIMEOUT >= 1800,
    )
    cmd = A._cli_cmd(job, 'sys', fresh=True)
    check(
        'cli: fresh spawn = new session id, sonnet, strict MCP, no built-in tools, tools allowed',
        '--session-id' in cmd
        and A._is_uuid(cmd[cmd.index('--session-id') + 1])
        and '--strict-mcp-config' in cmd
        and cmd[cmd.index('--tools') + 1] == ''
        and cmd[cmd.index('--model') + 1] == 'sonnet'
        and cmd[cmd.index('--allowedTools') + 1] == 'mcp__arch'
        and '--resume' not in cmd,
        ' '.join(cmd[:12]),
    )
    cfg = json.loads(cmd[cmd.index('--mcp-config') + 1])
    check(
        'cli: the MCP config spawns the shim with this job + token',
        cfg['mcpServers']['arch']['args'] == [A.SHIM]
        and cfg['mcpServers']['arch']['env']['ARCH_ASSIST_TOKEN'] == FIXTURE_TOKEN,
    )
    job['body']['session'] = '11111111-2222-3333-4444-555555555555'
    cmd = A._cli_cmd(job, 'sys', fresh=False)
    check(
        'cli: a known session is resumed',
        '--resume' in cmd
        and cmd[cmd.index('--resume') + 1] == job['body']['session']
        and job['session'] == job['body']['session'],
    )
    old = A.CLI_MODEL
    A.CLI_MODEL = 'claude-opus-5'
    check('cli: opus is refused (standing rule) -> sonnet', A._cli_model() == 'sonnet')
    A.CLI_MODEL = old
    msg = json.loads(A._cli_first_message('hello', ('image/jpeg', 'QUJD')))
    check(
        'cli: the first turn carries the viewport shot + the text',
        msg['type'] == 'user'
        and msg['message']['content'][0]['type'] == 'image'
        and msg['message']['content'][1]['text'] == 'hello',
    )
    check(
        'cli: pick_backend defaults to claude when the CLI exists',
        (A.pick_backend('', lambda s: None) == 'claude') == A.cli_available(),
    )
    check(
        'cli: the tab has no backend picker and sends the session',
        'ar-assist-be' not in open(A.HERE + '/inspection.html', encoding='utf-8').read()
        and "backend:'claude', session:AR.assist.session" in open(A.HERE + '/inspection.html', encoding='utf-8').read(),
    )

    # the shim, end to end
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, out, code):
            b = json.dumps(out).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            out, code = A.handle_get(u.path, q)
            self._send(out, code)

        def do_POST(self):
            n = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(n) or b'{}')
            out, code = A.handle_post(urllib.parse.urlparse(self.path).path, body)
            self._send(out, code)

    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = dict(
        os.environ,
        ARCH_ASSIST_URL=f'http://127.0.0.1:{srv.server_address[1]}',
        ARCH_ASSIST_JOB='tcli',
        ARCH_ASSIST_TOKEN=FIXTURE_TOKEN,
    )
    p = subprocess.Popen([sys.executable, A.SHIM], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
    reqs = [
        {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'initialize',
            'params': {
                'protocolVersion': '2025-06-18',
                'capabilities': {},
                'clientInfo': {'name': 't', 'version': '0'},
            },
        },
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}},
        {
            'jsonrpc': '2.0',
            'id': 3,
            'method': 'tools/call',
            'params': {'name': 'get_state', 'arguments': {'detail': 'summary'}},
        },
        {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'look', 'arguments': {'view': 'iso'}}},
        {'jsonrpc': '2.0', 'id': 5, 'method': 'ping'},
    ]
    threading.Thread(target=answer, daemon=True).start()
    out, _ = p.communicate('\n'.join(json.dumps(r) for r in reqs) + '\n', timeout=60)
    srv.shutdown()
    replies = {r['id']: r for r in (json.loads(l) for l in out.splitlines() if l.strip())}
    r1 = replies.get(1, {}).get('result', {})
    check(
        'shim: initialize answers with the tools capability + the client protocol version',
        r1.get('capabilities', {}).get('tools') == {} and r1.get('protocolVersion') == '2025-06-18',
    )
    tl = replies.get(2, {}).get('result', {}).get('tools', [])
    check(
        'shim: tools/list is the server list in MCP shape (inputSchema)',
        len(tl) == len(A.TOOL_DEFS)
        and all('inputSchema' in t for t in tl)
        and any(t['name'] == 'draw_box' for t in tl),
    )
    tc = replies.get(3, {}).get('result', {})
    check(
        'shim: tools/call forwards and returns text content',
        tc.get('isError') is False
        and tc.get('content', [{}])[0].get('type') == 'text'
        and bool(tc['content'][0]['text']),
        str(tc)[:160],
    )
    lk = replies.get(4, {}).get('result', {})
    check(
        'shim: a look comes back as an MCP image block + text',
        lk.get('isError') is False
        and lk.get('content', [{}])[0].get('type') == 'image'
        and lk['content'][0].get('data') == 'QUJD'
        and lk['content'][0].get('mimeType') == 'image/jpeg',
        str(lk)[:160],
    )
    check(
        'shim: ping answers, notifications get no reply', replies.get(5, {}).get('result') == {} and len(replies) == 5
    )
    A.JOBS.pop('tcli', None)


def test_cli_events():
    """The stream-json event parser, offline: thinking deltas feed the live
    tail, a finished block becomes a thought with its seconds, text deltas
    feed the live reply, the assistant event sets the reply and counts steps,
    the result event is returned, a failed MCP connect raises."""
    import tempfile
    import threading

    print('cli events (offline)')
    old_dir = A.CONV_DIR
    A.CONV_DIR = tempfile.mkdtemp(prefix='arch-ev-')
    job = {
        'id': 'tev',
        'status': 'running',
        'log': [],
        'steps': 0,
        'reply': '',
        'model': None,
        'cancel': False,
        'thinking': '',
        'thoughts': [],
        'think_s': 0.0,
        'reply_live': '',
        '_ev': threading.Event(),
    }
    log = lambda s: job['log'].append(str(s))
    E = A._cli_event
    se = lambda e: {'type': 'stream_event', 'event': e}
    SID = '11111111-2222-4333-8444-555555555555'
    r = E(
        job,
        {
            'type': 'system',
            'subtype': 'init',
            'model': 'claude-sonnet-4-6',
            'session_id': SID,
            'mcp_servers': [{'name': 'arch', 'status': 'connected'}],
        },
        log,
    )
    check('events: init records the model, returns nothing', r is None and job['model'] == 'claude-sonnet-4-6')
    led = lambda: [json.loads(l) for l in open(A._conv_path(), encoding='utf-8')]
    check(
        'events: init writes a session line with the transcript path (a killed run can still be tied to it)',
        led()[-1]['event'] == 'session'
        and led()[-1]['session'] == SID
        and job['_sid'] == SID
        and led()[-1]['transcript'].endswith('/' + SID + '.jsonl')
        and '/projects/-' in led()[-1]['transcript'],
        str(led()[-1])[:200],
    )
    big = 'x' * 6000
    E(job, se({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'thinking', 'thinking': ''}}), log)
    E(job, se({'type': 'content_block_delta', 'delta': {'type': 'thinking_delta', 'thinking': big}}), log)
    E(job, se({'type': 'content_block_stop', 'index': 0}), log)
    check(
        'events: a 6000-char thought is kept whole in the job (was capped at 4000)', job['thoughts'][-1]['text'] == big
    )
    check(
        'events: ...and written whole to the ledger the moment it ends',
        led()[-1]['event'] == 'thought'
        and led()[-1]['id'] == 'tev'
        and led()[-1]['text'] == big
        and led()[-1]['n'] == 1,
    )
    job['thoughts'] = []
    job['think_s'] = 0.0
    E(job, se({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'thinking', 'thinking': ''}}), log)
    E(job, se({'type': 'content_block_delta', 'delta': {'type': 'thinking_delta', 'thinking': 'The user wants '}}), log)
    E(job, se({'type': 'content_block_delta', 'delta': {'type': 'thinking_delta', 'thinking': 'a house at C4.'}}), log)
    check(
        'events: thinking deltas build the live tail',
        job['thinking'] == 'The user wants a house at C4.' and not job['thoughts'],
    )
    time.sleep(0.12)
    E(job, se({'type': 'content_block_stop', 'index': 0}), log)
    check(
        'events: block stop -> one thought with seconds, live tail cleared',
        len(job['thoughts']) == 1
        and job['thoughts'][0]['text'] == 'The user wants a house at C4.'
        and 0.1 <= job['thoughts'][0]['s'] <= 2
        and job['thinking'] == ''
        and job['think_s'] == job['thoughts'][0]['s'],
    )
    check(
        'events: the thought is in the job log',
        any(l.startswith('thought ') and 'house at C4' in l for l in job['log']),
    )
    E(
        job,
        {
            'type': 'assistant',
            'message': {'content': [{'type': 'thinking', 'thinking': 'The user wants a house at C4.'}]},
        },
        log,
    )
    check(
        'events: the whole-block assistant event does not duplicate a streamed thought',
        len(job['thoughts']) == 1 and job['steps'] == 0,
    )
    E(job, se({'type': 'content_block_start', 'index': 1, 'content_block': {'type': 'text', 'text': ''}}), log)
    E(job, se({'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'Building '}}), log)
    E(job, se({'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'now.'}}), log)
    check('events: text deltas feed the live reply', job['reply_live'] == 'Building now.')
    E(job, {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Building now.'}]}}, log)
    check(
        'events: the assistant text sets the reply, counts a step, clears the live reply',
        job['reply'] == 'Building now.' and job['steps'] == 1 and job['reply_live'] == '',
    )
    E(
        job,
        {
            'type': 'assistant',
            'message': {'content': [{'type': 'tool_use', 'name': 'mcp__arch__draw_box', 'input': {}}]},
        },
        log,
    )
    check('events: a tool_use counts a step', job['steps'] == 2)
    r = E(
        job, {'type': 'rate_limit_event', 'rate_limit_info': {'status': 'rejected', 'rateLimitType': 'five_hour'}}, log
    )
    check(
        'events: a rate-limit rejection lands as a NOTE',
        r is None and any(l.startswith('NOTE: Claude login rate limit: rejected') for l in job['log']),
    )
    r = E(job, {'type': 'result', 'subtype': 'success', 'usage': {}}, log)
    check('events: the result event is returned', r is not None and r.get('subtype') == 'success')
    job2 = dict(job, thoughts=[], think_s=0.0, _partials=False)
    E(job2, {'type': 'assistant', 'message': {'content': [{'type': 'thinking', 'thinking': 'whole block only'}]}}, log)
    check(
        'events: without deltas the whole-block thought is recorded',
        job2['thoughts'] and job2['thoughts'][0]['text'] == 'whole block only',
    )
    try:
        E(job, {'type': 'system', 'subtype': 'init', 'mcp_servers': [{'name': 'arch', 'status': 'failed'}]}, log)
        check('events: a failed MCP connect raises', False)
    except RuntimeError as e:
        check('events: a failed MCP connect raises', 'arch=failed' in str(e))
    cmd = A._cli_cmd({'id': 'x', '_token': 't', 'body': {'session': ''}}, 'sys', fresh=True)
    check('events: the CLI is spawned with partial messages (thinking streams)', '--include-partial-messages' in cmd)
    v = A._job_view(
        {
            'id': 'x',
            'status': 'running',
            'log': [],
            't0': time.time(),
            'thinking': 'tail',
            'thoughts': [{'text': 'a', 's': 1}],
            'think_s': 1.0,
        }
    )
    check(
        'events: a running job view carries the live tail and a count, not the list',
        v['thinking'] == 'tail' and v['thoughts_n'] == 1 and 'thoughts' not in v,
    )
    A.CONV_DIR = old_dir
    v = A._job_view(
        {
            'id': 'x',
            'status': 'done',
            'log': [],
            't0': time.time(),
            'thinking': '',
            'thoughts': [{'text': 'a', 's': 1}],
            'think_s': 1.0,
            'result': None,
        }
    )
    check(
        'events: a finished job view carries the thoughts',
        v['thoughts'] == [{'text': 'a', 's': 1}] and v['think_s'] == 1.0,
    )
    html = open(A.HERE + '/inspection.html', encoding='utf-8').read()
    check(
        'events: the panel renders thoughts and the live tail',
        'arAssistThoughtsHtml' in html
        and 'arAssistWaitHtml' in html
        and "j.think=d.thinking||''" in html
        and 'details class="think"' in html,
    )
