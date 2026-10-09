# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from .constants import (
    CACHE_PATH,
    CLASS_RE,
    DEF_RE,
    HARD_PRUNE,
    JS_FN_RE,
    MAIN_RE,
    NOLINE_EXT,
    PROMPT_NAME,
    ROOT,
    ROUTE_RE,
    TRAINING_ROOTS,
    _SKIP_BY_EXT,
    ast,
    json,
    os,
    re,
    warnings,
)
from .helpers import RUNTIME_FILE, _ext, _is_backup_name, _iso, _kind_of, _prune_reason

import logging as _zyg_logging

# The logger is re-created here by assignment rather than imported from the sibling
# module: getLogger returns the one singleton the original module held, and an assigned
# global keeps the method-call bytecode of every `_zyg_log.debug(...)` below unchanged.
_zyg_log = _zyg_logging.getLogger('zyg_dashboard.expansion_hub')
# ── per-file reading (cached) ────────────────────────────────────────────────


def _load_cache():
    try:
        with open(CACHE_PATH, encoding='utf-8') as fh:
            c = json.load(fh)
        return c if isinstance(c, dict) and c.get('v') == 2 else {'v': 2, 'files': {}}
    except (OSError, ValueError):
        return {'v': 2, 'files': {}}


def _save_cache(cache):
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        tmp = CACHE_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(cache, fh, separators=(',', ':'))
        os.replace(tmp, CACHE_PATH)
    except OSError as exc:
        _zyg_log.info(f'[EXPANSION] cache not saved: {exc}')


def _string_like(node):
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        return _string_like(node.left) or _string_like(node.right)
    return False


def _str_len(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return len(node.value), node.value.count('\n') + 1
    if isinstance(node, ast.JoinedStr):
        n = l = 0
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                n += len(v.value)
                l += v.value.count('\n')
        return n, l + 1
    if isinstance(node, ast.BinOp):
        a, al = _str_len(node.left) if _string_like(node.left) else (0, 0)
        b, bl = _str_len(node.right) if _string_like(node.right) else (0, 0)
        return a + b, max(1, al + bl - 1)
    return 0, 0


def _collect_strings(node, min_len=20):
    """Count long string constants inside a dict/list/tuple literal (a question bank)."""
    n = chars = 0
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and len(sub.value) >= min_len:
            n += 1
            chars += len(sub.value)
    return n, chars


def _prompt_literals(src):
    """Prompt literals in Python source: (count, chars, lines) — by AST, not grep.
    Counted: assignments whose target name says prompt/persona/instruction/question/
    checklist with a string value (or a dict/list bank of long strings), keyword args
    prompt=/system=/system_prompt=/instructions=/negative_prompt= with a string value,
    and {'role': 'system', 'content': <string>} message dicts."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            tree = ast.parse(src)
    except (SyntaxError, ValueError, RecursionError):
        return 0, 0, 0
    count = chars = lines = 0
    KW = {
        'prompt',
        'system',
        'system_prompt',
        'instructions',
        'negative_prompt',
        'positive',
        'negative',
        'prompt_text',
        'user_prompt',
        'sys_prompt',
    }
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = []
            for t in targets:
                if isinstance(t, ast.Name):
                    names.append(t.id)
                elif isinstance(t, ast.Attribute):
                    names.append(t.attr)
                elif (
                    isinstance(t, ast.Subscript)
                    and isinstance(t.slice, ast.Constant)
                    and isinstance(t.slice.value, str)
                ):
                    names.append(t.slice.value)
            if not any(PROMPT_NAME.search(n) for n in names) or node.value is None:
                continue
            v = node.value
            if _string_like(v):
                c, l = _str_len(v)
                if c >= 12:
                    count += 1
                    chars += c
                    lines += l
            elif isinstance(v, (ast.Dict, ast.List, ast.Tuple)):
                n, c = _collect_strings(v)
                count += n
                chars += c
                lines += n
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in KW and _string_like(kw.value):
                    c, l = _str_len(kw.value)
                    if c >= 12:
                        count += 1
                        chars += c
                        lines += l
        elif isinstance(node, ast.Dict):
            keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
            if 'role' in keys and 'content' in keys:
                role = content = None
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and k.value == 'role' and isinstance(v, ast.Constant):
                        role = v.value
                    if isinstance(k, ast.Constant) and k.value == 'content':
                        content = v
                if role == 'system' and content is not None and _string_like(content):
                    c, l = _str_len(content)
                    if c >= 12:
                        count += 1
                        chars += c
                        lines += l
    return count, chars, lines


def _prompt_units(path, ext, text):
    """How many prompts a prompt FILE holds, by its format. Documented rule per shape."""
    if ext in ('txt', 'md'):
        return 1, 'whole file is one prompt'
    if ext in ('yaml', 'yml', 'toml'):
        return max(1, len(re.findall(r'^\s*[\w\-]+\s*[:=]\s*[|>"\']?\s*\S', text, re.M))), 'top-level keys with a value'
    if ext != 'json':
        return 0, ''
    try:
        d = json.loads(text)
    except ValueError:
        return 0, 'unparseable json'
    base = os.path.basename(path)
    if base == 'prompt_registry.json' and isinstance(d, dict) and isinstance(d.get('prompts'), dict):
        return len(d['prompts']), 'entries in "prompts"'
    if '_comfy_workflows' in path and isinstance(d, dict):
        n = 0
        for node in d.values():
            if isinstance(node, dict) and isinstance(node.get('inputs'), dict):
                for k, v in node['inputs'].items():
                    if (
                        k in ('text', 'prompt', 'positive', 'negative', 'tags', 'lyrics')
                        and isinstance(v, str)
                        and len(v) >= 8
                    ):
                        n += 1
        return n, 'text inputs on graph nodes (text/prompt/positive/negative/tags/lyrics)'
    if base == 'vlm_checklists.json':
        n = 0
        stack = [d]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                stack.extend(x.values())
            elif isinstance(x, list):
                stack.extend(x)
            elif isinstance(x, str) and x.rstrip().endswith('?'):
                n += 1
        return n, 'binary questions (strings ending in ?)'
    if os.path.join('agents', 'crews', 'agents') in path or 'briefs' in path:
        return 1, 'one persona / brief per file'
    n = 0
    stack = [d]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)
        elif isinstance(x, str) and len(x) >= 40:
            n += 1
    return n, 'string values of 40+ characters'


def _read_file(path, ext, kind, st, cache_files, misses):
    """Per-file facts, from the cache when (mtime_ns, size) match."""
    key = path
    hit = cache_files.get(key)
    sig = [st.st_mtime_ns, st.st_size]
    if hit and hit.get('sig') == sig:
        return hit
    misses.append(path)
    rec = {'sig': sig, 'lines': 0, 'blank': 0, 'comment': 0}
    if ext in NOLINE_EXT or kind == 'asset' or st.st_size == 0:
        cache_files[key] = rec
        return rec
    try:
        with open(path, 'rb') as fh:
            raw = fh.read()
    except OSError:
        cache_files[key] = rec
        return rec
    if b'\0' in raw[:4096]:
        cache_files[key] = rec  # binary disguised as text
        return rec
    rec['lines'] = raw.count(b'\n') + (1 if raw and not raw.endswith(b'\n') else 0)
    if st.st_size <= 8 * 1024 * 1024:
        text = raw.decode('utf-8', errors='replace')
        blank = comment = 0
        cm = (
            ('#',)
            if ext
            in (
                'py',
                'sh',
                'bash',
                'zsh',
                'yaml',
                'yml',
                'toml',
                'ini',
                'cfg',
                'conf',
                'service',
                'nft',
                'requirements',
                'dockerfile',
                'compose',
                'ps1',
                'pl',
                'rb',
            )
            else ('//', '/*', '*')
            if ext
            in (
                'js',
                'mjs',
                'cjs',
                'ts',
                'tsx',
                'jsx',
                'css',
                'scss',
                'c',
                'cc',
                'cpp',
                'h',
                'hpp',
                'rs',
                'go',
                'java',
                'kt',
                'glsl',
                'wgsl',
                'osl',
            )
            else ('<!--',)
            if ext in ('html', 'htm', 'jinja', 'j2', 'xml')
            else ()
        )
        for ln in text.split('\n'):
            s = ln.strip()
            if not s:
                blank += 1
            elif cm and s.startswith(cm):
                comment += 1
        rec['blank'] = blank
        rec['comment'] = comment
        if ext == 'py':
            rec['defs'] = len(DEF_RE.findall(text))
            rec['classes'] = len(CLASS_RE.findall(text))
            rec['routes'] = len(ROUTE_RE.findall(text))
            rec['main'] = 1 if MAIN_RE.search(text) else 0
            pc, pch, pl = _prompt_literals(text)
            if pc:
                rec['p_lits'] = pc
                rec['p_chars'] = pch
                rec['p_lines'] = pl
        elif ext in ('js', 'mjs', 'cjs', 'ts'):
            rec['defs'] = len(JS_FN_RE.findall(text))
        elif ext in ('html', 'htm', 'jinja', 'j2'):
            rec['defs'] = len(re.findall(r'{%\s*include\b', text))
            rec['scripts'] = len(re.findall(r'<script\b', text, re.I))
        if kind == 'prompt':
            u, rule = _prompt_units(path, ext, text)
            rec['units'] = u
            rec['units_rule'] = rule
    cache_files[key] = rec
    return rec


# ── the walk ─────────────────────────────────────────────────────────────────


def _walk_component(comp, cache_files, misses, excluded, skipped, files, dirs_seen):
    root = comp['root']
    if comp['kind'] == 'files':
        for p in comp['files']:
            _add_file(p, comp, os.path.dirname(p), cache_files, misses, skipped, files)
        return
    for dp, dn, fn in os.walk(root, onerror=lambda e: None):
        keep = []
        for d in sorted(dn):
            full = os.path.join(dp, d)
            reason = _prune_reason(full, d, dp, root)
            if reason:
                excluded.append({'path': full, 'reason': reason, 'component': comp['id']})
            else:
                keep.append(d)
        dn[:] = keep
        dirs_seen.append((comp['id'], dp))
        for f in sorted(fn):
            _add_file(os.path.join(dp, f), comp, root, cache_files, misses, skipped, files)


def _add_file(full, comp, root, cache_files, misses, skipped, files):
    name = os.path.basename(full)
    try:
        st = os.lstat(full)
    except OSError:
        return
    if not os.path.isfile(full) or os.path.islink(full):
        return
    rel = os.path.relpath(full, root) if root and full.startswith(root + os.sep) else full
    rel_parts = rel.split(os.sep)[:-1]
    ext = _ext(name)
    if _is_backup_name(name):
        skipped['backup copies'][0] += 1
        skipped['backup copies'][1] += st.st_size
        return
    if RUNTIME_FILE.match(name):
        skipped['runtime stores / logs'][0] += 1
        skipped['runtime stores / logs'][1] += st.st_size
        return
    kind = _kind_of(full, ext, rel_parts)
    if kind is None:
        r = _SKIP_BY_EXT.get(ext, 'other')
        skipped[r][0] += 1
        skipped[r][1] += st.st_size
        return
    rec = _read_file(full, ext, kind, st, cache_files, misses)
    files.append(
        {
            'path': rel
            if root == ROOT
            else (os.path.join(os.path.basename(root), rel) if comp['kind'] == 'app' else full),
            'abs': full,
            'comp': comp['id'],
            'ext': ext or '(none)',
            'kind': kind,
            'bytes': st.st_size,
            'lines': rec.get('lines', 0),
            'blank': rec.get('blank', 0),
            'comment': rec.get('comment', 0),
            'mtime': st.st_mtime,
            'defs': rec.get('defs'),
            'classes': rec.get('classes'),
            'routes': rec.get('routes'),
            'main': rec.get('main'),
            'scripts': rec.get('scripts'),
            'p_lits': rec.get('p_lits'),
            'p_chars': rec.get('p_chars'),
            'p_lines': rec.get('p_lines'),
            'units': rec.get('units'),
            'units_rule': rec.get('units_rule'),
        }
    )


def _walk_training():
    out = []
    totals = {
        'files': 0,
        'bytes': 0,
        'images': 0,
        'captions': 0,
        'audio': 0,
        'video': 0,
        'manifests': 0,
        'other': 0,
        'datasets': 0,
    }
    IMG = {'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff'}
    AUD = {'wav', 'mp3', 'flac', 'ogg', 'm4a', 'opus'}
    VID = {'mp4', 'mov', 'webm', 'mkv'}
    MAN = {'json', 'toml', 'yaml', 'yml', 'csv', 'md'}
    for tr in TRAINING_ROOTS:
        root = tr['root']
        if not os.path.isdir(root):
            out.append(dict(tr, present=False, datasets=[]))
            continue
        sets = {}
        for dp, dn, fn in os.walk(root, onerror=lambda e: None):
            dn[:] = [d for d in dn if d not in HARD_PRUNE and not d.startswith('.venv')]
            rel = os.path.relpath(dp, root)
            top = rel.split(os.sep)[0] if rel != '.' else '(root)'
            s = sets.setdefault(
                top,
                {
                    'name': top,
                    'files': 0,
                    'bytes': 0,
                    'images': 0,
                    'captions': 0,
                    'audio': 0,
                    'video': 0,
                    'manifests': 0,
                    'other': 0,
                    'backup': 'backup' in top.lower() or 'quarantine' in top.lower(),
                    'newest': 0.0,
                },
            )
            for f in fn:
                try:
                    st = os.lstat(os.path.join(dp, f))
                except OSError as _exc:
                    _zyg_log.debug('%s vanished while being stat-ed, skipped: %s', f, _exc)
                    continue
                if not os.path.isfile(os.path.join(dp, f)):
                    continue
                e = f.rsplit('.', 1)[-1].lower() if '.' in f else ''
                s['files'] += 1
                s['bytes'] += st.st_size
                s['newest'] = max(s['newest'], st.st_mtime)
                if e in IMG:
                    s['images'] += 1
                elif e in ('txt', 'caption'):
                    s['captions'] += 1
                elif e in AUD:
                    s['audio'] += 1
                elif e in VID:
                    s['video'] += 1
                elif e in MAN:
                    s['manifests'] += 1
                else:
                    s['other'] += 1
        ds = sorted(sets.values(), key=lambda x: -x['bytes'])
        for s in ds:
            s['newest'] = _iso(s['newest']) if s['newest'] else ''
            for k in ('files', 'bytes', 'images', 'captions', 'audio', 'video', 'manifests', 'other'):
                totals[k] += s[k]
        totals['datasets'] += sum(1 for s in ds if s['name'] != '(root)' and not s['backup'])
        out.append(
            dict(tr, present=True, datasets=ds, files=sum(s['files'] for s in ds), bytes=sum(s['bytes'] for s in ds))
        )
    return out, totals
