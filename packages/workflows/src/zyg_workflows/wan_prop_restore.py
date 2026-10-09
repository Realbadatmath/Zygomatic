# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""wan_prop_restore.py — "video prop detailer": re-canonize a PROP region in a FINISHED clip.

2026-07-30, from the scene20 v7 forensic audit (output/multichar_seated/scene20_v7/forensics/):
the clay pipe morphs across the context-window seam at 13.2-13.9s (frames 233/234) — bowl
inflates, stem darkens/kinks, the grip flips to a physically-absurd bowl-cupping. Same cure
as wan_face_restore, aimed at a prop instead of a face: run the finished clip back through
VACE masked inpainting with ONLY the prop box masked white — inside the mask the model
re-synthesizes conditioned on the prop asset ref + prop LoRA; outside, the original frames
are the per-frame control (kept). Then feather-composite ONLY the masked region back over
the untouched original frames so motion, set and grade never take a VAE roundtrip.

    restore_prop_region(clip_path, box_frac, prompt, negative, out_path, ...) -> out_path|None
    restore_pipe(clip_path, out_path, ...)                                    -> out_path|None

Notes vs wan_face_restore:
- box_frac is one (fx0,fy0,fx1,fy1) fraction box on the clip geometry, dilated by
  expand_frac on every side; feather = GaussianBlur(sigma=feather_px/3), same math that
  gives face-restore its ~24px band at blur 8.
- denoise_strength: VACE has no img2img denoise knob. The original frames ARE the control,
  so control strength plays the role inversely: vace_strength = 1.0 - denoise_strength
  (denoise 0.55 -> control 0.45: enough freedom to rebuild the pipe toward the ref/LoRA,
  enough control to keep hand pose and lighting). The mapping is logged and returned in
  the dry-run summary so it is never a silent surprise.
- negative: generate_vace_clip_from_frames has no negative parameter (it hardcodes
  _static_neg()). We pass extra_negative if the service ever grows that kwarg (checked via
  inspect), else prepend ours by swapping wan_vace_service._static_neg for the duration of
  the call (single-threaded pipeline; restored in finally).
- dry_run=True builds everything up to the point of submission — explodes frames, builds
  the feathered mask, stages the control-frame folder, resolves refs/LoRAs — and returns a
  would-be job summary dict (frames, mask coverage %, call args) WITHOUT touching ComfyUI
  or the GPU. Use while trainings are running.
"""

import glob
import json
import os
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import logging as _zyg_logging
from zyg_workflows import paths
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


_HERE = os.path.dirname(os.path.abspath(__file__))
_LORA_ROOT = str(paths.ZYG_COMFY_ROOT / 'models' / 'loras')

# ── scene20 pipe defaults (v7 forensics: bowl/stem/grip morph zone, 480p fractions) ──
PIPE_BOX = (0.16, 0.30, 0.52, 0.78)
PIPE_PROMPT = (
    'zygpipe, long-stemmed white Gouda clay tobacco pipe, slender straight stem, '
    'small bowl, held by the stem, 17th century'
)
PIPE_NEGATIVE = 'cupping the bowl, hand covering the bowl opening, oversized bowl, dark stem, bent stem, two pipes'
_PIPE_LORA = 'wan_props/wan_prop_zygpipe.safetensors'


def _log_noop(_m):
    pass


PROP_ID_STRIDE = int(os.environ.get('ZYG_PROP_RESTORE_ID_STRIDE', '8'))
PROP_ID_MAX_FRAMES = int(os.environ.get('ZYG_PROP_RESTORE_ID_MAXFRAMES', '96'))


def _prop_require_gain():
    return os.environ.get('ZYG_PROP_RESTORE_REQUIRE_GAIN', '0').strip().lower() in ('1', 'true', 'yes', 'on')


def _prop_patch_series(clip, box_frac, ref_vecs, stride, log):
    """DINOv2 CLS cosine of the PROP BOX against the reference, once per sampled frame.

    Four-state ledger, same contract as the face instrument, with the two states a
    prop cannot reach reported as zero rather than quietly dropped:
      found        — the box was cropped and embedded
      unmeasurable — frame extract or embedder failed (ours, never a verdict)
      not_found / not_detectable — 0 by construction: a fixed box always exists.
      There is no prop DETECTOR here, so an empty box scores low rather than
      reporting 'the prop is not in shot'. That is a real limit, written down.
    """
    import shutil as _sh
    import tempfile as _tf
    import numpy as _np
    from zyg_workflows import identity_bank as _ib

    wd = _tf.mkdtemp(prefix='propid_')
    led = {'found': 0, 'not_found': 0, 'not_detectable': 0, 'unmeasurable': 0}
    vals = []
    try:
        try:
            frames = _ib._explode(clip, os.path.join(wd, 'f'), stride, PROP_ID_MAX_FRAMES)
        except Exception as e:
            led['unmeasurable'] += 1
            return {'ok': None, 'error': f'extract: {e}', 'ledger': led, 'series': []}
        series = []
        for i, fp in enumerate(frames):
            e = _ib.embed_region(fp, box_frac=tuple(box_frac), backend='dinov2')
            if not e.get('ok'):
                led['unmeasurable'] += 1
                series.append({'i': i * stride, 'state': 'unmeasurable', 'cosine': None, 'error': e.get('error')})
                continue
            v = _np.asarray(e['embedding'], dtype=_np.float32)
            c = float(max(float(v @ r) for r in ref_vecs))
            led['found'] += 1
            vals.append(c)
            series.append({'i': i * stride, 'state': 'found', 'cosine': round(c, 4)})
        if not vals:
            return {'ok': None, 'reason': 'no_measurable_frame', 'ledger': led, 'series': series}
        vals_s = sorted(vals)
        return {
            'ok': True,
            'ledger': led,
            'series': series,
            'cosine': round(sum(vals) / len(vals), 4),
            'cosine_min': round(vals_s[0], 4),
            'cosine_max': round(vals_s[-1], 4),
            'cosine_p10': round(vals_s[max(0, int(0.10 * (len(vals_s) - 1)))], 4),
            'cosine_median': round(vals_s[len(vals_s) // 2], 4),
            'spread': round(vals_s[-1] - vals_s[0], 4),
            'found': len(vals),
        }
    finally:
        _sh.rmtree(wd, ignore_errors=True)


def score_prop_delta(clip_in, clip_out, box_frac, ref_images, stride=None, log_fn=None):
    """DINOv2 patch similarity of the prop box to its reference, before and after.

    The prop analogue of the face-restore self-score: a masked re-render of a prop
    had no measurement either side of it, so 'the pipe was restored' meant 'the job
    returned a file'. Returns {'ok', 'before', 'after', 'delta', ...}; ok is None
    (never False) when the delta could not be taken.
    """
    log = log_fn or _log_noop
    out = {'ok': None, 'stride': stride or PROP_ID_STRIDE, 'box': [round(float(v), 4) for v in box_frac]}
    refs = [p for p in (ref_images or []) if p and os.path.isfile(p)]
    if not refs:
        out['error'] = 'no_prop_reference'
        return out
    try:
        import numpy as _np
        from zyg_workflows import identity_bank as _ib
    except Exception as e:
        out['error'] = f'identity_bank unavailable: {e}'
        return out
    if not _ib.enabled():
        out['error'] = 'disabled (ZYG_IDENTITY_CLIP=0)'
        return out
    ref_vecs = []
    for p in refs:
        e = _ib.embed_region(p, box_frac=None, backend='dinov2')
        if e.get('ok'):
            ref_vecs.append(_np.asarray(e['embedding'], dtype=_np.float32))
    if not ref_vecs:
        out['error'] = 'reference_not_embeddable'
        return out
    out['refs'] = [os.path.basename(p) for p in refs]
    st = stride or PROP_ID_STRIDE
    out['before'] = _prop_patch_series(clip_in, box_frac, ref_vecs, st, log)
    out['after'] = _prop_patch_series(clip_out, box_frac, ref_vecs, st, log)
    b, a = out['before'].get('cosine'), out['after'].get('cosine')
    out['delta'] = None if (b is None or a is None) else round(a - b, 4)
    bp, ap = out['before'].get('cosine_p10'), out['after'].get('cosine_p10')
    out['delta_p10'] = None if (bp is None or ap is None) else round(ap - bp, 4)
    out['ok'] = None if out['delta'] is None else bool(out['delta'] >= 0.0)
    log(f'[prop-restore][identity] dinov2 vs ref: before={b} after={a} delta={out["delta"]} (p10 {out["delta_p10"]})')
    return out


def find_clay_pipe_ref(log_fn=None):
    """Locate the clay-pipe asset preview. Order: asset_library_service (items/clay_pipe,
    the authoritative record) -> known preview path -> glob fallback. None if absent."""
    log = log_fn or _log_noop
    try:
        from zyg_workflows import asset_library_service as AL

        p = AL.preview_path('items', 'clay_pipe')
        if p and os.path.isfile(p):
            return p
    except Exception as e:
        log(f'[prop-restore] asset_library lookup unavailable ({e})')
    p = os.path.join(_HERE, 'output', 'assetlib_items', '_previews', 'clay_pipe.png')
    if os.path.isfile(p):
        return p
    for pat in (
        os.path.join(_HERE, 'output', 'assetlib_*', '_previews', '*pipe*.png'),
        os.path.join(_HERE, 'data', 'asset_libraries', '**', '*pipe*.png'),
    ):
        hits = sorted(glob.glob(pat, recursive=True))
        if hits:
            return hits[0]
    return None


def _norm_loras(loras, log):
    """Conform to wan_vace_service's LoRA chain: [(name_rel_to_lora_root, strength), ...].
    Accepts tuples or dicts; drops (with a log line, never an error) entries whose file is
    not on disk yet — prop LoRA trainings may still be running."""
    out = []
    for item in loras or []:
        if isinstance(item, dict):
            name = item.get('path') or item.get('lora') or item.get('name')
            strength = float(item.get('strength', 1.0))
        else:
            name, strength = item[0], float(item[1])
        if not name:
            continue
        full = name if os.path.isabs(name) else os.path.join(_LORA_ROOT, name)
        if os.path.isfile(full):
            rel = os.path.relpath(full, _LORA_ROOT) if os.path.isabs(name) else name
            out.append((rel, strength))
        else:
            log(f'[prop-restore] LoRA not on disk yet — skipping: {name}')
    return out


def _build_prop_mask(W, H, box_frac, expand_frac, feather_px):
    """White prop box on black, dilated + feathered exactly the wan_face_restore way."""
    fx0, fy0, fx1, fy1 = box_frac
    ex0 = max(0.0, fx0 - expand_frac)
    ey0 = max(0.0, fy0 - expand_frac)
    ex1 = min(1.0, fx1 + expand_frac)
    ey1 = min(1.0, fy1 + expand_frac)
    mask = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(mask)
    d.rectangle([int(W * ex0), int(H * ey0), int(W * ex1), int(H * ey1)], fill=255)
    sigma = max(1, int(round(feather_px / 3.0)))
    mask = mask.filter(ImageFilter.GaussianBlur(sigma))
    return mask, (ex0, ey0, ex1, ey1), sigma


def restore_prop_region(
    clip_path,
    box_frac,
    prompt,
    negative,
    out_path,
    ref_images=None,
    loras=None,
    denoise_strength=0.55,
    vace_end_percent=0.7,
    feather_px=24,
    expand_frac=0.04,
    fps=17,
    seed=1672,
    log_fn=None,
    steps=25,
    cfg=6.0,
    shift=5.0,
    dry_run=False,
):
    """Re-render ONLY the prop box toward the ref/LoRA canon; feather-composite back over
    the untouched originals; re-encode at the source fps. Returns out_path, or the summary
    dict when dry_run=True, or None on failure (fail-safe: callers keep their input clip)."""
    log = log_fn or _log_noop
    tmp = tempfile.mkdtemp(prefix='proprestore_')
    try:
        # 1) explode
        r = subprocess.run(
            [
                exe('ffmpeg'),
                '-y',
                '-loglevel',
                'error',
                '-i',
                clip_path,
                '-vsync',
                '0',
                os.path.join(tmp, 'f_%05d.png'),
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            log('[prop-restore] extract failed')
            return None
        frames = sorted(glob.glob(os.path.join(tmp, 'f_*.png')))
        if len(frames) < 8:
            log('[prop-restore] too few frames')
            return None
        with Image.open(frames[0]) as f0:
            W, H = f0.size

        # 2) prop mask (white = re-render), dilated + feathered
        mask, box_exp, sigma = _build_prop_mask(W, H, box_frac, expand_frac, feather_px)
        mask_path = os.path.join(tmp, 'propmask.png')
        mask.save(mask_path)
        cov = float((np.asarray(mask) > 127).mean() * 100)
        log(
            f'[prop-restore] mask {box_exp[0]:.2f},{box_exp[1]:.2f}-{box_exp[2]:.2f},'
            f'{box_exp[3]:.2f} sigma={sigma}px coverage={cov:.1f}%'
        )

        # 3) VACE masked re-render: control = ORIGINAL frames, mask = prop box,
        #    refs = prop asset preview, LoRA = trained prop LoRA (when present)
        num_frames = len(frames) if len(frames) % 4 == 1 else (len(frames) // 4) * 4 + 1
        frames_use = frames[:num_frames]
        refs = [p for p in (ref_images or []) if p and os.path.isfile(p)]
        for p in ref_images or []:
            if p and not os.path.isfile(p):
                log(f'[prop-restore] ref missing — skipped: {p}')
        loras_use = _norm_loras(loras, log)
        vace_strength = max(0.05, min(1.0, 1.0 - float(denoise_strength)))
        log(
            f'[prop-restore] denoise {denoise_strength:.2f} -> vace_strength '
            f'{vace_strength:.2f}, end_percent {vace_end_percent:.2f}'
        )

        ctrl_dir = os.path.join(tmp, 'ctrl')
        os.makedirs(ctrl_dir, exist_ok=True)
        for i, fp in enumerate(frames_use):
            shutil.copy2(fp, os.path.join(ctrl_dir, f'c_{i:05d}.png'))

        try:
            from zyg_workflows import pipeline_debug as _dbg

            _d = _dbg.get_active()
            _d.snapshot('prop_restore_mask', mask_path)
            _d.record_prompts(
                'prop_restore',
                positive=prompt,
                negative=negative,
                loras=str(loras_use),
                refs=str(refs),
                seed=seed,
                vace_strength=vace_strength,
                vace_end_percent=vace_end_percent,
                dry_run=dry_run,
            )
        except Exception as _exc:
            _zyg_log.debug('debug recorder skipped the prop-restore prompts: %s', _exc)

        if dry_run:
            # everything up to submission is built — report the would-be job, touch no GPU
            summary = {
                'dry_run': True,
                'clip': clip_path,
                'would_call': 'wan_vace_service.generate_vace_clip_from_frames',
                'frames_total': len(frames),
                'num_frames': num_frames,
                'ctrl_frames_staged': len(frames_use),
                'width': W,
                'height': H,
                'fps': fps,
                'mask_coverage_pct': round(cov, 2),
                'box_frac_expanded': box_exp,
                'feather_sigma_px': sigma,
                'vace_strength': vace_strength,
                'vace_end_percent': float(vace_end_percent),
                'steps': steps,
                'cfg': cfg,
                'shift': shift,
                'seed': seed,
                'refs': refs,
                'loras': loras_use,
                'prompt': prompt,
                'negative': negative,
            }
            keep = os.path.splitext(out_path)[0] + '_propmask.png'
            os.makedirs(os.path.dirname(os.path.abspath(keep)), exist_ok=True)
            mask.save(keep)
            summary['mask_png'] = keep
            log(f'[prop-restore] DRY RUN: {num_frames}f staged, mask {cov:.1f}% — no submission')
            return summary

        from zyg_workflows import wan_vace_service as V

        call_kw = dict(
            num_frames=num_frames,
            width=W,
            height=H,
            steps=steps,
            cfg=cfg,
            shift=shift,
            seed=seed,
            vace_strength=vace_strength,
            vace_end_percent=float(vace_end_percent),
            ref_images_paths=refs,
            loras=loras_use,
            log_fn=log,
        )
        import inspect

        params = inspect.signature(V.generate_vace_clip_from_frames).parameters
        if 'extra_negative' in params:
            call_kw['extra_negative'] = negative
            clipseg = V.generate_vace_clip_from_frames(ctrl_dir, mask_path, prompt, os.path.join(tmp, 'out'), **call_kw)
        else:
            # no negative kwarg in the service — prepend ours via _static_neg for this call
            orig_neg = V._static_neg

            def _neg_with_prop():
                try:
                    base = orig_neg()
                except Exception:
                    base = ''
                if negative:
                    return negative.strip().rstrip(',') + ', ' + base
                return base

            V._static_neg = _neg_with_prop
            try:
                clipseg = V.generate_vace_clip_from_frames(
                    ctrl_dir, mask_path, prompt, os.path.join(tmp, 'out'), **call_kw
                )
            finally:
                V._static_neg = orig_neg
        if not clipseg:
            log('[prop-restore] VACE re-render failed')
            return None

        # 4) feather-composite ONLY the masked region back over the originals
        rr = subprocess.run(
            [exe('ffmpeg'), '-y', '-loglevel', 'error', '-i', clipseg, '-vsync', '0', os.path.join(tmp, 'r_%05d.png')],
            capture_output=True,
            text=True,
        )
        if rr.returncode != 0:
            return None
        rendered = sorted(glob.glob(os.path.join(tmp, 'r_*.png')))
        matte = np.asarray(mask, dtype=np.float32)[:, :, None] / 255.0
        outdir = os.path.join(tmp, 'comp')
        os.makedirs(outdir, exist_ok=True)
        # composite over ALL source frames (frames past num_frames pass through untouched
        # — never shorten the clip)
        for i, fp in enumerate(frames):
            orig = np.asarray(Image.open(fp).convert('RGB'), dtype=np.float32)
            if i < len(rendered):
                ren = np.asarray(Image.open(rendered[i]).convert('RGB').resize((W, H)), dtype=np.float32)
                comp = orig * (1.0 - matte) + ren * matte
            else:
                comp = orig
            Image.fromarray(np.clip(comp, 0, 255).astype('uint8')).save(os.path.join(outdir, f'o_{i:05d}.png'))
        stage = out_path + '.stage.mp4'
        enc = subprocess.run(
            [
                exe('ffmpeg'),
                '-y',
                '-loglevel',
                'error',
                '-framerate',
                str(fps),
                '-i',
                os.path.join(outdir, 'o_%05d.png'),
                '-c:v',
                'libx264',
                '-pix_fmt',
                'yuv420p',
                '-crf',
                '16',
                stage,
            ],
            capture_output=True,
            text=True,
        )
        if enc.returncode != 0 or not os.path.isfile(stage):
            try:
                os.remove(stage)
            except OSError as _exc:
                _zyg_log.debug('failed encode %s left behind: %s', stage, _exc)
            return None
        # ── did the prop re-render move TOWARD its reference? (2026-09-02) ─────
        pid = score_prop_delta(clip_path, stage, box_frac, ref_images, log_fn=log)
        try:
            with open(out_path + '.identity.json', 'w') as fh:
                json.dump(
                    {
                        'clip_in': clip_path,
                        'clip_out': out_path,
                        'require_gain': _prop_require_gain(),
                        'prop_identity': pid,
                    },
                    fh,
                    indent=2,
                    default=str,
                )
        except Exception as e:
            log(f'[prop-restore] identity sidecar not written ({e})')
        if _prop_require_gain() and pid.get('ok') is False:
            log(
                f'[prop-restore] REFUSED: prop similarity fell (delta {pid.get("delta")}) '
                f'— ZYG_PROP_RESTORE_REQUIRE_GAIN=1, keeping the original clip'
            )
            try:
                os.remove(stage)
            except OSError as _exc:
                _zyg_log.debug('refused restore %s left behind: %s', stage, _exc)
            return None
        if pid.get('ok') is None:
            log(f'[prop-restore] prop delta UNMEASURABLE ({pid.get("error") or pid.get("reason")}) — publishing anyway')
        os.replace(stage, out_path)
        log(
            f'[prop-restore] -> {os.path.basename(out_path)} '
            f'(mask {cov:.1f}%, {len(rendered)}/{len(frames)}f re-rendered, '
            f'prop delta {pid.get("delta")})'
        )
        return out_path
    except Exception as e:
        log(f'[prop-restore] failed ({e})')
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def restore_pipe(clip_path, out_path, log_fn=None, **kw):
    """Convenience wrapper for the scene20 clay pipe: canonical box/prompt/negative, clay
    pipe preview as VACE ref, wan_prop_zygpipe LoRA @0.9 when its training has landed
    (graceful skip + log while it is still running). Extra kwargs (dry_run=True,
    denoise_strength=..., seed=...) pass through to restore_prop_region."""
    log = log_fn or _log_noop
    ref = find_clay_pipe_ref(log)
    if ref:
        log(f'[prop-restore] pipe ref: {ref}')
    else:
        log('[prop-restore] clay pipe preview NOT found — rendering without prop ref')
    loras = []
    if os.path.isfile(os.path.join(_LORA_ROOT, _PIPE_LORA)):
        loras.append((_PIPE_LORA, 0.9))
        log(f'[prop-restore] pipe LoRA active: {_PIPE_LORA} @0.9')
    else:
        log(f'[prop-restore] {_PIPE_LORA} absent (training still running?) — proceeding without it')
    return restore_prop_region(
        clip_path,
        PIPE_BOX,
        PIPE_PROMPT,
        PIPE_NEGATIVE,
        out_path,
        ref_images=[ref] if ref else None,
        loras=loras or None,
        log_fn=log,
        **kw,
    )
