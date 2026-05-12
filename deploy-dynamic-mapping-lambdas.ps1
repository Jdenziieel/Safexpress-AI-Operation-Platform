# Build + deploy script for the two safexpressops dynamic-mapping Lambdas.
#
# These two Lambdas are pure-Python (no compiled deps) and only use boto3,
# which is already in the AWS Lambda runtime. So a ZIP package containing
# just lambda_function.py is all we need — no `pip install`, no Docker,
# no ECR.
#
# Usage:
#   .\deploy-dynamic-mapping-lambdas.ps1                  # deploys BOTH
#   .\deploy-dynamic-mapping-lambdas.ps1 -Only agent      # agent only
#   .\deploy-dynamic-mapping-lambdas.ps1 -Only wrapper    # wrapper only
#   .\deploy-dynamic-mapping-lambdas.ps1 -DryRun          # zip only, no upload
#
# Idempotent. Safe to re-run. Prints LastModified before+after so you can
# verify the upload landed.

[CmdletBinding()]
param(
    [ValidateSet("both", "agent", "wrapper", "mapping", "sheets")]
    [string]$Only = "both",
    [string]$Region = "ap-southeast-1",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

# (LambdaName, source folder, file list to ZIP)
# The `mapping` target is a multi-file ZIP because the mapping-agent's
# entry point (lambda_function.py) imports sibling modules at runtime
# (mapping_agent_api, smart_mapping_engine, safexpressops_target_columns).
# All four MUST land at the archive root or `import mapping_agent_api`
# will fail with ModuleNotFoundError on the very first invocation.
#
# The `sheets` target is similar — it depends on sheets_agent_api as
# a sibling module. Heavy deps (pandas, numpy, google APIs) are provided
# by Lambda layers (sheets-google-layer, sheets-2A, sheets-2B, sheets-web)
# so the ZIP only needs the two .py files.
$targets = @(
    @{
        Name   = "safexpressops-dynamic-mapping-agent"
        Folder = Join-Path $Root "safexpressops-dynamic-mapping-agent-3ea76fd8-7f04-447b-a7a1-9d8d14b94060"
        Files  = @("lambda_function.py")
        Tag    = "agent"
    },
    @{
        Name   = "safexpressops-dynamic-mapping-wrapper"
        Folder = Join-Path $Root "downloaded-lambdas\safexpressops-dynamic-mapping-wrapper"
        Files  = @("lambda_function.py")
        Tag    = "wrapper"
    },
    @{
        Name   = "safexpressops-mapping-agent"
        Folder = Join-Path $Root "safexpressops-mapping-agent-287212a2-db05-452d-8bd4-54af56d985d4"
        Files  = @("lambda_function.py", "mapping_agent_api.py", "smart_mapping_engine.py", "safexpressops_target_columns.py")
        Tag    = "mapping"
    },
    @{
        Name   = "safexpressops-sheets-agent"
        Folder = Join-Path $Root "safexpressops-sheets-agent-b9d0a7da-6710-4267-839d-7f64ce3e3511"
        Files  = @("lambda_function.py", "sheets_agent_api.py")
        Tag    = "sheets"
    }
)

if ($Only -ne "both") {
    $targets = @($targets | Where-Object { $_.Tag -eq $Only })
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Magenta
Write-Host "  Deploying $($targets.Count) Lambda(s) to $Region" -ForegroundColor Magenta
Write-Host "==================================================" -ForegroundColor Magenta

$tmpDir = Join-Path $env:TEMP "safexpressops-deploy-$(Get-Date -Format yyyyMMdd-HHmmss)"
New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null

foreach ($t in $targets) {
    $name   = $t.Name
    $folder = $t.Folder
    $files  = $t.Files

    Write-Host ""
    Write-Host "--- $name ---" -ForegroundColor Cyan

    $srcPaths = @()
    foreach ($f in $files) {
        $p = Join-Path $folder $f
        if (-not (Test-Path $p)) {
            Write-Host "  [error] missing $p" -ForegroundColor Red
            exit 1
        }
        $srcPaths += $p
    }

    # Show the BEFORE state so the user can verify the deploy actually
    # bumped LastModified afterwards.
    $beforeJson = aws lambda get-function-configuration `
        --function-name $name `
        --region $Region `
        --query "{LastModified:LastModified,CodeSize:CodeSize,CodeSha256:CodeSha256}" `
        --output json 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [error] Lambda not found or access denied: $beforeJson" -ForegroundColor Red
        exit 1
    }
    $before = $beforeJson | ConvertFrom-Json
    Write-Host "  before: $($before.LastModified) | $($before.CodeSize) bytes | sha256=$($before.CodeSha256.Substring(0,12))..." -ForegroundColor Gray

    # Build a fresh ZIP. The Files list above controls what lands at the
    # archive root: single-file Lambdas just bundle lambda_function.py;
    # the mapping-agent target bundles the entry point + 3 sibling
    # modules it imports (Compress-Archive places each input file at the
    # archive root by default which is exactly what Lambda needs).
    $zipPath = Join-Path $tmpDir "$($t.Tag).zip"
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Compress-Archive -Path $srcPaths -DestinationPath $zipPath -Force
    $zipBytes = (Get-Item $zipPath).Length
    Write-Host "  built:  $zipPath ($zipBytes bytes, $($srcPaths.Count) file(s))" -ForegroundColor Gray

    if ($DryRun) {
        Write-Host "  [dry-run] skipping upload" -ForegroundColor Yellow
        continue
    }

    # update-function-code uploads the zip and returns immediately with
    # State=Pending. We then wait for State=Active before the next call —
    # otherwise a second update can race with the still-in-flight one.
    Write-Host "  uploading..." -ForegroundColor Cyan
    $uploadJson = aws lambda update-function-code `
        --function-name $name `
        --region $Region `
        --zip-file "fileb://$zipPath" `
        --output json 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [error] update-function-code failed: $uploadJson" -ForegroundColor Red
        exit 1
    }

    Write-Host "  waiting for Active..." -ForegroundColor Gray
    aws lambda wait function-updated --function-name $name --region $Region
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [warn] wait function-updated returned non-zero (lambda may still be active)" -ForegroundColor Yellow
    }

    $afterJson = aws lambda get-function-configuration `
        --function-name $name `
        --region $Region `
        --query "{LastModified:LastModified,CodeSize:CodeSize,CodeSha256:CodeSha256}" `
        --output json
    $after = $afterJson | ConvertFrom-Json
    Write-Host "  after:  $($after.LastModified) | $($after.CodeSize) bytes | sha256=$($after.CodeSha256.Substring(0,12))..." -ForegroundColor Green

    if ($before.CodeSha256 -eq $after.CodeSha256) {
        Write-Host "  [warn] CodeSha256 did NOT change — upload likely a no-op (identical bytes)" -ForegroundColor Yellow
    } else {
        Write-Host "  [ok] CodeSha256 changed — deploy confirmed" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Magenta
Write-Host "  Done." -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Magenta
