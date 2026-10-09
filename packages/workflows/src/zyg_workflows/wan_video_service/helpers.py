# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""wan_video_service — The ComfyUI submit path, the prompt builder, the stitcher and the motion/interpolation helpers."""

from zyg_workflows.wan_video_service.constants import (
    _CAMERA_BY_SHOT,
    _CINEMATIC_WAN_SUFFIX,
    _CLIP_FPS,
    _CLIP_FRAMES,
    _EMOTION_PRIORITY,
    _GUIDANCE,
    _HEIGHT,
    _INFER_STEPS,
    _LIGHTNING_HIGH_LORA,
    _LIGHTNING_LOW_LORA,
    _MOTION_BY_EMOTION,
    _MOTION_FREEZE_THRESH,
    _N_CHAINED,
    _OUTPUT_FPS,
    _SCENE_MOTION_HINTS,
    _STATIC_SHOT_NEG,
    _WAN22,
    _WAN22_BOUNDARY_FRACTION,
    _WAN_ATTENTION,
    _WAN_COMFY_MODEL,
    _WAN_LIGHTNING,
    _WIDTH,
    _comfy,
    _zyg_log,
    exe,
    os,
    shutil,
    subprocess,
)

# ── Internal helpers ─────────────────────────────────────────────────────────


def _generate_via_comfyui(
    flux_image_meta: list,
    wan_dir: str,
    n_clips: int,
    log_fn,
    prompt_log_fn,
    visual_style,
    n_chained: int = _N_CHAINED,
    frames: int | None = None,
    steps: int | None = None,
    flow_shift: float | None = None,
) -> list:
    """ComfyUI-backed I2V with chained sub-clips, stitch, interpolate, motion retry.
    ``frames``/``steps`` override the per-sub-clip length/sampler steps (used by the
    ~5s test mode); ``flow_shift`` overrides scheduler shift (lower = more stable / less
    motion drift — used to steady multi-character faces and subtle FX). ``None`` keeps
    the per-shot defaults."""
    try:
        workflow = _comfy.load_workflow('wan22_i2v' if _WAN22 else 'wan_i2v')
        if _WAN22:
            log_fn(
                'WAN: Wan2.2 A14B dual-expert path active (ZYG_WAN22)'
                + (' + Lightning 4-step' if _WAN_LIGHTNING else '')
            )
    except _comfy.ComfyUIError as exc:
        log_fn(f'WAN: ComfyUI workflow load failed: {exc}')
        return []

    candidates = sorted(
        flux_image_meta,
        key=lambda m: _EMOTION_PRIORITY.get(m.get('emotion', 'neutral'), 1),
        reverse=True,
    )[:n_clips]

    results: list = []
    for c in candidates:
        idx = c.get('index', 0)
        src_path = c.get('path', '')
        if not src_path or not os.path.exists(src_path):
            log_fn(f'WAN: clip {idx} has no source FLUX image — skipping')
            continue

        prompt = _build_prompt(c, visual_style=visual_style)
        if prompt_log_fn:
            try:
                prompt_log_fn(idx, prompt, c)
            except Exception as _exc:
                _zyg_log.debug('prompt log callback failed for clip %s: %s', idx, _exc)

        _shot_l = str(c.get('shot_type', '')).lower()
        if 'close-up' in _shot_l or 'extreme' in _shot_l:
            clip_shift = 2.0
            clip_steps = 30
        elif any(k in _shot_l for k in ('wide', 'overhead', 'aerial', 'drone', 'establishing')):
            clip_shift = 3.5
            clip_steps = _INFER_STEPS
        else:
            clip_shift = 2.5
            clip_steps = _INFER_STEPS
        if steps:  # test-mode / caller override → faster preview
            clip_steps = int(steps)
        _num_frames = int(frames) if frames else _CLIP_FRAMES
        if flow_shift is not None:  # caller override → steadier motion (multi-char/subtle FX)
            clip_shift = float(flow_shift)
        clip_guidance = 7.5 if c.get('emotion') in ('anger', 'triumph', 'tension') else _GUIDANCE
        base_seed = c.get('seed', idx * 1337)
        # Locked-camera shots: replace the template's anti-static negative (which forces
        # motion → set churn/push-in) with the curated static-shot negative.
        clip_negative = _STATIC_SHOT_NEG if c.get('static_shot') else None

        out_path = os.path.join(wan_dir, f'wan_{idx:03d}.mp4')
        sub_paths: list[str] = []
        current_src = src_path

        for sub_i in range(n_chained):
            if sub_i > 0 and sub_i % 2 == 0:
                current_src = src_path
                log_fn(f'WAN: clip {idx} sub {sub_i}: FLUX anchor reset (anti-drift)')
            sub_out = os.path.join(wan_dir, f'wan_{idx:03d}_sub{sub_i:02d}.mp4')
            if not _submit_wan_clip(
                workflow=workflow,
                src_path=current_src,
                prompt=prompt,
                idx=idx * 100 + sub_i,
                seed=base_seed + sub_i,
                shift=clip_shift,
                steps=clip_steps,
                guidance=clip_guidance,
                out_path=sub_out,
                log_fn=log_fn,
                frames=_num_frames,
                negative=clip_negative,
            ):
                log_fn(f'WAN: clip {idx} sub {sub_i} failed — aborting chain')
                sub_paths = []
                break
            sub_paths.append(sub_out)
            last_frame_path = sub_out + '.last.png'
            if _extract_last_frame(sub_out, last_frame_path, log_fn):
                # chain color-anchor: match the handoff frame's color statistics to the
                # ORIGINAL still so per-sub-clip color creep stops compounding
                if c.get('static_shot') and _color_match_to(src_path, last_frame_path, log_fn):
                    pass
                current_src = last_frame_path
            log_fn(f'WAN: clip {idx} sub-clip {sub_i + 1}/{n_chained} done (ComfyUI)')

        if not sub_paths:
            continue

        if _stitch_clips(sub_paths, out_path, log_fn):
            for _sp in sub_paths:
                try:
                    os.remove(_sp)
                    if os.path.isfile(_sp + '.last.png'):
                        os.remove(_sp + '.last.png')
                except OSError as _exc:
                    _zyg_log.debug('stitched sub-clip %s left behind: %s', _sp, _exc)
        else:
            shutil.copy2(sub_paths[0], out_path)

        _ip = os.path.join(wan_dir, f'wan_{idx:03d}_24fps.mp4')
        if _interpolate_clip(out_path, _ip, log_fn):
            os.replace(_ip, out_path)

        mscore = _compute_motion_score(out_path, log_fn)
        if mscore < (1.0 - _MOTION_FREEZE_THRESH):
            log_fn(f'WAN: clip {idx} motion={mscore:.2f} — Comfy regen shift=5.0')
            retry_path = out_path + '.retry.mp4'
            if _submit_wan_clip(
                workflow=workflow,
                src_path=src_path,
                prompt=prompt,
                idx=idx,
                seed=base_seed + 999,
                shift=5.0,
                steps=clip_steps,
                guidance=max(clip_guidance, 7.5),
                out_path=retry_path,
                log_fn=log_fn,
                negative=clip_negative,
            ):
                retry_score = _compute_motion_score(retry_path, log_fn)
                if retry_score > mscore:
                    os.replace(retry_path, out_path)

        results.append(
            {
                'path': out_path,
                'source_image': src_path,
                'index': idx,
                'slot_seconds': c.get('slot_seconds'),
                'subject': c.get('subject', ''),
                'prompt': prompt,
            }
        )
        log_fn(f'WAN: clip {idx} ✓ via ComfyUI chained ({n_chained} subs, shift={clip_shift})')

    return results


def _color_match_to(ref_path: str, target_path: str, log_fn) -> bool:
    """Match target's per-channel mean/std to the reference image IN PLACE. Used on
    chain handoff frames so sub-clip color creep (documented Wan chained-I2V drift)
    stops compounding across segments."""
    try:
        from PIL import Image
        import numpy as np

        ref = np.asarray(Image.open(ref_path).convert('RGB'), dtype=np.float32)
        tgt_img = Image.open(target_path).convert('RGB')
        tgt = np.asarray(tgt_img, dtype=np.float32)
        out = np.empty_like(tgt)
        for ch in range(3):
            t, r = tgt[:, :, ch], ref[:, :, ch]
            ts, rs = max(t.std(), 1e-4), r.std()
            out[:, :, ch] = (t - t.mean()) * (rs / ts) + r.mean()
        Image.fromarray(np.clip(out, 0, 255).astype('uint8')).save(target_path)
        return True
    except Exception as exc:
        if log_fn:
            log_fn(f'WAN: color-match skipped ({exc})')
        return False


def _extract_last_frame(video_path: str, out_png: str, log_fn) -> bool:
    """Grab last frame of an mp4 for chained I2V (ffmpeg)."""
    try:
        subprocess.run(
            [
                exe('ffmpeg'),
                '-y',
                '-sseof',
                '-0.1',
                '-i',
                video_path,
                '-frames:v',
                '1',
                '-q:v',
                '2',
                out_png,
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        return os.path.isfile(out_png) and os.path.getsize(out_png) > 1000
    except Exception as exc:
        if log_fn:
            log_fn(f'WAN: last-frame extract failed: {exc}')
        return False


def _submit_wan_clip(
    workflow: dict,
    src_path: str,
    prompt: str,
    idx: int,
    seed: int,
    shift: float,
    steps: int,
    guidance: float,
    out_path: str,
    log_fn,
    frames: int = _CLIP_FRAMES,
    negative: str | None = None,
) -> bool:
    """One ComfyUI wan_i2v submission. Returns True on success, copies result
    to out_path. Used by both initial generation and motion-regen retry.
    ``frames`` overrides the per-sub-clip length (default ``_CLIP_FRAMES``).
    ``negative`` overrides the template's negative prompt (None keeps the template
    default — which contains the anti-static motion-forcing tokens, correct for
    normal moving shots but wrong for locked static shots)."""
    try:
        src_name = _comfy.stage_input_image(src_path)
        _p20 = {'positive_prompt': prompt[:600]}
        if negative:
            _p20['negative_prompt'] = negative[:600]
        wf = workflow
        # Optional Wan LoRA (e.g. MIT Anti-Realistic-Transformation for painterly
        # inputs). Env-gated and default-off → graph byte-identical when unset.
        _lora = os.environ.get('ZYG_WAN_LORA', '').strip()
        _is_wan22 = '31' in workflow  # dual-expert graph marker
        if _lora or (_is_wan22 and _WAN_LIGHTNING):
            import copy as _cp

            wf = _cp.deepcopy(workflow)
        if _lora:
            wf['6'] = {
                'class_type': 'WanVideoLoraSelect',
                'inputs': {
                    'lora': _lora,
                    'strength': float(os.environ.get('ZYG_WAN_LORA_STRENGTH', '1.0')),
                    'low_mem_load': False,
                },
            }
            # 2.1 char/style LoRAs only fit the LOW-noise expert on 2.2
            _target = '7' if _is_wan22 else '1'
            wf[_target]['inputs']['lora'] = ['6', 0]
        if _is_wan22 and _WAN_LIGHTNING:
            wf['8'] = {
                'class_type': 'WanVideoLoraSelect',
                'inputs': {
                    'lora': _LIGHTNING_HIGH_LORA,
                    'strength': 1.0,
                    'low_mem_load': False,
                },
            }
            wf['1']['inputs']['lora'] = ['8', 0]
            _low_inputs = {'lora': _LIGHTNING_LOW_LORA, 'strength': 1.0, 'low_mem_load': False}
            if _lora:
                _low_inputs['prev_lora'] = ['6', 0]  # chain char LoRA under Lightning
            wf['9'] = {'class_type': 'WanVideoLoraSelect', 'inputs': _low_inputs}
            wf['7']['inputs']['lora'] = ['9', 0]
        if _is_wan22:
            if _WAN_LIGHTNING:
                # Lightning distill: 4 steps, no CFG, shift 5.0 — overrides the
                # caller's per-shot steps/cfg/shift tuning (logged for the logbook)
                steps, guidance, shift = 4, 1.0, 5.0
            _boundary = max(1, int(round(steps * _WAN22_BOUNDARY_FRACTION)))
            overrides = {
                '1': {'attention_mode': _WAN_ATTENTION},
                '7': {'attention_mode': _WAN_ATTENTION},
                '10': {'image': src_name},
                '11': {'width': _WIDTH, 'height': _HEIGHT, 'num_frames': int(frames)},
                '20': _p20,
                '30': {
                    'seed': seed,
                    'steps': steps,
                    'cfg': guidance,
                    'shift': shift,
                    'start_step': 0,
                    'end_step': _boundary,
                },
                '31': {
                    'seed': seed,
                    'steps': steps,
                    'cfg': guidance,
                    'shift': shift,
                    'start_step': _boundary,
                    'end_step': -1,
                },
                '45': {'fps': float(_CLIP_FPS)},
                '50': {'filename_prefix': f'ZygWan22I2V_{idx:03d}'},
            }
        else:
            overrides = {
                '1': {
                    'model': _WAN_COMFY_MODEL,  # 480P default; ZYG_WAN_MODEL switches to 720P
                    'attention_mode': _WAN_ATTENTION,
                },
                '10': {'image': src_name},
                '11': {'width': _WIDTH, 'height': _HEIGHT, 'num_frames': int(frames)},
                '20': _p20,
                '30': {'seed': seed, 'steps': steps, 'cfg': guidance, 'shift': shift},
                '45': {'fps': float(_CLIP_FPS)},
                '50': {'filename_prefix': f'ZygWanI2V_{idx:03d}'},
            }
        # debug trace: the EXACT prompts + graph going to comfy (incl. template negative
        # when no override — the anti-static-negative bug would have been visible here)
        try:
            from zyg_workflows import pipeline_debug as _dbg

            _d = _dbg.get_active()
            _eff_neg = _p20.get('negative_prompt') or wf.get('20', {}).get('inputs', {}).get(
                'negative_prompt', '(template default)'
            )
            _d.record_prompts(
                f'wan_clip_{idx}',
                positive=prompt,
                negative=_eff_neg,
                model=_WAN_COMFY_MODEL,
                seed=seed,
                steps=steps,
                cfg=guidance,
                shift=shift,
                frames=frames,
                lora=os.environ.get('ZYG_WAN_LORA', ''),
            )
            _merged = {
                nid: {
                    'class_type': n.get('class_type'),
                    'inputs': {**{k: v for k, v in (n.get('inputs') or {}).items()}, **(overrides.get(nid) or {})},
                }
                for nid, n in wf.items()
            }
            _d.record_graph(f'wan_{idx}', _merged)
        except Exception as _exc:
            _zyg_log.debug('debug recorder skipped the wan graph for clip %s: %s', idx, _exc)
        # 2026-07-30 attestation: sha256 every model file this graph points at and
        # diff vs data/runtime/model_pins.json BEFORE any frame is rendered. Catches
        # a swapped/renamed LoRA, a clobbered base checkpoint, and a LoRA left at
        # strength 0. Warn-only; ZYG_LORA_ATTEST=strict raises before submit.
        try:
            from zyg_workflows import lora_attest as _attest
        except Exception:
            _attest = None
        if _attest is not None:
            _attest.attest_submit(wf, overrides=overrides, tag=f'wan_clip_{idx}', log_fn=log_fn)
        outputs = _comfy.submit(wf, overrides=overrides, timeout_s=int(os.environ.get('ZYG_WAN_TIMEOUT_S', '900')))
        if not outputs:
            log_fn(f'WAN: clip {idx} ComfyUI returned no output')
            return False
        shutil.copy2(outputs[0], out_path)
        return True
    except Exception as exc:
        log_fn(f'WAN: clip {idx} ComfyUI submit failed: {exc}')
        return False


def _build_prompt(meta: dict, visual_style: str | None = None) -> str:
    """Build the motion/style prompt for Wan2.1-I2V.

    If the caller provides a Claude-written ``wan_prompt`` in meta, it is used
    verbatim — Claude already wrote it with the correct motion vocabulary and
    cinematic language.  Otherwise falls back to the heuristic builder.
    When ``visual_style='cinematic'`` a shot-type → camera mapping overrides the
    emotion-derived camera direction and a cinematic suffix is appended.
    """
    # Prefer Claude-written animation prompt (added in Stage 1 dual-prompt flow)
    wan_prompt = meta.get('wan_prompt', '').strip()
    if wan_prompt:
        # static_shot (locked camera / painterly scene): NO cinematic suffix — its
        # 'teal-orange grade' token progressively re-colors props (the teal-candle bug)
        # and 'smooth motion/anamorphic' add motion pressure. Lead with Wan's TRAINED
        # camera grammar instead, which it honors far better than free-form phrasing.
        if meta.get('static_shot'):
            _pfx = '固定镜头, static shot, fixed camera, locked-off tripod shot. '
            if 'static shot' not in wan_prompt.lower():
                wan_prompt = _pfx + wan_prompt
            return wan_prompt
        # 6C: For action/battle scenes, prepend motion vocabulary so WAN reads it first
        _meta_emotion = meta.get('emotion', 'neutral')
        _meta_scene_type = str(meta.get('scene_type', '')).lower()
        if _meta_emotion in ('anger', 'triumph', 'tension') or _meta_scene_type == 'pure_action':
            _action_pfx = _MOTION_BY_EMOTION.get(_meta_emotion, 'dynamic motion, kinetic energy')
            wan_prompt = f'{_action_pfx}. {wan_prompt}'
        # Still append cinematic suffix when visual_style is set so Claude prompts
        # also benefit from the explicit anamorphic/film-grain vocabulary.
        if visual_style == 'cinematic' and _CINEMATIC_WAN_SUFFIX not in wan_prompt:
            return wan_prompt.rstrip('. ') + f'. {_CINEMATIC_WAN_SUFFIX}.'
        return wan_prompt

    # ── Heuristic fallback (used when wan_prompt is absent / legacy runs) ────
    subject = meta.get('subject', '')
    shot = meta.get('shot_type', 'medium shot')
    emotion = meta.get('emotion', 'neutral')
    base = meta.get('prompt', subject)

    # Cinematic visual_style: shot-type takes precedence over emotion camera
    if visual_style == 'cinematic':
        # Match on any word in the shot field against our map keys
        shot_lower = shot.lower()
        cinematic_motion = next(
            (v for k, v in _CAMERA_BY_SHOT.items() if k in shot_lower),
            None,
        )
        if not cinematic_motion:
            # Fallback: use emotion cue but still add cinematic suffix
            cinematic_motion = meta.get('camera_motion') or _MOTION_BY_EMOTION.get(
                emotion, 'steady gentle camera movement, documentary style'
            )
    else:
        cinematic_motion = None

    # Claude-provided camera motion takes priority over emotion-derived fallback
    motion = (
        cinematic_motion
        or meta.get('camera_motion')
        or _MOTION_BY_EMOTION.get(emotion, 'steady gentle camera movement, documentary style')
    )

    # Build additional scene-specific motion hints by scanning the base prompt text
    scene_hints: list[str] = []
    base_lower = base.lower()
    for keywords, hint in _SCENE_MOTION_HINTS:
        if any(kw in base_lower for kw in keywords):
            scene_hints.append(hint)
            break  # one hint group is enough to avoid over-stuffing the prompt

    scene_motion = (', '.join(scene_hints) + '. ') if scene_hints else ''

    if visual_style == 'cinematic':
        return f'{motion}. {scene_motion}Cinematic documentary footage. {base}. {shot}. {_CINEMATIC_WAN_SUFFIX}.'
    return (
        f'{motion}. {scene_motion}'
        f'Cinematic documentary footage. {base}. '
        f'{shot}. '
        'Photorealistic, high detail, smooth motion, film grain, 4K quality. '
        'Continuous camera movement. Professional cinematography.'
    )


def _stitch_clips(sub_paths: list, out_path: str, log_fn=None) -> bool:
    """Concatenate multiple WAN sub-clips into a single MP4 using ffmpeg concat demuxer.

    All sub-clips must have the same codec/resolution (guaranteed since they're all
    produced by _save_video with identical params).  Stream-copy keeps quality lossless
    and is near-instant.  Returns True on success, False on any failure.
    """

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    if not sub_paths:
        return False
    if len(sub_paths) == 1:
        try:
            import shutil

            shutil.copy2(sub_paths[0], out_path)
            return True
        except Exception:
            return False

    concat_list = out_path + '.concat_list.txt'
    try:
        with open(concat_list, 'w') as fh:
            for p in sub_paths:
                fh.write(f"file '{p}'\n")
        r = subprocess.run(
            [
                exe('ffmpeg'),
                '-y',
                '-f',
                'concat',
                '-safe',
                '0',
                '-i',
                concat_list,
                '-c',
                'copy',
                out_path,
            ],
            capture_output=True,
            timeout=120,
        )
        ok = r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 1000
        if ok:
            _log(f'WAN: stitched {len(sub_paths)} sub-clips → {os.path.basename(out_path)}')
        else:
            _log(f'WAN: stitch failed (rc={r.returncode}): {r.stderr.decode()[:300]}')
        return ok
    except Exception as e:
        _log(f'WAN: stitch error — {e}')
        return False
    finally:
        try:
            os.remove(concat_list)
        except OSError as _exc:
            _zyg_log.debug('concat list %s left behind: %s', concat_list, _exc)


# ── New helper functions (Problems 6A, T2V pass) ─────────────────────────────


def _compute_motion_score(clip_path: str, log_fn=None) -> float:
    """Estimate motion fraction of a video clip using ffmpeg freezedetect.

    Returns a float in [0, 1] where 1.0 = fully moving, 0.0 = fully frozen.
    A score below (1 - _MOTION_FREEZE_THRESH) means the clip is near-static.
    """

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    try:
        # Get total duration
        dur_r = subprocess.run(
            [
                exe('ffprobe'),
                '-v',
                'error',
                '-show_entries',
                'format=duration',
                '-of',
                'default=noprint_wrappers=1:nokey=1',
                clip_path,
            ],
            capture_output=True,
            timeout=30,
        )
        total_dur = float(dur_r.stdout.decode().strip() or '0')
        if total_dur <= 0:
            return 1.0

        # Run freezedetect — outputs FREEZE_START / FREEZE_END / FREEZE_DURATION lines
        fz_r = subprocess.run(
            [
                exe('ffmpeg'),
                '-i',
                clip_path,
                '-vf',
                'freezedetect=n=-60dB:d=0.5',
                '-an',
                '-f',
                'null',
                '-',
            ],
            capture_output=True,
            timeout=120,
        )
        output = fz_r.stderr.decode()
        frozen_dur = 0.0
        for line in output.splitlines():
            if 'freeze_duration' in line:
                try:
                    frozen_dur += float(line.split('freeze_duration:')[-1].strip().split()[0])
                except (ValueError, IndexError) as _exc:
                    _zyg_log.debug('freezedetect line unparsed, not counted as frozen time: %s', _exc)

        motion_score = max(0.0, min(1.0, 1.0 - frozen_dur / total_dur))
        _log(f'WAN: motion score {motion_score:.2f} (frozen {frozen_dur:.1f}s / {total_dur:.1f}s)')
        return motion_score

    except Exception as e:
        _log(f'WAN: _compute_motion_score error: {e}')
        return 1.0  # assume good if detection fails — don't waste a retry


def _save_video(frames, out_path: str) -> None:
    """Write a list of PIL images as an H.264 MP4 using diffusers' export helper.

    The `def` line went missing in an earlier edit, which left this body glued to the
    end of _unload_t2v_pipe() and made the two _save_video() call sites a NameError.
    """
    from diffusers.utils import export_to_video

    export_to_video(frames, out_path, fps=_CLIP_FPS)


def _interpolate_clip(src: str, dst: str, log_fn=None) -> bool:
    """Interpolate a WAN clip from _CLIP_FPS (17) to _OUTPUT_FPS (24) using ffmpeg minterpolate.

    Uses blend mode (averaged intermediate frames) which is robust for fast-action
    and avoids ghosting artifacts that MCI motion estimation can introduce.
    Returns True on success, False if ffmpeg fails (caller keeps the original).
    """

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    try:
        r = subprocess.run(
            [
                exe('ffmpeg'),
                '-y',
                '-i',
                src,
                '-vf',
                f'minterpolate=fps={_OUTPUT_FPS}:mi_mode=blend',
                '-c:v',
                'libx264',
                '-preset',
                'veryfast',
                '-crf',
                '20',
                '-pix_fmt',
                'yuv420p',
                dst,
            ],
            capture_output=True,
            timeout=180,
        )
        if r.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 1000:
            _log(f'WAN: interpolated {os.path.basename(src)} → {_OUTPUT_FPS}fps')
            return True
        _log(f'WAN: interpolation failed (rc={r.returncode}) — keeping {_CLIP_FPS}fps original')
        return False
    except Exception as e:
        _log(f'WAN: interpolation error — {e}')
        return False
