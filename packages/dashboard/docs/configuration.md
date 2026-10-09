# Configuration

Environment variables read by `zyg_dashboard`. All are optional: with none of them
set the dashboard serves and links only to the loopback interface, which is the safe
default for a fresh checkout. Set them in the systemd unit (or the shell that starts
the service) to publish the stack on a local network.

| Variable | Default | Read by | What it does |
| --- | --- | --- | --- |
| `ZYG_LAN_HOST` | `127.0.0.1` | `hub/hub_launcher.py`, `hub/hub_server.py`, `hub/gamesim_server.py` | Host the hub cards and the Game Simulator "← Hub" link point at. The hub page is a LAN bookmark opened from phones and other machines, so its card URLs cannot be `127.0.0.1` unless you are sitting at the box. Set it to this machine's LAN address (e.g. `10.0.0.5`) to publish it. Hostnames work too. |
| `ZYG_SESSION_TREE_URL` | `http://127.0.0.1:7100` | `session_tree/st_cli.py` | Base URL of the Session Tree board the `st` CLI talks to, and the URL it prints after `st create`. Include the scheme and port, no trailing slash. |
| `ZYG_MEDUSA_APP_DIR` | `~/Zygomatic/medusa` | `apitests/inventory.py` | Checkout of the Medusa app (a separate project) whose routes the API-test inventory imports alongside the dashboard's. Only the inventory reads it. |
| `ZYG_LAN_ALLOWLIST` | empty (loopback only) | — | Comma-separated list of extra client IPs allowed to reach the loopback-only internal APIs. Empty means loopback only (`127.0.0.1`, `::1`), which is what every current `remote_addr` check enforces. Reserved: no module reads it yet. |
| `ZYG_CORS_ORIGINS` | empty (same-origin only) | `cors.py`, and through it every endpoint that answers cross-origin: `bp_assets_media.py`, `bp_pipeline_api.py`, `bp_integrity_ops.py`, `bp_agents_api.py`, `bp_medusa.py`, `crewai_web_gui.py` (the 429 handler), `hub/gamesim_server.py`, `hub/restart_api.py` | Comma-separated list of browser origins allowed to read cross-origin responses, each with scheme and port and no trailing slash (e.g. `http://127.0.0.1:8899,http://10.0.0.5:8090`). Empty means no `Access-Control-Allow-Origin` header is sent at all, so the browser enforces same-origin — the safe default for a fresh checkout. An origin that is not on the list gets no header; the wildcard `*` is never sent. |

Notes:

- `ZYG_CORS_ORIGINS` is what the in-house cross-origin callers need: the kanban boards
  on :8899 (pipeline, Medusa and asset status polling, and the children's / movement
  panels), the Creator Nexus frontend on :8090 (autosave), Medusa on :5300 (Picture
  Studio tools) and the hub on :7000 (restart API). List the origins the *browser* uses
  — the address bar of the page, not the service being called. Server-to-server calls on
  127.0.0.1 are unaffected: CORS is a browser rule, and those paths have their own
  loopback-only bypasses (listed in one block in `crewai_web_gui.py`).

- Pages served to a browser do **not** use `ZYG_LAN_HOST` where the target is the same
  machine on another port — `templates/dashboard/_chrome_sidebar.html` (hub icon, :7000)
  and `templates/remixai_manage.html` (inspection, :8899) rewrite their links from
  `location.hostname`, so they follow whatever address the viewer used.
- `deploy/dashboard_launcher.bat` (Windows) takes its working directory from
  `ZYG_PROJECT_DIR`, defaulting to `%USERPROFILE%\Desktop\Zygomatic Origin\Agents\crewai_project`.
