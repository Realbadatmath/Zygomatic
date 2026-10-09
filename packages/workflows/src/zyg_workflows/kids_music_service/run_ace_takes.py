# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The stages of ``stage_ace``: the take loop, the voice leg and the pick.

``stage_ace`` was a 460-line straight-line block; the house rule is 300. The
block is unchanged, only cut along its own seams — one take's inputs, its
render, its singer gate, the voice review, the two ways a take is promoted to
``song.mp3`` — with the loop state carried by :class:`AceLeg` instead of by
sixteen enclosing locals.

Every patchable name is read back through the parent module
(``_parent.ace_render``, ``_parent.A2A_DENOISE_LADDER``, …) on purpose: the
package's ``_SharedNamespace.__setattr__`` forwards an attribute assignment
only into the submodules listed in ``__init__._SUBMODULES``, and this module is
not one of them. Reading through ``run_ace`` — which is — keeps every test stub
(``K.ace_render``, ``K.gate_singer_age``, ``K.repair_take``,
``K.chroma_follow``) live at call time. The import direction is one way: this
module imports ``run_ace``, and ``run_ace`` defers its import of this one into
``stage_ace``.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from zyg_workflows.kids_music_service import run_ace as _parent


@dataclass
class AceLeg:
    """The locals the ACE-Step leg of ``run()`` used to carry in one scope.

    The fields above ``base_seed`` are what the leg was asked for; the ones
    below are what it decides and accumulates while it renders takes. The
    orchestrator reads the accumulators back out for ``run()``.
    """

    plan: dict
    singer: dict
    midi: str
    out_dir: str
    cinematic: bool
    log_fn: object
    should_abort: object
    abort: object
    stage: object
    ace_mode: str
    cond_melody: object
    cond_cover: object
    n_takes: int
    max_try: int = 0
    rounds: int = 0
    want_voice: bool = False
    want_repair: bool = False
    voice_budget_s: float = 0.0
    voice_t0: float = 0.0
    voice_waited: float = 0.0
    base_seed: int | None = None
    alt_st: int | None = None
    cond_low: str | None = None
    rung: int = 0
    best_voice: dict | None = None
    ace_mp3: str | None = None
    ace_info: dict = field(default_factory=dict)
    singer_gate: dict | None = None
    produced_status: str = 'not_requested'
    attempts: list = field(default_factory=list)
    ace_takes: list = field(default_factory=list)
    picked_take: dict | None = None
    voice: dict = field(default_factory=dict)


@dataclass
class TakeInputs:
    """What one take is rendered from: melody, seed, destination and rung."""

    melody: object
    shift_st: int
    seed: int | None
    dest: str
    denoise: float


def voice_work_s(leg):
    """Seconds the voice leg has spent WORKING — queue time behind other
    ComfyUI clients is waiting, not work, so it is subtracted."""
    return time.time() - leg.voice_t0 - leg.voice_waited


def alt_lead_shift(leg):
    """The semitone shift re-seeds alternate the melody by, or None.

    Only the one-take melody-conditioned path of a sung, non-cinematic brief
    whose singer carries ``retry_lead_shift_st`` alternates; best-of-N, cover
    and text runs are unchanged.
    """
    if (
        leg.n_takes == 1
        and leg.cond_melody
        and not leg.cond_cover
        and leg.plan['brief'].get('sung')
        and not leg.cinematic
        and leg.singer.get('retry_lead_shift_st')
    ):
        return int(leg.singer['retry_lead_shift_st'])
    return None


def open_leg(leg):
    """Decide the leg's budget, seed, conditioning walk and review switches.

    Runs once, after the ``Produced Track (ACE-Step)`` stage marker and before
    the first take, in the order the straight-line block read them.
    """
    leg.max_try = _parent._singer_retries(leg.singer)
    # One loop, two meanings: N takes to CHOOSE from, or up to max_try
    # re-seeds of the one take until the singer gate is happy.
    leg.rounds = leg.n_takes if leg.n_takes > 1 else leg.max_try
    # A singer with a named voice starts on that voice's seed; re-seeds and
    # best-of-N takes walk up from it (+1, +2 ...), exactly as they walked up
    # from a random first seed before. Instrumental and cinematic briefs
    # have no voice to hold and stay random.
    if leg.plan['brief'].get('sung') and not leg.cinematic and leg.singer.get('ace_seed') is not None:
        leg.base_seed = int(leg.singer['ace_seed'])
        leg.log_fn(f'ace: singer voice "{leg.singer.get("voice")}" — starting on its seed {leg.base_seed}')
    if leg.n_takes > 1:
        leg.log_fn(
            f'ace: best-of-{leg.n_takes} — every take is gated, the least shrill passer ships (mode {leg.ace_mode})'
        )
    # Re-seeds ALTERNATE conditioning for a singer that carries
    # retry_lead_shift_st: take 1 score, take 2 the SAME seed on the melody
    # lowered, take 3 seed+1 score, take 4 seed+1 lowered ... Measured in
    # kids_music_theory.SINGERS['adult_male'].
    leg.alt_st = alt_lead_shift(leg)
    # THE VOICE LEG (2026-09-15, vocal_analysis.py). On the one-take path a
    # take that passes the singer gate is reviewed on its own separated
    # vocal — every lyric line placed with Whisper, per-line pitch, key,
    # level — and what it finds is acted on DURING the run: line problems
    # are repainted (repair_take), hard problems re-render, a level problem
    # is re-balanced from the stems at the master. The least-wrong reviewed
    # take ships; the budget stops it chasing a perfect take forever.
    leg.want_voice = (
        leg.n_takes == 1 and bool(leg.plan['brief'].get('sung')) and not leg.cinematic and _parent._voice_review_on()
    )
    leg.want_repair = _parent._repair_on()
    leg.voice_budget_s = _parent._voice_budget_s()
    leg.voice_t0 = time.time()


def take_inputs(leg, k):
    """Build take *k*'s inputs, rendering the lowered lead the first time it is
    needed and logging the shift and the denoise rung the way the block did."""
    mel_k, shift_k = leg.cond_melody, 0
    if leg.alt_st and k % 2 == 1:
        if leg.cond_low is None:
            leg.cond_low = (
                _parent.lowered_lead_wav(
                    leg.midi, os.path.join(leg.out_dir, '_render_low.wav'), leg.alt_st, log_fn=leg.log_fn
                )
                or ''
            )
            if not leg.cond_low:
                leg.alt_st = None  # plain re-seed walk from here on
        if leg.cond_low:
            mel_k, shift_k = leg.cond_low, leg.alt_st
    step = k // 2 if leg.alt_st else k
    seed_k = None if leg.base_seed is None else leg.base_seed + step
    dest = (
        os.path.join(leg.out_dir, f'song_take{k + 1}.mp3') if leg.n_takes > 1 else os.path.join(leg.out_dir, 'song.mp3')
    )
    if shift_k:
        leg.log_fn(f'ace: take {k + 1} — seed {seed_k} on the melody lowered {abs(shift_k)} st')
    ladder = _parent.A2A_DENOISE_LADDER
    den_k = ladder[min(leg.rung, len(ladder) - 1)]
    if leg.rung:
        leg.log_fn(
            f'ace: take {k + 1} — climbing the denoise ladder to {den_k:g} (the last take could not be made out)'
        )
    return TakeInputs(melody=mel_k, shift_st=shift_k, seed=seed_k, dest=dest, denoise=den_k)


def render_take(leg, k, inp, info):
    """Render take *k* into ``inp.dest``.

    Returns the rendered path, or None when ACE-Step produced no audio — in
    which case the failure is recorded in ``produced_status`` and ``attempts``
    and the loop is over.
    """
    got = _parent.ace_render(
        leg.plan,
        inp.dest,
        seed=inp.seed,
        denoise=inp.denoise,
        log_fn=leg.log_fn,
        should_abort=leg.should_abort,
        info=info,
        melody_wav=inp.melody,
        cover_wav=leg.cond_cover,
    )
    info['lead_shift_st'] = inp.shift_st
    leg.voice_waited += float(info.get('lock_wait_s') or 0.0)
    if leg.base_seed is None:
        leg.base_seed = info.get('seed')
    if not got:
        leg.produced_status = f'failed:{info.get("reason") or "unknown"}'
        leg.attempts.append(
            {'attempt': k + 1, 'seed': info.get('seed'), 'result': 'no audio', 'reason': info.get('reason', '')}
        )
        return None
    return got


def attempt_record(k, info, shift_st, sg):
    """One row of the manifest's ``attempts`` list for a gated take."""
    ch = sg.get('checks', {})
    return {
        'attempt': k + 1,
        'seed': info.get('seed'),
        'lead_shift_st': shift_st,
        'result': sg['status'],
        'f0_hz': ch.get('f0_median_hz'),
        'verdict': ch.get('voice_qc_verdict', ''),
        'detail': sg.get('detail', ''),
    }


def take_record(k, info, got, sg):
    """One row of ``ace_takes`` for a best-of-N take, private handles included."""
    ch = sg.get('checks', {})
    return {
        'take': k + 1,
        'seed': info.get('seed'),
        'file': os.path.basename(got),
        'status': sg['status'],
        'ok': bool(sg.get('ok')),
        'f0_median_hz': ch.get('f0_median_hz'),
        'sharpness_acum': ch.get('sharpness_acum'),
        'hf_ratio_2k8k': ch.get('hf_ratio_2k8k'),
        'detail': sg.get('detail', ''),
        '_path': got,
        '_info': info,
        '_gate': sg,
    }


def gate_take(leg, k, got, info, shift_st):
    """Gate take *k* on the singer's age and record the attempt.

    Returns ``(own, sg, take_dir)``: every one-take attempt renders to
    song.mp3, so the take a review and its repairs work on must be its own copy.
    """
    take_dir = os.path.join(leg.out_dir, '_takes', f'take{k + 1}')
    own = got
    if leg.want_voice:
        import shutil as _sh

        os.makedirs(take_dir, exist_ok=True)
        own = os.path.join(take_dir, 'take.mp3')
        _sh.copyfile(got, own)
    sg = _parent.gate_singer_age(own, leg.plan, work_dir=take_dir if leg.want_voice else None, log_fn=leg.log_fn)
    leg.attempts.append(attempt_record(k, info, shift_st, sg))
    return own, sg, take_dir


def keep_take(leg, k, got, info, sg):
    """Keep a best-of-N take for the ranking that happens once the set exists.

    The choice is made after the set exists, because rank_score is a z-score
    OVER the set.
    """
    leg.ace_takes.append(take_record(k, info, got, sg))
    ch = sg.get('checks', {})
    leg.log_fn(
        f'ace: take {k + 1} of {leg.n_takes} — seed {info.get("seed")}, '
        f'{sg["status"]}, f0 {ch.get("f0_median_hz")} Hz, '
        f'sharpness {ch.get("sharpness_acum")}'
    )


def repair_lines(leg, own, info, take_dir, rep):
    """Repaint the lines the review says are repairable, inside the budget.

    Returns ``(path, report, records)`` — the take itself and its own review
    when nothing was repaired.
    """
    path_k, rep_k, recs = own, rep, []
    hard = [p for p in rep.get('problems') or [] if p['fix'] == 'rerender']
    if rep.get('ok') and not hard and leg.want_repair and any(p['fix'] == 'repaint' for p in rep.get('problems') or []):
        left = leg.voice_budget_s - voice_work_s(leg)
        if left > 60:
            path_k, rep_k, recs = _parent.repair_take(
                own,
                leg.plan,
                leg.singer,
                rep,
                info,
                take_dir,
                log_fn=leg.log_fn,
                should_abort=leg.should_abort,
                budget_s=min(_parent._repair_budget_s(), left),
            )
            leg.voice_waited += sum(float(r.get('lock_wait_s') or 0.0) for r in recs)
    return path_k, rep_k, recs


def voice_attempt_note(rep_k, recs, sev):
    """The ``voice`` sub-record of an attempt: severity, problems, repair count."""
    return {
        'severity': sev,
        'problems': [p['detail'] for p in rep_k.get('problems') or []][:8],
        'repairs_kept': sum(1 for r in recs if r.get('result') == 'kept'),
        'repairs_tried': len(recs),
    }


def candidate_take(k, path_k, info, sg, rep_k, rep, recs, denoise, foll, sev):
    """A reviewed take as ``_better_take`` compares them; an unmeasured
    severity sorts last at 10**6."""
    return {
        'take': k + 1,
        'path': path_k,
        'info': info,
        'sg': sg,
        'rep': rep_k,
        'first': rep,
        'repairs': recs,
        'denoise': denoise,
        'followed': foll.get('followed'),
        'chroma': foll,
        'sev': sev if sev is not None else 10**6,
    }


def maybe_climb_ladder(leg, k, rep_k):
    """Climb the denoise ladder when too few of the take's lines can be made out.

    A2A conditioning is what the ladder trades away, so it only climbs on a
    melody-conditioned (non-cover) run that has a rung left.
    """
    lyb = rep_k.get('lyrics_bare') or {}
    share = (lyb.get('clear') or 0) / lyb['lines'] if lyb.get('measured') and lyb.get('lines') else None
    if (
        share is not None
        and share < _parent.CLEAR_SHARE_MIN
        and leg.cond_melody
        and not leg.cond_cover
        and leg.rung < len(_parent.A2A_DENOISE_LADDER) - 1
    ):
        leg.rung += 1
        leg.log_fn(
            f'voice: take {k + 1} — only {share:.0%} of its lines can be '
            f'made out; the next take climbs to denoise '
            f'{_parent.A2A_DENOISE_LADDER[leg.rung]:g}'
        )


def review_take(leg, k, own, info, sg, take_dir, denoise):
    """Review take *k* on its separated vocal, repair it and judge it.

    Returns ``'again'`` when the leg should render another take and ``'stop'``
    when the one it has is the one that ships. A level problem is fixed at the
    master, and a line the song ends inside ('line_cut') is the same length on
    every take — neither is a reason to render another one.
    """
    from zyg_workflows import vocal_analysis as VA

    stems_dir = os.path.join(take_dir, 'stems')
    sep = {
        'ok': True,
        'vocals': os.path.join(stems_dir, 'vocals.wav'),
        'rest': os.path.join(stems_dir, 'no_vocals.wav'),
    }
    rep = VA.review(own, leg.plan, leg.singer, take_dir, sep=sep, log_fn=leg.log_fn)
    leg.log_fn(f'voice: take {k + 1} — {VA.summary_line(rep)}')
    path_k, rep_k, recs = repair_lines(leg, own, info, take_dir, rep)
    sev = rep_k.get('severity') if rep_k.get('ok') else None
    leg.attempts[-1]['voice'] = voice_attempt_note(rep_k, recs, sev)
    # Chroma per take, not just once at delivery: the ladder can buy clarity
    # by walking away from the composed tune, and the take that ships is
    # chosen here.
    foll = (
        _parent.chroma_follow(path_k, leg.plan, _parent._null_plans(exclude_dir=leg.out_dir), log_fn=leg.log_fn)
        if leg.rung or rep_k.get('ok')
        else {}
    )
    cand = candidate_take(k, path_k, info, sg, rep_k, rep, recs, denoise, foll, sev)
    leg.attempts[-1]['voice']['denoise'] = denoise
    leg.attempts[-1]['voice']['chroma_z'] = foll.get('z')
    if _parent._better_take(cand, leg.best_voice):
        leg.best_voice = cand
    remaining = [p for p in rep_k.get('problems') or [] if p.get('fix') not in ('remix', 'none')]
    if not rep_k.get('ok'):
        # The review itself could not run: the singer gate passed, which is
        # exactly what shipped before this leg existed.
        leg.produced_status = 'ok'
        return 'stop'
    if not remaining:
        leg.produced_status = 'ok'
        return 'stop'
    spent = voice_work_s(leg)
    if k + 1 < leg.max_try and spent < leg.voice_budget_s:
        maybe_climb_ladder(leg, k, rep_k)
        leg.log_fn(
            f'voice: take {k + 1} still has {len(remaining)} problem(s) — '
            f'rendering another take ({spent:.0f}s of {leg.voice_budget_s:.0f}s used)'
        )
        return 'again'
    leg.produced_status = 'ok'
    return 'stop'


def run_take_loop(leg):
    """Render, gate and review takes until one ships or the budget is spent."""
    for k in range(leg.rounds):
        if leg.abort():
            leg.produced_status = 'skipped_by_operator'
            leg.log_fn('ace: halt requested — stopping the retry loop')
            break
        info = {}
        inp = take_inputs(leg, k)
        got = render_take(leg, k, inp, info)
        if not got:
            break
        leg.stage('Measure Produced Track')
        own, sg, take_dir = gate_take(leg, k, got, info, inp.shift_st)
        if leg.n_takes > 1:
            keep_take(leg, k, got, info, sg)
            continue
        leg.ace_mp3, leg.ace_info, leg.singer_gate = got, info, sg
        if sg.get('ok') and leg.want_voice:
            if review_take(leg, k, own, info, sg, take_dir, inp.denoise) == 'again':
                continue
            break
        if sg.get('ok'):
            leg.produced_status = 'ok'
            break
        leg.produced_status = f'failed:singer gate — {sg.get("detail", "")}'
        if k + 1 < leg.max_try:
            leg.log_fn(f'ace: singer gate failed — re-rendering (attempt {k + 2} of {leg.max_try})')
        else:
            leg.log_fn(f'ace: singer gate failed on all {leg.max_try} takes')


def voice_record(bv, rep_b, stems_saved, level, voice_t0):
    """The manifest's ``voice`` block for the reviewed take that ships."""
    return {
        'reviewed': bool(rep_b.get('ok')),
        'error': rep_b.get('error', ''),
        'take': bv['take'],
        'take_file': 'song.mp3',
        'severity': rep_b.get('severity'),
        'severity_before_repair': (bv['first'] or {}).get('severity'),
        'problems': rep_b.get('problems') or [],
        'problems_before_repair': (bv['first'] or {}).get('problems') or [],
        'lyrics': rep_b.get('lyrics'),
        'lyrics_bare': rep_b.get('lyrics_bare'),
        'register': rep_b.get('register'),
        'key': rep_b.get('key'),
        'level': rep_b.get('level'),
        'lines': rep_b.get('lines') or [],
        'repairs': bv['repairs'],
        'stems': stems_saved,
        'mix': {
            'vocal_db': level['gain_db'] if level else 0.0,
            'backing_db': 0.0,
            'by': 'voice review' if level else 'none',
        },
        'identity': {
            'measured': False,
            'note': 'not measurable with TitaNet-large on sung stems: '
            'same caption across songs 0.45 vs other captions '
            '0.39, other captions on one song 0.49, paired test '
            '1 of 3 (male vs female 0.27 does separate) — '
            'output/kidsmusic/_voice_build/calibration.json',
        },
        'seconds': round(time.time() - voice_t0, 1),
        '_stems': rep_b.get('stems') or {},
    }


def write_voice_report(out_dir, voice, rep_b):
    """Write ``voice_report.json``; a write failure is logged, never fatal."""
    try:
        with open(os.path.join(out_dir, 'voice_report.json'), 'w') as fh:
            json.dump(
                {k: v for k, v in voice.items() if not k.startswith('_')} | {'words': rep_b.get('words') or []},
                fh,
                indent=1,
            )
    except OSError as _exc:
        _parent._zyg_log.warning('voice_report.json write failed, continuing without it: %s', _exc)


def ship_reviewed_take(leg):
    """Promote the least-wrong reviewed take to song.mp3 and build ``leg.voice``."""
    bv, rep_b = leg.best_voice, leg.best_voice['rep']
    song = os.path.join(leg.out_dir, 'song.mp3')
    if bv['path'].lower().endswith('.mp3'):
        import shutil as _sh

        _sh.copyfile(bv['path'], song)
    else:
        _parent._mp3(bv['path'], song, log_fn=leg.log_fn, br='320k')
    leg.ace_mp3, leg.ace_info, leg.singer_gate = song, bv['info'], bv['sg']
    leg.produced_status = 'ok'
    if bv['take'] != len(leg.attempts):
        leg.log_fn(f'voice: shipping take {bv["take"]} (severity {bv["sev"]}) — the least-wrong reviewed take')
    stems_saved = {}
    if rep_b.get('ok'):
        try:
            stems_saved = _parent.save_stems(rep_b['stems']['vocals'], rep_b['stems']['rest'], leg.out_dir)
        except Exception as e:  # noqa: BLE001
            leg.log_fn(f'voice: could not keep the stems ({type(e).__name__}: {e})')
    level = next((p for p in rep_b.get('problems') or [] if p['kind'] == 'level'), None)
    leg.voice = voice_record(bv, rep_b, stems_saved, level, leg.voice_t0)
    write_voice_report(leg.out_dir, leg.voice, rep_b)


def pick_ranked_take(leg):
    """Rank the best-of-N takes, promote the winner and record the pick."""
    try:
        from zyg_workflows import sung_pitch as _sp

        _sp.rank_score(leg.ace_takes)
    except Exception as e:  # noqa: BLE001 — never fatal
        leg.log_fn(f'ace: could not rank the takes ({type(e).__name__}: {e}) — keeping the first one')
    passed = [t for t in leg.ace_takes if t['ok']]
    # Only a passing take can be chosen ON MERIT. When none passed there is
    # nothing to choose between, so the least shrill of the failures carries
    # on to the produced gate, which fails it exactly as one take would have.
    best = min(passed or leg.ace_takes, key=lambda t: t.get('rank') or 0.0)
    song = os.path.join(leg.out_dir, 'song.mp3')
    try:
        import shutil as _sh

        _sh.copyfile(best['_path'], song)
        leg.ace_mp3 = song
    except OSError as e:
        leg.log_fn(f'ace: could not promote take {best["take"]} ({e}) — shipping it where it lies')
        leg.ace_mp3 = best['_path']
    leg.ace_info, leg.singer_gate = best['_info'], best['_gate']
    leg.produced_status = 'ok' if best['ok'] else f'failed:singer gate — {best["_gate"].get("detail", "")}'
    leg.log_fn(
        f'ace: kept take {best["take"]} of {len(leg.ace_takes)} — seed '
        f'{best["seed"]}, rank {best.get("rank")}, f0 '
        f'{best.get("f0_median_hz")} Hz; {len(passed)} of '
        f'{len(leg.ace_takes)} passed the singer gate'
    )
    # The private handles never reach the manifest — the board reads it on
    # every poll and a gate dict is not a record of a take.
    for _t in leg.ace_takes:
        for _k in ('_path', '_info', '_gate'):
            _t.pop(_k, None)
    leg.picked_take = dict(best)
