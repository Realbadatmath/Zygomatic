# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import atexit
import collections
import json
import os
import queue
import subprocess
import tempfile
import threading

from zyg_workflows.vlm_inspector.base import (
    TIERS,
    _VLM_PY,
    _VLM_WORKER,
    _mklog,
    _norm_answer,
    _quant_for,
    _strict,
    _timeout_for,
)

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.vlm_inspector')


# ── persistent judge (ZYG_VLM_PERSISTENT) ────────────────────────────────────
#
# THE PROBLEM, MEASURED 2026-08-03 on the scene20 v30 "Report + Logbook" stage.
# _run_worker below spawns a fresh subprocess PER QUESTION, and each spawn loads an
# 8B FP8 checkpoint (~10.7 GB) from disk into VRAM, answers one yes/no about one
# crop, and exits. 57 spawns were observed on one run, arriving every 13.5-14.0s —
# metronomically regular whatever the question, which is the signature of fixed
# load cost, not variable inference. ~12 of every 14s was weight loading: about
# 11 minutes of a 13-minute stage, and the reason that stage pins the GPU at 99%
# and a core at ~180%. The `tier=resident` label in the log was a misnomer;
# nothing was resident.
#
# THE FIX: keep the subprocess isolation exactly as it is — the judge still runs in
# models/vlm_judge/.venv so transformers/bitsandbytes never enter the production
# venv, and this process still never creates a CUDA context — but make the
# subprocess LONG-LIVED and feed it newline-delimited JSON requests.
#
# WHICH TIERS, AND WHY NOT ALL OF THEM. Default is resident+cpu only.
#   * 'resident' (8B, ~10.7 GB) is where the waste is: it is called one-question-
#     at-a-time, dozens of times per run.
#   * 'boundary' (32B, ~35.5 GB) is deliberately EXCLUDED. It already batches —
#     a whole checklist goes in a single call ("4f/10q 67.8s") — so persistence
#     buys it almost nothing, while a resident 35.5 GB judge idling between pause
#     points is exactly the thing that would strand the card a render needs.
# Override with ZYG_VLM_PERSISTENT_TIERS if that judgement turns out wrong.
#
# FAIL-SAFE: every failure path here returns None, and _run_worker then falls
# through to the original one-shot code. A broken server must cost time, never
# correctness — so the server is also torn down on first failure rather than
# retried, to avoid a half-dead process answering with stale state.

_PERSIST_DEFAULT_TIERS = 'resident,cpu'
_SERVERS = {}
_SERVERS_LOCK = threading.Lock()


def _persist_enabled(tier):
    if os.environ.get('ZYG_VLM_PERSISTENT', '1') == '0':
        return False
    allowed = os.environ.get('ZYG_VLM_PERSISTENT_TIERS', _PERSIST_DEFAULT_TIERS)
    return tier in {t.strip() for t in allowed.split(',') if t.strip()}


class _JudgeServer:
    """One long-lived `vlm_worker.py --serve` process for a (model, tier) pair."""

    def __init__(self, model_id, tier, log):
        self.model_id = model_id
        self.tier = tier
        self.log = log
        self.p = None
        self.replies = queue.Queue()
        self.errtail = collections.deque(maxlen=200)
        self.ready = None
        self.n = 0
        # One request in flight at a time, per server. The protocol is a single
        # unlabelled request/reply pipe, so two concurrent askers would each take
        # whichever reply arrived first — i.e. silently swap two frames' verdicts.
        # The one-shot path had no such hazard (a process per call), so this lock
        # is what keeps the persistent path as safe as the thing it replaces.
        self.lock = threading.Lock()

    # stderr MUST be drained continuously: the worker logs every question there,
    # and a full 64 KB pipe buffer would block it mid-generation with no diagnosis.
    def _drain_err(self):
        try:
            for line in iter(self.p.stderr.readline, ''):
                self.errtail.append(line.rstrip())
        except Exception as _exc:
            _zyg_log.debug('judge stderr drain ended early: %s', _exc)

    def _read_out(self):
        try:
            for line in iter(self.p.stdout.readline, ''):
                line = line.strip()
                if line.startswith('{'):
                    self.replies.put(line)
        except Exception as _exc:
            _zyg_log.debug('judge stdout read ended early: %s', _exc)
        self.replies.put(None)  # sentinel: worker's stdout closed

    def start(self):
        cfg = TIERS[self.tier]
        idle = os.environ.get('ZYG_VLM_IDLE_TIMEOUT', '180')
        cmd = [
            _VLM_PY,
            _VLM_WORKER,
            '--model-id',
            self.model_id,
            '--serve',
            '--idle-timeout',
            str(idle),
            '--device',
            cfg['device'],
            '--quantization',
            _quant_for(self.tier),
        ]
        env = dict(os.environ)
        if cfg['device'] == 'cpu':
            env['CUDA_VISIBLE_DEVICES'] = ''
        self.p = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, env=env
        )
        threading.Thread(target=self._drain_err, daemon=True).start()
        threading.Thread(target=self._read_out, daemon=True).start()
        try:
            first = self.replies.get(timeout=_timeout_for(self.tier))
        except queue.Empty:
            self.log(f'persistent judge: no ready line in {_timeout_for(self.tier)}s — falling back to one-shot')
            self.stop()
            return False
        if first is None:
            self.log(f'persistent judge: died before ready — {" | ".join(list(self.errtail)[-3:])}')
            self.stop()
            return False
        try:
            self.ready = json.loads(first)
        except Exception:
            self.stop()
            return False
        if not self.ready.get('ok'):
            self.log(f'persistent judge: refused to start ({self.ready.get("error")}) — falling back to one-shot')
            self.stop()
            return False
        self.log(
            f'persistent judge UP: {self.model_id} tier={self.tier} '
            f'pid={self.ready.get("pid")} loaded in '
            f'{self.ready.get("load_s")}s (idle timeout {idle}s)'
        )
        return True

    def ask(self, images, questions_obj, out_path):
        with self.lock:  # see self.lock: reply/request pairing
            if self.p is None or self.p.poll() is not None:
                return None
            req = {'images': [os.path.abspath(p) for p in images], 'questions': questions_obj, 'out': out_path}
            try:
                self.p.stdin.write(json.dumps(req) + '\n')
                self.p.stdin.flush()
            except Exception as e:
                self.log(f'persistent judge: write failed ({e})')
                return None
            try:
                line = self.replies.get(timeout=_timeout_for(self.tier))
            except queue.Empty:
                self.log(f'persistent judge: TIMEOUT after {_timeout_for(self.tier)}s')
                return None
            if line is None:
                self.log(f'persistent judge: process exited mid-request — {" | ".join(list(self.errtail)[-3:])}')
                return None
            try:
                self.n += 1
                return json.loads(line)
            except Exception as e:
                self.log(f'persistent judge: unparseable reply ({e})')
                return None

    def stop(self):
        p, self.p = self.p, None
        if p is None:
            return
        try:
            if p.poll() is None:
                p.stdin.write(json.dumps({'cmd': 'shutdown'}) + '\n')
                p.stdin.flush()
        except Exception as _exc:
            _zyg_log.debug('judge shutdown request not delivered: %s', _exc)
        try:
            p.wait(timeout=20)
        except Exception:
            try:
                p.kill()
            except Exception as _exc:
                _zyg_log.debug('judge process kill skipped: %s', _exc)


def _get_server(model_id, tier, log):
    """Live server for this (model, tier), or None if one cannot be had."""
    key = (model_id, tier, TIERS[tier]['device'], _quant_for(tier))
    with _SERVERS_LOCK:
        s = _SERVERS.get(key)
        if s is not None and s.p is not None and s.p.poll() is None:
            return s
        if s is not None:  # dead or half-dead: clear it out
            s.stop()
            _SERVERS.pop(key, None)
        s = _JudgeServer(model_id, tier, log)
        if not s.start():
            return None
        _SERVERS[key] = s
        return s


def _retire_server(model_id, tier):
    """Kill and forget one server — used after ANY failed request (see _run_worker)."""
    key = (model_id, tier, TIERS[tier]['device'], _quant_for(tier))
    with _SERVERS_LOCK:
        s = _SERVERS.pop(key, None)
    if s is not None:
        try:
            s.stop()
        except Exception as _exc:
            _zyg_log.debug('judge stop skipped: %s', _exc)


def shutdown_workers(log_fn=None):
    """Release every resident judge. Call at the end of a VLM stage.

    Safe to call more than once, and safe to call when persistence was never
    used. Registered with atexit as a backstop, but a stage that is about to
    hand the GPU back to a render should call it EXPLICITLY rather than wait
    for the idle timeout.
    """
    log = _mklog(log_fn)
    with _SERVERS_LOCK:
        keys = list(_SERVERS)
        for k in keys:
            s = _SERVERS.pop(k)
            try:
                n = s.n
                s.stop()
                log(f'persistent judge released: {k[0]} tier={k[1]} after {n} request(s)')
            except Exception as _exc:
                _zyg_log.debug('judge release skipped: %s', _exc)


atexit.register(shutdown_workers)


def _run_worker(model_id, images, questions_obj, tier, log):
    """One worker subprocess call.  Returns the parsed dict, or None on failure."""
    cfg = TIERS[tier]
    tmpdir = tempfile.mkdtemp(prefix='vlmjudge_')
    qpath = os.path.join(tmpdir, 'questions.json')
    vpath = os.path.join(tmpdir, 'verdicts.json')
    try:
        with open(qpath, 'w', encoding='utf-8') as f:
            json.dump(questions_obj, f, ensure_ascii=False)

        nq = len(questions_obj) if isinstance(questions_obj, list) else '?'
        if _persist_enabled(tier):
            srv = _get_server(model_id, tier, log)
            if srv is not None:
                log(
                    f'worker(served #{srv.n + 1}): {model_id} tier={tier} '
                    f'device={cfg["device"]} images={len(images)} questions={nq}'
                )
                res = srv.ask(images, questions_obj, vpath)
                if res is not None and res.get('ok'):
                    return res
                # ANY failure retires this server rather than retrying on it. A
                # timed-out request leaves a reply in flight; reusing the process
                # would hand that stale reply to the NEXT question and silently
                # mis-judge a frame. Losing time is acceptable, losing correctness
                # is not.
                if res is not None:
                    log(f'persistent judge returned not-ok ({res.get("error")})')
                _retire_server(model_id, tier)
                log('falling back to a one-shot spawn for this call')

        cmd = [_VLM_PY, _VLM_WORKER, '--model-id', model_id, '--images']
        cmd += [os.path.abspath(p) for p in images]
        cmd += ['--questions', qpath, '--out', vpath, '--device', cfg['device'], '--quantization', _quant_for(tier)]
        env = dict(os.environ)
        if cfg['device'] == 'cpu':
            # Hard guarantee: a CPU-tier judge cannot touch the render's VRAM.
            env['CUDA_VISIBLE_DEVICES'] = ''
        log(
            f'worker: {model_id} tier={tier} device={cfg["device"]} '
            f'images={len(images)} questions={len(questions_obj) if isinstance(questions_obj, list) else "?"}'
        )
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=_timeout_for(tier), env=env)
        if r.returncode != 0:
            log(f'worker FAILED rc={r.returncode}: {(r.stderr or "")[-600:]}')
            return None
        try:
            with open(vpath, encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('worker out file unreadable, falling back to its stdout: %s', _exc)
        for line in reversed((r.stdout or '').splitlines()):
            line = line.strip()
            if line.startswith('{'):
                try:
                    return json.loads(line)
                except ValueError as _exc:
                    _zyg_log.debug('non-JSON worker line ignored: %s', _exc)
                    continue
        log('worker produced no parseable JSON (no --out file, no final-line JSON)')
        return None
    except subprocess.TimeoutExpired:
        log(f'worker TIMEOUT after {_timeout_for(tier)}s (tier={tier})')
        return None
    except Exception as e:
        log(f'worker error: {e}')
        return None
    finally:
        if os.environ.get('ZYG_VLM_KEEP_FRAMES', '0') != '1':
            try:
                import shutil

                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception as _exc:
                _zyg_log.debug('worker temp dir cleanup skipped: %s', _exc)


def _aggregate(items, runs, log):
    """Fold k worker runs into one verdict set (majority vote per question)."""
    by_id = {it['id']: it for it in items}
    tally = {i: {'yes': 0, 'no': 0, 'unknown': 0} for i in by_id}
    reasons, boxes, box_frames = {}, {}, {}
    for run in runs:
        for v in run.get('verdicts') or []:
            if not isinstance(v, dict):
                continue
            vid = v.get('id')
            if vid not in tally:
                continue
            ans = _norm_answer(v.get('answer'))
            if ans == 'unknown' and isinstance(v.get('ok'), bool):
                # worker graded it itself — reconstruct the answer from expected
                exp = str(by_id[vid].get('expected', 'yes')).lower()
                ans = exp if v['ok'] else ('no' if exp == 'yes' else 'yes')
            tally[vid][ans] += 1
            if v.get('reason'):
                reasons.setdefault(vid, str(v['reason'])[:400])
            if v.get('bbox') and vid not in boxes:
                boxes[vid] = v['bbox']
                if v.get('bbox_frame') is not None:
                    box_frames[vid] = v.get('bbox_frame')

    verdicts, flags, criticals, majors, unknown = [], [], [], [], []
    for vid, it in by_id.items():
        t = tally[vid]
        if t['yes'] == 0 and t['no'] == 0:
            ans = 'unknown'
        else:
            ans = 'yes' if t['yes'] >= t['no'] else 'no'
        exp = str(it.get('expected', 'yes')).lower()
        sev = str(it.get('severity', 'major')).lower()
        ok = None if ans == 'unknown' else (ans == exp)
        rec = {
            'id': vid,
            'answer': ans,
            'expected': exp,
            'ok': ok,
            'severity': sev,
            'votes': t,
            'reason': reasons.get(vid, ''),
            'bbox': boxes.get(vid),
            'bbox_frame': box_frames.get(vid),
        }
        verdicts.append(rec)
        if ok is None:
            unknown.append(vid)  # fail-safe: unknown never fails a gate
            continue
        if not ok:
            flags.append(vid)
            (criticals if sev == 'critical' else majors).append(vid)
    ok = not criticals and (not majors or not _strict())
    if unknown:
        log(f'unanswered (treated as PASS): {", ".join(unknown)}')
    return {
        'ok': ok,
        'verdicts': verdicts,
        'flags': flags,
        'criticals': criticals,
        'majors': majors,
        'unknown': unknown,
        'bboxes': {k: v for k, v in boxes.items() if k in flags},
        'strict': _strict(),
    }
