# Build pdf-parse Lambda function using Docker for Linux compatibility
# This ensures the package works on AWS Lambda (Amazon Linux)

$ErrorActionPreference = "Stop"

Write-Host "=" * 60 -ForegroundColor Cyan
Write-Host "Building pdf-parse Lambda for Linux (Docker)" -ForegroundColor Cyan
Write-Host "=" * 60 -ForegroundColor Cyan

# Get script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DistDir = Join-Path $ScriptDir "dist"

# Create dist directory if it doesn't exist
if (-not (Test-Path $DistDir)) {
    New-Item -ItemType Directory -Path $DistDir | Out-Null
}

Write-Host "`nStep 1: Building Docker image..." -ForegroundColor Yellow
docker build -f Dockerfile.pdf-parse -t kb-lambda-pdf-parse-builder .

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Docker build failed!" -ForegroundColor Red
    exit 1
}

Write-Host "`nStep 2: Extracting ZIP package..." -ForegroundColor Yellow

# Create a temporary container to copy the ZIP file
$ContainerId = docker create kb-lambda-pdf-parse-builder
docker cp "${ContainerId}:/output/pdf-parse.zip" "$DistDir/pdf-parse.zip"
docker rm $ContainerId | Out-Null

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to extract ZIP file!" -ForegroundColor Red
    exit 1
}

Write-Host "`n" + ("=" * 60) -ForegroundColor Green
Write-Host "✅ Build Complete!" -ForegroundColor Green
Write-Host "=" * 60 -ForegroundColor Green

# Display package info
$ZipFile = Get-Item "$DistDir/pdf-parse.zip"
$SizeMB = [math]::Round($ZipFile.Length / 1MB, 2)

Write-Host "`nPackage Details:" -ForegroundColor Cyan
Write-Host "  File: $($ZipFile.FullName)" -ForegroundColor Gray
Write-Host "  Size: $SizeMB MB" -ForegroundColor Gray
Write-Host "  Built for: Amazon Linux 2 (Lambda Runtime)" -ForegroundColor Gray

if ($SizeMB -gt 50) {
    Write-Host "`n⚠️  WARNING: Package exceeds 50MB" -ForegroundColor Yellow
    Write-Host "   Upload to S3 first, then deploy from S3" -ForegroundColor Yellow
} else {
    Write-Host "`n✅ Package size is under 50MB - can deploy directly" -ForegroundColor Green
}

Write-Host "`nNext Steps:" -ForegroundColor Cyan
Write-Host "  1. Upload to S3 (if > 50MB):" -ForegroundColor Gray
Write-Host "     aws s3 cp dist/pdf-parse.zip s3://your-bucket/lambda/" -ForegroundColor Gray
Write-Host "`n  2. Deploy Lambda function:" -ForegroundColor Gray
Write-Host "     aws lambda update-function-code --function-name pdf-parse \" -ForegroundColor Gray
Write-Host "       --s3-bucket your-bucket --s3-key lambda/pdf-parse.zip" -ForegroundColor Gray
Write-Host ""
