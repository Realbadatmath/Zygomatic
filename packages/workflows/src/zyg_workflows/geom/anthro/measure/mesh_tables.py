# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The table passes of measure_mesh(), one function per block of the record.

Extracted from measure/mesh.py by the 2026-10 function-size split. Each pass
fills the SAME measurement dict in the SAME order the 337-line original did, so
the record's key order, its provenance strings and its notes are unchanged; what
is new is that every pass can be run — and tested — on its own.

The enclosing locals the original shared between its blocks travel as one
MeshScan: the geometry, the resolved landmarks, the joint-centre anchors, the
pose and the scan step.
"""

import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from zyg_workflows.geom.anthro import landmarks as LMK
from zyg_workflows.geom.anthro.measure.constants import (
    ANNY_VENDOR_DENSITY_KG_M3,
    ARM_SKIN_WEIGHT_THRESHOLD,
    BODY_DENSITY_KG_M3,
    CAGE_FACES,
    ISO_20685_1_TABLE4_MM,
    ISO_CAVEAT,
)
from zyg_workflows.geom.anthro.measure.primitives import body_volume
from zyg_workflows.geom.anthro.measure.record import (
    HULL_CONVENTION,
    POLYLINE_CONVENTION,
    _rec,
)
from zyg_workflows.geom.anthro.measure.sites import (
    _extent_measure,
    _girth_site,
)
from zyg_workflows.geom.anthro.measure.tables_extent import (
    BREADTH_SPEC,
    DEPTH_SPEC,
    HEIGHT_SPEC,
    LENGTH_SPEC,
    UNMEASURABLE,
)
from zyg_workflows.geom.anthro.measure.tables_girth import GIRTH_SITES


@dataclass
class MeshScan:
    """One cage under measurement: everything the table passes share.

    v / faces are the mesh, zmin and H its ground and its stature in metres, topo
    the body-shell topology, landmarks the resolved landmark records, axes the
    limb axes and coco the joint-centre keypoints they came from (coco_src says
    whose body those joints belong to), pose the pose/frame check, pose_ref the
    arms-down copy every horizontal site is differenced against, step the scan
    step in metres, ear_top and crotch_frac the per-mesh band floors.
    """

    v: np.ndarray
    faces: np.ndarray
    zmin: float
    H: float
    topo: dict
    landmarks: dict
    axes: Any
    coco: Any
    coco_src: str
    pose: dict
    pose_ref: Any
    pose_ref_info: dict
    step: float
    ear_top: Any
    crotch_frac: Any
    sex: Any = None
    name: Any = None
    t_start: float = 0.0


def resolve_coco(phenotype, local_changes) -> tuple[Any, str]:
    """The joint-centre keypoints for THIS recipe, and the provenance line for them.

    Returns (keypoints, source). The source says so loudly when no phenotype was
    passed: the anchors then belong to the stock anny body, which landmarks.py
    measured as a 16-19 mm error in acromial height.
    """
    try:
        coco = LMK._coco(phenotype, local_changes)
        coco_src = (
            'anny COCO keypoint regressor on THIS recipe'
            if phenotype is not None
            else 'NEUTRAL FALLBACK — no phenotype was passed, so every joint-centre '
            'anchor and limb axis belongs to the stock anny body, not to this '
            'character (measured cost: 16-19 mm on acromial height)'
        )
    except Exception as e:  # noqa: BLE001
        coco = None
        coco_src = 'UNAVAILABLE: %s' % e
    return coco, coco_src


def height_rows(M: dict, scan: MeshScan) -> None:
    """Fill every HEIGHT_SPEC row: stature off the mesh z-extent, the rest off
    their landmark's height above the standing surface, UNMEASURABLE when the
    landmark did not resolve."""
    for spec in HEIGHT_SPEC:
        if spec['name'] == 'stature':
            M['stature'] = _rec(
                scan.H * 1000,
                'height',
                'vertex to standing surface',
                'mesh z-extent',
                'height',
                spec['note'],
                frac_stature=1.0,
            )
            continue
        r = scan.landmarks.get(spec['landmark'])
        if r is None or r.get('height_m') is None:
            M[spec['name']] = _rec(
                None,
                'height',
                spec['landmark'],
                'landmark height',
                spec['iso_class'],
                spec['note'],
                provenance='UNMEASURABLE',
                reason='landmark %r unresolved on this mesh' % spec['landmark'],
            )
            continue
        M[spec['name']] = _rec(
            r['height_m'] * 1000,
            'height',
            '%s (%s)' % (spec['landmark'], r['anchor']),
            'vertical distance above the standing surface',
            spec['iso_class'],
            spec['note'],
            frac_stature=r['frac_stature'],
            landmark_confidence=r['confidence'],
            ansur_ratio=spec['ansur'],
        )


def cervicale_row(M: dict, scan: MeshScan) -> None:
    """cervicale: HOUSE substitution, never presented as a measurement.

    Needs both a resolved suprasternale (already in M) and a declared sex; either
    missing and the row is UNMEASURABLE with the reason saying which.
    """
    ss = M.get('suprasternale_height', {}).get('value_mm')
    sex, H = scan.sex, scan.H
    off = LMK.CERVICALE_OVER_SUPRASTERNALE.get(str(sex).lower()) if sex else None
    if ss is not None and off is not None:
        M['cervicale_height_house'] = _rec(
            ss + off[0] * H * 1000,
            'height',
            'suprasternale + ANSUR cervicale-minus-suprasternale offset',
            'HOUSE substitution (this cage has no vertebra prominens)',
            'height',
            'The offset is MEASURED from ANSUR II per-subject differences (%s: %.4f '
            '+/- %.4f of stature) but applying it to a mesh is HOUSE policy. It carries '
            'the offset SD (%.1f mm here) as irreducible uncertainty on top of the '
            'suprasternale error.' % (sex, off[0], off[1], off[1] * H * 1000),
            provenance='HOUSE',
            offset_frac_stature=off[0],
            offset_sd_mm=off[1] * H * 1000,
            frac_stature=(ss / 1000.0 + off[0] * H) / H,
            ansur_ratio='cervicale_height_over_stature',
        )
    else:
        M['cervicale_height_house'] = _rec(
            None,
            'height',
            'cervicale',
            'HOUSE substitution',
            'height',
            'needs both a resolved suprasternale and a declared sex',
            provenance='UNMEASURABLE',
            reason='sex not declared' if off is None else 'suprasternale unresolved',
        )


def length_rows(M: dict, scan: MeshScan) -> None:
    """Fill every LENGTH_SPEC row: the horizontal, vertical or 3D-chord distance
    between its two landmarks, UNMEASURABLE when either is unresolved."""
    for spec in LENGTH_SPEC:
        ra, rb = scan.landmarks.get(spec['a']), scan.landmarks.get(spec['b'])
        if not ra or not rb or ra.get('point') is None or rb.get('point') is None:
            M[spec['name']] = _rec(
                None,
                'length',
                '%s to %s' % (spec['a'], spec['b']),
                spec['mode'],
                spec['iso_class'],
                spec['note'],
                provenance='UNMEASURABLE',
                reason='one of the two landmarks is unresolved',
            )
            continue
        a, b = np.asarray(ra['point']), np.asarray(rb['point'])
        if spec['mode'] == 'horizontal':
            d = float(np.linalg.norm((a - b)[:2]))
            conv = 'horizontal distance between two landmarks'
        elif spec['mode'] == 'vertical':
            d = float(abs(a[2] - b[2]))
            conv = 'vertical distance between two landmarks'
        else:
            d = float(np.linalg.norm(a - b))
            conv = 'straight-line (3D chord) distance between two landmarks'
        M[spec['name']] = _rec(
            d * 1000,
            'length',
            '%s to %s' % (spec['a'], spec['b']),
            conv,
            spec['iso_class'],
            spec['note'],
            frac_stature=d / scan.H,
            ansur_ratio=spec['ansur'],
            survey_comparable=spec.get('survey_comparable', True),
            survey_not_comparable_because=spec.get('survey_reason'),
        )


def girth_rows(M: dict, scan: MeshScan) -> None:
    """Fill every GIRTH_SITES row, one per side the site has (None = unsided)."""
    for spec in GIRTH_SITES:
        for side in spec['sides'] or (None,):
            key = spec['name'] + ('_' + side if side else '')
            M[key] = _girth_site(
                scan.v,
                scan.faces,
                spec,
                side,
                scan.landmarks,
                scan.axes,
                scan.zmin,
                scan.H,
                scan.step,
                scan.coco,
                scan.ear_top,
                scan.crotch_frac,
                pose_ref=scan.pose_ref,
            )


def extent_rows(M: dict, scan: MeshScan) -> None:
    """Fill the BREADTH_SPEC (x) and DEPTH_SPEC (y) rows, in that order.

    A breadth marked not measurable on this cage is recorded UNMEASURABLE with
    its own reason rather than taken off the silhouette.
    """
    for spec in BREADTH_SPEC:
        if not spec.get('measurable', True):
            M[spec['name']] = _rec(
                None,
                'breadth',
                spec['landmark'],
                'not applicable',
                spec['iso_class'],
                spec['reason'],
                provenance='UNMEASURABLE',
                reason=spec['reason'],
                ansur_ratio=spec['ansur'],
            )
            continue
        M[spec['name']] = _extent_measure(
            scan.v,
            scan.faces,
            spec,
            scan.landmarks,
            scan.zmin,
            scan.H,
            scan.step,
            'x',
            scan.ear_top,
            scan.crotch_frac,
            pose_ref=scan.pose_ref,
        )
    for spec in DEPTH_SPEC:
        M[spec['name']] = _extent_measure(
            scan.v,
            scan.faces,
            spec,
            scan.landmarks,
            scan.zmin,
            scan.H,
            scan.step,
            'y',
            scan.ear_top,
            scan.crotch_frac,
            pose_ref=scan.pose_ref,
        )


def volume_rows(M: dict, scan: MeshScan) -> None:
    """Fill the volume row and the three numbers derived from it.

    body_volume_l is geometry; the volume-height index still is; mass and BMI are
    HOUSE, because the cage contains no lungs, gut gas or fat/lean split and so
    nothing in it can determine a density.
    """
    H = scan.H
    vol_body, vol_all, shell_note = body_volume(scan.v, scan.faces)
    M['body_volume_l'] = _rec(
        None,
        'volume',
        'whole body shell',
        'divergence-theorem sum over the closed body shell',
        None,
        'Units are LITRES, not millimetres — read value_l, not value_mm. ' + shell_note,
        value=vol_body * 1000,
        units='L',
        inclusions_l=(vol_all - vol_body) * 1000,
    )
    vhi = (vol_body * 1000) / (H**2)
    M['volume_height_index'] = _rec(
        None,
        'derived',
        'body volume / stature^2',
        'litres per square metre',
        None,
        'VHI. A pure geometry index — no density assumption enters it, which is why it is '
        'the honest shape statistic and BMI below is not.',
        value=vhi,
        units='L/m^2',
    )
    mass = vol_body * BODY_DENSITY_KG_M3
    M['derived_mass_kg'] = _rec(
        None,
        'derived',
        'body volume x assumed density',
        '%g kg/m^3 uniform density' % BODY_DENSITY_KG_M3,
        None,
        'DERIVED WITH AN ASSUMPTION, not measured. The density is HOUSE (task-specified); '
        'anny\'s own vendor code uses %g kg/m^3 "for simplicity". The mesh contains no '
        'lungs, gut gas or fat/lean split, so nothing in the geometry can determine it. A '
        '5%% density error is a 5%% mass error (%.1f kg here).' % (ANNY_VENDOR_DENSITY_KG_M3, 0.05 * mass),
        provenance='HOUSE',
        value=mass,
        units='kg',
        alternative_at_vendor_density_kg=vol_body * ANNY_VENDOR_DENSITY_KG_M3,
    )
    M['derived_bmi'] = _rec(
        None,
        'derived',
        'derived mass / stature^2',
        'kg/m^2 from the assumed density',
        None,
        'Inherits the density assumption above in full. Compare to the reference '
        'pack BMI distribution only while remembering that the pack BMI is from '
        'WEIGHED subjects and this one is from an assumed density.',
        provenance='HOUSE',
        value=mass / (H**2),
        units='kg/m^2',
    )


def meta_block(scan: MeshScan) -> dict:
    """The provenance block of the record: the pose, the vertex scope, every
    convention the numbers above were taken under, and how long the pass took."""
    pose, topo, v = scan.pose, scan.topo, scan.v
    return {
        'schema': 'geom.anthro.measure/1',
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'name': scan.name,
        'sex_declared': scan.sex,
        'units': 'value_mm is MILLIMETRES; volume is litres; ratios are dimensionless '
        'unless a units field says otherwise',
        'pose': pose['pose'],
        'pose_check': pose,
        'axis_convention': pose['axis_convention'],
        'handedness': pose['handedness'],
        'ground_plane': pose['ground_plane'],
        'stature_m': scan.H,
        'vertex_scope': (
            'anny cage, %d vertices / %d quads -> %d triangles; slices and '
            'volume use the BODY SHELL only (%d triangles of %d). %s'
            % (len(v), CAGE_FACES, len(topo['tri']), int(topo['body_tris'].sum()), len(topo['tri']), topo['shell_note'])
        ),
        'girth_convention': HULL_CONVENTION,
        'girth_conventions_also_reported': {
            'contour_mm': 'exact cross-section perimeter, follows every concavity; '
            '>= the hull for any non-convex section',
            'polyline_mm': POLYLINE_CONVENTION,
        },
        'limb_girth_convention': 'ISO 18825-2: limb girths are taken PERPENDICULAR TO THE '
        'LIMB AXIS. Every limb site also reports the horizontal '
        'value, because ANSUR tape measurements of thigh and '
        'calf are horizontal and the two are not the same number.',
        'arm_exclusion': (
            'THREE layers. (1) topological: a horizontal plane cuts the A-posed torso and '
            'each arm as separate closed loops, and torso measurements take the '
            'largest-area loop. (2) the SKINNING-WEIGHT MASK: every contour point carries '
            'the summed rig weight of the arm bones interpolated along its own crossing '
            'edge, and points at or above %.2f are dropped from every torso and head '
            'breadth, depth and girth (clavicle and shoulder01 are NOT masked — they '
            'carry genuine shoulder breadth). (3) the merge refusal: a torso GIRTH is '
            'refused, never trimmed, when arm surface is in the loop and both arms are '
            'not present as loops of their own, because the trunk section is then not '
            'closed. Each measurement carries its own arm_mask block saying whether the '
            'mask ran, how many points it dropped, and what the value was without it.' % ARM_SKIN_WEIGHT_THRESHOLD
        ),
        'arm_mask_provenance': topo['arm_mask_provenance'],
        'a_pose_bias': dict(
            scan.pose_ref_info,
            what='every horizontal site carries a_pose_bias_mm: the signed shift of that '
            'measurement when the humeri are brought vertical, so a consumer can see '
            "how much of a trunk number is anny's A-pose rather than the body. It "
            'is REPORTED, NEVER APPLIED. Sites whose section carries no arm skinning '
            'weight at all get an exact 0.0 rather than an estimate.',
            policy='a bounded, measured bias is an uncertainty to carry, not a reason to '
            'stop gating, so the trunk sites stay survey-comparable and ship their '
            'bias for a band check to widen by. A site whose DIMENSION is defined '
            'on the arm (bideltoid breadth, shoulder circumference) is a different '
            'dimension in this pose, cannot be put back on the survey convention, '
            'and stays NOT survey-comparable — the estimate over-corrects it by '
            '20-26% and would move the male bideltoid inside the band where a '
            'genuine re-pose leaves it outside.',
        ),
        'coco_source': scan.coco_src,
        'ear_top_frac_stature': scan.ear_top,
        'crotch_frac_stature': scan.crotch_frac,
        'band_floors': 'head bands start at the top of the ear morph support; the hip '
        'breadth band starts at the RESOLVED TROCHANTERION (the higher of '
        'left and right), not at the crotch — below the greater trochanter '
        'the lateral silhouette of this cage is thigh, and the x-extent '
        'profile above the crotch is monotonically decreasing on every '
        'body measured, so a crotch floor made the maximum search return '
        'the perineum every time. Both floors are per-mesh, not fixed '
        'fractions, and an unresolved floor landmark REFUSES the site '
        'rather than falling back to a fraction.',
        'iso_20685_1_table4_mm': ISO_20685_1_TABLE4_MM,
        'iso_caveat': ISO_CAVEAT,
        'density_assumption_kg_m3': BODY_DENSITY_KG_M3,
        'elapsed_s': round(time.time() - scan.t_start, 3),
        'landmark_module': 'geom.anthro.landmarks (%d spec rows)' % len(LMK.LANDMARK_SPEC),
    }


def unmeasurable_rows(M: dict) -> None:
    """Record every UNMEASURABLE table row — the dimensions this cage, in this
    pose, cannot produce — so a consumer never has to guess why one is absent."""
    for spec in UNMEASURABLE:
        M[spec['name']] = _rec(
            None,
            spec['kind'],
            spec['landmark'],
            'not available on this cage / in this pose',
            spec['iso_class'],
            spec['reason'],
            provenance='UNMEASURABLE',
            reason=spec['reason'],
        )
