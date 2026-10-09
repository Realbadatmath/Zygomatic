# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The reissue and derive commands.

Moved verbatim out of the old single-file mesh_skeletons.py (lines 2900-3301).
"""

import os
import time

from zyg_workflows.geom.mesh_skeletons.spec import DISPLAY_SUBDIV, MESH3D_SUBDIV, ORIGINAL_SPEC, ROOT

from zyg_workflows.geom.mesh_skeletons.rig import _build_mesh, _sha256

from zyg_workflows.geom.mesh_skeletons.anatomy import _apply_anatomy

from zyg_workflows.geom.mesh_skeletons.artifacts import (
    _atomic_json,
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

from zyg_workflows.geom.mesh_skeletons.anthro import STYLIZATION_AXIS, _anthro_gate, _apply_spec, _character_spec

from zyg_workflows.geom.mesh_skeletons.originals import verify_originals

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def reissue(names=None, dry_run=False, set_anatomy=None, force=False, set_target=None):
    """Rebuild registered bodies from their OWN params.json under the current house layers.

    WHY THIS EXISTS RATHER THAN `build-originals --force` PLUS A `derive` PER CHARACTER.
    Re-running the issue commands means reconstructing every argument of the original
    invocation from memory or from params.json by hand — phenotype, inherited locals,
    anatomy layer, ancestry, target height, stylization intent — and any one of them
    typed differently issues a DIFFERENT character under the same name while claiming to
    have merely refreshed it. params.json already IS the recipe; this reads it back and
    changes only what the house layer changes.

    What it rewrites: the correction block, the cage hash, the measured blocks, the GLB,
    the previews and the 3D geometry, and the gate report. What it does not touch:
    phenotype, local_changes, anatomy_layer, character_spec, ancestry, stylization, sex,
    height_target_m, note, or any declaration. Those are inputs, and a re-issue that
    edited an input would not be a re-issue.

    Prints a BEFORE/AFTER cage hash for every body, because "nothing changed" and "the
    change was applied" have to be distinguishable from the output alone.

    `set_anatomy` is the ONE exception to "changes no declared input", and it is explicit
    for that reason: anatomy_layer IS a declaration, so changing it is a re-derivation
    decision and not a refresh. It exists because the alternative — hand-editing
    params.json — leaves no record of who changed the declaration or why. Every key set
    this way is recorded in `anatomy_layer_changed` on the body, with its previous value,
    so the edit is visible in the artifact rather than only in a shell history.

    `set_target` is the SECOND such exception, and it exists for the same reason.
    t1_build_target_stature reads params['height_target_m'] and reports MISSING without
    one, so a body derived before anyone thought to pass `target_height_m=` can never
    run a blocking Tier-1 gate. build_originals() has always recorded the field;
    derive() records it only when the caller declares one, and the two derived bodies on
    this registry were issued without.

    IT DOES NOT SOLVE FOR THE TARGET AND IT MOVES NO VERTEX. A build target is a
    DECLARATION — a statement of what the recipe was asking for — and the gate's whole
    job is to compare the delivered stature against it. Deriving the target FROM the
    delivered stature would make the comparison tautological: the gate would pass by
    construction on every body forever and measure nothing. So this records a number the
    operator supplies and nothing else, keeps the previous value in
    `height_target_changed`, and stamps `build_target_source` with who declared it, so a
    reader can always tell a declared target from a laundered one. If the number does
    not match what the recipe actually builds, the gate is MEANT to fail.

    The three-state contract on the field mirrors the one hand_correction keeps:
      recorded already   -> carried forward untouched (a re-issue edits no input)
      declared here      -> recorded, with its previous value and provenance
      neither            -> stays ABSENT, and the gate goes on reporting MISSING.
    Never invented. A body issued before the field existed keeps reproducing its own
    cage hash either way: the field is metadata and no vertex depends on it.

    `force` re-issues a body whose recipe reproduces its recorded cage EXACTLY — normally
    skipped as 'identical'. It exists to repair the aux-hash defect below, and it is the
    SOUND way to do that repair rather than a blunt override: `moved == False` means
    _rebuild_from_params reproduced p['cage_vert_sha256'] bit for bit, which is the only
    real proof that the body on disk is the body the registry claims. Re-blessing on any
    weaker evidence — an mtime, or 'the GLB still verifies' — would launder a genuinely
    changed body, and rec['sha256'] in particular is NOT independent evidence here
    because this same function re-records it.

    THE AUX-HASH DEFECT (found 2026-08-26, present since 2026-08-08). This function
    regenerates all nine aux files of an original — six previews, mesh3d.bin, params.json
    and anthro_report.json — and used to re-record only the GLB hash, carrying the old
    `aux_sha256` forward through `dict(entry)`. Both originals therefore read HASH
    MISMATCH on every load while their GLBs verified perfectly, and because
    `verify_originals()` gates `derive()`, no new character could be issued at all. The
    re-record now happens where it must: AFTER `_atomic_json` writes params.json and
    AFTER `_anthro_gate` writes the report. Recording it beside `_emit_visuals` — the
    intuitive spot — would capture the PREVIOUS params.json and reproduce the bug in a
    subtler form. No `_aux_assert_unrewritten_intact` call is appropriate: this path
    legitimately rewrites the entire set, which is exactly why it must record all of it.

    Two further defects fixed alongside: the directory was left WRITE-ENABLED (both
    originals were sitting at mode 755 with 644 files instead of 555/444 because
    `_write_enable` had no matching `_write_protect`), and the registry was saved once at
    the very end, so a crash mid-run lost every body already rebuilt.
    """
    from zyg_workflows.geom.anthro import hand_correction as HC

    reg = _registry()
    todo = []
    for grp in ('originals', 'derived'):
        for nm, entry in sorted((reg.get(grp) or {}).items()):
            if names and nm not in names:
                continue
            todo.append((grp, nm, entry))
    if names:
        missing = sorted(set(names) - {nm for _g, nm, _e in todo})
        if missing:
            raise SystemExit('no registered body named: %s' % ', '.join(missing))
    if not todo:
        raise SystemExit('nothing to re-issue')

    _zyg_log.info('re-issuing %d bodies%s' % (len(todo), ' (DRY RUN)' if dry_run else ''))
    changed = []
    for grp, nm, entry in todo:
        p = dict(entry['params'])
        phen = p['phenotype']
        locs = p.get('local_changes') or None
        anat = dict(p.get('anatomy_layer') or {})
        req = p.get('bone_scales') or None
        old_sha = p.get('cage_vert_sha256')

        anat_changed = {}
        for k, val in (set_anatomy or {}).items():
            before = anat.get(k)
            if before == val:
                continue
            anat_changed[k] = {'from': before, 'to': val}
            if val in (None, 0, 0.0, ''):
                anat.pop(k, None)
            else:
                anat[k] = val
        if anat_changed:
            _zyg_log.info(
                '  %-12s anatomy_layer CHANGED: %s'
                % (nm, ', '.join('%s %s -> %s' % (k, c['from'], c['to']) for k, c in sorted(anat_changed.items())))
            )
        anat = anat or None

        target_changed = None
        if set_target and nm in set_target:
            want = set_target[nm]
            want = None if want is None else round(float(want), 6)
            have = p.get('height_target_m')
            if have is not None and want is not None and abs(have - want) < 1e-9:
                pass
            elif have == want:
                pass
            else:
                target_changed = {'from': have, 'to': want}
                _zyg_log.info('  %-12s height_target_m DECLARED: %s -> %s m' % (nm, have, want))

        # params=None on purpose: this is the one path that is ALLOWED to solve a new
        # correction for an already-issued body. Everywhere else, params carrying no
        # hand_correction means "reproduce the hand that shipped".
        eff, hc = HC.effective_scales(phen, locs, req, None)
        v, faces, applied = _build_mesh(phen, locs, eff, apply_hand_correction=False)
        v = _apply_anatomy(v, faces, anat, phenotype=phen, local_changes=locs, bone_scales=eff)
        new_sha = _vert_sha(v)
        # A declaration-only change moves no vertex, so `new_sha != old_sha` is False and
        # the body would be skipped as 'identical' with the declaration silently dropped.
        # It counts as a reason to rewrite the artifacts (params.json and the gate report
        # both carry it) while the cage hash below still prints UNCHANGED, which is
        # exactly the pair of facts a reader needs.
        moved = new_sha != old_sha or bool(anat_changed) or bool(target_changed)
        # The verdict word is about the CAGE, and a declaration-only re-issue moves no
        # vertex. Printing 'CHANGED' next to two identical hashes would tell a reader
        # the geometry moved when the hashes on the same line say it did not.
        if new_sha != old_sha:
            verdict = 'CHANGED'
        elif moved:
            verdict = 'identical cage; DECLARATION changed'
        else:
            verdict = 'identical'
        _zyg_log.info('  %-12s %s -> %s  %s' % (nm, (old_sha or 'none')[:16], new_sha[:16], verdict))
        if hc.get('applied'):
            _zyg_log.info(
                '       phalanx correction v%d, %d passes, residual %.1e'
                % (hc['version'], hc['iterations'], hc['residual'])
            )
        if dry_run or not (moved or force):
            continue
        if not moved:
            _zyg_log.info(
                '       re-blessing an IDENTICAL body: the recipe reproduced the '
                'recorded cage hash, so every artifact below is regenerated from '
                'proven-equivalent geometry'
            )

        d = os.path.join(ROOT, entry['dir'])
        prev_glb_sha = entry.get('sha256')
        _write_enable(d)
        try:
            glb = _export_glb(v, faces, os.path.join(d, 'skeleton_%s.glb' % (nm if grp == 'derived' else nm)))
            views, m3, mdisp, m3meas = _emit_visuals(v, faces, d)
            p['bone_scales_resolved'] = applied
            p['hand_correction'] = hc
            if anat_changed:
                p['anatomy_layer'] = dict(anat or {})
                hist = list(p.get('anatomy_layer_changed') or [])
                hist.append({'when': time.strftime('%Y-%m-%dT%H:%M:%S'), 'changes': anat_changed})
                p['anatomy_layer_changed'] = hist
            if target_changed:
                # Written in BOTH places the readers use: gates.Subject.from_registry
                # reads params['height_target_m'], and _anthro_spec reads
                # character_spec['build_target_stature_mm']. Setting one and not the
                # other is how a body ends up declaring two different targets.
                if target_changed['to'] is None:
                    p.pop('height_target_m', None)
                else:
                    p['height_target_m'] = target_changed['to']
                cs = dict(p.get('character_spec') or {})
                cs['build_target_stature_mm'] = (
                    None if target_changed['to'] is None else round(target_changed['to'] * 1000.0, 3)
                )
                cs['build_target_source'] = (
                    'UNDECLARED — no target stature was recorded for this build.'
                    if target_changed['to'] is None
                    else 'declared by the operator through `mesh_skeletons reissue '
                    '--set-target` on an already-issued body; a statement of what the '
                    'recipe was asking for, not a solver input and not derived from the '
                    'delivered stature'
                )
                p['character_spec'] = cs
                hist = list(p.get('height_target_changed') or [])
                hist.append({'when': time.strftime('%Y-%m-%dT%H:%M:%S'), 'change': target_changed})
                p['height_target_changed'] = hist
            p['measured'] = _measure(v)
            p['measured_display'] = mdisp
            p['measured_mesh3d'] = m3meas
            p['cage_vert_sha256'] = new_sha
            p['reissued'] = time.strftime('%Y-%m-%dT%H:%M:%S')
            p['reissued_from_cage_sha256'] = old_sha
            # BEFORE the aux re-record: _anthro_gate writes anthro_report.json and
            # _atomic_json writes params.json, and both are IN the hashed set.
            p['anthro'], _doc = _anthro_gate(nm, v, faces, p, d)
            _atomic_json(os.path.join(d, 'params.json'), p, indent=1)
            new_glb_sha = _sha256(glb)
            if not moved and prev_glb_sha and new_glb_sha != prev_glb_sha:
                # The cage is identical vertex-for-vertex, so a differing GLB means the
                # EXPORTER is not byte-deterministic, not that the body changed. Say so
                # rather than letting a silent hash move look like a geometry edit.
                _zyg_log.info(
                    '       note: identical cage but the GLB re-exported to a new '
                    'hash (%s -> %s) — exporter non-determinism, geometry unchanged'
                    % (prev_glb_sha[:12], new_glb_sha[:12])
                )
            entry = dict(entry)
            entry.update(
                {
                    'glb': os.path.basename(glb),
                    'sha256': new_glb_sha,
                    'previews': views,
                    'params': p,
                    'mesh3d': m3,
                    'visuals_updated': p['reissued'],
                    'anthro': p['anthro'],
                    'anthro_report': p['anthro'].get('report'),
                }
            )
            if grp == 'originals':
                entry['aux_sha256'] = _aux_hashes(d, views)
            reg[grp][nm] = entry
            changed.append(nm)
            # Persist per body: a crash after the next body's ~90s render used to lose
            # every registration already completed in this run.
            _save_registry(reg)
        finally:
            if grp == 'originals':
                _write_protect(d)

    _zyg_log.info('re-issued %d of %d (%s)' % (len(changed), len(todo), ', '.join(changed) or 'none'))
    if changed and not dry_run:
        bad = verify_originals()
        # A run that leaves the immutability contract broken must not report success —
        # this is the check whose absence let the aux-hash defect survive for 18 days.
        _zyg_log.info('   originals verify: %s' % ('OK' if not bad else '; '.join(bad)))
        # Raise only when THIS run touched an original. A derived-only re-issue that
        # aborts because of a pre-existing originals problem it neither caused nor could
        # fix is a confusing failure; reporting it is the useful half.
        touched_originals = [n for n in changed if n in (reg.get('originals') or {})]
        if bad and touched_originals:
            raise SystemExit('re-issue completed but originals FAIL verification: %s' % '; '.join(bad))
    return changed


def derive(
    char_id,
    base='male',
    phenotype=None,
    local_changes=None,
    bone_scales=None,
    note='',
    inherit_base_locals=True,
    anatomy=None,
    ancestry=None,
    target_height_m=None,
    stylization_intent=None,
    declared_by=None,
):
    """Issue one character body from an original.

    ancestry / target_height_m / stylization_intent are DECLARATIONS, recorded in the
    character spec for the Tier-4 gates. target_height_m in particular is not a solver
    input — it does not move a vertex; it states what this build was ASKING for, so that
    the delivered stature can be checked against something instead of against nothing.
    Passing a target the recipe does not actually hit is meant to fail loudly.
    """
    reg = _registry()
    if base not in reg.get('originals', {}):
        raise SystemExit('no original %r — run build-originals first' % base)
    bad = verify_originals()
    if bad:
        raise SystemExit('REFUSING to derive: originals failed verification: %s' % '; '.join(bad))

    # the base recipe is what the registered original ACTUALLY is (incl. its calibrated
    # issue height AND its issue local morphs), not the pre-calibration spec — the
    # character then overrides on top. Inheritance is SYMMETRIC (phenotype + locals)
    # and the effective merged recipe is what gets recorded, so a re-derivation from
    # params.json reproduces the mesh exactly with inherit_base_locals=False.
    bparams = reg['originals'][base].get('params', {})
    phen = dict(bparams.get('phenotype') or ORIGINAL_SPEC[base])
    phen.update(phenotype or {})
    base_locs = dict(bparams.get('local_changes') or {}) if inherit_base_locals else {}
    eff_locals = dict(base_locs)
    eff_locals.update(local_changes or {})
    inherited = sorted(k for k in base_locs if k not in (local_changes or {}))
    if inherited:
        _zyg_log.info('  inheriting template locals from %s: %s' % (base, ', '.join(inherited)))
    anat = dict(bparams.get('anatomy_layer') or {}) if inherit_base_locals else {}
    anat.update(anatomy or {})  # explicit channel: params.json can reproduce via derive
    anat = {k: val for k, val in anat.items() if val}
    if anat:
        _zyg_log.info('  anatomy layer: %s' % ', '.join('%s=%s' % kv for kv in sorted(anat.items())))
    # Solve the phalanx correction HERE rather than letting _build_mesh do it silently,
    # because the solved scales have to be RECORDED in params.json: that is what lets a
    # rebuild reproduce this exact body instead of re-solving and drifting, and what makes
    # a body issued before the correction distinguishable from one issued after.
    from zyg_workflows.geom.anthro import hand_correction as HC

    eff_scales, hc_rec = HC.effective_scales(phen, eff_locals or None, bone_scales, None)
    if hc_rec.get('applied'):
        _zyg_log.info(
            '  phalanx correction v%d: %d bones, %d passes, residual %.1e'
            % (hc_rec['version'], len(hc_rec['scales']), hc_rec['iterations'], hc_rec['residual'])
        )
    else:
        _zyg_log.info('  phalanx correction NOT applied: %s' % hc_rec.get('why'))
    v, faces, applied = _build_mesh(phen, eff_locals or None, eff_scales, apply_hand_correction=False)
    v = _apply_anatomy(v, faces, anat, phenotype=phen, local_changes=eff_locals or None, bone_scales=eff_scales)

    d = os.path.join(ROOT, 'derived', char_id)
    os.makedirs(d, exist_ok=True)
    glb = _export_glb(v, faces, os.path.join(d, 'skeleton_%s.glb' % char_id))
    views, m3, mdisp, m3meas = _emit_visuals(v, faces, d)
    params = {
        'kind': 'DERIVED',
        'char_id': char_id,
        'base': base,
        'base_sha256': reg['originals'][base]['sha256'],
        'phenotype': phen,
        'local_changes': eff_locals,
        'local_changes_inherited_from_base': inherited,
        'anatomy_layer': anat,
        # `bone_scales` stays the OPERATOR'S request and nothing else, so params.json
        # keeps saying what was asked for. The house correction is a separate, versioned,
        # visible block; `bone_scales_resolved` is the merged set that actually built the
        # mesh, which is where the two meet.
        'bone_scales': dict(bone_scales or {}),
        'bone_scales_resolved': applied,
        'hand_correction': hc_rec,
        'measured': _measure(v),
        'measured_display': mdisp,
        'display_subdiv_level': DISPLAY_SUBDIV,
        'measured_mesh3d': m3meas,
        'mesh3d_subdiv_level': MESH3D_SUBDIV,
        'cage_vert_sha256': _vert_sha(v),
        'note': note,
        'built': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    bsex = bparams.get('sex') or ('female' if float(phen.get('gender', 0.0)) > 0.5 else 'male')
    _apply_spec(
        params,
        _character_spec(
            phen,
            bsex,
            sex_source='inherited from the %r original, whose sex is declared in its params.json' % base,
            ancestry=ancestry,
            ancestry_source=('declared by the caller of derive()' if ancestry else None),
            build_target_m=target_height_m,
            build_target_source=(
                'declared by the caller of derive(); it is a statement of intent, not a solver input'
                if target_height_m
                else None
            ),
            stylization_explicit=STYLIZATION_AXIS in (phenotype or {}),
            stylization_intent=stylization_intent,
            declared_by=declared_by,
        ),
    )
    params['anthro'], _doc = _anthro_gate(char_id, v, faces, params, d)
    _atomic_json(os.path.join(d, 'params.json'), params, indent=1)
    reg['derived'][char_id] = {
        'dir': os.path.relpath(d, ROOT),
        'glb': os.path.basename(glb),
        'sha256': _sha256(glb),
        'previews': views,
        'params': params,
        'mesh3d': m3,
        'visuals_updated': params['built'],
        'anthro': params['anthro'],
        'anthro_report': params['anthro'].get('report'),
    }
    _save_registry(reg)
    _zyg_log.info(
        '  derived %s from %s: %d verts, %.3fm (original verified untouched)'
        % (char_id, base, params['measured']['vertices'], params['measured']['height_m'])
    )
    return reg['derived'][char_id]
