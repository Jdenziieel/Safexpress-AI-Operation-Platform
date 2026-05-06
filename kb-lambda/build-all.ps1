# =============================================================================
# Quick Build & Deploy - Builds all Lambda functions and optionally deploys
# =============================================================================
# Usage:
#   .\build-all.ps1              # Build all functions
#   .\build-all.ps1 -Deploy      # Build and deploy all
#   .\build-all.ps1 -Group kb    # Build only kb functions
#   .\build-all.ps1 -Group chat  # Build only chat functions
# =============================================================================

param(
    [ValidateSet("all", "kb", "chat", "admin", "websocket", "utility")]
    [string]$Group = "all",
    [switch]$Deploy,
    [switch]$Clean,
    [string]$Region = "us-east-1"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║            KB-Lambda Build & Deploy (Docker/Linux)                   ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Group mappings
$Groups = @{
    "all" = @()  # Will be handled by -All flag
    "kb" = @("kb_delete", "kb_list", "kb_query", "kb_upload", "kb_versions")
    "chat" = @("chat_message", "chat_quota", "chat_sessions", "chat_session_create", "chat_session_update")
    "admin" = @("admin_documents", "admin_health", "admin_stats")
    "websocket" = @("ws_chat_stream", "ws_connect", "ws_default", "ws_disconnect")
    "utility" = @("pdf_parse")
}

# Build
Write-Host "Step 1: Building Lambda packages..." -ForegroundColor Yellow
Write-Host ""

$BuildArgs = @()
if ($Clean) { $BuildArgs += "-Clean" }

if ($Group -eq "all") {
    $BuildArgs += "-All"
} else {
    $BuildArgs += "-Function"
    $BuildArgs += ($Groups[$Group] -join ",")
}

& "$ScriptDir\build-lambda-docker.ps1" @BuildArgs

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Build failed! Stopping." -ForegroundColor Red
    exit 1
}

# Deploy if requested
if ($Deploy) {
    Write-Host ""
    Write-Host "Step 2: Deploying to AWS Lambda..." -ForegroundColor Yellow
    Write-Host ""
    
    $DeployArgs = @("-Region", $Region)
    
    if ($Group -eq "all") {
        $DeployArgs += "-All"
    } else {
        $DeployArgs += "-Function"
        $DeployArgs += ($Groups[$Group] -join ",")
    }
    
    & "$ScriptDir\deploy-lambda.ps1" @DeployArgs
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "Deployment failed!" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  All operations completed successfully!" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
