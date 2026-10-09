#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Regression checks for the documentary image-intensity dial (2026-08-22/24).

Run from the crews directory:  python3 scripts/test_intensity_dial.py

What it protects — every one of these was a real defect once:
  * the dial resolves 'standard' | 'high' | 'extreme' and the HOOK slot (image 0)
    runs one level above the episode, so a default episode opens on 'extreme';
  * 'standard' reproduces the pre-dial pipeline EXACTLY (no hook, wide opener,
    no suffixes, no rule text) — the old restraint is still one option away;
  * murch_engine's exposition lock is bypassed only when hook_slot=True and
    counterpoint honours suppress_above;
  * the batch prompt writer is handed arc=hook / extreme close-up for slot 1,
    the intensity rules, the anti-gore steer, and the hook rule ONLY in the
    batch that contains slot 1;
  * the per-slot assembler gives the hook its own style row and mood, and the
    intensity suffix scales with level;
  * the moondream anatomy question stays the ONE-sentence template that the
    judge can parse (a longer version shipped 0/9 recall, see the bench script).

The batch writer and the assembler are closures ~4000 lines inside
_run_scholarly_pipeline, so they are lifted from the SHIPPING source with ast
and executed against stub state — this tests the code that runs, not a copy.
"""

import ast
import os
import re
import sys
import textwrap

CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CREWS)
os.chdir(CREWS)

from zyg_dashboard import crewai_web_gui  # noqa: E402,F401  — breaks the bp_benchmark circular import
from zyg_workflows import pipeline_scholarly as ps  # noqa: E402
from zyg_workflows import murch_engine as me  # noqa: E402
from zyg_workflows import pipeline_common as pc  # noqa: E402

FAILS = []


def chk(name, cond, extra=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'\n      <- {extra!r}'))
    if not cond:
        FAILS.append(name)


SRC = open(os.path.join(CREWS, 'pipeline_scholarly.py'), encoding='utf-8').read()
TREE = ast.parse(SRC)


def lift(name):
    fn = next(n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == name)
    return textwrap.dedent(ast.get_source_segment(SRC, fn))


# ── 1. dial resolution + options normaliser ──────────────────────────────────
d = ps._scholarly_image_intensity(None)
chk('default level is high', d['level'] == 'high', d)
chk('default hook is extreme', d['hook_level'] == 'extreme', d)
s = ps._scholarly_image_intensity({'image_intensity': 'standard'})
chk('standard is disabled', s['enabled'] is False, s)
chk('standard hook is high, not extreme', s['hook_level'] == 'high', s)
x = ps._scholarly_image_intensity({'image_intensity': 'extreme'})
chk('extreme hook caps at extreme', x['hook_level'] == 'extreme' and x['rank'] == 2, x)
chk('junk falls back to high', ps._scholarly_image_intensity({'image_intensity': 'nope'})['level'] == 'high')
chk('normaliser default high', pc._normalize_pipeline_options({})['image_intensity'] == 'high')
chk(
    'normaliser keeps STANDARD',
    pc._normalize_pipeline_options({'image_intensity': 'STANDARD'})['image_intensity'] == 'standard',
)
chk('normaliser survives None', pc._normalize_pipeline_options(None)['image_intensity'] == 'high')
for lvl in ('standard', 'high', 'extreme'):
    chk(f'vocab tables have {lvl}', lvl in ps._INTENSITY_STYLE_CTX and lvl in ps._INTENSITY_MOOD_SUFFIX)
chk(
    'standard adds no vocabulary',
    ps._INTENSITY_STYLE_CTX['standard'] == '' and ps._INTENSITY_MOOD_SUFFIX['standard'] == '',
)
for lvl in ('high', 'extreme'):
    v = (ps._INTENSITY_STYLE_CTX[lvl] + ps._INTENSITY_MOOD_SUFFIX[lvl]).lower()
    chk(f'{lvl} vocabulary carries no gore nouns', not re.search(r'\b(gore|blood|flesh|wound|corpse|mutilat)', v), v)

# ── 2. murch_engine ──────────────────────────────────────────────────────────
W = {'emotion': 0.45, 'story': 0.25, 'rhythm': 0.15, 'eye_trace': 0.10, 'continuity': 0.05}
chk(
    'exposition still forces wide without hook_slot',
    'wide establishing' in me.get_shot_type_grammar(0, 'shock', 0.95, 'exposition', W, 's', ''),
)
chk(
    'hook_slot bypasses the exposition lock',
    'extreme close-up' in me.get_shot_type_grammar(0, 'calm', 0.1, 'exposition', W, 's', '', hook_slot=True),
)
tp = [{'sentence_idx': 5, 'type': 'climax'}]
me.reset_counterpoint_state()
chk('counterpoint fires at a peak by default', me.should_apply_counterpoint(5, 'shock', 0.9, 'climax', tp) is True)
me.reset_counterpoint_state()
chk(
    'counterpoint suppressed above the cap',
    me.should_apply_counterpoint(5, 'shock', 0.9, 'climax', tp, suppress_above=0.6) is False,
)

# ── 3. the batch prompt writer (_make_user_msg) ───────────────────────────────
N = 6
SCRIPT = ' '.join(f'w{i}' for i in range(600))


def _bounds(idx, n):
    nw = len(SCRIPT.split())
    return idx * nw // n, ((idx + 1) * nw // n if idx < n - 1 else nw)


def render_msg(level):
    ns = {
        'n': N,
        'topic': 'general',
        'directive': 'the 1665 plague',
        '_essay_title_for_prompt': 'The Great Plague',
        '_style_ctx': 'historical cinematic',
        '_quality_tag': 'cinematic grain',
        '_period_lock_section': '',
        '_period_lock_rule': '',
        '_is_battle_topic': False,
        '_sch_intensity': ps._scholarly_image_intensity({'image_intensity': level}),
        '_hands_rule': '  - HANDS: keep hands out of the foreground — never a hand\n',
        '_skin_rule': (
            '  - DISEASE AND FAMINE ON THE SKIN, NOT THROUGH IT\n'
            if ps._scholarly_image_intensity({'image_intensity': level})['rank'] < 2
            else ''
        ),
        'narration_script': SCRIPT,
        '_slot_word_bounds': _bounds,
        '_narration_sentences': ['a sentence here.'] * 20,
        '_me2b': me,
        'pipeline_state': {
            'emotion_curve': [{'emotion': 'calm', 'intensity': 0.3}] * 20,
            'turning_points': [],
            '_stage3_scene_list': [f'scene {i}' for i in range(N)],
            'visual_tags': [],
        },
    }
    exec(compile(lift('_make_user_msg'), '<lifted:_make_user_msg>', 'exec'), ns)  # noqa: S102  AST subset lifted from a source file shipped in this repo, never from input
    return ns['_make_user_msg']


mk = render_msg('high')
m = mk(0, N)
slot1 = next(l for l in m.split('\n') if l.strip().startswith('Slot 1:') and 'arc=' in l)
chk('high: slot 1 brief is arc=hook + extreme close-up', 'arc=hook' in slot1 and 'extreme close-up' in slot1, slot1)
chk('high: hook rule present', 'SLOT 1 IS THE HOOK' in m)
chk('high: intensity rule present', '- INTENSITY:' in m)
chk('high: anti-gore steer present', 'gratuitous gore' in m)
chk('high: time-lock carve-out present', 'SLOT 1 IS EXEMPT' in m)
chk('high: no EXTREME rule', '- EXTREME:' not in m)
m2 = mk(3, N)
chk('batch 2 has no hook rule', 'SLOT 1 IS THE HOOK' not in m2 and 'SLOT 1 IS EXEMPT' not in m2)
chk('batch 2 keeps the intensity rule', '- INTENSITY:' in m2)
mx = render_msg('extreme')(0, N)
chk('extreme: EXTREME rule present', '- EXTREME:' in mx)
chk('extreme: still steers away from decoration', 'never as decoration' in mx)
ms = render_msg('standard')(0, N)
slot1s = next(l for l in ms.split('\n') if l.strip().startswith('Slot 1:') and 'arc=' in l)
chk(
    'standard: slot 1 brief is unchanged (exposition, wide)',
    'arc=exposition' in slot1s and 'wide establishing' in slot1s,
    slot1s,
)
chk(
    'standard: no hook/intensity text at all',
    all(t not in ms for t in ('SLOT 1 IS THE HOOK', '- INTENSITY:', 'SLOT 1 IS EXEMPT', '- EXTREME:')),
)

# ── 4. the per-slot assembler (_build_image_prompt) ───────────────────────────
SENTS = [f'The plague reached Cripplegate in sentence {i} and many died there.' for i in range(20)]
SCRIPT2 = ' '.join(SENTS)
STYLES = [f', style{i}' for i in range(20)]
ARC = {
    'exposition': [0, 9, 13],
    'rising': [1, 4, 6],
    'climax': [2, 10, 14],
    'falling': [17, 15, 7],
    'resolution': [18, 19, 3],
    'hook': [11, 14, 5],
}
CURVE = [{'emotion': 'calm', 'intensity': 0.25} for _ in range(20)]


def make_bip(level, prebuilt=None):
    it = ps._scholarly_image_intensity({'image_intensity': level})

    def _b(idx, n):
        nw = len(SCRIPT2.split())
        return idx * nw // n, ((idx + 1) * nw // n if idx < n - 1 else nw)

    ns = {
        'narration_script': SCRIPT2,
        '_slot_word_bounds': _b,
        '_extract_named_entities': lambda t: 'Cripplegate',
        '_used_entities': [],
        '_sentence_event_tag': lambda s: 'plague',
        '_tag_sentence': lambda s: 'historical archive',
        'pipeline_state': {
            'anatomy_hints_by_tag': {},
            'visual_tags': [{'scene_desc': 'a cart of bodies in a narrow street'}] * 20,
        },
        '_recent_emotions': [],
        '_EMOTION_RELIEF_SLOTS': {'calm', 'mystery', 'contemplative', 'wonder'},
        '_recent_shot_sizes': [],
        '_recent_shot_types': [],
        '_shot_size_of': lambda s: s[:12],
        '_SHOT_ROTATION': ['wide establishing shot, cinematic', 'close-up, tight focus'],
        '_is_modern_topic': False,
        '_prebuilt_prompts': prebuilt or [],
        '_ARC_STYLE_MAP': ARC,
        '_STYLE_SUFFIXES': STYLES,
        '_era_variants': ['period-accurate medieval setting'],
        '_sch_intensity': it,
        '_is_hook_slot': lambda idx: idx == 0 and it['hook_rank'] >= 2,
        '_INTENSITY_MOOD_SUFFIX': ps._INTENSITY_MOOD_SUFFIX,
        '_TEXT_SUBJECT_RE': ps._TEXT_SUBJECT_RE,
        '_TEXT_FRAMING_FIX': ps._TEXT_FRAMING_FIX,
        '_log': lambda *a, **k: None,
        '_debug': lambda *a, **k: None,
    }
    exec(compile(lift('_build_image_prompt'), '<lifted:_build_image_prompt>', 'exec'), ns)  # noqa: S102  AST subset lifted from a source file shipped in this repo, never from input
    return ns['_build_image_prompt']


def call(bip, idx):
    return bip(idx, N, SENTS, 'plague', prev_prompt='', emotion_curve=CURVE, turning_points=[])


bip = make_bip('high')
p0, *r0 = call(bip, 0)
chk('hook shot is extreme close-up', 'extreme close-up' in r0[3], r0[3])
chk('hook gets the hook mood row', 'strongest single image' in p0, p0)
chk('hook gets the extreme suffix', 'overwhelming presence' in p0, p0)
chk('hook uses the hook style row (11), not exposition (0)', ', style11' in p0 and ', style0,' not in p0, p0)
p1, *r1 = call(make_bip('high'), 1)
chk('slot 1 gets the high suffix only', 'charged with physical stakes' in p1 and 'overwhelming presence' not in p1, p1)
p0s, *r0s = call(make_bip('standard'), 0)
chk(
    'standard slot 0 is wide establishing on the exposition row',
    'wide establishing' in r0s[3] and ', style0' in p0s,
    p0s,
)
chk('standard adds no suffix', 'physical stakes' not in p0s and 'arresting' not in p0s, p0s)
PRE = [{'standard': f'prebuilt {i}', 'counterpoint': 'cp'} for i in range(N)]
pp0, *_ = call(make_bip('high', PRE), 0)
pp1, *_ = call(make_bip('high', PRE), 1)
chk('prebuilt hook: text kept + extreme suffix', 'prebuilt 0' in pp0 and 'overwhelming presence' in pp0, pp0)
chk('prebuilt body: high suffix', 'charged with physical stakes' in pp1 and 'overwhelming presence' not in pp1, pp1)
pps, *_ = call(make_bip('standard', PRE), 0)
# 2026-08-25: the era anchor now rides the live (prebuilt) path at every level —
# it was only ever on the no-Claude fallback. Standard still adds no intensity text.
chk(
    'standard prebuilt carries the era anchor and no intensity text',
    pps.endswith('symmetrical composition, period-accurate medieval setting') and 'physical stakes' not in pps,
    pps,
)
chk('high prebuilt carries the era anchor at the END', pp1.endswith('period-accurate medieval setting'), pp1)

# ── 4b. the flat half (2026-08-25) ────────────────────────────────────────────
# exposition slots alternate medium/close with the dial up; wide lock stays at standard
# a turning point at sentence 10 keeps slots 1-2 (sentences 3-9) in exposition
TP_EXPO = [{'sentence_idx': 10, 'type': 'rising'}]


def call_tp(bip, idx):
    return bip(idx, N, SENTS, 'plague', prev_prompt='', emotion_curve=CURVE, turning_points=TP_EXPO)


p2h, *r2h = call_tp(make_bip('high'), 2)
p1h, *r1h = call_tp(make_bip('high'), 1)
chk(
    'high: exposition slot 1 is medium, slot 2 close-up (no wide lock)',
    'medium' in r1h[3] and 'close-up' in r2h[3] and 'wide' not in r1h[3] + r2h[3],
    r1h[3] + ' | ' + r2h[3],
)
p2s, *r2s = call_tp(make_bip('standard'), 2)
chk('standard: exposition slot 2 is still wide establishing', 'wide establishing' in r2s[3], r2s[3])
# the rotation may not force wide at high (source check: the block set is extended)
i_rot = SRC.index('_blocked = {_shot_size_of(_s) for _s in _recent_shot_sizes[-2:]}')
chk('high: shot rotation blocks wide/aerial', "_blocked |= {'ws', 'aerial'}" in SRC[i_rot : i_rot + 700])
# counterpoint only in the falling zone at high
i_cp = SRC.index('_cp_zone_ok =')
chk(
    'high: counterpoint allowed only in the falling zone',
    "(not _sch_intensity['enabled']) or (_arc_zone == 'falling')" in SRC[i_cp : i_cp + 200],
)
chk('counterpoint condition uses the zone guard', 'not _hook_slot and _cp_zone_ok' in SRC)


# the brief: exposition alternates in the writer's Murch brief too
def render_msg_tp(level):
    mk_ = render_msg(level)
    # same writer, but the pipeline state carries a turning point at sentence 10
    # so slots 1-6 of this 6-slot fixture are all exposition
    mk_.__globals__['pipeline_state']['turning_points'] = [{'sentence_idx': 10, 'type': 'rising'}]
    return mk_


mh = render_msg_tp('high')(0, N)
slot2 = next(l for l in mh.split('\n') if l.strip().startswith('Slot 2:') and 'arc=' in l)
slot3 = next(l for l in mh.split('\n') if l.strip().startswith('Slot 3:') and 'arc=' in l)
chk(
    'high brief: exposition slots 2/3 alternate medium/close, no wide',
    'medium shot' in slot2 and 'close-up' in slot3 and 'wide' not in slot2 + slot3,
    slot2 + ' | ' + slot3,
)
ms2 = render_msg_tp('standard')(0, N)
slot2s = next(l for l in ms2.split('\n') if l.strip().startswith('Slot 2:') and 'arc=' in l)
chk('standard brief: exposition slot 2 still wide', 'wide establishing' in slot2s, slot2s)
chk('hook rule demands one unmistakable subject cue', 'unmistakable cue of this episode' in mh)
chk('hands are no longer something to get close to', 'faces, hands, bodies' not in mh and 'never a hand' in mh)
chk('hands rule present at every level', '- HANDS:' in mh and '- HANDS:' in ms2)
chk(
    'disease-on-skin rule at high, absent at extreme',
    'DISEASE AND FAMINE ON THE SKIN' in mh and 'DISEASE AND FAMINE ON THE SKIN' not in render_msg('extreme')(0, N),
)

# ── 5. the anatomy gate question stays parseable by moondream ────────────────
i = SRC.find('_anatomy_q = (')
lits = ''.join(re.findall(r"'([^']*)'", SRC[i : i + 900]))
chk(
    'anatomy question: one-sentence template (dial on)',
    'grotesquely distorted faces, melted facial features, or deformed anatomy, otherwise say no.' in lits,
    lits[:200],
)
chk('anatomy question: original kept for standard', 'grotesquely distorted or screaming faces' in lits)
chk('anatomy question: the moondream-breaking version is gone', 'Say no to those' not in lits)

print()
print('FAILURES:', FAILS if FAILS else 'none')
sys.exit(1 if FAILS else 0)
