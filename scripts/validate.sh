#!/usr/bin/env bash
# Validate the agentkit repo. Exit non-zero on any failure.
set -u

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root" || exit 1
fails=0
fail() { printf 'FAIL: %s\n' "$*" >&2; fails=$((fails + 1)); }
pass() { printf 'ok:   %s\n' "$*"; }

# Agents and skills: frontmatter.
python3 -I - "$root" <<'PY' || fails=$((fails + 1))
import glob, os, sys

root = sys.argv[1]
errors = []


def frontmatter(path):
    with open(path, encoding='utf-8') as f:
        lines = f.read().split('\n')
    if not lines or lines[0].strip() != '---':
        return None
    out = {}
    for line in lines[1:]:
        if line.strip() == '---':
            return out
        if ':' in line and not line.startswith((' ', '\t')):
            k, _, v = line.partition(':')
            out[k.strip()] = v.strip()
    return None


agents = sorted(glob.glob(os.path.join(root, 'agents', '*.md')))
for p in agents:
    n = os.path.basename(p)
    fm = frontmatter(p)
    if fm is None:
        errors.append('agents/%s: missing or unterminated frontmatter' % n)
        continue
    if fm.get('name') != n[:-3]:
        errors.append('agents/%s: name %r must equal the file name' % (n, fm.get('name')))
    for k in ('description', 'tools'):
        if not fm.get(k):
            errors.append('agents/%s: missing %s' % (n, k))
skills = sorted(glob.glob(os.path.join(root, 'skills', '*', 'SKILL.md')))
for p in skills:
    d = os.path.basename(os.path.dirname(p))
    fm = frontmatter(p)
    if fm is None:
        errors.append('skills/%s/SKILL.md: missing or unterminated frontmatter' % d)
    elif fm.get('name') != d:
        errors.append('skills/%s/SKILL.md: name %r must equal the folder name' % (d, fm.get('name')))
for e in errors:
    print('FAIL: ' + e, file=sys.stderr)
if not errors:
    print('ok:   %d agents, %d skills: frontmatter' % (len(agents), len(skills)))
sys.exit(1 if errors else 0)
PY

# No personal paths. The patterns are split so this file does not match itself.
p1="/Use""rs/"; p2="/ho""me/"
hits="$(grep -rIn --exclude-dir=.git --exclude-dir=.security-audit --exclude-dir=__pycache__ -e "$p1" -e "$p2" . 2> /dev/null)"
if [ -n "$hits" ]; then
  fail "personal paths found:"
  echo "$hits" >&2
else
  pass "no personal paths"
fi

# Python.
if python3 -I -m py_compile hooks/agent-log.py; then pass "py_compile hooks/agent-log.py"; else fail "py_compile hooks/agent-log.py"; fi
find . -name __pycache__ -path './hooks/*' -prune -exec rm -rf {} + 2> /dev/null
if python3 -I hooks/test_agent_log.py > /dev/null 2>&1; then pass "hooks/test_agent_log.py"; else fail "hooks/test_agent_log.py (run it by hand for details)"; fi

# Compile the shared native core without creating bytecode in the checkout.
if python3 -I - <<'PYCORE'
import pathlib
for path in sorted(pathlib.Path('lib').rglob('*.py')):
    compile(path.read_bytes(), str(path), 'exec')
print('ok:   shared Python core syntax')
PYCORE
then :; else fail "shared Python core syntax"; fi

# Codex support: python helper, data files, and the requirements block embedded in install.sh.
if PYTHONDONTWRITEBYTECODE=1 python3 -I -m py_compile lib/codex.py; then pass "py_compile lib/codex.py"; else fail "py_compile lib/codex.py"; fi
find . -name __pycache__ -path './lib/*' -prune -exec rm -rf {} + 2> /dev/null
for f in codex/models.map codex/karpathy-guidelines.md templates/AGENTS.md.snippet; do
  if [ -s "$f" ]; then pass "exists $f"; else fail "missing or empty $f"; fi
done
blk() { sed -n '/^# >>> agentkit:requirements$/,/^# <<< agentkit:requirements$/p' "$1"; }
if [ -n "$(blk lib/requirements.sh)" ] && [ "$(blk lib/requirements.sh)" = "$(blk install.sh)" ]; then
  pass "install.sh requirements block equals lib/requirements.sh"
else
  fail "requirements block in install.sh differs from lib/requirements.sh"
fi

# JSON files and version match.
for f in .claude-plugin/plugin.json .claude-plugin/marketplace.json hooks/hooks.json; do
  if python3 -I -c 'import json,sys; json.load(open(sys.argv[1]))' "$f" 2> /dev/null; then pass "json $f"; else fail "json $f does not parse"; fi
done
v="$(tr -d '[:space:]' < VERSION)"
pv="$(python3 -I -c 'import json; print(json.load(open(".claude-plugin/plugin.json"))["version"])' 2> /dev/null)"
if [ "$v" = "$pv" ]; then pass "plugin.json version $pv matches VERSION"; else fail "plugin.json version '$pv' differs from VERSION '$v'"; fi

# Shell scripts.
scripts="install.sh bin/agentkit lib/ui.sh lib/requirements.sh hooks/update-check.sh scripts/validate.sh scripts/sync.sh"
[ -f tests/run.sh ] && scripts="$scripts tests/run.sh"
[ -f lib/legacy-cli.sh ] && scripts="$scripts lib/legacy-cli.sh"
for s in $scripts; do
  if bash -n "$s"; then pass "bash -n $s"; else fail "syntax error in $s"; fi
done
if command -v shellcheck > /dev/null 2>&1; then
  # --severity=warning: fail on warnings and errors, not on style and info notes.
  # shellcheck disable=SC2086
  if shellcheck --severity=warning $scripts; then pass "shellcheck"; else fail "shellcheck"; fi
else
  echo "skip: shellcheck not installed"
fi

if [ "$fails" -gt 0 ]; then
  printf '\n%d check(s) failed.\n' "$fails" >&2
  exit 1
fi
echo "All checks passed."
