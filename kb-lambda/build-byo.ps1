param([string[]]$Functions = @('kb_query','chat_message','kb_delete'))

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DistDir   = Join-Path $ScriptDir "dist"

if (-not (Test-Path $DistDir)) {
    New-Item -ItemType Directory -Path $DistDir | Out-Null
}

foreach ($f in $Functions) {
    Write-Host ""
    Write-Host "=== Building $f ===" -ForegroundColor Cyan
    $img = "lambda-builder-$f"

    docker build --build-arg "FUNCTION_NAME=$f" -f Dockerfile.lambda -t $img --target builder . 2>&1 |
        ForEach-Object { $_ } |
        Select-String -Pattern '(DONE|ERROR|CACHED|exporting|naming)' |
        Select-Object -Last 4 |
        ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }

    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [FAIL] docker build failed" -ForegroundColor Red
        continue
    }

    $cid = (docker create $img | Out-String).Trim()
    if (-not $cid) {
        Write-Host "  [FAIL] could not create container" -ForegroundColor Red
        continue
    }

    $zipPath = Join-Path $DistDir "$f.zip"
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

    docker cp "${cid}:/build/lambda-function.zip" $zipPath 2>&1 | Out-Null
    docker rm $cid | Out-Null
    docker rmi $img -f 2>&1 | Out-Null

    if (Test-Path $zipPath) {
        $size = [math]::Round((Get-Item $zipPath).Length / 1MB, 2)
        Write-Host "  [OK] dist/$f.zip ($size MB)" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] zip not extracted" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "=== Build summary ===" -ForegroundColor Cyan
Get-ChildItem $DistDir -Filter "*.zip" | ForEach-Object {
    $size = [math]::Round($_.Length / 1MB, 2)
    Write-Host ("  {0,-30} {1,8} MB  ({2})" -f $_.Name, $size, $_.LastWriteTime.ToString('HH:mm:ss')) -ForegroundColor Gray
}
