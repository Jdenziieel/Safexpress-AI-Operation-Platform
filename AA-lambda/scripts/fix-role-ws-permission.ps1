param(
    [string]$Region = "ap-southeast-1",
    [string]$RoleName = "AA-Lambda-Execution-Role",
    [string]$WsApiId = "rjhzxw8sqj",
    [string]$NewPolicyName = "AA-WebSocket-PushBack",
    [switch]$DryRun
)

# Fixes:
#   [ApiGwPusher] push failed: AccessDeniedException ... User: <role>/supervisor-ws-chat
#     is not authorized to perform: execute-api:ManageConnections on resource:
#     arn:aws:execute-api:<region>:<acct>:<wsApiId>/<stage>/POST/@connections/{connectionId}
#
# Strategy: scan every inline policy already on the role. If any statement
# already grants execute-api:ManageConnections on the target WS API, do nothing
# (the runtime IAM evaluator only needs ONE matching Allow). Otherwise add a
# new minimal inline policy ($NewPolicyName) that grants just that one action.
# We deliberately do NOT rewrite an existing inline policy in place, because
# put-role-policy fully replaces the document and a typo would silently drop
# DynamoDB / S3 / InvokeSubAgents permissions.

$ErrorActionPreference = "Continue"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

function Test-StatementMatches {
    param($stmt, [string]$wsApiId)
    if ($stmt.Effect -ne "Allow") { return $false }

    $actions = @()
    if ($stmt.Action) {
        if ($stmt.Action -is [array]) { $actions = $stmt.Action } else { $actions = @($stmt.Action) }
    }
    $hasAction = $false
    foreach ($a in $actions) {
        if ($a -eq "execute-api:*" -or $a -eq "*" -or $a -eq "execute-api:ManageConnections") {
            $hasAction = $true; break
        }
    }
    if (-not $hasAction) { return $false }

    $resources = @()
    if ($stmt.Resource) {
        if ($stmt.Resource -is [array]) { $resources = $stmt.Resource } else { $resources = @($stmt.Resource) }
    }
    foreach ($r in $resources) {
        if ($r -eq "*") { return $true }
        if ($r -like "*:execute-api:*:*:$wsApiId/*") { return $true }
        if ($r -like "*:execute-api:*:*:$wsApiId") { return $true }
    }
    return $false
}

Write-Host ("Fix-RoleWsPermission: " + $RoleName) -ForegroundColor Cyan
Write-Host ("Target WS API: " + $WsApiId + "  Region: " + $Region) -ForegroundColor Cyan
if ($DryRun) { Write-Host "DRY RUN - no AWS writes" -ForegroundColor Yellow }
Write-Host ""

$roleJson = aws iam get-role --role-name $RoleName --output json 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host ("[FAIL] get-role: " + $roleJson) -ForegroundColor Red
    exit 1
}
$role = $roleJson | ConvertFrom-Json
Write-Host ("Role ARN: " + $role.Role.Arn) -ForegroundColor Gray

$listJson = aws iam list-role-policies --role-name $RoleName --output json 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host ("[FAIL] list-role-policies: " + $listJson) -ForegroundColor Red
    exit 1
}
$inlineNames = ($listJson | ConvertFrom-Json).PolicyNames
if (-not $inlineNames) { $inlineNames = @() }
Write-Host ("Inline policies found: " + $inlineNames.Count) -ForegroundColor Gray
foreach ($n in $inlineNames) { Write-Host ("  - " + $n) -ForegroundColor Gray }
Write-Host ""

$alreadyGranted = $false
$grantingPolicy = $null

foreach ($pname in $inlineNames) {
    $polJson = aws iam get-role-policy --role-name $RoleName --policy-name $pname --output json 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host ("  [WARN] could not fetch " + $pname + ": " + $polJson) -ForegroundColor Yellow
        continue
    }
    $pol = $polJson | ConvertFrom-Json
    $doc = $pol.PolicyDocument
    if ($doc -is [string]) { $doc = $doc | ConvertFrom-Json }

    $stmts = @()
    if ($doc.Statement) {
        if ($doc.Statement -is [array]) { $stmts = $doc.Statement } else { $stmts = @($doc.Statement) }
    }
    foreach ($s in $stmts) {
        if (Test-StatementMatches -stmt $s -wsApiId $WsApiId) {
            $alreadyGranted = $true
            $grantingPolicy = $pname
            break
        }
    }
    if ($alreadyGranted) { break }
}

if ($alreadyGranted) {
    Write-Host ("[OK] execute-api:ManageConnections on " + $WsApiId + " is already granted by inline policy '" + $grantingPolicy + "'.") -ForegroundColor Green
    Write-Host "No change needed. If the Lambda is still 403'ing, double-check the WS_API_ENDPOINT env var on supervisor-ws-chat points at this same API ID." -ForegroundColor Gray
    exit 0
}

Write-Host ("[GAP] No existing statement grants execute-api:ManageConnections on " + $WsApiId + ".") -ForegroundColor Yellow
Write-Host ("Will add inline policy '" + $NewPolicyName + "' to '" + $RoleName + "'.") -ForegroundColor Yellow
Write-Host ""

$policyDoc = [ordered]@{
    Version = "2012-10-17"
    Statement = @(
        [ordered]@{
            Sid = "WebSocketPushBack"
            Effect = "Allow"
            Action = @("execute-api:ManageConnections")
            Resource = "arn:aws:execute-api:${Region}:*:${WsApiId}/*"
        }
    )
}
$payload = $policyDoc | ConvertTo-Json -Depth 6 -Compress

Write-Host "Policy document to apply:" -ForegroundColor Cyan
Write-Host $payload -ForegroundColor Gray
Write-Host ""

if ($DryRun) {
    Write-Host ("[DRY] would put-role-policy --role-name " + $RoleName + " --policy-name " + $NewPolicyName) -ForegroundColor Magenta
    exit 0
}

$tmpPath = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllText($tmpPath, $payload, $utf8NoBom)
$result = aws iam put-role-policy `
    --role-name $RoleName `
    --policy-name $NewPolicyName `
    --policy-document "file://$tmpPath" `
    --output json 2>&1
Remove-Item $tmpPath -ErrorAction SilentlyContinue

if ($LASTEXITCODE -ne 0) {
    Write-Host ("[FAIL] put-role-policy: " + $result) -ForegroundColor Red
    exit 1
}

Write-Host ("[OK] Inline policy '" + $NewPolicyName + "' attached to '" + $RoleName + "'.") -ForegroundColor Green
Write-Host ""

Write-Host "Verifying..." -ForegroundColor Cyan
$verifyJson = aws iam get-role-policy --role-name $RoleName --policy-name $NewPolicyName --output json 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host ("[WARN] verification get-role-policy failed: " + $verifyJson) -ForegroundColor Yellow
} else {
    Write-Host $verifyJson -ForegroundColor Gray
}

Write-Host ""
Write-Host "IAM changes are effective immediately. Reproduce the failing supervisor-ws-chat call and confirm the [ApiGwPusher] error is gone in CloudWatch." -ForegroundColor Cyan
exit 0
