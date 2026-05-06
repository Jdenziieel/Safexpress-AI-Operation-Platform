Add-Type -AssemblyName System.IO.Compression.FileSystem

function Read-ZipEntry {
    param([System.IO.Compression.ZipArchive]$archive, [string]$pattern)
    $entry = $archive.Entries | Where-Object { $_.FullName -like $pattern } | Select-Object -First 1
    if (-not $entry) { return $null }
    $stream = $entry.Open()
    $reader = New-Object System.IO.StreamReader $stream
    $content = $reader.ReadToEnd()
    $reader.Dispose()
    $stream.Dispose()
    return $content
}

function Show-PayloadFields {
    param([string]$ZipPath, [string]$EntryPattern, [string]$Marker, [string]$Label)
    Write-Host ""
    Write-Host "=== $Label ===" -ForegroundColor Cyan
    Write-Host "  Zip:   $ZipPath" -ForegroundColor Gray
    Write-Host "  File:  $EntryPattern" -ForegroundColor Gray
    Write-Host "  After: '$Marker'" -ForegroundColor Gray

    $archive = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path $ZipPath).Path)
    try {
        $code = Read-ZipEntry $archive $EntryPattern
        if (-not $code) {
            Write-Host "  [MISS] entry not found in zip" -ForegroundColor Red
            return
        }
        $idx = $code.IndexOf($Marker)
        if ($idx -lt 0) {
            Write-Host "  [MISS] marker '$Marker' not in file" -ForegroundColor Red
            return
        }
        $window = $code.Substring($idx, [Math]::Min(2000, $code.Length - $idx))
        $lines = $window -split "`r?`n"
        # Find the json={ block
        $jsonStart = -1
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match 'json=\{') { $jsonStart = $i; break }
        }
        if ($jsonStart -lt 0) {
            Write-Host "  [MISS] could not locate json={ block after marker" -ForegroundColor Red
            return
        }
        $depth = 0
        for ($i = $jsonStart; $i -lt $lines.Count; $i++) {
            $line = $lines[$i]
            Write-Host "    $line" -ForegroundColor White
            $depth += ($line.ToCharArray() | Where-Object { $_ -eq '{' }).Count
            $depth -= ($line.ToCharArray() | Where-Object { $_ -eq '}' }).Count
            if ($depth -le 0 -and $i -gt $jsonStart) { break }
        }
    } finally {
        $archive.Dispose()
    }
}

Show-PayloadFields `
    -ZipPath '.\dist\ws_chat_stream.zip' `
    -EntryPattern '*lambda_function.py' `
    -Marker 'def report_usage' `
    -Label 'ws_chat_stream.zip - report_usage() POST body'

Show-PayloadFields `
    -ZipPath '.\dist\kb_upload.zip' `
    -EntryPattern '*shared/weaviate_utils.py' `
    -Marker 'def _report_embedding_usage' `
    -Label 'kb_upload.zip - _report_embedding_usage() POST body'

Show-PayloadFields `
    -ZipPath '.\dist\chat_message.zip' `
    -EntryPattern '*lambda_function.py' `
    -Marker 'def report_usage' `
    -Label 'chat_message.zip - report_usage() POST body'
