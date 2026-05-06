# Quota Lambda Build Script - Creates Separate ZIP files for each function
# Usage: .\build-lambda.ps1 [-Function <name1,name2,...>]
# Examples:
#   .\build-lambda.ps1                    # Build all functions
#   .\build-lambda.ps1 -Function quota-check,quota-usage  # Build specific functions

param(
    [string]$Function = ""  # Comma-separated list of function names to build
)

Write-Host ''
Write-Host '=== Quota Lambda Build Script ===' -ForegroundColor Cyan
Write-Host 'Building separate ZIP for each Lambda function...'
Write-Host ''

# Check Docker
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host 'ERROR: Docker not found. Please install Docker Desktop.' -ForegroundColor Red
    exit 1
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Create dist folder
$distFolder = Join-Path $scriptDir "dist"
if (-not (Test-Path $distFolder)) {
    New-Item -ItemType Directory -Path $distFolder | Out-Null
}

# Parse function filter
$functionFilter = @()
if ($Function -ne "") {
    $functionFilter = $Function.Split(',') | ForEach-Object { $_.Trim() }
    Write-Host "Building only: $($functionFilter -join ', ')" -ForegroundColor Yellow
    Write-Host ''
} else {
    # Clean old ZIPs only when building all
    Remove-Item "$distFolder\*.zip" -Force -ErrorAction SilentlyContinue
}

# Lambda functions to build
$allFunctions = @(
    @{ Name = "quota-check"; File = "lambda_quota_check.py" },
    @{ Name = "quota-balance"; File = "lambda_quota_balance.py" },
    @{ Name = "quota-report"; File = "lambda_quota_report.py" },
    @{ Name = "quota-usage"; File = "lambda_quota_usage.py" },
    @{ Name = "quota-health"; File = "lambda_health.py" },
    @{ Name = "admin-create-user"; File = "lambda_admin_create_user.py" },
    @{ Name = "admin-list-users"; File = "lambda_admin_list_users.py" },
    @{ Name = "admin-get-user"; File = "lambda_admin_get_user.py" },
    @{ Name = "admin-update-user"; File = "lambda_admin_update_user.py" },
    @{ Name = "admin-reset-usage"; File = "lambda_admin_reset_usage.py" },
    @{ Name = "admin-deactivate"; File = "lambda_admin_deactivate.py" },
    @{ Name = "admin-restore"; File = "lambda_admin_restore.py" },
    @{ Name = "admin-summary"; File = "lambda_admin_summary.py" },
    @{ Name = "admin-logs"; File = "lambda_admin_logs.py" },
    @{ Name = "admin-actions"; File = "lambda_admin_actions.py" },
    @{ Name = "admin-usage-breakdown"; File = "lambda_admin_usage_breakdown.py" },
    @{ Name = "admin-top-users"; File = "lambda_admin_top_users.py" },
    # Added 2026-05-01:
    #   scheduled-reset → EventBridge cron(5 0 * * ? *) — guaranteed monthly reset
    #   user-history    → GET /api/quota/me/history — Profile page consumption tab
    @{ Name = "scheduled-reset"; File = "lambda_scheduled_reset.py" },
    @{ Name = "user-history"; File = "lambda_user_history.py" }
)

# Filter functions if specified
if ($functionFilter.Count -gt 0) {
    $functions = $allFunctions | Where-Object { $functionFilter -contains $_.Name }
    if ($functions.Count -eq 0) {
        Write-Host "ERROR: No matching functions found. Available: $($allFunctions.Name -join ', ')" -ForegroundColor Red
        exit 1
    }
} else {
    $functions = $allFunctions
}

Write-Host '[1/3] Building base Docker image with dependencies...' -ForegroundColor Yellow

# Create base Dockerfile
$baseDockerfile = @"
FROM public.ecr.aws/lambda/python:3.11
WORKDIR /build
RUN yum install -y zip
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -t /build/deps
"@
$baseDockerfile | Out-File -FilePath "Dockerfile.base" -Encoding ASCII

docker build -f Dockerfile.base -t quota-lambda-base:latest . 2>&1 | Out-Null

if ($LASTEXITCODE -ne 0) {
    Write-Host 'ERROR: Base image build failed!' -ForegroundColor Red
    Remove-Item "Dockerfile.base" -Force -ErrorAction SilentlyContinue
    exit 1
}

Write-Host '[2/3] Building individual Lambda packages...' -ForegroundColor Yellow
Write-Host ''

$successCount = 0
$failCount = 0

foreach ($fn in $functions) {
    $name = $fn.Name
    $file = $fn.File
    $zipName = "quota-$name.zip"
    
    Write-Host "  Building $name..." -NoNewline
    
    # Create temp Dockerfile for this function
    $tempDockerfile = @"
FROM quota-lambda-base:latest
COPY $file /build/deps/lambda_function.py
RUN cd /build/deps && zip -r /build/$zipName .
"@
    $tempDockerfile | Out-File -FilePath "Dockerfile.temp" -Encoding ASCII
    
    # Build
    docker build -f Dockerfile.temp -t "quota-lambda-$name`:latest" . 2>&1 | Out-Null
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host ' FAILED (build)' -ForegroundColor Red
        $failCount++
        continue
    }
    
    # Extract ZIP using docker cp
    docker create --name temp-container "quota-lambda-$name`:latest" 2>&1 | Out-Null
    docker cp "temp-container:/build/$zipName" "$distFolder\$zipName" 2>&1 | Out-Null
    docker rm temp-container 2>&1 | Out-Null
    
    # Verify
    $zipPath = Join-Path $distFolder $zipName
    if ((Test-Path $zipPath) -and ((Get-Item $zipPath).Length -gt 1000000)) {
        $sizeMB = [math]::Round((Get-Item $zipPath).Length / 1MB, 2)
        Write-Host " OK ($sizeMB MB)" -ForegroundColor Green
        $successCount++
    } else {
        Write-Host ' FAILED (extract)' -ForegroundColor Red
        $failCount++
    }
}

# Cleanup
Remove-Item "Dockerfile.base" -Force -ErrorAction SilentlyContinue
Remove-Item "Dockerfile.temp" -Force -ErrorAction SilentlyContinue

Write-Host ''
Write-Host '[3/3] Build Summary' -ForegroundColor Yellow
Write-Host "  Success: $successCount" -ForegroundColor Green
Write-Host "  Failed:  $failCount" -ForegroundColor $(if ($failCount -gt 0) { 'Red' } else { 'Green' })
Write-Host ''

if ($successCount -gt 0) {
    Write-Host 'ZIP files ready in dist/ folder:' -ForegroundColor Cyan
    Get-ChildItem $distFolder -Filter "*.zip" | ForEach-Object {
        $sizeMB = [math]::Round($_.Length / 1MB, 2)
        Write-Host "  $($_.Name) ($sizeMB MB)" -ForegroundColor White
    }
    Write-Host ''
    Write-Host 'Upload each ZIP to corresponding Lambda function in AWS Console.' -ForegroundColor Yellow
}

exit $failCount
