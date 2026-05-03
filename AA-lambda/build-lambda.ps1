# Builds a single zip-based Lambda function package.
#
# Usage:
#   .\build-lambda.ps1 -Function supervisor-list-threads
#   .\build-lambda.ps1 -Function agent-gmail
#
# What it does:
#   1. Creates AA-lambda/build/<Function>/ as a fresh staging dir.
#   2. Runs `pip install --target` INSIDE a Linux Lambda container
#      (public.ecr.aws/lambda/python:3.12) so wheels match the deploy
#      target architecture. Building on Windows with the host pip pulls
#      Windows wheels for any binary package (pydantic_core, etc.) which
#      will ImportError at Lambda cold-start. Going through a Linux
#      container fixes that.
#   3. Copies functions/<Function>/*.py into it.
#   4. For supervisor-* functions, also copies shared/ in (Option A in S0.5.3).
#   5. Zips everything into AA-lambda/dist/<Function>.zip.
#
# The container reuses a NAMED Docker volume `aa-lambda-pip-cache` so
# the second function onward reuses wheels from the previous run - the
# whole 31-ZIP build runs in ~10-15 min instead of ~30+.
#
# To bypass Docker entirely (e.g. you're on Linux already), pass
# -NoDocker. The host pip is then used; expect ImportErrors on Lambda
# if you're not on a manylinux-compatible platform.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Function,
    [switch]$SkipPipInstall,
    [switch]$NoDocker,
    # Optional pre-installed shared-deps directory. When set, the script
    # skips the shared `pip install` and instead clone-copies this
    # template into the build dir, then runs ONLY the per-function pip
    # (if non-empty). Used by build-all.ps1 to avoid running pip 31
    # times for the 31 light supervisor functions that share an
    # identical light requirements.txt.
    [string]$TemplateDir = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$FuncDir = Join-Path $Root "functions\$Function"
$BuildDir = Join-Path $Root "build\$Function"
$DistDir = Join-Path $Root "dist"
$ZipPath = Join-Path $DistDir "$Function.zip"
$PipImage = "public.ecr.aws/lambda/python:3.12"
$PipCacheVolume = "aa-lambda-pip-cache"

if (-not (Test-Path $FuncDir)) {
    Write-Error "Function folder not found: $FuncDir"
    exit 1
}

Write-Host "Building zip for $Function" -ForegroundColor Cyan

# 1. Fresh staging dir
if (Test-Path $BuildDir) { Remove-Item $BuildDir -Recurse -Force }
New-Item -ItemType Directory -Path $BuildDir -Force | Out-Null
if (-not (Test-Path $DistDir)) { New-Item -ItemType Directory -Path $DistDir -Force | Out-Null }

# 2. Install deps inside a Linux Lambda container - produces wheels
# compatible with Lambda's Amazon Linux 2023 runtime regardless of
# whether the host is Windows / macOS / Linux.
function Invoke-DockerPip {
    param([string]$RequirementsPath)
    $relReq = (Resolve-Path -LiteralPath $RequirementsPath).Path.Substring($Root.Length).TrimStart('\').Replace('\', '/')
    docker run --rm `
        -v "${Root}:/src:ro" `
        -v "${BuildDir}:/build" `
        -v "${PipCacheVolume}:/root/.cache/pip" `
        --entrypoint /var/lang/bin/pip `
        $PipImage `
        install --quiet --target /build -r "/src/$relReq"
    if ($LASTEXITCODE -ne 0) { throw "pip install (docker) failed for $RequirementsPath" }
}

if (-not $SkipPipInstall) {
    $sharedReq = Join-Path $Root "requirements.txt"
    $fnReq = Join-Path $FuncDir "requirements.txt"

    if ($TemplateDir -and (Test-Path $TemplateDir)) {
        # Template fast-path: clone pre-installed shared deps into the
        # function's build dir. ~5s vs ~30s for a fresh `pip install`.
        # Triggered by build-all.ps1's batch mode.
        Write-Host "  Cloning shared deps from template" -ForegroundColor Gray
        # robocopy is ~3x faster than Copy-Item for thousands of small
        # files (typical for site-packages). Exit codes 0-7 are success;
        # 8+ are real failures.
        $rcOut = robocopy $TemplateDir $BuildDir /E /NFL /NDL /NJH /NJS /NP /MT:8
        if ($LASTEXITCODE -ge 8) {
            throw "robocopy failed cloning template (exit $LASTEXITCODE)"
        }
    } elseif ($NoDocker) {
        # Host-pip path. Only correct if the host platform matches Lambda
        # (i.e. you're on a manylinux-compatible Linux). On Windows the
        # resulting ZIP will ImportError at Lambda cold-start because
        # pydantic_core and other binary wheels are platform-specific.
        if (Test-Path $sharedReq) {
            Write-Host "  Installing shared requirements (host pip)" -ForegroundColor Gray
            pip install --quiet --target $BuildDir -r $sharedReq
        }
    } else {
        if (Test-Path $sharedReq) {
            Write-Host "  Installing shared requirements (Linux container)" -ForegroundColor Gray
            Invoke-DockerPip $sharedReq
        }
    }

    # Per-function requirements run regardless of template mode - they
    # may legitimately add deps the template doesn't carry.
    if (Test-Path $fnReq) {
        $reqContent = (Get-Content $fnReq -Raw) -replace '#.*', '' -replace '\s', ''
        if ($reqContent.Length -gt 0) {
            if ($NoDocker) {
                Write-Host "  Installing function requirements (host pip)" -ForegroundColor Gray
                pip install --quiet --target $BuildDir -r $fnReq
            } else {
                Write-Host "  Installing function requirements (Linux container)" -ForegroundColor Gray
                Invoke-DockerPip $fnReq
            }
        } else {
            Write-Host "  Skipping function requirements (empty)" -ForegroundColor DarkGray
        }
    }
}

# 4. Copy function code
Write-Host "  Copying function code" -ForegroundColor Gray
Get-ChildItem $FuncDir -File -Filter "*.py" | ForEach-Object {
    Copy-Item $_.FullName -Destination $BuildDir
}
Get-ChildItem $FuncDir -Recurse -Directory | Where-Object { $_.Name -notlike "__pycache__" -and $_.Name -ne "build" } | ForEach-Object {
    $rel = $_.FullName.Substring($FuncDir.Length).TrimStart('\')
    Copy-Item $_.FullName -Destination (Join-Path $BuildDir $rel) -Recurse -Force
}

# 5. Copy shared/ for supervisor-* zips (the brain)
if ($Function -like "supervisor-*") {
    Write-Host "  Copying shared/ brain into package" -ForegroundColor Gray
    $sharedSrc = Join-Path $Root "shared"
    $sharedDst = Join-Path $BuildDir "shared"
    if (Test-Path $sharedDst) { Remove-Item $sharedDst -Recurse -Force }
    Copy-Item $sharedSrc -Destination $sharedDst -Recurse -Force
    # Strip __pycache__ recursively
    Get-ChildItem -Path $sharedDst -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

# Strip __pycache__ everywhere in the build dir
Get-ChildItem -Path $BuildDir -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# 6. Zip
#
# We can't use ZipFile.CreateFromDirectory because on Windows it embeds
# entry names with backslash separators (e.g. "pydantic_core\foo.so").
# Lambda's Linux runtime treats backslashes as literal filename chars,
# so the package extracts to /var/task with all files at the root of
# Lambda's working dir (broken imports). We hand-walk the tree and add
# entries with forward-slash names.
#
# Compress-Archive would also produce forward slashes but is ~5-10x
# slower than the .NET ZipArchive route below for thousands of small
# files. The hand-walk + ZipArchive::CreateEntryFromFile approach takes
# ~5s per 18 MB function vs ~60s for Compress-Archive.
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Write-Host "  Zipping to $ZipPath" -ForegroundColor Gray
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$zipStream = [System.IO.File]::Open($ZipPath, [System.IO.FileMode]::CreateNew)
try {
    $zip = New-Object System.IO.Compression.ZipArchive(
        $zipStream,
        [System.IO.Compression.ZipArchiveMode]::Create
    )
    try {
        $buildPrefixLen = $BuildDir.Length + 1  # +1 for trailing separator
        Get-ChildItem $BuildDir -Recurse -File | ForEach-Object {
            $rel = $_.FullName.Substring($buildPrefixLen).Replace('\', '/')
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $zip,
                $_.FullName,
                $rel,
                [System.IO.Compression.CompressionLevel]::Optimal
            ) | Out-Null
        }
    } finally {
        $zip.Dispose()
    }
} finally {
    $zipStream.Dispose()
}

$size = (Get-Item $ZipPath).Length / 1MB
Write-Host ("[ok] {0} -> {1:N2} MB" -f $Function, $size) -ForegroundColor Green
