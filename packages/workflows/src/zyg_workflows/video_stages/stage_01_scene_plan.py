# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 0/1 of the video pipeline: VRAM startup sweep and scene planning.

Lines 154-465 of `pipeline_video._run_video_pipeline` at 770c30a: the
manga/standard startup branch (the nvidia-smi evict sweep, the ComfyUI
exemption, the pre-pipeline VRAM report) and then Stage 1 — the Claude call
that writes the scene list, the narration sentences and the music mood, the
`_resolve_video_timing` arithmetic, and the env-gated Scene-DSL snapshot.

The one 330-line function those lines made is now an orchestrator over the
helpers below: the sweep, the timing, the two prompt builders, the reply
parser, the fallback scene list and the DSL snapshot. Same order, same log
lines, same `ctx` writes; the prompt text and the parser are now reachable
from a test without a GPU or an API key.
"""

import json
import os

from zyg_workflows.bin import exe
from zyg_workflows.pipeline_common import _resolve_video_timing
from zyg_workflows.pipeline_config import _caveman_kw, _dsl, _STYLE_LORA_CONFIG
from zyg_workflows.runtime import _record_token_usage
from zyg_workflows.stage_runner import _log_prompt
from zyg_workflows.vram_manager import _ensure_comfy_offload_env, _release_pipeline_vram

import logging as _zyg_logging

# The monolith's channel, so a run's log lines keep one name across the split.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_video')


def _parse_compute_apps(stdout):
    """`[(pid, mib)]` from `nvidia-smi --query-compute-apps` CSV; unparseable rows are dropped."""
    apps = []
    for _pline in stdout.strip().splitlines():
        _pp = [x.strip() for x in _pline.split(',')]
        if len(_pp) != 2:
            continue
        try:
            apps.append((int(_pp[0]), int(_pp[1])))
        except ValueError as _exc:
            _zyg_log.debug('unparseable nvidia-smi app line skipped: %s', _exc)
            continue
    return apps


def _comfy_server_pid(_sp_pre):
    """The ComfyUI server's PID when ZYG_USE_COMFYUI is on, else None.

    With the flag on, that server is intentionally holding VRAM for our HTTP
    submits, so the evict sweep must leave it alone. A failing probe is not
    fatal: the sweep then simply has no exemption.
    """
    if os.environ.get('ZYG_USE_COMFYUI', '').strip().lower() not in ('1', 'true', 'yes', 'on'):
        return None
    try:
        _pgrep = _sp_pre.run(
            ['pgrep', '-f', 'ai-models/comfyui/.venv/bin/python main.py'],
            capture_output=True,
            timeout=5,
            text=True,
        )
        _pids = [int(x) for x in _pgrep.stdout.split() if x.strip().isdigit()]
        if _pids:
            return _pids[0]
    except Exception as _exc:
        _zyg_log.warning('comfy PID probe failed, the VRAM sweep has no exemption: %s', _exc)
    return None


def _evict_pid(_log, _ppid, _pmb):
    """SIGTERM then, if it is still there, SIGKILL one competing VRAM process."""
    try:
        os.kill(_ppid, 15)
        import time as _t_pre

        _t_pre.sleep(2)
        try:
            os.kill(_ppid, 0)
            os.kill(_ppid, 9)
            _t_pre.sleep(1)
        except ProcessLookupError as _exc:
            _zyg_log.debug('PID %s already gone after SIGTERM: %s', _ppid, _exc)
        _log('INFO', 'Stage 0', f'Evicted PID {_ppid} — freed ~{_pmb} MiB VRAM')
    except (ProcessLookupError, PermissionError) as _pe:
        _log('WARNING', 'Stage 0', f'Could not evict PID {_ppid}: {_pe}')


def _evict_competing_vram_users(_log):
    """Ask nvidia-smi who holds VRAM and evict every one of them but us and ComfyUI."""
    import subprocess as _sp_pre

    _own_pid_pre = os.getpid()
    _apps_pre = _sp_pre.run(
        [exe('nvidia-smi'), '--query-compute-apps=pid,used_memory', '--format=csv,noheader,nounits'],
        capture_output=True,
        timeout=10,
        text=True,
    )
    _comfy_exempt_pid = _comfy_server_pid(_sp_pre)
    for _ppid, _pmb in _parse_compute_apps(_apps_pre.stdout):
        if _ppid == _own_pid_pre:
            continue
        if _ppid == _comfy_exempt_pid:
            _log(
                'INFO',
                'Stage 0',
                f'Pre-pipeline: keeping ComfyUI server PID {_ppid} ({_pmb} MiB) — needed for ZYG_USE_COMFYUI',
            )
            continue
        _log('WARNING', 'Stage 0', f'Pre-pipeline: evicting competing VRAM process PID {_ppid} ({_pmb} MiB)')
        _evict_pid(_log, _ppid, _pmb)


def _report_free_vram(_log):
    """Log how much VRAM is free before Stage 2; silent when torch cannot say."""
    try:
        import torch as _t_pre_flush

        _vfree_pre = _t_pre_flush.cuda.mem_get_info()[0] / 1024**3
        _log('INFO', 'Stage 0', f'Pre-pipeline VRAM: {_vfree_pre:.1f} GB free before Stage 2')
    except Exception as _exc:
        _zyg_log.debug('pre-pipeline VRAM report unavailable: %s', _exc)


def _startup_vram_sweep(_log, _manga_mode):
    """Stage 0: evict competing VRAM users before any AI model loads.

    Manga skips the aggressive sweep — FLUX panels only, no WAN; avoids
    disturbing ComfyUI. A failing scan is a warning, never a stop.
    """
    if _manga_mode:
        _log('INFO', 'Stage 0', 'Manga mode: light startup (no VRAM evict / no /free sweep)')
        _ensure_comfy_offload_env()
        return
    try:
        _evict_competing_vram_users(_log)
    except Exception as _pre_e:
        _log('WARNING', 'Stage 0', f'Pre-pipeline VRAM scan failed: {_pre_e}')

    _ensure_comfy_offload_env()
    _release_pipeline_vram('Stage 0', lambda m: _log('INFO', 'Stage 0', m))
    _report_free_vram(_log)


def _plan_video_timing(_log, job, video_duration_minutes, scene_mode):
    """Resolve the scene count and length, record them on the job, log the WAN chaining.

    Returns `(n_scenes, scene_duration, target_total_sec, scene_mode)`. A
    single-scene video cannot be chained from a previous clip, so its
    `scene_mode` comes back as 'independent'.
    """
    _vt = _resolve_video_timing(job.get('pipeline_options'), video_duration_minutes)
    n_scenes = _vt['n_scenes']
    scene_duration = _vt['scene_duration']
    _target_total_sec = _vt['total_duration_sec']
    job.setdefault('pipeline_options', {})['total_duration_sec'] = _target_total_sec
    job.setdefault('pipeline_options', {})['scene_duration_sec'] = float(scene_duration)
    try:
        from zyg_workflows import wan_video_service as _wan_log

        _wan_subs = _wan_log.n_chained_for_scene_duration(scene_duration)
        _wan_nat = _wan_log.effective_wan_scene_duration_sec(scene_duration) * n_scenes
        _log(
            'INFO',
            'Stage 1',
            f'Video timing: {n_scenes} scene(s) × {scene_duration}s '
            f'(target ~{int(_target_total_sec)}s, WAN ~{_wan_nat:.1f}s / {_wan_subs} sub-clip(s) per scene)',
        )
    except Exception:
        _log(
            'INFO',
            'Stage 1',
            f'Video timing: {n_scenes} scene(s) × {scene_duration}s (target total ~{int(_target_total_sec)}s)',
        )
    # Single-scene videos cannot be chained — no previous clip exists to chain from.
    if n_scenes == 1:
        scene_mode = 'independent'
    return n_scenes, scene_duration, _target_total_sec, scene_mode


def _manga_plan_prompts(directive, n_scenes, scene_duration, _style_hint):
    """`(system, user)` asking for a manga/comic panel plan — illustrated panels, no motion."""
    _system = (
        'You are a manga editor and comic art director. '
        'You plan panel-by-panel manga/comic sequences with ink linework and screentone shading. '
        f'Visual style: MANGA ({_style_hint}). '
        'Each scene is one illustrated comic panel — not photographic.'
    )
    _user = (
        f'Create a {n_scenes}-panel manga/comic plan for:\n\n'
        f'"{directive}"\n\n'
        f'VISUAL STYLE: MANGA — {_style_hint}\n'
        f'Each panel is {scene_duration} seconds when assembled (Ken Burns or hold).\n\n'
        f'Respond with ONLY a JSON object (no markdown) with keys:\n'
        f'"music_mood": one of epic, battle, triumphant, mysterious, sad, peaceful, dark, adventure\n'
        f'"scenes": array of {n_scenes} panel objects, each with:\n'
        f'  "description": panel composition in manga style (≤300 chars)\n'
        f'  "flux_prompt": SHORT still-image prompt for one manga panel (≤40 words). '
        f'Ink lines, screentone, bold framing, illustrated — no photorealism, no motion language.\n'
        f'  "wan_prompt": "" (unused — leave empty string)\n'
        f'  "props": [] (unused — leave empty array)\n'
        f'  "narration": 3–4 sentences for voiceover (~{scene_duration}s spoken, ≤400 chars)\n'
        f'  "shot_type": panel framing — e.g. close-up, medium shot, wide establishing panel\n'
        f'  "camera_motion": Ken Burns hint — e.g. slow push-in on face, pan across battlefield\n'
        f'  "scene_type": one of character, action, landscape, establishing\n'
    )
    return _system, _user


def _video_plan_prompts(directive, n_scenes, scene_duration, visual_style, _style_hint):
    """`(system, user)` asking for a cinematic plan — a FLUX still and a WAN motion prompt per scene."""
    _system = (
        'You are a professional video director, cinematographer, and screenwriter. '
        'You plan cinematic video productions with separate optimised prompts for '
        f'still image generation (FLUX) and AI video animation (WAN I2V). '
        f'The visual style for this production is: {visual_style.upper()} ({_style_hint}). '
        f'All flux_prompt and wan_prompt values MUST reflect this style throughout.'
    )
    _user = (
        f'Create a {n_scenes}-scene video plan for the following topic:\n\n'
        f'"{directive}"\n\n'
        f'VISUAL STYLE: {visual_style.upper()} — {_style_hint}\n'
        f'All scene prompts must use this visual style consistently.\n\n'
        f'Each scene is {scene_duration} seconds long. '
        f'Total runtime: {int(n_scenes * scene_duration)} seconds '
        f'({n_scenes} scene{"s" if n_scenes != 1 else ""} × {scene_duration}s).\n\n'
        f'IMPORTANT: Match flux_prompt framing to shot_type — close-up / extreme close-up '
        f'use tight portrait framing, plain dark background, single subject only; '
        f'wide / establishing shots use environmental 16:9 composition.\n'
        f'Canvas: close-up scenes render as portrait (~768×1024); wide scenes as 16:9 (~1360×768).\n\n'
        f'Respond with ONLY a JSON object (no markdown, no extra text) with two keys:\n\n'
        f'"music_mood": choose exactly ONE word from this list that best fits the overall emotional tone of the video: '
        f'epic, battle, triumphant, mysterious, sad, peaceful, dark, adventure\n\n'
        f'"scenes": a JSON array of {n_scenes} scene objects, each with:\n'
        f'  "description": vivid visual description of the scene in {visual_style} style (≤300 chars) — subject, setting, mood, lighting\n'
        f'  "flux_prompt": SHORT still-image prompt for FLUX image generation (≤40 words, ≤250 chars). '
        f'MUST reflect {visual_style} visual style. '
        f'Describe the visual composition, subject appearance, lighting, color palette, and camera framing. '
        f'No motion language. Optimised for a single frame. '
        f'CRITICAL: Every animal, creature, or significant object mentioned in the topic MUST be physically visible and present in the image — '
        f'WAN can only animate subjects that already exist in the source frame.\n'
        f'  "wan_prompt": COMPLETE animation prompt for WAN I2V video model (≤180 words). '
        f'MUST maintain {visual_style} style throughout the animation. '
        f'Describe exactly what moves and how: subject motion, camera movement, environmental motion (wind, water, fire, etc.), '
        f'pacing (slow/fast), and cinematic style. The WAN model sees the FLUX image as the first frame — '
        f'tell it what to animate FROM that starting image. '
        f'CRITICAL: Only animate elements that are ALREADY VISIBLE in the FLUX source image. '
        f'Do NOT introduce new foreground subjects (animals, people, objects) that are not present in the starting frame — '
        f'WAN cannot reliably generate new subjects and will produce stylistically inconsistent or animated-looking results.\n'
        f'  "narration": three to four sentences of rich narration for this scene; when spoken aloud it should take approximately {scene_duration} seconds (≤400 chars)\n'
        f'  "shot_type": cinematic shot type — choose one from: "wide cinematic shot", "medium shot", "close-up", "extreme close-up", "overhead drone shot", "low-angle hero shot", "over-the-shoulder shot", "Dutch angle"\n'
        f'  "camera_motion": specific camera movement (≤80 chars) — e.g. "slow dolly push-in, golden light" or "urgent handheld tracking shot"\n'
        f'  "scene_type": classify the scene — choose exactly one from: '
        f'"pure_action" (intense physical combat, fast-moving battle, kinetic violence with maximum motion — gladiators clashing, cavalry charge, arrow volley, brutal melee), '
        f'"character" (portrait, dialogue, close-up of a person or figure, emotional beat), '
        f'"landscape" (wide environment, atmospheric vista, nature, establishing geography), '
        f'"establishing" (wide shot introducing a location, army formation, city skyline, battlefield overview)\n'
        f'  "props": ["up to 3 short noun phrases for distinct visible physical objects the character handles or that must persist on screen"] — '
        f'empty array if the scene has no such objects\n\n'
        f'Example structure:\n'
        f'{{"music_mood": "peaceful", "scenes": [{{"description": "...", "flux_prompt": "...", "wan_prompt": "...", "narration": "...", "shot_type": "...", "camera_motion": "...", "scene_type": "character", "props": ["..."]}}]}}\n\n'
        f'No extra text, no markdown, just the JSON object.'
    )
    return _system, _user


def _scene_plan_prompts(_manga_mode, directive, n_scenes, scene_duration, visual_style, _style_hint):
    """`(system, user)` for the planner call, wrapped by the Scene DSL when it is loaded."""
    if _manga_mode:
        _system, _user = _manga_plan_prompts(directive, n_scenes, scene_duration, _style_hint)
    else:
        _system, _user = _video_plan_prompts(directive, n_scenes, scene_duration, visual_style, _style_hint)
    if _dsl is not None:
        _system = _dsl.wrap_system_planner(_system, 'manga' if _manga_mode else 'video')
    return _system, _user


def _parse_scene_plan(_raw, n_scenes):
    """`(scenes, music_mood)` from the planner's reply, trimmed to `n_scenes`.

    A markdown fence is stripped, both the current object form and the legacy
    plain array are accepted, and a reply with fewer scenes than asked for
    raises ValueError — the caller falls back rather than ship a short video.
    """
    # Strip code fence if present
    if _raw.startswith('```'):
        _raw = '\n'.join(_raw.split('\n')[1:])
        _raw = _raw.rsplit('```', 1)[0].strip()
    _plan = json.loads(_raw)
    # Handle both new object format and legacy plain array
    if isinstance(_plan, dict):
        scenes = _plan.get('scenes', [])
        _claude_music_mood = str(_plan.get('music_mood', '')).strip().lower()
    else:
        scenes = _plan  # legacy: plain array, no music_mood
        _claude_music_mood = ''
    if not isinstance(scenes, list) or len(scenes) < n_scenes:
        raise ValueError(f'Unexpected scene count: {len(scenes)}')
    return scenes[:n_scenes], _claude_music_mood


def _claude_scene_plan(_log, ak, plan, pipeline_id):
    """Ask Claude for the scene list and the music mood.

    `plan` is the `_ScenePlanRequest` below. Returns `(scenes, music_mood)`;
    on any failure it logs a warning and returns `([], mood_so_far)` so the
    caller can fall back without losing a mood that was already parsed.
    """
    mood = ['']
    try:
        import anthropic as _anthropic

        _client = _anthropic.Anthropic(api_key=ak)
        _pipe_type = 'manga' if plan.manga_mode else 'video'
        _system, _user = _scene_plan_prompts(
            plan.manga_mode, plan.directive, plan.n_scenes, plan.scene_duration, plan.visual_style, plan.style_hint
        )
        _meta = {'topic': plan.directive, 'pipeline_type': _pipe_type, 'n_scenes': plan.n_scenes}
        _log_prompt(
            'claude_scene_plan',
            'Stage 1',
            pipeline_id,
            _user,
            meta=_meta,
            direction='sent',
            role='user',
            llm='claude-sonnet-4-6',
            from_who='system',
            to_who='claude-sonnet-4-6',
            system_prompt=_system,
        )
        with _client.messages.stream(
            model='claude-sonnet-4-6',
            max_tokens=8192,
            system=_system,
            messages=[{'role': 'user', 'content': _user}],
        ) as _st_vp:
            _resp = _st_vp.get_final_message()
        _raw = _resp.content[0].text.strip()
        _log_prompt(
            'claude_scene_plan',
            'Stage 1',
            pipeline_id,
            _raw,
            meta=_meta,
            direction='received',
            role='assistant',
            llm='claude-sonnet-4-6',
            from_who='claude-sonnet-4-6',
            to_who='system',
        )
        scenes, mood[0] = _parse_scene_plan(_raw, plan.n_scenes)
        _log(
            'INFO',
            'Stage 1',
            f'Scene planning complete: {len(scenes)} scenes, music mood: {mood[0] or "(keyword-derived)"}',
        )
        _record_token_usage(
            model='claude-sonnet-4-6',
            prompt_tokens=_resp.usage.input_tokens,
            completion_tokens=_resp.usage.output_tokens,
            pipeline_id=pipeline_id,
            stage='Stage 1',
            pipeline_type=_pipe_type,
            **_caveman_kw('planner'),
        )
        return scenes, mood[0]
    except Exception as _e:
        _log('WARNING', 'Stage 1', f'Claude scene planning failed: {_e} — using fallback')
        return [], mood[0]


def _fallback_scenes(directive, n_scenes):
    """A generic scene list, used when Claude is unavailable or its reply was unusable."""
    return [
        {
            'description': f'Scene {i + 1}: cinematic shot related to "{directive[:60]}"',
            'narration': f'Scene {i + 1} of the video about {directive[:60]}.',
            'props': [],
        }
        for i in range(n_scenes)
    ]


def _dsl_scene_metadata(_sc, directive, visual_style, scene_duration, _vfs_dsl):
    """The Scene-DSL metadata dict for one planned scene."""
    return {
        'duration': float(scene_duration),
        'subject': str(_sc.get('description', ''))[:200],
        'setting': _vfs_dsl.dsl_setting_for_scene(_sc, directive),
        'lighting_style': 'cool_blue' if visual_style == 'cinematic' else '',
        'aspect_ratio': _vfs_dsl.dsl_aspect_for_scene(_sc),
        'composition': str(_sc.get('shot_type', '') or ''),
        'tags': ['video', visual_style, str(_sc.get('scene_type', ''))],
    }


def _persist_scene_dsl(_log, scenes, plan, out_dir, pipeline_id):
    """Write one Scene-DSL snapshot per planned scene under `<out_dir>/dsl` (env-gated, non-fatal)."""
    if _dsl is None or not _dsl.is_enabled('video'):
        return
    try:
        from zyg_workflows import video_flux_still_service as _vfs_dsl

        _vid_dsl_dir = os.path.join(out_dir, 'dsl')
        for _si, _sc in enumerate(scenes):
            _scene_obj = _dsl.build_scene_from_metadata(
                _dsl_scene_metadata(_sc, plan.directive, plan.visual_style, plan.scene_duration, _vfs_dsl),
                pipeline='video',
                scene_id=f'video_{pipeline_id[:8]}_s{_si:02d}',
                sequence=_si,
            )
            _dsl.persist_scene(_scene_obj, _vid_dsl_dir, filename=f'scene_{_si:02d}.yaml')
        _log('INFO', 'Stage 1', f'DSL: {_dsl.status_summary("video")}')
    except Exception as _dsl_e:
        _log('WARNING', 'Stage 1', f'DSL hook failed (non-fatal): {_dsl_e}')


class _ScenePlanRequest:
    """What the planner and the DSL snapshot both need to know about this video."""

    def __init__(self, directive, n_scenes, scene_duration, visual_style, style_hint, manga_mode):
        self.directive = directive
        self.n_scenes = n_scenes
        self.scene_duration = scene_duration
        self.visual_style = visual_style
        self.style_hint = style_hint
        self.manga_mode = manga_mode


def stage_01_scene_plan(ctx):
    """Stage 0 + Stage 1: free the GPU, then plan the scenes onto `ctx`."""
    _complete_stage = ctx._complete_stage
    _log = ctx._log
    _manga_mode = ctx._manga_mode
    _set_stage = ctx._set_stage
    directive = ctx.directive
    job = ctx.job
    out_dir = ctx.out_dir
    pipeline_id = ctx.pipeline_id
    scene_mode = ctx.scene_mode
    video_duration_minutes = ctx.video_duration_minutes
    visual_style = ctx.visual_style

    _startup_vram_sweep(_log, _manga_mode)

    _set_stage('Topic Setup')
    _log('INFO', 'Stage 1', f'Scene planning for: {directive[:120]}')
    _vscfg = _STYLE_LORA_CONFIG.get(visual_style, _STYLE_LORA_CONFIG['cinematic'])
    _style_hint = _vscfg['claude_hint']
    _log('INFO', 'Stage 1', f'Visual style: {visual_style} — {_style_hint}')

    # topic alias — used by TTS, BGM, and other stages that expect this var
    topic = directive

    n_scenes, scene_duration, _target_total_sec, scene_mode = _plan_video_timing(
        _log, job, video_duration_minutes, scene_mode
    )

    ak = os.environ.get('ANTHROPIC_API_KEY', '')
    scenes = []  # list of {'description': str, 'narration': str}
    _claude_music_mood = ''  # Claude-suggested BGM mood, set during Stage 1
    plan = _ScenePlanRequest(directive, n_scenes, scene_duration, visual_style, _style_hint, _manga_mode)

    if ak:
        scenes, _claude_music_mood = _claude_scene_plan(_log, ak, plan, pipeline_id)

    if not scenes:
        scenes = _fallback_scenes(directive, n_scenes)
        _log('INFO', 'Stage 1', f'Using {n_scenes} fallback scenes')

    _complete_stage('Topic Setup')
    job['scenes'] = scenes

    # ── DSL: persist a Scene DSL snapshot per planned scene (env-gated) ──
    _persist_scene_dsl(_log, scenes, plan, out_dir, pipeline_id)
    ctx._claude_music_mood = _claude_music_mood
    ctx._target_total_sec = _target_total_sec
    ctx._vscfg = _vscfg
    ctx.n_scenes = n_scenes
    ctx.scene_duration = scene_duration
    ctx.scene_mode = scene_mode
    ctx.scenes = scenes
    ctx.topic = topic
