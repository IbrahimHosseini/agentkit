import hashlib, json, os, re, sys

START = '<!-- agentkit:start -->'
END = '<!-- agentkit:end -->'


def rd(p):
    try:
        with open(p, encoding='utf-8', newline='') as f:
            return f.read()
    except FileNotFoundError:
        return None


def wr(p, s):
    p = os.path.realpath(p)  # never replace a symlink, write through it
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.agentkit-tmp'
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        f.write(s)
    if os.path.exists(p):
        os.chmod(tmp, os.stat(p).st_mode & 0o7777)
    os.replace(tmp, p)


def load_settings(p):
    s = rd(p)
    if s is None or not s.strip():
        return {}
    d = json.loads(s)
    if not isinstance(d, dict):
        raise ValueError('not a JSON object')
    return d


def dump(d):
    return json.dumps(d, indent=2, ensure_ascii=False) + '\n'


PATTERNS = {
    'agentkit-agent-log': re.compile(r'hooks/agent-log\.pycheck'),
    'agentkit-auto-update': re.compile(r'/hooks/update-check\.sh$'),
}


def norm(cmd):
    return re.sub(r'["\'\s]+', '', str(cmd))


def is_ours(g, source):
    """Marked with source, or unmarked and every inner command matches our command."""
    if not isinstance(g, dict):
        return False
    if g.get('_agentkit_source') == source:
        return True
    if '_agentkit_source' in g or source not in PATTERNS:
        return False
    inner = g.get('hooks')
    if not isinstance(inner, list) or not inner:
        return False
    return all(isinstance(h, dict) and h.get('type') == 'command' and PATTERNS[source].search(norm(h.get('command', '')))
               for h in inner)


def entry(source, command, timeout):
    return {'hooks': [{'type': 'command', 'command': command, 'timeout': int(timeout)}],
            '_agentkit_source': source}


def main(a):
    c = a[0]
    if c == 'hook-show':
        print(dump({'hooks': {a[1]: [entry(a[2], a[3], a[4])]}}), end='')
    elif c == 'hook-add':
        path, event, source, command, timeout, mode = a[1:7]
        refresh = len(a) > 7 and a[7] == 'refresh'  # only touch entries that already carry our marker
        d = load_settings(path)
        hooks = d.setdefault('hooks', {})
        lst = hooks.setdefault(event, [])
        new = entry(source, command, timeout)
        idx = [i for i, g in enumerate(lst) if is_ours(g, source)]
        if refresh:
            idx = [i for i in idx if lst[i].get('_agentkit_source') == source]
            if not idx:
                print('unchanged')
                return
        if idx and len(idx) == 1 and lst[idx[0]] == new:
            status = 'unchanged'
        elif idx:
            lst[idx[0]] = new
            for i in reversed(idx[1:]):  # drop duplicates of our own entry
                del lst[i]
            status = 'updated'
        else:
            lst.append(new)
            status = 'added'
        if mode == 'write' and status != 'unchanged':
            wr(path, dump(d))
        print(status)
    elif c == 'hook-remove':
        path, prefix, mode = a[1:4]
        d = load_settings(path)
        n = 0
        hooks = d.get('hooks')
        if isinstance(hooks, dict):
            for ev in list(hooks):
                lst = hooks[ev]
                if not isinstance(lst, list):
                    continue
                keep = [g for g in lst if not (isinstance(g, dict) and str(g.get('_agentkit_source', '')).startswith(prefix))]
                n += len(lst) - len(keep)
                if len(keep) != len(lst):
                    if keep:
                        hooks[ev] = keep
                    else:
                        del hooks[ev]
            if not hooks and n:
                del d['hooks']
        if mode == 'write' and n:
            wr(path, dump(d))
        print(n)
    elif c == 'hook-has':
        d = load_settings(a[1])
        for lst in (d.get('hooks') or {}).values():
            for g in lst if isinstance(lst, list) else []:
                if isinstance(g, dict) and g.get('_agentkit_source') == a[2]:
                    sys.exit(0)
        sys.exit(1)
    elif c == 'hook-old':
        d = load_settings(a[1])
        for g in (d.get('hooks') or {}).get(a[2]) or []:
            if is_ours(g, a[3]):
                print(json.dumps(g, indent=2, ensure_ascii=False))
    elif c == 'export-has-groups':
        try:
            sys.exit(0 if json.loads(rd(a[1]) or '{}').get('groups') else 1)
        except ValueError:
            sys.exit(1)
    elif c == 'heading-outside':
        s = rd(a[1]) or ''
        s = re.sub(re.escape(START) + r'.*?' + re.escape(END), '', s, flags=re.S)
        sys.exit(0 if re.search(r'(?m)^#\s+Multi-agent workflow', s) else 1)
    elif c == 'block-has':
        sys.exit(0 if START in (rd(a[1]) or '') else 1)
    elif c == 'block-put':
        path, snip, mode = a[1:4]
        s = rd(path) or ''
        block = START + '\n' + (rd(snip) or '').rstrip('\n') + '\n' + END
        m = re.search(re.escape(START) + r'.*?' + re.escape(END), s, re.S)
        if m:
            new = s[:m.start()] + block + s[m.end():]
            status = 'replaced' if new != s else 'unchanged'
        elif START in s or END in s:
            raise ValueError('only one agentkit marker found; fix the file by hand')
        else:
            new = (s.rstrip('\n') + '\n\n' if s.strip() else '') + block + '\n'
            status = 'added'
        if mode == 'write' and status != 'unchanged':
            wr(path, new)
        print(status)
    elif c == 'block-del':
        path, mode = a[1:3]
        s = rd(path) or ''
        m = re.search(re.escape(START) + r'.*?' + re.escape(END), s, re.S)
        if not m:
            print('none')
            return
        before, after = s[:m.start()].rstrip('\n'), s[m.end():].lstrip('\n')
        new = before + ('\n\n' if before and after else '') + after
        new = new + '\n' if new else ''
        status = 'removed' if new.strip() else 'removed-empty'
        if mode == 'write':
            if new.strip():
                wr(path, new)
            else:
                os.unlink(os.path.realpath(path))
        print(status)
    elif c == 'mf-read':
        d = json.loads(rd(a[1]) or '{}')
        for k, v in sorted((d.get('files') or {}).items()):
            print(k + '\t' + v)
    elif c == 'mf-version':
        print(json.loads(rd(a[1]) or '{}').get('agentkit_version', ''))
    elif c == 'mf-write':
        path, version, tsv = a[1:4]
        files = {}
        for line in (rd(tsv) or '').splitlines():
            k, _, v = line.partition('\t')
            if k:
                files[k] = v
        out = dump({'agentkit_version': version, 'files': dict(sorted(files.items()))})
        if rd(path) != out:
            wr(path, out)
    else:
        sys.exit('unknown helper command: ' + c)
