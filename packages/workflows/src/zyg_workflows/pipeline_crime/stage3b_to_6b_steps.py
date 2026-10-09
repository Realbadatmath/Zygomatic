# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 3b-6b helpers: the visual tagger, the TTS leg, the SRT writer and the doc cards.

Extracted verbatim from `_crime_stages_3b_to_6b`, which keeps the stage banners, the job
label updates and the pipeline_state writes and calls the steps below in the same order
with the same side effects. The two nested defs of the original — `_parse_tag_json` and
`_fmt_srt` — are now the module-level :func:`parse_tag_json` and :func:`fmt_srt`, which
is the first time either can be exercised on its own.
"""

import re
from dataclasses import dataclass

from .constants import (
    OLLAMA_AVAILABLE,
    Ollama,
    _CHANNEL_VOICES_PATH,
    _LARGE_MODEL_THRESHOLD_GB,
    _MODEL_VRAM_GB,
    _VOICE_LIBRARY_PATH,
    _align_narration_word_timings,
    _caveman_kw,
    _dsl,
    _large_llm_semaphore,
    _log_prompt,
    _normalize_word_timings_for_subs,
    _ollama_semaphore,
    _register_prompt,
    _runtime,
    _tts_shared,
    _wait_for_vram,
    _zyg_log,
    exe,
    json,
    os,
    paths,
    requests,
    topic,
)

_BATCH = 15  # sentences per LLM call — keeps prompt under ~1200 tokens
_TAG_TYPES = ('person', 'location', 'event', 'court', 'crime_scene', 'generic')


def parse_tag_json(raw):
    """Extract a list of {type, subject} dicts from LLM JSON response."""
    try:
        raw = re.sub(r'```(?:json)?|```', '', raw).strip()
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and 'tags' in parsed:
            return parsed['tags']
    except ValueError as _exc:
        _zyg_log.debug('tag JSON did not parse, falling back to line scraping: %s', _exc)
    results = []
    for line in raw.splitlines():
        m = re.search(r'(person|location|event|court|crime_scene|generic)\s*[:\-]\s*(.+)', line, re.IGNORECASE)
        if m:
            results.append({'type': m.group(1).lower(), 'subject': m.group(2).strip().strip('"\'')})
    return results


def register_tagging_prompt(pipeline_id):
    """Register the visual tagging template prompt (instructions only, without runtime sentences)."""
    _register_prompt(
        'visual_tagging',
        'Visual Intent Tagger',
        'Tags each narration sentence with a visual type (person/location/event/court/crime_scene/generic) '
        'and a subject for image asset matching',
        'You are a visual director. For each numbered sentence below, output a JSON array '
        '(one object per sentence, same order) with keys "type" and "subject".\n'
        '"type" must be exactly one of: person, location, event, court, crime_scene, generic\n'
        '"subject" should be the specific name, place, or short description (max 5 words).\n'
        'Output ONLY valid JSON array, no explanation.\n\n'
        'Sentences: [numbered sentence batch injected at runtime]',
        pipeline_id=pipeline_id,
        stage='Stage 3b',
        topic='crime',
    )


def pick_tag_llm(_log, _tag_gpt, _stage3_llm_model, _stage3_llm_inst):
    """Pick the Ollama instance that will tag the sentences, or None for no local model.

    Prefers reusing the Stage 3 model (already hot in VRAM) and falls back to gpt-oss:20b;
    returns None straight away when OpenAI is configured or Ollama is unavailable.
    """
    _tag_llm = None
    if not _tag_gpt and OLLAMA_AVAILABLE and Ollama is not None:
        # Prefer reusing Stage 3 model (already hot in VRAM).
        # Fall back to gpt-oss:20b for tagging — fast and accurate enough.
        _tag_model_order = []
        if _stage3_llm_model:
            _tag_model_order.append((_stage3_llm_model, _stage3_llm_inst))
        if not any(m == 'gpt-oss:20b' for m, _ in _tag_model_order):
            _tag_model_order.append(('gpt-oss:20b', None))

        for _tm, _existing_inst in _tag_model_order:
            try:
                _tm_vram = _MODEL_VRAM_GB.get(_tm, 5)
                _tm_large = _tm_vram >= _LARGE_MODEL_THRESHOLD_GB
                _tm_sem = _large_llm_semaphore if _tm_large else _ollama_semaphore
                with _tm_sem:
                    # Skip VRAM check when reusing an already-loaded instance —
                    # the model is already in VRAM, checking free space is meaningless.
                    if _tm_large and _existing_inst is None:
                        if not _wait_for_vram(_tm_vram + 4, timeout=120, label=f'Stage 3b {_tm}'):
                            _log('WARNING', 'Stage 3b', f'VRAM timeout for {_tm} — skipping')
                            continue
                    if _existing_inst is not None:
                        _tag_llm = _existing_inst
                    else:
                        _tag_llm = Ollama(model=f'ollama/{_tm}', base_url=paths.ZYG_OLLAMA_URL, temperature=0.1)
                    # Quick smoke-test to confirm model responds
                    _smoke = _tag_llm.call([{'role': 'user', 'content': 'Reply: OK'}])
                    _log('INFO', 'Stage 3b', f'Using {_tm} for visual tagging')
                    break
            except Exception:
                _tag_llm = None
    return _tag_llm


def batch_tag_prompt(_batch):
    """Build the visual-tagging prompt for one batch of numbered narration sentences."""
    _numbered = '\n'.join(f'{i + 1}. {s}' for i, s in enumerate(_batch))
    _tag_prompt = (
        f'You are a visual director. For each numbered sentence below, output a JSON array '
        f'(one object per sentence, same order) with keys "type" and "subject".\n'
        f'"type" must be exactly one of: person, location, event, court, crime_scene, generic\n'
        f'"subject" should be the specific name, place, or short description (max 5 words).\n'
        f'Output ONLY valid JSON array, no explanation.\n\n'
        f'Sentences:\n{_numbered}'
    )
    if _dsl is not None:
        _tag_prompt = _dsl.wrap_user_planner(_tag_prompt, 'crime')
    return _tag_prompt


def _gpt_tag_response(pipeline_id, _tag_prompt, _batch):
    """POST one tagging batch to gpt-4o-mini; return the decoded body, or None on non-200."""
    _log_prompt(
        'gpt_visual_tag',
        'Stage 3b',
        pipeline_id,
        _tag_prompt,
        meta={'topic': topic, 'pipeline_type': 'crime', 'n_sents': len(_batch)},
        direction='sent',
        role='user',
        llm='gpt-4o-mini',
        from_who='system',
        to_who='gpt-4o-mini',
    )
    _gr = requests.post(
        'https://api.openai.com/v1/chat/completions',
        headers={
            'Authorization': f'Bearer {os.environ["OPENAI_API_KEY"]}',
            'Content-Type': 'application/json',
        },
        json={
            'model': 'gpt-4o-mini',
            'messages': [{'role': 'user', 'content': _tag_prompt}],
            'max_tokens': 800,
            'temperature': 0.1,
        },
        timeout=30,
    )
    if _gr.status_code == 200:
        return _gr.json()
    return None


def _record_gpt_tag_usage(_gr_j, pipeline_id, _batch):
    """Log the received tagging reply and record its token usage against Stage 3b."""
    _log_prompt(
        'gpt_visual_tag',
        'Stage 3b',
        pipeline_id,
        _gr_j['choices'][0]['message']['content'],
        meta={'topic': topic, 'pipeline_type': 'crime', 'n_sents': len(_batch)},
        direction='received',
        role='assistant',
        llm='gpt-4o-mini',
        from_who='gpt-4o-mini',
        to_who='system',
    )
    _gr_u = _gr_j.get('usage', {})
    if _gr_u:
        _runtime.record_token_usage(
            model='gpt-4o-mini',
            prompt_tokens=_gr_u.get('prompt_tokens', 0),
            completion_tokens=_gr_u.get('completion_tokens', 0),
            pipeline_id=pipeline_id,
            stage='Stage 3b',
            pipeline_type='crime',
            **_caveman_kw('user_planner'),
        )


def tag_sentence_batches(_log, narration_script, pipeline_id, _tag_gpt, _tag_llm):
    """Tag every narration sentence with a visual intent, in batches of fifteen.

    Returns the list of {sentence, type, subject} dicts in narration order; a sentence a
    model said nothing about still gets a row, tagged 'generic' with an empty subject.
    """
    _tag_sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', narration_script) if len(s.strip()) > 15]
    visual_tags = []  # list of {sentence, type, subject} in narration order

    for _bi in range(0, len(_tag_sentences), _BATCH):
        _batch = _tag_sentences[_bi : _bi + _BATCH]
        _tag_prompt = batch_tag_prompt(_batch)
        _batch_tags = []
        try:
            if _tag_gpt:
                _gr_j = _gpt_tag_response(pipeline_id, _tag_prompt, _batch)
                if _gr_j is not None:
                    _batch_tags = parse_tag_json(_gr_j['choices'][0]['message']['content'])
                    _record_gpt_tag_usage(_gr_j, pipeline_id, _batch)
            elif _tag_llm:
                _tr = _tag_llm.call([{'role': 'user', 'content': _tag_prompt}])
                _tr_str = _tr if isinstance(_tr, str) else getattr(_tr, 'content', str(_tr))
                _batch_tags = parse_tag_json(_tr_str)
        except Exception as _tage:
            _log('WARNING', 'Stage 3b', f'Batch {_bi // 15 + 1} tagging failed: {_tage}')

        for _ti, _sent in enumerate(_batch):
            _tag = _batch_tags[_ti] if _ti < len(_batch_tags) else {}
            visual_tags.append(
                {
                    'sentence': _sent,
                    'type': _tag.get('type', 'generic').lower(),
                    'subject': _tag.get('subject', '').strip(),
                }
            )

    _log(
        'INFO',
        'Stage 3b',
        f'Tagged {len(visual_tags)} sentences: '
        + ', '.join(f'{t}={sum(1 for x in visual_tags if x["type"] == t)}' for t in _TAG_TYPES),
    )
    return visual_tags


def crime_voice():
    """Return the crime department's assigned narrator voice, or the default on any gap."""
    crime_voice_id = 'en-US-GuyNeural'
    try:
        with open(_CHANNEL_VOICES_PATH) as _cvf:
            _cv_data = json.load(_cvf)
        _crime_assign = _cv_data.get('channels', {}).get('__crime__', {})
        if _crime_assign.get('profile_id'):
            with open(_VOICE_LIBRARY_PATH) as _vlf:
                _vl_data = json.load(_vlf)
            _vp = _vl_data.get('voices', {}).get(_crime_assign['profile_id'], {})
            if _vp.get('voice'):
                crime_voice_id = _vp['voice']
    except Exception as _exc:
        _zyg_log.warning('crime voice assignment unreadable, using the default narrator voice: %s', _exc)
    return crime_voice_id


def probe_tts_duration(_sp_crime, tts_path):
    """Return the narration's duration in seconds from ffprobe; 600.0 when it cannot be read."""
    try:
        _dur_r = _sp_crime.run(
            [exe('ffprobe'), '-v', 'quiet', '-print_format', 'json', '-show_format', tts_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return float(json.loads(_dur_r.stdout).get('format', {}).get('duration', 600))
    except Exception:
        return 600.0


def _whisper_backfill(_log, narration_script, tts_path, _word_timings):
    """Backfill word timings with a Whisper pass; returns the originals on any failure.

    2026-08-06 engine swap: no local cloner emits word timings, and this pipeline's
    tag-driven editing (person close-ups, court doc-cards, tension cues) plus
    word-boundary subtitles all key off them. Backfill exactly like pipeline_scholarly
    Stage 4 — without this the swap silently degrades every crime run to blind rotation.
    """
    try:
        from zyg_workflows import murch_engine as _mew_cr

        _log('INFO', 'Stage 4', 'Running Whisper word-timestamp pass (cloners emit no timings)…')
        _whisper_cr = _mew_cr.extract_word_timestamps_whisper(
            tts_path,
            narration_script,
        )
        if _whisper_cr:
            _word_timings = _whisper_cr
        _log('INFO', 'Stage 4', f'Whisper: {len(_whisper_cr)} word timestamps')
    except Exception as _we_cr:
        _log('WARNING', 'Stage 4', f'Whisper pass failed: {_we_cr!r}')
    return _word_timings


def _script_align_timings(_log, narration_script, _word_timings):
    """Align the word stream onto the script; keeps the raw stream below 50% coverage."""
    _wt_norm_cr = _normalize_word_timings_for_subs(_word_timings)
    _wt_aligned_cr, _wt_cov_cr = _align_narration_word_timings(
        narration_script,
        _wt_norm_cr,
    )
    if _wt_cov_cr >= 0.5:
        _word_timings = _wt_aligned_cr
        _log('INFO', 'Stage 4', f'Subtitle word stream script-aligned ({_wt_cov_cr:.0%} coverage)')
    return _word_timings


def stage_4_tts(_done, _log, _save, _sp_crime, narration_script, out_dir, pipeline_id, pipeline_state):
    """Stage 4: render the narration, measure it, and establish the word timings.

    Returns ``(tts_path, tts_duration, word_timings)`` and writes all three into
    pipeline_state. Raises RuntimeError when no engine produced audio.
    """
    tts_path = os.path.join(out_dir, f'{pipeline_id}_narration.mp3')

    # Look up crime department voice assignment
    voice = crime_voice()

    tts_ok = False
    _word_timings = []  # no cloner emits word timings — the Whisper backfill fills these

    # ── IndexTTS-2 primary, Chatterbox fallback (2026-08-06 engine swap) ──
    _eng: dict = {}
    _tts_ok_flag, _ = _tts_shared(
        narration_script,
        tts_path,
        'Stage 4',
        _log,
        voice_id=voice,
        engine_out=_eng,
    )
    if _tts_ok_flag:
        tts_ok = True
        _log('INFO', 'Stage 4', f'🎙️ TTS engine: {_eng.get("engine", "indextts2")} (seed {_eng.get("seed", "?")}) ✓')

    if not tts_ok:
        raise RuntimeError('Stage 4: TTS audio generation failed')

    tts_duration = probe_tts_duration(_sp_crime, tts_path)

    _log('INFO', 'Stage 4', f'TTS duration: {tts_duration:.0f}s ({tts_duration / 60:.1f} min)')
    if tts_duration < 480:
        _log(
            'WARNING',
            'Stage 4',
            f'TTS only {tts_duration:.0f}s — below 8min minimum (script too short, need ≥1400 words)',
        )

    if tts_ok and not _word_timings and narration_script and os.path.exists(tts_path):
        _word_timings = _whisper_backfill(_log, narration_script, tts_path, _word_timings)

    if _word_timings and narration_script:
        _word_timings = _script_align_timings(_log, narration_script, _word_timings)

    pipeline_state['tts_path'] = tts_path
    pipeline_state['tts_duration'] = tts_duration
    pipeline_state['word_timings'] = _word_timings
    _save()
    _done(
        'Stage 4: TTS Narration',
        {'duration_s': round(tts_duration, 1), 'size_kb': os.path.getsize(tts_path) // 1024},
    )
    return tts_path, tts_duration, _word_timings


def fmt_srt(s):
    """Format a time in seconds as an SRT timestamp (HH:MM:SS,mmm); negatives clamp to zero."""
    s = max(0.0, s)
    return f'{int(s // 3600):02d}:{int((s % 3600) // 60):02d}:{s % 60:06.3f}'.replace('.', ',')


def _aligned_srt_entries(narration_script, _word_timings):
    """Group the script-aligned word stream into subtitle entries of eight words.

    Returns ``(entries, source_label)``; the label says whether the script alignment was
    accepted (≥50% coverage) or the raw word boundaries were used.
    """
    from zyg_workflows import murch_engine as _me

    _srt_entries = []
    _wt_pairs = []
    for _w in _word_timings:
        try:
            _wt_pairs.append((str(_w[0]), float(_w[1])))
        except (IndexError, TypeError, ValueError) as _exc:
            _zyg_log.debug('malformed word timing skipped: %s', _exc)
            continue
    _aligned, _cov = _me.align_script_to_word_timings(
        _wt_pairs,
        narration=narration_script,
        voice_mode='narration',
        min_coverage=0.5,
    )
    _use = _aligned if _aligned and _cov >= 0.5 else [(w, t) for w, t in _wt_pairs]
    _src = 'word-boundary+script' if (_use is _aligned) else 'word-boundary'

    _chunk = 8
    for _wi in range(0, len(_use), _chunk):
        _grp = _use[_wi : _wi + _chunk]
        _ts = float(_grp[0][1])
        _te = float(_grp[-1][1]) + 0.35
        _next_i = _wi + _chunk
        if _next_i < len(_use):
            _te = min(_te, float(_use[_next_i][1]) - 0.05)
        _line = ' '.join(str(w) for w, _t in _grp)
        _srt_entries.append((_ts, max(_te, _ts + 0.3), _line))
    return _srt_entries, _src


def _raw_srt_entries(_word_timings):
    """Group the raw word-timing stream into subtitle entries of eight words.

    The fallback when the script alignment raises: each word's own duration, when the
    stream carries one, extends the entry instead of the flat 0.35 s tail.
    """
    _srt_entries = []
    _chunk = 8
    for _wi in range(0, len(_word_timings), _chunk):
        _grp = _word_timings[_wi : _wi + _chunk]
        _ts = float(_grp[0][1])
        _last = _grp[-1]
        _te = float(_last[1]) + (float(_last[2]) if len(_last) > 2 else 0.35)
        _next_i = _wi + _chunk
        if _next_i < len(_word_timings):
            _te = min(_te, float(_word_timings[_next_i][1]) - 0.05)
        _line = ' '.join(str(w[0]) for w in _grp)
        _srt_entries.append((_ts, max(_te, _ts + 0.3), _line))
    return _srt_entries


def estimated_srt_entries(narration_script, tts_duration):
    """Spread the script over the measured duration in nine-word entries.

    Used when the engine emitted no word timings at all.
    """
    _srt_entries = []
    _srt_words = narration_script.split()
    _actual_wps = len(_srt_words) / max(tts_duration, 1.0)
    _chunk = 9
    for _wi in range(0, len(_srt_words), _chunk):
        _line = ' '.join(_srt_words[_wi : _wi + _chunk])
        _ts = _wi / _actual_wps
        _te = min((_wi + _chunk) / _actual_wps, tts_duration)
        _srt_entries.append((_ts, _te, _line))
    return _srt_entries


def srt_entries(narration_script, _word_timings, tts_duration):
    """Build the subtitle entries and the label naming where their timing came from.

    Word timings are preferred; the script-aligned grouping falls back to the raw word
    boundaries if the aligner raises, and an empty stream falls back to an estimate.
    """
    if not _word_timings:
        # No word timings from the engine: estimate from total duration
        return estimated_srt_entries(narration_script, tts_duration), 'estimated'
    # Preserve script punctuation; align tokens onto timing stream.
    try:
        return _aligned_srt_entries(narration_script, _word_timings)
    except Exception:
        return _raw_srt_entries(_word_timings), 'word-boundary'


def stage_6a_srt(_log, narration_script, out_dir, pipeline_state, _title_safe, tts_duration, _word_timings):
    """Stage 6a: write the SRT subtitle file beside the video and record its path.

    Returns the written path, or None when the SRT could not be generated at all.
    """
    _srt_path = os.path.join(out_dir, f'{_title_safe}.srt')
    try:
        _entries, _src = srt_entries(narration_script, _word_timings, tts_duration)
        with open(_srt_path, 'w') as _sf:
            for _si, (_ts, _te, _line) in enumerate(_entries):
                _sf.write(f'{_si + 1}\n{fmt_srt(_ts)} --> {fmt_srt(_te)}\n{_line}\n\n')

        pipeline_state['srt_path'] = _srt_path
        _log('INFO', 'Stage 6', f'SRT: {len(_entries)} entries ({_src})')
    except Exception as _srte:
        _log('WARNING', 'Stage 6', f'SRT generation failed: {_srte}')
        _srt_path = None
    return _srt_path


@dataclass
class DocCardStyle:
    """Everything a single court document card needs besides its own text and index.

    Carries the Pillow modules and textwrap as attributes so the renderer never imports
    them itself: Stage 6b imports Pillow inside its own try, and a host without it must
    still log one warning and carry on rather than raise out of the stage.
    """

    image: object
    draw: object
    font: object
    wrap: object
    log: object
    case_name: str
    out_dir: str
    selected: dict
    font_serif: str
    font_mono: str
    font_reg: str
    n_cards: int


def _render_doc_card(style, _cdi, _sent):
    """Render one 1920x1080 case-file card for ``_sent`` and return its path, or None.

    None means the file was written but came out under 1 kB, which has already happened
    on a host with a broken font cache; the caller counts it as a miss.
    """
    _W, _H = 1920, 1080
    # Dark aged-paper background
    _img = style.image.new('RGB', (_W, _H), color=(18, 22, 35))
    _draw = style.draw.Draw(_img)
    _draw.rectangle([60, 60, _W - 60, _H - 60], outline=(180, 160, 120), width=3)
    _draw.rectangle([70, 70, _W - 70, _H - 70], outline=(120, 100, 70), width=1)

    try:
        _fnt_hdr = style.font.truetype(style.font_serif, 28)
        _fnt_body = style.font.truetype(style.font_mono, 26)
        _fnt_small = style.font.truetype(style.font_reg, 20)
    except Exception as _fe:
        style.log('WARNING', 'Stage 6', f'Font load failed ({_fe}), using default')
        _fnt_hdr = _fnt_body = _fnt_small = style.font.load_default()

    _court_header = f'CASE FILE — {style.selected.get("case_title", style.case_name).upper()}'
    _draw.text((_W // 2, 105), _court_header, fill=(200, 175, 120), font=_fnt_hdr, anchor='mm')
    _draw.text(
        (_W // 2, 140),
        f'STATE OF {style.selected.get("state", "UNITED STATES").upper()}  ·  {style.selected.get("year", "")}',
        fill=(150, 135, 100),
        font=_fnt_small,
        anchor='mm',
    )
    _draw.line([(90, 165), (_W - 90, 165)], fill=(150, 130, 90), width=2)

    _wrapped = style.wrap.wrap(_sent, width=90)
    _y_body = 220
    for _wline in _wrapped[:12]:
        _draw.text((100, _y_body), _wline, fill=(230, 220, 200), font=_fnt_body)
        _y_body += 38

    _draw.line([(90, _H - 110), (_W - 90, _H - 110)], fill=(150, 130, 90), width=1)
    _draw.text(
        (100, _H - 85),
        f'CRIME CHRONICLES  ·  DOCUMENT {_cdi + 1} OF {style.n_cards}',
        fill=(120, 110, 85),
        font=_fnt_small,
    )
    _draw.text(
        (_W - 100, _H - 85),
        f'CASE #{style.selected.get("case_number", "CLASSIFIED")}',
        fill=(120, 110, 85),
        font=_fnt_small,
        anchor='ra',
    )

    _card_path = os.path.join(style.out_dir, f'_doc_card_{_cdi:02d}.jpg')
    _img.save(_card_path, 'JPEG', quality=92)
    if os.path.exists(_card_path) and os.path.getsize(_card_path) > 1000:
        return _card_path
    style.log('WARNING', 'Stage 6', f'Doc card {_cdi} saved but empty')
    return None


def card_sentences(narration_script, tts_duration):
    """Pick the narration sentences the doc cards quote, spread over the whole script.

    Returns ``(card_sentences, n_long_sentences)``: between four and twelve sentences of
    more than sixty characters, one per ~55 s of narration.
    """
    _sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', narration_script) if len(s.strip()) > 60]
    _n_cards = max(4, min(12, int(tts_duration / 55)))
    _step = max(1, len(_sentences) // _n_cards)
    return _sentences[::_step][:_n_cards], len(_sentences)


def stage_6b_doc_cards(_log, _case_name, narration_script, out_dir, selected, tts_duration):
    """Stage 6b: generate the court document cards using Pillow.

    Returns the paths of the cards that came out non-empty, in order; a missing Pillow,
    an unreadable font or a card that fails to save is logged and skipped, never raised.
    """
    _doc_cards = []
    try:
        from PIL import Image as _PILImage, ImageDraw as _PILDraw, ImageFont as _PILFont
        import textwrap as _textwrap
        import traceback as _tb_doc

        _card_sentences, _n_sentences = card_sentences(narration_script, tts_duration)
        _log('INFO', 'Stage 6', f'Building {len(_card_sentences)} doc cards from {_n_sentences} sentences')
        _style = DocCardStyle(
            image=_PILImage,
            draw=_PILDraw,
            font=_PILFont,
            wrap=_textwrap,
            log=_log,
            case_name=_case_name,
            out_dir=out_dir,
            selected=selected,
            font_serif='/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf',
            font_mono='/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
            font_reg='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            n_cards=len(_card_sentences),
        )

        for _cdi, _sent in enumerate(_card_sentences):
            try:
                _card_path = _render_doc_card(_style, _cdi, _sent)
                if _card_path:
                    _doc_cards.append(_card_path)
            except Exception as _card_e:
                _log('WARNING', 'Stage 6', f'Doc card {_cdi} failed: {_card_e}\n{_tb_doc.format_exc()[-300:]}')

        _log('INFO', 'Stage 6', f'Generated {len(_doc_cards)}/{len(_card_sentences)} court document cards')
    except Exception as _dce:
        _log('WARNING', 'Stage 6', f'Document card generation failed: {_dce}')
    return _doc_cards
