<!--
SPDX-FileCopyrightText: 2026 Zygomatic

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# nomologin driver sidecar

A small Node sidecar (`driver.js`) that attaches `puppeteer-core` to the Chrome a Nomologin
persona is already signed in to. `zyg_zero/nomologin_browser.py` spawns it; nothing else
calls it directly.

`node_modules/` is **not** in the repository. Install the dependencies once, from this
directory, before the first run:

```bash
npm ci
```

`npm ci`, not `npm install`: it installs exactly what `package-lock.json` pins and fails
instead of silently resolving a newer tree. Node >= 20 is required (`engines` in
`package.json`). `puppeteer-core` ships no browser of its own by design — it drives the
Chrome the persona already uses, which is the whole point of the sidecar.
