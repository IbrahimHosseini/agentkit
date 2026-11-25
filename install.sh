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
  local columns="${COLUMNS:-}" size
  REQ_TABLE=0 REQ_BAR='|' REQ_JOIN='+' REQ_DASH='-'
  case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
    *[Uu][Tt][Ff]-8* | *[Uu][Tt][Ff]8*)
      REQ_OKM="✓"; REQ_BADM="✗"; REQ_BAR='│'; REQ_JOIN='┼'; REQ_DASH='─' ;;
    *) REQ_OKM="+"; REQ_BADM="x" ;;
  esac
  REQ_G="" REQ_R="" REQ_Z="" REQ_CLAUDE="" REQ_CODEX=""
  if [ -t 1 ] && [ "${TERM:-}" != dumb ]; then
    REQ_TABLE=1
    if ! [[ "$columns" =~ ^[1-9][0-9]{0,4}$ ]]; then
      { size="$(stty size <&3 2>/dev/null)" || size=''; } 3<&1
      columns="${size##* }"
    fi
    if [[ "$columns" =~ ^[1-9][0-9]{0,4}$ ]] && [ "$columns" -lt 38 ]; then REQ_TABLE=2; fi
  fi
  if [ "$REQ_TABLE" != 0 ] && [ -z "${NO_COLOR:-}" ] && [ "${QUIET:-0}" != 1 ]; then
    REQ_G=$'\033[32m'; REQ_R=$'\033[31m'; REQ_Z=$'\033[0m'
    case "${TERM:-}:${COLORTERM:-}" in
      *256color*:* | *:truecolor | *:24bit)
        REQ_CLAUDE=$'\033[38;5;173m'; REQ_CODEX=$'\033[38;5;73m' ;;
      *) REQ_CLAUDE=$'\033[33m'; REQ_CODEX=$'\033[36m' ;;
    esac
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
      for p in apt-get dnf pacman zypper apk brew; do
        if command -v "$p" > /dev/null 2>&1; then REQ_PM="$p"; break; fi
      done
      ;;
  esac
}

# Sets REQ_V_<tool> (version) and REQ_S_<tool> (ok | old | missing).
# shellcheck disable=SC2154
req_scan() {
  local t v major minor raw
  for t in git python3 claude codex gh bun; do
    v=""
    if command -v "$t" > /dev/null 2>&1; then
      if ! raw="$("$t" --version 2>&1)"; then
        eval "REQ_S_$t=broken; REQ_V_$t=\$raw"
        continue
      fi
      v="$(printf '%s\n' "$raw" | head -n 1 | grep -Eo '[0-9]+(\.[0-9]+)+' | head -n 1)"
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
req_met() { [ "$REQ_S_git" = ok ] && [ "$REQ_S_python3" = ok ] && { [ "${REQ_BOOTSTRAP:-0}" = 1 ] || req_agent_ok; }; }

# The final column stays open so long diagnostic text and commands can wrap.
req_table_row() {
  local name="$1" note="$2" status="${3:-}" color="${4:-}" accent='' reset='' padding
  case "$name" in
    claude) accent="$REQ_CLAUDE" ;;
    codex) accent="$REQ_CODEX" ;;
  esac
  [ -z "$accent" ] || reset="$REQ_Z"
  note="${note//[[:cntrl:]]/ }"
  if [ "$REQ_TABLE" = 2 ]; then
    printf '  %s%s%s' "$accent" "$name" "$reset"
    [ -z "$status" ] || printf ' %s %s%s%s' "$REQ_BAR" "$color" "$status" "$REQ_Z"
    printf '\n    %s %s\n' "$REQ_BAR" "$note"
    return
  fi
  printf -v padding '%*s' "$((8 - ${#name}))" ''
  printf '  %s%s%s%s %s ' "$accent" "$name" "$reset" "$padding" "$REQ_BAR"
  if [ -n "$status" ]; then
    printf -v padding '%*s' "$((8 - ${#status}))" ''
    printf '%s%s%s%s %s ' "$color" "$status" "$REQ_Z" "$padding" "$REQ_BAR"
  fi
  printf '%s\n' "$note"
}

req_table_heading() {
  [ "${REQ_TABLE:-0}" = 1 ] || return 0
  local start='---------' segment='----------' end='---------------'
  start="${start//-/$REQ_DASH}"; segment="${segment//-/$REQ_DASH}"; end="${end//-/$REQ_DASH}"
  if [ "$#" = 3 ]; then
    printf '  %-8s %s %-8s %s %s\n' "$1" "$REQ_BAR" "$2" "$REQ_BAR" "$3"
    printf '  %s%s%s%s%s\n' "$start" "$REQ_JOIN" "$segment" "$REQ_JOIN" "$end"
  else
    printf '  %-8s %s %s\n' "$1" "$REQ_BAR" "$2"
    printf '  %s%s%s\n' "$start" "$REQ_JOIN" "$end"
  fi
}

req_row() {
  local mark="$1" color="$2" name="$3" note="$4" status="$5"
  if [ "$REQ_TABLE" = 0 ]; then
    printf '  %s%s%s %-8s %s\n' "$color" "$mark" "$REQ_Z" "$name" "$note"
  else
    req_table_row "$name" "$note" "$status" "$color"
  fi
}

req_list() {
  local t s v note
  echo "Requirements:"
  req_table_heading Tool Status Details
  for t in git python3 claude codex gh bun; do
    if [ "${REQ_BOOTSTRAP:-0}" = 1 ]; then case "$t" in git | python3) ;; *) continue ;; esac; fi
    eval "s=\$REQ_S_$t; v=\$REQ_V_$t"
    case "$t:$s" in
      *:broken) req_row "$REQ_BADM" "$REQ_R" "$t" "--version failed: $v; reinstall or fix this command" Broken ;;
      python3:old) req_row "$REQ_BADM" "$REQ_R" "$t" "found $v, need 3.9 or newer" Outdated ;;
      *:ok) req_row "$REQ_OKM" "$REQ_G" "$t" "$v" Ready ;;
      *)
        case "$t" in
          git | python3) note="required" ;;
          claude | codex)
            if ! req_wants "$t"; then note="optional (not needed for this target)"
            elif [ "${REQ_WANT:-auto}" = auto ]; then
              if req_agent_ok; then note="optional (the other agent is installed)"
              else note="one of claude or codex is required"; fi
            else note="required"; fi ;;
          bun) note="required when gstack installation is accepted" ;;
          *) note="optional" ;;
        esac
        req_row "$REQ_BADM" "$REQ_R" "$t" "not found, $note" Missing
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
    pacman:gh | apk:gh) pkg="github-cli" ;;
  esac
  case "$REQ_PM" in
    brew) REQ_KIND=pm; REQ_CMD="brew install $pkg" ;;
    apt-get) REQ_KIND=pm; REQ_CMD="${REQ_SUDO}apt-get install -y $pkg" ;;
    dnf) REQ_KIND=pm; REQ_CMD="${REQ_SUDO}dnf install -y $pkg" ;;
    pacman) REQ_KIND=pm; REQ_CMD="${REQ_SUDO}pacman -S --noconfirm $pkg" ;;
    zypper) REQ_KIND=pm; REQ_CMD="${REQ_SUDO}zypper --non-interactive install $pkg" ;;
    apk) REQ_KIND=pm; REQ_CMD="${REQ_SUDO}apk add $pkg" ;;
  esac
}

req_suggest_one() {
  local t="$1" note
  req_plan "$t"
  case "$REQ_KIND" in
    pm) note="$REQ_CMD" ;;
    script) note="$REQ_CMD   (downloads and runs a remote script)" ;;
    *)
      if [ "$REQ_OS" = mac ] && [ "$REQ_PM" = none ]; then
        note="install Homebrew (https://brew.sh), or get it from $REQ_LINK"
      else
        note="install it from $REQ_LINK"
      fi
      ;;
  esac
  if [ "${REQ_TABLE:-0}" = 0 ]; then
    printf '  %-8s %s\n' "$t" "$note"
  else
    req_table_row "$t" "$note"
  fi
}

req_suggest_heading() {
  echo "How to install what is missing:"
  req_table_heading Tool Installation
}

req_suggest() {
  local t s any=0
  for t in git python3 gh bun; do
    if [ "${REQ_BOOTSTRAP:-0}" = 1 ]; then case "$t" in git | python3) ;; *) continue ;; esac; fi
    eval "s=\$REQ_S_$t"
    [ "$s" = ok ] && continue
    [ "$any" = 0 ] && { req_suggest_heading; any=1; }
    req_suggest_one "$t"
  done
  if [ "${REQ_BOOTSTRAP:-0}" != 1 ] && ! req_agent_ok; then
    [ "$any" = 0 ] && req_suggest_heading
    for t in claude codex; do
      eval "s=\$REQ_S_$t"
      if [ "$s" != ok ] && req_wants "$t"; then req_suggest_one "$t"; fi
    done
  fi
}

# Keep child diagnostics and prompts visible; only the waiting helper is backgrounded.
req_run() {
  local label="$1" command="$2" waiter rc saved_int saved_term log=""
  saved_int="$(trap -p INT)"; saved_term="$(trap -p TERM)"
  [ "${QUIET:-0}" = 1 ] || printf '%s ...\n' "$label"
  (
    tick=""
    trap '[ -z "$tick" ] || kill "$tick" 2>/dev/null; exit 0' INT TERM
    while :; do
      sleep 5 & tick=$!
      wait "$tick" || exit 0
      [ "${QUIET:-0}" = 1 ] || printf '  Waiting: %s\n' "$label"
    done
  ) &
  waiter=$!
  trap 'kill "$waiter" 2>/dev/null; wait "$waiter" 2>/dev/null; exit 130' INT
  trap 'kill "$waiter" 2>/dev/null; wait "$waiter" 2>/dev/null; exit 143' TERM
  if [ "${QUIET:-0}" = 1 ]; then
    log="$(mktemp "${TMPDIR:-/tmp}/agentkit-command.XXXXXX")" || { kill "$waiter" 2>/dev/null; return 1; }
    bash -o pipefail -c "$command" < /dev/null > "$log" 2>&1; rc=$?
    if [ "$rc" != 0 ]; then cat "$log" >&2; fi
    rm -f "$log"
  else bash -o pipefail -c "$command" < /dev/null; rc=$?; fi
  kill "$waiter" 2>/dev/null; wait "$waiter" 2>/dev/null
  trap - INT TERM
  [ -z "$saved_int" ] || eval "$saved_int"
  [ -z "$saved_term" ] || eval "$saved_term"
  if [ "$rc" != 0 ]; then
    printf 'error: %s failed (exit %s). Command: %s. Review the output above and retry.\n' "$label" "$rc" "$command" >&2
    return "$rc"
  fi
  [ "${QUIET:-0}" = 1 ] || printf '%s: complete\n' "$label"
  return 0
}

# Install one tool after consent. Remote scripts are never accepted by YES=1.
req_install() {
  local t="$1" rc
  req_plan "$t"
  case "$REQ_KIND" in
    pm)
      if [ "${YES:-0}" = 1 ]; then echo "Running: $REQ_CMD"
      elif req_tty; then req_ask "Install $t with: $REQ_CMD ?" || { echo "error: $t installation declined; required steps cannot complete. Run: $REQ_CMD" >&2; return 2; }
      else echo "No TTY: not running. Command: $REQ_CMD"; return 2; fi
      ;;
    script)
      if req_tty; then
        echo "This downloads and runs a remote script. Exact command:"
        echo "  $REQ_CMD"
        req_ask "Run it to install $t?" || { echo "error: $t installation declined. Run: $REQ_CMD" >&2; return 2; }
      else
        echo "No TTY: not running a remote script. Run it yourself: $REQ_CMD"
        return 2
      fi
      ;;
    *) echo "error: cannot install $t automatically. Install it from $REQ_LINK and retry." >&2; return 2 ;;
  esac
  req_run "Installing $t" "$REQ_CMD" || return 1
  if [ "$REQ_KIND" = script ] && [ -d "$HOME/.local/bin" ]; then
    case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$HOME/.local/bin:$PATH" ;; esac
  fi
  if [ "$t" = bun ] && [ -d "$HOME/.bun/bin" ]; then
    PATH="$HOME/.bun/bin:$PATH"
  fi
  export PATH
  hash -r 2> /dev/null
  if ! "$t" --version > /dev/null 2>&1; then
    echo "error: $t installation finished but $t --version failed. Check PATH and retry: $REQ_CMD" >&2
    return 1
  fi
  return 0
}

check_requirements() {
  local mode="${1:-report}" t rc
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
      eval "[ \"\$REQ_S_$t\" = ok ]" || req_install "$t" || return 1
    done
    req_scan
    if [ "${REQ_BOOTSTRAP:-0}" != 1 ] && ! req_agent_ok; then
      if [ "${REQ_WANT:-auto}" = auto ]; then
        req_install claude; rc=$?
        [ "$rc" = 0 ] || [ "$rc" = 2 ] || return "$rc"
        req_scan
        req_agent_ok || { req_install codex || return 1; req_scan; }
      else
        for t in claude codex; do
          eval "[ \"\$REQ_S_$t\" = ok ]" || { req_wants "$t" && { req_install "$t" || return 1; }; }
        done
        req_scan
      fi
    fi
    if req_met; then [ "${QUIET:-0}" = 1 ] || req_list; return 0; fi
  fi
  echo "error: required tools are unavailable; review the missing requirements and install commands above, then retry." >&2
  return 1
}
# <<< agentkit:requirements

# With curl | bash, stdin carries this script. Parse the entire installation
# before starting any child that might read stdin and consume the remaining steps.
{
# Check git, python3 and an agent CLI before cloning (the clone needs git).
export DRY YES QUIET REQ_WANT
REQ_BOOTSTRAP=1 check_requirements install || die "bootstrap requirements are not met"
# Desktop detection and target CLI installation run once in the Python core.
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$HOME/.local/bin:$PATH" ;; esac
export PATH

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
  export AGENTKIT_HOME
  if [ -d "$AGENTKIT_HOME/.git" ]; then
    if [ "$DRY" = 1 ]; then echo "[dry-run] git -C $AGENTKIT_HOME pull --ff-only"
    else req_run "Updating agentkit checkout" 'git -C "$AGENTKIT_HOME" pull --ff-only' || die "checkout update failed; inspect Git output, resolve local changes or network access, then retry"; fi
  elif [ -e "$AGENTKIT_HOME" ]; then
    die "$AGENTKIT_HOME exists and is not a git clone"
  elif [ "$DRY" = 1 ]; then
    echo "[dry-run] git clone $REPO $AGENTKIT_HOME"
    echo "[dry-run] Would then check target CLIs, offer optional desktop installation and install agentkit. No download or files written."
    exit 0
  else
    mkdir -p "$(dirname "$AGENTKIT_HOME")" || die "cannot create $(dirname "$AGENTKIT_HOME")"
    if [ -t 2 ]; then clone_flags="--progress"; else clone_flags=""; fi
    # shellcheck disable=SC2086
    [ "$QUIET" = 1 ] || echo "Downloading agentkit checkout ..."
    git clone $clone_flags "$REPO" "$AGENTKIT_HOME" || die "clone failed; review Git output and check repository/network access"
  fi
fi
[ -x "$AGENTKIT_HOME/bin/agentkit" ] || die "$AGENTKIT_HOME/bin/agentkit not found"
export AGENTKIT_HOME

# Complete requirements and the selected installation before adding a launcher.
# A missing target CLI must not leave a new launcher claiming a usable install.
AGENTKIT_BOOTSTRAP_ACTIVE=1 "$AGENTKIT_HOME/bin/agentkit" install "$@" || exit $?

# Link the CLI into ~/.local/bin. Ask before replacing anything that is not already our link.
confirm() { [ "$YES" = 1 ] || req_ask "$1"; }
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
      mv "$link" "$bak" || die "launcher backup failed: $link; check permissions and retry"
      [ "$QUIET" = 1 ] || echo "Backed up $link to $bak"
    fi
    ln -sf "$want" "$link" || die "launcher creation failed: $link; check permissions and retry"
    [ "$QUIET" = 1 ] || echo "Linked $link"
  else
    echo "warning: left $link as it is (it is $what). The CLI is at $want" >&2
    exit 0
  fi
elif [ "$DRY" = 1 ]; then
  echo "[dry-run] ln -s $want $link"
else
  mkdir -p "$HOME/.local/bin" && ln -s "$want" "$link" || die "launcher creation failed: $link; check directory permissions and retry"
  [ "$QUIET" = 1 ] || echo "Linked $link"
fi

# The bootstrap's PATH applies only to this process. Set up future interactive shells separately.
setup_launcher_path() {
  local profile login_profile shell_name="${SHELL:-}" path_status=0
  local marker='# agentkit: launcher PATH'
  local profiles pending=()
  case "${shell_name##*/}" in
    zsh) profiles=("${ZDOTDIR:-$HOME}/.zshrc") ;;
    bash)
      login_profile="$HOME/.profile"
      for profile in "$HOME/.bash_profile" "$HOME/.bash_login"; do
        if [ -f "$profile" ] && [ -r "$profile" ]; then
          login_profile="$profile"
          break
        fi
      done
      profiles=("$HOME/.bashrc" "$login_profile")
      ;;
    *) printf 'warning: Shell PATH setup skipped for %s. Add %s to PATH in your shell settings if needed.\n' "${SHELL:-an unidentified shell}" "$HOME/.local/bin" >&2; return 1 ;;
  esac

  for profile in "${profiles[@]}"; do
    if [ -f "$profile" ] && [ -r "$profile" ] && grep -Fqx -- "$marker" "$profile"; then
      continue
    fi
    if [ -L "$profile" ] || { [ -e "$profile" ] && { [ ! -f "$profile" ] || [ ! -r "$profile" ]; }; }; then
      printf 'warning: Shell PATH setup skipped for %s. Update this shell profile manually.\n' "$profile" >&2
      path_status=1
    else
      pending+=("$profile")
    fi
  done

  [ "${#pending[@]}" -ne 0 ] || return "$path_status"
  if [ "$DRY" = 1 ]; then
    printf '[dry-run] Would add agentkit to PATH in %s\n' "${pending[@]}"
  elif confirm "Add agentkit to PATH in ${pending[*]} for new terminals?"; then
    for profile in "${pending[@]}"; do
      if printf '\n%s\n%s\n' "$marker" \
        'if [ -x "$HOME/.local/bin/agentkit" ]; then
  case ":${PATH:-}:" in
    *":$HOME/.local/bin:"*) ;;
    *) export PATH="$HOME/.local/bin${PATH:+:$PATH}" ;;
  esac
fi' >> "$profile"; then
        [ "$QUIET" = 1 ] || printf 'Configured PATH in %s\n' "$profile"
      else
        printf 'warning: Could not update %s. Add %s to PATH in your shell settings.\n' "$profile" "$HOME/.local/bin" >&2
        path_status=1
      fi
    done
  else
    printf 'warning: Shell PATH setup skipped. Add %s to PATH in your shell settings if needed.\n' "$HOME/.local/bin" >&2
    path_status=1
  fi
  return "$path_status"
}

if setup_launcher_path; then
  [ "$DRY" = 1 ] || [ "$QUIET" = 1 ] || echo "Done. Open a new terminal, then run agentkit doctor."
elif [ "$DRY" = 0 ]; then
  printf 'The launcher is available at "%s". Run it with doctor to check the setup.\n' "$link" >&2
fi
exit 0
}
