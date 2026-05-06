#!/bin/bash
# Build script for pdf_parse Lambda function
# Run this in Git Bash, WSL, or any bash terminal

set -e  # Exit on error

FUNCTION_NAME="pdf_parse"
IMAGE_NAME="lb-pdf-parse"
OUTPUT_ZIP="dist/${FUNCTION_NAME}.zip"

echo "============================================"
echo "Building $FUNCTION_NAME Lambda Function"
echo "============================================"

# Navigate to kb-lambda directory
cd "$(dirname "$0")"

echo ""
echo "[1/4] Building Docker image..."
docker build \
  --build-arg FUNCTION_NAME=$FUNCTION_NAME \
  -f Dockerfile.lambda \
  -t $IMAGE_NAME \
  --target builder \
  .

echo ""
echo "[2/4] Creating container..."
cid=$(docker create $IMAGE_NAME)
echo "Container ID: $cid"

echo ""
echo "[3/4] Extracting lambda package..."
docker cp "$cid:/build/lambda-function.zip" "$OUTPUT_ZIP"

echo ""
echo "[4/4] Cleaning up..."
docker rm $cid
docker rmi $IMAGE_NAME -f

echo ""
echo "============================================"
echo "BUILD COMPLETE"
echo "============================================"
if [ -f "$OUTPUT_ZIP" ]; then
    size=$(du -h "$OUTPUT_ZIP" | cut -f1)
    echo "Package: $OUTPUT_ZIP"
    echo "Size: $size"
    echo ""
    echo "✓ Ready for AWS Lambda deployment"
else
    echo "ERROR: Package not found at $OUTPUT_ZIP"
    exit 1
fi
