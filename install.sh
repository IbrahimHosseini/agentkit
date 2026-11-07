#!/usr/bin/env bash
# agentkit bootstrap.
#   curl -fsSL https://raw.githubusercontent.com/IbrahimHosseini/agentkit/main/install.sh | bash -s -- [flags]
#   ./install.sh [flags]            (from a checkout)
# Flags are passed to: agentkit install (see: agentkit help)
set -u

REPO="${AGENTKIT_REPO:-https://github.com/IbrahimHosseini/agentkit.git}"
DRY=0
for a in "$@"; do [ "$a" = "--dry-run" ] && DRY=1; done

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
command -v git > /dev/null 2>&1 || die "git is required"
command -v python3 > /dev/null 2>&1 || die "python3 (3.9 or newer) is required"

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
  echo "Using checkout: $AGENTKIT_HOME"
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
    git clone "$REPO" "$AGENTKIT_HOME" || die "clone failed"
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
      mv "$link" "$bak" && echo "Backed up $link to $bak"
    fi
    ln -sf "$want" "$link" && echo "Linked $link"
  else
    echo "warning: left $link as it is (it is $what). The CLI is at $want" >&2
  fi
elif [ "$DRY" = 1 ]; then
  echo "[dry-run] ln -s $want $link"
else
  mkdir -p "$HOME/.local/bin" && ln -s "$want" "$link" && echo "Linked $link"
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
