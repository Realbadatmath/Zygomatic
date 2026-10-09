# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""Scene-release name parsing and language handling."""

import os
import re


# ── Scene-release name parsing ─────────────────────────────────────────────────
# Everything from the first of these tokens onward is release metadata, not title.
_QUALITY_TOKENS = (
    r'\d{3,4}[pi]',
    r'4k',
    r'uhd',
    r'hdr10?\+?',
    r'dolby ?vision',
    r'dv',
    r'bluray',
    r'blu-ray',
    r'brrip',
    r'bdrip',
    r'bdremux',
    r'remux',
    r'webrip',
    r'web-?dl',
    r'web',
    r'hdrip',
    r'dvdrip',
    r'dvdscr',
    r'hdtv',
    r'cam',
    r'ts',
    r'tc',
    r'r5',
    r'workprint',
    r'x264',
    r'x265',
    r'h\.?264',
    r'h\.?265',
    r'hevc',
    r'avc',
    r'xvid',
    r'divx',
    r'10bit',
    r'8bit',
    r'aac\d?(\.\d)?',
    r'ac3',
    r'eac3',
    r'dd\+?\d?(\.\d)?',
    r'ddp\d?(\.\d)?',
    r'dts(-hd)?(-ma)?',
    r'truehd',
    r'atmos',
    r'flac',
    r'mp3',
    r'\d\.\d(ch)?',
    r'multi',
    r'dual',
    r'repack',
    r'proper',
    r'extended',
    r'unrated',
    r'uncut',
    r'directors?.cut',
    r'theatrical',
    r'imax',
    r'limited',
    r'internal',
    r'complete',
    r'retail',
    r'remastered',
    r'anniversary',
)
_QUALITY_RE = re.compile(r'(?<![a-z0-9])(?:' + '|'.join(_QUALITY_TOKENS) + r')(?![a-z0-9])', re.I)
_YEAR_RE = re.compile(r'(?<!\d)(19\d{2}|20\d{2})(?!\d)')

# Episode markers, most specific first.
# A '.5' after the episode number is an OVA/recap special ('S01E24.5-Tales…'),
# and _clean_title has already turned that dot into a space by the time these
# run — so the half marker is matched as ' 5' followed by a non-digit. Without
# it the special parses as a second episode 24 and sits on top of the real one.
_HALF = r'(?:[ .](?P<half>5)(?![0-9]))?'
_EPISODE_RES = (
    re.compile(r'(?P<show>.*?)[ ._-]*[sS](?P<s>\d{1,2})[ ._-]*[eE](?P<e>\d{1,4})' + _HALF + r'(?![0-9])'),
    re.compile(r'(?P<show>.*?)[ ._-]*(?P<s>\d{1,2})[xX](?P<e>\d{1,4})' + _HALF + r'(?![0-9])'),
    re.compile(
        r'(?P<show>.*?)[ ._-]*[sS]eason[ ._-]*(?P<s>\d{1,2})[ ._-]*[eE]pisode[ ._-]*(?P<e>\d{1,4})'
        + _HALF
        + r'(?![0-9])'
    ),
    # The [eE] marker MUST follow a separator: without that guard a 4-digit
    # number lets "One Piece - 1015" match with the "e" of *Piece* as the
    # marker, and the show is filed forever as "One Piec".
    re.compile(r'(?P<show>.*?)(?:^|(?<=[ ._-]))[eE]p?[ ._-]*(?P<e>\d{1,4})' + _HALF + r'(?![0-9])(?P<s>)'),
)
_SEASON_DIR_RE = re.compile(r'^(?:season|series|s)[ ._-]*(\d{1,2})$', re.I)

# Image files that are advertising, not artwork. Measured on the real corpus:
# every YTS/YIFY/RARBG folder ships a poster-shaped banner for the tracker.
_AD_IMAGE_RE = re.compile(
    r'(www[. ]|\.com|\.mx|\.ag|\.bz|\.org|\.net|\.to|\.se|yts|yify|rarbg|torrent'
    r'|proxies|uindex|extratorrent|demonoid|ahashare|1337x|galaxyrg|sample|screen)',
    re.I,
)
# ONLY the Plex/Kodi artwork convention. Deliberately NOT '<videoname>.jpg':
# measured on this corpus, "Gods of Egypt ... .mkv.jpg" is a MediaInfo SCREENSHOT
# SHEET — a grid of stills with the file's bitrate printed over it — which is what
# release groups actually ship under that name. It is not a poster and it is not a
# preview of the film.
_POSTER_NAME_RE = re.compile(r'^(poster|folder|cover|fanart|backdrop|show|season\d*)$', re.I)


def _clean_title(raw: str) -> str:
    """Turn a scene-release stem into a human title."""
    s = raw
    s = re.sub(r'^\s*(?:www[. ][^ ]*|\[[^\]]*\])\s*[-_ ]*', ' ', s)  # leading site tag
    # Fansub CRC32 stamp — '[47C8F23B]'. Dropped BEFORE brackets become spaces,
    # or it survives as a word and every episode title ends in a hex hash.
    s = re.sub(r'\[\s*[0-9A-Fa-f]{8}\s*\]', ' ', s)
    s = s.replace('_', ' ')
    # Dots are separators only when the stem is dot-delimited (Foo.Bar.2019).
    if s.count('.') >= 2 and ' ' not in s.strip():
        s = s.replace('.', ' ')
    else:
        s = re.sub(r'\.(?=[A-Za-z0-9])', ' ', s)
    s = re.sub(r'[\[\](){}]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip(' -_.')
    return s


def parse_release_name(stem: str) -> tuple[str, int | None]:
    """``('Gods of Egypt', 2016)`` from ``Gods of Egypt 2016 1080p BluRay x264``."""
    s = _clean_title(stem)
    year = None
    cut = len(s)
    # A year is the strongest boundary, but only when something precedes it.
    for m in _YEAR_RE.finditer(s):
        if m.start() > 0:
            year = int(m.group(1))
            cut = m.start()
            break
    q = _QUALITY_RE.search(s)
    if q and q.start() > 0 and q.start() < cut:
        cut = q.start()
        if year is None:
            ym = _YEAR_RE.search(s[q.start() :])
            if ym:
                year = int(ym.group(1))
    title = s[:cut].strip(' -_.,')
    if not title:
        title = s.strip(' -_.,') or stem
    title = re.sub(r'\s+', ' ', title)
    return title, year


def detect_episode(video_path: str) -> dict | None:
    """Return ``{series, season, episode, episode_title}`` when the file is an episode."""
    stem = os.path.splitext(os.path.basename(video_path))[0]
    parent = os.path.basename(os.path.dirname(video_path))
    grandparent = os.path.basename(os.path.dirname(os.path.dirname(video_path)))

    season_from_dir = None
    sd = _SEASON_DIR_RE.match(parent.strip())
    if sd:
        season_from_dir = int(sd.group(1))

    for rx in _EPISODE_RES:
        m = rx.match(_clean_title(stem))
        if not m:
            continue
        raw_s = (m.group('s') or '').strip()
        # The bare "E05"/"Ep05" pattern is only trusted inside a Season folder —
        # otherwise "Deadpool 2" and every resolution token become "episodes".
        if not raw_s and season_from_dir is None:
            continue
        season = int(raw_s) if raw_s else season_from_dir
        episode = int(m.group('e'))
        if m.groupdict().get('half'):
            episode += 0.5
        show = _clean_title(m.group('show') or '')
        show = re.sub(r'[ .\-_]+$', '', show)
        if not show or len(show) < 2:
            base = grandparent if season_from_dir is not None else parent
            show, _ = parse_release_name(base)
        else:
            show, _ = parse_release_name(show + ' ')
        tail = _clean_title(stem)[m.end() :]
        tail = re.sub(r'^[ .\-_]+', '', tail)
        qcut = _QUALITY_RE.search(tail)
        if qcut:
            tail = tail[: qcut.start()]
        ep_title = tail.strip(' -_.')
        if len(ep_title) > 60:
            ep_title = ''
        return {'series': show or 'Unknown', 'season': season or 1, 'episode': episode, 'episode_title': ep_title}
    return None


# ── Language handling ─────────────────────────────────────────────────────────
_LANG_MAP = {
    'en': 'en',
    'eng': 'en',
    'english': 'en',
    'nl': 'nl',
    'nld': 'nl',
    'dut': 'nl',
    'dutch': 'nl',
    'nederlands': 'nl',
    'flemish': 'nl',
    'es': 'es',
    'spa': 'es',
    'esp': 'es',
    'spanish': 'es',
    'castellano': 'es',
    'espanol': 'es',
    'fr': 'fr',
    'fra': 'fr',
    'fre': 'fr',
    'french': 'fr',
    'francais': 'fr',
    'de': 'de',
    'deu': 'de',
    'ger': 'de',
    'german': 'de',
    'deutsch': 'de',
    'it': 'it',
    'ita': 'it',
    'italian': 'it',
    'italiano': 'it',
    'pt': 'pt',
    'por': 'pt',
    'portuguese': 'pt',
    'brazilian': 'pt',
    'ru': 'ru',
    'rus': 'ru',
    'russian': 'ru',
    'ar': 'ar',
    'ara': 'ar',
    'arabic': 'ar',
    'zh': 'zh',
    'chi': 'zh',
    'zho': 'zh',
    'chinese': 'zh',
    'mandarin': 'zh',
    'cantonese': 'zh',
    'ja': 'ja',
    'jpn': 'ja',
    'japanese': 'ja',
    'ko': 'ko',
    'kor': 'ko',
    'korean': 'ko',
    'sv': 'sv',
    'swe': 'sv',
    'swedish': 'sv',
    'no': 'no',
    'nor': 'no',
    'norwegian': 'no',
    'da': 'da',
    'dan': 'da',
    'danish': 'da',
    'fi': 'fi',
    'fin': 'fi',
    'finnish': 'fi',
    'pl': 'pl',
    'pol': 'pl',
    'polish': 'pl',
    'cs': 'cs',
    'cze': 'cs',
    'ces': 'cs',
    'czech': 'cs',
    'tr': 'tr',
    'tur': 'tr',
    'turkish': 'tr',
    'el': 'el',
    'gre': 'el',
    'ell': 'el',
    'greek': 'el',
    'he': 'he',
    'heb': 'he',
    'hebrew': 'he',
    'hi': 'hi',
    'hin': 'hi',
    'hindi': 'hi',
    'hu': 'hu',
    'hun': 'hu',
    'hungarian': 'hu',
    'ro': 'ro',
    'ron': 'ro',
    'rum': 'ro',
    'romanian': 'ro',
    'bg': 'bg',
    'bul': 'bg',
    'bulgarian': 'bg',
    'uk': 'uk',
    'ukr': 'uk',
    'ukrainian': 'uk',
    'th': 'th',
    'tha': 'th',
    'thai': 'th',
    'vi': 'vi',
    'vie': 'vi',
    'vietnamese': 'vi',
    'id': 'id',
    'ind': 'id',
    'indonesian': 'id',
    'ms': 'ms',
    'may': 'ms',
    'msa': 'ms',
    'malay': 'ms',
    'hr': 'hr',
    'hrv': 'hr',
    'croatian': 'hr',
    'sr': 'sr',
    'srp': 'sr',
    'serbian': 'sr',
    'sl': 'sl',
    'slv': 'sl',
    'slovenian': 'sl',
    'sk': 'sk',
    'slo': 'sk',
    'slk': 'sk',
    'slovak': 'sk',
    'et': 'et',
    'est': 'et',
    'estonian': 'et',
    'lv': 'lv',
    'lav': 'lv',
    'latvian': 'lv',
    'lt': 'lt',
    'lit': 'lt',
    'lithuanian': 'lt',
    'fa': 'fa',
    'per': 'fa',
    'fas': 'fa',
    'persian': 'fa',
    'farsi': 'fa',
}
_LANG_NAMES = {
    'en': 'English',
    'nl': 'Dutch',
    'es': 'Spanish',
    'fr': 'French',
    'de': 'German',
    'it': 'Italian',
    'pt': 'Portuguese',
    'ru': 'Russian',
    'ar': 'Arabic',
    'zh': 'Chinese',
    'ja': 'Japanese',
    'ko': 'Korean',
    'sv': 'Swedish',
    'no': 'Norwegian',
    'da': 'Danish',
    'fi': 'Finnish',
    'pl': 'Polish',
    'cs': 'Czech',
    'tr': 'Turkish',
    'el': 'Greek',
    'he': 'Hebrew',
    'hi': 'Hindi',
    'hu': 'Hungarian',
    'ro': 'Romanian',
    'bg': 'Bulgarian',
    'uk': 'Ukrainian',
    'th': 'Thai',
    'vi': 'Vietnamese',
    'id': 'Indonesian',
    'ms': 'Malay',
    'hr': 'Croatian',
    'sr': 'Serbian',
    'sl': 'Slovenian',
    'sk': 'Slovak',
    'et': 'Estonian',
    'lv': 'Latvian',
    'lt': 'Lithuanian',
    'fa': 'Persian',
}


def _norm_lang(raw: str | None) -> str:
    if not raw:
        return ''
    key = re.sub(r'[^a-z]', '', str(raw).lower())
    return _LANG_MAP.get(key, '')


def _lang_from_filename(name: str) -> str:
    """Best-effort language from a subtitle filename ('English (CC).eng.srt')."""
    stem = os.path.splitext(name)[0]
    # Longest tokens first so 'english' beats a stray 'en'.
    tokens = [t for t in re.split(r'[^A-Za-z]+', stem) if t]
    for tok in sorted(tokens, key=len, reverse=True):
        lang = _norm_lang(tok)
        if lang:
            return lang
    return ''


def _lang_label(lang: str, fallback: str = '') -> str:
    return _LANG_NAMES.get(lang) or (fallback or (lang.upper() if lang else 'Unknown'))
