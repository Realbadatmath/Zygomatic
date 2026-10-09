# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_icon_probe.py — proves the ICON seam end to end on the
worked example (s_last): the placeholder mark is gone in the live DOM, the icon
does its job under arTool, the assistant may press it (and pass args), the
server-ext route answers JSON and downloads, and doc.ext / record meta survive
both the tab and the assistant's Drawing."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, browser_eval, icon_state, server_ext  # noqa: E402

st = icon_state(['s_last'])
check(
    's_last is in the dock and no longer a placeholder (no stub flag, no dashed class, no [placeholder] tip)',
    st['s_last'].get('exists')
    and not st['s_last'].get('stub')
    and not st['s_last'].get('dashed')
    and not st['s_last'].get('tip_placeholder'),
    st,
)

r = browser_eval("""() => {
  const a = arNewObj('slab', {w:2, d:2, t:0.2}, 0, 0, 0), b = arNewObj('slab', {w:2, d:2, t:0.2}, 5, 0, 0);
  arSelect([a.id]); arSelect([b.id]);
  arTool('s_last'); const back = AR.sel.slice();
  arTool('s_last'); const fwd = AR.sel.slice();
  return {a: a.id, b: b.id, back: back, fwd: fwd, toast: document.getElementById('ar-toast').innerHTML};
}""")
v = r['value']
check('pressing Previous restores the earlier selection', v['back'] == [v['a']], v)
check('pressing it again comes forward', v['fwd'] == [v['b']], v)
check('the press toasts what it did', 'Selection restored' in v['toast'], v['toast'])
check('no page errors while pressing', not r['errors'], r['errors'])

txt, d = assistant('press_button', {'id': 's_last'})
check(
    'assistant may press s_last (EXT_BUTTONS)',
    txt.startswith('pressed') and d.ui and d.ui[-1]['args']['id'] == 's_last',
    txt,
)
txt2, d2 = assistant('press_button', {'id': 's_last', 'args': {'n': 1}})
check('press_button carries args to the tab', d2.ui[-1]['args'].get('args') == {'n': 1}, d2.ui)
txt3, _ = assistant('press_button', {'id': 'no_such_icon'})
check('unknown icons are still refused', txt3.startswith('refused'), txt3)

p = server_ext('icon_probe', 'ping', {'a': 1})
check('server ext POST answers JSON', p.get('ok') and p.get('echo') == {'a': 1} and p.get('method') == 'POST', p)
g = server_ext('icon_probe', 'ping', {'q': 'x'}, method='GET')
check('server ext GET answers JSON', g.get('ok') and (g.get('echo') or {}).get('q') == 'x', g)
t = server_ext('icon_probe', 'text', {'name': 'seam'})
check('a tuple result is sent as a download', t.get('bytes') == b'hello seam' and t.get('filename') == 'hello.txt', t)
u = server_ext('icon_probe', 'nope', {})
check('an unknown op is a 404', u.get('code') == 404, u)

txt4, d4 = assistant(
    'get_state',
    {},
    doc={
        'objects': [{'id': 'o1', 'kind': 'slab', 'p': {'w': 2, 'd': 2, 't': 0.2}, 'meta': {'layer': 'A'}}],
        'ext': {'units': 'mm'},
    },
)
check(
    'the assistant Drawing keeps doc.ext and record meta and writes them back',
    d4.ext == {'units': 'mm'}
    and d4.objs[0]['meta'] == {'layer': 'A'}
    and d4.to_doc()['ext'] == {'units': 'mm'}
    and d4.to_doc()['objects'][0]['meta'] == {'layer': 'A'},
    d4.to_doc(),
)
r2 = browser_eval("""() => {
  AR.doc.ext = {north: 30};
  const o = arNewObj('slab', {w:1, d:1, t:0.2}, 0, 0, 0); o.meta = {layer: 'B'};
  const out = arDocOut();
  const snap = JSON.parse(arSnapshot());
  return {ext: out.ext, meta: out.objects[out.objects.length - 1].meta, snapMeta: snap[snap.length - 1].meta};
}""")
check(
    'the tab writes doc.ext (other families may add their own keys beside ours) and record meta into the document and the undo snapshot',
    (r2['value']['ext'] or {}).get('north') == 30
    and r2['value']['meta'] == {'layer': 'B'}
    and r2['value']['snapMeta'] == {'layer': 'B'},
    r2['value'],
)
finish()
