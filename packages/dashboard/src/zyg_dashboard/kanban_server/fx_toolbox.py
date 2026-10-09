# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The VFX / Creature Studio / Picture Studio effect-stack toolboxes.

Split verbatim out of ``kanban_server.py`` (lines 537-824) on 2026-10-06, when that
3,172-line module became this package. The bodies are byte-for-byte the originals;
only the enclosing ``class`` line is new. :class:`zyg_dashboard.kanban_server._Handler`
puts the mixins back together in their original order, so the MRO finds every method
exactly where the single class had it.
"""

import json


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


class _FxToolboxMixin:
    # ── VFX effect stack ───────────────────────────────────────────────────
    def _fx_get(self, path):
        fx = _vfxfx()
        if not fx:
            return self._send_json({'error': f'effect stack unavailable: {_VFXFX_MOD["err"]}'}, 503)
        q = self._query()
        try:
            if path == '/inspect/api/vfx/fx/ops':
                return self._send_json(fx.ops_payload())
            if path == '/inspect/api/vfx/fx/job':
                if q.get('id'):
                    return self._send_json(fx.job_status(q.get('id')))
                return self._send_json({'ok': True, 'jobs': fx.recent_jobs()})
            if path == '/inspect/api/vfx/fx/chain':
                return self._send_json(
                    fx.chain_text(
                        q.get('cat', ''),
                        q.get('f', ''),
                        _fx_stack_arg(q.get('s')),
                        view=q.get('view', 'rgb'),
                        scope=q.get('scope', ''),
                        ab=q.get('ab', '') in ('1', 'true'),
                    )
                )
            if path == '/inspect/vfx/fx/frame':
                png, info = fx.preview_frame(
                    q.get('cat', ''),
                    q.get('f', ''),
                    _fx_stack_arg(q.get('s')),
                    t=float(q.get('t') or 0),
                    view=q.get('view', 'rgb'),
                    scope=q.get('scope', ''),
                    ab=q.get('ab', '') in ('1', 'true'),
                    maxw=max(160, min(3840, int(q.get('w') or fx.PREVIEW_MAX))),
                )
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                # no-store: the stack is in the URL, so a cached frame is a
                # frame from a stack you have already changed
                self.send_header('Cache-Control', 'no-store')
                # what the graph had to drop rides back in a header rather than
                # in the body, because the body has to stay a valid PNG
                if info.get('dropped'):
                    self.send_header('X-Fx-Dropped', json.dumps(info['dropped'])[:900])
                if info.get('time_ops'):
                    self.send_header('X-Fx-Timeops', ','.join(info['time_ops'])[:300])
                self.send_header('Content-Length', str(len(png)))
                self.end_headers()
                try:
                    self.wfile.write(png)
                except BrokenPipeError as _exc:
                    _zyg_log.debug('client closed the connection before the fx frame was sent: %s', _exc)
                return None
        except ValueError as e:
            return self._send_json({'error': str(e)}, 400)
        except Exception as e:  # noqa: BLE001 — a bad graph must 4xx, not traceback
            return self._send_json({'error': f'{type(e).__name__}: {e}'}, 400)
        return self.send_error(404)

    def _fx_post(self, path):
        fx = _vfxfx()
        if not fx:
            return self._send_json({'error': f'effect stack unavailable: {_VFXFX_MOD["err"]}'}, 503)
        body = self._json_body(limit=400_000) or {}
        try:
            if path == '/inspect/api/vfx/fx/render':
                out = fx.start_render(
                    body.get('cat', ''), body.get('f', ''), body.get('stack') or [], body.get('opts') or {}
                )
                if out.get('ok'):
                    # the rail has to show the new row; its 20 s cache would
                    # otherwise hide a render you just watched finish
                    _VFXA_CACHE.update(ts=0, data=None)
                return self._send_json(out, 200 if out.get('ok') else 400)
            if path == '/inspect/api/vfx/fx/preset':
                out = fx.save_preset(body.get('name'), body.get('stack') or [], body.get('note', ''))
                return self._send_json(out, 200 if out.get('ok') else 400)
            if path == '/inspect/api/vfx/fx/preset-delete':
                return self._send_json(fx.delete_preset(body.get('id')))
        except Exception as e:  # noqa: BLE001
            return self._send_json({'error': f'{type(e).__name__}: {e}'}, 400)
        return self.send_error(404)

    # ── Creature Studio toolbox ────────────────────────────────────────────
    # Same shape as the VFX effect stack and for the same reasons: the registry
    # is server-side, the page draws both bars from /ops and holds no tool list,
    # and the preview rides in an <img src> so the stack travels as base64url
    # JSON in the URL. Routed BEFORE the creature image route for the same
    # reason the VFX pair is: these need Pillow, not the creature pipeline's
    # whole import surface.
    def _crfx_get(self, path):
        fx = _crfx()
        if not fx:
            return self._send_json({'error': f'creature toolbox unavailable: {_CRFX_MOD["err"]}'}, 503)
        q = self._query()
        try:
            if path == '/inspect/api/creature/fx/ops':
                return self._send_json(fx.ops_payload())
            if path == '/inspect/api/creature/fx/facts':
                return self._send_json(fx.creature_facts(q.get('id', '')))
            if path == '/inspect/api/creature/fx/chain':
                return self._send_json(
                    fx.chain_text(q.get('id', ''), q.get('cat', ''), q.get('f', ''), _fx_stack_arg(q.get('s')))
                )
            if path == '/inspect/api/creature/fx/measure':
                return self._send_json(
                    fx.measure(
                        q.get('id', ''),
                        q.get('cat', ''),
                        q.get('f', ''),
                        q.get('m', ''),
                        _fx_stack_arg(q.get('s')),
                        band=q.get('band', 'front'),
                    )
                )
            if path == '/inspect/api/creature/fx/job':
                if q.get('job'):
                    return self._send_json(fx.job_status(q.get('job')))
                return self._send_json({'ok': True, 'jobs': fx.recent_jobs()})
            if path == '/inspect/api/creature/fx/recipe':
                return self._send_json({'ok': True, 'recipe': fx.read_recipe(q.get('id', ''), q.get('f', ''))})
            if path == '/inspect/api/creature/fx/pipeline':
                return self._send_json(fx.pipeline_commands(q.get('id', '')))
            if path == '/inspect/creature/fx/frame':
                png, info = fx.preview_frame(
                    q.get('id', ''),
                    q.get('cat', ''),
                    q.get('f', ''),
                    _fx_stack_arg(q.get('s')),
                    view=q.get('view', 'rgb'),
                    ab=q.get('ab', '') in ('1', 'true'),
                    ground=q.get('bg', ''),
                    maxw=max(120, min(4096, int(q.get('w') or fx.PREVIEW_MAX))),
                )
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                # no-store: the stack is in the URL, so a cached frame is a
                # frame from a stack you have already changed
                self.send_header('Cache-Control', 'no-store')
                # what the preview could NOT show rides back in a header, so the
                # body stays a valid PNG and the page can still say "3 generative
                # ops are not in this picture"
                if info.get('not_shown'):
                    self.send_header('X-Crfx-Notshown', json.dumps(info['not_shown'])[:900])
                if info.get('dropped'):
                    self.send_header('X-Crfx-Dropped', json.dumps(info['dropped'])[:900])
                self.send_header('X-Crfx-Size', f'{info["w"]}x{info["h"]}')
                self.send_header('Content-Length', str(len(png)))
                self.end_headers()
                try:
                    self.wfile.write(png)
                except BrokenPipeError as _exc:
                    _zyg_log.debug('client closed the connection before the creature fx frame was sent: %s', _exc)
                return None
        except ValueError as e:
            return self._send_json({'error': str(e)[:300]}, 400)
        except Exception as e:  # noqa: BLE001 — a bad stack must 4xx, not traceback
            return self._send_json({'error': f'{type(e).__name__}: {e}'}, 400)
        return self.send_error(404)

    def _crfx_post(self, path):
        fx = _crfx()
        if not fx:
            return self._send_json({'error': f'creature toolbox unavailable: {_CRFX_MOD["err"]}'}, 503)
        body = self._json_body(limit=400_000) or {}
        try:
            if path == '/inspect/api/creature/fx/render':
                out = fx.start_render(
                    body.get('id', ''),
                    body.get('cat', ''),
                    body.get('f', ''),
                    body.get('stack') or [],
                    body.get('opts') or {},
                )
                return self._send_json(out, 200 if out.get('ok') else 400)
            if path == '/inspect/api/creature/fx/apply':
                out = fx.apply_action(body)
                return self._send_json(out, 200 if out.get('ok') else 400)
            if path == '/inspect/api/creature/fx/preset':
                out = fx.save_preset(body.get('name'), body.get('stack') or [], body.get('note', ''))
                return self._send_json(out, 200 if out.get('ok') else 400)
            if path == '/inspect/api/creature/fx/preset-delete':
                return self._send_json(fx.delete_preset(body.get('id')))
        except ValueError as e:
            return self._send_json({'error': str(e)[:300]}, 400)
        except Exception as e:  # noqa: BLE001
            return self._send_json({'error': f'{type(e).__name__}: {e}'}, 400)
        return self.send_error(404)

    # ── Picture Studio toolbox (2026-09-06) ────────────────────────────────
    # Same shape as the creature pair above and for the same reasons: the stack
    # rides in the URL as base64url JSON so the preview can be an <img src>, the
    # frame comes back as a PNG with what it could NOT show in a header, and every
    # request re-validates (lib, id, cat, name, scope) inside picture_fx rather
    # than trusting this handler. The one addition is /img: a Picture Studio
    # source can be a character image, a creature image OR one of the studio's own
    # bakes, and neither _serve_image nor _creature_img can address the third.
    def _pfx_get(self, path):
        fx = _pfx()
        if not fx:
            return self._send_json({'error': f'picture toolbox unavailable: {_PFX_MOD["err"]}'}, 503)
        q = self._query()
        lib, cid = q.get('lib', ''), q.get('id', '')
        scope = q.get('scope', '')
        try:
            if path == '/inspect/api/picture/fx/ops':
                return self._send_json(fx.ops_payload())
            if path == '/inspect/api/picture/fx/facts':
                return self._send_json(fx.facts(lib, cid, scope))
            if path == '/inspect/api/picture/fx/images':
                return self._send_json({'ok': True, 'images': fx.images(lib, cid, scope)})
            if path == '/inspect/api/picture/fx/chain':
                return self._send_json(
                    fx.chain_text(lib, cid, q.get('cat', ''), q.get('f', ''), _fx_stack_arg(q.get('s')), scope)
                )
            if path == '/inspect/api/picture/fx/job':
                if q.get('job'):
                    return self._send_json(fx.job_status(q.get('job')))
                return self._send_json({'ok': True, 'jobs': fx.recent_jobs()})
            if path == '/inspect/api/picture/fx/recipe':
                return self._send_json({'ok': True, 'recipe': fx.read_recipe(lib, cid, q.get('f', ''), scope)})
            if path == '/inspect/picture/fx/img':
                fp = fx.resolve(lib, cid, q.get('cat', ''), q.get('name', ''), scope)
                return self._send_image_thumb_or_full(fp, q.get('thumb') == '1')
            if path == '/inspect/picture/fx/frame':
                png, info = fx.preview_frame(
                    lib,
                    cid,
                    q.get('cat', ''),
                    q.get('f', ''),
                    _fx_stack_arg(q.get('s')),
                    view=q.get('view', 'rgb'),
                    ab=q.get('ab', '') in ('1', 'true'),
                    ground=q.get('bg', ''),
                    maxw=max(120, min(4096, int(q.get('w') or fx.PREVIEW_MAX))),
                    scope=scope,
                )
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                # no-store: the stack is in the URL, so a cached frame is a frame
                # from a stack you have already changed
                self.send_header('Cache-Control', 'no-store')
                # what the preview could NOT show rides in a header, so the body
                # stays a valid PNG and the page can still say "3 ops are not in
                # this picture"
                if info.get('not_shown'):
                    self.send_header('X-Pfx-Notshown', json.dumps(info['not_shown'])[:900])
                if info.get('dropped'):
                    self.send_header('X-Pfx-Dropped', json.dumps(info['dropped'])[:900])
                self.send_header('X-Pfx-Size', f'{info["w"]}x{info["h"]}')
                self.send_header('Content-Length', str(len(png)))
                self.end_headers()
                try:
                    self.wfile.write(png)
                except BrokenPipeError as _exc:
                    _zyg_log.debug('client closed the connection before the picture fx frame was sent: %s', _exc)
                return None
        except ValueError as e:
            return self._send_json({'error': str(e)[:300]}, 400)
        except Exception as e:  # noqa: BLE001 — a bad stack must 4xx, not traceback
            return self._send_json({'error': f'{type(e).__name__}: {e}'}, 400)
        return self.send_error(404)

    def _pfx_post(self, path):
        fx = _pfx()
        if not fx:
            return self._send_json({'error': f'picture toolbox unavailable: {_PFX_MOD["err"]}'}, 503)
        # the mask a repair carries is a base64 PNG at the source's own
        # resolution, so the body limit is the lightbox's, not the stack's
        body = self._json_body(limit=12_000_000) or {}
        try:
            if path == '/inspect/api/picture/fx/render':
                out = fx.start_render(body)
                return self._send_json(out, 200 if out.get('ok') else 400)
            if path == '/inspect/api/picture/fx/apply':
                out = fx.apply_action(body)
                return self._send_json(out, 200 if out.get('ok') else 400)
            if path == '/inspect/api/picture/fx/preset':
                out = fx.save_preset(body.get('name'), body.get('stack') or [], body.get('note', ''))
                return self._send_json(out, 200 if out.get('ok') else 400)
            if path == '/inspect/api/picture/fx/preset-delete':
                return self._send_json(fx.delete_preset(body.get('id')))
        except ValueError as e:
            return self._send_json({'error': str(e)[:300]}, 400)
        except Exception as e:  # noqa: BLE001
            return self._send_json({'error': f'{type(e).__name__}: {e}'}, 400)
        return self.send_error(404)
