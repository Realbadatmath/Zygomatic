#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Pufferball regression: body plan in, person-only negatives out.

Moved verbatim out of tests/test_creature_sheet.py when it became this package.
"""

from .common import Image, _crews, cj, css, cts, json, needs_checklists

from .common import _isolate_review_cards  # noqa: F401  autouse fixture, see common.py

# ── The Pufferball regression: body plan in, person-only negatives out ───────
# 2026-08-26. The Zygo AI Pufferball klein LoRA rendered as a fur ball with a
# face — no tail, no arms, feet cropped — while the tail sat in 15 of 16
# training cells. Four independent causes, one test each, because each of them
# alone is enough to reproduce the defect.

_BP_FULL = (
    'a plump ball-shaped body, almost as wide as it is tall, covered in soft '
    'white fur; one segmented turquoise tail covered in tufts of the same soft '
    'white fur, rising from the lower back and curling up behind the body; '
    'two short turquoise arms; two turquoise three-toed feet'
)
_BRIEF = {
    'description': 'Round, puffy body with a turquoise face.',
    'body_plan': _BP_FULL,
    'style_hint': '3D animated film render',
}


def test_plan_clause_keeps_the_smallest_parts():
    """The parts are listed in DESCENDING prominence, so a tight cap eats exactly
    the arms and feet this clause exists to protect. Caught at limit=240: the
    real 253-char plan cut cleanly after the tail and dropped both."""
    plan = cts._plan_clause(_BRIEF)
    assert 'two short turquoise arms' in plan
    assert 'two turquoise three-toed feet' in plan
    assert plan == _BP_FULL.rstrip(' ,;.')


def test_plan_clause_runaway_cuts_on_a_part_boundary():
    """Half a part ("two turquoise three-") is worse than one part fewer."""
    cut = cts._plan_clause({'body_plan': '; '.join(f'part {i} of it' for i in range(200))})
    assert len(cut) <= 600
    assert cut.split('; ')[-1] == 'part %d of it' % (len(cut.split('; ')) - 1)
    assert not cut.endswith((';', ',', ' '))
    assert cts._plan_clause({}) == ''


def test_validation_prompt_carries_every_body_part():
    """training_tiles puts the plan in EVERY caption; a render prompt without it
    asks for a creature the adapter was never conditioned on."""
    vp = cts._val_prompt(_BRIEF, 'ZYG_CREATURE_TEST')
    assert vp.startswith('ZYG_CREATURE_TEST,')
    for part in ('turquoise tail', 'two short turquoise arms', 'two turquoise three-toed feet'):
        assert part in vp, part
    # the trainer-validation fix this rides on: still no human phrasing
    for human in (' person,', 'head and shoulders portrait', 'visible pores', 'unretouched'):
        assert human not in vp


def test_body_slots_ask_for_ground_and_feet():
    """The feet are ~11 latent tokens of 4096; the previews framed him so large
    that 98-100% of the bottom pixel row was subject and they were cropped off."""
    body = [a for _s, a, k, _d in cts._PREVIEW_SLOTS if k == 'body']
    assert body and all('feet visible' in a and 'space below the feet' in a for a in body)
    head = [a for _s, a, k, _d in cts._PREVIEW_SLOTS if k == 'head']
    assert head and not any('feet' in a for a in head)


@needs_checklists
def test_preview_judge_arms_the_body_plan_question():
    """cell_items() DROPS the body_plan item on an empty plan, so the preview
    judge asked 8 questions where the sheet asks 9 — and the one it skipped is
    the only one that looks for a missing tail, arms or feet. That is how three
    previews scored 3/3 PASS on renders with no tail (run log 'questions=8')."""
    base = cj.load_items(cj.PREVIEW_CHECKLIST)
    without = cj.cell_items('a front view', kind='body', base=base)
    with_bp = cj.cell_items('a front view', kind='body', base=base, body_plan=_BP_FULL)
    assert len(with_bp) == len(without) + 1
    bp = next(i for i in with_bp if i['id'] == 'body_plan')
    assert '{body_plan}' not in bp['question'] and 'three-toed feet' in bp['question']
    # a face close-up still must not be asked about feet
    assert not any(
        i['id'] in ('body_plan', 'whole_body')
        for i in cj.cell_items('a face', kind='head', base=base, body_plan=_BP_FULL)
    )


def test_render_previews_passes_plan_and_nonhuman_flag(tmp_path, monkeypatch, stub_module):
    """Reachability, not substring: prove the prompt the RENDERER receives carries
    the plan and that human_subject=False actually reaches generate_still."""
    seen = []

    class _Gen:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def generate_still(dest, prompt, **kw):
            seen.append({'prompt': prompt, 'kw': kw})
            Image.new('RGB', (8, 8), (9, 9, 9)).save(dest)
            return True, 'fake'

    monkeypatch.setattr(cts, '_ensure_comfy_env', lambda: None)
    stub_module('comfy_generation_service', _Gen)
    lora = tmp_path / 'l.safetensors'
    lora.write_bytes(b'x')
    cts._render_previews('cid0', _BRIEF, str(lora), 'klein', str(tmp_path), 'ZYG_T', None, lambda _m: None)

    assert len(seen) == len(cts._PREVIEW_SLOTS)
    assert all(c['kw'].get('human_subject') is False for c in seen)
    body = [c for c in seen if 'three-quarter' in c['prompt'] or 'front view' in c['prompt']]
    assert body, 'no body slot rendered'
    for c in body:
        assert 'two short turquoise arms' in c['prompt']
        assert 'two turquoise three-toed feet' in c['prompt']
        assert 'space below the feet' in c['prompt']
    close = [c for c in seen if 'close-up portrait' in c['prompt']]
    assert close and 'three-toed feet' not in close[0]['prompt']


def test_nonhuman_negative_drops_person_only_anatomy():
    """At cfg 4.0 the negative is live. "three fingers"/"claw hands"/"mutated
    hands" guard human hands; on a three-toed foot they argue against the body
    plan. The species-neutral guards must survive."""
    from zyg_workflows import comfy_generation_service as cgs

    pkg = {'conditioning': {'klein_lora_path': '/x'}, 'style_profile': {'render_style': 'stylized'}}
    neg = cgs.build_locked_negative_prompt(pkg, solo_subject=True)
    neg = cgs._dedupe_negative_clauses(f'{neg}, {css._NEG}')
    kept = cgs._dedupe_negative_clauses(cgs._strip_clause_tokens(neg, cgs._NONHUMAN_NEG_STRIP))
    clauses = [c.strip() for c in kept.split(',')]

    assert not any('finger' in c for c in clauses)
    for gone in ('mutated hands', 'malformed hands', 'claw hands', 'mismatched jewelry'):
        assert gone not in clauses, gone
    # a creature must still not grow a HUMAN hand, and defect guards stay
    for stays in (
        'human hand',
        'human face',
        'bad anatomy',
        'deformed face',
        'extra limbs',
        'fused limbs',
        'melted',
        'second creature',
    ):
        assert stays in clauses, stays
    # human renders are untouched
    assert 'three fingers' in [c.strip() for c in neg.split(',')]


def test_creature_negative_has_no_bare_hands_token():
    """A text encoder cannot tell "human hands" from "this creature's hands".
    The precise clause beside it ('human hand') already does that job."""
    clauses = [c.strip().lower() for c in css._NEG.split(',')]
    assert 'hands' not in clauses
    assert 'human hand' in clauses


def test_library_entry_exports_the_body_plan():
    """Downstream scene renders build their prompt from the library entry; the
    plan has to travel with the creature or they inherit the same defect."""
    import inspect
    from zyg_workflows import creature_library_service as cls

    src = inspect.getsource(cls.list_creatures)
    assert "'body_plan': str(meta.get('body_plan') or '')" in src


def test_klein_lora_runs_at_training_equivalent_strength():
    """ComfyUI applies (strength * alpha/rank). These exports carry alpha keys
    (lora_alpha 32 / rank 64 -> 0.5), which IS the scale training used, so
    strength must be 1.0 — qwen was already corrected this way when its alpha
    export landed; klein was left at 0.85 (= 0.425 effective, 15% under)."""
    wf = _crews('_comfy_workflows', 'klein_character_locked.json')
    with open(wf, encoding='utf-8') as fh:
        g = json.load(fh)
    loaders = [v for v in g.values() if isinstance(v, dict) and 'Lora' in str(v.get('class_type'))]
    assert len(loaders) == 1
    assert loaders[0]['inputs']['strength_model'] == 1.0
    assert loaders[0]['inputs']['strength_clip'] == 1.0


def test_stale_base_model_benchmark_is_dropped_when_the_prompt_changes(tmp_path):
    """SimpleTuner renders benchmarks/base_model/*.png ONCE and reuses it as the
    left panel of every validation strip, keyed on nothing. When the creature
    validation fix changed the prompt, the Pufferball's step-250 strip read
    "base model: a man in a black t-shirt | step 250: the creature" — correct
    training, stale baseline, and an operator reads that as a result."""
    from zyg_workflows import lora_trainer_service as lts

    def run(prev, new, make_bench=True):
        d = tmp_path / f'cfg{abs(hash((prev, new, make_bench)))}'
        out = d / 'w'
        bench = out / 'benchmarks' / 'base_model'
        if make_bench:
            bench.mkdir(parents=True)
            (bench / 'validation_1024x1024.png').write_bytes(b'x')
        if prev is not None and make_bench:
            (out / 'benchmarks' / '.validation_prompt').write_text(prev)
        d.mkdir(exist_ok=True)
        (d / 'config.json').write_text(json.dumps({'--validation_prompt': new, '--output_dir': str(out)}))
        lts._drop_stale_benchmarks(str(d))
        return (out / 'benchmarks' / 'base_model').is_dir()

    human = 'photograph of ZYG_X person, head and shoulders portrait, visible pores'
    creature = 'ZYG_X, a ball body; one tail; two arms; two three-toed feet, front view'

    assert run(human, creature) is False, 'changed prompt must drop the stale baseline'
    assert run(creature, creature) is True, 'matching sidecar must reuse the cache'
    # THE LEGACY CASE, and the one that actually bit: the prompt went stale before
    # any sidecar existed, so a transition check ("did it change since last run?")
    # sees prompt == prompt forever and the wrong baseline never expires.
    assert run(None, creature) is False, 'a benchmark with no sidecar must be dropped'
    assert run(human, creature, make_bench=False) is False, 'missing dir must not raise'


def test_stale_validation_frames_are_dropped_with_the_benchmark(tmp_path):
    """Frames go stale the same way and for the same reason: a run only overwrites
    the checkpoints it reaches, so the Pufferball retrain left step_0 from the
    PREVIOUS run beside 8 fresh ones and the card showed 2 humans among 8
    creatures. A mixed set reads as a contradiction, not as leftovers."""
    from zyg_workflows import lora_trainer_service as lts

    def run(sidecar, new):
        d = tmp_path / f'v{abs(hash((sidecar, new)))}'
        out = d / 'w'
        (out / 'benchmarks' / 'base_model').mkdir(parents=True)
        vdir = out / 'validation_images'
        vdir.mkdir()
        for f in ('step_0_validation_0.png', 'step_250_validation_0.png', 'keep.txt'):
            (vdir / f).write_bytes(b'x')
        if sidecar is not None:
            (out / 'benchmarks' / '.validation_prompt').write_text(sidecar)
        d.mkdir(exist_ok=True)
        (d / 'config.json').write_text(json.dumps({'--validation_prompt': new, '--output_dir': str(out)}))
        lts._drop_stale_benchmarks(str(d))
        return sorted(p.name for p in vdir.iterdir())

    human = 'photograph of ZYG_X person, head and shoulders portrait'
    creature = 'ZYG_X, a ball body; one tail; two arms; two three-toed feet'

    assert run(human, creature) == ['keep.txt'], 'stale frames must go with the baseline'
    assert len(run(creature, creature)) == 3, 'a matching prompt must keep its frames'
