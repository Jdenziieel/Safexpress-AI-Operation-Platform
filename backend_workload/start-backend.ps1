# ============================================================================
# Workload Analysis Backend - Startup Script
# ============================================================================

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Workload Analysis Backend Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Navigate to backend directory
$backendPath = "c:\Users\Carlos Miguel Carla\Documents\GitHub\CAPSTONEPROJECT\backend_workload"
Set-Location $backendPath

Write-Host "[1/3] Checking Python installation..." -ForegroundColor Yellow
python --version
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Python not found! Please install Python 3.8 or higher." -ForegroundColor Red
    exit 1
}
Write-Host "✅ Python is installed" -ForegroundColor Green
Write-Host ""

Write-Host "[2/3] Installing dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to install dependencies!" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Dependencies installed successfully" -ForegroundColor Green
Write-Host ""

Write-Host "[3/3] Starting backend server..." -ForegroundColor Yellow
Write-Host "Backend will run on: http://localhost:5002" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Gray
Write-Host ""

python app.py
