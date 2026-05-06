# =============================================================================
# Build Lambda Functions Using Docker (Linux/Amazon Linux 2023 Compatible)
# =============================================================================

param(
    [string[]]$Function,
    [switch]$All,
    [switch]$List,
    [switch]$Clean,
    [switch]$NoCache,
    [switch]$KeepImages,
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$FunctionsDir = Join-Path $ScriptDir "functions"
$DistDir = Join-Path $ScriptDir "dist"

# All available Lambda functions
$AllFunctions = @(
    "admin_documents",
    "admin_health", 
    "admin_stats",
    "chat_message",
    "chat_quota",
    "chat_sessions",
    "chat_session_create",
    "chat_session_update",
    "kb_delete",
    "kb_list",
    "kb_query",
    "kb_upload",
    "kb_versions",
    "pdf_parse",
    "ws_chat_stream",
    "ws_connect",
    "ws_default",
    "ws_disconnect"
)

# Function categories
$FunctionGroups = @{
    "kb" = @("kb_delete", "kb_list", "kb_query", "kb_upload", "kb_versions")
    "chat" = @("chat_message", "chat_quota", "chat_sessions", "chat_session_create", "chat_session_update")
    "admin" = @("admin_documents", "admin_health", "admin_stats")
    "websocket" = @("ws_chat_stream", "ws_connect", "ws_default", "ws_disconnect")
    "utility" = @("pdf_parse")
}

function Write-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor Cyan
}

function Write-Step {
    param([string]$Text)
    Write-Host "  -> $Text" -ForegroundColor Yellow
}

function Write-Success {
    param([string]$Text)
    Write-Host "  [OK] $Text" -ForegroundColor Green
}

function Write-Error {
    param([string]$Text)
    Write-Host "  [ERROR] $Text" -ForegroundColor Red
}

function Test-DockerRunning {
    try {
        $null = docker version 2>&1
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Build-LambdaFunction {
    param(
        [string]$FunctionName,
        [switch]$NoCache,
        [switch]$KeepImages
    )
    
    $StartTime = Get-Date
    $ImageName = "lambda-builder-$FunctionName"
    $ZipName = "$FunctionName.zip"
    $OutputPath = Join-Path $DistDir $ZipName
    
    Write-Host ""
    Write-Host "Building: $FunctionName" -ForegroundColor Magenta
    Write-Host ("-" * 50)
    
    # Check function exists
    $FunctionPath = Join-Path $FunctionsDir $FunctionName
    if (-not (Test-Path $FunctionPath)) {
        Write-Error "Function folder not found: $FunctionPath"
        return @{ Success = $false; Function = $FunctionName; Error = "Folder not found" }
    }
    
    # Build Docker image
    Write-Step "Building Docker image..."
    $BuildArgs = @(
        "build",
        "--build-arg", "FUNCTION_NAME=$FunctionName",
        "-f", "Dockerfile.lambda",
        "-t", $ImageName,
        "--target", "builder",
        "."
    )
    
    if ($NoCache) {
        $BuildArgs += "--no-cache"
    }
    
    if ($Verbose) {
        & docker @BuildArgs
    } else {
        & docker @BuildArgs 2>&1 | Out-Null
    }
    
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Docker build failed"
        return @{ Success = $false; Function = $FunctionName; Error = "Docker build failed" }
    }
    Write-Success "Docker image built"
    
    # Extract ZIP from container
    Write-Step "Extracting deployment package..."
    $ContainerId = docker create $ImageName
    
    # Remove existing zip if present
    if (Test-Path $OutputPath) {
        Remove-Item $OutputPath -Force
    }
    
    docker cp "${ContainerId}:/build/lambda-function.zip" $OutputPath
    docker rm $ContainerId | Out-Null
    
    if (-not (Test-Path $OutputPath)) {
        Write-Error "Failed to extract ZIP file"
        return @{ Success = $false; Function = $FunctionName; Error = "ZIP extraction failed" }
    }
    Write-Success "Package extracted"
    
    # Get file size
    $ZipSize = (Get-Item $OutputPath).Length
    $ZipSizeMB = [math]::Round($ZipSize / 1MB, 2)
    
    # Cleanup Docker image
    if (-not $KeepImages) {
        docker rmi $ImageName -f 2>&1 | Out-Null
    }
    
    $Duration = (Get-Date) - $StartTime
    $DurationSec = [math]::Round($Duration.TotalSeconds, 1)
    
    Write-Success "Complete! Size: $ZipSizeMB MB, Time: ${DurationSec}s"
    
    return @{
        Success = $true
        Function = $FunctionName
        ZipPath = $OutputPath
        SizeMB = $ZipSizeMB
        DurationSec = $DurationSec
    }
}

# =============================================================================
# Main Script
# =============================================================================

Write-Header "KB-Lambda Docker Build System"

# Check Docker is running
if (-not (Test-DockerRunning)) {
    Write-Error "Docker is not running. Please start Docker Desktop first."
    exit 1
}
Write-Success "Docker is running"

# Handle -List parameter
if ($List) {
    Write-Host ""
    Write-Host "Available Lambda Functions:" -ForegroundColor Cyan
    Write-Host ""
    
    foreach ($Group in $FunctionGroups.Keys | Sort-Object) {
        Write-Host "  $($Group.ToUpper()):" -ForegroundColor Yellow
        foreach ($Func in $FunctionGroups[$Group]) {
            Write-Host "    - $Func" -ForegroundColor White
        }
    }
    
    Write-Host ""
    Write-Host "Usage Examples:" -ForegroundColor Cyan
    Write-Host "  .\build-lambda-docker.ps1 -Function kb_list" -ForegroundColor Gray
    Write-Host "  .\build-lambda-docker.ps1 -All" -ForegroundColor Gray
    exit 0
}

# Create dist directory
if (-not (Test-Path $DistDir)) {
    New-Item -ItemType Directory -Path $DistDir | Out-Null
    Write-Success "Created dist directory"
}

# Handle -Clean parameter
if ($Clean) {
    Write-Step "Cleaning dist folder..."
    Get-ChildItem $DistDir -Filter "*.zip" | Remove-Item -Force
    Write-Success "Dist folder cleaned"
}

# Determine which functions to build
$FunctionsToBuild = @()

if ($All) {
    $FunctionsToBuild = $AllFunctions
} elseif ($Function) {
    foreach ($f in $Function) {
        $FunctionsToBuild += $f.Split(',').Trim()
    }
    
    foreach ($f in $FunctionsToBuild) {
        if ($f -notin $AllFunctions) {
            if ($FunctionGroups.ContainsKey($f.ToLower())) {
                $FunctionsToBuild = $FunctionsToBuild | Where-Object { $_ -ne $f }
                $FunctionsToBuild += $FunctionGroups[$f.ToLower()]
            } else {
                Write-Error "Unknown function: $f"
                Write-Host "Use -List to see available functions" -ForegroundColor Gray
                exit 1
            }
        }
    }
} else {
    Write-Host ""
    Write-Host "No function specified. Use one of:" -ForegroundColor Yellow
    Write-Host "  -Function NAME     Build specific function" -ForegroundColor Gray
    Write-Host "  -All               Build all functions" -ForegroundColor Gray
    Write-Host "  -List              List available functions" -ForegroundColor Gray
    Write-Host ""
    exit 0
}

# Remove duplicates
$FunctionsToBuild = $FunctionsToBuild | Select-Object -Unique

Write-Host ""
Write-Host "Functions to build: $($FunctionsToBuild.Count)" -ForegroundColor Cyan
Write-Host "  $($FunctionsToBuild -join ', ')" -ForegroundColor Gray

# Build each function
$Results = @()
$TotalStart = Get-Date

foreach ($FuncName in $FunctionsToBuild) {
    $Result = Build-LambdaFunction -FunctionName $FuncName -NoCache:$NoCache -KeepImages:$KeepImages
    $Results += $Result
}

# Summary
$TotalDuration = (Get-Date) - $TotalStart
$SuccessCount = ($Results | Where-Object { $_.Success }).Count
$FailCount = ($Results | Where-Object { -not $_.Success }).Count

Write-Header "Build Summary"

Write-Host ""
Write-Host "Results:" -ForegroundColor Cyan

foreach ($Result in $Results) {
    if ($Result.Success) {
        Write-Host "  [OK] $($Result.Function)" -ForegroundColor Green -NoNewline
        Write-Host " - $($Result.SizeMB) MB" -ForegroundColor Gray
    } else {
        Write-Host "  [FAIL] $($Result.Function)" -ForegroundColor Red -NoNewline
        Write-Host " - $($Result.Error)" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "Total: $SuccessCount succeeded, $FailCount failed" -ForegroundColor $(if ($FailCount -eq 0) { "Green" } else { "Yellow" })
Write-Host "Time: $([math]::Round($TotalDuration.TotalSeconds, 1)) seconds" -ForegroundColor Gray
Write-Host "Output: $DistDir" -ForegroundColor Gray

if ($FailCount -gt 0) {
    exit 1
}
