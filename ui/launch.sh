#!/bin/sh
# Opens the page: starts it in the background if it is not already running,
# waits until it answers, then opens it in your browser. Job Search on the
# Desktop runs this (install.sh makes it), and it works from a terminal too:
#
#     sh ui/launch.sh                  # start the page if need be, then open it
#     sh ui/launch.sh --restart PORT   # the page's Restart button: wait for the
#                                      # page on PORT to stop, then start it again
#
# The page runs with no Terminal window, and stops itself ten minutes after its
# last tab closes (server.py --idle-exit), so nothing is left running all day.
# What it prints goes to ~/Library/Logs/BS Job Search.log. When it cannot
# start, this exits 1 and says why on stderr, which Job Search shows in a
# dialog. It takes the first free port from 8765 up, so a port another program
# holds is passed over, and a page that is already up is opened rather than
# started twice.
#
# start.command is the other way in: the page in a Terminal window, stopped
# with Ctrl-C.

cd "$(dirname "$0")/.." || exit 1
ROOT=$(pwd -P)
LOG="$HOME/Library/Logs/BS Job Search.log"
IDLE_MINUTES=10
FIRST_PORT=8765
LAST_PORT=8774

# Opened from Finder, PATH is only /usr/bin:/bin:/usr/sbin:/sbin. path_helper
# adds what /etc/paths.d names (MacTeX's /Library/TeX/texbin among them), then
# the places uv and Claude Code install themselves.
if [ -x /usr/libexec/path_helper ]; then
  eval "$(/usr/libexec/path_helper -s)"
fi
PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
export PATH
# Finder sets no locale either. The page, git and tlmgr all expect UTF-8.
[ -n "${LANG:-}" ] || LANG=en_US.UTF-8
export LANG

fail() {
  printf '%s\n' "$*" >&2
  exit 1
}

notify() {
  osascript -e "display notification \"$1\" with title \"Job Search\"" >/dev/null 2>&1 || :
}

mkdir -p "$(dirname "$LOG")" 2>/dev/null
# Keep the log from growing forever: past 1 MB, keep its last 200 KB.
if [ -f "$LOG" ] && [ "$(wc -c <"$LOG")" -gt 1000000 ]; then
  tail -c 200000 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

UV=
for c in "$(command -v uv 2>/dev/null)" "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" \
         /opt/homebrew/bin/uv /usr/local/bin/uv; do
  if [ -n "$c" ] && [ -x "$c" ]; then UV=$c; break; fi
done
[ -n "$UV" ] || fail "Job Search needs uv, which is not installed. Open Terminal and run:

sh \"$ROOT/install.sh\"

It installs what is missing."

# What answers on a port: this folder's page ("this"), something else
# ("busy"), or nothing ("free").
probe() {
  body=$(curl -s -m 3 "http://127.0.0.1:$1/api/health" 2>/dev/null)
  [ $? -eq 7 ] && { echo free; return; }
  case $body in
    *'"app":"BS Job Search"'*) ;;
    *) echo busy; return ;;
  esac
  root=$(printf '%s' "$body" | sed -n 's/.*"root":"\([^"]*\)".*/\1/p')
  if [ -n "$root" ] && [ "$root" -ef "$ROOT" ]; then echo this; else echo busy; fi
}

open_page() {
  open "http://127.0.0.1:$1/" 2>/dev/null ||
    fail "The page is running, but no browser opened. Open http://127.0.0.1:$1/ in yours."
}

# Start the page on port $1, in the background, and wait until it answers.
# Returns 0 once it does, or 2 when the port turns out to be another
# program's; anything else ends here with what the page printed.
start_on() {
  port=$1
  size=$(wc -c <"$LOG" 2>/dev/null || echo 0)
  date "+--- %Y-%m-%d %H:%M:%S starting on port $port" >>"$LOG"
  BS_LAUNCHER="$ROOT/ui/launch.sh" nohup "$UV" run ui/server.py --no-open --port "$port" \
    --idle-exit "$IDLE_MINUTES" >>"$LOG" 2>&1 </dev/null &
  pid=$!
  waited=0
  while :; do
    [ "$(probe "$port")" = this ] && return 0
    if ! kill -0 "$pid" 2>/dev/null; then
      printed=$(tail -c +"$((size + 1))" "$LOG")
      case $printed in
        *"already running"*) return 0 ;;   # started by another launch meanwhile
        *"is taken"*) return 2 ;;
      esac
      fail "The page did not start. The last of what it printed:

$(printf '%s\n' "$printed" | tail -n 12)

All of it is in $LOG"
    fi
    sleep 0.5
    waited=$((waited + 1))
    if [ "$waited" -eq 8 ]; then
      notify "Getting the page ready. The first start after an update installs what it added, which can take a minute or two."
    fi
    if [ "$waited" -ge 1200 ]; then
      fail "The page has not answered after ten minutes. What it printed is in $LOG"
    fi
  done
}

if [ "${1:-}" = --restart ]; then
  # The page started this, and nobody sees its stderr: keep it in the log.
  exec 2>>"$LOG"
  port=${2:-$FIRST_PORT}
  i=0
  while [ "$(probe "$port")" != free ] && [ "$i" -lt 60 ]; do
    sleep 0.5
    i=$((i + 1))
  done
  [ "$(probe "$port")" = free ] || fail "The page on port $port did not stop, so it was not started again."
  start_on "$port" || fail "Port $port was taken while the page restarted. Open Job Search again."
  exit 0
fi

port=$FIRST_PORT
while [ "$port" -le "$LAST_PORT" ]; do
  case $(probe "$port") in
    this)
      open_page "$port"
      exit 0
      ;;
    free)
      if start_on "$port"; then
        open_page "$port"
        exit 0
      fi
      ;;
  esac
  port=$((port + 1))
done
fail "Ports $FIRST_PORT to $LAST_PORT are all taken by other programs, so the page has nowhere to run. Quit one of them, then open Job Search again."
