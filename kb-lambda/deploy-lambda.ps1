# =============================================================================
# Deploy Lambda Functions to AWS
# =============================================================================
# This script deploys built Lambda packages to AWS Lambda.
#
# Prerequisites:
#   - AWS CLI configured with proper credentials
#   - Lambda functions already created in AWS
#   - ZIP files built using build-lambda-docker.ps1
#
# Usage:
#   .\deploy-lambda.ps1 -Function kb_list          # Deploy single function
#   .\deploy-lambda.ps1 -Function kb_list,kb_delete # Deploy multiple
#   .\deploy-lambda.ps1 -All                        # Deploy all built ZIPs
#   .\deploy-lambda.ps1 -List                       # List deployable packages
# =============================================================================

param(
    [string[]]$Function,      # Specific function(s) to deploy
    [switch]$All,             # Deploy all built packages
    [switch]$List,            # List available packages
    [string]$Region = "us-east-1",  # AWS Region
    [string]$Profile,         # AWS CLI profile to use
    [switch]$DryRun           # Show what would be deployed without deploying
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DistDir = Join-Path $ScriptDir "dist"

# Lambda function name mapping (local name -> AWS Lambda name)
# Adjust these to match your actual Lambda function names in AWS
$LambdaNameMap = @{
    "admin_documents"     = "kb-admin-documents"
    "admin_health"        = "kb-admin-health"
    "admin_stats"         = "kb-admin-stats"
    "chat_message"        = "kb-chat-message"
    "chat_quota"          = "kb-chat-quota"
    "chat_sessions"       = "kb-chat-sessions"
    "chat_session_create" = "kb-chat-session-create"
    "chat_session_update" = "kb-chat-session-update"
    "kb_delete"           = "kb-delete"
    "kb_list"             = "kb-list"
    "kb_query"            = "kb-query"
    "kb_upload"           = "kb-upload"
    "kb_versions"         = "kb-versions"
    "pdf_parse"           = "kb-pdf-parse"
    "ws_chat_stream"      = "kb-ws-chat-stream"
    "ws_connect"          = "kb-ws-connect"
    "ws_default"          = "kb-ws-default"
    "ws_disconnect"       = "kb-ws-disconnect"
}

# Handler mapping
$HandlerMap = @{
    "admin_documents"     = "lambda_admin_documents.lambda_handler"
    "admin_health"        = "lambda_admin_health.lambda_handler"
    "admin_stats"         = "lambda_admin_stats.lambda_handler"
    "chat_message"        = "lambda_chat_message.lambda_handler"
    "chat_quota"          = "lambda_chat_quota.lambda_handler"
    "chat_sessions"       = "lambda_chat_sessions.lambda_handler"
    "chat_session_create" = "lambda_chat_session_create.lambda_handler"
    "chat_session_update" = "lambda_chat_session_update.lambda_handler"
    "kb_delete"           = "lambda_kb_delete.lambda_handler"
    "kb_list"             = "lambda_kb_list.lambda_handler"
    "kb_query"            = "lambda_kb_query.lambda_handler"
    "kb_upload"           = "lambda_kb_upload.lambda_handler"
    "kb_versions"         = "lambda_kb_versions.lambda_handler"
    "pdf_parse"           = "lambda_pdf_parse.lambda_handler"
    "ws_chat_stream"      = "lambda_ws_chat_stream.lambda_handler"
    "ws_connect"          = "lambda_ws_connect.lambda_handler"
    "ws_default"          = "lambda_ws_default.lambda_handler"
    "ws_disconnect"       = "lambda_ws_disconnect.lambda_handler"
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
    Write-Host "  → $Text" -ForegroundColor Yellow
}

function Write-Success {
    param([string]$Text)
    Write-Host "  ✓ $Text" -ForegroundColor Green
}

function Write-ErrorMsg {
    param([string]$Text)
    Write-Host "  ✗ $Text" -ForegroundColor Red
}

function Test-AwsCli {
    try {
        $null = aws --version 2>&1
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Get-AvailablePackages {
    if (-not (Test-Path $DistDir)) {
        return @()
    }
    
    $ZipFiles = Get-ChildItem $DistDir -Filter "*.zip"
    return $ZipFiles | ForEach-Object {
        $BaseName = $_.BaseName
        @{
            Name = $BaseName
            Path = $_.FullName
            SizeMB = [math]::Round($_.Length / 1MB, 2)
            LambdaName = $LambdaNameMap[$BaseName]
            Handler = $HandlerMap[$BaseName]
        }
    }
}

function Deploy-LambdaFunction {
    param(
        [string]$FunctionName,
        [string]$ZipPath,
        [string]$LambdaName,
        [string]$Region,
        [string]$Profile,
        [switch]$DryRun
    )
    
    Write-Host ""
    Write-Host "Deploying: $FunctionName → $LambdaName" -ForegroundColor Magenta
    Write-Host ("-" * 50)
    
    if (-not (Test-Path $ZipPath)) {
        Write-ErrorMsg "ZIP file not found: $ZipPath"
        return @{ Success = $false; Function = $FunctionName; Error = "ZIP not found" }
    }
    
    $ZipSize = [math]::Round((Get-Item $ZipPath).Length / 1MB, 2)
    Write-Step "Package size: $ZipSize MB"
    
    if ($DryRun) {
        Write-Step "[DRY RUN] Would deploy to: $LambdaName"
        return @{ Success = $true; Function = $FunctionName; DryRun = $true }
    }
    
    # Build AWS CLI command
    $AwsArgs = @(
        "lambda", "update-function-code",
        "--function-name", $LambdaName,
        "--zip-file", "fileb://$ZipPath",
        "--region", $Region
    )
    
    if ($Profile) {
        $AwsArgs += @("--profile", $Profile)
    }
    
    Write-Step "Uploading to AWS Lambda..."
    
    try {
        $Result = & aws @AwsArgs 2>&1
        
        if ($LASTEXITCODE -ne 0) {
            Write-ErrorMsg "Deployment failed: $Result"
            return @{ Success = $false; Function = $FunctionName; Error = $Result }
        }
        
        Write-Success "Deployed successfully"
        return @{ Success = $true; Function = $FunctionName; LambdaName = $LambdaName }
        
    } catch {
        Write-ErrorMsg "Deployment error: $_"
        return @{ Success = $false; Function = $FunctionName; Error = $_.ToString() }
    }
}

# =============================================================================
# Main Script
# =============================================================================

Write-Header "KB-Lambda AWS Deployment"

# Check AWS CLI
if (-not (Test-AwsCli)) {
    Write-ErrorMsg "AWS CLI is not installed or not in PATH"
    Write-Host "Install from: https://aws.amazon.com/cli/" -ForegroundColor Gray
    exit 1
}
Write-Success "AWS CLI found"

# Get available packages
$Packages = Get-AvailablePackages

if ($Packages.Count -eq 0) {
    Write-ErrorMsg "No deployment packages found in $DistDir"
    Write-Host ""
    Write-Host "Build packages first using:" -ForegroundColor Yellow
    Write-Host "  .\build-lambda-docker.ps1 -All" -ForegroundColor Gray
    exit 1
}

# Handle -List parameter
if ($List) {
    Write-Host ""
    Write-Host "Available Deployment Packages:" -ForegroundColor Cyan
    Write-Host ""
    
    foreach ($Pkg in $Packages) {
        $Status = if ($Pkg.LambdaName) { "→ $($Pkg.LambdaName)" } else { "(no AWS mapping)" }
        Write-Host "  $($Pkg.Name)" -ForegroundColor White -NoNewline
        Write-Host " ($($Pkg.SizeMB) MB) " -ForegroundColor Gray -NoNewline
        Write-Host $Status -ForegroundColor $(if ($Pkg.LambdaName) { "Green" } else { "Yellow" })
    }
    
    Write-Host ""
    Write-Host "Usage:" -ForegroundColor Cyan
    Write-Host "  .\deploy-lambda.ps1 -Function kb_list" -ForegroundColor Gray
    Write-Host "  .\deploy-lambda.ps1 -All" -ForegroundColor Gray
    Write-Host "  .\deploy-lambda.ps1 -Function kb_list -DryRun" -ForegroundColor Gray
    exit 0
}

# Determine which functions to deploy
$ToDeploy = @()

if ($All) {
    $ToDeploy = $Packages
} elseif ($Function) {
    foreach ($f in $Function) {
        foreach ($name in $f.Split(',').Trim()) {
            $Pkg = $Packages | Where-Object { $_.Name -eq $name }
            if ($Pkg) {
                $ToDeploy += $Pkg
            } else {
                Write-ErrorMsg "Package not found for: $name"
                Write-Host "Available: $($Packages.Name -join ', ')" -ForegroundColor Gray
            }
        }
    }
} else {
    Write-Host ""
    Write-Host "No function specified. Use one of:" -ForegroundColor Yellow
    Write-Host "  -Function <name>   Deploy specific function(s)" -ForegroundColor Gray
    Write-Host "  -All               Deploy all built packages" -ForegroundColor Gray
    Write-Host "  -List              List available packages" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Example: .\deploy-lambda.ps1 -Function kb_list" -ForegroundColor Cyan
    exit 0
}

if ($ToDeploy.Count -eq 0) {
    Write-ErrorMsg "No valid packages to deploy"
    exit 1
}

Write-Host ""
Write-Host "Deploying $($ToDeploy.Count) function(s) to region: $Region" -ForegroundColor Cyan
if ($DryRun) {
    Write-Host "[DRY RUN MODE - No actual deployments]" -ForegroundColor Yellow
}

# Deploy each function
$Results = @()

foreach ($Pkg in $ToDeploy) {
    if (-not $Pkg.LambdaName) {
        Write-ErrorMsg "No AWS Lambda name mapping for: $($Pkg.Name)"
        $Results += @{ Success = $false; Function = $Pkg.Name; Error = "No mapping" }
        continue
    }
    
    $Result = Deploy-LambdaFunction `
        -FunctionName $Pkg.Name `
        -ZipPath $Pkg.Path `
        -LambdaName $Pkg.LambdaName `
        -Region $Region `
        -Profile $Profile `
        -DryRun:$DryRun
    
    $Results += $Result
}

# Summary
$SuccessCount = ($Results | Where-Object { $_.Success }).Count
$FailCount = ($Results | Where-Object { -not $_.Success }).Count

Write-Header "Deployment Summary"

Write-Host ""
foreach ($Result in $Results) {
    if ($Result.Success) {
        $Suffix = if ($Result.DryRun) { " [DRY RUN]" } else { "" }
        Write-Host "  ✓ $($Result.Function)$Suffix" -ForegroundColor Green
    } else {
        Write-Host "  ✗ $($Result.Function) - $($Result.Error)" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Total: $SuccessCount succeeded, $FailCount failed" -ForegroundColor $(if ($FailCount -eq 0) { "Green" } else { "Yellow" })

if ($FailCount -gt 0) {
    exit 1
}
