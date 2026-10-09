#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Generate local Azure TTS V1/V2 samples for all Storyteller voices."""

from __future__ import annotations

import json
import os
import sys

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CREWS not in sys.path:
    sys.path.insert(0, _CREWS)

from zyg_workflows.storyteller_voice_preview_service import (  # noqa: E402
    SAMPLES_ROOT,
    VOICE_SAMPLE_V1,
    VOICE_SAMPLE_V2,
    default_voice_id,
    warm_all,
)


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description='Warm Storyteller Azure voice samples (V1+V2).')
    p.add_argument('--force', action='store_true', help='Re-synthesize even if files exist')
    args = p.parse_args()

    print('Default voice:', default_voice_id())
    print('Samples directory:', SAMPLES_ROOT)
    print('V1:', VOICE_SAMPLE_V1)
    print('V2:', VOICE_SAMPLE_V2)
    print('Warming… (this uses Azure Speech; may take several minutes)\n')

    summary = warm_all(force=args.force, include_default=True)
    print(json.dumps(summary, indent=2))
    print(
        f'\nDone: {summary["ok"]} full, {summary["partial"]} partial, '
        f'{summary["failed"]} failed — of {len(summary["voices"])} voices'
    )
    return 0 if summary['failed'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
