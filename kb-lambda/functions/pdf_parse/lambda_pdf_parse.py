"""
Lambda function for PDF parse endpoint.
POST /pdf/parse-pdf - Parse PDF file and extract structured chunks with full metadata.

Features retained from knowledge-base:
- Box coordinates for text lines, words, tables, and images
- Font metadata (size, bold, italic)
- Table extraction with bounding boxes
- Image extraction with base64 encoding and bboxes
- Spacing/line break detection
- Word-level bounding boxes
- Simplified view building with structure preservation

AI Processing Pipeline (when use_ai=true):
1. PDF Extraction - Extract text lines, tables, images with bounding boxes
2. Design-Heavy Detection - Identify document types
3. AI Text Chunking - Use OpenAI to create semantic chunks
4. AI Image Processing - Analyze images with vision AI
5. Chunk Merging - Combine text and image chunks in document order
6. PDF Anchoring - Map chunks back to PDF coordinates

Note: For large PDFs, use S3 pre-signed URLs for upload.
This endpoint handles the PDF parsing after file is uploaded to S3.
"""
import sys
import os
import io
import time
import uuid
import hashlib
import base64
import statistics
import json
from datetime import datetime
import pdfplumber
import fitz  # PyMuPDF
import boto3

# Add current directory to path for local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Add shared modules to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.response_utils import (
    success_response, error_response, unauthorized_response, 
    server_error_response, options_response, parse_body,
    validation_error_response, get_user_from_authorizer
)
from shared.db_utils import get_document_by_filename, get_document_by_hash, save_log
from shared.s3_utils import get_file, generate_upload_url

# Initialize AWS clients
s3_client = boto3.client('s3')
lambda_client = boto3.client('lambda')
dynamodb = boto3.resource('dynamodb')

# Get environment configuration
RESULTS_BUCKET = os.environ.get('RESULTS_BUCKET', os.environ.get('S3_BUCKET_NAME'))
LAMBDA_FUNCTION_NAME = os.environ.get('AWS_LAMBDA_FUNCTION_NAME', 'pdf-parse')
WEBSOCKET_ENDPOINT = os.environ.get('WEBSOCKET_ENDPOINT', '')
CONNECTIONS_TABLE = os.environ.get('CONNECTIONS_TABLE', 'KB_WebSocketConnections')

# Quota service configuration. PDF parse is intentionally:
#   1. NOT gated by /quota/check — uploads always proceed regardless of
#      the uploader's remaining balance.
#   2. Reported to /quota/report with `record_only: true` — UsageLogs gets
#      the full audit row (model, tokens, cost, file metadata) but the
#      uploader's UserQuotas.current_usage is NOT incremented. Document
#      processing therefore never drains the uploader's chat balance.
# tier='document' keeps document-tier costs analytically distinct from
# chat-tier costs in cost dashboards.
QUOTA_SERVICE_URL = os.environ.get('QUOTA_SERVICE_URL', '')
QUOTA_ENABLED = os.environ.get('QUOTA_ENABLED', 'true').lower() == 'true'

# Initialize connections table
connections_table = dynamodb.Table(CONNECTIONS_TABLE)

# httpx ships transitively with openai; guarded import so a misconfigured
# layer doesn't break basic PDF parsing (we just lose quota reporting).
try:
    import httpx as _httpx
except ImportError as _e:
    _httpx = None
    print(f"[WARN] httpx not available — quota reporting disabled: {_e}")

# Local imports for AI-powered PDF processing
try:
    from config import Config
    from chunking_service import (
        process_text_only,
        process_images_only,
        merge_text_and_image_chunks,
        is_design_heavy_simple as ai_is_design_heavy
    )
    from anchoring_service import anchor_chunks_to_pdf
    AI_MODULES_AVAILABLE = True
    print(f"[DEBUG] AI modules loaded successfully")
except ImportError as e:
    print(f"[WARN] AI modules not available: {e}")
    AI_MODULES_AVAILABLE = False


def report_pdf_usage(
    user_id: str,
    *,
    operation: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int,
    cost_usd: float,
    duration_ms: float = None,
    file_name: str = None,
    page_count: int = None,
    chunks_created: int = None,
    file_size_bytes: int = None,
    extraction_method: str = None,
    content_hash: str = None,
    request_id: str = None,
    success: bool = True,
    error: str = None,
):
    """Report PDF-parse LLM usage to the quota service in RECORD-ONLY mode.

    Per-spec, PDF parsing must NEVER be blocked AND must NEVER deduct from
    the uploader's quota balance. We achieve this with two independent
    mechanisms:

      1. No /quota/check call → no pre-flight gate, parsing always proceeds.
      2. /quota/report with `record_only: true` → quota service writes the
         row to UsageLogs (full audit trail: model, tokens, cost, file
         metadata) but SKIPS updating UserQuotas.current_usage. The
         uploader's chat balance is unaffected.

    `tier='document'` keeps document costs analytically distinct from chat
    costs in UsageLogs, so cost dashboards can split "what did the user
    spend on chat vs uploads" cleanly.

    Wraps in try/except internally — quota-service failures must never
    break the parse pipeline (the chunks are already saved to S3 by the
    time this is called).
    """
    if not QUOTA_ENABLED or not QUOTA_SERVICE_URL or _httpx is None:
        return

    if not user_id or not model:
        # /quota/report rejects requests without these — skip silently
        # rather than surface a 400 in CloudWatch on every parse.
        print(f"[Quota] Skipping report — missing user_id or model "
              f"(user_id={bool(user_id)}, model={bool(model)})")
        return

    # Service JWT headers — /api/quota/report is JWT-gated. Imported
    # lazily so a deploy lacking the service_jwt module still parses PDFs.
    try:
        from shared.service_jwt import service_auth_headers
        _auth_headers = service_auth_headers('kb-pdf-parse')
    except Exception:
        _auth_headers = {}

    try:
        with _httpx.Client(timeout=5.0) as client:
            response = client.post(
                f"{QUOTA_SERVICE_URL}/quota/report",
                json={
                    'user_id': user_id,
                    'service': 'knowledge-base',
                    'operation': operation,
                    'tier': 'document',
                    'model': model,
                    'input_tokens': int(input_tokens or 0),
                    'output_tokens': int(output_tokens or 0),
                    'cached_tokens': int(cached_tokens or 0),
                    'cost_usd': float(cost_usd or 0.0),
                    'duration_ms': float(duration_ms) if duration_ms is not None else None,
                    'success': bool(success),
                    'error': error,
                    'prompt_summary': (file_name or '')[:200],
                    'request_id': request_id,
                    # CRITICAL: record_only=True → audit row written, but
                    # uploader's UserQuotas balance NOT touched.
                    'record_only': True,
                    'metadata': {
                        'file_name': file_name,
                        'page_count': page_count,
                        'chunks_created': chunks_created,
                        'file_size_bytes': file_size_bytes,
                        'extraction_method': extraction_method,
                        'content_hash': content_hash,
                    },
                },
                headers=_auth_headers,
            )
            response.raise_for_status()
    except Exception as e:
        print(f"[Quota] PDF usage report warning: {e}")


# =============================================================================
# PDF EXTRACTION CORE FUNCTIONS (from knowledge-base/core/pdf_extractor.py)
# =============================================================================

def lines_from_chars(page, line_tol=5, word_tol=None):
    """
    Group page.chars into lines; return list of line dicts with
    text, bbox, font_size, style, spacing metadata, and per-word font info.
    """
    chars = sorted(
        page.chars,
        key=lambda c: (round(c.get("top", 0), 1), round(c.get("x0", 0), 1))
    )
    if not chars:
        return []
    
    # Calculate adaptive word tolerance if not provided
    if word_tol is None:
        font_sizes = [c.get("size", 12) for c in chars if c.get("size")]
        avg_font_size = statistics.median(font_sizes) if font_sizes else 12.0
        word_tol = avg_font_size * 0.4  # 40% of font size for word separation

    # --- group chars into lines
    lines = []
    current = [chars[0]]
    for ch in chars[1:]:
        if abs(ch.get("top", 0) - current[0].get("top", 0)) < line_tol:
            current.append(ch)
        else:
            lines.append(current)
            current = [ch]
    if current:
        lines.append(current)

    # --- build line objects
    line_objs = []
    prev_bottom = None

    # Get page number from page object for unique ID generation
    page_number = getattr(page, 'page_number', 1)

    for idx, ln in enumerate(lines):
        # Calculate line-specific word tolerance
        line_font_sizes = [c.get("size", 12) for c in ln if c.get("size")]
        line_avg_font = statistics.median(line_font_sizes) if line_font_sizes else 12.0
        line_word_tol = line_avg_font * 0.4  # Per-line adaptive tolerance

        # group chars into words within the line
        words = []
        current_word = [ln[0]]
        for ch in ln[1:]:
            prev = current_word[-1]
            gap = abs(ch.get("x0", 0) - prev.get("x1", 0))
            
            if gap > line_word_tol:
                words.append(current_word)
                current_word = [ch]
            else:
                current_word.append(ch)
        if current_word:
            words.append(current_word)

        word_objs = []
        for w in words:
            text = "".join(c.get("text", "") for c in w).strip()
            if not text:
                continue
            l = min(c.get("x0", 0) for c in w)
            t = min(c.get("top", 0) for c in w)
            r = max(c.get("x1", 0) for c in w)
            b = max(c.get("bottom", 0) for c in w)

            sizes = [float(c.get("size", 0)) for c in w if c.get("size") is not None]
            font_size = round(statistics.median(sizes), 2) if sizes else None

            fonts = [c.get("fontname", "") for c in w]
            bold = any("Bold" in f for f in fonts)
            italic = any("Italic" in f or "Oblique" in f for f in fonts)

            word_objs.append({
                "text": text,
                "box": {"l": l, "t": t, "r": r, "b": b},
                "font_size": font_size,
                "bold": bold,
                "italic": italic,
            })

        if not word_objs:
            continue

        l = min(w["box"]["l"] for w in word_objs)
        t = min(w["box"]["t"] for w in word_objs)
        r = max(w["box"]["r"] for w in word_objs)
        b = max(w["box"]["b"] for w in word_objs)

        # spacing metadata
        line_breaks_before = 0
        if prev_bottom is not None and (t - prev_bottom) > line_tol:
            line_breaks_before = 1
        prev_bottom = b

        # Generate unique line ID with page prefix
        unique_line_id = f"p{page_number}-ln-{idx}"

        line_objs.append({
            "id": unique_line_id,
            "type": "text",
            "text": " ".join(w["text"] for w in word_objs),
            "box": {"l": l, "t": t, "r": r, "b": b},
            "indent": l,
            "line_breaks_before": line_breaks_before,
            "line_breaks_after": 0,  # to be filled later
            "words": word_objs,
        })

    # --- fill line_breaks_after
    for i in range(len(line_objs) - 1):
        gap = line_objs[i+1]["box"]["t"] - line_objs[i]["box"]["b"]
        if gap > line_tol:
            line_objs[i]["line_breaks_after"] = 1

    return line_objs


def extract_tables_with_bbox(page):
    """
    Use page.find_tables() to get table objects and their bbox.
    Returns list of dicts: { type: 'table', 'table': rows, 'box': {l,t,r,b} }
    """
    tables = []
    found = page.find_tables()

    # Get page number for unique ID generation
    page_number = getattr(page, 'page_number', 1)

    for table_idx, t in enumerate(found):
        bbox = getattr(t, "bbox", None) or getattr(t, "_bbox", None)
        if bbox and len(bbox) == 4:
            l, ttop, r, btm = bbox
        else:
            # fallback: compute bbox from extracted table rows if possible, else skip
            rows = t.extract()
            if rows:
                try:
                    # collect text tokens, find their bounding boxes via page.extract_words
                    words = page.extract_words()
                    # naive fallback -> whole page dims
                    l, ttop, r, btm = 0, 0, page.width, page.height
                except Exception:
                    l, ttop, r, btm = 0, 0, page.width, page.height
            else:
                l, ttop, r, btm = 0, 0, page.width, page.height

        table_rows = t.extract()
        unique_table_id = f"p{page_number}-tbl-{table_idx}"

        tables.append({
            "id": unique_table_id,
            "type": "table",
            "table": table_rows,
            "box": {"l": l, "t": ttop, "r": r, "b": btm},
        })
    return tables


def line_intersects_bbox(line, bbox, margin=1.0):
    """
    Return True if line's vertical midpoint is inside bbox vertically and horizontally overlaps.
    margin: small tolerance
    """
    line_mid = (line["box"]["t"] + line["box"]["b"]) / 2.0
    tb_top, tb_bottom = bbox["t"] - margin, bbox["b"] + margin
    horiz_overlap = not (line["box"]["r"] < bbox["l"] or line["box"]["l"] > bbox["r"])
    return (tb_top <= line_mid <= tb_bottom) and horiz_overlap


def extract_images_with_bbox_pymupdf(file_bytes, page_number):
    """
    Uses xref placement rects to get true positions of images on the page.
    Returns list of dicts with unique IDs.
    """
    images = []
    with fitz.open(stream=file_bytes, filetype="pdf") as doc:
        page = doc[page_number]
        xref_rows = page.get_images(full=True)
        if not xref_rows:
            return images

        for img_index, row in enumerate(xref_rows):
            xref = row[0]
            rects = page.get_image_rects(xref)  # may return multiple placements
            try:
                pix = fitz.Pixmap(doc, xref)
                if pix.n > 4:  # convert CMYK/others to RGB
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                img_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
            except Exception as e:
                print(f"[WARN] xref={xref} pixmap failed: {e}")
                continue

            for placement_idx, rect in enumerate(rects):
                l, t, r, b = rect.x0, rect.y0, rect.x1, rect.y1
                unique_image_id = f"p{page_number+1}-img-{img_index}-{placement_idx}"
                images.append({
                    "id": unique_image_id,
                    "type": "image",
                    "subtype": "embedded",
                    "box": {"l": l, "t": t, "r": r, "b": b},
                    "page": page_number + 1,
                    "image_b64": img_b64,
                })
    return images


def assemble_elements(file_bytes, page, page_number):
    """
    Build ordered elements for the page:
    - get text lines (with font/style/spacing metadata)
    - get tables (with bbox)
    - get images (with bbox/base64)
    - remove lines that overlap table bboxes
    - combine into one list sorted by vertical position
    """
    text_lines = lines_from_chars(page)  # enriched with style + spacing + word-level info
    tables = extract_tables_with_bbox(page)
    images = extract_images_with_bbox_pymupdf(file_bytes, page_number)
    
    # --- Filter out text lines that overlap with any table bbox
    filtered_lines = []
    for ln in text_lines:
        in_any_table = any(line_intersects_bbox(ln, tb["box"]) for tb in tables)
        if not in_any_table:
            filtered_lines.append(ln)

    # --- Merge all elements into a unified list
    elements = []
    for ln in filtered_lines:
        elements.append({
            **ln,  # contains line-level text, box, spacing, and word-level list
            "page": page_number + 1,
            "top": ln["box"]["t"],
        })
    for tb in tables:
        elements.append({
            **tb,
            "page": page_number + 1,
            "top": tb["box"]["t"],
        })
    for im in images:
        elements.append({
            **im,
            "page": page_number + 1,
            "top": im["box"]["t"],
        })

    # --- Sort by top coordinate, fallback to left (chronological order)
    elements.sort(key=lambda e: (e["top"], e["box"].get("l", 0)))

    return elements


def build_simplified_view_from_elements(elements, gap_multiplier=1.5):
    """
    Build a simplified string preserving structure:
    - Preserve explicit line breaks (line_breaks_before/after) from extraction
    - Fallback to gap-based blank lines when explicit counts aren't present
    - Include a page header once per page
    - Place images inline at their positions with bbox info
    - Use inline markers for font size, bold, italic
    """
    lines_out = []

    # Group elements by page
    pages = {}
    for el in elements:
        page_no = el.get("page", 1)
        pages.setdefault(page_no, []).append(el)

    for page_no in sorted(pages.keys()):
        page_elems = pages[page_no]
        # Sort by visual order
        page_elems.sort(key=lambda e: (e.get("top", e["box"]["t"]), e["box"].get("l", 0)))

        # Median line height per page (gap fallback)
        heights = [
            (el["box"]["b"] - el["box"]["t"])
            for el in page_elems
            if el.get("type") == "text" and "box" in el
        ]
        median_height = statistics.median(heights) if heights else 12.0
        threshold = median_height * gap_multiplier

        # Page header (once)
        lines_out.append(f"[PAGE={page_no}]")

        prev_bottom = None
        active_size = None  # track active font size block

        for el in page_elems:
            top = el["box"]["t"]
            bottom = el["box"]["b"]

            # Explicit breaks BEFORE, else gap fallback
            lb_before = int(el.get("line_breaks_before", 0) or 0)
            if lb_before > 0:
                lines_out.extend([""] * lb_before)
            else:
                if prev_bottom is not None:
                    gap = top - prev_bottom
                    if gap > threshold:
                        lines_out.append("")

            if el["type"] == "text":
                words_out = []

                # Compute line font size (median of words)
                word_sizes = [w.get("font_size") for w in el.get("words", []) if w.get("font_size")]
                line_size = statistics.median(word_sizes) if word_sizes else None

                # Emit size tag when size changes
                if line_size and line_size != active_size:
                    if active_size:
                        words_out.append("</s>")
                    words_out.append(f"<s={int(line_size)}>")
                    active_size = line_size

                # Render words with style markers
                for w in el.get("words", []):
                    text = w.get("text", "")
                    bold = w.get("bold", False)
                    italic = w.get("italic", False)

                    if bold and italic:
                        words_out.append(f"*_ {text} _*")
                    elif bold:
                        words_out.append(f"*{text}*")
                    elif italic:
                        words_out.append(f"_{text}_")
                    else:
                        words_out.append(text)

                # Do not strip to preserve trailing spaces if present
                line_str = " ".join(words_out)
                lines_out.append(line_str)
                prev_bottom = bottom

            elif el["type"] == "table":
                lines_out.append("[TABLE]")
                for row in el.get("table", []):
                    lines_out.append(" | ".join(str(cell) for cell in row))
                lines_out.append("[/TABLE]")
                prev_bottom = bottom

            elif el["type"] == "image":
                bx = el.get("box", {})
                lines_out.append(
                    f"[IMAGE page={page_no} l={bx.get('l', 0):.1f} t={bx.get('t', 0):.1f} "
                    f"r={bx.get('r', 0):.1f} b={bx.get('b', 0):.1f}]"
                )
                prev_bottom = bottom

            # Explicit breaks AFTER
            lb_after = int(el.get("line_breaks_after", 0) or 0)
            if lb_after > 0:
                lines_out.extend([""] * lb_after)

        # Close active size at end of page
        if active_size:
            lines_out.append("</s>")
            active_size = None

        # Page separator
        lines_out.append("")

    # Trim trailing blanks
    while lines_out and lines_out[-1] == "":
        lines_out.pop()

    return "\n".join(lines_out)


def is_design_heavy_simple(structured):
    """
    Simple detection for design-heavy documents based on element ratios.
    
    Returns:
        tuple: (is_design_heavy: bool, confidence: float, reasons: list)
    """
    total_elements = len(structured)
    if total_elements == 0:
        return False, 0.0, ["No elements found"]
    
    image_count = len([el for el in structured if el.get("type") == "image"])
    table_count = len([el for el in structured if el.get("type") == "table"])
    text_count = len([el for el in structured if el.get("type") == "text"])
    
    image_ratio = image_count / total_elements if total_elements > 0 else 0
    
    reasons = []
    confidence = 0.0
    
    # High image ratio suggests design-heavy
    if image_ratio > 0.3:
        confidence += 0.4
        reasons.append(f"High image ratio: {image_ratio:.1%}")
    
    # Many images overall
    if image_count > 10:
        confidence += 0.2
        reasons.append(f"Many images: {image_count}")
    
    # Low text to image ratio
    if text_count > 0 and image_count / text_count > 0.5:
        confidence += 0.2
        reasons.append(f"High image/text ratio: {image_count}/{text_count}")
    
    is_design_heavy = confidence >= 0.4
    
    if not reasons:
        reasons.append("Standard document layout")
    
    return is_design_heavy, confidence, reasons


# =============================================================================
# LAMBDA HANDLER
# =============================================================================


def lambda_handler(event, context):
    """
    Parse PDF file and extract structured chunks with full metadata.
    
    Three modes:
    1. Request pre-signed URL for upload:
       POST /pdf/parse-pdf
       {"request_upload_url": true, "file_name": "doc.pdf"}
       
    2. Process PDF from S3 (async for AI processing):
       POST /pdf/parse-pdf
       {"s3_key": "uploads/user123/doc.pdf", "file_name": "doc.pdf", "use_ai": true}
       Returns: {"job_id": "...", "status": "processing"}
       
    3. Check job status:
       POST /pdf/parse-pdf
       {"check_status": true, "job_id": "..."}
       Returns: {"status": "complete|processing|failed", "result": {...}}
    
    For small files (< 5MB), can also accept base64:
       {"file_data": "base64...", "file_name": "doc.pdf"}
    
    Optional parameters:
       {"include_images": true}  - Include base64 image data (default: false)
       {"full_extraction": true} - Use full extraction with all metadata (default: true)
       {"use_ai": true}          - Use AI-powered chunking with OpenAI (default: false, triggers async)
    """
    # Handle CORS preflight
    if event.get('requestContext', {}).get('http', {}).get('method') == 'OPTIONS':
        return options_response()
    
    # Check if this is an async background invocation (no API Gateway context)
    is_background_task = 'requestContext' not in event
    
    if is_background_task:
        # This is an async Lambda invocation - process the AI job
        return process_ai_job_async(event)
    
    try:
        # Get user from API Gateway authorizer context
        try:
            user = get_user_from_authorizer(event)
            user_id = user['user_id']
        except Exception as e:
            return unauthorized_response(str(e))
        
        # Parse request body
        body = parse_body(event)
        
        # Mode 3: Check job status
        if body.get('check_status'):
            job_id = body.get('job_id')
            if not job_id:
                return validation_error_response("job_id is required for status check")
            return check_job_status(job_id)
        
        file_name = body.get('file_name', '').strip()
        if not file_name:
            return validation_error_response("file_name is required")
        
        # Options
        include_images = body.get('include_images', False)
        full_extraction = body.get('full_extraction', True)
        use_ai = body.get('use_ai', False)
        force_reparse = body.get('force_reparse', False)  # Override duplicate detection
        connection_id = body.get('connection_id')  # WebSocket connection for real-time updates
        
        # DEBUG: Log WebSocket configuration
        print(f"[PDF Parse DEBUG] connection_id from request: {connection_id}")
        print(f"[PDF Parse DEBUG] WEBSOCKET_ENDPOINT env var: {WEBSOCKET_ENDPOINT}")
        print(f"[PDF Parse DEBUG] WebSocket will be enabled: {bool(connection_id and WEBSOCKET_ENDPOINT)}")
        
        # Check AI availability
        if use_ai and not AI_MODULES_AVAILABLE:
            return error_response("AI processing is not available. Required modules not loaded.", 500)
        
        print(f"[PDF Parse] use_ai={use_ai}, AI_MODULES_AVAILABLE={AI_MODULES_AVAILABLE}")
        if use_ai:
            print(f"[PDF Parse] Will launch async AI processing for {file_name}")
        
        # Mode 1: Request pre-signed upload URL
        if body.get('request_upload_url'):
            upload_info = generate_upload_url(
                user_id=user_id,
                filename=file_name,
                content_type='application/pdf'
            )
            return success_response({
                'upload_url': upload_info['upload_url'],
                's3_key': upload_info['s3_key'],
                'expires_in': upload_info['expires_in'],
                'instructions': 'PUT your PDF file to the upload_url, then call this endpoint again with the s3_key'
            })
        
        # Get PDF content
        file_bytes = None
        s3_key = body.get('s3_key')
        file_data = body.get('file_data')  # Base64
        
        if s3_key:
            # Mode 2: Get from S3
            print(f"[PDF Parse] Reading PDF from S3: {s3_key}")
            try:
                file_bytes, metadata = get_file(s3_key)
                print(f"[PDF Parse] Got {len(file_bytes)} bytes from S3")
            except Exception as e:
                return error_response(f"Failed to read file from S3: {e}", 400)
                
        elif file_data:
            # Mode 3: Base64 encoded (for small files)
            try:
                file_bytes = base64.b64decode(file_data)
                print(f"[PDF Parse] Decoded {len(file_bytes)} bytes from base64")
            except Exception as e:
                return error_response(f"Invalid base64 data: {e}", 400)
        else:
            return validation_error_response(
                "Either s3_key or file_data is required. "
                "Use request_upload_url=true to get a pre-signed URL for large files."
            )
        
        # Calculate content hash
        content_hash = hashlib.sha256(file_bytes).hexdigest()
        
        # Check for duplicates (return 409 Conflict for frontend modal)
        # Skip duplicate check if force_reparse is enabled
        existing_by_name = None
        existing_by_hash = None
        
        if not force_reparse:
            existing_by_name = get_document_by_filename(file_name)
            existing_by_hash = get_document_by_hash(content_hash)
        
        if existing_by_hash:
            if existing_by_hash['file_name'] == file_name:
                # Exact duplicate - same file name and content
                return {
                    'statusCode': 409,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*',
                        'Access-Control-Allow-Headers': '*',
                        'Access-Control-Allow-Methods': '*'
                    },
                    'body': json.dumps({
                        'error': 'Duplicate document detected',
                        'detail': {
                            'duplicate': True,
                            'duplicate_type': 'exact',
                            'message': f"This exact file already exists as '{file_name}'",
                            'existing_doc': {
                                'doc_id': existing_by_hash['doc_id'],
                                'file_name': existing_by_hash['file_name'],
                                'uploaded_by': existing_by_hash.get('uploaded_by', 'Unknown'),
                                'upload_date': existing_by_hash.get('upload_date', 'Unknown'),
                                'chunks': existing_by_hash.get('chunks', 0),
                                'file_size_bytes': existing_by_hash.get('file_size_bytes', 0)
                            },
                            'suggestion': 'This exact document is already in the knowledge base.',
                            'cost_saved': 'Processing skipped - document already indexed'
                        }
                    })
                }
            else:
                # Content duplicate - same content, different file name
                return {
                    'statusCode': 409,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*',
                        'Access-Control-Allow-Headers': '*',
                        'Access-Control-Allow-Methods': '*'
                    },
                    'body': json.dumps({
                        'error': 'Duplicate content detected',
                        'detail': {
                            'duplicate': True,
                            'duplicate_type': 'content',
                            'message': f"This file content already exists as '{existing_by_hash['file_name']}'",
                            'existing_doc': {
                                'doc_id': existing_by_hash['doc_id'],
                                'file_name': existing_by_hash['file_name'],
                                'uploaded_by': existing_by_hash.get('uploaded_by', 'Unknown'),
                                'upload_date': existing_by_hash.get('upload_date', 'Unknown'),
                                'chunks': existing_by_hash.get('chunks', 0),
                                'file_size_bytes': existing_by_hash.get('file_size_bytes', 0)
                            },
                            'suggestion': 'The content is identical to an existing document with a different name.',
                            'cost_saved': 'Duplicate content detected - no reprocessing needed'
                        }
                    })
                }
        
        if existing_by_name:
            # Name duplicate - same file name, different content (version update scenario)
            return {
                'statusCode': 409,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Headers': '*',
                    'Access-Control-Allow-Methods': '*'
                },
                'body': json.dumps({
                    'error': 'Document name already exists',
                    'detail': {
                        'duplicate': True,
                        'duplicate_type': 'name',
                        'message': f"A file named '{file_name}' already exists. Click Override to create a new version.",
                        'existing_doc': {
                            'doc_id': existing_by_name['doc_id'],
                            'file_name': existing_by_name['file_name'],
                            'uploaded_by': existing_by_name.get('uploaded_by', 'Unknown'),
                            'upload_date': existing_by_name.get('upload_date', 'Unknown'),
                            'chunks': existing_by_name.get('chunks', 0),
                            'file_size_bytes': existing_by_name.get('file_size_bytes', 0),
                            'current_version': existing_by_name.get('current_version', 1)
                        },
                        'suggestion': 'Override will archive the current version and upload this as a new version.',
                        'cost_saved': None
                    }
                })
            }
        
        # FOR AI PROCESSING: Invoke async to avoid API Gateway timeout
        if use_ai:
            job_id = f"job-{uuid.uuid4().hex[:16]}"
            print(f"[PDF Parse] Launching async AI processing job: {job_id}")
            
            # Invoke self asynchronously for AI processing
            try:
                print(f"[PDF Parse] About to invoke async Lambda: {LAMBDA_FUNCTION_NAME}")
                lambda_client.invoke(
                    FunctionName=LAMBDA_FUNCTION_NAME,
                    InvocationType='Event',  # Async invocation
                    Payload=json.dumps({
                        'job_id': job_id,
                        's3_key': s3_key,
                        'file_name': file_name,
                        'user_id': user_id,
                        'content_hash': content_hash,
                        'include_images': include_images,
                        'force_reparse': force_reparse,  # Pass force_reparse to async job
                        'connection_id': connection_id,  # WebSocket connection for real-time updates
                        'async_ai_processing': True
                    })
                )
                print(f"[PDF Parse] Successfully invoked async processing for job: {job_id}")
                
                # Return immediately with job ID
                use_websocket = bool(connection_id and WEBSOCKET_ENDPOINT)
                print(f"[PDF Parse] Async response - connection_id: {connection_id}, WEBSOCKET_ENDPOINT: {WEBSOCKET_ENDPOINT}, use_websocket: {use_websocket}")
                return success_response({
                    'job_id': job_id,
                    'status': 'processing',
                    'message': 'AI processing started.' + (' Real-time updates via WebSocket.' if use_websocket else ' Use check_status=true with this job_id to check progress.'),
                    'use_websocket': use_websocket,
                    'estimated_time': '60-120 seconds',
                    'poll_interval': 5 if not use_websocket else None
                })
            except Exception as e:
                print(f"[PDF Parse] Failed to invoke async: {e}")
                return error_response(f"Failed to start async processing: {e}", 500)
        
        # Parse PDF - choose extraction method
        print(f"[PDF Parse] Parsing PDF with full_extraction={full_extraction}, use_ai={use_ai}...")
        try:
            if use_ai and AI_MODULES_AVAILABLE:
                # Full AI-powered processing pipeline
                result = parse_pdf_with_ai(file_bytes, file_name, include_images=include_images)
            elif full_extraction:
                result = parse_pdf_full(file_bytes, file_name, include_images=include_images)
            else:
                chunks, metadata = parse_pdf_simple(file_bytes, file_name)
                result = {
                    'chunks': chunks,
                    'document_metadata': metadata,
                    'extraction_method': 'simple'
                }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return error_response(f"Failed to parse PDF: {e}", 400)
        
        chunks = result.get('chunks', [])
        doc_metadata = result.get('document_metadata', {})
        
        print(f"[PDF Parse] Extracted {len(chunks)} chunks from {doc_metadata.get('page_count', 0)} pages")
        
        # Extract token/cost/duration info from result (AI processing).
        # Schema aligned with supervisor-agent `llm_calls` — input/output/cached
        # are additive; legacy `tokens_used`/`cost_usd` kept for back-compat.
        tokens_used = result.get('tokens_used', 0)
        input_tokens = result.get('input_tokens', 0)
        output_tokens = result.get('output_tokens', 0)
        cached_tokens = result.get('cached_tokens', 0)
        model_used = result.get('model')
        cost_usd = result.get('cost_usd', 0)
        duration_ms = result.get('duration_ms', 0)
        
        try:
            save_log('document', {
                'operation': 'parse',
                'tier': 'document',
                'model': model_used,
                'file_name': file_name,
                'file_size_bytes': len(file_bytes),
                'page_count': doc_metadata.get('page_count', 0),
                'chunks_created': len(chunks),
                'parsed_by': user_id,
                'extraction_method': result.get('extraction_method', 'full'),
                'tokens_used': tokens_used,
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'cached_tokens': cached_tokens,
                'cost_usd': cost_usd,
                'duration_ms': duration_ms,
                'success': True
            })
        except Exception as e:
            print(f"Logging warning: {e}")

        # Report to quota service. Only emits if there was actually an LLM
        # call (model_used != None and tokens > 0) — non-AI extractions
        # don't pollute UsageLogs with zero-token rows. Per spec, this
        # path is NEVER gated by /quota/check, so we always proceed even
        # if the user is over their balance.
        if model_used and (input_tokens or output_tokens):
            try:
                report_pdf_usage(
                    user_id,
                    operation='pdf_parse',
                    model=model_used,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_tokens=cached_tokens,
                    cost_usd=cost_usd,
                    duration_ms=duration_ms,
                    file_name=file_name,
                    page_count=doc_metadata.get('page_count', 0),
                    chunks_created=len(chunks),
                    file_size_bytes=len(file_bytes),
                    extraction_method=result.get('extraction_method', 'full'),
                    content_hash=content_hash,
                    request_id=event.get('requestContext', {}).get('requestId'),
                    success=True,
                )
            except Exception as quota_err:
                print(f"[Quota] PDF parse usage report error: {quota_err}")

        return success_response({
            'file_name': file_name,
            'content_hash': content_hash,
            'file_size_bytes': len(file_bytes),
            'page_count': doc_metadata.get('page_count', 0),
            'chunks': chunks,
            'total_chunks': len(chunks),
            'structured_elements': result.get('structured_elements', []),
            'simplified_view': result.get('simplified_view', ''),
            'extraction_summary': result.get('extraction_summary', {}),
            'document_metadata': doc_metadata,
            'processing_info': result.get('processing_info', {}),
            'tokens_used': tokens_used,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'cached_tokens': cached_tokens,
            'model': model_used,
            'cost_usd': cost_usd,
            # Echo back the source S3 key so the frontend can persist it on the
            # KB document. kb_delete uses this later to remove the original PDF
            # from S3 when the document is deleted (prevents orphaned uploads).
            # `None` for the base64 (file_data) path since there's no S3 object.
            's3_key': s3_key,
            'message': 'PDF parsed successfully. Use /kb/upload-to-kb to upload chunks to knowledge base.'
        })
        
    except Exception as e:
        print(f"Error parsing PDF: {e}")
        import traceback
        traceback.print_exc()
        return server_error_response(str(e))


def parse_pdf_full(file_bytes: bytes, file_name: str, include_images: bool = False) -> dict:
    """
    Full PDF parsing with complete extraction pipeline.
    Matches the functionality of knowledge-base/services/pdf_service.py
    
    Features:
    - Box coordinates for text lines, words, tables, and images
    - Font metadata (size, bold, italic)
    - Table extraction with bounding boxes
    - Image extraction with base64 encoding and bboxes
    - Spacing/line break detection
    - Word-level bounding boxes
    - Simplified view building with structure preservation
    - Design-heavy document detection
    
    Args:
        file_bytes: PDF file content as bytes
        file_name: Name of the source PDF file
        include_images: Whether to include base64 image data in response
        
    Returns:
        dict: Full result with structured elements, chunks, and metadata
    """
    from datetime import datetime
    
    # Wall-clock timer for the full extraction. Attached to `result` below
    # as `duration_ms` so save_log() in the calling context records the
    # actual time spent. Without this the synchronous parse path always
    # logged duration_ms=0, which made the LogsPage Document Analytics
    # "Avg Parse Time" tile render "N/A" forever (get_document_stats in
    # kb-lambda/shared/db_utils.py drops zero durations from the average).
    _t_parse_start = time.time()

    print(f"[PDF Parse] Processing file: {file_name}")

    structured = []
    page_count = 0

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        page_count = len(pdf.pages)
        
        for i, page in enumerate(pdf.pages):
            page_elems = assemble_elements(file_bytes, page, i)

            for el in page_elems:
                el["page"] = i + 1
                el["page_width"] = page.width
                el["page_height"] = page.height
            structured.extend(page_elems)

    simplified_view = build_simplified_view_from_elements(structured)
    print(f"[PDF Parse] Extracted structure: {len(structured)} elements")
    print(f"[PDF Parse] Simplified view length: {len(simplified_view)}")

    # Design-heavy detection
    is_design_heavy, confidence, reasons = is_design_heavy_simple(structured)
    print(f"[PDF Parse] Detection result: design_heavy={is_design_heavy} (confidence: {confidence:.1%})")
    for reason in reasons:
        print(f"[PDF Parse] - {reason}")

    # Collect images with base64 data
    images = []
    for el in structured:
        if el.get("type") == "image" and el.get("image_b64"):
            img_data = {
                "id": el.get("id", ""),
                "box": el.get("box", {}),
                "page": el.get("page", 1)
            }
            if include_images:
                img_data["image_b64"] = el["image_b64"]
            images.append(img_data)
    print(f"[PDF Parse] Found {len(images)} images")

    # Generate a pipeline_id for this document processing session
    pipeline_id = f"doc-{uuid.uuid4().hex[:12]}"
    print(f"[PDF Parse] Pipeline ID: {pipeline_id}")
    
    # Create chunks from structured elements
    # Each element becomes a chunk with full metadata
    chunks = []
    for idx, el in enumerate(structured):
        chunk = {
            "id": el.get("id", f"chunk-{idx}"),
            "type": el.get("type", "text"),
            "page": el.get("page", 1),
            "metadata": {
                "source": file_name,
                "page": el.get("page", 1),
                "page_width": el.get("page_width"),
                "page_height": el.get("page_height"),
                "box": el.get("box", {}),
                "pipeline_id": pipeline_id,
                "anchored": True  # All elements have box coordinates
            }
        }
        
        if el.get("type") == "text":
            chunk["text"] = el.get("text", "")
            chunk["metadata"]["indent"] = el.get("indent", 0)
            chunk["metadata"]["line_breaks_before"] = el.get("line_breaks_before", 0)
            chunk["metadata"]["line_breaks_after"] = el.get("line_breaks_after", 0)
            # Include word-level details
            chunk["metadata"]["words"] = el.get("words", [])
            
        elif el.get("type") == "table":
            # Convert table to text representation
            table_rows = el.get("table", [])
            table_text = ""
            for row in table_rows:
                row_text = " | ".join(str(cell) if cell else "" for cell in row)
                table_text += row_text + "\n"
            chunk["text"] = table_text.strip()
            chunk["metadata"]["table_data"] = table_rows
            
        elif el.get("type") == "image":
            chunk["text"] = f"[Image on page {el.get('page', 1)}]"
            chunk["metadata"]["subtype"] = el.get("subtype", "embedded")
            if include_images and el.get("image_b64"):
                chunk["metadata"]["image_b64"] = el["image_b64"]
        
        chunks.append(chunk)
    
    # Build extraction summary
    extraction_summary = {
        "total_elements": len(structured),
        "text_elements": len([el for el in structured if el.get("type") == "text"]),
        "table_elements": len([el for el in structured if el.get("type") == "table"]),
        "image_elements": len(images),
        "simplified_view_chars": len(simplified_view),
        "page_count": page_count
    }
    
    # Create final result with all metadata
    _duration_ms = int((time.time() - _t_parse_start) * 1000)
    result = {
        "chunks": chunks,
        "structured_elements": structured if include_images else _strip_image_data(structured),
        "simplified_view": simplified_view,
        "extraction_method": "full",
        # Wall-clock duration of the full extraction. The synchronous
        # entry point at lambda_handler reads result.get('duration_ms', 0)
        # and persists it onto the document save_log row; without this
        # field the Document Analytics "Avg Parse Time" tile stays N/A.
        "duration_ms": _duration_ms,
        "document_metadata": {
            "source_file": file_name,
            "processed_date": datetime.now().isoformat(),
            "total_chunks": len(chunks),
            "page_count": page_count,
            "processing_version": "lambda_v2.0",
            "processing_method": "full_extraction",
            "pipeline_id": pipeline_id,
            "duration_ms": _duration_ms,
            "design_heavy_detection": {
                "is_design_heavy": is_design_heavy,
                "confidence": confidence,
                "reasons": reasons
            }
        },
        "extraction_summary": extraction_summary
    }
    
    return result


def _strip_image_data(structured):
    """Remove base64 image data from structured elements to reduce response size."""
    result = []
    for el in structured:
        el_copy = {k: v for k, v in el.items() if k != "image_b64"}
        result.append(el_copy)
    return result


# Fallback grouping cap. We collapse consecutive un-matched lines on the
# same page into a single chunk so we don't flood Weaviate with hundreds of
# one-line "recovered text" entries — but we cap each fallback chunk at
# this many lines so a giant un-chunked region still ends up with multiple
# anchorable boxes (one per group).
_FALLBACK_LINES_PER_CHUNK = 15


def _build_fallback_chunks(structured, anchored_chunks, source_filename):
    """
    Emit recovery chunks for any text line in `structured` that no AI chunk
    matched. Without this, lines silently dropped by the chunker (input cap
    truncation, output cap truncation, prompt-driven over-merging, etc.)
    would never appear in the chunk list and never reach Weaviate.

    Strategy:
      1. Build set of matched_line_ids across every anchored chunk.
      2. Walk `structured` in document order; collect runs of consecutive
         text elements on the SAME page whose IDs are NOT in the matched set.
      3. Each run becomes one fallback chunk (capped at
         _FALLBACK_LINES_PER_CHUNK lines) with bbox = encompassing box of
         its lines and `metadata.processing_method = "fallback_recovery"`.

    Returns: list of new chunk dicts (may be empty).
    """
    matched_ids = set()
    for ch in anchored_chunks:
        for lid in (ch.get("metadata") or {}).get("matched_line_ids") or []:
            if lid:
                matched_ids.add(lid)

    fallback_chunks = []
    current_run = []
    current_page = None

    def _flush_run():
        if not current_run:
            return
        # Split overly long runs into smaller chunks so each fallback gets a
        # tight bbox and Weaviate doesn't end up with kitchen-sink chunks.
        for chunk_start in range(0, len(current_run), _FALLBACK_LINES_PER_CHUNK):
            slice_lines = current_run[chunk_start:chunk_start + _FALLBACK_LINES_PER_CHUNK]
            text = "\n".join(ln.get("text", "").strip() for ln in slice_lines if ln.get("text", "").strip())
            if not text:
                continue
            l = min(ln["box"]["l"] for ln in slice_lines)
            t = min(ln["box"]["t"] for ln in slice_lines)
            r = max(ln["box"]["r"] for ln in slice_lines)
            b = max(ln["box"]["b"] for ln in slice_lines)
            page = slice_lines[0].get("page", current_page or 1)
            line_ids = [ln.get("id", "") for ln in slice_lines if ln.get("id")]

            fallback_chunks.append({
                "id": f"fallback-{uuid.uuid4().hex[:12]}",
                "text": text,
                "metadata": {
                    "type": "paragraph",
                    "section": "",
                    "section_title": "",
                    "parent_section": "",
                    "context": "Recovered text not categorized by AI chunker",
                    "tags": ["recovered", "uncategorized"],
                    "continues": False,
                    "is_page_break": False,
                    "siblings": [],
                    "page": page,
                    "box": {"l": l, "t": t, "r": r, "b": b},
                    "anchored": True,
                    "matched_line_ids": line_ids,
                    "line_count": len(slice_lines),
                    "source_file": source_filename,
                    "created_at": datetime.now().isoformat(),
                    "processing_method": "fallback_recovery",
                },
            })

    for el in structured:
        if el.get("type") != "text":
            # A non-text element breaks the run (table or image between
            # paragraphs is a natural boundary).
            _flush_run()
            current_run = []
            current_page = None
            continue
        line_id = el.get("id", "")
        if not line_id or line_id in matched_ids:
            # Already covered by an AI chunk → flush the pending unmatched
            # run so we don't merge across covered lines.
            _flush_run()
            current_run = []
            current_page = None
            continue
        # Unmatched line. Open or extend a run on this page.
        page = el.get("page", 1)
        if current_page is None:
            current_page = page
        if page != current_page:
            _flush_run()
            current_run = []
            current_page = page
        current_run.append(el)

    _flush_run()

    if fallback_chunks:
        recovered_chars = sum(len(c["text"]) for c in fallback_chunks)
        print(
            f"[PDF Parse AI] Fallback recovery: produced {len(fallback_chunks)} "
            f"chunks covering {recovered_chars:,} chars of text the AI chunker "
            f"missed."
        )
    return fallback_chunks


def parse_pdf_with_ai(file_bytes: bytes, file_name: str, include_images: bool = False) -> dict:
    """
    Full AI-powered PDF parsing pipeline matching knowledge-base/services/pdf_service.py
    
    Pipeline:
    1. PDF Extraction - Extract text lines, tables, images with bounding boxes
    2. Design-Heavy Detection - Identify document types
    3. AI Text Chunking - Use OpenAI to create semantic chunks
    4. AI Image Processing - Analyze images with vision AI
    5. Chunk Merging - Combine text and image chunks in document order
    6. PDF Anchoring - Map chunks back to PDF coordinates
    
    Args:
        file_bytes: PDF file content as bytes
        file_name: Name of the source PDF file
        include_images: Whether to include base64 image data in response
        
    Returns:
        dict: Full result with AI-processed chunks and metadata
    """
    # Wall-clock timer for the full AI pipeline (extract + chunk + image
    # process + merge + anchor + fallback). Captured into the result
    # dict as `duration_ms` so the async/sync save_log() callers can
    # forward an accurate value to the document log row. Without this
    # the LogsPage "Avg Parse Time" tile renders N/A because every
    # parse log carries duration_ms=0.
    _t_parse_start = time.time()

    print(f"[PDF Parse AI] Processing file: {file_name}")

    structured = []
    page_count = 0

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        page_count = len(pdf.pages)
        
        for i, page in enumerate(pdf.pages):
            page_elems = assemble_elements(file_bytes, page, i)

            for el in page_elems:
                el["page"] = i + 1
                el["page_width"] = page.width
                el["page_height"] = page.height
            structured.extend(page_elems)

    simplified_view = build_simplified_view_from_elements(structured)
    print(f"[PDF Parse AI] Extracted structure: {len(structured)} elements")
    print(f"[PDF Parse AI] Simplified view length: {len(simplified_view)}")

    # Design-heavy detection using AI module or fallback
    try:
        is_design_heavy, confidence, reasons = ai_is_design_heavy(structured)
    except:
        is_design_heavy, confidence, reasons = is_design_heavy_simple(structured)
    
    print(f"[PDF Parse AI] Detection result: design_heavy={is_design_heavy} (confidence: {confidence:.1%})")
    for reason in reasons:
        print(f"[PDF Parse AI] - {reason}")

    # Collect images with base64 data for AI processing
    images = []
    for el in structured:
        if el.get("type") == "image" and el.get("image_b64"):
            images.append({
                "image_b64": el["image_b64"],
                "id": el.get("id", ""),
                "box": el.get("box", {}),
                "page": el.get("page", 1)
            })
    print(f"[PDF Parse AI] Found {len(images)} images with base64 data")

    # Generate a pipeline_id for this document processing session
    pipeline_id = f"doc-{uuid.uuid4().hex[:12]}"
    print(f"[PDF Parse AI] Pipeline ID: {pipeline_id}")

    # AI-powered text chunking
    print("[PDF Parse AI] Starting AI text chunking...")
    text_result = process_text_only(simplified_view, filename=file_name, pipeline_id=pipeline_id)
    print(f"[PDF Parse AI] Text chunking complete: {len(text_result.get('chunks', []))} chunks")

    # AI-powered image processing
    print("[PDF Parse AI] Starting AI image processing...")
    image_result = process_images_only(images, simplified_view, filename=file_name, pipeline_id=pipeline_id)
    print(f"[PDF Parse AI] Image processing complete: {len(image_result.get('chunks', []))} image chunks")

    # Merge chunks
    print("[PDF Parse AI] Merging text and image chunks...")
    merged_result = merge_text_and_image_chunks(
        text_result, 
        image_result, 
        simplified_view, 
        structured,
        file_name
    )
    print(f"[PDF Parse AI] Merged result: {len(merged_result.get('chunks', []))} total chunks")

    # Anchor chunks to PDF coordinates
    print("[PDF Parse AI] Anchoring chunks to PDF coordinates...")
    anchored_chunks = anchor_chunks_to_pdf(
        merged_result.get("chunks", []),
        structured
    )

    # Fallback recovery for any text line the AI never chunked. This used
    # to be the silent failure mode that lost short metadata lines
    # (effective dates, version numbers) and any content beyond the input
    # cap. We append fallback chunks BEFORE counting anchored vs un-anchored
    # so the final totals reflect actual coverage.
    fallback_chunks = _build_fallback_chunks(structured, anchored_chunks, file_name)
    if fallback_chunks:
        anchored_chunks.extend(fallback_chunks)

    anchored_count = sum(1 for chunk in anchored_chunks if chunk.get("metadata", {}).get("anchored", False))
    unanchored_count = len(anchored_chunks) - anchored_count
    fallback_count = len(fallback_chunks)
    print(
        f"[PDF Parse AI] Anchoring complete: {anchored_count} anchored, "
        f"{unanchored_count} unanchored, {fallback_count} fallback-recovered"
    )

    # Build extraction summary
    extraction_summary = {
        "total_elements": len(structured),
        "text_elements": len([el for el in structured if el.get("type") == "text"]),
        "table_elements": len([el for el in structured if el.get("type") == "table"]),
        "image_elements": len(images),
        "simplified_view_chars": len(simplified_view),
        "page_count": page_count
    }

    # Extract token usage from merged result
    tokens_used = merged_result.get("tokens_used", 0)
    input_tokens = merged_result.get("input_tokens", 0)
    output_tokens = merged_result.get("output_tokens", 0)
    cached_tokens = merged_result.get("cached_tokens", 0)
    model_used = merged_result.get("model", Config.OPENAI_MODEL)
    processing_duration_ms = merged_result.get("duration_ms", 0)

    # Cost via the shared pricing table with cached-tokens discount applied
    # (supervisor-agent guide §1 / §4). Falls back to a conservative blended
    # rate only if the shared module can't be imported for some reason (e.g.
    # layer misconfig) — far better than the old 0.02 flat guess which was
    # off by 2-5x depending on model.
    try:
        # Lambda layer / package root puts `shared/` on sys.path.
        from shared.openai_utils import estimate_cost as _estimate_cost
        cost_usd = _estimate_cost(
            input_tokens,
            output_tokens,
            model_used,
            cached_tokens=cached_tokens,
        )
    except Exception as cost_err:
        print(f"[PDF Parse AI] Pricing table unavailable ({cost_err}), using blended fallback")
        # Conservative gpt-4.1 blended rate (~50/50 split assumption).
        _in_rate = 0.002 / 1000
        _out_rate = 0.008 / 1000
        _cached_rate = _in_rate * 0.25  # 75% off
        _non_cached_in = max(input_tokens - cached_tokens, 0)
        if input_tokens or output_tokens:
            cost_usd = (
                _non_cached_in * _in_rate
                + cached_tokens * _cached_rate
                + output_tokens * _out_rate
            )
        else:
            # Legacy path: only `tokens_used` is available (shouldn't happen
            # after chunking_service changes, but keep the safety net).
            cost_usd = (tokens_used / 1000) * 0.005

    # Create final result with all metadata.
    # `duration_ms` is the wall-clock total of this entire function call
    # (extract → chunk → image-process → merge → anchor → fallback →
    # cost-estimate). The local `processing_duration_ms` captured above
    # from `merged_result` only covers the merge step, so we prefer the
    # outer wall-clock for the `duration_ms` we expose on `result` —
    # downstream save_log() calls forward it as the canonical parse
    # duration that powers the LogsPage Avg Parse Time tile.
    _duration_ms = int((time.time() - _t_parse_start) * 1000)
    result = {
        "chunks": anchored_chunks,
        "structured_elements": _strip_image_data(structured) if not include_images else structured,
        "simplified_view": simplified_view,
        "extraction_method": "ai_two_pass",
        "tokens_used": tokens_used,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "model": model_used,
        "cost_usd": cost_usd,
        "duration_ms": _duration_ms,
        "document_metadata": {
            "source_file": file_name,
            "processed_date": datetime.now().isoformat(),
            "total_chunks": len(anchored_chunks),
            "page_count": page_count,
            "processing_version": "lambda_v2.0_ai",
            "processing_method": "ai_two_pass",
            "pipeline_id": pipeline_id,
            "anchored_chunks": anchored_count,
            "unanchored_chunks": unanchored_count,
            "fallback_chunks": fallback_count,
            "chunker_truncated_input": text_result.get("truncated_input", False),
            "chunker_finish_reason": text_result.get("finish_reason"),
            "chunker_input_chars": text_result.get("sent_input_chars"),
            "chunker_input_chars_total": text_result.get("original_input_chars"),
            "tokens_used": tokens_used,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached_tokens,
            "model": model_used,
            "cost_usd": cost_usd,
            "duration_ms": _duration_ms,
            "design_heavy_detection": {
                "is_design_heavy": is_design_heavy,
                "confidence": confidence,
                "reasons": reasons
            }
        },
        "processing_info": merged_result.get("processing_info", {}),
        "extraction_summary": extraction_summary
    }

    print(
        f"[PDF Parse AI] Processing complete! in={input_tokens} out={output_tokens} "
        f"cached={cached_tokens} (total={tokens_used}), model={model_used}, "
        f"cost=${cost_usd:.4f}"
    )
    return result


def parse_pdf_simple(file_bytes: bytes, file_name: str) -> tuple:
    """
    Simple PDF parsing using pdfplumber.
    
    For production, consider using the full pdf_service with
    chunking, table extraction, etc.
    
    Returns:
        tuple: (chunks, metadata)
    """
    import pdfplumber
    
    chunks = []
    page_count = 0
    
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        page_count = len(pdf.pages)
        
        for page_num, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            
            if text.strip():
                # Simple chunking by page
                chunks.append({
                    'text': text.strip(),
                    'page': page_num,
                    'section': f"Page {page_num}",
                    'metadata': {
                        'source': file_name,
                        'page': page_num,
                        'char_count': len(text)
                    }
                })
    
    metadata = {
        'page_count': page_count,
        'total_chars': sum(len(c['text']) for c in chunks)
    }
    
    return chunks, metadata


# =============================================================================
# WEBSOCKET HELPERS
# =============================================================================

def get_apigw_client():
    """Create API Gateway Management API client for WebSocket messaging."""
    if not WEBSOCKET_ENDPOINT:
        return None
    return boto3.client('apigatewaymanagementapi', endpoint_url=WEBSOCKET_ENDPOINT)


def send_ws_message(connection_id, message):
    """Send a message to a WebSocket client."""
    if not connection_id or not WEBSOCKET_ENDPOINT:
        return False
    
    try:
        apigw = get_apigw_client()
        if not apigw:
            return False
            
        apigw.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(message).encode('utf-8')
        )
        print(f"[WebSocket] Sent message to {connection_id}: {message.get('type', 'unknown')}")
        return True
    except Exception as e:
        print(f"[WebSocket] Error sending to {connection_id}: {e}")
        return False


# =============================================================================
# ASYNC PROCESSING HELPERS
# =============================================================================

def process_ai_job_async(event):
    """
    Background async handler for AI processing.
    This runs outside API Gateway timeout constraints.
    Sends real-time updates via WebSocket if connection_id is provided.
    """
    job_id = event.get('job_id')
    s3_key = event.get('s3_key')
    file_name = event.get('file_name')
    user_id = event.get('user_id')
    content_hash = event.get('content_hash')
    include_images = event.get('include_images', False)
    connection_id = event.get('connection_id')  # WebSocket connection
    
    # DEBUG: Detailed WebSocket debugging
    print(f"[Async AI Job {job_id}] DEBUG - connection_id received: {connection_id}")
    print(f"[Async AI Job {job_id}] DEBUG - WEBSOCKET_ENDPOINT: {WEBSOCKET_ENDPOINT}")
    print(f"[Async AI Job {job_id}] DEBUG - connection_id type: {type(connection_id)}")
    print(f"[Async AI Job {job_id}] DEBUG - WEBSOCKET_ENDPOINT type: {type(WEBSOCKET_ENDPOINT)}")
    print(f"[Async AI Job {job_id}] DEBUG - connection_id bool: {bool(connection_id)}")
    print(f"[Async AI Job {job_id}] DEBUG - WEBSOCKET_ENDPOINT bool: {bool(WEBSOCKET_ENDPOINT)}")
    
    use_websocket = bool(connection_id and WEBSOCKET_ENDPOINT)
    print(f"[Async AI Job {job_id}] Starting processing for {file_name}, WebSocket: {use_websocket}")
    print(f"[Async AI Job {job_id}] AI_MODULES_AVAILABLE: {AI_MODULES_AVAILABLE}")
    print(f"[Async AI Job {job_id}] Event data: s3_key={s3_key}, user_id={user_id}, include_images={include_images}")
    
    def send_progress(status, message, progress=None, extra_data=None):
        """Send progress update via WebSocket and/or S3."""
        data = {'message': message}
        if progress is not None:
            data['progress'] = progress
        if extra_data:
            data.update(extra_data)
        
        # Save to S3 (for polling fallback)
        save_job_status(job_id, status, data)
        
        # Send via WebSocket if available
        if use_websocket:
            ws_message = {
                'type': 'pdf_progress',
                'job_id': job_id,
                'status': status,
                'message': message,
                'progress': progress,
                'file_name': file_name
            }
            if extra_data:
                ws_message.update(extra_data)
            send_ws_message(connection_id, ws_message)
    
    try:
        # Step 1: Download PDF
        send_progress('processing', 'Downloading PDF from S3...', 10)
        file_bytes, metadata = get_file(s3_key)
        print(f"[Async AI Job {job_id}] Downloaded {len(file_bytes)} bytes")
        
        # Step 2: Extract PDF structure
        send_progress('processing', 'Extracting PDF structure...', 20)
        
        # Step 3: Run AI analysis
        send_progress('processing', 'Running AI text analysis...', 40)
        print(f"[Async AI Job {job_id}] About to call parse_pdf_with_ai with {len(file_bytes)} bytes")
        ai_start_time = datetime.now()
        result = parse_pdf_with_ai(file_bytes, file_name, include_images=include_images)
        ai_duration = (datetime.now() - ai_start_time).total_seconds()
        print(f"[Async AI Job {job_id}] AI processing completed in {ai_duration:.2f} seconds")
        print(f"[Async AI Job {job_id}] AI result keys: {list(result.keys()) if result else 'None'}")
        
        send_progress('processing', 'Anchoring chunks to PDF coordinates...', 80)
        
        # Step 4: Add file_size_bytes, content_hash, and s3_key to result for
        # frontend to use in upload. s3_key is forwarded so kb_upload can
        # persist it on the KB_Documents row, which lets kb_delete later
        # remove the original PDF from S3 (prevents orphaned uploads/).
        result['file_size_bytes'] = len(file_bytes)
        result['content_hash'] = content_hash
        result['s3_key'] = s3_key
        
        # Step 5: Save result to S3 (with file_size_bytes and content_hash included)
        result_key = f"results/{job_id}.json"
        s3_client.put_object(
            Bucket=RESULTS_BUCKET,
            Key=result_key,
            Body=json.dumps(result),
            ContentType='application/json'
        )
        print(f"[Async AI Job {job_id}] Result saved to s3://{RESULTS_BUCKET}/{result_key}")
        
        # Step 6: Send completion
        completion_data = {
            'result_s3_key': result_key,
            'file_name': file_name,
            'total_chunks': result.get('document_metadata', {}).get('total_chunks', 0),
            'page_count': result.get('document_metadata', {}).get('page_count', 0)
        }
        
        # Save final status to S3
        save_job_status(job_id, 'complete', completion_data)
        
        # Send completion via WebSocket with full result (already includes file_size_bytes and content_hash)
        if use_websocket:
            ws_complete = {
                'type': 'pdf_complete',
                'job_id': job_id,
                'status': 'complete',
                'file_name': file_name,
                'total_chunks': completion_data['total_chunks'],
                'page_count': completion_data['page_count'],
                'result': result  # Send full result via WebSocket
            }
            send_ws_message(connection_id, ws_complete)
        
        # Extract token/cost/duration info from AI processing result.
        # Schema aligned with supervisor-agent `llm_calls` (additive).
        tokens_used = result.get('tokens_used', 0)
        input_tokens = result.get('input_tokens', 0)
        output_tokens = result.get('output_tokens', 0)
        cached_tokens = result.get('cached_tokens', 0)
        model_used = result.get('model')
        cost_usd = result.get('cost_usd', 0)
        duration_ms = result.get('duration_ms', 0)
        
        try:
            save_log('document', {
                'operation': 'ai_parse_async',
                'tier': 'document',
                'model': model_used,
                'job_id': job_id,
                'file_name': file_name,
                'file_size_bytes': len(file_bytes),
                'chunks_created': completion_data['total_chunks'],
                'page_count': completion_data['page_count'],
                'parsed_by': user_id,
                'use_websocket': use_websocket,
                'tokens_used': tokens_used,
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'cached_tokens': cached_tokens,
                'cost_usd': cost_usd,
                'duration_ms': duration_ms,
                'success': True
            })
        except Exception as e:
            print(f"Logging warning: {e}")

        # Async path mirrors the sync path: NEVER gated by /quota/check, but
        # ALWAYS reported to /quota/report so document costs show up in the
        # uploader's UsageLogs alongside chat costs.
        if model_used and (input_tokens or output_tokens):
            try:
                report_pdf_usage(
                    user_id,
                    operation='pdf_parse_async',
                    model=model_used,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_tokens=cached_tokens,
                    cost_usd=cost_usd,
                    duration_ms=duration_ms,
                    file_name=file_name,
                    page_count=completion_data.get('page_count', 0),
                    chunks_created=completion_data.get('total_chunks', 0),
                    file_size_bytes=len(file_bytes),
                    extraction_method='ai_two_pass',
                    content_hash=content_hash,
                    request_id=job_id,
                    success=True,
                )
            except Exception as quota_err:
                print(f"[Async AI Job {job_id}] Quota report error: {quota_err}")

        print(f"[Async AI Job {job_id}] Completed successfully")
        return {'statusCode': 200, 'body': json.dumps({'status': 'complete'})}
        
    except Exception as e:
        print(f"[Async AI Job {job_id}] Failed: {e}")
        import traceback
        traceback.print_exc()
        
        error_data = {
            'error': str(e),
            'error_type': type(e).__name__
        }
        
        # Save error to S3
        save_job_status(job_id, 'failed', error_data)
        
        # Send error via WebSocket
        if use_websocket:
            send_ws_message(connection_id, {
                'type': 'pdf_error',
                'job_id': job_id,
                'status': 'failed',
                'file_name': file_name,
                'error': str(e),
                'error_type': type(e).__name__
            })

        # Per supervisor-agent guide §8.5: log failures with the same shape
        # as the success path so success-rate dashboards stay accurate.
        try:
            save_log('document', {
                'operation': 'ai_parse_async',
                'tier': 'document',
                'job_id': job_id,
                'file_name': file_name,
                'parsed_by': user_id,
                'use_websocket': use_websocket,
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__,
            })
        except Exception as log_err:
            print(f"[Async AI Job {job_id}] Failure logging warning: {log_err}")

        return {'statusCode': 500, 'body': json.dumps({'status': 'failed', 'error': str(e)})}


def save_job_status(job_id, status, data=None):
    """Save job status to S3."""
    status_key = f"job-status/{job_id}.json"
    status_data = {
        'job_id': job_id,
        'status': status,
        'updated_at': datetime.now().isoformat(),
        **(data or {})
    }
    
    s3_client.put_object(
        Bucket=RESULTS_BUCKET,
        Key=status_key,
        Body=json.dumps(status_data),
        ContentType='application/json'
    )


def check_job_status(job_id):
    """Check the status of an async job."""
    print(f"[Job Status Check] Looking for job: {job_id}")
    try:
        status_key = f"job-status/{job_id}.json"
        print(f"[Job Status Check] Checking S3 key: {status_key}")
        response = s3_client.get_object(Bucket=RESULTS_BUCKET, Key=status_key)
        status_data = json.loads(response['Body'].read())
        print(f"[Job Status Check] Found status data: {status_data}")
        
        status = status_data.get('status')
        
        if status == 'complete':
            # Get the result
            result_key = status_data.get('result_s3_key')
            print(f"[Job Status Check] Job complete, result key: {result_key}")
            if result_key:
                result_response = s3_client.get_object(Bucket=RESULTS_BUCKET, Key=result_key)
                result = json.loads(result_response['Body'].read())
                print(f"[Job Status Check] Returning cached result with {len(result.get('chunks', []))} chunks")
                
                return success_response({
                    'status': 'complete',
                    'job_id': job_id,
                    'result': result,
                    'file_name': status_data.get('file_name'),
                    'total_chunks': status_data.get('total_chunks'),
                    'page_count': status_data.get('page_count')
                })
        
        elif status == 'failed':
            return success_response({
                'status': 'failed',
                'job_id': job_id,
                'error': status_data.get('error'),
                'error_type': status_data.get('error_type')
            })
        
        else:  # processing
            return success_response({
                'status': 'processing',
                'job_id': job_id,
                'message': status_data.get('message', 'Processing...'),
                'updated_at': status_data.get('updated_at')
            })
    
    except s3_client.exceptions.NoSuchKey:
        print(f"[Job Status Check] Job {job_id} not found in S3")
        return error_response(f"Job {job_id} not found", 404)
    except Exception as e:
        print(f"[Job Status Check] Error checking job status: {e}")
        return server_error_response(str(e))
