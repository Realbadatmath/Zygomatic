# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The ledger, the partials and the assets/materials catalogue."""

from zyg_workflows import arch_assistant as A
import json
import time
from zyg_workflows.test_arch_assistant.drawer import check

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def test_ledger():
    """(1) JSON-string tool arguments are coerced — the exact call that made
    Sonnet's curtain wall 'refuse' five times now works. (2) Every request
    leaves a start and an end line in the conversation ledger; a start without
    an end is closed as 'killed' at import. (3) /log and /active answer."""
    import os
    import tempfile
    import threading

    _zyg_log.info('ledger + coercion (offline)')
    # 1. coercion
    a = A._coerce_args(
        'add_curtain_wall', {'walls': '["o319", "o320"]', 'storeys': '[1, 3, 5]', 'mullion': '1.25', 'name': 'x'}
    )
    check(
        'coerce: JSON-string lists become lists, numeric strings numbers, plain strings stay',
        a['walls'] == ['o319', 'o320'] and a['storeys'] == [1, 3, 5] and a['mullion'] == 1.25 and a['name'] == 'x',
        str(a),
    )
    a = A._coerce_args('draw_box', {'storeys': '20', 'slabs': 'false', 'cell_from': 'C4', 'roof': 'flat'})
    check(
        'coerce: typed integer/boolean strings convert, enum strings untouched',
        a['storeys'] == 20 and a['slabs'] is False and a['cell_from'] == 'C4' and a['roof'] == 'flat',
        str(a),
    )
    a = A._coerce_args('add_windows', {'walls': 'tower', 'sides': '[not json'})
    check(
        'coerce: a group name and an unparsable string pass through',
        a['walls'] == 'tower' and a['sides'] == '[not json',
    )
    d = A.Drawing({'objects': []})
    A.call_tool(d, 'draw_box', {'cell_from': 'C4', 'cell_to': 'F7', 'storeys': 4, 'name': 'tower'})
    if 'add_curtain_wall' in A.TOOL_FN:
        r = A.call_tool(
            d, 'add_curtain_wall', {'walls': 'tower', 'storeys': '[1, 3]', 'mullion': 1.25, 'transom': 1.35}
        )
        cw = [o for o in d.objs if o['kind'] == 'curtain_wall']
        check(
            "coerce: Sonnet's failing call (storeys as a JSON string) now swaps exactly the odd storeys",
            r.startswith('replaced 8 wall') and len(cw) == 8,
            r[:120],
        )
    # 2. ledger, in a scratch dir
    old_dir = A.CONV_DIR
    A.CONV_DIR = tempfile.mkdtemp(prefix='arch-ledger-')
    try:
        body = {
            'text': 'ledger probe',
            'doc': {'name': 'p', 'objects': []},
            'name': 'p',
            'backend': 'anthropic',
            'history': [],
        }
        job = {
            'id': 'led1',
            'status': 'running',
            'phase': 'drawing',
            'log': ['draw_box(cell_from=C4)', '  drew', 'NOTE: x'],
            't0': time.time() - 3,
            'steps': 2,
            'question': None,
            'error': None,
            'need': None,
            'result': None,
            'reply': 'hi',
            'backend': 'claude',
            'cancel': False,
            'usage': {'in': 1},
            'session': 'abc',
            'model': 'm',
            'thinking': '',
            'thoughts': [{'text': 't1', 's': 1.5}] + [{'text': 'y' * 7000, 's': 0.5}] * 25,
            'think_s': 14.0,
            'reply_live': '',
            '_ev': threading.Event(),
            'body': body,
        }
        # the CLI transcript lives under <config>/projects/<cwd slug>/; point the config at a scratch dir and plant one
        old_cfg = os.environ.get('CLAUDE_CONFIG_DIR')
        os.environ['CLAUDE_CONFIG_DIR'] = tempfile.mkdtemp(prefix='arch-cfg-')
        old_tdir = A.TRANSCRIPT_DIR
        A.TRANSCRIPT_DIR = tempfile.mkdtemp(prefix='arch-tr-')
        SID = '99999999-8888-4777-8666-555555555555'
        src = A._transcript_src(SID)
        os.makedirs(os.path.dirname(src), exist_ok=True)
        open(src, 'w').write('{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"whole"}]}}\n')
        job['session'] = SID
        A._conv_start(job)
        job['status'] = 'done'
        job['result'] = {'summary': 'built', 'added': [1, 2], 'removed': []}
        A._conv_end(job)
        A._conv_start(dict(job, id='led2', body=dict(body, text='killed one')))  # a start with no end
        A._conv_write({'event': 'session', 'id': 'led2', 'session': SID, 'transcript': src})
        A._add_thought(
            {'id': 'led2', 'thoughts': [], 'think_s': 0}, 'z' * 5000, 3.0, lambda s: None
        )  # a thought that ended before the kill
        A._add_thought({'id': 'led2', 'thoughts': [{}], 'think_s': 3}, 'second', 1.0, lambda s: None)
        p = A._conv_path()
        rows = [json.loads(l) for l in open(p, encoding='utf-8')]
        check(
            'ledger: a start line and an end line per request',
            [r['event'] for r in rows] == ['start', 'end', 'start', 'session', 'thought', 'thought']
            and rows[0]['text'] == 'ledger probe'
            and rows[1]['status'] == 'done'
            and rows[1]['summary'] == 'built'
            and rows[1]['tool_calls'] == ['draw_box(cell_from=C4)']
            and rows[1]['thoughts'][0]['s'] == 1.5
            and rows[1]['added'] == 2
            and rows[1]['session'] == SID,
            str(rows)[:200],
        )
        check(
            'ledger: the end line keeps all 26 thoughts whole (was 20 x 1500 chars)',
            len(rows[1]['thoughts']) == 26 and len(rows[1]['thoughts'][1]['text']) == 7000,
        )
        check(
            'ledger: the end line archives the CLI transcript into the project',
            rows[1]['transcript']
            and rows[1]['transcript'].startswith(A.TRANSCRIPT_DIR)
            and os.path.exists(rows[1]['transcript'])
            and open(rows[1]['transcript']).read() == open(src).read(),
            str(rows[1].get('transcript')),
        )
        check(
            'ledger: a thought line is whole and numbered',
            rows[4]['text'] == 'z' * 5000 and rows[4]['n'] == 1 and rows[5]['n'] == 2,
        )
        n = A._close_orphans()
        rows = [json.loads(l) for l in open(p, encoding='utf-8')]
        check(
            'ledger: the orphan is closed as killed at import',
            n == 1
            and rows[-1]['event'] == 'end'
            and rows[-1]['id'] == 'led2'
            and rows[-1]['status'] == 'killed'
            and 'restart' in rows[-1]['error'],
        )
        check(
            'ledger: the killed end carries the thoughts that ended before the kill, its session and transcript',
            [t['text'] for t in rows[-1]['thoughts']] == ['z' * 5000, 'second']
            and rows[-1]['think_s'] == 4.0
            and rows[-1]['session'] == SID
            and rows[-1]['transcript']
            and os.path.exists(rows[-1]['transcript']),
            str(rows[-1])[:200],
        )
        check('ledger: closing twice adds nothing', A._close_orphans() == 0)
        out, code = A.handle_get(A.PREFIX + '/log', {'n': '10'})
        c = out['conversations']
        check(
            'ledger: /log joins start + end, newest last',
            code == 200
            and out['count'] == 2
            and c[0]['id'] == 'led1'
            and c[0]['status'] == 'done'
            and c[0]['text'] == 'ledger probe'
            and c[1]['status'] == 'killed',
            str(c)[:200],
        )
        check(
            'ledger: /log rows carry whole thoughts + session for both the done and the killed run',
            len(c[0]['thoughts']) == 26
            and c[1]['session'] == SID
            and len(c[1]['thoughts']) == 2
            and '_thoughts' not in c[1],
        )
        A._conv_start(dict(job, id='led3', body=dict(body, text='running one')))
        A._add_thought({'id': 'led3', 'thoughts': [], 'think_s': 0}, 'mid-flight', 2.0, lambda s: None)
        c = A.handle_get(A.PREFIX + '/log', {'n': '10'})[0]['conversations']
        check(
            'ledger: a run with no end yet shows its thought lines in /log',
            c[-1]['id'] == 'led3' and c[-1]['thoughts'][0]['text'] == 'mid-flight' and c[-1]['think_s'] == 2.0,
        )
        if old_cfg is None:
            os.environ.pop('CLAUDE_CONFIG_DIR', None)
        else:
            os.environ['CLAUDE_CONFIG_DIR'] = old_cfg
        A.TRANSCRIPT_DIR = old_tdir
        # a real start_job writes the start line (the thread will fail fast on the empty doc + a bad backend name)
        old_bin = A.CLI_BIN
        A.CLI_BIN = '/nonexistent/claude'  # the CLI path fails fast, no API key can be reached
        try:
            r = A.start_job({'text': 'route probe', 'doc': {'objects': []}, 'backend': 'claude'})
            for _ in range(100):
                if A.JOBS[r['id']]['status'] in ('error', 'done'):
                    break
                time.sleep(0.05)
        finally:
            A.CLI_BIN = old_bin
        rows = [json.loads(l) for l in open(p, encoding='utf-8')]
        mine = [x for x in rows if x['id'] == r['id']]
        check(
            'ledger: start_job + _run write start and end even on an error',
            [x['event'] for x in mine] == ['start', 'end'] and mine[1]['status'] == 'error' and mine[1]['error'],
            str(mine)[:200],
        )
        A.JOBS.pop(r['id'], None)
    finally:
        A.CONV_DIR = old_dir
    # 3. /active
    A.JOBS['act1'] = {'id': 'act1', 'status': 'running', 't0': time.time(), 'body': {'text': 'busy'}}
    out, code = A.handle_get(A.PREFIX + '/active', {})
    check(
        'active: counts running jobs with their text',
        code == 200 and out['running'] == 1 and out['jobs'][0]['text'] == 'busy',
    )
    A.JOBS.pop('act1', None)
    check('active: zero when idle', A.handle_get(A.PREFIX + '/active', {})[0]['running'] == 0)
    html = open(A.HERE + '/inspection.html', encoding='utf-8').read()
    check(
        'tab: a vanished job is explained as a restart', 'the server restarted while the assistant was working' in html
    )
    check(
        'tab: thoughts are stored whole (count-capped only) and the save degrades instead of dropping everything',
        "String(t.text||''), s:t.s||0" in html
        and 'slice(0,40)' in html
        and 'tries.length' in html
        and 'slice(0,1500)' in html,
    )


def test_partials():
    """2026-09-08: the thinking block that is still streaming survives a kill.
    Deltas used to reach the ledger only at content_block_stop, so a restart
    mid-block lost the whole thought. Now each block is mirrored to a throttled
    sidecar, cleared the moment it completes, and folded into the `killed` end
    line as a partial thought."""
    import os
    import tempfile
    import threading

    _zyg_log.info('partial thoughts (offline)')
    old_conv, old_part = A.CONV_DIR, A.PARTIAL_DIR
    A.CONV_DIR = tempfile.mkdtemp(prefix='arch-pconv-')
    A.PARTIAL_DIR = tempfile.mkdtemp(prefix='arch-part-')
    try:
        job = {
            'id': 'prt1',
            'status': 'running',
            'log': [],
            'steps': 0,
            'reply': '',
            'model': None,
            'cancel': False,
            'thinking': '',
            'thoughts': [],
            'think_s': 0.0,
            'reply_live': '',
            '_ev': threading.Event(),
            't0': time.time(),
            'body': {'text': 'partial probe', 'doc': {'objects': []}},
        }
        log = lambda s: job['log'].append(str(s))
        E, se = A._cli_event, lambda e: {'type': 'stream_event', 'event': e}
        side = A._partial_path('prt1')

        # 1. the sidecar appears while the block is still streaming
        E(job, se({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'thinking'}}), log)
        check('partial: no sidecar before the first delta', not os.path.exists(side))
        E(
            job,
            se({'type': 'content_block_delta', 'delta': {'type': 'thinking_delta', 'thinking': 'The user wants '}}),
            log,
        )
        check(
            'partial: the first delta is on disk at once, not held to block stop',
            os.path.exists(side) and open(side, encoding='utf-8').read().split(chr(10), 1)[1] == 'The user wants ',
        )
        head = json.loads(open(side, encoding='utf-8').read().split(chr(10), 1)[0])
        check(
            'partial: the sidecar header ties it to its job and block',
            head['id'] == 'prt1' and head['n'] == 1 and head['t0'],
        )

        # 2. throttled — a small delta inside the window does not rewrite, a big one does
        E(job, se({'type': 'content_block_delta', 'delta': {'type': 'thinking_delta', 'thinking': 'a house'}}), log)
        check(
            'partial: a small delta inside the window does not rewrite (throttled)',
            open(side, encoding='utf-8').read().endswith('The user wants ')
            and job['_think'] == 'The user wants a house',
        )
        E(job, se({'type': 'content_block_delta', 'delta': {'type': 'thinking_delta', 'thinking': 'z' * 5000}}), log)
        check(
            'partial: passing %d new characters forces a rewrite' % A.PARTIAL_FLUSH_CHARS,
            len(open(side, encoding='utf-8').read().split(chr(10), 1)[1]) == 5022,
        )

        # 3. a completed block leaves no sidecar — its whole text is a ledger line
        E(job, se({'type': 'content_block_stop', 'index': 0}), log)
        led = [json.loads(l) for l in open(A._conv_path(), encoding='utf-8')]
        check(
            'partial: block stop removes the sidecar and writes the thought whole',
            not os.path.exists(side) and led[-1]['event'] == 'thought' and len(led[-1]['text']) == 5022,
        )

        # 4. the kill: a block streaming with no stop, no end line
        A._conv_start(job)
        E(job, se({'type': 'content_block_start', 'index': 1, 'content_block': {'type': 'thinking'}}), log)
        E(job, se({'type': 'content_block_delta', 'delta': {'type': 'thinking_delta', 'thinking': 'cut mid-sen'}}), log)
        check('partial: the in-flight block is on disk when the kill lands', os.path.exists(side))
        n = A._close_orphans()
        row = [json.loads(l) for l in open(A._conv_path(), encoding='utf-8')][-1]
        check(
            'partial: the orphan is closed as killed',
            n == 1 and row['event'] == 'end' and row['id'] == 'prt1' and row['status'] == 'killed',
        )
        check(
            'partial: the killed end carries the finished thought AND the cut one, marked partial',
            [t['text'] for t in row['thoughts']] == ['The user wants a house' + 'z' * 5000, 'cut mid-sen']
            and row['thoughts'][-1].get('partial') is True
            and row['thoughts'][0].get('partial') is None
            and row['partial_thought'] is True,
            str(row['thoughts'])[:120],
        )
        check('partial: the killed end says the last thought was cut', 'cut mid-stream' in row['error'])
        check(
            'partial: the sidecar is swept once folded (it cannot be folded twice)',
            not os.path.exists(side) and A._close_orphans() == 0,
        )
        c = A.handle_get(A.PREFIX + '/log', {'n': '10'})[0]['conversations']
        check(
            'partial: /log shows the killed row with its partial thought',
            c[-1]['id'] == 'prt1' and len(c[-1]['thoughts']) == 2 and c[-1]['thoughts'][-1]['partial'] is True,
            str(c[-1])[:160],
        )

        # 5. a job that ends normally never leaves one behind
        j2 = {
            'id': 'prt2',
            'status': 'done',
            't0': time.time(),
            'log': [],
            'thoughts': [],
            '_think': 'leftover',
            '_blk_t0': time.time(),
            'body': {'text': 'x', 'doc': {'objects': []}},
            'result': None,
        }
        A._partial_write(j2, force=True)
        check('partial: force writes regardless of the throttle', os.path.exists(A._partial_path('prt2')))
        A._conv_end(j2)
        check(
            'partial: _conv_end drops the sidecar, so an ended job never looks unfinished',
            not os.path.exists(A._partial_path('prt2')),
        )

        # 6. a sidecar nothing will ever fold is swept
        stale = A._partial_path('prt3')
        open(stale, 'w').write('{}' + chr(10) + 'orphaned forever')
        os.utime(stale, (time.time() - 3 * 86400, time.time() - 3 * 86400))
        A._partial_sweep()
        check('partial: a sidecar older than the orphan window is swept', not os.path.exists(stale))
        check('partial: an empty sidecar reads as nothing to fold', A._partial_read('nosuchjob') is None)
    finally:
        A.CONV_DIR, A.PARTIAL_DIR = old_conv, old_part


def test_assets_materials():
    """2026-09-07 asset library work: every pack item carries a measured size
    (mesh_pack_dims.py), Poly Haven items carry search notes, the assistant's
    `material` arguments accept library ids via search_materials, and the new
    packs (house furniture CC-BY, Sprite Fright CC-BY, MPFB figures CC0) pass
    the licence gate with real dimensions."""
    import os
    from zyg_workflows import mesh_pack_dims as MD
    from zyg_workflows import architecture_assets as AA

    _zyg_log.info('assets + materials')
    d = A.Drawing({'objects': []})
    r = A.call_tool(d, 'search_assets', {'query': 'sofa', 'limit': 6})
    check(
        'assets: search shows measured sizes, not 1x1x1',
        '1x1x1 m' not in r and 'polyhaven_arch|sofa_02_2k' in r and '1.807x0.71x0.818 m' in r,
        r[:200],
    )
    r = A.call_tool(d, 'search_assets', {'query': 'street lamp', 'limit': 3})
    check('assets: a street lamp is 3.9 m tall in the results', '3.871' in r, r[:200])
    p = os.path.join(AA.PACKS_ROOT, 'polyhaven_arch', 'sofa_02', 'sofa_02_2k.gltf')
    m = MD.measure(p) if os.path.exists(p) else None
    check(
        "dims: the measurer matches Poly Haven's published size (1807 x 818 x 709 mm)",
        m is not None and abs(m[0] - 1.807) < 0.01 and abs(m[1] - 0.7095) < 0.01 and abs(m[2] - 0.818) < 0.01,
        str(m),
    )
    cat = AA.catalogue()
    n_items = cat['count']
    n_dims = sum(1 for g in cat['groups'] for it in g['items'] if 'bw' in (it.get('p') or {}))
    check(
        'dims: nearly every catalogued item carries a size',
        n_items > 7000 and n_dims >= n_items * 0.97,
        f'{n_dims}/{n_items}',
    )
    ph = next((it for g in cat['groups'] for it in g['items'] if it['id'] == 'polyhaven_arch|fir_tree_01_2k'), None)
    check(
        'notes: Poly Haven items carry category/tag words for search',
        ph is not None and 'tree' in (ph.get('note') or ''),
        str(ph)[:160],
    )
    # materials
    r = A.call_tool(d, 'search_materials', {'query': 'rough concrete', 'limit': 4})
    ids = [l.split(' — ')[0] for l in r.splitlines()[1:]]
    check(
        'materials: search_materials finds library surfaces with a tile size',
        ids and ids[0].startswith(('pht_', 'acg_')) and ' m' in r,
        r[:160],
    )
    check(
        'materials: MATERIALS accepts a library id, a preset, and refuses junk',
        ids[0] in A.MATERIALS
        and 'mat_brick' in A.MATERIALS
        and 'acg_nope' not in A.MATERIALS
        and 'granite' not in A.MATERIALS,
    )
    A.call_tool(d, 'draw_box', {'cell_from': 'C4', 'cell_to': 'F7', 'storeys': 1, 'material': ids[0]})
    check('materials: a library id lands on the walls', all(o['mat'] == ids[0] for o in d.objs if o['kind'] == 'wall'))
    enums = [
        k
        for t in A.TOOL_DEFS
        for k, pr in ((t.get('input_schema') or {}).get('properties') or {}).items()
        if isinstance(pr, dict) and pr.get('enum') and 'mat_concrete' in pr['enum']
    ]
    check('materials: no tool schema still restricts material to the presets', not enums, str(enums)[:100])
    check('materials: MATERIALS still lists only the presets (prompt stays short)', len(list(A.MATERIALS)) == 21)
    # new packs
    packs = {p['id']: p for p in cat['packs']}
    house = packs.get('lynxsdesign/house_41')
    check(
        'packs: the 4.1 house furniture pack is listed, CC-BY with attribution flag, 21 items',
        house is not None and house['attrib'] and house['count'] == 21,
        str(house)[:160],
    )
    fig = packs.get('human_bases/mpfb_scale_figures')
    check(
        'packs: the MPFB scale figures are listed as CC0, 20 items',
        fig is not None and not fig['attrib'] and fig['count'] == 20,
        str(fig)[:160],
    )
    r = A.call_tool(d, 'search_assets', {'query': 'man average figure', 'limit': 4})
    check(
        'packs: a scale figure comes back at human height',
        'mpfb_scale_figures|man_average' in r and 'x1.729x' in r,
        r[:200],
    )
    refused = [x for x in cat['refused'] if any(k in x['pack'] for k in ('lynxsdesign', 'blender_studio', 'mpfb'))]
    check('packs: none of the new packs is refused by the licence gate', not refused, str(refused)[:160])
