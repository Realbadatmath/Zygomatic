# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: E402, F401  # the re-export block IS this module; the shim below it needs sys.


"""The block-out ladder — does this body read as anatomy at every scale, or only at one?

WHY THIS MODULE EXISTS
Anatomy For Sculptors, Bridgman's Constructive Anatomy (1920) and every atelier since
teach a figure the same way: level 1 is a BLOCK-OUT of primitive volumes (the ribcage egg,
the pelvic box, the cranial ball), level 2 refines those into muscle masses, and only then
comes surface. A figure can be correct at one level and wrong at another, and the two
failures look nothing alike:

  LEVEL-1 ERROR — the primitive volume is the wrong volume. The historic case here is the
    male original at torso-muscle-pectoral-incr 1.5, which the operator rejected because it
    "looked like a bust". Every width was inside its ANSUR band. A metric gate has no
    predicate for "the chest volume is now a breast volume", because breadth and depth and
    circumference are all satisfied by both shapes.
  LEVEL-3 ERROR — the volumes and masses are right and there is NO SURFACE. That is "waxy
    skin": high-frequency relief has been smoothed away, so the body reads as a mannequin.
    Again no metric moves; a smoothed mesh measures the same as the mesh it came from, to
    well under a millimetre.

Both are invisible to geom.anthro, which is a METRIC layer, and both are invisible to a
single curvature number, which cannot say at what SCALE the surface went wrong. What
separates them is a band split: decompose the surface into the scales a sculptor works at
and ask which band carries how much. That is what this module computes.

HOW: MANIFOLD HARMONICS, NOT ITERATED SMOOTHING
The bands come from the generalised eigenproblem L phi = lambda M phi of the cotangent
Laplacian (Vallet & Levy 2008; Taubin 1995). Projecting positions onto the eigenvectors
below a cutoff gives the level-1 block-out DIRECTLY — a smooth, non-shrunken body.

The obvious alternative, implicit Laplacian smoothing at increasing timesteps, was tried
first and rejected on measured grounds, and the reason matters: implicit smoothing is
mean-curvature flow, so a cylinder of radius r moves inward by about t/r per step. A
timestep large enough to erase a torso-scale feature (sqrt(t) ~ 0.06 * stature = 0.11 m on
the male) displaces a 0.05 m-radius forearm by 0.25 m. It does not blur the arms into a
block-out, it DELETES them. Spectral projection has no such collapse: it is an orthogonal
projection, not a flow. Implicit smoothing survives in this module only as `smooth()`, at
timesteps small enough for the flow interpretation to be safe, and there it is used to
CONSTRUCT the waxy defect, not to measure it.

MEASURED COST, which is why the ladder stops where it does (RTX 4090 host, scipy
splu shift-invert, 13,348-vertex body shell): k=400 eigenpairs 7.9 s, k=600 16.3 s,
k=1500 116 s. k=1500 only reaches a feature wavelength of 0.042 * stature. Resolving true
skin-scale relief spectrally is therefore not affordable at any useful frame rate, and this
module does not pretend to: LOW and MID are spectral bands, and HIGH is the EXACT RESIDUAL
x - LOW - MID. Nothing is lost by that (the three bands still sum to x identically), but
HIGH is one bucket and cannot be sub-divided here. geom.form.curvature is the tool for
scales below HIGH's cutoff.

THE FOUR SHELLS. The cage is not one surface: measured, 13,348 v body + 226 v tongue +
2 x 72 v eyeball. A Laplacian over all four is block-diagonal, so a low-band reconstruction
gives each shell its OWN constant mode and collapses the eyeballs to points. Every number
and every render here is therefore computed on the BODY SHELL ALONE, and the excluded
shells are reported by name and vertex count rather than quietly dropped.

SCALE NORMALISATION, so a 1.52 m child and a 1.85 m adult are comparable. Eigenvalues carry
units of 1/m^2 and displacements carry metres, so neither is comparable across statures.
Everything published here is dimensionless: band cutoffs are quoted as lambda * stature^2
(equivalently, as a feature WAVELENGTH in fractions of stature), and every energy is an
M-weighted RMS displacement divided by stature, reported in MILLISTATURE (1 mstat = 0.001
of the subject's own height = 1.85 mm on the male original, 1.52 mm on abel). self_test()
proves the invariance by scaling a real character by 1.7 and re-measuring.

WHAT THIS MODULE DOES NOT DO. It ships no threshold and no gate. A form gate needs a
rejection rate against a reference sample of bodies our own pipeline accepts (the
Monte-Carlo morph-space sample under data/assets/form_reference/), and until that rate is
measured no number in here has earned the right to block anything. PREDICATES below names
the scalars a gate would band, and says so.
"""

# blockout.py, split at its own section banners. The sections are imported in the original
# declaration order, so every module-level side effect still runs in that order, and the
# first module carries the original top import block verbatim — re-exported here, so
# attribute access such as blockout.os keeps resolving.

from zyg_workflows.geom.form.blockout.spectral import (
    json,
    os,
    sys,
    time,
    np,
    sp,
    spl,
    connected_components,
    CV,
    __version__,
    BANDS,
    WAVELENGTH_LOW_FRAC,
    WAVELENGTH_MID_FRAC,
    LAMBDA_LOW,
    LAMBDA_MID,
    MICRO_SIGMA_FRAC,
    BAND_MEANING,
    EIGS_MARGIN,
    EIGS_MIN_K,
    EIGS_MAX_K,
    EIGS_GROWTH,
    EIGS_SIGMA,
    MSTAT,
    PREDICATES,
    shell_split,
    _body_quads,
    spectral_basis,
    decompose,
)
from zyg_workflows.geom.form.blockout.regions import (
    FALLBACK_BANDS,
    ARM_TARGETS,
    MORPH_REGION_CORE,
    MORPH_REGIONS,
    CAGE_VERTS,
    _to_mask,
    _sibling_groups,
    region_map,
)
from zyg_workflows.geom.form.blockout.energies import (
    _rms,
    band_energies,
    delta_bands,
    smooth,
    render_blockout,
    report,
    _json_safe,
    write_json,
)
from zyg_workflows.geom.form.blockout.demos import (
    _gate_ab,
    _status_counts,
    demo_level1_error,
    _print_level1,
    WAXY_SWEEP,
    demo_waxy,
    character_meshes,
    run_characters,
    self_test,
    main,
)
