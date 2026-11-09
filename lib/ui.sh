# agentkit UI helpers. Source this file; it has no side effects until ui_init.
# bash 3.2 compatible. Respects NO_COLOR and QUIET=1 (only errors print).
# shellcheck shell=bash

UI_FANCY=0 UI_UTF8=0 UI_SUMMARY="" UI_SPIN_PID=""
UI_TAB="$(printf '\t')"
UI_NL="$(printf '\nx')"
UI_NL="${UI_NL%x}"

ui__quiet() { [ "${QUIET:-0}" = 1 ]; }

ui_init() {
  UI_FANCY=0
  if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && ! ui__quiet; then UI_FANCY=1; fi
  UI_UTF8=0
  case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
    *[Uu][Tt][Ff]-8* | *[Uu][Tt][Ff]8*) UI_UTF8=1 ;;
  esac
  return 0
}

# ui__c CODE TEXT: colorize in fancy mode only.
ui__c() {
  if [ "${UI_FANCY:-0}" = 1 ]; then printf '\033[%sm%s\033[0m' "$1" "$2"; else printf '%s' "$2"; fi
}

ui_logo() { # name version
  ui__quiet && return 0
  if [ "${UI_FANCY:-0}" = 1 ]; then
    printf '%s\n' "$(ui__c 36 '  /\_/\')"
    printf '%s %s %s\n' "$(ui__c 36 ' ( o.o )')" "$(ui__c 1 "${1:-}")" "$(ui__c 2 "${2:-}")"
    printf '%s\n\n' "$(ui__c 36 '  > ^ <')"
  else
    printf '%s %s\n' "${1:-}" "${2:-}"
  fi
}

ui_step() { # n total title
  ui__quiet && return 0
  printf '%s %s\n' "$(ui__c 1 "[${1:-?}/${2:-?}]")" "${3:-}"
}

ui_item() { # installed|unchanged|skipped|error text
  local kind="${1:-}" text="${2:-}" sym col u="${UI_UTF8:-0}"
  case "$kind" in
    installed) col=32 sym='+'; [ "$u" = 1 ] && sym='✓' ;;
    unchanged) col=2 sym='='; [ "$u" = 1 ] && sym='•' ;;
    skipped) col=33 sym='!' ;;
    error) col=31 sym='x'; [ "$u" = 1 ] && sym='✗' ;;
    *) col=0 sym='-' ;;
  esac
  if [ "$kind" = error ]; then
    printf '  %s %s\n' "$(ui__c "$col" "$sym")" "$text" >&2
  else
    ui__quiet || printf '  %s %s\n' "$(ui__c "$col" "$sym")" "$text"
  fi
  return 0
}

ui_git_progress_flag() { if [ -t 2 ] && ! ui__quiet; then printf '%s\n' --progress; else printf '%s\n' -q; fi; }
ui_curl_progress_flag() { if [ -t 2 ] && ! ui__quiet; then printf '%s\n' -#; else printf '%s\n' -sS; fi; }

# ui__spin_stop: kill our own background job (never anything else), restore cursor.
ui__spin_stop() {
  if [ -n "$UI_SPIN_PID" ]; then
    kill "$UI_SPIN_PID" 2>/dev/null
    wait "$UI_SPIN_PID" 2>/dev/null
    UI_SPIN_PID=""
  fi
  if [ "${UI_FANCY:-0}" = 1 ]; then printf '\r\033[K\033[?25h'; fi
  return 0
}

ui__spin_sig() { # signal-number
  ui__spin_stop
  trap - INT TERM EXIT
  exit "$1"
}

ui_spin() { # label logfile cmd...
  local label="$1" log="$2" rc i=0 n fr
  shift 2
  [ "$#" -gt 0 ] || { printf 'ui_spin: no command\n' >&2; return 2; }
  : >> "$log" 2>/dev/null || { printf 'ui_spin: cannot write %s\n' "$log" >&2; return 2; }
  if [ "${UI_FANCY:-0}" = 1 ]; then
    if [ "${UI_UTF8:-0}" = 1 ]; then fr=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏); n=10; else fr=('|' '/' '-' '\'); n=4; fi
    printf '\033[?25l'
  else
    ui__quiet || printf '  %s ...\n' "$label"
  fi
  trap 'ui__spin_sig 130' INT
  trap 'ui__spin_sig 143' TERM
  trap 'ui__spin_stop' EXIT
  "$@" < /dev/null >> "$log" 2>&1 &
  UI_SPIN_PID=$!
  if [ "${UI_FANCY:-0}" = 1 ]; then
    while kill -0 "$UI_SPIN_PID" 2>/dev/null; do
      printf '\r  %s %s' "$(ui__c 36 "${fr[i % n]}")" "$label"
      i=$((i + 1))
      sleep 0.1
    done
  fi
  wait "$UI_SPIN_PID"
  rc=$?
  UI_SPIN_PID=""
  trap - INT TERM EXIT
  if [ "${UI_FANCY:-0}" = 1 ]; then printf '\r\033[K\033[?25h'; fi
  if [ "$rc" -ne 0 ]; then
    printf '  failed: %s (exit %s), log: %s\n' "$label" "$rc" "$log" >&2
  fi
  return "$rc"
}

ui_summary_add() { # target item status
  UI_SUMMARY="${UI_SUMMARY}${1:--}${UI_TAB}${2:--}${UI_TAB}${3:--}${UI_NL}"
}

ui_summary_print() {
  ui__quiet && return 0
  [ -n "$UI_SUMMARY" ] || return 0
  local t i s w1=6 w2=4
  while IFS="$UI_TAB" read -r t i s; do
    [ "${#t}" -gt "$w1" ] && w1=${#t}
    [ "${#i}" -gt "$w2" ] && w2=${#i}
  done <<EOT
${UI_SUMMARY%"$UI_NL"}
EOT
  printf '\n%s\n' "$(ui__c 1 "$(printf '%-*s  %-*s  %s' "$w1" TARGET "$w2" ITEM STATUS)")"
  while IFS="$UI_TAB" read -r t i s; do
    printf '%-*s  %-*s  %s\n' "$w1" "$t" "$w2" "$i" "$s"
  done <<EOT
${UI_SUMMARY%"$UI_NL"}
EOT
  return 0
}
