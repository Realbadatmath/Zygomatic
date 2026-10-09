<!--
SPDX-FileCopyrightText: 2026 Zygomatic

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# studio_ext — the studio extension seam (2026-09-18)

- Every `studio_ext/*.js` is concatenated in name order and served as
  `GET /studio_ext/bundle.js`, behind the preamble
  `window.SX = window.SX || {ready:[]};`. Each file is wrapped in try/catch, so a
  broken extension logs and the rest still runs. No caching — drop a file, reload.
- Files whose name starts with `_` (like this one) are NOT bundled.
- inspection.html loads the bundle AFTER its own main `<script>` block, so every
  page function and global (CS_TOOLS, CST_ACT, CS3, CT, CRST3, MVST, mo*, cs3d*,
  ct*, ...) already exists when your file runs. Wrap a page function by
  reassigning its global name: `var _o = crst3dLoad; crst3dLoad = function(s){...};`
- Page helpers available to you: `api(url)` (GET → JSON), `withScope(url)`, `esc(s)`.
- Server side: `studio_ext_server/<mod>.py` exports
  `ROUTES = {op: fn(payload: dict, method: str) -> dict | (bytes, mime, filename)}`,
  answered at `/inspect/api/studio/<mod>/<op>` for GET (query string → payload) and
  POST (JSON body, query merged). Modules hot-reload on mtime change — no restart.
  A dict with `error` and no `ok` is sent with HTTP status `payload.get('code', 400)`.
  `GET /inspect/api/studio/` lists `{mod: [ops]}`.
