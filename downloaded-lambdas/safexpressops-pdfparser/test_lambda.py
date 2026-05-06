#!/usr/bin/env python3

import os
import sys
import base64
import json
import boto3
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add current directory to path for local testing
sys.path.insert(0, os.path.dirname(__file__))

def test_local():
    """Test the Lambda function locally"""
    try:
        # Import your lambda function
        from lambda_function import lambda_handler
        
        # Test with a minimal PDF (base64 encoded empty PDF)
        test_pdf_b64 = "JVBERi0xLjQKJeLjz9MKMSAwIG9iago8PAovVHlwZSAvQ2F0YWxvZwovUGFnZXMgMiAwIFIKPj4KZW5kb2JqCjIgMCBvYmoKPDwKL1R5cGUgL1BhZ2VzCi9LaWRzIFszIDAgUl0KL0NvdW50IDEKPD4KZW5kb2JqCjMgMCBvYmoKPDwKL1R5cGUgL1BhZ2UKL1BhcmVudCAyIDAgUgovTWVkaWFCb3ggWzAgMCA2MTIgNzkyXQovUmVzb3VyY2VzIDw8Ci9Gb250IDw8Ci9GMSA0IDAgUgo+Pgo+PgovQ29udGVudHMgNSAwIFIKPj4KZW5kb2JqCjQgMCBvYmoKPDwKL1R5cGUgL0ZvbnQKL1N1YnR5cGUgL1R5cGUxCi9CYXNlRm9udCAvSGVsdmV0aWNhCj4+CmVuZG9iago1IDAgb2JqCjw8Ci9MZW5ndGggNDQKPj4Kc3RyZWFtCkJUCi9GMSAxMiBUZgoyMCA3MjAgVGQKKEhlbGxvIFdvcmxkKSBUagpFVApIbmRzdHJlYW0KZW5kb2JqCnhyZWYKMCA2CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAwMDAwOSAwMDAwMCBuIAowMDAwMDAwMDU4IDAwMDAwIG4gCjAwMDAwMDAxMTUgMDAwMDAgbiAKMDAwMDAwMDI0NSAwMDAwMCBuIAowMDAwMDAwMzE0IDAwMDAwIG4gCnRyYWlsZXIKPDwKL1NpemUgNgovUm9vdCAxIDAgUgo+PgpzdGFydHhyZWYKNDA4CiUlRU9G"
        
        # Create test event
        event = {
            'pdf_base64': test_pdf_b64,
            'source_filename': 'test.pdf',
            'processing_mode': 'both',
            'use_ai_processing': True
        }
        
        # Mock context
        class MockContext:
            def __init__(self):
                self.function_name = 'safexpressops-pdfparser'
                self.memory_limit_in_mb = 1024
                self.invoked_function_arn = 'arn:aws:lambda:us-east-1:123456789:function:safexpressops-pdfparser'
                self.aws_request_id = 'test-request-123'
        
        context = MockContext()
        
        # Set OpenAI API key for local testing
        os.environ['OPENAI_API_KEY'] = os.getenv('OPENAI_API_KEY', '')
        
        print("🧪 Testing Lambda function locally...")
        print("=" * 50)
        
        # Call the handler
        response = lambda_handler(event, context)
        
        print(f"Status Code: {response['statusCode']}")
        
        if response['statusCode'] == 200:
            body = json.loads(response['body'])
            print("✅ Local test successful!")
            print(f"📄 Filename: {body.get('filename')}")
            print(f"📖 Total pages: {body.get('total_pages')}")
            print(f"🤖 AI Enhanced: {body.get('ai_enhanced')}")
            
            if 'simplified' in body:
                print(f"📋 Simplified blocks: {len(body.get('simplified', []))}")
            
            if 'structured' in body:
                print(f"🏗️ Structured blocks: {len(body.get('structured', []))}")
            
            if 'chunks' in body:
                print(f"🧩 Chunks: {len(body.get('chunks', []))}")
                
                # Show first chunk if available
                if body['chunks']:
                    first_chunk = body['chunks'][0]
                    print(f"📝 First chunk preview: {first_chunk['text'][:100]}...")
                    if first_chunk['metadata'].get('ai_enhanced'):
                        print(f"🎯 AI Keywords: {first_chunk['metadata'].get('keywords', [])}")
        else:
            error_body = json.loads(response['body'])
            print("❌ Local test failed!")
            print(f"Error: {error_body.get('error')}")
            
    except ImportError as e:
        print(f"❌ Cannot import lambda_function: {e}")
        print("Make sure lambda_function.py exists in the current directory")
    except Exception as e:
        print(f"❌ Local test error: {str(e)}")
        import traceback
        traceback.print_exc()

def test_with_file(pdf_path):
    """Test with a real PDF file"""
    try:
        if not os.path.exists(pdf_path):
            print(f"❌ PDF file not found: {pdf_path}")
            return
        
        print(f"📁 Testing with PDF file: {pdf_path}")
        
        # Read the PDF file
        with open(pdf_path, 'rb') as f:
            pdf_data = f.read()
        
        # Convert to base64
        pdf_base64 = base64.b64encode(pdf_data).decode('utf-8')
        
        # Test locally first
        from lambda_function import lambda_handler
        
        event = {
            'pdf_base64': pdf_base64,
            'source_filename': os.path.basename(pdf_path),
            'processing_mode': 'both',
            'use_ai_processing': True
        }
        
        class MockContext:
            function_name = 'safexpressops-pdfparser'
        
        os.environ['OPENAI_API_KEY'] = os.getenv('OPENAI_API_KEY', '')
        
        print("🧪 Testing with real PDF...")
        response = lambda_handler(event, MockContext())
        
        if response['statusCode'] == 200:
            body = json.loads(response['body'])
            print("✅ PDF processing successful!")
            print(f"📄 File: {body.get('filename')}")
            print(f"📖 Pages: {body.get('total_pages')}")
            
            if body.get('chunks'):
                print(f"🧩 Generated {len(body['chunks'])} chunks")
                
                # Show some chunk details
                for i, chunk in enumerate(body['chunks'][:3]):
                    print(f"\nChunk {i+1}:")
                    print(f"  Type: {chunk['metadata'].get('type', 'unknown')}")
                    print(f"  Page: {chunk['metadata'].get('page', 'unknown')}")
                    print(f"  Text: {chunk['text'][:150]}...")
                    if chunk['metadata'].get('ai_enhanced'):
                        print(f"  AI Type: {chunk['metadata'].get('ai_content_type', 'N/A')}")
                        print(f"  Keywords: {chunk['metadata'].get('keywords', [])}")
        else:
            print("❌ PDF processing failed!")
            print(json.loads(response['body']))
            
    except Exception as e:
        print(f"❌ File test error: {str(e)}")

def test_deployed(function_name='safexpressops-pdfparser', region='us-east-1'):
    """Test the deployed Lambda function"""
    try:
        # Create Lambda client
        lambda_client = boto3.client('lambda', region_name=region)
        
        # Simple test payload
        test_pdf_b64 = "JVBERi0xLjQKJeLjz9MKMSAwIG9iago8PAovVHlwZSAvQ2F0YWxvZwovUGFnZXMgMiAwIFIKPj4KZW5kb2JqCjIgMCBvYmoKPDwKL1R5cGUgL1BhZ2VzCi9LaWRzIFszIDAgUl0KL0NvdW50IDEKPD4KZW5kb2JqCjMgMCBvYmoKPDwKL1R5cGUgL1BhZ2UKL1BhcmVudCAyIDAgUgovTWVkaWFCb3ggWzAgMCA2MTIgNzkyXQovUmVzb3VyY2VzIDw8Ci9Gb250IDw8Ci9GMSA0IDAgUgo+Pgo+PgovQ29udGVudHMgNSAwIFIKPj4KZW5kb2JqCjQgMCBvYmoKPDwKL1R5cGUgL0ZvbnQKL1N1YnR5cGUgL1R5cGUxCi9CYXNlRm9udCAvSGVsdmV0aWNhCj4+CmVuZG9iago1IDAgb2JqCjw8Ci9MZW5ndGggNDQKPj4Kc3RyZWFtCkJUCi9GMSAxMiBUZgoyMCA3MjAgVGQKKEhlbGxvIFdvcmxkKSBUagpFVApIbmRzdHJlYW0KZW5kb2JqCnhyZWYKMCA2CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAwMDAwOSAwMDAwMCBuIAowMDAwMDAwMDU4IDAwMDAwIG4gCjAwMDAwMDAxMTUgMDAwMDAgbiAKMDAwMDAwMDI0NSAwMDAwMCBuIAowMDAwMDAwMzE0IDAwMDAwIG4gCnRyYWlsZXIKPDwKL1NpemUgNgovUm9vdCAxIDAgUgo+PgpzdGFydHhyZWYKNDA4CiUlRU9G"
        
        payload = {
            'pdf_base64': test_pdf_b64,
            'source_filename': 'test.pdf',
            'processing_mode': 'parse',  # Start with basic parsing
            'use_ai_processing': False   # Disable AI for initial test
        }
        
        print("☁️ Testing deployed Lambda function...")
        print(f"Function: {function_name}")
        print(f"Region: {region}")
        print("=" * 50)
        
        # Invoke the function
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType='RequestResponse',
            Payload=json.dumps(payload)
        )
        
        # Read response
        response_payload = response['Payload'].read()
        result = json.loads(response_payload)
        
        print(f"Lambda Status: {response['StatusCode']}")
        
        if 'errorMessage' in result:
            print("❌ Lambda function error!")
            print(f"Error: {result['errorMessage']}")
            if 'errorType' in result:
                print(f"Type: {result['errorType']}")
        else:
            print("✅ Deployed function test successful!")
            print(f"Response: {result[:200]}..." if len(str(result)) > 200 else result)
        
        return result
        
    except Exception as e:
        print(f"❌ Deployment test error: {str(e)}")
        return None

def main():
    print("SafeExpressOps PDF Parser Lambda Test Suite")
    print("=" * 60)
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == 'local':
            test_local()
        elif command == 'file' and len(sys.argv) > 2:
            test_with_file(sys.argv[2])
        elif command == 'deployed':
            function_name = sys.argv[2] if len(sys.argv) > 2 else 'safexpressops-pdfparser'
            region = sys.argv[3] if len(sys.argv) > 3 else 'us-east-1'
            test_deployed(function_name, region)
        else:
            print("Usage:")
            print("  python test_lambda.py local")
            print("  python test_lambda.py file <path_to_pdf>")
            print("  python test_lambda.py deployed [function_name] [region]")
    else:
        print("Running all tests...")
        print("\n1. Testing locally:")
        test_local()
        
        print("\n2. Testing deployed function:")
        test_deployed()

if __name__ == "__main__":
    main()