# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SimpleTuner config support: captions, alpha stamping, validation."""

import os
import json
import logging
import shutil
import logging as _zyg_logging
from zyg_workflows.lora_trainer_service.job_state import (  # noqa: F401
    TrainingJob,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.lora_trainer_service')
logger = logging.getLogger('zyg_workflows.lora_trainer_service')


# ── SimpleTuner config writers ───────────────────────────────────────────────────
def _ensure_preview_captions(dataset_dir: str, trigger_token: str) -> None:
    """SimpleTuner textfile caption strategy requires .txt beside every .png."""
    # No 'character reference sheet' phrasing — it is a 3D-render/illustration
    # attractor and these captions feed training when previews sit in the
    # dataset dir (2026-07-09 audit).
    defaults = {
        'preview_sdxl_front.png': (
            f'photograph of {trigger_token} person, full body front view, '
            f'neutral studio background, natural skin texture'
        ),
        'preview_sdxl_face.png': (
            f'photograph of {trigger_token} person, face portrait front view, '
            f'neutral studio background, natural skin texture'
        ),
        'preview_flux_front.png': (
            f'photograph of {trigger_token} person, full body front view, '
            f'neutral studio background, natural skin texture'
        ),
        'preview_flux_face.png': (
            f'photograph of {trigger_token} person, face portrait front view, '
            f'neutral studio background, natural skin texture'
        ),
    }
    # 2026-07-31: previews are NOT training exemplars. This wrote
    # 'photograph of <trigger> person …' beside any preview_*.png sitting in the
    # training dir — a caption asserting the trigger token IS whatever is in that
    # PNG, with no verification the image was even rendered with this character's
    # own adapter. The preview writers save <slot>.png into whatever dataset_dir
    # they are handed, and the silent no-LoRA fallbacks (base-FLUX /
    # reference-driven) can put a stranger's portrait there — which then trains
    # into the adapter and bakes in the wrong identity permanently. Skip every
    # preview_* file: an authored caption is left untouched, and an uncaptioned
    # preview now makes SimpleTuner refuse the dataset (loud) instead of
    # poisoning the LoRA (silent). ZYG_LORA_CAPTION_PREVIEWS=1 restores it.
    _caption_previews = os.environ.get(
        'ZYG_LORA_CAPTION_PREVIEWS',
        '0',
    ).strip().lower() in ('1', 'true', 'yes', 'on')

    for png_name, caption in defaults.items():
        png_path = os.path.join(dataset_dir, png_name)
        if not os.path.isfile(png_path):
            continue
        if not _caption_previews:
            logger.warning(
                f'[LoraTrainer] preview image in the training dataset dir — NOT '
                f'auto-captioning it as a training exemplar: {png_path} '
                f'(move previews out of {dataset_dir} — an uncaptioned image '
                f'will be rejected by SimpleTuner)',
            )
            continue
        txt_path = os.path.splitext(png_path)[0] + '.txt'
        write = not os.path.isfile(txt_path)
        if not write:
            # Also replace the OLD auto-generated caption ('character reference
            # sheet' is a 3D-render attractor) — but never touch authored text.
            try:
                with open(txt_path, encoding='utf-8') as fh:
                    _existing = fh.read().strip()
                write = _existing.endswith('character reference sheet')
            except OSError:
                write = False
        if write:
            with open(txt_path, 'w', encoding='utf-8') as fh:
                fh.write(caption.strip() + '\n')
            logger.info(f'[LoraTrainer] wrote caption: {txt_path}')


def _read_trained_scale(weights_dir: str) -> tuple[int, float] | None:
    """(rank, alpha) as actually trained, from the run's own SimpleTuner config.

    Read from the artifact rather than from the env, so a later re-stamp always
    reflects the run that produced the file even if ZYG_LORA_RANK has moved on.
    """
    p = os.path.join(weights_dir, 'simpletuner_config.json')
    try:
        with open(p, encoding='utf-8') as fh:
            cfg = json.load(fh)
        rank = int(cfg['lora_rank'])
        alpha = float(cfg['lora_alpha'])
    except Exception:
        return None
    return (rank, alpha) if rank > 0 and alpha > 0 else None


def stamp_lora_alpha(lora_path: str) -> bool:
    """Write the trained alpha INTO an exported LoRA. Returns True if stamped.

    2026-08-10. SimpleTuner exports only lora_A/lora_B — no `.alpha` entries, no
    adapter_config.json, safetensors metadata just {'format': 'pt'}. Alpha is
    therefore UNRECOVERABLE from the file, and ComfyUI
    (comfy/weight_adapter/lora.py: `scale = alpha/rank if alpha is not None else
    1.0`) silently falls back to 1.0 — applying every adapter at 1/(alpha/rank)
    times its trained strength. At the standing rank 64 / alpha 32 that is 2x.

    Measured on the Nicols qwen LoRA through the real production workflow: the
    plain file at strength 1.0 renders smeared garbage, the stamped file at the
    same strength renders the character. Qwen is far less tolerant of
    over-strength than FLUX, which is why this surfaced there first.

    Idempotent, atomic, and a no-op when the run's rank/alpha cannot be read —
    it never guesses.
    """
    try:
        import torch
        from safetensors import safe_open
        from safetensors.torch import save_file
    except Exception as exc:
        logger.warning(f'[LoraTrainer] alpha stamp unavailable: {exc}')
        return False

    if not lora_path or not os.path.isfile(lora_path):
        return False
    ra = _read_trained_scale(os.path.dirname(lora_path))
    if not ra:
        logger.warning(f'[LoraTrainer] no rank/alpha for {lora_path} — left unstamped')
        return False
    rank, alpha = ra

    with safe_open(lora_path, 'pt') as fh:
        keys = list(fh.keys())
        tensors = {k: fh.get_tensor(k) for k in keys}
        meta = dict(fh.metadata() or {})

    # Every "down" key form ComfyUI resolves (comfy/weight_adapter/lora.py):
    # PEFT `.lora_A.weight`, diffusers `.lora.down.weight`, kohya
    # `.lora_down.weight`. One export can MIX them — SimpleTuner's flux2 writer
    # renames the double-block attention keys to the diffusers form and leaves
    # the single-block ones in PEFT form. The first version of this stamper
    # handled only `.lora_A.weight` AND treated "any .alpha present" as
    # "already stamped", so on a mixed file it stamped half the modules and
    # then refused to touch the rest: those modules loaded at 2x forever, and
    # the half-stamped file looked done to every later check.
    _DOWN = ('.lora_A.weight', '.lora.down.weight', '.lora_down.weight')
    have_alpha = {k[: -len('.alpha')] for k in keys if k.endswith('.alpha')}
    n = 0
    n_already = 0
    for k in keys:
        for suf in _DOWN:
            if k.endswith(suf):
                prefix = k[: -len(suf)]
                if prefix in have_alpha:
                    n_already += 1
                else:
                    tensors[f'{prefix}.alpha'] = torch.tensor(alpha, dtype=torch.float32)
                    have_alpha.add(prefix)
                    n += 1
                break
    if not n:
        return n_already > 0  # fully stamped already, or nothing to stamp

    meta.update({'lora_rank': str(rank), 'lora_alpha': str(alpha), 'trained_scale': str(alpha / rank)})
    tmp = f'{lora_path}.stamping.{os.getpid()}'
    save_file(tensors, tmp, metadata=meta)
    os.replace(tmp, lora_path)
    logger.info(
        f'[LoraTrainer] stamped alpha={alpha} rank={rank} '
        f'(scale {alpha / rank:g}) into {n} modules of {lora_path}'
        + (f' ({n_already} were already stamped)' if n_already else '')
    )
    return True


def _validation_prompt(job: 'TrainingJob', family: str) -> str:
    """The fixed prompt SimpleTuner renders its validation samples from.

    Precedence is CALLER FIRST. The train_mode branch below only ever knew two
    subjects — a human identity and a human body template — so a creature or an
    animal was validated as "<trigger> person, head and shoulders portrait ...
    natural skin texture with visible pores" and its frames came back as PEOPLE
    (2026-08-26: every creature LoRA on disk has such frames). Training weights
    were never affected — a validation prompt only renders a sample — but the
    sample is the only thing a human looks at, so it has to depict the subject.
    A caller that knows the subject is not a person passes job.validation_prompt
    and this branch is skipped entirely.

    Kept as one function rather than four inline ternaries so a future subject
    cannot be fixed for flux and silently missed for klein — which is exactly how
    the creature case went unnoticed.
    """
    explicit = (getattr(job, 'validation_prompt', '') or '').strip()
    if explicit:
        return explicit
    body = getattr(job, 'train_mode', 'identity') == 'body'
    # SDXL's CLIP encoder gets the terser reference-sheet phrasing; the T5/Qwen
    # families get the photographic one. Both are byte-identical to what the
    # four inline copies produced before this refactor.
    if family == 'sdxl':
        return (
            f'{job.trigger_token} {"body type" if body else "character"}, '
            f'full body front view, white studio background, '
            f'character reference sheet'
        )
    if body:
        # A body-template LoRA is trained with faces masked out of the loss and
        # with close-ups excluded, so validating it on a "head and shoulders
        # portrait" would render the one framing it was never taught — and with
        # ZYG_ST_VALIDATION_INTERVAL=0 that is the run's only render.
        return (
            f'photograph of {job.trigger_token} body type, full body, front '
            f'view, neutral gray studio background, natural skin texture'
        )
    return (
        f'photograph of {job.trigger_token} person, head and shoulders '
        f'portrait, front view, neutral gray studio background, natural '
        f'skin texture with visible pores, unretouched'
    )


def _validation_interval(steps: int) -> int:
    """Steps between validation renders.

    2026-07-18 made this end-of-run-only: mid-run renders cost minutes and
    nothing consumed them. 2026-08-10 reversed that. A qwen run went 8840 steps
    / 10 hours with its ONLY render at the end, and that render was the first
    evidence anything was wrong — there was no step-500 image that would have
    shown it in twelve minutes. Roughly six renders per run is well under 2% of
    a long run's wall clock, and it is the only in-flight signal there is.

    Unset -> automatic cadence. Explicit 0 -> end-of-run only (the old
    behaviour, kept as an escape hatch). Positive int -> exactly that.
    """
    raw = os.environ.get('ZYG_ST_VALIDATION_INTERVAL')
    if raw is not None and raw.strip():
        n = int(raw)
        return n if n > 0 else steps
    return min(1500, max(250, steps // 6))


def _read_config_value(config_dir: str, key: str) -> str:
    """One value out of an existing SimpleTuner config.json, '' when absent."""
    try:
        with open(os.path.join(config_dir, 'config.json'), encoding='utf-8') as fh:
            return str(json.load(fh).get(key) or '')
    except Exception:
        return ''


def _drop_stale_benchmarks(config_dir: str, _prev_unused: str = '') -> None:
    """Delete the cached base-model benchmark unless it was made from THIS prompt.

    SimpleTuner renders `<output>/benchmarks/base_model/*.png` ONCE and reuses it
    forever as the left-hand panel of every validation strip. Nothing keys that
    cache on the prompt that produced it, so a prompt change leaves every future
    strip comparing the new subject against the OLD prompt's baseline.

    Seen 2026-08-26 on the Pufferball: the creature-validation fix landed and the
    step-250 strip came back as "base model: a man in a black t-shirt | step 250:
    the creature". The training was correct; only the baseline was stale — exactly
    the kind of artifact an operator reads as a real result, and it did confuse one.

    STATE, NOT TRANSITION. The first version of this compared against the previous
    run's config and dropped on a change. That has a hole with a very long tail: the
    prompt that went stale changed BEFORE tracking existed, so run N+1 sees
    prompt==prompt, keeps the cache, and the wrong baseline survives forever. So the
    benchmark now carries a `.validation_prompt` sidecar naming the prompt it was
    rendered from, and anything that does not match — including a legacy benchmark
    with no sidecar at all — is dropped and regenerated. Self-healing: one extra
    pair of renders, once, on the first run after this landed."""
    new = _read_config_value(config_dir, '--validation_prompt')
    out = _read_config_value(config_dir, '--output_dir')
    if not new or not out:
        return
    bench = os.path.join(out, 'benchmarks')
    stamp = os.path.join(bench, '.validation_prompt')
    if os.path.isdir(bench):
        try:
            with open(stamp, encoding='utf-8') as fh:
                if fh.read() == new:
                    return  # baseline matches; keep the cache
        except OSError as _exc:
            _zyg_log.debug('benchmark stamp %s unreadable, re-rendering the baseline: %s', stamp, _exc)
        try:
            shutil.rmtree(bench)
            logger.info(
                '[LoraTrainer] base-model benchmark did not match the current validation '
                f'prompt — dropped {bench} so the comparison strip is rendered from it',
            )
        except OSError as exc:
            logger.warning(f'[LoraTrainer] could not drop stale benchmark {bench}: {exc}')
            return
        # Same staleness, same cause: validation_images/ are rendered from the same
        # prompt, and a run only overwrites the steps it actually reaches. The
        # Pufferball retrain left step_0 from the PREVIOUS run on disk, so the card
        # showed 8 fresh creature frames next to 2 stale human ones — a mixed set
        # reads as a contradiction rather than as leftovers.
        vdir = os.path.join(out, 'validation_images')
        if os.path.isdir(vdir):
            n = 0
            for f in os.listdir(vdir):
                if f.endswith(('.png', '.jpg', '.jpeg')):
                    try:
                        os.remove(os.path.join(vdir, f))
                        n += 1
                    except OSError as _exc:
                        _zyg_log.debug('stale validation frame %s removal skipped: %s', f, _exc)
            if n:
                logger.info(
                    f'[LoraTrainer] dropped {n} validation frame(s) rendered from the '
                    'previous prompt so this run does not mix two subjects',
                )
    try:
        os.makedirs(bench, exist_ok=True)
        with open(stamp, 'w', encoding='utf-8') as fh:
            fh.write(new)
    except OSError as exc:
        logger.warning(f'[LoraTrainer] could not stamp benchmark dir {bench}: {exc}')
