# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""DebugRun, part 1 of 3: construction, stage/graph/prompt recording and the
still-level QC batteries (qc_still, qc_identity, qc_mask_boundary, qc_semantics)."""

import json
import os
import time
from .common import (
    _CLIP,
    _THUMB_W,
    _clip_embed,
    _detect_hands,
    _jsonable,
    _ledger,
    _now,
    _vram_mb,
    _zyg_log,
    identity_similarity,
)


class _DebugRunRecord:
    def __init__(self, run_dir, name='run', run_id=None):
        self.dir = os.path.join(run_dir, 'debug')
        self.run_dir = run_dir
        self.name = name
        # run_id: explicit → inherited ZYG_RUN_ID → generated. When we generate it we
        # EXPORT it, so record_fallback() calls deep inside audio_mix / zyg_whisper /
        # tts attribute to this run with no signature changes; finish() restores it.
        # CAVEAT: os.environ is process-global. Two DebugRuns open SIMULTANEOUSLY in one
        # process (concurrent jobs in the Flask worker) share the env var, so the later
        # one wins and un-plumbed fallbacks may be attributed to it. The ledger itself is
        # per-call and thread-safe; only this convenience default is racy. Callers that
        # need exactness pass run_id= to record_fallback() directly.
        inherited = os.environ.get('ZYG_RUN_ID')
        self.run_id = str(run_id or inherited or f'{name}-{time.strftime("%Y%m%d-%H%M%S")}-{os.getpid()}')
        self._run_id_exported = (run_id is not None) or (not inherited)
        self._prev_run_id_env = inherited
        if self._run_id_exported:
            try:
                os.environ['ZYG_RUN_ID'] = self.run_id
            except Exception:
                self._run_id_exported = False
        self.doc = {
            'name': name,
            'run_id': self.run_id,
            'started': time.strftime('%Y-%m-%d %H:%M:%S'),
            'stages': [],
            'qc': [],
            'degradations': [],
            'verdict': None,
        }
        self._cur = None
        self._t0 = None  # monotonic start of the open stage
        self._vram0 = None  # VRAM MB at the open stage's start
        try:
            os.makedirs(os.path.join(self.dir, 'thumbs'), exist_ok=True)
        except OSError as _exc:
            _zyg_log.warning('thumbs dir creation failed, snapshots will not be saved: %s', _exc)

    # ── recording ────────────────────────────────────────────────────────────
    def stage(self, name, params=None):
        try:
            self._flush_stage()  # close out + ledger the PREVIOUS stage first
            self._cur = {
                'stage': name,
                't': _now(),
                'params': _jsonable(params or {}),
                'graphs': [],
                'prompts': [],
                'snapshots': [],
                'notes': [],
            }
            self.doc['stages'].append(self._cur)
            self._t0 = time.monotonic()
            self._vram0 = _vram_mb()
            self._save()
        except Exception as _exc:
            _zyg_log.warning('stage %r not recorded in the debug report: %s', name, _exc)

    def _flush_stage(self):
        """Record the open stage's EXECUTION PROVENANCE into run_ledger.stages and
        stamp wall_s onto the report. Provenance fields are read from the stage
        params when present (device / model_id / dtype / weights_sha256 / fallback) —
        callers that pass them get a real answer to 'what actually ran'; callers that
        don't still get timing + VRAM, which is enough to fingerprint a degrade.

        vram_peak_mb is the max of TWO boundary samples (stage start, stage end), not a
        continuous sampler — enough to separate a 33GB GPU render from a 2GB CPU
        fallback, not enough to catch a transient mid-stage spike.
        Fail-safe: never raises, never blocks."""
        try:
            if self._cur is None or self._t0 is None:
                return
            wall = time.monotonic() - self._t0
            self._cur['wall_s'] = round(wall, 2)
            v1 = _vram_mb()
            samples = [v for v in (self._vram0, v1) if v is not None]
            peak = max(samples) if samples else None
            if peak is not None:
                self._cur['vram_mb'] = peak
            led = _ledger()
            if led is not None:
                p = self._cur.get('params')
                p = p if isinstance(p, dict) else {}
                led.record_stage(
                    self._cur.get('stage'),
                    run_id=self.run_id,
                    device=p.get('device'),
                    model_id=(p.get('model_id') or p.get('model') or p.get('checkpoint') or p.get('ckpt')),
                    weights_sha256=p.get('weights_sha256'),
                    dtype=p.get('dtype'),
                    fallback_taken=(p.get('fallback') or p.get('fallback_taken')),
                    wall_s=round(wall, 3),
                    vram_peak_mb=peak,
                )
        except Exception as _exc:
            _zyg_log.warning('stage provenance not recorded in the run ledger: %s', _exc)
        finally:
            self._t0 = None
            self._vram0 = None

    def note(self, msg):
        try:
            (self._cur or self._mk('notes'))['notes'].append(f'[{_now()}] {str(msg)[:300]}')
            self._save()
        except Exception as _exc:
            _zyg_log.warning('note not recorded in the debug report: %s', _exc)

    def record_graph(self, tag, graph):
        """Dump the EXACT ComfyUI graph submitted — scalar inputs only, per node."""
        try:
            slim = {}
            for nid, node in (graph or {}).items():
                inputs = {k: v for k, v in (node.get('inputs') or {}).items() if not isinstance(v, list)}
                slim[nid] = {'class': node.get('class_type'), 'inputs': inputs}
            fp = os.path.join(self.dir, f'graph_{tag}_{len(self._cur["graphs"])}.json')
            with open(fp, 'w', encoding='utf-8') as f:
                json.dump(slim, f, indent=1, ensure_ascii=False)
            (self._cur or self._mk('graphs'))['graphs'].append(os.path.basename(fp))
            self._save()
        except Exception as _exc:
            _zyg_log.warning('graph dump %r failed, the manifest cannot attest its weights: %s', tag, _exc)

    def record_prompts(self, tag, positive=None, negative=None, **extra):
        try:
            rec = {'tag': tag, 'positive': str(positive or '')[:900], 'negative': str(negative or '')[:900]}
            rec.update({k: str(v)[:300] for k, v in extra.items()})
            (self._cur or self._mk('prompts'))['prompts'].append(rec)
            self._save()
        except Exception as _exc:
            _zyg_log.warning('prompt record %r not written to the debug report: %s', tag, _exc)

    def snapshot(self, tag, image_path):
        try:
            from PIL import Image

            if not (image_path and os.path.isfile(image_path)):
                return
            im = Image.open(image_path).convert('RGB')
            im.thumbnail((_THUMB_W, _THUMB_W * 3))
            fn = f'{len(self.doc["stages"]):02d}_{tag}.jpg'
            im.save(os.path.join(self.dir, 'thumbs', fn), quality=82)
            (self._cur or self._mk('snapshots'))['snapshots'].append({'tag': tag, 'thumb': fn, 'src': image_path})
            self._save()
        except Exception as _exc:
            _zyg_log.debug('snapshot thumbnail %r skipped: %s', tag, _exc)

    # ── QC batteries ─────────────────────────────────────────────────────────
    def qc_still(self, tag, still_path, char_regions=None, n_people=None):
        """Still gate: exposure per region + hand detection. char_regions: [(name, x0,y0,x1,y1
        as 0-1 fractions), ...]. n_people bounds the allowed hand count (detector scans the
        WHOLE image, so the allowance is 2×people — not 2×regions-passed). Returns checks."""
        out = {'tag': tag, 'kind': 'still', 'path': still_path, 'checks': []}
        try:
            import numpy as np
            from PIL import Image

            im = Image.open(still_path).convert('RGB')
            arr = np.asarray(im, dtype=float)
            H, W = arr.shape[:2]
            regions = char_regions or [('frame', 0, 0, 1, 1)]
            for name, fx0, fy0, fx1, fy1 in regions:
                rg = arr[int(H * fy0) : int(H * fy1), int(W * fx0) : int(W * fx1)]
                clipped = float((rg.max(axis=2) > 240).mean() * 100)
                mean_luma = float(rg.mean())
                exp_ok = clipped < 6.0 and mean_luma >= 28.0
                note = ''
                if clipped >= 6.0:
                    note = f'{clipped:.0f}% clipped highlights — overlit'
                elif mean_luma < 28.0:
                    note = f'mean luma {mean_luma:.0f} — underexposed (faces unreadable)'
                out['checks'].append(
                    {
                        'check': f'exposure:{name}',
                        'clipped_pct': round(clipped, 1),
                        'mean_luma': round(mean_luma, 1),
                        'ok': exp_ok,
                        'note': note,
                    }
                )
            # hand count via the installed detector (best-effort; unavailable → skipped)
            hands = _detect_hands(still_path)
            if hands is not None:
                allowed = 2 * max(1, int(n_people or len(regions)))
                out['checks'].append(
                    {
                        'check': 'hand_count',
                        'value': hands,
                        'allowed': allowed,
                        'ok': hands <= allowed,
                        'note': ''
                        if hands <= allowed
                        else f'{hands} hands for {n_people or len(regions)} people — extra-hand suspect',
                    }
                )
        except Exception as e:
            out['error'] = str(e)[:200]
        self.doc['qc'].append(out)
        self._save()
        return out

    def qc_identity(self, tag, image_path, char_map, threshold=0.80):
        """Identity-vs-canon gate. char_map: [(name, canon_crop_path, (fx0,fy0,fx1,fy1)), ...].
        CLIP cosine per character region vs its canonical face crop. Threshold 0.80 calibrated
        2026-07-29: canon-self 0.93, drifted video 0.66-0.75, wrong-char 0.71."""
        out = {'tag': tag, 'kind': 'identity', 'path': image_path, 'checks': []}
        try:
            for name, canon, region in char_map:
                sim = identity_similarity(image_path, canon, region=region)
                if sim is None:
                    continue
                out['checks'].append(
                    {
                        'check': f'identity:{name}',
                        'clip_sim': round(sim, 3),
                        'ok': sim >= threshold,
                        'note': '' if sim >= threshold else f'sim {sim:.2f} < {threshold} — face drifted from canon',
                    }
                )
        except Exception as e:
            out['error'] = str(e)[:200]
        self.doc['qc'].append(out)
        self._save()
        return out

    def qc_mask_boundary(self, tag, mask_path, image_path=None, prop_boxes=None):
        """A5 boundary gate (2026-07-30 candle incident): a generate/keep boundary must
        NEVER cut a rigid object. Checks: (1) per-prop straddle fraction |prop∩white|/|prop|
        must be <0.02 (fully kept) or >0.98 (fully generated); (2) edge density inside the
        boundary band vs frame median — high density = the boundary crosses structure.
        prop_boxes: [(name, fx0, fy0, fx1, fy1), ...]."""
        out = {'tag': tag, 'kind': 'mask_boundary', 'path': mask_path, 'checks': []}
        try:
            import numpy as np
            import cv2
            from PIL import Image

            m = np.asarray(Image.open(mask_path).convert('L'), dtype=np.uint8)
            H, W = m.shape
            white = m > 127
            for name, fx0, fy0, fx1, fy1 in prop_boxes or []:
                sub = white[int(H * fy0) : int(H * fy1), int(W * fx0) : int(W * fx1)]
                frac = float(sub.mean()) if sub.size else 0.0
                ok = frac < 0.02 or frac > 0.98
                out['checks'].append(
                    {
                        'check': f'straddle:{name}',
                        'white_frac': round(frac, 3),
                        'ok': ok,
                        'note': ''
                        if ok
                        else f'mask boundary CUTS "{name}" ({frac:.0%} in generate region) — snap fully in or out',
                    }
                )
            if image_path:
                img = np.asarray(Image.open(image_path).convert('L').resize((W, H)), dtype=np.uint8)
                edges = cv2.Canny(img, 60, 140) > 0
                band = cv2.dilate(white.astype(np.uint8), np.ones((9, 9), np.uint8)) ^ cv2.erode(
                    white.astype(np.uint8), np.ones((9, 9), np.uint8)
                )
                band = band.astype(bool)
                band_density = float(edges[band].mean()) if band.any() else 0.0
                frame_density = float(edges.mean())
                ratio = band_density / max(frame_density, 1e-4)
                ok = ratio < 2.0
                out['checks'].append(
                    {
                        'check': 'boundary_edge_density',
                        'ratio': round(ratio, 2),
                        'ok': ok,
                        'note': ''
                        if ok
                        else 'mask boundary runs through high-detail structure — reroute through flat zones',
                    }
                )
        except Exception as e:
            out['error'] = str(e)[:200]
        self.doc['qc'].append(out)
        self._save()
        return out

    def qc_semantics(self, tag, image_path, checks):
        """Comparative CLIP semantics gate (2026-07-30 smoke-ownership incident): for each
        (name, region_frac, text_a, text_b, expect_a) the region is scored against BOTH
        texts; the check passes when the expected text wins the softmax. Comparative
        scoring is far more reliable than absolute CLIP sims. Example:
            ('abel_not_smoking', (0.5,0,1,0.7), 'a boy writing with a quill pen',
             'a boy smoking a pipe', True)"""
        out = {'tag': tag, 'kind': 'semantics', 'path': image_path, 'checks': []}
        try:
            import torch
            import open_clip
            from PIL import Image

            if _CLIP['model'] is None:
                _clip_embed(Image.new('RGB', (32, 32)))  # force lazy init
            tok = open_clip.get_tokenizer('ViT-B-32')
            im = Image.open(image_path).convert('RGB')
            W, H = im.size
            for name, region, text_a, text_b, expect_a in checks:
                fx0, fy0, fx1, fy1 = region
                crop = im.crop((int(W * fx0), int(H * fy0), int(W * fx1), int(H * fy1)))
                e_img = _clip_embed(crop)
                with torch.no_grad():
                    te = _CLIP['model'].encode_text(tok([text_a, text_b]))
                    te = te / te.norm(dim=-1, keepdim=True)
                    sims = (te @ e_img).tolist()
                a_wins = sims[0] > sims[1]
                ok = a_wins == bool(expect_a)
                out['checks'].append(
                    {
                        'check': f'semantics:{name}',
                        'sim_a': round(sims[0], 3),
                        'sim_b': round(sims[1], 3),
                        'winner': text_a if a_wins else text_b,
                        'ok': ok,
                        'note': '' if ok else f'"{text_a if not expect_a else text_b}" should not win here',
                    }
                )
        except Exception as e:
            out['error'] = str(e)[:200]
        self.doc['qc'].append(out)
        self._save()
        return out
