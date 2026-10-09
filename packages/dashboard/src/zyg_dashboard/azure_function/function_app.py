# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Azure Function: PipelineWebhook
─────────────────────────────────────────────────────────────────────────────
HTTP-triggered entry point for external callers (webhooks, integrations).
Validates the incoming request and forwards it to the zero_public_server
running on your machine.

Deploy to Azure Functions (Python v2 model):
  func init --python
  func new --name PipelineWebhook --template "HTTP trigger"
  Replace function_app.py with this file.
  Set application settings in Azure Portal:
    PIPELINE_FORWARD_URL = https://<your-cloudflare-tunnel-or-ip>:5001/api/submit
    PIPELINE_SECRET_KEY  = <shared secret — same as ZERO_PUBLIC_TOKEN>

Free tier: 1 million calls/month.
"""

import json
import os
import logging

import azure.functions as func
import urllib.request
import urllib.error
import urllib.parse

_ALLOWED_FORWARD_SCHEMES = ('http', 'https')

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

_FORWARD_URL = os.getenv('PIPELINE_FORWARD_URL', '')
_SECRET_KEY = os.getenv('PIPELINE_SECRET_KEY', '')
_ALLOWED_TYPES = {'generate', 'caption', 'metadata'}  # job types this gate accepts


@app.route(route='PipelineWebhook', methods=['POST'])
def pipeline_webhook(req: func.HttpRequest) -> func.HttpResponse:
    """Validate and forward a generation request to the local pipeline."""
    logging.info('[AzFunc] PipelineWebhook invoked')

    # ── Authentication ────────────────────────────────────────────────────────
    auth_header = req.headers.get('X-Pipeline-Key', '') or req.headers.get('Authorization', '')
    if _SECRET_KEY and auth_header.removeprefix('Bearer ').strip() != _SECRET_KEY:
        logging.warning('[AzFunc] Unauthorized request — bad key')
        return func.HttpResponse('Unauthorized', status_code=401)

    # ── Parse body ────────────────────────────────────────────────────────────
    try:
        body = req.get_json()
    except (ValueError, TypeError):
        return func.HttpResponse('Invalid JSON body', status_code=400)

    job_type = body.get('type', 'generate')
    if job_type not in _ALLOWED_TYPES:
        return func.HttpResponse(f'Unknown job type: {job_type}', status_code=400)

    if not body.get('prompt', '').strip():
        return func.HttpResponse('Missing prompt', status_code=400)

    # ── Forward to local pipeline ─────────────────────────────────────────────
    if not _FORWARD_URL:
        logging.error('[AzFunc] PIPELINE_FORWARD_URL not set')
        return func.HttpResponse('Gateway not configured', status_code=503)

    # The forward URL comes from an application setting, so its scheme is checked here:
    # urlopen would otherwise happily follow file:// or any other scheme it is handed.
    if urllib.parse.urlsplit(_FORWARD_URL).scheme not in _ALLOWED_FORWARD_SCHEMES:
        logging.error('[AzFunc] PIPELINE_FORWARD_URL must be an http(s) URL')
        return func.HttpResponse('Gateway not configured', status_code=503)

    try:
        payload_bytes = json.dumps(body).encode('utf-8')
        request_obj = urllib.request.Request(  # noqa: S310  scheme checked above
            _FORWARD_URL,
            data=payload_bytes,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {_SECRET_KEY}',
            },
            method='POST',
        )
        with urllib.request.urlopen(request_obj, timeout=30) as resp:  # nosec B310  # noqa: S310  scheme checked above
            resp_body = resp.read().decode('utf-8')
            return func.HttpResponse(resp_body, status_code=resp.status, mimetype='application/json')
    except urllib.error.HTTPError as e:
        logging.error('[AzFunc] Forward HTTP error: %s', e)
        return func.HttpResponse(f'Pipeline error: {e.code}', status_code=502)
    except Exception as e:
        logging.exception('[AzFunc] Forward failed')
        return func.HttpResponse(f'Gateway error: {e}', status_code=502)
