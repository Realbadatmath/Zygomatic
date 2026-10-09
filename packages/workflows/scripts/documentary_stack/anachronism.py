# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The 2026-08-25 anachronism work: period noun rewrite, the era gate offline and
wired, thumbnails and the shot-grammar family."""

import os
import tempfile

from .core import (  # noqa: F401  shared harness state, used by the moved sections
    check,
    paths,
)


# ── 2026-08-25: anachronism work ──────────────────────────────────────────
def test_period_noun_rewrite():
    """The deterministic backstop behind NO BARE NOUNS, in isolation."""
    from zyg_dashboard import crewai_web_gui  # noqa: F401  — bp_benchmark circular import
    from zyg_workflows import pipeline_scholarly as ps

    era = {
        'is_historical': True,
        'period_label': 'Medieval Europe, 1347–1351',
        'period_start': 1347,
        'period_end': 1351,
    }
    o, ch = ps._period_noun_rewrite(
        'A fishing vessel rides at anchor while a man in a shirt hauls a net, his shoes wet', era
    )
    check('bare "vessel" becomes the period boat', 'wooden sailing cog' in o, o)
    check('bare "shirt" and "shoes" get their period form', 'linen chemise' in o and 'leather turnshoes' in o, o)
    check('changes are reported', len(ch) == 3, str(ch))
    o2, ch2 = ps._period_noun_rewrite(o, era)
    check('rewrite is idempotent', ch2 == [] and o2 == o, str(ch2))
    o3, _ = ps._period_noun_rewrite('a single-masted wooden cog, sailors in leather turnshoes', era)
    check('described nouns are left alone', 'cog, sailors in leather turnshoes' in o3, o3)
    o4, ch4 = ps._period_noun_rewrite('a boy in a coat and trousers watches, a bracelet on her wrist', era)
    check('a descriptor qualifies only the noun it is attached to (trousers still bare)', 'wool hose' in o4, o4)
    check('a watch/bracelet is DROPPED, not period-ised', 'bracelet' not in o4 and 'wrist' not in o4, o4)
    check('the verb "watches" survives the watch rule', 'watches' in o4, o4)
    o5, ch5 = ps._period_noun_rewrite('a ship and a shoe', {'is_historical': True, 'period_end': -44})
    check('antiquity gets a galley and a sandal, not a cog', 'galley' in o5 and 'sandal' in o5, o5)
    check(
        'modern episodes are untouched', ps._period_noun_rewrite('a ship and a shoe', {'is_historical': False})[1] == []
    )
    h, added = ps._period_hair_backstop('two merchants argue across a table', era)
    check('people with no hair described get the period hair line', added and 'coif' in h, h)
    h2, added2 = ps._period_hair_backstop('a tonsured monk at a table', era)
    check('described heads get nothing', not added2)
    g, gch = ps._render_safety_rewrite(
        'The emaciated boy, ribs showing through skin, an open wound at the neck, a bubo swelling', 1
    )
    check(
        'render-gore nouns rewritten onto intact skin',
        'ribs' not in g and 'open wound' not in g and 'intact skin' in g,
        g,
    )
    check('article agreement after substitution', ' an dark' not in g and ' a dark' in g, g)
    check("extreme keeps the writer's words", ps._render_safety_rewrite('ribs showing', 2)[1] == [])
    check('gore rewrite reported', len(gch) >= 3, str(gch))


def test_era_gate_offline():
    """era_gate without a GPU or an API: derivation, tiling, bbox mapping, qualifier."""
    from zyg_workflows import era_gate as EG

    era = {
        'is_historical': True,
        'period_label': 'Medieval Europe, 1347–1351',
        'period_start': 1347,
        'period_end': 1351,
        'anchors': [],
    }
    check('bucket from years', EG.period_bucket(era) == 'medieval')
    check('bucket antiquity', EG.period_bucket({'period_end': -44}) == 'antiquity')
    check('bucket from label only', EG.period_bucket({'period_label': 'Republican Rome, 100-44 BC'}) == 'antiquity')
    ch = EG.derive_checks_offline('a fishing boat at the quay, sailors in tunics, lantern light on the map', era)
    ids = [c['id'] for c in ch]
    check(
        'offline derivation finds the boat, the clothing and the map',
        'obj_boat' in ids and 'obj_clothing' in ids and 'obj_map' in ids,
        str(ids),
    )
    check(
        'every derived check carries a positive period fix',
        all(c['fix'] and 'no ' not in c['fix'][:3] for c in ch),
        str(ch),
    )
    ch2 = EG.derive_checks_offline('stained glass windows of the cathedral', era)
    check('stained glass does not trigger the window check', not any(c['id'] == 'obj_window' for c in ch2), str(ch2))
    items = EG.build_items({'subject': 'a beaked physician', 'checks': ch}, era)
    ids2 = [i['id'] for i in items]
    check(
        'items = derived + universal + gore + subject',
        'obj_boat' in ids2 and 'era_wrist' in ids2 and 'gore_wound_bone' in ids2 and 'subject_present' in ids2,
        str(ids2),
    )
    check(
        'subject question is asked on the full frame, expected yes',
        next(i for i in items if i['id'] == 'subject_present')['scope'] == 'frame'
        and next(i for i in items if i['id'] == 'subject_present')['expected'] == 'yes',
    )
    check(
        'every other item is on the tiles, expected no',
        all(i['scope'] == 'tiles' and i['expected'] == 'no' for i in items if i['id'] != 'subject_present'),
    )
    check(
        '@hair fix resolves to the era vocabulary', 'coif' in next(i for i in items if i['id'] == 'era_haircut')['fix']
    )
    boxes = EG.tile_boxes(1280, 720)
    check(
        '3x2 tiles cover the frame',
        len(boxes) == 6 and boxes[0][0] == 0 and boxes[-1][2] == 1280 and boxes[-1][3] == 720,
        str(boxes),
    )
    check('tiles overlap', boxes[0][2] > boxes[1][0])
    bb = EG.map_tile_bbox([0.5, 0.5, 1.0, 1.0], 6, boxes, (1280, 720))
    check(
        'tile bbox maps into the bottom-right of the frame (0-1000)',
        bb and bb[0] > 600 and bb[1] > 600 and bb[2] == 1000 and bb[3] == 1000,
        str(bb),
    )
    check(
        'full-frame bbox passes through',
        EG.map_tile_bbox([0.1, 0.2, 0.3, 0.4], 0, boxes, (1280, 720)) == [100, 200, 300, 400],
    )
    check('small-item area', EG.bbox_area_frac([100, 100, 200, 150]) < 0.01)
    q = EG.ladder_qualifier([{'fix': 'a horn lantern with a candle inside'}, {'fix': 'bare wrists'}], era)
    check(
        'ladder qualifier is positive and ends on the period',
        q.startswith(', a horn lantern') and 'bare wrists' in q and q.endswith('1347–1351'),
        q,
    )
    from PIL import Image

    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, 'f.jpg')
        Image.new('RGB', (1280, 720), (40, 40, 40)).save(src)
        paths, bxs, size = EG.make_tiles(src, td)
        check('make_tiles writes full frame + 6 enlarged tiles', len(paths) == 7 and size == (1280, 720))
        with Image.open(paths[1]) as t:
            check('tiles are enlarged to >= 896 px on the long side', max(t.size) >= 896, str(t.size))
        r = EG.judge_frame(src, items, era, prefer='api', api_key='', log=None, local_ok=False)
        check('no judge -> skipped, never a pass', r['skipped'] is True and r['flags'] == [], str(r))
    # vlm_inspector inline items contract
    from zyg_workflows import vlm_inspector as VI

    payload = VI._questions_payload(
        [{'id': 'x', 'question': 'q?', 'expected': 'no', 'frame_indices': [1, 2]}], 'pre', 0
    )
    check(
        'inline items pass per-question frame selection to the worker', payload[0].get('frames') == [1, 2], str(payload)
    )
    import inspect as _insp

    check(
        'inspect_frames accepts inline items + preamble',
        'items' in _insp.signature(VI.inspect_frames).parameters
        and 'preamble' in _insp.signature(VI.inspect_frames).parameters,
    )


def test_era_gate_wiring():
    """The gate, the ladder and the receipts are wired into the pipeline."""
    src = open('pipeline_scholarly.py', encoding='utf-8').read()
    check(
        'era gate is in the registry',
        "'era')" in src[src.index('_GATES_EXPECTED =') : src.index('_GATES_EXPECTED =') + 120],
    )
    check(
        'the old global moondream era question is gone', 'Say yes if this image shows any modern present-day' not in src
    )
    check(
        'render gate takes the prompt and the slot',
        "def _vlm_render_gate(image_path: str, prompt: str = '', slot: int | None = None)" in src,
    )
    check(
        'both generate paths pass prompt + slot',
        src.count('_vlm_render_gate(_attempt_p, prompt=_prompt_attempt, slot=idx)') == 2,
    )
    check('checks are extracted once per run, before the loop', '_era_slot_checks = _eg_pre.extract_checks(' in src)
    check('gate answers unreviewed, never pass, when no judge', "_last_gate_outcome['era'] = 'unreviewed'" in src)
    check('era gate default is ON for historical episodes', "_ERA_GATE_DEFAULT = '1'" in src)
    check(
        'era receipt filed on every path',
        src.count("_gate_receipt('era'") >= 1 and "'era', bool(_era_gate_stats['checked'])" in src,
    )
    check(
        'small boxed items go to region repair',
        'era_region_repair' in src.replace("'era_repair_tried'", 'era_region_repair'),
    )
    check(
        'hook: empty anatomy verdict escalates to a second judge',
        '_v_defect is None and slot == 0' in src and 'def _vlm_anatomy_escalate' in src,
    )
    check(
        'typography second vote when the prompt names a written thing',
        'if prompt and _TEXT_SUBJECT_RE.search(prompt):' in src and 'text_second_vote' in src,
    )
    check('C prompts are text-guarded across the whole prompt', "_head = (_body if _key == 'counterpoint'" in src)
    check(
        'ollama-built counterpoints get the text reframing too',
        "_cp_prompt = _cp_prompt.rstrip(' .,') + _TEXT_FRAMING_FIX" in src,
    )
    check('era front anchor at the render choke point', "_prompt = f'{_era_front}, {_prompt}'" in src)
    check(
        'deterministic period backstop at the render choke point',
        '_prompt, _bn_ch = _period_noun_rewrite(_prompt, _era_lock)' in src
        and "_prompt, _gore_ch = _render_safety_rewrite(_prompt, _sch_intensity['rank'])" in src,
    )
    check('bare-noun guard runs on every batch pair', '_parsed = _bare_noun_guard(_parsed)' in src)
    check('era anchor on the live prebuilt path', '_era_suffix_live' in src)
    check('writer rule: NO BARE NOUNS', 'NO BARE NOUNS: the renderer gives any unqualified object' in src)
    check('writer rule: hands out of the foreground', '- HANDS: keep hands out of the foreground' in src)
    check('writer rule: disease on the skin', 'DISEASE AND FAMINE ON THE SKIN, NOT THROUGH IT' in src)
    check(
        'intensity directive no longer names the hand',
        'Find the face, the hand, the' not in src and 'faces, hands, bodies under strain' not in src,
    )
    check('hook rule demands a subject cue', src.count('unmistakable cue of') >= 2)


def test_thumbnail_and_family():
    src = open('pipeline_scholarly.py', encoding='utf-8').read()
    i_thumb = src.index("_thumb_dst = os.path.join(out_dir, '_thumbnail.jpg')")
    i_clean = src.index('_cleanup_pipeline_output(\n            out_dir, final_video_path,')
    check('hook thumbnail is saved BEFORE cleanup deletes flux_images', i_thumb < i_clean)
    check('thumbnail prefers the hook still (index 0)', "int(_ei.get('index', -1)) == 0" in src)
    from zyg_workflows import scholarly_stills_backend as B

    old = os.environ.pop('ZYG_SCHOLARLY_STILL_FAMILY', None)
    try:
        check('still family defaults to qwen', B.scholarly_still_family() == 'qwen')
        os.environ['ZYG_SCHOLARLY_STILL_FAMILY'] = 'flux'
        check('flux restores the old path', B.scholarly_still_family() == 'flux')
        os.environ['ZYG_SCHOLARLY_STILL_FAMILY'] = 'nonsense'
        check('junk falls back to the default', B.scholarly_still_family() == 'qwen')
    finally:
        if old is None:
            os.environ.pop('ZYG_SCHOLARLY_STILL_FAMILY', None)
        else:
            os.environ['ZYG_SCHOLARLY_STILL_FAMILY'] = old
    check(
        'qwen path routes through Comfy only',
        '_sch_qwen_stills = True' in src and '_sch_use_comfy_images = True' in src,
    )
    check('qwen unavailable falls back to FLUX and says so', 'Qwen stills requested but unavailable' in src)
    check(
        'qwen renders at 20 steps / cfg 2.5',
        '_n_steps = 8 if _smoke else 20\n                            _g_scale = 2.5' in src,
    )
    check('qwen gets the live negatives', '_extra_neg_cg = _FLUX_NEGATIVE' in src and '_ERA_NEGATIVE' in src)
    check('qwen does not force the schnell unet', 'force_unet=(None if _sch_qwen_stills' in src)
    check('qwen skips the FLUX pose/IP anatomy graphs', 'if (_is_anatomy_shot and not _sch_qwen_stills' in src)
    check('model label reaches essay_images', "m.get('model') or 'FLUX.1-schnell'" in src)
    from zyg_workflows import murch_engine as me

    W = {'emotion': 0.45, 'story': 0.25, 'rhythm': 0.15, 'eye_trace': 0.10, 'continuity': 0.05}
    check(
        'exposition still forces wide by default',
        'wide establishing' in me.get_shot_type_grammar(2, 'calm', 0.2, 'exposition', W, 's', ''),
    )
    a1 = me.get_shot_type_grammar(1, 'calm', 0.2, 'exposition', W, 's', '', exposition_alternate=True)
    a2 = me.get_shot_type_grammar(2, 'calm', 0.2, 'exposition', W, 's', '', exposition_alternate=True)
    check(
        'exposition alternates medium/close with the flag',
        'medium' in a1 and 'close-up' in a2 and 'wide' not in a1 + a2,
        a1 + ' | ' + a2,
    )
