@echo off
REM Complete deployment script - builds and deploys to AWS S3 + CloudFront
REM Usage: deploy.bat

echo ========================================
echo    SafeXpress OPS - AWS Deployment
echo ========================================
echo.

REM Step 1: Build the application
echo [1/3] Building application...
echo Running: npm run build

call npm run build

if errorlevel 1 (
    echo Build failed!
    exit /b 1
)

echo Build successful!
echo.

REM Step 2: Upload to S3
echo [2/3] Uploading to S3...
echo Bucket: safexpressops-frontend

if not exist "dist" (
    echo Error: dist folder not found!
    echo Please run 'npm run build' first.
    exit /b 1
)

cd dist

REM Upload HTML files (no cache)
echo   -^> HTML files...
aws s3 sync . s3://safexpressops-frontend/ --exclude "*" --include "*.html" --content-type "text/html" --cache-control "no-cache, no-store, must-revalidate" --metadata-directive REPLACE

REM Upload JavaScript files (1 year cache)
echo   -^> JavaScript files...
aws s3 sync . s3://safexpressops-frontend/ --exclude "*" --include "*.js" --content-type "application/javascript" --cache-control "max-age=31536000, immutable" --metadata-directive REPLACE

REM Upload CSS files (1 year cache)
echo   -^> CSS files...
aws s3 sync . s3://safexpressops-frontend/ --exclude "*" --include "*.css" --content-type "text/css" --cache-control "max-age=31536000, immutable" --metadata-directive REPLACE

REM Upload JSON files
echo   -^> JSON files...
aws s3 sync . s3://safexpressops-frontend/ --exclude "*" --include "*.json" --content-type "application/json" --cache-control "no-cache"

REM Upload images
echo   -^> Image files...
aws s3 sync . s3://safexpressops-frontend/ --exclude "*" --include "*.png" --content-type "image/png" --cache-control "max-age=31536000"
aws s3 sync . s3://safexpressops-frontend/ --exclude "*" --include "*.jpg" --content-type "image/jpeg" --cache-control "max-age=31536000"
aws s3 sync . s3://safexpressops-frontend/ --exclude "*" --include "*.jpeg" --content-type "image/jpeg" --cache-control "max-age=31536000"
aws s3 sync . s3://safexpressops-frontend/ --exclude "*" --include "*.svg" --content-type "image/svg+xml" --cache-control "max-age=31536000"
aws s3 sync . s3://safexpressops-frontend/ --exclude "*" --include "*.gif" --content-type "image/gif" --cache-control "max-age=31536000"
aws s3 sync . s3://safexpressops-frontend/ --exclude "*" --include "*.ico" --content-type "image/x-icon" --cache-control "max-age=31536000"
aws s3 sync . s3://safexpressops-frontend/ --exclude "*" --include "*.webp" --content-type "image/webp" --cache-control "max-age=31536000"

REM Upload fonts
echo   -^> Font files...
aws s3 sync . s3://safexpressops-frontend/ --exclude "*" --include "*.woff" --content-type "font/woff" --cache-control "max-age=31536000"
aws s3 sync . s3://safexpressops-frontend/ --exclude "*" --include "*.woff2" --content-type "font/woff2" --cache-control "max-age=31536000"
aws s3 sync . s3://safexpressops-frontend/ --exclude "*" --include "*.ttf" --content-type "font/ttf" --cache-control "max-age=31536000"
aws s3 sync . s3://safexpressops-frontend/ --exclude "*" --include "*.otf" --content-type "font/otf" --cache-control "max-age=31536000"

cd ..

echo Upload successful!
echo.

REM Step 3: Invalidate CloudFront cache
echo [3/3] Invalidating CloudFront cache...
echo Distribution ID: EASISGRLJMW51

aws cloudfront create-invalidation --distribution-id EASISGRLJMW51 --paths "/*"

if errorlevel 1 (
    echo Cache invalidation failed!
    exit /b 1
)

echo Cache invalidation started!
echo This may take 5-15 minutes to complete.

echo.
echo ========================================
echo    Deployment Complete!
echo ========================================
echo.
echo Your app is deployed at:
echo https://d235efx2egjlji.cloudfront.net
echo.
echo Note: If you see old content, wait 5-15 minutes for cache invalidation.
echo.
