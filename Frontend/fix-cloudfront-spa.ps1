# Fix CloudFront SPA routing for React single-page application
# This adds custom error responses so that direct URL access and page refresh work
# (e.g. navigating directly to /sfx-bot won't return a 403 error)

param(
    [Parameter(Mandatory=$false)]
    [string]$DistributionId = "EASISGRLJMW51"
)

Write-Host "=== CloudFront SPA Routing Fix ===" -ForegroundColor Cyan
Write-Host "Distribution ID: $DistributionId" -ForegroundColor Yellow
Write-Host ""

# Step 1: Get current distribution config
Write-Host "1. Fetching current distribution config..." -ForegroundColor Green
$config = aws cloudfront get-distribution-config --id $DistributionId --output json | ConvertFrom-Json

if (-not $config) {
    Write-Host "ERROR: Failed to get distribution config. Check your AWS credentials and distribution ID." -ForegroundColor Red
    exit 1
}

$etag = $config.ETag
$distConfig = $config.DistributionConfig

Write-Host "   ETag: $etag" -ForegroundColor Gray

# Step 2: Update custom error responses for SPA routing
Write-Host "2. Updating custom error responses for SPA routing..." -ForegroundColor Green

# Add custom error responses: 403 and 404 both redirect to /index.html with 200
$distConfig.CustomErrorResponses = @{
    Quantity = 2
    Items = @(
        @{
            ErrorCode = 403
            ResponsePagePath = "/index.html"
            ResponseCode = "200"
            ErrorCachingMinTTL = 10
        },
        @{
            ErrorCode = 404
            ResponsePagePath = "/index.html"
            ResponseCode = "200"
            ErrorCachingMinTTL = 10
        }
    )
}

# Step 3: Write updated config to temp file
$tempFile = [System.IO.Path]::GetTempFileName()
$distConfig | ConvertTo-Json -Depth 20 | Set-Content $tempFile -Encoding UTF8

Write-Host "3. Applying updated config..." -ForegroundColor Green
aws cloudfront update-distribution --id $DistributionId --if-match $etag --distribution-config file://$tempFile --output json | Out-Null

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "SUCCESS! CloudFront SPA routing is now configured." -ForegroundColor Green
    Write-Host ""
    Write-Host "Custom error responses added:" -ForegroundColor Yellow
    Write-Host "  - 403 Forbidden -> /index.html (200 OK)" -ForegroundColor White
    Write-Host "  - 404 Not Found -> /index.html (200 OK)" -ForegroundColor White
    Write-Host ""
    Write-Host "This means:" -ForegroundColor Yellow
    Write-Host "  - Refreshing on /sfx-bot will now load your React app correctly" -ForegroundColor White
    Write-Host "  - Direct URL navigation to any route will work" -ForegroundColor White
    Write-Host ""
    Write-Host "The change may take a few minutes to propagate across CloudFront edge locations." -ForegroundColor Cyan
} else {
    Write-Host "ERROR: Failed to update distribution. See error above." -ForegroundColor Red
}

# Cleanup
Remove-Item $tempFile -ErrorAction SilentlyContinue
