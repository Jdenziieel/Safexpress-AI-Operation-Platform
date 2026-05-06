param(
    [ValidateSet('kb_upload','pdf_parse','ws_chat_stream','all')]
    [string]$Target = 'all'
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DistDir   = Join-Path $ScriptDir "dist"

if (-not (Test-Path $DistDir)) {
    New-Item -ItemType Directory -Path $DistDir | Out-Null
}

function Build-Special {
    param(
        [string]$Name,
        [string]$Dockerfile,
        [string]$Image,
        [string]$ContainerZipPath,
        [string]$OutputZipName,
        [bool]$UseTargetBuilder = $false
    )

    Write-Host ""
    Write-Host "=== Building $Name ===" -ForegroundColor Cyan
    Write-Host "  Dockerfile: $Dockerfile" -ForegroundColor Gray
    Write-Host "  Source:     $ContainerZipPath" -ForegroundColor Gray
    Write-Host "  Output:     dist\$OutputZipName" -ForegroundColor Gray

    $buildArgs = @('build', '-f', $Dockerfile, '-t', $Image)
    if ($UseTargetBuilder) { $buildArgs += @('--target','builder') }
    $buildArgs += '.'

    docker @buildArgs 2>&1 |
        Select-String -Pattern '(DONE|ERROR|CACHED|exporting|naming|✅)' |
        Select-Object -Last 4 |
        ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }

    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [FAIL] docker build failed" -ForegroundColor Red
        return
    }

    $cid = (docker create $Image | Out-String).Trim()
    if (-not $cid) {
        Write-Host "  [FAIL] could not create container" -ForegroundColor Red
        return
    }

    $zipPath = Join-Path $DistDir $OutputZipName
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

    docker cp "${cid}:$ContainerZipPath" $zipPath 2>&1 | Out-Null
    docker rm $cid | Out-Null
    docker rmi $Image -f 2>&1 | Out-Null

    if (Test-Path $zipPath) {
        $size = [math]::Round((Get-Item $zipPath).Length / 1MB, 2)
        Write-Host "  [OK] dist\$OutputZipName ($size MB)" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] zip not extracted from $ContainerZipPath" -ForegroundColor Red
    }
}

if ($Target -in 'kb_upload','all') {
    Build-Special -Name 'kb_upload' `
                  -Dockerfile 'Dockerfile.kb-upload' `
                  -Image 'kb-upload-builder' `
                  -ContainerZipPath '/build/kb-upload.zip' `
                  -OutputZipName 'kb-upload.zip' `
                  -UseTargetBuilder $true
}

if ($Target -in 'pdf_parse','all') {
    Build-Special -Name 'pdf_parse' `
                  -Dockerfile 'Dockerfile.pdf-parse' `
                  -Image 'kb-lambda-pdf-parse-builder' `
                  -ContainerZipPath '/output/pdf-parse.zip' `
                  -OutputZipName 'pdf-parse.zip' `
                  -UseTargetBuilder $false
}

if ($Target -in 'ws_chat_stream','all') {
    Build-Special -Name 'ws_chat_stream (multi-zip image)' `
                  -Dockerfile 'Dockerfile.websocket' `
                  -Image 'kb-lambda-websocket-builder' `
                  -ContainerZipPath '/build/ws-chat-stream.zip' `
                  -OutputZipName 'ws-chat-stream.zip' `
                  -UseTargetBuilder $false
}

Write-Host ""
Write-Host "=== New / updated zips ===" -ForegroundColor Cyan
Get-ChildItem $DistDir -Filter "*.zip" |
    Where-Object { $_.LastWriteTime -gt (Get-Date).AddMinutes(-30) } |
    Sort-Object LastWriteTime -Descending |
    ForEach-Object {
        $size = [math]::Round($_.Length / 1MB, 2)
        Write-Host ("  {0,-30} {1,8} MB  ({2})" -f $_.Name, $size, $_.LastWriteTime.ToString('HH:mm:ss')) -ForegroundColor Gray
    }
