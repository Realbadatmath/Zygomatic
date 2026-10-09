# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Video Studio: the render engine — one ComfyUI submission, one chained clip,
the ComfyUI enable shim and the render worker thread start_render() spawns."""

import json
import math
import os
import shutil
import time

from zyg_workflows import wan_video_service as _wan

from .. import _comfy, _OUT_ROOT, _zyg_log
from ..ffmpeg_finish import _color_match_filter, _detect, _motion_series, _post_process
from ..options import PATHWAYS
from ..prompts import compose_link_prompts, compose_prompt
from ..render_jobs import _job_log, _job_set, _RENDER_GATE, job
from ..spec import nondefault

from .graph import (
    _node,
    _augment_graph,
    _graph_overrides,
)


def _submit(
    p: dict,
    workflow: dict,
    src_path: str,
    prompt: str,
    negative: str,
    idx: int,
    seed: int,
    steps: int,
    guidance: float,
    shift: float,
    frames: int,
    out_path: str,
    log,
    end_path: str = '',
    graph_out: str = '',
) -> bool:
    """One ComfyUI submission with the full override set.

    A local reimplementation of wan_video_service._submit_wan_clip: that helper
    hard-codes the module-level width/height/LoRA/attention env and exposes only
    5 knobs, which is exactly the surface this console exists to replace. The
    node ids, the LoRA chaining rule (2.1 LoRAs onto the LOW expert) and the
    attestation call are kept identical to it deliberately."""
    if _comfy is None:
        log('ComfyUI client unavailable')
        return False
    try:
        import copy as _cp

        src_name = _comfy.stage_input_image(src_path)
        end_name = _comfy.stage_input_image(end_path) if end_path else ''
        is22 = '31' in workflow
        # Always a deep copy now: the optional-args nodes mutate the graph on
        # far more paths than the LoRA chain did, and a template mutated in
        # place would leak one render's dials into the next.
        wf = _cp.deepcopy(workflow)
        if p['lora']:
            wf['6'] = _node(
                'WanVideoLoraSelect', {'lora': p['lora'], 'strength': float(p['lora_strength']), 'low_mem_load': False}
            )
            wf['7' if is22 else '1']['inputs']['lora'] = ['6', 0]
        if is22 and p['lightning']:
            wf['8'] = _node(
                'WanVideoLoraSelect', {'lora': _wan._LIGHTNING_HIGH_LORA, 'strength': 1.0, 'low_mem_load': False}
            )
            wf['1']['inputs']['lora'] = ['8', 0]
            low = {'lora': _wan._LIGHTNING_LOW_LORA, 'strength': 1.0, 'low_mem_load': False}
            if p['lora']:
                low['prev_lora'] = ['6', 0]
            wf['9'] = _node('WanVideoLoraSelect', low)
            wf['7']['inputs']['lora'] = ['9', 0]

        extra = _augment_graph(p, wf, is22, src_name, end_name, negative, log)
        ov = _graph_overrides(p, wf, src_name, prompt, negative, idx, seed, steps, guidance, shift, frames)
        for nid, patch in extra.items():
            ov.setdefault(nid, {}).update(patch)

        if p['debug_trace'] or p['dry_run']:
            log('graph nodes: ' + ','.join(sorted(wf, key=lambda k: int(k))))
            log('graph overrides: ' + json.dumps(ov, sort_keys=True)[:4000])
        if graph_out:
            # The artefact that PROVES which node a dial reached. The log only
            # records what this process meant to send.
            try:
                with open(graph_out, 'w') as fh:
                    json.dump({'workflow': wf, 'overrides': ov}, fh, indent=1, sort_keys=True)
                log(f'graph written: {os.path.basename(graph_out)}')
            except OSError as exc:
                log(f'graph dump failed: {exc}')
        if p['dry_run']:
            log('dry run — nothing submitted')
            return False

        try:
            from zyg_workflows import lora_attest as _attest

            _attest.attest_submit(wf, overrides=ov, tag=f'vst_clip_{idx}', log_fn=log)
        except Exception as _exc:
            _zyg_log.warning('LoRA attestation failed for sub-clip %s, the render is not attested: %s', idx, _exc)

        outputs = _comfy.submit(wf, overrides=ov, timeout_s=int(os.environ.get('ZYG_WAN_TIMEOUT_S', '900')))
        if not outputs:
            log(f'sub-clip {idx}: ComfyUI returned no output')
            return False
        shutil.copy2(outputs[0], out_path)
        return True
    except Exception as exc:  # noqa: BLE001
        log(f'sub-clip {idx}: ComfyUI submit failed: {exc}')
        return False


def _render_one(
    jid: str,
    p: dict,
    img_path: str,
    out_dir: str,
    tag: str,
    base_seed: int,
    prompt: str,
    negative: str,
    workflow: dict,
    n_chained: int,
    frames: int,
    steps: int,
    guidance: float,
    shift: float,
    log,
    end_img: str = '',
    link_prompts: list = None,
) -> str:
    """One complete clip: n_chained sub-clips, stitched. Returns the path, or ''.
    Post-processing is NOT applied here — the motion gate measures the raw
    render, so that a grade or a fade can never be what makes a frozen clip
    look like it passed."""
    sub_paths = []
    current_src = img_path
    for i in range(n_chained):
        sub_out = os.path.join(out_dir, f'{tag}_sub{i:02d}.mp4')
        seed = base_seed if p['seed_mode'] == 'fixed' else base_seed + i
        # An end frame is the destination of the WHOLE clip, so on a chain it
        # conditions the last link only — putting it on every sub-clip would
        # ask each one to arrive at the ending and then leave again.
        sub_end = end_img if (end_img and i == n_chained - 1) else ''
        graph_out = os.path.join(out_dir, f'{tag}_sub{i:02d}.graph.json') if p['save_graph'] else ''
        pos, neg = link_prompts[i] if link_prompts else (prompt, negative)
        log(f'{tag}: link {i + 1}/{n_chained} positive: {pos}')
        log(f'{tag}: link {i + 1}/{n_chained} negative: {neg or "(graph template default)"}')
        if not _submit(
            p,
            workflow,
            current_src,
            pos,
            neg,
            i,
            seed,
            steps,
            guidance,
            shift,
            frames,
            sub_out,
            log,
            end_path=sub_end,
            graph_out=graph_out,
        ):
            # A dry run submits nothing, so every link would otherwise stop at
            # the first one — and the point of a dry run is to read the prompt
            # of EVERY link. current_src stays put (there is no last frame to
            # hand on) and the empty return after the loop still raises the
            # worker's 'dry run complete'.
            if p['dry_run']:
                log(f'{tag}: link {i + 1}/{n_chained} dry run — nothing submitted')
                continue
            return ''
        sub_paths.append(sub_out)
        last_frame = sub_out + '.last.png'
        if _wan._extract_last_frame(sub_out, last_frame, log):
            current_src = last_frame
        _job_set(jid, progress=f'{i + 1}/{n_chained}')
        log(f'{tag}: sub-clip {i + 1}/{n_chained} done')

    if not sub_paths:
        return ''
    final_out = os.path.join(out_dir, f'{tag}.mp4')
    if len(sub_paths) == 1:
        shutil.copy2(sub_paths[0], final_out)
    elif not _wan._stitch_clips(sub_paths, final_out, log):
        shutil.copy2(sub_paths[0], final_out)
        log(f'{tag}: stitch failed — first sub-clip kept')
    if not p['keep_subclips']:
        for sp in sub_paths:
            for f in (sp, sp + '.last.png'):
                try:
                    os.remove(f)
                except OSError as _exc:
                    _zyg_log.debug('sub-clip cleanup skipped: %s', _exc)
    return final_out


def _enable_comfy() -> None:
    """Make this render thread see the same ComfyUI the dashboard sees.

    ``_comfy_client.is_enabled()`` reads ZYG_USE_COMFYUI, which nothing sets in
    the shell and which kanban-server's unit does not set either — so this tab's
    Render has been reporting "ComfyUI is not reachable" against a perfectly
    healthy :8188 server. The GUI process gets the flag from
    ``vram_manager._ensure_comfy_offload_env``; importing that here would drag in
    crewai_web_gui (circular, ten thousand lines of Flask), so its whole body —
    two setdefaults gated on the server answering — is repeated, exactly as
    kids_video_service._enable_comfy() already does for the same reason."""
    try:
        if _comfy is not None and _comfy.server_reachable():
            os.environ.setdefault('ZYG_COMFY_PRIMARY', '1')
            os.environ.setdefault('ZYG_USE_COMFYUI', '1')
    except Exception as _exc:  # noqa: BLE001 — best effort only
        _zyg_log.debug('comfy auto-enable skipped: %s', _exc)


def _render_worker(jid: str, img_path: str, char_name: str):
    _job_set(jid, state='running')
    log = lambda msg: _job_log(jid, msg)  # noqa: E731
    out_dir = os.path.join(_OUT_ROOT, jid)
    with _RENDER_GATE:
        try:
            p = job(jid)['params']
            _enable_comfy()
            if not p['dry_run']:
                if _comfy is None or not _comfy.is_enabled() or not _comfy.server_reachable():
                    raise RuntimeError('ComfyUI is not reachable — start the ComfyUI server before rendering')
            os.makedirs(out_dir, exist_ok=True)

            wf_name = PATHWAYS.get(p['pathway'], ('wan_i2v', None))[0]
            workflow = _comfy.load_workflow(wf_name) if _comfy else {}
            is22 = '31' in workflow
            prompt, negative = compose_prompt(p, char_name)

            steps, guidance, shift = int(p['steps']), float(p['guidance']), float(p['flow_shift'])
            if is22 and p['lightning']:
                steps, guidance, shift = 4, 1.0, 5.0
                log('Lightning 4-step distill active — steps/cfg/shift overridden to 4 / 1.0 / 5.0')
            elif p['lightning'] and not is22:
                log('Lightning requested but the pathway is Wan2.1 — ignored (the distill LoRA pair is A14B-only)')

            frames = int(p['frames'])
            # Duration is frames / the ASSEMBLY rate, so lowering Render fps
            # lengthens each sub-clip and needs fewer of them for the same
            # target duration. Reading _CLIP_FPS here instead would silently
            # over-render every clip below 24fps.
            sec_per_sub = frames / max(1.0, float(p['fps']))
            n_chained = max(1, int(math.ceil(float(p['duration_s']) / sec_per_sub)))
            if p['context'] and n_chained > 1:
                log(
                    'context windows are on AND the duration needs '
                    f'{n_chained} chained sub-clips — the windows run inside '
                    'each sub-clip, they do not remove the hand-off between them'
                )
            if not is22 and (int(p['sampler_start_step']) or int(p['sampler_end_step']) != -1):
                log('start/end step set on a Wan2.1 pathway — applied')
            elif is22 and (int(p['sampler_start_step']) or int(p['sampler_end_step']) != -1):
                log('start/end step IGNORED on Wan2.2 — the expert boundary owns them on the dual-expert graph')
            links = compose_link_prompts(p, char_name, n_chained)
            if str(p['link_prompts'] or '').strip():
                log(f'link prompts: {n_chained} link(s) from Prompt per link')
            base_seed = int(p['seed']) or (int(time.time() * 1000) % 999999)

            end_img = job(jid).get('end_img', '')
            if p['end_frame'] != 'off' and not end_img:
                log(
                    'End frame is set but no end frame was extracted — the render is running without FLF2V conditioning'
                )

            log(
                f'pathway={p["pathway"]} wf={wf_name} res={p["resolution"]} '
                f'sched={p["scheduler"]} lora={p["lora"] or "none"}'
            )
            _accel = [
                n
                for n, on in (
                    (f'cache={p["cache_mode"]}', p['cache_mode'] != 'off'),
                    ('slg', p['slg']),
                    ('enhance-a-video', p['feta']),
                    ('nag', p['nag']),
                    ('context', p['context']),
                    (f'freeinit x{int(p["freeinit_iters"])}', p['freeinit']),
                    (f'block_swap={int(p["block_swap"])}', int(p['block_swap']) > 0),
                    (f'compile={p["torch_compile"]}', p['torch_compile'] != 'off'),
                    ('radial-attn', p['radial_attn']),
                    (f'end_frame={p["end_frame"]}', p['end_frame'] != 'off'),
                )
                if on
            ]
            log('extras: ' + (', '.join(_accel) if _accel else 'none'))
            log(f'positive: {prompt}')
            log(f'negative: {negative or "(graph template default)"}')
            log(
                f'{n_chained} sub-clip(s) x {frames}f (~{sec_per_sub:.1f}s each), '
                f'seed={base_seed} ({p["seed_mode"]}), steps={steps} cfg={guidance} '
                f'shift={shift}'
            )

            urls = []
            for v in range(int(p['variants'])):
                tag = 'clip' if int(p['variants']) == 1 else f'clip_v{v + 1}'
                v_seed = base_seed + v * 1000
                attempt, made = 0, ''
                while attempt <= int(p['retries']):
                    if attempt:
                        v_seed = (v_seed + 7919) % 999999
                        log(f'{tag}: retry {attempt} at seed {v_seed}')
                    made = _render_one(
                        jid,
                        p,
                        img_path,
                        out_dir,
                        tag,
                        v_seed,
                        prompt,
                        negative,
                        workflow,
                        n_chained,
                        frames,
                        steps,
                        guidance,
                        shift,
                        log,
                        end_img=end_img,
                        link_prompts=links,
                    )
                    if p['dry_run']:
                        break  # a dry run "fails" by design — never retry it
                    if made and p['motion_gate']:
                        score = _wan._compute_motion_score(made, log)
                        if score < (1.0 - float(p['motion_thresh'])):
                            log(
                                f'{tag}: frozen-clip gate REJECTED (motion {score:.2f} '
                                f'< {1.0 - float(p["motion_thresh"]):.2f})'
                            )
                            made = ''
                        else:
                            log(f'{tag}: frozen-clip gate passed (motion {score:.2f})')
                    # The extra gates measure the RAW render for the same reason
                    # the motion gate does — a fade to black would otherwise
                    # manufacture exactly the black run the black gate hunts for.
                    if made and p['black_gate']:
                        hits = _detect(made, 'blackdetect=d=0.2:pix_th=0.06', log)
                        if hits:
                            log(f'{tag}: black-frame gate REJECTED — {hits[0][:160]}')
                            made = ''
                        else:
                            log(f'{tag}: black-frame gate passed')
                    if made and p['freeze_gate']:
                        hits = _detect(made, 'freezedetect=n=0.003:d=0.5', log)
                        if hits:
                            log(f'{tag}: duplicate-frame gate REJECTED — {hits[0][:160]}')
                            made = ''
                        else:
                            log(f'{tag}: duplicate-frame gate passed')
                    if made and p['scene_report']:
                        hits = _detect(made, 'scdet=threshold=12', log)
                        log(
                            f'{tag}: scene-cut report — '
                            + (f'{len(hits)} cut(s) inside the clip' if hits else 'no cuts detected')
                        )
                    if made:
                        break
                    attempt += 1
                if not made:
                    if p['dry_run']:
                        raise RuntimeError(
                            'dry run complete — prompt and graph are in the log above, nothing was rendered'
                        )
                    raise RuntimeError(f'{tag} failed after {attempt} attempt(s) — see the log above')

                if p['motion_plot']:
                    _motion_series(made, log)
                pre = _color_match_filter(img_path, made, log) if p['color_match'] else ''
                _post_process(made, p, log, pre_filter=pre, run_id=jid)
                if p['save_params']:
                    try:
                        with open(os.path.splitext(made)[0] + '.settings.json', 'w') as fh:
                            json.dump(
                                {
                                    'prompt': prompt,
                                    'negative': negative,
                                    'seed': v_seed,
                                    'pathway': p['pathway'],
                                    'changed': nondefault(p),
                                },
                                fh,
                                indent=1,
                                sort_keys=True,
                            )
                        log(f'{tag}: settings written')
                    except OSError as exc:
                        log(f'{tag}: settings dump failed: {exc}')
                urls.append(f'/inspect/media?path=out/video_studio/{jid}/{os.path.basename(made)}')
                _job_set(jid, urls=list(urls), url=urls[0])
                log(f'{tag}: finished')

            _job_set(jid, state='done', url=urls[0], urls=urls, finished=time.time())
            log('done')
        except Exception as e:  # noqa: BLE001 — any failure ends the job, never the server
            log(f'error: {e}')
            _job_set(jid, state='error', error=str(e), finished=time.time())
