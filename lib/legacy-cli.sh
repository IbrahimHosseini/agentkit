#!/usr/bin/env bash
# agentkit: install and update a shared pack of Claude Code agents and skills.
# bash 3.2 compatible. JSON and CLAUDE.md edits use python3 -I (stdlib only).

set -u

# ---------------------------------------------------------------- python helper
IFS= read -r -d '' PYLIB <<'PY'
import hashlib, json, os, re, sys

START = '<!-- agentkit:start -->'
END = '<!-- agentkit:end -->'


def rd(p):
    try:
        with open(p, encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return None


def wr(p, s):
    p = os.path.realpath(p)  # never replace a symlink, write through it
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.agentkit-tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
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


try:
    main(sys.argv[1:])
except (ValueError, OSError) as e:
    sys.exit('error: ' + str(e))
PY

py() { python3 -I -c "$PYLIB" "$@"; }

# ---------------------------------------------------------------- helpers
say() { [ "$QUIET" = 1 ] || printf '%s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
dry() { say "[dry-run] $*"; }
skipped() { case "$SKIPS" in *" $1 "*) return 0 ;; esac; return 1; }

QUIET=0 DRY=0 YES=0 PROJECT="" SKIPS=" " TARGET_OPT="" TARGETS="" CUR=""
TS="$(date +%Y%m%d-%H%M%S)"
WORK=""
cleanup() { if [ -n "$WORK" ] && [ -d "$WORK" ]; then rm -rf "${WORK:?}"; fi; }
# ui_spin clears INT/TERM/EXIT traps on return, so re-arm after every spin.
arm_traps() { trap cleanup EXIT; trap 'exit 130' INT; trap 'exit 143' TERM; }
arm_traps
# One work dir per run, made in the main shell, removed on exit. Not made for 'log' (it uses exec).
init_work() {
  [ -n "$WORK" ] && return 0
  WORK="$(mktemp -d "${TMPDIR:-/tmp}/agentkit.XXXXXX")" || die "mktemp failed"
}
mktmp() { mktemp "$WORK/f.XXXXXX"; }

if command -v sha256sum > /dev/null 2>&1; then
  sha() { sha256sum "$1" | cut -d' ' -f1; }
else
  sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
fi

# Resolve where agentkit lives.
resolve_home() {
  if [ -n "${AGENTKIT_HOME:-}" ]; then return; fi
  local src="${BASH_SOURCE[0]}" d
  while [ -L "$src" ]; do
    d="$(cd "$(dirname "$src")" && pwd)"
    src="$(readlink "$src")"
    case "$src" in /*) ;; *) src="$d/$src" ;; esac
  done
  d="$(cd "$(dirname "$src")/.." 2> /dev/null && pwd)"
  if [ -n "$d" ] && [ -f "$d/VERSION" ] && [ -d "$d/agents" ]; then
    AGENTKIT_HOME="$d"
  else
    AGENTKIT_HOME="$HOME/.agentkit"
  fi
}
resolve_home
AGENTKIT_REPO="${AGENTKIT_REPO:-https://github.com/IbrahimHosseini/agentkit.git}"
CLAUDE_HOME="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
VERSION_FILE="$AGENTKIT_HOME/VERSION"
version() {
  if [ -f "$VERSION_FILE" ]; then tr -d '[:space:]' < "$VERSION_FILE"; else echo unknown; fi
}
cpy() { python3 -I "$AGENTKIT_HOME/lib/codex.py" "$@"; }

# UI and requirements libraries. version and help work without them.
case "${1:-help}" in
  version | --version | -v | help | --help | -h) ;;
  *)
    for _lib in ui.sh requirements.sh; do
      [ -f "$AGENTKIT_HOME/lib/$_lib" ] || die "AGENTKIT_HOME not found or incomplete: missing $AGENTKIT_HOME/lib/$_lib"
      # shellcheck source=/dev/null
      . "$AGENTKIT_HOME/lib/$_lib"
    done
    ;;
esac
# ui_spin's INT/TERM handler exits without our cleanup; replace it so the work dir is removed too.
ui__spin_sig() { ui__spin_stop; trap - INT TERM EXIT; cleanup; exit "$1"; }

# y/N prompt. --yes answers yes. No tty and no --yes: answer no and say so.
ask() {
  local ans
  [ "$YES" = 1 ] && return 0
  if { : < /dev/tty; } 2> /dev/null; then
    printf '%s [y/N] ' "$1" > /dev/tty
    read -r ans < /dev/tty
    case "$ans" in y | Y | yes | YES) return 0 ;; esac
    return 1
  fi
  say "No terminal, skipped: $1 (use --yes to accept)"
  return 1
}

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --project) [ $# -ge 2 ] || die "--project needs a directory"; PROJECT="$2"; shift ;;
      --project=*) PROJECT="${1#--project=}" ;;
      --dry-run) DRY=1 ;;
      --yes | -y) YES=1 ;;
      --force) : ;;
      --quiet) QUIET=1 ;;
      --purge) : ;;
      --target) [ $# -ge 2 ] || die "--target needs claude, codex or both"; set_target_opt "$2"; shift ;;
      --target=*) set_target_opt "${1#--target=}" ;;
      --skip)
        [ $# -ge 2 ] || die "--skip needs a value"
        add_skip "$2"; shift ;;
      --skip=*) add_skip "${1#--skip=}" ;;
      *) die "unknown option: $1 (see: agentkit help)" ;;
    esac
    shift
  done
}
set_target_opt() {
  case "$1" in claude | codex | both) TARGET_OPT="$1" ;; *) die "--target: unknown value '$1' (claude|codex|both)" ;; esac
}
add_skip() {
  case "$1" in gstack | karpathy | claude-md | hooks | skills) SKIPS="$SKIPS$1 " ;; *) die "--skip: unknown step '$1' (gstack|karpathy|claude-md|hooks|skills)" ;; esac
}

need_python() {
  python3 -I -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2> /dev/null || die "python3 >= 3.9 is required"
}

# Work dir and --project check, then the Claude paths (for claude-only commands).
resolve_target() {
  init_work
  if [ -n "$PROJECT" ]; then
    [ -d "$PROJECT" ] || die "project directory not found: $PROJECT"
    PROJECT="$(cd "$PROJECT" && pwd)"
  fi
  set_target claude
}

# Point TARGET, STATE, MANIFEST and the instruction file at one target (claude or codex).
set_target() {
  CUR="$1"
  if [ "$1" = codex ]; then
    TARGET="$CODEX_HOME"
    SETTINGS=""
  else
    if [ -n "$PROJECT" ]; then
      TARGET="$PROJECT/.claude"
    else
      TARGET="$CLAUDE_HOME"
    fi
    SETTINGS="$TARGET/settings.json"
  fi
  STATE="$TARGET/agentkit"
  MANIFEST="$STATE/manifest.json"
  BACKUP_DIR="$STATE/backups/$TS"
}

# Choose TARGETS. install: the CLIs found (REQ_HAVE_*). Others: every target with a manifest.
select_targets() { # install | other
  local t
  TARGETS=""
  if [ -n "$PROJECT" ]; then
    case "$TARGET_OPT" in codex | both) die "--project with codex is not supported in 0.2.0" ;; esac
    TARGETS=claude
  elif [ -n "$TARGET_OPT" ]; then
    case "$TARGET_OPT" in both) TARGETS="claude codex" ;; *) TARGETS="$TARGET_OPT" ;; esac
    if [ "$1" = install ]; then
      for t in $TARGETS; do
        case "$t:${REQ_HAVE_CLAUDE:-0}:${REQ_HAVE_CODEX:-0}" in
          claude:0:* | codex:*:0) warn "$t CLI not found; installing for --target $TARGET_OPT anyway" ;;
        esac
      done
    fi
  elif [ "$1" = install ]; then
    [ "${REQ_HAVE_CLAUDE:-0}" = 1 ] && TARGETS=claude
    [ "${REQ_HAVE_CODEX:-0}" = 1 ] && TARGETS="$TARGETS codex"
  else
    for t in claude codex; do
      set_target "$t"
      if [ -f "$MANIFEST" ] || { [ "$1" = uninstall ] && [ -d "$STATE" ]; }; then TARGETS="$TARGETS $t"; fi
    done
  fi
  TARGETS="${TARGETS# }"
  [ -n "$TARGETS" ] || TARGETS=claude
  set_target "${TARGETS%% *}"
}

claude_only() { # command name
  [ "$TARGET_OPT" = codex ] && die "$1 is only for the claude target"
  return 0
}

# Back up a file or symlink into the state dir before it is changed or removed.
backup() {
  local f="$1" rel dest
  [ -e "$f" ] || [ -L "$f" ] || return 0
  case "$f" in "$TARGET"/*) rel="${f#"$TARGET"/}" ;; "$PROJECT"/*) rel="${f#"$PROJECT"/}" ;; *) rel="$(basename "$f")" ;; esac
  dest="$BACKUP_DIR/$rel"
  if [ "$DRY" = 1 ]; then dry "back up $f -> $dest"; return 0; fi
  # A symlinked file is backed up as a copy of its content, not as a link. Folders keep -P.
  if [ -L "$f" ] && [ -f "$f" ]; then
    mkdir -p "$(dirname "$dest")" && cp -pL "$f" "$dest" || die "backup of $f failed"
  else
    mkdir -p "$(dirname "$dest")" && cp -PpR "$f" "$dest" || die "backup of $f failed"
  fi
}

# ---------------------------------------------------------------- settings.json hooks
# hook_apply EVENT SOURCE COMMAND TIMEOUT QUESTION. Sets HOOK_RES (unchanged|skipped|failed|added|updated).
HOOK_RES=""
hook_apply() {
  local st
  HOOK_RES=failed
  st="$(py hook-add "$SETTINGS" "$1" "$2" "$3" "$4" check)" || { warn "cannot read $SETTINGS (invalid JSON?); hook not added"; return 1; }
  if [ "$st" = unchanged ]; then ui_item unchanged "settings.json: $2 already present"; HOOK_RES=unchanged; return 0; fi
  # Show the entry unless --quiet; but never hide it when a y/N prompt follows.
  if [ "$QUIET" != 1 ] || { [ "$YES" != 1 ] && [ "$DRY" != 1 ]; }; then
    printf 'settings.json: %s this entry in %s:\n' "$st" "$SETTINGS"
    if [ "$st" = updated ]; then
      printf '  It replaces this existing entry:\n'
      py hook-old "$SETTINGS" "$1" "$2" | sed 's/^/    /'
      printf '  with:\n'
    fi
    py hook-show "$1" "$2" "$3" "$4" | sed 's/^/    /'
  fi
  if [ "$DRY" = 1 ]; then dry "settings.json: $st $2"; HOOK_RES=dry; return 0; fi
  ask "$5" || { ui_item skipped "settings.json: skipped"; HOOK_RES=skipped; return 1; }
  backup "$SETTINGS"
  py hook-add "$SETTINGS" "$1" "$2" "$3" "$4" write > /dev/null || { warn "cannot write $SETTINGS"; return 1; }
  ui_item installed "settings.json: $2 $st"
  HOOK_RES="$st"
}

hook_remove() { # prefix
  local n
  [ -f "$SETTINGS" ] || return 0
  n="$(py hook-remove "$SETTINGS" "$1" check)" || { warn "cannot read $SETTINGS; hook entries left"; return 0; }
  [ "$n" -gt 0 ] || return 0
  if [ "$DRY" = 1 ]; then dry "settings.json: remove $n entr(y/ies) marked $1*"; return 0; fi
  backup "$SETTINGS"
  py hook-remove "$SETTINGS" "$1" write > /dev/null || { warn "cannot write $SETTINGS"; return 0; }
  say "settings.json: removed $n entr(y/ies) marked $1*"
}

AGENTLOG_CMD() { printf 'python3 -I "%s/hooks/agent-log.py" check || true' "$AGENTKIT_HOME"; }

step_hooks() {
  skipped hooks && { ui_item skipped "hooks: skipped (--skip hooks)"; ui_summary_add "$CUR" hooks skipped; return; }
  hook_apply SubagentStop agentkit-agent-log "$(AGENTLOG_CMD)" 20 "Add the SubagentStop agent-log hook to $SETTINGS?"
  ui_summary_add "$CUR" "SubagentStop hook" "$HOOK_RES"
}

# ---------------------------------------------------------------- Codex config.toml
# Render the agent files and the config block for Codex into WORK. Agents already defined by the
# user outside our markers are left out (files and block) with a warning.
# ---------------------------------------------------------------- dependencies
# Where each host's gstack lives. Claude: the clone itself. Codex: setup writes
# $CODEX_HOME/skills/gstack-* (never clone the full repo under CODEX_HOME/skills).
gs_present() { # host -> prints a path and returns 0 when installed
  local p
  if [ "$1" = codex ]; then
    p="$(ls -d "$CODEX_HOME"/skills/gstack-* 2> /dev/null | head -n 1)"
    [ -n "$p" ] || return 1
    echo "$CODEX_HOME/skills/gstack-*"
  else
    [ -e "$CLAUDE_HOME/skills/gstack" ] || return 1
    echo "$CLAUDE_HOME/skills/gstack"
  fi
}

step_gstack() {
  local url=https://github.com/garrytan/gstack.git t p gs="" need="" cmd cloning=0 h log rc
  skipped gstack && { ui_item skipped "gstack: skipped (--skip gstack)"; ui_summary_add gstack - skipped; return; }
  for t in $TARGETS; do
    if p="$(gs_present "$t")"; then ui_item unchanged "gstack: already installed ($p)"
    else need="$need $t"; fi
  done
  need="${need# }"
  has_need() { case " $need " in *" $1 "*) return 0 ;; esac; return 1; }
  if [ -z "$need" ]; then ui_summary_add gstack - "already installed"; return; fi
  # Reuse an existing clone: the Claude one, else ~/gstack. Otherwise clone to the Claude
  # location when claude is a target, else to ~/gstack.
  if [ -f "$CLAUDE_HOME/skills/gstack/setup" ]; then gs="$CLAUDE_HOME/skills/gstack"
  elif [ -f "$HOME/gstack/setup" ] && ! has_need claude; then gs="$HOME/gstack"
  else
    cloning=1
    if has_target claude; then gs="$CLAUDE_HOME/skills/gstack"; else gs="$HOME/gstack"; fi
  fi
  cmd=""
  [ "$cloning" = 1 ] && cmd="git clone --single-branch --depth 1 $url $gs && "
  cmd="${cmd}cd $gs"
  for h in $need; do cmd="$cmd && ./setup --host $h"; done
  if [ "$DRY" = 1 ]; then dry "gstack: $cmd"; return; fi
  if [ "$cloning" = 1 ]; then
    ask "Install gstack (git clone into $gs, then its ./setup, needs git and bun)?" || { ui_item skipped "gstack: skipped. Manual: $cmd"; ui_summary_add gstack - skipped; return; }
    command -v git > /dev/null 2>&1 || { warn "gstack: git not found. Manual: $cmd"; return; }
  else
    ask "Run gstack's ./setup for: $need (needs bun)?" || { ui_item skipped "gstack: skipped. Manual: $cmd"; ui_summary_add gstack - skipped; return; }
  fi
  command -v bun > /dev/null 2>&1 || { warn "gstack: bun not found (https://bun.sh). Manual: $cmd"; return; }
  if [ "$cloning" = 1 ]; then
    mkdir -p "$(dirname "$gs")"
    # shellcheck disable=SC2046
    git clone $(ui_git_progress_flag) --single-branch --depth 1 "$url" "$gs" || { warn "gstack: clone failed"; return; }
  fi
  for h in $need; do
    set_target "$h"
    [ "$h" = codex ] && say "  note: gstack on Codex is experimental; its safety skills (careful, guard, freeze) are advisory there."
    mkdir -p "$STATE/logs" || { warn "cannot create $STATE/logs"; continue; }
    log="$STATE/logs/gstack-setup-$TS.log"
    ui_spin "gstack setup (--host $h)" "$log" bash -c 'cd "$1" && exec ./setup --host "$2"' _ "$gs" "$h"; rc=$?
    arm_traps
    if [ "$rc" = 0 ]; then
      ui_item installed "gstack: set up for $h (log: $log)"; ui_summary_add "$h" gstack installed
    else
      warn "gstack: ./setup --host $h failed; run it by hand in $gs (log: $log)"; ui_summary_add "$h" gstack failed
    fi
  done
}

step_karpathy() {
  local m="https://github.com/forrestchang/andrej-karpathy-skills.git" p="andrej-karpathy-skills@karpathy-skills"
  skipped karpathy && { ui_item skipped "karpathy: skipped (--skip karpathy)"; ui_summary_add claude karpathy skipped; return; }
  if ! command -v claude > /dev/null 2>&1; then
    say "karpathy: claude CLI not found. Run later:"
    say "  claude plugin marketplace add $m && claude plugin install $p"
    return
  fi
  if claude plugin list 2> /dev/null | grep -q 'andrej-karpathy-skills'; then ui_item unchanged "karpathy: plugin already installed"; ui_summary_add claude karpathy unchanged; return; fi
  if [ "$DRY" = 1 ]; then dry "karpathy: claude plugin marketplace add $m; claude plugin install $p"; return; fi
  ask "Install the karpathy-guidelines plugin with the claude CLI?" || { ui_item skipped "karpathy: skipped. Manual: claude plugin marketplace add $m && claude plugin install $p"; ui_summary_add claude karpathy skipped; return; }
  claude plugin marketplace add "$m" || warn "karpathy: marketplace add failed (maybe already added)"
  claude plugin install "$p" || warn "karpathy: install failed; run it by hand"
  ui_summary_add claude karpathy installed
}

# ---------------------------------------------------------------- commands
STEP_I=0 STEP_N=0
next_step() { STEP_I=$((STEP_I + 1)); ui_step "$STEP_I" "$STEP_N" "$1"; }
has_target() { case " $TARGETS " in *" $1 "*) return 0 ;; esac; return 1; }

count_steps() { # install steps for TARGETS
  local n=0
  if has_target claude; then
    n=$((n + 1))
    skipped claude-md || n=$((n + 1))
    skipped hooks || n=$((n + 1))
  fi
  if has_target codex; then
    n=$((n + 2))
    skipped claude-md || n=$((n + 1))
  fi
  skipped gstack || n=$((n + 1))
  if has_target claude && ! skipped karpathy; then n=$((n + 1)); fi
  echo "$n"
}

# Refresh hook entries that carry our marker but whose command changed (for example AGENTKIT_HOME
# moved). Never adds an entry. No prompt: only our own marked entries are touched.
refresh_hooks() {
  local src ev cmd t st
  skipped hooks && return 0
  [ -f "$SETTINGS" ] || return 0
  for src in agentkit-agent-log agentkit-auto-update; do
    if [ "$src" = agentkit-agent-log ]; then ev=SubagentStop; cmd="$(AGENTLOG_CMD)"; t=20
    else ev=SessionStart; cmd="\"$AGENTKIT_HOME/hooks/update-check.sh\""; t=5; fi
    st="$(py hook-add "$SETTINGS" "$ev" "$src" "$cmd" "$t" check refresh 2> /dev/null)" || continue
    [ "$st" = unchanged ] && continue
    if [ "$DRY" = 1 ]; then dry "settings.json: refresh $src"; continue; fi
    backup "$SETTINGS"
    if py hook-add "$SETTINGS" "$ev" "$src" "$cmd" "$t" write refresh > /dev/null; then ui_item installed "settings.json: refreshed $src"; fi
  done
}

update_failed() {
  printf 'error: %s\n' "$1" >&2
  if [ "$QUIET" = 1 ] && [ "$DRY" != 1 ]; then
    echo "agentkit: auto-update failed, see $STATE/update.log" > "$UPDATE_STATUS"
  fi
  exit 1
}

cmd_auto_update() {
  local sub="${1:-status}"
  [ $# -gt 0 ] && shift
  parse_args "$@"; ui_init; need_python; claude_only auto-update; resolve_target
  local cmd="$AGENTKIT_HOME/hooks/update-check.sh"
  case "$sub" in
    on)
      [ -x "$cmd" ] || die "$cmd not found or not executable"
      hook_apply SessionStart agentkit-auto-update "\"$cmd\"" 5 "Add the SessionStart auto-update hook to $SETTINGS?" ;;
    off) hook_remove agentkit-auto-update ;;
    status)
      if [ -f "$SETTINGS" ] && py hook-has "$SETTINGS" agentkit-auto-update 2> /dev/null; then echo "auto-update: on"; else echo "auto-update: off"; fi ;;
    *) die "usage: agentkit auto-update on|off|status" ;;
  esac
}

cmd_log() { need_python; exec python3 -I "$AGENTKIT_HOME/hooks/agent-log.py" "$@"; }

cmd_feedback() {
  parse_args "$@"; ui_init; need_python; claude_only feedback; resolve_target
  local f title keep
  f="$(mktmp)"
  python3 -I "$AGENTKIT_HOME/hooks/agent-log.py" export --out "$f" || die "log export failed"
  if [ ! -s "$f" ] || ! py export-has-groups "$f"; then
    echo "Nothing to send: no open issues in the agent log."
    return 0
  fi
  cat "$f"
  echo ""
  title="agent-log feedback $(date +%Y-%m-%d)"
  # Keep a copy outside the work dir (which is removed on exit).
  mkdir -p "$STATE" && keep="$STATE/feedback-$TS.json" && cp "$f" "$keep" || die "cannot save the export in $STATE"
  if ! command -v gh > /dev/null 2>&1; then
    echo "gh not found. The export is saved in $keep"
    echo "Open https://github.com/IbrahimHosseini/agentkit/issues/new and paste it."
    return 0
  fi
  if ! ask "Create the GitHub issue '$title' with this text in IbrahimHosseini/agentkit?"; then
    echo "Not sent. The export is saved in $keep"
    return 0
  fi
  if gh issue create --repo IbrahimHosseini/agentkit --title "$title" --label agent-log --body-file "$f" \
    || gh issue create --repo IbrahimHosseini/agentkit --title "$title" --body-file "$f"; then
    rm -f "$keep"
  else
    echo "gh failed. The export is saved in $keep"
    return 1
  fi
}

cmd_help() {
  cat <<'EOF'
agentkit: shared Claude Code agents and skills

  agentkit install [--target claude|codex|both] [--project DIR] [--dry-run] [--yes] [--force] [--skip STEP]...
        STEP is one of: gstack karpathy claude-md hooks skills
        --target: install default is every CLI found (claude, codex). update, uninstall and
        doctor default to every target that is installed. --project is claude only.
        claude-md also covers the Codex AGENTS.md block.
  agentkit update [--target T] [--project DIR] [--quiet] [--force] [--dry-run]
  agentkit auto-update on|off|status       (claude only)
  agentkit uninstall [--target T] [--project DIR] [--purge] [--dry-run] [--yes]
  agentkit doctor [--target T] [--project DIR]
  agentkit log report|resolve|export|merge [args]
  agentkit feedback
  agentkit version | help

Environment: AGENTKIT_HOME (default ~/.agentkit), AGENTKIT_REPO, CLAUDE_CONFIG_DIR, CODEX_HOME (default ~/.codex)
EOF
}

if [ "${AGENTKIT_LIBRARY_ONLY:-}" != 1 ]; then
case "${1:-help}" in
  auto-update) shift; cmd_auto_update "$@" ;;
  log) shift; cmd_log "$@" ;;
  feedback) shift; cmd_feedback "$@" ;;
  version | --version | -v) version ;;
  help | --help | -h) cmd_help ;;
  *) printf 'unknown command: %s\n\n' "$1" >&2; cmd_help >&2; exit 1 ;;
esac

fi
