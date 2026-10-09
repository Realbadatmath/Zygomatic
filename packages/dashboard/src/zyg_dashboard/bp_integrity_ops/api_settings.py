# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from zyg_dashboard.bp_integrity_ops.constants import (
    CANONICAL_LLMS,
    DEPENDENCIES_CONFIG,
    _HF_ENV_PATH,
    _require_csrf,
    block_spectator_mutation,
    bp,
    importlib,
    jsonify,
    os,
    request,
    threading,
)


import logging as _zyg_logging

# Bound by ASSIGNMENT (not `from .constants import _zyg_log`) so the moved
# `_zyg_log.debug(...)` calls keep compiling to the same method form.
# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_integrity_ops')


def _hf_read_env_token() -> str:
    """Read HF_TOKEN from .env file. Returns '' if not set."""
    try:
        with open(_HF_ENV_PATH, 'r') as fh:
            for line in fh:
                line = line.strip()
                if line.startswith('HF_TOKEN='):
                    return line[len('HF_TOKEN=') :].strip().strip('"').strip("'")
    except (OSError, UnicodeDecodeError) as _exc:
        # Falls back to the process env, and if that is empty every HF endpoint
        # answers "No token set" — the operator needs the real reason.
        _zyg_log.warning('HF token .env unreadable, falling back to the process env: %s', _exc)
    return ''


def _hf_active_token() -> str:
    """Resolved HF token: .env file wins over stale process env."""
    return _hf_read_env_token() or os.environ.get('HF_TOKEN', '') or ''


def _hf_write_env_token(token: str) -> None:
    """Write or update HF_TOKEN in .env file."""
    try:
        with open(_HF_ENV_PATH, 'r') as fh:
            lines = fh.readlines()
        found = False
        for i, line in enumerate(lines):
            if line.startswith('HF_TOKEN='):
                lines[i] = f'HF_TOKEN={token}\n'
                found = True
                break
        if not found:
            # Append under API Keys section or at end
            lines.append(f'HF_TOKEN={token}\n')
        with open(_HF_ENV_PATH, 'w') as fh:
            fh.writelines(lines)
        # Apply immediately to running process
        os.environ['HF_TOKEN'] = token
    except Exception as exc:
        raise RuntimeError(f'Could not write .env: {exc}') from exc


@bp.route('/api/settings/huggingface', methods=['GET'])
def hf_settings_get():
    """Return current HF_TOKEN (masked except last 4 chars) and login status."""
    tok = _hf_active_token()
    masked = ('hf_' + '*' * (len(tok) - 7) + tok[-4:]) if len(tok) > 7 else ('*' * len(tok) if tok else '')
    return jsonify({'set': bool(tok), 'masked': masked})


@bp.route('/api/settings/huggingface', methods=['POST'])
def hf_settings_save():
    """Save HF_TOKEN to .env and apply immediately."""
    r = block_spectator_mutation()
    if r is not None:
        return r
    csrf_err = _require_csrf()
    if csrf_err:
        return csrf_err
    try:
        data = request.get_json() or {}
        token = data.get('token', '').strip()
        if not token:
            return jsonify({'success': False, 'error': 'Token cannot be empty'}), 400
        if token.startswith('hf_') is False and not token.startswith('****'):
            return jsonify({'success': False, 'error': 'HuggingFace tokens start with hf_'}), 400
        if '****' in token:
            return jsonify({'success': True, 'message': 'Token unchanged (masked value)'}), 200
        _hf_write_env_token(token)
        os.environ['HF_TOKEN'] = token
        return jsonify({'success': True, 'message': 'HuggingFace token saved and applied.'})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@bp.route('/api/settings/huggingface/test', methods=['POST'])
def hf_settings_test():
    """Verify the stored HF_TOKEN by calling the HuggingFace whoami API."""
    r = block_spectator_mutation()
    if r is not None:
        return r
    csrf_err = _require_csrf()
    if csrf_err:
        return csrf_err
    try:
        tok = _hf_active_token()
        if not tok:
            return jsonify({'success': False, 'error': 'No token set'}), 400
        import urllib.request
        import urllib.error
        import json as _json

        # Fine-grained tokens require whoami-v2; legacy /api/whoami returns 401.
        req = urllib.request.Request(  # noqa: S310  literal https URL, no caller input in it
            'https://huggingface.co/api/whoami-v2',
            headers={'Authorization': f'Bearer {tok}'},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:  # nosec B310  # noqa: S310  literal https URL, no caller input in it
            info = _json.loads(resp.read().decode())
        username = info.get('name', info.get('fullname', 'unknown'))
        return jsonify({'success': True, 'username': username, 'message': f'Logged in as: {username}'})
    except urllib.error.HTTPError as e:
        return jsonify({'success': False, 'error': f'HuggingFace rejected token (HTTP {e.code})'}), 200
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 200


@bp.route('/api/settings/huggingface/download', methods=['POST'])
def hf_settings_download():
    """Queue IPAdapter weight download from HuggingFace (background thread)."""
    r = block_spectator_mutation()
    if r is not None:
        return r
    csrf_err = _require_csrf()
    if csrf_err:
        return csrf_err
    try:
        tok = _hf_active_token()
        if not tok:
            return jsonify({'success': False, 'error': 'HF_TOKEN not set — save your token first'}), 400
        repo = (request.get_json() or {}).get('repo', 'XLabs-AI/flux-ip-adapter')
        filename = (request.get_json() or {}).get('filename', 'ip_adapter.safetensors')

        # LICENCE GATE ON THE DOWNLOAD ITSELF (2026-08-26).
        # Deleting a non-commercial weight does not keep it deleted while a button
        # can re-fetch it. This endpoint took an arbitrary repo and downloaded it,
        # so it was the one path that could silently undo a licence removal.
        # Asks the same registry the graph gate asks; refuses only a RECORDED
        # violation, so an unregistered repo still downloads (unknown is not a
        # refusal — it is merely unexamined, and this endpoint is not the place
        # to invent a verdict).
        try:
            from zyg_workflows import licence_provenance as _lp

            _reg = _lp.load_registry()
            for _probe in (repo, filename, f'{repo}/{filename}'):
                _rule = _lp._match_rule(_probe, _reg.get('weights') or [])
                if _rule and _lp._record_status(_rule) in _lp._FAILING:
                    return jsonify(
                        {
                            'success': False,
                            'error': (
                                f'Refused on licence: {repo} is recorded as '
                                f'"{_rule.get("licence")}" in model_licences.json. '
                                f'Downloading it would reintroduce a weight this '
                                f'pipeline has already refused.'
                            ),
                        }
                    ), 403
        except Exception as _lic_e:
            # A broken registry must not become an open door.
            return jsonify({'success': False, 'error': f'Licence check unavailable — download refused: {_lic_e}'}), 503

        def _dl():
            try:
                os.environ['HF_TOKEN'] = tok
                from huggingface_hub import hf_hub_download

                # The operator names the repo and file at request time, so there is no commit to
                # pin here; 'main' at least makes the resolved ref explicit instead of implicit.
                # bandit only accepts a 40-char commit as "pinned", so B615 is suppressed here.
                hf_hub_download(repo, filename, token=tok, revision='main')  # nosec B615
                if repo == 'XLabs-AI/flux-ip-adapter':
                    from zyg_workflows import ipadapter_service as _ipa_dl

                    _ipa_dl.ensure_image_encoder_cached(
                        log_fn=lambda m: _zyg_log.info(f'[HF Download] {m}'),
                    )
            except Exception as dl_e:
                _zyg_log.info(f'[HF Download] {repo}/{filename} failed: {dl_e}')

        threading.Thread(target=_dl, daemon=True, name='hf-download').start()
        return jsonify({'success': True, 'message': f'Download started: {repo}/{filename}'})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@bp.route('/api/llms/list')
def get_llms_list():
    """Return the canonical list of LLMs for the Settings → LLMS overlay."""
    return jsonify(CANONICAL_LLMS)


def _check_dependency(import_name: str, package_name: str, optional: bool = False, category: str = '') -> dict:
    """Check if a dependency is installed. Returns {id, name, status, note, optional, category}.
    Status: installed | parts_missing (import ok but critical sub-component missing) | not_installed.
    See docs/implementation-spec.md for parts_missing rules (torch+CUDA, ffmpeg binary, etc)."""
    status = 'not_installed'
    note = ''
    try:
        mod = importlib.util.find_spec(import_name)
        if mod is None:
            status = 'not_installed'
            note = 'Module not found'
        else:
            importlib.import_module(import_name)
            status = 'installed'
            # Per-package parts_missing checks (implementation-spec.md)
            if import_name == 'torch':
                import torch

                if not getattr(torch, 'cuda', None) or not torch.cuda.is_available():
                    status = 'parts_missing'
                    note = 'CUDA not available'
            elif import_name == 'ffmpeg':
                import shutil

                if not shutil.which('ffmpeg'):
                    # Also accept ffmpeg bundled with imageio_ffmpeg
                    try:
                        import imageio_ffmpeg

                        if imageio_ffmpeg.get_ffmpeg_exe():
                            status = 'installed'
                            note = 'via imageio-ffmpeg bundle'
                        else:
                            status = 'parts_missing'
                            note = 'ffmpeg binary not in PATH'
                    except Exception:
                        status = 'parts_missing'
                        note = 'ffmpeg binary not in PATH'
    except ImportError as e:
        status = 'not_installed'
        note = str(e)[:80] if e else 'Import failed'
    except Exception as e:
        status = 'parts_missing'
        note = str(e)[:80] if e else 'Partial import'
    result = {
        'id': package_name.replace('-', '_'),
        'name': package_name,
        'status': status,
        'note': note,
        'optional': optional,
    }
    if category:
        result['category'] = category
    return result


@bp.route('/api/dependencies/status')
def get_dependencies_status():
    """Return status of all app dependencies: installed, parts_missing, or not_installed.
    Uses same checkmark semantics as Security Controls (implemented/partial/not_implemented).
    Categories: core, backend, agents, llm, embeddings, diffusion, video_gen, video_proc, speech, data, job_queue, monitoring, analytics, security, dev."""
    items = []
    for t in DEPENDENCIES_CONFIG:
        import_name, pkg_name, optional, category = t[0], t[1], t[2], t[3]
        items.append(_check_dependency(import_name, pkg_name, optional, category))
    return jsonify({'items': items})
