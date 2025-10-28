# Deploy script with correct Content-Type headers
# Replace YOUR_BUCKET_NAME with your actual S3 bucket name
# Replace YOUR_DISTRIBUTION_ID with your CloudFront distribution ID

param(
    [Parameter(Mandatory=$false)]
    [string]$BucketName = "safexpressops-frontend",
    
    [Parameter(Mandatory=$false)]
    [string]$DistributionId = "EASISGRLJMW51"
)

Write-Host "Starting deployment to S3 bucket: $BucketName" -ForegroundColor Green

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
