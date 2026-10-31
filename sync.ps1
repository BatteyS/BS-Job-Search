# Two-machine sync helper.
#
# The failure mode worth preventing is not "git is hard" -- it is finishing on
# the desktop without pushing, then editing the same file on the laptop and
# landing in a conflict. So: check before you start, and push when you stop.
#
#   .\sync.ps1 start     pull, then report anything that needs attention
#   .\sync.ps1 done      show what changed, commit with a message, push
#   .\sync.ps1 status    where things stand, without changing anything
#
#   .\sync.ps1 done -m "add SCADA bullets from split_scada"

param(
    [Parameter(Position = 0)][ValidateSet('start', 'done', 'status')]
    [string]$Action = 'status',
    [Alias('m')][string]$Message
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Test-Setup {
    if (-not (Test-Path 'content/contact.local.md')) {
        Write-Host ""
        Write-Host "  contact.local.md is missing on this machine." -ForegroundColor Yellow
        Write-Host "  Resume builds will fail until you create it:"
        Write-Host "      copy content\contact.example.md content\contact.local.md"
        Write-Host "  Then edit it. It is gitignored, so it never syncs."
    }
}

function Show-Divergence {
    $ahead = (git rev-list --count '@{u}..HEAD' 2>$null)
    $behind = (git rev-list --count 'HEAD..@{u}' 2>$null)
    if ($LASTEXITCODE -ne 0 -or $null -eq $ahead) {
        Write-Host "  no upstream configured yet (git push -u origin main)" -ForegroundColor DarkGray
        return
    }
    if ($ahead -gt 0) { Write-Host "  $ahead local commit(s) NOT pushed" -ForegroundColor Yellow }
    if ($behind -gt 0) { Write-Host "  $behind commit(s) on the remote not pulled" -ForegroundColor Yellow }
    if ($ahead -eq 0 -and $behind -eq 0) { Write-Host "  in sync with remote" -ForegroundColor Green }
}

switch ($Action) {

    'start' {
        Write-Host "pulling..." -ForegroundColor Cyan
        git pull --rebase
        if ($LASTEXITCODE -ne 0) {
            Write-Host ""
            Write-Host "  Pull failed -- most likely a conflict from editing the same" -ForegroundColor Red
            Write-Host "  file on both machines. Resolve, then: git rebase --continue"
            exit 1
        }
        Write-Host ""
        Show-Divergence
        Test-Setup
    }

    'done' {
        $changes = git status --porcelain
        if (-not $changes) {
            Write-Host "nothing to commit." -ForegroundColor DarkGray
            Show-Divergence
            break
        }
        Write-Host "changes:" -ForegroundColor Cyan
        git status --short
        Write-Host ""
        if (-not $Message) {
            $Message = Read-Host "commit message"
            if (-not $Message) { Write-Host "aborted."; exit 1 }
        }
        git add -A
        # No Co-Authored-By trailer -- see CLAUDE.md.
        git commit -m $Message
        Write-Host "pushing..." -ForegroundColor Cyan
        git push
        if ($LASTEXITCODE -ne 0) {
            Write-Host ""
            Write-Host "  Push failed. Usually means the remote moved ahead:" -ForegroundColor Yellow
            Write-Host "      .\sync.ps1 start     (pull --rebase, then push again)"
            exit 1
        }
        Write-Host "pushed." -ForegroundColor Green
    }

    'status' {
        git status --short
        Write-Host ""
        Show-Divergence
        Test-Setup
        Write-Host ""
        Write-Host "  Note: Applications/ is NOT in the repo and does not sync." -ForegroundColor DarkGray
    }
}
