# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""stage_helpers — stage helpers section of pipeline_remixai (verbatim split).

Moved unchanged from pipeline_remixai.py; see the package __init__ for the full docstring.
"""

from __future__ import annotations

from .core import _Stopped, _check_stop, _duration, _env_f, _log, _run, _zyg_log, exe, os, re, shutil, time


# ── helpers used by the stages ──────────────────────────────────────────────


def _gpu_holders() -> str:
    """Who is holding VRAM right now, for an error message that names names."""
    rc, out, _e = _run(
        [exe('nvidia-smi'), '--query-compute-apps=pid,used_memory,process_name', '--format=csv,noheader'], timeout=20
    )
    if rc != 0 or not out.strip():
        return 'unknown'
    rows = []
    for line in out.strip().splitlines()[:4]:
        parts = [x.strip() for x in line.split(',')]
        if len(parts) >= 3:
            rows.append(f'{os.path.basename(parts[2])}({parts[0]}) {parts[1]}')
    return '; '.join(rows) or 'unknown'


def _free_comfy_vram(pid, stage, min_free_gb=None) -> bool:
    """Make room for ollama before the VLM/LLM stages. Returns True if we got it.

    WAITS rather than giving up. The first version did the safe thing on both
    halves and still killed the job: it refused to disturb a SAMPLING ComfyUI
    (correct — never yank VRAM out from under someone's render), which meant
    VRAM was never freed, and the fail-closed per-call gate then returned
    nothing for all 8 frames and the run died 11 seconds in with a message
    blaming ollama. Two individually-correct safety behaviours composing into a
    hard failure is still a hard failure. Another tenant's render finishing is a
    thing worth waiting for, so now it waits for it.
    """
    min_free_gb = float(min_free_gb if min_free_gb is not None else _env_f('ZYG_REMIXAI_VLM_MIN_FREE_GB', 9))
    budget = _env_f('ZYG_REMIXAI_VRAM_WAIT_S', 900)
    try:
        from zyg_workflows import comfy_offload as CO
    except Exception as e:
        _log(pid, 'WARNING', stage, f'comfy_offload unavailable ({e}) — not freeing VRAM')
        return False

    def _lg(m):
        _log(pid, 'INFO', stage, m)

    deadline = time.time() + budget
    try:
        # 1. let any live render finish on its own terms
        waited = False
        while CO.comfy_is_sampling() and time.time() < deadline:
            if not waited:
                _log(
                    pid,
                    'INFO',
                    stage,
                    f'ComfyUI is SAMPLING — waiting for it to finish rather than interrupting (up to {int(budget)}s)',
                )
                waited = True
            _check_stop(pid)
            time.sleep(10)
        if CO.comfy_is_sampling():
            _log(pid, 'WARNING', stage, f'ComfyUI still sampling after {int(budget)}s — leaving it alone')
            return (CO.gpu_free_gb() or 0) >= min_free_gb

        # 2. ask it to unload, then 3. confirm the VRAM actually appeared
        before = CO.gpu_free_gb()
        CO.comfy_free(log_fn=_lg)
        got = CO.wait_for_vram(min_free_gb, timeout_s=max(30, deadline - time.time()), log_fn=_lg)
        after = CO.gpu_free_gb()
        _log(
            pid,
            'INFO',
            stage,
            f'VRAM for ollama: {before if before is None else round(before, 1)} → '
            f'{after if after is None else round(after, 1)} GB free '
            f'(need {min_free_gb:.0f}) — {"OK" if got else "STILL SHORT"}',
        )
        return bool(got)
    except _Stopped:
        raise
    except Exception as e:
        _log(pid, 'WARNING', stage, f'VRAM release failed: {e}')
        return False


def _flag(name, default='1'):
    return str(os.environ.get(name, default)).strip().lower() not in ('0', 'false', 'no', 'off')


def _slug(s: str) -> str:
    return re.sub(r'_+', '_', re.sub(r'[^A-Za-z0-9]+', '_', (s or '').lower())).strip('_')[:60]


def _asr(pid, media_path):
    """Local ASR when captions are missing. Fail-closed on a busy GPU: a render
    must never be squeezed for a transcript."""
    try:
        from zyg_workflows import comfy_offload as CO

        if CO.comfy_is_sampling():
            _log(pid, 'WARNING', 'Transcript Analysis', 'GPU busy — skipping ASR')
            return None
    except Exception as _exc:
        _zyg_log.warning('GPU-busy probe failed, running ASR without the fail-closed guard: %s', _exc)
    try:
        import zyg_whisper as _zw

        segs, _info = _zw.transcribe_segments(media_path, language='en', want_words=False, vad=True)
        try:
            _zw.unload_models()
        except Exception as _exc:
            _zyg_log.debug('whisper model unload skipped: %s', _exc)
        return [
            {'start': float(s['start']), 'end': float(s['end']), 'text': (s.get('text') or '').strip()}
            for s in segs
            if (s.get('text') or '').strip()
        ]
    except Exception as e:
        _log(pid, 'WARNING', 'Transcript Analysis', f'ASR failed: {e}')
        return None


def _delete_source(pid, work, vid):
    """Delete the downloaded source and every frame cut from it. Called the
    moment analysis completes — the pipeline never reads it again."""
    removed = 0
    for p in (os.path.join(work, f'{vid}.mp4'), os.path.join(work, 'src_bed.wav')):
        try:
            if os.path.isfile(p):
                os.remove(p)
                removed += 1
        except OSError as _exc:
            _zyg_log.warning('source cleanup failed, %s stays on disk: %s', p, _exc)
    fr = os.path.join(work, 'src_frames')
    if os.path.isdir(fr):
        removed += len([f for f in os.listdir(fr)])
        shutil.rmtree(fr, ignore_errors=True)
    _log(pid, 'INFO', 'Soundtrack Analysis', f'source material deleted ({removed} file(s)) — analysis complete')


def _backfill_images(beats):
    """A beat whose still failed borrows the nearest successful one rather than
    dropping its line: the script is the spine, and a missing picture should cost
    a repeated visual, not a hole in the argument."""
    last = None
    for b in beats:
        if b.get('image'):
            last = b['image']
        elif last:
            b['image'] = last
    nxt = None
    for b in reversed(beats):
        if b.get('image'):
            nxt = b['image']
        elif nxt:
            b['image'] = nxt


def _too_similar(a: str, b: str) -> bool:
    """Reject a generated title that leans on the source's actual wording.
    Jaccard over content words ≥ 0.6, or a shared run of 5+ consecutive words."""
    stop = {
        'the',
        'a',
        'an',
        'of',
        'to',
        'in',
        'is',
        'it',
        'and',
        'or',
        'for',
        'on',
        'with',
        'this',
        'that',
        'you',
        'your',
        'i',
        'my',
        'we',
    }
    wa = [w for w in re.findall(r'[a-z0-9]+', (a or '').lower()) if w not in stop]
    wb = [w for w in re.findall(r'[a-z0-9]+', (b or '').lower()) if w not in stop]
    if not wa or not wb:
        return False
    sa, sb = set(wa), set(wb)
    if len(sa & sb) / max(1, len(sa | sb)) >= 0.6:
        return True
    for i in range(len(wa) - 4):
        if ' '.join(wa[i : i + 5]) in ' '.join(wb):
            return True
    return False


def _replace_soundtrack(pid, video_in, req, out_dir, work, manifest, title):
    """Step 6b — a DIFFERENT track of the same genre, from our own licensed
    library (audio_service tiers), mixed under the narration."""
    stage = 'Soundtrack Replacement'
    out = os.path.join(work, 'scored.mp4')
    try:
        from zyg_workflows import audio_service as _as
    except Exception as e:
        _log(pid, 'WARNING', stage, f'audio_service unavailable ({e}) — no music')
        shutil.copy2(video_in, out)
        return out
    dur = int(_duration(video_in)) or 60
    try:
        music = _as.get_music_for_topic(
            (manifest.get('analysis', {}).get('brief', {}) or {}).get('topic') or title,
            req.get('source_mood') or 'neutral',
            out_dir=os.path.join(work, 'music'),
            duration_s=dur,
            music_mood=req.get('mood') or None,
            log_fn=lambda m: _log(pid, 'INFO', stage, m),
        )
    except Exception as e:
        _log(pid, 'WARNING', stage, f'music selection raised: {e}')
        music = None
    if not music:
        _log(pid, 'WARNING', stage, 'no replacement track available — delivering narration only')
        shutil.copy2(video_in, out)
        manifest['output']['music'] = {'replaced': False, 'reason': 'no track'}
        return out
    try:
        ok = _as.mix_bgm_into_video(
            video_in,
            music,
            out,
            music_vol=_env_f('ZYG_REMIXAI_MUSIC_VOL', 0.14),
            log_fn=lambda m: _log(pid, 'INFO', stage, m),
        )
    except Exception as e:
        _log(pid, 'WARNING', stage, f'mix raised: {e}')
        ok = False
    if not ok or not os.path.isfile(out):
        _log(pid, 'WARNING', stage, 'mix failed — delivering narration only')
        shutil.copy2(video_in, out)
        manifest['output']['music'] = {'replaced': False, 'reason': 'mix failed'}
        return out
    manifest['output']['music'] = {
        'replaced': True,
        'track': os.path.basename(music),
        'requested_mood': req.get('mood'),
        'source_genre': req.get('genre'),
        'clap_confident': req.get('confident'),
    }
    _log(pid, 'INFO', stage, f'soundtrack replaced → {os.path.basename(music)} (mood {req.get("mood")})')
    return out


def _write_description(out_dir, title, newt, brief, manifest):
    """Operator-facing upload sheet. Deliberately NOT auto-published — the remix
    department made the same call and it holds here: a human reads this first."""
    alts = '\n'.join(f'  - {a}' for a in (newt.get('alternates') or []))
    src = manifest.get('source', {})
    mus = manifest.get('output', {}).get('music', {})
    dv = (manifest.get('regenerated', {}) or {}).get('divergence', {}) or {}
    dm = dv.get('metrics', {}) or {}
    cos = dm.get('max_sentence_cosine')
    div_block = (
        f'  verdict             : {dv.get("verdict", "not run").upper()}\n'
        f'  5-gram containment  : {dm.get("containment_5gram", "—")} '
        f'(fails above {(dv.get("thresholds") or {}).get("containment_5gram", "—")})\n'
        f'  longest shared run  : {dm.get("longest_shared_run", "—")} words '
        f'(fails above {(dv.get("thresholds") or {}).get("longest_shared_run", "—")})\n'
        f'  closest sentence    : {"n/a" if cos is None else cos} '
        f'(fails above {(dv.get("thresholds") or {}).get("max_sentence_cosine", "—")})\n'
        f'  paraphrase check    : {dv.get("semantic", "not run")}\n'
    )
    txt = f"""TITLE
{title}

ALTERNATE TITLES
{alts or '  (none)'}

TOPIC
{brief.get('topic', '')}

ANGLE
{brief.get('angle', '')}

PROVENANCE (not for publication — operator record)
  studied format from : {src.get('video_id', '')} — {src.get('channel', '')}
  study signal        : {src.get('velocity', 0)} views/h, ai_score {src.get('ai_score', 0)}
  source retained     : NO (deleted after analysis)
  images              : generated ({manifest.get('output', {}).get('model_family', '')})
  script              : written from a structural brief, not the source transcript
  title               : written to the source's FORMAT, not from its words
  soundtrack          : {'replaced with ' + mus.get('track', '') if mus.get('replaced') else 'none'}

DIVERGENCE (measured against the source transcript, which was not retained)
{div_block}
OUTPUT
  {manifest.get('output', {}).get('path', '')}
  {manifest.get('output', {}).get('duration_s', 0)}s · {manifest.get('output', {}).get('geometry', {}).get('label', '')}
"""
    try:
        with open(os.path.join(out_dir, 'upload_sheet.txt'), 'w', encoding='utf-8') as f:
            f.write(txt)
    except OSError as _exc:
        _zyg_log.warning('upload_sheet.txt write failed, the delivery has no upload sheet: %s', _exc)
