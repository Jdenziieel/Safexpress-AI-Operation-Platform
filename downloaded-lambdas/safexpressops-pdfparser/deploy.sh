#!/bin/bash

# Simplified SafeExpressOps PDF Parser Lambda Deployment

set -e

# Configuration
FUNCTION_NAME="safexpressops-pdfparser"
REGION="us-east-1"
RUNTIME="python3.9"
MEMORY_SIZE=1024
TIMEOUT=300

echo "SafeExpressOps PDF Parser Lambda Deployment"
echo "==========================================="

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    echo "Error: AWS CLI not found. Please install AWS CLI first."
    exit 1
fi

# Check if OpenAI API key is provided
if [ -z "$OPENAI_API_KEY" ]; then
    echo "Warning: OPENAI_API_KEY environment variable not set."
    echo "You'll need to set this in Lambda environment variables after deployment."
fi

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf deployment/
rm -f safexpressops-pdfparser.zip

# Create deployment directory
mkdir deployment
cd deployment

echo "Installing Python dependencies..."

# Simple approach - let pip handle platform detection
pip install --target . --upgrade \
    PyMuPDF==1.23.8 \
    pdfplumber==0.10.3 \
    openai==1.3.7 \
    Pillow==10.0.1

# Copy source code
echo "Copying source code..."
cp ../lambda_function.py .

# Clean up to reduce package size
echo "Optimizing package size..."
find . -type d -name "__pycache__" -exec rm -r {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true
find . -name "*.pyo" -delete 2>/dev/null || true
find . -name "tests" -type d -exec rm -r {} + 2>/dev/null || true
find . -name "*.dist-info" -type d -exec rm -r {} + 2>/dev/null || true
find . -name "*.egg-info" -type d -exec rm -r {} + 2>/dev/null || true

# Remove test files and documentation
rm -rf */tests/ 2>/dev/null || true
rm -rf */test/ 2>/dev/null || true
rm -rf */docs/ 2>/dev/null || true

echo "Package contents:"
ls -la

echo "Package size:"
du -sh .

# Create deployment package
echo "Creating deployment package..."
zip -r ../safexpressops-pdfparser.zip . -q

cd ..

# Check package size
ZIP_SIZE=$(du -m safexpressops-pdfparser.zip | cut -f1)
echo "Deployment package size: ${ZIP_SIZE}MB"

if [ $ZIP_SIZE -gt 50 ]; then
    echo "Warning: Package size (${ZIP_SIZE}MB) exceeds 50MB Lambda limit!"
    echo "Consider using Lambda layers for large dependencies."
    echo "Proceeding anyway - AWS may reject the deployment."
fi

# Deploy to AWS
echo "Deploying to AWS Lambda..."

# Check if function exists
aws lambda get-function --function-name $FUNCTION_NAME --region $REGION >/dev/null 2>&1
FUNCTION_EXISTS=$?

if [ $FUNCTION_EXISTS -eq 0 ]; then
    echo "Function exists, updating code..."
    aws lambda update-function-code \
        --function-name $FUNCTION_NAME \
        --zip-file fileb://safexpressops-pdfparser.zip \
        --region $REGION

    echo "Updating function configuration..."
    aws lambda update-function-configuration \
        --function-name $FUNCTION_NAME \
        --timeout $TIMEOUT \
        --memory-size $MEMORY_SIZE \
        --region $REGION
        
    # Update environment variables if OPENAI_API_KEY is set
    if [ ! -z "$OPENAI_API_KEY" ]; then
        echo "Setting OpenAI API key..."
        aws lambda update-function-configuration \
            --function-name $FUNCTION_NAME \
            --environment Variables="{\"OPENAI_API_KEY\":\"$OPENAI_API_KEY\"}" \
            --region $REGION
    fi
else
    echo "Creating new function..."
    
    # Create IAM role
    ROLE_NAME="lambda-safexpress-pdf-role"
    
    echo "Creating IAM role..."
    aws iam create-role \
        --role-name $ROLE_NAME \
        --assume-role-policy-document '{
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }' 2>/dev/null || echo "Role already exists"
    
    aws iam attach-role-policy \
        --role-name $ROLE_NAME \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    
    # Get role ARN
    ROLE_ARN=$(aws iam get-role --role-name $ROLE_NAME --query 'Role.Arn' --output text)
    
    # Wait for role propagation
    echo "Waiting for IAM role to propagate..."
    sleep 15
    
    # Set environment variables
    ENV_VARS="{}"
    if [ ! -z "$OPENAI_API_KEY" ]; then
        ENV_VARS="{\"OPENAI_API_KEY\":\"$OPENAI_API_KEY\"}"
    fi
    
    aws lambda create-function \
        --function-name $FUNCTION_NAME \
        --runtime $RUNTIME \
        --role $ROLE_ARN \
        --handler lambda_function.lambda_handler \
        --zip-file fileb://safexpressops-pdfparser.zip \
        --timeout $TIMEOUT \
        --memory-size $MEMORY_SIZE \
        --environment Variables="$ENV_VARS" \
        --region $REGION
fi

# Get function details
FUNCTION_ARN=$(aws lambda get-function --function-name $FUNCTION_NAME --region $REGION --query 'Configuration.FunctionArn' --output text)

echo ""
echo "Deployment completed!"
echo "===================="
echo "Function Name: $FUNCTION_NAME"
echo "Function ARN: $FUNCTION_ARN"
echo "Region: $REGION"
echo "Memory: ${MEMORY_SIZE}MB"
echo "Timeout: ${TIMEOUT}s"

echo ""
echo "Testing deployment..."
python ../test_lambda.py deployed $FUNCTION_NAME $REGION

echo ""
echo "Next steps:"
echo "1. Test with real PDFs: python pdf_upload_utility.py your-file.pdf"
echo "2. Integrate with Django backend"
echo "3. Set up API Gateway if needed"