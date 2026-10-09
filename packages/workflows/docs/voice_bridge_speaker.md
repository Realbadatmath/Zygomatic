# Voice bridge — speaker verification

Only the operator's enrolled voice is obeyed.

## Read this first: it is a filter, not a lock

This is a **convenience filter**. It compares the voice at the microphone with
the voice you enrolled and refuses the ones that do not match. It tells a
stranger in the room from you. It **cannot** tell you from a **recording of
you**: play a clip of the operator at the microphone and it passes, every time.
Nothing in an ECAPA embedding carries liveness.

So: use it to stop a colleague, a television, or a passer-by from driving the
studios by accident. Never use it as authentication, and never gate anything
destructive on it alone. If the machine is somewhere people you do not trust can
speak at it, the answer is a locked door, not a threshold.

## What it does

| | |
|---|---|
| Model | `speechbrain/spkrec-ecapa-voxceleb` (Apache-2.0, 192-dim embedding) |
| Where it runs | CPU, in its own venv `/home/zygomatic/models/speaker_verify/.venv` |
| Cost | ~150 ms per embedding, **zero VRAM** — the 4090 is never touched |
| Provenance | `/home/zygomatic/models/speaker_verify/PROVENANCE.json` |

The kanban process holds no model. `voice_ext/speaker.py` starts
`speaker_verify_worker.py` in that CPU venv on first use, talks JSON lines to it
over a pipe, and restarts it if it died. The worker loads ECAPA once and exits
after 10 minutes idle, so an unused bridge costs nothing.

## Enrolling from the panel

1. Open the voice panel and press **Enrol**.
2. Say **at least 20 seconds** of ordinary speech — read anything, keep your
   normal voice and normal distance from the microphone. Under 20 s the request
   is refused with the length it measured; the mean embedding of a short clip
   still carries the sentence more than the speaker.
3. The clip is cut into 4-second windows, each is embedded, and the
   **L2-normalised mean** is stored in
   `data/runtime/voice_bridge/speakers/<slug>.json` — `{name, emb, n_windows,
   created}`. The audio itself is **not** kept.
4. Enrol again with the same name to overwrite. Several names can be enrolled;
   `verify` reports the best match across all of them.

Enrol in the acoustic conditions you will actually use. A headset enrolment and
a far-field session are two different voices to ECAPA.

## Thresholds

Every utterance is scored as the **cosine** of its embedding against each
enrolled speaker; the best one wins. Two keys in
`data/runtime/voice_bridge/config.json` decide what happens next:

| key | default | meaning |
|---|---|---|
| `speaker_threshold` | `0.55` | accept when `score >= threshold` |
| `speaker_gate` | `true` | `false` = accept everyone, **and still report the real score** |

Read or set them over the ext seam:

```
GET  /inspect/api/voice/ext/speaker/config
POST /inspect/api/voice/ext/speaker/config   {"speaker_threshold": 0.6, "speaker_gate": true}
```

### Why 0.55

Measured on this machine by `tools/vb_speaker_bench.py`, which embeds the two
halves of the Abel narrator seed (same speaker, different sentences) and one
voice from the reference pool:

```
same  abel_A  vs abel_B   cosine  +0.8631
cross abel_A  vs other    cosine  +0.0886
cross abel_B  vs other    cosine  +0.1041

margin = same - worst cross = +0.7590  (need >= 0.15)
```

0.55 sits in the middle of a gap that is five times wider than it needs to be,
which is what makes the default safe to ship.

Tuning it, when you have to: **turn the gate off first**
(`speaker_gate: false`). Everything is then accepted, but the honest score is
reported on every utterance. Talk normally for a few minutes, watch the numbers,
and set the threshold below your worst and above the room's best. Then turn the
gate back on. Raise it if something else in the room gets through; lower it if
you are refused when you are tired, ill, or across the room.

With nobody enrolled, `verify` returns `reason: "nobody is enrolled"` and
follows the gate: gate on refuses everything, gate off lets everything through.

## Routes

All under `/inspect/api/voice/ext/speaker/`; the module reloads when the file
changes, so no server restart is needed.

| op | method | payload | returns |
|---|---|---|---|
| `enrol` | POST | `{name, audio_b64, mime}` or `{name, wav}` | `{ok, name, slug, seconds, n_windows}` |
| `verify` | POST | `{audio_b64, mime}` or `{wav}` | `{ok, name, score, accepted, gate, threshold, others}` |
| `list` | GET | — | `{ok, speakers:[{name, slug, n_windows, created, seconds}], count}` |
| `delete` | POST | `{slug}` or `{name}` | `{ok, deleted}` |
| `config` | GET/POST | see above | `{ok, speaker_threshold, speaker_gate}` |

Input is converted the way `voice_stt` does it: `ffmpeg -ac 1 -ar 16000` into a
temporary wav, which is deleted when the request ends. `audio_b64` accepts a
bare base64 string or a `data:` URL.

## Proving it still works

```
cd "/home/zygomatic/Zygomatic Full/agents/crews"
../.venv/bin/python tools/vb_speaker_bench.py            # real model, exit 0 = PASS
../.venv/bin/python -m unittest tests.test_voice_speaker # logic only, no model
```

The bench loads ECAPA and takes a few seconds; the unit tests monkeypatch
`speaker.embed_wav` and run in under a second. `--other f01_warm_alto` (or any
name in `data/assets/voice_seeds/pool/manifest.json`) picks a different
cross-voice.
