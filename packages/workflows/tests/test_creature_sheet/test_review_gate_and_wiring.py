#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The review-gate state machine, and board cards <-> API <-> stages.

Moved verbatim out of tests/test_creature_sheet.py when it became this package.
"""

from .common import Image, _crews, _pure, cj, css, csvc, cts, json, needs_checklists, os
from .test_plan_and_sheet import _fake_edit, _noise

from .common import _isolate_review_cards  # noqa: F401  autouse fixture, see common.py

# ── review-gate state machine ────────────────────────────────────────────────


class _Stages:
    def __init__(self):
        self.calls = []

    def set(self, n):
        self.calls.append(('set', n))

    def done(self, n):
        self.calls.append(('done', n))

    def fail(self, n, e):
        self.calls.append(('fail', n, e))


def _fake_build_sheet(ds, brief, **kw):
    kw['progress_fn']('Anchor')
    kw['progress_fn']('Multi-Angle Sheet')
    kw['progress_fn']('Sheet QC')
    os.makedirs(os.path.join(ds, 'contact_sheet'), exist_ok=True)
    sp = os.path.join(ds, 'contact_sheet', 'sheet.png')
    Image.new('RGB', (32, 32), (1, 2, 3)).save(sp)
    root = os.path.join(ds, 'sheet.png')
    Image.new('RGB', (32, 32), (1, 2, 3)).save(root)
    cells = []
    for i in range(8):
        p = os.path.join(ds, 'contact_sheet', f'cell_{i:02d}.png')
        Image.new('RGB', (32, 32), (i, i, i)).save(p)
        cells.append(
            {
                'idx': i,
                'id': f'c{i}',
                'label': f'view {i}',
                'path': p,
                'ok': True,
                'judged': True,
                'judge_tier': 'resident',
            }
        )
    rep = {
        'cells': cells,
        'sheet_path': sp,
        'sheet_root_copy': root,
        'pass_count': 8,
        'cell_count': 8,
        'pass_rate': 1.0,
        'judged_any': True,
        'refs': [],
        'anchors': {'identity': {'path': root}},
        'source': 'scratch',
        'identity': {'model': 'facebook/dinov2-base'},
    }
    with open(os.path.join(ds, 'contact_sheet', 'sheet.json'), 'w') as fh:
        json.dump(rep, fh)
    return rep


def test_review_gate_parks_then_resumes(tmp_path, monkeypatch, stub_module):
    monkeypatch.setattr(cts, 'DATASET_ROOT', str(tmp_path / 'ds'))
    monkeypatch.setattr(cts, 'OUTPUT_ROOT', str(tmp_path / 'out'))
    monkeypatch.setattr(
        cts,
        '_generate_creature_brief',
        lambda d, log, reference_paths=None: {
            'name': 'Dr',
            'description': 'red dragon',
            'species': 'dragon',
            'profile_key': 'fantasy_dragon',
        },
    )
    monkeypatch.setattr(css, 'build_sheet', _fake_build_sheet)
    monkeypatch.setattr(cts, '_ensure_comfy_env', lambda: None)
    logs = []
    st = _Stages()
    job = {'creature_options': {'source': 'scratch', 'review_gate': True}}
    cts.run_creature_training(
        job,
        'abcdef123456',
        'red dragon',
        image_paths=[],
        set_stage=st.set,
        complete_stage=st.done,
        fail_stage=st.fail,
        log_fn=lambda lvl, stage, m: logs.append((lvl, stage, m)),
        phase='full',
    )
    assert job['status'] == 'awaiting_review'
    assert job['sheet_report']['pass_count'] == 8
    assert ('set', cts.STAGE_REVIEW) in st.calls
    assert ('done', cts.STAGE_QC) in st.calls
    assert not any(c[0] == 'fail' for c in st.calls)
    assert os.path.isfile(os.path.join(cts.DATASET_ROOT, 'abcdef123456', 'manifest.json'))

    # resume: mocked trainer + previews
    class _Trainer:
        def start_training(
            self, cid, dataset_dir, trigger_token=None, model_family='klein', output_root=None, validation_prompt=None
        ):
            assert dataset_dir.endswith('/training') and model_family == 'klein'
            assert trigger_token == 'ZYG_CREATURE_ABCDEF'
            n = len([f for f in os.listdir(dataset_dir) if f.endswith('.png')])
            assert n == 8
            # 2026-08-26: without an explicit prompt the trainer falls back to its
            # character defaults and validates the creature as a HUMAN portrait —
            # which is what every creature LoRA on disk before this date shows.
            assert validation_prompt, 'creature training must override the validation prompt'
            assert validation_prompt.startswith(trigger_token + ',')
            assert 'red dragon' in validation_prompt
            for human in (' person,', 'head and shoulders portrait', 'visible pores'):
                assert human not in validation_prompt, human
            return trigger_token

        def get_status(self, cid, model_family=None, output_root=None):
            return {'done': True, 'pct': 100, 'lora_path': str(tmp_path / 'lora.safetensors')}

        def get_lora_path(self, cid, model_family=None, output_root=None):
            return str(tmp_path / 'lora.safetensors')

    import types

    fake_lts = types.SimpleNamespace(get_trainer=lambda: _Trainer(), last_start_result=lambda cid: {})
    stub_module('lora_trainer_service', fake_lts)
    monkeypatch.setattr(cts, '_render_previews', lambda *a, **k: ([], {'previews': []}))
    monkeypatch.setattr(cts.time, 'sleep', lambda s: None)
    (tmp_path / 'lora.safetensors').write_bytes(b'x')
    job['status'] = 'running'
    cts.run_creature_training(
        job,
        'abcdef123456',
        'red dragon',
        image_paths=[],
        set_stage=st.set,
        complete_stage=st.done,
        fail_stage=st.fail,
        log_fn=lambda lvl, stage, m: logs.append((lvl, stage, m)),
        phase='train',
    )
    assert job['status'] == 'completed', job.get('error')
    assert job['result']['train_family'] == 'klein'
    assert ('done', cts.STAGE_TRAIN) in st.calls and ('done', cts.STAGE_PREVIEW) in st.calls
    man = json.load(open(os.path.join(cts.DATASET_ROOT, 'abcdef123456', 'manifest.json')))
    assert man['status'] == 'trained' and man['total'] == 8


def test_no_review_gate_runs_through(tmp_path, monkeypatch, stub_module):
    monkeypatch.setattr(cts, 'DATASET_ROOT', str(tmp_path / 'ds'))
    monkeypatch.setattr(cts, 'OUTPUT_ROOT', str(tmp_path / 'out'))
    monkeypatch.setattr(
        cts,
        '_generate_creature_brief',
        lambda d, log, reference_paths=None: {
            'name': 'Dr',
            'description': 'red dragon',
            'species': 'dragon',
            'profile_key': 'fantasy_dragon',
        },
    )
    monkeypatch.setattr(css, 'build_sheet', _fake_build_sheet)
    monkeypatch.setattr(cts, '_ensure_comfy_env', lambda: None)
    seen = {}

    class _Trainer:
        def start_training(self, cid, dataset_dir, **kw):
            seen['started'] = True
            return 'ZYG_CREATURE_ABCDEF'

        def get_status(self, cid, **kw):
            return {'done': True, 'lora_path': None}

        def get_lora_path(self, cid, **kw):
            return None

    import types

    stub_module(
        'lora_trainer_service',
        types.SimpleNamespace(get_trainer=lambda: _Trainer(), last_start_result=lambda cid: {}),
    )
    monkeypatch.setattr(cts, '_render_previews', lambda *a, **k: ([], {}))
    monkeypatch.setattr(cts.time, 'sleep', lambda s: None)
    st = _Stages()
    job = {'creature_options': {'source': 'scratch', 'review_gate': False}}
    cts.run_creature_training(
        job,
        'abcdef123456',
        'red dragon',
        image_paths=[],
        set_stage=st.set,
        complete_stage=st.done,
        fail_stage=st.fail,
        log_fn=lambda *a: None,
        phase='full',
    )
    assert seen.get('started') and job['status'] == 'completed'


# ── wiring: board cards ↔ API ↔ stages ───────────────────────────────────────
# test_kanban_cards_match_api_and_stages lives in the dashboard repository now
# (tests/test_creature_board_wiring.py): the board, the blueprint and the Live Tail are
# all its sources, and only it may see both sides — the dashboard imports this library,
# never the other way round.


def test_in_process_run_is_never_clobbered_by_the_disk_snapshot(tmp_path, monkeypatch):
    """2026-08-26 regression. A job once run by scripts/creature_worker.py keeps
    worker.mode == 'standalone' in its state file for ever, and the refresh helper
    re-reads that file on every status poll and REPLACES the registry entry. When
    a later resume ran inside the GUI, the worker thread was left mutating an
    orphaned dict: it parked at awaiting_review, the saver kept snapshotting the
    stale disk copy, and the finished run was then read back as 'interrupted' —
    a completed sheet reported as a crash."""
    registry, state = {}, tmp_path / 'creature_gen_abcdef123456.json'
    stale = {'creature_id': 'abcdef123456', 'status': 'running', 'worker': {'mode': 'standalone', 'pid': None}}
    state.write_text(json.dumps(stale), encoding='utf-8')
    monkeypatch.setattr(csvc, '_creature_gen_jobs', registry, raising=False)
    monkeypatch.setattr(csvc, '_creature_state_path', lambda cid: str(state), raising=False)

    # no live thread → a genuine standalone run is still followed from its file
    live = dict(stale) | {'status': 'awaiting_review'}
    registry['abcdef123456'] = live
    assert csvc._creature_refresh_external(live)['status'] == 'running'

    # a worker thread in THIS process owns the dict — the file must not win
    import threading as _th

    stop = _th.Event()
    t = _th.Thread(target=stop.wait, name='creature-train-abcdef12', daemon=True)
    t.start()
    try:
        owned = dict(stale) | {'status': 'awaiting_review'}
        registry['abcdef123456'] = owned
        assert csvc._creature_refresh_external(owned) is owned
        assert registry['abcdef123456'] is owned
    finally:
        stop.set()
        t.join(timeout=5)

    # and an in-GUI resume re-stamps ownership so the refresh never applies again
    gui = open(_crews('crewai_web_gui.py'), encoding='utf-8').read()
    assert "job['worker'] = {'pid': None, 'mode': 'in_gui'" in gui


def test_review_gate_is_reachable_by_an_operator():
    """2026-08-26 regression. The gate parked the run, logged one line and
    stopped: no Zero card, no board affordance, no notification — the documented
    way through it was a hand-written POST nobody was shown. Each assertion below
    is one door onto the gate; a gate with no door is a stall, not a gate."""
    api = open(_crews('bp_pipeline_api.py'), encoding='utf-8').read()
    # the sheet the decision is ABOUT must be servable
    assert '/api/internal/creature/<creature_id>/sheet' in api
    # approve/reject are callable as functions, so Zero and the route cannot drift
    assert 'def approve_creature_review(' in api and 'def reject_creature_review(' in api

    store = open(_crews('bp_zero_public_store.py'), encoding='utf-8').read()
    assert "_pipeline_kind == 'creature_review'" in store  # allow branch
    assert "elif _pipeline_kind == 'creature_review':" in store  # decline branch
    assert 'approve_creature_review' in store

    js = open(_crews('Static', 'js', 'dashboard_agent_zero.js'), encoding='utf-8').read()
    assert "pipeline === 'creature_review'" in js  # Zero card links the sheet

    kb = open(_crews('kanban_assets', 'kanban_main.js'), encoding='utf-8').read()
    assert 'function _updateReviewGate(' in kb and 'function kbReviewDecide(' in kb
    assert '_updateReviewGate(pipeline);' in kb  # actually CALLED, not just defined
    assert '/api/kanban/creature/decide' in kb
    assert 'id="kb-review-gate"' in open(_crews('kanban.html'), encoding='utf-8').read()
    # a parked run is a LIVE pipeline: reading it as idle blanked every card on
    # the board back to QUEUED and hid the jump-to-active badge
    assert 'const _parked = !!(pipeline && pipeline.review_pending);' in kb
    assert "(pipeline.status !== 'running' && !_parked)" in kb

    ks = open(_crews('kanban_server.py'), encoding='utf-8').read()
    assert "path == '/api/kanban/creature/decide'" in ks  # the proxy is routed
    assert "path == '/api/kanban/creature/sheet'" in ks
    assert 'X-Zero-Public-Token' in ks  # ...and authenticates


def test_park_queues_one_operator_card_and_resolve_closes_it(tmp_path, monkeypatch):
    monkeypatch.setattr(cts, 'DATASET_ROOT', str(tmp_path / 'ds'))
    monkeypatch.setattr(cts, 'OUTPUT_ROOT', str(tmp_path / 'out'))
    monkeypatch.setattr(
        cts,
        '_generate_creature_brief',
        lambda d, log, reference_paths=None: {
            'name': 'Pufferball',
            'description': 'round and puffy',
            'species': 'creature',
            'profile_key': 'real_wildlife',
        },
    )
    monkeypatch.setattr(css, 'build_sheet', _fake_build_sheet)
    monkeypatch.setattr(cts, '_ensure_comfy_env', lambda: None)
    st = _Stages()
    job = {'creature_options': {'source': 'scratch', 'review_gate': True}}
    cts.run_creature_training(
        job,
        'abcdef123456',
        'a pufferball',
        image_paths=[],
        set_stage=st.set,
        complete_stage=st.done,
        fail_stage=st.fail,
        log_fn=lambda *a: None,
        phase='full',
    )
    assert job['status'] == 'awaiting_review'
    cards = json.load(open(cts._PENDING_PATH, encoding='utf-8'))
    assert len(cards) == 1
    card = cards[0]
    assert card['pipeline'] == 'creature_review'
    assert card['status'] == 'pending'
    assert card['creature_id'] == 'abcdef123456' and card['char_id'] == 'abcdef123456'
    assert 'Pufferball' in card['label']
    assert card['model'] == cts.train_family()  # the licence gate reads this
    assert card['sheet_report']['pass_count'] == 8
    assert job['review_card_id'] == card['id']

    # a re-park (resume --phase sheet) must not stack a second card on the queue
    job['status'] = 'running'
    cts.run_creature_training(
        job,
        'abcdef123456',
        'a pufferball',
        image_paths=[],
        set_stage=st.set,
        complete_stage=st.done,
        fail_stage=st.fail,
        log_fn=lambda *a: None,
        phase='full',
    )
    assert len(json.load(open(cts._PENDING_PATH, encoding='utf-8'))) == 1

    # approving through ANY door closes the card, so the badge stops blinking
    assert cts.resolve_review_card('abcdef123456', 'approved') == 1
    closed = json.load(open(cts._PENDING_PATH, encoding='utf-8'))[0]
    assert closed['status'] == 'approved' and closed['decided_at']
    assert closed['approved_job_id'] == 'abcdef123456'
    assert cts.resolve_review_card('abcdef123456', 'approved') == 0  # idempotent


def test_review_card_push_never_loses_the_park(tmp_path, monkeypatch):
    """A broken queue must not cost the operator the parked state itself."""
    monkeypatch.setattr(cts, 'DATASET_ROOT', str(tmp_path / 'ds'))
    monkeypatch.setattr(cts, 'OUTPUT_ROOT', str(tmp_path / 'out'))
    monkeypatch.setattr(
        cts,
        '_generate_creature_brief',
        lambda d, log, reference_paths=None: {
            'name': 'Dr',
            'description': 'red dragon',
            'species': 'dragon',
            'profile_key': 'fantasy_dragon',
        },
    )
    monkeypatch.setattr(css, 'build_sheet', _fake_build_sheet)
    monkeypatch.setattr(cts, '_ensure_comfy_env', lambda: None)
    monkeypatch.setattr(cts, 'push_review_card', lambda *a, **k: (_ for _ in ()).throw(OSError('queue on fire')))
    logs = []
    st = _Stages()
    job = {'creature_options': {'source': 'scratch', 'review_gate': True}}
    cts.run_creature_training(
        job,
        'abcdef123456',
        'red dragon',
        image_paths=[],
        set_stage=st.set,
        complete_stage=st.done,
        fail_stage=st.fail,
        log_fn=lambda lvl, stage, m: logs.append((lvl, stage, m)),
        phase='full',
    )
    assert job['status'] == 'awaiting_review'
    assert not any(c[0] == 'fail' for c in st.calls)
    assert any(lvl == 'WARN' and 'review card push failed' in m for lvl, _s, m in logs)


def test_public_chain_carries_creature_options():
    for f, needle in (
        ('templates/assets/js/zpub_app.js', "fd.append('creature_options'"),
        ('zpub_routes_public.py', "'creature_options':     creature_options"),
        ('zpub_worker.py', "creature_options=job.get('creature_options')"),
        ('zpub_main_api.py', "payload['creature_options']"),
        ('templates/zero_public.html', 'id="creature-options-wrap"'),
    ):
        assert needle in open(_crews(f), encoding='utf-8').read(), f
    zm = _pure('zpub_main_api.py', ('_parse_creature_options',))
    o = zm._parse_creature_options('{"source":"scratch","review_gate":false,"angles":"compact"}')
    assert o == {'source': 'scratch', 'angles': 'compact', 'review_gate': False}


def test_letterbox_strip_and_native_reference(tmp_path):
    inner = _noise(tmp_path / 'inner.png', 11, size=(300, 160))
    im = Image.open(inner)
    boxed = Image.new('RGB', (300, 300), (12, 12, 14))
    boxed.paste(im, (0, 70))
    bp = tmp_path / 'boxed.png'
    boxed.save(bp)
    n = css.strip_letterbox(str(bp))
    assert n >= 130, n
    assert Image.open(bp).size == (300, 160)
    # a plain image is untouched, a uniform image is left to structural_check
    assert css.strip_letterbox(inner) == 0
    flat = tmp_path / 'flat.png'
    Image.new('RGB', (100, 100), (50, 50, 50)).save(flat)
    assert css.strip_letterbox(str(flat)) == 0
    ref = tmp_path / 'ref.png'
    css._prepare_reference(str(bp), str(ref))
    assert Image.open(ref).size == (300, 160)  # native aspect, no padding


def test_build_sheet_checkpoint_resume(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYG_CREATURE_VLM', '0')
    monkeypatch.setenv('ZYG_CREATURE_DINO', '0')
    calls = {'n': 0}
    fake = _fake_edit(tmp_path)

    def counting(ref, instruction, dest, seed, log, size=1024, style_hint='', **kw):
        calls['n'] += 1
        return fake(ref, instruction, dest, seed, log, size=size, style_hint=style_hint, **kw)

    monkeypatch.setattr(css, '_edit', counting)
    ref = _noise(tmp_path / 'ref.png', 21, size=(120, 80))
    ds = tmp_path / 'ds'
    ds.mkdir()
    rep1 = css.build_sheet(
        str(ds), {'name': 'P', 'description': 'x'}, source='reference', reference_paths=[ref], preset='compact'
    )
    n_first = calls['n']
    assert n_first >= 8  # anchor derivation (2) + 7 rotation cells
    assert os.path.isfile(os.path.join(str(ds), 'contact_sheet', 'anchors', 'anchors.json'))
    assert os.path.isfile(os.path.join(str(ds), 'contact_sheet', 'cells', 'cell_03.json'))
    rep2 = css.build_sheet(
        str(ds), {'name': 'P', 'description': 'x'}, source='reference', reference_paths=[ref], preset='compact'
    )
    assert calls['n'] == n_first, 'resume must render nothing when every cell is checkpointed'
    assert rep2['pass_count'] == rep1['pass_count'] == 8
    # a missing cell file is re-rendered, the rest reused
    os.remove(os.path.join(str(ds), 'contact_sheet', 'cells', 'cell_03.png'))
    css.build_sheet(
        str(ds), {'name': 'P', 'description': 'x'}, source='reference', reference_paths=[ref], preset='compact'
    )
    assert calls['n'] == n_first + 1


def test_stale_marking_and_external_pid():
    mod = _pure('char_state_service.py', ('_creature_external_pid_alive',))
    assert mod._creature_external_pid_alive({'worker': {'pid': os.getpid()}}) is True
    assert mod._creature_external_pid_alive({'worker': {'pid': 999999999}}) is False
    assert mod._creature_external_pid_alive({}) is False
    api = open(_crews('bp_pipeline_api.py'), encoding='utf-8').read()
    assert '/api/internal/creature/<creature_id>/resume' in api


@needs_checklists
def test_soft_flags_keep_strong_identity_tiles(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYG_CREATURE_DINO', '0')
    monkeypatch.setattr(css, '_edit', _fake_edit(tmp_path))
    ref = _noise(tmp_path / 'ref.png', 31, size=(120, 80))
    ds = tmp_path / 'ds'
    ds.mkdir()

    def fake_judge(jobs, offload=True, log_fn=None):
        out = {}
        for j in jobs:
            ids = [i['id'] for i in j['items']]
            # anchor/ref checks pass; for cells: flag angle on q45, whole_body on side, identity on back
            flags = []
            img = os.path.basename(j['image'])
            if 'cell_01' in img and 'angle_match' in ids:
                flags = ['angle_match']
            elif 'cell_03' in img and 'whole_body' in ids:
                flags = ['whole_body']
            elif 'cell_04' in img and 'same_creature_back' in ids:
                flags = ['same_creature_back']
            out[j['key']] = {
                'judged': True,
                'ok': not flags,
                'flags': flags,
                'criticals': [f for f in flags if f.startswith('same')],
                'majors': [f for f in flags if not f.startswith('same')],
                'verdicts': [{'id': i, 'answer': 'no' if i in flags else 'yes', 'ok': i not in flags} for i in ids],
            }
        return out

    monkeypatch.setattr(cj, 'judge_batch', fake_judge)
    monkeypatch.setattr(css, 'MAX_REGEN', 0)
    rep = css.build_sheet(
        str(ds), {'name': 'P', 'description': 'x'}, source='reference', reference_paths=[ref], preset='compact'
    )
    by = {c['idx']: c for c in rep['cells']}
    assert by[1]['ok'] and by[1]['soft'] == ['vlm:angle_match'] and by[1]['caption_mode'] == 'neutral'
    assert by[3]['ok'] and by[3]['caption_mode'] == 'partial'
    assert not by[4]['ok'] and by[4]['reasons'] == ['vlm:same_creature_back']
    assert rep['pass_count'] == 7 and rep['soft_count'] == 2
    css.training_tiles(rep, str(ds), 'ZYG_CREATURE_X', {'description': 'x', 'species': 'p'})
    cap1 = open(os.path.join(str(ds), 'training', 'sheet_01.txt')).read()
    cap3 = open(os.path.join(str(ds), 'training', 'sheet_03.txt')).read()
    assert 'alternate view of the creature' in cap1 and 'three-quarter' not in cap1
    assert 'partial view, cropped framing' in cap3
    assert not os.path.exists(os.path.join(str(ds), 'training', 'sheet_04.png'))
    # reclassify without re-judging keeps the same policy result
    rep2 = css.reclassify(str(ds), rejudge_hard=False)
    assert rep2['pass_count'] == 7 and rep2['soft_count'] == 2 and rep2.get('reclassified')


def test_split_flags_and_caption_mode():
    hard, soft = css._split_flags(['vlm:angle_match', 'identity_lost:0.1', 'vlm:no_human', 'vlm:whole_body'])
    assert hard == ['identity_lost:0.1', 'vlm:no_human'] and soft == ['vlm:angle_match', 'vlm:whole_body']
    assert css.caption_mode({'soft': soft}) == 'neutral_partial'
    assert css.caption_mode({'soft': []}) == 'angle'
