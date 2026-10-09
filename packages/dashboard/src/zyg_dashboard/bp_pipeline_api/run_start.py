# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Moved verbatim out of bp_pipeline_api.py (lines 86-571) when that 1,782-line module
# became this package. Zero logic edits: the bodies below are byte-for-byte the original.

import logging as _zyg_logging
from flask import (
    jsonify,
    request,
    session,
)

from zyg_workflows.pipeline_common import (
    _normalize_pipeline_options,
    _parse_pipeline_model_family,
)

from zyg_dashboard.crewai_web_gui import (  # noqa: E402  late: crewai_web_gui imports this blueprint at its bottom, so `bp` must exist first
    _VALID_VISUAL_STYLES,
    _start_clipfarm_internal,
    _start_creature_pipeline_internal,
    _start_manga_pipeline_internal,
    _start_storyteller_pipeline_internal,
    _start_video_pipeline_internal,
    limiter,
)
from zyg_dashboard.gui.controller import Crew, Process, Task, controller  # noqa: E402
from zyg_dashboard.gui.runtime_state import (  # noqa: E402
    _char_gen_jobs,
    _creature_gen_jobs,
    _workflow_jobs,
)
from zyg_dashboard.gui.scholarly import _start_scholarly_pipeline_internal  # noqa: E402
from zyg_dashboard.gui.zero_store import _zero_audit_log, block_spectator_mutation  # noqa: E402


from zyg_dashboard.bp_pipeline_api import bp  # the Blueprint the package __init__ creates

_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_pipeline_api')


@bp.route('/api/run_task', methods=['POST'])
@limiter.limit('30/hour')
def run_task():
    """API endpoint to run a task with selected agents"""
    r = block_spectator_mutation()
    if r is not None:
        return r
    data = request.json
    agent_names = data.get('agents', [])
    task_description = data.get('task', '')
    model_name = data.get('model', None)
    if not agent_names or not task_description:
        return jsonify({'error': 'Missing agents or task description'}), 400
    # ENFORCE MODEL USAGE
    if model_name:
        for name in agent_names:
            allowed = controller.agent_allowed_models.get(name, [])
            if model_name not in allowed:
                return jsonify({'error': f'Agent {name} is not allowed to use model {model_name}'}), 403
    try:
        # Get selected agents
        selected_agents = []
        for name in agent_names:
            if name in controller.agents:
                selected_agents.append(controller.agents[name])
        if not selected_agents:
            return jsonify({'error': 'No valid agents selected'}), 400
        # Create tasks
        tasks = []
        for agent in selected_agents:
            task = Task(
                description=f'Contribute to: {task_description}',
                agent=agent,
                expected_output='Your contribution to the overall task',
            )
            tasks.append(task)
        # Run crew
        crew = Crew(agents=selected_agents, tasks=tasks, verbose=True, process=Process.sequential)
        result = crew.kickoff()
        return jsonify({'success': True, 'result': str(result), 'agents_used': agent_names})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/run_single_agent', methods=['POST'])
@limiter.limit('30/hour')
def run_single_agent():
    """API endpoint to run a task with a single agent"""
    r = block_spectator_mutation()
    if r is not None:
        return r
    data = request.json
    agent_name = data.get('agent', '')
    task_description = data.get('task', '')
    model_name = data.get('model', None)
    if not agent_name or not task_description:
        return jsonify({'error': 'Missing agent or task description'}), 400
    # ENFORCE MODEL USAGE
    if model_name:
        allowed = controller.agent_allowed_models.get(agent_name, [])
        if model_name not in allowed:
            return jsonify({'error': f'Agent {agent_name} is not allowed to use model {model_name}'}), 403
    try:
        if agent_name not in controller.agents:
            return jsonify({'error': f'Agent {agent_name} not found'}), 400
        agent = controller.agents[agent_name]
        task = Task(
            description=task_description, agent=agent, expected_output='Detailed response with actionable insights'
        )
        crew = Crew(agents=[agent], tasks=[task], verbose=True, process=Process.sequential)
        result = crew.kickoff()
        return jsonify({'success': True, 'result': str(result), 'agent_used': agent_name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/start_clipfarm_workflow', methods=['POST'])
@limiter.limit('10/hour')
def start_clipfarm_workflow():
    """
    Start the full staged Clipfarm pipeline.
    Optionally accepts JSON body: {"directive": "..."} to override the default task description.
    Runs in a background thread so the HTTP response is immediate.
    Returns a job_id you can poll via /api/workflow_status/<job_id>.
    """
    r = block_spectator_mutation()
    if r is not None:
        return r

    data = request.json or {}
    directive = data.get('directive') or None
    niche = (data.get('niche') or '').lower().strip()
    scholarly_topic = (data.get('scholarly_topic') or 'crime').lower().strip()
    _sch_char_id = (data.get('char_id') or data.get('character_id') or '').strip()
    _user_name = (
        data.get('user_name') or session.get('user_name') or session.get('username') or session.get('user_id') or 'User'
    )
    _url = data.get('url') or data.get('source_url') or ''
    # Advanced Settings ride along on the niche route too. Without this the
    # visual intensity dial (and every other option) was reachable from
    # /api/pipeline/start but silently unreachable from /api/niche, which is
    # how the crime / religion / luxury / finance buttons start a documentary.
    _niche_opts = _normalize_pipeline_options(data.get('pipeline_options'))

    if niche == 'crime':
        job_info = _start_scholarly_pipeline_internal(
            directive=directive,
            topic='crime',
            user_name=_user_name,
            url=_url,
            char_id=_sch_char_id,
            pipeline_options=_niche_opts,
        )
        dept = 'crime'
        dept_label = 'Crime'
    elif niche == 'religion':
        job_info = _start_scholarly_pipeline_internal(
            directive=directive,
            topic='religion',
            user_name=_user_name,
            url=_url,
            char_id=_sch_char_id,
            pipeline_options=_niche_opts,
        )
        dept = 'scholarly'
        dept_label = 'Religion'
    elif niche == 'luxury':
        job_info = _start_scholarly_pipeline_internal(
            directive=directive,
            topic='luxury',
            user_name=_user_name,
            url=_url,
            char_id=_sch_char_id,
            pipeline_options=_niche_opts,
        )
        dept = 'scholarly'
        dept_label = 'Luxury'
    elif niche in ('finance', 'financials', 'fin'):
        _fin_topic = scholarly_topic if scholarly_topic else 'finance'
        job_info = _start_scholarly_pipeline_internal(
            directive=directive,
            topic=_fin_topic,
            user_name=_user_name,
            url=_url,
            char_id=_sch_char_id,
            pipeline_options=_niche_opts,
        )
        dept = 'scholarly'
        dept_label = f'Financials ({_fin_topic.title()})'
    elif niche == 'cars':
        job_info = _start_clipfarm_internal(directive=directive or 'cars automotive video content')
        dept = 'clipfarm'
        dept_label = 'Cars'
    elif niche == 'benchmark':
        job_info = _start_clipfarm_internal(directive=directive or 'benchmark comparison tech review')
        dept = 'clipfarm'
        dept_label = 'Benchmark'
    elif niche == 'scholarly':
        job_info = _start_scholarly_pipeline_internal(
            directive=directive,
            topic=scholarly_topic,
            user_name=_user_name,
            url=_url,
            char_id=_sch_char_id,
            pipeline_options=_niche_opts,
        )
        dept = 'scholarly'
        dept_label = f'Scholarly ({scholarly_topic.title()})'
    else:
        job_info = _start_clipfarm_internal(directive=directive)
        dept = 'clipfarm'
        dept_label = 'Clipfarm'

    if 'error' in job_info:
        return jsonify({'error': job_info['error']}), 503

    return jsonify(
        {
            'success': True,
            'job_id': job_info['job_id'],
            'pipeline_id': job_info['job_id'],
            'department': dept,
            'message': f'{dept_label} pipeline started in background.',
        }
    )


@bp.route('/api/internal/pipeline/start', methods=['POST'])
@limiter.exempt
def api_internal_pipeline_start():
    """Start a pipeline. Accepts {pipeline_type, directive, image_paths?}. Returns {job_id, status}."""
    data = request.get_json(silent=True) or {}
    pipeline_type = data.get('pipeline_type', 'scholarly')
    directive = (data.get('directive') or '').strip()
    image_paths = data.get('image_paths') or []
    is_test = bool(data.get('is_test', False)) or directive.startswith('__')
    video_duration_minutes = 0.5
    try:
        video_duration_minutes = max(0.25, min(3.0, float(data.get('video_duration_minutes', 0.5))))
    except (ValueError, TypeError) as _exc:
        _zyg_log.warning('bad video_duration_minutes in the start request, continuing with 0.5: %s', _exc)
    _nar = data.get('narration_enabled')
    narration_enabled = (
        bool(_nar)
        if isinstance(_nar, bool)
        else (str(_nar).lower() not in ('false', '0', 'no'))
        if _nar is not None
        else True
    )
    _vs_raw = (data.get('visual_style') or 'cinematic').strip().lower()
    visual_style = _vs_raw if _vs_raw in _VALID_VISUAL_STYLES else 'cinematic'
    # Optional: per-run image backend selection for Comfy generation (FLUX vs SDXL).
    # Defaults to existing behavior ('flux') so legacy clients remain unchanged.
    model_family = _parse_pipeline_model_family(data.get('model_family'))
    pipeline_options = _normalize_pipeline_options(data.get('pipeline_options'))
    # ~5s single-scene TEST render (fast inspection before a full run). Accept a top-level
    # `test_mode`/`test_scene` flag or the normalized option; force the display test badge on.
    if bool(data.get('test_mode') or data.get('test_scene')) or pipeline_options.get('test_scene'):
        pipeline_options['test_scene'] = True
        is_test = True
    if narration_enabled and pipeline_type not in ('video', 'intro', 'manga', 'storyteller'):
        pipeline_options['burn_subtitles'] = True
    _td_sec = pipeline_options.get('total_duration_sec')
    if _td_sec and pipeline_type in ('video', 'intro', 'manga'):
        video_duration_minutes = max(3.5 / 60.0, min(3.0, float(_td_sec) / 60.0))
    _sm_raw = (data.get('scene_mode') or 'independent').strip().lower()
    scene_mode = _sm_raw if _sm_raw in ('independent', 'continuous') else 'independent'
    ending_text = (data.get('ending_text') or '').strip()
    _user_name = (data.get('user_name') or '').strip()
    _url = (data.get('url') or data.get('source_url') or '').strip()
    # wardrobe (char+outfit), effects "apply preset" (char+effect_id) and asset-library applies
    # (category+asset_id+char) need no directive
    _fx_apply = pipeline_type == 'effects' and (data.get('effect_id') or '').strip()
    _al_apply = pipeline_type == 'asset_apply' and (data.get('asset_id') or '').strip()
    # Briefing departments carry no directive either — a Stockmarket episode's
    # content is decided by the screen, and a betting episode's by the `category`.
    _cr_ref = pipeline_type == 'creature' and bool(image_paths)
    _km_theme = pipeline_type == 'kidsmusic' and bool((data.get('song') or {}).get('theme'))
    # Children's series (kids_<slug>): every word, picture and note comes from
    # the runner's fixed tables, so there is nothing for a directive to say.
    _ks = pipeline_type.startswith('kids_')
    # 2D Character Basics I: the character IS the brief dict (name, gender, age,
    # height, cut, four colours). The Run button sends the same thing as a
    # one-line directive, so either form satisfies the requirement.
    _c2_brief = pipeline_type == 'char2d' and bool(data.get('brief'))
    if (
        not directive
        and pipeline_type not in ('wardrobe', 'remix', 'remix_compilation', 'stocks', 'crypto', 'tokitoki', 'arena')
        and not _fx_apply
        and not _al_apply
        and not _cr_ref
        and not _km_theme
        and not _ks
        and not _c2_brief
    ):
        return jsonify({'error': 'directive is required'}), 400
    # Check if a pipeline is already running
    running = [pid for pid, j in _workflow_jobs.items() if j.get('status') == 'running']
    running += [cid for cid, j in _creature_gen_jobs.items() if j.get('status') == 'running']
    running += [cid for cid, j in _char_gen_jobs.items() if j.get('status') == 'running']
    if running:
        return jsonify({'error': 'pipeline_busy', 'running_id': running[0]}), 409
    _pipe_char_id = (data.get('char_id') or data.get('character_id') or '').strip()
    if pipeline_type == 'crime':
        job_info = _start_scholarly_pipeline_internal(
            directive=directive,
            topic='general',
            narration_enabled=narration_enabled,
            visual_style=visual_style,
            user_name=_user_name,
            url=_url,
            char_id=_pipe_char_id,
            model_family=model_family,
            pipeline_options=pipeline_options,
        )
    elif pipeline_type == 'video':
        job_info = _start_video_pipeline_internal(
            directive=directive,
            image_paths=image_paths,
            video_duration_minutes=video_duration_minutes,
            narration_enabled=narration_enabled,
            visual_style=visual_style,
            scene_mode=scene_mode,
            ending_text=ending_text,
            model_family=model_family,
            pipeline_options=pipeline_options,
            char_id=_pipe_char_id,
        )
    elif pipeline_type == 'manga':
        job_info = _start_manga_pipeline_internal(
            directive=directive,
            image_paths=image_paths,
            video_duration_minutes=video_duration_minutes,
            narration_enabled=narration_enabled,
            scene_mode=scene_mode,
            ending_text=ending_text,
            model_family=model_family,
            pipeline_options=pipeline_options,
        )
    elif pipeline_type == 'creature':
        job_info = _start_creature_pipeline_internal(
            directive=directive,
            image_paths=image_paths,
            model_family=model_family,
            pipeline_options=pipeline_options,
            creature_options=data.get('creature_options'),
            phase=str(data.get('phase') or 'full'),
        )
    elif pipeline_type == 'storyteller':
        _st_params = data.get('storyteller_params') or {}
        job_info = _start_storyteller_pipeline_internal(
            directive=directive,
            char_id=_st_params.get('char_id', ''),
            character_params=_st_params.get('character_params', {}),
            voice_style=_st_params.get('voice_style', 'narration'),
            narrator_voice=_st_params.get('narrator_voice', ''),
            character_voice=_st_params.get('character_voice', ''),
            clip_duration_minutes=float(_st_params.get('clip_duration_minutes', 10.0)),
            era_start=_st_params.get('era_start'),
            era_end=_st_params.get('era_end'),
            camera_mode=_st_params.get('camera_mode', 'automatic'),
            story_prompt=directive or _st_params.get('story_prompt', ''),
            visual_style=visual_style,
            narration_enabled=narration_enabled,
            user_name=_user_name,
            model_family=model_family,
            pipeline_options=pipeline_options,
        )
        if job_info.get('status') == 'rejected' or job_info.get('error'):
            return jsonify(job_info), 400
    elif pipeline_type == 'environments':
        from zyg_workflows import pipeline_envfx_runner as _envfx

        job_info = _envfx.start_environments(
            directive=directive,
            image_paths=image_paths,
            render_mode=(data.get('render_mode') or '3d'),
            pipeline_options=pipeline_options,
        )
    elif pipeline_type == 'effects':
        from zyg_workflows import pipeline_envfx_runner as _envfx

        job_info = _envfx.start_effects(
            directive=directive,
            image_paths=image_paths,
            render_mode=(data.get('render_mode') or '3d'),
            effect_id=(data.get('effect_id') or ''),
            char_id=_pipe_char_id,
            pipeline_options=pipeline_options,
        )
    elif pipeline_type == 'wardrobe':
        from zyg_workflows import pipeline_envfx_runner as _envfx

        job_info = _envfx.start_wardrobe(
            directive=directive,
            char_id=_pipe_char_id,
            outfit_id=(data.get('outfit_id') or ''),
            image_paths=image_paths,
            pipeline_options=pipeline_options,
        )
    elif pipeline_type == 'asset_apply':
        from zyg_workflows import pipeline_envfx_runner as _envfx

        job_info = _envfx.start_asset_apply(
            category=(data.get('category') or ''),
            asset_id=(data.get('asset_id') or ''),
            char_id=_pipe_char_id,
            directive=directive,
            image_paths=image_paths,
            pipeline_options=pipeline_options,
        )
    elif pipeline_type in ('stocks', 'crypto'):
        # Briefing departments (2026-08-06). No directive: the episode's content
        # is whatever today's screen produces, so there is nothing to prompt.
        from zyg_workflows import pipeline_market as _market

        job_info = _market._start(pipeline_type, pipeline_options=pipeline_options)
        if job_info.get('error'):
            return jsonify(job_info), 409 if job_info['error'] == 'pipeline_busy' else 400
    elif pipeline_type in ('tokitoki', 'arena'):
        from zyg_workflows import pipeline_sports as _sports

        job_info = _sports.start_episode(
            pipeline_type,
            (data.get('category') or data.get('sport') or directive or '').strip().lower(),
            pipeline_options=pipeline_options,
        )
        if job_info.get('error'):
            return jsonify(job_info), 409 if job_info['error'] == 'pipeline_busy' else 400
    elif pipeline_type == 'kidsmusic':
        # Children's Music (2026-08-29). Sound only: composes a melody under
        # age-band constraints, renders it through the MIT SoundFont, and asks
        # ACE-Step for the produced take. Its own runner and its own output
        # tree — nothing above this line changes shape because of it.
        from zyg_workflows import pipeline_kidsmusic as _km

        job_info = _km.start_kidsmusic(
            directive=directive, pipeline_options=pipeline_options, song=data.get('song') or data.get('song_params')
        )
        if job_info.get('error'):
            return jsonify(job_info), 400
    elif pipeline_type == 'char2d':
        # 2D Character Basics I (2026-09-16). Blender/MPFB only: an MPFB body
        # under a cel shader, six ink-lined views, mouth sprites timed by
        # Rhubarb and ten posed gestures. Its own runner and its own output
        # tree — nothing above this line changes shape because of it.
        from zyg_workflows import pipeline_char2d as _c2

        job_info = _c2.start_char2d(directive=directive, pipeline_options=pipeline_options, brief=data.get('brief'))
        if job_info.get('error'):
            return jsonify(job_info), 400
    elif pipeline_type.startswith('kids_'):
        # Children's series (2026-09-06). GENERIC on purpose: one branch for all
        # ten runners, resolved through kids_series_common.discover() at call
        # time, so a new pipeline_kids_<slug>.py appears here without an edit.
        from zyg_workflows import kids_series_common as _ks_mod

        slug = pipeline_type[5:]
        _known = _ks_mod.discover()
        if slug not in _known:
            return jsonify({'error': f'unknown kids series {slug}', 'known': sorted(_known)}), 400
        job_info = _ks_mod.start_series(
            slug,
            episode=data.get('episode'),
            pipeline_options=pipeline_options,
            test_mode=bool(pipeline_options.get('test_scene')),
        )
        if job_info.get('error'):
            return jsonify(job_info), 400
    elif pipeline_type == 'remix_ai':
        # Remix Ai (2026-08-29). Studies a popular AI-GENERATED video and builds
        # an original one in the same format: same aesthetic, same beat shape,
        # same genre of soundtrack — new images, new script, new title, different
        # track. Its own runner and its own output tree (data/output/remix_ai/),
        # so nothing above this line changes shape because of it.
        from zyg_workflows import pipeline_remixai as _remixai

        job_info = _remixai.start_remix_ai(
            video_id=(data.get('video_id') or '').strip(), directive=directive, force=bool(data.get('force'))
        )
        if job_info.get('error'):
            return jsonify(job_info), 409 if job_info['error'] == 'pipeline_busy' else 400
    elif pipeline_type in ('remix', 'remix_compilation'):
        from zyg_workflows import pipeline_remix as _remix

        if pipeline_type == 'remix_compilation':
            job_info = _remix.start_compilation(
                clip_ids=data.get('clip_ids') or [],
                target_minutes=data.get('target_minutes'),
                title=(data.get('title') or ''),
                pipeline_options=pipeline_options,
            )
        else:
            job_info = _remix.start_remix(
                source_url=_url or directive, video_id=(data.get('video_id') or ''), pipeline_options=pipeline_options
            )
        if job_info.get('error'):
            _code = 409 if job_info['error'] == 'pipeline_busy' else 400
            return jsonify(job_info), _code
    else:
        job_info = _start_scholarly_pipeline_internal(
            directive=directive,
            topic='general',
            narration_enabled=narration_enabled,
            visual_style=visual_style,
            user_name=_user_name,
            url=_url,
            char_id=_pipe_char_id,
            model_family=model_family,
            pipeline_options=pipeline_options,
        )
    # Tag the job as a test run so the Kanban board can show the "Test Run" badge
    if job_info.get('job_id') and job_info['job_id'] in _workflow_jobs:
        if is_test:
            _workflow_jobs[job_info['job_id']]['is_test'] = True
    _zero_audit_log(
        'internal_pipeline_start',
        {
            'type': pipeline_type,
            'directive': directive[:200],
            'visual_style': visual_style,
            'scene_mode': scene_mode,
            'ending_text': ending_text[:100] if ending_text else '',
        },
    )
    return jsonify(job_info)
