# Launch a job scan. Double-click, or run:  .\scan.ps1
#
# Opens Claude Code in this folder and starts the /job-scan skill, which asks
# which role clusters to target, then fetches and scores immediately.
#
# If you already have Claude Code open here, just type /job-scan instead --
# this script exists only so the scan is one click from the desktop.

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$Claude = $null
$cmd = Get-Command claude -ErrorAction SilentlyContinue
if ($cmd) {
    $Claude = $cmd.Source
} else {
    # Installed path is version-pinned, so pick the newest rather than hard-coding
    # a version that breaks on the next update.
    foreach ($root in @($env:APPDATA, (Join-Path $env:USERPROFILE 'AppData\Roaming')) |
             Where-Object { $_ } | Select-Object -Unique) {
        $base = Join-Path $root 'Claude\claude-code'
        if (-not (Test-Path $base)) { continue }
        $newest = Get-ChildItem $base -Directory -ErrorAction SilentlyContinue |
                  Sort-Object { try { [version]$_.Name } catch { [version]'0.0.0' } } -Descending |
                  Select-Object -First 1
        if ($newest -and (Test-Path (Join-Path $newest.FullName 'claude.exe'))) {
            $Claude = Join-Path $newest.FullName 'claude.exe'
            break
        }
    }
}

if (-not $Claude) {
    Write-Host "Could not find claude.exe. Is Claude Code installed?" -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

& $Claude "/job-scan"
