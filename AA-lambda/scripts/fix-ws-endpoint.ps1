param(
    [string]$Region = "ap-southeast-1",
    [string]$WrongApiId = "3lt9ozkq6k",
    [string]$CorrectApiId = "rjhzxw8sqj",
    [switch]$DryRun
)

$ErrorActionPreference = "Continue"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

$Functions = @(
    "supervisor-create-thread",
    "supervisor-create-thread-upload",
    "supervisor-list-threads",
    "supervisor-search-threads",
    "supervisor-get-thread",
    "supervisor-get-messages",
    "supervisor-update-thread",
    "supervisor-delete-thread",
    "supervisor-post-message",
    "supervisor-post-message-upload",
    "supervisor-get-progress",
    "supervisor-actions-pending",
    "supervisor-action-get",
    "supervisor-action-approve",
    "supervisor-actions-cleanup",
    "supervisor-logs-list",
    "supervisor-logs-search",
    "supervisor-logs-stats",
    "supervisor-logs-by-request",
    "supervisor-logs-clear",
    "supervisor-agents-metrics",
    "supervisor-admin-logs",
    "supervisor-admin-activity",
    "supervisor-admin-activity-summary",
    "supervisor-admin-health",
    "supervisor-admin-alerts",
    "supervisor-admin-usage-summary",
    "supervisor-admin-pricing-list",
    "supervisor-admin-pricing-update",
    "supervisor-admin-budget-get",
    "supervisor-admin-budget-update",
    "supervisor-admin-metrics",
    "supervisor-admin-metrics-internal",
    "supervisor-health",
    "supervisor-workflow",
    "supervisor-ws-chat"
)

Write-Host ("Fix-WsEndpoint: " + $WrongApiId + " -> " + $CorrectApiId) -ForegroundColor Cyan
Write-Host ("Targets: " + $Functions.Count + " functions in region " + $Region) -ForegroundColor Cyan
if ($DryRun) { Write-Host "DRY RUN - no AWS writes" -ForegroundColor Yellow }
Write-Host ""

$ok = 0
$skipped = 0
$failed = @()

foreach ($f in $Functions) {
    $cfgJson = aws lambda get-function-configuration --function-name $f --region $Region --output json 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host ("  [FAIL] " + $f + " - get-function-configuration failed: " + $cfgJson) -ForegroundColor Red
        $failed += $f
        continue
    }
    $cfg = $cfgJson | ConvertFrom-Json

    if (-not $cfg.Environment -or -not $cfg.Environment.Variables) {
        Write-Host ("  [SKIP] " + $f + " - no env vars") -ForegroundColor Yellow
        $skipped++
        continue
    }
    $current = $cfg.Environment.Variables.WS_API_ENDPOINT
    if (-not $current) {
        Write-Host ("  [SKIP] " + $f + " - no WS_API_ENDPOINT") -ForegroundColor Yellow
        $skipped++
        continue
    }
    if ($current -notlike "*$WrongApiId*") {
        Write-Host ("  [SKIP] " + $f + " - already correct: " + $current) -ForegroundColor Yellow
        $skipped++
        continue
    }

    $envHash = [ordered]@{}
    foreach ($p in $cfg.Environment.Variables.PSObject.Properties | Sort-Object Name) {
        $val = $p.Value
        if ($p.Name -eq "WS_API_ENDPOINT") {
            $val = $val -replace $WrongApiId, $CorrectApiId
        }
        $envHash[$p.Name] = $val
    }
    $payload = @{ Variables = $envHash } | ConvertTo-Json -Depth 5 -Compress

    if ($DryRun) {
        Write-Host ("  [DRY] " + $f + " would set WS_API_ENDPOINT=" + $envHash.WS_API_ENDPOINT) -ForegroundColor Magenta
        $ok++
        continue
    }

    $tmpPath = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($tmpPath, $payload, $utf8NoBom)
    $result = aws lambda update-function-configuration --function-name $f --region $Region --environment "file://$tmpPath" --output json 2>&1
    Remove-Item $tmpPath -ErrorAction SilentlyContinue
    if ($LASTEXITCODE -ne 0) {
        Write-Host ("  [FAIL] " + $f + " - update-function-configuration failed: " + $result) -ForegroundColor Red
        $failed += $f
        continue
    }
    Write-Host ("  [OK]   " + $f) -ForegroundColor Green
    $ok++
}

Write-Host ""
Write-Host ("Summary: " + $ok + " updated, " + $skipped + " skipped, " + $failed.Count + " failed") -ForegroundColor Cyan
if ($failed.Count -gt 0) {
    Write-Host "Failed functions:" -ForegroundColor Red
    $failed | ForEach-Object { Write-Host ("  - " + $_) -ForegroundColor Red }
    exit 1
}
exit 0
