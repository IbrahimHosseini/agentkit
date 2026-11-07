#!/usr/bin/env bash
# SessionStart hook: start `agentkit update --quiet` in the background at most once per interval.
# Prints nothing to stdout, except one short line when the last background update needs attention.
# Always exits 0.

claude_home="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
state="$claude_home/agentkit"
stamp="$state/last-update-check"
status="$state/update-status"
interval="${AGENTKIT_UPDATE_INTERVAL:-86400}"

# Where is agentkit? Resolve this script's symlinks, then go up one level.
src="${BASH_SOURCE[0]}"
while [ -L "$src" ]; do
  d="$(cd "$(dirname "$src")" && pwd)"
  src="$(readlink "$src")"
  case "$src" in /*) ;; *) src="$d/$src" ;; esac
done
here="$(cd "$(dirname "$src")/.." 2>/dev/null && pwd)"
home="${AGENTKIT_HOME:-$here}"
bin="$home/bin/agentkit"

[ -d "$state" ] || exit 0
[ -x "$bin" ] || exit 0

# Report the result of the previous background update once.
if [ -s "$status" ]; then
  head -n 1 "$status"
  rm -f "$status"
fi

now="$(date +%s)"
last=0
[ -r "$stamp" ] && read -r last < "$stamp"
case "$last" in '' | *[!0-9]*) last=0 ;; esac
case "$interval" in '' | *[!0-9]*) interval=86400 ;; esac
[ $((now - last)) -lt "$interval" ] && exit 0

# Keep update.log small: over 256 KB, keep the last 100 KB.
log="$state/update.log"
if [ -f "$log" ] && [ "$(wc -c < "$log")" -gt 262144 ]; then
  tail -c 102400 "$log" > "$log.tmp" 2> /dev/null && mv "$log.tmp" "$log"
fi

echo "$now" > "$stamp" 2>/dev/null || exit 0
AGENTKIT_HOME="$home" nohup "$bin" update --quiet >> "$state/update.log" 2>&1 < /dev/null &
exit 0
