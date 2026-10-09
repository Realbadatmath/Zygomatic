# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Infrastructure checks, the check table itself and the orchestration tail
(verbatim from bp_integrity_ops_steps.py)."""

from zyg_dashboard.bp_integrity_ops_steps.constants import (
    _RUNTIME_DIR,
    _cf_ig,
    _runtime_path,
    _zyg_log,
    exe,
    functools,
    json,
    os,
    subprocess,
)
from zyg_dashboard.bp_integrity_ops_steps.steps_gates import (
    _step_antelopev2_absent,
    _step_audiogen_absent,
    _step_bg_remove,
    _step_cinematic_lora,
    _step_cv2_pkg,
    _step_era_gate_chk,
    _step_flux_dev_absent,
    _step_hand_qc,
    _step_identity_qc,
    _step_ipadapter_weights,
    _step_licence_gate,
    _step_mediapipe_pkg,
    _step_object_tracking,
    _step_restoration_qc_chk,
    _step_sam3,
    _step_sam3d_body,
    _step_style_loras_absent,
    _step_typography_gate,
    _step_vlm_judge,
)
from zyg_dashboard.bp_integrity_ops_steps.steps_stack import (
    _step_ace_step,
    _step_anatomy_repair,
    _step_anthropic_api,
    _step_asr_whisper,
    _step_comfyui_server,
    _step_diarizer,
    _step_esrgan,
    _step_flux_schnell,
    _step_hand_fixer,
    _step_hw_cuda_driver,
    _step_hw_disk,
    _step_hw_ram,
    _step_hw_vram,
    _step_infra_audio_svc,
    _step_klein,
    _step_ollama_model_check,
    _step_ollama_service,
    _step_qwen_edit,
    _step_qwen_t2i,
    _step_rife,
    _step_sageattention,
    _step_sdxl,
    _step_tts_engines,
    _step_wan22,
    _step_wan_animate,
    _step_wan_i2v,
    _step_wan_vace,
)


# ── Infrastructure ───────────────────────────────────────────────────────────
def _step_infra_ffmpeg():
    try:
        _out = subprocess.check_output([exe('ffmpeg'), '-version'], stderr=subprocess.STDOUT, timeout=5).decode()
        _ver = _out.split('\n')[0].replace('ffmpeg version ', '').strip()
        return 'pass', f'ffmpeg {_ver}'
    except Exception as _e:
        return 'fail', str(_e)


def _step_infra_output_dir():
    try:
        _tp = _runtime_path('_ig_write_probe')
        os.makedirs(_tp, exist_ok=True)
        _tf = os.path.join(_tp, 'probe.tmp')
        with open(_tf, 'w') as _f:
            _f.write('ok')
        os.remove(_tf)
        os.rmdir(_tp)
        return 'pass', f'Output dir writable: {_RUNTIME_DIR}'
    except Exception as _e:
        return 'fail', str(_e)


def _step_llm_audit_chk():
    from zyg_workflows import llm_audit as _la

    if not _la._INSTALLED:
        return 'warn', 'Anthropic SDK not instrumented — claude-* calls are not being logged'
    return (
        'pass',
        f'Anthropic SDK instrumented — every messages.create appends to {_la._AUDIT_DIR}/<pipeline>.jsonl',
    )


# ── The check table ──────────────────────────────────────────────────────────
# 2026-09-11 rebuild: the check list follows the stack the pipelines actually
# run (ComfyUI families, Wan VACE/2.2/Animate, faster-whisper, SAM 3, the QC
# gates). Weights deleted on licence grounds sit in a "Licence tripwires" group
# where ABSENT is the passing state — before, four of the five warnings on this
# tab were those deletions reading as faults.
def build_tasks(gpu_busy, ollama_url):
    """Return [(category, name, used_by, zero-arg check fn)] in display order.

    A string in the table's fourth slot is an Ollama model tag, resolved here
    into a check closure exactly as the inline loop did.
    """
    tasks = [
        # Hardware
        ('Hardware', 'GPU VRAM', 'All GPU stages', functools.partial(_step_hw_vram, gpu_busy)),
        ('Hardware', 'System RAM', 'All stages', _step_hw_ram),
        ('Hardware', 'Disk space', 'Output / models', _step_hw_disk),
        ('Hardware', 'NVIDIA driver', 'CUDA', _step_hw_cuda_driver),
        # Core services
        ('Core services', 'ComfyUI server', 'All ComfyUI renders', _step_comfyui_server),
        ('Core services', 'Ollama service', 'Local LLM + vision', functools.partial(_step_ollama_service, ollama_url)),
        ('Core services', 'Anthropic API', 'claude-* call sites', _step_anthropic_api),
        # Local LLMs. qwen2.5:72b REMOVED 2026-08-26 (Qwen research licence,
        # non-commercial); llama3.2-vision REMOVED 2026-08-09 (EU exclusion);
        # deepseek-coder:33b dropped 2026-09-11 — still pulled, referenced by nothing.
        ('Local LLMs (Ollama)', 'qwen3.6:35b-a3b', 'Heavy LLM · narration, Zero', 'qwen3.6:35b-a3b'),
        ('Local LLMs (Ollama)', 'gpt-oss:20b', 'Light LLM · briefing, remix', 'gpt-oss:20b'),
        ('Local LLMs (Ollama)', 'qwen3.5:9b', 'Vision · hand QC, photo analysis', 'qwen3.5:9b'),
        ('Local LLMs (Ollama)', 'moondream:latest', 'Documentary VLM QC', 'moondream:latest'),
        ('Local LLMs (Ollama)', 'qwen2.5-coder:32b', 'Agent Zero · code', 'qwen2.5-coder:32b'),
        # Image generation
        ('Image generation', 'Qwen-Image-2512', 'Video stills · HandFixer base', _step_qwen_t2i),
        ('Image generation', 'Qwen-Image-Edit', 'Contact-sheet angle edits', _step_qwen_edit),
        ('Image generation', 'FLUX.2 klein 4B', 'Character LoRA render + train', _step_klein),
        ('Image generation', 'FLUX.1-schnell (in-process)', 'Documentary stills', _step_flux_schnell),
        ('Image generation', 'SDXL checkpoints', 'Character / story leg', _step_sdxl),
        ('Image generation', 'HandFixer (Qwen inpaint)', 'Hand repair post-pass', _step_hand_fixer),
        ('Image generation', 'Anatomy repair tiers', 'Documentary Stage 3.6', _step_anatomy_repair),
        ('Image generation', 'RealESRGAN x2 / x4plus', 'Upscale', _step_esrgan),
        # Video
        ('Video', 'Wan2.1 I2V 14B (ComfyUI)', 'Video Stage 4 · I2V', _step_wan_i2v),
        ('Video', 'Wan2.2 A14B + Lightning', 'I2V (env-gated)', _step_wan22),
        ('Video', 'Wan VACE 14B', 'Character / prop control', _step_wan_vace),
        ('Video', 'Wan2.2-Animate 14B', 'Driver-video engine', _step_wan_animate),
        ('Video', 'SageAttention', 'Wan attention kernel', _step_sageattention),
        ('Video', 'RIFE v4.6', 'Video Stage 4c · repair', _step_rife),
        # Voice & audio
        ('Voice & audio', 'IndexTTS-2 + Chatterbox', 'TTS (all pipelines)', _step_tts_engines),
        ('Voice & audio', 'ACE-Step 1.5', 'BGM · kids music', _step_ace_step),
        ('Voice & audio', 'audio_service', 'Foley library · BGM mix', _step_infra_audio_svc),
        ('Voice & audio', 'faster-whisper', 'Subtitles · transcripts', _step_asr_whisper),
        ('Voice & audio', 'Sortformer v2 diarizer', 'Speaker diarization', _step_diarizer),
        # Vision tools
        ('Vision tools', 'SAM 3', 'Prop-persistence sweep', _step_sam3),
        ('Vision tools', 'SAM 3D Body', 'Pose track · mesh fit', _step_sam3d_body),
        ('Vision tools', 'Object tracking (YOLOv8n)', 'Video Stage 4b', _step_object_tracking),
        ('Vision tools', 'Background removal (u2net)', 'Picture Studio', _step_bg_remove),
        ('Vision tools', 'MediaPipe', 'Hands · pose', _step_mediapipe_pkg),
        ('Vision tools', 'OpenCV (cv2)', 'Frame process', _step_cv2_pkg),
        # QC gates
        ('QC gates', 'Licence provenance', 'Graph weight lineage', _step_licence_gate),
        ('QC gates', 'VLM judge (Qwen3-VL)', 'Frame inspection', _step_vlm_judge),
        ('QC gates', 'Typography OCR', 'Documentary lettering', _step_typography_gate),
        ('QC gates', 'Era / anachronism', 'Documentary slots', _step_era_gate_chk),
        ('QC gates', 'Hand QC', 'Stills · HandFixer', _step_hand_qc),
        ('QC gates', 'Identity QC', 'Storyteller · sheets', _step_identity_qc),
        ('QC gates', 'Restoration QC', 'Upscale invention', _step_restoration_qc_chk),
        # Licence tripwires (pass = absent)
        ('Licence tripwires', 'FLUX.1-dev family', 'Must stay absent', _step_flux_dev_absent),
        ('Licence tripwires', 'XLabs IP-Adapter', 'Must stay absent', _step_ipadapter_weights),
        ('Licence tripwires', 'FLUX style LoRAs', 'Must stay absent', _step_style_loras_absent),
        ('Licence tripwires', 'Cinematic LoRA (FLUX-dev)', 'Off by policy', _step_cinematic_lora),
        ('Licence tripwires', 'antelopev2 face pack', 'Must stay absent', _step_antelopev2_absent),
        ('Licence tripwires', 'AudioGen / MusicGen foley', 'Must stay absent', _step_audiogen_absent),
        # Infrastructure
        ('Infrastructure', 'ffmpeg', 'All video stages', _step_infra_ffmpeg),
        ('Infrastructure', 'Output dir', 'All write stages', _step_infra_output_dir),
        ('Infrastructure', 'LLM audit log', 'claude-* call sites', _step_llm_audit_chk),
    ]
    resolved = []
    for cat, name, stage, fn_or_id in tasks:
        if isinstance(fn_or_id, str):
            resolved.append((cat, name, stage, _step_ollama_model_check(ollama_url, fn_or_id, stage)))
        else:
            resolved.append((cat, name, stage, fn_or_id))
    return resolved


def _chk(category, name, stage, fn):
    try:
        status, detail = fn()
    except Exception as _e:
        status, detail = 'warn', str(_e)[:120]
    return {
        'category': category,
        'name': name,
        'stage': stage,  # shown as "Used by"
        'status': status,  # 'pass' | 'warn' | 'fail'
        'passed': status == 'pass',
        'detail': detail,
    }


def run_checks(resolved):
    """Run every resolved check in a 16-thread pool (25 s wall budget)."""
    results = []
    with _cf_ig.ThreadPoolExecutor(max_workers=16) as _ex:
        _futs = {_ex.submit(_chk, cat, name, stage, fn): (cat, name) for cat, name, stage, fn in resolved}
        _cf_ig.wait(_futs, timeout=25)
        for _fut, _key in _futs.items():
            try:
                results.append(_fut.result())
            except Exception as _e:
                results.append(
                    {
                        'category': _key[0],
                        'name': _key[1],
                        'stage': '',
                        'status': 'warn',
                        'passed': False,
                        'detail': str(_e),
                    }
                )
    return results


def job_stats(workflow_jobs):
    """Live pipeline counters straight off the in-memory job table."""
    _statuses = [j.get('status') for j in workflow_jobs.values()]
    return {
        'running': sum(1 for s in _statuses if s == 'running'),
        'completed': sum(1 for s in _statuses if s == 'completed'),
        'failed': sum(1 for s in _statuses if s == 'failed'),
        'queued': sum(1 for s in _statuses if s == 'queued'),
        'total_in_memory': len(workflow_jobs),
    }


def circuit_breaker():
    """Return (state, last 15 alert lines) from integrity_alerts.log."""
    _alerts_path = _runtime_path('integrity_alerts.log')
    _recent_alerts = []
    _cb_state = 'ok'
    if os.path.isfile(_alerts_path):
        try:
            with open(_alerts_path, 'r', encoding='utf-8') as _af:
                _lines = _af.readlines()
            _recent_alerts = [l.rstrip() for l in _lines[-15:] if l.strip()]
            # Detect if circuit breaker has tripped (anomaly / auto-pause in last lines)
            _cb_state = (
                'tripped' if any('auto-pause' in l.lower() or 'anomaly' in l.lower() for l in _recent_alerts) else 'ok'
            )
        except (OSError, UnicodeDecodeError) as _exc:
            # A breaker that cannot be read is reported as 'ok' — the operator
            # has to know the verdict came from an unreadable log.
            _zyg_log.warning('integrity alerts log unreadable, reporting circuit breaker ok: %s', _exc)
    return _cb_state, _recent_alerts


def last_pipeline(recent_state_files):
    """Newest pipeline_*_state.json summarised for the "last pipeline" tile.

    `recent_state_files` is passed in because the helper is a lazy import in
    the blueprint (pipeline_common loads before it).
    """
    _last_pipeline = {}
    try:
        _pfiles = recent_state_files(_runtime_path('pipeline_*_state.json'), 1)
        if _pfiles:
            with open(_pfiles[0], 'r', encoding='utf-8') as _f:
                _lp = json.load(_f)
            _last_pipeline = {
                'pipeline_id': _lp.get('pipeline_id', '')[:12],
                'department': _lp.get('department', 'unknown'),
                'topic': _lp.get('scholarly_topic') or _lp.get('essay_title', ''),
                'status': 'failed' if _lp.get('error') else ('completed' if _lp.get('ended') else 'running'),
                'started': _lp.get('started', ''),
                'ended': _lp.get('ended', ''),
                'error': str(_lp.get('error', ''))[:120] if _lp.get('error') else '',
            }
    except Exception as _exc:
        # The tile goes blank. Kept broad on purpose: a state file with an
        # unexpected value type raises TypeError/AttributeError here too, and
        # the gate must still answer.
        _zyg_log.warning('last-pipeline state file unusable, tile left empty: %s', _exc)
    return _last_pipeline


def summary(results):
    """Return (overall, blocked_reason, pass, warn, fail) over the check results."""
    _n_fail = sum(1 for c in results if c['status'] == 'fail')
    _n_warn = sum(1 for c in results if c['status'] == 'warn')
    _n_pass = sum(1 for c in results if c['status'] == 'pass')
    _blocked_reason = None
    for _c in results:
        if _c['status'] == 'fail' and _c['category'] in ('Hardware',):
            _blocked_reason = f'{_c["name"]}: {_c["detail"][:80]}'
            break
    _overall = 'fail' if _n_fail > 0 else ('warn' if _n_warn > 0 else 'pass')
    return _overall, _blocked_reason, _n_pass, _n_warn, _n_fail
