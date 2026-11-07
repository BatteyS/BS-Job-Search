# BS Job Search, set up on Windows in one step. When it finishes, Job Search is
# in the Start menu and on your Desktop: open it to open the page, which walks
# you through the rest.
#
# Paste this line into PowerShell (Start menu, type PowerShell) and press Enter:
#
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/BatteyS/BS-Job-Search/main/install.ps1 | iex"
#
# In a copy you already have, run it from that folder instead:
#
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# It installs only what is missing, all of it for you alone, and needs no
# administrator. In order:
#
#   1. git, from Git for Windows, through winget, Windows' own installer.
#   2. uv, which runs the Python this workflow is pinned to.
#   3. Claude Code, and its sign-in, in your browser. It needs any paid Claude
#      plan, including one from your employer, or an Anthropic Console account.
#   4. Your copy of the template, in %USERPROFILE%\job-search, and its Python
#      packages.
#   5. LaTeX, which typesets resumes: found if it is here, and otherwise left
#      to you, with what to install (MiKTeX).
#   6. Job Search in the Start menu and on your Desktop, which starts the page
#      and opens it. It also answers the link bs-job-search://launch, which
#      the Launch button on seanbattey.com uses.
#
# Run it again whenever you like: what is done is skipped, and Job Search's
# shortcuts and its link are made again, which is how to bring them back or
# point them at a copy you moved. Everything it runs prints into
# %LOCALAPPDATA%\BS Job Search\install.log.
#
# Options, after -File install.ps1, or with the one line written as
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/BatteyS/BS-Job-Search/main/install.ps1))) -NoLatex
#
#   -Dir FOLDER   where the copy goes (default %USERPROFILE%\job-search). Run
#                 from inside a copy, that copy is used.
#   -NoLatex      leave LaTeX for later; the page's Setup tab says what to install
#   -NoOpen       do not open the page at the end
#
# Windows 10 (1809 or newer) and 11, in Windows PowerShell 5.1 or PowerShell 7.
# On a Mac, install.sh is the same in one step; on Linux, follow Get started in
# README.md. Job Search on your phone (install.sh --phone) is for Macs only.

param(
  [string]$Dir = '',
  [switch]$NoLatex,
  [switch]$NoOpen,
  [switch]$Help
)

# The file this runs from, when it is one (-File install.ps1); empty when it
# arrives through irm | iex.
$ScriptPath = $PSCommandPath

$TemplateUrl = 'https://github.com/BatteyS/BS-Job-Search.git'
if ($env:BS_TEMPLATE_URL) { $TemplateUrl = $env:BS_TEMPLATE_URL }
$ReadmeUrl = 'https://github.com/BatteyS/BS-Job-Search#get-started'
$MinBuild = 17763    # Windows 10 1809, Claude Code's own floor: code.claude.com/docs/en/setup
$AppName = 'Job Search'
$UrlScheme = 'bs-job-search'   # the link bs-job-search://launch opens the page
$IdleMinutes = 10              # the page stops itself this long after its last tab closes
# A mark in each shortcut's comment, which tells this installer's own from
# anything else called Job Search.
$Description = 'Opens the BS Job Search page, starting it first if it is not running.'

$Utf8 = New-Object System.Text.UTF8Encoding $false
$Bold = ''; $Dim = ''; $Plain = ''
try {
  if (-not [Console]::IsOutputRedirected -and $Host.UI.SupportsVirtualTerminal) {
    $e = [char]27
    $Bold = "$e[1m"; $Dim = "$e[2m"; $Plain = "$e[0m"
  }
} catch { }

# ----------------------------------------------------------------- output

function Step([string]$Text) { Write-Host ''; Write-Host "$Bold$Text$Plain" }
function Ok([string]$Text) { Write-Host "  ${Bold}ok${Plain}    $Text" }
function Note([string]$Text) { Write-Host "        $Text" }

function Write-Log([string]$Text) {
  if (-not $script:Log) { return }
  try { [IO.File]::AppendAllText($script:Log, $Text + [Environment]::NewLine, $Utf8) } catch { }
}

function Show-LogTail([int]$Lines = 12) {
  if (-not $script:Log -or -not (Test-Path -LiteralPath $script:Log)) { return }
  Get-Content -LiteralPath $script:Log -Tail $Lines | ForEach-Object { Write-Host "$Dim        $_$Plain" }
}

# Stop with why, and what to do. Thrown, not exit: pasted straight into a
# PowerShell window, an exit would close it before the message could be read.
function Stop-Install([string]$Text) {
  [Console]::Error.WriteLine('')
  [Console]::Error.WriteLine("${Bold}Stopped.${Plain} $Text")
  if ($script:Log -and (Test-Path -LiteralPath $script:Log)) {
    [Console]::Error.WriteLine('')
    [Console]::Error.WriteLine("${Dim}Everything this run printed is in $($script:Log).$Plain")
  }
  [Console]::Error.WriteLine('Once it is fixed, run the same command again: it picks up where it stopped.')
  throw (New-Object System.OperationCanceledException 'BS Job Search install stopped')
}

# Run a program, everything it prints going to the log. True when it worked;
# what it printed is in $script:Printed.
function Invoke-Logged([string]$Exe, [string[]]$Arguments) {
  Write-Log ('> ' + $Exe + ' ' + ($Arguments -join ' '))
  $keep = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    $out = & $Exe @Arguments 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
  } catch {
    $out = @("$_")
    $code = 127
  } finally {
    $ErrorActionPreference = $keep
  }
  $script:Printed = @($out)
  if ($out) { Write-Log ($out -join [Environment]::NewLine) }
  return ($code -eq 0)
}

# The child PowerShell that runs uv's and Claude Code's own installers, so
# whatever they do (exit included) stays out of this one.
function Get-PowerShellExe {
  if ($env:SystemRoot) {
    $ps = [IO.Path]::Combine($env:SystemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    if (Test-Path -LiteralPath $ps) { return $ps }
  }
  return (Get-Process -Id $PID).Path
}

# Bring in what installers added to PATH since this window opened.
function Update-Path {
  $sep = [IO.Path]::PathSeparator
  $have = @($env:PATH -split [regex]::Escape($sep) | Where-Object { $_ })
  foreach ($target in 'User', 'Machine') {
    $more = [Environment]::GetEnvironmentVariable('Path', $target)
    if (-not $more) { continue }
    foreach ($d in ($more -split [regex]::Escape($sep))) {
      if ($d -and ($have -notcontains $d)) { $have += $d }
    }
  }
  $env:PATH = $have -join $sep
}

# ----------------------------------------------------------------- checks

function Test-Elevated {
  try {
    $me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    return $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  } catch { return $false }
}

function Test-Preflight {
  if ($env:OS -ne 'Windows_NT') {
    Stop-Install "This installer is for Windows. On a Mac, paste the line in Get started in README.md into Terminal instead; on Linux, follow Get started there: $ReadmeUrl"
  }
  if ($PSVersionTable.PSVersion.Major -lt 5) {
    Stop-Install "This is PowerShell $($PSVersionTable.PSVersion), and the installer needs 5.1, which every Windows 10 and 11 has. Open it from the Start menu (type PowerShell), then paste the line again."
  }
  if (Test-Elevated) {
    Stop-Install 'This PowerShell window runs as administrator. Run it in one opened the usual way, as yourself: everything goes into your own user folder, and what an administrator window installs can end up in another account, or belong to the administrator, which breaks updates later.'
  }

  # This run's log, begun only now that it is surely the user's own.
  $data = Join-Path $env:LOCALAPPDATA 'BS Job Search'
  $script:Data = $data
  $script:Log = Join-Path $data 'install.log'
  try {
    New-Item -ItemType Directory -Path $data -Force -ErrorAction Stop | Out-Null
    [IO.File]::WriteAllText($script:Log, '', $Utf8)
  } catch { $script:Log = $null }

  $build = 0; $version = ''
  try {
    $cv = Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' -ErrorAction Stop
    $build = [int]$cv.CurrentBuild
    $version = "$($cv.DisplayVersion)"
    if (-not $version) { $version = "$($cv.ReleaseId)" }
  } catch { $build = [Environment]::OSVersion.Version.Build }
  $name = 'Windows 10'
  if ($build -ge 22000) { $name = 'Windows 11' }
  if ($build -lt $MinBuild) {
    Stop-Install "This PC has $name build $build. Claude Code, which does the interviewing and writing, needs Windows 10 version 1809 (build $MinBuild) or newer. Settings, Windows Update, says whether this PC can take a newer one."
  }

  $arch = $env:PROCESSOR_ARCHITECTURE
  if ($env:PROCESSOR_ARCHITEW6432) { $arch = $env:PROCESSOR_ARCHITEW6432 }   # a 32-bit PowerShell on 64-bit Windows
  if ($arch -eq 'x86') {
    Stop-Install 'This PC runs 32-bit Windows. Claude Code, which does the interviewing and writing, needs 64-bit Windows (x64 or ARM64).'
  }
  $label = $name
  if ($version) { $label += " $version" }
  Ok "$label (build $build), $arch"
  Write-Log ("--- install.ps1, " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ", $label build $build, $arch, PowerShell $($PSVersionTable.PSVersion)")

  try {
    $drive = New-Object System.IO.DriveInfo ([IO.Path]::GetPathRoot($env:USERPROFILE))
    if ($drive.AvailableFreeSpace -lt 3GB) {
      Note "Only $([math]::Floor($drive.AvailableFreeSpace / 1GB)) GB free on this disk. Everything here takes about 1.5 GB."
    }
  } catch { }

  try {
    Invoke-WebRequest -Uri 'https://github.com' -Method Head -UseBasicParsing -TimeoutSec 20 -ErrorAction Stop | Out-Null
  } catch {
    Note 'github.com is not answering, so anything still to download will fail until it does.'
    Note 'On a company network, a proxy may be in the way.'
  }
}

# --------------------------------------------------------------- the tools

# Where uv, Claude Code and winget's programs may be when PATH does not say:
# their installers' own folders. Separated like PATH; the tests name their own.
function Get-ToolDirs {
  if ($env:BS_TOOL_DIRS) { return @($env:BS_TOOL_DIRS -split [regex]::Escape([IO.Path]::PathSeparator)) }
  $dirs = @()
  if ($env:USERPROFILE) {
    $dirs += [IO.Path]::Combine($env:USERPROFILE, '.local', 'bin')
    $dirs += [IO.Path]::Combine($env:USERPROFILE, '.cargo', 'bin')
  }
  if ($env:LOCALAPPDATA) { $dirs += [IO.Path]::Combine($env:LOCALAPPDATA, 'Microsoft', 'WinGet', 'Links') }
  return $dirs
}

# The first program called $Name on PATH, else in the tool folders, else at
# one of $Also.
function Find-Tool([string]$Name, [string[]]$Also = @()) {
  $found = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($found) { return $found.Path }
  $places = @()
  foreach ($d in (Get-ToolDirs)) {
    if ($d) { $places += (Join-Path $d "$Name.exe") }
  }
  $places += $Also
  foreach ($p in $places) {
    if ($p -and (Test-Path -LiteralPath $p -PathType Leaf)) { return (Get-Item -LiteralPath $p).FullName }
  }
  return $null
}

# ------------------------------------------------------------------- git

function Find-Git {
  $also = @()
  if ($env:LOCALAPPDATA) { $also += [IO.Path]::Combine($env:LOCALAPPDATA, 'Programs', 'Git', 'cmd', 'git.exe') }
  if ($env:ProgramFiles) { $also += [IO.Path]::Combine($env:ProgramFiles, 'Git', 'cmd', 'git.exe') }
  return (Find-Tool 'git' $also)
}

function Install-Git {
  Step '1. git'
  $script:Git = Find-Git
  if ($script:Git) {
    Ok (& $script:Git --version)
    return
  }
  $winget = Find-Tool 'winget'
  if (-not $winget) {
    Stop-Install "git is missing, and so is winget, Windows' own installer, which would bring it. Install Git for Windows from https://git-scm.com/downloads/win (its standard choices are fine), then run this again."
  }
  Note 'Installing Git for Windows with winget, for you alone (a minute or two)...'
  Invoke-Logged $winget @('install', '--id', 'Git.Git', '--exact', '--scope', 'user', '--source', 'winget',
    '--silent', '--accept-package-agreements', '--accept-source-agreements') | Out-Null
  Update-Path
  $script:Git = Find-Git
  if (-not $script:Git) {
    Show-LogTail
    Stop-Install 'git did not install: see above. Git for Windows also comes from https://git-scm.com/downloads/win (its standard choices are fine). Then run this again.'
  }
  Ok (& $script:Git --version)
}

# -------------------------------------------------------------------- uv

function Install-Uv {
  Step '2. uv, which runs Python'
  $script:Uv = Find-Tool 'uv'
  if (-not $script:Uv) {
    Note 'Installing uv from astral.sh...'
    Invoke-Logged (Get-PowerShellExe) @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
      'irm https://astral.sh/uv/install.ps1 | iex') | Out-Null
    Update-Path
    $script:Uv = Find-Tool 'uv'
    if (-not $script:Uv) { Show-LogTail; Stop-Install 'uv did not install: see above.' }
  }
  Ok "$(& $script:Uv --version 2>$null) at $($script:Uv)"
}

# ----------------------------------------------------------- Claude Code

function Find-Claude {
  $also = @()
  if ($env:APPDATA) { $also += [IO.Path]::Combine($env:APPDATA, 'npm', 'claude.cmd') }   # an npm install
  return (Find-Tool 'claude' $also)
}

# Signed in to an account that can run Claude Code. A claude.ai account on the
# Free plan signs in but cannot, so it is named, with what to do.
function Test-SignedIn {
  $keep = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try { $state = (& $script:Claude auth status --json 2>$null) -join "`n" } catch { $state = '' }
  finally { $ErrorActionPreference = $keep }
  if ($state -notmatch '"loggedIn":\s*true') { return $false }
  if ($state -match '"subscriptionType":\s*"free"') {
    Note 'This Claude account is on the Free plan, which does not include Claude Code.'
    Note 'Upgrade at claude.com/pricing, or sign in with a Console account instead:'
    Note "& `"$($script:Claude)`" auth login --console"
    return $false
  }
  return $true
}

function Install-Claude {
  Step '3. Claude Code'
  $script:Claude = Find-Claude
  if (-not $script:Claude) {
    Note 'Installing Claude Code from claude.ai. It shows no progress while it downloads,'
    Note 'which takes a minute or two.'
    Invoke-Logged (Get-PowerShellExe) @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
      'irm https://claude.ai/install.ps1 | iex') | Out-Null
    Update-Path
    $script:Claude = Find-Claude
    if (-not $script:Claude) {
      Show-LogTail
      Stop-Install 'Claude Code did not install: see above. Its own guide is at code.claude.com/docs/en/troubleshoot-install'
    }
  }
  $version = (& $script:Claude --version 2>$null | Select-Object -First 1)
  Ok "$version at $($script:Claude)"

  if (Test-SignedIn) { Ok 'signed in'; return }
  Note 'Claude Code needs a paid Claude plan (Pro, Max, Team or Enterprise, including one'
  Note 'from your employer) or an Anthropic Console account; the free plan does not include it.'
  Note 'Signed in to the Claude desktop app already? Claude Code still signs in once, here.'
  $later = "& `"$($script:Claude)`" auth login"
  if (-not $script:CanAsk) {
    Note "Sign in later, in PowerShell: $later"
    Note "(with an Anthropic Console account: $later --console)"
    return
  }
  $answer = Read-Host '        Sign in with a Claude plan (press Enter), a Console account (type c), or later (type l)'
  if ($answer -match '^[Ll]') {
    Note "Later, then. In PowerShell: $later (or $later --console)"
    return
  }
  $how = '--claudeai'
  if ($answer -match '^[Cc]') { $how = '--console' }
  Note "${Bold}Your browser opens to sign in. Come back here when it says you are done.$Plain"
  & $script:Claude auth login $how
  if (Test-SignedIn) {
    Ok 'signed in'
  } else {
    Note "Not signed in yet. Everything else carries on; the page's Setup tab says how to"
    Note 'sign in later.'
  }
}

# ------------------------------------------------------------- your copy

function Test-Copy([string]$Folder) {
  return ((Test-Path -LiteralPath (Join-Path $Folder 'ui\server.py')) -and
          (Test-Path -LiteralPath (Join-Path $Folder 'scripts\doctor.py')))
}

# git in the copy, quietly, its output in $script:Printed.
function Invoke-GitHere([string[]]$Arguments) {
  return (Invoke-Logged $script:Git (@('-C', $script:Dir) + $Arguments))
}

# The remote that is the template: origin for a clone, `template` for a copy
# backed up to a repository of its own.
function Get-TemplateRemote {
  foreach ($r in 'origin', 'template') {
    if ((Invoke-GitHere @('remote', 'get-url', $r)) -and ("$($script:Printed)".ToLower() -like '*batteys/bs-job-search*')) {
      return $r
    }
  }
  if ($env:BS_TEMPLATE_URL -and (Invoke-GitHere @('remote', 'get-url', 'origin')) -and
      ("$($script:Printed)".Trim() -eq $env:BS_TEMPLATE_URL)) { return 'origin' }
  return $null
}

# Bring a plain clone of the template up to date, when the copy needs it to
# run: only a fast-forward, only with nothing uncommitted, and never a copy
# backed up to a repository of its own (the page's Update handles that).
function Update-FromTemplate {
  if ((Get-TemplateRemote) -ne 'origin') { return $false }
  if (-not (Invoke-GitHere @('status', '--porcelain', '--untracked-files=no'))) { return $false }
  if ("$($script:Printed)".Trim()) { return $false }
  if (-not (Invoke-GitHere @('fetch', '--quiet', 'origin'))) { return $false }
  if (-not (Invoke-GitHere @('rev-list', '--count', 'HEAD..@{upstream}'))) { return $false }
  $behind = 0
  [int]::TryParse("$($script:Printed)".Trim(), [ref]$behind) | Out-Null
  if ($behind -le 0) { return $false }
  if (-not (Invoke-GitHere @('merge', '--ff-only', '--quiet', '@{upstream}'))) { return $false }
  Ok "brought in the template's last $behind update(s)"
  return $true
}

function Install-Copy {
  Step '4. Your copy'
  $dir = $script:Dir
  if ((Test-Path -LiteralPath $dir) -and -not (Test-Copy $dir)) {
    Stop-Install "$dir is already there and is not a copy of BS Job Search. Move it, or put the copy in another folder with -Dir: & ([scriptblock]::Create((irm https://raw.githubusercontent.com/BatteyS/BS-Job-Search/main/install.ps1))) -Dir `"$env:USERPROFILE\some-other-folder`""
  }
  if (-not (Test-Path -LiteralPath $dir)) {
    $keep = $env:GIT_TERMINAL_PROMPT
    $env:GIT_TERMINAL_PROMPT = '0'
    $cloned = Invoke-Logged $script:Git @('clone', '--quiet', $TemplateUrl, $dir)
    $env:GIT_TERMINAL_PROMPT = $keep
    if (-not $cloned) { Show-LogTail; Stop-Install "Could not download the template from ${TemplateUrl}: see above." }
    Ok "made $dir"
  } else {
    Ok $dir
  }
  foreach ($cloud in $env:OneDrive, $env:OneDriveConsumer, $env:OneDriveCommercial) {
    if ($cloud -and $dir.StartsWith($cloud.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
      Note 'This folder is kept in OneDrive. OneDrive can move its Python packages and git'
      Note 'files to the cloud to save space, which breaks them. A folder it does not sync,'
      Note 'such as %USERPROFILE%\job-search, is safer.'
      break
    }
  }
  # Job Search runs the copy's start.cmd: a copy without one, catch it up if it can.
  if (-not (Test-Path -LiteralPath (Join-Path $dir 'start.cmd'))) {
    Update-FromTemplate | Out-Null
    if (-not (Test-Path -LiteralPath (Join-Path $dir 'start.cmd'))) {
      Stop-Install "$dir has no start.cmd, which Job Search runs, and could not be brought up to date by itself. Open the page as before and press Update on its Setup tab, then run this again."
    }
  }
}

# One `uv sync`, what it printed kept in $script:Printed as well as the log.
# --inexact keeps extras installed earlier, such as the scraped boards'.
function Invoke-SyncOnce {
  Push-Location -LiteralPath $script:Dir
  try { return (Invoke-Logged $script:Uv @('sync', '--inexact')) } finally { Pop-Location }
}

function Sync-Packages {
  Note 'Installing Python and the packages (a minute or two the first time)...'
  if (Invoke-SyncOnce) { return $true }
  # A company network that inspects HTTPS: uv's own certificates do not know
  # its proxy, but Windows' certificate store does.
  if (("$($script:Printed)" -match 'certificate')) {
    $env:UV_NATIVE_TLS = '1'
    if (Invoke-SyncOnce) {
      $config = Join-Path $env:APPDATA 'uv'
      $toml = Join-Path $config 'uv.toml'
      New-Item -ItemType Directory -Path $config -Force | Out-Null
      if (-not ((Test-Path -LiteralPath $toml) -and (Select-String -LiteralPath $toml -Pattern 'native-tls' -Quiet))) {
        [IO.File]::AppendAllText($toml, "native-tls = true`n", $Utf8)
      }
      Note "This network inspects HTTPS, so uv now uses Windows' own certificates"
      Note '(native-tls = true, in %APPDATA%\uv\uv.toml).'
      return $true
    }
  }
  # A uv older than the lockfile's format updates itself, where it can.
  if (("$($script:Printed)" -match 'uv\.lock') -and (Invoke-Logged $script:Uv @('self', 'update')) -and (Invoke-SyncOnce)) {
    Note "uv was older than this copy's lockfile, so it updated itself."
    return $true
  }
  # A fix may be waiting in the template.
  return ((Update-FromTemplate) -and (Invoke-SyncOnce))
}

function Install-Packages {
  if (-not (Sync-Packages)) { Show-LogTail 15; Stop-Install 'The Python packages did not install: see above.' }
  Push-Location -LiteralPath $script:Dir
  try {
    $py = (& $script:Uv run --no-sync python -c 'import platform; print(platform.python_version())' 2>$null | Select-Object -First 1)
  } catch { $py = '' } finally { Pop-Location }
  Ok "Python $py and the packages, in $(Join-Path $script:Dir '.venv')"
}

# ------------------------------------------------------------------ LaTeX

# Run scripts/$Script in the copy, what it prints going to the log and to
# $script:Printed, and say once a minute that it is still going: a download
# can stall, and silence reads as stuck. BS_TICK, in seconds, is for the tests.
function Invoke-Ticking([string]$Script, [string[]]$Arguments = @()) {
  $tick = 60
  if ($env:BS_TICK) { $tick = [int]$env:BS_TICK }
  $out = [IO.Path]::GetTempFileName()
  $err = [IO.Path]::GetTempFileName()
  $argv = @('run', '--no-sync', 'python', "scripts/$Script") + $Arguments
  Write-Log ('> ' + $script:Uv + ' ' + ($argv -join ' '))
  try {
    $p = Start-Process -FilePath $script:Uv -ArgumentList $argv -WorkingDirectory $script:Dir -NoNewWindow `
      -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    $null = $p.Handle    # without it, Windows PowerShell loses the exit code
    $secs = 0
    while (-not $p.WaitForExit(1000)) {
      $secs++
      if ($secs % $tick -eq 0) { Note "still working ($([math]::Floor($secs / 60)) min)..." }
    }
    $p.WaitForExit()
    $printed = @(Get-Content -LiteralPath $out) + @(Get-Content -LiteralPath $err)
    $script:Printed = $printed
    Write-Log ($printed -join [Environment]::NewLine)
    return ($p.ExitCode -eq 0)
  } catch {
    $script:Printed = @("$_")
    Write-Log "$_"
    return $false
  } finally {
    Remove-Item -LiteralPath $out, $err -Force -ErrorAction SilentlyContinue
  }
}

function Install-Latex {
  Step '5. LaTeX, which typesets resumes'
  if ($NoLatex) {
    Note "Left for later: the page's Setup tab says what to install."
    return
  }
  if (Invoke-Ticking 'install_latex.py' @('--check')) {
    Ok ($script:Printed | Select-Object -First 1)
    return
  }
  # What install_latex.py can do on Windows, it does; what it cannot, it says.
  if (Invoke-Ticking 'install_latex.py') {
    Ok 'LaTeX, with the packages the templates use'
    return
  }
  foreach ($line in ($script:Printed | Where-Object { "$_".Trim() -and "$_" -notlike '$ *' } | Select-Object -Last 4)) {
    Note "$line"
  }
  Note 'Only resumes and letters need it: everything else carries on, and the page''s'
  Note 'Setup tab says the same until it is in.'
}

# ------------------------------------------- the Start menu and the Desktop

# The copy's icon, drawn by its own ui/icon.py, beside the log. None from a
# copy too old to draw one, and the shortcuts then show cmd's.
function New-Icon {
  $ico = Join-Path $script:Data 'Job Search.ico'
  Push-Location -LiteralPath $script:Dir
  try { $made = Invoke-Logged $script:Uv @('run', '--no-sync', 'python', 'ui/icon.py', '--ico', $ico) }
  finally { Pop-Location }
  if ($made -and (Test-Path -LiteralPath $ico)) { return $ico }
  return $null
}

# Whether the shortcut at $Path is one this installer made.
function Test-Ours($Shell, [string]$Path) {
  try { $lnk = $Shell.CreateShortcut($Path) } catch { return $false }
  return (("$($lnk.Description)" -eq $Description) -or ([IO.Path]::GetFileName("$($lnk.TargetPath)") -eq 'start.cmd'))
}

# Job Search in folder $Folder: start.cmd in the copy, its window minimized,
# since that window holds the page, and passing --idle-exit, so the page stops
# (and the window closes) once no tab has had it open for a while. Something
# else there by that name is never written over.
function New-Shortcut($Shell, [string]$Folder, [string]$Icon) {
  $path = Join-Path $Folder "$AppName.lnk"
  if ((Test-Path -LiteralPath $path) -and -not (Test-Ours $Shell $path)) {
    Note "$Folder already has something else called $AppName, which stays as it is."
    return $null
  }
  try {
    New-Item -ItemType Directory -Path $Folder -Force -ErrorAction Stop | Out-Null
    $lnk = $Shell.CreateShortcut($path)
    $lnk.TargetPath = Join-Path $script:Dir 'start.cmd'
    $lnk.Arguments = "--idle-exit $IdleMinutes"
    $lnk.WorkingDirectory = $script:Dir
    $lnk.WindowStyle = 7          # minimized
    $lnk.Description = $Description
    if ($Icon) { $lnk.IconLocation = "$Icon,0" }
    $lnk.Save()
    return $path
  } catch {
    Write-Log "Could not make ${path}: $_"
    return $null
  }
}

# What the link runs: this, written beside the log, which does what the
# shortcuts do. A file run with -File, so that nothing a link carries is ever
# read as a command; it is ignored.
function New-Opener {
  $opener = Join-Path $script:Data 'open.ps1'
  $folder = $script:Dir.Replace("'", "''")
  $text = @"
# Job Search, made by install.ps1 for the copy below. The link
# bs-job-search://launch (the Launch button on seanbattey.com) runs this, and it
# does what Job Search in the Start menu does. Whatever the link carries is
# ignored. Run install.ps1 in that copy again to make it anew, or to point it at
# a copy you moved.
`$Folder = '$folder'
`$start = Join-Path `$Folder 'start.cmd'
if (-not (Test-Path -LiteralPath `$start)) {
  `$said = "Job Search cannot find its folder, `$Folder, or the start.cmd in it. If you moved or renamed it, open PowerShell in its new place and run: powershell -ExecutionPolicy Bypass -File install.ps1. That makes Job Search anew."
  (New-Object -ComObject WScript.Shell).Popup(`$said, 0, 'Job Search', 48) | Out-Null
  exit 1
}
Start-Process -FilePath `$start -ArgumentList '--idle-exit', '$IdleMinutes' -WorkingDirectory `$Folder -WindowStyle Minimized
"@
  # With a byte-order mark, or Windows PowerShell reads a folder named in any
  # letter beyond ASCII wrongly.
  [IO.File]::WriteAllText($opener, $text, (New-Object System.Text.UTF8Encoding $true))
  return $opener
}

# The link bs-job-search://launch, for this user alone: the Launch button on
# seanbattey.com opens it. Made anew each run. Not fatal: Job Search works
# without it.
function Register-Link([string]$Opener, [string]$Icon) {
  $key = "HKCU:\Software\Classes\$UrlScheme"
  $command = "`"$(Get-PowerShellExe)`" -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Opener`""
  try {
    if (Test-Path -LiteralPath $key) { Remove-Item -LiteralPath $key -Recurse -Force -ErrorAction Stop }
    New-Item -Path $key -Value "URL:$AppName" -Force -ErrorAction Stop | Out-Null
    New-ItemProperty -Path $key -Name 'URL Protocol' -Value '' -PropertyType String -Force -ErrorAction Stop | Out-Null
    if ($Icon) { New-Item -Path "$key\DefaultIcon" -Value "`"$Icon`",0" -Force -ErrorAction Stop | Out-Null }
    # The name a browser may give it when it asks whether to open the link.
    New-Item -Path "$key\Application" -Force -ErrorAction Stop | Out-Null
    New-ItemProperty -Path "$key\Application" -Name 'ApplicationName' -Value $AppName -PropertyType String -Force -ErrorAction Stop | Out-Null
    New-Item -Path "$key\shell\open\command" -Value $command -Force -ErrorAction Stop | Out-Null
    Write-Log "registered $UrlScheme`: $command"
    return $true
  } catch {
    Write-Log "Could not register ${UrlScheme}: $_"
    return $false
  }
}

function Install-App {
  Step '6. Job Search in the Start menu and on your Desktop'
  $icon = New-Icon
  try { $shell = New-Object -ComObject WScript.Shell -ErrorAction Stop } catch {
    Show-LogTail
    Stop-Install "Windows would not make shortcuts here (WScript.Shell): $_"
  }
  # Windows' own answers, which follow a Desktop that OneDrive keeps. The
  # tests name their own folders.
  $programs = $env:BS_START_MENU
  if (-not $programs) { $programs = [Environment]::GetFolderPath('Programs') }
  if (-not $programs) { $programs = [IO.Path]::Combine($env:APPDATA, 'Microsoft', 'Windows', 'Start Menu', 'Programs') }
  $desktop = $env:BS_DESKTOP
  if (-not $desktop) { $desktop = [Environment]::GetFolderPath('Desktop') }
  if (-not $desktop) { $desktop = Join-Path $env:USERPROFILE 'Desktop' }

  $script:Shortcuts = @()
  foreach ($folder in $programs, $desktop) {
    $made = New-Shortcut $shell $folder $icon
    if ($made) { $script:Shortcuts += $made; Ok $made }
  }
  if (-not $script:Shortcuts) {
    Show-LogTail
    Stop-Install "Could not make $AppName in the Start menu or on the Desktop: see above."
  }
  if (Register-Link (New-Opener) $icon) {
    Ok "the link ${UrlScheme}://launch opens it"
  } else {
    Note "The link ${UrlScheme}://launch could not be registered, so the Launch button on"
    Note "seanbattey.com will not open $AppName. Everything else works. The log says why."
  }
}

# ------------------------------------------------------------------- main

function Invoke-Install {
  if ($Help) {
    if ($ScriptPath) {
      foreach ($line in (Get-Content -LiteralPath $ScriptPath)) {
        if ($line -notmatch '^#') { break }
        Write-Host ($line -replace '^# ?', '')
      }
    } else {
      Write-Host "BS Job Search's Windows installer. What it does and its options: $ReadmeUrl"
    }
    return
  }

  # Run from inside a copy (-File install.ps1), that copy is the one.
  $dir = $Dir
  if (-not $dir -and $ScriptPath) {
    $here = Split-Path -Parent $ScriptPath
    if ($here -and (Test-Copy $here)) { $dir = (Resolve-Path -LiteralPath $here).ProviderPath }
  }
  if (-not $dir) {
    if ($env:JOB_SEARCH_DIR) { $dir = $env:JOB_SEARCH_DIR } else { $dir = Join-Path $env:USERPROFILE 'job-search' }
  }
  $dir = [Environment]::ExpandEnvironmentVariables($dir)
  if ($dir -eq '~' -or $dir -like '~[\/]*') { $dir = Join-Path $env:USERPROFILE $dir.Substring(1).TrimStart('\', '/') }
  if (-not [IO.Path]::IsPathRooted($dir)) { $dir = Join-Path (Get-Location).ProviderPath $dir }
  $script:Dir = [IO.Path]::GetFullPath($dir).TrimEnd('\', '/')

  # Somewhere to ask questions: a window someone is typing into.
  $script:CanAsk = $false
  try { $script:CanAsk = [Environment]::UserInteractive -and -not [Console]::IsInputRedirected } catch { }

  try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }

  Write-Host "${Bold}BS Job Search: setting up this PC$Plain"
  Test-Preflight
  Install-Git
  Install-Uv
  Install-Claude
  Install-Copy
  Install-Packages
  Install-Latex
  Install-App

  Step 'Done'
  Note "$AppName is in the Start menu and on your Desktop: open it whenever you want the page."
  Note 'Its window waits, minimized, while the page runs, and closes by itself ten minutes'
  Note "after you close the page's last tab. This PowerShell window can be closed."
  if (-not $NoOpen) {
    Note "Opening the page in your browser now. Its Setup tab walks you through the rest."
    # Through the shortcut, not from here: the page then runs in a window of its
    # own, which closing this one leaves alone.
    try { Start-Process -FilePath $script:Shortcuts[0] -ErrorAction Stop }
    catch { Note "It did not open: open $AppName from the Start menu." }
  }
}

$Failed = $false
$KeepEncoding = $null
try {
  # What the programs it runs print, read as the UTF-8 they write.
  try { $KeepEncoding = [Console]::OutputEncoding; [Console]::OutputEncoding = $Utf8 } catch { }
  Invoke-Install
} catch [System.OperationCanceledException] {
  $Failed = $true
} catch {
  [Console]::Error.WriteLine('')
  [Console]::Error.WriteLine("${Bold}Stopped.${Plain} Something unexpected went wrong: $_")
  if ($script:Log) { [Console]::Error.WriteLine("${Dim}Everything this run printed is in $($script:Log).$Plain") }
  [Console]::Error.WriteLine('Run the same command again: it picks up where it stopped. If it stops here again, the log above says more.')
  Write-Log "unexpected: $_"
  $Failed = $true
} finally {
  if ($KeepEncoding) { try { [Console]::OutputEncoding = $KeepEncoding } catch { } }
}
# A failure ends with exit code 1 where that closes nothing anyone is reading:
# run as a file, or by the one line's own powershell -c.
if ($Failed -and ($ScriptPath -or ([Environment]::GetCommandLineArgs() -match '^-(c|command)$'))) { exit 1 }
