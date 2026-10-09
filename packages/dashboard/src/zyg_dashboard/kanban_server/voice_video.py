# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The voices API, Video Studio drafts and the merge/record endpoints.

Split verbatim out of ``kanban_server.py`` (lines 1113-1651) on 2026-10-06, when that
3,172-line module became this package. The bodies are byte-for-byte the originals;
only the enclosing ``class`` line is new. :class:`zyg_dashboard.kanban_server._Handler`
puts the mixins back together in their original order, so the MRO finds every method
exactly where the single class had it.
"""

import os
import json
import math
import tempfile
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


class _VoiceVideoMixin:
    # ── voices API ─────────────────────────────────────────────────────────
    def _json_body(self, limit=64000):
        """Read a JSON POST body. Returns {} on anything malformed — every caller
        below validates the fields it needs anyway."""
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            return {}
        if n <= 0 or n > limit:
            return {}
        try:
            body = self.rfile.read(n)
        except (OSError, ConnectionError):
            return {}
        try:
            obj = json.loads(body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return {}
        return obj if isinstance(obj, dict) else {}

    def _voice_post(self, path):
        vs = _voice_studio()
        if not vs:
            return self._send_json({'error': f'voice studio unavailable: {_VOICE_MOD["err"]}'}, 503)
        body = self._json_body()
        vid = str(body.get('voice') or '')
        try:
            if path == '/voice/api/render':
                job = vs.start_render(vid, str(body.get('text') or ''), body.get('params') or {})
                return self._send_json({'ok': True, 'job': job})
            if path == '/voice/api/preset/save':
                rec = vs.save_preset(
                    vid,
                    str(body.get('name') or ''),
                    body.get('params') or {},
                    slug=str(body.get('slug') or ''),
                    metrics=body.get('metrics') or {},
                    preview_wav=self._voice_job_wav(vs, str(body.get('job') or '')),
                    text=str(body.get('text') or ''),
                )
                _zyg_log.info(f'[KANBAN-SERVER] voice preset saved: {vid}/{rec["slug"]} ({rec["name"]!r})')
                return self._send_json({'ok': True, 'preset': rec, **vs.list_presets(vid)})
            if path == '/voice/api/preset/starters':
                # On demand, not pre-installed. The house voices got the starter
                # tier written to disk because there are seventeen of them; doing
                # the same for the Kyutai bank would mint ~2500 preset files for
                # voices nobody has opened. Idempotent, so a double-click is safe.
                from zyg_workflows import voice_presets_starter

                made = voice_presets_starter.install(vid)
                _zyg_log.info(f'[KANBAN-SERVER] starter presets for {vid}: {len(made)} written')
                return self._send_json({'ok': True, 'written': len(made), **vs.list_presets(vid)})
            if path == '/voice/api/preset/delete':
                ok = vs.delete_preset(vid, str(body.get('slug') or ''))
                return self._send_json({'ok': ok, **vs.list_presets(vid)})
            if path == '/voice/api/preset/activate':
                vs.set_active(vid, str(body.get('slug') or ''))
                return self._send_json({'ok': True, **vs.list_presets(vid)})
            if path == '/voice/api/prerender':
                job = vs.start_prerender(vid, str(body.get('text') or ''), force=bool(body.get('force')))
                _zyg_log.info(
                    f'[KANBAN-SERVER] pre-render {vid}: {job.get("total", 0)} preset(s), job {job.get("id", "")}'
                )
                return self._send_json({'ok': True, 'job': job})
            if path == '/voice/api/prerender/cancel':
                return self._send_json({'ok': vs.cancel_job(str(body.get('job') or ''))})
            if path == '/voice/api/bake':
                if body.get('stop'):
                    vs.stop_bake()
                else:
                    vs.start_bake()
                return self._send_json({'ok': True, **vs.library_status()})
            if path == '/voice/api/assign/save':
                va = _voice_assign()
                if not va:
                    return self._send_json({'error': f'assignments unavailable: {_ASSIGN_MOD["err"]}'}, 503)
                if not vs.voice(vid):
                    return self._send_json({'error': 'unknown voice'}, 400)
                chars = [str(x) for x in (body.get('characters') or [])][:2000]
                wfs = [str(x) for x in (body.get('workflows') or [])][:2000]
                view = va.save(vid, chars, wfs, preset=str(body.get('preset') or ''))
                _zyg_log.info(f'[KANBAN-SERVER] voice assign {vid}: {len(chars)} character(s), {len(wfs)} workflow(s)')
                return self._send_json({'ok': True, **view})
        except ValueError as e:
            return self._send_json({'error': str(e)[:300]}, 400)
        except Exception as e:  # noqa: BLE001 — never 500 silently
            _zyg_log.info(f'[KANBAN-SERVER] voice API error on {path}: {e!r}')
            return self._send_json({'error': f'{type(e).__name__}: {e}'[:300]}, 500)
        return self.send_error(404)

    @staticmethod
    def _voice_job_wav(vs, jid):
        """Absolute path of a finished job's preview wav, for freezing into a
        preset. Empty when the job is unknown/unfinished — saving the KNOBS must
        still succeed even if the audition take has already been swept."""
        if not jid:
            return ''
        j = vs.job(jid)
        return vs.resolve_audio(j.get('wav', '')) or '' if j else ''

    _VS_OUT = os.path.realpath(os.path.join(HERE, 'output', 'video_studio'))

    def _vfx_draft(self, vd, body):
        """POST /video/api/vfx/draft — place a VFX element on a rendered clip.

        Takes ``{job_id}`` or ``{clip: 'out/video_studio/<jid>/clip.mp4'}`` plus
        the Video Studio params, and answers with a 320p composite the player
        can swap straight in. The clip is resolved through the same media-path
        whitelist the rest of this server uses AND then re-checked to sit under
        output/video_studio: a draft writes its output NEXT TO its input, so
        letting an arbitrary media path through would let a caller choose where
        this handler writes."""
        try:
            from zyg_workflows import vfx_place
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f'vfx placement unavailable: {type(exc).__name__}: {exc}') from exc

        rel = str(body.get('clip') or '').strip()
        jid = str(body.get('job_id') or '').strip()
        if not rel and jid:
            job = vd.job(jid) or {}
            rel = str(job.get('url') or '').partition('path=')[2] or f'out/video_studio/{jid}/clip.mp4'
        clip = self._resolve_media_path(rel)
        if not clip or not clip.lower().endswith(('.mp4', '.mov', '.webm', '.mkv')):
            raise ValueError('clip not found')
        if not clip.startswith(self._VS_OUT + os.sep):
            raise ValueError('a VFX draft only runs on a Video Studio clip')

        job_dir = os.path.dirname(clip)
        params = vd.sanitize(body.get('params') or {})
        if str(params.get('vfx_element', 'none')) == 'none':
            raise ValueError('pick a VFX element first')

        # The scene-shot camera, when this clip was rendered from one: its
        # settings dump names the shot, and the studio camera that made the
        # frame beats any fov the operator dials in after the fact.
        try:
            with open(os.path.splitext(clip)[0] + '.settings.json', encoding='utf-8') as fh:
                st = json.load(fh)
            shot = str(st.get('scene_shot') or (st.get('changed') or {}).get('scene_shot') or '')
        except (OSError, ValueError):
            shot = ''
        if shot:
            params['scene_shot'] = shot

        n = 1
        while os.path.exists(os.path.join(job_dir, f'vfx_draft_{n}.mp4')):
            n += 1
        out = os.path.join(job_dir, f'vfx_draft_{n}.mp4')
        rec = vfx_place.plan(clip, params, draft=True)
        seconds = vfx_place.draft(clip, params, out)
        jdir = os.path.basename(job_dir)
        _zyg_log.info(
            f'[KANBAN-SERVER] vfx draft {jdir}/vfx_draft_{n}.mp4 — '
            f'{rec["element"]["name"]} at {rec["placement"]["depth"]:.2f}m '
            f'in {seconds:.2f}s (camera {rec["cam_source"]})'
        )
        return {
            'ok': True,
            'url': f'/inspect/media?path=out/video_studio/{jdir}/vfx_draft_{n}.mp4',
            'seconds': round(seconds, 3),
            'placement': rec['placement'],
            'camera': rec['camera'],
            'cam_source': rec['cam_source'],
            'element': {k: rec['element'][k] for k in ('key', 'name', 'mode', 'w', 'h', 'draft_only')},
            'width': vfx_place.DRAFT_WIDTH,
        }

    def _video_post(self, path):
        vd = _video_studio()
        if not vd:
            return self._send_json({'error': f'video studio unavailable: {_VIDEO_MOD["err"]}'}, 503)
        body = self._json_body()
        try:
            if path == '/video/api/render':
                # A still is the other way in: the workflow's own intro frame,
                # or anything dropped in output/video_studio/_stills/. Same
                # media-path check as the clip below — start_render() has always
                # accepted an arbitrary image, it was only ever unreachable.
                src_image = body.get('src_image') or {}
                if src_image:
                    img = self._resolve_media_path(str(src_image.get('path') or ''))
                    if not img or not img.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                        return self._send_json({'error': 'still not found'}, 400)
                    label = str(body.get('video_label') or os.path.basename(img))
                    job = vd.start_render('still', label, img, body.get('params') or {})
                    _zyg_log.info(f'[KANBAN-SERVER] video render (from still) started: {label} job {job.get("id", "")}')
                    return self._send_json({'ok': True, 'job': job})
                # Video Studio injects an existing clip, not a character —
                # resolve it through the SAME media-path check /inspect/media
                # and /inspect/thumb use (extension whitelist, per-root
                # realpath containment, medusa block), then let
                # start_render_from_video() pull its last frame as the I2V
                # starting image, continuing that clip.
                src_video = body.get('src_video') or {}
                vid = str(body.get('video_id') or '')
                vlabel = str(body.get('video_label') or vid)
                src_path = self._resolve_media_path(str(src_video.get('path') or ''))
                if not src_path or not src_path.lower().endswith('.mp4'):
                    return self._send_json({'error': 'video not found'}, 400)
                job = vd.start_render_from_video(vid, vlabel, src_path, body.get('params') or {})
                _zyg_log.info(f'[KANBAN-SERVER] video render (continue clip) started: {vlabel} job {job.get("id", "")}')
                return self._send_json({'ok': True, 'job': job})
            if path == '/video/api/assemble':
                # The SHOTS rack's own job. It takes NO source: the shot list
                # in the params names the clips it conforms, so there is
                # nothing to resolve here — same job registry and polling
                # contract as a render.
                job = vd.start_assemble(body.get('params') or {})
                _zyg_log.info(f'[KANBAN-SERVER] video assemble started: job {job.get("id", "")}')
                return self._send_json({'ok': True, 'job': job})
            if path == '/video/api/vfx/draft':
                # Synchronous on purpose: a 320p composite of a 3 s clip is
                # under a second, and a job registry + poll loop for that would
                # cost more than the work. Anything slow enough to need a job
                # is a BAKE, and a bake happens inside a render.
                return self._send_json(self._vfx_draft(vd, body))
            if path == '/video/api/still':
                # Make the start image instead of picking one: the first step of
                # a workflow that begins with a prompt and nothing else. Runs in
                # a child process (see video_stills) — this handler only queues.
                vst = _video_stills()
                if not vst:
                    return self._send_json({'error': f'still generation unavailable: {_STILL_MOD["err"]}'}, 503)
                prompt = str(body.get('prompt') or '').strip()
                if not prompt:
                    return self._send_json({'error': 'prompt is required'}, 400)
                if len(prompt) > 2000:
                    return self._send_json({'error': 'prompt too long (max 2000 chars)'}, 400)
                # Qwen wants multiples of 16; 512..1536 is the band the
                # workflow's latent sizes are tuned for.
                dims = {}
                for k, dflt in (('width', 1280), ('height', 720)):
                    try:
                        v = int(body.get(k, dflt))
                    except (TypeError, ValueError):
                        return self._send_json({'error': f'{k} must be a number'}, 400)
                    if not 512 <= v <= 1536 or v % 16:
                        return self._send_json({'error': f'{k} must be 512..1536 and a multiple of 16'}, 400)
                    dims[k] = v
                try:
                    seed = int(body.get('seed', 0))
                except (TypeError, ValueError):
                    return self._send_json({'error': 'seed must be a number'}, 400)
                # medusa=True is opt-in and set only by the Medusa app's own
                # caller (Vicky's picture_generate). It attaches the active
                # Medusa BASE LoRA and enforces the adults-only prompt floor,
                # which raises ValueError -> the 400 handler below.
                job = vst.generate(
                    prompt,
                    dims['width'],
                    dims['height'],
                    seed,
                    str(body.get('negative') or ''),
                    str(body.get('family') or 'qwen'),
                    str(body.get('label') or ''),
                    medusa=bool(body.get('medusa')),
                )
                _zyg_log.info(
                    f'[KANBAN-SERVER] still generation started: '
                    f'job {job.get("id", "")} {dims["width"]}x{dims["height"]}'
                )
                return self._send_json({'ok': True, 'job': job})
            if path == '/video/api/prompt':
                # Same compose_prompt() the worker calls — a preview built any
                # other way would be a second implementation free to drift.
                params = body.get('params') or {}
                subject = str(body.get('subject') or '')
                pos, neg = vd.compose_prompt(params, subject)
                # Preview only: the same chain arithmetic the worker does, so
                # the operator can read what each link will actually be sent
                # before spending the GPU on it.
                p = vd.sanitize(params)
                links = []
                try:
                    sec = int(p['frames']) / max(1.0, float(p['fps']))
                    n = max(1, int(math.ceil(float(p['duration_s']) / sec)))
                    links = [[lp, ln or ''] for lp, ln in vd.compose_link_prompts(p, subject, n)]
                except (TypeError, ValueError, ZeroDivisionError):
                    links = [[pos, neg or '']]
                return self._send_json({'positive': pos, 'negative': neg or '', 'links': links})
            if path == '/video/api/preset/save':
                name = vd.preset_save(str(body.get('name') or ''), body.get('params') or {})
                return self._send_json({'ok': True, 'name': name, 'presets': vd.presets()})
            if path == '/video/api/preset/load':
                return self._send_json({'ok': True, 'params': vd.preset_load(str(body.get('name') or ''))})
            if path == '/video/api/preset/delete':
                vd.preset_delete(str(body.get('name') or ''))
                return self._send_json({'ok': True, 'presets': vd.presets()})
        except ValueError as e:
            return self._send_json({'error': str(e)[:300]}, 400)
        except Exception as e:  # noqa: BLE001 — never 500 silently
            _zyg_log.info(f'[KANBAN-SERVER] video API error on {path}: {e!r}')
            return self._send_json({'error': f'{type(e).__name__}: {e}'[:300]}, 500)
        return self.send_error(404)

    def _merge_post(self, path):
        mg = _sfx_merger()
        if not mg:
            return self._send_json({'error': f'sfx merger unavailable: {_MERGE_MOD["err"]}'}, 503)
        # a 40-layer recipe with every knob is ~30 KB; the default 64 KB cap is
        # for one-field bodies
        body = self._json_body(limit=1_000_000)
        try:
            if path == '/inspect/api/merge/render':
                if not isinstance(body.get('items'), list):
                    # _json_body() answers {} for a missing, malformed or oversize
                    # body — that must not read as "an empty merge rendered fine"
                    return self._send_json({'error': 'no items in request body'}, 400)
                d = mg.render_mix(body['items'])
                if d['mix']:
                    d['url'] = '/inspect/merge/audio?p=' + d['mix']
                for it in d['items']:
                    it['url'] = '/inspect/merge/audio?p=' + it['stem']
                return self._send_json(d)
            if path == '/inspect/api/merge/stem':
                d = mg.stem(str(body.get('cat') or ''), str(body.get('f') or ''), body.get('slots') or [])
                d['ok'] = True
                d['url'] = '/inspect/merge/audio?p=' + d['stem']
                return self._send_json(d)
            if path == '/inspect/api/merge/analyze':
                d = mg.analyze(
                    str(body.get('cat') or ''),
                    str(body.get('f') or ''),
                    body.get('slots') or [],
                    pictures=body.get('pictures') is not False,
                )
                for kind, rel in list((d.get('pictures') or {}).items()):
                    d['pictures'][kind] = '/inspect/merge/asset?p=' + rel
                return self._send_json(d)
            if path == '/inspect/api/merge/export':
                d = mg.export_mix(
                    body.get('items') or [],
                    fmt=str(body.get('format') or 'wav24'),
                    rate=body.get('rate') or 48000,
                    dither=str(body.get('dither') or 'triangular_hp'),
                )
                d['url'] = '/inspect/merge/asset?p=' + d['export'] + '&dl=' + _urlquote(str(body.get('name') or 'sfx'))
                _zyg_log.info(
                    f'[KANBAN-SERVER] sfx export: {d["export"]} ({d["format"]} @ {d["rate"]} Hz, {d["bytes"]} bytes)'
                )
                return self._send_json(d)
            if path == '/inspect/api/merge/save':
                d = mg.save_mix(str(body.get('name') or ''), body.get('items') or [])
                d['url'] = '/inspect/sfx?cat=' + d['cat'] + '&f=' + _urlquote(d['file'])
                with _ALIB_LOCK:
                    _ALIB_CACHE.clear()  # the list must show it now
                _zyg_log.info(
                    f'[KANBAN-SERVER] sfx merge saved: merged/{d["file"]} '
                    f'({len(d["recipe"]["items"])} layers, {d["duration"]:.3f} s, '
                    f'licence {d["licence"]})'
                )
                return self._send_json(d)
        except ValueError as e:
            return self._send_json({'error': str(e)[:400]}, 400)
        except Exception as e:  # noqa: BLE001 — never 500 silently
            _zyg_log.info(f'[KANBAN-SERVER] merge API error on {path}: {e!r}')
            return self._send_json({'error': f'{type(e).__name__}: {e}'[:400]}, 500)
        return self.send_error(404)

    def _merge_record(self):
        """Adopt a live mic take from the mixer's Record button. The body is
        the RAW recorder blob (webm/opus, usually), with the name in the query
        string — not multipart, not JSON, so this is dispatched before
        _merge_post()'s _json_body() ever touches the socket (a JSON-parse
        attempt on binary would still consume and discard the bytes for any
        upload under its 1 MB sniff limit)."""
        mg = _sfx_merger()
        if not mg:
            return self._send_json({'error': f'sfx merger unavailable: {_MERGE_MOD["err"]}'}, 503)
        name = str(self._query().get('name') or '')[:120]
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            return self._send_json({'error': 'bad Content-Length'}, 400)
        if n <= 0:
            return self._send_json({'error': 'empty recording'}, 400)
        if n > _REC_MAX_UPLOAD:
            return self._send_json(
                {'error': f'recording is {n / 1e6:.0f} MB; the cap is {_REC_MAX_UPLOAD / 1e6:.0f} MB'}, 413
            )
        fd, tmp = tempfile.mkstemp(prefix='sfxrec-', suffix='.bin')
        got = 0
        try:
            with os.fdopen(fd, 'wb') as f:
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
        try:
            d = mg.save_recording(tmp, name)
        except ValueError as e:
            return self._send_json({'error': str(e)[:400]}, 400)
        except Exception as e:  # noqa: BLE001 — never 500 silently
            _zyg_log.info(f'[KANBAN-SERVER] recording save error: {e!r}')
            return self._send_json({'error': f'{type(e).__name__}: {e}'[:400]}, 500)
        finally:
            try:
                os.unlink(tmp)
            except OSError as _exc:
                _zyg_log.debug('upload temp %s not removed after the save: %s', tmp, _exc)
        with _ALIB_LOCK:
            _ALIB_CACHE.clear()  # the library list must show it now
        _zyg_log.info(f'[KANBAN-SERVER] sfx recording saved: recorded/{d["file"]} ({d["duration"]:.3f} s)')
        return self._send_json(d)

    def _voice_merge_post(self, path):
        vm = _voice_merger()
        if not vm:
            return self._send_json({'error': f'voice merger unavailable: {_VOICE_MERGE_MOD["err"]}'}, 503)
        body = self._json_body(limit=1_000_000)
        try:
            if path == '/voice/api/merge/render':
                if not isinstance(body.get('items'), list):
                    return self._send_json({'error': 'no items in request body'}, 400)
                d = vm.render_mix(body['items'])
                if d['mix']:
                    d['url'] = '/voice/merge/audio?p=' + d['mix']
                for it in d['items']:
                    it['url'] = '/voice/merge/audio?p=' + it['stem']
                return self._send_json(d)
            if path == '/voice/api/merge/stem':
                d = vm.stem(str(body.get('cat') or ''), str(body.get('f') or ''), body.get('slots') or [])
                d['ok'] = True
                d['url'] = '/voice/merge/audio?p=' + d['stem']
                return self._send_json(d)
            if path == '/voice/api/merge/save':
                d = vm.save_mix(str(body.get('name') or ''), body.get('items') or [])
                # _serve_sfx is a generic "stream one registered audio-kind
                # library file" route, not SFX-specific — voice_mix/voice_recorded
                # are registered the same way 'merged'/'recorded' are.
                d['url'] = '/inspect/sfx?cat=' + d['cat'] + '&f=' + _urlquote(d['file'])
                with _ALIB_LOCK:
                    _ALIB_CACHE.clear()  # the list must show it now
                _zyg_log.info(
                    f'[KANBAN-SERVER] voice merge saved: {d["cat"]}/{d["file"]} '
                    f'({len(d["recipe"]["items"])} layers, {d["duration"]:.3f} s, '
                    f'licence {d["licence"]})'
                )
                return self._send_json(d)
            if path == '/voice/api/merge/ref':
                # `whole_voice`: a Voice Studio rail row — fall back to the
                # voice's on-disk clip when it has no finished take (bench voices)
                ref = vm.voice_ref if body.get('whole_voice') else vm.take_ref
                d = ref(str(body.get('voice') or ''), str(body.get('text') or ''), body.get('params') or {})
                return self._send_json(d)
            if path == '/voice/api/merge/check':
                return self._send_json({'ok': True, 'exists': vm.check_sources(body.get('items') or [])})
        except ValueError as e:
            return self._send_json({'error': str(e)[:400]}, 400)
        except Exception as e:  # noqa: BLE001 — never 500 silently
            _zyg_log.info(f'[KANBAN-SERVER] voice merge API error on {path}: {e!r}')
            return self._send_json({'error': f'{type(e).__name__}: {e}'[:400]}, 500)
        return self.send_error(404)

    def _voice_merge_record(self):
        """Adopt a live mic take from the Voice Merger mixer's Record button —
        same raw-blob-in-the-body contract as _merge_record() above."""
        vm = _voice_merger()
        if not vm:
            return self._send_json({'error': f'voice merger unavailable: {_VOICE_MERGE_MOD["err"]}'}, 503)
        name = str(self._query().get('name') or '')[:120]
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            return self._send_json({'error': 'bad Content-Length'}, 400)
        if n <= 0:
            return self._send_json({'error': 'empty recording'}, 400)
        if n > _REC_MAX_UPLOAD:
            return self._send_json(
                {'error': f'recording is {n / 1e6:.0f} MB; the cap is {_REC_MAX_UPLOAD / 1e6:.0f} MB'}, 413
            )
        fd, tmp = tempfile.mkstemp(prefix='voicerec-', suffix='.bin')
        got = 0
        try:
            with os.fdopen(fd, 'wb') as f:
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
        try:
            d = vm.save_recording(tmp, name)
        except ValueError as e:
            return self._send_json({'error': str(e)[:400]}, 400)
        except Exception as e:  # noqa: BLE001 — never 500 silently
            _zyg_log.info(f'[KANBAN-SERVER] voice recording save error: {e!r}')
            return self._send_json({'error': f'{type(e).__name__}: {e}'[:400]}, 500)
        finally:
            try:
                os.unlink(tmp)
            except OSError as _exc:
                _zyg_log.debug('upload temp %s not removed after the save: %s', tmp, _exc)
        with _ALIB_LOCK:
            _ALIB_CACHE.clear()  # the library list must show it now
        _zyg_log.info(f'[KANBAN-SERVER] voice recording saved: {d["cat"]}/{d["file"]} ({d["duration"]:.3f} s)')
        return self._send_json(d)
