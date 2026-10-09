# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""DebugRun, part 2 of 3: the A-tier clip extensions — per-region tracking,
camera motion, flicker/seam indices, qc_clip and its identity sub-check."""

import os
from zyg_workflows.bin import exe
from .common import _zyg_log
from .run_record import _DebugRunRecord


class _DebugRunClipQC(_DebugRunRecord):
    # ── A-tier extensions (2026-07-29 external QC research) ──────────────────
    def _track_motion(self, arrs_gray, regions_px):
        """A3: PyrLK point-track NET displacement per region — shimmer integrates to ~0,
        real motion accumulates. The shimmer-proof freeze gate."""
        import cv2
        import numpy as np

        out = {}
        f0 = arrs_gray[0].astype('uint8')
        for name, (ys, xs) in regions_px.items():
            sub0 = f0[ys, xs]
            pts = cv2.goodFeaturesToTrack(sub0, maxCorners=60, qualityLevel=0.01, minDistance=8)
            if pts is None or len(pts) < 5:
                out[name] = None
                continue
            pts = pts + np.array([[[xs.start, ys.start]]], dtype=np.float32)
            cur = pts.copy()
            total = np.zeros(len(pts), dtype=np.float64)
            prev = f0
            for a in arrs_gray[1:]:
                a8 = a.astype('uint8')
                nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev, a8, cur, None, winSize=(21, 21), maxLevel=2)
                if nxt is None:
                    break
                ok = st.reshape(-1) == 1
                d = np.linalg.norm((nxt - cur).reshape(-1, 2), axis=1)
                total[ok] += d[ok]
                cur = nxt
                prev = a8
            # NET displacement start→end (not path length) separates drift from shimmer
            net = np.linalg.norm((cur - pts).reshape(-1, 2), axis=1)
            out[name] = {
                'net_px_median': round(float(np.median(net)), 2),
                'path_px_median': round(float(np.median(total)), 2),
            }
        return out

    def _camera_motion(self, arrs_gray):
        """A4: global affine fit first→last frame — classify static/pan/zoom + the
        non-rigid residual (set churn that camera motion cannot explain)."""
        import cv2
        import numpy as np

        f0 = arrs_gray[0].astype('uint8')
        fN = arrs_gray[-1].astype('uint8')
        warp = np.eye(2, 3, dtype=np.float32)
        crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 80, 1e-5)
        try:
            cv2.findTransformECC(f0, fN, warp, cv2.MOTION_AFFINE, crit, None, 3)
        except cv2.error:
            return {'classify': 'unknown'}
        zoom = (abs(float(warp[0, 0]) - 1.0) + abs(float(warp[1, 1]) - 1.0)) / 2
        pan = float(np.hypot(warp[0, 2], warp[1, 2]))
        aligned = cv2.warpAffine(
            fN, cv2.invertAffineTransform(warp), (f0.shape[1], f0.shape[0]), borderMode=cv2.BORDER_REPLICATE
        )
        residual = float(np.abs(aligned.astype(float) - f0.astype(float)).mean())
        cls = 'static'
        if zoom > 0.015:
            cls = 'zoom'
        elif pan > 6.0:
            cls = 'pan'
        return {
            'classify': cls,
            'zoom': round(zoom, 4),
            'pan_px': round(pan, 1),
            'nonrigid_residual': round(residual, 2),
        }

    def _flicker_index(self, arrs_gray):
        """A6: block-wise temporal sign-flip rate — painterly 'boiling' detector."""
        import numpy as np

        deltas = np.stack([arrs_gray[i + 1] - arrs_gray[i] for i in range(len(arrs_gray) - 1)])
        H, W = arrs_gray[0].shape
        bh, bw = H // 12, W // 12
        blocks = deltas[:, : bh * 12, : bw * 12].reshape(len(deltas), 12, bh, 12, bw).mean(axis=(2, 4))
        sign = np.sign(np.where(np.abs(blocks) < 0.15, 0, blocks))
        flips = (sign[1:] * sign[:-1] < 0).mean()
        return round(float(flips), 3)

    def _seam_spikes(self, arrs_gray):
        """A5: chain-join pop detector — 2nd-difference spikes of the global luma track."""
        import numpy as np

        m = np.array([a.mean() for a in arrs_gray])
        if len(m) < 6:
            return []
        d2 = np.abs(np.diff(m, 2))
        thr = d2.mean() + 4 * d2.std()
        # ignore the first 2 frames — the anchor-snap/RIFE boundary is a benign pop
        return [int(i + 1) for i in np.where(d2 > max(thr, 0.8))[0] if i + 1 > 2][:8]

    def qc_clip(
        self,
        tag,
        clip_path,
        char_regions=None,
        still_path=None,
        char_motion_min=1.5,
        bg_motion_max=1.0,
        identity_chars=None,
        identity_style='arcane',
        identity_stride=None,
    ):
        """Clip gate with HONEST motion measurement: per-region mean consecutive-frame
        delta. Character regions must MOVE (>= char_motion_min); background must NOT
        (< bg_motion_max, else camera drift / set churn). Plus color drift + set drift
        vs the anchor still when provided.

        identity_chars (2026-09-02): who is supposed to be IN this clip —
        ['char_id', ...] or [{'char_id', 'style', 'roi'}, ...]. Every check above
        measures whether SOMETHING moved in a region; none of them measures WHO it
        was. The per-frame identity instrument does, and its result lands in
        out['identity'] and in identity_clip.json next to the clip.

        It deliberately does NOT enter out['checks']: that list is the run's
        pass/fail ledger, and a metric benched for the first time today has not
        earned a vote in it. Advisory means advisory."""
        out = {'tag': tag, 'kind': 'clip', 'path': clip_path, 'checks': []}
        try:
            import glob
            import subprocess
            import tempfile
            import numpy as np
            from PIL import Image

            td = tempfile.mkdtemp(prefix='qc_')
            subprocess.run(
                [
                    exe('ffmpeg'),
                    '-y',
                    '-loglevel',
                    'error',
                    '-i',
                    clip_path,
                    '-vf',
                    'scale=640:-1',
                    '-vsync',
                    '0',
                    td + '/f_%04d.png',
                ],
                check=True,
            )
            frames = sorted(glob.glob(td + '/f_*.png'))[::2]
            arrs = [np.asarray(Image.open(f).convert('L'), dtype=float) for f in frames]
            rgb0 = np.asarray(Image.open(frames[0]).convert('RGB'), dtype=float)
            rgbN = np.asarray(Image.open(frames[-1]).convert('RGB'), dtype=float)
            H, W = arrs[0].shape
            regions = list(char_regions or [])

            # background = everything is approximated by the frame border strips
            def _reg(fx0, fy0, fx1, fy1):
                return (slice(int(H * fy0), int(H * fy1)), slice(int(W * fx0), int(W * fx1)))

            for name, fx0, fy0, fx1, fy1 in regions:
                rg = _reg(fx0, fy0, fx1, fy1)
                ds = [float(np.abs(arrs[i + 1][rg] - arrs[i][rg]).mean()) for i in range(len(arrs) - 1)]
                m = float(np.mean(ds))
                out['checks'].append(
                    {
                        'check': f'motion:{name}',
                        'mean_delta': round(m, 2),
                        'ok': m >= char_motion_min,
                        'note': ''
                        if m >= char_motion_min
                        else f'delta {m:.2f} < {char_motion_min} — REGION IS STATIC (frozen)',
                    }
                )
            bg = _reg(0.0, 0.0, 1.0, 0.12)  # top strip ≈ set/背景
            ds = [float(np.abs(arrs[i + 1][bg] - arrs[i][bg]).mean()) for i in range(len(arrs) - 1)]
            mbg = float(np.mean(ds))
            out['checks'].append(
                {
                    'check': 'set_stability',
                    'mean_delta': round(mbg, 2),
                    'ok': mbg < bg_motion_max,
                    'note': '' if mbg < bg_motion_max else f'background delta {mbg:.2f} — camera drift or set churn',
                }
            )
            # A3: shimmer-proof point-track freeze gate per character region
            try:
                regions_px = {name: _reg(fx0, fy0, fx1, fy1) for (name, fx0, fy0, fx1, fy1) in regions}
                tracks = self._track_motion(arrs, regions_px)
                for name, t in tracks.items():
                    if t is None:
                        continue
                    moved = t['path_px_median'] >= 3.0
                    out['checks'].append(
                        {
                            'check': f'track:{name}',
                            **t,
                            'ok': moved,
                            'note': ''
                            if moved
                            else f'tracked points barely moved ({t["path_px_median"]}px path) — frozen',
                        }
                    )
            except Exception as e:
                # ok=None, NOT True. A gate that could not look must not report
                # green: this line spent months turning "the tracker crashed"
                # into a passing aliveness check.
                out['checks'].append({'check': 'track', 'ok': None, 'measured': False, 'note': f'skipped: {e}'[:120]})
            # A4: camera-motion classification + non-rigid churn residual measured on the
            # BACKGROUND ONLY (2026-07-29 calibration: whole-frame residual counted the
            # characters' own motion as 'set churn' and false-failed lively clips)
            try:
                cam = self._camera_motion(arrs)
                is_static = cam.get('classify') == 'static'
                out['checks'].append(
                    {
                        'check': 'camera_motion',
                        **cam,
                        'ok': is_static,
                        'note': ''
                        if is_static
                        else f'camera {cam.get("classify")} detected (zoom {cam.get("zoom")}, pan {cam.get("pan_px")}px)',
                    }
                )
                res = cam.get('nonrigid_residual')
                if res is not None:
                    bg_mask = np.ones((H, W), dtype=bool)
                    for _nm, fx0, fy0, fx1, fy1 in regions:
                        bg_mask[int(H * fy0) : int(H * fy1), int(W * fx0) : int(W * fx1)] = False
                    if bg_mask.any():
                        bg_res = float(np.abs(arrs[-1][bg_mask] - arrs[0][bg_mask]).mean())
                    else:
                        bg_res = res
                    # illumination-invariant STRUCTURE churn (2026-07-29 calibration): live
                    # light sources (candle flicker) re-light the set every frame, which is
                    # intended — only re-DRAWN structure (edges moving) is a defect. Compare
                    # Sobel gradient magnitude instead of raw luma.
                    import cv2 as _cv2

                    def _grad(a):
                        a = a.astype('float32')
                        gx = _cv2.Sobel(a, _cv2.CV_32F, 1, 0, ksize=3)
                        gy = _cv2.Sobel(a, _cv2.CV_32F, 0, 1, ksize=3)
                        return np.sqrt(gx * gx + gy * gy)

                    g0, gN = _grad(arrs[0]), _grad(arrs[-1])
                    struct = float(np.abs(gN[bg_mask] - g0[bg_mask]).mean()) if bg_mask.any() else 0.0
                    out['checks'].append(
                        {
                            'check': 'set_churn_residual',
                            'bg_luma': round(bg_res, 2),
                            'bg_structure': round(struct, 2),
                            'whole_frame': res,
                            'ok': struct < 30.0,
                            'note': ('' if struct < 30.0 else 'background STRUCTURE re-drawn (churn) — not just re-lit')
                            + ('' if bg_res < 12.0 else f' | luma delta {bg_res:.0f} (light-play, informational)'),
                        }
                    )
            except Exception as _exc:
                _zyg_log.warning('set-churn residual check failed, it is absent from the verdict: %s', _exc)
            # A6 flicker + A5 chain-seam pops (informational thresholds)
            try:
                fl = self._flicker_index(arrs)
                out['checks'].append(
                    {
                        'check': 'flicker_index',
                        'value': fl,
                        'ok': fl < 0.35,
                        'note': '' if fl < 0.35 else 'painterly boiling / flicker',
                    }
                )
                seams = self._seam_spikes(arrs)
                out['checks'].append(
                    {
                        'check': 'chain_seams',
                        'frames': seams,
                        'ok': not seams,
                        'note': '' if not seams else f'luma pops at frame(s) {seams}',
                    }
                )
            except Exception as _exc:
                _zyg_log.warning('flicker/chain-seam checks failed, they are absent from the verdict: %s', _exc)
            # color drift start→end
            cdrift = float(np.abs(rgbN.mean(axis=(0, 1)) - rgb0.mean(axis=(0, 1))).mean())
            out['checks'].append(
                {
                    'check': 'color_drift',
                    'delta': round(cdrift, 2),
                    'ok': cdrift < 6.0,
                    'note': '' if cdrift < 6.0 else 'global color creep',
                }
            )
            if still_path and os.path.isfile(still_path):
                sarr = np.asarray(Image.open(still_path).convert('L').resize((W, H)), dtype=float)
                sd = float(np.abs(arrs[-1] - sarr).mean())
                out['checks'].append(
                    {'check': 'anchor_fidelity_end', 'delta': round(sd, 2), 'ok': True, 'note': 'informational'}
                )
        except Exception as e:
            out['error'] = str(e)[:200]
        # ── WHO is in this clip (advisory, 2026-09-02) ────────────────────────
        try:
            out['identity'] = self._qc_clip_identity(clip_path, identity_chars, identity_style, identity_stride)
        except Exception as e:
            out['identity'] = {'ok': None, 'error': f'{type(e).__name__}: {e}'}
        # 2026-09-03: promote the identity result into out['checks'] so it reaches
        # the verdict, the ledger and the report table. 'identity_clip' is NOT
        # registered in qc_contract, so mode_for() returns SHADOW and finish()
        # cannot let it flip verdict.ok. Do not register it.
        try:
            chk = self._identity_check(out.get('identity'))
            if chk is not None:
                out['checks'].append(chk)
        except Exception as _exc:
            _zyg_log.debug('advisory identity check not promoted into the verdict: %s', _exc)
        self.doc['qc'].append(out)
        self._save()
        return out

    @staticmethod
    def _identity_check(ident):
        """The slim identity result as one recorded check, or None when there is
        nothing measured to record. Advisory by construction: 'identity_clip' has
        no qc_contract entry, so it lands in shadow."""
        if not isinstance(ident, dict):
            return None
        if not ident.get('measured') or ident.get('ok') is None:
            return None
        per = ident.get('per_char') or {}
        row = per[next(iter(per))] if len(per) == 1 else {}
        chk = {
            'check': 'identity_clip',
            'ok': bool(ident.get('ok')),
            'cosine': row.get('cosine'),
            'cosine_p10': row.get('cosine_p10'),
            'pass_frac': row.get('pass_frac'),
            'floor': row.get('floor'),
            'note': 'per-frame identity (advisory; unregistered => shadow)',
        }
        if len(per) != 1:
            # more than one character (or none resolved): carry the per-character
            # cosines instead of pretending a single number describes the clip
            chk['chars'] = {cid: r.get('cosine') for cid, r in per.items()}
        return chk

    def _qc_clip_identity(self, clip_path, identity_chars, style, stride):
        """Per-frame identity over the finished clip. Fail-safe and non-blocking:
        any problem returns a reason, never an exception into the QC path."""
        if not identity_chars:
            return {'ok': None, 'reason': 'no_identity_chars_given', 'measured': False}
        try:
            from zyg_workflows import identity_bank as _ib
        except Exception as e:
            return {'ok': None, 'reason': f'identity_bank unavailable: {e}', 'measured': False}
        if not _ib.enabled():
            return {'ok': None, 'reason': 'disabled (ZYG_IDENTITY_CLIP=0)', 'measured': False}
        chars = []
        for c in identity_chars:
            chars.append(dict(c) if isinstance(c, dict) else {'char_id': c})
        res = _ib.score_run(
            os.path.dirname(os.path.abspath(clip_path)),
            chars=chars,
            style_profile=style,
            clips=[clip_path],
            stride=stride,
            log_fn=self.note if hasattr(self, 'note') else None,
            run_id=getattr(self, 'run_id', None),
        )
        slim = {
            'ok': res.get('ok'),
            'measured': True,
            'advisory': True,
            'reason': res.get('reason'),
            'chars': res.get('chars'),
            'sidecar': (res.get('clips') or [{}])[0].get('sidecar'),
            'per_char': {},
        }
        for entry in res.get('clips', []):
            for cid, r in (entry.get('results') or {}).items():
                slim['per_char'][cid] = {
                    k: r.get(k)
                    for k in (
                        'ok',
                        'cosine',
                        'cosine_min',
                        'cosine_p10',
                        'cosine_median',
                        'cosine_max',
                        'spread',
                        'spread_alarm',
                        'pass_frac',
                        'found',
                        'sampled',
                        'ledger',
                        'backend',
                        'floor',
                        'reason',
                        'z',
                    )
                }
        return slim
