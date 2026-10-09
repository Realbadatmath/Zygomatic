# Agent Zero v2

Zero v2 is the dashboard's chat agent: one window (hotkey `Z`) where the operator talks to a
model that can *drive the dashboard itself* through a tool map, with a model picker, a token
budget and its own metrics section. It replaces the preset-button chat of `bp_zero.py` +
`Static/js/dashboard_agent_zero.js` (both still on disk; the old JS is no longer referenced by
any template).

Wired into the live dashboard on 2026-10-08: `crewai_web_gui.py` registers
`agent_zero.bp` (blueprint name `zero_v2`) right after `bp_zero`, and
`templates/enhanced_dashboard.html` loads the six v2 frontend files.

## Files

| Path | What it is |
|---|---|
| `agent_zero/__init__.py` | `bp = Blueprint('zero_v2', …)`; imports the four route modules |
| `agent_zero/_host.py` | CONTRACT A — the **only** module allowed to touch host code (`crewai_web_gui`, `quota_meter`, `subscription_llm`, `llm_audit`, `bp_claude_clip`) |
| `agent_zero/contracts.py` | CONTRACT C — `TurnContext`, the event dicts, `PROVIDERS`, `BACKEND_FOR`, `estimate_tokens` |
| `agent_zero/models.py` + `models_catalog.json` | provider status, live model lists, selection, Ollama install jobs, provider-key store |
| `agent_zero/prompt.py` | builds the system prompt (fixed text + tool index + state snapshot + budget line) |
| `agent_zero/runner.py` | `start_turn` / `run_turn`: budget gate, compaction, `TURNS`, the event stream, booking |
| `agent_zero/backends/` | `subscription` (Claude Code CLI), `anthropic_api`, `openai_compat`, `ollama`, `fake` |
| `agent_zero/toolmap.py` + `toolmap.json` | the 138-tool catalogue in 10 groups and the three meta-tools |
| `agent_zero/toolmap_exec.py` | executes a tool, enforces risk class / confirmation, clips the result |
| `agent_zero/mcp_shim.py` | stdio MCP server the Claude Code CLI spawns; relays `tools/list` and `tools/call` back to `routes_mcp.py` |
| `agent_zero/memory.py` | session store (messages, title, pins, rolling summary) |
| `agent_zero/budget.py` | `DEFAULTS`, the per-turn/session/day/week gates, the override grant |
| `agent_zero/metrics.py` | CONTRACT F — the per-turn ledger and the whole `section_zero` reduction |
| `agent_zero/routes_{models,chat,mcp,budget}.py` | the HTTP surface (below) |
| `Static/js/agent_zero_v2/` | `zero_markdown.js`, `zero_chat.js`, `zero_chat_transcript.js`, `zero_models.js`, `zero_requests.js`, `zero_livetail.js` |
| `Static/css/agent_zero_v2.css` | the chat window, picker and live-tail styles |
| `data/agent_zero.json` | config: `selected_model`, Zero's role/goal, the legacy `llms` map |
| `data/runtime/zero_metrics.jsonl` | one row per finished turn (the ledger the Metrics tab reads) |
| `data/runtime/zero_tool_log.jsonl` | one line per executed tool |
| `data/runtime/zero_installs.jsonl` | one line per Ollama install job |
| `data/runtime/zero_provider_keys.json` | API keys, mode 0600, never returned by the API |

## HTTP API (CONTRACT G)

All under `/api/zero/v2/`, all session-authed by the dashboard's own `require_login`
(POSTs need the `X-CSRF-Token` header, like every other dashboard API).

Models and providers
- `GET  /models` → `{selected, providers, defaults, machine}`
- `POST /models/select` `{provider, model}` → persists `selected_model`
- `POST /models/install` `{name, confirm: true}` → an Ollama pull job; `GET /models/install/<job_id>`
- `GET  /models/machine` → VRAM / RAM / disk as the fit check sees them
- `POST|DELETE /providers/<provider>/key` → set/clear an API key (returns only `{set, suffix}`)

Chat
- `GET  /greeting` → `{text: 'Hi <name>, how can I help you?', user, selected}`
- `GET  /tools` → the tool index text (`?group=`, `?q=`)
- `GET|POST /sessions`, `GET|DELETE /sessions/<id>`, `POST /sessions/<id>/{rename,pin,unpin}`
- `POST /sessions/<id>/turn` `{message, image_b64?, provider?, model?}` → `202 {turn_id}`
- `GET  /turns/<turn_id>` → snapshot (for pollers); `POST /turns/<turn_id>/cancel`
- `GET  /turns/<turn_id>/events` → **SSE**; frames are `event: <type>` + a CONTRACT C event dict:
  `text_delta`, `thinking`, `tool_call`, `tool_result`, `usage`, `confirm`, `error`, `done`
- `POST /sessions/<id>/confirm` → run a tool that asked for confirmation

Budget: `GET /budget`, `POST /budget`, `POST /budget/override`.
MCP bridge (localhost + per-turn token only): `GET /mcp/<turn_id>/tools`, `POST /mcp/<turn_id>/call`.

Note the ordering trap: the `done` **event** is emitted before the transcript is booked, so a
client that stops at `done` is microseconds ahead of `GET /turns/<id>`'s `done` flag — poll it.

## Tool map and risk classes

`toolmap.json` (version 1) holds **138 tools in 10 groups**: `system` (20), `zero_legacy` (18),
`memory` (2), `approvals` (6), `agents` (10), `pipelines` (39), `launch` (18), `services` (16),
`code` (7), `shell` (2). The model never sees 138 tool schemas — it gets three meta-tools
(`zero_index`, `zero_find`, `zero_call`) and calls `zero_call` with a tool id.

Risk classes (measured today: 109 `read`, 7 `act`, 22 `danger`):
- `read` — runs immediately, nothing changes.
- `act` — changes state; runs, is logged to `zero_tool_log.jsonl`.
- `danger` — needs explicit confirmation: `toolmap_exec` returns
  `needs_confirmation` + a `confirm_id`, the runner emits a `confirm` event, and the operator
  (or `POST /sessions/<id>/confirm`) has to approve before it executes.

## Budget rules (`budget.DEFAULTS`)

- per turn: `max_context_tokens` 14000 (over it the turn is **refused**, never trimmed),
  `max_tool_calls` 12, `max_output_tokens` 4096, `thinking_tokens` 0,
  `tool_result_max_chars` 6000, `timeout_s` 600
- per session: `max_turns` 300, `compact_after_tokens` 24000, `keep_recent_turns` 8
- per day (Amsterdam): `soft_tokens` 150000 (warn), `hard_tokens` 400000 (block), `max_turns` 400
- per week: `zero_share_cap_pct` 20, `meter_reserve_pct` 90, `fable_cap_pct` 50
- policy: `allow_local_when_blocked` true (Ollama still answers when the API budget is spent),
  `override_turns_granted` 10

A blocked turn comes back as `429` with `kind: 'budget'`; `POST /budget/override` grants the
next N turns.

## Metrics

`GET /api/metrics/hub/zero` → section `zero` (Metrics hub + the Metrics tab, served by
`metrics_hub.section_zero`, which delegates to `agent_zero.metrics.section_zero`). Payload:
`totals`, `by_model`, `by_tool`, `daily`, `compute_ms`, `installs`, `recent_turns`,
`recent_errors`, `budget`, `selected`, `sources`, `notes`. The source of truth is the
append-only `data/runtime/zero_metrics.jsonl` (28 fixed columns per turn).

## Adding a provider

1. Add the id to `contracts.PROVIDERS` and map it in `contracts.BACKEND_FOR` (the value is a
   module name **relative to `agent_zero.backends`**, e.g. `'openai_compat'`).
2. OpenAI-compatible endpoints need no new code — add the base URL and seed models to
   `models_catalog.json`. Anything else gets its own `agent_zero/backends/<name>.py` with
   `run(ctx) -> Iterator[dict]` (CONTRACT C events, exactly one `done`) and `probe() -> dict`.
3. Heavy SDKs stay lazy: import inside the function, never at module import.

## Adding a tool

Add an entry to the right group in `agent_zero/toolmap.json`: `id` (`group.name`), `title`,
`kind` (`http` …), `method`, `path`, `risk`, `params`, `desc`. `toolmap.py` indexes it and
`toolmap_exec.py` executes it; nothing else changes. Keep the index text small — it is in every
system prompt (measured 614 est. tokens for all 138 tools).

## Tests

```bash
cd "/home/zygomatic/Zygomatic Full/agents/crews"
../.venv/bin/python -m pytest tests/test_agent_zero_*.py            # unit, no app import
../.venv/bin/python -m pytest tests/api/test_agent_zero_chat.py tests/api/test_agent_zero_toolmap.py
```

Lint (there is no `python -m ruff` in the venv):

```bash
/home/zygomatic/repos/.tools/venv/bin/ruff check agent_zero/<file>.py
/home/zygomatic/repos/.tools/venv/bin/ruff format --line-length 120 \
    --config "format.quote-style = 'single'" agent_zero/<file>.py
```

## Restart procedure

The dashboard is a systemd unit, so a Python change is live only after a restart. Before
restarting, check that nothing long-running is mid-flight:

```bash
curl -s http://127.0.0.1:5000/api/preempt/state      # every target's "running" must be []
curl -s http://127.0.0.1:8899/inspect/api/architecture/assistant/active   # "running": 0
sudo -n /usr/bin/systemctl restart crewai-gui.service   # max 3 restarts / 15 min
curl -sf http://127.0.0.1:5000/api/health
tail -n 80 data/runtime/flask.log                    # check for tracebacks
```

Frontend-only changes need no restart, but bump the `?v=` query on the changed
`Static/js/agent_zero_v2/*.js` / `Static/css/agent_zero_v2.css` tag in
`templates/enhanced_dashboard.html` or browsers keep the cached copy.
