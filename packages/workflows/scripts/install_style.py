#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Add / update a Storyteller STYLE reference LoRA and register it for easy switching.

Style LoRAs live in the ComfyUI loras dir as  style_<key>.safetensors
and are indexed in  data/runtime/storyteller_styles.json  (the switchboard).
To switch the active reference at render time, set  "active_style"  in that file
(or a per-template style_ref), and the pipeline stages that style's file.

Usage
-----
  # From Civitai (public models download anonymously; gated ones need a token):
  CIVITAI_TOKEN=xxxx python3 install_style.py --civitai 112904 --key arcane \
      --trigger arcane --weight 0.8 --reference "Arcane painterly semi-real"

  # From a Hugging Face repo file (uses HF_TOKEN from env if set):
  python3 install_style.py --hf user/repo:path/to/lora.safetensors --key rotoscope \
      --trigger "" --weight 0.7 --reference "rotoscope / photoreal-adjacent"

  # From a local file you already have:
  python3 install_style.py --file /path/to/lora.safetensors --key painterly \
      --weight 0.75 --reference "painterly semi-real concept art"

  # Just set the active reference (no download):
  python3 install_style.py --activate arcane

  # List the registry:
  python3 install_style.py --list
"""

import argparse
import json
import os
import struct
import sys
import time
import urllib.request
import logging as _zyg_logging
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


CREWS = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(CREWS, 'data', 'runtime')
LORA_DIR = str(paths.ZYG_COMFY_LORA_DIR)
REG_PATH = os.path.join(RUNTIME, 'storyteller_styles.json')
UA = {'User-Agent': 'curl/8.5'}


def load_reg():
    if os.path.exists(REG_PATH):
        try:
            r = json.load(open(REG_PATH, encoding='utf-8'))
            r.setdefault('styles', {})
            r.setdefault('loras_dir', LORA_DIR)
            r.setdefault('active_style', None)
            return r
        except Exception as _exc:
            _zyg_log.warning('style registry %s unreadable, continuing with an empty registry: %s', REG_PATH, _exc)
    return {'version': 1, 'active_style': None, 'loras_dir': LORA_DIR, 'styles': {}}


def save_reg(r):
    os.makedirs(RUNTIME, exist_ok=True)
    with open(REG_PATH, 'w', encoding='utf-8') as f:
        json.dump(r, f, indent=2, ensure_ascii=False)


def valid_safetensors(path):
    try:
        sz = os.path.getsize(path)
        with open(path, 'rb') as f:
            n = struct.unpack('<Q', f.read(8))[0]
            if n <= 0 or n > sz:
                return False, f'bad header len {n} vs size {sz}'
            hdr = json.loads(f.read(n).decode('utf-8'))
        keys = [k for k in hdr if k != '__metadata__']
        return len(keys) > 0, f'{len(keys)} tensors, {sz // (1024 * 1024)}MB'
    except Exception as e:
        return False, f'parse error: {e}'


def _open_http(url, *, headers=None, data=None, method=None, timeout=60):
    """``urlopen`` restricted to http/https.

    Plain ``urlopen`` follows ``file:`` and any custom scheme, so a URL that arrives from
    configuration or from an API response can read local files. Headers are needed here, so
    :func:`zyg_workflows.net.safe_urlopen` (which takes a bare URL) cannot be used directly;
    the same scheme check is applied to the composed ``Request`` instead.
    """
    req = urllib.request.Request(url, headers=headers or {}, data=data, method=method)  # noqa: S310  scheme checked on the next line
    if req.type not in ('http', 'https'):
        raise ValueError(f'refusing to open a {req.type!r} URL: {url!r}')
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310  scheme validated two lines above  # nosec B310


def http_get(url, dst, headers=None, tries=3):
    h = dict(UA)
    if headers:
        h.update(headers)
    for i in range(tries):
        try:
            with _open_http(url, headers=h, timeout=180) as r, open(dst, 'wb') as out:
                total = 0
                while True:
                    ch = r.read(1 << 20)
                    if not ch:
                        break
                    out.write(ch)
                    total += len(ch)
            return total, None
        except Exception as e:
            err = str(e)
            time.sleep(3 + i * 3)
    return 0, err


def civitai_download(model_id, dst):
    tok = os.environ.get('CIVITAI_TOKEN', '')
    m = json.load(_open_http(f'https://civitai.com/api/v1/models/{model_id}', headers=UA, timeout=30))
    for v in m.get('modelVersions', []):
        base = v.get('baseModel') or ''
        if not any(k in base for k in ('SDXL', 'Illustrious', 'Pony', 'XL', 'Flux', 'FLUX')):
            continue
        for f in v.get('files', []):
            if str(f.get('name', '')).endswith('.safetensors'):
                url = f['downloadUrl'] + (f'?token={tok}' if tok else '')
                got, err = http_get(url, dst)
                return got, err, base, f.get('name'), f'civitai:{model_id}/{v.get("id")}'
    return 0, 'no safetensors version found', None, None, f'civitai:{model_id}'


def hf_download(spec, dst):
    # spec = "user/repo:path/in/repo.safetensors"
    repo, path = spec.split(':', 1)
    tok = os.environ.get('HF_TOKEN', '')
    url = f'https://huggingface.co/{repo}/resolve/main/{path}?download=true'
    hdr = {'Authorization': f'Bearer {tok}'} if tok else {}
    got, err = http_get(url, dst, headers=hdr)
    return got, err, 'hf', os.path.basename(path), f'hf:{spec}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--civitai', type=int)
    ap.add_argument('--hf')
    ap.add_argument('--file')
    ap.add_argument('--key')
    ap.add_argument('--trigger', default='')
    ap.add_argument('--weight', type=float, default=0.75)
    ap.add_argument('--reference', default='')
    ap.add_argument('--name', default='')
    ap.add_argument('--activate')
    ap.add_argument('--list', action='store_true')
    a = ap.parse_args()
    reg = load_reg()

    if a.list:
        print(json.dumps(reg, indent=2))
        return
    if a.activate:
        if a.activate not in reg['styles']:
            print(f"unknown style '{a.activate}'. known: {list(reg['styles'])}")
            sys.exit(1)
        reg['active_style'] = a.activate
        save_reg(reg)
        print(f'active_style -> {a.activate}')
        return

    if not a.key:
        print('--key is required to install')
        sys.exit(1)
    os.makedirs(LORA_DIR, exist_ok=True)
    fname = f'style_{a.key}.safetensors'
    dst = os.path.join(LORA_DIR, fname)

    if a.file:
        import shutil

        shutil.copyfile(a.file, dst)
        base, cfile, src = 'local', os.path.basename(a.file), f'local:{a.file}'
        got = os.path.getsize(dst)
        err = None
    elif a.civitai:
        got, err, base, cfile, src = civitai_download(a.civitai, dst)
    elif a.hf:
        got, err, base, cfile, src = hf_download(a.hf, dst)
    else:
        print('one of --civitai / --hf / --file required')
        sys.exit(1)

    ok, info = valid_safetensors(dst) if got else (False, err or 'download failed')
    entry = {
        'name': a.name or a.key,
        'reference': a.reference,
        'trigger': a.trigger,
        'recommended_weight': a.weight,
        'base': base,
        'file': fname,
        'source': src,
        'installed': bool(ok),
    }
    if ok:
        entry['size_mb'] = os.path.getsize(dst) // (1024 * 1024)
        print(f'OK: {a.key} installed ({info}) from {src}')
    else:
        print(f'FAILED: {a.key} ({info}). Registered as pending.')
        try:
            if os.path.exists(dst):
                os.remove(dst)
        except OSError as _exc:
            _zyg_log.debug('stale lora %s removal skipped: %s', dst, _exc)
    reg['styles'][a.key] = entry
    if reg.get('active_style') is None and ok:
        reg['active_style'] = a.key
    save_reg(reg)


if __name__ == '__main__':
    main()
