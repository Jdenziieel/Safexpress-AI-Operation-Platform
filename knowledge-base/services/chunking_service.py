"""Service for AI-powered chunking of PDF content."""
import json
import re
import time
import uuid
from datetime import datetime
from services.openai_service import get_openai_client
from models.schemas import JSON_SCHEMA, ENHANCED_CHUNKING_INSTRUCTIONS
from utils.file_utils import save_json
from config import Config
from utils.kb_logger import KBLogger
from utils.token_tracker import TokenTracker, estimate_cost

# Initialize logger and token tracker
kb_logger = KBLogger()
token_tracker = TokenTracker()


def process_text_only(simplified_view, filename: str = None, pipeline_id: str = None):
    """
    First pass: Process text content only for structural analysis
    
    Args:
        simplified_view: The simplified text view of the document
        filename: Original filename for logging
        pipeline_id: Pipeline ID for grouping all operations on this document
    """
    client = get_openai_client()
    
    # Remove image markers from simplified_view for clean text processing
    image_pat = re.compile(r"\[IMAGE\s+page=(\d+)\s+l=([\d.]+)\s+t=([\d.]+)\s+r=([\d.]+)\s+b=([\d.]+)\]")
    clean_text = image_pat.sub("[IMAGE_PLACEHOLDER]", simplified_view)
    
    # Enhanced text-only prompt with strict instructions
    text_prompt = f"""You are an expert PDF document analyzer that creates structured, searchable chunks.

**YOUR MISSION:**
Transform unstructured document text into perfectly structured, searchable JSON chunks that enable precise information retrieval.

**CORE PRINCIPLES:**
1. **Preserve Document Hierarchy**: Maintain section relationships (parent-child)
2. **Rich Metadata**: Every chunk must have complete, accurate metadata
3. **Search-Friendly**: Tags and context must enable keyword AND semantic search
4. **Consistency**: Apply the same standards across ALL document types

**OUTPUT SCHEMA:**
{JSON_SCHEMA}

{ENHANCED_CHUNKING_INSTRUCTIONS}

**PROCESSING WORKFLOW:**

Step 1: Identify Document Structure
- Locate all section headings (SECTION 1, 1.1, Chapter 1, etc.)
- Map parent-child relationships (3.1 is child of 3)
- Identify content types (lists, tables, paragraphs)

Step 2: Create Meaningful Chunks
- Group related content (heading + description, list items together)
- Keep tables intact (don't split rows across chunks)
- Preserve context (subsection content includes parent section info)

Step 3: Enrich Metadata
- Extract ALL relevant keywords for tags (5-7 per chunk)
- Write descriptive context (what information does this contain?)
- Fill section, section_title, parent_section consistently

Step 4: Quality Check
- Every subsection (3.1) MUST have parent_section="3"
- Tags include both specific terms AND parent section topics
- Context describes content, not just restates the title
- Type matches actual content structure

**IMPORTANT REMINDERS:**
- Ignore [IMAGE_PLACEHOLDER] markers (processed separately)
- Strip formatting markers (*bold*, _italic_, <s=XX>)
- Preserve line breaks and list structure in text field
- Max one sentence for context (15 words or less)

**QUALITY STANDARDS:**
✅ Good chunk: Complete metadata, clear hierarchy, searchable tags
❌ Bad chunk: Missing parent_section, vague context, sparse tags

Begin processing. Output valid JSON only."""

    messages = [
        {"role": "system", "content": text_prompt},
        {"role": "user", "content": clean_text[:20000]}  # Limit text size
    ]
    
    try:
        start_time = time.time()
        response = client.chat.completions.create(
            model=Config.OPENAI_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=Config.TEMPERATURE
        )
        duration_ms = (time.time() - start_time) * 1000
        
        text_result = json.loads(response.choices[0].message.content)
        
        # Log the LLM call for document processing
        tokens_used = response.usage.total_tokens if response.usage else 0
        cost = estimate_cost(Config.OPENAI_MODEL, total_tokens=tokens_used)
        chunks_count = len(text_result.get('chunks', []))
        kb_logger.log_llm_call(
            pipeline_type="document_processing",
            stage="text_chunking",
            model=Config.OPENAI_MODEL,
            tokens=tokens_used,
            cost=cost,
            success=True,
            filename=filename,
            chunks_created=chunks_count,
            pipeline_id=pipeline_id,
            duration_ms=duration_ms
        )
        
        # Save text-only result
        save_json(text_result, "text_only_chunks.json")
        
        print(f"[DEBUG] Text-only processing: {chunks_count} chunks created in {duration_ms:.0f}ms")
        return text_result
        
    except Exception as e:
        # Log the error
        kb_logger.log_llm_call(
            pipeline_type="document_processing",
            stage="text_chunking",
            model=Config.OPENAI_MODEL,
            tokens=0,
            cost=0,
            success=False,
            error=str(e),
            filename=filename,
            pipeline_id=pipeline_id
        )
        print(f"[ERROR] Text-only processing failed: {e}")
        return {"chunks": []}


def process_images_only(images, simplified_view, filename: str = None, pipeline_id: str = None):
    """
    Second pass: Process images separately with rich context
    
    Args:
        images: List of images to process
        simplified_view: The simplified text view of the document
        filename: Original filename for logging
        pipeline_id: Pipeline ID for grouping all operations on this document
    """
    client = get_openai_client()
    
    if not images:
        return {"chunks": []}
    
    image_chunks = []
    image_pat = re.compile(r"\[IMAGE\s+page=(\d+)\s+l=([\d.]+)\s+t=([\d.]+)\s+r=([\d.]+)\s+b=([\d.]+)\]")
    
    # Store context for each individual marker
    image_contexts = []
    for match in image_pat.finditer(simplified_view):
        page = int(match.group(1))
        left = float(match.group(2))
        top = float(match.group(3))
        right = float(match.group(4))
        bottom = float(match.group(5))
        marker_pos = match.start()
        
        # Extract surrounding text for context
        context_start = max(0, marker_pos - 200)
        context_end = min(len(simplified_view), marker_pos + 200)
        context = simplified_view[context_start:context_end]
        
        image_contexts.append({
            "page": page,
            "left": left,
            "top": top,
            "right": right, 
            "bottom": bottom,
            "context": context,
            "marker_position": marker_pos
        })
    
    # Save image_context result for debugging
    save_json(image_contexts, "image_context.json")

    print(f"[DEBUG] Found {len(image_contexts)} image markers in simplified view")
    print(f"[DEBUG] Found {len(images)} images with base64 data")

    # Helper function to match image to context by coordinates
    def find_matching_context(image):
        """Find matching context by page and rounded coordinates"""
        image_page = image.get("page", 1)
        image_box = image.get("box", {})
        
        # Round image coordinates to 1 decimal to match simplified view format
        image_left = round(image_box.get("l", 0), 1)
        image_top = round(image_box.get("t", 0), 1)
        image_right = round(image_box.get("r", 0), 1)
        image_bottom = round(image_box.get("b", 0), 1)
        
        print(f"[DEBUG] Looking for image: page={image_page}, l={image_left}, t={image_top}, r={image_right}, b={image_bottom}")
        
        # Find exact match by page and coordinates
        for ctx_idx, ctx in enumerate(image_contexts):
            if (ctx["page"] == image_page and 
                ctx["left"] == image_left and 
                ctx["top"] == image_top and 
                ctx["right"] == image_right and 
                ctx["bottom"] == image_bottom):
                
                print(f"[DEBUG] ✅ Exact match found with context {ctx_idx}")
                return ctx["context"]
        
        print(f"[DEBUG] ❌ No exact coordinate match found for image")
        return "No surrounding text available"

    # Create lookup dictionary for images by ID for precise box retrieval
    images_by_id = {image.get("id", f"img-{idx}"): image for idx, image in enumerate(images)}
    print(f"[DEBUG] Created image lookup with {len(images_by_id)} entries")

    # Process each image with its matching context
    for idx, image in enumerate(images):
        page = image.get("page", 1)
        image_id = image.get("id", f"img-{idx}")
        context_text = find_matching_context(image)
        
        image_prompt = f"""Analyze this image in the context of a PDF document.

                        **Surrounding Text Context:**
                        {context_text}

                        **Your task:**
                        1. Describe the image comprehensively
                        2. Identify its purpose and relationship to surrounding text
                        3. Extract any text visible in the image
                        4. Classify the image type (logo, diagram, chart, photo, etc.)

                        **Response format:** Provide a detailed description suitable for a knowledge base chunk."""

        try:
            # Process single image with timing
            img_start_time = time.time()
            response = client.chat.completions.create(
                model=Config.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": image_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"Analyze this image from page {page}:"},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{image['image_b64']}"}
                            }
                        ]
                    }
                ],
                temperature=Config.TEMPERATURE
            )
            img_duration_ms = (time.time() - img_start_time) * 1000
            
            description = response.choices[0].message.content
            
            # Log the vision LLM call
            tokens_used = response.usage.total_tokens if response.usage else 0
            cost = estimate_cost(Config.OPENAI_MODEL, total_tokens=tokens_used)
            kb_logger.log_llm_call(
                pipeline_type="document_processing",
                stage="image_analysis",
                model=Config.OPENAI_MODEL,
                tokens=tokens_used,
                cost=cost,
                success=True,
                filename=filename,
                chunks_created=1,
                pipeline_id=pipeline_id,
                duration_ms=img_duration_ms
            )
            
            # Get precise bounding box from original image data
            original_image = images_by_id.get(image_id)
            precise_box = original_image.get("box", {}) if original_image else {}
            
            # Create image chunk
            image_chunk = {
                "text": description,
                "metadata": {
                    "type": "image",
                    "section": "Visual Content",
                    "context": f"Image from page {page}",
                    "tags": ["image", "visual"],
                    "page": page,
                    "continues": False,
                    "is_page_break": False,
                    "siblings": [],
                    "row_index": "",
                    "image_id": image_id,
                    "box": precise_box,
                    "anchored": True if precise_box else False
                }
            }
            
            image_chunks.append(image_chunk)
            print(f"[DEBUG] ✅ Processed image {idx+1} from page {page}")
            
        except Exception as e:
            # Log error for image processing
            kb_logger.log_llm_call(
                pipeline_type="document_processing",
                stage="image_analysis",
                model=Config.OPENAI_MODEL,
                tokens=0,
                cost=0,
                success=False,
                error=str(e),
                filename=filename,
                pipeline_id=pipeline_id
            )
            print(f"[ERROR] Failed to process image {idx+1}: {e}")
            continue
    
    result = {"chunks": image_chunks}
    
    # Save image-only result
    save_json(result, "image_only_chunks.json")
    
    print(f"[DEBUG] Image-only processing: {len(image_chunks)} image chunks created")
    return result


def merge_text_and_image_chunks(text_result, image_result, simplified_view, structured, source_filename):
    """
    Merge text and image chunks back into proper document order
    """
    text_chunks = text_result.get("chunks", [])
    image_chunks = image_result.get("chunks", [])
    
    # Create position mapping for image chunks
    image_pat = re.compile(r"\[IMAGE\s+page=(\d+)\s+l=([\d.]+)\s+t=([\d.]+)\s+r=([\d.]+)\s+b=([\d.]+)\]")
    image_positions = []
    
    for match in image_pat.finditer(simplified_view):
        page = int(match.group(1))
        position = match.start()
        image_positions.append({
            "page": page,
            "position": position,
            "marker_text": match.group(0)
        })
    
    # Sort image chunks by page and position
    for i, img_chunk in enumerate(image_chunks):
        if i < len(image_positions):
            img_chunk["_sort_position"] = image_positions[i]["position"]
            img_chunk["_sort_page"] = image_positions[i]["page"]
    
    # Create text position estimates (rough)
    total_text_length = len(simplified_view)
    for i, text_chunk in enumerate(text_chunks):
        # Estimate position based on chunk order
        estimated_position = (i / len(text_chunks)) * total_text_length if text_chunks else 0
        text_chunk["_sort_position"] = estimated_position
        
        # Find page by searching for chunk text in simplified_view
        chunk_text = text_chunk.get("text", "")[:50]  # First 50 chars
        text_pos = simplified_view.find(chunk_text)
        if text_pos != -1:
            # Count page markers before this position
            page_markers = len(re.findall(r'\[PAGE=(\d+)\]', simplified_view[:text_pos]))
            text_chunk["_sort_page"] = max(1, page_markers)
        else:
            text_chunk["_sort_page"] = text_chunk.get("metadata", {}).get("page", 1)
    
    # Combine and sort all chunks
    all_chunks = text_chunks + image_chunks
    all_chunks.sort(key=lambda x: (x.get("_sort_page", 1), x.get("_sort_position", 0)))
    
    # Clean up temporary sorting fields
    for chunk in all_chunks:
        chunk.pop("_sort_position", None)
        chunk.pop("_sort_page", None)
    
    # Generate unique IDs and add metadata
    for i, chunk in enumerate(all_chunks):
        chunk["id"] = f"chunk-{i}-{str(uuid.uuid4())[:8]}"
        if "metadata" not in chunk:
            chunk["metadata"] = {}
        
        chunk["metadata"]["source_file"] = source_filename
        chunk["metadata"]["created_at"] = datetime.now().isoformat()
        chunk["metadata"]["processing_method"] = "two_pass"
    
    result = {
        "chunks": all_chunks,
        "processing_info": {
            "method": "two_pass",
            "text_chunks": len(text_chunks),
            "image_chunks": len(image_chunks),
            "total_chunks": len(all_chunks),
            "processed_at": datetime.now().isoformat()
        }
    }
    
    print(f"[DEBUG] Merged result: {len(text_chunks)} text + {len(image_chunks)} image = {len(all_chunks)} total chunks")
    return result


def is_design_heavy_simple(structured_data):
    """
    Simple detection: check if PDF is mostly images with little text content
    Only reads 'type' field to avoid processing large image_b64 data
    """
    if not structured_data:
        return False, 0.0, ["No structured data provided"]
    
    image_count = 0
    text_count = 0
    total_elements = 0
    
    # Count element types efficiently
    for element in structured_data:
        element_type = element.get("type")
        if element_type:
            total_elements += 1
            if element_type == "image":
                image_count += 1
            elif element_type == "text":
                text_count += 1
    
    if total_elements == 0:
        return False, 0.0, ["No valid elements found"]
    
    # Calculate ratios
    image_ratio = image_count / total_elements
    text_ratio = text_count / total_elements
    
    # Simple decision logic
    is_design_heavy = False
    confidence = 0.0
    reasons = []
    
    # High image ratio indicates design-heavy
    if image_ratio > 0.7:  # 70%+ images
        is_design_heavy = True
        confidence = 0.9
        reasons.append(f"High image ratio: {image_ratio:.1%} ({image_count}/{total_elements})")
    elif image_ratio > 0.5:  # 50%+ images
        is_design_heavy = True
        confidence = 0.7
        reasons.append(f"Moderate-high image ratio: {image_ratio:.1%} ({image_count}/{total_elements})")
    
    # Very few text elements also indicates design-heavy
    if text_count < 5:
        is_design_heavy = True
        confidence = max(confidence, 0.8)
        reasons.append(f"Very few text elements: {text_count}")
    
    # Override: if no images at all, definitely not design-heavy
    if image_count == 0:
        is_design_heavy = False
        confidence = 0.9
        reasons = [f"No images found, only {text_count} text elements"]
    
    # Summary reason
    if is_design_heavy:
        reasons.insert(0, f"DESIGN-HEAVY detected (confidence: {confidence:.1%})")
    else:
        reasons.insert(0, f"STANDARD PDF detected (confidence: {1-confidence:.1%})")
    
    print(f"[DEBUG] Simple detection: {image_count} images, {text_count} text, {total_elements} total")
    
    return is_design_heavy, confidence, reasons
