# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 6d helpers: the asset pools, the tag timeline, the ffmpeg passes and the cleanup.

Extracted verbatim from `_crime_stage_6d_assembly`, which keeps the orchestration and
calls the steps below in the same order with the same side effects.
"""

from dataclasses import dataclass, field

from .constants import (
    _finish_subproc,
    _register_subproc,
    _zyg_log,
    exe,
    json,
    os,
)


@dataclass
class _AssetPools:
    """Sequential cursors over the doc-card and still-image pools of one 6d run.

    Each `next_*` call hands out the next entry and advances; the pools cycle rather
    than run dry, and an empty pool yields None.
    """

    doc_pool: list
    img_pool: list
    doc_cursor: int = 0
    img_cursor: int = 0

    def next_img(self):
        """Return the next still image path, or None when there are no images."""
        if not self.img_pool:
            return None
        p = self.img_pool[self.img_cursor % len(self.img_pool)]
        self.img_cursor += 1
        return p

    def next_doc(self):
        """Return the next doc-card path, or None when there are no doc cards."""
        if not self.doc_pool:
            return None
        p = self.doc_pool[self.doc_cursor % len(self.doc_pool)]
        self.doc_cursor += 1
        return p


@dataclass
class _SegmentCtx:
    """What the 6d timeline loop needs to turn one narrated moment into a clip.

    `img_to_clip` and `person_infobox_clip` are the renderers stage 6c returned;
    `shown_persons` is the caller's set (an info box is injected once per person) and
    `shown_persons_set` is this run's own record, which suppresses the person photo
    right after its info box.
    """

    img_to_clip: object
    person_infobox_clip: object
    log: object
    pools: _AssetPools
    named_persons: dict
    location_images: dict
    person_time_triggers: dict
    shown_persons: set
    sentence_times: list = field(default_factory=list)
    shown_persons_set: set = field(default_factory=set)


def _probe_clip_durations(stock_clips, _sp_crime):
    """Return [(path, duration_seconds)] for every stock clip; 60.0 when ffprobe fails."""
    _clip_info = []
    for _sc in stock_clips:
        try:
            _dr = _sp_crime.run(
                [exe('ffprobe'), '-v', 'quiet', '-print_format', 'json', '-show_format', _sc],
                capture_output=True,
                text=True,
                timeout=10,
            )
            _dur = float(json.loads(_dr.stdout).get('format', {}).get('duration', 60))
            _clip_info.append((_sc, _dur))
        except Exception:
            _clip_info.append((_sc, 60.0))
    return _clip_info


def _sentence_start_times(_word_timings, _visual_tags):
    """Align the stage-3b visual tags with the narration clock.

    Returns [(start_sec, tag_type, tag_subject)], one entry per tag, by matching each
    tagged sentence's first word in `_word_timings`; an unmatched sentence inherits the
    previous start time. Either input empty gives [].
    """
    _sentence_times = []
    if _word_timings and _visual_tags:
        _wt_idx = 0
        for _vt in _visual_tags:
            _sent_words = _vt['sentence'].split()
            if not _sent_words:
                _sentence_times.append((0.0, _vt['type'], _vt['subject']))
                continue
            _found = False
            for _wi in range(max(0, _wt_idx - 5), min(len(_word_timings), _wt_idx + len(_sent_words) + 20)):
                if _word_timings[_wi][0].lower() == _sent_words[0].lower():
                    _sentence_times.append((_word_timings[_wi][1], _vt['type'], _vt['subject']))
                    _wt_idx = _wi + len(_sent_words)
                    _found = True
                    break
            if not _found:
                _sentence_times.append(
                    (_sentence_times[-1][0] if _sentence_times else 0.0, _vt['type'], _vt['subject'])
                )
    return _sentence_times


def _tag_at_time(_sentence_times, t):
    """Return (type, subject) for the sentence being narrated at time t."""
    best = ('generic', '')
    for _st, _ty, _su in _sentence_times:
        if _st <= t:
            best = (_ty, _su)
        else:
            break
    return best


def _segment_ctx(
    _doc_cards,
    _img_to_clip,
    _log,
    _person_infobox_clip,
    _person_time_triggers,
    _shown_persons,
    _sp_crime,
    _word_timings,
    named_persons,
    pipeline_state,
    stock_clips,
    stock_images,
):
    """Build the shuffled asset pools and the tag timeline the 6d loop runs on."""
    import random as _rnd_seg

    _clip_info = _probe_clip_durations(stock_clips, _sp_crime)
    _rnd_seg.shuffle(_clip_info)

    _doc_pool = list(_doc_cards)
    _img_pool = list(stock_images)
    _rnd_seg.shuffle(_img_pool)

    return _SegmentCtx(
        img_to_clip=_img_to_clip,
        person_infobox_clip=_person_infobox_clip,
        log=_log,
        pools=_AssetPools(doc_pool=_doc_pool, img_pool=_img_pool),
        named_persons=named_persons,
        location_images=pipeline_state.get('location_images', {}),
        person_time_triggers=_person_time_triggers,
        shown_persons=_shown_persons,
        sentence_times=_sentence_start_times(_word_timings, pipeline_state.get('visual_tags', [])),
    )


def _select_tagged_visual(ctx, _tag_type, _tag_sub, _seg_idx):
    """Pick the clip a tagged moment asks for; returns (clip_path_or_None, duration)."""
    _seg_out = None
    _seg_dur_added = 0.0

    if _tag_type == 'person' and _tag_sub:
        # Show person photo if available (but not if info-box was just shown)
        _person_key = next(
            (k for k in ctx.named_persons if k.lower() in _tag_sub.lower() or _tag_sub.lower() in k.lower()),
            None,
        )
        if _person_key and _person_key not in ctx.shown_persons_set:
            _pdata = ctx.named_persons.get(_person_key, {})
            if _pdata.get('photo') and os.path.exists(_pdata['photo']):
                _seg_out = ctx.img_to_clip(_pdata['photo'], 8.0, _seg_idx, shot_type='close-up')
                _seg_dur_added = 8.0
        # Fallback: use a doc card so there's some content
        if not _seg_out and ctx.pools.doc_pool:
            _seg_out = ctx.img_to_clip(ctx.pools.next_doc(), 8.0, _seg_idx)
            _seg_dur_added = 8.0

    elif _tag_type == 'location' and _tag_sub:
        _loc_key = next(
            (k for k in ctx.location_images if k.lower() in _tag_sub.lower() or _tag_sub.lower() in k.lower()),
            None,
        )
        if _loc_key:
            _seg_out = ctx.img_to_clip(ctx.location_images[_loc_key], 7.0, _seg_idx, shot_type='wide establishing shot')
            _seg_dur_added = 7.0
        elif ctx.pools.img_pool:
            _seg_out = ctx.img_to_clip(ctx.pools.next_img(), 7.0, _seg_idx)
            _seg_dur_added = 7.0

    elif _tag_type == 'court':
        # Always show a doc card for court-tagged sentences
        _dc = ctx.pools.next_doc() if ctx.pools.doc_pool else None
        if _dc:
            _seg_out = ctx.img_to_clip(_dc, 9.0, _seg_idx)
            _seg_dur_added = 9.0
        elif ctx.pools.img_pool:
            _seg_out = ctx.img_to_clip(ctx.pools.next_img(), 9.0, _seg_idx)
            _seg_dur_added = 9.0

    elif _tag_type in ('crime_scene', 'event'):
        # Videos disabled — alternate: 1 doc card every 3 events, rest are images
        if _seg_idx % 3 == 0 and ctx.pools.doc_pool:
            _seg_out = ctx.img_to_clip(ctx.pools.next_doc(), 8.0, _seg_idx, emotion='tension')
            _seg_dur_added = 8.0
        elif ctx.pools.img_pool:
            _seg_out = ctx.img_to_clip(ctx.pools.next_img(), 8.0, _seg_idx, emotion='tension')
            _seg_dur_added = 8.0
        elif ctx.pools.doc_pool:
            _seg_out = ctx.img_to_clip(ctx.pools.next_doc(), 8.0, _seg_idx, emotion='tension')
            _seg_dur_added = 8.0

    return _seg_out, _seg_dur_added


def _select_fallback_visual(ctx, _fallback_phase, _seg_idx):
    """Doc card → image → doc card cycle for generic/untagged moments.

    `_fallback_phase` is the running count of fallbacks taken so far; returns
    (clip_path_or_None, duration).
    """
    _seg_out = None
    _seg_dur_added = 0.0
    _fp = _fallback_phase % 3
    if _fp == 0 and ctx.pools.doc_pool:
        _seg_out = ctx.img_to_clip(ctx.pools.next_doc(), 8.0, _seg_idx)
        _seg_dur_added = 8.0
    elif ctx.pools.img_pool:
        _seg_out = ctx.img_to_clip(ctx.pools.next_img(), 7.0, _seg_idx)
        _seg_dur_added = 7.0
    elif ctx.pools.doc_pool:
        _seg_out = ctx.img_to_clip(ctx.pools.next_doc(), 8.0, _seg_idx)
        _seg_dur_added = 8.0
    return _seg_out, _seg_dur_added


def _build_segment_timeline(ctx, _seg_files, tts_duration):
    """Fill `_seg_files` with clips until the narration is covered; returns their total duration.

    Appends in place so a failure part-way keeps the segments already rendered, exactly
    as the single `try` of the original stage did. Caps at 500 iterations.
    """
    _seg_total_dur = 0.0
    _seg_idx = 0
    _fallback_phase = 0  # used when tag says generic
    while _seg_total_dur < tts_duration and _seg_idx < 500:
        # ── Person info-box injection ──────────────────────────────────
        _next_trigger = None
        for _trig_t, _trig_name in sorted(ctx.person_time_triggers.items()):
            if _trig_t <= _seg_total_dur + 3 and _trig_name not in ctx.shown_persons:
                _next_trigger = (_trig_t, _trig_name)
                break
        if _next_trigger:
            _trig_t, _trig_name = _next_trigger
            _pb_out = ctx.person_infobox_clip(_trig_name, ctx.named_persons[_trig_name], _seg_idx, duration=10.0)
            if _pb_out:
                _seg_files.append(_pb_out)
                _seg_total_dur += 10.0
                ctx.shown_persons.add(_trig_name)
                ctx.shown_persons_set.add(_trig_name)
                _seg_idx += 1
                continue

        # ── Tag-driven visual selection ────────────────────────────────
        _tag_type, _tag_sub = _tag_at_time(ctx.sentence_times, _seg_total_dur)
        _seg_out, _seg_dur_added = _select_tagged_visual(ctx, _tag_type, _tag_sub, _seg_idx)

        # ── Fallback for generic/untagged: doc card → image → doc card cycle ──
        if not _seg_out:
            _seg_out, _seg_dur_added = _select_fallback_visual(ctx, _fallback_phase, _seg_idx)
            _fallback_phase += 1

        if _seg_out and _seg_dur_added > 0:
            _seg_files.append(_seg_out)
            _seg_total_dur += _seg_dur_added

        _seg_idx += 1

    return _seg_total_dur


def _append_outro_card(_img_to_clip, _log, _seg_files, out_dir):
    """Render the 5 s 'Crime Chronicles' outro card, append its clip, return the duration added."""
    try:
        from PIL import Image as _PI_o, ImageDraw as _PD_o, ImageFont as _PF_o

        _outro_card = _PI_o.new('RGB', (1920, 1080), (5, 5, 12))
        _draw_o = _PD_o.Draw(_outro_card)
        try:
            _fn_o1 = _PF_o.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 72)
            _fn_o2 = _PF_o.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 40)
            _fn_o3 = _PF_o.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 30)
        except Exception:
            _fn_o1 = _fn_o2 = _fn_o3 = _PF_o.load_default()
        # Title
        _draw_o.text((960, 340), 'CRIME CHRONICLES', fill=(200, 40, 40), font=_fn_o1, anchor='mm')
        # Divider
        _draw_o.line([(480, 430), (1440, 430)], fill=(150, 30, 30), width=3)
        # Subscribe text
        _draw_o.text((960, 490), 'Thank you for watching.', fill=(220, 210, 195), font=_fn_o2, anchor='mm')
        _draw_o.text(
            (960, 550),
            'Subscribe to Crime Chronicles for more documented cases.',
            fill=(180, 170, 155),
            font=_fn_o3,
            anchor='mm',
        )
        _draw_o.text((960, 600), 'Like · Comment · Share', fill=(140, 130, 110), font=_fn_o3, anchor='mm')
        _outro_img_path = os.path.join(out_dir, '_outro_card.jpg')
        _outro_card.save(_outro_img_path, 'JPEG', quality=95)
        _outro_clip = _img_to_clip(_outro_img_path, 5.0, 9999)
        if _outro_clip:
            _seg_files.append(_outro_clip)
            _log('INFO', 'Stage 6', 'Outro card added')
            return 5.0
    except Exception as _oe:
        _log('WARNING', 'Stage 6', f'Outro card failed: {_oe}')
    return 0.0


def _remove_quietly(_paths, _what):
    """Delete each existing path, logging at debug level what could not be removed."""
    for _p in _paths:
        try:
            if os.path.exists(_p):
                os.remove(_p)
        except OSError as _exc:
            _zyg_log.debug('%s %s removal skipped: %s', _what, _p, _exc)


def _ffmpeg_concat(_concat_list, _log, _raw_video, _sp_crime, pipeline_id, tts_duration):
    """Concat the segment list into `_raw_video` with NVENC, falling back to libx264.

    Returns True when the raw video exists and is larger than 10 kB.
    """
    _p_cat = _sp_crime.Popen(
        [
            exe('ffmpeg'),
            '-y',
            '-f',
            'concat',
            '-safe',
            '0',
            '-i',
            _concat_list,
            '-t',
            str(tts_duration + 2),
            '-c:v',
            'h264_nvenc',
            '-preset',
            'p4',
            '-rc',
            'vbr',
            '-cq',
            '20',
            '-an',
            '-sn',
            _raw_video,
        ],
        stdout=_sp_crime.PIPE,
        stderr=_sp_crime.PIPE,
    )
    _register_subproc(_p_cat.pid, 'crime-concat', pipeline_id)
    _, _stderr_cat = _p_cat.communicate(timeout=int(tts_duration * 3 + 120))
    _finish_subproc(_p_cat.pid, ok=(_p_cat.returncode == 0))

    if not (os.path.exists(_raw_video) and os.path.getsize(_raw_video) > 10000):
        if _p_cat.returncode != 0:
            _log(
                'WARNING',
                'Stage 6',
                f'GPU concat failed, trying CPU: {_stderr_cat.decode(errors="replace")[-200:]}',
            )
        _p_cat2 = _sp_crime.Popen(
            [
                exe('ffmpeg'),
                '-y',
                '-f',
                'concat',
                '-safe',
                '0',
                '-i',
                _concat_list,
                '-t',
                str(tts_duration + 2),
                '-c:v',
                'libx264',
                '-preset',
                'veryfast',
                '-crf',
                '20',
                '-pix_fmt',
                'yuv420p',
                '-an',
                '-sn',
                _raw_video,
            ],
            stdout=_sp_crime.PIPE,
            stderr=_sp_crime.PIPE,
        )
        _register_subproc(_p_cat2.pid, 'crime-concat-cpu', pipeline_id)
        _, _stderr_cat2 = _p_cat2.communicate(timeout=int(tts_duration * 4 + 120))
        _finish_subproc(_p_cat2.pid, ok=(_p_cat2.returncode == 0))
        if _p_cat2.returncode != 0:
            _log('WARNING', 'Stage 6', f'CPU concat failed: {_stderr_cat2.decode(errors="replace")[-300:]}')

    return os.path.exists(_raw_video) and os.path.getsize(_raw_video) > 10000


def _mux_narration(_pre_sub, _raw_video, _sp_crime, pipeline_id, tts_duration, tts_path):
    """Mux the narration onto the raw video (video copied, audio AAC 192k) into `_pre_sub`.

    Returns True when `_pre_sub` exists and is larger than 10 kB.
    """
    _p_merge = _sp_crime.Popen(
        [
            exe('ffmpeg'),
            '-y',
            '-i',
            _raw_video,
            '-i',
            tts_path,
            '-t',
            str(tts_duration),
            '-map',
            '0:v:0',
            '-map',
            '1:a:0',
            '-c:v',
            'copy',
            '-c:a',
            'aac',
            '-b:a',
            '192k',
            _pre_sub,
        ],
        stdout=_sp_crime.PIPE,
        stderr=_sp_crime.PIPE,
    )
    _register_subproc(_p_merge.pid, 'crime-merge', pipeline_id)
    _p_merge.communicate(timeout=int(tts_duration * 2 + 60))
    _finish_subproc(_p_merge.pid, ok=(_p_merge.returncode == 0))
    return os.path.exists(_pre_sub) and os.path.getsize(_pre_sub) > 10000


def _concat_and_merge(
    _asset_counts,
    _log,
    _seg_files,
    _sp_crime,
    final_video_path,
    out_dir,
    pipeline_id,
    tts_duration,
    tts_path,
):
    """Concat the segments, mux the narration, publish `final_video_path` and clean up.

    `_asset_counts` is (doc cards, images, video clips) for the success log line.
    Returns True when the published file exists and is larger than 10 kB.
    """
    _assembled = False
    try:
        _concat_list = os.path.join(out_dir, '_crime_concat.txt')
        with open(_concat_list, 'w') as _clf:
            for _sf in _seg_files:
                _clf.write(f"file '{_sf}'\n")

        _raw_video = os.path.join(out_dir, '_crime_raw.mp4')

        if _ffmpeg_concat(_concat_list, _log, _raw_video, _sp_crime, pipeline_id, tts_duration):
            _pre_sub = os.path.join(out_dir, '_crime_nosub.mp4')
            if _mux_narration(_pre_sub, _raw_video, _sp_crime, pipeline_id, tts_duration, tts_path):
                # SRT already saved to out_dir — copy clean video, no burn
                import shutil as _shu_nosub

                _shu_nosub.copy2(_pre_sub, final_video_path)

                if os.path.exists(final_video_path) and os.path.getsize(final_video_path) > 10000:
                    _assembled = True
                    _n_docs, _n_images, _n_clips = _asset_counts
                    _log(
                        'INFO',
                        'Stage 6',
                        f'Video assembled: {os.path.getsize(final_video_path) // 1024 // 1024} MB '
                        f'({_n_docs} doc cards, {_n_images} images, {_n_clips} video clips)',
                    )

        _remove_quietly([_raw_video, _concat_list, os.path.join(out_dir, '_crime_nosub.mp4')], 'temp file')
        _remove_quietly(_seg_files, 'segment file')

    except Exception as _asse:
        _log('WARNING', 'Stage 6', f'Assembly failed: {_asse}')
    return _assembled


def _text_card_vf_parts(_case_name):
    """Build the drawtext filter chain of the fallback card for one case name.

    The name is escaped for ffmpeg's filter syntax (quote and colon) and shown for the
    first ten seconds only.
    """
    _esc_name_tc = _case_name.replace("'", "\\'").replace(':', '\\:')
    return [
        'eq=brightness=-0.05',
        "drawtext=text='CRIME CHRONICLES':fontcolor=0xCC2200:fontsize=36"
        ':x=(w-text_w)/2:y=50:box=1:boxcolor=black@0.5:boxborderw=8',
        f"drawtext=text='{_esc_name_tc}':fontcolor=0xFFFFFF:fontsize=52"
        f':x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.6:boxborderw=10'
        f":enable='lte(t,10)'",
    ]


def _render_text_card(_case_name, _log, _sp_crime, final_video_path, pipeline_id, tts_duration, tts_path):
    """Render the narration over a title card when no segment video could be assembled.

    Returns True when `final_video_path` exists and is larger than 10 kB.
    """
    _vf_parts = _text_card_vf_parts(_case_name)
    # SRT saved to out_dir — not burned into text-card fallback
    _p_tc = _sp_crime.Popen(
        [
            exe('ffmpeg'),
            '-y',
            '-f',
            'lavfi',
            '-i',
            f'color=c=0x0d0d1a:s=1920x1080:r=30:d={int(tts_duration) + 2}',
            '-i',
            tts_path,
            '-t',
            str(tts_duration),
            '-map',
            '0:v:0',
            '-map',
            '1:a:0',
            '-vf',
            ','.join(_vf_parts),
            '-c:v',
            'libx264',
            '-preset',
            'veryfast',
            '-crf',
            '23',
            '-c:a',
            'aac',
            '-b:a',
            '192k',
            '-pix_fmt',
            'yuv420p',
            final_video_path,
        ],
        stdout=_sp_crime.PIPE,
        stderr=_sp_crime.PIPE,
    )
    _register_subproc(_p_tc.pid, 'crime-textcard', pipeline_id)
    _, _stderr_tc = _p_tc.communicate(timeout=int(tts_duration * 3 + 120))
    _finish_subproc(_p_tc.pid, ok=(_p_tc.returncode == 0))
    if _p_tc.returncode != 0:
        _log('ERROR', 'Stage 6', f'Text-card failed: {_stderr_tc.decode(errors="replace")[-300:]}')
    elif os.path.exists(final_video_path) and os.path.getsize(final_video_path) > 10000:
        _log('INFO', 'Stage 6', f'Text-card assembled: {os.path.getsize(final_video_path) // 1024 // 1024} MB')
        return True
    return False


def _loudnorm_filter(_ln):
    """Second-pass loudnorm filter string from the first pass's measurement JSON."""
    return (
        f'loudnorm=linear=true:I=-14:TP=-1:LRA=11:'
        f'measured_I={_ln.get("input_i", "-14")}:'
        f'measured_TP={_ln.get("input_tp", "-1")}:'
        f'measured_LRA={_ln.get("input_lra", "11")}:'
        f'measured_thresh={_ln.get("input_thresh", "-24")}:'
        f'offset={_ln.get("target_offset", "0")}'
    )


def _apply_loudnorm(_log, _sp_crime, final_video_path, pipeline_id, tts_duration):
    """Normalise the finished video to EBU R128 -14 LUFS in place, or log and skip."""
    try:
        _norm_tmp = final_video_path + '_norm.mp4'
        _p_ln1 = _sp_crime.run(
            [
                exe('ffmpeg'),
                '-y',
                '-i',
                final_video_path,
                '-af',
                'loudnorm=I=-14:TP=-1:LRA=11:print_format=json',
                '-f',
                'null',
                '-',
            ],
            capture_output=True,
            text=True,
            timeout=int(tts_duration * 2 + 60),
        )
        import re as _re_ln

        _ln_m = _re_ln.search(r'\{[^{}]*"input_i"[^{}]*\}', _p_ln1.stderr, _re_ln.DOTALL)
        if _ln_m:
            _ln = json.loads(_ln_m.group())
            _p_ln2 = _sp_crime.Popen(
                [
                    exe('ffmpeg'),
                    '-y',
                    '-i',
                    final_video_path,
                    '-af',
                    _loudnorm_filter(_ln),
                    '-c:v',
                    'copy',
                    '-c:a',
                    'aac',
                    '-b:a',
                    '192k',
                    _norm_tmp,
                ],
                stdout=_sp_crime.PIPE,
                stderr=_sp_crime.PIPE,
            )
            _register_subproc(_p_ln2.pid, 'crime-loudnorm', pipeline_id)
            _p_ln2.communicate(timeout=int(tts_duration * 2 + 60))
            _finish_subproc(_p_ln2.pid, ok=(_p_ln2.returncode == 0))
            if os.path.exists(_norm_tmp) and os.path.getsize(_norm_tmp) > 10000:
                import shutil as _shu_ln

                _shu_ln.move(_norm_tmp, final_video_path)
                _log('INFO', 'Stage 6', 'Loudnorm applied (-14 LUFS)')
    except Exception as _lne:
        _log('WARNING', 'Stage 6', f'Loudnorm skipped: {_lne}')
