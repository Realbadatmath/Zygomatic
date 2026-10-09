# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Every route Medusa serves: the page itself, the crews proxies, Training, Models and Vicky.

Moved verbatim out of medusa_server.py (lines 3888-4355).
"""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import requests
from flask import Response, jsonify, request, send_file

from zyg_workflows import paths

import medusa_vicky

from .app import BASE_DIR, FAVICON_ICO, FAVICON_PNG, app
from .html import HTML


@app.route('/favicon.png')
def favicon_png():
    return send_file(FAVICON_PNG, mimetype='image/png')


@app.route('/favicon.ico')
def favicon_ico():
    return send_file(FAVICON_ICO, mimetype='image/x-icon')


@app.route('/')
def index():
    return Response(HTML, content_type='text/html; charset=utf-8', headers={'Cache-Control': 'no-store'})


# Crews pipeline API (the :5000 workflows server that owns the FLUX engine).
CREWS_API = os.environ.get('MEDUSA_CREWS_API', 'http://127.0.0.1:5000')


def _crews_urlopen(url, timeout, data=None, headers=None, method=None):
    """Open a crews-API *url*, refusing every scheme but http/https.

    ``MEDUSA_CREWS_API`` is configuration, so without this check a deployment could point
    the proxies below at ``file://`` and have them serve local files to the browser. This
    is the audit :func:`zyg_workflows.net.safe_urlopen` performs; that function cannot be
    used directly because these call sites need headers and a method, so this is the single
    reviewed URL open of the module.
    """
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in ('http', 'https'):
        raise ValueError(f'refusing to open {scheme or "scheme-less"} crews URL: {url}')
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)  # noqa: S310  checked above
    return urllib.request.urlopen(req, timeout=timeout)  # nosec B310  # noqa: S310  scheme checked above


@app.route('/api/generate_character', methods=['POST'])
def api_generate_character():
    """Proxy a swimwear-character request to the crews Medusa endpoint.

    Medusa (:5300) has no generation deps — the real work lives on :5000. We
    forward the form as-is. (2026-08-06: this used to also fast-reject
    sub-18 ages before proxying; that and bp_medusa's own server-side
    adults-only/catalog-clean enforcement were both removed at the operator's
    request — see medusa_pipeline.py's module docstring.)
    """
    body = request.get_json(silent=True) or {}

    try:
        data = json.dumps(body).encode('utf-8')
        with _crews_urlopen(
            CREWS_API + '/api/medusa/generate',
            15,
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST',
        ) as resp:
            return Response(resp.read().decode('utf-8'), status=resp.status, content_type='application/json')
    except urllib.error.HTTPError as exc:
        return Response(exc.read().decode('utf-8', 'replace'), status=exc.code, content_type='application/json')
    except Exception as exc:
        return jsonify(
            {
                'ok': False,
                'error': f'Could not reach crews API at {CREWS_API} (is the :5000 workflows server up?): {exc}',
            }
        ), 502


def _crews_proxy(method, path, body=None):
    """Forward a request to the crews API and return (text, status)."""
    data = json.dumps(body).encode('utf-8') if body is not None else None
    headers = {'Content-Type': 'application/json'} if data is not None else {}
    with _crews_urlopen(CREWS_API + path, 15, data=data, headers=headers, method=method) as resp:
        return resp.read().decode('utf-8'), resp.status


@app.route('/api/medusa/angles', methods=['GET'])
def api_medusa_angles_proxy():
    """Angle catalog for the Character Studio picker.

    Proxied, not copied: the list lives with the generator on :5000, so the
    picker can never offer an angle the per-cell engine cannot render. With
    :5000 down there is nothing to render a run with either, so the picker
    just says so and the default 48-angle sheet stands.
    """
    try:
        payload, status = _crews_proxy('GET', '/api/medusa/angles')
        return Response(payload, status=status, content_type='application/json')
    except urllib.error.HTTPError as exc:
        return Response(exc.read().decode('utf-8', 'replace'), status=exc.code, content_type='application/json')
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'crews API unreachable: {exc}'}), 502


@app.route('/api/medusa/pending', methods=['GET'])
def api_medusa_pending_proxy():
    try:
        payload, status = _crews_proxy('GET', '/api/medusa/pending')
        return Response(payload, status=status, content_type='application/json')
    except urllib.error.HTTPError as exc:
        return Response(exc.read().decode('utf-8', 'replace'), status=exc.code, content_type='application/json')
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'crews API unreachable: {exc}'}), 502


@app.route('/api/medusa/pending/<req_id>/decide', methods=['POST'])
def api_medusa_decide_proxy(req_id):
    body = request.get_json(silent=True) or {}
    try:
        payload, status = _crews_proxy('POST', f'/api/medusa/pending/{req_id}/decide', body)
        return Response(payload, status=status, content_type='application/json')
    except urllib.error.HTTPError as exc:
        return Response(exc.read().decode('utf-8', 'replace'), status=exc.code, content_type='application/json')
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'crews API unreachable: {exc}'}), 502


# ── Training tab: dedicated-character upload/train, proxied to crews ────────
# Storage and isolation guarantees live entirely on the crews (:5000) side in
# bp_medusa_training.py — this GUI is a thin, stateless pass-through (same
# division of labor as the Character Studio tab above).
def _training_proxy_json(method, path, body=None):
    """JSON proxy for the training endpoints — same shape as the pending-queue
    proxies above, factored out since there are several of these routes."""
    try:
        payload, status = _crews_proxy(method, path, body)
        return Response(payload, status=status, content_type='application/json')
    except urllib.error.HTTPError as exc:
        return Response(exc.read().decode('utf-8', 'replace'), status=exc.code, content_type='application/json')
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'crews API unreachable: {exc}'}), 502


# ── Models tab (2026-09-18): BASE-model LoRA training, one per model family ──
# Wildcard proxies rather than a route per endpoint: bp_medusa_models owns the
# surface, and enumerating it twice is how the two drift. The JSON proxy covers
# everything except image bytes and multipart upload, which need their own
# passthroughs below.
@app.route('/api/medusa/models', methods=['GET', 'POST'])
def api_models_root():
    body = request.get_json(silent=True) if request.method == 'POST' else None
    return _training_proxy_json(request.method, '/api/medusa/models', body)


@app.route('/api/medusa/models/<path:sub>', methods=['GET', 'POST', 'PATCH', 'DELETE'])
def api_models_sub(sub):
    # Image BYTES are not JSON — hand them to the binary passthrough.
    if re.match(r'^[^/]+/(?:images|sample)/[^/]+$', sub) and request.method == 'GET':
        return _models_image_passthrough(sub)
    body = request.get_json(silent=True) if request.method in ('POST', 'PATCH') else None
    return _training_proxy_json(request.method, f'/api/medusa/models/{sub}', body)


def _models_image_passthrough(sub):
    try:
        with _crews_urlopen(f'{CREWS_API}/api/medusa/models/{sub}', 15) as resp:
            return Response(resp.read(), status=resp.status, content_type=resp.headers.get('Content-Type', 'image/png'))
    except urllib.error.HTTPError as exc:
        return Response(exc.read(), status=exc.code, content_type='application/json')
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'crews API unreachable: {exc}'}), 502


@app.route('/api/medusa/models/<model_id>/images', methods=['POST'])
def api_models_upload_images(model_id):
    """Multipart forward — same reason as the Training tab's: hand-rolling
    multipart/form-data over urllib is fragile for binary bodies."""
    files = request.files.getlist('files')
    if not files:
        return jsonify({'ok': False, 'error': 'no files in request (field "files")'}), 400
    try:
        import requests as _rq

        upstream = [('files', (f.filename, f.stream, f.mimetype or 'application/octet-stream')) for f in files]
        r = _rq.post(f'{CREWS_API}/api/medusa/models/{model_id}/images', files=upstream, timeout=600)
        return Response(r.content, status=r.status_code, content_type=r.headers.get('Content-Type', 'application/json'))
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'upload failed: {exc}'}), 502


@app.route('/api/medusa/training/characters', methods=['GET', 'POST'])
def api_training_characters():
    body = request.get_json(silent=True) if request.method == 'POST' else None
    return _training_proxy_json(request.method, '/api/medusa/training/characters', body)


@app.route('/api/medusa/training/characters/<char_id>', methods=['GET', 'DELETE'])
def api_training_character(char_id):
    return _training_proxy_json(request.method, f'/api/medusa/training/characters/{char_id}')


@app.route('/api/medusa/training/characters/<char_id>/train', methods=['POST'])
def api_training_train(char_id):
    body = request.get_json(silent=True) or {}
    return _training_proxy_json('POST', f'/api/medusa/training/characters/{char_id}/train', body)


@app.route('/api/medusa/training/characters/<char_id>/status', methods=['GET'])
def api_training_status(char_id):
    return _training_proxy_json('GET', f'/api/medusa/training/characters/{char_id}/status')


# ── Contact sheet routes (2026-08-07) ──────────────────────────────────────
# Sheets are Medusa-only by construction: crews serves them exclusively under
# /api/medusa/training/*, which its before_request restricts to localhost, and
# this app is the only caller. They are deliberately NOT wired into the :8899
# inspection SPA, the :5000 asset manager, or the zero-public store.
@app.route('/api/medusa/training/import-root', methods=['GET'])
def api_training_import_root():
    return _training_proxy_json('GET', '/api/medusa/training/import-root')


@app.route('/api/medusa/training/scan-folder', methods=['POST'])
def api_training_scan_folder():
    body = request.get_json(silent=True) or {}
    return _training_proxy_json('POST', '/api/medusa/training/scan-folder', body)


@app.route('/api/medusa/training/import-folders', methods=['POST'])
def api_training_import_folders():
    body = request.get_json(silent=True) or {}
    return _training_proxy_json('POST', '/api/medusa/training/import-folders', body)


@app.route('/api/medusa/training/import/<batch_id>', methods=['GET'])
def api_training_import_status(batch_id):
    return _training_proxy_json('GET', f'/api/medusa/training/import/{batch_id}')


@app.route('/api/medusa/training/characters/<char_id>/sheet', methods=['GET', 'POST'])
def api_training_sheet(char_id):
    body = request.get_json(silent=True) if request.method == 'POST' else None
    return _training_proxy_json(request.method, f'/api/medusa/training/characters/{char_id}/sheet', body)


@app.route('/api/medusa/training/characters/<char_id>/body-prepare', methods=['GET', 'POST'])
def api_training_body_prepare(char_id):
    body = (request.get_json(silent=True) or {}) if request.method == 'POST' else None
    return _training_proxy_json(request.method, f'/api/medusa/training/characters/{char_id}/body-prepare', body)


@app.route('/api/medusa/training/sheets', methods=['GET'])
def api_training_sheets():
    return _training_proxy_json('GET', '/api/medusa/training/sheets')


@app.route('/api/medusa/training/sheets/build-all', methods=['POST'])
def api_training_sheets_build_all():
    body = request.get_json(silent=True) or {}
    return _training_proxy_json('POST', '/api/medusa/training/sheets/build-all', body)


@app.route('/api/medusa/training/loras', methods=['GET'])
def api_training_loras():
    return _training_proxy_json('GET', '/api/medusa/training/loras')


@app.route('/api/medusa/training/loras/<char_id>/<family>/sample/<name>', methods=['GET'])
def api_training_lora_sample(char_id, family, name):
    """Binary proxy for a LoRA validation render."""
    try:
        with _crews_urlopen(f'{CREWS_API}/api/medusa/training/loras/{char_id}/{family}/sample/{name}', 30) as resp:
            return Response(resp.read(), status=resp.status, content_type=resp.headers.get('Content-Type', 'image/png'))
    except urllib.error.HTTPError as exc:
        return Response(exc.read(), status=exc.code, content_type='application/json')
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'crews API unreachable: {exc}'}), 502


@app.route('/api/medusa/training/characters/<char_id>/sheet/page/<page>', methods=['GET'])
def api_training_sheet_page(char_id, page):
    """Binary proxy for a montage page — mirrors the training-image proxy below."""
    try:
        with _crews_urlopen(f'{CREWS_API}/api/medusa/training/characters/{char_id}/sheet/page/{page}', 30) as resp:
            return Response(resp.read(), status=resp.status, content_type=resp.headers.get('Content-Type', 'image/png'))
    except urllib.error.HTTPError as exc:
        return Response(exc.read(), status=exc.code, content_type=exc.headers.get('Content-Type', 'application/json'))
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'crews API unreachable: {exc}'}), 502


@app.route('/api/medusa/training/characters/<char_id>/images/<image_id>', methods=['DELETE'])
def api_training_delete_image(char_id, image_id):
    return _training_proxy_json('DELETE', f'/api/medusa/training/characters/{char_id}/images/{image_id}')


@app.route('/api/medusa/training/characters/<char_id>/images/<image_id>', methods=['GET'])
def api_training_get_image(char_id, image_id):
    """Binary passthrough (gallery thumbnails) — urllib handles bytes fine, no
    need for requests here."""
    try:
        with _crews_urlopen(f'{CREWS_API}/api/medusa/training/characters/{char_id}/images/{image_id}', 15) as resp:
            return Response(resp.read(), status=resp.status, content_type=resp.headers.get('Content-Type', 'image/png'))
    except urllib.error.HTTPError as exc:
        return Response(exc.read(), status=exc.code, content_type='application/json')
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'crews API unreachable: {exc}'}), 502


@app.route('/api/medusa/training/characters/<char_id>/images', methods=['POST'])
def api_training_upload_images(char_id):
    """Multipart forward — uses requests (available under system python3) since
    hand-rolling multipart/form-data over urllib is fragile for binary bodies."""
    files = request.files.getlist('images')
    if not files:
        return jsonify({'ok': False, 'error': 'no images in request (field "images")'}), 400
    try:
        upstream_files = [('images', (f.filename, f.stream, f.mimetype or 'application/octet-stream')) for f in files]
        resp = requests.post(
            f'{CREWS_API}/api/medusa/training/characters/{char_id}/images',
            files=upstream_files,
            timeout=120,
        )
        return Response(
            resp.content, status=resp.status_code, content_type=resp.headers.get('Content-Type', 'application/json')
        )
    except requests.RequestException as exc:
        return jsonify({'ok': False, 'error': f'crews API unreachable: {exc}'}), 502


# ── Vicky: Medusa's own chat assistant (2026-09-16) ──────────────────────────
# See medusa_vicky.py for what runs behind this — a `claude -p --model sonnet`
# subprocess, rooted in this folder, whose only standing rules are
# VICKY_RULES.md. This app owns the job entirely (no crews proxy): Vicky reads
# and edits real files under this directory tree via her own real tools.
@app.route('/api/vicky/start', methods=['POST'])
def api_vicky_start():
    body = request.get_json(silent=True) or {}
    return jsonify(medusa_vicky.start_job(body))


@app.route('/api/vicky/job', methods=['GET'])
def api_vicky_job():
    return jsonify(medusa_vicky.job_status(request.args.get('id', '')))


@app.route('/api/vicky/cancel', methods=['POST'])
def api_vicky_cancel():
    body = request.get_json(silent=True) or {}
    return jsonify(medusa_vicky.cancel_job(body))


@app.route('/api/vicky/active', methods=['GET'])
def api_vicky_active():
    """Check this is 0 before restarting medusa.service — a restart kills
    whatever Vicky job is running under it."""
    return jsonify(medusa_vicky.active_jobs())


@app.route('/api/vicky/chats', methods=['GET'])
def api_vicky_chats():
    """Every saved chat, newest first, plus which one a refresh reopens."""
    out, status = medusa_vicky.handle_get('/api/vicky/chats', request.args)
    return jsonify(out), status


@app.route('/api/vicky/pictures', methods=['GET'])
def api_vicky_pictures():
    """Every picture any chat delivered, newest first - the Pictures gallery."""
    out, status = medusa_vicky.handle_get('/api/vicky/pictures', request.args)
    return jsonify(out), status


@app.route('/api/vicky/chat', methods=['GET'])
def api_vicky_chat():
    """One chat with its messages. Also reports a turn still running in it, so
    a browser refresh mid-answer reattaches instead of losing the reply."""
    out, status = medusa_vicky.handle_get('/api/vicky/chat', request.args)
    return jsonify(out), status


@app.route('/api/vicky/chat/<action>', methods=['POST'])
def api_vicky_chat_action(action):
    """new | open | rename | engine | delete (delete takes {id} or {all: true})."""
    body = request.get_json(silent=True) or {}
    out, status = medusa_vicky.handle_post(f'/api/vicky/chat/{action}', body)
    return jsonify(out), status


@app.route('/api/vicky/chat/export', methods=['GET'])
def api_vicky_chat_export():
    """Download one chat as Markdown (the panel's Save button) or raw JSON."""
    chat = medusa_vicky.open_chat(request.args.get('id', ''))
    stamp = str(chat.get('created') or '')[:10] or 'chat'
    slug = re.sub(r'[^a-z0-9]+', '-', (chat.get('title') or 'chat').lower()).strip('-')[:48] or 'chat'
    if (request.args.get('format') or 'md').lower() == 'json':
        return Response(
            json.dumps(chat, ensure_ascii=False, indent=1, default=str),
            mimetype='application/json',
            headers={'Content-Disposition': f'attachment; filename="vicky-{stamp}-{slug}.json"'},
        )
    return Response(
        medusa_vicky.chat_markdown(chat),
        mimetype='text/markdown',
        headers={'Content-Disposition': f'attachment; filename="vicky-{stamp}-{slug}.md"'},
    )


@app.route('/api/vicky/engines', methods=['GET'])
def api_vicky_engines():
    """The two assistants the panel's model switcher offers, with live
    availability — Vicky on the Claude CLI, Victor on local Ollama."""
    out, status = medusa_vicky.handle_get('/api/vicky/engines', request.args)
    return jsonify(out), status


@app.route('/api/vicky/info', methods=['GET'])
def api_vicky_info():
    out, status = medusa_vicky.handle_get('/api/vicky/info', request.args)
    return jsonify(out), status


# Where a picture the assistant rendered is allowed to come from. The path in a
# chat message was written by the tool that made the file, but this route reads
# whatever the browser sends, so it is checked against these roots rather than
# trusted: without that, any file on the box is one crafted query away.
# ZYG_MEDUSA_IMAGE_ROOTS (colon-separated) adds more.
VICKY_IMAGE_ROOTS = [
    os.path.realpath(p)
    for p in [
        str(paths.ZYG_OUTPUT_ROOT),  # stills + pipeline output
        str(paths.ZYG_LORA_DATASETS / 'storyteller_chars'),  # character sheets
        BASE_DIR,  # Medusa's own folder
    ]
    + [p for p in (os.environ.get('ZYG_MEDUSA_IMAGE_ROOTS') or '').split(':') if p.strip()]
]
VICKY_IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.webp', '.gif')


@app.route('/api/vicky/image', methods=['GET'])
def api_vicky_image():
    """Serve one rendered picture into the chat panel.

    The panel draws a thumbnail per image on a Vicky message; this is the only
    thing that turns the file path stored there into pixels in the browser.
    """
    raw = request.args.get('path', '')
    if not raw:
        return jsonify({'ok': False, 'error': 'path is required'}), 400
    path = os.path.realpath(raw)
    if not path.lower().endswith(VICKY_IMAGE_EXT):
        return jsonify({'ok': False, 'error': 'not an image'}), 400
    if not any(path == r or path.startswith(r + os.sep) for r in VICKY_IMAGE_ROOTS):
        return jsonify({'ok': False, 'error': 'outside the picture roots'}), 403
    if not os.path.isfile(path):
        return jsonify({'ok': False, 'error': 'no such file'}), 404
    return send_file(path, conditional=True)


@app.route('/api/vicky/upload', methods=['POST'])
def api_vicky_upload():
    """Save an uploaded video (or other binary) to the Vicky uploads folder.

    Images are passed as base64 inside the /api/vicky/start JSON body so they
    never touch the filesystem — this route is only for videos and other large
    files that should not be base64-encoded in-flight.  The returned path is
    inside UPLOAD_DIR (data/runtime/vicky/uploads/), which sits within Medusa's
    own folder tree that Vicky's tools are already fenced to.
    """
    f = request.files.get('file')
    if not f:
        return jsonify({'ok': False, 'error': 'no file'}), 400
    try:
        path = medusa_vicky.save_upload(f.filename or 'upload', f.read())
        size = os.path.getsize(path)
        return jsonify({'ok': True, 'path': path, 'name': f.filename or 'upload', 'size': size})
    except Exception as exc:  # noqa: BLE001
        return jsonify({'ok': False, 'error': str(exc)}), 500
