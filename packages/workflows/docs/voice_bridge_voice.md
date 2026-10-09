# The voice bridge's reply voice — operator note

How the assistant on :8899 chooses the voice it answers in, what the say-cache is,
and what to do after you change the voice.

Everything below lives under `agents/crews`. Run the python in it with
`../.venv/bin/python`.

---

## 1. How the voice is picked

Three things decide what a reply sounds like. All three are part of the cache key,
so changing any of them means the old cached audio is never served again.

**a. `voice_id` — `data/runtime/voice_bridge/config.json`**

```json
{ "voice_id": "abel", "engine": "auto" }
```

`voice_ext/tts.load_config()` reads it. An id that is not in the Voice Studio
registry (`voice_studio.VOICES`) is discarded and `default_voice()` is used
instead: **`abel`** when he is registered, otherwise the first voice in the
registry. A missing config.json is the same as an empty one — there is no error,
you get Abel.

Set it from the bridge itself:

```
POST /inspect/api/voice/ext/tts/config   {"voice_id": "mila_04"}
GET  /inspect/api/voice/ext/tts/voices    -> the picker list (id, name, role,
                                             has_active_preset) + the current pick
```

`save_config()` **merges**, so a POST that names only the voice keeps the engine
and vice versa. Writing config.json by hand works too; nothing caches it in
memory.

**b. The Voice Studio preset — the knobs**

The bridge does not own a knob set. `params_for(vid, engine)` is

```python
VS.sanitize(VS.active_params(vid) or VS.defaults())   # then p['engine'] = engine
```

`VS.active_params(vid)` returns the params of the preset marked **active** for that
voice, which is the preset whose slug is named in
`data/assets/voice_presets/<voice_id>/_active.json`. No active preset → Voice
Studio's `defaults()`. So the way to change *how* a voice speaks (emo alpha, tone
rack, tempo, seed…) is to tune it on the Voices tab, save the preset and mark it
active — the bridge adopts it on the next `say()`, with no restart.

For the record, the knob set this note was measured with (Abel, **no** active
preset, i.e. the defaults):

```
{"air":0.0,"body":0.0,"cb_cfg_weight":0.4,"cb_exaggeration":0.3,
 "cb_temperature":0.7,"comp":0.0,"deess":0.0,"device":"auto","eng_seed":1672,
 "engine":"indextts2","hpf":20.0,"ix_emo_alpha":0.6,"ix_emo_text":true,
 "lufs":-16.0,"mid":0.0,"pitch_st":0.0,"presence":0.0,"room":0.0,"room_ms":45.0,
 "seed_k":1.0,"seed_m":1.0,"size":1.0,"tempo":1.0,"tp":-1.5,"warmth":0.0}
```

The clone reference is the voice's frozen **seed** wav
(`ref_wav_for()` → `VOICES[vid]['seed']`, for Abel
`data/assets/voice_seeds/abel_narrator_seed.wav`) — deliberately not
`identity_ref`, which is a render and would be a second generation of loss.

**c. The engine**

`engine` in config.json is `auto` | `indextts2` | `chatterbox`. `auto` is resolved
per call by `choose_engine()`: **IndexTTS-2 when free VRAM ≥ 21000 MB**
(`ZYG_INDEXTTS_MIN_VRAM_MB`, the same line the IndexTTS-2 worker itself gates on),
**Chatterbox otherwise**. `nvidia-smi` unreadable counts as *not enough* — unknown
must not read as plenty, and the 4 GB engine is the one that still produces audio
on a busy card.

This matters for the cache: a phrase warmed while the card was free is stored under
the `indextts2` key, and a reply asked for while the card is busy resolves to
`chatterbox` and **misses**, paying a full render. If you want the cache to always
hit, pin `"engine": "chatterbox"` (or "indextts2") instead of leaving it on `auto`.

Every reply, whichever engine made it, is finished to one loudness:
silence trimmed off both ends, then `loudnorm` to **-16 LUFS, mono, 24 kHz,
16-bit** (`post_process()`), so answers do not jump in level between engines.

---

## 2. The say-cache

`data/runtime/voice_bridge/say/<sha1>.wav`, one file per phrase, keyed on
`sha1(voice_id | resolved engine | the whole sorted knob set | the exact text)`.
Nothing expires it; nothing invalidates it either — a changed voice or preset
simply produces different keys and the old files sit there unread.

`GET /inspect/api/voice/ext/tts/cache` reports count and bytes.

---

## 3. Pre-rendering — `tools/vb_prerender.py`

```
../.venv/bin/python tools/vb_prerender.py            # render what is missing
../.venv/bin/python tools/vb_prerender.py --clear    # drop the cache first
../.venv/bin/python tools/vb_prerender.py --list     # print the phrases, render nothing
../.venv/bin/python tools/vb_prerender.py --limit 5  # smoke run
```

It collects every fixed sentence the assistant can speak:

* `voice_brain.PHRASES` (imported) — the brain's own replies, `Opening <view>` for
  every view plus `Done`, `Drawing that now`, `I did not catch that`, …
* the `say:` of every action registered in `voice_ext/*.js`, read out of the
  source with `say:\s*'([^']*)'` and the double-quoted form. Backticked template
  literals are skipped (they are not fixed sentences), and so is half a
  concatenation such as `say: 'Opening ' + name` — a literal that keeps an edge
  space or is followed by `+` is never spoken on its own.

then feeds them **one at a time** to `voice_ext.tts.ROUTES['prerender']`, imported
as a module. Not over HTTP: the pre-render is meant to be run before
kanban-server has been restarted with the bridge mounted, so there is no endpoint
yet. One phrase per call is what lets the table print a real per-phrase time and a
real cached/rendered verdict.

**After changing the voice or the active preset:** the new keys are all misses, so
the first time the assistant says each sentence it pays a full render. Re-warm it:

```
# 1. point the bridge at the new voice
curl -s -X POST http://127.0.0.1:8899/inspect/api/voice/ext/tts/config \
     -H 'content-type: application/json' -d '{"voice_id":"<new id>"}'
#    (or just edit data/runtime/voice_bridge/config.json)
# 2. throw the old audio away and render the new voice
../.venv/bin/python tools/vb_prerender.py --clear
```

`--clear` deletes every `*.wav` in the say directory before rendering. Without it
the old voice's files stay on disk for ever — harmless but dead, about 160 kB
each. The tool renders with whatever config.json says and takes **no** `--voice` /
`--engine` flag on purpose: a flag that did not actually reach the route would
warm the cache under keys the running bridge never asks for.

Exit code is 0 when every phrase landed, 1 if any failed (the failures are listed
at the end).

---

## 4. Measured latency (2026-09-15, this box, Abel, defaults, IndexTTS-2)

Free VRAM at the start of the run was 46344 MB, well over the 21000 MB gate, so
`auto` resolved to **indextts2** for all of it.

All 308 phrases, timed one call at a time around `ROUTES['prerender']`:

| | min | median | mean | max |
|---|---|---|---|---|
| **uncached** (miss → engine), 308 sentences | 15129 ms | 16004 ms | **16001 ms** | 17341 ms |
| **cached** (hit → one stat + a file read), the same 308 | 13 ms | 23 ms | **23 ms** | 37 ms |

Whole-pass wall time: **4928 s (82 min) cold, 7.3 s warm** — 0 failures either
time, and the warm pass reported 0 rendered / 308 cached, which is the proof the
cache key is stable across processes.

So a cached reply is roughly **700× cheaper** than an uncached one: 23 ms is
inaudible, 16 s is the operator waiting for the assistant to think.

The uncached cost is almost entirely the **model load**: `voice_studio.synth()`
spawns the engine's venv worker per call, and the worker loads IndexTTS-2 from
cold every time. The sentences here are 2–8 words, so the actual inference is a
small part of it — a longer reply does not cost proportionally more.

Chatterbox is the cheaper engine (it is what `auto` picks when the card is busy);
these numbers are the IndexTTS-2 case, which is the expensive one.

Practical reading: **a pre-rendered reply is instant, an unrehearsed one is a
quarter of a minute.** That is the whole reason this tool exists. Any new fixed
`say:` added to a `voice_ext/*.js` file should be followed by a plain
`tools/vb_prerender.py` run (no `--clear`) — it renders only the new sentences and
reports the rest as cached.
