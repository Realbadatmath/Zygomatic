# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The GET route table of :class:`zyg_dashboard.kanban_server.routes._RoutesMixin`.

``do_GET`` was one 511-line if-ladder. It is now a loop over :data:`DISPATCHERS`,
the ladder's blocks in their original order; each dispatcher answers the request
and returns whatever the handler method returned, or returns :data:`MISS` when
none of its paths matched. ``MISS`` is a sentinel rather than ``None`` because
several branches legitimately answer ``None`` (a client that hung up mid-write).

The blocks are verbatim slices of the old ladder, so the matching order — on
which several prefixes depend, e.g. ``/inspect/api/vfx/fx/`` before
``/inspect/api/vfx/`` — is exactly the order of this module's dispatchers and,
inside each, the order of its ``if`` statements. Nothing here may be reordered.
"""

import os
import re
from urllib.parse import quote as _urlquote

from zyg_dashboard.kanban.common import HERE, _CHARS_ROOT, _OUTPUT_ROOT
from zyg_dashboard.kanban.creatures_series import (
    _api_bakeoffs,
    _api_creatures,
    _api_kids_series,
    _api_medusa_pictures,
    _api_series,
)
from zyg_dashboard.kanban.media_scan import _api_videos, _featured_preview
from zyg_dashboard.kanban.music import _api_kidsmusic, _km_forward, _km_spec
from zyg_dashboard.kanban.review_mesh import (
    _api_char,
    _api_list,
    _api_movement_library,
    _api_movement_objects,
    _api_pictures,
    _GNM_ROOT,
    _gnm_fits,
    _is_medusa_char,
    _MESH_CTYPE,
    _MESH_IMG_RE,
    _MESH_ROOT,
    _mesh_list,
    _mesh_list_scoped,
    _PROP_ROOT,
)
from zyg_dashboard.kanban.sfx_vfx import (
    _api_sfx,
    _api_vfx_assets,
    _MERGE_MOD,
    _MUSIC_MOD,
    _music_studio,
    _sfx_merger,
    _VOICE_MERGE_MOD,
    _vfx_featured_preview,
    _voice_merger,
    _volpv_status,
)
from zyg_dashboard.kanban.studios import (
    _AGENT_MOD,
    _agents,
    _ASSIGN_MOD,
    _STILL_MOD,
    _VIDEO_MOD,
    _video_stills,
    _video_studio,
    _VOICE_MOD,
    _voice_assign,
    _voice_studio,
)

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

#: Returned by a dispatcher that matched none of its paths. A plain ``object()``
#: and not ``None``: ``None`` is a real answer on a dropped connection.
MISS = object()

_TRUTHY = ('1', 'true', 'yes')


def _flag(q, name):
    """True when query parameter ``name`` carries one of 1/true/yes."""
    return q.get(name, '') in _TRUTHY


def send_file_bytes(h, full, cache=None):
    """Read ``full`` and write it whole, content type by extension.

    Answers 404 when the read fails (the file was deleted between the
    containment check and the open, which a running refresh does), ``None``
    when the client hung up mid-write, and otherwise whatever
    ``h.wfile.write`` returned. ``cache``, when given, is sent as
    ``Cache-Control``.
    """
    try:
        with open(full, 'rb') as fh:
            data = fh.read()
    except OSError:
        return h.send_error(404)
    try:
        h.send_response(200)
        h.send_header('Content-Type', _MESH_CTYPE.get(os.path.splitext(full)[1].lower(), 'application/octet-stream'))
        h.send_header('Content-Length', str(len(data)))
        if cache is not None:
            h.send_header('Cache-Control', cache)
        h.end_headers()
        return h.wfile.write(data)
    except (BrokenPipeError, ConnectionResetError):
        return None


def medusa_mesh_allowed(rel):
    """True when mesh path ``rel`` may be served to the Medusa scope.

    Fail-closed cross-scope guard, same shape as ``_serve_image``'s: only
    ``derived/<cid>/...`` paths for a verified Medusa+female character are
    servable. Originals (not tied to any character) and any other character's
    mesh are refused.
    """
    m = re.match(r'^derived/([^/]+)/', rel)
    if not m:
        return False
    mcid = m.group(1)
    rec = (_mesh_list().get('derived') or {}).get(mcid) or {}
    if ((rec.get('params') or {}).get('base') or '') != 'female':
        return False
    return bool(_is_medusa_char(mcid, os.path.join(_CHARS_ROOT, mcid)))


def voice_spec_row(vs, v):
    """One voice of ``/voice/api/spec``, flattened for the picker.

    The row used to emit id/name/role/sex/source ONLY, so any picker built on
    it was blind to age class, to the pre-pubertal VTL caution and to
    reference-only status — all three of which exist and none of which reached
    the client. They ride along now, together with the publication policy, so a
    UI can grey out what must never reach published audio instead of having to
    know the rules itself.
    """
    pol = vs.publication_policy(v) if hasattr(vs, 'publication_policy') else {}
    return {
        'id': v['id'],
        'name': v['name'],
        'role': v['role'],
        'sex': v.get('sex', ''),
        'source': v.get('source', ''),
        'age_class': v.get('age_class', ''),
        'caution_cm': v.get('vtl_caution_cm'),
        'caution_note': v.get('vtl_caution_note', ''),
        'reference_only': bool(v.get('reference_only')),
        # sex is DECLARED by the source, not measured, on every
        # row except the benches that carry a measurement.
        'sex_certain': bool(v.get('sex_certain', v.get('source', '').startswith('bench:'))),
        'licence': v.get(
            'licence',
            vs.SOURCE_LICENCES.get(str(v.get('source', '')).split(':', 1)[0], '')
            if hasattr(vs, 'SOURCE_LICENCES')
            else '',
        ),
        'publishable': pol.get('publishable'),
        'publish_blockers': pol.get('blockers', []),
        # What this voice can be HEARD from without rendering
        # anything. The library board's play button was gated on
        # a baked take; every voice has a seed wav this same
        # server already streams, and a sung bench row -- which
        # can never HAVE a baked take -- has only that.
        'clips': (vs.audition_clips(v) if hasattr(vs, 'audition_clips') else []),
    }


def voice_spec_payload(vs):
    """The whole ``/voice/api/spec`` body: racks, defaults, every voice row."""
    return {
        'racks': vs.RACKS,
        'defaults': vs.defaults(),
        'voices': [voice_spec_row(vs, v) for v in vs.VOICES.values()],
        'singable': sorted(vs.singable_voices()) if hasattr(vs, 'singable_voices') else [],
        # voice-independent, so they ride on the
        # spec rather than on every state call
        'default_lines': vs.DEFAULT_LINES,
        'max_chars': vs.MAX_PREVIEW_CHARS,
    }


def list_still_drops(stills_dir):
    """The start images dropped in ``stills_dir``, newest first.

    Anything an operator (or a workflow's intro step) leaves in the "render
    from a still" drop folder is offered as a start image. Each row carries
    name, the ``out/``-relative path, mtime and the pixel size — 0x0 when
    Pillow is absent or the file is a half-written drop.
    """
    os.makedirs(stills_dir, exist_ok=True)
    try:
        from PIL import Image as _PILImage
    except Exception:  # noqa: BLE001 — size is a nicety, not the list
        _PILImage = None
    stills = []
    for name in os.listdir(stills_dir):
        if not name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            continue
        fp = os.path.join(stills_dir, name)
        if not os.path.isfile(fp):
            continue
        w = h = 0
        if _PILImage is not None:
            try:
                with _PILImage.open(fp) as im:
                    w, h = im.size
            except Exception:  # noqa: BLE001 — a half-written drop
                w = h = 0
        stills.append(
            {
                'name': name,
                'path': f'out/video_studio/_stills/{name}',
                'mtime': os.path.getmtime(fp),
                'w': w,
                'h': h,
            }
        )
    stills.sort(key=lambda s: s['mtime'], reverse=True)
    return stills


def dispatch_inspect_library(h, path):
    """The contact-sheet SPA's read-only API: sheets, characters, images, bakeoffs."""
    if path == '/api/kanban/creature/sheet':
        return h._creature_sheet()
    if path == '/inspect/api/list':
        return h._send_json({'sheets': _api_list(h._query().get('scope', ''))})
    if path.startswith('/inspect/api/char/'):
        return h._cs_get(path)
    if path == '/inspect/api/char':
        q = h._query()
        data = _api_char(q.get('id'), q.get('scope', ''))
        return h._send_json(data) if data else h.send_error(404)
    if path == '/inspect/img':
        return h._serve_image()
    if path == '/inspect/api/videos':
        q = h._query()
        return h._send_json(_api_videos(q.get('scope', ''), intermediates=_flag(q, 'intermediates')))
    if path.startswith('/inspect/api/creature/fx/') or path == '/inspect/creature/fx/frame':
        return h._crfx_get(path)
    if path.startswith('/inspect/api/picture/fx/') or path.startswith('/inspect/picture/fx/'):
        return h._pfx_get(path)
    if path == '/inspect/api/creatures':
        return h._send_json(_api_creatures())
    if path == '/inspect/creature-img':
        return h._creature_img()
    if path == '/inspect/api/pictures':
        return h._send_json(_api_pictures(h._query().get('scope', '')))
    if path == '/inspect/api/medusa/pictures':
        # Every picture Medusa has made, for its own one-card Library.
        return h._send_json(_api_medusa_pictures(h._query().get('scope', '')))
    if path == '/inspect/medusa-img':
        return h._serve_medusa_img()
    if path == '/inspect/api/pictures/edit/job':
        return h._pic_edit_job()
    if path == '/inspect/api/pictures/edit/capability':
        return h._pic_edit_capability()
    if path == '/inspect/api/bakeoffs':
        return h._send_json(_api_bakeoffs())
    return MISS


def dispatch_music_and_movement(h, path):
    """Kids music, kids series and the movement library — most of it forwarded to :5000."""
    if path == '/inspect/api/kidsmusic':
        return h._send_json(_api_kidsmusic(force=_flag(h._query(), 'force')))
    if path == '/inspect/api/kidsmusic/spec':
        return h._send_json(_km_spec())
    if path == '/inspect/api/kidsmusic/status':
        out, code = _km_forward('/api/internal/kidsmusic/status', timeout=10)
        return h._send_json(out, code)
    if path == '/inspect/api/kidseries/status':
        out, code = _km_forward('/api/internal/kidseries/status', timeout=10)
        return h._send_json(out, code)
    if path == '/inspect/kidsmusic/file':
        return h._km_file()
    if path == '/inspect/api/movement/objects':
        return h._send_json(_api_movement_objects())
    if path == '/inspect/api/movement/spec':
        out, code = _km_forward('/api/internal/movement/spec', timeout=15)
        return h._send_json(out, code)
    if path == '/inspect/api/movement/presets':
        out, code = _km_forward('/api/internal/movement/presets', timeout=10)
        return h._send_json(out, code)
    if path == '/inspect/api/movement/status':
        jid = h._query().get('job_id', '')
        out, code = _km_forward('/api/internal/movement/status?job_id=' + _urlquote(jid), timeout=10)
        return h._send_json(out, code)
    if path == '/inspect/api/movement/driver':
        # the POST of this path STARTS a track extraction; this reads its job.json
        jid = h._query().get('job', '')
        out, code = _km_forward('/api/internal/movement/driver?job=' + _urlquote(jid), timeout=10)
        return h._send_json(out, code)
    if path == '/inspect/movement/file':
        return h._mv_file()
    if path == '/inspect/movement/thumb':
        return h._mv_thumb()
    if path == '/inspect/api/movement/library':
        return h._send_json(_api_movement_library(force=_flag(h._query(), 'force')))
    return MISS


def dispatch_vfx_ext_sfx(h, path):
    """The VFX rails, the three extension bundles, the studio bridge and the SFX library."""
    if path == '/inspect/api/vfx/assets':
        return h._send_json(_api_vfx_assets(force=_flag(h._query(), 'force')))
    if path == '/inspect/vfx/asset':
        return h._serve_vfx_asset()
    # Both of these sit BEFORE _vfx_get for the same reason the assets rail
    # does: that helper 503s unless the whole OpenCV/MediaPipe analyzer
    # stack imports, and building a preview needs Blender and ffmpeg, not a
    # CV install.
    if path == '/inspect/api/vfx/volume-preview':
        return h._send_json(_volpv_status(h._query().get('f', '')))
    if path == '/inspect/api/vfx/featured_preview':
        return h._send_json(_vfx_featured_preview())
    if path.startswith('/inspect/api/vfx/fx/') or path == '/inspect/vfx/fx/frame':
        return h._fx_get(path)
    if path.startswith('/inspect/api/vfx/') or path.startswith('/inspect/vfx/'):
        return h._vfx_get(path)
    if path.startswith('/inspect/arch-asset/'):
        return h._serve_arch_asset(path)
    if path == '/arch_ext/bundle.js':
        return h._serve_arch_ext_bundle()
    if path == '/studio_ext/bundle.js':
        return h._serve_studio_ext_bundle()
    if path.startswith('/inspect/api/studio/'):
        return h._studio_ext('GET', path, h._query())
    if path == '/voice_ext/bundle.js':
        return h._serve_voice_ext_bundle()
    if path == '/inspect/api/voice/events':
        return h._voice_bridge_sse()
    if path.startswith('/inspect/api/voice/'):
        return h._voice_bridge('GET', path)
    if path.startswith('/inspect/api/architecture'):
        return h._arch_get(path)
    if path == '/inspect/api/sfx':
        q = h._query()
        # ?extra=instruments — fold a DEFERRED library into this payload.
        # Bare basenames only, and the category still has to exist and be
        # audio, so a junk value costs nothing but its own cache slot.
        ex = [c.strip() for c in (q.get('extra', '') or '').split(',') if c.strip()][:8]
        # Same key _api_sfx caches under, so one memo slot per payload shape.
        return h._send_json(
            _api_sfx(force=_flag(q, 'force'), extra=ex),
            memo_key='sfx|' + ','.join(sorted(set(ex))),
        )
    if path == '/inspect/api/music/spec':
        ms = _music_studio()
        if not ms:
            return h._send_json({'error': f'music studio unavailable: {_MUSIC_MOD["err"]}'}, 503)
        return h._send_json(ms.spec())
    if path == '/inspect/sfx':
        return h._serve_sfx()
    return MISS


def _sfx_merge_get(h, path, mg, q):
    """One read of the SFX merger: its spec, a stored recipe, a stem or an export."""
    if path == '/inspect/api/merge/spec':
        return h._send_json(mg.spec())
    if path == '/inspect/api/merge/recipe':
        r = mg.recipe(q.get('f', ''))
        return (
            h._send_json({'ok': True, 'recipe': r})
            if r
            else h._send_json({'error': 'no recipe stored for that file'}, 404)
        )
    if path == '/inspect/merge/audio':
        fp = mg.resolve_audio(q.get('p', ''))
        # stems and mixes are content-addressed (the name IS the hash
        # of what made them), so the browser may cache freely: the
        # waveform fetch and the <audio> element then share one download
        return h._send_ranged(fp, 'audio/wav', 'public, max-age=86400') if fp else h.send_error(404)
    if path == '/inspect/merge/asset':
        # the analysis pictures and the export renders: same
        # content-addressed work dir, content type by extension, and
        # ?dl= turns it into a download with a human name
        rel = q.get('p', '')
        fp = mg.resolve_audio(rel)
        if not fp:
            return h.send_error(404)
        attach = None
        if q.get('dl'):
            base = re.sub(r'[^A-Za-z0-9 ._-]', '', q.get('dl'))[:80] or 'sfx'
            attach = base + os.path.splitext(rel)[1]
        return h._send_ranged(fp, mg.content_type(rel), 'public, max-age=86400', attach=attach)
    return h.send_error(404)


def _voice_merge_get(h, path, vm, q):
    """One read of the voice merger: its spec, a stored recipe or a stem."""
    if path == '/voice/api/merge/spec':
        return h._send_json(vm.spec())
    if path == '/voice/api/merge/recipe':
        r = vm.recipe(q.get('f', ''))
        return (
            h._send_json({'ok': True, 'recipe': r})
            if r
            else h._send_json({'error': 'no recipe stored for that file'}, 404)
        )
    if path == '/voice/merge/audio':
        fp = vm.resolve_audio(q.get('p', ''))
        return h._send_ranged(fp, 'audio/wav', 'public, max-age=86400') if fp else h.send_error(404)
    return h.send_error(404)


def dispatch_merge(h, path):
    """The two mergers (SFX and voice): 503 when the module is absent, 400 on a hostile query."""
    if path.startswith('/inspect/api/merge/') or path == '/inspect/merge/audio' or path == '/inspect/merge/asset':
        mg = _sfx_merger()
        if not mg:
            return h._send_json({'error': f'sfx merger unavailable: {_MERGE_MOD["err"]}'}, 503)
        try:
            return _sfx_merge_get(h, path, mg, h._query())
        except Exception as e:  # noqa: BLE001 - a hostile query string must 4xx, not traceback
            _zyg_log.info(f'[KANBAN-SERVER] merge GET error on {path}: {e!r}')
            return h._send_json({'error': f'{type(e).__name__}: {e}'[:300]}, 400)
    if path.startswith('/voice/api/merge/') or path == '/voice/merge/audio':
        vm = _voice_merger()
        if not vm:
            return h._send_json({'error': f'voice merger unavailable: {_VOICE_MERGE_MOD["err"]}'}, 503)
        try:
            return _voice_merge_get(h, path, vm, h._query())
        except Exception as e:  # noqa: BLE001 - a hostile query string must 4xx, not traceback
            _zyg_log.info(f'[KANBAN-SERVER] voice merge GET error on {path}: {e!r}')
            return h._send_json({'error': f'{type(e).__name__}: {e}'[:300]}, 400)
    return MISS


def dispatch_media_files(h, path):
    """Media, downloads, thumbnails and previews served off disk."""
    if path == '/inspect/media':
        return h._serve_media()
    if path == '/inspect/download':
        return h._serve_download()
    if path == '/inspect/thumb':
        return h._serve_thumb()
    if path == '/inspect/preview':
        return h._serve_preview()
    if path == '/inspect/api/featured_preview':
        return h._send_json(_featured_preview())
    return MISS


def dispatch_voice(h, path):
    """Everything under ``/voice/``: the studio spec, its jobs and its audio."""
    if not path.startswith('/voice/'):
        return MISS
    vs = _voice_studio()
    if not vs:
        return h._send_json({'error': f'voice studio unavailable: {_VOICE_MOD["err"]}'}, 503)
    q = h._query()
    if path == '/voice/api/spec':
        return h._send_json(voice_spec_payload(vs))
    if path == '/voice/api/prerender':
        return h._send_json(vs.prerender_state(q.get('voice', ''), q.get('text', '')))
    if path == '/voice/api/bake':
        return h._send_json(vs.library_status())
    if path == '/voice/api/assign':
        va = _voice_assign()
        if not va:
            return h._send_json({'error': f'assignments unavailable: {_ASSIGN_MOD["err"]}'}, 503)
        vid = q.get('voice', '')
        if not vs.voice(vid):
            return h.send_error(404)
        view = va.view(vid, vs.VOICES)
        # The button's badge only needs the two numbers. The full view is
        # ~53 KB, and arrow-keying the 244-voice rail would pull it per
        # voice for a count nobody has opened the panel to read.
        if _flag(q, 'counts'):
            return h._send_json({'voice': view['voice'], 'counts': view['counts']})
        return h._send_json(view)
    if path == '/voice/api/state':
        st = vs.studio_state(q.get('voice', ''))
        return h._send_json(st) if st else h.send_error(404)
    if path == '/voice/api/job':
        j = vs.job(q.get('id', ''))
        return h._send_json(j) if j else h.send_error(404)
    if path == '/voice/audio':
        fp = vs.resolve_audio(q.get('p', ''))
        # no-store: a preview wav is rewritten per render under a fresh
        # job id, but preset wavs keep their path across an overwrite
        mime = 'audio/mpeg' if str(fp).lower().endswith('.mp3') else 'audio/wav'
        return h._send_ranged(fp, mime, 'no-store') if fp else h.send_error(404)
    return h.send_error(404)


def dispatch_video(h, path):
    """Everything under ``/video/``: the studio spec, its jobs, stills and presets."""
    if not path.startswith('/video/'):
        return MISS
    vd = _video_studio()
    if not vd:
        return h._send_json({'error': f'video studio unavailable: {_VIDEO_MOD["err"]}'}, 503)
    q = h._query()
    if path == '/video/api/spec':
        # actions ride along with the racks: the Video Studio bars are
        # icon strips, and an action icon (Render, Inject, Preset) sits
        # in the same strip as a parameter icon — one spec, one layout.
        return h._send_json({'racks': vd.RACKS, 'actions': vd.ACTIONS, 'defaults': vd.defaults()})
    if path == '/video/api/job':
        j = vd.job(q.get('id', ''))
        return h._send_json(j) if j else h.send_error(404)
    if path == '/video/api/jobs':
        return h._send_json({'jobs': vd.jobs()})
    # Exact-match routes, so '/video/api/still' (one generation job) and
    # '/video/api/stills' (the drop-folder listing) never shadow.
    if path == '/video/api/still':
        vst = _video_stills()
        if not vst:
            return h._send_json({'error': f'still generation unavailable: {_STILL_MOD["err"]}'}, 503)
        j = vst.job(q.get('id', ''))
        return h._send_json(j) if j else h.send_error(404)
    if path == '/video/api/still/jobs':
        vst = _video_stills()
        if not vst:
            return h._send_json({'error': f'still generation unavailable: {_STILL_MOD["err"]}'}, 503)
        return h._send_json({'jobs': vst.jobs()})
    if path == '/video/api/stills':
        sd = os.path.join(_OUTPUT_ROOT, 'video_studio', '_stills')
        return h._send_json({'stills': list_still_drops(sd)})
    if path == '/video/api/presets':
        return h._send_json({'presets': vd.presets()})
    return h.send_error(404)


def dispatch_kanban_api(h, path):
    """The board's own JSON: the two series rails and the agent-session panel."""
    if path == '/kanban/api/series':
        return h._send_json(_api_series())
    if path == '/kanban/api/kids_series':
        return h._send_json(_api_kids_series())
    if path == '/kanban/api/agents':
        aa = _agents()
        if not aa:
            return h._send_json(
                {
                    'ok': False,
                    'error': _AGENT_MOD['err'],
                    'sessions': [],
                    'events': [],
                    'count': 0,
                    'active': 0,
                    'seq': 0,
                },
                200,
            )
        try:
            since = int(h._query().get('since', '0') or 0)
        except ValueError:
            since = 0
        return h._send_json(aa.snapshot(since=since))
    if path == '/kanban/api/agents/tail':
        aa = _agents()
        if not aa:
            return h._send_json({'error': _AGENT_MOD['err'], 'lines': []}, 200)
        q = h._query()
        try:
            lim = max(20, min(400, int(q.get('limit', '140') or 140)))
        except ValueError:
            lim = 140
        out = aa.session_tail(q.get('id', ''), lim)
        return h._send_json(out, 400 if out.get('error') else 200)
    return MISS


def dispatch_mesh_images(h, path):
    """The garment-fit and skeleton/prop mesh renders, each behind its own containment check."""
    if path == '/gnm/api/fits':
        return h._send_json(_gnm_fits())
    if path == '/gnm/img':
        rel = h._query().get('p', '')
        if not _MESH_IMG_RE.match(rel) or '..' in rel:
            return h.send_error(400)
        full = os.path.realpath(os.path.join(_GNM_ROOT, rel))
        if not full.startswith(_GNM_ROOT + os.sep) or not os.path.isfile(full):
            return h.send_error(404)
        return send_file_bytes(h, full, cache='no-cache')
    if path == '/mesh/api/list':
        return h._send_json(_mesh_list_scoped(h._query().get('scope', '')))
    if path == '/mesh/img':
        q = h._query()
        rel = q.get('p', '')
        if not _MESH_IMG_RE.match(rel) or '..' in rel:
            return h.send_error(400)
        # root=props addresses the prop/creature registry instead of the skeleton
        # tree. It is a SEPARATE base dir with its own containment check rather
        # than a path prefix inside _MESH_ROOT: a prefix is a string, and a string
        # is exactly what traversal attacks are made of.
        if q.get('root', '') == 'props':
            if q.get('scope', '') == 'medusa':
                return h.send_error(404)
            full = os.path.realpath(os.path.join(_PROP_ROOT, rel))
            if not full.startswith(_PROP_ROOT + os.sep) or not os.path.isfile(full):
                return h.send_error(404)
            return send_file_bytes(h, full)
        if q.get('scope', '') == 'medusa' and not medusa_mesh_allowed(rel):
            return h.send_error(404)
        full = os.path.realpath(os.path.join(_MESH_ROOT, rel))
        if not full.startswith(_MESH_ROOT + os.sep) or not os.path.exists(full):
            return h.send_error(404)
        return send_file_bytes(h, full)
    return MISS


def dispatch_medusa_assets(h, path):
    """The two fixed Medusa video paths: the mane loop and the page backdrop.

    Each is served from ONE fixed path rather than by adding '.mp4' to
    _STATIC_OK_EXT: HERE is the crews SOURCE tree and the listener is on
    0.0.0.0, so that one line would publish every mp4 under it — the identity
    benches, the face-restore receipts, the documentary intermediates.
    _send_ranged already speaks Range/206, which is what a <video> asks for,
    and the cache lifetime is explicit because these routes do not pass through
    _NO_CACHE_EXT (the page busts them with MDZ_V instead).

    The backdrop is NOT the drawing: it is an LTX-2.5 30 s seamless loop,
    pre-blurred in ffmpeg (sigma 28) and shrunk to 512 px, so the page does not
    pay for a full-screen CSS blur on every frame and the file stays ~0.5 MB.
    The mane loop is untouched — the board itself still shows only the artist's
    own pixels (kanban_assets/medusa/README_loop.md).
    """
    names = {'/medusa/loop.mp4': 'medusa_loop.mp4', '/medusa/backdrop.mp4': 'medusa_backdrop.mp4'}
    if path not in names:
        return MISS
    fp = os.path.join(HERE, 'kanban_assets', 'medusa', names[path])
    if not os.path.isfile(fp):
        return h.send_error(404)
    return h._send_ranged(fp, 'video/mp4', 'public, max-age=86400')


#: The old if-ladder's blocks, in the order they were written. ``do_GET`` tries
#: each in turn and answers with the first one that does not return :data:`MISS`.
DISPATCHERS = (
    dispatch_inspect_library,
    dispatch_music_and_movement,
    dispatch_vfx_ext_sfx,
    dispatch_merge,
    dispatch_media_files,
    dispatch_voice,
    dispatch_video,
    dispatch_kanban_api,
    dispatch_mesh_images,
    dispatch_medusa_assets,
)
