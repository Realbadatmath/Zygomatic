# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Architecture Studio and Character Studio APIs.

Split verbatim out of ``kanban_server.py`` (lines 2286-2571) on 2026-10-06, when that
3,172-line module became this package. The bodies are byte-for-byte the originals;
only the enclosing ``class`` line is new. :class:`zyg_dashboard.kanban_server._Handler`
puts the mixins back together in their original order, so the MRO finds every method
exactly where the single class had it.
"""

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


class _StudioApiMixin:
    # ── Architecture Studio API ────────────────────────────────────────────
    # /inspect/api/architecture           -> the left rail (drawings + catalogue)
    # /inspect/api/architecture/project   -> one saved drawing
    # /inspect/api/architecture/save      -> write a drawing (POST)
    # /inspect/api/architecture/delete    -> move one to trash (POST)
    # /inspect/api/architecture/rename    -> rename one (POST)
    def _arch_unavailable(self):
        return self._send_json({'error': f'architecture studio unavailable: {_ARCH_MOD["err"]}'}, 503)

    def _arch_get(self, path):
        if path.startswith('/inspect/api/architecture/assistant'):
            return self._arch_assist('GET', path)
        if path.startswith('/inspect/api/architecture/ext/'):
            return self._arch_ext('GET', path, self._query())
        ar = _arch()
        if not ar:
            return self._arch_unavailable()
        q = self._query()
        try:
            if path == '/inspect/api/architecture':
                return self._send_json(ar.library())
            if path == '/inspect/api/architecture/project':
                out = ar.load_project(q.get('id', ''))
                return self._send_json(out, 200 if out.get('ok') else 404)
        except ValueError as e:
            return self._send_json({'error': str(e)[:200]}, 400)
        except OSError as e:
            return self._send_json({'error': str(e)[:200]}, 500)
        return self.send_error(404)

    # /inspect/api/architecture/ext/<family>/<op>  -> server-side ops of the
    # icon families (2026-09-07). arch_server_ext/<family>.py exports
    # ROUTES = {op: fn(payload, method) -> dict | (bytes, mime, filename)};
    # architecture_studio.ext_dispatch() reloads a file whose mtime moved, so a
    # family lands without a server restart. A tuple is sent as a download.
    def _arch_ext(self, method, path, payload):
        ar = _arch()
        if not ar:
            return self._arch_unavailable()
        rest = path[len('/inspect/api/architecture/ext/') :]
        try:
            res = ar.ext_dispatch(method, rest, payload or {})
        except Exception as e:  # noqa: BLE001
            _zyg_log.info(f'[KANBAN-SERVER] arch ext {method} {rest}: {e!r}')
            return self._send_json({'error': str(e)[:300]}, 500)
        if isinstance(res, tuple):
            data, mime, fname = (list(res) + [None, None])[:3]
            if not isinstance(data, (bytes, bytearray)):
                data = str(data).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', mime or 'application/octet-stream')
            if fname:
                self.send_header('Content-Disposition', 'attachment; filename="%s"' % str(fname).replace('"', ''))
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)
            return None
        code = 200
        if isinstance(res, dict) and res.get('error') and not res.get('ok'):
            code = int(res.get('code') or 400)
        return self._send_json(res, code)

    # /inspect/api/studio/<mod>/<op>  -> server-side ops of the studio
    # extensions (2026-09-18). studio_ext_server/<mod>.py exports
    # ROUTES = {op: fn(payload, method) -> dict | (bytes, mime, filename)};
    # studio_ext_dispatch reloads a file whose mtime moved, so an op lands
    # without a server restart. A tuple is sent as a download. Empty rest lists
    # the modules.
    def _studio_ext(self, method, path, payload):
        rest = path[len('/inspect/api/studio/') :]
        try:
            from zyg_workflows import studio_ext_dispatch

            res = studio_ext_dispatch.dispatch(method, rest, payload or {})
        except Exception as e:  # noqa: BLE001
            _zyg_log.info(f'[KANBAN-SERVER] studio ext {method} {rest}: {e!r}')
            return self._send_json({'error': str(e)[:300]}, 500)
        if isinstance(res, tuple):
            data, mime, fname = (list(res) + [None, None])[:3]
            if not isinstance(data, (bytes, bytearray)):
                data = str(data).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', mime or 'application/octet-stream')
            if fname:
                self.send_header('Content-Disposition', 'attachment; filename="%s"' % str(fname).replace('"', ''))
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)
            return None
        code = 200
        if isinstance(res, dict) and res.get('error') and not res.get('ok'):
            code = int(res.get('code') or 400)
        return self._send_json(res, code)

    # /inspect/api/architecture/assistant/*  -> the drawing assistant
    #   (2026-09-06: start / job / render / cancel / blender / info — see
    #   arch_assistant.py; the model draws on the server, the tab injects)
    def _arch_assist(self, method, path):
        try:
            from zyg_workflows import arch_assistant
        except Exception as e:  # noqa: BLE001
            return self._send_json({'error': f'assistant unavailable: {e}'}, 503)
        try:
            if method == 'GET':
                out, code = arch_assistant.handle_get(path, self._query())
            else:
                out, code = arch_assistant.handle_post(path, self._json_body(limit=arch_assistant.BODY_LIMIT))
        except Exception as e:  # noqa: BLE001
            _zyg_log.info(f'[KANBAN-SERVER] arch assistant {method} {path}: {e!r}')
            return self._send_json({'error': str(e)[:300]}, 500)
        # 2026-09-16: /picture answers (bytes, mime) — the hero 4K render is a
        # FILE, far past what a JSON data URL can carry. Same shape as _arch_ext.
        if isinstance(out, tuple):
            data, mime = (list(out) + [None, None])[:2]
            if not isinstance(data, (bytes, bytearray)):
                data = str(data).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', mime or 'application/octet-stream')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)
            return None
        return self._send_json(out, code)

    def _arch_post(self, path):
        if path.startswith('/inspect/api/architecture/assistant'):
            return self._arch_assist('POST', path)
        ar = _arch()
        if not ar:
            return self._arch_unavailable()
        if path.startswith('/inspect/api/architecture/ext/'):
            return self._arch_ext('POST', path, self._json_body(limit=ar.MAX_DOC_BYTES + (1 << 16)))
        # A drawing is the whole POST body, so the 64 KB default would refuse
        # any scene past a few dozen objects. The module caps it again on the
        # way to disk; this cap only stops the read.
        body = self._json_body(limit=ar.MAX_DOC_BYTES + (1 << 16))
        try:
            if path == '/inspect/api/architecture/save':
                out = ar.save_project(body.get('doc') or {}, pid=body.get('id', ''), name=body.get('name', ''))
                if out.get('ok'):
                    _zyg_log.info(f'[KANBAN-SERVER] architecture: saved drawing {out["id"]} ({out["objects"]} objects)')
                return self._send_json(out, 200 if out.get('ok') else 400)
            if path == '/inspect/api/architecture/delete':
                out = ar.delete_project(body.get('id', ''))
                return self._send_json(out, 200 if out.get('ok') else 404)
            if path == '/inspect/api/architecture/rename':
                out = ar.rename_project(body.get('id', ''), body.get('name', ''))
                return self._send_json(out, 200 if out.get('ok') else 400)
        except ValueError as e:
            return self._send_json({'error': str(e)[:200]}, 400)
        except OSError as e:
            return self._send_json({'error': str(e)[:200]}, 500)
        return self.send_error(404)

    # ── Character Studio API ───────────────────────────────────────────────
    # /inspect/api/char/spec        -> the editable-field registry (GET)
    # /inspect/api/char/bible       -> one character's bible + measured facts (GET)
    # /inspect/api/char/bible/save  -> apply dotted-path edits (POST)
    def _cs_guard(self):
        """(module, cid, char_dir) or None, having sent the error. Same
        fail-closed cross-scope check _api_char makes: the default view never
        reads or writes a medusa character and the medusa view never touches a
        storyteller one."""
        m = _cstudio()
        if not m:
            self._send_json({'error': f'character studio unavailable: {_CSTUDIO_MOD["err"]}'}, 503)
            return None
        q = self._query()
        cid = q.get('id', '')
        cdir = _safe_char_dir(cid)
        if not cdir:
            self.send_error(404)
            return None
        if _is_medusa_char(cid, cdir) != (q.get('scope', '') == 'medusa'):
            self.send_error(404)
            return None
        return m, cid, cdir

    def _cs_get(self, path):
        if path == '/inspect/api/char/spec':
            m = _cstudio()
            if not m:
                return self._send_json({'error': f'character studio unavailable: {_CSTUDIO_MOD["err"]}'}, 503)
            return self._send_json(m.spec())
        g = self._cs_guard()
        if not g:
            return None
        m, cid, cdir = g
        if path == '/inspect/api/char/bible':
            out = m.read(cid, cdir)
            return self._send_json(out, 200 if out.get('ok') else 404)
        return self.send_error(404)

    def _cs_post(self, path):
        # ── Body axes + plates (2026-09-02, S05) ───────────────────────────
        # The Body panel reads and writes an Anny CANDIDATE, never the bible and
        # never the registry, so it goes through character_studio's own body_axes
        # / write_candidate rather than through edit()'s bible whitelist.
        if path in ('/inspect/api/char/body', '/inspect/api/char/body/save', '/inspect/api/char/plates'):
            g = self._cs_guard()
            if not g:
                return None
            m, cid, _cdir = g
            body = self._json_body(limit=40_000)
            # A character id is not a body name. resolve_body says which body
            # this character has AND how it decided, and the answer travels with
            # every response so the panel can show an inferred link as inferred.
            link = m.resolve_body(cid)
            if not link.get('body'):
                return self._send_json({'ok': False, 'state': 'unavailable', 'link': link, 'error': link['why']}, 404)
            bname = link['body']
            if path == '/inspect/api/char/body':
                try:
                    out = m.body_axes(bname)
                    out['link'] = link
                    return self._send_json(out)
                except Exception as e:  # noqa: BLE001
                    return self._send_json({'ok': False, 'error': f'{type(e).__name__}: {e}'[:200]}, 500)
            if path == '/inspect/api/char/body/save':
                try:
                    out = m.write_candidate(bname, body.get('edits') or {}, note=body.get('note') or '')
                    out['link'] = link
                except Exception as e:  # noqa: BLE001
                    return self._send_json({'ok': False, 'error': f'{type(e).__name__}: {e}'[:200]}, 500)
                if out.get('ok'):
                    _zyg_log.info(
                        f'[KANBAN-SERVER] body candidate: {cid} <- {sorted(out.get("applied") or {})} -> {out["path"]}'
                    )
                return self._send_json(out, 200 if out.get('ok') else 400)
            # /inspect/api/char/plates — read the manifest, or render on request.
            # Rendering is a Blender job of a couple of minutes per body, so it
            # only happens when the caller asks for it explicitly.
            try:
                import zyg_workflows.geom.body_plates as BP

                if body.get('render'):
                    man = BP.build(
                        bname,
                        char_id=cid,
                        force=bool(body.get('force')),
                        size=int(body.get('size') or 768),
                        samples=int(body.get('samples') or 24),
                    )
                else:
                    man = BP.load_manifest(bname, cid)
                if not man:
                    return self._send_json(
                        {
                            'ok': False,
                            'state': 'not_found',
                            'link': link,
                            'error': 'no plates rendered for this character yet',
                            'dir': BP.plates_dir(bname, cid),
                        },
                        404,
                    )
                return self._send_json({'ok': True, 'manifest': man, 'link': link, 'dir': BP.plates_dir(bname, cid)})
            except Exception as e:  # noqa: BLE001
                return self._send_json({'ok': False, 'error': f'{type(e).__name__}: {e}'[:400]}, 500)

        if path != '/inspect/api/char/bible/save':
            return self.send_error(404)
        g = self._cs_guard()
        if not g:
            return None
        m, cid, cdir = g
        # a free-text bible field runs to 2 KB and a section-wide apply writes
        # up to MAX_EDITS of them, so the 64 KB default body cap is raised here
        body = self._json_body(limit=256000)
        try:
            out = m.edit(cid, cdir, body.get('edits') or {})
        except Exception as e:  # noqa: BLE001 — surfaced to the panel
            return self._send_json({'ok': False, 'error': f'{type(e).__name__}: {e}'[:200]}, 500)
        if out.get('ok'):
            _NAME_CACHE.pop(cid, None)  # display_name may have just changed
            _LIST_CACHE['data'] = None  # ...and the library list caches it
            _zyg_log.info(f'[KANBAN-SERVER] character studio: {cid} <- {sorted(out.get("applied") or {})}')
        return self._send_json(out, 200 if out.get('ok') else 400)
