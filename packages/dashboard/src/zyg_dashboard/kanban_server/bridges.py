# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Studio extension bundles, the voice bridge, ranged media and the deleters.

Split verbatim out of ``kanban_server.py`` (lines 825-1112) on 2026-10-06, when that
3,172-line module became this package. The bodies are byte-for-byte the originals;
only the enclosing ``class`` line is new. :class:`zyg_dashboard.kanban_server._Handler`
puts the mixins back together in their original order, so the MRO finds every method
exactly where the single class had it.
"""

import os
import re
from urllib.parse import unquote as _urlunquote


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


class _BridgesMixin:
    # ── Architecture Studio extensions (2026-09-06) ────────────────────────
    # arch_ext/*.js are geometry/label/opening registrations for kinds the
    # studio did not ship with. They are served as ONE bundle, concatenated in
    # name order behind a preamble that defines the AR_EXT registry, so a new
    # family is a new FILE and never an edit of inspection.html. No caching:
    # an executor drops a file and reloads.
    def _serve_arch_ext_bundle(self):
        import glob as _glob

        parts = [
            '/* arch_ext bundle — generated per request */',
            'window.AR_EXT = window.AR_EXT || {geom:{}, label:{}, openings:{}, ready:[],'
            ' tools:{}, modes:{}, snaps:[], matHooks:[], ticks:[], resizes:[], keys:{}, sections:[], render:null};',
        ]
        for f in sorted(_glob.glob(os.path.join(HERE, 'arch_ext', '*.js'))):
            try:
                with open(f, encoding='utf-8') as fh:
                    parts.append(
                        f'/* ── {os.path.basename(f)} ── */\ntry {{\n'
                        + fh.read()
                        + f'\n}} catch (e) {{ console.error("arch_ext {os.path.basename(f)}", e); }}'
                    )
            except OSError as e:
                parts.append(f'console.error("arch_ext {os.path.basename(f)} unreadable: {e}");')
        body = '\n'.join(parts).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/javascript; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── Studio extensions (2026-09-18) ────────────────────────────────────
    # The same seam as arch_ext above, but for the character/creature/movement
    # studios: studio_ext/*.js are wrapped page extensions, concatenated in name
    # order behind a preamble that defines the SX registry. The page loads this
    # bundle AFTER its own script block, so a file here may wrap or replace any
    # page global. Names starting with '_' are docs, not code, and are skipped.
    def _serve_studio_ext_bundle(self):
        import glob as _glob

        parts = ['/* studio_ext bundle — generated per request */', 'window.SX = window.SX || {ready:[]};']
        for f in sorted(_glob.glob(os.path.join(HERE, 'studio_ext', '*.js'))):
            if os.path.basename(f).startswith('_'):
                continue
            try:
                with open(f, encoding='utf-8') as fh:
                    parts.append(
                        f'/* ── {os.path.basename(f)} ── */\ntry {{\n'
                        + fh.read()
                        + f'\n}} catch (e) {{ console.error("studio_ext {os.path.basename(f)}", e); }}'
                    )
            except OSError as e:
                parts.append(f'console.error("studio_ext {os.path.basename(f)} unreadable: {e}");')
        body = '\n'.join(parts).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/javascript; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── Voice bridge (2026-09-15) ──────────────────────────────────────────
    # /inspect/api/voice/*  -> voice_bridge.py (the microphone seam). NOTE the
    # prefix: /voice/api/* already belongs to Voice Studio and is a different
    # subsystem. voice_ext/*.js are the per-studio action registrations, served
    # as ONE bundle exactly like arch_ext above.
    def _serve_voice_ext_bundle(self):
        try:
            from zyg_workflows import voice_bridge

            body = voice_bridge.bundle_js().encode('utf-8')
        except Exception as e:  # noqa: BLE001
            body = (
                'window.VB = window.VB || {actions:{}, aliases:{}, ready:[], views:{}};\n'
                'console.error("voice_ext bundle unavailable: %s");' % str(e).replace('"', "'")[:200]
            ).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/javascript; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError) as _exc:
            _zyg_log.debug('client closed the connection before the voice bundle was sent: %s', _exc)

    def _voice_bridge(self, method, path):
        try:
            from zyg_workflows import voice_bridge
        except Exception as e:  # noqa: BLE001
            return self._send_json({'error': f'voice bridge unavailable: {e}'}, 503)
        try:
            if method == 'GET':
                res = voice_bridge.handle_get(path, self._query())
            else:
                res = voice_bridge.handle_post(path, self._json_body(limit=voice_bridge.BODY_LIMIT))
        except Exception as e:  # noqa: BLE001
            _zyg_log.info(f'[KANBAN-SERVER] voice bridge {method} {path}: {e!r}')
            return self._send_json({'error': str(e)[:300]}, 500)
        # An ext op may answer with (bytes, mime, filename) — a rendered wav,
        # most often — which is sent raw rather than wrapped in JSON.
        if isinstance(res, tuple) and len(res) == 3:
            data, mime, fname = res
            if not isinstance(data, (bytes, bytearray)):
                data = str(data).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', mime or 'application/octet-stream')
            if fname:
                self.send_header('Content-Disposition', 'attachment; filename="%s"' % str(fname).replace('"', ''))
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError) as _exc:
                _zyg_log.debug('client closed the connection before the voice payload was sent: %s', _exc)
            return None
        out, code = res
        return self._send_json(out, code)

    # Held open for hours by the driver tab. Safe here only because _Server is
    # threading with daemon threads: this occupies one thread, not the loop.
    def _voice_bridge_sse(self):
        try:
            from zyg_workflows import voice_bridge
        except Exception as e:  # noqa: BLE001
            return self._send_json({'error': f'voice bridge unavailable: {e}'}, 503)
        try:
            return voice_bridge.handle_sse(self, self._query())
        except Exception as e:  # noqa: BLE001
            _zyg_log.info(f'[KANBAN-SERVER] voice bridge sse: {e!r}')
            return None

    def _serve_arch_asset(self, path):
        """Stream one mesh-pack file for the Architecture Studio viewport.

        PATH-BASED (/inspect/arch-asset/<pack>/<file>) and not a query string,
        because a .gltf names its .bin and its textures by RELATIVE uri: the
        browser resolves those against this document's own URL, so a query
        string would send the loader after `?pack=x&scene.bin`. Containment,
        the traversal check and the extension allowlist all live in
        architecture_assets.resolve_url — including for the sidecars, which the
        catalogue never listed and which therefore need the fence most."""
        try:
            from zyg_workflows import architecture_assets as aa
        except Exception:
            return self.send_error(503)
        try:
            rel = _urlunquote(path[len('/inspect/arch-asset/') :])
        except Exception:
            return self.send_error(404)
        fp = aa.resolve_url(rel)
        if not fp:
            return self.send_error(404)
        # Immutable: a pack file is content the ingest hashed and never edits
        # in place, so the browser may keep it for a day.
        return self._send_ranged(fp, aa.mime_for(fp), 'public, max-age=86400')

    def _serve_media(self):
        """Serve one file under output/ (mp4/png/…) with HTTP Range support so <video> can
        stream and seek. Strict path containment; only whitelisted extensions."""
        fp = self._resolve_media_path()
        if not fp:
            return self.send_error(404)
        mime = _MEDIA_MIME.get(os.path.splitext(fp)[1].lower())
        if not mime:
            return self.send_error(404)
        return self._send_ranged(fp, mime)

    def _send_ranged(self, fp, mime, cache='public, max-age=30', attach=None):
        """Byte-range file send. The CALLER owns path validation — this only
        streams what it is handed."""
        try:
            fsz = os.path.getsize(fp)
        except OSError:
            return self.send_error(404)
        start, end, code = 0, fsz - 1, 200
        rng = self.headers.get('Range')
        if rng:
            m = re.match(r'bytes=(\d*)-(\d*)\s*$', rng)
            if m:
                g1, g2 = m.group(1), m.group(2)
                if g1 == '' and g2 != '':
                    start, end = max(0, fsz - int(g2)), fsz - 1
                else:
                    start = int(g1) if g1 else 0
                    end = int(g2) if g2 else fsz - 1
                end = min(end, fsz - 1)
                if start > end or start >= fsz:
                    self.send_response(416)
                    self.send_header('Content-Range', 'bytes */%d' % fsz)
                    # Content-Length is not optional once keep-alive is on: a
                    # response without one leaves the connection desynchronised.
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                code = 206
        length = end - start + 1
        try:
            fh = open(fp, 'rb')
        except OSError:
            return self.send_error(404)
        try:
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Cache-Control', cache)
            if attach:
                self.send_header('Content-Disposition', f'attachment; filename="{attach}"')
            if code == 206:
                self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, fsz))
            self.send_header('Content-Length', str(length))
            self.end_headers()
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(65536, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    break
                remaining -= len(chunk)
        finally:
            fh.close()

    def _delete_image(self):
        """Move one inspected image into <char_dir>/.deleted/ (recoverable) so it disappears
        from the inspection lists AND from workflow/training dir globs. Same validation chain
        as _serve_image; POST only."""
        q = self._query()
        cid, cat, name = q.get('id'), q.get('cat'), q.get('name')
        char_dir = _safe_char_dir(cid)
        if not char_dir or cat not in _CATS or not name or not _NAME_RE.match(name):
            return self._send_json({'error': 'bad params'}, 400)
        if _is_medusa_char(cid, char_dir) != (q.get('scope', '') == 'medusa'):
            return self._send_json({'error': 'not found'}, 404)
        if os.path.basename(name) != name:
            return self._send_json({'error': 'bad name'}, 400)
        sub, _ = _CATS[cat]
        cat_dir = os.path.realpath(os.path.join(char_dir, sub))
        fp = os.path.realpath(os.path.join(cat_dir, name))
        if not (fp.startswith(cat_dir + os.sep) and cat_dir.startswith(char_dir) and os.path.isfile(fp)):
            return self._send_json({'error': 'not found'}, 404)
        trash = os.path.join(char_dir, '.deleted')
        try:
            os.makedirs(trash, exist_ok=True)
            dst = os.path.join(trash, f'{cat}__{name}')
            n = 1
            while os.path.exists(dst):
                dst = os.path.join(trash, f'{cat}__{n}__{name}')
                n += 1
            os.rename(fp, dst)
        except OSError as e:
            return self._send_json({'error': str(e)[:120]}, 500)
        _LIST_CACHE['ts'] = 0.0  # invalidate list cache so counts refresh
        _zyg_log.info(f'[KANBAN-SERVER] deleted (to trash): {cid}/{cat}/{name}')
        return self._send_json({'ok': True})

    def _delete_character(self):
        """Move a whole character's directory into <_CHARS_ROOT>/.deleted/ (recoverable),
        so it drops out of every listing (_ID_RE never matches a dot-prefixed name) without
        destroying the LoRA/training assets underneath it. POST only."""
        q = self._query()
        cid = q.get('id')
        char_dir = _safe_char_dir(cid)
        if not char_dir:
            return self._send_json({'error': 'bad params'}, 400)
        if _is_medusa_char(cid, char_dir) != (q.get('scope', '') == 'medusa'):
            return self._send_json({'error': 'not found'}, 404)
        trash = os.path.join(_CHARS_ROOT, '.deleted')
        try:
            os.makedirs(trash, exist_ok=True)
            dst = os.path.join(trash, cid)
            n = 1
            while os.path.exists(dst):
                dst = os.path.join(trash, f'{cid}__{n}')
                n += 1
            os.rename(char_dir, dst)
        except OSError as e:
            return self._send_json({'error': str(e)[:120]}, 500)
        _LIST_CACHE['ts'] = 0.0
        _NAME_CACHE.pop(cid, None)
        _zyg_log.info(f'[KANBAN-SERVER] deleted character (to trash): {cid}')
        return self._send_json({'ok': True, 'id': cid})
