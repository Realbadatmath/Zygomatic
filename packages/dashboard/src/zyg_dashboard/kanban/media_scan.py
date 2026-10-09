# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kanban/media_scan.py — the video scan with its poster thumbnails, hover previews, burned-in subtitles and image thumbnails.

Split verbatim out of ``kanban_server.py`` (lines 1501-2194) on 2026-10-06; the handler
re-imports every name from here, so ``zyg_dashboard.kanban_server.<name>`` still resolves.
"""

import os
import re
import json
import time
import hashlib
import subprocess
import threading
from zyg_workflows import provenance_seal as _seal
from zyg_dashboard.kanban.common import HERE, _FFMPEG, _MEDIA_ROOTS, _OUTPUT_ROOT, _zyg_log

# ── video scan ───────────────────────────────────────────────────────────────
# Top-level dirs that are NOT generated output: stock footage we downloaded,
# raw user uploads, remix (highlight clips cut from downloaded YouTube videos)
# and claude_clips (Claude-planned cuts of an existing source video). The
# Videos tab shows GENERATED video only, so downloaded / derived-from-download
# trees are excluded entirely — the intermediates toggle must not reveal them.
# kidsmusic (2026-09-02): the children's-music tree has its own browser — the
# Melodies tab lists output/kidsmusic/<job>/ one card per SONG, with the audio,
# the score and the picture leg together. Its videos were also landing here as a
# 'kidsmusic' department (7 cards), which is a second, worse view of the same
# runs: no song context, and 'video.mp4' repeated per job. Excluded wholesale,
# in both modes, like the other trees that are browsed somewhere else.
_VID_SKIP_TOP = {'stocks', 'stock', 'uploads', 'bench_assets', 'assets', 'remix', 'claude_clips', 'kidsmusic'}
# kids_<slug> (2026-09-11): the children's SERIES trees (kids_series_common
# writes output/kids_<slug>/<job>/) were still arriving as ten 'Kids …'
# departments. Operator rule: children's and melody video is seen in Melodies
# ONLY — _km_series() lists these episodes there. Matched by PREFIX, not listed,
# because a series is added by dropping in a pipeline_kids_*.py, and a fixed
# set here would let the eleventh straight back into Videos.
_VID_SKIP_PREFIX = ('kids_',)
# Downloaded YouTube sources and the cuts made from them sit INSIDE documentary
# job folders (Stage 4a downloads into output_dir), recognised two ways:
# (1) ground truth — Stage 4a writes '<video_id>_transcript.json' beside every
#     download, so any mp4 sharing that id prefix in the same folder is
#     downloaded content ('<id>.mp4' raw, '<id>_clipN[_norm].mp4' cuts);
# (2) fallback when the transcript json is gone — the cut naming pattern
#     itself: an 11-char YouTube id + '_clipN'. Generated finals are slug-named
#     ('sikh_empire.mp4', 'scholarly_final.mp4') and never carry that suffix.
_VID_DL_CUT_RE = re.compile(r'^[A-Za-z0-9_-]{11}_clip\d+(_norm)?\.mp4$', re.IGNORECASE)
# Path segments that mark a working file rather than a deliverable.
_VID_TMP_SEGS = {'_kb_tmp', '_frames', 'wan_clips', 'clips', 'segments', 'scenes', 'tmp', 'work', 'parts', '_tmp'}
# SUPERSEDED CUTS (2026-08-21). Re-rendering a scene in place means keeping the
# outgoing cut, and the house habit is a '_prev_<what-changed>/' folder beside
# it — _prev_cut_2026-08-11, _prev_synth_sigh, _prev_broken_voice. Those copies
# were landing in the grid as full deliverables, so one scene showed four
# near-identical 'Cornelis Day1' cards differing only by timestamp and a
# megabyte, and picking the current one meant reading file sizes. A superseded
# cut IS a working file by this tab's own definition — real output, not the one
# you want now — so it hides with the rest and comes back under `show working
# files`. Matched by prefix, because the suffix names whatever changed.
_VID_PREV_SEG_RE = re.compile(r'^_prev[_-]', re.IGNORECASE)
# 2026-08-25 (P-03): a job that aborts before Cleanup leaves its _graded /
# _slideshow / _subtitled renders beside the final — docsmoke-da17fb8a showed
# all three as deliverables. Those suffixes name pipeline STAGES, never a final.
_VID_TMP_FILE_RE = re.compile(
    r'^(kb_\d+|seg_?\d+|scene_?\d+|part_?\d+|chunk_?\d+|clip_?\d+|_).*\.mp4$'
    r'|^.*_(graded|slideshow|subtitled)\.mp4$',
    re.IGNORECASE,
)
# SMOKE / GATECHECK JOBS (2026-08-25, P-03). Test runs write real mp4s into
# real job folders and this tab showed them as deliverables — 19 of the 339
# documentary cards on the day of the Florence autopsy were docsmoke-* or
# gatecheck-* renders, the top card included. A test job folder is an
# INTERMEDIATE here: hidden by default, back under `show working files`.
# Two signals: the job id prefix (the shared predicate in pipeline_common —
# this process is stdlib-only, so that import is guarded and the regex is the
# fallback) and the SMOKE_RUN marker file the pipeline drops into out_dir.
# The bare 'smoke' prefix is only trusted under data/output, where folder
# names ARE pipeline ids; under output/ an effects scene may well be called
# 'smoke_plume', so there only the explicit prefixes and the marker count.
_VID_SMOKE_JOB_RE = re.compile(r'^(docsmoke-|gatecheck-|introsmoke-|smoke)', re.IGNORECASE)
_VID_SMOKE_JOB_STRICT_RE = re.compile(r'^(docsmoke-|gatecheck-|introsmoke-)', re.IGNORECASE)
_VID_SMOKE_MARKER = 'SMOKE_RUN'
try:
    from zyg_workflows.pipeline_common import (
        is_test_pipeline_id as _pc_is_test_pipeline_id,  # noqa: E402
        SMOKE_MARKER_FILE as _VID_SMOKE_MARKER,
    )
except Exception as _pc_err:
    _zyg_log.info(f'[KANBAN] pipeline_common unavailable ({_pc_err}) — using the local test-id regex')
    _pc_is_test_pipeline_id = None


def _vid_is_test_job(name, strict=False):
    """Is this job-folder name a smoke/gatecheck id? strict=True ignores the
    bare 'smoke' prefix (see the note above about effects scenes)."""
    name = name or ''
    if strict:
        return bool(_VID_SMOKE_JOB_STRICT_RE.match(name))
    if _pc_is_test_pipeline_id is not None:
        try:
            return bool(_pc_is_test_pipeline_id(name))
        except Exception as _exc:
            _zyg_log.debug('test-id helper refused %r, falling back to the regex: %s', name, _exc)
    return bool(_VID_SMOKE_JOB_RE.match(name))


# Department label per (root key, first path segment).
_VID_GROUPS = (
    ('dout', 'clips', 'documentary'),
    # Remix Ai (2026-08-29) — its own subtab in the Videos grid. The tree is
    # data/output/remix_ai/<pid>/, and unlike the 'remix' tree it is NOT in
    # _VID_SKIP_TOP: remix delivers cuts OF third-party video, which this tab
    # exists not to show, while remix_ai delivers fully generated frames. The
    # source it studied is deleted by the pipeline before delivery, and any that
    # survives a crash is still hidden by the '<id>_transcript.json' sidecar rule
    # below.
    ('dout', 'remix_ai', 'remix ai'),
    ('dout', 'storyteller', 'storyteller'),
    ('dout', 'tokitoki', 'tokitoki'),
    ('out', 'storyteller', 'storyteller'),
    ('out', 'environments', 'environments'),
    ('out', 'effects', 'effects'),
    ('out', 'wardrobe', 'wardrobe'),
    ('out', 'video_studio', 'video studio'),
)
_VID_CACHE = {'ts': 0.0, 'key': None, 'data': None}
_VID_CACHE_TTL = 20.0

# ── poster thumbnails ────────────────────────────────────────────────────────
# 2026-08-11: the grid used to mount a <video preload="metadata"> per clip. At
# 918 clips that is 918 media elements each opening a connection into a
# multi-hundred-MB file — Chrome went "Page Unresponsive". Cards now show a
# small cached JPEG and only build a <video> when the operator clicks play.
# Extraction is one ffmpeg seek-frame per clip, cached on disk forever (keyed by
# path+mtime), and capped so a cold grid cannot storm the CPU.
_THUMB_DIR = os.path.join(HERE, 'data', 'runtime', '.vidthumbs')
_THUMB_SEM = threading.Semaphore(4)
_THUMB_W = 480


def _thumb_path(fp, mtime):
    key = hashlib.sha1(f'{fp}|{int(mtime)}|{_THUMB_W}'.encode(), usedforsecurity=False).hexdigest()
    return os.path.join(_THUMB_DIR, key + '.jpg')


# ── hover previews ───────────────────────────────────────────────────────────
# 2026-09-01: a poster says what a clip looks like at one instant; it says
# nothing about the moment the clip is FOR. A preview is a short, silent,
# small cut of the clip that plays under the pointer and stops when the
# pointer leaves — once, never looped.
#
# The in/out points are OPERATOR-CHOSEN, not derived: "from 26s until the DAY 1
# card" is a judgement about this cut, and no generic rule (first N seconds,
# middle of the clip) would land on it. So previews are opt-in per clip through
# the registry below, keyed by the same '<rootkey>/<relpath>' string the media
# URLs use. A clip with no entry gets no preview and no hover behaviour at all
# — which is the honest default: an auto-cut preview would be claiming to show
# the point of a clip nobody has looked at.
_PREVIEW_DIR = os.path.join(HERE, 'data', 'runtime', '.vidpreviews')
_PREVIEW_REG = os.path.join(HERE, 'data', 'runtime', 'vid_previews.json')
_PREVIEW_SEM = threading.Semaphore(2)
_PREVIEW_W = 480  # card-sized; a preview is never fullscreened
_PREVIEW_MAX_S = 30.0  # a hover that outlives the pointer is a bug
_PREVIEW_CACHE = {'ts': 0.0, 'mt': -1.0, 'reg': {}}


def _preview_registry():
    """{'<rootkey>/<relpath>': {'start': float, 'end': float}} from disk.

    Re-read when the file's mtime moves, so adding a preview is a JSON edit
    and not a restart. A malformed or missing file means 'no previews', never
    a 500 on the videos list."""
    now = time.time()
    c = _PREVIEW_CACHE
    if now - c['ts'] < 5.0:
        return c['reg']
    c['ts'] = now
    try:
        mt = os.path.getmtime(_PREVIEW_REG)
    except OSError:
        c['mt'], c['reg'] = -1.0, {}
        return c['reg']
    if mt == c['mt']:
        return c['reg']
    reg = {}
    try:
        with open(_PREVIEW_REG, encoding='utf-8') as fh:
            raw = json.load(fh)
        for k, v in (raw.get('previews') or {}).items():
            try:
                st, en = float(v['start']), float(v['end'])
            except (TypeError, ValueError, KeyError) as _exc:
                _zyg_log.debug('preview %s has no usable start/end, skipped: %s', k, _exc)
                continue
            if en > st >= 0:
                reg[k] = {'start': st, 'end': min(en, st + _PREVIEW_MAX_S)}
    except (OSError, ValueError, AttributeError) as e:
        _zyg_log.info(f'[KANBAN-SERVER] preview registry unreadable: {e!r}')
        reg = {}
    c['mt'], c['reg'] = mt, reg
    return reg


def _featured_preview():
    """The one preview the Library's Videos TILE shows, or {}.

    The tile is the card you see before opening anything, and it was icon-only
    — nothing to look at and nothing to hover. It now borrows a preview from
    the registry: the entry flagged '"featured": true', else the only entry
    when there is exactly one. Chosen in the registry rather than hardcoded in
    the page so moving it is the same JSON edit as adding one, and so a renamed
    or deleted clip degrades to the old icon instead of a broken tile."""
    reg = _preview_registry()
    if not reg:
        return {}
    try:
        with open(_PREVIEW_REG, encoding='utf-8') as fh:
            raw = json.load(fh).get('previews') or {}
    except (OSError, ValueError, AttributeError):
        raw = {}
    picks = [k for k in reg if (raw.get(k) or {}).get('featured')]
    if not picks and len(reg) == 1:
        picks = list(reg)
    if not picks:
        return {}
    rel = picks[0]
    head, _, tail = rel.partition('/')
    root = _MEDIA_ROOTS.get(head, _OUTPUT_ROOT)
    fp = os.path.realpath(os.path.join(root, tail if head in _MEDIA_ROOTS else rel))
    if not (fp.startswith(root + os.sep) and os.path.isfile(fp)):
        return {}
    return {
        'thumb': '/inspect/thumb?path=' + rel,
        'preview': '/inspect/preview?path=' + rel,
        'label': os.path.splitext(os.path.basename(fp))[0].replace('_', ' '),
    }


def _preview_path(fp, mtime, start, end):
    sig = f'{fp}|{int(mtime)}|{start:.3f}|{end:.3f}|{_PREVIEW_W}'
    return os.path.join(_PREVIEW_DIR, hashlib.sha1(sig.encode(), usedforsecurity=False).hexdigest() + '.mp4')


def _make_preview(fp, dst, start, end):
    """Cut [start, end) out of `fp` → a small silent mp4. Returns True on success.

    -an is not a stylistic choice: the card plays this under the pointer, and a
    clip that makes noise on mouseover is unusable in a grid. Re-encoded rather
    than stream-copied because a copy can only start at a keyframe, which would
    move the in-point off the frame that was actually chosen."""
    os.makedirs(_PREVIEW_DIR, exist_ok=True)
    tmp = dst + '.part'
    cmd = [
        _FFMPEG,
        '-nostdin',
        '-loglevel',
        'error',
        '-y',
        '-threads',
        '2',
        '-ss',
        f'{start:.3f}',
        '-i',
        fp,
        '-t',
        f'{max(0.1, end - start):.3f}',
        '-an',
        '-vf',
        f'scale={_PREVIEW_W}:-2',
        '-c:v',
        'libx264',
        '-preset',
        'veryfast',
        '-crf',
        '26',
        '-pix_fmt',
        'yuv420p',
        '-movflags',
        '+faststart',
        '-f',
        'mp4',
        tmp,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        _zyg_log.info(f'[KANBAN-SERVER] preview failed for {os.path.basename(fp)}: {str(e)[:200]}')
        return False
    if r.returncode == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
        os.replace(tmp, dst)
        return True
    _zyg_log.info(
        f'[KANBAN-SERVER] preview failed for {os.path.basename(fp)}: '
        f'{(r.stderr or b"").decode("utf-8", "replace")[:300]}'
    )
    try:
        os.remove(tmp)
    except OSError as _exc:
        _zyg_log.debug('preview temp %s not removed: %s', tmp, _exc)
    return False


# ── "subtitles on" download copy ─────────────────────────────────────────────
# The soft mov_text track in the delivered mp4 ships OFF, and whether a player
# turns it on is the PLAYER's decision — VLC, QuickTime, a phone gallery and a
# messaging app all answer differently, and several ignore soft tracks entirely.
# So the yes-please copy BURNS the captions into the picture: that is the only
# form that survives being sent to someone else. It costs a re-encode of the
# video (audio is stream-copied, so the approved mix is untouched), hence the
# cache — the second request for the same clip is a file read.
_SUBBURN_DIR = os.path.join(HERE, 'data', 'runtime', '.vidsubburn')
_SUBBURN_SEM = threading.Semaphore(1)  # transcodes are heavy; one at a time
# Plain white text: no ring around the glyphs (Outline=0) and no drop shadow
# under them (Shadow=0), both by operator direction. That leaves NOTHING
# separating the captions from the picture, which is fine on this scene because
# the lower frame is dark throughout — but a bright or busy plate underneath
# will read as low contrast, and the fix would have to be a shadow or an
# outline, i.e. the two things just removed.
# MarginV is in ASS SCRIPT units, not screen pixels: ffmpeg's SRT decoder emits
# a script at PlayResY=288 and libass scales it to the frame, so one unit is
# H/288 px — 2.67 px on the 768-tall scenes. That makes the setting a PERCENTAGE
# of frame height, which is also how the standards express it, so a 1080-tall
# clip lands in the same relative place. MarginV/2.88 = percent of height.
#
# Measured on the Abel scene at t=5 s (bottom ink row, frame height 768):
#   MarginV 28 → 77 px → 10.0%   SMPTE/EBU TITLE safe — the broadcast+cinema rule
#   MarginV 23 → 64 px →  8.3%   typical modern streaming caption position
#   MarginV 14 → 40 px →  5.2%   SMPTE/EBU ACTION safe — the lowest standard line
# 14 by operator direction: 28 read as too high on this scene. Note that 28 was
# not arbitrary — it WAS the title-safe standard — so this trades conformance for
# the requested look, and anything below 14 leaves the standards behind entirely.
_SUBBURN_STYLE = (
    'FontName=DejaVu Sans,FontSize=19,PrimaryColour=&H00FFFFFF&,BorderStyle=1,Outline=0,Shadow=0,MarginV=14'
)
# `-tune grain`, NOT the bare crf 18 that first shipped. These scenes bake in
# film grain and particles, and a second-generation encode at default psy
# settings throws part of that away — which is why the burnt copy came out 13 MB
# SMALLER than the master instead of larger. Measured full-clip WITH the captions
# burnt in and the audio muxed — i.e. exactly what this builds — vs a 67.2 MB
# master, all on the same caption-free window:
#   crf 18 medium (was)  57.3 MB   SSIM 0.9705   PSNR 42.7 dB   ← lost detail
#   crf 18 slow grain    74.4 MB   SSIM 0.9783   PSNR 45.5 dB   ← shipping
#   crf 19 slow grain    63.5 MB   SSIM 0.9736   PSNR 44.6 dB
#   crf 20 slow grain    52.8 MB   SSIM 0.9677   PSNR 43.8 dB
# Landing slightly ABOVE the master is the correct shape for a second generation:
# reproducing the first encode's own grain costs more bits than creating it did.
# TWO measurement traps, both of which bit while picking this number:
#  • Tune on the WHOLE clip, never a sample. The pull-out at 27-34 s runs 26 Mbps
#    against the film's 13 Mbps average; tuning on that window alone chose crf 12
#    — a 161 MB file for 43 seconds.
#  • Encode WITH the subtitles burnt in. Video-only trials read ~10 MB light,
#    because high-contrast text is expensive and it shifts the rate allocation.
_SUBBURN_VENC = ['-c:v', 'libx264', '-crf', '18', '-preset', 'slow', '-tune', 'grain', '-pix_fmt', 'yuv420p']


def _subburn_path(fp, mtime):
    # Encode settings are IN the key, not just the style: without them a crf or
    # tune change would keep serving the previously cached copy forever.
    sig = f'{fp}|{int(mtime)}|{_SUBBURN_STYLE}|{" ".join(_SUBBURN_VENC)}'
    return os.path.join(_SUBBURN_DIR, hashlib.sha1(sig.encode(), usedforsecurity=False).hexdigest() + '.mp4')


def _make_subburn(fp, srt, dst):
    """Burn `srt` into `fp` → `dst`. Returns True on success.

    Runs with cwd set to the clip's own directory and passes BASENAMES to the
    subtitles filter: a lavfi filter argument re-parses ':' and ',' out of the
    value, and the legacy tree's absolute path contains a space in its root name,
    so keeping the filter value to a bare sidecar name sidesteps the escaping
    entirely. force_style is quoted for the same reason — it has commas in it."""
    os.makedirs(_SUBBURN_DIR, exist_ok=True)
    tmp = dst + '.part'
    cmd = [
        _FFMPEG,
        '-nostdin',
        '-loglevel',
        'error',
        '-y',
        '-i',
        os.path.basename(fp),
        '-vf',
        f"subtitles={os.path.basename(srt)}:force_style='{_SUBBURN_STYLE}'",
        # -sn: do NOT also carry the soft track through. A player that honours
        # it would draw a second copy of every caption over the burnt-in one.
        '-map',
        '0:v:0',
        '-map',
        '0:a:0',
        '-sn',
        *_SUBBURN_VENC,
        '-c:a',
        'copy',
        '-movflags',
        '+faststart',
        '-f',
        'mp4',
        tmp,
    ]
    try:
        r = subprocess.run(cmd, cwd=os.path.dirname(fp), capture_output=True, timeout=1800)
    except (OSError, subprocess.SubprocessError) as e:
        _zyg_log.info(f'[KANBAN-SERVER] subburn failed for {os.path.basename(fp)}: {str(e)[:200]}')
        return False
    if r.returncode == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
        os.replace(tmp, dst)
        # The re-encode drops the master's manifest, so the burnt-in copy is signed again
        # with the master named as its parent ingredient. Fail-safe: never breaks a preview.
        _seal.seal_derived(dst, fp, pipeline='subburn')
        return True
    _zyg_log.info(
        f'[KANBAN-SERVER] subburn failed for {os.path.basename(fp)}: '
        f'{(r.stderr or b"").decode("utf-8", "replace")[:300]}'
    )
    try:
        os.remove(tmp)
    except OSError as _exc:
        _zyg_log.debug('subburn temp %s not removed: %s', tmp, _exc)
    return False


def _make_thumb(fp, dst):
    """One frame → small JPEG. Seeks 1s in (frame 0 is often black on a fade-in)
    and falls back to frame 0 for clips shorter than that."""
    os.makedirs(_THUMB_DIR, exist_ok=True)
    tmp = dst + '.part'
    vf = f'scale={_THUMB_W}:-2'
    err = ''
    # 2026-09-01: the third attempt (no -ss at all) is what makes a STILL poster
    # work. A single JPEG/PNG is one frame the image2 demuxer gives a 0.04s
    # duration, so ANY seek — 00:00:00 included — lands past the end: ffmpeg
    # decodes nothing, writes no file and still EXITS 0. Both seeking attempts
    # therefore failed silently and the poster 404'd, measured on all 7
    # kidsmusic cards, whose poster.jpg is a perfectly good 1920x1080 still.
    for ss in ('00:00:01', '00:00:00', None):
        # -f image2 is REQUIRED: the atomic '.part' temp name gives ffmpeg no
        # extension to infer a muxer from, and it exits 234 without it.
        cmd = [
            _FFMPEG,
            '-nostdin',
            '-loglevel',
            'error',
            '-threads',
            '2',
            *(('-ss', ss) if ss else ()),
            '-i',
            fp,
            '-frames:v',
            '1',
            '-vf',
            vf,
            '-q:v',
            '5',
            '-f',
            'image2',
            '-y',
            tmp,
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=45)
            err = (r.stderr or b'').decode('utf-8', 'replace')[:200]
        except (OSError, subprocess.SubprocessError) as e:
            err = str(e)[:200]
            break
        if os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
            os.replace(tmp, dst)
            return True
    try:
        os.remove(tmp)
    except OSError as _exc:
        _zyg_log.debug('thumb temp %s not removed: %s', tmp, _exc)
    _zyg_log.info(f'[KANBAN-SERVER] thumb failed for {os.path.basename(fp)}: {err}')
    return False


# ── static image thumbnails (Pictures / Creatures grids) ────────────────────
# 2026-08-31: Pictures and Creatures serve full-resolution originals into a
# grid of dozens of <img> tags (see _serve_image / _creature_img below), which
# is what made those two tabs feel slow next to Videos — the video grid has
# had a small cached poster since 2026-08-11 (_make_thumb above). Same fix
# here: a thumb=1 request gets a small cached JPEG, keyed by path+mtime+width
# so an edited source regenerates on its own; the plain endpoint is untouched
# for a lightbox/zoom view.
_IMG_THUMB_DIR = os.path.join(HERE, 'data', 'runtime', '.imgthumbs')
_IMG_THUMB_W = 480


def _img_thumb_path(fp, mtime, w):
    key = hashlib.sha1(f'{fp}|{int(mtime)}|{w}'.encode(), usedforsecurity=False).hexdigest()
    return os.path.join(_IMG_THUMB_DIR, key + '.jpg')


def _make_img_thumb(fp, dst, w):
    """Resize one image to width `w` (aspect preserved, never upscaled) → cached JPEG."""
    try:
        from PIL import Image
    except ImportError:
        return False
    os.makedirs(_IMG_THUMB_DIR, exist_ok=True)
    tmp = dst + '.part'
    try:
        with Image.open(fp) as im:
            im = im.convert('RGB')
            if im.width > w:
                h = max(1, round(im.height * w / im.width))
                im = im.resize((w, h), Image.LANCZOS)
            im.save(tmp, 'JPEG', quality=82)
        os.replace(tmp, dst)
        return True
    except Exception as e:
        _zyg_log.info(f'[KANBAN-SERVER] image thumb failed for {os.path.basename(fp)}: {str(e)[:200]}')
        try:
            os.remove(tmp)
        except OSError as _exc:
            _zyg_log.debug('image thumb temp %s not removed: %s', tmp, _exc)
        return False


def _vid_group(root_key, seg0):
    for rk, s0, label in _VID_GROUPS:
        if rk == root_key and seg0 == s0:
            return label
    if seg0.startswith('multichar'):
        return 'multichar'
    if seg0.startswith('quarantine'):
        return 'quarantine'
    if seg0.startswith('video_pipeline'):
        return 'video'
    if seg0.startswith('manga_pipeline'):
        return 'manga'
    if seg0.startswith('assetlib'):
        return 'asset library'
    return seg0.replace('_', ' ')[:28] or root_key


def _api_videos(scope='', intermediates=False):
    """Every generated video across all three output trees, with a poster still
    when one sits beside it. Read-only; served via /inspect/media.

    Deliverables (a file sitting directly in its job folder) are returned always;
    working files — Ken-Burns slot temps, per-scene wan clips, in-flight pipeline
    dirs, quarantine, and SUPERSEDED CUTS kept in a '_prev*' folder — only when
    intermediates=1, because they outnumber the deliverables and drown the list.

    Downloaded videos and cuts made from them (2026-08-13) are NEVER returned,
    in either mode — this tab inspects generations only. Excluded: the remix
    and claude_clips trees wholesale (_VID_SKIP_TOP), plus YouTube sources and
    their '<id>_clipN[_norm].mp4' cuts inside documentary job folders (matched
    by the sibling '<id>_transcript.json' Stage 4a leaves, with _VID_DL_CUT_RE
    as fallback). Count reported as hidden_downloads, shown in the header.

    Medusa: scope=medusa returns an empty list, and any path containing 'medusa'
    is skipped in every scope. Medusa is a single-character swimwear/LoRA image
    generator that produces no video today, and there is no per-video origin tag
    anywhere in this data (verified: zero char_id|department|medusa hits in a
    live scene dir's CHECKPOINTS.json / debug/report.json). Empty is the honest
    answer for that scope — a guessed heuristic could leak content either way."""
    if scope == 'medusa':
        return {
            'videos': [],
            'groups': [],
            'total': 0,
            'hidden_intermediates': 0,
            'hidden_downloads': 0,
            'hidden_tests': 0,
        }
    ck = bool(intermediates)
    now = time.time()
    if _VID_CACHE['data'] is not None and _VID_CACHE['key'] == ck and (now - _VID_CACHE['ts']) < _VID_CACHE_TTL:
        return _VID_CACHE['data']

    preview_reg = _preview_registry()
    vids, hidden, hidden_dl, hidden_tests = [], 0, 0, 0
    for root_key, root in _MEDIA_ROOTS.items():
        if not os.path.isdir(root):
            continue
        try:
            tops = sorted(os.listdir(root))
        except OSError as _exc:
            _zyg_log.warning('media root %s not listable, its videos are missing from the board: %s', root, _exc)
            continue
        for top in tops:
            if (
                top in _VID_SKIP_TOP
                or top.startswith(_VID_SKIP_PREFIX)
                or top.startswith('.')
                or 'medusa' in top.lower()
            ):
                continue
            base = os.path.join(root, top)
            if not os.path.isdir(base):
                continue
            for dirpath, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if 'medusa' not in d.lower()]
                mp4s = [f for f in files if f.lower().endswith('.mp4')]
                if not mp4s:
                    continue
                reldir = os.path.relpath(dirpath, root).replace(os.sep, '/')
                segs = reldir.split('/')
                # ids of YouTube videos downloaded into THIS folder (Stage 4a
                # leaves '<id>_transcript.json' beside every download)
                dl_ids = {f[: -len('_transcript.json')] for f in files if f.endswith('_transcript.json')}
                # poster: any still already in this folder (cheap — files listed)
                poster = None
                for cand in ('multichar_still.png', 'FINAL_still_plate.png'):
                    if cand in files:
                        poster = cand
                        break
                if poster is None:
                    stills = sorted(f for f in files if f.lower().endswith(('.png', '.jpg')) and not f.startswith('_'))
                    poster = stills[0] if stills else None
                group = _vid_group(root_key, segs[0])
                # P-03: smoke/gatecheck JOB? The job folder is the segment under
                # the tree root ('clips/<id>', 'storyteller/<id>'); the marker
                # sits in that folder, so look there as well as in the current
                # dir (bed/, flux_images/ … carry no marker of their own).
                job_seg = segs[1] if len(segs) > 1 else segs[0]
                job_dir = os.path.join(root, *segs[:2]) if len(segs) > 1 else dirpath
                test_job = (
                    _vid_is_test_job(job_seg, strict=(root_key != 'dout'))
                    or _VID_SMOKE_MARKER in files
                    or os.path.isfile(os.path.join(job_dir, _VID_SMOKE_MARKER))
                )
                dir_is_tmp = (
                    root_key == 'drun'
                    or group == 'quarantine'
                    or test_job
                    or any(s in _VID_TMP_SEGS for s in segs[1:])
                    or any(_VID_PREV_SEG_RE.match(s) for s in segs[1:])
                )
                for fn in mp4s:
                    if 'medusa' in fn.lower():
                        continue
                    # downloaded content is excluded in BOTH modes — the
                    # intermediates toggle shows working GENERATIONS, never
                    # downloads or cuts of downloads
                    stem0 = fn[:-4]
                    if _VID_DL_CUT_RE.match(fn) or stem0 in dl_ids or any(stem0.startswith(i + '_') for i in dl_ids):
                        hidden_dl += 1
                        continue
                    inter = dir_is_tmp or bool(_VID_TMP_FILE_RE.match(fn))
                    if inter and not intermediates:
                        hidden += 1
                        if test_job:
                            hidden_tests += 1
                        continue
                    fp = os.path.join(dirpath, fn)
                    try:
                        mt, sz = os.path.getmtime(fp), os.path.getsize(fp)
                    except OSError as _exc:
                        _zyg_log.debug('%s not statable, left out of the video list: %s', fp, _exc)
                        continue
                    stem = fn.rsplit('.', 1)[0]
                    final = fn.upper().startswith('FINAL') or stem.lower().endswith('_final')
                    label = stem.replace('FINAL_', '').replace('_final', '').replace('_', ' ').strip() or stem
                    relvid = f'{root_key}/{reldir}/{fn}' if reldir != '.' else f'{root_key}/{fn}'
                    relposter = (
                        (f'{root_key}/{reldir}/{poster}' if reldir != '.' else f'{root_key}/{poster}')
                        if poster
                        else None
                    )
                    # Sibling WebVTT written by the renderer → the card mounts a
                    # <track> and the browser offers Captions. Absent for every
                    # clip that has none, which is most of them.
                    subs = f'{stem}.vtt' if os.path.isfile(os.path.join(dirpath, f'{stem}.vtt')) else None
                    relsubs = (
                        (f'{root_key}/{reldir}/{subs}' if reldir != '.' else f'{root_key}/{subs}') if subs else None
                    )
                    # Thumb from the still beside the clip when there is one
                    # (instant), else one seek-frame out of the video itself.
                    vids.append(
                        {
                            'group': group,
                            'dir': reldir,
                            'name': fn,
                            'label': label,
                            'job': segs[1] if len(segs) > 1 else segs[0],
                            'url': '/inspect/media?path=' + relvid,
                            'thumb': '/inspect/thumb?path=' + (relposter or relvid),
                            # 2026-09-08: the FULL-resolution still, for anything
                            # that mounts a real player. 'thumb' is a 480px jpeg —
                            # fine on a card, but as a <video poster> it becomes the
                            # element's intrinsic size AND the picture shown before
                            # play, so a fullscreen before the first frame upscaled
                            # a 480px thumbnail. Empty when the clip has no still.
                            'still': ('/inspect/media?path=' + relposter) if relposter else '',
                            'subs': ('/inspect/media?path=' + relsubs) if relsubs else '',
                            # Opt-in silent hover cut. Empty for every clip without a
                            # registry entry, and the card keys its hover on that —
                            # so an unregistered card behaves exactly as it did before.
                            'preview': ('/inspect/preview?path=' + relvid if relvid in preview_reg else ''),
                            'mtime': round(mt, 1),
                            'size': sz,
                            'final': final,
                            'intermediate': inter,
                            'test': test_job,
                        }
                    )
    vids.sort(key=lambda v: -v['mtime'])
    groups = sorted({v['group'] for v in vids})
    data = {
        'videos': vids,
        'groups': groups,
        'total': len(vids),
        'hidden_intermediates': hidden,
        'hidden_downloads': hidden_dl,
        'hidden_tests': hidden_tests,
    }
    _VID_CACHE.update(ts=now, key=ck, data=data)
    return data
