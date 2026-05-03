# Top-level orchestrator - builds Lambda images in the AA-lambda fleet.
#
# Usage examples:
#
#   # Common cases ------------------------------------------------------
#   .\build-all.ps1 -Functions supervisor-list-threads
#       Rebuild ONE function. Fast (~5s) when cache is warm.
#
#   .\build-all.ps1 -Functions supervisor-create-thread,supervisor-workflow,agent-mapping
#       Rebuild specific N. Comma-separated list, no spaces.
#
#   .\build-all.ps1 -Group supervisor -AllDocker
#       Rebuild all 36 supervisor-* functions as Docker images.
#
#   .\build-all.ps1 -Group agents -AllDocker
#       Rebuild only the 6 sub-agents.
#
#   .\build-all.ps1 -AllDocker
#       Full fleet rebuild. ~15min cold, ~5min warm cache.
#
#   .\build-all.ps1 -Functions supervisor-ws-chat -Push
#       Rebuild and push to ECR.
#
#   # Build-only (no push) is the default. Use -Push to also push.
#
# Caching behavior (BuildKit, Docker 25+):
#
#   - The `# syntax=docker/dockerfile:1.6` header in each Dockerfile enables
#     pip wheel caching via `--mount=type=cache`. The wheel cache survives
#     across builds AND across functions, so the SECOND function you build
#     (with the same Python deps) reuses wheels downloaded for the first.
#
#   - Layer cache invalidation rules:
#       * COPY requirements.txt    -> invalidates pip-install layer
#       * COPY shared/             -> invalidates the shared-copy + later layers
#       * COPY functions/<name>/   -> invalidates only the per-function layer
#
#   - Therefore: editing brain code in `shared/` triggers a fast (~5-10s)
#     rebuild of every supervisor function (the slow pip layer is cached).
#     Editing one function's `lambda_function.py` triggers a ~3s rebuild of
#     ONLY that function.
#
#   - To force-rebuild without cache, pass `-NoCache`. Useful only when
#     debugging suspected cache poisoning.

[CmdletBinding()]
param(
    [ValidateSet("all", "agents", "supervisor")]
    [string]$Group = "all",

    # Surgical: build only the named functions. Overrides $Group when set.
    # Accepts comma-separated values: -Functions supervisor-workflow,agent-mapping
    [string[]]$Functions = @(),

    [switch]$Push,
    [switch]$OnlyZip,
    [switch]$OnlyDocker,
    # AllDocker: ignore the zip/docker split and build EVERY function as a
    # Docker image. The light functions reuse Dockerfile.lambda via the
    # FUNCTION_NAME build arg, so layer caching keeps the marginal build
    # cost per function low (only the per-function COPY layer changes).
    # Used by the unified-deploy guide where every fleet member is Docker.
    [switch]$AllDocker,
    [switch]$NoCache,
    # When set, ZIPs that already exist in dist/ with a "looks complete"
    # size (>= 17 MB for light supervisor zips) are skipped. Used to
    # resume an interrupted build without redoing finished functions.
    [switch]$SkipBuiltZips,
    [string]$Region = "ap-southeast-1",
    [string]$Tag = "latest"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

# Functions that need Docker (any name not in this list is built as zip).
#
# 11 total: 5 heavy supervisor + 6 agents. Everything else is a light
# DynamoDB-CRUD endpoint that ships as a ~30-50 MB ZIP via build-lambda.ps1
# (which installs only the light top-level requirements.txt).
#
# A function belongs here ONLY if its lambda_function.py (or a transitive
# import from `shared/`) needs the heavy LLM stack: langchain, langgraph,
# openai, tiktoken, jinja2, etc. - OR it's a sub-agent that ships its own
# heavy non-LLM stack (Google APIs, pandas, pdfplumber, pymupdf).
#
# Reverse audit (DO NOT add a function here unless it imports the brain):
#   - supervisor-action-approve uses shared.utils.call_agent_with_retry,
#     which `import langchain_openai, tiktoken` at module top level.
#   - supervisor-create-thread / -upload import conversational_agent
#     (Tier 0 / Tier 1 enrichment + planner) when initial_message is set.
#   - supervisor-workflow imports routes/workflow which imports the planner.
#   - supervisor-ws-chat runs the full chat pipeline (Tier 0/0.5/1 + planner).
#   - 6 agents each ship their own per-function heavy deps (Google APIs,
#     pandas, pdf libs, langchain-openai for body-rewrite, etc.).
$DockerFunctions = @(
    "supervisor-create-thread",
    "supervisor-create-thread-upload",
    "supervisor-action-approve",
    "supervisor-workflow",
    "supervisor-ws-chat",
    "agent-gmail",
    "agent-docs",
    "agent-sheets",
    "agent-calendar",
    "agent-drive",
    "agent-mapping"
)

$AllFunctions = Get-ChildItem (Join-Path $Root "functions") -Directory | Select-Object -ExpandProperty Name

# Resolution order:
#   1. -Functions list (overrides everything if specified)
#   2. -Group filter
#   3. all functions
if ($Functions -and $Functions.Count -gt 0) {
    # Allow either single -Functions a,b,c or repeated -Functions a -Functions b.
    # PowerShell merges both into the same array - we just need to flatten any
    # commas the user might have left inside one element (rare but easy to fix).
    $expanded = @()
    foreach ($f in $Functions) {
        $expanded += ($f -split ',') | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    }
    $unknown = $expanded | Where-Object { $AllFunctions -notcontains $_ }
    if ($unknown.Count -gt 0) {
        Write-Host "[fail] Unknown function name(s): $($unknown -join ', ')" -ForegroundColor Red
        Write-Host ""
        Write-Host "Available functions ($($AllFunctions.Count) total):" -ForegroundColor Gray
        $AllFunctions | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }
        exit 1
    }
    $Filtered = $expanded
    Write-Host "Building targeted set: $($Filtered -join ', ')" -ForegroundColor Cyan
} else {
    $Filtered = switch ($Group) {
        "agents"     { $AllFunctions | Where-Object { $_ -like "agent-*" } }
        "supervisor" { $AllFunctions | Where-Object { $_ -like "supervisor-*" } }
        default      { $AllFunctions }
    }
    Write-Host "Building group=$Group ($($Filtered.Count) functions)" -ForegroundColor Cyan
}

if ($AllDocker) {
    $ZipTargets = @()
    $DockerTargets = $Filtered
} else {
    $ZipTargets = $Filtered | Where-Object { $DockerFunctions -notcontains $_ }
    $DockerTargets = $Filtered | Where-Object { $DockerFunctions -contains $_ }
}

Write-Host "  Zip targets   : $($ZipTargets.Count)" -ForegroundColor Gray
Write-Host "  Docker targets: $($DockerTargets.Count)" -ForegroundColor Gray
Write-Host "  AllDocker     : $AllDocker" -ForegroundColor Gray
Write-Host "  Push to ECR   : $Push" -ForegroundColor Gray
Write-Host "  No cache      : $NoCache" -ForegroundColor Gray
Write-Host ""

$Failures = @()

if (-not $OnlyDocker -and $ZipTargets.Count -gt 0) {
    # Optimization: every light supervisor function shares the SAME shared
    # requirements.txt (boto3 + pydantic + httpx + ulid-py + dotenv).
    # Their per-function requirements.txt files are mostly empty
    # (comment-only). So we install the shared deps ONCE into a template
    # build dir, then clone-copy + apply per-function deps for each
    # remaining function. Cuts ~31 docker pip-install runs down to 1.
    #
    # The template lives at build/_shared_zip_template/ and is rebuilt
    # only when AA-lambda/requirements.txt changes (mtime check below).
    $template = Join-Path $Root "build\_shared_zip_template"
    $sharedReq = Join-Path $Root "requirements.txt"
    $templateStamp = Join-Path $template ".req-mtime"

    $needsTemplateBuild = $true
    if ((Test-Path $template) -and (Test-Path $templateStamp)) {
        $stampMtime = [int64](Get-Content $templateStamp)
        $reqMtime = [int64](Get-Item $sharedReq).LastWriteTime.Ticks
        if ($stampMtime -eq $reqMtime) { $needsTemplateBuild = $false }
    }

    if ($needsTemplateBuild) {
        Write-Host "Building shared-zip template (one-time install of light requirements)" -ForegroundColor Cyan
        if (Test-Path $template) { Remove-Item $template -Recurse -Force }
        New-Item -ItemType Directory -Path $template -Force | Out-Null
        $relReq = "requirements.txt"
        docker run --rm `
            -v "${Root}:/src:ro" `
            -v "${template}:/build" `
            -v "aa-lambda-pip-cache:/root/.cache/pip" `
            --entrypoint /var/lang/bin/pip `
            "public.ecr.aws/lambda/python:3.12" `
            install --quiet --target /build -r "/src/$relReq"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[fail] template install failed - falling back to per-function pip" -ForegroundColor Red
            Remove-Item $template -Recurse -Force -ErrorAction SilentlyContinue
        } else {
            (Get-Item $sharedReq).LastWriteTime.Ticks | Out-File -FilePath $templateStamp -Encoding ascii
            Write-Host "  template ready at $template" -ForegroundColor Gray
        }
    } else {
        Write-Host "Reusing shared-zip template (requirements.txt unchanged)" -ForegroundColor Gray
    }

    $useTemplate = (Test-Path $template) -and (Test-Path $templateStamp)

    foreach ($fn in $ZipTargets) {
        # Resume support: skip if a complete-looking zip already exists.
        # Light supervisor ZIPs are ~18 MB; anything < 17 MB suggests a
        # truncated/interrupted Compress-Archive run from a prior attempt.
        if ($SkipBuiltZips) {
            $existingZip = Join-Path $Root "dist\$fn.zip"
            if (Test-Path $existingZip) {
                $sizeMB = (Get-Item $existingZip).Length / 1MB
                if ($sizeMB -ge 17) {
                    Write-Host ""
                    Write-Host ("[skip] {0} -> already built ({1:N2} MB)" -f $fn, $sizeMB) -ForegroundColor DarkYellow
                    continue
                }
            }
        }

        Write-Host ""
        try {
            if ($useTemplate) {
                & (Join-Path $Root "build-lambda.ps1") -Function $fn -TemplateDir $template
            } else {
                & (Join-Path $Root "build-lambda.ps1") -Function $fn
            }
        }
        catch {
            Write-Host "[fail] $fn : $_" -ForegroundColor Red
            $Failures += "zip:$fn"
        }
    }
}

if (-not $OnlyZip) {
    foreach ($fn in $DockerTargets) {
        Write-Host ""
        try {
            $args = @{ Function = $fn; Region = $Region; Tag = $Tag }
            if (-not $Push) { $args["SkipPush"] = $true }
            if ($NoCache)   { $args["NoCache"]  = $true }
            & (Join-Path $Root "build-lambda-docker.ps1") @args
        }
        catch {
            Write-Host "[fail] $fn : $_" -ForegroundColor Red
            $Failures += "docker:$fn"
        }
    }
}

Write-Host ""
if ($Failures.Count -gt 0) {
    Write-Host "Build complete with $($Failures.Count) failure(s):" -ForegroundColor Red
    $Failures | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    exit 1
}

Write-Host "Build complete - all targets succeeded." -ForegroundColor Green
