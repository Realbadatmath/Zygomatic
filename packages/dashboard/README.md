# zygomatic-dashboard

The operator surface of the Zygomatic production system: a Flask web GUI, a kanban
board, an approval queue, a set of metrics hubs, a launcher hub and an agent job
board. It drives the pipelines — it does not implement them. The pipelines,
studios and services live in **zygomatic-workflows**, which this package imports.

## What is in here

| Thing | Where | Notes |
| --- | --- | --- |
| **Dashboard GUI** | `src/zyg_dashboard/crewai_web_gui.py` + 37 `bp_*.py` blueprints | 430 route decorators across 38 registered blueprints: pipelines, studios (picture, char2d, movement, remix, storyteller, kids series, kids music, sports), assets and media, voices, safety, schedules, benchmarks, market. Port 5000. |
| **Kanban board** | `src/zyg_dashboard/kanban_server.py`, `kanban.html`, `inspection.html` | A standalone `http.server` on port 8899 that serves the board and the inspection API, and polls the dashboard API on :5000. Also the voice bridge (Server-Sent Events). |
| **Approval queue** | `bp_approval_queue.py`, `approval_queue_settings.py` | Renders wait for a human verdict before they are published. |
| **Metrics hubs** | `metrics_hub.py`, `analytics_hub.py`, `capabilities_hub.py`, `expansion_hub.py`, `test_data_hub.py` | Quota in euros, per-model cost splits, machine utilisation, QC gate trends, capability inventory. Fed on timers by `quota_meter.py`, `sysusage_sampler.py` and the run ledger in `zyg_workflows`. |
| **Session Tree** | `src/zyg_dashboard/session_tree/` | A job board for Claude agents on port 7100, with the `st` CLI (`st_cli.py`). |
| **Hub launcher** | `src/zyg_dashboard/hub/` | A LAN bookmark page of cards that start and stop the other services: `hub_server.py` on 7000, `restart_api.py` on 7001, `hub_launcher.py` on 7777, supervised by `hub_watch.py`. |
| **Deployment** | `deploy/` | systemd user units, Dockerfiles, compose files, nginx front door. See [deploy/README.md](deploy/README.md). |
| **API test layer** | `tests/api/`, `apitests/` | In-process pytest layer and a generated Postman collection. See [apitests/README.md](apitests/README.md). |

## How it relates to zygomatic-workflows

`zyg_dashboard` imports `zyg_workflows`; `zyg_workflows` never imports
`zyg_dashboard`. That direction is enforced by import-linter (`.importlinter`,
run by `scripts/scan.sh`), so the base library stays usable without the GUI.

Install both, editable, into one virtualenv — workflows first:

```bash
git clone <workflows-url> ~/repos/zygomatic-workflows
git clone <dashboard-url> ~/repos/zygomatic-dashboard
python3.11 -m venv ~/repos/.venv
~/repos/.venv/bin/pip install -e ~/repos/zygomatic-workflows
~/repos/.venv/bin/pip install -e '~/repos/zygomatic-dashboard[dev]'
```

`bash deploy/setup_ubuntu.sh` does that plus the system packages (ffmpeg,
libsndfile, portaudio, postgresql, nginx) and writes the environment file with a
fresh secret key. `~/repos/.venv` is the path the shipped systemd units expect.

## Running the servers

Every server is a module; none of them wants a working directory inside the
package. `FLASK_SECRET_KEY` must be set or the dashboard raises `RuntimeError`
at import.

```bash
export FLASK_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')

python -m zyg_dashboard.crewai_web_gui                   # GUI            :5000
python -m zyg_dashboard.kanban_server                    # kanban board   :8899
python -m zyg_dashboard.session_tree.session_tree_server # agent board    :7100
python -m zyg_dashboard.hub.hub_server                   # hub cards      :7000
python -m zyg_dashboard.hub.hub_launcher                 # hub launcher   :7777
```

On a real host use the user units instead
(`deploy/systemd/user/*.service`, installed with `systemctl --user`); they read
one environment file at `~/.config/zygomatic/env` and restart on failure.
`deploy/dashboard_launcher.sh` is the same auto-restart loop for a terminal.

Several hubs and blueprints can re-import their collector module on every
request so an edited collector goes live without a GUI restart. That hot-reload
is off by default and armed by one environment variable, `ZYG_DEV_RELOAD=1`
(`zyg_workflows.devreload.maybe_reload`): unset, each call site hands the
already-imported module straight back; set to `1`, it calls
`importlib.reload()` as before. Leave it unset in production — reloading costs
a module re-execution per request and throws away every module-level cache, and
for a module that has become a package it only re-executes `__init__.py` anyway.
Export it in a development shell before starting the GUI.

## What needs a GPU

The GUI, the kanban board, the hubs, the session tree and the whole API test
layer run on CPU. Generation does not: image and video routes drive ComfyUI
(port 8188) or load FLUX in-process, upscales load RealESRGAN, voice loads a TTS
model, and the 3D routes drive Blender. Those need a CUDA device and the model
weights under `ZYG_MODELS_ROOT` (default `~/ai-models`). Without a GPU, start
from `deploy/docker-compose.cpu.yml` and expect every render route to fail.

Tests that need a device or a running service are marked, so they can be skipped:
`pytest -m "not gpu and not service"`.

## Authentication

Three roles: `admins`, `operators` and `spectators` (view-only, no credentials).
`bp_auth.py` validates a role plus an id and password against a users file and
puts the role in the Flask session; `/api/login` is rate-limited to 10 requests a
minute per address, and every session carries a CSRF token and a validity token
that is invalidated by a server restart.

The users file (`dashboard_users.json`) is **not** in this repository and is never
committed — it is created at runtime next to the package, or at the path
`dashboard_config.USERS_DATA_PATH` names. Passwords are stored as a
`password_hash` and compared with `hmac.compare_digest`; the plaintext `password`
and `passwords` fields are a migration fallback only and should not be used.
`FLASK_SECRET_KEY` and every API key belong in the environment file, outside the
repository, mode 0600 — see [deploy/README.md](deploy/README.md).

## Network exposure

The default posture is loopback: with no environment variables set, the stack
serves and links only to `127.0.0.1`, and the internal APIs enforce a
`remote_addr` check. Two exceptions are worth knowing before you expose the
machine: `crewai_web_gui` and `kanban_server` bind `0.0.0.0`, so put them behind
the nginx front door (`deploy/nginx/`) or a firewall. `ZYG_LAN_HOST` is what
publishes the hub cards on a LAN address instead of loopback.

Every variable the dashboard reads — `ZYG_LAN_HOST`, `ZYG_SESSION_TREE_URL`,
`ZYG_LAN_ALLOWLIST` — is documented in [docs/configuration.md](docs/configuration.md).
Filesystem roots and service URLs come from `zyg_workflows.paths`, and
`zyg_workflows.settings` is the generated registry of every `ZYG_*` flag.

## Tests

```bash
pytest -m "not gpu and not service"   # the suite a laptop can run
pytest tests/api                      # in-process HTTP layer, no server needed
bash scripts/scan.sh                  # the full publishability gate
```

`tests/api/` imports the Flask app and pushes requests through `test_client`, so
it needs no network socket and no running service. `apitests/` is the second
layer: a Postman collection generated from the same route inventory, run with
newman against a live server — use it to explore, and the pytest layer for proof.

`scripts/scan.sh` is what CI runs: ruff check and format, bandit, gitleaks,
reuse lint, import layering, `compileall`, test collection and a personal-data
grep. Exit 0 means publishable. `pre-commit install` runs the fast half of it
before every commit. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

AGPL-3.0-or-later. Every file carries an SPDX header and the repository is
[REUSE](https://reuse.software) compliant — `reuse lint` is part of the gate.
Full text in [LICENSE](LICENSE); security reports in [SECURITY.md](SECURITY.md).
