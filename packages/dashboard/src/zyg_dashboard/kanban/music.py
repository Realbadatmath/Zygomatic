# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kanban/music.py — children's music: songs, melody shelves, series and the forwarders to the music API.

Split verbatim out of ``kanban_server.py`` (lines 2961-3637) on 2026-10-06; the handler
re-imports every name from here, so ``zyg_dashboard.kanban_server.<name>`` still resolves.
"""

import os
import re
import json
import time
from zyg_dashboard.kanban.common import _OUTPUT_ROOT, _zyg_log
from zyg_dashboard.kanban.review_mesh import _MAIN_APP, _MEDIA_PATH_RE, _internal_token

# ── Children's Music (2026-08-29) ────────────────────────────────────────────
# The workflow writes one folder per song under output/kidsmusic/<job id>/ with a
# manifest. This tab reads those manifests, and launches new runs by forwarding
# to the pipeline API the same way the creature review gate does — except that
# the kidsmusic routes are localhost-gated rather than token-gated, because
# ZERO_PUBLIC_TOKEN is not set on this box and a workflow nobody can start is
# not a workflow.
# 2026-09-06: two producers write into this one library. The children's
# composer writes output/kidsmusic/<job>/; the cinematic composer writes
# output/cinematic/<job>/. One root per family, and EVERY path in this tab is
# built through _km_dir, so which root a song lives in is answered in exactly
# one place instead of being assumed at each call site.
_KM_ROOTS = {
    'children': os.path.realpath(os.path.join(_OUTPUT_ROOT, 'kidsmusic')),
    'cinematic': os.path.realpath(os.path.join(_OUTPUT_ROOT, 'cinematic')),
}
# The pre-split name, kept as the children alias so older callers still resolve.
_KM_ROOT = _KM_ROOTS['children']
_KM_ID_RE = re.compile(r'^([a-f0-9]{12}|cli_[0-9_]{1,24})$')
_KM_CACHE = {'ts': 0.0, 'data': None}
_KM_CACHE_TTL = 8.0
# A fixed whitelist of EXACT filenames, not a pattern: the caller never supplies
# a path fragment, so there is nothing for a traversal to be built out of.
_KM_FILES = {
    'master.mp3': 'audio/mpeg',
    'song.mp3': 'audio/mpeg',
    'melody.mp3': 'audio/mpeg',
    'melody.mid': 'audio/midi',
    'roll.svg': 'image/svg+xml',
    'lyrics.txt': 'text/plain; charset=utf-8',
    'song.json': 'application/json',
    'manifest.json': 'application/json',
    'LICENSE.txt': 'text/plain; charset=utf-8',
    # The measurement record. On the five songs whose audio was deleted on
    # 2026-08-29 this is the only surviving evidence of what they measured and
    # why they went, so it has to be reachable from the tab.
    'MEASUREMENT.json': 'application/json',
    # The picture leg.
    'video.mp4': 'video/mp4',
    'poster.jpg': 'image/jpeg',
    'storyboard.json': 'application/json',
    # The voice leg (2026-09-15): the shipped take split into its two stems,
    # and the review that measured the voice on its own track.
    'stems/vocals.flac': 'audio/flac',
    'stems/backing.flac': 'audio/flac',
    'voice_report.json': 'application/json',
    # The voice conversion (2026-09-15): the unconverted voice, kept for A/B.
    'master_unconverted.mp3': 'audio/mpeg',
    'stems/vocals_unconverted.flac': 'audio/flac',
}

# Storyboard frames live in a subdirectory, which the exact-name whitelist above
# cannot express. The containment property is kept by not using the caller's
# string at all: only the INTEGER inside it survives, and the path is rebuilt
# from a fixed format. A traversal has nothing to be built out of.
_KM_FRAME_RE = re.compile(r'^frames/([ft])(\d{1,4})\.(png|jpg)$')


def _km_dir(sid):
    """The folder of one song, looked for in every library root.

    The containment check is made per root and against the REALPATH, so an id
    shaped like a traversal (or a symlink planted inside a root) still cannot
    reach outside the root it was joined to, let alone out of output/.
    """
    if not _KM_ID_RE.match(sid or ''):
        return None
    for root in _KM_ROOTS.values():
        d = os.path.realpath(os.path.join(root, sid))
        if d.startswith(root + os.sep) and os.path.isdir(d):
            return d
    return None


def _km_root_of(song_dir):
    """Which family root a resolved song folder came out of ('' if none)."""
    for key, root in _KM_ROOTS.items():
        if song_dir.startswith(root + os.sep):
            return key
    return ''


# Leg -> the words that belong in a downloaded filename.
_KM_DL_LEG = {
    'master.mp3': 'master',
    'song.mp3': 'ACE-Step take',
    'melody.mp3': 'score render',
    'melody.mid': 'score',
    'song.json': 'plan',
    'roll.svg': 'piano roll',
    'lyrics.txt': 'lyric',
    'manifest.json': 'manifest',
    'MEASUREMENT.json': 'measurement',
    'LICENSE.txt': 'LICENCE',
    'video.mp4': 'video',
    'poster.jpg': 'poster',
    'storyboard.json': 'storyboard',
    'stems/vocals.flac': 'voice track',
    'stems/backing.flac': 'music track',
    'voice_report.json': 'voice report',
}


# ── Melody shelves (2026-09-01) ──────────────────────────────────────────────
# The Melodies library is a TREE, not a flat list: three families, and shelves
# under each. "Storytime" exists under two of them and does not mean the same
# thing in each, so a shelf is only ever addressed as (family, shelf) — never by
# its own name. The client builds its boards from this list rather than from a
# second copy of it, so the two cannot drift.
#
# 2026-09-06: the children family's shelf keys ARE the kids_music_theory.STYLES
# keys — one shelf per style the composer can be asked for, so a song's declared
# style is its shelf and no mapping table sits between them. (Action & Dance-along
# is deliberately absent: the operator excluded it.) The first shelf stays
# 'playtime', because _KM_FIRST_SHELF backstops the fallback and moving it would
# silently re-home every style-less song. The four original keys — learning,
# playtime, sleeptime, storytime — are kept verbatim so songs already filed on
# them do not move.
_KM_FAMILIES = [
    (
        'children',
        'Children melodies',
        [
            ('playtime', 'Playtime'),
            ('sleeptime', 'Sleeptime'),
            ('storytime', 'Storytime'),
            ('learning', 'Learning'),
            ('lullaby', 'Lullaby'),
            ('nursery', 'Nursery Rhyme'),
            ('counting', 'Counting & Alphabet'),
            ('singalong', 'Sing-along'),
            ('animals', 'Animal Songs'),
            ('seasons', 'Seasons & Holidays'),
            ('bedtime', 'Bath & Bedtime Routine'),
        ],
    ),
    # 2026-09-06: the cinematic family gets one shelf per style the cinematic
    # composer can be asked for, the same contract the children family has —
    # a piece's declared style IS its shelf, with no mapping table between.
    # The six original keys keep their spelling so pieces already filed on them
    # do not move; only their ORDER changed, and order is presentation.
    (
        'cinematic',
        'Cinematic melodies',
        [
            ('cheerful', 'Cheerful'),
            ('sad', 'Sad'),
            ('heroic', 'Heroic'),
            ('tavern', 'Tavern'),
            ('storytime', 'Storytime'),
            ('sonata', 'Sonata'),
            ('suspense', 'Suspense'),
            ('romance', 'Romance'),
            ('wonder', 'Wonder & Discovery'),
            ('mystery', 'Mystery'),
            ('chase', 'Chase'),
            ('melancholy', 'Melancholy'),
            ('triumph', 'Triumphant Finale'),
        ],
    ),
    # 2026-09-02: the soundtrack library. The other two families are named for
    # WHO a piece is for and shelved by mood; a soundtrack is written for a
    # PLACE IN A PRODUCTION, so its shelves are cue roles. Keeping the roles out
    # of the mood vocabulary is what stops a score cue and a Cinematic melody
    # from being the same card filed twice.
    (
        'soundtracks',
        'Soundtracks',
        [
            ('theme', 'Main theme'),
            ('opening', 'Opening'),
            ('underscore', 'Underscore'),
            ('tension', 'Tension'),
            ('action', 'Action'),
            ('closing', 'Closing'),
        ],
    ),
]
_KM_SHELF_OK = {f: {k for k, _ in sh} for f, _, sh in _KM_FAMILIES}
# The children shelves are a CONTRACT, not a preference: the composer's style
# names, the tab's board order and the filing validator all read this one list.
# An explicit raise, not an assert, so an edit that breaks the contract fails at
# import — loudly, on the next restart, and under `python -O` too — rather than
# quietly filing songs onto a shelf that the board cannot draw.
if [k for k, _ in _KM_FAMILIES[0][2]] != [
    'playtime',
    'sleeptime',
    'storytime',
    'learning',
    'lullaby',
    'nursery',
    'counting',
    'singalong',
    'animals',
    'seasons',
    'bedtime',
]:
    raise RuntimeError('children shelf keys must match kids_music_theory.STYLES')
if [k for k, _ in _KM_FAMILIES[1][2]] != [
    'cheerful',
    'sad',
    'heroic',
    'tavern',
    'storytime',
    'sonata',
    'suspense',
    'romance',
    'wonder',
    'mystery',
    'chase',
    'melancholy',
    'triumph',
]:
    raise RuntimeError('cinematic shelf keys must match the cinematic composer styles')
_KM_DEFAULT_FAMILY = 'children'
# Where a song lands when nothing about it matched a shelf. Per family, because
# a shelf name is only meaningful inside its own family — 'cheerful' is not a
# soundtrack cue role, and a derived placement pointing at a shelf that family
# does not have is a song that renders nowhere. The first shelf of the family
# is the backstop, so a family added later cannot fall through to a KeyError.
_KM_FALLBACK_SHELF = {'children': 'playtime', 'cinematic': 'cheerful', 'soundtracks': 'underscore'}
_KM_FIRST_SHELF = {f: sh[0][0] for f, _, sh in _KM_FAMILIES}

# A narrative subject — "a dinosaur WHO lost his socks", "a little red train
# THAT says toot toot". A song about a character doing something is a story; a
# song about an activity ("washing your hands with lots of bubbles") is not.
_KM_STORY_RE = re.compile(r'\b(?:a|an|the)\b[^.]{0,44}?\b(?:who|that|which)\b', re.I)
_KM_SLEEPY_MOODS = {'lullaby', 'sleepy', 'calm', 'gentle', 'dreamy'}


def _km_derive_shelf(m):
    """First guess at where a never-filed song belongs, from the manifest the
    composer already wrote.

    This is a GUESS, and it is only ever consulted for a song with no shelf.json.
    A guess that lands wrong is corrected by filing the song — which writes the
    record — not by tuning this rule, so re-running it can never move a song
    that someone has already placed.
    """
    labels = m.get('labels') or {}
    brief = m.get('brief') or {}
    music = m.get('music') or {}
    # Both producers declare their family in the manifest; anything that does
    # not is one of the older kidsmusic songs, which predate the field.
    fam = str(m.get('family') or brief.get('family') or '').strip().lower()
    if fam not in _KM_SHELF_OK:
        fam = _KM_DEFAULT_FAMILY
    # The style the composer was ASKED for beats every heuristic below it: since
    # 2026-09-06 the children AND cinematic shelf keys are their composer's
    # style keys, so a declared style is not a hint about the shelf, it IS the
    # shelf. The mood/bpm/theme rules below stay as the fallback for the older
    # songs that predate the style field.
    style = str(m.get('style') or brief.get('style') or '').strip().lower()
    if style in _KM_SHELF_OK[fam]:
        return fam, style
    mood = str(labels.get('mood') or brief.get('mood') or '').strip().lower()
    theme = str(brief.get('theme') or '')
    try:
        bpm = float(music.get('bpm') or brief.get('bpm') or 0)
    except (TypeError, ValueError):
        bpm = 0.0
    if fam == 'children':
        if mood in _KM_SLEEPY_MOODS or (0 < bpm <= 80):
            return fam, 'sleeptime'
        if _KM_STORY_RE.search(theme):
            return fam, 'storytime'
        return fam, 'playtime'
    # Every other family: the mood label is looked up in THAT family's own
    # shelf keys (Cinematic's moods, Soundtracks' cue roles) — never in a fixed
    # list that assumes one family's vocabulary.
    for key in _KM_SHELF_OK[fam]:
        if key in mood:
            return fam, key
    if 'storytime' in _KM_SHELF_OK[fam] and _KM_STORY_RE.search(theme):
        return fam, 'storytime'
    return fam, _KM_FALLBACK_SHELF.get(fam) or _KM_FIRST_SHELF[fam]


def _km_shelf_of(song_dir, m):
    """Where a song sits: its own recorded placement first, the rule second.

    shelf.json is the RECORD — written when a song is filed, and the only thing
    a move rewrites. Reading it separately from the manifest keeps a filing
    decision out of the composer's output, so re-running a song's pipeline
    cannot silently re-file it.
    """
    try:
        with open(os.path.join(song_dir, 'shelf.json'), encoding='utf-8') as fh:
            rec = json.load(fh)
        fam = str(rec.get('family') or '').strip().lower()
        shelf = str(rec.get('shelf') or '').strip().lower()
        if fam in _KM_SHELF_OK and shelf in _KM_SHELF_OK[fam]:
            return {'family': fam, 'shelf': shelf, 'source': 'filed', 'filed': rec.get('filed') or ''}
    except (OSError, ValueError) as _exc:
        _zyg_log.warning('shelf.json in %s unreadable, the song is re-filed by derivation: %s', song_dir, _exc)
    fam, shelf = _km_derive_shelf(m)
    return {'family': fam, 'shelf': shelf, 'source': 'derived', 'filed': ''}


def _km_file_song(sid, family, shelf):
    """Record a song's shelf. Atomic, and validated against the taxonomy above —
    an unknown family/shelf pair is refused rather than written, because a shelf
    nothing can navigate to is a song that has vanished from the library."""
    d = _km_dir(sid)
    if not d:
        return {'error': 'no such song'}, 404
    if family not in _KM_SHELF_OK or shelf not in _KM_SHELF_OK[family]:
        return {'error': f'unknown shelf {family}/{shelf}'}, 400
    dst = os.path.join(d, 'shelf.json')
    tmp = dst + '.part'
    rec = {'family': family, 'shelf': shelf, 'filed': time.strftime('%Y-%m-%dT%H:%M:%S')}
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(rec, fh, indent=2)
        os.replace(tmp, dst)
    except OSError as e:
        return {'error': f'could not write shelf.json: {e}'}, 500
    _KM_CACHE.update({'ts': 0.0, 'data': None})
    _zyg_log.info(f'[KANBAN-SERVER] melody {sid} filed under {family}/{shelf}')
    return {'ok': True, 'id': sid, **rec}, 200


def _km_download_name(song_dir, fn):
    """A human filename for a downloaded song file, from the song's own title.

    Falls back to the bare leg name if the manifest is unreadable — a download
    that arrives with a dull name is fine; one that fails is not.
    """
    title = ''
    try:
        with open(os.path.join(song_dir, 'manifest.json'), encoding='utf-8') as fh:
            title = str(json.load(fh).get('title') or '')
    except (OSError, ValueError) as _exc:
        _zyg_log.debug('manifest in %s unreadable, naming the download after the leg: %s', song_dir, _exc)
    # Anything that is not a plain filename character goes. This string is
    # interpolated into a Content-Disposition header, so quotes, semicolons,
    # newlines and path separators must not survive.
    title = re.sub(r'[^A-Za-z0-9 _.,()&-]+', '', title).strip()[:70].rstrip('.')
    # `fn` can now name a file inside frames/, so the leg is taken from the
    # BASENAME and put through the same character filter as the title — a path
    # separator has no business in a Content-Disposition filename.
    leg = _KM_DL_LEG.get(fn) or os.path.splitext(os.path.basename(fn))[0]
    leg = re.sub(r'[^A-Za-z0-9 _.,()&-]+', '', leg)[:40] or 'file'
    ext = os.path.splitext(fn)[1] or '.bin'
    if not title:
        title = os.path.basename(song_dir.rstrip('/'))
    return f'{title} - {leg}{ext}'


# ── Children's series in the Melodies library (2026-09-11) ───────────────────
# The Kids Series runners deliver one folder per episode under
# output/kids_<slug>/<job>/: episode.mp4, poster.jpg and a manifest naming both.
# They used to be reachable only as Videos departments, which _api_videos now
# skips; this is where they are listed instead. Only the DELIVERED episode is a
# card — the silent/faded renders and clips/ beside it are assembly steps.
# Titles come off each episode's own manifest, never discover(): that reloads
# every runner module, which is a menu's cost, not a library poll's.
_KS_DIR_RE = re.compile(r'^kids_([a-z0-9_]{1,40})$')


def _km_series():
    """[{slug, title, episodes}] — each episode in the Videos card shape, so the
    Melodies board plays it with the same vidCardHtml the Videos library uses."""
    try:
        tops = sorted(os.listdir(_OUTPUT_ROOT))
    except OSError:
        return []
    out = []
    for top in tops:
        mt_ = _KS_DIR_RE.match(top)
        base = os.path.join(_OUTPUT_ROOT, top)
        if not mt_ or not os.path.isdir(base):
            continue
        slug, title, eps = mt_.group(1), '', []
        try:
            jobs = os.listdir(base)
        except OSError as _exc:
            _zyg_log.warning('%s not listable, its episodes are missing from the board: %s', base, _exc)
            continue
        for job in jobs:
            jd = os.path.join(base, job)
            if job.startswith('.') or 'medusa' in job.lower() or not os.path.isdir(jd):
                continue
            try:
                with open(os.path.join(jd, 'manifest.json'), encoding='utf-8') as fh:
                    man = json.load(fh)
            except (OSError, ValueError):
                man = {}
            if not isinstance(man, dict):
                man = {}
            files = man.get('files') if isinstance(man.get('files'), dict) else {}
            # basename(): a manifest names a file IN its own folder, and only that.
            vid = os.path.basename(str(files.get('episode') or 'episode.mp4'))
            pos = os.path.basename(str(files.get('poster') or 'poster.jpg'))
            fp = os.path.join(jd, vid)
            relvid = f'out/{top}/{job}/{vid}'
            # A URL /inspect/media would refuse is not handed out at all.
            if not (vid.lower().endswith('.mp4') and os.path.isfile(fp) and _MEDIA_PATH_RE.match(relvid)):
                continue
            relpos = f'out/{top}/{job}/{pos}'
            if not (os.path.isfile(os.path.join(jd, pos)) and _MEDIA_PATH_RE.match(relpos)):
                relpos = None
            try:
                mtime, size = os.path.getmtime(fp), os.path.getsize(fp)
            except OSError as _exc:
                _zyg_log.debug('%s not statable, left out of the episode list: %s', fp, _exc)
                continue
            test = bool(man.get('test_mode')) if 'test_mode' in man else job.startswith('test_')
            title = title or str(man.get('title') or '')
            label = f'Episode {man.get("episode") or "?"}'
            if test:
                label += ' · test unit'
            if isinstance(man.get('duration_s'), (int, float)):
                # '140s', not '140 s': the card caption capitalises words.
                label += f' · {man["duration_s"]:.0f}s'
            eps.append(
                {
                    'group': '',
                    'dir': f'{top}/{job}',
                    'name': vid,
                    'label': label,
                    'job': job,
                    'url': '/inspect/media?path=' + relvid,
                    'thumb': '/inspect/thumb?path=' + (relpos or relvid),
                    'still': ('/inspect/media?path=' + relpos) if relpos else '',
                    'subs': '',
                    'preview': '',
                    'mtime': round(mtime, 1),
                    'size': size,
                    'final': not test,
                    'intermediate': False,
                    'test': test,
                    'ok': man.get('ok'),
                }
            )
        eps.sort(key=lambda e: -e['mtime'])
        title = title or slug.replace('_', ' ').title()
        for e in eps:
            e['group'] = title
        out.append({'slug': slug, 'title': title, 'episodes': eps})
    out.sort(key=lambda s: s['title'].lower())
    return out


def _api_kidsmusic(force=False):
    """Every finished song, newest first, from its own manifest."""
    now = time.time()
    if not force and _KM_CACHE['data'] and (now - _KM_CACHE['ts']) < _KM_CACHE_TTL:
        return _KM_CACHE['data']
    songs = []
    # Both roots, in one pass. A root that does not exist yet is simply empty —
    # the cinematic composer may not have run on this box.
    names = []
    for root in _KM_ROOTS.values():
        try:
            names.extend(os.listdir(root))
        except OSError as _exc:
            _zyg_log.debug('%s not listable, treated as empty: %s', root, _exc)
    seen = set()
    for sid in names:
        # _km_dir resolves an id in the FIRST root that has it, so an id present
        # in both roots is one song, listed once, not the same folder twice.
        if sid in seen:
            continue
        d = _km_dir(sid)
        if not d:
            continue
        seen.add(sid)
        mf = os.path.join(d, 'manifest.json')
        try:
            with open(mf, encoding='utf-8') as fh:
                m = json.load(fh)
        except (OSError, ValueError) as _exc:
            _zyg_log.warning('%s unreadable, the song is missing from the list: %s', mf, _exc)
            continue
        files = {}
        for fn in _KM_FILES:
            fp = os.path.join(d, fn)
            if os.path.isfile(fp):
                try:
                    files[fn] = os.path.getsize(fp)
                except OSError:
                    files[fn] = 0
        lyr = ''
        try:
            with open(os.path.join(d, 'lyrics.txt'), encoding='utf-8') as fh:
                lyr = fh.read()[:1200]
        except OSError as _exc:
            _zyg_log.debug('no readable lyrics in %s: %s', d, _exc)
        sc = m.get('score') or {}
        # The picture leg. Only the storyboard's SLOT LIST is carried into the
        # list payload — the frame-by-frame CLIP scores and the beat array live
        # in storyboard.json, which the card links to. Thirty songs x hundreds of
        # beats would make this endpoint the heaviest thing on the page.
        vid = m.get('video') or {}
        board = []
        if vid.get('ok'):
            try:
                with open(os.path.join(d, 'storyboard.json'), encoding='utf-8') as fh:
                    sbj = json.load(fh)
                for s in (sbj.get('slots') or [])[:400]:
                    board.append(
                        {
                            'i': s.get('i'),
                            'start': s.get('start'),
                            'dur': s.get('dur'),
                            'pace': s.get('pace'),
                            'name': s.get('name'),
                            'role': s.get('role'),
                            'motif': s.get('motif'),
                            'idea': s.get('idea'),
                            'source': s.get('source'),
                            'render': s.get('source_render'),
                        }
                    )
            except (OSError, ValueError):
                board = []
        songs.append(
            {
                'id': sid,
                # Which library root the folder came out of — the physical fact,
                # kept apart from 'family', which is what the manifest CLAIMS.
                'root': _km_root_of(d),
                'shelf': _km_shelf_of(d, m),
                'video': {
                    'ok': bool(vid.get('ok')),
                    'file': vid.get('file'),
                    'poster': vid.get('poster'),
                    'reason': vid.get('reason'),
                    'pacing': vid.get('pacing') or {},
                    'gates': vid.get('gates') or {},
                    'verify': vid.get('verify') or {},
                    'vram': vid.get('vram') or {},
                    'generation': vid.get('generation') or {},
                    'ideas': {k: v for k, v in (vid.get('ideas') or {}).items() if k != 'llm'},
                    'storyboard': vid.get('storyboard') or {},
                    'elapsed_s': vid.get('elapsed_s'),
                },
                'slots': board,
                'title': m.get('title') or sid,
                # What the song was ASKED to be, straight off the manifest, so the
                # tab can print the style beside the shelf it derived from it.
                'style': m.get('style'),
                'family': m.get('family'),
                'created': m.get('created') or '',
                'mtime': os.path.getmtime(mf),
                'elapsed_s': m.get('elapsed_s'),
                'brief': m.get('brief') or {},
                'labels': m.get('labels') or {},
                'music': m.get('music') or {},
                'score': {
                    'total': sc.get('total'),
                    'ok': sc.get('ok'),
                    'subscores': sc.get('subscores') or {},
                    'metrics': sc.get('metrics') or {},
                    'fails': sc.get('fails') or [],
                    'warnings': sc.get('warnings') or [],
                    'seed': sc.get('seed'),
                    'candidates': sc.get('candidates'),
                },
                'gates': m.get('gates') or {},
                'delivery': m.get('delivery') or {},
                'licence': m.get('licence') or {},
                'lyrics': lyr,
                'lyrics_source': m.get('lyrics_source') or '',
                'files': files,
                # The voice leg, minus the word list (that lives in voice_report.json).
                'voice': m.get('voice') or None,
            }
        )
    songs.sort(key=lambda r: r['mtime'], reverse=True)
    # The shelf taxonomy travels WITH the songs so the board and the filing
    # rules have exactly one definition between them.
    data = {
        'songs': songs,
        'count': len(songs),
        # 'root' is the children folder name, kept for callers written
        # before the split; 'roots' is the whole truth.
        'root': os.path.basename(_KM_ROOT),
        'roots': {k: os.path.basename(v) for k, v in _KM_ROOTS.items()},
        # Children's series episodes — NOT a family: 'families' is also the
        # filing taxonomy, and an episode cannot be filed onto a shelf.
        'series': _km_series(),
        'families': [
            {'key': f, 'label': lbl, 'shelves': [{'key': k, 'label': sl} for k, sl in sh]}
            for f, lbl, sh in _KM_FAMILIES
        ],
    }
    _KM_CACHE.update({'ts': now, 'data': data})
    return data


_KM_SPEC_MOD = {'m': None, 'err': ''}


def _km_theory():
    """kids_music_theory, imported lazily and defensively (the _ALIB_MOD pattern)
    so a broken composer module costs this tab only."""
    if _KM_SPEC_MOD['m'] is None and not _KM_SPEC_MOD['err']:
        try:
            # kanban_server runs out of HERE, so the crews dir is already
            # sys.path[0] — no path juggling needed.
            from zyg_workflows import kids_music_theory as _t

            _KM_SPEC_MOD['m'] = _t
        except Exception as e:  # noqa: BLE001
            _KM_SPEC_MOD['err'] = f'{type(e).__name__}: {e}'
            _zyg_log.info(f'[KANBAN-SERVER] kids_music_theory unavailable — {_KM_SPEC_MOD["err"]}')
    return _KM_SPEC_MOD['m']


def _km_spec():
    """The composer panel builds itself from this.

    Delegates to kids_music_theory.ui_spec() — the single owner. This function
    and bp_kidsmusic.km_spec used to build the vocabulary independently and had
    already drifted apart.
    """
    T = _km_theory()
    if not T:
        return {'error': f'composer unavailable: {_KM_SPEC_MOD["err"]}'}
    return T.ui_spec()


def _km_forward(path, payload=None, method='GET', timeout=30):
    """Same-host hop to the pipeline API, the shape _creature_decide already
    uses — except no token: the kidsmusic routes are localhost-gated on the
    other side, and this process is localhost."""
    import urllib.error
    import urllib.request

    url = f'{_MAIN_APP}{path}'
    data = json.dumps(payload or {}).encode('utf-8') if method == 'POST' else None
    req = urllib.request.Request(  # noqa: S310  _MAIN_APP's scheme is checked at import
        url, data=data, method=method, headers={'Content-Type': 'application/json'}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310  # noqa: S310  scheme checked at import
            return json.loads(resp.read().decode('utf-8') or '{}'), 200
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode('utf-8') or '{}'), e.code
        except (ValueError, OSError):
            return {'error': f'pipeline API returned {e.code}'}, e.code
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {'error': f'pipeline API unreachable: {e}'[:200]}, 502


def _pe_forward(path, payload=None, method='GET', timeout=30):
    """Token-aware sibling of _km_forward, for the picture-editing routes:
    those trigger GPU work on the :5000 side and must authenticate with
    X-Zero-Public-Token, the same shape _creature_decide's inline request
    already uses — generalized here into one forwarder since there are three
    call sites (submit/job/capability), not one."""
    import urllib.error
    import urllib.request

    token = _internal_token()
    if not token:
        return {'error': 'ZERO_PUBLIC_TOKEN not set — cannot authenticate to the pipeline API'}, 503
    url = f'{_MAIN_APP}{path}'
    data = json.dumps(payload or {}).encode('utf-8') if method == 'POST' else None
    req = urllib.request.Request(  # noqa: S310  _MAIN_APP's scheme is checked at import
        url, data=data, method=method, headers={'Content-Type': 'application/json', 'X-Zero-Public-Token': token}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310  # noqa: S310  scheme checked at import
            return json.loads(resp.read().decode('utf-8') or '{}'), 200
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode('utf-8') or '{}'), e.code
        except (ValueError, OSError):
            return {'error': f'pipeline API returned {e.code}'}, e.code
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {'error': f'pipeline API unreachable: {e}'[:200]}, 502
