# Build WebSocket Lambda functions using Docker for Linux compatibility
# This ensures the packages work on AWS Lambda (Amazon Linux)

param(
    [string]$Function = ""
)

$ErrorActionPreference = "Stop"

Write-Host "=" * 60 -ForegroundColor Cyan
Write-Host "Building WebSocket Lambdas for Linux (Docker)" -ForegroundColor Cyan
Write-Host "=" * 60 -ForegroundColor Cyan

# Get script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DistDir = Join-Path $ScriptDir "dist"

# Create dist directory if it doesn't exist
if (-not (Test-Path $DistDir)) {
    New-Item -ItemType Directory -Path $DistDir | Out-Null
}

# Define WebSocket functions
$AllFunctions = @("ws-connect", "ws-disconnect", "ws-default", "ws-chat-stream")

# Validate function parameter if provided
if ($Function -and $Function -notin $AllFunctions) {
    Write-Host "ERROR: Unknown function '$Function'" -ForegroundColor Red
    Write-Host "Available functions: $($AllFunctions -join ', ')" -ForegroundColor Yellow
    exit 1
}

Write-Host "`nStep 1: Building Docker image..." -ForegroundColor Yellow
docker build -f Dockerfile.websocket -t kb-lambda-websocket-builder .

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Docker build failed!" -ForegroundColor Red
    exit 1
}

Write-Host "`nStep 2: Extracting ZIP packages..." -ForegroundColor Yellow

# Create a temporary container to copy the ZIP files
$ContainerId = docker create kb-lambda-websocket-builder

# Determine which functions to extract
$FunctionsToExtract = if ($Function) { @($Function) } else { $AllFunctions }

$ExtractedCount = 0
foreach ($FuncName in $FunctionsToExtract) {
    Write-Host "  Extracting $FuncName.zip..." -ForegroundColor Gray
    
    docker cp "${ContainerId}:/build/$FuncName.zip" "$DistDir/$FuncName.zip"
    
    if ($LASTEXITCODE -eq 0) {
        $ExtractedCount++
    } else {
        Write-Host "  ⚠️  Failed to extract $FuncName.zip" -ForegroundColor Yellow
    }
}

docker rm $ContainerId | Out-Null

if ($ExtractedCount -eq 0) {
    Write-Host "ERROR: Failed to extract any ZIP files!" -ForegroundColor Red
    exit 1
}

Write-Host "`n" + ("=" * 60) -ForegroundColor Green
Write-Host "✅ Build Complete!" -ForegroundColor Green
Write-Host "=" * 60 -ForegroundColor Green

# Display package info
Write-Host "`nPackage Details:" -ForegroundColor Cyan
foreach ($FuncName in $FunctionsToExtract) {
    $ZipPath = Join-Path $DistDir "$FuncName.zip"
    if (Test-Path $ZipPath) {
        $ZipFile = Get-Item $ZipPath
        $SizeMB = [math]::Round($ZipFile.Length / 1MB, 2)
        Write-Host "  $FuncName : $SizeMB MB" -ForegroundColor Gray
        
        if ($SizeMB -gt 50) {
            Write-Host "    ⚠️  > 50MB - Upload to S3 first" -ForegroundColor Yellow
        }
    }
}

Write-Host "`nBuilt for: Amazon Linux 2 (Lambda Runtime)" -ForegroundColor Gray
Write-Host "`nNext Steps:" -ForegroundColor Cyan
Write-Host "  1. Upload to S3:" -ForegroundColor Gray
Write-Host "     aws s3 cp dist/ws-connect.zip s3://your-bucket/lambda/" -ForegroundColor DarkGray
Write-Host "`n  2. Deploy Lambda:" -ForegroundColor Gray
Write-Host "     aws lambda update-function-code --function-name kb-ws-connect \" -ForegroundColor DarkGray
Write-Host "       --s3-bucket your-bucket --s3-key lambda/ws-connect.zip" -ForegroundColor DarkGray
