#!/bin/sh
# BS Job Search, set up on a Mac in one step. When it finishes, Job Search is
# on your Desktop: double-click it to open the page, which walks you through
# the rest.
#
# Paste this line into Terminal (Applications > Utilities) and press Return:
#
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/BatteyS/BS-Job-Search/main/install.sh)"
#
# In a copy you already have, run it from that folder instead: sh install.sh
#
# It installs only what is missing, all of it into your own home folder, and
# asks for no password itself. Apple's Command Line Tools come through a window
# of Apple's, which on some Macs asks for an administrator. In order:
#
#   1. Apple's Command Line Tools, which bring git. macOS asks you to click
#      Install, and the steps that do not need git go on while they download.
#   2. uv, which runs the Python this workflow is pinned to.
#   3. Claude Code, and its sign-in, in your browser. It needs any paid Claude
#      plan, including one from your employer, or an Anthropic Console account.
#   4. Your copy of the template, in ~/job-search, and its Python packages.
#   5. LaTeX, which typesets resumes: TinyTeX, in your own Library folder.
#   6. Job Search on your Desktop, which starts the page and opens it.
#   7. If you want it, Job Search on your phone too: an icon on its home screen
#      that opens the page from anywhere (ui/phone.py, with Tailscale).
#
# Run it again whenever you like: what is done is skipped, and Job Search on
# the Desktop is made again, which is how to bring it back or point it at a
# copy you moved. Everything it runs prints into
# ~/Library/Logs/BS Job Search install.log.
#
# Options:
#   --dir FOLDER   where the copy goes (default ~/job-search). Run from
#                  inside a copy, that copy is used.
#   --no-latex     leave LaTeX for later; the page's Setup tab installs it
#   --no-open      do not open the page at the end
#   --phone        set up Job Search on your phone, without asking first
#
# Only macOS for now. On Windows or Linux, follow Get started in README.md.

TEMPLATE_URL=${BS_TEMPLATE_URL:-https://github.com/BatteyS/BS-Job-Search.git}
README_URL=https://github.com/BatteyS/BS-Job-Search#get-started
MIN_MACOS=13   # Claude Code's own floor: code.claude.com/docs/en/setup
APP_NAME="Job Search"
APP_ID=io.github.batteys.bs-job-search
LOG="$HOME/Library/Logs/BS Job Search install.log"
# Where uv and Claude Code may be when PATH does not say, as in a Terminal
# opened before they were installed: their installers' own folder, and
# Homebrew's on Apple silicon and on Intel. Separated like PATH; the tests
# name their own.
TOOL_DIRS=${BS_TOOL_DIRS:-$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin}

if [ -t 1 ]; then BOLD=$(printf '\033[1m'); DIM=$(printf '\033[2m'); PLAIN=$(printf '\033[0m')
else BOLD= DIM= PLAIN=; fi

step() { printf '\n%s%s%s\n' "$BOLD" "$*" "$PLAIN"; }
ok()   { printf '  %sok%s    %s\n' "$BOLD" "$PLAIN" "$*"; }
note() { printf '        %s\n' "$*"; }
quiet() { "$@" >>"$LOG" 2>&1; }
# $1 in single quotes, for a command to paste: each ' written '\''.
shq() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }

die() {
  printf '\n%sStopped.%s %s\n' "$BOLD" "$PLAIN" "$*" >&2
  if [ -s "$LOG" ]; then
    printf '\n%sEverything this run printed is in %s.%s\n' "$DIM" "$LOG" "$PLAIN" >&2
  fi
  printf 'Once it is fixed, run the same command again: it picks up where it stopped.\n' >&2
  exit 1
}

show_log_tail() {
  printf '%s' "$DIM"
  tail -n "${1:-12}" "$LOG" | sed 's/^/        /'
  printf '%s' "$PLAIN"
}

# A terminal to ask questions in. Piped in from curl, stdin is the script
# itself, so questions go to /dev/tty, and without one there are none.
TTY=
if (exec </dev/tty) 2>/dev/null; then TTY=/dev/tty; fi

wait_for_return() {
  [ -n "$TTY" ] || return 1
  printf '%s ' "$1"
  read -r _ <"$TTY"
}

# ----------------------------------------------------------------- checks

preflight() {
  [ "$(uname -s)" = Darwin ] || die "This installer is for macOS. On Windows or Linux, follow Get started in README.md: $README_URL"
  [ "$(id -u)" != 0 ] || die "Run it as yourself, without sudo. Everything goes into your own home folder, and what sudo puts there belongs to root, which breaks updates later."

  # This run's log, begun only now that it is surely the user's own.
  mkdir -p "$(dirname "$LOG")" 2>/dev/null
  : >"$LOG" 2>/dev/null || LOG=/dev/null

  version=$(sw_vers -productVersion 2>/dev/null)
  major=${version%%.*}
  case $major in ''|*[!0-9]*) major=0 ;; esac
  [ "$major" -ge "$MIN_MACOS" ] || die "This Mac has macOS ${version:-of an unknown version}. Claude Code, which does the interviewing and writing, needs macOS $MIN_MACOS (Ventura) or newer. If this Mac can take a newer macOS, it is in System Settings > General > Software Update."

  chip=Intel
  [ "$(uname -m)" = arm64 ] && chip="Apple silicon"
  if [ "$(sysctl -n sysctl.proc_translated 2>/dev/null)" = 1 ]; then
    chip="Apple silicon, with Terminal running under Rosetta"
  fi
  ok "macOS $version, $chip"
  case $chip in *Rosetta*)
    note "That works, but more slowly. To run Terminal natively: quit it, select it in Finder"
    note "(Applications > Utilities), choose File > Get Info, and untick Open using Rosetta." ;;
  esac

  date "+--- install.sh, %Y-%m-%d %H:%M:%S, macOS $version, $(uname -m)" >>"$LOG"

  # uv and Claude Code install into ~/.local/bin. A ~/.local made with sudo
  # belongs to root, and both installers then fail.
  for d in "$HOME/.local" "$HOME/.local/bin" "$HOME/.local/share"; do
    if [ -e "$d" ] && [ ! -w "$d" ]; then
      me=$(id -un)
      die "$d belongs to another user (usually root, from an earlier sudo), so nothing can install into it. Give it back to yourself with this command, then run this again:

    sudo chown -R $me $(shq "$HOME/.local")

It needs an administrator of this Mac. If that is you, it asks for your Mac password. If not, an administrator can run it from their own account, or in this Terminal window after su followed by their account name (which asks for their password)."
    fi
  done

  free_kb=$(df -Pk "$HOME" 2>/dev/null | awk 'NR == 2 { print $4 }')
  case $free_kb in ''|*[!0-9]*) free_kb= ;; esac
  if [ -n "$free_kb" ] && [ "$free_kb" -lt 3000000 ]; then
    note "Only $((free_kb / 1024 / 1024)) GB free on this disk. Everything here takes about 1.5 GB,"
    note "and Apple's Command Line Tools, if they are missing, several more."
  fi

  if ! curl -fsSI -m 20 https://github.com >/dev/null 2>&1; then
    note "github.com is not answering, so anything still to download will fail until it does."
    note "On a company network, a proxy may be in the way."
  fi
}

# ------------------------------------------------------------- git (Xcode)

# A git that runs. Without Apple's Command Line Tools, /usr/bin/git is only a
# stub that opens Apple's install window, so ask xcode-select where the tools
# are before running it.
git_ok() {
  g=$(command -v git 2>/dev/null) || return 1
  if [ "$g" = /usr/bin/git ]; then
    dev=$(xcode-select -p 2>/dev/null) || return 1
    [ -x "$dev/usr/bin/git" ] || return 1
  fi
  "$g" --version >/dev/null 2>&1
}

clt_window_open() {
  pgrep -f "Install Command Line Developer Tools" >/dev/null 2>&1
}

# Ask Apple for the Command Line Tools, which opens its install window, or
# stop with why it did not. One reason is tools that are in, but where macOS
# does not look for them, which only an administrator can reset.
open_clt_window() {
  said=$(xcode-select --install 2>&1)
  rc=$?
  printf '%s\n' "$said" >>"$LOG"
  [ "$rc" -eq 0 ] && return 0
  clt_window_open && return 0   # open already, from an earlier run
  case $said in
    *"already installed"*)
      die "Apple's Command Line Tools are on this Mac, but macOS looks for them in the wrong place ($(xcode-select -p 2>/dev/null || echo 'none is set')), so git cannot run. This command points it at them:

    sudo xcode-select --reset

It needs an administrator of this Mac: if you are not one, ask whoever is to run it. Then run this again." ;;
  esac
  die "Apple's installer for the Command Line Tools did not start. It said: ${said:-nothing}"
}

start_git() {
  step "1. git"
  WAIT_FOR_GIT=
  if git_ok; then
    ok "$(git --version)"
    return
  fi
  # Xcode itself, its license not yet accepted: git refuses until it is.
  # Asked only where Xcode is what xcode-select names, since without any
  # tools, running git is what opens Apple's window.
  case $(xcode-select -p 2>/dev/null) in
    *.app/*)
      if git --version 2>&1 | grep -qi license; then
        die "Xcode is installed but its license has not been accepted, so git will not run. Accept it with this, then run this again:

    sudo xcodebuild -license accept

It needs an administrator of this Mac: if you are not one, ask whoever is to run it."
      fi ;;
  esac
  open_clt_window
  WAIT_FOR_GIT=1
  note "Apple's Command Line Tools bring git, which keeps your copy up to date."
  note "${BOLD}A window from Apple has opened: click Install, then Agree.${PLAIN}"
  note "They take 5 to 20 minutes to download, and the next steps go on meanwhile."
}

wait_for_git() {
  [ -n "$WAIT_FOR_GIT" ] || return 0
  step "Waiting for Apple's Command Line Tools"
  note "Still downloading in Apple's window. This goes on by itself once they are in."
  waited=0
  until git_ok; do
    sleep 5
    waited=$((waited + 5))
    # Give the window a minute to appear before asking whether it is gone.
    if [ "$waited" -ge 60 ] && [ $((waited % 30)) -eq 0 ] && ! clt_window_open && ! git_ok; then
      if wait_for_return "Apple's window has closed, and git is not in yet. Press Return to open it again, or Ctrl-C to stop:"; then
        open_clt_window
      else
        die "Apple's install window closed before git was in. Run this again to reopen it."
      fi
    fi
    [ "$waited" -lt 5400 ] || die "The Command Line Tools have not arrived after 90 minutes. If Apple's window shows an error, they can also be downloaded from developer.apple.com/download/all (search Command Line Tools; it needs an Apple ID, and installing what it downloads needs an administrator of this Mac: if you are not one, ask whoever is). Then run this again."
  done
  ok "$(git --version)"
}

# --------------------------------------------------------------------- uv

# The first program called $1 on PATH, else in TOOL_DIRS.
find_tool() {
  found=$(command -v "$1" 2>/dev/null)
  if [ -n "$found" ] && [ -x "$found" ]; then echo "$found"; return 0; fi
  rest=$TOOL_DIRS
  while [ -n "$rest" ]; do
    d=${rest%%:*}
    case $rest in *:*) rest=${rest#*:} ;; *) rest= ;; esac
    if [ -n "$d" ] && [ -x "$d/$1" ]; then echo "$d/$1"; return 0; fi
  done
  return 1
}

find_uv() {
  UV=$(find_tool uv)
}

ensure_uv() {
  step "2. uv, which runs Python"
  if find_uv; then
    ok "$("$UV" --version 2>/dev/null) at $UV"
    return
  fi
  note "Installing uv from astral.sh..."
  curl -LsSf https://astral.sh/uv/install.sh 2>>"$LOG" | sh >>"$LOG" 2>&1
  find_uv || { show_log_tail; die "uv did not install: see above."; }
  ok "$("$UV" --version 2>/dev/null) at $UV"
}

# ------------------------------------------------------------ Claude Code

find_claude() {
  CLAUDE=$(find_tool claude) && return 0
  # Where older installers put it.
  for c in "$HOME/.claude/local/claude" "$HOME/.npm-global/bin/claude"; do
    if [ -x "$c" ]; then CLAUDE=$c; return 0; fi
  done
  return 1
}

ensure_claude() {
  step "3. Claude Code"
  if ! find_claude; then
    note "Installing Claude Code from claude.ai. It shows no progress while it downloads,"
    note "which takes a minute or two."
    curl -fsSL https://claude.ai/install.sh 2>>"$LOG" | bash >>"$LOG" 2>&1
    find_claude || { show_log_tail; die "Claude Code did not install: see above. Its own guide is at code.claude.com/docs/en/troubleshoot-install"; }
  fi
  ok "$("$CLAUDE" --version 2>/dev/null | head -n 1) at $CLAUDE"

  if claude_signed_in; then
    ok "signed in"
    return
  fi
  note "Claude Code needs a paid Claude plan (Pro, Max, Team or Enterprise, including one"
  note "from your employer) or an Anthropic Console account; the free plan does not include it."
  note "Signed in to the Claude desktop app already? Claude Code still signs in once, here."
  if [ -z "$TTY" ]; then
    note "Sign in later, in Terminal: \"$CLAUDE\" auth login"
    note "(with an Anthropic Console account: \"$CLAUDE\" auth login --console)"
    return
  fi
  printf '        Sign in with a Claude plan (press Return), or a Console account (type c)? '
  answer=
  read -r answer <"$TTY" || answer=
  case $answer in [Cc]*) how=--console ;; *) how=--claudeai ;; esac
  note "${BOLD}Your browser opens to sign in. Come back here when it says you are done.${PLAIN}"
  note "(Ctrl-C skips signing in for now, and the rest carries on.)"
  # Ctrl-C ends the sign-in alone: the trap keeps this script going.
  trap ':' INT
  "$CLAUDE" auth login "$how" <"$TTY"
  trap - INT
  if claude_signed_in; then
    ok "signed in"
  else
    note "Not signed in yet. Everything else carries on; the page's Setup tab says how to"
    note "sign in later."
  fi
}

# Signed in to an account that can run Claude Code. A claude.ai account on the
# Free plan signs in but cannot, so it is named, with what to do.
claude_signed_in() {
  state=$("$CLAUDE" auth status --json 2>/dev/null)
  printf '%s' "$state" | grep -q '"loggedIn": *true' || return 1
  if printf '%s' "$state" | grep -q '"subscriptionType": *"free"'; then
    note "This Claude account is on the Free plan, which does not include Claude Code."
    note "Upgrade at claude.com/pricing, or sign in with a Console account instead:"
    note "\"$CLAUDE\" auth login --console"
    return 1
  fi
  return 0
}

# ------------------------------------------------------------- your copy

is_copy() {
  [ -f "$1/ui/server.py" ] && [ -f "$1/scripts/doctor.py" ]
}

template_remote() {
  # The remote that is the template: origin for a clone, `template` for a
  # copy backed up to a repository of its own.
  for r in origin template; do
    url=$(git -C "$DIR" remote get-url "$r" 2>/dev/null) || continue
    case $(printf '%s' "$url" | tr 'A-Z' 'a-z') in
      *batteys/bs-job-search*) echo "$r"; return 0 ;;
    esac
  done
  [ -n "${BS_TEMPLATE_URL:-}" ] && [ "$(git -C "$DIR" remote get-url origin 2>/dev/null)" = "$BS_TEMPLATE_URL" ] && { echo origin; return 0; }
  return 1
}

# Bring a plain clone of the template up to date, when the copy needs it to
# run: only a fast-forward, only with nothing uncommitted, and never a copy
# backed up to a repository of its own (the page's Update handles that).
catch_up() {
  remote=$(template_remote) || return 1
  [ "$remote" = origin ] || return 1
  [ -z "$(git -C "$DIR" status --porcelain --untracked-files=no 2>/dev/null)" ] || return 1
  quiet git -C "$DIR" fetch --quiet origin || return 1
  behind=$(git -C "$DIR" rev-list --count 'HEAD..@{upstream}' 2>/dev/null) || return 1
  [ "${behind:-0}" -gt 0 ] || return 1
  quiet git -C "$DIR" merge --ff-only --quiet '@{upstream}' || return 1
  ok "brought in the template's last $behind update(s)"
}

ensure_copy() {
  step "4. Your copy"
  if [ -e "$DIR" ] && ! is_copy "$DIR"; then
    die "$DIR is already there and is not a copy of BS Job Search. Move it, or name another folder: add --dir ~/some-other-folder to the command."
  fi
  if [ ! -e "$DIR" ]; then
    GIT_TERMINAL_PROMPT=0 quiet git clone --quiet "$TEMPLATE_URL" "$DIR" ||
      { show_log_tail; die "Could not download the template from $TEMPLATE_URL: see above."; }
    ok "made $DIR"
  else
    ok "$DIR"
  fi
  case $DIR in
    "$HOME/Documents"/*|"$HOME/Desktop"/*|"$HOME/Library/Mobile Documents"/*)
      note "This folder may be kept in iCloud Drive. iCloud can move its Python packages"
      note "and git files to the cloud to save space, which breaks them. A folder that is"
      note "not synced, such as ~/job-search, is safer." ;;
  esac
  # A copy from before the launcher has no ui/launch.sh: catch it up if it can.
  if [ ! -f "$DIR/ui/launch.sh" ]; then
    catch_up
    [ -f "$DIR/ui/launch.sh" ] || die "$DIR is from before Job Search on the Desktop, and could not be brought up to date by itself. Open the page as before and press Update on its Setup tab, then run this again."
  fi
}

# One `uv sync`, its output kept in $SYNCED as well as the log. --inexact
# keeps extras installed earlier, such as the scraped boards'.
sync_once() {
  (cd "$DIR" && "$UV" sync --inexact) >"$SYNCED" 2>&1
  status=$?
  cat "$SYNCED" >>"$LOG"
  return $status
}

sync_packages() {
  note "Installing Python and the packages (a minute or two the first time)..."
  SYNCED=$(mktemp "${TMPDIR:-/tmp}/job-search-sync.XXXXXX") || SYNCED=/dev/null
  sync_once && return 0
  # A company network that inspects HTTPS: uv's own certificates do not know
  # its proxy, but the Mac's keychain does.
  if grep -qi "certificate" "$SYNCED" && UV_NATIVE_TLS=1 sync_once; then
    mkdir -p "$HOME/.config/uv"
    grep -qs "native-tls" "$HOME/.config/uv/uv.toml" || echo "native-tls = true" >>"$HOME/.config/uv/uv.toml"
    note "This network inspects HTTPS, so uv now uses the Mac's own certificates"
    note "(native-tls = true, in ~/.config/uv/uv.toml)."
    return 0
  fi
  # A uv older than the lockfile's format updates itself, where it can.
  if grep -q "uv.lock" "$SYNCED" && quiet "$UV" self update && sync_once; then
    note "uv was older than this copy's lockfile, so it updated itself."
    return 0
  fi
  # A fix may be waiting in the template.
  catch_up && sync_once
}

ensure_packages() {
  sync_packages || { show_log_tail 15; die "The Python packages did not install: see above."; }
  ok "Python $(cd "$DIR" && "$UV" run --no-sync python -c 'import platform; print(platform.python_version())' 2>/dev/null) and the packages, in $DIR/.venv"
}

# ------------------------------------------------------------------ LaTeX

# Run scripts/$1 in the copy, what it prints going to the log, and say once a
# minute that it is still going: a download can stall, and silence reads as
# stuck. It runs in the foreground, so Ctrl-C stops it, and the ticker stops
# with this script. BS_TICK, in seconds, is for the tests.
run_ticking() {
  (
    parent=$$ secs=0
    while sleep 1; do
      kill -0 "$parent" 2>/dev/null || exit 0
      secs=$((secs + 1))
      [ $((secs % ${BS_TICK:-60})) -eq 0 ] && note "still working ($((secs / 60)) min)..."
    done
  ) &
  ticker=$!
  (cd "$DIR" && "$UV" run --no-sync python "scripts/$1" >>"$LOG" 2>&1)
  ran=$?
  kill "$ticker" 2>/dev/null
  return $ran
}

ensure_latex() {
  step "5. LaTeX, which typesets resumes"
  if [ -n "$NO_LATEX" ]; then
    note "Left for later: the page's Setup tab installs it."
    return
  fi
  found=$(cd "$DIR" && "$UV" run --no-sync python scripts/install_latex.py --check 2>&1)
  status=$?
  printf '%s\n' "$found" >>"$LOG"
  if [ "$status" -eq 0 ]; then
    ok "$(printf '%s\n' "$found" | head -n 1)"
    return
  fi
  note "Installing TinyTeX into ~/Library/TinyTeX: about 64 MB. A few minutes, longer on a"
  note "slow connection: it is still working while a line here says so, once a minute."
  if run_ticking install_latex.py; then
    ok "TinyTeX, with the packages the templates use"
  else
    show_log_tail
    note "LaTeX did not install, which only resumes and letters need. Everything else"
    note "carries on, and the page's Setup tab can try again."
  fi
}

# ------------------------------------------------------------ the Desktop

# Whether $1 is a Job Search this installer (or the earlier hand-made one) made.
ours() {
  [ -d "$1" ] || return 1
  [ "$(plutil -extract CFBundleIdentifier raw -o - "$1/Contents/Info.plist" 2>/dev/null)" = "$APP_ID" ] && return 0
  grep -qs "BS Job Search.log" "$1/Contents/Resources/launch.sh"
}

make_app() {
  dest=$1
  tmp=$(mktemp -d "${TMPDIR:-/tmp}/job-search-app.XXXXXX") || return 1
  app="$tmp/$APP_NAME.app"
  cat >"$tmp/main.applescript" <<'EOF'
-- Job Search, made by install.sh: opens the BS Job Search page, starting it
-- first if it is not running. Contents/Resources/open.sh names the copy.
on run
	set opener to (POSIX path of (path to me)) & "Contents/Resources/open.sh"
	try
		do shell script "/bin/sh " & quoted form of opener
	on error errorText number errorNumber
		if errorNumber is not -128 then
			display dialog errorText buttons {"OK"} default button "OK" with title "Job Search" with icon caution
		end if
	end try
end run
EOF
  quiet osacompile -o "$app" "$tmp/main.applescript" || return 1
  # Job Search's own icon (ui/icon.py) in place of the script icon. The asset
  # catalog holds the old one, and would win over applet.icns.
  if (cd "$DIR" && "$UV" run --no-sync python ui/icon.py --iconset "$tmp/icon.iconset") >>"$LOG" 2>&1 &&
     quiet iconutil -c icns "$tmp/icon.iconset" -o "$app/Contents/Resources/applet.icns"; then
    rm -f "$app/Contents/Resources/Assets.car"
    quiet plutil -remove CFBundleIconName "$app/Contents/Info.plist"
  fi
  # The copy this one opens. A path in single quotes, each ' written '\''.
  quoted=$(printf '%s' "$DIR" | sed "s/'/'\\\\''/g")
  cat >"$app/Contents/Resources/open.sh" <<EOF
#!/bin/sh
# Job Search, made by install.sh for the copy below. Run install.sh in that
# copy again to make it anew, or to point it at a copy you moved.
FOLDER='$quoted'
if [ ! -d "\$FOLDER" ]; then
  echo "Job Search cannot find its folder, \$FOLDER. If you moved or renamed it, open Terminal in its new place and run: sh install.sh. That puts a new Job Search on the Desktop." >&2
  exit 1
fi
if [ ! -f "\$FOLDER/ui/launch.sh" ]; then
  echo "The copy in \$FOLDER has no ui/launch.sh, which Job Search runs: it is from before Job Search on the Desktop, or on a branch without it. Bring it up to date (the Update button on the page's Setup tab), then open Job Search again." >&2
  exit 1
fi
exec /bin/sh "\$FOLDER/ui/launch.sh"
EOF
  quiet plutil -replace CFBundleIdentifier -string "$APP_ID" "$app/Contents/Info.plist" || return 1
  # Editing the bundle broke osacompile's signature. Seal it again, or
  # Apple silicon may refuse to open it.
  quiet codesign --force --sign - "$app" || return 1
  rm -rf "$dest" && mv "$app" "$dest" || return 1
  rm -rf "$tmp"
}

# Make Job Search in folder $1, unless something there by that name is not
# ours, which is never written over.
make_in() {
  APP="$1/$APP_NAME.app"
  if [ -e "$APP" ] && ! ours "$APP"; then
    note "$1 already has something else called $APP_NAME, which stays as it is."
    return 1
  fi
  mkdir -p "$1" 2>/dev/null
  make_app "$APP"
}

ensure_app() {
  step "6. Job Search on your Desktop"
  note "If macOS asks whether Terminal may use your Desktop folder, click Allow."
  if make_in "$HOME/Desktop"; then
    ok "$APP"
  elif make_in "$HOME/Applications"; then
    ok "$APP"
    note "It could not go on the Desktop, so it is in the Applications folder in your home"
    note "folder: drag it to the Desktop or the Dock from there."
  else
    show_log_tail
    die "Could not make $APP_NAME on the Desktop or in ~/Applications: see above."
  fi
}

# ---------------------------------------------------------------- the phone

# `cd` to the copy, as a person would type it, so a command printed here works
# from a new Terminal window: ~/job-search rather than the whole path, when the
# copy is in the home folder under a plain name (ui/phone.py's cd does the same).
cd_copy() {
  case $DIR in
    "$HOME"/*)
      rest=${DIR#"$HOME"/}
      case $rest in ''|*[!A-Za-z0-9._/-]*) ;; *) echo "cd ~/$rest"; return ;; esac ;;
  esac
  echo "cd $(shq "$DIR")"
}

# Job Search on the phone too, when asked (--phone) or when the user says yes:
# ui/phone.py hands the page's port to launchd and points Tailscale at it.
# Once it is set up, each run checks that it still works, from the same
# diagnosis as the page's Setup tab, and says why not and what to do.
ensure_phone() {
  again="$(cd_copy) && sh install.sh --phone"
  if [ -z "$PHONE" ]; then
    if [ -f "$DIR/data/ui-remote.json" ]; then
      step "7. Your phone"
      if said=$(cd "$DIR" && "$UV" run --no-sync python ui/phone.py check 2>>"$LOG"); then
        ok "$said"
      else
        printf '%s\n' "${said:-It could not be checked. To set it up again: $again}" |
          fold -s -w 82 | sed 's/^/        /'
      fi
      return
    fi
    [ -n "$TTY" ] || return 0
    step "7. Your phone (optional)"
    note "Job Search can also be an icon on your phone's home screen, opening this page from"
    note "anywhere. It needs the free Tailscale app, on this Mac and on your phone."
    printf '        Set it up now? [y/N] '
    answer=
    read -r answer <"$TTY" || answer=
    case $answer in
      [Yy]*) ;;
      *) note "Skipped. To set it up later, in Terminal: $again"; return ;;
    esac
  else
    step "7. Your phone"
  fi
  (cd "$DIR" && "$UV" run --no-sync python ui/phone.py enable) ||
    note "Not finished: see above. To try again, in Terminal: $again"
}

# ------------------------------------------------------------------- main

main() {
  NO_LATEX= NO_OPEN= PHONE= DIR=
  while [ $# -gt 0 ]; do
    case $1 in
      --dir) DIR=${2:-}; shift ;;
      --dir=*) DIR=${1#--dir=} ;;
      --no-latex) NO_LATEX=1 ;;
      --no-open) NO_OPEN=1 ;;
      --phone) PHONE=1 ;;
      -h|--help) sed -n '2,39p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'; exit 0 ;;
      *) die "Unknown option: $1 (try --help)" ;;
    esac
    shift
  done

  # Run from inside a copy (sh install.sh), that copy is the one. Piped in
  # from curl, $0 is the shell's own name, not a file.
  if [ -z "$DIR" ] && [ -f "$0" ]; then
    here=$(cd "$(dirname "$0")" 2>/dev/null && pwd -P)
    if [ -n "$here" ] && is_copy "$here"; then DIR=$here; fi
  fi
  DIR=${DIR:-${JOB_SEARCH_DIR:-$HOME/job-search}}
  case $DIR in "~"/*) DIR="$HOME/${DIR#"~/"}" ;; /*) ;; *) DIR="$(pwd -P)/$DIR" ;; esac

  printf '%sBS Job Search: setting up this Mac%s\n' "$BOLD" "$PLAIN"
  preflight
  start_git
  ensure_uv
  ensure_claude
  if [ -n "$WAIT_FOR_GIT" ] && [ ! -e "$DIR" ]; then
    note "Fetching Python while the Command Line Tools download..."
    quiet "$UV" python install 3.12
  fi
  wait_for_git
  ensure_copy
  ensure_packages
  ensure_latex
  ensure_app
  ensure_phone

  step "Done"
  case $APP in
    "$HOME/Desktop"/*) where="on your Desktop" ;;
    *) where="in the Applications folder in your home folder" ;;
  esac
  note "$APP_NAME is $where: double-click it whenever you want the page."
  note "It runs with no window, and stops by itself ten minutes after you close the page's"
  note "last tab. This Terminal window can be closed."
  if [ -z "$NO_OPEN" ]; then
    note "Opening the page in your browser now. Its Setup tab walks you through the rest."
    # Through the app, not from here: a page started from this window would be
    # tied to it, and closing the window could stop the page.
    open "$APP" 2>>"$LOG" || note "It did not open: double-click $APP_NAME, $where."
  fi
}

main "$@"
