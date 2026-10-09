# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""Generation plumbing: the ComfyUI env gate and the VRAM releases.

Moved verbatim out of the old single-file kids_video_service.py (lines 2010-2032, 2065-2347).
"""

from __future__ import annotations

import os
import re
import time

from zyg_workflows.kids_video_service.constants import (
    CARTOON_MIN,
    CFG,
    MODEL_FAMILY,
    RENDER_H,
    RENDER_W,
    STEPS,
    _OLLAMA,
    _log_noop,
    _zyg_log,
    fast_unet,
)
from zyg_workflows.kids_video_service.gates import (
    CARTOON_NEG,
    CARTOON_POS,
    _CAPTION_BAIT,
    _CLIP,
    _NO_TEXT,
    _clip,
    reads_text,
)
from zyg_workflows.kids_video_service.motifs import (
    NEGATIVE,
)


# ── Generation ───────────────────────────────────────────────────────────────


def _enable_comfy():
    """Make this thread see the same ComfyUI the dashboard sees.

    ``_comfy_client.is_enabled()`` reads ZYG_USE_COMFYUI, which nothing sets in
    the shell.  The GUI gets it from ``vram_manager._ensure_comfy_offload_env``,
    and the obvious move is to call that — but vram_manager imports
    crewai_web_gui, so from a CLI or any worker that has not already loaded the
    dashboard, "make sure the env is set" would import ten thousand lines of
    Flask app (and fail on a circular import on the way).  That helper's entire
    body is the two ``setdefault`` calls below, gated on the server answering,
    so it is repeated here instead of imported.  Same gate, no side effects.
    """
    try:
        from zyg_workflows import _comfy_client as _cc

        if _cc.server_reachable():
            os.environ.setdefault('ZYG_COMFY_PRIMARY', '1')
            os.environ.setdefault('ZYG_USE_COMFYUI', '1')
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('comfy reachability probe skipped, env left as it is: %s', _exc)


def release_ollama(log_fn=None, why="the storyboard is written, the GPU is the pictures' now"):
    """Unload the storyboard LLM before the pictures start.

    The idea batches are the ONLY thing this leg wants from ollama, and they all
    happen before the first render — but the request carries ``keep_alive: 2m``
    so the batches do not each pay a model load, and qwen3.5:9b is **8,296 MiB**
    of the card (measured).  Fifty renders then run alongside a model with
    nothing left to do.  There is 49 GiB here so it fits, but it is the same
    contention that cost pipeline_remixai a stage: freeing it costs nothing,
    because nothing asks ollama for anything else in this leg.

    Uses ollama's own ``keep_alive: 0`` (the shape
    `character_photo_analysis_service.evict_ollama_model` uses) rather than
    importing vram_manager, which drags in the whole Flask app.
    """
    log_fn = log_fn or _log_noop
    try:
        import json as _j
        import urllib.request as _ur

        from zyg_workflows.net import safe_urlopen as _safe_urlopen

        with _safe_urlopen(f'{_OLLAMA}/api/ps', timeout=5) as r:
            loaded = _j.loads(r.read().decode('utf-8')).get('models') or []
        names = [m.get('name') or m.get('model') for m in loaded]
        names = [n for n in names if n]
        if not names:
            return []
        mb = sum(int(m.get('size_vram') or 0) for m in loaded) // (1024 * 1024)
        for n in names:
            # safe_urlopen takes a bare URL and this POST needs headers, so the same
            # scheme check is applied to the composed Request instead.
            req = _ur.Request(  # noqa: S310  scheme checked on the next line
                f'{_OLLAMA}/api/generate',
                data=_j.dumps({'model': n, 'prompt': ' ', 'stream': False, 'keep_alive': 0}).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            if req.type not in ('http', 'https'):
                raise ValueError(f'refusing to open a {req.type!r} URL: {_OLLAMA!r}')
            with _ur.urlopen(req, timeout=30):  # noqa: S310  scheme validated above  # nosec B310
                pass
        log_fn(f'vram: unloaded {len(names)} ollama model(s) (~{mb} MiB) — {why}')
        return names
    except Exception as e:  # noqa: BLE001 — never fail a run
        log_fn(f'vram: ollama unload skipped ({type(e).__name__})')
        return []


def release_comfy_vram(log_fn=None, wait_s=None):
    """Give ComfyUI's VRAM back when this leg is finished with it.

    THIS MUST NOT GO THROUGH ``clear_vram_between_slots``, and the reason is a
    defect that shipped: the root ``.env`` sets ``ZYG_COMFY_KEEP_LOADED=1`` (so
    the FLUX unet stays resident across the character pipelines), and both
    ``_comfy_client.release_memory`` AND ``vram_manager``'s idle sweeper honour
    that flag by doing nothing.  This leg's ``finally`` restored the flag to its
    previous value — which on this box is ``1`` — and then asked for a release
    that was silently skipped.  Measured after a finished run: **25,022 MiB still
    held, eighteen minutes later**, with no line in the log to say so, because
    the call was made with ``log_fn=lambda m: None``.  Two mistakes in one place:
    a release that could not work, and a release nobody could see fail.

    ``comfy_offload.comfy_free`` posts ``/free`` directly and polls ComfyUI's own
    PID until the memory actually appears — it does not consult the keep-loaded
    policy, which is exactly why ``pipeline_remixai`` uses it for the same job.

    MULTI-TENANT SAFE.  :8188 is shared.  If ComfyUI is sampling for somebody
    else this waits for them (bounded), and if they are still going it leaves
    them alone and says so rather than yanking VRAM out from under a live
    render.  Returns a dict for the manifest — including the failure cases,
    because "the video shipped and the GPU is still full" is a thing the record
    has to be able to say.
    """
    log_fn = log_fn or _log_noop
    wait_s = float(wait_s if wait_s is not None else os.environ.get('ZYG_KIDSVIDEO_VRAM_WAIT_S', '120'))
    out = {'released': False, 'before_mb': None, 'after_mb': None, 'reason': ''}
    # THE .env POLICY IS "keep loaded BETWEEN generations", and this leg honours
    # it: the weights stay resident for all fifty renders, which is the whole 6x.
    # What it does not mean is "hold 16-25 GiB forever after the last one" — the
    # song is finished, nothing else in the run wants klein, and the idle sweeper
    # is switched off by that same flag, so if this leg does not give the card
    # back nothing will. ZYG_KIDSVIDEO_KEEP_VRAM=1 for anyone queueing songs
    # back to back who would rather pay the memory than the reload.
    if os.environ.get('ZYG_KIDSVIDEO_KEEP_VRAM', '').strip().lower() in ('1', 'true', 'yes', 'on'):
        out['reason'] = 'ZYG_KIDSVIDEO_KEEP_VRAM=1 — residency kept on request'
        log_fn(f'vram: not released — {out["reason"]}')
        return out
    try:
        from zyg_workflows import comfy_offload as CO
    except Exception as e:  # noqa: BLE001
        out['reason'] = f'comfy_offload unavailable ({type(e).__name__})'
        log_fn(f'vram: NOT released — {out["reason"]}')
        return out
    try:
        pid = CO.comfy_server_pid()
        out['before_mb'] = CO._gpu_used_mb_by_pid(pid) if pid else 0
        deadline = time.time() + wait_s
        waited = False
        while CO.comfy_is_sampling() and time.time() < deadline:
            if not waited:
                log_fn(
                    f'vram: ComfyUI is sampling for another client — waiting '
                    f'up to {wait_s:.0f}s rather than interrupting it'
                )
                waited = True
            time.sleep(5)
        if CO.comfy_is_sampling():
            out['reason'] = 'another client is still rendering — left alone'
            log_fn(f'vram: NOT released — {out["reason"]} ({out["before_mb"]} MiB still held)')
            return out
        ok = CO.comfy_free(unload_models=True, log_fn=lambda m: None)
        out['after_mb'] = CO._gpu_used_mb_by_pid(pid) if pid else 0
        out['released'] = bool(ok)
        if ok:
            log_fn(f'vram: released — ComfyUI {out["before_mb"]} → {out["after_mb"]} MiB')
        else:
            out['reason'] = 'comfy_free did not confirm the drop'
            log_fn(f'vram: release NOT confirmed — ComfyUI {out["before_mb"]} → {out["after_mb"]} MiB')
    except Exception as e:  # noqa: BLE001 — never fail a
        out['reason'] = f'{type(e).__name__}: {e}'  # delivered video over this
        log_fn(f'vram: release failed — {out["reason"]}')
    return out


def release_clip(log_fn=None):
    """Drop the CLIP scorer off the GPU once the frames have been measured.

    ``_clip`` caches a closure over a CUDA-resident ViT-B-32 so the fifty-odd
    per-frame scorings do not each pay a model load.  Cached forever, that is
    ~1.6 GiB of the GUI process sitting on the card for the rest of its life —
    measured on this box after a finished run.  The model is moved back to the
    CPU rather than discarded, so a later song re-uses it (a re-upload costs
    under a second) instead of re-reading it from disk.
    """
    log_fn = log_fn or _log_noop
    if _CLIP.get('model') is None:
        return False
    try:
        import torch

        _CLIP['model'].to('cpu')
        _CLIP['device'] = 'cpu'
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        log_fn('vram: CLIP scorer moved off the GPU')
        return True
    except Exception as e:  # noqa: BLE001
        log_fn(f'vram: CLIP not released ({type(e).__name__})')
        return False


def _repair_frames(slots, paths, prompts, C, rng, info, log_fn):
    """Re-render, once, every generated frame that fails a content check.

    Two failure modes, one pass, because the remedy is the same: a fresh seed and
    a prompt with the invitation removed.

      * LETTERING baked into the picture. Measured: 2 of 53 frames on the first
        illustrated song, both invited by prompts saying the train "says" or
        "sings" something — a negative prompt does not beat a positive that asks
        for a caption, so `_CAPTION_BAIT` strips the invitation.
      * A frame that fails the CARTOON contrast. On the distilled model that was
        1 of 49, and looking at it mattered: it was a perfectly good flat cartoon
        seed on a mound of soil, scored 0.676 because a near-empty frame gives
        CLIP little picture-book to read. So this is not only a "the model went
        photoreal" guard — it is also a second draw when a sparse composition
        lands badly, which is the honest description of what it does.

    THE RETRY MUST STRICTLY IMPROVE OR IT IS DISCARDED, so this pass can never
    leave a song worse than not running it. It is affordable at all because
    generation went from 13.5 s an image to 2.2 s: a handful of retries used to
    cost a minute and now costs seconds.
    """
    for k in (
        'text_flagged',
        'text_repaired',
        'text_remaining',
        'cartoon_flagged',
        'cartoon_repaired',
        'cartoon_remaining',
        'retries',
    ):
        info.setdefault(k, 0)
    contrast = _clip()

    def _score(path):
        """(lettering regions, cartoon score). None cartoon = could not measure,
        which must not be treated as a failure."""
        n = len(reads_text(path))
        c = None
        if contrast is not None:
            try:
                c = contrast(path, CARTOON_POS, CARTOON_NEG)
            except Exception:  # noqa: BLE001
                c = None
        return n, c

    flagged = []
    for s, p in zip(slots, paths):
        if s.get('source_render') != 'generated' or not os.path.isfile(p):
            continue
        n, c = _score(p)
        bad_text = n > 0
        bad_look = c is not None and c < CARTOON_MIN
        if bad_text:
            info['text_flagged'] += 1
        if bad_look:
            info['cartoon_flagged'] += 1
        if bad_text or bad_look:
            flagged.append((s, p, n, c, bad_text, bad_look))
    if not flagged:
        return
    log_fn(
        f'repair: {len(flagged)} frame(s) flagged '
        f'({info["text_flagged"]} lettered, {info["cartoon_flagged"]} below '
        f'the cartoon gate) — re-rendering them once'
    )
    for s, p, n0, c0, bad_text, bad_look in flagged:
        base = prompts.get(s['i'], '') or ''
        if bad_text:
            base = re.sub(r'\s{2,}', ' ', _CAPTION_BAIT.sub('', base)).strip(' ,')
        if not base:
            continue
        alt = p + '.retry.png'
        info['retries'] += 1
        try:
            ok, _b = C.generate_still(
                alt,
                f'{base}, {_NO_TEXT}',
                width=RENDER_W,
                height=RENDER_H,
                steps=STEPS,
                cfg=CFG,
                seed=rng.randrange(1, 2**31 - 1),
                model_family=MODEL_FAMILY,
                skip_qa=True,
                prompt_finalized=True,
                extra_negative=NEGATIVE,
                solo_subject=False,
                human_subject=False,
                force_unet=fast_unet(),
                clear_vram_after=False,
                log_fn=lambda m: None,
            )
        except Exception:  # noqa: BLE001
            ok = False
        n1, c1 = _score(alt) if (ok and os.path.isfile(alt)) else (n0 + 1, None)
        # Lettering first (it is the harder defect), then the cartoon score.
        better = (n1 < n0) or (n1 == n0 and c1 is not None and c0 is not None and c1 > c0)
        if better:
            try:
                os.replace(alt, p)
                s['source_render'] = 'generated_retry'
                if bad_text:
                    info['text_repaired'] += 1
                if bad_look:
                    info['cartoon_repaired'] += 1
            except OSError:
                better = False
        else:
            try:
                os.remove(alt)
            except OSError as _exc:
                _zyg_log.debug('losing repair candidate %s removal skipped: %s', alt, _exc)
        # What is STILL wrong after the attempt — read off the file that survived.
        n2, c2 = _score(p)
        if n2:
            info['text_remaining'] += 1
        if c2 is not None and c2 < CARTOON_MIN:
            info['cartoon_remaining'] += 1
    # 'improved', not 'fixed'. A retry is accepted when it scores BETTER, which
    # is not the same as clearing the gate — the first fast-mode run logged
    # "1/1 fixed (1 left)" and the two halves of that sentence were both true.
    log_fn(
        f'repair: {info["retries"]} retried · lettering '
        f'{info["text_repaired"]}/{info["text_flagged"]} improved, '
        f'{info["text_remaining"]} still lettered · cartoon '
        f'{info["cartoon_repaired"]}/{info["cartoon_flagged"]} improved, '
        f'{info["cartoon_remaining"]} still under the gate'
    )
