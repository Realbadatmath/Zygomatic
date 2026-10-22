# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline coverage for :mod:`zyg_workflows.tools.infrastructure_tools`.

Nothing here touches Postgres: ``pgdb.raw_connect`` returns a fake connection that records the SQL
it was handed and replays canned rows. Every JSON-backed store gets an explicit file under
``tmp_path``, and ``_RUNTIME_DIR`` is redirected for every test so a path the module derives itself
can never land in the repo's tracked ``data/runtime`` tree.
"""

import json
import os
import types
from datetime import datetime, timedelta, timezone

import pytest

from zyg_workflows.tools import infrastructure_tools as mod


class FakeConn:
    """What ``pgdb.raw_connect()`` returns: it is its own cursor and replays ``rows``."""

    def __init__(self):
        self.statements, self.rows, self.fail_on = [], [], None
        self.commits, self.closed, self.row_factory = 0, False, None

    def execute(self, sql, params=None):
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError('connection lost')
        self.statements.append((sql, params))
        return self

    def cursor(self, row_factory=None):
        self.row_factory = row_factory
        return self

    def fetchall(self):
        return list(self.rows)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


class SyncThread:
    """A ``threading.Thread`` stand-in that runs its target inline, leaking no thread into pytest."""

    def __init__(self, target=None, daemon=False):
        self._target, self.daemon = target, daemon

    def start(self):
        self._target()


class FakeCrew:
    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeCrew.instances.append(self)

    def kickoff(self):
        return 'crew finished'


class BoomCrew(FakeCrew):
    def kickoff(self):
        raise RuntimeError('llm unreachable')


@pytest.fixture(autouse=True)
def runtime_dir(tmp_path, monkeypatch):
    """Point every path the module derives at run time into tmp_path."""
    target = tmp_path / 'runtime'
    monkeypatch.setattr(mod, '_RUNTIME_DIR', str(target))
    return target


@pytest.fixture
def conn(monkeypatch):
    """A fake Postgres connection; a test may re-seed its rows or arm a failure."""
    fake = FakeConn()
    monkeypatch.setattr(mod.pgdb, 'raw_connect', lambda *a, **k: fake)
    return fake


@pytest.fixture
def registry(monkeypatch):
    """An isolated executor registry; monkeypatch restores the real globals afterwards."""
    for name in ('_AGENT_EXECUTOR', '_AGENT_CONFIGS', '_ACTIVE_JOBS'):
        monkeypatch.setattr(mod, name, {})
    for name in ('_CREW_CLS', '_TASK_CLS', '_PROCESS_CLS'):
        monkeypatch.setattr(mod, name, None)
    monkeypatch.setattr(mod, 'threading', types.SimpleNamespace(Thread=SyncThread))
    FakeCrew.instances = []
    return mod


def _j(tool, *args, **kwargs):
    """``tool._run(…)`` with its JSON answer already parsed."""
    return json.loads(tool._run(*args, **kwargs))


def _sql(fake):
    return ' | '.join(s for s, _ in fake.statements)


def _register(crew_cls=FakeCrew):
    """Register two agents: 'editor' has a configured goal, 'rigger' has none."""
    mod.register_agent_executor(
        {'editor': object(), 'rigger': object()},
        {'editor': {'goal': 'Cut the episode down to 90 seconds.'}},
        crew_cls,
        types.SimpleNamespace,  # the module builds a Task(description=…, agent=…, expected_output=…)
        types.SimpleNamespace(sequential='sequential'),
    )


@pytest.mark.parametrize('name', ['content_index', 'A', '_x9', 'a' * 63])
def test_tbl_accepts_plain_identifiers(name):
    assert mod._tbl(name) == f'tools."{name}"'


@pytest.mark.parametrize('name', ['', None, '9lives', 'drop table x', 'a"b', 'a' * 64, 'tools.x'])
def test_tbl_rejects_anything_else(name):
    with pytest.raises(ValueError, match='Invalid table name'):
        mod._tbl(name)


def test_runtime_path_strips_directories_and_ensure_dir_is_idempotent(runtime_dir):
    assert mod._runtime_path('/elsewhere/deep/x.json') == os.path.join(str(runtime_dir), 'x.json')
    assert not runtime_dir.exists()
    assert mod._ensure_runtime_dir() == str(runtime_dir) and runtime_dir.is_dir()
    assert mod._ensure_runtime_dir() == str(runtime_dir)


@pytest.mark.parametrize('value', [None, 17, b'2026-01-01', ['2026-01-01'], 'not a date', ''])
def test_parse_iso_returns_none_for_undatable(value):
    assert mod._parse_iso(value) is None


def test_parse_iso_normalises_to_aware_utc():
    assert mod._parse_iso('2026-01-02T03:04:05') == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert mod._parse_iso('2026-01-02T03:04:05+02:00').utcoffset() == timedelta(hours=2)
    assert mod._parse_iso(mod._now_iso()).tzinfo is not None


def test_register_agent_executor_wires_globals_and_jobs_snapshot_is_a_copy(registry):
    _register()
    assert set(mod._AGENT_EXECUTOR) == {'editor', 'rigger'}
    assert mod._AGENT_CONFIGS['editor']['goal'].startswith('Cut the episode')
    assert (mod._CREW_CLS, mod._TASK_CLS) == (FakeCrew, types.SimpleNamespace)
    assert mod._PROCESS_CLS.sequential == 'sequential'

    mod._ACTIVE_JOBS['job1'] = {'status': 'running'}
    snapshot = mod.get_active_jobs()
    assert snapshot == {'job1': {'status': 'running'}}
    snapshot['job2'] = {'status': 'invented'}
    assert 'job2' not in mod._ACTIVE_JOBS


def test_index_storage_create_table_then_insert(conn):
    tool = mod.SQLiteIndexStorageTool()
    # `db_path` is accepted for signature compatibility only: every tool goes through pgdb.
    assert mod._get_db('/nowhere/ignored.db') is conn and mod._get_db() is conn
    assert _j(tool, 'create_table', table='clips') == {'status': 'table_ready', 'table': 'clips'}
    assert 'CREATE TABLE IF NOT EXISTS tools."clips"' in _sql(conn)
    assert conn.commits == 1 and conn.closed

    payload = {'id': 'clip-7', 'content': 'a dog on a skateboard', 'metadata': {'src': 'archive'}}
    inserted = _j(tool, 'insert', table='clips', data_json=json.dumps(payload))
    assert inserted == {'status': 'inserted', 'id': 'clip-7', 'table': 'clips'}
    sql, params = conn.statements[-1]
    assert 'INSERT INTO tools."clips"' in sql and 'ON CONFLICT (id)' in sql
    assert params[:2] == ('clip-7', 'a dog on a skateboard') and json.loads(params[2]) == {'src': 'archive'}
    # A dict payload is accepted as-is, and a missing id is invented from the clock.
    invented = _j(tool, 'insert', data_json={'content': 'no id here'})
    assert invented['status'] == 'inserted' and invented['id'].startswith('row_')
    assert conn.statements[-1][1][2] == '{}'


def test_index_storage_query_filter_and_limit_clamp(conn):
    tool = mod.SQLiteIndexStorageTool()
    conn.rows = [{'id': 'a', 'content': 'one'}, {'id': 'b', 'content': 'two'}]
    out = _j(tool, 'query', limit=5)
    assert out['count'] == 2 and out['rows'][1]['id'] == 'b'
    sql, params = conn.statements[0]
    assert 'WHERE' not in sql and sql.endswith('ORDER BY indexed_at DESC LIMIT %s')
    assert params == [5] and conn.row_factory is mod.dict_row
    # The search term and its LIKE wildcards go in the parameter, never in the SQL.
    conn.rows = []
    assert _j(tool, 'query', content_contains="o'brien") == {'count': 0, 'rows': []}
    sql, params = conn.statements[-1]
    assert 'WHERE content LIKE %s' in sql and params == ["%o'brien%", 100]
    # Whatever the caller asks for, the bound LIMIT stays between 1 and 1000.
    for limit, expected in ((0, 1), (-9, 1), (37, 37), (1000, 1000), (99_999, 1000)):
        tool._run('query', limit=limit)
        assert conn.statements[-1][1][-1] == expected


def test_index_storage_delete_unknown_action_bad_table_and_driver_failure(conn):
    tool = mod.SQLiteIndexStorageTool()
    assert _j(tool, 'delete', data_json='{"id": "clip-7"}') == {'status': 'deleted', 'id': 'clip-7'}
    assert conn.statements[0] == ('DELETE FROM tools."content_index" WHERE id=%s', ('clip-7',))
    assert _j(tool, 'delete', data_json={}) == {'error': 'No id provided for delete'}
    assert _j(tool, 'truncate') == {'error': 'Unknown action: truncate'}
    assert len(conn.statements) == 1 and conn.closed
    # A table name that is not a plain identifier never reaches the driver.
    assert 'Invalid table name' in _j(tool, 'create_table', table='clips; DROP TABLE x')['error']
    assert len(conn.statements) == 1

    conn.fail_on = 'INSERT INTO'
    assert _j(tool, 'insert', data_json='{"id": "x"}') == {'error': 'connection lost'}


def test_content_index_query_creates_the_table_then_queries(conn):
    conn.rows = [{'id': 'a', 'content': 'skateboard'}]
    out = _j(mod.ContentIndexDBQueryTool(), search_term='skate', table='clips', limit=3)
    assert out['count'] == 1
    joined = _sql(conn)
    assert 'CREATE TABLE IF NOT EXISTS tools."clips"' in joined and 'WHERE content LIKE %s' in joined
    assert conn.statements[-1][1] == ['%skate%', 3]


def test_asset_index_index_search_remove_unknown_action_and_failure(conn, tmp_path):
    tool = mod.AssetIndexDBTool()
    asset = tmp_path / 'clip.mp4'
    asset.write_bytes(b'0123456789')
    out = _j(tool, 'index', asset_path=str(asset), tags='dogs,funny')
    assert out['status'] == 'indexed' and out['path'] == str(asset) and out['id'].startswith('video_')
    assert conn.statements[-1][1][1:5] == (str(asset), 'video', 'dogs,funny', 10)
    # A path that does not exist is indexed with size 0 rather than raising.
    tool._run('index', asset_path='/nowhere/gone.wav', asset_type='audio')
    assert conn.statements[-1][1][2:5] == ('audio', '', 0)

    conn.rows = [{'id': 'video_1', 'path': '/a.mp4'}, {'id': 'video_2', 'path': '/b.mp4'}]
    found = _j(tool, 'search', asset_path='dogs', asset_type='video')
    assert found['count'] == 2 and found['assets'][0]['id'] == 'video_1'
    sql, params = conn.statements[-1]
    assert 'WHERE type=%s OR tags LIKE %s' in sql and params == ('video', '%dogs%')

    assert _j(tool, 'remove', asset_path='/a.mp4') == {'status': 'removed', 'path': '/a.mp4'}
    assert conn.statements[-1] == ('DELETE FROM tools.asset_index WHERE path=%s', ('/a.mp4',))
    assert _j(tool, 'reindex') == {'error': 'Unknown action: reindex'}

    conn.fail_on = 'CREATE TABLE'
    assert _j(tool, 'search') == {'error': 'connection lost'}
    assert conn.closed


def test_posting_pattern_store_get_and_list(tmp_path):
    store = str(tmp_path / 'patterns.json')
    tool = mod.PlatformPostingPatternDBTool()
    assert _j(tool, 'list', db_path=store) == {'platforms': [], 'data': {}}
    assert _j(tool, 'get', platform='myspace', db_path=store)['pattern'] == {}
    assert _j(tool, 'purge', db_path=store) == {'error': 'Unknown action: purge'}

    stored = _j(tool, 'store', platform='tiktok', pattern_json='{"best_hour": 19}', db_path=store)
    assert stored == {'status': 'stored', 'platform': 'tiktok'}
    # A second store merges into the existing entry instead of replacing it.
    tool._run('store', platform='tiktok', pattern_json={'frequency': 3}, db_path=store)

    pattern = _j(tool, 'get', platform='tiktok', db_path=store)['pattern']
    assert pattern['best_hour'] == 19 and pattern['frequency'] == 3
    assert mod._parse_iso(pattern['updated_at']) is not None
    assert _j(tool, 'list', db_path=store)['platforms'] == ['tiktok']


def test_overlay_template_store_full_cycle(tmp_path):
    store = str(tmp_path / 'templates.json')
    tool = mod.OverlayTemplateStoreTool()
    assert _j(tool, 'list', store_file=store)['count'] == 0
    saved = _j(tool, 'save', template_name='intro', template_path='/t/intro.mov', store_file=store)
    assert saved == {'status': 'saved', 'name': 'intro'}

    got = _j(tool, 'get', template_name='intro', store_file=store)
    assert got['template']['path'] == '/t/intro.mov' and got['template']['type'] == 'overlay'
    assert _j(tool, 'get', template_name='absent', store_file=store)['template'] is None
    assert _j(tool, 'list', store_file=store)['count'] == 1

    assert _j(tool, 'delete', template_name='intro', store_file=store) == {'status': 'deleted'}
    assert _j(tool, 'delete', template_name='intro', store_file=store) == {'status': 'not_found'}
    assert _j(tool, 'rename', store_file=store) == {'error': 'Unknown action: rename'}


def test_music_library_add_search_list_and_remove(tmp_path):
    store = str(tmp_path / 'music.json')
    tool = mod.MusicLibraryManagerTool()
    added = _j(tool, 'add', track_path='/m/calm.mp3', genre='Ambient', bpm=80, store_file=store)
    assert added['status'] == 'added' and added['track']['genre'] == 'Ambient'
    tool._run('add', track_path='/m/rush.mp3', genre='dnb', bpm=174, duration_sec=200, store_file=store)

    assert _j(tool, 'list', store_file=store)['count'] == 2
    by_genre = _j(tool, 'search', genre='ambient', store_file=store)
    assert by_genre['count'] == 1 and by_genre['tracks'][0]['path'] == '/m/calm.mp3'
    assert _j(tool, 'search', bpm=170, store_file=store)['count'] == 1
    assert _j(tool, 'search', store_file=store)['count'] == 2

    removed = _j(tool, 'remove', track_path='/m/calm.mp3', store_file=store)
    assert removed == {'status': 'removed', 'removed_count': 1}
    assert _j(tool, 'remove', track_path='/m/calm.mp3', store_file=store)['removed_count'] == 0
    assert _j(tool, 'shuffle', store_file=store) == {'error': 'Unknown action: shuffle'}


@pytest.fixture
def music_rows(monkeypatch):
    """Stub the manager class the asset store reads through: it calls ``_run('list')`` with no
    ``store_file``, so replacing the class is the only seam that keeps the repo's own library out."""
    tracks = [
        {'path': '/m/calm.mp3', 'genre': 'Ambient', 'bpm': 80},
        {'path': '/m/rush.mp3', 'genre': 'Drum and Bass', 'bpm': 174},
        {'path': '/m/mid.mp3', 'genre': 'house', 'bpm': 124},
    ]

    class StubManager:
        def _run(self, *args, **kwargs):
            return json.dumps({'count': len(tracks), 'tracks': tracks})

    monkeypatch.setattr(mod, 'MusicLibraryManagerTool', StubManager)
    return tracks


@pytest.mark.parametrize(
    ('kwargs', 'expected'),
    [
        ({}, ['/m/calm.mp3', '/m/rush.mp3', '/m/mid.mp3']),
        ({'mood': 'sad'}, ['/m/calm.mp3', '/m/rush.mp3', '/m/mid.mp3']),
        ({'genre': 'bass'}, ['/m/rush.mp3']),
        ({'bpm_min': 100}, ['/m/rush.mp3', '/m/mid.mp3']),
        ({'bpm_max': 130}, ['/m/calm.mp3', '/m/mid.mp3']),
        ({'bpm_min': 100, 'bpm_max': 130}, ['/m/mid.mp3']),
        ({'genre': 'house', 'bpm_min': 200}, []),
    ],
)
def test_music_asset_store_filters(music_rows, kwargs, expected):
    out = _j(mod.MusicLibraryAssetStoreTool(), **kwargs)
    assert [t['path'] for t in out['tracks']] == expected and out['count'] == len(expected)


def test_sfx_library_add_then_list_and_search(tmp_path):
    store = str(tmp_path / 'sfx.json')
    tool = mod.SFXLibraryTool()
    assert _j(tool, store_file=store) == {'count': 0, 'sfx': []}
    added = _j(tool, 'add', sfx_path='/s/whoosh.wav', category='Transition', tags='air,fast', store_file=store)
    assert added['status'] == 'added' and added['sfx']['category'] == 'Transition'
    tool._run('add', sfx_path='/s/thud.wav', category='impact', tags='heavy', store_file=store)

    assert _j(tool, 'list', store_file=store)['count'] == 2
    found = _j(tool, 'search', category='transition', tags='air', store_file=store)
    assert found['count'] == 1 and found['sfx'][0]['path'] == '/s/whoosh.wav'
    assert _j(tool, 'search', store_file=store)['count'] == 2


def test_thumbnail_template_browse_and_update(tmp_path):
    store = str(tmp_path / 'thumbs.json')
    browse, update = mod.ThumbnailTemplateTool(), mod.ThumbnailTemplateUpdaterTool()
    assert _j(browse, store_file=store) == {'count': 0, 'available_styles': [], 'templates': {}}
    assert _j(update, 'bold', '{"font": "Impact"}', store_file=store) == {'status': 'updated', 'style': 'bold'}
    update._run('soft', {'font': 'Georgia'}, store_file=store)

    listed = _j(browse, store_file=store)
    assert listed['count'] == 2 and sorted(listed['available_styles']) == ['bold', 'soft']
    assert _j(browse, style='bold', store_file=store)['template'] == {'font': 'Impact'}
    assert _j(browse, style='neon', store_file=store)['template'] is None


@pytest.mark.parametrize(
    ('platform', 'key', 'value'),
    [
        ('youtube', 'max_duration_sec', 43200),
        ('YouTube', 'monetization_min_subs', 1000),
        ('tiktok', 'max_file_size_mb', 287),
        ('instagram', 'max_duration_sec', 90),
    ],
)
def test_platform_policy_ruleset_known(platform, key, value):
    out = _j(mod.PlatformPolicyRulesetTool(), platform=platform)
    assert out['platform'] == platform and out['policy'][key] == value and 'approximate' in out['note']
    # An unknown platform answers with an empty policy, and the default platform is youtube.
    assert _j(mod.PlatformPolicyRulesetTool(), platform='myspace')['policy'] == {}
    assert _j(mod.PlatformPolicyRulesetTool())['platform'] == 'youtube'


@pytest.mark.parametrize(
    ('platform', 'content_type', 'resolution'),
    [
        ('youtube', 'shorts', '1080x1920'),
        ('youtube', 'long', '1920x1080'),
        ('TikTok', 'anything', '1080x1920'),  # falls back to the platform's 'default' spec
        ('instagram', 'reels', '1080x1920'),
        ('myspace', 'shorts', None),  # unknown platform
        ('instagram', 'stories', None),  # known platform, unknown content type
    ],
)
def test_platform_spec_ruleset(platform, content_type, resolution):
    out = _j(mod.PlatformSpecRulesetTool(), platform=platform, content_type=content_type)
    assert out['platform'] == platform and out['content_type'] == content_type
    assert out['spec'].get('resolution') == resolution
    assert resolution is not None or out['spec'] == {}
    # With no arguments at all the tool answers for youtube shorts.
    default = _j(mod.PlatformSpecRulesetTool())['spec']
    assert default['fps'] == 60 and default['aspect'] == '9:16'


def test_restricted_channel_registry(tmp_path):
    reg = tmp_path / 'restricted.json'
    tool = mod.RestrictedChannelRegistryTool()
    assert _j(tool, registry_file=str(reg)) == {'count': 0, 'restricted_channels': []}
    absent = _j(tool, channel_id='UC_x', registry_file=str(reg))
    assert absent == {'channel_id': 'UC_x', 'restricted': False, 'reason': ''}

    reg.write_text(json.dumps({'UC_bad': {'reason': 'repeat strikes'}, 'UC_other': {}}))
    bad = _j(tool, channel_id='UC_bad', registry_file=str(reg))
    assert bad == {'channel_id': 'UC_bad', 'restricted': True, 'reason': 'repeat strikes'}
    assert _j(tool, channel_id='UC_other', registry_file=str(reg))['reason'] == ''
    assert _j(tool, registry_file=str(reg))['count'] == 2


def test_activation_without_a_registered_agent_warns(registry, tmp_path):
    store = tmp_path / 'activation.json'
    out = _j(mod.AgentActivationControllerTool(), 'activate', agent_name='editor', store_file=str(store))
    assert out['status'] == 'activated' and out['job_id'] is None
    assert 'not in executor registry' in out['warning']
    assert json.loads(store.read_text())['editor']['active'] is True


def test_activation_spawns_a_crew_and_records_the_result(registry, tmp_path):
    _register()
    store = str(tmp_path / 'activation.json')
    tool = mod.AgentActivationControllerTool()
    out = _j(tool, 'activate', agent_name='editor', store_file=store)
    assert out['status'] == 'activated' and 'warning' not in out
    job_id = out['job_id']
    assert isinstance(job_id, str) and len(job_id) == 12

    job = mod.get_active_jobs()[job_id]
    assert job == {'status': 'completed', 'agent': 'editor', 'result': 'crew finished', 'error': None}
    spawned = FakeCrew.instances[-1]
    assert spawned.kwargs['process'] == 'sequential' and spawned.kwargs['verbose'] is True
    assert spawned.kwargs['agents'] == [mod._AGENT_EXECUTOR['editor']]

    status = _j(tool, 'status', agent_name='editor', store_file=store)
    assert status['active'] is True and status['job']['status'] == 'completed'
    assert _j(tool, 'job_status', agent_name=job_id, store_file=store)['result'] == 'crew finished'


def test_activation_task_description_is_override_then_goal_then_a_fallback(registry, tmp_path):
    _register()
    tool = mod.AgentActivationControllerTool()
    tool._run('activate', agent_name='editor', task_override='x' * 2500, store_file=str(tmp_path / 'a.json'))
    tool._run('activate', agent_name='editor', store_file=str(tmp_path / 'b.json'))
    tool._run('activate', agent_name='rigger', store_file=str(tmp_path / 'c.json'))

    override, goal, fallback = (c.kwargs['tasks'][0].description for c in FakeCrew.instances[-3:])
    assert len(override) == 2000
    assert goal == 'Cut the episode down to 90 seconds.'
    assert fallback == 'Execute your pipeline role as rigger.'
    # A crew whose kickoff raises is recorded as a failed job rather than propagated.
    _register(crew_cls=BoomCrew)
    boom = _j(tool, 'activate', agent_name='editor', store_file=str(tmp_path / 'd.json'))
    failed = mod.get_active_jobs()[boom['job_id']]
    assert failed['status'] == 'failed' and failed['result'] is None and failed['error'] == 'llm unreachable'


def test_activation_deactivate_status_list_and_unknown(registry, tmp_path, runtime_dir):
    store = str(tmp_path / 'activation.json')
    tool = mod.AgentActivationControllerTool()
    assert _j(tool, 'deactivate', agent_name='editor', store_file=store) == {
        'status': 'deactivated',
        'agent': 'editor',
    }
    status = _j(tool, 'status', agent_name='editor', store_file=store)
    assert status['active'] is False and status['job_id'] is None and status['job'] is None

    ghost = _j(tool, 'status', agent_name='ghost', store_file=store)
    assert ghost == {'agent': 'ghost', 'active': False, 'updated_at': 'never', 'job_id': None, 'job': None}
    listed = _j(tool, 'list', store_file=store)
    assert listed['count'] == 1 and 'editor' in listed['agents']
    assert _j(tool, 'job_status', agent_name='nope', store_file=store) == {'error': 'No job found with id: nope'}
    assert _j(tool, 'restart', store_file=store) == {'error': 'Unknown action: restart'}

    # With no store_file the tool derives one from the runtime directory.
    tool._run('deactivate', agent_name='editor')
    derived = runtime_dir / 'clipfarm_agent_activation.json'
    assert json.loads(derived.read_text())['editor']['active'] is False


def test_pipeline_status_monitor(tmp_path):
    tool = mod.PipelineStatusMonitorTool()
    assert _j(tool) == {'active_pipelines': 0, 'pipelines': {}}

    store = tmp_path / 'pipeline_status.json'
    store.write_text(json.dumps({'ep-1': {'status': 'rendering'}}))
    assert _j(tool, store_file=str(store))['active_pipelines'] == 1
    known = _j(tool, pipeline_id='ep-1', store_file=str(store))
    assert known == {'pipeline_id': 'ep-1', 'status': {'status': 'rendering'}}
    assert _j(tool, pipeline_id='ep-9', store_file=str(store))['status'] == {'status': 'unknown'}


def _write_schedule(runtime_dir, entries):
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / 'clipfarm_schedule.json').write_text(json.dumps(entries))


def test_schedule_monitor_resolves_interval_entries_and_reports_the_rest(runtime_dir):
    # With no schedule file at all the tool answers 'no_schedule' rather than raising.
    assert _j(mod.ScheduleMonitorTool()) == {'status': 'no_schedule', 'upcoming': [], 'overdue': []}

    created = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    _write_schedule(
        runtime_dir,
        [
            {'id': 'soon', 'active': True, 'type': 'interval', 'interval_seconds': 3600, 'created_at': created},
            {'id': 'far', 'active': True, 'type': 'interval', 'interval_seconds': 86400 * 7, 'created_at': created},
            {'id': 'off', 'active': False, 'type': 'interval', 'interval_seconds': 60, 'created_at': created},
            {'id': 'cron', 'active': True, 'type': 'cron', 'cron': '0 9 * * *', 'created_at': created},
            {'id': 'zero', 'active': True, 'type': 'interval', 'interval_seconds': 0, 'created_at': created},
            {'id': 'undated', 'active': True, 'type': 'interval', 'interval_seconds': 60, 'created_at': 'whenever'},
        ],
    )
    out = _j(mod.ScheduleMonitorTool(), look_ahead_hours=2)

    assert out['total_scheduled'] == 6 and out['look_ahead_hours'] == 2
    assert [u['id'] for u in out['upcoming']] == ['soon']
    assert mod._parse_iso(out['upcoming'][0]['next_run']) is not None
    assert sorted(u['id'] for u in out['unresolved']) == ['cron', 'undated', 'zero']


def test_schedule_monitor_horizon_edges_and_list_caps(runtime_dir):
    past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    entry = {'id': 'soon', 'active': True, 'type': 'interval', 'interval_seconds': 3600, 'created_at': past}
    _write_schedule(runtime_dir, [entry])
    # A negative look-ahead clamps to "now", so nothing is upcoming.
    assert _j(mod.ScheduleMonitorTool(), look_ahead_hours=-5)['upcoming'] == []

    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    _write_schedule(
        runtime_dir,
        [{'id': 'future', 'active': True, 'type': 'interval', 'interval_seconds': 600, 'created_at': future}],
    )
    assert [u['id'] for u in _j(mod.ScheduleMonitorTool())['upcoming']] == ['future']
    # Both answer lists are capped at twenty entries.
    created = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    _write_schedule(
        runtime_dir,
        [
            {'id': f'i{n}', 'active': True, 'type': 'interval', 'interval_seconds': 60, 'created_at': created}
            for n in range(25)
        ]
        + [{'id': f'c{n}', 'active': True, 'type': 'cron', 'created_at': created} for n in range(25)],
    )
    out = _j(mod.ScheduleMonitorTool())
    assert len(out['upcoming']) == 20 and len(out['unresolved']) == 20 and out['total_scheduled'] == 50


def test_failure_monitor_counts_only_recent_dated_failures(runtime_dir, tmp_path):
    # With no audit log the tool reports a quiet window instead of raising.
    assert _j(mod.FailurePatternMonitorTool()) == {'failure_count': 0, 'alert': False, 'window_minutes': 5}

    now = datetime.now(timezone.utc)
    log = tmp_path / 'audit.json'
    log.write_text(
        json.dumps(
            [
                {'action': 'render_ERROR', 'timestamp': (now - timedelta(seconds=10)).isoformat()},
                {'action': 'upload failed', 'timestamp': (now - timedelta(seconds=290)).isoformat()},
                {'action': 'stale_error', 'timestamp': (now - timedelta(hours=3)).isoformat()},
                {'action': 'render_ok', 'timestamp': now.isoformat()},
                {'action': 'FAIL_hard', 'timestamp': 'not-a-date'},
                {'action': 'fail_nostamp'},
            ]
        )
    )
    out = _j(mod.FailurePatternMonitorTool(), log_file=str(log), threshold_failures=5)
    assert out['failure_count'] == 2 and out['threshold'] == 5 and out['alert'] is False
    assert out['undated_failures_skipped'] == 2 and out['window_minutes'] == 5


def test_failure_monitor_alerts_at_the_threshold_and_derives_its_log(runtime_dir, tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    log = tmp_path / 'audit.json'
    log.write_text(json.dumps([{'action': 'step_failed', 'timestamp': now} for _ in range(3)]))
    out = _j(mod.FailurePatternMonitorTool(), log_file=str(log), threshold_failures=3)
    assert out['failure_count'] == 3 and out['alert'] is True

    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / 'clipfarm_audit.json').write_text(json.dumps([{'action': 'oops_error', 'timestamp': now}]))
    assert _j(mod.FailurePatternMonitorTool())['failure_count'] == 1


def test_infrastructure_tools_list_matches_all():
    assert len(mod.INFRASTRUCTURE_TOOLS) == 17
    assert mod.__all__[-1] == 'INFRASTRUCTURE_TOOLS' and 'SQLiteIndexStorageTool' in mod.__all__
    for tool in mod.INFRASTRUCTURE_TOOLS:
        assert tool.name and tool.description
