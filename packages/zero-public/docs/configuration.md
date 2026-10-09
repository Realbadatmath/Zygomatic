<!--
SPDX-FileCopyrightText: 2026 Zygomatic

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Configuration

Nothing in this repository names a machine, a network address, a domain or a home
directory. Every deployment-specific value is read from the environment, and the default
is always the safe local one: loopback for anything reachable, and a directory under
`ZYG_DATA_ROOT` for anything on disk. An unconfigured checkout therefore starts, serves
itself on loopback, and is reachable from nowhere else.

Filesystem roots shared with the pipelines live in `zyg_workflows.paths`; the values this
repository adds on top live in `zyg_zero/settings.py`.

## Reachability

| Variable | Default | What it does |
| --- | --- | --- |
| `ZYG_LAN_ALLOWLIST` | *(empty)* | Comma- or semicolon-separated IPs and CIDRs allowed to reach the LAN-bound Medusa apps (`:5300`, `:5301`), **on top of** loopback. Empty means loopback only. See the lockout note below. |
| `ZYG_LAN_HOST` | `127.0.0.1` | The host the services print and advertise in their start-up banners, and the mDNS fallback address of the public server. Set it to the box's LAN name or address to advertise a URL other machines can use. |
| `MEDUSA_ALLOWED_IPS` | `$ZYG_LAN_ALLOWLIST` | Legacy name, still honoured so existing unit files keep working. When set it replaces `ZYG_LAN_ALLOWLIST` entirely. |
| `ZERO_PUBLIC_URL` | *(empty)* | Base URL for user-facing links (`/u/<token>` invites) and the URL written to the Cloudflare tunnel sidecar. Needed only when the public hostname differs from the `Host` header requests arrive with — a tunnel. When unset, each link is built from the address the request actually came in on, falling back to `http://localhost:$ZERO_PUBLIC_PORT`. |
| `ZERO_MAIN_APP_URL` | `http://localhost:5000` | The internal dashboard this server proxies to. |
| `ZERO_PUBLIC_PORT` | `5001` | Listening port of the public site. |
| `MEDUSA_CREWS_API` | `http://127.0.0.1:5000` | The crews API the Medusa apps forward generation requests to. |

**Lockout safety.** `127.0.0.1/32` and `::1/128` are always allowed by
`zyg_zero/medusa/medusa_ipgate.py` and cannot be configured away, so a malformed allowlist
can never lock the operator out permanently: the app stays reachable from the box itself,
or through `ssh -L 5300:127.0.0.1:5300 <user>@<host>`.

**Both addresses, not one.** A LAN deployment usually needs *two* entries: the operator's
workstation, and the box's own LAN address. `ip route get <own LAN address>` resolves to
`local … dev lo`, so requests to the URL the entry points advertise originate from that
address — omitting it denies the machine access to itself.

This is reachability reduction, not authentication. Anything that can present an allowed
source address is inside.

## Filesystem roots

| Variable | Default | What it holds |
| --- | --- | --- |
| `ZYG_MEDUSA_IMPORT_DIR` | `$ZYG_DATA_ROOT/medusa_import` | Imported reference pictures: one subdirectory per character. The Training tab's folder importer and the Resources tab both read this root, which is why they agree without a copy step. |
| `ZYG_MEDUSA_RESOURCES_ROOT` | `$ZYG_MEDUSA_IMPORT_DIR` | Override for the Resources tab alone, when its downloads should land somewhere other than the Training import root. |
| `ZYG_PORTFOLIO_DIR` | `$ZYG_DATA_ROOT/portfolio` | Portfolio media served on the public pages: `slideshow/` for the frame deck, `showreel.mp4` for the video. |
| `ZPUB_PORTFOLIO_SLIDES` | `$ZYG_PORTFOLIO_DIR/slideshow` | Override for the slideshow frames alone. |
| `ZPUB_PORTFOLIO_VIDEO` | `$ZYG_PORTFOLIO_DIR/showreel.mp4` | Override for the showreel file alone. |
| `ZPUB_PORTFOLIO_SPEEDRUN` | `$ZYG_PORTFOLIO_DIR/speedrun.mp4` | Override for the three-minute speedrun cut of the portfolio film, streamed by `/portfolio-speedrun-stream` behind the same same-origin door as the full film. |
| `ZYG_SPORTS_VIDEO_DIR` | `$ZYG_DATA_ROOT/sports-video-pipeline` | Working directory of the sports-video pipeline: its `status.json` and its scripts. |
| `ZYG_MEDUSA_AGE_GATE` | `$ZYG_CREWS_ROOT/medusa_age_gate.py` | The crews age gate, imported by path. Optional: a missing file degrades to the built-in screen rather than breaking a turn. |
| `ZYG_MEDUSA_STILLS_DIR` | `$ZYG_OUTPUT_ROOT/video_studio/_stills` | Where the still service writes rendered pictures, read to recover pictures whose chat was deleted. |
| `ZYG_MEDUSA_IMAGE_ROOTS` | *(empty)* | Colon-separated extra roots a picture the assistant rendered may be served from, on top of `$ZYG_OUTPUT_ROOT`, the storyteller character sheets, and Medusa's own directory. |

Inherited from `zyg_workflows.paths` and documented there: `ZYG_HOME`, `ZYG_CREWS_ROOT`,
`ZYG_DATA_ROOT`, `ZYG_OUTPUT_ROOT`, `ZYG_LORA_DATASETS`, `ZYG_LORA_OUTPUTS`,
`ZYG_MODELS_DIR`, `ZYG_FLUX_ROOT`.

## Medusa character origin

`zyg_workflows.medusa_chars` answers whether a storyteller character came from Medusa —
the question the public library, the public character list and the dashboard's own views
all have to ask before showing anything. It reads two independent signals:

| Variable | Default | What it holds |
| --- | --- | --- |
| `ZYG_STORYTELLER_CHARS` | `$ZYG_LORA_DATASETS/storyteller_chars` | One directory per character; a `.medusa_origin` file inside one marks it. |
| `ZYG_MEDUSA_RUNTIME_DIR` | `$ZYG_DATA_ROOT/runtime` | Per-character `medusa_<id>_state.json` run state, the second signal. |
| `ZPUB_PORTFOLIO_TOKEN` | empty (no vanity invite) | The invite token the `/Portfolio` vanity page renders in place. Empty means the page shows the expired-invite card. Set it to a long-lived invite from the invite store; never commit it. |

Both detectors are fail-safe towards *not* medusa, so a misconfigured root can never
reclassify adult content as a stock character — but it can let one through a filter. Point
these at the same directories the pipeline writes to.

## Not read from the environment

Two files under `src/zyg_zero/medusa/config/` carry paths that are not expanded at
runtime, because the tools that read them do no expansion of their own. Both are written
home-relative (`~/…`) and must be pointed at the real store by hand:

- `model_params.json` — `checkpoint_path`, `lora_dir`. Mirrors `ZYG_FLUX_ROOT` and
  `ZYG_LORA_OUTPUTS`.
- `Vicky.Modelfile` — the `FROM` line. Ollama does not expand `~`; the build command in
  the file's own header shows the substitution.
