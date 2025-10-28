# Deployment Scripts

This folder contains automated deployment scripts for deploying the SafeXpress OPS application to AWS S3 and CloudFront.

## 🚀 Quick Start

### Windows PowerShell (Recommended for Windows)
```powershell
.\deploy.ps1
```

### Git Bash / Linux / macOS
```bash
chmod +x deploy.sh
./deploy.sh
```

## 📋 What the Script Does

1. **Builds the application** - Runs `npm run build` to create production bundle
2. **Uploads to S3** - Syncs all files to S3 bucket with correct Content-Type headers
3. **Invalidates CloudFront cache** - Clears CloudFront cache so changes appear immediately

## ⚙️ Script Options

### PowerShell (deploy.ps1)

```powershell
# Full deployment (build + upload + invalidate)
.\deploy.ps1

# Skip build (only upload and invalidate)
.\deploy.ps1 -SkipBuild

# Skip cache invalidation
.\deploy.ps1 -SkipInvalidation

# Custom bucket and distribution
.\deploy.ps1 -BucketName "my-bucket" -DistributionId "E1234567890ABC"

# Combine options
.\deploy.ps1 -SkipBuild -BucketName "my-bucket"
```

### Bash (deploy.sh)

```bash
# Full deployment (build + upload + invalidate)
./deploy.sh

# Skip build (only upload and invalidate)
./deploy.sh --skip-build

# Skip cache invalidation
./deploy.sh --skip-invalidation

# Custom bucket and distribution
./deploy.sh --bucket "my-bucket" --distribution-id "E1234567890ABC"

# Combine options
./deploy.sh --skip-build --skip-invalidation
```

## 🔧 Prerequisites

### Required Tools

1. **Node.js and npm** - For building the application
   ```bash
   node --version  # Should be v16 or higher
   npm --version
   ```

2. **AWS CLI** - For uploading to S3 and invalidating CloudFront
   ```bash
   aws --version
   ```

3. **AWS Credentials** - Must be configured with access to:
   - S3 bucket: `safexpressops-frontend`
   - CloudFront distribution: `EASISGRLJMW51`

### AWS CLI Setup

If you haven't set up AWS CLI yet:

```bash
# Install AWS CLI (if not installed)
# Windows: Download from https://aws.amazon.com/cli/
# macOS: brew install awscli
# Linux: sudo apt-get install awscli

# Configure credentials
aws configure
# Enter:
#   - AWS Access Key ID
#   - AWS Secret Access Key
#   - Default region (us-east-1)
#   - Default output format (json)
```

## 📊 Content-Type Headers

The script automatically sets correct Content-Type headers for all file types:

| File Type | Content-Type | Cache Control |
|-----------|-------------|---------------|
| `.html` | text/html | no-cache |
| `.js` | application/javascript | max-age=31536000 (1 year) |
| `.css` | text/css | max-age=31536000 (1 year) |
| `.json` | application/json | no-cache |
| `.png`, `.jpg`, `.jpeg` | image/png, image/jpeg | max-age=31536000 |
| `.svg` | image/svg+xml | max-age=31536000 |
| `.woff`, `.woff2` | font/woff, font/woff2 | max-age=31536000 |

## 🌐 Deployment URLs

- **Frontend CloudFront**: https://d235efx2egjlji.cloudfront.net
- **Backend CloudFront**: https://d1r565u2m90baj.cloudfront.net
- **S3 Bucket**: s3://safexpressops-frontend

## ⏱️ Deployment Timeline

- **Build**: 30-60 seconds
- **Upload**: 10-30 seconds (depending on file changes)
- **CloudFront Invalidation**: 5-15 minutes

> **Note**: After deployment completes, you may see old content for a few minutes while CloudFront cache invalidates. Clear your browser cache if needed.

## 🐛 Troubleshooting

### "dist folder not found"
```bash
# Build the application first
npm run build
```

### "AWS credentials not configured"
```bash
# Configure AWS CLI
aws configure
```

### "Access Denied" error
- Verify your AWS credentials have permissions for:
  - `s3:PutObject` on bucket `safexpressops-frontend`
  - `cloudfront:CreateInvalidation` on distribution `EASISGRLJMW51`

### "Command not found: aws"
- Install AWS CLI: https://aws.amazon.com/cli/

### Changes not appearing after deployment
- Wait 5-15 minutes for CloudFront cache invalidation
- Clear your browser cache (Ctrl+Shift+Delete)
- Try hard refresh (Ctrl+F5)

## 📝 Manual Deployment (if script fails)

If the automated script doesn't work, you can deploy manually:

```bash
# 1. Build
npm run build

# 2. Upload to S3
cd dist
aws s3 sync . s3://safexpressops-frontend/ --exclude "*" --include "*.html" --content-type "text/html" --cache-control "no-cache"
aws s3 sync . s3://safexpressops-frontend/ --exclude "*" --include "*.js" --content-type "application/javascript" --cache-control "max-age=31536000"
aws s3 sync . s3://safexpressops-frontend/ --exclude "*" --include "*.css" --content-type "text/css" --cache-control "max-age=31536000"
cd ..

# 3. Invalidate cache
aws cloudfront create-invalidation --distribution-id EASISGRLJMW51 --paths "/*"
```

## 🔒 Security Notes

- Never commit AWS credentials to git
- Use IAM roles with minimum required permissions
- Keep AWS CLI and Node.js updated
- Review CloudFront access logs regularly

## 📚 Additional Resources

- [AWS CLI Documentation](https://docs.aws.amazon.com/cli/)
- [CloudFront Invalidation Guide](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/Invalidation.html)
- [S3 Static Website Hosting](https://docs.aws.amazon.com/AmazonS3/latest/userguide/WebsiteHosting.html)
