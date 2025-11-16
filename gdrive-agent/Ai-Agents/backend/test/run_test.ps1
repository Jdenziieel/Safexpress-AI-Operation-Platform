# Test Runner Script for Google Drive Agent (PowerShell)
# Works with backend/test/ folder structure

param(
    [Parameter(Position=0)]
    [string]$TestType = "all"
)

# Colors for output
function Write-ColorOutput($ForegroundColor) {
    $fc = $host.UI.RawUI.ForegroundColor
    $host.UI.RawUI.ForegroundColor = $ForegroundColor
    if ($args) {
        Write-Output $args
    }
    $host.UI.RawUI.ForegroundColor = $fc
}

Write-Host "🧪 Google Drive Agent Test Suite" -ForegroundColor Cyan
Write-Host "==================================" -ForegroundColor Cyan
Write-Host ""

# Check if pytest is installed
try {
    $null = Get-Command pytest -ErrorAction Stop
} catch {
    Write-ColorOutput Red "❌ pytest not found. Installing test requirements..."
    pip install -r requirements.txt
}

# Execute based on test type
switch ($TestType.ToLower()) {
    "all" {
        Write-ColorOutput Blue "📋 Running all tests..."
        pytest test_drive_agent.py -v --tb=short
        break
    }
    
    "quick" {
        Write-ColorOutput Blue "⚡ Running quick tests (no coverage)..."
        pytest test_drive_agent.py -v --tb=short -x
        break
    }
    
    "coverage" {
        Write-ColorOutput Blue "📊 Running tests with coverage..."
        pytest test_drive_agent.py -v --cov=.. --cov-report=html --cov-report=term-missing
        Write-Host ""
        Write-ColorOutput Green "✅ Coverage report generated at: htmlcov/index.html"
        break
    }
    
    "unit" {
        Write-ColorOutput Blue "🔬 Running unit tests only..."
        pytest test_drive_agent.py::TestToolsFunctions -v --tb=short
        pytest test_drive_agent.py::TestAPITools -v --tb=short
        break
    }
    
    "integration" {
        Write-ColorOutput Blue "🔗 Running integration tests only..."
        pytest test_drive_agent.py::TestIntegration -v --tb=short
        break
    }
    
    "errors" {
        Write-ColorOutput Blue "🐛 Running error handling tests..."
        pytest test_drive_agent.py::TestErrorHandling -v --tb=short
        break
    }
    
    "watch" {
        Write-ColorOutput Blue "👀 Running tests in watch mode..."
        try {
            $null = Get-Command pytest-watch -ErrorAction Stop
        } catch {
            Write-ColorOutput Yellow "⚠️  pytest-watch not installed. Installing..."
            pip install pytest-watch
        }
        pytest-watch test_drive_agent.py -v --tb=short
        break
    }
    
    "failed" {
        Write-ColorOutput Blue "🔄 Re-running last failed tests..."
        pytest test_drive_agent.py -v --lf --tb=short
        break
    }
    
    "debug" {
        Write-ColorOutput Blue "🔍 Running tests in debug mode (with prints)..."
        pytest test_drive_agent.py -v -s --tb=long
        break
    }
    
    {$_ -in "help", "-h", "--help"} {
        Write-Host "Usage: .\run_tests.ps1 [TEST_TYPE]"
        Write-Host ""
        Write-Host "Test Types:"
        Write-Host "  all         - Run all tests (default)"
        Write-Host "  quick       - Run all tests, stop on first failure"
        Write-Host "  coverage    - Run with coverage report"
        Write-Host "  unit        - Run unit tests only"
        Write-Host "  integration - Run integration tests only"
        Write-Host "  errors      - Run error handling tests only"
        Write-Host "  watch       - Run in watch mode (re-run on file changes)"
        Write-Host "  failed      - Re-run only failed tests from last run"
        Write-Host "  debug       - Run with verbose output and print statements"
        Write-Host "  help        - Show this help message"
        Write-Host ""
        Write-Host "Examples:"
        Write-Host "  .\run_tests.ps1 all"
        Write-Host "  .\run_tests.ps1 coverage"
        Write-Host "  .\run_tests.ps1 unit"
        Write-Host ""
        Write-Host "Note: Run this script from the backend/test directory"
        exit 0
        break
    }
    
    default {
        Write-ColorOutput Red "❌ Unknown test type: $TestType"
        Write-Host "Run '.\run_tests.ps1 help' for usage information"
        exit 1
    }
}

# Check exit code
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-ColorOutput Green "✅ All tests passed!"
    exit 0
} else {
    Write-Host ""
    Write-ColorOutput Red "❌ Some tests failed. Run '.\run_tests.ps1 debug' for more details."
    exit 1
}