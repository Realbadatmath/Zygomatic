# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Check functions for the generation stack: hardware, core services, image,
video, voice & audio (verbatim from bp_integrity_ops_steps.py)."""

from zyg_dashboard.bp_integrity_ops_steps.constants import (
    _COMFY_MODELS,
    _COMFY_ROOT,
    _GPU_HOLDER_LABELS,
    _SDXL_CHECKPOINTS,
    _comfy_files,
    _env_on,
    _first_model,
    _g,
    _gpu_work_active,
    _hf_weight_files,
    _qwen_t2i_unet,
    _shu_ig,
    _zyg_log,
    exe,
    json,
    os,
    paths,
    re,
    subprocess,
)


# ══ CHECK FUNCTIONS ══════════════════════════════════════════════════════════


# ── Hardware ─────────────────────────────────────────────────────────────────
def _step_hw_vram(gpu_busy):
    # Whole-GPU numbers from nvidia-smi. This read torch.cuda.memory_reserved()
    # for the GUI process alone, which cannot see VRAM held by ComfyUI,
    # Ollama or the TTS / VLM worker processes.
    try:
        _row = (
            subprocess.check_output(
                [
                    exe('nvidia-smi'),
                    '--query-gpu=name,memory.total,memory.used,memory.free',
                    '--format=csv,noheader,nounits',
                ],
                timeout=5,
            )
            .decode()
            .strip()
            .splitlines()[0]
        )
        _name, _tot, _used, _free = [x.strip() for x in _row.split(',')]
        _total, _used_gb, _free_gb = int(_tot) / 1024, int(_used) / 1024, int(_free) / 1024
    except Exception as _e:
        return 'warn', f'nvidia-smi unavailable: {_e}'
    _detail = (
        f'{_name} | {_free_gb:.1f} GB free / {_total:.0f} GB total ({_used_gb / _total * 100:.0f}% used, all processes)'
    )
    try:
        _apps = (
            subprocess.check_output(
                [exe('nvidia-smi'), '--query-compute-apps=used_memory,process_name', '--format=csv,noheader,nounits'],
                timeout=5,
            )
            .decode()
            .strip()
            .splitlines()
        )
        _holders = []
        for _a in _apps:
            _mb, _proc = [x.strip() for x in _a.split(',', 1)]
            _low = _proc.lower()
            _label = next((_lbl for _sub, _lbl in _GPU_HOLDER_LABELS if _sub in _low), os.path.basename(_proc))
            _holders.append((int(_mb), _label))
        _holders.sort(reverse=True)
        if _holders:
            _detail += ' | held by: ' + ', '.join(f'{l} {mb / 1024:.1f} GB' for mb, l in _holders[:4])
    except Exception as _exc:
        # Cosmetic suffix only — the free/total verdict below does not need it.
        _zyg_log.debug('gpu holder breakdown unavailable: %s', _exc)
    if _free_gb > 8.0:
        return 'pass', _detail
    try:
        _busy = gpu_busy or _gpu_work_active()
    except Exception:
        _busy = gpu_busy
    if _busy:
        return 'pass', _detail + ' | GPU job running (expected)'
    return 'warn', _detail + ' | no GPU job running — resident models are holding the card'


def _step_hw_ram():
    try:
        with open('/proc/meminfo') as _mf:
            _lines = {l.split(':')[0]: l.split(':')[1].strip() for l in _mf if ':' in l}
        _total_kb = int(_lines.get('MemTotal', '0 kB').split()[0])
        _avail_kb = int(_lines.get('MemAvailable', '0 kB').split()[0])
        _buf_kb = int(_lines.get('Buffers', '0 kB').split()[0])
        _cache_kb = int(_lines.get('Cached', '0 kB').split()[0])
        _total_gb = _total_kb / 1024**2
        _avail_gb = _avail_kb / 1024**2
        _used_pct = (1 - _avail_kb / _total_kb) * 100
        _st = 'pass' if _avail_gb > 12.0 else ('warn' if _avail_gb > 4.0 else 'fail')
        return _st, (
            f'{_avail_gb:.1f} GB available / {_total_gb:.0f} GB total '
            f'({_used_pct:.0f}% used) | buffers+cache: {(_buf_kb + _cache_kb) / 1024**2:.1f} GB'
        )
    except Exception as _e:
        return 'warn', str(_e)


def _step_hw_disk():
    try:
        _disk = _shu_ig.disk_usage(str(paths.ZYG_HOME))
        _free = _disk.free / 1024**3
        _total = _disk.total / 1024**3
        _used_pct = _disk.used / _disk.total * 100
        _st = 'pass' if _free > 150 else ('warn' if _free > 50 else 'fail')
        return _st, f'{_free:.0f} GB free / {_total:.0f} GB total ({_used_pct:.0f}% used) on the home partition'
    except Exception as _e:
        return 'warn', str(_e)


def _step_hw_cuda_driver():
    try:
        _out = (
            subprocess.check_output(
                [
                    exe('nvidia-smi'),
                    '--query-gpu=name,driver_version,memory.total,memory.free',
                    '--format=csv,noheader',
                ],
                timeout=5,
            )
            .decode()
            .strip()
        )
        return 'pass', _out
    except Exception as _e:
        return 'warn', f'nvidia-smi not available: {_e}'


# ── Core services ────────────────────────────────────────────────────────────
def _step_comfyui_server():
    from zyg_workflows import _comfy_client as _cc
    from zyg_workflows.net import safe_urlopen

    try:
        _stats = json.loads(safe_urlopen(_cc._url('/system_stats'), timeout=3).read())
        _queue = json.loads(safe_urlopen(_cc._url('/queue'), timeout=3).read())
    except Exception as _e:
        return 'fail', (
            f'not reachable on :{_cc.COMFY_PORT} ({_e}) — Qwen, klein, SDXL, Wan, '
            f'ACE-Step and HandFixer all render through it'
        )
    _ver = (_stats.get('system') or {}).get('comfyui_version', '?')
    _detail = (
        f'ComfyUI {_ver} on :{_cc.COMFY_PORT} | queue: '
        f'{len(_queue.get("queue_running") or [])} running, '
        f'{len(_queue.get("queue_pending") or [])} pending'
    )
    if not _cc.is_enabled():
        return 'warn', _detail + ' | ZYG_USE_COMFYUI is off — callers take their diffusers fallbacks'
    # Ownership, not `systemctl is-active`: seen 2026-09-11, a ComfyUI started
    # from a login session held :8188 for days. crewai-gui.service Wants=
    # comfyui.service, so each GUI restart sends the unit through four starts
    # that die on "Port 8188 is already in use" — is-active flickers 'active'
    # mid-loop and would read that as healthy.
    try:
        _m = re.search(
            r'pid=(\d+)',
            subprocess.run(
                [exe('ss'), '-ltnpH', f'sport = :{_cc.COMFY_PORT}'], capture_output=True, text=True, timeout=3
            ).stdout,
        )
        _pid = int(_m.group(1)) if _m else None
        with open(f'/proc/{_pid}/cgroup') as _fh:
            _cgroup = _fh.read()
    except Exception:
        return 'pass', _detail + ' | listener pid not visible — systemd ownership unchecked'
    if 'comfyui.service' in _cgroup:
        return 'pass', _detail + f' | pid {_pid} under comfyui.service'
    try:
        _state = (
            '/'.join(
                subprocess.run(
                    [
                        exe('systemctl'),
                        'show',
                        'comfyui.service',
                        '-p',
                        'ActiveState',
                        '-p',
                        'SubState',
                        '--value',
                    ],
                    capture_output=True,
                    text=True,
                    timeout=3,
                ).stdout.split()
            )
            or 'unknown'
        )
    except Exception:
        _state = 'unknown'
    return 'warn', (
        _detail + f' | pid {_pid} runs OUTSIDE comfyui.service (unit {_state}): systemctl '
        f'cannot stop or restart it, and each crewai-gui restart sends the unit '
        f'through failing starts against the held port'
    )


def _step_ollama_service(ollama_url):
    try:
        from zyg_workflows.net import safe_urlopen

        _resp = safe_urlopen(ollama_url + '/api/tags', timeout=4)
        _d = json.loads(_resp.read())
        _models = _d.get('models', [])
        _names = [m.get('name', '') for m in _models]
        return 'pass', f'Reachable at {ollama_url} — {len(_models)} models: {", ".join(_names)}'
    except Exception as _e:
        return 'fail', f'Not reachable: {_e}'


def _step_ollama_model_check(ollama_url, model_id, role):
    def _fn():
        try:
            from zyg_workflows.net import safe_urlopen

            _resp = safe_urlopen(ollama_url + '/api/tags', timeout=4)
            _d = json.loads(_resp.read())
            _models = {m.get('name', '') for m in _d.get('models', [])}
            _exact = model_id in _models
            _partial = any(model_id.split(':')[0] in m for m in _models)
            if _exact:
                _info = next((m for m in _d.get('models', []) if m.get('name') == model_id), {})
                _size = _info.get('size', 0)
                _size_str = f'{_size / 1024**3:.1f} GB' if _size else ''
                return 'pass', f'Available {_size_str} | {role}'
            if _partial:
                return 'warn', f'Partial match only (exact tag "{model_id}" not found) | {role}'
            return 'warn', f'Not pulled — run: ollama pull {model_id} | {role}'
        except Exception as _e:
            return 'warn', f'Could not check: {_e}'

    return _fn


def _step_anthropic_api():
    # Replaces a live messages.create ping that billed a Sonnet call on every
    # 20 s refresh of this tab. The models endpoint is not billed: it proves
    # the key and model access, but it cannot see the credit balance.
    _ak = os.environ.get('ANTHROPIC_API_KEY', '')
    if not _ak:
        return 'fail', 'ANTHROPIC_API_KEY not set — every claude-* call site will fail'
    try:
        import anthropic as _ant

        _ids = [m.id for m in _ant.Anthropic(api_key=_ak, timeout=8.0, max_retries=0).models.list(limit=100)]
    except Exception as _e:
        return 'fail', f'models endpoint refused the key: {str(_e)[:120]}'
    _want = ('claude-sonnet-4-6', 'claude-haiku-4-5')
    _missing = [w for w in _want if not any(i.startswith(w) for i in _ids)]
    if _missing:
        return 'warn', f'key valid, but not listed for this key: {", ".join(_missing)}'
    return 'pass', (
        f'key valid | {" + ".join(_want)} available | unbilled models check — credit balance is not visible from here'
    )


# ── Image generation ─────────────────────────────────────────────────────────
def _step_qwen_t2i():
    _unet = _qwen_t2i_unet()
    if not _unet:
        return 'fail', 'Qwen-Image-2512 UNet missing — video anchor stills and HandFixer have no base'
    _miss, _gb = _comfy_files(
        [
            ('diffusion_models', _unet),
            ('text_encoders', 'qwen_2.5_vl_7b_fp8_scaled.safetensors'),
            ('vae', 'qwen_image_vae.safetensors'),
        ]
    )
    if _miss:
        return 'fail', f'{_unet} present but graph inputs missing: {", ".join(_miss)}'
    _fam = os.environ.get('ZYG_VIDEO_STILL_FAMILY', 'qwen').strip().lower() or 'qwen'
    return 'pass', (
        f'{_unet} + Qwen2.5-VL-7B encoder + VAE ({_gb:.0f} GB) | Apache-2.0 | video anchor-still family: {_fam}'
    )


def _step_qwen_edit():
    _dm = os.path.join(_COMFY_MODELS, 'diffusion_models')
    _on_disk = sorted(f for f in os.listdir(_dm) if f.startswith('qwen_image_edit_')) if os.path.isdir(_dm) else []
    _unet = _first_model(
        'diffusion_models',
        'ZYG_QWEN_EDIT_UNET',
        ['qwen_image_edit_2509_bf16.safetensors', 'qwen_image_edit_2509_fp8_e4m3fn.safetensors'],
    )
    if not _unet:
        return 'fail', f'no Qwen-Image-Edit UNet resolvable (on disk: {", ".join(_on_disk) or "none"})'
    _lora = os.environ.get('ZYG_QWEN_EDIT_ANGLES_LORA', '').strip() or 'qwen_edit_2509_multiple_angles.safetensors'
    _lora_ok = os.path.isfile(os.path.join(_COMFY_MODELS, 'loras', _lora))
    _gb = os.path.getsize(os.path.join(_dm, _unet)) / 1024**3
    _detail = f'{_unet} ({_gb:.0f} GB) | angle LoRA: {_lora}{"" if _lora_ok else " MISSING"} | Apache-2.0'
    _idle = [f for f in _on_disk if f != _unet]
    if _idle:
        _detail += f' | on disk, not selected: {", ".join(_idle)} (ZYG_QWEN_EDIT_UNET)'
    return ('pass' if _lora_ok else 'warn'), _detail


def _step_klein():
    _order = ['flux-2-klein-base-4b.safetensors', 'flux-2-klein-4b.safetensors']
    if _env_on('ZYG_KLEIN_DISTILLED', '0'):
        _order.reverse()
    _unet = _first_model('diffusion_models', 'ZYG_KLEIN_T2I_UNET', _order)
    _te = _first_model('text_encoders', 'ZYG_KLEIN_CLIP', ['qwen_3_4b.safetensors'])
    _vae = _first_model('vae', 'ZYG_KLEIN_VAE', ['flux2-vae.safetensors'])
    _missing = [n for n, v in (('UNet', _unet), ('Qwen3-4B encoder', _te), ('FLUX.2 VAE', _vae)) if not v]
    if _missing:
        return 'fail', f'FLUX.2 klein 4B incomplete — missing {", ".join(_missing)}'
    _n_lora = len(_g.glob(os.path.join(_COMFY_MODELS, 'loras', '*_klein.safetensors')))
    return 'pass', (
        f'{_unet} ({"base, undistilled" if "base" in _unet.lower() else "distilled"}) '
        f'+ {_te} + {_vae} | {_n_lora} character LoRAs staged | Apache-2.0 (4B only)'
    )


def _step_flux_schnell():
    _p = os.path.join(str(paths.ZYG_FLUX_ROOT), 'flux1-schnell')
    if not os.path.isdir(_p):
        return 'fail', f'Not found at {_p} — documentary stills cannot render'
    try:
        import diffusers as _df

        _dver = f'diffusers {_df.__version__}'
    except Exception as _e:
        return 'fail', f'diffusers not importable ({_e}) — in-process schnell cannot load'
    _files = set(_g.glob(os.path.join(_p, '**', '*.safetensors'), recursive=True))
    _sz = sum(os.path.getsize(f) for f in _files if os.path.isfile(f)) / 1024**3
    _persist = ', persistent worker' if _env_on('ZYG_SCHOLARLY_FLUX_PERSISTENT') else ''
    return 'pass', (
        f'{len(_files)} safetensors, {_sz:.0f} GB | in-process via {_dver}{_persist} | '
        f'Apache-2.0 (not affected by the FLUX.1-dev pause)'
    )


def _step_sdxl():
    from zyg_workflows import licence_provenance as _lp

    _ck = os.path.join(_COMFY_MODELS, 'checkpoints')
    _reg = _lp.load_registry()
    _parts, _uncleared = [], 0
    for _n in _SDXL_CHECKPOINTS:
        if not os.path.isfile(os.path.join(_ck, _n)):
            continue
        _st = _lp.classify_weight(_n, registry=_reg).get('status', 'unknown')
        _uncleared += _st != 'cleared'
        _parts.append(f'{_n[: -len(".safetensors")]} [{_st}]')
    if not _parts:
        return 'fail', 'no SDXL checkpoints in checkpoints/ — the character / story SDXL leg cannot render'
    _detail = ' | '.join(_parts)
    if _uncleared:
        _detail += f' — {_uncleared} not cleared for commercial use (open question in model_licences.json)'
    return 'pass', _detail


def _step_hand_fixer():
    _engine = os.environ.get('ZYG_HAND_FIXER_ENGINE', 'qwen').strip().lower()
    if _engine == 'flux':
        return 'warn', (
            'ZYG_HAND_FIXER_ENGINE=flux — the FLUX.1-Fill-dev leg is non-commercial, '
            'deleted, and refused while FLUX renders are paused'
        )
    if not (
        _qwen_t2i_unet()
        and os.path.isfile(
            os.path.join(_COMFY_MODELS, 'controlnet', 'Qwen-Image-InstantX-ControlNet-Inpainting.safetensors')
        )
    ):
        return (
            'warn',
            'InstantX Qwen inpaint ControlNet or Qwen-2512 base missing — HandFixer degrades to TELEA / HandDetailer',
        )
    return (
        'pass',
        'InstantX Qwen-Image ControlNet-Inpainting on Qwen-Image-2512 | graph hand_fixer_qwen_inpaint | Apache-2.0',
    )


def _step_anatomy_repair():
    from zyg_workflows import flux_fill_service as _ffs

    _tiers = _ffs.available_tiers(use_flux_fill=False)
    if not _tiers:
        return 'fail', 'no licence-clean repair tier can run (ComfyUI Qwen inpaint, cv2 TELEA)'
    _detail = 'tiers: ' + ' → '.join(_tiers) + ' | FLUX.1-Fill-dev excluded (non-commercial)'
    if 'qwen_inpaint_comfy' not in _tiers:
        return 'warn', _detail + ' | Qwen inpaint unavailable — cv2 TELEA only'
    return 'pass', _detail


def _step_esrgan():
    _file_paths = (
        ('x2', os.path.join(_COMFY_MODELS, 'upscale_models', 'RealESRGAN_x2.pth')),
        ('x4plus', os.path.join(str(paths.ZYG_REALESRGAN_ROOT), 'RealESRGAN_x4plus.pth')),
    )
    _missing = [n for n, p in _file_paths if not os.path.isfile(p)]
    _detail = (
        'x2 via ComfyUI (contact sheets; restoration QC calibrated on it) + x4plus (video pipeline) | BSD-3-Clause'
    )
    if _missing:
        return 'warn', f'missing RealESRGAN {", ".join(_missing)} | ' + _detail
    return 'pass', _detail


# ── Video ────────────────────────────────────────────────────────────────────
def _step_wan_i2v():
    _unet = os.environ.get('ZYG_WAN_MODEL', 'Wan2_1-I2V-14B-480P_fp8_e4m3fn.safetensors')
    _miss, _gb = _comfy_files(
        [
            ('diffusion_models', _unet),
            ('text_encoders', 'umt5-xxl-enc-bf16.safetensors'),
            ('clip_vision', 'open-clip-xlm-roberta-large-vit-huge-14_visual_fp32.safetensors'),
            ('vae', 'Wan2_1_VAE_bf16.safetensors'),
        ]
    )
    if _miss:
        return 'fail', f'wan_i2v graph inputs missing: {", ".join(_miss)}'
    _detail = (
        f'{_unet} + umT5-XXL + CLIP-H + VAE ({_gb:.0f} GB) via ComfyUI | Apache-2.0 | '
        f'attention: {os.environ.get("ZYG_WAN_ATTENTION", "") or "default"}'
    )
    if not _hf_weight_files('models--Wan-AI--Wan2.1-I2V-14B-480P-Diffusers'):
        _detail += ' | diffusers fallback not cached (a ComfyUI failure falls back to a ~30 GB download)'
    if not _env_on('ZYG_USE_COMFYUI'):
        return 'warn', 'ZYG_USE_COMFYUI is off — I2V takes the diffusers path | ' + _detail
    return 'pass', _detail


def _step_wan22():
    _miss, _gb = _comfy_files(
        [
            ('diffusion_models', 'Wan2_2-I2V-A14B-HIGH_fp8_e4m3fn_scaled_KJ.safetensors'),
            ('diffusion_models', 'Wan2_2-I2V-A14B-LOW_fp8_e4m3fn_scaled_KJ.safetensors'),
            ('loras', 'wan_lightning/Wan2.2-Lightning_I2V-A14B-4steps-lora_HIGH_fp16.safetensors'),
            ('loras', 'wan_lightning/Wan2.2-Lightning_I2V-A14B-4steps-lora_LOW_fp16.safetensors'),
        ]
    )
    _on22, _onl = _env_on('ZYG_WAN22'), _env_on('ZYG_WAN_LIGHTNING')
    _state = f'ZYG_WAN22 {"ON" if _on22 else "off"}, ZYG_WAN_LIGHTNING {"ON" if _onl else "off"}'
    if _miss:
        return ('fail' if (_on22 or _onl) else 'warn'), f'missing {", ".join(_miss)} | {_state}'
    return 'pass', f'A14B HIGH + LOW experts + Lightning 4-step LoRAs ({_gb:.0f} GB) | {_state} | Apache-2.0'


def _step_wan_vace():
    _t2v = os.environ.get('ZYG_WAN_T2V_MODEL', 'Wan2_1-T2V-14B_fp8_e4m3fn.safetensors')
    _mod = os.environ.get('ZYG_WAN_VACE_MODULE', 'Wan2_1-VACE_module_14B_fp8_e4m3fn.safetensors')
    _miss, _gb = _comfy_files(
        [
            ('diffusion_models', _t2v),
            ('diffusion_models', _mod),
            ('text_encoders', 'umt5-xxl-enc-bf16.safetensors'),
            ('vae', 'Wan2_1_VAE_bf16.safetensors'),
        ]
    )
    if _miss:
        return 'fail', f'VACE graph inputs missing: {", ".join(_miss)}'
    _n = {
        d: len(_g.glob(os.path.join(_COMFY_MODELS, 'loras', d, '*.safetensors')))
        for d in ('wan_chars', 'wan_props', 'wan_antireal')
    }
    return 'pass', (
        f'{_t2v} + {_mod} ({_gb:.0f} GB) | LoRAs: {_n["wan_chars"]} character, '
        f'{_n["wan_props"]} prop, {_n["wan_antireal"]} anti-real | Apache-2.0'
    )


def _step_wan_animate():
    _miss, _gb = _comfy_files(
        [
            ('diffusion_models', 'Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2.safetensors'),
            ('text_encoders', 'umt5_xxl_fp8_e4m3fn_scaled.safetensors'),
            ('vae', 'wan_2.1_vae.safetensors'),
            ('clip_vision', 'clip_vision_h.safetensors'),
        ]
    )
    if _miss:
        return 'warn', f'wan22_animate graph inputs missing: {", ".join(_miss)}'
    return 'pass', f'Wan2.2-Animate-14B fp8 + native umT5 / VAE / CLIP-H ({_gb:.0f} GB) | Apache-2.0'


def _step_sageattention():
    _mode = os.environ.get('ZYG_WAN_ATTENTION', '').strip()
    _dist = _g.glob(os.path.join(_COMFY_ROOT, '.venv', 'lib', 'python3*', 'site-packages', 'sageattention-*.dist-info'))
    if not _dist:
        return (
            ('fail' if _mode == 'sageattn' else 'warn'),
            f'sageattention not installed in the ComfyUI venv | ZYG_WAN_ATTENTION={_mode or "unset"}',
        )
    _ver = os.path.basename(_dist[0])[len('sageattention-') : -len('.dist-info')]
    return 'pass', f'sageattention {_ver} (triton) in the ComfyUI venv | ZYG_WAN_ATTENTION={_mode or "unset"}'


def _step_rife():
    from zyg_workflows import rife_service as _rs

    _missing = [p for p in (_rs._RIFE_BINARY, _rs._RIFE_MODEL_DIR) if not os.path.exists(p)]
    if _missing:
        return 'warn', f'missing {", ".join(_missing)} — temporal repair skipped'
    return 'pass', f'rife-ncnn-vulkan + {os.path.basename(_rs._RIFE_MODEL_DIR)} | 2× interpolation / frame repair'


# ── Voice & audio ────────────────────────────────────────────────────────────
def _step_tts_engines():
    """IndexTTS-2 (primary) + Chatterbox (fallback) + voice seed pool.

    Both engines run in their own venvs behind subprocess workers, so this
    checks files on disk — importing them here would drag two torch stacks
    into the GUI process.
    """
    try:
        from zyg_workflows import tts_service as _ts
    except Exception as _e:
        return 'fail', f'tts_service not importable: {_e}'
    _idx = os.path.isfile(_ts._INDEXTTS_PY) and os.path.isfile(_ts._INDEXTTS_WORKER)
    _cbx = os.path.isfile(_ts._CHATTERBOX_PY) and os.path.isfile(_ts._CHATTERBOX_WORKER)
    _seeds = len(_ts._seed_pool())
    if not _seeds:
        return 'fail', (
            f'no voice seeds in {_ts._SEED_POOL_DIR} — both engines are '
            f'cloners and cannot synthesize without a reference wav'
        )
    if not _idx and not _cbx:
        return 'fail', 'neither IndexTTS-2 nor Chatterbox worker/venv found'
    if not _idx:
        return 'warn', f'IndexTTS-2 missing — running on the Chatterbox fallback ({_seeds} seeds)'
    if not _cbx:
        return 'warn', f'Chatterbox fallback missing — IndexTTS-2 has no safety net ({_seeds} seeds)'
    return 'pass', f'IndexTTS-2 + Chatterbox workers present, {_seeds} seed voices'


def _step_ace_step():
    # Music engine is ACE-Step 1.5 (MIT) since 2026-08-09 — MusicGen
    # (CC-BY-NC weights) retired from the shipping path.
    from zyg_workflows import ace_step_service as _ace

    if _ace.is_available():
        return 'pass', f'{_ace.model_id()} via ComfyUI native nodes | MIT'
    _ckpt = os.path.join(_COMFY_MODELS, 'checkpoints', _ace.CHECKPOINT)
    if not os.path.isfile(_ckpt):
        return 'warn', f'ACE-Step checkpoint missing: {_ckpt}'
    return 'warn', 'ACE-Step checkpoint present but ComfyUI server unreachable'


def _step_infra_audio_svc():
    try:
        from zyg_workflows import audio_service as _asvc

        _has = lambda a: hasattr(_asvc, a)
        _parts = []
        if _has('mix_foley_into_audio'):
            _parts.append('foley SFX')
        if _has('mix_bgm_into_video'):
            _parts.append('BGM mix')
        if _has('get_music_for_topic'):
            _parts.append('Claude mood override')
        return 'pass', 'audio_service ready — ' + ', '.join(_parts or ['loaded'])
    except Exception as _e:
        return 'warn', str(_e)


def _step_asr_whisper():
    import importlib.util as _ilu

    _model = os.environ.get('ZYG_WHISPER_MODEL', 'large-v3').strip() or 'large-v3'
    if _ilu.find_spec('faster_whisper') is None:
        return 'fail', 'faster_whisper not installed in the GUI venv — subtitles and transcripts fail'
    if not _hf_weight_files(f'models--Systran--faster-whisper-{_model}'):
        return 'warn', f'faster-whisper {_model} not cached — the first transcription downloads it'
    return 'pass', f'faster-whisper {_model} cached | VAD, VRAM-aware CUDA/CPU via zyg_whisper | MIT'


def _step_diarizer():
    _p = os.environ.get('ZYG_SORTFORMER_MODEL', '').strip()
    if not _p:
        return 'warn', 'ZYG_SORTFORMER_MODEL not set — diarize_sortformer has no pinned .nemo'
    if not os.path.isfile(_p):
        return 'fail', f'pinned diarizer missing: {_p}'
    return 'pass', (
        f'{os.path.basename(_p)} ({os.path.getsize(_p) / 1024**2:.0f} MB) | '
        f'streaming 4-speaker diarizer | CC-BY-4.0 (attribution)'
    )
