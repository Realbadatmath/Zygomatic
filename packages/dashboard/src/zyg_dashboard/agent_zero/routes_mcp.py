# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""routes_mcp.py — the HTTP bridge the subscription backend's MCP shim talks to.

Why this exists. On the `subscription` backend the thing that produces tool
calls is the Claude Code CLI, a separate process on the operator's login. It
can only reach tools through MCP, and mcp_shim.py (the stdio server the CLI
spawns) is deliberately stateless: both of its methods come back here, so the
turn's tool map, its budget, its confirmations and its audit trail stay in the
dashboard process and the subscription backend behaves exactly like the API
ones.

Two routes, both for one turn only:
  GET  /api/zero/v2/mcp/<turn_id>/tools?token=…   -> {'ok', 'tools': [...]}
  POST /api/zero/v2/mcp/<turn_id>/call            -> the execute_tool dict

Authorisation is three gates, all of which must pass:
  * the turn id must name a live turn in runner.TURNS;
  * the per-turn token must match (constant-time compare);
  * the request must come from this machine (127.0.0.1 / ::1).
The shim also forwards the user's dashboard session cookie and CSRF header, so
the dashboard's own login gate sees an ordinary logged-in request; the token is
what binds the call to one turn.

WHERE THE TOKEN LIVES (the choice CONTRACT C left open, documented once):
`ctx.extra['mcp_token']` is authoritative — the backend owns the TurnContext and
writes the secret there before the CLI process starts. `turn.mcp_token` is
accepted as a fallback for runners that prefer to mint it themselves.
The backend reaches the turn through `runner.TURNS[turn_id].ctx`, so the turn
runner (agent_zero/runner.py) must store the context it built as `turn.ctx`.
"""

import hmac
import logging

from flask import jsonify, request

from . import bp

_log = logging.getLogger(__name__)

LOCAL_ADDRS = ('127.0.0.1', '::1')
TOOL_PREFIX = 'mcp__zero__'
REFUSED = {'ok': False, 'error': 'refused'}


def _runner():
    try:
        from . import runner
    except ImportError:  # the runner is not loaded in this process
        _log.warning('agent_zero.runner is not importable — the MCP bridge has no turns to serve')
        return None
    return runner


def _turn_token(turn) -> str:
    """The per-turn secret. ctx.extra['mcp_token'] first (the backend writes it
    there), then turn.mcp_token."""
    # runner.TURNS holds plain dicts (the Turn is turn['ctx'].extra['turn']); accept
    # an attribute-style object too so a test stub keeps working.
    ctx = turn.get('ctx') if isinstance(turn, dict) else getattr(turn, 'ctx', None)
    extra = getattr(ctx, 'extra', None)
    if isinstance(extra, dict) and extra.get('mcp_token'):
        return str(extra['mcp_token'])
    if isinstance(turn, dict):
        return str(turn.get('mcp_token') or '')
    return str(getattr(turn, 'mcp_token', '') or '')


def _authorised(turn_id: str, token: str):
    """(turn, None) when every gate passes, else (None, the refusal response)."""
    if request.remote_addr not in LOCAL_ADDRS:
        _log.warning('zero mcp bridge: refused a non-local request from %s', request.remote_addr)
        return None, (jsonify(REFUSED), 403)
    runner = _runner()
    turn = (getattr(runner, 'TURNS', None) or {}).get(turn_id) if runner is not None else None
    if turn is None:
        _log.warning('zero mcp bridge: unknown turn %s', turn_id)
        return None, (jsonify(REFUSED), 403)
    want = _turn_token(turn)
    if not want or not token or not hmac.compare_digest(str(token), want):
        _log.warning('zero mcp bridge: bad token for turn %s', turn_id)
        return None, (jsonify(REFUSED), 403)
    return turn, None


@bp.get('/api/zero/v2/mcp/<turn_id>/tools')
def zero_mcp_tools(turn_id: str):
    """The three meta-tools, in CONTRACT C shape ('input_schema'); the shim
    renames the key to MCP's 'inputSchema'."""
    _turn, refusal = _authorised(turn_id, request.args.get('token') or '')
    if refusal is not None:
        return refusal
    from . import toolmap

    return jsonify({'ok': True, 'tools': toolmap.tool_specs()})


@bp.post('/api/zero/v2/mcp/<turn_id>/call')
def zero_mcp_call(turn_id: str):
    """One tool call from the CLI, executed by the turn's own executor so that
    the budget, the confirmations and the audit trail are the ones the turn
    already owns."""
    body = request.get_json(silent=True) or {}
    turn, refusal = _authorised(turn_id, body.get('token') or '')
    if refusal is not None:
        return refusal
    name = str(body.get('name') or '')
    name = name.removeprefix(TOOL_PREFIX)
    args = body.get('args')
    if not isinstance(args, dict):
        args = {}
    ctx = turn.get('ctx') if isinstance(turn, dict) else getattr(turn, 'ctx', None)
    execute_tool = getattr(ctx, 'execute_tool', None)
    if not callable(execute_tool):
        _log.error('zero mcp bridge: turn %s has no ctx.execute_tool', turn_id)
        return jsonify(REFUSED), 403
    return jsonify(execute_tool(name, args))
