# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Flask routes: simulation, schematics, production queue, creator and benchmark."""

import json
import logging as _zyg_logging
import re
import threading
import time
from pathlib import Path

from flask import Response, abort, jsonify, request, send_file

import schem_io
import schem_model
import schem_prims
import schem_store
from schem_compiler import compile_schematic
from zyg_dashboard.cors import apply_cors
from zyg_workflows.paths import tmp_dir

from . import HUB_DIR
from .benchmark import (
    _bench_lock,
    _bench_state,
    _run_benchmark_bg,
    get_installed_games,
)
from .config import LAN_HOST_PLACEHOLDER, RECORDINGS_DIR, app, lan_host
from .queue_engine import _queue, _queue_lock, _queue_uid, _save_queue_locked
from .schematics import (
    BUILD_FP_GAME,
    BUILTIN_SCHEMATIC_IDS,
    SCHEMATICS,
    SCHEM_COLUMN_IDS,
    _load_schem_columns,
    _read_build_status,
    _schem_lock,
    _set_schem_column,
    _write_schematic_file,
)
from .sim_state import FOLDER_TO_GAME, _sim_lock, _sim_state, _start_sim_bg, _stop_sim
from .ui import HTML

_zyg_log = _zyg_logging.getLogger(__name__)


@app.route('/favicon.ico')
def favicon():
    return send_file(HUB_DIR / 'gamesim_favicon.ico', mimetype='image/png')


@app.route('/')
def index():
    page = HTML.replace(LAN_HOST_PLACEHOLDER, lan_host())
    return Response(page, content_type='text/html; charset=utf-8', headers={'Cache-Control': 'no-store'})


@app.route('/api/installed')
def api_installed():
    data = json.dumps(get_installed_games())
    resp = Response(data, content_type='application/json', headers={'Cache-Control': 'no-store'})
    return apply_cors(resp, request)


@app.route('/api/simulate/start', methods=['POST'])
def api_sim_start():
    body = request.get_json(silent=True) or {}
    games = body.get('games', [])
    if not games:
        return jsonify({'ok': False, 'error': 'No games specified'})
    if _sim_state.get('running'):
        return jsonify({'ok': False, 'error': 'Simulation already running — stop it first'})
    threading.Thread(target=_start_sim_bg, args=(games,), daemon=True).start()
    return jsonify({'ok': True, 'count': len(games)})


@app.route('/api/simulate/stop', methods=['POST'])
def api_sim_stop():
    status = _read_build_status()
    _stop_sim()
    # A manually-run schematic that finished gets promoted to "Built"
    if status and status.get('complete') and status.get('schematic') in SCHEMATICS:
        _set_schem_column(status['schematic'], 'built')
    return jsonify({'ok': True})


# ── Schematics API ───────────────────────────────────────────────────────
@app.route('/api/schematics')
def api_schematics():
    with _schem_lock:
        cols = _load_schem_columns()
    with _queue_lock:
        pending = [i['schematic'] for i in _queue['items'] if i['status'] in ('queued', 'running')]
    out = []
    for s in SCHEMATICS.values():
        d = dict(s)
        d['column'] = cols.get(s['id'], 'backlog')
        d['queued_count'] = pending.count(s['id'])
        out.append(d)
    return jsonify(out)


@app.route('/api/schematics/column', methods=['POST'])
def api_schematics_column():
    body = request.get_json(silent=True) or {}
    sid, col = body.get('id'), body.get('column')
    if sid not in SCHEMATICS or col not in SCHEM_COLUMN_IDS:
        return jsonify({'ok': False, 'error': 'Bad schematic or column'})
    _set_schem_column(sid, col)
    return jsonify({'ok': True})


@app.route('/api/schematics/run', methods=['POST'])
def api_schematics_run():
    body = request.get_json(silent=True) or {}
    sid = body.get('id')
    schem = SCHEMATICS.get(sid)
    if not schem:
        return jsonify({'ok': False, 'error': 'Unknown schematic'})
    with _queue_lock:
        busy = _queue['state'] == 'playing' or _queue['current_uid']
    if busy:
        return jsonify({'ok': False, 'error': 'Production list is running — pause or stop it first'})
    if _sim_state.get('running'):
        return jsonify({'ok': False, 'error': 'A simulation is already running — stop it first'})
    _write_schematic_file(schem)
    threading.Thread(target=_start_sim_bg, args=([BUILD_FP_GAME],), daemon=True).start()
    _set_schem_column(sid, 'inproduction')
    return jsonify({'ok': True, 'schematic': sid})


# ── Production queue API ────────────────────────────────────────────────
@app.route('/api/queue')
def api_queue():
    progress = _read_build_status()
    with _queue_lock:
        items = []
        for i in _queue['items']:
            s = SCHEMATICS.get(i['schematic'], {})
            items.append(
                {
                    **i,
                    'name': s.get('name', i['schematic']),
                    'block_count': s.get('block_count', 0),
                    'est_minutes': s.get('est_minutes', 0),
                    'category': s.get('category', ''),
                }
            )
        state = _queue['state']
        current = _queue['current_uid']
    return jsonify(
        {
            'state': state,
            'current_uid': current,
            'items': items,
            'progress': progress,
            'sim_running': bool(_sim_state.get('running')),
        }
    )


@app.route('/api/queue/add', methods=['POST'])
def api_queue_add():
    sid = (request.get_json(silent=True) or {}).get('id')
    if sid not in SCHEMATICS:
        return jsonify({'ok': False, 'error': 'Unknown schematic'})
    with _queue_lock:
        _queue_uid[0] += 1
        uid = f'q{int(time.time())}_{_queue_uid[0]}'
        _queue['items'].append({'uid': uid, 'schematic': sid, 'status': 'queued', 'added_at': time.time()})
        _save_queue_locked()
    return jsonify({'ok': True, 'uid': uid})


@app.route('/api/queue/remove', methods=['POST'])
def api_queue_remove():
    uid = (request.get_json(silent=True) or {}).get('uid')
    with _queue_lock:
        item = next((i for i in _queue['items'] if i['uid'] == uid), None)
        if not item:
            return jsonify({'ok': False, 'error': 'Not found'})
        if item['status'] == 'running':
            return jsonify({'ok': False, 'error': 'Item is building — stop the list first'})
        _queue['items'].remove(item)
        _save_queue_locked()
    return jsonify({'ok': True})


@app.route('/api/queue/move', methods=['POST'])
def api_queue_move():
    body = request.get_json(silent=True) or {}
    uid, direction = body.get('uid'), body.get('dir')
    with _queue_lock:
        idx = next((n for n, i in enumerate(_queue['items']) if i['uid'] == uid), None)
        if idx is None:
            return jsonify({'ok': False, 'error': 'Not found'})
        swap = idx - 1 if direction == 'up' else idx + 1
        if swap < 0 or swap >= len(_queue['items']):
            return jsonify({'ok': False, 'error': 'Cannot move further'})
        items = _queue['items']
        items[idx], items[swap] = items[swap], items[idx]
        _save_queue_locked()
    return jsonify({'ok': True})


@app.route('/api/queue/clear_done', methods=['POST'])
def api_queue_clear_done():
    with _queue_lock:
        _queue['items'] = [i for i in _queue['items'] if i['status'] in ('queued', 'running')]
        _save_queue_locked()
    return jsonify({'ok': True})


@app.route('/api/queue/play', methods=['POST'])
def api_queue_play():
    with _queue_lock:
        has_queued = any(i['status'] == 'queued' for i in _queue['items'])
        current = _queue['current_uid']
    if not has_queued and not current:
        return jsonify({'ok': False, 'error': 'Production list is empty — queue a build first'})
    if _sim_state.get('running') and not current:
        return jsonify({'ok': False, 'error': 'A manual simulation is running — stop it first'})
    with _queue_lock:
        _queue['state'] = 'playing'
        _save_queue_locked()
    return jsonify({'ok': True})


@app.route('/api/queue/pause', methods=['POST'])
def api_queue_pause():
    with _queue_lock:
        if _queue['state'] == 'playing':
            _queue['state'] = 'paused'
            _save_queue_locked()
    return jsonify({'ok': True})


@app.route('/api/queue/stop', methods=['POST'])
def api_queue_stop():
    with _queue_lock:
        _queue['state'] = 'stopped'
        _save_queue_locked()
    return jsonify({'ok': True})


# ── Schematic Creator API ───────────────────────────────────────────────
# Every authoring front-end (parametric ops, layer painting, fork, .schem import,
# world capture) is a thin producer of one block list. They all funnel through
# compile_schematic(), which is the only thing that decides what the bot can
# actually build.


def _palette():
    """Building blocks worth offering: giveable, full-cube, and with a real
    colour sampled from the game's own textures."""
    out = []
    for name, b in schem_model.blocks().items():
        if not b['give'] or not b['full'] or not b.get('color'):
            continue
        if name.endswith(('_spawn_egg', '_command_block')) or name in ('air',):
            continue
        out.append({'n': name, 'c': b['color'], 'd': b.get('display') or name})
    out.sort(key=lambda m: m['n'])
    return out


def _oriented_palette():
    """Stairs/slabs/doors — the blocks that make a build look designed rather
    than extruded. bot.js places them and straightens them via RCON."""
    groups = {'stairs': [], 'slabs': [], 'doors': []}
    for name, b in schem_model.blocks().items():
        if not b['give'] or not b.get('color'):
            continue
        if name.endswith('_stairs'):
            groups['stairs'].append({'n': name, 'c': b['color']})
        elif name.endswith('_slab'):
            groups['slabs'].append({'n': name, 'c': b['color']})
        elif name.endswith('_door'):
            groups['doors'].append({'n': name, 'c': b['color']})
    for g in groups.values():
        g.sort(key=lambda m: m['n'])
    return groups


@app.route('/api/creator/catalog')
def api_creator_catalog():
    return jsonify(
        {
            'ops': schem_prims.describe(),
            'palette': _palette(),
            'oriented': _oriented_palette(),
            'model': {
                'ground_y': schem_model.GROUND_Y,
                'base_y': schem_model.BASE_Y,
                'reach_range': schem_model.REACH_RANGE,
                'reach_ceiling': 5,
                'zone': {
                    'x0': schem_model.ZONE_X0,
                    'x1': schem_model.ZONE_X1,
                    'z0': schem_model.ZONE_Z0,
                    'z1': schem_model.ZONE_Z1,
                },
                'spawn': schem_model.BOT_SPAWN,
            },
            'builtins': sorted(BUILTIN_SCHEMATIC_IDS),
        }
    )


def _bake(body):
    """ops → blocks, or take raw blocks. Raises ValueError with a usable message."""
    ops = body.get('ops')
    if ops:
        return schem_prims.bake(ops), ops
    blocks = body.get('blocks') or []
    return blocks, body.get('source', {}).get('ops')


@app.route('/api/creator/compile', methods=['POST'])
def api_creator_compile():
    """Bake + prove, without saving. This is what the Creator tab calls on every
    edit, so it must stay fast and never mutate anything."""
    body = request.get_json(silent=True) or {}
    try:
        blocks, _ = _bake(body)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)})
    if not blocks:
        return jsonify({'ok': False, 'error': 'Nothing to build yet — add an op.'})
    if len(blocks) > 4000:
        return jsonify(
            {'ok': False, 'error': f'{len(blocks)} blocks is beyond what this rig will build in a session (max 4000).'}
        )
    compiled, report = compile_schematic(blocks, auto_scaffold=bool(body.get('scaffold', True)))
    return jsonify(
        {
            'ok': True,
            'report': report,
            # Preview shows the source blocks plus any synthesised scaffold, so the
            # user sees exactly what would get built.
            'blocks': compiled if compiled else blocks + report.get('scaffold', []),
            'certified': report['certified'],
        }
    )


@app.route('/api/creator/save', methods=['POST'])
def api_creator_save():
    body = request.get_json(silent=True) or {}
    name = (body.get('name') or '').strip()
    if not name:
        return jsonify({'ok': False, 'error': 'Give the build a name'})
    try:
        blocks, ops = _bake(body)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)})
    if not blocks:
        return jsonify({'ok': False, 'error': 'Nothing to save'})

    compiled, report = compile_schematic(blocks, auto_scaffold=bool(body.get('scaffold', True)))
    if not report['certified'] and not body.get('force'):
        return jsonify(
            {
                'ok': False,
                'error': f'Not buildable yet — the bot cannot reach {report["stats"].get("unbuilt", "?")} block(s)',
                'report': report,
            }
        )
    final = compiled if compiled else blocks

    sid = body.get('id')
    if sid in BUILTIN_SCHEMATIC_IDS:
        return jsonify({'ok': False, 'error': 'Cannot overwrite a built-in — save under a new name'})
    if not sid:
        sid = schem_store.slugify(name, taken=set(SCHEMATICS))

    rec = schem_store.make_record(
        sid,
        name,
        body.get('desc') or 'Created in the Schematic Creator.',
        body.get('category') or 'Custom',
        body.get('difficulty') or 'medium',
        final,
        source={'ops': ops} if ops else {'kind': body.get('origin') or 'voxels'},
        report=report,
        scaffold=report.get('scaffold'),
        origin=body.get('origin') or 'creator',
    )
    schem_store.save(rec)
    SCHEMATICS[sid] = rec
    _set_schem_column(sid, body.get('column') or 'ready')
    return jsonify({'ok': True, 'id': sid, 'report': report})


@app.route('/api/creator/delete', methods=['POST'])
def api_creator_delete():
    sid = (request.get_json(silent=True) or {}).get('id')
    if sid in BUILTIN_SCHEMATIC_IDS:
        return jsonify({'ok': False, 'error': 'Built-in schematics cannot be deleted'})
    with _queue_lock:
        if any(i['schematic'] == sid and i['status'] in ('queued', 'running') for i in _queue['items']):
            return jsonify({'ok': False, 'error': 'It is in the production list — remove it there first'})
    if not schem_store.delete(sid):
        return jsonify({'ok': False, 'error': 'Not found'})
    SCHEMATICS.pop(sid, None)
    return jsonify({'ok': True})


@app.route('/api/creator/fork', methods=['POST'])
def api_creator_fork():
    """Open an existing schematic as an editable draft — the fastest way in."""
    sid = (request.get_json(silent=True) or {}).get('id')
    s = SCHEMATICS.get(sid)
    if not s:
        return jsonify({'ok': False, 'error': 'Unknown schematic'})
    ops = (s.get('source') or {}).get('ops')
    return jsonify(
        {
            'ok': True,
            'name': s['name'] + ' copy',
            'desc': s.get('desc', ''),
            'category': s.get('category', 'Custom'),
            'difficulty': s.get('difficulty', 'medium'),
            # Built-ins are Python generators with no recipe, so they fork as painted
            # cells — still fully editable, just not parametric.
            'ops': ops or [{'op': 'voxels', 'params': {'blocks': s['blocks']}}],
            'parametric': bool(ops),
        }
    )


@app.route('/api/creator/import', methods=['POST'])
def api_creator_import():
    """Import a Sponge .schem the user supplies.

    User-supplied files only — we deliberately do not bundle or fetch community
    catalogues: Planet Minecraft and minecraft-schematics.com leave copyright with
    the original author and grant downloaders no reuse licence.
    """
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'No file uploaded'})
    tmp = tmp_dir('hub') / ('hub_import_' + re.sub(r'[^A-Za-z0-9_.-]', '_', f.filename))
    f.save(str(tmp))
    try:
        data = schem_io.import_schem(str(tmp))
    except schem_io.IOError_ as exc:
        return jsonify({'ok': False, 'error': str(exc)})
    finally:
        try:
            tmp.unlink()
        except OSError as _exc:
            _zyg_log.debug('upload temp %s not removed: %s', tmp, _exc)

    blocks, changes = schem_io.cubify(data['blocks'], schem_model.block_info)
    dropped = [c[0] for c in changes if c[1] is None]
    swapped = {c[0]: c[1] for c in changes if c[1]}
    return jsonify(
        {
            'ok': True,
            'blocks': blocks,
            'size': data['size'],
            'imported': len(data['blocks']),
            'kept': len(blocks),
            'dropped': sorted(set(dropped)),
            'swapped': swapped,
            'name': Path(f.filename).stem.replace('_', ' ').title(),
        }
    )


@app.route('/api/creator/capture', methods=['POST'])
def api_creator_capture():
    """Capture a hand-built region from the live build server.

    The natural authoring tool: a human building in survival stays within reach,
    leaves doorways, and uses materials they can see — so captures pass the
    compiler far more often than imports from the wild do.
    """
    body = request.get_json(silent=True) or {}
    frm = body.get('from') or [-6, 65, -12]
    to = body.get('to') or [6, 78, -2]
    try:
        data = schem_io.capture_region(frm, to, port=int(body.get('port', 25567)))
    except schem_io.IOError_ as exc:
        return jsonify({'ok': False, 'error': str(exc)})
    blocks = schem_io.clean_capture(data['blocks'])
    if not blocks:
        return jsonify({'ok': False, 'error': "Nothing found in that region (the pad's grass floor is ignored)."})
    return jsonify({'ok': True, 'blocks': blocks, 'scanned': data['scanned'], 'captured': len(blocks)})


@app.route('/api/creator/export/<sid>')
def api_creator_export(sid):
    """Export as a Sponge .schem so a build opens in WorldEdit or Litematica."""
    s = SCHEMATICS.get(sid)
    if not s:
        abort(404)
    out = tmp_dir('hub') / f'{sid}.schem'
    try:
        schem_io.export_schem(s['blocks'], str(out))
    except schem_io.IOError_ as exc:
        return jsonify({'ok': False, 'error': str(exc)})
    return send_file(str(out), as_attachment=True, download_name=f'{sid}.schem')


@app.route('/api/creator/lint')
def api_creator_lint():
    """Dev endpoint: prove every schematic in the registry, built-ins included."""
    out = []
    for sid, s in SCHEMATICS.items():
        _, rep = compile_schematic(s['blocks'], auto_scaffold=False)
        out.append(
            {
                'id': sid,
                'certified': rep['certified'],
                'blocks': rep['block_count'],
                'stats': rep['stats'],
                'ms': rep['ms'],
                'unbuilt': [u['pos'] for u in rep['unbuilt'][:5]],
            }
        )
    return jsonify(out)


@app.route('/api/simulate/status')
def api_sim_status():
    with _sim_lock:
        state = {
            'running': _sim_state['running'],
            'started_at': _sim_state['started_at'],
            'instances': [
                {k: v for k, v in inst.items() if k not in ('xvfb_pid', 'game_pid', 'ffmpeg_pid')}
                | {'xvfb_pid': inst['xvfb_pid'], 'game_pid': inst['game_pid'], 'ffmpeg_pid': inst['ffmpeg_pid']}
                for inst in _sim_state['instances']
            ],
        }
    return jsonify(state)


@app.route('/api/benchmark/start', methods=['POST'])
def api_bench_start():
    with _bench_lock:
        if _bench_state['running']:
            return jsonify({'ok': False, 'error': 'Benchmark already running'})
    body = request.get_json(silent=True) or {}
    duration = max(10, min(300, int(body.get('duration', 30))))
    threading.Thread(target=_run_benchmark_bg, args=(duration,), daemon=True).start()
    return jsonify({'ok': True, 'duration': duration, 'games': get_installed_games()})


@app.route('/api/benchmark/stop', methods=['POST'])
def api_bench_stop():
    with _bench_lock:
        _bench_state['running'] = False
        _bench_state['phase'] = 'idle'
        gp = _bench_state.pop('game_proc', None)
    if gp and gp.poll() is None:
        try:
            import os as _os
            import signal as _sig

            _os.killpg(_os.getpgid(gp.pid), _sig.SIGTERM)
        except Exception:
            try:
                gp.terminate()
            except Exception as _exc:
                _zyg_log.warning('benchmark game pid %s could not be stopped, it may still run: %s', gp.pid, _exc)
    return jsonify({'ok': True})


@app.route('/api/benchmark/status')
def api_bench_status():
    _SKIP = {'game_proc', 'debug_log'}
    with _bench_lock:
        snap = {k: v for k, v in _bench_state.items() if k not in _SKIP}
    return jsonify(snap)


@app.route('/api/benchmark/results')
def api_bench_results():
    with _bench_lock:
        return jsonify(_bench_state.get('results', []))


@app.route('/api/benchmark/debug')
def api_bench_debug():
    with _bench_lock:
        return jsonify({'lines': list(_bench_state.get('debug_log', []))})


@app.route('/api/recordings')
def api_recordings():
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(r'^(.+)_inst(\d+)_(\d+)\.mp4$')
    results = []
    for f in sorted(RECORDINGS_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.suffix.lower() != '.mp4':
            continue
        m = pattern.match(f.name)
        folder = m.group(1) if m else f.stem
        instance = int(m.group(2)) if m else 1
        ts = int(m.group(3)) if m else int(f.stat().st_mtime)
        game = FOLDER_TO_GAME.get(folder, folder.replace('_', ' ').title())
        size_mb = round(f.stat().st_size / (1024 * 1024), 1)
        results.append(
            {
                'filename': f.name,
                'game': game,
                'folder': folder,
                'instance': instance,
                'ts': ts,
                'size_mb': size_mb,
            }
        )
    return jsonify(results)


@app.route('/recordings/<path:filename>')
def serve_recording(filename):
    path = RECORDINGS_DIR / filename
    if not path.exists() or not path.is_file():
        abort(404)
    return send_file(str(path), mimetype='video/mp4', conditional=True)


@app.route('/api/frames/<folder_name>')
def api_frames_list(folder_name):
    """Return sorted list of JPEG filenames for a frames capture folder."""
    folder_name = Path(folder_name).name  # strip any traversal
    fdir = RECORDINGS_DIR / folder_name
    if not fdir.is_dir():
        return jsonify([])
    return jsonify(sorted(f.name for f in fdir.glob('*.jpg')))


@app.route('/frames/<folder_name>/<filename>')
def serve_frame(folder_name, filename):
    """Serve a single JPEG frame from a frames capture folder."""
    folder_name = Path(folder_name).name
    filename = Path(filename).name
    path = RECORDINGS_DIR / folder_name / filename
    if not path.exists() or not path.is_file():
        abort(404)
    return send_file(str(path), mimetype='image/jpeg')


@app.route('/api/recordings/<path:filename>', methods=['DELETE'])
def delete_recording(filename):
    path = RECORDINGS_DIR / filename
    if not path.exists():
        return jsonify({'ok': False, 'error': 'Not found'})
    path.unlink()
    return jsonify({'ok': True})
