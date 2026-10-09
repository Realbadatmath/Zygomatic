# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""wan_video_service — The public generate() entry point together with the diffusers pipeline state it mutates."""

from zyg_workflows.wan_video_service.constants import (
    _CLIP_FRAMES,
    _DEFAULT_N_CLIPS,
    _EMOTION_PRIORITY,
    _GUIDANCE,
    _HEIGHT,
    _INFER_STEPS,
    _MODEL_ID,
    _MOTION_FREEZE_THRESH,
    _N_CHAINED,
    _T2V_MODEL_ID,
    _WIDTH,
    _comfy,
    _zyg_log,
    gc,
    json,
    os,
    threading,
    time,
)
from zyg_workflows.wan_video_service import api_passes as _ap
from zyg_workflows.wan_video_service.helpers import (
    _generate_via_comfyui,
)

_pipe = None
_pipe_lock = threading.Lock()

_t2v_pipe = None
_t2v_pipe_lock = threading.Lock()


def _build_pass(wan_dir: str, chain: int, log, sched_cls, visual_style, prompt_log_fn) -> _ap.WanPass:
    """Assemble the pass object the I2V/T2V stages render with.

    The render sizes and sampler defaults are read HERE, in a registered ``_SECTIONS``
    module, and travel on the pass object: the smoke scripts patch them on the
    ``wan_video_service`` package, and that patch is not forwarded to ``api_passes``.
    ``torch`` is left unset — the orchestrator fills it in once a pipeline has loaded.
    """
    return _ap.WanPass(
        wan_dir=wan_dir,
        log=log,
        chain=chain,
        frames=_CLIP_FRAMES,
        width=_WIDTH,
        height=_HEIGHT,
        steps_default=_INFER_STEPS,
        guidance_default=_GUIDANCE,
        motion_thresh=_MOTION_FREEZE_THRESH,
        sched_cls=sched_cls,
        visual_style=visual_style,
        prompt_log_fn=prompt_log_fn,
    )


# ── Public API ───────────────────────────────────────────────────────────────


def generate(
    flux_image_meta: list,
    out_dir: str,
    n_clips: int = _DEFAULT_N_CLIPS,
    log_fn=None,
    prompt_log_fn=None,
    flow_shift: float | None = None,
    visual_style: str | None = None,
    n_chained: int | None = None,
    frames: int | None = None,
    steps: int | None = None,
) -> list:
    """Generate *n_clips* video clips from the visual-framework metadata produced
    by Stage 3.5.

    ``frames``/``steps`` (optional) override per-sub-clip length and sampler steps —
    used by the ~5s single-scene test mode; ``None`` preserves normal behavior.

    Parameters
    ----------
    flux_image_meta : list[dict]
        Each entry must contain at minimum: ``prompt``, ``subject``, ``tag``,
        ``slot_seconds``, ``index``, ``path`` (FLUX image path), ``emotion``.
        Entries are expected to be pre-sorted by ``qa_score`` descending so the
        highest-quality images are preferred when the emotion priority is tied.
    out_dir : str
        Pipeline run output directory.  A ``wan_clips/`` sub-directory is created.
    n_clips : int
        Maximum number of clips to generate (default 2).
    log_fn : callable | None
        Optional ``log_fn(message: str)`` callback for status logging.
    prompt_log_fn : callable | None
        Optional ``prompt_log_fn(idx, prompt, meta)`` callback — called once
        per clip with the built Wan prompt and its source image metadata so
        the caller can persist it to prompt_log.json.
    flow_shift : float | None
        Scheduler flow-shift override.  Lower values (e.g. 2.0) reduce temporal
        motion aggressiveness which improves object/weapon persistence.
        ``None`` uses the scheduler's current default (3.0 for 480p).

    Returns
    -------
    list[dict]
        One entry per generated clip: ``{path, source_image, index,
        slot_seconds, subject, prompt}``.  Also writes ``wan_manifest.json``.
    """

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    if not flux_image_meta:
        _log('WAN: no FLUX image metadata — skipping video generation')
        return []

    wan_dir = os.path.join(out_dir, 'wan_clips')
    os.makedirs(wan_dir, exist_ok=True)
    _effective_chain = n_chained if n_chained is not None else _N_CHAINED

    # ── ComfyUI shortcut path ────────────────────────────────────────────────
    # When ZYG_USE_COMFYUI=1 and the server is reachable, dispatch the entire
    # I2V pass through ComfyUI's wan_i2v workflow. The advanced bells (per-clip
    # flow_shift, anti-drift anchor, motion-regen retry, T2V split) are NOT
    # replicated in the ComfyUI path yet — they will be added incrementally as
    # the workflows mature in the UI.
    if _comfy is not None and _comfy.is_enabled() and _comfy.server_reachable():
        _log('WAN: ZYG_USE_COMFYUI=1 → routing I2V through ComfyUI server')
        _chain_n = n_chained if n_chained is not None else _N_CHAINED
        comfy_results = _generate_via_comfyui(
            flux_image_meta,
            wan_dir,
            n_clips,
            _log,
            prompt_log_fn,
            visual_style,
            n_chained=_chain_n,
            frames=frames,
            steps=steps,
            flow_shift=flow_shift,
        )
        if comfy_results:
            manifest_path = os.path.join(wan_dir, 'wan_manifest.json')
            with open(manifest_path, 'w') as mf:
                json.dump(comfy_results, mf, indent=2)
            return comfy_results
        _log('WAN: ComfyUI path produced 0 clips — falling back to diffusers')

    candidates = _ap.pick_candidates(flux_image_meta, n_clips, _EMOTION_PRIORITY)
    _log(f'WAN: generating {len(candidates)} clip(s) — subjects: {[c.get("subject", "?") for c in candidates]}')

    results: list = []

    # Lazy-import scheduler class once (used for per-clip adaptive flow_shift)
    try:
        from diffusers import FlowMatchEulerDiscreteScheduler as _FMSched_g
    except ImportError:
        _FMSched_g = None

    _i2v_cands, _t2v_cands = _ap.split_scene_types(candidates)
    if _t2v_cands:
        _log(f'WAN: {len(_t2v_cands)} pure_action scene(s) → T2V pass; {len(_i2v_cands)} standard scene(s) → I2V pass')

    _pass = _build_pass(wan_dir, _effective_chain, _log, _FMSched_g, visual_style, prompt_log_fn)

    # ── Pass 1: I2V generation (all non-pure-action scenes) ─────────────────
    if _i2v_cands:
        try:
            with _pipe_lock:
                _load_pipe(_log)

            import torch

            _pass.torch = torch
            _ap.generate_i2v_clips(_i2v_cands, _pipe, _pass, results)
        except Exception as outer_err:
            _log(f'WAN I2V: generation failed — {outer_err}')
        finally:
            with _pipe_lock:
                _unload_pipe(_log)

    # ── Pass 2: T2V generation (pure_action scenes — maximum motion freedom) ─
    if _t2v_cands:
        try:
            with _t2v_pipe_lock:
                _load_t2v_pipe(_log)

            import torch

            _pass.torch = torch
            _ap.generate_t2v_clips(_t2v_cands, _t2v_pipe, _pass, results)
        except Exception as t2v_outer:
            _log(f'WAN T2V pass failed — {t2v_outer}')
        finally:
            with _t2v_pipe_lock:
                _unload_t2v_pipe(_log)

    if results:
        _ap.write_manifest(wan_dir, results, _log)

    return results


def _load_pipe(log_fn=None) -> None:
    """Load Wan2.1-I2V-14B-480P into VRAM (bfloat16, ~28 GB)."""
    global _pipe
    if _pipe is not None:
        return  # already loaded

    import torch
    from diffusers import WanImageToVideoPipeline

    def _log(msg):
        if log_fn:
            log_fn(msg)

    _log(f'WAN: loading {_MODEL_ID} (bfloat16) …')
    t0 = time.time()

    # Prefer the locally cached snapshot to avoid network calls (the HuggingFace Hub
    # sometimes returns 404 for old model IDs and requires a network round-trip even
    # when the model is fully downloaded).  Look for the snapshot directory directly in
    # the HuggingFace cache so from_pretrained() loads from disk without any HTTP request.
    _HF_CACHE = os.path.join(os.path.expanduser('~'), '.cache', 'huggingface', 'hub')
    _snap_root = os.path.join(
        _HF_CACHE,
        'models--' + _MODEL_ID.replace('/', '--'),
        'snapshots',
    )
    _local_model_path = _MODEL_ID  # fallback to Hub ID
    if os.path.isdir(_snap_root):
        _snaps = [
            os.path.join(_snap_root, s)
            for s in sorted(os.listdir(_snap_root))
            if os.path.isfile(os.path.join(_snap_root, s, 'model_index.json'))
        ]
        if _snaps:
            _local_model_path = _snaps[-1]  # most recent snapshot
            _log(f'WAN: using local cache at {_local_model_path}')

    _pipe = WanImageToVideoPipeline.from_pretrained(
        _local_model_path,
        torch_dtype=torch.bfloat16,
        local_files_only=(_local_model_path != _MODEL_ID),
    )
    _pipe = _pipe.to('cuda')
    # Tile the VAE to keep VRAM spikes manageable during video decode
    _pipe.vae.enable_tiling()
    if hasattr(_pipe.vae, 'enable_slicing'):
        _pipe.vae.enable_slicing()
    _log(f'WAN: model ready in {time.time() - t0:.0f}s')


def _unload_pipe(log_fn=None) -> None:
    """Move pipeline to CPU and free VRAM."""
    global _pipe
    import torch

    if _pipe is None:
        return
    try:
        _pipe.to('cpu')
    except Exception as _exc:
        _zyg_log.debug('i2v pipe stayed on the GPU, relying on the cache flush: %s', _exc)
    del _pipe
    _pipe = None
    gc.collect()
    torch.cuda.empty_cache()
    if log_fn:
        log_fn('WAN: VRAM freed')


def _load_t2v_pipe(log_fn=None) -> None:
    """Load the WAN T2V (text-to-video) pipeline into memory.

    Uses CPU offload because the T2V-14B model is ~75 GB and cannot fit
    in 24 GB VRAM without offloading.
    """
    global _t2v_pipe

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    if _t2v_pipe is not None:
        _log('WAN T2V: pipeline already loaded')
        return

    _log(f'WAN T2V: loading {_T2V_MODEL_ID} with CPU offload …')
    try:
        import torch
        from diffusers import WanPipeline

        _t2v_pipe = WanPipeline.from_pretrained(
            _T2V_MODEL_ID,
            torch_dtype=torch.bfloat16,
        )
        _t2v_pipe.enable_model_cpu_offload()
        _log('WAN T2V: pipeline loaded with CPU offload')
    except Exception as e:
        _log(f'WAN T2V: load failed — {e}')
        _t2v_pipe = None
        raise


def _unload_t2v_pipe(log_fn=None) -> None:
    """Unload the T2V pipeline and free VRAM."""
    global _t2v_pipe

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    if _t2v_pipe is None:
        return
    try:
        _t2v_pipe.to('cpu')
    except Exception as _exc:
        _zyg_log.debug('t2v pipe stayed on the GPU, relying on the cache flush: %s', _exc)
    del _t2v_pipe
    _t2v_pipe = None
    gc.collect()
    import torch

    torch.cuda.empty_cache()
    _log('WAN T2V: VRAM freed')
