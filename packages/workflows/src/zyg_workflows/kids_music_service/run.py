# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""run() — compose, render both legs, measure, master, file it.

Moved verbatim out of the old single-file kids_music_service.py (lines 3311-3501, 3924-4023, 4387-4424).

run() is now the orchestrator of the steps it always had, each a module-level
function below; the statements, their order and their side effects are the ones
run() ran.  The helpers stay in THIS module so every name they look up
(`render_soundfont`, `master_audio`, …) is still the one the package's
`_SharedNamespace.__setattr__` write-through patches.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from zyg_workflows import paths
from zyg_workflows import kids_music_theory as T

from zyg_workflows.kids_music_service.base import (
    _log_noop,
    _zyg_log,
)
from zyg_workflows.kids_music_service.midi import write_midi
from zyg_workflows.kids_music_service.soundfont import render_soundfont
from zyg_workflows.kids_music_service.lyrics import (
    lyrics_block,
    write_lyrics,
)
from zyg_workflows.kids_music_service.measure import gate_audio
from zyg_workflows.kids_music_service.roll import write_roll_svg
from zyg_workflows.kids_music_service.mixdown import (
    _mp3,
    _write_state,
    mix_balance,
    percussion_wav,
    prelevel,
    soundfont_info,
)
from zyg_workflows.kids_music_service.master import (
    _update_voice_report,
    convert_voice,
    master_audio,
    remix_stems,
)
from zyg_workflows.kids_music_service.run_ace import stage_ace
from zyg_workflows.kids_music_service.run_deliver import stage_deliver


@dataclass
class _ScoreRender:
    """What the score-render leg produced and the legs below read from it.

    `render_mp3` is None when the SoundFont render failed; `render_wav_kept`
    and `soundfont_wav` are the audio ACE-Step may be conditioned on.
    """

    midi: str
    render_mp3: str | None = None
    render_wav_kept: str | None = None
    soundfont_wav: str | None = None
    render_engine: str = 'soundfont'
    sampler_res: dict = field(default_factory=dict)
    sampler_credits: dict = field(default_factory=dict)
    sampler_fallback: str = ''
    mix: dict = field(default_factory=dict)


def _stage_brief(brief, log_fn, stage):
    """Normalise the brief and announce what is about to be made.

    In: the brief, the log and stage callbacks.  Out: `(brief, family,
    cinematic, singer, sf_info)`.
    """
    stage('Song Brief')
    brief = T._normalise_brief(brief)
    # Which workflow this is. 'children' for everything that predates the
    # cinematic family, so every existing brief runs exactly as it did.
    family = brief.get('family') or 'children'
    cinematic = family == 'cinematic'
    singer = T.SINGERS[brief.get('singer') or T.DEFAULT_SINGER]
    log_fn(
        f'brief: "{brief["theme"]}" · {T.AGE_BANDS[brief["age_band"]]["label"]} · '
        f'{T.MOODS[brief["mood"]]["label"]} · {brief["seconds"]:.0f}s · '
        + (f'sung by {singer["label"]}' if brief.get('sung') else 'instrumental')
    )
    sf_info = soundfont_info()
    if not sf_info['ok']:
        log_fn(f'licence: SoundFont NOT VERIFIED — {sf_info["reason"]}')
    return brief, family, cinematic, singer, sf_info


def _stage_lyrics(brief, cinematic, log_fn, stage):
    """Write the lyric lines into the brief, before anything is composed.

    In: the brief (mutated with `lyrics_lines` and `title`), whether this is a
    cinematic brief, the callbacks.  Out: `(lyric_src, lyric_info)`.
    """
    lyric_src, title = 'none', brief.get('title') or ''
    lyric_info = {}
    # NOT `if sung` alone. A cinematic brief already comes back with sung=False,
    # but saying so here is what makes the skip a decision rather than a
    # side-effect: there is no lyric leg in this family, so the LLM is never
    # asked for one even if a caller forces sung back on.
    if brief.get('sung') and not cinematic and not brief.get('lyrics_lines'):
        stage('Lyrics')
        probe = T.compose(brief, seed=0)
        n_lines = len(probe['order']) * 2
        syl = T._syllable_targets(brief, len(probe['order']))
        lines, t_title, lyric_src, lyric_info = write_lyrics(brief, n_lines, syl, order=probe['order'], log_fn=log_fn)
        brief['lyrics_lines'] = lines
        title = title or t_title
        log_fn(
            f'lyrics: {len(lines)} lines via {lyric_src} '
            f'({lyric_info.get("model") or "?"} on {lyric_info.get("backend") or "?"})'
        )
        if brief.get('lyrics_truncated'):
            log_fn(f'lyrics: {brief["lyrics_truncated"]} line(s) truncated by the {T.LYRIC_LINE_CAP}-line cap')
    elif brief.get('lyrics_lines'):
        lyric_src = 'operator'
    brief['title'] = title or (brief['theme'][:60].strip().capitalize())
    return lyric_src, lyric_info


def _stage_compose(brief, out_dir, candidates, lyric_src, log_fn, stage):
    """Search for the best plan; write it, the lyric block and the roll.

    In: the brief, the output dir, the candidate budget (None → the
    environment, default 48), the lyric source, the callbacks.  Out:
    `(plan, score_card)`.
    """
    stage('Compose & Score')
    n_cand = int(candidates or os.environ.get('ZYG_KIDSMUSIC_CANDIDATES', '48'))
    plan = T.compose_best(brief, candidates=n_cand, log_fn=log_fn)
    sc = plan['score']
    log_fn(
        f'compose: kept seed {plan["seed"]} of {plan["search"]["candidates_tried"]} '
        f'→ score {sc["total"]:.3f} ({"PASS" if sc["ok"] else "SOFT FAIL"})'
    )
    for f in sc['fails']:
        log_fn(f'  gate fail: {f}')
    for w in sc['warnings']:
        log_fn(f'  note: {w}')
    if not sc.get('invariants_ok', True):
        log_fn(f'  COMPOSER BUG: invariants broken — {sc.get("invariants")}')
    if brief.get('lyrics_lines'):
        plan['lyrics'] = brief['lyrics_lines']
        plan['lyrics_block'] = lyrics_block(brief['lyrics_lines'], plan['order'])
        plan['lyrics_source'] = lyric_src
        with open(os.path.join(out_dir, 'lyrics.txt'), 'w') as fh:
            fh.write(plan['lyrics_block'] + '\n')

    with open(os.path.join(out_dir, 'song.json'), 'w') as fh:
        json.dump(plan, fh, indent=1)
    # The roll belongs to the SCORE leg. It is the composed tune, and the ACE leg
    # does not follow it — drawing it above both players said the opposite.
    write_roll_svg(plan, os.path.join(out_dir, 'roll.svg'))
    return plan, sc


def _play_the_score(plan, midi, out_dir, sr, log_fn):
    """Play the plan on the melody sampler when the style asks for voices; out: the wav to level."""
    # THE SOUNDFONT RENDER IS WHAT GOES INTO ACE-STEP, ALWAYS.
    # The Philharmonia samples the melody_sampler plays are tagged
    # no_ai_training=True; the SoundFont is MIT and carries no such term. So
    # `render_wav_kept` — the audio a model is CONDITIONED ON — stays the
    # SoundFont render whatever the style asks for, and the sampled render is
    # only ever a thing a human listens to. The two are the same performance
    # of the same plan, so nothing musical is lost by the split.
    ship_wav = sr.soundfont_wav
    if plan.get('voices'):
        try:
            from zyg_workflows import melody_sampler as MS

            perc = None
            if plan.get('percussion'):
                perc = percussion_wav(midi, os.path.join(out_dir, '_perc.wav'), log_fn=log_fn)
            s_wav = os.path.join(out_dir, '_render_sampler.wav')
            sr.sampler_res = MS.render_plan(plan, s_wav, voices=plan['voices'], log_fn=log_fn, perc_wav=perc)
            if sr.sampler_res.get('ok'):
                ship_wav = s_wav
                sr.render_engine = 'sampler'
                sr.sampler_credits = MS.credits(sr.sampler_res.get('files'), log_fn=log_fn)
                # The full per-role file lists belong with the plan, not in
                # the manifest: a style can put a hundred sample ids in there
                # and the manifest is read by the board on every poll.
                plan['render_files'] = sr.sampler_res.get('files') or {}
                with open(os.path.join(out_dir, 'song.json'), 'w') as fh:
                    json.dump(plan, fh, indent=1)
            else:
                sr.sampler_fallback = 'render_plan returned ok=False'
        except Exception as e:  # noqa: BLE001 — never fatal
            sr.sampler_fallback = f'{type(e).__name__}: {e}'[:180]
        if sr.sampler_fallback:
            log_fn('sampler: fell back to the SoundFont render — ' + sr.sampler_fallback)
    return ship_wav


def _stage_score_render(brief, plan, out_dir, log_fn, stage):
    """Render the score leg: midi, the performance, the levelled mp3.

    In: the brief, the plan, the output dir, the callbacks.  Out:
    `(_ScoreRender, want_a2a)`.  Always runs — it is the diagnostic.
    """
    stage('Score Render')
    midi = write_midi(plan, os.path.join(out_dir, 'melody.mid'), log_fn=log_fn)
    render_wav = os.path.join(out_dir, '_render.wav')
    sr = _ScoreRender(midi=midi)
    # Melody conditioning starts the sampler from the SCORE RENDER's latent
    # instead of from noise, so the ACE leg follows the composed tune instead of
    # merely sharing its key and lyric. ON by default (denoise 0.45, measured
    # chroma z 7.35 with a real vocal present); ZYG_KIDSMUSIC_A2A=0 or
    # brief['melody_conditioning']=False turns it off.
    want_a2a = bool(
        brief.get(
            'melody_conditioning', os.environ.get('ZYG_KIDSMUSIC_A2A', '1').strip() not in ('0', 'false', 'no', 'off')
        )
    )
    if render_soundfont(midi, render_wav, log_fn=log_fn):
        # The SoundFont render itself, whether or not melody conditioning is on:
        # COVER mode needs that exact file and does not go through `want_a2a`.
        sr.soundfont_wav = render_wav
        if want_a2a:
            sr.render_wav_kept = render_wav

        ship_wav = _play_the_score(plan, midi, out_dir, sr, log_fn)

        sr.mix = mix_balance(midi, plan, engine=sr.render_engine, log_fn=log_fn)
        if sr.mix.get('margin_db') is not None:
            log_fn(
                f'mix: melody {sr.mix["margin_db"]:+.1f} dB against bass '
                f'({"ok" if sr.mix.get("ok") else "TUNE IS BURIED"})'
            )
        # Levelled to a deliberately quieter target than the master, so the
        # master still reads as the finished product — and high-passed at 60 Hz,
        # below the lowest bass fundamental the composer can write.
        lvl = prelevel(ship_wav, os.path.join(out_dir, '_render_lvl.wav'), target_lufs=-18.0, log_fn=log_fn)
        sr.render_mp3 = _mp3(lvl, os.path.join(out_dir, 'melody.mp3'), log_fn=log_fn, highpass_hz=60)
    return sr, want_a2a


def _stage_measure_render(plan, sr, log_fn, stage):
    """Gate the score render, and decide whether it may ever be shipped.

    In: the plan, the `_ScoreRender`, the callbacks.  Out:
    `(gates, fallback_safe)`.
    """
    gates = {}
    if sr.render_mp3:
        stage('Measure Score Render')
        # want_clap=True. This is the leg that ships when ACE-Step is down, and
        # it was the ONLY leg with its content gate switched off — the newest
        # song scored 0.4705 on "heavy metal" against 0.0947 on "a cheerful
        # children's song", and nothing anywhere noticed.
        gates['render'] = gate_audio(sr.render_mp3, plan, leg='render', want_clap=True, log_fn=log_fn)
        gates['render']['mix'] = sr.mix
        try:
            i_l = __import__('zyg_workflows.audio_mix').measure_lufs(sr.render_mp3, log_fn=None)
            if i_l is not None:
                gates['render']['checks']['lufs_after_levelling'] = round(float(i_l), 2)
                if abs(float(i_l) + 18.0) > 3.0:
                    gates['render']['warnings'].append(f'score render landed {float(i_l):.1f} LUFS, not -18 +-3')
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.warning('LUFS re-measure of the score render failed, gate check omitted: %s', _exc)

    # Is the score render safe to SHIP, as opposed to safe to inspect?
    _clap = gates.get('render', {}).get('checks', {}).get('clap') or {}
    # `is True` on the CLAP verdict is deliberate — it must distinguish a real
    # pass from `None` (did not run). The mix verdict is a plain bool and is
    # tested for truth.
    fallback_safe = bool(
        sr.render_mp3 and gates.get('render', {}).get('ok') and _clap.get('ok') is True and sr.mix.get('ok')
    )
    if sr.render_mp3 and not fallback_safe:
        log_fn('render: DIAGNOSTIC ONLY — did not clear its content gate, so it will not be offered as a deliverable')
    return gates, fallback_safe


def _pick_leg(ace_mp3, render_mp3, gates, fallback_safe, log_fn):
    """Choose the deliverable between the two legs; out: `(pick, why, picked_leg)`."""
    pick, why, picked_leg = None, '', ''
    if ace_mp3 and gates.get('produced', {}).get('ok'):
        pick, why, picked_leg = ace_mp3, 'ACE-Step variation passed its gates', 'produced'
    elif fallback_safe:
        pick, picked_leg = render_mp3, 'render'
        why = (
            'ACE-Step variation failed its gates — shipping the score render'
            if ace_mp3
            else 'no ACE-Step variation — shipping the score render'
        )
    else:
        why = (
            'no shippable leg: '
            + ('the ACE-Step variation failed its gates and ' if ace_mp3 else 'no ACE-Step variation and ')
            + ('the score render did not clear its content gate' if render_mp3 else 'no score render')
        )
        log_fn(f'deliver: {why}')
    return pick, why, picked_leg


def _remix_for_level(voice, out_dir, pick, log_fn):
    """Re-balance a take from its stems before mastering; out: the wav to master, `pick` if it failed."""
    try:
        feed = remix_stems(
            voice['_stems']['vocals'],
            voice['_stems']['rest'],
            os.path.join(out_dir, '_remix.wav'),
            vocal_db=voice['mix']['vocal_db'],
        )['path']
        log_fn(f'voice: level fix — vocal {voice["mix"]["vocal_db"]:+.1f} dB from the stems before mastering')
    except Exception as e:  # noqa: BLE001 — ship the take unbalanced
        log_fn(f'voice: level fix failed ({type(e).__name__}: {e}) — mastering the take')
        voice['mix'] = {'vocal_db': 0.0, 'backing_db': 0.0, 'by': 'none', 'error': f'{type(e).__name__}'}
        feed = pick
    return feed


def _master_converted(voice, plan, feed, conv_feed, out_dir, log_fn):
    """Master the converted mix, keeping the unconverted one for A/B; out: `(master, mgate, trimmed_s)`."""
    um, ugate, _t = master_audio(feed, out_dir, plan, log_fn=log_fn, dst_name='master_unconverted.mp3')
    voice['conversion']['master_unconverted'] = (
        {
            'file': os.path.basename(um),
            'lufs': (ugate.get('checks') or {}).get('lufs'),
            'key_match': (ugate.get('checks') or {}).get('key_match'),
        }
        if um
        else None
    )
    master, mgate, trimmed_s = master_audio(conv_feed, out_dir, plan, log_fn=log_fn)
    if not master and um:
        # The converted mix would not master: ship the take as it was.
        os.replace(um, os.path.join(out_dir, 'master.mp3'))
        master, mgate = os.path.join(out_dir, 'master.mp3'), ugate
        voice['conversion'].update(shipped=False, reasons=['mastering the converted mix failed'])
        log_fn('voice: the converted mix would not master — shipping the unconverted take')
    return master, mgate, trimmed_s


def _stage_master(*, abort, ace_mp3, fallback_safe, gates, log_fn, out_dir, plan, sr, singer, stage, voice):
    """Pick the leg that ships and master it.

    In: everything the two legs produced plus the callbacks.  Out:
    `(master, trimmed_s, pick, picked_leg, why)`.
    """
    stage('Master & Deliver')
    pick, why, picked_leg = _pick_leg(ace_mp3, sr.render_mp3, gates, fallback_safe, log_fn)

    master, trimmed_s = None, 0.0
    if pick:
        feed = pick
        # The voice leg's level fix: a take whose median sung line sits outside
        # the calibrated -6..+3 dB against the band is re-balanced from its own
        # stems before mastering (vocal_analysis.problems 'level').
        if picked_leg == 'produced' and voice.get('mix', {}).get('vocal_db'):
            feed = _remix_for_level(voice, out_dir, pick, log_fn)
        # The voice conversion (voice_conversion.py): a singer that names a
        # trained voice gets its shipped vocal converted to it, re-checked, and
        # re-mixed at the same balance. The unconverted master is mastered too,
        # from exactly the feed it would have shipped as, for A/B on the card.
        conv_feed = None
        if picked_leg == 'produced' and voice and singer.get('vc_model') and not abort():
            conv_feed = convert_voice(voice, plan, singer, pick, out_dir, log_fn=log_fn)
        if conv_feed:
            master, mgate, trimmed_s = _master_converted(voice, plan, feed, conv_feed, out_dir, log_fn)
        else:
            master, mgate, trimmed_s = master_audio(feed, out_dir, plan, log_fn=log_fn)
        if master:
            gates['master'] = mgate
        if voice.get('conversion'):
            _update_voice_report(out_dir, voice)
    return master, trimmed_s, pick, picked_leg, why


def _sweep_temps(out_dir, cond_melody, cond_cover):
    """Remove everything the run wrote that is not a deliverable.

    In: the output dir and the two conditioning handles.  Out: nothing;
    every removal is best effort and logged at debug level.
    """
    # Cover mode stages under its own stem so both can exist in one process.
    if cond_melody or cond_cover:
        base = str(paths.ZYG_COMFY_INPUT)
        for _stem in ('melody', 'src'):
            try:
                os.remove(os.path.join(base, f'kidsmusic_{_stem}_{os.getpid()}.wav'))
            except OSError as _exc:
                _zyg_log.debug('voice-clone temp wav removal skipped: %s', _exc)
    for tmp in (
        '_render.wav',
        '_render_lvl.wav',
        '_master.wav',
        '_pre.wav',
        '_trim.wav',
        '_render_sampler.wav',
        '_perc.wav',
        '_render_low.wav',
        '_remix.wav',
        '_remix_vc.wav',
    ):
        try:
            os.remove(os.path.join(out_dir, tmp))
        except OSError as _exc:
            _zyg_log.debug('run temp %s removal skipped: %s', tmp, _exc)
    import shutil as _sh_vc

    _sh_vc.rmtree(os.path.join(out_dir, '_vc'), ignore_errors=True)


def _stage_file_it(brief, out_dir, manifest, ok, video, want_video, why, log_fn, job_id):
    """Section 7: file the song, write the run state, log the closing line.

    In: the brief, the output dir, the manifest, `ok`, the video record,
    `want_video`, the pick sentence, the log, the job id.  Out: nothing.
    """
    # A styled song knows its shelf before it exists, so it is placed by the
    # run rather than guessed at by the board later. Same record
    # kanban_server._km_file_song writes, plus `by` so a placement the operator
    # did not make is identifiable.
    if ok and brief.get('shelf'):
        shelf_path = os.path.join(out_dir, 'shelf.json')
        if not os.path.exists(shelf_path):
            try:
                with open(shelf_path, 'w', encoding='utf-8') as fh:
                    json.dump(
                        {
                            'family': brief.get('family') or 'children',
                            'shelf': brief['shelf'],
                            'filed': time.strftime('%Y-%m-%dT%H:%M:%S'),
                            'by': 'style',
                        },
                        fh,
                        indent=2,
                    )
                log_fn(f'filed: {manifest["family"]}/{brief["shelf"]}')
            except OSError as e:
                log_fn(f'filing failed ({e}) — the board will guess a shelf')
    _write_state(out_dir, manifest, job_id=job_id)
    _vpx = video.get('pacing') or {}
    log_fn(
        f'done in {manifest["elapsed_s"]:.0f}s → '
        f'{manifest["delivery"]["picked"] or "NOTHING"} ({why})'
        + (
            f' · video {video.get("file")} — {_vpx.get("pictures", "?")} pictures, '
            f'{_vpx.get("per_5s_mean", "?")} per 5s'
            if video.get('ok')
            else (f' · no video ({video.get("reason")})' if want_video else '')
        )
    )


def run(brief, out_dir, *, log_fn=None, stage_fn=None, candidates=None, want_ace=True, should_abort=None, job_id=''):
    """Compose → score-gate → render both legs → measure → master → manifest.

    Returns the manifest dict.  Never raises: a leg that fails is recorded as a
    failed leg and the run continues.

    WHAT SHIPS. The ACE-Step leg is the deliverable when it exists and passes its
    gates — including the SINGER gate, because a song for children sung by a
    child voice is the one outcome this workflow must not produce. The score
    render is a DIAGNOSTIC by default: it is the composed tune, exactly, which is
    what makes it useful for inspection, and it is promoted to a shippable
    fallback only when it passes its own content gate (CLAP) and the mix
    regression. A run that has neither says "no shippable leg" rather than
    naming a file it cannot stand behind — `manifest['ok']` is derived from
    whether audio actually exists, not from whether run() returned normally.
    """
    log_fn = log_fn or _log_noop
    stage = stage_fn or (lambda _s: None)
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    abort = should_abort or (lambda: False)

    # ── 1. Brief
    brief, family, cinematic, singer, sf_info = _stage_brief(brief, log_fn, stage)

    # ── 2. Lyrics (before composing: the syllable budget shapes the rhythm)
    lyric_src, lyric_info = _stage_lyrics(brief, cinematic, log_fn, stage)

    # ── 3. Compose + score gate
    plan, sc = _stage_compose(brief, out_dir, candidates, lyric_src, log_fn, stage)

    # ── 4. Score render (always — it is the diagnostic, and sometimes the fallback)
    sr, want_a2a = _stage_score_render(brief, plan, out_dir, log_fn, stage)
    gates, fallback_safe = _stage_measure_render(plan, sr, log_fn, stage)

    (
        ace_info,
        ace_mode,
        ace_mp3,
        ace_takes,
        attempts,
        cond_cover,
        cond_melody,
        n_takes,
        picked_take,
        produced_status,
        voice,
    ) = stage_ace(
        abort=abort,
        cinematic=cinematic,
        gates=gates,
        log_fn=log_fn,
        midi=sr.midi,
        out_dir=out_dir,
        plan=plan,
        render_wav_kept=sr.render_wav_kept,
        should_abort=should_abort,
        singer=singer,
        soundfont_wav=sr.soundfont_wav,
        stage=stage,
        want_a2a=want_a2a,
        want_ace=want_ace,
    )

    # ── 6. Master.  The ACE leg is the deliverable when it exists and passes;
    #      otherwise the score render, but ONLY if it cleared its content gate.
    master, trimmed_s, pick, picked_leg, why = _stage_master(
        abort=abort,
        ace_mp3=ace_mp3,
        fallback_safe=fallback_safe,
        gates=gates,
        log_fn=log_fn,
        out_dir=out_dir,
        plan=plan,
        sr=sr,
        singer=singer,
        stage=stage,
        voice=voice,
    )
    _sweep_temps(out_dir, cond_melody, cond_cover)

    (
        manifest,
        ok,
        video,
        want_video,
        why,
    ) = stage_deliver(
        abort=abort,
        ace_info=ace_info,
        ace_mode=ace_mode,
        ace_mp3=ace_mp3,
        ace_takes=ace_takes,
        attempts=attempts,
        brief=brief,
        cinematic=cinematic,
        fallback_safe=fallback_safe,
        family=family,
        gates=gates,
        log_fn=log_fn,
        lyric_info=lyric_info,
        lyric_src=lyric_src,
        master=master,
        midi=sr.midi,
        n_takes=n_takes,
        out_dir=out_dir,
        pick=pick,
        picked_leg=picked_leg,
        picked_take=picked_take,
        plan=plan,
        produced_status=produced_status,
        render_engine=sr.render_engine,
        render_mp3=sr.render_mp3,
        sampler_credits=sr.sampler_credits,
        sampler_fallback=sr.sampler_fallback,
        sampler_res=sr.sampler_res,
        sc=sc,
        sf_info=sf_info,
        should_abort=should_abort,
        singer=singer,
        stage=stage,
        t0=t0,
        trimmed_s=trimmed_s,
        voice=voice,
        why=why,
    )

    # ── 7. File it.
    _stage_file_it(brief, out_dir, manifest, ok, video, want_video, why, log_fn, job_id)
    return manifest
