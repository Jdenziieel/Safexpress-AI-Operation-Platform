# Build kb-upload Lambda using Docker for Linux compatibility
# This ensures pydantic and other binary dependencies are compiled for Amazon Linux

param(
    [switch]$NoBuild,
    [switch]$NoClean
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "=" * 60 -ForegroundColor Cyan
Write-Host "Building kb-upload Lambda with Docker" -ForegroundColor Cyan
Write-Host "=" * 60 -ForegroundColor Cyan

# Check if Docker is running
try {
    docker version | Out-Null
} catch {
    Write-Host "ERROR: Docker is not running. Please start Docker Desktop." -ForegroundColor Red
    exit 1
}

$ImageName = "kb-upload-builder"
$OutputDir = Join-Path $ScriptDir "dist"

# Create output directory
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

if (-not $NoBuild) {
    Write-Host "`nBuilding Docker image..." -ForegroundColor Yellow
    docker build -f Dockerfile.kb-upload -t $ImageName . --target builder
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Docker build failed" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "`nExtracting ZIP file..." -ForegroundColor Yellow
    $ContainerId = docker create $ImageName
    docker cp "${ContainerId}:/build/kb-upload.zip" "$OutputDir/kb-upload.zip"
    docker rm $ContainerId | Out-Null
}

if (Test-Path "$OutputDir/kb-upload.zip") {
    $ZipSize = (Get-Item "$OutputDir/kb-upload.zip").Length / 1MB
    Write-Host "`nBuild complete!" -ForegroundColor Green
    Write-Host "Output: $OutputDir\kb-upload.zip" -ForegroundColor Cyan
    Write-Host "Size: $([math]::Round($ZipSize, 2)) MB" -ForegroundColor Cyan
}

if (-not $NoClean) {
    Write-Host "`nCleaning up..." -ForegroundColor Yellow
    docker rmi $ImageName -f | Out-Null
}

Write-Host "`nNext steps:" -ForegroundColor Yellow
Write-Host "1. Upload dist/kb-upload.zip to Lambda kb-upload function" -ForegroundColor White
Write-Host "2. Verify handler is: lambda_kb_upload.lambda_handler" -ForegroundColor White
Write-Host "3. Test the upload endpoint" -ForegroundColor White
