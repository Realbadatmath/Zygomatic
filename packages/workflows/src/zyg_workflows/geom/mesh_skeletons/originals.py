# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The originals commands: gate-registered, height calibration,
build-originals, refresh-previews and verify-originals.

Moved verbatim out of the old single-file mesh_skeletons.py (lines 2575-2899).
"""

import glob
import os
import time
import traceback

from zyg_workflows.geom.mesh_skeletons.spec import (
    AUX_NOT_REGENERATED_BY_REFRESH,
    AUX_REGENERATED_BY_GATE,
    DISPLAY_SUBDIV,
    MESH3D_SUBDIV,
    ORIGINAL_ANATOMY,
    ORIGINAL_LOCALS,
    ORIGINAL_PHEN,
    ORIGINAL_SPEC,
    ROOT,
    TARGET_HEIGHT_M,
)

from zyg_workflows.geom.mesh_skeletons.rig import _bone_names, _build_mesh, _model, _sha256

from zyg_workflows.geom.mesh_skeletons.anatomy import _apply_anatomy

from zyg_workflows.geom.mesh_skeletons.artifacts import (
    _atomic_json,
    _aux_assert_unrewritten_intact,
    _aux_hashes,
    _emit_visuals,
    _export_glb,
    _measure,
    _registry,
    _save_registry,
    _vert_sha,
    _write_enable,
    _write_protect,
)

from zyg_workflows.geom.mesh_skeletons.anthro import (
    ORIGINAL_STYLIZATION_INTENT,
    STYLIZATION_AXIS,
    _anthro_gate,
    _apply_spec,
    _backfill_spec,
    _character_spec,
    _rebuild_from_params,
)

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def gate_registered(names=None):
    """(Re-)gate already-issued characters in place, without touching a single vertex.

    This exists because the gates were added after the bodies were issued. It rebuilds
    each body from its recipe, verifies the cage hash, writes anthro_report.json beside
    the mesh and records the summary in params.json and the registry. The GLB is never
    rewritten.

    For an ORIGINAL that means params.json changes and a new file appears in a
    write-protected directory, so the aux hash set is RE-RECORDED afterwards — exactly
    what refresh_previews() already does when the visual surface legitimately changes.
    The pinned geometry hash (rec['sha256'], the GLB) is not touched and is re-verified
    at the end.

    Returns {name: summary}. The VERDICT is deliberately not the return value: a body
    outside a band is unusual by a stated amount, not broken, and this function's job is
    to make sure the number exists — the caller decides what to do with it.
    """
    reg = _registry()
    out = {}
    for kind in ('originals', 'derived'):
        for key, rec in reg.get(kind, {}).items():
            if names and key not in names:
                continue
            d = os.path.join(ROOT, rec['dir'])
            p = rec['params']
            if kind == 'originals':
                _write_enable(d)
            try:
                # `gate` rewrites params.json and anthro_report.json and nothing else, so
                # the previews and mesh3d.bin it is about to re-record hashes for must
                # still match what was recorded at issue. Checked before any write.
                if kind == 'originals':
                    _aux_assert_unrewritten_intact(d, rec.get('aux_sha256'), set(AUX_REGENERATED_BY_GATE), 'gate')
                p['character_spec'] = p.get('character_spec') or _backfill_spec(p, key)
                _apply_spec(p, p['character_spec'])
                v, faces = _rebuild_from_params(p, key)
                summary, _doc = _anthro_gate(key, v, faces, p, d)
                p['anthro'] = summary
                _atomic_json(os.path.join(d, 'params.json'), p, indent=1)
                rec['anthro'] = summary
                if summary.get('report'):
                    rec['anthro_report'] = summary['report']
                if kind == 'originals':
                    rec['aux_sha256'] = _aux_hashes(d, rec.get('previews'))
                out[key] = summary
            except Exception as e:  # noqa: BLE001
                _zyg_log.info('  FAILED %s/%s: %s — entry left as it was' % (kind, key, e))
                traceback.print_exc()
                out[key] = {'status': 'gate-error', 'error': '%s: %s' % (type(e).__name__, e)}
                continue
            finally:
                if kind == 'originals':
                    _write_protect(d)
            _save_registry(reg)
    unknown = [n for n in (names or []) if n not in out]
    if unknown:
        _zyg_log.info('  NOT IN THE REGISTRY, nothing gated: %s' % ', '.join(unknown))
    bad = verify_originals()
    if bad:
        _zyg_log.info('originals after gating: %s' % bad)
    else:
        _zyg_log.info(
            'originals after gating: verified-immutable (GLBs untouched, aux re-recorded over the new report)'
        )
    return out


def _calibrate_height(phen, target_m, tol=0.0005, iters=18, locals_=None):
    """Binary-search the height axis until the measured vertex span hits target_m.

    Measured against the same z-span the cards display, so what is asked for is what
    is shown. Returns (height_axis_value, achieved_m); prints a warning if the target
    sits outside the axis range instead of silently clamping.
    """
    lo, hi = 0.0, 1.0
    best = (phen.get('height', 0.5), None)
    for edge in (lo, hi):
        v, _, _ = _build_mesh({**phen, 'height': edge}, locals_)
        h = _measure(v)['height_m']
        if edge == lo and target_m < h:
            _zyg_log.info('  WARNING: target %.3fm below axis minimum %.3fm — clamping' % (target_m, h))
            return lo, h
        if edge == hi and target_m > h:
            _zyg_log.info('  WARNING: target %.3fm above axis maximum %.3fm — clamping' % (target_m, h))
            return hi, h
    for _ in range(iters):
        mid = (lo + hi) / 2.0
        v, _, _ = _build_mesh({**phen, 'height': mid}, locals_)
        h = _measure(v)['height_m']
        best = (mid, h)
        if abs(h - target_m) <= tol:
            break
        if h < target_m:
            lo = mid
        else:
            hi = mid
    return best


def build_originals(force=False):
    reg = _registry()
    m = _model()
    vocab = [str(x) for x in getattr(m, 'local_change_labels', [])]
    for sex, phen in ORIGINAL_SPEC.items():
        d = os.path.join(ROOT, 'originals', sex)
        if reg['originals'].get(sex) and not force:
            _zyg_log.info(
                '  original %s exists — refusing to rebuild (it is an ORIGINAL); '
                'use --force only if you mean to re-issue the template' % sex
            )
            continue
        if force:
            _write_enable(d)
        os.makedirs(d, exist_ok=True)
        try:
            phen = dict(phen)
            phen.update(ORIGINAL_PHEN.get(sex) or {})
            locs = dict(ORIGINAL_LOCALS.get(sex) or {})
            target = TARGET_HEIGHT_M.get(sex)
            if target:
                hv, achieved = _calibrate_height(phen, target, locals_=locs)
                phen['height'] = round(float(hv), 6)
                _zyg_log.info('  %s height axis %.4f -> %.4fm (target %.2fm)' % (sex, phen['height'], achieved, target))
            anat = dict(ORIGINAL_ANATOMY.get(sex) or {})
            from zyg_workflows.geom.anthro import hand_correction as HC

            eff_scales, hc_rec = HC.effective_scales(phen, locs or None, None, None)
            if hc_rec.get('applied'):
                _zyg_log.info(
                    '  phalanx correction v%d: %d bones, %d passes, residual %.1e'
                    % (hc_rec['version'], len(hc_rec['scales']), hc_rec['iterations'], hc_rec['residual'])
                )
            v, faces, _ = _build_mesh(phen, locs, eff_scales, apply_hand_correction=False)
            v = _apply_anatomy(v, faces, anat, phenotype=phen, local_changes=locs, bone_scales=eff_scales)
            glb = _export_glb(v, faces, os.path.join(d, 'skeleton_%s.glb' % sex))
            views, m3, mdisp, m3meas = _emit_visuals(v, faces, d)
            params = {
                'kind': 'ORIGINAL',
                'sex': sex,
                'phenotype': phen,
                'local_changes': locs,
                'anatomy_layer': anat,
                'height_target_m': target,
                'adjustable': {
                    'phenotype_axes': ['gender', 'age', 'muscle', 'weight', 'height', 'proportions'],
                    'local_change_labels': vocab,
                    'bone_scale': 'any of the %d rig bone names below, matched as a '
                    'case-insensitive SUBSTRING (e.g. "upperleg" scales '
                    'both thighs). A key matching none of them is a hard '
                    'error, not a no-op.' % len(_bone_names(m)),
                    'bone_scale_names': [str(x) for x in _bone_names(m)],
                },
                'hand_correction': hc_rec,
                'measured': _measure(v),
                'measured_display': mdisp,
                'display_subdiv_level': DISPLAY_SUBDIV,
                'measured_mesh3d': m3meas,
                'mesh3d_subdiv_level': MESH3D_SUBDIV,
                'cage_vert_sha256': _vert_sha(v),
                'source': 'anny 0.5 (Apache-2.0 code, CC0 MakeHuman-derived data)',
                'built': time.strftime('%Y-%m-%dT%H:%M:%S'),
            }
            _apply_spec(
                params,
                _character_spec(
                    phen,
                    sex,
                    build_target_m=target,
                    build_target_source='TARGET_HEIGHT_M, operator-specified at issue and '
                    'solved for by _calibrate_height',
                    stylization_explicit=STYLIZATION_AXIS in (ORIGINAL_PHEN.get(sex) or {}),
                    stylization_intent=ORIGINAL_STYLIZATION_INTENT,
                    declared_by='geom.mesh_skeletons ORIGINAL_PHEN',
                ),
            )
            # gate BEFORE params.json is written and before the aux hashes are taken, so
            # the report is part of the hashed, write-protected issue rather than a file
            # that appeared next to one
            params['anthro'], _doc = _anthro_gate(sex, v, faces, params, d)
            _atomic_json(os.path.join(d, 'params.json'), params, indent=1)
            sha = _sha256(glb)
            entry = {
                'dir': os.path.relpath(d, ROOT),
                'glb': os.path.basename(glb),
                'sha256': sha,
                'previews': views,
                'params': params,
                'immutable': True,
                'mesh3d': m3,
                'visuals_updated': params['built'],
                'anthro': params['anthro'],
                'anthro_report': params['anthro'].get('report'),
            }
            entry['aux_sha256'] = _aux_hashes(d, views)
            reg['originals'][sex] = entry
        except Exception as e:  # noqa: BLE001
            _zyg_log.info(
                '  FAILED %s: %s — files on disk may mismatch the registry; re-run build-originals --force' % (sex, e)
            )
            continue
        finally:
            # NEVER leave an originals dir write-enabled — not on Ctrl-C, not on a
            # failed render, not on disk-full
            _write_protect(d)
        # persist per entry: a crash during the NEXT original must not orphan this one
        _save_registry(reg)
        _zyg_log.info(
            '  ORIGINAL %s: %d verts, %.3fm, sha %s… (write-protected)'
            % (sex, params['measured']['vertices'], params['measured']['height_m'], sha[:12])
        )
    return reg


def _gate_rebuild(got, issued):
    """Does the rebuilt mesh match the issued one? Checked on every measurement we
    stored — a library upgrade that keeps the z-span but shifts topology or proportions
    must NOT silently repaint the visualisation of a pinned GLB."""
    if got['vertices'] != issued.get('vertices', got['vertices']):
        return 'vertex count %d != issued %d' % (got['vertices'], issued['vertices'])
    for k, tol in (('height_m', 0.002), ('span_x_m', 0.005), ('span_y_m', 0.005)):
        if k in issued and abs(got[k] - issued[k]) > tol:
            return '%s %.4f != issued %.4f' % (k, got[k], issued[k])
    return None


def refresh_previews():
    """Re-render previews + mesh3d for every registered skeleton WITHOUT touching the
    hashed GLBs. The immutability contract covers the GEOMETRY; its visualisation may
    improve. Crash-safe by construction: new renders overwrite deterministic names (no
    delete-then-render window), every write is atomic or verified, and an originals dir
    is re-write-protected in a finally whatever happens mid-entry."""
    reg = _registry()
    ok_all = True
    for kind in ('originals', 'derived'):
        for key, rec in reg.get(kind, {}).items():
            d = os.path.join(ROOT, rec['dir'])
            p = rec['params']
            changed = False
            if kind == 'originals':
                _write_enable(d)
            try:
                # BEFORE anything is rewritten: this command regenerates every hashed aux
                # file EXCEPT the anthro report, so the report's recorded hash must still
                # match or the re-record at the end would silently bless it. Checked up
                # front so a refusal really does leave the entry byte-identical.
                if kind == 'originals':
                    _aux_assert_unrewritten_intact(
                        d,
                        rec.get('aux_sha256'),
                        {k for k in (rec.get('aux_sha256') or {}) if k not in AUX_NOT_REGENERATED_BY_REFRESH},
                        'refresh-previews',
                    )
                v, faces, _ = _build_mesh(p['phenotype'], p.get('local_changes') or None, p.get('bone_scales') or None)
                v = _apply_anatomy(
                    v,
                    faces,
                    p.get('anatomy_layer'),
                    phenotype=p['phenotype'],
                    local_changes=p.get('local_changes') or None,
                    bone_scales=p.get('bone_scales') or None,
                )
                why = _gate_rebuild(_measure(v), p['measured'])
                if not why and p.get('cage_vert_sha256') and _vert_sha(v) != p['cage_vert_sha256']:
                    why = 'cage vertex content differs from issue'
                if why:
                    _zyg_log.info(
                        '  SKIP %s/%s: %s — recipe no longer reproduces the registered mesh' % (kind, key, why)
                    )
                    ok_all = False
                    continue
                views, m3, mdisp, m3meas = _emit_visuals(v, faces, d)
                rec['mesh3d'] = m3
                rec['previews'] = views
                p['measured_display'] = mdisp
                p['display_subdiv_level'] = DISPLAY_SUBDIV
                p['measured_mesh3d'] = m3meas
                p['mesh3d_subdiv_level'] = MESH3D_SUBDIV
                _atomic_json(os.path.join(d, 'params.json'), p, indent=1)
                # strays from older naming schemes, only after the new set exists
                keep = {os.path.basename(x) for x in views}
                for old in glob.glob(os.path.join(d, 'view_*.png')) + glob.glob(os.path.join(d, 'head_*.png')):
                    if os.path.basename(old) not in keep:
                        os.remove(old)
                rec['visuals_updated'] = time.strftime('%Y-%m-%dT%H:%M:%S')
                if kind == 'originals':
                    rec['aux_sha256'] = _aux_hashes(d, views)
                changed = True
            except Exception as e:  # noqa: BLE001
                _zyg_log.info('  FAILED %s/%s: %s — entry left as it was' % (kind, key, e))
                ok_all = False
                continue
            finally:
                if kind == 'originals':
                    _write_protect(d)
            # persist per entry: a crash later in the run must not leave this entry's
            # fresh files unregistered (that would fail verification and brick derive)
            if changed:
                _save_registry(reg)
            _zyg_log.info('  refreshed %s %s: %d views + mesh3d.json' % (kind, key, len(rec['previews'])))
    bad = verify_originals()
    _zyg_log.info(
        'originals after refresh: %s' % ('verified-immutable (GLBs untouched, previews re-hashed)' if not bad else bad)
    )
    return ok_all and not bad


def verify_originals():
    """The immutability gate. Called before every derivation. Covers the GLB (the
    pinned geometry) AND every displayed file (previews, mesh3d, params) so the
    verification surface equals what the operator actually sees."""
    reg = _registry()
    bad = []
    for sex, rec in reg.get('originals', {}).items():
        d = os.path.join(ROOT, rec['dir'])
        p = os.path.join(d, rec['glb'])
        if not os.path.exists(p):
            bad.append('%s: MISSING' % sex)
        elif _sha256(p) != rec['sha256']:
            bad.append('%s: HASH MISMATCH — the original has been modified' % sex)
        for fn, want in (rec.get('aux_sha256') or {}).items():
            fp = os.path.join(d, fn)
            if not os.path.exists(fp):
                bad.append('%s: %s MISSING' % (sex, fn))
            elif _sha256(fp) != want:
                bad.append('%s: %s modified' % (sex, fn))
    return bad
