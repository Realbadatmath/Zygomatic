# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os


# ── tunables (env-overridable, house style) ───────────────────────────────────
INK_SAM2_ENABLED = os.environ.get('ZYG_INK_SAM2', '1') != '0'
INK_AUTO_BLUR = os.environ.get('ZYG_INK_AUTO_BLUR', '1') != '0'

# Calibration targets from the v8b forensics (see module docstring).
SHARPNESS_TARGET = (0.95, 1.20)  # lapvar(inked)/lapvar(raw) acceptance window
TEMPORAL_TARGET = (0.85, 1.15)  # on-ink temporal sigma ratio; the QC gate is a
# >=0.60 FLOOR, but overshoot is its own artefact
BLUR_SIGMA_RANGE = (0.4, 2.5)  # search bracket; past ~1.6 strokes go mushy at 480p
GRAIN_MUL_SIGMA = 0.09  # multiplicative alpha grain
GRAIN_ADD_SIGMA = 0.023  # additive alpha grain (~3.94/255 = measured page sigma)
JITTER_PX = 0.35  # +-px translation of the page homography
JITTER_SCALE = 0.0015  # +-0.15% scale
JITTER_CORR_FRAMES = 6.0  # correlation length of the smooth jitter noise
