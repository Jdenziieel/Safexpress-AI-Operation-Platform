# Builds a single Docker-based Lambda image and pushes it to ECR.
#
# Usage:
#   .\build-lambda-docker.ps1 -Function supervisor-create-thread -EcrRepo supervisor-create-thread
#   .\build-lambda-docker.ps1 -Function agent-mapping -EcrRepo agent-mapping -Region ap-southeast-1
#
# Flags:
#   -SkipPush        : build only, don't push to ECR
#   -Tag <string>    : image tag (default: "latest")
#
# Picks the right Dockerfile based on Function name:
#   - agent-gmail       -> Dockerfile.gmail-agent
#   - agent-docs        -> Dockerfile.docs-agent
#   - agent-sheets      -> Dockerfile.sheets-agent
#   - agent-calendar    -> Dockerfile.calendar-agent
#   - agent-drive       -> Dockerfile.drive-agent
#   - agent-mapping     -> Dockerfile.mapping-agent
#   - supervisor-ws-chat-> Dockerfile.websocket
#   - 5 heavy supervisor-* -> Dockerfile.lambda  (FUNCTION_NAME build-arg)
#
# All 6 agent images are self-contained — they do NOT install the top-level
# `requirements.txt` / `requirements-heavy.txt` and do NOT copy `shared/`.
# This drops ~700 MB of unused wheels (the supervisor brain + LangGraph
# stack) from each agent image vs. the prior Dockerfile.lambda fallthrough.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Function,
    [string]$EcrRepo = "",
    [string]$Region = "ap-southeast-1",
    [string]$Tag = "latest",
    [switch]$SkipPush,
    # Force a clean rebuild ignoring all BuildKit layer cache.
    # Almost never needed in normal use — the layered Dockerfile + the
    # `# syntax=docker/dockerfile:1.6` cache mounts handle invalidation
    # correctly. Pass this when you suspect a stale layer.
    [switch]$NoCache
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

# Image-mode (Docker) is intentionally restricted to the 11 functions
# below. These are the heavy ones whose dependency footprints (LangGraph,
# google-api-client, pandas, etc.) push the ZIP package above 50 MB or
# need OS-level binaries. Every OTHER Lambda is ZIP-packaged via
# build-lambda.ps1 / deploy-lambda.ps1: smaller cold-starts, faster
# iteration, no ECR storage cost, no orphan-repo risk.
#
# If you genuinely need to add a 12th image-mode function, append it
# here AND mirror the matching Dockerfile entry in dockerfileMap below.
# The script aborts EARLY otherwise so an accidental
# `.\build-lambda-docker.ps1 -Function supervisor-XYZ` can't silently
# create a one-off ECR repo and waste ~80 MB of registry storage.
$IMAGE_MODE_FUNCTIONS = @(
    "agent-calendar",
    "agent-docs",
    "agent-drive",
    "agent-gmail",
    "agent-mapping",
    "agent-sheets",
    "supervisor-action-approve",
    "supervisor-create-thread",
    "supervisor-create-thread-upload",
    "supervisor-workflow",
    "supervisor-ws-chat"
)

if ($IMAGE_MODE_FUNCTIONS -notcontains $Function) {
    Write-Host ""
    Write-Host "[refused] '$Function' is NOT an image-mode Lambda." -ForegroundColor Red
    Write-Host "  Image (Docker / ECR) is reserved for these 11 functions only:" -ForegroundColor Yellow
    foreach ($fn in $IMAGE_MODE_FUNCTIONS) { Write-Host "    - $fn" -ForegroundColor Yellow }
    Write-Host ""
    Write-Host "  Use the ZIP path for everything else:" -ForegroundColor Cyan
    Write-Host "    .\build-lambda.ps1   -Function $Function" -ForegroundColor Cyan
    Write-Host "    .\deploy-lambda.ps1  -Function $Function" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  (This guard exists because accidentally pushing a ZIP-mode" -ForegroundColor DarkGray
    Write-Host "   function as Docker creates an orphan ECR repository and" -ForegroundColor DarkGray
    Write-Host "   does not actually update the Lambda. Wasted work + cost.)" -ForegroundColor DarkGray
    exit 2
}

$dockerfileMap = @{
    "agent-gmail"        = "Dockerfile.gmail-agent"
    "agent-docs"         = "Dockerfile.docs-agent"
    "agent-sheets"       = "Dockerfile.sheets-agent"
    "agent-calendar"     = "Dockerfile.calendar-agent"
    "agent-drive"        = "Dockerfile.drive-agent"
    "agent-mapping"      = "Dockerfile.mapping-agent"
    "supervisor-ws-chat" = "Dockerfile.websocket"
}

$dockerfile = $dockerfileMap[$Function]
if (-not $dockerfile) {
    $dockerfile = "Dockerfile.lambda"
}
$dockerfilePath = Join-Path $Root $dockerfile

if (-not (Test-Path $dockerfilePath)) {
    Write-Error "Dockerfile not found: $dockerfilePath"
    exit 1
}

if (-not $EcrRepo) { $EcrRepo = $Function }

Write-Host "Building Docker image for $Function" -ForegroundColor Cyan
Write-Host "  Dockerfile: $dockerfile" -ForegroundColor Gray
Write-Host "  ECR repo:   $EcrRepo" -ForegroundColor Gray
Write-Host "  Tag:        $Tag" -ForegroundColor Gray

$buildArgs = @()
if ($dockerfile -eq "Dockerfile.lambda") {
    $buildArgs += "--build-arg"
    $buildArgs += "FUNCTION_NAME=$Function"
}

Push-Location $Root
try {
    $cacheFlag = @()
    if ($NoCache) { $cacheFlag = @("--no-cache") }
    # --provenance=false / --sbom=false: disable BuildKit attestation
    # manifests. Without these flags, repeated builds with the same tag
    # can fail with `image "...:latest": already exists` on Docker 25+ due
    # to attestation-manifest deduplication. We don't ship provenance to
    # ECR — Lambda doesn't surface it anywhere — so safe to drop.
    docker build `
        -f $dockerfilePath `
        -t "${EcrRepo}:${Tag}" `
        --provenance=false `
        --sbom=false `
        @cacheFlag `
        @buildArgs `
        .
    if ($LASTEXITCODE -ne 0) { throw "docker build failed" }
}
finally {
    Pop-Location
}

if ($SkipPush) {
    Write-Host "[ok] built ${EcrRepo}:${Tag} (skip-push)" -ForegroundColor Green
    return
}

# Discover account id and login to ECR
$AccountId = (aws sts get-caller-identity --query Account --output text).Trim()
if (-not $AccountId) { Write-Error "AWS credentials not configured"; exit 1 }
$EcrUri = "$AccountId.dkr.ecr.$Region.amazonaws.com"

# Ensure repo exists
$exists = aws ecr describe-repositories --repository-names $EcrRepo --region $Region 2>$null
if (-not $exists) {
    Write-Host "  Creating ECR repository $EcrRepo" -ForegroundColor Yellow
    aws ecr create-repository --repository-name $EcrRepo --region $Region | Out-Null
}

aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin $EcrUri | Out-Null

$RemoteTag = "${EcrUri}/${EcrRepo}:${Tag}"
docker tag "${EcrRepo}:${Tag}" $RemoteTag
docker push $RemoteTag
if ($LASTEXITCODE -ne 0) { throw "docker push failed" }

Write-Host "[ok] pushed ${RemoteTag}" -ForegroundColor Green
