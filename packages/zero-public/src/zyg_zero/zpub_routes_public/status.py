# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Status, streaming, download and the public content-credential door.

Moved verbatim out of ``zpub_routes_public.py`` (lines 1007-1380).
"""

from zyg_zero.zpub_routes_public.core import (
    AVG_PIPELINE_SECONDS,
    Response,
    _ams_iso,
    _get_pipeline_status,
    _get_running,
    _jobs_for_library,
    _load_job,
    _queue_length,
    _queue_position,
    _save_job,
    _seal,
    _session_id,
    _set_running,
    _zpub_log,
    bp,
    json,
    jsonify,
    limiter,
    os,
    paths,
    render_template,
    request,
    send_from_directory,
    stream_with_context,
    tempfile,
    time,
)


def _reconcile_zpub_job_with_pipeline(job: dict) -> dict:
    """Sync a persisted ``running`` Zero Public job with the main app pipeline status."""
    if job.get('status') != 'running':
        return job
    pipeline_id = (job.get('pipeline_id') or '').strip()
    if not pipeline_id:
        return job
    status_data = _get_pipeline_status(pipeline_id)
    if not status_data:
        return job
    if status_data.get('error') == 'not found':
        job['status'] = 'failed'
        job['error'] = job.get('error') or 'Pipeline not found on main server'
        job['completed_at'] = _ams_iso()
        _save_job(job)
        _set_running(None)
        return job
    ps = status_data.get('status', '')
    job['current_stage'] = status_data.get('current_stage') or job.get('current_stage', '')
    job['pipeline_status'] = ps
    if ps == 'completed':
        job['status'] = 'done'
        job['completed_at'] = _ams_iso()
        job['result'] = status_data.get('result', '')
        job['output_dir'] = status_data.get('output_dir', '')
        job['output_files'] = status_data.get('output_files', [])
        job['error'] = None
        _save_job(job)
        _set_running(None)
    elif ps in ('failed', 'stopped', 'interrupted'):
        job['status'] = 'failed'
        job['error'] = status_data.get('error') or (
            'Pipeline interrupted — server restarted' if ps == 'interrupted' else 'Pipeline failed'
        )
        job['completed_at'] = _ams_iso()
        _save_job(job)
        _set_running(None)
    return job


@bp.route('/api/status/<job_id>')
def api_status(job_id):
    job = _load_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found. It may have expired (48 h TTL).'}), 404

    job = _reconcile_zpub_job_with_pipeline(job)

    position = eta_min = ahead = 0
    if job['status'] == 'queued':
        position = _queue_position(job_id)
        running = _get_running()
        ahead = max(0, position + (1 if running else 0) - 1)
        eta_min = max(1, ahead * AVG_PIPELINE_SECONDS // 60) if ahead > 0 else 1

    return jsonify(
        {
            'job_id': job['job_id'],
            'status': job['status'],
            'department': job.get('department'),
            'current_stage': job.get('current_stage', ''),
            'prompt': job.get('prompt', ''),
            'created_at': job.get('created_at'),
            'started_at': job.get('started_at'),
            'completed_at': job.get('completed_at'),
            'result': job.get('result'),
            'error': job.get('error'),
            'output_files': job.get('output_files', []),
            'queue_position': position,
            'ahead': ahead,
            'eta_minutes': eta_min,
        }
    )


@bp.route('/api/stream/<job_id>')
def api_stream(job_id):
    """SSE stream — pushes job status every 3 s until the job is done or failed."""

    def generate():
        last_stage = None
        last_status = None
        heartbeat = 0

        for _ in range(1500):  # 1500 × 3 s = 75 min max
            job = _load_job(job_id)
            if not job:
                yield f'data: {json.dumps({"error": "job not found"})}\n\n'
                return

            job = _reconcile_zpub_job_with_pipeline(job)

            status = job.get('status', 'unknown')
            stage = job.get('current_stage', '')
            changed = status != last_status or stage != last_stage
            heartbeat += 1

            if changed or heartbeat >= 20:  # force heartbeat every ~60 s
                last_status = status
                last_stage = stage
                heartbeat = 0

                position = eta_min = ahead = 0
                if status == 'queued':
                    position = _queue_position(job_id)
                    running = _get_running()
                    ahead = max(0, position + (1 if running else 0) - 1)
                    eta_min = max(1, ahead * AVG_PIPELINE_SECONDS // 60) if ahead > 0 else 1

                payload = {
                    'status': status,
                    'current_stage': stage,
                    'department': job.get('department'),
                    'queue_position': position,
                    'ahead': ahead,
                    'eta_minutes': eta_min,
                    'output_files': job.get('output_files', []),
                    'result': job.get('result'),
                    'error': job.get('error'),
                }
                yield f'data: {json.dumps(payload)}\n\n'

                if status in ('done', 'failed'):
                    return

            time.sleep(3)

        yield f'data: {json.dumps({"error": "stream timeout — please refresh"})}\n\n'

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )


@bp.route('/download/<job_id>/<filename>')
def download_file(job_id, filename):
    job = _load_job(job_id)
    if not job or job.get('status') != 'done':
        return 'File is not available yet.', 404

    safe_name = os.path.basename(filename)  # prevent path traversal
    output_dir = job.get('output_dir', '')
    if not output_dir or not os.path.isdir(output_dir):
        return 'Output directory not found.', 404

    fpath = os.path.join(output_dir, safe_name)
    if not os.path.isfile(fpath):
        return 'File not found.', 404

    # The last gate before a stranger holds the file: under ZYG_C2PA=strict nothing leaves
    # here without a content credential. In warn mode the download is not slowed by a second
    # manifest read — the pipeline already logged whatever it could not sign.
    if (os.environ.get('ZYG_C2PA', 'warn') or '').strip().lower() == 'strict':
        if os.path.splitext(safe_name)[1].lower() in _seal.SUPPORTED and not _seal.is_sealed(fpath):
            return jsonify({'error': 'deliverable is not sealed'}), 409

    return send_from_directory(output_dir, safe_name, as_attachment=True)


@bp.route('/api/queue')
def api_queue():
    return jsonify(
        {
            'queue_length': _queue_length(),
            'is_running': bool(_get_running()),
            'avg_pipeline_minutes': AVG_PIPELINE_SECONDS // 60,
        }
    )


@bp.route('/api/token_jobs/<token>')
def api_token_jobs(token):
    """Return the persistent Library sidebar contents for this browser.

    Kept at this URL for frontend compatibility, but the list is no longer
    scoped to just this invite token — see _jobs_for_library — so it
    survives the token expiring or the visitor being handed a new link.
    """
    tok = token if token and len(token) >= 8 else ''
    jobs = _jobs_for_library(tok, _session_id())
    return jsonify(
        [
            {
                'job_id': j['job_id'],
                'prompt': j.get('prompt', ''),
                'status': j.get('status', 'unknown'),
                'created_at': j.get('created_at', ''),
                'completed_at': j.get('completed_at', ''),
                'output_files': j.get('output_files', []),
                'error': j.get('error', ''),
            }
            for j in jobs
        ]
    )


# ── Content credentials — the public verification door ─────────────────────────
# Every deliverable leaves the studio with a C2PA manifest embedded in it
# (zyg_workflows.provenance_seal). A signature only means something to a verifier
# that holds the issuing root, so the PUBLIC root certificate is published at
# /.well-known/zygomatic-c2pa-root.pem and anyone can read a file's credential
# here, in c2patool, or on the Content Credentials site.
#
# The signer key and the certificate chain NEVER leave the operator's machine:
# this route reads one path and one path only — the one ZYG_C2PA_ROOT_CERT names
# — and refuses anything whose first bytes are not a PEM certificate header, so a
# mis-pointed variable cannot turn into a key leak.
_C2PA_ROOT_CERT_DEFAULT = '~/.config/zygomatic/c2pa/root/ca.pem'
_C2PA_ROOT_CERT_NAME = 'zygomatic-c2pa-root.pem'
_PEM_CERT_HEADER = '-----BEGIN CERTIFICATE-----'
# A root certificate is ~1 KB; this is the most of the named file we will ever read or serve.
_PEM_MAX_BYTES = 64 * 1024

_VERIFY_MAX_BYTES = 64 * 1024 * 1024
_VERIFY_CHUNK_BYTES = 1024 * 1024


def _c2pa_root_cert_path() -> str:
    """The configured public root certificate, ``~`` expanded. Read per request, not at import."""
    return os.path.expanduser(os.environ.get('ZYG_C2PA_ROOT_CERT', _C2PA_ROOT_CERT_DEFAULT) or '')


@bp.route('/.well-known/zygomatic-c2pa-root.pem')
@limiter.exempt
def c2pa_root_cert():
    """Hand out the public root certificate so anyone can verify our signatures.

    404 when the file is absent, unreadable, or does not begin with a PEM
    certificate header — the last check is what keeps a private key, a chain or
    any other PEM out of the response.
    """
    path = _c2pa_root_cert_path()
    if not path or not os.path.isfile(path):
        return jsonify({'error': 'Not found'}), 404
    try:
        with open(path, encoding='utf-8') as fh:
            pem = fh.read(_PEM_MAX_BYTES)
    except (OSError, UnicodeDecodeError):
        return jsonify({'error': 'Not found'}), 404
    if not pem.startswith(_PEM_CERT_HEADER):
        return jsonify({'error': 'Not found'}), 404
    resp = Response(pem, mimetype='application/x-pem-file')
    resp.headers['Content-Disposition'] = f'inline; filename="{_C2PA_ROOT_CERT_NAME}"'
    resp.headers['Cache-Control'] = 'public, max-age=3600'
    return resp


#: Rows for the result block when the request never reached the reader (no file, too large).
_EMPTY_REPORT = {
    'name': '',
    'sealed': 'no',
    'state': 'not read',
    'trusted': 'no',
    'issuer': '—',
    'time': '—',
    'pipeline': '—',
    'run_id': '—',
    'models': '—',
    'verdict': 'Nothing was read: this file is not sealed as far as this page knows.',
    'verdict_class': 'is-warn',
}


def _verify_view(result=None, status: int = 200):
    """Render the verification page, with a result block when there is one."""
    return render_template('zero_verify.html', result=result, max_mb=_VERIFY_MAX_BYTES // (1024 * 1024)), status


def _verify_report(path: str, name: str) -> dict:
    """``provenance_seal.verify`` turned into the page's rows and a plain-language verdict."""
    info = _seal.verify(path)
    prov = info.get('provenance') or {}
    models = []
    for model in prov.get('models') or []:
        label = model.get('name') if isinstance(model, dict) else model
        if label:
            models.append(str(label))
    state = info.get('state') or 'unknown'
    sealed = bool(info.get('sealed'))
    trusted = bool(info.get('trusted'))
    if not sealed:
        verdict = (
            'This file is not sealed: it carries no content credential. Either it did not come from '
            'Zygomatic, or it was re-encoded, screenshotted or stripped on its way to you.'
        )
        verdict_class = 'is-bad'
    elif state == 'Invalid':
        verdict = (
            'This file carries a content credential, but it no longer matches the bytes: the file has '
            'been modified since it was signed.'
        )
        verdict_class = 'is-bad'
    elif trusted:
        verdict = (
            'Genuine: this file was signed by Zygomatic, the signature chains to the root certificate '
            'published on this site, and nothing in the file has changed since.'
        )
        verdict_class = 'is-ok'
    else:
        verdict = (
            'This file carries a valid, unmodified content credential, but the signature does not chain '
            'to the Zygomatic root certificate — so it was signed by someone else, or our root is not '
            'installed here.'
        )
        verdict_class = 'is-warn'
    return {
        'name': name,
        'sealed': 'yes' if sealed else 'no',
        'state': state,
        'trusted': 'yes' if trusted else 'no',
        'issuer': info.get('issuer') or '—',
        'time': info.get('time') or '—',
        'pipeline': prov.get('pipeline') or '—',
        'run_id': prov.get('run_id') or '—',
        'models': ', '.join(models) if models else '—',
        'error': info.get('error') or '',
        'verdict': verdict,
        'verdict_class': verdict_class,
    }


@bp.route('/verify')
@limiter.exempt
def verify_page():
    """The public verification page: what a content credential is and how to check one."""
    return _verify_view()


@bp.route('/verify', methods=['POST'])
@limiter.limit('60 per hour')
def verify_file():
    """Read the content credential of an uploaded file and throw the upload away.

    The bytes are streamed into a tempfile under ``paths.tmp_dir('verify')``
    (owner-only) because the reader needs a path, are capped at 64 MB while they
    are written, and the file is deleted in the ``finally`` — a visitor's media is
    never stored, logged or served back.
    """
    upload = request.files.get('file')
    name = os.path.basename((upload.filename or '').strip()) if upload else ''
    if upload is None or not name:
        return _verify_view({'error': 'Choose a file first.', **_EMPTY_REPORT}, 400)
    ext = os.path.splitext(name)[1].lower()[:16]
    handle, tmp_path = tempfile.mkstemp(dir=str(paths.tmp_dir('verify')), prefix='verify_', suffix=ext)
    try:
        written = 0
        with os.fdopen(handle, 'wb') as out:
            while True:
                chunk = upload.stream.read(_VERIFY_CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > _VERIFY_MAX_BYTES:
                    return _verify_view(
                        {
                            'error': f'That file is larger than {_VERIFY_MAX_BYTES // (1024 * 1024)} MB.',
                            **_EMPTY_REPORT,
                        },
                        413,
                    )
                out.write(chunk)
        report = _verify_report(tmp_path, name)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    _zpub_log('c2pa_verify', ip=request.remote_addr or 'unknown', sealed=report['sealed'], state=report['state'])
    return _verify_view(report)
