"""Service for AI-powered chunking of PDF content."""
import json
import re
import time
import uuid
from datetime import datetime
from openai import OpenAI
from config import Config
from schemas import JSON_SCHEMA, ENHANCED_CHUNKING_INSTRUCTIONS

# Layer 3: second-order injection defense for PDF text (guardrails.md §6).
# A malicious uploader can plant `### SYSTEM` / `<|im_start|>system` markers
# in PDF body text — those would otherwise be sent verbatim to OpenAI and
# persisted into Weaviate to attack every future chat. Tolerant import:
# the pdf_parse Lambda zip flat-packs `shared/` next to this file, but if
# sys.path isn't set up yet we degrade to no-op shims and log loudly so
# the issue is visible in CloudWatch.
try:
    from shared.guardrails import strip_injection_delimiters, wrap_untrusted_content
except ImportError as _e:
    print(f"[WARNING] Guardrails import failed in chunking_service: {_e}. "
          f"PDF content will NOT be sanitized — fix sys.path before relying on this!")

    def strip_injection_delimiters(text):  # type: ignore
        return text or ""

    def wrap_untrusted_content(text, source_label="untrusted content"):  # type: ignore
        return text or ""


def get_openai_client():
    """Get the OpenAI client instance."""
    Config.validate()
    return OpenAI(api_key=Config.OPENAI_API_KEY)


def _extract_usage(response):
    """
    Pull prompt / completion / cached token counts from an OpenAI response.

    Shape follows the supervisor-agent model-change guide §1 / §4: input_tokens
    INCLUDES cached_tokens (cached is a subset that gets the discounted rate).
    Returns a dict with keys: input_tokens, output_tokens, cached_tokens,
    total_tokens. All zero if usage isn't populated by the SDK.
    """
    usage = getattr(response, "usage", None)
    if not usage:
        return {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "total_tokens": 0}

    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", 0) or (input_tokens + output_tokens))

    cached_tokens = 0
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        if isinstance(details, dict):
            cached_tokens = int(details.get("cached_tokens", 0) or 0)
        else:
            cached_tokens = int(getattr(details, "cached_tokens", 0) or 0)

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "total_tokens": total_tokens,
    }


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

**COVERAGE — DO NOT DROP CONTENT:**
- Every meaningful line of input MUST appear in at least one chunk's `text`.
- Short standalone lines (effective dates, version numbers, document IDs,
  policy codes, headers, footers with regulatory references) are MEANINGFUL.
  If they don't fit any larger section, emit them as their own chunk with
  type="paragraph" and a descriptive context like
  "Document metadata: effective date".
- Headings (numbered or unnumbered) MUST always become their own chunk OR
  the leading line of a chunk that contains their content. Never silently
  fold a heading into an unrelated paragraph.
- When in doubt, emit a chunk. It is far better to over-chunk than to lose
  information.

**QUALITY STANDARDS:**
Good chunk: Complete metadata, clear hierarchy, searchable tags
Bad chunk: Missing parent_section, vague context, sparse tags, dropped lines

Begin processing. Output valid JSON only."""

    # Apply env-configurable input cap (was hard-coded 20K; default now 100K).
    # We track the original length and how much we sent so the lambda can
    # build fallback chunks for any text the AI never saw — see
    # `lambda_pdf_parse._build_fallback_chunks` for the consumer side.
    cap = max(1000, int(Config.CHUNKING_INPUT_CHAR_CAP or 100000))
    original_input_chars = len(clean_text)
    truncated_input = original_input_chars > cap
    if truncated_input:
        dropped = original_input_chars - cap
        print(
            f"[PDF Parse] WARNING: cleaned text {original_input_chars:,} chars "
            f"exceeds CHUNKING_INPUT_CHAR_CAP={cap:,}. Sending first {cap:,} "
            f"chars to chunker; {dropped:,} chars will be covered by the "
            f"fallback chunk pass."
        )
    sent_text = clean_text[:cap]
    safe_text = wrap_untrusted_content(
        sent_text,
        source_label="pdf document text",
    )
    messages = [
        {"role": "system", "content": text_prompt},
        {"role": "user", "content": safe_text},
    ]

    def _call_chunker(max_tok: int):
        """Single OpenAI call wrapper so we can retry with a bigger cap."""
        return client.chat.completions.create(
            model=Config.OPENAI_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=Config.TEMPERATURE,
            max_tokens=max_tok,
        )

    try:
        start_time = time.time()
        response = _call_chunker(Config.CHUNKING_OUTPUT_MAX_TOKENS)
        duration_ms = (time.time() - start_time) * 1000

        choice = response.choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        raw_content = choice.message.content or ""

        # If the model hit the output cap (`finish_reason == "length"`) the
        # JSON is almost certainly truncated mid-string and json.loads will
        # raise. Even if it parses, trailing chunks may be cut. Retry once
        # with a doubled cap (clamped to gpt-4.1's 32K output ceiling) so
        # long documents get a complete response.
        try:
            text_result = json.loads(raw_content)
            if finish_reason == "length":
                raise ValueError(
                    "chunker hit max_tokens cap — retrying with larger budget"
                )
        except (json.JSONDecodeError, ValueError) as parse_err:
            retry_budget = min(32768, max(Config.CHUNKING_OUTPUT_MAX_TOKENS * 2, 16384))
            print(
                f"[PDF Parse] WARNING: chunker output incomplete "
                f"(finish_reason={finish_reason}, err={parse_err}). "
                f"Retrying with max_tokens={retry_budget}..."
            )
            retry_start = time.time()
            response = _call_chunker(retry_budget)
            duration_ms += (time.time() - retry_start) * 1000
            choice = response.choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            text_result = json.loads(choice.message.content or "")
            if finish_reason == "length":
                print(
                    f"[PDF Parse] WARNING: chunker STILL hit max_tokens cap "
                    f"after retry. Trailing chunks may be missing — fallback "
                    f"pass will fill them in."
                )

        # Extract full token split (input/output/cached) for cost accounting —
        # the legacy `tokens_used` field is kept for back-compat with the merge
        # step and older analytics that only read total.
        usage = _extract_usage(response)
        tokens_used = usage["total_tokens"]
        chunks_count = len(text_result.get('chunks', []))

        print(
            f"[PDF Parse] Text-only processing: {chunks_count} chunks created in "
            f"{duration_ms:.0f}ms, in={usage['input_tokens']} out={usage['output_tokens']} "
            f"cached={usage['cached_tokens']} (total={tokens_used}), model={Config.OPENAI_MODEL}, "
            f"finish_reason={finish_reason}, sent_chars={len(sent_text):,}/{original_input_chars:,}"
        )

        text_result['tokens_used'] = tokens_used
        text_result['input_tokens'] = usage['input_tokens']
        text_result['output_tokens'] = usage['output_tokens']
        text_result['cached_tokens'] = usage['cached_tokens']
        text_result['model'] = Config.OPENAI_MODEL
        text_result['duration_ms'] = duration_ms
        text_result['truncated_input'] = truncated_input
        text_result['original_input_chars'] = original_input_chars
        text_result['sent_input_chars'] = len(sent_text)
        text_result['finish_reason'] = finish_reason

        return text_result

    except Exception as e:
        print(f"[ERROR] Text-only processing failed: {e}")
        return {
            "chunks": [],
            "tokens_used": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_tokens": 0,
            "model": Config.OPENAI_MODEL,
            "duration_ms": 0,
            "truncated_input": truncated_input,
            "original_input_chars": original_input_chars,
            "sent_input_chars": len(sent_text),
            "finish_reason": "error",
        }


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
        return {
            "chunks": [],
            "tokens_used": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_tokens": 0,
            "model": Config.OPENAI_MODEL,
            "duration_ms": 0,
        }
    
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
        
        # Extract surrounding text for context. Stripped of injection
        # delimiters because this is later f-string'd into a *system* prompt
        # (image_prompt below), so role markers planted in PDF body text
        # next to an image would flip the prompt hierarchy.
        context_start = max(0, marker_pos - 200)
        context_end = min(len(simplified_view), marker_pos + 200)
        context = strip_injection_delimiters(
            simplified_view[context_start:context_end]
        )

        image_contexts.append({
            "page": page,
            "left": left,
            "top": top,
            "right": right, 
            "bottom": bottom,
            "context": context,
            "marker_position": marker_pos
        })

    print(f"[PDF Parse] Found {len(image_contexts)} image markers in simplified view")
    print(f"[PDF Parse] Found {len(images)} images with base64 data")

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
        
        # Find exact match by page and coordinates
        for ctx_idx, ctx in enumerate(image_contexts):
            if (ctx["page"] == image_page and 
                ctx["left"] == image_left and 
                ctx["top"] == image_top and 
                ctx["right"] == image_right and 
                ctx["bottom"] == image_bottom):
                return ctx["context"]
        
        return "No surrounding text available"

    # Create lookup dictionary for images by ID for precise box retrieval
    images_by_id = {image.get("id", f"img-{idx}"): image for idx, image in enumerate(images)}

    # Track total tokens and duration across all image processing. Split
    # counts so we can apply the cached-tokens discount accurately per the
    # supervisor-agent guide — image analysis re-uses a long system prompt
    # across N images, so prompt caching on gpt-4.1 saves real money.
    total_image_tokens = 0
    total_image_input_tokens = 0
    total_image_output_tokens = 0
    total_image_cached_tokens = 0
    total_image_duration = 0

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
            
            # Track tokens for this image with full split for cache accounting.
            img_usage = _extract_usage(response)
            total_image_tokens += img_usage["total_tokens"]
            total_image_input_tokens += img_usage["input_tokens"]
            total_image_output_tokens += img_usage["output_tokens"]
            total_image_cached_tokens += img_usage["cached_tokens"]
            total_image_duration += img_duration_ms
            
            description = response.choices[0].message.content
            
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
            print(f"[PDF Parse] ✅ Processed image {idx+1} from page {page} in {img_duration_ms:.0f}ms")
            
        except Exception as e:
            print(f"[ERROR] Failed to process image {idx+1}: {e}")
            continue
    
    result = {
        "chunks": image_chunks,
        "tokens_used": total_image_tokens,
        "input_tokens": total_image_input_tokens,
        "output_tokens": total_image_output_tokens,
        "cached_tokens": total_image_cached_tokens,
        "model": Config.OPENAI_MODEL,
        "duration_ms": total_image_duration,
    }
    print(
        f"[PDF Parse] Image-only processing: {len(image_chunks)} image chunks, "
        f"in={total_image_input_tokens} out={total_image_output_tokens} "
        f"cached={total_image_cached_tokens} (total={total_image_tokens}), "
        f"model={Config.OPENAI_MODEL}"
    )
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
    
    # Aggregate token usage from both processing passes. Keep the legacy
    # total fields and add the split so the upstream lambda can compute cost
    # with the cached-tokens discount (see supervisor-agent guide §4).
    text_tokens = text_result.get("tokens_used", 0)
    image_tokens = image_result.get("tokens_used", 0)
    total_tokens = text_tokens + image_tokens

    text_input = text_result.get("input_tokens", 0)
    text_output = text_result.get("output_tokens", 0)
    text_cached = text_result.get("cached_tokens", 0)
    image_input = image_result.get("input_tokens", 0)
    image_output = image_result.get("output_tokens", 0)
    image_cached = image_result.get("cached_tokens", 0)

    total_input = text_input + image_input
    total_output = text_output + image_output
    total_cached = text_cached + image_cached

    text_duration = text_result.get("duration_ms", 0)
    image_duration = image_result.get("duration_ms", 0)
    total_duration = text_duration + image_duration

    result = {
        "chunks": all_chunks,
        "tokens_used": total_tokens,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cached_tokens": total_cached,
        "model": text_result.get("model") or image_result.get("model") or Config.OPENAI_MODEL,
        "duration_ms": total_duration,
        "processing_info": {
            "method": "two_pass",
            "text_chunks": len(text_chunks),
            "image_chunks": len(image_chunks),
            "total_chunks": len(all_chunks),
            "text_tokens": text_tokens,
            "image_tokens": image_tokens,
            "total_tokens": total_tokens,
            "text_input_tokens": text_input,
            "text_output_tokens": text_output,
            "text_cached_tokens": text_cached,
            "image_input_tokens": image_input,
            "image_output_tokens": image_output,
            "image_cached_tokens": image_cached,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cached_tokens": total_cached,
            "processed_at": datetime.now().isoformat()
        }
    }
    
    print(
        f"[PDF Parse] Merged result: {len(text_chunks)} text + {len(image_chunks)} image = "
        f"{len(all_chunks)} chunks, in={total_input} out={total_output} cached={total_cached} "
        f"(total={total_tokens})"
    )
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
    
    print(f"[PDF Parse] Simple detection: {image_count} images, {text_count} text, {total_elements} total")
    
    return is_design_heavy, confidence, reasons
