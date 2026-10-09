<!--
SPDX-FileCopyrightText: 2026 Zygomatic

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# zygomatic-creator-nexus

The **Creator Nexus** is the channel and creator planning board for the Zygomatic
content pipeline: one place to keep every channel the operation publishes to, the
credentials and policy rules each one needs, the upload queue feeding them, and the
performance numbers coming back.

Four tabs, one page:

- **Channels** — the registry. Per channel: region, platforms (YouTube, TikTok,
  Kick, X, Instagram, Facebook, VK, Bilibili, Weibo and some twenty more), a
  per-channel vault of handles, URLs and API credentials, and the policy rules that
  decide what may be published where.
- **Upload Pipeline** — what is cut, what is rendered, what is queued, what aired.
- **Marketing Pipeline** — a kanban of publish cards with three daily batch slots
  (uploads go out an hour before the 08:00 / 14:00 / 20:00 air slots), plus the log.
- **Metrics** — channel overview, video performance, audience and demographics.

## The two halves

The Creator Nexus is a **static frontend** (`site/`) plus **one optional Flask
blueprint** (`src/zyg_nexus/bp_creator_nexus.py`).

**`site/`** is plain HTML, CSS and one JavaScript file — no build step, no bundler,
no framework. It keeps its whole state in browser `localStorage`. Any static server
will do; the shipped unit uses `python -m http.server` on port 8090.

**`src/zyg_nexus/bp_creator_nexus.py`** exists because localStorage is not durable:
a single bad page load once overwrote the channel registry with an empty list. The
blueprint gives the browser store a server-side mirror. It serves three routes:

| Route | Does |
| --- | --- |
| `GET/POST /api/creator-nexus/state` | read back / autosave the owned localStorage keys |
| `GET /api/creator-nexus/snapshots` | list the rotating history (60 kept) |
| `GET /api/creator-nexus/snapshots/<name>` | fetch one snapshot verbatim to restore |

Two guarantees are deliberate: a POST that would replace a non-empty channel list
with an empty one is **refused** (409, unless `force=true`), and every accepted save
also lands in a timestamped snapshot that is never overwritten.

The blueprint does **not** run a server of its own. It is a `flask.Blueprint` that
the Zygomatic dashboard registers on its app (port 5000). Nothing in this repository
imports the dashboard: shared state is reached only through `zyg_workflows.runtime`
— `runtime.runtime_dir()` for the data directory, and `runtime.limiter` looked up at
call time, which is `None` outside the GUI and makes the rate-limit decorator a
no-op. That is what lets the blueprint be registered on a bare Flask app in a test.

`site/app.js` therefore assumes the dashboard runs on whatever host served the page
(`API_BASE`, derived from `location`) — no address is hardcoded. Set
`window.ZYG_API_BASE` before `app.js` loads when the two live on different hosts.

## Running it

The site on its own — this is all the planning board needs:

```sh
python -m http.server 8090 --bind 127.0.0.1 --directory site
# → http://127.0.0.1:8090
```

As a user service (`deploy/systemd/creator-nexus.service`, templated on `%h`, so no
absolute path is baked in):

```sh
cp deploy/systemd/creator-nexus.service ~/.config/systemd/user/
systemctl --user enable --now creator-nexus
```

The blueprint — needed for durable state and for the marketing and metrics tabs — is
loaded by the dashboard; it is not started from here:

```python
from zyg_nexus.bp_creator_nexus import bp as creator_nexus_bp

app.register_blueprint(creator_nexus_bp)
```

Cross-origin access (site on 8090, API on 5000) is **off by default**: no CORS header
is sent unless the request's origin is on the `ZYG_CORS_ORIGINS` allowlist.

```sh
export ZYG_CORS_ORIGINS='http://127.0.0.1:8090'
```

Development:

```sh
pip install -e '.[dev]'
pytest                 # tests/
bash scripts/scan.sh   # the gate: ruff, bandit, gitleaks, reuse, import layering
```

## State lives outside the repository

Everything the blueprint writes goes under `$ZYG_DATA_ROOT/runtime/creator_nexus/`
— `state_current.json` plus `snapshots/state_<timestamp>.json`. Never inside this
checkout.

This matters: the channel vault holds passwords, API keys, OAuth client secrets and
access tokens **in cleartext**, because that is how the browser stores them. The
mirror must not widen who can read them, so the directory and every file are created
owner-only (`0700` / `0600`) and writes are atomic. Back that directory up, and treat
it exactly like a password store. `ZYG_DATA_ROOT` is resolved by
`zyg_workflows.paths`; set it to move the whole store elsewhere.

## Licence

AGPL-3.0-or-later — see [LICENSE](LICENSE). The repository is
[REUSE](https://reuse.software/)-compliant: every file carries its own SPDX headers.
Security reports: [SECURITY.md](SECURITY.md). Contributing:
[CONTRIBUTING.md](CONTRIBUTING.md).
