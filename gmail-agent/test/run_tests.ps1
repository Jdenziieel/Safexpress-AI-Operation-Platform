# ========================================
# Gmail Agent Test Suite Runner
# ========================================

param(
    [string]$arg1 = "all"
)

# ----------------------------
# Helper Print Functions
# ----------------------------
function Print-Info {
    param ([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Print-Warning {
    param ([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Print-Error {
    param ([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Print-Success {
    param ([string]$Message)
    Write-Host "[SUCCESS] $Message" -ForegroundColor Green
}

# ----------------------------
# Header
# ----------------------------
Write-Host ""
Write-Host "========================================" -ForegroundColor Blue
Write-Host " Gmail Agent Test Suite" -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue
Write-Host ""

# ----------------------------
# Check pytest installation
# ----------------------------
if (Get-Command pytest -ErrorAction SilentlyContinue) {
    Print-Success "pytest found"
} else {
    Print-Error "pytest not found. Please install it using 'pip install pytest'."
    exit 1
}

# ----------------------------
# Determine test scope
# ----------------------------
switch ($arg1.ToLower()) {
    "unit" {
        Print-Info "Running unit tests..."
        pytest -v --maxfail=1 --disable-warnings test_unit\
        if ($LASTEXITCODE -eq 0) {
            Print-Success "All unit tests passed!"
        } else {
            Print-Error "Some unit tests failed."
        }
    }

    "integration" {
        Print-Info "Running integration tests..."
        pytest -v --maxfail=1 --disable-warnings test_integration\
        if ($LASTEXITCODE -eq 0) {
            Print-Success "All integration tests passed!"
        } else {
            Print-Error "Some integration tests failed."
        }
    }

    "all" {
        Print-Info "Running all tests..."
        pytest -v --maxfail=1 --disable-warnings
        if ($LASTEXITCODE -eq 0) {
            Print-Success "All tests passed successfully!"
        } else {
            Print-Error "Some tests failed."
        }
    }

    "help" | "-h" | "--help" {
        Write-Host ""
        Write-Host "Usage:" -ForegroundColor Cyan
        Write-Host "  .\run_tests.ps1 [option]" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Options:" -ForegroundColor Cyan
        Write-Host "  all           Run all test suites (default)" -ForegroundColor Cyan
        Write-Host "  unit          Run only unit tests" -ForegroundColor Cyan
        Write-Host "  integration   Run only integration tests" -ForegroundColor Cyan
        Write-Host "  help, -h      Show this help message" -ForegroundColor Cyan
    }

    default {
        Print-Warning "Unknown argument '$arg1'. Use 'help' for usage info."
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Blue
Write-Host " Test Execution Completed " -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue
Write-Host ""
