# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The input stages of generate_vace_static_clip: still, mask, control channel, prompts.

Extracted from static_clip.py (2026-10-09) so the entry point is an orchestrator and every
stage can be exercised without a GPU. The code is the code that was inside the function;
what changed is that the dataflow between the stages is now explicit — each stage takes
what it reads and returns what the next one needs, and a stage that refuses to let the run
reach a GPU returns None instead of `return None`-ing out of the caller.
"""

from dataclasses import dataclass, field

from zyg_workflows.wan_vace_service.base import (
    Image,
    _env_flag,
    _log_noop,
    os,
)
from zyg_workflows.wan_vace_service.beats import assert_no_dead_beats, clip_negative, clip_prompt_beats
from zyg_workflows.wan_vace_service.masks import build_char_mask, preflight_mask_gates
from zyg_workflows.wan_vace_service.sequences import (
    build_control_from_dir,
    build_control_sequence,
    build_mask_sequence,
    is_mask_sequence,
    paint_control_frame,
    paint_control_sequence,
    stamp_control_channel,
)

STATIC_PREFIX = '固定镜头, static shot, fixed camera, locked-off tripod shot. '


@dataclass
class MaskPlan:
    """The mask inputs one static clip renders from.

    mask_path    : the single-PNG mask — always set, built by build_char_mask when the
                   caller passed none, resized to the render size when it passed one.
    mask_dir     : directory of per-frame masks in sequence mode, else None.
    pin_mask_src : the still-frame mask the graded pin is derived from (the union PNG in
                   sequence mode) — else the graded pin silently degrades to binary.
    seq_mode     : True when mask_path was a frame sequence and ZYG_VACE_MASK_SEQ is on.
    """

    mask_path: str
    mask_dir: str | None
    pin_mask_src: str
    seq_mode: bool


@dataclass
class ControlPlan:
    """The control channel VACE is handed, and the receipt of how it was built.

    control_src : the single control image (node 11), meaningful only when ctrl_dir is None.
    ctrl_dir    : directory of per-frame control frames (node 13), else None.
    ctrl_mode   : the human-readable mode string that goes into the run's receipt.
    ctrl_audit  : build_control_from_dir's audit dict ({} when no control_dir was used).
    paint_audit : paint_control_sequence's audit dict ({} in the single-image path).
    """

    control_src: str
    ctrl_dir: str | None
    ctrl_mode: str
    ctrl_audit: dict = field(default_factory=dict)
    paint_audit: dict = field(default_factory=dict)


def fit_still_to_render(still_path, out_dir, width=None, height=None):
    """Crop STILL_PATH to the output aspect, resize it to the render size, save it.

    Returns (still_fit_path, W, H). The render size comes from width/height, else from
    ZYG_WAN_WIDTH / ZYG_WAN_HEIGHT, else 832x480. Letterbox-free: a still whose aspect is
    more than 1% off the output's is CROPPED about its centre (never padded), so no bars
    are introduced and the composition stays centred. The fitted still is written to
    `<out_dir>/_vace_still.png` and is what every later stage measures.
    """
    with Image.open(still_path) as im:
        sw, sh = im.size
    W = int(width or os.environ.get('ZYG_WAN_WIDTH', 832))
    H = int(height or os.environ.get('ZYG_WAN_HEIGHT', 480))
    # letterbox-free: crop still to output aspect then resize (keeps composition centred)
    ar_out = W / H
    ar_in = sw / sh
    im = Image.open(still_path).convert('RGB')
    if abs(ar_in - ar_out) > 0.01:
        if ar_in > ar_out:
            nw = int(sh * ar_out)
            im = im.crop(((sw - nw) // 2, 0, (sw + nw) // 2, sh))
        else:
            nh = int(sw / ar_out)
            im = im.crop((0, (sh - nh) // 2, sw, (sh + nh) // 2))
    im = im.resize((W, H), Image.LANCZOS)
    still_fit = os.path.join(out_dir, '_vace_still.png')
    im.save(still_fit)
    return still_fit, W, H


def gate_mask_png(pth, size, log_fn=None):
    """C3 preflight with the shared ZYG_MASK_GATE escape hatch. -> True to continue."""
    log = log_fn or _log_noop
    ok_m, why_m = preflight_mask_gates(pth, expect_size=size, log_fn=log)
    if ok_m:
        return True
    if os.environ.get('ZYG_MASK_GATE', '1') == '0':
        log(f'[vace] mask preflight WARN (ZYG_MASK_GATE=0) on {os.path.basename(pth)}: {why_m}')
        return True
    log(
        f'[vace] BLOCKED before submit by mask preflight on {os.path.basename(pth)}: '
        f'{why_m} — rebuild with build_motion_envelope_mask, or set ZYG_MASK_GATE=0 '
        'to render anyway'
    )
    return False


def resolve_mask_inputs(mask_path, still_fit, out_dir, size, num_frames, n_regions=2, log_fn=None):
    """Settle the three accepted mask shapes into one MaskPlan. -> MaskPlan, or None to abort.

    MASK. Three accepted shapes:
      None            -> build_char_mask (unchanged)
      a single image  -> the historical path; BYTE-IDENTICAL while ZYG_VACE_MASK_SEQ is
                         unset, which is the whole point of the env gate
      a directory/mp4 -> (4) per-frame mask sequence, requires ZYG_VACE_MASK_SEQ=1

    None is returned — and no GPU is committed — when a frame sequence arrives with the env
    gate unset, when the sequence cannot be built, or when a mask fails the C3 preflight.
    """
    log = log_fn or _log_noop
    W, H = size
    seq_mode = False
    if mask_path and is_mask_sequence(mask_path):
        if _env_flag('ZYG_VACE_MASK_SEQ'):
            seq_mode = True
        else:
            log(
                f'[vace] mask_path {mask_path} is a frame sequence but ZYG_VACE_MASK_SEQ is '
                'not set — refusing to guess. Set ZYG_VACE_MASK_SEQ=1 or pass a single PNG'
            )
            return None
    mask_dir = None
    pin_mask_src = mask_path  # the still-frame mask the graded pin is derived from

    if not mask_path:
        mask_path = os.path.join(out_dir, '_vace_charmask.png')
        build_char_mask(still_fit, mask_path, n_regions=n_regions, log_fn=log)
        pin_mask_src = mask_path  # else the graded pin silently degrades to binary
    elif seq_mode:
        mask_dir, pin_mask_src, _n_src = build_mask_sequence(mask_path, out_dir, int(num_frames), (W, H), log_fn=log)
        if not mask_dir:
            log('[vace] mask sequence could not be built — aborting before GPU')
            return None
        # gate a SAMPLE of the sequence (first/middle/last) — a sequence whose frames fail
        # C3 is exactly as expensive a mistake as a single PNG that fails it
        for gi in sorted({0, int(num_frames) // 2, int(num_frames) - 1}):
            if not gate_mask_png(os.path.join(mask_dir, f'm_{gi:05d}.png'), (W, H), log_fn=log):
                return None
    else:
        # ensure mask matches output size
        mimg = Image.open(mask_path).convert('L')
        if mimg.size != (W, H):
            mimg.resize((W, H), Image.LANCZOS).save(mask_path)
        # C3 (2026-07-31): a supplied mask is checked BEFORE any GPU is committed. v8's mask
        # (white_frac 0.795 / soft_band 0.221 / border 255) would have been blocked here and
        # saved 4.5h. Gate runs after the resize above so it measures what actually ships.
        if not gate_mask_png(mask_path, (W, H), log_fn=log):
            return None
    return MaskPlan(mask_path=mask_path, mask_dir=mask_dir, pin_mask_src=pin_mask_src, seq_mode=seq_mode)


def neutralised_control_image(still_fit, mask_path, out_dir, size, log_fn=None):
    """Grey-fill the generate region of STILL_FIT. -> the written control PNG path.

    Inpaint semantics: `still*(1-m) + 127*m` at the render size, written to
    `<out_dir>/_vace_control.png`. The set stays as hard per-frame control; the characters
    get a free canvas instead of the still's own pixels leaking in as guidance.
    """
    log = log_fn or _log_noop
    W, H = size
    import numpy as _np

    s_arr = _np.asarray(Image.open(still_fit).convert('RGB'), dtype=_np.float32)
    m_arr = _np.asarray(Image.open(mask_path).convert('L').resize((W, H)), dtype=_np.float32)[:, :, None] / 255.0
    grey = _np.full_like(s_arr, 127.0)
    ctrl = s_arr * (1.0 - m_arr) + grey * m_arr
    control_src = os.path.join(out_dir, '_vace_control.png')
    Image.fromarray(ctrl.astype('uint8')).save(control_src)
    log('[vace] control frames neutralized under mask')
    return control_src


def external_control_frames(control_dir, still_fit, masks, out_dir, num_frames, size, control_blend=None, log_fn=None):
    """(S01) EXTERNAL PLATES FIRST. -> (ctrl_dir or None, ctrl_mode, audit).

    When a control_dir is given it replaces the grey fill as the content of the generate
    region; everything after it (per-frame painting, the graph wiring) is shared with
    sequence mode. A failure here is not fatal: ctrl_dir comes back None and the caller's
    ordinary branches build the channel they always built. 'mask' blend composites the
    plate into the generate region only (`still*(1-m) + plate*m`); 'raw' uses the plate
    frames verbatim. Env override: ZYG_VACE_CTRL_BLEND.
    """
    log = log_fn or _log_noop
    W, H = size
    ctrl_dir, ctrl_mode, ctrl_audit = None, 'still (neutral_control off)', {}
    _blend = control_blend or os.environ.get('ZYG_VACE_CTRL_BLEND', 'mask')
    if masks.seq_mode and not masks.mask_dir:
        log('[ctrl-dir] sequence mode without a mask dir — ignoring control_dir')
        return ctrl_dir, ctrl_mode, ctrl_audit
    _cd, ctrl_audit = build_control_from_dir(
        control_dir,
        still_fit,
        out_dir,
        int(num_frames),
        (W, H),
        mask_dir=masks.mask_dir,
        mask_png=(None if masks.mask_dir else masks.mask_path),
        blend=_blend,
        log_fn=log,
    )
    if _cd:
        ctrl_dir = _cd
        ctrl_mode = f'control_dir ({_blend})'
    else:
        log(
            f'[ctrl-dir] NOT USED ({ctrl_audit.get("reason")}) — falling back to '
            'the control channel this run would have built without it'
        )
    return ctrl_dir, ctrl_mode, ctrl_audit


def painted_single_control(still_fit, masks, out_dir, size, prop_plates=None, log_fn=None):
    """The one control frame of the single-image path: grey-filled, then painted.

    -> the path of the frame node 11 loads.

    ── GEOMETRY INTO THE CONTROL (props 2026-08-01, character 2026-08-05)
    The grey fill is the whole reason the ledger and the pipe morph: measured on
    scene20_v15 they sit 95.4% and 100% inside this mask, so VACE receives a CONSTANT
    where they are and re-invents both objects in each of six context windows from text
    alone. Text pins semantics, not geometry. The same mechanism costs the CHARACTER
    identity (prop fidelity ~0 by frame 80, identity decay by frame 200, scene20
    v15/v28/v30).

    Both painters put rendered/detected geometry back into exactly that region. This is a
    GUIDE, not a paste: it goes into the control frame, which VACE releases at
    vace_end_percent. That is what makes it safe where the 2026-07-30 paste-back was not —
    the model stays free to draw a hand in front of the book, it is only told what shape
    the book is. Fail-safe: any error leaves the neutral control exactly as it was.
    Rollback: ZYG_CHAR_GEOM_CTRL=0.

    (S01, 2026-09-02) the block is paint_control_frame() so the per-frame path can call the
    identical code for every frame. This single-image call keeps the same output names and
    the same log lines it always had.
    """
    log = log_fn or _log_noop
    control_src = neutralised_control_image(still_fit, masks.mask_path, out_dir, size, log_fn=log)
    return paint_control_frame(
        control_src,
        masks.mask_path,
        os.path.join(out_dir, '_vace_control_props.png'),
        os.path.join(out_dir, '_vace_control_char.png'),
        prop_plates=prop_plates,
        still_fit=still_fit,
        log_fn=log,
    )


def build_control_channel(
    still_fit,
    masks,
    out_dir,
    num_frames,
    size,
    neutral_control=True,
    control_dir=None,
    control_blend=None,
    prop_plates=None,
    log_fn=None,
):
    """Build the control channel VACE is handed and stamp the run's receipt for it.

    Takes the fitted still and the MaskPlan; returns a ControlPlan, or None when the run
    must not reach a GPU (a per-frame mask whose per-frame control sequence failed —
    shipping a union-grey still under it would paint grey walls).

    Precedence, unchanged: an external control_dir replaces the grey fill as the content of
    the generate region; otherwise sequence mode builds a grey per-frame sequence and the
    single-image path builds one neutralised frame. Whenever the channel ends up a SEQUENCE
    the prop/character painters run on EVERY frame; the single-image path calls the same
    painter once. The receipt (stamp_control_channel) is written last, as it always was.
    """
    log = log_fn or _log_noop
    W, H = size
    # control frames: still with the generate-region NEUTRALIZED (inpaint semantics) —
    # the set stays as hard per-frame control, characters get a free canvas
    control_src = still_fit
    ctrl_dir = None
    ctrl_mode = 'still (neutral_control off)'
    ctrl_audit = {}
    paint_audit = {}
    if control_dir and neutral_control:
        ctrl_dir, ctrl_mode, ctrl_audit = external_control_frames(
            control_dir, still_fit, masks, out_dir, num_frames, (W, H), control_blend, log_fn=log
        )
    if neutral_control and not ctrl_dir:
        if masks.seq_mode:
            # per-frame mask NEEDS per-frame control: a union-grey still under a shrinking
            # mask hands flat grey to VACE's `inactive` branch as keep-this-content (see the
            # (4) header) — that paints grey walls. No silent downgrade.
            ctrl_dir = build_control_sequence(still_fit, masks.mask_dir, out_dir, int(num_frames), (W, H), log_fn=log)
            if not ctrl_dir:
                log(
                    '[vace] per-frame control sequence FAILED — aborting rather than '
                    'shipping a union-grey control under a per-frame mask'
                )
                return None
            ctrl_mode = 'build_control_sequence (grey per-frame)'
        else:
            control_src = painted_single_control(still_fit, masks, out_dir, (W, H), prop_plates=prop_plates, log_fn=log)
            ctrl_mode = 'single control image'

    # (S01) PER-FRAME PAINTING. Whenever the control channel is a SEQUENCE — an external
    # control_dir or ZYG_VACE_MASK_SEQ — the two painters above have to run on every frame.
    # Until today they could not run at all in that mode: they were `if neutral_control:`
    # single-image children, so the one path with per-frame control was the one path with
    # no geometry in it.
    if ctrl_dir:
        ctrl_dir, paint_audit = paint_control_sequence(
            ctrl_dir,
            still_fit,
            out_dir,
            int(num_frames),
            mask_dir=masks.mask_dir,
            mask_png=(None if masks.mask_dir else masks.mask_path),
            prop_plates=prop_plates,
            log_fn=log,
        )

    stamp_control_channel(
        out_dir,
        ctrl_dir or control_src,
        int(num_frames),
        {
            'mode': ctrl_mode,
            'control_dir_arg': control_dir,
            'control_blend': (control_blend or os.environ.get('ZYG_VACE_CTRL_BLEND', 'mask')) if control_dir else None,
            'seq_mode': bool(masks.seq_mode),
            'neutral_control': bool(neutral_control),
            'mask_dir': masks.mask_dir,
            'audit': ctrl_audit,
            'painting': paint_audit,
            'ZYG_CHAR_GEOM_CTRL': os.environ.get('ZYG_CHAR_GEOM_CTRL', '1'),
            'prop_plates': len(prop_plates or []),
        },
        log_fn=log,
    )
    return ControlPlan(
        control_src=control_src,
        ctrl_dir=ctrl_dir,
        ctrl_mode=ctrl_mode,
        ctrl_audit=ctrl_audit,
        paint_audit=paint_audit,
    )


def build_prompt_pair(prompt, extra_negative, base_negative, log_fn=None):
    """Assemble the (positive, negative) umt5 prompts for a locked-camera clip.

    The static-camera grammar is prefixed onto EVERY beat of a scheduled ' | ' prompt —
    each sub-prompt must be standalone, because the wrapper selects one per window.
    extra_negative is prepended to BASE_NEGATIVE (the caller passes _static_neg()'s result
    so wan_prop_restore's live swap of that function still reaches this call). Both strings
    then go through (1) per-beat clipping, which replaced the aggregate pos[:4000]/neg[:900].
    """
    log = log_fn or _log_noop
    _pfx = STATIC_PREFIX
    if '|' in (prompt or ''):
        # scheduled per-window prompts (kijai " | " syntax): every sub-prompt must be
        # standalone — prefix the camera grammar onto each
        pos = ' | '.join(_pfx + p.strip() for p in prompt.split('|'))
    else:
        pos = _pfx + (prompt or '')
    neg = base_negative
    if extra_negative:
        neg = extra_negative.strip().rstrip(',') + ', ' + neg
    # (1) PER-BEAT CLIPPING — replaces pos[:4000] / neg[:900] (see the header). The prefix is
    # already on every beat at this point, so what is measured here is what umt5 receives.
    pos = clip_prompt_beats(pos, tag='positive', log_fn=log)
    neg = clip_negative(neg, log_fn=log)
    return pos, neg


def resolve_beat_map(pos, num_frames, context_windows, context_frames, context_overlap, context_stride, log_fn=None):
    """(2) DEAD-BEAT GATE. -> (ok, beat_map); ok False means abort before the GPU.

    A ' | ' schedule is only selectable inside the context loop, so beats 1+ are dead
    without context_windows, and a window that spans no beat is a silently dropped beat.
    Fail-closed; ZYG_BEAT_MAP_GATE=0 downgrades both refusals to a loud warning, in which
    case ok stays True and beat_map stays None. An unscheduled prompt is always (True, None).
    """
    log = log_fn or _log_noop
    beat_map = None
    if '|' in (pos or ''):
        n_beats = len(pos.split('|'))
        hard = os.environ.get('ZYG_BEAT_MAP_GATE', '1') != '0'
        if not context_windows:
            why = (
                f'scheduled prompt has {n_beats} beats but context_windows=False — the '
                'wrapper only picks a per-window sub-prompt inside the context loop '
                '(nodes_sampler.py:1886), so beats 1+ are never selected'
            )
            if hard:
                log(f'[vace] BLOCKED before submit: {why} (ZYG_BEAT_MAP_GATE=0 to override)')
                return False, None
            log(f'[vace] WARNING (ZYG_BEAT_MAP_GATE=0): {why}')
        else:
            try:
                # node 60 always carries ref_images (the still at minimum) -> has_ref True
                beat_map = assert_no_dead_beats(
                    int(num_frames),
                    int(context_frames),
                    int(context_overlap),
                    n_beats,
                    has_ref=True,
                    context_stride=int(context_stride),
                    fps=17.0,
                    log_fn=log,
                )
                log(
                    '[beat-map] window spans: '
                    + ', '.join(
                        f'w{i} {t0:.1f}-{t1:.1f}s->beat {p}'
                        for i, ((t0, t1), p) in enumerate(zip(beat_map['window_times'], beat_map['mapping']))
                    )
                )
            except ValueError as e:
                if hard:
                    log(f'[vace] BLOCKED before submit by the beat map: {e} (ZYG_BEAT_MAP_GATE=0 to render anyway)')
                    return False, None
                log(f'[vace] WARNING (ZYG_BEAT_MAP_GATE=0): {e}')
    return True, beat_map
