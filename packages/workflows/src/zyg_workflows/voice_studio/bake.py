# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_studio.bake — the library bake.

Moved verbatim from voice_studio.py lines 2437-2907 (2026-10-06 split).
"""

from __future__ import annotations

from zyg_workflows.bin import exe
import json
import logging as _zyg_logging
import os
import shutil
import subprocess
import threading
import time

from zyg_workflows.voice_studio.constants import (
    DEFAULT_LINES,
    MAX_PREVIEW_CHARS,
    RENDER_ROOT,
    VOICES,
    _SEED_SR,
)
from zyg_workflows.voice_studio.policy import (
    voice,
)
from zyg_workflows.voice_studio.params import (
    defaults,
)
from zyg_workflows.voice_studio.synthesis import (
    _apply,
    measure,
    seed_chain,
    synth,
    synth_batch,
)
from zyg_workflows.voice_studio.jobs import (
    _RENDER_GATE,
    _cache_get,
    _cache_put,
    _finish_take,
    _produce_take,
    _synth_key,
    _take_put,
    _yield_to_interactive,
    take_cached,
    take_has,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.voice_studio')


# ─────────────────────────────────────────────────────── the library bake
# "Pre-render every sentence for every voice, so clicking a voice never means
# clicking Render." 244 voices × the lines in the line list, deduplicated — 2,683
# takes, about 3.5 GB. Four things make that a background job rather than a wall:
#
#   PHASE A IS BREADTH FIRST. The line each voice OPENS on, for every voice,
#   before any voice gets a second line. So the whole picker answers instantly
#   after roughly an hour, instead of the first forty voices being perfect and
#   voice 41 onward still blank ten hours in. Depth-first would finish at exactly
#   the same time and be useless for most of it.
#
#   PHASE B IS BATCHED, and that is where the time went. Profiling one take at 1 s
#   resolution showed the GPU at 93 % for one or two seconds out of twelve; the
#   rest was a fresh Chatterbox process importing torch and loading weights —
#   2,683 times. Phase B hands a voice's whole remaining line list to ONE worker
#   invocation, so the model loads once per VOICE instead of once per TAKE.
#   Measured 2.0x on three lines, and more on ten. Phase A cannot be batched (its
#   whole point is one line each across all voices) and does not need to be: it is
#   244 takes, not 2,439.
#
#   IT YIELDS. Every take, and every batch, waits on _yield_to_interactive first,
#   so pressing Render always beats the bake to the engine. The gate is released
#   before the CPU half of a batch, so post-processing overlaps with whatever asked
#   for the engine next instead of blocking it.
#
#   RESUME IS FREE, and is not bookkeeping. The plan is recomputed from the voice
#   registry and every entry already in the take cache is skipped, so a restart,
#   a crash or a stop-and-start mid-way costs nothing and cannot double-render.
#   The state file only records whether it was RUNNING, so it can pick itself
#   back up; it is never trusted for what is done.
#
# Rendered at the DEFAULT knob positions, which is exactly what vsPickVoice loads
# when a voice is clicked. A twisted knob is a different cache key and still costs
# a render — correctly, because it is a different sound.
_BAKE_STATE = os.path.join(RENDER_ROOT, '_bake.json')
# Lines per worker invocation in phase B. The cap is about RESPONSIVENESS, not
# memory: a batch cannot be interrupted, so it is the longest an interactive
# render can be made to wait. Twelve lines is ~25 s worst case, against ~15 s
# before batching — and no voice has more than eleven, so in practice a voice is
# always exactly one batch.
_BAKE_BATCH = 12
# Post-processing is ffmpeg + ffmpeg + Praat per take, all separate processes and
# all CPU, so a batch's worth can run at once instead of serially. Four, not
# twenty: the box already carries a 20-of-24-core ceiling, and this has to leave
# room for the render pipelines it is deliberately staying out of the way of.
_BAKE_POST_WORKERS = 4
# The bake runs for hours on the same GPU the render pipelines want, and
# _RENDER_GATE only serialises voice_studio's own jobs — it knows nothing about
# ComfyUI, Wan or a character run. vram_manager._gpu_work_active() is no help
# either: it reads in-process job dicts that live in the :5000 Flask GUI, so from
# this process it would answer False forever.
#
# So the bake gates on the two signals that actually CROSS processes: the shared
# maintenance flag every briefing pipeline already honours, and free VRAM. Idle on
# this box is ~2 GB used of 50.9; a 10 GB floor means "something substantial has
# the card, stand aside". Both fail OPEN — if nvidia-smi cannot be read we render
# rather than stall forever on a probe that is broken.
# Overridable by $ZYG_MAINT_FLAG; the default is the cross-process path the briefing
# pipelines already write. This module only ever READS it (isfile + getmtime) and never
# creates, writes or parses it, so the shared-directory risk S108/B108 flags does not apply.
_MAINT_FLAG = os.environ.get('ZYG_MAINT_FLAG') or '/var/tmp/zygomatic-maintenance.flag'  # noqa: S108  read-only cross-process flag, see the comment above  # nosec B108
_BAKE_VRAM_FLOOR_GB = 10.0


def _bake_blocked() -> str:
    """'' when the bake may render, else why it is standing aside."""
    try:
        if os.path.isfile(_MAINT_FLAG) and time.time() - os.path.getmtime(_MAINT_FLAG) < 900:
            return 'maintenance flag set'
    except OSError as _exc:
        _zyg_log.debug('maintenance flag %s not readable, treated as absent: %s', _MAINT_FLAG, _exc)
    try:
        r = subprocess.run(
            [exe('nvidia-smi'), '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
            capture_output=True,
            timeout=8,
            text=True,
        )
        free_gb = float(r.stdout.strip().splitlines()[0].strip()) / 1024.0
        if free_gb < _BAKE_VRAM_FLOOR_GB:
            return f'GPU busy — {free_gb:.1f} GB free'
    except Exception as _exc:  # noqa: BLE001 — fail open, see above
        _zyg_log.debug('free-vram probe failed, letting the bake proceed: %s', _exc)
    return ''


_BAKE = {
    'running': False,
    'stop': False,
    'done': 0,
    'total': 0,
    'skipped': 0,
    'failed': 0,
    'voice': '',
    'line': '',
    'started': 0.0,
    'secs': [],
    'finished': 0.0,
    'log': [],
    'held': '',
}
_BAKE_LOCK = threading.Lock()


def bake_lines(vid: str) -> list:
    """Every distinct sentence this voice should have on tap, opening line first.

    Deduplicated by TEXT, not by id: Abel's default text, the shared epigraph and
    his own '1672 opening' read are the same 135 characters, and rendering them
    three times would buy three identical files under three names."""
    v = voice(vid)
    if not v:
        return []
    out, seen = [], set()

    def _add(lid, label, text):
        t = (text or '').strip()[:MAX_PREVIEW_CHARS]
        if t and t not in seen:
            seen.add(t)
            out.append({'id': lid, 'label': label, 'text': t})

    _add('default', 'opening line', v.get('default_text', ''))
    for line in DEFAULT_LINES:
        _add(line['id'], line['label'], line['text'])
    for line in v.get('test_lines') or []:
        _add(line['id'], line['label'], line['text'])
    return out


def bake_plan() -> list:
    """[(vid, label, text)] in breadth-first order — see the section comment."""
    per = [(vid, bake_lines(vid)) for vid in VOICES]
    depth = max((len(ls) for _v, ls in per), default=0)
    plan = []
    for i in range(depth):
        for vid, lines in per:
            if i < len(lines):
                plan.append((vid, lines[i]['label'], lines[i]['text']))
    return plan


def _bake_read() -> dict:
    try:
        with open(_BAKE_STATE, encoding='utf-8') as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def _bake_write(running: bool):
    try:
        os.makedirs(RENDER_ROOT, exist_ok=True)
        tmp = _BAKE_STATE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'running': bool(running), 'at': time.strftime('%Y-%m-%d %H:%M:%S')}, f, indent=1)
        os.replace(tmp, _BAKE_STATE)
    except OSError as _exc:
        _zyg_log.warning('bake state %s not written, the tab may show a stale running flag: %s', _BAKE_STATE, _exc)


def _bake_log(msg: str):
    with _BAKE_LOCK:
        _BAKE['log'].append(f'{time.strftime("%H:%M:%S")} {msg}')
        _BAKE['log'] = _BAKE['log'][-60:]
    _zyg_log.info(f'[VOICE-BAKE] {msg}')


def bake_status() -> dict:
    with _BAKE_LOCK:
        s = dict(_BAKE)
    secs = s.pop('secs', []) or []
    left = max(0, s['total'] - s['done'])
    # ETA off the last RENDERS only — see _bake_tick for why skips are excluded.
    # A window rather than a lifetime average, because phase A (one model load
    # per take) and phase B (one per voice) cost several times different, and a
    # blended rate would be wrong in both phases.
    per = (sum(secs) / len(secs)) if secs else 0.0
    s['per_take_s'] = round(per, 1)
    s['eta_s'] = int(left * per) if per else 0
    s['left'] = left
    s['pct'] = round(s['done'] / s['total'] * 100, 1) if s['total'] else 0.0
    return s


_LIB_CACHE = {'at': 0.0, 'voices': {}, 'n': 0}


def library_status() -> dict:
    """Bake progress plus which voices already answer instantly.

    `voices` is only the OPENING line per voice — that is the ⚡ in the picker,
    and it is the honest claim: clicking that voice plays without a render. The
    per-voice count of ALL its lines is what prerender_state answers, per voice,
    when you are actually on one."""
    s = bake_status()
    now = time.monotonic()
    if now - _LIB_CACHE['at'] > 5.0:
        p = defaults()
        got = {}
        for vid, _v in VOICES.items():
            lines = bake_lines(vid)
            if lines and take_has(vid, lines[0]['text'], p):
                got[vid] = 1
        _LIB_CACHE.update(at=now, voices=got, n=len(got))
    s['voices'] = _LIB_CACHE['voices']
    s['voices_ready'] = _LIB_CACHE['n']
    s['voices_total'] = len(VOICES)
    return s


def start_bake() -> dict:
    with _BAKE_LOCK:
        if _BAKE['running']:
            return bake_status()
        _BAKE.update(
            running=True,
            stop=False,
            done=0,
            total=0,
            skipped=0,
            failed=0,
            voice='',
            line='',
            started=time.time(),
            secs=[],
            finished=0.0,
            log=[],
            held='',
        )
    _bake_write(True)
    threading.Thread(target=_bake_worker, daemon=True).start()
    return bake_status()


def stop_bake() -> bool:
    with _BAKE_LOCK:
        if not _BAKE['running']:
            return False
        _BAKE['stop'] = True
    _bake_write(False)
    _bake_log('stopping after the current take…')
    return True


def bake_eta() -> dict:
    """What is left, and roughly how long — phase A and phase B cost very
    different amounts per take, so quoting one blended rate would be wrong in
    both directions. Read-only; used by the CLI check and by tests."""
    p = defaults()
    a = b = 0
    for vid in VOICES:
        lines = bake_lines(vid)
        if not lines:
            continue
        if not take_has(vid, lines[0]['text'], p):
            a += 1
        b += sum(1 for ln in lines[1:] if not take_has(vid, ln['text'], p))
    return {'phase_a': a, 'phase_b': b, 'left': a + b}


def _bake_stopping() -> bool:
    with _BAKE_LOCK:
        return bool(_BAKE['stop'])


def _bake_wait_turn() -> bool:
    """Stand aside for an interactive render and for the render pipelines.
    False if the bake was stopped while waiting."""
    _yield_to_interactive(_bake_stopping)
    held = _bake_blocked()
    if held:
        with _BAKE_LOCK:
            _BAKE['held'] = held
        _bake_log(f'holding — {held}')
        while _bake_blocked() and not _bake_stopping():
            time.sleep(30)
        with _BAKE_LOCK:
            _BAKE['held'] = ''
        if not _bake_stopping():
            _bake_log('resuming — the GPU is free again')
    return not _bake_stopping()


def _bake_tick(n: int, dt: float):
    with _BAKE_LOCK:
        _BAKE['done'] += n
        # Per-TAKE seconds even when a batch produced several, so the ETA stays
        # in the same unit as the count it is multiplying.
        #
        # dt == 0 means a cache SKIP, and those must not enter the rate window:
        # a resumed bake opens with hundreds of instant skips, which dragged the
        # average to 2.9 s and quoted two hours for work that had not started.
        # An ETA is only worth printing if it is built from the cost of the work
        # actually remaining.
        if dt > 0:
            _BAKE['secs'] = (_BAKE['secs'] + [dt / max(1, n)] * min(n, 6))[-25:]
        done, tot = _BAKE['done'], _BAKE['total']
    if done % 25 < n:
        st = bake_status()
        _bake_log(
            f'{done}/{tot} ({st["pct"]}%) · {st["per_take_s"]}s a take · '
            f'~{st["eta_s"] // 3600}h{st["eta_s"] % 3600 // 60:02d}m left'
        )


def _bake_one(vid: str, v: dict, label: str, text: str, p: dict) -> bool:
    """One take, gate held for the whole thing. Phase A's unit."""
    work = os.path.join(RENDER_ROOT, vid, f'_bake_{int(time.time() * 1000):x}')
    _RENDER_GATE.acquire()
    try:
        os.makedirs(work, exist_ok=True)
        final, _reused = _produce_take(vid, text, p, work, lambda _m: None)
        met = measure(final, age_class=v.get('age_class', ''), identity_ref=v.get('identity_ref', ''))
        _take_put(vid, text, p, final, met)
        return True
    except Exception as e:  # noqa: BLE001 — one bad voice must not end the bake
        _bake_log(f'{vid} / {label} FAILED: {str(e)[:140]}')
        return False
    finally:
        _RENDER_GATE.release()
        shutil.rmtree(work, ignore_errors=True)


def _bake_batch(vid: str, v: dict, lines: list, p: dict) -> int:
    """Many takes for ONE voice through one worker invocation. Phase B's unit.

    The gate covers the GPU half only. Post-processing is ffmpeg and Praat — all
    CPU, all separate processes — so it is released first and the batch finishes
    alongside whatever wanted the engine next, instead of making it wait."""
    work = os.path.join(RENDER_ROOT, vid, f'_bake_{int(time.time() * 1000):x}')
    made = []
    _RENDER_GATE.acquire()
    try:
        os.makedirs(work, exist_ok=True)
        # Seed shaping is per VOICE, not per line, so it happens once here — the
        # same chain _produce_take runs, against the same defaults.
        ref, chain = v['seed'], seed_chain(p)
        if len(chain) > 1:
            shaped = os.path.join(work, 'seed_shaped.wav')
            if _apply(ref, shaped, chain, _SEED_SR) is None:
                raise RuntimeError('seed shaping failed (ffmpeg)')
            ref = shaped
        items = []
        for i, ln in enumerate(lines):
            key = _synth_key(vid, ln['text'], p)
            hit = _cache_get(vid, key)
            if hit:  # a hand render already synthesised this
                made.append((ln, hit))
                continue
            items.append({'text': ln['text'], 'out': os.path.join(work, f'raw_{i:02d}.wav'), 'line': ln, 'key': key})
        if items:
            # synth_batch is Chatterbox-only and returns 0 for IndexTTS-2; a
            # bake must still fill the cache, so render those one line at a
            # time through the same synth() a click would run.
            if not synth_batch(items, ref, p, lambda _m: None) and p.get('engine') != 'chatterbox':
                for it in items:
                    synth(it['text'], ref, it['out'], p, lambda _m: None)
            for it in items:
                if os.path.isfile(it['out']) and os.path.getsize(it['out']) > 44:
                    made.append((it['line'], _cache_put(vid, it['key'], it['out'])))
    except Exception as e:  # noqa: BLE001
        _bake_log(f'{vid} batch FAILED: {str(e)[:140]}')
    finally:
        _RENDER_GATE.release()

    ok = 0
    try:
        from concurrent.futures import ThreadPoolExecutor

        def _finish(pair):
            ln, raw = pair
            sub = os.path.join(work, 'post_' + ln['id'])
            os.makedirs(sub, exist_ok=True)
            final = _finish_take(raw, p, sub, lambda _m: None)
            met = measure(final, age_class=v.get('age_class', ''), identity_ref=v.get('identity_ref', ''))
            _take_put(vid, ln['text'], p, final, met)

        with ThreadPoolExecutor(max_workers=_BAKE_POST_WORKERS) as pool:
            for pair, fut in [(m, pool.submit(_finish, m)) for m in made]:
                try:
                    fut.result()
                    ok += 1
                except Exception as e:  # noqa: BLE001
                    _bake_log(f'{vid} / {pair[0]["label"]} post FAILED: {str(e)[:120]}')
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return ok


def _bake_worker():
    p = defaults()
    plan = bake_plan()
    with _BAKE_LOCK:
        _BAKE['total'] = len(plan)
    _bake_log(f'{len(plan)} takes over {len(VOICES)} voices')

    # ── phase A: the opening line of every voice, breadth first ──────────────
    _bake_log(f'phase A — the opening line of all {len(VOICES)} voices')
    for vid in VOICES:
        if _bake_stopping():
            break
        v, lines = voice(vid), bake_lines(vid)
        if not (v and lines and os.path.isfile(v['seed'])):
            _bake_tick(1, 0.0)
            continue
        ln = lines[0]
        if take_cached(vid, ln['text'], p):
            with _BAKE_LOCK:
                _BAKE['skipped'] += 1
            _bake_tick(1, 0.0)
            continue
        with _BAKE_LOCK:
            _BAKE['voice'], _BAKE['line'] = v.get('name', vid), ln['label']
        if not _bake_wait_turn():
            break
        t0 = time.time()
        if not _bake_one(vid, v, ln['label'], ln['text'], p):
            with _BAKE_LOCK:
                _BAKE['failed'] += 1
        _bake_tick(1, time.time() - t0)

    # ── phase B: everything else, one worker invocation per voice ────────────
    if not _bake_stopping():
        _bake_log('phase B — remaining lines, batched (model loads once per voice, not once per take)')
    for vid in VOICES:
        if _bake_stopping():
            break
        v = voice(vid)
        if not (v and os.path.isfile(v['seed'])):
            continue
        todo = [ln for ln in bake_lines(vid)[1:] if not take_cached(vid, ln['text'], p)]
        cached = len(bake_lines(vid)) - 1 - len(todo)
        if cached:
            with _BAKE_LOCK:
                _BAKE['skipped'] += cached
            _bake_tick(cached, 0.0)
        if not todo:
            continue
        for i in range(0, len(todo), _BAKE_BATCH):
            chunk = todo[i : i + _BAKE_BATCH]
            with _BAKE_LOCK:
                _BAKE['voice'] = v.get('name', vid)
                _BAKE['line'] = f'{len(chunk)} lines'
            if not _bake_wait_turn():
                break
            t0 = time.time()
            ok = _bake_batch(vid, v, chunk, p)
            if ok < len(chunk):
                with _BAKE_LOCK:
                    _BAKE['failed'] += len(chunk) - ok
            _bake_tick(len(chunk), time.time() - t0)

    with _BAKE_LOCK:
        stopped, s = _BAKE['stop'], dict(_BAKE)
        _BAKE.update(running=False, stop=False, voice='', line='', finished=time.time())
    _bake_write(False)
    _bake_log(
        ('stopped — ' if stopped else 'complete — ') + f'{s["done"]}/{s["total"]} ({s["skipped"]} already cached, '
        f'{s["failed"]} failed)'
    )


def resume_bake_if_interrupted():
    """Pick a bake back up after a restart. Called once when the module loads:
    the operator asked for the library to BE rendered, so a server bounce in the
    middle of it should not silently leave the job half done."""
    if _bake_read().get('running') and not _BAKE['running']:
        _bake_log('resuming the library bake after a restart')
        start_bake()
