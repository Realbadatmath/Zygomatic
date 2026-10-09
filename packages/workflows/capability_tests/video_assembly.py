# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Assembly, encode & delivery (video_assembly). 2026-09-30.

Question the sheet asks: does the cut come out right, and how much of the box does encoding take?

Nothing on this step generates a picture. Every row takes material that already exists and is
judged on whether it comes out the other side unchanged except where the edit said so — which
means almost every column here is mechanically decidable by ffprobe, SSIM or arithmetic, and
the operator is needed only where "does this transition read as a transition" is genuinely a
human question. That is the opposite of the render steps, and the budget shows it.

One fixture carries most of the test: a 30 s synthetic clip with a CLAP at exactly 5.000 s —
a 20 ms audio burst and a one-frame white flash on the same frame — so the A/V offset truth is
zero by construction and needs no marked waveform. A 60-minute version with a second clap at
3595 s answers the drift question the only way it can be answered, which is by sitting through
an hour.

Four measured receipts from the code are built into the thresholds rather than rediscovered:

  * `video_assembly.py:187-188` encodes with **libx264 -crf 26 -preset ultrafast** (draft) and
    **-crf 16 -preset medium** (final). There is no `-b:v` anywhere on the path, so "bitrate
    hits the target" has no target on that row and is `na` with the lines, not a guess.
  * `briefing_video.py:107-126` runs a live `-c:v h264_nvenc -f null -` probe (timeout 30 s)
    before trusting NVENC, because a driver userspace/kernel mismatch (580.173 vs a loaded
    580.159 module) left h264_nvenc LISTED by ffmpeg while failing on use. So the `nvenc`
    column is two measurements: is the hardware tag really in the output, and does the guard
    fall back to libx264 cleanly when it is not.
  * `zpub_cinema.py:1636` records that **h264_nvenc refuses 10-bit input** ("10 bit encode not
    supported"). `colour_space` therefore runs on a 10-bit BT.2020 fixture as well as an 8-bit
    one, and the expected result is that the NVENC row fails the 10-bit case and the libx264
    rows pass it. A step that silently drops to 8 bit is the failure worth catching.
  * `zpub_cinema.py:1787` records that **h264_nvenc on this build ignores -force_key_frames**.
    HLS segmentation depends on keyframes landing where they were asked for, so the `hls` probe
    measures the segment durations against the declared target rather than trusting the
    playlist, and this is the reason why.

What is BLOCKED and why: nothing. Every answer key here is either arithmetic (the clap is at
5.000 s because the command put it there), a string burned into a fixture by drawtext, or an
ffprobe field. No operator marks a waveform for this step.
"""

from __future__ import annotations

FX = 'capability_tests/fixtures/video_assembly'

# Check kinds this module needs and capability_tests/__init__.CHECK_KINDS does not have.
CHECK_KINDS = {
    'cut_durations_match': "for every shot in the cut list `cutlist`, the shot's duration in the finished file (measured from the join timestamps in the run receipt, cross-checked against a scene-change decode) is within `tol_frames` frames of the duration the cut list asked for, and the shot ORDER matches; a missing or reordered shot is a `no`, never a `partial`",
    'av_offset_max': 'the absolute difference between the time of the audio transient (first sample whose short-time energy exceeds `energy_z` sigma over the preceding second) and the time of the video flash (first frame whose mean luma exceeds `luma_z` sigma over the preceding second) is <= `max_ms`',
    'av_offset_drift_max': 'av_offset measured in the last `window_s` seconds of the file minus av_offset measured in the first `window_s` is <= `max_ms` in absolute value; both are signed, and the signed pair is written into the cell so a drift direction is recoverable',
    'av_offset_drift_max_note': 'not a check: reserved so the runner author sees that drift is the DIFFERENCE of two av_offset measurements and must not be implemented as a fresh correlation over an hour of audio',
    'ssim_min': 'mean SSIM (luma plane, 8x8 windows) between each frame of the finished file and the corresponding frame of the source it came from is >= `min`, and no single frame is below `floor`',
    'bitrate_within': 'ffprobe `format.bit_rate` is within `tol` (relative) of `target_kbps`; the column is `na` on a row whose encoder is constant-quality, because there is no target to hit',
    'ffprobe_tag_equals': 'the ffprobe field `field` of the stream selected by `stream` equals `value` exactly (string compare on the raw ffprobe JSON, no normalisation)',
    'ffprobe_stream_present': 'ffprobe reports at least one stream with `codec_type` == `codec_type` and, when given, `tags.language` == `lang` and `codec_name` == `codec_name`; the count found is written into the cell',
    'ffprobe_chapters': 'ffprobe -show_chapters returns exactly `n` chapters whose titles equal `titles` in order and whose start times are within `tol_ms` of `starts`',
    'hls_playlist_valid': 'the .m3u8 parses as an HLS media playlist (EXTM3U, EXT-X-TARGETDURATION, EXT-X-ENDLIST present), lists `n` segments, every segment file exists and decodes with no error on stderr, the sum of segment durations is within `tol_s` of the source duration, and no segment exceeds EXT-X-TARGETDURATION',
    'xfade_ramp': "across each declared xfade window, the frame-to-frame SSIM against the outgoing shot's last frame falls monotonically and against the incoming shot's first frame rises monotonically (allowing `wobble` reversals), AND PySceneDetect ContentDetector finds NO hard cut inside the window — a failed dissolve reads as a cut and that is the signal",
    'encode_ratio': 'wall-clock seconds spent per second of finished output, measured at each concurrency in `levels` with that many encodes running together; the column is the level beyond which total throughput (finished seconds per wall second, summed over the jobs) stops rising by more than `gain_min`',
}

CLAP_S = 5.000
CLIP_S = 30
LONG_S = 3600
LONG_CLAP2_S = 3595
FPS = 24
SIZE = '1920x1080'

FIX_CLIP = FX + '/clip30.mp4'
FIX_CLIP10 = FX + '/clip30_10bit.mp4'
FIX_LONG = FX + '/long60.mp4'
FIX_TITLE = FX + '/title.png'
FIX_SUBS = FX + '/subs.srt'
FIX_CHAPS = FX + '/chapters.ffmeta'
FIX_CUTLIST = FX + '/cutlist.json'

# The clap: a 20 ms 1 kHz burst mixed into a 440 Hz bed at exactly 5.000 s, and a one-frame
# white flash on the frame that starts at 5.000 s (frame 120 at 24 fps). Truth = offset 0.
GEN_CLIP = (
    'ffmpeg -y -f lavfi -i "testsrc2=s=%s:r=%d:d=%d" '
    '-f lavfi -i "sine=frequency=440:duration=%d:sample_rate=48000" '
    '-f lavfi -i "sine=frequency=1000:duration=0.02:sample_rate=48000" '
    '-filter_complex "[0:v]drawbox=x=0:y=0:w=iw:h=ih:c=white:t=fill:'
    "enable='between(n,120,120)'[v];"
    '[2:a]adelay=5000|5000,volume=4[clap];[1:a][clap]amix=inputs=2:duration=first:normalize=0[a]" '
    '-map "[v]" -map "[a]" -c:v libx264 -crf 12 -pix_fmt yuv420p -c:a pcm_s16le %s'
    % (SIZE, FPS, CLIP_S, CLIP_S, FIX_CLIP)
)

GEN_CLIP10 = (
    'ffmpeg -y -i %s -c:v libx264 -profile:v high10 -pix_fmt yuv420p10le '
    '-color_primaries bt2020 -color_trc smpte2084 -colorspace bt2020nc -color_range tv '
    '-crf 12 -c:a copy %s' % (FIX_CLIP, FIX_CLIP10)
)

GEN_LONG = (
    'ffmpeg -y -f lavfi -i "testsrc2=s=%s:r=%d:d=%d" '
    '-f lavfi -i "sine=frequency=440:duration=%d:sample_rate=48000" '
    '-f lavfi -i "sine=frequency=1000:duration=0.02:sample_rate=48000" '
    '-f lavfi -i "sine=frequency=1000:duration=0.02:sample_rate=48000" '
    '-filter_complex "[0:v]drawbox=x=0:y=0:w=iw:h=ih:c=white:t=fill:'
    "enable='between(n,120,120)+between(n,86280,86280)'[v];"
    '[2:a]adelay=5000|5000,volume=4[c1];[3:a]adelay=3595000|3595000,volume=4[c2];'
    '[1:a][c1][c2]amix=inputs=3:duration=first:normalize=0[a]" '
    '-map "[v]" -map "[a]" -c:v libx264 -crf 26 -preset ultrafast -pix_fmt yuv420p '
    '-c:a pcm_s16le %s   # ~6 GB, ~12 min to make; the second flash is frame 86280 = 3595 s x 24'
    % (SIZE, FPS, LONG_S, LONG_S, FIX_LONG)
)

GEN_TITLE = (
    'ffmpeg -y -f lavfi -i "color=c=0x0d1014:s=%s" -vf '
    "\"drawtext=text='THE SECOND LEDGER 1671':fontsize=84:fontcolor=white:"
    'x=(w-text_w)/2:y=(h-text_h)/2" -frames:v 1 %s' % (SIZE, FIX_TITLE)
)

TITLE_TEXT = 'THE SECOND LEDGER 1671'

# Three shots out of the one fixture, with trims chosen so every duration is a whole number of
# frames and the arithmetic is checkable by hand: 6 s + 8 s + 5 s, joined by 0.18 s xfades.
CUTLIST = {
    'fps': FPS,
    'size': [1920, 1080],
    'shots': [
        {'path': FIX_CLIP, 'trim': [0.0, 6.0], 'xfade_s': 0.18},
        {'path': FIX_CLIP, 'trim': [8.0, 16.0], 'xfade_s': 0.18},
        {'still': FIX_TITLE, 'hold_s': 5.0},
    ],
    'fade_in_s': 0.0,
    'fade_out_s': 0.0,
    'expect': {
        'shot_durations_s': [6.0, 8.0, 5.0],
        'joins_s': [6.0, 14.0],
        'total_s': 18.64,
        'note': '6 + 8 + 5 = 19 s of material less two 0.18 s xfade overlaps = 18.64 s; at 24 fps that is 447.36 frames, so the tolerance of 1 frame is doing real work',
    },
}

CHAPTERS = {'n': 3, 'titles': ['The quay', 'The ledger', 'The tide'], 'starts_ms': [0, 6000, 14000]}
SUB_CUES = ['The quay at first light.', 'Twenty-three barrels, and a name.', 'The tide does not wait.']

COND = {
    'repeats': 2,
    'note': 'two runs of the same cut list; an assembler that is not reproducible is a finding, and ffprobe fields are cheap to read twice',
}

ALL = ['nvenc', 'assembly', 'kenburns', 'overlay', 'hls']
ENCODERS = ['nvenc', 'assembly', 'hls']
CRF_ROWS = ['assembly', 'kenburns', 'overlay']


def _p(pid, title, feeds, checks, rows, fixture=FIX_CLIP, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'fixture': fixture, 'cutlist': FIX_CUTLIST, 'prompt': None},
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': rows,
    }
    p.update(kw)
    return p


PROBES = [
    # ── The cut ──
    _p(
        'correct',
        'The cut matches the edit',
        ['correct'],
        [
            {'check': 'cut_durations_match', 'cutlist': FIX_CUTLIST, 'tol_frames': 1},
            {'check': 'duration_s', 'min': 18.60, 'max': 18.68},
            {'check': 'frames_exact', 'frames': 447, 'fps': FPS},
        ],
        ['assembly', 'kenburns', 'overlay'],
        state_note='18.64 s is arithmetic from the cut list (6 + 8 + 5 less two 0.18 s overlaps); 447 frames is that rounded down. A single dropped or duplicated frame at a join fails this, which is the point.',
        state_rule={'yes': 1.0, 'partial': 0.5},
    ),
    _p(
        'sync',
        'Audio stays in sync',
        ['sync'],
        [{'check': 'av_offset_max', 'max_ms': 20, 'energy_z': 6.0, 'luma_z': 6.0}],
        ALL,
        state_note="20 ms is half a frame at 24 fps. The clap is at 5.000 s in both tracks by construction, so a non-zero offset is the row's own, and the SIGNED offset goes in the cell — early and late are different bugs.",
    ),
    _p(
        'drift_av',
        'No A/V drift over an hour',
        ['drift_av'],
        [{'check': 'av_offset_drift_max', 'max_ms': 20, 'window_s': 10}],
        ALL,
        fixture=FIX_LONG,
        state_note='the two claps are 3590 s apart; 20 ms over that is 5.6 ppm, which is tighter than any sample-rate mismatch would be and looser than a correct remux. A row that resamples 48000 to 47952 shows ~3.6 s here, not 20 ms.',
    ),
    _p(
        'transitions',
        'Transitions are correct',
        ['transitions'],
        [
            {'check': 'xfade_ramp', 'windows_s': [[6.0, 6.18], [14.0, 14.18]], 'wobble': 1},
            {
                'check': 'operator',
                'blind': True,
                'question': 'At this join, does one shot dissolve into the next, or does it cut abruptly / flash to black in between? yes = it dissolves cleanly',
            },
        ],
        ['assembly'],
        state_note='a failed xfade almost always reads as a hard cut or a black flash, and PySceneDetect finding a cut inside the declared window is exactly that signal; the operator question is kept because a technically-monotone dissolve can still be the wrong length',
    ),
    _p(
        'titles',
        'Titles and overlays land',
        ['titles'],
        [
            {'check': 'ocr_equals', 'text': TITLE_TEXT, 'sample': 'the frame at 16.0 s (mid-title)'},
            {'check': 'ocr_stable', 'sample': 'every 12th frame between 14.5 s and 18.5 s'},
        ],
        ['assembly', 'kenburns', 'overlay'],
        fixture=FIX_TITLE,
        state_note='the string is burned into the fixture by drawtext, so the OCR truth is exact; ocr_stable catches a title that is re-rendered per frame and jitters',
    ),
    _p(
        'subs_mux',
        'Subtitles mux correctly',
        ['subs_mux'],
        [
            {'check': 'ffprobe_stream_present', 'codec_type': 'subtitle', 'codec_name': 'mov_text', 'lang': 'eng'},
            {'check': 'present', 'terms': SUB_CUES},
        ],
        ['assembly', 'hls'],
        fixture=FIX_SUBS,
        state_note='the second check extracts the muxed track back out and compares the cue text, because a stream that is present and empty is the common failure',
    ),
    _p(
        'chapters',
        'Chapters and metadata',
        ['chapters'],
        [
            {
                'check': 'ffprobe_chapters',
                'n': CHAPTERS['n'],
                'titles': CHAPTERS['titles'],
                'starts': CHAPTERS['starts_ms'],
                'tol_ms': 40,
            }
        ],
        ['assembly', 'hls'],
        fixture=FIX_CHAPS,
        state_note='40 ms is one frame; chapter marks that land on the wrong side of a cut are the thing this catches',
    ),
    # ── Encode ──
    _p(
        'quality',
        'No encode artefacts',
        ['quality'],
        [{'check': 'ssim_min', 'min': 0.98, 'floor': 0.95}],
        ALL,
        state_note=(
            'SSIM against the SOURCE frames, not against a reference encode. 0.98 mean with no frame under 0.95 is what libx264 -crf 16 delivers on this fixture; '
            'testsrc2 is deliberately hostile to an encoder (hard edges, a moving gradient), so this is a floor rather than a flattering number.'
        ),
    ),
    _p(
        'bitrate',
        'Bitrate hits the target',
        ['bitrate'],
        [
            {'check': 'bitrate_within', 'target_kbps': 8000, 'tol': 0.10},
            {'check': 'ffprobe_tag_equals', 'stream': 'v:0', 'field': 'bit_rate', 'value': '<recorded, not asserted>'},
        ],
        ['nvenc', 'hls'],
        state_note='asked only of the rows that can be given a target. 8000 kbps at 1080p24 is the house delivery rate; the second check records what ffprobe actually reports so a row that hits the average by overshooting and starving is visible in the trial.',
    ),
    _p(
        'colour_space',
        'Colour space survives',
        ['colour_space'],
        [
            {'check': 'ffprobe_tag_equals', 'stream': 'v:0', 'field': 'color_primaries', 'value': 'bt2020'},
            {'check': 'ffprobe_tag_equals', 'stream': 'v:0', 'field': 'color_transfer', 'value': 'smpte2084'},
            {'check': 'ffprobe_tag_equals', 'stream': 'v:0', 'field': 'pix_fmt', 'value': 'yuv420p10le'},
        ],
        ALL,
        fixture=FIX_CLIP10,
        grid={'source': ['clip30.mp4 (8-bit, bt709)', 'clip30_10bit.mp4 (10-bit, bt2020 / PQ)']},
        state_note=(
            'The 10-bit case is where this column earns its keep. zpub_cinema.py:1636 records that h264_nvenc on this box refuses 10-bit input outright ("10 bit encode not supported"), '
            'so the expected result is: NVENC row `no` on the 10-bit source (it errors, or it silently drops to 8 bit — the pix_fmt check tells those apart), libx264 rows `yes`. '
            'An unset colour tag is a `no`: an untagged file is a file the next tool guesses about.'
        ),
    ),
    _p(
        'concurrency',
        'Parallel encodes that pay off',
        ['concurrency'],
        [{'check': 'encode_ratio', 'levels': [1, 2, 4, 8], 'gain_min': 0.15}],
        ENCODERS,
        state_note=(
            'The ladder stops at 8 because that is the NVENC session cap on this class of card ([[project_kenburns_nvenc_bench]]), so a 9th encode does not queue, it fails to open. '
            'The cell is the level at which summed throughput stops rising by 15 %, and the per-level seconds-per-finished-second table goes into the trial — that table is what an operator schedules against.'
        ),
    ),
    _p(
        'nvenc',
        'Hardware encode is used',
        ['nvenc'],
        [
            {'check': 'ffprobe_tag_equals', 'stream': 'v:0', 'field': 'codec_tag_string', 'value': 'avc1'},
            {'check': 'metric_within', 'metric': 'encoder_used', 'target': 'h264_nvenc', 'tol': 0, 'unit': 'string'},
            {
                'check': 'operator',
                'blind': False,
                'question': 'derived: with the NVENC guard forced to fail, the same call still produces a playable file encoded with libx264 (the fallback works)',
            },
        ],
        ALL,
        state_note=(
            'Two measurements, because the interesting failure is not "no hardware" but "hardware that lies". briefing_video.py:107-116 runs a real `-c:v h264_nvenc -f null -` trial with a 30 s timeout '
            'precisely because a userspace/kernel driver mismatch (580.173 against a loaded 580.159) left h264_nvenc LISTED by ffmpeg and failing on use; :126 then encodes with -preset p5 -rc vbr -cq 21 and '
            ":1310 logs which encoder won. So: (a) which encoder is actually in the file, read from the run's own log and cross-checked against ffprobe, and (b) does the guard degrade to libx264 without "
            'dropping the job. Expected results per row: nvenc `yes`; assembly, kenburns and overlay `no` — video_assembly.py:187-188 and video_overlay.py:524-526 hardcode libx264 and never probe for NVENC at all.'
        ),
    ),
    # ── Delivery ──
    _p(
        'hls',
        'HLS packaging',
        ['hls'],
        [
            {'check': 'hls_playlist_valid', 'n': 5, 'tol_s': 0.5},
            {'check': 'metric_within', 'metric': 'max_segment_duration_s', 'target': 6.0, 'tol': 1.0, 'unit': 's'},
        ],
        ['hls'],
        state_note=(
            '30 s at a 6 s target duration is 5 segments. The second check is there because of zpub_cinema.py:1787: h264_nvenc on this build IGNORES -force_key_frames, which is measured, and HLS segment '
            'boundaries can only land where a keyframe is. So a playlist that parses is not enough — the segment durations must actually be near the target, and a row that packages an NVENC encode is '
            'expected to show segments that drift off it. That is the receipt this column exists to carry.'
        ),
    ),
]

NA_CAP = {
    'cap_people': 'no row of this step generates a person; they arrive in the footage and the question belongs to the step that rendered them',
    'cap_named': 'no subject is named to an encoder and none is generated; identity is neither given nor asked here',
    'cap_faces': 'faces are not generated; whether a face survives the encode is the `quality` column, measured as SSIM against the source',
    'cap_hands': 'hands are not generated; hand quality through an encode is SSIM, which is the `quality` column',
    'cap_objects': 'an encoder keeps track of macroblocks, not objects, and counts none of them',
    'cap_words': 'no text is generated; whether burned-in lettering survives is the `titles` column, measured by OCR against a known string',
    'cap_digits': 'no digits are generated; the digits in the fixture title are part of the `titles` OCR truth',
    'cap_animals': 'nothing is generated, so there is no count at which generation degrades',
    'cap_prompt_terms': 'no row of this step takes a prompt — a cut list, a placement record and an ffmpeg command line',
    'cap_moving': 'the number of moving subjects does not bound an encode; it changes the bitrate needed, which is the `bitrate` and `quality` columns',
}
# `cap_shots` is deliberately NOT in NA_CAP: how many shots cut together IS this step's
# business, so it is left to the video bank's own probe rather than waved away here.

NA_CRF = {
    'bitrate': 'this row encodes at constant quality and never at a target rate — libx264 -crf 26 -preset ultrafast for a draft and -crf 16 -preset medium for a final (video_assembly.py:187-188; video_overlay.py:524-526 does the same with -crf 28 / -crf 14). There is no target bitrate on the path, so there is nothing for the output to hit or miss.'
}
NA_NO_TIMELINE = {
    c: 'this row encodes or packages a finished file; it holds no cut list and joins no shots, so the edit questions belong to the assembly row'
    for c in ['correct', 'transitions']
}
NA_KENBURNS = {
    c: 'the Ken Burns pass renders one still into a moving segment; it muxes no subtitle and writes no chapter (briefing_video._render_segment, :1075-1090)'
    for c in ['subs_mux', 'chapters']
}
NA_OVERLAY = {
    c: 'video_overlay.composite takes one base clip and a placement record; it muxes no subtitle, writes no chapter and packages nothing'
    for c in ['subs_mux', 'chapters', 'transitions']
}
NA_NOT_HLS = {
    'hls': 'HLS packaging is the delivery row (zpub_cinema); this row produces a single progressive file and is not asked to segment it'
}

TEST = {
    'step': 'video_assembly',
    'version': '2026-09-30.1',
    'title': 'One clap fixture, one cut list, and ffprobe — plus an hour for the drift question',
    'purpose': 'Prove the edit came out frame-exact and in sync against a synthetic truth, and record which rows actually use hardware encode, survive 10-bit and segment where they said they would.',
    'include_shared': 'video',
    'cutlist': CUTLIST,
    'rows': {
        'nvenc': {
            'transport': 'ffmpeg',
            'where': 'ffmpeg h264_nvenc — data/models.json /cpu/2105 {"name": "ffmpeg / NVENC assembly", "slug": "ffmpeg-nvenc", "vram_required_mb": 0, "in_use": true, "type": "encode"}; the availability guard and the encode parameters are briefing_video.py:107-126 (-preset p5 -rc vbr -cq 21) and the chosen encoder is logged at :1310',
            'na': dict(NA_CAP, **NA_NO_TIMELINE, **NA_KENBURNS, **NA_NOT_HLS),
        },
        'assembly': {
            'transport': 'service',
            'where': 'video_assembly.assemble(shotlist, out_mp4) — conform, trim, speed ramps, stills, xfade joins, top-and-tail fades and the final encode (libx264, :187-188); overlay and audio are delegated to video_overlay.composite and video_audio.build_track/mux',
            'na': dict(NA_CAP, **NA_CRF, **NA_NOT_HLS),
        },
        'kenburns': {
            'transport': 'service',
            'where': 'briefing_video._render_segment(img, wav, out, use_nvenc, ken_burns=True) (:1075, the move applied at :1090) — the documentary stills pass; the same module owns the NVENC guard, so this row CAN take hardware encode where the assembly row cannot',
            'na': dict(NA_CAP, **NA_CRF, **NA_KENBURNS, **NA_NOT_HLS),
        },
        'overlay': {
            'transport': 'service',
            'where': 'video_overlay.composite from a placement record (video_overlay.py:1-40); draft and final read the SAME record and differ only in resolution / fps / preset; encoder libx264 -crf 28 ultrafast (draft) or -crf 14 medium (:524-526)',
            'na': dict(NA_CAP, **NA_CRF, **NA_OVERLAY, **NA_NOT_HLS),
        },
        'hls': {
            'transport': 'service',
            'where': 'zpub_cinema.py — Zero Cinema HLS packaging [[project_zero_cinema_hls]]; the NVENC ladder is :1607 (-c:v h264_nvenc -preset p4 -rc vbr), the 10-bit refusal is recorded at :1636 and the ignored -force_key_frames at :1787',
            'na': dict(NA_CAP, **NA_NO_TIMELINE, **NA_KENBURNS),
        },
    },
    'na_bands': {
        'reason': 'no row of this step takes a text prompt: the inputs are a cut list, a placement record, an ffmpeg command line and a packaging profile. Every prompt question would measure something that is not on the path.',
        'bands': ['Prompt: damage', 'Prompt: clarity needed', 'Prompt: limits', 'Prompt: steering'],
    },
    'probes': PROBES,
    'derive': {
        'ratio': {
            'from': 'wall-clock minutes the row held, divided by minutes of finished output, at concurrency 1 — taken from the same runs that answer `concurrency`, so the two cannot disagree',
            'grade': 'measured',
            'unit': 'count',
        },
    },
    'lookup': {
        'platform_spec': {
            'source': 'YouTube recommended upload encoding settings',
            'source_url': 'https://support.google.com/youtube/answer/1722171',
            'revision': 'the page is fetched and its sha256 and fetch date recorded with the cell; a spec whose revision is not pinned is a rumour',
            'requires': (
                'the finished file is checked against the spec fields the page states, each read with ffprobe: container mp4, video h264 high profile, pix_fmt yuv420p, closed GOP, '
                'progressive scan, audio AAC-LC 48 kHz stereo at >= 384 kbps, and the recommended video bitrate for the measured resolution and frame rate (8000 kbps at 1080p24). '
                'Each field is written into the cell pass/fail separately, so "meets the spec" is never one opinion.'
            ),
            'grade': 'receipt',
        },
    },
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': FIX_CLIP,
            'generated': GEN_CLIP,
            'verified': True,
            'note': 'the clap is at 5.000 s in the audio (adelay 5000 ms) and the white flash is frame 120 = 5.000 s at 24 fps, so the A/V offset truth is 0 by construction and no waveform is marked by hand',
        },
        {
            'path': FIX_CLIP10,
            'generated': GEN_CLIP10,
            'verified': True,
            'note': '10-bit BT.2020 / PQ, made from the 8-bit fixture so the two colour cases share one picture',
        },
        {
            'path': FIX_LONG,
            'generated': GEN_LONG,
            'verified': True,
            'note': 'claps at 5 s and 3595 s; ~6 GB and ~12 min to make, which is why drift_av is last in run_order',
        },
        {'path': FIX_TITLE, 'generated': GEN_TITLE, 'verified': True, 'note': 'OCR truth: ' + TITLE_TEXT},
        {
            'path': FIX_CUTLIST,
            'generated': 'written by the runner from TEST["cutlist"] before the first probe, so the runner and this file cannot drift apart',
            'verified': True,
        },
        {
            'path': FIX_SUBS,
            'generated': "written by the runner from TEST['sub_cues']: three srt cues at 00:00:01,000-00:00:04,000 / 00:00:07,000-00:00:11,000 / 00:00:15,000-00:00:18,000 carrying the three strings verbatim",
            'verified': True,
        },
        {
            'path': FIX_CHAPS,
            'generated': "written by the runner from TEST['chapters'] as an ffmetadata file: three [CHAPTER] blocks with TIMEBASE=1/1000 and START 0 / 6000 / 14000 and the three titles verbatim",
            'verified': True,
        },
    ],
    'sub_cues': SUB_CUES,
    'chapters': CHAPTERS,
    'budget': {
        'calls': 44,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'every row is an ffmpeg command line or a house timeline service; no language model is called on this step and no tokens are spent',
        'minutes': 78,
        'gpu_minutes': 9,
        'operator_minutes': 3,
        'note': (
            '14 probes x 2 repeats, not all on every row, comes to ~44 encodes or packaging runs per row. The 30 s fixture encodes in ~8 s on libx264 -crf 16 medium at 1080p and ~3 s on NVENC, so the short-fixture '
            'probes total ~6 min. The two expensive items dominate. (1) drift_av needs the 60-minute fixture: making it once is ~12 min, and each row must encode an hour of 1080p — ~14 min on libx264 medium, '
            '~4 min on NVENC — x 2 repeats, so ~28 min on a CRF row and the GPU rows account for the 9 gpu_minutes. (2) concurrency runs the 30 s fixture at 1, 2, 4 and 8 in parallel, twice = 30 encodes, ~7 min. '
            'Measuring is cheap here and that is the character of this step: ffprobe is milliseconds, SSIM over 447 frames is ~20 s, OCR on ~30 sampled frames is ~15 s, and the hour-long SSIM is NOT taken '
            '(quality is measured on the 30 s fixture only). Call it ~78 min per row, of which ~9 are on the card for the NVENC-capable rows and 0 for the others. Operator: 2 blind questions '
            "(transitions, and the derived fallback note on nvenc) x 2 repeats = 4 decisions = ~2 min, plus shuffling = 3 min. Disk: the 60-minute fixture is ~6 GB and each row's hour-long output another "
            '~4-6 GB, so budget ~40 GB of scratch for a full pass across five rows — that is the number to check before scheduling, not the minutes. SHARED BANK for this step: the video bank covers 39 of the '
            '53 columns and renders no subject bank for video_assembly; its own budget note carries its cost. No claude_cli or anthropic_api row exists here, so the shared Claude week is untouched.'
        ),
    },
    'run_order': [
        'nvenc',
        'colour_space',
        'bitrate',
        'quality',
        'correct',
        'titles',
        'subs_mux',
        'chapters',
        'sync',
        'transitions',
        'hls',
        'concurrency',
        'drift_av',
    ],
    'notes': [
        'Almost nothing here needs a judge. The clap fixture makes sync arithmetic, drawtext makes the title OCR truth exact, the cut list makes the durations arithmetic, and ffprobe answers four columns outright. The only blind operator question that carries a column on its own is `transitions`.',
        'bitrate is `na` on the three CRF rows rather than a guessed target. If the house ever sets a delivery bitrate for the assembly path, that na becomes a probe and the version here bumps — the na names the exact lines so the change is easy to find.',
        'The expected pattern on `nvenc` is: the nvenc and hls rows yes, the assembly and overlay rows no, because video_assembly.py:187-188 and video_overlay.py:524-526 hardcode libx264 and never probe for hardware. That is a real finding about the box, not a gap in the test — the fastest encoder on the machine is not wired into the main assembly path.',
        'colour_space and hls both carry a measured NVENC limitation from zpub_cinema.py (10-bit refused at :1636, -force_key_frames ignored at :1787). The thresholds are set so those limitations show as a `no` on the affected row instead of averaging into a `partial`.',
        'drift_av is last in run_order and costs more than the rest of the step put together. A partial run that stops before it still fills twelve of the fourteen domain columns.',
    ],
}
