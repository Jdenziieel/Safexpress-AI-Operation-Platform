# wire-rest-routes.ps1
#
# Creates the 36 supervisor REST API routes on the existing kb-stack API
# Gateway (`anf38iju12`, stage `prod`). Idempotent - re-runs that hit an
# already-created resource skip without erroring.
#
# What this script does, per route:
#   1. Walks the path segments, creating any missing parent resources.
#   2. Creates the method (GET/POST/PUT/DELETE) with Lambda proxy integration.
#   3. Attaches the JWT authorizer (`jwt-api-authorizer`, type=TOKEN).
#   4. Adds an OPTIONS method (MOCK) for CORS preflight.
#   5. Grants API Gateway permission to invoke the target Lambda.
#
# What this script does NOT do:
#   - Deploy the prod stage (you must run S11.5 of the deployment guide AFTER
#     this script finishes). Reason: deploying mid-run would publish a half-
#     wired API. Run -Deploy at the end as a separate step.
#
# Run mode:
#   .\wire-rest-routes.ps1                # do everything except deploy
#   .\wire-rest-routes.ps1 -Deploy        # do everything + deploy prod stage
#   .\wire-rest-routes.ps1 -DryRun        # print plan, change nothing
#   .\wire-rest-routes.ps1 -Routes "GET /threads","POST /threads"  # subset
#
# Pre-reqs:
#   - aws CLI configured with the deploy profile.
#   - Lambdas listed in $LambdaTargets must already exist (audit them via
#     `aws lambda list-functions --query "Functions[?starts_with(FunctionName,'supervisor-')].FunctionName"`).
#   - Authorizer ID `tmp1if` must exist on the API (this is the existing
#     kb-stack JWT authorizer; we reuse it).

[CmdletBinding()]
param(
    [string]$ApiId = "anf38iju12",
    [string]$Region = "ap-southeast-1",
    [string]$AuthorizerId = "tmp1if",
    [string]$StageName = "prod",
    [string[]]$Routes,
    [switch]$Deploy,
    [switch]$DryRun
)

# Per-action error handling: each AWS call below checks $LASTEXITCODE
# explicitly and throws into the per-route try/catch. We don't want the
# outer "Stop" preference because PowerShell treats AWS CLI's stderr
# warnings (e.g. expired-creds nags, deprecation banners) as terminating
# errors, which kills the whole loop after one route.
$ErrorActionPreference = "Continue"

# ---------------------------------------------------------------------
# Route definitions - single source of truth, mirrors ENDPOINT_INVENTORY.md
# ---------------------------------------------------------------------

$RouteDefs = @(
    # Threads (11)
    @{ Method = "POST";   Path = "/threads";                                  Lambda = "supervisor-create-thread" }
    @{ Method = "POST";   Path = "/threads/create-with-upload";               Lambda = "supervisor-create-thread-upload" }
    @{ Method = "GET";    Path = "/threads";                                  Lambda = "supervisor-list-threads" }
    @{ Method = "GET";    Path = "/threads/search";                           Lambda = "supervisor-search-threads" }
    @{ Method = "GET";    Path = "/threads/{thread_id}";                      Lambda = "supervisor-get-thread" }
    @{ Method = "GET";    Path = "/threads/{thread_id}/messages";             Lambda = "supervisor-get-messages" }
    @{ Method = "PUT";    Path = "/threads/{thread_id}";                      Lambda = "supervisor-update-thread" }
    @{ Method = "DELETE"; Path = "/threads/{thread_id}";                      Lambda = "supervisor-delete-thread" }
    @{ Method = "POST";   Path = "/threads/{thread_id}/messages";             Lambda = "supervisor-post-message" }
    @{ Method = "POST";   Path = "/threads/{thread_id}/messages/upload";      Lambda = "supervisor-post-message-upload" }
    @{ Method = "GET";    Path = "/threads/{thread_id}/progress";             Lambda = "supervisor-get-progress" }

    # Actions (4)
    @{ Method = "GET";    Path = "/actions/pending";                          Lambda = "supervisor-actions-pending" }
    @{ Method = "GET";    Path = "/action/{action_id}";                       Lambda = "supervisor-action-get" }
    @{ Method = "POST";   Path = "/action/approve/{action_id}";               Lambda = "supervisor-action-approve" }
    @{ Method = "POST";   Path = "/actions/cleanup";                          Lambda = "supervisor-actions-cleanup" }

    # Logs (6)
    @{ Method = "GET";    Path = "/logs";                                     Lambda = "supervisor-logs-list" }
    @{ Method = "GET";    Path = "/logs/search";                              Lambda = "supervisor-logs-search" }
    @{ Method = "GET";    Path = "/logs/stats";                               Lambda = "supervisor-logs-stats" }
    @{ Method = "GET";    Path = "/logs/requests/{request_id}";               Lambda = "supervisor-logs-by-request" }
    @{ Method = "DELETE"; Path = "/logs";                                     Lambda = "supervisor-logs-clear" }
    @{ Method = "GET";    Path = "/agents/metrics";                           Lambda = "supervisor-agents-metrics" }

    # Admin (12)
    @{ Method = "GET";    Path = "/admin/logs";                               Lambda = "supervisor-admin-logs" }
    @{ Method = "GET";    Path = "/admin/activity";                           Lambda = "supervisor-admin-activity" }
    @{ Method = "GET";    Path = "/admin/activity/summary";                   Lambda = "supervisor-admin-activity-summary" }
    @{ Method = "GET";    Path = "/admin/health";                             Lambda = "supervisor-admin-health" }
    @{ Method = "GET";    Path = "/admin/alerts";                             Lambda = "supervisor-admin-alerts" }
    @{ Method = "GET";    Path = "/admin/usage/summary";                      Lambda = "supervisor-admin-usage-summary" }
    @{ Method = "GET";    Path = "/admin/pricing";                            Lambda = "supervisor-admin-pricing-list" }
    @{ Method = "PUT";    Path = "/admin/pricing/{model}";                    Lambda = "supervisor-admin-pricing-update" }
    @{ Method = "GET";    Path = "/admin/settings/budget";                    Lambda = "supervisor-admin-budget-get" }
    @{ Method = "PUT";    Path = "/admin/settings/budget";                    Lambda = "supervisor-admin-budget-update" }
    @{ Method = "GET";    Path = "/admin/metrics";                            Lambda = "supervisor-admin-metrics" }
    @{ Method = "GET";    Path = "/admin/metrics/internal";                   Lambda = "supervisor-admin-metrics-internal" }

    # Misc (3)
    @{ Method = "GET";    Path = "/";                                         Lambda = "supervisor-health" }
    @{ Method = "GET";    Path = "/health";                                   Lambda = "supervisor-health" }
    @{ Method = "POST";   Path = "/workflow";                                 Lambda = "supervisor-workflow" }
)

# Optional per-run filter. PowerShell 5.x's `-in` operator is finicky with
# arrays of hashtables when the filter expression returns multiple values
# from the LHS - so we build a hashset and check explicit membership. Also
# preserves the original $RouteDefs order (Where-Object does that anyway).
if ($Routes -and $Routes.Count -gt 0) {
    $routeSet = @{}
    foreach ($k in $Routes) { $routeSet[$k.Trim()] = $true }
    $filtered = @()
    foreach ($r in $RouteDefs) {
        $key = $r.Method + " " + $r.Path
        if ($routeSet.ContainsKey($key)) { $filtered += ,$r }
    }
    $RouteDefs = $filtered
    if ($RouteDefs.Count -eq 0) { throw "No matching routes for filter: $($Routes -join ', ')" }
}

Write-Host ""
Write-Host "REST API wiring plan" -ForegroundColor Cyan
Write-Host ("  API:        " + $ApiId)
Write-Host ("  Region:     " + $Region)
Write-Host ("  Authorizer: " + $AuthorizerId + " (jwt-api-authorizer, TOKEN)")
Write-Host ("  Routes:     " + $RouteDefs.Count)
Write-Host ("  Deploy:     " + $Deploy.IsPresent)
Write-Host ("  DryRun:     " + $DryRun.IsPresent)
Write-Host ""

$AccountId = (aws sts get-caller-identity --query Account --output text).Trim()
if (-not $AccountId) { throw "Could not get account id from STS" }
Write-Host ("AWS account: " + $AccountId) -ForegroundColor Gray

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

function Get-AllResources {
    param([string]$ApiId, [string]$Region)
    # Returns a hashtable: path -> @{ Id; Methods }
    $items = aws apigateway get-resources --rest-api-id $ApiId --region $Region --limit 500 --output json | ConvertFrom-Json
    $map = @{}
    foreach ($r in $items.items) {
        $methods = @()
        if ($r.resourceMethods) { $methods = $r.resourceMethods.PSObject.Properties.Name }
        $map[$r.path] = @{ Id = $r.id; Methods = $methods }
    }
    return $map
}

function Ensure-Resource {
    param(
        [string]$ApiId,
        [string]$Region,
        [hashtable]$ResourceMap,
        [string]$Path
    )
    # Walks `/a/b/c` ensuring each prefix exists. Returns the leaf resource id.
    if ($Path -eq "/") { return $ResourceMap["/"].Id }

    $segments = $Path.TrimStart("/").Split("/")
    $parentPath = "/"
    foreach ($seg in $segments) {
        $childPath = if ($parentPath -eq "/") { "/" + $seg } else { $parentPath + "/" + $seg }
        if ($ResourceMap.ContainsKey($childPath)) {
            $parentPath = $childPath
            continue
        }
        $parentId = $ResourceMap[$parentPath].Id
        if (-not $parentId) { throw "Lost parent for $childPath (parentPath=$parentPath)" }
        if ($DryRun) {
            Write-Host ("    [dry-run] would create resource " + $childPath + " under parent " + $parentPath)
            # Add a placeholder so subsequent path segments (and subsequent
            # routes) can resolve their parent without re-printing the same
            # creation line. In real-run mode the create-resource call below
            # adds the real id.
            $ResourceMap[$childPath] = @{ Id = "DRY-RUN-PLACEHOLDER"; Methods = @() }
        } else {
            $newId = aws apigateway create-resource `
                --rest-api-id $ApiId `
                --region $Region `
                --parent-id $parentId `
                --path-part $seg `
                --query "id" --output text 2>&1
            if ($LASTEXITCODE -ne 0) {
                # Recovery path: API Gateway's get-resources is eventually
                # consistent. A prior run (or another process) may have
                # created this exact resource milliseconds ago, leaving it
                # absent from our cached map but already present on AWS. The
                # error string includes "ConflictException" + "same parent
                # already has this name". Refetch the parent's children and
                # find ours.
                if ($newId -match "ConflictException") {
                    $children = aws apigateway get-resources --rest-api-id $ApiId --region $Region --limit 500 --output json 2>$null | ConvertFrom-Json
                    $found = $children.items | Where-Object { $_.parentId -eq $parentId -and $_.pathPart -eq $seg } | Select-Object -First 1
                    if ($found) {
                        $ResourceMap[$childPath] = @{ Id = $found.id; Methods = if ($found.resourceMethods) { @($found.resourceMethods.PSObject.Properties.Name) } else { @() } }
                        Write-Host ("    = resource " + $childPath + " already exists (recovered " + $found.id + ")") -ForegroundColor DarkGray
                        $parentPath = $childPath
                        continue
                    }
                }
                throw ("create-resource failed for " + $childPath + ": " + $newId)
            }
            $ResourceMap[$childPath] = @{ Id = $newId.Trim(); Methods = @() }
            Write-Host ("    + created resource " + $childPath + " (" + $newId.Trim() + ")") -ForegroundColor Green
        }
        $parentPath = $childPath
    }
    return $ResourceMap[$Path].Id
}

function Ensure-Method {
    param(
        [string]$ApiId,
        [string]$Region,
        [string]$ResourceId,
        [string]$Method,
        [string]$AuthType,
        [string]$AuthorizerId
    )
    if ($DryRun) {
        Write-Host ("    [dry-run] would create method " + $Method + " (auth=" + $AuthType + ")")
        return $false
    }

    # Idempotent: if the method already exists, leaves it alone.
    $existing = aws apigateway get-method --rest-api-id $ApiId --region $Region --resource-id $ResourceId --http-method $Method 2>$null
    if ($LASTEXITCODE -eq 0) { return $true }  # already exists

    $args = @(
        "apigateway", "put-method",
        "--rest-api-id", $ApiId,
        "--region", $Region,
        "--resource-id", $ResourceId,
        "--http-method", $Method,
        "--authorization-type", $AuthType
    )
    if ($AuthType -eq "CUSTOM" -and $AuthorizerId) {
        $args += @("--authorizer-id", $AuthorizerId)
    }
    $putErr = & aws @args 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        # Same eventual-consistency story as Ensure-Resource: an earlier run
        # may have already created this method.
        if ($putErr -match "ConflictException" -or $putErr -match "already exists") {
            Write-Host ("    = method " + $Method + " already exists") -ForegroundColor DarkGray
            return $true
        }
        throw ("put-method failed for " + $Method + ": " + $putErr)
    }
    Write-Host ("    + method " + $Method + " (auth=" + $AuthType + ")") -ForegroundColor Green
    return $false
}

function Ensure-LambdaIntegration {
    param(
        [string]$ApiId,
        [string]$Region,
        [string]$ResourceId,
        [string]$Method,
        [string]$LambdaName,
        [string]$AccountId
    )
    if ($DryRun) {
        Write-Host ("    [dry-run] would link integration " + $Method + " -> " + $LambdaName) -ForegroundColor DarkYellow
        return
    }
    $lambdaArn = "arn:aws:lambda:" + $Region + ":" + $AccountId + ":function:" + $LambdaName
    $integrationUri = "arn:aws:apigateway:" + $Region + ":lambda:path/2015-03-31/functions/" + $lambdaArn + "/invocations"

    aws apigateway put-integration `
        --rest-api-id $ApiId `
        --region $Region `
        --resource-id $ResourceId `
        --http-method $Method `
        --type AWS_PROXY `
        --integration-http-method POST `
        --uri $integrationUri | Out-Null
    if ($LASTEXITCODE -ne 0) { throw ("put-integration failed for " + $Method + " -> " + $LambdaName) }
    Write-Host ("    + integration -> " + $LambdaName) -ForegroundColor Green
}

function Ensure-LambdaPermission {
    param(
        [string]$LambdaName,
        [string]$ApiId,
        [string]$Region,
        [string]$AccountId,
        [string]$Method,
        [string]$Path
    )
    # The statement ID must be deterministic per (lambda, method, path). The
    # source ARN is the API Gateway invocation ARN - we use a wildcard stage
    # so a single permission statement covers prod + any future stages.
    $sid = "apigw-" + $Method + "-" + ($Path -replace "[^A-Za-z0-9_]", "_")
    if ($sid.Length -gt 100) { $sid = $sid.Substring(0, 100) }
    $sourceArn = "arn:aws:execute-api:" + $Region + ":" + $AccountId + ":" + $ApiId + "/*/" + $Method + $Path

    if ($DryRun) {
        Write-Host ("    [dry-run] would add invoke permission sid=" + $sid)
        return
    }

    # add-permission errors with `ResourceConflictException` if the statement
    # already exists. Treat that as success.
    $err = aws lambda add-permission `
        --function-name $LambdaName `
        --region $Region `
        --statement-id $sid `
        --action "lambda:InvokeFunction" `
        --principal apigateway.amazonaws.com `
        --source-arn $sourceArn 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host ("    + lambda invoke permission " + $sid) -ForegroundColor Green
    } elseif ($err -match "ResourceConflictException") {
        Write-Host ("    = lambda invoke permission " + $sid + " already present") -ForegroundColor DarkGray
    } else {
        throw ("lambda add-permission failed: " + $err)
    }
}

function Ensure-CorsOptions {
    param(
        [string]$ApiId,
        [string]$Region,
        [string]$ResourceId,
        [string]$Path
    )
    if ($DryRun) {
        Write-Host ("    [dry-run] would add OPTIONS for CORS")
        return
    }

    # MOCK integration on OPTIONS that returns the CORS headers. The Lambda
    # functions also return CORS on real responses (CORS_HEADERS in
    # shared/lambda_helpers.py), so this MOCK only covers the preflight.
    #
    # Idempotence: detect partial state by inspecting the four sub-resources
    # individually (method, method-response, integration, integration-
    # response). Earlier prototype runs sometimes left integration-response
    # missing because of a JSON-quoting bug; a re-run detected the method and
    # bailed without finishing the wiring.
    $existing = aws apigateway get-method --rest-api-id $ApiId --region $Region --resource-id $ResourceId --http-method OPTIONS --output json 2>$null
    $methodExists = ($LASTEXITCODE -eq 0)
    $integrationExists = $false
    $integrationResponseExists = $false
    $methodResponseExists = $false
    if ($methodExists) {
        $existingObj = try { $existing | ConvertFrom-Json } catch { $null }
        if ($existingObj) {
            if ($existingObj.PSObject.Properties.Name -contains 'methodResponses' -and $existingObj.methodResponses) {
                $methodResponseExists = ($existingObj.methodResponses.PSObject.Properties.Name -contains '200')
            }
            if ($existingObj.PSObject.Properties.Name -contains 'methodIntegration' -and $existingObj.methodIntegration) {
                $integrationExists = $true
                if ($existingObj.methodIntegration.PSObject.Properties.Name -contains 'integrationResponses' -and $existingObj.methodIntegration.integrationResponses) {
                    $integrationResponseExists = ($existingObj.methodIntegration.integrationResponses.PSObject.Properties.Name -contains '200')
                }
            }
        }
    }
    if ($methodExists -and $methodResponseExists -and $integrationExists -and $integrationResponseExists) {
        Write-Host ("    = OPTIONS already configured (full)") -ForegroundColor DarkGray
        return
    }
    if ($methodExists) {
        Write-Host ("    ~ OPTIONS partial (method=$methodExists, mr=$methodResponseExists, int=$integrationExists, ir=$integrationResponseExists) - completing") -ForegroundColor Yellow
    }

    # PowerShell + AWS CLI inline-JSON quoting is brittle, so we write each
    # JSON payload to a tempfile and pass it via file://. Encoding is
    # explicitly UTF-8 *without* BOM (AWS CLI rejects BOM-prefixed files).
    $tmpDir = Join-Path $env:TEMP ("apigw-cors-" + [System.Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null
    try {
        $methodRespJson = '{"method.response.header.Access-Control-Allow-Origin":true,"method.response.header.Access-Control-Allow-Methods":true,"method.response.header.Access-Control-Allow-Headers":true}'
        $integrationReqJson = '{"application/json":"{\"statusCode\":200}"}'
        # API Gateway requires the *literal* string `'*'` (single-quote +
        # asterisk + single-quote) as the response value - the runtime echos
        # this back as the header. Build it via a here-string so PowerShell
        # doesn't try to interpolate or escape it.
        $integrationRespJson = @'
{
  "method.response.header.Access-Control-Allow-Origin":"'*'",
  "method.response.header.Access-Control-Allow-Methods":"'GET,POST,PUT,DELETE,OPTIONS'",
  "method.response.header.Access-Control-Allow-Headers":"'Content-Type,Authorization,X-Amz-Date,X-Api-Key'"
}
'@

        $mrPath = Join-Path $tmpDir "method-response.json"
        $irqPath = Join-Path $tmpDir "integration-request.json"
        $irsPath = Join-Path $tmpDir "integration-response.json"
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($mrPath, $methodRespJson, $utf8NoBom)
        [System.IO.File]::WriteAllText($irqPath, $integrationReqJson, $utf8NoBom)
        [System.IO.File]::WriteAllText($irsPath, $integrationRespJson, $utf8NoBom)

        # 1. Method (only if missing)
        if (-not $methodExists) {
            aws apigateway put-method `
                --rest-api-id $ApiId --region $Region `
                --resource-id $ResourceId --http-method OPTIONS `
                --authorization-type NONE | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "OPTIONS put-method failed" }
        }

        # 2. Method response (only if missing)
        if (-not $methodResponseExists) {
            aws apigateway put-method-response `
                --rest-api-id $ApiId --region $Region `
                --resource-id $ResourceId --http-method OPTIONS `
                --status-code 200 `
                --response-parameters "file://$mrPath" | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "OPTIONS put-method-response failed" }
        }

        # 3. MOCK integration (only if missing)
        if (-not $integrationExists) {
            aws apigateway put-integration `
                --rest-api-id $ApiId --region $Region `
                --resource-id $ResourceId --http-method OPTIONS `
                --type MOCK `
                --request-templates "file://$irqPath" | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "OPTIONS put-integration failed" }
        }

        # 4. Integration response (only if missing) - echoes headers back
        if (-not $integrationResponseExists) {
            aws apigateway put-integration-response `
                --rest-api-id $ApiId --region $Region `
                --resource-id $ResourceId --http-method OPTIONS `
                --status-code 200 `
                --response-parameters "file://$irsPath" | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "OPTIONS put-integration-response failed" }
        }

        Write-Host "    + OPTIONS (MOCK CORS)" -ForegroundColor Green
    }
    finally {
        Remove-Item $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

Write-Host "Loading existing resource tree..." -ForegroundColor Gray
$resourceMap = Get-AllResources -ApiId $ApiId -Region $Region
Write-Host ("  loaded " + $resourceMap.Count + " resources") -ForegroundColor Gray

$failures = @()
$ix = 0
foreach ($r in $RouteDefs) {
    $ix++
    $tag = "[" + $ix + "/" + $RouteDefs.Count + "]"
    Write-Host ""
    Write-Host ($tag + " " + $r.Method + " " + $r.Path + " -> " + $r.Lambda) -ForegroundColor Cyan

    try {
        # 1. Walk path; create resources as needed.
        $resourceId = Ensure-Resource -ApiId $ApiId -Region $Region -ResourceMap $resourceMap -Path $r.Path
        if (-not $resourceId -and -not $DryRun) {
            throw ("Could not resolve resourceId for " + $r.Path)
        }

        # Re-load methods for this resource (they may have changed since the
        # initial fetch). In dry-run mode the resource doesn't actually exist
        # yet, so skip the round-trip - Ensure-Method also branches on
        # DryRun before any AWS call.
        #
        # Defensive coding here: a freshly-created resource has no
        # `resourceMethods` key in the JSON response, so $rinfo.resourceMethods
        # is $null. Calling .PSObject on $null trips strict-mode handling.
        if (-not $DryRun) {
            $rinfoJson = aws apigateway get-resource --rest-api-id $ApiId --region $Region --resource-id $resourceId --output json 2>$null
            $methods = @()
            if ($rinfoJson) {
                try {
                    $rinfo = $rinfoJson | ConvertFrom-Json -ErrorAction SilentlyContinue
                    if ($rinfo -and $rinfo.PSObject.Properties.Name -contains 'resourceMethods' -and $rinfo.resourceMethods) {
                        $methods = @($rinfo.resourceMethods.PSObject.Properties.Name)
                    }
                } catch {
                    # leave $methods empty
                }
            }
            $resourceMap[$r.Path].Methods = $methods
        }

        # 2. Method (with custom authorizer)
        $null = Ensure-Method -ApiId $ApiId -Region $Region -ResourceId $resourceId -Method $r.Method -AuthType "CUSTOM" -AuthorizerId $AuthorizerId

        # 3. Integration (always re-link to handle Lambda re-creation cases)
        Ensure-LambdaIntegration -ApiId $ApiId -Region $Region -ResourceId $resourceId -Method $r.Method -LambdaName $r.Lambda -AccountId $AccountId

        # 4. Lambda invoke permission
        Ensure-LambdaPermission -LambdaName $r.Lambda -ApiId $ApiId -Region $Region -AccountId $AccountId -Method $r.Method -Path $r.Path

        # 5. CORS preflight on the same resource
        Ensure-CorsOptions -ApiId $ApiId -Region $Region -ResourceId $resourceId -Path $r.Path
    }
    catch {
        Write-Host ("  [fail] " + $_) -ForegroundColor Red
        $failures += ($r.Method + " " + $r.Path + " -> " + $r.Lambda + ": " + $_)
    }
}

Write-Host ""
Write-Host "Wiring summary:" -ForegroundColor Cyan
if ($failures.Count -eq 0) {
    Write-Host ("  [ok] all " + $RouteDefs.Count + " routes processed") -ForegroundColor Green
} else {
    Write-Host ("  [fail] " + $failures.Count + " of " + $RouteDefs.Count + " routes failed:") -ForegroundColor Red
    $failures | ForEach-Object { Write-Host ("    - " + $_) -ForegroundColor Red }
}

if ($Deploy -and $failures.Count -eq 0 -and -not $DryRun) {
    Write-Host ""
    Write-Host "Deploying prod stage..." -ForegroundColor Cyan
    aws apigateway create-deployment `
        --rest-api-id $ApiId `
        --region $Region `
        --stage-name $StageName `
        --description "AI Assistant migration: 36 supervisor routes" | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host ("  [ok] deployed " + $StageName + " stage") -ForegroundColor Green
    } else {
        Write-Host "  [fail] deployment failed" -ForegroundColor Red
    }
} elseif ($Deploy -and $failures.Count -gt 0) {
    Write-Host "  [skip] not deploying because some routes failed" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done." -ForegroundColor Gray
