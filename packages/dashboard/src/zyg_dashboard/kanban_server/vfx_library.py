# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Picture Studio advanced editing and the VFX Library (list/adopt/upload).

Split verbatim out of ``kanban_server.py`` (lines 2050-2285) on 2026-10-06, when that
3,172-line module became this package. The bodies are byte-for-byte the originals;
only the enclosing ``class`` line is new. :class:`zyg_dashboard.kanban_server._Handler`
puts the mixins back together in their original order, so the MRO finds every method
exactly where the single class had it.
"""

import os
import time
import shutil
from urllib.parse import quote as _urlquote


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


class _VfxLibraryMixin:
    # ── Picture Studio advanced editing (2026-08-31) ────────────────────────
    # GPU work (upscale/inpaint/bg-remove) runs on :5000 via bp_picture_studio.py;
    # this process only proxies with the shared token, same shape as _creature_decide.

    def _pic_edit_submit(self):
        body = self._json_body(limit=12_000_000)  # a base64 mask PNG can exceed the 64KB default
        body['scope'] = self._query().get('scope', '')
        out, code = _pe_forward('/api/internal/picture_studio/submit', payload=body, method='POST', timeout=30)
        return self._send_json(out, code)

    def _pic_edit_job(self):
        jid = self._query().get('id', '')
        out, code = _pe_forward(f'/api/internal/picture_studio/job/{_urlquote(jid)}', method='GET', timeout=10)
        return self._send_json(out, code)

    def _pic_edit_capability(self):
        out, code = _pe_forward('/api/internal/picture_studio/capability', method='GET', timeout=10)
        return self._send_json(out, code)

    # ── VFX Library ─────────────────────────────────────────────────────────

    def _vfx_get(self, path):
        va = _vfx()
        if not va:
            return self._send_json({'error': f'vfx analyzer unavailable: {_VFX_MOD["err"]}'}, 503)
        q = self._query()
        try:
            if path == '/inspect/api/vfx/library':
                return self._send_json({'media': va.library(), 'jobs': va.jobs()})
            if path == '/inspect/api/vfx/capability':
                return self._send_json(va.capability())
            if path.startswith('/inspect/api/vfx/probe'):
                from zyg_workflows import vfx_probes as vp

                if path == '/inspect/api/vfx/probes':
                    return self._send_json(
                        {
                            'probes': vp.list_probes(),
                            'capability': vp.capability(),
                            'harvesters': {
                                k: {'label': v['label'], 'classes': v['classes'], 'source': v['source']}
                                for k, v in vp.HARVESTERS.items()
                            },
                            'jobs': vp.training_jobs(),
                        }
                    )
                if path == '/inspect/api/vfx/probe':
                    r = vp.get_probe(q.get('id'))
                    return self._send_json(r) if r else self.send_error(404)
                if path == '/inspect/api/vfx/probe/job':
                    j = vp.training_job(q.get('id'))
                    return self._send_json(j or {'error': 'unknown job'}, 200 if j else 404)
                if path == '/inspect/api/vfx/probe/labels':
                    return self._send_json({'labels': vp.hand_labels(q.get('probe'))})
            if path == '/inspect/api/vfx/taxonomy':
                t = va.taxonomy(force=q.get('force', '') in ('1', 'true'))
                dom = q.get('domain', '')
                ents = [e for e in t.get('entries', []) if not dom or e['id'].startswith(dom + '.')]
                # the full ontology is ~2200 entries; the page asks per domain
                return self._send_json(
                    {
                        'count': t.get('count', 0),
                        'built': t.get('built', ''),
                        'domain_counts': t.get('domain_counts', {}),
                        'tier_counts': t.get('tier_counts', {}),
                        'error': t.get('error', ''),
                        'entries': ents[:1200],
                        'truncated': len(ents) > 1200,
                    }
                )
            if path == '/inspect/api/vfx/runs':
                return self._send_json({'runs': va.runs(q.get('media') or None)})
            if path == '/inspect/api/vfx/run':
                rep = va.run(q.get('id'))
                return self._send_json(rep) if rep else self.send_error(404)
            if path == '/inspect/api/vfx/frames':
                try:
                    off = max(0, int(q.get('offset', 0)))
                    lim = max(1, min(2000, int(q.get('limit', 400))))
                except ValueError:
                    off, lim = 0, 400
                return self._send_json({'frames': va.frames(q.get('id'), lim, off), 'offset': off})
            if path == '/inspect/api/vfx/events':
                return self._send_json({'events': va.events(q.get('id'))})
            if path == '/inspect/api/vfx/unknowns':
                return self._send_json({'unknowns': va.unknowns(q.get('id'))})
            if path == '/inspect/api/vfx/log':
                return self._send_json({'log': va.log_text(q.get('id'))})
            if path == '/inspect/api/vfx/job':
                j = va.job(q.get('id'))
                return self._send_json(j or {'error': 'unknown job'}, 200 if j else 404)
            if path == '/inspect/api/vfx/jobs':
                return self._send_json({'jobs': va.jobs()})
            if path == '/inspect/vfx/frame':
                fp = va.frame_image_path(q.get('run'), q.get('i'))
                # frames are immutable for the life of a run, so the browser may
                # cache them hard — the frame strip fetches hundreds of them
                return self._send_ranged(fp, 'image/jpeg', 'public, max-age=86400') if fp else self.send_error(404)
            if path == '/inspect/vfx/crop':
                fp = va.crop_image_path(q.get('run'), q.get('f'))
                return self._send_ranged(fp, 'image/jpeg', 'public, max-age=86400') if fp else self.send_error(404)
            if path == '/inspect/vfx/media':
                fp = va.media_path(q.get('id'))
                if not fp:
                    return self.send_error(404)
                mime = _MEDIA_MIME.get(os.path.splitext(fp)[1].lower(), 'video/mp4')
                return self._send_ranged(fp, mime, 'public, max-age=3600')
        except Exception as e:  # noqa: BLE001 — a bad query must 4xx, not traceback
            return self._send_json({'error': f'{type(e).__name__}: {e}'}, 400)
        return self.send_error(404)

    def _vfx_post(self, path):
        va = _vfx()
        if not va:
            return self._send_json({'error': f'vfx analyzer unavailable: {_VFX_MOD["err"]}'}, 503)
        if path == '/inspect/api/vfx/upload':
            return self._vfx_upload(va)
        if path == '/inspect/api/vfx/adopt':
            return self._vfx_adopt(va)
        body = self._json_body(limit=200_000)
        try:
            if path == '/inspect/api/vfx/run':
                out = va.start_run(body.get('media_id'), body.get('opts') or {})
                return self._send_json(out, 200 if out.get('ok') else 400)
            if path.startswith('/inspect/api/vfx/probe') or path == '/inspect/api/vfx/label':
                from zyg_workflows import vfx_probes as vp

                if path == '/inspect/api/vfx/probe/train':
                    out = vp.start_training(body.get('id'), body.get('spec') or {})
                    return self._send_json(out, 200 if out.get('ok') else 400)
                if path == '/inspect/api/vfx/probe/delete':
                    return self._send_json(vp.delete_probe(body.get('id')))
                if path == '/inspect/api/vfx/label':
                    out = vp.add_label(body.get('probe'), body.get('run_id'), body.get('frame'), body.get('class'))
                    return self._send_json(out, 200 if out.get('ok') else 400)
            if path == '/inspect/api/vfx/cancel':
                return self._send_json({'ok': va.cancel(body.get('id'))})
            if path == '/inspect/api/vfx/delete-media':
                out = va.delete_media(body.get('media_id'))
                return self._send_json(out, 200 if out.get('ok') else 400)
            if path == '/inspect/api/vfx/delete-run':
                out = va.delete_run(body.get('run_id'))
                return self._send_json(out, 200 if out.get('ok') else 400)
        except Exception as e:  # noqa: BLE001
            return self._send_json({'error': f'{type(e).__name__}: {e}'}, 400)
        return self.send_error(404)

    def _vfx_adopt(self, va):
        """Hand one file from a VFX library to the Analyzer.

        The rail browses the effects LIBRARY now, not the analyzer's own media
        list, so this is the bridge between them: {cat, f} → a media_id the
        Analyzer and Probes can scan. register_upload() MOVES what it is given
        and is content-addressed, so the library copy is duplicated to a temp
        file first (never handed over directly) and adopting the same plate
        twice returns the existing entry rather than a second copy."""
        vi = _vfxa()
        if not vi:
            return self._send_json({'error': 'vfx library unavailable'}, 503)
        body = self._json_body(limit=20_000) or {}
        cat, fn = str(body.get('cat') or ''), str(body.get('f') or '')
        if cat not in vi.CATEGORIES:
            return self._send_json({'error': 'unknown category'}, 400)
        if not fn or os.path.basename(fn) != fn or fn.startswith('.'):
            return self._send_json({'error': 'bad filename'}, 400)
        root = os.path.realpath(os.path.join(vi.LIBS, cat))
        fp = os.path.realpath(os.path.join(root, fn))
        if not (fp.startswith(root + os.sep) and os.path.isfile(fp)):
            return self._send_json({'error': 'not in that library'}, 404)
        if os.path.splitext(fn)[1].lower() not in getattr(va, 'VIDEO_EXT', ('.mp4',)):
            return self._send_json(
                {'error': 'only video assets can be analyzed; sprites and VDB packs have no frames to scan'}, 400
            )
        os.makedirs(va.ROOT, exist_ok=True)
        tmp = os.path.join(va.ROOT, f'.adopt-{os.getpid()}-{int(time.time() * 1000)}.part')
        try:
            shutil.copyfile(fp, tmp)
            meta = va.register_upload(tmp, fn)
        except Exception as e:  # noqa: BLE001 — report, never traceback
            for junk in (tmp,):
                try:
                    os.unlink(junk)
                except OSError as _exc:
                    _zyg_log.debug('adopt temp %s not removed: %s', junk, _exc)
            return self._send_json({'error': f'{type(e).__name__}: {e}'}, 500)
        return self._send_json(meta)

    def _vfx_upload(self, va):
        """Adopt an uploaded video.

        The body is the RAW file, with the name in the query string — not
        multipart. A video is the one thing this server receives that can be
        gigabytes, and multipart would mean buffering the whole encoded body in
        memory to find the part boundaries. This streams straight to disk in
        chunks, so upload size costs disk and not RAM."""
        q = self._query()
        name = os.path.basename(q.get('name', '') or 'upload.mp4')[:180]
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            return self._send_json({'error': 'bad Content-Length'}, 400)
        if n <= 0:
            return self._send_json({'error': 'empty upload'}, 400)
        if n > _VFX_MAX_UPLOAD:
            return self._send_json(
                {'error': f'upload is {n / 1e9:.1f} GB; the cap is {_VFX_MAX_UPLOAD / 1e9:.0f} GB'}, 413
            )
        os.makedirs(va.ROOT, exist_ok=True)
        tmp = os.path.join(va.ROOT, f'.upload-{os.getpid()}-{int(time.time() * 1000)}.part')
        got = 0
        try:
            with open(tmp, 'wb') as f:
                while got < n:
                    chunk = self.rfile.read(min(1 << 20, n - got))
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
        except (OSError, ConnectionError) as e:
            try:
                os.unlink(tmp)
            except OSError as _exc:
                _zyg_log.debug('upload temp %s not removed after the failed read: %s', tmp, _exc)
            return self._send_json({'error': f'upload failed after {got} bytes: {e}'}, 400)
        if got != n:
            try:
                os.unlink(tmp)
            except OSError as _exc:
                _zyg_log.debug('upload temp %s not removed after the truncated read: %s', tmp, _exc)
            return self._send_json({'error': f'truncated upload: {got}/{n} bytes'}, 400)
        out = va.register_upload(tmp, name)
        if out.get('error'):
            return self._send_json(out, 400)
        _zyg_log.info(f'[KANBAN-SERVER] vfx upload: {name!r} -> {out.get("media_id")} ({got / 1e6:.1f} MB)')
        return self._send_json(out)
