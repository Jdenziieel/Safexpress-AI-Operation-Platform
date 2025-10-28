#!/bin/bash
# Complete deployment script - builds and deploys to AWS S3 + CloudFront
# Usage: ./deploy.sh

set -e  # Exit on error

BUCKET_NAME="safexpressops-frontend"
DISTRIBUTION_ID="EASISGRLJMW51"
SKIP_BUILD=false
SKIP_INVALIDATION=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --skip-invalidation)
            SKIP_INVALIDATION=true
            shift
            ;;
        --bucket)
            BUCKET_NAME="$2"
            shift 2
            ;;
        --distribution-id)
            DISTRIBUTION_ID="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "========================================"
echo "   SafeXpress OPS - AWS Deployment"
echo "========================================"
echo ""

# Step 1: Build the application
if [ "$SKIP_BUILD" = false ]; then
    echo "[1/3] Building application..."
    echo "Running: npm run build"
    
    npm run build
    
    echo "✅ Build successful!"
    echo ""
else
    echo "[1/3] Skipping build (--skip-build flag set)"
    echo ""
fi

# Step 2: Upload to S3
echo "[2/3] Uploading to S3..."
echo "Bucket: $BUCKET_NAME"

if [ ! -d "dist" ]; then
    echo "❌ Error: dist folder not found!"
    echo "Please run 'npm run build' first."
    exit 1
fi

cd dist

# Upload HTML files (no cache)
echo "  → HTML files..."
aws s3 sync . "s3://$BUCKET_NAME/" --exclude "*" --include "*.html" \
    --content-type "text/html" \
    --cache-control "no-cache, no-store, must-revalidate" \
    --metadata-directive REPLACE

# Upload JavaScript files (1 year cache)
echo "  → JavaScript files..."
aws s3 sync . "s3://$BUCKET_NAME/" --exclude "*" --include "*.js" \
    --content-type "application/javascript" \
    --cache-control "max-age=31536000, immutable" \
    --metadata-directive REPLACE

# Upload CSS files (1 year cache)
echo "  → CSS files..."
aws s3 sync . "s3://$BUCKET_NAME/" --exclude "*" --include "*.css" \
    --content-type "text/css" \
    --cache-control "max-age=31536000, immutable" \
    --metadata-directive REPLACE

# Upload JSON files
echo "  → JSON files..."
aws s3 sync . "s3://$BUCKET_NAME/" --exclude "*" --include "*.json" \
    --content-type "application/json" \
    --cache-control "no-cache"

# Upload images
echo "  → Image files..."
aws s3 sync . "s3://$BUCKET_NAME/" --exclude "*" --include "*.png" \
    --content-type "image/png" --cache-control "max-age=31536000"
aws s3 sync . "s3://$BUCKET_NAME/" --exclude "*" --include "*.jpg" \
    --content-type "image/jpeg" --cache-control "max-age=31536000"
aws s3 sync . "s3://$BUCKET_NAME/" --exclude "*" --include "*.jpeg" \
    --content-type "image/jpeg" --cache-control "max-age=31536000"
aws s3 sync . "s3://$BUCKET_NAME/" --exclude "*" --include "*.svg" \
    --content-type "image/svg+xml" --cache-control "max-age=31536000"
aws s3 sync . "s3://$BUCKET_NAME/" --exclude "*" --include "*.gif" \
    --content-type "image/gif" --cache-control "max-age=31536000"
aws s3 sync . "s3://$BUCKET_NAME/" --exclude "*" --include "*.ico" \
    --content-type "image/x-icon" --cache-control "max-age=31536000"
aws s3 sync . "s3://$BUCKET_NAME/" --exclude "*" --include "*.webp" \
    --content-type "image/webp" --cache-control "max-age=31536000"

# Upload fonts
echo "  → Font files..."
aws s3 sync . "s3://$BUCKET_NAME/" --exclude "*" --include "*.woff" \
    --content-type "font/woff" --cache-control "max-age=31536000"
aws s3 sync . "s3://$BUCKET_NAME/" --exclude "*" --include "*.woff2" \
    --content-type "font/woff2" --cache-control "max-age=31536000"
aws s3 sync . "s3://$BUCKET_NAME/" --exclude "*" --include "*.ttf" \
    --content-type "font/ttf" --cache-control "max-age=31536000"
aws s3 sync . "s3://$BUCKET_NAME/" --exclude "*" --include "*.otf" \
    --content-type "font/otf" --cache-control "max-age=31536000"

cd ..

echo "✅ Upload successful!"
echo ""

# Step 3: Invalidate CloudFront cache
if [ "$SKIP_INVALIDATION" = false ]; then
    echo "[3/3] Invalidating CloudFront cache..."
    echo "Distribution ID: $DISTRIBUTION_ID"
    
    INVALIDATION_OUTPUT=$(aws cloudfront create-invalidation \
        --distribution-id "$DISTRIBUTION_ID" \
        --paths "/*" \
        --output json)
    
    INVALIDATION_ID=$(echo "$INVALIDATION_OUTPUT" | grep -o '"Id": "[^"]*"' | cut -d'"' -f4)
    
    echo "✅ Cache invalidation started!"
    echo "   Invalidation ID: $INVALIDATION_ID"
    echo "   This may take 5-15 minutes to complete."
else
    echo "[3/3] Skipping CloudFront invalidation (--skip-invalidation flag set)"
fi

echo ""
echo "========================================"
echo "   🚀 Deployment Complete!"
echo "========================================"
echo ""
echo "Your app is deployed at:"
echo "https://d235efx2egjlji.cloudfront.net"
echo ""
echo "Note: If you see old content, wait 5-15 minutes for cache invalidation."
echo ""
