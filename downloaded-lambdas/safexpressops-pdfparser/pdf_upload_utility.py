#!/usr/bin/env python3

import os
import base64
import json
import boto3
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def create_test_event_from_pdf(pdf_path, processing_mode='both', use_ai=True):
    """Create a test event from a PDF file"""
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    
    with open(pdf_path, 'rb') as f:
        pdf_data = f.read()
    
    pdf_base64 = base64.b64encode(pdf_data).decode('utf-8')
    
    return {
        'pdf_base64': pdf_base64,
        'source_filename': os.path.basename(pdf_path),
        'processing_mode': processing_mode,
        'use_ai_processing': use_ai
    }

def test_with_pdf_file(pdf_path, function_name='safexpressops-pdfparser', region='us-east-1'):
    """Test Lambda function with a real PDF file"""
    try:
        print(f"Testing with PDF: {pdf_path}")
        print(f"Function: {function_name}")
        print(f"Region: {region}")
        
        # Create test event
        event = create_test_event_from_pdf(pdf_path)
        
        # Initialize Lambda client
        lambda_client = boto3.client('lambda', region_name=region)
        
        # Invoke function
        print("Invoking Lambda function...")
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType='RequestResponse',
            Payload=json.dumps(event)
        )
        
        # Parse response
        response_payload = response['Payload'].read()
        result = json.loads(response_payload)
        
        print(f"HTTP Status: {response['StatusCode']}")
        
        if 'errorMessage' in result:
            print(f"Error: {result['errorMessage']}")
            if 'errorType' in result:
                print(f"Error Type: {result['errorType']}")
        else:
            print("Success!")
            print(f"Filename: {result.get('filename')}")
            print(f"Pages: {result.get('total_pages')}")
            print(f"AI Enhanced: {result.get('ai_enhanced')}")
            
            # Show processing results
            if 'simplified' in result:
                print(f"Simplified blocks: {len(result['simplified'])}")
            
            if 'structured' in result:
                print(f"Structured blocks: {len(result['structured'])}")
            
            if 'chunks' in result:
                print(f"Chunks generated: {len(result['chunks'])}")
                
                # Show first few chunks
                for i, chunk in enumerate(result['chunks'][:3]):
                    print(f"\nChunk {i+1}:")
                    print(f"  Type: {chunk['metadata'].get('type')}")
                    print(f"  Page: {chunk['metadata'].get('page')}")
                    print(f"  Text preview: {chunk['text'][:100]}...")
                    
                    if chunk['metadata'].get('ai_enhanced'):
                        print(f"  AI Type: {chunk['metadata'].get('ai_content_type')}")
                        print(f"  Keywords: {chunk['metadata'].get('keywords', [])}")
        
        return result
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return None

def batch_test_pdfs(pdf_directory, function_name='safexpressops-pdfparser', region='us-east-1'):
    """Test multiple PDF files"""
    if not os.path.exists(pdf_directory):
        print(f"Directory not found: {pdf_directory}")
        return
    
    pdf_files = [f for f in os.listdir(pdf_directory) if f.lower().endswith('.pdf')]
    
    if not pdf_files:
        print(f"No PDF files found in {pdf_directory}")
        return
    
    print(f"Found {len(pdf_files)} PDF files to test")
    
    results = []
    for pdf_file in pdf_files:
        pdf_path = os.path.join(pdf_directory, pdf_file)
        print(f"\n{'='*50}")
        print(f"Testing: {pdf_file}")
        
        result = test_with_pdf_file(pdf_path, function_name, region)
        results.append({
            'file': pdf_file,
            'success': result is not None and 'errorMessage' not in result,
            'result': result
        })
    
    # Summary
    print(f"\n{'='*50}")
    print("BATCH TEST SUMMARY")
    print(f"{'='*50}")
    
    successful = sum(1 for r in results if r['success'])
    failed = len(results) - successful
    
    print(f"Total files: {len(results)}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    
    if failed > 0:
        print("\nFailed files:")
        for r in results:
            if not r['success']:
                error = r['result'].get('errorMessage', 'Unknown error') if r['result'] else 'No response'
                print(f"  - {r['file']}: {error}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python pdf_upload_utility.py <pdf_file>")
        print("  python pdf_upload_utility.py batch <pdf_directory>")
        sys.exit(1)
    
    if sys.argv[1] == 'batch':
        if len(sys.argv) < 3:
            print("Please provide directory path for batch testing")
            sys.exit(1)
        batch_test_pdfs(sys.argv[2])
    else:
        pdf_path = sys.argv[1]
        function_name = sys.argv[2] if len(sys.argv) > 2 else 'safexpressops-pdfparser'
        region = sys.argv[3] if len(sys.argv) > 3 else 'us-east-1'
        
        test_with_pdf_file(pdf_path, function_name, region)