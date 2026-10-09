# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""generate_vace_static_clip - the VACE static-shot entry point (original lines 1917-2643).

Split out of wan_vace_service.py. The function is now an orchestrator over the stages in
static_clip_inputs.py (still, mask, control channel, prompts, beat gate) and
static_clip_graph.py (staging, the VACE graph, the submit); the behaviour, the log lines and
their order are the ones this file has always had.
"""

import logging as _zyg_logging
from zyg_workflows.wan_vace_service.base import (
    _log_noop,
    _static_neg,
    os,
)
from zyg_workflows.wan_vace_service.graded_pin import _resolve_pin_regions
from zyg_workflows.wan_vace_service.static_clip_graph import build_vace_graph, record_graph_debug, submit_static_graph
from zyg_workflows.wan_vace_service.static_clip_inputs import (
    build_control_channel,
    build_prompt_pair,
    fit_still_to_render,
    resolve_beat_map,
    resolve_mask_inputs,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.wan_vace_service')


def generate_vace_static_clip(
    still_path,
    prompt,
    out_dir,
    num_frames=65,
    steps=30,
    cfg=5.0,
    shift=2.0,
    seed=7,
    width=None,
    height=None,
    mask_path=None,
    n_regions=2,
    vace_strength=0.7,
    vace_end_percent=0.7,
    vace_start_percent=0.0,
    neutral_control=True,
    ref_images_paths=None,
    interpolate=True,
    loras=None,
    extra_negative='',
    context_windows=False,
    context_frames=81,
    context_overlap=24,
    context_stride=4,
    fuse_method='pyramid',
    set_plate_path=None,
    set_strength=1.0,
    set_end_percent=0.88,
    subject_strength=None,
    subject_end_percent=None,
    pin_regions=None,
    prop_plates=None,
    control_dir=None,
    control_blend=None,
    log_fn=None,
):
    """Locked-camera clip with the set pinned in-model via VACE. Returns clip path or None.

    loras : optional [(lora_name, strength), ...] — Wan LoRAs (e.g. trained character LoRAs
            'wan_chars/wan_char_<cid>.safetensors') chained into the model loader. Put each
            LoRA's trigger token in the prompt.

    2026-07-29 frozen-clip fix — correct inpaint semantics:
    neutral_control : grey-fill the control frames UNDER the character mask so the still's
            pixels stop leaking as per-frame guidance where generation should be free.
            (The first build fed the raw still everywhere at strength 1.0 for 100% of steps
            → the model reproduced the still 65 times.)
    vace_strength / vace_end_percent : relaxed defaults (0.7 / 0.7) so late denoising steps
            can synthesize actual character motion while the set stays pinned.

    A5 (2026-07-31) TWO VACE EMBEDS — set_plate_path / set_strength / set_end_percent.
            THE CENTRAL CONFLICT: one embed forces ONE compromise on both the wall (wants
            ~1.0 for ~90% of steps) and the characters (want ~0.5 and early release) — v8's
            0.8/end-0.6 is why the wall was under-pinned while the bodies were
            over-constrained. Passing a clean plate here builds a SECOND WanVideoVACEEncode
            (node 59, strength 1.0 / end 0.88 over the plate) chained into the subject embed
            via prev_vace_embeds, and drops the subject embed to 0.5 / end 0.35. This is what
            makes the A3 mask and the A4 plate safe. OFF unless set_plate_path is given, so
            existing callers are behaviourally byte-identical.
            The plate is expected to be A4's three-zone composite (plate everywhere, neutral
            grey only over genuinely moving parts) — it is guidance, not output.
            If the set embed re-freezes anything inside the mask, drop it to 0.85/0.75 —
            TUNE THE EMBED, NOT THE MASK GEOMETRY.

    fuse_method (A7) : 'pyramid' explicitly on the context-options node. The wrapper default
            is silently 'linear' (nodes.py:1906) and v8 omitted it — linear ramps only at
            window edges, so two windows placing a 2-4px quill/pipe stem 2-3px apart average
            into a doubled/bowed edge. context_overlap and context_stride are deliberately
            NOT touched (two research findings recommended opposite directions, and stride
            already floors to latent 1 at nodes_sampler.py:616-618).

    2026-07-31 — four env-gated changes, each independently bisectable. Full rationale lives
    in the module-level headers above; the switches are:
      ZYG_WAN_BEAT_CHARS   (default 1500) (1) per-beat prompt clipping. Always on; replaces
              the aggregate pos[:4000] / neg[:900]. Set higher only if you know the beat fits
              inside 512 umt5 tokens.
      ZYG_BEAT_MAP_GATE    (default 1)    (2) refuse to submit a ' | ' schedule whose beats
              are not all reachable by a context window. 0 downgrades to a loud warning.
      ZYG_VACE_DIFFDIFF    (default 0)    (3) graded pin via WanVideoEncode noise_mask.
              ZYG_VACE_DIFFDIFF_LEVEL (0.65) is a pinned box's value = pinned for the first
              35% of steps then free; ZYG_VACE_DIFFDIFF_NEUTRAL (1.0) is everywhere else and
              is a no-op. Needs pin_regions (below) — the flag alone now does nothing.
              ZYG_VACE_DIFFDIFF_WHOLE_MASK=1 restores the v12 whole-character-mask pin for
              bisecting only (it measured Cornelis' face 0.70 -> 0.33).
      ZYG_VACE_MASK_SEQ    (default 0)    (4) mask_path may be a DIRECTORY of per-frame PNGs
              or an .mp4; a matching per-frame control sequence is built alongside it. The
              single-PNG graph is byte-identical while this is unset.

    control_dir (2026-09-02, S01) : a DIRECTORY of external per-frame control frames
            (`ctrl_%05d.png`, the geom/vace_control.build naming, or `frame_%05d.png`).
            This is the argument whose absence meant no per-frame geometry sequence had
            ever reached a GPU render: node 13 has always been LoadImagesFromFolderKJ and
            has always been able to read any folder, and build_control_sequence was the
            only sequence the Python would hand it. Count is padded/truncated to
            num_frames by the same rule as build_mask_sequence, frames are resized to the
            render size, and the result is written to the run's own `_vace_ctrlseq/`.
            Works with a single-PNG mask (mask repeated per frame) or with
            ZYG_VACE_MASK_SEQ=1 (per-frame mask). Fail-safe: any problem logs and falls
            back to the control channel this function would have built without it.
    control_blend : 'mask' (default) composites the plate into the generate region only,
            `still*(1-m) + plate*m` — a depth/skeleton plate is a full-frame raster on
            black and handing that in raw would pin a black set. 'raw' uses the plate
            frames verbatim (the "we rendered the whole scene" case). Env override
            ZYG_VACE_CTRL_BLEND.
    PER-FRAME PAINTING (2026-09-02, S01) : prop_plates and ZYG_CHAR_GEOM_CTRL used to be
            children of the single-image branch, so they were structurally unreachable in
            exactly the mode that has per-frame control. They now run through
            paint_control_frame() on EVERY frame whenever control_dir or sequence mode is
            active; the single-image branch calls the same function once, so its behaviour
            and its log lines are unchanged.

    pin_regions (2026-08-01) : WHERE the graded pin applies, e.g.
            [{'box': (0.444, 0.560, 0.538, 0.878), 'level': 0.65}] — or, better,
            pin_regions_from_meta(shot_meta) so the geometry is not hardcoded twice.
            DEFAULT None = EMPTY = the pin is off and NO diffdiff node is emitted, so the
            graph is byte-identical to ZYG_VACE_DIFFDIFF=0 even when that flag is set.
            WHY it is per-region: v12 pinned the whole character mask and froze Cornelis'
            face (aliveness 0.70 -> 0.33) while doing nothing for Abel's hand jitter; the one
            thing it improved was the candle flicker (flow 0.179 -> 0.305), which the
            operator asked to keep. Pin the candle, leave the faces alone. PIN_WHOLE_MASK
            (or ZYG_VACE_DIFFDIFF_WHOLE_MASK=1) reinstates v12 for bisecting."""
    log = log_fn or _log_noop
    from zyg_workflows import _comfy_client as CC

    os.makedirs(out_dir, exist_ok=True)
    still_fit, W, H = fit_still_to_render(still_path, out_dir, width, height)
    masks = resolve_mask_inputs(mask_path, still_fit, out_dir, (W, H), int(num_frames), n_regions=n_regions, log_fn=log)
    if masks is None:
        return None
    controls = build_control_channel(
        still_fit,
        masks,
        out_dir,
        int(num_frames),
        (W, H),
        neutral_control=neutral_control,
        control_dir=control_dir,
        control_blend=control_blend,
        prop_plates=prop_plates,
        log_fn=log,
    )
    if controls is None:
        return None
    pos, neg = build_prompt_pair(prompt, extra_negative, _static_neg(), log_fn=log)
    beats_ok, beat_map = resolve_beat_map(
        pos,
        int(num_frames),
        context_windows,
        int(context_frames),
        int(context_overlap),
        int(context_stride),
        log_fn=log,
    )
    if not beats_ok:
        return None
    pin_regions_res = _resolve_pin_regions(pin_regions)
    g = build_vace_graph(
        CC,
        still_fit,
        masks,
        controls,
        (W, H),
        pos,
        neg,
        num_frames=num_frames,
        steps=steps,
        cfg=cfg,
        shift=shift,
        seed=seed,
        vace_strength=vace_strength,
        vace_start_percent=vace_start_percent,
        vace_end_percent=vace_end_percent,
        loras=loras,
        ref_images_paths=ref_images_paths,
        set_plate_path=set_plate_path,
        set_strength=set_strength,
        set_end_percent=set_end_percent,
        subject_strength=subject_strength,
        subject_end_percent=subject_end_percent,
        context_windows=context_windows,
        context_frames=context_frames,
        context_overlap=context_overlap,
        context_stride=context_stride,
        fuse_method=fuse_method,
        pin_regions_res=pin_regions_res,
        out_dir=out_dir,
        log_fn=log,
    )
    if g is None:
        return None
    record_graph_debug(
        g,
        pos,
        neg,
        masks,
        pin_regions_res,
        loras=loras,
        seed=seed,
        steps=steps,
        cfg=cfg,
        shift=shift,
        vace_strength=vace_strength,
        beat_map=beat_map,
    )
    return submit_static_graph(CC, g, out_dir, interpolate=interpolate, log_fn=log)
