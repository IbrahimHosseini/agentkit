#!/usr/bin/env bash
# agentkit bootstrap.
#   curl -fsSL https://raw.githubusercontent.com/IbrahimHosseini/agentkit/main/install.sh | bash -s -- [flags]
#   ./install.sh [flags]            (from a checkout)
# Flags are passed to: agentkit install (see: agentkit help)
set -u

REPO="${AGENTKIT_REPO:-https://github.com/IbrahimHosseini/agentkit.git}"
DRY=0
YES=0
QUIET=0
REQ_WANT=auto
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
# -q is spelled --quiet for the agentkit CLI. --target is read here only to know which CLIs to require.
args=()
want_next=0
for a in "$@"; do
  if [ "$want_next" = 1 ]; then REQ_WANT="$a"; want_next=0; args+=("$a"); continue; fi
  case "$a" in
    --dry-run) DRY=1 ;;
    --yes | -y) YES=1 ;;
    --quiet | -q) QUIET=1; a="--quiet" ;;
    --target) want_next=1 ;;
    --target=*) REQ_WANT="${a#--target=}" ;;
  esac
  args+=("$a")
done
[ "$want_next" = 1 ] && die "--target needs claude, codex or both"
case "$REQ_WANT" in auto | claude | codex | both) ;; *) die "--target: unknown value '$REQ_WANT' (claude|codex|both)" ;; esac
set -- ${args[@]+"${args[@]}"}

# >>> agentkit:requirements
req_tty() { { : < /dev/tty; } 2> /dev/null; }

req_ask() {
  local ans
  req_tty || return 1
  printf '%s [y/N] ' "$1" > /dev/tty
  read -r ans < /dev/tty || return 1
  case "$ans" in y | Y | yes | YES | Yes) return 0 ;; esac
  return 1
}

req_ui() {
  case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
    *[Uu][Tt][Ff]-8* | *[Uu][Tt][Ff]8*) REQ_OKM="✓"; REQ_BADM="✗" ;;
    *) REQ_OKM="+"; REQ_BADM="x" ;;
  esac
  REQ_G=""; REQ_R=""; REQ_Z=""
  if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    REQ_G=$'\033[32m'; REQ_R=$'\033[31m'; REQ_Z=$'\033[0m'
  fi
}

req_detect() {
  local p
  REQ_OS=other; REQ_PM=none; REQ_SUDO="sudo "
  [ "$(id -u 2> /dev/null)" = 0 ] && REQ_SUDO=""
  case "$(uname -s 2> /dev/null)" in
    Darwin) REQ_OS=mac; command -v brew > /dev/null 2>&1 && REQ_PM=brew ;;
    Linux)
      REQ_OS=linux
      for p in apt-get dnf pacman brew; do
        if command -v "$p" > /dev/null 2>&1; then REQ_PM="$p"; break; fi
      done
      ;;
  esac
}

# Sets REQ_V_<tool> (version) and REQ_S_<tool> (ok | old | missing).
# shellcheck disable=SC2154
req_scan() {
  local t v major minor
  for t in git python3 claude codex gh bun; do
    v=""
    if command -v "$t" > /dev/null 2>&1; then
      v="$("$t" --version 2> /dev/null | head -n 1 | grep -Eo '[0-9]+(\.[0-9]+)+' | head -n 1)"
      [ -n "$v" ] || v="unknown"
      eval "REQ_S_$t=ok"
      if [ "$t" = python3 ]; then
        major="${v%%.*}"; minor="${v#*.}"; minor="${minor%%.*}"
        case "$v" in unknown) eval "REQ_S_$t=old" ;; *)
          if [ "$major" -lt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -lt 9 ]; }; then eval "REQ_S_$t=old"; fi ;;
        esac
      fi
    else
      eval "REQ_S_$t=missing"
    fi
    eval "REQ_V_$t=\$v"
  done
  REQ_HAVE_CLAUDE=0; REQ_HAVE_CODEX=0
  [ "$REQ_S_claude" = ok ] && REQ_HAVE_CLAUDE=1
  [ "$REQ_S_codex" = ok ] && REQ_HAVE_CODEX=1
}

req_agent_ok() {
  case "${REQ_WANT:-auto}" in
    claude) [ "$REQ_HAVE_CLAUDE" = 1 ] ;;
    codex) [ "$REQ_HAVE_CODEX" = 1 ] ;;
    both) [ "$REQ_HAVE_CLAUDE" = 1 ] && [ "$REQ_HAVE_CODEX" = 1 ] ;;
    *) [ "$REQ_HAVE_CLAUDE" = 1 ] || [ "$REQ_HAVE_CODEX" = 1 ] ;;
  esac
}
# Is this agent CLI part of what the target asks for?
req_wants() {
  case "${REQ_WANT:-auto}" in
    auto | both) return 0 ;;
    *) [ "${REQ_WANT}" = "$1" ] ;;
  esac
}
# REQ_S_<tool> is assigned through eval in req_scan, so shellcheck cannot see it.
# shellcheck disable=SC2154
req_met() { [ "$REQ_S_git" = ok ] && [ "$REQ_S_python3" = ok ] && req_agent_ok; }

req_row() {
  local mark="$1" color="$2" name="$3" note="$4"
  printf '  %s%s%s %-8s %s\n' "$color" "$mark" "$REQ_Z" "$name" "$note"
}

req_list() {
  local t s v note
  echo "Requirements:"
  for t in git python3 claude codex gh bun; do
    eval "s=\$REQ_S_$t; v=\$REQ_V_$t"
    case "$t:$s" in
      python3:old) req_row "$REQ_BADM" "$REQ_R" "$t" "found $v, need 3.9 or newer" ;;
      *:ok) req_row "$REQ_OKM" "$REQ_G" "$t" "$v" ;;
      *)
        case "$t" in
          git | python3) note="required" ;;
          claude | codex)
            if ! req_wants "$t"; then note="optional (not needed for this target)"
            elif [ "${REQ_WANT:-auto}" = auto ]; then
              if req_agent_ok; then note="optional (the other agent is installed)"
              else note="one of claude or codex is required"; fi
            else note="required"; fi ;;
          *) note="optional" ;;
        esac
        req_row "$REQ_BADM" "$REQ_R" "$t" "not found, $note"
        ;;
    esac
  done
}

# Sets REQ_KIND (pm | script | link), REQ_CMD, REQ_LINK for one tool.
req_plan() {
  local t="$1" pkg
  REQ_KIND='link'; REQ_CMD=""
  case "$t" in
    git) REQ_LINK="https://git-scm.com/downloads" ;;
    python3) REQ_LINK="https://www.python.org/downloads/" ;;
    gh) REQ_LINK="https://cli.github.com" ;;
    bun) REQ_LINK="https://bun.sh" ;;
    codex) REQ_LINK="https://github.com/openai/codex" ;;
    claude) REQ_LINK="https://docs.claude.com/en/docs/claude-code/setup" ;;
  esac
  case "$t" in
    claude) REQ_KIND=script; REQ_CMD='curl -fsSL https://claude.ai/install.sh | bash'; return 0 ;;
    bun)
      if [ "$REQ_PM" = brew ]; then REQ_KIND=pm; REQ_CMD='brew install oven-sh/bun/bun'
      else REQ_KIND=script; REQ_CMD='curl -fsSL https://bun.sh/install | bash'; fi
      return 0 ;;
    codex)
      if [ "$REQ_PM" = brew ]; then REQ_KIND=pm; REQ_CMD='brew install codex'
      elif command -v npm > /dev/null 2>&1; then REQ_KIND=pm; REQ_CMD='npm i -g @openai/codex'; fi
      return 0 ;;
  esac
  pkg="$t"
  case "$REQ_PM:$t" in
    brew:python3) pkg="python@3.12" ;;
    pacman:python3) pkg="python" ;;
    pacman:gh) pkg="github-cli" ;;
  esac
  case "$REQ_PM" in
    brew) REQ_KIND=pm; REQ_CMD="brew install $pkg" ;;
    apt-get) REQ_KIND=pm; REQ_CMD="${REQ_SUDO}apt-get install -y $pkg" ;;
    dnf) REQ_KIND=pm; REQ_CMD="${REQ_SUDO}dnf install -y $pkg" ;;
    pacman) REQ_KIND=pm; REQ_CMD="${REQ_SUDO}pacman -S --noconfirm $pkg" ;;
  esac
}

req_suggest_one() {
  local t="$1"
  req_plan "$t"
  case "$REQ_KIND" in
    pm) printf '  %-8s %s\n' "$t" "$REQ_CMD" ;;
    script) printf '  %-8s %s   (downloads and runs a remote script)\n' "$t" "$REQ_CMD" ;;
    *)
      if [ "$REQ_OS" = mac ] && [ "$REQ_PM" = none ]; then
        printf '  %-8s install Homebrew (https://brew.sh), or get it from %s\n' "$t" "$REQ_LINK"
      else
        printf '  %-8s install it from %s\n' "$t" "$REQ_LINK"
      fi
      ;;
  esac
}

req_suggest() {
  local t s any=0
  for t in git python3 gh bun; do
    eval "s=\$REQ_S_$t"
    [ "$s" = ok ] && continue
    [ "$any" = 0 ] && { echo "How to install what is missing:"; any=1; }
    req_suggest_one "$t"
  done
  if ! req_agent_ok; then
    [ "$any" = 0 ] && echo "How to install what is missing:"
    for t in claude codex; do
      eval "s=\$REQ_S_$t"
      if [ "$s" != ok ] && req_wants "$t"; then req_suggest_one "$t"; fi
    done
  fi
}

# Install one tool after consent. Remote scripts are never accepted by YES=1.
req_install() {
  local t="$1"
  req_plan "$t"
  case "$REQ_KIND" in
    pm)
      if [ "${YES:-0}" = 1 ]; then echo "Running: $REQ_CMD"
      elif req_tty; then req_ask "Install $t with: $REQ_CMD ?" || return 1
      else echo "No TTY: not running. Command: $REQ_CMD"; return 1; fi
      ;;
    script)
      if req_tty; then
        echo "This downloads and runs a remote script. Exact command:"
        echo "  $REQ_CMD"
        req_ask "Run it to install $t?" || return 1
      else
        echo "No TTY: not running a remote script. Run it yourself: $REQ_CMD"
        return 1
      fi
      ;;
    *) return 1 ;;
  esac
  eval "$REQ_CMD" < /dev/null || { echo "error: install of $t failed" >&2; return 1; }
  if [ "$REQ_KIND" = script ] && [ -d "$HOME/.local/bin" ]; then
    case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$HOME/.local/bin:$PATH" ;; esac
  fi
  hash -r 2> /dev/null
  return 0
}

check_requirements() {
  local mode="${1:-report}" t
  case "$mode" in install | report) ;; *) echo "check_requirements: use install or report" >&2; return 2 ;; esac
  case "${REQ_WANT:-auto}" in auto | claude | codex | both) ;; *) echo "check_requirements: REQ_WANT must be auto, claude, codex or both" >&2; return 2 ;; esac
  req_ui; req_detect; req_scan
  if req_met; then
    [ "${QUIET:-0}" = 1 ] || req_list
    return 0
  fi
  req_list
  req_suggest
  if [ "$mode" = install ] && [ "${DRY:-0}" != 1 ]; then
    for t in git python3; do
      eval "[ \"\$REQ_S_$t\" = ok ]" || req_install "$t"
    done
    req_scan
    if ! req_agent_ok; then
      if [ "${REQ_WANT:-auto}" = auto ]; then
        req_install claude || true
        req_scan
        req_agent_ok || { req_install codex || true; req_scan; }
      else
        for t in claude codex; do
          eval "[ \"\$REQ_S_$t\" = ok ]" || { req_wants "$t" && { req_install "$t" || true; }; }
        done
        req_scan
      fi
    fi
    if req_met; then req_list; return 0; fi
  fi
  return 1
}
# <<< agentkit:requirements

# Check git, python3 and an agent CLI before cloning (the clone needs git).
export DRY YES QUIET REQ_WANT
check_requirements install || die "requirements are not met"
export AGENTKIT_REQS_OK=1

tmp_clone=""
cleanup() { [ -n "$tmp_clone" ] && [ -d "$tmp_clone" ] && rm -rf "${tmp_clone:?}"; }
trap cleanup EXIT

# Run from a checkout? Use it as AGENTKIT_HOME.
here=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
if [ -n "$here" ] && [ -f "$here/bin/agentkit" ]; then
  AGENTKIT_HOME="$here"
  [ "$QUIET" = 1 ] || echo "Using checkout: $AGENTKIT_HOME"
else
  AGENTKIT_HOME="${AGENTKIT_HOME:-$HOME/.agentkit}"
  if [ -d "$AGENTKIT_HOME/.git" ]; then
    if [ "$DRY" = 1 ]; then echo "[dry-run] git -C $AGENTKIT_HOME pull --ff-only"
    else git -C "$AGENTKIT_HOME" pull --ff-only || echo "warning: could not fast-forward $AGENTKIT_HOME; continuing with the current version" >&2; fi
  elif [ -e "$AGENTKIT_HOME" ]; then
    die "$AGENTKIT_HOME exists and is not a git clone"
  elif [ "$DRY" = 1 ]; then
    real_home="$AGENTKIT_HOME"
    tmp_clone="$(mktemp -d "${TMPDIR:-/tmp}/agentkit-dry.XXXXXX")" || die "mktemp failed"
    echo "[dry-run] git clone $REPO $AGENTKIT_HOME  (using a temporary clone for this dry run)"
    git clone --quiet "$REPO" "$tmp_clone/agentkit" || die "clone failed"
    AGENTKIT_HOME="$tmp_clone/agentkit"
  else
    mkdir -p "$(dirname "$AGENTKIT_HOME")" || die "cannot create $(dirname "$AGENTKIT_HOME")"
    if [ -t 2 ]; then clone_flags="--progress"; else clone_flags=""; fi
    # shellcheck disable=SC2086
    git clone $clone_flags "$REPO" "$AGENTKIT_HOME" || die "clone failed"
  fi
fi
[ -x "$AGENTKIT_HOME/bin/agentkit" ] || die "$AGENTKIT_HOME/bin/agentkit not found"
export AGENTKIT_HOME

# Link the CLI into ~/.local/bin. Ask before replacing anything that is not already our link.
yes=0
for a in "$@"; do
  case "$a" in --yes | -y) yes=1 ;; esac
done
confirm() {
  local ans
  [ "$yes" = 1 ] && return 0
  if { : < /dev/tty; } 2> /dev/null; then
    printf '%s [y/N] ' "$1" > /dev/tty
    read -r ans < /dev/tty
    case "$ans" in y | Y | yes | YES) return 0 ;; esac
  fi
  return 1
}
link="$HOME/.local/bin/agentkit"
want="${real_home:-$AGENTKIT_HOME}/bin/agentkit"
if [ -L "$link" ] && [ "$(readlink "$link")" = "$want" ]; then
  :
elif [ -e "$link" ] || [ -L "$link" ]; then
  if [ -L "$link" ]; then what="a link to $(readlink "$link")"; else what="a regular file"; fi
  if [ "$DRY" = 1 ]; then
    echo "[dry-run] $link is $what; would ask before replacing it with a link to $want"
  elif confirm "$link is $what. Replace it with a link to $want?"; then
    if [ ! -L "$link" ]; then
      bak="$link.bak-$(date +%Y%m%d-%H%M%S)"
      mv "$link" "$bak" && { [ "$QUIET" = 1 ] || echo "Backed up $link to $bak"; }
    fi
    ln -sf "$want" "$link" && { [ "$QUIET" = 1 ] || echo "Linked $link"; }
  else
    echo "warning: left $link as it is (it is $what). The CLI is at $want" >&2
  fi
elif [ "$DRY" = 1 ]; then
  echo "[dry-run] ln -s $want $link"
else
  mkdir -p "$HOME/.local/bin" && ln -s "$want" "$link" && { [ "$QUIET" = 1 ] || echo "Linked $link"; }
fi
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "warning: $HOME/.local/bin is not on your PATH. Add this to your shell profile: export PATH=\"\$HOME/.local/bin:\$PATH\"" >&2 ;;
esac

# Not exec when a temp clone must be cleaned up afterwards.
if [ -n "$tmp_clone" ]; then
  "$AGENTKIT_HOME/bin/agentkit" install "$@"
  exit $?
fi
exec "$AGENTKIT_HOME/bin/agentkit" install "$@"
