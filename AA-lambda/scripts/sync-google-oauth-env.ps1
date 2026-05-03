# Pushes GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET from Secrets Manager
# (`prod/app/google-oauth`) into the Lambda environment variables of
# every Lambda that runs the supervisor orchestrator in-process.
#
# Why this exists:
#   * Per-user `access_token` / `refresh_token` live in DynamoDB
#     `SocialTokens` (written by `auth-google-login` at OAuth callback).
#   * App-wide `client_id` / `client_secret` are NOT per-user — they
#     are the OAuth app's own identity, shared across every user, and
#     are stored in Secrets Manager.
#   * `shared/google_creds.py` reads `GOOGLE_CLIENT_ID` /
#     `GOOGLE_CLIENT_SECRET` from Lambda env vars. If those env vars
#     are unset, every workflow bails at the orchestrator's pre-flight
#     check (`supervisor_agent.py:1179`) with:
#       "Missing required Google credentials: client_id, client_secret.
#        Cannot execute plan."
#
# When to run:
#   * After rotating the OAuth secret in Secrets Manager.
#   * After provisioning a new orchestrator-running Lambda (add it to
#     $ORCHESTRATOR_LAMBDAS below first).
#   * On a fresh stack-up.
#
# Usage:
#   .\scripts\sync-google-oauth-env.ps1
#   .\scripts\sync-google-oauth-env.ps1 -Region ap-southeast-1
#   .\scripts\sync-google-oauth-env.ps1 -DryRun     # show plan, change nothing
#
# IAM the runner needs:
#   * secretsmanager:GetSecretValue on prod/app/google-oauth-*
#   * lambda:GetFunctionConfiguration + UpdateFunctionConfiguration on the
#     listed function ARNs.

[CmdletBinding()]
param(
    [string]$Region = "ap-southeast-1",
    [string]$SecretId = "prod/app/google-oauth",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# Lambdas that run the supervisor orchestrator in-process (and therefore
# need GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET to refresh expired access
# tokens via shared/google_creds.py).
#
# When you add a new orchestrator-entry-point Lambda (anything that
# calls `ConversationalAgent.process_message` or `run_workflow`), append
# it here AND re-run this script.
$ORCHESTRATOR_LAMBDAS = @(
    # WebSocket chat path (handles initial planning + 'yes/cancel' resume)
    "supervisor-ws-chat",
    # REST chat path
    "supervisor-post-message",
    "supervisor-post-message-upload",
    # Thread create with initial_message
    "supervisor-create-thread",
    "supervisor-create-thread-upload",
    # Approval resume (REST)
    "supervisor-action-approve",
    # Stand-alone heavy workflow lambda
    "supervisor-workflow"
)

Write-Host "Reading $SecretId from Secrets Manager (region $Region) ..." -ForegroundColor Cyan
$secretJson = aws secretsmanager get-secret-value --secret-id $SecretId --region $Region --query 'SecretString' --output text
if ($LASTEXITCODE -ne 0) {
    Write-Host "[fail] could not read secret $SecretId. Check IAM + region." -ForegroundColor Red
    exit 1
}
$secret = $secretJson | ConvertFrom-Json
$clientId = $secret.GOOGLE_CLIENT_ID
$clientSecret = $secret.GOOGLE_CLIENT_SECRET

if (-not $clientId -or -not $clientSecret) {
    Write-Host "[fail] secret is missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET." -ForegroundColor Red
    exit 1
}
Write-Host "  client_id length=$($clientId.Length), client_secret length=$($clientSecret.Length)" -ForegroundColor Green

$updated = 0
$alreadyOk = 0
$failed = 0

foreach ($fn in $ORCHESTRATOR_LAMBDAS) {
    Write-Host ""
    Write-Host "=== $fn ===" -ForegroundColor Cyan

    $existingJson = aws lambda get-function-configuration --function-name $fn --region $Region --query 'Environment.Variables' --output json 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [skip] function does not exist or no permission to read." -ForegroundColor Yellow
        $failed++
        continue
    }
    $existing = $existingJson | ConvertFrom-Json
    $merged = @{}
    if ($existing) { $existing.PSObject.Properties | ForEach-Object { $merged[$_.Name] = $_.Value } }

    $needsUpdate = $false
    if ($merged["GOOGLE_CLIENT_ID"] -ne $clientId) { $needsUpdate = $true }
    if ($merged["GOOGLE_CLIENT_SECRET"] -ne $clientSecret) { $needsUpdate = $true }

    if (-not $needsUpdate) {
        Write-Host "  [ok] already in sync." -ForegroundColor Green
        $alreadyOk++
        continue
    }

    if ($DryRun) {
        Write-Host "  [dry-run] would update GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET." -ForegroundColor Yellow
        continue
    }

    $merged["GOOGLE_CLIENT_ID"] = $clientId
    $merged["GOOGLE_CLIENT_SECRET"] = $clientSecret

    # Write the env JSON to a temp file WITHOUT a UTF-8 BOM (PowerShell's
    # default Set-Content adds one and AWS CLI rejects it with
    # "Expected: '=', received: 'i'" — see fix-history below).
    $envJson = "{`"Variables`": " + ($merged | ConvertTo-Json -Compress) + "}"
    $tmpFile = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($tmpFile, $envJson, (New-Object System.Text.UTF8Encoding $false))

    aws lambda update-function-configuration --function-name $fn --region $Region --environment file://$tmpFile --query 'LastUpdateStatus' --output text | Out-Null
    Remove-Item $tmpFile -Force

    aws lambda wait function-updated --function-name $fn --region $Region
    Write-Host "  [ok] updated and ready." -ForegroundColor Green
    $updated++
}

Write-Host ""
Write-Host "Summary: $updated updated, $alreadyOk already-ok, $failed failed." -ForegroundColor Cyan
if ($DryRun) {
    Write-Host "(dry-run; no changes applied)" -ForegroundColor Yellow
}
