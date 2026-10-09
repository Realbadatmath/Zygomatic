# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


# ── measurement constants ────────────────────────────────────────────────────
# Structure-tensor scales, in pixels at 1024. sigma_d is the derivative scale: it must be
# SMALLER than a lock or the gradient averages across neighbouring locks and the coherence
# collapses. sigma_i is the integration scale: it must be LARGER than a lock or the tensor
# never accumulates a consistent direction and every pixel reports its own noise. Measured
# on the anchor at 1024: locks read ~8-14 px across, so 1.6 / 6.0 brackets them.
SIGMA_D = 1.6
SIGMA_I = 6.0

# Below this coherence a pixel has no meaningful direction (flat fur interior, the plate,
# the eyes) and must not vote. 0.15 keeps ~55% of anchor fur pixels and ~60% of render fur
# pixels — checked, not assumed; null_report prints the kept fraction.
COHERENCE_FLOOR = 0.15

# Radial-deviation profile bins: position bins around the centroid (where on the body) x
# deviation is reported as a mean, not a histogram, because the mean is what a loss can use.
N_AZIMUTH_BINS = 12

# Power-spectrum band for lock scale, in cycles per subject-width. Below 6 is body form,
# above 90 is render noise / JPEG-ish ringing in the anchor. Both bounds checked against
# the null model.
LOCK_K_MIN = 6.0
LOCK_K_MAX = 90.0

# Silhouette blur scales in units of subject width. 0.004 ~ 4 px at 1024 (individual
# strands), 0.02 ~ 20 px (locks), 0.08 ~ 80 px (body form).
SIL_SCALES = (0.004, 0.02, 0.08)

# ── the coat-presence term ───────────────────────────────────────────────────
# BALD_TAU: a pixel is "smooth" when its local contrast is below this fraction of the
# SUBJECT'S OWN median contrast. Relative, because the anchors are generated images whose
# fur is soft and low-contrast while Cycles renders it sharp: measured, our renders carry
# ~1.7x the anchor's absolute fine-detail energy everywhere (0.0141 vs 0.0081), so every
# ABSOLUTE texture statistic reads "less fur" as "closer to the anchor". Three candidate
# absolute terms were built and all three failed on exactly that.
# 0.4 and 0.5 both separate cleanly; 0.6 nearly closes (bald 0.1304 vs furry 0.1284).
BALD_TAU = 0.4
BALD_BLUR = 0.006  # local-contrast kernel, in subject widths

# estimate_matte: a pixel belongs to the subject if it differs from its ROW's backdrop by
# more than this in luminance, OR carries more chroma than this. Two channels because the
# anchor's white crown differs from the backdrop in L only, while its green feet differ
# mostly in chroma. Phase 1 lost two rounds to a single-channel Otsu split that cut the
# body in half; these thresholds are deliberately loose and the connected-component pass
# below does the real work.
MATTE_DL = 22.0
MATTE_DC = 14.0
MATTE_EDGE_COLS = 0.04  # fraction of width sampled from each side for the backdrop
