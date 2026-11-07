#!/usr/bin/env bash
# Maintainer tool: copy agents from ~/.claude/agents into this repo's agents/.
# Usage: scripts/sync.sh [--new]
# Shows a diff for every changed file and asks y/N before writing. Never writes to ~/.claude.
set -u

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
src="${SYNC_SRC:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/agents}"
new=0
[ "${1:-}" = "--new" ] && new=1
[ -d "$src" ] || { echo "error: $src not found" >&2; exit 1; }

ask() {
  local ans
  if { : < /dev/tty; } 2> /dev/null; then
    printf '%s [y/N] ' "$1" > /dev/tty
    read -r ans < /dev/tty
  else
    read -r ans || ans=n
  fi
  case "$ans" in y | Y | yes) return 0 ;; esac
  return 1
}

copied=0
check() { # name
  local s="$src/$1" d="$root/agents/$1"
  if [ -f "$d" ]; then
    cmp -s "$s" "$d" && return
    echo "=== $1 (changed)"
    diff -u "$d" "$s"
  else
    echo "=== $1 (new)"
    diff -u /dev/null "$s"
  fi
  if ask "Write agents/$1?"; then
    cp "$s" "$d" && copied=$((copied + 1))
  else
    echo "skipped $1"
  fi
}

for f in "$root"/agents/*.md; do
  [ -f "$f" ] || continue
  n="$(basename "$f")"
  [ -f "$src/$n" ] && check "$n"
done
if [ "$new" = 1 ]; then
  for f in "$src"/*.md; do
    [ -f "$f" ] || continue
    n="$(basename "$f")"
    [ -f "$root/agents/$n" ] || check "$n"
  done
fi
echo "Done: $copied file(s) written."
