# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Composite the generated character over the Blender background plates.

    python3 tools/character_composite.py CLIP PLATES_DIR OUT_MP4 [--fps 24] [--dilate 14] [--feather 6]

Per frame k: background = bg_k with the actor hole (m_k) inpainted (Telea); character alpha =
rembg(u2net) alpha of the generated frame, limited to the dilated proxy matte so nothing the
model invented outside the actor survives; feathered and composited. The set, its lighting and
the VFX frame contract stay Blender's; VACE only supplies the character pixels (2026-09-20).
"""

if __name__ == '__main__':  # the CLI lives in character_composite_cli
    from zyg_workflows.tools.character_composite_cli import main as _cli_main

    raise SystemExit(_cli_main())
