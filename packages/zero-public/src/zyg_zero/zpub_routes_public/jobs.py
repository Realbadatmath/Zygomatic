# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Job routes: the index, the job page, uploads, the chunked preview upload, submit.

Moved verbatim out of ``zpub_routes_public.py`` (lines 477-1006).
"""

from zyg_zero.zpub_routes_public.core import (
    ALLOWED_IMAGE_EXTS,
    ALLOWED_VIDEO_EXTS,
    AVG_PIPELINE_SECONDS,
    CHUNK_UPLOAD_ROOT,
    MAX_UPLOAD_BYTES,
    MAX_VIDEO_BYTES,
    PREVIEW_CHUNK_BYTES,
    RATE_LIMIT_PER_HOUR,
    UPLOAD_ROOT,
    _ams_iso,
    _check_rate_limit,
    _enqueue,
    _gate_response,
    _get_running,
    _jobs_for_library,
    _link_session_job,
    _link_token_job,
    _load_job,
    _parse_creature_options,
    _parse_model_family,
    _parse_pipeline_options,
    _pending_store,
    _queue_length,
    _require_api_session,
    _save_job,
    _session_id,
    _session_invite,
    _session_jobs,
    _token_check,
    _token_use,
    _zpub_log,
    bp,
    datetime,
    json,
    jsonify,
    limiter,
    os,
    public_url,
    re,
    render_template,
    request,
    send_from_directory,
    session,
    shutil,
    uuid,
)


@bp.route('/')
def index():
    # Root URL is only for admin. Regular users must enter via /u/<token>.
    if not session.get('is_zpub_admin'):
        return _gate_response()
    sid = _session_id()
    _zpub_log(
        'page_visit',
        ip=request.remote_addr or 'unknown',
        session_id=sid[:8] + '…',
        user_agent=request.headers.get('User-Agent', '')[:120],
    )
    recent = []
    for jid in reversed(_session_jobs(sid)):
        j = _load_job(jid)
        if j:
            recent.append(j)
        if len(recent) >= 5:
            break
    return render_template(
        'zero_public.html',
        recent_jobs=recent,
        active_job_id=None,
        invite_mode='active',
        # noqa below: '__admin__' is the public sentinel for an admin session, not a secret
        invite_token='__admin__',  # noqa: S106  sentinel, not a secret
    )


@bp.route('/job/<job_id>')
def job_page(job_id):
    if not _session_invite() and not session.get('is_zpub_admin'):
        return _gate_response()
    sid = _session_id()
    tok = _session_invite() or '__admin__'
    return render_template(
        'zero_public.html',
        recent_jobs=_jobs_for_library(tok, sid),
        active_job_id=job_id,
        invite_mode='active',
        invite_token=tok,
        invite_label='',
        invite_used=0,
        invite_max=0,
    )


@bp.route('/uploads/<path:subpath>')
@limiter.exempt
def uploads(subpath: str):
    """Serve user-uploaded media from the runtime uploads folder.

    Note: This endpoint is invite-gated; only active invite/admin sessions can fetch.
    Exempt from the global 300/hour limit — preview pages load many thumbnails at once.
    """
    if not _session_invite() and not session.get('is_zpub_admin'):
        return _gate_response()
    _session_id()  # ensure session exists
    # Prevent path traversal; only allow within UPLOAD_ROOT
    safe_sub = os.path.normpath(subpath).lstrip(os.sep)
    abs_path = os.path.abspath(os.path.join(UPLOAD_ROOT, safe_sub))
    if not abs_path.startswith(os.path.abspath(UPLOAD_ROOT) + os.sep):
        return jsonify({'error': 'Invalid path'}), 400
    folder = os.path.dirname(abs_path)
    fname = os.path.basename(abs_path)
    if not os.path.isfile(abs_path):
        return jsonify({'error': 'Not found'}), 404
    resp = send_from_directory(folder, fname, as_attachment=False)
    # Browser cache cuts duplicate requests (mirrors, hover, refresh).
    # UUID filenames are immutable — aggressive cache = instant refresh in browser.
    resp.headers['Cache-Control'] = 'private, max-age=31536000, immutable'
    return resp


def _preview_chunk_dir(upload_id: str) -> str:
    return os.path.join(CHUNK_UPLOAD_ROOT, upload_id)


def _cleanup_preview_chunks(upload_id: str) -> None:
    d = _preview_chunk_dir(upload_id)
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)


def _finalize_preview_upload(sid: str, ext: str, assembled_path: str) -> tuple[str | None, str | None]:
    """Move assembled file into the visitor preview folder; return (url, error)."""
    up_dir = os.path.join(UPLOAD_ROOT, 'preview', sid)
    os.makedirs(up_dir, exist_ok=True)
    safe_name = f'{uuid.uuid4().hex}{ext}'
    dest = os.path.join(up_dir, safe_name)
    try:
        shutil.move(assembled_path, dest)
    except Exception as e:
        return None, f'Upload failed: {str(e)[:120]}'
    return f'/uploads/preview/{sid}/{safe_name}', None


@bp.route('/api/preview_upload', methods=['POST'])
@limiter.exempt
def api_preview_upload():
    """Upload media for preview windows so it survives refresh.

    Images can be stored as data: URLs in localStorage, but videos exceed quota and
    disappear on refresh. This endpoint stores videos on disk and returns a URL.

    Large videos use chunked upload (upload_id + chunk_index + total_chunks) so each
    request stays under the Cloudflare tunnel body-size limit (~100 MB).
    """
    blocked = _require_api_session()
    if blocked:
        return blocked
    sid = _session_id()

    upload_id = (request.form.get('upload_id') or '').strip()
    chunk_index_raw = request.form.get('chunk_index')
    total_chunks_raw = request.form.get('total_chunks')
    original_name = (request.form.get('filename') or '').strip()

    # ── Chunked upload (videos through site proxy) ───────────────────────────
    if upload_id and chunk_index_raw is not None and total_chunks_raw is not None:
        if not re.fullmatch(r'[0-9a-f]{32}', upload_id):
            return jsonify({'success': False, 'error': 'Invalid upload_id'}), 400
        try:
            chunk_index = int(chunk_index_raw)
            total_chunks = int(total_chunks_raw)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Invalid chunk metadata'}), 400
        if total_chunks < 1 or chunk_index < 0 or chunk_index >= total_chunks:
            return jsonify({'success': False, 'error': 'Invalid chunk index'}), 400

        ext = os.path.splitext(original_name)[1].lower()
        if ext not in ALLOWED_VIDEO_EXTS:
            return jsonify({'success': False, 'error': f'Unsupported file type: {ext}'}), 400

        try:
            total_size = int(request.form.get('total_size') or 0)
        except (TypeError, ValueError):
            total_size = 0
        if total_size <= 0 or total_size > MAX_VIDEO_BYTES:
            mb = MAX_VIDEO_BYTES // (1024 * 1024)
            return jsonify({'success': False, 'error': f'File too large (max {mb} MB)'}), 413

        f = request.files.get('file')
        if not f:
            return jsonify({'success': False, 'error': 'No chunk provided'}), 400

        chunk_dir = _preview_chunk_dir(upload_id)
        os.makedirs(chunk_dir, exist_ok=True)
        meta_path = os.path.join(chunk_dir, '_meta.json')
        if chunk_index == 0:
            meta = {
                'sid': sid,
                'filename': original_name,
                'ext': ext,
                'total_chunks': total_chunks,
                'total_size': total_size,
            }
            with open(meta_path, 'w', encoding='utf-8') as mf:
                json.dump(meta, mf)
        elif not os.path.isfile(meta_path):
            return jsonify({'success': False, 'error': 'Upload session expired — retry upload'}), 400
        else:
            with open(meta_path, encoding='utf-8') as mf:
                meta = json.load(mf)
            if meta.get('sid') != sid:
                return jsonify({'success': False, 'error': 'Upload session mismatch'}), 403
            if meta.get('total_chunks') != total_chunks or meta.get('total_size') != total_size:
                return jsonify({'success': False, 'error': 'Chunk metadata mismatch'}), 400

        chunk_path = os.path.join(chunk_dir, f'{chunk_index:05d}')
        try:
            f.save(chunk_path)
        except Exception as e:
            _cleanup_preview_chunks(upload_id)
            return jsonify({'success': False, 'error': f'Chunk save failed: {str(e)[:120]}'}), 500

        try:
            chunk_sz = os.path.getsize(chunk_path)
        except OSError:
            chunk_sz = 0
        if chunk_sz > PREVIEW_CHUNK_BYTES + (512 * 1024):
            _cleanup_preview_chunks(upload_id)
            return jsonify({'success': False, 'error': 'Chunk too large'}), 413

        if chunk_index + 1 < total_chunks:
            return jsonify({'success': True, 'chunk': chunk_index, 'complete': False})

        # Last chunk — assemble and finalize
        assembled = os.path.join(chunk_dir, '_assembled')
        try:
            with open(assembled, 'wb') as out:
                for i in range(total_chunks):
                    part = os.path.join(chunk_dir, f'{i:05d}')
                    if not os.path.isfile(part):
                        raise FileNotFoundError(f'missing chunk {i}')
                    with open(part, 'rb') as inp:
                        shutil.copyfileobj(inp, out)
            final_sz = os.path.getsize(assembled)
        except Exception as e:
            _cleanup_preview_chunks(upload_id)
            return jsonify({'success': False, 'error': f'Assembly failed: {str(e)[:120]}'}), 500

        if final_sz != total_size:
            _cleanup_preview_chunks(upload_id)
            return jsonify({'success': False, 'error': 'Uploaded size mismatch — retry upload'}), 400

        url, err = _finalize_preview_upload(sid, ext, assembled)
        _cleanup_preview_chunks(upload_id)
        if err:
            return jsonify({'success': False, 'error': err}), 500
        return jsonify({'success': True, 'url': url, 'is_video': True, 'complete': True})

    # ── Single-request upload (images + small videos) ────────────────────────
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'success': False, 'error': 'No file provided'}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in (ALLOWED_IMAGE_EXTS | ALLOWED_VIDEO_EXTS):
        return jsonify({'success': False, 'error': f'Unsupported file type: {ext}'}), 400

    # Size check (prefer Content-Length but validate stream too)
    try:
        f.seek(0, 2)
        sz = f.tell()
        f.seek(0)
    except Exception:
        sz = 0
    max_bytes = MAX_VIDEO_BYTES if ext in ALLOWED_VIDEO_EXTS else MAX_UPLOAD_BYTES
    if sz and sz > max_bytes:
        return jsonify({'success': False, 'error': f'File too large (max {max_bytes // (1024 * 1024)} MB)'}), 413

    up_dir = os.path.join(UPLOAD_ROOT, 'preview', sid)
    os.makedirs(up_dir, exist_ok=True)
    safe_name = f'{uuid.uuid4().hex}{ext}'
    dest = os.path.join(up_dir, safe_name)
    try:
        f.save(dest)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Upload failed: {str(e)[:120]}'}), 500

    url = f'/uploads/preview/{sid}/{safe_name}'
    return jsonify({'success': True, 'url': url, 'is_video': (ext in ALLOWED_VIDEO_EXTS)})


@bp.route('/api/submit', methods=['POST'])
@limiter.limit('10 per hour')
def api_submit():
    sid = _session_id()
    is_admin = session.get('is_zpub_admin', False)

    # Support both JSON and multipart/form-data (video uploads)
    _VALID_VS = frozenset(
        {'cinematic', 'anime', 'disney', 'art', 'realism', 'scenery', '3d_render', 'filmic', 'mjv6', 'manga'}
    )
    ct = request.content_type or ''
    if ct.startswith('multipart/form-data') or ct.startswith('application/x-www-form-urlencoded'):
        data = request.form
        prompt = (data.get('prompt') or '').strip()
        pipeline_style = (data.get('pipeline_style') or 'documentary').strip()
        _mf_raw = (data.get('model_family') or '').strip().lower()
        model_family = _parse_model_family(_mf_raw)
        pipeline_options = _parse_pipeline_options(data.get('pipeline_options'))
        try:
            video_duration_minutes = max(0.25, min(3.0, float(data.get('video_duration_minutes', 0.5))))
        except (ValueError, TypeError):
            video_duration_minutes = 0.5
        _nar_raw = (data.get('narration_enabled') or '').lower()
        narration_enabled = _nar_raw not in ('false', '0', 'no')
        _vs_raw = (data.get('visual_style') or 'cinematic').strip().lower()
        _sm_raw = (data.get('scene_mode') or 'independent').strip().lower()
        ending_text = (data.get('ending_text') or '').strip()[:200]
        char_id = (data.get('char_id') or data.get('character_id') or '').strip()
        creature_options = _parse_creature_options(data.get('creature_options'))
    else:
        data = request.get_json(silent=True) or {}
        prompt = (data.get('prompt') or '').strip()
        pipeline_style = (data.get('pipeline_style') or 'documentary').strip()
        model_family = _parse_model_family(data.get('model_family'))
        pipeline_options = _parse_pipeline_options(data.get('pipeline_options'))
        try:
            video_duration_minutes = max(0.25, min(3.0, float(data.get('video_duration_minutes', 0.5))))
        except (ValueError, TypeError):
            video_duration_minutes = 0.5
        _nar_val = data.get('narration_enabled')
        narration_enabled = (
            bool(_nar_val)
            if isinstance(_nar_val, bool)
            else str(_nar_val).lower() not in ('false', '0', 'no')
            if _nar_val is not None
            else True
        )
        _vs_raw = (data.get('visual_style') or 'cinematic').strip().lower()
        _sm_raw = (data.get('scene_mode') or 'independent').strip().lower()
        ending_text = (data.get('ending_text') or '').strip()[:200]
        char_id = (data.get('char_id') or data.get('character_id') or '').strip()
        creature_options = _parse_creature_options(data.get('creature_options'))

    visual_style = _vs_raw if _vs_raw in _VALID_VS else 'cinematic'
    scene_mode = _sm_raw if _sm_raw in ('independent', 'continuous') else 'independent'
    _td_sec = pipeline_options.get('total_duration_sec')
    if _td_sec and pipeline_style in ('video', 'intro', 'manga'):
        video_duration_minutes = max(3.5 / 60.0, min(3.0, float(_td_sec) / 60.0))

    if pipeline_style not in ('documentary', 'video', 'intro', 'storyteller', 'manga', 'creature', 'templates'):
        pipeline_style = 'documentary'

    # Documentary + narrator voice → always burn subtitles into the output.
    if pipeline_style == 'documentary' and narration_enabled:
        pipeline_options['burn_subtitles'] = True

    # Admin sessions bypass invite token and rate limiting entirely
    if is_admin:
        token = '__admin__'  # noqa: S105  '__admin__' is the public sentinel for an admin session, not a secret
    else:
        # Use token from POST body if provided, else fall back to session
        token = (data.get('invite_token') or '').strip() or _session_invite()

        # Block direct API calls with no session invite
        if not token:
            _zpub_log('gate_blocked', ip=request.remote_addr or 'unknown', session_id=sid[:8] + '…', path='/api/submit')
            return jsonify({'error': 'Access denied. A valid invite link is required.'}), 403

    if not prompt:
        return jsonify({'error': 'Please enter a prompt.'}), 400
    if len(prompt) > 2000:
        return jsonify({'error': 'Prompt too long (max 2 000 characters).'}), 400

    # Atomically consume one credit from the invite token (skipped for admin)
    if not is_admin:
        use_result = _token_use(token)
        _zpub_log('debug_token_use_result', token=token[:8] + '…', use_result=use_result)
        if not use_result.get('ok', False):
            reason = use_result.get('reason', 'unknown')
            _zpub_log(
                'invite_rejected',
                ip=request.remote_addr or 'unknown',
                session_id=sid[:8] + '…',
                invite_token=token[:8] + '…',
                reason=reason,
                prompt_preview=prompt[:80],
            )
            if reason == 'manual_permission_required':
                # Queue the request for operator approval instead of hard-blocking
                entry = use_result.get('entry', {})
                req_id = 'preq_' + uuid.uuid4().hex[:12]
                body_data = request.get_json(force=True, silent=True) or {}
                pending_req = {
                    'id': req_id,
                    'token': token,
                    'label': entry.get('label', ''),
                    'invite_url': f'{public_url()}/u/{token}' if token else '',
                    'prompt': prompt[:500],
                    'pipeline': body_data.get('pipeline_type', body_data.get('type', 'unknown')),
                    'voice': body_data.get('voice', ''),
                    'style': body_data.get('style', ''),
                    'model': body_data.get('model', ''),
                    'ip': request.remote_addr or 'unknown',
                    'session_id': sid,
                    'body_snapshot': body_data,
                    'requested_at': datetime.utcnow().isoformat() + 'Z',
                    'status': 'pending',
                    'decided_at': None,
                    'approved_job_id': None,
                }
                _pending_store(pending_req)
                _zpub_log(
                    'manual_pending_queued',
                    ip=request.remote_addr or 'unknown',
                    req_id=req_id,
                    label=entry.get('label', ''),
                    prompt_preview=prompt[:80],
                )
                return jsonify(
                    {
                        'pending': True,
                        'pending_id': req_id,
                        'message': 'Your request is awaiting manual approval. You will receive a notification in your library once it is processed. You can safely close this page.',
                    }
                ), 202
            msgs = {
                'exhausted': 'This invite link has reached its request limit.',
                'expired': 'This invite link has expired.',
                'revoked': 'This invite link has been revoked.',
                'not_found': 'Invite link not found.',
                'main_app_unreachable': 'Server is temporarily unavailable. Please try again shortly.',
            }
            return jsonify({'error': msgs.get(reason, 'Invite link is no longer valid.')}), 403

    # Extra check for manual permission in case _token_use was bypassed somehow or not checked
    if not is_admin:
        token_info = _token_check(token)
        if token_info.get('valid') and token_info.get('entry', {}).get('permission') == 'manual':
            entry = token_info.get('entry', {})
            req_id = 'preq_' + uuid.uuid4().hex[:12]
            body_data = request.get_json(force=True, silent=True) or {}
            pending_req = {
                'id': req_id,
                'token': token,
                'label': entry.get('label', ''),
                'invite_url': f'{public_url()}/u/{token}' if token else '',
                'prompt': prompt[:500],
                'pipeline': body_data.get('pipeline_type', body_data.get('type', 'unknown')),
                'voice': body_data.get('voice', ''),
                'style': body_data.get('style', ''),
                'model': body_data.get('model', ''),
                'ip': request.remote_addr or 'unknown',
                'session_id': sid,
                'body_snapshot': body_data,
                'requested_at': datetime.utcnow().isoformat() + 'Z',
                'status': 'pending',
                'decided_at': None,
                'approved_job_id': None,
            }
            _pending_store(pending_req)
            return jsonify(
                {
                    'pending': True,
                    'pending_id': req_id,
                    'message': 'Your request is awaiting manual approval. You will receive a notification in your library once it is processed.',
                }
            ), 202

    ip = request.remote_addr or 'unknown'
    if not is_admin and not _check_rate_limit(ip):
        _zpub_log(
            'rate_limited',
            ip=ip,
            session_id=sid[:8] + '…',
            invite_token=token[:8] + '…' if token else None,
            prompt_preview=prompt[:80],
        )
        return jsonify({'error': f'Rate limit reached: max {RATE_LIMIT_PER_HOUR} jobs per hour per connection.'}), 429

    job_id = uuid.uuid4().hex

    # Save uploaded images if any (video style)
    uploaded_image_paths = []
    if pipeline_style in ('video', 'manga', 'creature'):
        upload_files = request.files.getlist('images')
        if upload_files:
            upload_dir = os.path.join(UPLOAD_ROOT, job_id)
            os.makedirs(upload_dir, exist_ok=True)
            for uf in upload_files:
                if not uf or not uf.filename:
                    continue
                ext = os.path.splitext(uf.filename)[1].lower()
                if ext not in ALLOWED_IMAGE_EXTS:
                    continue
                uf.seek(0, 2)
                sz = uf.tell()
                uf.seek(0)
                if sz > MAX_UPLOAD_BYTES:
                    continue
                safe_name = f'{uuid.uuid4().hex}{ext}'
                dest = os.path.join(upload_dir, safe_name)
                uf.save(dest)
                uploaded_image_paths.append(dest)

    _short_doc_mode = (
        pipeline_style == 'documentary'
        and pipeline_options.get('total_duration_sec')
        and float(pipeline_options['total_duration_sec']) < 300
    )

    job = {
        'job_id': job_id,
        'session_id': sid,
        'invite_token': token,
        'ip': ip,
        'prompt': prompt,
        'pipeline_style': pipeline_style,
        'short_doc_mode': _short_doc_mode,
        'video_duration_minutes': video_duration_minutes,
        'narration_enabled': narration_enabled,
        'visual_style': visual_style,
        'model_family': model_family,
        'pipeline_options': pipeline_options,
        'scene_mode': scene_mode,
        'ending_text': ending_text,
        'uploaded_image_paths': uploaded_image_paths,
        'creature_options': creature_options if pipeline_style == 'creature' else None,
        'char_id': char_id if pipeline_style == 'video' else '',
        'status': 'queued',
        'department': None,
        'pipeline_id': None,
        'created_at': _ams_iso(),
        'started_at': None,
        'completed_at': None,
        'current_stage': 'Waiting in queue…',
        'output_dir': None,
        'output_files': [],
        'result': None,
        'error': None,
    }
    _save_job(job)
    _enqueue(job_id)
    _link_session_job(sid, job_id)
    if token and token != '__admin__':  # noqa: S105  '__admin__' is the public sentinel for an admin session, not a secret
        _link_token_job(token, job_id)

    qlen = _queue_length()
    running = _get_running()
    ahead = qlen + (1 if running else 0) - 1

    _zpub_log(
        'submit',
        ip=ip,
        session_id=sid[:8] + '…',
        job_id=job_id,
        invite_token=token[:8] + '…' if token else None,
        prompt_preview=prompt[:120],
        prompt_len=len(prompt),
        queue_position=qlen,
        ahead=max(0, ahead),
        queue_running=bool(running),
    )
    eta_min = max(1, ahead * AVG_PIPELINE_SECONDS // 60) if ahead > 0 else 1

    return jsonify(
        {
            'job_id': job_id,
            'status': 'queued',
            'queue_position': qlen,
            'ahead': max(0, ahead),
            'eta_minutes': eta_min,
            'job_url': f'/job/{job_id}',
        }
    )
