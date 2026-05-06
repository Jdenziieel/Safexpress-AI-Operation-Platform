Add-Type -AssemblyName System.IO.Compression.FileSystem

$zips = @('kb_query.zip','chat_message.zip','kb_delete.zip','kb-upload.zip','pdf-parse.zip','ws-chat-stream.zip')

function Read-ZipEntry {
    param([System.IO.Compression.ZipArchive]$archive, [string]$pattern)
    $entry = $archive.Entries | Where-Object { $_.FullName -like $pattern } | Select-Object -First 1
    if (-not $entry) { return $null }
    $stream = $entry.Open()
    $reader = New-Object System.IO.StreamReader($stream)
    $content = $reader.ReadToEnd()
    $reader.Dispose()
    $stream.Dispose()
    return $content
}

foreach ($z in $zips) {
    $path = ".\dist\$z"
    if (-not (Test-Path $path)) {
        Write-Host ("{0,-22} MISSING" -f $z) -ForegroundColor Red
        continue
    }

    $archive = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path $path).Path)
    try {
        $openai = Read-ZipEntry $archive '*shared/openai_utils.py'
        $weaviate = Read-ZipEntry $archive '*shared/weaviate_utils.py'

        $hasEmbed       = $openai -and ($openai -match 'def embed_texts')
        $hasReport      = $weaviate -and ($weaviate -match '_report_embedding_usage')
        $hasBM25        = $weaviate -and ($weaviate -match 'BM25-only fallback')
        $hasVecNone     = $weaviate -and ($weaviate -match 'Vectorizer\.none\(\)')
        $hasNoneGuard   = $openai -and ($openai -match '\(t or ''\)\.strip')
        $hasQuotaTrue   = $weaviate -and ($weaviate -match "QUOTA_ENABLED.*'true'")

        $allOk = $hasEmbed -and $hasReport -and $hasBM25 -and $hasVecNone -and $hasNoneGuard -and $hasQuotaTrue
        $status = if ($allOk) { 'OK' } else { 'INCOMPLETE' }
        $color = if ($allOk) { 'Green' } else { 'Yellow' }

        Write-Host ("{0,-22} {1,-11} embed_texts={2,-5} report={3,-5} bm25={4,-5} vec_none={5,-5} none_guard={6,-5} quota_true={7}" -f `
            $z, $status, $hasEmbed, $hasReport, $hasBM25, $hasVecNone, $hasNoneGuard, $hasQuotaTrue) -ForegroundColor $color
    } finally {
        $archive.Dispose()
    }
}

Write-Host ""
Write-Host "Lambda functions code verification:" -ForegroundColor Cyan

# Check that lambda function entry point in each zip references the new behaviour
$callerChecks = @{
    'kb_query.zip'        = @{ pattern = 'lambda_kb_query.py'; need = "user_id=user_id," }
    'chat_message.zip'    = @{ pattern = 'lambda_chat_message.py'; need = "user_id=user_id," }
    'kb_delete.zip'       = @{ pattern = 'lambda_kb_delete.py'; need = "s3_delete_file" }
    'kb-upload.zip'       = @{ pattern = 'lambda_kb_upload.py'; need = "user_id=user_id," }
    'pdf-parse.zip'       = @{ pattern = 'lambda_pdf_parse.py'; need = "'s3_key': s3_key" }
    'ws-chat-stream.zip'  = @{ pattern = 'lambda_ws_chat_stream.py'; need = "user_id=user_id," }
}

foreach ($z in $zips) {
    $path = ".\dist\$z"
    if (-not (Test-Path $path)) { continue }

    $check = $callerChecks[$z]
    $archive = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path $path).Path)
    try {
        $code = Read-ZipEntry $archive "*$($check.pattern)"
        $found = $code -and ($code.Contains($check.need))
        $status = if ($found) { 'OK' } else { 'MISSING' }
        $color = if ($found) { 'Green' } else { 'Yellow' }
        Write-Host ("  {0,-22} {1,-12} ({2} contains '{3}')" -f $z, $status, $check.pattern, $check.need) -ForegroundColor $color
    } finally {
        $archive.Dispose()
    }
}
