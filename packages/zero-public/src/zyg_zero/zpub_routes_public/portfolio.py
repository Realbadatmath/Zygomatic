# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Portfolio media routes: the film streams, the architecture atlas, the slide deck.

Moved verbatim out of ``zpub_routes_public.py`` (lines 195-476).
"""

from zyg_zero import paths
from zyg_zero.zpub_routes_public.core import (
    _gate_response,
    _session_invite,
    _zpub_log,
    bp,
    jsonify,
    limiter,
    os,
    re,
    render_template,
    request,
    send_from_directory,
    session,
    settings,
    time,
    zpub_portfolio_deck,
)

# ── Portfolio film — shown, not handed out ────────────────────────────────────
# The video is served only to a media element on one of our own pages. There is
# no download link, the player advertises ``nodownload``, and this route refuses
# any request that did not originate from this site: a pasted URL, curl, wget,
# yt-dlp or a hotlink from someone else's page all get 403. Range requests are
# still honoured so the viewer can seek.
#
# HONEST LIMIT: this defeats casual saving and scripted grabbers, not a
# determined viewer. The bytes necessarily reach the browser to be played, so
# anyone willing to open devtools can still recover them. Treat it as a closed
# door, not a vault.
_PORTFOLIO_VIDEO_PATH = (
    os.environ.get('ZPUB_PORTFOLIO_VIDEO') or str(settings.ZYG_PORTFOLIO_DIR / 'showreel.mp4')
)  # 2026-10-05: v7 = v6 with Ubi moved off the backend table (S30) so the WEB LAYER column reads in full; v6 = v5 with the two stale Metrics screenshots (dropped 'Sports video' tab) replaced by cuts of the 10-04 metrics recording


def _request_is_same_origin() -> bool:
    """True only for a sub-resource request issued by one of our own pages.

    Sec-Fetch-* is set by the browser itself and is a forbidden header for page
    scripts, so it cannot be forged from inside a page. Scripted grabbers do not
    send it at all — MEASURED: yt-dlp pulled the whole film when this function
    still fell back to trusting Referer, because its generic extractor sets
    Referer to the page it scraped. There is deliberately no Referer fallback
    any more; a missing Sec-Fetch-Site is treated as "not a browser".

    Cost of that strictness: browsers older than Chrome 76 / Firefox 90 /
    Safari 16.4 cannot play the film. That is the trade the operator asked for.
    """
    site = (request.headers.get('Sec-Fetch-Site') or '').strip().lower()
    if site not in ('same-origin', 'same-site'):
        return False
    # 'navigate' means the URL itself is being opened (typed, or a link/Save As)
    # rather than pulled in by a media element on a page.
    mode = (request.headers.get('Sec-Fetch-Mode') or '').strip().lower()
    if mode == 'navigate':
        return False
    return True


_PORTFOLIO_SPEEDRUN_PATH = os.environ.get('ZPUB_PORTFOLIO_SPEEDRUN') or str(settings.ZYG_PORTFOLIO_DIR / 'speedrun.mp4')


def _stream_portfolio_file(path, blocked_tag):
    """Stream one of our own films to our own player — never as a file download."""
    if not _request_is_same_origin():
        _zpub_log(
            blocked_tag,
            ip=request.remote_addr or 'unknown',
            sec_fetch_site=request.headers.get('Sec-Fetch-Site', ''),
            sec_fetch_mode=request.headers.get('Sec-Fetch-Mode', ''),
            sec_fetch_dest=request.headers.get('Sec-Fetch-Dest', ''),
            referer=(request.referrer or '')[:120],
            user_agent=request.headers.get('User-Agent', '')[:120],
        )
        return jsonify({'error': 'Forbidden'}), 403
    if not os.path.isfile(path):
        return jsonify({'error': 'Not found'}), 404
    from flask import send_file

    resp = send_file(path, mimetype='video/mp4', conditional=True)
    resp.headers['Content-Disposition'] = 'inline'
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return resp


@bp.route('/portfolio-stream')
def portfolio_stream():
    """Stream the portfolio film to our own player — never as a file download."""
    return _stream_portfolio_file(_PORTFOLIO_VIDEO_PATH, 'portfolio_stream_blocked')


@bp.route('/portfolio-speedrun-stream')
def portfolio_speedrun_stream():
    """The three-minute speedrun cut of the portfolio film, behind the same door."""
    return _stream_portfolio_file(_PORTFOLIO_SPEEDRUN_PATH, 'portfolio_speedrun_stream_blocked')


# ── Architecture atlas — the self-contained system diagram, shown and downloadable ─
# 2026-10-05: the Zygomatic Atlas (zoomable architecture diagram, 270 boxes,
# 9 layers, 10 workflow traces) lives as ONE static HTML file under
# templates/assets/portfolio/. /atlas renders it inline for viewing, /atlas/download
# hands the same file over as an attachment. It is the public edition: internal
# addresses and the private channel are scrubbed before the file is placed here.
_ATLAS_PATH = os.environ.get(
    'ZPUB_ATLAS_FILE',
    str(paths.TEMPLATES_DIR / 'assets' / 'portfolio' / 'zygomatic_atlas.html'),
)
_ATLAS_DOWNLOAD_NAME = 'Zygomatic_Atlas_2026-10-05.html'
# Compact second edition (structure only, one screen) — same folder, own routes.
_ARCH_PATH = os.environ.get(
    'ZPUB_ARCH_FILE',
    str(paths.TEMPLATES_DIR / 'assets' / 'portfolio' / 'zygomatic_architecture.html'),
)
_ARCH_DOWNLOAD_NAME = 'Zygomatic_Architecture_compact_2026-10-05.html'


def _atlas_response(as_attachment: bool, path: str = None, name: str = None, kind: str = 'atlas'):
    path = path or _ATLAS_PATH
    name = name or _ATLAS_DOWNLOAD_NAME
    if not os.path.isfile(path):
        return jsonify({'error': 'Not found'}), 404
    from flask import send_file

    resp = send_file(
        path,
        mimetype='text/html',
        conditional=True,
        as_attachment=as_attachment,
        download_name=name if as_attachment else None,
    )
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    _zpub_log(
        f'{kind}_download' if as_attachment else f'{kind}_view',
        ip=request.remote_addr or 'unknown',
        user_agent=request.headers.get('User-Agent', '')[:120],
    )
    return resp


@bp.route('/atlas')
@limiter.exempt
def atlas_view():
    """The architecture atlas, opened in its own tab."""
    return _atlas_response(as_attachment=False)


@bp.route('/atlas/download')
@limiter.exempt
def atlas_download():
    """The same file as a download."""
    return _atlas_response(as_attachment=True)


@bp.route('/architecture')
@limiter.exempt
def architecture_view():
    """The compact architecture (structure only), opened in its own tab."""
    return _atlas_response(False, _ARCH_PATH, _ARCH_DOWNLOAD_NAME, 'architecture')


@bp.route('/architecture/download')
@limiter.exempt
def architecture_download():
    """The compact architecture as a download."""
    return _atlas_response(True, _ARCH_PATH, _ARCH_DOWNLOAD_NAME, 'architecture')


# ── Portfolio slideshow — the screenshot deck, shown on our own page ──────────
# TEMPORARY presentation: the screenshot set captured 2026-10-02 (104 frames,
# 1920x1080, operator layout) is replayed one frame at a time by
# /portfolio-slideshow. Point it at a different folder with
# ZPUB_PORTFOLIO_SLIDES; a purpose-built presentation replaces this later.
_PORTFOLIO_SLIDES_DIR = os.environ.get('ZPUB_PORTFOLIO_SLIDES') or str(settings.ZYG_PORTFOLIO_DIR / 'slideshow')

# Slides are addressed by bare filename — no separators and no leading dot, so
# a crafted name cannot climb out of the folder even before send_from_directory.
_SLIDE_NAME_RE = re.compile(r'^[0-9A-Za-z][0-9A-Za-z._-]*\.(?:png|jpe?g|webp)$', re.IGNORECASE)

_SLIDE_CACHE = {'at': 0.0, 'slides': []}
_SLIDE_CACHE_TTL = 30.0


def _portfolio_slides() -> list:
    """Ordered slides as {file, n, title}; [] when the folder is missing.

    Cached briefly so a page render never costs a directory listing per
    visitor, while new screenshots dropped into the folder still appear
    without a restart.
    """
    now = time.time()
    if _SLIDE_CACHE['slides'] and now - _SLIDE_CACHE['at'] < _SLIDE_CACHE_TTL:
        return _SLIDE_CACHE['slides']
    try:
        names = sorted(n for n in os.listdir(_PORTFOLIO_SLIDES_DIR) if _SLIDE_NAME_RE.match(n))
    except OSError:
        return []
    slides = []
    for name in names:
        stem = os.path.splitext(name)[0]
        m = re.match(r'^(\d+)[_-](.+)$', stem)
        num, rest = (m.group(1), m.group(2)) if m else ('', stem)
        slides.append(
            {
                'file': name,
                'n': num.lstrip('0') or num,
                'title': rest.replace('_', ' ').strip(),
            }
        )
    _SLIDE_CACHE['at'] = now
    _SLIDE_CACHE['slides'] = slides
    return slides


@bp.app_context_processor
def _inject_portfolio_deck():
    """Deck summary for the slideshow card on every zero_public.html render (cached)."""
    try:
        return {'portfolio_deck': zpub_portfolio_deck.deck(_PORTFOLIO_SLIDES_DIR)}
    except Exception:
        return {'portfolio_deck': None}


@bp.route('/portfolio-slideshow')
def portfolio_slideshow():
    """The portfolio presentation — a curated deck played like a film.

    2026-10-04: replaced the raw 104-frame replay with the edited deck from
    zpub_portfolio_deck.py (hero, chapters, captions). The page loads the
    movie engine from /assets/zero/js/zpub_portfolio_movie.js; the same
    engine plays the deck inside the card on the invite page.
    """
    if not _session_invite() and not session.get('is_zpub_admin'):
        return _gate_response()
    deck = zpub_portfolio_deck.deck(_PORTFOLIO_SLIDES_DIR)
    _zpub_log(
        'portfolio_slideshow_open',
        ip=request.remote_addr or 'unknown',
        slides=deck['count'],
        chapters=len(deck['chapters']),
    )
    return render_template('zero_slideshow.html', deck=deck)


@bp.route('/portfolio-slideshow/deck.json')
@limiter.exempt
def portfolio_deck_json():
    """The deck as JSON for the card player on the invite page.

    Same door as the slides (see _request_is_same_origin): only a fetch()
    issued by one of our own pages gets it. Not behind the invite gate on
    purpose — the card sits on the gate page too, and the deck is captions
    for pictures that are themselves only served same-origin.
    """
    if not _request_is_same_origin():
        return jsonify({'error': 'Forbidden'}), 403
    resp = jsonify(zpub_portfolio_deck.deck(_PORTFOLIO_SLIDES_DIR))
    resp.headers['Cache-Control'] = 'private, max-age=60'
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return resp


@bp.route('/portfolio-slideshow/slide/<name>')
@limiter.exempt
def portfolio_slide(name: str):
    """Serve one slide to an <img> on one of our own pages.

    Same door as the film (see _request_is_same_origin): the bytes are shown,
    not handed out. Deliberately NOT behind the invite gate — the page that
    embeds them already is, and the slides are sub-resource fetches whose
    session cookie may be absent on a prefetch.
    """
    if not _request_is_same_origin():
        return jsonify({'error': 'Forbidden'}), 403
    if not _SLIDE_NAME_RE.match(name or ''):
        return jsonify({'error': 'Not found'}), 404
    if not os.path.isfile(os.path.join(_PORTFOLIO_SLIDES_DIR, name)):
        return jsonify({'error': 'Not found'}), 404
    resp = send_from_directory(_PORTFOLIO_SLIDES_DIR, name, conditional=True)
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return resp


@bp.route('/portfolio-slideshow/cover')
@limiter.exempt
def portfolio_slide_cover():
    """First picture of the deck — backdrop of the slideshow card on the invite page."""
    deck = zpub_portfolio_deck.deck(_PORTFOLIO_SLIDES_DIR)
    for ch in deck['chapters']:
        for s in ch['slides']:
            if s.get('file'):
                return portfolio_slide(s['file'])
    slides = _portfolio_slides()
    if not slides:
        return jsonify({'error': 'Not found'}), 404
    return portfolio_slide(slides[0]['file'])
