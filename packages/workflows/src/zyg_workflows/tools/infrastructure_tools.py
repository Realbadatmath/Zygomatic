# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Infrastructure tools: PostgreSQL storage, Redis queue, APScheduler,
asset stores, platform registries, and monitoring tools.

The index tables live in Postgres schema `tools` (see pgdb.py); the `db_path`
arguments below are accepted for signature compatibility only.
"""

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

from zyg_workflows import pgdb
from psycopg.rows import dict_row

try:
    from langchain.tools import BaseTool
except ImportError:
    try:
        from langchain_core.tools import BaseTool
    except ImportError:

        class BaseTool:
            name: str = ''
            description: str = ''

            def _run(self, *args, **kwargs):
                raise NotImplementedError


import threading

_RUNTIME_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'runtime')

# Accepted for compatibility, ignored since 2026-10-02: the index tables moved to
# Postgres schema `tools` and no tool opens a file database any more.
_DEFAULT_DB = os.path.join(_RUNTIME_DIR, 'clipfarm.db')

# A table name an agent may hand us is interpolated into DDL, so it must be a
# plain unquoted identifier and nothing else.
_IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,62}$')


def _tbl(name: str) -> str:
    """`tools."<name>"` for a validated identifier; ValueError for anything else."""
    if not _IDENT.match(name or ''):
        raise ValueError(f'Invalid table name: {name!r}')
    return f'tools."{name}"'


def _runtime_path(filename: str) -> str:
    return os.path.join(_RUNTIME_DIR, os.path.basename(filename))


def _ensure_runtime_dir() -> str:
    """Create the tools' runtime directory and return it.

    Every store below calls this just before it writes. It must NOT go into
    `_runtime_path()`: that one is evaluated as a default argument while the
    classes are being defined, i.e. at import, and an import that makes a
    directory breaks a bare CI runner.
    """
    os.makedirs(_RUNTIME_DIR, exist_ok=True)
    return _RUNTIME_DIR


def _parse_iso(value) -> datetime | None:
    """A UTC-aware datetime from an ISO stamp written by `_now_iso()`, else None."""
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Agent Executor Registry — populated by Flask at startup so tools can
# actually spawn real CrewAI crews when the Overseer activates an agent.
# ---------------------------------------------------------------------------
_AGENT_EXECUTOR: dict = {}  # agent_name -> CrewAI Agent instance
_AGENT_CONFIGS: dict = {}  # agent_name -> raw config dict (goal, backstory…)
_CREW_CLS = None
_TASK_CLS = None
_PROCESS_CLS = None
_ACTIVE_JOBS: dict = {}  # job_id -> {status, agent, result, error}
_JOBS_LOCK = threading.Lock()


def register_agent_executor(agents_dict: dict, configs_dict: dict, crew_cls, task_cls, process_cls):
    """Call once at Flask startup to wire real agents into the activation tool."""
    global _AGENT_EXECUTOR, _AGENT_CONFIGS, _CREW_CLS, _TASK_CLS, _PROCESS_CLS
    _AGENT_EXECUTOR.update(agents_dict)
    _AGENT_CONFIGS.update(configs_dict)
    _CREW_CLS = crew_cls
    _TASK_CLS = task_cls
    _PROCESS_CLS = process_cls


def get_active_jobs() -> dict:
    with _JOBS_LOCK:
        return dict(_ACTIVE_JOBS)


def _get_db(db_path: str = _DEFAULT_DB):
    """db_path is accepted for signature compatibility and IGNORED: all index
    tables live in Postgres schema tools."""
    return pgdb.raw_connect()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteIndexStorageTool(BaseTool):
    name: str = 'PostgreSQL (index storage)'
    description: str = (
        'Store and query indexed content records in PostgreSQL (schema tools). '
        "Actions: 'create_table', 'insert', 'query', 'delete'."
    )

    def _run(
        self,
        action: str,
        table: str = 'content_index',
        data_json: str = '{}',
        content_contains: str = '',
        limit: int = 100,
        db_path: str = _DEFAULT_DB,
    ) -> str:
        conn = _get_db(db_path)
        try:
            if action == 'create_table':
                # content_index and asset_index come from Alembic; this is the
                # escape hatch for a table name an agent chose itself.
                conn.execute(f"""CREATE TABLE IF NOT EXISTS {_tbl(table)} (
                    id TEXT PRIMARY KEY,
                    content TEXT,
                    metadata TEXT,
                    indexed_at TEXT
                )""")  # noqa: S608  identifier validated by _tbl(); no values interpolated
                conn.commit()
                return json.dumps({'status': 'table_ready', 'table': table})
            elif action == 'insert':
                data = json.loads(data_json) if isinstance(data_json, str) else data_json
                row_id = data.get('id', f'row_{int(time.time() * 1000)}')
                conn.execute(
                    f'INSERT INTO {_tbl(table)} (id, content, metadata, indexed_at) '  # nosec B608  # noqa: S608  identifier validated by _tbl(); every value is bound below
                    'VALUES (%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET '
                    'content=EXCLUDED.content, metadata=EXCLUDED.metadata, '
                    'indexed_at=EXCLUDED.indexed_at',
                    (row_id, data.get('content', ''), json.dumps(data.get('metadata', {})), _now_iso()),
                )
                conn.commit()
                return json.dumps({'status': 'inserted', 'id': row_id, 'table': table})
            elif action == 'query':
                # This took a whole WHERE/ORDER BY/LIMIT tail as a string, so a
                # caller's search term reached the SQL parser verbatim — the
                # in-tree caller built `content LIKE '%<term>%'` by hand. The
                # filter is now structured and bound; the `%` wildcards sit in
                # the parameter, which psycopg never rescans for placeholders.
                sql = f'SELECT * FROM {_tbl(table)}'  # nosec B608  # noqa: S608  identifier validated by _tbl(); filter values bound below
                params: list = []
                if content_contains:
                    sql += ' WHERE content LIKE %s'
                    params.append(f'%{content_contains}%')
                sql += ' ORDER BY indexed_at DESC LIMIT %s'
                params.append(max(1, min(int(limit), 1000)))
                rows = conn.cursor(row_factory=dict_row).execute(sql, params).fetchall()
                return json.dumps({'count': len(rows), 'rows': [dict(r) for r in rows]})
            elif action == 'delete':
                data = json.loads(data_json) if isinstance(data_json, str) else data_json
                row_id = data.get('id', '')
                if row_id:
                    conn.execute(
                        f'DELETE FROM {_tbl(table)} WHERE id=%s',  # nosec B608  # noqa: S608  identifier validated by _tbl(); id is bound
                        (row_id,),
                    )
                    conn.commit()
                    return json.dumps({'status': 'deleted', 'id': row_id})
                return json.dumps({'error': 'No id provided for delete'})
        except Exception as e:
            return json.dumps({'error': str(e)})
        finally:
            conn.close()
        return json.dumps({'error': f'Unknown action: {action}'})


class ContentIndexDBQueryTool(BaseTool):
    name: str = 'Content Index DB Query'
    description: str = 'Query the content index database for matching records.'

    def _run(
        self, search_term: str = '', table: str = 'content_index', limit: int = 20, db_path: str = _DEFAULT_DB
    ) -> str:
        tool = SQLiteIndexStorageTool()
        # Ensure table exists
        tool._run('create_table', table=table, db_path=db_path)
        return tool._run('query', table=table, content_contains=search_term, limit=limit, db_path=db_path)


class AssetIndexDBTool(BaseTool):
    name: str = 'Asset Index DB'
    description: str = (
        "Index and query pipeline assets (video files, audio files, thumbnails). Actions: 'index', 'search', 'remove'."
    )

    def _run(
        self, action: str, asset_path: str = '', asset_type: str = 'video', tags: str = '', db_path: str = _DEFAULT_DB
    ) -> str:
        conn = _get_db(db_path)
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS tools.asset_index (
                id TEXT PRIMARY KEY, path TEXT, type TEXT, tags TEXT,
                size_bytes BIGINT, indexed_at TEXT
            )""")
            conn.commit()
            if action == 'index':
                asset_id = f'{asset_type}_{abs(hash(asset_path))}'
                size = os.path.getsize(asset_path) if os.path.exists(asset_path) else 0
                conn.execute(
                    'INSERT INTO tools.asset_index '
                    '(id, path, type, tags, size_bytes, indexed_at) '
                    'VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET '
                    'path=EXCLUDED.path, type=EXCLUDED.type, tags=EXCLUDED.tags, '
                    'size_bytes=EXCLUDED.size_bytes, indexed_at=EXCLUDED.indexed_at',
                    (asset_id, asset_path, asset_type, tags, size, _now_iso()),
                )
                conn.commit()
                return json.dumps({'status': 'indexed', 'id': asset_id, 'path': asset_path})
            elif action == 'search':
                rows = (
                    conn.cursor(row_factory=dict_row)
                    .execute(
                        'SELECT * FROM tools.asset_index WHERE type=%s OR tags LIKE %s LIMIT 50',
                        (asset_type, f'%{asset_path}%'),
                    )
                    .fetchall()
                )
                return json.dumps({'count': len(rows), 'assets': [dict(r) for r in rows]})
            elif action == 'remove':
                conn.execute('DELETE FROM tools.asset_index WHERE path=%s', (asset_path,))
                conn.commit()
                return json.dumps({'status': 'removed', 'path': asset_path})
        except Exception as e:
            return json.dumps({'error': str(e)})
        finally:
            conn.close()
        return json.dumps({'error': f'Unknown action: {action}'})


class PlatformPostingPatternDBTool(BaseTool):
    name: str = 'Platform Posting Pattern DB'
    description: str = (
        "Store and retrieve posting pattern data (best times, frequency) per platform. Actions: 'store', 'get', 'list'."
    )

    def _run(
        self,
        action: str,
        platform: str = '',
        pattern_json: str = '{}',
        db_path: str = _runtime_path('clipfarm_posting_patterns.json'),
    ) -> str:
        data = {}
        if os.path.exists(db_path):
            with open(db_path) as f:
                data = json.load(f)
        if action == 'store':
            pattern = json.loads(pattern_json) if isinstance(pattern_json, str) else pattern_json
            data[platform] = {**data.get(platform, {}), **pattern, 'updated_at': _now_iso()}
            _ensure_runtime_dir()
            with open(db_path, 'w') as f:
                json.dump(data, f, indent=2)
            return json.dumps({'status': 'stored', 'platform': platform})
        elif action == 'get':
            return json.dumps({'platform': platform, 'pattern': data.get(platform, {})})
        elif action == 'list':
            return json.dumps({'platforms': list(data.keys()), 'data': data})
        return json.dumps({'error': f'Unknown action: {action}'})


class OverlayTemplateStoreTool(BaseTool):
    name: str = 'Overlay / Template Store'
    description: str = (
        'Store and retrieve video overlay templates (intros, outros, lower thirds). '
        "Actions: 'save', 'get', 'list', 'delete'."
    )

    def _run(
        self,
        action: str,
        template_name: str = '',
        template_path: str = '',
        template_type: str = 'overlay',
        store_file: str = _runtime_path('clipfarm_templates.json'),
    ) -> str:
        data = {}
        if os.path.exists(store_file):
            with open(store_file) as f:
                data = json.load(f)
        if action == 'save':
            data[template_name] = {'path': template_path, 'type': template_type, 'saved_at': _now_iso()}
            _ensure_runtime_dir()
            with open(store_file, 'w') as f:
                json.dump(data, f, indent=2)
            return json.dumps({'status': 'saved', 'name': template_name})
        elif action == 'get':
            return json.dumps({'name': template_name, 'template': data.get(template_name)})
        elif action == 'list':
            return json.dumps({'count': len(data), 'templates': data})
        elif action == 'delete':
            removed = data.pop(template_name, None)
            _ensure_runtime_dir()
            with open(store_file, 'w') as f:
                json.dump(data, f, indent=2)
            return json.dumps({'status': 'deleted' if removed else 'not_found'})
        return json.dumps({'error': f'Unknown action: {action}'})


class MusicLibraryManagerTool(BaseTool):
    name: str = 'Music Library Manager'
    description: str = "Manage a library of background music tracks. Actions: 'add', 'search', 'list', 'remove'."

    def _run(
        self,
        action: str,
        track_path: str = '',
        genre: str = '',
        bpm: float = 0,
        duration_sec: float = 0,
        store_file: str = _runtime_path('clipfarm_music_library.json'),
    ) -> str:
        library = []
        if os.path.exists(store_file):
            with open(store_file) as f:
                library = json.load(f)
        if action == 'add':
            track = {
                'path': track_path,
                'genre': genre,
                'bpm': bpm,
                'duration_sec': duration_sec,
                'added_at': _now_iso(),
            }
            library.append(track)
            _ensure_runtime_dir()
            with open(store_file, 'w') as f:
                json.dump(library, f, indent=2)
            return json.dumps({'status': 'added', 'track': track})
        elif action == 'search':
            results = [
                t
                for t in library
                if (not genre or t.get('genre', '').lower() == genre.lower())
                and (not bpm or abs(t.get('bpm', 0) - bpm) < 10)
            ]
            return json.dumps({'count': len(results), 'tracks': results})
        elif action == 'list':
            return json.dumps({'count': len(library), 'tracks': library})
        elif action == 'remove':
            before = len(library)
            library = [t for t in library if t.get('path') != track_path]
            _ensure_runtime_dir()
            with open(store_file, 'w') as f:
                json.dump(library, f, indent=2)
            return json.dumps({'status': 'removed', 'removed_count': before - len(library)})
        return json.dumps({'error': f'Unknown action: {action}'})


class MusicLibraryAssetStoreTool(BaseTool):
    name: str = 'Music Library (asset store)'
    description: str = 'Retrieve music assets from the library by genre, mood, or BPM range.'

    def _run(self, genre: str = '', mood: str = '', bpm_min: float = 0, bpm_max: float = 300) -> str:
        tool = MusicLibraryManagerTool()
        result = json.loads(tool._run('list'))
        tracks = result.get('tracks', [])
        if genre:
            tracks = [t for t in tracks if genre.lower() in t.get('genre', '').lower()]
        if bpm_min > 0 or bpm_max < 300:
            tracks = [t for t in tracks if bpm_min <= t.get('bpm', 0) <= bpm_max]
        return json.dumps({'count': len(tracks), 'tracks': tracks})


class SFXLibraryTool(BaseTool):
    name: str = 'SFX Library'
    description: str = "Browse or retrieve sound effects from the SFX library. Actions: 'add', 'search', 'list'."

    def _run(
        self,
        action: str = 'list',
        sfx_path: str = '',
        category: str = '',
        tags: str = '',
        store_file: str = _runtime_path('clipfarm_sfx_library.json'),
    ) -> str:
        library = []
        if os.path.exists(store_file):
            with open(store_file) as f:
                library = json.load(f)
        if action == 'add':
            entry = {'path': sfx_path, 'category': category, 'tags': tags, 'added_at': _now_iso()}
            library.append(entry)
            _ensure_runtime_dir()
            with open(store_file, 'w') as f:
                json.dump(library, f, indent=2)
            return json.dumps({'status': 'added', 'sfx': entry})
        elif action == 'search':
            results = [
                s
                for s in library
                if (not category or category.lower() in s.get('category', '').lower())
                or (not tags or any(t in s.get('tags', '') for t in tags.split(',')))
            ]
            return json.dumps({'count': len(results), 'sfx': results})
        return json.dumps({'count': len(library), 'sfx': library})


class ThumbnailTemplateTool(BaseTool):
    name: str = 'Thumbnail Template Library'
    description: str = 'Browse thumbnail design templates for video covers.'

    def _run(self, style: str = '', store_file: str = _runtime_path('clipfarm_thumbnails.json')) -> str:
        templates = {}
        if os.path.exists(store_file):
            with open(store_file) as f:
                templates = json.load(f)
        if style:
            return json.dumps({'style': style, 'template': templates.get(style)})
        return json.dumps({'count': len(templates), 'available_styles': list(templates.keys()), 'templates': templates})


class ThumbnailTemplateUpdaterTool(BaseTool):
    name: str = 'Thumbnail Template Updater'
    description: str = 'Add or update a thumbnail template in the library.'

    def _run(
        self, style: str, template_data_json: str, store_file: str = _runtime_path('clipfarm_thumbnails.json')
    ) -> str:
        templates = {}
        if os.path.exists(store_file):
            with open(store_file) as f:
                templates = json.load(f)
        templates[style] = json.loads(template_data_json) if isinstance(template_data_json, str) else template_data_json
        _ensure_runtime_dir()
        with open(store_file, 'w') as f:
            json.dump(templates, f, indent=2)
        return json.dumps({'status': 'updated', 'style': style})


class PlatformPolicyRulesetTool(BaseTool):
    name: str = 'Platform Policy Ruleset'
    description: str = 'Read content policy rules for a given platform.'

    def _run(self, platform: str = 'youtube') -> str:
        POLICIES = {
            'youtube': {
                'max_duration_sec': 43200,
                'min_duration_sec': 1,
                'max_file_size_gb': 256,
                'allowed_formats': ['mp4', 'mov', 'avi', 'mkv'],
                'prohibited': ['copyright_music', 'explicit_thumbnails', 'spam'],
                'monetization_min_views': 4000,
                'monetization_min_subs': 1000,
            },
            'tiktok': {
                'max_duration_sec': 600,
                'min_duration_sec': 3,
                'max_file_size_mb': 287,
                'allowed_formats': ['mp4', 'mov'],
                'prohibited': ['platform_watermarks', 'explicit_content'],
            },
            'instagram': {
                'max_duration_sec': 90,
                'min_duration_sec': 3,
                'max_file_size_mb': 100,
                'allowed_formats': ['mp4', 'mov'],
                'aspect_ratios': ['9:16', '4:5', '1:1'],
            },
        }
        return json.dumps(
            {
                'platform': platform,
                'policy': POLICIES.get(platform.lower(), {}),
                'note': 'Policy data is approximate — verify with platform docs',
            }
        )


class PlatformSpecRulesetTool(BaseTool):
    name: str = 'Platform Spec Ruleset'
    description: str = 'Get technical specifications for uploading to a platform.'

    def _run(self, platform: str = 'youtube', content_type: str = 'shorts') -> str:
        SPECS = {
            'youtube': {
                'shorts': {
                    'resolution': '1080x1920',
                    'fps': 60,
                    'aspect': '9:16',
                    'codec': 'H.264',
                    'audio': 'AAC 320kbps',
                },
                'long': {
                    'resolution': '1920x1080',
                    'fps': 60,
                    'aspect': '16:9',
                    'codec': 'H.264',
                    'audio': 'AAC 320kbps',
                },
            },
            'tiktok': {
                'default': {
                    'resolution': '1080x1920',
                    'fps': 60,
                    'aspect': '9:16',
                    'codec': 'H.264/H.265',
                    'audio': 'AAC 128kbps+',
                },
            },
            'instagram': {
                'reels': {
                    'resolution': '1080x1920',
                    'fps': 30,
                    'aspect': '9:16',
                    'codec': 'H.264',
                    'audio': 'AAC 128kbps+',
                },
            },
        }
        platform_specs = SPECS.get(platform.lower(), {})
        spec = platform_specs.get(content_type, platform_specs.get('default', {}))
        return json.dumps({'platform': platform, 'content_type': content_type, 'spec': spec})


class RestrictedChannelRegistryTool(BaseTool):
    name: str = 'Restricted Channel Registry'
    description: str = 'Check if a channel/account is on the restricted list.'

    def _run(
        self, channel_id: str = '', registry_file: str = _runtime_path('clipfarm_restricted_channels.json')
    ) -> str:
        registry = {}
        if os.path.exists(registry_file):
            with open(registry_file) as f:
                registry = json.load(f)
        if channel_id:
            is_restricted = channel_id in registry
            return json.dumps(
                {
                    'channel_id': channel_id,
                    'restricted': is_restricted,
                    'reason': registry.get(channel_id, {}).get('reason', ''),
                }
            )
        return json.dumps({'count': len(registry), 'restricted_channels': list(registry.keys())})


class AgentActivationControllerTool(BaseTool):
    name: str = 'Agent Activation Controller'
    description: str = (
        'Enable, disable, or check the activation status of a pipeline agent. '
        "Actions: 'activate', 'deactivate', 'status', 'list', 'job_status'."
    )

    def _run(self, action: str, agent_name: str = '', task_override: str = '', store_file: str = '') -> str:
        store_file = store_file or _runtime_path('clipfarm_agent_activation.json')
        data = {}
        if os.path.exists(store_file):
            with open(store_file) as f:
                data = json.load(f)

        if action == 'activate':
            job_id = None
            spawn_error = None

            # Spawn a real CrewAI crew if the executor registry is populated
            if agent_name in _AGENT_EXECUTOR and _CREW_CLS is not None:
                import hashlib

                job_id = hashlib.md5(f'{agent_name}{time.time()}'.encode(), usedforsecurity=False).hexdigest()[:12]
                cfg = _AGENT_CONFIGS.get(agent_name, {})
                task_desc = task_override or cfg.get('goal', f'Execute your pipeline role as {agent_name}.')

                def _run_crew(jid=job_id, aname=agent_name, tdesc=task_desc):
                    try:
                        agent = _AGENT_EXECUTOR[aname]
                        task = _TASK_CLS(
                            description=tdesc[:2000],
                            agent=agent,
                            expected_output='Completion status and any outputs or findings from this pipeline step.',
                        )
                        crew = _CREW_CLS(agents=[agent], tasks=[task], verbose=True, process=_PROCESS_CLS.sequential)
                        result = crew.kickoff()
                        with _JOBS_LOCK:
                            _ACTIVE_JOBS[jid] = {
                                'status': 'completed',
                                'agent': aname,
                                'result': str(result),
                                'error': None,
                            }
                    except Exception as exc:
                        with _JOBS_LOCK:
                            _ACTIVE_JOBS[jid] = {'status': 'failed', 'agent': aname, 'result': None, 'error': str(exc)}

                with _JOBS_LOCK:
                    _ACTIVE_JOBS[job_id] = {
                        'status': 'running',
                        'agent': agent_name,
                        'result': None,
                        'error': None,
                        'started_at': _now_iso(),
                    }
                threading.Thread(target=_run_crew, daemon=True).start()
            elif agent_name not in _AGENT_EXECUTOR:
                spawn_error = f"Agent '{agent_name}' not in executor registry (LLM may be in mock mode)"

            data[agent_name] = {'active': True, 'updated_at': _now_iso(), 'job_id': job_id}
            _ensure_runtime_dir()
            with open(store_file, 'w') as f:
                json.dump(data, f, indent=2)
            out = {'status': 'activated', 'agent': agent_name, 'job_id': job_id}
            if spawn_error:
                out['warning'] = spawn_error
            return json.dumps(out)

        elif action == 'deactivate':
            data[agent_name] = {'active': False, 'updated_at': _now_iso()}
            _ensure_runtime_dir()
            with open(store_file, 'w') as f:
                json.dump(data, f, indent=2)
            return json.dumps({'status': 'deactivated', 'agent': agent_name})

        elif action == 'status':
            entry = data.get(agent_name, {'active': False})
            job_id = entry.get('job_id')
            job_info = None
            if job_id:
                with _JOBS_LOCK:
                    job_info = _ACTIVE_JOBS.get(job_id)
            return json.dumps(
                {
                    'agent': agent_name,
                    'active': entry.get('active', False),
                    'updated_at': entry.get('updated_at', 'never'),
                    'job_id': job_id,
                    'job': job_info,
                }
            )

        elif action == 'list':
            return json.dumps({'agents': data, 'count': len(data)})

        elif action == 'job_status':
            with _JOBS_LOCK:
                job = _ACTIVE_JOBS.get(agent_name)  # agent_name used as job_id here
            if not job:
                return json.dumps({'error': f'No job found with id: {agent_name}'})
            return json.dumps(job)

        return json.dumps({'error': f'Unknown action: {action}'})


class PipelineStatusMonitorTool(BaseTool):
    name: str = 'Pipeline Status Monitor'
    description: str = 'Report the current status of all active pipeline stages.'

    def _run(self, pipeline_id: str = '', store_file: str = '') -> str:
        store_file = store_file or _runtime_path('clipfarm_pipeline_status.json')
        data = {}
        if os.path.exists(store_file):
            with open(store_file) as f:
                data = json.load(f)
        if pipeline_id:
            return json.dumps({'pipeline_id': pipeline_id, 'status': data.get(pipeline_id, {'status': 'unknown'})})
        return json.dumps({'active_pipelines': len(data), 'pipelines': data})


class ScheduleMonitorTool(BaseTool):
    name: str = 'Schedule Monitor'
    description: str = 'Monitor the pipeline schedule for upcoming and overdue tasks.'

    def _run(self, look_ahead_hours: float = 24.0) -> str:
        schedule_file = _runtime_path('clipfarm_schedule.json')
        if not os.path.exists(schedule_file):
            return json.dumps({'status': 'no_schedule', 'upcoming': [], 'overdue': []})
        with open(schedule_file) as f:
            schedules = json.load(f)
        # look_ahead_hours used to be ignored: every active entry came back as
        # 'upcoming', so a 1-hour look-ahead answered the same as a 24-hour one.
        now = datetime.now(timezone.utc)
        horizon_seconds = max(0.0, look_ahead_hours) * 3600
        upcoming, unresolved = [], []
        for s in schedules:
            if not s.get('active'):
                continue
            step = float(s.get('interval_seconds') or 0)
            created = _parse_iso(s.get('created_at'))
            if s.get('type') != 'interval' or step <= 0 or created is None:
                # Cron entries need APScheduler's parser to resolve a fire time.
                # Report them rather than drop them from the answer.
                unresolved.append(s)
                continue
            wait = step - (max(0.0, (now - created).total_seconds()) % step)
            if wait <= horizon_seconds:
                upcoming.append({**s, 'next_run': (now + timedelta(seconds=wait)).isoformat()})
        return json.dumps(
            {
                'total_scheduled': len(schedules),
                'look_ahead_hours': look_ahead_hours,
                'upcoming': upcoming[:20],
                'unresolved': unresolved[:20],
            }
        )


class FailurePatternMonitorTool(BaseTool):
    name: str = 'Failure Pattern Monitor (5-minute rolling window)'
    description: str = (
        'Monitor and detect failure patterns in a 5-minute rolling window. '
        'Returns failure rate and whether alert threshold is exceeded.'
    )

    def _run(self, log_file: str = '', threshold_failures: int = 5) -> str:
        log_file = log_file or _runtime_path('clipfarm_audit.json')
        if not os.path.exists(log_file):
            return json.dumps({'failure_count': 0, 'alert': False, 'window_minutes': 5})
        with open(log_file) as f:
            logs = json.load(f)
        # The window was never applied: every failure in the retained log counted,
        # so a quiet pipeline with 5 old failures alerted forever. `_log_event`
        # stamps each entry with a UTC ISO 'timestamp'; an entry we cannot date is
        # not claimed to be inside the window.
        window_start = datetime.now(timezone.utc) - timedelta(seconds=300)
        undated = 0
        recent_failures = []
        for e in logs:
            action = e.get('action', '').lower()
            if 'error' not in action and 'fail' not in action:
                continue
            stamp = _parse_iso(e.get('timestamp'))
            if stamp is None:
                undated += 1
            elif stamp >= window_start:
                recent_failures.append(e)
        count = len(recent_failures)
        return json.dumps(
            {
                'failure_count': count,
                'threshold': threshold_failures,
                'alert': count >= threshold_failures,
                'window_minutes': 5,
                'undated_failures_skipped': undated,
            }
        )


INFRASTRUCTURE_TOOLS = [
    SQLiteIndexStorageTool(),
    ContentIndexDBQueryTool(),
    AssetIndexDBTool(),
    PlatformPostingPatternDBTool(),
    OverlayTemplateStoreTool(),
    MusicLibraryManagerTool(),
    MusicLibraryAssetStoreTool(),
    SFXLibraryTool(),
    ThumbnailTemplateTool(),
    ThumbnailTemplateUpdaterTool(),
    PlatformPolicyRulesetTool(),
    PlatformSpecRulesetTool(),
    RestrictedChannelRegistryTool(),
    AgentActivationControllerTool(),
    PipelineStatusMonitorTool(),
    ScheduleMonitorTool(),
    FailurePatternMonitorTool(),
]

__all__ = [c.__class__.__name__ for c in INFRASTRUCTURE_TOOLS] + ['INFRASTRUCTURE_TOOLS']
