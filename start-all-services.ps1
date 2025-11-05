# Start All AI Agent Services
# Run this script from the Ai-Agents root directory

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Starting AI Agent System" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if we're in the correct directory
if (-not (Test-Path ".\gmail-agent") -or -not (Test-Path ".\supervisor-agent") -or -not (Test-Path ".\Capstone")) {
    Write-Host "❌ Error: Please run this script from the Ai-Agents root directory" -ForegroundColor Red
    Write-Host "Current directory: $(Get-Location)" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ Found all required directories" -ForegroundColor Green
Write-Host ""

# Function to start a service in a new terminal
function Start-Service {
    param(
        [string]$Name,
        [string]$Path,
        [string]$Command,
        [string]$Color
    )
    
    Write-Host "🚀 Starting $Name..." -ForegroundColor $Color
    
    # Start in new PowerShell window
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Path'; Write-Host '========================================' -ForegroundColor $Color; Write-Host '  $Name' -ForegroundColor $Color; Write-Host '========================================' -ForegroundColor $Color; Write-Host ''; $Command"
    
    Write-Host "   ✓ $Name terminal opened" -ForegroundColor Green
    Start-Sleep -Seconds 2
}

# Start Gmail Agent (Port 8001)
Start-Service -Name "Gmail Agent" -Path "$PSScriptRoot\gmail-agent" -Command "python api.py" -Color "Yellow"

# Start Supervisor Agent (Port 8000)
Start-Service -Name "Supervisor Agent" -Path "$PSScriptRoot\supervisor-agent" -Command "python supervisor_agent.py" -Color "Magenta"

# Wait a bit for backend to initialize
Write-Host ""
Write-Host "⏳ Waiting for backend services to initialize..." -ForegroundColor Cyan
Start-Sleep -Seconds 3

# Start Frontend (Port 5173)
Start-Service -Name "React Frontend" -Path "$PSScriptRoot\Capstone" -Command "npm run dev" -Color "Blue"

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  ✅ All Services Started!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "📡 Services:" -ForegroundColor Cyan
Write-Host "   - Gmail Agent:      http://localhost:8001" -ForegroundColor Yellow
Write-Host "   - Supervisor Agent: http://localhost:8000" -ForegroundColor Magenta
Write-Host "   - Frontend:         http://localhost:5173" -ForegroundColor Blue
Write-Host ""
Write-Host "📚 Documentation:" -ForegroundColor Cyan
Write-Host "   - Gmail API:        http://localhost:8001/docs" -ForegroundColor Yellow
Write-Host "   - Supervisor API:   http://localhost:8000/docs" -ForegroundColor Magenta
Write-Host ""
Write-Host "🧪 Ready for testing!" -ForegroundColor Green
Write-Host "   Open your browser to: http://localhost:5173" -ForegroundColor Blue
Write-Host ""
Write-Host "📖 Test prompts:" -ForegroundColor Cyan
Write-Host "   Test 1: 'Search my emails and show me 4 recent emails'" -ForegroundColor White
Write-Host "   Test 2: 'Search my recent emails, then forward the first one to test@example.com'" -ForegroundColor White
Write-Host ""
Write-Host "Press any key to exit this window..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
