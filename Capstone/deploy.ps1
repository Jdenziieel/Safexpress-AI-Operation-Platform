#!/usr/bin/env pwsh
# Complete deployment script - builds and deploys to AWS S3 + CloudFront
# Usage: .\deploy.ps1

param(
    [Parameter(Mandatory=$false)]
    [string]$BucketName = "safexpressops-frontend",
    
    [Parameter(Mandatory=$false)]
    [string]$DistributionId = "EASISGRLJMW51",
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipBuild = $false,
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipInvalidation = $false
)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Magenta
Write-Host "   SafeXpress OPS - AWS Deployment" -ForegroundColor Magenta
Write-Host "========================================" -ForegroundColor Magenta
Write-Host ""

# Step 1: Build the application
if (-not $SkipBuild) {
    Write-Host "[1/3] Building application..." -ForegroundColor Cyan
    Write-Host "Running: npm run build" -ForegroundColor Gray
    
    npm run build
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Build failed!" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "✅ Build successful!" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "[1/3] Skipping build (--SkipBuild flag set)" -ForegroundColor Yellow
    Write-Host ""
}

# Step 2: Upload to S3 with correct Content-Type headers
Write-Host "[2/3] Uploading to S3..." -ForegroundColor Cyan
Write-Host "Bucket: $BucketName" -ForegroundColor Gray

$distPath = "dist"
if (-not (Test-Path $distPath)) {
    Write-Host "❌ Error: dist folder not found!" -ForegroundColor Red
    Write-Host "Please run 'npm run build' first." -ForegroundColor Red
    exit 1
}

Push-Location $distPath

try {
    # Upload HTML files (no cache)
    Write-Host "  → HTML files..." -ForegroundColor Gray
    aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.html" `
        --content-type "text/html" `
        --cache-control "no-cache, no-store, must-revalidate" `
        --metadata-directive REPLACE

    # Upload JavaScript files (1 year cache)
    Write-Host "  → JavaScript files..." -ForegroundColor Gray
    aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.js" `
        --content-type "application/javascript" `
        --cache-control "max-age=31536000, immutable" `
        --metadata-directive REPLACE

    # Upload CSS files (1 year cache)
    Write-Host "  → CSS files..." -ForegroundColor Gray
    aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.css" `
        --content-type "text/css" `
        --cache-control "max-age=31536000, immutable" `
        --metadata-directive REPLACE

    # Upload JSON files
    Write-Host "  → JSON files..." -ForegroundColor Gray
    aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.json" `
        --content-type "application/json" `
        --cache-control "no-cache"

    # Upload images
    Write-Host "  → Image files..." -ForegroundColor Gray
    aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.png" `
        --content-type "image/png" --cache-control "max-age=31536000"
    aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.jpg" `
        --content-type "image/jpeg" --cache-control "max-age=31536000"
    aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.jpeg" `
        --content-type "image/jpeg" --cache-control "max-age=31536000"
    aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.svg" `
        --content-type "image/svg+xml" --cache-control "max-age=31536000"
    aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.gif" `
        --content-type "image/gif" --cache-control "max-age=31536000"
    aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.ico" `
        --content-type "image/x-icon" --cache-control "max-age=31536000"
    aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.webp" `
        --content-type "image/webp" --cache-control "max-age=31536000"

    # Upload fonts
    Write-Host "  → Font files..." -ForegroundColor Gray
    aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.woff" `
        --content-type "font/woff" --cache-control "max-age=31536000"
    aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.woff2" `
        --content-type "font/woff2" --cache-control "max-age=31536000"
    aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.ttf" `
        --content-type "font/ttf" --cache-control "max-age=31536000"
    aws s3 sync . "s3://$BucketName/" --exclude "*" --include "*.otf" `
        --content-type "font/otf" --cache-control "max-age=31536000"

    Write-Host "✅ Upload successful!" -ForegroundColor Green
    Write-Host ""
    
} catch {
    Write-Host "❌ Upload failed: $_" -ForegroundColor Red
    Pop-Location
    exit 1
} finally {
    Pop-Location
}

# Step 3: Invalidate CloudFront cache
if (-not $SkipInvalidation) {
    Write-Host "[3/3] Invalidating CloudFront cache..." -ForegroundColor Cyan
    Write-Host "Distribution ID: $DistributionId" -ForegroundColor Gray
    
    $invalidation = aws cloudfront create-invalidation `
        --distribution-id $DistributionId `
        --paths "/*" `
        --output json | ConvertFrom-Json
    
    if ($LASTEXITCODE -eq 0) {
        $invalidationId = $invalidation.Invalidation.Id
        Write-Host "✅ Cache invalidation started!" -ForegroundColor Green
        Write-Host "   Invalidation ID: $invalidationId" -ForegroundColor Gray
        Write-Host "   This may take 5-15 minutes to complete." -ForegroundColor Gray
    } else {
        Write-Host "❌ Cache invalidation failed!" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "[3/3] Skipping CloudFront invalidation (--SkipInvalidation flag set)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Magenta
Write-Host "   🚀 Deployment Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Magenta
Write-Host ""
Write-Host "Your app is deployed at:" -ForegroundColor Cyan
Write-Host "https://d235efx2egjlji.cloudfront.net" -ForegroundColor White
Write-Host ""
Write-Host "Note: If you see old content, wait 5-15 minutes for cache invalidation." -ForegroundColor Yellow
Write-Host ""
