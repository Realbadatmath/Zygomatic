# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""storyteller_scene_service_steps — Steps 2 and 3: the voice lines and the scene timeline built from them."""

from __future__ import annotations

from zyg_workflows.storyteller_scene_service_steps.stills import (
    _GateReceipts,
    _svc,
    os,
)

# ── 2 ── voice lines ─────────────────────────────────────────────────────────


def _line_voice(voices: dict, ev: dict) -> dict:
    """The character's voice, with any per-line sampler override applied.
    `seed`/`exaggeration`/`cfg_weight`/`temperature` on a line re-roll THAT
    line's take without touching the character's voice anywhere else — the
    identity comes from `ref` (the frozen clone), which a line cannot set."""
    v = dict(voices[ev['speaker']])
    # `tempo`/`pace_ref` are overridable too, so a line can opt out of the
    # scene's pace match — an anchored one-word line is where the TTS is
    # least reliable, and pacing a take that restated itself against a
    # reference of the clean single word is meaningless.
    for k in ('seed', 'exaggeration', 'cfg_weight', 'temperature', 'tempo', 'pace_ref'):
        if k in ev:
            v[k] = ev[k]
    return v


def _line_wav(voices: dict, ev: dict, wav: str, tag: str, log) -> str | None:
    """Render/reuse one line's audio. Returns the wav, or None on failure."""
    # A cached line is only valid for the settings that produced it, and
    # there are TWO layers: the sampler settings that made the clone and the
    # pitch settings applied on top. The `.tune` marker carries both, so
    # this gate never short-circuits a changed sampler seed; _synth_line's
    # `.take` marker then decides whether the CLONE has to be re-rendered or
    # whether a re-shift of the cached one is enough. A re-tune stays one
    # ffmpeg pass; a re-roll costs a fresh render, as it must.
    voice = _line_voice(voices, ev)
    want = f'{_svc()._tune_key(voice, wav)}|{_svc()._take_key(voice, ev["text"])}'
    got = None
    if os.path.isfile(wav + '.tune'):
        with open(wav + '.tune') as fh:
            got = fh.read().strip()
    stale = got != want
    if stale and os.path.isfile(wav):
        log(f'[scene] {tag} re-tune: {got or "unmarked"} → {want}')
    if not (os.path.isfile(wav) and not stale and not ev.get('force')):
        if not _svc()._synth_line(ev['text'], wav, voice, log_fn=log):
            log(f'[scene] ABORT — TTS failed for {tag} ({ev["speaker"]})')
            return None
    return wav


def _step_voice_lines(spec: dict, out_dir: str, log, gates: _GateReceipts) -> tuple[list, list] | None:
    """Stage 2: render every dialogue line and every anchored line. Returns
    (lines, anchored) or None to abort."""
    voices = spec.get('voices', {})

    lines: list[dict] = []
    for i, ev in enumerate(spec['dialogue']):
        if 'text' not in ev:
            lines.append(dict(ev))
            continue
        wav = os.path.join(out_dir, f'line_{i:02d}_{ev["speaker"]}.wav')
        if not _line_wav(voices, ev, wav, f'line {i}', log):
            gates.audit()
            return None
        d = _svc()._read_mono48k(wav)
        lines.append({**ev, 'wav': wav, 'dur': len(d) / _svc()._SR})

    # 2b ── anchored lines ───────────────────────────────────────────────────
    # A line that does NOT belong to the running order: it hangs off a named
    # mark instead of following the previous line. Rendered here with the rest,
    # placed once the marks exist (stage 3b) — the tail marks it wants to hang
    # on are derived from where the dialogue ends, so it cannot be positioned
    # until the running order is laid out.
    anchored: list[dict] = []
    # line_verify gate stats — aggregated across every anchored line, since
    # the ASR transcript check (_verify_line_text) runs per line but is
    # reported here as one pipeline-level gate, same as hand_qc is one gate
    # over many shots.
    _lv_stats = {'checked': 0, 'passed': 0, 'failed': 0, 'unavailable': 0, 'opted_out': 0}
    for i, ev in enumerate(spec.get('anchored_lines') or []):
        wav = os.path.join(out_dir, f'anchor_{i:02d}_{ev["speaker"]}.wav')
        if not _line_wav(voices, ev, wav, f'anchored line {i}', log):
            gates.audit()
            return None
        d = _svc()._read_mono48k(wav)
        if ev.get('trim_silence', True):
            isl = _svc()._speech_islands(d)
            a, b = _svc()._pick_island(d, isl, ev.get('take', 'loudest'))
            if len(isl) > 1:
                log(
                    f'[scene] WARN anchored line {i} "{ev["text"]}": the TTS '
                    f'rendered {len(isl)} takes '
                    f'({", ".join(f"{s / _svc()._SR:.2f}-{e / _svc()._SR:.2f}s" for s, e in isl)})'
                    f' — shipping the {ev.get("take", "loudest")} one '
                    f'({a / _svc()._SR:.2f}-{b / _svc()._SR:.2f}s). Short prompts make it '
                    f'restate; verify the kept take says what it should.'
                )
        else:
            a, b = 0, len(d)
        if ev.get('verify_text', True):
            _lv_verdict = _svc()._verify_line_text(d[a:b], ev['text'], out_dir, f'anchored line {i}', log_fn=log)
            if _lv_verdict is None:
                _lv_stats['unavailable'] += 1
            else:
                _lv_stats['checked'] += 1
                _lv_stats['passed' if _lv_verdict else 'failed'] += 1
        else:
            _lv_stats['opted_out'] += 1
        anchored.append({**ev, 'wav': wav, 'span': (a, b), 'dur': (b - a) / _svc()._SR})

    if not (spec.get('anchored_lines') or []):
        gates.file('line_verify', False, 'no anchored_lines in this spec')
    elif _lv_stats['checked']:
        gates.file('line_verify', True, '', _lv_stats)
    elif _lv_stats['unavailable']:
        gates.file(
            'line_verify',
            False,
            'no ASR interpreter reached any anchored line — transcripts shipped unverified',
            _lv_stats,
        )
    else:
        gates.file(
            'line_verify', False, f'verify_text=False on all {_lv_stats["opted_out"]} anchored line(s)', _lv_stats
        )
    return lines, anchored


# ── 3 ── timeline ────────────────────────────────────────────────────────────


def _at_time(v, tl: dict, default: float = 0.0) -> float:
    """Resolve a spec time: a number, {'mark': name}, or {'event': i,
    'at': 'start'|'end'} — each with an optional 'offset'."""
    if v is None:
        return float(default)
    if isinstance(v, (int, float)):
        return float(v)
    off = float(v.get('offset', 0.0))
    if 'mark' in v:
        return tl['marks'][v['mark']] + off
    ev_i = tl['events'][int(v['event'])]
    return ev_i['t1' if v.get('at') == 'end' else 't0'] + off


def _step_timeline(spec: dict, lines: list, anchored: list, log) -> dict:
    """Stage 3: audio placements + shot windows. Returns the timeline dict every
    later stage reads (`events`, `marks`, the named instants and the windows)."""
    head = float(spec.get('head_silence_s', 1.0))
    t = head
    events: list[dict] = []  # {'kind','t0','t1',...}
    for ev in lines:
        if 'text' in ev:
            events.append({'kind': 'line', 't0': t, 't1': t + ev['dur'], **ev})
            t = t + ev['dur'] + float(ev.get('pause_after_s', 0.9))
        elif 'sfx' in ev:
            # A one-shot in the running order — a recorded breath, cough or
            # laugh taking a dialogue beat's place. dur_s defaults to the FILE's
            # own length rather than a fixed 2 s: these are performances with a
            # natural end, and a hard-coded default silently truncates anything
            # longer (the yawns here run past 3 s). `tempo` re-times the take
            # the way it does for a line.
            dur = ev.get('dur_s')
            src = _svc()._audio_asset(ev['sfx'])
            if dur is None:
                dur = max(0.05, _svc()._audio_dur(src) - float(ev.get('src_start_s', 0.0)))
            dur = float(dur) / max(0.05, float(ev.get('tempo', 1.0)))
            t0 = t - float(ev.get('overlap_s', 0.0))
            events.append({'kind': 'sfx', 't0': t0, 't1': t0 + dur, **ev, 'dur_s': dur})
            # pause_after_s, same as a line: a sigh that is a beat in the
            # dialogue needs the silence after it as much as a sentence does.
            t = max(t, t0 + dur * float(ev.get('advance_frac', 1.0))) + float(ev.get('pause_after_s', 0.0))
        elif 'beat' in ev:
            t += float(ev['beat'])

    dialogue_end = t
    # Optional wordless PULL-OUT beat that plays on after the last line, before
    # the fade to black: the camera keeps moving on the SAME still (see
    # _kb_zoom_at), so the scene opens up instead of cutting away.
    pull = spec.get('pullout') or {}
    pull_hold = float(pull.get('hold_s', 0.0)) if pull else 0.0
    pullout_end = dialogue_end + pull_hold
    fade_black = float(spec.get('fade_to_black_s', 1.2))
    card = spec.get('title_card') or {}
    card_dur = float(card.get('dur_s', 3.0)) if card else 0.0
    tail_shot = spec.get('tail_shot_id')
    tail_fadein = float(spec.get('tail_fade_in_s', 1.5))
    tail_hold = float(spec.get('tail_hold_s', 5.5))
    end_fade = float(spec.get('end_fade_s', 1.5))
    total = pullout_end + fade_black + card_dur + (tail_fadein + tail_hold if tail_shot else 0.0)
    card_t0 = pullout_end + fade_black
    tail_t0 = card_t0 + card_dur
    picture_end = total + end_fade  # screen fully black
    # The score is allowed to outlive the picture: `audio_tail_s` holds black
    # frames after the fade so a cue can keep resolving into the dark instead of
    # being guillotined the instant the image goes. The frames MUST be rendered —
    # the mux runs -shortest, so audio past the last frame is simply discarded.
    audio_tail = float(spec.get('audio_tail_s', 0.0))
    audio_end = picture_end + audio_tail

    # Named instants a spec can hang a music cue on, so cue times survive any
    # change in line durations instead of being hand-typed seconds.
    #   'end'       — the last visible frame (screen black)
    #   'audio_end' — the end of the master, i.e. `end` + audio_tail_s
    marks = {
        'start': 0.0,
        'dialogue_end': dialogue_end,
        'pullout_start': dialogue_end,
        'pullout_end': pullout_end,
        'card_start': card_t0,
        'card_end': tail_t0,
        'tail_start': tail_t0,
        'total': total,
        'end': picture_end,
        'picture_end': picture_end,
        'audio_end': audio_end,
    }
    tl = {
        'events': events,
        'marks': marks,
        'head': head,
        'dialogue_end': dialogue_end,
        'pull': pull,
        'pull_hold': pull_hold,
        'pullout_end': pullout_end,
        'fade_black': fade_black,
        'card': card,
        'card_dur': card_dur,
        'card_t0': card_t0,
        'tail_shot': tail_shot,
        'tail_fadein': tail_fadein,
        'tail_hold': tail_hold,
        'tail_t0': tail_t0,
        'end_fade': end_fade,
        'total': total,
        'picture_end': picture_end,
        'audio_tail': audio_tail,
        'audio_end': audio_end,
    }

    # 3b ── place the anchored lines ─────────────────────────────────────────
    # Appended AFTER the running order is laid out, so every existing
    # {'event': i} reference in the spec (music cues, shot cut points) keeps the
    # index it already had. `align` says which END of the line meets the mark:
    # 'end' is the useful one for a word that has to LAND before something —
    # authoring "finish 0.4 s before the fade starts" should not require knowing
    # how long the TTS decided the word was.
    anchor_log: list[dict] = []
    for ev in anchored:
        t_anchor = _at_time(ev.get('at'), tl, dialogue_end)
        t0 = t_anchor - ev['dur'] if ev.get('align', 'end') == 'end' else t_anchor
        t0 = max(0.0, t0)
        events.append({'kind': 'line', 't0': t0, 't1': t0 + ev['dur'], **ev})
        anchor_log.append(
            {'speaker': ev['speaker'], 'text': ev['text'], 't0': round(t0, 2), 't1': round(t0 + ev['dur'], 2)}
        )
        log(
            f'[scene] anchored line "{ev["text"]}" ({ev["speaker"]}) '
            f'{t0:.2f}→{t0 + ev["dur"]:.2f}s '
            f'({ev.get("align", "end")} on {ev.get("at")})'
        )

    # shot windows: cut points come from the spec's per-shot 'until' event index
    # (the shot holds the screen until that dialogue event's cue time).
    shot_windows: list[dict] = []
    t_cursor = 0.0
    for shot in spec['shots']:
        cue = shot.get('until_event')
        if cue is None:
            continue  # tail shot — appended below
        ev = events[cue]
        t_cut = ev['t0'] + float(shot.get('cut_offset_s', 0.0))
        shot_windows.append({'id': shot['id'], 't0': t_cursor, 't1': t_cut, 'shot': shot})
        t_cursor = t_cut
    # last dialogue shot runs to dialogue_end
    for shot in spec['shots']:
        if shot.get('last_dialogue_shot'):
            shot_windows.append({'id': shot['id'], 't0': t_cursor, 't1': dialogue_end, 'shot': shot})
            t_cursor = dialogue_end
    # the pull-out is its own window on an already-used still, with its own zoom
    # span — continuous with the dialogue framing, so it reads as one long take.
    if pull_hold > 0:
        shot_windows.append(
            {
                'id': pull.get('shot_id', shot_windows[-1]['id']),
                't0': dialogue_end,
                't1': pullout_end,
                'shot': _svc().shot_by_id_spec(spec, pull.get('shot_id', shot_windows[-1]['id'])),
                'zoom': tuple(pull['zoom']) if pull.get('zoom') else None,
                'focus_xy': tuple(pull['focus_xy']) if pull.get('focus_xy') else None,
            }
        )

    tl['anchor_log'] = anchor_log
    tl['shot_windows'] = shot_windows
    return tl
