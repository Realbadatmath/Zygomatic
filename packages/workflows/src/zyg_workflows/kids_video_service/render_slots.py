# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""The slot loop behind `render.render_images`: the leg's state and its passes.

`render_images` was one 329-line function. Everything that does not touch the
generator's own error handling lives here: the manifest counters, the candidate
pool's directories and worker, the per-slot render pass and the copy pass for
reused slots. The orchestrator in `render.py` keeps the generator open/close
paths, because those are the ones that swallow a backend's exceptions.

The leg carries the names the suite rebinds (`screen_frame`,
`draw_count_card`, the renderer itself) as attributes instead of reading them
as globals: the package's `_OneNamespace` rebinds a patched name in the
section modules it already lives in, and `render_images` reads them out of
`render`'s namespace when it builds the leg.
"""

from __future__ import annotations

import os
import time

from zyg_workflows.kids_video_service.cards import _draw_card
from zyg_workflows.kids_video_service.constants import _zyg_log
from zyg_workflows.kids_video_service.motifs import build_prompt
from zyg_workflows.kids_video_service.screen import (
    SCREEN_CALIBRATION,
    SCREEN_LLM,
    _VLM_FAILS,
    _reject_thumb,
)


def _new_info(family, steps, cfg, unet, fast, fast_requested, speed_warnings):
    """The run's manifest counters, zeroed, with the model facts this leg ran with.

    'drawn' is a FALLBACK (the generator was unavailable); 'drawn_count' is BY
    DESIGN (the counting cards). Two different facts about a run, and
    collapsing them would make every song look like one whose generator had
    failed. 'drawn_screen' = every candidate of a slot was thrown out by the
    defect screen.
    """
    return {
        'family': family,
        'steps': steps,
        'cfg': cfg,
        'unet': unet,
        'fast': fast,
        'fast_requested': fast_requested,
        'speed_warnings': list(speed_warnings),
        'generated': 0,
        'drawn': 0,
        'drawn_count': 0,
        'drawn_screen': 0,
        'reused': 0,
        'failed': 0,
        'text_flagged': 0,
        'text_repaired': 0,
        'text_remaining': 0,
        'cartoon_flagged': 0,
        'cartoon_repaired': 0,
        'cartoon_remaining': 0,
        'retries': 0,
        'backend': '',
        'seconds': 0.0,
        'unique': 0,
        'reuse_map': {},
        'aborted': False,
    }


class RenderLeg:
    """One picture leg: its directories, its counters, its candidate pool and its state.

    Constructed once the generator is known, so `pool` can depend on it. The
    screening worker (one thread) runs beside the render loop, so each
    candidate is judged as soon as it exists without the renders waiting on
    the judge. `t0` is taken last, exactly where the monolith took it: after
    the generator and the pool are open, before the first slot.
    """

    def __init__(self, gen, info, log_fn, abort, rng, style, fdir, candidates, screen_on):
        self.gen = gen
        self.info = info
        self.log_fn = log_fn
        self.abort = abort
        self.rng = rng
        self.style = style
        self.fdir = fdir
        # The candidate pool (see CANDIDATES).
        self.pool = bool(gen is not None and candidates > 1)
        self.n_cand = candidates if self.pool else 1
        self.screen = bool(self.pool and screen_on)
        if self.pool:
            info['pool'] = {
                'candidates_per_slot': self.n_cand,
                'screen': self.screen,
                'screen_model': SCREEN_LLM if self.screen else None,
                'calibration': SCREEN_CALIBRATION if self.screen else None,
                'rendered': 0,
                'rejected': 0,
                'rejected_reasons': {},
                'soft': 0,
                'unmeasured': 0,
                'in_song': 0,
                'excess_kept': 0,
                'reseeded_slots': 0,
                'screen_s': 0.0,
            }
        self.cdir = os.path.join(fdir, '_cand')
        self.xdir = os.path.join(fdir, 'excess')
        self.rdir = os.path.join(fdir, 'rejected')
        if self.pool:
            import shutil as _sh

            for d in (self.cdir, self.xdir, self.rdir):  # a re-illustrated song starts clean
                _sh.rmtree(d, ignore_errors=True)
            os.makedirs(self.cdir, exist_ok=True)
        self.executor = None
        if self.screen:
            from concurrent.futures import ThreadPoolExecutor

            self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='kidsvideo-screen')
            _VLM_FAILS['n'] = 0
        self.prompts = {}  # slot index -> the prompt it used
        self.seeds = {}  # (seed group, candidate) -> its shared seed
        self.made = {}  # idea text -> slot index already rendered
        self.paths = []
        self.pending = []  # pooled slots awaiting their pick
        # Bound by `render_images` out of `render`'s live namespace, so a test
        # that patches the package still reaches the stub (see module docstring).
        self.render = None
        self.screen_cand = None
        self.draw_count_card = None
        self.t0 = time.time()


def _screen_candidate(cand, rdir, screen_frame):
    """Worker: screen one candidate; a defect is thrown out on the spot."""
    r = screen_frame(cand['path'])
    cand['screen'] = r
    if r['verdict'] == 'defect':
        _reject_thumb(cand['path'], os.path.join(rdir, os.path.basename(cand['path'])[:-4] + '.jpg'))
        try:
            os.remove(cand['path'])
        except OSError as _exc:
            _zyg_log.debug('rejected candidate %s removal skipped: %s', cand['path'], _exc)
        cand['rejected'] = True
    return cand


def _render_slot_candidates(leg, s, p, slots):
    """Render one slot: `(ok, candidates, seed_group)`.

    Without the pool a single frame is rendered straight to `p` and `ok` says
    whether it arrived. With the pool, `leg.n_cand` candidates go to the
    candidate directory and each is handed to the screening worker. A counting
    run shares one seed per candidate index so only the NUMBER changes between
    its pictures — with a fresh seed each time the blocks change colour and
    the count stops reading as a count.
    """
    gid = s.get('seed_group') or ''
    cands = []
    ok = False
    for c in range(leg.n_cand):
        if gid:
            frame_seed = leg.seeds.setdefault((gid, c), leg.rng.randrange(1, 2**31 - 1))
        else:
            frame_seed = leg.rng.randrange(1, 2**31 - 1)
        if not leg.pool:
            # Last slot releases the models; every other keeps them resident.
            ok = leg.render(s, p, frame_seed, clear=(s is slots[-1]))
            break
        cp = os.path.join(leg.cdir, f'f{s["i"]:03d}_c{c}.png')
        if leg.render(s, cp, frame_seed):
            cand = {'c': c, 'seed': frame_seed, 'path': cp}
            leg.info['pool']['rendered'] += 1
            cands.append(leg.executor.submit(leg.screen_cand, cand) if leg.executor else cand)
    return ok, cands, gid


def _progress_line(info, done, total, elapsed, pending_n, pool):
    """The 'images: 6/30 …' progress line: what has been made so far and how long it took."""
    return (
        f'images: {done}/{total} '
        f'({info["generated"] + pending_n} generated, '
        f'{info["drawn_count"]} counting cards drawn'
        + (f', {info["drawn"]} drawn as fallback' if info['drawn'] else '')
        + (f', {info["pool"]["rendered"]} candidates rendered' if pool else '')
        + f', {elapsed:.0f}s)'
    )


def _render_slot_loop(leg, slots, reuse):
    """One picture per slot, in order: reuse, counting card, candidates or a single render.

    Writes the picture paths and the per-slot `source_render` verdicts; pooled
    slots are parked on `leg.pending` for `_pick_candidates` to choose from.
    """
    info, log_fn, rng = leg.info, leg.log_fn, leg.rng
    for s in slots:
        p = os.path.join(leg.fdir, f'f{s["i"]:03d}.png')
        leg.paths.append(p)
        key = (s.get('idea') or '').strip().lower()
        if reuse and key in leg.made:
            # Bounded-cost path only: engaged when the slot count exceeds
            # MAX_IMAGES. Recorded per slot so the manifest never implies a
            # unique picture where a repeat shipped. The copy is made after
            # the pick, because a pooled slot's picture is chosen later.
            s['source_render'] = 'reused'
            s['_reuse_of'] = leg.made[key]
            info['reused'] += 1
            info['reuse_map'][str(s['i'])] = f'f{leg.made[key]:03d}.png'
            continue
        if leg.abort():
            info['aborted'] = True
            log_fn(
                'images: halt requested — stopping after '
                f'{info["generated"] + len(leg.pending) + info["drawn"] + info["drawn_count"]} '
                f'frame(s)'
            )
            break
        spec = s.get('draw')
        if spec and spec.get('kind') == 'count':
            # DRAWN BY DESIGN, not because anything failed — the count is the
            # content and a generator will not honour it. Recorded separately
            # from the fallback so the manifest never reads as a broken run.
            if leg.draw_count_card(spec, p, rng):
                s['source_render'] = 'drawn_count'
                info['drawn_count'] += 1
                leg.made[key] = s['i']
                continue
            log_fn(f'images: slot {s["i"]} counting card could not be drawn — falling through to the generator')
        ok = False
        if leg.gen is not None:
            leg.prompts[s['i']] = build_prompt(leg.style, s['idea'])
            ok, cands, gid = _render_slot_candidates(leg, s, p, slots)
            if leg.pool and cands:
                s['_cands'] = cands
                s['_gid'] = gid
                leg.pending.append(s)
                leg.made[key] = s['i']
                continue
        if ok:
            s['source_render'] = 'generated'
            info['generated'] += 1
            leg.made[key] = s['i']
        elif _draw_card(s, p, rng):
            s['source_render'] = 'drawn'
            info['drawn'] += 1
            leg.made[key] = s['i']
        else:
            s['source_render'] = 'missing'
            info['failed'] += 1
        if (s['i'] + 1) % 6 == 0 or s is slots[-1]:
            log_fn(_progress_line(info, s['i'] + 1, len(slots), time.time() - leg.t0, len(leg.pending), leg.pool))


def _copy_reused_frames(slots, fdir, info):
    """Reused slots copy the picture their idea ended up with; a failed copy is 'missing'."""
    import shutil as _shr

    for s in slots:
        src_i = s.pop('_reuse_of', None)
        if src_i is None:
            continue
        try:
            _shr.copyfile(os.path.join(fdir, f'f{src_i:03d}.png'), os.path.join(fdir, f'f{s["i"]:03d}.png'))
        except OSError:
            s['source_render'] = 'missing'
            info['failed'] += 1
            info['reused'] -= 1
