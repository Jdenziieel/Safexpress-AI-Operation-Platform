# Phase 8.C - Stop local + archive SQLite to S3.
#
# - Surfaces the local FastAPI/uvicorn processes so the operator can stop them.
# - Copies threads.db + logs.db to S3 with a date-stamped key.
# - Leaves the source files in place. Idempotent (re-run with a different
#   -DateStamp produces a separate archive).
#
# Run from anywhere; paths resolved relative to the repo root.

param(
    [Parameter(Mandatory=$true)]
    [string]$ArchiveBucket,

    [string]$Region    = "ap-southeast-1",
    [string]$Prefix    = "archive/supervisor",
    [string]$DateStamp = (Get-Date -Format "yyyy-MM-dd"),

    [switch]$SkipUploads,
    [switch]$SkipProcessList,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# Repo root = parent of "AA-lambda/" containing this script.
$RepoRoot  = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ThreadsDb = Join-Path $RepoRoot "supervisor-agent\threads.db"
$LogsDb    = Join-Path $RepoRoot "supervisor-agent\logs.db"

$bar = ("=" * 72)
Write-Host $bar
Write-Host "AA-lambda Phase 8.C - Archive + decommission helper"
Write-Host $bar
Write-Host "  RepoRoot:       $RepoRoot"
Write-Host "  ArchiveBucket:  s3://$ArchiveBucket/$Prefix/"
Write-Host "  Region:         $Region"
Write-Host "  DateStamp:      $DateStamp"
if ($DryRun) {
    Write-Host "  Mode:           DRY RUN (no S3 writes)"
}
Write-Host ""

# ----------------------------------------------------------------------
# 1. Local process surface
# ----------------------------------------------------------------------

if (-not $SkipProcessList) {
    Write-Host "Step 1: local uvicorn / FastAPI processes"
    Write-Host "  Stop these manually after confirming the deployed stack is healthy."
    Write-Host ""
    $candidates = Get-Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Path -and
            ($_.Path -match "python|uvicorn") -and
            $_.CommandLine -ne $null
        } |
        Select-Object Id, ProcessName, Path, StartTime |
        Sort-Object StartTime
    if ($candidates) {
        $candidates | Format-Table -AutoSize
        Write-Host '  Stop with: Stop-Process -Id <ID> (one at a time)'
    } else {
        Write-Host "  No matching python/uvicorn processes found."
    }
    Write-Host ""
}

# ----------------------------------------------------------------------
# 2. Archive to S3
# ----------------------------------------------------------------------

if (-not $SkipUploads) {
    Write-Host "Step 2: archive SQLite DBs to S3"

    $files = @(
        @{ Local = $ThreadsDb; Key = "$Prefix/$DateStamp/threads.db" },
        @{ Local = $LogsDb;    Key = "$Prefix/$DateStamp/logs.db"    }
    )

    foreach ($f in $files) {
        if (-not (Test-Path $f.Local)) {
            Write-Host "  [SKIP] $($f.Local) does not exist - nothing to archive."
            continue
        }
        $size   = (Get-Item $f.Local).Length
        $sizeMb = [math]::Round($size / 1MB, 2)
        $dest   = "s3://$ArchiveBucket/$($f.Key)"
        Write-Host "  $($f.Local)  ($sizeMb MB)  ->  $dest"
        if ($DryRun) {
            Write-Host "    (dry-run, no upload)"
            continue
        }
        & aws s3 cp $f.Local $dest --region $Region
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [ERROR] aws s3 cp exited $LASTEXITCODE for $($f.Local)"
            exit $LASTEXITCODE
        }
    }

    Write-Host ""
    Write-Host "  Archive complete. The originals are untouched - keep them on disk"
    Write-Host "  for at least one rollback window before deleting."
}

# ----------------------------------------------------------------------
# 3. Reminder
# ----------------------------------------------------------------------

Write-Host $bar
Write-Host "Next steps:"
Write-Host "  1. Stop the 7 local uvicorn processes listed above."
Write-Host "  2. Update onboarding docs to mark supervisor-agent/ and the 6 sub-agent"
Write-Host "     folders as 'reference implementation'. AA-lambda/ is the canonical home."
Write-Host "  3. Verify rollback path: ``cd supervisor-agent && python main.py`` still works."
Write-Host $bar
