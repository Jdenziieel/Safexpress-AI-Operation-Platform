# Calendar Agent Test Runner for PowerShell
# Convenient script to run tests with various options

param(
    [Parameter(Position=0)]
    [ValidateSet("all", "fast", "unit", "coverage", "debug", "failed", "clean", "help")]
    [string]$Option = "all"
)

# Colors for output
function Write-ColorOutput {
    param(
        [string]$Message,
        [string]$Color = "White"
    )
    Write-Host $Message -ForegroundColor $Color
}

Write-ColorOutput "========================================" "Blue"
Write-ColorOutput "   Calendar Agent Test Suite" "Blue"
Write-ColorOutput "========================================" "Blue"
Write-Host ""

# Check if we're in tests directory
if (-not (Test-Path "test_calendar_agent.py")) {
    if (Test-Path "tests") {
        Write-ColorOutput "Changing to tests directory..." "Yellow"
        Set-Location tests
    } else {
        Write-ColorOutput "Error: Cannot find tests directory" "Red"
        exit 1
    }
}

# Check if pytest is installed
try {
    $null = Get-Command pytest -ErrorAction Stop
} catch {
    Write-ColorOutput "Error: pytest is not installed" "Red"
    Write-ColorOutput "Install with: pip install -r requirements.txt" "Yellow"
    exit 1
}

# Execute based on option
switch ($Option) {
    "all" {
        Write-ColorOutput "Running all tests..." "Green"
        pytest -v
    }
    
    "fast" {
        Write-ColorOutput "Running fast tests only..." "Green"
        pytest -v -m "not slow"
    }
    
    "unit" {
        Write-ColorOutput "Running unit tests only..." "Green"
        pytest -v -m unit
    }
    
    "coverage" {
        Write-ColorOutput "Running tests with coverage..." "Green"
        pytest --cov=../ --cov-report=html --cov-report=term
        Write-Host ""
        Write-ColorOutput "Coverage report generated in htmlcov\index.html" "Blue"
    }
    
    "debug" {
        Write-ColorOutput "Running tests with debugging..." "Green"
        pytest -v -s --pdb
    }
    
    "failed" {
        Write-ColorOutput "Re-running only failed tests..." "Green"
        pytest -v --lf
    }
    
    "clean" {
        Write-ColorOutput "Cleaning test artifacts..." "Yellow"
        Remove-Item -Recurse -Force .pytest_cache, __pycache__, htmlcov, .coverage -ErrorAction SilentlyContinue
        Get-ChildItem -Recurse -Filter "*.pyc" | Remove-Item -Force
        Write-ColorOutput "Clean complete!" "Green"
    }
    
    "help" {
        Write-ColorOutput "Usage: .\run_tests.ps1 [option]" "Blue"
        Write-Host ""
        Write-Host "Options:"
        Write-ColorOutput "  all      " "Green" -NoNewline
        Write-Host "- Run all tests (default)"
        Write-ColorOutput "  fast     " "Green" -NoNewline
        Write-Host "- Run only fast tests"
        Write-ColorOutput "  unit     " "Green" -NoNewline
        Write-Host "- Run only unit tests"
        Write-ColorOutput "  coverage " "Green" -NoNewline
        Write-Host "- Run with coverage report"
        Write-ColorOutput "  debug    " "Green" -NoNewline
        Write-Host "- Run with debugger on failures"
        Write-ColorOutput "  failed   " "Green" -NoNewline
        Write-Host "- Re-run only failed tests"
        Write-ColorOutput "  clean    " "Green" -NoNewline
        Write-Host "- Clean test artifacts"
        Write-ColorOutput "  help     " "Green" -NoNewline
        Write-Host "- Show this help message"
        Write-Host ""
        Write-ColorOutput "Examples:" "Blue"
        Write-Host "  .\run_tests.ps1 all"
        Write-Host "  .\run_tests.ps1 coverage"
        Write-Host "  .\run_tests.ps1 unit"
    }
}

# Exit with pytest's exit code (if available)
exit $LASTEXITCODE