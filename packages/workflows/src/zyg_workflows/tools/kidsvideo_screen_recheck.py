# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Re-measure the PRODUCTION screen (kids_video_service.vlm_defects + judge_description)
on the calibration labels plus a live song's receipts. Writes screen_recheck_<tag>.json.
Live receipts are 320 px (the full frames were deleted) — upscaled, a harder read."""

import os
import sys

from zyg_workflows import paths

# CREWS only names the frame/score data; the two sys.path inserts that used to
# precede the service imports (now in kidsvideo_screen_recheck_cli) are gone.
CREWS = str(paths.ZYG_CREWS_ROOT)

OUT = os.path.join(CREWS, 'output/kidsmusic/_frame_defect_bench')
LIVE = os.path.join(CREWS, 'output/kidsmusic/7a9514bf0b42/frames')
LIVE_POS = ['f012_c1', 'f042_c1']  # merged front wheels; "Hello" speech bubble
LIVE_NEG = ['f016_c0', 'f025_c1', 'f033_c1', 'f037_c0', 'f052_c0', 'f015_c0', 'f049_c0', 'f039_c1', 'f054_c1']


if __name__ == '__main__':  # the CLI lives in kidsvideo_screen_recheck_cli
    from zyg_workflows.tools.kidsvideo_screen_recheck_cli import main as _cli_main

    raise SystemExit(_cli_main(sys.argv[1]))
