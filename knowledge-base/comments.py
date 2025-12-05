"""
Archive of commented code from original app.py
This file contains legacy OCR/Computer Vision code that was commented out.
Preserved for future reference and potential reactivation.

Original context: Design-heavy PDF processing using OCR (pytesseract) and Computer Vision (OpenCV)
This approach was used for Canva-style PDFs with complex layouts before being commented out.
"""

# ==============================================================================
# LEGACY CODE: OCR-based Text Extraction and Region Detection
# ==============================================================================
# This section contains the original attempt to process design-heavy PDFs
# using OCR (pytesseract) and Computer Vision (OpenCV) to detect text and
# image regions separately, then map AI-generated semantic chunks to those regions.
#
# The approach involved:
# 1. OCR extraction with pytesseract to find text blocks with bounding boxes
# 2. Computer Vision contour detection to find non-text (image) regions
# 3. AI analysis to create semantic chunks
# 4. Mapping AI chunks to detected regions for precise coordinate grounding
#
# This code was replaced by a simpler approach but is preserved here for reference.
# ==============================================================================

# def detect_image_regions(image_b64):
#     """
#     Use computer vision to detect non-text regions (likely images/graphics)
#     """
#     # Decode image
#     image_data = base64.b64decode(image_b64)
#     image = Image.open(io.BytesIO(image_data))
#     img_array = np.array(image)
    
#     # Convert to grayscale
#     gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    
#     # Create text mask using OCR
#     ocr_data = pytesseract.image_to_data(img_array, output_type=pytesseract.Output.DICT)
#     text_mask = np.zeros(gray.shape, dtype=np.uint8)
    
#     # Fill text regions
#     for i in range(len(ocr_data['text'])):
#         if int(ocr_data['conf'][i]) > 30:
#             x, y, w, h = ocr_data['left'][i], ocr_data['top'][i], ocr_data['width'][i], ocr_data['height'][i]
#             cv2.rectangle(text_mask, (x, y), (x + w, y + h), 255, -1)
    
#     # Find non-text regions
#     non_text_mask = cv2.bitwise_not(text_mask)
    
#     # Find contours (potential image regions)
#     contours, _ = cv2.findContours(non_text_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
#     image_regions = []
#     min_area = 1000  # Minimum area for image regions
    
#     for contour in contours:
#         area = cv2.contourArea(contour)
#         if area > min_area:
#             x, y, w, h = cv2.boundingRect(contour)
            
#             # Normalize coordinates
#             img_height, img_width = gray.shape
#             image_regions.append({
#                 'box': {
#                     'l': x / img_width,
#                     't': y / img_height, 
#                     'r': (x + w) / img_width,
#                     'b': (y + h) / img_height
#                 },
#                 'area': area,
#                 'type': 'detected_image_region'
#             })
    
#     return image_regions

# # def get_layout_analysis(image_b64):
# #     """Use AI to identify text vs image regions with approximate coordinates"""
    
# #     layout_prompt = """Analyze this image and identify distinct regions:

# # 1. Text regions: Areas containing readable text
# # 2. Image regions: Photos, graphics, logos, charts
# # 3. Provide approximate bounding box coordinates as percentages (0-100)

# # Format your response as JSON:
# # {
# #   "regions": [
# #     {
# #       "type": "text|image|logo|graphic",
# #       "description": "brief description",
# #       "bbox": {"left": 10, "top": 20, "right": 90, "bottom": 50}
# #     }
# #   ]
# # }"""

# #     try:
# #         response = client.chat.completions.create(
# #             model="gpt-4o",
# #             messages=[
# #                 {"role": "system", "content": layout_prompt},
# #                 {
# #                     "role": "user",
# #                     "content": [
# #                         {"type": "text", "content": "Identify all regions in this image:"},
# #                         {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
# #                     ]
# #                 }
# #             ],
# #             response_format={"type": "json_object"},
# #             temperature=0.1
# #         )
        
# #         layout_data = json.loads(response.choices[0].message.content)
# #         return layout_data.get("regions", [])
        
# #     except Exception as e:
# #         print(f"[ERROR] Layout analysis failed: {e}")
# #         return []

# def extract_text_with_ocr(image_b64):
#     """
#     Extract text with bounding boxes using OCR
#     """
#     try:
#         # Decode base64 image
#         image_data = base64.b64decode(image_b64)
#         image = Image.open(io.BytesIO(image_data))
        
#         # Convert to numpy array for OpenCV
#         img_array = np.array(image)
        
#         # Use pytesseract to get detailed info
#         ocr_data = pytesseract.image_to_data(img_array, output_type=pytesseract.Output.DICT)
        
#         # Group words into text blocks
#         text_blocks = []
#         current_block = []
#         current_line = None
        
#         for i in range(len(ocr_data['text'])):
#             confidence = int(ocr_data['conf'][i])
#             text = ocr_data['text'][i].strip()
            
#             # Skip low confidence and empty text
#             if confidence < 30 or not text:
#                 continue
                
#             word_info = {
#                 'text': text,
#                 'left': ocr_data['left'][i],
#                 'top': ocr_data['top'][i], 
#                 'width': ocr_data['width'][i],
#                 'height': ocr_data['height'][i],
#                 'line_num': ocr_data['line_num'][i],    
#                 'block_num': ocr_data['block_num'][i],
#                 'confidence': confidence
#             }
            
#             # Group by block and line numbers
#             if (current_line is None or 
#                 ocr_data['line_num'][i] != current_line or 
#                 ocr_data['block_num'][i] != current_block):
                
#                 # Save previous block if it exists
#                 if current_block:
#                     text_blocks.append(current_block)
                
#                 # Start new block
#                 current_block = [word_info]
#                 current_line = ocr_data['line_num'][i]
#             else:
#                 current_block.append(word_info)
        
#         # Don't forget the last block
#         if current_block:
#             text_blocks.append(current_block)
        
#         # Convert to text chunks with bounding boxes
#         text_chunks = []
#         for block_idx, block in enumerate(text_blocks):
#             if not block:
#                 continue
                
#             # Combine all words in the block
#             text_parts = [word['text'] for word in block]
#             combined_text = ' '.join(text_parts)
            
#             if not combined_text.strip():
#                 continue
                
#             # Calculate block bounding box
#             left = min(word['left'] for word in block)
#             top = min(word['top'] for word in block) 
#             right = max(word['left'] + word['width'] for word in block)
#             bottom = max(word['top'] + word['height'] for word in block)
            
#             # Normalize coordinates (0-1 range)
#             img_width, img_height = image.size
            
#             # Calculate confidence score (average of all words in block)
#             avg_confidence = sum(word['confidence'] for word in block) / len(block)
            
#             text_chunks.append({
#                 'text': combined_text,
#                 'box': {
#                     'l': left / img_width,
#                     't': top / img_height,
#                     'r': right / img_width,
#                     'b': bottom / img_height
#                 },
#                 'type': 'text',
#                 'confidence': avg_confidence,
#                 'word_count': len(block),
#                 'block_id': f"ocr-block-{block_idx}"
#             })
        
#         print(f"[DEBUG] OCR extracted {len(text_chunks)} text blocks from image")
#         return text_chunks
        
#     except Exception as e:
#         print(f"[ERROR] OCR processing failed: {e}")
#         import traceback
#         traceback.print_exc()
#         return []
        
# def process_design_heavy_pdf_simplified(images, source_filename):
#     """Simplified design-heavy processing using OCR + Computer Vision only"""
    
#     all_chunks = []
#     all_text_regions = []  # ✅ Collect all text regions
#     all_image_regions = []  # ✅ Collect all image regions
    
#     for idx, image in enumerate(images):
#         page = image.get("page", 1)
#         image_b64 = image['image_b64']
        
#         print(f"[DEBUG] Processing design-heavy image from page {page}")
        
#         # Step 1: OCR to extract text regions with bounding boxes
#         try:
#             text_regions = extract_text_with_ocr(image_b64)
#             print(f"[DEBUG] Found {len(text_regions)} text regions via OCR")

#              # ✅ Add page info and collect text regions
#             for region in text_regions:
#                 region['source_page'] = page
#                 region['source_filename'] = source_filename
#             all_text_regions.extend(text_regions)

#         except Exception as e:
#             print(f"[WARN] OCR failed: {e}")
#             text_regions = []
        
#         # Step 2: Computer Vision to detect image regions  
#         try:
#             image_regions = detect_image_regions(image_b64)
#             print(f"[DEBUG] Found {len(image_regions)} image regions via CV")

#             # ✅ Add page info and collect image regions
#             for region in image_regions:
#                 region['source_page'] = page
#                 region['source_filename'] = source_filename
#             all_image_regions.extend(image_regions)
            
#         except Exception as e:
#             print(f"[WARN] Image detection failed: {e}")
#             image_regions = []
        
#         # Step 3: Add ONE comprehensive analysis of the full image
#         # (This replaces multiple region analyses)
#         try:
#             ai_result = analyze_image_with_region_validation(
#                 image_b64, page, text_regions, image_regions, source_filename
#             )
            
#             # Step 4: Map AI chunks to precise bounding boxes
#             page_chunks = map_ai_chunks_to_detected_regions(
#                 ai_result, text_regions, image_regions, page, source_filename
#             )
            
#             all_chunks.extend(page_chunks)
#             print(f"[DEBUG] Created {len(page_chunks)} validated chunks from page {page}")
            
#         except Exception as e:
#             print(f"[WARN] Full image analysis failed: {e}")

#         # ✅ Save extracted regions to separate files (simple approach)
#         try:
#             # Save text regions
#             with open("extracted_text_regions.json", "w") as f:
#                 json.dump(all_text_regions, f, indent=2)
#             print(f"[DEBUG] Saved {len(all_text_regions)} text regions to extracted_text_regions.json")
            
#             # Save image regions
#             with open("extracted_image_regions.json", "w") as f:
#                 json.dump(all_image_regions, f, indent=2)
#             print(f"[DEBUG] Saved {len(all_image_regions)} image regions to extracted_image_regions.json")
            
#             # Save processed chunks
#             with open("processed_chunks.json", "w") as f:
#                 json.dump(all_chunks, f, indent=2)
#             print(f"[DEBUG] Saved {len(all_chunks)} processed chunks to processed_chunks.json")

#         except Exception as save_error:
#             print(f"[ERROR] Failed to save extracted data: {save_error}")
            
#     return {
#         "chunks": all_chunks,
#         "processing_info": {
#             "method": "design_heavy_ocr_only",
#             "total_chunks": len(all_chunks),
#             "processed_at": datetime.now().isoformat()
#         }
#     }


# def analyze_full_design_image(image_b64, page, text_regions):
#     """Analyze the complete design-heavy image with context of extracted text"""
    
#     # Build context from OCR text
#     ocr_context = ""
#     if text_regions:
#         ocr_texts = [region['text'] for region in text_regions]
#         ocr_context = f"OCR extracted text: {' | '.join(ocr_texts)}"
    
#     prompt = f"""You are analyzing a design-heavy PDF page that contains both text and visual elements.

# **Context:**
# - Page {page} from a design-heavy document (likely Canva-made or similar)
# - {ocr_context}

# **Provide comprehensive analysis following your established format:**
# - Summary, Content Analysis, Technical Details, Spatial Relationships, Analysis & Interpretation
# - Focus on visual elements, layout, branding, and design choices
# - Note how text and visual elements work together
# - Describe the overall page design and purpose

# This analysis will be used in a knowledge base, so be thorough and descriptive."""

#     try:
#         response = client.chat.completions.create(
#             model="gpt-4o",
#             messages=[
#                 {"role": "system", "content": prompt},
#                 {
#                     "role": "user",
#                     "content": [
#                         {"type": "text", "text": f"Analyze this complete design page {page}:"},
#                         {
#                             "type": "image_url",
#                             "image_url": {"url": f"data:image/png;base64,{image_b64}"}
#                         }
#                     ]
#                 }
#             ],
#             temperature=0.1,
#             max_tokens=1500
#         )
        
#         return response.choices[0].message.content
        
#     except Exception as e:
#         return f"Visual analysis failed for page {page}: {str(e)}"

# def analyze_image_with_region_validation(image_b64, page, text_regions, image_regions, source_filename):
#     """
#     AI analysis that validates and maps to detected regions (simplified)
#     """
    
#     # Build context from detected regions (no bounding boxes)
#     text_context = ""
#     if text_regions:
#         text_summary = []
#         for idx, region in enumerate(text_regions):
#             text_summary.append(f"TextRegion{idx}: '{region['text'][:50]}...' (confidence: {region.get('confidence', 0):.1f})")
#         text_context = "OCR Detected Text Regions:\n" + "\n".join(text_summary)
    
#     image_context = ""
#     if image_regions:
#         image_summary = []
#         for idx, region in enumerate(image_regions):
#             # Keep minimal spatial info (area) for model decision making
#             image_summary.append(f"ImageRegion{idx}: area={region['area']} pixels, type={region.get('type', 'region')}")
#         image_context = "Computer Vision Detected Image Regions:\n" + "\n".join(image_summary)

#     validation_prompt = f"""You are analyzing a design-heavy PDF page. I have pre-detected regions using OCR and computer vision. Your task is to create semantic chunks while MAPPING to these detected regions.

# **Pre-detected Regions:**
# {text_context}

# {image_context}

# **Your Tasks:**
# 1. **Create semantic chunks** - group related elements logically  
# 2. **Map chunks to region indices** - specify which detected regions each chunk uses
# 3. **Validate meaningful content** - focus on regions that contain significant information

# **Output Format - Return valid JSON:**
# {{
#   "chunks": [
#     {{
#       "text": "extracted text or comprehensive visual description",
#       "metadata": {{
#         "type": "heading|paragraph|list|image|logo|graphic",
#         "section": "logical section name", 
#         "context": "one sentence describing purpose"
#       }},
#       "region_mapping": {{
#         "text_regions": [0, 1],
#         "image_regions": [0],
#         "validation_notes": "why these regions belong together"
#       }}
#     }}
#   ]
# }}

# **Region Mapping Rules:**
# - Map chunks to the EXACT region indices provided above (0, 1, 2, etc.)
# - For text chunks: match content to TextRegion indices by content similarity
# - For image chunks: reference ImageRegion indices that contain meaningful visual content
# - Group related regions into single semantic chunks when appropriate
# - Skip regions that contain only noise, decorative elements, or irrelevant content

# **Focus on:**
# - Creating fewer, more meaningful chunks rather than many small fragments
# - Grouping logically related content (headers with descriptions, logos with text, etc.)
# - Using region indices precisely for accurate coordinate mapping

# **Important:** Return your response as valid JSON format only."""

#     try:
#         response = client.chat.completions.create(
#             model="gpt-4o",
#             messages=[
#                 {"role": "system", "content": validation_prompt},
#                 {
#                     "role": "user",
#                     "content": [
#                         {"type": "text", "text": f"Create semantic chunks and map to regions for page {page}. Respond with JSON format:"},
#                         {
#                             "type": "image_url",
#                             "image_url": {"url": f"data:image/png;base64,{image_b64}"}
#                         }
#                     ]
#                 }
#             ],
#             response_format={"type": "json_object"},
#             temperature=0.1,
#             max_tokens=3000
#         )
        
#         result = json.loads(response.choices[0].message.content)
        
#         # Simplified return - just chunks
#         return {"chunks": result.get("chunks", [])}
        
#     except Exception as e:
#         print(f"[ERROR] Region validation analysis failed: {e}")
#         return {"chunks": []}

# def map_ai_chunks_to_detected_regions(ai_result, text_regions, image_regions, page, source_filename):
#     """
#     Map AI semantic chunks to detected regions with precise bounding boxes (simplified)
#     """
    
#     chunks_with_boxes = []
#     ai_chunks = ai_result.get("chunks", [])
    
#     print(f"[DEBUG] Mapping {len(ai_chunks)} AI chunks to detected regions")
#     print(f"[DEBUG] Available: {len(text_regions)} text regions, {len(image_regions)} image regions")
    
#     for chunk_idx, chunk in enumerate(ai_chunks):
#         try:
#             region_mapping = chunk.get("region_mapping", {})
#             mapped_text_indices = region_mapping.get("text_regions", [])
#             mapped_image_indices = region_mapping.get("image_regions", [])
            
#             # Build chunk with precise bounding boxes
#             chunk_boxes = []
#             chunk_text = chunk.get("text", "")
#             chunk_type = chunk.get("metadata", {}).get("type", "")
            
#             # Map text regions
#             for text_idx in mapped_text_indices:
#                 if 0 <= text_idx < len(text_regions):
#                     text_region = text_regions[text_idx]
#                     chunk_boxes.append(text_region['box'])
#                     print(f"[DEBUG] Mapped TextRegion{text_idx}: '{text_region['text'][:30]}...'")
#                 else:
#                     print(f"[WARN] Invalid text region index: {text_idx}")
            
#             # Map image regions  
#             for img_idx in mapped_image_indices:
#                 if 0 <= img_idx < len(image_regions):
#                     image_region = image_regions[img_idx]
#                     chunk_boxes.append(image_region['box'])
#                     print(f"[DEBUG] Mapped ImageRegion{img_idx} with area {image_region['area']}")
#                 else:
#                     print(f"[WARN] Invalid image region index: {img_idx}")
            
#             # Calculate encompassing bounding box
#             if chunk_boxes:
#                 combined_box = calculate_encompassing_bbox(chunk_boxes)
#             else:
#                 print(f"[WARN] No valid regions mapped for chunk {chunk_idx}")
#                 # Fallback to full page
#                 combined_box = {"l": 0, "t": 0, "r": 1, "b": 1}
            
#             # Create final chunk with precise grounding
#             final_chunk = {
#                 "text": chunk_text,
#                 "grounding": [{"box": combined_box, "page": page}],
#                 "chunk_type": chunk_type,
#                 "chunk_id": str(uuid.uuid4()),
#                 "rotation_angle": 0,
#                 "metadata": {
#                     **chunk.get("metadata", {}),
#                     "page": page,
#                     "continues": False,
#                     "is_page_break": False,
#                     "siblings": [],
#                     "row_index": None,
#                     "source_file": source_filename,
#                     "created_at": datetime.now().isoformat(),
#                     "processing_method": "ai_region_validated",
#                     "mapped_text_regions": mapped_text_indices,
#                     "mapped_image_regions": mapped_image_indices,
#                     "validation_notes": region_mapping.get("validation_notes", ""),
#                     "region_count": len(chunk_boxes),
#                     "box_source": "cv_ocr_mapped"
#                 }
#             }
            
#             chunks_with_boxes.append(final_chunk)
#             print(f"[DEBUG] Created chunk with {len(chunk_boxes)} mapped regions")
            
#         except Exception as e:
#             print(f"[ERROR] Failed to map chunk {chunk_idx}: {e}")
#             continue
    
#     return chunks_with_boxes

# def calculate_encompassing_bbox(bboxes):
#     """Calculate bounding box that encompasses all provided boxes"""
#     if not bboxes:
#         return {"l": 0, "t": 0, "r": 1, "b": 1}
    
#     min_l = min(bbox.get("l", 0) for bbox in bboxes)
#     min_t = min(bbox.get("t", 0) for bbox in bboxes)  
#     max_r = max(bbox.get("r", 1) for bbox in bboxes)
#     max_b = max(bbox.get("b", 1) for bbox in bboxes)
    
#     return {"l": min_l, "t": min_t, "r": max_r, "b": max_b}

# def analyze_image_for_semantic_chunks(image_b64, page, source_filename):
#     """
#     Have the model analyze the full image and create semantic chunks
#     """
    
#     prompt = f"""You are analyzing a design-heavy PDF page (likely made with Canva or similar tools) that contains both text and visual elements in a single composite image.

# Your task is to:
# 1. Identify all distinct content regions (text blocks, images, graphics, logos, etc.)
# 2. Group related elements semantically (e.g., header with subtitle, logo with tagline)
# 3. Create meaningful chunks that represent complete ideas or sections

# For each chunk you identify, provide:
# - **Text content**: Extract and transcribe any text, or describe visual elements
# - **Type**: heading, paragraph, list, image, logo, graphic, etc.
# - **Section**: Logical grouping or document section
# - **Context**: One sentence describing the chunk's purpose

# **Output Format:**
# {{
#   "chunks": [
#     {{
#       "text": "extracted text or visual description",
#       "metadata": {{
#         "type": "heading|paragraph|list|image|logo|graphic",
#         "section": "string (logical section name)",
#         "context": "string (one sentence max)"
#       }}
#     }}
#   ]
# }}

# **Guidelines:**
# - Group related elements (don't split headers from their descriptions)
# - Extract all readable text accurately
# - Describe visual elements comprehensively
# - Create fewer, more meaningful chunks rather than fragmenting content
# - Preserve the logical flow and hierarchy of the content"""

#     try:
#         response = client.chat.completions.create(
#             model="gpt-4o",
#             messages=[
#                 {"role": "system", "content": prompt},
#                 {
#                     "role": "user",
#                     "content": [
#                         {"type": "text", "text": f"Analyze this design page {page} and create semantic chunks:"},
#                         {
#                             "type": "image_url",
#                             "image_url": {"url": f"data:image/png;base64,{image_b64}"}
#                         }
#                     ]
#                 }
#             ],
#             response_format={"type": "json_object"},
#             temperature=0.1,
#             max_tokens=2000
#         )
        
#         result = json.loads(response.choices[0].message.content)
#         chunks = result.get("chunks", [])
        
#         # Add standard metadata to each chunk
#         for i, chunk in enumerate(chunks):
#             chunk["id"] = f"chunk-p{page}-{i}-{str(uuid.uuid4())[:8]}"
            
#             # Ensure metadata exists
#             if "metadata" not in chunk:
#                 chunk["metadata"] = {}
                
#             # Add standard fields
#             chunk["metadata"].update({
#                 "page": page,
#                 "continues": False,
#                 "is_page_break": False,
#                 "siblings": [],
#                 "row_index": None,
#                 "source_file": source_filename,
#                 "created_at": datetime.now().isoformat(),
#                 "processing_method": "semantic_grouping"
#             })
        
#         return chunks
        
#     except Exception as e:
#         print(f"[ERROR] Image analysis failed for page {page}: {e}")
#         return []

# ==============================================================================
# LEGACY ENDPOINT: Original /parse-pdf route
# ==============================================================================
# This was the first version of the parse-pdf endpoint before the full
# two-pass processing pipeline was implemented. It demonstrates the original
# anchoring approach.
# ==============================================================================

# @app.route('/parse-pdf', methods=['POST'])
# def parse_pdf():
#     if 'file' not in request.files:
#         return jsonify({"error": "No file part"}), 400
#     file = request.files['file']
#     if not file.filename or not file.filename.lower().endswith('.pdf'):
#         return jsonify({"error": "File is not a PDF"}), 400

#     source_filename = file.filename  # ✅ Capture the filename for metadata

#     try:
#         file_bytes = file.read()
#         structured = []
#         with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
#             for i, page in enumerate(pdf.pages):
#                 page_elems = assemble_elements(file_bytes, page, i)
#                 for el in page_elems:
#                     el["page"] = i + 1
#                     el["page_width"] = page.width
#                     el["page_height"] = page.height
#                 structured.extend(page_elems)

#         simplified = build_simplified_view_from_elements(structured)

#         # --- ✅ MERGED LOGIC: Apply Anchoring Immediately ---
#         # Load your existing chunked output (this simulates the GPT output)
#         try:
#             with open("sample_output.json", "r") as f:
#                 result = json.load(f)
#         except FileNotFoundError:
#             return jsonify({"error": "sample_output.json not found. Please ensure the file exists."}), 404

#         # Create empty image_bindings (since we're not calling GPT live)
#         image_bindings = []

#         # Apply anchoring with the real PDF structured data + filename
#         anchored_chunks = _anchor_chunks_to_pdf(
#             result.get("chunks", []),
#             structured,
#             image_bindings,
#             source_filename=source_filename
#         )

#         # Update the result with anchored chunks
#         result["chunks"] = anchored_chunks

#         # Add document-level metadata
#         result["document_metadata"] = {
#             "source_file": source_filename,
#             "processed_date": datetime.now().isoformat(),
#             "total_chunks": len(anchored_chunks),
#             "processing_version": "1.0",
#             "anchored_chunks": sum(1 for chunk in anchored_chunks if chunk.get("metadata", {}).get("anchored", False)),
#             "unanchored_chunks": sum(1 for chunk in anchored_chunks if not chunk.get("metadata", {}).get("anchored", False))
#         }

#         # Save the anchored result (optional, for debugging)
#         with open("anchored_output_V8.json", "w") as f:
#             json.dump(result, f, indent=2)

#         # Instead of returning simplified/structured, return the final anchored result
#         return jsonify(result), 200

#     except Exception as e:
#         import traceback
#         print("[ERROR]", traceback.format_exc())
#         return jsonify({"error": f"Internal server error: {str(e)}"}), 500

# ==============================================================================
# END OF ARCHIVED CODE
# ==============================================================================
