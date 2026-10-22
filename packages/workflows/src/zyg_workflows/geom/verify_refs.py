# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""verify_refs.py — every reference image gets LOOKED AT before it counts (2026-08-04).

RUN:
    python3 -m zyg_workflows.geom.verify_refs [--asset ID] [--redo] [--no-siglip]

THE RULE THIS ENFORCES: if a prompt mentions an object, person or environment, reference
images for it must be downloaded AND INSPECTED to confirm they show what we are looking
for. Licence checking already existed; this adds the half that was missing, and it was
missing for a measured reason — two failures from this very week:
  * the Met Museum "Axe Head" images cited as the hurlbat's profile source were, on
    actual inspection, neolithic stone celts — beautifully licensed, useless;
  * the Commons full-text sweep for "hurlbat" returned book scans and an EU regulation
    that merely CONTAIN the word.
Both sailed through licence verification because licence verification never looks at
pixels. This module looks at pixels.

TWO STAGES, CHEAP THEN SMART:
  SigLIP 2   (google/siglip2-so400m, Apache-2.0 — verified from the model card) scores
             image<->text similarity in milliseconds. It CANNOT veto on its own — it is
             recorded and used to rank — because a threshold that never sees the image
             semantics would re-create exactly the blind spot being closed. Optional:
             skipped cleanly when transformers/weights are unavailable.
  local VLM  the same Qwen3 judge the pipeline already trusts, resident tier, persistent
             server, one closed question per image: does this image clearly show
             <subject>? THE CROP RULE does not apply here — the whole point is judging
             the whole reference.

The verdict is written INTO the ref's provenance entry in the manifest:
    verified: {shows_subject: bool, subject, answer, siglip, by, date}
and manifest._check refuses unverified refs on kind='ref'/'character' from now on
(ZYG_REQUIRE_VERIFIED_REFS=1 by default). A ref that fails stays in the file with
shows_subject=false — visible, counted, and excluded — rather than silently deleted.

Judge unavailable => refs stay unverified and the audit says so loudly. This module never
fabricates a verdict; "not inspected" must remain distinguishable from "inspected: yes".
"""

import os
import time
import logging as _zyg_logging


# Hugging Face revision for every from_pretrained/download in this module. 'main' is the
# floating default these call sites used implicitly; $ZYG_HF_REVISION pins a commit instead.
_HF_REVISION = os.environ.get('ZYG_HF_REVISION', '').strip() or 'main'

_zyg_log = _zyg_logging.getLogger(__name__)


# What each existing asset's references are SUPPOSED to show. New ingests should pass
# `subject=` explicitly; this table covers the corpus that predates the rule.
SUBJECTS = {
    'ref_oak_bark': 'the bark of a tree, close enough to see texture',
    'ref_oak_leaf': 'one or more oak (or similar broadleaf) leaves',
    'ref_forest_floor': 'a forest floor or woodland ground with leaves/vegetation',
    'ref_hatchet': 'an axe or hatchet (tool photo, historical photo, or drawing of one)',
    'ref_bark_wounds': 'a cut, wound, scar or tapping panel in the bark of a living tree',
    'ref_hurlbat': 'a medieval axe, axe head, or throwing-axe (museum object or drawing)',
    'bark_oak': 'tree bark surface texture',
    'ground_forest': 'forest ground / soil surface texture',
    'wood_sapwood_fresh': 'raw pale wood grain surface',
    'wood_scar_weathered': 'weathered cut wood or bark surface',
    'env_forest_overcast': 'a forest environment panorama',
    'char_abel': 'a boy around 12 with light brown hair (painterly or photoreal portrait)',
    'char_cornelis': 'an adult man (painterly or photoreal portrait or figure)',
}

_SIGLIP = None


def _siglip_score(image_path, text):
    """SigLIP2 image-text probability, or None when unavailable. Lazy, cached, silent."""
    global _SIGLIP
    if _SIGLIP is False:
        return None
    try:
        if _SIGLIP is None:
            import torch
            from transformers import AutoModel, AutoProcessor

            name = 'google/siglip2-so400m-patch16-384'
            proc = AutoProcessor.from_pretrained(name, revision=_HF_REVISION)
            model = AutoModel.from_pretrained(name, torch_dtype=torch.float16, device_map='cuda', revision=_HF_REVISION)
            _SIGLIP = (proc, model, torch)
        proc, model, torch = _SIGLIP
        from PIL import Image

        img = Image.open(image_path).convert('RGB')
        inputs = proc(text=[text], images=[img], return_tensors='pt', padding='max_length', max_length=64)
        inputs = {k: (v.to('cuda') if hasattr(v, 'to') else v) for k, v in inputs.items()}
        with torch.no_grad():
            out = model(**inputs)
        return float(torch.sigmoid(out.logits_per_image)[0, 0])
    except Exception:
        _SIGLIP = False
        return None


def _vlm_verify(image_path, subject, log):
    """One closed question to the local judge. Returns (bool|None, raw_answer)."""
    try:
        from zyg_workflows import vlm_inspector as V
    except Exception as e:
        log('judge unimportable: %s' % e)
        return None, 'judge_unavailable'
    if not V.available() or not V._enabled():
        return None, 'judge_unavailable'
    tier = 'resident'
    q = [
        {
            'id': 'shows_subject',
            'question': (
                'Look at the image. Does it clearly show %s? Answer yes only if '
                'that is a prominent, recognisable subject of the image — not a '
                'background detail, not a page of text about it.' % subject
            ),
            'expected': 'yes',
            'severity': 'critical',
            'grounding': False,
        }
    ]
    res = V._run_worker(V.model_for(tier), [os.path.abspath(image_path)], q, tier, log)
    if not res:
        return None, 'worker_failed'
    verd = res.get('verdicts') or res.get('answers') or []
    for v in verd:
        if v.get('id') == 'shows_subject' or len(verd) == 1:
            ans = str(v.get('answer', '')).strip().lower()
            return (ans.startswith('y'), ans)
    return None, 'no_verdict'


def verify_manifest(asset_id=None, redo=False, use_siglip=True, log=print):
    from . import manifest

    man = manifest.Manifest()
    changed, results = 0, []
    for a in man.list():
        if asset_id and a['id'] != asset_id:
            continue
        subject = SUBJECTS.get(a['id'])
        if not subject:
            # derive from notes as a last resort; better an explicit table miss than a
            # silently wrong subject
            results.append((a['id'], 'skip', 'no subject registered'))
            continue
        for r in a.get('refs') or []:
            if r.get('verified') and not redo:
                continue
            p = r.get('file')
            if not p or not os.path.exists(p):
                r['verified'] = {
                    'shows_subject': False,
                    'subject': subject,
                    'answer': 'file_missing',
                    'by': 'verify_refs',
                    'date': time.strftime('%Y-%m-%d'),
                }
                changed += 1
                continue
            sig = _siglip_score(p, 'a photo of %s' % subject) if use_siglip else None
            ok, ans = _vlm_verify(p, subject, log)
            if ok is None:
                results.append((a['id'], 'UNVERIFIED', os.path.basename(p) + ' ' + ans))
                continue
            r['verified'] = {
                'shows_subject': bool(ok),
                'subject': subject,
                'answer': ans,
                'siglip': None if sig is None else round(sig, 4),
                'by': 'qwen3-vl-resident+siglip2' if sig is not None else 'qwen3-vl-resident',
                'date': time.strftime('%Y-%m-%d'),
            }
            changed += 1
            results.append(
                (
                    a['id'],
                    'PASS' if ok else 'FAIL',
                    '%s siglip=%s' % (os.path.basename(p)[:40], 'n/a' if sig is None else '%.3f' % sig),
                )
            )
    if changed:
        man.save()
    return changed, results


if __name__ == '__main__':  # the CLI lives in verify_refs_cli
    from zyg_workflows.geom.verify_refs_cli import main as _cli_main

    raise SystemExit(_cli_main())
