# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Static files, the inspection API envelope and every media reader.

Split verbatim out of ``kanban_server.py`` (lines 114-536) on 2026-10-06, when that
3,172-line module became this package. The bodies are byte-for-byte the originals;
only the enclosing ``class`` line is new. :class:`zyg_dashboard.kanban_server._Handler`
puts the mixins back together in their original order, so the MRO finds every method
exactly where the single class had it.
"""

import os
import json
import hashlib
import gzip


# ── the sections, split into zyg_dashboard.kanban/ (2026-10-06) ──────────────
# Imported back by name so the handler below can go on calling them bare and
# `zyg_dashboard.kanban_server.<name>` keeps resolving for every outside caller.
from zyg_dashboard.kanban.common import _zyg_log, _FFMPEG, PORT, HERE, _CHARS_ROOT, _RUNTIME  # noqa: F401
from zyg_dashboard.kanban.common import _OUTPUT_ROOT, _DATA_OUTPUT_ROOT, _DATA_RUNTIME_ROOT  # noqa: F401
from zyg_dashboard.kanban.common import _MEDIA_ROOTS  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _CREATURE_ROOT, _CREATURE_ID_RE, _VFX_MAX_UPLOAD  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _REC_MAX_UPLOAD, _MAIN_APP, _internal_token, _MEDIA_MIME  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _MEDIA_PATH_RE, _CATS, _CAT_LABELS, _CAT_ORDER, _ID_RE  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _NAME_RE, _IMG_MIME, _LIST_CACHE, _NAME_CACHE, _MESH_ROOT  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _MESH_CACHE, _MESH_IMG_RE, _MESH_CTYPE, _mesh_list  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _PROP_ROOT, _PROP_CACHE, _prop_mesh_list, _MV_OUT_ROOT  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _MV_JOB_ID_RE, _api_movement_objects, _MV_CACHE  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _MV_CACHE_TTL, _api_movement_library, _GNM_ROOT, _GNM_CACHE  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _gnm_fits, _MESH_JOBS, _MESH_PY, _MESH_JOB_ID_RE  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _MESH_HASH_RE, _MESH_LOCK, _MESH_RUNNING, _MESH_JOBS_MEM  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _MESH_DRYRUN_OK, _mesh_names, _mesh_parse_hashes  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _MESH_VERDICT_RE, _mesh_parse_verdict, _mesh_job_run  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _mesh_job_start, _mesh_list_scoped, _safe_char_dir  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _display_name, _FACET_CACHE, _char_facets, _runtime_status  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _manifest_qc, _list_images, _MEDUSA_IDS_CACHE  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _medusa_id_set, _is_medusa_char, _api_list_all, _api_list  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _api_char, _api_pictures  # noqa: F401
from zyg_dashboard.kanban.creatures_series import _MEDUSA_STILL_DIR, _medusa_still_side  # noqa: F401
from zyg_dashboard.kanban.creatures_series import _medusa_still_path, _api_medusa_pictures  # noqa: F401
from zyg_dashboard.kanban.creatures_series import _CREATURE_OUT_ROOT, _CREATURE_CATS, _CREATURE_LICENCE  # noqa: F401
from zyg_dashboard.kanban.creatures_series import _FLUX1_FAMILIES, _FLUX1_BLOCK_NOTE, _is_flux1  # noqa: F401
from zyg_dashboard.kanban.creatures_series import _creature_manifest, _HUMANISH, _val_prompt  # noqa: F401
from zyg_dashboard.kanban.creatures_series import _creature_dir, _creature_weights, _creature_job  # noqa: F401
from zyg_dashboard.kanban.creatures_series import _creature_images, _api_creatures, _api_bakeoffs  # noqa: F401
from zyg_dashboard.kanban.creatures_series import _api_series, _KS_MOD, _ks_common, _api_kids_series  # noqa: F401
from zyg_dashboard.kanban.media_scan import _VID_SKIP_TOP, _VID_SKIP_PREFIX, _VID_DL_CUT_RE  # noqa: F401
from zyg_dashboard.kanban.media_scan import _VID_TMP_SEGS, _VID_PREV_SEG_RE, _VID_TMP_FILE_RE  # noqa: F401
from zyg_dashboard.kanban.media_scan import _VID_SMOKE_JOB_RE, _VID_SMOKE_JOB_STRICT_RE  # noqa: F401
from zyg_dashboard.kanban.media_scan import _VID_SMOKE_MARKER, _vid_is_test_job, _VID_GROUPS, _VID_CACHE  # noqa: F401
from zyg_dashboard.kanban.media_scan import _VID_CACHE_TTL, _THUMB_DIR, _THUMB_SEM, _THUMB_W  # noqa: F401
from zyg_dashboard.kanban.media_scan import _thumb_path, _PREVIEW_DIR, _PREVIEW_REG, _PREVIEW_SEM  # noqa: F401
from zyg_dashboard.kanban.media_scan import _PREVIEW_W, _PREVIEW_MAX_S, _PREVIEW_CACHE  # noqa: F401
from zyg_dashboard.kanban.media_scan import _preview_registry, _featured_preview, _preview_path  # noqa: F401
from zyg_dashboard.kanban.media_scan import _make_preview, _SUBBURN_DIR, _SUBBURN_SEM, _SUBBURN_STYLE  # noqa: F401
from zyg_dashboard.kanban.media_scan import _SUBBURN_VENC, _subburn_path, _make_subburn, _make_thumb  # noqa: F401
from zyg_dashboard.kanban.media_scan import _IMG_THUMB_DIR, _IMG_THUMB_W, _img_thumb_path  # noqa: F401
from zyg_dashboard.kanban.media_scan import _make_img_thumb, _vid_group, _api_videos  # noqa: F401
from zyg_dashboard.kanban.sfx_vfx import _ALIB_MOD, _ALIB_EXT_MIME, _ALIB_CACHE, _ALIB_CACHE_TTL  # noqa: F401
from zyg_dashboard.kanban.sfx_vfx import _ALIB_DEFER_MIN, _ALIB_PROBE, _ALIB_LOCK, _ALIB_TAKE_RE  # noqa: F401
from zyg_dashboard.kanban.sfx_vfx import _ALIB_CAT_DESC, _alib, _alib_probe, _alib_ai_state, _api_sfx  # noqa: F401
from zyg_dashboard.kanban.sfx_vfx import _VFXA_MOD, _VFXA_CACHE, _VFXA_CACHE_TTL, _VFXA_LOCK  # noqa: F401
from zyg_dashboard.kanban.sfx_vfx import _VFXA_EXT_MIME, _vfxa, _api_vfx_assets, _VFXFX_MOD, _vfxfx  # noqa: F401
from zyg_dashboard.kanban.sfx_vfx import _CRFX_MOD, _crfx, _PFX_MOD, _pfx, _fx_stack_arg  # noqa: F401
from zyg_dashboard.kanban.sfx_vfx import _vfx_featured_preview, _VOLPV_JOBS, _VOLPV_LOCK, _volpv_worker  # noqa: F401
from zyg_dashboard.kanban.sfx_vfx import _volpv_start, _volpv_status, _MERGE_MOD, _sfx_merger  # noqa: F401
from zyg_dashboard.kanban.sfx_vfx import _MUSIC_MOD, _music_studio, _VOICE_MERGE_MOD, _voice_merger  # noqa: F401
from zyg_dashboard.kanban.studios import _AGENT_MOD, _agents, _VFX_MOD, _vfx, _ARCH_MOD, _arch  # noqa: F401
from zyg_dashboard.kanban.studios import _CSTUDIO_MOD, _cstudio, _VOICE_MOD, _voice_studio, _VIDEO_MOD  # noqa: F401
from zyg_dashboard.kanban.studios import _video_studio, _STILL_MOD, _video_stills, _ASSIGN_MOD  # noqa: F401
from zyg_dashboard.kanban.studios import _voice_assign  # noqa: F401
from zyg_dashboard.kanban.music import _KM_ROOTS, _KM_ROOT, _KM_ID_RE, _KM_CACHE, _KM_CACHE_TTL  # noqa: F401
from zyg_dashboard.kanban.music import _KM_FILES, _KM_FRAME_RE, _km_dir, _km_root_of, _KM_DL_LEG  # noqa: F401
from zyg_dashboard.kanban.music import _KM_FAMILIES, _KM_SHELF_OK, _KM_DEFAULT_FAMILY  # noqa: F401
from zyg_dashboard.kanban.music import _KM_FALLBACK_SHELF, _KM_FIRST_SHELF, _KM_STORY_RE  # noqa: F401
from zyg_dashboard.kanban.music import _KM_SLEEPY_MOODS, _km_derive_shelf, _km_shelf_of, _km_file_song  # noqa: F401
from zyg_dashboard.kanban.music import _km_download_name, _KS_DIR_RE, _km_series, _api_kidsmusic  # noqa: F401
from zyg_dashboard.kanban.music import _KM_SPEC_MOD, _km_theory, _km_spec, _km_forward, _pe_forward  # noqa: F401
from zyg_dashboard.kanban.http_cache import _JSON_GZ, _JSON_GZ_MAX, _JSON_GZ_MIN, _JSON_GZ_LOCK  # noqa: F401
from zyg_dashboard.kanban.http_cache import _JSON_MEMO, _STATIC_GZ, _STATIC_GZ_LOCK, _STATIC_GZ_TYPES  # noqa: F401
from zyg_dashboard.kanban.http_cache import _gz_cached  # noqa: F401


class _StaticFilesMixin:
    # 2026-09-05: the stdlib default is HTTP/1.0, which closes the connection
    # after EVERY response — so a thumbnail grid opened one TCP connection per
    # tile and left one TIME-WAIT socket behind per tile (measured: 84 of them
    # after 60 requests). Keep-alive is safe here because every response in this
    # file sets Content-Length: _send_json, _send_ranged, the mesh and thumb
    # writers, and SimpleHTTPRequestHandler's own static path all do.
    protocol_version = 'HTTP/1.1'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=HERE, **kwargs)

    # 2026-08-01: .js/.css were NOT in this list, and that is a real bug, not a
    # tidy-up. SimpleHTTPRequestHandler sends Last-Modified but no Cache-Control,
    # so browsers HEURISTICALLY cache those assets. kanban.html revalidated on
    # every load while kanban_main.js did not, which is how an open dashboard ran
    # a stale script for an hour: the poll kept pulling fresh JSON from :5000, so
    # the header text updated with the new backend while the board logic — and the
    # TEMPLATES object holding the new second_ledger board — stayed at the old
    # revision. Clicking 'Active: Second Ledger' then switched to a board the
    # cached script did not have, silently fell back to documentary, and rendered
    # every card 'queued'. The ?v= query bump cannot save a page that never
    # reloads. no-cache still allows 304s, so this costs a conditional GET, not a
    # re-download.
    _NO_CACHE_EXT = ('.html', '.js', '.css')

    def end_headers(self):
        if self.path.split('?', 1)[0].endswith(self._NO_CACHE_EXT):
            self.send_header('Cache-Control', 'no-cache, must-revalidate')
        super().end_headers()

    def log_message(self, fmt, *args):
        _zyg_log.info(f'[KANBAN-SERVER] {self.address_string()} - {fmt % args}')

    # ── inspection API ─────────────────────────────────────────────────────
    def _send_json(self, obj, code=200, memo_key=''):
        """One JSON response, conditional and compressed. See the comment on
        _JSON_GZ for why: the tabs re-poll on a 5 s clock, so the common case by
        far is a payload the caller already holds, and that case must not cost a
        re-send."""
        # Serialising is not free at this size: json.dumps of the instruments
        # payload measures 82 ms and the hash another 61 ms, and until the bytes
        # were remembered that was paid on EVERY poll — including the 304s that
        # send nothing. memo_key opts an endpoint into keeping them. The cached
        # payload is one long-lived object, so object identity is the test: the
        # same object means the same bytes, and a rebuild makes a new one.
        memo = _JSON_MEMO.get(memo_key) if memo_key else None
        if memo is not None and memo[0] is obj:
            body, etag = memo[1], memo[2]
        else:
            body = json.dumps(obj).encode('utf-8')
            etag = '"%s"' % hashlib.blake2b(body, digest_size=16).hexdigest()
            if memo_key:
                if len(_JSON_MEMO) >= _JSON_GZ_MAX:
                    _JSON_MEMO.clear()
                _JSON_MEMO[memo_key] = (obj, body, etag)
        # The poll already holds this exact payload: answer with no body.
        if code == 200 and self.headers.get('If-None-Match') == etag:
            self.send_response(304)
            self.send_header('ETag', etag)
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        enc = ''
        if code == 200 and len(body) >= _JSON_GZ_MIN and 'gzip' in (self.headers.get('Accept-Encoding') or '').lower():
            body, enc = _gz_cached(etag, body), 'gzip'
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        # no-cache, NOT no-store. They read alike and are opposites here:
        # no-store forbids the browser from keeping the copy it would revalidate
        # against, which would make the ETag above dead weight. no-cache keeps
        # the copy and requires revalidation before every use — still never
        # serving anything stale, but now able to answer 304.
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('ETag', etag)
        if enc:
            self.send_header('Content-Encoding', enc)
            self.send_header('Vary', 'Accept-Encoding')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError as _exc:
            _zyg_log.debug('client closed the connection before the body was sent: %s', _exc)

    # Everything that reaches the static fall-through is served straight off
    # disk from HERE — which is the crews SOURCE tree. Until 2026-09-06 that
    # meant GET / returned a browsable index of it on 0.0.0.0: every .py, every
    # .bak-* copy, agent_configurations.json. The pages need six kinds of file
    # (measured by loading all sixteen tabs and recording what they asked for);
    # this is an allowlist rather than a denylist because the failure mode of a
    # missed pattern has to be a 404, not a source leak.
    _STATIC_OK_EXT = frozenset(
        (
            '.html',
            '.js',
            '.css',
            '.map',
            '.png',
            '.jpg',
            '.jpeg',
            '.gif',
            '.svg',
            '.webp',
            '.ico',
            '.woff',
            '.woff2',
            '.ttf',
            '.otf',
        )
    )

    def _static_allowed(self, path):
        parts = [p for p in path.split('/') if p]
        # dotfiles and the .bak_*/.adv_*/.anthro_* backup DIRECTORIES
        if any(p.startswith('.') for p in parts):
            return False
        if os.path.splitext(path)[1].lower() not in self._STATIC_OK_EXT:
            return False
        # A .bak-<tag> copy usually fails the extension test on its own
        # (inspection.html.bak-perf-20260905 ends in '.bak-perf-20260905'), but
        # a name that puts the marker in the middle would not.
        return '.bak' not in os.path.basename(path).lower()

    def list_directory(self, path):
        """No index of anything, ever. Belt to _static_allowed's braces: a
        directory URL has no extension and is already refused, and this makes
        certain that no future route can reintroduce a listing."""
        self.send_error(404)
        return None

    def _serve_static_gz(self, path):
        """Compressed answer for a static text asset, or False to let
        SimpleHTTPRequestHandler serve it uncompressed. inspection.html is the
        reason this exists — 1.9 MB served no-cache on every page load, 547 KB
        once gzipped. Returns True if it answered the request."""
        ctype = _STATIC_GZ_TYPES.get(os.path.splitext(path)[1].lower())
        if not ctype:
            return False
        if 'gzip' not in (self.headers.get('Accept-Encoding') or '').lower():
            return False
        fp = self.translate_path(self.path)
        try:
            st = os.stat(fp)
        except OSError:
            return False
        if not os.path.isfile(fp):
            return False
        key = (st.st_mtime, st.st_size)
        with _STATIC_GZ_LOCK:
            hit = _STATIC_GZ.get(fp)
        if not hit or hit[0] != key:
            try:
                with open(fp, 'rb') as fh:
                    raw = fh.read()
            except OSError:
                return False
            hit = (key, gzip.compress(raw, 6))
            with _STATIC_GZ_LOCK:
                _STATIC_GZ[fp] = hit
        gz = hit[1]
        etag = '"%x-%x"' % (int(st.st_mtime), st.st_size)
        if self.headers.get('If-None-Match') == etag:
            self.send_response(304)
            self.send_header('ETag', etag)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return True
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Encoding', 'gzip')
        self.send_header('Vary', 'Accept-Encoding')
        self.send_header('ETag', etag)
        self.send_header('Content-Length', str(len(gz)))
        self.end_headers()
        try:
            self.wfile.write(gz)
        except (BrokenPipeError, ConnectionResetError) as _exc:
            _zyg_log.debug('client closed the connection before the gzip body was sent: %s', _exc)
        return True

    def _query(self):
        from urllib.parse import parse_qs, urlparse

        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    def _serve_image(self):
        q = self._query()
        cid, cat, name = q.get('id'), q.get('cat'), q.get('name')
        char_dir = _safe_char_dir(cid)
        if not char_dir or cat not in _CATS or not name or not _NAME_RE.match(name):
            self.send_error(404)
            return
        # Fail-closed cross-scope guard (mirrors _api_char): a default-scope image
        # request for a medusa char, or a medusa-scope request for a non-medusa
        # char, 404s. Keeps medusa images out of the default view and vice versa.
        if _is_medusa_char(cid, char_dir) != (q.get('scope', '') == 'medusa'):
            self.send_error(404)
            return
        if os.path.basename(name) != name:
            self.send_error(404)
            return
        sub, _ = _CATS[cat]
        cat_dir = os.path.realpath(os.path.join(char_dir, sub))
        fp = os.path.realpath(os.path.join(cat_dir, name))
        # final realpath must stay inside the category dir inside the char dir
        if not (fp.startswith(cat_dir + os.sep) and cat_dir.startswith(char_dir) and os.path.isfile(fp)):
            self.send_error(404)
            return
        self._send_image_thumb_or_full(fp, q.get('thumb') == '1')

    def _serve_medusa_img(self):
        """One Medusa chat picture — thumb=1 for a grid card, otherwise the
        original PNG. Scope-guarded and sidecar-guarded the same way
        /inspect/img is: without scope=medusa, and for any still this app did
        not make, there is nothing here to fetch."""
        q = self._query()
        if q.get('scope', '') != 'medusa':
            return self.send_error(404)
        fp = _medusa_still_path(q.get('name', ''))
        if not fp:
            return self.send_error(404)
        return self._send_image_thumb_or_full(fp, q.get('thumb') == '1')

    def _send_image_thumb_or_full(self, fp, want_thumb):
        """Serve `fp` — a small cached JPEG when want_thumb is set (grid cards),
        the original bytes otherwise (lightbox/zoom). Both call sites have
        already validated fp lies inside its allowed root. The thumb variant
        gets a long Cache-Control since its cache key already carries the
        source's mtime; the original keeps the short one it always had."""
        ext = os.path.splitext(fp)[1].lower()
        if want_thumb and ext in _IMG_MIME:
            try:
                mt = os.path.getmtime(fp)
            except OSError:
                mt = None
            tp = _img_thumb_path(fp, mt, _IMG_THUMB_W) if mt is not None else None
            if tp and (os.path.isfile(tp) or _make_img_thumb(fp, tp, _IMG_THUMB_W)):
                try:
                    with open(tp, 'rb') as fh:
                        data = fh.read()
                except OSError:
                    tp = None
                if tp:
                    self.send_response(200)
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', str(len(data)))
                    self.send_header('Cache-Control', 'public, max-age=3600')
                    self.end_headers()
                    try:
                        self.wfile.write(data)
                    except BrokenPipeError as _exc:
                        _zyg_log.debug('client closed the connection before the thumb was sent: %s', _exc)
                    return
        try:
            with open(fp, 'rb') as fh:
                data = fh.read()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', _IMG_MIME.get(ext, 'application/octet-stream'))
        self.send_header('Cache-Control', 'public, max-age=30')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError as _exc:
            _zyg_log.debug('client closed the connection before the image was sent: %s', _exc)

    def _resolve_media_path(self, rel=None):
        """Validate a '<rootkey>/<relpath>' media path and return an absolute
        file path, or None. Defaults to reading ?path= off the current
        request (the /inspect/media and /inspect/thumb use); passing rel
        explicitly lets a POST body value (e.g. /video/api/render's injected
        source clip) go through the same extension whitelist, per-root
        realpath containment and medusa block instead of a second check."""
        if rel is None:
            rel = self._query().get('path', '')
        if not rel or rel.startswith('/') or '..' in rel or not _MEDIA_PATH_RE.match(rel):
            return None
        head, _, tail = rel.partition('/')
        root, sub = (_MEDIA_ROOTS[head], tail) if (head in _MEDIA_ROOTS and tail) else (_OUTPUT_ROOT, rel)
        if not sub or 'medusa' in sub.lower():
            return None
        fp = os.path.realpath(os.path.join(root, sub))
        if not (fp.startswith(root + os.sep) and os.path.isfile(fp)):
            return None
        return fp

    def _serve_thumb(self):
        """Small cached JPEG poster for one video (or image). Extract-once, then
        served from disk. Never blocks on more than _THUMB_SEM extractions."""
        fp = self._resolve_media_path()
        if not fp:
            return self.send_error(404)
        try:
            mt = os.path.getmtime(fp)
        except OSError:
            return self.send_error(404)
        tp = _thumb_path(fp, mt)
        if not os.path.isfile(tp):
            with _THUMB_SEM:
                if not os.path.isfile(tp) and not _make_thumb(fp, tp):
                    return self.send_error(404)
        try:
            with open(tp, 'rb') as fh:
                body = fh.read()
        except OSError:
            return self.send_error(404)
        self.send_response(200)
        self.send_header('Content-Type', 'image/jpeg')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'public, max-age=86400')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError) as _exc:
            _zyg_log.debug('client closed the connection before the poster was sent: %s', _exc)

    def _serve_preview(self):
        """The short silent hover cut for one clip. Built once, then served
        from disk like the poster is.

        Only a clip named in the preview registry has one: an unregistered
        path 404s rather than falling back to some auto-chosen segment, so a
        card can never hover-play a moment nobody picked."""
        q = self._query()
        rel = q.get('path', '')
        ent = _preview_registry().get(rel)
        if not ent:
            return self.send_error(404)
        fp = self._resolve_media_path()
        if not fp or not fp.lower().endswith('.mp4'):
            return self.send_error(404)
        try:
            mt = os.path.getmtime(fp)
        except OSError:
            return self.send_error(404)
        dst = _preview_path(fp, mt, ent['start'], ent['end'])
        if not os.path.isfile(dst):
            with _PREVIEW_SEM:
                if not os.path.isfile(dst) and not _make_preview(fp, dst, ent['start'], ent['end']):
                    return self.send_error(404)
        return self._send_ranged(dst, 'video/mp4', 'public, max-age=86400')

    def _serve_download(self):
        """Save-to-disk copy of one clip, with or without captions burnt in.

        `subs=burn` returns the hardsubbed copy (built once, then cached);
        anything else returns the delivered file untouched. Either way it is
        sent as an attachment so the browser saves rather than navigates."""
        fp = self._resolve_media_path()
        if not fp or not fp.lower().endswith('.mp4'):
            return self.send_error(404)
        stem = os.path.splitext(os.path.basename(fp))[0]
        name = stem + '.mp4'
        if self._query().get('subs', '') == 'burn':
            srt = os.path.splitext(fp)[0] + '.srt'
            if not os.path.isfile(srt):
                return self.send_error(404)
            try:
                mt = max(os.path.getmtime(fp), os.path.getmtime(srt))
            except OSError:
                return self.send_error(404)
            out = _subburn_path(fp, mt)
            if not os.path.isfile(out):
                with _SUBBURN_SEM:
                    if not os.path.isfile(out) and not _make_subburn(fp, srt, out):
                        return self.send_error(500)
            fp, name = out, f'{stem}_subtitled.mp4'
        return self._send_ranged(fp, 'video/mp4', cache='no-store', attach=name)

    def _serve_sfx(self):
        """Stream one registered library sample (?cat=<audio category>&f=<basename>)
        with Range support. Containment: the category must be an AUDIO library
        the service knows, the name must be a bare basename with a whitelisted
        extension, and the realpath must sit inside that library's dir — the
        _originals/ masters and everything else on disk stay unreachable."""
        als = _alib()
        if not als:
            return self.send_error(503)
        q = self._query()
        cat, fn = q.get('cat', ''), q.get('f', '')
        info = als._CATEGORIES.get(cat)
        if not info or info.get('kind') != 'audio':
            return self.send_error(404)
        if not fn or os.path.basename(fn) != fn or fn.startswith('.'):
            return self.send_error(404)
        mime = _ALIB_EXT_MIME.get(os.path.splitext(fn)[1].lower())
        if not mime:
            return self.send_error(404)
        root = os.path.realpath(als._audio_dir(cat))
        fp = os.path.realpath(os.path.join(root, fn))
        if not (fp.startswith(root + os.sep) and os.path.isfile(fp)):
            return self.send_error(404)
        return self._send_ranged(fp, mime)

    def _serve_vfx_asset(self):
        """Stream one VFX library file (?cat=<vfx category>&f=<basename>) with
        Range support, so a plate can seek in the preview pane. Same containment
        contract as _serve_sfx: the category must be one vfx_ingest declares,
        the name a bare basename with a whitelisted extension, and the realpath
        must sit inside that library dir — the _originals/ masters (31 GB of VDB
        archives and the MPEG-2 films) stay unreachable through this route."""
        vi = _vfxa()
        if not vi:
            return self.send_error(503)
        q = self._query()
        cat, fn = q.get('cat', ''), q.get('f', '')
        if cat not in vi.CATEGORIES:
            return self.send_error(404)
        if not fn or os.path.basename(fn) != fn or fn.startswith('.'):
            return self.send_error(404)
        mime = _VFXA_EXT_MIME.get(os.path.splitext(fn)[1].lower())
        if not mime:
            return self.send_error(404)
        root = os.path.realpath(os.path.join(vi.LIBS, cat))
        fp = os.path.realpath(os.path.join(root, fn))
        if not (fp.startswith(root + os.sep) and os.path.isfile(fp)):
            return self.send_error(404)
        return self._send_ranged(fp, mime, 'public, max-age=3600')
