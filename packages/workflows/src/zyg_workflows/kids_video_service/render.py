# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""Rendering the pictures: the klein/HiDream pass and the candidate pick.

Moved verbatim out of the old single-file kids_video_service.py (lines 2625-3132).
"""

from __future__ import annotations

import functools
import os
import random
import time

from zyg_workflows.kids_video_service.cards import (
    _draw_card,
    draw_count_card,
)
from zyg_workflows.kids_video_service.comfy import (
    _enable_comfy,
    _repair_frames,
    release_comfy_vram,
    release_ollama,
)
from zyg_workflows.kids_video_service.constants import (
    CFG,
    MODEL_FAMILY,
    RENDER_H,
    RENDER_W,
    STEPS,
    _FAST,
    _FAST_ACTIVE,
    _SPEED_WARNINGS,
    _log_noop,
    _zyg_log,
    fast_unet,
)
from zyg_workflows.kids_video_service.motifs import (
    NEGATIVE,
    style_for,
)
from zyg_workflows.kids_video_service.render_slots import (
    RenderLeg,
    _copy_reused_frames,
    _new_info,
    _render_slot_loop,
    _screen_candidate,
)
from zyg_workflows.kids_video_service.screen import (
    CANDIDATES,
    SCREEN_ON,
    _SCREEN_RANK,
    screen_frame,
)


class _HiDreamGen:
    """A ``comfy_generation_service`` look-alike over HiDream-O1 on :8189, so the
    render, candidate-pick and repair paths need no second code path.  Only the
    keyword arguments those paths actually use are honoured; the rest are
    accepted and ignored (klein-specific knobs such as ``force_unet``)."""

    backend = 'hidream-o1-dev'

    def __init__(self, LH, log_fn):
        self.LH = LH
        self.log = log_fn

    def is_available(self):
        return self.LH.is_available()

    def generate_still(
        self, out_path, scene_prompt, *, width=1280, height=720, seed=42, extra_negative='', log_fn=None, **_ignored
    ):
        ok = self.LH.hidream_still(
            scene_prompt,
            out_path,
            width=int(width),
            height=int(height),
            seed=int(seed),
            negative=extra_negative or '',
            log_fn=log_fn or self.log,
        )
        return bool(ok), self.backend


def _render_still(leg, slot, path, frame_seed, *, clear=False, prompt=None):
    """Render one frame with the open generator; False (and a log line) when it raised."""
    try:
        ok_, backend_ = leg.gen.generate_still(
            path,
            prompt or leg.prompts[slot['i']],
            width=RENDER_W,
            height=RENDER_H,
            steps=STEPS,
            cfg=CFG,
            seed=frame_seed,
            model_family=MODEL_FAMILY,
            skip_qa=True,
            prompt_finalized=True,
            extra_negative=NEGATIVE,
            solo_subject=False,
            human_subject=False,
            force_unet=fast_unet(),
            clear_vram_after=clear,
            log_fn=lambda m: None,
        )
        leg.info['backend'] = leg.info['backend'] or backend_
        return bool(ok_ and os.path.isfile(path))
    except Exception as e:  # noqa: BLE001 — one bad frame is
        leg.log_fn(
            f'images: slot {slot["i"]} generator raised '  # not a failed video
            f'{type(e).__name__}'
        )
        return False


def _open_generator(info, log_fn, abort):
    """Open the picture generator: `(generator, lease)`.

    HiDream-O1 on :8189 when that is the configured family and its server is
    up (the lease is held for the whole leg), otherwise klein on :8188.
    Neither being available is not an error — every frame is then DRAWN.
    """
    C = None
    _lease = None  # the :8189 GPU lease, held for the whole leg
    if MODEL_FAMILY == 'hidream':
        try:
            from zyg_workflows import ltx_hidream_service as _LH

            if _LH.ensure_up(log_fn=log_fn):
                _lease = _LH.gpu_lease(abort, log_fn=log_fn)
                _lease.__enter__()
                C = _HiDreamGen(_LH, log_fn)
                info.update(
                    {
                        'family': 'hidream',
                        'steps': _LH.HIDREAM_STEPS,
                        'cfg': 1.0,
                        'unet': _LH.HIDREAM_CKPT,
                        'fast': False,
                    }
                )
                log_fn(
                    f'images: HiDream-O1 ({_LH.HIDREAM_CKPT}) on ComfyUI :8189, '
                    f'{_LH.HIDREAM_STEPS} steps, {RENDER_W}x{RENDER_H}'
                )
            else:
                log_fn('images: HiDream server (:8189) unavailable — falling back to klein on :8188')
        except Exception as e:  # noqa: BLE001
            log_fn(f'images: HiDream path unavailable ({type(e).__name__}: {e}) — falling back to klein')
            C = None
    if C is None:
        try:
            from zyg_workflows import comfy_generation_service as _C

            if _C.is_available():
                C = _C
            else:
                log_fn('images: ComfyUI unavailable — every frame will be DRAWN, not generated')
        except Exception as e:  # noqa: BLE001
            log_fn(f'images: generator unavailable ({type(e).__name__}) — drawing instead')
    return C, _lease


def _close_render_leg(leg, prev_keep, lease):
    """Shut the leg down: the screening thread, the candidate directory, the VRAM and the policy."""
    if leg.executor is not None:
        leg.executor.shutdown(wait=False, cancel_futures=True)
    if leg.pool:
        import shutil as _shc

        _shc.rmtree(leg.cdir, ignore_errors=True)
    # Put the ambient policy back exactly as it was — it belongs to everyone
    # else in this process, not to this run.
    if prev_keep is None:
        os.environ.pop('ZYG_COMFY_KEEP_LOADED', None)
    else:
        os.environ['ZYG_COMFY_KEEP_LOADED'] = prev_keep
    if lease is not None:
        try:  # unloads HiDream from :8189, releases the lock
            lease.__exit__(None, None, None)
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.warning('HiDream lease release failed, the :8189 lock may still be held: %s', _exc)
    if leg.gen is not None:
        leg.info['vram'] = release_comfy_vram(log_fn=leg.log_fn)
    if leg.screen:
        release_ollama(log_fn=leg.log_fn, why='the defect screen is finished')


def render_images(slots, brief, out_dir, *, seed=0, log_fn=None, stage_fn=None, should_abort=None, reuse=None):
    """One picture per slot.  Returns (paths, info).

    KEEPING THE MODELS RESIDENT IS THE WHOLE COST STORY.  Measured on this box
    with klein at 20 steps: 63.8 s an image with the default per-slot VRAM
    release, 39.6 s with ``clear_vram_after=False`` alone, and **15.6 s** with
    ``ZYG_COMFY_KEEP_LOADED=1`` as well.  A thirty-picture song is therefore
    eight minutes rather than half an hour.  The residency is released once at
    the end — including on the failure path — so this leg cannot leave the 4B
    unet and its text encoder sitting in VRAM for the next workflow.
    """
    log_fn = log_fn or _log_noop
    abort = should_abort or (lambda: False)
    fdir = os.path.join(out_dir, 'frames')
    os.makedirs(fdir, exist_ok=True)
    style = style_for(brief)
    rng = random.Random((int(seed) * 104729 + 7) & 0xFFFFFFFF)

    info = _new_info(MODEL_FAMILY, STEPS, CFG, fast_unet() or 'resolver default', _FAST_ACTIVE, _FAST, _SPEED_WARNINGS)

    _enable_comfy()
    prev_keep = os.environ.get('ZYG_COMFY_KEEP_LOADED')
    os.environ['ZYG_COMFY_KEEP_LOADED'] = '1'
    C, _lease = _open_generator(info, log_fn, abort)

    leg = RenderLeg(C, info, log_fn, abort, rng, style, fdir, CANDIDATES, SCREEN_ON)
    # Read out of THIS module's namespace, which is what a test patches.
    leg.render = functools.partial(_render_still, leg)
    leg.screen_cand = functools.partial(_screen_candidate, rdir=leg.rdir, screen_frame=screen_frame)
    leg.draw_count_card = draw_count_card
    try:
        _render_slot_loop(leg, slots, reuse)
        if leg.pool:
            _pick_candidates(
                leg.pending,
                leg.paths,
                slots,
                info,
                leg.executor,
                leg.render,
                leg.screen_cand,
                leg.prompts,
                leg.seeds,
                rng,
                fdir,
                leg.cdir,
                leg.xdir,
                abort,
                log_fn,
            )
        _copy_reused_frames(slots, fdir, info)

        # ── Repair.  Without the candidate pool, every generated frame is checked
        # for baked-in lettering and against the cartoon contrast, and the
        # failures get ONE fresh seed. With the pool, the screen already judged
        # every candidate on the same two checks (plus the VLM) and re-seeded
        # any slot left with nothing usable — a second, unscreened retry here
        # could put back exactly what the screen threw out.
        if C is not None and not leg.pool and not abort():
            _repair_frames(slots, leg.paths, leg.prompts, C, rng, info, log_fn)
    finally:
        _close_render_leg(leg, prev_keep, _lease)

    info['seconds'] = round(time.time() - leg.t0, 1)
    info['unique'] = len(leg.made)
    return leg.paths, info


def _pick_candidates(
    pending, paths, slots, info, executor, _render, _screen_cand, prompts, seeds, rng, fdir, cdir, xdir, abort, log_fn
):
    """Choose each pooled slot's picture from its screened candidates.

    Order: healthy > unmeasured > soft (below the cartoon contrast) — never a
    defect. Ties go to the candidate index its counting run already uses (so
    the run keeps one look), then to the higher cartoon score. A slot whose
    candidates were ALL thrown out gets one fresh seed, screened the same way;
    if that is thrown out too, the slot is DRAWN (a plain card, recorded as
    drawn_screen) rather than shipping a defect. Healthy leftovers go to
    frames/excess/f###_c#.png; defects were deleted when they were screened."""
    pl = info['pool']
    t0 = time.time()
    group_pick = {}
    for s in pending:
        cands = []
        for f in s.pop('_cands'):
            try:
                cands.append(f.result() if hasattr(f, 'result') else f)
            except Exception as e:  # noqa: BLE001 — a screen that died
                log_fn(f'screen: slot {s["i"]} screen failed ({type(e).__name__})')
        for cand in cands:
            cand.setdefault(
                'screen', {'verdict': 'unmeasured', 'reasons': [], 'soft': [], 'cartoon': None, 'vlm': 'not screened'}
            )
        usable = [c for c in cands if not c.get('rejected') and os.path.isfile(c['path'])]
        if not usable and not abort():
            pl['reseeded_slots'] += 1
            cp = os.path.join(cdir, f'f{s["i"]:03d}_c{len(cands)}.png')
            fs = rng.randrange(1, 2**31 - 1)
            if _render(s, cp, fs):
                pl['rendered'] += 1
                cand = {'c': len(cands), 'seed': fs, 'path': cp, 'reseed': True}
                cand = _screen_cand(cand) if executor is not None else cand
                cand.setdefault(
                    'screen',
                    {'verdict': 'unmeasured', 'reasons': [], 'soft': [], 'cartoon': None, 'vlm': 'not screened'},
                )
                cands.append(cand)
                if not cand.get('rejected'):
                    usable = [cand]
        gid = s.pop('_gid', '')
        pref = group_pick.get(gid) if gid else None
        p = os.path.join(fdir, f'f{s["i"]:03d}.png')
        chosen = None
        if usable:
            chosen = min(
                usable,
                key=lambda c: (
                    _SCREEN_RANK.get(c['screen']['verdict'], 5),
                    0 if c['c'] == pref else 1,
                    -(c['screen'].get('cartoon') or 0.0),
                ),
            )
            os.replace(chosen['path'], p)
            s['source_render'] = 'generated'
            info['generated'] += 1
            pl['in_song'] += 1
            if gid:
                group_pick.setdefault(gid, chosen['c'])
            for c in usable:
                if c is chosen:
                    continue
                os.makedirs(xdir, exist_ok=True)
                dst = os.path.join(xdir, os.path.basename(c['path']))
                os.replace(c['path'], dst)
                c['file'] = f'frames/excess/{os.path.basename(dst)}'
                pl['excess_kept'] += 1
            chosen['file'] = f'frames/{os.path.basename(p)}'
        elif _draw_card(s, p, rng):
            s['source_render'] = 'drawn_screen'
            info['drawn_screen'] += 1
        else:
            s['source_render'] = 'missing'
            info['failed'] += 1
        for c in cands:
            v = c['screen']['verdict']
            if c.get('rejected'):
                pl['rejected'] += 1
                c['file'] = f'frames/rejected/{os.path.basename(c["path"])[:-4]}.jpg'
                for r in c['screen']['reasons']:
                    kind = (
                        r.split(':')[0]
                        if r.startswith(('lettering', 'writing'))
                        else ('heads' if 'heads' in r else 'anatomy/other')
                    )
                    pl['rejected_reasons'][kind] = pl['rejected_reasons'].get(kind, 0) + 1
            elif v == 'soft':
                pl['soft'] += 1
            elif v == 'unmeasured':
                pl['unmeasured'] += 1
            pl['screen_s'] += float(c['screen'].get('seconds') or 0.0)
        s['candidates'] = [
            {
                'c': c['c'],
                'seed': c['seed'],
                'verdict': c['screen']['verdict'],
                'reasons': c['screen']['reasons'] + c['screen']['soft'],
                'cartoon': c['screen'].get('cartoon'),
                'vlm': c['screen'].get('vlm'),
                'described': c['screen'].get('described'),
                'reseed': bool(c.get('reseed')),
                'file': c.get('file'),
                'chosen': c is chosen,
            }
            for c in cands
        ]
    pl['screen_s'] = round(pl['screen_s'], 1)
    why = ', '.join(f'{v} {k}' for k, v in sorted(pl['rejected_reasons'].items())) or 'none'
    log_fn(
        f'screen: {pl["rendered"]} candidates rendered for {len(pending)} pictures · '
        f'{pl["rejected"]} thrown out ({why}) · {pl["in_song"]} in the song · '
        f'{pl["excess_kept"]} spare kept in frames/excess'
        + (f' · {pl["reseeded_slots"]} slot(s) re-seeded' if pl['reseeded_slots'] else '')
        + (f' · {info["drawn_screen"]} drawn (every candidate rejected)' if info['drawn_screen'] else '')
        + (f' · {pl["unmeasured"]} unmeasured (VLM did not answer)' if pl['unmeasured'] else '')
        + f' · screen {pl["screen_s"]:.0f}s total, pick {time.time() - t0:.0f}s'
    )


def write_thumbs(paths, out_dir, log_fn=None):
    """480 px JPEG copies for the inspection tab.

    The tab shows a strip of every frame in a song; at ~300 KB a PNG that is a
    ten-megabyte page for one card.
    """
    try:
        from PIL import Image
    except ImportError:
        return 0
    n = 0
    for i, p in enumerate(paths):
        if not p or not os.path.isfile(p):
            continue
        try:
            with Image.open(p) as im:
                im = im.convert('RGB')
                im.thumbnail((480, 480))
                im.save(os.path.join(out_dir, 'frames', f't{i:03d}.jpg'), quality=82, optimize=True)
            n += 1
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.warning('thumbnail for frame %s failed, not counted: %s', p, _exc)
            continue
    return n
