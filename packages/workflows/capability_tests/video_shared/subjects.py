# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The 132 subjects, assembled from the two halves they are written in."""

from __future__ import annotations

from .subjects_a import SUBJECTS_A
from .subjects_b import SUBJECTS_B

# ── the 132 subjects: (id, operator label, still prompt < 60 words, motion phrase < 40 words,
# mechanical tags). The id suffix is shared by the pair render_<id> / move_<id>. Tags:
#   face   ArcFace identity, frame 0 vs last      p<N>   person detector count N
#   h1/h2  hand landmarker, 1 or 2 hands          h1f5   one hand, five extended fingers
#   ocr:X  OCR must read X                        ocrs   OCR string must be stable, content free
#   static the SUBJECT must not move while the camera does   hi  legitimately high-motion subject
SUBJECTS = SUBJECTS_A + SUBJECTS_B
assert len(SUBJECTS) == 132, len(SUBJECTS)
assert len({s[0] for s in SUBJECTS}) == 132
