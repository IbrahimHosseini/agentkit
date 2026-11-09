#!/usr/bin/env bash
# agentkit integration tests. Run: bash tests/run.sh [test_name ...]
# bash 3.2 compatible. Every test runs in its own temp HOME. Nothing touches the real ~/.claude,
# ~/.agentkit, the network, or a real `claude` / `gh` (stubs are used). Exit 1 on any failure.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
LIB="$ROOT/tests/lib"
REAL_HOME="${HOME:-}"

SUITE="$(mktemp -d "${TMPDIR:-/tmp}/agentkit-tests.XXXXXX")" || { echo "cannot create temp dir" >&2; exit 2; }
SUITE="$(cd "$SUITE" && pwd -P)"
REALBIN="$SUITE/realbin"
BASE="$SUITE/base.git"

wait_bg() { # wait (max 20s) for background agentkit processes started under this suite
  local i=0
  command -v pgrep > /dev/null 2>&1 || { sleep 1; return 0; }
  while pgrep -f "$SUITE/t\\..*/(home/\\.agentkit|fake)/(bin/agentkit|hooks)" > /dev/null 2>&1 && [ "$i" -lt 200 ]; do
    sleep 0.1; i=$((i + 1))
  done
}
cleanup() { wait_bg; rm -rf "${SUITE:?}"; }
trap cleanup EXIT

# ------------------------------------------------------------------ suite setup
# A PATH with only the tools agentkit needs. No claude, no gh, no bun.
mkdir -p "$REALBIN"
PY="$(python3 -I -c 'import sys; print(sys.executable)')" || { echo "python3 is required" >&2; exit 2; }
ln -s "$PY" "$REALBIN/python3"
for tool in bash sh git env awk sed grep find sort tail head cat cp mv rm mkdir mktemp date wc tr cut readlink \
  dirname basename shasum sha256sum ls ln chmod uname nohup rmdir diff cmp touch sleep id xargs tee pgrep tar dd; do
  p="$(command -v "$tool" 2> /dev/null)"
  case "$p" in /*) ln -sf "$p" "$REALBIN/$tool" ;; esac
done
PY="$REALBIN/python3"
export GIT_AUTHOR_NAME=test GIT_AUTHOR_EMAIL=test@example.invalid GIT_COMMITTER_NAME=test GIT_COMMITTER_EMAIL=test@example.invalid
export GIT_CONFIG_NOSYSTEM=1

# The "upstream": a bare repo made from a temp copy of the working tree (without tests/ and .git).
mkdir -p "$SUITE/work"
(cd "$ROOT" && tar -cf - --exclude=./tests --exclude=./.git --exclude=__pycache__ --exclude=.DS_Store .) | (cd "$SUITE/work" && tar -xf -) \
  || { echo "cannot copy the working tree" >&2; exit 2; }
(
  cd "$SUITE/work" && PATH="$REALBIN" && git init -q . && git symbolic-ref HEAD refs/heads/main \
    && git add -A && git commit -q -m base && git clone -q --bare . "$BASE"
) || { echo "cannot create the upstream repo" >&2; exit 2; }

# ------------------------------------------------------------------ per-test environment
new_env() { # T
  T="$1"
  export HOME="$T/home" TMPDIR="$T/tmp" AGENT_LOG_DIR="$T/agent-log" PATH="$T/stubs:$REALBIN"
  export AGENTKIT_REPO="$T/origin.git" STUB_LOG="$T/stub.log"
  export CODEX_HOME="$HOME/.codex" LC_ALL=C
  unset CLAUDE_CONFIG_DIR AGENTKIT_HOME AGENTKIT_UPDATE_INTERVAL GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE STUB_PLUGIN_LIST STUB_GH_FAIL_LABEL
  unset NO_COLOR LANG LC_CTYPE AGENTKIT_REQS_OK STUB_CURL_LOG
  mkdir -p "$HOME" "$TMPDIR" "$T/work" "$T/stubs"
  # A silent claude, so the requirements check passes. Tests that need no claude remove it.
  printf '#!/bin/sh\nexit 0\n' > "$T/stubs/claude"
  chmod +x "$T/stubs/claude"
  cp -R "$BASE" "$AGENTKIT_REPO"
  CLAUDE="$HOME/.claude"
  CODEX="$CODEX_HOME"
  AKH="$HOME/.agentkit"
  AK="$AKH/bin/agentkit"
  RUN_STDIN=/dev/null
  cd "$T/work" || exit 99
  sandbox_ok
}

sandbox_ok() {
  case "$HOME" in "$SUITE"/t.*/home) ;; *) echo "FATAL: HOME is not a temp dir: $HOME"; exit 99 ;; esac
  [ "$HOME" != "$REAL_HOME" ] || { echo "FATAL: HOME is the real HOME"; exit 99; }
  [ -z "${CLAUDE_CONFIG_DIR:-}" ] || { echo "FATAL: CLAUDE_CONFIG_DIR is set"; exit 99; }
  case "${CODEX_HOME:-}" in "$SUITE"/t.*) ;; '') ;; *) echo "FATAL: CODEX_HOME is outside the temp dir: $CODEX_HOME"; exit 99 ;; esac
  case "$AGENT_LOG_DIR" in "$SUITE"/*) ;; *) echo "FATAL: AGENT_LOG_DIR is outside the temp dir"; exit 99 ;; esac
}

# ------------------------------------------------------------------ assertions
fail() { printf '    ASSERT FAILED: %s\n' "$*"; echo 1 >> "$T/.fails"; }
show_out() { printf '%s\n' "$OUT" | tail -n 25 | sed 's/^/      | /'; }
assert_eq() { [ "$1" = "$2" ] || fail "$3 (expected '$2', got '$1')"; }
assert_rc() { [ "$RC" -eq "$1" ] || { fail "$2: exit code $RC, expected $1"; show_out; }; }
assert_rc_nz() { [ "$RC" -ne 0 ] || { fail "$1: exit code 0, expected non-zero"; show_out; }; }
assert_contains() { case "$OUT" in *"$1"*) ;; *) fail "${2:-output}: lacks '$1'"; show_out ;; esac; }
assert_not_contains() { case "$OUT" in *"$1"*) fail "${2:-output}: should not contain '$1'"; show_out ;; *) ;; esac; }
assert_file() { [ -f "$1" ] || fail "missing file: $1"; }
assert_nofile() { { [ ! -e "$1" ] && [ ! -L "$1" ]; } || fail "should not exist: $1"; }
assert_same() { cmp -s "$1" "$2" || fail "differs: $1 and $2"; }
assert_grep() { grep -qF -- "$2" "$1" 2> /dev/null || fail "$1 lacks '$2'"; }
assert_nogrep() { if grep -qF -- "$2" "$1" 2> /dev/null; then fail "$1 should not contain '$2'"; fi; }
assert_jtrue() { "$PY" -I "$LIB/jtrue.py" "$1" "$2" > /dev/null 2> "$T/.jerr" || fail "$1: expression is false: $2 $(cat "$T/.jerr")"; }
jval() { "$PY" -I "$LIB/jtrue.py" "$1" "$2" 2> /dev/null; }
snap() { "$PY" -I "$LIB/snap.py" "$1"; }
count_of() { grep -c -- "$2" "$1" 2> /dev/null || true; }
nlines() { if [ -f "$1" ]; then wc -l < "$1" | tr -d ' '; else echo 0; fi; }

# run CMD...: no terminal, stdin from $RUN_STDIN, output (stdout+stderr) in $OUT, exit code in $RC.
run() {
  sandbox_ok
  OUT="$("$PY" -I "$LIB/notty.py" "$@" 2>&1 < "$RUN_STDIN")"
  RC=$?
}
# run_split CMD...: stdout in $T/stdout, stderr in $T/stderr, seconds in $ELAPSED.
run_split() {
  sandbox_ok
  "$PY" -I "$LIB/timeit.py" "$T/elapsed" "$@" > "$T/stdout" 2> "$T/stderr" < "$RUN_STDIN"
  RC=$?
  ELAPSED="$(cat "$T/elapsed")"
  OUT="$(cat "$T/stdout" "$T/stderr")"
}
wait_for() { # file seconds
  local i=0
  while [ ! -s "$1" ] && [ "$i" -lt $(($2 * 10)) ]; do sleep 0.1; i=$((i + 1)); done
  [ -s "$1" ]
}
wait_lines() { # file n seconds
  local i=0
  while [ "$(nlines "$1")" -lt "$2" ] && [ "$i" -lt $(($3 * 10)) ]; do sleep 0.1; i=$((i + 1)); done
  [ "$(nlines "$1")" -ge "$2" ]
}

# ------------------------------------------------------------------ fixtures
setup_home() { git clone -q "$AGENTKIT_REPO" "$AKH" || { echo "clone failed"; exit 99; }; }
install_user() { run bash "$AKH/install.sh" --yes --skip gstack --skip karpathy "$@"; }
# upstream 'shell commands': run them in a fresh clone of the upstream repo, commit, push.
upstream() {
  rm -rf "$T/up"
  git clone -q "$AGENTKIT_REPO" "$T/up" \
    && (cd "$T/up" && sh -c "$1" && git add -A && git commit -q -m "upstream change" && git push -q origin HEAD:main) \
    || { echo "upstream change failed"; exit 99; }
}
mk_claude() {
  cat > "$T/stubs/claude" <<'EOF'
#!/bin/sh
echo "claude $*" >> "$STUB_LOG"
if [ "$1 $2" = "plugin list" ] && [ -n "${STUB_PLUGIN_LIST:-}" ]; then echo "$STUB_PLUGIN_LIST"; fi
exit 0
EOF
  chmod +x "$T/stubs/claude"
  PATH="$T/stubs:$REALBIN"
}
mk_gh() {
  cat > "$T/stubs/gh" <<'EOF'
#!/bin/sh
echo "gh $*" >> "$STUB_LOG"
prev=""
for a in "$@"; do
  if [ "$prev" = "--body-file" ]; then while IFS= read -r l; do echo "$l" >> "$STUB_LOG.body"; done < "$a"; fi
  prev="$a"
done
case " $* " in *" --label "*) if [ -n "${STUB_GH_FAIL_LABEL:-}" ]; then echo "label not found" >&2; exit 1; fi ;; esac
echo "https://example.invalid/issues/1"
exit 0
EOF
  chmod +x "$T/stubs/gh"
  PATH="$T/stubs:$REALBIN"
}
# A logging codex stub (the default claude stub is silent). Found through $T/stubs on PATH.
mk_codex() {
  cat > "$T/stubs/codex" <<'EOF'
#!/bin/sh
echo "codex $*" >> "$STUB_LOG"
exit 0
EOF
  chmod +x "$T/stubs/codex"
}
# A curl stub: any call is recorded in $T/curl.log and fails. agentkit must never reach it with --yes.
mk_curl() {
  cat > "$T/stubs/curl" <<'EOF'
#!/bin/sh
echo "curl $*" >> "$T_CURL_LOG"
exit 22
EOF
  chmod +x "$T/stubs/curl"
  export T_CURL_LOG="$T/curl.log"
}
# no_tool NAME...: PATH of the stubs and REALBIN without the named tools (no claude, no git, ...).
no_tool() {
  local d="$T/notool" f b x skip
  rm -rf "$d"; mkdir -p "$d"
  for f in "$T/stubs"/* "$REALBIN"/*; do
    b="$(basename "$f")"; skip=0
    for x in "$@"; do [ "$b" = "$x" ] && skip=1; done
    [ "$skip" = 1 ] || [ -e "$d/$b" ] || ln -s "$f" "$d/$b"
  done
  PATH="$d"
}
install_codex() { run "$AK" install --target codex --yes --skip gstack --skip karpathy "$@"; }
# run_pty CMD...: like run, but with a pseudo terminal on stdin, stdout and stderr.
run_pty() {
  sandbox_ok
  "$PY" -I "$LIB/pty_run.py" "$@" > "$T/pty.raw" 2>&1 < /dev/null
  RC=$?
  OUT="$(tr -d '\r' < "$T/pty.raw")"
}
assert_match() { printf '%s\n' "$OUT" | grep -Eq -- "$1" || { fail "${2:-output}: no line matches '$1'"; show_out; }; }
assert_dir_has() { [ -d "$1" ] || fail "missing folder: $1"; }
has_esc() { case "$1" in *$'\033'*) return 0 ;; esac; return 1; }
# line_of TEXT: number of the first output line containing TEXT (0 if none).
line_of() { printf '%s\n' "$OUT" | grep -n -F -- "$1" | head -n 1 | cut -d: -f1 | grep . || echo 0; }
# A fake agentkit home for the update-check hook: it records each call.
mk_fake_ak() {
  FAKE="$T/fake"
  mkdir -p "$FAKE/bin" "$CLAUDE/agentkit"
  cat > "$FAKE/bin/agentkit" <<EOF
#!/bin/sh
echo "called \$* home=\${AGENTKIT_HOME:-}" >> "$T/calls"
exit 0
EOF
  chmod +x "$FAKE/bin/agentkit"
  HOOK="$ROOT/hooks/update-check.sh"
}
# strip_markers FILE: remove _agentkit_source from every settings entry (a user "cleaned" the file).
strip_markers() {
  "$PY" -I -c '
import json, sys
p = sys.argv[1]
d = json.load(open(p))
for lst in d.get("hooks", {}).values():
    for g in lst:
        g.pop("_agentkit_source", None)
json.dump(d, open(p, "w"), indent=2)
' "$1"
}
n_src() { jval "$1" "sum(1 for g in d.get('hooks', {}).get('$2', []) if g.get('_agentkit_source') == '$3')"; }
sha_of() { "$PY" -I -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"; }

# ================================================================== tests

t_dry_run_writes_nothing() {
  setup_home
  mkdir -p "$CLAUDE"
  echo '{"keep": 1}' > "$CLAUDE/settings.json"
  printf '# mine\n' > "$CLAUDE/CLAUDE.md"
  local before after
  before="$(snap "$HOME")"
  run bash "$AKH/install.sh" --dry-run --skip gstack --skip karpathy
  assert_rc 0 "dry run from a checkout"
  assert_contains "[dry-run]"
  assert_contains "(dry run: nothing is written)"
  after="$(snap "$HOME")"
  assert_eq "$after" "$before" "dry run changed files under HOME"
  assert_nofile "$HOME/.local/bin/agentkit"
  assert_nofile "$CLAUDE/agents"
  assert_nofile "$CLAUDE/agentkit"
  # Piped like `curl | bash`: no checkout and no clone yet. The temp clone must be cleaned up.
  rm -rf "$AKH"
  before="$(snap "$HOME")"
  RUN_STDIN="$ROOT/install.sh" run bash -s -- --dry-run --skip gstack --skip karpathy
  assert_rc 0 "piped dry run"
  assert_contains "[dry-run] git clone"
  assert_eq "$(snap "$HOME")" "$before" "piped dry run changed files under HOME"
  assert_eq "$(find "$TMPDIR" -mindepth 1 -maxdepth 1 -name '*agentkit-dry*' | wc -l | tr -d ' ')" 0 "piped dry run left its temp clone behind"
}

# Regression: mktmp used inside $(...) lost its list, so temp files were never removed.
t_no_temp_files_left() {
  setup_home
  install_user
  assert_rc 0 "install"
  run "$AK" doctor
  assert_eq "$(ls -A "$TMPDIR" | wc -l | tr -d ' ')" 0 "agentkit left temp files in TMPDIR: $(ls -A "$TMPDIR" | tr '\n' ' ')"
}

t_install_yes() {
  setup_home
  mkdir -p "$CLAUDE"
  cat > "$CLAUDE/settings.json" <<'EOF'
{"theme": "dark", "permissions": {"allow": ["Bash(ls)"]},
 "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo pre"}]}],
           "SubagentStop": [{"hooks": [{"type": "command", "command": "echo user-stop"}]}]}}
EOF
  printf '# My rules\nBe nice.\n' > "$CLAUDE/CLAUDE.md"
  install_user
  assert_rc 0 "install --yes"
  local f n
  for f in "$AKH"/agents/*.md; do assert_same "$f" "$CLAUDE/agents/$(basename "$f")"; done
  diff -rq -x .DS_Store -x '*.pyc' "$AKH/skills" "$CLAUDE/skills" > "$T/.diff" 2>&1 || fail "skills differ from source: $(cat "$T/.diff")"
  assert_file "$CLAUDE/skills/write-swift/SKILL.md"
  # CLAUDE.md
  assert_eq "$(head -n 1 "$CLAUDE/CLAUDE.md")" "# My rules" "CLAUDE.md first line"
  assert_grep "$CLAUDE/CLAUDE.md" "Be nice."
  assert_eq "$(count_of "$CLAUDE/CLAUDE.md" '<!-- agentkit:start -->')" 1 "start markers"
  assert_eq "$(count_of "$CLAUDE/CLAUDE.md" '<!-- agentkit:end -->')" 1 "end markers"
  assert_grep "$CLAUDE/CLAUDE.md" "# Multi-agent workflow (agentkit)"
  # settings.json
  local s="$CLAUDE/settings.json"
  export AKH
  assert_jtrue "$s" "d['theme'] == 'dark' and d['permissions']['allow'] == ['Bash(ls)']"
  assert_jtrue "$s" "d['hooks']['PreToolUse'][0]['hooks'][0]['command'] == 'echo pre'"
  assert_jtrue "$s" "any(h['command'] == 'echo user-stop' for g in d['hooks']['SubagentStop'] for h in g['hooks'])"
  assert_eq "$(n_src "$s" SubagentStop agentkit-agent-log)" 1 "agentkit SubagentStop entries"
  assert_jtrue "$s" "[g for g in d['hooks']['SubagentStop'] if g.get('_agentkit_source') == 'agentkit-agent-log'][0]['hooks'][0] == {'type': 'command', 'command': 'python3 -I \"' + os.environ['AKH'] + '/hooks/agent-log.py\" check || true', 'timeout': 20}"
  # manifest
  n="$(cd "$AKH" && find agents skills -type f ! -name .DS_Store ! -name '*.pyc' | wc -l | tr -d ' ')"
  assert_jtrue "$CLAUDE/agentkit/manifest.json" "d['agentkit_version'] == '$(tr -d '[:space:]' < "$AKH/VERSION")' and len(d['files']) == $n and 'agents/backend.md' in d['files']"
  # link
  [ -L "$HOME/.local/bin/agentkit" ] || fail "link missing"
  assert_eq "$(readlink "$HOME/.local/bin/agentkit")" "$AKH/bin/agentkit" "link target"
  run "$HOME/.local/bin/agentkit" version
  assert_eq "$OUT" "$(tr -d '[:space:]' < "$AKH/VERSION")" "agentkit version through the link"
  # the changed settings.json and CLAUDE.md were backed up
  [ -n "$(find "$CLAUDE/agentkit/backups" -name settings.json 2> /dev/null)" ] || fail "no settings.json backup"
  [ -n "$(find "$CLAUDE/agentkit/backups" -name CLAUDE.md 2> /dev/null)" ] || fail "no CLAUDE.md backup"
}

t_install_idempotent() {
  setup_home
  install_user
  assert_rc 0 "first install"
  local before
  before="$(snap "$HOME")"
  install_user
  assert_rc 0 "second install"
  assert_contains "0 added, 0 updated"
  assert_contains "already present"
  assert_contains "block already up to date"
  assert_eq "$(snap "$HOME")" "$before" "second install changed files"
  assert_eq "$(n_src "$CLAUDE/settings.json" SubagentStop agentkit-agent-log)" 1 "agentkit entries after two installs"
  assert_eq "$(jval "$CLAUDE/settings.json" "len(d['hooks']['SubagentStop'])")" 1 "SubagentStop groups"
  assert_eq "$(count_of "$CLAUDE/CLAUDE.md" '<!-- agentkit:start -->')" 1 "start markers after two installs"
}

t_install_foreign_files() {
  setup_home
  mkdir -p "$CLAUDE/agents" "$CLAUDE/skills/write-swift"
  echo "my backend" > "$CLAUDE/agents/backend.md"
  echo "my skill" > "$CLAUDE/skills/write-swift/SKILL.md"
  echo "extra" > "$CLAUDE/skills/write-swift/extra.txt"
  install_user
  assert_rc 0 "install with foreign files"
  assert_contains "agents/backend.md exists and is not managed by agentkit; skipped"
  assert_contains "skills/write-swift exists and is not managed by agentkit; skipped"
  assert_eq "$(cat "$CLAUDE/agents/backend.md")" "my backend" "foreign agent kept"
  assert_eq "$(cat "$CLAUDE/skills/write-swift/SKILL.md")" "my skill" "foreign skill kept"
  assert_file "$CLAUDE/skills/write-swift/extra.txt"
  assert_eq "$(ls "$CLAUDE/skills/write-swift" | wc -l | tr -d ' ')" 2 "files in foreign skill folder"
  assert_same "$AKH/agents/frontend.md" "$CLAUDE/agents/frontend.md"
  assert_jtrue "$CLAUDE/agentkit/manifest.json" "'agents/backend.md' not in d['files'] and not any(k.startswith('skills/write-swift/') for k in d['files'])"
  # Uninstall must leave the foreign files alone.
  run "$AK" uninstall --yes
  assert_rc 0 "uninstall"
  assert_eq "$(cat "$CLAUDE/agents/backend.md")" "my backend" "foreign agent survives uninstall"
  assert_file "$CLAUDE/skills/write-swift/SKILL.md"
  # --force: back up, then replace.
  install_user
  install_user --force
  assert_rc 0 "install --force"
  assert_same "$AKH/agents/backend.md" "$CLAUDE/agents/backend.md"
  assert_same "$AKH/skills/write-swift/SKILL.md" "$CLAUDE/skills/write-swift/SKILL.md"
  assert_nofile "$CLAUDE/skills/write-swift/extra.txt"
  assert_eq "$(cat "$(find "$CLAUDE/agentkit/backups" -path '*agents/backend.md' | head -n 1)")" "my backend" "agent backup content"
  assert_eq "$(cat "$(find "$CLAUDE/agentkit/backups" -path '*skills/write-swift/SKILL.md' | head -n 1)")" "my skill" "skill backup content"
  [ -f "$(find "$CLAUDE/agentkit/backups" -path '*skills/write-swift/extra.txt' | head -n 1)" ] || fail "extra.txt not in backup"
}

t_update_merge() {
  setup_home
  mkdir -p "$CLAUDE"
  printf '# My rules\nBe nice.\n' > "$CLAUDE/CLAUDE.md"
  install_user
  assert_rc 0 "install"
  echo "# my edit" >> "$CLAUDE/agents/backend.md"
  echo "# my edit" >> "$CLAUDE/agents/writing.md"
  upstream 'echo "<!-- upstream -->" >> agents/frontend.md
    echo "<!-- upstream -->" >> agents/backend.md
    git rm -q agents/seo.md agents/writing.md
    printf -- "---\nname: newagent\ndescription: x\ntools: Read\n---\nbody\n" > agents/newagent.md
    echo "<!-- upstream -->" >> skills/write-swift/SKILL.md
    echo "upstream snippet line" >> templates/CLAUDE.md.snippet'
  run "$AK" update
  assert_rc 0 "update"
  assert_contains "kept your edited agents/backend.md"
  assert_contains "kept agents/writing.md (removed upstream, but you edited it)"
  assert_grep "$CLAUDE/agents/backend.md" "# my edit"
  assert_nogrep "$CLAUDE/agents/backend.md" "<!-- upstream -->"
  assert_file "$CLAUDE/agents/backend.md.agentkit-new"
  assert_same "$AKH/agents/backend.md" "$CLAUDE/agents/backend.md.agentkit-new"
  assert_same "$AKH/agents/frontend.md" "$CLAUDE/agents/frontend.md"
  assert_grep "$CLAUDE/agents/frontend.md" "<!-- upstream -->"
  assert_same "$AKH/agents/newagent.md" "$CLAUDE/agents/newagent.md"
  assert_nofile "$CLAUDE/agents/seo.md"
  assert_file "$CLAUDE/agents/writing.md"
  assert_same "$AKH/skills/write-swift/SKILL.md" "$CLAUDE/skills/write-swift/SKILL.md"
  assert_grep "$CLAUDE/CLAUDE.md" "upstream snippet line"
  assert_grep "$CLAUDE/CLAUDE.md" "Be nice."
  assert_jtrue "$CLAUDE/agentkit/manifest.json" "'agents/newagent.md' in d['files'] and 'agents/seo.md' not in d['files']"
  # A second update keeps the edit again.
  run "$AK" update
  assert_rc 0 "second update"
  assert_grep "$CLAUDE/agents/backend.md" "# my edit"
  assert_contains "kept your edited agents/backend.md"
  # --force overwrites, with a backup.
  run "$AK" update --force
  assert_rc 0 "update --force"
  assert_same "$AKH/agents/backend.md" "$CLAUDE/agents/backend.md"
  assert_contains "1 replaced (--force)"
  assert_grep "$(find "$CLAUDE/agentkit/backups" -path '*agents/backend.md' | head -n 1)" "# my edit"
}

t_update_not_fast_forward() {
  setup_home
  install_user
  assert_rc 0 "install"
  git -C "$AKH" commit -q --allow-empty -m "local commit"
  upstream 'echo "<!-- upstream -->" >> agents/frontend.md'
  local before
  before="$(snap "$CLAUDE")"
  run "$AK" update
  assert_rc_nz "update with diverged history"
  assert_contains "git pull --ff-only failed"
  assert_contains "cd $AKH && git status"
  assert_eq "$(snap "$CLAUDE")" "$before" "failed update changed files"
  assert_eq "$(git -C "$AKH" log -1 --format=%s)" "local commit" "local commit kept"
  assert_nogrep "$CLAUDE/agents/frontend.md" "<!-- upstream -->"
  # The background form records the failure for the next session.
  run "$AK" update --quiet
  assert_rc_nz "quiet update with diverged history"
  assert_grep "$CLAUDE/agentkit/update-status" "auto-update failed"
}

t_update_not_a_clone() {
  setup_home
  install_user
  rm -rf "$AKH/.git"
  run "$AK" update
  assert_rc_nz "update without a git clone"
  assert_contains "not a git clone"
}

t_auto_update_toggle() {
  setup_home
  install_user
  local s="$CLAUDE/settings.json"
  run "$AK" auto-update status
  assert_eq "$OUT" "auto-update: off" "initial status"
  # No --yes and no terminal: nothing is added.
  run "$AK" auto-update on
  assert_contains "settings.json: skipped"
  assert_eq "$(n_src "$s" SessionStart agentkit-auto-update)" 0 "entries without consent"
  run "$AK" auto-update on --yes
  assert_rc 0 "auto-update on"
  assert_eq "$(n_src "$s" SessionStart agentkit-auto-update)" 1 "SessionStart entries"
  export AKH
  assert_jtrue "$s" "d['hooks']['SessionStart'][0]['hooks'][0]['command'] == '\"' + os.environ['AKH'] + '/hooks/update-check.sh\"'"
  run "$AK" auto-update status
  assert_eq "$OUT" "auto-update: on" "status after on"
  run "$AK" auto-update on --yes
  assert_contains "already present"
  assert_eq "$(n_src "$s" SessionStart agentkit-auto-update)" 1 "entries after a second on"
  run "$AK" auto-update off
  assert_rc 0 "auto-update off"
  run "$AK" auto-update status
  assert_eq "$OUT" "auto-update: off" "status after off"
  assert_jtrue "$s" "'SessionStart' not in d['hooks'] and len(d['hooks']['SubagentStop']) == 1"
  run "$AK" auto-update bogus
  assert_rc_nz "auto-update with a bad subcommand"
}

t_hook_silent_fast_and_runs_update() {
  mk_fake_ak
  AGENTKIT_HOME="$FAKE" run_split bash "$HOOK"
  assert_rc 0 "update-check.sh"
  assert_eq "$(cat "$T/stdout")" "" "stdout of a normal run"
  assert_eq "$(cat "$T/stderr")" "" "stderr of a normal run"
  "$PY" -I -c 'import sys; sys.exit(0 if float(sys.argv[1]) < 1.0 else 1)' "$ELAPSED" || fail "hook took $ELAPSED s, expected < 1 s"
  wait_for "$T/calls" 5 || fail "background update was not started"
  assert_grep "$T/calls" "called update --quiet home=$FAKE"
  local stamp
  stamp="$(cat "$CLAUDE/agentkit/last-update-check")"
  case "$stamp" in '' | *[!0-9]*) fail "stamp is not a number: '$stamp'" ;; esac
}

t_hook_throttle() {
  mk_fake_ak
  local st="$CLAUDE/agentkit/last-update-check" now
  AGENTKIT_HOME="$FAKE" run_split bash "$HOOK"
  wait_lines "$T/calls" 1 5 || fail "first run did not start an update"
  local first
  first="$(cat "$st")"
  AGENTKIT_HOME="$FAKE" run_split bash "$HOOK"
  assert_rc 0 "second run inside the interval"
  sleep 1
  assert_eq "$(nlines "$T/calls")" 1 "updates started inside the interval"
  assert_eq "$(cat "$st")" "$first" "stamp changed inside the interval"
  now="$(date +%s)"
  echo $((now - 100)) > "$st"
  AGENTKIT_UPDATE_INTERVAL=50 AGENTKIT_HOME="$FAKE" run_split bash "$HOOK"
  wait_lines "$T/calls" 2 5 || fail "run with a short interval did not start an update"
  echo $((now - 100)) > "$st"
  AGENTKIT_UPDATE_INTERVAL=1000 AGENTKIT_HOME="$FAKE" run_split bash "$HOOK"
  sleep 1
  assert_eq "$(nlines "$T/calls")" 2 "updates started with a long interval"
  echo "garbage" > "$st"
  AGENTKIT_UPDATE_INTERVAL=abc AGENTKIT_HOME="$FAKE" run_split bash "$HOOK"
  assert_rc 0 "garbage stamp and interval"
  wait_lines "$T/calls" 3 5 || fail "garbage stamp should count as 'never checked'"
}

t_hook_rotates_log() {
  mk_fake_ak
  local log="$CLAUDE/agentkit/update.log" st="$CLAUDE/agentkit/last-update-check" size
  head -c 100000 /dev/zero | tr '\0' 'x' > "$log"
  AGENTKIT_HOME="$FAKE" run_split bash "$HOOK"
  wait_for "$T/calls" 5 || fail "update was not started"
  assert_eq "$(wc -c < "$log" | tr -d ' ')" 100000 "a 100 KB log must not be cut"
  rm -f "$st" "$T/calls"
  { head -c 300000 /dev/zero | tr '\0' 'x'; printf '\nLAST-LINE-MARKER\n'; } > "$log"
  AGENTKIT_HOME="$FAKE" run_split bash "$HOOK"
  assert_rc 0 "run with a big log"
  wait_for "$T/calls" 5 || fail "update was not started"
  size="$(wc -c < "$log" | tr -d ' ')"
  [ "$size" -le 110000 ] && [ "$size" -gt 0 ] || fail "log size after rotation is $size, expected about 102400"
  assert_grep "$log" "LAST-LINE-MARKER"
}

t_hook_status_line_and_noops() {
  mk_fake_ak
  local state="$CLAUDE/agentkit"
  printf 'agentkit: auto-update failed, see x\nsecond line\n' > "$state/update-status"
  echo "$(date +%s)" > "$state/last-update-check"
  AGENTKIT_HOME="$FAKE" run_split bash "$HOOK"
  assert_rc 0 "run with a status file"
  assert_eq "$(cat "$T/stdout")" "agentkit: auto-update failed, see x" "status line"
  assert_nofile "$state/update-status"
  # No state dir: silent no-op. Bin not executable: silent no-op.
  rm -rf "$state" "$T/calls"
  AGENTKIT_HOME="$FAKE" run_split bash "$HOOK"
  assert_rc 0 "no state dir"
  assert_eq "$(cat "$T/stdout")" "" "stdout without a state dir"
  mkdir -p "$state"
  chmod -x "$FAKE/bin/agentkit"
  AGENTKIT_HOME="$FAKE" run_split bash "$HOOK"
  assert_rc 0 "bin not executable"
  assert_eq "$(cat "$T/stdout")" "" "stdout with a bad bin"
  sleep 0.5
  assert_nofile "$T/calls"
}

t_auto_update_end_to_end() {
  setup_home
  install_user
  run "$AK" auto-update on --yes
  assert_rc 0 "auto-update on"
  upstream 'echo "<!-- upstream -->" >> agents/frontend.md'
  local cmd i=0
  cmd="$(jval "$CLAUDE/settings.json" "d['hooks']['SessionStart'][0]['hooks'][0]['command']")"
  AGENTKIT_UPDATE_INTERVAL=0 run_split bash -c "$cmd"
  assert_rc 0 "SessionStart command from settings.json"
  assert_eq "$(cat "$T/stdout")" "" "hook stdout"
  while ! grep -qF "<!-- upstream -->" "$CLAUDE/agents/frontend.md" 2> /dev/null && [ "$i" -lt 200 ]; do sleep 0.1; i=$((i + 1)); done
  assert_grep "$CLAUDE/agents/frontend.md" "<!-- upstream -->"
  wait_bg
  assert_file "$CLAUDE/agentkit/last-update-check"
}

t_hook_markers_stripped() {
  setup_home
  mkdir -p "$CLAUDE"
  cat > "$CLAUDE/settings.json" <<'EOF'
{"hooks": {"SubagentStop": [{"hooks": [{"type": "command", "command": "echo mine-stop"}]}],
           "SessionStart": [{"hooks": [{"type": "command", "command": "/opt/me/my-start.sh"}]}]}}
EOF
  local s="$CLAUDE/settings.json"
  install_user
  assert_rc 0 "install"
  run "$AK" auto-update on --yes
  assert_eq "$(jval "$s" "len(d['hooks']['SubagentStop'])")" 2 "SubagentStop groups after install"
  strip_markers "$s"
  assert_eq "$(n_src "$s" SubagentStop agentkit-agent-log)" 0 "markers after stripping"
  install_user
  assert_rc 0 "install after stripping"
  run "$AK" auto-update on --yes
  assert_rc 0 "auto-update on after stripping"
  assert_eq "$(n_src "$s" SubagentStop agentkit-agent-log)" 1 "restored SubagentStop marker"
  assert_eq "$(n_src "$s" SessionStart agentkit-auto-update)" 1 "restored SessionStart marker"
  assert_eq "$(jval "$s" "len(d['hooks']['SubagentStop'])")" 2 "SubagentStop groups (no duplicates)"
  assert_eq "$(jval "$s" "len(d['hooks']['SessionStart'])")" 2 "SessionStart groups (no duplicates)"
  # Markers gone again: `auto-update off` and uninstall remove only MARKED entries, so unmarked ones stay.
  strip_markers "$s"
  run "$AK" auto-update off
  assert_rc 0 "auto-update off with unmarked entries"
  assert_eq "$(jval "$s" "len(d['hooks']['SessionStart'])")" 2 "SessionStart groups after off (unmarked entry must stay)"
  run "$AK" uninstall --yes
  assert_rc 0 "uninstall"
  assert_eq "$(jval "$s" "len(d['hooks']['SubagentStop'])")" 2 "SubagentStop groups after uninstall (unmarked entry must stay)"
  assert_jtrue "$s" "not any('_agentkit_source' in g for l in d['hooks'].values() for g in l)"
  assert_jtrue "$s" "any(h['command'] == 'echo mine-stop' for g in d['hooks']['SubagentStop'] for h in g['hooks']) and any(h['command'] == '/opt/me/my-start.sh' for g in d['hooks']['SessionStart'] for h in g['hooks'])"
  # With markers, uninstall removes ours and keeps the user's.
  install_user
  run "$AK" auto-update on --yes
  assert_eq "$(n_src "$s" SubagentStop agentkit-agent-log)" 1 "marked entry restored by install"
  run "$AK" uninstall --yes
  assert_eq "$(n_src "$s" SubagentStop agentkit-agent-log)" 0 "marked SubagentStop entry after uninstall"
  assert_eq "$(n_src "$s" SessionStart agentkit-auto-update)" 0 "marked SessionStart entry after uninstall"
}

t_project_scope() {
  setup_home
  install_user
  assert_rc 0 "user install"
  local proj="$T/proj" before after
  mkdir -p "$proj"
  printf '# proj notes\n' > "$proj/CLAUDE.md"
  before="$(snap "$HOME")"
  run "$AK" install --project "$proj" --yes --skip gstack --skip karpathy
  assert_rc 0 "project install"
  assert_same "$AKH/agents/backend.md" "$proj/.claude/agents/backend.md"
  assert_file "$proj/.claude/skills/write-swift/SKILL.md"
  assert_file "$proj/.claude/agentkit/manifest.json"
  assert_grep "$proj/CLAUDE.md" "<!-- agentkit:start -->"
  assert_grep "$proj/CLAUDE.md" "# proj notes"
  assert_eq "$(n_src "$proj/.claude/settings.json" SubagentStop agentkit-agent-log)" 1 "project hook entries"
  assert_eq "$(snap "$HOME")" "$before" "project install touched HOME"
  run "$AK" uninstall --project "$proj" --yes
  assert_rc 0 "project uninstall"
  assert_nofile "$proj/.claude/agents/backend.md"
  assert_nofile "$proj/.claude/skills/write-swift"
  assert_eq "$(cat "$proj/CLAUDE.md")" "# proj notes" "project CLAUDE.md after uninstall"
  assert_eq "$(n_src "$proj/.claude/settings.json" SubagentStop agentkit-agent-log)" 0 "project hook entries after uninstall"
  after="$(snap "$HOME")"
  assert_eq "$after" "$before" "project uninstall touched HOME"
  # --purge with --project keeps the shared clone and the link.
  run "$AK" install --project "$proj" --yes --skip gstack --skip karpathy
  run "$AK" uninstall --project "$proj" --yes --purge
  assert_rc 0 "project uninstall --purge"
  assert_file "$AK"
  [ -L "$HOME/.local/bin/agentkit" ] || fail "--purge --project removed the link"
  assert_eq "$(snap "$HOME")" "$before" "project purge touched HOME"
}

t_uninstall() {
  setup_home
  mkdir -p "$CLAUDE"
  printf '# My rules\nBe nice.\n' > "$CLAUDE/CLAUDE.md"
  echo '{"theme": "dark"}' > "$CLAUDE/settings.json"
  install_user
  assert_rc 0 "install"
  echo "# my edit" >> "$CLAUDE/agents/backend.md"
  local before
  before="$(snap "$HOME")"
  run "$AK" uninstall --dry-run
  assert_rc 0 "uninstall --dry-run"
  assert_contains "[dry-run] remove agents/frontend.md"
  assert_eq "$(snap "$HOME")" "$before" "uninstall --dry-run changed files"
  run "$AK" uninstall --yes
  assert_rc 0 "uninstall"
  assert_contains "Kept because you edited them"
  assert_file "$CLAUDE/agents/backend.md"
  assert_grep "$CLAUDE/agents/backend.md" "# my edit"
  assert_eq "$(ls "$CLAUDE/agents" | wc -l | tr -d ' ')" 1 "agent files left"
  assert_nofile "$CLAUDE/skills/write-swift"
  assert_nofile "$CLAUDE/skills/agent-report"
  assert_eq "$(cat "$CLAUDE/CLAUDE.md")" "$(printf '# My rules\nBe nice.')" "CLAUDE.md after uninstall"
  assert_jtrue "$CLAUDE/settings.json" "d == {'theme': 'dark'}"
  assert_nofile "$CLAUDE/agentkit/manifest.json"
  [ -d "$CLAUDE/agentkit/backups" ] || fail "backups folder should be kept"
  assert_file "$AK"
  [ -L "$HOME/.local/bin/agentkit" ] || fail "link removed without --purge"
}

t_uninstall_purge() {
  setup_home
  install_user
  assert_rc 0 "install"
  run "$HOME/.local/bin/agentkit" uninstall --purge --yes
  assert_rc 0 "uninstall --purge"
  assert_nofile "$AKH"
  assert_nofile "$HOME/.local/bin/agentkit"
  assert_nofile "$CLAUDE/agentkit"
  assert_nofile "$CLAUDE/agents/backend.md"
  assert_nofile "$CLAUDE/CLAUDE.md"
}

t_doctor() {
  setup_home
  install_user
  assert_rc 0 "install"
  run "$AK" doctor
  assert_rc 0 "doctor after install"
  assert_contains "all required checks passed"
  assert_contains "SubagentStop hook in settings.json"
  # Broken: AGENTKIT_HOME does not exist.
  AGENTKIT_HOME="$T/nowhere" run "$AK" doctor
  assert_rc_nz "doctor with a missing AGENTKIT_HOME"
  assert_contains "AGENTKIT_HOME not found"
  # Broken: an installed agent was deleted.
  rm "$CLAUDE/agents/backend.md"
  run "$AK" doctor
  assert_rc_nz "doctor with a missing agent"
  assert_contains "agent backend: missing"
  # Broken: python3 is not on PATH.
  mkdir -p "$T/nopy"
  local f
  for f in "$REALBIN"/*; do [ "$(basename "$f")" = python3 ] || ln -s "$f" "$T/nopy/$(basename "$f")"; done
  PATH="$T/nopy" run bash "$AK" doctor
  assert_rc_nz "doctor without python3"
  assert_contains "python3 >= 3.9 not found"
  # Not installed at all.
  rm -rf "$CLAUDE"
  run "$AK" doctor
  assert_rc_nz "doctor without an install"
  assert_contains "not installed in"
}

t_log_commands() {
  local f1="$T/e1.json" f2="$T/e2.json" id
  setup_home
  run "$AK" log add --agent backend --rule destructive --evidence "rm -rf $HOME/secret/proj/file.txt token=abcdefghijk12345 bob@example.com"
  assert_rc 0 "log add"
  id="$OUT"
  run "$AK" log report
  assert_rc 0 "log report"
  assert_contains "agent: backend"
  assert_contains "rule: destructive"
  assert_contains "$id"
  run "$AK" log export --out "$f1"
  assert_rc 0 "log export"
  assert_jtrue "$f1" "d['schema'] == 'agentkit-log-export/1' and d['groups'][0]['agent'] == 'backend' and d['groups'][0]['count'] == 1"
  assert_nogrep "$f1" "$(basename "$T")"
  assert_nogrep "$f1" "$HOME"
  assert_nogrep "$f1" "abcdefghijk12345"
  assert_nogrep "$f1" "bob@example.com"
  assert_nogrep "$f1" '"session_id"'
  assert_nogrep "$f1" '"cwd"'
  assert_nogrep "$f1" '"transcript"'
  # A second reporter (separate log dir) with the same issue.
  AGENT_LOG_DIR="$T/agent-log2" run "$AK" log add --agent backend --rule destructive --evidence "git push -f"
  AGENT_LOG_DIR="$T/agent-log2" run "$AK" log export --out "$f2"
  assert_rc 0 "second export"
  run "$AK" log merge "$f1" "$f2"
  assert_rc 0 "log merge"
  assert_contains "files: 2  reporters: 2"
  assert_contains "count: 2  reporters: 2"
  run "$AK" log merge "$f1" "$f1"
  assert_contains "reporters: 1"
  echo "not json" > "$T/bad.json"
  run "$AK" log merge "$f1" "$T/bad.json"
  assert_rc 0 "merge with one bad file"
  assert_contains "skip $T/bad.json"
  run "$AK" log merge "$T/bad.json"
  assert_rc_nz "merge with no valid file"
  # resolve hides the issue from report, --all shows it.
  run "$AK" log resolve "$id"
  assert_rc 0 "log resolve"
  run "$AK" log report
  assert_not_contains "rule: destructive"
  run "$AK" log report --all
  assert_contains "[resolved]"
  run "$AK" log resolve nosuchid
  assert_rc_nz "resolve of an unknown id"
}

t_feedback() {
  setup_home
  run "$AK" log add --agent backend --rule destructive --evidence "rm -rf $HOME/a/b/c.txt"
  # No gh: print the URL, send nothing.
  run "$AK" feedback
  assert_rc 0 "feedback without gh"
  assert_contains "gh not found"
  assert_contains "https://github.com/IbrahimHosseini/agentkit/issues/new"
  mk_gh
  # gh present, no terminal and no --yes: not sent.
  run "$AK" feedback
  assert_rc 0 "feedback without consent"
  assert_contains "Not sent"
  assert_nofile "$STUB_LOG"
  # --yes: gh is called for the right repo, with the export as the body.
  run "$AK" feedback --yes
  assert_rc 0 "feedback --yes"
  assert_grep "$STUB_LOG" "--repo IbrahimHosseini/agentkit"
  assert_grep "$STUB_LOG" "issue create"
  assert_grep "$STUB_LOG.body" '"schema": "agentkit-log-export/1"'
  assert_nogrep "$STUB_LOG.body" "$HOME"
  # The first call fails (label missing): it retries without --label.
  rm -f "$STUB_LOG"
  STUB_GH_FAIL_LABEL=1 run "$AK" feedback --yes
  assert_rc 0 "feedback with a missing label"
  assert_eq "$(nlines "$STUB_LOG")" 2 "gh calls"
  assert_eq "$(sed -n 1p "$STUB_LOG" | grep -c -- '--label')" 1 "first call has --label"
  assert_eq "$(sed -n 2p "$STUB_LOG" | grep -c -- '--label')" 0 "second call has no --label"
}

t_dependency_stubs() {
  setup_home
  mk_claude
  local m=https://github.com/forrestchang/andrej-karpathy-skills.git
  # Plugin missing: add the marketplace, then install.
  run bash "$AKH/install.sh" --yes --skip gstack
  assert_rc 0 "install with a fake claude"
  assert_grep "$STUB_LOG" "claude plugin list"
  assert_grep "$STUB_LOG" "claude plugin marketplace add $m"
  assert_grep "$STUB_LOG" "claude plugin install andrej-karpathy-skills@karpathy-skills"
  # Plugin already installed: no add, no install.
  rm -f "$STUB_LOG"
  STUB_PLUGIN_LIST="andrej-karpathy-skills@karpathy-skills" run bash "$AKH/install.sh" --yes --skip gstack
  assert_contains "karpathy: plugin already installed"
  assert_nogrep "$STUB_LOG" "plugin install"
  # No consent: nothing is installed.
  rm -f "$STUB_LOG"
  run bash "$AKH/install.sh" --skip gstack
  assert_contains "karpathy: skipped. Manual:"
  assert_nogrep "$STUB_LOG" "plugin install"
  assert_nogrep "$STUB_LOG" "marketplace add"
  # gstack: no bun on PATH, so nothing is cloned and nothing needs the network.
  run bash "$AKH/install.sh" --yes --skip karpathy
  assert_rc 0 "install with gstack and no bun"
  assert_contains "gstack: bun not found"
  assert_nofile "$CLAUDE/skills/gstack"
  # gstack: declined.
  run bash "$AKH/install.sh" --skip karpathy
  assert_contains "gstack: skipped. Manual:"
  assert_nofile "$CLAUDE/skills/gstack"
  # gstack: already present.
  mkdir -p "$CLAUDE/skills/gstack"
  run bash "$AKH/install.sh" --yes --skip karpathy
  assert_contains "gstack: already installed"
  # Dry run prints the commands and runs nothing.
  rm -f "$STUB_LOG"
  rm -rf "$CLAUDE/skills/gstack"
  run bash "$AKH/install.sh" --dry-run
  assert_contains "[dry-run] gstack: git clone"
  assert_contains "[dry-run] karpathy: claude plugin marketplace add"
  assert_nogrep "$STUB_LOG" "plugin install"
  assert_nofile "$CLAUDE/skills/gstack"
}

t_subagent_stop_command_runs() {
  setup_home
  install_user
  assert_rc 0 "install"
  local cmd tp="$T/transcript/agent-aaa.jsonl"
  cmd="$(jval "$CLAUDE/settings.json" "d['hooks']['SubagentStop'][0]['hooks'][0]['command']")"
  mkdir -p "$T/transcript"
  printf '%s\n' '{"type":"user","message":{"content":"add a function"}}' \
    '{"type":"assistant","message":{"content":[{"type":"text","text":"done"}]}}' > "$tp"
  printf '{"session_id":"s1","cwd":"%s","agent_id":"aaa","agent_type":"backend","agent_transcript_path":"%s","last_assistant_message":"done"}' \
    "$T/work" "$tp" > "$T/stdin.json"
  RUN_STDIN="$T/stdin.json" run_split bash -c "$cmd"
  assert_rc 0 "SubagentStop command from settings.json"
  assert_contains '"systemMessage"'
  assert_contains "report-incomplete"
  assert_grep "$AGENT_LOG_DIR/issues.jsonl" '"rule": "report-incomplete"'
  # Garbage input: the script itself still exits 0 and logs the error.
  echo "not json" > "$T/garbage"
  RUN_STDIN="$T/garbage" run python3 -I "$AKH/hooks/agent-log.py" check
  assert_rc 0 "agent-log.py check with garbage input"
  assert_file "$AGENT_LOG_DIR/hook-errors.log"
}

t_bad_settings_untouched() {
  setup_home
  mkdir -p "$CLAUDE"
  printf '{not json' > "$CLAUDE/settings.json"
  install_user
  assert_rc 0 "install with an invalid settings.json"
  assert_contains "cannot read"
  assert_eq "$(cat "$CLAUDE/settings.json")" "{not json" "invalid settings.json must stay as it was"
  assert_same "$AKH/agents/backend.md" "$CLAUDE/agents/backend.md"
}

t_cli_errors() {
  setup_home
  run "$AK" bogus
  assert_rc_nz "unknown command"
  run "$AK" install --bogus
  assert_rc_nz "unknown option"
  run "$AK" install --skip nothing
  assert_rc_nz "unknown skip step"
  run "$AK" install --project "$T/does-not-exist" --yes --skip gstack --skip karpathy
  assert_rc_nz "missing project dir"
  run "$AK" update
  assert_rc_nz "update before install"
  assert_contains "not installed"
  run "$AK" uninstall --yes
  assert_rc_nz "uninstall before install"
  run "$AK" help
  assert_rc 0 "help"
  assert_contains "agentkit install"
}

t_symlinked_skill_not_adopted() {
  setup_home
  mkdir -p "$CLAUDE/skills" "$T/outside"
  cp -R "$AKH/skills/write-swift" "$T/outside/write-swift"
  ln -s "$T/outside/write-swift" "$CLAUDE/skills/write-swift"
  local tsnap
  tsnap="$(snap "$T/outside")"
  install_user
  assert_rc 0 "install with a symlinked skill"
  assert_contains "skills/write-swift is a symlink; skipped"
  [ -L "$CLAUDE/skills/write-swift" ] || fail "the symlink was replaced without --force"
  assert_jtrue "$CLAUDE/agentkit/manifest.json" "not any(k.startswith('skills/write-swift/') for k in d['files'])"
  assert_file "$CLAUDE/skills/agent-report/SKILL.md"
  run "$AK" uninstall --yes
  assert_rc 0 "uninstall"
  [ -L "$CLAUDE/skills/write-swift" ] || fail "uninstall removed the symlink"
  assert_eq "$(snap "$T/outside")" "$tsnap" "uninstall changed the link target"
  install_user --force
  assert_rc 0 "install --force over a symlink"
  [ ! -L "$CLAUDE/skills/write-swift" ] || fail "--force did not replace the link"
  assert_same "$AKH/skills/write-swift/SKILL.md" "$CLAUDE/skills/write-swift/SKILL.md"
  assert_eq "$(snap "$T/outside")" "$tsnap" "--force changed the link target"
  local b
  b="$(find "$CLAUDE/agentkit/backups" -path '*skills/write-swift' 2> /dev/null | head -n 1)"
  { [ -n "$b" ] && [ -L "$b" ]; } || fail "the link was not backed up as a link (found: '$b')"
}

t_deleted_file_stays_deleted() {
  setup_home
  install_user
  assert_rc 0 "install"
  rm "$CLAUDE/agents/frontend.md"
  upstream 'echo "<!-- one -->" >> agents/backend.md'
  run "$AK" update
  assert_rc 0 "first update"
  assert_contains "kept removed: agents/frontend.md"
  assert_nofile "$CLAUDE/agents/frontend.md"
  assert_grep "$CLAUDE/agents/backend.md" "<!-- one -->"
  upstream 'echo "<!-- two -->" >> agents/frontend.md; echo "<!-- two -->" >> agents/backend.md'
  run "$AK" update
  assert_rc 0 "second update"
  assert_nofile "$CLAUDE/agents/frontend.md"
  assert_grep "$CLAUDE/agents/backend.md" "<!-- two -->"
  assert_jtrue "$CLAUDE/agentkit/manifest.json" "'agents/frontend.md' in d['files']"
}

t_purge_keeps_non_default_checkout() {
  # A checkout that is not ~/.agentkit must survive --purge.
  git clone -q "$AGENTKIT_REPO" "$T/dev" || { echo "clone failed"; exit 99; }
  AGENTKIT_HOME="$T/dev" run "$T/dev/bin/agentkit" install --yes --skip gstack --skip karpathy
  assert_rc 0 "install from a dev checkout"
  AGENTKIT_HOME="$T/dev" run "$T/dev/bin/agentkit" uninstall --purge --yes
  assert_rc 0 "uninstall --purge"
  assert_file "$T/dev/bin/agentkit"
  assert_file "$T/dev/VERSION"
  assert_contains "Kept $T/dev"
  assert_nofile "$CLAUDE/agentkit"
  # The same without AGENTKIT_HOME set (location found from the script path).
  run "$T/dev/bin/agentkit" install --yes --skip gstack --skip karpathy
  run "$T/dev/bin/agentkit" uninstall --purge --yes
  assert_file "$T/dev/bin/agentkit"
  # The default clone is removed (see also t_uninstall_purge).
  setup_home
  install_user
  run "$AK" uninstall --purge --yes
  assert_rc 0 "purge of the default clone"
  assert_nofile "$AKH"
  assert_file "$T/dev/bin/agentkit"
}

t_feedback_nothing_to_send() {
  setup_home
  mk_gh
  run "$AK" feedback --yes
  assert_rc 0 "feedback with an empty log"
  assert_contains "Nothing to send"
  assert_nofile "$STUB_LOG"
  # Only resolved issues: still nothing to send.
  run "$AK" log add --agent backend --rule destructive --evidence "x"
  run "$AK" log resolve "$OUT"
  run "$AK" feedback --yes
  assert_contains "Nothing to send"
  assert_nofile "$STUB_LOG"
}

t_uninstall_keeps_user_agentlog_hook() {
  setup_home
  install_user
  assert_rc 0 "install"
  local s="$CLAUDE/settings.json"
  "$PY" -I -c '
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["hooks"]["SubagentStop"].append({"hooks": [{"type": "command", "command": "python3 -I ~/.claude/hooks/agent-log.py check || true"}]})
json.dump(d, open(p, "w"), indent=2)
' "$s"
  run "$AK" uninstall --yes
  assert_rc 0 "uninstall"
  assert_eq "$(n_src "$s" SubagentStop agentkit-agent-log)" 0 "marked entry after uninstall"
  assert_jtrue "$s" "d['hooks']['SubagentStop'] == [{'hooks': [{'type': 'command', 'command': 'python3 -I ~/.claude/hooks/agent-log.py check || true'}]}]"
}

t_update_refreshes_marked_hooks() {
  setup_home
  install_user
  run "$AK" auto-update on --yes
  local s="$CLAUDE/settings.json"
  export AKH
  # Point both marked entries to an old path.
  "$PY" -I -c '
import json, sys
p = sys.argv[1]
d = json.load(open(p))
for g in d["hooks"]["SubagentStop"]:
    g["hooks"][0]["command"] = "python3 -I \"/old/place/hooks/agent-log.py\" check || true"
for g in d["hooks"]["SessionStart"]:
    g["hooks"][0]["command"] = "\"/old/place/hooks/update-check.sh\""
json.dump(d, open(p, "w"), indent=2)
' "$s"
  run "$AK" update
  assert_rc 0 "update"
  assert_contains "refreshed agentkit-agent-log"
  assert_contains "refreshed agentkit-auto-update"
  assert_jtrue "$s" "d['hooks']['SubagentStop'][0]['hooks'][0]['command'] == 'python3 -I \"' + os.environ['AKH'] + '/hooks/agent-log.py\" check || true'"
  assert_jtrue "$s" "d['hooks']['SessionStart'][0]['hooks'][0]['command'] == '\"' + os.environ['AKH'] + '/hooks/update-check.sh\"'"
  assert_eq "$(n_src "$s" SubagentStop agentkit-agent-log)" 1 "entries after refresh"
  # --quiet never adds a missing entry (the user removed them on purpose).
  "$PY" -I -c '
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["hooks"] = {}
json.dump(d, open(p, "w"), indent=2)
' "$s"
  run "$AK" update --quiet
  assert_rc 0 "quiet update"
  assert_jtrue "$s" "d['hooks'] == {}"
  run "$AK" update
  assert_jtrue "$s" "d['hooks'] == {}"
  # An unmarked entry with an old path is not touched either.
  "$PY" -I -c '
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["hooks"] = {"SubagentStop": [{"hooks": [{"type": "command", "command": "python3 -I \"/old/place/hooks/agent-log.py\" check || true", "timeout": 20}]}]}
json.dump(d, open(p, "w"), indent=2)
' "$s"
  run "$AK" update
  assert_jtrue "$s" "'/old/place/' in d['hooks']['SubagentStop'][0]['hooks'][0]['command'] and '_agentkit_source' not in d['hooks']['SubagentStop'][0]"
}

t_install_existing_link() {
  setup_home
  mkdir -p "$HOME/.local/bin" "$T/other"
  echo '#!/bin/sh' > "$T/other/agentkit"
  chmod +x "$T/other/agentkit"
  ln -s "$T/other/agentkit" "$HOME/.local/bin/agentkit"
  # No terminal and no --yes: left alone, with a warning.
  run bash "$AKH/install.sh" --skip gstack --skip karpathy
  assert_rc 0 "install with a foreign link"
  assert_contains "warning: left $HOME/.local/bin/agentkit as it is"
  assert_eq "$(readlink "$HOME/.local/bin/agentkit")" "$T/other/agentkit" "foreign link target"
  # A regular file is left alone too.
  rm "$HOME/.local/bin/agentkit"
  echo "mine" > "$HOME/.local/bin/agentkit"
  run bash "$AKH/install.sh" --skip gstack --skip karpathy
  assert_contains "warning: left $HOME/.local/bin/agentkit as it is (it is a regular file)"
  assert_eq "$(cat "$HOME/.local/bin/agentkit")" "mine" "regular file kept"
  # Dry run only reports.
  run bash "$AKH/install.sh" --dry-run --skip gstack --skip karpathy
  assert_contains "would ask before replacing"
  assert_eq "$(cat "$HOME/.local/bin/agentkit")" "mine" "regular file kept by dry run"
  # With --yes the file is backed up and replaced by our link.
  run bash "$AKH/install.sh" --yes --skip gstack --skip karpathy
  assert_rc 0 "install --yes over a regular file"
  assert_eq "$(readlink "$HOME/.local/bin/agentkit")" "$AKH/bin/agentkit" "link after --yes"
  assert_eq "$(cat "$HOME/.local/bin/agentkit.bak-"*)" "mine" "backup of the regular file"
}

t_claude_md_duplicate_heading_warns() {
  setup_home
  mkdir -p "$CLAUDE"
  printf '# Multi-agent workflow\nmy own version\n' > "$CLAUDE/CLAUDE.md"
  run bash "$AKH/install.sh" --dry-run --skip gstack --skip karpathy
  assert_contains "already has a '# Multi-agent workflow' section outside the agentkit markers"
  assert_eq "$(count_of "$CLAUDE/CLAUDE.md" 'agentkit:start')" 0 "dry run wrote the block"
  install_user
  assert_rc 0 "install"
  assert_contains "WARNING:"
  assert_contains "already has a '# Multi-agent workflow' section outside the agentkit markers"
  assert_grep "$CLAUDE/CLAUDE.md" "my own version"
  # No warning when the heading is only inside our block.
  rm -rf "$CLAUDE" "$HOME/.local"
  install_user
  assert_not_contains "WARNING:" "clean install"
}

# ------------------------------------------------------------------ requirements
t_requirements_missing_agent_cli() {
  setup_home
  rm -f "$T/stubs/claude"
  mk_curl
  local before
  before="$(snap "$HOME")"
  run "$AK" install --yes --skip gstack --skip karpathy
  assert_rc_nz "install without claude and codex"
  assert_contains "Requirements:"
  assert_match '^  \+ git +[0-9]' "git row"
  assert_match '^  x claude +not found, one of claude or codex is required' "claude row"
  assert_match '^  x codex +not found, one of claude or codex is required' "codex row"
  assert_contains "How to install what is missing:"
  assert_contains "curl -fsSL https://claude.ai/install.sh | bash"
  assert_contains "downloads and runs a remote script"
  assert_contains "https://github.com/openai/codex"
  assert_contains "requirements are not met"
  # --yes never runs a remote script, so curl is never called.
  assert_contains "No TTY: not running a remote script"
  assert_nofile "$T/curl.log"
  assert_eq "$(snap "$HOME")" "$before" "a failed requirements check changed files"
  assert_nofile "$CLAUDE"
  assert_nofile "$CODEX"
  # The bootstrap script checks too, before it links or installs anything.
  run bash "$AKH/install.sh" --yes --skip gstack --skip karpathy
  assert_rc_nz "install.sh without claude and codex"
  assert_contains "requirements are not met"
  assert_nofile "$T/curl.log"
  assert_nofile "$HOME/.local/bin/agentkit"
}

t_requirements_missing_git() {
  setup_home
  no_tool git
  run "$AK" install --yes --skip gstack --skip karpathy
  assert_rc_nz "install without git"
  assert_match '^  x git +not found, required' "git row"
  assert_match '^  \+ python3 +3' "python3 row"
  assert_contains "https://git-scm.com/downloads"
  assert_contains "requirements are not met"
  assert_nofile "$CLAUDE"
}

t_requirements_other_agent_is_enough() {
  setup_home
  rm -f "$T/stubs/claude"
  mk_codex
  # No --target: either agent is enough.
  run "$AK" install --yes --skip gstack --skip karpathy
  assert_rc 0 "install with codex only"
  assert_match '^  x claude +not found, optional \(the other agent is installed\)' "claude row"
  assert_match '^  \+ codex ' "codex row"
  assert_not_contains "How to install what is missing:"
  assert_file "$CODEX/agents/backend.toml"
  assert_nofile "$CLAUDE"
  # --target codex: claude is not needed at all.
  rm -rf "$CODEX"
  run "$AK" install --target codex --yes --skip gstack --skip karpathy
  assert_rc 0 "install --target codex with codex only"
  assert_match '^  x claude +not found, optional \(not needed for this target\)' "claude row"
  assert_file "$CODEX/agents/backend.toml"
}
t_requirements_dry_run_installs_nothing() {
  setup_home
  rm -f "$T/stubs/claude"
  mk_curl
  local before
  before="$(snap "$HOME")"
  run "$AK" install --dry-run --yes --skip gstack --skip karpathy
  assert_rc_nz "dry run with unmet requirements"
  assert_contains "Requirements:"
  assert_contains "How to install what is missing:"
  assert_not_contains "Running:"
  assert_nofile "$T/curl.log"
  assert_eq "$(snap "$HOME")" "$before" "dry run changed files"
  run bash "$AKH/install.sh" --dry-run --yes --skip gstack --skip karpathy
  assert_rc_nz "install.sh dry run with unmet requirements"
  assert_not_contains "Running:"
  assert_nofile "$T/curl.log"
  assert_eq "$(snap "$HOME")" "$before" "install.sh dry run changed files"
}

t_requirements_ok_skips_check_not_detection() {
  setup_home
  rm -f "$T/stubs/claude"
  mk_codex
  # AGENTKIT_REQS_OK=1 skips the check and its output, but the CLIs found still pick the targets.
  AGENTKIT_REQS_OK=1 run "$AK" install --yes --skip gstack --skip karpathy
  assert_rc 0 "install with the check skipped"
  assert_not_contains "Requirements:"
  assert_file "$CODEX/agents/backend.toml"
  assert_nofile "$CLAUDE"
  # With no agent CLI at all, the default is claude (assumption: documented fallback in select_targets).
  rm -f "$T/stubs/codex"
  rm -rf "$CODEX"
  AGENTKIT_REQS_OK=1 run "$AK" install --yes --skip gstack --skip karpathy
  assert_rc 0 "install with the check skipped and no CLI"
  assert_file "$CLAUDE/agents/backend.md"
  assert_nofile "$CODEX"
}

t_requirements_doctor() {
  setup_home
  install_user
  assert_rc 0 "install"
  run "$AK" doctor
  assert_rc 0 "doctor after install"
  assert_eq "$(printf '%s\n' "$OUT" | head -n 1)" "agentkit $(tr -d '[:space:]' < "$AKH/VERSION") doctor" "doctor header"
  assert_contains "Requirements:"
  assert_match '^  \+ git +[0-9]' "git row"
  assert_match '^  \+ python3 +3' "python3 row"
  assert_match '^  \+ claude' "claude row"
  assert_match '^  x codex +not found, optional \(the other agent is installed\)' "codex row"
  assert_contains "target claude: $CLAUDE"
  assert_not_contains "ok    python3"
  assert_not_contains "ok    git"
  assert_not_contains "claude CLI"
  # No agent CLI: the requirements fail the doctor.
  rm -f "$T/stubs/claude"
  run "$AK" doctor
  assert_rc_nz "doctor without an agent CLI"
  assert_contains "one of claude or codex is required"
  assert_contains "requirements not met"
  assert_contains "required check(s) failed"
}

# ------------------------------------------------------------------ output
t_output_plain_has_no_ansi() {
  setup_home
  install_user
  assert_rc 0 "install"
  has_esc "$OUT" && fail "install output has an escape sequence"
  case "$OUT" in *$'\r'*) fail "install output has a carriage return" ;; esac
  run "$AK" doctor
  has_esc "$OUT" && fail "doctor output has an escape sequence"
  run "$AK" update
  has_esc "$OUT" && fail "update output has an escape sequence"
  NO_COLOR=1 run "$AK" install --yes --skip gstack --skip karpathy
  has_esc "$OUT" && fail "NO_COLOR output has an escape sequence"
  run "$AK" uninstall --yes
  has_esc "$OUT" && fail "uninstall output has an escape sequence"
  # The same checks can fail: with a terminal and no NO_COLOR the output has colors.
}

t_output_terminal_color_and_no_color() {
  setup_home
  run_pty "$AK" install --yes --skip gstack --skip karpathy
  assert_rc 0 "install on a terminal"
  has_esc "$OUT" || fail "no color on a terminal"
  assert_contains "( o.o )" "cat logo on a terminal"
  assert_contains "Requirements:"
  # NO_COLOR: no escape sequence even on a terminal.
  run_pty env NO_COLOR=1 "$AK" install --yes --skip gstack --skip karpathy
  assert_rc 0 "install on a terminal with NO_COLOR"
  has_esc "$OUT" && fail "NO_COLOR ignored on a terminal"
  assert_contains "Requirements:"
  assert_not_contains "( o.o )"
  run_pty env NO_COLOR=1 "$AK" doctor
  has_esc "$OUT" && fail "NO_COLOR ignored by doctor on a terminal"
  # --quiet: no output at all on success, even on a terminal.
  run_pty "$AK" install --quiet --yes --skip gstack --skip karpathy
  assert_rc 0 "quiet install on a terminal"
  assert_eq "$OUT" "" "quiet install on a terminal printed something"
}

t_output_quiet() {
  setup_home
  # Hooks are skipped here: see t_output_quiet_install for the hook entry text.
  run "$AK" install --quiet --yes --skip gstack --skip karpathy --skip hooks
  assert_rc 0 "quiet install"
  assert_eq "$OUT" "" "quiet install printed something"
  assert_file "$CLAUDE/agents/backend.md"
  run "$AK" doctor --quiet
  assert_rc 0 "quiet doctor"
  run "$AK" uninstall --quiet --yes
  assert_rc 0 "quiet uninstall"
  assert_eq "$OUT" "" "quiet uninstall printed something"
  assert_nofile "$CLAUDE/agents/backend.md"
  # Codex too.
  mk_codex
  run "$AK" install --quiet --target codex --yes --skip gstack --skip karpathy
  assert_rc 0 "quiet codex install"
  assert_eq "$OUT" "" "quiet codex install printed something"
  assert_file "$CODEX/agents/backend.toml"
  run "$AK" uninstall --quiet --target codex --yes
  assert_eq "$OUT" "" "quiet codex uninstall printed something"
  # Errors still print.
  rm -f "$T/stubs/claude" "$T/stubs/codex"
  run "$AK" install --quiet --yes --skip gstack --skip karpathy
  assert_rc_nz "quiet install without an agent CLI"
  assert_contains "requirements are not met"
  run "$AK" install --quiet --target bogus
  assert_rc_nz "quiet install with a bad target"
  assert_contains "--target: unknown value 'bogus'"
}

# --quiet must print nothing on success.
t_output_quiet_install() {
  setup_home
  run "$AK" install --quiet --yes --skip gstack --skip karpathy
  assert_rc 0 "quiet install"
  assert_eq "$OUT" "" "quiet install printed something"
  assert_file "$CLAUDE/agents/backend.md"
  assert_eq "$(n_src "$CLAUDE/settings.json" SubagentStop agentkit-agent-log)" 1 "hook entry"
}

t_output_markers_and_table() {
  setup_home
  run "$AK" install --yes --skip gstack --skip karpathy
  assert_rc 0 "install"
  assert_eq "$(printf '%s\n' "$OUT" | head -n 1)" "agentkit $(tr -d '[:space:]' < "$AKH/VERSION")" "logo line"
  [ "$(line_of "Requirements:")" -lt "$(line_of "installing into")" ] || fail "Requirements: must print before the install starts"
  [ "$(line_of "Requirements:")" -gt 1 ] || fail "the logo line must print before Requirements:"
  assert_contains "agentkit $(tr -d '[:space:]' < "$AKH/VERSION"): installing into $CLAUDE"
  assert_contains "[1/3] Claude: agents and skills"
  assert_contains "[2/3] Claude: CLAUDE.md"
  assert_contains "[3/3] Claude: SubagentStop hook"
  assert_contains "  + agents/backend.md"
  assert_contains "  + skills/write-swift/SKILL.md"
  assert_match '^  \+ Files: [0-9]+ added, 0 updated' "files line"
  assert_match '^TARGET +ITEM +STATUS$' "table header"
  assert_match '^claude +files +[0-9]+ added, 0 updated, 0 unchanged$' "files row"
  assert_match '^claude +CLAUDE.md +added$' "CLAUDE.md row"
  assert_match '^claude +SubagentStop hook +added$' "hook row"
  # Second run: unchanged files print no line, unchanged results use "=".
  install_user
  assert_rc 0 "second install"
  assert_not_contains "agents/backend.md"
  assert_not_contains "skills/write-swift"
  assert_contains "  = Files: 0 added, 0 updated"
  assert_contains "  = CLAUDE.md: block already up to date"
  assert_contains "  = settings.json: agentkit-agent-log already present"
  assert_match '^claude +files +0 added, 0 updated, [0-9]+ unchanged$' "files row (second run)"
  assert_match '^claude +CLAUDE.md +unchanged$' "CLAUDE.md row (second run)"
  # Skips and updates.
  echo "# my edit" >> "$CLAUDE/agents/backend.md"
  upstream 'echo "<!-- upstream -->" >> agents/frontend.md
    echo "<!-- upstream -->" >> agents/backend.md
    git rm -q agents/seo.md
    printf -- "---\nname: newagent\ndescription: x\ntools: Read\nmodel: sonnet\n---\nbody\n" > agents/newagent.md'
  run "$AK" update
  assert_rc 0 "update"
  assert_contains "  + agents/frontend.md (updated)"
  assert_contains "  + agents/newagent.md"
  assert_contains "  + agents/seo.md (removed upstream)"
  assert_contains "  ! kept your edited agents/backend.md; new version in agents/backend.md.agentkit-new"
  assert_not_contains "agents/debugger.md"
  run "$AK" update --force
  assert_rc 0 "update --force"
  assert_contains "  + agents/backend.md (replaced)"
}

# ------------------------------------------------------------------ target detection
t_target_default_detection() {
  setup_home
  # Only claude on PATH (the default stub): claude only.
  run "$AK" install --yes --skip gstack --skip karpathy
  assert_rc 0 "install with claude only"
  assert_file "$CLAUDE/agents/backend.md"
  assert_nofile "$CODEX"
  assert_not_contains "installing into $CODEX"
  # Add codex: update and doctor still follow the manifests, so claude only.
  mk_codex
  run "$AK" update
  assert_rc 0 "update"
  assert_not_contains "codex"
  assert_nofile "$CODEX"
  run "$AK" doctor
  assert_not_contains "target codex"
  # Both CLIs: install picks both.
  run "$AK" uninstall --yes
  run "$AK" install --yes --skip gstack --skip karpathy
  assert_rc 0 "install with both CLIs"
  assert_contains "installing into $CLAUDE"
  assert_contains "installing into $CODEX"
  assert_file "$CLAUDE/agents/backend.md"
  assert_file "$CODEX/agents/backend.toml"
  # Both are installed now: update and doctor cover both.
  run "$AK" doctor
  assert_rc 0 "doctor with both targets"
  assert_contains "target claude: $CLAUDE"
  assert_contains "target codex: $CODEX"
  run "$AK" update
  assert_rc 0 "update with both targets"
  assert_contains "claude: $CLAUDE"
  assert_contains "codex: $CODEX"
  # --target narrows it.
  run "$AK" doctor --target codex
  assert_contains "target codex: $CODEX"
  assert_not_contains "target claude"
}

t_target_codex_only_cli() {
  setup_home
  rm -f "$T/stubs/claude"
  mk_codex
  run "$AK" install --yes --skip gstack --skip karpathy
  assert_rc 0 "install with codex only"
  assert_file "$CODEX/agents/backend.toml"
  assert_nofile "$CLAUDE"
  assert_not_contains "karpathy"
}

t_target_explicit_without_cli() {
  setup_home
  # --target codex needs the codex CLI: the requirements check fails and nothing is written.
  local before
  before="$(snap "$HOME")"
  run "$AK" install --target codex --yes --skip gstack --skip karpathy
  assert_rc_nz "install --target codex without the CLI"
  assert_match '^  x codex +not found, required' "codex row"
  assert_contains "requirements are not met"
  assert_eq "$(snap "$HOME")" "$before" "a failed install changed files"
  assert_nofile "$CODEX"
  # With the check skipped (AGENTKIT_REQS_OK=1): warn, install anyway.
  AGENTKIT_REQS_OK=1 run "$AK" install --target codex --yes --skip gstack --skip karpathy
  assert_rc 0 "install --target codex with the check skipped"
  assert_contains "codex CLI not found; installing for --target codex anyway"
  assert_file "$CODEX/agents/backend.toml"
  assert_nofile "$CLAUDE"
  # --target claude with codex present: codex is left alone.
  rm -rf "$CODEX"
  mk_codex
  run "$AK" install --target claude --yes --skip gstack --skip karpathy
  assert_rc 0 "install --target claude"
  assert_file "$CLAUDE/agents/backend.md"
  assert_nofile "$CODEX"
  run "$AK" install --target bogus
  assert_rc_nz "bad target"
  assert_contains "--target: unknown value 'bogus' (claude|codex|both)"
  run "$AK" install --target
  assert_rc_nz "target without a value"
  assert_contains "--target needs claude, codex or both"
}
t_target_both_install_and_uninstall() {
  setup_home
  mk_codex
  run "$AK" install --target both --yes --skip gstack --skip karpathy
  assert_rc 0 "install --target both"
  assert_contains "[1/6] Claude: agents and skills"
  assert_contains "[4/6] Codex: agents and skills"
  assert_contains "[6/6] Codex: AGENTS.md"
  assert_match '^claude +files ' "claude files row"
  assert_match '^codex +files ' "codex files row"
  assert_match '^codex +config.toml +added$' "config.toml row"
  assert_match '^codex +AGENTS.md +added$' "AGENTS.md row"
  assert_file "$CLAUDE/settings.json"
  assert_nofile "$CODEX/settings.json"
  # The SubagentStop hook belongs to claude only.
  assert_eq "$(n_src "$CLAUDE/settings.json" SubagentStop agentkit-agent-log)" 1 "claude hook entries"
  # Uninstall without --yes and no terminal: asks (and is refused), changes nothing.
  local before
  before="$(snap "$HOME")"
  run "$AK" uninstall
  assert_rc_nz "uninstall without consent"
  assert_contains "Remove agentkit files, hooks and the instruction blocks (CLAUDE.md, AGENTS.md, config.toml) for: claude codex?"
  assert_eq "$(snap "$HOME")" "$before" "refused uninstall changed files"
  run "$AK" uninstall --dry-run
  assert_rc 0 "uninstall --dry-run"
  assert_contains "[dry-run] remove agents/backend.toml"
  assert_contains "[dry-run] config.toml: remove agentkit block"
  assert_eq "$(snap "$HOME")" "$before" "uninstall --dry-run changed files"
  run "$AK" uninstall --yes
  assert_rc 0 "uninstall both"
  assert_nofile "$CLAUDE/agents/backend.md"
  assert_nofile "$CODEX/agents/backend.toml"
  assert_nofile "$CODEX/config.toml"
  assert_nofile "$CODEX/AGENTS.md"
  assert_nofile "$CLAUDE/CLAUDE.md"
}

t_target_project_with_codex_errors() {
  setup_home
  mk_codex
  local proj="$T/proj" before
  mkdir -p "$proj"
  before="$(snap "$HOME")$(snap "$proj")"
  run "$AK" install --project "$proj" --target codex --yes --skip gstack --skip karpathy
  assert_rc_nz "--project with --target codex"
  assert_contains "--project with codex is not supported"
  run "$AK" install --project "$proj" --target both --yes --skip gstack --skip karpathy
  assert_rc_nz "--project with --target both"
  assert_contains "--project with codex is not supported"
  run "$AK" doctor --project "$proj" --target codex
  assert_rc_nz "doctor --project --target codex"
  assert_eq "$(snap "$HOME")$(snap "$proj")" "$before" "a refused project install changed files"
  assert_nofile "$proj/.claude"
  assert_nofile "$CODEX"
  # --project alone (and with --target claude) still works and never touches codex.
  run "$AK" install --project "$proj" --target claude --yes --skip gstack --skip karpathy
  assert_rc 0 "project install with --target claude"
  assert_file "$proj/.claude/agents/backend.md"
  assert_nofile "$CODEX"
  run "$AK" install --project "$proj" --yes --skip gstack --skip karpathy
  assert_rc 0 "project install with codex on PATH"
  assert_nofile "$CODEX"
}

t_claude_only_commands_reject_codex() {
  setup_home
  install_user
  run "$AK" auto-update on --target codex --yes
  assert_rc_nz "auto-update --target codex"
  assert_contains "auto-update is only for the claude target"
  run "$AK" feedback --target codex
  assert_rc_nz "feedback --target codex"
  assert_contains "feedback is only for the claude target"
}

t_gstack_dry_run_hosts() {
  setup_home
  mk_codex
  local g="$CLAUDE/skills/gstack" u=https://github.com/garrytan/gstack.git
  run "$AK" install --dry-run --target claude --skip karpathy
  assert_rc 0 "dry run, claude"
  assert_contains "[dry-run] gstack: git clone --single-branch --depth 1 $u $g && cd $g && ./setup --host claude"
  assert_not_contains "--host codex"
  run "$AK" install --dry-run --target both --skip karpathy
  assert_rc 0 "dry run, both"
  assert_contains "git clone --single-branch --depth 1 $u $g && cd $g && ./setup --host claude && ./setup --host codex"
  # codex only: the clone goes to ~/gstack, never into CODEX_HOME/skills.
  run "$AK" install --dry-run --target codex --skip karpathy
  assert_rc 0 "dry run, codex"
  assert_contains "[dry-run] gstack: git clone --single-branch --depth 1 $u $HOME/gstack && cd $HOME/gstack && ./setup --host codex"
  assert_not_contains "--host claude"
  assert_not_contains "$CODEX/skills/gstack &&"
  # an existing ~/gstack clone is reused
  mkdir -p "$HOME/gstack"
  : > "$HOME/gstack/setup"
  run "$AK" install --dry-run --target codex --skip karpathy
  assert_contains "[dry-run] gstack: cd $HOME/gstack && ./setup --host codex"
  assert_not_contains "git clone"
  # claude clone present (with its setup): both targets reuse it and add only codex
  mkdir -p "$g"
  : > "$g/setup"
  run "$AK" install --dry-run --target both --skip karpathy
  assert_contains "gstack: already installed ($g)"
  assert_contains "[dry-run] gstack: cd $g && ./setup --host codex"
  assert_not_contains "git clone"
  # codex presence is any $CODEX_HOME/skills/gstack-*
  mkdir -p "$CODEX/skills/gstack-review"
  run "$AK" install --dry-run --target both --skip karpathy
  assert_contains "gstack: already installed ($CODEX/skills/gstack-*)"
  assert_not_contains "[dry-run] gstack:"
  assert_nofile "$CODEX/agents"
}

t_gstack_prompt_and_footer() {
  setup_home
  mk_codex
  local u=https://github.com/garrytan/gstack.git
  # No --yes and no terminal: the prompt is declined, with the manual command.
  run "$AK" install --target codex --skip karpathy
  assert_rc 0 "install, gstack declined"
  assert_contains "Install gstack (git clone into $HOME/gstack, then its ./setup, needs git and bun)?"
  assert_contains "gstack: skipped. Manual: git clone --single-branch --depth 1 $u $HOME/gstack && cd $HOME/gstack && ./setup --host codex"
  assert_nofile "$HOME/gstack"
  run "$AK" install --target claude --skip karpathy
  assert_contains "Install gstack (git clone into $CLAUDE/skills/gstack, then its ./setup, needs git and bun)?"
  # uninstall footer
  run "$AK" uninstall --target codex --yes
  assert_rc 0 "uninstall --target codex"
  assert_contains "gstack (codex): delete $CODEX/skills/gstack-* (and the clone in ~/gstack if you want)"
  assert_not_contains "settings.json entries marked"
  run "$AK" uninstall --target claude --yes
  assert_contains "gstack:   delete $CLAUDE/skills/gstack and the settings.json entries marked _gstack_source"
}

t_gstack_codex_setup_runs() {
  setup_home
  mk_codex
  # A cloned gstack in ~/gstack with a stub setup, and a bun stub: no network, no real setup.
  mkdir -p "$HOME/gstack"
  cat > "$HOME/gstack/setup" <<'EOF'
#!/bin/sh
echo "setup $*" >> "$STUB_LOG"
mkdir -p "$CODEX_HOME/skills/gstack-review"
exit 0
EOF
  chmod +x "$HOME/gstack/setup"
  printf '#!/bin/sh\nexit 0\n' > "$T/stubs/bun"
  chmod +x "$T/stubs/bun"
  run "$AK" install --target codex --yes --skip karpathy
  assert_rc 0 "install with gstack"
  assert_grep "$STUB_LOG" "setup --host codex"
  assert_nogrep "$STUB_LOG" "setup --host claude"
  assert_contains "gstack: set up for codex"
  assert_match '^codex +gstack +installed$' "gstack row"
  assert_dir_has "$CODEX/skills/gstack-review"
  assert_nofile "$CODEX/skills/gstack"
  # Second run: already installed, setup is not run again.
  : > "$STUB_LOG"
  run "$AK" install --target codex --yes --skip karpathy
  assert_contains "gstack: already installed ($CODEX/skills/gstack-*)"
  assert_nogrep "$STUB_LOG" "setup --host"
  # The same on a terminal (the spinner path).
  rm -rf "$CODEX/skills/gstack-review"
  run_pty "$AK" install --target codex --yes --skip karpathy
  assert_rc 0 "install with gstack on a terminal"
  assert_contains "gstack: set up for codex"
  assert_grep "$STUB_LOG" "setup --host codex"
  assert_not_contains "command not found"
}
# ------------------------------------------------------------------ codex target
t_codex_install() {
  setup_home
  mk_codex
  mkdir -p "$CODEX"
  printf 'model = "my-model"\n\n[mcp_servers.foo]\ncommand = "foo"\n' > "$CODEX/config.toml"
  printf '# My codex rules\nBe nice.\n' > "$CODEX/AGENTS.md"
  install_codex
  assert_rc 0 "install --target codex"
  assert_nofile "$CLAUDE"
  assert_grep "$STUB_LOG" "codex --version"
  local f n name map_model map_effort
  # one TOML per agent, none extra
  n=0
  for f in "$AKH"/agents/*.md; do
    name="$(basename "$f" .md)"
    assert_file "$CODEX/agents/$name.toml"
    assert_grep "$CODEX/agents/$name.toml" "developer_instructions = "
    n=$((n + 1))
  done
  assert_eq "$(ls "$CODEX/agents" | wc -l | tr -d ' ')" "$n" "number of agent files"
  assert_nofile "$CODEX/agents/backend.md"
  # models and sandbox come from codex/models.map and the tools
  map_model="$(awk '$1 == "sonnet" { print $2 }' "$AKH/codex/models.map")"
  map_effort="$(awk '$1 == "sonnet" { print $3 }' "$AKH/codex/models.map")"
  assert_grep "$CODEX/agents/backend.toml" "model = \"$map_model\""
  assert_grep "$CODEX/agents/backend.toml" "model_reasoning_effort = \"$map_effort\""
  assert_grep "$CODEX/agents/backend.toml" 'sandbox_mode = "workspace-write"'
  assert_grep "$CODEX/agents/security.toml" 'sandbox_mode = "read-only"'
  assert_grep "$CODEX/agents/security.toml" 'model_reasoning_effort = "high"'
  assert_nogrep "$CODEX/agents/writing.toml" "# Coding discipline" # writing.md has no karpathy skill
  assert_grep "$CODEX/agents/backend.toml" "# Coding discipline"
  # config.toml: user content first and kept, our block once
  assert_eq "$(head -n 1 "$CODEX/config.toml")" 'model = "my-model"' "config.toml first line"
  assert_grep "$CODEX/config.toml" "[mcp_servers.foo]"
  assert_grep "$CODEX/config.toml" 'command = "foo"'
  assert_eq "$(count_of "$CODEX/config.toml" '# agentkit:start')" 1 "config.toml start markers"
  assert_eq "$(count_of "$CODEX/config.toml" '# agentkit:end')" 1 "config.toml end markers"
  assert_eq "$(count_of "$CODEX/config.toml" '^\[agents\.')" "$n" "agent tables in config.toml"
  assert_grep "$CODEX/config.toml" "[agents.backend]"
  assert_grep "$CODEX/config.toml" "config_file = \"$CODEX/agents/backend.toml\""
  # AGENTS.md: user content first and kept, our block once
  assert_eq "$(head -n 1 "$CODEX/AGENTS.md")" "# My codex rules" "AGENTS.md first line"
  assert_grep "$CODEX/AGENTS.md" "Be nice."
  assert_eq "$(count_of "$CODEX/AGENTS.md" '<!-- agentkit:start -->')" 1 "AGENTS.md start markers"
  assert_eq "$(count_of "$CODEX/AGENTS.md" '<!-- agentkit:end -->')" 1 "AGENTS.md end markers"
  assert_grep "$CODEX/AGENTS.md" "# Multi-agent workflow (agentkit)"
  assert_nofile "$CODEX/CLAUDE.md"
  # the three shared skills, and only those
  for n in agent-report security-audit write-swift; do
    diff -rq -x .DS_Store -x '*.pyc' "$AKH/skills/$n" "$CODEX/skills/$n" > "$T/.diff" 2>&1 || fail "skill $n differs: $(cat "$T/.diff")"
  done
  assert_eq "$(ls "$CODEX/skills" | wc -l | tr -d ' ')" 3 "skills copied to codex"
  # manifest
  assert_jtrue "$CODEX/agentkit/manifest.json" "d['agentkit_version'] == '$(tr -d '[:space:]' < "$AKH/VERSION")' and 'agents/backend.toml' in d['files'] and 'skills/write-swift/SKILL.md' in d['files'] and not any(k.endswith('.md') and k.startswith('agents/') for k in d['files'])"
  assert_jtrue "$CODEX/agentkit/manifest.json" "d['files']['agents/backend.toml'] == '$(sha_of "$CODEX/agents/backend.toml")'"
  # backups of the two files that were changed
  [ -n "$(find "$CODEX/agentkit/backups" -name config.toml 2> /dev/null)" ] || fail "no config.toml backup"
  [ -n "$(find "$CODEX/agentkit/backups" -name AGENTS.md 2> /dev/null)" ] || fail "no AGENTS.md backup"
  assert_eq "$(ls -A "$TMPDIR" | wc -l | tr -d ' ')" 0 "temp files left: $(ls -A "$TMPDIR" | tr '\n' ' ')"
}

t_codex_install_idempotent() {
  setup_home
  mk_codex
  install_codex
  assert_rc 0 "first install"
  local before
  before="$(snap "$HOME")"
  install_codex
  assert_rc 0 "second install"
  assert_contains "0 added, 0 updated"
  assert_contains "config.toml: block already up to date"
  assert_contains "AGENTS.md: block already up to date"
  assert_not_contains "agents/backend.toml"
  assert_eq "$(snap "$HOME")" "$before" "second install changed files"
  assert_eq "$(count_of "$CODEX/config.toml" '# agentkit:start')" 1 "config.toml start markers after two installs"
  assert_eq "$(count_of "$CODEX/AGENTS.md" '<!-- agentkit:start -->')" 1 "AGENTS.md start markers after two installs"
}

t_codex_install_dry_run() {
  setup_home
  mk_codex
  mkdir -p "$CODEX"
  printf 'model = "x"\n' > "$CODEX/config.toml"
  local before
  before="$(snap "$HOME")"
  run "$AK" install --target codex --dry-run --skip gstack --skip karpathy
  assert_rc 0 "codex dry run"
  assert_contains "(dry run: nothing is written)"
  assert_contains "[dry-run] copy agents/backend.toml"
  assert_contains "[dry-run] config.toml: added agentkit block"
  assert_eq "$(snap "$HOME")" "$before" "codex dry run changed files"
}

t_codex_config_agent_conflict() {
  setup_home
  mk_codex
  mkdir -p "$CODEX"
  printf '[agents.backend]\ndescription = "my backend"\nconfig_file = "/mine/backend.toml"\n' > "$CODEX/config.toml"
  install_codex
  assert_rc 0 "install with a conflicting [agents.backend]"
  assert_contains "config.toml already defines agent(s) outside the agentkit markers: backend"
  assert_contains "Those are skipped"
  # The user's table is untouched and the only one for backend.
  assert_eq "$(head -n 3 "$CODEX/config.toml")" "$(printf '[agents.backend]\ndescription = "my backend"\nconfig_file = "/mine/backend.toml"')" "user table changed"
  assert_eq "$(count_of "$CODEX/config.toml" '^\[agents\.backend\]')" 1 "[agents.backend] tables"
  assert_nofile "$CODEX/agents/backend.toml"
  assert_jtrue "$CODEX/agentkit/manifest.json" "'agents/backend.toml' not in d['files'] and 'agents/frontend.toml' in d['files']"
  assert_file "$CODEX/agents/frontend.toml"
  assert_grep "$CODEX/config.toml" "[agents.frontend]"
  # Once the user table is gone, a new install brings the agent in.
  printf 'model = "x"\n' > "$CODEX/config.toml"
  install_codex
  assert_rc 0 "install after removing the conflict"
  assert_file "$CODEX/agents/backend.toml"
  assert_grep "$CODEX/config.toml" "[agents.backend]"
}

t_codex_foreign_agent_file() {
  setup_home
  mk_codex
  mkdir -p "$CODEX/agents"
  echo "my backend agent" > "$CODEX/agents/backend.toml"
  install_codex
  assert_rc 0 "install with a foreign agents/backend.toml"
  assert_contains "Codex agent(s) backend not installed"
  assert_contains "exists and is not managed by agentkit. Use --force"
  assert_eq "$(cat "$CODEX/agents/backend.toml")" "my backend agent" "foreign agent file changed"
  # Not registered either, so config.toml never points at the foreign file.
  assert_nogrep "$CODEX/config.toml" "[agents.backend]"
  assert_nogrep "$CODEX/config.toml" "agents/backend.toml"
  assert_grep "$CODEX/config.toml" "[agents.frontend]"
  assert_file "$CODEX/agents/frontend.toml"
  assert_jtrue "$CODEX/agentkit/manifest.json" "'agents/backend.toml' not in d['files']"
  # A second install says the same and still leaves it alone.
  install_codex
  assert_contains "Codex agent(s) backend not installed"
  assert_eq "$(cat "$CODEX/agents/backend.toml")" "my backend agent" "foreign agent file changed by a second install"
  # Uninstall leaves it alone.
  run "$AK" uninstall --target codex --yes
  assert_rc 0 "uninstall"
  assert_eq "$(cat "$CODEX/agents/backend.toml")" "my backend agent" "foreign agent file removed by uninstall"
  # --force: back up, replace, register.
  install_codex --force
  assert_rc 0 "install --force"
  assert_not_contains "not installed"
  assert_grep "$CODEX/agents/backend.toml" "developer_instructions = "
  assert_grep "$CODEX/config.toml" "[agents.backend]"
  assert_eq "$(cat "$(find "$CODEX/agentkit/backups" -path '*agents/backend.toml' | head -n 1)")" "my backend agent" "backup content"
  assert_jtrue "$CODEX/agentkit/manifest.json" "'agents/backend.toml' in d['files']"
  # An identical file we wrote earlier (manifest lost) is adopted without a warning.
  rm -f "$CODEX/agentkit/manifest.json"
  install_codex
  assert_rc 0 "install with the manifest gone"
  assert_not_contains "not installed"
  assert_jtrue "$CODEX/agentkit/manifest.json" "'agents/backend.toml' in d['files']"
}

t_codex_config_declined() {
  setup_home
  mk_codex
  # No --yes and no terminal: the agent files are copied, config.toml is not touched.
  run "$AK" install --target codex --skip gstack --skip karpathy
  assert_rc 0 "install without consent"
  assert_file "$CODEX/agents/backend.toml"
  assert_nofile "$CODEX/config.toml"
  assert_nofile "$CODEX/AGENTS.md"
  assert_match '^  ! config.toml: skipped$' "config.toml result line"
  assert_contains "the agent files in $CODEX/agents are not registered in config.toml; codex doctor will warn about them"
  assert_match '^codex +config.toml +skipped$' "config.toml row"
  # update does not add a block the user never accepted.
  run "$AK" update
  assert_rc 0 "update"
  assert_nofile "$CODEX/config.toml"
  assert_nofile "$CODEX/AGENTS.md"
}

t_codex_config_unusable() {
  setup_home
  mk_codex
  mkdir -p "$CODEX"
  printf '# agentkit:start\n[agents.x]\n' > "$CODEX/config.toml"
  install_codex
  assert_rc 0 "install with a half marker in config.toml"
  assert_contains "cannot use $CODEX/config.toml"
  assert_eq "$(cat "$CODEX/config.toml")" "$(printf '# agentkit:start\n[agents.x]')" "broken config.toml was changed"
  assert_contains "config.toml: no agents registered"
}

t_codex_doctor() {
  setup_home
  mk_codex
  install_codex
  assert_rc 0 "install"
  run "$AK" doctor --target codex
  assert_rc 0 "doctor after install"
  assert_contains "target codex: $CODEX"
  assert_not_contains "target claude"
  assert_contains "  ok    agent backend"
  assert_contains "  ok    skill write-swift"
  assert_contains "  ok    config.toml agents block"
  assert_contains "  ok    AGENTS.md block"
  assert_contains "all required checks passed"
  assert_not_contains "SubagentStop"
  # A missing agent file fails the doctor.
  rm "$CODEX/agents/backend.toml"
  run "$AK" doctor --target codex
  assert_rc_nz "doctor with a missing agent file"
  assert_contains "agent backend: missing"
  # An edited one only warns.
  install_codex --force
  echo "# mine" >> "$CODEX/agents/backend.toml"
  run "$AK" doctor --target codex
  assert_rc 0 "doctor with an edited agent file"
  assert_contains "agent backend: modified"
  # A removed block only warns.
  "$PY" -I "$AKH/lib/codex.py" config-del "$CODEX/config.toml" write > /dev/null
  run "$AK" doctor --target codex
  assert_rc 0 "doctor without the config block"
  assert_contains "config.toml agents block not present"
  # Not installed at all.
  rm -rf "$CODEX"
  run "$AK" doctor --target codex
  assert_rc_nz "doctor without an install"
  assert_contains "not installed in $CODEX"
}

t_codex_update_prunes() {
  setup_home
  mk_codex
  install_codex
  assert_rc 0 "install"
  echo "# my edit" >> "$CODEX/agents/backend.toml"
  upstream 'echo "<!-- upstream -->" >> agents/frontend.md
    git rm -q agents/seo.md
    printf -- "---\nname: newagent\ndescription: a new one\ntools: Read\nmodel: sonnet\n---\nbody\n" > agents/newagent.md
    echo "upstream snippet line" >> templates/AGENTS.md.snippet'
  run "$AK" update
  assert_rc 0 "update"
  assert_contains "$CODEX"
  assert_not_contains "$CLAUDE"
  assert_contains "  + agents/frontend.toml (updated)"
  assert_contains "  + agents/newagent.toml"
  assert_contains "  + agents/seo.toml (removed upstream)"
  assert_contains "  ! kept your edited agents/backend.toml"
  assert_grep "$CODEX/agents/frontend.toml" "<!-- upstream -->"
  assert_file "$CODEX/agents/newagent.toml"
  assert_nofile "$CODEX/agents/seo.toml"
  assert_grep "$CODEX/agents/backend.toml" "# my edit"
  assert_file "$CODEX/agents/backend.toml.agentkit-new"
  # the block follows the agent set
  assert_grep "$CODEX/config.toml" "[agents.newagent]"
  assert_nogrep "$CODEX/config.toml" "[agents.seo]"
  assert_nogrep "$CODEX/config.toml" "seo.toml"
  assert_eq "$(count_of "$CODEX/config.toml" '# agentkit:start')" 1 "config.toml start markers"
  assert_grep "$CODEX/AGENTS.md" "upstream snippet line"
  assert_jtrue "$CODEX/agentkit/manifest.json" "'agents/newagent.toml' in d['files'] and 'agents/seo.toml' not in d['files']"
  assert_nofile "$CLAUDE"
  # a second update has nothing new to say about files
  run "$AK" update
  assert_rc 0 "second update"
  assert_contains "0 added, 0 updated"
  assert_not_contains "(removed upstream)"
  assert_not_contains "(updated)"
  assert_contains "config.toml: block already up to date"
}

t_codex_update_user_removed_block_stays() {
  setup_home
  mk_codex
  install_codex
  "$PY" -I "$AKH/lib/codex.py" config-del "$CODEX/config.toml" write > /dev/null
  rm -f "$CODEX/config.toml.empty"
  local before
  before="$(snap "$CODEX")"
  run "$AK" update
  assert_rc 0 "update"
  assert_nogrep "$CODEX/config.toml" "agentkit:start"
  assert_eq "$(snap "$CODEX")" "$before" "update re-added files or blocks the user removed"
}

t_codex_uninstall_restores_originals() {
  setup_home
  mk_codex
  mkdir -p "$CODEX"
  printf 'model = "x"\n\n[mcp_servers.foo]\ncommand = "foo"\n' > "$CODEX/config.toml"
  printf '# mine\nrules\n' > "$CODEX/AGENTS.md"
  cp "$CODEX/config.toml" "$T/config.orig"
  cp "$CODEX/AGENTS.md" "$T/agents-md.orig"
  install_codex
  assert_rc 0 "install"
  assert_grep "$CODEX/config.toml" "agentkit:start"
  run "$AK" uninstall --target codex --yes
  assert_rc 0 "uninstall"
  assert_contains "config.toml: removed agentkit block"
  assert_contains "AGENTS.md: removed agentkit block"
  assert_same "$CODEX/config.toml" "$T/config.orig"
  assert_same "$CODEX/AGENTS.md" "$T/agents-md.orig"
  assert_nofile "$CODEX/agents"
  assert_nofile "$CODEX/skills"
  assert_nofile "$CODEX/agentkit/manifest.json"
  [ -d "$CODEX/agentkit/backups" ] || fail "backups folder should be kept"
  # Files that did not exist before are gone again.
  rm -rf "$CODEX"
  install_codex
  run "$AK" uninstall --target codex --yes
  assert_rc 0 "uninstall of a fresh install"
  assert_nofile "$CODEX/config.toml"
  assert_nofile "$CODEX/AGENTS.md"
  assert_nofile "$CODEX/agents"
  # An edited agent file stays, and so does its folder.
  install_codex
  echo "# my edit" >> "$CODEX/agents/backend.toml"
  run "$AK" uninstall --target codex --yes
  assert_rc 0 "uninstall with an edited agent file"
  assert_contains "Kept because you edited them"
  assert_grep "$CODEX/agents/backend.toml" "# my edit"
  assert_eq "$(ls "$CODEX/agents" | wc -l | tr -d ' ')" 1 "agent files left"
  assert_nogrep "$CODEX/config.toml" "agentkit:start"
}

# Files without a final newline: uninstall should give back the original bytes. Today it leaves a "\n" behind.
t_codex_uninstall_restores_no_trailing_newline() {
  setup_home
  mk_codex
  mkdir -p "$CODEX"
  printf 'model = "x"' > "$CODEX/config.toml"
  printf '# mine' > "$CODEX/AGENTS.md"
  cp "$CODEX/config.toml" "$T/config.orig"
  cp "$CODEX/AGENTS.md" "$T/agents-md.orig"
  install_codex
  assert_rc 0 "install"
  run "$AK" uninstall --target codex --yes
  assert_rc 0 "uninstall"
  assert_same "$CODEX/config.toml" "$T/config.orig"
  assert_same "$CODEX/AGENTS.md" "$T/agents-md.orig"
}

t_codex_uninstall_keeps_other_target() {
  setup_home
  mk_codex
  install_codex
  install_user
  assert_rc 0 "claude install"
  run "$AK" uninstall --target codex --yes
  assert_rc 0 "uninstall --target codex"
  assert_nofile "$CODEX/agents/backend.toml"
  assert_file "$CLAUDE/agents/backend.md"
  assert_file "$CLAUDE/CLAUDE.md"
  assert_eq "$(n_src "$CLAUDE/settings.json" SubagentStop agentkit-agent-log)" 1 "claude hook entries"
  assert_not_contains "settings.json"
  run "$AK" doctor
  assert_not_contains "target codex"
  assert_contains "target claude"
}

t_codex_home_default_is_dot_codex() {
  setup_home
  mk_codex
  unset CODEX_HOME
  install_codex
  assert_rc 0 "install with CODEX_HOME unset"
  assert_file "$HOME/.codex/agents/backend.toml"
  assert_file "$HOME/.codex/agentkit/manifest.json"
}

# ------------------------------------------------------------------ bootstrap script
t_install_sh_requirements_block_matches_lib() {
  local a="$T/block.install" b="$T/block.lib"
  sed -n '/^# >>> agentkit:requirements$/,/^# <<< agentkit:requirements$/p' "$ROOT/install.sh" > "$a"
  sed -n '/^# >>> agentkit:requirements$/,/^# <<< agentkit:requirements$/p' "$ROOT/lib/requirements.sh" > "$b"
  [ "$(wc -l < "$a" | tr -d ' ')" -gt 50 ] || fail "install.sh has no requirements block"
  [ "$(wc -l < "$b" | tr -d ' ')" -gt 50 ] || fail "lib/requirements.sh has no requirements block"
  cmp -s "$a" "$b" || fail "install.sh block differs from lib/requirements.sh: $(diff "$a" "$b" | head -n 10 | tr '\n' '|')"
  assert_eq "$(grep -c '^# >>> agentkit:requirements$' "$ROOT/install.sh")" 1 "start markers in install.sh"
  assert_eq "$(grep -c '^# <<< agentkit:requirements$' "$ROOT/install.sh")" 1 "end markers in install.sh"
}

# A brew stub: logs every call; `brew install codex` makes a codex stub appear on PATH.
mk_brew() {
  export T_BREW_LOG="$T/brew.log" T_STUBS="$T/stubs"
  cat > "$T/stubs/brew" <<'EOF'
#!/bin/sh
echo "brew $*" >> "$T_BREW_LOG"
if [ "$1 $2" = "install codex" ]; then
  printf '#!/bin/sh\nexit 0\n' > "$T_STUBS/codex"
  chmod +x "$T_STUBS/codex"
fi
exit 0
EOF
  chmod +x "$T/stubs/brew"
}

# ------------------------------------------------------------------ requirements per target
t_requirements_target_claude() {
  setup_home
  rm -f "$T/stubs/claude"
  mk_brew; mk_curl
  # codex is on PATH but claude is not: --target claude needs claude, and never installs codex.
  mk_codex
  run "$AK" install --target claude --yes --skip gstack --skip karpathy
  assert_rc_nz "--target claude without claude"
  assert_match '^  x claude +not found, required' "claude row"
  assert_match '^  \+ codex ' "codex row"
  assert_contains "requirements are not met"
  assert_nofile "$T/curl.log"
  assert_nofile "$T/brew.log"
  assert_nofile "$CLAUDE"
  # codex missing too: still no codex install for --target claude
  rm -f "$T/stubs/codex"
  run "$AK" install --target claude --yes --skip gstack --skip karpathy
  assert_rc_nz "--target claude without any CLI"
  assert_match '^  x codex +not found, optional \(not needed for this target\)' "codex row"
  assert_not_contains "brew install codex"
  assert_nofile "$T/brew.log"
  assert_nofile "$T/curl.log"
  assert_nofile "$T/stubs/codex"
  # claude present: fine, codex is optional
  printf '#!/bin/sh\nexit 0\n' > "$T/stubs/claude"; chmod +x "$T/stubs/claude"
  run "$AK" install --target claude --yes --skip gstack --skip karpathy
  assert_rc 0 "--target claude with claude"
  assert_file "$CLAUDE/agents/backend.md"
  assert_nofile "$CODEX"
  assert_nofile "$T/brew.log"
}

t_requirements_target_codex() {
  setup_home
  rm -f "$T/stubs/claude"
  mk_brew; mk_curl
  # --yes with a package manager installs codex, and only codex; no remote script runs.
  run "$AK" install --target codex --yes --skip gstack --skip karpathy
  assert_rc 0 "--target codex with brew"
  assert_match '^  x codex +not found, required' "codex row"
  assert_match '^  x claude +not found, optional \(not needed for this target\)' "claude row"
  assert_contains "Running: brew install codex"
  assert_grep "$T/brew.log" "brew install codex"
  assert_eq "$(nlines "$T/brew.log")" 1 "brew calls"
  assert_nofile "$T/curl.log"
  assert_file "$T/stubs/codex"
  assert_nofile "$T/stubs/claude"
  assert_file "$CODEX/agents/backend.toml"
  assert_nofile "$CLAUDE"
  # Without --yes and without a terminal, brew is not run.
  rm -f "$T/stubs/codex" "$T/brew.log"
  rm -rf "$CODEX"
  run "$AK" install --target codex --skip gstack --skip karpathy
  assert_rc_nz "--target codex, no consent"
  assert_contains "No TTY: not running. Command: brew install codex"
  assert_nofile "$T/brew.log"
  assert_nofile "$CODEX"
}

t_requirements_target_both() {
  setup_home
  rm -f "$T/stubs/claude"
  mk_brew; mk_curl
  # both needs both: codex comes from brew, claude is a remote script that --yes never runs.
  run "$AK" install --target both --yes --skip gstack --skip karpathy
  assert_rc_nz "--target both without claude"
  assert_contains "Running: brew install codex"
  assert_contains "No TTY: not running a remote script"
  assert_nofile "$T/curl.log"
  assert_match '^  x claude +not found, required' "claude row"
  assert_nofile "$CLAUDE"
  assert_nofile "$CODEX/agents/backend.toml"
  assert_nofile "$CODEX/config.toml"
  # Both present: installs both.
  printf '#!/bin/sh\nexit 0\n' > "$T/stubs/claude"; chmod +x "$T/stubs/claude"
  run "$AK" install --target both --yes --skip gstack --skip karpathy
  assert_rc 0 "--target both with both CLIs"
  assert_file "$CLAUDE/agents/backend.md"
  assert_file "$CODEX/agents/backend.toml"
  assert_eq "$(nlines "$T/brew.log")" 1 "brew calls"
  assert_nofile "$T/curl.log"
}

t_requirements_auto_installs_only_what_it_may() {
  setup_home
  rm -f "$T/stubs/claude"
  mk_brew; mk_curl
  # No --target, no CLI, --yes: claude would need a remote script (never run), codex comes from brew.
  run "$AK" install --yes --skip gstack --skip karpathy
  assert_rc 0 "auto with brew"
  assert_nofile "$T/curl.log"
  assert_grep "$T/brew.log" "brew install codex"
  assert_file "$CODEX/agents/backend.toml"
  assert_nofile "$CLAUDE"
}

t_requirements_install_sh_target_and_quiet() {
  setup_home
  rm -f "$T/stubs/claude"
  mk_brew; mk_curl
  # install.sh reads --target / --target= for the requirements and passes it on.
  run bash "$AKH/install.sh" --target codex --yes --skip gstack --skip karpathy
  assert_rc 0 "install.sh --target codex"
  assert_match '^  x claude +not found, optional \(not needed for this target\)' "claude row"
  assert_file "$CODEX/agents/backend.toml"
  assert_nofile "$CLAUDE"
  assert_nofile "$T/curl.log"
  rm -rf "$CODEX" "$T/stubs/codex" "$T/brew.log"
  run bash "$AKH/install.sh" --target=claude --yes --skip gstack --skip karpathy
  assert_rc_nz "install.sh --target=claude without claude"
  assert_match '^  x claude +not found, required' "claude row"
  assert_nofile "$T/brew.log"
  run bash "$AKH/install.sh" --target bogus --yes
  assert_rc_nz "install.sh with a bad target"
  assert_contains "--target: unknown value 'bogus'"
  run bash "$AKH/install.sh" --target
  assert_rc_nz "install.sh with --target and no value"
  assert_contains "--target needs claude, codex or both"
  # -q is --quiet: nothing is printed on success, errors still print.
  printf '#!/bin/sh\nexit 0\n' > "$T/stubs/claude"; chmod +x "$T/stubs/claude"
  PATH="$HOME/.local/bin:$PATH" run bash "$AKH/install.sh" -q --yes --skip gstack --skip karpathy --skip hooks
  assert_rc 0 "install.sh -q"
  assert_eq "$OUT" "" "install.sh -q printed something"
  assert_file "$CLAUDE/agents/backend.md"
  rm -f "$T/stubs/claude" "$T/stubs/brew" "$T/stubs/codex"
  PATH="$HOME/.local/bin:$PATH" run bash "$AKH/install.sh" --quiet --yes --skip gstack --skip karpathy
  assert_rc_nz "install.sh --quiet without a CLI"
  assert_contains "requirements are not met"
}

t_requirements_doctor_target() {
  setup_home
  mk_codex
  install_codex
  rm -f "$T/stubs/claude"
  run "$AK" doctor --target codex
  assert_rc 0 "doctor --target codex without claude"
  assert_match '^  x claude +not found, optional \(not needed for this target\)' "claude row"
  rm -f "$T/stubs/codex"
  run "$AK" doctor --target codex
  assert_rc_nz "doctor --target codex without codex"
  assert_match '^  x codex +not found, required' "codex row"
}

# ------------------------------------------------------------------ quiet and hook preview
t_quiet_still_shows_hook_preview_before_a_prompt() {
  setup_home
  # --quiet without --yes: a y/N prompt follows, so the entry is shown first.
  run "$AK" install --quiet --skip gstack --skip karpathy
  assert_rc 0 "quiet install without --yes"
  assert_contains "settings.json: added this entry in $CLAUDE/settings.json:"
  assert_contains '"_agentkit_source": "agentkit-agent-log"'
  assert_nofile "$CLAUDE/settings.json"
  # --yes: nothing is asked, nothing is shown.
  run "$AK" install --quiet --yes --skip gstack --skip karpathy
  assert_rc 0 "quiet install --yes"
  assert_eq "$OUT" "" "quiet install --yes printed something"
  assert_eq "$(n_src "$CLAUDE/settings.json" SubagentStop agentkit-agent-log)" 1 "hook entries"
  # Without --quiet the entry is always shown.
  rm -rf "$CLAUDE"
  run "$AK" install --yes --skip gstack --skip karpathy
  assert_contains '"_agentkit_source": "agentkit-agent-log"'
}

# ------------------------------------------------------------------ codex rendering
t_codex_rendered_agents_have_no_claude_paths() {
  setup_home
  mk_codex
  install_codex
  assert_rc 0 "install"
  local f bad=""
  for f in "$CODEX"/agents/*.toml; do
    if grep -qF '.claude/' "$f"; then bad="$bad $(basename "$f")"; fi
  done
  assert_eq "$bad" "" "rendered agents that still mention .claude/"
  # supervisor.md reads the agent definitions: it must point at the Codex ones.
  assert_grep "$AKH/agents/supervisor.md" "~/.claude/agents/*.md"
  assert_grep "$CODEX/agents/supervisor.toml" "~/.codex/agents/*.toml"
  assert_nogrep "$CODEX/agents/supervisor.toml" "~/.claude"
}

t_codex_effort_values() {
  setup_home
  mk_codex
  local e
  # every allowed effort value is rendered as given
  for e in low medium high xhigh max; do
    printf -- '---\nname: eff-%s\ndescription: x\ntools: Read\nmodel: sonnet\neffort: %s\n---\nbody\n' "$e" "$e" > "$AKH/agents/eff-$e.md"
  done
  install_codex
  assert_rc 0 "install with every effort value"
  for e in low medium high xhigh max; do
    assert_grep "$CODEX/agents/eff-$e.toml" "model_reasoning_effort = \"$e\""
  done
  # an unknown value is refused, and nothing is written
  rm -rf "$CODEX"
  rm -f "$AKH"/agents/eff-*.md
  printf -- '---\nname: eff-bad\ndescription: x\ntools: Read\nmodel: sonnet\neffort: turbo\n---\nbody\n' > "$AKH/agents/eff-bad.md"
  install_codex
  assert_rc_nz "install with effort: turbo"
  assert_contains "effort 'turbo' not one of low, medium, high, xhigh, max"
  assert_contains "cannot render Codex agent eff-bad"
  assert_eq "$(ls -A "$CODEX/agents" 2> /dev/null | wc -l | tr -d ' ')" 0 "agent files written despite the error"
  assert_nofile "$CODEX/config.toml"
  assert_nofile "$CODEX/agentkit/manifest.json"
}

# ------------------------------------------------------------------ symlinked instruction files
t_symlinked_config_backup_is_a_copy() {
  setup_home
  mk_codex
  mkdir -p "$CODEX" "$CLAUDE" "$T/dotfiles"
  printf 'model = "x"\n' > "$T/dotfiles/config.toml"
  printf '# my agents\n' > "$T/dotfiles/AGENTS.md"
  printf '# my claude\n' > "$T/dotfiles/CLAUDE.md"
  ln -s "$T/dotfiles/config.toml" "$CODEX/config.toml"
  ln -s "$T/dotfiles/AGENTS.md" "$CODEX/AGENTS.md"
  ln -s "$T/dotfiles/CLAUDE.md" "$CLAUDE/CLAUDE.md"
  run "$AK" install --target both --yes --skip gstack --skip karpathy
  assert_rc 0 "install over symlinked files"
  # the links stay links, the block went into the real files
  [ -L "$CODEX/config.toml" ] || fail "config.toml link was replaced"
  [ -L "$CODEX/AGENTS.md" ] || fail "AGENTS.md link was replaced"
  [ -L "$CLAUDE/CLAUDE.md" ] || fail "CLAUDE.md link was replaced"
  assert_grep "$T/dotfiles/config.toml" "agentkit:start"
  assert_grep "$T/dotfiles/AGENTS.md" "agentkit:start"
  assert_grep "$T/dotfiles/CLAUDE.md" "agentkit:start"
  # the backups are regular files with the old content
  local b
  for b in "$CODEX/agentkit/backups/*/config.toml:model = \"x\"" "$CODEX/agentkit/backups/*/AGENTS.md:# my agents" "$CLAUDE/agentkit/backups/*/CLAUDE.md:# my claude"; do
    local pat="${b%%:*}" want="${b#*:}" found
    found="$(find "$(dirname "$(dirname "$pat")")" -name "$(basename "$pat")" 2> /dev/null | head -n 1)"
    { [ -n "$found" ] && [ -f "$found" ] && [ ! -L "$found" ]; } || { fail "backup of $(basename "$pat") is missing or a link (found: '$found')"; continue; }
    assert_eq "$(cat "$found")" "$want" "backup content of $(basename "$pat")"
  done
  # uninstall writes through the links too
  run "$AK" uninstall --target both --yes
  assert_rc 0 "uninstall"
  [ -L "$CODEX/config.toml" ] || fail "config.toml link was replaced by uninstall"
  assert_eq "$(cat "$T/dotfiles/config.toml")" 'model = "x"' "config.toml after uninstall"
  assert_eq "$(cat "$T/dotfiles/AGENTS.md")" "# my agents" "AGENTS.md after uninstall"
}

# ================================================================== runner
ALL_TESTS="
t_dry_run_writes_nothing
t_no_temp_files_left
t_install_yes
t_install_idempotent
t_install_foreign_files
t_update_merge
t_update_not_fast_forward
t_update_not_a_clone
t_auto_update_toggle
t_hook_silent_fast_and_runs_update
t_hook_throttle
t_hook_rotates_log
t_hook_status_line_and_noops
t_auto_update_end_to_end
t_hook_markers_stripped
t_project_scope
t_uninstall
t_uninstall_purge
t_doctor
t_log_commands
t_feedback
t_dependency_stubs
t_subagent_stop_command_runs
t_bad_settings_untouched
t_cli_errors
t_symlinked_skill_not_adopted
t_deleted_file_stays_deleted
t_purge_keeps_non_default_checkout
t_feedback_nothing_to_send
t_uninstall_keeps_user_agentlog_hook
t_update_refreshes_marked_hooks
t_install_existing_link
t_claude_md_duplicate_heading_warns
t_requirements_missing_agent_cli
t_requirements_missing_git
t_requirements_other_agent_is_enough
t_requirements_dry_run_installs_nothing
t_requirements_ok_skips_check_not_detection
t_requirements_doctor
t_output_plain_has_no_ansi
t_output_terminal_color_and_no_color
t_output_quiet
t_output_quiet_install
t_output_markers_and_table
t_target_default_detection
t_target_codex_only_cli
t_target_explicit_without_cli
t_target_both_install_and_uninstall
t_target_project_with_codex_errors
t_claude_only_commands_reject_codex
t_gstack_dry_run_hosts
t_codex_install
t_codex_install_idempotent
t_codex_install_dry_run
t_codex_config_agent_conflict
t_codex_foreign_agent_file
t_codex_config_declined
t_codex_config_unusable
t_codex_doctor
t_codex_update_prunes
t_codex_update_user_removed_block_stays
t_codex_uninstall_restores_originals
t_codex_uninstall_restores_no_trailing_newline
t_codex_uninstall_keeps_other_target
t_codex_home_default_is_dot_codex
t_install_sh_requirements_block_matches_lib
t_requirements_target_claude
t_requirements_target_codex
t_requirements_target_both
t_requirements_auto_installs_only_what_it_may
t_requirements_install_sh_target_and_quiet
t_requirements_doctor_target
t_quiet_still_shows_hook_preview_before_a_prompt
t_codex_rendered_agents_have_no_claude_paths
t_codex_effort_values
t_symlinked_config_backup_is_a_copy
t_gstack_prompt_and_footer
t_gstack_codex_setup_runs
"

# Tests that currently fail because of a bug in the code under test. They print XFAIL and do not fail
# the run; when the bug is fixed they print XPASS and DO fail the run, so remove them from this list then.
KNOWN_BUGS=" t_codex_uninstall_restores_no_trailing_newline "

PASSED=0 FAILED=0 XFAILED=0 FAILED_NAMES=""
tests="${*:-$ALL_TESTS}"
n=0
for t in $tests; do
  n=$((n + 1))
  dir="$SUITE/t.$n"
  mkdir -p "$dir"
  ( new_env "$dir"; "$t"; exit 0 ) > "$dir/.log" 2>&1
  rc=$?
  if [ "$rc" -eq 99 ]; then
    cat "$dir/.log"
    echo "ABORT: sandbox check failed in $t"
    exit 2
  fi
  wait_bg
  known=0
  case "$KNOWN_BUGS" in *" $t "*) known=1 ;; esac
  if [ "$rc" -eq 0 ] && [ ! -s "$dir/.fails" ]; then
    if [ "$known" = 1 ]; then
      printf 'XPASS %s (listed in KNOWN_BUGS but passes now: remove it from the list)\n' "$t"
      FAILED=$((FAILED + 1)); FAILED_NAMES="$FAILED_NAMES $t"
    else
      printf 'PASS  %s\n' "$t"
      PASSED=$((PASSED + 1))
    fi
  elif [ "$known" = 1 ]; then
    printf 'XFAIL %s (known bug in the code under test)\n' "$t"
    sed 's/^/      /' "$dir/.log"
    XFAILED=$((XFAILED + 1))
  else
    printf 'FAIL  %s\n' "$t"
    sed 's/^/      /' "$dir/.log"
    [ "$rc" -ne 0 ] && printf '      (test function exited with %s)\n' "$rc"
    FAILED=$((FAILED + 1))
    FAILED_NAMES="$FAILED_NAMES $t"
  fi
done

echo
printf '%d passed, %d failed, %d known-bug (xfail), %d total\n' "$PASSED" "$FAILED" "$XFAILED" $((PASSED + FAILED + XFAILED))
[ "$FAILED" -eq 0 ] || { echo "Failed:$FAILED_NAMES"; exit 1; }
exit 0
