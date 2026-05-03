# Deploys a single Lambda — either by uploading the zip or pointing at an
# ECR image — to AWS. Assumes the function already exists (created via
# CloudFormation or manually). For Lambdas that don't exist yet, run
# `aws lambda create-function ...` once before using this script.
#
# Usage:
#   .\deploy-lambda.ps1 -Function supervisor-list-threads
#   .\deploy-lambda.ps1 -Function agent-mapping -Mode docker -ImageUri 123456789012.dkr.ecr.ap-southeast-1.amazonaws.com/agent-mapping:latest
#
# Flags:
#   -Mode zip|docker     : default "zip" (auto-detected from -ImageUri presence)
#   -ImageUri <uri>      : full ECR URI for docker mode
#   -Region <region>     : default ap-southeast-1

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Function,
    [ValidateSet("zip", "docker")]
    [string]$Mode = "zip",
    [string]$ImageUri = "",
    [string]$Region = "ap-southeast-1",
    [string]$ZipPath = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($Mode -eq "zip") {
    if (-not $ZipPath) { $ZipPath = Join-Path $Root "dist\$Function.zip" }
    if (-not (Test-Path $ZipPath)) { Write-Error "Zip not found: $ZipPath. Run build-lambda.ps1 first."; exit 1 }
    Write-Host "Deploying zip $ZipPath -> Lambda $Function" -ForegroundColor Cyan
    aws lambda update-function-code `
        --function-name $Function `
        --zip-file "fileb://$ZipPath" `
        --region $Region | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "update-function-code failed" }
}
elseif ($Mode -eq "docker") {
    if (-not $ImageUri) { Write-Error "-ImageUri required for -Mode docker"; exit 1 }
    Write-Host "Deploying image $ImageUri -> Lambda $Function" -ForegroundColor Cyan
    aws lambda update-function-code `
        --function-name $Function `
        --image-uri $ImageUri `
        --region $Region | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "update-function-code failed" }
}

# Wait for the update to finish so subsequent config updates don't race
aws lambda wait function-updated --function-name $Function --region $Region | Out-Null

Write-Host "[ok] deployed $Function" -ForegroundColor Green
