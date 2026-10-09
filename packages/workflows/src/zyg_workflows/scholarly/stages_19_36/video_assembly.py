# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 4 — Ken-Burns rendering and video assembly (`stage_15_video_assembly`).

The stage is the orchestrator only; the work lives next door in
`video_assembly_slides` (which pictures, how long each is held, the filter
graph, the encode) and `video_assembly_kenburns` (the per-slot camera move and
its PIL render). The three `ZYG_*` reads stay here so the generated settings
registry keeps naming this file as their source.
"""

from ._common import (
    _update_marker,
    os,
)

from .video_assembly_kenburns import KenBurnsEnv, render_ken_burns_slots
from .video_assembly_slides import (
    build_slideshow_filter,
    download_generic_backgrounds,
    encode_slideshow,
    essay_image_paths,
    load_motion_clip_map,
    plan_slideshow,
    rescue_flux_images,
)


def _kb_env():
    """The stage's three `ZYG_*` flags as one `KenBurnsEnv`.

    `ZYG_KB_MAX_WORKERS` caps the render thread pool (default 8, was 16: each
    worker holds multiple 5120×2880 frame buffers); the two `ZYG_DOC_FILMLOOK_*`
    flags only decide what the film-look report claims is in the chain.
    """
    return KenBurnsEnv(
        worker_cap=int(os.environ.get('ZYG_KB_MAX_WORKERS', '8')),
        dust_on=os.environ.get('ZYG_DOC_FILMLOOK_DUST', '1').strip().lower()
        not in (
            '0',
            'false',
            'no',
        ),
        grain_on=os.environ.get('ZYG_DOC_FILMLOOK_GRAIN', '0').strip().lower()
        not in (
            '0',
            'false',
            'no',
            '',
        ),
    )


def stage_15_video_assembly(ctx):
    _debug = ctx._debug
    _log = ctx._log
    _pipeline_marker = ctx._pipeline_marker
    _sch_family_label = ctx._sch_family_label
    _slug = ctx._slug
    job = ctx.job
    out_dir = ctx.out_dir
    pipeline_id = ctx.pipeline_id
    pipeline_state = ctx.pipeline_state
    visual_tags = ctx.visual_tags
    # ── Stage 6: Video Assembly ────────────────────────────────────────
    job['current_stage'] = 'Stage 6: Video Assembly'
    _update_marker(_pipeline_marker, label=f'🔄 Scholarly {pipeline_id[:8]} — Video Assembly')
    _log('INFO', 'Stage 6', 'Assembling scholarly video')

    # Stock clip downloading DISABLED — no API keys configured; essay image slideshow used instead
    downloaded_clips = []

    # Build image slideshow from essay images (each shown once, no repeats)
    _essay_imgs = pipeline_state.get('essay_images', [])
    _tts_dur = pipeline_state.get('tts_duration', 300)
    _img_paths = essay_image_paths(_essay_imgs, _log)
    if not _img_paths:
        _img_paths = rescue_flux_images(out_dir, _sch_family_label, _log)
    if not _img_paths:
        downloaded_clips = download_generic_backgrounds(pipeline_state, out_dir, _log)

    # Build image slideshow from essay images if available
    if _img_paths:
        _plan = plan_slideshow(pipeline_state, _img_paths, _essay_imgs, visual_tags, _tts_dur, _log, _debug)

        # ── Load motion-clip substitutions before PIL pre-render ───────
        _wan_img_to_clip = load_motion_clip_map(out_dir, pipeline_state, _log)

        # ── Pre-render each image slot as a PIL Ken Burns clip (parallel) ──
        _kb_clips, _kb_tmp_dir = render_ken_burns_slots(
            _img_paths,
            _plan,
            _essay_imgs,
            _wan_img_to_clip,
            out_dir,
            _kb_env(),
            _log,
            _debug,
        )

        _filter, _use_xfade = build_slideshow_filter(len(_img_paths), _plan, _log, _debug)
        _slide_out = encode_slideshow(
            _kb_clips,
            _filter,
            _use_xfade,
            os.path.join(out_dir, f'{_slug}_slideshow.mp4'),
            _tts_dur,
            _kb_tmp_dir,
            _log,
            _debug,
        )
        if _slide_out:
            downloaded_clips = [_slide_out]

    ctx._img_paths = _img_paths
    ctx.downloaded_clips = downloaded_clips
