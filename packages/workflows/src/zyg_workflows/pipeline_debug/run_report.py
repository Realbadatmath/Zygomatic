# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""DebugRun, part 3 of 3 (the class itself) plus the active-run registry.

Holds the module-level gate wrappers, the taxonomy/ledger/manifest/report.html
writers, make_ab_video, and `_ACTIVE` with its only mutator `set_active` — that
global and both its readers (`get_active` and `DebugRun._run_gate`) have to live
in one module, because a re-export by value cannot see a rebinding."""

import json
import os
import time
from zyg_workflows import paths
from zyg_workflows.bin import exe
from .common import _check_score, _contract, _ledger, _zyg_log
from .run_clip_qc import _DebugRunClipQC


class DebugRun(_DebugRunClipQC):
    # ── 2026-08-01 gates: who is alive, who leads the beats, what did I break ──
    # These three are module-level functions (callable from a bare python -c or the CLI at
    # the bottom of this file, with no DebugRun in sight). The methods here exist so that a
    # run gets their verdicts into ITS report.json / report.html / run_ledger even when it
    # is not the process-global active run — _record_qc() writes to get_active(), so the
    # only correct way to target a specific run is to make it active for the call.
    def _run_gate(self, fn, *a, **kw):
        """Run a module-level qc_* gate with THIS run active, then restore the previous
        one. Fail-safe: a gate that raises returns None rather than breaking the caller."""
        prev = _ACTIVE
        try:
            set_active(self)
            return fn(*a, **kw)
        except Exception as e:
            try:
                self.note(f'{getattr(fn, "__name__", "gate")} raised: {str(e)[:180]}')
            except Exception as _exc:
                _zyg_log.debug('gate failure note not recorded: %s', _exc)
            return None
        finally:
            set_active(prev)

    def qc_character_balance(self, tag, clip_path, characters, **kw):
        """Per-character face/hand aliveness + the cross-character face ratio.
        See the module-level qc_character_balance() for the measured calibration."""
        kw.setdefault('tag', tag)
        return self._run_gate(qc_character_balance, clip_path, characters, **kw)

    def qc_beat_prominence(self, tag, beats, characters, **kw):
        """PROMPT-side check (no video): does every character lead a fair share of the
        beats? This is the one that costs seconds instead of a 90-minute render."""
        kw.setdefault('tag', tag)
        return self._run_gate(qc_beat_prominence, beats, characters, **kw)

    def qc_regression_vs(self, tag, clip_path, baseline_path, regions, **kw):
        """Same regions, two clips, signed deltas — 'what did I break since <baseline>'."""
        kw.setdefault('tag', tag)
        return self._run_gate(qc_regression_vs, clip_path, baseline_path, regions, **kw)

    # ── finish ───────────────────────────────────────────────────────────────
    _TAXONOMY = (
        ('motion:', 'frozen-motion'),
        ('track:', 'frozen-motion'),
        ('set_stability', 'set-churn'),
        ('set_churn_residual', 'set-churn'),
        ('camera_motion', 'camera-drift'),
        ('exposure:', 'overexposure'),
        ('hand_count', 'hand-malform'),
        ('color_drift', 'grade-drift'),
        ('flicker_index', 'boiling'),
        ('chain_seams', 'chain-seam'),
        ('identity:', 'identity-drift'),
        ('region_flow:', 'frozen-motion'),
        ('prop_ncc:', 'prop-morph'),
        # 2026-07-31 C1 triad + the two v8b edge/FX gates
        ('prop_triad', 'prop-morph'),
        ('prop_scale', 'prop-morph'),
        ('prop_geometry', 'prop-morph'),
        ('prop_ridge', 'prop-morph'),
        ('frame_border:', 'chain-seam'),
        ('fx_', 'boiling'),
        # 2026-07-31 motion QUALITY (jitter) — distinct from 'frozen-motion',
        # which is the opposite failure and has the opposite remedy
        ('motion_quality:', 'motion-jitter'),
        ('motion_balance:', 'motion-jitter'),
        # 2026-08-01 — WHO is alive. 'character-imbalance' is its own class: the
        # shot is neither frozen nor jittery, it is CARRIED BY ONE CHARACTER while
        # the other sits there as set dressing. The remedy is prompt-side, which is
        # why the static beat gate shares the tag. 'box_quality' is deliberately NOT
        # tagged that way — a diluted face box is a broken MEASUREMENT, and calling
        # it a shot defect would send the operator to re-render a fine shot.
        ('character_balance:box_quality', 'qc-broken'),
        ('character_balance:measured', 'qc-broken'),
        ('character_balance:', 'character-imbalance'),
        ('beat_prominence', 'character-imbalance'),
        ('regression:provenance', 'qc-broken'),
        ('regression:measured', 'qc-broken'),
        ('regression:', 'regression'),
    )

    def _taxonomy_tag(self, check):
        for pre, t in self._TAXONOMY:
            if str(check or '').startswith(pre):
                return t
        return ''

    def _record_gates(self):
        """Every QC check of this run → run_ledger.gates (run_id, gate, outcome,
        score, taxonomy tag). One run's gates are boring; fourteen days of them are
        how a quiet pass-rate slide (the ghost-face pattern) becomes visible."""
        n = 0
        try:
            led = _ledger()
            if led is None:
                return 0
            qcm = _contract()
            for q in self.doc.get('qc', []):
                for c in q.get('checks', []):
                    gate = str(c.get('check') or q.get('kind') or 'unknown')
                    if qcm is not None:
                        # classify() also catches ok=True carrying a skip note —
                        # a green verdict from a gate that never looked.
                        v = qcm.classify(c)
                        outcome = {qcm.PASS: 'pass', qcm.FAIL: 'fail'}.get(v, 'skip')
                        # A SHADOW gate is measured, never enforced — finish() already
                        # keeps its FAIL out of verdict.ok. Writing it here as a plain
                        # 'fail' still dragged the cross-run pass-rate down as if it
                        # had blocked something, so it gets its own outcome: the trend
                        # loop counts only 'pass'/'fail' (run_ledger.py:495-515).
                        if v == qcm.FAIL:
                            try:
                                mode = qcm.mode_for(c.get('check'))
                            except Exception:
                                mode = None
                            if mode == qcm.SHADOW:
                                outcome = 'shadow_fail'
                    else:
                        ok = c.get('ok')
                        outcome = 'pass' if ok else ('skip' if ok is None else 'fail')
                    if led.record_gate(
                        self.run_id, gate, outcome, score=_check_score(c), tag=self._taxonomy_tag(c.get('check'))
                    ):
                        n += 1
                # a QC battery that ERRORED is itself an event worth trending
                if q.get('error'):
                    led.record_gate(self.run_id, f'qc_error:{q.get("kind")}', 'fail', tag='qc-broken')
        except Exception as _exc:
            _zyg_log.warning('gate outcomes only partly recorded in the run ledger (%d written): %s', n, _exc)
        return n

    def _export_qc_spec(self):
        """Publish the thresholds this run was ACTUALLY judged by, into the run
        dir where self_improve.load_qc_spec() looks for them.

        The self-improvement loop's top remedy needed a qc_spec citing
        `scene20_v8.py::V8_QC` — a driver that does not exist. Its thresholds had
        been authored by the agent that built the report rather than exported by
        production, so the loop was reasoning about a system that was not the one
        that shipped. Without qc_spec only `unnecessary_pin` could fire, because
        no rule consumes the region-free discovery.* facts.

        Written from qc_contract (the live ladder) plus the regions this run
        genuinely measured. Region boxes come from shot_metadata.json when it
        exists; load_qc_spec falls back to it for boxes anyway."""
        try:
            qcm = _contract()
            if qcm is None:
                return
            checks = [c for q in self.doc.get('qc', []) for c in q.get('checks', [])]
            regions, props = {}, {}
            for c in checks:
                n = str(c.get('check') or '')
                if n.startswith('region_flow:') and not n.startswith('region_flow:keep'):
                    regions.setdefault(n.split(':', 1)[1], None)
                elif n.startswith('prop_ncc:'):
                    props.setdefault(n.split(':', 1)[1], None)
            if not regions and not props:
                return

            meta = {}
            for fn in ('shot_metadata.json', 'regions.json'):
                try:
                    with open(os.path.join(self.run_dir, fn), encoding='utf-8') as f:
                        meta = json.load(f) or {}
                    break
                except (OSError, json.JSONDecodeError) as _exc:
                    _zyg_log.debug('region metadata not readable from %s: %s', fn, _exc)
                    continue
            boxes = meta.get('regions') or (meta.get('qc') or {}).get('regions') or {}
            for k in list(regions):
                if k in boxes:
                    regions[k] = boxes[k]

            spec = {
                '_README': (
                    'AUTO-EXPORTED by pipeline_debug.DebugRun.finish() from '
                    'the live qc_contract ladder. These are the thresholds '
                    'this run was actually judged by — not a driver constant.'
                ),
                'source': 'pipeline_debug/qc_contract',
                'run_id': self.run_id,
                'regions': {k: v for k, v in regions.items() if v} or {k: None for k in regions},
                'prop_boxes': props,
                'min_flow': (qcm.contract_for('region_flow:') or None) and qcm.contract_for('region_flow:').noise_floor,
                'max_churn': (qcm.contract_for('region_churn:') or None)
                and qcm.contract_for('region_churn:').noise_floor,
                'ncc_min': (qcm.contract_for('prop_ncc:') or None) and qcm.contract_for('prop_ncc:').noise_floor,
                'gate_modes': {
                    g: qcm.mode_for_gate_name(g) for g in sorted({c.name for c in qcm.GATE_CONTRACTS.values()})
                },
                'enforcement': qcm.enforcement_enabled(),
            }
            tmp = os.path.join(self.run_dir, 'qc_spec.json.tmp')
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(spec, f, indent=1, ensure_ascii=False)
            os.replace(tmp, os.path.join(self.run_dir, 'qc_spec.json'))
        except Exception as _exc:
            _zyg_log.warning('qc_spec.json write failed, the thresholds used are not published: %s', _exc)

    def _collect_degradations(self):
        """Pull every silent fallback logged under this run_id out of the ledger."""
        try:
            led = _ledger()
            if led is None:
                return []
            return led.fallbacks_for_run(self.run_id) or []
        except Exception:
            return []

    def _restore_run_id_env(self):
        """Un-export ZYG_RUN_ID so a long-lived Flask process does not attribute the
        NEXT job's fallbacks to this finished run."""
        try:
            if not self._run_id_exported:
                return
            if self._prev_run_id_env is None:
                os.environ.pop('ZYG_RUN_ID', None)
            else:
                os.environ['ZYG_RUN_ID'] = self._prev_run_id_env
            self._run_id_exported = False
        except Exception as _exc:
            _zyg_log.warning('ZYG_RUN_ID un-export failed, a later job may inherit this run_id: %s', _exc)

    def finish(self, ok=None):
        """Close the run, write the verdict, and — new as of 2026-08-04 — actually
        ENFORCE the gate ladder.

        Before this, `gate_mode` was read from a file that did not exist, defaulted
        to 'shadow', was written into the verdict, and was consumed by nothing:
        `grep gate_mode` returned zero call sites. Every gate in a 203 KB QC module
        was advisory. scene20_v28 — the best render on disk — finished with
        verdict.ok=false, 29 failed checks and 10 defect tags, and shipped.

        Raises qc_contract.QCBlocked when a gate at mode=block returns FAIL. The
        raise happens OUTSIDE the try/except below, because that except swallows
        everything and would have turned the block back into a shrug.
        """
        verdict = None
        blocking = []
        try:
            self._flush_stage()  # the last stage never got a successor to close it
            checks = [c for q in self.doc['qc'] for c in q.get('checks', [])]
            qcm = _contract()

            shadow_fails = []
            if qcm is not None:
                ev = qcm.evaluate(checks)
                # 2026-09-03: a SHADOW gate is 'measure, record, never surface as a
                # blocker' (qc_contract.py:45). It was surfacing anyway — every FAIL
                # counted here regardless of mode, so one unregistered gate flipped
                # verdict.ok. Split them: shadow failures are recorded, not counted.
                fails = []
                for c in checks:
                    if qcm.classify(c) != qcm.FAIL:
                        continue
                    try:
                        mode = qcm.mode_for(c.get('check'))
                    except Exception:
                        mode = None
                    (shadow_fails if mode == qcm.SHADOW else fails).append(c)
                blocking = list(ev.get('blocking_failures') or [])
            else:  # contract unavailable — legacy two-verdict path
                ev = {}
                fails = [c for c in checks if not c.get('ok')]

            # A9: failure taxonomy tags
            tags = sorted({t for c in fails for pre, t in self._TAXONOMY if str(c.get('check', '')).startswith(pre)})
            shadow_tags = sorted(
                {t for c in shadow_fails for pre, t in self._TAXONOMY if str(c.get('check', '')).startswith(pre)}
            )

            self._record_gates()  # cross-run gate ledger
            degr = self._collect_degradations()  # silent-degrade ledger
            self.doc['degradations'] = degr

            verdict = {
                'ok': (ok if ok is not None else not fails),
                'failed_checks': len(fails),
                'tags': tags,
                'shadow_failed': len(shadow_fails),
                'shadow_tags': shadow_tags,
                'shadow_failed_checks': [str(c.get('check', '')) for c in shadow_fails],
                'run_id': self.run_id,
                'degradations': len(degr),
                'finished': time.strftime('%Y-%m-%d %H:%M:%S'),
            }
            verdict.update(ev)  # pass/fail/unknown counts, coverage, blocked
            # ev['failed_checks'] counts EVERY FAIL, shadow included; the verdict's
            # own count is the one that decides 'ok', so it wins here.
            verdict['failed_checks'] = len(fails)
            # a run is only 'ok' if nothing at block level failed
            if verdict.get('blocked'):
                verdict['ok'] = False
            self.doc['verdict'] = verdict

            self._manifest()  # A2
            self._diff_vs_lastpass()  # A1
            self._history()  # A11
            self._export_qc_spec()  # thresholds -> self_improve.load_qc_spec
            self._save()
            self._html()
        except Exception:
            verdict = self.doc.get('verdict')
        finally:
            self._restore_run_id_env()

        # ── enforcement, outside the swallow ────────────────────────────────
        if verdict and verdict.get('blocked'):
            qcm = _contract()
            if qcm is not None:
                raise qcm.QCBlocked(
                    f'QC blocked {self.run_id}: '
                    f'{len(blocking)} gate(s) at mode=block failed '
                    f'({", ".join(sorted(set(blocking))[:6])}). '
                    f'Report: {os.path.join(self.dir, "report.html")}. '
                    f'Override for this run with ZYG_QC_ENFORCE=0.',
                    verdict=verdict,
                    gates=blocking,
                )
        return verdict

    def _manifest(self):
        """A2: executed-state manifest — env flags, model files referenced by recorded
        graphs (size+mtime), torch/driver versions. Answers 'what ACTUALLY ran'."""
        try:
            man = {
                'env': {k: v for k, v in os.environ.items() if k.startswith('ZYG_')},
                'python': os.sys.version.split()[0],
                'run_id': self.run_id,
            }
            try:
                import torch

                man['torch'] = torch.__version__
            except Exception as _exc:
                _zyg_log.debug('torch version unavailable for the manifest: %s', _exc)
            # 2026-07-30: NVML (nvidia-ml-py, BSD) instead of shelling out to
            # nvidia-smi — microseconds instead of ~200ms of subprocess, and it also
            # yields live VRAM. run_ledger.gpu_info() keeps the nvidia-smi path as a
            # graceful fallback and returns {'source': None} if the GPU is absent.
            try:
                led = _ledger()
                man['gpu'] = led.gpu_info() if led is not None else {'source': None}
            except Exception:
                man['gpu'] = {'source': None}
            roots = (
                str(paths.ZYG_COMFY_ROOT / 'models' / 'diffusion_models'),
                str(paths.ZYG_COMFY_ROOT / 'models' / 'loras'),
            )
            # Weight attestation: SHA256 of every safetensors the recorded graphs
            # actually referenced (mtime+size cached, so it is a stat() after the
            # first run). This is what catches an in-place checkpoint clobber
            # (2026-07-26 Juggernaut→DynaVision) that size+mtime alone can miss.
            want_sha = os.environ.get('ZYG_MANIFEST_SHA256', '1') not in ('0', 'false', 'no')
            max_mb = float(os.environ.get('ZYG_MANIFEST_SHA256_MAX_MB', '32000') or 32000)
            files = {}
            for st in self.doc['stages']:
                for gf in st.get('graphs', []):
                    try:
                        with open(os.path.join(self.dir, gf)) as f:
                            gd = json.load(f)
                        for n in gd.values():
                            for v in (n.get('inputs') or {}).values():
                                if isinstance(v, str) and v.endswith('.safetensors'):
                                    for root in roots:
                                        fp = os.path.join(root, v)
                                        if os.path.isfile(fp):
                                            s = os.stat(fp)
                                            rec = {'size': s.st_size, 'mtime': int(s.st_mtime)}
                                            if want_sha and s.st_size <= max_mb * 1048576:
                                                led = _ledger()
                                                if led is not None:
                                                    rec['sha256'] = led.sha256_file(fp)
                                            files[v] = rec
                    except Exception as _exc:
                        _zyg_log.warning('weight attestation skipped for graph %s: %s', gf, _exc)
                        continue
            man['model_files'] = files
            # Silent degrades recorded anywhere in the process under this run_id.
            man['degradations'] = self.doc.get('degradations') or []
            with open(os.path.join(self.dir, 'manifest.json'), 'w') as f:
                json.dump(man, f, indent=1)
            self.doc['manifest'] = 'manifest.json'
        except Exception as _exc:
            _zyg_log.warning('manifest.json write failed, this run has no executed-state record: %s', _exc)

    def _diff_vs_lastpass(self):
        """A1: 'what changed since the last PASS of this run-name' — prompts + graph scalars.
        Catches config regressions (the anti-static-negative class) in one glance."""
        try:
            reg_path = os.path.join(_CREWS, 'data', 'runtime', 'debug_lastpass.json')
            try:
                with open(reg_path) as f:
                    reg = json.load(f)
            except Exception:
                reg = {}
            prev_dir = reg.get(self.name)
            changes = []
            if prev_dir and os.path.isdir(prev_dir) and os.path.abspath(prev_dir) != os.path.abspath(self.dir):
                try:
                    with open(os.path.join(prev_dir, 'report.json')) as f:
                        prev = json.load(f)
                    import difflib

                    for st_new in self.doc['stages']:
                        st_old = next(
                            (s for s in prev.get('stages', []) if s.get('stage') == st_new.get('stage')), None
                        )
                        if not st_old:
                            continue
                        for pn, po in zip(st_new.get('prompts', []), st_old.get('prompts', [])):
                            for field in ('positive', 'negative'):
                                if pn.get(field) != po.get(field):
                                    d = '\n'.join(
                                        difflib.unified_diff(
                                            (po.get(field) or '').split(', '),
                                            (pn.get(field) or '').split(', '),
                                            lineterm='',
                                            n=0,
                                        )
                                    )[:800]
                                    changes.append(
                                        {'stage': st_new['stage'], 'what': f'{pn.get("tag")}:{field}', 'diff': d}
                                    )
                        if json.dumps(st_new.get('params'), sort_keys=True) != json.dumps(
                            st_old.get('params'), sort_keys=True
                        ):
                            changes.append(
                                {
                                    'stage': st_new['stage'],
                                    'what': 'params',
                                    'diff': f'old={st_old.get("params")} new={st_new.get("params")}'[:600],
                                }
                            )
                except Exception as _exc:
                    _zyg_log.debug('stage diff vs the last pass skipped: %s', _exc)
            self.doc['changes_since_last_pass'] = changes
            if self.doc.get('verdict', {}).get('ok'):
                reg[self.name] = self.dir
                os.makedirs(os.path.dirname(reg_path), exist_ok=True)
                with open(reg_path, 'w') as f:
                    json.dump(reg, f, indent=1)
        except Exception as _exc:
            _zyg_log.warning('last-pass registry update failed, the next run cannot diff against this one: %s', _exc)

    def _history(self):
        """A11: append a run summary line for cross-run trends (durations, verdict, tags)."""
        try:
            hp = os.path.join(_CREWS, 'data', 'runtime', 'debug_run_history.jsonl')
            os.makedirs(os.path.dirname(hp), exist_ok=True)
            with open(hp, 'a') as f:
                f.write(
                    json.dumps(
                        {
                            'name': self.name,
                            'dir': self.dir,
                            'run_id': self.run_id,
                            'ts': time.strftime('%Y-%m-%d %H:%M:%S'),
                            'degradations': len(self.doc.get('degradations') or []),
                            'verdict': self.doc.get('verdict'),
                        }
                    )
                    + '\n'
                )
        except Exception as _exc:
            _zyg_log.warning('run history line not appended, cross-run trends will miss this run: %s', _exc)

    # ── internals ────────────────────────────────────────────────────────────
    def _mk(self, _key):
        self.stage('(implicit)')
        return self._cur

    def _save(self):
        try:
            with open(os.path.join(self.dir, 'report.json'), 'w', encoding='utf-8') as f:
                json.dump(self.doc, f, indent=1, ensure_ascii=False)
        except Exception as _exc:
            _zyg_log.warning('report.json write failed, the debug report is stale: %s', _exc)

    def _html(self):
        try:
            d = self.doc
            rows = []
            for st in d['stages']:
                snaps = ''.join(
                    f'<figure><img src="thumbs/{s["thumb"]}"><figcaption>{s["tag"]}</figcaption></figure>'
                    for s in st.get('snapshots', [])
                )
                prompts = ''.join(
                    f'<details><summary>prompt: {p["tag"]}</summary><pre>+ {p.get("positive", "")}\n- {p.get("negative", "")}</pre></details>'
                    for p in st.get('prompts', [])
                )
                graphs = ' '.join(f'<a href="{g}">{g}</a>' for g in st.get('graphs', []))
                notes = '<br>'.join(st.get('notes', []))
                params = json.dumps(st.get('params', {}), ensure_ascii=False)[:600]
                rows.append(
                    f'<section><h3>{st["stage"]} <small>{st["t"]}</small></h3>'
                    f'<code>{params}</code><div class="snaps">{snaps}</div>'
                    f'{prompts}<div>{graphs}</div><div class="notes">{notes}</div></section>'
                )
            qcm = _contract()

            def _vrd(c):
                """PASS / FAIL / UNKNOWN + the gate's ladder mode."""
                if qcm is None:
                    return ('PASS', 'ok') if c.get('ok') else ('FAIL', 'bad')
                v = qcm.classify(c)
                mode = qcm.mode_for(c.get('check'))
                if v == qcm.UNKNOWN:
                    return ('UNKNOWN', 'unk')
                if v == qcm.FAIL:
                    return (f'FAIL[{mode}]', 'bad' if mode == 'block' else 'warn')
                return ('PASS', 'ok')

            qcrows = []
            for q in d['qc']:
                cells = []
                for c in q.get('checks', []):
                    label, cls = _vrd(c)
                    data = json.dumps(
                        {k: v for k, v in c.items() if k not in ('check', 'ok', 'note')}, ensure_ascii=False
                    )
                    cells.append(
                        f'<tr class="{cls}"><td>{c.get("check")}</td>'
                        f'<td>{data}</td><td>{label}</td>'
                        f'<td>{c.get("note", "")}</td></tr>'
                    )
                qcrows.append(
                    f'<h3>QC — {q["tag"]} ({q["kind"]})</h3>'
                    f'<table><tr><th>check</th><th>data</th>'
                    f'<th>verdict</th><th>note</th></tr>'
                    f'{"".join(cells)}</table>'
                )

            # ── coverage matrix: what this run did NOT test ─────────────────
            # The yellow rows are the point. A green run with six uncovered
            # classes is not clean, it is six unopened doors. 'eyelid-aperture'
            # sat uncovered for six renders while every gate measured motion,
            # which is ANTI-CORRELATED with it.
            covhtml = ''
            try:
                if qcm is not None:
                    allchecks = [c for qq in d['qc'] for c in qq.get('checks', [])]
                    cov = qcm.coverage(allchecks)
                    crows = []
                    for cls in sorted(cov):
                        if cls == 'qc-broken':
                            continue
                        row = cov[cls]
                        status = row['status']
                        cls_css = {'covered': 'ok', 'unknown': 'unk', 'uncovered': 'unk'}[status]
                        gates = ', '.join(row['gates']) or '—'
                        blind = ', '.join(row['blind_gates']) or ''
                        why = qcm.DEFECT_TAXONOMY.get(cls, '')
                        crows.append(
                            f'<tr class="{cls_css}"><td><b>{cls}</b><br>'
                            f'<small>{why}</small></td>'
                            f'<td>{status.upper()}</td><td>{gates}</td>'
                            f'<td><small>{blind}</small></td></tr>'
                        )
                    ungated = ', '.join(qcm.ungated_classes()) or 'none'
                    covhtml = (
                        '<h2>Coverage — what was actually tested</h2>'
                        '<p><small>UNCOVERED means no gate that detects this class '
                        'ran. It is not a pass. These are the classes your eyes are '
                        'still the only instrument for.<br>'
                        f'No gate anywhere in the registry detects: <b>{ungated}</b>'
                        '</small></p>'
                        '<table><tr><th>defect class</th><th>status</th>'
                        '<th>gates that looked</th><th>gates blind to it</th></tr>'
                        f'{"".join(crows)}</table>'
                    )
            except Exception:
                covhtml = ''
            v = d.get('verdict') or {}
            color = '#3fb950' if v.get('ok') else '#f85149'
            # degradations: what silently ran in a mode nobody asked for
            degr = d.get('degradations') or []
            if degr:
                drows = ''.join(
                    f'<tr class="bad"><td>{g.get("component")}</td>'
                    f'<td>{g.get("expected")}</td><td>{g.get("actual")}</td>'
                    f'<td>{str(g.get("detail") or "")[:300]}</td>'
                    f'<td>{g.get("ts_iso") or ""}</td></tr>'
                    for g in degr
                )
                degr_html = (
                    '<section><h3>Degradations — SILENT FALLBACKS THIS RUN '
                    f'({len(degr)})</h3><table><tr><th>component</th>'
                    '<th>expected</th><th>actually ran</th><th>detail</th>'
                    f'<th>when</th></tr>{drows}</table></section>'
                )
            else:
                degr_html = (
                    '<section><h3>Degradations</h3><div class="notes">none '
                    'recorded — every instrumented component ran in its '
                    'expected mode</div></section>'
                )
            html = (
                '<!DOCTYPE html><meta charset="utf-8"><title>debug ' + d['name'] + '</title>'
                '<style>body{background:#0e1014;color:#e6e9ef;font:14px system-ui;margin:24px;}'
                'section{border:1px solid #262b34;border-radius:8px;padding:12px;margin:12px 0;}'
                'img{border-radius:6px;max-width:280px;} figure{display:inline-block;margin:6px;}'
                'figcaption{font-size:11px;color:#9aa4b2;} code,pre{background:#171a21;padding:4px 8px;'
                'border-radius:6px;display:block;white-space:pre-wrap;} table{border-collapse:collapse;width:100%;}'
                'td,th{border:1px solid #262b34;padding:5px 9px;font-size:13px;text-align:left;}'
                'tr.bad td{color:#f85149;} tr.ok td{color:#9fd4a0;}'
                'tr.warn td{color:#e3b341;} tr.unk td{color:#d29922;background:#1d1a10;}'
                '.notes{color:#9aa4b2;font-size:12px;}'
                '.blocked{background:#3d1416;border:1px solid #f85149;padding:8px 12px;'
                'border-radius:6px;margin:8px 0;}'
                '</style>'
                f'<h1>Debug — {d["name"]}</h1>'
                f'<p>started {d["started"]} · run_id <code style="display:inline">'
                f'{d.get("run_id", "?")}</code> · verdict <b style="color:{color}">'
                f'{"PASS" if v.get("ok") else "FAIL"}</b> · '
                f'{v.get("passed_checks", "?")} pass / {v.get("failed_checks", "?")} fail / '
                f'<span style="color:#d29922">{v.get("unknown_checks", 0)} unknown</span>'
                f' · coverage {v.get("coverage_score", "?")}'
                f' · {len(d.get("degradations") or [])} degradation(s)</p>'
                + (
                    f'<div class="blocked"><b>BLOCKED</b> — gate(s) at mode=block '
                    f'failed: {", ".join(sorted(set(v.get("blocking_failures") or [])))}'
                    f'</div>'
                    if v.get('blocked')
                    else ''
                )
                + (
                    f'<p class="notes">UNCOVERED this run: '
                    f'<b>{", ".join(v.get("uncovered_classes") or []) or "none"}</b></p>'
                )
                + degr_html
                + covhtml
                + ''.join(rows)
                + ''.join(qcrows)
            )
            with open(os.path.join(self.dir, 'report.html'), 'w', encoding='utf-8') as f:
                f.write(html)
        except Exception as _exc:
            _zyg_log.warning('report.html write failed: %s', _exc)


# THE ONE LINE OF THIS SPLIT THAT IS NOT VERBATIM. It read
#     _CREWS = os.path.dirname(os.path.abspath(__file__))
# while pipeline_debug.py sat directly in zyg_workflows/, so it resolved to that package
# root. This module is one level deeper, and _diff_vs_lastpass / _history join
# data/runtime/debug_lastpass.json and data/runtime/debug_run_history.jsonl onto it — a
# verbatim copy would have silently moved both ledgers into pipeline_debug/data/.
# dirname twice keeps the value, and therefore both file paths, exactly as they were.
_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make_ab_video(clip_a, clip_b, out_path):
    """A8: side-by-side + difference comparison video for human review (ffmpeg only)."""
    import subprocess

    try:
        subprocess.run(
            [
                exe('ffmpeg'),
                '-y',
                '-loglevel',
                'error',
                '-i',
                clip_a,
                '-i',
                clip_b,
                '-filter_complex',
                '[0:v]scale=640:-2[a];[1:v]scale=640:-2[b];'
                '[a][b]hstack[top];[0:v][1:v]blend=all_mode=difference,scale=1280:-2,eq=brightness=0.3[diff];'
                '[top][diff]vstack',
                out_path,
            ],
            check=True,
            timeout=300,
        )
        return out_path
    except Exception:
        return None


# ── active-run registry: services record into the current run without signature changes ──
_ACTIVE = None


class _Null:
    def __getattr__(self, _n):
        return lambda *a, **k: None


def set_active(dbg):
    global _ACTIVE
    _ACTIVE = dbg


def get_active():
    """Always safe to call: returns the active DebugRun or a no-op stand-in."""
    return _ACTIVE if _ACTIVE is not None else _Null()


# imported last: these module-level gates close the cycle with this module
# (DebugRun._run_gate resolves them at call time, not at import time).
from .gates_charbal import qc_character_balance  # noqa: E402
from .gates_beats import qc_beat_prominence  # noqa: E402
from .gates_regression import qc_regression_vs  # noqa: E402
