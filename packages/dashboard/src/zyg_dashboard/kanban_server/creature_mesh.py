# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Creature sheets, kids music/series files, movement and mesh jobs.

Split verbatim out of ``kanban_server.py`` (lines 1652-2049) on 2026-10-06, when that
3,172-line module became this package. The bodies are byte-for-byte the originals;
only the enclosing ``class`` line is new. :class:`zyg_dashboard.kanban_server._Handler`
puts the mixins back together in their original order, so the MRO finds every method
exactly where the single class had it.
"""

import os
import re
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


class _CreatureMeshMixin:
    def _creature_sheet(self):
        """Serve the parked review sheet for one creature (id is 12-hex, the
        filename is fixed — no caller-supplied path reaches the filesystem)."""
        cid = self._query().get('id', '')
        if not _CREATURE_ID_RE.match(cid):
            return self.send_error(404)
        for cand in (
            os.path.join(_CREATURE_ROOT, cid, 'contact_sheet', 'sheet.png'),
            os.path.join(_CREATURE_ROOT, cid, 'sheet.png'),
        ):
            fp = os.path.realpath(cand)
            if fp.startswith(_CREATURE_ROOT + os.sep) and os.path.isfile(fp):
                try:
                    with open(fp, 'rb') as fh:
                        data = fh.read()
                except OSError:
                    break
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except BrokenPipeError as _exc:
                    _zyg_log.debug('client closed the connection before the png was sent: %s', _exc)
                return
        return self.send_error(404)

    def _creature_img(self):
        """Serve one creature image. Same fail-closed shape as _serve_image: the
        id is 12-hex, the category picks the directory (the caller never supplies
        a path fragment), the filename is regex-bound and basename-only, and the
        final realpath must still sit inside the category dir inside the tree it
        belongs to — 'val' resolves into the OUTPUT tree, every other category
        into the DATASET tree."""
        q = self._query()
        cid, cat, name = q.get('id', ''), q.get('cat', ''), q.get('name', '')
        if cat not in _CREATURE_CATS or not name or not _NAME_RE.match(name):
            return self.send_error(404)
        if os.path.basename(name) != name:
            return self.send_error(404)
        w = _creature_weights(cid)
        # The licence block is enforced HERE too, not only in the listing: a
        # cached page, a bookmarked lightbox URL or a hand-typed query would
        # otherwise still pull FLUX.1-dev pixels out of a tab that claims not to
        # show them. Withholding is a property of the creature, not of the DOM.
        ds_for_fam = _creature_dir(cid, _CREATURE_ROOT)
        fam = (w or {}).get('family') or (_creature_manifest(ds_for_fam).get('train_family') if ds_for_fam else '')
        if _is_flux1(fam):
            return self.send_error(404)
        if cat == 'val':
            if not w:
                return self.send_error(404)
            cat_dir = os.path.realpath(os.path.join(w['dir'], 'validation_images'))
            root = _CREATURE_OUT_ROOT
        else:
            ds = _creature_dir(cid, _CREATURE_ROOT)
            if not ds:
                return self.send_error(404)
            sub = _CREATURE_CATS[cat][0]
            cat_dir = os.path.realpath(os.path.join(ds, sub) if sub else ds)
            root = _CREATURE_ROOT
        if not (cat_dir.startswith(root + os.sep) and os.path.isdir(cat_dir)):
            return self.send_error(404)
        fp = os.path.realpath(os.path.join(cat_dir, name))
        if not (fp.startswith(cat_dir + os.sep) and os.path.isfile(fp)):
            return self.send_error(404)
        self._send_image_thumb_or_full(fp, q.get('thumb') == '1')

    def _km_file(self):
        """Stream one file from one song folder. The id is regex-bound and the
        filename must be one of a FIXED set of exact names — nothing the caller
        sends is ever joined as a path fragment."""
        q = self._query()
        d = _km_dir(q.get('id', ''))
        fn = q.get('f', '')
        mime = _KM_FILES.get(fn)
        if d and not mime:
            # A storyboard frame. The caller's string is PARSED, never joined:
            # only the leading letter and the integer survive, and the name is
            # rebuilt from a fixed format string.
            fm = _KM_FRAME_RE.match(fn)
            if fm:
                kind, idx, ext = fm.group(1), int(fm.group(2)), fm.group(3)
                if idx <= 9999:
                    fn = os.path.join('frames', f'{kind}{idx:03d}.{ext}')
                    mime = 'image/png' if ext == 'png' else 'image/jpeg'
        if not d or not mime:
            return self.send_error(404)
        fp = os.path.realpath(os.path.join(d, fn))
        if not (fp.startswith(d + os.sep) and os.path.isfile(fp)):
            return self.send_error(404)
        # ?dl=1 turns the same stream into a download, named after the SONG
        # rather than after the leg — "Red Train to the Sea - master.mp3" is
        # what belongs in someone's downloads folder, not "master.mp3" for the
        # fourth time. The name is built here, from the manifest, and sanitised:
        # it ends up in a Content-Disposition header, so nothing the caller sent
        # may reach it.
        attach = None
        if q.get('dl', '') in ('1', 'true', 'yes'):
            attach = _km_download_name(d, fn)
        return self._send_ranged(fp, mime, cache='public, max-age=3600', attach=attach)

    def _km_post(self, path):
        body = self._json_body(limit=200_000)
        # Filing is a LOCAL write (shelf.json beside the song), so it is handled
        # here rather than forwarded — the pipeline API owns rendering, not
        # where a finished song is shelved.
        if path == '/inspect/api/kidsmusic/shelf':
            out, code = _km_file_song(
                str(body.get('id') or ''),
                str(body.get('family') or '').strip().lower(),
                str(body.get('shelf') or '').strip().lower(),
            )
            return self._send_json(out, code)
        if path == '/inspect/api/kidsmusic/start':
            out, code = _km_forward('/api/internal/kidsmusic/start', body, 'POST', timeout=30)
            if code == 200:
                _zyg_log.info(
                    f'[KANBAN-SERVER] kidsmusic run started: {str((body.get("song") or {}).get("theme"))[:80]!r}'
                )
            return self._send_json(out, code)
        if path == '/inspect/api/kidsmusic/stop':
            out, code = _km_forward('/api/internal/kidsmusic/stop', body, 'POST')
            return self._send_json(out, code)
        if path == '/inspect/api/kidsmusic/delete':
            out, code = _km_forward('/api/internal/kidsmusic/delete', body, 'POST')
            if code == 200:
                _KM_CACHE['data'] = None  # the list must stop showing it
            return self._send_json(out, code)
        if path == '/inspect/api/kidsmusic/remix':
            # Mastering + re-muxing the video takes seconds, not milliseconds.
            out, code = _km_forward('/api/internal/kidsmusic/remix', body, 'POST', timeout=240)
            if code == 200:
                _KM_CACHE['data'] = None  # the card must show the new mix
            return self._send_json(out, code)
        return self.send_error(404)

    def _ks_post(self, path):
        """Children's series start/stop — the same same-host hop as kidsmusic's:
        this process never imports a runner, it forwards to the GUI, which owns
        the job registry and the single ComfyUI submit lock."""
        body = self._json_body(limit=50_000)
        if path == '/inspect/api/kidseries/start':
            out, code = _km_forward('/api/internal/kidseries/start', body, 'POST', timeout=30)
            if code == 200:
                _zyg_log.info(
                    f'[KANBAN-SERVER] kids series started: '
                    f'{str(body.get("series"))[:60]!r} '
                    f'test={bool(body.get("test_mode"))}'
                )
            return self._send_json(out, code)
        if path == '/inspect/api/kidseries/stop':
            out, code = _km_forward('/api/internal/kidseries/stop', body, 'POST')
            return self._send_json(out, code)
        return self.send_error(404)

    def _mv_post(self, path):
        """Movement Studio start/stop — same same-host hop as kidsmusic's:
        this process never imports wan_vace_service itself."""
        body = self._json_body(limit=50_000)
        if path == '/inspect/api/movement/start':
            out, code = _km_forward('/api/internal/movement/start', body, 'POST', timeout=30)
            if code == 200:
                _zyg_log.info(
                    f'[KANBAN-SERVER] movement render started: '
                    f'{body.get("subject_type")}/{body.get("subject_id")} '
                    f'preset={body.get("preset")!r} mode={body.get("mode")!r}'
                )
            return self._send_json(out, code)
        if path == '/inspect/api/movement/stop':
            out, code = _km_forward('/api/internal/movement/stop', body, 'POST')
            return self._send_json(out, code)
        # 2026-09-02 option surface. The prompt preview forwards rather than
        # composing here for the reason bp_movement._resolve_prompt gives: two
        # composition paths is how a preview starts lying about what will render.
        if path == '/inspect/api/movement/prompt':
            out, code = _km_forward('/api/internal/movement/prompt', body, 'POST', timeout=20)
            return self._send_json(out, code)
        if path == '/inspect/api/movement/presets':
            out, code = _km_forward('/api/internal/movement/presets', body, 'POST')
            return self._send_json(out, code)
        # 2026-09-02 S05. The plate chip is a manifest read, so it is cheap and
        # synchronous. 2026-09-18: the driver extraction is an hour of GPU work,
        # so this POST only STARTS the job and returns its id — the GET forward
        # further down polls its job.json. One clip at a time is the same
        # discipline the render itself follows, enforced by bp_movement.
        if path == '/inspect/api/movement/plate':
            out, code = _km_forward('/api/internal/movement/plate', body, 'POST', timeout=30)
            return self._send_json(out, code)
        if path == '/inspect/api/movement/driver':
            out, code = _km_forward('/api/internal/movement/driver', body, 'POST', timeout=30)
            return self._send_json(out, code)
        if path == '/inspect/api/movement/delete':
            out, code = _km_forward('/api/internal/movement/delete', body, 'POST')
            if code == 200:
                _MV_CACHE['data'] = None  # the library must stop showing it
            return self._send_json(out, code)
        return self.send_error(404)

    def _mesh_post(self, path):
        """derive / reissue / gate, plus the job poll. Every argument that
        reaches the CLI is either a registry name or a value parsed here."""
        body = self._json_body(limit=20_000) or {}
        names = _mesh_names()
        if path == '/mesh/api/job':
            jid = str(body.get('job_id') or '')
            if not _MESH_JOB_ID_RE.match(jid):
                return self._send_json({'error': 'bad job id'}, 400)
            job = _MESH_JOBS_MEM.get(jid)
            if not job:
                return self._send_json({'error': 'unknown job'}, 404)
            out = {k: v for k, v in job.items() if k != 'argv'}
            out['cmd'] = ' '.join(job['argv'])
            return self._send_json(out)

        if path == '/mesh/api/gate':
            name = str(body.get('name') or '')
            if name not in names:
                return self._send_json({'error': f'not a registered body: {name!r}', 'known': sorted(names)}, 400)
            # anthro check is the report; it never touches a vertex, so no dry run
            out, code = _mesh_job_start('gate', name, [_MESH_PY, '-m', 'geom.anthro', 'check', name])
            return self._send_json(out, code)

        if path == '/mesh/api/reissue':
            name = str(body.get('name') or '')
            if name not in names:
                return self._send_json({'error': f'not a registered body: {name!r}', 'known': sorted(names)}, 400)
            dry = bool(body.get('dry_run', True))
            if not dry and name not in _MESH_DRYRUN_OK:
                # The operator approves a reissue by looking at two hashes. A
                # confirm with no dry run behind it in this process is a click
                # on a number nobody has seen.
                return self._send_json(
                    {
                        'error': f'run a dry run on {name} first — a reissue is approved '
                        'against its BEFORE and AFTER cage hashes'
                    },
                    409,
                )
            argv = [_MESH_PY, '-m', 'geom.mesh_skeletons', 'reissue', name]
            if dry:
                argv.append('--dry-run')
            if body.get('force'):
                argv.append('--force')
            anat = str(body.get('set_anatomy') or '').strip()
            if anat:
                # k=v,... only — this DECLARES an input, so it is recorded by the
                # CLI with its previous value and must not be free text.
                if not re.match(r'^[A-Za-z0-9_]+=-?[0-9.]+(,[A-Za-z0-9_]+=-?[0-9.]+)*$', anat):
                    return self._send_json(
                        {
                            'error': 'set_anatomy must be k=v,... with numeric values, '
                            f'e.g. toe_declash=0.005 (got {anat!r})'
                        },
                        400,
                    )
                argv += ['--set-anatomy', anat]
            out, code = _mesh_job_start('reissue', name, argv, dry_run=dry)
            return self._send_json(out, code)

        if path == '/mesh/api/derive':
            # derive MAKES a body, so its id is new and cannot be checked against
            # the registry — it is checked against the registry the other way:
            # a name that already exists is refused rather than overwritten.
            cid = str(body.get('char_id') or '')
            if not re.match(r'^[A-Za-z0-9_-]{1,64}$', cid):
                return self._send_json({'error': 'char_id must be [A-Za-z0-9_-]{1,64}'}, 400)
            if cid in names:
                return self._send_json(
                    {
                        'error': f'{cid} is already registered — use reissue, which rebuilds '
                        'it from its own params.json, rather than deriving over it'
                    },
                    409,
                )
            argv = [_MESH_PY, '-m', 'geom.mesh_skeletons', 'derive', cid]
            base = str(body.get('base') or '')
            if base:
                if base not in ('male', 'female'):
                    return self._send_json({'error': "base must be 'male' or 'female'"}, 400)
                argv += ['--base', base]
            # The remaining flags are k=v lists and free-text notes. Each is
            # matched against the shape the CLI documents; anything else is a
            # 400 here rather than an argparse error inside a background job.
            for key, flag, pat in (
                ('phenotype', '--phenotype', r'^[A-Za-z0-9_]+=-?[0-9.]+(,[A-Za-z0-9_]+=-?[0-9.]+)*$'),
                ('bone_scale', '--bone-scale', r'^[A-Za-z0-9_.]+=-?[0-9.]+(,[A-Za-z0-9_.]+=-?[0-9.]+)*$'),
                ('local', '--local', r'^[A-Za-z0-9_.]+=-?[0-9.]+(,[A-Za-z0-9_.]+=-?[0-9.]+)*$'),
                ('anatomy', '--anatomy', r'^[A-Za-z0-9_]+=-?[0-9.]+(,[A-Za-z0-9_]+=-?[0-9.]+)*$'),
                ('target_height', '--target-height', r'^[0-9.]+$'),
                ('ancestry', '--ancestry', r'^[A-Za-z0-9 _/-]{1,80}$'),
                ('stylization_intent', '--stylization-intent', r'^[A-Za-z0-9 _/-]{1,80}$'),
                ('declared_by', '--declared-by', r'^[A-Za-z0-9 _@.-]{1,80}$'),
                ('note', '--note', r'^[^\x00-\x1f]{1,400}$'),
            ):
                val = str(body.get(key) or '').strip()
                if not val:
                    continue
                if not re.match(pat, val):
                    return self._send_json({'error': f'{key} has the wrong shape: {val!r}'}, 400)
                argv += [flag, val]
            if body.get('no_inherit_locals'):
                argv.append('--no-inherit-locals')
            out, code = _mesh_job_start('derive', cid, argv)
            if out.get('ok'):
                _MESH_CACHE['data'] = None
            return self._send_json(out, code)
        return self.send_error(404)

    def _mv_file(self):
        """Stream the finished clip for one movement job. Fixed filename —
        generate_vace_static_clip always writes vace_static.mp4 into its
        out_dir, so nothing the caller sends is ever joined as a path."""
        jid = self._query().get('id', '')
        if not _MV_JOB_ID_RE.match(jid):
            return self.send_error(404)
        fp = os.path.realpath(os.path.join(_MV_OUT_ROOT, jid, 'vace_static.mp4'))
        if not (fp.startswith(_MV_OUT_ROOT + os.sep) and os.path.isfile(fp)):
            return self.send_error(404)
        return self._send_ranged(fp, 'video/mp4', cache='no-store')

    def _mv_thumb(self):
        """Cached poster JPEG for one movement job's clip — same extract-once
        pattern as _serve_thumb, but resolved against _MV_OUT_ROOT directly
        since that tree is not one of _MEDIA_ROOTS."""
        jid = self._query().get('id', '')
        if not _MV_JOB_ID_RE.match(jid):
            return self.send_error(404)
        fp = os.path.realpath(os.path.join(_MV_OUT_ROOT, jid, 'vace_static.mp4'))
        if not (fp.startswith(_MV_OUT_ROOT + os.sep) and os.path.isfile(fp)):
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
            _zyg_log.debug('client closed the connection before the sheet image was sent: %s', _exc)

    def _creature_decide(self):
        """Approve or reject a creature parked at the sheet-review gate."""
        import urllib.error
        import urllib.request

        body = self._json_body()
        cid = str(body.get('id') or '')
        action = str(body.get('action') or '').lower()
        if not _CREATURE_ID_RE.match(cid) or action not in ('approve', 'reject'):
            return self._send_json({'error': 'need {id: <12-hex>, action: approve|reject}'}, 400)
        token = _internal_token()
        if not token:
            return self._send_json(
                {'error': 'ZERO_PUBLIC_TOKEN not set — cannot authenticate to the pipeline API'}, 503
            )
        payload = json.dumps({'reason': 'rejected from the Kanban review gate'} if action == 'reject' else {}).encode(
            'utf-8'
        )
        req = urllib.request.Request(  # noqa: S310  _MAIN_APP's scheme is checked at import
            f'{_MAIN_APP}/api/internal/creature/{cid}/{action}',
            data=payload,
            method='POST',
            headers={'Content-Type': 'application/json', 'X-Zero-Public-Token': token},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310  # noqa: S310  scheme checked at import
                out = json.loads(resp.read().decode('utf-8') or '{}')
            _zyg_log.info(f'[KANBAN-SERVER] creature {cid} {action}d from the board')
            return self._send_json(out)
        except urllib.error.HTTPError as e:
            try:
                out = json.loads(e.read().decode('utf-8') or '{}')
            except (ValueError, OSError):
                out = {'error': f'pipeline API returned {e.code}'}
            return self._send_json(out, e.code)
        except (urllib.error.URLError, OSError, ValueError) as e:
            return self._send_json({'error': f'pipeline API unreachable: {e}'}, 502)
