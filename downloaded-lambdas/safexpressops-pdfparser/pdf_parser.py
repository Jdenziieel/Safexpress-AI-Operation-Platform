"""
PDF Parser Lambda Integration for SafeExpressOps
Handles communication between Django backend and Lambda PDF processing function
"""

import boto3
import base64
import json
import logging
from django.conf import settings
from typing import Dict, Any, Optional
import time

logger = logging.getLogger(__name__)

class PDFParserLambda:
    """
    Handles PDF parsing through AWS Lambda function
    """
    
    def __init__(self, function_name='safexpressops-pdfparser', region='us-east-1'):
        self.function_name = function_name
        self.region = region
        self.lambda_client = boto3.client('lambda', region_name=region)
    
    def parse_pdf(self, file_data: bytes, filename: str, 
                  processing_mode: str = 'both', 
                  use_ai: bool = True) -> Dict[str, Any]:
        """
        Parse PDF using Lambda function
        
        Args:
            file_data: PDF file as bytes
            filename: Original filename
            processing_mode: 'parse', 'chunk', or 'both'
            use_ai: Whether to use OpenAI enhancement
            
        Returns:
            Dict containing parsed results or error information
        """
        try:
            # Encode PDF data
            pdf_base64 = base64.b64encode(file_data).decode('utf-8')
            
            # Prepare payload
            payload = {
                'pdf_base64': pdf_base64,
                'source_filename': filename,
                'processing_mode': processing_mode,
                'use_ai_processing': use_ai
            }
            
            logger.info(f"Invoking Lambda function {self.function_name} for file: {filename}")
            start_time = time.time()
            
            # Invoke Lambda function
            response = self.lambda_client.invoke(
                FunctionName=self.function_name,
                InvocationType='RequestResponse',
                Payload=json.dumps(payload)
            )
            
            processing_time = time.time() - start_time
            logger.info(f"Lambda processing completed in {processing_time:.2f} seconds")
            
            # Parse response
            response_payload = response['Payload'].read()
            result = json.loads(response_payload)
            
            # Check if Lambda execution was successful
            if response['StatusCode'] != 200:
                logger.error(f"Lambda invocation failed with status: {response['StatusCode']}")
                return {'error': f'Lambda execution failed: Status {response["StatusCode"]}'}
            
            # Check for Lambda function errors
            if 'errorMessage' in result:
                logger.error(f"Lambda function error: {result['errorMessage']}")
                return {
                    'error': result['errorMessage'],
                    'error_type': result.get('errorType', 'Unknown'),
                    'traceback': result.get('stackTrace', [])
                }
            
            # Add processing metadata
            result['processing_time'] = processing_time
            result['processed_by'] = 'lambda'
            
            logger.info(f"Successfully parsed PDF: {filename}")
            return result
            
        except Exception as e:
            logger.error(f"Error calling Lambda function: {str(e)}")
            return {'error': f'Lambda invocation error: {str(e)}'}
    
    def parse_and_chunk(self, file_data: bytes, filename: str) -> Dict[str, Any]:
        """
        Convenience method for full parsing and chunking with AI
        """
        return self.parse_pdf(file_data, filename, 'both', True)
    
    def parse_only(self, file_data: bytes, filename: str) -> Dict[str, Any]:
        """
        Convenience method for basic parsing only
        """
        return self.parse_pdf(file_data, filename, 'parse', False)
    
    def chunk_only(self, file_data: bytes, filename: str, use_ai: bool = True) -> Dict[str, Any]:
        """
        Convenience method for chunking only
        """
        return self.parse_pdf(file_data, filename, 'chunk', use_ai)
    
    def health_check(self) -> bool:
        """
        Check if Lambda function is accessible
        """
        try:
            # Simple test with minimal payload
            test_payload = {
                'pdf_base64': '',
                'source_filename': 'health_check.pdf',
                'processing_mode': 'parse',
                'use_ai_processing': False
            }
            
            response = self.lambda_client.invoke(
                FunctionName=self.function_name,
                InvocationType='RequestResponse',
                Payload=json.dumps(test_payload)
            )
            
            return response['StatusCode'] == 200
            
        except Exception as e:
            logger.error(f"Lambda health check failed: {str(e)}")
            return False

# Singleton instance for the application
pdf_parser = PDFParserLambda()

def parse_pdf_document(file_data: bytes, filename: str, 
                      processing_mode: str = 'both', 
                      use_ai: bool = True) -> Dict[str, Any]:
    """
    Main function to parse PDF documents
    This is the function your Django views should call
    """
    return pdf_parser.parse_pdf(file_data, filename, processing_mode, use_ai)

def extract_delivery_order(file_data: bytes, filename: str) -> Dict[str, Any]:
    """
    Specific function for delivery order processing
    Optimized for SafeExpressOps delivery order automation
    """
    try:
        # First, do basic parsing
        result = pdf_parser.parse_pdf(file_data, filename, 'both', True)
        
        if 'error' in result:
            return result
        
        # Extract delivery-specific information
        delivery_info = extract_delivery_specific_data(result)
        result['delivery_order'] = delivery_info
        
        return result
        
    except Exception as e:
        logger.error(f"Error processing delivery order: {str(e)}")
        return {'error': f'Delivery order processing failed: {str(e)}'}

def extract_delivery_specific_data(parsed_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract delivery order specific information from parsed PDF
    """
    delivery_info = {
        'issuance_id': None,
        'client_name': None,
        'delivery_date': None,
        'items': [],
        'total_quantity': 0,
        'special_instructions': None
    }
    
    try:
        # Look through chunks for delivery-specific patterns
        chunks = parsed_result.get('chunks', [])
        
        for chunk in chunks:
            text = chunk.get('text', '').lower()
            
            # Look for client information
            if 'client' in text or 'company' in text:
                # Extract client name logic here
                pass
            
            # Look for delivery date
            if 'delivery' in text and 'date' in text:
                # Extract date logic here
                pass
            
            # Look for item lists
            if chunk['metadata'].get('type') == 'table' or 'quantity' in text:
                # Extract items logic here
                pass
        
        return delivery_info
        
    except Exception as e:
        logger.error(f"Error extracting delivery data: {str(e)}")
        return delivery_info

# Fallback function for when Lambda is unavailable
def fallback_local_parser(file_data: bytes, filename: str) -> Dict[str, Any]:
    """
    Basic fallback parser if Lambda is unavailable
    Uses local libraries for minimal processing
    """
    try:
        import fitz  # PyMuPDF
        import tempfile
        import os
        
        # Save to temporary file
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            tmp_file.write(file_data)
            tmp_file_path = tmp_file.name
        
        try:
            doc = fitz.open(tmp_file_path)
            
            simplified_data = []
            
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                text = page.get_text()
                
                if text.strip():
                    simplified_data.append({
                        'page': page_num + 1,
                        'type': 'text',
                        'text': text.strip()
                    })
            
            doc.close()
            
            return {
                'simplified': simplified_data,
                'structured': [],
                'chunks': [],
                'filename': filename,
                'total_pages': len(doc),
                'ai_enhanced': False,
                'processing_mode': 'fallback',
                'processed_by': 'fallback'
            }
            
        finally:
            if os.path.exists(tmp_file_path):
                os.unlink(tmp_file_path)
                
    except Exception as e:
        logger.error(f"Fallback parser error: {str(e)}")
        return {'error': f'All parsing methods failed: {str(e)}'}

# Smart parsing function that tries Lambda first, then falls back
def smart_parse_pdf(file_data: bytes, filename: str, 
                   processing_mode: str = 'both', 
                   use_ai: bool = True) -> Dict[str, Any]:
    """
    Intelligent PDF parsing that tries Lambda first, falls back to local if needed
    """
    # Try Lambda first
    result = pdf_parser.parse_pdf(file_data, filename, processing_mode, use_ai)
    
    # If Lambda failed, try fallback
    if 'error' in result:
        logger.warning(f"Lambda parsing failed, trying fallback for {filename}")
        fallback_result = fallback_local_parser(file_data, filename)
        
        # Indicate this was a fallback
        fallback_result['lambda_error'] = result['error']
        fallback_result['used_fallback'] = True
        
        return fallback_result
    
    return result