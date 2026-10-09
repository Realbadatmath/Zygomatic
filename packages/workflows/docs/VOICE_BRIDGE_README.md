# Voice bridge — speak to the studios

The operator speaks into the browser microphone; the GUI on `:8899`
(`inspection.html`) executes the command visibly — navigation, tool clicks, knob
moves, with a ghost cursor — and answers in a Voice Studio voice.

Everything below is measured on this box on 2026-09-15 unless it says otherwise.
cwd for every command: `/home/zygomatic/Zygomatic Full/agents/crews`.

---

## 1. Architecture

```
  browser mic (MediaRecorder, audio/webm opus)
        │  POST /inspect/api/voice/utterance {driver, audio_b64, mime, view, t_start}
        ▼
  voice_bridge._utterance
        │
        ├─► voice_stt.transcribe_utterance(audio, mime)      → text
        │       ffmpeg → wav 16 kHz mono → zyg_whisper (large-v3 on cuda)
        │
        ├─► voice_ext/speaker.verify  (ONLY when somebody is enrolled)
        │       → {name, score, accepted}; nobody enrolled ⇒ gate not armed ⇒ None
        │
        ├─► voice_brain.plan(text, {view, registry})
        │       builtin → grammar → arch → llm      → {actions, say, tier}
        │
        ├─► SSE push to the driver tab   event: action / event: say
        │
        └─► ledger.jsonl line {kind:'utterance', text, speaker, tier, actions, acks:[]}

  driver tab (voice_ext/00_core.js)
        │  runs VB.actions[name].run(args) — the studio's OWN handler
        │  ghost cursor: VB.cursor.moveTo/click/highlight/caption
        ▼
  POST /inspect/api/voice/ack {id, ok, error, detail, view}
        └─► appended to the utterance's `acks` in memory and on disk

  reply:  say event carries wav = /inspect/api/voice/ext/tts/say?text=…
          the page fetches that URL when it wants to HEAR it.
          voice_ext/tts.py renders through IndexTTS-2 and caches by
          (voice_id, engine, params, text) under data/runtime/voice_bridge/say/.
```

Two things this design deliberately does **not** do:

- `voice_bridge` never synthesises audio. The `say` event carries a *URL*, so a
  tab that is muted costs nothing and the cache is shared by every tab.
- Actions are pushed over SSE **and** returned in the utterance response. The
  page must not run them twice — core de-duplicates on the action `id`.

---

## 2. The contract

Reproduced verbatim from the tree brief. Code against it; do not redesign it.

```
=== VOICE BRIDGE CONTRACT (identical in every brief of this tree; code against it, do not redesign it) ===
Goal of the tree: the operator speaks into the browser microphone; the GUI on :8899 (inspection.html, ONE 34.8k-line file,
served by kanban_server.py = stdlib ThreadingTCPServer + SimpleHTTPRequestHandler subclass `_Handler`, NOT Flask) executes his
commands visibly (navigation, tool clicks, knob moves, with a ghost cursor) and answers in a Voice Studio voice.
cwd for everything: /home/zygomatic/Zygomatic Full/agents/crews. Backups: copy any existing file you edit to <file>.bak-voice-20260915 BEFORE editing (skip if that .bak exists).
Never edit inspection.html unless your brief says so (exactly one task in the tree does). Never touch kanban_server.py unless
your brief says so (exactly one task does). Do not restart kanban-server (the last task does, gated on
GET http://127.0.0.1:8899/inspect/api/architecture/assistant/active -> running == 0). Standing rules: the arch assistant is
NEVER run on Opus; nothing auto-selects in Architecture Studio after an injection; digits not words in any subtitle text.

SERVER SEAM (task 3 builds it; everyone else codes to it):
- `voice_bridge.py` exports `handle_get(path, query) -> (dict, code)`, `handle_post(path, body) -> (dict, code)`,
  `handle_sse(handler, query)` (writes an SSE stream on handler.wfile) and `BODY_LIMIT = 4_000_000`.
  Mounted in kanban_server under `/inspect/api/voice/...` (NOTE `/voice/api/...` already belongs to Voice Studio; do not reuse it).
- Extension modules: `voice_ext/<name>.py` with `ROUTES = {'<op>': fn(payload: dict, method: str)}` reachable at
  `/inspect/api/voice/ext/<name>/<op>` (GET query merged into payload; POST JSON body = payload). fn returns a dict, or a
  tuple `(bytes, mime, filename)` which is sent as a download/blob. voice_bridge reloads a module whose file mtime moved
  (same pattern as `architecture_studio.ext_dispatch()`, grep it) so ext modules never need a restart.
- Client bundle: GET `/voice_ext/bundle.js` = concatenation of `voice_ext/*.js` sorted by name, each wrapped in try/catch,
  prefixed with `window.VB = window.VB || {actions:{}, aliases:{}, ready:[], views:{}};` — built exactly like
  `_serve_arch_ext_bundle` in kanban_server.py (~line 5478). The bundle is loaded by ONE `<script src="/voice_ext/bundle.js">`
  placed right after `<script src="/arch_ext/bundle.js"></script>` (inspection.html line 6911), i.e. BEFORE the studio script
  (6916..34826). Therefore a voice_ext/*.js file may only REGISTER at top level (functions, tables); anything that touches DOM or
  studio globals (goToView, vstSetRate, AR, ...) runs later inside `run()`/`el()` or a `VB.ready.push(fn)` callback
  (core calls `VB.ready` once on DOMContentLoaded).
- Runtime dirs: `data/runtime/voice_bridge/` (config.json, say/ cache, speakers/, ledger.jsonl). Create with os.makedirs(exist_ok=True).

CLIENT REGISTRY (every per-studio file registers into it; core executes it):
  VB.actions['<view>.<verb>'] = {
    view: '<view id as used by goToView>',           // 'videos','pictures','charstudio','creatures','movement','voices1','sfx','musicstudio','vfx','music','architecture','mesh','inspections','settings','home'
    label: 'human label',                              // shown in the panel + given to the language model
    aliases: ['spoken phrase', ...],                   // lower-case, what the operator would SAY (several per action)
    args: { value: 'number 0..1' } or null,           // optional named args with a one-line type/range description
    el: function(args){ return document.getElementById('...'); },   // the control the ghost cursor moves to (or null)
    run: function(args){ /* call the studio's OWN handler, e.g. vstSetRate('1.5'); never re-implement it */ },
    say: 'sentence the assistant speaks after success, digits allowed, <= 12 words'
  };
  Rules: `run` MUST call the existing handler the human click calls (find it in the onclick/onchange of the control or the
  JS function that the icon rail builds). Actions must be idempotent and must not open prompt()/confirm(). If a control does
  not exist yet (studio not entered), `run` first calls `goToView(view)` and waits for `el()` to appear (core provides
  `VB.waitFor(fn, ms)` returning a Promise). `run` may return a Promise. On failure throw an Error with a readable message.
  Names are stable identifiers: lower-case, dots, no spaces.
HELLO: on load core POSTs `/inspect/api/voice/hello` {driver, registry:[{name,view,label,aliases,args}...], view: current}.
SSE: GET `/inspect/api/voice/events?driver=<token>` sends `event: action` `data: {"id","name","args","say"}`,
  `event: say` `data: {"id","text","wav":"/inspect/api/voice/ext/tts/say?text=..."}`, `event: status` (free text) and a
  `: ping` comment every 15 s. Core executes an action, then POSTs `/inspect/api/voice/ack` {id, ok, error, detail, view}.
UTTERANCE: POST `/inspect/api/voice/utterance` {driver, audio_b64, mime:'audio/webm', view, t_start} ->
  {ok, text, speaker:{name, score, accepted}, tier:'grammar'|'llm'|'arch'|'none', actions:[...], say:{text, wav}}.
  Actions are ALSO pushed over SSE (the page must not run them twice: core de-duplicates on action id).
BRAIN: `voice_brain.plan(text, ctx) -> {'actions':[{'name','args'}], 'say': str, 'tier': str}`, ctx = {'view', 'registry'}.
Ghost cursor: `VB.cursor.moveTo(el)`, `.click(el)`, `.highlight(el, ms)`, `.caption(text)` (core+cursor tasks).
Driver: the ONE tab that executes actions holds a token in localStorage 'vb.driver' (panel toggle). Other tabs only watch.
=== END CONTRACT ===
```

---

## 3. File map

### Server

| File | Role |
|---|---|
| `voice_bridge.py` | The seam. `handle_get` / `handle_post` / `handle_sse` / `bundle_js()` / `BODY_LIMIT = 4_000_000`. Routes, driver table, SSE queues, ledger, ext dispatch with mtime reload. |
| `voice_brain.py` | `plan(text, ctx)` → `{actions, say, tier}`. Tier order: builtin → grammar → arch → llm. `OLLAMA_MODEL = 'qwen3.5:9b'` via `llm_audit.ollama_generate`; `MIN_FREE_VRAM_MB = 8*1024`. |
| `voice_stt.py` | `transcribe_utterance(bytes, mime)` → `{text, seconds, ms, device, model}`; ffmpeg → wav 16 kHz mono → `zyg_whisper`. `warm()` preloads. |
| `voice_ext/tts.py` | `ROUTES = {say, voices, config, prerender, cache}`. IndexTTS-2 / Chatterbox, say-cache keyed on (voice, engine, params, text). |
| `voice_ext/speaker.py` | `ROUTES = {enrol, verify, list, delete, config}`. Cosine on embeddings, default threshold 0.55. |
| `kanban_server.py` | Mount only: `_voice_bridge` (3908), `_voice_bridge_sse` (3946), `/voice_ext/bundle.js` (5572), POST hook (5435), GET hook (5577). |
| `inspection.html` | One `<script src="/voice_ext/bundle.js">` right after `/arch_ext/bundle.js` (line 6911), i.e. before the studio script. |

### Client — `voice_ext/*.js`, concatenated in name order by `bundle_js()`

Core: `00_core.js` (registry, hello, SSE, ack, `VB.waitFor`, `VB.ready`, driver
token), `01_cursor.js` (ghost cursor), `02_mic.js` (MediaRecorder + VAD),
`03_panel_extras.js` (panel, enrol, voice picker).

Per studio: `10_nav.js`, `20_videos.js`, `21_pictures.js`, `22_charstudio.js`,
`23_creatures.js`, `24_movement.js`, `25_voices.js`, `26_sfx.js`,
`27_musicstudio.js`, `28_vfx.js`, `29_melody.js`, `30_architecture.js`,
`31_mesh_lib_settings.js`.

### Tools, tests, runtime, docs

- `tools/vb_prerender.py` — warm the say-cache (`--list`, `--clear`, `--limit`).
- `tools/vb_stt_bench.py`, `tools/vb_speaker_bench.py` — latency/accuracy benches.
- `tests/test_voice_bridge.py`, `test_voice_brain.py`, `test_voice_stt.py`,
  `test_voice_tts.py`, `test_voice_speaker.py`, `test_voice_leg.py`.
- `tests/vb_core.test.js`, `tests/vb_mic_smoke.html`, `tests/vb_cursor_zoom.html`,
  `tests/vb_panel_extras_smoke.html`.
- `data/runtime/voice_bridge/` — `config.json`, `say/`, `speakers/`, `ledger.jsonl`.
- Sibling docs: `docs/voice_bridge_nginx.md` (TLS), `docs/voice_bridge_voice.md`
  (reply voice, cache), `docs/voice_bridge_speaker.md` (verification).

---

## 4. Operator's first-run checklist

1. **HTTPS.** `getUserMedia` is refused on a plain-http origin that is not
   `localhost`, so the microphone only works over TLS from another machine.
   Deploy the front door as `docs/voice_bridge_nginx.md` describes (§1 deploy and
   reload, §2 unattended renewal, §3 make the name resolve on the LAN), then open
   `https://studio.zygomaticszero.com`. Its "Mixed content" section (§ Mixed
   content) is the one to read if the page loads but the mic button stays dead.
2. **Become the driver.** Open the voice panel and turn the driver toggle on.
   That writes `localStorage['vb.driver']`; exactly one tab may hold it. Every
   other tab watches the stream and executes nothing. Confirm with
   `curl -s http://127.0.0.1:8899/inspect/api/voice/state` — your token should be
   listed with `connected: true` and a non-zero `actions` count.
3. **Pick the reply voice.** Panel → voice picker, or
   `POST /inspect/api/voice/ext/tts/config {voice_id: '<id>'}`. Default on this
   box is `abel` with `engine: auto` resolving to `indextts2`. Details and the
   full switch procedure: `docs/voice_bridge_voice.md` §1.
4. **Pre-render the cache** after any voice change, or the first sentence of
   every reply costs a full synthesis:
   `tools/vb_prerender.py --clear` (new voice) or `tools/vb_prerender.py`
   (fill gaps only). The cache currently holds 309 clips / 46.2 MB.
5. **Enrol your voice — last, and optional.** Panel → enrol, or
   `POST /inspect/api/voice/ext/speaker/enrol`. Until somebody is enrolled the
   gate is **not armed** and the bridge obeys whoever is at the microphone; that
   is deliberate, since a bridge that refused every command until an enrolment
   existed could never be enrolled by voice. Thresholds and the reasoning behind
   0.55: `docs/voice_bridge_speaker.md`.

---

## 5. Measured latencies

Measured 2026-09-15 on this box (RTX, 46.3 GB VRAM free, GPU 9 % busy) against
the seam mounted on a spare port. Command audio: the sentence "navigate to video
studio" rendered by the assistant's own TTS — 3.19 s of `audio/webm` opus @32k,
13 792 bytes.

| Leg | Measurement |
|---|---|
| SSE delivery (POST `action` → `data:` line read by the client) | **2.35 ms** |
| STT, first call (model load + transcribe 3.183 s) | **6307 ms** (`device: cuda`, `model: large-v3`) |
| STT, warm (same audio, model resident) | **222 ms** (whole POST round-trip 224 ms) |
| TTS `say`, first call (engine load + synthesis, 4 words) | **16006 ms** |
| TTS `say`, engine warm, novel text (9 words → 10.9 s audio) | **19274 ms** |
| TTS `say`, cache hit | **23–43 ms** |

Read that table as: **the steady-state spoken command costs ~0.25 s** (222 ms STT
+ 2 ms SSE + the action's own work) **provided the reply sentence is in the
say-cache**. Everything above a quarter of a second in the first-call column is a
model being loaded once. An un-cached reply costs ~2 s of synthesis per second of
speech, which is why step 4 of the checklist is not optional.

Full end-to-end evidence (`hello` → `utterance` → `ack` → `ledger`):

```json
{
  "ok": true,
  "text": "Navigate to Video Studio.",
  "speaker": null,
  "tier": "grammar",
  "actions": [ { "id": "c7a404f92c69", "name": "nav.videos", "args": {}, "say": "" } ],
  "say": {
    "id": "d402bc3d3131",
    "text": "Opening Video Studio",
    "wav": "/inspect/api/voice/ext/tts/say?text=Opening%20Video%20Studio"
  },
  "stt": { "seconds": 3.183, "ms": 6307, "device": "cuda", "model": "large-v3" }
}
```

`speaker: null` with `ok: true` is the un-armed gate of checklist step 5:
`speaker/list` returned `{"speakers": [], "count": 0}` while `speaker/config`
reported `speaker_gate: true, speaker_threshold: 0.55` — the gate is configured
on but has nobody to compare against, so the utterance is accepted.

---

## 6. Known limits

- **One driver tab.** The token in `localStorage['vb.driver']` elects a single
  executing tab. A second SSE connection for the same token takes the stream over
  (`d['sub'] != mine` retires the older loop); the queue survives, so an action
  pushed during a reload is still delivered, but two tabs fighting over one token
  will hand the stream back and forth.
- **Actions are serialised.** Core runs one action at a time and acks before
  taking the next. A `run` that returns a slow Promise blocks the queue behind
  it. Actions must be idempotent and must never open `prompt()`/`confirm()`.
- **The local model tier needs 8 GB free VRAM.** `voice_brain.MIN_FREE_VRAM_MB`
  is `8 * 1024`; below that the `llm` tier is skipped and an utterance that no
  builtin or grammar rule matched returns `tier: 'none'`. The grammar tier has no
  such requirement, so navigation and registered aliases keep working while the
  GPU is busy rendering.
- **The architecture design hand-off uses the existing Sonnet assistant.** In the
  `architecture` view an utterance starting with an arch verb becomes
  `architecture.assist {text: <verbatim>}` with `tier: 'arch'`; `voice_brain`
  never rewrites that text. The standing rule holds — the arch assistant is never
  run on Opus.
- **SSE costs a thread.** `kanban_server` is a stdlib `ThreadingTCPServer`, so
  each open stream holds one thread for as long as the tab lives (hours).
  `handle_sse` is written never to raise out of its loop for that reason.
- **Utterance bodies are capped** at `BODY_LIMIT = 4_000_000` bytes of JSON,
  i.e. roughly 30 s of base64'd opus plus context.
- **A restart is needed for the Python seam, but not for extensions.**
  `voice_ext/<name>.py` is re-imported whenever its mtime moves, and
  `/voice_ext/bundle.js` is rebuilt per request, so client files and ext ops land
  with a browser reload. Changes to `voice_bridge.py`, `voice_brain.py`,
  `voice_stt.py` or the mount in `kanban_server.py` need
  `systemctl --user restart kanban-server.service`, which must only be done while
  `GET /inspect/api/architecture/assistant/active` reports `running: 0`.
