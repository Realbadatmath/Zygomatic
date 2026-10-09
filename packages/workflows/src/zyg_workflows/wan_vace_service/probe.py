# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Probe-then-render driver, keep-region paste-back and the from-frames generator (original lines 832-1197).

Split out of wan_vace_service.py; the code below is unchanged.
"""

import logging as _zyg_logging
from zyg_workflows.wan_vace_service.base import (
    Image,
    _QCBlocked,
    _T2V_MODEL,
    _VACE_MODULE,
    _log_noop,
    _static_neg,
    exe,
    os,
    shutil,
)
from zyg_workflows.wan_vace_service.beats import clip_negative, clip_prompt_beats
from zyg_workflows.wan_vace_service.static_clip import generate_vace_static_clip

_zyg_log = _zyg_logging.getLogger('zyg_workflows.wan_vace_service')


def generate_vace_with_probe(
    still_path,
    prompt,
    out_dir,
    num_frames=341,
    probe_frames=81,
    probe_char_regions=None,
    probe_min_track=3.0,
    probe_qc_fn=None,
    probe_prompt=None,
    log_fn=None,
    **kw,
):
    """THE 81-FRAME PROBE RULE (2026-07-30): any long run whose anchor or mask changed
    first renders ONE short window with identical settings (~11 min), runs the QC battery,
    and only commits to the full-length run when the probe passes. Costs 11 minutes; saves
    85 when something's wrong.

    Probe gates (defaults): character motion (track-path >= probe_min_track px on at least
    one region), camera static, no hard QC failure. probe_qc_fn(clip_path) -> (ok, note)
    adds caller-specific checks (identity, semantics...). The probe uses the FIRST
    scheduled sub-prompt when the prompt is ' | ' scheduled. Returns (final_clip|None, report).

    2026-07-30b: interpolate is forced OFF via probe_kw for the probe only — passing
    interpolate=False in **kw (as the v7/v8 recipe does) used to TypeError on the
    duplicated keyword; the full run still honors the caller's interpolate.

    2026-07-30c — THE PROBE MUST RENDER THE SAME REGIME AS THE RUN. The first version
    forced context_windows=False ("one native window"), which made the probe a DIFFERENT
    renderer from the run it gates: a single window leaves the static neutral-grey control
    dominating vace_end_percent of the denoise with no FreeNoise/overlap variation to break
    its grip. Measured: v7's exact proven-alive recipe (82px in the 341f context-window run)
    probed at 1.5-1.6px = "frozen" in the single-window regime — a FALSE FAILURE that
    blocked two good renders. (Single-window is only alive at the historical
    vace_end_percent ~0.42; v7/v8 run 0.6, which is safe only WITH context windows.)
    The probe now inherits the caller's context_windows and merely clamps the window to
    the probe length. probe_prompt= lets the caller pick a motion-bearing beat: the default
    prompt.split('|')[0] is whichever beat plays FIRST, which in a calm opening scene is the
    least motion-bearing instruction in the film — a motion gate must not be fed the stillest
    line in the script."""
    log = log_fn or _log_noop
    probe_dir = os.path.join(out_dir, '_probe')
    probe_prompt = (
        probe_prompt.strip() if probe_prompt else (prompt.split('|')[0].strip() if '|' in (prompt or '') else prompt)
    )
    probe_kw = dict(kw)
    probe_kw['interpolate'] = False  # probe stays native-fps
    if probe_kw.get('context_windows'):
        # same regime, shorter: clamp the window (and its overlap) to the probe length
        cf = min(int(probe_kw.get('context_frames') or probe_frames), probe_frames)
        probe_kw['context_frames'] = cf
        probe_kw['context_overlap'] = min(int(probe_kw.get('context_overlap') or 24), max(4, cf // 4))
    log(f'[probe] rendering {probe_frames}f probe first (the 81-frame rule)')
    pclip = generate_vace_static_clip(
        still_path, probe_prompt, probe_dir, num_frames=probe_frames, log_fn=log, **probe_kw
    )
    report = {'probe_clip': pclip, 'checks': []}
    if not pclip:
        report['verdict'] = 'probe render failed'
        log('[probe] FAILED to render — aborting long run')
        return None, report
    try:
        from zyg_workflows import pipeline_debug as DBG

        d = DBG.DebugRun(probe_dir, name='probe_qc')
        regions = probe_char_regions or [('chars', 0.0, 0.1, 1.0, 0.95)]
        q = d.qc_clip('probe', pclip, char_regions=regions)
        report['checks'] = [dict(c) for c in q.get('checks', [])]
        tracks = [c for c in q['checks'] if c['check'].startswith('track:')]
        moved = any((c.get('path_px_median') or 0) >= probe_min_track for c in tracks)
        cam = next((c for c in q['checks'] if c['check'] == 'camera_motion'), None)
        cam_ok = (cam or {}).get('ok', True)
        ok = moved and cam_ok
        note = []
        if not moved:
            note.append(
                f'probe frozen (max track {max((c.get("path_px_median") or 0) for c in tracks) if tracks else 0:.1f}px)'
            )
        if not cam_ok:
            note.append('camera drift in probe')
        if ok and probe_qc_fn:
            ok2, n2 = probe_qc_fn(pclip)
            ok = ok and ok2
            if n2:
                note.append(n2)
        report['verdict'] = 'PASS' if ok else ('FAIL: ' + '; '.join(note))
        d.finish()
    except _QCBlocked as e:
        # A gate at mode=block failed. This is a decision, not an error: do NOT
        # fall through to the 'proceeding cautiously' branch below, which exists
        # for BROKEN measurement and would turn a deliberate stop into a shrug.
        ok = False
        report['verdict'] = f'FAIL: blocked by QC gate — {e}'
        report['blocked_gates'] = list(getattr(e, 'gates', []) or [])
    except Exception as e:
        report['verdict'] = f'probe qc error ({e}) — proceeding cautiously'
        ok = True
    log(f'[probe] verdict: {report["verdict"]}')
    if report['verdict'].startswith('FAIL'):
        return None, report
    log(f'[probe] PASSED — committing to {num_frames}f full run')
    clip = generate_vace_static_clip(still_path, prompt, out_dir, num_frames=num_frames, log_fn=log, **kw)
    return clip, report


def paste_back_keep_regions(clip_path, still_path, mask_path, out_path, fps=17, log_fn=None):
    """A4 (2026-07-30): re-composite the ANCHOR's pixels over every keep (black-mask) region
    of a rendered clip. The VAE encode/decode round-trip drifts pixels even in 'preserved'
    areas and clips edges at mask boundaries (kijai #23) — pinned props (candle, book) come
    back pixel-exact; only the feather band blends. Pure numpy/ffmpeg."""
    log = log_fn or _log_noop
    import glob as _glob
    import subprocess
    import tempfile
    import numpy as _np

    tmp = tempfile.mkdtemp(prefix='pasteback_')
    try:
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
            return None
        frames = sorted(_glob.glob(os.path.join(tmp, 'f_*.png')))
        if not frames:
            return None
        W, H = Image.open(frames[0]).size
        still = _np.asarray(Image.open(still_path).convert('RGB').resize((W, H)), dtype=_np.float32)
        m = _np.asarray(Image.open(mask_path).convert('L').resize((W, H)), dtype=_np.float32)[:, :, None] / 255.0
        outdir = os.path.join(tmp, 'out')
        os.makedirs(outdir, exist_ok=True)
        for i, fp in enumerate(frames):
            fr = _np.asarray(Image.open(fp).convert('RGB'), dtype=_np.float32)
            comp = still * (1.0 - m) + fr * m  # black mask (keep) → anchor pixels
            Image.fromarray(_np.clip(comp, 0, 255).astype('uint8')).save(os.path.join(outdir, f'o_{i:05d}.png'))
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
                out_path,
            ],
            capture_output=True,
            text=True,
        )
        if enc.returncode != 0:
            return None
        log('[paste-back] keep regions restored pixel-exact')
        return out_path
    finally:
        import shutil as _sh

        _sh.rmtree(tmp, ignore_errors=True)


def generate_vace_clip_from_frames(
    frames_dir,
    mask_path,
    prompt,
    out_dir,
    num_frames=65,
    width=832,
    height=480,
    steps=25,
    cfg=6.0,
    shift=5.0,
    seed=11,
    vace_strength=0.9,
    vace_end_percent=1.0,
    ref_images_paths=None,
    loras=None,
    fps=24.0,
    log_fn=None,
):
    """VACE with a PER-FRAME control video (folder of frames) + mask + canon refs.
    Used by wan_face_restore: control = original clip frames (everything preserved),
    mask = face regions (re-rendered toward the refs + LoRAs). Returns clip path or None.

    fps (2026-07-31): was hardcoded 24.0 while the rest of this pipeline renders at 17 —
    a restore pass silently retimed its own output. Default kept at 24.0 so existing callers
    are unchanged; pass the source clip's fps to stop the drift."""
    log = log_fn or _log_noop
    from zyg_workflows import _comfy_client as CC

    os.makedirs(out_dir, exist_ok=True)
    st_mask = CC.stage_input_image(mask_path)
    st_refs = [CC.stage_input_image(p) for p in (ref_images_paths or []) if p and os.path.isfile(p)]
    pos = '固定镜头, static shot, fixed camera. ' + (prompt or '')
    # (1) 2026-07-31 — was pos[:900] / neg[:900] inline in node 20. 900 chars is ~300 umt5
    # tokens, barely half the 512-token budget, so this graph validated a MUTILATED prompt:
    # a probe that renders a different prompt from the run it gates is not a gate.
    neg_fr = _static_neg()
    pos = clip_prompt_beats(pos, tag='frames-graph positive', log_fn=log)
    neg_fr = clip_negative(neg_fr, log_fn=log)
    g = {
        '1': {
            'class_type': 'WanVideoModelLoader',
            'inputs': {
                'model': _T2V_MODEL,
                'base_precision': 'bf16',
                'quantization': 'fp8_e4m3fn',
                'load_device': 'offload_device',
                'attention_mode': os.environ.get('ZYG_WAN_ATTENTION', 'sdpa').strip() or 'sdpa',
                'extra_model': ['7', 0],
            },
        },
    }
    prev = None
    for i, (lname, lstr) in enumerate(loras or []):
        nid = f'8{i}'
        node = {
            'class_type': 'WanVideoLoraSelect',
            'inputs': {'lora': lname, 'strength': float(lstr), 'low_mem_load': False},
        }
        if prev:
            node['inputs']['prev_lora'] = [prev, 0]
        g[nid] = node
        prev = nid
    if prev:
        g['1']['inputs']['lora'] = [prev, 0]
    g.update(
        {
            '2': {
                'class_type': 'LoadWanVideoT5TextEncoder',
                'inputs': {'model_name': 'umt5-xxl-enc-bf16.safetensors', 'precision': 'bf16'},
            },
            '4': {
                'class_type': 'WanVideoVAELoader',
                'inputs': {'model_name': 'Wan2_1_VAE_bf16.safetensors', 'precision': 'bf16'},
            },
            '7': {'class_type': 'WanVideoVACEModelSelect', 'inputs': {'vace_model': _VACE_MODULE}},
            '13': {
                'class_type': 'LoadImagesFromFolderKJ',
                'inputs': {
                    'folder': os.path.abspath(frames_dir),
                    'width': int(width),
                    'height': int(height),
                    'keep_aspect_ratio': 'stretch',
                    'image_load_cap': int(num_frames),
                    'start_index': 0,
                },
            },
            '14': {'class_type': 'LoadImage', 'inputs': {'image': st_mask}},
            '15': {'class_type': 'RepeatImageBatch', 'inputs': {'image': ['14', 0], 'amount': int(num_frames)}},
            '16': {'class_type': 'ImageToMask', 'inputs': {'image': ['15', 0], 'channel': 'red'}},
            '20': {
                'class_type': 'WanVideoTextEncode',
                'inputs': {'t5': ['2', 0], 'positive_prompt': pos, 'negative_prompt': neg_fr, 'force_offload': True},
            },
            '60': {
                'class_type': 'WanVideoVACEEncode',
                'inputs': {
                    'vae': ['4', 0],
                    'width': int(width),
                    'height': int(height),
                    'num_frames': int(num_frames),
                    'strength': float(vace_strength),
                    'vace_start_percent': 0.0,
                    'vace_end_percent': float(vace_end_percent),
                    'input_frames': ['13', 0],
                    'input_masks': ['16', 0],
                },
            },
            '30': {
                'class_type': 'WanVideoSampler',
                'inputs': {
                    'model': ['1', 0],
                    'image_embeds': ['60', 0],
                    'text_embeds': ['20', 0],
                    'steps': int(steps),
                    'cfg': float(cfg),
                    'shift': float(shift),
                    'seed': int(seed),
                    'scheduler': 'unipc',
                    'riflex_freq_index': 0,
                    'force_offload': True,
                },
            },
            '40': {
                'class_type': 'WanVideoDecode',
                'inputs': {
                    'vae': ['4', 0],
                    'samples': ['30', 0],
                    'enable_vae_tiling': False,
                    'tile_x': 272,
                    'tile_y': 272,
                    'tile_stride_x': 144,
                    'tile_stride_y': 128,
                },
            },
            '45': {'class_type': 'CreateVideo', 'inputs': {'images': ['40', 0], 'fps': float(fps)}},
            '50': {
                'class_type': 'SaveVideo',
                'inputs': {'video': ['45', 0], 'filename_prefix': 'ZygFaceRestore', 'format': 'mp4', 'codec': 'h264'},
            },
        }
    )
    if st_refs:
        prev_ref = None
        for ri, rname in enumerate(st_refs[:3]):
            nid = f'7{ri + 1}'
            g[nid] = {'class_type': 'LoadImage', 'inputs': {'image': rname}}
            if prev_ref is None:
                prev_ref = [nid, 0]
            else:
                bid = f'7{ri + 5}'
                g[bid] = {'class_type': 'ImageBatch', 'inputs': {'image1': prev_ref, 'image2': [nid, 0]}}
                prev_ref = [bid, 0]
        g['60']['inputs']['ref_images'] = prev_ref
    try:
        from zyg_workflows import pipeline_debug as _dbg

        _d = _dbg.get_active()
        _d.record_prompts(
            'vace_face_restore', positive=pos, negative=neg_fr, loras=str(loras or []), refs=str(ref_images_paths or [])
        )
        _d.record_graph('vace_face_restore', g)
    except Exception as _exc:
        _zyg_log.debug('debug recorder skipped the vace face-restore graph: %s', _exc)
    # 2026-07-30 model attestation (see lora_attest.py) — hash-verify the LoRA chain,
    # the T2V checkpoint, the VACE module and the VAE before any frame is rendered.
    # Warn-only; ZYG_LORA_ATTEST=strict raises before submit.
    try:
        from zyg_workflows import lora_attest as _attest
    except Exception:
        _attest = None
    if _attest is not None:
        try:
            _attest.attest_submit(g, tag='vace_face_restore', log_fn=log)
        except _attest.AttestationError as e:
            log(f'[vace-frames] BLOCKED before submit by model attestation (strict): {e}')
            return None
    try:
        outs = CC.submit(g, timeout_s=int(os.environ.get('ZYG_WAN_TIMEOUT_S', '2400')))
    except Exception as e:
        log(f'[vace-frames] submit failed: {e}')
        return None
    if not (outs and os.path.isfile(outs[0])):
        return None
    clip = os.path.join(out_dir, 'vace_frames.mp4')
    shutil.copy2(outs[0], clip)
    return clip
