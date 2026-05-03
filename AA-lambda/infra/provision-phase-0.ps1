# AA-lambda Phase 0 Provisioner
#
# Runs the three Phase 0 checkpoints:
#   0.A  CloudFormation deploy of the 12 Sup_* DynamoDB tables
#   0.B  Secrets/IAM/S3 patching
#   0.C  API Gateway resource + WebSocket route registration
#
# Re-runnable: each step is idempotent.

param(
    [string]$Region              = "ap-southeast-1",
    [string]$RestApiId           = "anf38iju12",
    [string]$WsApiId             = "rjhzxw8sqj",
    [string]$RoleName            = "AuthLambdaExecutionRole",
    [string]$AccountId           = "",
    [switch]$SkipTables,
    [switch]$SkipSecrets,
    [switch]$SkipApiGateway
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $AccountId) {
    $AccountId = (aws sts get-caller-identity --query Account --output text).Trim()
    Write-Host "Resolved account id: $AccountId"
}

# ----------------------------------------------------------------------
# 0.A — DynamoDB tables via CloudFormation
# ----------------------------------------------------------------------
if (-not $SkipTables) {
    Write-Host "`n=== Phase 0.A: DynamoDB tables ===" -ForegroundColor Cyan
    $TemplateFile = Join-Path $ScriptDir "dynamodb-tables.yaml"
    $StackName = "aa-lambda-supervisor-tables"

    $exists = $false
    try {
        aws cloudformation describe-stacks --stack-name $StackName --region $Region --output json | Out-Null
        $exists = $true
    } catch { $exists = $false }

    if ($exists) {
        Write-Host "Stack $StackName exists; running update-stack..."
        try {
            aws cloudformation update-stack `
                --stack-name $StackName `
                --template-body file://$TemplateFile `
                --region $Region 2>&1 | Out-Null
        } catch {
            if ($_.Exception.Message -like "*No updates are to be performed*") {
                Write-Host "  No updates needed." -ForegroundColor Green
            } else { throw }
        }
    } else {
        Write-Host "Creating stack $StackName..."
        aws cloudformation create-stack `
            --stack-name $StackName `
            --template-body file://$TemplateFile `
            --region $Region | Out-Null
        aws cloudformation wait stack-create-complete --stack-name $StackName --region $Region
    }

    Write-Host "DynamoDB tables ready." -ForegroundColor Green
}

# ----------------------------------------------------------------------
# 0.B — Secrets / IAM / S3
# ----------------------------------------------------------------------
if (-not $SkipSecrets) {
    Write-Host "`n=== Phase 0.B: Secrets / IAM / S3 ===" -ForegroundColor Cyan

    # Confirm google-oauth secret
    try {
        aws secretsmanager describe-secret --secret-id "prod/app/google-oauth" --region $Region | Out-Null
        Write-Host "  prod/app/google-oauth exists" -ForegroundColor Green
    } catch {
        Write-Host "  WARNING: prod/app/google-oauth missing — populate before Phase 2 deploy" -ForegroundColor Yellow
    }

    # Add openai secret if missing
    try {
        aws secretsmanager describe-secret --secret-id "prod/app/openai" --region $Region | Out-Null
        Write-Host "  prod/app/openai exists" -ForegroundColor Green
    } catch {
        Write-Host "  Creating prod/app/openai (placeholder — set value via console or follow-up CLI)" -ForegroundColor Yellow
        aws secretsmanager create-secret `
            --name "prod/app/openai" `
            --secret-string '{"OPENAI_API_KEY":"REPLACE_ME"}' `
            --region $Region | Out-Null
    }

    # Patch IAM role
    Write-Host "  Patching $RoleName inline policy AALambdaInvokeAndPushExtras"
    $WsArn = "arn:aws:execute-api:${Region}:${AccountId}:${WsApiId}/*/POST/@connections/*"
    $AgentArn = "arn:aws:lambda:${Region}:${AccountId}:function:agent-*"
    $SupervisorArn = "arn:aws:lambda:${Region}:${AccountId}:function:supervisor-*"
    $InlinePolicy = @{
        Version = "2012-10-17"
        Statement = @(
            @{ Effect="Allow"; Action="lambda:InvokeFunction"; Resource=@($AgentArn, $SupervisorArn) }
            @{ Effect="Allow"; Action="execute-api:ManageConnections"; Resource=$WsArn }
            @{ Effect="Allow"; Action=@("dynamodb:*"); Resource="arn:aws:dynamodb:${Region}:${AccountId}:table/Sup_*" }
        )
    } | ConvertTo-Json -Depth 6

    $TmpFile = Join-Path $env:TEMP "aa-inline-policy.json"
    $InlinePolicy | Set-Content -Path $TmpFile -Encoding UTF8
    aws iam put-role-policy `
        --role-name $RoleName `
        --policy-name AALambdaInvokeAndPushExtras `
        --policy-document file://$TmpFile

    Write-Host "  IAM patched." -ForegroundColor Green
}

# ----------------------------------------------------------------------
# 0.C — API Gateway resources + WS route
# ----------------------------------------------------------------------
if (-not $SkipApiGateway) {
    Write-Host "`n=== Phase 0.C: API Gateway resources + WS route ===" -ForegroundColor Cyan
    Write-Host "  This runs against the existing REST API ($RestApiId) and WS API ($WsApiId)."
    Write-Host "  Routes are wired to Lambda integrations LATER in Phase 3.F (RBAC + integrations)."
    Write-Host "  This step only creates the resource tree + the new sendAgentMessage WS route."

    # Resource paths to create. Hierarchical — / -> api -> threads -> {thread_id}, etc.
    $RestRoutes = @(
        # Threads (11)
        @{ Method="POST"; Path="/threads" }
        @{ Method="POST"; Path="/threads/create-with-upload" }
        @{ Method="GET"; Path="/threads" }
        @{ Method="GET"; Path="/threads/search" }
        @{ Method="GET"; Path="/threads/{thread_id}" }
        @{ Method="GET"; Path="/threads/{thread_id}/messages" }
        @{ Method="PUT"; Path="/threads/{thread_id}" }
        @{ Method="DELETE"; Path="/threads/{thread_id}" }
        @{ Method="POST"; Path="/threads/{thread_id}/messages" }
        @{ Method="POST"; Path="/threads/{thread_id}/messages/upload" }
        @{ Method="GET"; Path="/threads/{thread_id}/progress" }
        # Actions (4)
        @{ Method="GET"; Path="/actions/pending" }
        @{ Method="GET"; Path="/action/{action_id}" }
        @{ Method="POST"; Path="/action/approve/{action_id}" }
        @{ Method="POST"; Path="/actions/cleanup" }
        # Logs (6)
        @{ Method="GET"; Path="/logs" }
        @{ Method="GET"; Path="/logs/search" }
        @{ Method="GET"; Path="/logs/stats" }
        @{ Method="GET"; Path="/logs/requests/{request_id}" }
        @{ Method="DELETE"; Path="/logs" }
        @{ Method="GET"; Path="/agents/metrics" }
        # Admin (12)
        @{ Method="GET"; Path="/admin/logs" }
        @{ Method="GET"; Path="/admin/activity" }
        @{ Method="GET"; Path="/admin/activity/summary" }
        @{ Method="GET"; Path="/admin/health" }
        @{ Method="GET"; Path="/admin/alerts" }
        @{ Method="GET"; Path="/admin/usage/summary" }
        @{ Method="GET"; Path="/admin/pricing" }
        @{ Method="PUT"; Path="/admin/pricing/{model}" }
        @{ Method="GET"; Path="/admin/settings/budget" }
        @{ Method="PUT"; Path="/admin/settings/budget" }
        @{ Method="GET"; Path="/admin/metrics" }
        @{ Method="GET"; Path="/admin/metrics/internal" }
        # Health + Workflow
        @{ Method="GET"; Path="/health" }
        @{ Method="GET"; Path="/" }
        @{ Method="POST"; Path="/workflow" }
    )

    Write-Host "  REST routes to create: $($RestRoutes.Count)"
    Write-Host "  Use create-resource + put-method via the AWS CLI in Phase 3.F when Lambdas exist."
    Write-Host "  See AA-lambda/scripts/wire_api_gateway.ps1 for the per-route loop."

    # WebSocket route
    Write-Host "  Registering sendAgentMessage WS route on $WsApiId..."
    $existing = (aws apigatewayv2 get-routes --api-id $WsApiId --region $Region --output json | ConvertFrom-Json).Items |
        Where-Object { $_.RouteKey -eq "sendAgentMessage" }
    if ($existing) {
        Write-Host "  sendAgentMessage already exists ($($existing.RouteId))" -ForegroundColor Green
    } else {
        $route = aws apigatewayv2 create-route `
            --api-id $WsApiId `
            --route-key "sendAgentMessage" `
            --region $Region | ConvertFrom-Json
        Write-Host "  Created route $($route.RouteId)" -ForegroundColor Green
        Write-Host "  Integration target wired in Phase 4.E (after supervisor-ws-chat is built)."
    }
}

Write-Host "`nPhase 0 complete." -ForegroundColor Green
