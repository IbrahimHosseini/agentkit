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
  export HOME="$T/home" TMPDIR="$T/tmp" AGENT_LOG_DIR="$T/agent-log" PATH="$REALBIN"
  export AGENTKIT_REPO="$T/origin.git" STUB_LOG="$T/stub.log"
  unset CLAUDE_CONFIG_DIR AGENTKIT_HOME AGENTKIT_UPDATE_INTERVAL GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE STUB_PLUGIN_LIST STUB_GH_FAIL_LABEL
  mkdir -p "$HOME" "$TMPDIR" "$T/work" "$T/stubs"
  cp -R "$BASE" "$AGENTKIT_REPO"
  CLAUDE="$HOME/.claude"
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
  assert_eq "$(ls -A "$TMPDIR" | grep -c 'agentkit-dry')" 0 "piped dry run left its temp clone behind"
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
"

# Tests that currently fail because of a bug in the code under test. They print XFAIL and do not fail
# the run; when the bug is fixed they print XPASS and DO fail the run, so remove them from this list then.
KNOWN_BUGS=" "

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
