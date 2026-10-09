# Deploying the Zygomatic dashboard

Everything in this directory assumes two checkouts side by side and one virtualenv
shared between them:

```
~/repos/
  .venv/                     the only interpreter the units use
  zygomatic-workflows/       the base library (zyg_workflows)
  zygomatic-dashboard/       this repository (zyg_dashboard)
```

Nothing here contains an absolute home directory. The systemd units use systemd's
`%h` specifier, the containers use `/app`, and every host-specific value lives in
one environment file outside the repository.

## 1. Install order

`zyg_dashboard` imports `zyg_workflows`, never the reverse, so workflows goes first.

```bash
git clone <workflows-url> ~/repos/zygomatic-workflows
git clone <dashboard-url> ~/repos/zygomatic-dashboard
python3.11 -m venv ~/repos/.venv
~/repos/.venv/bin/pip install -e ~/repos/zygomatic-workflows
~/repos/.venv/bin/pip install -e '~/repos/zygomatic-dashboard[dev]'
```

`bash deploy/setup_ubuntu.sh` does the same thing plus the system packages
(ffmpeg, libsndfile, portaudio, postgresql, nginx) and creates the environment
file with a fresh secret key.

## 2. The environment file

One file, **outside** the repository, mode 0600, never committed:

```
~/.config/zygomatic/env
```

Every unit in `systemd/` reads it as `EnvironmentFile=%h/.config/zygomatic/env`,
`deploy/dashboard_launcher.sh` sources it, and the compose files pass it through
`ZYG_ENV_FILE`. It is a plain `KEY=value` file — no quoting, no shell expansion.

| Key | Required | What it is |
| --- | --- | --- |
| `FLASK_SECRET_KEY` | **yes** | Flask session signing key. The app raises `RuntimeError` at import without it. Generate with `python -c "import secrets; print(secrets.token_hex(32))"`. |
| `ANTHROPIC_API_KEY` | no | Claude features; absent = those routes degrade. |
| `OPENAI_API_KEY` | no | GPT features; same. |
| `DATABASE_URL` | no | Postgres for the run ledger and the QC trend job. The GUI starts without it. |
| `REDIS_PASSWORD` | compose | Read by the compose files to set and check `requirepass`. |
| `FLASK_PORT` | no | Host port the container publishes (default 5000). |
| `ZYG_LAN_HOST` | no | Address the hub cards and the Game Simulator link point at. Default `127.0.0.1`. |
| `ZYG_SESSION_TREE_URL` | no | Base URL the `st` CLI talks to. Default `http://127.0.0.1:7100`. |
| `ZYG_MODELS_ROOT` | no | Model weights root. Default `$HOME/ai-models`. `ZYG_COMFY_ROOT`, `ZYG_FLUX_ROOT` and `ZYG_REALESRGAN_ROOT` default to subdirectories of it. |
| `ZYG_DATA_ROOT`, `ZYG_OUTPUT_ROOT` | no | Runtime state and renders. Default under `ZYG_CREWS_ROOT`. |
| `BIND_HOST` | no | Interface the workflow services bind. Default `127.0.0.1`. |

`zyg_workflows.paths` holds every filesystem root and service URL with its
default; `zyg_workflows.settings` is the generated registry of all `ZYG_*` flags.
`docs/configuration.md` in this repository documents the dashboard's own ones.

## 3. Ports

| Port | Service | Unit |
| --- | --- | --- |
| 5000 | Flask dashboard GUI (all `bp_*` blueprints) | `crewai-gui.service` |
| 8899 | Kanban board + inspection API | `kanban-server.service` |
| 7000 | Hub web server | `zyg-hub.service` (supervises 7000/7001/7777) |
| 7100 | Session Tree board | `session-tree.service` |
| 8188 | ComfyUI generation backend | `comfyui.service` |
| 8750 | Nomologin persona board (loopback only) | `nomologin.service` |
| 5300 / 5301 | Medusa GUI / Medusa presets | `medusa.service`, `medusa-presets.service` |

`crewai_web_gui` and `kanban_server` currently bind `0.0.0.0`. Put them behind the
nginx front door or a firewall before exposing the machine; the loopback-only
internal APIs enforce their own `remote_addr` checks.

## 4. systemd

`systemd/user/` are **user** units — they use `%h`, which only resolves to the real
home directory for `systemctl --user`. `systemd/system/` holds the one unit that is
genuinely machine-wide (`zygomatic-health.service`, a oneshot probe in
`/usr/local/bin`).

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/user/* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now crewai-gui.service kanban-server.service zyg-hub.service
systemctl --user enable --now zyg-sysusage.service session-tree.service
systemctl --user enable --now zyg-quota-meter.timer zyg-qc-trends.timer zyg-preempt-testcard.timer
loginctl enable-linger "$USER"      # so the units survive logout
```

`zyg-certbot-renew`, `zyg-cpu-cap` and `zyg-postgres` drive host-local things that
this repository does not ship (a certbot venv, `~/bin/zyg_cpu_cap.sh`, a hand-made
`~/pg16` install); enable them only if those exist.

`medusa.service`, `medusa-presets.service` and `nomologin.service` start code that
lives in **zygomatic-zero-public** (`zyg_zero.medusa`, `zyg_zero.nomologin_board`).
They are kept here because the hub launcher restarts them; they belong in that
repository's `deploy/systemd/` once it has one.

## 5. Containers

The build context is the **repository root**, not this directory, because the image
installs the package from `pyproject.toml` (`COPY . /app` + `pip install -e .`).
There is no `requirements/` directory: dependencies come from the pyproject, and
torch is installed first from the matching PyTorch index (cu128 or cpu).

```bash
docker compose -f deploy/docker-compose.yml up -d           # GPU
docker compose -f deploy/docker-compose.cpu.yml up -d       # CPU, no rendering
docker compose -f deploy/docker-compose.yml logs -f zyg
```

Compose reads two variables of its own: `ZYG_ENV_FILE` (default `../.env`) and
`ZYG_MODELS_ROOT` (the host directory bind-mounted read-only at `/models`).
Ollama and Redis have no `ports:` block — they are reachable only on the internal
Docker network.

## 6. nginx

`nginx/studio.zygomaticszero.com.conf` is the TLS front door for the :8899 board
(`inspection.html` plus the voice bridge). Copy it to
`/etc/nginx/sites-available/`, symlink it into `sites-enabled/`, and make sure
`/etc/nginx/conf.d/upgrade_map.conf` defines `$connection_upgrade`.

nginx cannot expand variables in `ssl_certificate`, so those two lines name
certbot's default `/etc/letsencrypt` paths; edit them if the certificate lives in
the renewal tree `zyg-certbot-renew.service` maintains. `proxy_buffering off` is
load-bearing: the voice bridge streams Server-Sent Events.

## 7. Health checks

```bash
curl -sf http://127.0.0.1:5000/ -o /dev/null && echo dashboard ok
curl -sf http://127.0.0.1:8899/ -o /dev/null && echo kanban ok
systemctl --user status crewai-gui.service
journalctl --user -u crewai-gui.service -f
```

| Problem | Check |
| --- | --- |
| Dashboard exits immediately | `FLASK_SECRET_KEY` missing from the env file — the app raises `RuntimeError` at import. |
| `ModuleNotFoundError: zyg_workflows` | workflows not installed in the venv the unit uses (`%h/repos/.venv`). |
| Rendering routes fail | No CUDA device, or `ZYG_MODELS_ROOT` points nowhere. `nvidia-smi` first. |
| Hub cards point at the wrong host | `ZYG_LAN_HOST` is still the default `127.0.0.1`. |
