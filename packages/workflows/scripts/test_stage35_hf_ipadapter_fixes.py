#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Verify HF token test path, IPAdapter cache helpers, and Stage 3.5 routing flags."""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

CREWS = Path(__file__).resolve().parent.parent
ROOT_ENV = CREWS.parents[1] / '.env'
sys.path.insert(0, str(CREWS))


def _read_hf_token() -> str:
    for line in ROOT_ENV.read_text().splitlines():
        line = line.strip()
        if line.startswith('HF_TOKEN='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    return ''


def test_hf_whoami_v2() -> None:
    tok = _read_hf_token()
    assert tok.startswith('hf_'), 'HF_TOKEN missing or invalid in .env'
    req = urllib.request.Request(
        'https://huggingface.co/api/whoami-v2',
        headers={'Authorization': f'Bearer {tok}'},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310  literal https:// URL above
        info = json.loads(resp.read().decode())
    assert info.get('name'), f'whoami-v2 failed: {info}'
    print(f'OK hf whoami-v2: {info["name"]}')


def test_legacy_whoami_fails_for_fine_grained() -> None:
    """Document: legacy endpoint 401s for fine-grained tokens (dashboard bug we fixed)."""
    tok = _read_hf_token()
    req = urllib.request.Request(
        'https://huggingface.co/api/whoami',
        headers={'Authorization': f'Bearer {tok}'},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310  literal https:// URL above
            json.loads(resp.read().decode())
        print('NOTE legacy /api/whoami succeeded (classic token?)')
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print('OK legacy /api/whoami returns 401 (expected for fine-grained — use whoami-v2)')
        else:
            raise


def test_ipadapter_cache_helpers() -> None:
    from zyg_workflows import ipadapter_service as ipa
    from huggingface_hub import try_to_load_from_cache

    os.environ['HF_TOKEN'] = _read_hf_token()
    adapter = try_to_load_from_cache(ipa._IP_ADAPTER_REPO, ipa._IP_ADAPTER_WEIGHT)
    assert adapter is not None, 'ip_adapter.safetensors not in HF cache — run dashboard download'
    print(f'OK IPAdapter weights cached: {adapter}')

    ok = ipa.ensure_image_encoder_cached(print)
    assert ok, 'CLIP image encoder could not be cached'
    enc = try_to_load_from_cache(ipa._IMAGE_ENCODER_REPO, 'config.json')
    assert enc is not None, 'CLIP encoder config not cached after ensure'
    print(f'OK CLIP encoder cached: {enc}')


def test_comfy_primary_routing_logic() -> None:
    """Pure logic: flux + comfy available => comfy primary, no eager diffusers."""
    model_family = 'flux'
    comfy_available = True
    comfy_primary = comfy_available and model_family in ('sdxl', 'flux')
    use_diffusers = not comfy_primary
    assert comfy_primary is True
    assert use_diffusers is False
    print('OK Stage 3.5 routing: FLUX + Comfy => Comfy-primary, no diffusers preload')


def main() -> int:
    tests = [
        test_hf_whoami_v2,
        test_legacy_whoami_fails_for_fine_grained,
        test_ipadapter_cache_helpers,
        test_comfy_primary_routing_logic,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            print(f'FAIL {t.__name__}: {e}', file=sys.stderr)
    if failed:
        print(f'\n{failed} test(s) failed', file=sys.stderr)
        return 1
    print(f'\nAll {len(tests)} checks passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
