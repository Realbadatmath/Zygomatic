# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.arcane_restyle.__main__ — the standalone PREVIEW CLI, verbatim from
arcane_restyle.py lines 997-1021. `python -m zyg_workflows.arcane_restyle` replaces
`python3 arcane_restyle.py`.
"""

from __future__ import annotations

from zyg_workflows import paths
from zyg_workflows.arcane_restyle import profiles as _zyg_profiles
from zyg_workflows.arcane_restyle import dataset as _zyg_dataset

_PROFILES_PATH = _zyg_profiles._PROFILES_PATH
load_profile = _zyg_profiles.load_profile
build_styled_sdxl_dataset = _zyg_dataset.build_styled_sdxl_dataset


if __name__ == '__main__':
    # Standalone PREVIEW: restyle a few of a character's photoreal tiles into the
    # chosen profile's style, WITHOUT training. Usage:
    #   python3 arcane_restyle.py <char_id> [profile=arcane_animation] [limit=6] [--dir OUT]
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument('char_id')
    ap.add_argument('profile', nargs='?', default='arcane_animation')
    ap.add_argument('--limit', type=int, default=6)
    ap.add_argument('--photoreal-dir', default=None)
    ap.add_argument('--out-dir', default=None)
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    prof = load_profile(a.profile)
    if not prof:
        raise SystemExit(f'unknown profile: {a.profile} (in {_PROFILES_PATH})')
    _chars_root = paths.ZYG_LORA_DATASETS / 'storyteller_chars'
    pr_dir = a.photoreal_dir or str(_chars_root / a.char_id / 'training')
    out_dir = a.out_dir or str(_chars_root / a.char_id / f'style_preview_{a.profile}')
    print(f'profile={a.profile} photoreal_dir={pr_dir} out_dir={out_dir} limit={a.limit}')
    d = build_styled_sdxl_dataset(
        a.char_id, pr_dir, style_cfg=prof['restyle'], out_dir=out_dir, limit=a.limit, force=a.force
    )
    print('done ->', d)
