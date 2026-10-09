<!-- SPDX-FileCopyrightText: 2026 Zygomatic -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# zygomatic-zero-public

The outward-facing half of the Zygomatic content studio: the site strangers actually reach.
It takes a prompt from an invited visitor, puts it on a queue, lets the generation pipelines
in [`zygomatic-workflows`](#how-this-depends-on-zygomatic-workflows) do the work, and streams
the result back — plus three smaller services that share the same "reachable from as little
as possible" posture.

Python package: `zyg_zero` under `src/`. One Flask app (`zero_public_server`) and three
sidecars that are started separately.

Everything in here is public-facing or identity-bearing, so the whole repository is written
to one rule: **nothing names a machine, an address, a domain or a home directory.** Defaults
are loopback and a directory under `ZYG_DATA_ROOT`; a deployment names its own in the
environment. See [`docs/configuration.md`](docs/configuration.md).

## What is in it

### The public site — `zero_public_server`, port 5001

A standalone Flask app, deliberately separate from the dashboard. It owns no models and runs
no pipeline itself: it validates, queues, and relays.

- **Redis-backed job queue** (`zpub_store.py`, `zpub_worker.py`). Jobs survive a browser
  close, a refresh and a restart, because the queue is in redis, not in memory. Keys are
  `zpub:queue` (list), `zpub:running`, `zpub:job:<id>`, `zpub:sess:<session_id>` and
  `zpub:rate:<ip>`; job state goes `queued → running → done | failed` with a 48 h TTL.
- **One worker thread.** The GPU behind the pipelines fits one job at a time, so the queue is
  the honest place to say so rather than failing under load.
- **Per-session job ids**, so two visitors never see each other's work.
- **SSE progress**, so a waiting page costs one connection instead of a poll loop.
- Route blueprints: `zpub_routes_public.py` (the gate, invites, uploads, the portfolio),
  `zpub_routes_cinema.py`, `zpub_routes_storyteller.py` (the relay to the dashboard),
  `zpub_routes_sports.py`, `zpub_routes_admin.py`.

### The invite gate and the fingerprint gate

Two different doors, on purpose — they protect different things and must not share a key.

**The invite gate** is the front door. `GET /` anonymously renders a locked page and answers
**403**, not a redirect: there is no "public mode" to fall back to. Access comes from a
capability URL, `/u/<token>`, handed out one at a time; visiting it stores the token in the
session, so later page loads stay open without the token appearing in the address bar again.
Each invite carries a label and a `max_requests` budget, and expires or is revoked from the
admin API — an expired or revoked token falls through to a **410 Gone** card rather than
silently behaving like a stranger. `/Portfolio` (and `/portfolio`) is a vanity alias for one
long-lived invite, so the URL on a job application stays memorable; it renders the invite
page **in place** rather than redirecting, so the raw token is never shown.

**The fingerprint gate** is a second, independent door on the gate page itself: a fingerprint
hotspot opens a password prompt, and a correct password sets `session['cinema_ok']` and
*nothing else*. It is deliberately **not** the admin flag — someone through the fingerprint
gate can watch the cinema and cannot touch the pipeline, the invite system or the admin API.
Because the password is short and the site is reachable from the internet,
`/api/cinema/unlock` is both rate-limited and carries its own per-IP lockout with exponential
backoff.

**Rate limiting** (`zpub_gate.py`) keys on `remote_addr|edge_ip`. The peer address always
stays in the key, and only `CF-Connecting-IP` is trusted on top of it — never
`X-Forwarded-For`, which a client can append to and would hand an attacker an unlimited
supply of fresh buckets. This exists because measurement forced it: with the site behind a
tunnel, 18,706 of 18,826 IP-bearing log events read `127.0.0.1`, collapsing every per-IP
limit into one global bucket.

### Zero Cinema

A private media library behind the fingerprint gate (`zpub_cinema.py`,
`zpub_routes_cinema.py`). It scans folders for films and series, probes them with `ffprobe`,
builds thumbnails, finds subtitles (external files and embedded streams) and decides per
title whether it can be served byte-for-byte or has to be transcoded on the fly. The index is
a plain JSON file under the runtime data root — inspectable, restart-proof, and no second
datastore. Nothing is probed twice: an entry is re-probed only when its `(size, mtime)` moves.

### Nomologin — persona browser isolation, loopback only

`nomologin*.py` plus the `nomologin_node/` sidecar. A *persona* is one brand whose social
accounts all live inside a single Chrome profile that no other persona shares, reaching the
network through its own proxy shim on its own loopback port.

The design in one line: **it never logs in.** You sign into each platform by hand, once,
inside the persona's profile, and the cookie jar keeps that session for months. Scripted
logins are what trigger 2FA challenges, captchas and "suspicious login" mail.

Isolation rests on a separate `--user-data-dir` per persona (not Chrome's profile switcher,
which shares a browser process and the sign-in surface), `--password-store=basic` (the
default keyring is shared by every profile at the OS level), seeded prefs that switch off
Chrome sign-in, sync and password-leak detection, and a `--proxy-server` plus
`--webrtc-ip-handling-policy=disable_non_proxied_udp`. It **fails closed**: a persona with a
proxy configured launches only after its shim is up *and* an egress probe has returned an
address that is not this machine's. If the proxy is down, Chrome does not open at all.

**Loopback-only by design, and that is a security property, not an oversight.** The board
(`nomologin_board.py`, port 8750) can launch browsers holding live sessions for every account
you own, and it prints 2FA codes. The rest of the hub listens on `0.0.0.0`; this one must
not. "Localhost only" is not by itself a defence against a web page the operator happens to
be visiting, so three further guards apply:

- **Host header pinning** — a page on the internet can point its own name at `127.0.0.1` (DNS
  rebinding) and reach this port. Requests whose `Host` is not `localhost:8750` are refused.
- **`Sec-Fetch-Site`** — browsers label cross-site requests themselves and page scripts cannot
  forge the header. Anything not `same-origin` or `none` is refused. The one exception is a
  top-level document navigation, which is how the hub card opens the board; its response is
  unreadable to the page that started it.
- **A per-boot token**, embedded in the page and required on every mutating call. A
  cross-origin script cannot read the page to learn it.

Reach it from another machine with an SSH tunnel — `ssh -L 8750:127.0.0.1:8750 <user>@<host>`
— not by binding it wider.

### Medusa — persona chat and preset submitter

Two small Flask services under `src/zyg_zero/medusa/`, both LAN-bound and both behind
`medusa_ipgate.py`:

| service | port | what it is |
| --- | --- | --- |
| `medusa_server.py` | 5300 | the 8-tab GUI: training imports, resources, generation, and **Vicky**, the chat assistant |
| `medusa_presets.py` | 5301 | the same guarded entry, fed from saved preset files instead of a live form |

**Vicky** (`medusa_vicky.py`) is a Claude Code CLI subprocess spawned fresh per turn and
resumed by session id. Her system prompt is built per request from `VICKY_RULES.md` in that
folder and nothing else; `--setting-sources project` means she loads only that folder's
`.claude/settings.json` and never the operator's own. She is fenced to that directory tree by
those permission rules plus a pinned `cwd`. **Known, accepted gap:** `Read`/`Write`/`Edit`/
`Glob`/`Grep` take a path the rules match against and are genuinely directory-scoped, but
`Bash` is not — Claude Code has no "this shell command may only touch this directory" rule —
and it is allowed broadly because Vicky cannot do her job without running scripts and tests.
Narrow it in `VICKY_RULES.md`; do not assume it is already narrow.

Both Medusa services submit through the *same* guarded crews endpoint
(`POST $MEDUSA_CREWS_API/api/medusa/generate`), so the server-side guardrails apply either
way: adults only, a wardrobe restriction, free-text prompts sanitised, and an operator
approval queue that parks every request as `pending` until it is allowed or declined.

**Lockout safety.** `127.0.0.1/32` and `::1/128` are always allowed by `medusa_ipgate.py` and
cannot be configured away, so a malformed `ZYG_LAN_ALLOWLIST` can never lock the operator out
permanently. Note that an allowlist is reachability reduction, **not** authentication:
anything that can present an allowed source address is inside.

## Ports

| port | service | binds to | default reachability |
| --- | --- | --- | --- |
| 5001 | `zero_public_server` — the public site | `$ZYG_BIND_HOST` (`127.0.0.1`) | loopback; the public internet through the tunnel or the nginx front door |
| 5300 | `medusa/medusa_server.py` — Medusa GUI + Vicky | `$ZYG_BIND_HOST` | loopback, plus whatever `ZYG_LAN_ALLOWLIST` adds |
| 5301 | `medusa/medusa_presets.py` — preset submitter | `$ZYG_BIND_HOST` | same |
| 8750 | `nomologin_board.py` — persona board | `127.0.0.1`, hard-coded | loopback only, never configurable |

Two ports this repository *talks to* but does not serve: **5000**, the dashboard main app
(`ZERO_MAIN_APP_URL`), and **6379**, redis (`REDIS_URL`).

## Configuration

Every deployment-specific value is an environment variable with a safe local default. The
full table — reachability, filesystem roots, Medusa character origin, and the two files that
are deliberately *not* read from the environment — is in
[`docs/configuration.md`](docs/configuration.md). The short version:

| variable | default | why you would set it |
| --- | --- | --- |
| `FLASK_SECRET_KEY` | a fresh random key per start | **set it.** Without it, every restart logs every visitor out. |
| `ZERO_PUBLIC_PORT` | `5001` | listening port of the public site |
| `ZYG_BIND_HOST` | `127.0.0.1` | the interface the services bind; `0.0.0.0` only together with an allowlist |
| `ZYG_LAN_HOST` | `127.0.0.1` | the host the services print and advertise |
| `ZYG_LAN_ALLOWLIST` | *(empty)* | IPs and CIDRs allowed to reach the Medusa services on top of loopback |
| `ZERO_MAIN_APP_URL` | `http://localhost:5000` | the dashboard this server relays to |
| `ZERO_PUBLIC_URL` | *(empty)* | base URL for `/u/<token>` invite links, when the public hostname differs from the `Host` requests arrive with |
| `ZERO_PUBLIC_TOKEN` | *(empty)* | shared secret for internal calls to the main app; unset means the main app rejects them |
| `REDIS_URL` | `redis://localhost:6379/0` | the job queue |

Put them in one `0600` file outside the repository — `~/.config/zygomatic/env` is what the
systemd unit reads. Never commit one; `.env*` is in `.gitignore` for a reason.

## How this depends on zygomatic-workflows

`zyg_zero` imports [`zygomatic-workflows`](../zygomatic-workflows) (package `zyg_workflows`)
and **never the reverse**. Workflows is the base library: `zyg_workflows.paths` owns every
filesystem root, and `zyg_zero/settings.py` adds only the handful of values the public site,
nomologin and Medusa need on top of it.

The rule is enforced, not merely documented — `import-linter` runs in CI and in
`scripts/scan.sh`: workflows must never import `zyg_dashboard`, `zyg_zero` or `zyg_nexus`,
and this repository must never import `zyg_dashboard`. Where the public site needs something
the dashboard owns it goes over HTTP to `ZERO_MAIN_APP_URL`, which is why
`zpub_routes_storyteller.py` answers `503 Main app unreachable` instead of importing it.

## Install

Two checkouts side by side, one virtualenv:

```bash
git clone <workflows-url> ~/repos/zygomatic-workflows
git clone <this-url>      ~/repos/zygomatic-zero-public
python3.12 -m venv ~/repos/.venv
~/repos/.venv/bin/pip install -e ~/repos/zygomatic-workflows
~/repos/.venv/bin/pip install -e '~/repos/zygomatic-zero-public[dev]'
```

Python 3.12 is the floor, imposed by workflows' own dependency set. Workflows goes first,
because this package imports it.

`requirements-lock.txt` is the fully pinned, audited resolution of `pyproject.toml` — use it
for a reproducible deployment (`pip install -r requirements-lock.txt`), not for development.
Regenerate it with the `uv pip compile` command written at the top of `pyproject.toml`, and
keep it clean under `pip-audit -r requirements-lock.txt --no-deps --disable-pip`.

The nomologin sidecar has its own Node dependencies, not vendored here:

```bash
cd src/zyg_zero/nomologin_node && npm ci
```

Non-Python things the services shell out to: **redis** (the queue) and **ffmpeg/ffprobe**
(cinema probing and transcoding). Nomologin additionally needs a Chrome or Chromium binary.

## Run

```bash
~/repos/.venv/bin/python -m zyg_zero.zero_public_server     # the public site, :5001
~/repos/.venv/bin/python -m zyg_zero.nomologin_board        # the persona board, :8750

# Medusa, :5300 and :5301 — run as scripts, from their own directory (see the note below)
cd src/zyg_zero/medusa && ~/repos/.venv/bin/python medusa_server.py
cd src/zyg_zero/medusa && ~/repos/.venv/bin/python medusa_presets.py
```

**Known defect, Medusa only.** `medusa_server.py`, `medusa_presets.py` and `medusa_vicky.py`
still reach their siblings with bare top-level imports (`import medusa_ipgate`,
`medusa_resources`, `medusa_vicky`, `medusa_victor`) left over from before these modules were
a package. Those names resolve only when the interpreter's first `sys.path` entry is the
`medusa/` directory itself, which is what running them as scripts from that directory gives
you — so `python -m zyg_zero.medusa.medusa_server` raises
`ModuleNotFoundError: No module named 'medusa_ipgate'`. Nothing else in `zyg_zero` is
affected: the public site and the board are plain `-m` targets. The fix is to rewrite those
five imports as `from zyg_zero.medusa import …`.

For a real deployment use `deploy/`:

- `deploy/systemd/zero-public.service` — a systemd **user** unit for the public site. `%h` is
  only meaningful in the user manager, which is what lets the unit name no home directory.
  Install it with `cp deploy/systemd/zero-public.service ~/.config/systemd/user/` followed by
  `systemctl --user enable --now zero-public.service`, and run `loginctl enable-linger $USER`
  once so it survives logout.
- `deploy/nginx/zygomaticszero` — the port-80 front door, proxying to loopback `:5001`. It
  sets `X-Real-IP`, which the invite gate, the Medusa IP gate and the rate limiter all key
  on; without it every visitor would arrive as `127.0.0.1`.

## Tests and the publishability gate

```bash
bash scripts/scan.sh          # the whole gate; exit 0 means clean
```

`scan.sh` runs what CI runs: `ruff check`, `ruff format --check`, `bandit -ll`, `gitleaks`
over the tree *and* the history, `reuse lint`, the import-layering contract, `compileall`,
`pytest --collect-only`, and a grep for personal data (home directories, private addresses,
personal mail). It needs the tool venv; point `ZYG_TOOLS` at it if it is not `~/repos/.tools`.

```bash
pytest -m 'not service'       # the CPU subset — no external process needed
pytest                        # everything, including routes that need a live service
```

`tests/api/test_zero_public.py` is a route sweep rather than a unit suite: it imports the app
with `Thread.start` neutered (so the real job worker never runs beside the live server),
enumerates every rule, and asserts that no anonymous request reaches a handler that should
have refused it. Tests marked `service` need something outside this repository — the
dashboard main app on :5000, or the separate sports-video checkout — and are excluded from
the CPU subset. One test is a **strict `xfail`**: `/api/sports-video/trigger` really is
ungated and really does write before it validates. That is a known open finding kept
deliberately visible; the day a gate is added the xfail turns into an XPASS failure and
forces the marker to come off.

## Licence

AGPL-3.0-or-later. See [`LICENSE`](LICENSE), and [`REUSE.toml`](REUSE.toml) for the
machine-readable declaration — the repository is [REUSE](https://reuse.software/)-compliant
and `reuse lint` is part of the gate.

Contributing: [`CONTRIBUTING.md`](CONTRIBUTING.md). Reporting a vulnerability:
[`SECURITY.md`](SECURITY.md).
