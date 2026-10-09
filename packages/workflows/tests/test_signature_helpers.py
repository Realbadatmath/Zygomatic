# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the stages build_signature was split into.

Every test here pins one behaviour the single 564-line function used to have:
the contract keys it publishes, which gates each clip is measured against, how
it attributes a failing region between the render and the post-process, which
chain link it blames, what an already-executed alternative proves, how a pin's
overlap with a failing region is reported, where lost motion is discovered
without any named region, and how the probe / lora tail is normalised.
No clip is decoded — `measure_clip` / `motion_loss_map` are replaced and the
measurement dicts are handed in as plain data.
"""

import json
import os

from zyg_workflows.self_improve import signature_stages as ST


def _region(flow_norm, ok, *, gate=0.1, flow_ok=None):
    """A delivered/raw region measurement as measure_clip() returns one."""
    return {
        'flow_norm': flow_norm,
        'flow_mean': flow_norm * 2.0,
        'flow_p95': flow_norm + 0.1,
        'churn_mean': 0.5,
        'churn_p95': 0.9,
        'ok': ok,
        'flow_ok': ok if flow_ok is None else flow_ok,
        'gate_min_flow': gate,
        'gate_max_churn': 3.0,
    }


def _prop(name, ncc_min, ok, *, box=(0.0, 0.0, 0.5, 0.5), gate=0.8):
    """A prop measurement with one seam pair."""
    return {
        'box': list(box),
        'ncc_min': ncc_min,
        'ncc_max': ncc_min + 0.05,
        'gate_ncc_min': gate,
        'ok': ok,
        'pairs': [{'t0': 1.0, 't1': 2.0, 'ncc': ncc_min, 'ok': ok}],
    }


def _step(file, step, *, family='post', variant_of=None, keep_mask=None, path=None):
    """One detected chain link."""
    return {
        'file': file,
        'path': path or f'/runs/{file}',
        'step': step,
        'family': family,
        'variant_of': variant_of,
        'param_key': f'{step}.enabled',
        'disable_value': False,
        'keep_mask': keep_mask,
    }


# ── new_signature ───────────────────────────────────────────────────────────


def test_new_signature_publishes_the_whole_contract_surface():
    sig = ST.new_signature('/runs/scene20_v8', {'steps': 30})
    for key in ('gates', 'regions', 'props', 'keep_boxes', 'chain', 'deltas', 'params'):
        assert key in sig, key
    assert sig['schema'] == 'zyg.signature/1'
    assert sig['run_name'] == 'scene20_v8'
    assert sig['ok'] is False
    assert sig['facts'] == [] and sig['failures'] == []


def test_new_signature_copies_params_instead_of_aliasing_them():
    params = {'steps': 30}
    sig = ST.new_signature('/runs/x', params)
    sig['params']['steps'] = 1
    assert params['steps'] == 30


# ── resolve_inputs ──────────────────────────────────────────────────────────


def test_resolve_inputs_refuses_a_run_dir_without_a_delivered_clip(tmp_path):
    (tmp_path / 'qc_spec.json').write_text(json.dumps({'regions': {'hand': [0, 0, 1, 1]}}), encoding='utf-8')
    sig = ST.new_signature(str(tmp_path), None)
    lines = []
    assert ST.resolve_inputs(sig, str(tmp_path), None, None, None, None, lines.append) is None
    assert 'no delivered clip found' in sig['error']
    assert sig['clip'] is None
    assert sig['qc_spec']['regions'] == {'hand': [0, 0, 1, 1]}
    assert any('no delivered clip' in line for line in lines)


# ── collect_keep_boxes ──────────────────────────────────────────────────────


def test_collect_keep_boxes_normalises_caller_boxes_to_records():
    sig = ST.new_signature('/runs/x', None)
    kb = ST.collect_keep_boxes(sig, '/runs/x', {}, {'lamp': (0.1, 0.1, 0.4, 0.4)}, lambda _m: None)
    assert kb['lamp'] == {'box': [0.1, 0.1, 0.4, 0.4], 'source': 'caller'}
    assert sig['keep_boxes'] == {'lamp': [0.1, 0.1, 0.4, 0.4]}  # contract shape
    assert sig['keep_boxes_detail'] is kb


# ── region_motion_facts / record_region_deltas ──────────────────────────────


def test_region_motion_facts_blames_the_postprocess_when_raw_passed():
    sig = ST.new_signature('/runs/x', None)
    delivered, raw = _region(0.080, False), _region(0.254, True)
    ST.region_motion_facts(sig, 'abel_hand', delivered, raw, {'pct': -68.5}, 0.1, True)
    namespaces = [f['ns'] for f in sig['facts']]
    assert namespaces == ['gate.fail', 'motion.lost_in_postprocess']
    assert sig['failures'][0]['region'] == 'abel_hand'
    assert sig['failures'][0]['why'] == 'flow'
    assert sig['failures'][0]['margin'] == -0.02


def test_region_motion_facts_blames_the_sampler_when_the_raw_render_failed_too():
    sig = ST.new_signature('/runs/x', None)
    ST.region_motion_facts(sig, 'hand', _region(0.02, False), _region(0.03, False), {}, 0.1, True)
    assert [f['ns'] for f in sig['facts']] == ['gate.fail', 'motion.frozen_at_source']


def test_region_motion_facts_says_so_when_no_raw_render_can_attribute_it():
    sig = ST.new_signature('/runs/x', None)
    ST.region_motion_facts(sig, 'hand', _region(0.02, False), None, {}, 0.1, False)
    assert [f['ns'] for f in sig['facts']] == ['gate.fail', 'motion.failed_no_raw']


def test_region_motion_facts_stay_silent_on_a_passing_region():
    sig = ST.new_signature('/runs/x', None)
    ST.region_motion_facts(sig, 'hand', _region(0.4, True), _region(0.5, True), {}, 0.1, True)
    assert sig['facts'] == [] and sig['failures'] == []


def test_record_region_deltas_fills_the_contract_and_the_delta_columns():
    sig = ST.new_signature('/runs/x', None)
    ctx = ST.SignatureInputs(
        meta={},
        spec={'roles': {'abel_hand': 'motion'}},
        regions={'abel_hand': (0.1, 0.2, 0.3, 0.4)},
        min_flow=None,
        max_churn=None,
        ncc_min=None,
        prop_pairs=None,
        chain=[],
        clip_path='/runs/x/out.mp4',
        raw_clip='/runs/x/raw.mp4',
    )
    m_del = {'regions': {'abel_hand': _region(0.080, False)}}
    m_raw = {'regions': {'abel_hand': _region(0.254, True)}}
    ST.record_region_deltas(sig, ctx, m_del, m_raw)
    rec = sig['region_deltas']['abel_hand']
    assert rec['delivered'] == 0.080 and rec['raw'] == 0.254
    assert rec['delta'] == -0.174 and rec['pct'] == -68.5
    assert sig['regions']['abel_hand']['flow_mean'] == 0.080  # NORMALISED, not px
    assert sig['regions']['abel_hand']['flow_mean_px'] == 0.160
    assert sig['regions']['abel_hand']['role'] == 'motion'
    assert sig['regions']['abel_hand']['box'] == [0.1, 0.2, 0.3, 0.4]
    assert sig['gates']['region_flow:abel_hand'] == {'ok': False, 'score': 0.080, 'threshold': 0.1}
    assert sig['deltas']['region_flow:abel_hand'] == {'before': 0.254, 'after': 0.080}


def test_record_region_deltas_skips_a_region_the_clip_never_measured():
    sig = ST.new_signature('/runs/x', None)
    ctx = ST.SignatureInputs(
        meta={},
        spec={},
        regions={'absent': (0, 0, 1, 1)},
        min_flow=None,
        max_churn=None,
        ncc_min=None,
        prop_pairs=None,
        chain=[],
        clip_path='/runs/x/out.mp4',
        raw_clip=None,
    )
    ST.record_region_deltas(sig, ctx, {'regions': {}}, None)
    assert sig['region_deltas'] == {} and sig['regions'] == {}


# ── worsened_regions / record_chain_deltas ──────────────────────────────────


def test_worsened_regions_only_reports_a_region_pushed_across_its_gate():
    ma = {'regions': {'hand': _region(0.254, True), 'face': _region(0.30, True)}}
    mb = {'regions': {'hand': _region(0.080, False), 'face': _region(0.25, True)}}
    worsened = ST.worsened_regions(ma, mb, {'hand': (0, 0, 1, 1), 'face': (0, 0, 1, 1), 'gone': (0, 0, 1, 1)})
    assert [w['region'] for w in worsened] == ['hand']
    assert worsened[0] == {
        'region': 'hand',
        'before': 0.254,
        'after': 0.080,
        'drop': 0.174,
        'pct': -68.5,
        'crossed_gate': True,
    }


def test_worsened_regions_reports_no_pct_when_the_before_value_is_zero():
    ma = {'regions': {'hand': _region(0.0, True)}}
    mb = {'regions': {'hand': _region(0.0, False)}}
    assert ST.worsened_regions(ma, mb, {'hand': (0, 0, 1, 1)})[0]['pct'] is None


def test_record_chain_deltas_indicts_the_pinning_step_in_its_own_namespace(monkeypatch):
    sig = ST.new_signature('/runs/x', None)
    chain = [_step('a_raw.mp4', 'render'), _step('b_pin.mp4', 'keep_composite', keep_mask='mask.png')]
    ctx = ST.SignatureInputs(
        meta={},
        spec={},
        regions={'hand': (0, 0, 1, 1)},
        min_flow=None,
        max_churn=None,
        ncc_min=None,
        prop_pairs=None,
        chain=chain,
        clip_path='/runs/b_pin.mp4',
        raw_clip='/runs/a_raw.mp4',
    )
    m_raw = {'ok': True, 'regions': {'hand': _region(0.254, True)}}
    m_del = {'ok': True, 'regions': {'hand': _region(0.080, False)}}
    monkeypatch.setattr(ST, 'measure_clip', lambda *a, **k: (_ for _ in ()).throw(AssertionError('decoded a clip')))
    ST.record_chain_deltas(sig, ctx, m_del, m_raw, '/runs', lambda _m: None)
    assert len(sig['chain_deltas']) == 1
    link = sig['chain_deltas'][0]
    assert (link['from'], link['to'], link['step']) == ('a_raw.mp4', 'b_pin.mp4', 'keep_composite')
    assert [f['ns'] for f in sig['facts']] == ['chain.step_destructive_pinning']
    assert 'keep mask' in sig['facts'][0]['note']


def test_measure_main_chain_reuses_the_two_clips_already_measured():
    ctx = ST.SignatureInputs(
        meta={},
        spec={},
        regions={},
        min_flow=None,
        max_churn=None,
        ncc_min=None,
        prop_pairs=None,
        chain=[],
        clip_path='/runs/b.mp4',
        raw_clip='/runs/a.mp4',
    )
    chain = [_step('a.mp4', 'render', path='/runs/a.mp4'), _step('b.mp4', 'post', path='/runs/b.mp4')]
    m_del, m_raw = {'ok': True, 'tag': 'delivered'}, {'ok': True, 'tag': 'raw'}
    measured = ST.measure_main_chain(chain, ctx, m_del, m_raw, '/runs', lambda _m: None)
    assert measured == {'a.mp4': m_raw, 'b.mp4': m_del}


# ── measure_clips ───────────────────────────────────────────────────────────


def test_measure_clips_probes_every_pin_as_a_raw_region_with_a_permissive_gate(tmp_path, monkeypatch):
    delivered = tmp_path / 'out.mp4'
    raw = tmp_path / 'raw.mp4'
    for p in (delivered, raw):
        p.write_bytes(b'')
    sig = ST.new_signature(str(tmp_path), None)
    ctx = ST.SignatureInputs(
        meta={},
        spec={'prop_boxes': {'mug': [0.9, 0.9, 1.0, 1.0]}},
        regions={'hand': (0.2, 0.2, 0.3, 0.3)},
        min_flow={'hand': 0.1},
        max_churn={'hand': 3.0},
        ncc_min=0.8,
        prop_pairs=[[1.0, 2.0]],
        chain=[],
        clip_path=str(delivered),
        raw_clip=str(raw),
    )
    calls = []

    def _fake_measure(path, regions, min_flow, max_churn, prop_boxes, prop_pairs, ncc_min, **kw):
        calls.append(
            {
                'path': path,
                'regions': dict(regions),
                'min_flow': min_flow,
                'max_churn': max_churn,
                'prop_boxes': dict(prop_boxes or {}),
                'cache_dir': kw.get('cache_dir'),
            }
        )
        return {'ok': True, 'tag': os.path.basename(path)}

    monkeypatch.setattr(ST, 'measure_clip', _fake_measure)
    m_del, m_raw = ST.measure_clips(sig, ctx, {'lamp': {'box': [0.1, 0.1, 0.4, 0.4]}}, str(tmp_path), lambda _m: None)

    assert (m_del['tag'], m_raw['tag']) == ('out.mp4', 'raw.mp4')
    assert sig['metrics']['delivered'] is m_del and sig['metrics']['raw'] is m_raw
    # the pin is a PROP on both clips...
    assert calls[0]['prop_boxes'] == {'mug': [0.9, 0.9, 1.0, 1.0], 'keep:lamp': [0.1, 0.1, 0.4, 0.4]}
    assert calls[1]['prop_boxes'] == calls[0]['prop_boxes']
    # ...and an extra FLOW region on the raw clip only, gated so it can never fail
    assert set(calls[0]['regions']) == {'hand'}
    assert calls[1]['regions']['keep:lamp'] == (0.1, 0.1, 0.4, 0.4)
    assert calls[1]['min_flow'] == {'hand': 0.1, 'keep:lamp': 0.0}
    assert calls[1]['max_churn'] == {'hand': 3.0, 'keep:lamp': 9.0}
    assert ctx.min_flow == {'hand': 0.1}  # the caller's gates are copied, never widened
    assert calls[0]['cache_dir'] == str(tmp_path)


def test_measure_clips_skips_the_raw_pass_when_no_raw_render_is_on_disk(tmp_path, monkeypatch):
    delivered = tmp_path / 'out.mp4'
    delivered.write_bytes(b'')
    sig = ST.new_signature(str(tmp_path), None)
    ctx = ST.SignatureInputs(
        meta={},
        spec={},
        regions={},
        min_flow=None,
        max_churn=None,
        ncc_min=None,
        prop_pairs=None,
        chain=[],
        clip_path=str(delivered),
        raw_clip=str(tmp_path / 'absent.mp4'),
    )
    monkeypatch.setattr(ST, 'measure_clip', lambda *a, **k: {'ok': True})
    m_del, m_raw = ST.measure_clips(sig, ctx, {}, str(tmp_path), lambda _m: None)
    assert m_del == {'ok': True} and m_raw is None
    assert 'raw' not in sig['metrics']


# ── record_variant_evidence ─────────────────────────────────────────────────


def _variant_ctx(chain):
    """A context whose chain is the only thing record_variant_evidence reads."""
    return ST.SignatureInputs(
        meta={},
        spec={},
        regions={'hand': (0, 0, 1, 1)},
        min_flow=None,
        max_churn=None,
        ncc_min=None,
        prop_pairs=None,
        chain=chain,
        clip_path='/runs/out.mp4',
        raw_clip=None,
    )


def test_record_variant_evidence_keys_a_failed_alternative_by_family(monkeypatch):
    sig = ST.new_signature('/runs/x', None)
    chain = [
        _step('out.mp4', 'post'),
        _step('alt_pin.mp4', 'keep_composite', family='pinning', variant_of='out.mp4'),
    ]
    monkeypatch.setattr(ST, 'measure_clip', lambda *a, **k: {'ok': True, 'regions': {'hand': _region(0.02, False)}})
    ST.record_variant_evidence(sig, _variant_ctx(chain), '/runs/x', lambda _m: None)
    assert len(sig['facts']) == 1  # the non-variant link is never re-measured
    fact = sig['facts'][0]
    assert fact['ns'] == 'variant.tried_and_failed'
    assert fact['args'] == {'family': 'pinning'}  # the SLOT, not the artifact name
    assert fact['evidence']['failing'] == ['hand']
    assert 'do not propose that alternative again' in fact['note']


def test_record_variant_evidence_records_an_alternative_that_passes(monkeypatch):
    sig = ST.new_signature('/runs/x', None)
    chain = [_step('alt.mp4', 'post', family='post', variant_of='out.mp4')]
    monkeypatch.setattr(ST, 'measure_clip', lambda *a, **k: {'ok': True, 'regions': {'hand': _region(0.4, True)}})
    ST.record_variant_evidence(sig, _variant_ctx(chain), '/runs/x', lambda _m: None)
    assert [f['ns'] for f in sig['facts']] == ['variant.tried_and_passed']
    assert sig['facts'][0]['evidence']['failing'] == []


def test_record_variant_evidence_ignores_a_variant_that_could_not_be_measured(monkeypatch):
    sig = ST.new_signature('/runs/x', None)
    chain = [_step('alt.mp4', 'post', variant_of='out.mp4')]
    monkeypatch.setattr(ST, 'measure_clip', lambda *a, **k: {'ok': False, 'error': 'unreadable'})
    ST.record_variant_evidence(sig, _variant_ctx(chain), '/runs/x', lambda _m: None)
    assert sig['facts'] == []


# ── keep boxes ──────────────────────────────────────────────────────────────


def test_keep_box_raw_probe_calls_a_pin_unnecessary_when_raw_ncc_holds():
    sig = ST.new_signature('/runs/x', None)
    kv = {'box': [0.1, 0.1, 0.4, 0.4], 'source': 'metadata'}
    m_raw = {'regions': {'keep:lamp': _region(0.01, False)}, 'props': {'keep:lamp': _prop('keep:lamp', 0.95, True)}}
    ST.keep_box_raw_probe(sig, 'lamp', kv, (0.1, 0.1, 0.4, 0.4), m_raw, 0.05)
    assert kv['contains_motion'] is False
    assert kv['pin_unnecessary'] is True
    assert kv['raw_ncc_min'] == 0.95
    assert [f['ns'] for f in sig['facts']] == ['keep.pin_unnecessary']


def test_keep_box_raw_probe_reports_real_motion_under_a_pin():
    sig = ST.new_signature('/runs/x', None)
    kv = {'box': [0.1, 0.1, 0.4, 0.4], 'source': 'mask'}
    m_raw = {'regions': {'keep:hand': _region(0.30, True)}, 'props': {'keep:hand': _prop('keep:hand', 0.40, False)}}
    ST.keep_box_raw_probe(sig, 'hand', kv, (0.1, 0.1, 0.4, 0.4), m_raw, 0.05)
    assert kv['contains_motion'] is True
    assert [f['ns'] for f in sig['facts']] == ['keep.contains_motion', 'keep.pin_justified']


def test_keep_box_overlap_facts_report_a_failing_region_inside_the_pin():
    sig = ST.new_signature('/runs/x', None)
    sig['failures'] = [{'region': 'hand'}, {'region': 'unknown'}]
    ST.keep_box_overlap_facts(sig, {'hand': (0.2, 0.2, 0.3, 0.3)}, 'lamp', (0.1, 0.1, 0.5, 0.5))
    assert [f['ns'] for f in sig['facts']] == ['keep.covers_failing_region']
    ev = sig['facts'][0]['evidence']
    assert ev['region_frac_inside_keep'] == 1.0
    assert ev['shrink_to']  # concrete remainder strips, not "make it smaller"


def test_keep_box_overlap_facts_ignore_a_pin_that_misses_the_failing_region():
    sig = ST.new_signature('/runs/x', None)
    sig['failures'] = [{'region': 'hand'}]
    ST.keep_box_overlap_facts(sig, {'hand': (0.8, 0.8, 0.9, 0.9)}, 'lamp', (0.1, 0.1, 0.2, 0.2))
    assert sig['facts'] == []


def test_interrogate_keep_boxes_leaves_both_verdicts_unknown_without_a_raw_render():
    sig = ST.new_signature('/runs/x', None)
    sig['failures'] = [{'region': 'hand'}]
    kb = {'lamp': {'box': [0.1, 0.1, 0.5, 0.5], 'source': 'metadata'}}
    ctx = _variant_ctx([])
    ctx.regions = {'hand': (0.2, 0.2, 0.3, 0.3)}
    ST.interrogate_keep_boxes(sig, ctx, kb, None, 0.05)
    # unknown, never guessed as False — a missing raw render is not evidence
    assert kb['lamp']['contains_motion'] is None
    assert kb['lamp']['pin_unnecessary'] is None
    assert 'raw_flow' not in kb['lamp']
    assert [f['ns'] for f in sig['facts']] == ['keep.covers_failing_region']


def test_interrogate_keep_boxes_probes_the_raw_clip_and_then_the_overlap():
    sig = ST.new_signature('/runs/x', None)
    sig['failures'] = [{'region': 'hand'}]
    kb = {'lamp': {'box': [0.1, 0.1, 0.5, 0.5], 'source': 'mask'}}
    ctx = _variant_ctx([])
    ctx.regions = {'hand': (0.2, 0.2, 0.3, 0.3)}
    m_raw = {
        'regions': {'keep:lamp': _region(0.30, True)},
        'props': {'keep:lamp': _prop('keep:lamp', 0.95, True)},
    }
    ST.interrogate_keep_boxes(sig, ctx, kb, m_raw, 0.05)
    assert kb['lamp']['contains_motion'] is True
    assert kb['lamp']['pin_unnecessary'] is True
    assert [f['ns'] for f in sig['facts']] == [
        'keep.contains_motion',
        'keep.pin_unnecessary',
        'keep.covers_failing_region',
    ]


# ── record_motion_loss_discovery ────────────────────────────────────────────


def test_record_motion_loss_discovery_blames_the_pin_a_lost_cluster_sits_in(tmp_path, monkeypatch):
    raw = tmp_path / 'raw.mp4'
    raw.write_bytes(b'')
    sig = ST.new_signature(str(tmp_path), None)
    ctx = _variant_ctx([])
    ctx.raw_clip = str(raw)
    ctx.clip_path = str(tmp_path / 'out.mp4')
    ml = {
        'ok': True,
        'boxes': [{'box': [0.2, 0.2, 0.3, 0.3], 'drop_frac': 0.68, 'raw': 0.254, 'delivered': 0.080}],
    }
    monkeypatch.setattr(ST, 'motion_loss_map', lambda a, b, **k: ml)
    ST.record_motion_loss_discovery(sig, ctx, {'lamp': {'box': [0.1, 0.1, 0.5, 0.5]}}, lambda _m: None)
    assert sig['motion_loss'] is ml
    assert [f['ns'] for f in sig['facts']] == ['discovery.motion_lost', 'discovery.motion_lost_inside_pin']
    assert sig['facts'][0]['args'] == {'box': '0.2x0.2x0.3x0.3'}
    assert sig['facts'][0]['evidence']['inside_keep'] == [{'keep': 'lamp', 'frac': 1.0}]
    assert '68%' in sig['facts'][0]['note']
    assert sig['facts'][1]['args'] == {'keep': 'lamp'}


def test_record_motion_loss_discovery_reports_an_unpinned_cluster_on_its_own(tmp_path, monkeypatch):
    raw = tmp_path / 'raw.mp4'
    raw.write_bytes(b'')
    sig = ST.new_signature(str(tmp_path), None)
    ctx = _variant_ctx([])
    ctx.raw_clip = str(raw)
    ctx.clip_path = str(tmp_path / 'out.mp4')
    boxes = [{'box': [0.8, 0.8, 0.9, 0.9], 'drop_frac': 0.5, 'raw': 0.2, 'delivered': 0.1}] * 6
    monkeypatch.setattr(ST, 'motion_loss_map', lambda a, b, **k: {'ok': True, 'boxes': boxes})
    ST.record_motion_loss_discovery(sig, ctx, {'lamp': {'box': [0.1, 0.1, 0.2, 0.2]}}, lambda _m: None)
    assert [f['ns'] for f in sig['facts']] == ['discovery.motion_lost'] * 4  # only the four biggest clusters
    assert sig['facts'][0]['evidence']['inside_keep'] == []
    assert 'inside pin' not in sig['facts'][0]['note']


def test_record_motion_loss_discovery_does_nothing_without_a_raw_render():
    sig = ST.new_signature('/runs/x', None)
    ctx = _variant_ctx([])
    ctx.raw_clip = None
    ST.record_motion_loss_discovery(sig, ctx, {}, lambda _m: None)
    assert sig['facts'] == [] and 'motion_loss' not in sig


# ── props ───────────────────────────────────────────────────────────────────


def test_record_props_marks_a_prop_pinned_by_name_and_by_overlap():
    sig = ST.new_signature('/runs/x', None)
    kb = {'lamp': {'box': [0.0, 0.0, 0.5, 0.5]}}
    m_del = {
        'props': {
            'keep:lamp': _prop('keep:lamp', 0.9, True, box=(0.0, 0.0, 0.5, 0.5)),
            'mug': _prop('mug', 0.6, False, box=(0.0, 0.0, 0.5, 0.5)),
            'sky': _prop('sky', 0.95, True, box=(0.9, 0.9, 1.0, 1.0)),
        }
    }
    m_raw = {'props': {'keep:lamp': _prop('keep:lamp', 0.5, False)}}
    ST.record_props(sig, kb, m_del, m_raw)
    assert set(sig['props']) == {'lamp', 'mug', 'sky'}  # keep: prefix stripped for the KB join
    assert sig['props']['lamp']['pinned'] is True  # by name
    assert sig['props']['mug']['pinned'] is True  # by overlap with the pin
    assert sig['props']['sky']['pinned'] is False
    assert sig['props']['lamp']['min_ncc'] == 0.9 and sig['props']['lamp']['ncc_min'] == 0.8  # value vs GATE
    assert sig['props']['lamp']['raw_min_ncc'] == 0.5
    assert sig['gates']['prop_ncc:mug'] == {'ok': False, 'score': 0.6, 'threshold': 0.8}
    assert sig['deltas']['prop_ncc:lamp'] == {'before': 0.5, 'after': 0.9}


def test_record_prop_morphs_facts_only_failing_non_keep_props():
    sig = ST.new_signature('/runs/x', None)
    m_del = {
        'props': {
            'keep:lamp': _prop('keep:lamp', 0.1, False),
            'mug': _prop('mug', 0.42, False),
            'sky': _prop('sky', 0.99, True),
        }
    }
    ST.record_prop_morphs(sig, m_del)
    assert [f['args']['prop'] for f in sig['facts']] == ['mug']
    assert sig['facts'][0]['ns'] == 'prop.morph_at_seam'
    assert 'ncc 0.42' in sig['facts'][0]['note']


# ── the contract tail: probe / run / loras ──────────────────────────────────


def test_probe_block_maps_each_verdict_to_the_contract_vocabulary():
    assert ST.probe_block({'skipped': True, 'verdict': 'PASS'})['verdict'] == 'skipped'
    assert ST.probe_block({'verdict': 'FROZEN hand'})['verdict'] == 'frozen'
    assert ST.probe_block({'verdict': 'PASS (all regions)'})['verdict'] == 'ok'
    assert ST.probe_block({'verdict': 'weird'})['verdict'] == 'weird'
    assert 'context_windows' not in ST.probe_block({'verdict': 'PASS'})
    assert ST.probe_block({'verdict': 'PASS', 'context_windows': 3})['context_windows'] == 3


def test_lora_block_normalises_pairs_and_dicts_and_sums_the_weight():
    assert ST.lora_block({}) is None
    block = ST.lora_block({'loras': [('abel', '0.8'), {'name': 'city', 'scale': 0.25, 'trained_on': 'v3'}]})
    assert block['total_weight'] == 1.05
    assert block['items'][0] == {'name': 'abel', 'scale': 0.8}
    assert block['items'][1]['trained_on'] == 'v3'


def test_record_contract_tail_reads_the_probe_report_and_the_run_block(tmp_path):
    (tmp_path / 'probe_report.json').write_text(json.dumps({'verdict': 'PASS'}), encoding='utf-8')
    sig = ST.new_signature(str(tmp_path), {'render.context_windows': 2, 'config_proven': True, 'loras': []})
    ST.record_contract_tail(sig, str(tmp_path))
    assert sig['probe'] == {'skipped': False, 'verdict': 'ok'}
    assert sig['run'] == {'context_windows': 2, 'config_proven': True}
    assert sig['loras'] == {'total_weight': 0.0, 'items': []}


def test_record_contract_tail_invents_nothing_without_a_probe_report(tmp_path):
    sig = ST.new_signature(str(tmp_path), {})
    ST.record_contract_tail(sig, str(tmp_path))
    assert 'probe' not in sig and 'run' not in sig and 'loras' not in sig
