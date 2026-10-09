# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""storyteller_scene_service.subtitles — the subtitles section — cue wrapping, SRT/VTT writing and mp4 muxing (lines 3414-3802).

Moved verbatim out of the old single-file storyteller_scene_service.py.
"""

from __future__ import annotations

from zyg_workflows.storyteller_scene_service.constants import (
    exe,
    os,
    subprocess,
)

# ── subtitles ────────────────────────────────────────────────────────────────
# Authored as a SOFT track (mov_text), never burned in: the picture is approved
# pixel-by-pixel by this point, and burning captions would both alter it and take
# the toggle away. The cue times come from the same `events` the mix is built
# from, so subtitles cannot drift from the audio the way a re-transcription can.

_SUB_CPL = 42  # characters per line — the BBC/Netflix working limit
_SUB_MIN_S = 0.9  # a cue shorter than this flashes rather than reads
# Words a line may break BEFORE when no punctuation offers a better seam: they
# open a phrase, so the reader is not left hanging mid-group at the line end.
_SUB_WEAK_HEADS = frozenset(
    'and but or nor yet so for that which who whom whose when while where '
    'because though although if unless until after before since as than '
    'with without at by in into of on onto to from over under like'.split()
)


_NUM_WORD = {
    'zero': 0,
    'one': 1,
    'two': 2,
    'three': 3,
    'four': 4,
    'five': 5,
    'six': 6,
    'seven': 7,
    'eight': 8,
    'nine': 9,
    'ten': 10,
    'eleven': 11,
    'twelve': 12,
    'thirteen': 13,
    'fourteen': 14,
    'fifteen': 15,
    'sixteen': 16,
    'seventeen': 17,
    'eighteen': 18,
    'nineteen': 19,
    'twenty': 20,
    'thirty': 30,
    'forty': 40,
    'fifty': 50,
    'sixty': 60,
    'seventy': 70,
    'eighty': 80,
    'ninety': 90,
}
_NUM_SCALE = {'hundred': 100, 'thousand': 1000, 'million': 10**6, 'billion': 10**9}


def _sub_digits(text: str) -> str:
    """Spelled-out cardinals → digits, for SUBTITLES ONLY.

    A caption is read in the two seconds it is on screen, so 'five hundred and
    ninety three' costs the viewer the whole cue while '593' is instant. This
    deliberately does NOT touch the spec's dialogue string: that text is what
    Chatterbox is handed AND what `_take_key` hashes, so rewriting it there
    would both mispronounce the line and invalidate every cached take."""
    import re

    toks = [(bool(re.fullmatch(r"[A-Za-z']+", t)), t) for t in re.findall(r"[A-Za-z']+|[^A-Za-z']+", text)]
    words = [i for i, (isw, _) in enumerate(toks) if isw]

    def val(i):  # numeric value of word-token index i
        w = toks[i][1].lower()
        return _NUM_WORD.get(w, _NUM_SCALE.get(w))

    def joins(a, b):  # only spaces/hyphens may sit inside a number
        return all(not toks[k][0] and re.fullmatch(r'[\s-]+', toks[k][1]) for k in range(a + 1, b))

    out, wi = [], 0
    while wi < len(words):
        i = words[wi]
        if val(i) is None:
            wi += 1
            continue
        run = [i]  # extend across number words, and 'and'
        wj = wi + 1
        while wj < len(words):
            j = words[wj]
            if not joins(run[-1], j):
                break
            if val(j) is not None:
                run.append(j)
                wj += 1
            elif (
                toks[j][1].lower() == 'and'
                and wj + 1 < len(words)
                and joins(j, words[wj + 1])
                and val(words[wj + 1]) is not None
            ):
                run.extend([j, words[wj + 1]])
                wj += 2
            else:
                break
        # A SOLITARY 'one' is left spelled. It is the only number word in English
        # that is also a pronoun and a determiner — 'one of the last', 'the one
        # candle' — and nothing here can tell those from a count. Every other
        # number word is unambiguous, and a run of two or more ('twenty-one',
        # 'one thousand') is always a quantity, so only this single case is held
        # back. It also costs the viewer nothing: three letters read as fast as
        # the digit, which is not true of 'five hundred and ninety three'.
        if len(run) == 1 and toks[run[0]][1].lower() == 'one':
            wi = wj
            continue
        # 'a hundred' / 'an thousand' — absorb the article, else the caption
        # reads 'A 100'. Only for a BARE scale word; 'a' is not a count itself.
        a0 = run[0]
        if len(run) == 1 and toks[run[0]][1].lower() in _NUM_SCALE:
            prev = [k for k in words if k < run[0]]
            if prev and toks[prev[-1]][1].lower() in ('a', 'an') and joins(prev[-1], run[0]):
                a0 = prev[-1]
        # accumulate: units/tens add, 'hundred' multiplies, larger scales bank
        total = cur = 0
        for k in run:
            w = toks[k][1].lower()
            if w == 'and':
                continue
            if w == 'hundred':
                cur = (cur or 1) * 100
            elif w in _NUM_SCALE:
                total += (cur or 1) * _NUM_SCALE[w]
                cur = 0
            else:
                cur += _NUM_WORD[w]
        out.append((a0, run[-1], f'{total + cur:,}'.replace(',', ' ') if total + cur >= 10000 else str(total + cur)))
        wi = wj
    for a, b, digits in reversed(out):
        toks[a : b + 1] = [(True, digits)]
    return ''.join(t for _, t in toks)


def _sub_wrap(text: str, cpl: int = _SUB_CPL):
    """Wrap to at most TWO balanced lines, or None if it does not fit."""
    words = text.split()
    if not words:
        return None
    if len(text) <= cpl:
        return [text]
    # Break at the highest SYNTACTIC boundary that leaves both halves legal, and
    # only use balance to choose between equals. Pure balance is what produces
    # 'The men are tired and' / 'malnourished. Our ship is broken.' — legal
    # widths, and it splits a word group while burying a full stop mid-line.
    best = None
    for i in range(1, len(words)):
        a, b = ' '.join(words[:i]), ' '.join(words[i:])
        if len(a) > cpl or len(b) > cpl:
            continue
        if a[-1] in '.!?':
            rank = 0  # sentence end
        elif a[-1] in ',;:':
            rank = 1  # clause end
        elif words[i][0].islower() and words[i] in _SUB_WEAK_HEADS:
            rank = 2  # before a conjunction/preposition
        else:
            rank = 3
        score = (rank, abs(len(a) - len(b)))
        if best is None or score < best[0]:
            best = (score, [a, b])
    return best[1] if best else None


def _sub_split(text: str):
    """One line of dialogue → the cue texts it has to become.

    Sentences first (a caption that ends on a full stop reads as a unit), then
    merged back together while the merge still fits two lines, then any sentence
    still too long is broken at its own comma before falling back to words."""
    import re

    parts = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]
    out: list[str] = []
    for part in parts:
        if _sub_wrap(part):
            out.append(part)
            continue
        # too long for two lines — break at a comma if there is one, else at the
        # word nearest the middle, and recurse on both halves.
        cuts = [m.end() for m in re.finditer(r',\s+', part)]
        if cuts:
            mid = min(cuts, key=lambda c: abs(c - len(part) / 2))
            head, tail = part[:mid].strip(), part[mid:].strip()
        else:
            w = part.split()
            h = max(1, len(w) // 2)
            head, tail = ' '.join(w[:h]), ' '.join(w[h:])
        out.extend(_sub_split(head))
        out.extend(_sub_split(tail))
    # merge neighbours back while they still fit one cue, so short sentences
    # ("Our ship is broken.") do not each get their own flash card
    merged: list[str] = []
    for cue in out:
        if merged and _sub_wrap(f'{merged[-1]} {cue}'):
            merged[-1] = f'{merged[-1]} {cue}'
        else:
            merged.append(cue)
    return merged or [text]


def _srt_t(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600.0)
    m, s = divmod(rem, 60.0)
    # NOT int(s) — truncating before the .3f format silently snaps every cue to a
    # whole second, which still writes a valid SRT and reads as "the subtitles
    # lag the voice".
    return f'{int(h):02d}:{int(m):02d}:{s:06.3f}'.replace('.', ',')


def _write_srt(events: list[dict], path: str, limit_s: float | None = None) -> int:
    """SRT from the timeline's line events. Returns the cue count."""
    cues: list[tuple[float, float, str]] = []
    # 'sfx' beats are included when — and only when — they carry a sub_text.
    # A recorded sigh standing in a dialogue beat is captionable exactly like a
    # synthesised one ("[sighs]", SDH practice); an ambience one-shot with no
    # sub_text still produces no cue, because .get returns '' for it below.
    for ev in sorted((e for e in events if e.get('kind') in ('line', 'sfx')), key=lambda e: e['t0']):
        # `sub_text` lets a cue differ from what was synthesised. It exists for
        # non-speech beats: the sigh is rendered from a breath prompt whose text
        # is nonsense on the page, and SDH practice is to caption it "[sighs]".
        # An explicitly empty sub_text drops the cue entirely.
        raw = ev.get('sub_text', ev.get('text', ''))
        if ev.get('kind') == 'sfx' and 'sub_text' not in ev:
            continue
        if raw is False:
            continue
        text = _sub_digits(str(raw).strip())
        if not text:
            continue
        t0, t1 = float(ev['t0']), float(ev['t1'])
        chunks = _sub_split(text)
        # Split the line's own span by character count. The alternative — forced
        # alignment per word — buys nothing here: these cues are whole sentences
        # inside a span whose ends are already exact.
        total = sum(len(c) for c in chunks) or 1
        cur = t0
        for i, c in enumerate(chunks):
            end = t1 if i == len(chunks) - 1 else cur + (t1 - t0) * len(c) / total
            cues.append((cur, max(end, cur + _SUB_MIN_S), c))
            cur = end
    if limit_s is not None:  # never outlive the picture
        cues = [(a, min(b, limit_s), c) for a, b, c in cues if a < limit_s]
    with open(path, 'w', encoding='utf-8') as fh:
        for i, (a, b, c) in enumerate(cues, 1):
            lines = _sub_wrap(c) or [c]
            fh.write(f'{i}\n{_srt_t(a)} --> {_srt_t(b)}\n' + '\n'.join(lines) + '\n\n')
    return len(cues)


def _srt_to_vtt(srt: str, vtt: str) -> bool:
    """WebVTT beside the SRT, from the same cues.

    Browsers need this one: an HTML5 <video> ignores subtitle tracks INSIDE the
    MP4 container entirely, so the muxed mov_text track — which VLC and YouTube
    read fine — is invisible to Chrome. A page-level <track> pointing at a .vtt
    is the only thing that puts Captions in the player's overflow menu."""
    try:
        with open(srt, encoding='utf-8') as fh:
            body = fh.read()
    except OSError:
        return False
    # SRT and VTT differ here only in the header and the decimal comma.
    out = ['WEBVTT', '']
    for line in body.splitlines():
        out.append(line.replace(',', '.') if '-->' in line else line)
    with open(vtt, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out).rstrip() + '\n')
    return True


def _mp4_boxes(buf: bytes, start: int, end: int):
    """Yield (type, payload_start, box_end) for the boxes in [start, end)."""
    i = start
    while i + 8 <= end:
        size = int.from_bytes(buf[i : i + 4], 'big')
        btype = bytes(buf[i + 4 : i + 8])
        head = 8
        if size == 1:  # 64-bit largesize
            size = int.from_bytes(buf[i + 8 : i + 16], 'big')
            head = 16
        elif size == 0:  # runs to the end of the file
            size = end - i
        if size < head or i + size > end:
            return
        yield btype, i + head, i + size
        i += size


def _mp4_find(buf: bytes, start: int, end: int, btype: bytes):
    for t, ps, be in _mp4_boxes(buf, start, end):
        if t == btype:
            return ps, be
    return None


def _mp4_disable_subtitle_track(path: str, log_fn=None) -> bool:
    """Clear track_enabled on the subtitle track so it ships OFF by default.

    ffmpeg 6.1's mov muxer writes tkhd flags=3 for every track it lays down and
    ignores `-disposition:s:0 0` — verified, both `0` and `none` still come back
    as default=1 on a fresh mux. The flag is one bit in the track header, so it
    is patched in place rather than left wrong: a subtitle track advertised as
    default is one many players switch on by themselves, which is the opposite
    of a toggle."""
    log = log_fn or print
    with open(path, 'rb') as fh:
        buf = bytearray(fh.read())
    moov = _mp4_find(buf, 0, len(buf), b'moov')
    if not moov:
        return False
    hit = 0
    for t, ps, be in _mp4_boxes(buf, *moov):
        if t != b'trak':
            continue
        tkhd = _mp4_find(buf, ps, be, b'tkhd')
        mdia = _mp4_find(buf, ps, be, b'mdia')
        if not tkhd or not mdia:
            continue
        hdlr = _mp4_find(buf, *mdia, b'hdlr')
        if not hdlr:
            continue
        # hdlr payload: version(1) flags(3) predefined(4) handler_type(4)
        if bytes(buf[hdlr[0] + 8 : hdlr[0] + 12]) not in (b'sbtl', b'text', b'subt'):
            continue
        f0 = tkhd[0] + 1  # tkhd payload: version(1) flags(3)
        flags = int.from_bytes(buf[f0 : f0 + 3], 'big')
        if flags & 1:
            buf[f0 : f0 + 3] = (flags & ~1).to_bytes(3, 'big')
            hit += 1
    if not hit:
        return False
    tmp = path + '.tmp'
    with open(tmp, 'wb') as fh:
        fh.write(buf)
    os.replace(tmp, path)
    log(f'[scene] subtitle track flagged OFF by default ({hit} track header patched)')
    return True


def _mux_subs(video: str, srt: str, lang: str = 'eng', log_fn=None) -> bool:
    """Add the SRT to the MP4 as a toggleable mov_text track.

    A separate stream-COPY pass on purpose: folding the subtitle input into the
    original encode would put it under that command's `-shortest`, which decides
    output length from the shortest input — a subtitle track that ends with the
    last line would truncate the fade to black."""
    log = log_fn or print
    tmp = video.replace('.mp4', '._subs.mp4')
    r = subprocess.run(
        [
            exe('ffmpeg'),
            '-loglevel',
            'error',
            '-y',
            '-i',
            video,
            '-i',
            srt,
            # v/a only from input 0, never `-map 0`: on a file that already carries a
            # subtitle track that would keep the old one AND append the new one.
            '-map',
            '0:v',
            '-map',
            '0:a',
            '-map',
            '1',
            '-c',
            'copy',
            '-c:s',
            'mov_text',
            '-metadata:s:s:0',
            f'language={lang}',
            # asks for the track to ship OFF; movenc ignores it, so the flag is
            # patched afterwards — see _mp4_disable_subtitle_track.
            '-disposition:s:0',
            '0',
            tmp,
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0 or not os.path.isfile(tmp):
        log(f'[scene] subtitle mux failed: {r.stderr[:300]}')
        return False
    os.replace(tmp, video)
    _mp4_disable_subtitle_track(video, log_fn=log)
    return True
