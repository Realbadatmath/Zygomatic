# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Proof — the actor WALKS THE CLIP, and its chest stays over its ribs.

Two defects the operator reported on 2026-09-24, both measured here off the
shipped artefacts (the actor's GLB and the clip's own BVH), no Blender and no
browser:

  (a) THE STANCE. The retarget gives every bone the rotation the BVH performs
      between frame 1 and frame t, on top of the rest pose -- so whatever the
      rest pose holds that the clip never corrects is added to every frame. The
      base body's A-pose stands with its feet turned out, and cmu/02_01 is a
      walk whose own stance foot progression angle is 1 deg: the actor played it
      with 19.6 deg of toe-out per foot, a 40 deg V, which is the "feet pointed
      to the side too much" of that report. proxy_actor.ALIGN_BONES now turns
      the leg chain to the BVH's frame 1 like the arms, so the clip's own leg
      angles come through. Measured: the foot bone, the body's own foot, and the
      fitted skeleton's foot, against the BVH's.

  (b) THE CHEST. Bone heat gave the chest wall to the two clavicle bones and the
      flank to the arm (sternum 70 % clavicle / 9 % Spine1, flank 18 % arm), so
      on a walk the chest swung with the arms and collapsed INWARD PAST THE
      RIBCAGE: 369 of 1190 lateral-chest ribcage vertices ended up outside the
      skin, by 28 mm, which through a muscle layer riding 1.5 mm under that skin
      is the "skin on his chest goes through the chest" of the same report.
      proxy_actor.bound_clavicles / bound_arm_chain hand that skin back to the
      thorax. Measured over every frame of the clip, not just the bind pose --
      the bind pose was never the pose that was wrong.

Run:  <venv>/bin/python \\
          tools/studio_verify/check_movement_stance.py [actor_name]
"""

import json
import math
import os
import struct
import sys

import numpy as np
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ACTORS = os.path.join(HERE, 'data', 'architecture', 'actors')
MOTION = os.path.join(HERE, 'data', 'assets', 'motion_library')

# Bounds. Each one passes on the actors built after 2026-09-24 and fails on the
# ones built before it; the measured value at the time is in the comment.
FOOT_VS_CLIP_DEG = 6.0  # stance progression angle vs the clip's: 1.5 vs 0.9
REST_FOOT_DEG = 6.0  # the body's own foot at rest: 1.0 (was 15.8)
FOOT_AGREE_DEG = 4.0  # skeleton foot vs body foot: 1.4 (was 3.8)
# The chest bound is set by the FEMALE body, which carries the same male CC0
# ribcage in a slimmer chest: 49 of its 1281 lateral-chest ribcage vertices
# still graze the skin by 3.4 mm at one frame of the walk, and looked at on the
# plate at exactly that frame, nothing shows -- what is left there is the skin
# moving over the ribs, not the fit under them. The male body reads 3 vertices
# at 1.4 mm. Before the fix: 369 vertices at 28.6 mm on cmu/02_01 and 446 at
# 34.2 mm on cmu/07_01, so this still catches that by a factor of seven.
RIB_OUT_VERTS = 60  # ribcage vertices out of the chest, any frame
RIB_OUT_MM = 5.0  # how far out the worst of them is


# ── glTF ────────────────────────────────────────────────────────────────────
_COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NUM = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}


def glb_load(path):
    with open(path, 'rb') as fh:
        data = fh.read()
    if data[:4] != b'glTF':
        raise ValueError('%s is not a GLB' % path)
    off, js, bins = 12, None, []
    while off < len(data):
        length, kind = struct.unpack('<II', data[off : off + 8])
        chunk = data[off + 8 : off + 8 + length]
        off += 8 + length
        if kind == 0x4E4F534A:
            js = json.loads(chunk)
        else:
            bins.append(chunk)
    return js, bins[0]


def acc(g, bin_, i):
    a = g['accessors'][i]
    n, dt = _NUM[a['type']], _COMP[a['componentType']]
    size = np.dtype(dt).itemsize
    bv = g['bufferViews'][a['bufferView']]
    base = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    stride = bv.get('byteStride') or n * size
    if stride == n * size:
        out = np.frombuffer(bin_, dtype=dt, count=a['count'] * n, offset=base)
        out = out.reshape(a['count'], n)
    else:
        rows = []
        for k in range(a['count']):
            start = base + k * stride
            rows.append(np.frombuffer(bin_, dtype=dt, count=n, offset=start))
        out = np.array(rows)
    return out.astype(np.float64) if dt == np.float32 else out


def quat_matrix(q):
    x, y, z, w = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def node_world(g, pose=None):
    parent = {}
    for i, node in enumerate(g['nodes']):
        for c in node.get('children', []):
            parent[c] = i
    out = {}

    def local(i):
        node = g['nodes'][i]
        t = np.array(node.get('translation', [0, 0, 0]), float)
        r = np.array(node.get('rotation', [0, 0, 0, 1]), float)
        s = np.array(node.get('scale', [1, 1, 1]), float)
        if pose and i in pose:
            t = pose[i].get('translation', t)
            r = pose[i].get('rotation', r)
            s = pose[i].get('scale', s)
        m = np.eye(4)
        m[:3, :3] = quat_matrix(r) * np.array(s)
        m[:3, 3] = t
        return m

    def walk(i):
        if i in out:
            return out[i]
        m = local(i)
        out[i] = (walk(parent[i]) @ m) if i in parent else m
        return out[i]

    for i in range(len(g['nodes'])):
        walk(i)
    return out


# ── BVH ─────────────────────────────────────────────────────────────────────
def bvh_load(path):
    lines = open(path).read().split('\n')
    i, stack, joints, cur = 0, [], [], None
    while i < len(lines):
        w = lines[i].strip().split()
        i += 1
        if not w:
            continue
        if w[0] in ('ROOT', 'JOINT', 'End'):
            name = w[1] if w[0] != 'End' else joints[stack[-1]]['name'] + '_End'
            joints.append(
                {'name': name, 'offset': None, 'ch': [], 'parent': stack[-1] if stack else None, 'children': []}
            )
            if joints[-1]['parent'] is not None:
                joints[joints[-1]['parent']]['children'].append(len(joints) - 1)
            cur = len(joints) - 1
        elif w[0] == 'OFFSET':
            joints[cur]['offset'] = np.array([float(x) for x in w[1:4]])
        elif w[0] == 'CHANNELS':
            joints[cur]['ch'] = w[2:]
        elif w[0] == '{':
            stack.append(cur)
        elif w[0] == '}':
            stack.pop()
            cur = stack[-1] if stack else None
        elif w[0] == 'MOTION':
            break
    frames = int(lines[i].split()[-1])
    rows = [[float(x) for x in ln.split()] for ln in lines[i + 2 : i + 2 + frames] if ln.strip()]
    return joints, np.array(rows)


def _axis(name, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    if name == 'X':
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if name == 'Y':
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def bvh_world(joints, frame):
    chan, ptr = {}, 0
    for i, j in enumerate(joints):
        chan[i] = frame[ptr : ptr + len(j['ch'])]
        ptr += len(j['ch'])
    out = {}

    def walk(i):
        j = joints[i]
        rot, pos = np.eye(3), np.zeros(3)
        for name, value in zip(j['ch'], chan[i]):
            if name.endswith('rotation'):
                rot = rot @ _axis(name[0], value)
            elif name == 'Xposition':
                pos[0] = value
            elif name == 'Yposition':
                pos[1] = value
            elif name == 'Zposition':
                pos[2] = value
        m = np.eye(4)
        if j['parent'] is None:
            m[:3, :3], m[:3, 3] = rot, j['offset'] + pos
        else:
            p = out[j['parent']]
            m[:3, :3] = p[:3, :3] @ rot
            m[:3, 3] = p[:3, 3] + p[:3, :3] @ (j['offset'] + pos)
        out[i] = m
        for c in j['children']:
            walk(c)

    walk(0)
    return {joints[k]['name']: v for k, v in out.items()}


# ── the measurements ────────────────────────────────────────────────────────
def pelvis_toe_out(lat, foot, side):
    """A foot's progression angle in the PELVIS's frame, in degrees out.

    Against the pelvis, not against the direction of travel: a capture clip's
    subject can fight on the spot, and then a travel azimuth is noise. Handed
    without deciding a handedness -- the angle to the hip-to-hip axis is 90 deg
    for a foot pointing straight ahead, and which way it leaves 90 says which
    way the toe turns.
    """
    a, b = np.array([lat[0], 0.0, lat[2]]), np.array([foot[0], 0.0, foot[2]])
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-9 or nb < 1e-9:
        return float('nan')
    ang = math.degrees(math.acos(max(-1.0, min(1.0, float(a @ b) / (na * nb)))))
    return (90.0 - ang) if side == 'L' else (ang - 90.0)


def foot_vector(pos, keep):
    """A foot's own long axis as a heel->toe vector, iterated off its vertices."""
    a = np.array([0.0, 1.0])
    d = np.array([0.0, 0.0, 1.0])
    for _ in range(6):
        q = pos[keep][:, [0, 2]] - pos[keep][:, [0, 2]].mean(0)
        t = q @ a
        lo = pos[keep][t <= np.percentile(t, 10)].mean(0)
        hi = pos[keep][t >= np.percentile(t, 90)].mean(0)
        d = hi - lo
        a = np.array([d[0], d[2]])
        a /= np.linalg.norm(a)
    return d


def hip_axis(world, key):
    """The hip-to-hip vector, from whatever names this skeleton uses."""
    return world[key('LeftUpLeg')][:3, 3] - world[key('RightUpLeg')][:3, 3]


FLAT_FRAC = 0.85  # of its resting horizontal length = flat enough to read
LOW_FRAC = 0.40  # the lowest this fraction of frames is the stance


def _stance_mean(rows, flat0):
    """The mean progression angle over the flat, low frames of one foot."""
    flat = [r for r in rows if r[1] >= FLAT_FRAC * flat0]
    if not flat:
        return float('nan')
    cut = np.percentile([r[0] for r in flat], 100.0 * LOW_FRAC)
    low = [r[2] for r in flat if r[0] <= cut]
    return float(np.mean(low)) if low else float('nan')


def main(argv):
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
    sys.exit(main(sys.argv[1:]))
