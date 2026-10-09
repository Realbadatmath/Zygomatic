# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Mood pick, music + foley selection and the ffmpeg mixes."""

from __future__ import annotations

from zyg_workflows.audio_service.catalogs import (
    FOLEY_DIR,
    MUSIC_DIR,
    _EMOTION_MOOD_MAP,
    _FOLEY_CATALOG,
    _MUSICGEN_PROMPTS,
    _MUSIC_CATALOG,
    _SCENE_FOLEY_KEYWORDS,
    _TOPIC_MOOD_MAP,
    _zyg_log,
    exe,
    json,
    os,
    re,
    subprocess,
)
from zyg_workflows.audio_service.downloads import (
    _download_music_soundbible_fallback,
    _download_music_ytdlp,
    _download_soundbible,
    _extract_foley_query,
    _freesound_search,
)


def _pick_mood(topic: str, emotion: str) -> str:
    """Choose a music mood based on topic keywords and detected emotion."""
    combined = (topic + ' ' + emotion).lower()
    # Emotion override first
    for key, mood in _EMOTION_MOOD_MAP.items():
        if key in combined:
            return mood
    # Topic keyword matching
    for keywords, mood in _TOPIC_MOOD_MAP:
        for kw in keywords:
            if kw in combined:
                return mood
    return 'epic'


_VALID_MOODS: frozenset[str] = frozenset(_MUSICGEN_PROMPTS)


def get_music_for_topic(
    topic: str,
    emotion: str = 'neutral',
    out_dir: str | None = None,
    duration_s: int = 30,
    *,
    music_mood: str = '',
    log_fn=None,
) -> str | None:
    """Return path to a background music track appropriate for the given topic/emotion.

    If ``music_mood`` is provided (e.g. Claude-suggested) and is a valid mood key
    it is used directly, bypassing the keyword-scan ``_pick_mood`` heuristic.

    Priority:
      1. ACE-Step 1.5 (local AI, MIT weights) — unique track generated per run
         (replaced MusicGen 2026-08-09: facebook/musicgen-small weights are
         CC-BY-NC — banned from published audio by our own licence policy)
      2. yt-dlp YouTube download (royalty-free/CC)
      3. soundbible.com ambient loop (CC0, always works)

    Returns None only if all three tiers fail.
    """

    def _notify(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    if music_mood and music_mood in _VALID_MOODS:
        mood = music_mood
        _notify(f'BGM: using Claude-suggested mood: {mood}')
    else:
        mood = _pick_mood(topic, emotion)
        _notify(f'BGM: mood derived from keyword scan: {mood}')
    prompt = _MUSICGEN_PROMPTS.get(mood, _MUSICGEN_PROMPTS['epic'])

    # ── Tier 1: ACE-Step local AI ─────────────────────────────────────────
    # Cache name is ace_{mood}.mp3 — deliberately distinct from the retired
    # musicgen_{mood}.mp3 so stale NC-generated tracks can never be served.
    try:
        from zyg_workflows import ace_step_service as _ace
        import random as _rng

        if _ace.is_available():
            music_dir = out_dir or MUSIC_DIR
            os.makedirs(music_dir, exist_ok=True)
            mg_path = os.path.join(music_dir, f'ace_{mood}.mp3')
            _notify(f'BGM: generating AI music via ACE-Step ({mood}, {duration_s}s)…')
            _seed = _rng.randint(0, 2**31 - 1)
            if _ace.generate(prompt, mg_path, duration_s=duration_s, seed=_seed, log_fn=log_fn):
                return mg_path
            _notify('BGM: ACE-Step failed — falling back to yt-dlp')
        else:
            _notify('BGM: ACE-Step not available — using yt-dlp')
    except ImportError:
        _notify('BGM: ace_step_service not found — using yt-dlp')
    except Exception as _mge:
        _notify(f'BGM: ACE-Step error ({_mge}) — using yt-dlp')

    # ── Tier 2: yt-dlp YouTube ────────────────────────────────────────────
    tracks = _MUSIC_CATALOG.get(mood, _MUSIC_CATALOG['epic'])
    for fname, yt_url, _sb_fallback_id in tracks:
        dest = os.path.join(MUSIC_DIR, fname)
        if os.path.exists(dest) and os.path.getsize(dest) > 10000:
            _notify(f'BGM: using cached yt-dlp track {fname} ({mood})')
            return dest
        _notify(f'BGM: downloading yt-dlp track ({mood}): {fname}…')
        if _download_music_ytdlp(yt_url, dest, log_fn=log_fn):
            return dest

    # ── Tier 3: soundbible ambient fallback ──────────────────────────────
    for fname, _yt_url, sb_fallback_id in tracks:
        dest = os.path.join(MUSIC_DIR, fname)
        _notify(f'BGM: yt-dlp failed — using soundbible ambient fallback for {mood}')
        if _download_music_soundbible_fallback(sb_fallback_id, dest, log_fn=log_fn):
            return dest

    # Last resort: any already-cached track
    try:
        existing = [
            os.path.join(MUSIC_DIR, f)
            for f in os.listdir(MUSIC_DIR)
            if f.endswith('.mp3') and os.path.getsize(os.path.join(MUSIC_DIR, f)) > 10000
        ]
        if existing:
            _notify(f'BGM: using cached fallback track {os.path.basename(existing[0])}')
            return existing[0]
    except Exception as _exc:
        _zyg_log.warning('cached music scan failed, no fallback track: %s', _exc)

    _notify('BGM: all tiers failed — no background music')
    return None


def get_foley_for_scene(
    description: str,
    max_foley: int = 2,
    *,
    log_fn=None,
) -> list[tuple[str, float]]:
    """Return [(path, volume), ...] of foley SFX matching the scene description.

    Tier pipeline — each tier fills remaining slots before falling through:

    Tier 1 — DISABLED 2026-08-09: generative foley (AudioGen) removed — its
        facebook/audiogen-medium weights are CC-BY-NC. Slot reserved for a
        licence-clean V2A engine (Foley-Omni, MIT) once it passes QC.

    Tier 2 — Freesound API (530k+ Creative Commons recordings)
        Requires FREESOUND_API_KEY in environment.

    Tier 3 — Soundbible hardcoded catalog (CC0, offline, always available)
        Keyword-match fallback using the static _FOLEY_CATALOG entries.
    """

    def _notify(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    desc_lower = description.lower()
    result: list[tuple[str, float]] = []

    _ambient = {'wind', 'ocean_waves', 'rain', 'nature_birds', 'footsteps', 'frogs', 'cat_meow', 'crickets', 'bee_buzz'}

    # Score all categories against the scene description
    scored: list[tuple[int, str]] = []
    for category, keywords in _SCENE_FOLEY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in desc_lower)
        if score > 0:
            scored.append((score, category))
    scored.sort(key=lambda x: x[0], reverse=True)
    top_categories = [cat for _, cat in scored][:max_foley]

    slots_remaining = max_foley
    ag_succeeded: set[str] = set()

    # ── Tier 1: generative foley DISABLED 2026-08-09 (licence) ────────────
    # AudioGen (facebook/audiogen-medium) carries CC-BY-NC weights — banned
    # from published audio by our own policy. Slot stays empty until a clean
    # engine (Foley-Omni, MIT — pending per-file aux licence verification)
    # passes QC; Freesound/soundbible tiers below cover foley meanwhile.
    if top_categories:
        _notify('Foley: generative tier disabled (AudioGen CC-BY-NC licence, 2026-08-09) — using library tiers')

    # ── Tier 2: Freesound API ─────────────────────────────────────────────
    if slots_remaining > 0 and os.environ.get('FREESOUND_API_KEY', '').strip():
        query = _extract_foley_query(description)
        if query:
            cache_name = 'fs_' + re.sub(r'\W+', '_', query)[:40].strip('_') + '.mp3'
            dest = os.path.join(FOLEY_DIR, cache_name)
            if _freesound_search(query, dest, log_fn=log_fn):
                result.append((dest, 0.28))
                slots_remaining -= 1
        else:
            _notify('Foley: could not extract query from scene description')

    # ── Tier 3: Soundbible hardcoded catalog ──────────────────────────────
    for category in top_categories:
        if slots_remaining <= 0:
            break
        if category in ag_succeeded:
            continue  # already covered by AudioGen
        if category not in _FOLEY_CATALOG:
            continue
        fname, sb_id = _FOLEY_CATALOG[category]
        dest = os.path.join(FOLEY_DIR, fname)
        if _download_soundbible(sb_id, dest, log_fn=log_fn):
            vol = 0.20 if category in _ambient else 0.30
            result.append((dest, vol))
            slots_remaining -= 1

    if not result:
        _notify('Foley: all tiers failed — no SFX for this scene')
    return result


def mix_foley_into_audio(
    tts_path: str,
    foley_list: list[tuple[str, float]],
    out_path: str,
    tts_dur: float,
    *,
    log_fn=None,
) -> bool:
    """Mix foley SFX tracks into TTS audio. Foley is trimmed/looped to tts_dur.

    Returns True on success. Falls back to copying tts_path → out_path on any failure.
    """

    def _notify(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    if not foley_list or not os.path.exists(tts_path):
        if os.path.exists(tts_path):
            import shutil

            shutil.copy2(tts_path, out_path)
        return False

    try:
        # Build filter_complex: TTS at full volume + each foley trimmed/looped to tts_dur
        inputs = ['-i', tts_path]
        filter_parts: list[str] = ['[0:a]volume=1.0[tts]']
        labels: list[str] = ['[tts]']

        for idx, (fpath, vol) in enumerate(foley_list, 1):
            inputs += ['-i', fpath]
            label = f'[sfx{idx}]'
            # Loop + trim foley to match TTS duration
            filter_parts.append(f'[{idx}:a]aloop=loop=-1:size=999999,atrim=0:{tts_dur:.3f},volume={vol:.2f}{label}')
            labels.append(label)

        n = len(labels)
        amix = f'{"".join(labels)}amix=inputs={n}:duration=first:dropout_transition=0[out]'
        filter_complex = ';'.join(filter_parts) + ';' + amix

        cmd = (
            [exe('ffmpeg'), '-y']
            + inputs
            + ['-filter_complex', filter_complex, '-map', '[out]', '-c:a', 'libmp3lame', '-q:a', '4', out_path]
        )
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
            _notify(f'Foley mixed into audio ({len(foley_list)} track(s))')
            return True
        else:
            err = (r.stderr or b'').decode('utf-8', errors='replace')[-300:]
            _notify(f'⚠ Foley mix failed: {err}')
    except Exception as e:
        _notify(f'⚠ Foley mix error: {e}')

    # Fallback: just copy original TTS
    import shutil

    shutil.copy2(tts_path, out_path)
    return False


def mix_foley_into_video(
    video_path: str,
    foley_list: list[tuple[str, float]],
    out_path: str,
    duration_s: float,
    *,
    log_fn=None,
) -> bool:
    """Mix foley SFX directly into a video (used when there is no TTS narration).

    If the video already has an audio stream, foley is mixed under it at the
    specified volumes.  If not, foley becomes the sole audio track.
    Returns True on success.
    """

    def _notify(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    if not foley_list or not os.path.exists(video_path):
        return False

    try:
        probe_a = subprocess.run(
            [
                exe('ffprobe'),
                '-v',
                'quiet',
                '-print_format',
                'json',
                '-show_streams',
                '-select_streams',
                'a',
                video_path,
            ],
            capture_output=True,
            timeout=15,
        )
        has_audio = bool(json.loads(probe_a.stdout).get('streams'))
    except Exception:
        has_audio = False

    try:
        inputs: list[str] = ['-i', video_path]
        filter_parts: list[str] = []
        labels: list[str] = []

        if has_audio:
            filter_parts.append('[0:a]volume=1.0[orig]')
            labels.append('[orig]')

        for idx, (fpath, vol) in enumerate(foley_list, 1):
            inputs += ['-i', fpath]
            label = f'[sfx{idx}]'
            filter_parts.append(f'[{idx}:a]aloop=loop=-1:size=999999,atrim=0:{duration_s:.3f},volume={vol:.2f}{label}')
            labels.append(label)

        n = len(labels)
        amix = f'{"".join(labels)}amix=inputs={n}:duration=first:dropout_transition=0[out]'
        filter_complex = ';'.join(filter_parts) + ';' + amix

        cmd = (
            [exe('ffmpeg'), '-y']
            + inputs
            + [
                '-filter_complex',
                filter_complex,
                '-map',
                '0:v:0',
                '-map',
                '[out]',
                '-c:v',
                'copy',
                '-c:a',
                'aac',
                '-b:a',
                '128k',
                out_path,
            ]
        )
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
            _notify(f'Foley mixed into video ({len(foley_list)} track(s))')
            return True
        err = (r.stderr or b'').decode('utf-8', errors='replace')[-300:]
        _notify(f'⚠ Foley-video mix failed: {err}')
    except Exception as e:
        _notify(f'⚠ Foley-video mix error: {e}')
    return False


def mix_bgm_into_video(
    video_path: str,
    music_path: str,
    out_path: str,
    music_vol: float = 0.12,
    *,
    log_fn=None,
) -> bool:
    """Mix background music into a video at music_vol (0.0–1.0) under the original audio.

    Music is looped to match video duration and faded out over the last 3 seconds.
    Returns True on success. Does NOT modify video_path on failure.
    """

    def _notify(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    if not os.path.exists(video_path) or not os.path.exists(music_path):
        _notify('⚠ BGM mix skipped — video or music file missing')
        return False

    try:
        # Probe video duration so we can trim music precisely
        probe = subprocess.run(
            [exe('ffprobe'), '-v', 'quiet', '-print_format', 'json', '-show_format', video_path],
            capture_output=True,
            timeout=30,
        )
        import json as _json

        dur = float(_json.loads(probe.stdout).get('format', {}).get('duration', 0)) or 60.0
        fade_start = max(dur - 3.0, dur * 0.9)

        # Probe whether video has an audio stream (narration may be disabled)
        probe_a = subprocess.run(
            [
                exe('ffprobe'),
                '-v',
                'quiet',
                '-print_format',
                'json',
                '-show_streams',
                '-select_streams',
                'a',
                video_path,
            ],
            capture_output=True,
            timeout=30,
        )
        _has_audio = bool(_json.loads(probe_a.stdout).get('streams', []))

        if _has_audio:
            # Mix music under existing audio track
            filter_complex = (
                f'[0:a]volume=1.0[orig];'
                f'[1:a]aloop=loop=-1:size=999999,'
                f'atrim=0:{dur:.3f},'
                f'volume={music_vol:.2f},'
                f'afade=t=in:st=0:d=2,'
                f'afade=t=out:st={fade_start:.3f}:d=3'
                f'[bgm];'
                f'[orig][bgm]amix=inputs=2:duration=first:dropout_transition=0[out]'
            )
            cmd = [
                'ffmpeg',
                '-y',
                '-i',
                video_path,
                '-i',
                music_path,
                '-filter_complex',
                filter_complex,
                '-map',
                '0:v',
                '-map',
                '[out]',
                '-c:v',
                'copy',
                '-c:a',
                'aac',
                '-b:a',
                '192k',
                '-movflags',
                '+faststart',
                out_path,
            ]
        else:
            # No audio in video (e.g. narration disabled) — add music as sole audio track
            _notify('Video has no audio stream — adding music as sole audio track')
            filter_complex = (
                f'[1:a]aloop=loop=-1:size=999999,'
                f'atrim=0:{dur:.3f},'
                f'asetpts=PTS-STARTPTS,'
                f'volume={music_vol * 3:.2f},'
                f'afade=t=in:st=0:d=2,'
                f'afade=t=out:st={fade_start:.3f}:d=3'
                f'[bgm]'
            )
            cmd = [
                'ffmpeg',
                '-y',
                '-i',
                video_path,
                '-i',
                music_path,
                '-filter_complex',
                filter_complex,
                '-map',
                '0:v',
                '-map',
                '[bgm]',
                '-c:v',
                'copy',
                '-c:a',
                'aac',
                '-b:a',
                '192k',
                '-movflags',
                '+faststart',
                out_path,
            ]
        r = subprocess.run(cmd, capture_output=True, timeout=600)
        if r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 10000:
            _notify(
                f'✅ BGM mixed in at {int(music_vol * 100)}% volume ({os.path.getsize(out_path) // 1024 // 1024}MB)'
            )
            return True
        else:
            err = (r.stderr or b'').decode('utf-8', errors='replace')[-400:]
            _notify(f'⚠ BGM mix failed (rc={r.returncode}): {err}')
    except Exception as e:
        _notify(f'⚠ BGM mix error: {e}')

    return False
