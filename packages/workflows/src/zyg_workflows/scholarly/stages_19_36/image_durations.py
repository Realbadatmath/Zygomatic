# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Ken-Burns duration planner, lifted out of `stage_15_video_assembly`.

Each body below is the byte-for-byte range of the single file; the enclosing
`_make_*` wrapper only re-creates the closure the nested `def` used to get
from its stage function, so the inner code is unchanged down to the indent.
"""


def _make_build_image_durations(pipeline_state):
    """Build `_build_image_durations` over the stage local it closed over."""

    def _build_image_durations(img_paths, visual_tags, word_timings_raw, tts_dur):
        """
        Assign on-screen duration to each image using:
          1. Emotion curve (Murch rhythm rule) — high intensity = shorter hold
          2. Word-boundary timestamps from TTS — anchor images to spoken words
          3. Fallback: uniform distribution

        Murch timing rules:
          shock/grief/triumph (intensity >= 0.85) → 0.8–1.5 s  (punch cut)
          tension/awe         (intensity >= 0.65) → 1.5–2.5 s  (quick cut)
          unease/mystery      (intensity >= 0.45) → 2.5–3.5 s  (medium)
          calm/neutral        (intensity < 0.45)  → 3.5–6.0 s  (slow, breathing room)
        """
        import re as _re_sync
        import unicodedata as _ud

        def _norm(t):
            t = _ud.normalize('NFKD', t.lower())
            return _re_sync.sub(r'[^a-z0-9\s]', '', t).split()

        _n = len(img_paths)
        if not _n:
            return []

        # ── Get emotion curve ──────────────────────────────────────────
        _ec = pipeline_state.get('emotion_curve', [])

        # Map image slot → emotion intensity
        def _slot_intensity(slot_idx):
            if not _ec:
                return 0.2
            _ec_idx = int(slot_idx * len(_ec) / _n)
            _ec_idx = min(_ec_idx, len(_ec) - 1)
            return _ec[_ec_idx].get('intensity', 0.2)

        # ── Emotion → duration ─────────────────────────────────────────
        def _emotion_duration(intensity):
            if intensity >= 0.85:
                return 1.2  # shock / triumph — punch cut
            elif intensity >= 0.65:
                return 2.0  # tension / awe
            elif intensity >= 0.45:
                return 3.0  # unease / mystery
            else:
                return 4.5  # calm / neutral — slow hold

        if not word_timings_raw or not visual_tags:
            # Emotion-only fallback (no TTS word boundaries available)
            _raw = [_emotion_duration(_slot_intensity(i)) for i in range(_n)]
            _total = sum(_raw)
            return [round(d * tts_dur / _total, 2) for d in _raw]

        # ── TTS anchor pass ────────────────────────────────────────────
        _wt = [(w, t) for w, t in word_timings_raw if w.strip()]
        _sent_times = []
        _wt_pos = 0
        for vt in visual_tags:
            _swords = _norm(vt['sentence'])[:3]
            if not _swords:
                _sent_times.append(None)
                continue
            _matched = None
            for _wi in range(_wt_pos, min(_wt_pos + 300, len(_wt) - len(_swords))):
                if [
                    _norm(_wt[_wi + k][0])[0] if _norm(_wt[_wi + k][0]) else '' for k in range(len(_swords))
                ] == _swords:
                    _matched = _wt[_wi][1]
                    _wt_pos = _wi + len(_swords)  # advance past matched words
                    break
            _sent_times.append(_matched)

        _known = [(i, t) for i, t in enumerate(_sent_times) if t is not None]
        if not _known:
            _raw = [_emotion_duration(_slot_intensity(i)) for i in range(_n)]
            _total = sum(_raw)
            return [round(d * tts_dur / _total, 2) for d in _raw]

        if _known[0][0] > 0:
            for i in range(_known[0][0]):
                _sent_times[i] = _known[0][1]
        if _known[-1][0] < len(_sent_times) - 1:
            # Interpolate evenly across unmatched tail sentences instead of
            # pinning them all to tts_dur (which caused one image to get 647s)
            _last_ki, _last_kt = _known[-1]
            _tail_n = len(_sent_times) - 1 - _last_ki
            _tail_step = (tts_dur - _last_kt) / (_tail_n + 1)
            for i in range(_last_ki + 1, len(_sent_times)):
                _sent_times[i] = _last_kt + _tail_step * (i - _last_ki)
        for _ka in range(len(_known) - 1):
            _ia, _ta = _known[_ka]
            _ib, _tb = _known[_ka + 1]
            if _ib - _ia > 1:
                for _ii in range(_ia + 1, _ib):
                    _frac = (_ii - _ia) / (_ib - _ia)
                    _sent_times[_ii] = _ta + _frac * (_tb - _ta)

        # ── Bucket sentences into N image slots ────────────────────────
        _bucket_size = len(_sent_times) / _n
        _image_starts = []
        for _bi in range(_n):
            _idx = min(int(_bi * _bucket_size), len(_sent_times) - 1)
            _image_starts.append(_sent_times[_idx] if _sent_times[_idx] is not None else (_bi / _n * tts_dur))

        # ── Convert starts → raw durations ─────────────────────────────
        _raw_durations = []
        for _bi in range(_n):
            _start = _image_starts[_bi]
            _end = _image_starts[_bi + 1] if _bi + 1 < _n else tts_dur
            _raw_durations.append(max(0.5, _end - _start))

        # ── Apply emotion scaling on top of TTS-derived durations ──────
        # Emotion shortens or extends each slot relative to its TTS-derived baseline.
        # We scale by emotion factor but keep total == tts_dur.
        _emotion_factors = []
        for _bi in range(_n):
            _intens = _slot_intensity(_bi)
            _target = _emotion_duration(_intens)
            _baseline = _raw_durations[_bi]
            # Blend: 60% TTS baseline, 40% emotion target (so TTS sync isn't destroyed)
            _blended = _baseline * 0.6 + _target * 0.4
            _emotion_factors.append(max(0.5, _blended))

        # Normalize first so proportions are correct, then cap.
        # Capping before normalizing was pointless — normalization re-inflated
        # capped values back to 90%+ of tts_dur when tail slots had 0.5s each.
        _total = sum(_emotion_factors)
        if _total > 0:
            _emotion_factors = [d * tts_dur / _total for d in _emotion_factors]

        _max_single = (tts_dur / _n) * 4.0
        if any(d > _max_single for d in _emotion_factors):
            _emotion_factors = [min(d, _max_single) for d in _emotion_factors]
            _total2 = sum(_emotion_factors)
            if _total2 > 0:
                _emotion_factors = [d * tts_dur / _total2 for d in _emotion_factors]

        # Enforce minimum slot duration so a 1.5s dissolve doesn't swallow the image.
        # A slot must be at least max_transition_dur + 1s (= 2.5s) to be visible.
        _min_slot = 2.5
        if any(d < _min_slot for d in _emotion_factors):
            _emotion_factors = [max(d, _min_slot) for d in _emotion_factors]
            _total_min = sum(_emotion_factors)
            if _total_min > 0:
                _emotion_factors = [d * tts_dur / _total_min for d in _emotion_factors]

        return [round(max(_min_slot, d), 2) for d in _emotion_factors]

    return _build_image_durations
