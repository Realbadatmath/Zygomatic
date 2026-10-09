#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Smoke test for character bible + consistency QA + comfy generation imports."""

import os
import sys

CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CREWS)

from zyg_workflows import character_bible_service as cbs  # noqa: E402  deliberate late import, after the sys.path shim above
from zyg_workflows import consistency_qa_service as cqa  # noqa: E402  deliberate late import, after the sys.path shim above
from zyg_workflows import comfy_generation_service as cgs  # noqa: E402  deliberate late import, after the sys.path shim above


def main():
    pkg = cbs.default_package('test_char_continuity', 'ZYG_CHAR_TEST01')
    path = cbs.save(pkg)
    print(f'OK bible save → {path}')
    loaded = cbs.load('test_char_continuity')
    # 'trigger_token' is the LoRA trigger WORD baked into a character bible, not a credential.
    assert loaded and loaded['trigger_token'] == 'ZYG_CHAR_TEST01'  # noqa: S105  LoRA trigger word, see above
    prefix = cbs.identity_prompt_prefix(loaded)
    assert loaded['trigger_token'] in prefix or prefix == ''
    full = cbs.full_character_descriptor(loaded)
    print(f'OK identity prefix ({len(prefix)} chars), full descriptor ({len(full)} chars)')
    print(f'comfy primary={cgs.is_primary_backend()} available={cgs.is_available()}')
    print(f'qa backend={cqa._embed_backend}')
    print('All continuity stack imports OK')


if __name__ == '__main__':
    main()
