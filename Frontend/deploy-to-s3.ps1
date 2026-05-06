# Deploy script with correct Content-Type headers.
#
# IMPORTANT — DO NOT add `--delete` to any aws s3 sync command in this script.
# Both deployment buckets (safexpressops-frontend AND frontend-safexpress) are
# SHARED with non-frontend prefixes:
#   - uploads/...        → KB user-uploaded PDFs (NOT recoverable, versioning OFF)
#   - lambda-packages/... → Lambda code-zip backups
# A `--delete` sync would wipe those siblings. Stale frontend assets are
# acceptable; lost user uploads are NOT. (Learned the hard way 2026-05-03 on
# frontend-safexpress — two live KB documents and three orphan uploads were
# permanently destroyed.)
#
# Known buckets / distributions:
#   safexpressops-frontend → EASISGRLJMW51 → d235efx2egjlji.cloudfront.net
#   frontend-safexpress    → E24R286JHHQ55F → d2q36i8ewtxnwb.cloudfront.net (current prod)

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet("safexpressops-frontend", "frontend-safexpress")]
    [string]$BucketName = "frontend-safexpress",

    [Parameter(Mandatory=$false)]
    [string]$DistributionId = ""
)

# Auto-resolve distribution id if caller passed only a bucket
if ([string]::IsNullOrWhiteSpace($DistributionId)) {
    $DistributionId = switch ($BucketName) {
        "safexpressops-frontend" { "EASISGRLJMW51" }
        "frontend-safexpress"    { "E24R286JHHQ55F" }
    }
}

Write-Host "Starting deployment to S3 bucket: $BucketName (distribution: $DistributionId)" -ForegroundColor Green

# Navigate to dist directory
$distPath = "dist"
if (-not (Test-Path $distPath)) {
    Write-Host "Error: dist folder not found. Run 'npm run build' first." -ForegroundColor Red
    exit 1
}

Set-Location $distPath

# Upload HTML files
Write-Host "Uploading HTML files..." -ForegroundColor Cyan
aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.html" --content-type "text/html" --cache-control "no-cache"

# Upload JavaScript files
Write-Host "Uploading JavaScript files..." -ForegroundColor Cyan
aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.js" --content-type "application/javascript" --cache-control "max-age=31536000"

# Upload CSS files
Write-Host "Uploading CSS files..." -ForegroundColor Cyan
aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.css" --content-type "text/css" --cache-control "max-age=31536000"

# Upload JSON files
Write-Host "Uploading JSON files..." -ForegroundColor Cyan
aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.json" --content-type "application/json"

# Upload image files
Write-Host "Uploading image files..." -ForegroundColor Cyan
aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.png" --content-type "image/png" --cache-control "max-age=31536000"
aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.jpg" --content-type "image/jpeg" --cache-control "max-age=31536000"
aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.jpeg" --content-type "image/jpeg" --cache-control "max-age=31536000"
aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.svg" --content-type "image/svg+xml" --cache-control "max-age=31536000"
aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.gif" --content-type "image/gif" --cache-control "max-age=31536000"
aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.ico" --content-type "image/x-icon" --cache-control "max-age=31536000"

# Upload any remaining files
Write-Host "Uploading remaining files..." -ForegroundColor Cyan
aws s3 sync . "s3://$BucketName/" --exclude "*.html" --exclude "*.js" --exclude "*.css" --exclude "*.json" --exclude "*.png" --exclude "*.jpg" --exclude "*.jpeg" --exclude "*.svg" --exclude "*.gif" --exclude "*.ico"

Set-Location ..

Write-Host "`nUpload complete!" -ForegroundColor Green

# Invalidate CloudFront cache if distribution ID provided
if ($DistributionId) {
    Write-Host "`nInvalidating CloudFront cache..." -ForegroundColor Cyan
    aws cloudfront create-invalidation --distribution-id $DistributionId --paths "/*"
    Write-Host "Cache invalidation started. This may take a few minutes." -ForegroundColor Green
} else {
    Write-Host "`nSkipping CloudFront invalidation (no distribution ID provided)." -ForegroundColor Yellow
    Write-Host "To invalidate cache later, run:" -ForegroundColor Yellow
    Write-Host "aws cloudfront create-invalidation --distribution-id YOUR_DISTRIBUTION_ID --paths '/*'" -ForegroundColor Yellow
}

Write-Host "`nDeployment complete! 🚀" -ForegroundColor Green
