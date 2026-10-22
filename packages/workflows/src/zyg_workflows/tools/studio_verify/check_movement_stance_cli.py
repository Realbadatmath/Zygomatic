# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.studio_verify.check_movement_stance`, moved out of the
library module so that library code never prints;
`python -m zyg_workflows.tools.studio_verify.check_movement_stance` still reaches it.
"""

import json
import os
import sys

import numpy as np
from scipy.spatial import cKDTree

from zyg_workflows.tools.studio_verify.check_movement_stance import (
    ACTORS,
    FOOT_AGREE_DEG,
    FOOT_VS_CLIP_DEG,
    MOTION,
    REST_FOOT_DEG,
    RIB_OUT_MM,
    RIB_OUT_VERTS,
    _stance_mean,
    acc,
    bvh_load,
    bvh_world,
    foot_vector,
    glb_load,
    hip_axis,
    node_world,
    pelvis_toe_out,
)


def main(argv=None):
    # The library module's `if __name__` block passed sys.argv[1:] in; that block
    # is now a connector that calls main(), so the command line is read here.
    if argv is None:
        argv = sys.argv[1:]
    actor = argv[0] if argv else 'base_male_realistic__cmu_02_01'
    glb = os.path.join(ACTORS, actor, actor + '.glb')
    side = json.load(open(os.path.join(ACTORS, actor, actor + '.json')))
    g, bin_ = glb_load(glb)
    names = {i: n.get('name', '') for i, n in enumerate(g['nodes'])}
    idx = {v: k for k, v in names.items()}
    skin = g['skins'][0]
    joints = [names[j] for j in skin['joints']]
    ibm = acc(g, bin_, skin['inverseBindMatrices']).reshape(-1, 4, 4).transpose(0, 2, 1)

    def prim(i):
        p = g['meshes'][i]['primitives'][0]['attributes']
        return (acc(g, bin_, p['POSITION']), acc(g, bin_, p['JOINTS_0']).astype(int), acc(g, bin_, p['WEIGHTS_0']))

    body, bj, bw = prim(0)
    if len(g['meshes']) < 2:
        print('  this GLB carries no skeleton mesh: built before 2026-09-23, rebuild the actor before measuring it')
        return 1
    bones, sj, sw = prim(1)
    dom = np.array([joints[sj[i][np.argmax(sw[i])]] for i in range(len(bones))])
    bdom = np.array([joints[bj[i][np.argmax(bw[i])]] for i in range(len(body))])

    tracks, spans = {}, []
    anim = g['animations'][0]
    for ch in anim['channels']:
        s = anim['samplers'][ch['sampler']]
        t = acc(g, bin_, s['input'])[:, 0]
        tgt = ch['target']
        node_i, prop = (tgt[k] for k in ('node', 'path'))
        tracks[(names[node_i], prop)] = (t, acc(g, bin_, s['output']))
        spans.append(t)
    times = max(spans, key=len)

    def pose_at(ti):
        out = {}
        for (nm, path), (tt, vv) in tracks.items():
            out.setdefault(idx[nm], {})[path] = vv[int(np.argmin(np.abs(tt - ti)))]
        return out

    def skinned(pose, pos, jj, ww, keep):
        world = node_world(g, pose)
        mats = np.array([world[skin['joints'][k]] @ ibm[k] for k in range(len(joints))])
        v = np.concatenate([pos[keep], np.ones((keep.sum() if keep.dtype == bool else len(keep), 1))], 1)
        out = np.zeros((len(v), 3))
        for k in range(jj.shape[1]):
            out += np.einsum('nij,nj->ni', mats[jj[keep][:, k]], v)[:, :3] * ww[keep][:, k][:, None]
        return out, world

    fails = []
    print('actor %s   clip %s   %d frames @ %s fps' % (actor, side['motion'], side['frames'], side['fps']))

    # (a) the stance ---------------------------------------------------------
    # cmu, capture and edit clips are three buckets of one library, and all
    # three are BVH on disk; 'authored' clips are keyframed actions with no BVH
    # and no rest alignment, so there is nothing to compare them against.
    lib = json.load(open(os.path.join(MOTION, 'library.json')))
    rec, bucket = next(
        ((c, b) for b in ('clips', 'capture', 'edit') for c in lib.get(b) or [] if c['id'] == side['motion']),
        (None, None),
    )
    if rec is None:
        print(
            '  %s carries no BVH (an authored action?): the stance has nothing to be measured against' % side['motion']
        )
        return 1
    # A capture's frame 1 is the reference pose motion_capture.py prepends, and
    # that is exactly the frame align_rest and the retarget work from.
    rest_frame = int(rec.get('rest_frame') or 0)
    bj_, bd = bvh_load(os.path.join(MOTION, rec['file']))
    bd = bd[max(0, rest_frame - 1) :]  # frame 1 of the retarget
    rest = node_world(g)
    rest_lat = hip_axis(rest, lambda n: idx[n])
    clip_lat = hip_axis(bvh_world(bj_, bd[0]), lambda n: n)

    # THE REST POSE IS THE CLIP'S FRAME 1, not a neutral stance, because that
    # is what align_rest makes it and what the delta retarget then reproduces.
    # On cmu/02_01 the clip stands with its feet straight, so the actor does;
    # on a capture, whose frame 1 is the subject's own first-frame pose (see
    # motion_capture.py's prepended reference frame), the actor stands the way
    # the subject did -- asymmetrically, and correctly. So the rest feet are
    # measured AGAINST THE CLIP'S, in each one's own pelvis frame.
    w0 = bvh_world(bj_, bd[0])
    clip_rest = {
        s2: pelvis_toe_out(clip_lat, w0[pre + 'ToeBase'][:3, 3] - w0[pre + 'Foot'][:3, 3], s2)
        for s2, pre in (('L', 'Left'), ('R', 'Right'))
    }

    # ONLY A CMU CLIP'S FRAME 1 IS A STANDING POSE. Those subjects stand
    # before they walk, so the actor's rest feet and its stance can be held
    # against the clip's. A capture's frame 1 is whatever the subject was doing
    # when the camera started -- on capture/qa_sword one foot is already turned
    # 23 deg out -- and an edit may have trimmed or mirrored that frame away. On
    # those the stance numbers are printed and left unasserted, because there is
    # no reference to assert them against. The chest is asserted on every clip.
    standing = bucket == 'clips'
    if not standing:
        print(
            '  %s is a %s clip: its frame 1 is not a standing pose, so the stance '
            'numbers below are printed, not asserted' % (side['motion'], bucket)
        )

    for tag, pos, keep_dom in (('body', body, bdom), ('skeleton', bones, dom)):
        for s2, pre in (('L', 'Left'), ('R', 'Right')):
            vec = foot_vector(pos, (keep_dom == pre + 'Foot') | (keep_dom == pre + 'ToeBase'))
            got = pelvis_toe_out(rest_lat, vec, s2)
            gap = abs(got - clip_rest[s2])
            print(
                '  rest %-8s %s foot %+6.1f deg out, clip frame 1 %+6.1f -> %.1f apart'
                % (tag, s2, got, clip_rest[s2], gap)
            )
            if standing and gap > REST_FOOT_DEG:
                fails.append(
                    "%s %s foot rests %+.1f deg out against the clip's %+.1f "
                    '(max %.1f apart)' % (tag, s2, got, clip_rest[s2], REST_FOOT_DEG)
                )
    for s2, pre in (('L', 'Left'), ('R', 'Right')):
        a = pelvis_toe_out(rest_lat, foot_vector(body, (bdom == pre + 'Foot') | (bdom == pre + 'ToeBase')), s2)
        b = pelvis_toe_out(rest_lat, foot_vector(bones, (dom == pre + 'Foot') | (dom == pre + 'ToeBase')), s2)
        print('  skeleton vs body foot, %s: %.1f deg apart' % (s2, abs(a - b)))
        if standing and abs(a - b) > FOOT_AGREE_DEG:
            fails.append(
                '%s: the skeleton foot and the body foot are %.1f deg apart (max %.1f)'
                % (s2, abs(a - b), FOOT_AGREE_DEG)
            )

    # STANCE, and how it is picked. A foot pointing down has almost no
    # horizontal axis left, so its progression angle is noise -- at toe-off the
    # same foot reads +60 deg in the BVH itself. So a frame counts only when the
    # foot is nearly as flat as it rests (FLAT_FRAC of its resting horizontal
    # length) and low: the lowest LOW_FRAC of that foot's frames.
    actor_stance, clip_stance = {}, {}
    for s2, pre in (('L', 'Left'), ('R', 'Right')):
        flat0 = np.linalg.norm((rest[idx[pre + 'ToeBase']][:3, 3] - rest[idx[pre + 'Foot']][:3, 3])[[0, 2]])
        rows = []
        for ti in times:
            world = node_world(g, pose_at(ti))
            ankle, toe = world[idx[pre + 'Foot']][:3, 3], world[idx[pre + 'ToeBase']][:3, 3]
            rows.append(
                (
                    min(ankle[1], toe[1]),
                    np.linalg.norm((toe - ankle)[[0, 2]]),
                    pelvis_toe_out(hip_axis(world, lambda n: idx[n]), toe - ankle, s2),
                )
            )
        actor_stance[s2] = _stance_mean(rows, flat0)
        flat0 = np.linalg.norm((w0[pre + 'ToeBase'][:3, 3] - w0[pre + 'Foot'][:3, 3])[[0, 2]])
        rows = []
        for f in range(0, len(bd), 5):
            w = bvh_world(bj_, bd[f])
            ankle, toe = w[pre + 'Foot'][:3, 3], w[pre + 'ToeBase'][:3, 3]
            rows.append(
                (
                    min(ankle[1], toe[1]),
                    np.linalg.norm((toe - ankle)[[0, 2]]),
                    pelvis_toe_out(hip_axis(w, lambda n: n), toe - ankle, s2),
                )
            )
        clip_stance[s2] = _stance_mean(rows, flat0)
    for s2 in 'LR':
        gap = abs(actor_stance[s2] - clip_stance[s2])
        print(
            '  stance progression %s: actor %+5.1f deg, clip %+5.1f deg -> %.1f apart'
            % (s2, actor_stance[s2], clip_stance[s2], gap)
        )
        if standing and not (gap <= FOOT_VS_CLIP_DEG):
            fails.append(
                "%s stance %+.1f deg vs the clip's %+.1f (max %.1f apart)"
                % (s2, actor_stance[s2], clip_stance[s2], FOOT_VS_CLIP_DEG)
            )

    # (b) the chest, over every frame ---------------------------------------
    h = body[:, 1].max()
    chest = np.where(
        (body[:, 0] < -0.085)
        & (body[:, 0] > -0.15)
        & (body[:, 1] > 0.66 * h)
        & (body[:, 1] < 0.74 * h)
        & (body[:, 2] > 0.0)
    )[0]
    ribs = np.where(
        (dom == 'Spine1')
        & (bones[:, 0] < -0.085)
        & (bones[:, 0] > -0.15)
        & (bones[:, 1] > 0.66 * h)
        & (bones[:, 1] < 0.74 * h)
        & (bones[:, 2] > 0.0)
    )[0]
    worst_n, worst_mm, worst_t = 0, 0.0, None
    for ti in times:
        pose = pose_at(ti)
        b, _ = skinned(pose, body, bj, bw, chest)
        r, _ = skinned(pose, bones, sj, sw, ribs)
        tree = cKDTree(b[:, [1, 2]])
        d, i = tree.query(r[:, [1, 2]])
        gap = (np.abs(b[i][:, 0]) - np.abs(r[:, 0]))[d < 0.02]
        if gap.size and (gap < 0).sum() >= worst_n:
            if (gap < 0).sum() > worst_n or -1000.0 * gap.min() > worst_mm:
                worst_n, worst_mm, worst_t = int((gap < 0).sum()), max(0.0, -1000.0 * gap.min()), ti
    print(
        '  chest over %d frames: worst %d of %d ribcage vertices outside the skin '
        'by %.1f mm (at t=%s)'
        % (len(times), worst_n, len(ribs), worst_mm, '%.2f' % worst_t if worst_t is not None else '-')
    )
    if worst_n > RIB_OUT_VERTS or worst_mm > RIB_OUT_MM:
        fails.append(
            'the chest swallows %d ribcage vertices by %.1f mm (max %d / %.1f)'
            % (worst_n, worst_mm, RIB_OUT_VERTS, RIB_OUT_MM)
        )

    if fails:
        print('\nFAIL')
        for f in fails:
            print('  - %s' % f)
        return 1
    print('\nPASS — the actor walks the clip and its chest stays over its ribs')
    return 0


if __name__ == '__main__':
    sys.exit(main())
