# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""Playback preferences, series naming, subtitle/audio defaults, intro/outro marks."""

import hashlib
import json
import os
import re

from .constants import FFPROBE, RUNTIME_DIR, SUB_EXTS, _lock
from .naming import _QUALITY_RE, _lang_from_filename, _lang_label
from .probing import _parse_chapters, _run

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_zero.zpub_cinema')


# ══ Playback preferences (audio/subtitle defaults + intro/outro marks) ════════
# Why a separate file from the library: the library is derived data that a rescan
# rewrites wholesale, while these are the user's CHOICES and must survive it.
PREFS_PATH = os.path.join(RUNTIME_DIR, 'cinema_prefs.json')

DEFAULT_PREFS: dict = {
    # Audio: first match wins. 'ja' first is the anime rule — a dual-audio
    # release is watched in Japanese here.
    'audio_langs': ['ja', 'en'],
    'audio_avoid': ['commentary', 'description', 'descriptive', 'karaoke'],
    # Subtitles: language order first, then these label keywords in order.
    # 'dialogue' is what a fansub release calls its FULL track; the other track
    # in the same file is usually signs/songs only, which is not a translation.
    'sub_langs': ['en'],
    'sub_prefer': ['asakura', 'asukara', 'dialogue', 'full'],
    'sub_avoid': ['signs', 'songs', 'karaoke', 'commentary', 'forced'],
    # Intro skip. A chapter list beats all of this when the file carries one.
    'intro_seconds': 90.0,  # assumed opening length when nothing else says
    'intro_start': 0.0,
    'intro_end': 0.0,  # set by "Intro ends here" (absolute seconds)
    'intro_button_seconds': 10.0,  # how long the Skip-intro button stays up
    # Ending skip: trailing seconds treated as ending/credits/preview.
    'outro_lead': 90.0,
    'auto_skip_outro': True,
}

_PREFS_KEYS = set(DEFAULT_PREFS)
_prefs_cache: dict = {'mtime': -1.0, 'data': None}


def _blank_prefs() -> dict:
    return {'version': 1, 'defaults': dict(DEFAULT_PREFS), 'shows': {}}


def load_prefs() -> dict:
    """Read the prefs file (cached on mtime); never raises."""
    with _lock:
        try:
            mtime = os.path.getmtime(PREFS_PATH)
        except OSError:
            if _prefs_cache['data'] is None or _prefs_cache['mtime'] != -1.0:
                _prefs_cache.update({'mtime': -1.0, 'data': _blank_prefs()})
            return _prefs_cache['data']
        if _prefs_cache['data'] is not None and _prefs_cache['mtime'] == mtime:
            return _prefs_cache['data']
        try:
            with open(PREFS_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError('prefs is not an object')
        except (OSError, ValueError) as exc:
            _zyg_log.info(f'[Cinema] prefs unreadable ({exc}) — using defaults')
            data = _blank_prefs()
        base = dict(DEFAULT_PREFS)
        base.update({k: v for k, v in (data.get('defaults') or {}).items() if k in _PREFS_KEYS})
        data['defaults'] = base
        shows = data.get('shows')
        data['shows'] = shows if isinstance(shows, dict) else {}
        data.setdefault('version', 1)
        _prefs_cache.update({'mtime': mtime, 'data': data})
        return data


def save_prefs(data: dict) -> None:
    with _lock:
        tmp = PREFS_PATH + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=1)
            os.replace(tmp, PREFS_PATH)
            _prefs_cache.update({'mtime': os.path.getmtime(PREFS_PATH), 'data': data})
        except OSError as exc:
            _zyg_log.info(f'[Cinema] prefs save failed: {exc}')


def show_key(name: str) -> str:
    """Collapse a show/movie title to a stable key ('Slime S01' folders vary)."""
    return re.sub(r'[^a-z0-9]+', ' ', (name or '').lower()).strip()


def item_show_key(item: dict, names: dict | None = None) -> str:
    """Prefs key for an item. Follows the DISPLAYED series name, so renaming a
    show carries its skip marks and track choices with it."""
    if names is not None:
        named = names.get(item.get('folder') or '')
        if named:
            return show_key(named)
    return show_key(item.get('series') or item.get('title') or item.get('filename') or '')


def _coerce_pref(key: str, value):
    """Keep a stored pref the same shape as its default (a bad POST can't poison it)."""
    proto = DEFAULT_PREFS.get(key)
    if isinstance(proto, bool):
        return bool(value)
    if isinstance(proto, float):
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return None
    if isinstance(proto, list):
        if not isinstance(value, (list, tuple)):
            return None
        return [str(v).strip().lower() for v in value if str(v).strip()][:24]
    return None


def update_prefs(patch: dict, show: str = '') -> dict:
    """Merge ``patch`` into the global defaults, or into one show's overrides."""
    data = load_prefs()
    data = {
        'version': data.get('version', 1),
        'defaults': dict(data.get('defaults') or {}),
        'shows': {k: dict(v) for k, v in (data.get('shows') or {}).items()},
    }
    key = show_key(show)
    target = data['shows'].setdefault(key, {}) if key else data['defaults']
    for k, v in (patch or {}).items():
        if k not in _PREFS_KEYS:
            continue
        if v is None:
            target.pop(k, None)  # None = "stop overriding this"
            continue
        clean = _coerce_pref(k, v)
        if clean is not None:
            target[k] = clean
    if key and not data['shows'][key]:
        data['shows'].pop(key, None)
    save_prefs(data)
    return data


# ── Series naming ─────────────────────────────────────────────────────────────
# Some releases carry the show's name NOWHERE: measured on a real download, the
# folder is '01. Season 1 + Special' and the files are 'S01E14-Title [CRC].mkv',
# so every derivation available produces junk. The name is therefore a stored
# fact, keyed on the FOLDER — unambiguous (two shows can both derive 'Season 1',
# but they cannot share a directory) and inherited by files dropped in later.
def display_series(item: dict, names: dict | None = None) -> str:
    """The name to show for this item's series, override included."""
    if names:
        named = names.get(item.get('folder') or '')
        if named:
            return named
    return item.get('series') or item.get('title') or ''


def prefs_for(item: dict, names: dict | None = None) -> dict:
    """Effective prefs for one item: global defaults + its show's overrides."""
    data = load_prefs()
    out = dict(data.get('defaults') or DEFAULT_PREFS)
    over = (data.get('shows') or {}).get(item_show_key(item, names)) or {}
    out.update({k: v for k, v in over.items() if k in _PREFS_KEYS})
    out['_show'] = item_show_key(item, names)
    out['_overrides'] = sorted(k for k in over if k in _PREFS_KEYS)
    return out


def _kw_score(text: str, keywords) -> int:
    """Index of the first keyword found in ``text``, else len(keywords)."""
    low = (text or '').lower()
    kws = list(keywords or [])
    for i, kw in enumerate(kws):
        if kw and str(kw).lower() in low:
            return i
    return len(kws)


def _lang_score(lang: str, order) -> int:
    """0..n-1 for a listed language, then untagged, then anything else."""
    order = [str(x).lower() for x in (order or [])]
    if lang and lang in order:
        return order.index(lang)
    return len(order) if not lang else len(order) + 1


# ── Subtitle discovery ────────────────────────────────────────────────────────
def _external_subs(video_path: str) -> list[dict]:
    """Sidecar subtitle files: alongside the video and in a ``Subs/`` folder."""
    out = []
    vdir = os.path.dirname(video_path)
    vstem = os.path.splitext(os.path.basename(video_path))[0].lower()
    candidates: list[str] = []
    try:
        for name in sorted(os.listdir(vdir)):
            full = os.path.join(vdir, name)
            if os.path.isfile(full) and os.path.splitext(name)[1].lower() in SUB_EXTS:
                candidates.append(full)
            elif os.path.isdir(full) and name.lower() in ('subs', 'subtitles', 'sub', 'subtitle'):
                try:
                    for sub in sorted(os.listdir(full)):
                        sfull = os.path.join(full, sub)
                        if os.path.isfile(sfull) and os.path.splitext(sub)[1].lower() in SUB_EXTS:
                            candidates.append(sfull)
                except OSError as _exc:
                    _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    except OSError:
        return out

    for full in candidates:
        name = os.path.basename(full)
        stem = os.path.splitext(name)[0]
        lang = _lang_from_filename(name)
        low = stem.lower()
        forced = 'forced' in low
        sdh = bool(re.search(r'\b(sdh|cc)\b|\(cc\)|\(sdh\)', low))
        # A sidecar that matches the video stem exactly carries no language in
        # its name — it is the release's own default track.
        matches_video = low.startswith(vstem[:40]) if vstem else False
        if not lang and matches_video:
            lang = 'en'
        label = _lang_label(lang, stem if not matches_video else 'Default')
        extras = []
        if sdh:
            extras.append('SDH')
        if forced:
            extras.append('Forced')
        if extras:
            label = f'{label} ({", ".join(extras)})'
        try:
            size = os.path.getsize(full)
        except OSError:
            size = 0
        out.append(
            {
                'id': 'x' + hashlib.sha1(full.encode('utf-8', 'replace'), usedforsecurity=False).hexdigest()[:12],
                'kind': 'external',
                'path': full,
                'label': label,
                'lang': lang,
                'forced': forced,
                'sdh': sdh,
                'size': size,
                'text': True,
            }
        )
    return out


TEXT_SUB_CODECS = {'subrip', 'srt', 'ass', 'ssa', 'mov_text', 'webvtt', 'text', 'micro_dvd'}
IMAGE_SUB_CODECS = {'hdmv_pgs_subtitle', 'dvd_subtitle', 'dvb_subtitle', 'xsub'}


def _embedded_subs(info: dict) -> list[dict]:
    out = []
    for st in info.get('subs') or []:
        codec = st.get('codec') or ''
        text = codec in TEXT_SUB_CODECS
        if not text and codec not in IMAGE_SUB_CODECS:
            text = True  # unknown → try as text
        lang = st.get('lang') or ''
        extras = []
        if st.get('hearing_impaired'):
            extras.append('SDH')
        if st.get('forced'):
            extras.append('Forced')
        title = st.get('title') or ''
        # Release groups stamp the full filename into every stream title; that is
        # noise, not a label.
        if len(title) > 40 or _QUALITY_RE.search(title):
            title = ''
        label = _lang_label(lang, title or f'Track {st.get("order", 0) + 1}')
        if title and _lang_label(lang, '') and title.lower() not in label.lower():
            label = f'{label} — {title}'
        # Don't append a marker the stream title already spells out
        # ('English — SDH (SDH)' was the pre-fix output).
        extras = [e for e in extras if e.lower() not in label.lower()]
        if extras:
            label = f'{label} ({", ".join(extras)})'
        if not text:
            label = f'{label} [burn-in]'
        out.append(
            {
                'id': f'e{st.get("order", 0)}',
                'kind': 'embedded',
                'stream': st.get('order', 0),
                'abs_index': st.get('index'),
                'codec': codec,
                'label': label,
                'lang': lang,
                'forced': bool(st.get('forced')),
                'sdh': bool(st.get('hearing_impaired')),
                'text': text,
            }
        )
    return out


def _sub_rank(s: dict, pref: dict) -> tuple:
    """Sort key for the default subtitle.

    Language order from the prefs first, then label keywords: a fansub release
    ships a FULL track ('Dialogue', often group-stamped) beside a signs/songs
    track that translates nothing but on-screen text — both tagged the same
    language, so only the label separates them. Then plain ahead of SDH/forced,
    external ahead of embedded (a file read beats an ffmpeg extraction), text
    ahead of burn-in.
    """
    text = ' '.join([str(s.get('label') or ''), str(s.get('title') or ''), os.path.basename(str(s.get('path') or ''))])
    avoid = list(pref.get('sub_avoid') or [])
    prefer = list(pref.get('sub_prefer') or [])
    hit = _kw_score(text, prefer)
    # A wanted keyword CANCELS the avoid list. Without this, picking the
    # signs/songs track as a series' default stored the choice and then ranked
    # it last anyway ('signs' is on the avoid list), so the setting did nothing.
    penalty = 0 if hit < len(prefer) else (0 if _kw_score(text, avoid) == len(avoid) else 1)
    return (
        _lang_score(s.get('lang') or '', pref.get('sub_langs')),
        0 if hit < len(prefer) else 1,
        penalty,
        hit,
        1 if s.get('forced') else 0,
        1 if s.get('sdh') else 0,
        0 if s.get('text') else 1,
        0 if s.get('kind') == 'external' else 1,
        # Size breaks the remaining ties. Measured on Thunderbolts: the root
        # sidecar and Subs/English.eng.srt rank identically, but the root file
        # is 2 KB — the FORCED track copied up, which subtitles ~8 lines of the
        # whole film. Without this the default track was decided by readdir order.
        -int(s.get('size') or 0),
        s.get('label', ''),
    )


def pick_default_sub(subs: list[dict], pref: dict | None = None) -> str:
    """Return the id of the subtitle to enable automatically, or ''."""
    usable = [s for s in subs if s.get('text')] or list(subs)
    if not usable:
        return ''
    pref = pref if pref is not None else dict(DEFAULT_PREFS)
    return sorted(usable, key=lambda s: _sub_rank(s, pref))[0]['id']


# ── Default audio track ───────────────────────────────────────────────────────
def _audio_rank(track: dict, i: int, pref: dict) -> tuple:
    """Sort key for the default audio track.

    Language order from the prefs decides first (``ja`` before ``en`` by
    default), then commentary/description tracks are pushed to the back — they
    are tagged with the SAME language as the feature track, so nothing but the
    title separates them.
    """
    text = f'{track.get("title") or ""} {track.get("label") or ""}'
    avoid = pref.get('audio_avoid') or []
    return (
        _lang_score(track.get('lang') or '', pref.get('audio_langs')),
        0 if _kw_score(text, avoid) == len(list(avoid)) else 1,
        0 if track.get('default') else 1,
        -int(track.get('channels') or 0),
        i,
    )


def pick_default_audio(tracks: list[dict], pref: dict | None = None) -> int:
    """Index into ``tracks`` of the audio to select automatically."""
    if not tracks:
        return 0
    pref = pref if pref is not None else dict(DEFAULT_PREFS)
    order = sorted(range(len(tracks)), key=lambda i: _audio_rank(tracks[i], i, pref))
    return order[0]


# ── Intro / ending marks ──────────────────────────────────────────────────────
# Chapter titles are the only trustworthy signal, and only these words carry
# meaning; 'Chapter 04' and timecode-only names say nothing and are ignored.
# Chapter titles are the only exact source for where an opening ends and an
# ending begins. Vocabulary and thresholds below are measured against a real
# 25-episode season whose lists look like:
#   E02  OP 0–91 | Part A | Part B | ED 1326–1416 | PV 1416–1422
#   E03  Intro 0–31 | OP 31–121 | Part A | Part B | ED | PV
#   E01  Intro 0–360 | Part A | Part B | OP 1326–1416 | PV        <- the trap
# 'Intro' is STORY in every one of those files (6 minutes of it in E01) and the
# opening of E01 plays at the END, so neither the name nor the position alone is
# enough. Every genuine OP/ED in that season runs 90–91 s.
_OP_STRICT_RE = re.compile(
    r'\b(op\d?|opening|opening\s*(?:credits|theme|titles|sequence)|'
    r'title\s*sequence|nc?op\d?)\b',
    re.I,
)
_OP_LOOSE_RE = re.compile(r'\b(intro|avant\s*title)\b', re.I)
# Anything here is not story: safe to leave behind at the END of an episode.
_TAIL_CH_RE = re.compile(
    r'\b(ed\d?|ending|nc?ed\d?|outro|closing|end\s*card|endcard|'
    r'credits|end\s*credits|preview|pv|next\s*(?:episode|time)|'
    r'op\d?|opening|epilogue)\b',
    re.I,
)
# An opening is a fixed-length title sequence, not a six-minute cold open.
OP_MIN_SECONDS, OP_MAX_SECONDS = 20.0, 150.0


def detect_marks(item: dict, pref: dict | None = None) -> dict:
    """Where this title's intro ends and its ending begins.

    Three sources, most trusted first: what somebody set for this series, the
    file's own named chapters (exact, and per-episode), then the global defaults
    — which is what makes a freshly added series behave before anyone has
    configured anything.
    """
    pref = pref if pref is not None else prefs_for(item)
    dur = float(item.get('duration') or 0)
    is_ep = item.get('kind') == 'episode'
    chapters = item.get('chapters') or []

    intro = outro = None
    named = [ch for ch in chapters if (ch.get('title') or '').strip()]

    # ── the opening: a title sequence near the FRONT, of a plausible length.
    # An explicit 'OP' beats a vaguer 'Intro' in the same file (E03 names both,
    # and only the second one is the opening); ties go to the later one.
    best = None
    for ch in named:
        title = (ch.get('title') or '').strip()
        try:
            c_start, c_end = float(ch.get('start') or 0), float(ch.get('end') or 0)
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
        strict = bool(_OP_STRICT_RE.search(title))
        if not strict and not _OP_LOOSE_RE.search(title):
            continue
        length = c_end - c_start
        if c_start > max(300.0, dur * 0.25):
            continue  # E01's opening plays at the very end
        if not (OP_MIN_SECONDS <= length <= OP_MAX_SECONDS):
            continue  # 360 s of 'Intro' is the episode, not a skip
        rank = (0 if strict else 1, -c_end)
        if best is None or rank < best[0]:
            best = (rank, {'start': round(c_start, 3), 'end': round(c_end, 3), 'source': 'chapter', 'label': title})
    if best:
        intro = best[1]

    # ── the ending: the trailing RUN of non-story chapters, not the first
    # ED-shaped name anywhere. E23 has 'ED | Extra | PV' — starting at that ED
    # would skip four minutes of story that follows it, so only the unbroken
    # run at the end of the file counts.
    tail = None
    for ch in reversed(named):
        title = (ch.get('title') or '').strip()
        if not _TAIL_CH_RE.search(title):
            break
        try:
            c_start = float(ch.get('start') or 0)
        except (TypeError, ValueError):
            break
        tail = {'start': round(c_start, 3), 'source': 'chapter', 'label': title}
    if tail and dur and tail['start'] >= dur * 0.6:
        outro = tail

    over = pref.get('_overrides') or []
    # An explicit "Intro ends here" / "Ending starts here" for this series beats
    # the file's own chapters: it was typed by the person watching, who can see
    # the picture, while a chapter list is only as good as its muxer. It only
    # beats them when it is USABLE, though — an out-of-range value falls through
    # to the chapters instead of silently leaving the title with no marks.
    i_start = float(pref.get('intro_start') or 0)
    i_end = float(pref.get('intro_end') or 0)
    if i_end > i_start and i_end <= dur * 0.5:
        intro = {
            'start': round(i_start, 3),
            'end': round(i_end, 3),
            'source': 'show' if 'intro_end' in over else 'setting',
            'label': '',
        }

    lead = float(pref.get('outro_lead') or 0)
    if 'outro_lead' in over and lead > 0 and dur and (dur - lead) >= dur * 0.5:
        outro = {'start': round(dur - lead, 3), 'source': 'show', 'label': ''}

    # A named chapter list is EVIDENCE. When one exists and it puts no opening at
    # the front (E01), guessing 90 s would skip the story the episode opens with,
    # so the guesses below apply only to files that say nothing at all.
    blind = not named

    if intro is None and blind and dur > 300 and is_ep:
        guess = i_start + float(pref.get('intro_seconds') or 0)
        if guess > i_start:
            # A 90 s guess is fine on an episode (the button is a CHOICE) but
            # would be a cut, not a skip, against a feature's cold open.
            intro = {
                'start': round(i_start, 3),
                'end': round(min(guess, dur * 0.5), 3),
                'source': 'default',
                'label': '',
            }

    if outro is None and blind and is_ep and dur > 480 and lead > 0 and (dur - lead) > dur * 0.6:
        outro = {'start': round(dur - lead, 3), 'source': 'show' if 'outro_lead' in over else 'default', 'label': ''}

    return {
        'intro': intro,
        'outro': outro,
        'auto_skip_outro': bool(pref.get('auto_skip_outro')) and is_ep and outro is not None,
        'button_seconds': float(pref.get('intro_button_seconds') or 10),
        'show': pref.get('_show', ''),
        'overrides': pref.get('_overrides') or [],
    }


def chapters_of(path: str) -> list[dict]:
    """Chapters only — a cheap probe used to backfill entries indexed before
    chapters were read at all."""
    rc, out, _err = _run([FFPROBE, '-v', 'error', '-print_format', 'json', '-show_chapters', path], timeout=60)
    if rc != 0 or not out.strip():
        return []
    try:
        return _parse_chapters(json.loads(out))
    except Exception:
        return []
