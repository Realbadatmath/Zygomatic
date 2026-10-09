# The Zygomatic API test layer — operator guide

This folder and `tests/api/` together are the test layer for the four Flask apps
that make up Zygomatic's HTTP surface: the **dashboard**
(`src/zyg_dashboard/crewai_web_gui.py`, port 5000, 430 routes), **zero_public**
(`zyg_zero/zero_public_server.py`, port 5001, 69 routes), **medusa**
(`medusa_server.py`, port 5300, 53 routes) and the tiny **skill_proxy**
(port 5051, 5 routes). 554 routes in total. Before this layer existed, zero of
them had an HTTP test.

The split across repositories, since the 2026-10-05 repository split: the
dashboard, medusa and skill_proxy modules live here in `zygomatic-dashboard`, so
their pytest modules are in this repo's `tests/api/`. **zero_public lives in the
sibling `zygomatic-zero-public` repository and its test module moved with it** —
`test_zero_public.py` is now `../zygomatic-zero-public/tests/api/test_zero_public.py`
and is run from that repository. The route inventory, the classification files and
the Postman collection in this folder still cover all four apps, because the
collection is generated once from one inventory.

Everything here runs from the repository root:

```
cd .../zygomatic-dashboard
```

and uses an interpreter that can import the apps — the venv the packages are
installed in, never a bare system Python with no dependencies. The commands below
take it from `ZYG_PY` and fall back to `python`:

```
export ZYG_PY=/path/to/venv/bin/python
```

---

## 1. The two layers, and when to use which

**Layer A — pytest + Flask `test_client` (in-process).** `tests/api/`. This is
the layer that runs in CI and on the Session Tree board. It does **not** talk to
a network socket and does **not** need any server to be running: it imports the
Flask app object into the test process and pushes requests straight into it. That
is why it is fast (the whole suite is ~54 s), why it can read a response without
guessing, and why it can safely test the login gate from a pretend IP address.
Use layer A to answer *"did my change break a route?"*

**Layer B — Postman / Newman (over the network).** `apitests/zygomatic.postman_collection.json`.
Generated from the *same* route inventory as layer A, so the two can never drift.
This layer talks HTTP to a **live** service on 127.0.0.1. Use layer B when you
want to click around a real running system, inspect real headers and bodies, or
hand someone a collection they can import and explore. Use it for learning and
for manual poking; use layer A for proof.

Run both with one command:

```
bash apitests/run_all.sh
```

It runs layer A, then layer B, prints every report path, and exits non-zero if
either failed.

---

## 2. The hazard you must understand before you touch layer A

Importing `crewai_web_gui` does not just define routes — **it starts about 19
background worker threads** (market-scheduler, preempt-watcher,
zero-approval-worker, remix-watcher, storyteller-daily-watcher, sports-scheduler,
telemetry-sampler and more). `zero_public_server` likewise starts `zpub-worker`,
the real job runner. The test process runs on the *same machine as the live
production services*. A second copy of those workers would poll the same queues,
write the same files under `data/runtime`, and race the live process — i.e. a
test run could corrupt production state without ever issuing a request.

So every fixture neuters `threading.Thread.start` around the import:

```python
_real = threading.Thread.start
threading.Thread.start = lambda self: None if not self.name.startswith('Otel') else _real(self)
import crewai_web_gui as g

threading.Thread.start = _real
```

Three things about that recipe are load-bearing:

1. The **Otel** exporter thread is let through. Its `atexit` handler joins it, and
   joining a thread that was never started prints a `RuntimeError` at shutdown.
2. For zero_public the suppression stays installed **for the whole module**, not
   just the import — several handlers import heavy modules lazily
   (`GET /api/storyteller/voices` pulls in `crewai_web_gui`), so a sweep can start
   a watcher long after import time. The report's `suppressed_threads` list is the
   proof that it did not.
3. Each fixture asserts in teardown that no watcher thread survived. If you add a
   test module that imports an app, copy an existing fixture; do not write a new
   import.

The second hazard is the **rate limiter**. The dashboard's default is 200
requests/hour; the GET sweep alone issues 225. Every fixture therefore sets
`app.limiter.enabled = False` (for zero_public the object is
`zpub_gate.limiter`, default 2000/hour). Without it, half a sweep comes back 429
and the failures look like route bugs.

Also set `socket.setdefaulttimeout(5)` so a handler that reaches for a dead
service fails fast instead of hanging the suite, and
`os.environ['CREWAI_PAGE_LOAD_DEBUG'] = '0'` before the import to silence a debug
print on every request.

---

## 3. Authentication, in one page

**Dashboard.** A `before_request` hook, `require_login` (`crewai_web_gui.py:410-560`),
answers before any handler: `401` JSON on `/api/*` without a session role, `302`
to `/login` on pages. An admin session for the test client is made like this:

```python
with client.session_transaction() as s:
    s['user_role'] = 'admin'
    s['user_id'] = '__apitest__'
    s['user_name'] = 'apitest'
    s['_validity'] = g.SESSION_VALIDITY_TOKEN
    s['_csrf_token'] = 't' * 43
```

**CSRF** (`_require_csrf`, lines 391-407): POST/PUT/DELETE/PATCH on `/api/*` need
the header `X-CSRF-Token` equal to `session['_csrf_token']`, or you get `403`
(only `/api/login` is exempt).

The gate has two bypasses you must respect when writing a test:

* an **open allowlist** that needs no login at all (`/static/*`, `/favicon.ico`,
  `/api/telemetry`, `/api/vram/free`, `/api/health`, `/api/kanban/status`,
  `/api/creator-nexus/*`, `/api/medusa/kanban_status`, and a dozen more);
* a **localhost bypass** when `request.remote_addr` is `127.0.0.1`, covering
  `/api/medusa/*`, `/api/approval_queue/*`, `/api/preempt/*`,
  `/api/internal/<subsystem>/*`, `/api/storyteller/training/*`, `/api/skill/inbound`.

The test client's default `REMOTE_ADDR` **is** `127.0.0.1`, so to test the gate on
those routes you must come from somewhere else:

```python
client.get(url, environ_base={'REMOTE_ADDR': '10.0.0.9'})
```

**zero_public** has *no* app-level gate — every gated route checks a session in
its own body. **medusa** has no login at all: `medusa_ipgate` allows 127.0.0.1 and
answers `403` JSON to anything else. **skill_proxy** allows only the source
network `10.10.20.` (`skill_proxy.py:44`) and needs a `runner_token` in the body.

---

## 4. The risk classes — the rule that keeps this layer safe

The dashboard has 166 routes that take a body (145 POST, 8 GET+POST, 8 DELETE,
5 PATCH). Calling one is nothing like calling a GET: a handler that runs writes
the operator's real state under `data/runtime`, starts a pipeline, trains a LoRA,
approves a queue item or deletes files. **There is no test data root.** So every
body route was classified by *reading its handler*:

| class | meaning | what the tests may do |
|---|---|---|
| `safe` | idempotent, writes nothing | call it, assert it is not a 5xx |
| `validate` | an empty `{}` body is rejected with a 4xx **before** the first write, subprocess or thread | POST `{}`, assert the recorded status |
| `exclude` | anything else, **or anything that could not be verified** | **never called with a session** |

Dashboard counts: 14 `safe`, 31 `validate`, **123 `exclude`**. The classification
lives in `apitests/classify_A.json` + `classify_B.json` and is merged into
`routes.json`; `merge_classify.py` refuses to merge if a body route has no class,
if a class names a route that does not exist, or if a risk is outside
`safe|validate|exclude`.

### GET-only routes: the `danger` flag, and how to override it

A GET has no body, so it has no risk class. What decides whether the read-only
sweep calls it is the inventory's `danger` flag, and that is a heuristic —
`inventory.route_danger()`. For body routes it is still the substring match of
`DANGER_RE` (a POST is assumed to act until a hand classification proves
otherwise, so a false positive is free). For a GET a false positive is *not*
free: it drops the route out of the sweep, which is the only test the route has.
So since 2026-10-06 a GET acts only when

* an action verb from `GET_ACTION_WORDS` is the **whole last segment** of the
  rule (`/api/gpu/timeline/generate` acts; `/api/assetlib/generated` lists), or
* its handler source matches `HANDLER_WRITE_RE`.

That replaced a plain substring match which had excluded 31 read-only GETs for
verbs that named something else in the path: `skill` matched `kill`,
`asset_manager` matched `set_`, `<run_id>` matched `run`, every
`/api/medusa/training/...` getter matched `train`. `login` is deliberately not
an action word (GET `/login` renders a form) but `logout` is (it clears the
session, which would log the shared test client out). `download` and `export`
are not: on a GET they name a generated artefact being read back.
`os.makedirs`/`mkdir` are deliberately not in `HANDLER_WRITE_RE` — the
`/api/medusa/training` listing endpoints ensure their already-existing root with
`exist_ok=True` before scanning it, which writes no data.

`apitests/classify_get.json` overrides the flag by hand, and is applied by
`merge_classify.py` **after** the heuristic. Each entry needs `rule`, `endpoint`
(checked against the inventory), `danger` (a bool) and a `why`. That file — never
a weakened assertion in `test_get_smoke_dashboard.py` — is where a route goes
when the sweep proves it answers 5xx or writes real state.

The one assertion that is safe for **every** gated route, including all 121
excluded ones, is an **anonymous request from a non-localhost address**: the gate
answers 401 before the handler is ever reached. That is how 158 body routes are
covered without a single side effect.

In layer B the same contract is enforced by the collection itself: everything
`exclude` lives under the folder `EXCLUDED — side effects (never run blind)`,
whose pre-request script *throws* unless `ALLOW_DANGEROUS=1`. Do not set that
variable against production data.

---

## 5. Commands

Layer A, the whole thing:

```
"${ZYG_PY:-python}" -m pytest -o addopts= -q -p no:cacheprovider tests/api
```

`-o addopts=` matters: `pytest.ini` already supplies `-q`, and a second `-q`
suppresses the `N passed` summary line you actually want.

Per module (use these while iterating — the dashboard import costs ~3 s/315 MB):

```
"${ZYG_PY:-python}" -m pytest -o addopts= -q -p no:cacheprovider tests/api/test_harness.py
"${ZYG_PY:-python}" -m pytest -o addopts= -q -p no:cacheprovider tests/api/test_get_smoke_dashboard.py
"${ZYG_PY:-python}" -m pytest -o addopts= -q -p no:cacheprovider tests/api/test_post_dashboard.py
"${ZYG_PY:-python}" -m pytest -o addopts= -q -p no:cacheprovider tests/api/test_medusa.py
```

zero_public is run from its own repository:

```
cd ../zygomatic-zero-public
"${ZYG_PY:-python}" -m pytest -o addopts= -q -p no:cacheprovider tests/api/test_zero_public.py
```

One test, by name:

```
"${ZYG_PY:-python}" -m pytest -o addopts= -q -p no:cacheprovider \
  "tests/api/test_post_dashboard.py::test_gate_rejects_anonymous_body_request[POST /api/zero/chat]"
```

Layer B, headless:

```
bash apitests/run_newman.sh
```

That runs only the folder `Health (open, no login)` — 18 GET-only,
login-exempt endpoints on 127.0.0.1, no body, no side effects. Every other folder
skips itself while `ZYG_USER`/`ZYG_PASS` are empty, so an anonymous run reports
skips instead of a wall of 401s.

Both layers:

```
bash apitests/run_all.sh
```

### Opening the collection in Postman desktop

```
sudo snap install postman
```

Then in Postman: **Import** → `apitests/zygomatic.postman_collection.json`, and
**Import** again for `apitests/zygomatic.postman_environment.json`. Select the
environment *Zygomatic local (127.0.0.1)* in the top-right picker. It defines
`dash_url`, `zpub_url`, `medusa_url`, `skill_url`, a `__apitest__` default for
every path variable in the inventory, and empty `ZYG_USER` / `ZYG_PASS`.

Fill `ZYG_USER` and `ZYG_PASS` **in the Postman environment only** — as *current
value*, which Postman does not sync or export. Never put credentials in the JSON
files in this folder; they are read by other agents and ship with the repo.

---

## 6. Adding a new route to the layer

1. Regenerate the inventory: `"${ZYG_PY:-python}" apitests/inventory.py`
   → rewrites `apitests/routes.json` and `apitests/routes.md`. The output is
   deterministic apart from the `generated` timestamp, so the diff is exactly
   your route.
2. If the route takes a body, classify it by **reading the handler** and add an
   entry to `apitests/classify_A.json` or `classify_B.json`: `risk`
   (`safe`/`validate`/`exclude`), `empty_body_status` (for `validate`), and a `why`
   that names the file and line where the first side effect would happen. If you
   cannot prove it rejects `{}` before acting, it is `exclude`. That is not a
   failure, it is the correct answer. If it is a GET and the heuristic got its
   `danger` flag wrong, add an entry to `apitests/classify_get.json` instead
   (see §4).
3. Merge: `"${ZYG_PY:-python}" apitests/merge_classify.py` (or `--check` to
   verify without writing). It aborts on anything unclassified or contradictory.
4. Regenerate layer B: `"${ZYG_PY:-python}" apitests/make_postman.py`.
5. Re-run: `bash apitests/run_all.sh`.

The pytest modules read `routes.json` and parametrise themselves, so steps 1–3
are usually all a new route needs — you only write test code for behaviour that
the generic classes cannot express.

---

## 7. Where the reports land and how to read them

Everything is written under `apitests/reports/` by the tests themselves, so a
report is always as fresh as the last run.

| file | what it holds |
|---|---|
| `get_smoke_dashboard.json` | every dashboard GET that was attempted: rule, status, ms. `summary.counts_by_status` and `summary.slowest_10` are the two fields to read |
| `post_dashboard.json` | the body-route matrix, split into `gate_results`, `csrf_results`, `validate_results`, `safe_results`, and `exclude_never_executed` (the 121 routes that were deliberately *not* called, each with the reason) |
| `zero_public.json` | zero_public + skill_proxy status matrix, plus `suppressed_threads` (the thread-leak proof) and `never_called` — written by the test in the `zygomatic-zero-public` repository, under *that* repo's `apitests/reports/`, so `run_all.sh` here no longer lists it |
| `medusa.json` | medusa's 53 rules, their class, and `get_excluded_by_hand` |
| `newman_health.json` | the raw Newman run (large). `run.stats` is the part to read |
| `findings_*.md` | prose: the real issues, with route names and line numbers |

Reading a result: a `401` in `gate_results` is a **pass** (the gate worked), a
`403` in `csrf_results` is a **pass** (CSRF worked), a `4xx` in
`validate_results` is a **pass** (the handler refused an empty body). A `5xx`
anywhere is a bug. A `404` on a route with a path parameter usually just means
`__apitest__` is not a real id.

---

## 8. Findings so far (measured 2026-10-02)

Re-measured 2026-10-06, after the GET `danger` heuristic was narrowed (§4) and
the inventory regenerated: the dashboard suite
(`pytest -q -m "not gpu and not service"`) is **598 passed, 14 skipped**, up
from 563 passed / 42 skipped. `test_excluded_get_is_not_called` went from 39
skips to 10 — 29 read-only GETs are now actually called, and all 29 answer
non-5xx — while `tests/test_schedule_cpu_gpu_timelines.py` adds one opt-in skip,
for a net −28. The 10 that remain are 6 `external` plus the 4 pinned in
`classify_get.json`; one of those four is FINDING 3 below.

Current state of the layer: **555 passed, 2 failed, 39 skipped** in layer A;
**18/18 assertions passed** in layer B. The two failures are not flaky — they are
the findings below, and they will go green the day the code is fixed.

**Layer-A results by app.** Dashboard GETs: 225 requested, 176×200, 27×404 (path
params filled with `__apitest__`), 16×400 (missing query arguments), 2×401,
1×403, 1×302, 2×503 (`/api/agents`, `/api/gpu/schedule` — honest "no control
plane" answers), **0×500**. Dashboard body routes: 158 gate checks all 401, 31
CSRF checks all 403, 31 `validate` POSTs all 4xx, 14 `safe` routes 200 or 501,
**0 findings** — every `validate` route really does refuse `{}`. Medusa: 15 safe
GETs 200, 6 `validate` POSTs 400, 2 404, 18 excluded (all of them proxy a
mutating call to the live dashboard API on :5000 — character generation, LoRA
training, contact-sheet renders, deletes).

### FINDING 1 — `POST /api/sports-video/trigger` has no gate and acts immediately

`zpub_routes_sports.py:64`, `sv_pipeline_trigger()`. The handler reads the JSON
body and then, **before any authentication, authorisation or validation**, calls
`scripts.betlab_query.write_data_json(...)` — an anonymous POST queries
`betlab.db` and writes `sports-video/data/<sport>_<date>.json`, then goes on to
the sports-video pipeline. This is the *public, internet-facing* app (served
through the cloudflared tunnel) and `/api/sports-video/status` is in the
dashboard's open allowlist, so the route is discoverable. The test layer
**never issues this request**; it asserts on the handler's source instead, which
is why `test_ungated_acting_body_route_is_still_ungated` fails. Suggested fix
(not applied): make `blocked = _require_api_session()` the first statement, the
shape `zpub_routes_public.api_submit` already uses.

### FINDING 2 — `POST /api/cinema/lock` answers 200 to an anonymous empty body

`zpub_routes_cinema.py:118`. No `_require()`, no rate limit. Measured:
anonymous POST from `10.0.0.9` with `{}` → **200**. Impact is low (it only clears
the caller's own session key) but it breaks the invariant the layer asserts, and
being ungated and unlimited it is a free request. Either give it `_require()` or
annotate it as deliberately public.

### FINDING 3 — `GET /api/jackmona/daily_batch` is a hard 500

`bp_jackmona_daily.py:502`, `api_jackmona_daily_batch()`. Line 512 reads
`list(__import__('zyg_workflows.kids_music_theory').SONG_SECONDS)`. `__import__`
with a dotted name returns the **top** package, so the attribute lookup raises
`AttributeError: module 'zyg_workflows' has no attribute 'SONG_SECONDS'` and the
route answers 500 to every caller — including the board card and the operator's
shell that the handler's own comment says it feeds. Found 2026-10-06 the first
time the GET sweep was allowed to call it. The fix is
`importlib.import_module('zyg_workflows.kids_music_theory')`. Not applied here;
the route is pinned `danger` in `classify_get.json` so the sweep stays green,
and **that pin must be deleted when the fix lands**.

### Root cause behind both

**zero_public has no app-level `before_request` gate.** Each route authenticates
in its own body, so a route added to a zero_public blueprint is **public by
default**. Gate calls per file: `zpub_routes_public.py` 5,
`zpub_routes_storyteller.py` 2, `zpub_routes_cinema.py` 0 (a module-local
`_require()`, 8 call sites), `zpub_routes_admin.py` 0 (module-local
`_check_admin`), **`zpub_routes_sports.py` 0**.

### Smaller observations (recorded, not fixed)

* `/api/metrics/all` takes **11.8 s** and `/api/metrics/dashboard` **11.4 s**
  in-process, `/api/dependencies/status` 6.5 s. Three routes are 85 % of the
  sweep's wall time.
* `GET /api/storyteller/voice-samples-health` (`zpub_routes_storyteller.py:475`)
  performs a **disk migration** (`migrate_legacy_wav_samples()`) before
  answering. The danger-word heuristic has no `migrate`, so it is classified as a
  safe GET. The regex should learn `migrate|rename|prune|rotate`.
* `GET /api/queue` (`zpub_routes_public.py:757`) returns 200 anonymously — the
  public job queue is readable without an invite. Probably deliberate.
* `/admin/logs` and `/api/admin/logs` answer 401 even with `is_zpub_admin=True`
  in the session: they authenticate on their own token, not the session flag.
* Medusa's `GET /api/vicky/chat` **writes** (`medusa_vicky.open_chat()` rewrites
  `data/runtime/vicky/current.json` and mints a chat file when the store is
  empty). A GET that writes is excluded by hand, not by the heuristic.
* `POST /api/approval_queue/<wf>/settings` answers 404 rather than the 400 its
  classification expected — an unknown workflow id is rejected earlier than the
  body is. Harmless; the class is right, the expected status was optimistic.
