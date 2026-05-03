# Restores the canonical env-var set on supervisor-admin-budget-{get,update}
# after they were accidentally clobbered by an --environment "Variables={...}"
# call (which REPLACES the entire env map instead of merging).
#
# Symptom: GET /admin/settings/budget returns 502, and CloudWatch shows:
#   OperationalError: unable to open database file
# at LogStorage(...).  Cause: PERSISTENCE_BACKEND=dynamodb was wiped, so
# the lambda fell back to SQLite at /var/task/logs.db (read-only filesystem).
#
# Fix: pull the canonical env from a known-good ZIP-mode lambda
# (supervisor-admin-pricing-list) and merge in the BUDGET_ALERT_*
# overrides that the budget lambdas need on top of the baseline.

[CmdletBinding()]
param(
  [string]$Region = "ap-southeast-1",
  [string]$ReferenceLambda = "supervisor-admin-pricing-list",
  [string[]]$TargetLambdas = @(
    "supervisor-admin-budget-get",
    "supervisor-admin-budget-update"
  )
)

$env:PYTHONUTF8 = "1"
chcp 65001 | Out-Null

Write-Host "=== Pulling canonical env from $ReferenceLambda ===" -ForegroundColor Cyan
$refJson = aws lambda get-function-configuration --function-name $ReferenceLambda --region $Region --query "Environment.Variables" --output json 2>&1
if ($LASTEXITCODE -ne 0) {
  Write-Host "Failed to read reference env: $refJson" -ForegroundColor Red
  exit 1
}
$baseline = $refJson | ConvertFrom-Json
$baselineKeys = @($baseline.PSObject.Properties.Name)
Write-Host ("  Baseline has {0} vars: {1}" -f $baselineKeys.Count, ($baselineKeys -join ", "))

foreach ($fn in $TargetLambdas) {
  Write-Host ""
  Write-Host "=== Restoring $fn ===" -ForegroundColor Cyan

  # Read current (possibly broken) env so we preserve any extras
  # the budget lambdas have on top of the baseline.
  $curJson = aws lambda get-function-configuration --function-name $fn --region $Region --query "Environment.Variables" --output json 2>&1
  if ($LASTEXITCODE -ne 0) {
    Write-Host "  Skipping (could not read current env): $curJson" -ForegroundColor Yellow
    continue
  }
  $current = $curJson | ConvertFrom-Json
  $currentKeys = @($current.PSObject.Properties.Name)
  Write-Host ("  Current has {0} vars: {1}" -f $currentKeys.Count, ($currentKeys -join ", "))

  # Merge: baseline first, then current (so current overrides baseline
  # for shared keys, and current-only keys like BUDGET_ALERT_* survive).
  $merged = [ordered]@{}
  foreach ($p in $baseline.PSObject.Properties) {
    $merged[$p.Name] = $p.Value
  }
  foreach ($p in $current.PSObject.Properties) {
    $merged[$p.Name] = $p.Value
  }

  # Diff for the human reading the log.
  $added = @($baselineKeys | Where-Object { -not ($currentKeys -contains $_) })
  if ($added.Count -gt 0) {
    Write-Host ("  Re-adding wiped vars: {0}" -f ($added -join ", ")) -ForegroundColor Green
  } else {
    Write-Host "  All baseline vars already present (no-op)" -ForegroundColor Gray
  }

  # Build the AWS CLI env JSON: { "Variables": { ... } } and write
  # to a BOM-free UTF-8 file. AWS CLI rejects UTF-8 BOM in --environment
  # JSON files (root cause of the IAM MalformedPolicyDocument issue earlier).
  $envObj = @{ Variables = $merged }
  $envJson = $envObj | ConvertTo-Json -Depth 10 -Compress
  $tmpFile = Join-Path ([System.IO.Path]::GetTempPath()) ("env-{0}-{1}.json" -f $fn, ([guid]::NewGuid().ToString("N")))
  $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($tmpFile, $envJson, $utf8NoBom)

  $result = aws lambda update-function-configuration --function-name $fn --region $Region --environment ("file://" + $tmpFile) --output json 2>&1
  Remove-Item $tmpFile -ErrorAction SilentlyContinue

  if ($LASTEXITCODE -ne 0) {
    Write-Host ("  FAILED: {0}" -f $result) -ForegroundColor Red
  } else {
    Write-Host "  Updated. Final var keys:" -ForegroundColor Green
    $finalKeys = ($result | ConvertFrom-Json).Environment.Variables.PSObject.Properties.Name | Sort-Object
    Write-Host ("    " + ($finalKeys -join ", "))
  }
}

Write-Host ""
Write-Host "Done. Wait ~5s for the new config to propagate, then refresh the dashboard." -ForegroundColor Cyan
