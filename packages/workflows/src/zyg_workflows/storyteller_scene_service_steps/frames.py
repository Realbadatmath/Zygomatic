# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""storyteller_scene_service_steps — Steps 6 and 7: the rendered frames, the encode/mux and the scene state record."""

from __future__ import annotations

from zyg_workflows.storyteller_scene_service_steps.stills import (
    Image,
    ImageEnhance,
    ImageFilter,
    _GateReceipts,
    _seal,
    _svc,
    exe,
    json,
    math,
    np,
    os,
    shutil,
    subprocess,
    time,
)
from zyg_workflows.storyteller_scene_service_steps.timeline import (
    _at_time,
)

# ── 6 ── frames ──────────────────────────────────────────────────────────────


def _window_view(wnd: dict, t_abs: float, shot_by_id: dict) -> tuple:
    """(z, focus_xy) of a shot window's camera at t_abs. Split out of
    _shot_frame so an effect that has to know where a point of the PLATE
    sits on the delivered frame — the candle the reveal spreads from — reads
    the same camera the picture is cut with."""
    sid, t0, t1 = wnd['id'], wnd['t0'], wnd['t1']
    s = shot_by_id[sid]
    fx = s.get('fx', {})
    tt = 0.0 if t1 <= t0 else max(0.0, min(1.0, (t_abs - t0) / (t1 - t0)))
    mode = fx.get('kenburns', 'push_in')
    amount = float(fx.get('kb_amount', 0.06))
    zoom = wnd.get('zoom') or fx.get('kb_zoom')
    focus_xy = wnd.get('focus_xy') or fx.get('focus_xy')
    # zoom is a FRACTION OF THE IMAGE (1.0 == whole frame). _zoom_frame sizes
    # its window as base/z, so the number means the same framing whether or
    # not this still happens to be upscaled — do NOT rescale it by the base.
    keys = wnd.get('kb_keys') or fx.get('kb_keys')
    if keys:
        return _svc()._kb_keys_at(tt, keys)
    z = _svc()._kb_zoom_at(tt, mode, amount, zoom)
    return z, _svc()._kb_focus_at(tt, mode, amount, fx.get('focus', 'center'), focus_xy)


def _shot_frame(wnd: dict, t_abs: float, fx_ctx: dict, cam_t: float | None = None) -> Image.Image:
    """One delivered frame of a shot window at t_abs.

    `cam_t` freezes the CAMERA at a different instant than the effects run
    at. Only the fade to black uses it: that beat holds the pull-out's last
    framing, and before this it did so by rendering the whole frame at
    wnd['t1'] — which froze the fire along with the camera, so a flame that
    had been guttering for six seconds went dead still for the 1.2 s the
    audience spends watching it dim. The framing is what has to hold there,
    not time.
    """
    W, H = fx_ctx['W'], fx_ctx['H']
    shot_by_id, bases, route_ctxs = fx_ctx['shot_by_id'], fx_ctx['bases'], fx_ctx['route_ctxs']
    sid = wnd['id']
    s = shot_by_id[sid]
    fx = s.get('fx', {})
    z, focus = _window_view(wnd, t_abs if cam_t is None else cam_t, shot_by_id)
    # Base-space overlays are cut with the SAME window as the plate and
    # composited BEFORE the resize, so they are registered to the picture
    # through the whole move and are downsampled with it.
    overlays = []
    rc = route_ctxs.get(sid)
    if rc is not None:
        _svc()._route_advance(rc, t_abs)
        overlays.append((rc['origin'], rc['rope_ov']))
        if rc['marks_ov'] is not None:
            overlays.append((rc['origin'], rc['marks_ov']))
    for sm in [fx['smoke']] if isinstance(fx.get('smoke'), dict) else list(fx.get('smoke') or ()):
        overlays.append(_svc()._draw_smoke(bases[sid].size, sm, t_abs))
    # The bird is timed from when its SHOT arrives, not from the top of the
    # scene: it is authored as "n seconds after the harbour appears", and
    # the harbour's arrival moves whenever a line above it re-renders.
    bird = fx.get('bird')
    if bird:
        bv = _svc()._draw_bird(bases[sid].size, bird, t_abs - wnd['t0'] - float(bird.get('t0_rel', 0.0)))
        if bv is not None:
            overlays.append(bv)
    if overlays:
        box = _svc()._zoom_box(bases[sid], z, focus)
        crop = _svc()._compose_overlays(bases[sid].crop(box), box, overlays)
        img = crop if crop.size == (W, H) else crop.resize((W, H), Image.LANCZOS)
    else:
        img = _svc()._zoom_frame(bases[sid], W, H, z, focus)
    fl = _svc()._flicker_factor(t_abs, float(fx.get('flicker', 0.0)))
    if fl != 1.0:
        img = ImageEnhance.Brightness(img).enhance(fl)
    # The flame itself, lit on the frame the room flicker has already been
    # applied to and BEFORE the grade — so the warm/vignette/grain that make
    # the plate a photograph run over the fire too, instead of leaving it
    # sitting on top as a clean gradient.
    flame = fx.get('flame')
    if flame:
        box = _svc()._zoom_box(bases[sid], z, focus)
        bw, bh = bases[sid].size
        fax, fay = flame.get('anchor', (0.5, 0.5))
        _fx = (float(fax) * bw - box[0]) / max(1, box[2] - box[0]) * W
        _fy = (float(fay) * bh - box[1]) / max(1, box[3] - box[1]) * H
        img = _svc()._flame_apply(img, flame, _fx, _fy, z, t_abs)
    # The water, on the same terms as the flame and for the same reason —
    # before the grade, so the warm/vignette/grain run over the moving
    # surface too instead of sitting on top of it.
    water = fx.get('water')
    if water:
        img = _svc()._water_apply(img, water, _svc()._zoom_box(bases[sid], z, focus), bases[sid].size, z, t_abs)
    part = fx.get('particles')
    if part:
        ov = fx_ctx['draw_particles'](W, H, part, (t_abs * 0.10) % 1.0, seed=42)
        ov = ov.filter(ImageFilter.GaussianBlur(0.8))
        a_img = np.asarray(img, dtype=np.float32)
        a_ov = np.asarray(ov, dtype=np.float32) * float(fx.get('particle_gain', 0.5))
        img = Image.fromarray(np.clip(255 - (255 - a_img) * (255 - a_ov) / 255, 0, 255).astype(np.uint8))
    return _svc()._grade(
        img,
        warm=float(fx.get('warm', 0.6)),
        vignette=float(fx.get('vignette', 0.28)),
        grain=float(fx.get('grain', 5.0)),
        rng=fx_ctx['grain_rng'],
    )


def _frame_head_reveal(img: Image.Image, t_abs: float, reveal: dict, fx_ctx: dict, shot_windows: list, log):
    """The candle reveal, multiplied over whatever the head frames rendered."""
    W, H = fx_ctx['W'], fx_ctx['H']
    rv_sid = reveal.get('shot_id') or shot_windows[0]['id']
    rv_wnd = next((w for w in shot_windows if w['id'] == rv_sid and w['t0'] <= t_abs < w['t1']), None)
    if rv_wnd is None:
        # A mistyped shot_id, or a reveal that outlives its shot's cut,
        # would otherwise light the frame with a camera that is not on
        # screen — say so once rather than fall back in silence.
        if not reveal.get('_fallback_warned'):
            log(
                f"[scene] WARN reveal shot_id '{rv_sid}' has no window at "
                f"{t_abs:.2f}s — using the first window's camera"
            )
            reveal['_fallback_warned'] = True
        rv_wnd = shot_windows[0]
    z, focus = _window_view(rv_wnd, t_abs, fx_ctx['shot_by_id'])
    base = fx_ctx['bases'][rv_wnd['id']]
    bx0, by0, bx1, by1 = _svc()._zoom_box(base, z, focus)
    ax, ay = reveal.get('anchor', (0.5, 0.5))
    sx = (float(ax) * base.width - bx0) / max(1, bx1 - bx0) * W
    sy = (float(ay) * base.height - by0) / max(1, by1 - by0) * H
    d_max = max(math.hypot(cx - sx, cy - sy) for cx in (0.0, float(W)) for cy in (0.0, float(H))) / W
    rv = _svc()._reveal_at(reveal, t_abs, d_max)
    if rv is None:
        return img
    R, gain = rv
    # The halo breathes with the flame: the same deterministic
    # flicker the plate gets, so the two never disagree. Coupled
    # through the SQUARE ROOT because the light goes as R² — a
    # first cut scaled R by 1.5×(fl−1) and, squared, that made every
    # pixel still on the slope throb at ~3× the plate's amplitude and
    # then stop dead at full_at_s (found in review). With √fl the
    # far field flickers by exactly what the plate already does,
    # and nothing changes when the mask goes.
    fl = _svc()._flicker_factor(t_abs, float(reveal.get('flicker', 0.035)), seed=int(reveal.get('seed', 7)))
    light = _svc()._reveal_light(W, H, (sx, sy), R * math.sqrt(max(0.0, fl)))
    light = light * np.float32(gain)
    a_img = np.asarray(img, dtype=np.float32) * light[..., None]
    return Image.fromarray(np.clip(a_img, 0, 255).astype(np.uint8))


def _frames_context(spec: dict, stills: dict, W: int, H: int, log, tl: dict) -> dict:
    """The bases, the course overlays and the camera inputs every frame reads."""
    from zyg_workflows.pipeline_effects import _draw_particles

    # A still only ever framed at 1× is loaded at delivery size. One that gets
    # zoomed INTO uses the hi-res base built (and hand-repaired) in stage 1b2 —
    # so the close end of the move is native pixels rather than an interpolated
    # blow-up of a 1344-wide render.
    base_scale = _svc()._base_scale_for(spec)
    bases = {}
    for sid, p in stills.items():
        hp = _svc()._hires_path(p)
        if os.path.isfile(hp):
            bases[sid] = Image.open(hp).convert('RGB')
            log(f'[scene] base {sid}: hi-res {bases[sid].size} (×{bases[sid].width / W:.2f})')
            continue
        s = min(float(base_scale.get(sid, 1.0)), 2.0)
        src = Image.open(p).convert('RGB')
        bases[sid] = (
            _svc()._esrgan_resize(src, int(round(W * s)), int(round(H * s)), log_fn=log)
            if s >= _svc()._HIRES_MIN
            else src.resize((W, H), Image.LANCZOS)
        )

    # Courses drawn on a chart. The reveal window is authored against the same
    # events/marks the mix is, so if a line re-renders longer the rope simply
    # draws for longer with it instead of finishing under a sentence that is
    # still going.
    route_ctxs: dict = {}
    for shot in spec['shots']:
        if not shot.get('route'):
            continue
        drw = shot['route'].get('draw') or {}
        rt0 = _at_time(drw.get('from'), tl, tl['tail_t0'])
        rt1 = _at_time(drw.get('to'), tl, rt0 + 6.0)
        route_ctxs[shot['id']] = _svc()._route_context(shot, bases[shot['id']].size, rt0, rt1, log_fn=log)
        log(f'[scene] course on {shot["id"]}: draws {rt0:.2f}→{rt1:.2f}s, {len(route_ctxs[shot["id"]]["marks"])} ports')

    return {
        'W': W,
        'H': H,
        'bases': bases,
        'route_ctxs': route_ctxs,
        'shot_by_id': {s['id']: s for s in spec['shots']},
        'grain_rng': np.random.RandomState(99),
        'draw_particles': _draw_particles,
    }


def _step_frames(spec: dict, out_dir: str, W: int, H: int, log, stills: dict, tl: dict) -> dict:
    """Stage 6: render every delivered frame as a jpg in `_frames`."""
    framedir = os.path.join(out_dir, '_frames')
    if os.path.isdir(framedir):
        shutil.rmtree(framedir)
    os.makedirs(framedir)
    n_frames = int(round(tl['audio_end'] * _svc()._FPS))

    # The tail move is authored to finish LATER than the picture does: with an
    # overshoot the camera is still travelling when the fade takes the screen,
    # so the scene ends approaching its subject rather than arriving at it (an
    # arrival is a full stop; a fade mid-move leaves the shot open). The window
    # the zoom interpolates over therefore runs past the last visible frame.
    # Measured from BLACK, not from the start of the fade — the statement being
    # made is "the move had this much still to run when the screen went". With
    # no overshoot the window ends at `total` exactly as it always did, so specs
    # that do not ask for this are untouched.
    tail_over = float(spec.get('tail_zoom_overshoot_s', 0.0))
    tail_win_t1 = (tl['picture_end'] + tail_over) if tail_over > 0 else tl['total']
    head_fade = float(spec.get('fade_in_s', 0.0))
    # Black held BEFORE the fade begins. Not the same knob as head_silence_s:
    # that governs when the first line lands, this governs when the picture
    # starts arriving, and a scene that opens on sound alone needs both.
    head_delay = float(spec.get('fade_in_delay_s', 0.0))
    # A candle reveal REPLACES the head fade (2026-08-25): the picture does not
    # arrive from black as a whole, it is lit outward from one flame on the
    # plate — see _reveal_light. Authored in base-normalised coordinates like
    # the smoke anchor, and cut through the same camera as the picture, so the
    # light stays on the candle while the push-in moves the frame under it.
    reveal = spec.get('reveal')
    if reveal and (head_fade > 0 or head_delay > 0):
        log(
            '[scene] WARN both `reveal` and fade_in_s/fade_in_delay_s are set — '
            'the reveal takes the head, the fade is ignored'
        )
        head_fade = 0.0
        head_delay = 0.0  # so scene_state does not report a delay the frames lack
    if reveal:
        log(
            f'[scene] candle reveal: flame at {tuple(reveal.get("anchor", (0.5, 0.5)))}, '
            f'flame only until {float(reveal.get("delay_s", 3.0)):.1f}s, full picture at '
            f'{float(reveal.get("delay_s", 3.0)) + float(reveal.get("dur_s", 5.0)):.1f}s'
        )

    fx_ctx = _frames_context(spec, stills, W, H, log, tl)
    shot_windows = tl['shot_windows']
    pullout_end, card_t0, picture_end = tl['pullout_end'], tl['card_t0'], tl['picture_end']
    tail_t0, tail_shot, total = tl['tail_t0'], tl['tail_shot'], tl['total']
    card, fade_black, end_fade, tail_fadein = tl['card'], tl['fade_black'], tl['end_fade'], tl['tail_fadein']

    for f in range(n_frames):
        t_abs = f / _svc()._FPS
        img = None
        # Everything up to pullout_end is a shot window (the pull-out is just
        # the last one); after that comes the fade to black, the card, the tail.
        if t_abs < pullout_end:
            for wnd in shot_windows:
                if wnd['t0'] <= t_abs < wnd['t1'] or wnd is shot_windows[-1]:
                    if wnd['t0'] <= t_abs:
                        img = _shot_frame(wnd, t_abs, fx_ctx)
                    if wnd['t0'] <= t_abs < wnd['t1']:
                        break
            if img is None:
                img = _shot_frame(shot_windows[0], t_abs, fx_ctx)
        elif t_abs < card_t0:
            # hold the pull-out's LAST framing and dim it, so the fade to black
            # does not jump back to a different crop on its first frame
            k = 1.0 - (t_abs - pullout_end) / fade_black
            last = shot_windows[-1]
            img = ImageEnhance.Brightness(_shot_frame(last, t_abs, fx_ctx, cam_t=last['t1'])).enhance(max(0.0, k))
        elif t_abs >= picture_end:
            img = Image.new('RGB', (W, H), (0, 0, 0))  # audio_tail_s of black
        elif t_abs < tail_t0 or not tail_shot:
            a = min(1.0, (t_abs - card_t0) / max(0.4, float(card.get('fade_in_s', 0.8))))
            img = _svc()._title_card(W, H, card.get('text', ''), a) if card else Image.new('RGB', (W, H), (0, 0, 0))
        else:
            img = _shot_frame(
                {'id': tail_shot, 't0': tail_t0, 't1': tail_win_t1, 'shot': fx_ctx['shot_by_id'][tail_shot]},
                t_abs,
                fx_ctx,
            )
            if t_abs < tail_t0 + tail_fadein:
                img = ImageEnhance.Brightness(img).enhance((t_abs - tail_t0) / tail_fadein)
            if t_abs > total:
                img = ImageEnhance.Brightness(img).enhance(max(0.0, 1.0 - (t_abs - total) / end_fade))
        # Opening fade from black. Sits OUTSIDE the branch chain because it is a
        # property of the head of the scene, not of whichever window happens to
        # own that instant — it multiplies whatever the first frames render.
        if reveal and t_abs < pullout_end:
            img = _frame_head_reveal(img, t_abs, reveal, fx_ctx, shot_windows, log)
        elif head_fade > 0 and t_abs < head_delay + head_fade:
            img = ImageEnhance.Brightness(img).enhance(max(0.0, (t_abs - head_delay) / head_fade))
        img.save(os.path.join(framedir, f'f_{f:05d}.jpg'), quality=92)

    return {
        'framedir': framedir,
        'n_frames': n_frames,
        'route_ctxs': fx_ctx['route_ctxs'],
        'shot_by_id': fx_ctx['shot_by_id'],
        'reveal': reveal,
        'head_fade': head_fade,
        'head_delay': head_delay,
        'tail_win_t1': tail_win_t1,
    }


# ── 7 ── encode + mux ────────────────────────────────────────────────────────


def _step_encode(
    spec: dict,
    out_dir: str,
    slug: str,
    W: int,
    H: int,
    log,
    stills: dict,
    tl: dict,
    frames: dict,
    mixed: dict,
    t_start: float,
    gates: _GateReceipts,
) -> dict | None:
    """Stage 7: encode the frames against the master, mux the soft subtitle
    track, write scene_state.json. Returns build_scene's result dict or None."""
    framedir, master = frames['framedir'], mixed['master']
    video = os.path.join(out_dir, f'{slug}.mp4')
    r = subprocess.run(
        [
            exe('ffmpeg'),
            '-loglevel',
            'error',
            '-y',
            '-framerate',
            str(_svc()._FPS),
            '-i',
            os.path.join(framedir, 'f_%05d.jpg'),
            '-i',
            master,
            '-c:v',
            'libx264',
            '-crf',
            '18',
            '-pix_fmt',
            'yuv420p',
            '-c:a',
            'aac',
            '-b:a',
            '192k',
            '-shortest',
            video,
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0 or not os.path.isfile(video):
        log(f'[scene] encode failed: {r.stderr[:400]}')
        gates.audit()
        return None
    shutil.rmtree(framedir, ignore_errors=True)

    # ── subtitles (soft, toggleable) ─────────────────────────────────────────
    srt_path = None
    if spec.get('subtitles', True):
        srt_path = os.path.join(out_dir, f'{slug}.srt')
        n_cues = _svc()._write_srt(tl['events'], srt_path, limit_s=tl['picture_end'])
        _svc()._srt_to_vtt(srt_path, srt_path.replace('.srt', '.vtt'))
        if n_cues and _svc()._mux_subs(video, srt_path, lang=str(spec.get('subtitle_lang', 'eng')), log_fn=log):
            log(f'[scene] subtitles: {n_cues} cues, soft mov_text track (off by default) + .srt/.vtt sidecars')
        else:
            log('[scene] subtitles: NOT muxed — sidecars written only')

    # Content credential on the scene mp4, after the subtitle mux has replaced it for the
    # last time and before scene_state.json records what was shipped. Fail-safe: an
    # unsigned scene is logged, never a failed build.
    _seal.seal(video, pipeline='storyteller_scene', run_id=slug, log_fn=log)

    state = _scene_state(spec, slug, W, H, video, stills, tl, frames, mixed, srt_path, t_start, gates)
    state_p = os.path.join(out_dir, 'scene_state.json')
    with open(state_p, 'w') as fh:
        json.dump(state, fh, indent=1)
    log(f'[scene] DONE {video} ({state["total_s"]}s, {state["elapsed_s"]}s build)')
    return {'video': video, 'master_audio': master, 'stills': stills, 'timeline': state, 'state': state_p}


def _scene_state(
    spec: dict,
    slug: str,
    W: int,
    H: int,
    video: str,
    stills: dict,
    tl: dict,
    frames: dict,
    mixed: dict,
    srt_path: str | None,
    t_start: float,
    gates: _GateReceipts,
) -> dict:
    """scene_state.json — the build's own account of what it shipped."""
    reveal, route_ctxs = frames['reveal'], frames['route_ctxs']
    tail_shot, shot_windows = tl['tail_shot'], tl['shot_windows']
    bed_out_t = mixed['bed_out_t']
    return {
        'spec_slug': slug,
        'video': video,
        'master_audio': mixed['master'],
        'stills': stills,
        'width': W,
        'height': H,
        'fps': _svc()._FPS,
        'total_s': round(tl['audio_end'], 2),
        'picture_end_s': round(tl['picture_end'], 2),
        'audio_tail_s': round(tl['audio_tail'], 2),
        'dialogue_end_s': round(tl['dialogue_end'], 2),
        'bed_fade_out_s': (round(bed_out_t, 2) if bed_out_t is not None else None),
        'subtitles': srt_path,
        'bed_fade_in_s': float(spec.get('bed_fade_in_s', 0.0)),
        'head_silence_s': tl['head'],
        'picture_fade_in_s': frames['head_fade'],
        'picture_fade_in_delay_s': frames['head_delay'],
        'reveal': (
            {
                'shot_id': reveal.get('shot_id') or shot_windows[0]['id'],
                'anchor': list(reveal.get('anchor', (0.5, 0.5))),
                'flame_r_frac': float(reveal.get('flame_r_frac', 0.03)),
                'flame_in_s': float(reveal.get('flame_in_s', 1.0)),
                'delay_s': float(reveal.get('delay_s', 3.0)),
                'dur_s': float(reveal.get('dur_s', 5.0)),
                'ease': float(reveal.get('ease', 2.0)),
                'full_at_s': round(float(reveal.get('delay_s', 3.0)) + float(reveal.get('dur_s', 5.0)), 2),
            }
            if reveal
            else None
        ),
        'routes': {
            sid: {
                'draw_s': [round(rc['t0'], 2), round(rc['t1'], 2)],
                'ports': [{'name': m['name'], 'at_s': round(m['t_arrive'], 2)} for m in rc['marks']],
            }
            for sid, rc in route_ctxs.items()
        },
        # what the tail move actually reached before the screen went black —
        # the authored kb_zoom end is deliberately never arrived at
        'tail_zoom_at_black': (
            round(
                _svc()._tail_z_at_black(
                    frames['shot_by_id'][tail_shot], tl['picture_end'], tl['tail_t0'], frames['tail_win_t1']
                ),
                3,
            )
            if tail_shot
            else None
        ),
        'marks': {k: round(v, 2) for k, v in tl['marks'].items()},
        'events': [
            {k: (round(v, 3) if isinstance(v, float) else v) for k, v in e.items() if k not in ('wav', 'span')}
            for e in tl['events']
        ],
        'anchored_lines': tl['anchor_log'],
        'shot_windows': [
            {'id': w['id'], 't0': round(w['t0'], 2), 't1': round(w['t1'], 2), 'zoom': w.get('zoom')}
            for w in shot_windows
        ],
        'music': mixed['music_log'],
        'voice_stem_lufs': mixed['stem_lufs'],
        'bed_lufs': float(spec.get('bed_lufs', -42.0)),
        'voices': {
            k: {'ref': v.get('ref'), 'pitch_semitones': float(v.get('pitch_semitones', 0.0))}
            for k, v in spec.get('voices', {}).items()
        },
        'sfx_licences': (
            'all bed/sfx files are CC0 (asset_library_sfx_meta.json); '
            'generated music is ACE-Step 1.5 (MIT weights)'
            + (
                '; explicit-file cues ('
                + ', '.join(sorted({c['file'] for c in (spec.get('music') or []) if c.get('file')}))
                + ') carry their own library sidecar licence'
                if any(c.get('file') for c in (spec.get('music') or []))
                else ''
            )
        ),
        'elapsed_s': round(time.time() - t_start, 1),
        'gate_receipts': dict(gates.receipts),
        'gate_audit': gates.audit(),
    }
