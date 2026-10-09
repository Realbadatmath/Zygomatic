# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_studio.jobs — render jobs, the synthesis cache and the FINISHED-take cache.

Moved verbatim from voice_studio.py lines 1769-2280 (2026-10-06 split).
"""

from __future__ import annotations

from zyg_workflows import provenance_seal as _seal
import json
import logging as _zyg_logging
import os
import shutil
import threading
import time

from zyg_workflows.voice_studio.constants import (
    MAX_PREVIEW_CHARS,
    RENDER_ROOT,
    _SEED_SR,
    _SR,
)
from zyg_workflows.voice_studio.policy import (
    voice,
)
from zyg_workflows.voice_studio.params import (
    RACKS,
    sanitize,
)
from zyg_workflows.voice_studio.synthesis import (
    _apply,
    measure,
    render_chain,
    seed_chain,
    synth,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.voice_studio')


# ──────────────────────────────────────────────────────────────── render jobs
# One render at a time: the engines want the whole GPU, and two concurrent
# Chatterbox loads on CPU starve each other past the worker timeout.
_JOBS: dict = {}
_LATEST: dict = {}  # voice -> newest job id, so stale queued renders can bail
_JOBS_LOCK = threading.Lock()
_RENDER_GATE = threading.Semaphore(1)
_JOB_KEEP = 24
_RENDER_TTL_S = 6 * 3600

# ── who gets the engine first ──
# The gate is one semaphore and a semaphore is not fair, so a background batch
# that releases and immediately re-acquires can win the race against an operator
# who just pressed Render — every time, for hours. Interactive renders therefore
# announce themselves here BEFORE queueing, and the batch workers wait while the
# count is non-zero. Without this the library bake would be indistinguishable
# from a hung panel.
_GATE_WAITERS = 0
_WAIT_LOCK = threading.Lock()


def _gate_want(delta: int):
    global _GATE_WAITERS
    with _WAIT_LOCK:
        _GATE_WAITERS = max(0, _GATE_WAITERS + delta)


def _yield_to_interactive(stop=None):
    """Hold a background batch back while any interactive render is queueing."""
    while _GATE_WAITERS > 0:
        if stop and stop():
            return
        time.sleep(0.4)


def _job_set(jid: str, **kw):
    with _JOBS_LOCK:
        j = _JOBS.get(jid)
        if j:
            j.update(kw)


def _job_log(jid: str, msg: str):
    with _JOBS_LOCK:
        j = _JOBS.get(jid)
        if j:
            j['log'].append(f'{time.strftime("%H:%M:%S")} {msg}')
            j['log'] = j['log'][-40:]


def job(jid: str) -> dict:
    with _JOBS_LOCK:
        j = _JOBS.get(jid)
        return dict(j) if j else {}


def _prune_jobs():
    """Keep the last _JOB_KEEP jobs — but never evict one that is still going.
    A pre-render walks a whole bank and is by far the longest-lived job here; the
    plain oldest-first prune would drop it out of _JOBS mid-sweep and the GUI
    would be left polling a 404 while the engine carried on rendering.
    Caller holds _JOBS_LOCK."""
    live = {k for k, j in _JOBS.items() if j.get('state') in ('queued', 'running')}
    finished = [k for k in sorted(_JOBS, key=lambda k: _JOBS[k]['started']) if k not in live]
    for old in finished[: max(0, len(finished) - _JOB_KEEP)]:
        _JOBS.pop(old, None)


# ── synthesis cache ──
# The whole point of the knob panel is that a twist is AUDIBLE straight away, and
# the engine is the only slow part: ~11 s on GPU versus ~0.3 s for the entire
# ffmpeg post chain. So the raw synthesis is cached against exactly the inputs
# that determine it — voice, text, engine + its sampling knobs, and the seed
# shaping that produces the reference wav. Turn a TONE knob and the cached take
# is re-used, so the render loop closes in about a second instead of twelve.
# Anything that changes what the model actually says or sounds like misses the
# cache and re-synthesises, which is correct: those knobs cannot be faked.
_SYNTH_KEYS_COMMON = ('engine', 'eng_seed', 'seed_k', 'seed_m')
_SYNTH_KEYS_ENGINE = {
    'chatterbox': ('device', 'cb_exaggeration', 'cb_cfg_weight', 'cb_temperature'),
    'indextts2': ('ix_emo_alpha', 'ix_emo_text'),
}
# 48, not 12 (2026-08-12). Pre-rendering a voice's presets walks 11+ DIFFERENT
# engine settings back to back, and each is its own synth key — at 12 the tier
# evicted its own earlier entries before the sweep finished, so re-opening the
# first preset re-synthesised. The wavs are ~1–2 MB and the tier is swept by the
# same LRU as before.
_CACHE_KEEP = 48

# Stamp every parameter with whether moving it costs a new synthesis. The GUI
# marks those knobs so the operator can tell a ~0.3 s twist from an ~11 s one
# WITHOUT having to learn which is which — and it is derived from the cache key
# itself, so the two can never disagree.
_RESYNTH_KEYS = set(_SYNTH_KEYS_COMMON).union(*[set(v) for v in _SYNTH_KEYS_ENGINE.values()])
for _r in RACKS:
    for _p in _r['params']:
        _p['resynth'] = _p['key'] in _RESYNTH_KEYS


def _synth_key(vid: str, text: str, p: dict) -> str:
    import hashlib

    keys = _SYNTH_KEYS_COMMON + _SYNTH_KEYS_ENGINE.get(p['engine'], ())
    sig = json.dumps([vid, text] + [[k, p[k]] for k in sorted(keys)], sort_keys=True)
    return hashlib.sha256(sig.encode('utf-8')).hexdigest()[:20]


def _cache_dir(vid: str) -> str:
    return os.path.join(RENDER_ROOT, vid, '_synth_cache')


# ── the FINISHED-take cache ─────────────────────────────────────────────────
# The synth cache above skips the engine; this one skips the whole pipeline. Its
# key covers every parameter plus the text, so a hit is bit-for-bit the take the
# render loop would have produced — which is what makes it safe to hand straight
# to the player with no job at all.
#
# It exists because auditioning a preset bank meant pressing Render eleven times
# and waiting ~11 s each. Pre-rendering fills this tier once, and stepping
# through the browser afterwards is a file read.
_TAKE_KEEP = 64  # per voice: 11 starters × a few lines, plus headroom
_CACHE_TTL_S = 14 * 24 * 3600
_CACHE_DIRS = ('_synth_cache', '_takes')
# A per-voice cap alone does not bound this: the tier grows with the number of
# voices anyone has rendered, not just with one voice's presets. So it also
# carries a GLOBAL budget, oldest-first.
#
# 24 GB, sized from measurement rather than guessed: the whole line library is
# 2,683 (voice, line) pairs at ~1.3 MB each ≈ 3.5 GB, and the per-voice preset
# banks on top of it are a few GB more. The budget MUST clear the full library or
# the bake never converges — it would evict the voices it rendered first and then
# find them missing on the next pass. There is 255 GB free on this box.
_TAKE_BUDGET_BYTES = 24 * 1024**3
_TAKE_LOCK = threading.Lock()
_SWEEP = {'at': 0.0}
_SWEEP_EVERY_S = 600


def _take_key(vid: str, text: str, p: dict) -> str:
    import hashlib

    sig = json.dumps([vid, text, sorted(sanitize(p).items())], sort_keys=True, default=str)
    return hashlib.sha256(sig.encode('utf-8')).hexdigest()[:20]


def _take_dir(vid: str) -> str:
    return os.path.join(RENDER_ROOT, vid, '_takes')


def _take_index_path(vid: str) -> str:
    return os.path.join(_take_dir(vid), 'index.json')


def _take_index(vid: str) -> dict:
    try:
        with open(_take_index_path(vid), encoding='utf-8') as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def take_has(vid: str, text: str, p: dict) -> bool:
    """Is there a finished take for this exactly? Stats the wav and stops there.

    take_cached reads the per-voice index too, because its caller wants the
    metrics. Asking the same question for all 244 voices at once — which is what
    the picker's ⚡ marks are — would be 244 JSON reads for a boolean."""
    path = os.path.join(_take_dir(vid), _take_key(vid, text, p) + '.wav')
    try:
        return os.path.getsize(path) > 44
    except OSError:
        return False


def take_cached(vid: str, text: str, p: dict) -> dict:
    """The finished take for exactly these params and this text, or {}.

    Verifies the WAV is still on disk before claiming a hit: the index is a
    convenience, the file is the truth, and the sweep can remove one without the
    other."""
    key = _take_key(vid, text, p)
    rec = _take_index(vid).get(key)
    if not rec:
        return {}
    path = os.path.join(_take_dir(vid), key + '.wav')
    if not (os.path.isfile(path) and os.path.getsize(path) > 44):
        return {}
    os.utime(path, None)  # LRU: touch on use
    return {
        'wav': f'run/{vid}/_takes/{key}.wav',
        'metrics': rec.get('metrics') or {},
        'at': rec.get('at', ''),
        'key': key,
    }


def _take_put(vid: str, text: str, p: dict, wav: str, metrics: dict) -> dict:
    d = _take_dir(vid)
    os.makedirs(d, exist_ok=True)
    key = _take_key(vid, text, p)
    dst = os.path.join(d, key + '.wav')
    try:
        shutil.copyfile(wav, dst)
    except OSError:
        return {}
    # Locked: a hand render publishes its take AFTER releasing the render gate, so
    # it can land while a pre-render batch is writing the same voice's index. The
    # loser of that race would drop the other's row, and a wav that exists but is
    # not indexed reads as a cache miss — an 11 s re-render of a take already on
    # disk. Cheap lock, and only ever held around a small file rewrite.
    with _TAKE_LOCK:
        idx = _take_index(vid)
        idx[key] = {
            'at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'metrics': metrics or {},
            'text': text[:MAX_PREVIEW_CHARS],
        }
        # LRU by file mtime, then drop the index rows whose wav has gone —
        # otherwise the index grows without bound while the directory stays capped.
        try:
            wavs = sorted((os.path.getmtime(os.path.join(d, f)), f) for f in os.listdir(d) if f.endswith('.wav'))
            for _mt, f in wavs[:-_TAKE_KEEP]:
                os.remove(os.path.join(d, f))
            alive = {f[:-4] for f in os.listdir(d) if f.endswith('.wav')}
            idx = {k: v for k, v in idx.items() if k in alive}
        except OSError as _exc:
            _zyg_log.debug('take LRU prune for %s skipped, the budget sweep will catch up: %s', vid, _exc)
        try:
            tmp = _take_index_path(vid) + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(idx, f, indent=1)
            os.replace(tmp, _take_index_path(vid))
        except OSError as _exc:
            _zyg_log.warning(
                'take index %s not written, cached takes will be re-rendered: %s', _take_index_path(vid), _exc
            )
    return take_cached(vid, text, p)


def _sweep_take_budget():
    """Hold the whole take tier under _TAKE_BUDGET_BYTES, oldest first.

    Per-voice caps cannot do this on their own — they bound one voice while the
    tier grows with the number of voices anyone has pre-rendered. Index rows for
    the removed wavs are left behind; take_cached checks the FILE, and the next
    _take_put for that voice prunes them."""
    files = []
    try:
        for vid in os.listdir(RENDER_ROOT):
            d = os.path.join(RENDER_ROOT, vid, '_takes')
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                if not fn.endswith('.wav'):
                    continue
                p = os.path.join(d, fn)
                try:
                    st = os.stat(p)
                except OSError as _exc:
                    _zyg_log.debug('take %s skipped by the budget sweep, it cannot be stat-ed: %s', p, _exc)
                    continue
                files.append((st.st_mtime, st.st_size, p))
    except OSError:
        return
    total = sum(f[1] for f in files)
    if total <= _TAKE_BUDGET_BYTES:
        return
    for _mt, size, p in sorted(files):
        try:
            os.remove(p)
            total -= size
        except OSError as _exc:
            _zyg_log.debug('budget sweep could not delete take %s, it still counts: %s', p, _exc)
        if total <= _TAKE_BUDGET_BYTES:
            break


def _cache_get(vid: str, key: str) -> 'str|None':
    p = os.path.join(_cache_dir(vid), key + '.wav')
    if os.path.isfile(p) and os.path.getsize(p) > 44:
        os.utime(p, None)  # LRU: touch on use
        return p
    return None


def _cache_put(vid: str, key: str, wav: str) -> str:
    d = _cache_dir(vid)
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, key + '.wav')
    try:
        shutil.copyfile(wav, dst)
    except OSError:
        return wav
    try:
        entries = sorted((os.path.getmtime(os.path.join(d, f)), f) for f in os.listdir(d) if f.endswith('.wav'))
        for _mt, f in entries[:-_CACHE_KEEP]:
            os.remove(os.path.join(d, f))
    except OSError as _exc:
        _zyg_log.debug('preview cache prune for %s skipped: %s', vid, _exc)
    return dst


def _sweep_old_renders():
    """Preview wavs are scratch. Anything older than the TTL goes, so the runtime
    tree does not grow a wav per knob twiddle forever.

    The two CACHE tiers get the long TTL instead of the 6 h one. They used to be
    swept with everything else, which quietly undid them: a pre-rendered preset
    bank was gone by the next morning and the operator was back to clicking
    Render on each one. Each tier is still bounded by its own LRU count, so the
    long TTL sets an upper age, not an upper size.

    Throttled to once every 10 minutes. It walks the whole runtime tree, which is
    now thousands of cached wavs, and it used to run on EVERY render — during a
    2,683-take bake that is 2,683 full tree walks to delete nothing."""
    now = time.time()
    if now - _SWEEP['at'] < _SWEEP_EVERY_S:
        return
    _SWEEP['at'] = now
    cutoff, cache_cutoff = now - _RENDER_TTL_S, now - _CACHE_TTL_S
    for root, _dirs, files in os.walk(RENDER_ROOT):
        limit = cache_cutoff if os.path.basename(root) in _CACHE_DIRS else cutoff
        for fn in files:
            p = os.path.join(root, fn)
            try:
                if os.path.getmtime(p) < limit:
                    os.remove(p)
            except OSError as _exc:
                _zyg_log.debug('expiry sweep left %s in place: %s', p, _exc)
    _sweep_take_budget()


def start_render(vid: str, text: str, params: dict) -> dict:
    v = voice(vid)
    if not v:
        raise ValueError('unknown voice')
    if not os.path.isfile(v['seed']):
        raise ValueError(
            f'frozen seed missing: {v["seed"]} — both engines are cloners and cannot synthesise without one'
        )
    text = (text or v['default_text']).strip()[:MAX_PREVIEW_CHARS]
    if not text:
        raise ValueError('nothing to say')
    p = sanitize(params)
    jid = f'{int(time.time() * 1000):x}{os.getpid():x}'
    with _JOBS_LOCK:
        _JOBS[jid] = {
            'id': jid,
            'voice': vid,
            'state': 'queued',
            'log': [],
            'text': text,
            'params': p,
            'wav': '',
            'seed_wav': '',
            'metrics': {},
            'seed_metrics': {},
            'error': '',
            'reused': False,
            'measuring': False,
            'started': time.time(),
            'finished': 0.0,
        }
        _LATEST[vid] = jid
        _prune_jobs()
    threading.Thread(target=_render_worker, args=(jid,), daemon=True).start()
    return job(jid)


def _produce_take(vid: str, text: str, p: dict, work: str, log, on_seed=None) -> 'tuple[str, bool]':
    """Seed shaping → synthesis (or the cached one) → post chain → loudness.

    Returns (final_wav_path, reused_synthesis). Factored out of _render_worker so
    the pre-render pass runs the IDENTICAL chain: a pre-rendered take that was
    produced by a second, subtly different code path would be a cache that lies,
    and it would lie exactly where it is hardest to notice — a preset that sounds
    almost right. `on_seed(metrics, rel_wav)` is called when the seed is shaped.

    Assumes the caller holds _RENDER_GATE; both callers do."""
    v = voice(vid)
    # 1+2 ── seed shaping and synthesis, or the cached take if neither changed
    key = _synth_key(vid, text, p)
    raw = _cache_get(vid, key)
    reused = bool(raw)
    if raw:
        log('re-using the cached take — only the post chain changed')
    else:
        ref = v['seed']
        chain = seed_chain(p)
        if len(chain) > 1:
            shaped = os.path.join(work, 'seed_shaped.wav')
            log(f'shaping seed: k={p["seed_k"]:.3f} m={p["seed_m"]:.3f}')
            if _apply(ref, shaped, chain, _SEED_SR) is None:
                raise RuntimeError('seed shaping failed (ffmpeg)')
            ref = shaped
            sm = measure(shaped)
            if on_seed:
                on_seed(sm, f'run/{vid}/{os.path.basename(work)}/seed_shaped.wav')
            if sm.get('available'):
                log(f'shaped seed: F0 {sm["f0_hz"]} Hz · VTL {sm["vtl_cm"]} cm')
        raw = os.path.join(work, 'raw.wav')
        log(f'synthesising {len(text.split())} words on {p["engine"]}…')
        if synth(text, ref, raw, p, log) is None:
            raise RuntimeError(f'{p["engine"]} produced no audio')
        raw = _cache_put(vid, key, raw)

    return _finish_take(raw, p, work, log), reused


def _finish_take(raw: str, p: dict, work: str, log) -> str:
    """Post chain + loudness: the CPU half, from a raw synthesis to a take.

    Split out from _produce_take so the batched bake path can share it VERBATIM.
    The batch differs only in how the raw wav is produced — one worker
    invocation for many lines instead of one each — and a raw wav is a raw wav.
    Everything after it must stay one implementation, or a pre-rendered take
    stops being the thing pressing Render would have given you."""
    # 3 ── post chain
    shaped_out = os.path.join(work, 'shaped.wav')
    rc = render_chain(p)
    if len(rc) > 1:
        log('post chain: ' + ' → '.join(f.split('=')[0] for f in rc[1:]))
    if _apply(raw, shaped_out, rc, _SR) is None:
        raise RuntimeError('post chain failed (ffmpeg)')

    # 4 ── loudness (two-pass; single-pass AGC would eat the pauses)
    final = os.path.join(work, 'preview.wav')
    try:
        from zyg_workflows import audio_mix

        norm = audio_mix.loudnorm_two_pass(shaped_out, final, i=float(p['lufs']), tp=float(p['tp']))
    except Exception as e:
        log(f'loudnorm unavailable ({e!r}) — serving the unnormalised take')
        norm = None
    if not norm:
        shutil.copyfile(shaped_out, final)
    else:
        log(f'loudness: {norm.get("normalization_type", "?")} to {p["lufs"]:g} LUFS / {p["tp"]:g} dBTP')

    # 5 ── the content credential, on whichever of the two paths produced it:
    # a take served unnormalised is still a take that shipped.
    _seal.seal(final, pipeline='voice_studio', run_id=os.path.basename(work), log_fn=log)
    return final


def _render_worker(jid: str):
    j = job(jid)
    vid, text, p = j['voice'], j['text'], j['params']
    v = voice(vid)
    log = lambda m: _job_log(jid, m)  # noqa: E731 — terse on purpose
    work = os.path.join(RENDER_ROOT, vid, jid)
    acquired = False
    try:
        os.makedirs(work, exist_ok=True)
        _sweep_old_renders()
        # Announce BEFORE queueing so the background batches stand aside — see
        # _gate_want. Released as soon as the gate is held, not when the render
        # finishes: the batch only needs to know someone is waiting.
        _gate_want(+1)
        try:
            if not _RENDER_GATE.acquire(blocking=False):
                _job_set(jid, state='queued')
                log('waiting for the engine — one render at a time')
                _RENDER_GATE.acquire()
        finally:
            _gate_want(-1)
        acquired = True
        # Sweeping a knob with auto-render armed can queue a dozen jobs behind one
        # 12 s synthesis. Only the newest ask still matters — the operator is not
        # waiting on the take from four knob positions ago, and rendering it would
        # just delay the one they ARE waiting for.
        if _LATEST.get(vid) != jid:
            _job_set(jid, state='superseded', finished=time.time())
            log('superseded by a newer render')
            return
        _job_set(jid, state='running')

        final, reused = _produce_take(
            vid, text, p, work, log, on_seed=lambda sm, rel: _job_set(jid, seed_metrics=sm, seed_wav=rel)
        )
        _job_set(jid, reused=reused)

        # 5 ── publish the audio BEFORE measuring it.
        # Praat costs ~1.3 s — more than the entire ffmpeg chain — and holding the
        # wav back for it would put that on every knob twist. The take is playable
        # the moment it exists; the meters catch up a beat later and the UI keeps
        # polling until 'measuring' clears.
        _job_set(jid, state='done', wav=f'run/{vid}/{jid}/preview.wav', measuring=True, finished=time.time())
        _RENDER_GATE.release()
        acquired = False
        met = measure(final, age_class=v.get('age_class', ''), identity_ref=v.get('identity_ref', ''))
        if met.get('available'):
            log(
                f'render: F0 {met["f0_hz"]} Hz · VTL {met["vtl_cm"]} cm'
                + (f' · {met["age"]["status"]} {v["age_class"]}' if met.get('age') else '')
            )
        else:
            log('voice measurement unavailable — meters stay blank, the render is fine')
        _job_set(jid, metrics=met, measuring=False)
        # Park the finished take so this exact (text, params) never needs the
        # engine again — the same tier the pre-render pass fills. A hand-tuned
        # render therefore warms the cache too, not just the batch button.
        _take_put(vid, text, p, final, met)
    except Exception as e:
        _job_set(jid, state='error', error=str(e)[:400], finished=time.time())
        _job_log(jid, f'FAILED: {e}')
    finally:
        if acquired:
            _RENDER_GATE.release()
