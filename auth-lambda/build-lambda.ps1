# Auth Lambda Build Script - Creates Separate ZIP files for each function
# Usage: .\build-lambda.ps1

Write-Host ''
Write-Host '=== Auth Lambda Build Script ===' -ForegroundColor Cyan
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

# Clean old ZIPs
Remove-Item "$distFolder\*.zip" -Force -ErrorAction SilentlyContinue

# Lambda functions to build
$functions = @(
    @{ Name = "google-login"; File = "lambda_google_login.py" },
    @{ Name = "token-refresh"; File = "lambda_token_refresh.py" },
    @{ Name = "user-detail"; File = "lambda_user_detail.py" },
    @{ Name = "onboard-user"; File = "lambda_onboard_user.py" },
    @{ Name = "list-users"; File = "lambda_list_users.py" },
    @{ Name = "update-user"; File = "lambda_update_user.py" },
    @{ Name = "deactivate-user"; File = "lambda_deactivate_user.py" },
    @{ Name = "activity-logs"; File = "lambda_activity_logs.py" },
    @{ Name = "accept-terms"; File = "lambda_accept_terms.py" }
)

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

docker build -f Dockerfile.base -t auth-lambda-base:latest . 2>&1 | Out-Null

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
    $zipName = "auth-$name.zip"
    
    Write-Host "  Building $name..." -NoNewline
    
    # Create temp Dockerfile for this function
    $tempDockerfile = @"
FROM auth-lambda-base:latest
COPY $file /build/deps/lambda_function.py
RUN cd /build/deps && zip -r /build/$zipName .
"@
    $tempDockerfile | Out-File -FilePath "Dockerfile.temp" -Encoding ASCII
    
    # Build
    docker build -f Dockerfile.temp -t "auth-lambda-$name`:latest" . 2>&1 | Out-Null
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host ' FAILED (build)' -ForegroundColor Red
        $failCount++
        continue
    }
    
    # Extract ZIP using docker cp
    docker create --name temp-container "auth-lambda-$name`:latest" 2>&1 | Out-Null
    docker cp "temp-container:/build/$zipName" "$distFolder\$zipName" 2>&1 | Out-Null
    docker rm temp-container 2>&1 | Out-Null
    
    # Verify
    $zipPath = Join-Path $distFolder $zipName
    if ((Test-Path $zipPath) -and ((Get-Item $zipPath).Length -gt 1000000)) {
        $sizeMB = [math]::Round((Get-Item $zipPath).Length / 1MB, 2)
        Write-Host " OK ($sizeMB MB)" -ForegroundColor Green
        $successCount++
    } else {
        Write-Host ' FAILED (zip)' -ForegroundColor Red
        $failCount++
    }
}

# Cleanup
Remove-Item "Dockerfile.base" -Force -ErrorAction SilentlyContinue
Remove-Item "Dockerfile.temp" -Force -ErrorAction SilentlyContinue

Write-Host ''
Write-Host '[3/3] Build Complete!' -ForegroundColor Green
Write-Host ''
Write-Host "  Success: $successCount" -ForegroundColor Green
Write-Host "  Failed:  $failCount" -ForegroundColor $(if ($failCount -gt 0) { 'Red' } else { 'Gray' })
Write-Host ''
Write-Host 'Output files in dist folder:' -ForegroundColor Cyan

Get-ChildItem "$distFolder\*.zip" | ForEach-Object {
    $sizeMB = [math]::Round($_.Length / 1MB, 2)
    Write-Host "  $($_.Name) ($sizeMB MB)"
}

Write-Host ''
Write-Host 'Handler for all functions: lambda_function.lambda_handler' -ForegroundColor Yellow
Write-Host ''
