import json
import base64
import tempfile
import os
import fitz  # PyMuPDF
import pdfplumber
import uuid
import traceback
from openai import OpenAI

def lambda_handler(event, context):
    """
    AWS Lambda handler for SafexpressOps PDF parsing with OpenAI integration
    """
    print("=== Lambda function started ===")
    print(f"Request ID: {context.request_id if hasattr(context, 'request_id') else 'unknown'}")
    
    try:
        # Initialize OpenAI client
        print("Checking for OpenAI API key...")
        openai_api_key = os.environ.get('OPENAI_API_KEY')
        if not openai_api_key:
            print("ERROR: OPENAI_API_KEY not configured")
            return create_response(500, {'error': 'OpenAI API key not configured'})
        
        print(f"OpenAI API key found (starts with: {openai_api_key[:10]}...)")
        client = OpenAI(api_key=openai_api_key)
        
        # Handle different event sources
        print(f"Processing event type: {'API Gateway' if 'body' in event else 'Direct invocation'}")
        
        if 'body' in event:
            # API Gateway event
            if event.get('isBase64Encoded', False):
                body = base64.b64decode(event['body'])
                body = json.loads(body)
            else:
                body = event['body']
                if isinstance(body, str):
                    body = json.loads(body)
        else:
            # Direct invocation
            body = event
        
        print(f"Body keys: {list(body.keys())}")
        
        # Extract PDF data
        if 'file_data' in body:
            print("Using 'file_data' field")
            pdf_data = base64.b64decode(body['file_data'])
        elif 'pdf_base64' in body:
            print("Using 'pdf_base64' field")
            pdf_data = base64.b64decode(body['pdf_base64'])
        else:
            print("ERROR: No PDF data field found")
            return create_response(400, {'error': 'No PDF data provided'})
        
        # Get parameters
        source_filename = body.get('source_filename', 'document.pdf')
        use_ai_processing = body.get('use_ai_processing', True)
        processing_mode = body.get('processing_mode', 'both')
        
        print(f"Processing: {source_filename}")
        print(f"PDF size: {len(pdf_data)} bytes")
        print(f"Mode: {processing_mode}, AI: {use_ai_processing}")
        
        # Process the PDF
        print("Starting PDF processing...")
        result = parse_pdf(pdf_data, source_filename, client if use_ai_processing else None, processing_mode)
        
        print(f"Processing complete! Pages: {result.get('total_pages', 'unknown')}")
        print(f"Result keys: {list(result.keys())}")
        
        return create_response(200, result)
        
    except Exception as e:
        print(f"=== Lambda Error ===")
        print(f"Error type: {type(e).__name__}")
        print(f"Lambda Error: {str(e)}")
        print(traceback.format_exc())
        
        return create_response(500, {
            'error': str(e),
            'traceback': traceback.format_exc()
        })
def create_response(status_code, body):
    """Helper to create consistent API responses"""
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type'
        },
        'body': json.dumps(body, default=str)
    }

def parse_pdf(pdf_data, filename, openai_client=None, mode='both'):
    """
    Parse PDF and return structured data with optional OpenAI enhancement
    """
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
        tmp_file.write(pdf_data)
        tmp_file_path = tmp_file.name
    
    try:
        result = {}
        
        if mode in ['parse', 'both']:
            # Basic parsing with PyMuPDF
            simplified_data, structured_data = parse_with_pymupdf(tmp_file_path)
            result.update({
                'simplified': simplified_data,
                'structured': structured_data
            })
        
        if mode in ['chunk', 'both']:
            # Advanced chunking processing
            chunks = process_chunks(tmp_file_path, openai_client)
            result['chunks'] = chunks
        
        # Add metadata
        doc = fitz.open(tmp_file_path)
        result.update({
            'filename': filename,
            'total_pages': len(doc),
            'ai_enhanced': openai_client is not None,
            'processing_mode': mode
        })
        doc.close()
        
        return result
        
    finally:
        if os.path.exists(tmp_file_path):
            os.unlink(tmp_file_path)

def parse_with_pymupdf(pdf_path):
    """
    Basic PDF parsing using PyMuPDF (similar to your original parser)
    """
    doc = fitz.open(pdf_path)
    simplified_data = []
    structured_data = []
    
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        blocks = page.get_text("dict")
        
        # Process simplified view
        page_simplified = process_page_simplified(blocks, page_num + 1)
        simplified_data.extend(page_simplified)
        
        # Process structured view
        page_structured = process_page_structured(blocks, page_num + 1)
        structured_data.extend(page_structured)
    
    doc.close()
    return simplified_data, structured_data

def process_page_simplified(blocks, page_num):
    """Extract simplified text content"""
    simplified = []
    
    for block in blocks.get("blocks", []):
        if "lines" in block:
            block_text = ""
            for line in block["lines"]:
                line_text = ""
                for span in line["spans"]:
                    line_text += span["text"]
                block_text += line_text + "\n"
            
            if block_text.strip():
                simplified.append({
                    "page": page_num,
                    "type": "text",
                    "text": block_text.strip()
                })
    
    return simplified

def process_page_structured(blocks, page_num):
    """Extract structured content with bounding boxes"""
    structured = []
    
    for block in blocks.get("blocks", []):
        if "lines" in block:
            block_text = ""
            bbox = block.get("bbox", [0, 0, 0, 0])
            fonts = []
            font_sizes = []
            
            for line in block["lines"]:
                line_text = ""
                for span in line["spans"]:
                    line_text += span["text"]
                    fonts.append(span.get("font", ""))
                    font_sizes.append(span.get("size", 0))
                block_text += line_text + "\n"
            
            if block_text.strip():
                avg_font_size = sum(font_sizes) / len(font_sizes) if font_sizes else 12
                content_type = classify_content_type(block_text.strip(), avg_font_size, fonts)
                
                structured.append({
                    "id": str(uuid.uuid4()),
                    "page": page_num,
                    "type": content_type,
                    "text": block_text.strip(),
                    "metadata": {
                        "page": page_num,
                        "box": {
                            "l": bbox[0], "t": bbox[1],
                            "r": bbox[2], "b": bbox[3]
                        },
                        "avg_font_size": avg_font_size,
                        "fonts": list(set(fonts))
                    }
                })
    
    return structured

def process_chunks(pdf_path, openai_client=None):
    """
    Advanced chunking similar to your /test-anchoring endpoint
    """
    chunks = []
    
    # Use pdfplumber for more detailed text extraction
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            # Extract text with positions
            chars = page.chars
            
            if not chars:
                continue
            
            # Group characters into lines and blocks
            lines = group_chars_into_lines(chars)
            blocks = group_lines_into_blocks(lines)
            
            for block in blocks:
                if not block['text'].strip():
                    continue
                
                chunk = {
                    "id": str(uuid.uuid4()),
                    "text": block['text'].strip(),
                    "metadata": {
                        "page": page_num + 1,
                        "type": classify_chunk_type(block['text'], block.get('font_size', 12)),
                        "boxes": block.get('boxes', []),
                        "source_filename": os.path.basename(pdf_path)
                    }
                }
                chunks.append(chunk)
    
    # Enhance with OpenAI if available
    if openai_client and chunks:
        chunks = enhance_chunks_with_openai(chunks, openai_client)
    
    return chunks

def group_chars_into_lines(chars):
    """Group characters into lines based on y-coordinate"""
    if not chars:
        return []
    
    # Sort by y-coordinate (top to bottom) then x-coordinate (left to right)
    sorted_chars = sorted(chars, key=lambda c: (round(c['top'], 1), c['x0']))
    
    lines = []
    current_line = []
    current_y = None
    tolerance = 3  # pixels
    
    for char in sorted_chars:
        y = round(char['top'], 1)
        
        if current_y is None or abs(y - current_y) <= tolerance:
            current_line.append(char)
            current_y = y
        else:
            if current_line:
                lines.append(current_line)
            current_line = [char]
            current_y = y
    
    if current_line:
        lines.append(current_line)
    
    return lines

def group_lines_into_blocks(lines):
    """Group lines into blocks based on spacing"""
    if not lines:
        return []
    
    blocks = []
    current_block = []
    prev_bottom = None
    line_height_threshold = 20  # pixels
    
    for line in lines:
        if not line:
            continue
        
        line_top = min(char['top'] for char in line)
        line_bottom = max(char['bottom'] for char in line)
        line_text = ''.join(char['text'] for char in line)
        
        if prev_bottom is None or (line_top - prev_bottom) <= line_height_threshold:
            current_block.append({
                'text': line_text,
                'top': line_top,
                'bottom': line_bottom,
                'chars': line
            })
        else:
            if current_block:
                blocks.append(finalize_block(current_block))
            current_block = [{
                'text': line_text,
                'top': line_top,
                'bottom': line_bottom,
                'chars': line
            }]
        
        prev_bottom = line_bottom
    
    if current_block:
        blocks.append(finalize_block(current_block))
    
    return blocks

def finalize_block(block_lines):
    """Convert grouped lines into a final block"""
    if not block_lines:
        return {}
    
    text = '\n'.join(line['text'] for line in block_lines)
    
    # Calculate bounding box
    all_chars = []
    for line in block_lines:
        all_chars.extend(line['chars'])
    
    if all_chars:
        bbox = {
            'l': min(char['x0'] for char in all_chars),
            't': min(char['top'] for char in all_chars),
            'r': max(char['x1'] for char in all_chars),
            'b': max(char['bottom'] for char in all_chars)
        }
        
        # Get font size (average)
        font_sizes = [char.get('size', 12) for char in all_chars if char.get('size')]
        avg_font_size = sum(font_sizes) / len(font_sizes) if font_sizes else 12
    else:
        bbox = {'l': 0, 't': 0, 'r': 0, 'b': 0}
        avg_font_size = 12
    
    return {
        'text': text,
        'boxes': [bbox],
        'font_size': avg_font_size
    }

def classify_content_type(text, font_size, fonts):
    """Classify content type based on text characteristics"""
    text_lower = text.lower().strip()
    
    if font_size > 14 or (len(text.split()) <= 10 and font_size > 11):
        if any(word in text_lower for word in ['chapter', 'section', 'introduction', 'conclusion']):
            return 'section_header'
        return 'header'
    
    if (text.startswith(('•', '-', '*', '1.', '2.', '3.')) or 
        any(line.strip().startswith(('•', '-', '*')) for line in text.split('\n'))):
        return 'list'
    
    lines = text.split('\n')
    if len(lines) > 1 and any('|' in line or '\t' in line for line in lines):
        return 'table'
    
    return 'paragraph'

def classify_chunk_type(text, font_size):
    """Simplified chunk classification"""
    text_lower = text.lower().strip()
    
    if font_size > 14:
        return 'header'
    elif text.startswith(('•', '-', '*', '1.', '2.')):
        return 'list'
    elif '\t' in text or '|' in text:
        return 'table'
    else:
        return 'paragraph'

def enhance_chunks_with_openai(chunks, openai_client):
    """Use OpenAI to enhance chunk classification and metadata"""
    try:
        batch_size = 5
        enhanced_chunks = []
        
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            
            # Prepare batch for analysis
            batch_texts = []
            for idx, chunk in enumerate(batch):
                batch_texts.append(f"Chunk {idx + 1}: {chunk['text'][:300]}")
            
            combined_text = "\n\n".join(batch_texts)
            
            prompt = f"""Analyze these PDF text chunks and classify each one:

{combined_text}

For each chunk, provide:
1. content_type: header, paragraph, list, table, or caption
2. importance: high, medium, or low
3. keywords: up to 3 relevant keywords

Respond in JSON format:
[{{"chunk": 1, "content_type": "...", "importance": "...", "keywords": ["..."]}}]"""

            try:
                response = openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=800,
                    temperature=0.1
                )
                
                ai_analysis = json.loads(response.choices[0].message.content)
                
                # Apply enhancements
                for j, chunk in enumerate(batch):
                    if j < len(ai_analysis):
                        ai_data = ai_analysis[j]
                        chunk['metadata']['ai_content_type'] = ai_data.get('content_type', chunk['metadata']['type'])
                        chunk['metadata']['importance'] = ai_data.get('importance', 'medium')
                        chunk['metadata']['keywords'] = ai_data.get('keywords', [])
                        chunk['metadata']['ai_enhanced'] = True
                    else:
                        chunk['metadata']['ai_enhanced'] = False
                    
                    enhanced_chunks.append(chunk)
                    
            except Exception as ai_error:
                print(f"OpenAI error for batch {i}: {str(ai_error)}")
                # Add without enhancement
                for chunk in batch:
                    chunk['metadata']['ai_enhanced'] = False
                    enhanced_chunks.append(chunk)
        
        return enhanced_chunks
        
    except Exception as e:
        print(f"Error in OpenAI enhancement: {str(e)}")
        for chunk in chunks:
            chunk['metadata']['ai_enhanced'] = False
        return chunks