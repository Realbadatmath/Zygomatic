# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""wan_video_service — the per-clip I2V and T2V render passes that generate() orchestrates.

The import graph stays one-way: ``api`` → ``api_passes`` → ``helpers`` → ``constants``.
This module never imports ``api``, so the pipeline objects and the module-level locks
stay where they were and are passed in.

Two deliberate choices keep the package's monkeypatch contract intact.  This module is
not one of the package ``_SECTIONS`` that ``wan_video_service.__init__`` forwards a
``setattr`` to, so (a) every value the smoke scripts patch on the package
(``_INFER_STEPS``, ``_N_CHAINED``, ``_CLIP_FRAMES``, ``_WIDTH``, ``_HEIGHT``) is passed
in from ``api`` on the :class:`WanPass` instead of read here as a global, and (b) the
``helpers`` functions are called through the ``_h`` module reference, so a patch on
``wan_video_service._build_prompt`` still reaches them.
"""

from collections.abc import Callable
from dataclasses import dataclass

from zyg_workflows.wan_video_service import helpers as _h
from zyg_workflows.wan_video_service.constants import (
    _HUMAN_SUBJECT_KW,
    _zyg_log,
    json,
    os,
    time,
)

# ── Negative-prompt fragments ────────────────────────────────────────────────
# The I2V pass uses base + style + tail; the T2V pass omits the 2D-art style block
# because text-to-video is already free of the still's rendering.
_NEG_BASE = (
    'text, watermark, logo, blurry, distorted anatomy, '
    'extra limbs, low quality, static, still image, '
    'compression artifacts, pixelated, overexposed, '
    'cartoon, anime, animated, illustration, drawing, '
)
_NEG_STYLE = 'cel shading, stylized, 2D art, flat colors, '
_NEG_TAIL = 'static, motionless, frozen, lifeless, no movement'
_NEG_ANATOMY = (
    ', morphing face, melting skin, extra fingers, changing facial features, '
    'inconsistent anatomy, face swap, disfigured face'
)

# Shot types that read as atmospheric rather than tight, and the emotions that want a
# stronger adherence to the motion prompt.
_WIDE_SHOT_KW = ('wide', 'overhead', 'aerial', 'drone', 'establishing')
_HIGH_GUIDANCE_EMOTIONS = ('anger', 'triumph', 'tension')

# The high-motion retry: flow shift, guidance floor, seed offset, and the byte size below
# which the retry's stitched file counts as a failure rather than a replacement.
_RETRY_FLOW_SHIFT = 5.0
_RETRY_GUIDANCE_FLOOR = 7.5
_RETRY_SEED_OFFSET = 999
_MIN_USABLE_BYTES = 1000


@dataclass
class ClipKnobs:
    """The sampler knobs one I2V clip is rendered with.

    ``shot_label`` is the lowercased shot type with ``'medium'`` standing in for a
    candidate that declares none — it is what the flow-shift log line prints.
    """

    flow_shift: float
    steps: int
    guidance: float
    shot_label: str


@dataclass
class WanPass:
    """Everything one generate() pass needs besides its candidates and its pipeline.

    The render sizes and sampler defaults are fields rather than globals because the
    smoke scripts patch them on the ``wan_video_service`` package and that patch does
    not reach this module (see the module docstring).  ``torch`` is filled in by the
    orchestrator after the pipeline has loaded, since importing it is what proves CUDA
    is available at all.
    """

    wan_dir: str
    log: Callable[[str], None]
    chain: int
    frames: int
    width: int
    height: int
    steps_default: int
    guidance_default: float
    motion_thresh: float
    torch: object = None
    sched_cls: object = None
    visual_style: str | None = None
    prompt_log_fn: Callable | None = None


# ── Pure candidate/prompt derivation ─────────────────────────────────────────


def pick_candidates(flux_image_meta: list, n_clips: int, priority: dict) -> list:
    """Return the *n_clips* emotionally strongest entries of *flux_image_meta*.

    ``sorted`` is stable, so the caller's qa_score-descending order decides ties in
    emotion *priority*: the best-looking image of an emotion wins.  An emotion missing
    from *priority* ranks at 1.
    """
    return sorted(
        flux_image_meta,
        key=lambda m: priority.get(m.get('emotion', 'neutral'), 1),
        reverse=True,
    )[:n_clips]


def split_scene_types(candidates: list) -> tuple[list, list]:
    """Split *candidates* into the ``(i2v, t2v)`` passes by their ``scene_type``.

    ``pure_action`` scenes go to T2V for maximum motion freedom; every other scene is
    animated from its FLUX still by I2V.  Both lists keep the input order.
    """
    i2v = [c for c in candidates if str(c.get('scene_type', '')).lower() != 'pure_action']
    t2v = [c for c in candidates if str(c.get('scene_type', '')).lower() == 'pure_action']
    return i2v, t2v


def clip_knobs(cand: dict, *, steps_default: int, guidance_default: float) -> ClipKnobs:
    """Derive one clip's flow shift, inference steps and guidance scale.

    Tight shots (close-up/extreme) get a low flow shift — less motion, so anatomy stays
    stable — plus 30 inference steps because the anatomy is more visible; wide and
    aerial shots get a higher shift for atmospheric movement; everything else sits in
    between.  Action emotions raise the guidance scale to 7.5 so the motion prompt is
    followed more literally.
    """
    shot = str(cand.get('shot_type', '')).lower()
    tight = 'close-up' in shot or 'extreme' in shot
    if tight:
        flow_shift = 2.0
    elif any(k in shot for k in _WIDE_SHOT_KW):
        flow_shift = 3.5
    else:
        flow_shift = 2.5
    emotion = cand.get('emotion', 'neutral')
    return ClipKnobs(
        flow_shift=flow_shift,
        steps=30 if tight else steps_default,
        guidance=_RETRY_GUIDANCE_FLOOR if emotion in _HIGH_GUIDANCE_EMOTIONS else guidance_default,
        shot_label=shot or 'medium',
    )


def negative_prompt(cand: dict, human_kw, *, style_block: bool) -> str:
    """Build one clip's negative prompt.

    The anatomy clause is appended only when the candidate's subject and prompt text
    mention one of *human_kw* — a scene with an identifiable human is where morphing
    faces and extra fingers show.  *style_block* adds the 2D-art terms that the I2V
    pass carries and the T2V pass does not.
    """
    text = (cand.get('subject', '') + ' ' + cand.get('prompt', '')).lower()
    anat = _NEG_ANATOMY if any(kw in text for kw in human_kw) else ''
    return _NEG_BASE + (_NEG_STYLE if style_block else '') + _NEG_TAIL + anat


def _clip_record(cand: dict, idx: int, out_path: str, prompt: str, last_frame) -> dict:
    """One result record for a finished clip, in the shape Stage 6 reads."""
    return {
        'path': out_path,
        'source_image': cand.get('path', ''),
        'index': idx,
        'slot_seconds': cand.get('slot_seconds', 0.0),
        'subject': cand.get('subject', ''),
        'prompt': prompt,
        'last_frame': last_frame,
    }


def write_manifest(wan_dir: str, results: list, log: Callable[[str], None]) -> None:
    """Write ``wan_manifest.json`` for *results* into *wan_dir*.

    The in-memory ``last_frame`` image of each record is dropped: it is passed on to the
    next clip's chain, not serialised.
    """
    manifest_path = os.path.join(wan_dir, 'wan_manifest.json')
    serializable = [{k: v for k, v in r.items() if k != 'last_frame'} for r in results]
    with open(manifest_path, 'w') as fh:
        json.dump(serializable, fh, indent=2)
    log(f'WAN: {len(results)} clip(s) saved → {wan_dir}')


# ── Pipeline-touching stages ─────────────────────────────────────────────────


def _apply_flow_shift(pipe, sched_cls, shift: float) -> tuple[bool, object]:
    """Rebuild *pipe*'s scheduler with ``shift=shift``; return ``(applied, error)``.

    The caller decides how loudly to complain, because the I2V and T2V passes report a
    failed swap differently.
    """
    try:
        pipe.scheduler = sched_cls.from_config(pipe.scheduler.config, shift=shift)
    except Exception as exc:
        return False, exc
    return True, None


def _load_still(cand: dict, idx: int, log: Callable[[str], None]):
    """Open the candidate's FLUX still as RGB, or return None after logging why.

    A clip with no usable still cannot be animated, so the caller skips it.
    """
    from PIL import Image as _PIL

    path = cand.get('path', '')
    image = None
    if path and os.path.exists(path):
        try:
            image = _PIL.open(path).convert('RGB')
            log(f'WAN: loaded FLUX image {os.path.basename(path)} for clip {idx}')
        except Exception as exc:
            log(f'WAN: could not load image {path} — {exc}')
    if image is None:
        log(f'WAN: no FLUX image for clip {idx} — skipping')
    return image


def _run_i2v_chain(
    pipe,
    cand: dict,
    idx: int,
    image,
    prompt: str,
    neg: str,
    st: WanPass,
    *,
    knobs: ClipKnobs,
    guidance: float,
    seed_off: int = 0,
) -> tuple[list, object]:
    """Render ``st.chain`` I2V sub-clips and return ``(sub_clip_paths, last_frame)``.

    Each sub-clip continues from the previous one's last frame, except that every second
    sub-clip restarts from the original FLUX still — the anchor reset is what keeps a
    long chain from drifting away from the scene.  *seed_off* shifts every sub-clip's
    seed so a retry renders something different.
    """
    subs: list = []
    cur = image
    for s in range(st.chain):
        if s > 0 and s % 2 == 0:
            cur = image
            st.log(f'WAN: clip {idx} sub {s}: FLUX anchor reset (anti-drift)')
        sub_path = os.path.join(st.wan_dir, f'wan_{idx:03d}_sub{s:02d}_r{seed_off}.mp4')
        output = pipe(
            image=cur,
            prompt=prompt,
            negative_prompt=neg,
            height=st.height,
            width=st.width,
            num_frames=st.frames,
            num_inference_steps=knobs.steps,
            guidance_scale=guidance,
            output_type='pil',
            generator=st.torch.Generator('cuda').manual_seed(cand.get('seed', idx * 1337) + s + seed_off),
        )
        frames = output.frames[0]
        _h._save_video(frames, sub_path)
        subs.append(sub_path)
        cur = frames[-1]
        st.log(f'WAN: clip {idx} sub-clip {s + 1}/{st.chain} done')
    return subs, cur


def _stitch_and_interpolate(sub_paths: list, out_path: str, idx: int, st: WanPass) -> None:
    """Concatenate the sub-clips into *out_path* and interpolate it to 24 fps in place.

    A failed stitch falls back to the first sub-clip alone.  Either way the sub-clips are
    removed; one that will not delete is only noted, never raised.
    """
    if _h._stitch_clips(sub_paths, out_path, st.log):
        for sub_path in sub_paths:
            try:
                os.remove(sub_path)
            except OSError as exc:
                _zyg_log.debug('stitched sub-clip %s left behind: %s', sub_path, exc)
    else:
        st.log(f'WAN: clip {idx} stitch failed — using first sub-clip only')
        os.replace(sub_paths[0], out_path)
        for sub_path in sub_paths[1:]:
            try:
                os.remove(sub_path)
            except OSError as exc:
                _zyg_log.debug('unused sub-clip %s left behind: %s', sub_path, exc)
    interp_path = os.path.join(st.wan_dir, f'wan_{idx:03d}_24fps.mp4')
    if _h._interpolate_clip(out_path, interp_path, st.log):
        os.replace(interp_path, out_path)


def _motion_retry(
    pipe, cand: dict, idx: int, out_path: str, image, prompt: str, neg: str, st: WanPass, knobs: ClipKnobs, last_frame
):
    """Re-render *out_path* with high-motion parameters when it came out near-static.

    Returns the last frame to record: the retry's whenever the retry ran, otherwise the
    *last_frame* passed in.  The retry only replaces *out_path* when it produced a file
    big enough to be a real clip.
    """
    score = _h._compute_motion_score(out_path, st.log)
    floor = 1.0 - st.motion_thresh
    if score >= floor:
        return last_frame

    guidance = max(knobs.guidance, _RETRY_GUIDANCE_FLOOR)
    st.log(
        f'WAN: clip {idx} motion={score:.2f} (< {floor:.2f}) '
        f'— near-static; retrying with flow_shift={_RETRY_FLOW_SHIFT}, '
        f'guidance={guidance}'
    )
    if st.sched_cls is not None:
        applied, err = _apply_flow_shift(pipe, st.sched_cls, _RETRY_FLOW_SHIFT)
        if not applied:
            _zyg_log.warning('flow_shift=5.0 not applied, retrying with the previous scheduler: %s', err)

    retry_subs, last_frame = _run_i2v_chain(
        pipe, cand, idx, image, prompt, neg, st, knobs=knobs, guidance=guidance, seed_off=_RETRY_SEED_OFFSET
    )
    retry_out = out_path + '_retry.mp4'
    _stitch_and_interpolate(retry_subs, retry_out, idx, st)
    if os.path.exists(retry_out) and os.path.getsize(retry_out) > _MIN_USABLE_BYTES:
        os.replace(retry_out, out_path)
        st.log(f'WAN: clip {idx} regenerated with high-motion parameters')
    return last_frame


def generate_i2v_clips(cands: list, pipe, st: WanPass, out: list) -> None:
    """Run the I2V pass over *cands*, appending one record per finished clip to *out*.

    *out* is mutated rather than returned so that clips already rendered survive an
    exception raised between clips, which is what the caller's outer handler relies on.
    A clip that fails inside its own render is logged and skipped; the pass continues.
    """
    for cand in cands:
        idx = cand.get('index', 0)
        out_path = os.path.join(st.wan_dir, f'wan_{idx:03d}.mp4')
        knobs = clip_knobs(cand, steps_default=st.steps_default, guidance_default=st.guidance_default)

        if st.sched_cls is not None:
            applied, err = _apply_flow_shift(pipe, st.sched_cls, knobs.flow_shift)
            if applied:
                st.log(f'WAN: clip {idx} flow_shift={knobs.flow_shift} ({knobs.shot_label})')
            else:
                st.log(f'WAN: clip {idx} flow_shift update failed: {err}')

        neg = negative_prompt(cand, _HUMAN_SUBJECT_KW, style_block=True)
        prompt = _h._build_prompt(cand, visual_style=st.visual_style)
        if st.prompt_log_fn:
            try:
                st.prompt_log_fn(idx, prompt, cand)
            except Exception as exc:
                _zyg_log.debug('prompt log callback failed for clip %s: %s', idx, exc)

        image = _load_still(cand, idx, st.log)
        if image is None:
            continue

        st.log(
            f'WAN: animating clip {idx} '
            f'(fs={knobs.flow_shift}, steps={knobs.steps}, guidance={knobs.guidance}) '
            f'"{cand.get("subject", "?")}…"'
        )
        t0 = time.time()
        try:
            sub_paths, last_frame = _run_i2v_chain(
                pipe, cand, idx, image, prompt, neg, st, knobs=knobs, guidance=knobs.guidance
            )
            _stitch_and_interpolate(sub_paths, out_path, idx, st)
            last_frame = _motion_retry(pipe, cand, idx, out_path, image, prompt, neg, st, knobs, last_frame)

            elapsed = time.time() - t0
            st.log(f'WAN: clip {idx} done in {elapsed:.0f}s — {out_path}')
            out.append(_clip_record(cand, idx, out_path, prompt, last_frame))
        except Exception as clip_err:
            st.log(f'WAN: clip {idx} failed — {clip_err}')


def _prepend_flux_anchor(frames: list, cand: dict, st: WanPass) -> list:
    """Prepend the candidate's FLUX still four times to *frames* for visual continuity.

    Returns *frames* unchanged when the still is missing or will not open — the clip is
    still usable, it just no longer opens on the image its scene was planned around.
    """
    path = cand.get('path', '')
    if not (path and os.path.exists(path)):
        return frames
    try:
        from PIL import Image as _PIL_t2v

        anchor = _PIL_t2v.open(path).convert('RGB').resize((st.width, st.height))
    except Exception as exc:
        _zyg_log.warning('flux anchor frames not prepended, this clip may not match its still: %s', exc)
        return frames
    return [anchor] * 4 + frames


def _write_t2v_clip(frames: list, out_path: str, idx: int, st: WanPass) -> None:
    """Save *frames* and land them at *out_path*, interpolated to 24 fps when possible.

    The raw render is kept only as the fallback for a failed interpolation.
    """
    raw_path = out_path + '_t2v_raw.mp4'
    _h._save_video(frames, raw_path)
    interp_path = os.path.join(st.wan_dir, f'wan_{idx:03d}_24fps.mp4')
    if _h._interpolate_clip(raw_path, interp_path, st.log):
        os.replace(interp_path, out_path)
        try:
            os.remove(raw_path)
        except OSError as exc:
            _zyg_log.debug('pre-interpolation render %s left behind: %s', raw_path, exc)
    else:
        os.replace(raw_path, out_path)


def generate_t2v_clips(cands: list, pipe, st: WanPass, out: list) -> None:
    """Run the T2V pass over the pure_action *cands*, appending records to *out*.

    Each clip is rendered from its prompt alone — one long render rather than a chain —
    at a high flow shift for maximum motion, then the FLUX still is prepended as anchor
    frames so the clip still belongs to its scene.  *out* is mutated for the same reason
    as in :func:`generate_i2v_clips`.
    """
    for cand in cands:
        idx = cand.get('index', 0)
        out_path = os.path.join(st.wan_dir, f'wan_{idx:03d}.mp4')
        neg = negative_prompt(cand, _HUMAN_SUBJECT_KW, style_block=False)
        prompt = _h._build_prompt(cand, visual_style=st.visual_style)

        if st.sched_cls is not None:
            applied, err = _apply_flow_shift(pipe, st.sched_cls, _RETRY_FLOW_SHIFT)
            if not applied:
                _zyg_log.warning('T2V flow_shift=5.0 not applied, rendering with the default scheduler: %s', err)

        st.log(f'WAN: T2V pure_action clip {idx} "{cand.get("subject", "?")}…"')
        t0 = time.time()
        try:
            output = pipe(
                prompt=prompt,
                negative_prompt=neg,
                height=st.height,
                width=st.width,
                num_frames=st.frames * st.chain,
                num_inference_steps=30,
                guidance_scale=8.0,
                output_type='pil',
                generator=st.torch.Generator('cuda').manual_seed(cand.get('seed', idx * 1337)),
            )
            frames = _prepend_flux_anchor(output.frames[0], cand, st)
            _write_t2v_clip(frames, out_path, idx, st)

            score = _h._compute_motion_score(out_path, st.log)
            elapsed = time.time() - t0
            st.log(f'WAN: T2V clip {idx} done in {elapsed:.0f}s motion={score:.2f} — {out_path}')
            out.append(_clip_record(cand, idx, out_path, prompt, frames[-1] if frames else None))
        except Exception as clip_err:
            st.log(f'WAN: T2V clip {idx} failed — {clip_err}')
