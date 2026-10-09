# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.briefing_video.episode — render_episode and the retention sweep.

Moved verbatim out of briefing_video.py (lines 1595-1956); zero logic changes.
"""

from __future__ import annotations

import functools

from zyg_workflows.briefing_video.base import (
    _AUDIO_ARGS,
    _dur,
    _nvenc_available,
    _run,
    _seal,
    _zyg_log,
    exe,
    os,
    shutil,
    time,
)

from zyg_workflows.briefing_video.tts import seed_path, speak, speak_batch

from zyg_workflows.briefing_video.assemble import (
    _build_chapters,
    _concat,
    _ffmetadata,
    _loudnorm,
    _render_segment,
    _ts,
    qc,
)


# ── the episode ─────────────────────────────────────────────────────────────

#: Which provenance pipeline a channel's theme belongs to. The two betting channels are
#: 'sports', the two finance ones 'market'; anything else seals as a plain 'briefing'.
_SEAL_PIPELINE = {'arena': 'sports', 'tokitoki': 'sports', 'stocks': 'market', 'crypto': 'market'}


def _emit(log, level, msg):
    """Send one line to the caller's log sink.

    log is the optional ``log(level, msg)`` callable render_episode was given;
    without one the line goes to stdout in the `[BRIEF|LEVEL] msg` shape every
    briefing channel's console already shows.
    """
    if log:
        log(level, msg)
    else:
        _zyg_log.info(f'[BRIEF|{level}] {msg}')


def _build_panels(spec, jingle_in, jingle_out):
    """Flatten an episode spec into the ordered panel list the renderer walks.

    spec is the render_episode spec; jingle_in/jingle_out are the stinger paths
    (only their existence is read here, to decide the board's narration lead-in
    and the outro card's hold). Returns [board, *item panels, outro], each panel
    a dict with kind/image/text/chapter/min_seconds/ken_burns.
    """
    panels = [
        {
            'kind': 'board',
            'image': spec['board_png'],
            'text': spec.get('welcome_text') or '',
            'chapter': spec.get('welcome_chapter') or 'Welcome & today’s list',
            'min_seconds': float(spec.get('board_seconds') or 10),
            # the narrator waits for the intro stinger to fade (≈5 s asset)
            'lead_in': 5.2 if (jingle_in and os.path.isfile(jingle_in)) else 0.0,
            'ken_burns': False,
        }
    ]
    for it in spec.get('items') or []:
        for i, p in enumerate(it.get('panels') or []):
            panels.append(
                {
                    'kind': 'item',
                    'image': p.get('image'),
                    'text': p.get('text') or '',
                    'chapter': it.get('chapter') if i == 0 else None,
                    'min_seconds': float(p.get('min_seconds') or 0),
                    'ken_burns': bool(p.get('ken_burns')),
                }
            )
    # 12 s, not the ~8 s the outro line actually takes: YouTube discards the WHOLE
    # chapter list if any chapter is under 10 s, so a short end card would cost the
    # entire playbar. It also gives the subscribe beat room to land. With an outro
    # stinger the card holds 14 s so the full 5 s tail fits after the line.
    panels.append(
        {
            'kind': 'outro',
            'image': spec['outro_png'],
            'text': spec.get('outro_text') or '',
            'chapter': spec.get('outro_chapter') or 'Outro',
            'min_seconds': 14.0 if (jingle_out and os.path.isfile(jingle_out)) else 12.0,
            'ken_burns': False,
        }
    )
    return panels


def _narrate_panels(panels, spec, work_dir, seed, log, emit, stop, progress):
    """Give every panel with text a narration wav, in place.

    One batched engine run for the whole episode, then `speak()` per panel for
    anything the batch did not deliver. See speak_batch's docstring for why.
    Sets panel['wav'] on every panel ('' when it will hold silently) and returns
    how many of them ended up with audio.
    """
    total_panels = len(panels)
    _texts = [(i, p['text']) for i, p in enumerate(panels) if (p['text'] or '').strip()]
    _batched = speak_batch(_texts, work_dir, seed_wav=seed, voice_id=spec.get('voice_id', ''), log=log)
    for i, p in enumerate(panels):
        stop()
        if not (p['text'] or '').strip():
            p['wav'] = ''
            continue
        if _batched.get(i):
            p['wav'] = _batched[i]
            continue
        wav = os.path.join(work_dir, f'seg_{i:03d}.wav')
        if speak(p['text'], wav, seed_wav=seed, voice_id=spec.get('voice_id', ''), log=log):
            p['wav'] = wav
        else:
            p['wav'] = ''
            emit('WARNING', f'panel {i} produced no audio — it will hold silently')
        if progress:
            progress('Narrate', 32 + int(23 * (i + 1) / total_panels))
    return sum(1 for p in panels if p.get('wav'))


def _apply_tempo(panels, emit):
    """Speed every narration wav up by ZYG_BRIEF_TEMPO (operator 2026-08-08).

    Pitch-preserving atempo on every narration wav. 1.07 reads noticeably
    brisker without chipmunking; ZYG_BRIEF_TEMPO=1.0 disables. Rewrites
    panel['wav'] in place for each panel whose faster render came out usable.
    """
    try:
        tempo = float(os.environ.get('ZYG_BRIEF_TEMPO', '1.07') or 1.07)
    except ValueError:
        tempo = 1.07
    if abs(tempo - 1.0) <= 0.005:
        return
    n_t = 0
    for p in panels:
        if not p.get('wav'):
            continue
        fast = p['wav'].replace('.wav', '.tempo.wav')
        r = _run([exe('ffmpeg'), '-y', '-i', p['wav'], '-af', f'atempo={tempo:g}', fast], timeout=300)
        if r.returncode == 0 and os.path.isfile(fast) and os.path.getsize(fast) > 1000:
            p['wav'] = fast
            n_t += 1
    emit('INFO', f'narration pace: atempo {tempo:g} applied to {n_t} panel(s)')


def _render_panels(panels, work_dir, use_nvenc, emit, stop, progress):
    """Encode one clip per panel and time the episode as it goes.

    Panels with no image on disk, and panels ffmpeg refused, are skipped with a
    warning. Returns (parts, marks, seconds): the clip paths to concat, the
    chapter marks at their running offsets, and the total duration.
    """
    total_panels = len(panels)
    parts, marks, t = [], [], 0.0
    for i, p in enumerate(panels):
        stop()
        if not p.get('image') or not os.path.isfile(p['image']):
            emit('WARNING', f'panel {i} has no image — skipped')
            continue
        clip = os.path.join(work_dir, f'part_{i:03d}.mp4')
        made, dur = _render_segment(
            p['image'],
            p.get('wav'),
            clip,
            use_nvenc,
            min_seconds=p['min_seconds'],
            ken_burns=p['ken_burns'],
            lead_in=float(p.get('lead_in') or 0.0),
        )
        if not made:
            emit('WARNING', f'panel {i} failed to encode — skipped')
            continue
        if p.get('chapter'):
            marks.append({'at': t, 'title': p['chapter']})
        parts.append(made)
        t += dur
        if progress:
            progress('Render', 55 + int(25 * (i + 1) / total_panels))
    return parts, marks, t


def _mix_stingers(mastered, panels, t, work_dir, jingle_in, jingle_out, emit):
    """Mix the intro/outro stingers under the mastered audio (operator 2026-08-08).

    Both assets are ~5 s with the fade envelope BAKED IN (1 s fade-in, full
    body, fade-out across seconds 4-5). Intro sits at t=0 under the silent
    narration lead-in; outro is anchored after the spoken outro line, ending
    with the video. Mixed post-loudnorm with normalize=0 so speech level is
    untouched. Returns the path to deliver — the mixed file when it worked,
    `mastered` unchanged (with a warning) whenever it did not.
    """
    if not (jingle_in or jingle_out):
        return mastered
    try:
        outro_wav_dur = _dur(panels[-1].get('wav')) if panels[-1].get('wav') else 8.0
        j_inputs, j_filters, j_tags = [], [], []
        idx = 1
        if jingle_in and os.path.isfile(jingle_in):
            j_inputs += ['-i', jingle_in]
            j_filters.append(f'[{idx}:a]adelay=0|0[j{idx}]')
            j_tags.append(f'[j{idx}]')
            idx += 1
        if jingle_out and os.path.isfile(jingle_out):
            # start after the spoken line (outro panel holds 14 s), but
            # never so late that the 5 s asset would be cut off at the end
            out_at = (t - 14.0) + outro_wav_dur + 0.6
            out_at = max(0.0, min(out_at, t - 5.2))
            ms = int(out_at * 1000)
            j_inputs += ['-i', jingle_out]
            j_filters.append(f'[{idx}:a]adelay={ms}|{ms}[j{idx}]')
            j_tags.append(f'[j{idx}]')
            idx += 1
        if j_tags:
            jingled = os.path.join(work_dir, 'jingled.mp4')
            fc = (
                ';'.join(j_filters) + f';[0:a]{"".join(j_tags)}amix=inputs={1 + len(j_tags)}:'
                f'duration=first:normalize=0[mix]'
            )
            r = _run(
                [exe('ffmpeg'), '-y', '-i', mastered]
                + j_inputs
                + ['-filter_complex', fc, '-map', '0:v', '-map', '[mix]', '-c:v', 'copy']
                + _AUDIO_ARGS
                + ['-movflags', '+faststart', jingled],
                timeout=600,
            )
            if r.returncode == 0 and os.path.isfile(jingled):
                mastered = jingled
                emit('INFO', 'intro/outro stingers mixed in')
            else:
                emit('WARNING', 'stinger mix failed — delivering without it')
    except Exception as _je:
        emit('WARNING', f'stinger mix raised ({_je!r}) — delivering without it')
    return mastered


def _mux_chapters(mastered, chapters, t, work_dir, out_dir, slug, emit):
    """Copy the mastered episode to its delivery path with chapter metadata.

    Embeds real chapter metadata too — YouTube reads the description, but every
    desktop player and the operator's own review pass reads the container. On a
    mux failure the mastered bytes are copied over instead, with a warning.
    Returns the delivered path (<out_dir>/<slug>.mp4).
    """
    meta = _ffmetadata(chapters, t, os.path.join(work_dir, 'chapters.ffmeta'))
    final = os.path.join(out_dir, f'{slug}.mp4')
    r = _run(
        [
            exe('ffmpeg'),
            '-y',
            '-i',
            mastered,
            '-i',
            meta,
            '-map_metadata',
            '1',
            '-c',
            'copy',
            '-movflags',
            '+faststart',
            final,
        ],
        timeout=600,
    )
    if r.returncode != 0 or not os.path.isfile(final):
        shutil.copy2(mastered, final)
        emit('WARNING', 'chapter metadata mux failed — delivered without it')
    return final


def _qc_gate(final, t, chapters, panels, rendered, spoken, out_dir, slug, emit):
    """Run the delivery QC gate and log every check.

    Returns (report, quarantined): the gate's own report dict, and the path the
    deliverable was renamed to when the gate failed (None when it passed, i.e.
    `final` is still the deliverable).
    """
    q = qc(
        final,
        t,
        chapters,
        production={
            'planned': len(panels),
            'rendered': rendered,
            'with_text': sum(1 for p in panels if (p.get('text') or '').strip()),
            'narrated': spoken,
        },
    )
    for c in q['checks']:
        emit(
            'INFO' if c['ok'] else 'ERROR',
            f'QC {"PASS" if c["ok"] else "FAIL"} — {c["name"]}{(": " + c["detail"]) if c["detail"] else ""}',
        )
    if not q['passed']:
        bad = os.path.join(out_dir, f'{slug}.QUARANTINED.mp4')
        os.replace(final, bad)
        return q, bad
    return q, None


def _write_sidecars(out_dir, slug, spec, chapters, panels):
    """Write the three text sidecars that travel with the episode.

    The description carries the playbar chapters (plus the disclaimer and the
    attribution note when the spec has them), the chapters file the same
    `mm:ss Title` lines alone, and the script file every spoken panel. Returns
    their three paths in that order.
    """
    desc = [spec.get('description_intro') or '', '']
    desc.append('CHAPTERS')
    for c in chapters:
        desc.append(f'{_ts(c["at"])} {c["title"]}')
    desc.append('')
    if spec.get('disclaimer'):
        desc += [spec['disclaimer'], '']
    if spec.get('attribution_note'):
        desc += [spec['attribution_note'], '']
    desc_path = os.path.join(out_dir, f'{slug}.description.txt')
    with open(desc_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(desc).strip() + '\n')

    chap_path = os.path.join(out_dir, f'{slug}.chapters.txt')
    with open(chap_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(f'{_ts(c["at"])} {c["title"]}' for c in chapters) + '\n')

    script_path = os.path.join(out_dir, f'{slug}.script.txt')
    with open(script_path, 'w', encoding='utf-8') as f:
        for p in panels:
            if (p.get('text') or '').strip():
                f.write(f'[{p.get("chapter") or p["kind"]}]\n{p["text"]}\n\n')
    return desc_path, chap_path, script_path


def render_episode(spec: dict, work_dir: str, out_dir: str, log=None, check_stop=None, progress=None) -> dict:
    """Build one briefing episode. Returns the delivery manifest.

    spec = {
      channel, theme, voice_seed, title, slug,
      welcome_text, board_png, board_seconds,
      items: [{chapter, panels: [{image, text, ken_burns}]}],
      outro_text, outro_lines, description_intro, disclaimer, attribution
    }
    """
    _log = functools.partial(_emit, log)

    def _stop():
        if check_stop:
            check_stop()

    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    seed = seed_path(spec.get('voice_seed') or '')
    if not seed:
        _log(
            'WARNING',
            f'voice seed {spec.get("voice_seed")!r} not in the pool — falling back to the deterministic voice-id pick',
        )
    use_nvenc = _nvenc_available()
    _log('INFO', f'encoder: {"h264_nvenc" if use_nvenc else "libx264"}')

    # ── flatten the episode into panels ─────────────────────────────────────
    jingle_in = spec.get('jingle_intro') or ''
    jingle_out = spec.get('jingle_outro') or ''
    panels = _build_panels(spec, jingle_in, jingle_out)
    total_panels = len(panels)
    _log('INFO', f'{total_panels} panel(s) — {len(spec.get("items") or [])} item(s) + opening board + outro')

    # ── narrate ─────────────────────────────────────────────────────────────
    if progress:
        progress('Narrate', 32)
    spoken = _narrate_panels(panels, spec, work_dir, seed, log, _log, _stop, progress)
    if spoken == 0:
        return {'error': 'no narration audio was produced for any panel'}
    if spoken < total_panels * 0.6:
        _log('WARNING', f'only {spoken}/{total_panels} panels have audio')

    # ── pace (operator 2026-08-08: "a bit too slow") ────────────────────────
    _apply_tempo(panels, _log)

    # ── render + time each panel ────────────────────────────────────────────
    parts, marks, t = _render_panels(panels, work_dir, use_nvenc, _log, _stop, progress)
    if not parts:
        return {'error': 'no panels rendered'}

    silent = os.path.join(work_dir, 'joined.mp4')
    if not _concat(parts, silent, work_dir):
        return {'error': 'concat failed'}

    chapters, chap_warn = _build_chapters(marks, t)
    for w in chap_warn:
        _log('WARNING', f'chapters: {w}')

    mastered = os.path.join(work_dir, 'mastered.mp4')
    _loudnorm(silent, mastered, log=_log)

    # ── intro / outro stingers (operator 2026-08-08) ────────────────────────
    mastered = _mix_stingers(mastered, panels, t, work_dir, jingle_in, jingle_out, _log)

    slug = spec.get('slug') or 'episode'
    final = _mux_chapters(mastered, chapters, t, work_dir, out_dir, slug, _log)

    # ── content credential ──────────────────────────────────────────────────
    # Sealed here, once, on the finished container and before the QC gate: the gate
    # either passes the file through untouched or renames it to .QUARANTINED.mp4, and
    # a seal that travelled with a rename still describes the bytes it was made for.
    # Sealing after the gate would leave every quarantined file unsigned and every
    # re-delivery of one a second claim.
    _seal.seal(
        final,
        pipeline=_SEAL_PIPELINE.get(str(spec.get('department') or spec.get('theme') or '').lower(), 'briefing'),
        run_id=str(spec.get('run_id') or spec.get('id') or ''),
        log_fn=lambda m: _log('INFO', m),
    )

    # ── QC ──────────────────────────────────────────────────────────────────
    if progress:
        progress('QC Gates', 88)
    q, quarantined = _qc_gate(final, t, chapters, panels, len(parts), spoken, out_dir, slug, _log)
    if quarantined:
        return {'error': 'QC gates failed', 'qc': q, 'quarantined': quarantined}

    # ── description with the playbar chapters ───────────────────────────────
    desc_path, chap_path, script_path = _write_sidecars(out_dir, slug, spec, chapters, panels)

    return {
        'video': final,
        'description': desc_path,
        'chapters_file': chap_path,
        'script': script_path,
        'duration': round(t, 2),
        'chapters': chapters,
        'chapter_warnings': chap_warn,
        'qc': q,
        'panels': len(parts),
        'narrated_panels': spoken,
    }


# ── retention ───────────────────────────────────────────────────────────────


def retention_sweep(out_root: str, ttl_hours: float, log=print) -> dict:
    """Delete delivered episodes older than the TTL. Operator spec: 3 days."""
    removed, kept, freed = [], 0, 0.0
    if not os.path.isdir(out_root):
        return {'removed': [], 'kept': 0, 'freed_gb': 0.0}
    cutoff = time.time() - max(1.0, ttl_hours) * 3600.0
    for parent, dirs, _files in os.walk(out_root):
        for d in list(dirs):
            p = os.path.join(parent, d)
            # only sweep leaf job dirs (they contain the delivered mp4)
            try:
                if not any(f.endswith('.mp4') for f in os.listdir(p)):
                    continue
            except OSError as _exc:
                _zyg_log.debug('run directory skipped, listing failed: %s', _exc)
                continue
            try:
                mt = max(os.path.getmtime(os.path.join(p, f)) for f in os.listdir(p))
            except (OSError, ValueError) as _exc:
                _zyg_log.debug('run directory skipped, mtime unreadable: %s', _exc)
                continue
            if mt < cutoff:
                size = 0
                for dp, _dd, ff in os.walk(p):
                    for f in ff:
                        try:
                            size += os.path.getsize(os.path.join(dp, f))
                        except OSError as _exc:
                            _zyg_log.debug('size scan skipped a file: %s', _exc)
                shutil.rmtree(p, ignore_errors=True)
                removed.append(p)
                freed += size / 1e9
                log(f'[BRIEF-CLEANER] removed {p} ({size / 1e6:.0f} MB, older than {ttl_hours:.0f} h)')
            else:
                kept += 1
    return {'removed': removed, 'kept': kept, 'freed_gb': round(freed, 2)}
