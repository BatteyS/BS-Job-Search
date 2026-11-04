"""install.sh, the one-step Mac setup, run against stand-ins.

Each test gives the installer a home folder of its own and a folder of fake
programs ahead of the real ones on PATH: Apple's (sw_vers, xcode-select,
osacompile, plutil, codesign), uv and Claude Code and their installers (curl
hands out a script that puts the fake in ~/.local/bin), and a git that works
only once the fake Command Line Tools are in. The template is a local git
repository. So the installer's own decisions run for real, on any system,
offline, and every outside call it makes is written to a log the tests read.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest

from helpers import ROOT

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="install.sh is for macOS")

APP = "Job Search.app"
APP_ID = "io.github.batteys.bs-job-search"

STUBS = {
    "uname": """case "$1" in -s) echo "${STUB_UNAME:-Darwin}" ;; -m) echo "${STUB_ARCH:-arm64}" ;; *) echo Darwin ;; esac""",
    "sw_vers": """echo "${STUB_MACOS:-14.5}\"""",
    "sysctl": "echo 0",
    "pgrep": "exit 1",
    "id": """if [ "$1" = -u ] && [ -n "${STUB_ROOT:-}" ]; then echo 0; else exec /usr/bin/id "$@"; fi""",
    "xcode-select": """case "$1" in
  -p) if [ -f "$STUB_STATE/clt" ]; then echo "$STUB_STATE/dev"; else exit 2; fi ;;
  --install) echo "xcode-select --install" >>"$STUB_STATE/calls"; touch "$STUB_STATE/clt" ;;
esac""",
    "git": """[ -f "$STUB_STATE/clt" ] || { echo "xcrun: error: no developer tools" >&2; exit 1; }
exec "$REAL_GIT" "$@\"""",
    "curl": """echo "curl $*" >>"$STUB_STATE/calls"
for a in "$@"; do url=$a; done
case $url in
  https://github.com) exit 0 ;;
  https://astral.sh/uv/install.sh) echo 'mkdir -p "$HOME/.local/bin" && cp "$STUB_STATE/uv" "$HOME/.local/bin/uv"' ;;
  https://claude.ai/install.sh) echo 'mkdir -p "$HOME/.local/bin" && cp "$STUB_STATE/claude" "$HOME/.local/bin/claude"' ;;
  *) exit 22 ;;
esac""",
    "osacompile": """mkdir -p "$2/Contents/Resources/Scripts" "$2/Contents/MacOS" &&
cp "$3" "$2/Contents/Resources/Scripts/main.applescript" && : >"$2/Contents/Info.plist\"""",
    "plutil": """case "$1" in
  -replace) echo "$2=$4" >>"$5" ;;
  -extract) sed -n "s/^$2=//p" "$6" 2>/dev/null ;;
esac""",
    "codesign": "exit 0",
}

# Installed by the fake installers above, into ~/.local/bin.
UV = """echo "uv $*" >>"$STUB_STATE/calls"
case "$1" in
  --version) echo "uv 0.13.6" ;;
  sync) mkdir -p .venv ;;
  run) shift; [ "$1" = --no-sync ] && shift; [ "$1" = python ] && shift; exec "$STUB_PYTHON" "$@" ;;
esac"""
CLAUDE = """echo "claude $*" >>"$STUB_STATE/calls"
case "$*" in
  --version) echo "2.1.317 (Claude Code)" ;;
  "auth status --json") if [ -f "$STUB_STATE/signed-in" ]; then echo '{"loggedIn": true}'; else echo '{"loggedIn": false}'; fi ;;
esac"""


def script(path, body):
    with open(path, "w") as fh:
        fh.write("#!/bin/sh\n" + body + "\n")
    os.chmod(path, 0o755)


def commit(repo, message):
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm",
                    message], cwd=repo, check=True)


@pytest.fixture
def mac(tmp_path):
    """A Mac with nothing installed, and a template to clone."""
    home, stubs, state, template = (tmp_path / d for d in ("home", "stubs", "state", "template"))
    for d in (home, stubs, state):
        d.mkdir()
    for name, body in STUBS.items():
        script(stubs / name, body)
    script(state / "uv", UV)
    script(state / "claude", CLAUDE)

    # The template: enough of a copy for the installer to know one.
    for rel in ("ui/server.py", "scripts/doctor.py", "scripts/install_latex.py"):
        (template / rel).parent.mkdir(parents=True, exist_ok=True)
        (template / rel).write_text("")
    subprocess.run(["git", "init", "-q", "-b", "main", str(template)], check=True)
    commit(template, "before the launcher")
    (template / "ui/launch.sh").write_text("#!/bin/sh\n")
    shutil.copy(os.path.join(ROOT, "install.sh"), template / "install.sh")
    commit(template, "the launcher")

    env = {"HOME": str(home), "PATH": f"{stubs}:/usr/bin:/bin:/usr/sbin:/sbin",
           "TMPDIR": str(tmp_path), "STUB_STATE": str(state), "STUB_PYTHON": sys.executable,
           "REAL_GIT": shutil.which("git"), "BS_TEMPLATE_URL": str(template), "LANG": "C",
           # Only the fakes: never this machine's own uv or Claude Code.
           "BS_TOOL_DIRS": f"{home}/.local/bin"}

    class Mac:
        pass
    m = Mac()
    m.home, m.state, m.template, m.env, m.tmp = home, state, template, env, tmp_path

    def run(*args, how="bash -c", extra=None):
        """The installer as the README's one line runs it (bash -c), piped (sh
        -s, stdin the script), or from inside a copy (sh install.sh)."""
        e = {**env, **(extra or {})}
        text = open(os.path.join(ROOT, "install.sh")).read()
        if how == "bash -c":
            argv, stdin = ["bash", "-c", text, "bash", *args], subprocess.DEVNULL
        elif how == "sh -s":
            argv, stdin = ["sh", "-s", "--", *args], None
        else:
            argv, stdin = ["sh", how, *args], subprocess.DEVNULL
        (state / "calls").write_text("")
        r = subprocess.run(argv, env=e, cwd=str(tmp_path), capture_output=True, text=True,
                           input=text if stdin is None else None,
                           stdin=stdin if stdin is not None else None, timeout=120)
        r.calls = (state / "calls").read_text().splitlines()
        r.all = r.stdout + r.stderr
        return r
    m.run = run
    return m


def test_a_fresh_mac_gets_everything_and_the_desktop_app(mac):
    r = mac.run("--no-latex", "--no-open")
    assert r.returncode == 0, r.all
    calls = "\n".join(r.calls)
    assert "xcode-select --install" in calls                 # git, through Apple's tools
    assert "astral.sh/uv/install.sh" in calls and "claude.ai/install.sh" in calls
    assert "uv python install 3.12" in calls                 # fetched while git downloads
    assert "uv sync --inexact" in calls                      # extras installed earlier stay
    assert "claude auth login" not in calls                  # no terminal to sign in from
    assert "Sign in later" in r.stdout

    copy = mac.home / "job-search"
    assert (copy / "ui" / "launch.sh").is_file() and (copy / ".venv").is_dir()
    app = mac.home / "Desktop" / APP
    opener = (app / "Contents/Resources/open.sh").read_text()
    assert f"FOLDER='{copy}'" in opener
    assert f"CFBundleIdentifier={APP_ID}" in (app / "Contents/Info.plist").read_text()
    applescript = (app / "Contents/Resources/Scripts/main.applescript").read_text()
    assert "open.sh" in applescript and str(copy) not in applescript   # the path lives in open.sh


def test_running_it_again_installs_nothing_and_remakes_the_app(mac):
    assert mac.run("--no-latex", "--no-open").returncode == 0
    (mac.state / "signed-in").touch()
    stale = mac.home / "Desktop" / APP / "Contents/Resources/stale"
    stale.write_text("")
    r = mac.run("--no-latex", "--no-open")
    assert r.returncode == 0, r.all
    calls = "\n".join(r.calls)
    assert "xcode-select --install" not in calls and "install.sh" not in calls
    assert "signed in" in r.stdout
    assert not stale.exists()                                # made anew


def test_piped_and_from_inside_a_copy(mac):
    r = mac.run("--no-latex", "--no-open", how="sh -s")
    assert r.returncode == 0, r.all
    copy = mac.home / "job-search"
    # From inside a copy, that copy is the one, wherever it is.
    moved = mac.tmp / "elsewhere" / "my search"
    moved.parent.mkdir()
    shutil.move(str(copy), str(moved))
    r = mac.run("--no-latex", "--no-open", how=str(moved / "install.sh"))
    assert r.returncode == 0, r.all
    assert not copy.exists()
    opener = (mac.home / "Desktop" / APP / "Contents/Resources/open.sh").read_text()
    assert f"FOLDER='{moved}'" in opener


def test_a_copy_from_before_the_launcher_is_brought_up_to_date(mac):
    copy = mac.home / "job-search"
    (mac.state / "clt").touch()
    subprocess.run(["git", "clone", "-q", str(mac.template), str(copy)], check=True)
    subprocess.run(["git", "reset", "-q", "--hard", "HEAD~1"], cwd=copy, check=True)
    assert not (copy / "ui/launch.sh").exists()
    r = mac.run("--no-latex", "--no-open")
    assert r.returncode == 0, r.all
    assert (copy / "ui/launch.sh").is_file()
    assert "brought in the template's last 1 update(s)" in r.stdout


def test_a_copy_with_work_in_it_is_never_updated_by_force(mac):
    copy = mac.home / "job-search"
    (mac.state / "clt").touch()
    subprocess.run(["git", "clone", "-q", str(mac.template), str(copy)], check=True)
    subprocess.run(["git", "reset", "-q", "--hard", "HEAD~1"], cwd=copy, check=True)
    (copy / "ui/server.py").write_text("# my change\n")
    r = mac.run("--no-latex", "--no-open")
    assert r.returncode == 1
    assert "Update" in r.stderr and (copy / "ui/server.py").read_text() == "# my change\n"


def test_someone_elses_job_search_app_is_left_alone(mac):
    theirs = mac.home / "Desktop" / APP
    theirs.mkdir(parents=True)
    (theirs / "mine.txt").write_text("keep")
    r = mac.run("--no-latex", "--no-open")
    assert r.returncode == 0, r.all
    assert (theirs / "mine.txt").read_text() == "keep"
    assert (mac.home / "Applications" / APP / "Contents/Resources/open.sh").is_file()
    assert "Applications folder" in r.stdout


@pytest.mark.parametrize("extra, says", [
    ({"STUB_MACOS": "12.7.4"}, "needs macOS 13"),
    ({"STUB_ROOT": "1"}, "without sudo"),
    ({"STUB_UNAME": "Linux"}, "for macOS"),
])
def test_it_stops_early_where_it_cannot_work(mac, extra, says):
    r = mac.run("--no-latex", "--no-open", extra=extra)
    assert r.returncode == 1 and says in r.stderr
    assert not (mac.home / "job-search").exists()


def test_a_folder_in_the_way_is_not_touched(mac):
    taken = mac.home / "job-search"
    taken.mkdir()
    (taken / "notes.txt").write_text("mine")
    r = mac.run("--no-latex", "--no-open")
    assert r.returncode == 1 and "is not a copy of BS Job Search" in r.stderr
    assert os.listdir(taken) == ["notes.txt"]
