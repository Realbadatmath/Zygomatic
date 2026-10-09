# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""vfx_probes.py — linear probes on frozen DINOv2 features.

A probe is one matrix. It maps the 768-float embedding of a frame to a small set
of classes, and each class is bound to a taxonomy entry. Training is a logistic
regression that fits in well under a second; the artefact is ~74 KB.

The whole point is that the BACKBONE is shared and frozen, so adding the
hundredth observable costs a matrix and no extra inference. See vfx_embed.

THE SHIPPING RULE
-----------------
A probe does not ship because it scored well. It ships because it beat TWO nulls
by a stated margin:

    majority null   always predict the most common test class
    shuffled null   the same probe, same features, labels shuffled before fitting

The second is the important one. It answers "could this score have come from the
features carrying nothing at all", which a train/test split alone cannot. A probe
that fails either is still SAVED — with shippable=false and its numbers on the
record — because a measured failure is information and a silent one is not. This
is the same discipline the detector thresholds get, for the same reason: a fit
metric means nothing without its null.

THE SPLIT RULE
--------------
Splits are BY GROUP, never by row. On character renders the group is the
character, so a probe cannot pass by memorising a face — the test characters are
never seen in training. Training refuses to run if a group appears on both sides.

THE ABSTENTION RULE (added after it bit)
----------------------------------------
A linear probe CANNOT abstain on its own. Softmax always sums to 1, so a frame
from a distribution the probe never saw still gets a confident label — it is
forced to. Measured here: a probe at 100% on held-out character sheets called a
frontal portrait clip "back_to_camera" at 0.86 confidence, on every frame.

So every probe stores a reference sample of its training features and gates on
k-NN cosine distance to them. Measured separation on this project:

    held-out sheets (in-distribution)   median distance 0.033
    an unrelated clip (out)             median distance 0.618
    gate at the in-distribution p99  ->  1.0% false alarms, 100% caught

An out-of-distribution frame yields NO event, and a run that is wholly
out-of-distribution reports UNMEASURABLE with the distance on the record. This
is the same principle as the rest of the analyzer: a detector that cannot see
must say so rather than produce its most likely guess.

WHAT A PROBE CANNOT DO
----------------------
It reads the CLS token, which summarises the whole image, so it answers WHAT and
never WHERE. It sees one frame, so a temporal observable needs a probe over a
window of embeddings, not this. And it is closed-set: it cannot name something
that was never defined. Those are the VLM's and the curiosity channel's jobs.
"""

import json
import os
import re
import time

import numpy as np
import logging as _zyg_logging
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


ROOT = paths.ZYG_VFX_ROOT
PROBE_DIR = os.path.join(ROOT, 'probes')
LABEL_DIR = os.path.join(ROOT, 'labels')

# A probe must beat the BETTER of its two nulls by this much to ship.
SHIP_MARGIN = float(os.environ.get('ZYG_VFX_PROBE_MARGIN', 0.08))
# Per-frame confidence floor. Below it the probe declines to answer rather than
# guessing — the prediction is dropped, not downgraded.
DEFAULT_CONF = float(os.environ.get('ZYG_VFX_PROBE_CONF', 0.60))
# Reference rows kept per probe for the out-of-distribution gate, and the k in
# the k-NN distance. 512 x 768 float16 is ~786 KB — cheap next to being wrong.
OOD_REF_N = int(os.environ.get('ZYG_VFX_PROBE_OOD_REF', 512))
OOD_K = int(os.environ.get('ZYG_VFX_PROBE_OOD_K', 5))
# Fraction of a run's frames that may be OOD before the probe declines entirely.
OOD_RUN_FRAC = float(os.environ.get('ZYG_VFX_PROBE_OOD_RUN_FRAC', 0.60))
_ID_RE = re.compile(r'^[a-z0-9_]{2,48}$')


def _dirs():
    for d in (PROBE_DIR, LABEL_DIR):
        os.makedirs(d, exist_ok=True)


def _read_json(p, default=None):
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, p)


# ── label harvesters ─────────────────────────────────────────────────────────
# A harvester turns files this project ALREADY wrote into (path, group, class).
# No annotation: the pipeline recorded the parameter when it made the render, so
# the label is free and exactly as correct as the generator was.

CHARS_ROOT = paths.ZYG_STORYTELLER_CHARS
_SHEET_RE = re.compile(r'^([a-z]+)[a-z_]*_(\d+)_(\d+)deg\.png$')

# The sheet's degree is the SUBJECT's yaw on a turntable, not the camera's
# height. Binding it to camera.angle_high/low would be a straight overclaim, so
# it binds to the three facing entries the taxonomy actually has.
_YAW_CLASSES = {
    'frontal': 'camera.angle_face_yaw_frontal',
    'profile': 'camera.angle_face_profile',
    'away': 'camera.angle_back_to_camera',
}
_SHOT_CLASSES = {
    'face': 'camera.shot_size_close_up',
    'portrait': 'camera.shot_size_medium_close',
    'full': 'camera.shot_size_full_figure',
    'wide': 'camera.shot_size_wide',
}


def _yaw_class(deg):
    d = deg % 360
    if d <= 45 or d >= 315:
        return 'frontal'
    if 135 <= d <= 225:
        return 'away'
    return 'profile'


def harvest_character_sheets(axis='yaw', limit=0):
    """Free labels from the 48-angle character sheets.

    Filenames look like `full_06_090deg.png` — shot prefix, index, subject yaw.
    The group is the character id, so the split can hold whole characters out."""
    import glob

    out = []
    for p in glob.glob(os.path.join(CHARS_ROOT, '*', '*deg.png')):
        m = _SHEET_RE.match(os.path.basename(p))
        if not m:
            continue
        shot, _idx, deg = m.group(1), m.group(2), int(m.group(3))
        char = os.path.basename(os.path.dirname(p))
        cls = _yaw_class(deg) if axis == 'yaw' else shot
        if axis == 'shot' and cls not in _SHOT_CLASSES:
            continue
        out.append({'path': p, 'group': char, 'class': cls})
    out.sort(key=lambda r: r['path'])
    if limit:
        rng = np.random.default_rng(0)
        idx = rng.permutation(len(out))[:limit]
        out = [out[i] for i in sorted(idx)]
    return out


HARVESTERS = {
    'character_sheet_yaw': {
        'fn': lambda limit=0: harvest_character_sheets('yaw', limit),
        'classes': _YAW_CLASSES,
        'label': 'Subject facing, from the 48-angle character sheets',
        'source': 'filename: <char>/<shot>_<idx>_<deg>deg.png, yaw binned to frontal/profile/away',
    },
    'character_sheet_shot': {
        'fn': lambda limit=0: harvest_character_sheets('shot', limit),
        'classes': _SHOT_CLASSES,
        'label': 'Shot size, from the character-sheet render prefixes',
        'source': 'filename prefix: face / portrait / full / wide',
    },
}


def hand_labels(probe_id):
    """Frames a human labelled in the Analyzer, as (run_id, frame) references."""
    rows = []
    p = os.path.join(LABEL_DIR, f'{probe_id}.jsonl')
    try:
        with open(p, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError as _exc:
                        _zyg_log.debug('malformed label line ignored: %s', _exc)
    except OSError:
        return []
    # last label for a given frame wins, so re-labelling corrects rather than duplicates
    latest = {}
    for r in rows:
        latest[(r.get('run_id'), r.get('frame'))] = r
    return list(latest.values())


def add_label(probe_id, run_id, frame, cls, by='ui'):
    _dirs()
    if not _ID_RE.match(str(probe_id)):
        return {'error': 'bad probe id'}
    rec = {
        'run_id': run_id,
        'frame': int(frame),
        'class': str(cls)[:64],
        'by': by,
        'ts': time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    with open(os.path.join(LABEL_DIR, f'{probe_id}.jsonl'), 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec) + '\n')
    return {'ok': True, 'label': rec}


# ── registry ─────────────────────────────────────────────────────────────────


def list_probes():
    _dirs()
    out = []
    for fn in sorted(os.listdir(PROBE_DIR)):
        if not fn.endswith('.json'):
            continue
        rec = _read_json(os.path.join(PROBE_DIR, fn))
        if rec:
            out.append(rec)
    return out


def get_probe(pid):
    if not _ID_RE.match(str(pid or '')):
        return None
    return _read_json(os.path.join(PROBE_DIR, f'{pid}.json'))


def delete_probe(pid):
    if not _ID_RE.match(str(pid or '')):
        return {'error': 'bad probe id'}
    for ext in ('.json', '.npz'):
        try:
            os.unlink(os.path.join(PROBE_DIR, f'{pid}{ext}'))
        except OSError as _exc:
            _zyg_log.debug('probe file removal skipped: %s', _exc)
    return {'ok': True, 'id': pid}


def _load_weights(pid):
    p = os.path.join(PROBE_DIR, f'{pid}.npz')
    if not os.path.isfile(p):
        return None
    z = np.load(p, allow_pickle=True)
    out = {'coef': z['coef'], 'intercept': z['intercept'], 'classes': [str(c) for c in z['classes']]}
    out['ref'] = z['ref'].astype(np.float32) if 'ref' in z.files else None
    return out


def _unit(X):
    n = np.linalg.norm(X, axis=1, keepdims=True)
    return X / np.maximum(n, 1e-8)


def _stratified_ref_idx(groups, n, seed=0):
    """Reference-row indices, spread EVENLY across training groups rather than
    sampled uniformly by row. A minority domain (a handful of footage runs) can
    be a small fraction of total ROWS while still being a distinct region of
    embedding space; row-uniform sampling gives it a proportional handful of the
    512 reference slots, which is not enough to cover its own internal variety.
    Measured: with sheets:footage rows at roughly 70:1, row-uniform sampling put
    only ~1% of the reference set on the footage domain, so its own labelled
    frames still measured ~0.5 cosine distance from the nearest reference row —
    OOD by construction, regardless of how well the classifier itself learned it."""
    rng = np.random.default_rng(seed)
    uniq = sorted(set(groups))
    per = max(1, n // max(1, len(uniq)))
    rows, seen = [], set()
    for g in uniq:
        idx = np.where(groups == g)[0]
        take = min(per, len(idx))
        for i in rng.choice(idx, size=take, replace=False):
            if i not in seen:
                seen.add(i)
                rows.append(i)
    if len(rows) < n:
        remaining = np.array([i for i in range(len(groups)) if i not in seen])
        if len(remaining):
            extra = rng.choice(remaining, size=min(n - len(rows), len(remaining)), replace=False)
            rows.extend(int(i) for i in extra)
    elif len(rows) > n:
        rows = list(rng.choice(rows, size=n, replace=False))
    return np.array(sorted(rows))


def _knn_dist(X, ref, k=OOD_K):
    """Cosine distance from each row to the mean of its k nearest reference rows.
    Low = the probe has seen frames like this; high = it is being asked to
    extrapolate, and its confidence means nothing."""
    if ref is None or len(ref) == 0 or X.size == 0:
        return None
    S = _unit(X) @ _unit(ref).T
    k = int(min(k, S.shape[1]))
    return 1.0 - np.sort(S, axis=1)[:, -k:].mean(axis=1)


# ── training ─────────────────────────────────────────────────────────────────


def train(
    probe_id,
    rows,
    class_taxonomy,
    label='',
    source='',
    backbone=None,
    test_frac=0.25,
    conf=DEFAULT_CONF,
    log_fn=None,
    limit=0,
):
    """Fit a probe from rows of {path|(run_id,frame), group, class}.

    Returns the full report — including the nulls and whether it may ship."""
    from zyg_workflows import vfx_embed as VE
    from sklearn.linear_model import LogisticRegression

    log = log_fn or (lambda _m: None)
    _dirs()
    if not _ID_RE.match(str(probe_id)):
        return {'error': 'probe id must be [a-z0-9_]{2,48}'}
    rows = [r for r in rows if r.get('class')]
    if limit and len(rows) > limit:
        rng = np.random.default_rng(0)
        rows = [rows[i] for i in sorted(rng.permutation(len(rows))[:limit])]
    if len(rows) < 30:
        return {'error': f'need at least 30 labelled frames, have {len(rows)}'}
    classes = sorted({r['class'] for r in rows})
    if len(classes) < 2:
        return {'error': f'need at least 2 classes, have {classes}'}

    paths = [_resolve(r) for r in rows]
    missing = [i for i, p in enumerate(paths) if not p]
    if missing:
        log(f'[probe] {len(missing)} row(s) had no resolvable image and were dropped')
        keep = [i for i in range(len(rows)) if paths[i]]
        rows = [rows[i] for i in keep]
        paths = [paths[i] for i in keep]
    if len(rows) < 30:
        return {'error': 'too few resolvable frames after dropping missing images'}

    t0 = time.time()
    log(f'[probe] embedding {len(paths)} frames with {VE.BACKBONE}')
    X, bad = VE.embed_paths(paths, log_fn=log)
    emb_s = time.time() - t0
    y = np.array([r['class'] for r in rows], dtype=object)
    groups = np.array([str(r.get('group') or r.get('run_id') or i) for i, r in enumerate(rows)])

    # split by GROUP: a probe must not pass by memorising an identity.
    # Assignment is a hash of the group NAME, not a permutation of the group
    # LIST — a permutation's size is the group count, so adding one new group
    # changed that count and reshuffled every existing group's train/test side.
    # Measured: retraining after 3 new labelled rows flipped several previously
    # -passing timestamps back to unmeasurable, because their run's group moved
    # from train to test and dropped out of the OOD reference sample. A
    # per-group hash means adding a group can only change THAT group's side.
    gs = sorted(set(groups))

    def _is_test_group(g, seed=0):
        import hashlib

        h = hashlib.sha1(f'{seed}:{g}'.encode('utf-8'), usedforsecurity=False).hexdigest()
        return (int(h[:8], 16) / 0xFFFFFFFF) < test_frac

    test_g = {g for g in gs if _is_test_group(g)}
    if not test_g and gs:
        test_g = {gs[0]}
    te = np.isin(groups, list(test_g))
    tr = ~te
    if tr.sum() < 20 or te.sum() < 10:
        return {'error': f'split too small: {tr.sum()} train / {te.sum()} test across {len(gs)} group(s)'}
    leak = set(groups[tr]) & set(groups[te])
    if leak:
        return {'error': f'split leaks groups across train/test: {sorted(leak)[:5]}'}
    if len(set(y[tr])) < 2:
        return {'error': 'training split has only one class'}

    t1 = time.time()
    clf = LogisticRegression(max_iter=3000, C=1.0).fit(X[tr], y[tr])
    fit_s = time.time() - t1
    acc = float(clf.score(X[te], y[te]))

    from collections import Counter

    maj = Counter(y[te]).most_common(1)[0][1] / float(te.sum())
    sh = y[tr].copy()
    np.random.default_rng(0).shuffle(sh)
    nul = float(LogisticRegression(max_iter=3000, C=1.0).fit(X[tr], sh).score(X[te], y[te]))

    worst_null = max(maj, nul)
    margin = acc - worst_null
    shippable = bool(margin >= SHIP_MARGIN and acc > 0.5)

    per_class = {}
    pred = clf.predict(X[te])
    for c in classes:
        m = y[te] == c
        per_class[c] = {'n': int(m.sum()), 'recall': float((pred[m] == c).mean()) if m.sum() else None}

    # Out-of-distribution gate. The reference set is a subsample of the TRAINING
    # rows; the threshold is calibrated on the HELD-OUT rows, which are known to
    # be in-distribution, so the false-alarm rate is a measured quantity and not
    # a guess.
    ridx = _stratified_ref_idx(groups[tr], OOD_REF_N)
    ref = _unit(X[tr][ridx]).astype(np.float16)
    d_ho = _knn_dist(X[te], ref.astype(np.float32))
    ood_thr = float(np.percentile(d_ho, 99)) if d_ho is not None else None
    ood_fa = float((d_ho > ood_thr).mean()) if d_ho is not None else None

    np.savez(
        os.path.join(PROBE_DIR, f'{probe_id}.npz'),
        coef=clf.coef_,
        intercept=clf.intercept_,
        classes=np.array(list(clf.classes_), dtype=object),
        ref=ref,
    )
    rec = {
        'id': probe_id,
        'label': label or probe_id,
        'backbone': backbone or VE.BACKBONE,
        'dim': int(X.shape[1]),
        'classes': [str(c) for c in clf.classes_],
        'class_taxonomy': dict(class_taxonomy or {}),
        'label_source': source,
        'split': 'by_group (held-out groups)',
        'n_total': int(len(rows)),
        'n_train': int(tr.sum()),
        'n_test': int(te.sum()),
        'n_groups': len(gs),
        'n_groups_held_out': len(test_g),
        'held_out_groups': sorted(test_g)[:40],
        'accuracy': round(acc, 4),
        'majority_null': round(float(maj), 4),
        'shuffled_null': round(nul, 4),
        'margin_over_worst_null': round(float(margin), 4),
        'ship_margin_required': SHIP_MARGIN,
        'shippable': shippable,
        'per_class': per_class,
        'confidence_floor': float(conf),
        'ood_threshold': None if ood_thr is None else round(ood_thr, 5),
        'ood_ref_rows': int(len(ref)),
        'ood_k': OOD_K,
        'ood_false_alarm_on_heldout': None if ood_fa is None else round(ood_fa, 4),
        'ood_note': (
            'k-NN cosine distance to a sample of the training features; a frame '
            'beyond the threshold yields no event, because a linear probe cannot '
            'abstain on its own — softmax forces a confident label on anything'
        ),
        'embed_seconds': round(emb_s, 2),
        'fit_seconds': round(fit_s, 2),
        'trained': time.strftime('%Y-%m-%d %H:%M:%S'),
        'unreadable_frames': len(bad),
    }
    if not shippable:
        rec['why_not_shippable'] = (
            f'accuracy {acc:.3f} does not beat its worst null {worst_null:.3f} by the '
            f'required {SHIP_MARGIN:.2f} margin — kept on the record, not used in runs'
        )
    _write_json(os.path.join(PROBE_DIR, f'{probe_id}.json'), rec)
    log(
        f'[probe] {probe_id}: acc={acc:.3f} maj-null={maj:.3f} shuf-null={nul:.3f} '
        f'-> {"SHIPPABLE" if shippable else "NOT shippable"}'
    )
    return rec


def _resolve(row):
    """Row -> an image path on disk. Accepts a direct path, or a run frame."""
    p = row.get('path')
    if p and os.path.isfile(p):
        return p
    if row.get('run_id') is not None and row.get('frame') is not None:
        try:
            from zyg_workflows import vfx_analyzer as VA

            return VA.frame_image_path(row['run_id'], int(row['frame']) + 1)
        except Exception:  # noqa: BLE001
            return None
    return None


# ── inference ────────────────────────────────────────────────────────────────


def predict(pid, X):
    """(N, dim) features -> per-row (class, confidence). Softmax over the linear
    scores; multinomial for >2 classes, logistic for binary."""
    w = _load_weights(pid)
    if w is None or X.size == 0:
        return None
    z = X @ w['coef'].T + w['intercept']
    if z.shape[1] == 1:  # binary: sklearn keeps one column
        p1 = 1.0 / (1.0 + np.exp(-z[:, 0]))
        P = np.stack([1.0 - p1, p1], axis=1)
    else:
        e = np.exp(z - z.max(axis=1, keepdims=True))
        P = e / e.sum(axis=1, keepdims=True)
    idx = P.argmax(axis=1)
    d = _knn_dist(X, w.get('ref'))
    rec = get_probe(pid) or {}
    thr = rec.get('ood_threshold')
    out = []
    for r, i in enumerate(idx):
        dist = float(d[r]) if d is not None else None
        ood = bool(thr is not None and dist is not None and dist > float(thr))
        out.append(
            {
                'class': w['classes'][i],
                'confidence': float(P[r, i]),
                'ood_distance': None if dist is None else round(dist, 5),
                'ood': ood,
            }
        )
    return out


def probe_results(ctx, features):
    """Run every SHIPPABLE probe over a run's cached features and return Results
    in the same shape vfx_detectors emits, so the ledger treats them uniformly.

    A frame whose top class sits below the confidence floor produces no event.
    The Result still carries the best confidence seen, which is the calibration
    handle — exactly as for the hand-written detectors."""
    out = []
    if features is None or len(features) == 0:
        for rec in list_probes():
            for tid in (rec.get('class_taxonomy') or {}).values():
                out.append(
                    {
                        'id': tid,
                        'state': 'unmeasurable',
                        'events': [],
                        'best': None,
                        'threshold': rec.get('confidence_floor'),
                        'unit': 'probe confidence',
                        'reason': 'no frame embeddings for this run — the embedding '
                        'stage was skipped or the backbone was unavailable',
                        'from_probe': rec['id'],
                    }
                )
        return out
    for rec in list_probes():
        tax = rec.get('class_taxonomy') or {}
        if not rec.get('shippable'):
            for tid in tax.values():
                out.append(
                    {
                        'id': tid,
                        'state': 'unmeasurable',
                        'events': [],
                        'best': None,
                        'threshold': rec.get('confidence_floor'),
                        'unit': 'probe confidence',
                        'from_probe': rec['id'],
                        'reason': rec.get('why_not_shippable', 'probe did not beat its null models'),
                    }
                )
            continue
        preds = predict(rec['id'], features)
        if preds is None:
            continue
        conf_floor = float(rec.get('confidence_floor', DEFAULT_CONF))
        n_ood = sum(1 for pr in preds if pr.get('ood'))
        ood_frac = n_ood / float(max(1, len(preds)))
        dists = [pr['ood_distance'] for pr in preds if pr.get('ood_distance') is not None]
        if ood_frac >= OOD_RUN_FRAC:
            # The probe is being asked about content unlike anything it trained
            # on. Its labels would be confident and meaningless.
            for tid in tax.values():
                out.append(
                    {
                        'id': tid,
                        'state': 'unmeasurable',
                        'events': [],
                        'best': None,
                        'threshold': conf_floor,
                        'unit': 'probe confidence',
                        'from_probe': rec['id'],
                        'reason': (
                            f"{ood_frac:.0%} of frames are outside this probe's "
                            f'training distribution (median k-NN distance '
                            f'{float(np.median(dists)):.3f} vs gate '
                            f'{rec.get("ood_threshold")}); the probe was trained on '
                            f'{rec.get("label_source", "?")} and cannot speak to this '
                            f'footage. Label frames from THIS content and retrain.'
                        ),
                    }
                )
            continue
        by_class = {c: [] for c in rec['classes']}
        best = {c: 0.0 for c in rec['classes']}
        for i, pr in enumerate(preds):
            cls, p = pr['class'], pr['confidence']
            if pr.get('ood'):
                continue  # outside the manifold: no vote at all
            if cls in best:
                best[cls] = max(best[cls], p)
            if p >= conf_floor and cls in by_class:
                by_class[cls].append((i, p))
        for cls, tid in tax.items():
            hits = by_class.get(cls, [])
            evs = [
                {
                    'id': tid,
                    'frame': int(i),
                    't_s': ctx.t_of(i),
                    'confidence': round(p, 4),
                    'evidence': {
                        'probe': rec['id'],
                        'class': cls,
                        'probe_accuracy': rec.get('accuracy'),
                        'ood_distance': next((pr['ood_distance'] for k, pr in enumerate(preds) if k == i), None),
                        'probe_worst_null': max(rec.get('majority_null') or 0, rec.get('shuffled_null') or 0),
                        'backbone': rec.get('backbone'),
                    },
                }
                for i, p in hits
            ]
            out.append(
                {
                    'id': tid,
                    'state': 'ok',
                    'events': evs,
                    'best': round(best.get(cls, 0.0), 4),
                    'threshold': conf_floor,
                    'unit': 'probe confidence',
                    'from_probe': rec['id'],
                    'ood_frames': n_ood,
                    'ood_fraction': round(ood_frac, 4),
                    'note': (
                        f'linear probe on frozen {rec.get("backbone")}; '
                        f'held-out accuracy {rec.get("accuracy")} vs worst null '
                        f'{max(rec.get("majority_null") or 0, rec.get("shuffled_null") or 0)} '
                        f'({rec.get("n_train")} train / {rec.get("n_test")} test, '
                        f'split {rec.get("split")})'
                    ),
                }
            )
    return out


def capability():
    from zyg_workflows import vfx_embed as VE

    probes = list_probes()
    return {
        'backbone': VE.available(),
        'probes': len(probes),
        'shippable': sum(1 for p in probes if p.get('shippable')),
        'harvesters': sorted(HARVESTERS),
        'ship_margin': SHIP_MARGIN,
    }


# ── background training ──────────────────────────────────────────────────────
# Training embeds a few thousand frames, so it must not block the HTTP thread.
# Same shape as the analyzer's run jobs: a dict, a lock, a daemon thread.
import threading  # noqa: E402

_TJOBS = {}
_TLOCK = threading.Lock()


def training_jobs():
    with _TLOCK:
        return [dict(j) for j in sorted(_TJOBS.values(), key=lambda j: -j.get('started_ts', 0))]


def training_job(jid):
    with _TLOCK:
        j = _TJOBS.get(str(jid))
        return dict(j) if j else None


def start_training(probe_id, spec):
    """spec: {harvester?, label_source 'harvester'|'hand', classes?, class_taxonomy?,
    label?, limit?, confidence?}"""
    _dirs()
    if not _ID_RE.match(str(probe_id or '')):
        return {'error': 'probe id must be [a-z0-9_]{2,48}'}
    jid = f'{probe_id}_{int(time.time())}'
    with _TLOCK:
        _TJOBS[jid] = {
            'id': jid,
            'probe': probe_id,
            'state': 'queued',
            'log': [],
            'started': time.strftime('%Y-%m-%d %H:%M:%S'),
            'started_ts': time.time(),
            'result': None,
            'error': '',
        }
        for k in [k for k in sorted(_TJOBS, key=lambda k: _TJOBS[k]['started_ts'])[:-12]]:
            if _TJOBS[k]['state'] in ('done', 'error'):
                _TJOBS.pop(k, None)

    def _log(m):
        with _TLOCK:
            j = _TJOBS.get(jid)
            if j:
                j['log'].append(f'[{time.strftime("%H:%M:%S")}] {m}')
                del j['log'][:-200]
        _zyg_log.info(f'[VFX-PROBE] {m}')

    def _work():
        try:
            with _TLOCK:
                _TJOBS[jid]['state'] = 'running'
            src = spec.get('label_source', 'harvester')
            if src == 'harvester':
                h = HARVESTERS.get(spec.get('harvester'))
                if not h:
                    raise ValueError(f'unknown harvester {spec.get("harvester")!r}')
                rows = h['fn']()
                tax = h['classes']
                label = spec.get('label') or h['label']
                source = h['source']
            else:
                rows = hand_labels(probe_id)
                tax = spec.get('class_taxonomy') or {}
                if not tax:
                    raise ValueError('hand-labelled probes need class_taxonomy {class: taxonomy_id}')
                label = spec.get('label') or probe_id
                source = f'hand-labelled in the Analyzer ({len(rows)} frames)'
                for r in rows:
                    r.setdefault('group', r.get('run_id'))
            _log(f'{len(rows)} labelled rows from {src}')
            rec = train(
                probe_id,
                rows,
                tax,
                label=label,
                source=source,
                limit=int(spec.get('limit') or 0),
                conf=float(spec.get('confidence') or DEFAULT_CONF),
                log_fn=_log,
            )
            with _TLOCK:
                _TJOBS[jid].update(
                    state='error' if rec.get('error') else 'done', result=rec, error=rec.get('error', '')
                )
        except Exception as e:  # noqa: BLE001
            import traceback

            _log(f'FAILED: {type(e).__name__}: {e}')
            with _TLOCK:
                _TJOBS[jid].update(
                    state='error',
                    error=f'{type(e).__name__}: {e}',
                    result={'traceback': traceback.format_exc().split('\n')[-12:]},
                )

    threading.Thread(target=_work, daemon=True).start()
    return {'ok': True, 'job': jid}
