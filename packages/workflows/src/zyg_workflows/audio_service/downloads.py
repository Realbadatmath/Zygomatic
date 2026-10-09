# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Soundbible / yt-dlp / Freesound asset acquisition."""

from __future__ import annotations

from zyg_workflows.audio_service.catalogs import _YTDLP, _zyg_log, exe, json, os, re, subprocess, urllib


def _download_soundbible(sb_id: str, dest_path: str, log_fn=None) -> bool:
    """Download a soundbible.com sound by numeric ID. Returns True on success."""

    def _notify(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 3000:
        return True  # already cached

    url = f'https://soundbible.com/grab.php?id={sb_id}&type=mp3'
    tmp = dest_path + '.tmp'
    try:
        r = subprocess.run(
            [exe('curl'), '-sL', '--max-time', '20', '-A', 'Mozilla/5.0', '-o', tmp, url],
            capture_output=True,
            timeout=30,
        )
        if r.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 3000:
            # Verify it's an actual audio file (not an HTML error page)
            probe = subprocess.run(
                [exe('ffprobe'), '-v', 'quiet', '-show_format', tmp],
                capture_output=True,
                timeout=10,
            )
            if probe.returncode == 0:
                os.replace(tmp, dest_path)
                sz = os.path.getsize(dest_path) // 1024
                _notify(f'✅ SFX {os.path.basename(dest_path)} ({sz}KB)')
                return True
        _notify(f'⚠ SFX download failed: {os.path.basename(dest_path)} (id={sb_id})')
    except Exception as e:
        _notify(f'⚠ SFX download error: {e}')
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError as _exc:
                _zyg_log.debug('temporary download removal skipped: %s', _exc)
    return False


def _download_music_ytdlp(youtube_url: str, dest_path: str, log_fn=None) -> bool:
    """Download audio from YouTube using yt-dlp. Returns True on success.

    Downloads as mp3 at medium quality (~128kbps) to keep file sizes reasonable.
    Times out after 90 seconds to avoid blocking the pipeline.
    """

    def _notify(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 10000:
        return True

    # yt-dlp outputs to <dest_path> but needs explicit path without extension
    base_noext = dest_path.rsplit('.', 1)[0]
    try:
        r = subprocess.run(
            [
                _YTDLP,
                '--extract-audio',
                '--audio-format',
                'mp3',
                '--audio-quality',
                '5',
                '--quiet',
                '--no-warnings',
                '--max-filesize',
                '30M',  # cap at 30MB to avoid huge files
                '-o',
                base_noext + '.%(ext)s',
                youtube_url,
            ],
            capture_output=True,
            timeout=120,
        )
        if r.returncode == 0 and os.path.exists(dest_path) and os.path.getsize(dest_path) > 10000:
            sz = os.path.getsize(dest_path) // 1024 // 1024
            _notify(f'✅ Music downloaded: {os.path.basename(dest_path)} ({sz}MB)')
            return True
        elif r.returncode == 0:
            _notify(f'⚠ yt-dlp output file missing for {os.path.basename(dest_path)}')
        else:
            stderr = (r.stderr or b'').decode('utf-8', errors='replace')[-200:]
            _notify(f'⚠ yt-dlp failed for {os.path.basename(dest_path)}: {stderr}')
    except subprocess.TimeoutExpired:
        _notify(f'⚠ yt-dlp timeout for {os.path.basename(dest_path)}')
    except Exception as e:
        _notify(f'⚠ Music download error: {e}')
    return False


def _download_music_soundbible_fallback(sb_id: str, dest_path: str, log_fn=None) -> bool:
    """Soundbible fallback for music: download an ambient loop track."""
    return _download_soundbible(sb_id, dest_path, log_fn=log_fn)


# ── Foley stop-words (filtered out when building Freesound search queries) ───
_FOLEY_STOP_WORDS: frozenset[str] = frozenset(
    [
        'a',
        'an',
        'the',
        'and',
        'or',
        'but',
        'in',
        'on',
        'at',
        'to',
        'for',
        'of',
        'with',
        'as',
        'is',
        'are',
        'was',
        'were',
        'be',
        'been',
        'being',
        'have',
        'has',
        'had',
        'do',
        'does',
        'did',
        'will',
        'would',
        'could',
        'should',
        'may',
        'might',
        'shall',
        'can',
        'not',
        'no',
        'nor',
        'so',
        'yet',
        'both',
        'either',
        'neither',
        'each',
        'every',
        'all',
        'any',
        'few',
        'more',
        'most',
        'other',
        'some',
        'such',
        'than',
        'too',
        'very',
        'just',
        'its',
        'it',
        'this',
        'that',
        'these',
        'those',
        'their',
        'they',
        'them',
        'there',
        'then',
        'when',
        'where',
        'which',
        'who',
        'how',
        'what',
        'up',
        'down',
        'out',
        'into',
        'over',
        'under',
        'again',
        'through',
        'during',
        'before',
        'after',
        'above',
        'below',
        'between',
        'shows',
        'scene',
        'shows',
        'depicts',
        'revealing',
        'while',
        'from',
        'across',
    ]
)


def _extract_foley_query(description: str, max_words: int = 3) -> str:
    """Extract the most scene-relevant sound keywords for a Freesound search.

    Strips stop-words, punctuation, and short filler words, returning a 2-3
    word query that focuses on what *sounds* in the scene (not visual details).
    Example: "a lion stalks through tall savannah grass at dusk" → "lion savannah grass"
    """
    words = re.sub(r'[^\w\s]', ' ', description.lower()).split()
    meaningful = [w for w in words if w not in _FOLEY_STOP_WORDS and len(w) > 3]
    return ' '.join(meaningful[:max_words])


def _freesound_search(query: str, dest_path: str, *, duration_max: int = 15, log_fn=None) -> bool:
    """Search Freesound.org for a sound matching `query` and download it.

    Requires FREESOUND_API_KEY in environment (free account at freesound.org/apiv2/apply/).
    Results are cached: if dest_path already exists and is valid, returns True immediately.
    Downloads the HQ MP3 preview (~128kbps, ≤30 s) — no OAuth needed for previews.
    """

    def _notify(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    api_key = os.environ.get('FREESOUND_API_KEY', '').strip()
    if not api_key:
        return False  # key not configured — skip silently

    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 3000:
        return True  # already cached

    try:
        params = urllib.parse.urlencode(
            {
                'query': query,
                'fields': 'id,name,previews,duration',
                'filter': f'duration:[0.5 TO {duration_max}]',
                'sort': 'score',
                'page_size': 5,
                'token': api_key,
            }
        )
        # The scheme is the literal https of the f-string; `params` is urlencoded into the query.
        url = f'https://freesound.org/apiv2/search/text/?{params}'
        req = urllib.request.Request(url, headers={'User-Agent': 'Zygomatic/1.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310  # noqa: S310  literal https:// URL above
            data = json.loads(resp.read())

        results = data.get('results', [])
        if not results:
            _notify(f'⚠ Freesound: no results for "{query}"')
            return False

        for sound in results:
            preview_url = sound.get('previews', {}).get('preview-hq-mp3')
            if not preview_url:
                continue
            tmp = dest_path + '.tmp'
            try:
                r = subprocess.run(
                    [exe('curl'), '-sL', '--max-time', '30', '-o', tmp, preview_url],
                    capture_output=True,
                    timeout=40,
                )
                if r.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 3000:
                    probe = subprocess.run(
                        [exe('ffprobe'), '-v', 'quiet', '-show_format', tmp],
                        capture_output=True,
                        timeout=10,
                    )
                    if probe.returncode == 0:
                        os.replace(tmp, dest_path)
                        sz = os.path.getsize(dest_path) // 1024
                        _notify(f'✅ Freesound: "{sound["name"]}" ({sz}KB) → {os.path.basename(dest_path)}')
                        return True
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError as _exc:
                        _zyg_log.debug('temporary preview removal skipped: %s', _exc)

        _notify(f'⚠ Freesound: all previews failed for "{query}"')
    except Exception as e:
        _notify(f'⚠ Freesound error: {e}')
    return False


# ── AudioGen foley generation REMOVED 2026-08-09 ──────────────────────────
# facebook/audiogen-medium weights are CC-BY-NC — the exact licence class
# ambience_ingest.py bans from published audio. The generative foley tier is
# disabled until a licence-clean video-to-audio model (Foley-Omni, MIT — aux
# files pending per-file verification) passes QC. The 14 previously generated
# ag_*.mp3 cache files were quarantined to the 2026-08-09 backup vault so the
# cache short-circuit can never ship stale NC audio. _AUDIOGEN_PROMPTS is kept
# above as the category→prompt vocabulary for the replacement engine.
