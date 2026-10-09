# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_stages — the fourteen stages ``_run_pipeline`` walks, one helper per phase.

Extracted from ``pipeline._run_pipeline`` (2026-10-09), which was a single 488-line
function. Nothing here changes what the department does: every log line, every gate
and every side effect is in the order the one function had them. What changed is the
seam — each phase now takes a :class:`RunContext`, so the pure parts of it
(candidate choice, manifest assembly, narration arithmetic, what of a divergence
report is allowed to persist) can be exercised without YouTube, a GPU or a job board.

The orchestrator keeps the error funnel (``_Stopped`` / failure / ``finally``) and the
``_seal.seal`` call, which ``scripts/check_seal_hooks.py`` requires to be inside
``_run_pipeline`` itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .core import (
    DEPARTMENT,
    RA,
    RD,
    RI,
    _OUT_ROOT,
    _check_stop,
    _duration,
    _env_f,
    _env_i,
    _jobs,
    _log,
    _marker,
    _now_iso,
    _update_stage,
    disk_ok,
    os,
    shutil,
    time,
)
from .media import (
    _build_image_prompt,
    _burn_subs,
    _concat,
    _gen_still,
    _ken_burns_segment,
    _model_family,
    _tts_line,
    _write_srt,
    _write_vtt,
    output_geometry,
    target_seconds,
)
from .stage_helpers import (
    _asr,
    _backfill_images,
    _delete_source,
    _flag,
    _free_comfy_vram,
    _gpu_holders,
    _replace_soundtrack,
    _slug,
    _too_similar,
    _write_description,
)

#: The candidate fields the manifest keeps about the source video.
SOURCE_KEYS = ('video_id', 'title', 'channel', 'view_count', 'velocity', 'ai_score', 'duration', 'url', 'term')
#: The probe fields added to the manifest's source section once the file is on disk.
PROBE_KEYS = ('width', 'height', 'duration', 'fps', 'aspect')


@dataclass
class RunContext:
    """Everything one ``_run_pipeline`` call carries from one stage to the next.

    The fields are exactly the locals the original function threaded through its
    fourteen stages; each stage fills the ones it owns and reads the ones before it.
    """

    pid: str
    out_dir: str
    work: str
    mid: Any
    manifest: dict
    src_path: str | None = None
    cand: dict = field(default_factory=dict)
    vid: str = ''
    src_info: dict = field(default_factory=dict)
    geo: dict = field(default_factory=dict)
    tgt_s: float = 0.0
    descs: list = field(default_factory=list)
    style: Any = None
    segs: list = field(default_factory=list)
    brief: dict = field(default_factory=dict)
    req: Any = None
    script: dict = field(default_factory=dict)
    beats: list = field(default_factory=list)
    title: str = ''
    newt: dict = field(default_factory=dict)
    parts: list = field(default_factory=list)
    scored: str = ''
    final: str = ''
    burned: bool = False


def new_run(pid):
    """A fresh :class:`RunContext` for pipeline *pid*, with its work directory made.

    Reads the job's ``output_dir`` (falling back to ``_OUT_ROOT/<pid>``), creates
    ``<out_dir>/work``, registers the ``remixai-<pid>`` marker and seeds the manifest.
    """
    job = _jobs().get(pid) or {}
    out_dir = job.get('output_dir') or os.path.join(_OUT_ROOT, pid)
    work = os.path.join(out_dir, 'work')
    os.makedirs(work, exist_ok=True)
    return RunContext(
        pid=pid,
        out_dir=out_dir,
        work=work,
        mid=_marker(f'remixai-{pid}', pid),
        manifest={
            'pipeline_id': pid,
            'department': DEPARTMENT,
            'started': _now_iso(),
            'source': {},
            'analysis': {},
            'regenerated': {},
            'output': {},
        },
    )


def pick_candidate(cands, seen):
    """The first candidate in *cands* this department has not already worked.

    *seen* is ``remixai_ingest.seen()`` — ``{video_id: {'state': …}}``; a candidate
    whose state is ``'worked'`` is skipped. Returns ``None`` when every one is worked.
    """
    return next((c for c in cands if (seen.get(c['video_id']) or {}).get('state') != 'worked'), None)


def source_manifest(cand):
    """The manifest's ``source`` section for candidate *cand*: :data:`SOURCE_KEYS` only.

    Every key is present even when the candidate does not carry it, so the manifest
    shape never depends on which sweep found the video.
    """
    return {k: cand.get(k) for k in SOURCE_KEYS}


def narration_stats(beats):
    """``(spoken_seconds, spoken_words, measured_wpm)`` over the voiced *beats*.

    Seconds come from every beat's ``wav_dur``; words only from beats that actually
    have a ``wav``. The rate is 0.0 until there is more than a second of audio, so a
    single short beat cannot report a wild words-per-minute figure.
    """
    spoken_s = sum(b.get('wav_dur') or 0.0 for b in beats)
    spoken_w = sum(len((b.get('text') or '').split()) for b in beats if b.get('wav'))
    return spoken_s, spoken_w, (60.0 * spoken_w / spoken_s) if spoken_s > 1 else 0.0


def divergence_to_persist(div_report):
    """The part of a divergence report the manifest is allowed to keep.

    ``evidence`` quotes the source's own sentences, so it survives only when the gate
    FAILED and a human has to see why; a shipped episode's manifest carries the scores
    and nothing of the source's text. The input is never mutated.
    """
    persisted = dict(div_report)
    if div_report['verdict'] != 'fail':
        persisted.pop('evidence', None)
    return persisted


def stage_source(run, video_id):
    """Stages 1–2 — Source Sweep and Source Download.

    Picks *video_id* (or the best unworked candidate), downloads it into ``run.work``
    and probes it. Fills ``cand``, ``vid``, ``src_path``, ``src_info``, ``geo``,
    ``tgt_s`` and the manifest's source/output geometry. Raises ``RuntimeError`` when
    the disk gate refuses, no source is eligible, or the download fails.
    """
    pid = run.pid

    # ── Stage 1: Source Sweep ───────────────────────────────────────────
    _update_stage(pid, 'Source Sweep', 2)
    ok, why = disk_ok()
    if not ok:
        raise RuntimeError(f'disk gate: {why}')
    _log(pid, 'INFO', 'Source Sweep', why)

    cand = None
    if video_id:
        cand = next((c for c in RI.ranked_candidates(50) if c.get('video_id') == video_id), None) or RI.probe(video_id)
        if cand:
            cand.setdefault(
                'ai_score', RI.ai_score(cand.get('title', ''), cand.get('description', ''), cand.get('tags'))
            )
    else:
        cands = RI.ranked_candidates(20)
        if not cands:
            _log(pid, 'INFO', 'Source Sweep', 'no cached candidates — sweeping now')
            cands = RI.sweep(log=lambda m: _log(pid, 'INFO', 'Source Sweep', m)).get('candidates') or []
        cand = pick_candidate(cands, RI.seen())
    if not cand or not cand.get('video_id'):
        raise RuntimeError('no eligible source found (widen terms or lower min_views)')

    run.cand = cand
    run.vid = vid = cand['video_id']
    run.manifest['source'] = source_manifest(cand)
    _log(
        pid,
        'INFO',
        'Source Sweep',
        f'source {vid} · "{(cand.get("title") or "")[:70]}" · '
        f'{cand.get("velocity", 0)} views/h · ai_score {cand.get("ai_score", 0)}',
    )
    _check_stop(pid)

    # ── Stage 2: Source Download ────────────────────────────────────────
    _update_stage(pid, 'Source Download', 8)
    dl = RI.download(vid, run.work, log=lambda m: _log(pid, 'INFO', 'Source Download', m))
    if dl.get('error'):
        RI.mark_seen(vid, state='failed', error=dl['error'][:200])
        raise RuntimeError(f'download failed: {dl["error"]}')
    run.src_path = dl['path']
    run.src_info = src_info = RA.probe_video(run.src_path)
    run.manifest['source'].update({k: src_info.get(k) for k in PROBE_KEYS})
    run.geo = geo = output_geometry(src_info)
    run.tgt_s = tgt_s = target_seconds(src_info)
    run.manifest['output']['geometry'] = geo
    run.manifest['output']['target_seconds'] = round(tgt_s, 1)
    _log(
        pid,
        'INFO',
        'Source Download',
        f'{src_info.get("width")}×{src_info.get("height")} '
        f'{src_info.get("duration", 0):.1f}s → output {geo["label"]} '
        f'{geo["w"]}×{geo["h"]} @ {tgt_s:.0f}s',
    )
    # transcript sidecar named for the inspection tab's download exclusion
    # (kanban_server._api_videos hides any mp4 sharing a '<id>_transcript.json'
    # prefix) — written now so the source never shows as a deliverable.
    RI._save(os.path.join(run.work, f'{vid}_transcript.json'), {'video_id': vid})
    _check_stop(pid)


def stage_analysis(run):
    """Stages 3–4 — Frame Analysis and Transcript Analysis.

    Frees ComfyUI's VRAM, samples and describes frames, then reads the transcript
    (captions, else local ASR) into a structural brief. Fills ``descs``, ``style``,
    ``segs``, ``brief`` and the manifest's analysis section. Raises ``RuntimeError``
    when sampling, the VLM, the transcript or the brief's divergence gate fail.
    """
    pid = run.pid

    # ── Stage 3: Frame Analysis ─────────────────────────────────────────
    _update_stage(pid, 'Frame Analysis', 16)
    # RELEASE COMFYUI'S VRAM FIRST. The .env sets ZYG_COMFY_KEEP_LOADED=1, so
    # ComfyUI holds its checkpoints resident indefinitely — measured at 47.5 GB
    # of 49 GB on this box. The next three stages are ollama's (vision + two
    # text passes) and ollama cannot fit beside that: on the first attempt it
    # was evicted entirely and each frame crawled toward its timeout, taking
    # the stage from ~40 s to over 20 minutes. Freeing here costs ComfyUI a
    # reload at Stage 8, which is one-off and happens while there is nothing
    # else to do. Multi-tenant safe: comfy_free only measures ComfyUI's own PID.
    _vram_ok = _free_comfy_vram(pid, 'Frame Analysis')
    if not _vram_ok:
        _log(
            pid,
            'WARNING',
            'Frame Analysis',
            f'proceeding without the VRAM headroom ollama wants — holders: {_gpu_holders()}',
        )
    n_frames = _env_i('ZYG_REMIXAI_FRAMES', 8)
    frames = RA.sample_frames(
        run.src_path,
        os.path.join(run.work, 'src_frames'),
        n=n_frames,
        log=lambda m: _log(pid, 'INFO', 'Frame Analysis', m),
    )
    if not frames:
        raise RuntimeError('frame sampling produced nothing')
    descs = RA.describe_frames(frames, log=lambda m: _log(pid, 'INFO', 'Frame Analysis', m))
    if not descs:
        # Name the actual cause. "ollama down or GPU busy" sent me looking at
        # ollama when the answer was a co-tenant holding 17 GB.
        raise RuntimeError(
            'VLM returned no frame descriptions — '
            + (
                f'GPU headroom never freed (holders: {_gpu_holders()})'
                if not _vram_ok
                else 'ollama returned nothing (is it running?)'
            )
        )
    run.descs = descs
    run.style = style = RA.visual_style_summary(descs, log=lambda m: _log(pid, 'INFO', 'Frame Analysis', m))
    run.manifest['analysis']['frames'] = descs
    run.manifest['analysis']['style'] = style
    _check_stop(pid)

    # ── Stage 4: Transcript Analysis ────────────────────────────────────
    _update_stage(pid, 'Transcript Analysis', 26)
    segs = RI.fetch_captions(run.vid)
    tsrc = 'captions'
    if not segs:
        _log(pid, 'INFO', 'Transcript Analysis', 'no captions — trying local ASR')
        segs, tsrc = _asr(pid, run.src_path), 'whisper'
    if not segs:
        raise RuntimeError('no transcript available (no captions, ASR unavailable)')
    run.segs = segs
    brief = RA.analyze_transcript(
        segs, run.src_info.get('duration') or 0, log=lambda m: _log(pid, 'INFO', 'Transcript Analysis', m)
    )
    if not brief or not brief.get('beats'):
        raise RuntimeError('structural brief extraction failed')
    run.brief = brief

    # THE BRIEF'S OWN GATE. The brief now carries the source's substance —
    # claims, figures, named things — which is the whole point and also the
    # one change that could turn it into a channel for the source's WORDING.
    # A contaminated brief poisons everything downstream and no amount of
    # care in the writer fixes it, so it fails here rather than later.
    _bd = brief.get('brief_divergence') or {}
    if _bd.get('verdict') == 'fail':
        raise RuntimeError(
            'brief divergence gate failed: '
            f'{", ".join(_bd.get("failed") or [])} — the extracted brief '
            'reproduces the source transcript rather than abstracting it'
        )
    if _bd.get('verdict') == 'unavailable':
        _log(
            pid,
            'WARNING',
            'Transcript Analysis',
            'brief divergence UNMEASURED — the script gate still runs, but the brief itself went unchecked',
        )
    _san = brief.get('_sanitizer') or {}
    if _san.get('dropped') or _san.get('trimmed'):
        _log(
            pid,
            'INFO',
            'Transcript Analysis',
            f'brief sanitiser: {_san.get("dropped", 0)} dropped, {_san.get("trimmed", 0)} trimmed',
        )
    run.manifest['analysis']['transcript_source'] = tsrc
    run.manifest['analysis']['brief'] = brief
    _check_stop(pid)


def stage_soundtrack(run):
    """Stage 5 — Soundtrack Analysis, then the source's deletion.

    Reads the music bed's character into the manifest and derives the replacement
    request (``run.req``). Analysis is complete at the end of it, so the downloaded
    source is deleted here: this department must not retain other people's video.
    """
    pid = run.pid
    _update_stage(pid, 'Soundtrack Analysis', 34)
    music = {}
    if run.src_info.get('has_audio'):
        bed = RA.extract_music_bed(
            run.src_path,
            os.path.join(run.work, 'src_bed.wav'),
            log=lambda m: _log(pid, 'INFO', 'Soundtrack Analysis', m),
        )
        if bed:
            music = RA.analyze_music(bed, log=lambda m: _log(pid, 'INFO', 'Soundtrack Analysis', m))
    if not music:
        _log(pid, 'WARNING', 'Soundtrack Analysis', 'no soundtrack reading — replacement falls back to a calm bed')
    run.manifest['analysis']['music'] = music
    run.req = req = RA.music_request(music)
    run.manifest['analysis']['music_request'] = req

    # SOURCE DELETION. Analysis is complete; nothing downstream reads the
    # source again, and this department must not retain other people's video.
    _delete_source(pid, run.work, run.vid)
    run.src_path = None
    _check_stop(pid)


def stage_script(run):
    """Stage 6 — Script Regeneration behind the divergence gate.

    Writes a new script from the abstract brief and measures it against the source
    transcript, retrying with the gate's own instruction up to
    ``ZYG_REMIXAI_DIVERGENCE_TRIES`` times. Fails closed: a script that still scores
    too close after every attempt raises unless ``ZYG_REMIXAI_DIVERGENCE_WARN`` is set.
    """
    pid = run.pid
    _update_stage(pid, 'Script Regeneration', 40)
    # The source transcript stays in MEMORY for the gate and is never written
    # to the manifest or to disk. It is the yardstick, not an input: the
    # writer never sees it (regenerate_script takes the abstract brief only),
    # and the gate only ever measures against it.
    source_text = ' '.join((sg.get('text') or '').strip() for sg in run.segs)
    script, div_report, extra = None, None, ''
    tries = _env_i('ZYG_REMIXAI_DIVERGENCE_TRIES', 3)
    for attempt in range(1, tries + 1):
        _check_stop(pid)
        cand_script = RA.regenerate_script(
            run.brief, run.tgt_s, log=lambda m: _log(pid, 'INFO', 'Script Regeneration', m), extra_instruction=extra
        )
        if not cand_script or not cand_script.get('beats'):
            _log(pid, 'WARNING', 'Script Regeneration', f'attempt {attempt}/{tries}: no script returned')
            continue
        cand_text = ' '.join(b['text'] for b in cand_script['beats'])
        div_report = RD.check(
            cand_text,
            source_text,
            log=lambda m, _a=attempt: _log(pid, 'INFO', 'Script Regeneration', f'attempt {_a}/{tries} — {m}'),
        )
        script = cand_script
        if div_report['verdict'] in ('pass', 'degraded'):
            break
        extra = RD.retry_instruction(div_report)
        _log(
            pid,
            'WARNING',
            'Script Regeneration',
            f'attempt {attempt}/{tries} breached {", ".join(div_report["failed"])} — regenerating',
        )
    if not script or not script.get('beats'):
        raise RuntimeError('script regeneration failed (ollama down or GPU busy)')
    if div_report is None:
        raise RuntimeError('divergence gate never ran — refusing to ship unmeasured')

    # FAIL CLOSED. A script that still scores too close to the source after
    # every attempt does not ship; the operator can downgrade this to a
    # warning, but never by accident and never silently.
    if div_report['verdict'] == 'fail':
        if _flag('ZYG_REMIXAI_DIVERGENCE_WARN', '0'):
            _log(
                pid,
                'WARNING',
                'Script Regeneration',
                'DIVERGENCE GATE FAILED after every attempt — shipping anyway '
                'because ZYG_REMIXAI_DIVERGENCE_WARN is set',
            )
        else:
            raise RuntimeError(
                'divergence gate failed after '
                f'{tries} attempt(s): {", ".join(div_report["failed"])}. '
                'The script scored too close to the source material.'
            )
    if div_report['verdict'] == 'degraded':
        _log(
            pid,
            'WARNING',
            'Script Regeneration',
            'divergence gate DEGRADED — the lexical checks passed but the '
            'embedding model was unavailable, so paraphrase went unmeasured '
            '(set ZYG_REMIXAI_DIVERGENCE_STRICT=1 to make this blocking)',
        )
        if _flag('ZYG_REMIXAI_DIVERGENCE_STRICT', '0'):
            raise RuntimeError('divergence gate degraded and strict mode is on')

    run.script = script
    run.manifest['regenerated']['script'] = script
    run.manifest['regenerated']['divergence'] = divergence_to_persist(div_report)
    _check_stop(pid)


def stage_title(run):
    """Stage 7 — Title Regeneration, with the overlap fallback.

    Learns the source title's FORMAT and writes a new title for the brief's topic and
    angle. A title that still overlaps the source too closely is dropped for the
    topic itself. Fills ``run.title`` and ``run.newt``.
    """
    pid = run.pid
    _update_stage(pid, 'Title Regeneration', 46)
    tfmt = RA.analyze_title(run.cand.get('title', ''), log=lambda m: _log(pid, 'INFO', 'Title Regeneration', m))
    newt = RA.regenerate_title(
        tfmt,
        run.brief.get('topic', ''),
        run.brief.get('angle', ''),
        log=lambda m: _log(pid, 'INFO', 'Title Regeneration', m),
    )
    title = (newt.get('title') or '').strip() or (run.brief.get('topic') or 'Untitled').title()
    if _too_similar(title, run.cand.get('title', '')):
        _log(
            pid,
            'WARNING',
            'Title Regeneration',
            'generated title overlapped the source too closely — using the topic instead',
        )
        title = (run.brief.get('topic') or 'Untitled').title()
        newt = {'title': title, 'alternates': [], 'source': 'fallback'}
    run.title, run.newt = title, newt
    run.manifest['regenerated']['title_format'] = tfmt
    run.manifest['regenerated']['title'] = newt
    _log(pid, 'INFO', 'Title Regeneration', f'title: {title}')
    _check_stop(pid)


def stage_visuals(run):
    """Stages 8–10 — AI Image Generation, TTS Narration and Ken Burns Animation.

    One still per beat (a beat without one reuses its neighbour), one narration wav
    per beat, one animated segment per beat that has an image. Fills ``run.beats`` and
    ``run.parts`` and records the measured narration rate in the manifest. Raises
    ``RuntimeError`` when no image, no audio or no segment at all could be produced.
    """
    pid = run.pid

    # ── Stage 8: AI Image Generation ────────────────────────────────────
    _update_stage(pid, 'AI Image Generation', 52)
    img_dir = os.path.join(run.out_dir, 'images')
    os.makedirs(img_dir, exist_ok=True)
    run.beats = beats = run.script['beats']
    descs, geo = run.descs, run.geo
    made = []
    for i, b in enumerate(beats):
        _check_stop(pid)
        hint = descs[min(int(i * len(descs) / max(1, len(beats))), len(descs) - 1)]
        prompt = _build_image_prompt(b.get('visual') or run.brief.get('topic', ''), run.style, hint)
        dest = os.path.join(img_dir, f'beat_{i:02d}.png')
        b['image_prompt'] = prompt
        if _gen_still(pid, prompt, dest, geo):
            b['image'] = dest
            made.append(dest)
        else:
            b['image'] = None
        _jobs()[pid]['progress_pct'] = 52 + int(20 * (i + 1) / len(beats))
    if not made:
        raise RuntimeError('no images generated — ComfyUI unavailable or all attempts failed')
    # a beat with no image reuses its neighbour rather than dropping the line
    _backfill_images(beats)
    _log(
        pid,
        'INFO',
        'AI Image Generation',
        f'{len(made)}/{len(beats)} still(s) generated at {geo["iw"]}×{geo["ih"]}',
    )
    _check_stop(pid)

    # ── Stage 9: TTS Narration ──────────────────────────────────────────
    _update_stage(pid, 'TTS Narration', 74)
    voiced = 0
    for i, b in enumerate(beats):
        _check_stop(pid)
        wav = os.path.join(run.work, f'beat_{i:02d}.wav')
        if _tts_line(pid, b['text'], wav):
            b['wav'] = wav
            b['wav_dur'] = _duration(wav)
            voiced += 1
        else:
            b['wav'] = None
            b['wav_dur'] = 0.0
    if not voiced:
        raise RuntimeError('TTS produced no audio for any beat')
    _spoken_s, _spoken_w, _meas_wpm = narration_stats(beats)
    run.manifest['output']['tts_wpm_measured'] = round(_meas_wpm, 1)
    run.manifest['output']['narration_seconds'] = round(_spoken_s, 1)
    _log(
        pid,
        'INFO',
        'TTS Narration',
        f'{voiced}/{len(beats)} beat(s) voiced — {_spoken_w} words in '
        f'{_spoken_s:.1f}s = {_meas_wpm:.0f} wpm '
        f'(budgeted at {RA._tts_wpm()} wpm; re-derive the constant if these drift)',
    )
    _check_stop(pid)

    # ── Stage 10: Ken Burns Animation ───────────────────────────────────
    _update_stage(pid, 'Ken Burns Animation', 80)
    parts, t_cursor = [], 0.0
    for i, b in enumerate(beats):
        _check_stop(pid)
        if not b.get('image'):
            continue
        seg = os.path.join(run.work, f'seg_{i:02d}.mp4')
        res = _ken_burns_segment(
            b['image'], b.get('wav'), seg, geo, min_seconds=_env_f('ZYG_REMIXAI_MIN_BEAT_S', 2.2), direction=i
        )
        path, dur = res[0], res[1]
        if not path:
            _log(pid, 'WARNING', 'Ken Burns Animation', f'beat {i} segment failed: {res[2] if len(res) > 2 else ""}')
            continue
        b['start'] = round(t_cursor + 0.25, 3)  # lead_in offset
        b['dur'] = round(max(0.6, (b.get('wav_dur') or dur)), 3)
        t_cursor += dur
        parts.append(path)
        _jobs()[pid]['progress_pct'] = 80 + int(6 * (i + 1) / len(beats))
    if not parts:
        raise RuntimeError('no Ken Burns segments rendered')
    run.parts = parts
    _log(pid, 'INFO', 'Ken Burns Animation', f'{len(parts)} segment(s), {t_cursor:.1f}s total')
    _check_stop(pid)


def stage_assembly(run):
    """Stages 11–13 — Video Assembly, Soundtrack Replacement and Subtitle Burn.

    Concatenates the segments, scores them with the replacement bed, then lands
    ``FINAL_<slug>.mp4`` in the output directory — subtitles burned in when
    ``ZYG_REMIXAI_BURN_SUBS`` allows and the burn succeeds, otherwise unburned, with a
    sibling WebVTT either way. Fills ``run.scored``, ``run.final`` and ``run.burned``.
    """
    pid = run.pid

    # ── Stage 11: Video Assembly ────────────────────────────────────────
    _update_stage(pid, 'Video Assembly', 87)
    assembled = os.path.join(run.work, 'assembled.mp4')
    ok_cat, err = _concat(run.parts, assembled, run.work)
    if not ok_cat:
        raise RuntimeError(f'concat failed: {err}')
    geo = run.geo
    _log(pid, 'INFO', 'Video Assembly', f'assembled {_duration(assembled):.1f}s at {geo["w"]}×{geo["h"]}')
    _check_stop(pid)

    # ── Stage 12: Soundtrack Replacement ────────────────────────────────
    _update_stage(pid, 'Soundtrack Replacement', 90)
    run.scored = scored = _replace_soundtrack(pid, assembled, run.req, run.out_dir, run.work, run.manifest, run.title)
    _check_stop(pid)

    # ── Stage 13: Subtitle Burn ─────────────────────────────────────────
    _update_stage(pid, 'Subtitle Burn', 94)
    srt = _write_srt([b for b in run.beats if b.get('dur')], os.path.join(run.work, 'subs.srt'))
    final_stem = _slug(run.title) or f'remixai_{pid[:8]}'
    run.final = final = os.path.join(run.out_dir, f'FINAL_{final_stem}.mp4')
    burned = False
    if srt and _flag('ZYG_REMIXAI_BURN_SUBS', '1'):
        tmp = os.path.join(run.work, 'subtitled.mp4')
        ok_b, err_b = _burn_subs(scored, srt, tmp, geo)
        if ok_b:
            shutil.move(tmp, final)
            burned = True
            _log(pid, 'INFO', 'Subtitle Burn', 'subtitles burned in')
        else:
            _log(pid, 'WARNING', 'Subtitle Burn', f'burn failed ({err_b}) — delivering unburned')
    if not burned:
        shutil.move(scored, final)
    run.burned = burned
    # sibling WebVTT so the inspection card offers a Captions track
    if srt:
        _write_vtt(srt, os.path.join(run.out_dir, f'FINAL_{final_stem}.vtt'))
        shutil.copy2(srt, os.path.join(run.out_dir, 'subtitles.srt'))
    _check_stop(pid)


def stage_delivery(run):
    """Stage 14 — Delivery: the manifest, the description, the library row, the sweep.

    Called with ``FINAL_<slug>.mp4`` already sealed by the orchestrator. Measures the
    deliverable, writes ``manifest.json`` and the description, marks the source worked,
    adds the library entry and removes the work directory unless
    ``ZYG_REMIXAI_KEEP_WORK`` is set. Returns the result dict ``_finish`` is given.
    """
    pid, final = run.pid, run.final
    dur_final = _duration(final)
    run.manifest['output'].update(
        {
            'path': final,
            'duration_s': round(dur_final, 2),
            'title': run.title,
            'beats': len(run.parts),
            'subtitles_burned': run.burned,
            'model_family': _model_family(),
        }
    )
    run.manifest['ended'] = _now_iso()
    RI._save(os.path.join(run.out_dir, 'manifest.json'), run.manifest)
    _write_description(run.out_dir, run.title, run.newt, run.brief, run.manifest)
    RI.mark_seen(run.vid, state='worked', pipeline_id=pid, out=final)
    RI.library_add(
        {
            'pipeline_id': pid,
            'ts': time.time(),
            'source_id': run.vid,
            'source_title': run.cand.get('title', ''),
            'source_channel': run.cand.get('channel', ''),
            'title': run.title,
            'path': final,
            'duration_s': round(dur_final, 2),
            'geometry': run.geo['label'],
            'music': run.manifest['output'].get('music', {}),
        }
    )
    # working files go: the department keeps deliverables only
    if _flag('ZYG_REMIXAI_KEEP_WORK', '0'):
        _log(pid, 'INFO', 'Delivery', f'work dir kept at {run.work}')
    else:
        shutil.rmtree(run.work, ignore_errors=True)
    _log(pid, 'INFO', 'Delivery', f'delivered {os.path.basename(final)} · {dur_final:.1f}s · "{run.title}"')
    return {'path': final, 'title': run.title, 'duration_s': round(dur_final, 2)}
