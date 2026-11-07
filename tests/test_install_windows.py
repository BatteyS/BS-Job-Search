"""install.ps1, the one-step Windows setup, run against stand-ins.

No Windows is needed: PowerShell 7 (pwsh) runs the installer on macOS or Linux,
and what only Windows has is played by stand-ins. A prelude, loaded first,
takes the place of the registry (each key the installer writes is recorded),
of WScript.Shell (each shortcut is saved as JSON with what it was given), of
the Windows version in the registry, and of the network. winget, uv, Claude
Code and their installers are fake programs that put a fake in place, as
tests/test_install.py does for the Mac. The template is a local git repository.
So the installer's own decisions run for real, offline, and the tests read
what it did.

What this cannot show is Windows itself: that a shortcut made this way opens
start.cmd minimized, that the link opens from a browser, that winget installs
Git for Windows for one user. Those need a real PC. Without pwsh the tests that
run the installer are skipped; CI's Ubuntu has it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

from helpers import ROOT

PWSH = shutil.which("pwsh")
needs_pwsh = pytest.mark.skipif(PWSH is None or sys.platform == "win32",
                                reason="needs pwsh, and the stand-ins are sh scripts")

SCRIPT = os.path.join(ROOT, "install.ps1")
KEY = r"HKCU:\Software\Classes\bs-job-search"
ONE_LINE = ('powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/'
            'BatteyS/BS-Job-Search/main/install.ps1 | iex"')

# Windows, as far as the installer can see it. Each stand-in writes what it
# was asked to $STUB_STATE/calls.
PRELUDE = r"""
function Record([string]$Line) { Add-Content -LiteralPath (Join-Path $env:STUB_STATE 'calls') -Value $Line }

function Get-ItemProperty {
  [CmdletBinding()] param([string]$Path)
  if ($Path -like 'HKLM:*') { return [pscustomobject]@{ CurrentBuild = $env:STUB_BUILD; DisplayVersion = '24H2' } }
  throw "the test's Get-ItemProperty knows only HKLM: $Path"
}

# The registry, as a list of what was done to it.
function Reg([string]$Line) { Add-Content -LiteralPath (Join-Path $env:STUB_STATE 'registry') -Value $Line }
function Test-Path {
  [CmdletBinding()] param([Parameter(Position=0)][string[]]$Path, [string[]]$LiteralPath, [string]$PathType)
  $p = "$Path$LiteralPath"
  if ($p -like 'HKCU:*') {
    $file = Join-Path $env:STUB_STATE 'registry'
    return ((Microsoft.PowerShell.Management\Test-Path -LiteralPath $file) -and
            [bool](Get-Content -LiteralPath $file | Where-Object { $_ -like "new`t$p`t*" }))
  }
  Microsoft.PowerShell.Management\Test-Path @PSBoundParameters
}
function New-Item {
  [CmdletBinding()] param([Parameter(Position=0)][string]$Path, [string]$ItemType, [object]$Value, [switch]$Force)
  if ($Path -like 'HKCU:*') { Reg "new`t$Path`t$Value"; return [pscustomobject]@{ PSPath = $Path } }
  Microsoft.PowerShell.Management\New-Item @PSBoundParameters
}
function New-ItemProperty {
  [CmdletBinding()] param([string]$Path, [string]$Name, [object]$Value, [string]$PropertyType, [switch]$Force)
  Reg "set`t$Path`t$Name`t$Value"
}
function Remove-Item {
  [CmdletBinding()] param([string[]]$LiteralPath, [switch]$Recurse, [switch]$Force)
  if ("$LiteralPath" -like 'HKCU:*') { Reg "remove`t$LiteralPath"; return }
  Microsoft.PowerShell.Management\Remove-Item @PSBoundParameters
}

# WScript.Shell: a shortcut is saved as JSON of what it was given, and read
# back from it; a dialog is recorded.
function New-FakeShortcut([string]$Path) {
  $lnk = [pscustomobject]@{ FullName = $Path; TargetPath = ''; Arguments = ''; WorkingDirectory = '';
                            WindowStyle = 1; Description = ''; IconLocation = '' }
  if (Microsoft.PowerShell.Management\Test-Path -LiteralPath $Path) {
    $saved = Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
    foreach ($p in $saved.PSObject.Properties) { $lnk.($p.Name) = $p.Value }
  }
  $lnk | Add-Member ScriptMethod Save {
    $this | Select-Object TargetPath, Arguments, WorkingDirectory, WindowStyle, Description, IconLocation |
      ConvertTo-Json | Set-Content -LiteralPath $this.FullName
  }
  return $lnk
}
function New-Object {
  [CmdletBinding()] param([Parameter(Position=0)][string]$TypeName, [Parameter(Position=1)][object[]]$ArgumentList,
                          [string]$ComObject)
  if ($ComObject -eq 'WScript.Shell') {
    if ($env:STUB_NO_SHELL) { throw 'no WScript.Shell here' }
    $shell = [pscustomobject]@{}
    $shell | Add-Member ScriptMethod CreateShortcut { param($p) New-FakeShortcut $p }
    $shell | Add-Member ScriptMethod Popup { param($text, $secs, $title, $kind) Record "popup $text"; 1 }
    return $shell
  }
  Microsoft.PowerShell.Utility\New-Object @PSBoundParameters
}

function Invoke-WebRequest { [CmdletBinding()] param([string]$Uri, [string]$Method, [switch]$UseBasicParsing, [int]$TimeoutSec) Record "web $Uri" }

# Opening a shortcut or start.cmd is recorded; running anything else, such as
# the copy's uv, is real.
function Start-Process {
  [CmdletBinding()] param([Parameter(Position=0)][string]$FilePath, [string[]]$ArgumentList, [string]$WorkingDirectory,
                          [string]$WindowStyle, [switch]$NoNewWindow, [switch]$PassThru,
                          [string]$RedirectStandardOutput, [string]$RedirectStandardError)
  if ($FilePath -like '*.lnk' -or $FilePath -like '*start.cmd') {
    Record ("start $FilePath | $($ArgumentList -join ' ') | $WindowStyle | $WorkingDirectory")
    return
  }
  Microsoft.PowerShell.Management\Start-Process @PSBoundParameters
}
"""

# The fake programs. Each runs with a PATH of its own, since the installer's
# PATH holds only the stand-ins.
SH = "#!/bin/sh\nPATH=/usr/bin:/bin; export PATH\n"
STUBS = {
    # Windows' installer: Git for Windows, per user, puts git where it goes.
    "winget": """echo "winget $*" >>"$STUB_STATE/calls"
case "$*" in *"--id Git.Git"*)
  mkdir -p "$LOCALAPPDATA/Programs/Git/cmd" && cp "$STUB_STATE/git" "$LOCALAPPDATA/Programs/Git/cmd/git.exe" ;;
esac""",
}
# The Windows PowerShell that runs uv's and Claude Code's installers.
POWERSHELL = """echo "powershell $*" >>"$STUB_STATE/calls"
case "$*" in
  *astral.sh/uv/install.ps1*) mkdir -p "$USERPROFILE/.local/bin" && cp "$STUB_STATE/uv" "$USERPROFILE/.local/bin/uv.exe" ;;
  *claude.ai/install.ps1*) mkdir -p "$USERPROFILE/.local/bin" && cp "$STUB_STATE/claude" "$USERPROFILE/.local/bin/claude.exe" ;;
esac"""
GIT = 'exec "$REAL_GIT" "$@"'
UV = """echo "uv $*" >>"$STUB_STATE/calls"
case "$1" in
  --version) echo "uv 0.13.7" ;;
  sync) mkdir -p .venv ;;
  run) shift; [ "$1" = --no-sync ] && shift; [ "$1" = python ] && shift; exec "$STUB_PYTHON" "$@" ;;
esac"""
CLAUDE = """echo "claude $*" >>"$STUB_STATE/calls"
case "$*" in
  --version) echo "2.1.317 (Claude Code)" ;;
  "auth status --json")
    if [ -f "$STUB_STATE/free" ]; then echo '{"loggedIn": true, "authMethod": "claude.ai", "subscriptionType": "free"}'
    elif [ -f "$STUB_STATE/signed-in" ]; then echo '{"loggedIn": true, "authMethod": "claude.ai", "subscriptionType": "pro"}'
    else echo '{"loggedIn": false}'; fi ;;
esac"""
# scripts/install_latex.py on a Windows without TeX, as it is.
NO_LATEX = """import sys
print("No LaTeX on this machine.")
if "--check" not in sys.argv:
    print("On Windows, install MiKTeX from miktex.org/download and let it install missing "
          "packages on the fly when its installer asks: the first resume build then fetches what it needs.")
sys.exit(1)
"""


def script(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(SH + body + "\n")
    os.chmod(path, 0o755)


def commit(repo, message):
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm",
                    message], cwd=repo, check=True)


def ps_quote(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def registry(state) -> dict:
    """The fake registry after everything recorded: {key: {name: value}},
    the key's own value under ''."""
    keys: dict = {}
    path = state / "registry"
    for line in (path.read_text().splitlines() if path.exists() else []):
        op, rest = line.split("\t", 1)
        if op == "remove":
            for k in [k for k in keys if k == rest or k.startswith(rest + "\\")]:
                del keys[k]
        elif op == "new":
            key, value = rest.split("\t", 1)
            keys[key] = {"": value}
        else:
            key, name, value = rest.split("\t", 2)
            keys.setdefault(key, {})[name] = value
    return keys


@pytest.fixture
def pc(tmp_path):
    """A Windows PC with nothing installed, and a template to clone."""
    home, local, roaming, windows, stubs, state, template = (
        tmp_path / d for d in ("home", "local", "roaming", "windows", "stubs", "state", "template"))
    for d in (home, local, roaming, stubs, state):
        d.mkdir()
    for name, body in STUBS.items():
        script(str(stubs / name), body)
    script(str(windows / "System32/WindowsPowerShell/v1.0/powershell.exe"), POWERSHELL)
    script(str(state / "git"), GIT)
    script(str(state / "uv"), UV)
    script(str(state / "claude"), CLAUDE)
    (state / "calls").write_text("")
    prelude = tmp_path / "prelude.ps1"
    prelude.write_text(PRELUDE)

    # The template: enough of a copy for the installer to know one, with the
    # real start.cmd and the real icon drawer.
    for rel in ("ui/server.py", "scripts/doctor.py"):
        (template / rel).parent.mkdir(parents=True, exist_ok=True)
        (template / rel).write_text("")
    (template / "scripts/install_latex.py").write_text(NO_LATEX)
    shutil.copy(os.path.join(ROOT, "ui", "icon.py"), template / "ui" / "icon.py")
    shutil.copy(os.path.join(ROOT, "start.cmd"), template / "start.cmd")
    shutil.copy(SCRIPT, template / "install.ps1")
    subprocess.run(["git", "init", "-q", "-b", "main", str(template)], check=True)
    commit(template, "the template")

    env = {"OS": "Windows_NT", "USERPROFILE": str(home), "HOME": str(home), "LOCALAPPDATA": str(local),
           "APPDATA": str(roaming), "SystemRoot": str(windows), "PROCESSOR_ARCHITECTURE": "AMD64",
           "STUB_BUILD": "26100", "PATH": str(stubs), "TMPDIR": str(tmp_path), "LANG": "C",
           "STUB_STATE": str(state), "STUB_PYTHON": sys.executable, "REAL_GIT": shutil.which("git"),
           "BS_TEMPLATE_URL": str(template),
           # Only the fakes: never this machine's own uv or Claude Code, and never
           # its own Desktop, which .NET finds on a Mac whatever HOME says.
           "BS_TOOL_DIRS": str(home / ".local" / "bin"),
           "BS_START_MENU": str(roaming / "Microsoft/Windows/Start Menu/Programs"),
           "BS_DESKTOP": str(home / "Desktop")}

    class PC:
        pass
    m = PC()
    m.home, m.local, m.state, m.template, m.tmp = home, local, state, template, tmp_path
    m.copy = home / "job-search"
    m.data = local / "BS Job Search"
    m.start_menu = roaming / "Microsoft/Windows/Start Menu/Programs/Job Search.lnk"
    m.desktop = home / "Desktop/Job Search.lnk"

    def run(*args, how="one line", extra=None, drop=()):
        """The installer as the README's one line runs it (irm | iex; with
        options, the scriptblock form the header gives), or as a file from
        inside a copy (-File install.ps1)."""
        e = {**env, **(extra or {})}
        for k in drop:
            e.pop(k, None)
        opts = " ".join(args)
        if how == "one line" and not args:
            body = f"Get-Content -Raw -LiteralPath {ps_quote(SCRIPT)} | Invoke-Expression"
        elif how == "one line":
            body = f"& ([scriptblock]::Create((Get-Content -Raw -LiteralPath {ps_quote(SCRIPT)}))) {opts}"
        else:
            body = f"& {ps_quote(how)} {opts}"
        (state / "calls").write_text("")
        r = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", f". {ps_quote(prelude)}; {body}"],
                           env=e, cwd=str(tmp_path), capture_output=True, text=True, timeout=180,
                           stdin=subprocess.DEVNULL)
        r.calls = (state / "calls").read_text().splitlines()
        r.all = r.stdout + r.stderr
        return r
    m.run = run

    def shortcut(path):
        return json.loads(path.read_text())
    m.shortcut = shortcut
    return m


# ------------------------------------------------------------ without pwsh

def test_the_readme_line_is_the_scripts_own():
    """README's Windows line, and the one install.ps1's header gives, are the same
    line, and it fetches install.ps1 from the public template."""
    head = open(SCRIPT, encoding="utf-8").read()
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
        readme = fh.read()
    assert f"#   {ONE_LINE}\n" in head
    assert f"```powershell\n{ONE_LINE}\n```" in readme


def test_it_is_plain_ascii_and_ships_with_the_template():
    """Windows PowerShell 5.1 reads a script without a byte-order mark in the
    PC's own code page, so the script keeps to ASCII. The export carries it to
    the public template, which the one line fetches from."""
    import export_template
    with open(SCRIPT, "rb") as fh:
        data = fh.read()
    assert all(b < 128 for b in data), [i for i, b in enumerate(data) if b >= 128][:5]
    assert export_template.is_engine("install.ps1")


def test_it_registers_the_link_for_this_user_and_runs_start_cmd():
    with open(SCRIPT, encoding="utf-8") as fh:
        text = fh.read()
    assert r"HKCU:\Software\Classes\$UrlScheme" in text and "$UrlScheme = 'bs-job-search'" in text
    assert "'URL Protocol'" in text and r"\shell\open\command" in text
    assert "HKLM:\\SOFTWARE\\Classes" not in text          # never for every user
    # The shortcut passes its options to the page through start.cmd.
    with open(os.path.join(ROOT, "start.cmd"), encoding="utf-8") as fh:
        assert "ui/server.py %*" in fh.read()


def test_the_windows_icon_holds_every_size_as_png():
    sys.path.insert(0, os.path.join(ROOT, "ui"))
    import struct

    import icon
    data = icon.ico()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind, count) == (0, 1, len(icon.ICO_SIZES))
    for i, size in enumerate(icon.ICO_SIZES):
        w, h, _, _, planes, bits, length, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
        assert (w, h) == ((0, 0) if size == 256 else (size, size)) and (planes, bits) == (1, 32)
        assert data[offset:offset + length] == icon.png(size, tile=True)


# --------------------------------------------------------------- with pwsh

@needs_pwsh
def test_it_parses_and_keeps_to_windows_powershell_5_1():
    """It parses, and uses nothing PowerShell 7 added (?? ?. ?: && ||), since
    the one line runs it in the Windows PowerShell every Windows has."""
    check = (f"$t = $null; $e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile("
             f"{ps_quote(SCRIPT)}, [ref]$t, [ref]$e); $e | ForEach-Object {{ 'error: ' + $_.Message }}; "
             "$t | Where-Object { $_.Kind -in 'QuestionQuestion', 'QuestionQuestionEquals', 'QuestionDot', "
             "'QuestionLBracket', 'QuestionMark', 'AndAnd', 'OrOr' } | ForEach-Object { 'ps7: ' + $_.Text }")
    r = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", check], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0 and r.stdout.strip() == "", r.stdout + r.stderr


@needs_pwsh
def test_a_fresh_pc_gets_everything_and_job_search(pc):
    r = pc.run()
    assert r.returncode == 0, r.all
    calls = "\n".join(r.calls)
    # git through winget, for this user; uv and Claude Code through their own installers.
    assert "winget install --id Git.Git --exact --scope user" in calls
    assert "astral.sh/uv/install.ps1" in calls and "claude.ai/install.ps1" in calls
    assert "uv sync --inexact" in calls                     # extras installed earlier stay
    assert "claude auth login" not in calls                 # no window to sign in from
    assert "Sign in later" in r.stdout
    assert (pc.copy / "start.cmd").is_file() and (pc.copy / ".venv").is_dir()
    # LaTeX: what install_latex.py says on Windows, passed on, and the rest goes on.
    assert "install MiKTeX from miktex.org/download" in r.stdout

    # Job Search in the Start menu and on the Desktop: start.cmd in the copy,
    # minimized, stopping by itself, with the drawn icon.
    ico = pc.data / "Job Search.ico"
    assert ico.read_bytes()[:4] == b"\x00\x00\x01\x00"
    for lnk in (pc.start_menu, pc.desktop):
        s = pc.shortcut(lnk)
        assert s["TargetPath"] == str(pc.copy / "start.cmd") and s["WorkingDirectory"] == str(pc.copy)
        assert s["Arguments"] == "--idle-exit 10" and s["WindowStyle"] == 7
        assert s["IconLocation"] == f"{ico},0"

    # The link, for this user: a URL protocol whose command runs the opener
    # with -File, so nothing a link carries is ever read as a command.
    reg = registry(pc.state)
    assert reg[KEY] == {"": "URL:Job Search", "URL Protocol": ""}
    command = reg[KEY + r"\shell\open\command"][""]
    opener = pc.data / "open.ps1"
    assert command.startswith('"') and "powershell.exe" in command
    assert f'-File "{opener}"' in command and "%1" not in command and "-Command" not in command
    assert reg[KEY + r"\DefaultIcon"][""] == f'"{ico}",0'
    assert reg[KEY + r"\Application"]["ApplicationName"] == "Job Search"
    assert f"$Folder = '{pc.copy}'" in opener.read_text(encoding="utf-8-sig")

    # Opened at the end, through the shortcut, and everything logged.
    assert any(c.startswith(f"start {pc.start_menu} ") for c in r.calls)
    assert "Job Search is in the Start menu and on your Desktop" in r.stdout
    log = (pc.data / "install.log").read_text(encoding="utf-8")
    assert "--- install.ps1" in log and "winget install" in log


@needs_pwsh
def test_running_it_again_installs_nothing_and_remakes_job_search(pc):
    assert pc.run("-NoLatex", "-NoOpen").returncode == 0
    (pc.state / "signed-in").touch()
    stale = pc.shortcut(pc.desktop)
    stale["Arguments"] = "stale"
    pc.desktop.write_text(json.dumps(stale))
    r = pc.run("-NoLatex", "-NoOpen")
    assert r.returncode == 0, r.all
    calls = "\n".join(r.calls)
    assert "winget" not in calls and "install.ps1" not in calls
    assert "ok    signed in" in r.stdout
    assert pc.shortcut(pc.desktop)["Arguments"] == "--idle-exit 10"      # made anew
    assert any(line == f"remove\t{KEY}" for line in (pc.state / "registry").read_text().splitlines())
    assert registry(pc.state)[KEY]["URL Protocol"] == ""
    assert not any(c.startswith("start ") for c in r.calls)              # -NoOpen
    assert "Left for later" in r.stdout and "install_latex" not in calls


@needs_pwsh
def test_from_inside_a_copy_that_copy_is_used(pc):
    """Run as a file from a copy, that copy is the one, wherever it is; the
    shortcuts and the link follow it. A name with a quote in it stays whole."""
    assert pc.run("-NoLatex", "-NoOpen").returncode == 0
    moved = pc.tmp / "elsewhere" / "Pat's search"
    moved.parent.mkdir()
    shutil.move(str(pc.copy), str(moved))
    r = pc.run("-NoLatex", "-NoOpen", how=str(moved / "install.ps1"))
    assert r.returncode == 0, r.all
    assert not pc.copy.exists()
    assert pc.shortcut(pc.desktop)["TargetPath"] == str(moved / "start.cmd")
    opener = (pc.data / "open.ps1").read_text(encoding="utf-8-sig")
    assert "$Folder = '" + str(moved).replace("'", "''") + "'" in opener


@needs_pwsh
def test_the_link_does_what_the_shortcut_does_and_ignores_what_it_carries(pc):
    """The opener the link runs starts start.cmd as the shortcut does. What a
    link carries (here, text a cmd would run) is never more than an argument
    nobody reads. With the copy gone, it says so in a dialog."""
    assert pc.run("-NoLatex", "-NoOpen").returncode == 0
    opener = pc.data / "open.ps1"
    prelude = pc.tmp / "prelude.ps1"

    def open_link(*link):
        (pc.state / "calls").write_text("")
        args = " ".join(ps_quote(a) for a in link)
        r = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command",
                            f". {ps_quote(prelude)}; & {ps_quote(opener)} {args}"],
                           env={"PATH": "/usr/bin:/bin", "HOME": str(pc.home), "STUB_STATE": str(pc.state)},
                           capture_output=True, text=True, timeout=60)
        return r, (pc.state / "calls").read_text().splitlines()

    r, calls = open_link('bs-job-search://launch"&calc&"')
    assert r.returncode == 0, r.stdout + r.stderr
    assert calls == [f"start {pc.copy / 'start.cmd'} | --idle-exit 10 | Minimized | {pc.copy}"]
    shutil.rmtree(pc.copy)
    r, calls = open_link("bs-job-search://launch")
    assert r.returncode == 1
    assert len(calls) == 1 and calls[0].startswith("popup Job Search cannot find its folder")


@needs_pwsh
def test_someone_elses_job_search_is_left_alone(pc):
    pc.desktop.parent.mkdir(parents=True)
    theirs = json.dumps({"TargetPath": r"C:\Games\Job Search.exe", "Description": "a game"})
    pc.desktop.write_text(theirs)
    r = pc.run("-NoLatex", "-NoOpen")
    assert r.returncode == 0, r.all
    assert pc.desktop.read_text() == theirs
    assert "already has something else called Job Search" in r.stdout
    assert pc.shortcut(pc.start_menu)["TargetPath"] == str(pc.copy / "start.cmd")


@pytest.mark.parametrize("extra, drop, says", [
    ({}, ("OS",), "This installer is for Windows"),
    ({"STUB_BUILD": "17134"}, (), "needs Windows 10 version 1809"),
    ({"PROCESSOR_ARCHITECTURE": "x86"}, (), "64-bit Windows"),
])
@needs_pwsh
def test_it_stops_early_where_it_cannot_work(pc, extra, drop, says):
    r = pc.run("-NoLatex", "-NoOpen", extra=extra, drop=drop)
    assert r.returncode == 1 and says in r.stderr
    assert "run the same command again: it picks up where it stopped" in r.stderr
    assert not pc.copy.exists()


@needs_pwsh
def test_a_folder_in_the_way_is_not_touched(pc):
    pc.copy.mkdir()
    (pc.copy / "notes.txt").write_text("mine")
    r = pc.run("-NoLatex", "-NoOpen")
    assert r.returncode == 1 and "is not a copy of BS Job Search" in r.stderr and "-Dir" in r.stderr
    assert os.listdir(pc.copy) == ["notes.txt"]


@needs_pwsh
def test_without_winget_it_says_where_git_comes_from(pc):
    os.remove(pc.tmp / "stubs" / "winget")
    r = pc.run("-NoLatex", "-NoOpen")
    assert r.returncode == 1
    assert "git-scm.com/downloads/win" in r.stderr and "run this again" in r.stderr
    assert "Everything this run printed is in" in r.stderr


@needs_pwsh
def test_pasted_into_a_window_a_stop_leaves_the_window_open(pc):
    """irm | iex pasted straight into PowerShell (no powershell -c around it)
    runs in the user's own window: a stop says why and returns, rather than
    exiting, which would close the window before it could be read."""
    body = (f". {ps_quote(pc.tmp / 'prelude.ps1')}; "
            f"Get-Content -Raw -LiteralPath {ps_quote(SCRIPT)} | Invoke-Expression; 'still here'")
    r = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-EncodedCommand",
                        __import__("base64").b64encode(body.encode("utf-16-le")).decode()],
                       env={"PATH": str(pc.tmp / "stubs"), "HOME": str(pc.home), "STUB_STATE": str(pc.state),
                            "LOCALAPPDATA": str(pc.local), "USERPROFILE": str(pc.home)},
                       capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert "This installer is for Windows" in r.stderr
    assert r.stdout.strip().endswith("still here")


@needs_pwsh
def test_a_free_plan_is_not_taken_for_signed_in(pc):
    (pc.state / "free").touch()
    r = pc.run("-NoLatex", "-NoOpen")
    assert r.returncode == 0, r.all
    assert "Free plan" in r.stdout and "auth login --console" in r.stdout
    assert "ok    signed in" not in r.stdout
    assert "Sign in later" in r.stdout and r.stdout.count("auth login --console") >= 2


@needs_pwsh
def test_latex_found_says_so_and_a_slow_one_says_it_is_still_working(pc):
    (pc.template / "scripts/install_latex.py").write_text(
        "import sys, time\n"
        "if '--check' in sys.argv:\n    print('MiKTeX at C:\\\\TeX\\\\pdflatex.exe, without newtx'); sys.exit(1)\n"
        "time.sleep(2.5)\nprint('LaTeX is ready.')\n")
    commit(pc.template, "a LaTeX installer that takes a while")
    r = pc.run("-NoOpen", extra={"BS_TICK": "1"})
    assert r.returncode == 0, r.all
    assert "still working (0 min)..." in r.stdout
    assert "ok    LaTeX, with the packages the templates use" in r.stdout

    (pc.copy / "scripts/install_latex.py").write_text("print('MiKTeX at C:\\\\TeX, with every package the templates use')\n")
    r = pc.run("-NoOpen")
    assert "ok    MiKTeX at C:\\TeX, with every package" in r.stdout


@needs_pwsh
def test_without_a_shell_for_shortcuts_it_stops_with_why(pc):
    r = pc.run("-NoLatex", "-NoOpen", extra={"STUB_NO_SHELL": "1"})
    assert r.returncode == 1 and "WScript.Shell" in r.stderr


def test_the_header_lists_the_steps_the_script_takes():
    """Each numbered step the script prints is in its header, in order."""
    with open(SCRIPT, encoding="utf-8") as fh:
        text = fh.read()
    steps = re.findall(r"Step '(\d)\. ", text)
    assert steps == ["1", "2", "3", "4", "5", "6"]
    head = text.split("param(")[0]
    assert [n for n in re.findall(r"^#   (\d)\. ", head, re.M)] == steps
