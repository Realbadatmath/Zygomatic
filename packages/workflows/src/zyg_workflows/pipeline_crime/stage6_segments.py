# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 6c: the segment renderers and the named-person info-box clip builder."""

from .constants import (
    _zyg_log,
    exe,
    os,
)


def _crime_stage_6c_segments(_log, _sp_crime, _word_timings, narration_script, out_dir, pipeline_state, tts_duration):
    # ── 6c: Helpers to render segments ──────────────────────────────────
    def _img_to_clip(img_path, duration, clip_idx, shot_type='', emotion='calm', focal_zone='center'):
        """Convert a still image to a Ken Burns animated 1920x1080/30fps video clip."""
        _out = os.path.join(out_dir, f'_seg_{clip_idx:04d}.mp4')
        _n = max(1, int(duration * 30))
        _s = str(shot_type).lower()
        # Motion style driven by shot_type; fall back to index-cycled variety
        if 'close' in _s or 'extreme' in _s or 'portrait' in _s:
            _style = 'push_in'
        elif 'wide' in _s or 'establish' in _s or 'aerial' in _s or 'drone' in _s:
            _style = 'pan_r' if clip_idx % 2 == 0 else 'pan_l'
        elif 'over' in _s or 'overhead' in _s:
            _style = 'drift'
        else:
            _style = ['push_in', 'pan_r', 'pan_l', 'pull_out'][clip_idx % 4]
        # Emotion-driven speed multiplier (same table as scholarly pipeline)
        _spd = {
            'grief': 0.55,
            'calm': 0.70,
            'mystery': 0.80,
            'unease': 0.85,
            'awe': 1.0,
            'triumph': 1.1,
            'tension': 1.4,
            'shock': 1.5,
        }.get(str(emotion).lower(), 1.0)
        _delta = 0.0003 * _spd
        # Focal zone anchor (0–1 fractions of w/h)
        _fz = str(focal_zone).lower()
        _ax = 0.25 if 'left' in _fz else (0.75 if 'right' in _fz else 0.5)
        _ay = 0.2 if 'top' in _fz else 0.5
        if _style == 'push_in':
            _z = f'min(1.0+(on+1)*{_delta:.6f},1.3)'
            _x = f'iw*{_ax:.3f}-iw/zoom/2'
            _y = f'ih*{_ay:.3f}-ih/zoom/2'
        elif _style == 'pull_out':
            _z = f'max(1.3-on*{_delta:.6f},1.0)'
            _x = f'iw*{_ax:.3f}-iw/zoom/2'
            _y = f'ih*{_ay:.3f}-ih/zoom/2'
        elif _style == 'pan_r':
            _xr = _delta * 0.4
            _z = '1.08'
            _x = f'min(iw*{_xr:.6f}*on,iw*(1-1/zoom))'
            _y = 'ih/2-ih/zoom/2'
        elif _style == 'pan_l':
            _xr = _delta * 0.4
            _z = '1.08'
            _x = f'max(iw*(1-1/zoom)-iw*{_xr:.6f}*on,0)'
            _y = 'ih/2-ih/zoom/2'
        else:  # drift (overhead/drone)
            _z = '1.06'
            _x = 'iw/2-iw/zoom/2'
            _y = f'max(ih*(1-1/zoom)-ih*{_delta:.6f}*on,0)'
        _vf = (
            f'scale=2560:1440:force_original_aspect_ratio=increase,crop=2560:1440,'
            f'setsar=1,'
            f"zoompan=z='{_z}':x='{_x}':y='{_y}':d={_n}:s=1920x1080:fps=30,"
            f'scale=1920:1080,format=yuv420p,setpts=PTS-STARTPTS'
        )
        _r = _sp_crime.run(
            [
                exe('ffmpeg'),
                '-y',
                '-loop',
                '1',
                '-t',
                str(duration + 0.5),
                '-i',
                img_path,
                '-vf',
                _vf,
                '-t',
                str(duration),
                '-c:v',
                'libx264',
                '-preset',
                'veryfast',
                '-crf',
                '20',
                '-pix_fmt',
                'yuv420p',
                '-an',
                _out,
            ],
            capture_output=True,
            timeout=120,
        )
        return _out if (_r.returncode == 0 and os.path.exists(_out) and os.path.getsize(_out) > 1000) else None

    def _video_to_clip(vid_path, start_sec, duration, clip_idx):
        """Extract a segment from a stock video, crop bottom 12% to remove burned-in subs, normalise to 1080p."""
        _out = os.path.join(out_dir, f'_seg_{clip_idx:04d}.mp4')
        # crop=iw:ih*0.88:0:0 removes bottom 12% where burned-in subtitles live,
        # then scale back up to fill 1920x1080
        _r = _sp_crime.run(
            [
                exe('ffmpeg'),
                '-y',
                '-ss',
                str(start_sec),
                '-i',
                vid_path,
                '-t',
                str(duration),
                '-vf',
                'crop=iw:trunc(ih*0.88/2)*2:0:0,'
                'scale=1920:1080:force_original_aspect_ratio=decrease,'
                'pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,fps=30',
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
                _out,
            ],
            capture_output=True,
            timeout=90,
        )
        return _out if (_r.returncode == 0 and os.path.exists(_out) and os.path.getsize(_out) > 10000) else None

    # ── 6c-extra: Named-person info-box clip builder ────────────────────
    named_persons = pipeline_state.get('named_persons', {})

    def _person_infobox_clip(person_name, bio, clip_idx, duration=10.0):
        """Render a person photo + lower-third info box as a video clip."""
        _out = os.path.join(out_dir, f'_seg_{clip_idx:04d}.mp4')
        try:
            from PIL import Image as _PI, ImageDraw as _PD, ImageFont as _PF

            _W, _H = 1920, 1080
            _canvas = _PI.new('RGB', (_W, _H), (10, 10, 18))
            _draw = _PD.Draw(_canvas)

            # Left side: photo (if available)
            _photo_path = bio.get('photo', '')
            if _photo_path and os.path.exists(_photo_path):
                try:
                    _ph = _PI.open(_photo_path).convert('RGB')
                    _ph_w, _ph_h = _ph.size
                    _target_h = 800
                    _target_w = int(_ph_w * _target_h / _ph_h)
                    _ph = _ph.resize((_target_w, _target_h), _PI.LANCZOS)
                    # Paste centred in left half
                    _px = max(0, ((_W // 2) - _target_w) // 2)
                    _py = (_H - _target_h) // 2
                    _canvas.paste(_ph, (_px, _py))
                except Exception as _exc:
                    _zyg_log.warning('case photo %s could not be composited onto the card: %s', _photo_path, _exc)

            # Right side: info box — build rows first so we can size the box exactly
            try:
                _fn_big = _PF.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 52)
                _fn_med = _PF.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 32)
                _fn_sm = _PF.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 26)
            except Exception:
                _fn_big = _fn_med = _fn_sm = _PF.load_default()

            _rx = _W // 2 + 40
            _ry_top = 120  # top of box

            # Build row list first so we know the height before drawing
            _rows = []
            if bio.get('dob'):
                _rows.append(('Date of Birth', bio['dob']))
            if bio.get('death'):
                _rows.append(('Date of Death', bio['death']))
            if bio.get('birthplace'):
                _rows.append(('Born In', bio['birthplace']))
            if bio.get('gender'):
                _rows.append(('Gender', bio['gender']))
            if bio.get('occupation'):
                _rows.append(('Occupation', bio['occupation']))

            # Calculate exact box height: name(75) + divider(20) + rows(42 each) + padding(24)
            _box_h = 75 + 20 + len(_rows) * 42 + 24
            _box_bottom = _ry_top - 20 + _box_h

            # Draw box sized to content
            _draw.rectangle(
                [_rx - 20, _ry_top - 20, _W - 40, _box_bottom], fill=(20, 20, 35), outline=(180, 60, 60), width=3
            )

            # Name
            _ry = _ry_top
            _draw.text((_rx, _ry), person_name, fill=(255, 80, 80), font=_fn_big)
            _ry += 75
            _draw.line([(_rx, _ry), (_W - 60, _ry)], fill=(180, 60, 60), width=2)
            _ry += 20

            for _label, _val in _rows:
                _draw.text((_rx, _ry), f'{_label}:', fill=(180, 160, 120), font=_fn_sm)
                _draw.text((_rx + 260, _ry), str(_val), fill=(230, 220, 200), font=_fn_sm)
                _ry += 42

            _card_p = os.path.join(out_dir, f'_np_card_{clip_idx:04d}.jpg')
            _canvas.save(_card_p, 'JPEG', quality=92)
            if os.path.exists(_card_p) and os.path.getsize(_card_p) > 1000:
                return _img_to_clip(_card_p, duration, clip_idx, shot_type='close-up')
        except Exception as _pbe:
            _log('WARNING', 'Stage 6', f'Person box for {person_name} failed: {_pbe}')
        return None

    # Build a map: which sentence indices mention each known person
    _person_sentence_map = {}  # sentence_index → person_name
    if named_persons:
        import re as _re_np2

        _narr_sentences = _re_np2.split(r'(?<=[.!?])\s+', narration_script)
        for _sni, _snt in enumerate(_narr_sentences):
            for _pname in named_persons:
                if _pname in _snt and _pname not in _person_sentence_map.values():
                    _person_sentence_map[_sni] = _pname
                    break  # one person per sentence slot

    # Convert sentence index → approximate time offset for injection
    # Works whether or not word_timings is available:
    # - If word_timings exist (Azure SDK): use exact per-word timestamps
    # - Fallback: estimate position by word-count ratio through the script
    _person_time_triggers = {}  # time_sec → person_name (injected once per person)
    _shown_persons = set()
    if named_persons:
        _narr_words = narration_script.split()
        _total_narr_words = max(len(_narr_words), 1)
        for _pname in named_persons:
            _pwords = _pname.split()
            for _wi_idx in range(len(_narr_words) - len(_pwords) + 1):
                if _narr_words[_wi_idx : _wi_idx + len(_pwords)] == _pwords:
                    if _word_timings and _wi_idx < len(_word_timings):
                        # Exact timestamp from Azure Speech SDK WordBoundary
                        _trigger_t = _word_timings[_wi_idx][1]
                    else:
                        # Estimate: word position as fraction of total duration
                        _trigger_t = tts_duration * (_wi_idx / _total_narr_words)
                    _person_time_triggers[_trigger_t] = _pname
                    break

    return (_img_to_clip, _person_infobox_clip, _person_time_triggers, _shown_persons, named_persons)
