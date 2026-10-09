# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The stages of a scan run, hoisted out of `scan._worker`.

`_worker` was a 340-line function whose every phase shared ~20 implicit locals; none of
it could be exercised without ffmpeg, a video and a GPU. The locals are now the fields of
one `ScanRun`, each phase is a module-level stage that reads and fills it, and the
line-building arithmetic (the capability line, the frame-count note, the cadence lines,
the landmark coverage, the ledger summary, the initial and the failed report) is a set of
pure functions with no I/O at all.

Import direction: this module imports `scan` at module level for the primitives that stay
there (`_job_set`, `job`, `_extract`, `_segment_shots`, `_thin_landmarks`, `_build_ledger`
— every one of them re-exported by name from `vfx_analyzer/__init__.py`), and `scan`
defers `from . import scan_stages` into `_worker` itself. Acyclic in both directions, and
reaching the primitives through the module object keeps them monkeypatchable.
"""

import dataclasses
import json
import os
import time
import traceback

import numpy as np
from zyg_workflows.vfx_analyzer import _zyg_log
from zyg_workflows.vfx_analyzer import scan as _scan
from zyg_workflows.vfx_analyzer.capability import capability
from zyg_workflows.vfx_analyzer.constants import _write_json


@dataclasses.dataclass
class ScanRun:
    """Everything one scan run carries from stage to stage — the former locals of `_worker`.

    The first eleven fields are the request (ids, paths, config, the report being built,
    and the two callables the job board owns: `log` and `cancelled`); the rest are filled
    in by the stages, in the order the stages run, and read by the ones downstream.
    """

    jid: str
    rid: str
    media_id: str
    src: str
    meta: dict
    cfg: dict
    rdir: str
    fdir: str
    report: dict
    t_start: float
    log: object
    cancelled: object
    cv2: object = None
    vm: object = None
    vd: object = None
    names: list = dataclasses.field(default_factory=list)
    n: int = 0
    fps: float = 0.0
    per_frame: list = dataclasses.field(default_factory=list)
    hashes: list = dataclasses.field(default_factory=list)
    imgs_small: list = dataclasses.field(default_factory=list)
    cad: dict = dataclasses.field(default_factory=dict)
    uidx: list = dataclasses.field(default_factory=list)
    pair_by_frame: dict = dataclasses.field(default_factory=dict)
    shots: list = dataclasses.field(default_factory=list)
    lm_seq: list = dataclasses.field(default_factory=list)
    vels: list = dataclasses.field(default_factory=list)
    features: object = None
    ctx: object = None
    results: list = dataclasses.field(default_factory=list)
    unk: list = dataclasses.field(default_factory=list)


# ── the pure line builders ───────────────────────────────────────────────────


def _initial_report(rid, media_id, meta, cfg):
    """The report dict as it stands before the first stage: ids, config, probe, window."""
    return {
        'run_id': rid,
        'media_id': media_id,
        'media_name': meta.get('name', ''),
        'started': time.strftime('%Y-%m-%d %H:%M:%S'),
        'state': 'running',
        'config': cfg,
        'probe': meta.get('probe', {}),
        'error': '',
        'stages': [],
        'window': {'start_s': cfg['start_s'], 'duration_s': cfg['duration_s']},
    }


def _record_stage(report, name, ok, secs, note=''):
    """Append one stage row to `report['stages']` — the former `stage()` closure."""
    report['stages'].append({'name': name, 'ok': bool(ok), 'seconds': round(secs, 2), 'note': note})


def _capability_line(cap):
    """The one-line summary of what this box can do, for the run log."""
    return (
        f'capability: landmarks={ {k: v.get("ok") for k, v in (cap.get("landmarks") or {}).items() if isinstance(v, dict)} } '
        f'vlm={cap["vlm"].get("ok")} detectors={cap.get("detectors", {}).get("count", 0)} '
        f'taxonomy={cap.get("taxonomy", {}).get("count", 0)}'
    )


def _frame_count_note(n, duration_s, fps):
    """The NOTE line when the extracted count misses the expected one, else ''.

    Tolerance is 5 % of the expectation or two frames, whichever is larger: a short tail
    at the end of the file and a VFR source both land here, and neither is an error.
    """
    expected = int(round(duration_s * fps))
    if abs(n - expected) > max(2, 0.05 * expected):
        return (
            f'NOTE: extracted {n} frames, expected ~{expected} at {fps:.3f} fps '
            f'— window may be clipped by the file end, or the source is VFR'
        )
    return ''


def _cadence_lines(cad, n):
    """The cadence log lines: the map itself, plus the unique-cel warning on 2s/3s."""
    lines = [
        f'cadence: {cad["cadence"]}  unique cels {len(cad["unique_idx"])}/{n} '
        f'(ratio {cad["unique_ratio"]:.3f}, mean hold {cad["mean_hold"]:.2f}) '
        f'holds={cad["hold_hist"]}'
    ]
    if cad['cadence'] in ('twos', 'threes'):
        lines.append(
            f'  -> temporal metrics will be taken between UNIQUE cels only; '
            f'a per-frame reading here would be {1 - cad["unique_ratio"]:.0%} structural zeros'
        )
    return lines


def _landmark_coverage(lm_seq, n):
    """How many frames resolved a pose, a face and a hand, out of `n`."""
    return {
        'pose_frames': sum(1 for f in lm_seq if (f.get('pose') or {}).get('state') == 'found'),
        'face_frames': sum(1 for f in lm_seq if (f.get('face') or {}).get('state') == 'found'),
        'hand_frames': sum(1 for f in lm_seq if (f.get('hand') or {}).get('state') == 'found'),
        'total_frames': n,
    }


def _ledger_lines(ledger, unk, seconds):
    """The closing LEDGER block of the run log, one line per state."""
    return [
        '',
        '=== LEDGER ===',
        f'  FOUND          {len(ledger["found"]):4d}   detector fired',
        f'  NOT FOUND      {len(ledger["not_found"]):4d}   detector ran, evidence below threshold',
        f'  UNMEASURABLE   {len(ledger["unmeasurable"]):4d}   detector could not run on this input',
        f'  NOT DETECTABLE {len(ledger["not_detectable"]):4d}   no detector exists yet (known blind spot)',
        f'  UNKNOWNS       {len(unk):4d}   moving things nothing in the taxonomy claimed',
        f'run finished in {seconds}s',
    ]


def _failed_report(report, exc, tb, t_start):
    """Stamp the error state, the finish time and the last 25 traceback lines in place."""
    report['state'] = 'error'
    report['error'] = f'{type(exc).__name__}: {exc}'
    report['finished'] = time.strftime('%Y-%m-%d %H:%M:%S')
    report['seconds'] = round(time.time() - t_start, 2)
    report['traceback'] = tb.split('\n')[-25:]
    return report


def _new_run(jid, rid, media_id, src, meta, cfg, rdir, log, cancelled):
    """Build the `ScanRun` for one job: the request, the frame dir and a fresh report."""
    return ScanRun(
        jid=jid,
        rid=rid,
        media_id=media_id,
        src=src,
        meta=meta,
        cfg=cfg,
        rdir=rdir,
        fdir=os.path.join(rdir, 'frames'),
        report=_initial_report(rid, media_id, meta, cfg),
        t_start=time.time(),
        log=log,
        cancelled=cancelled,
    )


# ── the stages, in the order _worker runs them ───────────────────────────────


def open_run(run):
    """Mark the job running, print the run header, and record what this box can do."""
    log = run.log
    _scan._job_set(run.jid, state='running', stage='extract')
    log(f'=== VFX ANALYZER RUN {run.rid} ===')
    log(f'media: {run.meta.get("name")}  ({run.meta.get("bytes", 0) / 1e6:.1f} MB)')
    log(f'probe: {json.dumps(run.meta.get("probe", {}))}')
    cap = capability()
    run.report['capability'] = cap
    log(_capability_line(cap))


def extract_frames(run):
    """Stage 1: every frame of the window on disk; fills `names`, `n` and `fps`.

    Raises RuntimeError when ffmpeg failed or produced nothing — the run is over, there is
    nothing to measure. A max_frames cap deletes the surplus jpgs rather than ignoring
    them, so the frame dir and the report agree.
    """
    cfg, log, fdir = run.cfg, run.log, run.fdir
    t0 = time.time()
    names, err = _scan._extract(run.src, fdir, cfg['start_s'], cfg['duration_s'], log)
    if err:
        raise RuntimeError(err)
    if cfg['max_frames'] and len(names) > cfg['max_frames']:
        for extra in names[cfg['max_frames'] :]:
            try:
                os.unlink(os.path.join(fdir, extra))
            except OSError as _exc:
                _zyg_log.debug('capped frame removal skipped: %s', _exc)
        names = names[: cfg['max_frames']]
        log(f'capped to max_frames={cfg["max_frames"]}')
    if not names:
        raise RuntimeError('ffmpeg produced no frames for that window')
    n = len(names)
    fps = float((run.meta.get('probe') or {}).get('fps') or 0) or 24.0
    note = _frame_count_note(n, cfg['duration_s'], fps)
    if note:
        log(note)
    run.report['frames_scanned'] = n
    run.report['fps'] = fps
    run.names, run.n, run.fps = names, n, fps
    _scan._job_set(run.jid, frames_total=n)
    _record_stage(run.report, 'extract', True, time.time() - t0, f'{n} frames @ {fps:.3f} fps')


def measure_frames(run):
    """Stage 2: the per-frame battery, the perceptual hash and the thumbnail, per frame.

    Imports OpenCV and vfx_metrics here, as the original did — the first two tiers of the
    scan are the only hard dependency of a run — and keeps them on the run for the later
    stages. An unreadable frame becomes an `error` row rather than a hole in the sequence,
    because every downstream index is a frame number.
    """
    import cv2
    from zyg_workflows import vfx_metrics as VM

    run.cv2, run.vm = cv2, VM
    cfg, log, names, n, fps, fdir = run.cfg, run.log, run.names, run.n, run.fps, run.fdir
    t0 = time.time()
    _scan._job_set(run.jid, stage='frame metrics')
    log(f'frame metrics: measuring {n} frames, {len(VM.describe()["frame"])} readings each')
    per_frame, hashes, imgs_small = [], [], []
    for i, fn in enumerate(names):
        if run.cancelled():
            raise RuntimeError('cancelled')
        img = cv2.imread(os.path.join(fdir, fn), cv2.IMREAD_COLOR)
        if img is None:
            per_frame.append({'index': i, 'error': 'unreadable'})
            hashes.append(0)
            imgs_small.append(None)
            continue
        m = VM.frame_battery(img)
        m['index'] = i
        m['t_s'] = round(cfg['start_s'] + i / fps, 4)
        m['file'] = fn
        per_frame.append(m)
        hashes.append(VM.phash(img))
        imgs_small.append(VM.thumb(img))
        if i % 10 == 0:
            _scan._job_set(run.jid, frame=i, pct=round(8 + 32 * i / max(1, n), 1))
    run.per_frame, run.hashes, run.imgs_small = per_frame, hashes, imgs_small
    _record_stage(run.report, 'frame_metrics', True, time.time() - t0, f'{n} frames')


def temporal_structure(run):
    """Stages 3-5: the cadence map, the pair metrics between unique cels, and the shots.

    One stage because they are one contract: the cadence map decides which frames are the
    real pictures, pair metrics are only ever taken between consecutive unique cels and
    divided by the REAL elapsed time, and the cut detector reads those pairs.
    """
    cv2, VM, log, n, fps = run.cv2, run.vm, run.log, run.n, run.fps
    report, names, fdir = run.report, run.names, run.fdir

    t0 = time.time()
    _scan._job_set(run.jid, stage='cadence')
    cad = VM.cadence_map(run.hashes, thumbs=run.imgs_small)
    report['cadence'] = cad['cadence']
    report['unique_cels'] = len(cad['unique_idx'])
    report['cadence_detail'] = {k: cad[k] for k in ('cadence', 'unique_ratio', 'mean_hold', 'hold_hist')}
    for line in _cadence_lines(cad, n):
        log(line)
    _record_stage(report, 'cadence', True, time.time() - t0, cad['cadence'])
    run.cad = cad

    t0 = time.time()
    _scan._job_set(run.jid, stage='pair metrics')
    uidx = cad['unique_idx']
    pair_by_frame = {}
    for k in range(1, len(uidx)):
        if run.cancelled():
            raise RuntimeError('cancelled')
        a, b = uidx[k - 1], uidx[k]
        ia = cv2.imread(os.path.join(fdir, names[a]), cv2.IMREAD_COLOR)
        ib = cv2.imread(os.path.join(fdir, names[b]), cv2.IMREAD_COLOR)
        if ia is None or ib is None:
            continue
        pm = VM.pair_battery(ia, ib)
        pm['from_frame'] = a
        pm['to_frame'] = b
        pm['dt_s'] = round((b - a) / fps, 5)
        pair_by_frame[b] = pm
        if k % 8 == 0:
            _scan._job_set(run.jid, pct=round(40 + 18 * k / max(1, len(uidx)), 1))
    log(f'pair metrics: {len(pair_by_frame)} unique-cel pairs ({len(VM.describe()["pair"])} readings each)')
    _record_stage(report, 'pair_metrics', True, time.time() - t0, f'{len(pair_by_frame)} pairs')
    run.uidx, run.pair_by_frame = uidx, pair_by_frame

    t0 = time.time()
    _scan._job_set(run.jid, stage='shots')
    shots = _scan._segment_shots(run.per_frame, pair_by_frame, uidx, fps)
    report['shots'] = shots
    log(
        f'shots: {len(shots)} segment(s) — '
        + ', '.join(f'{s["start"]}-{s["end"]} ({s["frames"]}f)' for s in shots[:8])
        + (' …' if len(shots) > 8 else '')
    )
    _record_stage(report, 'shots', True, time.time() - t0, f'{len(shots)} shots')
    run.shots = shots


def track_landmarks(run):
    """Stage 6: pose, face and hand landmarks per frame, plus their velocities.

    An optional tier: a failure here is recorded in the stage note and the scan goes on
    with empty sequences, because MediaPipe under-detects stylised art and a run that
    died on that would hide every detector that does not need a subject.
    """
    cfg, log, names, n, fps, fdir = run.cfg, run.log, run.names, run.n, run.fps, run.fdir
    lm_seq, vels = [], []
    lm_state = 'skipped'
    t0 = time.time()
    if cfg['do_landmarks']:
        _scan._job_set(run.jid, stage='landmarks')
        try:
            from zyg_workflows import vfx_landmarks as VL

            tr = VL.LandmarkTracker(log_fn=log)
            for i, fn in enumerate(names):
                if run.cancelled():
                    raise RuntimeError('cancelled')
                img = run.cv2.imread(os.path.join(fdir, fn), run.cv2.IMREAD_COLOR)
                if img is None:
                    lm_seq.append({})
                    continue
                lm_seq.append(tr.step(img, int(round(1000 * i / fps))))
                if i % 10 == 0:
                    _scan._job_set(run.jid, frame=i, pct=round(58 + 22 * i / max(1, n), 1))
            tr.close()
            vels = VL.velocities(lm_seq, run.uidx, fps)
            cov = _landmark_coverage(lm_seq, n)
            lm_state = 'ran'
            log(
                f'landmarks: pose on {cov["pose_frames"]}/{n} frames, '
                f'face {cov["face_frames"]}/{n}, hands {cov["hand_frames"]}/{n}'
            )
            if cov['pose_frames'] == 0 and cov['face_frames'] == 0:
                log(
                    '  -> NO subjects resolved. MediaPipe is trained on photographs and '
                    'under-detects stylised art. Every subject-dependent detector below '
                    'reports UNMEASURABLE, which is NOT the same as "did not happen".'
                )
            run.report['landmark_coverage'] = cov
        except Exception as e:  # noqa: BLE001 — tier is optional
            lm_state = f'failed: {type(e).__name__}: {e}'
            log(f'landmarks FAILED: {e}')
    else:
        log('landmarks: disabled for this run')
    _record_stage(run.report, 'landmarks', lm_state in ('ran',), time.time() - t0, lm_state)
    run.lm_seq, run.vels = lm_seq, vels


def embed_frames(run):
    """Stage 6.5: one frozen forward pass per frame, cached for every linear probe.

    This is what makes the marginal cost of the hundredth learned observable ~zero: the
    probes are 74 KB matrices over this one vector. The card is given straight back.
    """
    cfg, log, names, fdir = run.cfg, run.log, run.names, run.fdir
    features = None
    emb_state = 'skipped'
    t0 = time.time()
    if cfg.get('do_probes', True):
        _scan._job_set(run.jid, stage='embeddings', pct=80)
        try:
            from zyg_workflows import vfx_embed as VE

            av = VE.available()
            if not av.get('ok'):
                emb_state = f'unavailable: {av.get("note")}'
                log(f'embeddings: {emb_state}')
            else:
                paths = [os.path.join(fdir, fn) for fn in names]
                features, bad = VE.embed_paths(paths, log_fn=log)
                np.save(os.path.join(run.rdir, 'features.npy'), features)
                emb_state = 'ran'
                log(
                    f'embeddings: {features.shape[0]} x {features.shape[1]} '
                    f'({av["backbone"]} on {av["device"]}) in {time.time() - t0:.1f}s'
                    + (f', {len(bad)} unreadable' if bad else '')
                )
                VE.unload()  # give the card back to the render pipeline
        except Exception as e:  # noqa: BLE001 — tier is optional
            emb_state = f'failed: {type(e).__name__}: {e}'
            log(f'embeddings FAILED: {e}')
    else:
        log('embeddings: disabled for this run')
    _record_stage(run.report, 'embeddings', emb_state == 'ran', time.time() - t0, emb_state)
    run.features = features


def run_detectors(run):
    """Stages 7-8: every registered detector, the probe bindings, then the curiosity pass.

    One stage because all three share the single `VD.Ctx` built here — the frame and pair
    readings, the cadence, the shots, the landmarks and the caller's thresholds — and the
    curiosity pass needs the detector results to know what nothing claimed.
    """
    cfg, log = run.cfg, run.log
    t0 = time.time()
    _scan._job_set(run.jid, stage='detectors', pct=82)
    from zyg_workflows import vfx_detectors as VD

    run.vd = VD
    ctx = VD.Ctx(
        run_dir=run.rdir,
        frame_dir=run.fdir,
        names=run.names,
        fps=run.fps,
        frame_metrics=run.per_frame,
        pair_metrics=run.pair_by_frame,
        unique_idx=run.uidx,
        cadence=run.cad,
        shots=run.shots,
        landmarks=run.lm_seq,
        velocities=run.vels,
        thresholds=cfg['thresholds'],
        log=log,
        start_s=cfg['start_s'],
    )
    results = VD.run_all(ctx)
    n_det = len(results)
    if cfg.get('do_probes', True):
        try:
            from zyg_workflows import vfx_probes as VP

            pres = VP.probe_results(ctx, run.features)
            results.extend(pres)
            fired = sum(1 for r in pres if r.get('events'))
            log(
                f'probes: {len(pres)} taxonomy binding(s) from '
                f'{len({r.get("from_probe") for r in pres})} probe(s), {fired} fired'
            )
        except Exception as e:  # noqa: BLE001
            log(f'probes FAILED: {type(e).__name__}: {e}')
    _record_stage(
        run.report,
        'detectors',
        True,
        time.time() - t0,
        f'{n_det} detectors + {len(results) - n_det} probe binding(s)',
    )
    run.ctx, run.results = ctx, results

    t0 = time.time()
    unk = []
    if cfg['do_curiosity']:
        _scan._job_set(run.jid, stage='curiosity', pct=90)
        unk = VD.curiosity(ctx, results, do_vlm=cfg['do_vlm'])
        log(
            f'curiosity: {len(unk)} unexplained moving region track(s) '
            f'{"identified by VLM" if cfg["do_vlm"] else "logged unidentified (VLM off)"}'
        )
    _record_stage(run.report, 'curiosity', True, time.time() - t0, f'{len(unk)} unknowns')
    run.unk = unk


def write_outputs(run):
    """Stage 9: the three jsonl streams, the ledger, report.json and the closing log."""
    cfg, log, rdir, report = run.cfg, run.log, run.rdir, run.report
    per_frame, pair_by_frame, uidx, lm_seq = run.per_frame, run.pair_by_frame, run.uidx, run.lm_seq
    results, unk, VM = run.results, run.unk, run.vm
    _scan._job_set(run.jid, stage='writing', pct=95)
    with open(os.path.join(rdir, 'frames.jsonl'), 'w', encoding='utf-8') as f:
        for i, m in enumerate(per_frame):
            rec = dict(m)
            pm = pair_by_frame.get(i)
            if pm:
                rec['pair'] = pm
            rec['is_unique_cel'] = i in set(uidx)
            if cfg['do_landmarks'] and i < len(lm_seq):
                rec['landmarks'] = _scan._thin_landmarks(lm_seq[i])
            f.write(json.dumps(rec) + '\n')
    with open(os.path.join(rdir, 'events.jsonl'), 'w', encoding='utf-8') as f:
        for r in results:
            for ev in r.get('events') or []:
                f.write(json.dumps(ev) + '\n')
    with open(os.path.join(rdir, 'unknowns.jsonl'), 'w', encoding='utf-8') as f:
        for u in unk:
            f.write(json.dumps(u) + '\n')

    ledger = _scan._build_ledger(results, log)
    report['ledger'] = ledger
    report['totals'] = {k: len(v) for k, v in ledger.items()}
    report['totals']['events'] = sum(len(r.get('events') or []) for r in results)
    report['totals']['unknowns'] = len(unk)
    report['unknowns'] = unk
    report['metric_dictionary'] = {'frame': VM.describe()['frame'], 'pair': VM.describe()['pair']}
    try:
        from zyg_workflows import vfx_landmarks as VL2

        report['metric_dictionary']['landmark'] = VL2.describe()
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('landmark metric dictionary unavailable, the report ships without it: %s', _exc)
    report['state'] = 'done'
    report['finished'] = time.strftime('%Y-%m-%d %H:%M:%S')
    report['seconds'] = round(time.time() - run.t_start, 2)
    _write_json(os.path.join(rdir, 'report.json'), report)

    for line in _ledger_lines(ledger, unk, report['seconds']):
        log(line)
    _scan._job_set(run.jid, state='done', stage='done', pct=100)


def _record_failure(run, exc):
    """The error path: stamp the report, write what can be written, log the tail, mark the job.

    Called from inside `_worker`'s `except` block, so `traceback.format_exc()` still sees
    the exception being handled.
    """
    tb = traceback.format_exc()
    report = _failed_report(run.report, exc, tb, run.t_start)
    try:
        _write_json(os.path.join(run.rdir, 'report.json'), report)
    except OSError as _exc:
        _zyg_log.warning('report.json not written for the failed run: %s', _exc)
    run.log(f'RUN FAILED: {report["error"]}')
    for ln in tb.strip().split('\n')[-12:]:
        run.log('  ' + ln)
    _scan._job_set(run.jid, state='error', stage='error', error=report['error'])
