#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The dependency inventory, the agent config, Agent Zero.

Lines 3230-3755 of the original module, verbatim: ``CANONICAL_LLMS``,
``DEPENDENCIES_CONFIG``, ``get_agent_config``, the Agent Zero legacy shape, the
Google-Trends topic pools with the sports blocklist and the Zero kanban
sequential queue with its auto-mode scheduler.
"""

# Verbatim move: the original import order is load-bearing, and every name here is read
# back off zyg_dashboard.crewai_web_gui by the bp_* blueprints.

from zyg_dashboard import paths as _dash_paths
from zyg_dashboard.crewai_web_gui._bootstrap import (
    _RUNTIME_DIR,
    _zero_load_config,
    _zyg_log,
    gui_state,
    json,
    jsonify,
    os,
    threading,
)

# Canonical LLMs list for Settings → LLMS overlay
CANONICAL_LLMS = [
    'Animatediff',
    'Bark',
    'Claude 3',
    'Controlnet',
    'Crewai Openagents',
    'DeepSeek Coder 33B',
    'Dreambooth',
    'Dreamshaper Realisticvision',
    'GPT-OSS 20B',
    'HumanEval',
    'LLaMA 3 70B',
    'Mistral 7B',
    'Qwen3.5 9B',
    'Qwen3.6 35B-A3B',
    'Plotly',
    'Stable Diffusion 1.5 XL',
    'Stable Video Diffusion',
    'Tortoise TTS',
]


# 2026-07-17 heavy-tranche: get_llms_list moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: _check_dependency moved to bp_integrity_ops.py


# Full AI production stack. Tuples: (import_name, pkg_name, optional, category)
# Categories: core, backend, agents, llm, embeddings, diffusion, video_gen, video_proc, speech, data, job_queue, monitoring, analytics, security, dev
DEPENDENCIES_CONFIG = [
    # CORE – basic Python infrastructure
    ('pydantic', 'pydantic', False, 'core'),
    ('dotenv', 'python-dotenv', False, 'core'),
    ('rich', 'rich', False, 'core'),
    ('click', 'click', False, 'core'),
    ('tqdm', 'tqdm', False, 'core'),
    ('tenacity', 'tenacity', False, 'core'),
    ('orjson', 'orjson', False, 'core'),
    ('yaml', 'pyyaml', False, 'core'),
    # BACKEND – Flask / API
    ('flask', 'flask', False, 'backend'),
    ('flask_cors', 'flask-cors', False, 'backend'),
    ('flask_limiter', 'flask-limiter', False, 'backend'),
    ('waitress', 'waitress', False, 'backend'),
    ('requests', 'requests', False, 'backend'),
    ('httpx', 'httpx', False, 'backend'),
    ('aiohttp', 'aiohttp', False, 'backend'),
    ('fastapi', 'fastapi', True, 'backend'),
    ('uvicorn', 'uvicorn', True, 'backend'),
    ('starlette', 'starlette', True, 'backend'),
    # AGENTS – orchestration
    ('crewai', 'crewai', False, 'agents'),
    ('openagents', 'openagents', True, 'agents'),
    ('langchain', 'langchain', False, 'agents'),
    ('langchain_core', 'langchain-core', False, 'agents'),
    ('langchain_community', 'langchain-community', False, 'agents'),
    ('langchain_experimental', 'langchain-experimental', True, 'agents'),
    ('pyautogen', 'autogen', True, 'agents'),
    ('langchain_ollama', 'langchain-ollama', True, 'agents'),
    # LLM RUNTIME – local LLMs (LLaMA, Mistral, DeepSeek)
    ('transformers', 'transformers', False, 'llm'),
    ('accelerate', 'accelerate', False, 'llm'),
    ('bitsandbytes', 'bitsandbytes', False, 'llm'),
    ('sentencepiece', 'sentencepiece', False, 'llm'),
    ('safetensors', 'safetensors', False, 'llm'),
    ('huggingface_hub', 'huggingface-hub', False, 'llm'),
    ('peft', 'peft', False, 'llm'),
    ('vllm', 'vllm', True, 'llm'),
    ('optimum', 'optimum', True, 'llm'),
    # EMBEDDINGS – vector search
    ('faiss', 'faiss-cpu', True, 'embeddings'),
    ('chromadb', 'chromadb', True, 'embeddings'),
    ('sentence_transformers', 'sentence-transformers', True, 'embeddings'),
    # DIFFUSION – Stable Diffusion, ControlNet, AnimateDiff
    ('torch', 'torch', False, 'diffusion'),
    ('torchvision', 'torchvision', False, 'diffusion'),
    ('diffusers', 'diffusers', False, 'diffusion'),
    ('xformers', 'xformers', True, 'diffusion'),
    ('compel', 'compel', True, 'diffusion'),
    ('imwatermark', 'invisible-watermark', True, 'diffusion'),
    ('cv2', 'opencv-python', False, 'diffusion'),
    ('PIL', 'Pillow', False, 'diffusion'),
    ('skimage', 'scikit-image', True, 'diffusion'),
    # VIDEO GENERATION – SVD, AnimateDiff pipelines
    ('imageio', 'imageio', False, 'video_gen'),
    ('imageio_ffmpeg', 'imageio-ffmpeg', False, 'video_gen'),
    ('decord', 'decord', True, 'video_gen'),
    ('einops', 'einops', True, 'video_gen'),
    # VIDEO PROCESSING – clip-farm slicing
    ('ffmpeg', 'ffmpeg-python', False, 'video_proc'),
    ('moviepy', 'moviepy', False, 'video_proc'),
    ('av', 'av', False, 'video_proc'),
    ('scenedetect', 'scenedetect', False, 'video_proc'),
    ('pydub', 'pydub', False, 'video_proc'),
    ('librosa', 'librosa', False, 'video_proc'),
    ('soundfile', 'soundfile', False, 'video_proc'),
    ('yt_dlp', 'yt-dlp', True, 'video_proc'),
    ('pymediainfo', 'pymediainfo', True, 'video_proc'),
    # SPEECH / AUDIO – Bark, Tortoise, Whisper
    ('torchaudio', 'torchaudio', False, 'speech'),
    ('phonemizer', 'phonemizer', True, 'speech'),
    ('encodec', 'encodec', True, 'speech'),
    ('whisper', 'whisper', True, 'speech'),
    ('faster_whisper', 'faster-whisper', False, 'speech'),
    ('bark', 'bark', True, 'speech'),
    ('tortoise', 'tortoise-tts', True, 'speech'),
    # NLP – text processing, keyword extraction, topic modelling
    ('spacy', 'spacy', True, 'nlp'),
    ('keybert', 'keybert', True, 'nlp'),
    ('sklearn', 'scikit-learn', True, 'nlp'),
    # VISION – object detection, image hashing, CLIP
    ('ultralytics', 'ultralytics', True, 'vision'),
    ('imagehash', 'ImageHash', True, 'vision'),
    # DATA STORAGE
    ('sqlalchemy', 'sqlalchemy', False, 'data'),
    ('alembic', 'alembic', False, 'data'),
    ('redis', 'redis', False, 'data'),
    ('minio', 'minio', False, 'data'),
    ('aiosqlite', 'aiosqlite', True, 'data'),
    ('praw', 'praw', True, 'data'),
    ('pytrends', 'pytrends', True, 'data'),
    ('youtube_transcript_api', 'youtube-transcript-api', True, 'data'),
    # JOB QUEUE / SCHEDULING
    ('celery', 'celery', False, 'job_queue'),
    ('apscheduler', 'apscheduler', False, 'job_queue'),
    ('rq', 'rq', True, 'job_queue'),
    # MONITORING
    ('psutil', 'psutil', False, 'monitoring'),
    ('loguru', 'loguru', True, 'monitoring'),
    ('prometheus_client', 'prometheus-client', True, 'monitoring'),
    ('pynvml', 'pynvml', True, 'monitoring'),
    # ANALYTICS
    ('plotly', 'plotly', False, 'analytics'),
    ('pandas', 'pandas', False, 'analytics'),
    ('numpy', 'numpy', False, 'analytics'),
    ('matplotlib', 'matplotlib', True, 'analytics'),
    ('seaborn', 'seaborn', True, 'analytics'),
    # SECURITY
    ('cryptography', 'cryptography', False, 'security'),
    ('passlib', 'passlib', True, 'security'),
    # DEVELOPMENT / TESTING
    ('pytest', 'pytest', True, 'dev'),
    ('black', 'black', True, 'dev'),
    ('isort', 'isort', True, 'dev'),
    ('mypy', 'mypy', True, 'dev'),
]


# 2026-07-17 heavy-tranche: get_dependencies_status moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: get_workflow_step_agents moved to bp_agents_api.py


# 2026-07-17 heavy-tranche: get_agents_config moved to bp_agents_api.py


# 2026-07-17 heavy-tranche: get_agent_config_by_name moved to bp_agents_api.py


# 2026-07-17 heavy-tranche: get_agent_logbook moved to bp_agents_api.py


# 2026-07-17 heavy-tranche: api_prompt_log moved to bp_agents_api.py


def get_agent_config():
    config_path = str(_dash_paths.PKG_DIR / 'FULL_TASK_SPECIFICATIONS.json')
    with open(config_path, 'r') as f:
        data = json.load(f)
    return jsonify(data)


# 2026-10-06 round-2 split: _get_gpu_bar_mapping and _get_cpu_bar_mapping moved to
# zyg_dashboard.gui.telemetry (they read _load_canonical_json back off this module)


# 2026-07-17 heavy-tranche: get_agent_model_bar_mapping moved to bp_agents_api.py

# 2026-07-17 heavy-tranche: get_cpu_agent_model_bar_mapping moved to bp_agents_api.py

# --- Agent Zero (user-facing chatbot, wake with "z") ---
# 2026-10-06 round-2 split: AGENT_ZERO_CONFIG_PATH and _zero_load_config moved to
# zyg_dashboard.gui.zero_store


def _zero_agent_legacy_shape():
    """Return Zero as legacy agent shape for /api/agents. Zero is from agent_zero.json, not agents.json."""
    cfg = _zero_load_config()
    llms = cfg.get('llms') or {}
    ai_models = list(llms.values()) if isinstance(llms, dict) else []
    return {
        'id': cfg.get('id') or 'zero',
        'name': cfg.get('name') or 'Zero',
        'role': cfg.get('role', ''),
        'goal': cfg.get('goal', ''),
        'backstory': cfg.get('backstory', ''),
        'department': cfg.get('department', 'System'),
        'tier': cfg.get('tier', 0),
        'primary_task': cfg.get('goal', ''),
        'tools': [],
        'skills': cfg.get('capabilities', []),
        'max_concurrent_tasks': 1,
        'current_tasks': 0,
        'supervisor': '',
        'subordinates': [],
        'production_workflow': [],
        'tasks': [],
        'performance_metrics': [],
        'ai_models': ai_models,
        'ai_models_display': list(llms.values()) if isinstance(llms, dict) else [],
        'capabilities': cfg.get('capabilities', []),
        'gpu_schedule': None,
    }


# 2026-07-17 heavy-tranche: _zero_classify_task moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_get_model moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_load_governance moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_gather_context moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_required_llms moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_ollama_tags moved to bp_zero.py


# 2026-07-17 heavy-tranche: zero_workflow_health moved to bp_zero.py


# 2026-07-17 heavy-tranche: zero_workflow_override moved to bp_zero.py


# 2026-07-17 heavy-tranche: zero_context moved to bp_zero.py


# 2026-07-17 heavy-tranche: get_zero_llms_status moved to bp_zero.py


# 2026-07-17 heavy-tranche: zero_install_llms moved to bp_zero.py


# 2026-07-17 modularization: removed duplicate /api/zero/context route (was shadowed by zero_context above; see crews_modularization_backups_20260717)


# 2026-07-17 heavy-tranche: _zero_extract_image_base64 moved to bp_zero.py


# 2026-07-17 heavy-tranche: zero_chat moved to bp_zero.py


# ── Internal API: called by zero_public_server.py with X-Zero-Public-Token ───

# 2026-07-17 heavy-tranche: api_internal_zero_classify moved to bp_zero.py


# 2026-07-17 heavy-tranche: api_internal_pipeline_start moved to bp_pipeline_api.py


# 2026-07-17 heavy-tranche: api_internal_pipeline_status moved to bp_pipeline_api.py


# 2026-07-17 heavy-tranche: api_internal_pipeline_download moved to bp_pipeline_api.py


# 2026-10-06 layering: ZERO_AUDIT_PATH and _zero_audit_log moved to zyg_dashboard.appcore
# 2026-10-06 round-2 split: ZERO_TASK_STATE_PATH, and the import site of those two, moved to
# zyg_dashboard.gui.zero_store

# 2026-07-17 modularization: lines moved to a bp_* blueprint module (see crews_modularization_backups_20260717)


# ── Agent Zero: Google Trends "find topics" feature ─────────────────────────

_ZERO_TOPICS_PENDING: dict = {}  # client_ip → {topics: [...], ts: float}
_ZERO_TOPICS_PENDING_PATH = os.path.join(_RUNTIME_DIR, 'zero_topics_pending.json')
_ZERO_TOPICS_TTL = 86400  # 24 hours


# 2026-07-17 heavy-tranche: _zero_pending_save moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_pending_load moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_fetch_trending_raw moved to bp_zero.py


_SPORTS_KEYWORD_BLOCKLIST = {
    # Tournaments / cups / leagues
    'world cup',
    'world series',
    'stanley cup',
    'super bowl',
    'superbowl',
    'champions league',
    'europa league',
    'premier league',
    'bundesliga',
    'la liga',
    'serie a',
    'ligue 1',
    'copa america',
    'africa cup',
    'gold cup',
    'nations league',
    'concacaf',
    'continental cup',
    'championship game',
    'playoff',
    'playoffs',
    # Sports governing bodies & competition names
    'icc ',
    ' icc',
    'icc,',
    ' t20',
    't20 ',
    'one day international',
    ' odi',
    'wimbledon',
    'french open',
    'us open tennis',
    'australian open',
    'grand slam',
    'atp ',
    'wta ',
    'pga tour',
    'masters golf',
    'the open championship',
    'tour de france',
    'grand prix',
    'formula 1',
    'formula one',
    ' f1 ',
    ' nfl',
    'nfl ',
    ' nba',
    'nba ',
    ' mlb',
    'mlb ',
    ' nhl',
    'nhl ',
    ' mls',
    'mls ',
    'ncaa',
    'nascar',
    'daytona 500',
    'indy 500',
    'ufc ',
    ' ufc',
    ' mma',
    'mma ',
    'rugby world',
    'six nations',
    'ashes series',
    'ipl ',
    ' ipl',
    'euro 2024',
    'euro 2025',
    'euro 2026',
    # Match/game language
    ' vs ',
    ' vs.',
    'halftime',
    'final score',
    'match result',
    'game 7',
    'overtime win',
    'hat trick',
    'touchd',
    # Explicit sports exit/result framing
    'world cup exit',
    'cup exit',
    'cup qualifying',
    'cup draw',
}


# 2026-07-17 heavy-tranche: _sports_pre_filter moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_filter_documentary_topics moved to bp_zero.py


_ZERO_TOPIC_POOLS_PATH = str(_dash_paths.DATA_DIR / 'zero_topic_pools.json')

_ZERO_POOL_LABELS = [
    ('influential_people', 'Influential Person'),
    ('historic_events', 'Historic Event'),
    ('histomap_peoples', 'Ancient Civilization'),
    ('historic_inventions', 'Historic Invention'),
    ('extinct_species', 'Extinct Species'),
    ('big_history_topics', 'Big History'),
    ('historic_wars', 'Historic War'),
    ('space_exploration', 'Space Mission'),
    ('aviation_firsts', 'Aviation First'),
    ('exploration_voyages', 'Exploration Voyage'),
    ('geopolitical_events', 'Geopolitical Event'),
    # literature_milestones excluded — pool contains copyrighted works (post-1922)
    # that would create infringement risk in AI-generated documentary content.
]

_ZERO_POOL_PICK_COUNT = 6  # how many topics to present each call
_ZERO_BATCH_SCHEDULE_PATH = os.path.join(_RUNTIME_DIR, 'zero_batch_schedule.json')
_ZERO_PUB_TIMES = ['08:00', '14:00', '20:00']  # Amsterdam publish slots
_ZERO_BATCH_LOCK = __import__('threading').Lock()
_ZERO_KANBAN_PATH = os.path.join(_RUNTIME_DIR, 'zero_kanban_batch.json')
_ZERO_AUTO_MODE_PATH = os.path.join(_RUNTIME_DIR, 'zero_auto_mode.json')
_ZERO_KANBAN_LOCK = threading.Lock()


# 2026-07-17 heavy-tranche: _zero_fetch_pool_topics moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_find_topics_handler moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_compute_batch_publish_slots moved to bp_zero.py


def _zero_claim_batch_slot(pipeline_id: str) -> dict:
    """Atomically claim the next unclaimed slot from zero_batch_schedule.json.
    Stamps scheduled_upload_at / scheduled_publish_at into the pipeline state file.
    Returns the slot dict, or {} if no schedule exists or no free slots remain.
    """
    with _ZERO_BATCH_LOCK:
        try:
            if not os.path.exists(_ZERO_BATCH_SCHEDULE_PATH):
                return {}
            with open(_ZERO_BATCH_SCHEDULE_PATH, 'r', encoding='utf-8') as _f:
                _sched = json.load(_f)
            _slots = _sched.get('slots', [])
            # Already claimed by this pipeline? Return existing slot.
            for _s in _slots:
                if _s.get('claimed_by') == pipeline_id:
                    return _s
            _free = [_s for _s in _slots if not _s.get('claimed_by')]
            if not _free:
                return {}
            _slot = _free[0]
            _slot['claimed_by'] = pipeline_id
            with open(_ZERO_BATCH_SCHEDULE_PATH, 'w', encoding='utf-8') as _f:
                json.dump(_sched, _f, indent=2)
            # Stamp the schedule into the pipeline state file so it persists.
            _st_path = os.path.join(_RUNTIME_DIR, f'pipeline_{pipeline_id}_state.json')
            if os.path.exists(_st_path):
                try:
                    with open(_st_path, 'r', encoding='utf-8') as _f:
                        _pst = json.load(_f)
                    _pst['scheduled_upload_at'] = _slot['upload_at']
                    _pst['scheduled_publish_at'] = _slot['publish_at']
                    with open(_st_path, 'w', encoding='utf-8') as _f:
                        json.dump(_pst, _f, indent=2)
                except Exception as _exc:
                    _zyg_log.warning(
                        'schedule slot not written into %s, the pipeline keeps no upload time: %s', _st_path, _exc
                    )
            return _slot
        except Exception:
            return {}


# 2026-07-17 heavy-tranche: _zero_launch_topic_documentaries moved to bp_zero.py


# ── end "find topics" feature ─────────────────────────────────────────────────


# ── Zero Kanban: sequential pipeline queue + auto-mode scheduler ──────────────

# 2026-07-17 heavy-tranche: _zero_kanban_load moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_kanban_save moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_auto_mode_load moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_auto_mode_save moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_kanban_pipeline_outcome moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_kanban_create_batch moved to bp_zero.py


gui_state._ZERO_RAM_GATE_HOLDING = False


# 2026-07-17 heavy-tranche: _mem_available_gb moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_batch_release_models moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_kanban_tick moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_auto_scheduler_tick moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_kanban_watcher moved to bp_zero.py


# ── end Zero Kanban ───────────────────────────────────────────────────────────

# 2026-07-17 heavy-tranche: lines 7176-7176 moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_read_task_state moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_write_task_state moved to bp_zero.py
